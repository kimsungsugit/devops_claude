from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.mcp import get_code_search_mcp_server, get_docs_mcp_server, get_jenkins_mcp_server
from backend.services.files import list_log_candidates, tail_text
from workflow.rag import get_kb

from .router import route_retrieval_domains

_logger = logging.getLogger("workflow.retrieval.hybrid")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _semantic_note(reason: str) -> str:
    """열화 사유 → 사용자에게 보일 한 줄. 사유 문자열은 searcher 가 만든다."""
    if reason.startswith("degraded_query_embedding"):
        return ("KB 시맨틱(벡터) 검색이 비활성입니다 — 임베딩 백엔드가 없어 무작위 벡터로 "
                "폴백되므로 유사도 랭킹을 만들 수 없습니다. 아래 근거는 **키워드 검색만** "
                "기준입니다. GEMINI_API_KEY / KB_EMBED_URL / sentence-transformers 중 하나를 "
                "설정하면 복구됩니다.")
    if reason.startswith("alpha=0"):
        return "KB 검색이 키워드 전용 설정(RAG_HYBRID_ALPHA=0)입니다 — 시맨틱 축 미사용."
    return f"KB 시맨틱 검색 비활성: {reason}"


def _report_hits(
    question: str,
    report_dir: Optional[Path],
    top_k: int = 5,
    *,
    notes_out: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """KB 근거 수집.

    Args:
        notes_out: 주면 검색 진단(시맨틱 축 비활성 등)을 사람이 읽을 문장으로 넣는다.
            비어 있는 결과를 "KB 가 비었음" 으로 오독하지 않게 하는 유일한 채널이다.
    """
    if not report_dir:
        return []
    try:
        kb = get_kb(report_dir)
    except Exception:
        return []
    kb_stats: Dict[str, Any] = {}
    try:
        # `stats_out` 미지원 구현체를 TypeError 로 폴백해 주지 **않는다** — 그러면 stub
        # 시그니처 불일치가 조용히 "진단 없음" 으로 삼켜져 이 배선 자체가 무력화된다.
        entries = kb.search(question, top_k=top_k, stats_out=kb_stats)
    except Exception:
        _logger.warning("KB 검색 실패 — 근거 없이 진행한다", exc_info=True)
        return []
    reason = kb_stats.get("semantic_disabled_reason")
    if reason and notes_out is not None:
        notes_out.append(_semantic_note(str(reason)))
    hits: List[Dict[str, Any]] = []
    for idx, ent in enumerate(entries or [], start=1):
        score = ent.get("score") or ent.get("similarity") or ent.get("relevance") or 0.0
        err = str(ent.get("error_clean") or ent.get("error_raw") or "").strip()
        fix = str(ent.get("fix") or ent.get("fix_suggestion") or ent.get("solution") or "").strip()
        snippet = err
        if fix:
            snippet = f"{err}\nFix: {fix}".strip()
        if not snippet:
            continue
        hits.append(
            {
                "hit_id": f"report-{idx}",
                "domain": "reports",
                "source_type": "report",
                "uri": f"kb://{ent.get('source_file') or ent.get('id')}",
                "path": str(ent.get("source_file") or ""),
                "label": str(ent.get("category") or ent.get("id") or f"report-{idx}"),
                "metadata": dict(ent),
                "chunk_text": snippet[:1200],
                "score": float(score or 0.0),
                "rerank_score": float(score or 0.0),
            }
        )
    if len(hits) < top_k:
        summary = _read_json(report_dir / "analysis_summary.json", {})
        status = _read_json(report_dir / "run_status.json", {})
        findings = _read_json(report_dir / "findings_flat.json", [])
        coverage = summary.get("coverage") if isinstance(summary, dict) else {}
        synth_lines: List[str] = []
        state = str(status.get("state") or status.get("status") or "").strip() if isinstance(status, dict) else ""
        if state:
            synth_lines.append(f"build status: {state}")
        if isinstance(status, dict) and isinstance(status.get("ok"), bool):
            synth_lines.append("build ok" if status.get("ok") else "build failed")
        if isinstance(coverage, dict):
            line_rate = coverage.get("line_rate")
            if line_rate not in (None, ""):
                synth_lines.append(f"coverage line rate: {line_rate}")
        if isinstance(findings, list) and findings:
            synth_lines.append(f"findings count: {len(findings)}")
        if not synth_lines:
            synth_lines.append(f"report directory available: {report_dir.name}")
        # 합성 요약은 **검색된 근거가 아니다** — 리포트 파일에서 조립한 대체물이다.
        # 예전엔 점수를 0.35 로 하드코딩했는데, 위 KB 근거는 RRF 융합 점수라 상한이
        # 0.0328(k=60)이다. 그래서 합성 항목이 **항상 실제 근거보다 위**에 정렬되고
        # `retrieve_contexts` 의 top_k 슬롯을 먼저 차지했다. 실제 근거보다 아래로 두고,
        # 근거 텍스트 자체에도 합성임을 명시한다(LLM 이 컨텍스트만 보고 판단하므로).
        real_scores = [float(h.get("score") or 0.0) for h in hits]
        synth_score = min(real_scores) * 0.5 if real_scores else 0.05
        hits.append(
            {
                "hit_id": "report-synth",
                "domain": "reports",
                "source_type": "report",
                "uri": f"report://session/{report_dir.name}",
                "path": str(report_dir),
                "label": "report_summary(합성)",
                "metadata": {"synthetic": True},
                "chunk_text": ("[합성 요약 — KB 검색 결과가 아니라 리포트 파일에서 조립한 값]\n"
                               + "\n".join(synth_lines))[:1200],
                "score": synth_score,
                "rerank_score": synth_score,
            }
        )
    return hits


def _docs_hits(question: str, top_k: int = 5) -> List[Dict[str, Any]]:
    docs = get_docs_mcp_server()
    result = docs.call_tool("search_docs", query=question, max_results=top_k)
    if not result.get("ok"):
        return []
    hits: List[Dict[str, Any]] = []
    for idx, item in enumerate(((result.get("output") or {}).get("results")) or [], start=1):
        path = str(item.get("path") or "")
        line = int(item.get("line") or 0)
        text = str(item.get("text") or "")
        score = max(0.1, 1.0 - ((idx - 1) * 0.1))
        hits.append(
            {
                "hit_id": f"docs-{idx}",
                "domain": "docs",
                "source_type": "doc",
                "uri": f"docs://file/{path}",
                "path": path,
                "label": path or f"docs-{idx}",
                "metadata": {"line": line},
                "chunk_text": text,
                "score": score,
                "rerank_score": score,
            }
        )
    return hits


def _logs_hits(question: str, report_dir: Optional[Path], top_k: int = 5) -> List[Dict[str, Any]]:
    if not report_dir:
        return []
    hits: List[Dict[str, Any]] = []
    try:
        candidates = list_log_candidates(report_dir)
    except Exception:
        candidates = {}
    q_tokens = [tok.lower() for tok in str(question or "").split() if tok.strip()]
    for key, paths in candidates.items():
        if not paths:
            continue
        text = tail_text(paths[0], max_bytes=96 * 1024)
        if not text:
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        selected = []
        for line in lines:
            lower = line.lower()
            if any(tok in lower for tok in q_tokens) or any(k in lower for k in ("error", "fail", "exception", "warning", "traceback")):
                selected.append(line)
            if len(selected) >= 4:
                break
        if not selected:
            selected = lines[-4:]
        if not selected:
            continue
        score = max(0.1, 1.0 - (len(hits) * 0.1))
        hits.append(
            {
                "hit_id": f"log-{key}",
                "domain": "logs",
                "source_type": "log",
                "uri": f"report://log/{key}",
                "path": str(paths[0]),
                "label": key,
                "metadata": {},
                "chunk_text": "\n".join(selected)[:1200],
                "score": score,
                "rerank_score": score,
            }
        )
        if len(hits) >= top_k:
            break
    return hits


def _code_hits(question: str, ui_context: Optional[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    ctx = ui_context or {}
    project_root = str(ctx.get("project_root") or "")
    if not project_root:
        return []
    rel_path = str(ctx.get("workdir_rel") or ".")
    code = get_code_search_mcp_server()
    result = code.call_tool("search_code", project_root=project_root, rel_path=rel_path, query=question, max_results=top_k)
    if not result.get("ok"):
        return []
    hits: List[Dict[str, Any]] = []
    for idx, item in enumerate(((result.get("output") or {}).get("results")) or [], start=1):
        path = str(item.get("path") or "")
        line = int(item.get("line") or 0)
        text = str(item.get("text") or "")
        score = max(0.1, 1.0 - ((idx - 1) * 0.1))
        label = path or f"code-{idx}"
        snippet = text
        symbol_match = next((tok for tok in str(question or "").split() if "_" in tok or tok.isidentifier()), "")
        if symbol_match and symbol_match not in snippet:
            snippet = f"{symbol_match}\n{snippet}".strip()
        hits.append(
            {
                "hit_id": f"code-{idx}",
                "domain": "code",
                "source_type": "code",
                "uri": f"code://file/{path}",
                "path": path,
                "label": label,
                "metadata": {"line": line},
                "chunk_text": snippet,
                "score": score,
                "rerank_score": score,
            }
        )
    return hits


def _jenkins_hits(question: str, ui_context: Optional[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    ctx = ui_context or {}
    job_url = str(ctx.get("job_url") or "").strip()
    cache_root = str(ctx.get("cache_root") or "").strip()
    build_selector = str(ctx.get("build_selector") or "lastSuccessfulBuild").strip()
    if not job_url or not cache_root:
        return []
    jenkins = get_jenkins_mcp_server()
    hits: List[Dict[str, Any]] = []

    tool_specs = [
        ("get_build_report_summary", "summary", "jenkins"),
        ("get_build_report_status", "status", "jenkins"),
        ("get_build_report_findings", "findings", "jenkins"),
        ("get_console_excerpt", "console", "log"),
    ]
    for tool_name, label, source_type in tool_specs:
        result = jenkins.call_tool(tool_name, job_url=job_url, cache_root=cache_root, build_selector=build_selector)
        if not result.get("ok"):
            continue
        output = result.get("output")
        if isinstance(output, dict):
            if "text" in output:
                chunk_text = str(output.get("text") or "")
                path = str(output.get("path") or "")
            else:
                chunk_text = str(output)[:1200]
                path = ""
        else:
            chunk_text = str(output)[:1200]
            path = ""
        if not chunk_text.strip():
            continue
        score = max(0.1, 1.0 - (len(hits) * 0.1))
        hits.append(
            {
                "hit_id": f"jenkins-{label}",
                "domain": "jenkins",
                "source_type": source_type,
                "uri": str(result.get("resource_uri") or ""),
                "path": path,
                "label": label,
                "metadata": {},
                "chunk_text": chunk_text[:1200],
                "score": score,
                "rerank_score": score,
            }
        )
        if len(hits) >= top_k:
            break
    return hits


def retrieve_contexts(
    *,
    question: str,
    question_type: str,
    report_dir: Optional[Path],
    ui_context: Optional[Dict[str, Any]],
    top_k: int = 6,
    notes_out: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """도메인별 근거 수집.

    Args:
        notes_out: 주면 검색 진단(KB 시맨틱 축 비활성 등)을 사람이 읽을 문장으로 넣는다.
            hits 가 적거나 비었을 때 그 **이유**를 사용자·LLM 이 구분할 수 있어야 한다
            (additive — 기존 호출 무영향).
    """
    domains = route_retrieval_domains(question_type)
    hits: List[Dict[str, Any]] = []
    if "reports" in domains:
        hits.extend(_report_hits(question, report_dir, top_k=top_k, notes_out=notes_out))
    if "logs" in domains:
        hits.extend(_logs_hits(question, report_dir, top_k=min(top_k, 4)))
    if "docs" in domains:
        hits.extend(_docs_hits(question, top_k=min(top_k, 5)))
    if "code" in domains:
        hits.extend(_code_hits(question, ui_context, top_k=min(top_k, 5)))
    if "jenkins" in domains:
        hits.extend(_jenkins_hits(question, ui_context, top_k=min(top_k, 4)))

    domain_rank = {name: idx for idx, name in enumerate(domains)}

    def _sort_key(item: Dict[str, Any]) -> tuple[float, float]:
        domain = str(item.get("domain") or "")
        priority = float(max(0, 10 - domain_rank.get(domain, 9)))
        score = float(item.get("rerank_score") or item.get("score") or 0.0)
        return (priority, score)

    hits.sort(key=_sort_key, reverse=True)
    return hits[:top_k]
