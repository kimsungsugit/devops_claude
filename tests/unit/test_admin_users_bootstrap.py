"""41차 T273 W2 — bootstrap_from_env 회귀.

4 시나리오:
  1. env 없음 → skipped_no_env
  2. env 있음 + admin 비어있음 → bootstrapped
  3. env 있음 + 이미 admin 있음 → skipped_has_admins (idempotent)
  4. env 다명 (콤마/공백) → 모두 등록
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import admin_users as au  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_path(tmp_path, monkeypatch):
    """각 test 격리 + cache 초기화 + env 변수 cleanup."""
    p = tmp_path / "admin_users.json"
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()
    # env cleanup — 다른 test의 잔재 차단
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERS", raising=False)
    return p


class TestBootstrapFromEnv:
    def test_no_env_returns_skipped(self, _isolated_path):
        result = au.bootstrap_from_env()
        assert result["action"] == "skipped_no_env"
        assert result["added"] == []
        # admin list는 여전히 빈 상태
        assert au.load_admins() == set()

    def test_env_set_with_empty_admin_bootstraps(self, _isolated_path, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_USERS", "hbrnd2")
        result = au.bootstrap_from_env()
        assert result["action"] == "bootstrapped"
        assert "hbrnd2" in result["added"]
        # admin list 등록 확인
        assert au.is_admin("hbrnd2") is True

    def test_env_set_with_existing_admins_skipped(self, _isolated_path, monkeypatch):
        """이미 admin 있으면 env 무시 — idempotent."""
        au.save_admins(["existing_admin"])
        monkeypatch.setenv("BOOTSTRAP_ADMIN_USERS", "new_user")
        result = au.bootstrap_from_env()
        assert result["action"] == "skipped_has_admins"
        assert result["added"] == []
        # 기존 admin 그대로, env user 등록 안 됨
        assert au.is_admin("existing_admin") is True
        assert au.is_admin("new_user") is False

    def test_env_multi_users_comma_separated(self, _isolated_path, monkeypatch):
        """콤마 list — 공백 trim + 빈 항목 skip."""
        monkeypatch.setenv("BOOTSTRAP_ADMIN_USERS", " alice , bob , , charlie ")
        result = au.bootstrap_from_env()
        assert result["action"] == "bootstrapped"
        assert set(result["added"]) == {"alice", "bob", "charlie"}
        assert au.is_admin("alice") is True
        assert au.is_admin("bob") is True
        assert au.is_admin("charlie") is True
