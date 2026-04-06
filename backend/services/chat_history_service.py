"""Chat history persistence — save / load / list / delete conversations."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from backend.services.chat_history_db import get_session
from backend.services.chat_history_models import ChatConversation, ChatMessage

_logger = logging.getLogger("backend.chat_history")


def _auto_title(question: str) -> str:
    """첫 질문에서 대화 제목 자동 생성 (최대 80자)."""
    title = question.strip().replace("\n", " ")
    return title[:80] if len(title) > 80 else title


# ── Save ─────────────────────────────────────────────────────────────

def save_message_pair(
    *,
    thread_id: str,
    session_id: Optional[str],
    mode: str,
    report_dir: Optional[str],
    question: str,
    answer: str,
    request_id: str = "",
    llm_model: str = "",
) -> Dict[str, Any]:
    """user 질문 + assistant 응답을 한 쌍으로 저장. 대화가 없으면 자동 생성."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None:
            conv = ChatConversation(
                thread_id=thread_id,
                session_id=session_id,
                mode=mode,
                report_dir=report_dir,
                title=_auto_title(question),
            )
            sess.add(conv)
            sess.flush()

        conv.updated_at = datetime.now(timezone.utc)

        max_seq = (
            sess.query(func.coalesce(func.max(ChatMessage.seq), 0))
            .filter_by(conversation_id=conv.id)
            .scalar()
        )

        user_msg = ChatMessage(
            conversation_id=conv.id,
            seq=max_seq + 1,
            role="user",
            text=question,
            request_id=request_id,
        )
        assistant_msg = ChatMessage(
            conversation_id=conv.id,
            seq=max_seq + 2,
            role="assistant",
            text=answer,
            request_id=request_id,
            llm_model=llm_model or None,
        )
        sess.add_all([user_msg, assistant_msg])

    return {"thread_id": thread_id, "saved": 2}


# ── Load ─────────────────────────────────────────────────────────────

def load_history(
    thread_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Optional[Dict[str, Any]]:
    """thread_id로 대화 이력 조회. 없으면 None."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None:
            return None

        total = sess.query(func.count(ChatMessage.id)).filter_by(
            conversation_id=conv.id
        ).scalar()

        msgs = (
            sess.query(ChatMessage)
            .filter_by(conversation_id=conv.id)
            .order_by(ChatMessage.seq)
            .offset(offset)
            .limit(limit)
            .all()
        )

        return {
            "thread_id": conv.thread_id,
            "session_id": conv.session_id,
            "mode": conv.mode,
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "total_messages": total,
            "messages": [
                {
                    "seq": m.seq,
                    "role": m.role,
                    "text": m.text,
                    "request_id": m.request_id,
                    "llm_model": m.llm_model,
                    "created_at": m.created_at.isoformat(),
                }
                for m in msgs
            ],
        }


def load_history_as_chat_items(
    thread_id: str,
    *,
    last_n: int = 16,
) -> List[Dict[str, str]]:
    """LLM 컨텍스트용: 최근 N개 메시지를 [{role, text}] 형태로 반환."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None:
            return []

        msgs = (
            sess.query(ChatMessage)
            .filter_by(conversation_id=conv.id)
            .order_by(ChatMessage.seq.desc())
            .limit(last_n)
            .all()
        )
        msgs.reverse()
        return [{"role": m.role, "text": m.text} for m in msgs]


# ── List ─────────────────────────────────────────────────────────────

def list_conversations(
    *,
    session_id: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> Dict[str, Any]:
    """대화 목록 조회. session_id로 필터 가능."""
    with get_session() as sess:
        q = sess.query(ChatConversation)
        count_q = sess.query(func.count(ChatConversation.id))
        if session_id:
            q = q.filter_by(session_id=session_id)
            count_q = count_q.filter(ChatConversation.session_id == session_id)

        total = count_q.scalar()
        convs = (
            q.order_by(ChatConversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = []
        for c in convs:
            msg_count = sess.query(func.count(ChatMessage.id)).filter_by(
                conversation_id=c.id
            ).scalar()
            items.append({
                "thread_id": c.thread_id,
                "session_id": c.session_id,
                "mode": c.mode,
                "title": c.title,
                "message_count": msg_count,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            })

        return {"total": total, "conversations": items}


# ── Delete ───────────────────────────────────────────────────────────

def delete_conversation(thread_id: str) -> bool:
    """대화 삭제 (CASCADE로 메시지도 삭제). 성공 시 True."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None:
            return False
        sess.delete(conv)
    return True


def update_title(thread_id: str, title: str) -> bool:
    """대화 제목 변경."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None:
            return False
        conv.title = title[:200]
    return True
