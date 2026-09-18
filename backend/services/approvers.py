"""승인자(approver) 목록 — `config/approvers.json` (R48-a).

## 왜 admin 과 따로 두나

검토 기록 쓰기는 R34 부터 **admin 전용**이었다(계획서 §8 #8 (a) — "유일하게 실재하는 권한 목록").
그 결정의 결과는 계정 1개(`hbrnd2`) 가 생성도 하고 승인도 하는 **단독 검토**였다. ISO 26262 의 검토는
만든 사람과 확인하는 사람이 달라야 의미가 있으므로(4-eyes), 승인 권한을 admin 과 분리해 **역할 목록**으로
둔다. admin 은 계정을 만들고 역할을 주는 사람이고, approver 는 산출물에 판정을 남기는 사람이다. 한 사람이
둘 다일 수는 있지만, **자기가 만든 run 은 승인할 수 없다**(`workflow/quality/review.py::SelfReview`).

## 저장소 규약

`backend/services/admin_users.py` 와 같은 패턴 — FileLock(없으면 threading.Lock) · 원자 쓰기(`.tmp` →
`os.replace`, `newline="\\n"`) · mtime 캐시 무효화 · 손상 파일은 `.invalid.json` 으로 비켜 두고 빈 목록.
비교는 lowercase/trim(사용자 이름 비교 규약을 admin 과 같게 — 둘이 갈리면 같은 사람이 한쪽에서만 통과한다).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    FileLock = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVERS_PATH = REPO_ROOT / "config" / "approvers.json"
_LOCK = (
    FileLock(str(APPROVERS_PATH) + ".lock", timeout=10)
    if FileLock
    else threading.Lock()
)

_cache: dict[str, Any] = {"mtime": 0.0, "approvers": set()}
_CACHE_LOCK = threading.Lock()


def _empty_store() -> dict[str, Any]:
    return {"approvers": [], "schema_version": 1}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # `.gitattributes` `*.json text eol=lf` — 저장 한 번으로 줄끝이 뒤집히지 않게
    )
    os.replace(str(tmp), str(path))


def _ensure_file() -> None:
    if not APPROVERS_PATH.exists():
        _atomic_write(APPROVERS_PATH, _empty_store())


def _read_raw() -> set[str]:
    """디스크에서 그대로 읽는다 — 캐시 무시."""
    _ensure_file()
    try:
        raw = json.loads(APPROVERS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # 손상 파일은 비켜 두고 빈 목록 — 승인 권한이 조용히 **넓어지는** 쪽으로는 접히지 않는다.
        # 다만 그 사실은 남긴다(승인자가 갑자기 전원 사라진 이유가 로그에 있어야 한다).
        _logger.warning("approvers.json 을 읽지 못해 빈 목록으로 대체한다(%s: %s)", type(exc).__name__, exc)
        try:
            APPROVERS_PATH.rename(APPROVERS_PATH.with_suffix(".invalid.json"))
        except OSError as rexc:  # pragma: no cover
            _logger.warning("손상 approvers.json 백업 실패(%s)", rexc)
        _atomic_write(APPROVERS_PATH, _empty_store())
        return set()
    if not isinstance(raw, dict):
        return set()
    items = raw.get("approvers") or []
    return {str(a).strip() for a in items if isinstance(a, str) and str(a).strip()}


def load_approvers() -> set[str]:
    """캐시 + mtime 무효화."""
    try:
        current_mtime = APPROVERS_PATH.stat().st_mtime if APPROVERS_PATH.exists() else 0.0
    except OSError:
        current_mtime = 0.0
    with _CACHE_LOCK:
        if _cache["mtime"] == current_mtime and current_mtime > 0:
            return set(_cache["approvers"])
        items = _read_raw()
        _cache["mtime"] = current_mtime
        _cache["approvers"] = items
        return set(items)


def is_approver(user: str) -> bool:
    """승인자 목록에 있는가 — lowercase/trim 비교, `default` 는 항상 False."""
    if not user:
        return False
    u = user.strip().lower()
    if not u or u == "default":
        return False
    return any(a.lower() == u for a in load_approvers())


def save_approvers(approvers: list[str]) -> None:
    payload = {
        "approvers": sorted({str(a).strip() for a in approvers if isinstance(a, str) and str(a).strip()}),
        "schema_version": 1,
    }
    with _LOCK:
        _atomic_write(APPROVERS_PATH, payload)
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0


def add_approver(user: str) -> dict[str, Any]:
    """추가. 이미 있으면(대소문자 무시) `added=False`."""
    name = (user or "").strip()
    if not name:
        raise ValueError("user 가 비어 있다")
    with _LOCK:
        current = _read_raw()
        if any(a.lower() == name.lower() for a in current):
            return {"added": False, "user": name, "approvers": sorted(current)}
        current.add(name)
        _atomic_write(APPROVERS_PATH, {"approvers": sorted(current), "schema_version": 1})
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"added": True, "user": name, "approvers": sorted(current)}


def remove_approver(user: str) -> dict[str, Any]:
    """제거(대소문자 무시). 없으면 `removed=False`."""
    name = (user or "").strip()
    if not name:
        raise ValueError("user 가 비어 있다")
    with _LOCK:
        current = _read_raw()
        keep = {a for a in current if a.lower() != name.lower()}
        if len(keep) == len(current):
            return {"removed": False, "user": name, "approvers": sorted(current)}
        _atomic_write(APPROVERS_PATH, {"approvers": sorted(keep), "schema_version": 1})
    with _CACHE_LOCK:
        _cache["mtime"] = 0.0
    return {"removed": True, "user": name, "approvers": sorted(keep)}


__all__ = [
    "APPROVERS_PATH",
    "add_approver",
    "is_approver",
    "load_approvers",
    "remove_approver",
    "save_approvers",
]
