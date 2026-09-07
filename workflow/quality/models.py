"""SQLAlchemy ORM models for Quality DB."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
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


class QualityBase(DeclarativeBase):
    pass


class GenerationRun(QualityBase):
    __tablename__ = "generation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(10), nullable=False)  # uds/sts/suts
    # ⚠ `project_root` 는 **어휘가 doc_type 마다 다르다**(실측 964행, 2026-08-07):
    #   swut/swit/swreport/swsa → `req.project_id`  ("HDPDM01")
    #   sts/suts/sits           → `source_root`      ("D:/Project/Ados/PDS64_RD", 콤마 복수도)
    #   uds                     → **전부 NULL**      (호출 5곳이 인자를 안 넘겼다)
    # 그래서 이 컬럼으로는 "프로젝트별" 조회가 성립하지 않는다. `scm_id` 가 그 축이고
    # 여기는 **원본 증거로 그대로 보존**한다 — 지우면 백필 결과를 되짚을 수 없다.
    project_root: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # SCM registry(`config/scm_registry.json`)의 entry id — 프로젝트 축 **정본**.
    # NULL 은 "미상"이지 "무소속"이 아니다. 백필이 근거 없이 채우지 않은 행이 여기 남는다
    # (`scripts/backfill_quality_scm_id.py` — 정확일치만 매핑, 부분일치·단일후보 폴백 금지).
    scm_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_function: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )
    elapsed_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # (R33 C-1) 산출물 **바이트**의 SHA-256(hex 64). 검토 기록(R34~)이 "어느 바이트에 대한
    # 판정인가" 를 여기에 고정한다. 실측(2026-09-07): `output_path` 가 있는 43 run 중 18 run 은
    # 기록된 `output_size_bytes` 와 지금 그 경로의 파일 크기가 **다르다**(`SITS_gate.xlsm` 한
    # 경로를 21 run 이 돌려썼다) — 경로는 run 을 식별하지 못한다. NULL = 해시 미기록(구 run,
    # 파일 부재, BytesIO 응답이라 경로가 없는 run) 이지 "빈 산출물" 이 아니다.
    # ⚠ 컬럼 추가는 `db.py::_COLUMN_ADDITIONS` 한 줄과 한 세트다.
    output_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ai_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON

    scores: Mapped[List["QualityScore"]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
    )
    summary: Mapped[Optional["QualitySummary"]] = relationship(
        back_populates="run", uselist=False, cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_gen_run_doc_type", "doc_type"),
        Index("ix_gen_run_created", "created_at"),
        Index("ix_gen_run_project", "project_root"),
        Index("ix_gen_run_scm", "scm_id"),
    )


class QualityScore(QualityBase):
    __tablename__ = "quality_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generation_runs.id"), nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    gate_pass: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped["GenerationRun"] = relationship(back_populates="scores")

    __table_args__ = (
        Index("ix_qs_run_id", "run_id"),
        Index("ix_qs_metric", "metric_name"),
    )


class QualitySummary(QualityBase):
    __tablename__ = "quality_summaries"

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generation_runs.id"), primary_key=True,
    )
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    gate_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    score_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prev_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fn_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    run: Mapped["GenerationRun"] = relationship(back_populates="summary")


# ── 검토 기록 (R34, 계획 C-2) ──────────────────────────────────────────────
# 사람이 run 하나에 남기는 판정(approved / rejected / needs_work)과 그 감사 이력.
# 게이트화하지 않는다 — 검토 결과로 FAIL 을 만들지 않고, 사이드카 `.md` 에도 한 글자도 쓰지 않는다(S1).
# 판정 대상은 **run 이 아니라 그 run 의 산출물 바이트**다: `output_sha256` 스냅샷(NOT NULL)이 없으면 기록할
# 수 없다(S5·S6 — 해시 없는 run 은 `hash_unavailable` 로 검토 잠금).
class ReviewRecord(QualityBase):
    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("generation_runs.id"), nullable=False)
    # 검토 시점의 산출물 해시 스냅샷. run 의 값이 나중에 바뀌어도(재기록) 이 값은 남는다 → 조회 시 `stale`.
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(120), nullable=False)
    # 어떤 인증으로 남겼나 — 쓰기는 JWT 만 받으므로 지금은 항상 'jwt'(S4). 기록해 두는 이유: 뒷날 다른
    # 경로가 열리면 그 행이 구분되어야 한다.
    auth_method: Mapped[str] = mapped_column(String(16), nullable=False, default="jwt")
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # approved|rejected|needs_work
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 낙관적 잠금(S9) — 갱신은 현재 version 을 같이 보내야 하고, 다르면 409 VERSION_CONFLICT.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )

    __table_args__ = (
        # 한 검토자는 run 당 기록 하나 — 갱신은 version 으로(S9). 두 번째 INSERT 는 IntegrityError.
        UniqueConstraint("run_id", "reviewer", name="uq_review_run_reviewer"),
        Index("ix_review_run", "run_id"),
        Index("ix_review_reviewer", "reviewer"),
    )


class ReviewAudit(QualityBase):
    __tablename__ = "review_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(Integer, ForeignKey("review_records.id"), nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("generation_runs.id"), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # create|update
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )

    __table_args__ = (
        Index("ix_review_audit_run", "run_id"),
        Index("ix_review_audit_created", "created_at"),
    )
