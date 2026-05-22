"""56차 T308 — path_mode_check.py 회귀.

UNC + mapped network drive 감지 + Local/Cloudium 모드 분기 + 400 응답 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import HTTPException  # noqa: E402

from backend.services.path_mode_check import (  # noqa: E402
    check_log_folder_mode_compat,
    is_network_path,
)


class TestIsNetworkPath:
    def test_unc_prefix_detected(self):
        """`\\\\server\\share` 형식 UNC 감지."""
        assert is_network_path(r"\\corp\share\folder") is True
        assert is_network_path(r"\\192.168.1.1\share") is True

    def test_mapped_network_drive_letters(self):
        """회사 mapped drive (U/V/W/X/Y/Z) 감지."""
        assert is_network_path("U:/연구소/test") is True
        assert is_network_path("V:/data") is True
        assert is_network_path("Z:\\share") is True
        # 대소문자 무관
        assert is_network_path("u:/path") is True

    def test_local_drive_letters_not_network(self):
        """A-T (보통 local HDD/SSD/USB) 는 network 아님."""
        assert is_network_path("C:/Users/test") is False
        assert is_network_path("D:/Project") is False
        assert is_network_path("E:/backup") is False
        assert is_network_path("T:/temp") is False

    def test_empty_or_none(self):
        """빈 string / None / 공백 → False."""
        assert is_network_path("") is False
        assert is_network_path(None) is False  # type: ignore[arg-type]
        assert is_network_path("   ") is False


class TestCheckLogFolderModeCompat:
    """Local + UNC 차단 / Cloudium 통과 / 빈 log_folder 통과."""

    def test_local_mode_unc_raises_400(self):
        """Local 모드 + UNC path → HTTPException 400 + PATH_MODE_MISMATCH."""
        from backend.services.file_resolver import LocalFileResolver
        resolver = LocalFileResolver()
        with pytest.raises(HTTPException) as exc:
            check_log_folder_mode_compat(r"\\corp\share", resolver)
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "PATH_MODE_MISMATCH"
        assert exc.value.detail["suggested_mode"] == "cloudium"
        assert "Cloudium" in exc.value.detail["message"]

    def test_local_mode_mapped_drive_raises_400(self):
        """Local 모드 + U:/ → 400."""
        from backend.services.file_resolver import LocalFileResolver
        resolver = LocalFileResolver()
        with pytest.raises(HTTPException) as exc:
            check_log_folder_mode_compat("U:/연구소/test", resolver)
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "PATH_MODE_MISMATCH"

    def test_local_mode_local_path_passes(self):
        """Local 모드 + local path (C:/) → 통과."""
        from backend.services.file_resolver import LocalFileResolver
        resolver = LocalFileResolver()
        check_log_folder_mode_compat("C:/Users/test", resolver)  # no raise

    def test_cloudium_mode_unc_passes(self, monkeypatch):
        """Cloudium 모드 + UNC → worker가 처리, pre-flight 통과."""
        from backend.services.file_resolver import CloudiumFileResolver
        resolver = CloudiumFileResolver(allowed_prefixes="C:/test")
        check_log_folder_mode_compat(r"\\corp\share", resolver)  # no raise

    def test_empty_log_folder_passes(self):
        """빈 log_folder → 검사 skip (사용자가 입력 안 한 케이스)."""
        from backend.services.file_resolver import LocalFileResolver
        resolver = LocalFileResolver()
        check_log_folder_mode_compat("", resolver)  # no raise
        check_log_folder_mode_compat(None, resolver)  # type: ignore[arg-type]
