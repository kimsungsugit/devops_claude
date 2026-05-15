"""40차 T268 — admin_users CRUD 회귀.

10 시나리오: load/save/add/remove/case-insensitive/cache invalidate/atomic.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import admin_users as au  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_path(tmp_path, monkeypatch):
    """각 test 마다 별도 임시 admin_users.json + cache 초기화."""
    p = tmp_path / "admin_users.json"
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    # cache 초기화 (mtime=0이면 다음 load_admins에서 disk read)
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()
    return p


class TestLoadAdmins:
    def test_missing_file_returns_empty_set(self, _isolated_path):
        assert au.load_admins() == set()
        assert _isolated_path.exists()  # _ensure_file 동작 확인

    def test_normal_load(self, _isolated_path):
        _isolated_path.write_text(
            json.dumps({"admins": ["hbrnd2", "tester"], "schema_version": 1}),
            encoding="utf-8",
        )
        assert au.load_admins() == {"hbrnd2", "tester"}

    def test_corrupted_file_graceful(self, _isolated_path):
        _isolated_path.write_text("{not valid json", encoding="utf-8")
        result = au.load_admins()
        assert result == set()
        assert _isolated_path.with_suffix(".invalid.json").exists()


class TestIsAdmin:
    def test_admin_user_recognized(self, _isolated_path):
        au.save_admins(["hbrnd2"])
        assert au.is_admin("hbrnd2") is True

    def test_case_insensitive(self, _isolated_path):
        au.save_admins(["Admin"])
        assert au.is_admin("admin") is True
        assert au.is_admin("ADMIN") is True
        assert au.is_admin("AdMiN") is True

    def test_non_admin_rejected(self, _isolated_path):
        au.save_admins(["hbrnd2"])
        assert au.is_admin("guest") is False

    def test_default_user_rejected(self, _isolated_path):
        au.save_admins(["default"])
        # "default"는 user_context fallback 값 — 명시 거부
        assert au.is_admin("default") is False
        assert au.is_admin("") is False


class TestAddAdmin:
    def test_add_new(self, _isolated_path):
        result = au.add_admin("alice")
        assert result["added"] is True
        assert "alice" in result["admins"]

    def test_add_duplicate_rejected(self, _isolated_path):
        au.add_admin("alice")
        result = au.add_admin("alice")
        assert result["added"] is False

    def test_add_case_insensitive_duplicate(self, _isolated_path):
        au.add_admin("Alice")
        result = au.add_admin("alice")
        assert result["added"] is False


class TestRemoveAdmin:
    def test_remove_existing(self, _isolated_path):
        au.add_admin("alice")
        au.add_admin("bob")
        result = au.remove_admin("alice")
        assert result["removed"] is True
        assert "alice" not in result["admins"]
        assert "bob" in result["admins"]

    def test_remove_missing_graceful(self, _isolated_path):
        au.add_admin("alice")
        result = au.remove_admin("never_added")
        assert result["removed"] is False
