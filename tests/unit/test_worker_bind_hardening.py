"""워커 TCP 서버의 바인딩 계약 — **포트 가로채기를 막는다.**

2026-08-19 실증. `_ThreadingTCPServer.allow_reuse_address = True` 였는데, Windows 에서
SO_REUSEADDR 은 POSIX 와 뜻이 다르다 — 재시작 편의가 아니라 **남이 이미 바인딩한
포트를 가로챌 수 있게** 한다. 두 번째 프로세스가 **살아 있는 워커의 포트를 뺏어**
리스너가 둘이 됐고, 뺏은 쪽은 Cloudium 권한이 없으므로 그리로 간 요청은 조용히
실패한다 — 게이트는 초록인데 파일만 안 읽히는 최악의 형태다.

끄면 손해가 있을 줄 알았는데 **실측하니 없었다**:

    설정                A 가로채기 차단   B 즉시 재바인딩
    REUSEADDR(옛판)     ❌ 뚫림           ✅ 된다
    **끔(현행)**        ✅ 차단(10048)    ✅ 된다
    EXCLUSIVEADDRUSE    ✅ 차단(10048)    ✅ 된다

`SO_EXCLUSIVEADDRUSE` 는 이득이 **0** 이라 안 쓴다(죽은 방어 금지).

⚠ 이 값은 `dist/excel_rename_gui_v2.exe` 를 **다시 빌드해야** 실제로 반영된다.
  이 테스트는 소스 계약을 고정할 뿐이다.
"""

from __future__ import annotations

import socket
import socketserver
import threading

import pytest

from cloudium_worker import worker


class TestBindContract:
    def test_reuse_address_is_off(self):
        assert worker._ThreadingTCPServer.allow_reuse_address is False, (
            "Windows 에서 SO_REUSEADDR 은 포트 가로채기를 허용한다 — 실증됨"
        )

    def test_hijack_is_blocked(self):
        """계약이 아니라 **행동**을 본다 — 상수만 보면 소켓 옵션 변경을 못 잡는다."""
        srv = worker._ThreadingTCPServer(("127.0.0.1", 0), worker._Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with pytest.raises(OSError):
                worker._ThreadingTCPServer(("127.0.0.1", port), worker._Handler)
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)

    def test_hijack_by_reuseaddr_attacker_is_blocked(self):
        """비대칭 케이스 — **상대가** SO_REUSEADDR 을 켜도 우리 포트는 지켜져야 한다."""
        class _Attacker(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True

        srv = worker._ThreadingTCPServer(("127.0.0.1", 0), worker._Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with pytest.raises(OSError):
                _Attacker(("127.0.0.1", port), worker._Handler)
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)

    def test_restart_rebinding_still_works(self):
        """끄는 대가로 **재시작이 막히면** 흔한 문제를 새로 만드는 것이다. 안 막힌다."""
        srv = worker._ThreadingTCPServer(("127.0.0.1", 0), worker._Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        for _ in range(3):                      # 연결을 실제로 처리시킨다
            try:
                c = socket.create_connection(("127.0.0.1", port), timeout=2)
                c.sendall(b'{"id":"p","op":"ping","args":{}}\n')
                c.recv(256)
                c.close()
            except OSError:
                pass
        srv.shutdown()
        srv.server_close()
        t.join(timeout=2)

        again = worker._ThreadingTCPServer(("127.0.0.1", port), worker._Handler)
        again.server_close()    # 여기서 OSError 가 나면 재시작 마찰이 생긴 것


class TestBindFailureMessage:
    """트레이스백만 내면 사용자는 '그냥 안 켜진다' 로 겪는다."""

    @pytest.mark.parametrize("code", [10013, 10048])
    def test_conflict_codes_get_actionable_hint(self, code):
        exc = OSError()
        exc.winerror = code
        msg = worker.bind_failure_message("127.0.0.1", 8766, exc)
        assert "다른 프로세스" in msg
        assert "netstat" in msg and "8766" in msg
        assert "CLOUDIUM_WORKER_PORT" in msg

    def test_10013_is_explicitly_disarmed(self):
        """10013 은 '권한 문제' 로 읽힌다 — 아니라고 **명시**해야 진단이 안 헛돈다."""
        exc = OSError()
        exc.winerror = 10013
        assert "권한 문제가 아니라" in worker.bind_failure_message("h", 1, exc)

    def test_dialog_ttl_is_read_at_call_time(self, monkeypatch):
        """⚠ import 시점에 얼리면 재로드 없이는 바꿀 수도 잴 수도 없다.

        이 저장소는 기본 인자를 def 시점에 얼려 두고 "튜닝했다" 고 믿었다가 실험
        자체가 no-op 이던 전례가 있다(`file_resolver._ping_worker` docstring).
        """
        monkeypatch.setenv("CLOUDIUM_WORKER_ERR_DIALOG_TTL", "3.5")
        assert worker.err_dialog_ttl_s() == 3.5
        monkeypatch.delenv("CLOUDIUM_WORKER_ERR_DIALOG_TTL")
        assert worker.err_dialog_ttl_s() == worker._ERR_DIALOG_TTL_DEFAULT_S

    def test_dialog_ttl_default_is_bounded(self):
        """무인 spawn 이 대화상자에 붙잡히지 않으려면 기본값이 **유한**해야 한다."""
        ttl = worker.err_dialog_ttl_s()
        assert 0 < ttl <= 120, f"기본 TTL 이 비었거나 과하다: {ttl}"

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "1,5"])
    def test_bad_ttl_falls_back(self, monkeypatch, bad):
        monkeypatch.setenv("CLOUDIUM_WORKER_ERR_DIALOG_TTL", bad)
        assert worker.err_dialog_ttl_s() == worker._ERR_DIALOG_TTL_DEFAULT_S

    def test_ttl_zero_means_no_dialog(self, monkeypatch):
        """0 이하면 대화상자를 안 띄운다 — 주석에 적었으면 동작도 그래야 한다."""
        monkeypatch.setenv("CLOUDIUM_WORKER_ERR_DIALOG_TTL", "0")
        assert worker.err_dialog_ttl_s() <= 0

    def test_unrelated_error_gets_no_false_hint(self):
        """포트 충돌이 아닌데 '포트를 옮기라' 고 하면 반대 방향 오진단이다."""
        exc = OSError()
        exc.winerror = 10055          # 버퍼 부족 — 충돌과 무관
        msg = worker.bind_failure_message("127.0.0.1", 8766, exc)
        assert "netstat" not in msg
        assert "CLOUDIUM_WORKER_PORT" not in msg
