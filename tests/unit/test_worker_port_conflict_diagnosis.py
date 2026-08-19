"""워커가 안 뜰 때 **원인을 가려서** 말한다 — '아직'과 '충돌'은 처방이 정반대다.

2026-08-19 실사고. 무관한 앱이 기본 포트 8765 를 점유해 워커가 바인딩에서 죽었다.
`worker.py` 의 TCP 서버가 `allow_reuse_address=True`(SO_REUSEADDR) 라 Windows 는
익숙한 10048("포트 사용 중") 대신 **10013("액세스 권한에 의해 숨겨진 소켓")** 을
돌려준다. 로그만 보면 권한 문제다.

그런데 auto-start 는 준비 실패를 통틀어 **"CLOUDIUM_WORKER_READY_TIMEOUT 을
늘릴 것"** 이라고 안내하고 있었다. 포트 충돌에는 **영원히 듣지 않는 처방**이다.

    아직 안 떴다        → 기다리면 된다 (타임아웃을 늘리는 게 맞다)
    남이 포트를 쥐었다  → 아무리 기다려도 안 된다 (포트를 옮겨야 한다)

이 파일은 그 분기를 고정한다. 반환 dict 의 `port_conflict` 는 UI/호출부가 읽을 수
있는 **관측 가능한 신호**다 — 로그 문구만 바꾸면 프로그램은 여전히 구분을 못 한다.
"""

from __future__ import annotations

import logging
import socket
import threading

import pytest

from backend.services import cloudium_worker_launcher as L


@pytest.fixture
def squatter():
    """워커가 아닌 리스너 — ping 에 pong 을 안 준다(= 남이 포트를 쥔 상태)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (OSError, socket.timeout):
                continue
            conn.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    yield port
    stop.set()
    t.join(timeout=2)
    srv.close()


class TestPortHeldDetection:
    def test_detects_foreign_listener(self, squatter, monkeypatch):
        monkeypatch.setattr(
            "backend.services.file_resolver._worker_endpoint",
            lambda: ("127.0.0.1", squatter),
        )
        taken, port = L._port_held_by_other()
        assert taken is True
        assert port == squatter

    def test_free_port_is_not_reported_as_conflict(self, monkeypatch):
        """빈 포트를 충돌로 부르면 반대 방향 오진단이다 — 애먼 포트를 옮기게 된다."""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
        s.close()
        monkeypatch.setattr(
            "backend.services.file_resolver._worker_endpoint",
            lambda: ("127.0.0.1", free),
        )
        taken, port = L._port_held_by_other()
        assert taken is False
        assert port == free


class TestEnsureReportsConflict:
    """`ensure_cloudium_worker_running` 이 충돌을 **구조화해서** 알리나."""

    @staticmethod
    def _arm(monkeypatch, tmp_path, *, port):
        exe = tmp_path / "dist" / "excel_rename_gui_v2.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"stub")
        monkeypatch.setattr(L, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(L, "_is_disabled", lambda: False)
        monkeypatch.setattr(L, "_wait_ready", lambda *_a, **_k: (False, 0.0))
        monkeypatch.setattr("backend.services.file_resolver.is_gate_running",
                            lambda *a, **k: False)
        monkeypatch.setattr(L.subprocess, "Popen", lambda *a, **k: None)
        monkeypatch.setattr(
            "backend.services.file_resolver._worker_endpoint",
            lambda: ("127.0.0.1", port),
        )

    def test_conflict_is_flagged_and_explained(self, squatter, monkeypatch, tmp_path,
                                               caplog):
        self._arm(monkeypatch, tmp_path, port=squatter)
        with caplog.at_level(logging.WARNING):
            res = L.ensure_cloudium_worker_running()
        assert res.get("port_conflict") is True, (
            "충돌을 dict 로 안 알리면 호출부·UI 는 여전히 구분을 못 한다"
        )
        assert res.get("port") == squatter
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "점유" in msg
        assert "타임아웃" not in msg or "늘려도 안 된다" in msg, (
            "충돌인데 타임아웃을 늘리라고 안내하면 영원히 낫지 않는 처방이다"
        )

    def test_plain_not_ready_keeps_timeout_advice(self, monkeypatch, tmp_path, caplog):
        """빈 포트일 땐 원래 안내(타임아웃)를 유지해야 한다 — 한쪽만 고치면 반대가 깨진다."""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
        s.close()
        self._arm(monkeypatch, tmp_path, port=free)
        with caplog.at_level(logging.WARNING):
            res = L.ensure_cloudium_worker_running()
        assert "port_conflict" not in res
        assert "CLOUDIUM_WORKER_READY_TIMEOUT" in " ".join(
            r.getMessage() for r in caplog.records)
