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


def require_user() -> str:
    """**로그인만** 요구 — admin 권한도, Bearer 강제도 하지 않는다.

    조회 전용 endpoint 용이다. 세 단계의 중간 칸을 채운다:

    | Depends | 요구 | 쓰임 |
    |---|---|---|
    | `require_jwt_user` | Bearer 필수(X-User 거부) | logout·비밀번호 변경 등 파괴적 작업 |
    | **`require_user`** | 신원만(미들웨어 판정 그대로) | 조회 — 품질 이력·게이트 근거 |
    | `require_admin` | 신원 + admin 등록 | 빌더 실행·evidence 생성 |

    Bearer 를 강제하지 않는 이유: 미들웨어가 이미 신원을 세우고, 이 계층은 데이터를
    **바꾸지 않는다**. `DEV_MODE_X_USER_FALLBACK` 환경에서 X-User 로 들어온 요청까지
    막으면 개발 중 조회 화면이 통째로 401 이 된다(파괴적 작업과 달리 그 대가가 없다).

    Returns:
        인증된 사용자 이름.

    Raises:
        HTTPException 401 AUTH_REQUIRED — 미들웨어가 신원을 못 세운 경우.
    """
    user = get_current_user()
    if not user or user == "default":
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "로그인 필요"},
        )
    return user


__all__ = ["require_jwt_user", "require_user"]
