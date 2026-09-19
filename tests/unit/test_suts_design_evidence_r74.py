"""R74 (N90) — SUTS 의 값과 추적 ID 는 설계 문서가 말한 것을 쓴다: SwUDS 의 Type·Value Range·Description, HSIS 의 SW 값 범위, STS 와 같은 요구 매핑.

실측(KJPDS02 라이브 run 2117~2121): 보강 3종이 전부 0건이었다 —
  · SRS 요구 ID: 요구 본문에서 `…_init|_get…` 꼴 함수 이름을 정규식으로 찾았다(후보 0, unit 0/933). STS 매핑으로는 896/933.
  · UDS 설명: 문단 heading 을 키로 썼다(`SwUFn_0101: main` 꼴 문서에서 0건). 함수 표에는 989 함수 전부 Description 이 있다.
  · HSIS: 열 번호 상수(T=19)로 읽어 25 신호 중 SW 변수 1개. 실제는 `SW Variable` 묶음의 `Name`(22열)·`Value Range`(24열).
그리고 SwUDS 파라미터 표는 **범위를 직접 적는다**(`0x00 ~ 0x01` 842행) — 타입 전폭(0/127/255)보다 강한 경계값 출처다.
"""
from __future__ import annotations

import zipfile

import pytest

from generators.suts import (
    _unit_uds_param_info,
    collect_unit_functions,
    generate_sequences,
    generate_suts_quality_report,
    range_bounds,
)
from generators.uds_unit_io import load_uds_unit_io, parse_value_range, resolve_unit_io

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in cells) + "</w:tr>"


def _docx(tmp_path, rows: str, name: str = "Fn") -> str:
    p = tmp_path / "uds.docx"
    body = f"<w:p><w:r><w:t>SwUFn_0102: {name}</w:t></w:r></w:p><w:tbl>{rows}</w:tbl>"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return str(p)


_TABLE = (
    _row("[ Function Information ]") + _row("ID", "SwUFn_0102") + _row("Name", "Fn")
    + _row("Description", "WDI 를 토글한다") + _row("ASIL", "A")
    + _row("[ Input Parameters ]") + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    + _row("1", "u8g_Flag", "U8", "0x00 ~ 0x01", "0x00", "플래그")
    + _row("2", "s16g_Pos", "S16", "0x8000 ~ 0x7FFF", "0", "위치")
    + _row("3", "st_Mode", "enum", "0x00 ~ 0x04", "0", "모드")
    + _row("4", "pt_X", "N/A", "N/A", "N/A", "N/A")
    + _row("[ Output Parameters ]") + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    + _row("1", "u8g_Out", "U8", "0 ~ 100", "0", "출력")
    + _row("선행조건", "N/A") + _row("[ Logic Diagram ]", "")
)


class TestValueRange:
    @pytest.mark.parametrize("text, expected", [
        ("0x00 ~ 0x01", (0, 1)), ("0x00~0xFF", (0, 255)), ("0x0000U ~ 0xFFFFU", (0, 65535)), ("0 ~ 100", (0, 100)),
        ("0x8000 ~ 0x7FFF", (-32768, 32767)), ("0x80000000 ~ 0x7FFFFFFF", (-2147483648, 2147483647)), ("0x80 ~ 0x7F", (-128, 127)),
        ("-5 ~ 5", (-5, 5)), ("0 ... 10", (0, 10)),
    ])
    def test_reads_ranges_including_twos_complement_hex(self, text, expected):
        assert parse_value_range(text) == expected

    @pytest.mark.parametrize("text", ["N/A", "", "9 to 16V", "On: GND, Off: 5V", "10 ~ 5", "0x00 ~", None])
    def test_unreadable_is_none_not_a_guess(self, text):
        assert parse_value_range(text) is None

    def test_range_bounds(self):
        assert range_bounds([0, 4]) == {"min_inv": -1, "min": 0, "mid": 2, "max": 4, "max_inv": 5}
        assert range_bounds(None) == {} and range_bounds([5, 1]) == {} and range_bounds(["a", 1]) == {}


class TestSwUdsTable:
    def test_description_type_and_range_are_read(self, tmp_path):
        rec = resolve_unit_io(load_uds_unit_io(_docx(tmp_path, _TABLE)), "Fn")
        assert rec["description"] == "WDI 를 토글한다"
        assert rec["param_info"]["u8g_Flag"] == {"type": "U8", "range": [0, 1]}
        assert rec["param_info"]["s16g_Pos"]["range"] == [-32768, 32767]
        assert rec["param_info"]["u8g_Out"] == {"type": "U8", "range": [0, 100]}
        assert "pt_X" not in rec["param_info"], "`N/A` 는 근거가 아니다 — 싣지 않는다"
        assert rec["inputs"] == ["u8g_Flag", "s16g_Pos", "st_Mode", "pt_X"]

    def test_param_table_description_column_is_not_the_function_description(self, tmp_path):
        rows = _TABLE.replace(_row("Description", "WDI 를 토글한다"), "")
        rec = resolve_unit_io(load_uds_unit_io(_docx(tmp_path, rows)), "Fn")
        assert rec["description"] == ""

    def test_first_description_row_wins(self, tmp_path):
        """함수 정보 표의 Description 이 먼저다 — 뒤에 같은 머리의 행이 또 와도 덮어쓰지 않는다."""
        rows = _TABLE.replace(_row("ASIL", "A"), _row("ASIL", "A") + _row("Description", "뒤에 온 다른 설명"))
        rec = resolve_unit_io(load_uds_unit_io(_docx(tmp_path, rows)), "Fn")
        assert rec["description"] == "WDI 를 토글한다"

    def test_unit_lookup_strips_element_index(self):
        info = {"param_info": {"au8_Buf": {"type": "U8", "range": [0, 9]}, "u8g_Flag": {"range": [0, 1]}}}
        got = _unit_uds_param_info(info, ["au8_Buf[3]", "U8G_FLAG", "other"])
        assert got == {"au8_Buf[3]": {"type": "U8", "range": [0, 9]}, "U8G_FLAG": {"range": [0, 1]}}
        assert _unit_uds_param_info(None, ["x"]) == {} and _unit_uds_param_info({}, ["x"]) == {}


def _unit(**kw):
    base = {"fid": "F", "name": "Fn", "prototype": "void Fn(void)", "input_vars": [], "output_vars": [], "indirect_vars": [],
            "logic_flow": [], "calls_list": [], "param_types": {}, "value_domains": {}, "uds_param_info": {}}
    base.update(kw)
    return base


class TestBoundsPriority:
    def test_design_range_beats_the_type_width(self):
        """`U8` 플래그의 경계는 0/127/255 가 아니라 설계서가 적은 0/0/1 (범위 밖 2) 다."""
        u = _unit(input_vars=["u8g_Flag"], uds_param_info={"u8g_Flag": {"type": "U8", "range": [0, 1]}})
        by = {s["strategy"]: s["inputs"]["u8g_Flag"] for s in generate_sequences(u, 6, type_cache={"u8g_Flag": "U8"})}
        assert (by["BV_MIN_INV"], by["BV_MIN"], by["BV_MAX"], by["BV_MAX_INV"]) == (-1, 0, 1, 2)
        assert u["bounds_source"]["u8g_Flag"] == "uds_range"

    def test_order_is_design_range_then_enum_then_hsis_then_type(self):
        u = _unit(input_vars=["a", "b", "c", "d"], param_types={"a": "U8", "b": "E_T", "c": "U16", "d": "U8"},
                  uds_param_info={"a": {"range": [0, 3]}}, value_domains={"a": {"values": [7, 8]}, "b": {"values": [16, 18]}},
                  hsis_bounds={"a": (0, 9), "b": (0, 9), "c": (0, 1000)})
        seqs = {s["strategy"]: s["inputs"] for s in generate_sequences(u, 6, type_cache={})}
        assert seqs["BV_MAX"] == {"a": 3, "b": 18, "c": 1000, "d": 255}
        assert u["bounds_source"] == {"a": "uds_range", "b": "enum", "c": "hsis_range", "d": "type"}

    def test_unknown_declaration_with_a_design_range_is_no_longer_blank(self):
        u = _unit(input_vars=["h"], param_types={"h": "l_ifc_handle"}, uds_param_info={"h": {"range": [0, 3]}})
        seqs = generate_sequences(u, 6, type_cache={})
        assert u["var_types"]["h"] == "range" and u["unknown_type_vars"] == []
        assert {s["strategy"]: s["inputs"]["h"] for s in seqs}["BV_MAX"] == 3

    def test_unknown_declaration_with_a_design_type_uses_the_type(self):
        u = _unit(input_vars=["h"], param_types={"h": "MyHandle_t"}, uds_param_info={"h": {"type": "U16"}})
        generate_sequences(u, 6, type_cache={})
        assert u["var_types"]["h"] == "uint16_t" and u["bounds_source"]["h"] == "type"

    def test_document_range_wider_than_the_declared_type_is_not_used(self):
        """실측 HSIS: U16 변수에 `0x0000 ~ 0xFFFFFU`(F 다섯) — 선언 타입이 담을 수 없는 값은 문서 오류다. 쓰지 않고 센다."""
        u = _unit(input_vars=["u16g_Fb"], param_types={"u16g_Fb": "U16"}, hsis_bounds={"u16g_Fb": (0, 0xFFFFF)})
        by = {s["strategy"]: s["inputs"]["u16g_Fb"] for s in generate_sequences(u, 6, type_cache={})}
        assert by["BV_MAX"] == 65535 and u["bounds_source"]["u16g_Fb"] == "type"
        assert u["range_conflicts"] and "HSIS" in u["range_conflicts"][0]

    def test_quality_report_names_the_sources_and_conflicts(self):
        units = [_unit(fid="a", name="a", bounds_source={"x": "uds_range", "y": "type"}, srs_req_ids="SwTR_0101",
                       range_conflicts=["v(HSIS 0~1048575 vs uint16_t)"]),
                 _unit(fid="b", name="b", bounds_source={"z": "enum"}, srs_req_ids="")]
        q = generate_suts_quality_report(units, {}, 2)
        assert q["bounds_source_distribution"] == {"uds_range": 1, "type": 1, "enum": 1}
        assert q["units_with_srs_req_ids"] == 1 and q["range_conflict_count"] == 1


class TestCollect:
    def test_unit_carries_design_info_and_the_longer_description(self, tmp_path):
        io = load_uds_unit_io(_docx(tmp_path, _TABLE))
        fd = {"SwUFn_0102": {"id": "SwUFn_0102", "name": "Fn", "prototype": "void Fn(void)", "description": "짧음",
                             "inputs": [], "outputs": [], "globals_global": ["[IN] u8g_Flag"], "globals_static": [],
                             "logic_flow": []}}
        u = collect_unit_functions(fd, {}, sds_map={}, uds_io_map=io)[0]
        assert u["description"] == "WDI 를 토글한다"
        assert u["uds_param_info"]["u8g_Flag"]["range"] == [0, 1] and u["uds_param_info"]["u8g_Out"]["range"] == [0, 100]

    def test_source_description_stays_when_the_design_has_none(self):
        fd = {"F": {"id": "F", "name": "Fn", "prototype": "void Fn(void)", "description": "소스 주석 설명", "inputs": [],
                    "outputs": [], "globals_global": [], "globals_static": [], "logic_flow": []}}
        u = collect_unit_functions(fd, {}, sds_map={})[0]
        assert u["description"] == "소스 주석 설명" and u["uds_param_info"] == {}


class TestHsisLoaderFindsColumnsByHeader:
    @staticmethod
    def _xlsx(tmp_path, layout: str) -> str:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "2.HSIS"
        if layout == "grouped":   # KJPDS02 HSIS v2.01 — `SW Variable` 묶음 아래 ID·Type·Name·Initial·Value Range
            head = [None, "Device", "Pin No", "사용", "HS/SW Mapping", "ID", "Signal Name", "Signal Type", "Pin Name", "Description",
                    "Register Name", "Direction", "Characteristics", "Pull Up/Down", "Architecture Element", None, None, None,
                    "Extension Connector", None, None, "SW Variable", None, None, None, "Related ID", "Verification Criteria"]
            sub = [None] * 14 + ["ID", "Name", "Internal Interface", "SM_ID", "Pin No", "Pin Name", "ID", "Type", "Name",
                                 "Initial Value", "Value Range"]
            row = [None, "MCU", "1", "O", "O", "HSI_30", "VCC_BAT", "Analog", "VSUP", "Battery", "VSUP", "IN", "9 to 16V", None,
                   "SyEL_01", "Power", "SyII_05", "SySM_04", None, None, None, "U16", "u16g_DrvIn_Vsup", "0x0000U",
                   "0x0000U ~ 0xFFFFU", "SyTR_0401", "HW"]
            for _r in (["HSIS"], [], head, sub, row):
                ws.append(_r)
        else:                      # 옛 양식 — T(19)=SW Variable Name · U(20)=Related ID
            head = [None] * 5 + ["ID", "Signal Name", "Signal Type", "Pin Name", "Desc", "Reg", "Direction", "Characteristics"] \
                + [None] * 6 + ["SW Variable Name", "Related ID"]
            row = [None] * 5 + ["HSI_01", "KEY", "Digital", "PL0", "", "", "IN", "0...1"] + [None] * 6 + ["u8g_Key", "SwTR_0101"]
            for _r in (["HSIS"], [], head, row):
                ws.append(_r)
        p = tmp_path / f"hsis_{layout}.xlsx"
        wb.save(p)
        return str(p)

    def test_grouped_layout_reads_name_type_and_value_range(self, tmp_path):
        from generators.sts import _load_hsis_signals

        sig = _load_hsis_signals(self._xlsx(tmp_path, "grouped"))["signals"]
        assert len(sig) == 1
        assert (sig[0]["sw_var_name"], sig[0]["sw_var_type"], sig[0]["value_range"], sig[0]["related_id"]) == \
            ("u16g_DrvIn_Vsup", "U16", "0x0000U ~ 0xFFFFU", "SyTR_0401")
        assert sig[0]["column_layout"] == "header" and sig[0]["id"] == "HSI_30"

    def test_legacy_layout_still_reads(self, tmp_path):
        from generators.sts import _load_hsis_signals

        sig = _load_hsis_signals(self._xlsx(tmp_path, "legacy"))["signals"]
        assert [(s["sw_var_name"], s["related_id"], s["value_range"]) for s in sig] == [("u8g_Key", "SwTR_0101", "")]


class TestSrsLinkUsesTheStsMapping:
    def test_generator_no_longer_greps_function_names_out_of_requirement_text(self):
        """구조 가드 — 요구는 함수 이름을 적지 않는다(실측 후보 0건). 보강은 STS 와 같은 매핑을 뒤집어 쓴다."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "generators" / "suts.py").read_text(encoding="utf-8")
        body = src[src.index("def generate_suts("):]
        assert "map_requirements_to_functions(" in body and "_pds|_init|_main" not in body
        assert "_link_units_to_requirements(units, _fid_to_reqs)" in body
        assert "sds_map=_sds_map or {}" in body, "`sds_map=None` 은 저장소 docs/ 글롭(프로젝트 무관)을 부른다"
        assert "ids[:4]" not in src, "(리뷰 W2) 요구 ID 를 앞 4개로 자르던 절단이 남아 있다"


class TestLinkUnitsToRequirements:
    def test_union_full_list_and_link_basis(self):
        """(리뷰 W2) 수집 단계가 적은 ID 와 합치고, 전량을 적고, 어느 근거인지 남긴다."""
        from generators.suts import _link_units_to_requirements

        units = [{"fid": "F1", "srs_req_ids": "SwTR_0001"}, {"fid": "F2", "srs_req_ids": ""}, {"fid": "F3"},
                 {"fid": "F4", "srs_req_ids": "SwTR_0009"}]
        f2r = {"F1": ["SwTR_0002", "SwTR_0001"], "F2": [f"SwTR_{i:04d}" for i in range(1, 8)], "F4": []}
        assert _link_units_to_requirements(units, f2r) == 2
        assert units[0]["srs_req_ids"] == "SwTR_0001, SwTR_0002" and units[0]["srs_req_link"] == "sds_partition+sts_mapping"
        assert units[1]["srs_req_ids"].count("SwTR_") == 7 and units[1]["srs_req_link"] == "sts_mapping", "앞 4개로 자르지 않는다"
        assert "srs_req_link" not in units[2] and not units[2].get("srs_req_ids")
        assert units[3]["srs_req_link"] == "sds_partition"


class TestReviewFindings:
    def test_param_columns_are_found_by_header_not_by_position(self, tmp_path):
        """(리뷰 C1) 열 순서가 다른 양식 — `Reset Value` 를 범위로 읽고 "설계서가 말했다" 고 적으면 안 된다."""
        rows = (_row("[ Function Information ]") + _row("Name", "Fn")
                + _row("[ Input Parameters ]") + _row("No", "Name", "Reset Value", "Type", "Description", "Value Range")
                + _row("1", "u8g_Flag", "0x00 ~ 0x7F", "U8", "플래그", "0x00 ~ 0x01"))
        rec = resolve_unit_io(load_uds_unit_io(_docx(tmp_path, rows)), "Fn")
        assert rec["param_info"]["u8g_Flag"] == {"type": "U8", "range": [0, 1]} and rec["param_col_layout"] == "header"

    def test_missing_range_column_reads_nothing_rather_than_another_column(self, tmp_path):
        rows = (_row("[ Function Information ]") + _row("Name", "Fn")
                + _row("[ Input Parameters ]") + _row("No", "Name", "Type", "Reset Value")
                + _row("1", "u8g_Flag", "U8", "0x00 ~ 0x7F"))
        rec = resolve_unit_io(load_uds_unit_io(_docx(tmp_path, rows)), "Fn")
        assert rec["param_info"]["u8g_Flag"] == {"type": "U8"}

    @pytest.mark.parametrize("text", ["0xFFFF ~ 0x0000", "0x8000 ~ 0x7F", "0x800 ~ 0x7FF", "0x100 ~ 0x0FF", "0x90 ~ 0x7F"])
    def test_twos_complement_only_for_the_exact_full_width(self, text):
        """(리뷰 C2) 자릿수만 보고 부호를 고치면 내림차순 표기가 (-1, 0) 같은 범위가 되어 최우선 출처에 실린다."""
        assert parse_value_range(text) is None

    def test_name_guessed_type_does_not_veto_the_design_range(self):
        """(리뷰 W1) `_Flag` 라는 이름으로 추측한 `bit` 가 설계서의 `0 ~ 255` 를 "문서 오류" 로 기각하면 우선순위가 뒤집힌다."""
        from generators.suts import infer_variable_type

        assert infer_variable_type("Mode_Flag", {}) == "bit", "전제: 이 이름은 선언 없이 `bit` 로 추측된다"
        u = _unit(input_vars=["Mode_Flag"], uds_param_info={"Mode_Flag": {"range": [0, 255]}})
        by = {s["strategy"]: s["inputs"]["Mode_Flag"] for s in generate_sequences(u, 6, type_cache={})}
        assert by["BV_MAX"] in (255, "0xFF") and u["range_conflicts"] == [] and u["bounds_source"]["Mode_Flag"] == "uds_range"

    def test_declared_type_still_vetoes_and_conflicts_are_not_duplicated(self):
        u = _unit(input_vars=["b"], output_vars=["b"], param_types={"b": "bool"}, uds_param_info={"b": {"range": [0, 255]}})
        generate_sequences(u, 24, type_cache={})
        assert u["bounds_source"]["b"] == "type" and len(u["range_conflicts"]) == 1

    def test_hsis_related_ids_keep_only_the_software_level(self):
        """(리뷰 W4) 열 교정으로 Related ID 가 실제로 읽히면서 시스템 요구(`SyTR_`)가 SW 문서의 요구 칸으로 샐 수 있다."""
        from generators.sts import hsis_sw_related_ids

        sig = [{"related_id": "SyTR_0401"}, {"related_id": "SwTR_0101, SwTR_0102"}, {"related_id": "SwTR_0101"}, {}]
        assert hsis_sw_related_ids(sig) == ["SwTR_0101", "SwTR_0102"] and hsis_sw_related_ids([]) == []
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        for rel in ("backend/routers/local.py", "tools/generate_uds_local.py"):
            text = (root / rel).read_text(encoding="utf-8")
            assert "hsis_sw_related_ids" in text and "_rel_ids[0]" not in text and "hsis_related_ids[0]" not in text, rel

    def test_hsis_sub_header_may_come_after_a_blank_row(self, tmp_path):
        """(리뷰 W6) 머리행과 하위 머리행 사이에 빈 줄이 껴도 찾는다. 끝내 못 찾으면 `fixed-fallback` 이라 적는다."""
        from openpyxl import Workbook

        from generators.sts import _load_hsis_signals

        def build(with_sub: bool) -> str:
            wb = Workbook()
            ws = wb.active
            ws.title = "2.HSIS"
            head = [None] * 5 + ["ID", "Signal Name", "Signal Type", "Pin", "Desc", "Reg", "Direction", "Characteristics", None,
                                 "Architecture Element"] + [None] * 6 + ["SW Variable", None, None, None, "Related ID"]
            sub = [None] * 14 + ["ID", "Name"] + [None] * 4 + ["ID", "Type", "Name", "Initial Value", "Value Range"]
            row = [None] * 5 + ["HSI_01", "KEY", "Digital", "PL0", "", "", "IN", "5V"] + [None] * 8 + ["U8", "u8g_Key", "0", "0x00 ~ 0x01",
                                                                                                        "SyTR_01"]
            for r in ([["HSIS"], [], head, [None] * 26] + ([sub] if with_sub else []) + [row]):
                ws.append(r)
            p = tmp_path / f"h_{with_sub}.xlsx"
            wb.save(p)
            return str(p)

        ok = _load_hsis_signals(build(True))["signals"]
        assert [(s["sw_var_name"], s["value_range"], s["column_layout"]) for s in ok] == [("u8g_Key", "0x00 ~ 0x01", "header")]
        bad = _load_hsis_signals(build(False))["signals"]
        assert all(s["column_layout"] == "fixed-fallback" for s in bad)
