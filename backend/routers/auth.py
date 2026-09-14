"""40차 — 인증/권한 endpoint. 45차 C1 — JWT login/refresh 통합.

Endpoints:
  GET  /api/auth/me — 현재 사용자 + is_admin + is_approver + must_change_password 응답 (공개).
  GET  /api/auth/admins — admin list 조회 (admin only).
  GET  /api/auth/approvers — 승인자 list 조회 (admin + JWT, R48-a — 마스킹 되맞히기 방지).
  GET  /api/auth/users — 계정 목록 + 역할 (admin + JWT, R48-a). 해시는 절대 싣지 않는다.
  POST /api/auth/users — 계정 생성 {username, temp_password, approver?, admin?} (admin + JWT).
       임시 비밀번호는 admin 이 정해 **전달**하고, 화면이 첫 로그인에서 변경을 강제한다(must_change_password —
       API 자체는 그 계정의 토큰을 막지 않는다). 계정·역할 변경은 `reports/account_audit.jsonl` 에 append-only 로 남는다.
  PUT  /api/auth/users/{username}/roles — {approver?, admin?} 역할 변경 (admin + JWT). 자기 자신의 admin
       해제는 거부(lockout — 행위자가 admin 이라 남을 내려도 자기가 남는다. '마지막 admin' 검사는 그래서 없다).
  DELETE /api/auth/users/{username} — 계정 삭제 + 역할 제거 (admin + JWT). 자기 자신은 거부.
  POST /api/auth/login — username + password → access + refresh token (공개).
  POST /api/auth/refresh — refresh token → 새 access token (공개).
  POST /api/auth/change-password — 본인 PW 변경 (인증 필요).
  POST /api/auth/logout — client-side token 폐기 안내 (실 서버 상태 없음).

(R48-a) 계정·역할을 HTTP 로 연 이유: 승인(4-eyes)은 **둘 이상의 신원**이 있어야 성립하는데, 지금까지 계정을
만드는 길이 `config/users.json` 직접 편집뿐이라 실제로 계정 1개로만 운영됐다. 관리 endpoint 는 전부
JWT + admin 이다 — X-User 로는 계정을 만들 수 없다.

JWT 도입으로 X-User 헤더 신뢰 모델 폐기 — `dev_mode_x_user_fallback` 활성 시만 호환.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.dependencies.admin import require_admin
from backend.dependencies.auth import require_jwt_user
from backend.services.account_audit import record_account_event
from backend.services.admin_users import add_admin, is_admin, load_admins, mask_user, remove_admin
from backend.services.approvers import add_approver, is_approver, load_approvers, remove_approver
from backend.services.auth_service import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend.services.users import (
    add_user,
    get_user,
    increment_token_version,
    list_users,
    remove_user,
    verify_credentials,
)
from backend.services.users import (
    change_password as _change_password,
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
            "is_approver": False,
            "authenticated": False,
            "must_change_password": False,
        }
    record = get_user(user)
    return {
        "username": user,
        "is_admin": is_admin(user),
        "is_approver": is_approver(user),
        "authenticated": True,
        "must_change_password": bool(record and record.get("must_change_password")),
    }


@router.get("/admins")
async def list_admins_endpoint(_admin: str = Depends(require_admin)) -> dict:
    """admin list 조회 — admin only."""
    return {"admins": sorted(load_admins())}


# ── (R48-a) 계정·역할 관리 ──────────────────────────────────────────────────────

# 영문/숫자로 시작·끝, 사이에 `._-`. `..` 과 끝 점은 거부 — 사용자 이름이 캐시 경로(`{base}/{user}/`)에 들어가므로
# 경로 토큰이 될 수 있는 형태는 처음부터 받지 않는다.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9_-])?$")
# Windows 예약 디바이스명(리뷰 I7) — 이 이름의 캐시 디렉터리는 만들 수 없다. 확장자처럼 붙은 꼴(`con.x`)도 예약이다.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", "default"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
)


def _require_admin_jwt(jwt_user: str = Depends(require_jwt_user), _admin: str = Depends(require_admin)) -> str:
    """계정 관리 = JWT **그리고** admin. 두 의존성은 같은 contextvar 를 읽으므로 신원은 하나다."""
    return jwt_user


def _valid_username(name: str) -> str:
    n = (name or "").strip()
    if len(n) < 2 or ".." in n or not _USERNAME_RE.match(n) or n.split(".", 1)[0].lower() in _RESERVED_NAMES:
        raise HTTPException(
            status_code=422,
            detail={"code": "BAD_USERNAME", "message": "username 은 영문/숫자로 시작·끝나는 2~64자([A-Za-z0-9._-], `..`·예약어 불가)"},
        )
    return n


def _user_view(record: dict) -> dict:
    """목록/생성 응답 한 행 — **해시 없음**. 역할은 두 목록에서 그때 읽는다(캐시는 각 서비스 몫)."""
    name = str(record.get("username") or "")
    return {
        "username": name,
        "created_at": record.get("created_at"),
        "must_change_password": bool(record.get("must_change_password")),
        "is_admin": is_admin(name),
        "is_approver": is_approver(name),
    }


class CreateUserRequest(BaseModel):
    """`extra='forbid'` — 오타 필드(`approvr`)가 조용히 무시되지 않게(리뷰 I6, `ReviewBody` 와 같은 규약)."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=2, max_length=64)
    # admin 이 정해 전달하는 **임시** 비밀번호 — 화면(Login/AuthGate)이 첫 로그인에서 변경을 강제한다(API 는 막지 않는다,
    # 리뷰 I9). 응답에는 되돌려 주지 않는다.
    temp_password: str = Field(..., min_length=8, max_length=200)
    approver: bool = False
    admin: bool = False

    @field_validator("username")
    @classmethod
    def _uname(cls, v: str) -> str:
        return _valid_username(v)


class RolesRequest(BaseModel):
    """`None` = 그 역할은 건드리지 않는다(부분 갱신). 둘 다 None 이면 422."""

    model_config = ConfigDict(extra="forbid")

    approver: bool | None = None
    admin: bool | None = None


@router.get("/approvers")
async def list_approvers_endpoint(_admin: str = Depends(_require_admin_jwt)) -> dict:
    """승인자 목록 — **admin 전용**(리뷰 W3: 로그인 누구나 보게 하면 검토 응답의 마스킹된 이름을 이 목록으로 되맞힌다).

    승인자 본인은 `/api/auth/me.is_approver` 로 자기 역할을 안다. 화면은 이 목록 대신 `/api/auth/users` 를 쓴다.
    """
    return {"approvers": sorted(load_approvers())}


@router.get("/users")
async def list_users_endpoint(_admin: str = Depends(_require_admin_jwt)) -> dict:
    users = [_user_view(u) for u in list_users()]
    users.sort(key=lambda u: u["username"].lower())
    return {"users": users, "admins": sorted(load_admins()), "approvers": sorted(load_approvers())}


@router.post("/users")
async def create_user_endpoint(body: CreateUserRequest, admin: str = Depends(_require_admin_jwt)) -> dict:
    """계정 생성. 이미 있으면 **409**(조용히 역할만 바꾸지 않는다 — 기존 계정의 비밀번호를 덮어쓴 것처럼 읽힌다)."""
    try:
        result = add_user(body.username, body.temp_password, must_change_password=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "BAD_REQUEST", "message": str(exc)}) from None
    if not result.get("added"):
        raise HTTPException(
            status_code=409,
            detail={"code": "USER_EXISTS", "message": f"이미 있는 계정입니다: {body.username}"},
        )
    try:
        if body.approver:
            add_approver(body.username)
        if body.admin:
            add_admin(body.username)
    except Exception as exc:  # noqa: BLE001 — 역할 부여가 실패하면 계정도 되돌린다(리뷰 I8: 역할 없는 계정이 남고 재시도는 409)
        remove_user(body.username)
        _logger.warning("user create rolled back: %s (%s)", mask_user(body.username), type(exc).__name__)
        raise HTTPException(status_code=500, detail={"code": "ROLE_ASSIGN_FAILED", "message": f"역할 부여 실패({type(exc).__name__}) — 계정을 만들지 않았습니다"}) from None
    _logger.info(
        "user create: %s by=%s approver=%s admin=%s",
        mask_user(body.username), mask_user(admin), body.approver, body.admin,
    )
    audited = record_account_event("user.create", actor=admin, subject=body.username,
                                   detail={"approver": body.approver, "admin": body.admin})
    record = get_user(body.username) or {"username": body.username, "must_change_password": True}
    return {"created": True, "user": _user_view(record), "audit_recorded": audited}


@router.put("/users/{username}/roles")
async def set_roles_endpoint(username: str, body: RolesRequest, admin: str = Depends(_require_admin_jwt)) -> dict:
    name = _valid_username(username)
    if body.approver is None and body.admin is None:
        raise HTTPException(status_code=422, detail={"code": "NO_ROLE", "message": "approver 또는 admin 중 하나는 지정해야 합니다"})
    record = get_user(name)
    if not record:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": f"계정이 없습니다: {name}"})
    actual = str(record.get("username") or name)
    if body.admin is False:
        # lockout 방어 — 자기 자신의 admin 해제는 거부한다. "다음 요청부터 아무도 계정을 못 만든다" 로 끝나고, 회복 경로는
        # 파일 편집 + 재기동뿐이다(docs/admin-operations.md). ⚠ "마지막 admin" 검사는 따로 두지 않는다 — 이 endpoint 의
        # 행위자는 항상 admin 이므로 **남을 내리면 자기가 남는다**. 그 검사는 도달 불가한 죽은 가지였다(뮤테이션 M9 생존).
        if actual.lower() == admin.strip().lower():
            raise HTTPException(status_code=409, detail={"code": "SELF_DEMOTE", "message": "자기 자신의 admin 권한은 해제할 수 없습니다"})
    changed: dict = {}
    if body.approver is True:
        changed["approver"] = add_approver(actual).get("added")
    elif body.approver is False:
        changed["approver"] = remove_approver(actual).get("removed")
    if body.admin is True:
        changed["admin"] = add_admin(actual).get("added")
    elif body.admin is False:
        changed["admin"] = remove_admin(actual).get("removed")
    _logger.info("user roles: %s by=%s %s", mask_user(actual), mask_user(admin), changed)
    audited = record_account_event("user.roles", actor=admin, subject=actual,
                                   detail={"approver": body.approver, "admin": body.admin, "changed": changed})
    return {"ok": True, "changed": changed, "user": _user_view(get_user(actual) or record), "audit_recorded": audited}


@router.delete("/users/{username}")
async def delete_user_endpoint(username: str, admin: str = Depends(_require_admin_jwt)) -> dict:
    name = _valid_username(username)
    if name.lower() == admin.strip().lower():
        raise HTTPException(status_code=409, detail={"code": "SELF_DELETE", "message": "자기 자신은 삭제할 수 없습니다"})
    record = get_user(name)
    if not record:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": f"계정이 없습니다: {name}"})
    actual = str(record.get("username") or name)
    # (마지막 admin 검사 없음 — 위 roles 와 같은 이유: 행위자가 admin 이라 남을 지워도 자기가 남는다. 자기는 SELF_DELETE.)
    # 역할부터 지운다 — 계정은 지웠는데 목록에 이름이 남으면, 같은 이름으로 다시 만든 계정이 역할을 **상속**한다.
    remove_approver(actual)
    remove_admin(actual)
    result = remove_user(actual)
    _logger.info("user delete: %s by=%s removed=%s", mask_user(actual), mask_user(admin), result.get("removed"))
    audited = record_account_event("user.delete", actor=admin, subject=actual, detail={"removed": bool(result.get("removed"))})
    return {"ok": True, "removed": bool(result.get("removed")), "username": actual, "audit_recorded": audited}


@router.post("/login")
async def login(body: LoginRequest) -> dict:
    """45차 C1 — username + password 검증 → JWT access + refresh 발급.

    실패 시 401 INVALID_CREDENTIALS — username 존재 여부 노출 안 함 (timing).
    성공 시 must_change_password 표시로 frontend가 PW 변경 화면 강제.
    """
    record = verify_credentials(body.username, body.password)
    if not record:
        _logger.warning("Login failed: user=%s", mask_user(body.username))
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "사용자명 또는 비밀번호 불일치"},
        )
    actual_username = record["username"]
    # 47차 W35: token_version을 access/refresh 모두에 포함 → logout/PW 변경 시 즉시 무효화
    tv = int(record.get("token_version", 0))
    access = create_access_token(actual_username, token_version=tv)
    refresh = create_refresh_token(actual_username, token_version=tv)
    _logger.info("Login OK: user=%s", mask_user(actual_username))
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
async def change_password_endpoint(
    body: ChangePasswordRequest,
    user: str = Depends(require_jwt_user),
) -> dict:
    """본인 PW 변경 — 임시 PW 후 첫 로그인 시 호출.

    48차 C5: JWT-only 인증 강제 (DEV_MODE X-User fallback 거부) — 다른 사용자
    PW 변경 spoofing 차단. require_jwt_user Depends.
    """
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
    _logger.info("Password changed: user=%s new_tv=%d", mask_user(user), new_tv)
    return {
        "changed": True,
        "username": user,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(user: str = Depends(require_jwt_user)) -> dict:
    """47차 W35 — 인증된 사용자의 token_version 증가 → 기존 토큰 모두 즉시 무효화.

    이전 (45차): stateless. 도난된 refresh 7일간 유효.
    47차: server-side revocation. logout 직후 모든 access/refresh 거부 (TOKEN_REVOKED).
    48차 C5: JWT-only 강제 (X-User fallback 거부) — 다른 사용자 강제 logout spoofing 차단.
    """
    try:
        result = increment_token_version(user)
        _logger.info("Logout OK: user=%s new_tv=%d", mask_user(user), result["new_token_version"])
        return {"ok": True, "username": user, "revoked": True}
    except ValueError:
        # 사용자 삭제됨 — 그래도 OK 응답 (client 측 정리)
        return {"ok": True, "message": "client 측 토큰 삭제 (server 측 사용자 없음)"}


# 48차 W44: `_mask` 중복 제거 — `admin_users.mask_user` 단일 출처 사용.
# 이전 (45차): auth_router 내부에 자체 _mask 함수 정의. W19와 동일 패턴 재발.
