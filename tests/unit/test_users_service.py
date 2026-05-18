"""45차 C1 — users service 회귀 (config/users.json CRUD + bcrypt verify)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def _isolated_users(tmp_path, monkeypatch):
    """각 test 격리 — tmp users.json + cache 초기화."""
    p = tmp_path / "users.json"
    from backend.services import users as us
    monkeypatch.setattr(us, "USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(us, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(us, "_LOCK", threading.Lock())
    us._cache["mtime"] = 0.0
    us._cache["users"] = {}
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USER", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("JWT_SECRET", "test_secret_minimum_32bytes_xxxxxxxxxxxxxxxx")
    return p


class TestAddUser:
    def test_add_user_basic(self, _isolated_users):
        from backend.services import users as us
        result = us.add_user("alice", "password123")
        assert result["added"] is True
        assert result["username"] == "alice"
        assert result["must_change_password"] is True
        assert us.user_exists("alice") is True

    def test_add_duplicate_user(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        result = us.add_user("alice", "another_pw_123")
        assert result["added"] is False

    def test_add_user_case_insensitive(self, _isolated_users):
        from backend.services import users as us
        us.add_user("Alice", "password123")
        assert us.user_exists("alice") is True
        assert us.user_exists("ALICE") is True
        # 원래 case 보존
        record = us.get_user("alice")
        assert record["username"] == "Alice"

    def test_add_user_short_password_rejected(self, _isolated_users):
        from backend.services import users as us
        with pytest.raises(ValueError, match="8자"):
            us.add_user("alice", "short")

    def test_add_user_empty_username_rejected(self, _isolated_users):
        from backend.services import users as us
        with pytest.raises(ValueError, match="비어"):
            us.add_user("", "password123")


class TestVerifyCredentials:
    def test_verify_valid_credentials(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        result = us.verify_credentials("alice", "password123")
        assert result is not None
        assert result["username"] == "alice"

    def test_verify_wrong_password(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        assert us.verify_credentials("alice", "wrong") is None

    def test_verify_unknown_user(self, _isolated_users):
        from backend.services import users as us
        assert us.verify_credentials("nobody", "password123") is None

    def test_verify_case_insensitive_username(self, _isolated_users):
        from backend.services import users as us
        us.add_user("Alice", "password123")
        assert us.verify_credentials("alice", "password123") is not None
        assert us.verify_credentials("ALICE", "password123") is not None


class TestChangePassword:
    def test_change_password(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        result = us.change_password("alice", "new_password456")
        assert result["changed"] is True
        # 새 PW로만 verify 가능
        assert us.verify_credentials("alice", "new_password456") is not None
        assert us.verify_credentials("alice", "password123") is None
        # must_change_password 초기화
        record = us.get_user("alice")
        assert record["must_change_password"] is False

    def test_change_password_unknown_user_raises(self, _isolated_users):
        from backend.services import users as us
        with pytest.raises(ValueError, match="없음"):
            us.change_password("nobody", "new_password456")

    def test_change_password_short_rejected(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        with pytest.raises(ValueError, match="8자"):
            us.change_password("alice", "short")


class TestRemoveUser:
    def test_remove_user(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        result = us.remove_user("alice")
        assert result["removed"] is True
        assert us.user_exists("alice") is False

    def test_remove_unknown_user(self, _isolated_users):
        from backend.services import users as us
        result = us.remove_user("nobody")
        assert result["removed"] is False


class TestListUsers:
    def test_list_users_excludes_password_hash(self, _isolated_users):
        from backend.services import users as us
        us.add_user("alice", "password123")
        us.add_user("bob", "password456")
        result = us.list_users()
        assert len(result) == 2
        for u in result:
            assert "password_hash" not in u
            assert "username" in u
            assert "must_change_password" in u
            assert "created_at" in u


class TestBootstrap:
    def test_bootstrap_no_env(self, _isolated_users):
        from backend.services import users as us
        result = us.bootstrap_admin_user_from_env()
        assert result["action"] == "skipped_no_env"

    def test_bootstrap_only_username(self, _isolated_users, monkeypatch):
        from backend.services import users as us
        monkeypatch.setenv("BOOTSTRAP_ADMIN_USER", "alice")
        # password 없음 → 마찬가지로 skipped_no_env
        result = us.bootstrap_admin_user_from_env()
        assert result["action"] == "skipped_no_env"

    def test_bootstrap_both_env(self, _isolated_users, monkeypatch):
        from backend.services import users as us
        monkeypatch.setenv("BOOTSTRAP_ADMIN_USER", "alice")
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "secret12345")
        result = us.bootstrap_admin_user_from_env()
        assert result["action"] == "bootstrapped"
        assert result["username"] == "alice"
        assert us.verify_credentials("alice", "secret12345") is not None

    def test_bootstrap_skipped_if_users_exist(self, _isolated_users, monkeypatch):
        from backend.services import users as us
        us.add_user("existing", "password123")
        monkeypatch.setenv("BOOTSTRAP_ADMIN_USER", "newadmin")
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "secret12345")
        result = us.bootstrap_admin_user_from_env()
        assert result["action"] == "skipped_has_users"
        # newadmin 등록 안 됨
        assert us.user_exists("newadmin") is False
