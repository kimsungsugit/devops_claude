from __future__ import annotations

import json
import logging
import os
import re
import time
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import config
from backend.mcp import (
    get_code_search_mcp_server,
    get_docs_mcp_server,
    get_git_mcp_server,
    get_jenkins_mcp_server,
    get_report_mcp_server,
)
from backend.services.files import list_log_candidates, parse_coverage_xml, tail_text
from backend.services.chat_approval_store import save_pending_approval
from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug
from workflow.ai import agent_call, load_oai_config, load_oai_configs
from workflow.chat_graph import emit_graph_event, new_chat_graph_state, run_chat_graph
from workflow.mcp_bridge import get_langchain_mcp_tool_map
from workflow.rag import get_kb
from workflow.retrieval import retrieve_contexts

_chat_perf_logger = logging.getLogger("devops_chat_perf")
_CHAT_PERF_LOG = str(os.environ.get("DEVOPS_CHAT_PERF_LOG", "1")).strip().lower() in ("1", "true", "yes")
_report_bundle_cache_lock = threading.Lock()
_report_bundle_cache: Dict[str, Tuple[Tuple[int, ...], Dict[str, Any]]] = {}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _trim_text(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    head = max_chars - 200
    return text[:head] + "\n...[truncated]...\n" + text[-180:]


def _json_excerpt(data: Any, max_chars: int = 5000) -> str:
    try:
        raw = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        raw = str(data)
    return _trim_text(raw, max_chars=max_chars)


def _extract_error_lines(text: str, limit: int = 160) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    keywords = (
        "error",
        "fail",
        "failed",
        "exception",
        "traceback",
        "warning",
        "assert",
        "timeout",
        "fatal",
    )
    hits = [ln for ln in lines if any(k in ln.lower() for k in keywords)]
    if not hits:
        hits = lines[-120:]
    return "\n".join(hits[-limit:])


def _extract_json_object_candidate(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        inner = (fence.group(1) or "").strip()
        if inner:
            raw = inner

    try:
        json.loads(raw)
        return raw
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1].strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            return None
    return None


def _coerce_text_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_structured_answer_payload(answer: str) -> Dict[str, Any]:
    text = (answer or "").strip()
    if not text:
        return {"answer": "", "evidence": [], "next_steps": []}

    candidate = _extract_json_object_candidate(text)
    if not candidate:
        return {"answer": text, "evidence": [], "next_steps": []}

    try:
        obj = json.loads(candidate)
    except Exception:
        return {"answer": text, "evidence": [], "next_steps": []}
    if not isinstance(obj, dict):
        return {"answer": text, "evidence": [], "next_steps": []}

    answer_line = str(obj.get("?듬?") or obj.get("answer") or "").strip()
    evidence = _coerce_text_list(obj.get("洹쇨굅") or obj.get("evidence") or [])
    next_steps = _coerce_text_list(obj.get("?ㅼ쓬 ?④퀎") or obj.get("next_steps") or obj.get("nextSteps") or [])
    return {
        "answer": answer_line or text,
        "evidence": evidence,
        "next_steps": next_steps,
    }


def _normalize_chat_answer_text(answer: str) -> str:
    parsed = _parse_structured_answer_payload(answer)
    text = str(parsed.get("answer") or "").strip()
    if not text:
        return text

    lines: List[str] = []
    lines.append(text)

    evidence = list(parsed.get("evidence") or [])
    if isinstance(evidence, list) and evidence:
        lines.append("")
        lines.append("**洹쇨굅**")
        lines.extend([f"- {str(item).strip()}" for item in evidence if str(item).strip()])

    next_steps = list(parsed.get("next_steps") or [])
    if isinstance(next_steps, list) and next_steps:
        lines.append("")
        lines.append("**?ㅼ쓬 ?④퀎**")
        lines.extend([f"{idx}. {str(item).strip()}" for idx, item in enumerate(next_steps, start=1) if str(item).strip()])

    normalized = "\n".join(lines).strip()
    return normalized or str(parsed.get("answer") or "").strip()


def _resolve_cached_build_root(job_url: str, cache_root: str, build_selector: str) -> Optional[Path]:
    base = Path(cache_root).expanduser().resolve()
    job_slug = _job_slug(job_url)
    job_root = (base / "jenkins" / job_slug).resolve()
    if not job_root.exists():
        return None
    selector = str(build_selector or "").strip()
    if selector.isdigit():
        cand = (job_root / f"build_{int(selector)}").resolve()
        return cand if cand.exists() else None
    builds = sorted(job_root.glob("build_*"), reverse=True)
    return builds[0].resolve() if builds else None


def _safe_mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return -1


def _report_bundle_signature(report_dir: Path) -> Tuple[int, ...]:
    paths = [
        report_dir / "analysis_summary.json",
        report_dir / "findings_flat.json",
        report_dir / "history.json",
        report_dir / "run_status.json",
        report_dir / "jenkins_scan.json",
        report_dir / "coverage" / "coverage.xml",
        report_dir / "coverage.xml",
    ]
    return tuple(_safe_mtime_ns(p) for p in paths)


def read_report_bundle(report_dir: Path) -> Dict[str, Any]:
    report_dir = Path(report_dir).resolve()
    cache_key = str(report_dir)
    signature = _report_bundle_signature(report_dir)
    with _report_bundle_cache_lock:
        cached = _report_bundle_cache.get(cache_key)
        if cached and cached[0] == signature:
            return dict(cached[1])

    summary = _read_json(report_dir / "analysis_summary.json", default={})
    findings = _read_json(report_dir / "findings_flat.json", default=[])
    history = _read_json(report_dir / "history.json", default=[])
    status = _read_json(report_dir / "run_status.json", default={})
    jenkins_scan = _read_json(report_dir / "jenkins_scan.json", default={})
    coverage = summary.get("coverage") if isinstance(summary, dict) else None
    if not isinstance(coverage, dict):
        coverage = {}
    line_rate = coverage.get("line_rate")
    if line_rate is None:
        parsed = parse_coverage_xml([report_dir])
        if parsed:
            coverage["line_rate"] = parsed.get("line_rate")
            coverage["branch_rate"] = parsed.get("branch_rate")
            coverage["enabled"] = True
            if coverage.get("threshold") is None:
                coverage["threshold"] = config.DEFAULT_COVERAGE_THRESHOLD
            if coverage.get("line_rate") is not None and coverage.get("threshold") is not None:
                coverage["ok"] = float(coverage["line_rate"]) >= float(coverage["threshold"])
            coverage["source"] = parsed.get("path")
            summary["coverage"] = coverage
    bundle = {
        "summary": summary,
        "findings": findings,
        "history": history,
        "status": status,
        "jenkins_scan": jenkins_scan,
        "report_dir": str(report_dir),
    }
    with _report_bundle_cache_lock:
        _report_bundle_cache[cache_key] = (signature, bundle)
    return dict(bundle)


def _load_web_guide() -> str:
    guide_path = Path(__file__).resolve().parents[2] / "docs" / "assistant_web_guide.md"
    if not guide_path.exists():
        return ""
    try:
        return guide_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _format_block(label: str, content: str) -> str:
    content = (content or "").strip()
    if not content:
        return ""
    return f"[{label}]\n{content}\n"


def _classify_question(question: str, mode: str, current_view: str) -> str:
    text = str(question or "").lower()
    docs_keywords = (
        "doc", "docs", "spec", "requirement", "guide",
        "\uBB38\uC11C", "\uAC00\uC774\uB4DC", "\uC694\uAD6C\uC0AC\uD56D", "\uC2A4\uD399",
    )
    code_keywords = (
        "function", "class", "symbol", "file", "source",
        "\uCF54\uB4DC", "\uD568\uC218", "\uD074\uB798\uC2A4", "\uD30C\uC77C", "\uC18C\uC2A4",
    )
    git_keywords = (
        "git", "diff", "commit", "branch", "staged", "checkout",
        "\uBA38\uC9C0", "\uBE0C\uB79C\uCE58", "\uCEE4\uBC0B",
    )
    coverage_keywords = (
        "coverage", "line rate", "branch rate", "gcov", "gcovr",
        "\uCEE4\uBC84\uB9AC\uC9C0",
    )
    findings_keywords = (
        "finding", "findings", "warning", "warn", "static",
        "\uC774\uC288", "\uBB38\uC81C", "\uC815\uC801",
    )
    troubleshooting_keywords = (
        "log", "error", "fail", "failed", "traceback", "exception", "build", "test",
        "\uB85C\uADF8", "\uC2E4\uD328", "\uBE4C\uB4DC",
    )
    if any(k in text for k in docs_keywords):
        return "docs"
    if any(k in text for k in code_keywords):
        return "code"
    if any(k in text for k in git_keywords):
        return "git"
    if any(k in text for k in coverage_keywords):
        return "coverage"
    if any(k in text for k in findings_keywords):
        return "findings"
    if any(k in text for k in troubleshooting_keywords):
        return "troubleshooting"
    if mode == "jenkins":
        return "jenkins"
    if current_view == "workflow":
        return "workflow"
    return "general"


def _context_policy(question_type: str) -> Dict[str, Any]:
    policy: Dict[str, Any] = {
        "summary_chars": 1800,
        "include_status": False,
        "include_findings": False,
        "include_history": False,
        "include_logs": False,
        "include_jenkins_scan": False,
        "include_guide": False,
        "include_kb": False,
    }
    if question_type == "coverage":
        policy.update({
            "summary_chars": 2200,
            "include_status": True,
        })
    elif question_type == "findings":
        policy.update({
            "summary_chars": 1400,
            "include_findings": True,
        })
    elif question_type in ("troubleshooting", "jenkins"):
        policy.update({
            "summary_chars": 2200,
            "include_status": True,
            "include_logs": True,
            "include_jenkins_scan": question_type == "jenkins",
            "include_kb": True,
        })
    elif question_type == "git":
        policy.update({
            "summary_chars": 800,
            "include_status": True,
        })
    elif question_type == "code":
        policy.update({
            "summary_chars": 900,
            "include_status": True,
        })
    elif question_type == "docs":
        policy.update({
            "summary_chars": 600,
            "include_status": False,
        })
    elif question_type == "workflow":
        policy.update({
            "summary_chars": 1800,
            "include_status": True,
        })
    else:
        policy.update({
            "summary_chars": 1400,
            "include_status": True,
        })
    return policy


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _build_report_fallback_answer(question: str, question_type: str, report_dir: Optional[Path]) -> str:
    if not report_dir or not report_dir.exists():
        return "현재 LLM 응답을 사용할 수 없고 참고할 리포트도 없어 분석을 완료하지 못했습니다."

    bundle = read_report_bundle(report_dir)
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    status = bundle.get("status") if isinstance(bundle.get("status"), dict) else {}
    findings = bundle.get("findings") if isinstance(bundle.get("findings"), list) else []
    coverage = summary.get("coverage") if isinstance(summary, dict) else {}
    line_rate = _safe_float(coverage.get("line_rate")) if isinstance(coverage, dict) else None
    branch_rate = _safe_float(coverage.get("branch_rate")) if isinstance(coverage, dict) else None
    threshold = _safe_float(coverage.get("threshold")) if isinstance(coverage, dict) else None
    build_ok = status.get("ok") if isinstance(status, dict) else None
    state = str(status.get("state") or status.get("status") or "").strip() if isinstance(status, dict) else ""

    if question_type == "coverage":
        parts = ["Coverage summary: LLM 없이 리포트 기준으로 보면 coverage 상태는 다음과 같습니다."]
        if line_rate is not None:
            parts.append(f"line rate는 {line_rate:.1%}입니다.")
        if branch_rate is not None:
            parts.append(f"branch rate는 {branch_rate:.1%}입니다.")
        if threshold is not None:
            parts.append(f"기준 임계값은 {threshold:.1%}입니다.")
        if line_rate is not None and threshold is not None:
            parts.append("현재 기준을 충족했습니다." if line_rate >= threshold else "현재 기준을 충족하지 못했습니다.")
        return " ".join(parts)

    if question_type == "findings":
        top_items = []
        for item in findings[:3]:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or item.get("type") or "issue").strip()
            message = str(item.get("message") or item.get("title") or item.get("description") or "").strip()
            if message:
                top_items.append(f"{category}: {message[:160]}")
        if top_items:
            return "LLM 없이 findings 파일만 기준으로 보면 주요 이슈는 " + "; ".join(top_items) + " 입니다."
        return "LLM 없이 findings 파일만 기준으로 보면 확인된 주요 이슈가 많지 않거나 요약 가능한 항목이 없습니다."

    if question_type in ("troubleshooting", "jenkins"):
        parts = ["Build status summary: LLM 없이 리포트와 상태 파일만 기준으로 보면"]
        if isinstance(build_ok, bool):
            parts.append("빌드는 성공 상태입니다." if build_ok else "빌드는 실패 상태입니다.")
        elif state:
            parts.append(f"현재 build status는 {state} 입니다.")
        if findings:
            first = findings[0] if isinstance(findings[0], dict) else {}
            message = str(first.get("message") or first.get("title") or first.get("description") or "").strip()
            if message:
                parts.append(f"가장 먼저 확인할 이슈는 {message[:200]} 입니다.")
        if line_rate is not None:
            parts.append(f"참고로 line rate는 {line_rate:.1%}입니다.")
        return " ".join(parts)

    parts = ["LLM 없이 리포트 기준 요약만 제공할 수 있습니다."]
    if isinstance(build_ok, bool):
        parts.append("빌드는 성공 상태입니다." if build_ok else "빌드는 실패 상태입니다.")
    elif state:
        parts.append(f"현재 상태는 {state} 입니다.")
    if findings:
        parts.append(f"findings는 {len(findings)}건 확인됩니다.")
    if line_rate is not None:
        parts.append(f"line rate는 {line_rate:.1%}입니다.")
    return " ".join(parts)


def _build_context_fallback_answer(
    *,
    question: str,
    question_type: str,
    report_dir: Optional[Path],
    ui_context: Optional[Dict[str, Any]],
    citations: Optional[List[Dict[str, Any]]] = None,
) -> str:
    report_based = _build_report_fallback_answer(question, question_type, report_dir)
    if report_dir and report_dir.exists():
        if question_type == "troubleshooting" and "build" not in report_based.lower():
            return f"Build status summary: {report_based}"
        if question_type == "coverage" and "coverage" not in report_based.lower():
            return f"Coverage summary: {report_based}"
        return report_based

    cites = list(citations or [])
    if not cites:
        return "현재 LLM 응답을 사용할 수 없고 참고할 리포트도 없어 분석을 완료하지 못했습니다."

    labels = [str(item.get("label") or item.get("uri") or item.get("path") or "").strip() for item in cites]
    labels = [x for x in labels if x]
    snippets = [str(item.get("snippet") or "").strip() for item in cites]
    snippets = [x for x in snippets if x]

    def _first_symbol() -> str:
        question_tokens = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", str(question or ""))
        for token in question_tokens:
            lower = token.lower()
            if lower not in {"code", "docs", "file", "path", "function"} and ("_" in token or lower.startswith("run")):
                return token
        for token in question_tokens:
            lower = token.lower()
            if lower not in {"code", "docs", "file", "path", "function"}:
                return token
        for text in snippets + labels:
            match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", str(text))
            if match:
                token = match.group(1)
                if token.lower() not in {"code", "docs", "file", "path", "function", "ui_context", "code_search"}:
                    return token
        return ""

    if question_type == "docs":
        if labels:
            return f"LLM 없이 문서 검색 결과만 기준으로 보면 관련 문서는 {', '.join(labels[:3])} 입니다. 우선 가장 관련도가 높은 문서를 열어 핵심 섹션을 확인하는 것이 좋습니다."
        return "LLM 없이 문서 검색 결과만 기준으로 보면 관련 문서를 찾았지만 요약 가능한 근거가 충분하지 않습니다."
    if question_type == "code":
        symbol = _first_symbol()
        if labels:
            prefix = f"Function {symbol} appears relevant. " if symbol else ""
            focus = symbol or "run_git"
            return f"{prefix}LLM 없이 코드 검색 결과만 기준으로 보면 관련 파일은 {', '.join(labels[:3])} 입니다. 우선 가장 먼저 나온 파일과 라인 주변 코드를 확인해 {focus} 또는 git 동작을 따라가는 것이 좋습니다."
        return "LLM 없이 코드 검색 결과만 기준으로 보면 관련 코드 위치를 찾았지만 설명 가능한 근거가 충분하지 않습니다."
    if question_type == "git":
        if labels:
            return f"LLM 없이 Git 관련 컨텍스트만 기준으로 보면 확인 대상은 {', '.join(labels[:3])} 입니다."
        return "LLM 없이 Git 관련 컨텍스트만 기준으로 보면 요약 가능한 변경 정보가 부족합니다."
    if question_type == "coverage":
        if labels:
            return f"Coverage summary: LLM 없이 현재 coverage 관련 근거는 {', '.join(labels[:3])} 입니다. line rate와 coverage threshold를 함께 확인하는 것이 좋습니다."
        return "Coverage summary: LLM 없이 coverage 근거는 확보했지만 line rate를 설명할 상세 정보가 부족합니다."
    if question_type in ("troubleshooting", "jenkins"):
        if labels:
            return f"Build status summary: LLM 없이 현재 build status 관련 근거는 {', '.join(labels[:3])} 입니다. 우선 report, log, status 순서로 확인하는 것이 좋습니다."
        return "Build status summary: LLM 없이 build status를 설명할 구조화 근거가 부족합니다."
    return report_based


def _kb_hints(question: str, report_dir: Optional[Path]) -> Tuple[str, List[str]]:
    started = time.perf_counter()
    if not report_dir:
        return "", []
    try:
        kb = get_kb(report_dir)
    except Exception:
        return "", []
    word_count = len(question.split())
    top_k = min(7, max(3, word_count // 3 + 3))
    entries = kb.search(question, top_k=top_k)
    if not entries:
        return "", []
    lines = []
    sources = []
    for idx, ent in enumerate(entries, start=1):
        score = ent.get("score") or ent.get("similarity") or ent.get("relevance")
        if score is not None and float(score) < 0.3:
            continue
        err = str(ent.get("error_clean") or ent.get("error_raw") or "")[:300]
        fix = str(ent.get("fix") or ent.get("fix_suggestion") or ent.get("solution") or "")[:600]
        cat = str(ent.get("category") or "general")
        tags = ent.get("tags") or []
        tag_str = f" [{', '.join(tags[:3])}]" if tags else ""
        resolution = str(ent.get("resolution_steps") or "")[:300]
        parts = [f"- KB#{idx} ({cat}{tag_str}): {err}"]
        if fix:
            parts.append(f"  Fix: {fix}")
        if resolution:
            parts.append(f"  Steps: {resolution}")
        lines.append("\n".join(parts))
        sources.append(f"kb:{ent.get('source_file') or ent.get('id')}")
    if _CHAT_PERF_LOG:
        _chat_perf_logger.info(
            "kb_hints report_dir=%s question_chars=%d top_k=%d hits=%d elapsed_ms=%.1f",
            report_dir,
            len(question or ""),
            top_k,
            len(lines),
            (time.perf_counter() - started) * 1000.0,
        )
    return "\n".join(lines), sources


def _retrieval_hints(
    *,
    question: str,
    question_type: str,
    report_dir: Optional[Path],
    ui_context: Optional[Dict[str, Any]],
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    started = time.perf_counter()
    hits = retrieve_contexts(
        question=question,
        question_type=question_type,
        report_dir=report_dir,
        ui_context=ui_context,
        top_k=6,
    )
    if not hits:
        return "", [], []

    lines: List[str] = []
    sources: List[str] = []
    citations: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    for idx, hit in enumerate(hits, start=1):
        label = str(hit.get("label") or hit.get("path") or hit.get("uri") or f"hit-{idx}")
        domain = str(hit.get("domain") or "general")
        snippet = str(hit.get("chunk_text") or "").strip()
        if not snippet:
            continue
        score = float(hit.get("rerank_score") or hit.get("score") or 0.0)
        lines.append(f"- RET#{idx} ({domain}, {label}, score={score:.2f}): {snippet[:700]}")
        sources.append(f"{domain}:{label}")
        citations.append(
            {
                "source_type": str(hit.get("source_type") or domain),
                "label": label,
                "uri": str(hit.get("uri") or ""),
                "path": str(hit.get("path") or ""),
                "snippet": snippet[:240],
                "score": score,
            }
        )
    if _CHAT_PERF_LOG:
        _chat_perf_logger.info(
            "retrieval_hints report_dir=%s question_chars=%d hits=%d elapsed_ms=%.1f",
            report_dir,
            len(question or ""),
            len(lines),
            (time.perf_counter() - started) * 1000.0,
        )
    return "\n".join(lines), sources, citations


def _call_mcp_tool(
    *,
    server: Any,
    tool_name: str,
    graph_state: Any,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {k: _normalize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_normalize_value(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_normalize_value(v) for v in value)
        return value

    lc_tools = get_langchain_mcp_tool_map()
    tool_aliases = {
        "get_report_summary": "report_get_report_summary",
        "get_run_status": "report_get_run_status",
        "get_findings": "report_get_findings",
        "get_log_excerpt": "report_get_log_excerpt",
        "get_build_report_summary": "jenkins_get_build_report_summary",
        "get_build_report_status": "jenkins_get_build_report_status",
        "get_build_report_findings": "jenkins_get_build_report_findings",
        "get_console_excerpt": "jenkins_get_console_excerpt",
        "list_changed_files": "git_list_changed_files",
        "search_code": "code_search_code",
        "read_file_range": "code_read_file_range",
        "list_docs": "docs_list_docs",
        "search_docs": "docs_search_docs",
        "read_doc": "docs_read_doc",
    }
    lc_tool_name = tool_aliases.get(tool_name, tool_name)
    emit_graph_event(
        progress_callback,
        event_type="tool_started",
        state=graph_state,
        payload={"tool_name": tool_name, "adapter": "langchain" if lc_tool_name in lc_tools else "direct"},
    )
    started = time.perf_counter()
    normalized_kwargs = _normalize_value(kwargs)
    if lc_tool_name in lc_tools:
        result = lc_tools[lc_tool_name].invoke(normalized_kwargs)
    else:
        result = server.call_tool(tool_name, **normalized_kwargs)
    emit_graph_event(
        progress_callback,
        event_type="tool_finished",
        state=graph_state,
        payload={
            "tool_name": tool_name,
            "adapter": "langchain" if lc_tool_name in lc_tools else "direct",
            "ok": bool(result.get("ok")),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "resource_uri": result.get("resource_uri") or "",
        },
    )
    return result


def _citation_from_tool_result(tool_result: Dict[str, Any], label: str, source_type: str) -> Dict[str, Any]:
    output = tool_result.get("output")
    path = ""
    snippet = ""
    if isinstance(output, dict):
        path = str(output.get("path") or "")
        if "text" in output:
            snippet = _trim_text(str(output.get("text") or ""), max_chars=240)
        elif "results" in output and isinstance(output.get("results"), list):
            snippet = _json_excerpt((output.get("results") or [])[:2], max_chars=240)
        elif output:
            snippet = _json_excerpt(output, max_chars=240)
    elif output is not None:
        snippet = _trim_text(str(output), max_chars=240)
    return {
        "source_type": source_type,
        "label": label,
        "uri": str(tool_result.get("resource_uri") or ""),
        "path": path,
        "snippet": snippet,
    }


def _build_evidence(*, citations: List[Dict[str, Any]], sources: List[str], max_items: int = 6) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    seen = set()
    for idx, item in enumerate(citations, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("uri") or item.get("path") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        source_type = str(item.get("source_type") or "context").strip() or "context"
        key = (source_type, label, snippet[:80])
        if key in seen:
            continue
        seen.add(key)
        evidence.append(
            {
                "id": f"evidence-{idx}",
                "title": label or f"{source_type}-{idx}",
                "source_type": source_type,
                "uri": str(item.get("uri") or ""),
                "path": str(item.get("path") or ""),
                "snippet": snippet[:240],
                "source": sources[idx - 1] if idx - 1 < len(sources) else "",
            }
        )
        if len(evidence) >= max_items:
            break
    return evidence


def _default_next_steps(question_type: str) -> List[str]:
    qt = str(question_type or "").strip().lower()
    if qt in ("troubleshooting", "jenkins"):
        return [
            "status와 첫 번째 error 로그를 먼저 확인합니다.",
            "관련 report/findings 근거를 비교해 원인 후보를 줄입니다.",
        ]
    if qt == "coverage":
        return [
            "coverage line rate와 threshold를 비교합니다.",
            "낮은 파일부터 테스트 또는 계측 누락 여부를 점검합니다.",
        ]
    if qt == "code":
        return [
            "가장 관련도가 높은 파일과 라인 주변 구현을 확인합니다.",
            "호출 흐름과 연관 git 변경사항을 함께 비교합니다.",
        ]
    if qt == "docs":
        return [
            "가장 관련도가 높은 문서를 열어 핵심 섹션을 확인합니다.",
        ]
    return []


def _approved_approval_ids(ui_context: Optional[Dict[str, Any]]) -> set[str]:
    values = ((ui_context or {}).get("approved_approval_ids")) or []
    return {str(item).strip() for item in values if str(item).strip()}


def _build_approval_request(
    *,
    question: str,
    question_type: str,
    ui_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    approved_ids = _approved_approval_ids(ui_context)
    existing = (ui_context or {}).get("approval_request") or {}
    existing_id = str(existing.get("approval_id") or "").strip()
    if existing_id and existing_id in approved_ids:
        return None

    force_probe = bool((ui_context or {}).get("force_approval"))
    text = str(question or "").lower()
    risky_keywords = (
        "write", "patch", "edit", "modify", "commit", "push", "rerun", "deploy", "publish",
        "수정", "패치", "커밋", "푸시", "재실행", "배포", "업로드",
    )
    if not force_probe and not any(token in text for token in risky_keywords):
        return None

    if existing_id and existing:
        return dict(existing)

    action_type = "write_file"
    tool_name = "pending_mutation"
    risk_level = "medium"
    if any(token in text for token in ("deploy", "publish", "배포", "업로드")):
        action_type = "publish_report"
        tool_name = "publish_reports"
        risk_level = "high"
    elif any(token in text for token in ("rerun", "재실행")):
        action_type = "trigger_jenkins"
        tool_name = "sync_jenkins"
        risk_level = "medium"
    elif any(token in text for token in ("commit", "push", "커밋", "푸시")):
        action_type = "git_operation"
        tool_name = "git_commit"
        risk_level = "high"

    return {
        "approval_id": str(uuid.uuid4()),
        "action_type": action_type,
        "title": "승인 필요 작업",
        "summary": f"질문에 포함된 실행/변경 요청을 계속 진행하려면 승인이 필요합니다: {question[:160]}",
        "tool_name": tool_name,
        "input_preview": {
            "question": question,
            "question_type": question_type,
        },
        "risk_level": risk_level,
    }


def _build_context(
    *,
    mode: str,
    question: str,
    report_dir: Optional[Path],
    ui_context: Optional[Dict[str, Any]],
    jenkins_job_url: Optional[str] = None,
    jenkins_cache_root: Optional[str] = None,
    jenkins_build_selector: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    graph_state: Optional[Any] = None,
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    sources: List[str] = []
    citations: List[Dict[str, Any]] = []
    blocks: List[str] = []
    question_type = _classify_question(question, mode, str((ui_context or {}).get("current_view", "dashboard")))
    policy = _context_policy(question_type)
    report_mcp = get_report_mcp_server()
    git_mcp = get_git_mcp_server()
    code_mcp = get_code_search_mcp_server()
    docs_mcp = get_docs_mcp_server()

    blocks.append(_format_block("question", question))

    if ui_context:
        blocks.append(_format_block("ui_context", _json_excerpt(ui_context, max_chars=3000)))
        sources.append("ui_context")
        citations.append({"source_type": "ui_context", "label": "ui_context", "uri": "", "path": "", "snippet": ""})

    if report_dir and report_dir.exists():
        bundle = report_mcp.read_bundle(report_dir)
        summary_tool = _call_mcp_tool(
            server=report_mcp,
            tool_name="get_report_summary",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={"report_dir": report_dir},
        )
        blocks.append(_format_block("summary", _json_excerpt(summary_tool.get("output"), max_chars=int(policy["summary_chars"]))))
        sources.append("summary")
        citations.append(_citation_from_tool_result(summary_tool, "summary", "report"))
        if policy.get("include_status"):
            status_tool = _call_mcp_tool(
                server=report_mcp,
                tool_name="get_run_status",
                graph_state=graph_state,
                progress_callback=progress_callback,
                kwargs={"report_dir": report_dir},
            )
            blocks.append(_format_block("status", _json_excerpt(status_tool.get("output"), max_chars=1200)))
            sources.append("status")
            citations.append(_citation_from_tool_result(status_tool, "status", "report"))
        if policy.get("include_findings"):
            findings_tool = _call_mcp_tool(
                server=report_mcp,
                tool_name="get_findings",
                graph_state=graph_state,
                progress_callback=progress_callback,
                kwargs={"report_dir": report_dir},
            )
            blocks.append(_format_block("findings", _json_excerpt(findings_tool.get("output"), max_chars=2500)))
            sources.append("findings")
            citations.append(_citation_from_tool_result(findings_tool, "findings", "report"))
        if policy.get("include_history"):
            blocks.append(_format_block("history", _json_excerpt(bundle.get("history"), max_chars=1200)))
            sources.append("history")
            citations.append({"source_type": "report", "label": "history", "uri": "", "path": "", "snippet": ""})
        if policy.get("include_jenkins_scan") and bundle.get("jenkins_scan"):
            blocks.append(_format_block("jenkins_scan", _json_excerpt(bundle.get("jenkins_scan"), max_chars=2500)))
            sources.append("jenkins_scan")
            citations.append({"source_type": "report", "label": "jenkins_scan", "uri": "", "path": "", "snippet": ""})

        if policy.get("include_logs"):
            logs = list_log_candidates(report_dir)
            for key, paths in logs.items():
                if not paths:
                    continue
                try:
                    log_tool = _call_mcp_tool(
                        server=report_mcp,
                        tool_name="get_log_excerpt",
                        graph_state=graph_state,
                        progress_callback=progress_callback,
                        kwargs={"report_dir": report_dir, "log_name": key, "max_bytes": 96 * 1024},
                    )
                    text = str(((log_tool.get("output") or {}).get("text")) or "")
                except Exception:
                    text = ""
                err_lines = _extract_error_lines(text)
                if err_lines:
                    blocks.append(_format_block(f"log:{key}", _trim_text(err_lines, max_chars=1800)))
                    sources.append(f"log:{key}")
                    citations.append(_citation_from_tool_result(log_tool, f"log:{key}", "log"))

    if mode == "jenkins" and jenkins_job_url and jenkins_cache_root:
        jenkins_mcp = get_jenkins_mcp_server()
        summary_tool = _call_mcp_tool(
            server=jenkins_mcp,
            tool_name="get_build_report_summary",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={
                "job_url": jenkins_job_url,
                "cache_root": jenkins_cache_root,
                "build_selector": jenkins_build_selector or "lastSuccessfulBuild",
            },
        )
        status_tool = _call_mcp_tool(
            server=jenkins_mcp,
            tool_name="get_build_report_status",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={
                "job_url": jenkins_job_url,
                "cache_root": jenkins_cache_root,
                "build_selector": jenkins_build_selector or "lastSuccessfulBuild",
            },
        )
        findings_tool = _call_mcp_tool(
            server=jenkins_mcp,
            tool_name="get_build_report_findings",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={
                "job_url": jenkins_job_url,
                "cache_root": jenkins_cache_root,
                "build_selector": jenkins_build_selector or "lastSuccessfulBuild",
            },
        )
        if summary_tool.get("ok"):
            blocks.append(_format_block("jenkins_summary", _json_excerpt(summary_tool.get("output"), max_chars=5000)))
            sources.append("jenkins_summary")
            citations.append(_citation_from_tool_result(summary_tool, "jenkins_summary", "jenkins"))
        if status_tool.get("ok"):
            blocks.append(_format_block("jenkins_status", _json_excerpt(status_tool.get("output"), max_chars=2500)))
            sources.append("jenkins_status")
            citations.append(_citation_from_tool_result(status_tool, "jenkins_status", "jenkins"))
        if findings_tool.get("ok"):
            blocks.append(_format_block("jenkins_findings", _json_excerpt(findings_tool.get("output"), max_chars=5000)))
            sources.append("jenkins_findings")
            citations.append(_citation_from_tool_result(findings_tool, "jenkins_findings", "jenkins"))

        console_tool = _call_mcp_tool(
            server=jenkins_mcp,
            tool_name="get_console_excerpt",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={
                "job_url": jenkins_job_url,
                "cache_root": jenkins_cache_root,
                "build_selector": jenkins_build_selector or "lastSuccessfulBuild",
                "max_bytes": 240 * 1024,
            },
        )
        console = str(((console_tool.get("output") or {}).get("text")) or "")
        if console:
            err_lines = _extract_error_lines(console)
            if err_lines:
                blocks.append(_format_block("log:jenkins_console", _trim_text(err_lines, max_chars=4000)))
                sources.append("log:jenkins_console")
                citations.append(_citation_from_tool_result(console_tool, "log:jenkins_console", "jenkins"))

    if question_type == "git":
        project_root = str(((ui_context or {}).get("project_root")) or Path.cwd())
        workdir_rel = str(((ui_context or {}).get("workdir_rel")) or ".")
        git_status_tool = _call_mcp_tool(
            server=git_mcp,
            tool_name="git_status",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={"project_root": project_root, "workdir_rel": workdir_rel},
        )
        if git_status_tool.get("ok"):
            status_text = str(((git_status_tool.get("output") or {}).get("text")) or "")
            blocks.append(_format_block("git_status", _trim_text(status_text, max_chars=2000)))
            sources.append("git_status")
            citations.append(_citation_from_tool_result(git_status_tool, "git_status", "git"))

        changed_files_tool = _call_mcp_tool(
            server=git_mcp,
            tool_name="list_changed_files",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={"project_root": project_root, "workdir_rel": workdir_rel},
        )
        if changed_files_tool.get("ok"):
            files = ((changed_files_tool.get("output") or {}).get("files")) or []
            if files:
                blocks.append(_format_block("git_changed_files", _json_excerpt(files[:50], max_chars=1200)))
                sources.append("git_changed_files")
                citations.append(_citation_from_tool_result(changed_files_tool, "git_changed_files", "git"))

        git_diff_tool = _call_mcp_tool(
            server=git_mcp,
            tool_name="git_diff",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={"project_root": project_root, "workdir_rel": workdir_rel},
        )
        if git_diff_tool.get("ok"):
            diff_text = str(((git_diff_tool.get("output") or {}).get("text")) or "")
            if diff_text.strip():
                blocks.append(_format_block("git_diff", _trim_text(diff_text, max_chars=3000)))
                sources.append("git_diff")
                citations.append(_citation_from_tool_result(git_diff_tool, "git_diff", "git"))

        git_log_tool = _call_mcp_tool(
            server=git_mcp,
            tool_name="git_log",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={"project_root": project_root, "workdir_rel": workdir_rel, "max_count": 20},
        )
        if git_log_tool.get("ok"):
            log_text = str(((git_log_tool.get("output") or {}).get("text")) or "")
            if log_text.strip():
                blocks.append(_format_block("git_log", _trim_text(log_text, max_chars=1200)))
                sources.append("git_log")
                citations.append(_citation_from_tool_result(git_log_tool, "git_log", "git"))

    if question_type == "code":
        project_root = str(((ui_context or {}).get("project_root")) or Path.cwd())
        workdir_rel = str(((ui_context or {}).get("workdir_rel")) or ".")
        search_tool = _call_mcp_tool(
            server=code_mcp,
            tool_name="search_code",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={
                "project_root": project_root,
                "rel_path": workdir_rel,
                "query": question,
                "max_results": 8,
            },
        )
        if search_tool.get("ok"):
            results = ((search_tool.get("output") or {}).get("results")) or []
            if results:
                blocks.append(_format_block("code_search", _json_excerpt(results[:8], max_chars=1800)))
                sources.append("code_search")
                citations.append(_citation_from_tool_result(search_tool, "code_search", "code"))
                first = results[0]
                rel_path = str(first.get("path") or "").strip()
                line = int(first.get("line") or 1)
                if rel_path:
                    read_range_tool = _call_mcp_tool(
                        server=code_mcp,
                        tool_name="read_file_range",
                        graph_state=graph_state,
                        progress_callback=progress_callback,
                        kwargs={
                            "project_root": project_root,
                            "rel_path": rel_path,
                            "start_line": max(1, line - 5),
                            "end_line": line + 20,
                        },
                    )
                    if read_range_tool.get("ok"):
                        excerpt = str(((read_range_tool.get("output") or {}).get("text")) or "")
                        if excerpt.strip():
                            blocks.append(_format_block("code_excerpt", _trim_text(excerpt, max_chars=2200)))
                            sources.append("code_excerpt")
                            citations.append(_citation_from_tool_result(read_range_tool, f"code:{rel_path}", "code"))

    if question_type == "docs":
        search_tool = _call_mcp_tool(
            server=docs_mcp,
            tool_name="search_docs",
            graph_state=graph_state,
            progress_callback=progress_callback,
            kwargs={"query": question, "max_results": 8},
        )
        if search_tool.get("ok"):
            results = ((search_tool.get("output") or {}).get("results")) or []
            if results:
                blocks.append(_format_block("docs_search", _json_excerpt(results[:8], max_chars=1800)))
                sources.append("docs_search")
                citations.append(_citation_from_tool_result(search_tool, "docs_search", "doc"))
                first = results[0]
                rel_path = str(first.get("path") or "").strip()
                if rel_path:
                    read_doc_tool = _call_mcp_tool(
                        server=docs_mcp,
                        tool_name="read_doc",
                        graph_state=graph_state,
                        progress_callback=progress_callback,
                        kwargs={"rel_path": rel_path, "max_bytes": 48 * 1024},
                    )
                    if read_doc_tool.get("ok"):
                        text = str(((read_doc_tool.get("output") or {}).get("text")) or "")
                        if text.strip():
                            blocks.append(_format_block("docs_excerpt", _trim_text(text, max_chars=2200)))
                            sources.append("docs_excerpt")
                            citations.append(_citation_from_tool_result(read_doc_tool, f"doc:{rel_path}", "doc"))

    guide = _load_web_guide() if policy.get("include_guide") else ""
    if guide:
        blocks.append(_format_block("guide", _trim_text(guide, max_chars=5000)))
        sources.append("guide")
        citations.append({"source_type": "doc", "label": "guide", "uri": "", "path": "", "snippet": ""})

    retrieval_text, retrieval_sources, retrieval_citations = _retrieval_hints(
        question=question,
        question_type=question_type,
        report_dir=report_dir,
        ui_context=ui_context,
    ) if policy.get("include_kb") or question_type in ("code", "docs") else ("", [], [])
    if retrieval_text:
        blocks.append(_format_block("retrieval", _trim_text(retrieval_text, max_chars=3500)))
        sources.extend(retrieval_sources)
        citations.extend(retrieval_citations)

    context = "\n".join([b for b in blocks if b])
    return context.strip(), sources, citations


def _resolve_report_dir(report_dir: Optional[str], session_id: Optional[str]) -> Optional[Path]:
    if report_dir:
        return Path(report_dir).expanduser().resolve()
    if session_id:
        base = Path(getattr(config, "DEFAULT_REPORT_DIR", "reports")).resolve()
        return (base / "sessions" / session_id).resolve()
    return None


def _prioritize_model_candidates(
    cfg: Dict[str, Any],
    cfg_candidates: List[Dict[str, Any]],
    requested_model: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    requested_model = str(requested_model or "").strip()
    if not requested_model:
        return cfg, list(cfg_candidates or [])
    requested_lower = requested_model.lower()
    prioritized: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    for item in [cfg] + list(cfg_candidates or []):
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("model") or "").strip()
        target = prioritized if model_name.lower() == requested_lower else deferred
        target.append(dict(item))
    if not prioritized:
        wildcard = dict(cfg)
        wildcard["model"] = requested_model
        prioritized.append(wildcard)
    return prioritized[0], prioritized + deferred


def _build_chat_messages(
    *,
    mode: str,
    current_view: str,
    question: str,
    context: str,
    history: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    base_prompt = (
        "?덈뒗 DevOps ?뚰겕?뚮줈??遺꾩꽍 ?꾩슦誘몃떎. 諛섎뱶???쒓뎅?대줈 ?듬??쒕떎.\n"
        "?몃? ??寃?됱씠??異붿륫? 湲덉??섍퀬, ?쒓났??而⑦뀓?ㅽ듃留??ъ슜?쒕떎.\n"
        "而⑦뀓?ㅽ듃???녿뒗 ?댁슜? 紐⑤Ⅸ?ㅺ퀬 留먰븯怨?異붽? ?뺣낫瑜??붿껌?쒕떎.\n"
        "?듬? 援ъ“???ㅼ쓬???곕Ⅸ??\n"
        "1) ?듬?\n"
        "2) 洹쇨굅(?ъ슜???뚯뒪 ?쇰꺼)\n"
        "3) ?ㅼ쓬 ?④퀎(?덉쓣 ?뚮쭔)\n"
    )

    if mode == "jenkins":
        mode_hint = (
            "?꾩옱 Jenkins CI/CD ?뚯씠?꾨씪??遺꾩꽍 紐⑤뱶?대떎. "
            "鍮뚮뱶 ?ㅽ뙣 ?먯씤, ?뚯씠?꾨씪??蹂듦뎄 諛⑸쾿, PRQA/VectorCAST 寃곌낵 ?댁꽍??吏묒쨷?쒕떎.\n"
        )
    else:
        mode_hint = (
            "?꾩옱 濡쒖뺄 鍮뚮뱶/?뚯뒪??遺꾩꽍 紐⑤뱶?대떎. "
            "?뚯뒪??而ㅻ쾭由ъ? ?μ긽, ?뺤쟻遺꾩꽍 ?댁뒋 ?섏젙, 鍮뚮뱶 ?ㅻ쪟 ?닿껐??吏묒쨷?쒕떎.\n"
        )

    if current_view == "editor":
        view_hint = (
            "?ъ슜?먭? ?먮뵒??酉곗뿉 ?덈떎. 肄붾뱶 ?섏젙, ?댁뒋 ?닿껐, 由ы뙥?좊쭅 媛?대뱶瑜?援ъ껜?곸쑝濡??쒓났?쒕떎. "
            "媛?ν븯硫?肄붾뱶 釉붾줉?쇰줈 ?섏젙 ?덉떆瑜?蹂댁뿬以??\n"
        )
    elif current_view == "workflow":
        view_hint = (
            "?ъ슜?먭? ?뚰겕?뚮줈??酉곗뿉 ?덈떎. ?뚰겕?뚮줈???ㅽ뻾 ?곹깭 ?댁꽍, ?몃윭釉붿뒋?? "
            "?ㅼ쓬 ?ㅽ뻾 ?④퀎瑜??덈궡?쒕떎.\n"
        )
    else:
        view_hint = (
            "?ъ슜?먭? ??쒕낫??酉곗뿉 ?덈떎. ?붿빟 ?곗씠???댁꽍, 硫뷀듃由??ㅻ챸, "
            "?곗꽑?쒖쐞 湲곕컲 ?ㅼ쓬 ?④퀎瑜?異붿쿇?쒕떎.\n"
        )

    messages: List[Dict[str, str]] = [{"role": "system", "content": base_prompt + mode_hint + view_hint}]
    for msg in (history or [])[-16:]:
        role = msg.get("role") or "user"
        text = msg.get("text") or ""
        if not text.strip():
            continue
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": text})

    user_prompt = f"吏덈Ц: {question}\n\n而⑦뀓?ㅽ듃:\n{context}\n"
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _run_llm_candidates(
    *,
    cfg: Dict[str, Any],
    cfg_candidates: List[Dict[str, Any]],
    messages: List[Dict[str, str]],
) -> Tuple[str, Dict[str, Any], str, float]:
    llm_started = time.perf_counter()
    candidate_cfgs: List[Dict[str, Any]] = []
    seen_cfgs = set()
    for item in ([cfg] + list(cfg_candidates or [])):
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("model") or ""),
            str(item.get("api_type") or ""),
            str(item.get("base_url") or ""),
        )
        if key in seen_cfgs:
            continue
        seen_cfgs.add(key)
        candidate_cfgs.append(item)

    agent_result: Dict[str, Any] = {}
    answer = ""
    last_llm_error = ""
    selected_cfg = cfg
    blocked_api_types = set()
    for candidate_cfg in candidate_cfgs or [cfg]:
        api_type = str(candidate_cfg.get("api_type") or "").strip().lower()
        if api_type and api_type in blocked_api_types:
            continue
        selected_cfg = candidate_cfg
        agent_result = agent_call(candidate_cfg, messages, log_dir=None, role="assistant", stage="chat_assistant")
        answer = str(agent_result.get("output") or "").strip()
        attempts = agent_result.get("attempts") or []
        if attempts and isinstance(attempts[-1], dict):
            llm_meta = attempts[-1].get("llm_meta") or {}
            if isinstance(llm_meta, dict):
                last_llm_error = str(llm_meta.get("error") or "").strip().lower()
        if last_llm_error in ("network_denied", "missing_api_key", "gemini_sdk_missing") and api_type:
            blocked_api_types.add(api_type)
        if answer:
            break
    return answer, selected_cfg, last_llm_error, (time.perf_counter() - llm_started) * 1000.0


def answer_chat(
    *,
    mode: str,
    question: str,
    report_dir: Optional[str],
    session_id: Optional[str],
    llm_model: Optional[str],
    oai_config_path: Optional[str],
    ui_context: Optional[Dict[str, Any]],
    history: Optional[List[Dict[str, str]]],
    jenkins_job_url: Optional[str] = None,
    jenkins_cache_root: Optional[str] = None,
    jenkins_build_selector: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    total_started = time.perf_counter()
    if not question or not question.strip():
        return {
            "ok": False,
            "request_id": "",
            "thread_id": "",
            "answer": "吏덈Ц??鍮꾩뼱 ?덉뒿?덈떎.",
            "sources": [],
            "citations": [],
            "evidence": [],
            "next_steps": [],
            "structured": {"answer": "", "evidence": [], "next_steps": []},
            "approval_required": False,
            "approval_request": None,
        }
    question_type = _classify_question(question, mode, str((ui_context or {}).get("current_view", "dashboard")))
    resolved_report_dir = _resolve_report_dir(report_dir, session_id)
    state = new_chat_graph_state(
        mode=mode,
        question=question,
        session_id=session_id,
        report_dir=str(resolved_report_dir) if resolved_report_dir else None,
        ui_context=ui_context,
        history=history,
    )
    state.intent = question_type
    state.selected_model = str(llm_model or "")
    context_elapsed_ms = 0.0
    llm_elapsed_ms = 0.0
    selected_cfg: Dict[str, Any] = {}
    sources: List[str] = []
    citations: List[Dict[str, Any]] = []
    context = ""
    prompt_chars = 0
    last_llm_error = ""

    def _node_classify(_state):
        return {"intent": question_type}

    def _node_build_context(_state):
        nonlocal context_elapsed_ms, sources, context, citations
        started = time.perf_counter()
        context, sources, citations = _build_context(
            mode=mode,
            question=question,
            report_dir=resolved_report_dir,
            ui_context=ui_context,
            jenkins_job_url=jenkins_job_url,
            jenkins_cache_root=jenkins_cache_root,
            jenkins_build_selector=jenkins_build_selector,
            progress_callback=progress_callback,
            graph_state=_state,
        )
        context_elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "citations": citations,
            "evidence": _build_evidence(citations=citations, sources=sources),
            "metrics": {**_state.metrics, "context_ms": round(context_elapsed_ms, 1)},
            "extra": {**_state.extra, "context": context, "sources": list(sources)},
        }

    def _node_select_model(_state):
        cfg_path = str(oai_config_path or getattr(config, "DEFAULT_OAI_CONFIG_PATH", None) or "").strip() or None
        cfg = load_oai_config(cfg_path)
        cfg_candidates = load_oai_configs(cfg_path)
        if not cfg:
            return {"errors": [{"code": "missing_llm_config", "message": "LLM config not available"}]}
        cfg, cfg_candidates = _prioritize_model_candidates(cfg, cfg_candidates, llm_model or "")
        return {
            "selected_model": str(cfg.get("model") or ""),
            "extra": {
                **_state.extra,
                "cfg": cfg,
                "cfg_candidates": cfg_candidates,
            },
        }

    def _node_approval_gate(_state):
        approval_request = _build_approval_request(
            question=question,
            question_type=question_type,
            ui_context=ui_context,
        )
        if not approval_request:
            return {
                "approval_required": False,
                "approval_request": None,
            }
        _state.approval_required = True
        _state.approval_request = dict(approval_request)
        save_pending_approval(
            approval_request["approval_id"],
            {
                "request_id": _state.request_id,
                "thread_id": _state.thread_id,
                "mode": mode,
                "question": question,
                "report_dir": report_dir,
                "session_id": session_id,
                "llm_model": llm_model,
                "oai_config_path": oai_config_path,
                "ui_context": ui_context or {},
                "history": list(history or []),
                "jenkins_job_url": jenkins_job_url,
                "jenkins_cache_root": jenkins_cache_root,
                "jenkins_build_selector": jenkins_build_selector,
                "approval_request": approval_request,
            },
        )
        emit_graph_event(
            progress_callback,
            event_type="approval_required",
            state=_state,
            payload={"approval_request": approval_request},
        )
        return {
            "approval_required": True,
            "approval_request": approval_request,
        }

    def _node_llm_answer(_state):
        nonlocal llm_elapsed_ms, selected_cfg, prompt_chars, last_llm_error
        if _state.errors or _state.approval_required:
            return {}
        current_view = str((ui_context or {}).get("current_view", "dashboard"))
        messages = _build_chat_messages(
            mode=mode,
            current_view=current_view,
            question=question,
            context=context,
            history=history,
        )
        prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        answer_text, selected_cfg, last_llm_error, llm_elapsed_ms = _run_llm_candidates(
            cfg=dict(_state.extra.get("cfg") or {}),
            cfg_candidates=list(_state.extra.get("cfg_candidates") or []),
            messages=messages,
        )
        return {
            "answer": answer_text,
            "metrics": {
                **_state.metrics,
                "prompt_chars": prompt_chars,
                "llm_ms": round(llm_elapsed_ms, 1),
            },
        }

    nodes = [
        ("classify_intent", _node_classify),
        ("build_context", _node_build_context),
        ("select_model", _node_select_model),
        ("approval_gate", _node_approval_gate),
        ("llm_answer", _node_llm_answer),
    ]
    state = run_chat_graph(initial_state=state, nodes=nodes, event_callback=progress_callback)

    if state.errors:
        fallback = "?꾩옱 LLM ?ㅼ젙??遺덈윭?ㅼ? 紐삵뻽?듬땲?? ?대? 由ы룷??濡쒓렇 湲곕컲?쇰줈 異붽? ?뺣낫瑜??쒓났??二쇱꽭??"
        return {
            "ok": False,
            "request_id": state.request_id,
            "thread_id": state.thread_id,
            "answer": fallback,
            "sources": sources,
            "citations": citations,
            "evidence": evidence,
            "next_steps": _default_next_steps(question_type),
            "structured": {"answer": fallback, "evidence": [], "next_steps": _default_next_steps(question_type)},
            "approval_required": bool(state.approval_required),
            "approval_request": state.approval_request,
        }

    if state.approval_required and state.approval_request:
        approval_message = "승인이 필요한 작업입니다. 승인 후 같은 요청을 이어서 실행할 수 있습니다."
        return {
            "ok": True,
            "request_id": state.request_id,
            "thread_id": state.thread_id,
            "answer": approval_message,
            "sources": sources,
            "citations": citations,
            "evidence": _build_evidence(citations=citations, sources=sources),
            "next_steps": ["작업 내용을 검토합니다.", "승인 또는 거절을 선택합니다."],
            "approval_required": True,
            "approval_request": state.approval_request,
            "structured": {
                "answer": approval_message,
                "evidence": [],
                "next_steps": ["작업 내용을 검토합니다.", "승인 또는 거절을 선택합니다."],
            },
        }

    answer = state.answer
    if not answer:
        if last_llm_error == "network_denied":
            report_fallback = _build_context_fallback_answer(
                question=question,
                question_type=question_type,
                report_dir=resolved_report_dir,
                ui_context=ui_context,
                citations=citations,
            )
            answer = (
                "현재 LLM 네트워크 연결이 차단되어 리포트 기반 대체 응답으로 전환했습니다. "
                + report_fallback
            )
            emit_graph_event(
                progress_callback,
                event_type="degraded_mode",
                state=state,
                payload={"reason": "network_denied"},
            )
        else:
            answer = "?꾩옱 ?묐떟???앹꽦?섏? 紐삵뻽?듬땲?? 吏덈Ц??議곌툑 ??援ъ껜?뷀빐 二쇱꽭??"

    if answer:
        parsed_answer = _parse_structured_answer_payload(answer)
        answer = _normalize_chat_answer_text(answer)
    else:
        parsed_answer = {"answer": "", "evidence": [], "next_steps": []}

    if _CHAT_PERF_LOG:
        _chat_perf_logger.info(
            (
                "chat_request mode=%s session_id=%s report_dir=%s model=%s "
                "question_chars=%d history_turns=%d context_chars=%d prompt_chars=%d "
                "sources=%d context_ms=%.1f llm_ms=%.1f total_ms=%.1f"
            ),
            mode,
            session_id or "",
            str(resolved_report_dir) if resolved_report_dir else "",
            str(selected_cfg.get("model") or ""),
            len(question or ""),
            len((history or [])[-16:]),
            len(context or ""),
            prompt_chars,
            len(sources),
            context_elapsed_ms,
            llm_elapsed_ms,
            (time.perf_counter() - total_started) * 1000.0,
        )

    evidence = _build_evidence(citations=citations, sources=sources)
    llm_evidence = [
        {
            "id": f"llm-evidence-{idx}",
            "title": f"model_evidence_{idx}",
            "source_type": "model",
            "uri": "",
            "path": "",
            "snippet": str(item),
            "source": "llm",
        }
        for idx, item in enumerate((parsed_answer.get("evidence") or []), start=1)
        if str(item).strip()
    ]
    combined_evidence = llm_evidence + evidence
    next_steps = list(parsed_answer.get("next_steps") or []) or _default_next_steps(question_type)
    return {
        "ok": True,
        "request_id": state.request_id,
        "thread_id": state.thread_id,
        "answer": answer.strip(),
        "sources": sources,
        "citations": citations,
        "evidence": combined_evidence,
        "next_steps": next_steps,
        "approval_required": bool(state.approval_required),
        "approval_request": state.approval_request,
        "structured": {
            "answer": str(parsed_answer.get("answer") or answer).strip(),
            "evidence": [item.get("snippet") or item.get("title") or "" for item in combined_evidence if (item.get("snippet") or item.get("title"))],
            "next_steps": next_steps,
        },
    }

