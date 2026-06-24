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


def _fault_injection_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FI_Test Case"
    ws.cell(9, 2).value = 1
    ws.cell(9, 3).value = "SwIFITC_01"
    ws.cell(9, 15).value = "ExpectedA"
    ws.cell(9, 17).value = "ActualA"
    ws.cell(10, 4).value = 1
    ws.cell(10, 5).value = "FI"
    ws.cell(10, 6).value = "AOR"
    ws.cell(10, 15).value = "0"
    ws.cell(10, 16).value = "1"
    ws.cell(10, 17).value = "0"
    ws.cell(10, 18).value = "1"
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
        fault_injection_bytes=_fault_injection_workbook(),
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
    assert wb["3.IT301"]["C85"].value == 1
    assert wb["3.IT301"]["E85"].value == 1
    assert wb["3.IT301"]["F85"].value == 1
    assert wb["3.IT301"]["C102"].value == "식별된 결함"
    assert wb["3.IT301"]["C103"].value == "해당사항 없음"
    assert wb["Summary"]["G20"].value == "X"


class TestSwitcrCoverAndSummary96Final:
    """라운드 96-final QA fix — SwITCR Cover stamp (이전 완전 미스탬프 Critical)
    + Summary O열 시트명 rename 동기 (INDIRECT #REF! 차단)."""

    @staticmethod
    def _meta():
        from backend.services.swit_comprehensive_aggregator import SwitcrBuildMeta
        return SwitcrBuildMeta(
            project_id="KJPDS02", release_sw_version="0.10",
            test_date="2026-06-04", test_engineer="주희영",
            default_author="JK Kim", default_approver="CH In",
            doc_filename_pattern="(KJPDS02_PV_SwITCR) X_v{version}_{date}_R.xlsm",
        )

    def test_switcr_cover_stamps_xxxx_placeholders(self):
        import openpyxl

        from backend.services.swit_comprehensive_aggregator import _write_switcr_cover
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Cover"
        ws["I2"] = "Author"
        ws["J2"] = "Reviewer"
        ws["K2"] = "Approver"
        ws["C26"] = "Document ID"
        ws["D26"] = "HKY-[P_Name]-SwITCR-28A1"
        ws["C27"] = "Version"
        ws["D27"] = "v0.10"
        ws["C28"] = "Status"
        ws["D28"] = "Unspecified"
        ws["C29"] = "Date"
        ws["D29"] = "202X.XX.XX"
        ws["C30"] = "Author"
        ws["D30"] = "XXXX"
        warns: list[str] = []
        _write_switcr_cover(ws, self._meta(), {}, out_warnings=warns)
        assert ws["D26"].value == "HKY-KJPDS02_PV-SwITCR-28A1"
        assert ws["D28"].value == "DRAFT — PENDING REVIEW"
        assert ws["D29"].value == "2026.06.04"
        assert ws["D30"].value == "주희영"  # test_engineer 우선
        assert ws["J2"].value == "Reviewer"  # 라벨 보존
        assert ws["I3"].value == "주희영"
        assert ws["K3"].value == "CH In"

    def test_summary_o_col_synced_to_renamed_sheets(self):
        import openpyxl

        from backend.services.swit_comprehensive_aggregator import _write_summary_sheet
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        _write_summary_sheet(ws, self._meta(), {})
        assert ws.cell(20, 15).value == "(해당X)5.IT501"
        assert ws.cell(21, 15).value == "(해당X)6.IT601"
        assert ws.cell(23, 15).value == "(해당X)8.IT801"
        # IT802는 8.IT801 시트 내 섹션 — 존재하지 않는 '8.IT802' stamp 금지
        assert ws.cell(24, 15).value == "(해당X)8.IT801"


class TestSwitcrCoverDeepReviewerW1W2:
    """deep-reviewer 96-final W1/W2 — 비-trio fallback + O열 동적 참조."""

    def test_non_trio_template_fallback_writes_reviewer_approver(self):
        import openpyxl

        from backend.services.swit_comprehensive_aggregator import (
            SwitcrBuildMeta,
            _write_switcr_cover,
        )
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Cover"
        # 세로 단독 kv 라벨 (가로 trio 없음)
        ws["B5"] = "Reviewer"
        ws["B7"] = "Approver"
        meta = SwitcrBuildMeta(
            project_id="KJPDS02", release_sw_version="0.10",
            test_date="2026-06-04", default_approver="CH In",
        )
        _write_switcr_cover(ws, meta, {}, out_warnings=[])
        # fallback 경로 — Approver 기입 + Reviewer 빈 값 노란
        assert ws["C7"].value == "CH In"
        assert str(ws["C5"].value or "").startswith("▶")

    def test_summary_o_col_resolves_actual_names(self):
        import openpyxl

        from backend.services.swit_comprehensive_aggregator import (
            SwitcrBuildMeta,
            _write_summary_sheet,
        )
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        # rename이 일부만 적용된 변형: 5.IT501은 rename됨, 6.IT601은 원명 유지
        wb.create_sheet("(해당X)5.IT501")
        wb.create_sheet("6.IT601")
        meta = SwitcrBuildMeta(
            project_id="KJPDS02", release_sw_version="0.10", test_date="2026-06-04",
        )
        _write_summary_sheet(ws, meta, {})
        assert ws.cell(20, 15).value == "(해당X)5.IT501"
        assert ws.cell(21, 15).value == "6.IT601"  # 원명 유지분은 원명 참조 (desync 차단)


def _switcv_workbook_formula_summary() -> bytes:
    """요약셀(E5..G6)을 비워 수식→data_only None 을 모사. 실제 SwITCV는 이 셀들이
    회사 템플릿 수식이라 openpyxl이 cached=None 으로 저장한다. 데이터행은 SwITCV
    function/call 경로와 동일하게 O/X·count·exception 모두 리터럴."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "4.Coverage"
    # E5..G6 미기입 (None) — 수식 캐시 부재 재현
    rows = [
        # unit_id, name, func_result, func_exc, ccount, ctotal, call_result, call_exc
        ("SwUFn_0101", "FuncA", "X", "O", 2, 3, "X", "O"),
        ("SwUFn_0102", "FuncB", "O", None, 3, 3, "O", None),
        ("SwUFn_0103", "FuncC", "O", None, None, None, "O", None),
    ]
    for i, (uid, nm, fr, fe, cc, ct, cr, ce) in enumerate(rows):
        r = 11 + i
        ws.cell(r, 4).value = uid
        ws.cell(r, 5).value = nm
        ws.cell(r, 6).value = fr
        if fe is not None:
            ws.cell(r, 7).value = fe
        if cc is not None:
            ws.cell(r, 8).value = cc
        if ct is not None:
            ws.cell(r, 9).value = ct
        ws.cell(r, 10).value = cr
        if ce is not None:
            ws.cell(r, 11).value = ce
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_load_workbook_summary_computes_from_rows_when_summary_blank():
    """후속 결함 회귀 — 요약셀이 수식(data_only None)이어도 roll-up이 데이터행에서
    함수/호출 fail·exception 을 정확 집계 (거짓 100% 커버리지 차단). 이전엔 None→0
    으로 fail/exception 이 0 처리되어 coverage_fail_details(정상)와 모순이었다."""
    from backend.services.swit_comprehensive_aggregator import _load_workbook_summary
    out = _load_workbook_summary(_switcv_workbook_formula_summary())
    assert out["functions_total"] == 3
    assert out["functions_fail_count"] == 1
    assert out["functions_exception_count"] == 1
    assert out["function_calls_total"] == 3
    assert out["function_calls_fail_count"] == 1
    assert out["function_calls_exception_count"] == 1
    assert len(out["coverage_fail_details"]) == 2  # func X + call X (동일 행)


def test_load_workbook_summary_prefers_literal_summary_cells():
    """셀에 리터럴 캐시값이 있으면(외부 재계산본) 데이터행 집계보다 우선."""
    from backend.services.swit_comprehensive_aggregator import _load_workbook_summary
    out = _load_workbook_summary(_switcv_workbook())  # E5=570/F5=1/G5=1 리터럴
    assert out["functions_total"] == 570
    assert out["functions_fail_count"] == 1
    assert out["functions_exception_count"] == 1
