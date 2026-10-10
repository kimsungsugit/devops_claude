"""R65 — SwUDS 문서 판독(사용자 방향 10-06 "입력문서를 제대로 읽지 못하면 아무것도 진행할 수가 없어").

R63 판독 실측이 찾은 손실과 이번 라운드의 대조(옛 판독 ↔ 새 판독, 두 문서의 모든 (Type, Value Range) 쌍)에서 드러난 오독:

- 머리말 `u8s_DataValidCheck(New)` — 표시까지 이름에 넣어 HDPDM01 18 함수가 설계 ID · 입출력 표 · 범위 · ASIL 을 잃었다.
  머리말 오타 2 개는 표 `Name` 행이 소스의 실제 이름이었다(`g_DrvIn_MotorPostion` · `u16s_MotorShortBattA1_Check`).
- 번호 칸이 세로 병합된 파라미터 행(HDPDM01 10 행), `pst_Queue-> ast_Queue` 의 공백(KJPDS02_PV 11 행), 이름 칸의 식.
- Value Range: HDPDM01 는 부호 있는 전폭을 `0x7FFF ~ 0x8000`(최대 ~ 최소)로 적는다(323 행) — 옛 판독은 32767 ~ 32768
  로 읽어 '범위 충돌' 로 공시했다. `0xFF10 ~ 0x00F0`(S16) · 값 목록 `0, 5, 15` · `array 0x00 ~ 0xFF` 는 못 읽었다.
- `p->m` 으로 적힌 파라미터의 범위가 unit 이름 `p[0].m` 과 맞지 않아 한 번도 조회되지 않았다(감사 #18 — PV 301 행).
"""
from __future__ import annotations

import zipfile

import pytest

from generators.uds_design_ids import load_uds_design_ids, read_design_heading, resolve_design_id
from generators.uds_unit_io import (
    clean_param_name,
    document_int_type,
    load_uds_unit_io,
    parse_value_range,
    read_value_range,
    resolve_unit_io,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(body_xml: str, tmp_path, name: str = "uds.docx") -> str:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml",
                    f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body_xml}</w:body></w:document>')
    return str(p)


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _tc(text: str, span: int = 1, vmerge: str = "") -> str:
    pr = ""
    if span > 1 or vmerge:
        pr = "<w:tcPr>" + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "") + (
            '<w:vMerge w:val="restart"/>' if vmerge == "restart" else "<w:vMerge/>" if vmerge else "") + "</w:tcPr>"
    return f"<w:tc>{pr}<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(c if c.startswith("<w:tc>") else _tc(c) for c in cells) + "</w:tr>"


def _table(fid: str, name: str, inputs, outputs=(), name_row: str = "", extra: str = "") -> str:
    rows = _row("[ Function Information ]") + _row("ID", fid) + _row("Name", name_row or name) + extra
    rows += _row("[ Input Parameters ]") + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    rows += "".join(r if isinstance(r, str) else _row(*r) for r in inputs)
    rows += _row("[ Output Parameters ]") + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    rows += "".join(r if isinstance(r, str) else _row(*r) for r in outputs)
    rows += _row("[ Logic Diagram ]", "")
    return f"<w:tbl>{rows}</w:tbl>"


class TestReadValueRange:
    @pytest.mark.parametrize("text, typ, want", [
        ("0x00 ~ 0x01", "U8", {"range": (0, 1)}),
        ("0x8000 ~ 0x7FFF", "S16", {"range": (-32768, 32767)}),
        # HDPDM01: 부호 있는 전폭을 최대 ~ 최소로 — 옛 판독은 (32767, 32768)
        ("0x7FFF ~ 0x8000", "S16", {"range": (-32768, 32767)}),
        ("0x7F ~ 0x80", "S8", {"range": (-128, 127)}),
        ("0x7FFFFFFF ~ 0x80000000", "S32", {"range": (-2147483648, 2147483647)}),
        ("0xFFFF ~ 0x0000", "U16", {"range": (0, 65535)}),
        # KJPDS02_PV LIN 가속도: 같은 행의 S16 이 2의 보수를 정한다
        ("0xFF10 ~ 0x00F0", "S16", {"range": (-240, 240)}),
        ("0xFE ~ 0x02", "S8", {"range": (-2, 2)}),
        ("0xFFFC~0x0000", "S16", {"range": (-4, 0)}),
        # 타입이 부호를 말하지 않아도 괄호 십진 주석이 같은 값을 말하면 읽는다
        ("0xFF10 ~ 0x00F0 (-240~240)", "", {"range": (-240, 240)}),
        ("0x00, 0x01", "U8", {"range": (0, 1)}),                         # 연속 값 목록 = 범위
        ("0, 5, 15", "U16", {"values": [0, 5, 15]}),
        ("0x0000, 0x08DC, 0x09A6", "S16", {"values": [0, 2268, 2470]}),
        ("array 0x00 ~ 0xFF", "U8", {"range": (0, 255)}),
        ("Array 0x0000 ~ 0x87E7", "U16", {"range": (0, 34791)}),
        ("0x00000000~0x FFFFFFFF", "U32", {"range": (0, 4294967295)}),
        ("0 ~ FFFF", "U16", {"range": (0, 65535)}),
        ("0x00~0xFF(0x00제외)", "U8", {"range": (1, 255)}),
        ("1,000 ~ 2,000", "", {"range": (1000, 2000)}),
        ("N/A", "U8", {}),
        ("", "U8", {}),
    ])
    def test_reads(self, text, typ, want):
        got = read_value_range(text, typ)
        assert {k: (tuple(v) if k == "range" else v) for k, v in got.items() if k in ("range", "values")} == want

    @pytest.mark.parametrize("text, typ, why", [
        ("0x00", "U8", "single_value"),                                   # 범위인지 기본값인지 모른다
        ("0x0044,", "U16", "single_value"),
        ("0x00 ~ 0x40, 0x80", "U8", "multiple_intervals"),
        ("0x8000 ~ 0xFFFF, 0x0001~0x7FFF", "S16", "multiple_intervals"),
        # 부호 타입이 없는 내림차순은 적지 않은 범위를 만든다(뒤집으면 240 ~ 65296)
        ("0xFF10 ~ 0x00F0", "U16", "descending"),
        ("0xFF10 ~ 0x00F0", "", "descending"),
        ("0x00F0 ~ 0x80F0", "S16", "signed_hex_out_of_order"),           # 적힌 순서는 오름차순 — 부호 크기 표기 후보
        ("0x0082~0x0064", "S16", "descending"),
        ("0x7FFFFFF~ 0x80000000", "S32", "digit_count_differs"),          # F 일곱 — 오타 후보
        ("0x7FFFF ~ 0x8000", "S16", "outside_document_type"),
        ("0x0000 ~ 0xFFFF", "U8", "outside_document_type"),
        ("0x00000000 ~ 40xFFFFFFFF", "U32", "not_a_number"),
        ("10 ~ FF", "U8", "hex_without_prefix"),                           # 10 이 16 일 수 있다
        ("U16", "U16", "type_in_range_column"),
        ("0x01~0x07(0x05제외)", "U8", "excludes_inner_value"),
        ("0xFF10 ~ 0x00F0 (-200~200)", "", "annotation_disagrees"),
        ("Array", "enum", "no_value"),
        ("9 to 16V", "", "not_a_number"),
    ])
    def test_unread_has_a_reason_never_a_guess(self, text, typ, why):
        got = read_value_range(text, typ)
        assert got.get("unread") == why and "range" not in got and "values" not in got

    @pytest.mark.parametrize("text, want", [
        ("0x8000 ~ 0x7FFF", (-32768, 32767)), ("0x0000U ~ 0xFFFFU", (0, 65535)), ("0 ... 10", (0, 10)),
        ("0x7FFFFFF~ 0x80000000", (134217727, 2147483648)), ("0xFFFF ~ 0x0000", None), ("10 ~ 5", None),
        ("0, 5, 15", None), ("0x00, 0x01", (0, 1)),
    ])
    def test_untyped_parse_keeps_the_r74_contract(self, text, want):
        """타입 없는 `parse_value_range`(HSIS 도 쓴다)는 정확히 전폭인 쌍만 부호로 읽고, 내림차순을 뒤집지 않는다."""
        assert parse_value_range(text) == want

    @pytest.mark.parametrize("typ, want", [
        ("U8", (False, 8)), ("S16", (True, 16)), ("uint32_t", (False, 32)), ("int8_t", (True, 8)), ("sint16", (True, 16)),
        ("const U16", (False, 16)), ("U8[8]", (False, 8)), ("U8*", None), ("enum", None), ("byte", (False, 8)),
        ("unsigned short", (False, 16)), ("SINT16", (True, 16)), ("int", None), ("bool", None), ("", None),
    ])
    def test_document_type(self, typ, want):
        assert document_int_type(typ) == want


class TestDesignHeadings:
    @pytest.mark.parametrize("text, name, status", [
        ("SwUFn_0101: main", "main", "plain"),
        ("SwUFn_0916: u8s_DataValidCheck(New)", "u8s_DataValidCheck", "marked"),
        ("SwUFn_1424: s_DoorState_TipToRun_Detection(NEW)", "s_DoorState_TipToRun_Detection", "marked"),
        ("SwUFn_1007: s_RemoteSleepCheckTimer(삭제)", "s_RemoteSleepCheckTimer", "deleted"),
        ("SwUFn_0101: main 함수", "main", "plain"),
        ("SwUFn_0101: main-old", "main", "unread"),
        ("SwUFn_0101: 3abc", "", "unread"),
    ])
    def test_heading(self, text, name, status):
        h = read_design_heading(text)
        assert h is not None and (h["name"], h["status"]) == (name, status)
        assert read_design_heading("본문 줄") is None

    def test_marked_heading_maps_and_deleted_does_not(self, tmp_path):
        body = (_para("SwUFn_0916: u8s_DataValidCheck(New)") + _table("SwUFn_0916", "u8s_DataValidCheck", [("1", "a", "U8", "0x00 ~ 0x01")])
                + _para("SwUFn_1007: s_Gone(삭제)") + _table("SwUFn_1007", "s_Gone", [("1", "b", "U8", "0x00 ~ 0x01")]))
        path = _docx(body, tmp_path)
        io, ids = load_uds_unit_io(path), load_uds_design_ids(path)
        assert resolve_unit_io(io, "u8s_DataValidCheck")["inputs"] == ["a"]
        assert resolve_design_id(ids, "u8s_DataValidCheck") == "SwUFn_0916"
        assert resolve_unit_io(io, "s_Gone") is None and resolve_design_id(ids, "s_Gone") == ""
        assert io["reading"]["marked_headings"] == ["SwUFn_0916: u8s_DataValidCheck(New)"]
        assert io["reading"]["deleted_headings"] == ["SwUFn_1007: s_Gone(삭제)"]
        assert ids["deleted"] == ["SwUFn_1007: s_Gone(삭제)"]

    def test_name_row_is_an_alias_when_the_heading_is_misspelled(self, tmp_path):
        """HDPDM01: 머리말 `u16_sMotorShortBattA1_Check` · 표 Name `u16s_MotorShortBattA1_Check`(소스의 이름)."""
        body = _para("SwUFn_1207: u16_sMotorShortBattA1_Check") + _table(
            "SwUFn_1207", "u16_sMotorShortBattA1_Check", [], [("1", "return", "U16", "0x0000 ~ 0xFFFF")],
            name_row="u16s_MotorShortBattA1_Check")
        path = _docx(body, tmp_path)
        src = ["u16s_MotorShortBattA1_Check"]                        # 소스 함수 목록으로 확인한 별칭만 조회된다
        io, ids = load_uds_unit_io(path, source_functions=src), load_uds_design_ids(path, source_functions=src)
        assert resolve_unit_io(load_uds_unit_io(path), "u16s_MotorShortBattA1_Check") is None   # 확인 안 한 맵
        assert resolve_unit_io(io, "u16s_MotorShortBattA1_Check")["outputs"] == ["return"]
        assert resolve_design_id(ids, "u16s_MotorShortBattA1_Check") == "SwUFn_1207"
        assert resolve_design_id(ids, "u16_sMotorShortBattA1_Check") == "SwUFn_1207"   # 머리말 이름도 그대로
        assert io["reading"]["name_row_aliases"] == ["u16_sMotorShortBattA1_Check ← 표 Name `u16s_MotorShortBattA1_Check`"]

    def test_alias_is_not_used_when_it_names_another_table_or_two_tables_claim_it(self, tmp_path):
        body = (_para("SwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", [("1", "a", "U8", "0 ~ 1")], name_row="f_b")
                + _para("SwUFn_0002: f_b") + _table("SwUFn_0002", "f_b", [("1", "b", "U8", "0 ~ 1")])
                + _para("SwUFn_0003: f_c") + _table("SwUFn_0003", "f_c", [("1", "c", "U8", "0 ~ 1")], name_row="f_x")
                + _para("SwUFn_0004: f_d") + _table("SwUFn_0004", "f_d", [("1", "d", "U8", "0 ~ 1")], name_row="f_x"))
        path = _docx(body, tmp_path)
        io, ids = load_uds_unit_io(path), load_uds_design_ids(path)
        assert resolve_unit_io(io, "f_b")["inputs"] == ["b"]                # 머리말 f_b 의 표 — 별칭이 가로채지 않는다
        assert resolve_unit_io(io, "f_x") is None and resolve_design_id(ids, "f_x") == ""
        assert sorted(io["reading"]["alias_conflicts"]) == ["f_b(다른 머리말 이름)", "f_x(f_c·f_d 두 표)"]

    def test_case_only_difference_is_not_an_alias(self, tmp_path):
        body = _para("SwUFn_1201: g_DiagCtrlMain") + _table("SwUFn_1201", "g_DiagCtrlMain", [], name_row="G_DiagCtrlMain")
        io = load_uds_unit_io(_docx(body, tmp_path))
        assert io["aliases"] == {} and resolve_unit_io(io, "g_DiagCtrlMain") is not None


class TestParameterRows:
    def test_vertically_merged_number_cell_row_is_read(self, tmp_path):
        """HDPDM01 `s_BuzzerStateFlashing_Twice`: 번호 칸이 위 행과 세로 병합돼 비어 있던 행 4 개를 잃었다."""
        rows = [_row(_tc("1", vmerge="restart"), "u8g_A", "U8", "0x00 ~ 0x03", "0", "d"),
                _row(_tc("", vmerge="continue"), "u8g_B", "U8", "0x00 ~ 0x01", "0", "d"),
                ("2", "u8g_C", "U8", "0x00 ~ 0x01", "0", "d"),
                _row("", "", "", "", "", "")]                                   # 빈 행은 행이 아니다
        io = load_uds_unit_io(_docx(_para("SwUFn_0001: f") + _table("SwUFn_0001", "f", rows), tmp_path))
        assert resolve_unit_io(io, "f")["inputs"] == ["u8g_A", "u8g_B", "u8g_C"]
        assert io["reading"]["rows_continued"] == 1 and io["reading"]["param_rows"] == 3

    def test_grid_columns_follow_the_header(self, tmp_path):
        """번호 칸이 그리드 두 열을 덮는 양식 — 머리행과 데이터 행을 같은 그리드 좌표로 읽는다. 칸 하나가 행 전체를 덮는
        행(`if( … )`)은 이름이 아니다."""
        head = _row(_tc("No", span=2), "Name", "Type", "Value Range", "Reset Value", "Description")
        data = _row(_tc("1", span=2), "u8g_A", "U8", "0x00 ~ 0x01", "0", "d")
        expr = _row(_tc("6", span=2), _tc("if( sid_supported_flag == 1U )", span=5))
        rows = (_row("[ Function Information ]") + _row(_tc("ID", span=2), "SwUFn_0001")
                + _row(_tc("ASIL", span=2), "B") + _row("[ Input Parameters ]") + head + data
                + _row("[ Output Parameters ]") + head + expr + _row("[ Logic Diagram ]", ""))
        io = load_uds_unit_io(_docx(_para("SwUFn_0001: f") + f"<w:tbl>{rows}</w:tbl>", tmp_path))
        rec = resolve_unit_io(io, "f")
        assert rec["inputs"] == ["u8g_A"] and rec["outputs"] == []
        assert rec["param_info"]["u8g_A"]["range"] == [0, 1]
        assert rec["asil"] == "B"                                   # 라벨이 두 열을 덮어도 값은 라벨이 아닌 첫 칸
        assert io["reading"]["rows_unread"] == [
            {"function": "f", "section": "out", "text": "if( sid_supported_flag == 1U )",
             "reason": "name_not_a_designator"}]

    def test_names_are_designators(self, tmp_path):
        rows = [("1", "pst_Queue-> ast_Queue[x].u8_Data", "U8", "0x00 ~ 0xFF", "0", "d"),
                ("2", "8g_SysEepromCtrl_InLineModSpdChange_F", "U8", "0x00 ~ 0x01", "0", "d"),
                ("3", "u8g_A u8g_B", "U8", "0x00 ~ 0x01", "0", "d")]
        io = load_uds_unit_io(_docx(_para("SwUFn_0001: f") + _table("SwUFn_0001", "f", rows), tmp_path))
        assert resolve_unit_io(io, "f")["inputs"] == ["pst_Queue->ast_Queue.u8_Data"]
        assert [(r["text"], r["reason"]) for r in io["reading"]["rows_unread"]] == [
            ("8g_SysEepromCtrl_InLineModSpdChange_F", "name_not_identifier"), ("u8g_A u8g_B", "name_not_a_designator")]
        assert clean_param_name("p -> m") == "p->m"

    def test_param_info_carries_values_and_unread_reasons_with_the_text(self, tmp_path):
        rows = [("1", "u16g_Opt", "U16", "0, 5, 15", "0", "d"), ("2", "s16g_Pos", "S16", "0x7FFF ~ 0x8000", "0", "d"),
                ("3", "u8g_One", "U8", "0x22", "0", "d"), ("4", "u8g_Na", "U8", "N/A", "0", "d")]
        io = load_uds_unit_io(_docx(_para("SwUFn_0001: f") + _table("SwUFn_0001", "f", rows), tmp_path))
        info = resolve_unit_io(io, "f")["param_info"]
        assert info["u16g_Opt"] == {"type": "U16", "values": [0, 5, 15], "range_text": "0, 5, 15"}
        assert info["s16g_Pos"]["range"] == [-32768, 32767]
        assert info["u8g_One"] == {"type": "U8", "range_unread": "single_value", "range_text": "0x22"}
        assert info["u8g_Na"] == {"type": "U8"}
        r = io["reading"]
        assert (r["range_read"], r["values_read"], r["range_unread_by_reason"]) == (1, 1, {"single_value": 1})
        assert r["range_notation"] == {"signed_hex": 1, "descending_full_width": 1}
        assert r["range_unread_samples"] == {"single_value": ["f.u8g_One `0x22`"]}

    def test_unreadable_document_says_why(self, tmp_path):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"not a zip")
        io = load_uds_unit_io(str(bad))
        assert io["by_name"] == {} and io["reading"]["read_error"].startswith("BadZipFile")
        assert load_uds_unit_io(str(tmp_path / "none.docx"))["reading"] == {"read_error": "file_not_found"}


class TestSutsUsesTheReading:
    def test_pointer_member_names_find_their_design_range(self):
        """감사 #18: 설계서 `p->m` 과 unit `p[0].m` 이 같은 객체다."""
        from generators.suts import _unit_uds_param_info

        rec = {"param_info": {"pt_Ctx->u8_Mode": {"type": "U8", "range": [0, 3]}, "u8g_A": {"range": [0, 1]}}}
        got = _unit_uds_param_info(rec, ["pt_Ctx[0].u8_Mode", "u8g_A", "u8g_B"])
        assert got == {"pt_Ctx[0].u8_Mode": {"type": "U8", "range": [0, 3]}, "u8g_A": {"range": [0, 1]}}

    def test_design_value_list_bounds_the_input_like_enumerators(self):
        from generators.suts import _boundary_domains, generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["u16g_Opt"], "output_vars": [], "param_types": {"u16g_Opt": "U16"},
             "uds_param_info": {"u16g_Opt": {"type": "U16", "values": [0, 5, 15], "range_text": "0, 5, 15"}}}
        seqs = generate_sequences(u, type_cache={})
        assert u["bounds_source"]["u16g_Opt"] == "uds_values"
        vals = {str((s.get("inputs") or {}).get("u16g_Opt")) for s in seqs}
        assert {"0", "5", "15"} <= vals and "7" not in vals             # 목록 사이 정수는 설계 값이 아니다
        dom = _boundary_domains(u, ["u16g_Opt"], {"u16g_Opt": "uint16_t"},
                                {"u16g_Opt": {"min": 0, "max": 15, "mid": 5}}, set())
        assert dom == {"u16g_Opt": [0, 5, 15]}

    def test_unread_design_range_is_recorded_and_the_type_width_is_used(self):
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["u8g_One"], "output_vars": [], "param_types": {"u8g_One": "U8"},
             "uds_param_info": {"u8g_One": {"type": "U8", "range_unread": "single_value", "range_text": "0x22"}}}
        generate_sequences(u, type_cache={})
        assert u["uds_range_unread"] == {"u8g_One": "single_value"} and u["bounds_source"]["u8g_One"] == "type"

    def test_value_list_the_declaration_cannot_hold_is_a_conflict(self):
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["k"], "output_vars": [], "param_types": {"k": "U8"},
             "uds_param_info": {"k": {"values": [0, 300, 600], "range_text": "0, 300, 600"}}}
        generate_sequences(u, type_cache={})
        assert u["bounds_source"]["k"] == "type" and u["range_conflicts"] == ["k(SwUDS 0~600 vs uint8_t) ← 원문 `0, 300, 600`"]

    def test_mcdc_domain_takes_the_design_values(self):
        from generators.mcdc_design import _apply_design_range

        unit = {"uds_param_info": {"k": {"values": [0, 5, 15]}}}
        dom = {"min": 0, "max": 65535}
        _apply_design_range(unit, "k", dom)
        assert (dom["min"], dom["max"], dom["values"], dom["constraint_source"]) == (0, 15, [0, 5, 15], "uds_values")
        dom2 = {"min": 0, "max": 3}
        _apply_design_range(unit, "k", dom2)
        assert dom2["design_range_conflict"]["reason"] == "values_outside_declaration" and "values" not in dom2

    def test_summary_and_disclosure(self):
        from generators.suts import summarize_uds_reading
        from report_gen.generation_disclosures import build_disclosures

        io = {"by_name": {"u8s_DataValidCheck": {}}, "aliases": {"g_X": "g_Y"}, "aliases_checked": True, "reading": {
            "headings": 3, "tables": 2, "functions": 2, "param_rows": 9, "rows_continued": 1, "range_read": 6,
            "values_read": 1, "marked_headings": ["SwUFn_0916: u8s_DataValidCheck(New)"],
            "deleted_headings": ["SwUFn_1007: s_Gone(삭제)"], "name_row_aliases": ["g_Y ← 표 Name `g_X`"],
            "rows_unread": [{"function": "f", "section": "out", "text": "8g_A", "reason": "name_not_identifier"}],
            "range_unread_by_reason": {"single_value": 2}, "range_unread_samples": {"single_value": ["f.k `0x22`"]},
            "range_notation": {"signed_hex": 3}}}
        units = [{"name": "u8s_DataValidCheck", "uds_range_unread": {"k": "single_value"},
                  "uds_param_info": {"k": {"range_text": "0x22"}}, "bounds_source": {"k": "type", "o": "uds_values"}},
                 {"name": "g_X"}]
        s = summarize_uds_reading(io, units, True)
        assert s["units_via_marked_heading"] == ["u8s_DataValidCheck"] and s["units_via_name_row_alias"] == ["g_X"]
        assert s["unit_vars_range_unread"] == {"single_value": 1} and s["unit_vars_uds_values"] == 1
        assert summarize_uds_reading(None, units, False) == {"given": False}
        items = [it for it in build_disclosures("suts", {"uds_reading": s}) if it["key"] == "suts_uds_reading"]
        assert len(items) == 1 and items[0]["tone"] == "warning"
        note = items[0]["note"]
        for want in ("`SwUFn_0916: u8s_DataValidCheck(New)`", "g_Y ← 표 Name `g_X`", "삭제 표시", "`8g_A`",
                     "값 하나(범위인지 기본값인지 문서가 말하지 않음) 2", "`lo ~ hi` 꼴로 고치면"):
            assert want in note, want
        unread = build_disclosures("suts", {"uds_reading": {"given": True, "read": False, "read_error": "BadZipFile: x"}})
        assert [it["value"] for it in unread if it["key"] == "suts_uds_reading"] == ["읽지 못함"]
        assert not [it for it in build_disclosures("suts", {"uds_reading": {"given": False}})
                    if it["key"] == "suts_uds_reading"]


class TestReviewRound1:
    """deep 리뷰 1차(W1~W5 · I1~I8) — 각 반례가 이제 지어낸 값을 내지 않는다."""

    def test_w1_alias_naming_any_heading_is_not_used(self, tmp_path):
        """별칭이 표 없는 머리말 · 삭제 머리말의 이름이면 쓰지 않는다(그 함수는 자기 머리말이 있다)."""
        body = (_para("SwUFn_0009: f_x")                                              # 표 없는 머리말
                + _para("SwUFn_0010: f_y") + _table("SwUFn_0010", "f_y", [("1", "a", "U8", "0 ~ 1")], name_row="f_x")
                + _para("SwUFn_0011: f_z(삭제)")
                + _para("SwUFn_0012: f_w") + _table("SwUFn_0012", "f_w", [("1", "b", "U8", "0 ~ 1")], name_row="f_z"))
        path = _docx(body, tmp_path)
        io, ids = load_uds_unit_io(path), load_uds_design_ids(path)
        assert resolve_unit_io(io, "f_x") is None and resolve_design_id(ids, "f_x") == "SwUFn_0009"
        assert resolve_unit_io(io, "f_z") is None and resolve_design_id(ids, "f_z") == ""
        assert io["aliases"] == ids["aliases"] == {}
        assert io["reading"]["alias_conflicts"] == ids["alias_conflicts"] == ["f_x(다른 머리말 이름)", "f_z(다른 머리말 이름)"]

    def test_w1_alias_whose_heading_is_a_source_function_is_dropped_by_the_caller(self):
        from generators.uds_design_ids import restrict_aliases

        ids = {"by_name": {"f_y": "SwUFn_0010"}, "aliases": {"f_x": "f_y"}}
        assert resolve_design_id(restrict_aliases(ids, ["f_x", "F_Y"]), "f_x") == ""     # f_y 도 소스 함수 — 표는 f_y 의 것일 수 있다
        assert resolve_design_id(restrict_aliases(ids, ["f_x"]), "f_x") == "SwUFn_0010"
        assert ids["aliases"] == {"f_x": "f_y"}                                          # 캐시된 원본은 그대로
        assert restrict_aliases(ids, ["f_y"])["alias_dropped_source"] == ["f_x→f_y"]

    @pytest.mark.parametrize("text, status", [
        ("SwUFn_0001: f_x (삭제)", "deleted"), ("SwUFn_0001: f_x(삭제됨)", "deleted"), ("SwUFn_0001: f_x (폐기)", "deleted"),
        ("SwUFn_0001: f_x(수정)", "marked"), ("SwUFn_0001: f_x (New)", "marked"), ("SwUFn_0001: f_x(old)", "marked"),
        # HDPDM01 실데이터: 옮긴 설계 메모는 이름을 지킨다(옛 판독도 매핑했다) · 삭제 낱말이 섞인 표시는 삭제
        ("SwUFn_1005: Wake_Up_Setting (Internal -> Interface 이동)", "marked"),
        ("SwUFn_1123: s_Write2Eeprom_SW_Version (New, 삭제)", "deleted"),
        # 리뷰 2차 N1: 기능 설명 속 삭제 낱말은 설계 삭제가 아니다 · N13: 괄호 아닌 삭제 표시
        ("SwUFn_0001: g_Dtc_Clear(DTC 이력 삭제)", "marked"), ("SwUFn_0001: f_x (삭제 예정)", "marked"),
        ("SwUFn_0001: f_x (Delete key 처리)", "marked"), ("SwUFn_0001: f_x (v1.2 삭제)", "deleted"),
        ("SwUFn_0001: f_x - 삭제", "deleted"), ("SwUFn_0001: f_x [삭제]", "deleted"), ("SwUFn_0001: f_x 삭제 함수", "plain"),
    ])
    def test_w2_marks(self, text, status):
        assert read_design_heading(text)["status"] == status

    def test_w2_spaced_deleted_mark_does_not_make_the_new_design_ambiguous(self, tmp_path):
        body = (_para("SwUFn_0010: f_x (삭제)") + _table("SwUFn_0010", "f_x", [("1", "a", "U8", "0 ~ 1")])
                + _para("SwUFn_0011: f_x(New)") + _table("SwUFn_0011", "f_x", [("1", "b", "U8", "0 ~ 1")]))
        path = _docx(body, tmp_path)
        assert resolve_unit_io(load_uds_unit_io(path), "f_x")["inputs"] == ["b"]
        assert resolve_design_id(load_uds_design_ids(path), "f_x") == "SwUFn_0011"

    @pytest.mark.parametrize("text, typ", [("0xFF10 ~ 0x00F0 (-240 ~ 240)", "U16"), ("0x80 ~ 0x7F (-128 ~ 127)", "U8")])
    def test_w3_annotation_never_reads_negative_values_for_an_unsigned_type(self, text, typ):
        assert "range" not in read_value_range(text, typ)

    @pytest.mark.parametrize("text, typ, want", [
        ("0x7FFF ~ 0x8000", "U16", "signed_notation_unsigned_type"),                     # HDPDM01 4 행
        ("0x7FFF ~ 0x8000", "S32", "signed_notation_width_differs"),
    ])
    def test_w4_signed_notation_on_another_type_is_not_read(self, text, typ, want):
        assert read_value_range(text, typ).get("unread") == want

    @pytest.mark.parametrize("text, typ", [("0x7FFF ~ 0x8000", ""), ("0x7FFF ~ 0x8000", "SINT16"),
                                           ("0x7FFF ~ 0x8000", "INT16"), ("0x7FFF ~ 0x8000", "signed short")])
    def test_w4_signed_full_width_written_top_down(self, text, typ):
        assert read_value_range(text, typ)["range"] == (-32768, 32767)
        assert parse_value_range("0x7F ~ 0x80") == (-128, 127)

    def test_w5_mcdc_keeps_the_declaration_when_a_listed_value_does_not_fit(self):
        from generators.mcdc_design import _apply_design_range

        dom = {"min": 0, "max": 255}
        _apply_design_range({"uds_param_info": {"k": {"values": [0, 128, 300]}}}, "k", dom)
        assert (dom["min"], dom["max"], "values" in dom) == (0, 255, False)
        assert dom["design_range_conflict"]["source"] == "uds_values"
        enum_dom = {"min": 0, "max": 9, "values": [0, 1, 2]}
        _apply_design_range({"uds_param_info": {"k": {"values": [0, 2, 7]}}}, "k", enum_dom)
        assert enum_dom["values"] == [0, 1, 2] and "design_range_conflict" in enum_dom

    @pytest.mark.parametrize("text, want", [("0, 100,200", "ambiguous_comma"), ("AB ~ CD", "not_a_number"),
                                            ("0 ~ cell", "not_a_number")])
    def test_i1_i2_no_number_from_words_or_mixed_commas(self, text, want):
        assert read_value_range(text, "").get("unread") == want
        assert read_value_range("0 ~ FFFF", "U16")["range"] == (0, 65535)
        assert read_value_range("0x00000001 ~ 7FFFFFFF", "S32")["range"] == (1, 2147483647)

    def test_i3_i4_empty_value_and_reserved_rows(self, tmp_path):
        rows = [("1", "u8g_A", "U8", "0 ~ 1", "0", "d"), ("", "Reserved", "", "", "", ""),
                ("", "u8g_B", "U8", "0 ~ 1", "0", "d")]
        extra = _row("ASIL", "", "Period", "10ms")
        io = load_uds_unit_io(_docx(_para("SwUFn_0001: f") + _table("SwUFn_0001", "f", rows, extra=extra), tmp_path))
        rec = resolve_unit_io(io, "f")
        assert rec["inputs"] == ["u8g_A", "u8g_B"] and rec["asil"] == ""

    def test_i5_tab_in_a_heading_is_a_space(self, tmp_path):
        body = '<w:p><w:r><w:t>SwUFn_0012: f_x</w:t></w:r><w:r><w:tab/><w:t>Init</w:t></w:r></w:p>'
        assert resolve_design_id(load_uds_design_ids(_docx(body, tmp_path)), "f_x") == "SwUFn_0012"

    def test_i7_read_error_does_not_carry_the_directory(self, tmp_path):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"PK broken")
        err = load_uds_unit_io(str(bad))["reading"]["read_error"]
        assert str(tmp_path) not in err

    def test_i8_two_value_list_is_marked(self):
        got = read_value_range("0x0363, 0x035C", "S16")
        assert got["values"] == [860, 867] and "two_value_list" in got["notation"]

    def test_text_box_inside_the_heading_is_not_part_of_the_name(self, tmp_path):
        """HDPDM01 `SwUFn_3531: LinUdsToTp` 문단 속 도형 번호(Choice · Fallback 두 벌)가 `2211SwUFn_3531…` 로 읽혔다."""
        mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
        box = (f'<w:r><mc:AlternateContent xmlns:mc="{mc}"><mc:Choice><w:drawing><w:txbxContent><w:p><w:r><w:t>2</w:t>'
               f'</w:r></w:p></w:txbxContent></w:drawing></mc:Choice><mc:Fallback><w:pict><w:txbxContent><w:p><w:r>'
               f'<w:t>2</w:t></w:r></w:p></w:txbxContent></w:pict></mc:Fallback></mc:AlternateContent></w:r>')
        body = (f"<w:p>{box}<w:r><w:t>SwUFn_3531:  LinUdsToTp</w:t></w:r></w:p>"
                + _table("SwUFn_3531", "LinUdsToTp", [("1", "u8g_A", "U8", "0 ~ 1", "0", "d")]))
        path = _docx(body, tmp_path)
        assert resolve_design_id(load_uds_design_ids(path), "LinUdsToTp") == "SwUFn_3531"
        assert resolve_unit_io(load_uds_unit_io(path), "LinUdsToTp")["inputs"] == ["u8g_A"]


class TestReviewRound2:
    def test_n5_non_breaking_hyphen_is_a_minus_sign(self, tmp_path):
        cell = '<w:tc><w:p><w:r><w:noBreakHyphen/><w:t>240 ~ 240</w:t></w:r></w:p></w:tc>'
        cell2 = '<w:tc><w:p><w:r><w:t>0x00 ~ 0x05</w:t></w:r></w:p></w:tc>'
        rows = [_row("1", "s16g_A", "S16", cell, "0", "d"), _row("2", "s16g_B", "S16", "5 ~ 5", "0", "d"),
                _row("3", "u8g_C", "U8", cell2, "0", "d")]
        io = load_uds_unit_io(_docx(_para("SwUFn_0001: f") + _table("SwUFn_0001", "f", rows), tmp_path))
        info = resolve_unit_io(io, "f")["param_info"]
        assert info["s16g_A"]["range"] == [-240, 240] and info["s16g_A"]["range_text"] == "-240 ~ 240"
        assert info["s16g_B"]["range_unread"] == "single_value"           # 끝이 같은 범위는 값 하나
        assert info["u8g_C"]["range"] == [0, 5]

    def test_n6_alternate_content_reads_the_choice_once(self, tmp_path):
        mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
        body = (f'<w:p><w:r><w:t>SwUFn_0001: </w:t></w:r><mc:AlternateContent xmlns:mc="{mc}"><mc:Choice><w:r><w:t>f_a'
                f'</w:t></w:r></mc:Choice><mc:Fallback><w:r><w:t>f_a</w:t></w:r></mc:Fallback></mc:AlternateContent></w:p>')
        assert resolve_design_id(load_uds_design_ids(_docx(body, tmp_path)), "f_a") == "SwUFn_0001"

    def test_n7_table_of_contents_entry_is_not_a_heading(self, tmp_path):
        toc = ('<w:p><w:pPr><w:pStyle w:val="TOC2"/></w:pPr><w:r><w:t>SwUFn_0101: main</w:t></w:r><w:r><w:tab/>'
               '<w:t>12</w:t></w:r></w:p>')
        rev = "<w:tbl>" + _row("Version", "Date") + _row("1.0", "2024") + "</w:tbl>"
        body = toc + rev + _para("SwUFn_0101: main") + _table("SwUFn_0101", "main", [("1", "u8g_A", "U8", "0 ~ 1")])
        io = load_uds_unit_io(_docx(body, tmp_path))
        assert resolve_unit_io(io, "main")["inputs"] == ["u8g_A"] and io["ambiguous"] == []

    def test_n8_os_error_text_has_only_the_file_name(self, tmp_path):
        from generators.uds_design_ids import read_error_text

        p = tmp_path / "SwUDS_v1.docx"
        err = read_error_text(PermissionError(13, "Permission denied", str(p)), p)
        assert err == "PermissionError: Permission denied (SwUDS_v1.docx)"

    def test_n9_n10_n11(self):
        assert read_value_range("0xFFF0 ~ 0x0010 (-16 ~ 16)", "S32").get("unread") == "annotation_disagrees"
        assert read_value_range("0 ~ 1E6", "").get("unread") == "not_a_number"
        assert document_int_type("X uint16") == (False, 16) and document_int_type("AUTO int16") == (True, 16)

    def test_n4_enum_variable_with_values_that_are_not_enumerators(self):
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["e"], "output_vars": [], "param_types": {"e": "E_Mode"},
             "value_domains": {"e": {"values": [0, 1, 2]}},
             "uds_param_info": {"e": {"values": [0, 5, 15], "range_text": "0, 5, 15"}}}
        generate_sequences(u, type_cache={})
        assert u["bounds_source"]["e"] == "enum"
        assert u["range_conflicts"] == ["e(SwUDS 값 목록 0,5,15 ⊄ 열거자) ← 원문 `0, 5, 15`"]

    def test_n3_disclosure_lists_only_used_aliases_and_deleted_source_functions(self):
        from generators.suts import summarize_uds_reading
        from generators.uds_design_ids import restrict_aliases

        io = restrict_aliases({"by_name": {"f_y": {}}, "aliases": {"f_x": "f_y"}, "reading": {
            "functions": 1, "deleted_headings": ["SwUFn_0002: s_Gone(삭제)"]}}, ["f_x", "f_y", "s_Gone"])
        s = summarize_uds_reading(io, [{"name": "f_x"}], True, ["f_x", "f_y", "s_Gone"])
        assert s["name_row_aliases"] == [] and s["alias_dropped_source"] == ["f_x→f_y"]
        assert s["deleted_in_source"] == ["s_Gone"]


class TestReviewRound3:
    @pytest.mark.parametrize("mark", ["(삭제함)", "(삭제 됨)", "(삭제된 함수)", "(삭제.)", "(삭제/미사용)", "(삭제, 미사용)",
                                      "(v1.05에서 삭제)", "(Rev.3 삭제)", "(deleted in v1.05)", "(Removed from v2)",
                                      "(미사용 함수)", "(사용하지 않음)", "(Del)"])
    def test_i1_more_deletion_phrases(self, mark):
        assert read_design_heading(f"SwUFn_0001: f_x{mark}")["status"] == "deleted"

    def test_i1_the_live_heading_wins_over_one_whose_mark_says_deleted(self, tmp_path):
        """삭제 표현을 알아보지 못해도(`(삭제 처리 완료)` — 설명으로 읽힘) 같은 이름의 살아 있는 머리말이 하나뿐이면 그것을 쓴다."""
        body = (_para("SwUFn_0010: f_x(삭제 처리 완료)") + _table("SwUFn_0010", "f_x", [("1", "a", "U8", "0 ~ 1")])
                + _para("SwUFn_0011: f_x(New)") + _table("SwUFn_0011", "f_x", [("1", "b", "U8", "0 ~ 1")]))
        path = _docx(body, tmp_path)
        io, ids = load_uds_unit_io(path), load_uds_design_ids(path)
        assert resolve_unit_io(io, "f_x")["inputs"] == ["b"] and resolve_design_id(ids, "f_x") == "SwUFn_0011"
        assert io["reading"]["superseded_headings"] == ids["superseded_headings"] == [
            "SwUFn_0010: f_x(삭제 처리 완료) → SwUFn_0011: f_x(New)"]

    def test_i1_two_live_headings_stay_ambiguous(self, tmp_path):
        body = (_para("SwUFn_2901: SCI0_Init") + _table("SwUFn_2901", "SCI0_Init", [("1", "a", "U8", "0 ~ 1")])
                + _para("SwUFn_3515: SCI0_Init") + _table("SwUFn_3515", "SCI0_Init", [("1", "b", "U8", "0 ~ 1")]))
        path = _docx(body, tmp_path)
        assert load_uds_unit_io(path)["ambiguous"] == ["SCI0_Init"] and load_uds_design_ids(path)["ambiguous"] == ["SCI0_Init"]

    def test_i2_toc_by_style_name_in_a_korean_document(self, tmp_path):
        styles = (f'<?xml version="1.0"?><w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="11">'
                  f'<w:name w:val="toc 1"/></w:style></w:styles>')
        toc = ('<w:p><w:pPr><w:pStyle w:val="11"/></w:pPr><w:r><w:t>SwUFn_0101: main</w:t></w:r><w:r><w:tab/>'
               '<w:t>12</w:t></w:r></w:p>')
        rev = "<w:tbl>" + _row("Version", "Date") + _row("1.0", "2024") + "</w:tbl>"
        body = toc + rev + _para("SwUFn_0101: main") + _table("SwUFn_0101", "main", [("1", "u8g_A", "U8", "0 ~ 1")])
        p = tmp_path / "uds.docx"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("word/document.xml",
                        f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
            zf.writestr("word/styles.xml", styles)
        io = load_uds_unit_io(str(p))
        assert resolve_unit_io(io, "main")["inputs"] == ["u8g_A"] and io["ambiguous"] == []

    def test_i4_exclusion_leaving_one_value_is_a_single_value(self):
        assert read_value_range("0 ~ 1 (0 제외)", "U8").get("unread") == "single_value"

    def test_i5_empty_choice_reads_the_fallback(self, tmp_path):
        mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
        body = (f'<w:p><w:r><w:t>SwUFn_0001: </w:t></w:r><mc:AlternateContent xmlns:mc="{mc}"><mc:Choice/>'
                f'<mc:Fallback><w:r><w:t>f_a</w:t></w:r></mc:Fallback></mc:AlternateContent></w:p>')
        assert resolve_design_id(load_uds_design_ids(_docx(body, tmp_path)), "f_a") == "SwUFn_0001"

    def test_v1_deleted_heading_with_a_live_twin_is_not_reported_as_out_of_scope(self):
        from generators.suts import summarize_uds_reading
        from generators.uds_design_ids import restrict_aliases

        io = restrict_aliases({"by_name": {"s_Timer": {}}, "reading": {
            "functions": 1, "deleted_headings": ["SwUFn_0002: s_Timer(삭제)", "SwUFn_0003: s_Gone(삭제)"]}},
            ["s_Timer", "s_Gone"])
        assert summarize_uds_reading(io, [], True, ["s_Timer", "s_Gone"])["deleted_in_source"] == ["s_Gone"]


class TestReviewRound4:
    @pytest.mark.parametrize("mark", ["(Delay 처리)", "(Model 변경)", "(Unusedflag 정리)", "(삭제버튼 처리)",
                                      "(DEL_FLAG 처리)", "(Del2 처리)"])
    def test_w1_words_inside_other_words_do_not_pick_one_of_two_static_functions(self, tmp_path, mark):
        body = (_para("SwUFn_0201: SCI0_Init") + _table("SwUFn_0201", "SCI0_Init", [("1", "a", "U8", "0 ~ 1")])
                + _para(f"SwUFn_0301: SCI0_Init{mark}") + _table("SwUFn_0301", "SCI0_Init", [("1", "b", "U8", "0 ~ 1")]))
        path = _docx(body, tmp_path)
        assert load_uds_unit_io(path)["ambiguous"] == ["SCI0_Init"]
        assert resolve_design_id(load_uds_design_ids(path), "SCI0_Init") == ""

    @pytest.mark.parametrize("text, status", [("SwUFn_0001: f_x(삭제 함수 추가)", "marked"),
                                              ("SwUFn_0001: f_x(신규 삭제 함수)", "marked"),
                                              ("SwUFn_0001: f_x(삭제된 함수)", "deleted")])
    def test_i2_function_added_is_a_description(self, text, status):
        assert read_design_heading(text)["status"] == status

    def test_i1_a_live_heading_without_a_table_still_counts_as_mapped(self, tmp_path):
        from generators.suts import summarize_uds_reading

        body = (_para("SwUFn_1106: s_T(삭제)") + _table("SwUFn_1106", "s_T", [("1", "a", "U8", "0 ~ 1")])
                + _para("SwUFn_1107: s_T(New)"))
        io = load_uds_unit_io(_docx(body, tmp_path), source_functions=["s_T"])
        assert summarize_uds_reading(io, [], True, ["s_T"])["deleted_in_source"] == []


    @pytest.mark.parametrize("mark", ["(삭제되었음)", "(삭제하였음)", "(삭제했음)"])
    def test_r5_past_tense_deletion(self, mark):
        assert read_design_heading(f"SwUFn_0001: f_x{mark}")["status"] == "deleted"


class TestFullWidthDesignRange:
    @pytest.mark.parametrize("ptype", ["S16", "E_Unknown"])
    def test_a_design_range_equal_to_the_type_uses_the_type_boundaries(self, ptype):
        """설계 범위가 선언 타입 전폭과 같으면 타입 표의 경계값(가운데 0) — `(lo+hi)//2 = -1` 로 기준 행이 흔들리지 않게.
        소스 선언이 모르는 타입이어도 설계서 Type 칸(S16)이 정한 타입이면 같다."""
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["s16g_A"], "output_vars": [], "param_types": {"s16g_A": ptype},
             "uds_param_info": {"s16g_A": {"type": "S16", "range": [-32768, 32767], "range_text": "0x7FFF ~ 0x8000"}}}
        seqs = generate_sequences(u, type_cache={})
        assert u["bounds_source"]["s16g_A"] == "uds_range"
        mid = [s for s in seqs if s.get("strategy") == "BV_MID"]
        assert mid and str(mid[0]["inputs"]["s16g_A"]) == "0"
