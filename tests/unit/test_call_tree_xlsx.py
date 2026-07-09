"""backend.services.call_tree_xlsx.build_call_tree_xlsx 단위 테스트.

검증: 유효한 xlsx 바이트 생성, depth 컬럼 들여쓰기 + depth별 색상(회사 SwITS 2.SW
Integration Strategy 재현), 루트 강조, 외부/ASIL/마커 열, 양방향 2시트, 역방향 제목,
빈 트리 안내, 수식 주입 가드, DoS 캡 truncation.
"""

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from backend.services import call_tree_xlsx as ctx  # noqa: E402
from backend.services.call_tree_xlsx import build_call_tree_xlsx  # noqa: E402
from backend.services.design_tokens import (  # noqa: E402
    CALL_TREE_DEPTH_FILLS,
    CALL_TREE_ROOT_FILL_RGB,
)


def _uni():
    return {
        "trees": [
            {
                "name": "s_Root", "file": "root.c", "asil": "D",
                "calls": [
                    {
                        "name": "child_d1", "file": "a.c", "asil": "C",
                        "calls": [
                            {
                                "name": "child_d2",
                                "calls": [{"name": "leaf_d3", "cycle": True, "calls": []}],
                                "externals": [{"name": "memcpy", "header": "string.h", "library": "string"}],
                            },
                        ],
                    },
                    {"name": "marked", "via_ref": True, "indirect": ["fp"], "truncated": True, "calls": []},
                ],
            },
            {"name": "main", "file": "boot.c", "calls": [{"name": "App_Init", "asil": "A", "calls": []}]},
        ],
        "stats": {"engine": "tree-sitter", "functions": 7, "edges": 6, "reverse": False, "roots": 2},
        "meta": {"job_url": "http://j/job/X", "build_selector": "last"},
    }


def _open(data):
    return openpyxl.load_workbook(io.BytesIO(data))


def _fill(cell):
    try:
        rgb = cell.fill.fgColor.rgb
        return str(rgb) if rgb and str(rgb) != "00000000" else None
    except Exception:
        return None


def _find(ws, value, col=None, rmax=40):
    """value를 담은 첫 셀 좌표 (row, col) 반환 — 없으면 None."""
    for r in range(1, min(ws.max_row, rmax) + 1):
        for c in range(1, ws.max_column + 1):
            if col is not None and c != col:
                continue
            if ws.cell(r, c).value == value:
                return r, c
    return None


def test_produces_valid_xlsx_single_sheet():
    data = build_call_tree_xlsx(_uni(), {"generated_at": "2026-07-08T00:00:00"})
    assert isinstance(data, bytes) and len(data) > 0
    wb = _open(data)
    assert wb.sheetnames == ["SW Integration Strategy"]
    ws = wb.active
    assert ws.cell(1, 1).value == "Software Integration Strategy"
    assert "호출(callee)" in (ws.cell(2, 1).value or "")


def test_header_row_has_depth_and_info_columns():
    ws = _open(build_call_tree_xlsx(_uni()))["SW Integration Strategy"]
    labels = [ws.cell(5, c).value for c in range(1, ws.max_column + 1)]
    assert labels[0] == "No"
    assert labels[1] == "진입 함수"
    assert "1 depth" in labels and "2 depth" in labels and "3 depth" in labels
    assert "정의 파일" in labels and "ASIL" in labels and "유형/비고" in labels


def test_depth_indentation_and_colors():
    """각 노드가 (C + depth) 컬럼에, depth별 색으로 렌더되는지 — 참조 시트 재현 핵심."""
    ws = _open(build_call_tree_xlsx(_uni()))["SW Integration Strategy"]
    # 루트(depth0) → C열(3)
    root = _find(ws, "s_Root", col=3)
    assert root is not None, "루트가 C열(depth0)에 없음"
    assert _fill(ws.cell(root[0], 3)) == CALL_TREE_DEPTH_FILLS[0]
    # child_d1(depth1) → D열(4)
    d1 = _find(ws, "child_d1", col=4)
    assert d1 is not None and _fill(ws.cell(d1[0], 4)) == CALL_TREE_DEPTH_FILLS[1]
    # child_d2(depth2) → E열(5)
    d2 = _find(ws, "child_d2", col=5)
    assert d2 is not None and _fill(ws.cell(d2[0], 5)) == CALL_TREE_DEPTH_FILLS[2]
    # leaf_d3(depth3) → F열(6)
    d3 = _find(ws, "leaf_d3", col=6)
    assert d3 is not None and _fill(ws.cell(d3[0], 6)) == CALL_TREE_DEPTH_FILLS[3]


def test_root_highlight_in_col_b():
    ws = _open(build_call_tree_xlsx(_uni()))["SW Integration Strategy"]
    b = _find(ws, "s_Root", col=2)
    assert b is not None, "루트가 B열(강조)에 없음"
    assert _fill(ws.cell(b[0], 2)) == CALL_TREE_ROOT_FILL_RGB
    # 블록 번호 A열
    assert ws.cell(b[0], 1).value == 1


def test_external_and_marker_notes():
    ws = _open(build_call_tree_xlsx(_uni()))["SW Integration Strategy"]
    notes = [str(ws.cell(r, ws.max_column).value or "") for r in range(6, ws.max_row + 1)]
    joined = " ".join(notes)
    assert "외부 · string.h/string" in joined
    assert "↻ 순환" in joined
    assert "↪ 참조" in joined and "⚡ 간접호출 1" in joined and "깊이제한" in joined
    assert "진입점" in joined


def test_asil_cells_present():
    ws = _open(build_call_tree_xlsx(_uni()))["SW Integration Strategy"]
    # ASIL 열에 D/C/A 등급이 찍혔는지 (색은 design_tokens ASIL fill)
    asil_vals = {ws.cell(r, c).value for r in range(6, ws.max_row + 1)
                 for c in range(1, ws.max_column + 1)}
    assert "D" in asil_vals and "C" in asil_vals and "A" in asil_vals


def test_external_only_when_present():
    """externals 없는 노드는 외부 행을 만들지 않음."""
    p = {"trees": [{"name": "f", "calls": [{"name": "g", "calls": []}]}], "stats": {}}
    ws = _open(build_call_tree_xlsx(p))["SW Integration Strategy"]
    notes = " ".join(str(ws.cell(r, ws.max_column).value or "") for r in range(6, ws.max_row + 1))
    assert "외부" not in notes


def test_bidirectional_two_sheets():
    bidir = {
        "bidir": True,
        "callees": {"trees": [{"name": "c", "calls": [{"name": "cc", "calls": []}]}],
                    "stats": {"engine": "tree-sitter", "reverse": False}},
        "callers": {"trees": [{"name": "c", "calls": [{"name": "pp", "calls": []}]}],
                    "stats": {"engine": "tree-sitter", "reverse": True}},
        "stats": {"engine": "tree-sitter"},
    }
    wb = _open(build_call_tree_xlsx(bidir))
    assert wb.sheetnames == ["호출 트리 (callee)", "역호출 트리 (caller)"]


def test_reverse_single_sheet_title():
    p = {"trees": [{"name": "x", "calls": []}], "stats": {"reverse": True}}
    wb = _open(build_call_tree_xlsx(p))
    assert wb.sheetnames == ["역호출 트리 (caller)"]
    assert "caller" in (wb.active.cell(1, 1).value or "")


def test_empty_trees_guide_row():
    ws = _open(build_call_tree_xlsx({"trees": [], "stats": {}}))["SW Integration Strategy"]
    guide = any("트리가 없습니다" in str(ws.cell(r, 1).value or "") for r in range(1, ws.max_row + 1))
    assert guide


def test_formula_injection_guard():
    ws = _open(build_call_tree_xlsx({"trees": [{"name": "=cmd()", "calls": []}], "stats": {}}))["SW Integration Strategy"]
    vals = [ws.cell(r, c).value for r in range(6, ws.max_row + 1) for c in range(2, 6)]
    cmd = [v for v in vals if v and "cmd" in str(v)]
    assert cmd and all(str(v).startswith("'") for v in cmd), "수식 프리픽스 미적용"


def test_cap_truncation(monkeypatch):
    monkeypatch.setattr(ctx, "_MAX_NODES", 3)
    p = {"trees": [{"name": "r", "calls": [
        {"name": "a", "calls": [{"name": "b", "calls": [{"name": "c", "calls": []}]}]},
    ]}], "stats": {}}
    ws = _open(build_call_tree_xlsx(p))["SW Integration Strategy"]
    trunc = any("상한" in str(ws.cell(r, 1).value or "") for r in range(1, ws.max_row + 1))
    assert trunc, "캡 초과 안내 행 없음"


def test_non_dict_payload_graceful():
    data = build_call_tree_xlsx(None, None)
    assert isinstance(data, bytes) and len(data) > 0
    # 빈 payload → trees 없음 → 안내 행
    ws = _open(data).active
    assert any("트리가 없습니다" in str(ws.cell(r, 1).value or "") for r in range(1, ws.max_row + 1))


def test_missing_name_node_graceful():
    p = {"trees": [{"calls": [{"name": "child", "calls": []}]}], "stats": {}}
    data = build_call_tree_xlsx(p)
    assert isinstance(data, bytes) and len(data) > 0


def test_deep_recursion_guard():
    """선형 체인 1500 깊이 — _MAX_DEPTH clamp로 RecursionError 없이 생성(W1)."""
    node = {"name": "leaf", "calls": []}
    for i in range(1500):
        node = {"name": f"f{i}", "calls": [node]}
    data = build_call_tree_xlsx({"trees": [node], "stats": {}}, {})
    assert isinstance(data, bytes) and len(data) > 0


def test_source_incomplete_provenance_warning():
    """meta.source_complete=False → 메타 라인에 부분 집계 경고(W3 감사 provenance)."""
    ws = _open(build_call_tree_xlsx(
        {"trees": [{"name": "f", "calls": []}], "stats": {"engine": "x"}},
        {"source_complete": False},
    ))["SW Integration Strategy"]
    assert "부분 집계" in (ws.cell(2, 1).value or "")


def _has_row(ws, *needles):
    return any(all(n in str(ws.cell(r, 1).value or "") for n in needles)
              for r in range(1, ws.max_row + 1))


def test_depth_cap_surfaces_warning(monkeypatch):
    """깊이 상한 발동 시 silent 누락이 아니라 경고행으로 표면화(W-1)."""
    monkeypatch.setattr(ctx, "_MAX_DEPTH", 3)
    node = {"name": "leaf", "calls": []}
    for i in range(6):
        node = {"name": f"f{i}", "calls": [node]}
    ws = _open(build_call_tree_xlsx({"trees": [node], "stats": {}}, {}))["SW Integration Strategy"]
    assert _has_row(ws, "깊이", "상한"), "깊이 상한 경고행 없음"


def test_tree_cap_surfaces_warning(monkeypatch):
    """루트(진입 함수) 상한 초과 시 경고행 표면화(W-1)."""
    monkeypatch.setattr(ctx, "_MAX_TREES", 2)
    trees = [{"name": f"r{i}", "calls": []} for i in range(5)]
    ws = _open(build_call_tree_xlsx({"trees": trees, "stats": {}}, {}))["SW Integration Strategy"]
    assert _has_row(ws, "진입 함수", "상한"), "루트 상한 경고행 없음"


def test_bidir_caller_sheet_reverse_label():
    """양방향 caller 시트는 callers.stats 부재에도 '역호출' 라벨(W-2 명시 reverse 인자)."""
    bidir = {
        "bidir": True,
        "callees": {"trees": [{"name": "c", "calls": []}]},   # stats 없음 → 폴백
        "callers": {"trees": [{"name": "c", "calls": []}]},   # stats 없음 → 폴백
        "stats": {"reverse": False},                          # 폴백 stats는 reverse=False
    }
    wb = _open(build_call_tree_xlsx(bidir))
    assert "역호출(caller)" in (wb["역호출 트리 (caller)"].cell(2, 1).value or "")
    assert "호출(callee)" in (wb["호출 트리 (callee)"].cell(2, 1).value or "")


def test_parse_swit_strategy_map():
    """SwITS '2.SW Integration Strategy' 시트 → {진입함수: SwIT_ID} 추출."""
    from backend.services.call_tree_xlsx import parse_swit_strategy_map
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2.SW Integration Strategy"
    ws.cell(7, 2, "SwIT_SwUFn_0504_01")   # B7 = ID
    ws.cell(7, 3, "s_Ap_Execute")          # C7 = 진입 함수(첫 non-empty)
    ws.cell(10, 2, "SwIT_SwUFn_3563")      # B10 = ID
    ws.cell(10, 4, "main")                 # D10 = 진입 함수(C 비어도 첫 non-empty)
    ws.cell(12, 2, "일반행")               # SwIT 아님 → 무시
    ws.cell(12, 3, "noise")
    buf = io.BytesIO()
    wb.save(buf)
    m = parse_swit_strategy_map(buf.getvalue())
    assert m["s_Ap_Execute"] == "SwIT_SwUFn_0504_01"
    assert m["main"] == "SwIT_SwUFn_3563"
    assert "noise" not in m


def test_swit_map_relabels_root_only():
    """swit_map: 루트 B열만 SwIT_ID로 치환, depth 트리 컬럼은 함수명 유지."""
    swit = {"main": "SwIT_SwUFn_3563", "child": "SwIT_SwUFn_9999"}
    ws = _open(build_call_tree_xlsx(
        {"trees": [{"name": "main", "calls": [{"name": "child", "calls": []}]}], "stats": {}},
        {}, swit_map=swit,
    ))["SW Integration Strategy"]
    assert _find(ws, "SwIT_SwUFn_3563", col=2) is not None, "루트 B열 SwIT_ID 치환 안 됨"
    assert _find(ws, "main", col=3) is not None, "트리 C열 함수명 유지 안 됨"
    # 자식은 루트가 아니므로 B열 아님 — swit_map 매칭돼도 트리 컬럼(D)에 함수명
    assert _find(ws, "child", col=4) is not None
    assert _find(ws, "SwIT_SwUFn_9999", col=2) is None, "비루트가 B열에 잘못 치환됨"


def test_no_swit_map_keeps_function_name():
    """swit_map 미지정 → 함수명 유지(현재 방식)."""
    ws = _open(build_call_tree_xlsx(
        {"trees": [{"name": "main", "calls": []}], "stats": {}}, {},
    ))["SW Integration Strategy"]
    assert _find(ws, "main", col=2) is not None


def test_count_swit_matched_roots():
    """매칭 루트 수 계산(W1 표면화용) — 단방향/양방향/빈."""
    from backend.services.call_tree_xlsx import count_swit_matched_roots
    uni = {"trees": [{"name": "main", "calls": []}, {"name": "other", "calls": []}]}
    assert count_swit_matched_roots(uni, {"main": "SwIT_1"}) == (1, 2)
    bidir = {"bidir": True, "callees": {"trees": [{"name": "a", "calls": []}]},
             "callers": {"trees": [{"name": "b", "calls": []}]}}
    assert count_swit_matched_roots(bidir, {"a": "SwIT_A"}) == (1, 2)
    assert count_swit_matched_roots(None, {"a": "1"}) == (0, 0)
    assert count_swit_matched_roots({"trees": [{"name": "x"}]}, None) == (0, 0)


def test_parse_skips_nonident_entry_cell():
    """C열 순번/설명(비식별자)은 건너뛰고 함수명 셀을 진입 함수로 채택(W2)."""
    from backend.services.call_tree_xlsx import parse_swit_strategy_map
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2.SW Integration Strategy"
    ws.cell(7, 2, "SwIT_SwUFn_9")   # B7 = ID
    ws.cell(7, 3, "1)")             # C7 = 순번(비식별자) → skip
    ws.cell(7, 4, "s_Real_Func")    # D7 = 함수명 → 채택
    buf = io.BytesIO()
    wb.save(buf)
    m = parse_swit_strategy_map(buf.getvalue())
    assert m.get("s_Real_Func") == "SwIT_SwUFn_9"
    assert "1)" not in m


def test_missing_swit_rendered_at_bottom():
    """regen 모드: 참조 SITS엔 있으나 소스에 정의 없는 SwIT를 시트 하단에 명시(정직성 표면화).

    43개 매핑 중 35개만 트리로 나오고 8개가 무표기로 사라지던 갭을 방지 — SwIT_ID는 B열,
    진입 함수명은 C열에 하단 별도 블록으로 렌더된다.
    """
    missing = [("SCI0_ISR", "SwIT_SwUFn_3546"), ("TIM0_Ch0_ISR", "SwIT_SwUFn_3514")]
    ws = _open(build_call_tree_xlsx(
        _uni(), {"generated_at": "2026-07-09"},
        swit_map={"s_Root": "SwIT_SwUFn_0001"}, missing_swit=missing,
    ))["SW Integration Strategy"]
    assert any(
        isinstance(ws.cell(r, 1).value, str) and "미생성 SwIT 2개" in ws.cell(r, 1).value
        for r in range(1, ws.max_row + 1)
    ), "미생성 SwIT 헤더 미표기"
    # 각 미생성 SwIT_ID는 B열, 진입 함수명은 C열
    assert _find(ws, "SwIT_SwUFn_3546", col=2, rmax=ws.max_row)
    assert _find(ws, "SwIT_SwUFn_3514", col=2, rmax=ws.max_row)
    assert _find(ws, "SCI0_ISR", col=3, rmax=ws.max_row)
    assert _find(ws, "TIM0_Ch0_ISR", col=3, rmax=ws.max_row)
    # 정상 루트(s_Root)는 여전히 존재 — 미생성 블록이 트리를 대체하지 않음
    assert _find(ws, "SwIT_SwUFn_0001", col=2, rmax=ws.max_row)


def test_missing_swit_none_no_render():
    """missing_swit=None → 하단 미생성 표기 없음(기존 동작 보존)."""
    ws = _open(build_call_tree_xlsx(
        _uni(), {}, swit_map={"s_Root": "SwIT_1"}, missing_swit=None,
    ))["SW Integration Strategy"]
    assert not any(
        isinstance(ws.cell(r, 1).value, str) and "미생성 SwIT" in ws.cell(r, 1).value
        for r in range(1, ws.max_row + 1)
    )


def test_missing_swit_empty_no_render():
    """missing_swit=[] → 하단 미생성 표기 없음."""
    ws = _open(build_call_tree_xlsx(
        _uni(), {}, swit_map={"s_Root": "SwIT_1"}, missing_swit=[],
    ))["SW Integration Strategy"]
    assert not any(
        isinstance(ws.cell(r, 1).value, str) and "미생성 SwIT" in ws.cell(r, 1).value
        for r in range(1, ws.max_row + 1)
    )
