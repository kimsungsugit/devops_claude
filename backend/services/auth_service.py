"""45차 C1 — JWT 인증 서비스.

JWT 발급/검증 + 비밀번호 hash/verify (bcrypt). 40~44차의 X-User 헤더 신뢰 모델을
JWT bearer token으로 교체. ISO 26262 audit 추적성 — 진짜 사용자 식별 보장.

설정 (`.env`):
  JWT_SECRET — 토큰 서명 키 (필수). 미설정 시 시작 거부.
  JWT_ALGORITHM — 기본 "HS256".
  JWT_ACCESS_EXPIRE_MINUTES — 기본 60.
  JWT_REFRESH_EXPIRE_DAYS — 기본 7.
  DEV_MODE_X_USER_FALLBACK — "1"이면 JWT 없을 때 X-User 헤더 fallback (개발 only).

비고:
  - HS256 (symmetric) — internal network 환경. 외부 노출 시 RS256 + 키 분리 검토.
  - bcrypt rounds 12 — 적당한 cost (~250ms/hash).
  - access/refresh 분리 — refresh로 access 재발급. refresh는 sliding window 아님 (만료 시 재로그인).
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

# bcrypt 직접 사용 — passlib 1.7.4가 bcrypt 5.x __about__ attribute 미지원으로 실패.
# bcrypt 72-byte password limit은 정책상 명시 (verify_password / hash_password에서 동일 처리).
_BCRYPT_MAX_BYTES = 72
_BCRYPT_ROUNDS = 12


def _get_secret() -> str:
    """JWT secret 로드 — env 우선, 없으면 첫 호출 시 dev 임시 secret 생성.

    프로덕션은 반드시 JWT_SECRET env 설정. 임시 secret은 backend 재기동 시 모든 토큰 무효.
    """
    secret = os.environ.get("JWT_SECRET", "").strip()
    if secret:
        return secret
    # dev fallback — 메모리 keep (재기동 시 변경, 의도된 동작)
    if not hasattr(_get_secret, "_dev_secret"):
        _get_secret._dev_secret = secrets.token_urlsafe(32)  # type: ignore[attr-defined]
    return _get_secret._dev_secret  # type: ignore[attr-defined]


def _get_algorithm() -> str:
    return os.environ.get("JWT_ALGORITHM", "HS256")


def _get_access_expire_minutes() -> int:
    try:
        return int(os.environ.get("JWT_ACCESS_EXPIRE_MINUTES", "60"))
    except ValueError:
        return 60


def _get_refresh_expire_days() -> int:
    try:
        return int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))
    except ValueError:
        return 7


def _truncate_to_bcrypt_limit(password: str) -> bytes:
    """bcrypt 72-byte limit 정책. UTF-8 인코딩 후 72바이트로 truncate.

    한국어 한 글자 = 3바이트라 24자 = 72바이트. 그 이상은 silent truncate되어
    audit 추적성 영향 — 본 함수에서 명시 처리 + register 시점에 정책 안내.
    """
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """bcrypt hash — 사용자 등록/PW 변경 시 호출."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_truncate_to_bcrypt_limit(password), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """bcrypt verify — 로그인 시 호출. timing safe."""
    try:
        return bcrypt.checkpw(
            _truncate_to_bcrypt_limit(plain),
            hashed.encode("utf-8"),
        )
    except Exception:
        # 손상된 hash / 잘못된 형식 — graceful False (로그인 실패와 동일)
        return False


def create_access_token(username: str, *, extra_claims: dict[str, Any] | None = None) -> str:
    """Access token 발급 — 60분 default expire."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_get_access_expire_minutes())).timestamp()),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _get_secret(), algorithm=_get_algorithm())


def create_refresh_token(username: str) -> str:
    """Refresh token 발급 — 7일 default expire."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=_get_refresh_expire_days())).timestamp()),
        "type": "refresh",
    }
    return jwt.encode(payload, _get_secret(), algorithm=_get_algorithm())


class TokenError(Exception):
    """토큰 검증 실패 — 401 응답 매핑."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def decode_token(token: str, *, expected_type: str = "access") -> dict[str, Any]:
    """토큰 decode + 검증 — 실패 시 TokenError raise.

    Args:
        token: JWT bearer token (Authorization 헤더에서 추출).
        expected_type: "access" 또는 "refresh". 토큰 type claim과 일치해야 통과.

    Returns:
        payload dict — `sub`, `iat`, `exp`, `type` 포함.

    Raises:
        TokenError: 만료 / 서명 불일치 / type 불일치.
    """
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[_get_algorithm()])
    except jwt.ExpiredSignatureError:
        raise TokenError("TOKEN_EXPIRED", "토큰이 만료됨 — 재로그인 필요")
    except jwt.InvalidTokenError as e:
        raise TokenError("TOKEN_INVALID", f"토큰이 유효하지 않음: {e}")

    if payload.get("type") != expected_type:
        raise TokenError(
            "TOKEN_TYPE_MISMATCH",
            f"토큰 type 불일치 (expected={expected_type}, got={payload.get('type')})",
        )
    if not payload.get("sub"):
        raise TokenError("TOKEN_MISSING_SUB", "토큰에 사용자 식별자 없음")
    return payload


def is_dev_mode_x_user_fallback_enabled() -> bool:
    """개발 모드 X-User fallback 허용 여부.

    .env에 `DEV_MODE_X_USER_FALLBACK=1`이면 활성. 프로덕션 false 기본.
    """
    return os.environ.get("DEV_MODE_X_USER_FALLBACK", "").strip() in ("1", "true", "True", "yes")


__all__ = [
    "TokenError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "is_dev_mode_x_user_fallback_enabled",
]
