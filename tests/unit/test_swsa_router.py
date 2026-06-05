"""SwSA 라우터 테스트 — 입력 표면(스키마) 검증 + 400 경로."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
_EP = "/api/swsa/report/build"
_HDR = {"X-User": "tester"}  # conftest DEV_MODE_X_USER_FALLBACK 회귀 호환


def _post(body):
    return client.post(_EP, json=body, headers=_HDR)


def _valid_body(**over):
    body = {
        "project_id": "KJPDS02",
        "release_sw_version": "2631.00",
        "test_date": "2026.04.24",
    }
    body.update(over)
    return body


class TestSchemaValidation:
    def test_missing_project_id_422(self):
        r = _post({"release_sw_version": "2631.00", "test_date": "2026.04.24"})
        assert r.status_code == 422

    def test_extra_field_forbidden_422(self):
        # extra='forbid' — legacy/오타 키 차단
        r = _post(_valid_body(template_pathX="x"))
        assert r.status_code == 422

    def test_bad_version_422(self):
        r = _post(_valid_body(release_sw_version="abc"))
        assert r.status_code == 422

    def test_dotted_date_accepted_then_400(self):
        # 점 구분 날짜(2026.04.24) 허용 → 스키마 통과 후 template 부재로 400
        r = _post(_valid_body())
        assert r.status_code == 400  # template_path 미지정

    def test_newline_in_path_422(self):
        r = _post(_valid_body(template_path="a\nb"))
        assert r.status_code == 422


class TestAdminGate:
    def test_non_admin_forbidden(self):
        # admin gate (require_admin) — 비-admin 사용자 차단 (SwUT/SwIT 대칭)
        r = client.post(_EP, json=_valid_body(template_path="U:/x/tpl.xlsm"),
                        headers={"X-User": "nonadmin_user_xyz"})
        assert r.status_code in (401, 403)

    def test_admin_passes_gate(self):
        # admin(tester, conftest 등록)은 gate 통과 → template 부재 400 (gate 아님)
        r = _post(_valid_body())
        assert r.status_code == 400


class TestBuildPath:
    def test_no_template_returns_400(self):
        r = _post(_valid_body(log_folder="", template_path=""))
        assert r.status_code == 400
        assert "template_path" in r.text


@pytest.mark.parametrize("date", ["2026.04.24", "2026-04-24", "26/4/9"])
def test_date_formats_accepted(date):
    # 스키마 단계 통과 (template 부재 400) — 다양한 날짜 구분자 허용
    r = _post(_valid_body(test_date=date))
    assert r.status_code == 400
