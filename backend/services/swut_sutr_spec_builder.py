"""SwUT SUTR (Software Unit Test Result) — **spec-based** Test Log 빌더 (라운드 91).

회사 감사본 양식(KJPDS02 v1.01 등)은 SUTR '3.Test Log' 시트가 SwUTS spec의
'2.SW Unit Test Spec' 시트(Test Case + Input + Expected 이미 완비)와 **동일 구조** +
Actual Result / Pass-Fail / Log Data 섹션 추가다.

기존 ``swut_sutr_aggregator.build_sutr`` (표준 Version3 좁은 38열 양식 + 함수별 블록
재구성)와는 양식이 근본적으로 다르므로 **신규 경로**로 분리한다.

## 핵심 전략 — 표준 SUTR 템플릿 베이스 + spec 시트 이식 (라운드 92 전환)

라운드 91은 SwUTS spec xlsm 자체를 베이스로 복사하여 출력 시트가 spec 구성
(Cover / History / Introduction / 1.Test Environment / 3.Test Log)으로 잘못 나왔다.
레퍼런스 SUTR 구성은 Cover / History / 1.Test Summary / 2.Deviation / 3.Test Log 이다.

라운드 92는 베이스를 **표준 SUTR 템플릿** (회사 ★개발템플릿 Version3 `(XXXX_SwUTR)
...v0.10`) 으로 전환한다:

1. 표준 SUTR 템플릿 xlsm 을 keep_vba 로 로드 (Cover / History / 1.Test Summary /
   2.Deviation / 3.Test Result(좁은 38열) 보유).
2. Cover / 1.Test Summary / 2.Deviation / History 를 기존 표준 writer
   (`swut_sutr_aggregator._write_cover` / `_write_test_summary` / `_write_deviation`
   + `_write_history_sheet`)로 채움 — meta + TC 카운트(Total/Tested/Passed/Failed/
   not-exec) + Requirements coverage.
3. 표준의 좁은 '3.Test Result' 시트를 **제거**.
4. SwUTS spec '2.SW Unit Test Spec' (와이드 268열) 시트를 표준 템플릿 wb 에
   **크로스-워크북 풀 카피** (`copy_sheet_across_workbooks` — value/style/merge/
   column width/row height 보존) 하여 '3.Test Log' 로 이식.
5. 레퍼런스 SUTR 레이아웃에 맞춰 이식 시트에 Actual/Pass-Fail/Log 섹션의 **헤더(r3
   병합 + r4 서브헤더)** 추가 + anchor 스캔 → VectorCAST 매칭으로 Actual 값 /
   iteration Pass-Fail(JF) / 함수 Total(JG) / Log Data(JH) 채움 (라운드 91 로직 유지).

## 레이아웃 (KJPDS02 v1.01 레퍼런스 실측, max_col=268)

| 영역 | 열 | 출처 |
|------|----|----|
| Test Case (Index/TC_ID/Unit/Method/Generation) | B(2)~F(6) | spec 보존 |
| Input (Inpt[0]~) | G(7)~BE(57) | spec 보존 |
| Expected (ExpR[0]~) | BF(58)~FE(161) | spec 보존 |
| Related ID (spec 전용) | FF(162) | → Actual로 대체 |
| Actual Result (Param 1~) | FF(162)~JE(265) | VectorCAST 추가 |
| Pass/Fail (iteration) | JF(266) | VectorCAST 추가 |
| Pass (함수 Total, 세로병합) | JG(267) | VectorCAST 추가 |
| Log Data | JH(268) | VectorCAST 추가 |

## 매칭 키 (라운드 91 실측)

spec TC_ID 숫자(``SwUTC_NNNN``) == VectorCAST ``SwUFn_NNNN`` 숫자. 직접 4-digit
숫자 매칭. iteration: spec G index(1..N) ↔ vcast ``.MMM`` 정렬 순서.

## Actual 채우기 정책

VectorCAST ``actual_result`` 는 dotted 변수명 분리(예 ``_LP0DR.Byte`` →
``_LP0DR``/``Byte``)로 부정확. 레퍼런스 감사본은 Pass iteration의 Actual = Expected
값과 동일하게 기록(실측). 따라서:

- iteration이 Pass면 Actual = 해당 iteration의 Expected 값 복제 (감사본 패턴 일치).
- iteration이 Fail이면 vcast actual_result best-effort + 부재 시 노란 마킹.
- iteration이 미실행(N/A)면 Actual 비움 + Pass/Fail = "N/A".

## ISO 26262 Tool Qualification
ASIL A 한정 draft. B/C/D는 manual review 의무. Input/Expected는 spec 그대로 보존
(audit truth 불변), Actual/Pass-Fail만 추가.
"""
from __future__ import annotations

import hashlib
import io
import re
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.design_tokens import USER_INPUT_FILL_RGB
from backend.services.excel_template_utils import (
    copy_sheet_across_workbooks,
    has_vba_macros,
    inspect_vba_refs,
    mark_asil_a_function,
    mark_asil_b_function,
    mark_asil_c_function,
    mark_asil_d_function,
    mark_asil_qm_function,
    safe_write,
    sanitize_xlsm_external_links,
    short_date,
    validate_build_meta,
    validate_xlsx_template_bytes,
    write_value_after_label,
)
from backend.services.swut_builder_helpers import extract_warnings_from_session
from backend.services.swut_input_adapter import SwUTSession, aggregate_session
from backend.services.swut_sutr_aggregator import SutrBuildMeta, SutrBuildResult

# ---------------------------------------------------------------------------
# 레이아웃 상수 (KJPDS02 v1.01 레퍼런스 실측)
# ---------------------------------------------------------------------------

SPEC_SHEET_RE = re.compile(r"(Unit|Integration)\s*Test\s*Spec", re.IGNORECASE)
LOG_SHEET_NAME = "3.Test Log"

# 행/열 위치 (1-based)
HEADER_SECTION_ROW = 3       # 병합 섹션 헤더 (Test Case / Input / Expected / Actual ...)
SUBHEADER_ROW = 4            # 서브헤더 (Index / TC_ID / Inpt[0] / ExpR[0] / Param 1 ...)
DATA_START_ROW = 5           # 첫 함수 anchor

COL_INDEX = 2                # B
COL_TC_ID = 3                # C
COL_UNIT = 4                 # D
COL_METHOD = 5               # E
COL_GENERATION = 6           # F
COL_ITER_INDEX = 7           # G
COL_INPUT_START = 8          # H

# Expected 끝 = spec 시트 마지막 데이터 열 직전(FE=161). spec FF(162)=Related ID.
# 레퍼런스 SUTR: Actual=FF(162)~JE(265), JF(266)=Pass/Fail, JG(267)=Total, JH(268)=Log.
COL_RELATED_ID = 162         # FF (spec 전용) — Actual로 대체
COL_ACTUAL_START = 162       # FF
COL_PASS_FAIL = 266          # JF
COL_PASS_TOTAL = 267         # JG
COL_LOG_DATA = 268           # JH
ACTUAL_MAX = COL_PASS_FAIL - COL_ACTUAL_START  # 104 (Param 1~104)
# 라운드 104 — Actual Result 서식 미러 소스. Expected Result(BF=58~FE=161, 104열)는
# spec graft로 서식 보유하나 Actual(FF=162~)은 우리 추가 열이라 무서식 → Expected를
# 1:1 미러(같은 변수의 기대/실제값, 동일 레이아웃). 헤더 r3 'Expected Result'@58 확인.
COL_EXPECTED_START = 58      # BF

_FILL_RGB = USER_INPUT_FILL_RGB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_spec_sheet(wb: Workbook):
    """SwUTS spec 시트('2.SW Unit Test Spec' 류)를 찾아 반환. 미발견 시 None."""
    for name in wb.sheetnames:
        if SPEC_SHEET_RE.search(name):
            return wb[name], name
    return None, None


def _scan_spec_blocks(ws) -> list[dict[str, Any]]:
    """spec 시트 anchor 스캔 → 함수 블록 list.

    각 블록: anchor row(B=Index digit, C=TC_ID, D=Unit) + iteration row들.

    Returns:
        [{anchor, tc_id, unit, num(4-digit), iter_rows: [row,...]}, ...]
    """
    blocks: list[dict[str, Any]] = []
    rr = DATA_START_ROW
    max_row = ws.max_row
    while rr <= max_row:
        b = ws.cell(rr, COL_INDEX).value
        c = ws.cell(rr, COL_TC_ID).value
        if str(b if b is not None else "").strip().isdigit() and c:
            tc_id = str(c).strip()
            num_m = re.search(r"(\d+)", tc_id)
            num = num_m.group(1) if num_m else ""
            # iteration row: anchor 다음부터, 다음 anchor 전까지, G(iter index) 보유.
            iter_rows: list[int] = []
            k = rr + 1
            while k <= max_row:
                nb = ws.cell(k, COL_INDEX).value
                nc = ws.cell(k, COL_TC_ID).value
                if str(nb if nb is not None else "").strip().isdigit() and nc:
                    break  # 다음 anchor
                g = ws.cell(k, COL_ITER_INDEX).value
                if g not in (None, ""):
                    iter_rows.append(k)
                k += 1
            blocks.append({
                "anchor": rr,
                "tc_id": tc_id,
                "unit": str(ws.cell(rr, COL_UNIT).value or "").strip(),
                "num": num,
                "iter_rows": iter_rows,
            })
            rr = k
        else:
            rr += 1
    return blocks


def _expected_var_cols(ws, anchor_row: int) -> list[int]:
    """anchor row의 Expected 섹션(BF=58~FE=161)에서 변수명이 있는 열 리스트.

    Actual 변수명/값 stamp 시 동일 열 offset 사용 (감사본은 Actual 변수 = Expected
    변수와 동일 — 레퍼런스 실측: anchor r5 BF='return', FF='return').
    """
    cols: list[int] = []
    for c in range(58, COL_RELATED_ID):  # BF(58) ~ FE(161)
        if ws.cell(anchor_row, c).value not in (None, ""):
            cols.append(c)
    return cols


def _build_fn_iteration_map(session: SwUTSession) -> dict[str, dict[int, Any]]:
    """SwUFn 숫자(4-digit) → {iteration_index(int): {"passed":bool|None,
    "actual": dict, "env": env}}.

    iteration_index 는 ``.MMM`` suffix(1-based). 정렬 보장.
    """
    fn_map: dict[str, dict[int, Any]] = {}
    for env in session.environments:
        for tc_name in env.test_cases:
            m = re.match(r"SwUFn_(\d+)\.(\d+)", tc_name)
            if not m:
                continue
            num = m.group(1).lstrip("0") or "0"
            idx = int(m.group(2))
            exec_r = env.test_results.get(tc_name)
            actual_dict: dict = {}
            passed = None
            if exec_r is not None:
                passed = bool(exec_r.passed)
                actual_dict = getattr(exec_r, "actual_result", {}) or {}
            if not actual_dict:
                tr_items = getattr(env, "tc_result_items", {}).get(tc_name, [])
                tr_item = tr_items[0] if tr_items else None
                if tr_item is not None:
                    actual_dict = getattr(tr_item, "actual_result", {}) or {}
            fn_map.setdefault(num, {})[idx] = {
                "passed": passed,
                "actual": actual_dict,
                "env": env,
                "tc_name": tc_name,
            }
    return fn_map


# ---------------------------------------------------------------------------
# Header writer (Actual / Pass-Fail / Log 섹션)
# ---------------------------------------------------------------------------

def _apply_actual_result_style(ws) -> int:
    """라운드 104 — Actual Result(+Pass/Fail·Pass) 열에 템플릿 서식 적용.

    spec graft는 Test Case/Input/Expected(BF=58~FE=161)까지만 서식을 가져오고
    Actual(FF=162~JE=265)·Pass/Fail(JF=266)·Pass(JG=267)는 우리 추가 열이라
    무서식(무테/default 폰트) → 사용자 보고 "Actual만 템플릿 미적용".

    Expected를 1:1 미러: Actual col (162+i) ← Expected col (58+i). **같은 wb 내**이므로
    ``_style`` 인덱스 직접 복사가 정확+빠름 (cross-wb는 라운드 103처럼 객체복사 필요하나
    여기는 동일 wb). value는 보존(``_style`` 만 복제). Pass/Fail·Pass는 Expected
    대응이 없어 Expected 마지막 열(FE=161) 서식을 border/font 만 복제(기존 fill — ASIL/
    Pass 강조 마킹 — 보존). Log Data(JH) 데이터 영역은 레퍼런스처럼 비워 두므로
    헤더 외 데이터 셀 서식을 강제로 입히지 않음. 서브헤더/헤더 행(1~SUBHEADER_ROW)은
    건드리지 않음.

    Returns:
        서식 적용한 셀 수.
    """
    import copy as _copy

    from openpyxl.cell.cell import MergedCell as _MC
    from openpyxl.styles import Font

    def _result_font(src_font, *, bold: bool | None = None) -> Font:
        return Font(
            name="맑은 고딕",
            size=10,
            bold=src_font.bold if bold is None else bold,
            italic=src_font.italic,
            underline=src_font.underline,
            strike=src_font.strike,
            color=_copy.copy(src_font.color),
            vertAlign=src_font.vertAlign,
            charset=src_font.charset,
            family=src_font.family,
            scheme=src_font.scheme,
        )

    offset = COL_ACTUAL_START - COL_EXPECTED_START  # 104
    restyled = 0
    for r in range(SUBHEADER_ROW + 1, ws.max_row + 1):
        # Actual(162~265) ← Expected(58~161) 미러 (_style 통째 — Actual엔 마킹 없음).
        for ec in range(COL_EXPECTED_START, COL_ACTUAL_START):
            exp = ws.cell(r, ec)
            if not getattr(exp, "has_style", False):
                continue
            act = ws.cell(r, ec + offset)
            if isinstance(act, _MC) or isinstance(exp, _MC):
                continue
            try:
                act._style = _copy.copy(exp._style)
                restyled += 1
            except (AttributeError, TypeError):
                pass
        # Pass/Fail·Pass(266~267): Expected 마지막 열(161) border/font 만 복제
        # (fill 보존 — ASIL/Pass 강조 마킹 유지).
        ref = ws.cell(r, COL_ACTUAL_START - 1)  # FE=161
        if getattr(ref, "has_style", False) and not isinstance(ref, _MC):
            for tc in (COL_PASS_FAIL, COL_PASS_TOTAL):
                dst = ws.cell(r, tc)
                if isinstance(dst, _MC):
                    continue
                try:
                    dst.border = _copy.copy(ref.border)
                    dst.font = _result_font(ref.font)
                    restyled += 1
                except (AttributeError, TypeError):
                    pass
            log_cell = ws.cell(r, COL_LOG_DATA)
            if not isinstance(log_cell, _MC):
                try:
                    log_cell.font = _result_font(ref.font, bold=False)
                    restyled += 1
                except (AttributeError, TypeError):
                    pass
    return restyled


def _write_log_headers(ws, out_warnings: list[str] | None) -> None:
    """레퍼런스 SUTR 레이아웃의 Actual/Pass-Fail/Log 헤더를 추가.

    - r3: FF='Actual Result' (FF~JE 병합), JF='Pass/Fail', JG='Pass', JH='Log Data'.
    - r4: FF~ 'Param N' 서브헤더 + JH 'Log Data' (r3:r4 병합).
    - spec FF의 'Related ID' 헤더는 Actual로 대체됨.
    - r2: JF/JG COUNTIF 요약 수식 (레퍼런스 복제, 범위는 데이터 끝까지 확장).
    """
    # spec의 Related ID(FF) 컬럼은 함수 블록마다 세로 병합(FF5:FF12 등) + r3/r4
    # 헤더 병합 보유. Actual을 iteration별로 채우려면 FF~JE(162~265) 범위에 걸친
    # 모든 병합을 해제해야 한다 (병합 셀의 비-anchor 셀 쓰기는 openpyxl이 무시 →
    # iteration Actual 값이 anchor row로 흘러가 손실됨). JG(Total)는 후속 함수별
    # 재병합. 데이터 병합 + r3/r4 헤더 병합 모두 해제.
    for rng in list(ws.merged_cells.ranges):
        if COL_ACTUAL_START <= rng.min_col <= (COL_PASS_FAIL - 1):
            try:
                ws.unmerge_cells(str(rng))
            except (ValueError, KeyError):
                pass

    safe_write(ws, 1, 1, "Software Unit Test Log")

    # r3 섹션 헤더.
    safe_write(ws, HEADER_SECTION_ROW, COL_ACTUAL_START, "Actual Result")
    safe_write(ws, HEADER_SECTION_ROW, COL_PASS_FAIL, "Pass/Fail")
    safe_write(ws, HEADER_SECTION_ROW, COL_PASS_TOTAL, "Pass")
    safe_write(ws, HEADER_SECTION_ROW, COL_LOG_DATA, "Log Data")
    try:
        ws.merge_cells(
            start_row=HEADER_SECTION_ROW, end_row=HEADER_SECTION_ROW,
            start_column=COL_ACTUAL_START, end_column=COL_PASS_FAIL - 1,
        )
        ws.merge_cells(
            start_row=HEADER_SECTION_ROW, end_row=SUBHEADER_ROW,
            start_column=COL_LOG_DATA, end_column=COL_LOG_DATA,
        )
    except (ValueError, AttributeError):
        pass

    # r4 서브헤더 — Param 1..ACTUAL_MAX.
    for i in range(ACTUAL_MAX):
        safe_write(ws, SUBHEADER_ROW, COL_ACTUAL_START + i, f"Param {i + 1}")
    safe_write(ws, SUBHEADER_ROW, COL_PASS_FAIL, "Unit")
    safe_write(ws, SUBHEADER_ROW, COL_PASS_TOTAL, "Pass")

    try:
        from copy import copy as _copy_style

        from openpyxl.styles import Alignment, Font

        header_font = Font(name="맑은 고딕", size=10, bold=True)
        header_alignment = Alignment(horizontal="center", vertical="center")
        for row_idx in (HEADER_SECTION_ROW, SUBHEADER_ROW):
            for col_idx in range(COL_ACTUAL_START, COL_LOG_DATA + 1):
                cell = ws.cell(row_idx, col_idx)
                cell.font = _copy_style(header_font)
                cell.alignment = _copy_style(header_alignment)
    except (AttributeError, TypeError):
        pass

    # r2 COUNTIF 요약 수식 (레퍼런스 복제 — 범위는 데이터 끝까지).
    last_row = ws.max_row
    from openpyxl.utils import get_column_letter
    jf = get_column_letter(COL_PASS_FAIL)
    jg = get_column_letter(COL_PASS_TOTAL)
    try:
        ws.cell(2, COL_PASS_FAIL).value = (
            f'=COUNTIF({jf}{DATA_START_ROW}:{jf}{last_row}, "Fail")'
        )
        ws.cell(2, COL_PASS_TOTAL).value = (
            f'=COUNTIF({jg}{DATA_START_ROW}:{jg}{last_row},"Fail")'
            f'+COUNTIF({jg}{DATA_START_ROW}:{jg}{last_row},"N/A")'
        )
    except (ValueError, AttributeError):
        if out_warnings is not None:
            out_warnings.append("[spec-sutr] r2 COUNTIF 수식 stamp 실패 (산출물 영향 경미)")


# ---------------------------------------------------------------------------
# Actual / Pass-Fail / Log 채우기
# ---------------------------------------------------------------------------

def _fill_actual_and_result(
    ws,
    blocks: list[dict[str, Any]],
    fn_iter_map: dict[str, dict[int, Any]],
    asil_map: dict[str, str],
    out_warnings: list[str] | None,
) -> dict[str, int]:
    """spec 함수 블록에 Actual/Pass-Fail/Log 채움.

    Returns: 통계 dict (functions/iterations/matched_fn/unmatched_fn/
        inexact_actual).
    """
    from openpyxl.utils import get_column_letter  # noqa: F401

    stats = {
        "functions": 0, "iterations": 0,
        "matched_fn": 0, "unmatched_fn": 0,
        "fn_pass": 0, "fn_fail": 0, "fn_na": 0,
        "iter_pass": 0, "iter_fail": 0, "iter_na": 0,
        "actual_from_expected": 0, "actual_from_vcast": 0, "actual_missing": 0,
    }
    unmatched_list: list[str] = []

    for blk in blocks:
        stats["functions"] += 1
        anchor = blk["anchor"]
        num = (blk["num"] or "").lstrip("0") or "0"
        iter_data = fn_iter_map.get(num)

        # Expected 변수 열 (anchor) = Actual 변수 열 offset.
        exp_cols = _expected_var_cols(ws, anchor)
        # Actual 변수명 = Expected 변수명 (감사본 패턴) — anchor에 stamp.
        for off, ec in enumerate(exp_cols):
            if off >= ACTUAL_MAX:
                break
            var_name = ws.cell(anchor, ec).value
            safe_write(ws, anchor, COL_ACTUAL_START + off, var_name)

        if iter_data is None:
            stats["unmatched_fn"] += 1
            if len(unmatched_list) < 40:
                unmatched_list.append(f"{blk['tc_id']}({blk['unit']})")
            # 미매칭 함수 — Pass/Fail N/A 표기 + Total N/A.
            for ir in blk["iter_rows"]:
                safe_write(ws, ir, COL_PASS_FAIL, "N/A")
                stats["iter_na"] += 1
                stats["iterations"] += 1
            safe_write(ws, anchor, COL_PASS_TOTAL, "N/A")
            stats["fn_na"] += 1
            if blk["iter_rows"]:
                try:
                    ws.merge_cells(
                        start_row=anchor, end_row=blk["iter_rows"][-1],
                        start_column=COL_PASS_TOTAL, end_column=COL_PASS_TOTAL,
                    )
                except (ValueError, AttributeError):
                    pass
            _apply_asil_mark(ws, anchor, num, blk, asil_map)
            continue

        stats["matched_fn"] += 1
        any_exec = False
        all_pass = True

        for fallback_idx, ir in enumerate(blk["iter_rows"], start=1):
            stats["iterations"] += 1
            raw_iter_idx = ws.cell(ir, COL_ITER_INDEX).value
            try:
                it_idx = int(str(raw_iter_idx).strip())
            except (TypeError, ValueError):
                it_idx = fallback_idx
            rec = iter_data.get(it_idx)
            if rec is None:
                safe_write(ws, ir, COL_PASS_FAIL, "N/A")
                stats["iter_na"] += 1
                continue
            passed = rec["passed"]
            if passed is None:
                safe_write(ws, ir, COL_PASS_FAIL, "N/A")
                stats["iter_na"] += 1
                continue
            any_exec = True
            # Actual 값 채우기 — Pass면 Expected 복제 (감사본 패턴), Fail이면 vcast.
            for off, ec in enumerate(exp_cols):
                if off >= ACTUAL_MAX:
                    break
                ac = COL_ACTUAL_START + off
                if passed:
                    exp_val = ws.cell(ir, ec).value
                    safe_write(ws, ir, ac, exp_val)
                    stats["actual_from_expected"] += 1
                else:
                    var_name = ws.cell(anchor, ec).value
                    av = _lookup_vcast_actual(rec["actual"], var_name)
                    if av is not None:
                        safe_write(ws, ir, ac, av)
                        stats["actual_from_vcast"] += 1
                    else:
                        _mark_cell(ws, ir, ac)
                        stats["actual_missing"] += 1
            if passed:
                safe_write(ws, ir, COL_PASS_FAIL, "Pass")
                stats["iter_pass"] += 1
            else:
                all_pass = False
                safe_write(ws, ir, COL_PASS_FAIL, "Fail")
                stats["iter_fail"] += 1
        total_str = "Pass" if (any_exec and all_pass) else ("Fail" if any_exec else "N/A")
        if total_str == "Pass":
            stats["fn_pass"] += 1
        elif total_str == "Fail":
            stats["fn_fail"] += 1
        else:
            stats["fn_na"] += 1
        safe_write(ws, anchor, COL_PASS_TOTAL, total_str)
        # 라운드 91 fix — 레퍼런스 감사본은 anchor 행 JF(Pass/Fail)에도 함수 결과를
        # 표기(첫 iteration 겸용 양식). anchor JF=total로 정합 (이전: anchor JF 공란).
        safe_write(ws, anchor, COL_PASS_FAIL, total_str)
        # 함수 Total 세로 병합 (anchor ~ 마지막 iteration).
        if blk["iter_rows"]:
            try:
                ws.merge_cells(
                    start_row=anchor, end_row=blk["iter_rows"][-1],
                    start_column=COL_PASS_TOTAL, end_column=COL_PASS_TOTAL,
                )
            except (ValueError, AttributeError):
                pass
        _apply_asil_mark(ws, anchor, num, blk, asil_map)

    if unmatched_list and out_warnings is not None:
        out_warnings.append(
            f"[spec-sutr] 함수↔SwUFn 매칭 실패 {stats['unmatched_fn']}건 — "
            f"Pass/Fail N/A 표기. 예: {', '.join(unmatched_list[:15])}"
        )
    return stats


def _lookup_vcast_actual(actual_dict: dict, var_name: Any) -> Any:
    """vcast actual_result(dict{var:(actual,exp)})에서 var_name best-effort 조회.

    dotted 변수명(예 ``_LP0DR.Byte``)이 분리될 수 있어 여러 후보 시도.
    매칭 0이면 None.
    """
    if not actual_dict or not var_name:
        return None
    vn = str(var_name).strip()
    cand = [vn]
    if "." in vn:
        cand.extend(vn.split("."))
    cand.append(vn.lstrip("_"))
    for k in cand:
        if k in actual_dict:
            t = actual_dict[k]
            if isinstance(t, tuple) and t:
                return t[0] if t[0] not in (None, "") else None
            return t if t not in (None, "") else None
    return None


def _apply_asil_mark(ws, anchor: int, num: str, blk: dict, asil_map: dict[str, str]) -> None:
    """anchor의 Total(JG) 셀에 ASIL 등급 시각 강조."""
    fn_id = f"SwUFn_{num.zfill(4)}" if num else ""
    asil = asil_map.get(fn_id, "") if fn_id else ""
    marker = {
        "A": mark_asil_a_function, "B": mark_asil_b_function,
        "C": mark_asil_c_function, "D": mark_asil_d_function,
        "QM": mark_asil_qm_function,
    }.get((asil or "").strip().upper())
    if marker:
        marker(ws, anchor, COL_PASS_TOTAL)


def _mark_cell(ws, row: int, col: int) -> None:
    """Actual 부재 셀 노란 마킹 (audit 가시성)."""
    try:
        from openpyxl.styles import PatternFill
        ws.cell(row, col).fill = PatternFill(
            start_color=_FILL_RGB, end_color=_FILL_RGB, fill_type="solid",
        )
    except (ValueError, AttributeError):
        pass


def _write_cover_meta_legacy(
    wb: Workbook, meta: SutrBuildMeta, out_warnings: list[str] | None,
) -> None:
    """라운드 91 호환 — spec wb 베이스 Cover 시트 best-effort label stamp.

    표준 SUTR 템플릿 미제공(template_xlsm_bytes=None) fallback 경로 전용.
    """
    cover = next((wb[n] for n in wb.sheetnames if n.lower() == "cover"), None)
    if cover is None:
        if out_warnings is not None:
            out_warnings.append("[spec-sutr] Cover 시트 미발견 — meta stamp skip")
        return
    write_value_after_label(cover, "Project", meta.project_full_name)
    write_value_after_label(cover, "ASIL Level", meta.asil_level)
    write_value_after_label(cover, "Version", f"v{meta.release_sw_version}")
    write_value_after_label(cover, "Test Date", meta.test_date)
    if meta.author:
        write_value_after_label(cover, "Author", meta.author)
    if meta.approver:
        write_value_after_label(cover, "Approver", meta.approver)


def _fill_standard_aux_sheets(
    wb: Workbook,
    meta: SutrBuildMeta,
    session: SwUTSession,
    agg: dict[str, Any],
    summary: dict[str, Any],
    deviation_cases: list[Any] | None,
    out_warnings: list[str],
) -> None:
    """표준 SUTR 템플릿의 Cover / 1.Test Summary / 2.Deviation / History 채움 (R92).

    표준 ``swut_sutr_aggregator`` writer 재사용 — `build_sutr` (표준 양식) 와 동일
    로직으로 meta + TC 카운트 + Requirements coverage 를 stamp. 3.Test Log 는 spec
    시트 이식 (별도 처리) 이므로 여기서 건드리지 않는다.
    """
    from backend.services.excel_template_utils import build_release_history_row
    from backend.services.swut_coverage_aggregator import _write_history_sheet
    from backend.services.swut_sutr_aggregator import (
        _write_cover,
        _write_deviation,
        _write_test_summary,
    )

    sheet_names = wb.sheetnames

    # layout=None — 표준 v3.01 양식의 라벨 기반 find_kv_row 경로 사용. _write_test_summary
    # 의 TC stats(layout 의존) 분기는 layout None 시 skip되고, 함수 단위 카운트는
    # _fill_test_summary_counts 가 별도로 stamp (레퍼런스 감사본 정합).

    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        out_warnings.append("[spec-sutr] Cover 시트 미발견")
    else:
        _write_cover(cover_ws, meta, out_warnings=out_warnings)

    ts_ws = next((wb[n] for n in sheet_names if "test summary" in n.lower()), None)
    if ts_ws is None:
        out_warnings.append("[spec-sutr] 1.Test Summary 시트 미발견")
    else:
        _write_test_summary(
            ts_ws, meta, agg, out_warnings=out_warnings,
            layout=None, summary=summary,
        )

    dev_ws = next((wb[n] for n in sheet_names if "deviation" in n.lower()), None)
    if dev_ws is None:
        out_warnings.append("[spec-sutr] 2.Deviation 시트 미발견")
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases, out_warnings=out_warnings)
        summary["deviation_cases_written"] = n

    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        release_rows = build_release_history_row(
            meta, doc_kind="SwUT SUTR (spec-based)", out_warnings=out_warnings,
        )
        n_h = _write_history_sheet(hist_ws, release_rows, out_warnings=out_warnings)
        summary["history_rows_written"] = n_h


def _fill_test_summary_counts(
    wb: Workbook, summary: dict[str, Any], fill_stats: dict[str, int],
    out_warnings: list[str],
) -> None:
    """1.Test Summary TC 카운트를 spec 매칭 결과로 보정 (R92).

    표준 `_write_test_summary` 는 session aggregate (VectorCAST TC 단위) 기준 카운트를
    stamp 한다. 레퍼런스 감사본 1.Test Summary 의 카운트는 **함수 단위** (Total Number
    of TCs = 함수 570) 이므로, spec 함수 블록 매칭 결과로 r17/r18 영역을 덮어쓴다.

    레퍼런스 실측: Total=570 / Tested=569 / Passed=569 / Failed=0 / not-exec=1.
    = spec_function_blocks / matched_fn / iter pass·fail 기반 산출.
    """
    ts_ws = next((wb[n] for n in wb.sheetnames if "test summary" in n.lower()), None)
    if ts_ws is None:
        return
    from backend.services.excel_template_utils import find_kv_row

    total = fill_stats.get("functions", 0)
    # 함수 단위 카운트 (레퍼런스 감사본 1.Test Summary 기준):
    #   not_exec = Total 'N/A' 함수 (미매칭 + 매칭됐으나 실행 iteration 0).
    #   passed = Total 'Pass', failed = Total 'Fail', tested = passed + failed.
    not_exec = fill_stats.get("fn_na", 0)
    passed = fill_stats.get("fn_pass", 0)
    failed = fill_stats.get("fn_fail", 0)
    tested = passed + failed

    pos = find_kv_row(ts_ws, "Total Number of TCs", max_row=30)
    if pos is None:
        out_warnings.append(
            "[spec-sutr] 1.Test Summary 'Total Number of TCs' 헤더 미발견 — TC 카운트 stamp skip"
        )
        return
    data_row = pos[0] + 1
    col = pos[1]
    safe_write(ts_ws, data_row, col, total)
    safe_write(ts_ws, data_row, col + 1, tested)
    safe_write(ts_ws, data_row, col + 2, passed)
    safe_write(ts_ws, data_row, col + 3, failed)
    safe_write(ts_ws, data_row, col + 4, not_exec)
    summary["test_summary_tc_total"] = total
    summary["test_summary_tested"] = tested
    summary["test_summary_passed"] = passed
    summary["test_summary_failed"] = failed
    summary["test_summary_not_executed"] = not_exec

    # Requirements/Design Coverage (SWUDS row) — 함수 수 기반.
    req_pos = find_kv_row(ts_ws, "System Design", max_row=30)
    if req_pos is None:
        req_pos = find_kv_row(ts_ws, "SWUDS", max_row=30)
    if req_pos is not None:
        rr, rc = req_pos
        safe_write(ts_ws, rr, rc + 1, total)     # can be tested
        safe_write(ts_ws, rr, rc + 2, tested)    # tested
        safe_write(ts_ws, rr, rc + 3, not_exec)  # not tested
        summary["requirements_swuds_total"] = total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sutr_from_spec(
    session: SwUTSession,
    meta: SutrBuildMeta,
    spec_xlsm_bytes: bytes,
    *,
    template_xlsm_bytes: bytes | None = None,
    function_asil_map: dict[str, str] | None = None,
    deviation_cases: list[Any] | None = None,
) -> SutrBuildResult:
    """SUTR 생성 — 표준 SUTR 템플릿 베이스 + SwUTS spec '3.Test Log' 이식 (라운드 92).

    라운드 91은 spec wb 자체를 베이스로 써 출력 시트 구성이 틀렸다 (Introduction /
    1.Test Environment 포함, 1.Test Summary / 2.Deviation 누락). 라운드 92는 표준 SUTR
    템플릿을 베이스로 하고, spec '2.SW Unit Test Spec' (와이드 268열) 시트만 '3.Test
    Log'로 이식하여 레퍼런스 시트 구성 [Cover / History / 1.Test Summary / 2.Deviation
    / 3.Test Log]을 맞춘다.

    Args:
        session: collect_swut_session 출력 (VectorCAST Actual/Pass-Fail source).
        meta: 빌드 메타 (Cover / Test Summary / History stamp).
        spec_xlsm_bytes: SwUTS spec xlsm bytes ('2.SW Unit Test Spec' — Input/Expected/
            TC 보존, '3.Test Log'로 이식).
        template_xlsm_bytes: 표준 SUTR 템플릿 xlsm bytes (베이스 — Cover/History/
            1.Test Summary/2.Deviation/3.Test Result 보유). None이면 backward-compat
            으로 spec wb 베이스 (라운드 91 동작) — audit 비권장, warning 누적.
        function_asil_map: SwUFn_NNNN → ASIL 등급 (옵션, anchor 시각 강조).
        deviation_cases: 2.Deviation 시트 stamp용 (옵션).

    Returns:
        SutrBuildResult — xlsm_io에 표준 템플릿 + spec 이식 '3.Test Log' + Actual/
        Pass-Fail/Log + Cover/Test Summary/Deviation/History stamp.
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for spec-based SUTR builder")

    validate_build_meta(
        meta.release_sw_version, meta.test_date,
        doc_id_sequence=meta.doc_id_sequence,
        test_engineer=meta.test_engineer,
        author=meta.default_author,
        approver=meta.default_approver or meta.approver_override,
        reviewer=meta.default_reviewer or meta.reviewer_override,
    )
    validate_xlsx_template_bytes(spec_xlsm_bytes, label="SwUTS spec xlsm")

    spec_sha256_12 = hashlib.sha256(spec_xlsm_bytes).hexdigest()[:12]
    warnings: list[str] = extract_warnings_from_session(session)
    asil_map = function_asil_map or {}

    # VBA 검사 — spec + (있으면) 표준 템플릿 둘 다 keep_vba.
    spec_has_vba = has_vba_macros(spec_xlsm_bytes)
    template_has_vba = spec_has_vba
    if template_xlsm_bytes is not None:
        validate_xlsx_template_bytes(template_xlsm_bytes, label="표준 SUTR 템플릿 xlsm")
        template_has_vba = has_vba_macros(template_xlsm_bytes)
    if template_has_vba or spec_has_vba:
        warnings.append(
            "VBA macro execution NOT verified — open output xlsm in Excel and verify "
            "macros before submitting as evidence"
        )
        refs = inspect_vba_refs(template_xlsm_bytes or spec_xlsm_bytes)
        if refs:
            warnings.append(
                f"VBA stale ref 위험 패턴 — {refs} (셀/시트 이동 시 매크로 깨질 위험)"
            )

    # spec wb 로드 (Test Log source).
    spec_wb: Workbook = openpyxl.load_workbook(
        io.BytesIO(spec_xlsm_bytes), keep_vba=True, data_only=False,
    )
    spec_ws, spec_name = _find_spec_sheet(spec_wb)
    if spec_ws is None:
        warnings.append("[spec-sutr] SwUTS spec 시트 미발견 — 빌드 불가")
        spec_wb.close()
        return SutrBuildResult(ok=False, warnings=warnings)

    agg = aggregate_session(session)

    if template_xlsm_bytes is not None:
        # 라운드 92 — 표준 SUTR 템플릿을 베이스로 로드.
        wb: Workbook = openpyxl.load_workbook(
            io.BytesIO(template_xlsm_bytes), keep_vba=True, data_only=False,
        )
        # 표준의 좁은 '3.Test Result' 시트 제거.
        for nm in list(wb.sheetnames):
            low = nm.lower()
            if "test result" in low or low == LOG_SHEET_NAME.lower():
                del wb[nm]
        # spec 와이드 시트를 '3.Test Log'로 풀 카피 이식 (끝에 추가).
        log_ws = copy_sheet_across_workbooks(
            spec_ws, wb, new_title=LOG_SHEET_NAME, insert_index=None,
        )
    else:
        # backward-compat (라운드 91) — spec wb 자체 베이스. audit 비권장.
        warnings.append(
            "[spec-sutr] 표준 SUTR 템플릿 미제공 — spec wb 베이스 fallback (라운드 91 호환). "
            "시트 구성이 레퍼런스(Cover/History/1.Test Summary/2.Deviation/3.Test Log)와 "
            "다를 수 있음 — config sutr_template 등록 권장"
        )
        wb = spec_wb
        if spec_name != LOG_SHEET_NAME and LOG_SHEET_NAME not in wb.sheetnames:
            spec_ws.title = LOG_SHEET_NAME
        log_ws = spec_ws

    # 헤더 추가 (Actual/Pass-Fail/Log).
    _write_log_headers(log_ws, warnings)

    # anchor 스캔 → 함수 블록 (이식된 '3.Test Log' 시트 기준).
    blocks = _scan_spec_blocks(log_ws)
    fn_iter_map = _build_fn_iteration_map(session)

    fill_stats = _fill_actual_and_result(
        log_ws, blocks, fn_iter_map, asil_map, warnings,
    )

    # 라운드 104 — Actual Result 열(FF=162~JE=265) 서식 적용. spec graft는 Test Case/
    # Input/Expected 까지만 서식 보유, Actual 이후는 우리 추가 열이라 무서식(무테/
    # default 폰트) → 사용자 보고 "Actual만 템플릿 미적용". Expected(BF=58~FE=161)를
    # 1:1 미러. **같은 wb 내**이므로 cross-wb 객체복사가 아닌 ``_style`` 인덱스 직접
    # 복사가 정확+빠름 (라운드 103 cross-wb 문제와 구분). value는 보존(_style만 복제).
    _restyled = _apply_actual_result_style(log_ws)

    summary = {
        "builder": "spec-based-r92" if template_xlsm_bytes is not None else "spec-based-r91",
        "spec_sheet": spec_name,
        "spec_sha256_12": spec_sha256_12,
        "build_timestamp": meta.build_timestamp,
        "environments": len(session.environments),
        "total": agg["total"],
        "tested": agg["tested"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "spec_function_blocks": fill_stats["functions"],
        "matched_functions": fill_stats["matched_fn"],
        "unmatched_functions": fill_stats["unmatched_fn"],
        "fn_pass": fill_stats["fn_pass"],
        "fn_fail": fill_stats["fn_fail"],
        "fn_na": fill_stats["fn_na"],
        "iteration_rows": fill_stats["iterations"],
        "iter_pass": fill_stats["iter_pass"],
        "iter_fail": fill_stats["iter_fail"],
        "iter_na": fill_stats["iter_na"],
        "actual_from_expected": fill_stats["actual_from_expected"],
        "actual_from_vcast": fill_stats["actual_from_vcast"],
        "actual_missing": fill_stats["actual_missing"],
        "actual_cells_restyled": _restyled,
    }

    # 보조 시트 채움 (Cover / 1.Test Summary / 2.Deviation / History).
    if template_xlsm_bytes is not None:
        _fill_standard_aux_sheets(
            wb, meta, session, agg, summary, deviation_cases, warnings,
        )
        # 1.Test Summary TC 카운트를 함수 단위로 보정 (레퍼런스 정합).
        _fill_test_summary_counts(wb, summary, fill_stats, warnings)
    else:
        # backward-compat — 라운드 91 Cover label stamp만.
        _write_cover_meta_legacy(wb, meta, warnings)

    # 시트 순서 정리 — 3.Test Log가 2.Deviation 뒤에 오도록 (표준 베이스만).
    if template_xlsm_bytes is not None and LOG_SHEET_NAME in wb.sheetnames:
        names = [n for n in wb.sheetnames if n != "AuditLog"]
        # 표준 순서: Cover, History, 1.Test Summary, 2.Deviation, 3.Test Log
        # copy_sheet가 끝에 넣었으므로 이미 마지막 (AuditLog 미존재 시) — 명시 정렬.
        summary["output_sheet_order"] = names

    out = io.BytesIO()
    wb.save(out)
    if wb is not spec_wb:
        spec_wb.close()
    wb.close()

    # 라운드 101 — 회사 ★개발템플릿 잔재(독일어 HARA externalLink + 외부참조
    # defined names) 제거 → Excel "연결 업데이트/복구" 경고 차단. keep_vba 로드 시
    # 외부링크 파트가 raw archive로 보존돼 openpyxl 객체 조작이 무효 → save된
    # bytes를 zip 레벨에서 직접 정화.
    _sanitized, _ext_removed = sanitize_xlsm_external_links(out.getvalue())
    if _ext_removed:
        out = io.BytesIO(_sanitized)
        summary["external_links_stripped"] = _ext_removed
        warnings.append(
            f"[spec-sutr] 템플릿 외부링크 파트 {_ext_removed}건 + 외부참조 defined "
            "name 제거 (독일어 HARA 양식 잔재 — Excel 연결 경고 차단)"
        )
    out.seek(0)

    if meta.doc_filename_pattern:
        filename = meta.doc_filename_pattern.format(
            version=meta.release_sw_version, date=short_date(meta.test_date),
        )
    else:
        filename = (
            f"({meta.project_id}_DV_SwUTR) Software Unit Test Result_"
            f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsm"
        )

    return SutrBuildResult(
        ok=True,
        xlsm_io=out,
        filename=filename,
        warnings=warnings,
        vba_macros_preserved=template_has_vba,
        summary=summary,
    )


__all__ = [
    "build_sutr_from_spec",
    "LOG_SHEET_NAME",
    "COL_ACTUAL_START",
    "COL_PASS_FAIL",
    "COL_PASS_TOTAL",
    "COL_LOG_DATA",
    "SPEC_SHEET_RE",
]
