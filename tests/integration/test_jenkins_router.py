# tests/integration/test_jenkins_router.py
"""Integration tests for Jenkins router endpoints.

외부 Jenkins 서버는 mock 처리하여 격리된 환경에서 검증한다.

STS 추적성:
  - STS-JENKINS-001: POST /api/jenkins/jobs API 토큰 누락 시 400 반환
  - STS-JENKINS-002: POST /api/jenkins/jobs 연결 불가 URL 시 5xx/4xx 에러
  - STS-JENKINS-003: GET /api/jenkins/progress 응답 구조 검증
  - STS-JENKINS-004: POST /api/jenkins/builds job_url 누락 시 400 반환
  - STS-JENKINS-005: POST /api/jenkins/build-info 요청 구조 422 검증
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from backend.main import app
    return TestClient(app)


class TestJenkinsJobsValidation:
    """POST /api/jenkins/jobs — 입력 유효성 및 에러 처리.

    @pytest.mark.requirement("STS-JENKINS-001")
    """

    def test_jobs_missing_token_returns_400(self, client):
        # Arrange: api_token 없이 요청 (빈 문자열)
        payload = {
            "base_url": "http://jenkins.example.invalid",
            "username": "user",
            "api_token": "",
        }
        # Act
        resp = client.post("/api/jenkins/jobs", json=payload)
        # Assert: 토큰 누락 → 400
        assert resp.status_code == 400

    def test_jobs_missing_body_returns_422(self, client):
        # Arrange: 본문 없이 요청
        # Act
        resp = client.post("/api/jenkins/jobs")
        # Assert
        assert resp.status_code == 422

    def test_jobs_unreachable_url_returns_error(self, client):
        # Arrange: 도달할 수 없는 서버 URL
        payload = {
            "base_url": "http://jenkins.localhost.invalid:9999",
            "username": "user",
            "api_token": "dummy-token",
            "verify_tls": False,
        }
        # Act: list_jobs 가 연결 오류를 발생시키도록 mock
        with patch(
            "backend.routers.jenkins.list_jobs",
            side_effect=ConnectionError("Connection refused"),
        ):
            resp = client.post("/api/jenkins/jobs", json=payload)
        # Assert: 연결 실패 → 503
        assert resp.status_code == 503

    def test_jobs_unauthorized_returns_401(self, client):
        # Arrange
        payload = {
            "base_url": "http://jenkins.example.invalid",
            "username": "user",
            "api_token": "wrong-token",
            "verify_tls": False,
        }
        with patch(
            "backend.routers.jenkins.list_jobs",
            side_effect=Exception("401 Unauthorized"),
        ):
            resp = client.post("/api/jenkins/jobs", json=payload)
        # Assert
        assert resp.status_code == 401

    def test_jobs_timeout_returns_504(self, client):
        # Arrange
        payload = {
            "base_url": "http://jenkins.example.invalid",
            "username": "user",
            "api_token": "some-token",
            "verify_tls": False,
        }
        with patch(
            "backend.routers.jenkins.list_jobs",
            side_effect=Exception("Request timed out"),
        ):
            resp = client.post("/api/jenkins/jobs", json=payload)
        # Assert
        assert resp.status_code == 504


class TestJenkinsProgress:
    """GET /api/jenkins/progress — 진행률 조회 응답 구조.

    @pytest.mark.requirement("STS-JENKINS-003")
    """

    def test_progress_returns_200(self, client):
        # Arrange / Act
        resp = client.get(
            "/api/jenkins/progress",
            params={
                "action": "uds",
                "job_url": "http://jenkins.example.invalid/job/test",
                "build_selector": "lastSuccessfulBuild",
            },
        )
        # Assert
        assert resp.status_code == 200

    def test_progress_has_ok_and_progress_fields(self, client):
        # Arrange / Act
        data = client.get(
            "/api/jenkins/progress",
            params={
                "action": "sync",
                "job_url": "http://jenkins.example.invalid/job/test",
            },
        ).json()
        # Assert: 응답 구조에 ok, progress 필드 존재
        assert "ok" in data
        assert "progress" in data

    def test_progress_ok_is_boolean(self, client):
        # Arrange / Act
        data = client.get(
            "/api/jenkins/progress",
            params={
                "action": "sts",
                "job_url": "http://jenkins.example.invalid/job/myproject",
            },
        ).json()
        # Assert
        assert isinstance(data["ok"], bool)

    def test_progress_missing_action_returns_422(self, client):
        # Arrange: action 파라미터 누락
        resp = client.get(
            "/api/jenkins/progress",
            params={"job_url": "http://jenkins.example.invalid/job/test"},
        )
        # Assert
        assert resp.status_code == 422

    def test_progress_missing_job_url_returns_422(self, client):
        # Arrange: job_url 파라미터 누락
        resp = client.get(
            "/api/jenkins/progress",
            params={"action": "uds"},
        )
        # Assert
        assert resp.status_code == 422


class TestJenkinsBuildsValidation:
    """POST /api/jenkins/builds — 입력 유효성 검사.

    @pytest.mark.requirement("STS-JENKINS-004")
    """

    def test_builds_empty_job_url_returns_400(self, client):
        # Arrange: job_url 빈 문자열
        payload = {
            "job_url": "",
            "username": "user",
            "api_token": "token",
        }
        # Act
        resp = client.post("/api/jenkins/builds", json=payload)
        # Assert
        assert resp.status_code == 400

    def test_builds_missing_token_returns_400(self, client):
        # Arrange: api_token 빈 문자열
        payload = {
            "job_url": "http://jenkins.example.invalid/job/test",
            "username": "user",
            "api_token": "",
        }
        # Act
        resp = client.post("/api/jenkins/builds", json=payload)
        # Assert
        assert resp.status_code == 400


class TestJenkinsBuildInfoValidation:
    """POST /api/jenkins/build-info — 요청 구조 유효성 검사.

    @pytest.mark.requirement("STS-JENKINS-005")
    """

    def test_build_info_missing_body_returns_422(self, client):
        # Arrange / Act
        resp = client.post("/api/jenkins/build-info")
        # Assert
        assert resp.status_code == 422
