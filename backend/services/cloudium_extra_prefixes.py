"""39차 — Cloudium 사용자 추가 allowed_prefixes 영구 저장소.

scm_registry와 별개의 저장소 — SwIT/SwUT 빌드 input 경로 같이 SCM(추적성)과
의미가 다른 path들을 사용자가 동적 등록.

저장 위치: `config/cloudium_extra_prefixes.json`
스키마:
    {"prefixes": ["U:/...", "U:/..."], "schema_version": 1}

CRUD API:
    - load_extra_prefixes() -> list[str]
    - save_extra_prefixes(list[str]) -> None  (atomic write + lock)
    - add_prefix(prefix: str) -> dict          (중복 거부 + 정규화)
    - remove_prefix(prefix: str) -> dict       (미존재 시 graceful)

scm_registry.py 패턴 차용 — FileLock + atomic write (.tmp → os.replace).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    FileLock = None  # type: ignore[assignment]
import threading

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFIXES_PATH = REPO_ROOT / "config" / "cloudium_extra_prefixes.json"
_LOCK = (
    FileLock(str(PREFIXES_PATH) + ".lock", timeout=10)
    if FileLock
    else threading.Lock()
)


def _empty_store() -> dict[str, Any]:
    return {"prefixes": [], "schema_version": 1}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """atomic write — tmp 파일 작성 후 os.replace로 원자적 교체."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(str(tmp), str(path))


def _ensure_file() -> None:
    if not PREFIXES_PATH.exists():
        _atomic_write(PREFIXES_PATH, _empty_store())


def load_extra_prefixes() -> list[str]:
    """영구 저장된 사용자 추가 prefixes 목록 반환.

    Returns:
        list[str] — 파일 없거나 손상 시 빈 list (graceful).
    """
    _ensure_file()
    try:
        raw = json.loads(PREFIXES_PATH.read_text(encoding="utf-8"))
    except Exception:
        # 손상 파일 graceful — backup 후 빈 list 반환
        try:
            PREFIXES_PATH.rename(PREFIXES_PATH.with_suffix(".invalid.json"))
        except Exception:  # pragma: no cover
            pass
        _atomic_write(PREFIXES_PATH, _empty_store())
        return []
    if not isinstance(raw, dict):
        return []
    prefixes = raw.get("prefixes") or []
    return [str(p) for p in prefixes if isinstance(p, str) and p.strip()]


def save_extra_prefixes(prefixes: list[str]) -> None:
    """전체 prefixes 목록 일괄 저장."""
    payload = {"prefixes": list(prefixes), "schema_version": 1}
    with _LOCK:
        _atomic_write(PREFIXES_PATH, payload)


_SYSTEM_BLACKLIST = (
    # Windows 시스템 디렉토리 (대소문자 무관 prefix-match)
    "c:/windows",
    "c:\\windows",
    "c:/program files",
    "c:\\program files",
    "c:/program files (x86)",
    "c:\\program files (x86)",
    "c:/programdata",
    "c:\\programdata",
    # POSIX 시스템 root
    "/etc",
    "/root",
    "/sys",
    "/proc",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
)


def _is_blacklisted(prefix: str) -> bool:
    """53차 C2 — system 디렉토리 prefix 등록 차단.

    admin이 실수로 `C:/` 또는 `C:/Windows` 같은 시스템 prefix를 cloudium allowed_prefixes
    에 등록하면 worker가 시스템 전체 read 가능 → audit 도구 보안 경계 약화. blacklist는
    30차 W21 swut_asil_resolver 패턴 차용 (deep-reviewer C2 권장).

    Returns:
        True if prefix가 system 디렉토리거나 root drive (`C:/`, `/` 등).
    """
    norm = prefix.strip().lower().replace("\\", "/")
    # 단일 drive root (C:/, D:/ 등) 차단
    if len(norm) <= 3 and norm.endswith(":/"):
        return True
    # POSIX root 단독
    if norm == "/":
        return True
    # blacklist prefix-match
    for bad in _SYSTEM_BLACKLIST:
        bad_norm = bad.replace("\\", "/")
        if norm == bad_norm or norm.startswith(bad_norm + "/"):
            return True
    return False


def add_prefix(prefix: str) -> dict[str, Any]:
    """새 prefix 추가.

    Args:
        prefix: 추가할 경로. 공백 trim 후 빈 string이면 에러.

    Returns:
        {"added": bool, "prefix": str, "prefixes": list[str]}
        - added=False면 이미 존재 (중복) — 기존 list 그대로 반환.

    Raises:
        ValueError: prefix 빈 string 또는 system 디렉토리 (53차 C2).
    """
    p = (prefix or "").strip()
    if not p:
        raise ValueError("prefix가 비어있음 — 경로 입력 필요")
    # 53차 C2 — system 디렉토리 등록 차단 (admin 실수 보호)
    if _is_blacklisted(p):
        raise ValueError(
            f"시스템 디렉토리는 cloudium allowed_prefixes에 등록 불가: {p} "
            "(Windows: C:/Windows, Program Files 등 / POSIX: /etc, /root 등 차단)"
        )
    with _LOCK:
        current = load_extra_prefixes()
        # 정규화 비교 (case-insensitive on Windows) — file_resolver 패턴 재사용
        try:
            from backend.services.file_resolver import CloudiumFileResolver
            norm_new = CloudiumFileResolver._normalize_for_compare(p)
            existing_norm = {
                CloudiumFileResolver._normalize_for_compare(x): x for x in current
            }
        except Exception:  # pragma: no cover — graceful fallback
            norm_new = p
            existing_norm = {x: x for x in current}

        if norm_new in existing_norm:
            return {"added": False, "prefix": p, "prefixes": current}
        updated = current + [p]
        payload = {"prefixes": updated, "schema_version": 1}
        _atomic_write(PREFIXES_PATH, payload)
        return {"added": True, "prefix": p, "prefixes": updated}


def remove_prefix(prefix: str) -> dict[str, Any]:
    """prefix 제거.

    Args:
        prefix: 제거할 경로.

    Returns:
        {"removed": bool, "prefix": str, "prefixes": list[str]}
        - removed=False면 미존재 (graceful).
    """
    p = (prefix or "").strip()
    if not p:
        raise ValueError("prefix가 비어있음 — 경로 입력 필요")
    with _LOCK:
        current = load_extra_prefixes()
        try:
            from backend.services.file_resolver import CloudiumFileResolver
            norm_target = CloudiumFileResolver._normalize_for_compare(p)
            updated = [
                x for x in current
                if CloudiumFileResolver._normalize_for_compare(x) != norm_target
            ]
        except Exception:  # pragma: no cover
            updated = [x for x in current if x != p]

        if len(updated) == len(current):
            return {"removed": False, "prefix": p, "prefixes": current}
        payload = {"prefixes": updated, "schema_version": 1}
        _atomic_write(PREFIXES_PATH, payload)
        return {"removed": True, "prefix": p, "prefixes": updated}


__all__ = [
    "PREFIXES_PATH",
    "load_extra_prefixes",
    "save_extra_prefixes",
    "add_prefix",
    "remove_prefix",
]
