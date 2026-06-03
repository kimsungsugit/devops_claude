"""라운드 91 — spec-based SUTR 빌더 (swut_sutr_spec_builder) 단위 테스트.

회사 감사본 양식(KJPDS02 v1.01 류) SUTR '3.Test Log' 빌드 경로 검증:
- SwUTS spec 시트 통째 복사 (Input/Expected 보존) + Actual/Pass-Fail/Log 추가.
- 함수 anchor 스캔, SwUFn 숫자 매칭, iteration Pass/Fail, JG Total 세로병합.
"""
from __future__ import annotations

import io

import openpyxl
import pytest

from backend.services.swut_input_adapter import (
    EnvironmentData,
    ExecutionRow,
    SwUTSession,
)
from backend.services.swut_sutr_aggregator import SutrBuildMeta
from backend.services.swut_sutr_spec_builder import (
    COL_ACTUAL_START,
    COL_EXPECTED_START,
    COL_LOG_DATA,
    COL_PASS_FAIL,
    COL_PASS_TOTAL,
    LOG_SHEET_NAME,
    SUBHEADER_ROW,
    _apply_actual_result_style,
    _build_fn_iteration_map,
    _lookup_vcast_actual,
    _scan_spec_blocks,
    build_sutr_from_spec,
)


# ---------------------------------------------------------------------------
# 합성 spec xlsm 생성 (회사 KJPDS02 v1.01 양식 축소판)
# ---------------------------------------------------------------------------

def _make_spec_bytes(blocks: list[tuple[str, str, list[tuple]]]) -> bytes:
    """합성 SwUTS spec xlsm bytes 생성.

    blocks: [(tc_id, unit, [(input_vals, expected_vals), ...]), ...]
        각 iteration tuple = (dict 형태 단순화 — 여기선 변수 1개씩 H/BF에).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2.SW Unit Test Spec"
    # 헤더
    ws.cell(1, 1).value = "Software Unit Test"
    ws.cell(3, 2).value = "Test Case"
    ws.cell(3, 7).value = "Input"
    ws.cell(3, 58).value = "Expected Result"
    ws.cell(3, 162).value = "Related ID"
    ws.cell(4, 2).value = "Index"
    ws.cell(4, 3).value = "TC_ID"
    ws.cell(4, 4).value = "Unit"
    ws.cell(4, 5).value = "Test Method"
    ws.cell(4, 6).value = "Test Case Generation"
    ws.cell(4, 7).value = " "
    ws.cell(4, 8).value = "Inpt[0]"
    ws.cell(4, 58).value = "ExpR[0]"
    rr = 5
    idx = 1
    for tc_id, unit, iters in blocks:
        anchor = rr
        ws.cell(anchor, 2).value = idx
        ws.cell(anchor, 3).value = tc_id
        ws.cell(anchor, 4).value = unit
        ws.cell(anchor, 8).value = "in_var"   # H 변수명
        ws.cell(anchor, 58).value = "exp_var"  # BF 변수명
        # spec Related ID 세로병합 (실제 양식 재현 — 빌더가 해제해야 함)
        if iters:
            ws.merge_cells(start_row=anchor, end_row=anchor + len(iters),
                           start_column=162, end_column=162)
        for it_no, (inp, exp) in enumerate(iters, start=1):
            ir = anchor + it_no
            ws.cell(ir, 5).value = "REQ"
            ws.cell(ir, 6).value = "ABV"
            ws.cell(ir, 7).value = it_no
            ws.cell(ir, 8).value = inp
            ws.cell(ir, 58).value = exp
        rr = anchor + len(iters) + 1
        idx += 1
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _make_session(fn_results: dict[str, list[bool | None]]) -> SwUTSession:
    """fn_results: {'SwUFn_0101': [True, False, None], ...} → session."""
    env = EnvironmentData(env_name="SwUT_01_Test", component_name="Test")
    for fn_id, results in fn_results.items():
        for i, passed in enumerate(results, start=1):
            key = f"{fn_id}.{i:03d}"
            env.test_cases[key] = []  # 빌더는 키만 사용 (Actual은 Expected 복제)
            if passed is not None:
                env.test_results[key] = ExecutionRow(
                    tc_name=key, passed=passed,
                    actual_result={"exp_var": ("actual_v", "exp_v")},
                )
    sess = SwUTSession(project_id="KJPDS02")
    sess.environments = [env]
    return sess


def _meta() -> SutrBuildMeta:
    return SutrBuildMeta(
        project_id="KJPDS02", project_full_name="KJPDS02", asil_level="ASIL A",
        doc_id_base="KJPDS02-SUTR", doc_id_sequence="1",
        default_author="JK Kim", default_approver="CH In",
        release_sw_version="1.01", test_date="2025-12-05", test_engineer="JK Kim",
    )


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_scan_spec_blocks_basic():
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("0x0", "0x1"), ("0x2", "0x3")]),
        ("SwUTC_0102", "foo", [("a", "b")]),
    ])
    wb = openpyxl.load_workbook(io.BytesIO(spec))
    ws = wb.active
    blocks = _scan_spec_blocks(ws)
    assert len(blocks) == 2
    assert blocks[0]["tc_id"] == "SwUTC_0101"
    assert blocks[0]["unit"] == "main"
    assert blocks[0]["num"] == "0101"
    assert len(blocks[0]["iter_rows"]) == 2
    assert len(blocks[1]["iter_rows"]) == 1


def test_build_fn_iteration_map():
    sess = _make_session({"SwUFn_0101": [True, False], "SwUFn_0102": [None]})
    m = _build_fn_iteration_map(sess)
    # 4-digit num은 lstrip("0") → "101"
    assert "101" in m
    assert m["101"][1]["passed"] is True
    assert m["101"][2]["passed"] is False
    assert "102" in m


def test_apply_actual_result_style_mirrors_expected():
    """라운드 104 — Actual(162~)이 Expected(58~) 서식을 미러 + 헤더행 미변경."""
    from openpyxl.styles import Border, Font, Side
    wb = openpyxl.Workbook()
    ws = wb.active
    thin = Side(style="thin")
    bd = Border(left=thin, right=thin, top=thin, bottom=thin)
    data_row = SUBHEADER_ROW + 1
    # Expected 셀에 테두리/폰트 부여 (graft 서식 모사).
    exp = ws.cell(data_row, COL_EXPECTED_START)
    exp.border = bd
    exp.font = Font(name="Arial", size=10)
    # Expected 마지막(161) — Pass/Fail·Total·Log 미러 소스.
    last_exp = ws.cell(data_row, COL_ACTUAL_START - 1)
    last_exp.border = bd
    last_exp.font = Font(name="Arial", size=10)
    # 헤더 행(SUBHEADER_ROW)의 Actual 셀은 변경되면 안 됨 — 기본(무테) 확인용.
    hdr_actual = ws.cell(SUBHEADER_ROW, COL_ACTUAL_START)

    n = _apply_actual_result_style(ws)
    assert n > 0
    # Actual 대응 셀(162)이 Expected 테두리 미러.
    act = ws.cell(data_row, COL_ACTUAL_START)
    assert act.border.left is not None and act.border.left.style == "thin"
    assert act.font.name == "Arial"
    # Pass/Fail(266)·Pass(267) border 적용 + 레퍼런스 폰트 통일.
    assert ws.cell(data_row, COL_PASS_FAIL).border.top.style == "thin"
    assert ws.cell(data_row, COL_PASS_TOTAL).border.bottom.style == "thin"
    assert ws.cell(data_row, COL_PASS_FAIL).font.name == "맑은 고딕"
    assert ws.cell(data_row, COL_PASS_FAIL).font.sz == 10
    assert ws.cell(data_row, COL_PASS_TOTAL).font.name == "맑은 고딕"
    assert ws.cell(data_row, COL_PASS_TOTAL).font.sz == 10
    # Log Data(JH)는 데이터 값을 비워 두되 폰트만 레퍼런스 기준으로 통일.
    assert (
        ws.cell(data_row, COL_LOG_DATA).border.bottom is None
        or ws.cell(data_row, COL_LOG_DATA).border.bottom.style is None
    )
    assert ws.cell(data_row, COL_LOG_DATA).font.name == "맑은 고딕"
    assert ws.cell(data_row, COL_LOG_DATA).font.sz == 10
    # 헤더 행은 미변경 (데이터 행만 대상).
    assert hdr_actual.border.left is None or hdr_actual.border.left.style is None


def test_lookup_vcast_actual_dotted():
    d = {"_LP0DR": ("0x3", "0x3"), "Byte": ("0x4", "0x4")}
    # dotted 변수명 분리 후보 매칭
    assert _lookup_vcast_actual(d, "_LP0DR.Byte") in ("0x3", "0x4")
    assert _lookup_vcast_actual(d, "missing") is None
    assert _lookup_vcast_actual({}, "x") is None


def test_build_sutr_from_spec_layout_matches_reference():
    """생성 '3.Test Log' 시트명 + 헤더 + Actual 채움 검증 (레퍼런스 양식)."""
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("0x0", "0x1"), ("0x2", "0x3")]),
    ])
    sess = _make_session({"SwUFn_0101": [True, True]})
    res = build_sutr_from_spec(sess, _meta(), spec, function_asil_map={})
    assert res.ok
    wb = openpyxl.load_workbook(res.xlsm_io, data_only=False)
    assert LOG_SHEET_NAME in wb.sheetnames
    ws = wb[LOG_SHEET_NAME]
    # 헤더
    assert ws.cell(1, 1).value == "Software Unit Test Log"
    assert ws.cell(3, COL_ACTUAL_START).value == "Actual Result"
    assert ws.cell(3, COL_PASS_FAIL).value == "Pass/Fail"
    assert ws.cell(3, COL_PASS_TOTAL).value == "Pass"
    assert ws.cell(3, COL_LOG_DATA).value == "Log Data"
    assert ws.cell(4, COL_ACTUAL_START).value == "Param 1"
    assert ws.cell(4, COL_PASS_FAIL).value == "Unit"
    assert ws.cell(4, COL_PASS_TOTAL).value == "Pass"
    assert ws.cell(3, COL_PASS_FAIL).font.name == "맑은 고딕"
    assert ws.cell(3, COL_PASS_FAIL).font.sz == 10
    assert ws.cell(3, COL_PASS_FAIL).font.bold is True
    assert ws.cell(4, COL_PASS_FAIL).font.name == "맑은 고딕"
    assert ws.cell(4, COL_PASS_FAIL).font.sz == 10
    assert ws.cell(4, COL_PASS_FAIL).font.bold is True
    # Input/Expected 보존
    assert ws.cell(6, 8).value == "0x0"     # iteration1 input
    assert ws.cell(6, 58).value == "0x1"    # iteration1 expected
    # anchor Actual 변수명 = Expected 변수명
    assert ws.cell(5, COL_ACTUAL_START).value == "exp_var"
    # iteration Actual = Expected 복제 (Pass)
    assert ws.cell(6, COL_ACTUAL_START).value == "0x1"
    assert ws.cell(7, COL_ACTUAL_START).value == "0x3"
    # Pass/Fail
    assert ws.cell(6, COL_PASS_FAIL).value == "Pass"
    assert ws.cell(7, COL_PASS_FAIL).value == "Pass"
    # Total
    assert ws.cell(5, COL_PASS_TOTAL).value == "Pass"
    # Log Data 데이터 셀에는 로그 경로를 쓰지 않음(레퍼런스 정합).
    assert ws.cell(6, COL_LOG_DATA).value is None


def test_build_sutr_unmatched_function_na():
    """spec에 있지만 vcast 미실행 함수 → Pass/Fail N/A, Total N/A."""
    spec = _make_spec_bytes([
        ("SwUTC_0199", "orphan", [("x", "y")]),
    ])
    sess = _make_session({"SwUFn_0101": [True]})  # 0199 없음
    res = build_sutr_from_spec(sess, _meta(), spec, function_asil_map={})
    assert res.ok
    assert res.summary["unmatched_functions"] == 1
    ws = openpyxl.load_workbook(res.xlsm_io)[LOG_SHEET_NAME]
    assert ws.cell(6, COL_PASS_FAIL).value == "N/A"
    assert ws.cell(5, COL_PASS_TOTAL).value == "N/A"
    merges = [
        str(m) for m in ws.merged_cells.ranges
        if m.min_col == COL_PASS_TOTAL and m.min_row == 5
    ]
    assert merges, "미매칭 함수도 JG Total 세로병합 필요"


def test_build_sutr_fail_iteration():
    """Fail iteration → JF='Fail', Total='Fail'."""
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("0x0", "0x1"), ("0x2", "0x3")]),
    ])
    sess = _make_session({"SwUFn_0101": [True, False]})
    res = build_sutr_from_spec(sess, _meta(), spec, function_asil_map={})
    ws = openpyxl.load_workbook(res.xlsm_io)[LOG_SHEET_NAME]
    assert ws.cell(6, COL_PASS_FAIL).value == "Pass"
    assert ws.cell(7, COL_PASS_FAIL).value == "Fail"
    assert ws.cell(5, COL_PASS_TOTAL).value == "Fail"  # 하나라도 Fail


def test_build_sutr_uses_spec_iteration_number_when_rows_have_gap():
    """G열 iteration 번호가 비어도 해당 SwUFn suffix 결과를 매칭한다."""
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("0x0", "0x1"), ("0x2", "0x3")]),
    ])
    wb = openpyxl.load_workbook(io.BytesIO(spec), keep_vba=True)
    ws = wb["2.SW Unit Test Spec"]
    ws.cell(7, 7).value = 3
    buf = io.BytesIO()
    wb.save(buf)
    sess = _make_session({"SwUFn_0101": [True, None, True]})

    res = build_sutr_from_spec(sess, _meta(), buf.getvalue(), function_asil_map={})
    out = openpyxl.load_workbook(res.xlsm_io, keep_vba=True)
    log = out[LOG_SHEET_NAME]

    assert log.cell(6, COL_PASS_FAIL).value == "Pass"
    assert log.cell(7, COL_PASS_FAIL).value == "Pass"
    assert log.cell(7, COL_ACTUAL_START).value == "0x3"
    assert log.cell(5, COL_PASS_TOTAL).value == "Pass"


def test_build_sutr_total_vertical_merge():
    """JG Total 셀이 함수 블록 전체 세로병합."""
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("a", "b"), ("c", "d"), ("e", "f")]),
    ])
    sess = _make_session({"SwUFn_0101": [True, True, True]})
    res = build_sutr_from_spec(sess, _meta(), spec, function_asil_map={})
    ws = openpyxl.load_workbook(res.xlsm_io)[LOG_SHEET_NAME]
    merges = [str(m) for m in ws.merged_cells.ranges
              if m.min_col == COL_PASS_TOTAL and m.min_row == 5]
    assert merges, "JG Total 세로병합 없음"
    rng = next(m for m in ws.merged_cells.ranges
               if m.min_col == COL_PASS_TOTAL and m.min_row == 5)
    assert rng.max_row == 8  # anchor(5) + 3 iteration


def test_build_sutr_no_spec_sheet_fails():
    """spec 시트 없는 xlsm → ok=False."""
    wb = openpyxl.Workbook()
    wb.active.title = "Random"
    bio = io.BytesIO()
    wb.save(bio)
    res = build_sutr_from_spec(_make_session({}), _meta(), bio.getvalue())
    assert res.ok is False


def test_build_sutr_invalid_date_raises():
    spec = _make_spec_bytes([("SwUTC_0101", "main", [("a", "b")])])
    meta = _meta()
    meta.test_date = "251205"  # 잘못된 형식
    with pytest.raises(Exception):
        build_sutr_from_spec(_make_session({}), meta, spec)


def test_build_sutr_asil_marking_applied():
    """function_asil_map 제공 시 anchor Total 셀에 ASIL 시각 강조 fill 적용."""
    spec = _make_spec_bytes([("SwUTC_0101", "main", [("a", "b")])])
    sess = _make_session({"SwUFn_0101": [True]})
    res = build_sutr_from_spec(
        sess, _meta(), spec, function_asil_map={"SwUFn_0101": "A"},
    )
    ws = openpyxl.load_workbook(res.xlsm_io)[LOG_SHEET_NAME]
    fill = ws.cell(5, COL_PASS_TOTAL).fill
    rgb = getattr(getattr(fill, "fgColor", None), "rgb", None)
    assert rgb not in (None, "00000000"), "ASIL A 마킹 fill 미적용"


def test_is_sutr_spec_based_flag():
    """라우터 분기 헬퍼 — config sutr_spec_based 플래그."""
    from backend.routers.swut import _is_sutr_spec_based

    class _Req:
        project_id = "KJPDS02"

    assert _is_sutr_spec_based(_Req(), {"sutr_spec_based": True}) is True
    assert _is_sutr_spec_based(_Req(), {"sutr_spec_based": False}) is False
    assert _is_sutr_spec_based(_Req(), {}) is False  # 미설정 → backward-compat


# ---------------------------------------------------------------------------
# 라운드 92 — 표준 SUTR 템플릿 베이스 + spec 시트 이식
# ---------------------------------------------------------------------------

def _make_standard_template_bytes() -> bytes:
    """합성 표준 SUTR 템플릿 (Cover/History/1.Test Summary/2.Deviation/3.Test Result)."""
    wb = openpyxl.Workbook()
    cover = wb.active
    cover.title = "Cover"
    cover.cell(3, 2).value = "Project"
    cover.cell(4, 2).value = "ASIL Level"
    cover.cell(5, 2).value = "Version"
    cover.cell(6, 2).value = "Test Date"
    cover.cell(7, 2).value = "Author"
    cover.cell(8, 2).value = "Approver"

    hist = wb.create_sheet("History")
    hist.cell(3, 2).value = "No."
    hist.cell(3, 3).value = "Date"
    hist.cell(3, 4).value = "Version"
    hist.cell(3, 5).value = "Description"
    hist.cell(3, 6).value = "Author"

    ts = wb.create_sheet("1.Test Summary")
    ts.cell(4, 2).value = "Project Name"
    ts.cell(5, 2).value = "SW Version"
    ts.cell(6, 2).value = "HW Version"
    ts.cell(7, 2).value = "Test Date"
    ts.cell(8, 2).value = "Test Engineer"
    ts.cell(17, 2).value = "Total Number of TCs"
    ts.cell(17, 3).value = "Number of TCs Tested"
    ts.cell(17, 4).value = "Number of TCs Passed"
    ts.cell(17, 5).value = "Number of TCs Failed"
    ts.cell(17, 6).value = "Number of TCs not executed"
    ts.cell(21, 2).value = "Source"
    ts.cell(22, 2).value = "System Design"

    dev = wb.create_sheet("2.Deviation")
    dev.cell(4, 2).value = "Test Case ID"
    dev.cell(4, 3).value = "Issue"
    dev.cell(4, 4).value = "Deviation"
    dev.cell(4, 5).value = "Status"

    res = wb.create_sheet("3.Test Result")
    res.cell(1, 1).value = "Narrow 38-col result"
    res.cell(5, 38).value = "edge"

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def test_r92_template_base_sheet_composition():
    """R92 — 표준 템플릿 베이스 시 시트 구성이 레퍼런스 정합.

    [Cover, History, 1.Test Summary, 2.Deviation, 3.Test Log] (+AuditLog)
    Introduction / 1.Test Environment / 3.Test Result 없음.
    """
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("0x0", "0x1"), ("0x2", "0x3")]),
        ("SwUTC_0102", "foo", [("a", "b")]),
    ])
    tmpl = _make_standard_template_bytes()
    sess = _make_session({"SwUFn_0101": [True, True], "SwUFn_0102": [False]})
    res = build_sutr_from_spec(
        sess, _meta(), spec, template_xlsm_bytes=tmpl, function_asil_map={},
    )
    assert res.ok
    wb = openpyxl.load_workbook(res.xlsm_io, data_only=False)
    names = wb.sheetnames
    # 좁은 3.Test Result 제거됨
    assert "3.Test Result" not in names
    # 레퍼런스 4 시트 + 3.Test Log 존재
    for must in ("Cover", "History", "1.Test Summary", "2.Deviation", "3.Test Log"):
        assert must in names, f"{must} 누락 (시트: {names})"
    # spec 전용 시트 미존재
    assert not any("introduction" in n.lower() for n in names)
    assert not any("environment" in n.lower() for n in names)


def test_r92_test_log_wide_sheet_grafted():
    """R92 — 이식된 3.Test Log가 spec 와이드 양식(value/merge) 보존."""
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("0x0", "0x1"), ("0x2", "0x3")]),
    ])
    tmpl = _make_standard_template_bytes()
    sess = _make_session({"SwUFn_0101": [True, True]})
    res = build_sutr_from_spec(
        sess, _meta(), spec, template_xlsm_bytes=tmpl, function_asil_map={},
    )
    wb = openpyxl.load_workbook(res.xlsm_io, data_only=False)
    ws = wb["3.Test Log"]
    # spec 보존 — Input/Expected
    assert ws.cell(6, 8).value == "0x0"
    assert ws.cell(6, 58).value == "0x1"
    # R91 fill 로직 적용 — Actual/Pass-Fail
    assert ws.cell(3, COL_ACTUAL_START).value == "Actual Result"
    assert ws.cell(6, COL_ACTUAL_START).value == "0x1"  # Pass → Expected 복제
    assert ws.cell(6, COL_PASS_FAIL).value == "Pass"
    assert ws.cell(5, COL_PASS_TOTAL).value == "Pass"


def test_r92_test_summary_function_counts():
    """R92 — 1.Test Summary TC 카운트가 함수 단위(레퍼런스 정합)로 stamp."""
    spec = _make_spec_bytes([
        ("SwUTC_0101", "main", [("a", "b")]),       # pass fn
        ("SwUTC_0102", "foo", [("c", "d")]),         # fail fn
        ("SwUTC_0103", "bar", [("e", "f")]),         # na fn (vcast 미실행)
    ])
    tmpl = _make_standard_template_bytes()
    sess = _make_session({"SwUFn_0101": [True], "SwUFn_0102": [False]})
    res = build_sutr_from_spec(
        sess, _meta(), spec, template_xlsm_bytes=tmpl, function_asil_map={},
    )
    assert res.summary["test_summary_tc_total"] == 3
    assert res.summary["test_summary_passed"] == 1
    assert res.summary["test_summary_failed"] == 1
    assert res.summary["test_summary_not_executed"] == 1
    assert res.summary["test_summary_tested"] == 2
    wb = openpyxl.load_workbook(res.xlsm_io)
    ts = wb["1.Test Summary"]
    assert ts.cell(18, 2).value == 3   # Total
    assert ts.cell(18, 3).value == 2   # Tested
    assert ts.cell(18, 4).value == 1   # Passed
    assert ts.cell(18, 5).value == 1   # Failed
    assert ts.cell(18, 6).value == 1   # not executed


def test_r92_cover_meta_stamped():
    """R92 — Cover 시트 meta(Project/Version/Date) stamp."""
    spec = _make_spec_bytes([("SwUTC_0101", "main", [("a", "b")])])
    tmpl = _make_standard_template_bytes()
    sess = _make_session({"SwUFn_0101": [True]})
    res = build_sutr_from_spec(
        sess, _meta(), spec, template_xlsm_bytes=tmpl, function_asil_map={},
    )
    wb = openpyxl.load_workbook(res.xlsm_io)
    cover = wb["Cover"]
    # 표준 _write_cover 가 stamp 하는 라벨: Project / ASIL Level / Version.
    assert cover.cell(3, 3).value == "KJPDS02"          # Project value (C열)
    assert cover.cell(4, 3).value == "ASIL A"           # ASIL Level
    assert cover.cell(5, 3).value == "v1.01"            # Version
    # Test Date 는 1.Test Summary 에 stamp.
    ts = wb["1.Test Summary"]
    assert ts.cell(7, 3).value == "2025-12-05"          # Test Date (Summary)


def test_copy_sheet_across_workbooks_fidelity():
    """크로스-워크북 시트 복사 helper — value/merge/width/height 보존."""
    from backend.services.excel_template_utils import copy_sheet_across_workbooks

    src_wb = openpyxl.Workbook()
    src = src_wb.active
    src.title = "Src"
    src.cell(1, 1).value = "hello"
    src.cell(2, 3).value = 42
    src.merge_cells("A5:C5")
    src.column_dimensions["B"].width = 33.0
    src.row_dimensions[4].height = 22.0

    dst_wb = openpyxl.Workbook()
    dst = copy_sheet_across_workbooks(src, dst_wb, new_title="3.Test Log")
    assert "3.Test Log" in dst_wb.sheetnames
    assert dst.cell(1, 1).value == "hello"
    assert dst.cell(2, 3).value == 42
    assert "A5:C5" in [str(m) for m in dst.merged_cells.ranges]
    assert dst.column_dimensions["B"].width == 33.0
    assert dst.row_dimensions[4].height == 22.0


def test_r91_fallback_when_no_template():
    """R92 — template None이면 R91 fallback (spec wb 베이스) + warning."""
    spec = _make_spec_bytes([("SwUTC_0101", "main", [("a", "b")])])
    sess = _make_session({"SwUFn_0101": [True]})
    res = build_sutr_from_spec(sess, _meta(), spec, function_asil_map={})
    assert res.ok
    assert res.summary["builder"] == "spec-based-r91"
    assert any("표준 SUTR 템플릿 미제공" in w for w in res.warnings)
