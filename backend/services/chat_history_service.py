"""Chat history persistence — save / load / list / delete conversations."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from backend.services.chat_history_db import get_session
from backend.services.chat_history_models import ChatConversation, ChatMessage

_logger = logging.getLogger("backend.chat_history")


def _auto_title(question: str) -> str:
    """첫 질문에서 대화 제목 자동 생성 (최대 80자)."""
    title = question.strip().replace("\n", " ")
    return title[:80] if len(title) > 80 else title


def _max_turns() -> int:
    try:
        import config
        return int(getattr(config, "CHAT_MAX_TURNS", 16) or 16)
    except Exception:
        return 16


def _owner_allows(conv_owner: Optional[str], requester: Optional[str]) -> bool:
    """소유권 검증. requester 미지정(내부 호출) 또는 레거시(owner None)는 허용, 그 외 일치 요구."""
    if not requester:
        return True
    if not conv_owner:
        return True
    return conv_owner == requester


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
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    """user 질문 + assistant 응답을 한 쌍으로 저장. 대화가 없으면 자동 생성."""
    last_exc: Optional[Exception] = None
    for _attempt in range(3):
        try:
            with get_session() as sess:
                conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
                # W2: 기존 대화에 타 사용자가 메시지를 주입하지 못하도록 소유권 검증
                if conv is not None and not _owner_allows(conv.owner, owner):
                    return {"thread_id": thread_id, "saved": 0, "error": "forbidden"}
                if conv is None:
                    conv = ChatConversation(
                        thread_id=thread_id,
                        session_id=session_id,
                        mode=mode,
                        report_dir=report_dir,
                        title=_auto_title(question),
                        owner=owner,
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
        except IntegrityError as exc:
            # D1/D2: thread_id 동시 생성 또는 (conversation_id, seq) 충돌 — 재조회로 재시도
            last_exc = exc
            continue
    _logger.error("save_message_pair conflict after retries (thread_id=%s): %s", thread_id, last_exc)
    return {"thread_id": thread_id, "saved": 0, "error": "conflict"}


# ── Load ─────────────────────────────────────────────────────────────

def load_history(
    thread_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    requester: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """thread_id로 대화 이력 조회. 없거나 소유자가 다르면 None."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None or not _owner_allows(conv.owner, requester):
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
    last_n: Optional[int] = None,
    requester: Optional[str] = None,
) -> List[Dict[str, str]]:
    """LLM 컨텍스트용: 최근 N개 메시지를 [{role, text}] 형태로 반환."""
    with get_session() as sess:
        last_n = last_n or _max_turns()
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None or not _owner_allows(conv.owner, requester):
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
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    """대화 목록 조회. owner(소유자)/session_id 로 필터. 레거시(owner None)는 함께 노출."""
    with get_session() as sess:
        q = sess.query(ChatConversation)
        count_q = sess.query(func.count(ChatConversation.id))
        if owner:
            owner_filter = (ChatConversation.owner == owner) | (ChatConversation.owner.is_(None))
            q = q.filter(owner_filter)
            count_q = count_q.filter(owner_filter)
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

        # message_count 를 단일 group-by 쿼리로 (N+1 제거)
        conv_ids = [c.id for c in convs]
        counts: Dict[int, int] = {}
        if conv_ids:
            rows = (
                sess.query(ChatMessage.conversation_id, func.count(ChatMessage.id))
                .filter(ChatMessage.conversation_id.in_(conv_ids))
                .group_by(ChatMessage.conversation_id)
                .all()
            )
            counts = {int(cid): int(cnt) for cid, cnt in rows}

        items = []
        for c in convs:
            items.append({
                "thread_id": c.thread_id,
                "session_id": c.session_id,
                "mode": c.mode,
                "title": c.title,
                "message_count": counts.get(c.id, 0),
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            })

        return {"total": total, "conversations": items}


# ── Delete ───────────────────────────────────────────────────────────

def delete_conversation(thread_id: str, *, requester: Optional[str] = None) -> bool:
    """대화 삭제 (CASCADE로 메시지도 삭제). 없거나 소유자가 다르면 False."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None or not _owner_allows(conv.owner, requester):
            return False
        sess.delete(conv)
    return True


def update_title(thread_id: str, title: str, *, requester: Optional[str] = None) -> bool:
    """대화 제목 변경. 없거나 소유자가 다르면 False."""
    with get_session() as sess:
        conv = sess.query(ChatConversation).filter_by(thread_id=thread_id).first()
        if conv is None or not _owner_allows(conv.owner, requester):
            return False
        conv.title = title[:200]
    return True
