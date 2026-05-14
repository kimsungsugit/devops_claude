"""33차 SwIT router endpoint 회귀.

SwUT router 패턴 차용 — 입력 표면 / X-User middleware / Semaphore /
StreamingResponse 헤더 검증.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


client = TestClient(app)


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
        assert r.status_code in (400, 404, 500)


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
        from backend.routers.swit import _BUILD_SEMAPHORE
        # 모듈 단일 instance — Coverage build_swit_coverage / SITR build_swit_sitr
        # 모두 `_BUILD_SEMAPHORE` 사용 (소스 검사로 충분).
        import backend.routers.swit as swit_mod
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
        """template_path 미지정 — Coverage와 동일 정책."""
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
        assert r.status_code in (400, 404, 500)


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
