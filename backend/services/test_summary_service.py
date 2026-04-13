"""테스트 결과 자동 요약 서비스

VectorCAST 파서 결과를 기반으로 실패 분류, 유닛별 분석, 품질 게이트,
트렌드 분석, executive summary를 생성합니다.
ISO 26262 심사 증거로 사용 가능한 수준의 구조화된 보고서를 제공합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

_FAILURE_PATTERNS: Dict[str, List[str]] = {
    "assertion": ["MISMATCH", "EXPECTED", "ASSERT", "!=", "NOT EQUAL"],
    "timeout": ["TIMEOUT", "TIME_OUT", "TIMED OUT", "DEADLINE"],
    "crash": ["CRASH", "ABORT", "SEGFAULT", "EXCEPTION", "ACCESS VIOLATION",
              "SIGNAL", "CORE DUMP", "STACK OVERFLOW"],
    "environment": ["ENV", "SETUP", "CONFIG", "LICENSE", "CONNECTION",
                    "FILE NOT FOUND", "MISSING", "INITIALIZATION"],
}


def classify_failure(row: Dict[str, Any]) -> str:
    """Classify a failed test row into a failure category.

    Args:
        row: dict with at least 'result' key, optionally 'actual_result', 'description'

    Returns:
        One of: 'assertion', 'timeout', 'crash', 'environment', 'unknown'
    """
    texts = []
    for key in ("result", "actual_result", "description", "error_message"):
        val = row.get(key)
        if val:
            texts.append(str(val).upper())
    combined = " ".join(texts)

    for category, patterns in _FAILURE_PATTERNS.items():
        if any(pat in combined for pat in patterns):
            return category
    return "unknown"


def classify_failures_bulk(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Classify all failed rows and return category counts."""
    counts: Dict[str, int] = {
        "assertion": 0, "timeout": 0, "crash": 0, "environment": 0, "unknown": 0,
    }
    for row in rows:
        status = _normalize_result(row.get("result"))
        if status == "fail":
            cat = classify_failure(row)
            counts[cat] = counts.get(cat, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Unit / subprogram breakdown
# ---------------------------------------------------------------------------

def build_unit_breakdown(test_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build per-unit pass/fail/skip breakdown from VectorCAST test results.

    Args:
        test_results: dict keyed by test case name, values are lists of
                      TestResultItem-like dicts with 'header.unit_name' and 'passed'

    Returns:
        List of dicts: [{unit_name, passed, failed, total, pass_rate}, ...]
    """
    units: Dict[str, Dict[str, int]] = {}

    for tc_name, results in test_results.items():
        if not isinstance(results, list):
            results = [results]
        for item in results:
            # Support both dataclass and dict
            if hasattr(item, "header"):
                unit_name = item.header.unit_name if hasattr(item.header, "unit_name") else "UNKNOWN"
                is_passed = item.passed if hasattr(item, "passed") else False
            elif isinstance(item, dict):
                header = item.get("header") or {}
                unit_name = header.get("unit_name", "UNKNOWN") if isinstance(header, dict) else "UNKNOWN"
                is_passed = item.get("passed", False)
            else:
                continue

            if unit_name not in units:
                units[unit_name] = {"passed": 0, "failed": 0}
            if is_passed:
                units[unit_name]["passed"] += 1
            else:
                units[unit_name]["failed"] += 1

    result = []
    for uname, counts in sorted(units.items()):
        total = counts["passed"] + counts["failed"]
        result.append({
            "unit_name": uname,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "total": total,
            "pass_rate": counts["passed"] / total if total > 0 else 0.0,
        })
    return result


def build_subprogram_breakdown(
    statement_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build per-subprogram coverage breakdown from VectorCAST metrics.

    Args:
        statement_data: dict keyed by unit name, values are MatixDataBank-like
                        objects with dic_data containing MatricStatementItem

    Returns:
        List of dicts with coverage details per subprogram
    """
    result = []
    for unit_name, bank in statement_data.items():
        dic_data = bank.dic_data if hasattr(bank, "dic_data") else (
            bank.get("dic_data", {}) if isinstance(bank, dict) else {}
        )
        for sub_name, item in dic_data.items():
            stmts = _extract_coverage(item, "statements")
            branches = _extract_coverage(item, "branches")
            result.append({
                "unit_name": unit_name,
                "subprogram": sub_name,
                "stmt_count": stmts[0],
                "stmt_total": stmts[1],
                "stmt_pct": stmts[0] / stmts[1] * 100 if stmts[1] > 0 else 0.0,
                "branch_count": branches[0],
                "branch_total": branches[1],
                "branch_pct": branches[0] / branches[1] * 100 if branches[1] > 0 else 0.0,
            })
    return result


# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Single quality gate evaluation result."""
    name: str
    actual: float
    threshold: float
    status: str  # "pass", "warn", "fail"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "actual": self.actual,
                "threshold": self.threshold, "status": self.status}


DEFAULT_TEST_QUALITY_GATES = {
    "pass_rate_min": 95.0,
    "coverage_line_min": 80.0,
    "coverage_branch_min": 70.0,
    "max_new_failures": 0,
}


def evaluate_quality_gates(
    summary: Dict[str, Any],
    gates: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Evaluate test quality gates against summary metrics.

    Args:
        summary: dict with keys like 'pass_rate', 'coverage_line', 'coverage_branch',
                 'new_failures' (from build_report_summary or _summarize_vcast_tests)
        gates: threshold dict, defaults to DEFAULT_TEST_QUALITY_GATES

    Returns:
        {"overall_pass": bool, "gates": [GateResult.to_dict(), ...]}
    """
    gates = gates or DEFAULT_TEST_QUALITY_GATES
    results: List[GateResult] = []

    # Pass rate
    pass_rate = summary.get("pass_rate", 0.0)
    if isinstance(pass_rate, (int, float)) and pass_rate <= 1.0:
        pass_rate *= 100  # normalize 0-1 to 0-100
    threshold = gates.get("pass_rate_min", 95.0)
    results.append(GateResult(
        name="테스트 통과율",
        actual=round(pass_rate, 1),
        threshold=threshold,
        status="pass" if pass_rate >= threshold else "fail",
    ))

    # Line coverage
    line_cov = _extract_pct(summary, "coverage_line", "line_rate",
                            "kpis.coverage.line_rate")
    threshold = gates.get("coverage_line_min", 80.0)
    results.append(GateResult(
        name="라인 커버리지",
        actual=round(line_cov, 1),
        threshold=threshold,
        status="pass" if line_cov >= threshold else (
            "warn" if line_cov >= threshold * 0.8 else "fail"),
    ))

    # Branch coverage
    branch_cov = _extract_pct(summary, "coverage_branch", "branch_rate",
                              "kpis.coverage.branch_rate")
    threshold = gates.get("coverage_branch_min", 70.0)
    results.append(GateResult(
        name="분기 커버리지",
        actual=round(branch_cov, 1),
        threshold=threshold,
        status="pass" if branch_cov >= threshold else (
            "warn" if branch_cov >= threshold * 0.8 else "fail"),
    ))

    # New failures
    new_failures = summary.get("new_failures", 0)
    max_new = gates.get("max_new_failures", 0)
    results.append(GateResult(
        name="신규 실패",
        actual=float(new_failures),
        threshold=float(max_new),
        status="pass" if new_failures <= max_new else "fail",
    ))

    overall = all(g.status != "fail" for g in results)
    return {
        "overall_pass": overall,
        "gates": [g.to_dict() for g in results],
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def build_trend_analysis(
    current: Dict[str, Any],
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare current test results against a previous run.

    Returns:
        dict with deltas, new failures, resolved failures
    """
    if not previous:
        return {"available": False, "message": "이전 빌드 데이터 없음"}

    cur_rate = _safe_float(current.get("pass_rate", 0))
    prev_rate = _safe_float(previous.get("pass_rate", 0))
    cur_total = current.get("total", 0)
    prev_total = previous.get("total", 0)
    cur_failed = current.get("failed", 0)
    prev_failed = previous.get("failed", 0)

    return {
        "available": True,
        "pass_rate_delta": round(cur_rate - prev_rate, 2),
        "total_delta": cur_total - prev_total,
        "failed_delta": cur_failed - prev_failed,
        "new_failures": max(0, cur_failed - prev_failed),
        "resolved_failures": max(0, prev_failed - cur_failed),
        "improved": cur_rate >= prev_rate,
    }


# ---------------------------------------------------------------------------
# Requirement-Test linkage
# ---------------------------------------------------------------------------

_REQ_PATTERN = re.compile(r"(?:SwTR|SwFn|SwUFn|SwTC|SRS)[-_]\w+", re.IGNORECASE)


def build_requirement_test_map(
    test_data: Dict[str, Any],
) -> Dict[str, List[str]]:
    """Build requirement_id → [test_case_name, ...] map.

    Scans test case names, descriptions, and notes for requirement ID patterns.
    """
    req_map: Dict[str, List[str]] = {}
    for tc_name, items in test_data.items():
        if not isinstance(items, list):
            items = [items]
        for item in items:
            text = tc_name
            if hasattr(item, "description"):
                text += " " + (item.description or "")
            elif isinstance(item, dict):
                text += " " + str(item.get("description", ""))
            for m in _REQ_PATTERN.finditer(text):
                req_id = m.group(0)
                if req_id not in req_map:
                    req_map[req_id] = []
                if tc_name not in req_map[req_id]:
                    req_map[req_id].append(tc_name)
    return req_map


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

def generate_executive_summary(
    test_summary: Dict[str, Any],
    quality_gates: Optional[Dict[str, Any]] = None,
    unit_breakdown: Optional[List[Dict[str, Any]]] = None,
    failure_categories: Optional[Dict[str, int]] = None,
    trend: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate ISO 26262 evidence-grade executive summary.

    Returns structured summary with all sections needed for audit evidence.
    """
    total = test_summary.get("total", 0)
    passed = test_summary.get("passed", 0)
    failed = test_summary.get("failed", 0)
    skipped = test_summary.get("skipped", 0)
    pass_rate = test_summary.get("pass_rate", 0.0)
    if isinstance(pass_rate, (int, float)) and pass_rate <= 1.0:
        pass_rate *= 100

    # Overall verdict
    gates_pass = quality_gates.get("overall_pass", True) if quality_gates else True
    if gates_pass and failed == 0:
        verdict = "PASS"
        verdict_text = "모든 테스트 통과, 품질 게이트 충족"
    elif gates_pass:
        verdict = "PASS_WITH_ISSUES"
        verdict_text = f"품질 게이트 충족, {failed}건 실패 존재"
    else:
        verdict = "FAIL"
        failed_gates = [g["name"] for g in (quality_gates or {}).get("gates", [])
                        if g.get("status") == "fail"]
        verdict_text = f"품질 게이트 미충족: {', '.join(failed_gates)}"

    # Worst units
    worst_units = []
    if unit_breakdown:
        failed_units = [u for u in unit_breakdown if u["failed"] > 0]
        worst_units = sorted(failed_units, key=lambda u: u["pass_rate"])[:5]

    # Failure analysis
    failure_summary = ""
    if failure_categories:
        parts = [f"{cat}: {cnt}건" for cat, cnt in failure_categories.items() if cnt > 0]
        failure_summary = ", ".join(parts) if parts else "실패 없음"

    # Trend
    trend_text = ""
    if trend and trend.get("available"):
        delta = trend.get("pass_rate_delta", 0)
        if delta > 0:
            trend_text = f"이전 빌드 대비 통과율 +{delta:.1f}% 개선"
        elif delta < 0:
            trend_text = f"이전 빌드 대비 통과율 {delta:.1f}% 하락"
        else:
            trend_text = "이전 빌드 대비 변화 없음"

    return {
        "generated_at": datetime.now().isoformat(),
        "verdict": verdict,
        "verdict_text": verdict_text,
        "metrics": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate_pct": round(pass_rate, 1),
        },
        "quality_gates": quality_gates,
        "failure_analysis": {
            "categories": failure_categories or {},
            "summary": failure_summary,
        },
        "worst_units": worst_units,
        "trend": trend or {"available": False},
        "trend_text": trend_text,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_result(value: Any) -> str:
    """Normalize test result to pass/fail/skip/unknown."""
    raw = str(value or "").strip().upper()
    if any(tok in raw for tok in ("PASS", "OK", "SUCCESS")):
        return "pass"
    if any(tok in raw for tok in ("SKIP", "SKIPPED", "N/A", "NOT RUN", "NOTRUN")):
        return "skip"
    if any(tok in raw for tok in ("FAIL", "ERROR", "NG", "FATAL")):
        return "fail"
    return "unknown"


def _extract_coverage(item: Any, attr: str) -> Tuple[int, int]:
    """Extract (count, total) from a coverage attribute."""
    cov = getattr(item, attr, None) if hasattr(item, attr) else (
        item.get(attr) if isinstance(item, dict) else None
    )
    if cov is None:
        return (0, 0)
    if hasattr(cov, "count"):
        return (cov.count, cov.total)
    if isinstance(cov, dict):
        return (cov.get("count", 0), cov.get("total", 0))
    return (0, 0)


def _extract_pct(summary: Dict[str, Any], *keys: str) -> float:
    """Extract percentage from summary dict, trying multiple key paths."""
    for key in keys:
        if "." in key:
            parts = key.split(".")
            val = summary
            for p in parts:
                val = val.get(p, {}) if isinstance(val, dict) else {}
            if isinstance(val, (int, float)):
                return float(val) * 100 if val <= 1.0 else float(val)
        else:
            val = summary.get(key)
            if isinstance(val, (int, float)):
                return float(val) * 100 if val <= 1.0 else float(val)
    return 0.0


def _safe_float(val: Any) -> float:
    try:
        v = float(val)
        return v * 100 if v <= 1.0 else v
    except (TypeError, ValueError):
        return 0.0
