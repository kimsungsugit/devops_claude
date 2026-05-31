"""SwUT SUTR (Software Unit Test Result) — **spec-based** Test Log 빌더 (라운드 91).

회사 감사본 양식(KJPDS02 v1.01 등)은 SUTR '3.Test Log' 시트가 SwUTS spec의
'2.SW Unit Test Spec' 시트(Test Case + Input + Expected 이미 완비)와 **동일 구조** +
Actual Result / Pass-Fail / Log Data 섹션 추가다.

기존 ``swut_sutr_aggregator.build_sutr`` (표준 Version3 좁은 38열 양식 + 함수별 블록
재구성)와는 양식이 근본적으로 다르므로 **신규 경로**로 분리한다.

## 핵심 전략 — spec 시트 template-copy

1. SwUTS spec xlsm을 keep_vba로 로드.
2. '2.SW Unit Test Spec' 시트를 **그대로 활용** (Input/Expected/TC_ID/Unit/Method/
   Generation/iteration 전부 보존 — 검증/수정 금지) + 시트명을 '3.Test Log'로 rename.
3. 레퍼런스 SUTR 레이아웃에 맞춰 Actual/Pass-Fail/Log 섹션의 **헤더(r3 병합 + r4
   서브헤더)** 를 프로그램으로 추가.
4. spec anchor 행(B=Index digit, C=TC_ID, D=Unit)을 스캔 → 함수 블록 식별 →
   VectorCAST 로그 매칭으로 Actual 값 / iteration Pass-Fail(JF) / 함수 Total(JG) /
   Log Data(JH) 채움.

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
from dataclasses import dataclass, field
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.design_tokens import USER_INPUT_FILL_RGB
from backend.services.excel_template_utils import (
    has_vba_macros,
    inspect_vba_refs,
    mark_asil_a_function,
    mark_asil_b_function,
    mark_asil_c_function,
    mark_asil_d_function,
    mark_asil_qm_function,
    safe_write,
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
            _apply_asil_mark(ws, anchor, num, blk, asil_map)
            continue

        stats["matched_fn"] += 1
        any_exec = False
        all_pass = True

        for it_idx, ir in enumerate(blk["iter_rows"], start=1):
            stats["iterations"] += 1
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
            # Log Data (iteration env/tc).
            env = rec.get("env")
            if env is not None and getattr(env, "env_name", ""):
                safe_write(
                    ws, ir, COL_LOG_DATA,
                    f"{env.env_name}/{rec.get('tc_name', '')}.html",
                )

        total_str = "Pass" if (any_exec and all_pass) else ("Fail" if any_exec else "N/A")
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


def _write_cover_meta(wb: Workbook, meta: SutrBuildMeta, out_warnings: list[str] | None) -> None:
    """spec에서 가져온 Cover 시트에 SUTR meta 갱신 (best-effort label 매칭)."""
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sutr_from_spec(
    session: SwUTSession,
    meta: SutrBuildMeta,
    spec_xlsm_bytes: bytes,
    *,
    function_asil_map: dict[str, str] | None = None,
) -> SutrBuildResult:
    """SwUTS spec 시트 기반 SUTR '3.Test Log' 생성 (라운드 91, 회사 감사본 양식).

    Args:
        session: collect_swut_session 출력 (VectorCAST Actual/Pass-Fail source).
        meta: 빌드 메타 (Cover stamp).
        spec_xlsm_bytes: SwUTS spec xlsm bytes (베이스 — Input/Expected/TC 보존).
        function_asil_map: SwUFn_NNNN → ASIL 등급 (옵션, anchor 시각 강조).

    Returns:
        SutrBuildResult — xlsm_io에 spec 복사본 + Actual/Pass-Fail/Log 추가.
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

    template_has_vba = has_vba_macros(spec_xlsm_bytes)
    if template_has_vba:
        warnings.append(
            "VBA macro execution NOT verified — open output xlsm in Excel and verify "
            "macros before submitting as evidence"
        )
        refs = inspect_vba_refs(spec_xlsm_bytes)
        if refs:
            warnings.append(
                f"VBA stale ref 위험 패턴 — {refs} (셀/시트 이동 시 매크로 깨질 위험)"
            )

    wb: Workbook = openpyxl.load_workbook(
        io.BytesIO(spec_xlsm_bytes), keep_vba=True, data_only=False,
    )

    spec_ws, spec_name = _find_spec_sheet(wb)
    if spec_ws is None:
        warnings.append("[spec-sutr] SwUTS spec 시트 미발견 — 빌드 불가")
        return SutrBuildResult(ok=False, warnings=warnings)

    # 시트명을 '3.Test Log'로 변경.
    if spec_name != LOG_SHEET_NAME and LOG_SHEET_NAME not in wb.sheetnames:
        spec_ws.title = LOG_SHEET_NAME

    # 헤더 추가 (Actual/Pass-Fail/Log).
    _write_log_headers(spec_ws, warnings)

    # anchor 스캔 → 함수 블록.
    blocks = _scan_spec_blocks(spec_ws)
    fn_iter_map = _build_fn_iteration_map(session)

    fill_stats = _fill_actual_and_result(
        spec_ws, blocks, fn_iter_map, asil_map, warnings,
    )

    # Cover meta 갱신.
    _write_cover_meta(wb, meta, warnings)

    agg = aggregate_session(session)
    summary = {
        "builder": "spec-based",
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
        "iteration_rows": fill_stats["iterations"],
        "iter_pass": fill_stats["iter_pass"],
        "iter_fail": fill_stats["iter_fail"],
        "iter_na": fill_stats["iter_na"],
        "actual_from_expected": fill_stats["actual_from_expected"],
        "actual_from_vcast": fill_stats["actual_from_vcast"],
        "actual_missing": fill_stats["actual_missing"],
    }

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    wb.close()

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
]
