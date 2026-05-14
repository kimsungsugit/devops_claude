"""38차 I2 — 라우터 _safety decorator 회귀.

run_build_safely / run_consistency_safely의 5 예외 시나리오:
  1. HTTPException 재raise (의도된 client error)
  2. FileNotFoundError → 404
  3. PermissionError → 403
  4. ValueError → 400
  5. 기타 Exception → 500 (메시지 본문 미노출)
+ 정상 응답 통과 시나리오.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.routers._safety import (  # noqa: E402
    run_build_safely,
    run_consistency_safely,
)


_LOGGER = logging.getLogger("test_router_safety")


def _fake_req():
    """SwUT/SwIT request 모방 — 공통 필드만 갖춘 namespace."""
    class _R:
        project_id = "HDPDM01"
        release_sw_version = "2.02"
        coverage_path = "C:/fake/cov.xlsx"
        sutr_path = "C:/fake/sutr.xlsm"
    return _R()


# ---------------------------------------------------------------------------
# build wrapper
# ---------------------------------------------------------------------------

class TestRunBuildSafely:
    """run_build_safely의 5 예외 분기 + 정상."""

    def test_normal_passthrough(self):
        """builder 정상 응답 → 그대로 통과."""
        resp = MagicMock()
        resp.headers = {"content-length": "1024"}
        build_fn = MagicMock(return_value=resp)
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            result = run_build_safely(
                series="swut", kind="coverage",
                build_fn=build_fn, req=_fake_req(), logger=_LOGGER,
            )
        assert result is resp
        build_fn.assert_called_once()

    def test_http_exception_reraised(self):
        """HTTPException은 sanitize 없이 그대로 raise (의도된 client error)."""
        build_fn = MagicMock(side_effect=HTTPException(status_code=429, detail="rate limited"))
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_build_safely(
                    series="swut", kind="coverage",
                    build_fn=build_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 429
        assert exc.value.detail == "rate limited"

    def test_file_not_found_returns_404(self):
        build_fn = MagicMock(side_effect=FileNotFoundError("missing template"))
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_build_safely(
                    series="swit", kind="sitr",
                    build_fn=build_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 404
        # 메시지에 path leak 없음 — type 이름만
        assert "FileNotFoundError" in exc.value.detail
        assert "missing template" not in exc.value.detail

    def test_permission_error_returns_403(self):
        build_fn = MagicMock(side_effect=PermissionError("denied"))
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_build_safely(
                    series="swut", kind="sutr",
                    build_fn=build_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 403

    def test_value_error_returns_400(self):
        """ValueError는 입력 검증 실패 — 400. e 메시지는 detail에 노출 가능."""
        build_fn = MagicMock(side_effect=ValueError("invalid release_sw_version"))
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_build_safely(
                    series="swit", kind="coverage",
                    build_fn=build_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 400
        assert "invalid release_sw_version" in str(exc.value.detail)

    def test_unexpected_exception_returns_500_with_type_only(self):
        """기타 Exception → 500. 메시지 본문은 sensitive — type 이름만 노출."""
        secret = "sensitive_internal_path"

        class _CustomError(RuntimeError):
            pass

        build_fn = MagicMock(side_effect=_CustomError(secret))
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_build_safely(
                    series="swut", kind="coverage",
                    build_fn=build_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 500
        assert "_CustomError" in exc.value.detail
        assert secret not in exc.value.detail, "sensitive 본문 누설 — type 이름만 노출되어야 함"


# ---------------------------------------------------------------------------
# consistency wrapper
# ---------------------------------------------------------------------------

class TestRunConsistencySafely:
    """consistency check wrapper — build와 동일 분기 + dict 응답 통과."""

    def test_normal_passthrough_dict(self):
        check_fn = MagicMock(return_value={
            "ok": True, "issues": [], "parse_warnings": [],
        })
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            result = run_consistency_safely(
                series="swut", check_fn=check_fn, req=_fake_req(), logger=_LOGGER,
            )
        assert result == {"ok": True, "issues": [], "parse_warnings": []}

    def test_http_exception_reraised(self):
        check_fn = MagicMock(side_effect=HTTPException(status_code=400, detail="bad"))
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_consistency_safely(
                    series="swit", check_fn=check_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 400

    def test_file_not_found_returns_404(self):
        check_fn = MagicMock(side_effect=FileNotFoundError())
        with patch("backend.routers._safety.get_current_user", return_value="tester"):
            with pytest.raises(HTTPException) as exc:
                run_consistency_safely(
                    series="swut", check_fn=check_fn, req=_fake_req(), logger=_LOGGER,
                )
        assert exc.value.status_code == 404
