# tests/integration/test_api_endpoints.py
"""Integration tests for FastAPI endpoints using TestClient."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from backend.main import app
    return TestClient(app)


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

    def test_stop_nonexistent_pid(self, client):
        resp = client.post("/api/run/stop", json={"pid": 999999})
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


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
