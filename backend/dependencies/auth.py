"""48차 C5 — JWT-only 인증 Depends.

47차 자체 평가에서 발견한 C5 보안 결함:
  DEV_MODE_X_USER_FALLBACK=1 환경에서 admin이 `X-User: other_user` 헤더만으로
  /api/auth/logout 호출 시 middleware가 user='other_user' 인식 → logout endpoint가
  other_user.token_version 증가 → other_user 강제 logout.

본 Depends는 destructive endpoint (logout, change-password, admin-revoke 등)에 적용:
  - Authorization Bearer 헤더 존재 강제 → X-User fallback 거부
  - middleware가 이미 token 검증 + current_user 설정 후라 user 추출만 수행

기존 require_admin (admin_users.is_admin 검증)은 별도 — admin 권한이 있더라도
본 require_jwt_user 통과 못 하면 destructive endpoint 호출 거부.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)


def require_jwt_user(request: Request) -> str:
    """JWT-only 인증 — Authorization Bearer 헤더 필수. X-User fallback 거부.

    Returns:
        인증된 사용자 username (current_user contextvar에서 추출).

    Raises:
        HTTPException 401 JWT_REQUIRED — Authorization 헤더 없거나 Bearer 형식 아님.
        HTTPException 401 AUTH_REQUIRED — middleware가 user 식별 안 함 (default).
    """
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        _logger.warning("require_jwt_user: Authorization Bearer 누락 (X-User fallback 차단)")
        raise HTTPException(
            status_code=401,
            detail={
                "code": "JWT_REQUIRED",
                "message": "이 작업은 JWT Bearer 토큰 인증 필요 (X-User 헤더 거부)",
            },
        )
    user = get_current_user()
    if not user or user == "default":
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "인증 필요"},
        )
    return user


__all__ = ["require_jwt_user"]
