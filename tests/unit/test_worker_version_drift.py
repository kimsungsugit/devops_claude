"""배포된 워커 exe 가 **소스와 어긋난 걸** 감지한다.

`dist/excel_rename_gui_v2.exe` 는 `.gitignore` 대상이라 `cloudium_worker/worker.py` 를
고쳐도 **배포본은 그대로**다. 그 어긋남은 아무 신호도 안 낸다 — 게이트는 초록이고
read 도 되는데 고친 동작만 빠져 있다.

2026-08-19 실측: `allow_reuse_address` 를 껐는데 도는 exe 는 옛 판이라 **포트
가로채기가 여전히 가능**했다. 눈으로는 못 잡는다.

계약:
  · 기대값은 **소스 상수를 직접 읽는다**(`cloudium_worker.worker.WORKER_VERSION`).
    두 벌로 적으면 그것부터 갈라진다.
  · 어긋나면 `version_check="stale_exe"` + 경고. 프로그램이 읽을 수 있는 신호여야
    한다 — 로그 문구만 바꾸면 호출부·UI 는 여전히 모른다.
  · 조회 실패는 **모른다고 말한다**(`unavailable`). 낡음/최신 어느 쪽으로도 단정 않는다.
  · **평상시 경로(`already_running`)에도** 붙어야 한다. spawn 쪽에만 달면 재기동해도
    낡은 exe 를 영영 못 본다.
"""

from __future__ import annotations

import json
import socket
import socketserver
import threading

import pytest

from backend.services import cloudium_worker_launcher as L


class _FakeWorker(socketserver.StreamRequestHandler):
    version = "1.0"

    def handle(self):
        try:
            self.rfile.readline()
            self.wfile.write(
                json.dumps({"id": "v", "ok": True, "result": self.version}).encode()
                + b"\n")
            self.wfile.flush()
        except OSError:
            pass


@pytest.fixture
def fake_worker():
    """지정한 버전을 답하는 가짜 워커. 반환 (port, set_version)."""
    class _S(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = False

    handler = type("_H", (_FakeWorker,), {"version": "1.0"})
    srv = _S(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield port, (lambda v: setattr(handler, "version", v))
    srv.shutdown()
    srv.server_close()
    t.join(timeout=2)


def _point_at(monkeypatch, port):
    monkeypatch.setattr("backend.services.file_resolver._worker_endpoint",
                        lambda: ("127.0.0.1", port))


class TestVersionReport:
    def test_match_when_versions_equal(self, fake_worker, monkeypatch):
        from cloudium_worker.worker import WORKER_VERSION

        port, set_version = fake_worker
        set_version(WORKER_VERSION)
        _point_at(monkeypatch, port)
        rep = L._worker_version_report()
        assert rep["version_check"] == "match"
        assert rep["worker_version"] == WORKER_VERSION

    def test_stale_exe_is_flagged(self, fake_worker, monkeypatch, caplog):
        import logging

        port, set_version = fake_worker
        set_version("0.9-old")
        _point_at(monkeypatch, port)
        with caplog.at_level(logging.WARNING):
            rep = L._worker_version_report()
        assert rep["version_check"] == "stale_exe", (
            "dict 로 안 알리면 호출부·UI 는 낡은 exe 를 영영 못 본다"
        )
        assert rep["worker_version"] == "0.9-old"
        assert "pyinstaller" in " ".join(r.getMessage() for r in caplog.records).lower()

    def test_newer_exe_is_reported_without_claiming_stale(self, fake_worker,
                                                          monkeypatch, caplog):
        """⚠ 방향을 단정하면 거짓말이 된다.

        흔한 건 'exe 가 낡음' 이지만, **소스를 되돌린 경우**(옛 커밋 체크아웃 등)엔
        exe 가 더 새 판이다. 그때도 "낡았다" 고 적으면 사실이 아니다 — 두 값을 다
        보여주고 판단은 사람에게 넘겨야 한다.
        """
        import logging

        port, set_version = fake_worker
        set_version("99.0-newer")
        _point_at(monkeypatch, port)
        with caplog.at_level(logging.WARNING):
            rep = L._worker_version_report()
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert rep["worker_version"] == "99.0-newer"
        assert rep["expected_worker_version"] is not None
        assert "낡은 판" not in msg, "방향을 단정했다 — 소스를 되돌린 경우엔 거짓이다"
        assert "어긋난다" in msg

    def test_unreachable_is_unknown_not_stale(self, monkeypatch):
        """못 물어본 걸 '낡음' 으로 접으면 없는 재빌드를 시킨다."""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
        s.close()
        _point_at(monkeypatch, free)
        rep = L._worker_version_report()
        assert rep["version_check"].startswith("unavailable")
        assert rep["worker_version"] is None


class TestWiredIntoBothPaths:
    """spawn 쪽에만 달면 **평상시 경로**에서 영영 안 보인다."""

    def test_already_running_path_reports_version(self, fake_worker, monkeypatch):
        port, set_version = fake_worker
        set_version("0.9-old")
        _point_at(monkeypatch, port)
        monkeypatch.setattr(L, "_is_disabled", lambda: False)
        monkeypatch.setattr("backend.services.file_resolver.is_gate_running",
                            lambda *a, **k: True)
        res = L.ensure_cloudium_worker_running()
        assert res["action"] == "already_running"
        assert res.get("version_check") == "stale_exe"

    def test_source_constant_is_the_single_expectation(self):
        """기대값을 launcher 에 하드코딩하면 두 벌이 되어 갈라진다."""
        src = (L.__file__ and open(L.__file__, encoding="utf-8").read()) or ""
        assert "from cloudium_worker.worker import WORKER_VERSION" in src, (
            "기대 버전은 소스 상수에서 읽어야 한다"
        )
