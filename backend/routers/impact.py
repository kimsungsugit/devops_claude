"""Auto-generated router: impact"""
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    ImpactAiGuideRequest,
    ImpactAnalyzeRequest,
    ImpactDocDraftRequest,
    ImpactDocProseRequest,
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
    except Exception:
        # 내부 예외 문자열(서버 경로·subprocess/SVN 메시지 등)을 응답으로 노출하지 않는다
        # — 형제 엔드포인트(/ai-guide, /explain-change)와 동일 정책. 상세는 서버 로그에만.
        _logger.exception("impact analyze failed")
        raise HTTPException(status_code=500, detail="영향도 분석에 실패했습니다. 서버 로그를 확인하세요.")
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
                ImpactGuideContext,
                generate_impact_guide,
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
            ImpactGuideContext,
            generate_impact_guide,
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
            function_diff=req.function_diff,
            asil=req.asil,
            module=req.module,
            requirements=req.requirements,
            doc_content=req.doc_content or None,
            impact_path=req.impact_path or None,
            no_semantic_change=req.no_semantic_change,
        )
        if explanation:
            return {"ok": True, "explanation": explanation}
        return {"ok": False, "error": "LLM 미설정 또는 응답 없음"}
    except Exception:
        _logger.exception("explain-change failed")
        return {"ok": False, "error": "explain-change failed"}


_DOC_DRAFT_KINDS = {"uds", "sds", "sts", "suts", "sits"}


@router.post("/api/impact/doc-draft")
def impact_doc_draft(req: ImpactDocDraftRequest) -> Dict[str, Any]:
    """한 함수의 **전체** 문서 초안(온디맨드) — job에는 요약만, 여기선 생성기 기본값 전량.

    job JSON에 24 시퀀스 × 50 함수를 전부 실으면 페이로드가 폭증하므로, 카드는 요약(10건)만
    받고 사용자가 '전체 보기'를 누를 때 이 엔드포인트가 나머지를 만든다.
    소스가 미해결(cloudium)이면 `_build_doc_proposal`이 문서 원문 기준으로 폴백하며,
    어느 근거로 만들었는지는 `source`('generator'|'document')로 정직하게 돌려준다.
    """
    doc = str(req.doc or "suts").strip().lower()
    if doc not in _DOC_DRAFT_KINDS:
        raise HTTPException(status_code=400, detail=f"unsupported doc: {doc}")
    fn = str(req.function or "").strip().lower()
    if not fn:
        raise HTTPException(status_code=400, detail="function is required")

    from workflow.impact_jobs import load_job
    try:
        # job_id는 _sanitize_fragment가 alnum/_/- 로 정규화하므로 traversal 불가(impact_jobs).
        job = load_job(str(req.job_id or ""))
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found") from None
    except Exception:
        _logger.exception("doc-draft: job load failed")
        raise HTTPException(status_code=500, detail="failed to read job state") from None
    if str(job.get("status") or "") == "running":
        raise HTTPException(status_code=409, detail="job is still running")

    result = job.get("result") or {}
    doc_content = result.get("doc_content") or {}
    change_details = result.get("change_details") or {}

    # 소스 경로: SCM registry 우선 — 오케스트레이터도 `entry.source_root`로 분석했기 때문이다.
    # ⚠ 다만 job 실행 이후 registry가 바뀌었으면 **분석 당시와 다른 소스**로 초안을 만들게 된다.
    #   job에는 그때의 registry 값이 기록돼 있지 않아 사후 판별이 불가능하므로, 어떤 경로를 썼는지
    #   응답(`source_root`)에 실어 사용자가 대조할 수 있게 한다(조용히 다른 소스를 쓰지 않는다).
    warnings: List[str] = []
    source_root = ""
    try:
        from backend.services.scm_registry import get_registry_entry
        _entry = get_registry_entry(str(job.get("scm_id") or ""))
        source_root = str(getattr(_entry, "source_root", "") or "")
    except Exception:
        _logger.debug("doc-draft: registry lookup failed", exc_info=True)
    _job_src = str((job.get("metadata") or {}).get("source_root") or "")
    if not source_root:
        source_root = _job_src
    elif _job_src and _job_src != source_root:
        warnings.append(
            f"전체 초안: 분석 당시 트리거 소스({_job_src})와 현재 SCM registry 소스({source_root})가 "
            "다릅니다 — registry 기준으로 합성했습니다")

    sections: Dict[str, Any] = {}
    if source_root:
        try:
            from workflow.impact_orchestrator import _load_source_sections
            sections = _load_source_sections(source_root) or {}
        except Exception as exc:  # noqa: BLE001 — 소스 미해결이면 문서 폴백으로 계속(사유는 표면화)
            _logger.debug("doc-draft: source sections unavailable: %s", exc)
            warnings.append("전체 초안: 소스 파싱 불가 — 문서 원문 기준으로 합성")

    from workflow.impact_orchestrator import _build_doc_proposal
    # 생성기 기본값 전량(SUTS 24 시퀀스 / SITS 14 서브케이스). 함수 1개라 비용이 제한된다.
    proposal = _build_doc_proposal(
        sections, {fn}, warn_sink=warnings,
        doc_content=doc_content, change_details=change_details,
        fn_cap=1, seq_cap=24, sub_cap=14, sts_tc_cap=99, step_cap=12,
    )
    node = proposal.get(doc)
    payload = node.get(fn) if isinstance(node, dict) else None
    var_types = (proposal.get("var_types") or {}).get(fn) or {}
    # ⚠ meta/columns/doc_rows 는 **SUTS 축 전용**이다(시트 컬럼·시퀀스 총량). doc='sits'인데
    #   SUTS 메타를 돌려주면 호출부가 다른 문서의 열 순서로 TSV를 만들게 된다 — doc이 다르면 비운다.
    _is_suts = doc == "suts"
    meta = (proposal.get("suts_meta") or {}).get(fn) if _is_suts else None
    # 표시/TSV 열 순서의 권위 소스 — 시트 헤더 원문(문서 파싱본).
    columns = ((doc_content.get("suts_meta") or {}).get(fn) or {}).get("columns") if _is_suts else None
    doc_rows = (doc_content.get("suts") or {}).get(fn) if _is_suts else None
    # ⚠ `proposal`이 비는 건 정상일 수 있다 — 문서 폴백 경로는 생성기 없이 시퀀스를 지어내지 않고
    #   meta/columns/var_types만 준다. 그러나 **전부** 비었으면 못 만든 것이고, 그때 ok=True를
    #   돌려주면 프론트가 "전체 초안을 불러왔습니다"를 표시하고 버튼까지 없애 재시도가 막힌다.
    if not (payload or meta or var_types or columns or doc_rows):
        warnings.append(f"전체 초안: '{fn}' 에 대한 {doc.upper()} 초안을 만들지 못했습니다(소스·문서 모두 미해결)")
        return {
            "ok": False, "doc": doc, "function": fn,
            "source": proposal.get("source") or "",
            "reason": "empty_proposal", "warnings": warnings,
        }
    return {
        "ok": True,
        "doc": doc,
        "function": fn,
        "source": proposal.get("source") or "",
        "proposal": payload,
        "meta": meta,
        "var_types": var_types,
        "columns": columns,
        "doc_rows": doc_rows,
        # 어느 소스로 합성했는지 — registry가 job 이후 바뀌었을 수 있어 사용자가 대조할 수 있어야 한다.
        "source_root": source_root,
        "warnings": warnings,
    }


@router.post("/api/impact/doc-prose")
def impact_doc_prose(req: ImpactDocProseRequest) -> Dict[str, Any]:
    """결정론 초안에 붙일 **서술문만** 생성(선택). 값은 결정론이 소유 — AI가 바꾸지 않는다.

    응답의 숫자·식별자는 요청으로 받은 결정론 페이로드에 실재하는 것만 통과시킨다
    (환각 필드는 사유와 함께 폐기). LLM 미설정/실패는 ok=False로 정직 반환 — 프론트는
    표를 그대로 유지한다."""
    try:
        from workflow.impact_doc_prose import generate_doc_prose
        return generate_doc_prose(
            function=req.function,
            deterministic=req.deterministic or {},
            signature=req.signature,
            function_diff=req.function_diff,
        )
    except Exception:
        _logger.exception("doc-prose failed")
        return {"ok": False, "fields": {}, "dropped_fields": [], "reason": "doc-prose failed"}


