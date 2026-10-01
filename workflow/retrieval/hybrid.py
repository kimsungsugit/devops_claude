from __future__ import annotations

import json
import logging
import re
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


# (R53) the STS generation findings (`scripts/sts_findings_to_kb.py`): the shared KB, never a session's — the chat's
#   ``report_dir`` is ``reports/sessions/<thread>`` whose KB never holds them (review C1: 16 of 16 question/mode paths
#   missed them). One category, so the local UDS AI (categories uds · requirements · code) does not take them in. Asked
#   only for the requirement / HW IDs a question names, and only entries that carry one (tag or text — r3 W2;
#   review r2 W-A: '문서' in any question matched every review title) — the chat puts them
#   in a block of their own (`assistant_service`).
# (R53 review r3 W1) an ID followed by a Korean particle (``SwTSR_0104는``) or written in lower case — Python's ``\w``
#   holds Hangul, so ``\b`` fails between ``4`` and ``는``
REQUIREMENT_ID = re.compile(r"(?<![A-Za-z0-9_])(?:Sw|Sy|Hw)[A-Za-z]{1,6}_\d+(?:_\d+)?(?![A-Za-z0-9_])", re.IGNORECASE)
FINDINGS_PER_QUESTION = 4


def _findings_category() -> str:
    import config
    return str(getattr(config, "RAG_STS_FINDINGS_CATEGORY", "sts_findings"))


def _shared_report_dir() -> Path:
    """`config.DEFAULT_REPORT_DIR` against the repository root (config.py's folder), never the process CWD."""
    import config
    base = Path(getattr(config, "DEFAULT_REPORT_DIR", "reports"))
    return base if base.is_absolute() else Path(config.__file__).resolve().parent / base


def _entry_ids(ent: Dict[str, Any]) -> set:
    """The IDs an entry is about: its tags, and (review r3 W2) every ID its title and body write — the HW blocks of a
    tolerance path, the system blocks of a review item (the tags carry the SRS IDs only)."""
    text = f"{ent.get('error_raw') or ''}\n{ent.get('fix') or ''}"
    return {str(i).casefold() for i in [*(ent.get("tags") or []), *REQUIREMENT_ID.findall(text)]}


# (review r4 I1) what a question's words ask for → the finding kinds (tags of `scripts/sts_findings_to_kb.py` — a
#   test binds the two). (r5 W-A) They come first; (r6 I-1) in two tiers — the words that ask for that kind, then the
#   words a question of that kind usually writes (``초과`` · ``근거``) but so do others: '허용오차' still wins over
#   '초과', and '{ID} 근거는?' finds the boundary evidence again
_ASKED_KIND_LOOSE = (
    (("초과", "미만"), "inclusion_conflict"),
    (("경계", "근거"), "sts_evidence"),
    (("검토",), "review_held_back"),
)
_ASKED_KIND = (
    (("값 차이", "값이 다", "다른 값", "차이"), "value_difference"),
    (("포함", "이상인지", "이하인지"), "inclusion_conflict"),
    (("허용오차", "허용 오차", "감시 경로", "측정 오차", "hw 블록", "hw 감시"), "sts_hw_tolerance"),
    (("경계 근거", "경계값", "경계 값", "경계 점", "스텝"), "sts_evidence"),
    (("검토 필요", "주어", "정하지", "빠진"), "review_held_back"),
    (("결합", " and ", " or "), "review_read"),
)


def _finding_kind(ent: Dict[str, Any]) -> tuple:
    tags = [str(t) for t in (ent.get("tags") or [])]
    project = next((t.split(":", 1)[1] for t in tags if t.startswith("sts_findings:")), tags[0] if tags else "")
    kind = tags[1] if len(tags) > 1 else ""
    return project, kind + (f":{tags[2]}" if kind == "sts_review" and len(tags) > 2 else "")


def requirement_findings_hits(question: str, top_k: int = FINDINGS_PER_QUESTION,
                              notes_out: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """(R53) What STS generation found in the requirement documents about the IDs ``question`` names — review items,
    value differences, inclusion conflicts, boundary evidence, HW tolerance paths — from the shared KB, category
    `config.RAG_STS_FINDINGS_CATEGORY`. ``[]`` when the question names no ID.

    (review r3 W4) The entries about those IDs are taken first (an ID's 31 entries no longer compete with the rest for
    a dozen search places), ranked by the search's score, narrowed to the project the question names (``HDPDM01`` ·
    ``KJPDS02_PV``) when it names one, and picked one per project and kind before a second of any — so the value
    difference asked about is not crowded out by two review items of the same kind."""
    ids = {i.casefold() for i in REQUIREMENT_ID.findall(question or "")}
    if not ids:
        return []
    category = _findings_category()
    try:
        kb = get_kb(_shared_report_dir())
        pool = [dict(e) for e in list(kb.data) if str(e.get("category") or "") == category]
        if not pool:
            # (review r4 I3) a store that keeps no entry list in memory (pgvector) — the ingest refuses it, so its
            #   empty answer is "not loadable here", not "nothing found"
            if notes_out is not None and not str(getattr(kb, "storage", "sqlite") or "sqlite") == "sqlite":
                notes_out.append("요구 문서 발견 사항(STS 생성 결과)은 sqlite 지식베이스에만 적재된다 — 이 저장소에서는 그 근거 없이 "
                                 "답한다.")
            return []
        # (review r4 I2) the entries about the IDs first — a question naming an ID nothing was found about costs no
        #   search (and no query embedding)
        candidates = [e for e in pool if ids & _entry_ids(e)]
        if not candidates:
            return []
        stats: Dict[str, Any] = {}
        ranked = kb.search(question, top_k=len(pool), category=category, stats_out=stats)
    except Exception as exc:
        _logger.warning("요구 문서 발견 사항 검색 실패 — 그 근거 없이 진행한다", exc_info=True)
        if notes_out is not None:      # (review r3 I4) a failed search is not 'nothing found'
            notes_out.append(f"요구 문서 발견 사항(STS 생성 결과) 검색 실패 — {type(exc).__name__}: 그 근거 없이 답한다.")
        return []
    reason = stats.get("semantic_disabled_reason")
    if reason and notes_out is not None and _semantic_note(str(reason)) not in notes_out:   # (review r2 I-1) once
        notes_out.append(_semantic_note(str(reason)))
    score = {str(e.get("id")): float(e.get("score") or e.get("similarity") or e.get("relevance") or 0.0)
             for e in ranked or []}
    asked = question.casefold()
    named = {p for p, _k in map(_finding_kind, candidates) if p and (p.casefold() in asked
                                                                     or p.split("_")[0].casefold() in asked)}
    if named:
        candidates = [e for e in candidates if _finding_kind(e)[0] in named] or candidates
    # (review r4 I1) equal scores (a keyword-only search scores '0104는' as no word) break on the kind the question
    #   asks about, not on the title's alphabet (``[STS HW…`` sorted before every Korean title)
    wanted = {kind for words, kind in _ASKED_KIND if any(w in asked for w in words)}
    loose = {kind for words, kind in _ASKED_KIND_LOOSE if any(w in asked for w in words)} - wanted

    def asked_rank(e: Dict[str, Any]) -> int:
        kind = _finding_kind(e)[1]
        names = {kind, kind.split(":")[-1]}
        return 0 if names & wanted else 1 if names & loose else 2
    candidates.sort(key=lambda e: (-score.get(str(e.get("id")), 0.0), asked_rank(e), str(e.get("error_raw") or "")))
    picked: List[Dict[str, Any]] = []
    seen: set = set()
    # (review r5 W-A) the kind asked about first, then one per project and kind — by score alone '허용오차는?' lost its
    #   HW tolerance entry to four review items scoring higher (8 of 10 such questions on the real KB)
    for e in sorted(candidates, key=asked_rank):      # stable: score order within
        if len(picked) < top_k and _finding_kind(e) not in seen:
            picked.append(e)
            seen.add(_finding_kind(e))
    for e in candidates:
        if len(picked) >= top_k:
            break
        if e not in picked:
            picked.append(e)
    hits: List[Dict[str, Any]] = []
    for idx, ent in enumerate(picked, start=1):
        title = str(ent.get("error_clean") or ent.get("error_raw") or "").strip()
        body = str(ent.get("fix") or "").strip()
        s_ = score.get(str(ent.get("id")), 0.0)
        hits.append({"hit_id": f"requirement-finding-{idx}", "domain": "requirements", "source_type": "kb",
                     "uri": f"kb://{ent.get('id')}", "path": "", "label": title[:200] or category,
                     "metadata": {"id": ent.get("id"), "tags": ent.get("tags") or [], "category": ent.get("category")},
                     "chunk_text": f"{title}\n{body}".strip()[:1200], "score": s_, "rerank_score": s_})
    return hits


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
        # (R53 review r4 I9 · r5 I-4) one KB for all (KB_GLOBAL_DIR): the findings would fill the top places and leave
        #   the reports none — taken wider by as many findings as the KB holds, the findings dropped, then cut
        findings = _findings_category()
        held = sum(1 for e in list(getattr(kb, "data", None) or []) if str(e.get("category") or "") == findings)
        entries = kb.search(question, top_k=top_k + held, stats_out=kb_stats)
        entries = [e for e in entries or [] if str(e.get("category") or "") != findings][:top_k]
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
