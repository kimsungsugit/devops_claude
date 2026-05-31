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
    COL_LOG_DATA,
    COL_PASS_FAIL,
    COL_PASS_TOTAL,
    LOG_SHEET_NAME,
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
    assert ws.cell(3, COL_ACTUAL_START).value == "Actual Result"
    assert ws.cell(3, COL_PASS_FAIL).value == "Pass/Fail"
    assert ws.cell(3, COL_PASS_TOTAL).value == "Pass"
    assert ws.cell(3, COL_LOG_DATA).value == "Log Data"
    assert ws.cell(4, COL_ACTUAL_START).value == "Param 1"
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

