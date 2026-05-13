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

    # 17차 T171: 2.Consistency 시트 (Coverage 대칭)
    wb.create_sheet("2.Consistency")

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
        """deep-reviewer W5/ISO F3: placeholder 시트는 incomplete_sheets에 명시.

        15차: 2.Consistency는 자체 일관성 4 row 완료, SwUDS↔SwUTS 비교만 미완 →
        라벨이 ``2.Consistency (SwUDS 비교 partial — v3.02)`` 로 변경.
        """
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        d = result.to_dict()
        assert "1.Traceability" in d["incomplete_sheets"]
        assert any("2.Consistency" in s for s in d["incomplete_sheets"])
        # 15차: 자체 일관성 4 row 작성됨
        assert d["summary"].get("consistency_self_check_rows") == 4

    # ── 15차 — 2.Consistency 자체 일관성 ─────────────────────────────────

    def test_consistency_self_check_writes_4_rows(self):
        """15차: 2.Consistency 시트에 4개 일관성 row 작성."""
        import openpyxl
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        cons = wb["2.Consistency"]
        # 헤더 (row 3) + 4 data row = 4-7
        assert cons.cell(3, 1).value == "Item"
        assert cons.cell(3, 4).value == "Result"
        items = [cons.cell(r, 1).value for r in range(4, 8)]
        assert all(items), f"row 4-7 모두 채워져야 함: {items}"
        # 4 result 값이 PASS 또는 FAIL
        results = [cons.cell(r, 4).value for r in range(4, 8)]
        assert all(r in ("PASS", "FAIL") for r in results), f"result {results}"

    def test_consistency_passes_for_well_formed_session(self):
        """15차: _make_session()의 정상 데이터는 4 row 모두 PASS."""
        import openpyxl
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        cons = wb["2.Consistency"]
        results = [cons.cell(r, 4).value for r in range(4, 8)]
        assert all(r == "PASS" for r in results), f"all PASS expected, got {results}"

    def test_consistency_fails_for_missing_test_results(self):
        """15차: TC가 test_results에 없으면 'TC 실행 결과 완전성' FAIL."""
        from backend.services.swut_input_adapter import (
            EnvironmentData, ExecutionRow, FunctionCoverage, SwUTSession,
        )
        # 환경: test_cases는 2개 TC지만 test_results는 1개만 → 누락
        env = EnvironmentData(
            env_name="SWTE_01",
            component_name="X",
            test_cases={"SwUFn_0001.001": [object()], "SwUFn_0001.002": [object()]},
            test_results={"SwUFn_0001.001": ExecutionRow(tc_name="SwUFn_0001.001", passed=True)},
            function_coverage=[FunctionCoverage(unit_id="SwUFn_0001", name="X")],
        )
        session = SwUTSession(environments=[env])
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())

        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        cons = wb["2.Consistency"]
        # row 6 = "TC 실행 결과 완전성"
        for r in range(4, 8):
            item = str(cons.cell(r, 1).value or "")
            if "실행" in item:
                assert cons.cell(r, 4).value == "FAIL", \
                    f"누락된 test_result로 FAIL이어야 함: {cons.cell(r, 4).value}"
                break
        # warnings에 FAIL 보고
        assert any("FAIL" in w for w in result.warnings)

    def test_consistency_summary_includes_row_count(self):
        """15차: summary에 consistency_self_check_rows=4 포함."""
        session = _make_session()
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, _build_coverage_template())
        assert result.summary.get("consistency_self_check_rows") == 4

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

    def test_traceability_matches_company_format(self):
        """T136: 회사 row label `SwUTC_<fn_id>` (인덱스 없음) 매칭 검증."""
        import io as _io

        import openpyxl
        from backend.services.swut_input_adapter import (
            EnvironmentData,
            ExecutionRow,
            FunctionCoverage,
            SwUTSession,
        )

        # session: SwUFn_0001 함수, TC name = SwUFn_0001.001
        env = EnvironmentData(
            env_name="SWTE_X",
            component_name="X",
            test_cases={"SwUFn_0001.001": [object()]},
            test_results={"SwUFn_0001.001": ExecutionRow(tc_name="SwUFn_0001.001", passed=True)},
            function_coverage=[FunctionCoverage(unit_id="SwUFn_0001", name="X")],
        )
        session = SwUTSession(environments=[env])

        # 회사 v3.01 형식 fixture — header row 12, 데이터 row 14 (B열: SwUTC_SwUFn_0001)
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        wb.create_sheet("Cover")
        wb.create_sheet("Test Summary")
        # 1.Traceability — minimal: header row 1, 50개 SwUFn 컬럼 + 데이터 row 2~6
        trace = wb.create_sheet("1.Traceability")
        for i in range(50):
            trace.cell(row=1, column=4 + i, value=f"SwUFn_{i+1:04d}")
        # 회사 row format: 인덱스 없는 `SwUTC_SwUFn_0001`
        trace.cell(row=2, column=2, value="SwUTC_SwUFn_0001")
        wb.create_sheet("2.Consistency")
        wb.create_sheet("3. Coverage").cell(row=1, column=1, value="Statement Coverage")
        wb["3. Coverage"].cell(row=6, column=1, value="Unit ID")
        wb.create_sheet("History").cell(row=1, column=1, value="■ Revision History")
        buf = _io.BytesIO()
        wb.save(buf)
        template = buf.getvalue()

        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_coverage_report(session, meta, template)
        # T136 fix: traceability_o_cells > 0
        assert result.summary["traceability_o_cells"] >= 1
        # incomplete_sheets에서 1.Traceability 제거됨
        assert "1.Traceability" not in result.incomplete_sheets

    def test_build_meta_base_default_factory(self):
        """T137: BuildMetaBase 기본 생성 + 3 property 동작."""
        from backend.services.swut_meta import BuildMetaBase
        m = BuildMetaBase()
        assert m.project_id == "HDPDM01"
        assert m.final_test_result == "PASS"
        assert m.build_timestamp  # 빈 string 아님
        # property: override 없으면 default 반환
        assert m.author == ""
        m2 = BuildMetaBase(default_author="JK", test_engineer="JE")
        assert m2.author == "JE"  # test_engineer 우선
        m3 = BuildMetaBase(default_approver="A", approver_override="B")
        assert m3.approver == "B"  # override 우선

    def test_subclass_inheritance_preserves_signature(self):
        """T137: CoverageBuildMeta / SutrBuildMeta가 BuildMetaBase 상속 후도 기존 인자 호환."""
        cov = CoverageBuildMeta(
            release_sw_version="1.01.05", test_date="2024-02-19",
            project_id="HDPDM01", asil_level="ASIL A",
        )
        assert cov.final_test_result == "PASS"  # base default
        sutr = SutrBuildMeta(
            release_sw_version="1.01.05", test_date="2024-02-19",
        )
        assert sutr.final_test_result == "OK"  # subclass override
        assert sutr.target_coverage == 1.0
        assert sutr.target_pass_ratio == 1.0
        assert sutr.doc_id_base == "HDPDM01-SUTR"  # subclass override


# ---------------------------------------------------------------------------
# 30차 W21 — ASIL distribution + 시각 강조
# ---------------------------------------------------------------------------

class TestAsilDistribution21:
    """30차 W21 T221 — _compute_asil_distribution + build_coverage_report summary."""

    def test_distribution_counts_per_asil(self):
        """30차 W21 + 31차 W29: return (dist, ids_by_asil dict {B,C,D})."""
        from backend.services.swut_coverage_aggregator import _compute_asil_distribution
        from backend.services.swut_input_adapter import FunctionCoverage
        rows = [
            FunctionCoverage(unit_id="SwUFn_0101", name="x"),
            FunctionCoverage(unit_id="SwUFn_0102", name="y"),
            FunctionCoverage(unit_id="SwUFn_0103", name="z"),
            FunctionCoverage(unit_id="SwUFn_0104", name="w"),
            FunctionCoverage(unit_id="SwUFn_0105", name="u"),  # 매핑 없음 → UNKNOWN
        ]
        asil_map = {
            "SwUFn_0101": "A",
            "SwUFn_0102": "B",
            "SwUFn_0103": "D",
            "SwUFn_0104": "D",
        }
        dist, ids_by_asil = _compute_asil_distribution(rows, asil_map)
        assert dist == {"ASIL_A": 1, "ASIL_B": 1, "ASIL_D": 2, "UNKNOWN": 1}
        assert ids_by_asil["D"] == ["SwUFn_0103", "SwUFn_0104"]
        assert ids_by_asil["B"] == ["SwUFn_0102"]
        assert ids_by_asil["C"] == []

    def test_distribution_empty_when_no_function_rows(self):
        from backend.services.swut_coverage_aggregator import _compute_asil_distribution
        dist, ids_by_asil = _compute_asil_distribution([], {})
        assert dist == {}
        assert ids_by_asil == {"B": [], "C": [], "D": []}

    def test_distribution_all_unknown_when_no_asil_map(self):
        from backend.services.swut_coverage_aggregator import _compute_asil_distribution
        from backend.services.swut_input_adapter import FunctionCoverage
        rows = [FunctionCoverage(unit_id=f"SwUFn_010{i}") for i in range(3)]
        dist, ids_by_asil = _compute_asil_distribution(rows, {})
        assert dist == {"UNKNOWN": 3}
        assert ids_by_asil == {"B": [], "C": [], "D": []}

    def test_build_coverage_includes_asil_distribution_in_summary(self):
        """build_coverage_report summary에 asil_distribution + B/C/D 키 존재."""
        session = _make_session()
        # session.environments[0]에 function_asil_map 주입
        session.environments[0].function_asil_map = {
            session.environments[0].function_coverage[0].unit_id: "D",
        } if session.environments[0].function_coverage else {}
        meta = CoverageBuildMeta(
            release_sw_version="1.01.05",
            test_date="2024-02-19",
            test_engineer="JK Kim",
            doc_id_sequence="851",
        )
        template = _build_coverage_template()
        result = build_coverage_report(session, meta, template)
        assert result.ok
        assert "asil_distribution" in result.summary
        # 31차 W29: B/C/D 모두 노출
        assert "asil_b_function_ids" in result.summary
        assert "asil_c_function_ids" in result.summary
        assert "asil_d_function_ids" in result.summary
        # 매핑된 함수만큼 카운트 + 나머지 UNKNOWN
        assert sum(result.summary["asil_distribution"].values()) == result.summary["function_rows"]


class TestAsilBCDistribution31:
    """31차 W29: ASIL B/C도 함수 ID 별도 노출 + summary 키."""

    def test_summary_includes_asil_b_function_ids(self):
        session = _make_session()
        if session.environments[0].function_coverage:
            fid = session.environments[0].function_coverage[0].unit_id
            session.environments[0].function_asil_map = {fid: "B"}
        meta = CoverageBuildMeta(
            release_sw_version="1.01.05", test_date="2024-02-19",
            test_engineer="JK Kim", doc_id_sequence="851",
        )
        result = build_coverage_report(session, meta, _build_coverage_template())
        assert result.ok
        if session.environments[0].function_coverage:
            assert len(result.summary["asil_b_function_ids"]) >= 1

    def test_summary_includes_asil_c_function_ids(self):
        session = _make_session()
        if session.environments[0].function_coverage:
            fid = session.environments[0].function_coverage[0].unit_id
            session.environments[0].function_asil_map = {fid: "C"}
        meta = CoverageBuildMeta(
            release_sw_version="1.01.05", test_date="2024-02-19",
            test_engineer="JK Kim", doc_id_sequence="851",
        )
        result = build_coverage_report(session, meta, _build_coverage_template())
        assert result.ok
        if session.environments[0].function_coverage:
            assert len(result.summary["asil_c_function_ids"]) >= 1

    def test_sutr_summary_includes_b_c_d_function_ids(self):
        """SUTR builder도 Coverage와 대칭 — B/C/D 키 노출."""
        session = _make_session()
        if session.environments[0].function_coverage:
            fid = session.environments[0].function_coverage[0].unit_id
            session.environments[0].function_asil_map = {fid: "B"}
        meta = SutrBuildMeta(
            release_sw_version="1.01.05", test_date="2024-02-19",
            test_engineer="JK Kim", doc_id_sequence="851",
        )
        result = build_sutr(session, meta, _build_sutr_template())
        assert result.ok
        assert "asil_b_function_ids" in result.summary
        assert "asil_c_function_ids" in result.summary
        assert "asil_d_function_ids" in result.summary


class TestSutrTestLogAsil31:
    """31차 W27: SUTR Test Log 시트 col+4 Function ID + col+5 ASIL 컬럼."""

    def test_test_log_writes_function_id_column(self):
        """TC name에서 SwUFn_NNNN 추출되어 col+4에 기록."""
        import openpyxl
        from backend.services.swut_sutr_aggregator import _write_test_log
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "Test Case ID"

        session = _make_session()
        # session.environments[0].test_cases 에 SwUFn 포함 TC name 보장
        env = session.environments[0]
        env.test_cases = {"SwUTC_SwUFn_0103.001": "...", "non_swufn_tc": "..."}
        env.test_results = {}

        n = _write_test_log(ws, session, function_asil_map={"SwUFn_0103": "D"})
        assert n >= 1
        # row 2 (start_row = pos[0] + 1) — SwUTC_SwUFn_0103 또는 non_swufn_tc 중
        # 정렬상 'SwUTC_SwUFn_0103.001'이 먼저 (S < n in ASCII)
        # col+4에 함수 ID
        col4_values = [ws.cell(r, 5).value for r in (2, 3)]
        assert "SwUFn_0103" in col4_values

    def test_test_log_writes_asil_column_with_d_highlight(self):
        """ASIL D 함수 row의 col+5 셀에 빨간 강조."""
        import openpyxl
        from backend.services.swut_sutr_aggregator import _write_test_log
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "Test Case ID"

        session = _make_session()
        env = session.environments[0]
        env.test_cases = {"SwUTC_SwUFn_0103.001": "..."}
        env.test_results = {}

        _write_test_log(ws, session, function_asil_map={"SwUFn_0103": "D"})
        # ASIL D row의 col+5 (col=1, col+5=6) — fill 적용
        cell = ws.cell(2, 6)
        assert cell.value == "ASIL D"
        assert "FFC7CE" in str(cell.fill.fgColor.rgb).upper()

    def test_test_log_empty_function_asil_map_writes_blank_asil_column(self):
        """function_asil_map None 또는 빈 dict면 ASIL 컬럼은 빈 값."""
        import openpyxl
        from backend.services.swut_sutr_aggregator import _write_test_log
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "Test Case ID"

        session = _make_session()
        env = session.environments[0]
        env.test_cases = {"SwUTC_SwUFn_0103.001": "..."}
        env.test_results = {}

        _write_test_log(ws, session, function_asil_map=None)
        # function_id는 추출되나 ASIL은 빈 string
        assert ws.cell(2, 5).value == "SwUFn_0103"
        assert ws.cell(2, 6).value == ""

    def test_test_log_col4_5_non_empty_emits_warning_to_session(self):
        """31-fix D10: col+4/5 영역에 기존 데이터 있으면 out_warnings 누적."""
        import openpyxl
        from backend.services.swut_sutr_aggregator import _write_test_log
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "Test Case ID"
        # col+4/5 (5, 6)에 양식 사용 중 시뮬레이션
        ws.cell(1, 5).value = "Tester"   # 회사가 col+4를 Tester로 사용
        ws.cell(1, 6).value = "Date"     # col+5를 Date로 사용

        session = _make_session()
        env = session.environments[0]
        env.test_cases = {"SwUTC_SwUFn_0103.001": "..."}
        env.test_results = {}

        warnings: list[str] = []
        _write_test_log(
            ws, session,
            function_asil_map={"SwUFn_0103": "D"},
            out_warnings=warnings,
        )
        # logger.warning + out_warnings 둘 다 — sufficient evidence
        assert any("col+4/5 not empty" in w for w in warnings)
        assert any("audit reviewer 확인" in w for w in warnings)

    def test_test_log_col4_5_empty_no_warning(self):
        """31-fix D10: col+4/5 빈 영역이면 warning 0."""
        import openpyxl
        from backend.services.swut_sutr_aggregator import _write_test_log
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "Test Case ID"
        # col+4/5 빈 상태 (default)

        session = _make_session()
        env = session.environments[0]
        env.test_cases = {"SwUTC_SwUFn_0103.001": "..."}
        env.test_results = {}

        warnings: list[str] = []
        _write_test_log(
            ws, session,
            function_asil_map={"SwUFn_0103": "D"},
            out_warnings=warnings,
        )
        assert not any("col+4/5" in w for w in warnings)


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

    def test_pass_ratio_marked_user_input_when_tested_zero(self):
        """deep-reviewer X7 + 24차: tested=0이면 ratio 셀에 노란 강조 + 안내 텍스트.

        24차 이전: silent "N/A" 텍스트
        24차 이후: "▶ 사용자 입력 필요 — 실행된 TC 없음..." + 노란 fill
        audit reviewer가 데이터 부재를 즉시 인지.
        """
        from backend.services.swut_input_adapter import EnvironmentData
        session = SwUTSession(environments=[EnvironmentData(env_name="EMPTY")])
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        import io as _io
        wb = openpyxl.load_workbook(_io.BytesIO(result.xlsm_bytes), keep_vba=True)
        ts = wb["Test Summary"]
        # "▶ 사용자 입력 필요" 텍스트 + 노란 fill 셀 발견
        marked_cells = []
        for row in ts.iter_rows():
            for c in row:
                if c.value and "사용자 입력 필요" in str(c.value):
                    fg = str(getattr(c.fill.fgColor, "rgb", "") or "").upper()
                    marked_cells.append((c.coordinate, c.value, fg))
        assert len(marked_cells) >= 2, f"Actual Coverage / Actual Pass ratio 양쪽 강조: {marked_cells}"
        # 모두 노란 fill (FFEB9C)
        assert all("FFEB9C" in fg for _, _, fg in marked_cells)
        # 안내 텍스트
        all_text = " ".join(str(v) for _, v, _ in marked_cells)
        assert "TC 없음" in all_text or "VectorCAST" in all_text

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

    # ── 17차 T171: SUTR 2.Consistency 시트 ─────────────────────────────────

    def test_sutr_consistency_writes_4_rows_without_swuds(self):
        """T171: SUTR 빌드도 Coverage와 같은 자체 일관성 4 row 작성."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsm_bytes), keep_vba=True)
        cons = wb["2.Consistency"]
        # 헤더 (row 3) + 4 data row (4-7)
        assert cons.cell(3, 1).value == "Item"
        items = [cons.cell(r, 1).value for r in range(4, 8)]
        assert all(items), f"row 4-7 모두 채워져야 함: {items}"
        results = [cons.cell(r, 4).value for r in range(4, 8)]
        assert all(r in ("PASS", "FAIL") for r in results)

    def test_sutr_consistency_writes_5_rows_with_swuds(self):
        """T171: swuds_function_ids 제공 시 row 5 (SwUDS↔SwUTS) 추가."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        # session의 function_coverage에 SwUFn_0101, SwUFn_0103 있음 (위 _make_session 참조)
        result = build_sutr(
            session, meta, _build_sutr_template(),
            swuds_function_ids={"SwUFn_0101", "SwUFn_0103"},
        )

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsm_bytes), keep_vba=True)
        cons = wb["2.Consistency"]
        items = [str(cons.cell(r, 1).value or "") for r in range(4, 10)]
        swuds_rows = [item for item in items if "SwUDS" in item]
        assert swuds_rows, f"SwUDS 매핑 row 없음: {items}"

    def test_sutr_summary_includes_consistency_keys(self):
        """T171: summary에 17차 신규 키 2개 포함."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        # 1) swuds 미제공
        r1 = build_sutr(session, meta, _build_sutr_template())
        assert r1.summary.get("consistency_self_check_rows") == 4
        assert r1.summary.get("consistency_swuds_compared") is False
        # 2) swuds 제공
        r2 = build_sutr(
            session, meta, _build_sutr_template(),
            swuds_function_ids={"SwUFn_0101", "SwUFn_0103"},
        )
        assert r2.summary.get("consistency_self_check_rows") == 5
        assert r2.summary.get("consistency_swuds_compared") is True

    def test_sutr_consistency_partial_label_kept_without_swuds(self):
        """T171: swuds 미제공 시 incomplete_sheets에 partial 라벨 유지."""
        session = _make_session()
        meta = SutrBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")
        result = build_sutr(session, meta, _build_sutr_template())
        assert any("partial" in s for s in result.incomplete_sheets)
