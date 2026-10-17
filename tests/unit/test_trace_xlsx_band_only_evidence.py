"""감사 산출물(xlsx)이 화면과 모순되지 않는가 — '추적 0건' 판정의 기준.

xlsx 교차표는 10밴드 합이 0이면 '추적 0건'(분홍)으로 찍는다. 그런데 SDS 밴드는 추적
정화 이후 **실 컴포넌트(SwCom)만** 센다. 설계ID(`SwFn_`/`SwST_`)·상태명·인터페이스
함수로만 연결된 요구는 전 밴드가 비어 total=0 이 되는데, 화면은 같은 행을
`has_design`(components OR functions OR design_elements)으로 **covered** 라 부른다.

저장소 동봉 HDPDM01 실측: 정화 전 '추적 0건' 0건 → 정화 후 **14건**, 그 14건이 전부
화면에서는 '설계 있음'. ISO 26262 감사에서 두 문서가 어긋나는 상태였다.

⚠ 그렇다고 밴드에 설계요소를 되넣으면 정화가 무효가 된다. 밴드는 그대로 두고
**'추적 0건' 판정**만 밴드 밖 근거를 함께 보게 하고, 비어 보이는 행엔 사유를 남긴다.
"""
from __future__ import annotations

import io

import pytest

from report_gen.trace_matrix_xlsx import build_trace_xlsx

openpyxl = pytest.importorskip("openpyxl")


def _row(rid, **over):
    base = {
        "requirement_id": rid, "requirement_name": f"요구 {rid}", "asil": "A",
        "sds_components": [], "sds_functions": [], "sds_design_elements": [],
        "hsis_signals": [], "source_ids": [], "syrs_parents": [],
        "sts_tests": [], "suts_tests": [], "sits_tests": [],
        "syts_tests": [], "syits_tests": [], "tests": [],
    }
    base.update(over)
    return base


def _sheet(rows):
    data = build_trace_xlsx({"rows": rows}, meta={"project_name": "T"})
    wb = openpyxl.load_workbook(io.BytesIO(data))
    return wb["교차표"]


def _summary_text(ws):
    for row in ws.iter_rows(min_row=1, max_row=14, max_col=2):
        if row[0].value == "요구사항 수":
            return str(row[1].value or "")
    return ""


def _note_text(ws):
    for row in ws.iter_rows(min_row=1, max_row=14, max_col=2):
        if row[0].value == "밴드 외 설계근거":
            return str(row[1].value or "")
    return ""


def test_design_element_only_row_is_not_called_untraced():
    """핵심 — 설계요소로만 연결된 요구를 '추적 0건'으로 세면 화면과 모순된다."""
    ws = _sheet([_row("SwTR_01", sds_design_elements=["swst_09"])])
    assert "추적 0건 0건" in _summary_text(ws)
    assert "밴드 외 설계근거만 1건" in _summary_text(ws)


def test_function_only_row_is_not_called_untraced():
    """인터페이스 함수로만 연결된 경우도 같다(SDS 밴드는 컴포넌트만 센다)."""
    ws = _sheet([_row("SwTR_02", sds_functions=["g_do_work"])])
    assert "추적 0건 0건" in _summary_text(ws)


def test_true_orphan_is_still_untraced():
    """밴드도 밴드 밖 근거도 없으면 그대로 '추적 0건' — 완화가 아니라 정정이다."""
    ws = _sheet([_row("SwTR_03")])
    assert "추적 0건 1건" in _summary_text(ws)
    assert "밴드 외 설계근거만" not in _summary_text(ws)


def test_band_row_unaffected():
    """밴드가 채워진 행은 이 변경과 무관."""
    ws = _sheet([_row("SwTR_04", sds_components=["SwCom_01"])])
    assert "추적 0건 0건" in _summary_text(ws)
    assert "밴드 외 설계근거만" not in _summary_text(ws)


def test_reason_is_written_into_the_document():
    """밴드 칸이 전부 빈 행이 왜 통과인지 **문서 안에** 있어야 한다.

    없으면 감사자가 화면과 대조해야만 알 수 있다 — 산출물 자립성이 깨진다.
    """
    ws = _sheet([_row("SwTR_05", sds_design_elements=["swfn_10"])])
    note = _note_text(ws)
    assert note, "사유 줄이 없다"
    assert "SwCom" in note and "설계" in note


def test_no_reason_line_when_not_applicable():
    """해당 행이 없으면 사유 줄도 없다(빈 설명으로 지면 낭비/오독 유발 금지)."""
    ws = _sheet([_row("SwTR_06", sds_components=["SwCom_01"])])
    assert _note_text(ws) == ""


def test_band_only_row_is_flagged_not_silently_blank():
    """밴드 칸이 전부 비어 보이므로 amber 로 '검토 필요'를 남긴다 — 무표시 금지."""
    ws = _sheet([_row("SwTR_07", sds_design_elements=["swst_01"])])
    # 헤더 다음 첫 데이터 행을 찾아 채움색이 있는지 본다.
    head = next(r for r in range(1, 16)
                if str(ws.cell(r, 1).value or "") == "요구사항")
    fill = ws.cell(head + 1, 1).fill
    assert fill is not None and str(fill.fgColor.rgb or "").upper() not in ("00000000", ""), \
        "밴드가 빈 행이 아무 표시 없이 정상처럼 보인다"


def test_stale_row_without_new_field_still_works():
    """구 캐시 행엔 sds_design_elements 키가 아예 없다 — 크래시 없이 기존 판정."""
    stale = _row("SwTR_08")
    del stale["sds_design_elements"]
    ws = _sheet([stale])
    assert "추적 0건 1건" in _summary_text(ws)
