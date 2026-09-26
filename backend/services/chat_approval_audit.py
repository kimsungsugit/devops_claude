"""승인 게이트 감사 로그 (append-only, SQLite 영속 — ISO 26262).

승인 요청 생성/승인/거절/만료를 불변 로그로 기록한다. in-memory 승인 store
(chat_approval_store)와 별개로, 멀티워커/재시작과 무관하게 감사 추적을 보존한다.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import func

from backend.services.chat_history_db import get_session
from backend.services.chat_history_models import ChatApprovalAudit

_logger = logging.getLogger("backend.chat_approval_audit")


def record_audit(
    *,
    approval_id: str,
    status: str,
    owner: Optional[str] = None,
    action_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    tool_name: Optional[str] = None,
    question: Optional[str] = None,
    comment: Optional[str] = None,
) -> None:
    """감사 이벤트 1건 기록 (append-only). 실패는 non-fatal(승인 흐름을 막지 않음)."""
    try:
        with get_session() as sess:
            sess.add(ChatApprovalAudit(
                approval_id=str(approval_id or ""),
                owner=owner,
                action_type=action_type,
                risk_level=risk_level,
                tool_name=tool_name,
                question_preview=(str(question)[:300] if question else None),
                status=status,
                comment=comment,
            ))
    except Exception:
        _logger.warning("approval audit record failed (status=%s)", status, exc_info=True)


def list_audit(*, owner: Optional[str] = None, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """감사 로그 조회 (최신순). owner 로 필터 가능(미지정 시 전체 — admin 전용 엔드포인트에서 호출).

    조회 실패는 빈 결과로 fallback (admin UI 에 500 전파 방지).
    """
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))
    try:
        with get_session() as sess:
            q = sess.query(ChatApprovalAudit)
            count_q = sess.query(func.count(ChatApprovalAudit.id))
            if owner:
                q = q.filter(ChatApprovalAudit.owner == owner)
                count_q = count_q.filter(ChatApprovalAudit.owner == owner)
            total = count_q.scalar()
            rows = (
                q.order_by(ChatApprovalAudit.created_at.desc(), ChatApprovalAudit.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            items = [
                {
                    "approval_id": r.approval_id,
                    "owner": r.owner,
                    "action_type": r.action_type,
                    "risk_level": r.risk_level,
                    "tool_name": r.tool_name,
                    "question_preview": r.question_preview,
                    "status": r.status,
                    "comment": r.comment,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
            return {"total": total or 0, "items": items}
    except Exception:
        _logger.warning("approval audit list failed", exc_info=True)
        return {"total": 0, "items": []}
