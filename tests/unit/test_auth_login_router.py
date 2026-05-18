"""45차 C1 — POST /api/auth/login + /refresh + /change-password 회귀.

기존 test_auth_router.py는 X-User 신뢰 모델 (40~44차) 검증.
본 파일은 JWT 인증 흐름 (login → access/refresh → change-password) 검증.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import admin_users as au  # noqa: E402
from backend.services import users as us  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """각 test 격리된 admin_users.json + users.json + JWT secret."""
    # admin_users.json
    ap = tmp_path / "admin_users.json"
    ap.write_text('{"admins": ["alice"], "schema_version": 1}', encoding="utf-8")
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", ap)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(ap) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()

    # users.json
    up = tmp_path / "users.json"
    monkeypatch.setattr(us, "USERS_PATH", up)
    try:
        from filelock import FileLock
        monkeypatch.setattr(us, "_LOCK", FileLock(str(up) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(us, "_LOCK", threading.Lock())
    us._cache["mtime"] = 0.0
    us._cache["users"] = {}

    # JWT secret + dev mode disabled (JWT 검증 강제)
    monkeypatch.setenv("JWT_SECRET", "test_secret_minimum_32bytes_xxxxxxxxxxxxxxxx")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_EXPIRE_DAYS", "7")
    monkeypatch.delenv("DEV_MODE_X_USER_FALLBACK", raising=False)

    # alice 사용자 등록 (admin)
    us.add_user("alice", "secret_password_12", must_change_password=False)
    return tmp_path


class TestLogin:
    def test_login_success(self, _isolated):
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["username"] == "alice"
        assert data["is_admin"] is True
        assert data["must_change_password"] is False

    def test_login_wrong_password(self, _isolated):
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "wrong",
        })
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_unknown_user(self, _isolated):
        r = client.post("/api/auth/login", json={
            "username": "nobody",
            "password": "anything",
        })
        # timing-safe — 동일 401 + 동일 code
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_missing_password(self, _isolated):
        r = client.post("/api/auth/login", json={"username": "alice"})
        assert r.status_code == 422  # Pydantic validation

    def test_login_username_with_newline_rejected(self, _isolated):
        r = client.post("/api/auth/login", json={
            "username": "alice\n",
            "password": "secret_password_12",
        })
        assert r.status_code == 422


class TestRefresh:
    def _get_tokens(self):
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        return r.json()

    def test_refresh_success(self, _isolated):
        tokens = self._get_tokens()
        r = client.post("/api/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert data["username"] == "alice"
        assert data["is_admin"] is True

    def test_refresh_with_access_token_rejected(self, _isolated):
        tokens = self._get_tokens()
        r = client.post("/api/auth/refresh", json={
            "refresh_token": tokens["access_token"],  # 의도된 오용
        })
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "TOKEN_TYPE_MISMATCH"

    def test_refresh_invalid_token(self, _isolated):
        r = client.post("/api/auth/refresh", json={
            "refresh_token": "not.a.valid.jwt.token.string",
        })
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "TOKEN_INVALID"

    def test_refresh_user_revoked(self, _isolated):
        tokens = self._get_tokens()
        # alice 삭제 후 refresh 시도 → USER_REVOKED
        us.remove_user("alice")
        r = client.post("/api/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "USER_REVOKED"


class TestChangePassword:
    def _login_and_get_auth(self):
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def test_change_password_success(self, _isolated):
        headers = self._login_and_get_auth()
        r = client.post(
            "/api/auth/change-password",
            json={"new_password": "new_secret_345"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
        # 신규 PW로 재로그인 가능
        r2 = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "new_secret_345",
        })
        assert r2.status_code == 200
        # 구 PW는 거부
        r3 = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        assert r3.status_code == 401

    def test_change_password_short_rejected(self, _isolated):
        headers = self._login_and_get_auth()
        r = client.post(
            "/api/auth/change-password",
            json={"new_password": "short"},
            headers=headers,
        )
        assert r.status_code == 422  # Pydantic min_length=8

    def test_change_password_no_auth(self, _isolated):
        r = client.post(
            "/api/auth/change-password",
            json={"new_password": "new_secret_345"},
        )
        # UserContextMiddleware 단계에서 401 AUTH_REQUIRED
        assert r.status_code == 401


class TestLogout:
    def test_logout_basic(self, _isolated):
        r = client.post("/api/auth/logout")
        # 미인증 logout — no-op + 200
        assert r.status_code in (200, 401)

    def test_logout_authenticated_revokes_token(self, _isolated):
        """47차 W35: 인증된 사용자 logout → token_version 증가 → 기존 토큰 거부."""
        # 1. login
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        tokens = r.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # 2. logout (인증)
        r2 = client.post("/api/auth/logout", headers=headers)
        assert r2.status_code == 200
        body = r2.json()
        assert body["revoked"] is True
        assert body["username"] == "alice"

        # 3. 기존 access로 다른 endpoint 호출 → TOKEN_REVOKED
        r3 = client.get("/api/auth/admins", headers=headers)
        assert r3.status_code == 401
        err = r3.json().get("error", {})
        assert err.get("code") == "TOKEN_REVOKED"

        # 4. 기존 refresh로 갱신 → TOKEN_REVOKED
        r4 = client.post("/api/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert r4.status_code == 401
        assert r4.json()["error"]["code"] == "TOKEN_REVOKED"


class TestW35TokenRevocation:
    """47차 W35: token_version 기반 revocation 시나리오."""

    def test_change_password_returns_new_tokens(self, _isolated):
        """PW 변경 응답에 새 access + refresh 포함 (재로그인 부담 회피)."""
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        old_tokens = r.json()
        old_access = old_tokens["access_token"]
        headers = {"Authorization": f"Bearer {old_access}"}

        r2 = client.post(
            "/api/auth/change-password",
            json={"new_password": "new_secret_345"},
            headers=headers,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["access_token"] != old_access  # 새 token

    def test_old_token_revoked_after_password_change(self, _isolated):
        """PW 변경 후 기존 access 토큰 → TOKEN_REVOKED."""
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        old_tokens = r.json()
        old_headers = {"Authorization": f"Bearer {old_tokens['access_token']}"}

        # PW 변경
        client.post(
            "/api/auth/change-password",
            json={"new_password": "new_secret_345"},
            headers=old_headers,
        )

        # 기존 access로 다른 endpoint 호출 → TOKEN_REVOKED
        r2 = client.get("/api/auth/admins", headers=old_headers)
        assert r2.status_code == 401
        assert r2.json()["error"]["code"] == "TOKEN_REVOKED"

    def test_new_tokens_after_password_change_work(self, _isolated):
        """PW 변경 응답의 새 access는 정상 동작."""
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        old_access = r.json()["access_token"]

        r2 = client.post(
            "/api/auth/change-password",
            json={"new_password": "new_secret_345"},
            headers={"Authorization": f"Bearer {old_access}"},
        )
        new_access = r2.json()["access_token"]

        # 새 access로 호출 → 정상
        r3 = client.get("/api/auth/admins", headers={"Authorization": f"Bearer {new_access}"})
        assert r3.status_code == 200

    def test_user_deleted_token_revoked(self, _isolated):
        """user 삭제 후 access/refresh 모두 USER_REVOKED."""
        from backend.services import users as us
        r = client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret_password_12",
        })
        tokens = r.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # 사용자 삭제
        us.remove_user("alice")

        # 기존 access → USER_REVOKED
        r2 = client.get("/api/auth/admins", headers=headers)
        assert r2.status_code == 401
        assert r2.json()["error"]["code"] == "USER_REVOKED"
