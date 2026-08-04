"""Quality history API -- view generation runs and quality scores."""
from __future__ import annotations

import logging
from datetime import timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies.admin import require_admin

_logger = logging.getLogger("devops_api.quality")

# 형제 evidence 라우터(swsa/swut/swit/swreport)와 동일하게 라우터 전체 admin only.
# 프론트 Quality 탭의 adminOnly 는 클라이언트 토글일 뿐이라 backend 게이트가 유일 방어선.
router = APIRouter(
    prefix="/api/quality",
    tags=["quality"],
    dependencies=[Depends(require_admin)],
)


def _run_to_dict(run, *, include_scores: bool = False) -> Dict[str, Any]:
    """GenerationRun ORM → API 응답 dict."""
    d: Dict[str, Any] = {
        "id": run.id,
        "run_uuid": run.run_uuid,
        "doc_type": run.doc_type,
        "project_root": run.project_root,
        "target_function": run.target_function,
        "status": run.status,
        # 저장은 tz-naive UTC(datetime.now(utc)) → 응답에 UTC offset 명시.
        # (naive isoformat 은 'Z' 없어 JS가 로컬해석 → KST 등에서 날짜 하루 밀림)
        "created_at": (
            run.created_at.replace(tzinfo=timezone.utc).isoformat()
            if run.created_at else None
        ),
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """생성 이력 목록 (summary 포함)."""
    try:
        from workflow.quality.db import get_session, init_db
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
        # created_at 동률 시 id 2차키로 결정적 정렬 (동시/근접 타임스탬프 역전 방지)
        runs = (
            q.order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "runs": [_run_to_dict(r) for r in runs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.get("/runs/{run_id}")
def get_run(run_id: int) -> Dict[str, Any]:
    """단일 실행 상세 (scores 포함).

    ⚠ 미존재 run 은 **404** 다. 예전엔 `HTTP 200 + {"error": …}` 를 돌려줬는데,
    프론트 헬퍼가 `if (res.ok) return res.json()`(`api.js:145`)이라 **에러를 성공으로
    삼킨다** — 화면은 빈 상세를 "정상" 으로 그린다. 라이브 실측(2026-08-04):

        GET /api/quality/runs/999999  ->  200  {"error": "run_id 999999 not found"}

    이 endpoint 의 프론트 소비자는 그동안 0건이었으므로(§6-1 실측) 계약을 바로잡는
    지금이 유일하게 무해한 시점이다.
    """
    try:
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun
    except ImportError:
        # 모듈 부재는 클라이언트 잘못이 아니다 — 503(일시적 불가)로 구분한다.
        raise HTTPException(status_code=503, detail="quality module not available") from None

    init_db()

    with get_session() as session:
        run = session.query(GenerationRun).filter_by(id=run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")
        return _run_to_dict(run, include_scores=True)


@router.get("/trend")
def get_trend(
    doc_type: Optional[str] = Query(None, description="uds|sts|suts (생략/all = 전체)"),
    project_root: Optional[str] = Query(None),
    target_function: Optional[str] = Query(None),
    last_n: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """시계열 점수 추이. doc_type 생략 또는 'all'이면 전 doc_type 통합 추이."""
    try:
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun, QualitySummary
    except ImportError:
        return {"trend": [], "error": "quality module not available"}

    init_db()

    dt = (doc_type or "").lower().strip()
    with get_session() as session:
        q = session.query(GenerationRun).join(QualitySummary)
        # 프론트 "전체"(doc_type 생략) → 미필터. list_runs 와 동일한 전체 조회 의미.
        if dt and dt != "all":
            q = q.filter(GenerationRun.doc_type == dt)
        if project_root:
            q = q.filter(GenerationRun.project_root == project_root)
        if target_function:
            q = q.filter(GenerationRun.target_function == target_function)

        runs = (
            q.order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .limit(last_n)
            .all()
        )
        runs.reverse()  # oldest first for trend

        return {
            "doc_type": dt or "all",
            "trend": [
                {
                    "run_id": r.id,
                    "doc_type": r.doc_type,
                    "created_at": (
                        r.created_at.replace(tzinfo=timezone.utc).isoformat()
                        if r.created_at else None
                    ),
                    "overall_score": r.summary.overall_score if r.summary else None,
                    "gate_pass": r.summary.gate_pass if r.summary else None,
                    "score_delta": r.summary.score_delta if r.summary else None,
                }
                for r in runs
            ],
        }


# 게이트 임계값 12키가 읽는 env 변수 이름 — `config.py:154-167` 과 **한 세트**다.
# ⚠ 여기 리터럴로 적는 이유: `config.py` 는 `_safe_float("UDS_CALLED_MIN", 95.0)` 처럼
#   호출 인자로만 이름을 갖고 있어 런타임에 되짚을 수 없다. 대신 아래
#   `test_quality_policy_endpoint.py` 가 두 목록이 어긋나면 실패시킨다.
_GATE_ENV_NAMES = {
    "called_min": "UDS_CALLED_MIN",
    "calling_min": "UDS_CALLING_MIN",
    "input_min": "UDS_INPUT_MIN",
    "output_min": "UDS_OUTPUT_MIN",
    "global_min": "UDS_GLOBAL_MIN",
    "static_min": "UDS_STATIC_MIN",
    "description_min": "UDS_DESCRIPTION_MIN",
    "asil_min": "UDS_ASIL_MIN",
    "related_min": "UDS_RELATED_MIN",
    "description_trusted_min": "UDS_DESC_TRUSTED_MIN",
    "asil_trusted_min": "UDS_ASIL_TRUSTED_MIN",
    "related_trusted_min": "UDS_RELATED_TRUSTED_MIN",
}


@router.get("/policy")
def get_policy() -> Dict[str, Any]:
    """게이트 정책값 **읽기 전용** 노출 (§6-1 G4).

    화면이 임계값을 다시 정의하지 않게 하는 것이 목적이다. 세 표를 **라벨과 함께** 낸다:

    | 표 | 상태 | 근거 |
    |---|---|---|
    | `UDS_QUALITY_GATE_THRESHOLDS` | `applied` (조정 가능) | 12키 각각 전용 env 이름으로 덮인다 |
    | `UDS_QUALITY_WARNING_THRESHOLDS` | `defined_unused` | 판정 참조 0건 · env 훅 0개 |
    | `TEST_QUALITY_GATES_BY_ASIL` | `defined_unused` | 사용 0건 · env 훅 0개 |

    ⚠ "적용됨 / 정의만 있고 미사용" 2분법으로는 부족하다는 게 실측 결론이다 —
    적용되는 표 안에서도 **조정 가능(env)** 인지 **코드 상수**인지가 갈린다. 라벨 축을
    둘(`status`, `adjustable`) 두지 않으면 리뷰어가 "바꾸려면 어디를 고치나" 를 오독한다.

    ⚠ **실효값**을 낸다(리터럴이 아니라 지금 프로세스가 쓰는 값). override 실적은 현재
    0건이라 둘이 같지만, `.env` 는 `backend/main.py` 만 로드하고 `config.py` 는 dotenv 를
    스스로 읽지 않으므로 **스크립트와 백엔드의 실효값이 갈릴 수 있다** — 각주로 남긴다.

    판정 로직은 0개다. 값을 바꾸지도 않는다.
    """
    import os

    try:
        import config
    except ImportError:
        raise HTTPException(status_code=503, detail="config module not available") from None

    gate = dict(getattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {}) or {})
    warn = dict(getattr(config, "UDS_QUALITY_WARNING_THRESHOLDS", {}) or {})
    asil = dict(getattr(config, "TEST_QUALITY_GATES_BY_ASIL", {}) or {})

    return {
        "tables": [
            {
                "key": "UDS_QUALITY_GATE_THRESHOLDS",
                "label": "UDS 품질 게이트 임계값",
                "status": "applied",
                "status_label": "적용됨 — 판정에 쓰인다",
                "adjustable": "env",
                "adjustable_label": "키별 환경변수로 조정 가능",
                "entries": [
                    {
                        "key": k,
                        "value": v,
                        "env_name": _GATE_ENV_NAMES.get(k),
                        # 이 프로세스에서 실제로 덮였는가(리터럴과 실효값이 갈리는지 확인용)
                        "env_set": bool(os.environ.get(_GATE_ENV_NAMES.get(k) or "")),
                    }
                    for k, v in sorted(gate.items())
                ],
            },
            {
                "key": "UDS_QUALITY_WARNING_THRESHOLDS",
                "label": "UDS '주의' 밴드",
                "status": "defined_unused",
                "status_label": "정의만 있고 판정에 안 쓰인다",
                "adjustable": "code",
                "adjustable_label": "코드 상수 — env 훅 없음",
                "entries": [{"key": k, "value": v, "env_name": None, "env_set": False}
                            for k, v in sorted(warn.items())],
            },
            {
                "key": "TEST_QUALITY_GATES_BY_ASIL",
                "label": "ASIL별 시험 품질 게이트 프로파일",
                "status": "defined_unused",
                "status_label": "정의만 있고 사용처가 없다",
                "adjustable": "code",
                "adjustable_label": "코드 상수 — env 훅 없음",
                "entries": [{"key": k, "value": v, "env_name": None, "env_set": False}
                            for k, v in sorted(asil.items())],
            },
        ],
        "notes": [
            "이 화면은 정책값을 **표시만** 한다 — 여기서 바꿀 수 없고 판정도 하지 않는다.",
            "`config.py` 는 dotenv 를 스스로 읽지 않는다(`backend/main.py` 만 로드) — "
            "백엔드 프로세스와 별도 스크립트의 실효값이 갈릴 수 있다.",
            "'정의만 있고 미사용' 표를 판정에 넣을지는 정책 결정이며 아직 하지 않았다.",
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
