"""40차 T270 — 13 endpoint admin only 가드 회귀.

각 endpoint × 3 시나리오 (admin / non-admin / 미인증).
parametrize로 일괄 검증.
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
    """'admin_user'만 admin — non-admin과 미인증 구분 검증."""
    p = tmp_path / "admin_users.json"
    p.write_text('{"admins": ["admin_user"], "schema_version": 1}', encoding="utf-8")
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()
    # config/file_mode.json(cloudium 영속)이 dev 머신에 있으면 get_resolver가 cloudium
    # 으로 초기화돼 /api/swut/browse가 cloudium 게이트 경로로 빠져 admin 403 검증이
    # 깨진다 → admin 게이트 회귀는 기본 local로 고정.
    from backend.services import file_resolver as fr
    monkeypatch.setattr(fr, "_resolver", fr.LocalFileResolver())

    # ⚠ 위에서 local 로 고정하는 순간 /api/file-mode/browse-file 이 **LOCAL 경로**
    # (health.py "LOCAL 모드 — backend 자체 tkinter")로 들어가 pick_file 이
    # tkinter askopenfilename **모달 대화상자**를 띄운다. admin 은 가드를 통과하므로
    # test_admin_passes_gate 만 그 핸들러에 도달하고, 헤드리스 CI/자동 실행에는
    # 대화상자를 닫아 줄 사람이 없어 **테스트가 영구 정지**한다(실측: pytest 가
    # 39%에서 무한 대기). 가드 통과 여부만 보는 회귀이므로 picker 는 스텁으로 대체.
    from backend.services import local_service as ls
    monkeypatch.setattr(ls, "pick_file", lambda title="": ("", "cancelled"))
    monkeypatch.setattr(ls, "pick_directory", lambda title="": ("", "cancelled"))


# 13 endpoint × (method, path, sample body)
_ENDPOINTS = [
    # SwIT (4)
    ("POST", "/api/swit/coverage/build", {"project_id": "X", "release_sw_version": "1.0", "test_date": "2024-01-01"}),
    ("POST", "/api/swit/sitr/build", {"project_id": "X", "release_sw_version": "1.0", "test_date": "2024-01-01"}),
    ("POST", "/api/swit/switcr/build", {"project_id": "X", "release_sw_version": "1.0", "test_date": "2024-01-01"}),
    ("POST", "/api/swit/consistency/check", {"coverage_path": "C:/x", "sitr_path": "C:/y"}),
    ("POST", "/api/swit/log-folder/preview", {"log_folder": "C:/x"}),
    # SwUT (5)
    ("POST", "/api/swut/coverage/build", {"project_id": "X", "release_sw_version": "1.0", "test_date": "2024-01-01"}),
    ("POST", "/api/swut/sutr/build", {"project_id": "X", "release_sw_version": "1.0", "test_date": "2024-01-01"}),
    ("POST", "/api/swut/swutcr/build", {"project_id": "X", "release_sw_version": "1.0", "test_date": "2024-01-01"}),
    ("POST", "/api/swut/consistency/check", {"coverage_path": "C:/x", "sutr_path": "C:/y"}),
    ("POST", "/api/swut/log-folder/preview", {"log_folder": "C:/x"}),
    ("POST", "/api/swut/browse", {"path": "C:/x", "pattern": "*"}),
    # file-mode (4)
    ("GET", "/api/file-mode/extra-prefixes", None),
    ("POST", "/api/file-mode/add-allowed-prefix", {"prefix": "U:/test"}),
    ("POST", "/api/file-mode/remove-allowed-prefix", {"prefix": "U:/test"}),
    ("POST", "/api/file-mode/browse-file", {"kind": "file"}),
    # Quality (4) — ISO 26262 품질 evidence, 형제 라우터와 동일 admin only
    ("GET", "/api/quality/runs", None),
    ("GET", "/api/quality/runs/1", None),
    ("GET", "/api/quality/trend", None),
    ("POST", "/api/quality/runs/1/advice", {}),
]


def _call(method, path, body, user_header):
    headers = {"Content-Type": "application/json"}
    if user_header:
        headers["X-User"] = user_header
    if method == "GET":
        return client.get(path, headers=headers)
    return client.post(path, json=body or {}, headers=headers)


@pytest.mark.parametrize("method,path,body", _ENDPOINTS)
class TestAdminGate:
    """13 endpoint × 3 user type = 39 회귀."""

    def test_non_admin_rejected_403(self, method, path, body):
        """admin 아닌 user → 403 ADMIN_REQUIRED."""
        r = _call(method, path, body, user_header="guest")
        assert r.status_code == 403, (
            f"non-admin allowed (status={r.status_code}, body={r.text[:200]})"
        )
        body_json = r.json()
        # error_handler standard shape
        detail = body_json.get("error", {}).get("message", "") or str(body_json.get("detail", ""))
        assert "admin" in detail.lower(), f"unexpected error: {detail}"

    def test_missing_x_user_rejected(self, method, path, body):
        """X-User 없음 → middleware 401 (또는 require_admin 401)."""
        r = _call(method, path, body, user_header=None)
        assert r.status_code in (401, 403)

    def test_admin_passes_gate(self, method, path, body):
        """admin user는 가드 통과 — 이후 builder 단계는 400/422/500 가능 (path 무효)."""
        r = _call(method, path, body, user_header="admin_user")
        # admin 통과 후 builder 단계 검증. 403 ADMIN_REQUIRED가 안 떠야 함.
        if r.status_code == 403:
            err = r.json().get("error", {}).get("message", "")
            assert "admin" not in err.lower(), (
                f"admin user blocked by admin gate (path={path}): {err}"
            )
        # 그 외 status (200, 400, 422, 500)는 admin gate 외 단계 — 본 회귀는 가드만 검증
