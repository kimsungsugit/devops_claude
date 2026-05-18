"""45차 C1 — JWT auth_service 회귀.

password hash/verify + JWT encode/decode + 만료 + type 불일치 검증.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """각 test 격리 secret + JWT_ALGORITHM 기본."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_minimum_32bytes_long_secret_x")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_EXPIRE_DAYS", "7")
    monkeypatch.delenv("DEV_MODE_X_USER_FALLBACK", raising=False)
    yield


class TestPasswordHash:
    def test_hash_verify_roundtrip(self):
        from backend.services.auth_service import hash_password, verify_password
        h = hash_password("secret12345")
        assert h.startswith("$2b$")
        assert verify_password("secret12345", h) is True

    def test_wrong_password(self):
        from backend.services.auth_service import hash_password, verify_password
        h = hash_password("secret12345")
        assert verify_password("wrong", h) is False

    def test_corrupted_hash_graceful(self):
        from backend.services.auth_service import verify_password
        # 손상된 hash — graceful False
        assert verify_password("anything", "not_a_valid_bcrypt_hash") is False

    def test_korean_long_password_truncates_at_72_bytes(self):
        """72바이트 정책 — 한국어 24자 = 72바이트. 그 이상 truncate."""
        from backend.services.auth_service import hash_password, verify_password
        pw = "가나다라마바사아자차카타파하" * 3  # ~117 bytes
        h = hash_password(pw)
        # 동일한 long password verify
        assert verify_password(pw, h) is True
        # 처음 72바이트만 hashing — truncate 결과 동등
        first_72 = pw.encode("utf-8")[:72].decode("utf-8", errors="ignore")
        assert verify_password(first_72, h) is True


class TestJWTToken:
    def test_access_token_roundtrip(self):
        from backend.services.auth_service import create_access_token, decode_token
        token = create_access_token("alice")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "alice"
        assert payload["type"] == "access"
        assert "iat" in payload and "exp" in payload

    def test_refresh_token_roundtrip(self):
        from backend.services.auth_service import create_refresh_token, decode_token
        token = create_refresh_token("bob")
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "bob"
        assert payload["type"] == "refresh"

    def test_type_mismatch_raises(self):
        from backend.services.auth_service import (
            TokenError,
            create_access_token,
            decode_token,
        )
        access = create_access_token("alice")
        with pytest.raises(TokenError) as exc_info:
            decode_token(access, expected_type="refresh")
        assert exc_info.value.code == "TOKEN_TYPE_MISMATCH"

    def test_invalid_token_raises(self):
        from backend.services.auth_service import TokenError, decode_token
        with pytest.raises(TokenError) as exc_info:
            decode_token("not.a.valid.jwt")
        assert exc_info.value.code == "TOKEN_INVALID"

    def test_expired_token_raises(self, monkeypatch):
        from backend.services import auth_service as svc
        from backend.services.auth_service import (
            TokenError,
            create_access_token,
            decode_token,
        )
        # access expire 0분 → 즉시 만료
        monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "0")
        token = create_access_token("alice")
        # 시계 1초 진행 — 만료 확실
        time.sleep(1)
        with pytest.raises(TokenError) as exc_info:
            decode_token(token)
        assert exc_info.value.code == "TOKEN_EXPIRED"

    def test_secret_mismatch_raises(self, monkeypatch):
        from backend.services.auth_service import (
            TokenError,
            create_access_token,
            decode_token,
        )
        monkeypatch.setenv("JWT_SECRET", "secret_a_minimum_32bytes_long_xxxxxxxxxxxxxx")
        token = create_access_token("alice")
        # 다른 secret으로 decode — InvalidSignatureError → TokenError
        monkeypatch.setenv("JWT_SECRET", "secret_b_minimum_32bytes_long_yyyyyyyyyyyyyy")
        with pytest.raises(TokenError) as exc_info:
            decode_token(token)
        assert exc_info.value.code == "TOKEN_INVALID"


class TestDevModeFallback:
    def test_dev_mode_disabled_default(self):
        from backend.services.auth_service import is_dev_mode_x_user_fallback_enabled
        assert is_dev_mode_x_user_fallback_enabled() is False

    def test_dev_mode_enabled_via_env(self, monkeypatch):
        from backend.services.auth_service import is_dev_mode_x_user_fallback_enabled
        monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", "1")
        assert is_dev_mode_x_user_fallback_enabled() is True

    def test_dev_mode_various_truthy(self, monkeypatch):
        from backend.services.auth_service import is_dev_mode_x_user_fallback_enabled
        for val in ("1", "true", "True", "yes"):
            monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", val)
            assert is_dev_mode_x_user_fallback_enabled() is True
        for val in ("0", "false", "no", ""):
            monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", val)
            assert is_dev_mode_x_user_fallback_enabled() is False
