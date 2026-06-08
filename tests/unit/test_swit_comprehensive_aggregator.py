from __future__ import annotations

import io

import openpyxl

from backend.services.swit_comprehensive_aggregator import (
    SwitcrBuildMeta,
    build_switcr_report,
)
from backend.services.swut_input_adapter import (
    CoverageStats,
    EnvironmentData,
    ExecutionRow,
    FunctionCoverage,
    SwUTSession,
)


def _minimal_switcr_template() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    wb.create_sheet("Cover")
    wb.create_sheet("History")
    wb.create_sheet("Guideline")
    wb.create_sheet("Summary")
    for name in (
        "1.IT101",
        "2.IT201",
        "3.IT301",
        "4.IT401",
        "5.IT501",
        "6.IT601",
        "7.IT701",
        "8.IT801",
    ):
        ws = wb.create_sheet(name)
        ws.cell(1, 2).value = name
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _switcv_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "4.Coverage"
    ws["E5"] = 570
    ws["F5"] = 1
    ws["G5"] = 1
    ws["E6"] = 570
    ws["F6"] = 0
    ws["G6"] = 0
    ws.cell(11, 4).value = "SwUFn_0101"
    ws.cell(11, 5).value = "FunctionA"
    ws.cell(11, 6).value = "X"
    ws.cell(11, 7).value = "O"
    ws.cell(11, 10).value = "O"
    ws.cell(11, 12).value = "SwITCR 참고"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _switr_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2.Test Log"
    ws.cell(4, 6).value = "SwITC_0101_01"
    ws.cell(4, 20).value = "Pass"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _session() -> SwUTSession:
    env = EnvironmentData(
        env_name="SWIT_SWUFN_0101_DEPTH4_FILE12",
        component_name="CompA",
        test_cases={"SwITC_0101_01": [object()]},
        test_results={
            "SwITC_0101_01": ExecutionRow(
                tc_name="SwITC_0101_01",
                passed=True,
                actual_result={"Input[0]": ("0x01", "0x01")},
            ),
        },
        function_coverage=[
            FunctionCoverage(
                unit_id="SwUFn_0101",
                name="FunctionA",
                statement=CoverageStats(covered=9, total=10),
                branch=CoverageStats(covered=5, total=5),
            ),
        ],
    )
    return SwUTSession(environments=[env])


def test_build_switcr_preserves_template_and_writes_active_sheets():
    result = build_switcr_report(
        _session(),
        SwitcrBuildMeta(
            project_id="KJPDS02",
            project_full_name="KJPDS02",
            release_sw_version="1.01",
            test_date="2025-12-05",
            test_engineer="JK Kim",
            doc_filename_pattern=(
                "(KJPDS02_DV_SwITCR) Software Integration Test Comprehensive Result_"
                "v{version}_{date}_R.xlsm"
            ),
            project_config={
                "switcr_metadata": {
                    "software_platform_ver": "25A1",
                    "tester": "JK Kim",
                    "qualified_function_total": 570,
                }
            },
        ),
        _minimal_switcr_template(),
        swits_map={"SwITC_0101_01": {"tc_id": "SwITC_0101_01"}},
        switcv_bytes=_switcv_workbook(),
        switr_bytes=_switr_workbook(),
    )

    assert result.ok is True
    assert result.filename == (
        "(KJPDS02_DV_SwITCR) Software Integration Test Comprehensive Result_v1.01_251205_R.xlsm"
    )
    assert result.summary["switcr_function_count"] == 570
    assert result.summary["swits_entries"] == 1
    assert result.result_size_bytes > 0

    wb = openpyxl.load_workbook(result.xlsm_io, data_only=False)
    assert "AuditLog" not in wb.sheetnames
    assert wb.sheetnames == [
        "Cover", "History", "Guideline", "Summary",
        "1.IT101", "2.IT201", "3.IT301", "4.IT401",
        "7.IT701", "(해당X)5.IT501", "(해당X)6.IT601", "(해당X)8.IT801",
    ]
    assert "(해당X)5.IT501" in wb.sheetnames
    assert "(해당X)6.IT601" in wb.sheetnames
    assert "(해당X)8.IT801" in wb.sheetnames
    assert wb["1.IT101"]["C5"].value == "25A1"
    assert wb["1.IT101"]["E75"].value == 570
    assert wb["1.IT101"]["C83"].value == "함수커버리지"
    assert wb["1.IT101"]["E83"].value == "SwUFn_0101"
    assert wb["2.IT201"]["F70"].value == 1
    assert wb["2.IT201"]["G70"].value == 1
    assert wb["Summary"]["G20"].value == "X"
