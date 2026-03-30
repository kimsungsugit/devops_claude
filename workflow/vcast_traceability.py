# workflow/vcast_traceability.py
"""VectorCAST coverage -> UDS traceability matrix integration.

Links VectorCAST test coverage data with UDS function details to provide
a unified traceability view: Requirement -> UDS Function -> Test Coverage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def parse_vcast_coverage_summary(vcast_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract per-function coverage from VectorCAST parsed data.

    Returns dict mapping function_name (lowercase) -> coverage info.
    """
    coverage_map: Dict[str, Dict[str, Any]] = {}

    rows = vcast_data.get("rows", [])
    if not rows:
        rows = vcast_data.get("data", [])

    for row in rows:
        if not isinstance(row, dict):
            continue
        func_name = str(row.get("function", row.get("Function", row.get("name", "")))).strip()
        if not func_name:
            continue

        coverage_map[func_name.lower()] = {
            "function": func_name,
            "statement_coverage": _parse_pct(row.get("statement_coverage", row.get("Statement", ""))),
            "branch_coverage": _parse_pct(row.get("branch_coverage", row.get("Branch", ""))),
            "mcdc_coverage": _parse_pct(row.get("mcdc_coverage", row.get("MC/DC", ""))),
            "test_count": int(row.get("test_count", row.get("Tests", 0)) or 0),
            "file": str(row.get("file", row.get("File", ""))),
        }

    return coverage_map


def _parse_pct(val: Any) -> Optional[float]:
    """Parse percentage value from various formats."""
    if val is None:
        return None
    s = str(val).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def build_traceability_matrix(
    function_details: Dict[str, Dict[str, Any]],
    vcast_coverage: Dict[str, Dict[str, Any]],
    req_to_fids: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Build a unified traceability matrix linking requirements, UDS functions, and test coverage.

    Returns:
        {
            "matrix": [...],  # list of traceability rows
            "summary": {...},  # coverage statistics
            "uncovered_functions": [...],
            "unmapped_requirements": [...],
        }
    """
    matrix: List[Dict[str, Any]] = []
    covered_fids: Set[str] = set()
    uncovered_functions: List[str] = []

    fid_to_reqs: Dict[str, List[str]] = {}
    if req_to_fids:
        for req_id, fids in req_to_fids.items():
            for fid in fids:
                fid_to_reqs.setdefault(fid, []).append(req_id)

    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        func_name = info.get("name", "")
        if not func_name:
            continue

        cov = vcast_coverage.get(func_name.lower(), {})
        has_coverage = bool(cov)
        req_ids = fid_to_reqs.get(fid, [])
        asil = info.get("asil", "QM")

        row = {
            "fid": fid,
            "function_name": func_name,
            "module": info.get("module_name", ""),
            "asil": asil,
            "requirement_ids": req_ids,
            "has_test_coverage": has_coverage,
            "statement_coverage": cov.get("statement_coverage"),
            "branch_coverage": cov.get("branch_coverage"),
            "mcdc_coverage": cov.get("mcdc_coverage"),
            "test_count": cov.get("test_count", 0),
            "coverage_file": cov.get("file", ""),
        }
        matrix.append(row)

        if has_coverage:
            covered_fids.add(fid)
        else:
            uncovered_functions.append(func_name)

    total = len(matrix)
    covered = len(covered_fids)
    with_reqs = sum(1 for r in matrix if r["requirement_ids"])
    safety_funcs = sum(1 for r in matrix if str(r.get("asil", "")).upper() not in ("QM", "", "N/A"))
    safety_covered = sum(
        1 for r in matrix
        if str(r.get("asil", "")).upper() not in ("QM", "", "N/A") and r["has_test_coverage"]
    )

    unmapped_reqs = []
    if req_to_fids:
        mapped_reqs = set()
        for row in matrix:
            mapped_reqs.update(row["requirement_ids"])
        all_reqs = set(req_to_fids.keys())
        unmapped_reqs = sorted(all_reqs - mapped_reqs)

    avg_stmt = _avg([r["statement_coverage"] for r in matrix if r["statement_coverage"] is not None])
    avg_branch = _avg([r["branch_coverage"] for r in matrix if r["branch_coverage"] is not None])

    summary = {
        "total_functions": total,
        "covered_functions": covered,
        "coverage_rate": round(covered / total * 100, 1) if total > 0 else 0,
        "functions_with_requirements": with_reqs,
        "req_traceability_rate": round(with_reqs / total * 100, 1) if total > 0 else 0,
        "safety_functions": safety_funcs,
        "safety_covered": safety_covered,
        "safety_coverage_rate": round(safety_covered / safety_funcs * 100, 1) if safety_funcs > 0 else 0,
        "avg_statement_coverage": avg_stmt,
        "avg_branch_coverage": avg_branch,
    }

    logger.info(
        "VCast traceability: %d/%d functions covered (%.1f%%), %d safety funcs, %d unmapped reqs",
        covered, total, summary["coverage_rate"], safety_funcs, len(unmapped_reqs),
    )

    return {
        "matrix": matrix,
        "summary": summary,
        "uncovered_functions": uncovered_functions[:50],
        "unmapped_requirements": unmapped_reqs[:50],
    }


def _avg(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)
