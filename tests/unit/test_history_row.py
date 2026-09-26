"""개정 이력 한 행 덧붙이기 — **문서 끝 표시를 이력으로 오인하지 않는지**가 본체다.

정본을 템플릿으로 쓰면 과거 이력이 딸려온다. 지우지 않고 다음 행에 이번 개정을
덧붙인다(사용자 결정, 2026-08-12).

⚠ 작성 중 실제로 겪은 결함: "값이 있는 마지막 행" 으로 마지막 이력을 찾았더니 정본
  History 78행의 `<End of Document>` 를 집어 버전 파싱에 실패했고, 그 결과 이력이
  **한 줄도 안 붙었다**(조용히 `None` 반환). 버전 모양인 행만 세도록 고쳤다.
"""
from __future__ import annotations

import pytest

from generators.history_row import _bump, append_history_row, find_history_columns


def _wb_with_history(rows, headers=("Version", "Date", "변경위치", "Description")):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "History"
    ws.cell(row=2, column=2, value="■ Revision History")
    for c, h in enumerate(headers, 2):
        ws.cell(row=4, column=c, value=h)
    for i, (ver, dt, desc) in enumerate(rows, 5):
        ws.cell(row=i, column=2, value=ver)
        ws.cell(row=i, column=3, value=dt)
        ws.cell(row=i, column=5, value=desc)
    return wb, ws


def test_appends_next_version_after_last_history_row():
    wb, ws = _wb_with_history([("v0.10", "25.09.16", "초안"), ("v1.02", "26.06.01", "작성")])
    got = append_history_row(wb, today="26.08.12")
    assert got == "v1.03"
    assert ws.cell(row=7, column=2).value == "v1.03"
    assert ws.cell(row=7, column=3).value == "26.08.12"
    assert ws.cell(row=7, column=5).value  # 설명은 비우지 않는다


def test_end_of_document_marker_is_not_treated_as_history():
    """⚠ 실제로 이것 때문에 이력이 한 줄도 안 붙었다(정본 78행 `<End of Document>`)."""
    wb, ws = _wb_with_history([("v1.02", "26.06.01", "작성")])
    ws.cell(row=20, column=2, value="<End of Document>")
    got = append_history_row(wb, today="26.08.12")
    assert got == "v1.03", "문서 끝 표시를 마지막 이력으로 오인하면 버전 파싱이 실패한다"
    assert ws.cell(row=6, column=2).value == "v1.03"   # 마지막 **이력** 행 바로 다음
    assert ws.cell(row=20, column=2).value == "<End of Document>"   # 끝 표시는 건드리지 않는다


def test_same_version_is_not_appended_twice():
    """재생성마다 같은 행이 쌓이면 이력이 아니라 로그가 된다."""
    wb, ws = _wb_with_history([("v1.03", "26.08.12", "자동 생성")])
    assert append_history_row(wb, version="v1.03") is None
    assert ws.cell(row=6, column=2).value is None


def test_explicit_version_wins_over_bump():
    wb, ws = _wb_with_history([("v1.02", "26.06.01", "작성")])
    assert append_history_row(wb, version="v2.00", today="26.08.12") == "v2.00"
    assert ws.cell(row=6, column=2).value == "v2.00"


def test_missing_history_sheet_is_a_no_op():
    """History 시트가 없으면 **만들지 않는다** — 흉내 낸 서식은 납품본과 다르다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Cover"
    assert append_history_row(wb, version="v1.00") is None
    assert wb.sheetnames == ["Cover"]


def test_unparseable_version_is_not_invented():
    """형식을 못 읽으면 지어내지 않는다 — 원본을 그대로 돌려준다."""
    assert _bump("v1.02") == "v1.03"
    assert _bump("1.09") == "1.10"
    assert _bump("v0.10") == "v0.11"
    assert _bump("rev-A") == "rev-A"
    assert _bump("") == ""


def test_header_is_found_by_label_not_by_row_number():
    """문서마다 열 구성이 다르다 — 번호를 박으면 엉뚱한 칸에 쓴다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "History"
    # 헤더가 6행에 있고 Description 이 앞쪽에 오는 변형
    for c, h in enumerate(("Description", "Version", "Date", "Author"), 3):
        ws.cell(row=6, column=c, value=h)
    cols = find_history_columns(ws)
    assert cols["header_row"] == 6
    assert cols["version"] == 4 and cols["date"] == 5 and cols["description"] == 3
