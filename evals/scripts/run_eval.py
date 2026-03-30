from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.assistant_service import _classify_question, answer_chat
from workflow.retrieval import retrieve_contexts


def _load_manifest(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_report_dir(raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    p = (ROOT / text).resolve() if not Path(text).is_absolute() else Path(text).resolve()
    return p


def _domain_counts(hits: List[Dict[str, Any]]) -> Dict[str, int]:
    c = Counter(str(hit.get("domain") or "unknown") for hit in hits)
    return dict(c)


def _score_case(case: Dict[str, Any], answer: str, citations: List[Dict[str, Any]], hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    answer_lower = str(answer or "").lower()
    expected_topics = [str(x).lower() for x in case.get("expected_topics") or []]
    preferred_domains = [str(x).lower() for x in case.get("preferred_domains") or []]
    topic_hits = sum(1 for topic in expected_topics if topic in answer_lower)
    citation_ok = bool(citations) if case.get("must_cite") else True
    hit_domains = {str(hit.get("domain") or "").lower() for hit in hits}
    preferred_domain_ok = bool(hit_domains.intersection(preferred_domains)) if preferred_domains else True
    return {
        "topic_hit_count": topic_hits,
        "topic_expected_count": len(expected_topics),
        "citation_ok": citation_ok,
        "preferred_domain_ok": preferred_domain_ok,
        "pass": citation_ok and preferred_domain_ok and (topic_hits > 0 or not expected_topics),
    }


def main() -> int:
    manifest_path = ROOT / "evals" / "cases" / "baseline_manifest.json"
    results_dir = ROOT / "evals" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(manifest_path)
    run_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = results_dir / f"eval_{run_at}.json"

    cases_out: List[Dict[str, Any]] = []
    for case in manifest:
        question = str(case.get("question") or "")
        mode = str(case.get("mode") or "local")
        report_dir = _resolve_report_dir(str(case.get("report_dir") or ""))
        ui_context = dict(case.get("ui_context") or {})
        question_type = _classify_question(question, mode, str(ui_context.get("current_view") or "dashboard"))

        retrieval_started = time.perf_counter()
        hits = retrieve_contexts(
            question=question,
            question_type=question_type,
            report_dir=report_dir,
            ui_context=ui_context,
            top_k=6,
        )
        retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000.0, 1)

        answer_started = time.perf_counter()
        answer_result = answer_chat(
            mode=mode,
            question=question,
            report_dir=str(report_dir) if report_dir else None,
            session_id=None,
            llm_model=None,
            oai_config_path=None,
            ui_context=ui_context,
            history=[],
        )
        answer_ms = round((time.perf_counter() - answer_started) * 1000.0, 1)

        answer_text = str(answer_result.get("answer") or "")
        citations = list(answer_result.get("citations") or [])
        score = _score_case(case, answer_text, citations, hits)

        cases_out.append(
            {
                "id": case.get("id"),
                "question": question,
                "question_type": question_type,
                "report_dir": str(report_dir) if report_dir else "",
                "retrieval_ms": retrieval_ms,
                "answer_ms": answer_ms,
                "retrieval_hit_count": len(hits),
                "retrieval_domains": _domain_counts(hits),
                "sources": list(answer_result.get("sources") or []),
                "citations_count": len(citations),
                "answer_preview": answer_text[:500],
                "score": score,
            }
        )

    summary = {
        "run_at": run_at,
        "case_count": len(cases_out),
        "pass_count": sum(1 for case in cases_out if case.get("score", {}).get("pass")),
        "avg_retrieval_ms": round(sum(case["retrieval_ms"] for case in cases_out) / max(1, len(cases_out)), 1),
        "avg_answer_ms": round(sum(case["answer_ms"] for case in cases_out) / max(1, len(cases_out)), 1),
    }
    payload = {"summary": summary, "cases": cases_out}
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False))
    print(str(result_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
