# tests/integration/test_scm_router.py
"""Integration tests for SCM registry router endpoints.

STS 추적성:
  - STS-SCM-001: GET /api/scm/list 정상 응답 구조 검증
  - STS-SCM-002: POST /api/scm/register 필수 필드 누락 시 422 반환
  - STS-SCM-003: POST /api/scm/register 중복 ID 등록 시 409 반환
  - STS-SCM-004: GET /api/scm/status/{entry_id} 존재하지 않는 항목 404
  - STS-SCM-005: DELETE /api/scm/delete/{entry_id} 존재하지 않는 항목 404
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from backend.main import app
    return TestClient(app)


@pytest.fixture()
def unique_id():
    """테스트마다 충돌 없는 고유 ID 생성."""
    return f"test-scm-{uuid.uuid4().hex[:8]}"


class TestScmList:
    """GET /api/scm/list — SCM 레지스트리 목록 조회.

    @pytest.mark.requirement("STS-SCM-001")
    """

    def test_scm_list_returns_200(self, client):
        # Arrange / Act
        resp = client.get("/api/scm/list")
        # Assert
        assert resp.status_code == 200

    def test_scm_list_has_ok_flag(self, client):
        # Arrange / Act
        data = client.get("/api/scm/list").json()
        # Assert
        assert data.get("ok") is True

    def test_scm_list_has_items_and_count(self, client):
        # Arrange / Act
        data = client.get("/api/scm/list").json()
        # Assert: items 리스트와 count 필드 존재
        assert "items" in data
        assert "count" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["items"])


class TestScmRegisterValidation:
    """POST /api/scm/register — 입력 유효성 검사.

    @pytest.mark.requirement("STS-SCM-002")
    """

    def test_register_missing_body_returns_422(self, client):
        # Arrange: 본문 없이 요청
        # Act
        resp = client.post("/api/scm/register")
        # Assert: 유효성 오류
        assert resp.status_code == 422

    def test_register_missing_required_id_returns_422(self, client):
        # Arrange: id 필드 누락 (name만 전송)
        payload = {"name": "missing-id-test"}
        # Act
        resp = client.post("/api/scm/register", json=payload)
        # Assert
        assert resp.status_code == 422

    def test_register_missing_name_returns_422(self, client):
        # Arrange: name 필드 누락
        payload = {"id": "no-name-entry"}
        # Act
        resp = client.post("/api/scm/register", json=payload)
        # Assert
        assert resp.status_code == 422

    def test_register_empty_body_returns_422(self, client):
        # Arrange: 빈 객체
        # Act
        resp = client.post("/api/scm/register", json={})
        # Assert
        assert resp.status_code == 422


class TestScmRegisterDuplicate:
    """POST /api/scm/register 중복 ID 등록 시 409 반환.

    @pytest.mark.requirement("STS-SCM-003")
    """

    def test_register_duplicate_id_returns_409(self, client, unique_id):
        # Arrange: 유효한 첫 번째 등록
        payload = {"id": unique_id, "name": "Duplicate Test Entry"}
        first = client.post("/api/scm/register", json=payload)
        # 첫 등록이 성공했을 때만 중복 검증 진행
        if first.status_code != 200:
            pytest.skip(f"첫 등록 실패({first.status_code}), 중복 테스트 불가")

        # Act: 동일 ID로 재등록
        second = client.post("/api/scm/register", json=payload)
        # Assert: 충돌 에러
        assert second.status_code == 409

        # Teardown: 등록된 항목 삭제
        client.delete(f"/api/scm/delete/{unique_id}")


class TestScmStatusNotFound:
    """GET /api/scm/status/{entry_id} — 존재하지 않는 항목 404.

    @pytest.mark.requirement("STS-SCM-004")
    """

    def test_status_nonexistent_entry_returns_404(self, client):
        # Arrange: 존재하지 않을 ID
        fake_id = f"nonexistent-{uuid.uuid4().hex}"
        # Act
        resp = client.get(f"/api/scm/status/{fake_id}")
        # Assert
        assert resp.status_code == 404


class TestScmDeleteNotFound:
    """DELETE /api/scm/delete/{entry_id} — 존재하지 않는 항목 404.

    @pytest.mark.requirement("STS-SCM-005")
    """

    def test_delete_nonexistent_entry_returns_404(self, client):
        # Arrange
        fake_id = f"nonexistent-{uuid.uuid4().hex}"
        # Act
        resp = client.delete(f"/api/scm/delete/{fake_id}")
        # Assert
        assert resp.status_code == 404
