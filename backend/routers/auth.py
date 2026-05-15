"""40차 — 인증/권한 endpoint.

GET /api/auth/me — 현재 사용자 + is_admin 응답 (frontend AdminContext용).
GET /api/auth/admins — admin list 조회 (admin only).

본 라운드는 X-User 헤더 신뢰 모델 유지 — JWT/세션 도입은 41차+ 별도.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from backend.dependencies.admin import require_admin
from backend.services.admin_users import is_admin, load_admins
from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def get_me() -> dict:
    """현재 X-User + is_admin 응답.

    Frontend AdminContext가 mount 시 호출 — localStorage 신뢰 제거.
    인증 안 됨 (X-User 없음)이면 authenticated=False (401 raise 안 함 — public endpoint).
    """
    user = get_current_user()
    if not user or user == "default":
        return {
            "username": None,
            "is_admin": False,
            "authenticated": False,
        }
    return {
        "username": user,
        "is_admin": is_admin(user),
        "authenticated": True,
    }


@router.get("/admins")
async def list_admins_endpoint(_admin: str = Depends(require_admin)) -> dict:
    """admin list 조회 — admin only.

    Returns:
        {"admins": ["user1", "user2"]}
    """
    return {"admins": sorted(load_admins())}
