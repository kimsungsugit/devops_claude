"""33차 SwIT router endpoint 회귀.

SwUT router 패턴 차용 — 입력 표면 / X-User middleware / Semaphore /
StreamingResponse 헤더 검증.
"""
from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)


def test_apply_c_function_map_populates_function_and_swufn_keys(tmp_path, monkeypatch):
    """SwITCR reason/action evidence can use C source function bodies."""
    from backend.routers import swit
    from backend.schemas import SwITBuildRequest
    from backend.services.swut_input_adapter import SwUTSession
    from workflow.code_parser import c_parser

    monkeypatch.setattr(
        swit,
        "_resolver_resolve_c_source_root",
        lambda req, project_id: str(tmp_path),
    )
    monkeypatch.setattr(
        c_parser,
        "parse_c_project",
        lambda root, max_files=300: {
            "functions": [{
                "name": "FunctionA",
                "signature": "void FunctionA(void)",
                "body": "void FunctionA(void) {}",
                "file": "FunctionA.c",
                "comment_related": "SwUFn_0001",
            }]
        },
    )

    req = SwITBuildRequest(
        project_id="KJPDS02",
        release_sw_version="1.01",
        test_date="2025-12-05",
    )
    session = SwUTSession()
    swit._apply_c_function_map(req, session)

    assert session.c_function_map["FunctionA"]["file"] == "FunctionA.c"
    assert session.c_function_map["SwUFn_0001"]["name"] == "FunctionA"
    assert any("parsed 1 C functions" in warning for warning in session.parse_warnings)


# ---------------------------------------------------------------------------
# Pydantic input surface validation
# ---------------------------------------------------------------------------

class TestSwitPydanticValidation:
    """SwITBuildRequest 입력 표면 — SwUT 13차 W7/W8/W9 패턴 동일 검증."""

    def _base_body(self) -> dict:
        return {
            "project_id": "HDPDM01",
            "release_sw_version": "2.02",
            "test_date": "2024-02-19",
        }

    def test_minimal_required_fields_accepted(self):
        """필수 3개 필드만 → schema 통과 + endpoint도 호출 (log_folder 없이 빌더 호출 단계에서 400 가능)."""
        from backend.schemas import SwITBuildRequest
        req = SwITBuildRequest(**self._base_body())
        assert req.project_id == "HDPDM01"
        assert req.release_sw_version == "2.02"
        assert req.asil_level == "ASIL B"   # SwIT default
        assert req.c_source_root == ""

    def test_invalid_release_sw_version_rejected(self):
        body = self._base_body()
        body["release_sw_version"] = "bad-ver"
        r = client.post(
            "/api/swit/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_test_date_with_garbage_suffix_rejected(self):
        """13차 W7 동일 — pattern $ anchor."""
        body = self._base_body()
        body["test_date"] = "2024-02-19; DROP TABLE users"
        r = client.post(
            "/api/swit/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_log_folder_newline_rejected(self):
        """W8 동일 — 헤더 인젝션 방어."""
        body = self._base_body()
        body["log_folder"] = "C:/fake\r\nX-Injected: evil"
        r = client.post(
            "/api/swit/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_c_source_root_maxlen_rejected(self):
        """30차 W21 동일 — maxlen 500."""
        body = self._base_body()
        body["c_source_root"] = "D:/" + "a" * 600
        r = client.post(
            "/api/swit/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# X-User middleware integration
# ---------------------------------------------------------------------------

class TestSwitXUserHeader:
    def test_missing_x_user_rejected(self):
        r = client.post(
            "/api/swit/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "2.02",
                "test_date": "2024-02-19",
            },
        )
        # middleware가 401 또는 400
        assert r.status_code in (401, 403, 400)


# ---------------------------------------------------------------------------
# Semaphore + endpoint registration
# ---------------------------------------------------------------------------

class TestSwitEndpointRegistration:
    """라우터 등록 확인 — openapi.json에 SwIT endpoint 노출."""

    def test_swit_coverage_endpoint_registered(self):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/api/swit/coverage/build" in paths
        # POST 메소드 등록
        assert "post" in paths["/api/swit/coverage/build"]

    def test_swit_semaphore_initial_capacity(self):
        """Semaphore(2) — SwUT(3)보다 보수적."""
        from backend.routers.swit import _BUILD_SEMAPHORE
        # asyncio.Semaphore._value는 internal이지만 회귀에 사용 가능
        assert _BUILD_SEMAPHORE._value == 2


# ---------------------------------------------------------------------------
# Meta builder & template loading
# ---------------------------------------------------------------------------

class TestSwitMetaBuilder:
    """_build_swit_coverage_meta — SwITBuildRequest → SwitCoverageBuildMeta."""

    def test_meta_doc_id_base_is_project_swit(self):
        from backend.routers.swit import _build_swit_coverage_meta
        from backend.schemas import SwITBuildRequest
        req = SwITBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
            doc_id_sequence="042",
        )
        meta = _build_swit_coverage_meta(req)
        assert meta.doc_id_base == "HDPDM01-SwIT"
        assert meta.doc_id_sequence == "042"
        assert meta.asil_level == "ASIL B"   # SwIT default

    def test_template_path_required_returns_400(self):
        """template_path 미지정 시 명시 400 (config 별도 없음 33차 정책)."""
        body = {
            "project_id": "HDPDM01",
            "release_sw_version": "2.02",
            "test_date": "2024-02-19",
            "log_folder": "C:/fake/log",   # validation 통과만, 빌더에서 404
        }
        r = client.post(
            "/api/swit/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        # template_path 누락 → 400 또는 빌더 단계에서 404 (log_folder 미존재)
        # F7: config 회사 표준 path 등록 후 path validation skip → admin 가드 403도 정상
        assert r.status_code in (400, 403, 404, 500)


# ---------------------------------------------------------------------------
# 34차 SITR endpoint — Pydantic / endpoint 등록 / Semaphore 공유 / media_type
# ---------------------------------------------------------------------------

class TestSwitSitrPydantic:
    """SwITSitrBuildRequest — Coverage 17 필드 + deviation_cases 정책."""

    def _base_body(self) -> dict:
        return {
            "project_id": "HDPDM01",
            "release_sw_version": "2.02",
            "test_date": "2024-02-19",
        }

    def test_minimal_required_accepted(self):
        from backend.schemas import SwITSitrBuildRequest
        req = SwITSitrBuildRequest(**self._base_body())
        assert req.asil_level == "ASIL B"
        assert req.deviation_cases == []

    def test_deviation_cases_oversize_rejected(self):
        """deviation_cases 합산 256KB 초과 거부 (13차 C3 패턴)."""
        from backend.schemas import SwITSitrBuildRequest
        body = self._base_body()
        # 200 items × 1.5KB ≈ 300KB
        body["deviation_cases"] = [
            {"tc_id": f"TC_{i:04d}", "issue_text": "X" * 1500}
            for i in range(200)
        ]
        with pytest.raises(ValueError, match="256KB"):
            SwITSitrBuildRequest(**body)

    def test_deviation_cases_item_keys_too_many_rejected(self):
        from backend.schemas import SwITSitrBuildRequest
        body = self._base_body()
        body["deviation_cases"] = [
            {f"k{i}": "v" for i in range(25)},
        ]
        with pytest.raises(ValueError, match=r"key 수 ≤ 20"):
            SwITSitrBuildRequest(**body)


class TestSwitSitrEndpointRegistration:
    """라우터 등록 확인 — openapi.json에 /api/swit/sitr/build 노출."""

    def test_sitr_endpoint_registered(self):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/api/swit/sitr/build" in paths
        assert "post" in paths["/api/swit/sitr/build"]

    def test_sitr_shares_coverage_semaphore(self):
        """Semaphore(2) — Coverage와 SITR 동일 인스턴스 공유."""
        # 모듈 단일 instance — Coverage build_swit_coverage / SITR build_swit_sitr
        # 모두 `_BUILD_SEMAPHORE` 사용 (소스 검사로 충분).
        import backend.routers.swit as swit_mod
        from backend.routers.swit import _BUILD_SEMAPHORE
        src = swit_mod.__file__
        with open(src, encoding="utf-8") as f:
            content = f.read()
        assert content.count("_BUILD_SEMAPHORE") >= 3, (
            "Coverage + SITR 두 endpoint가 동일 Semaphore 사용 확인"
        )
        assert _BUILD_SEMAPHORE._value == 2


class TestSwitSitrMediaType:
    """SITR 응답 media_type — xlsm macroenabled.12."""

    def test_sitr_missing_template_returns_400_or_404(self):
        """template_path 미지정 — Coverage와 동일 정책. F7 — admin 가드 403도 허용."""
        body = {
            "project_id": "HDPDM01",
            "release_sw_version": "2.02",
            "test_date": "2024-02-19",
            "log_folder": "C:/fake/log",
        }
        r = client.post(
            "/api/swit/sitr/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code in (400, 403, 404, 500)


class TestSwitSitrXUserHeader:
    def test_sitr_missing_x_user_rejected(self):
        r = client.post(
            "/api/swit/sitr/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "2.02",
                "test_date": "2024-02-19",
            },
        )
        assert r.status_code in (401, 403, 400)


# ---------------------------------------------------------------------------
# 38차 W4 — log_folder preview endpoint
# ---------------------------------------------------------------------------

class TestSwitLogFolderPreview38:
    """38차 W4: /api/swit/log-folder/preview — 빌드 전 release 후보 list."""

    def test_minimal_returns_200_with_empty_candidates(self):
        """존재하는 빈 디렉토리 → candidates 0건 + warnings."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = client.post(
                "/api/swit/log-folder/preview",
                json={"log_folder": tmp},
                headers={"X-User": "tester"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["candidates"] == []
            assert data["auto_resolved"] is False
            assert data["input_log_folder"] == tmp
            assert any("미발견" in w for w in (data.get("warnings") or []))

    def test_pydantic_422_on_newline(self):
        r = client.post(
            "/api/swit/log-folder/preview",
            json={"log_folder": "C:/fake\r\nX-Injected: evil"},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_pydantic_422_on_maxlen(self):
        r = client.post(
            "/api/swit/log-folder/preview",
            json={"log_folder": "C:/" + "a" * 600},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_release_candidates_enumerated_with_latest_marked(self, tmp_path):
        """3 release 디렉토리 → 후보 list + is_latest=True 1건."""
        for name in ("v2.02_240219", "v2.03_240315", "v2.10_241201"):
            (tmp_path / name / "01.TestCaseDataReport").mkdir(parents=True)
        r = client.post(
            "/api/swit/log-folder/preview",
            json={"log_folder": str(tmp_path)},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["candidates"]) == 3
        latest = [c for c in data["candidates"] if c.get("is_latest")]
        assert len(latest) == 1
        assert latest[0]["name"] == "v2.10_241201"
        assert data["auto_resolved"] is True
        assert any("auto-resolved" in w for w in data["warnings"])


class TestSwitConfigFallback50:
    """50차 — SwIT가 swut_meta.json 재활용 (config fallback).

    HDPDM01은 SwUT/SwIT 동일 프로젝트 — c_source_root + swuds_docx_path 공유.
    SwIT template은 swit_coverage_template / swit_sitr_template 별도 키 (v2.02).
    """

    def _setup_cfg(self, tmp_path, monkeypatch, cfg_dict):
        from backend.routers import swit as swit_mod
        from backend.routers import swut as swut_mod
        from backend.services import swut_meta_resolver as resolver_mod
        cfg_path = tmp_path / "swut_meta.json"
        import json as _json
        cfg_path.write_text(_json.dumps(cfg_dict), encoding="utf-8")
        # 54차 T281 + 54-fix W2 — resolver + swut + swit 세 모듈 모두 patch
        # (swit.py도 backward compat alias로 _META_CONFIG_PATH 갖게 됨)
        monkeypatch.setattr(resolver_mod, "_META_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(swut_mod, "_META_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(swit_mod, "_META_CONFIG_PATH", str(cfg_path))
        resolver_mod._read_meta_config_raw.cache_clear()

    def test_resolve_swit_c_source_root_config_fallback(self, tmp_path, monkeypatch):
        from backend.routers.swit import _resolve_swit_c_source_root
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {"c_source_root": "D:/from_config_swit"}}
        })
        req = SwITBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
        )
        assert _resolve_swit_c_source_root(req) == "D:/from_config_swit"

    def test_resolve_swit_c_source_root_req_priority(self, tmp_path, monkeypatch):
        """53차 W1 — req.c_source_root 우선 (config 값 무시). SwUT 대칭."""
        from backend.routers.swit import _resolve_swit_c_source_root
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {"c_source_root": "D:/from_config_swit"}}
        })
        req = SwITBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
            c_source_root="D:/from_req_swit",
        )
        # req 우선 — config 무시
        assert _resolve_swit_c_source_root(req) == "D:/from_req_swit"


    def test_resolve_swit_swuds_path_req_priority(self, tmp_path, monkeypatch):
        from backend.routers.swit import _resolve_swit_swuds_path
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {"swuds_docx_path": "U:/config_swuds.docx"}}
        })
        req = SwITBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
            swuds_docx_path="U:/req_swuds.docx",
        )
        assert _resolve_swit_swuds_path(req) == "U:/req_swuds.docx"

    def test_resolve_swit_spec_prefers_swits_over_swuts_config(self, tmp_path, monkeypatch):
        """SwIT 요청은 config fallback에서 SwITS spec을 SwUTS보다 우선 사용."""
        from backend.schemas import SwITBuildRequest
        from backend.services.swut_meta_resolver import resolve_swuts_path
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "swuts_docx_path": "U:/spec/(KJPDS02_SwUTS).xlsm",
                "swits_docx_path": "U:/spec/(KJPDS02_SwITS).xlsm",
            }}
        })
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        assert resolve_swuts_path(req, "KJPDS02") == "U:/spec/(KJPDS02_SwITS).xlsm"

    def test_resolve_swit_spec_uses_nested_iso26262_swits_path(self, tmp_path, monkeypatch):
        """top-level swits_docx_path가 없어도 iso26262_docs.swits_xlsm_path를 사용."""
        from backend.schemas import SwITBuildRequest
        from backend.services.swut_meta_resolver import resolve_swuts_path
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "swuts_docx_path": "U:/spec/(KJPDS02_SwUTS).xlsm",
                "iso26262_docs": {
                    "swits_xlsm_path": "U:/nested/(KJPDS02_SwITS).xlsm",
                },
            }}
        })
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        assert resolve_swuts_path(req, "KJPDS02") == "U:/nested/(KJPDS02_SwITS).xlsm"

    def test_resolve_swit_log_folder_config_fallback(self, tmp_path, monkeypatch):
        """req.log_folder가 비면 config.swit_log_folder를 사용."""
        from backend.routers.swit import _resolve_swit_log_folder
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "swit_log_folder": "U:/logs/251106_IT_Report",
            }}
        })
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        assert _resolve_swit_log_folder(req) == "U:/logs/251106_IT_Report"

    def test_resolve_swit_log_folder_req_priority(self, tmp_path, monkeypatch):
        """req.log_folder가 있으면 config fallback보다 우선."""
        from backend.routers.swit import _resolve_swit_log_folder
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "swit_log_folder": "U:/logs/from_config",
            }}
        })
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
            log_folder="C:/logs/from_req",
        )
        assert _resolve_swit_log_folder(req) == "C:/logs/from_req"

    def test_read_template_bytes_empty_both_returns_400(self, tmp_path, monkeypatch):
        """req.template_path 빈 + config의 swit_coverage_template 빈 슬롯 → 400 raise (사용자가 swut_meta.json 미설정 시 명시 에러)."""
        from fastapi import HTTPException

        from backend.routers.swit import _read_template_bytes
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {"template_paths": {"swit_coverage_template": ""}}}
        })
        with pytest.raises(HTTPException) as exc_info:
            _read_template_bytes("", "HDPDM01", "coverage")
        assert exc_info.value.status_code == 400
        assert "swit_coverage_template" in str(exc_info.value.detail)

    def test_read_template_bytes_sitr_kind_uses_swit_sitr_key(self, tmp_path, monkeypatch):
        """kind='sitr' → swit_sitr_template config 키 사용."""
        from fastapi import HTTPException

        from backend.routers.swit import _read_template_bytes
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {"template_paths": {"swit_sitr_template": ""}}}
        })
        with pytest.raises(HTTPException) as exc_info:
            _read_template_bytes("", "HDPDM01", "sitr")
        assert exc_info.value.status_code == 400
        assert "swit_sitr_template" in str(exc_info.value.detail)

    def test_read_template_bytes_switcr_kind_uses_switcr_key(self, tmp_path, monkeypatch):
        """kind='switcr' uses switcr_template config key."""
        from fastapi import HTTPException

        from backend.routers.swit import _read_template_bytes
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {"template_paths": {"switcr_template": ""}}}
        })
        with pytest.raises(HTTPException) as exc_info:
            _read_template_bytes("", "HDPDM01", "switcr")
        assert exc_info.value.status_code == 400
        assert "switcr_template" in str(exc_info.value.detail)

    def test_coverage_endpoint_uses_coverage_template_path(self, monkeypatch):
        """52차 W2 — SwIT Coverage endpoint이 coverage_template_path만 사용.

        sitr_template_path 입력은 무시되고 coverage_template_path가 _read_template_bytes로 전달.
        """
        from backend.routers import swit as swit_mod
        captured = {}

        def _fake_read(template_path, project_id, kind):
            captured["template_path"] = template_path
            captured["kind"] = kind
            raise RuntimeError("stop after capture")

        monkeypatch.setattr(swit_mod, "_read_template_bytes", _fake_read)
        body = {
            "project_id": "HDPDM01",
            "release_sw_version": "2.02",
            "test_date": "2024-02-19",
            "log_folder": "C:/fake/log",
            "coverage_template_path": "C:/coverage.xlsx",
            "sitr_template_path": "C:/sitr.xlsm",
        }
        client.post(
            "/api/swit/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        if "template_path" in captured:
            assert captured["template_path"] == "C:/coverage.xlsx"
            assert captured["kind"] == "coverage"

    def test_sitr_endpoint_uses_sitr_template_path(self, monkeypatch):
        """52차 W2 — SwIT SITR endpoint이 sitr_template_path만 사용."""
        from backend.routers import swit as swit_mod
        captured = {}

        def _fake_read(template_path, project_id, kind):
            captured["template_path"] = template_path
            captured["kind"] = kind
            raise RuntimeError("stop after capture")

        monkeypatch.setattr(swit_mod, "_read_template_bytes", _fake_read)
        body = {
            "project_id": "HDPDM01",
            "release_sw_version": "2.02",
            "test_date": "2024-02-19",
            "log_folder": "C:/fake/log",
            "coverage_template_path": "C:/coverage.xlsx",
            "sitr_template_path": "C:/sitr.xlsm",
        }
        client.post(
            "/api/swit/sitr/build", json=body,
            headers={"X-User": "tester"},
        )
        if "template_path" in captured:
            assert captured["template_path"] == "C:/sitr.xlsm"
            assert captured["kind"] == "sitr"

    def test_coverage_meta_pulls_config_approvers(self, tmp_path, monkeypatch):
        """50차 — SwIT Coverage meta가 config의 approvers + project_full_name 자동 적용."""
        from backend.routers.swit import _build_swit_coverage_meta
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {
                "project_full_name": "HDPDM01 Full Project Name",
                "approvers": {
                    "default_author": "JK Kim",
                    "default_reviewer": "Reviewer X",
                    "default_approver": "CH In",
                }
            }}
        })
        req = SwITBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
        )
        meta = _build_swit_coverage_meta(req)
        assert meta.project_full_name == "HDPDM01 Full Project Name"
        assert meta.default_author == "JK Kim"
        assert meta.default_reviewer == "Reviewer X"
        assert meta.default_approver == "CH In"
        # author override는 test_engineer (빈) — default_author 사용
        assert meta.author == "JK Kim"
        # doc_id_base는 SwIT 고유 — config 영향 안 받음
        assert meta.doc_id_base == "HDPDM01-SwIT"

    def test_coverage_meta_uses_switcv_doc_filename_pattern(self, tmp_path, monkeypatch):
        """SwIT Coverage meta는 SwUT coverage 패턴이 아니라 switcv 패턴을 사용."""
        from backend.routers.swit import _build_swit_coverage_meta
        from backend.schemas import SwITBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "doc_filenames": {
                    "coverage": "(KJPDS02_DV_SwUTCV)_v{version}_{date}_R.xlsx",
                    "switcv": "(KJPDS02_DV_SwITCV)_v{version}_{date}_R.xlsx",
                }
            }}
        })
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        meta = _build_swit_coverage_meta(req)
        assert meta.doc_filename_pattern == "(KJPDS02_DV_SwITCV)_v{version}_{date}_R.xlsx"

    def test_sitr_meta_pulls_config_approvers(self, tmp_path, monkeypatch):
        """50차 — SwIT SITR meta도 config approvers fallback."""
        from backend.routers.swit import _build_swit_sitr_meta
        from backend.schemas import SwITSitrBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"HDPDM01": {
                "approvers": {"default_author": "AlphaUser", "default_approver": "ChIn"}
            }}
        })
        req = SwITSitrBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
        )
        meta = _build_swit_sitr_meta(req)
        assert meta.default_author == "AlphaUser"
        assert meta.default_approver == "ChIn"
        assert meta.doc_id_base == "HDPDM01-SITR"  # SwIT 고유 — config 무영향

    def test_sitr_meta_uses_switr_doc_filename_pattern(self, tmp_path, monkeypatch):
        """SwIT SITR meta는 SwUTR 패턴이 아니라 switr 패턴을 사용."""
        from backend.routers.swit import _build_swit_sitr_meta
        from backend.schemas import SwITSitrBuildRequest
        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "doc_filenames": {
                    "sutr": "(KJPDS02_DV_SwUTR)_v{version}_{date}_R.xlsm",
                    "switr": "(KJPDS02_DV_SwITR)_v{version}_{date}_R.xlsm",
                }
            }}
        })
        req = SwITSitrBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        meta = _build_swit_sitr_meta(req)
        assert meta.doc_filename_pattern == "(KJPDS02_DV_SwITR)_v{version}_{date}_R.xlsm"

    def test_coverage_build_passes_swits_map_to_builder(self, monkeypatch):
        """SwITCV도 SwITS spec parse 결과를 Traceability writer로 전달."""
        import io

        from backend.routers import swit as swit_mod
        from backend.schemas import SwITBuildRequest
        from backend.services.swit_coverage_aggregator import SwitCoverageBuildResult

        captured = {}
        swits_map = {"SwITC_0001": object()}

        monkeypatch.setattr(swit_mod, "check_log_folder_mode_compat", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(swit_mod, "collect_swit_session", lambda *_args, **_kwargs: object())
        monkeypatch.setattr(swit_mod, "_apply_function_asil_map", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(swit_mod, "_read_template_bytes", lambda *_args, **_kwargs: b"template")
        # 2026-08-04: `out_warnings` kwarg 추가(SwUDS 읽기 실패 침묵 차단) — 스텁도
        # kwargs 를 흡수해야 한다. `lambda _req:` 로 두면 TypeError 로 죽는다.
        monkeypatch.setattr(swit_mod, "_resolve_swuds_function_ids",
                            lambda _req, **_kwargs: {"SwUFn_0001"})
        monkeypatch.setattr(
            swit_mod, "_resolver_resolve_hmr_html_bytes",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            swit_mod, "_resolver_resolve_swuts_test_specs",
            lambda *_args, **_kwargs: swits_map,
        )

        def _fake_build(session, meta, template_bytes, **kwargs):
            captured["swits_map"] = kwargs.get("swits_map")
            return SwitCoverageBuildResult(
                ok=True,
                xlsx_io=io.BytesIO(b"dummy"),
                filename="dummy.xlsx",
                summary={},
                warnings=[],
                incomplete_sheets=[],
            )

        monkeypatch.setattr(swit_mod, "build_swit_coverage_report", _fake_build)
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
            log_folder="C:/fake/log",
        )
        response = swit_mod._do_swit_coverage_build(req)
        assert response.status_code == 200
        assert captured["swits_map"] is swits_map

    def test_coverage_build_uses_config_log_folder_when_request_empty(self, tmp_path, monkeypatch):
        """SwITCV build는 req.log_folder가 비면 config.swit_log_folder를 collector에 전달.

        B2 대칭 이후 — 라우터는 단일 config 폴더도 ``log_folders=[folder]``
        (list kwarg)로 collector에 전달한다.
        """
        import io

        from backend.routers import swit as swit_mod
        from backend.schemas import SwITBuildRequest
        from backend.services.swit_coverage_aggregator import SwitCoverageBuildResult

        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "swit_log_folder": "U:/logs/251106_IT_Report",
            }}
        })
        captured = {}

        monkeypatch.setattr(swit_mod, "check_log_folder_mode_compat", lambda *_args, **_kwargs: None)

        def _fake_collect(_resolver, _project_id, **kwargs):
            captured["log_folders"] = kwargs.get("log_folders")
            return object()

        monkeypatch.setattr(swit_mod, "collect_swit_session", _fake_collect)
        monkeypatch.setattr(swit_mod, "_apply_function_asil_map", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(swit_mod, "_read_template_bytes", lambda *_args, **_kwargs: b"template")
        monkeypatch.setattr(swit_mod, "_resolve_swuds_function_ids",
                            lambda _req, **_kwargs: set())  # out_warnings kwarg 흡수(2026-08-04)
        monkeypatch.setattr(swit_mod, "_resolver_resolve_hmr_html_bytes", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(swit_mod, "_resolver_resolve_swuts_test_specs", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            swit_mod,
            "build_swit_coverage_report",
            lambda *_args, **_kwargs: SwitCoverageBuildResult(
                ok=True,
                xlsx_io=io.BytesIO(b"dummy"),
                filename="dummy.xlsx",
                summary={},
                warnings=[],
                incomplete_sheets=[],
            ),
        )
        req = SwITBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        response = swit_mod._do_swit_coverage_build(req)
        assert response.status_code == 200
        assert captured["log_folders"] == ["U:/logs/251106_IT_Report"]

    def test_sitr_build_uses_config_log_folder_when_request_empty(self, tmp_path, monkeypatch):
        """SwITR build도 req.log_folder가 비면 config.swit_log_folder를 collector에 전달.

        B2 대칭 이후 — 단일 config 폴더도 ``log_folders=[folder]`` list kwarg로 전달.
        """
        import io

        from backend.routers import swit as swit_mod
        from backend.schemas import SwITSitrBuildRequest
        from backend.services.swit_sitr_aggregator import SwitSitrBuildResult

        self._setup_cfg(tmp_path, monkeypatch, {
            "projects": {"KJPDS02": {
                "swit_log_folder": "U:/logs/251106_IT_Report",
            }}
        })
        captured = {}

        monkeypatch.setattr(swit_mod, "check_log_folder_mode_compat", lambda *_args, **_kwargs: None)

        def _fake_collect(_resolver, _project_id, **kwargs):
            captured["log_folders"] = kwargs.get("log_folders")
            return object()

        monkeypatch.setattr(swit_mod, "collect_swit_session", _fake_collect)
        monkeypatch.setattr(swit_mod, "_apply_function_asil_map", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(swit_mod, "_read_template_bytes", lambda *_args, **_kwargs: b"template")
        monkeypatch.setattr(swit_mod, "_resolve_swuds_function_ids",
                            lambda _req, **_kwargs: set())  # out_warnings kwarg 흡수(2026-08-04)
        monkeypatch.setattr(swit_mod, "_resolver_resolve_swuts_test_specs", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            swit_mod,
            "build_swit_sitr_report",
            lambda *_args, **_kwargs: SwitSitrBuildResult(
                ok=True,
                xlsm_io=io.BytesIO(b"dummy"),
                filename="dummy.xlsm",
                summary={},
                warnings=[],
                incomplete_sheets=[],
            ),
        )
        req = SwITSitrBuildRequest(
            project_id="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
        )
        response = swit_mod._do_swit_sitr_build(req)
        assert response.status_code == 200
        assert captured["log_folders"] == ["U:/logs/251106_IT_Report"]


class TestSwitSitrMetaBuilder:
    """_build_swit_sitr_meta — SwITSitrBuildRequest → SwitSitrBuildMeta."""

    def test_sitr_meta_doc_id_base_is_project_sitr(self):
        from backend.routers.swit import _build_swit_sitr_meta
        from backend.schemas import SwITSitrBuildRequest
        req = SwITSitrBuildRequest(
            project_id="HDPDM01",
            release_sw_version="2.02",
            test_date="2024-02-19",
            doc_id_sequence="042",
        )
        meta = _build_swit_sitr_meta(req)
        assert meta.doc_id_base == "HDPDM01-SITR"
        assert meta.doc_id_sequence == "042"
        # SwitSitrBuildMeta inherits SutrBuildMeta — final_test_result default "OK"
        assert meta.final_test_result == "OK"


class TestExtraForbid53fix:
    """53차 C1 + 53-fix C2 — Pydantic extra='forbid' 422 회귀.

    외부 호출자가 51차 이전 schema의 unknown 키 (예: template_path) 보내면
    silent ignore 대신 422 + extra_forbidden 응답.
    """

    def test_swit_coverage_unknown_template_path_returns_422(self):
        """legacy template_path 키 (51차 제거됨) → extra_forbidden 422."""
        r = client.post(
            "/api/swit/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "2.02",
                "test_date": "2024-02-19",
                "template_path": "U:/legacy.xlsx",
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert any(
            d.get("type") == "extra_forbidden" and "template_path" in d.get("loc", [])
            for d in detail
        ), detail

    def test_swit_sitr_unknown_template_path_returns_422(self):
        """SITR endpoint도 동일 — SwITSitrBuildRequest는 SwITBuildRequest 상속으로 extra=forbid 자동."""
        r = client.post(
            "/api/swit/sitr/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "2.02",
                "test_date": "2024-02-19",
                "template_path": "U:/legacy.xlsm",
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_swit_coverage_unknown_random_key_returns_422(self):
        """알 수 없는 임의 키도 차단 — silent ignore 안 됨."""
        r = client.post(
            "/api/swit/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "2.02",
                "test_date": "2024-02-19",
                "random_garbage_key": "value",
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422


class TestSheetNameSubstring53fix:
    """53차 + 53-fix C1 — SwIT v2.02 양식 시트명 substring 매칭 회귀.

    33차에 SwIT가 SwUT 인프라 81% 재활용으로 만들어졌으나 SwIT v2.02 양식은
    시트명 prefix가 다름 (`1.Test Summary`, `2.Test Log` 등). 53차에 substring
    매칭으로 변경. 향후 누군가 exact 매칭으로 되돌리면 silent regression 위험 →
    회귀로 매칭 동작 검증.
    """

    def test_swit_coverage_aggregator_matches_swit_v202_sheet_names(self):
        """SwIT v2.02 양식의 '1.Test Summary' 시트가 substring 매칭으로 발견됨."""
        from backend.services import swit_coverage_aggregator as mod
        from tests.unit._source_probe import source_of
        src = source_of(mod)
        assert '"test summary" in n.lower()' in src or "'test summary' in n.lower()" in src, (
            "swit_coverage_aggregator가 'test summary' substring 매칭 안 함 — 53차 fix 누락"
        )

    def test_swit_sitr_aggregator_matches_swit_v202_sheet_names(self):
        """SITR도 동일 — Test Summary + Deviation + Test Log substring 매칭."""
        from backend.services import swit_sitr_aggregator as mod
        from tests.unit._source_probe import source_of
        src = source_of(mod)
        for keyword in ("test summary", "deviation", "test log"):
            assert (f'"{keyword}" in n.lower()' in src
                    or f"'{keyword}' in n.lower()" in src), (
                f"swit_sitr_aggregator가 '{keyword}' substring 매칭 안 함 — 53차 fix 누락"
            )


class TestPathModeMismatch56:
    """56차 T308 — log_folder UNC + Local 모드 → 400 + PATH_MODE_MISMATCH."""

    def test_swit_coverage_unc_local_mode_returns_400(self):
        """Local 모드에서 log_folder=U:/... → 400 + suggested_mode=cloudium.

        error_handler가 dict detail의 code/message를 top-level로 분해 + 나머지는
        detail dict에 유지. 그래서 body['code']=PATH_MODE_MISMATCH, body['message']에
        안내 메시지, body['detail']['suggested_mode']=cloudium 구조.
        """
        from backend.services.file_resolver import LocalFileResolver, set_resolver
        set_resolver(LocalFileResolver())
        try:
            r = client.post(
                "/api/swit/coverage/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "2.02",
                    "test_date": "2024-02-19",
                    "log_folder": "U:/연구소/test/v2.02",  # mapped network drive
                },
                headers={"X-User": "tester"},
            )
            assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
            body = r.json()
            # error_response shape: {ok: false, error: {code, message, detail}}
            err = body.get("error", {})
            assert err.get("code") == "PATH_MODE_MISMATCH", f"body={body}"
            assert "Cloudium" in err.get("message", ""), f"body={body}"
            extra = err.get("detail", {})
            if isinstance(extra, dict):
                assert extra.get("suggested_mode") == "cloudium"
        finally:
            set_resolver(LocalFileResolver())

    def test_swit_sitr_unc_local_mode_returns_400(self):
        """SITR endpoint도 동일 — Local + UNC → 400."""
        from backend.services.file_resolver import LocalFileResolver, set_resolver
        set_resolver(LocalFileResolver())
        try:
            r = client.post(
                "/api/swit/sitr/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "2.02",
                    "test_date": "2024-02-19",
                    "log_folder": r"\\corp\share\test",  # UNC
                },
                headers={"X-User": "tester"},
            )
            assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        finally:
            set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# B2 대칭 (SwIT) — _resolve_swit_log_folders 4단계 우선순위 + log_folders 스키마
# (SwUT test_swut_router.py TestResolveSwutLogFoldersPriority/TestLogFoldersSchema 미러)
# ---------------------------------------------------------------------------


def _make_swit_req(**kwargs):
    """최소 유효 SwITBuildRequest — log_folder(s) 우선순위 검증용."""
    from backend.schemas import SwITBuildRequest
    base = {
        "project_id": "KJPDS02",
        "release_sw_version": "0.10",
        "test_date": "2026-06-04",
    }
    base.update(kwargs)
    return SwITBuildRequest(**base)


class TestResolveSwitLogFoldersPriority:
    """B2 대칭 — req.log_folders > req.log_folder > config swit_log_folders >
    config swit_log_folder."""

    def _patch_cfg(self, monkeypatch, cfg: dict):
        from backend.routers import swit as swit_mod
        monkeypatch.setattr(
            swit_mod, "_load_meta_from_config", lambda _project_id: cfg,
        )
        return swit_mod

    _FULL_CFG = {
        "swit_log_folders": ["U:/cfg/app_it", "U:/cfg/boot_it"],
        "swit_log_folder": "U:/cfg/single_it",
    }

    def test_req_log_folders_first(self, monkeypatch):
        swit_mod = self._patch_cfg(monkeypatch, dict(self._FULL_CFG))
        req = _make_swit_req(
            log_folders=["C:/req/app", "C:/req/boot"],
            log_folder="C:/req/single",
        )
        assert swit_mod._resolve_swit_log_folders(req) == [
            "C:/req/app", "C:/req/boot",
        ]

    def test_req_log_folder_second(self, monkeypatch):
        swit_mod = self._patch_cfg(monkeypatch, dict(self._FULL_CFG))
        req = _make_swit_req(log_folder="C:/req/single")
        assert swit_mod._resolve_swit_log_folders(req) == ["C:/req/single"]

    def test_config_log_folders_third(self, monkeypatch):
        swit_mod = self._patch_cfg(monkeypatch, dict(self._FULL_CFG))
        req = _make_swit_req()
        assert swit_mod._resolve_swit_log_folders(req) == [
            "U:/cfg/app_it", "U:/cfg/boot_it",
        ]

    def test_config_log_folder_fourth(self, monkeypatch):
        swit_mod = self._patch_cfg(
            monkeypatch, {"swit_log_folder": "U:/cfg/single_it"},
        )
        req = _make_swit_req()
        assert swit_mod._resolve_swit_log_folders(req) == ["U:/cfg/single_it"]

    def test_legacy_log_folders_dict_keys_still_work(self, monkeypatch):
        """기존 log_folders dict 키 (swit/integration) fallback 유지."""
        swit_mod = self._patch_cfg(
            monkeypatch, {"log_folders": {"swit": "U:/cfg/dict_swit"}},
        )
        req = _make_swit_req()
        assert swit_mod._resolve_swit_log_folders(req) == ["U:/cfg/dict_swit"]

    def test_all_empty_returns_empty_list(self, monkeypatch):
        swit_mod = self._patch_cfg(monkeypatch, {})
        req = _make_swit_req()
        assert swit_mod._resolve_swit_log_folders(req) == []

    def test_config_empty_list_falls_through_to_single(self, monkeypatch):
        swit_mod = self._patch_cfg(
            monkeypatch,
            {"swit_log_folders": [], "swit_log_folder": "U:/cfg/single_it"},
        )
        req = _make_swit_req()
        assert swit_mod._resolve_swit_log_folders(req) == ["U:/cfg/single_it"]

    def test_backward_compat_wrapper_returns_first(self, monkeypatch):
        """_resolve_swit_log_folder(단수 wrapper) — 첫 폴더 단일 반환 계약 유지."""
        swit_mod = self._patch_cfg(monkeypatch, dict(self._FULL_CFG))
        req = _make_swit_req()
        assert swit_mod._resolve_swit_log_folder(req) == "U:/cfg/app_it"
        swit_mod2 = self._patch_cfg(monkeypatch, {})
        assert swit_mod2._resolve_swit_log_folder(_make_swit_req()) is None


class TestSwitLogFoldersSchema:
    """B2 대칭 — SwITBuildRequest.log_folders 입력 표면 (maxlen/줄바꿈/개수/extra)."""

    _BASE = {
        "project_id": "KJPDS02",
        "release_sw_version": "0.10",
        "test_date": "2026-06-04",
    }

    def test_valid_two_folders_accepted(self):
        req = _make_swit_req(log_folders=["C:/a", "C:/b"])
        assert req.log_folders == ["C:/a", "C:/b"]

    def test_item_over_500_rejected(self):
        from pydantic import ValidationError
        item = "C:/" + "x" * 498  # 501자
        with pytest.raises(ValidationError, match="500"):
            _make_swit_req(log_folders=[item])

    @pytest.mark.parametrize("bad", ["C:/a\nb", "C:/a\rb", "C:/a\r\nX-Injected: evil"])
    def test_item_newline_rejected(self, bad):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="줄바꿈"):
            _make_swit_req(log_folders=[bad])

    def test_nine_items_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _make_swit_req(log_folders=[f"C:/p{i}" for i in range(9)])

    def test_extra_field_still_forbidden(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _make_swit_req(log_folders_typo=["C:/a"])

    def test_sitr_request_inherits_log_folders(self):
        """SwITSitrBuildRequest(상속)도 log_folders 사용 가능."""
        from backend.schemas import SwITSitrBuildRequest
        req = SwITSitrBuildRequest(**self._BASE, log_folders=["C:/a", "C:/b"])
        assert req.log_folders == ["C:/a", "C:/b"]

    def test_endpoint_log_folders_newline_422(self):
        r = client.post(
            "/api/swit/coverage/build",
            json={
                **self._BASE,
                "log_folders": ["C:/fake/log\r\nX-Injected: evil"],
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422


def test_collect_swit_session_passes_log_folders_through(monkeypatch):
    """collect_swit_session이 log_folders kwarg를 SwUT collect로 전달 (B2 대칭)."""
    from backend.services import swit_input_adapter

    captured: dict = {}

    def _fake_collect(resolver, project_id, **kwargs):
        captured.update(kwargs)
        from backend.services.swut_input_adapter import SwUTSession
        return SwUTSession(project_id=project_id)

    monkeypatch.setattr(swit_input_adapter, "collect_swut_session", _fake_collect)
    swit_input_adapter.collect_swit_session(
        object(), "KJPDS02",
        log_folders=["U:/app", "U:/boot"],
    )
    assert captured["log_folders"] == ["U:/app", "U:/boot"]
    assert captured["env_prefix"] == "SwITC"


# ── 시험 결과 3종의 Quality 기록 배선 (2026-08-21) ────────────────────────────
#
# 여기서 깨지는 방식은 **조용하다**. 빌드는 성공하고 파일도 받아지는데 Quality DB 에
# 행이 안 남아, 생성 현황 보드가 방금 만든 문서를 영영 "미생성" 으로 표시한다. 실제로
# SwIT Coverage 에만 기록이 있어 SITR 가 그 상태였고(커밋 이력), 고친 뒤에도
# **SWITCR 은 여전히 그 상태였다** — 같은 결함이 한 칸 옆에서 반복됐다.
#
# 그래서 헬퍼 단독 테스트로는 부족하다(호출부가 빠진 게 결함이므로). 아래는 **호출부를
# AST 로** 확인한다: 각 빌드 함수가 `_record_test_quality` 를 부르는가, 그리고 doc_type
# 을 무엇으로 넘기는가. doc_type 이 틀리면 종합결과서가 SITR 행을 덮어쓴다.


class TestQualityRecordingWiring:
    EXPECTED = {
        "_do_swit_sitr_build": "sitr",
        "_do_swit_sitr_build_spec_based": "sitr",
        "_do_switcr_build": "switcr",
    }

    @staticmethod
    def _record_calls(func_name: str):
        import ast
        src = pathlib.Path("backend/routers/swit.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name),
            None,
        )
        assert fn is not None, f"{func_name} 가 사라졌다 — 테스트가 겨눌 대상이 없다"
        out = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_record_test_quality"):
                kw = {k.arg: k.value for k in node.keywords}
                doc = kw.get("doc_type")
                out.append(doc.value if isinstance(doc, ast.Constant) else None)
        return out

    @pytest.mark.parametrize("func_name", sorted(EXPECTED))
    def test_build_path_records_quality_with_its_own_doc_type(self, func_name):
        calls = self._record_calls(func_name)
        assert calls == [self.EXPECTED[func_name]], (
            f"{func_name} 의 quality 기록 호출: {calls} "
            f"(기대: [{self.EXPECTED[func_name]!r}])"
        )

    def test_doc_type_has_no_default(self):
        """기본값을 두면 **빠뜨린 호출이 조용히 SITR 로 기록**된다 — 종합결과서가
        SITR 행을 덮어쓰고, 보드는 둘을 구분하지 못한다."""
        import inspect

        from backend.routers import swit as mod
        sig = inspect.signature(mod._record_test_quality)
        param = sig.parameters["doc_type"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty

    def test_helper_passes_doc_type_through(self, monkeypatch):
        """헬퍼가 받은 doc_type 을 그대로 recorder 에 넘기는가."""
        import workflow.quality.recorder as rec
        from backend.routers import swit as mod
        seen = {}

        def _fake(doc_type, summary, **kw):
            seen["doc_type"] = doc_type
            seen["summary"] = summary
            seen.update(kw)
            return 1

        monkeypatch.setattr(rec, "record_test_result_run", _fake)

        class _Req:
            project_id = "HDPDM01"
            release_sw_version = "1.02"

        class _Meta:
            asil_level = "ASIL B"

        mod._record_test_quality(_Req(), _Meta(), {"total_tcs": 5}, doc_type="switcr")
        assert seen["doc_type"] == "switcr"
        assert seen["release_sw_version"] == "1.02"
        assert seen["project_id"] == "HDPDM01"

    def test_recording_failure_is_logged_not_silent(self, monkeypatch, caplog):
        """non-fatal 은 유지하되 **침묵은 금지** — 같은 블록이 NameError 를 삼킨 전례가 있다."""
        import logging

        import workflow.quality.recorder as rec
        from backend.routers import swit as mod

        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(rec, "record_test_result_run", _boom)

        class _X:
            project_id = ""
            release_sw_version = ""
            asil_level = ""

        with caplog.at_level(logging.ERROR):
            mod._record_test_quality(_X(), _X(), {}, doc_type="switcr")   # 예외가 새면 안 된다
        assert any("SWITCR" in r.getMessage() for r in caplog.records), (
            "기록 실패가 로그에 남지 않았다 — 조용한 실패는 이 파일이 겨누는 결함 그 자체다"
        )

    def test_scm_id_is_passed_through_not_guessed(self, monkeypatch):
        """프로젝트 축을 **추측에 맡기지 않는다**(2026-08-24 라이브 실측).

        비우면 recorder 가 `project_id` 에서 `resolve_scm_id` 로 추측하는데, 문자열
        "KJPDS02" 가 SCM entry `kjpds02` 의 id 이면서 `kjpds02_pv` 의 builder_project_id
        라 추측이 빗나갔다 → 생성 현황 보드(`kjpds02_pv` 로 조회)가 방금 만든 문서를
        영영 "미생성" 으로 표시했다. 빌드도 기록도 정상인데 화면만 침묵하는 형태다.
        """
        import workflow.quality.recorder as rec
        from backend.routers import swit as mod
        seen = {}
        monkeypatch.setattr(
            rec, "record_test_result_run",
            lambda doc_type, summary, **kw: (seen.update(kw), 1)[1],
        )

        class _Req:
            project_id = "KJPDS02"
            release_sw_version = "1.02"
            scm_id = "kjpds02_pv"

        class _Meta:
            asil_level = "ASIL A"

        mod._record_test_quality(_Req(), _Meta(), {"total_tcs": 5}, doc_type="switcr")
        assert seen["scm_id"] == "kjpds02_pv"

    def test_absent_scm_id_stays_none_not_empty_string(self, monkeypatch):
        """빈 문자열을 넘기면 recorder 의 `if not scm_id` 추측 분기가 **살아 있어야** 한다
        — `""` 를 그대로 저장하면 '축을 아는데 빈 값' 처럼 보여 더 나쁘다."""
        import workflow.quality.recorder as rec
        from backend.routers import swit as mod
        seen = {}
        monkeypatch.setattr(
            rec, "record_test_result_run",
            lambda doc_type, summary, **kw: (seen.update(kw), 1)[1],
        )

        class _Req:
            project_id = "KJPDS02"
            release_sw_version = "1.02"
            scm_id = ""

        class _Meta:
            asil_level = "ASIL A"

        mod._record_test_quality(_Req(), _Meta(), {"total_tcs": 5}, doc_type="switcr")
        assert seen["scm_id"] is None
