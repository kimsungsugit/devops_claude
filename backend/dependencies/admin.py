"""40차 — `require_admin` FastAPI Depends.

13 SwIT/SwUT/file-mode endpoint에 추가하여 admin role 검증.
non-admin은 401 (X-User 없음) 또는 403 (X-User 있지만 admin 아님) 응답.

ISO 26262 audit 무결성: 누구나 builder 호출 차단 — admin만 evidence 생성 가능.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from backend.services.admin_users import is_admin
from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)


def require_admin() -> str:
    """FastAPI Depends — admin only endpoint 보호.

    Returns:
        admin user 이름 (logging / audit trail용).

    Raises:
        HTTPException 401 AUTH_REQUIRED — X-User 헤더 없음 또는 default user.
        HTTPException 403 ADMIN_REQUIRED — X-User는 있지만 admin 아님.
    """
    user = get_current_user()
    if not user or user == "default":
        _logger.warning("admin gate: X-User missing")
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_REQUIRED",
                "message": "X-User 헤더 필요 — Settings에서 사용자 이름 설정",
            },
        )
    if not is_admin(user):
        _logger.warning("admin gate: user=%s is not admin", user)
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ADMIN_REQUIRED",
                "message": (
                    f"admin 권한 필요 (현재 사용자: {user}). "
                    f"config/admin_users.json에 admin 등록 필요"
                ),
            },
        )
    return user


__all__ = ["require_admin"]
