from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.scm_registry import get_registry_entry
from workflow.delta_update import get_changed_files
from workflow.scm_fallback import diff_source_snapshot


@dataclass
class ChangeTrigger:
    trigger_type: str
    scm_id: str
    source_root: str
    scm_type: str
    base_ref: str
    changed_files: List[str] = field(default_factory=list)
    dry_run: bool = False
    auto_generate: bool = False
    targets: List[str] | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_registry_trigger(
    *,
    trigger_type: str,
    scm_id: str,
    base_ref: str = "",
    dry_run: bool = False,
    auto_generate: bool = False,
    targets: Optional[List[str]] = None,
    manual_changed_files: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ChangeTrigger:
    entry = get_registry_entry(scm_id)
    if entry is None:
        raise KeyError(scm_id)

    changed_files = [str(x).strip() for x in (manual_changed_files or []) if str(x).strip()]
    scm_type = str(entry.scm_type or "git").lower()
    default_base_ref = "" if scm_type == "svn" else "HEAD~1"
    resolved_base_ref = str(base_ref or entry.base_ref or default_base_ref).strip()
    if not changed_files:
        if scm_type in {"git", "svn"} and str(entry.source_root or "").strip():
            changed_files = get_changed_files(
                str(entry.source_root),
                base_ref=resolved_base_ref,
                scm_type=scm_type,
            )
        else:
            snapshot = diff_source_snapshot(
                scm_id,
                str(entry.source_root),
                watch_patterns=list(entry.watch_patterns or []),
                ignore_patterns=list(entry.ignore_patterns or []),
            )
            changed_files = list(snapshot.get("changed_files") or [])
            metadata = {**(metadata or {}), "snapshot": snapshot}

    return ChangeTrigger(
        trigger_type=trigger_type,
        scm_id=entry.id,
        source_root=str(entry.source_root or ""),
        scm_type=scm_type,
        base_ref=resolved_base_ref,
        changed_files=changed_files,
        dry_run=bool(dry_run),
        auto_generate=bool(auto_generate),
        targets=list(targets) if targets else None,
        metadata=dict(metadata or {}),
    )
