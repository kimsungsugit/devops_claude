"""SQLAlchemy ORM models for Chat History DB."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import List, Optional


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
        Index("ix_msg_conv_seq", "conversation_id", "seq"),
    )
