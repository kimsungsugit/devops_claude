from __future__ import annotations

import io

import openpyxl

from backend.services.swut_comprehensive_aggregator import (
    SwutcrBuildMeta,
    _coverage_failures,
    build_swutcr_report,
)
from backend.services.swut_input_adapter import (
    CoverageStats,
    EnvironmentData,
    ExecutionRow,
    FunctionCoverage,
    SwUTSession,
)


def _minimal_swutcr_template() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    cover = wb.create_sheet("Cover")
    for row, label in enumerate((
        "Project", "ASIL Level", "Status", "Validation Date", "Author",
        "Reviewer", "Approver", "Doc. ID", "Version", "Build Timestamp",
    ), start=1):
        cover.cell(row, 1).value = label

    summary = wb.create_sheet("Test Summary")
    for row, label in enumerate((
        "Project Name", "Release Name(SW)", "Test Target Version(HW)",
        "Test Date", "Test Engineer", "Target Coverage", "Actual Coverage",
        "Target Pass ratio", "Actual Pass ratio", "Final Test Result",
    ), start=1):
        summary.cell(row, 1).value = label

    wb.create_sheet("1.Traceability")
    wb.create_sheet("2.Consistency")
    coverage = wb.create_sheet("3.Coverage")
    coverage["A1"] = "Statement Coverage"
    coverage["A6"] = "Unit ID"

    deviation = wb.create_sheet("Deviation")
    deviation["B1"] = "Test Case ID"

    test_log = wb.create_sheet("Test Log")
    test_log["B1"] = "Test Case ID"
    test_log["C1"] = "Description"
    test_log["D1"] = "Generation Method"
    test_log["F1"] = "Input"
    test_log["P1"] = "Expected Result"
    test_log["Z1"] = "Actual Result"
    test_log["AJ1"] = "Pass/Fail Unit"
    test_log["AK1"] = "Pass/Fail Total"
    test_log["AL1"] = "Log Data"

    wb.create_sheet("History")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _minimal_swutcr_specific_template() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cover = wb.create_sheet("Cover")
    cover["A1"] = "Project"
    wb.create_sheet("History")
    wb.create_sheet("Summary")
    wb.create_sheet("1.UT101")
    wb.create_sheet("2.UT201")
    wb.create_sheet("3.UT301")
    wb.create_sheet("21.IT801")
    wb.create_sheet("통합검증_BTB")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _session() -> SwUTSession:
    env = EnvironmentData(
        env_name="SWTE_01",
        component_name="CompA",
        test_cases={"SwUFn_0001.001": [object()]},
        test_results={
            "SwUFn_0001.001": ExecutionRow(
                tc_name="SwUFn_0001.001",
                passed=True,
                actual_result={"Input[0]": ("0x01", "0x01")},
            ),
        },
        function_coverage=[
            FunctionCoverage(unit_id="SwUFn_0001", name="FunctionA"),
        ],
    )
    return SwUTSession(environments=[env])


def test_coverage_failures_draft_reason_from_c_source_default_branch():
    failures = _coverage_failures(
        [
            FunctionCoverage(
                unit_id="SwUFn_0001",
                name="FunctionA",
                branch=CoverageStats(covered=1, total=2),
            )
        ],
        {
            "FunctionA": {
                "name": "FunctionA",
                "file": "SysSafety.c",
                "body": "switch (mode) { default: return E_NOT_OK; }",
                "calls": [],
                "used_globals": [],
            }
        },
    )

    assert len(failures) == 1
    assert "switch/default defensive logic" in failures[0]["reason"]
    assert "negative/default-path TC" in failures[0]["action"]


def test_build_swutcr_preserves_template_and_writes_summary():
    result = build_swutcr_report(
        _session(),
        SwutcrBuildMeta(
            project_id="KJPDS02",
            project_full_name="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
            test_engineer="JK Kim",
            doc_filename_pattern=(
                "(KJPDS02_DV_SwUTCR) Software Unit Test Comprehensive Result_"
                "v{version}_{date}_R.xlsm"
            ),
        ),
        _minimal_swutcr_template(),
        swuds_function_ids={"SwUFn_0001"},
    )

    assert result.ok is True
    assert result.filename == (
        "(KJPDS02_DV_SwUTCR) Software Unit Test Comprehensive Result_v1.01_251205_R.xlsm"
    )
    assert result.summary["total_tcs"] == 1
    assert result.summary["passed"] == 1
    assert result.result_size_bytes > 0

    wb = openpyxl.load_workbook(result.xlsm_io, data_only=False)
    assert "Cover" in wb.sheetnames
    assert "Test Summary" in wb.sheetnames
    assert "AuditLog" in wb.sheetnames
    assert wb["Test Summary"]["B2"].value == "1.01"


def test_build_swutcr_specific_template_uses_project_config_and_no_generic_warnings():
    result = build_swutcr_report(
        _session(),
        SwutcrBuildMeta(
            project_id="KJPDS02",
            project_full_name="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
            test_engineer="",
            project_config={
                "swutcr_metadata": {
                    "project": "KJPDS02",
                    "phase": "DV",
                    "software_platform_ver": "25A1",
                    "product": "PDS",
                    "verification_target": "MCU",
                    "asil": "A",
                    "compiler": "\tCodeWarrior HC12Z ",
                    "mcu": "\tNXP S12ZVMC",
                    "test_iteration": "0.1",
                    "tester": "주희영",
                    "debugger": "이재원, 유영규",
                    "prepare_hours": 10,
                    "execution_hours": 10,
                    "review_hours": 10,
                    "tool_name": "VectorCAST",
                    "tool_version": "2025.sp3",
                    "excluded_scope": "LIN",
                    "excluded_size": 65826,
                    "qualified_function_total": 570,
                    "fault_injection_total": 402,
                    "fault_injection_passed": 402,
                    "reference_document": "SwTP",
                    "reference_id": "SwUTE_01",
                    "ut101_enabled": "O",
                    "ut201_enabled": "O",
                    "ut301_enabled": "X",
                    "heap_memory_leak_count": 0,
                    "heap_access_violation_count": 0,
                },
            },
        ),
        _minimal_swutcr_specific_template(),
    )

    assert result.ok is True
    assert "Traceability" not in result.incomplete_sheets
    assert not any("Traceability sheet not found" in w for w in result.warnings)
    assert not any("Test Log sheet not found" in w for w in result.warnings)
    assert result.summary["swutcr_qualified_function_count"] == 570
    assert result.summary["swutcr_raw_function_count"] == 1

    wb = openpyxl.load_workbook(result.xlsm_io, data_only=False)
    assert "AuditLog" not in wb.sheetnames
    assert wb["Summary"]["E5"].value == "25A1"
    assert wb["Summary"]["E6"].value == "PDS"
    assert wb["Summary"]["E9"].value == "\tCodeWarrior HC12Z "
    assert wb["1.UT101"]["C6"].value == "주희영"
    assert wb["1.UT101"]["F76"].value == 570
    assert wb["2.UT201"]["C85"].value == 570
    assert wb["2.UT201"]["E85"].value == 402
    assert wb["2.UT201"]["F85"].value == 402
    assert wb["3.UT301"]["C6"].value == "주희영"
    assert wb["3.UT301"]["C80"].value == "N/A"
    assert wb["21.IT801"]["C6"].value == "주희영"
    assert wb["21.IT801"]["E45"].value == 0
    assert wb["21.IT801"]["E46"].value == 0
    assert wb["통합검증_BTB"]["D4"].value == "KJPDS02"
    assert wb["통합검증_BTB"]["C37"].value == "N/A"
