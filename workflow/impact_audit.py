from __future__ import annotations

import os
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO_ROOT / "reports" / "impact_audit"
LOCK_PATH = AUDIT_DIR / ".run_lock"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except Exception:
        return False
    return True


def _thread_alive(thread_id: int) -> bool:
    try:
        wanted = int(thread_id)
    except Exception:
        return False
    for thread in threading.enumerate():
        ident = getattr(thread, "ident", None)
        native_id = getattr(thread, "native_id", None)
        if ident == wanted or native_id == wanted:
            return True
    return False


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return raw if isinstance(raw, dict) else default


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_audit_dir() -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIT_DIR


def acquire_run_lock(scm_id: str) -> Dict[str, Any]:
    ensure_audit_dir()
    if LOCK_PATH.exists():
        existing = _load_json(LOCK_PATH, default={}) or {}
        pid = int(existing.get("pid") or 0)
        thread_id = int(existing.get("thread_id") or 0)
        if pid and _pid_alive(pid) and thread_id and _thread_alive(thread_id):
            return {"ok": False, "reason": "active_lock", "lock_path": str(LOCK_PATH), "lock": existing}
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    payload = {
        "scm_id": str(scm_id or "").strip(),
        "started_at": _now_iso(),
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
    }
    _save_json(LOCK_PATH, payload)
    return {"ok": True, "lock_path": str(LOCK_PATH), "lock": payload}


def release_run_lock() -> bool:
    if not LOCK_PATH.exists():
        return False
    try:
        LOCK_PATH.unlink()
        return True
    except OSError:
        return False


def write_impact_audit(payload: Dict[str, Any]) -> Path:
    ensure_audit_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = AUDIT_DIR / f"impact_{ts}.json"
    _save_json(out, payload)
    return out


def list_impact_audits(scm_id: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    ensure_audit_dir()
    target_scm = str(scm_id or "").strip()
    items: List[Dict[str, Any]] = []
    for path in sorted(AUDIT_DIR.glob("impact_*.json"), reverse=True):
        raw = _load_json(path, default={})
        if not raw:
            continue
        if target_scm and str(raw.get("scm_id") or "").strip() != target_scm:
            continue
        actions = raw.get("actions") if isinstance(raw.get("actions"), dict) else {}
        auto_count = 0
        flag_count = 0
        failed_count = 0
        for info in actions.values():
            if not isinstance(info, dict):
                continue
            mode = str(info.get("mode") or "").upper()
            status = str(info.get("status") or "").lower()
            if mode == "AUTO":
                auto_count += 1
            elif mode == "FLAG":
                flag_count += 1
            if status == "failed":
                failed_count += 1
        items.append(
            {
                "path": str(path),
                "filename": path.name,
                "timestamp": raw.get("timestamp") or raw.get("started_at") or path.stem.replace("impact_", ""),
                "scm_id": raw.get("scm_id", ""),
                "trigger": raw.get("trigger", ""),
                "dry_run": bool(raw.get("dry_run")),
                "changed_files": raw.get("changed_files") or [],
                "changed_functions": raw.get("changed_functions") or {},
                "warnings": raw.get("warnings") or [],
                "auto_count": auto_count,
                "flag_count": flag_count,
                "failed_count": failed_count,
                "actions": actions,
            }
        )
        if len(items) >= max(1, int(limit or 10)):
            break
    return items
