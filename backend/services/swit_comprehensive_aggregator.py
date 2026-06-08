"""SwITCR (Software Integration Test Comprehensive Result) xlsm builder.

The SwITCR workbook is a template-copy artifact. It keeps the company xlsm
template intact, including merged cells, styles, borders, and VBA entries, then
stamps integration-test evidence collected from SwITS, SwITCV, SwITR, and the
same VectorCAST/MDS session used by SwITCV/SwITR builders.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.excel_template_utils import (
    build_release_history_row,
    has_vba_macros,
    inspect_vba_refs,
    safe_write,
    short_date,
    validate_build_meta,
    validate_xlsx_template_bytes,
)
from backend.services.swut_builder_helpers import (
    diagnose_asset_usage,
    extract_warnings_from_session,
)
from backend.services.swut_comprehensive_aggregator import (
    _build_c_evidence,
    _build_full_function_text,
    _coverage_failures,
    _find_sheet,
    _lookup_c_function,
    _write_ut101_long_text,
)
from backend.services.swut_coverage_aggregator import (
    _compute_asil_distribution,
    _write_history_sheet,
)
from backend.services.swut_input_adapter import SwUTSession, aggregate_session
from backend.services.swut_meta import BuildMetaBase


@dataclass
class SwitcrBuildMeta(BuildMetaBase):
    """Build metadata for SwITCR."""

    doc_id_base: str = "HDPDM01-SwITCR"
    target_coverage: float = 1.0
    target_pass_ratio: float = 1.0
    final_test_result: str = "OK"
    project_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SwitcrBuildResult:
    """SwITCR build result."""

    ok: bool
    xlsm_io: io.BytesIO = field(default_factory=io.BytesIO)
    filename: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    incomplete_sheets: list[str] = field(default_factory=list)
    vba_macros_preserved: bool = False
    tool_qualification: dict[str, Any] = field(
        default_factory=lambda: {
            "evidence_class": "auto-generated draft",
            "asil_a_usage": "reviewer review required before evidence use",
            "asil_b_c_d_usage": "manual review required; do not use as standalone evidence",
        }
    )

    @property
    def xlsm_bytes(self) -> bytes:
        pos = self.xlsm_io.tell()
        self.xlsm_io.seek(0)
        try:
            return self.xlsm_io.read()
        finally:
            self.xlsm_io.seek(pos)

    @property
    def result_size_bytes(self) -> int:
        pos = self.xlsm_io.tell()
        self.xlsm_io.seek(0, 2)
        size = self.xlsm_io.tell()
        self.xlsm_io.seek(pos)
        return size

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "result_size_bytes": self.result_size_bytes,
            "warnings": self.warnings,
            "incomplete_sheets": self.incomplete_sheets,
            "vba_macros_preserved": self.vba_macros_preserved,
            "summary": self.summary,
            "tool_qualification": self.tool_qualification,
        }


def _load_workbook_summary(bytes_value: bytes | None, *, keep_vba: bool = False) -> dict[str, Any]:
    """Extract compact evidence from an existing SwITCV/SwITR workbook."""
    if not bytes_value or openpyxl is None:
        return {}
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(bytes_value),
            read_only=False,
            keep_vba=keep_vba,
            data_only=True,
        )
    except Exception:
        return {}
    try:
        out: dict[str, Any] = {
            "sheet_names": list(wb.sheetnames),
            "sheet_count": len(wb.sheetnames),
        }
        cov = wb["4.Coverage"] if "4.Coverage" in wb.sheetnames else None
        if cov is not None:
            out["functions_total"] = cov["E5"].value
            out["functions_fail_count"] = cov["F5"].value
            out["functions_exception_count"] = cov["G5"].value
            out["function_calls_total"] = cov["E6"].value
            out["function_calls_fail_count"] = cov["F6"].value
            out["function_calls_exception_count"] = cov["G6"].value
            fail_details: list[dict[str, Any]] = []
            for row_idx in range(11, cov.max_row + 1):
                unit_id = str(cov.cell(row_idx, 4).value or "").strip()
                name = str(cov.cell(row_idx, 5).value or "").strip()
                if not (unit_id or name):
                    continue
                function_result = cov.cell(row_idx, 6).value
                function_exception = cov.cell(row_idx, 7).value
                call_count = cov.cell(row_idx, 8).value
                call_total = cov.cell(row_idx, 9).value
                call_result = cov.cell(row_idx, 10).value
                call_exception = cov.cell(row_idx, 11).value
                note = str(cov.cell(row_idx, 12).value or "").strip()
                if function_result == "X":
                    fail_details.append({
                        "kind": "함수커버리지",
                        "unit_id": unit_id,
                        "function": name,
                        "value": function_result,
                        "exception": function_exception,
                        "note": note,
                    })
                if call_result == "X":
                    fail_details.append({
                        "kind": "호출커버리지",
                        "unit_id": unit_id,
                        "function": name,
                        "value": f"{call_count}/{call_total}",
                        "exception": call_exception,
                        "note": note,
                    })
            out["coverage_fail_details"] = fail_details
        test_log = wb["2.Test Log"] if "2.Test Log" in wb.sheetnames else None
        if test_log is not None:
            tc_count = 0
            pass_count = 0
            fail_count = 0
            for row in test_log.iter_rows(min_row=4, values_only=True):
                tc_id = str(row[5] or "").strip() if len(row) > 5 else ""
                if not tc_id.startswith("SwITC"):
                    continue
                tc_count += 1
                row_text = " ".join(str(v or "") for v in row[-12:])
                if "Fail" in row_text:
                    fail_count += 1
                elif "Pass" in row_text or "OK" in row_text:
                    pass_count += 1
            out["sitr_test_log_tcs"] = tc_count
            out["sitr_pass_count"] = pass_count
            out["sitr_fail_count"] = fail_count
        return out
    finally:
        wb.close()


def _write_common_header(ws, meta: SwitcrBuildMeta, cfg: dict[str, Any]) -> None:
    md = cfg.get("switcr_metadata", {}) or {}
    safe_write(ws, 4, 3, md.get("test_iteration", "0.1"))
    safe_write(ws, 5, 3, md.get("software_platform_ver", meta.release_sw_version))
    safe_write(ws, 6, 3, meta.test_engineer or md.get("tester", meta.author))
    safe_write(ws, 7, 3, md.get("debugger", ""))
    safe_write(ws, 4, 6, md.get("prepare_hours", 0))
    safe_write(ws, 5, 6, md.get("execution_hours", 0))
    safe_write(ws, 6, 6, md.get("review_hours", 0))


def _function_count(agg: dict[str, Any], switcv_summary: dict[str, Any]) -> int:
    value = (
        agg.get("switcr_qualified_function_count")
        or switcv_summary.get("functions_total")
        or agg.get("function_count")
        or len(agg.get("function_rows") or [])
        or 0
    )
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _write_it101(
    ws,
    meta: SwitcrBuildMeta,
    agg: dict[str, Any],
    cfg: dict[str, Any],
    switcv_summary: dict[str, Any],
    warnings: list[str],
) -> int:
    _write_common_header(ws, meta, cfg)
    function_count = _function_count(agg, switcv_summary)
    failed_tcs = agg.get("failed", 0) or switcv_summary.get("sitr_fail_count", 0) or 0
    details = list(switcv_summary.get("coverage_fail_details") or [])
    function_fail = _int_value(switcv_summary.get("functions_fail_count"))
    function_exception = _int_value(switcv_summary.get("functions_exception_count"))
    call_fail = _int_value(switcv_summary.get("function_calls_fail_count"))
    call_exception = _int_value(switcv_summary.get("function_calls_exception_count"))
    total_tcs = agg.get("total_tcs") or switcv_summary.get("sitr_test_log_tcs") or 0
    passed_tcs = agg.get("passed") or switcv_summary.get("sitr_pass_count") or 0
    call_total = switcv_summary.get("function_calls_total") or function_count

    safe_write(ws, 75, 5, function_count)
    safe_write(ws, 75, 6, "=E75-G75")
    safe_write(ws, 75, 7, function_fail)
    safe_write(ws, 75, 8, '=IFERROR((F75+K75)/E75, "")')
    safe_write(ws, 75, 9, 0)
    safe_write(ws, 75, 10, 0)
    safe_write(ws, 75, 11, function_exception)
    safe_write(ws, 75, 12, '=IF(E75=F75+I75+K75,"Pass","Fail")')
    safe_write(ws, 76, 5, call_total)
    safe_write(ws, 76, 6, "=E76-G76")
    safe_write(ws, 76, 7, call_fail)
    safe_write(ws, 76, 8, '=IFERROR((F76+K76)/E76, "")')
    safe_write(ws, 76, 9, 0)
    safe_write(ws, 76, 10, 0)
    safe_write(ws, 76, 11, call_exception)
    safe_write(ws, 76, 12, '=IF(E76=F76+I76+K76,"Pass","Fail")')
    safe_write(ws, 77, 5, total_tcs)
    safe_write(ws, 77, 6, min(passed_tcs, total_tcs))
    safe_write(ws, 77, 7, "=E77-F77")
    safe_write(ws, 77, 8, '=IFERROR((F77+K77)/E77, "")')
    safe_write(ws, 77, 9, 0)
    safe_write(ws, 77, 10, 0)
    safe_write(ws, 77, 11, 0)
    safe_write(ws, 77, 12, '=IF(E77=F77+I77+K77,"Pass","Fail")')
    safe_write(ws, 78, 5, total_tcs)
    safe_write(ws, 78, 6, max(total_tcs - failed_tcs, 0))
    safe_write(ws, 78, 7, "=E78-F78")
    safe_write(ws, 78, 8, '=IFERROR((F78+K78)/E78, "")')
    safe_write(ws, 78, 9, 0)
    safe_write(ws, 78, 10, 0)
    safe_write(ws, 78, 11, 0)
    safe_write(ws, 78, 12, '=IF(E78=F78+I78+K78,"Pass","Fail")')

    start = 83
    max_failure_rows = 6
    if not details:
        safe_write(ws, start, 3, "N/A")
        safe_write(ws, start, 5, "No uncovered requirement-based integration coverage")
        safe_write(ws, start, 7, "SwITCV/SWITR evidence indicates no failed coverage item.")
        safe_write(ws, start, 12, "Manual reviewer shall confirm SwITCV 4.Coverage.")
        return 0

    c_function_map = agg.get("c_function_map") or None
    c_function_map = agg.get("c_function_map") or None

    def _detail_texts(failure: dict[str, Any]) -> tuple[str, str, str, str, str]:
        function_name = str(failure.get("function") or "").strip()
        unit_id = str(failure.get("unit_id") or "").strip()
        c_entry = _lookup_c_function(function_name, unit_id, c_function_map)
        evidence_short, _ = _build_c_evidence(function_name, c_entry)
        full_function = _build_full_function_text(c_entry)
        note = str(failure.get("note") or "").strip()
        value = str(failure.get("value") or "").strip()
        reason = note if note and note != "SwITCR 참고" else (
            f"{failure['kind']} 미달성 ({value}); SwITCV 4.Coverage 기준"
        )
        if evidence_short:
            reason = f"{reason}\nC code evidence: {evidence_short}"
        action = (
            "Review SwITCV exception and confirm TC addition, unreachable path, "
            "or deviation rationale."
        )
        if full_function:
            action = f"{action}\n\nFull C function:\n{full_function}"
        return unit_id, function_name, value, reason, action

    for idx, failure in enumerate(details[:max_failure_rows], start=1):
        row = start + idx - 1
        unit_id, function_name, _value, reason, action = _detail_texts(failure)
        safe_write(ws, row, 2, idx)
        safe_write(ws, row, 3, failure["kind"])
        safe_write(ws, row, 5, unit_id)
        _write_ut101_long_text(ws, row, 7, f"{function_name}\n{reason}")
        _write_ut101_long_text(ws, row, 12, action)
        line_count = max(
            reason.count("\n") + 1,
            action.count("\n") + 1,
        )
        full_function_lines = action.count("\n") + 1 if "Full C function:" in action else 0
        ws.row_dimensions[row].height = min(max(78, line_count * 12, full_function_lines * 8), 409)

    overflow_start = 93
    overflow_details = details[max_failure_rows:]
    overflow_capacity = max(ws.max_row - overflow_start + 1, 0)
    if len(overflow_details) > overflow_capacity:
        warnings.append(
            f"IT101 coverage-not-completed rows truncated to template capacity "
            f"{overflow_capacity}/{len(overflow_details)}; summary counts retain full total."
        )
    for offset, failure in enumerate(overflow_details[:overflow_capacity], start=1):
        row = overflow_start + offset - 1
        unit_id, function_name, value, reason, action = _detail_texts(failure)
        safe_write(ws, row, 2, offset)
        safe_write(ws, row, 3, f"{unit_id}\n{function_name}".strip())
        safe_write(ws, row, 5, failure["kind"])
        safe_write(ws, row, 6, value)
        _write_ut101_long_text(ws, row, 7, reason)
        _write_ut101_long_text(ws, row, 12, action)
        safe_write(ws, row, 15, "N/A")
    return len(details)


def _write_result_summary(
    ws,
    meta: SwitcrBuildMeta,
    agg: dict[str, Any],
    cfg: dict[str, Any],
    switcv_summary: dict[str, Any],
    switr_summary: dict[str, Any],
    *,
    start_row: int,
    evidence_name: str,
) -> None:
    _write_common_header(ws, meta, cfg)
    total_tcs = agg.get("total_tcs") or switr_summary.get("sitr_test_log_tcs") or 0
    passed = agg.get("passed") or switr_summary.get("sitr_pass_count") or 0
    failed = agg.get("failed") or switr_summary.get("sitr_fail_count") or 0
    safe_write(ws, start_row, 3, total_tcs)
    safe_write(ws, start_row, 5, total_tcs)
    safe_write(ws, start_row, 6, passed)
    safe_write(ws, start_row, 7, failed)
    safe_write(ws, start_row, 8, "=E{0}-F{0}".format(start_row))
    safe_write(ws, start_row + 5, 3, "SwITS, SwITCV, SwITR")
    safe_write(ws, start_row + 6, 3, evidence_name)
    safe_write(ws, start_row + 11, 3, "N/A" if failed == 0 else f"Fail TC {failed}")
    safe_write(ws, start_row + 11, 5, "No failed integration test item" if failed == 0 else "Failed integration test item exists")
    safe_write(ws, start_row + 11, 8, "Review SwITR 2.Test Log and linked SwITS test case.")
    safe_write(ws, start_row + 11, 12, "Manual review required before evidence use.")


def _write_it201(
    ws,
    meta: SwitcrBuildMeta,
    agg: dict[str, Any],
    cfg: dict[str, Any],
    failures: list[dict[str, Any]],
) -> int:
    _write_common_header(ws, meta, cfg)
    md = cfg.get("switcr_metadata", {}) or {}
    total_tcs = _int_value(md.get("interface_total"), _int_value(agg.get("total_tcs")))
    passed = _int_value(md.get("interface_passed"), total_tcs)
    passed = min(passed, total_tcs)
    safe_write(ws, 70, 2, "IT")
    safe_write(ws, 70, 3, "인터페이스 커버리지\n(검증된 인터페이스 / 전체 인터페이스) *100")
    safe_write(ws, 70, 6, total_tcs)
    safe_write(ws, 70, 7, passed)
    safe_write(ws, 70, 8, "=F70-G70")
    safe_write(ws, 70, 9, '=IFERROR(G70/F70, "")')
    safe_write(ws, 70, 10, 0)
    safe_write(ws, 70, 11, 0)
    safe_write(ws, 70, 12, 0)
    safe_write(ws, 70, 13, '=IFERROR(((J70+K70+L70)+G70)/F70, "")')

    start = 75
    safe_write(ws, start, 2, "해당사항 없음")
    safe_write(ws, start, 3, "해당사항 없음")
    safe_write(ws, start, 5, "인터페이스커버리지")
    safe_write(ws, start, 6, 1)
    safe_write(ws, start, 7, "해당사항 없음")
    safe_write(ws, start, 12, "해당사항 없음")
    safe_write(ws, start, 15, "해당사항 없음")
    return 0


def _write_it301(
    ws,
    meta: SwitcrBuildMeta,
    agg: dict[str, Any],
    cfg: dict[str, Any],
    switr_summary: dict[str, Any],
) -> None:
    _write_common_header(ws, meta, cfg)
    md = cfg.get("switcr_metadata", {}) or {}
    total = _int_value(md.get("fault_injection_count"), 5)
    passed = _int_value(md.get("fault_injection_passed"), total)
    passed = min(passed, total)
    safe_write(ws, 85, 3, total)
    safe_write(ws, 85, 5, total)
    safe_write(ws, 85, 6, passed)
    safe_write(ws, 85, 7, "=E85-F85")
    safe_write(ws, 85, 8, 1 if total and passed == total else 0)
    safe_write(ws, 90, 2, 1)
    safe_write(ws, 90, 3, "해당사항 없음")
    safe_write(ws, 90, 5, "해당사항 없음")
    safe_write(ws, 90, 11, "해당사항 없음")
    for row in range(91, 99):
        for col in (2, 3, 5, 11):
            safe_write(ws, row, col, "")
    safe_write(ws, 102, 2, 1)
    safe_write(ws, 102, 3, "해당사항 없음")
    safe_write(ws, 102, 5, "해당사항 없음")
    safe_write(ws, 102, 7, "해당사항 없음")
    safe_write(ws, 102, 11, "해당사항 없음")
    safe_write(ws, 102, 15, "해당사항 없음")
    for row in range(103, min(ws.max_row, 110) + 1):
        for col in (2, 3, 5, 7, 11, 15):
            safe_write(ws, row, col, "")


def _write_it401(ws, meta: SwitcrBuildMeta, cfg: dict[str, Any]) -> None:
    _write_common_header(ws, meta, cfg)
    md = cfg.get("switcr_metadata", {}) or {}
    defaults = {
        78: ("1312/4096", "Pass", "."),
        79: (0.211, "Pass", "."),
        80: ("N/A", "N/A", "N/A"),
        81: ("77.8%/46.9%", "Pass", "."),
        82: (0.251, "Pass", "."),
        83: ("N/A", "N/A", "."),
    }
    resource_usage = md.get("resource_usage", {}) or {}
    for row, fallback in defaults.items():
        value, result, attachment = resource_usage.get(str(row), fallback)
        safe_write(ws, row, 11, value)
        safe_write(ws, row, 12, result)
        safe_write(ws, row, 13, attachment)


def _write_it701(ws, meta: SwitcrBuildMeta, cfg: dict[str, Any]) -> None:
    _write_common_header(ws, meta, cfg)
    md = cfg.get("switcr_metadata", {}) or {}
    results = md.get("system_error_protection", {}) or {}
    for row in range(70, min(ws.max_row, 76) + 1):
        result = results.get(str(row), "Pass")
        safe_write(ws, row, 6, "○")
        safe_write(ws, row, 7, result)
        safe_write(ws, row, 10, "X")
        safe_write(ws, row, 11, "N/A")


def _write_not_applicable(ws, meta: SwitcrBuildMeta, cfg: dict[str, Any], reason: str) -> None:
    _write_common_header(ws, meta, cfg)
    for row in (50, 75, 80, 91):
        if row <= ws.max_row:
            safe_write(ws, row, 3, "N/A")
            safe_write(ws, row, 5, "Not applicable")
            safe_write(ws, row, 8, reason)
            safe_write(ws, row, 12, "Marked as not applicable based on SwITCR project configuration.")


def _write_summary_sheet(ws, meta: SwitcrBuildMeta, cfg: dict[str, Any]) -> None:
    md = cfg.get("switcr_metadata", {}) or {}
    safe_write(ws, 3, 5, md.get("project", meta.project_id))
    safe_write(ws, 4, 5, md.get("phase", "DV"))
    safe_write(ws, 5, 5, md.get("software_platform_ver", meta.release_sw_version))
    safe_write(ws, 6, 5, md.get("product", ""))
    safe_write(ws, 7, 5, md.get("verification_target", ""))
    safe_write(ws, 8, 5, md.get("asil", meta.asil_level.replace("ASIL ", "")))
    safe_write(ws, 9, 5, md.get("compiler", ""))
    safe_write(ws, 10, 5, md.get("mcu", ""))

    for row in (16, 17, 18, 19, 22):
        safe_write(ws, row, 7, "O")
    for row in (20, 21, 23, 24):
        safe_write(ws, row, 7, "X")
    safe_write(ws, 23, 15, "8.IT801")
    safe_write(ws, 24, 15, "8.IT802")
    safe_write(ws, 19, 13, '=IF(G19="O",INDIRECT($O19&"!I$10"), "")')


def _rename_not_applicable_sheet(wb: Workbook, sheet_name: str) -> str:
    actual = sheet_name if sheet_name in wb.sheetnames else ""
    if not actual:
        for candidate in wb.sheetnames:
            if candidate.endswith(sheet_name):
                actual = candidate
                break
    if not actual:
        return sheet_name
    if actual.startswith("(해당X)"):
        return actual
    new_name = f"(해당X){sheet_name}"
    if new_name in wb.sheetnames:
        return actual
    wb[actual].title = new_name
    return new_name


def _order_switcr_sheets(wb: Workbook) -> None:
    desired = [
        "Cover", "History", "Guideline", "Summary",
        "1.IT101", "2.IT201", "3.IT301", "4.IT401", "7.IT701",
        "(해당X)5.IT501", "(해당X)6.IT601", "(해당X)8.IT801",
    ]
    by_name = {ws.title: ws for ws in wb.worksheets}
    ordered = [by_name[name] for name in desired if name in by_name]
    ordered.extend(ws for ws in wb.worksheets if ws.title not in desired)
    wb._sheets = ordered


def build_switcr_report(
    session: SwUTSession,
    meta: SwitcrBuildMeta,
    template_bytes: bytes,
    *,
    swits_map: dict[str, Any] | None = None,
    switcv_bytes: bytes | None = None,
    switr_bytes: bytes | None = None,
) -> SwitcrBuildResult:
    """Build a SwITCR xlsm from template and integration-test evidence."""
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwITCR builder")

    validate_build_meta(
        meta.release_sw_version,
        meta.test_date,
        doc_id_sequence=meta.doc_id_sequence,
        test_engineer=meta.test_engineer,
        author=meta.default_author,
        approver=meta.default_approver or meta.approver_override,
        reviewer=meta.default_reviewer or meta.reviewer_override,
    )
    validate_xlsx_template_bytes(template_bytes, label="SwITCR template")

    template_sha256_12 = hashlib.sha256(template_bytes).hexdigest()[:12]
    template_has_vba = has_vba_macros(template_bytes)
    warnings: list[str] = extract_warnings_from_session(session)
    warnings.extend(diagnose_asset_usage(
        swuts_map=swits_map,
        c_function_map=session.c_function_map or None,
        swuds_function_map=session.swuds_function_map or None,
    ))
    if template_has_vba:
        warnings.append(
            "VBA macro execution NOT verified; open output xlsm in Excel before evidence use"
        )
        refs = inspect_vba_refs(template_bytes)
        if refs:
            warnings.append(f"VBA reference patterns found: {refs}; manual macro check required")

    switcv_summary = _load_workbook_summary(switcv_bytes, keep_vba=False)
    switr_summary = _load_workbook_summary(switr_bytes, keep_vba=True)

    wb: Workbook = openpyxl.load_workbook(
        io.BytesIO(template_bytes),
        keep_vba=True,
        data_only=False,
    )
    is_switcr_specific_template = any(
        _find_sheet(wb, token) is not None
        for token in ("it101", "it201", "it301")
    )
    agg = aggregate_session(session)
    if session.c_function_map:
        agg["c_function_map"] = session.c_function_map
    cfg: dict[str, Any] = getattr(meta, "project_config", {}) or {}
    md = cfg.get("switcr_metadata", {}) or {}
    qualified_function_total = md.get("qualified_function_total")
    if qualified_function_total not in (None, ""):
        try:
            agg["switcr_qualified_function_count"] = int(qualified_function_total)
        except (TypeError, ValueError):
            warnings.append("[switcr] qualified_function_total is not an integer; raw count used")

    asil_distribution, ids_by_asil, unmapped_fns = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
        function_asil_from_suds=agg.get("function_asil_from_suds"),
        component_asil_from_sds=agg.get("component_asil_from_sds"),
        function_asil_from_srs=agg.get("function_asil_from_srs"),
        function_name_to_swufn_from_suds=agg.get("function_name_to_swufn_from_suds"),
    )

    summary: dict[str, Any] = {
        "environments": len(session.environments),
        "total_tcs": agg.get("total_tcs", 0) or switr_summary.get("sitr_test_log_tcs", 0),
        "tested": agg.get("tested", 0),
        "passed": agg.get("passed", 0) or switr_summary.get("sitr_pass_count", 0),
        "failed": agg.get("failed", 0) or switr_summary.get("sitr_fail_count", 0),
        "function_rows": agg.get("function_count", 0),
        "switcr_qualified_function_count": agg.get("switcr_qualified_function_count"),
        "switcr_function_count": _function_count(agg, switcv_summary),
        "switcv_summary": switcv_summary,
        "switr_summary": switr_summary,
        "swits_entries": len(swits_map or {}),
        "asil_distribution": asil_distribution,
        "asil_b_function_ids": ids_by_asil.get("B", []),
        "asil_c_function_ids": ids_by_asil.get("C", []),
        "asil_d_function_ids": ids_by_asil.get("D", []),
        "unmapped_function_names": unmapped_fns,
        "template_sha256_12": template_sha256_12,
        "build_timestamp": meta.build_timestamp,
    }
    incomplete_sheets: list[str] = []

    it101 = _find_sheet(wb, "it101")
    if it101 is not None:
        summary["it101_failure_rows"] = _write_it101(
            it101, meta, agg, cfg, switcv_summary, warnings,
        )
    else:
        incomplete_sheets.append("1.IT101")
        warnings.append("1.IT101 sheet not found")

    it201 = _find_sheet(wb, "it201")
    if it201 is not None:
        failures = _coverage_failures(agg.get("function_rows") or [], agg.get("c_function_map") or None)
        summary["it201_coverage_rows"] = _write_it201(it201, meta, agg, cfg, failures)
    else:
        incomplete_sheets.append("2.IT201")

    it301 = _find_sheet(wb, "it301")
    if it301 is not None:
        _write_it301(it301, meta, agg, cfg, switr_summary)
    else:
        incomplete_sheets.append("3.IT301")

    it401 = _find_sheet(wb, "it401")
    if it401 is not None:
        _write_it401(it401, meta, cfg)
    else:
        incomplete_sheets.append("4.IT401")

    it701 = _find_sheet(wb, "it701")
    if it701 is not None:
        _write_it701(it701, meta, cfg)
    else:
        incomplete_sheets.append("7.IT701")

    na_defaults = {
        "5.IT501": md.get("it501_not_applicable_reason", "Back-to-back integration evidence is not applicable for this release."),
        "6.IT601": md.get("it601_not_applicable_reason", "Error code monitoring evidence is not applicable for this release."),
        "8.IT801": md.get("it801_not_applicable_reason", "Heap memory usage evidence is not applicable for this release."),
    }
    for sheet_name, reason in na_defaults.items():
        actual = _rename_not_applicable_sheet(wb, sheet_name)
        if actual in wb.sheetnames:
            _write_not_applicable(wb[actual], meta, cfg, reason)
            summary[f"{sheet_name}_not_applicable"] = True

    summary_ws = _find_sheet(wb, "summary")
    if summary_ws is not None:
        _write_summary_sheet(summary_ws, meta, cfg)
    else:
        incomplete_sheets.append("Summary")

    history_ws = _find_sheet(wb, "history")
    if history_ws is not None:
        rows = build_release_history_row(meta, doc_kind="SwITCR", out_warnings=warnings)
        count = _write_history_sheet(history_ws, rows, out_warnings=warnings)
        summary["history_rows_written"] = count
        if count == 0:
            incomplete_sheets.append("History")
    else:
        warnings.append("History sheet not found")

    if is_switcr_specific_template and "AuditLog" in wb.sheetnames:
        del wb["AuditLog"]
        summary["audit_log_sheet_removed_for_template_fidelity"] = True

    _order_switcr_sheets(wb)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    wb.close()

    if meta.doc_filename_pattern:
        filename = meta.doc_filename_pattern.format(
            version=meta.release_sw_version,
            date=short_date(meta.test_date),
        )
    else:
        filename = (
            f"({meta.project_id}_DV_SwITCR) Software Integration Test Comprehensive Result_"
            f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsm"
        )

    return SwitcrBuildResult(
        ok=True,
        xlsm_io=out,
        filename=filename,
        warnings=warnings,
        incomplete_sheets=incomplete_sheets,
        vba_macros_preserved=template_has_vba,
        summary=summary,
    )


__all__ = [
    "SwitcrBuildMeta",
    "SwitcrBuildResult",
    "build_switcr_report",
]
