"""R90 — SUTS 기대값 ↔ 설계 대조(`generators.suts_design_check`).

소스로 계산한 기대값은 늘 코드와 같다 — 코드가 설계와 어긋나도. 이 대조는 칸마다 설계(SwUDS 출력 표 Value Range · HSIS SW 값
범위)가 그 출력에 적은 것과 견주어 정보로 적는다: 행 · 값은 그대로, Test Evidence 의 `Design Check` · `Design Basis` 열과
품질 보고서 `design_check` · 공시 `suts_design_check`.

실측(2026-10-16 HDPDM01 SwUDS v1.07 · 소스 PDS64_RD): `s16g_SysOptCtrl_OverPos` 의 설계 값 목록은 `0, 2470, 2268` 인데 코드의
`s16s_FRONT_OVER_POS` 는 2472 · `s16s_REAR_OVER_POS` 는 2253 이다(주석 `2542 - 50 - 20 = 2472`). 기대값은 코드를 따라 2472 를
적고, 예전엔 그 어긋남이 어디에도 보이지 않았다.

리뷰(deep) 반영: C1 근거 칸의 문서 이름은 지정한 원래 파일(웹 = 스크립트) · W1 머리 수는 단정할 수 있는 칸만 · W2 어긋날 수
없던 대조는 따로 · W3 같은 폭 부호 차이는 비트 패턴 · W4 표기만 다른 두 행은 상충 아님 · W5 대조 0 칸은 "밖 없음" 이 아님 ·
I1~I9.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from generators import suts
from generators.suts_design_check import (
    CONFLICTING,
    CONSISTENT,
    CONSISTENT_FULL_WIDTH,
    OUTSIDE,
    OUTSIDE_AMBIGUOUS_VALUES,
    OUTSIDE_CELL_UNREAD,
    OUTSIDE_ON_INPUT,
    OUTSIDE_STUB_VALUE,
    OUTSIDE_TWIN,
    OUTSIDE_TYPE_DIFFERS,
    OUTSIDE_UNDESIGNED_INPUT,
    DesignChecker,
    check_bucket,
    summarize_design_check,
    uds_output_rows,
)
from generators.uds_unit_io import load_uds_unit_io, resolve_unit_io, uds_param_key
from report_gen.generation_disclosures import build_disclosures

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in cells) + "</w:tr>"


def _docx(path: Path, tables: dict) -> str:
    body = ""
    for i, (name, rows) in enumerate(tables.items()):
        body += f"<w:p><w:r><w:t>SwUFn_{i + 1:04d}: {name}</w:t></w:r></w:p><w:tbl>{rows}</w:tbl>"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return str(path)


def _table(inputs, outputs, hdr=("No", "Name", "Type", "Value Range", "Reset Value", "Description")) -> str:
    head = _row(*hdr)
    s = _row("[ Function Information ]") + _row("ASIL", "QM") + _row("[ Input Parameters ]") + head
    s += "".join(_row(str(i + 1), n, t, r, "0", "-") for i, (n, t, r) in enumerate(inputs))
    s += _row("[ Output Parameters ]") + head
    s += "".join(_row(str(i + 1), n, t, r, "0", "-") for i, (n, t, r) in enumerate(outputs))
    return s + _row("[ Logic Diagram ]", "")


def _seq(expected, inputs=None, basis="assigned", status="derived", **ev):
    return {"seq_num": 1, "inputs": dict(inputs or {}), "expected": dict(expected),
            "expected_evidence": {k: {"status": status, "basis": basis, **ev} for k in expected}}


# ── SwUDS 출력 표를 따로 읽는다 ─────────────────────────────────────────────
class TestOutputRows:
    def test_output_row_is_kept_apart_from_the_input_row_of_the_same_name(self, tmp_path):
        """`param_info` 는 이름마다 첫 행(입력 표)이다 — 같은 이름의 출력 행이 적은 범위는 `out_info` 에만 있다."""
        p = _docx(tmp_path / "u.docx", {"Fn": _table([("g_x", "U8", "0x00 ~ 0xFF")],
                                                     [("g_x", "U8", "0x00 ~ 0x03"), ("Return", "U8", "0, 5, 9")])})
        rec = resolve_unit_io(load_uds_unit_io(p), "Fn")
        assert rec["param_info"]["g_x"]["range"] == [0, 255], "입력 행은 그대로 — 행을 만드는 출처는 바뀌지 않는다"
        assert rec["out_info"]["g_x"]["range"] == [0, 3] and rec["out_info"]["g_x"]["range_text"] == "0x00 ~ 0x03"
        assert rec["out_info"]["g_x"]["no"] == "1"
        assert rec["out_info"]["Return"]["values"] == [0, 5, 9] and rec["heading"] == "Fn"
        assert "two_value_list" not in rec["out_info"]["Return"] and "range_column_missing" not in rec["out_info"]["g_x"]

    def test_two_output_rows_that_disagree_are_both_kept(self, tmp_path):
        p = _docx(tmp_path / "u.docx", {"Fn": _table([], [("g_y", "U8", "0 ~ 3"), ("g_y", "U8", "0 ~ 7")])})
        rec = resolve_unit_io(load_uds_unit_io(p), "Fn")
        assert rec["out_info"]["g_y"]["range"] == [0, 3]
        assert [r["range_text"] for r in rec["out_info"]["g_y"]["conflicting_rows"]] == ["0 ~ 7"]
        same = _docx(tmp_path / "s.docx", {"Fn": _table([], [("g_y", "U8", "0 ~ 3"), ("g_y", "U8", "0 ~ 3")])})
        assert "conflicting_rows" not in resolve_unit_io(load_uds_unit_io(same), "Fn")["out_info"]["g_y"]

    def test_rows_that_differ_only_in_notation_are_not_a_conflict(self, tmp_path):
        """(리뷰 W4) KJPDS02_PV 의 '상충' 둘은 표기만 달랐다(`0x00 ~ 0xFF` · `0x00~0xFF`, `0XFFFFFFFF` · `0xFFFFFFFF`) —
        읽은 값으로 견준다. 못 읽은 칸은 원문(공백 · 대소문자 뺀)으로 — `0x05` 와 `0x06` 은 둘 다 `single_value` 지만 다른 말이다."""
        p = _docx(tmp_path / "u.docx", {"Fn": _table([], [
            ("g_a", "U8", "0x00 ~ 0xFF"), ("g_a", "U8", "0x00~0xFF"),
            ("g_b", "U32", "0x00000000 ~ 0XFFFFFFFF"), ("g_b", "U32", "0x00000000 ~ 0xFFFFFFFF"),
            ("g_c", "U8", "0x05"), ("g_c", "U8", "0X05"),
            ("g_d", "U8", "0x05"), ("g_d", "U8", "0x06")])})
        out = resolve_unit_io(load_uds_unit_io(p), "Fn")["out_info"]
        assert [k for k in ("g_a", "g_b", "g_c") if "conflicting_rows" in out[k]] == []
        assert [r["range_text"] for r in out["g_d"]["conflicting_rows"]] == ["0x06"]

    def test_empty_range_cell_is_a_row_without_range_not_an_absent_row(self, tmp_path):
        p = _docx(tmp_path / "u.docx", {"Fn": _table([], [("g_z", "U8", "N/A")])})
        rec = resolve_unit_io(load_uds_unit_io(p), "Fn")
        assert rec["out_info"]["g_z"]["range_text"] == "N/A" and "range" not in rec["out_info"]["g_z"]

    def test_table_without_a_value_range_column_and_two_value_lists_are_marked(self, tmp_path):
        """(리뷰 I3) Value Range 열이 없는 표는 '범위 칸이 비었다' 와 다르다. (리뷰 I2) 값 둘은 표기가 남는다."""
        hdr = ("No", "Name", "Type", "Reset Value", "Description")
        no_col = _row("[ Output Parameters ]") + _row(*hdr) + _row("1", "g_n", "U8", "0", "-")
        p = _docx(tmp_path / "u.docx", {"Fn": no_col, "Two": _table([("g_i", "U8", "0x00, 0xFF")],
                                                                     [("g_t", "U8", "0x00, 0xFF"), ("g_v", "U8", "0, 5, 9")])})
        io = load_uds_unit_io(p)
        assert resolve_unit_io(io, "Fn")["out_info"]["g_n"]["range_column_missing"] is True
        rec = resolve_unit_io(io, "Two")
        two = rec["out_info"]["g_t"]
        assert two["values"] == [0, 255] and two["two_value_list"] is True
        assert rec["param_info"]["g_i"]["two_value_list"] is True, "입력 행도 — 입력 쪽 대조가 같은 규칙을 쓴다"
        assert "two_value_list" not in rec["out_info"]["g_v"], "값 셋은 값 둘 목록이 아니다"

    def test_unit_block(self):
        io = {"by_name": {"Fn": {}}, "total": 1, "source": "d.docx"}
        assert uds_output_rows(None, None) is None and uds_output_rows(None, {"by_name": {}, "total": 0}) is None
        assert uds_output_rows(None, io) == {"doc": "d.docx", "heading": None, "rows": None}
        assert uds_output_rows({"heading": "Fn", "out_info": {"a": {}}}, io)["rows"] == {"a": {}}
        # (리뷰 C1) 지정한 원래 이름이 임시 사본 이름(`io["source"]`)보다 먼저 — 캐시된 맵은 바꾸지 않는다
        assert uds_output_rows({"heading": "Fn", "out_info": {}}, io, doc_name="orig.docx")["doc"] == "orig.docx"
        assert io["source"] == "d.docx"
        # (리뷰 W5) 지정했는데 표를 하나도 못 읽음 ≠ 지정 안 함
        assert uds_output_rows(None, None, doc_name="orig.docx") == {"doc": "orig.docx", "heading": None, "rows": None,
                                                                      "document_unread": True}
        # (리뷰 I3) 같은 이름의 표가 둘이라 빠진 함수
        amb = {"by_name": {"A": {}}, "total": 3, "ambiguous": ["Fn"], "source": "d.docx"}
        assert uds_output_rows(None, amb, function="Fn")["ambiguous"] is True
        assert "ambiguous" not in uds_output_rows(None, amb, function="Other")

    def test_one_key_rule(self):
        """(리뷰 I9) SUTS 범위 조회와 설계 대조가 같은 열쇠 규칙 하나를 쓴다."""
        for n in ("p->a[2].B C", "Return", "buf[3]", "p[0].m"):
            assert suts._uds_param_key(n) == uds_param_key(n)
        assert uds_param_key("p->m") == uds_param_key("p[0].m") == "p.m" and uds_param_key("Return") == "return"


# ── 판정 ─────────────────────────────────────────────────────────────────────
def _unit(rows=None, **kw):
    u = {"fid": "F1", "name": "Fn", "uds_output_rows": {"doc": "d.docx", "heading": "Fn", "rows": rows}}
    u.update(kw)
    return u


class TestClassify:
    def test_inside_outside_and_values(self):
        u = _unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "2", "type": "U8"},
                   "Return": {"values": [0, 5, 9], "range_text": "0, 5, 9", "no": "1"}})
        c = DesignChecker()
        assert c.classify(u, _seq({"g_out": 5}), "g_out")["check"] == CONSISTENT
        assert c.classify(u, _seq({"g_out": 0}), "g_out")["check"] == CONSISTENT, "하한(가장 흔한 값 0)도 안이다"
        r = c.classify(u, _seq({"g_out": 6}), "g_out")
        assert r["check"] == OUTSIDE and r["value"] == 6
        assert "d.docx · Fn [Output Parameters] No 2 `g_out` Value Range `0 ~ 5` → 0~5" in r["basis"]
        assert c.classify(u, _seq({"return": 9}), "return")["check"] == CONSISTENT, "`Return` 행은 `return` 열이다"
        assert c.classify(u, _seq({"return": 4}), "return")["check"] == OUTSIDE, "값 목록 사이의 정수는 설계 값이 아니다"

    def test_element_and_pointer_member_names_find_the_design_row(self):
        u = _unit({"buf": {"range": [0, 3], "range_text": "array 0x00 ~ 0x03", "no": "1", "type": "U8"},
                   "pst->u8_A": {"range": [0, 1], "range_text": "0 ~ 1", "no": "2", "type": "U8"}})
        c = DesignChecker()
        assert c.classify(u, _seq({"buf[2]": 4}), "buf[2]")["check"] == OUTSIDE
        assert c.classify(u, _seq({"pst[0].u8_A": 1}), "pst[0].u8_A")["check"] == CONSISTENT

    def test_rows_folding_into_one_key_are_not_picked_first_wins(self):
        """(리뷰 I1) `x[0]` 0~3 · `x[1]` 0~100 — 이름이 그대로 있으면 그 행, 같은 열쇠의 행들이 다른 말을 하면 첫 행을 고르지
        않는다(값이 한쪽에만 들면 '설계 행 갈림')."""
        u = _unit({"x[0]": {"range": [0, 3], "range_text": "0 ~ 3", "no": "1", "type": "U8"},
                   "x[1]": {"range": [0, 100], "range_text": "0 ~ 100", "no": "2", "type": "U8"},
                   "p->m": {"range": [0, 1], "range_text": "0 ~ 1", "no": "3"},
                   "p.m": {"range": [0, 9], "range_text": "0 ~ 9", "no": "4"},
                   "q->m": {"range": [0, 1], "range_text": "0 ~ 1", "no": "5"},
                   "Q->M": {"range": [0, 1], "range_text": "0x00 ~ 0x01", "no": "6"}})
        c = DesignChecker()
        assert c.classify(u, _seq({"x[1]": 50}), "x[1]")["check"] == CONSISTENT, "이름 그대로인 행"
        r = c.classify(u, _seq({"x[2]": 50}), "x[2]")
        assert r["check"] == CONFLICTING and "같은 출력의 다른 행: `0 ~ 100`(No 2 `x[1]`)" in r["basis"]
        assert c.classify(u, _seq({"x[2]": 2}), "x[2]")["check"] == CONSISTENT, "두 행 모두 안"
        assert c.classify(u, _seq({"x[2]": 101}), "x[2]")["check"] == OUTSIDE, "두 행 모두 밖"
        assert c.classify(u, _seq({"p[0].m": 5}), "p[0].m")["check"] == CONFLICTING
        assert "conflicting" not in c.statement(u, "q[0].m"), "같은 말(표기만 다름)이면 상충이 아니다"

    def test_out_of_design_input_row_is_not_a_defect_claim(self):
        u = _unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}},
                  uds_param_info={"g_in": {"range": [0, 1]}, "g_v": {"values": [0, 5]}}, var_types={"g_t": "uint8_t"})
        c = DesignChecker()
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_in": 2}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "g_in=2 (설계 0~1)" in r["basis"]
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_t": 256}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "g_t=256 (타입 uint8_t 0~255)" in r["basis"], "진술 없으면 선언 타입 폭"
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_v": 3}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "g_v=3 (설계 값 0,5)" in r["basis"], "입력의 값 목록도 본다"
        assert c.classify(u, _seq({"g_out": 7}, inputs={"g_v": 5}), "g_out")["check"] == OUTSIDE
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_in": 1}), "g_out")
        assert r["check"] == OUTSIDE and r["inputs_undesigned"] == [] and "설계 진술 없이" not in r["basis"]

    def test_outside_is_split_by_what_it_rests_on(self):
        """(리뷰 W1) HDPDM01 '설계 밖' 11 출력 중 입력이 모두 설계 진술 안이고 stub 이 없는 것은 4 — 나머지는 범위를 적지 않은
        입력 · stub 값에 기댔다. 그런 칸은 단정하지 않는다(약한 후보 라벨)."""
        u = _unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}},
                  uds_param_info={"g_in": {"range": [0, 1]}}, var_types={"g_t": "uint8_t"})
        c = DesignChecker()
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_in": 1, "g_t": 255}), "g_out")
        assert r["check"] == OUTSIDE_UNDESIGNED_INPUT and r["inputs_undesigned"] == ["g_t"]
        assert "설계 진술 없이 넣은 입력: g_t(설계 범위 없음 · 선언 타입 폭 안)" in r["basis"]
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_u": 3, "g_s": "N/A"}), "g_out")
        assert r["check"] == OUTSIDE_UNDESIGNED_INPUT, "(리뷰 I5) 타입도 모르는 입력 · 수가 아닌 입력은 대조하지 못했다"
        assert "g_u(설계 범위 없음 · 타입도 모름)" in r["basis"] and "g_s(수가 아닌 값 — 대조 안 함)" in r["basis"]
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_in": 1}, stubs=["Get"]), "g_out")
        assert r["check"] == OUTSIDE_STUB_VALUE and "stub 한 피호출: Get" in r["basis"]
        assert c.classify(u, _seq({"g_out": 7}, inputs={"g_in": 0.5}), "g_out")["check"] == OUTSIDE, "실수 입력은 크기로 견준다"
        assert c.classify(u, _seq({"g_out": 7}, inputs={"g_in": 1.5}), "g_out")["check"] == OUTSIDE_ON_INPUT

    def test_stub_value_outside_the_callees_design_return(self):
        """HDPDM01 실측: `g_SysCtrl_ErrorProtection` 행이 `u8s_RAM_Test() return` 을 127 로 stub 했다 — 피호출 함수의 설계 Return
        범위 밖 값이면 그 행은 설계 밖 입력에 기댄다(결함 주장이 아니다). 범위 안 stub 이면 설계 범위 밖 출력은 그대로 후보다."""
        callee = {"fid": "F2", "name": "Test", "uds_output_rows": {"doc": "d.docx", "heading": "Test", "rows": {
            "Return": {"range": [0, 1], "range_text": "0x00 ~ 0x01", "no": "1"}}}}
        u = _unit({"g_out": {"range": [0, 3], "range_text": "0 ~ 3", "no": "1"}})
        c = DesignChecker([u, callee])
        r = c.classify(u, _seq({"g_out": 9}, inputs={"Test() return": 127}, stubs=["Test"]), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "Test() return=127 (Test 설계 Return 0~1)" in r["basis"]
        assert c.classify(u, _seq({"g_out": 9}, inputs={"Test() return": 1}), "g_out")["check"] == OUTSIDE
        r = DesignChecker([u]).classify(u, _seq({"g_out": 9}, inputs={"Test() return": 127}), "g_out")
        assert r["check"] == OUTSIDE_UNDESIGNED_INPUT and "Test() return(피호출 함수의 설계 Return 없음)" in r["basis"], \
            "설계를 모르는 피호출 함수의 stub 값은 설계 진술이 아니다"
        # 피호출 함수가 있지만 설계 Return 이 없으면 — 건너뛰지 않고 '진술 없음'
        bare = {"fid": "F3", "name": "Test", "uds_output_rows": {"doc": "d.docx", "heading": "Test", "rows": {}}}
        assert DesignChecker([u, bare]).classify(u, _seq({"g_out": 9}, inputs={"Test() return": 1}), "g_out")["check"] \
            == OUTSIDE_UNDESIGNED_INPUT

    def test_stub_value_against_a_callee_value_list(self):
        callee = {"fid": "F2", "name": "Test", "uds_output_rows": {"doc": "d.docx", "heading": "Test", "rows": {
            "Return": {"values": [0, 1, 9], "range_text": "0, 1, 9", "no": "1"}}}}
        u = _unit({"g_out": {"range": [0, 3], "range_text": "0 ~ 3", "no": "1"}})
        c = DesignChecker([u, callee])
        assert c.classify(u, _seq({"g_out": 7}, inputs={"Test() return": 9}), "g_out")["check"] == OUTSIDE
        r = c.classify(u, _seq({"g_out": 7}, inputs={"Test() return": 4}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "Test() return=4 (Test 설계 Return 값 0,1,9)" in r["basis"]

    def test_stub_callee_twins_are_looked_up_in_the_same_build(self):
        """(리뷰 I6) APP · BOOT 에 같은 이름의 피호출 함수 — 같은 빌드(소스 경로가 가장 길게 겹치는 것)의 설계 Return 으로 본다.
        unit 순서가 바뀌어도 같다. 겹침이 같은 후보가 둘이면 고르지 않는다."""
        def callee(fid, path, hi):
            return {"fid": fid, "name": "Test", "source_path": path, "uds_output_rows": {"doc": "d.docx", "heading": "Test",
                    "rows": {"Return": {"range": [0, hi], "range_text": f"0 ~ {hi}", "no": "1"}}}}
        app, boot = callee("A", "D:/P/APP/src/t.c", 1), callee("B", "D:/P/BOOT/src/t.c", 200)
        u = _unit({"g_out": {"range": [0, 3], "range_text": "0 ~ 3", "no": "1"}}, source_path="D:/P/APP/src/u.c")
        seq = _seq({"g_out": 9}, inputs={"Test() return": 100})
        for order in ([u, app, boot], [u, boot, app]):
            r = DesignChecker(order).classify(u, seq, "g_out")
            assert r["check"] == OUTSIDE_ON_INPUT and "(Test 설계 Return 0~1)" in r["basis"], order[1]["fid"]
        tie = callee("C", "D:/P/APP/src/v.c", 200)
        r = DesignChecker([u, app, tie]).classify(u, seq, "g_out")
        assert r["check"] == OUTSIDE_UNDESIGNED_INPUT and "같은 이름의 피호출 정의 여럿" in r["basis"]

    def test_twin_definitions_are_named_in_the_basis(self):
        """(리뷰 I6) 같은 이름의 정의가 여럿(APP · BOOT `EEPROM_Init`)인데 이름으로 찾은 설계 표 하나와 대조했다는 사실."""
        rows = {"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}}
        a = _unit(rows, fid="A", source_path="D:/Ados/PDS64_RD/Sources/e.c")
        b = _unit(rows, fid="B", source_path="D:/Ados/PDS64_FBL/Sources/e.c")
        r = DesignChecker([a, b]).classify(a, _seq({"g_out": 1}), "g_out")
        assert "같은 이름의 정의 2개(PDS64_FBL/Sources/e.c, PDS64_RD/Sources/e.c) — 이름으로 찾은 설계 표 하나와 대조했다" \
            in r["basis"]
        assert "같은 이름의 정의" not in DesignChecker([a]).classify(a, _seq({"g_out": 1}), "g_out")["basis"]

    def test_return_read_through_the_variable_every_return_gives(self):
        """HDPDM01 SwUDS 는 반환값을 `Return` 이 아니라 돌려주는 지역 변수(`u8t_Result`)로 적는다(63 함수). 본문의 모든 `return` 이
        그 변수 하나를 돌려줄 때만 그 행을 반환값의 설계로 읽는다."""
        rows = {"u8t_Result": {"range": [0, 1], "range_text": "0x00 ~ 0x01", "no": "1", "type": "U8"}}
        src = ("typedef unsigned char U8;\nU8 g;\nU8 Fn(void)\n{\n    U8 u8t_Result = 0U;\n    if (g) { return (u8t_Result); }\n"
               "    u8t_Result = 1U;\n    return /* the result */ u8t_Result;\n}\n")
        c = DesignChecker()
        r = c.classify(_unit(rows, source_text=src), _seq({"return": 2}), "return")
        assert r["check"] == OUTSIDE and "(본문의 모든 return 이 `u8t_Result` 를 돌려준다)" in r["basis"]
        assert c.classify(_unit(rows, source_text=src), _seq({"g_other": 2}), "g_other")["check"] == \
            "no_design_statement:not_in_design_outputs", "별칭은 반환값에만 — 다른 출력을 그 행으로 읽지 않는다"
        two = src.replace("return (u8t_Result);", "return u9_Other;")
        assert DesignChecker().classify(_unit(rows, source_text=two), _seq({"return": 2}), "return")["check"] == \
            "no_design_statement:not_in_design_outputs", "다른 것을 돌려주는 return 이 있으면 읽지 않는다"
        expr = src.replace("return (u8t_Result);", "return (U8)(u8t_Result + 1U);")
        assert DesignChecker().classify(_unit(rows, source_text=expr), _seq({"return": 2}), "return")["check"] == \
            "no_design_statement:not_in_design_outputs", "식을 돌려주는 return 은 변수가 아니다"
        twin = src + src.replace("U8 g;", "")
        assert DesignChecker().classify(_unit(rows, source_text=twin), _seq({"return": 2}), "return")["check"] == \
            "no_design_statement:not_in_design_outputs", "같은 이름의 정의가 둘이면 어느 본문인지 모른다"
        assert DesignChecker().classify(_unit(rows, source_text=src, source_text_complete=False), _seq({"return": 2}),
                                        "return")["check"] == "no_design_statement:return_alias_unreadable"
        assert c.classify(_unit(rows, source_text=src), _seq({"u8t_Result": 2}), "u8t_Result")["check"] == OUTSIDE

    def test_return_alias_parse_failure_is_named_and_each_text_is_parsed_once(self, monkeypatch):
        """(리뷰 I3) 파싱 실패는 '출력 표에 없음' 이 아니다. (리뷰 I7) 같은 원문의 unit 들은 한 번만 파싱한다."""
        from generators import c_project_context

        rows = {"u8t_Result": {"range": [0, 1], "range_text": "0 ~ 1", "no": "1"}}
        src = "typedef unsigned char U8;\nU8 A(void) { U8 u8t_Result = 0U; return u8t_Result; }\n" \
              "U8 B(void) { U8 u8t_Result = 1U; return u8t_Result; }\n"
        real = c_project_context.shared_parser
        calls = []

        class Counting:
            def __init__(self, p):
                self._p = p

            def parse(self, raw):
                calls.append(len(raw))
                return self._p.parse(raw)

        monkeypatch.setattr(c_project_context, "shared_parser", lambda: Counting(real()))
        c = DesignChecker()
        a, b = _unit(rows, name="A", source_text=src), _unit(rows, fid="F2", name="B", source_text=src)
        assert c.classify(a, _seq({"return": 2}), "return")["check"] == OUTSIDE
        assert c.classify(b, _seq({"return": 2}), "return")["check"] == OUTSIDE
        assert len(calls) == 1, "파일당 한 번"

        def broken():
            raise RuntimeError("no grammar")

        monkeypatch.setattr(c_project_context, "shared_parser", broken)
        assert DesignChecker().classify(a, _seq({"return": 2}), "return")["check"] == \
            "no_design_statement:return_alias_unreadable"

    def test_no_statement_reasons_are_named(self):
        c = DesignChecker()
        seq = _seq({"g_out": 1})
        assert c.classify({"fid": "F", "name": "Fn"}, seq, "g_out")["check"] == "no_design_statement:no_design_document"
        assert c.classify(_unit(None), seq, "g_out")["check"] == "no_design_statement:no_design_table"
        assert c.classify(_unit({}), seq, "g_out")["check"] == "no_design_statement:not_in_design_outputs"
        r = c.classify(_unit({"g_out": {"range_text": "", "no": "1"}}), seq, "g_out")
        assert r["check"] == "no_design_statement:design_row_without_range" and "No 1" in r["basis"]
        r = c.classify(_unit({"g_out": {"range_unread": "single_value", "range_text": "0x05", "no": "1"}}), seq, "g_out")
        assert r["check"] == "no_design_statement:range_unread:single_value" and "`0x05`" in r["basis"]
        # (리뷰 W5 · I3) 지정했지만 못 읽은 문서 · 같은 이름의 표 둘 · Value Range 열이 없는 표
        unread = {"fid": "F", "name": "Fn", "uds_output_rows": uds_output_rows(None, None, doc_name="x.docx")}
        assert c.classify(unread, seq, "g_out")["check"] == "no_design_statement:design_document_unread"
        amb = {"fid": "F", "name": "Fn", "uds_output_rows": {"doc": "d", "heading": None, "rows": None, "ambiguous": True}}
        assert c.classify(amb, seq, "g_out")["check"] == "no_design_statement:ambiguous_design_table"
        r = c.classify(_unit({"g_out": {"range_text": "", "no": "1", "range_column_missing": True}}), seq, "g_out")
        assert r["check"] == "no_design_statement:design_table_without_range_column"

    def test_pointer_rows(self):
        c = DesignChecker()
        addr = _unit({"p": {"range": [0, 0xFFFFFFFF], "range_text": "0 ~ 0xFFFFFFFF", "type": "U16 *", "no": "1"}})
        assert c.classify(addr, _seq({"p[0]": 70000}), "p[0]")["check"] == "no_design_statement:pointer_row_address"
        neg = _unit({"p": {"range": [-5, 100], "range_text": "-5 ~ 100", "type": "U16 *", "no": "1"}})
        assert c.classify(neg, _seq({"p[0]": 1}), "p[0]")["check"] == "no_design_statement:pointer_row_address", \
            "가리키는 타입의 하한 밖도 주소 범위다"
        bare = _unit({"p": {"range_text": "", "type": "U16 *", "no": "1"}})
        assert c.classify(bare, _seq({"p[0]": 1}), "p[0]")["check"] == "no_design_statement:design_row_without_range"
        val = _unit({"p": {"range": [0, 100], "range_text": "0 ~ 100", "type": "U16 *", "no": "1"}})
        assert c.classify(val, _seq({"p[0]": 101}), "p[0]")["check"] == OUTSIDE, "가리키는 타입에 드는 범위는 값의 범위다"
        # (리뷰 I8) `U32 *` 의 `0 ~ 0xFFFFFFFF` 는 주소 범위와 가를 수 없다 — 어긋날 수 없는 대조로(범위 안에 넣지 않는다)
        u32 = _unit({"p": {"range": [0, 0xFFFFFFFF], "range_text": "0 ~ 0xFFFFFFFF", "type": "U32 *", "no": "1"}})
        assert c.classify(u32, _seq({"p[0]": 7}), "p[0]")["check"] == CONSISTENT_FULL_WIDTH

    def test_pointer_input_rows(self):
        """(리뷰 I8) 입력 쪽 포인터 행 — 주소 범위 · 가리키는 타입 전폭은 그 입력의 설계 진술이 아니다."""
        out = {"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}}
        c = DesignChecker()
        for rec in ({"type": "U32 *", "range": [0, 0xFFFFFFFF]}, {"type": "U16 *", "range": [0, 0xFFFFFFFF]}):
            u = _unit(out, uds_param_info={"p[0]": rec})
            assert c.classify(u, _seq({"g_out": 7}, inputs={"p[0]": 5}), "g_out")["check"] == OUTSIDE_UNDESIGNED_INPUT
        u = _unit(out, uds_param_info={"p[0]": {"type": "U16 *", "range": [0, 10]}})
        assert DesignChecker().classify(u, _seq({"g_out": 7}, inputs={"p[0]": 5}), "g_out")["check"] == OUTSIDE
        assert DesignChecker().classify(u, _seq({"g_out": 7}, inputs={"p[0]": 11}), "g_out")["check"] == OUTSIDE_ON_INPUT

    def test_full_width_design_range_is_a_comparison_that_could_not_fail(self):
        """(리뷰 W2) 설계 범위가 값의 타입 전폭이면 밖으로 나갈 수 없다 — '범위 안' 으로 세지 않는다(HDPDM01 4,143 중 1,855)."""
        c = DesignChecker()
        full = _unit({"g_a": {"range": [0, 255], "range_text": "0x00 ~ 0xFF", "no": "1", "type": "U8"},
                      "g_b": {"range": [0, 255], "range_text": "0 ~ 255", "no": "2", "type": "U8"},
                      "g_c": {"range": [0, 5], "range_text": "0 ~ 5", "no": "3", "type": "U8"}},
                     var_types={"g_b": "uint16_t"})
        assert c.classify(full, _seq({"g_a": 3}), "g_a")["check"] == CONSISTENT_FULL_WIDTH, "소스 타입 모름 → 설계 행 타입"
        assert c.classify(full, _seq({"g_b": 3}), "g_b")["check"] == CONSISTENT, "소스가 더 넓으면 밖으로 나갈 수 있다"
        assert c.classify(full, _seq({"g_c": 3}), "g_c")["check"] == CONSISTENT
        flag = _unit({"g_f": {"range": [0, 1], "range_text": "0 ~ 1", "no": "1"}}, var_types={"g_f": "bool"})
        assert c.classify(flag, _seq({"g_f": 1}), "g_f")["check"] == CONSISTENT_FULL_WIDTH

    def test_same_width_sign_difference_is_compared_by_bit_pattern(self):
        """(리뷰 W3) 설계 S16 `0xFFF6 ~ 0x000A`(-10~10) 에 소스 U16 65531(= -5), 설계 U16 전폭에 소스 S16 -5 — 같은 비트다."""
        c = DesignChecker()
        s16 = _unit({"g": {"range": [-10, 10], "range_text": "0xFFF6 ~ 0x000A", "no": "1", "type": "S16"}},
                    var_types={"g": "uint16_t"})
        r = c.classify(s16, _seq({"g": 65531}), "g")
        assert r["check"] == CONSISTENT and "비트 패턴으로 대조: 65531 → -5" in r["basis"]
        assert c.classify(s16, _seq({"g": 100}), "g")["check"] == OUTSIDE, "비트로 읽어도 밖이면 밖"
        for src in ("int16_t", "sint16_t"):     # 표 밖 철자도 폭이 정해진 정수면 읽는다
            u16 = _unit({"g": {"range": [0, 65535], "range_text": "0x0000 ~ 0xFFFF", "no": "1", "type": "U16"}},
                        var_types={"g": src})
            assert DesignChecker().classify(u16, _seq({"g": -5}), "g")["check"] == CONSISTENT_FULL_WIDTH, src
        # 설계 타입을 모르는데 부호 표기가 소스 타입과 다르다 — 단정하지 않는다
        neg = _unit({"g": {"range": [-10, 10], "range_text": "-10 ~ 10", "no": "1", "type": "T_Gain"}},
                    var_types={"g": "uint16_t"})
        assert c.classify(neg, _seq({"g": 65531}), "g")["check"] == OUTSIDE_TYPE_DIFFERS
        hi = _unit({"g": {"range": [0, 0xFFF0], "range_text": "0 ~ 0xFFF0", "no": "1", "type": "T_Gain"}},
                   var_types={"g": "int16_t"})
        assert c.classify(hi, _seq({"g": -5}), "g")["check"] == OUTSIDE_TYPE_DIFFERS
        assert c.classify(hi, _seq({"g": 5}), "g")["check"] == CONSISTENT

    def test_bit_pattern_only_for_the_same_width(self):
        """(2차 W-C, M03) 부호도 폭도 다른 타입(설계 U8 · 소스 S16)은 비트 패턴으로 읽지 않는다 — 266 을 하위 8 비트(10)로 읽으면
        설계 `0 ~ 10` 안이 된다."""
        u = _unit({"g": {"range": [0, 10], "range_text": "0 ~ 10", "no": "1", "type": "U8"}}, var_types={"g": "int16_t"})
        r = DesignChecker().classify(u, _seq({"g": 266}), "g")
        assert r["check"] == OUTSIDE and "비트 패턴" not in r["basis"]

    def test_two_value_rule_reads_every_row_and_the_design_types_bit_pattern(self):
        """(2차 W-C) M10 — 같은 출력의 다른 행이 값 둘 목록이어도 사이 값은 단정하지 않는다. M27 — '사이' 는 설계 타입의 표기로 본
        값으로 판단한다(설계 S16 값 둘 `-10, 10` · 소스 U16 65531 = S16 -5 는 사이다)."""
        c = DesignChecker()
        u = _unit({"x[0]": {"range": [0, 3], "range_text": "0 ~ 3", "no": "1"},
                   "x[1]": {"values": [2, 9], "range_text": "0x02, 0x09", "no": "2", "two_value_list": True}})
        assert c.classify(u, _seq({"x[2]": 5}), "x[2]")["check"] == OUTSIDE_AMBIGUOUS_VALUES
        assert c.classify(u, _seq({"x[2]": 12}), "x[2]")["check"] == OUTSIDE
        s16 = _unit({"g": {"values": [-10, 10], "range_text": "0xFFF6, 0x000A", "no": "1", "type": "S16", "two_value_list": True}},
                    var_types={"g": "uint16_t"})
        r = c.classify(s16, _seq({"g": 65531}), "g")
        assert r["check"] == OUTSIDE_AMBIGUOUS_VALUES and "값 -5 이 값 둘 -10,10 사이" in r["basis"]

    def test_twin_definitions_do_not_give_a_determinate_outside(self):
        """(2차 W-A) APP · BOOT 가 둘 다 `EEPROM_Init` 를 정의하고 SwUDS 표는 하나(이름으로 찾음) — BOOT 행의 값이 그 표 밖이어도
        그 표가 BOOT 의 설계라는 근거가 문서에 없다. 머리 수 · 표본에 넣지 않는다(HDPDM01 · KJPDS02_PV: `EEPROM_Init` ·
        `lin_lld_sci_init`, 현재 0칸)."""
        rows = {"g_eep_state": {"range": [0, 2], "range_text": "0x00 ~ 0x02", "no": "1", "type": "U8"}}
        blk = {"doc": "SwUDS.docx", "heading": "EEPROM_Init", "rows": rows}

        def unit(fid, root, **kw):
            return {"fid": fid, "name": "EEPROM_Init", "source_path": f"C:/P/{root}/Sources/eep.c", "uds_output_rows": blk,
                    "var_types": {"g_eep_state": "uint8_t"}, **kw}

        app, boot = unit("A", "APP"), unit("B", "FBL")
        c = DesignChecker([app, boot])
        r = c.classify(boot, _seq({"g_eep_state": 5}), "g_eep_state")
        assert r["check"] == OUTSIDE_TWIN and "이름으로 찾은 표가 이 빌드의 설계인지 모른다 — 단정하지 않는다" in r["basis"]
        assert "같은 이름의 정의 2개(APP/Sources/eep.c, FBL/Sources/eep.c)" in r["basis"]
        assert c.classify(boot, _seq({"g_eep_state": 1}), "g_eep_state")["check"] == CONSISTENT
        assert DesignChecker([app]).classify(app, _seq({"g_eep_state": 5}), "g_eep_state")["check"] == OUTSIDE, "정의 하나면 단정"
        s = summarize_design_check([app, boot], {"A": [_seq({"g_eep_state": 2})], "B": [_seq({"g_eep_state": 5})]}, True)
        assert s["outside_slots"] == 0 and s["outside_samples"] == [] and s["outside_twin_definition_slots"] == 1
        # HSIS 진술은 변수의 진술이다 — 같은 이름의 정의가 여럿이어도 단정하고, 표 이야기를 근거에 적지 않는다
        h = {"doc": "SwUDS.docx", "heading": "EEPROM_Init", "rows": {}}
        happ = unit("A", "APP", uds_output_rows=h, hsis_bounds={"g_eep_state": (0, 2)})
        hboot = unit("B", "FBL", uds_output_rows=h, hsis_bounds={"g_eep_state": (0, 2)})
        r = DesignChecker([happ, hboot]).classify(hboot, _seq({"g_eep_state": 5}), "g_eep_state")
        assert r["check"] == OUTSIDE and "같은 이름의 정의" not in r["basis"]

    def test_inputs_are_read_in_the_design_types_bit_pattern_too(self):
        """(리뷰 W3) HDPDM01 12 행: 입력 `s16g_SysEepromCtrl_FrM10ClGain=-1`(소스 S16)을 설계 U16 `0~65535` 밖 입력으로 봤다 — 같은
        비트(65535)다. 설계 타입을 모르는데 부호 표기가 다르면 '설계 밖 입력' 이라 하지 않고 '진술 없음(대조 안 함)' 이다."""
        out = {"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}}
        u = _unit(out, uds_param_info={"s16g_Gain": {"type": "U16", "range": [0, 65535]},
                                       "g_s": {"type": "S16", "range": [-10, 10]},
                                       "g_n": {"type": "T_Gain", "range": [-10, 10]}},
                  var_types={"s16g_Gain": "int16_t", "g_s": "uint16_t", "g_n": "uint16_t"})
        c = DesignChecker()
        assert c.classify(u, _seq({"g_out": 7}, inputs={"s16g_Gain": -1}), "g_out")["check"] == OUTSIDE
        assert c.classify(u, _seq({"g_out": 7}, inputs={"g_s": 65531}), "g_out")["check"] == OUTSIDE, "65531 = S16 -5"
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_s": 100}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "g_s=100 (설계 -10~10)" in r["basis"]
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_s": 65000}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "g_s=65000 (설계 -10~10) — 비트 패턴 -536" in r["basis"]
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_n": 65531}), "g_out")
        assert r["check"] == OUTSIDE_UNDESIGNED_INPUT and "g_n(설계 범위와 소스 타입의 부호 표기가 다름 — 대조 안 함)" in r["basis"]

    def test_hsis_only_when_the_design_row_says_no_range(self):
        c = DesignChecker()
        u = _unit({}, hsis_bounds={"g_out": (0, 3)}, hsis_range_text={"g_out": "0x00 ~ 0x03"})
        r = c.classify(u, _seq({"g_out": 4}), "g_out")
        assert r["check"] == OUTSIDE and r["statement"]["source"] == "HSIS"
        assert r["basis"] == "HSIS · `g_out` SW Value Range `0x00 ~ 0x03` → 0~3", "출처 · 칸 이름을 겹쳐 적지 않는다"
        assert c.classify(_unit({}, hsis_bounds={"g_arr": (0, 3)}), _seq({"g_arr[2]": 4}), "g_arr[2]")["check"] == OUTSIDE, \
            "원소 이름은 첨자를 떼고 찾는다"
        u = _unit({"g_out": {"range_unread": "single_value", "range_text": "0x05", "no": "4"}}, hsis_bounds={"g_out": (0, 3)})
        r = c.classify(u, _seq({"g_out": 4}), "g_out")
        # (2차 I-2) SwUDS 행이 무엇을 적었는데 못 읽었다 — HSIS 범위 밖이어도 단정하지 않는다
        assert r["check"] == OUTSIDE_CELL_UNREAD
        assert "No 4 `g_out` 의 범위 칸 `0x05` 을 읽지 못했다 — range_unread:single_value" in r["basis"]
        assert "SwUDS 행의 범위 칸을 읽지 못해 HSIS 범위로 대조했다 — 단정하지 않는다" in r["basis"]
        assert c.classify(u, _seq({"g_out": 3}), "g_out")["check"] == CONSISTENT
        # 행이 범위를 적지 않았으면(빈칸 · N/A) 설계서가 다른 말을 하지 않았다 — HSIS 로 단정한다
        bare = _unit({"g_out": {"range_text": "N/A", "no": "4"}}, hsis_bounds={"g_out": (0, 3)})
        assert c.classify(bare, _seq({"g_out": 4}), "g_out")["check"] == OUTSIDE
        u = _unit({"g_out": {"range": [0, 9], "range_text": "0 ~ 9", "no": "1"}}, hsis_bounds={"g_out": (0, 3)})
        assert c.classify(u, _seq({"g_out": 4}), "g_out")["check"] == CONSISTENT, "SwUDS 출력 행이 먼저"

    def test_not_checked(self):
        c = DesignChecker()
        u = _unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}})
        for status in ("unknown", "proposed", "unsupported", "unrecorded"):
            assert c.classify(u, _seq({"g_out": 9}, status=status), "g_out")["check"] == "not_checked:not_derived", status
        assert c.classify(u, _seq({"g_out": 9}, basis="unchanged_input"), "g_out")["check"] == \
            "not_checked:unchanged_input", "함수가 쓰지 않은 값은 함수의 결과가 아니다"
        assert c.classify(u, _seq({"g_out": 1.5}), "g_out")["check"] == "not_checked:value_not_integer"
        assert c.classify(u, _seq({"g_out": 5.0}), "g_out")["check"] == CONSISTENT, "정수인 실수는 대조한다"
        assert c.classify(u, _seq({"g_out": True}), "g_out")["check"] == CONSISTENT

    def test_basis_lists_are_never_cut_silently(self):
        """(리뷰 I4) 다른 행 · stub · 입력 목록은 넘으면 '외 N'."""
        c = DesignChecker()
        u = _unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1",
                             "conflicting_rows": [{"range_text": f"0 ~ {9 + i}", "no": str(2 + i)} for i in range(5)]}})
        r = c.classify(u, _seq({"g_out": 6}, stubs=[f"f{i}" for i in range(6)]), "g_out")
        assert "같은 출력의 다른 행: `0 ~ 9`(No 2), `0 ~ 10`(No 3), `0 ~ 11`(No 4) 외 2" in r["basis"]
        assert "stub 한 피호출: f0, f1, f2, f3 외 2" in r["basis"]
        r = c.classify(_unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}}),
                       _seq({"g_out": 6}, inputs={f"g{i}": "x" for i in range(6)}), "g_out")
        assert r["basis"].endswith("g3(수가 아닌 값 — 대조 안 함) 외 2")

    def test_two_value_list_gives_no_determinate_verdict_between_the_two_values(self):
        """(리뷰 I2, 결정) `0x02, 0x09` 는 '값 둘' 인지 '쉼표로 쓴 범위' 인지 문서가 말하지 않는다 — 두 값 사이는 두 읽기가 갈려
        단정하지 않고(약한 후보), 두 값과 같으면 안, 두 값 밖(테두리 밖)이면 어느 읽기로도 밖이라 단정한다."""
        u = _unit({"g": {"values": [2, 9], "range_text": "0x02, 0x09", "no": "1", "type": "U8", "two_value_list": True}})
        c = DesignChecker()
        r = c.classify(u, _seq({"g": 5}), "g")
        assert r["check"] == OUTSIDE_AMBIGUOUS_VALUES
        assert "값 둘 — '값 둘' 인지 쉼표로 쓴 범위인지 설계서가 말하지 않는다" in r["basis"]
        assert "값 5 이 값 둘 2,9 사이 — 값 둘이면 밖 · 쉼표로 쓴 범위면 안이라 단정하지 않는다" in r["basis"]
        assert c.classify(u, _seq({"g": 2}), "g")["check"] == CONSISTENT and c.classify(u, _seq({"g": 9}), "g")["check"] == CONSISTENT
        assert c.classify(u, _seq({"g": 12}), "g")["check"] == OUTSIDE and c.classify(u, _seq({"g": 1}), "g")["check"] == OUTSIDE
        # 값 둘 목록 표시가 없는 값 목록(설계가 정한 값 집합)은 사이 값도 밖이다
        plain = _unit({"g": {"values": [2, 9], "range_text": "2, 9", "no": "1", "type": "U8"}})
        assert c.classify(plain, _seq({"g": 5}), "g")["check"] == OUTSIDE

    def test_two_value_list_on_the_input_side(self):
        out = {"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"}}
        u = _unit(out, uds_param_info={"g_tv": {"type": "U8", "values": [2, 9], "two_value_list": True}})
        c = DesignChecker()
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_tv": 5}), "g_out")
        assert r["check"] == OUTSIDE_UNDESIGNED_INPUT
        assert "g_tv(설계 값 둘 사이 — 값 둘인지 쉼표로 쓴 범위인지 설계서가 말하지 않음)" in r["basis"]
        r = c.classify(u, _seq({"g_out": 7}, inputs={"g_tv": 12}), "g_out")
        assert r["check"] == OUTSIDE_ON_INPUT and "g_tv=12 (설계 값 2,9)" in r["basis"], "두 값 밖은 어느 읽기로도 설계 밖"
        assert c.classify(u, _seq({"g_out": 7}, inputs={"g_tv": 9}), "g_out")["check"] == OUTSIDE


class TestSummary:
    def test_counts(self):
        u = _unit({"g_out": {"range": [0, 5], "range_text": "0 ~ 5", "no": "1"},
                   "g_c": {"range": [0, 1], "range_text": "0 ~ 1", "no": "2", "conflicting_rows": [{"range_text": "0~3"}]}},
                  uds_param_info={"g_in": {"range": [0, 1]}})
        seqs = {"F1": [_seq({"g_out": 6, "g_c": 1}), _seq({"g_out": 7}, stubs=["f"]),
                       _seq({"g_out": 9}, inputs={"g_in": 3}), _seq({"g_out": 2, "g_other": 1}),
                       _seq({"g_out": 99}, status="unknown"), _seq({"g_out": 50}, basis="unchanged_input"),
                       _seq({"g_n": 1.5})]}
        s = summarize_design_check([u], seqs, True)
        assert s["derived_slots"] == 8 and s["by_check"] == {OUTSIDE: 1, CONSISTENT: 2, OUTSIDE_STUB_VALUE: 1,
                                                             OUTSIDE_ON_INPUT: 1, "no_design_statement": 1,
                                                             "not_checked": 2}
        assert s["outside_slots"] == 1 and s["outside_outputs"] == 1 and s["outside_functions"] == 1
        assert s["outside_stub_value_slots"] == 1 and s["outside_stub_value_outputs"] == 1
        assert s["outside_undesigned_input_slots"] == 0 and s["outside_type_differs_slots"] == 0
        s2 = summarize_design_check([{**u, "var_types": {"g_t": "uint8_t"}}], {"F1": [
            _seq({"g_out": 7}, inputs={"g_t": 3}), _seq({"g_out": 6})]}, True)
        assert s2["outside_undesigned_input_outputs"] == 1 and s2["outside_outputs"] == 1
        assert s2["outside_samples"] == [s2["outside_samples"][0]] and "설계 진술 없이" not in s2["outside_samples"][0], \
            "표본은 단정할 수 있는 칸만, 글은 설계 진술만"
        twin = {**u, "fid": "F2"}
        s3 = summarize_design_check([u, twin], {"F1": [_seq({"g_out": 6})], "F2": [_seq({"g_out": 8})]}, True)
        # 같은 이름의 두 정의(APP · FBL)를 한 출력으로 묶지 않는다 — 그리고 둘 다 이름으로 찾은 표 하나라 단정하지 않는다(2차 W-A)
        assert s3["outside_twin_definition_outputs"] == 2 and s3["outside_twin_definition_slots"] == 2
        assert s3["outside_outputs"] == 0 and s3["outside_samples"] == []
        assert s["outside_on_input_slots"] == 1 and s["outside_on_input_outputs"] == 1
        # 정수가 아닌 값의 칸도 그 출력을 센다(`g_n` — 대조하지 못한 출력도 출력 수에 든다)
        assert s["outputs"] == 4 and s["outputs_with_statement"] == 2 and s["conflicting_design_rows"] == 1
        assert s["functions"] == 1 and s["functions_with_statement"] == 1
        assert s["not_compared_by_reason"] == {"no_design_statement:not_in_design_outputs": 1,
                                               "not_checked:unchanged_input": 1, "not_checked:value_not_integer": 1}
        assert s["outside_samples"][0].startswith("Fn.g_out = 6 (1행) ← SwUDS d.docx")

    def test_full_width_and_conflicting_cells_are_counted_apart(self):
        u = _unit({"g_a": {"range": [0, 255], "range_text": "0 ~ 255", "no": "1", "type": "U8"},
                   "x[0]": {"range": [0, 3], "range_text": "0 ~ 3", "no": "2"},
                   "x[1]": {"range": [0, 9], "range_text": "0 ~ 9", "no": "3"}})
        s = summarize_design_check([u], {"F1": [_seq({"g_a": 1, "x[2]": 5}), _seq({"g_a": 2, "x[2]": 1})]}, True)
        assert s["type_full_width_slots"] == 2 and s["type_full_width_outputs"] == 1 and s["consistent_slots"] == 1
        assert s["conflicting_design_slots"] == 1 and s["conflicting_design_outputs"] == 1
        assert s["by_check"] == {CONSISTENT_FULL_WIDTH: 2, CONFLICTING: 1, CONSISTENT: 1}

    def test_two_value_list_between_is_a_weak_candidate_not_a_headline(self):
        u = _unit({"g": {"values": [2, 9], "range_text": "0x02, 0x09", "no": "1", "two_value_list": True}})
        s = summarize_design_check([u], {"F1": [_seq({"g": 5}), _seq({"g": 12}), _seq({"g": 9})]}, True)
        assert s["outside_ambiguous_value_list_slots"] == 1 and s["outside_ambiguous_value_list_outputs"] == 1
        assert s["outside_slots"] == 1 and s["outside_samples"] == [s["outside_samples"][0]]
        assert s["outside_samples"][0].startswith("Fn.g = 12 (1행)"), "표본은 테두리 밖 값만(사이 값 5 는 없다)"
        assert s["by_check"] == {OUTSIDE_AMBIGUOUS_VALUES: 1, OUTSIDE: 1, CONSISTENT: 1}

    def test_samples_are_cut_with_the_total(self):
        rows = {f"g{i}": {"range": [0, 1], "range_text": "0 ~ 1", "no": str(i)} for i in range(25)}
        s = summarize_design_check([_unit(rows)], {"F1": [_seq({f"g{i}": 5 for i in range(25)})]}, True)
        assert len(s["outside_samples"]) == 20 and s["outside_samples_total"] == 25


# ── 공시 ─────────────────────────────────────────────────────────────────────
class TestDisclosure:
    def _item(self, block):
        return {i["key"]: i for i in build_disclosures("suts", {"design_check": block})}.get("suts_design_check")

    @staticmethod
    def _block(**kw):
        b = {"uds_given": True, "derived_slots": 10, "outputs": 3, "outputs_with_statement": 2, "functions": 1,
             "functions_with_statement": 1, "consistent_slots": 3, "type_full_width_slots": 2, "type_full_width_outputs": 1,
             "outside_slots": 2, "outside_outputs": 1, "outside_functions": 1, "outside_on_input_slots": 0,
             "outside_on_input_outputs": 0, "conflicting_design_slots": 0, "conflicting_design_outputs": 0,
             "conflicting_design_rows": 0, "outside_undesigned_input_slots": 3, "outside_undesigned_input_outputs": 2,
             "outside_stub_value_slots": 0, "outside_stub_value_outputs": 0, "outside_type_differs_slots": 0,
             "outside_type_differs_outputs": 0, "outside_ambiguous_value_list_slots": 0,
             "outside_ambiguous_value_list_outputs": 0, "outside_twin_definition_slots": 0,
             "outside_twin_definition_outputs": 0, "outside_design_cell_unread_slots": 0,
             "outside_design_cell_unread_outputs": 0, "stated_slots_by_source": {"SwUDS": 9},
             "outside_samples": ["Fn.g = 6 (2행) ← SwUDS x"], "outside_samples_total": 1,
             "not_compared_by_reason": {"no_design_statement:not_in_design_outputs": 1}}
        b.update(kw)
        return b

    def test_headline_counts_only_the_cells_that_can_be_claimed(self):
        """(리뷰 W1 · W2) 머리 수 '설계 범위 밖' 은 단정할 수 있는 칸만, 약한 후보와 어긋날 수 없던 대조는 따로."""
        it = self._item(self._block())
        assert it["tone"] == "warning"
        assert it["value"].startswith("설계 범위 밖 2칸(출력 1 · 함수 1) · 범위 안 3칸 · 어긋날 수 없던 대조 2칸 · 약한 후보 3칸")
        assert "Fn.g = 6 (2행)" in it["note"] and "출력 표에 없는 출력 1" in it["note"]
        assert "설계 진술 없이 넣은 입력에 기댄 것 3칸(출력 2)" in it["note"] and "stub 한 피호출 반환값에 기댄 것" not in it["note"]
        assert "어긋날 수 없던 대조 2칸(출력 1)은 '범위 안' 에 넣지 않았다" in it["note"]
        assert "설계 밖 입력(강건성" not in it["note"]
        it = self._item(self._block(outside_on_input_slots=4, outside_on_input_outputs=2))
        assert "설계 밖 입력(강건성 · 오류 경로 행)에서 밖으로 나간 칸은 결함 주장이 아니라 따로 센다(출력 2)" in it["note"]
        # (I2 결정) 값 둘 목록의 두 값 사이도 약한 후보 — 머리 수에 넣지 않고 종류를 적는다
        it = self._item(self._block(outside_ambiguous_value_list_slots=2, outside_ambiguous_value_list_outputs=1))
        assert "약한 후보 5칸" in it["value"] and it["value"].startswith("설계 범위 밖 2칸")
        assert "설계 값 둘 목록의 두 값 사이(값 둘인지 쉼표로 쓴 범위인지 설계서가 말하지 않음) 2칸(출력 1)" in it["note"]
        it = self._item(self._block(outside_twin_definition_slots=1, outside_twin_definition_outputs=1,
                                    outside_design_cell_unread_slots=2, outside_design_cell_unread_outputs=1))
        assert "약한 후보 6칸" in it["value"]
        assert "같은 이름의 정의가 여럿(APP · BOOT)이라 이름으로 찾은 설계 표가 이 빌드의 것인지 모르는 것 1칸(출력 1)" in it["note"]
        assert "SwUDS 행의 범위 칸을 못 읽어 HSIS 범위로 대조한 것 2칸(출력 1)" in it["note"]

    def test_weak_only_is_not_a_claim_and_not_silence(self):
        it = self._item(self._block(outside_slots=0, outside_outputs=0, outside_functions=0, outside_samples=[],
                                    outside_samples_total=0))
        assert it["tone"] == "info" and it["value"].startswith("설계 범위 밖 0칸")
        # (2차 W-B) 괄호 안 수는 단정할 수 있던 대조(범위 안)만 — 약한 후보 3 은 그 분모가 아니다
        assert "설계 범위 밖 기대값은 없었다(범위 안 3칸)" in it["note"] and "약한 후보" in it["note"]

    def test_comparisons_that_could_not_fail_do_not_read_as_no_problems(self):
        """(리뷰 W2 · W5) 대조가 전부 타입 전폭이면 '밖 없음' 이 아니다."""
        it = self._item(self._block(outside_slots=0, outside_outputs=0, outside_functions=0, consistent_slots=0,
                                    outside_undesigned_input_slots=0, outside_samples=[], outside_samples_total=0))
        assert it["tone"] == "warning" and "단정할 수 있는 대조가 0칸이다 — '설계 범위 밖 없음' 이 아니다" in it["note"]
        assert "대조한 칸이 모두 어긋날 수 없던 대조(타입 전폭) 2칸이다" in it["note"]
        assert "설계 범위 밖 기대값은 없었다" not in it["note"]

    def test_only_weak_cells_are_not_assertable_comparisons(self):
        """(2차 W-B) 범위 안 0 · 단정 밖 0 · 약한 후보 5 — '단정할 수 있는 칸에서 밖 없음(5)' 이라 하면 5 가 전부 약한 후보다."""
        it = self._item(self._block(outside_slots=0, outside_outputs=0, outside_functions=0, consistent_slots=0,
                                    type_full_width_slots=0, outside_undesigned_input_slots=5, outside_samples=[],
                                    outside_samples_total=0))
        assert it["tone"] == "warning"
        assert "단정할 수 있는 대조가 0칸이다 — '설계 범위 밖 없음' 이 아니다(대조한 칸이 모두 약한 후보 5칸이다)" in it["note"]
        assert "없었다" not in it["note"]

    def test_only_out_of_design_input_rows_are_not_assertable_comparisons(self):
        it = self._item(self._block(outside_slots=0, outside_outputs=0, outside_functions=0, consistent_slots=0,
                                    type_full_width_slots=0, outside_undesigned_input_slots=0, outside_on_input_slots=4,
                                    outside_on_input_outputs=1, outside_samples=[], outside_samples_total=0))
        assert it["tone"] == "warning" and "(대조한 칸이 모두 설계 밖 입력 행 4칸이다)" in it["note"]
        assert "없었다" not in it["note"]

    def test_given_but_unread_swuds_is_zero_comparisons_not_nothing_outside(self):
        """(리뷰 W5) SwUDS 를 지정했지만 출력 표를 못 읽었으면 '대조 0칸' — 정보 톤 '밖 없음' 이 아니다."""
        it = self._item({"uds_given": True, "derived_slots": 12, "outputs": 4, "outputs_with_statement": 0,
                         "not_compared_by_reason": {"no_design_statement:design_document_unread": 12}})
        assert it["tone"] == "warning" and it["value"] == "대조 0칸 — SwUDS 를 지정했지만 출력 표를 읽지 못했다 / 소스 계산 12칸"
        assert "'설계 범위 밖 없음' 이 아니다" in it["note"] and "SwUDS 를 지정했지만 출력 표를 못 읽음 12" in it["note"]
        it = self._item({"uds_given": True, "derived_slots": 3, "outputs_with_statement": 0,
                         "not_compared_by_reason": {"no_design_statement:not_in_design_outputs": 3}})
        assert it["tone"] == "warning" and it["value"].startswith("대조 0칸 — 설계 진술이 있는 출력 없음")

    def test_conflicting_rows_and_reasons(self):
        it = self._item(self._block(conflicting_design_rows=2, conflicting_design_slots=1, conflicting_design_outputs=1,
                                    not_compared_by_reason={"no_design_statement:range_unread:descending": 2,
                                                            "no_design_statement:ambiguous_design_table": 1}))
        assert "설계 행 갈림 1칸" in it["value"] and "'설계 행 갈림' 으로 따로 셌다" in it["note"]
        assert "출력 행 범위 칸을 못 읽음(descending) 2" in it["note"] and "같은 이름의 함수 표가 둘" in it["note"]

    def test_no_uds_says_so(self):
        none = self._item({"uds_given": False, "outputs_with_statement": 0})
        assert none["value"] == "대조 안 함" and "SwUDS 를 주지 않아" in none["note"]
        assert self._item(None) is None, "구판 산출물(블록 없음)은 말하지 않는다"

    def test_issue_action_says_it_is_a_design_fact_not_a_regeneration_deficit(self):
        from backend.services.issue_explainer import rule_action

        text = rule_action("disclosure:suts_design_check")
        assert "설계와 코드 중 틀린 쪽을 고친다" in text and "재생성으로 사라지지 않는다" in text
        assert "SwUDS 판독" in text, "대조 0칸(못 읽음)의 조치도 말한다"


# ── 끝에서 끝: 생성 문서의 열 · 품질 보고서 · 값 불변 ─────────────────────────
_C = """typedef unsigned char U8;
typedef unsigned int U16;
U8 g_mode;
U8 g_out;
U8 g_res;
void Fn(void)
{
    if (g_mode == 1U) { g_out = 7U; } else { g_out = 2U; }
}
U8 Get(U8 a)
{
    return (U8)(a + 1U);
}
void Use(void)
{
    if (Get(g_mode) > 5U) { g_res = 9U; } else { g_res = 1U; }
}
"""
_DOC = "(PRJ_SwUDS) Unit Design_v1.docx"


def _uds_tables():
    return {"Fn": _table([("g_mode", "U8", "0x00 ~ 0x01")], [("g_out", "U8", "0 ~ 5")]),
            "Get": _table([("a", "U8", "0 ~ 9")], [("Return", "U8", "0 ~ 10")]),
            "Use": _table([("g_mode", "U8", "0x00 ~ 0x01")], [("g_res", "U8", "0 ~ 5")])}


def _gen(tmp_path, name="u.xlsm", uds=True, uds_path=None, **kw):
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "m.c").write_text(_C, encoding="utf-8")
    path = uds_path or (_docx(tmp_path / _DOC, _uds_tables()) if uds else None)
    out = tmp_path / name
    # 기본 범위(scope="suds") — 설계 ID 가 있는 함수만
    res = suts.generate_suts(source_root=str(tmp_path / "src"), output_path=str(out), uds_path=path, **kw)
    return res, out


def _evidence(out):
    import openpyxl

    wb = openpyxl.load_workbook(out, read_only=True)
    try:
        rows = wb["Test Evidence"].iter_rows(values_only=True)
        head = list(next(rows))
        return head, [dict(zip(head, r, strict=False)) for r in rows]
    finally:
        wb.close()


def test_generated_document_carries_the_check_and_values_do_not_change(tmp_path):
    res, out = _gen(tmp_path)
    head, rows = _evidence(out)
    assert head[-2:] == ["Design Check", "Design Basis"]
    fn = {(r["Observable"], r["Expected"]): r for r in rows if r["Function"] == "Fn" and r["Status"] == "derived"
          and r["Basis"] != "unchanged_input"}
    assert fn[("g_out", 7)]["Design Check"] in (OUTSIDE, OUTSIDE_ON_INPUT)
    # g_mode == 1 is inside its design range 0~1 — that row is the design-vs-code disagreement itself
    assert any(r["Design Check"] == OUTSIDE and '"g_mode": 1' in r["Inputs JSON"] for r in fn.values())
    assert fn[("g_out", 2)]["Design Check"] == CONSISTENT and "[Output Parameters] No 1 `g_out`" in fn[("g_out", 2)]["Design Basis"]
    assert f"SwUDS {_DOC} · Fn" in fn[("g_out", 2)]["Design Basis"]
    get = [r for r in rows if r["Function"] == "Get" and r["Status"] == "derived"]
    assert all(r["Design Check"] == CONSISTENT for r in get if 0 <= r["Expected"] <= 10)
    assert all(r["Design Check"] == OUTSIDE_ON_INPUT for r in get if not 0 <= r["Expected"] <= 10), \
        "a 가 설계 0~9 밖인 행만 반환값이 0~10 밖으로 나간다"
    # 피호출 함수(Get)를 stub 한 Use — stub 값이 Get 의 설계 Return(0~10) 밖이면 설계 밖 입력, 안이면 stub 값에 기댄 약한 후보
    use = [r for r in rows if r["Function"] == "Use" and r["Status"] == "derived" and r["Basis"] != "unchanged_input"]
    stub_in = {r["Design Check"] for r in use if r["Expected"] == 9}
    assert stub_in <= {OUTSIDE_ON_INPUT, OUTSIDE_STUB_VALUE} and OUTSIDE_ON_INPUT in stub_in, stub_in
    assert any("(Get 설계 Return 0~10)" in (r["Design Basis"] or "") for r in use)
    dc = res["quality_report"]["design_check"]
    assert dc["uds_given"] and dc["outside_outputs"] == 1 and dc["outside_functions"] == 1
    assert dc["outside_samples"][0].startswith("Fn.g_out = 7")
    # 시트와 품질 보고서는 같은 unit 목록으로 같은 판정을 낸다(리뷰 R17 — 시트 쪽이 피호출 함수의 설계를 모르면 갈린다)
    sheet = Counter(check_bucket(r["Design Check"]) for r in rows if r["Design Check"] != "not_checked:not_derived")
    assert dict(sheet) == dc["by_check"]
    item = {i["key"]: i for i in build_disclosures("suts", res["quality_report"])}["suts_design_check"]
    assert item["tone"] == "warning"
    # 대조는 정보만 더한다 — 판정을 끈 생성과 앞 16 열(값 · 근거 · 입력)이 칸마다 같다
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(suts.DesignChecker, "classify", lambda self, u, q, v: {"check": "off", "basis": "off"})
        _res2, out2 = _gen(tmp_path, "off.xlsm")
    _head2, rows2 = _evidence(out2)
    strip = [h for h in head if h not in ("Design Check", "Design Basis")]
    assert [[r[h] for h in strip] for r in rows] == [[r[h] for h in strip] for r in rows2]
    assert {r["Design Check"] for r in rows2} == {"off"}


def test_swuds_not_given_or_unread_is_said(tmp_path):
    """(리뷰 R12 · W5) 지정하지 않음 → '대조 안 함', 지정했지만 못 읽음 → '대조 0칸 — 출력 표를 읽지 못했다'(경고)."""
    # 설계 ID 가 없으니 전 함수 범위(scope="all")로 — 소스 계산 칸이 있어야 '대조 안 함 · 0칸' 이 뜻을 갖는다
    res, out = _gen(tmp_path / "none", uds=False, scope="all")
    dc = res["quality_report"]["design_check"]
    assert dc["derived_slots"] > 0 and dc["uds_given"] is False and dc["outputs_with_statement"] == 0
    item = {i["key"]: i for i in build_disclosures("suts", res["quality_report"])}["suts_design_check"]
    assert item["value"] == "대조 안 함"
    # (2차 W-C, M15) 주지 않은 SwUDS 는 '지정했지만 못 읽음' 이 아니다 — 시트 칸 · 사유 둘 다
    assert set(dc["not_compared_by_reason"]) <= {"no_design_statement:no_design_document", "not_checked:unchanged_input",
                                                  "not_checked:value_not_integer"}
    _head, rows = _evidence(out)
    assert {r["Design Check"] for r in rows if r["Status"] == "derived" and r["Basis"] != "unchanged_input"} == \
        {"no_design_statement:no_design_document"}
    (tmp_path / "bad").mkdir()
    broken = tmp_path / "bad" / _DOC
    broken.write_bytes(b"not a zip")
    res, out = _gen(tmp_path / "bad", uds_path=str(broken), scope="all")
    dc = res["quality_report"]["design_check"]
    assert dc["uds_given"] is True and dc["outputs_with_statement"] == 0
    assert dc["not_compared_by_reason"].get("no_design_statement:design_document_unread", 0) > 0
    item = {i["key"]: i for i in build_disclosures("suts", res["quality_report"])}["suts_design_check"]
    assert item["tone"] == "warning" and item["value"].startswith("대조 0칸 — SwUDS 를 지정했지만 출력 표를 읽지 못했다")
    _head, rows = _evidence(out)
    assert {r["Design Check"] for r in rows if r["Status"] == "derived" and r["Basis"] != "unchanged_input"} == \
        {"no_design_statement:design_document_unread"}


def test_hsis_range_is_used_with_its_own_text_when_the_swuds_row_says_no_range(tmp_path, monkeypatch):
    """SwUDS 출력 행이 범위를 적지 않은 출력은 HSIS SW 값 범위로 — 근거 칸이 HSIS 칸 원문과 SwUDS 행이 범위를 적지 않았다는 사실을
    함께 적는다(읽은 수만 적으면 문서 오타인지 판독 오류인지 가를 수 없다)."""
    from generators import sts

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "h.c").write_text(
        "typedef unsigned char U8;\ntypedef unsigned int U16;\nU8 g_k;\nU8 g_hs;\n"
        "void H(void)\n{\n    if (g_k == 1U) { g_hs = 5U; } else { g_hs = 1U; }\n}\n", encoding="utf-8")
    uds = _docx(tmp_path / _DOC, {"H": _table([("g_k", "U8", "0x00 ~ 0x01")], [("g_hs", "U8", "N/A")])})
    hsis = tmp_path / "HSIS.xlsx"
    hsis.write_bytes(b"stub")             # 판독은 아래 stub — 파일은 열 수 있어야 한다
    monkeypatch.setattr(sts, "_load_hsis_signals", lambda _p: {"signals": [
        {"sw_var_name": "g_hs", "value_range": "0x00  ~ 0x03", "related_id": ""}]})
    out = tmp_path / "h.xlsm"
    suts.generate_suts(source_root=str(tmp_path / "src"), output_path=str(out), uds_path=uds, hsis_path=str(hsis))
    _head, rows = _evidence(out)
    hs = [r for r in rows if r["Observable"] == "g_hs" and r["Status"] == "derived" and r["Basis"] != "unchanged_input"]
    checks = {r["Expected"]: r["Design Check"] for r in hs}
    # 5 는 HSIS 0~3 밖(행이 넣은 다른 입력에 설계 범위가 없으면 약한 후보), 1 은 안
    assert checks[1] == CONSISTENT and checks[5] in (OUTSIDE, OUTSIDE_UNDESIGNED_INPUT), checks
    assert all("HSIS · `g_hs` SW Value Range `0x00 ~ 0x03` → 0~3" in r["Design Basis"] for r in hs)
    assert all("No 1 `g_hs` 은 범위를 적지 않았다" in r["Design Basis"] for r in hs)


def test_worker_materialized_swuds_names_the_original_document(tmp_path, monkeypatch):
    """(리뷰 C1) 파일 접근기(Cloudium worker)만 읽을 수 있는 SwUDS 는 실행마다 다른 이름의 임시 파일로 꺼내진다 — 근거 칸 · 공시
    표본이 그 임시 이름을 적으면 웹 생성 ≠ 스크립트 생성, 웹 ≠ 웹이다. 두 번의 접근기 경유 생성과 로컬 경로 생성이 같은 시트 ·
    같은 요약을 내고, 근거는 지정한 원래 문서를 적는다."""
    from backend.services import file_resolver

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.c").write_text(_C, encoding="utf-8")
    local = _docx(tmp_path / _DOC, _uds_tables())
    remote = str(tmp_path / "worker_only" / _DOC)       # 로컬에 없다 — 접근기만 연다
    inner = file_resolver.get_resolver()

    class WorkerOnly:
        mode = "cloudium"

        def __getattr__(self, name):
            return getattr(inner, name)

        def is_file(self, p):
            return True if str(p) == remote else inner.is_file(p)

        def read_bytes(self, p):
            return Path(local).read_bytes() if str(p) == remote else inner.read_bytes(p)

    monkeypatch.setattr(file_resolver, "get_resolver", lambda: WorkerOnly())
    made: list = []
    real_ntf = suts.tempfile.NamedTemporaryFile

    def spy(*a, **k):
        fh = real_ntf(*a, **k)
        made.append(Path(fh.name).name)
        return fh

    monkeypatch.setattr(suts.tempfile, "NamedTemporaryFile", spy)

    def run(path, name):
        before = len(made)
        out = tmp_path / name
        res = suts.generate_suts(source_root=str(tmp_path / "src"), output_path=str(out), uds_path=path)
        return res["quality_report"]["design_check"], _evidence(out)[1], [m for m in made[before:] if m.startswith("UDS")]

    s1, rows1, tmp1 = run(remote, "web1.xlsm")
    s2, rows2, tmp2 = run(remote, "web2.xlsm")
    s0, rows0, tmp0 = run(local, "script.xlsm")
    assert tmp1 and tmp2 and not set(tmp1) & set(tmp2) and not tmp0, "접근기 경유는 실행마다 다른 임시 이름으로 꺼냈다"
    assert rows1 == rows2 == rows0, "웹 = 웹 = 스크립트(시트 칸 단위)"
    assert s1 == s2 == s0
    basis = [r["Design Basis"] for r in rows1 if r["Design Check"] in (CONSISTENT, OUTSIDE)]
    assert basis and all(f"SwUDS {_DOC} · " in b for b in basis)
    assert not any(t in b for b in basis for t in tmp1) and not any("UDS(입출력)_" in b for b in basis)
    assert all(_DOC in x for x in s1["outside_samples"])


# ── 실제 HDPDM01: 설계서 값 목록 vs 소스 상수 ──────────────────────────────
_HD_UDS = Path(r"D:/Project/devops/260105/docs/(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")
_HD_SRC = Path(r"D:/Project/Ados/PDS64_RD/Sources/SYSTEM/SysOptionCtrl_PDS.c")


@pytest.mark.skipif(not (_HD_UDS.is_file() and _HD_SRC.is_file()), reason="HDPDM01 SwUDS / 소스가 이 PC 에 없다")
def test_real_hdpdm01_over_position_disagrees_with_its_design():
    """실제 설계서 · 실제 소스(읽기만). 설계 값은 문서에서, 코드 값은 `#define` 을 이 시험이 따로 읽는다(생성기와 다른 경로)."""
    io = load_uds_unit_io(str(_HD_UDS))
    text = _HD_SRC.read_text(encoding="utf-8", errors="replace")
    const = {m.group(1): int(m.group(2)) for m in re.finditer(r"#define\s+(\w+)\s+\(\s*\(\s*[SU]16\s*\)\s*\(\s*(\d+)U?\s*\)", text)}
    assert const["s16s_FRONT_OVER_POS"] == 2472 and const["s16s_REAR_OVER_POS"] == 2253
    c = DesignChecker()
    for fn in ("g_SysOptionCtrl_Reset", "s_DeviceOptionSet_DoorAngle"):
        unit = {"fid": fn, "name": fn, "uds_output_rows": uds_output_rows(resolve_unit_io(io, fn), io)}
        st = c.statement(unit, "s16g_SysOptCtrl_OverPos")
        assert st["status"] == "stated" and st["values"] == [0, 2268, 2470] and st["text"] == "0, 2470, 2268"
        for v in (const["s16s_FRONT_OVER_POS"], const["s16s_REAR_OVER_POS"]):
            assert c.classify(unit, _seq({"s16g_SysOptCtrl_OverPos": v}), "s16g_SysOptCtrl_OverPos")["check"] == OUTSIDE
    unit = {"fid": "f", "name": "s_DeviceOptionSet_DoorAngle",
            "uds_output_rows": uds_output_rows(resolve_unit_io(io, "s_DeviceOptionSet_DoorAngle"), io)}
    assert c.statement(unit, "u16g_SysOptCtrl_OverOpenDeg")["values"] == [0, 68, 73]
    assert c.classify(unit, _seq({"u16g_SysOptCtrl_OverOpenDeg": 68}), "u16g_SysOptCtrl_OverOpenDeg")["check"] == CONSISTENT
    assert c.classify(unit, _seq({"u16g_SysOptCtrl_OverOpenDeg": const["u16s_REAR_OVER_OPEN_DEG"]}),
                      "u16g_SysOptCtrl_OverOpenDeg")["check"] == OUTSIDE
