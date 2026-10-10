# tests/integration/test_api_endpoints.py
"""Integration tests for FastAPI endpoints using TestClient."""

from __future__ import annotations


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestStopEndpoint:
    def test_stop_invalid_pid(self, client):
        resp = client.post("/api/run/stop", json={"pid": 0})
        assert resp.status_code == 400

    def test_untracked_pid_is_refused(self, client):
        """추적 밖의 PID 는 **403** 이다 — 200 이 아니다.

        ⚠ 이 테스트는 원래 `test_stop_nonexistent_pid` 로 **200 을 기대**했다. 그건
          `stop_run` 이 클라이언트가 준 PID 를 검증 없이 `taskkill /T /F` 로 넘기던
          시절의 계약이다(그때는 백엔드 자신의 PID 를 줘서 uvicorn 을 통째로 내릴 수
          있었고, `{"ok": True}` 고정이라 PID 존재를 떠보는 oracle 이기도 했다 —
          `backend/routers/sessions.py:436` docstring).

          그 구멍은 막혔는데 **이 스위트가 한 번도 안 돌아서** 낡은 기대가 그대로
          남아 있었다. 되살리며 "실패하니까" 200 쪽으로 되돌리면 취약점이 돌아온다.
          존재/부재를 흘리지 않으려고 404 가 아니라 **403 · 동일 메시지**다.
        """
        resp = client.post("/api/run/stop", json={"pid": 999999})
        assert resp.status_code == 403, resp.text
        assert "tracked" in resp.text


class TestChatEndpoint:
    def test_chat_missing_body(self, client):
        resp = client.post("/api/chat")
        assert resp.status_code in (400, 422)

    def test_chat_empty_message(self, client):
        resp = client.post("/api/chat", json={"message": "", "jenkins_config": {}})
        assert resp.status_code in (200, 400, 422)


class TestLocalReportsSummary:
    def test_summary_no_session(self, client):
        resp = client.get("/api/reports/local/summary")
        assert resp.status_code in (200, 404, 422)


class TestStaticAssets:
    def test_openapi_schema(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/api/health" in schema["paths"]
