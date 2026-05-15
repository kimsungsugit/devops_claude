"""39차 — Cloudium extra_prefixes CRUD 회귀.

10 시나리오: load/save/add 중복/remove 미존재/atomic write/load 손상 graceful.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import cloudium_extra_prefixes as cep  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_path(tmp_path, monkeypatch):
    """각 test 마다 별도 임시 JSON 파일 사용 — 영구 저장소 격리."""
    p = tmp_path / "extra.json"
    monkeypatch.setattr(cep, "PREFIXES_PATH", p)
    # _LOCK도 임시 (filelock은 path-bound)
    try:
        from filelock import FileLock
        monkeypatch.setattr(cep, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(cep, "_LOCK", threading.Lock())
    return p


class TestLoadExtraPrefixes:
    def test_file_missing_returns_empty_list(self, _isolated_path):
        assert cep.load_extra_prefixes() == []
        # _ensure_file이 빈 stub 생성
        assert _isolated_path.exists()

    def test_normal_load(self, _isolated_path):
        _isolated_path.write_text(
            json.dumps({"prefixes": ["U:/a", "U:/b"], "schema_version": 1}),
            encoding="utf-8",
        )
        assert cep.load_extra_prefixes() == ["U:/a", "U:/b"]

    def test_corrupted_file_graceful_returns_empty(self, _isolated_path):
        _isolated_path.write_text("{not valid json", encoding="utf-8")
        result = cep.load_extra_prefixes()
        assert result == []
        # 손상 파일은 .invalid.json으로 백업
        assert _isolated_path.with_suffix(".invalid.json").exists()


class TestSaveExtraPrefixes:
    def test_save_creates_atomic(self, _isolated_path):
        cep.save_extra_prefixes(["U:/path/A", "U:/path/B"])
        data = json.loads(_isolated_path.read_text(encoding="utf-8"))
        assert data["prefixes"] == ["U:/path/A", "U:/path/B"]
        assert data["schema_version"] == 1

    def test_save_overwrites_existing(self, _isolated_path):
        cep.save_extra_prefixes(["U:/first"])
        cep.save_extra_prefixes(["U:/second"])
        assert cep.load_extra_prefixes() == ["U:/second"]


class TestAddPrefix:
    def test_add_new_prefix(self, _isolated_path):
        result = cep.add_prefix("U:/test/path")
        assert result["added"] is True
        assert result["prefix"] == "U:/test/path"
        assert result["prefixes"] == ["U:/test/path"]

    def test_add_duplicate_rejected(self, _isolated_path):
        cep.add_prefix("U:/dup")
        result = cep.add_prefix("U:/dup")
        assert result["added"] is False
        assert len(result["prefixes"]) == 1

    def test_add_case_insensitive_duplicate_rejected_on_windows(self, _isolated_path):
        """Windows에서 case-insensitive 비교 — file_resolver._normalize_for_compare 재사용."""
        cep.add_prefix("U:/CamelCase/Path")
        result = cep.add_prefix("u:/camelcase/path")
        # Windows에서는 동일 — added=False 기대
        import sys as _sys
        if _sys.platform == "win32":
            assert result["added"] is False
        else:  # POSIX는 case-sensitive
            assert result["added"] is True

    def test_add_empty_raises(self, _isolated_path):
        with pytest.raises(ValueError, match="비어있음"):
            cep.add_prefix("")
        with pytest.raises(ValueError, match="비어있음"):
            cep.add_prefix("   ")


class TestRemovePrefix:
    def test_remove_existing(self, _isolated_path):
        cep.add_prefix("U:/a")
        cep.add_prefix("U:/b")
        result = cep.remove_prefix("U:/a")
        assert result["removed"] is True
        assert result["prefixes"] == ["U:/b"]

    def test_remove_missing_graceful(self, _isolated_path):
        cep.add_prefix("U:/exists")
        result = cep.remove_prefix("U:/never_added")
        assert result["removed"] is False
        assert result["prefixes"] == ["U:/exists"]
