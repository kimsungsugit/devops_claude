"""33차 SwIT Coverage Report 빌더 회귀 — SwUT 패턴 차용.

SwUT는 30~32차에 17개 시나리오 커버. SwIT는 SwUT 시트 writer 그대로
import 재활용이라 SwUT 회귀가 SwIT에도 적용. 본 회귀는 SwIT 도구별
차이 (파일명 / doc_id_base / 결과 dataclass) + smoke + 시트 미발견
fallback 위주.
"""
from __future__ import annotations

import io
from pathlib import Path
import sys

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.swit_coverage_aggregator import (  # noqa: E402
    SwitCoverageBuildResult,
    build_swit_coverage_report,
)
from backend.services.swit_meta import SwitCoverageBuildMeta  # noqa: E402
from backend.services.swut_input_adapter import (  # noqa: E402
    EnvironmentData, ExecutionRow, FunctionCoverage, SwUTSession,
)


def _build_swit_template() -> bytes:
    """SwIT v2.02 빈 양식 — SwUT _build_coverage_template 와 동일 구조 가정."""
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


def _make_swit_session() -> SwUTSession:
    """Integration test session — SwUT와 동일 구조 (재활용)."""
    env = EnvironmentData(env_name="SWTE_01", component_name="SysOs_Main")
    env.test_cases = {"SwITC_SwUFn_0101.001": []}
    env.test_results = {
        "SwITC_SwUFn_0101.001": ExecutionRow(
            tc_name="SwITC_SwUFn_0101.001",
            component="SysOs_Main", passed=True,
        ),
    }
    env.function_coverage = [
        FunctionCoverage(unit_id="SwUFn_0101", name="SysOs_Main.init"),
    ]
    return SwUTSession(
        project_id="HDPDM01", version="v2.02_240219",
        source_kind="log_folder", source_path="/tmp/fake/v2.02_240219",
        environments=[env],
    )


def _make_swit_meta() -> SwitCoverageBuildMeta:
    return SwitCoverageBuildMeta(
        project_id="HDPDM01",
        release_sw_version="2.02",
        test_date="2024-02-19",
        test_engineer="JK Kim",
        doc_id_sequence="001",
        doc_id_base="HDPDM01-SwIT",
        asil_level="ASIL B",
    )


class TestBuildSwitCoverage:
    """SwIT Coverage Report builder smoke + structure."""

    def test_smoke_minimal(self):
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        assert isinstance(result, SwitCoverageBuildResult)
        assert result.ok
        assert result.xlsx_io.tell() == 0   # 처음으로 seek됨 (StreamingResponse 준비)
        assert result.result_size_bytes > 0

    def test_filename_has_swit_keyword_and_version(self):
        """파일명: '(HDPDM01)SwIT Coverage Report_v2.02_240219_R.xlsx'."""
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        assert "SwIT" in result.filename
        assert "HDPDM01" in result.filename
        assert "v2.02" in result.filename
        assert result.filename.endswith("_R.xlsx")

    def test_summary_contains_asil_keys(self):
        """30차 W21 + 31차 W29 ASIL summary keys 노출 (SwUT 동일)."""
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        for key in (
            "asil_distribution", "asil_b_function_ids",
            "asil_c_function_ids", "asil_d_function_ids",
            "asil_highlight_policy",
        ):
            assert key in result.summary, f"summary 키 '{key}' 누락"

    def test_summary_contains_basic_metrics(self):
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        s = result.summary
        assert s["environments"] == 1
        assert s["function_rows"] == 1
        assert s["passed"] == 1
        assert "template_sha256_12" in s
        assert "build_timestamp" in s

    def test_tool_qualification_present(self):
        """ISO 26262 ASIL audit evidence_class draft 정책."""
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        tq = result.tool_qualification
        assert tq["evidence_class"] == "auto-generated draft"
        assert "asil_a_usage" in tq
        assert "asil_b_c_d_usage" in tq


class TestSwitMissingSheetFallback:
    """일부 시트 미발견 시 incomplete_sheets에 표시 + 빌드 진행 (graceful)."""

    def test_cover_sheet_missing(self):
        """Cover 미발견 → warnings 누적, 빌드는 진행."""
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        wb.create_sheet("Test Summary")
        wb.create_sheet("1.Traceability")
        wb.create_sheet("2.Consistency")
        wb.create_sheet("3. Coverage")
        wb.create_sheet("History")
        buf = io.BytesIO()
        wb.save(buf)
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), buf.getvalue(),
        )
        assert result.ok
        assert any("Cover" in w for w in result.warnings)

    def test_traceability_sheet_missing(self):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        wb.create_sheet("Cover")
        wb.create_sheet("Test Summary")
        wb.create_sheet("2.Consistency")
        wb.create_sheet("3. Coverage")
        wb.create_sheet("History")
        buf = io.BytesIO()
        wb.save(buf)
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), buf.getvalue(),
        )
        assert result.ok
        assert any("1.Traceability" in w for w in result.warnings)

    def test_consistency_partial_when_swuds_not_provided(self):
        """SwUDS function_ids 미제공 → incomplete_sheets에 partial 표시."""
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
            swuds_function_ids=None,
        )
        assert result.ok
        assert any("Consistency" in s for s in result.incomplete_sheets)
        assert result.summary.get("consistency_swuds_compared") is False


class TestSwitAsilDistribution33:
    """SwUT _compute_asil_distribution 재활용 → SwIT summary에서도 동작."""

    def test_distribution_when_function_asil_map_provided(self):
        session = _make_swit_session()
        # function_asil_map 주입 (router의 _apply_function_asil_map 시뮬레이션)
        session.environments[0].function_asil_map = {"SwUFn_0101": "D"}
        result = build_swit_coverage_report(
            session, _make_swit_meta(), _build_swit_template(),
        )
        assert result.ok
        assert "ASIL_D" in result.summary["asil_distribution"]
        assert "SwUFn_0101" in result.summary["asil_d_function_ids"]


class TestSwitSwudsFunctionIds:
    """SwUDS function_ids 제공 시 2.Consistency 매핑 row 추가 + summary 갱신."""

    def test_consistency_summary_with_swuds_function_ids(self):
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
            swuds_function_ids={"SwUFn_0101"},
        )
        assert result.ok
        assert result.summary.get("consistency_swuds_compared") is True


class TestSwitMetaValidation:
    """validate_build_meta 패턴 — release_sw_version / test_date 형식."""

    def test_invalid_release_sw_version_raises(self):
        bad_meta = SwitCoverageBuildMeta(
            project_id="HDPDM01",
            release_sw_version="bad-version",
            test_date="2024-02-19",
            test_engineer="JK Kim",
        )
        with pytest.raises(Exception):  # noqa: B017
            build_swit_coverage_report(
                _make_swit_session(), bad_meta, _build_swit_template(),
            )

    def test_invalid_template_bytes_raises(self):
        """ZIP bomb / magic byte 검증 — non-xlsx bytes 거부."""
        with pytest.raises(Exception):  # noqa: B017
            build_swit_coverage_report(
                _make_swit_session(), _make_swit_meta(),
                template_bytes=b"not an xlsx",
            )


class TestSwitResultDataclass:
    """SwitCoverageBuildResult API — xlsx_bytes property + to_dict."""

    def test_xlsx_bytes_property_returns_full_content(self):
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        assert isinstance(result.xlsx_bytes, bytes)
        assert len(result.xlsx_bytes) == result.result_size_bytes

    def test_to_dict_includes_required_keys(self):
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        d = result.to_dict()
        for k in ("ok", "filename", "result_size_bytes", "warnings",
                  "incomplete_sheets", "summary", "tool_qualification"):
            assert k in d


class TestSwitFilenameSafeDate:
    """short_date 변환 — '2024-02-19' → '240219' 패턴."""

    def test_filename_short_date_format(self):
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), _build_swit_template(),
        )
        # short_date(2024-02-19) → 240219
        assert "240219" in result.filename


# ---------------------------------------------------------------------------
# 54차 T282/T283 — v2.02 양식 호환 회귀
# ---------------------------------------------------------------------------

def _build_v202_template() -> bytes:
    """SwIT v2.02 양식 mimic — "SW Version" / "HW Version" / B17 TC stats / B22 Requirements."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cover = wb.create_sheet("Cover")
    cover["B1"] = "Project"
    cover["B2"] = "ASIL Level"
    cover["B3"] = "Author"
    cover["B4"] = "Approver"

    # v2.02 양식: "1.Test Summary" + SW Version/HW Version + TC stats row + Requirements row
    ts = wb.create_sheet("1.Test Summary")
    ts["B1"] = "Project Name"
    ts["B2"] = "SW Version"      # v2.02 라벨
    ts["B3"] = "HW Version"      # v2.02 라벨
    ts["B4"] = "Test Date"
    ts["B5"] = "Test Engineer"
    ts["B6"] = "Final Test Result"
    # 신규 row — TC stats (Total/Tested/Passed/Failed/Blocked)
    ts["A17"] = "Total TC"
    # 신규 row — Requirements/Design Coverage
    ts["A22"] = "Requirements/Design Coverage"

    wb.create_sheet("1.Traceability")
    wb.create_sheet("2.Consistency")
    cov = wb.create_sheet("3.Coverage")
    cov["A6"] = "Unit ID"
    cov["B6"] = "Name"
    cov["C6"] = "Count"
    cov["D6"] = "Total"
    cov["E6"] = "Pass"
    wb.create_sheet("History")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestSwitV202LayoutCompat:
    """54차 T282/T283 — v2.02 양식 label 매칭 + TC stats + B22 fill."""

    def test_sw_version_label_filled(self):
        """v2.02 'SW Version' 라벨 옆 셀에 release_sw_version 채움."""
        template = _build_v202_template()
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), template,
        )
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        ts = wb["1.Test Summary"]
        # "SW Version" label은 B2 → value는 C2 (col+1)
        assert ts["C2"].value == "2.02"

    def test_hw_version_label_filled(self):
        """v2.02 'HW Version' 라벨 옆 셀에 hw_version 채움."""
        template = _build_v202_template()
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), template,
        )
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        ts = wb["1.Test Summary"]
        # HW Version 라벨 B3 → value C3 (col+1). default "1.00"
        assert ts["C3"].value == "1.00"

    def test_tc_stats_row_filled(self):
        """55-fix: 라벨 row=17이 헤더 (가로 배치), data는 row=18에 채움."""
        template = _build_v202_template()
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), template,
        )
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        ts = wb["1.Test Summary"]
        # 55-fix: "Total TC" 라벨 A17에 위치 → tc_stats_row=18 (data), col_start=1 (A)
        assert ts["A18"].value == 1   # Total
        assert ts["B18"].value == 1   # Tested
        assert ts["C18"].value == 1   # Passed
        assert ts["D18"].value == 0   # Failed
        assert ts["E18"].value == 0   # Blocked (inferred)
        assert result.summary.get("tc_stats_blocked_inferred") is True

    def test_requirements_row_filled_with_swits(self):
        """B22 Requirements/Design Coverage row에 SwITS 표기."""
        template = _build_v202_template()
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), template,
        )
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        ts = wb["1.Test Summary"]
        # Requirements/Design Coverage row=22, B22(col 2)에 "SwITS"
        assert ts["B22"].value == "SwITS"

    def test_v301_backward_compat(self):
        """v3.01 양식 (Release Name(SW) 라벨)도 정상 채움 — backward compat."""
        # 기존 _build_swit_template은 Release Name(SW) 라벨 사용 (v3.01 호환)
        template = _build_swit_template()
        result = build_swit_coverage_report(
            _make_swit_session(), _make_swit_meta(), template,
        )
        # v3.01 호환 — fill 성공 + tc_stats_blocked_inferred 없음 (v2.02 row 없음)
        assert result.ok
        assert "tc_stats_blocked_inferred" not in result.summary


class TestSwutBuilderV202InspectFix54:
    """54-fix C1 — SwUT Coverage 빌더가 v2.02 template 잘못 입력 받아도 silent 빈 셀 차단.

    SwUT 라우터에 사용자가 SwIT v2.02 양식 path를 잘못 지정 시:
    - 이전: hardcode "Release Name(SW)" 라벨 미발견 → silent 빈 셀
    - 54-fix: inspect_swit_layout → v2.02 라벨 매핑 → SW Version 옆 자동 채움
    """

    def test_swut_coverage_with_v202_template_fills_sw_version(self):
        """SwUT 빌더에 v2.02 template 입력 → SW Version cell 자동 채움."""
        from backend.services.swut_coverage_aggregator import (
            CoverageBuildMeta, build_coverage_report,
        )
        meta = CoverageBuildMeta(
            project_id="HDPDM01",
            release_sw_version="1.0.5",
            test_date="2024-02-19",
            test_engineer="JK Kim",
            doc_id_sequence="001",
        )
        result = build_coverage_report(
            _make_swit_session(), meta, _build_v202_template(),
        )
        assert result.ok
        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        # v2.02 "1.Test Summary" 시트의 SW Version 옆 셀
        ts = wb["1.Test Summary"]
        # SW Version 라벨 B2 → value C2 (col+1)
        assert ts["C2"].value == "1.0.5"

    def test_swut_coverage_with_v301_template_backward_compat(self):
        """SwUT 기존 v3.01 양식도 정상 채움 — fallback_to_v301."""
        from backend.services.swut_coverage_aggregator import (
            CoverageBuildMeta, build_coverage_report,
        )
        meta = CoverageBuildMeta(
            project_id="HDPDM01",
            release_sw_version="1.0.5",
            test_date="2024-02-19",
            test_engineer="JK Kim",
            doc_id_sequence="001",
        )
        # 기존 v3.01 호환 template (Release Name(SW) 라벨)
        result = build_coverage_report(
            _make_swit_session(), meta, _build_swit_template(),
        )
        assert result.ok
        # v3.01 → fallback_to_v301=True, tc_stats_blocked_inferred 부재
        assert "tc_stats_blocked_inferred" not in result.summary
