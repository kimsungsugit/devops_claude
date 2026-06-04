"""SwSA aggregator — 회사 SwSA 템플릿(.xlsm)에 정적분석 결과 채우기.

SwUT/SwIT template-copy 전략 동일: ``openpyxl.load_workbook(keep_vba=True)`` 로
회사 양식을 in-place 로 열어(셀병합/폰트/매크로 보존) 라벨 앵커로 셀만 덮어쓴다.

채우는 시트 (템플릿에 **존재하는 것만**):
  - Cover (META): doc_id/version/status/date/author
  - Summary 헤더 (META): project/phase/platform/asil/compiler/mcu
  - ST101 (AUTO): QAC results_data.xml M3CM → 위반 룰 개수 / 총 위반. 예외처리/
    수정대상은 로그 부재 → 노란 표시.
  - ST201 (AUTO): QAC HMR 메트릭 + PMD 중복 → Test-Info + (best-effort 결과)
  - ST1101 (AUTO): QAC HKCCM → Test-Info + 총 위반
  - 모든 실행 ST 시트: Test-Information(분석차수/SW Ver/Tester/Debugger)

판정 셀(예외처리/수정대상/P-F)은 QAC 에서 도출 불가 → ``write_value_or_mark`` 로
값 없으면 노란 '사용자 입력 필요'. extraction_failed 시에도 0 stamp 대신 노란 표시.

ISO 26262: 산출물은 evidence 'auto-generated draft'. reviewer 검토 의무.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, List, Optional

from openpyxl import load_workbook

from backend.services.excel_template_utils import (
    has_vba_macros,
    mark_user_input_required,
    safe_write,
    write_value_or_mark,
)
from backend.services.swsa_layout_resolver import (
    detect_st_layout,
    find_label_row,
    find_value_target,
)
from backend.services.swsa_meta import SwsaBuildMeta
from backend.services.swsa_pmd_parser import PmdResult
from backend.services.swsa_qac_xml_parser import (
    MISRA_MANDATORY,
    MISRA_REQUIRED,
    QacXmlResult,
)
from backend.services.swsa_st201_binner import (
    St201Result,
    bin_values_into_bands,
    metric_item_for_name,
    parse_band_predicate,
)

__all__ = ["SwsaBuildResult", "build_swsa_report"]

# 양식 시트명 (존재할 때만 채움)
SHEET_COVER = "Cover"
SHEET_SUMMARY = "Summary"
SHEET_ST101 = "1.ST101"
SHEET_ST201 = "2.ST201"
SHEET_ST1101 = "11.ST1101"


@dataclass
class SwsaBuildResult:
    xlsm_io: io.BytesIO
    sheets_filled: List[str] = field(default_factory=list)
    filled_cells: int = 0
    user_input_cells: int = 0
    warnings: List[str] = field(default_factory=list)
    vba_preserved: bool = False


def _stamp(ws: Any, label: str, value: Any, *, max_row: int = 40,
           label_col: Optional[int] = None) -> bool:
    """라벨 옆 셀에 값 기입 (merge-aware). 라벨 없으면 False."""
    tgt = find_value_target(ws, label, max_row=max_row, label_col=label_col)
    if tgt is None:
        return False
    return safe_write(ws, tgt[0], tgt[1], value)


def _stamp_or_mark(ws: Any, label: str, value: Any, *, hint: str = "", max_row: int = 120,
                   label_col: Optional[int] = None) -> Optional[bool]:
    """라벨 옆 셀에 값/노란표시. 라벨 없으면 None."""
    tgt = find_value_target(ws, label, max_row=max_row, label_col=label_col)
    if tgt is None:
        return None
    return write_value_or_mark(ws, tgt[0], tgt[1], value, hint=hint)


# ─────────────────────────── Cover ───────────────────────────
def _write_cover(ws: Any, meta: SwsaBuildMeta, res: SwsaBuildResult) -> None:
    pairs = [
        ("Document ID", meta.doc_id),
        ("Version", meta.doc_version),
        ("Status", meta.doc_status),
        ("Date", meta.test_date),
        ("Author", meta.author),
    ]
    n = 0
    for label, val in pairs:
        # doc-block 라벨은 col C(3) — 사인오프 헤더 I2 'Author' 충돌 회피
        if _stamp(ws, label, val, max_row=40, label_col=3):
            n += 1
    res.filled_cells += n
    if n:
        res.sheets_filled.append(SHEET_COVER)


# ─────────────────────────── Summary ───────────────────────────
def _write_summary_header(ws: Any, meta: SwsaBuildMeta, res: SwsaBuildResult) -> None:
    asil = meta.asil_level.replace("ASIL", "").strip() or meta.asil_level  # 'ASIL A' → 'A'
    pairs = [
        ("Project", meta.project_id),
        ("Phase", meta.phase),
        ("Software Platform Ver.", meta.platform_version),
        ("Product", meta.product),
        ("검증 대상", meta.verification_target),
        ("ASIL 등급", asil),
        ("Complier", meta.compiler),   # 양식 철자 그대로 (Complier)
        ("MCU", meta.mcu),
    ]
    n = 0
    for label, val in pairs:
        # Summary 정보블록 라벨은 col B(2) — 검증대상 값 'MCU' 가 'MCU' 라벨과
        # 충돌하던 문제 회피 (값은 col E 에 쓰이므로 label_col=2 로 라벨만 매칭)
        r = _stamp_or_mark(ws, label, val, hint=label, max_row=14, label_col=2)
        if r is not None:
            n += 1
            if r is False:
                res.user_input_cells += 1
    res.filled_cells += n
    if n:
        res.sheets_filled.append(SHEET_SUMMARY)


# ─────────────────────── ST 공통 Test-Info ───────────────────────
def _write_st_test_info(ws: Any, meta: SwsaBuildMeta, res: SwsaBuildResult) -> bool:
    """모든 실행 ST 시트의 Test-Information 헤더 채우기. 라벨 앵커로 버전 흡수."""
    lay = detect_st_layout(ws)
    if lay.missing:
        res.warnings.append(f"{ws.title}: Test-Info 라벨 미발견 {lay.missing}")
    values = {
        "analysis_round": meta.analysis_round,
        "sw_version": meta.release_sw_version,
        "tester": meta.tester_name,
        "debugger": meta.debugger,
    }
    n = 0
    for key, (r, c) in lay.test_info.items():
        val = values.get(key, "")
        if write_value_or_mark(ws, r, c, val, hint=key):
            n += 1
        else:
            res.user_input_cells += 1
    res.filled_cells += n
    return bool(lay.test_info)


def _find_summary_rows(ws: Any, header_row: int, label_col_max: int = 4) -> dict:
    """ST101 Test Summary 표의 Mandatory/Required/Total 행 탐색.

    v0.11 은 3행(Mandatory/Required/Total), v0.10 은 단일행 → Total=header+1 default.
    """
    rows = {}
    for r in range(header_row + 1, header_row + 6):
        for c in range(1, label_col_max + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str):
                vs = v.strip()
                if vs in ("Mandatory", "Required", "Total"):
                    rows[vs] = r
    if not rows:
        rows["Total"] = header_row + 1
    return rows


# ─────────────────────────── ST101 ───────────────────────────
def _write_st101(ws: Any, meta: SwsaBuildMeta, qac: Optional[QacXmlResult], res: SwsaBuildResult) -> None:
    _write_st_test_info(ws, meta, res)
    # 코딩룰 버전
    _stamp(ws, "코딩룰 버전", meta.misra_rule_version, max_row=12)

    misra = qac.misra if qac else None
    failed = (qac is None) or qac.extraction_failed or (misra is None)

    # Test Summary 표: 헤더 '총 위반 건수' / '위반 룰 개수' 라벨 앵커
    h_total = find_label_row(ws, "총 위반 건수", max_row=120)
    h_rules = find_label_row(ws, "위반 룰 개수", max_row=120)
    h_exc = find_label_row(ws, "예외 처리 항목 수", max_row=120)
    if h_total is None:
        res.warnings.append(f"{ws.title}: '총 위반 건수' 헤더 미발견 — Summary 표 미기입")
    else:
        hr = h_total[0]
        srows = _find_summary_rows(ws, hr)
        # 카테고리별 값 (v0.11 Mandatory/Required/Total) — v0.10 은 Total 만
        cat_active = {}
        cat_rules = {}
        if misra is not None:
            cat_active["Total"] = misra.active
            cat_rules["Total"] = misra.distinct_rules()
            cat_active["Mandatory"] = misra.category(MISRA_MANDATORY).active
            cat_active["Required"] = misra.category(MISRA_REQUIRED).active
            cat_rules["Mandatory"] = sum(
                1 for r in misra.leaf_rules if r.severity == MISRA_MANDATORY and r.active > 0)
            cat_rules["Required"] = sum(
                1 for r in misra.leaf_rules if r.severity == MISRA_REQUIRED and r.active > 0)
        for cat, r in srows.items():
            # 총 위반 건수
            if failed:
                mark_user_input_required(ws, r, h_total[1], hint="QAC 추출 실패")
                res.user_input_cells += 1
            else:
                safe_write(ws, r, h_total[1], cat_active.get(cat, 0))
                res.filled_cells += 1
            # 위반 룰 개수
            if h_rules is not None:
                if failed:
                    mark_user_input_required(ws, r, h_rules[1], hint="QAC 추출 실패")
                    res.user_input_cells += 1
                else:
                    safe_write(ws, r, h_rules[1], cat_rules.get(cat, 0))
                    res.filled_cells += 1
            # 예외 처리 항목 수 — 로그 부재 → 노란 표시 (리뷰어 판정)
            if h_exc is not None:
                mark_user_input_required(ws, r, h_exc[1], hint="리뷰어 Deviation 판정")
                res.user_input_cells += 1

    # Test Environment: 도구명 / Version
    if misra is not None and qac is not None:
        _stamp(ws, "도구명", "Helix QAC", max_row=80)
        ver = qac.helix_qac_version.replace("Helix QAC", "").split("(")[0].strip()
        if ver:
            _stamp(ws, "Version", ver, max_row=80)

    res.sheets_filled.append(SHEET_ST101)


# ─────────────────────────── ST201 ───────────────────────────
def _write_st201(ws: Any, meta: SwsaBuildMeta, st201: Optional[St201Result],
                 pmd: Optional[PmdResult], res: SwsaBuildResult) -> None:
    """ST201 Test Summary Report — 템플릿 주도 메트릭 밴드 채우기.

    템플릿 'Test Summary Report' 표를 스캔: D열 메트릭명 → MatrixItem, E열 밴드
    라벨 → 술어. 함수값을 그 밴드로 binning 해 F열(함수 개수)에 기입. H(예외처리)/
    J(수정대상=F-H)/L(결과)은 양식 수식이 자동 계산. 버전(v0.10/v0.11)·밴드 quirk
    무관 (라벨 그대로 파싱). 무소스 메트릭(Recursion/Stress)은 skip + 경고.
    """
    _write_st_test_info(ws, meta, res)
    # 'Test Summary Report' 섹션을 먼저 찾아 그 아래의 '함수 개수' 헤더만 매칭
    # (상단 Result 블록의 '함수 개수' I4 오매칭 방지).
    sec_row = 1
    for rr in range(1, min(ws.max_row, 140) + 1):
        bv = ws.cell(rr, 2).value
        if isinstance(bv, str) and "Test Summary Report" in bv:
            sec_row = rr
            break
    hdr = find_label_row(ws, "함수 개수", max_row=140, min_row=sec_row)
    if hdr is None:
        res.warnings.append(f"{ws.title}: Test Summary '함수 개수' 헤더 미발견 — 표 미기입")
        res.sheets_filled.append(SHEET_ST201)
        return
    hr, fcol = hdr  # F열(count) = 헤더 컬럼

    filled = 0
    skipped: List[str] = []
    partial: List[str] = []

    def _flush(item: Any, name: str, rows: List[tuple]) -> None:
        nonlocal filled
        if not rows:
            return
        labels = [lbl for (_r, lbl) in rows]
        vals: Optional[List[int]] = None
        if item is not None and st201 is not None:
            vals = st201.values_for(item)
        elif "duplicat" in name.lower() and pmd is not None:
            vals = [b.lines for b in pmd.blocks]
        if not vals:
            skipped.append(name.strip().replace("\n", " ")[:28])
            return
        counts = bin_values_into_bands(vals, labels)
        # audit 투명성: 일부 값이 템플릿 밴드 밖이면(예: nesting=0 in '1~10') 기록
        if sum(counts) < len(vals):
            partial.append(f"{name.strip().replace(chr(10), ' ')[:20]}({sum(counts)}/{len(vals)})")
        for (rr, _lbl), cnt in zip(rows, counts):
            if safe_write(ws, rr, fcol, cnt):
                filled += 1

    current_item: Any = None
    current_name = ""
    pending: List[tuple] = []
    r = hr + 1
    while r <= min(ws.max_row, hr + 80):
        bval = ws.cell(r, 2).value
        if isinstance(bval, str) and bval.strip() == "Total":
            break
        dval = ws.cell(r, 4).value
        eval_ = ws.cell(r, 5).value
        if isinstance(dval, str) and dval.strip():
            _flush(current_item, current_name, pending)
            current_item = metric_item_for_name(dval)
            current_name = dval
            pending = []
        if isinstance(eval_, str) and parse_band_predicate(eval_) is not None:
            pending.append((r, eval_))
        r += 1
    _flush(current_item, current_name, pending)

    if skipped:
        res.warnings.append(f"{ws.title}: 무소스 메트릭 skip(수동 입력) {skipped}")
    if partial:
        res.warnings.append(f"{ws.title}: 일부 함수값이 템플릿 밴드 밖 {partial}")
    res.filled_cells += filled
    res.sheets_filled.append(SHEET_ST201)


# ─────────────────────────── ST1101 ───────────────────────────
def _write_st1101(ws: Any, meta: SwsaBuildMeta, qac: Optional[QacXmlResult], res: SwsaBuildResult) -> None:
    _write_st_test_info(ws, meta, res)
    _stamp(ws, "코딩룰 버전", meta.secure_rule_version, max_row=12)
    secure = qac.secure if qac else None
    failed = (qac is None) or qac.extraction_failed or (secure is None)
    h_total = find_label_row(ws, "총 위반 건수", max_row=120) or find_label_row(ws, "총 위반", max_row=12)
    if h_total is not None:
        # 총 위반 헤더 옆/아래 — LAYOUT-B 는 헤더 다음 행에 값
        tgt = find_value_target(ws, "총 위반", max_row=12)
        if tgt:
            if failed or secure is None:
                mark_user_input_required(ws, tgt[0], tgt[1], hint="QAC 추출 실패")
                res.user_input_cells += 1
            else:
                safe_write(ws, tgt[0], tgt[1], secure.active)
                res.filled_cells += 1
    res.sheets_filled.append(SHEET_ST1101)


def build_swsa_report(
    template_bytes: bytes,
    meta: SwsaBuildMeta,
    *,
    qac_xml: Optional[QacXmlResult] = None,
    st201: Optional[St201Result] = None,
    pmd: Optional[PmdResult] = None,
) -> SwsaBuildResult:
    """SwSA 템플릿(.xlsm) → 채워진 xlsm BytesIO.

    Args:
        template_bytes: 회사 SwSA 양식 .xlsm 바이트.
        meta: SwsaBuildMeta.
        qac_xml/st201/pmd: 파싱된 결과 (None 이면 해당 시트 노란 표시).

    Returns:
        SwsaBuildResult (xlsm_io 는 keep_vba 보존 스트림).
    """
    vba = has_vba_macros(template_bytes)
    wb = load_workbook(io.BytesIO(template_bytes), data_only=False, keep_vba=vba)
    res = SwsaBuildResult(xlsm_io=io.BytesIO(), vba_preserved=vba)
    sheets = set(wb.sheetnames)

    if SHEET_COVER in sheets:
        _write_cover(wb[SHEET_COVER], meta, res)
    if SHEET_SUMMARY in sheets:
        _write_summary_header(wb[SHEET_SUMMARY], meta, res)
    if SHEET_ST101 in sheets:
        _write_st101(wb[SHEET_ST101], meta, qac_xml, res)
    if SHEET_ST201 in sheets:
        _write_st201(wb[SHEET_ST201], meta, st201, pmd, res)
    if SHEET_ST1101 in sheets:
        _write_st1101(wb[SHEET_ST1101], meta, qac_xml, res)

    # 존재하지 않는 AUTO 시트 안내 (graceful)
    for sn in (SHEET_ST1101,):
        if sn not in sheets:
            res.warnings.append(f"{sn} 시트 없음 (템플릿 버전에 미포함) — graceful skip")

    wb.save(res.xlsm_io)
    res.xlsm_io.seek(0)
    return res
