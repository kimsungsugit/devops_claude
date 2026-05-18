"""40차 — pytest conftest: 회귀 fixture 공통.

40차 admin role 가드 도입 — 기존 100+ 회귀가 X-User='tester'를 admin으로 암묵 가정.
본 autouse fixture가 admin_users 모듈을 monkeypatch해서 ['tester', 'hbrnd2']를 기본
admin으로 등록 → 기존 회귀 깨지지 않음.

회귀 파일별 격리 fixture(`_isolated_admins`, `_isolated_storage` 등)가 있으면
그들이 우선 (override). 본 fixture는 default fallback.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _default_admin_users(tmp_path_factory, monkeypatch, request):
    """기존 회귀 (X-User='tester')를 admin으로 자동 등록.

    파일별 회귀가 본인의 admin_users fixture(`_isolated_admins`)를 정의했으면
    monkeypatch 우선순위로 그 fixture가 본 default를 덮어쓴다.
    """
    # 임시 admin_users.json — 회귀 batch 종료 후 자동 cleanup
    tmp = tmp_path_factory.mktemp("admin_users_default")
    p = tmp / "admin_users.json"
    p.write_text(
        '{"admins": ["tester", "hbrnd2"], "schema_version": 1}',
        encoding="utf-8",
    )
    try:
        from backend.services import admin_users as au
    except ImportError:
        # backend 모듈 import 실패 (예: backend 외 회귀)
        return
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    # cache invalidate — 다음 load_admins에서 disk read
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()


@pytest.fixture(autouse=True)
def _default_jwt_env(monkeypatch):
    """45차 C1 — 기존 X-User 신뢰 회귀 호환.

    DEV_MODE_X_USER_FALLBACK=1로 backward-compat 모드 활성. 단, JWT 전용 회귀
    (test_auth_login_router.py, test_auth_service.py)는 본인 fixture에서 명시적으로
    `monkeypatch.delenv("DEV_MODE_X_USER_FALLBACK", raising=False)` 호출하여 비활성.

    JWT secret도 기본 secret 설정 — 100+ 회귀가 JWT decoder import만 해도 동작.
    """
    monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", "1")
    if not (monkeypatch.delenv("JWT_SECRET", raising=False) or False):
        monkeypatch.setenv(
            "JWT_SECRET",
            "default_test_secret_minimum_32bytes_xxxxxxxxxxxxxxxx",
        )
