"""Quality history API -- view generation runs and quality scores."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

_logger = logging.getLogger("devops_api.quality")

router = APIRouter(prefix="/api/quality", tags=["quality"])


def _run_to_dict(run, *, include_scores: bool = False) -> Dict[str, Any]:
    """GenerationRun ORM → API 응답 dict."""
    d: Dict[str, Any] = {
        "id": run.id,
        "run_uuid": run.run_uuid,
        "doc_type": run.doc_type,
        "project_root": run.project_root,
        "target_function": run.target_function,
        "status": run.status,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "elapsed_sec": run.elapsed_sec,
        "output_path": run.output_path,
        "output_size_bytes": run.output_size_bytes,
        "ai_model": run.ai_model,
    }
    if run.summary:
        d["summary"] = {
            "overall_score": run.summary.overall_score,
            "gate_pass": run.summary.gate_pass,
            "score_delta": run.summary.score_delta,
            "prev_run_id": run.summary.prev_run_id,
            "fn_count": run.summary.fn_count,
        }
    else:
        d["summary"] = None

    if include_scores:
        d["scores"] = [
            {
                "metric_name": s.metric_name,
                "value": s.value,
                "gate_pass": s.gate_pass,
                "threshold": s.threshold,
            }
            for s in (run.scores or [])
        ]
    return d


@router.get("/runs")
def list_runs(
    doc_type: Optional[str] = Query(None, description="uds|sts|suts"),
    project_root: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """생성 이력 목록 (summary 포함)."""
    try:
        from workflow.quality.db import init_db, get_session
        from workflow.quality.models import GenerationRun
    except ImportError:
        return {"runs": [], "total": 0, "error": "quality module not available"}

    init_db()

    with get_session() as session:
        q = session.query(GenerationRun)
        if doc_type:
            q = q.filter(GenerationRun.doc_type == doc_type.lower().strip())
        if project_root:
            q = q.filter(GenerationRun.project_root == project_root)
        total = q.count()
        runs = q.order_by(GenerationRun.created_at.desc()).offset(offset).limit(limit).all()
        return {
            "runs": [_run_to_dict(r) for r in runs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.get("/runs/{run_id}")
def get_run(run_id: int) -> Dict[str, Any]:
    """단일 실행 상세 (scores 포함)."""
    try:
        from workflow.quality.db import init_db, get_session
        from workflow.quality.models import GenerationRun
    except ImportError:
        return {"error": "quality module not available"}

    init_db()

    with get_session() as session:
        run = session.query(GenerationRun).filter_by(id=run_id).first()
        if not run:
            return {"error": f"run_id {run_id} not found"}
        return _run_to_dict(run, include_scores=True)


@router.get("/trend")
def get_trend(
    doc_type: str = Query("uds", description="uds|sts|suts"),
    project_root: Optional[str] = Query(None),
    target_function: Optional[str] = Query(None),
    last_n: int = Query(20, le=100),
) -> Dict[str, Any]:
    """시계열 점수 추이."""
    try:
        from workflow.quality.db import init_db, get_session
        from workflow.quality.models import GenerationRun, QualitySummary
    except ImportError:
        return {"trend": [], "error": "quality module not available"}

    init_db()

    with get_session() as session:
        q = (
            session.query(GenerationRun)
            .join(QualitySummary)
            .filter(GenerationRun.doc_type == doc_type.lower().strip())
        )
        if project_root:
            q = q.filter(GenerationRun.project_root == project_root)
        if target_function:
            q = q.filter(GenerationRun.target_function == target_function)

        runs = q.order_by(GenerationRun.created_at.desc()).limit(last_n).all()
        runs.reverse()  # oldest first for trend

        return {
            "doc_type": doc_type,
            "trend": [
                {
                    "run_id": r.id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "overall_score": r.summary.overall_score if r.summary else None,
                    "gate_pass": r.summary.gate_pass if r.summary else None,
                    "score_delta": r.summary.score_delta if r.summary else None,
                }
                for r in runs
            ],
        }


@router.post("/runs/{run_id}/advice")
def get_advice(run_id: int) -> Dict[str, Any]:
    """품질 개선 제안 생성."""
    try:
        from workflow.quality.advisor import suggest_improvements
        return suggest_improvements(run_id)
    except ImportError:
        return {"error": "advisor module not available"}
