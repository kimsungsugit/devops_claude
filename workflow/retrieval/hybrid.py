from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from backend.mcp import get_code_search_mcp_server, get_docs_mcp_server, get_jenkins_mcp_server
from backend.services.files import list_log_candidates, tail_text
from workflow.rag import get_kb

from .router import route_retrieval_domains


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _report_hits(question: str, report_dir: Optional[Path], top_k: int = 5) -> List[Dict[str, Any]]:
    if not report_dir:
        return []
    try:
        kb = get_kb(report_dir)
    except Exception:
        return []
    try:
        entries = kb.search(question, top_k=top_k)
    except Exception:
        return []
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
        hits.append(
            {
                "hit_id": "report-synth",
                "domain": "reports",
                "source_type": "report",
                "uri": f"report://session/{report_dir.name}",
                "path": str(report_dir),
                "label": "report_summary",
                "metadata": {"synthetic": True},
                "chunk_text": "\n".join(synth_lines)[:1200],
                "score": 0.35,
                "rerank_score": 0.35,
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
) -> List[Dict[str, Any]]:
    domains = route_retrieval_domains(question_type)
    hits: List[Dict[str, Any]] = []
    if "reports" in domains:
        hits.extend(_report_hits(question, report_dir, top_k=top_k))
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
