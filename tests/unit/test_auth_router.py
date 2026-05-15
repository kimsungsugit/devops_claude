"""40차 T269 — /api/auth/me + /api/auth/admins 회귀.

6 시나리오: admin / non-admin / 미인증 + admins list 조회 / non-admin 거부.
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


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_admins(tmp_path, monkeypatch):
    """각 test 격리된 admin_users.json + 'tester'를 admin으로 기본 등록."""
    p = tmp_path / "admin_users.json"
    p.write_text('{"admins": ["tester"], "schema_version": 1}', encoding="utf-8")
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()
    return p


class TestGetMe:
    """GET /api/auth/me — 공개 endpoint."""

    def test_admin_user(self):
        r = client.get("/api/auth/me", headers={"X-User": "tester"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "tester"
        assert data["is_admin"] is True
        assert data["authenticated"] is True

    def test_non_admin_user(self):
        r = client.get("/api/auth/me", headers={"X-User": "guest"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "guest"
        assert data["is_admin"] is False
        assert data["authenticated"] is True

    def test_missing_x_user_header(self):
        """X-User 없음 — UserContextMiddleware가 401 차단."""
        r = client.get("/api/auth/me")
        # middleware 단계 401 (또는 200 + authenticated=False — middleware 동작에 따라)
        assert r.status_code in (200, 401)
        if r.status_code == 200:
            assert r.json()["authenticated"] is False


class TestGetAdmins:
    """GET /api/auth/admins — admin only."""

    def test_admin_can_list(self):
        r = client.get("/api/auth/admins", headers={"X-User": "tester"})
        assert r.status_code == 200
        assert "tester" in r.json()["admins"]

    def test_non_admin_rejected(self):
        r = client.get("/api/auth/admins", headers={"X-User": "guest"})
        assert r.status_code == 403
        body = r.json()
        msg = body.get("error", {}).get("message") or body.get("detail", {})
        # detail이 dict ({"code": ..., "message": ...}) 또는 str
        if isinstance(msg, dict):
            assert msg.get("code") == "ADMIN_REQUIRED"
        else:
            assert "admin" in str(msg).lower()

    def test_missing_x_user_rejected(self):
        r = client.get("/api/auth/admins")
        # UserContextMiddleware 단계 401 또는 require_admin 단계 401
        assert r.status_code in (401, 403)
