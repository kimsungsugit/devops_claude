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


__all__ = [
    "ADMIN_USERS_PATH",
    "load_admins",
    "is_admin",
    "save_admins",
    "add_admin",
    "remove_admin",
]
