from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_approval_lock = threading.Lock()
_pending_approvals: Dict[str, Dict[str, Any]] = {}


def save_pending_approval(approval_id: str, record: Dict[str, Any]) -> None:
    payload = dict(record or {})
    payload["approval_id"] = approval_id
    payload["saved_at"] = time.time()
    with _approval_lock:
        _pending_approvals[approval_id] = payload


def get_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    with _approval_lock:
        item = _pending_approvals.get(approval_id)
        return dict(item) if isinstance(item, dict) else None


def pop_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    with _approval_lock:
        item = _pending_approvals.pop(approval_id, None)
        return dict(item) if isinstance(item, dict) else None


def mark_pending_approval_resolved(approval_id: str, decision: str, comment: str = "") -> Optional[Dict[str, Any]]:
    with _approval_lock:
        item = _pending_approvals.get(approval_id)
        if not isinstance(item, dict):
            return None
        item["decision"] = str(decision or "").strip().lower()
        item["comment"] = str(comment or "")
        item["resolved_at"] = time.time()
        _pending_approvals[approval_id] = item
        return dict(item)
