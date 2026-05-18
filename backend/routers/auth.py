"""40차 — 인증/권한 endpoint. 45차 C1 — JWT login/refresh 통합.

Endpoints:
  GET  /api/auth/me — 현재 사용자 + is_admin + must_change_password 응답 (공개).
  GET  /api/auth/admins — admin list 조회 (admin only).
  POST /api/auth/login — username + password → access + refresh token (공개).
  POST /api/auth/refresh — refresh token → 새 access token (공개).
  POST /api/auth/change-password — 본인 PW 변경 (인증 필요).
  POST /api/auth/logout — client-side token 폐기 안내 (실 서버 상태 없음).

JWT 도입으로 X-User 헤더 신뢰 모델 폐기 — `dev_mode_x_user_fallback` 활성 시만 호환.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.dependencies.admin import require_admin
from backend.services.admin_users import is_admin, load_admins
from backend.services.auth_service import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend.services.users import (
    change_password as _change_password,
    get_user,
    increment_token_version,
    verify_credentials,
)
from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def _no_newline_user(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("username에 줄바꿈 금지")
        return v.strip()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=2000)


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=200)


@router.get("/me")
async def get_me() -> dict:
    """현재 사용자 + is_admin + must_change_password 응답.

    Frontend AuthContext + AdminContext가 mount 시 호출.
    인증 안 됨 (JWT 없음 + X-User fallback 비활성)이면 authenticated=False (401 raise 안 함).
    """
    user = get_current_user()
    if not user or user == "default":
        return {
            "username": None,
            "is_admin": False,
            "authenticated": False,
            "must_change_password": False,
        }
    record = get_user(user)
    return {
        "username": user,
        "is_admin": is_admin(user),
        "authenticated": True,
        "must_change_password": bool(record and record.get("must_change_password")),
    }


@router.get("/admins")
async def list_admins_endpoint(_admin: str = Depends(require_admin)) -> dict:
    """admin list 조회 — admin only."""
    return {"admins": sorted(load_admins())}


@router.post("/login")
async def login(body: LoginRequest) -> dict:
    """45차 C1 — username + password 검증 → JWT access + refresh 발급.

    실패 시 401 INVALID_CREDENTIALS — username 존재 여부 노출 안 함 (timing).
    성공 시 must_change_password 표시로 frontend가 PW 변경 화면 강제.
    """
    record = verify_credentials(body.username, body.password)
    if not record:
        _logger.warning("Login failed: user=%s", _mask(body.username))
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "사용자명 또는 비밀번호 불일치"},
        )
    actual_username = record["username"]
    # 47차 W35: token_version을 access/refresh 모두에 포함 → logout/PW 변경 시 즉시 무효화
    tv = int(record.get("token_version", 0))
    access = create_access_token(actual_username, token_version=tv)
    refresh = create_refresh_token(actual_username, token_version=tv)
    _logger.info("Login OK: user=%s", _mask(actual_username))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "username": actual_username,
        "is_admin": is_admin(actual_username),
        "must_change_password": bool(record.get("must_change_password")),
    }


@router.post("/refresh")
async def refresh(body: RefreshRequest) -> dict:
    """refresh token 검증 → 새 access token 발급.

    refresh 자체는 sliding 아님 — 7일 만료 후 재로그인 필요.
    """
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except TokenError as e:
        raise HTTPException(
            status_code=401,
            detail={"code": e.code, "message": e.message},
        )
    username = payload["sub"]
    # user record 재확인 — 삭제된 사용자의 refresh는 거부
    record = get_user(username)
    if not record:
        raise HTTPException(
            status_code=401,
            detail={"code": "USER_REVOKED", "message": "사용자가 삭제됨 — 재로그인 필요"},
        )
    # 47차 W35: token_version 일치 확인 — logout/PW 변경 후 기존 refresh 거부
    expected_tv = int(record.get("token_version", 0))
    token_tv = int(payload.get("tv", 0))
    if token_tv != expected_tv:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "TOKEN_REVOKED",
                "message": "토큰이 폐기됨 (logout 또는 PW 변경) — 재로그인 필요",
            },
        )
    # 새 access는 현재 token_version으로 발급 (동일)
    access = create_access_token(username, token_version=expected_tv)
    return {
        "access_token": access,
        "token_type": "bearer",
        "username": username,
        "is_admin": is_admin(username),
    }


@router.post("/change-password")
async def change_password_endpoint(body: ChangePasswordRequest) -> dict:
    """본인 PW 변경 — 임시 PW 후 첫 로그인 시 호출.

    JWT 인증 필요 (UserContext에서 사용자 식별). must_change_password 초기화.
    """
    user = get_current_user()
    if not user or user == "default":
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "인증 필요"},
        )
    try:
        result = _change_password(user, body.new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PASSWORD", "message": str(e)},
        )
    # 47차 W35: change_password가 token_version 자동 증가 → 기존 토큰 모두 무효.
    # 사용자 재로그인 부담 회피를 위해 새 access + refresh 발급.
    new_tv = int(result.get("new_token_version", 0))
    access = create_access_token(user, token_version=new_tv)
    refresh = create_refresh_token(user, token_version=new_tv)
    _logger.info("Password changed: user=%s new_tv=%d", _mask(user), new_tv)
    return {
        "changed": True,
        "username": user,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout() -> dict:
    """47차 W35 — 인증된 사용자의 token_version 증가 → 기존 토큰 모두 즉시 무효화.

    이전 (45차): stateless. 도난된 refresh 7일간 유효.
    47차: server-side revocation. logout 직후 모든 access/refresh 거부 (TOKEN_REVOKED).
    """
    user = get_current_user()
    if not user or user == "default":
        # 미인증 logout — no-op (client측 토큰 정리만)
        return {"ok": True, "message": "client 측 토큰 삭제"}
    try:
        result = increment_token_version(user)
        _logger.info("Logout OK: user=%s new_tv=%d", _mask(user), result["new_token_version"])
        return {"ok": True, "username": user, "revoked": True}
    except ValueError:
        # 사용자 삭제됨 — 그래도 OK 응답 (client 측 정리)
        return {"ok": True, "message": "client 측 토큰 삭제 (server 측 사용자 없음)"}


def _mask(user: str) -> str:
    """log용 마스킹 — admin_users.mask_user 패턴."""
    u = (user or "").strip()
    if len(u) <= 2:
        return "*" * len(u)
    if len(u) <= 4:
        return u[0] + "*" * (len(u) - 1)
    return u[:2] + "*" * (len(u) - 3) + u[-1]
