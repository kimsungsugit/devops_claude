from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

# 주의: in-memory 저장소 — 프로세스 전역.
#  - WEB_CONCURRENCY>1 (멀티 워커) 환경에서는 워커 간 공유되지 않으므로
#    승인 생성/해소가 서로 다른 워커로 라우팅되면 404 가 날 수 있다.
#    멀티워커 배포 시에는 SQLite/Redis 기반 영속 저장소로 교체해야 한다.
#  - 아래 TTL 로 만료분을 정리해 메모리 누수를 방지한다.
_approval_lock = threading.Lock()
_pending_approvals: Dict[str, Dict[str, Any]] = {}


def _ttl_seconds() -> float:
    try:
        import config
        return float(getattr(config, "CHAT_APPROVAL_TTL_SECONDS", 1800) or 1800)
    except Exception:
        return 1800.0


def _purge_expired_locked() -> None:
    """만료된 승인 항목 제거 (호출자가 _approval_lock 을 보유한 상태에서 호출)."""
    ttl = _ttl_seconds()
    now = time.time()
    expired = [
        k
        for k, v in _pending_approvals.items()
        if now - float(v.get("saved_at") or 0.0) > ttl
    ]
    for k in expired:
        _pending_approvals.pop(k, None)


def save_pending_approval(approval_id: str, record: Dict[str, Any]) -> None:
    payload = dict(record or {})
    payload["approval_id"] = approval_id
    payload["saved_at"] = time.time()
    with _approval_lock:
        _purge_expired_locked()
        _pending_approvals[approval_id] = payload


def get_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    with _approval_lock:
        _purge_expired_locked()
        item = _pending_approvals.get(approval_id)
        return dict(item) if isinstance(item, dict) else None


def pop_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    with _approval_lock:
        _purge_expired_locked()
        item = _pending_approvals.pop(approval_id, None)
        return dict(item) if isinstance(item, dict) else None


def mark_pending_approval_resolved(approval_id: str, decision: str, comment: str = "") -> Optional[Dict[str, Any]]:
    with _approval_lock:
        _purge_expired_locked()
        item = _pending_approvals.get(approval_id)
        if not isinstance(item, dict):
            return None
        item["decision"] = str(decision or "").strip().lower()
        item["comment"] = str(comment or "")
        item["resolved_at"] = time.time()
        _pending_approvals[approval_id] = item
        return dict(item)
