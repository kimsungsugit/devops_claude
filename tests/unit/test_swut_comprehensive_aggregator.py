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
                "signature": "void FunctionA(void)",
                "body": "switch (mode) { default: return E_NOT_OK; }",
                "calls": [],
                "used_globals": [],
            }
        },
    )

    assert len(failures) == 1
    assert "switch/default defensive logic" in failures[0]["reason"]
    assert "C code evidence:" in failures[0]["reason"]
    assert "negative/default-path TC" in failures[0]["action"]
    assert "Review basis:" in failures[0]["action"]
    assert "Full C function:" in failures[0]["action"]
    assert "void FunctionA(void)" in failures[0]["action"]
    assert "default:" in failures[0]["c_evidence"]


def test_coverage_failures_classifies_register_self_test_not_range():
    failures = _coverage_failures(
        [
            FunctionCoverage(
                unit_id="SwUFn_0002",
                name="u8s_Register_Test",
                branch=CoverageStats(covered=3, total=5),
            )
        ],
        {
            "u8s_Register_Test": {
                "name": "u8s_Register_Test",
                "file": "SysCtrl_Main_PDS.c",
                "body": "ECCIE &= ~u8g_MAX; if (u8t_Register_InitialValue == u8g_CLR) { return OK; }",
                "calls": [],
                "used_globals": [],
            }
        },
    )

    assert "hardware register self-test" in failures[0]["reason"]
    assert "range or boundary" not in failures[0]["reason"]


def test_coverage_failures_classifies_interpolation_guard():
    failures = _coverage_failures(
        [
            FunctionCoverage(
                unit_id="SwUFn_0003",
                name="s16s_ApiIn_InterpolateTemperature",
                statement=CoverageStats(covered=8, total=9),
            )
        ],
        {
            "s16s_ApiIn_InterpolateTemperature": {
                "name": "s16s_ApiIn_InterpolateTemperature",
                "file": "ApiIn_Main_PDS.c",
                "body": "if ((s32t_Adc2 - s32t_Adc1) == (S32)0) { s32t_TempInterpolated = s32t_Temp1; }",
                "calls": [],
                "used_globals": [],
            }
        },
    )

    assert "interpolation or divide-by-zero guard" in failures[0]["reason"]
    assert "lookup-table boundary/interpolation" in failures[0]["action"]


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


# ---------------------------------------------------------------------------
# 라운드 96-final QA fix — C-5 (UT201 FI 마킹) + W-6 3건 (라벨행 보존)
# ---------------------------------------------------------------------------

_USER_INPUT_YELLOW = "FFFFEB9C"


def _meta_96final() -> SwutcrBuildMeta:
    return SwutcrBuildMeta(
        project_id="KJPDS02",
        project_full_name="KJPDS02",
        release_sw_version="1.01",
        test_date="2025-12-05",
        test_engineer="주희영",
    )


class TestUt201FaultInjection96Final:
    """C-5 — Fault Injection 실측 config 키 부재 시 노란 사용자입력 마킹.

    이전 fallback(total=함수 수, passed=failed==0이면 total)은 FI 실측 부재 시
    측정한 것처럼 보이는 수치(예: 1014/1014)를 무표식 기입 — 24차 silent N/A
    제거 정책 위반 (fabrication). 키 존재 시에는 기존대로 실측 stamp.
    """

    def test_fi_keys_absent_marks_user_input_and_warns(self):
        from backend.services.swut_comprehensive_aggregator import _write_ut201
        wb = openpyxl.Workbook()
        ws = wb.active
        warns: list[str] = []
        cfg = {"swutcr_metadata": {"tool_name": "VectorCAST"}}
        _write_ut201(ws, _meta_96final(), {"swutcr_qualified_function_count": 570},
                     cfg, warns)
        assert ws.cell(85, 3).value == 570  # 함수 수는 정상 stamp
        # E85/F85/C90 — placeholder 텍스트 + 노란 fill
        for row, col in ((85, 5), (85, 6), (90, 3)):
            assert str(ws.cell(row, col).value or "").startswith("▶"), (
                f"({row},{col}) placeholder 미기입: {ws.cell(row, col).value!r}"
            )
            assert ws.cell(row, col).fill.start_color.rgb == _USER_INPUT_YELLOW
        # 파생 수식(G85/H85)은 미기입 — placeholder operand #VALUE! 차단
        assert ws.cell(85, 7).value is None
        assert ws.cell(85, 8).value is None
        assert any("fault injection 실측 미제공" in w for w in warns)

    def test_fi_keys_present_stamps_measured_values(self):
        from backend.services.swut_comprehensive_aggregator import _write_ut201
        wb = openpyxl.Workbook()
        ws = wb.active
        warns: list[str] = []
        cfg = {"swutcr_metadata": {
            "fault_injection_total": 402,
            "fault_injection_passed": 400,
        }}
        _write_ut201(ws, _meta_96final(), {}, cfg, warns)
        assert ws.cell(85, 5).value == 402
        assert ws.cell(85, 6).value == 400
        assert ws.cell(85, 7).value == "=E85-F85"
        assert ws.cell(90, 3).value == "Fail TC 2건"
        assert not any("fault injection" in w for w in warns)

    def test_fi_all_passed_writes_none_note(self):
        from backend.services.swut_comprehensive_aggregator import _write_ut201
        wb = openpyxl.Workbook()
        ws = wb.active
        cfg = {"swutcr_metadata": {
            "fault_injection_total": 402,
            "fault_injection_passed": 402,
        }}
        _write_ut201(ws, _meta_96final(), {}, cfg, [])
        assert str(ws.cell(90, 3).value).strip() == "해당 사항 없음"


class TestW6LabelRowFixes96Final:
    """W-6 ①②③ — 머지 라벨 헤더행 덮어쓰기 결함 fix (값은 헤더 아래 값행에).

    ① 3.UT301 r90:91 세로 머지 라벨 → 값은 92행.
    ② 21.IT801 r50 헤더('파일명' 등) → 값은 51행.
    ③ 통합검증_BTB r10 머지 라벨(C10:D11 'SW 버전'/E10:F11 'Test Period')
       → 값은 12행 (C12:D12/E12:F12 머지 anchor).
    """

    def test_ut301_w6_1_labels_preserved_values_on_row92(self):
        from backend.services.swut_comprehensive_aggregator import _write_ut301
        wb = openpyxl.Workbook()
        ws = wb.active
        labels = {3: "SW Unit(함수)", 5: "미달성 사유", 8: "대책", 12: "문장"}
        for col, text in labels.items():
            ws.cell(90, col).value = text
            ws.merge_cells(start_row=90, end_row=91, start_column=col, end_column=col)
        cfg = {"swutcr_metadata": {"ut301_enabled": "X"}}
        _write_ut301(ws, _meta_96final(), {}, cfg)
        # 라벨 보존 (이전: 91행 기입 → merge anchor redirect로 90행 라벨 덮어씀)
        for col, text in labels.items():
            assert ws.cell(90, col).value == text, f"라벨 col {col} 덮어써짐"
        # 값은 헤더 아래 첫 값행(92행)
        assert ws.cell(92, 3).value == "N/A"
        assert ws.cell(92, 5).value == "-"
        assert "Back-to-back" in str(ws.cell(92, 8).value)
        assert ws.cell(92, 12).value == "추가 B2B evidence source 제공 시 재작성"
        assert ws.cell(80, 3).value == "N/A"  # 기존 80행 stamp 불변

    def test_it801_w6_2_header_row50_preserved_values_on_row51(self):
        from backend.services.swut_comprehensive_aggregator import _write_it801
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(50, 3).value = "파일명"
        ws.cell(50, 5).value = "오류 내용"
        ws.cell(50, 7).value = "수정 여부"
        _write_it801(ws, _meta_96final(), {})
        assert ws.cell(50, 3).value == "파일명"
        assert ws.cell(50, 5).value == "오류 내용"
        assert ws.cell(50, 7).value == "수정 여부"
        assert ws.cell(51, 3).value == "N/A"
        assert ws.cell(51, 5).value == "해당 사항 없음"
        assert ws.cell(51, 7).value == "O"
        assert "mpatrol" in str(ws.cell(51, 10).value)

    def test_btb_w6_3_merged_labels_row10_preserved_values_on_row12(self):
        from backend.services.swut_comprehensive_aggregator import _write_btb_sheet
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(10, 3).value = "SW 버전"
        ws.merge_cells("C10:D11")
        ws.cell(10, 5).value = "Test Period"
        ws.merge_cells("E10:F11")
        ws.merge_cells("C12:D12")
        ws.merge_cells("E12:F12")
        cfg = {"swutcr_metadata": {
            "test_iteration": "0.1",
            "software_platform_ver": "25A1",
            "prepare_hours": 10,
            "execution_hours": 20,
            "review_hours": 30,
        }}
        _write_btb_sheet(ws, _meta_96final(), cfg)
        # 머지 라벨 헤더(10행) 보존
        assert ws.cell(10, 3).value == "SW 버전"
        assert ws.cell(10, 5).value == "Test Period"
        # 값행(12행) — C12/E12 머지 anchor + 시간값 G12:J12
        assert ws.cell(12, 3).value == "0.1"
        assert ws.cell(12, 5).value == "25A1"
        assert ws.cell(12, 7).value == 10
        assert ws.cell(12, 8).value == 20
        assert ws.cell(12, 9).value == 30
        assert ws.cell(12, 10).value == "=SUM(G12:I12)"
