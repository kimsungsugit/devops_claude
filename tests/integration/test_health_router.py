# tests/integration/test_health_router.py
"""Integration tests for Health router endpoints.

STS 추적성:
  - STS-HEALTH-001: GET /api/health 정상 응답 구조 검증
  - STS-HEALTH-002: 상태 필드 존재 및 값 검증
  - STS-HEALTH-003: GET /api/metrics 시스템 메트릭 응답 검증
  - STS-HEALTH-004: GET /api/file-mode 파일 모드 응답 구조 검증
  - STS-HEALTH-005: POST /api/cache/clear 캐시 초기화 응답 검증
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from backend.main import app
    return TestClient(app)


class TestHealthCheck:
    """GET /api/health — 기본 헬스체크 엔드포인트.

    @pytest.mark.requirement("STS-HEALTH-001")
    @pytest.mark.requirement("STS-HEALTH-002")
    """

    def test_health_returns_200(self, client):
        # Arrange / Act
        resp = client.get("/api/health")
        # Assert
        assert resp.status_code == 200

    def test_health_status_field_is_ok(self, client):
        # Arrange / Act
        resp = client.get("/api/health")
        data = resp.json()
        # Assert: status 필드가 "ok" 이어야 한다 (STS-HEALTH-002)
        assert "status" in data
        assert data["status"] == "ok"

    def test_health_contains_required_fields(self, client):
        # Arrange / Act
        resp = client.get("/api/health")
        data = resp.json()
        # Assert: engine, version, file_mode 필드 존재 여부
        for field in ("status", "engine", "version", "file_mode"):
            assert field in data, f"응답에 '{field}' 필드가 없습니다"

    def test_health_engine_is_string(self, client):
        # Arrange / Act
        data = client.get("/api/health").json()
        # Assert: engine 필드가 문자열
        assert isinstance(data.get("engine"), str)
        assert len(data["engine"]) > 0


class TestMetricsEndpoint:
    """GET /api/metrics — 시스템 메트릭 엔드포인트.

    @pytest.mark.requirement("STS-HEALTH-003")
    """

    def test_metrics_returns_200(self, client):
        # Arrange / Act
        resp = client.get("/api/metrics")
        # Assert
        assert resp.status_code == 200

    def test_metrics_has_cpu_field(self, client):
        # Arrange / Act
        data = client.get("/api/metrics").json()
        # Assert: cpu_percent 필드 존재 (psutil 없으면 None)
        assert "cpu_percent" in data

    def test_metrics_has_memory_section(self, client):
        # Arrange / Act
        data = client.get("/api/metrics").json()
        # Assert: memory 섹션 존재
        assert "memory" in data
        assert isinstance(data["memory"], dict)

    def test_metrics_has_process_pid(self, client):
        # Arrange / Act
        data = client.get("/api/metrics").json()
        # Assert: process.pid 필드 존재 및 양의 정수
        assert "process" in data
        assert "pid" in data["process"]
        assert data["process"]["pid"] > 0


class TestFileModeEndpoint:
    """GET /api/file-mode — 파일 모드 조회 엔드포인트.

    @pytest.mark.requirement("STS-HEALTH-004")
    """

    def test_file_mode_returns_200(self, client):
        # Arrange / Act
        resp = client.get("/api/file-mode")
        # Assert
        assert resp.status_code == 200

    def test_file_mode_returns_dict(self, client):
        # Arrange / Act
        resp = client.get("/api/file-mode")
        # Assert
        assert isinstance(resp.json(), dict)


class TestCacheClearEndpoint:
    """POST /api/cache/clear — 캐시 초기화 엔드포인트.

    @pytest.mark.requirement("STS-HEALTH-005")
    """

    def test_cache_clear_returns_200(self, client):
        # Arrange / Act
        resp = client.post("/api/cache/clear")
        # Assert
        assert resp.status_code == 200

    def test_cache_clear_ok_flag(self, client):
        # Arrange / Act
        data = client.post("/api/cache/clear").json()
        # Assert
        assert data.get("ok") is True
