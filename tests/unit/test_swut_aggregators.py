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
    ExecutionRow,
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
            "SwUFn_0101.001": ExecutionRow(tc_name="SwUFn_0101.001", passed=True),
            "SwUFn_0103.001": ExecutionRow(tc_name="SwUFn_0103.001", passed=False),
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

    def test_incomplete_sheets_reported(self):
        """deep-reviewer W5/ISO F3: placeholder 시트는 incomplete_sheets에 명시."""
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        d = result.to_dict()
        assert "1.Traceability" in d["incomplete_sheets"]
        assert "2.Consistency" in d["incomplete_sheets"]

    def test_result_size_key_unified(self):
        """deep-reviewer Info X3: xlsx/xlsm size 키 통합."""
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        d = result.to_dict()
        assert "result_size_bytes" in d
        assert d["result_size_bytes"] > 0

    def test_zip_bomb_rejected(self):
        """deep-reviewer Critical S: 잘못된 bytes는 TemplateValidationError."""
        from backend.services.excel_template_utils import TemplateValidationError
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        with pytest.raises(TemplateValidationError):
            build_coverage_report(session, meta, b"NOT_AN_XLSX")

    def test_invalid_meta_rejected(self):
        """deep-reviewer X3: 빈 release_sw_version 거부."""
        from backend.services.excel_template_utils import BuildMetaValidationError
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="", test_date="2024-02-19")
        with pytest.raises(BuildMetaValidationError, match="release_sw_version"):
            build_coverage_report(session, meta, _build_coverage_template())

    def test_audit_meta_in_summary(self):
        """5차 L1 ISO F3: build_timestamp + template_sha256_12 audit 추적성."""
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.01.05", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        assert "template_sha256_12" in result.summary
        assert len(result.summary["template_sha256_12"]) == 12
        assert "build_timestamp" in result.summary
        assert result.summary["build_timestamp"]  # 빈 string 아님


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

    def test_deviation_shape_invalid_skipped_with_warning(self):
        """deep-reviewer W6: dict/dataclass 외 shape는 skip + warning."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        # 잘못된 shape 2건 (list, namedtuple 비슷한 객체) + 정상 1건
        invalid_cases = [
            ["not", "a", "dict"],  # list
            {"tc_id": "", "issue_text": "empty id"},  # tc_id 빈값 → 거부
            {"tc_id": "SwUTC_X", "issue_text": "valid"},  # 정상
        ]
        result = build_sutr(session, meta, _build_sutr_template(), invalid_cases)
        assert result.summary["deviation_cases_written"] == 1
        assert any("Deviation case shape 검증 실패" in w for w in result.warnings)

    def test_pass_ratio_na_when_tested_zero(self):
        """deep-reviewer X7: tested=0이면 ratio="N/A" silent wrong-pick 회피."""
        # 빈 환경 session
        from backend.services.swut_input_adapter import EnvironmentData
        session = SwUTSession(environments=[EnvironmentData(env_name="EMPTY")])
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        # 출력 xlsm 안의 "Actual Pass ratio" 셀이 "N/A"
        import io as _io
        wb = openpyxl.load_workbook(_io.BytesIO(result.xlsm_bytes), keep_vba=True)
        ts = wb["Test Summary"]
        # B8 = Final Test Result, B7 = Actual Coverage, B... 정확한 위치는 fixture 의존
        # 단순 검증: 시트에 "N/A" 문자열이 존재
        all_values = []
        for row in ts.iter_rows(values_only=True):
            all_values.extend(str(c) for c in row if c is not None)
        assert any("N/A" in v for v in all_values)

    def test_history_auto_filled_by_git_log(self):
        """T134: History 시트가 git log로 자동 채워지면 incomplete_sheets에서 빠짐."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        d = result.to_dict()
        # git log 성공 시 history_rows_written > 0, 실패 시 incomplete_sheets에 History 있음.
        # CI 환경에서 git 없으면 후자, 일반 dev 환경은 전자.
        assert (
            d["summary"].get("history_rows_written", 0) > 0
            or "History" in d["incomplete_sheets"]
        )

    def test_vba_macros_flag_false_for_xlsx_template(self):
        """deep-reviewer W2: 일반 xlsx template (VBA 없음) → vba_macros_preserved=False."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        # fixture는 plain Workbook이라 VBA 없음
        assert result.vba_macros_preserved is False
        d = result.to_dict()
        assert d["vba_macros_preserved"] is False

    def test_result_size_key_unified(self):
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        d = result.to_dict()
        assert "result_size_bytes" in d
        assert d["result_size_bytes"] > 0
