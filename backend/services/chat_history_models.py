"""SQLAlchemy ORM models for Chat History DB."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ChatHistoryBase(DeclarativeBase):
    pass


class ChatConversation(ChatHistoryBase):
    """대화 세션 (thread) 단위."""
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="local")
    report_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    messages: Mapped[List["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )

    __table_args__ = (
        Index("ix_conv_session", "session_id"),
        Index("ix_conv_updated", "updated_at"),
    )


class ChatMessage(ChatHistoryBase):
    """개별 메시지."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    text: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )

    conversation: Mapped["ChatConversation"] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_msg_conv_seq"),
        Index("ix_msg_conv_seq", "conversation_id", "seq"),
    )


class ChatApprovalAudit(ChatHistoryBase):
    """승인 게이트 감사 로그 (append-only — ISO 26262). 이벤트 1건당 1행."""
    __tablename__ = "chat_approval_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    action_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    question_preview: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # created|approved|rejected|expired
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_audit_approval", "approval_id"),
        Index("ix_audit_created", "created_at"),
    )


class ChatPendingApproval(ChatHistoryBase):
    """미해소 승인 요청 (영속 — 멀티워커 공유). payload 는 전체 record JSON.

    in-memory 대비: WEB_CONCURRENCY>1 에서 생성/해소가 다른 워커로 라우팅돼도
    동일 SQLite 를 공유하므로 404 가 나지 않는다. saved_at(epoch) 으로 TTL 만료.
    """
    __tablename__ = "chat_pending_approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # 전체 record JSON
    saved_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)

    __table_args__ = (
        Index("ix_pending_saved", "saved_at"),
    )
