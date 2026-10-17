"""(R48-a) 계정·역할 관리 endpoint — `/api/auth/users*` · `/api/auth/approvers` · `/api/auth/me.is_approver`.

전부 **JWT + admin** 이다(X-User 로는 계정을 만들 수 없다). 진짜 로그인 흐름(`/api/auth/login`)으로 토큰을 받아
쓴다 — 의존성을 덮으면 "JWT 없이 계정 생성" 회귀를 못 잡는다.

lockout 방어: 자기 자신 삭제/강등 거부 · 마지막 admin 해제 거부. 응답 어디에도 `password_hash` 가 없다.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import admin_users as au  # noqa: E402
from backend.services import approvers as apv  # noqa: E402
from backend.services import users as us  # noqa: E402

client = TestClient(app)


def _isolate_json_store(monkeypatch, module, path_attr: str, lock_attr: str, path: Path, cache_key: str, empty):
    monkeypatch.setattr(module, path_attr, path)
    try:
        from filelock import FileLock
        monkeypatch.setattr(module, lock_attr, FileLock(str(path) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(module, lock_attr, threading.Lock())
    module._cache["mtime"] = 0.0
    module._cache[cache_key] = empty


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ap = tmp_path / "admin_users.json"
    ap.write_text('{"admins": ["alice"], "schema_version": 1}', encoding="utf-8")
    _isolate_json_store(monkeypatch, au, "ADMIN_USERS_PATH", "_LOCK", ap, "admins", set())
    _isolate_json_store(monkeypatch, apv, "APPROVERS_PATH", "_LOCK", tmp_path / "approvers.json", "approvers", set())
    _isolate_json_store(monkeypatch, us, "USERS_PATH", "_LOCK", tmp_path / "users.json", "users", {})
    monkeypatch.setenv("JWT_SECRET", "test_secret_minimum_32bytes_xxxxxxxxxxxxxxxx")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_EXPIRE_DAYS", "7")
    monkeypatch.delenv("DEV_MODE_X_USER_FALLBACK", raising=False)
    us.add_user("alice", "secret_password_12", must_change_password=False)
    us.add_user("plain", "secret_password_12", must_change_password=False)
    return tmp_path


def _hdr(username="alice", password="secret_password_12"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestGuards:
    def test_x_user_alone_cannot_manage_users(self):
        """(핵심) admin 이름을 헤더로 대도 JWT 가 없으면 401 — 계정 생성은 신원 위조 채널로 못 연다."""
        r = client.post("/api/auth/users", headers={"X-User": "alice"},
                        json={"username": "mallory", "temp_password": "temp_password_12"})
        assert r.status_code == 401, r.text
        assert us.user_exists("mallory") is False

    def test_non_admin_jwt_is_403(self):
        r = client.get("/api/auth/users", headers=_hdr("plain"))
        assert r.status_code == 403, r.text
        r = client.post("/api/auth/users", headers=_hdr("plain"),
                        json={"username": "mallory", "temp_password": "temp_password_12"})
        assert r.status_code == 403, r.text

    def test_approvers_list_is_admin_only(self):
        """(리뷰 W3) 로그인 누구나 보게 하면 검토 응답의 마스킹된 이름을 이 목록으로 되맞힌다."""
        apv.add_approver("bob")
        assert client.get("/api/auth/approvers", headers=_hdr("plain")).status_code == 403
        assert client.get("/api/auth/approvers", headers={"X-User": "alice"}).status_code == 401
        r = client.get("/api/auth/approvers", headers=_hdr())
        assert r.status_code == 200
        assert r.json() == {"approvers": ["bob"]}

    def test_unknown_fields_are_422(self):
        h = _hdr()
        r = client.post("/api/auth/users", headers=h, json={"username": "okname", "temp_password": "temp_password_12", "approvr": True})
        assert r.status_code == 422
        assert client.put("/api/auth/users/plain/roles", headers=h, json={"approvr": True}).status_code == 422

    @pytest.mark.parametrize("bad", ["CON", "nul", "com1", "LPT9.txt", "default"])
    def test_reserved_names_are_422(self, bad):
        r = client.post("/api/auth/users", headers=_hdr(), json={"username": bad, "temp_password": "temp_password_12"})
        assert r.status_code == 422, bad

    def test_account_events_are_audited_append_only(self, tmp_path, monkeypatch):
        from backend.services import account_audit as aa

        monkeypatch.setattr(aa, "audit_path", lambda: tmp_path / "audit" / "account_audit.jsonl")
        h = _hdr()
        r = client.post("/api/auth/users", headers=h, json={"username": "aud1", "temp_password": "temp_password_12", "approver": True})
        assert r.json()["audit_recorded"] is True
        client.put("/api/auth/users/aud1/roles", headers=h, json={"approver": False})
        client.delete("/api/auth/users/aud1", headers=h)
        rows = [json.loads(ln) for ln in (tmp_path / "audit" / "account_audit.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [(r["action"], r["actor"], r["subject"]) for r in rows] == [
            ("user.create", "alice", "aud1"), ("user.roles", "alice", "aud1"), ("user.delete", "alice", "aud1"),
        ]
        assert rows[0]["detail"] == {"approver": True, "admin": False}

    def test_role_assignment_failure_rolls_back_the_account(self, monkeypatch):
        """(리뷰 I8) 역할 부여가 실패하면 역할 없는 계정이 남아 재시도가 409 로 막힌다 — 계정도 되돌린다."""
        from backend.routers import auth as auth_mod

        def boom(_u):
            raise OSError("disk")
        monkeypatch.setattr(auth_mod, "add_approver", boom)
        r = client.post("/api/auth/users", headers=_hdr(), json={"username": "rb1", "temp_password": "temp_password_12", "approver": True})
        assert r.status_code == 500 and r.json()["error"]["code"] == "ROLE_ASSIGN_FAILED"
        assert us.user_exists("rb1") is False


class TestCreateAndList:
    def test_create_approver_account_forces_password_change_and_never_returns_hash(self):
        h = _hdr()
        r = client.post("/api/auth/users", headers=h,
                        json={"username": "reviewer01", "temp_password": "temp_password_12", "approver": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] is True
        assert body["user"]["username"] == "reviewer01"
        assert body["user"]["is_approver"] is True
        assert body["user"]["is_admin"] is False
        assert body["user"]["must_change_password"] is True
        assert "password_hash" not in str(body) and "temp_password_12" not in str(body)
        # 실제로 로그인이 되고, 첫 로그인은 비밀번호 변경을 요구한다.
        r2 = client.post("/api/auth/login", json={"username": "reviewer01", "password": "temp_password_12"})
        assert r2.status_code == 200
        assert r2.json()["must_change_password"] is True
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r2.json()['access_token']}"}).json()
        assert me["is_approver"] is True and me["is_admin"] is False

    def test_duplicate_is_409_and_does_not_touch_roles(self):
        h = _hdr()
        r = client.post("/api/auth/users", headers=h,
                        json={"username": "plain", "temp_password": "another_pw_123", "approver": True})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "USER_EXISTS"
        assert apv.is_approver("plain") is False, "실패한 생성이 역할만 붙이면 안 된다"

    @pytest.mark.parametrize("bad", ["a", "-lead", "has space", "x" * 65, "dot..", "ünïcode"])
    def test_bad_username_is_422(self, bad):
        r = client.post("/api/auth/users", headers=_hdr(),
                        json={"username": bad, "temp_password": "temp_password_12"})
        assert r.status_code == 422, (bad, r.text)

    def test_short_temp_password_is_422(self):
        r = client.post("/api/auth/users", headers=_hdr(), json={"username": "okname", "temp_password": "short"})
        assert r.status_code == 422

    def test_list_shows_roles_and_no_hashes(self):
        apv.add_approver("plain")
        r = client.get("/api/auth/users", headers=_hdr())
        assert r.status_code == 200
        data = r.json()
        by = {u["username"]: u for u in data["users"]}
        assert by["alice"]["is_admin"] is True and by["alice"]["is_approver"] is False
        assert by["plain"]["is_admin"] is False and by["plain"]["is_approver"] is True
        assert data["approvers"] == ["plain"] and data["admins"] == ["alice"]
        assert "password_hash" not in r.text


class TestRolesAndDelete:
    def test_grant_and_revoke_approver(self):
        h = _hdr()
        r = client.put("/api/auth/users/plain/roles", headers=h, json={"approver": True})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["is_approver"] is True
        r = client.put("/api/auth/users/plain/roles", headers=h, json={"approver": False})
        assert r.json()["user"]["is_approver"] is False

    def test_no_role_given_is_422_and_unknown_user_is_404(self):
        h = _hdr()
        assert client.put("/api/auth/users/plain/roles", headers=h, json={}).status_code == 422
        assert client.put("/api/auth/users/ghost/roles", headers=h, json={"approver": True}).status_code == 404

    def test_self_demote_and_last_admin_are_refused(self):
        h = _hdr()
        r = client.put("/api/auth/users/alice/roles", headers=h, json={"admin": False})
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_DEMOTE"
        assert au.is_admin("alice") is True
        # 다른 admin 을 세운 뒤 그 사람을 내리는 건 되지만, 그가 유일해지면 안 된다.
        client.put("/api/auth/users/plain/roles", headers=h, json={"admin": True})
        h2 = _hdr("plain")
        r = client.put("/api/auth/users/alice/roles", headers=h2, json={"admin": False})
        assert r.status_code == 200, r.text
        r = client.put("/api/auth/users/plain/roles", headers=h2, json={"admin": False})
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_DEMOTE"

    def test_delete_removes_roles_too_and_refuses_self(self):
        h = _hdr()
        apv.add_approver("plain")
        r = client.delete("/api/auth/users/alice", headers=h)
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_DELETE"
        r = client.delete("/api/auth/users/plain", headers=h)
        assert r.status_code == 200 and r.json()["removed"] is True
        assert us.user_exists("plain") is False
        assert apv.is_approver("plain") is False, "이름이 목록에 남으면 같은 이름의 새 계정이 역할을 상속한다"
        assert client.delete("/api/auth/users/plain", headers=h).status_code == 404

    def test_sole_admin_cannot_remove_itself_by_any_route(self):
        """유일한 admin 이 되면 자기 강등·자기 삭제 둘 다 SELF_* 로 막힌다 — 그래서 '마지막 admin' 검사가 따로 필요 없다(M9)."""
        h = _hdr()
        client.put("/api/auth/users/plain/roles", headers=h, json={"admin": True})
        h2 = _hdr("plain")
        client.put("/api/auth/users/alice/roles", headers=h2, json={"admin": False})
        # 이제 plain 이 유일한 admin — alice 가 (admin 아님) 지우려 하면 403, plain 자신은 SELF_DELETE/SELF_DEMOTE.
        assert client.delete("/api/auth/users/plain", headers=h).status_code == 403
        r = client.delete("/api/auth/users/plain", headers=h2)
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_DELETE"
        r = client.put("/api/auth/users/plain/roles", headers=h2, json={"admin": False})
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_DEMOTE"
        assert au.is_admin("plain") is True

    def test_x_user_with_dev_fallback_still_needs_jwt(self, monkeypatch):
        """(뮤테이션 M12) DEV 폴백이 켜져 X-User 로 신원이 서도, 계정 관리는 Bearer 가 없으면 401 JWT_REQUIRED 다."""
        monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", "1")
        r = client.post("/api/auth/users", headers={"X-User": "alice"},
                        json={"username": "mallory2", "temp_password": "temp_password_12"})
        assert r.status_code == 401, r.text
        assert r.json()["error"]["code"] == "JWT_REQUIRED"
        assert us.user_exists("mallory2") is False
