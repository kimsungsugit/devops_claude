# workflow/iso26262_checker.py
"""ISO 26262 Part 6 (Software Development) compliance auto-checker.

Verifies that generated UDS/STS/SUTS documents meet ISO 26262 Part 6
required items for automotive safety software documentation.

Reference: ISO 26262-6:2018 Tables 1-12 (software development work products)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ISO 26262-6 Table 1: Software safety requirements specification
SRS_CHECKLIST = [
    {"id": "SRS-01", "desc": "Each requirement has a unique ID", "field": "id"},
    {"id": "SRS-02", "desc": "ASIL level assigned to each requirement", "field": "asil"},
    {"id": "SRS-03", "desc": "Verification criteria defined", "field": "verification"},
    {"id": "SRS-04", "desc": "Traceability to system requirements (Related ID)", "field": "related_id"},
]

# ISO 26262-6 Table 5: Software unit design specification (UDS)
UDS_CHECKLIST = [
    {"id": "UDS-01", "desc": "Function ID assigned (SwUFn_xxx)", "field": "id"},
    {"id": "UDS-02", "desc": "Function name specified", "field": "name"},
    {"id": "UDS-03", "desc": "Function description present", "field": "description"},
    {"id": "UDS-04", "desc": "Input parameters documented", "field": "inputs"},
    {"id": "UDS-05", "desc": "Output parameters documented", "field": "outputs"},
    {"id": "UDS-06", "desc": "Preconditions specified", "field": "precondition"},
    {"id": "UDS-07", "desc": "ASIL classification present", "field": "asil"},
    {"id": "UDS-08", "desc": "Call relationships documented (called/calling)", "field": "called"},
    {"id": "UDS-09", "desc": "Traceability to requirements (related)", "field": "related"},
    {"id": "UDS-10", "desc": "Global/static variable usage documented", "field": "globals_global"},
    {"id": "UDS-11", "desc": "Logic flow / control flow documented", "field": "logic"},
    {"id": "UDS-12", "desc": "Component assignment (SwCom)", "field": "module_name"},
]

# ISO 26262-6 Table 9: Software unit test specification (STS/SUTS)
TEST_CHECKLIST = [
    {"id": "TST-01", "desc": "Test case ID assigned", "field": "tc_id"},
    {"id": "TST-02", "desc": "Requirement traceability (req_id)", "field": "req_id"},
    {"id": "TST-03", "desc": "Test method defined", "field": "test_method"},
    {"id": "TST-04", "desc": "Test steps present", "field": "steps"},
    {"id": "TST-05", "desc": "Expected results defined", "field": "expected"},
    {"id": "TST-06", "desc": "Test environment specified", "field": "test_env"},
]


def _check_field_present(item: Dict[str, Any], field: str) -> bool:
    """Check if a field is present and non-empty."""
    val = item.get(field)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip()) and val.strip().upper() not in ("N/A", "-", "")
    if isinstance(val, (list, dict)):
        return len(val) > 0
    return True


def verify_uds_compliance(
    function_details: Dict[str, Dict[str, Any]],
    *,
    asil_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify UDS function details against ISO 26262-6 Table 5 checklist.

    Args:
        function_details: Dict of fid -> function info
        asil_filter: If set, only check functions with this ASIL level or higher

    Returns:
        Compliance report with per-item and per-function results
    """
    asil_order = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    min_level = asil_order.get((asil_filter or "").upper(), 0)

    total_functions = 0
    item_pass_counts: Dict[str, int] = {c["id"]: 0 for c in UDS_CHECKLIST}
    item_fail_details: Dict[str, List[str]] = {c["id"]: [] for c in UDS_CHECKLIST}
    function_scores: List[Dict[str, Any]] = []

    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue

        fn_asil = str(info.get("asil", "QM")).upper().replace("ASIL-", "").replace("ASIL", "").strip()
        if fn_asil not in asil_order:
            fn_asil = "QM"
        if asil_order.get(fn_asil, 0) < min_level:
            continue

        total_functions += 1
        fn_name = info.get("name", fid)
        fn_pass = 0
        fn_total = len(UDS_CHECKLIST)

        for check in UDS_CHECKLIST:
            if _check_field_present(info, check["field"]):
                item_pass_counts[check["id"]] += 1
                fn_pass += 1
            else:
                item_fail_details[check["id"]].append(fn_name)

        function_scores.append({
            "fid": fid,
            "name": fn_name,
            "asil": fn_asil,
            "score": fn_pass / fn_total if fn_total > 0 else 0,
            "pass": fn_pass,
            "total": fn_total,
        })

    checklist_results = []
    for check in UDS_CHECKLIST:
        cid = check["id"]
        passed = item_pass_counts[cid]
        rate = passed / total_functions if total_functions > 0 else 0
        checklist_results.append({
            "id": cid,
            "description": check["desc"],
            "field": check["field"],
            "pass_count": passed,
            "total": total_functions,
            "compliance_rate": round(rate * 100, 1),
            "status": "PASS" if rate >= 0.95 else ("WARN" if rate >= 0.7 else "FAIL"),
            "failing_functions": item_fail_details[cid][:10],
        })

    overall_score = sum(r["compliance_rate"] for r in checklist_results) / len(checklist_results) if checklist_results else 0

    low_score_fns = sorted(function_scores, key=lambda x: x["score"])[:10]

    return {
        "standard": "ISO 26262-6:2018",
        "section": "Table 5 - Software unit design specification",
        "total_functions": total_functions,
        "asil_filter": asil_filter,
        "overall_compliance": round(overall_score, 1),
        "overall_status": "PASS" if overall_score >= 95 else ("WARN" if overall_score >= 70 else "FAIL"),
        "checklist": checklist_results,
        "lowest_scoring_functions": low_score_fns,
    }


def verify_test_compliance(
    test_cases: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Verify STS/SUTS test cases against ISO 26262-6 Table 9 checklist."""
    total = len(test_cases)
    item_pass_counts: Dict[str, int] = {c["id"]: 0 for c in TEST_CHECKLIST}

    for tc in test_cases:
        for check in TEST_CHECKLIST:
            if _check_field_present(tc, check["field"]):
                item_pass_counts[check["id"]] += 1

    checklist_results = []
    for check in TEST_CHECKLIST:
        cid = check["id"]
        passed = item_pass_counts[cid]
        rate = passed / total if total > 0 else 0
        checklist_results.append({
            "id": cid,
            "description": check["desc"],
            "pass_count": passed,
            "total": total,
            "compliance_rate": round(rate * 100, 1),
            "status": "PASS" if rate >= 0.95 else ("WARN" if rate >= 0.7 else "FAIL"),
        })

    overall = sum(r["compliance_rate"] for r in checklist_results) / len(checklist_results) if checklist_results else 0

    return {
        "standard": "ISO 26262-6:2018",
        "section": "Table 9 - Software test specification",
        "total_test_cases": total,
        "overall_compliance": round(overall, 1),
        "overall_status": "PASS" if overall >= 95 else ("WARN" if overall >= 70 else "FAIL"),
        "checklist": checklist_results,
    }


def generate_iso26262_report(
    function_details: Dict[str, Dict[str, Any]],
    test_cases: Optional[List[Dict[str, Any]]] = None,
    *,
    asil_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a combined ISO 26262-6 compliance report."""
    uds_report = verify_uds_compliance(function_details, asil_filter=asil_filter)

    report: Dict[str, Any] = {
        "standard": "ISO 26262-6:2018",
        "uds_compliance": uds_report,
    }

    if test_cases:
        test_report = verify_test_compliance(test_cases)
        report["test_compliance"] = test_report

    uds_score = uds_report["overall_compliance"]
    test_score = report.get("test_compliance", {}).get("overall_compliance", 0)

    if test_cases:
        combined = (uds_score + test_score) / 2
    else:
        combined = uds_score

    report["combined_compliance"] = round(combined, 1)
    report["combined_status"] = "PASS" if combined >= 95 else ("WARN" if combined >= 70 else "FAIL")

    logger.info("ISO 26262-6 compliance: UDS=%.1f%%, Tests=%.1f%%, Combined=%.1f%% [%s]",
                uds_score, test_score, combined, report["combined_status"])

    return report
