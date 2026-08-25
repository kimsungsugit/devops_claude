"""40차 — Admin role 영구 저장소 + 검증.

`config/admin_users.json`에 admin 사용자 list 저장. X-User 헤더값 매칭으로 is_admin 판정.

scm_registry.py + cloudium_extra_prefixes.py 패턴 차용:
    - FileLock (선택) + threading.Lock fallback
    - atomic write (.tmp → os.replace)
    - lru_cache + mtime invalidate (swut_meta 12차 패턴)
    - 손상 파일 graceful (빈 set fallback + .invalid backup)

ISO 26262: admin 권한은 audit 정책 강화 — 누구나 builder 호출 차단 (산출물 무결성).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    FileLock = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_USERS_PATH = REPO_ROOT / "config" / "admin_users.json"
_LOCK = (
    FileLock(str(ADMIN_USERS_PATH) + ".lock", timeout=10)
    if FileLock
    else threading.Lock()
)

# 12차 패턴 — mtime 기반 캐시 invalidate
_cache: dict[str, Any] = {"mtime": 0.0, "admins": set()}
_CACHE_LOCK = threading.Lock()


def _empty_store() -> dict[str, Any]:
    return {"admins": [], "schema_version": 1}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        # `.gitattributes` 는 `*.json text eol=lf` 다. `newline` 을 안 주면 Windows 에서
        # `\n` -> `\r\n` 으로 바뀌어, 설정을 한 번 저장하는 것만으로 파일 전체 줄끝이
        # 뒤집힌다. 같은 실수가 훅 스크립트에서 나면 bash 가 실행을 거부한다.
        newline="\n",
    )
    os.replace(str(tmp), str(path))


def _ensure_file() -> None:
    if not ADMIN_USERS_PATH.exists():
        _atomic_write(ADMIN_USERS_PATH, _empty_store())


def _read_admins_raw() -> set[str]:
    """Disk에서 raw load — cache 무시."""
    _ensure_file()
    try:
        raw = json.loads(ADMIN_USERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        # 손상 파일 — backup + 빈 set fallback
        try:
            ADMIN_USERS_PATH.rename(
                ADMIN_USERS_PATH.with_suffix(".invalid.json"),
            )
        except Exception:  # pragma: no cover
            pass
        _atomic_write(ADMIN_USERS_PATH, _empty_store())
        return set()
    if not isinstance(raw, dict):
        return set()
    admins = raw.get("admins") or []
    # case 보존 — 단 is_admin은 lowercase 비교
    return {str(a).strip() for a in admins if isinstance(a, str) and str(a).strip()}


def load_admins() -> set[str]:
    """캐시 + mtime invalidate로 admin set 반환."""
    try:
        current_mtime = ADMIN_USERS_PATH.stat().st_mtime if ADMIN_USERS_PATH.exists() else 0.0
    except OSError:
        current_mtime = 0.0

    with _CACHE_LOCK:
        if _cache["mtime"] == current_mtime and current_mtime > 0:
            return set(_cache["admins"])  # shallow copy
        admins = _read_admins_raw()
        _cache["mtime"] = current_mtime
        _cache["admins"] = admins
        return set(admins)


def is_admin(user: str) -> bool:
    """X-User 헤더값을 admin set과 비교 (lowercase, trim)."""
    if not user:
        return False
    u = user.strip().lower()
    if not u or u == "default":
        return False
    return any(a.lower() == u for a in load_admins())


def save_admins(admins: list[str]) -> None:
    """전체 admin list 일괄 저장 + cache invalidate."""
    payload = {
        "admins": sorted(set(str(a).strip() for a in admins if isinstance(a, str) and str(a).strip())),
        "schema_version": 1,
    }
    with _LOCK:
        _atomic_write(ADMIN_USERS_PATH, payload)
    # invalidate cache — 다음 load_admins에서 재읽기
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0


def add_admin(user: str) -> dict[str, Any]:
    """admin 추가. 중복 시 added=False.

    Returns:
        {"added": bool, "user": str, "admins": list[str]}
    """
    u = (user or "").strip()
    if not u:
        raise ValueError("user가 비어있음")
    with _LOCK:
        current = _read_admins_raw()
        if any(a.lower() == u.lower() for a in current):
            return {"added": False, "user": u, "admins": sorted(current)}
        current.add(u)
        _atomic_write(
            ADMIN_USERS_PATH,
            {"admins": sorted(current), "schema_version": 1},
        )
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"added": True, "user": u, "admins": sorted(current)}


def remove_admin(user: str) -> dict[str, Any]:
    """admin 제거. 미존재 시 removed=False."""
    u = (user or "").strip()
    if not u:
        raise ValueError("user가 비어있음")
    with _LOCK:
        current = _read_admins_raw()
        target = next((a for a in current if a.lower() == u.lower()), None)
        if not target:
            return {"removed": False, "user": u, "admins": sorted(current)}
        current.discard(target)
        _atomic_write(
            ADMIN_USERS_PATH,
            {"admins": sorted(current), "schema_version": 1},
        )
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"removed": True, "user": u, "admins": sorted(current)}


def mask_user(user: str) -> str:
    """43차 W19 — admin user 이름 log 마스킹 (예: 'hbrnd2' → 'hb***2').

    backend log 또는 외부 노출 시 admin 사용자 보호. 42차에 `_mask_user` (private)로
    도입했으나 `dependencies/admin.py`가 underscore private 함수를 import하는
    convention 위반 → 43차에 public name으로 승격. backward-compat alias 유지.
    """
    u = (user or "").strip()
    if len(u) <= 2:
        return "*" * len(u)
    if len(u) <= 4:
        return u[0] + "*" * (len(u) - 1)
    return u[:2] + "*" * (len(u) - 3) + u[-1]


# 43차 W19 — 42차 import path backward-compat (기존 tests / 외부 코드).
# 44차 I3 — DeprecationWarning + alias 유지. 45차+ 완전 제거 검토.
def _mask_user(user: str) -> str:  # noqa: D401 — alias docstring 불필요
    """Deprecated — use `mask_user` instead (44차 I3)."""
    import warnings as _warnings
    _warnings.warn(
        "admin_users._mask_user is deprecated; use mask_user (44차 I3).",
        DeprecationWarning,
        stacklevel=2,
    )
    return mask_user(user)


def bootstrap_from_env() -> dict[str, Any]:
    """41차 W2 — env BOOTSTRAP_ADMIN_USERS 콤마 list로 admin 자동 초기화.

    backend startup 시 main.py lifespan에서 1회 호출. 빈 admin_users.json 시
    lockout 회복용 + 첫 사용자 등록 편의.

    동작:
        - env 변수 없음/공백 → action="skipped_no_env"
        - 이미 admin 있음 → action="skipped_has_admins" (env 변경해도 영향 없음)
        - 빈 admin + env 있음 → action="bootstrapped" + added list

    Returns:
        {"action": str, "added": list[str]}
    """
    env_val = os.environ.get("BOOTSTRAP_ADMIN_USERS", "").strip()
    if not env_val:
        return {"action": "skipped_no_env", "added": []}
    current = _read_admins_raw()
    if current:
        return {"action": "skipped_has_admins", "added": []}
    new_users = [u.strip() for u in env_val.split(",") if u.strip()]
    if not new_users:
        return {"action": "skipped_no_env", "added": []}
    save_admins(new_users)
    # 42차 W7+W18: 응답에 평문 user 포함 안 함 — count + masked만 노출. log/audit 안전.
    # 43차 W19: public name `mask_user` 사용 (underscore private 사용 회피).
    return {
        "action": "bootstrapped",
        "added_count": len(new_users),
        "added_masked": [mask_user(u) for u in new_users],
    }


__all__ = [
    "ADMIN_USERS_PATH",
    "load_admins",
    "is_admin",
    "save_admins",
    "add_admin",
    "remove_admin",
    "bootstrap_from_env",
    "mask_user",  # 43차 W19 — public API
]
