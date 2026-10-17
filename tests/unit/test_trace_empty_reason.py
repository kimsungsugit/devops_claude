# -*- coding: utf-8 -*-
"""STS/SUTS '시트는 찾았는데 0행' — 사유를 갈래별로 말하는가.

인계 문서 P1. `_finalize_trace_result` 가 이 경우를 **`ok:true` + 무사유**로 반환했다.
프론트(`SrsSdsSection`)는 `warning` 도 `available_sheets` 도 없으면 두 분기가 **모두
미발화**하므로, 추적성 밴드가 이유 없이 빈 채로 끝났다(완전 침묵).

SITS 는 같은 결함을 이미 고쳐 두고 주석에 "Strategy2의 '시트 없음' 경로만 warning 을
실었음 — **비대칭 해소**" 라고 적어 놨다(:5157). STS/SUTS 만 남아 있었다.

고정하는 계약:
  A. 0행이면 **반드시** `warning` 이 있다 (침묵 금지)
  B. 사유가 갈래마다 **다르다** — 뭉뚱그리면 사용자가 엉뚱한 곳(문서 경로)을 의심한다
     (커밋 b2d2968 "SRS 경로를 확인하세요가 실은 다섯 갈래였다" 와 같은 교정)
  C. 행이 **있으면** 사유를 붙이지 않는다 (정상에 경고를 흘리지 않음)
  D. 추출 행 수·내용은 **불변** — 이번 변경은 카운터만 더한다
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.routers.jenkins import _finalize_trace_result, _trace_empty_reason


def _diag(**over: Any) -> Dict[str, Any]:
    base = {
        "sheet": "Traceability", "sheets": ["Cover", "Traceability"], "layout": "header",
        "req_cols": 0, "tc_seen": 0, "req_cells_seen": 0, "id_hits": 0,
        "header_row": None, "truncated_at": None,
    }
    base.update(over)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# A·B — 0행이면 사유가 있고, 갈래마다 다르다
# ─────────────────────────────────────────────────────────────────────────────

def test_0행이면_반드시_warning이_붙는다():
    r = _finalize_trace_result([], None, expected="sts", other="suts", diag=_diag())
    assert r["ok"] is True                      # 추출 자체는 성공 — 계약 유지
    assert r.get("warning"), "0행인데 사유가 없다 — 프론트에서 완전 침묵된다"
    assert "STS" in r["warning"]


def test_diag_없이_불려도_침묵하지_않는다():
    """구 호출자/부분 이관 상태에서도 사유는 남아야 한다."""
    r = _finalize_trace_result([], None, expected="suts", other="sts")
    assert r.get("warning")
    assert "SUTS" in r["warning"]


@pytest.mark.parametrize(("diag", "must_contain", "must_not_contain"), [
    # matrix — 요구 헤더를 못 찾음
    (_diag(layout="matrix", req_cols=0, tc_seen=0), "4행", "고정 컬럼"),
    # matrix — 헤더는 찾았는데 TC 없음
    (_diag(layout="matrix", req_cols=7, tc_seen=0), "3열", "4행"),
    # matrix — 둘 다 있는데 교차 표시가 없음
    (_diag(layout="matrix", req_cols=7, tc_seen=42), "교차", "3열"),
    # header — TC 열이 빔
    (_diag(layout="header", header_row=3, req_cols=2, tc_seen=0), "TC 열", "고정 컬럼"),
    # header — TC 는 있는데 요구 열이 전부 빔
    (_diag(layout="header", header_row=3, req_cols=2, tc_seen=10, req_cells_seen=0), "요구 열", "패턴"),
    # header — 값은 있는데 ID 패턴 불일치
    (_diag(layout="header", header_row=3, req_cols=2, tc_seen=10, req_cells_seen=88, id_hits=0),
     "표기 규약", "비어 있습니다"),
    # fixed_fallback — 템플릿 불일치(SUTS 2템플릿 사건과 같은 계열)
    (_diag(layout="fixed_fallback", tc_seen=0, req_cells_seen=0), "고정 컬럼", "4행"),
])
def test_사유가_갈래마다_다르다(diag, must_contain, must_not_contain):
    msg = _trace_empty_reason(diag, "STS")
    assert must_contain in msg, f"{must_contain!r} 가 사유에 없다: {msg}"
    assert must_not_contain not in msg, f"다른 갈래의 문구가 샜다({must_not_contain!r}): {msg}"


def test_모든_갈래의_사유가_서로_다른_문장이다():
    """한 문장으로 뭉개지면 '다섯 갈래'가 다시 하나가 된다."""
    variants = [
        _diag(layout="matrix", req_cols=0),
        _diag(layout="matrix", req_cols=7, tc_seen=0),
        _diag(layout="matrix", req_cols=7, tc_seen=42),
        _diag(layout="header", header_row=3, tc_seen=0),
        _diag(layout="header", header_row=3, tc_seen=10, req_cells_seen=0),
        _diag(layout="header", header_row=3, tc_seen=10, req_cells_seen=88),
        _diag(layout="fixed_fallback"),
    ]
    msgs = [_trace_empty_reason(d, "SUTS") for d in variants]
    assert len(set(msgs)) == len(msgs), f"사유가 겹친다: {msgs}"


def test_사유에_시트명과_시트목록이_들어간다():
    """'어느 시트를 봤는지'가 없으면 사용자가 대조할 수 없다."""
    msg = _trace_empty_reason(_diag(sheet="TC List", sheets=["Cover", "TC List", "Log"]), "STS")
    assert "TC List" in msg
    assert "Cover" in msg and "Log" in msg


def test_조기_종료는_침묵하지_않는다():
    """빈 행 50연속 break 는 아래쪽 데이터를 버렸을 수 있다 — 절단을 숨기지 않는다."""
    msg = _trace_empty_reason(_diag(truncated_at=812), "STS")
    assert "812" in msg and "조기 종료" in msg


# ─────────────────────────────────────────────────────────────────────────────
# C — 정상 결과에는 사유를 붙이지 않는다
# ─────────────────────────────────────────────────────────────────────────────

def test_행이_있으면_0행_사유를_붙이지_않는다():
    rows = [{"requirement_id": "SwTR_0101", "testcase": "TC1", "source": "STS", "result": "mapped"}]
    r = _finalize_trace_result(rows, None, expected="sts", other="suts", diag=_diag())
    assert "0건 추출" not in str(r.get("warning") or "")
    assert "empty_diagnostics" not in r
    assert r["total_mappings"] == 1


def test_시트_자체가_없으면_기존_error_경로_그대로():
    r = _finalize_trace_result([], ["A", "B"], expected="sts", other="suts", diag=_diag())
    assert r["ok"] is False
    assert r["available_sheets"] == ["A", "B"]
    assert "찾을 수 없습니다" in r["error"]


# ─────────────────────────────────────────────────────────────────────────────
# D — **추출부까지 태운다**. 위 테스트들은 diag 를 손으로 만들어 메시지 생성기만 본다.
#     그것만으론 diag 를 *채우는* 코드가 죽어도 통과한다(뮤테이션 M3/M4 생존으로 실증).
# ─────────────────────────────────────────────────────────────────────────────

def _wb(sheet: str, rows: list):
    """openpyxl in-memory 워크북 — `_GridSheet` 가 요구하는 iter_rows(values_only) 를 만족."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(list(r))
    return wb


def _extract(wb, label="STS", **kw):
    from backend.routers.jenkins import _extract_test_spec_traceability

    return _extract_test_spec_traceability(wb, source_label=label, sheet_name_arg="", **kw)


def test_추출부가_고정컬럼_폴백을_실제로_표시한다():
    """헤더('Test Case ID')가 없으면 고정 컬럼(5/6) 폴백이다 — 템플릿 불일치의 주된 원인.

    (SUTS 2템플릿 사건: 컬럼 하드코딩으로 704/1013행이 침묵 드롭됐다.)
    """
    wb = _wb("Traceability", [
        ["제목", "", "", "", "", ""],
        ["설명", "", "", "", "", ""],
        ["Idx", "이름", "비고", "함수", "", ""],   # TC/요구가 5·6열에 없다
        ["1", "a", "b", "Foo", "", ""],
    ])
    rows, avail, diag = _extract(wb)
    assert avail is None and rows == []
    assert diag["layout"] == "fixed_fallback", "고정컬럼 폴백을 표시하지 않는다"
    msg = _finalize_trace_result(rows, avail, expected="sts", other="suts", diag=diag)["warning"]
    assert "고정 컬럼" in msg


def test_추출부가_조기_종료_행번호를_기록한다():
    """빈 행 50연속 break — 아래에 데이터가 더 있었을 수 있어 절단을 숨기면 안 된다."""
    rows_in = [["Test Case ID", "Related ID"], ["", ""]]
    rows_in += [["", ""] for _ in range(80)]      # 50연속을 넘긴다
    wb = _wb("Traceability", rows_in)
    rows, avail, diag = _extract(wb)
    assert rows == []
    assert diag["truncated_at"], "조기 종료를 기록하지 않는다 — 절단이 침묵된다"
    msg = _finalize_trace_result(rows, avail, expected="sts", other="suts", diag=diag)["warning"]
    assert "조기 종료" in msg


def test_추출부가_헤더_레이아웃과_카운터를_채운다():
    """요구 열에 값은 있는데 ID 패턴이 아닌 경우 — '표기 규약' 갈래로 가야 한다."""
    wb = _wb("Traceability", [
        ["Test Case ID", "Related ID"],
        ["TC-1", "그냥 설명 텍스트"],
        ["TC-2", "또 다른 텍스트"],
    ])
    rows, avail, diag = _extract(wb)
    assert rows == []
    assert diag["layout"] == "header" and diag["header_row"] == 1
    assert diag["tc_seen"] == 2 and diag["req_cells_seen"] == 2 and diag["id_hits"] == 0
    msg = _finalize_trace_result(rows, avail, expected="sts", other="suts", diag=diag)["warning"]
    assert "표기 규약" in msg


def test_추출이_정상이면_행이_나오고_사유가_없다():
    """음성 대조군 — 위 테스트들이 '항상 0행'이라서 통과하는 게 아님을 보인다."""
    wb = _wb("Traceability", [
        ["Test Case ID", "Related ID"],
        ["TC-1", "SwTR_0101"],
        ["TC-2", "SwTR_0102, SwTR_0103"],
    ])
    rows, avail, diag = _extract(wb)
    assert len(rows) == 3, f"정상 문서에서 3행이 나와야 한다: {rows}"
    assert diag["id_hits"] == 3
    r = _finalize_trace_result(rows, avail, expected="sts", other="suts", diag=diag)
    assert "0건 추출" not in str(r.get("warning") or "")


def test_시트를_아예_못_찾으면_available_sheets_경로():
    wb = _wb("Cover", [["아무것도 아님"]])
    rows, avail, diag = _extract(wb)
    assert rows == [] and avail == ["Cover"]
    assert _finalize_trace_result(rows, avail, expected="sts", other="suts", diag=diag)["ok"] is False


def test_오태깅_경고는_행이_있을_때만_판정된다():
    """0행 사유와 H3 오태깅 경고가 서로를 덮어쓰지 않는지."""
    # SUTS 구조(SwUFn)인데 sts 로 선언 → 오태깅 경고
    rows = [{"requirement_id": f"SwUFn_{i:04d}", "testcase": f"TC{i}",
             "source": "STS", "result": "mapped"} for i in range(1, 40)]
    r = _finalize_trace_result(rows, None, expected="sts", other="suts", diag=_diag())
    assert r["total_mappings"] == 39
    # 오태깅이든 아니든, 0행 사유가 잘못 섞이면 안 된다.
    assert "0건 추출" not in str(r.get("warning") or "")
