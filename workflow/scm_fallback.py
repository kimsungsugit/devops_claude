from __future__ import annotations

import fnmatch
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO_ROOT / "reports" / "impact_audit"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _snapshot_path(scm_id: str) -> Path:
    safe_id = "".join(ch for ch in str(scm_id or "default") if ch.isalnum() or ch in {"_", "-"})
    safe_id = safe_id or "default"
    return AUDIT_DIR / f".source_snapshot_{safe_id}.json"


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


def _match_any(path_str: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path_str, pat) for pat in patterns if str(pat).strip())


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_source_snapshot(
    source_root: str,
    *,
    watch_patterns: List[str] | None = None,
    ignore_patterns: List[str] | None = None,
) -> Dict[str, Any]:
    root = Path(source_root).expanduser().resolve()
    watch = watch_patterns or ["*.c", "*.h"]
    ignore = ignore_patterns or []
    files: Dict[str, Dict[str, Any]] = {}
    if not root.exists() or not root.is_dir():
        return {"snapshot_at": _now_iso(), "files": files}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if watch and not _match_any(rel, watch):
            continue
        if ignore and _match_any(rel, ignore):
            continue
        stat = path.stat()
        files[rel] = {
            "mtime": int(stat.st_mtime),
            "md5": _file_md5(path),
        }
    return {
        "snapshot_at": _now_iso(),
        "files": files,
    }


def load_source_snapshot(scm_id: str) -> Dict[str, Any]:
    path = _snapshot_path(scm_id)
    raw = _load_json(path, default={"snapshot_at": "", "files": {}})
    if not isinstance(raw, dict):
        return {"snapshot_at": "", "files": {}}
    raw.setdefault("snapshot_at", "")
    raw.setdefault("files", {})
    return raw


def save_source_snapshot(scm_id: str, snapshot: Dict[str, Any]) -> Path:
    path = _snapshot_path(scm_id)
    _save_json(path, snapshot)
    return path


def diff_source_snapshot(
    scm_id: str,
    source_root: str,
    *,
    watch_patterns: List[str] | None = None,
    ignore_patterns: List[str] | None = None,
) -> Dict[str, Any]:
    previous = load_source_snapshot(scm_id)
    current = collect_source_snapshot(
        source_root,
        watch_patterns=watch_patterns,
        ignore_patterns=ignore_patterns,
    )
    prev_files = previous.get("files") or {}
    cur_files = current.get("files") or {}
    changed: List[str] = []
    removed: List[str] = []
    if not prev_files:
        changed = sorted(cur_files.keys())
    else:
        for rel, cur_meta in cur_files.items():
            prev_meta = prev_files.get(rel)
            if not isinstance(prev_meta, dict):
                changed.append(rel)
                continue
            if prev_meta.get("mtime") != cur_meta.get("mtime") or prev_meta.get("md5") != cur_meta.get("md5"):
                changed.append(rel)
        for rel in prev_files.keys():
            if rel not in cur_files:
                removed.append(rel)
    return {
        "scm_id": scm_id,
        "snapshot_path": str(_snapshot_path(scm_id)),
        "previous_snapshot_at": previous.get("snapshot_at") or "",
        "current_snapshot_at": current.get("snapshot_at") or "",
        "changed_files": sorted(dict.fromkeys(changed + removed)),
        "removed_files": sorted(removed),
        "current_snapshot": current,
    }
