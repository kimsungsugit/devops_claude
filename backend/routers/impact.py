"""Auto-generated router: impact"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List
import json
import re
import traceback
import logging
import uuid
from pathlib import Path
from datetime import datetime

from backend.schemas import (
    ImpactAnalyzeRequest,
    ImpactAiGuideRequest,
    ImpactExplainChangeRequest,
)

repo_root = Path(__file__).resolve().parents[2]

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.post("/api/impact/analyze")
def impact_analyze(req: ImpactAnalyzeRequest) -> Dict[str, Any]:
    raw_source = str(req.source_root or "").strip()
    # resolver 인식 검증 — cloudium 원격 경로는 로컬 resolve/exists로 못 잡으므로 worker로 확인.
    from backend.services.file_resolver import get_resolver
    _res = get_resolver()
    if getattr(_res, "mode", "local") != "local":
        try:
            _ok = bool(raw_source) and _res.is_dir(raw_source)
        except Exception:
            _ok = False   # worker 미기동/권한거부 → 접근불가(500 누출 방지 → 400)
        if not _ok:
            raise HTTPException(status_code=400, detail="source_root not found or not directory")
        source_root_str = raw_source
    else:
        _sr = Path(raw_source).expanduser().resolve()
        if not _sr.exists() or not _sr.is_dir():
            raise HTTPException(status_code=400, detail="source_root not found or not directory")
        source_root_str = str(_sr)
    changed_rows = [str(x).strip() for x in (req.changed_files or []) if str(x).strip()]
    if not changed_rows and str(req.changed_raw or "").strip():
        changed_rows = [x.strip() for x in re.split(r"[\n,;]+", str(req.changed_raw)) if x.strip()]
    if not changed_rows:
        raise HTTPException(status_code=400, detail="changed_files or changed_raw required")
    # in-process 호출 — subprocess는 worker IPC/ContextVar를 상속하지 않아 cloudium에서 동작 불가.
    # (local 모드도 동일 동작 + 서브프로세스 오버헤드 제거.) 소스 read는 Phase1로 resolver 경유.
    try:
        from tools.impact_analysis import analyze as _impact_analyze
        data = _impact_analyze(source_root_str, changed_rows)
    except Exception as exc:
        _logger.exception("impact analyze failed")
        raise HTTPException(status_code=500, detail=f"impact analyze failed: {exc}")
    out_dir = repo_root / "reports" / "uds"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"impact_analysis_api_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.md"
    out_json = out_md.with_suffix(".json")
    try:
        out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _md = [
            "# UDS Impact Analysis Report",
            "",
            f"- Source root: `{source_root_str}`",
            f"- Changed files: `{len(changed_rows)}`",
            f"- Seed functions: `{data.get('seed_function_count', 0)}`",
            f"- Impacted functions: `{data.get('impacted_function_count', 0)}`",
            "",
            "## Impacted SwCom",
        ]
        _sw = data.get("impacted_swcom") or []
        _md += ([f"- {x}" for x in _sw] if _sw else ["- none"])
        _md += ["", f"- JSON: `{out_json}`"]
        out_md.write_text("\n".join(_md), encoding="utf-8")
    except Exception as exc:
        _logger.warning("impact report write failed: %s", exc)
    # AI guide enrichment (optional)
    ai_guide_data = None
    if req.include_ai_guide:
        try:
            from workflow.impact_ai_guide import (
                generate_impact_guide, ImpactGuideContext,
            )
            # analyze()는 변경 '유형' 분류/by_name을 산출하지 않으므로 이전엔 빈 컨텍스트로
            # 위험이 항상 LOW로 위장됐다. 영향 집합(impacted_functions)을 direct로 매핑해
            # scope 기반 평가가 동작하게 하고, ASIL 미상은 assess_risk가 명시한다(QM 단정 금지).
            _impacted = list(data.get("impacted_functions") or [])
            ctx = ImpactGuideContext(
                changed_types={},
                impact_groups={"direct": _impacted},
                by_name={},
            )
            guide = generate_impact_guide(ctx)
            ai_guide_data = guide.to_dict()
        except Exception as e:
            _logger.debug("AI guide generation failed: %s", e)

    # cloudium에서 0 영향 + 변경파일 있음 → worker read 실패 가능성(과소보고) 명시.
    _warns: List[str] = []
    if getattr(_res, "mode", "local") != "local" and not (data.get("impacted_function_count") or 0):
        _warns.append("cloudium: 0 impacted functions — source read may have failed; result may be under-reported")
    return {
        "ok": True,
        "result": data,
        "report_path": str(out_md),
        "json_path": str(out_json),
        "ai_guide": ai_guide_data,
        "warnings": _warns,
    }


@router.post("/api/impact/ai-guide")
def impact_ai_guide(req: ImpactAiGuideRequest) -> Dict[str, Any]:
    """Generate AI risk assessment and cross-document impact guide."""
    try:
        from workflow.impact_ai_guide import (
            generate_impact_guide, ImpactGuideContext,
        )
        ctx = ImpactGuideContext(
            changed_types=req.changed_types or {},
            impact_groups=req.impact_groups or {},
            by_name=req.by_name or {},
        )
        guide = generate_impact_guide(ctx)
        return {"ok": True, "guide": guide.to_dict()}
    except Exception:
        # 내부 예외 문자열을 응답으로 노출하지 않는다(정보 누출) — 상세는 서버 로그로만.
        _logger.exception("ai-guide failed")
        return {"ok": False, "error": "ai-guide generation failed"}


@router.post("/api/impact/explain-change")
def impact_explain_change(req: ImpactExplainChangeRequest) -> Dict[str, Any]:
    """단일 함수 변경의 자연어 설명(Gemini). LLM 미설정/실패 시 ok=False로 정직 반환
    (프론트는 결정론 매개변수 diff로 폴백). 예외 문자열은 응답에 노출하지 않는다."""
    try:
        from workflow.impact_ai_guide import explain_function_change
        explanation = explain_function_change(
            function=req.function,
            change_type=req.change_type,
            before=req.before,
            after=req.after,
            asil=req.asil,
            module=req.module,
            requirements=req.requirements,
        )
        if explanation:
            return {"ok": True, "explanation": explanation}
        return {"ok": False, "error": "LLM 미설정 또는 응답 없음"}
    except Exception:
        _logger.exception("explain-change failed")
        return {"ok": False, "error": "explain-change failed"}


