"""45차 C1 — 사용자 인증 정보 영구 저장소.

`config/users.json`에 사용자 list + bcrypt password hash 저장. JWT login 시 verify.

스키마:
{
  "users": [
    {
      "username": "hbrnd2",
      "password_hash": "$2b$12$...",
      "must_change_password": true,  # 임시 PW 발급 시 true, 변경 후 false
      "created_at": "2026-05-18T09:00:00+00:00"
    }
  ],
  "schema_version": 1
}

admin_users.py + scm_registry.py 패턴 차용:
  - FileLock (선택) + threading.Lock fallback
  - atomic write (.tmp → os.replace)
  - lru_cache + mtime invalidate
  - 손상 파일 graceful (빈 list + .invalid backup)

운영:
  - 첫 사용자 등록: admin이 add_user(username, temp_password, must_change=True)
  - 사용자 로그인: verify_credentials(username, password) → bool
  - PW 변경: change_password(username, new_password)
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    FileLock = None  # type: ignore[assignment]

from backend.services.auth_service import hash_password, verify_password

# 46차 W32 — timing attack 차단용 dummy hash.
# unknown user verify 시에도 동일한 bcrypt round 호출하여 응답 시간 동등화 → user enumeration 차단.
# module load 시 1회 계산 (~250ms, startup 1회 비용). 매 호출 새 hash 생성은 비용 과다.
_DUMMY_HASH: str | None = None


def _get_dummy_hash() -> str:
    """timing-safe verify용 dummy hash. lazy initialization (첫 unknown user verify 시).

    한 번 계산 후 module-level cache. ~250ms 1회 비용은 호출자 view에서 첫 호출 시
    추가 latency. startup 시 미리 호출하면 첫 호출 latency 없음 — main.py에서 호출 가능.
    """
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("__dummy_password_for_timing_safety__")
    return _DUMMY_HASH


def warmup_dummy_hash() -> None:
    """46차 W32 — startup 시 dummy hash 미리 계산. 첫 로그인 latency 회피.

    main.py lifespan에서 호출 권장 — 첫 unknown user 로그인이 dummy hash 계산
    ~250ms latency 추가되는 것 차단.
    """
    _get_dummy_hash()

REPO_ROOT = Path(__file__).resolve().parents[2]
USERS_PATH = REPO_ROOT / "config" / "users.json"
_LOCK = (
    FileLock(str(USERS_PATH) + ".lock", timeout=10)
    if FileLock
    else threading.Lock()
)

_cache: dict[str, Any] = {"mtime": 0.0, "users": {}}
_CACHE_LOCK = threading.Lock()


def _empty_store() -> dict[str, Any]:
    return {"users": [], "schema_version": 1}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(str(tmp), str(path))


def _ensure_file() -> None:
    if not USERS_PATH.exists():
        _atomic_write(USERS_PATH, _empty_store())


def _read_users_raw() -> dict[str, dict[str, Any]]:
    """Disk에서 raw load — username → user record dict."""
    _ensure_file()
    try:
        raw = json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        try:
            USERS_PATH.rename(USERS_PATH.with_suffix(".invalid.json"))
        except Exception:  # pragma: no cover
            pass
        _atomic_write(USERS_PATH, _empty_store())
        return {}
    if not isinstance(raw, dict):
        return {}
    users = raw.get("users") or []
    result: dict[str, dict[str, Any]] = {}
    for u in users:
        if not isinstance(u, dict):
            continue
        name = (u.get("username") or "").strip()
        if not name:
            continue
        result[name.lower()] = {  # lowercase key for case-insensitive lookup
            "username": name,  # 원래 case 보존
            "password_hash": u.get("password_hash") or "",
            "must_change_password": bool(u.get("must_change_password", False)),
            "created_at": u.get("created_at") or "",
        }
    return result


def _load_users() -> dict[str, dict[str, Any]]:
    """mtime 기반 캐시 + invalidate."""
    try:
        current_mtime = USERS_PATH.stat().st_mtime if USERS_PATH.exists() else 0.0
    except OSError:
        current_mtime = 0.0
    with _CACHE_LOCK:
        if _cache["mtime"] == current_mtime and current_mtime > 0:
            return dict(_cache["users"])
        users = _read_users_raw()
        _cache["mtime"] = current_mtime
        _cache["users"] = users
        return dict(users)


def _save_users(users_map: dict[str, dict[str, Any]]) -> None:
    payload = {
        "users": sorted(users_map.values(), key=lambda u: u["username"].lower()),
        "schema_version": 1,
    }
    with _LOCK:
        _atomic_write(USERS_PATH, payload)
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0


def user_exists(username: str) -> bool:
    """username 등록 여부 (case-insensitive)."""
    u = (username or "").strip().lower()
    if not u:
        return False
    return u in _load_users()


def get_user(username: str) -> dict[str, Any] | None:
    """user record 반환 — 미존재 시 None."""
    u = (username or "").strip().lower()
    if not u:
        return None
    return _load_users().get(u)


def verify_credentials(username: str, password: str) -> dict[str, Any] | None:
    """username + password 검증 — 성공 시 user record, 실패 시 None.

    46차 W32 timing-safe: unknown user / password_hash 없음 경우에도 dummy bcrypt
    verify 호출하여 응답 시간 동등화 → user enumeration 차단. 모든 fail path가
    동일한 bcrypt round (~250ms) 비용 소비.
    """
    user = get_user(username)
    if not user or not user.get("password_hash"):
        # unknown user / 손상 hash — dummy verify로 시간 균등화
        verify_password(password, _get_dummy_hash())
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def add_user(
    username: str,
    password: str,
    *,
    must_change_password: bool = True,
) -> dict[str, Any]:
    """사용자 등록 — admin이 호출. password는 plain → 자동 bcrypt hash.

    Returns:
        {"added": bool, "username": str, "must_change_password": bool}
    """
    name = (username or "").strip()
    if not name:
        raise ValueError("username이 비어있음")
    if not password or len(password) < 8:
        raise ValueError("password는 8자 이상 필요")
    key = name.lower()
    with _LOCK:
        current = _read_users_raw()
        if key in current:
            return {"added": False, "username": name, "must_change_password": current[key]["must_change_password"]}
        current[key] = {
            "username": name,
            "password_hash": hash_password(password),
            "must_change_password": must_change_password,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write(
            USERS_PATH,
            {
                "users": sorted(current.values(), key=lambda u: u["username"].lower()),
                "schema_version": 1,
            },
        )
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"added": True, "username": name, "must_change_password": must_change_password}


def change_password(username: str, new_password: str) -> dict[str, Any]:
    """사용자 본인이 PW 변경 — 임시 PW 후 첫 로그인 시 호출.

    Returns:
        {"changed": True} 또는 raises if user 미존재.
    """
    name = (username or "").strip()
    if not name:
        raise ValueError("username이 비어있음")
    if not new_password or len(new_password) < 8:
        raise ValueError("password는 8자 이상 필요")
    key = name.lower()
    with _LOCK:
        current = _read_users_raw()
        if key not in current:
            raise ValueError(f"사용자 '{name}' 없음")
        current[key]["password_hash"] = hash_password(new_password)
        current[key]["must_change_password"] = False
        _atomic_write(
            USERS_PATH,
            {
                "users": sorted(current.values(), key=lambda u: u["username"].lower()),
                "schema_version": 1,
            },
        )
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"changed": True}


def remove_user(username: str) -> dict[str, Any]:
    """사용자 삭제 — admin이 호출."""
    name = (username or "").strip()
    if not name:
        raise ValueError("username이 비어있음")
    key = name.lower()
    with _LOCK:
        current = _read_users_raw()
        if key not in current:
            return {"removed": False, "username": name}
        del current[key]
        _atomic_write(
            USERS_PATH,
            {
                "users": sorted(current.values(), key=lambda u: u["username"].lower()),
                "schema_version": 1,
            },
        )
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"removed": True, "username": name}


def list_users() -> list[dict[str, Any]]:
    """사용자 목록 — password_hash 제외 (외부 노출 시 안전)."""
    return [
        {
            "username": u["username"],
            "must_change_password": u["must_change_password"],
            "created_at": u["created_at"],
        }
        for u in _load_users().values()
    ]


def bootstrap_admin_user_from_env() -> dict[str, Any]:
    """45차 C1 — BOOTSTRAP_ADMIN_USER + BOOTSTRAP_ADMIN_PASSWORD env로 첫 admin 등록.

    빈 users.json + 두 env 설정 시 자동 등록. lockout 회복 + 첫 가동 편의.
    must_change_password=True로 첫 로그인 후 PW 변경 강제.

    Returns:
        {"action": "bootstrapped" | "skipped_has_users" | "skipped_no_env", "username": str?}
    """
    username = os.environ.get("BOOTSTRAP_ADMIN_USER", "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if not username or not password:
        return {"action": "skipped_no_env"}
    current = _read_users_raw()
    if current:
        return {"action": "skipped_has_users"}
    add_user(username, password, must_change_password=True)
    return {"action": "bootstrapped", "username": username}


__all__ = [
    "USERS_PATH",
    "user_exists",
    "get_user",
    "verify_credentials",
    "add_user",
    "change_password",
    "remove_user",
    "list_users",
    "bootstrap_admin_user_from_env",
]
