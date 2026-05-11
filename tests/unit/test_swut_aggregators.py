"""Tests for swut_coverage_aggregator + swut_sutr_aggregator.

template xlsx fixture를 in-memory로 생성 → build_* 호출 → 출력 bytes 검증.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.excel_template_utils import short_date  # noqa: E402
from backend.services.swut_coverage_aggregator import (  # noqa: E402
    CoverageBuildMeta,
    build_coverage_report,
)
from backend.services.swut_input_adapter import (  # noqa: E402
    CoverageStats,
    EnvironmentData,
    FunctionCoverage,
    SwUTSession,
    TestExecution,
)
from backend.services.swut_sutr_aggregator import (  # noqa: E402
    SutrBuildMeta,
    build_sutr,
)


# ---------------------------------------------------------------------------
# Minimal template xlsx (memory)
# ---------------------------------------------------------------------------

def _build_coverage_template() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cover = wb.create_sheet("Cover")
    cover["B1"] = "Project"
    cover["B2"] = "ASIL Level"
    cover["B3"] = "Author"
    cover["B4"] = "Approver"

    ts = wb.create_sheet("Test Summary")
    ts["B1"] = "Project Name"
    ts["B2"] = "Release Name(SW)"
    ts["B3"] = "Test Target Version(HW)"
    ts["B4"] = "Test Date"
    ts["B5"] = "Test Engineer"
    ts["B6"] = "Final Test Result"

    trace = wb.create_sheet("1.Traceability")
    trace["A1"] = "Traceability matrix placeholder"

    cons = wb.create_sheet("2.Consistency")
    cons["A1"] = "Consistency placeholder"

    cov = wb.create_sheet("3. Coverage")
    cov["A1"] = "Statement Coverage"
    cov["A6"] = "Unit ID"
    cov["B6"] = "Name"
    cov["C6"] = "Count"
    cov["D6"] = "Total"
    cov["E6"] = "Pass"

    hist = wb.create_sheet("History")
    hist["A1"] = "■ Revision History"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_sutr_template() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cover = wb.create_sheet("Cover")
    cover["B1"] = "Project"
    cover["B2"] = "ASIL Level"
    cover["B3"] = "Author"
    cover["B4"] = "Version"

    ts = wb.create_sheet("Test Summary")
    ts["B1"] = "Project Name"
    ts["B2"] = "Release Name(SW)"
    ts["B3"] = "Test Target Version(HW)"
    ts["B4"] = "Test Date"
    ts["B5"] = "Test Engineer"
    ts["B6"] = "Target Coverage"
    ts["B7"] = "Actual Coverage"
    ts["B8"] = "Final Test Result"

    dev = wb.create_sheet("Deviation")
    dev["B1"] = "Test Case ID"
    dev["C1"] = "Issue"
    dev["D1"] = "Deviation"
    dev["E1"] = "Status"

    log = wb.create_sheet("Test Log")
    log["B1"] = "Test Case ID"
    log["C1"] = "Component"
    log["D1"] = "Method"
    log["E1"] = "Pass/Fail"

    hist = wb.create_sheet("History")
    hist["A1"] = "■ Revision History"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_session() -> SwUTSession:
    env = EnvironmentData(
        env_name="SWTE_01",
        component_name="SysOs_Main",
        test_cases={"SwUFn_0101.001": [object()], "SwUFn_0103.001": [object()]},
        test_results={
            "SwUFn_0101.001": TestExecution(tc_name="SwUFn_0101.001", passed=True),
            "SwUFn_0103.001": TestExecution(tc_name="SwUFn_0103.001", passed=False),
        },
        function_coverage=[
            FunctionCoverage(
                unit_id="SwUFn_0101", name="main",
                statement=CoverageStats(8, 8, 1.0),
                branch=CoverageStats(2, 2, 1.0),
                complexity=3,
            ),
            FunctionCoverage(
                unit_id="SwUFn_0103", name="s_SystemOperation",
                statement=CoverageStats(8, 8, 1.0),
                branch=CoverageStats(3, 3, 1.0),
                complexity=2,
            ),
        ],
        grand_total=FunctionCoverage(
            unit_id="GRAND TOTALS",
            statement=CoverageStats(16, 16, 1.0),
            branch=CoverageStats(5, 5, 1.0),
        ),
    )
    return SwUTSession(
        project_id="HDPDM01",
        version="v2.02_240219",
        source_kind="log_folder",
        environments=[env],
    )


# ---------------------------------------------------------------------------
# Coverage aggregator
# ---------------------------------------------------------------------------

class TestShortDate:
    @pytest.mark.parametrize("inp,expected", [
        ("2024-02-19", "240219"),
        ("2024/02/19", "240219"),
        ("24-02-19", "240219"),
        ("", ""),
    ])
    def test_parse(self, inp, expected):
        assert short_date(inp) == expected


class TestBuildCoverageReport:
    def test_smoke_minimal(self):
        session = _make_session()
        meta = CoverageBuildMeta(
            project_id="HDPDM01",
            release_sw_version="1.01.05",
            test_date="2024-02-19",
            test_engineer="김진경",
            asil_level="ASIL A",
            default_author="JK Kim",
            default_approver="CH In",
            doc_id_base="HDPDM01-COV",
            doc_id_sequence="001",
        )
        template = _build_coverage_template()
        result = build_coverage_report(session, meta, template)
        assert result.ok
        assert result.xlsx_bytes
        assert "(HDPDM01)SwUT Coverage Report_v1.01.05_240219_R.xlsx" == result.filename

        # 출력 bytes를 다시 로드 → 시트 값 검증
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        ts = wb["Test Summary"]
        # B1="Project Name" 옆 C1에 "HDPDM01"이 들어가야 함
        assert ts["C1"].value == "HDPDM01"
        assert ts["C2"].value == "1.01.05"  # Release Name(SW)
        assert ts["C5"].value == "김진경"

        cov = wb["3. Coverage"]
        # 헤더 행이 row 6 → 데이터 시작 row 8
        assert cov.cell(row=8, column=2).value == "SwUFn_0101"
        assert cov.cell(row=8, column=3).value == "main"
        assert cov.cell(row=8, column=4).value == 8  # statement total
        assert cov.cell(row=8, column=5).value == 8  # statement covered

    def test_summary_aggregates(self):
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        assert result.summary["environments"] == 1
        assert result.summary["function_rows"] == 2
        assert result.summary["passed"] == 1
        assert result.summary["failed"] == 1
        assert result.summary["coverage_rows_written"] == 2

    def test_tool_qualification_present(self):
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        d = result.to_dict()
        assert d["tool_qualification"]["evidence_class"] == "auto-generated draft"
        assert "단독 evidence" in d["tool_qualification"]["asil_b_c_d_usage"]


# ---------------------------------------------------------------------------
# SUTR aggregator
# ---------------------------------------------------------------------------

class TestBuildSutr:
    def test_smoke_minimal(self):
        session = _make_session()
        meta = SutrBuildMeta(
            release_sw_version="1.01.05",
            test_date="2024-02-19",
            test_engineer="JK Kim",
            doc_id_sequence="851",
        )
        template = _build_sutr_template()
        result = build_sutr(session, meta, template)
        assert result.ok
        assert result.xlsm_bytes
        assert result.filename.endswith(".xlsm")
        assert "(HDPDM01_SUTR)" in result.filename
        assert "240219" in result.filename

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsm_bytes), keep_vba=True)
        ts = wb["Test Summary"]
        assert ts["C1"].value == "HDPDM01"
        assert ts["C2"].value == "1.01.05"

        log = wb["Test Log"]
        # 헤더 row 1 → 데이터 row 2부터, 2 TC
        assert log["B2"].value in ("SwUFn_0101.001", "SwUFn_0103.001")

    def test_deviation_cases_written(self):
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        deviation_cases = [
            {
                "tc_id": "SwUTC_SwUFn_407",
                "tc_no": "TC2",
                "issue_text": "< Divide by zero >",
                "auto_rationale": "[AUTO-GENERATED DRAFT] foo",
            },
        ]
        result = build_sutr(session, meta, _build_sutr_template(), deviation_cases)
        assert result.summary["deviation_cases_written"] == 1

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsm_bytes), keep_vba=True)
        dev = wb["Deviation"]
        assert dev["B2"].value == "SwUTC_SwUFn_407 (TC2)"
        assert "Divide by zero" in str(dev["C2"].value)

    def test_summary_pass_ratio(self):
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        # passed=1, tested=2 → pass ratio 0.5
        assert result.summary["passed"] == 1
        assert result.summary["failed"] == 1
        assert result.summary["tested"] == 2
