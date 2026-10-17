"""SQLAlchemy ORM models for RAG Knowledge Base."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _vector_column():
    """KB_STORAGE에 따라 vector 컬럼 타입 반환."""
    storage = os.environ.get("KB_STORAGE", "sqlite").strip().lower()
    force_pg = os.environ.get("FORCE_PGVECTOR", "0").strip().lower() in ("1", "true", "yes")
    if storage == "pgvector" or force_pg:
        try:
            from pgvector.sqlalchemy import Vector  # type: ignore
            return mapped_column(Vector(768), nullable=True)
        except ImportError:
            pass
    # SQLite: JSON text로 저장
    return mapped_column(Text, nullable=True, default="[]")


class KbEntry(Base):
    """RAG KB 엔트리 모델. 기존 kb_entries 테이블과 호환."""
    __tablename__ = "kb_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    error_raw: Mapped[Optional[str]] = mapped_column(Text, default="")
    error_clean: Mapped[Optional[str]] = mapped_column(Text, default="")
    fix: Mapped[Optional[str]] = mapped_column(Text, default="")
    tags: Mapped[Optional[str]] = mapped_column(Text, default="[]")  # JSON string for SQLite, JSONB is Phase 3
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), default="general")
    context: Mapped[Optional[str]] = mapped_column(Text, default="")
    vector: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="[]")  # JSON for now, Phase 3 switches to VECTOR(768)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    apply_count: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[Optional[str]] = mapped_column(String(50), default="")
    source_file: Mapped[Optional[str]] = mapped_column(Text, default="")
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    project_root: Mapped[Optional[str]] = mapped_column(Text, default="")
    metadata_: Mapped[Optional[str]] = mapped_column("metadata", Text, default="{}")  # JSON string

    # FTS용 컬럼 (Phase 4에서 활성화)
    # fts_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 관계
    source_relations = relationship("DocRelation", foreign_keys="DocRelation.source_id", back_populates="source_entry", lazy="select")
    target_relations = relationship("DocRelation", foreign_keys="DocRelation.target_id", back_populates="target_entry", lazy="select")

    def to_dict(self) -> Dict[str, Any]:
        """기존 dict 형식으로 변환 (하위 호환)."""
        import json
        tags: list = []
        try:
            tags = json.loads(self.tags or "[]")
        except Exception:
            tags = []
        vector: list = []
        try:
            vector = json.loads(self.vector or "[]")
        except Exception:
            vector = []
        metadata: dict = {}
        try:
            metadata = json.loads(self.metadata_ or "{}")
        except Exception:
            metadata = {}
        return {
            "id": self.id,
            "error_raw": self.error_raw or "",
            "error_clean": self.error_clean or "",
            "fix": self.fix or "",
            "tags": tags if isinstance(tags, list) else [],
            "role": self.role,
            "stage": self.stage,
            "category": self.category or "general",
            "context": self.context or "",
            "vector": vector if isinstance(vector, list) else [],
            "weight": float(self.weight or 1.0),
            "apply_count": int(self.apply_count or 0),
            "timestamp": self.timestamp or "",
            "source_file": self.source_file or "",
            "error_count": int(self.error_count or 0),
            "project_root": self.project_root or "",
            "metadata": metadata if isinstance(metadata, dict) else {},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KbEntry":
        """기존 dict에서 ORM 인스턴스 생성."""
        import json
        tags = d.get("tags") or []
        if isinstance(tags, list):
            tags_str = json.dumps(tags, ensure_ascii=False)
        else:
            tags_str = str(tags)
        vector = d.get("vector") or []
        if isinstance(vector, list):
            vector_str = json.dumps(vector, ensure_ascii=False)
        else:
            vector_str = str(vector)
        metadata = d.get("metadata") or {}
        if isinstance(metadata, dict):
            metadata_str = json.dumps(metadata, ensure_ascii=False)
        else:
            metadata_str = str(metadata)
        return cls(
            id=d.get("id", ""),
            error_raw=d.get("error_raw", ""),
            error_clean=d.get("error_clean", ""),
            fix=d.get("fix", ""),
            tags=tags_str,
            role=d.get("role"),
            stage=d.get("stage"),
            category=d.get("category", "general"),
            context=d.get("context", ""),
            vector=vector_str,
            weight=float(d.get("weight", 1.0)),
            apply_count=int(d.get("apply_count", 0)),
            timestamp=d.get("timestamp", ""),
            source_file=d.get("source_file", ""),
            error_count=int(d.get("error_count", 0)),
            project_root=d.get("project_root", ""),
            metadata_=metadata_str,
        )


class DocRelation(Base):
    """문서 추적성 관계 (SRS->SDS->UDS)."""
    __tablename__ = "doc_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("kb_entries.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(String, ForeignKey("kb_entries.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "srs_to_sds", "sds_to_uds", "implements", "traces_to"
    req_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 추적성 요구사항 ID (SRS-001 등)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # 자동 추적 신뢰도
    created_at: Mapped[Optional[str]] = mapped_column(String(50), default="")

    source_entry = relationship("KbEntry", foreign_keys=[source_id], back_populates="source_relations")
    target_entry = relationship("KbEntry", foreign_keys=[target_id], back_populates="target_relations")

    __table_args__ = (
        Index("ix_doc_rel_source", "source_id"),
        Index("ix_doc_rel_target", "target_id"),
        Index("ix_doc_rel_type", "relation_type"),
        Index("ix_doc_rel_req", "req_id"),
    )
