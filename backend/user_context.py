"""Lightweight user identification.

45차 C1: JWT Authorization 헤더 우선 검증 + DEV_MODE_X_USER_FALLBACK 활성 시 X-User 헤더 fallback.
이전 (40~44차): X-User 헤더 단독 신뢰 — 본 라운드에서 폐기.
"""
from __future__ import annotations

import json
import logging
import contextvars
from pathlib import Path
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from backend.services.auth_service import (
    TokenError,
    decode_token,
    is_dev_mode_x_user_fallback_enabled,
)
# 48차 W45: users.get_user를 top-level import (이전 47차 W35: lazy import).
# circular 안전 — users.py가 user_context 미참조.
from backend.services.users import get_user as _users_get_user

_logger = logging.getLogger(__name__)

current_user: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user", default="default"
)

# Allowed users list (loaded once at import)
_ALLOWED_USERS_PATH = Path(__file__).resolve().parents[1] / "config" / "allowed_users.json"
_allowed_users: set[str] | None = None


def _load_allowed_users() -> set[str] | None:
    """Load allowed users from config. Returns None if no restriction (file missing)."""
    if not _ALLOWED_USERS_PATH.exists():
        return None
    try:
        data = json.loads(_ALLOWED_USERS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > 0:
            return set(data)
        return None
    except Exception:
        return None


def get_allowed_users() -> set[str] | None:
    global _allowed_users
    if _allowed_users is None:
        _allowed_users = _load_allowed_users()
    return _allowed_users


def reload_allowed_users():
    global _allowed_users
    _allowed_users = _load_allowed_users()


# 45차 C1: 인증 우회 endpoint — JWT/X-User 모두 없이 접근 가능 (로그인 + 공개)
_AUTH_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/health",
    "/favicon.svg",
})

# 45차 C1: best-effort 인증 — JWT/X-User 있으면 식별, 없어도 401 raise 안 함.
# /api/auth/me가 핵심 — 미인증 시 authenticated=False 응답, 인증 시 user + is_admin.
_AUTH_BEST_EFFORT_PATHS = frozenset({
    "/api/auth/me",
})


def _extract_user_from_authorization(request: Request) -> tuple[str | None, str | None]:
    """Authorization 헤더에서 사용자 추출.

    47차 W35: token_version 검증 — user record의 token_version과 token tv claim
    일치 확인. 불일치 시 TOKEN_REVOKED (logout/change-password 후 도난 토큰 차단).

    Returns:
        (username, error_code) — 성공 시 (username, None), 실패 시 (None, error_code).
        헤더 자체가 없으면 (None, None) — fallback 가능성 표시.
    """
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        return (None, None)
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return (None, "AUTH_HEADER_MALFORMED")
    token = parts[1].strip()
    if not token:
        return (None, "AUTH_HEADER_MALFORMED")
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as e:
        return (None, e.code)
    username = payload["sub"]
    # 47차 W35 + 48차 W45: token_version 검증 — DB read (lru_cache + mtime invalidate).
    # 미존재 user는 USER_REVOKED, tv 불일치는 TOKEN_REVOKED.
    # 48차 W45: lazy import 제거 — top-level import로 매 요청 dict 조회 비용 절감.
    try:
        record = _users_get_user(username)
    except Exception:
        record = None
    if record is None:
        # 사용자 삭제됨 — 도난 토큰 차단
        return (None, "USER_REVOKED")
    expected_tv = int(record.get("token_version", 0))
    token_tv = int(payload.get("tv", 0))
    if token_tv != expected_tv:
        return (None, "TOKEN_REVOKED")
    return (username, None)


class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        # CORS preflight + 공개 endpoint + non-API: 인증 우회
        if (
            request.method == "OPTIONS"
            or path in _AUTH_EXEMPT_PATHS
            or not path.startswith("/api/")
        ):
            return await call_next(request)

        # 45차 C1 best-effort 인증: /api/auth/me 등은 인증 시도하되 실패해도 default user 진행
        if path in _AUTH_BEST_EFFORT_PATHS:
            user, _err = _extract_user_from_authorization(request)
            if user is None and is_dev_mode_x_user_fallback_enabled():
                user = (request.headers.get("X-User") or "").strip() or None
            if user:
                token = current_user.set(user)
                try:
                    return await call_next(request)
                finally:
                    current_user.reset(token)
            return await call_next(request)

        # 45차 C1: JWT Authorization 우선
        user, jwt_error = _extract_user_from_authorization(request)
        if user is None:
            if jwt_error:
                # 토큰 제공됐으나 검증 실패 — 401 with code
                return JSONResponse(
                    status_code=401,
                    content={
                        "ok": False,
                        "error": {
                            "code": jwt_error,
                            "message": "JWT 토큰 검증 실패 — 재로그인 필요",
                        },
                    },
                )
            # JWT 없음 — DEV 모드 X-User fallback 시도
            if is_dev_mode_x_user_fallback_enabled():
                x_user = (request.headers.get("X-User") or "").strip()
                if x_user:
                    user = x_user
                else:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "ok": False,
                            "error": {
                                "code": "AUTH_REQUIRED",
                                "message": "Authorization Bearer token 또는 X-User 헤더 필요 (DEV 모드)",
                            },
                        },
                    )
            else:
                return JSONResponse(
                    status_code=401,
                    content={
                        "ok": False,
                        "error": {
                            "code": "AUTH_REQUIRED",
                            "message": "Authorization Bearer token 필요",
                        },
                    },
                )

        allowed = get_allowed_users()
        if allowed is not None and user not in allowed:
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "error": {
                        "code": "USER_NOT_AUTHORIZED",
                        "message": f"User '{user}' not authorized",
                    },
                },
            )

        token = current_user.set(user)
        try:
            response = await call_next(request)
            return response
        finally:
            current_user.reset(token)


def get_current_user() -> str:
    """Return the current request's user identifier."""
    return current_user.get("default")


def wrap_with_user(fn):
    """Wrap a callable so it inherits the current user context."""
    user = get_current_user()

    def wrapper(*args, **kwargs):
        token = current_user.set(user)
        try:
            return fn(*args, **kwargs)
        finally:
            current_user.reset(token)

    return wrapper
