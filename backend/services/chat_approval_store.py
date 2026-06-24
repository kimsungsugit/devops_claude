"""미해소 승인 요청 영속 저장소 (SQLite — 멀티워커 공유, R2).

이전: in-memory(프로세스 전역) → WEB_CONCURRENCY>1 에서 생성/해소가 다른 워커로
라우팅되면 404. 이제 chat_history.sqlite 의 chat_pending_approvals 테이블에 영속화해
워커/재시작과 무관하게 공유한다. TTL(saved_at 기준)로 만료분 정리.

pop 은 SELECT(payload) → DELETE → rowcount 검사의 단일 승자 패턴으로 원자적이다
(SQLite write lock 직렬화 — DELETE 가 1행을 지운 트랜잭션만 승자). RETURNING 을
쓰지 않으므로 구버전 SQLite(<3.35, 예: Ubuntu 20.04)에서도 동작한다.

write lock 최소화: bulk 만료 정리(_purge_expired)는 쓰기 경로(save)에서만 수행하고,
read(get)는 write lock 없이 in-memory 만료 판정만 한다(폴링 시 lock 경합 방지).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy import text

from backend.services.chat_history_db import get_session
from backend.services.chat_history_models import ChatPendingApproval

_logger = logging.getLogger("backend.chat_approval_store")


def _ttl_seconds() -> float:
    try:
        import config
        val = float(getattr(config, "CHAT_APPROVAL_TTL_SECONDS", 1800) or 1800)
        return val if val > 0 else 1800.0  # 0/falsy/음수 → 기본값
    except Exception:
        return 1800.0


def _is_expired(saved_at: Any) -> bool:
    try:
        return (time.time() - float(saved_at or 0.0)) > _ttl_seconds()
    except (TypeError, ValueError):
        return False


def _purge_expired(sess) -> None:
    """만료(saved_at < now-ttl) 항목 일괄 제거. 쓰기 경로(save)에서만 호출."""
    cutoff = time.time() - _ttl_seconds()
    sess.query(ChatPendingApproval).filter(
        ChatPendingApproval.saved_at < cutoff,
    ).delete(synchronize_session=False)


def _decode(payload: Optional[str]) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    try:
        obj = json.loads(payload)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def save_pending_approval(approval_id: str, record: Dict[str, Any]) -> None:
    payload = dict(record or {})
    payload["approval_id"] = approval_id
    payload["saved_at"] = time.time()
    data = json.dumps(payload, ensure_ascii=False, default=str)
    try:
        with get_session() as sess:
            _purge_expired(sess)  # 쓰기 경로에서만 bulk 정리
            obj = sess.get(ChatPendingApproval, approval_id)
            if obj is None:
                sess.add(ChatPendingApproval(
                    approval_id=approval_id,
                    owner=payload.get("owner"),
                    payload=data,
                    saved_at=float(payload["saved_at"]),
                ))
            else:
                obj.owner = payload.get("owner")
                obj.payload = data
                obj.saved_at = float(payload["saved_at"])
    except Exception:
        # 저장 실패는 non-fatal(답변 흐름 유지) — 다만 이후 resolve 가 404 날 수 있음
        _logger.warning("save_pending_approval failed (approval_id=%s)", approval_id, exc_info=True)


def get_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    """읽기 전용 — write lock 없이 만료 판정(만료분은 다음 save 의 bulk purge 가 정리)."""
    try:
        with get_session() as sess:
            obj = sess.get(ChatPendingApproval, approval_id)
            if obj is None or _is_expired(obj.saved_at):
                return None
            return _decode(obj.payload)
    except Exception:
        _logger.warning("get_pending_approval failed (approval_id=%s)", approval_id, exc_info=True)
        return None


def pop_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    """원자적 read+delete (단일 승자). 동시 resolve(double-fire) 시 한쪽만 payload 획득.

    SELECT payload → DELETE → rowcount==1 인 트랜잭션만 승자(나머지 0행 → None).
    RETURNING 미사용으로 구버전 SQLite 호환.
    """
    try:
        with get_session() as sess:
            obj = sess.get(ChatPendingApproval, approval_id)
            if obj is None:
                return None
            expired = _is_expired(obj.saved_at)
            payload = obj.payload
            res = sess.execute(
                text("DELETE FROM chat_pending_approvals WHERE approval_id = :id"),
                {"id": approval_id},
            )
            if expired or (getattr(res, "rowcount", 0) or 0) < 1:
                return None  # 만료됐거나 다른 호출이 이미 소비
            return _decode(payload)
    except Exception:
        _logger.warning("pop_pending_approval failed (approval_id=%s)", approval_id, exc_info=True)
        return None


def mark_pending_approval_resolved(
    approval_id: str, decision: str, comment: str = "",
) -> Optional[Dict[str, Any]]:
    """승인 결정 기록(payload 갱신). 현재 호출처 없음 — API 호환 유지용."""
    try:
        with get_session() as sess:
            obj = sess.get(ChatPendingApproval, approval_id)
            if obj is None or _is_expired(obj.saved_at):
                return None
            data = _decode(obj.payload) or {}
            data["decision"] = str(decision or "").strip().lower()
            data["comment"] = str(comment or "")
            data["resolved_at"] = time.time()
            obj.payload = json.dumps(data, ensure_ascii=False, default=str)
            return data
    except Exception:
        _logger.warning("mark_pending_approval_resolved failed (approval_id=%s)", approval_id, exc_info=True)
        return None
