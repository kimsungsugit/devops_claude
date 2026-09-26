"""R73 (N92) — 모르는 타입의 상당수는 소스가 이미 말하고 있다: typedef 별칭 · 프로젝트가 증언한 C 타입 폭 · enum 의 닫힌 값 집합.

실측(KJPDS02 in-scope 933 unit, 2026-09-19): R71 이 `unknown` 으로 비운 426칸 중 enum 이 170칸 이상이었다 — enum 은 소스가 값의
전부를 적어 둔 타입이라 최소/최대/범위 밖을 **읽을 수 있다**. 또 이 프로젝트는 `typedef unsigned int U16` 이라 typedef 를 무작정
풀면 아는 타입(`U16`)이 폭 모르는 `unsigned int` 가 되어 1,647칸이 도로 unknown 이 된다(첫 실측) → 선언이 아는 타입이면 선언이 이긴다.
"""
from __future__ import annotations

import pytest

from generators.suts import (
    _UNKNOWN_TYPE,
    _gim_to_type_map,
    _prefer_known_decl,
    collect_unit_functions,
    enum_bounds,
    generate_sequences,
)
from report_gen.source_parser import (
    apply_c_type_width,
    extract_enum_domains,
    extract_typedef_aliases,
    infer_c_type_widths,
    resolve_typedef,
)
from report_gen.uds_generator import _annotate_typedef_bases

_SRC = """
typedef unsigned char  U8;          /* 8 bit */
typedef unsigned int   U16;
typedef signed int     S16;
typedef unsigned long  UINT32;
typedef  word * EEPROM_TAddress;
typedef const word * EEPROM_TAddress_Const;
typedef U16 Speed_t;
typedef Speed_t Alias2_t;
typedef struct { U8 a; } ST_X;
typedef void (*Callback_t)(void);
/* typedef unsigned long Commented_t; */
enum en_g_DoorState { DOOR_CLOSED, DOOR_OPENING, DOOR_OPEN = 5, DOOR_ERR };
typedef enum { E_IDLE = 0x10, E_RUN, E_STOP } E_STATE;
typedef enum tagMode { MODE_A = MACRO_BASE, MODE_B } Mode_t;
"""


class TestTypedefAliases:
    def test_simple_aliases_with_pointer_marks(self):
        a = extract_typedef_aliases(_SRC)
        assert a["U16"] == "unsigned int" and a["UINT32"] == "unsigned long"
        assert a["EEPROM_TAddress"] == "word *" and a["EEPROM_TAddress_Const"] == "const word *"
        assert a["Speed_t"] == "U16"

    def test_aggregates_function_pointers_and_comments_are_not_aliases(self):
        a = extract_typedef_aliases(_SRC)
        assert "ST_X" not in a and "Callback_t" not in a and "Commented_t" not in a
        assert "E_STATE" not in a, "본문이 있는 enum typedef 는 별칭 표가 아니라 값 집합 표의 일이다"

    def test_multi_declarator_typedef(self):
        """(리뷰 W2) 통짜로 읽으면 주 별칭 `U8` 이 사라지고 `PU8 -> "unsigned char U8, *"` 라는 쓰레기가 남는다."""
        a = extract_typedef_aliases("typedef unsigned char U8, *PU8, Buf8[8];")
        assert a == {"U8": "unsigned char", "PU8": "unsigned char *", "Buf8": "unsigned char[8]"}

    def test_resolve_follows_the_chain_and_stops_on_cycles(self):
        a = extract_typedef_aliases(_SRC)
        assert resolve_typedef("Alias2_t", a) == "unsigned int"
        assert resolve_typedef("const Alias2_t *", a) == "unsigned int *", "포인터 표기는 잃지 않는다"
        assert resolve_typedef("ST_X", a) == "ST_X"
        assert resolve_typedef("A", {"A": "B", "B": "A"}) in ("A", "B")


class TestProjectTestifiedWidths:
    def test_width_named_aliases_testify_the_plain_c_type_width(self):
        """`typedef unsigned int U16` 이면 이 타깃의 `unsigned int` 는 16비트다 — 표로 가정하지 않고 프로젝트가 증언한다."""
        w = infer_c_type_widths(extract_typedef_aliases(_SRC))
        assert w["unsigned int"] == "uint16_t" and w["signed int"] == "int16_t" and w["unsigned long"] == "uint32_t"
        assert w["unsigned char"] == "uint8_t"

    def test_conflicting_testimony_drops_the_type(self):
        w = infer_c_type_widths({"U16": "unsigned int", "U32": "unsigned int"})
        assert "unsigned int" not in w, "같은 기본 타입에 다른 폭이 증언되면 모르는 것으로 둔다"

    def test_non_width_names_and_pointers_do_not_testify(self):
        assert infer_c_type_widths({"Speed_t": "unsigned int", "P16": "unsigned int", "U16": "unsigned int *"}) == {}

    def test_apply_keeps_pointer_mark_and_leaves_unknown_alone(self):
        w = {"unsigned int": "uint16_t"}
        assert apply_c_type_width("const unsigned int *", w) == "uint16_t *"
        assert apply_c_type_width("ST_X", w) == "ST_X" and apply_c_type_width("unsigned int", {}) == "unsigned int"


class TestEnumDomains:
    def test_values_follow_c_rules(self):
        d = extract_enum_domains(_SRC)
        door = d["enum en_g_DoorState"]
        assert door["values"] == [0, 1, 5, 6] and door["names"][2] == "DOOR_OPEN"
        assert "en_g_DoorState" not in d, "맨 태그 이름은 키가 아니다(리뷰 W1) — 같은 이름의 struct typedef 와 공존할 수 있다"
        assert d["E_STATE"]["values"] == [16, 17, 18] and (d["E_STATE"]["min"], d["E_STATE"]["max"]) == (16, 18)

    def test_non_literal_initializer_drops_the_whole_enum(self):
        """`MODE_A = MACRO_BASE` — 일부만 아는 값 집합으로 최소·최대를 말하지 않는다."""
        d = extract_enum_domains(_SRC)
        assert "Mode_t" not in d and "tagMode" not in d

    def test_struct_typedef_sharing_a_tag_name_does_not_get_the_enum_domain(self):
        """(리뷰 W1) `enum Mode {…}` 와 `typedef struct {…} Mode;` 는 C 에서 공존한다 — 구조체 전역이 enum 경계값을 받으면 안 된다."""
        src = "enum Mode { M_A, M_B };\ntypedef struct { int x; } Mode;\n"
        gim = {"g_ModeCfg": {"type": "Mode"}, "g_Mode": {"type": "enum Mode"}}
        _annotate_typedef_bases(gim, {}, extract_typedef_aliases(src), extract_enum_domains(src))
        assert "value_domain" not in gim["g_ModeCfg"] and gim["g_Mode"]["value_domain"]["values"] == [0, 1]

    def test_typedef_enum_with_extra_declarators_keeps_the_first_alias(self):
        assert extract_enum_domains("typedef enum { A, B } E, *PE;")["E"]["values"] == [0, 1]

    def test_enum_bounds(self):
        assert enum_bounds({"values": [0, 1, 5, 6]}) == {"min_inv": -1, "min": 0, "mid": 5, "max": 6, "max_inv": 7}
        assert enum_bounds({}) == {} and enum_bounds(None) == {} and enum_bounds({"values": ["x"]}) == {}


class TestAnnotation:
    def _run(self):
        gim = {"g_Speed": {"type": "Speed_t"}, "g_Door": {"type": "enum en_g_DoorState"}, "g_Plain": {"type": "U8"},
               "g_State": {"type": "volatile E_STATE"}, "g_St": {"type": "ST_X"}}
        fd = {"F1": {"name": "f", "inputs": ["[IN] EEPROM_TAddress Addr (idx: i)", "[IN] E_STATE st", "[IN] U8 n"],
                     "outputs": ["[OUT] return U8"]}}
        stats = _annotate_typedef_bases(gim, fd, extract_typedef_aliases(_SRC), extract_enum_domains(_SRC))
        return gim, fd, stats

    def test_only_resolved_things_get_keys(self):
        gim, fd, stats = self._run()
        assert gim["g_Speed"]["base_type"] == "uint16_t", "별칭 사슬 → 기본 타입 → 프로젝트 폭"
        assert gim["g_Plain"]["base_type"] == "uint8_t"
        assert "base_type" not in gim["g_St"] and "value_domain" not in gim["g_Speed"]
        assert fd["F1"]["param_base_types"] == {"Addr": "word *", "n": "uint8_t"}
        assert stats["globals_resolved"] == 2 and stats["params_resolved"] == 2

    def test_enum_domains_reach_globals_and_params(self):
        gim, fd, stats = self._run()
        assert gim["g_Door"]["value_domain"]["values"] == [0, 1, 5, 6]
        assert gim["g_State"]["value_domain"]["type"] == "E_STATE", "cv 한정자를 걷고 찾는다"
        assert fd["F1"]["param_value_domains"]["st"] == {"kind": "enum", "type": "E_STATE", "values": [16, 17, 18]}, \
            "레코드엔 값 집합만 — 이름·최소·최대는 payload 루트 표에 있다(리뷰 W6)"
        assert (stats["globals_with_enum_domain"], stats["params_with_enum_domain"]) == (2, 1)

    def test_no_aliases_and_no_enums_is_a_noop(self):
        gim = {"g": {"type": "Speed_t"}}
        assert _annotate_typedef_bases(gim, {}, {}, {})["globals_resolved"] == 0 and gim == {"g": {"type": "Speed_t"}}


class TestConsumers:
    def test_known_declaration_beats_the_resolved_base(self):
        """순서가 실체다 — `U16` 을 먼저 풀면 폭 모르는 `unsigned int` 가 되어 아는 타입이 도로 unknown 이 된다(첫 실측 1,647칸)."""
        assert _prefer_known_decl("U16", "unsigned int") == "U16"
        assert _prefer_known_decl("Speed_t", "uint16_t") == "uint16_t"
        assert _prefer_known_decl("ST_X", "") == "ST_X" and _prefer_known_decl("", "uint8_t") == "uint8_t"
        assert _gim_to_type_map({"a": {"type": "U16", "base_type": "unsigned int"}, "b": {"type": "Speed_t", "base_type": "uint16_t"}}) \
            == {"a": "U16", "b": "uint16_t"}

    def _unit(self, **kw):
        base = {"fid": "F", "name": "Fn", "prototype": "void Fn(void)", "input_vars": [], "output_vars": [],
                "indirect_vars": [], "logic_flow": [], "calls_list": [], "param_types": {}, "value_domains": {}}
        base.update(kw)
        return base

    def test_enum_variable_gets_enumerator_bounds_not_blank_not_uint8(self):
        dom = {"kind": "enum", "type": "E_STATE", "values": [16, 17, 18]}
        u = self._unit(input_vars=["st", "n"], param_types={"st": "E_STATE", "n": "U8"}, value_domains={"st": dom})
        by = {s["strategy"]: s for s in generate_sequences(u, 6, type_cache={})}
        assert (by["BV_MIN"]["inputs"]["st"], by["BV_MID"]["inputs"]["st"], by["BV_MAX"]["inputs"]["st"]) == (16, 17, 18)
        assert by["BV_MAX_INV"]["inputs"]["st"] == 19 and by["BV_MIN_INV"]["inputs"]["st"] == 15
        assert u["var_types"]["st"] == "enum" and u["unknown_type_vars"] == []

    def test_enum_without_a_domain_stays_unknown(self):
        u = self._unit(input_vars=["st"], param_types={"st": "Mode_t"})
        seqs = generate_sequences(u, 6, type_cache={})
        assert u["var_types"]["st"] == _UNKNOWN_TYPE and all("st" not in s["inputs"] for s in seqs)

    def test_indirect_global_enum_in_the_no_io_path(self):
        dom = {"values": [0, 1, 2]}
        u = self._unit(indirect_vars=["g_Mode"], value_domains={"g_Mode": dom})
        by = {s["strategy"]: s for s in generate_sequences(u, 6, type_cache={"g_Mode": "enum en_Mode"})}
        assert by["NORMAL_CALL"]["inputs"]["g_Mode"] == 1 and by["ERROR_PATH"]["inputs"]["g_Mode"] == 3

    def test_collect_carries_domains_and_prefers_params(self):
        gim = {"st": {"type": "enum en_g", "value_domain": {"values": [7, 8]}},
               "g_Door": {"type": "enum en_g_DoorState", "value_domain": {"values": [0, 1]}}}
        fd = {"F1": {"id": "F1", "name": "Fn", "prototype": "void Fn(E_STATE st)", "inputs": ["[IN] E_STATE st"], "outputs": [],
                     "globals_global": ["[IN] g_Door"], "globals_static": [], "logic_flow": [],
                     "param_base_types": {}, "param_value_domains": {"st": {"values": [16, 17, 18]}}}}
        u = collect_unit_functions(fd, gim, sds_map={})[0]
        assert u["value_domains"]["st"]["values"] == [16, 17, 18], "파라미터의 값 집합이 같은 이름 전역보다 앞선다"
        assert u["value_domains"]["g_Door"]["values"] == [0, 1]

    def test_sts_boundary_tc_uses_enumerator_values(self):
        from generators.sts import _generate_simple_steps

        tcs = _generate_simple_steps({"name": "f", "inputs": ["[IN] E_STATE st"], "calls_list": [],
                                      "param_value_domains": {"st": {"values": [16, 17, 18]}}})
        acts = [s["action"] for t in tcs for s in t]
        assert any("st=16" in a for a in acts) and any("st=18" in a for a in acts) and any("st=19" in a for a in acts), acts

    def test_sts_resolved_typedef_only_when_declaration_is_unknown(self):
        from generators.sts import _generate_simple_steps

        tcs = _generate_simple_steps({"name": "f", "inputs": ["[IN] Speed_t v", "[IN] U16 w"], "calls_list": [],
                                      "param_base_types": {"v": "uint16_t", "w": "unsigned int"}})
        acts = [s["action"] for s in tcs[1]]
        assert any("v=65535" in a and "w=65535" in a for a in acts), acts


class TestConflictsAreDroppedNotPicked:
    def test_same_alias_with_different_bases_across_files_is_dropped_and_reported(self, tmp_path):
        """(리뷰 W3) first-wins 로 고르면 `infer_c_type_widths` 의 "상충 증언은 뺀다" 가 무력하다 — 충돌한 이름은 표에서 뺀다."""
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "a.h").write_text("typedef unsigned char U8;\ntypedef unsigned int U16;\nenum E { X, Y };\n", encoding="utf-8")
        (tmp_path / "b.h").write_text("typedef unsigned long U8;\ntypedef unsigned int U16;\nenum E { X, Y, Z };\n",
                                      encoding="utf-8")
        (tmp_path / "m.c").write_text('#include "a.h"\nvoid f(U8 n)\n{\n    (void)n;\n}\n', encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path))
        assert "U8" not in sec["typedef_aliases"] and sec["typedef_aliases"]["U16"] == "unsigned int"
        assert "enum E" not in sec["enum_domains"]
        assert sec["typedef_scan"]["alias_conflicts"] == ["U8"] and sec["typedef_scan"]["enum_conflicts"] == ["enum E"]


class TestMcdcUsesTheSameBounds:
    def test_enum_condition_variable_never_leaves_its_domain(self):
        """(리뷰 C1) 같은 unit 표에 `BV_MAX=18` 과 `MCDC_BASE=255` 가 나란히 섰다 — MC/DC 경로만 uint8 기본값으로 접혔다."""
        from generators.suts import get_boundary_values

        assert get_boundary_values("enum") == {}
        dom = {"values": [16, 17, 18]}
        u = {"fid": "F", "name": "Fn", "prototype": "void Fn(void)", "input_vars": ["st", "thr"], "output_vars": [],
             "indirect_vars": [], "calls_list": [], "param_types": {"st": "E_STATE", "thr": "U8"}, "value_domains": {"st": dom},
             "logic_flow": [{"type": "if", "condition": "st >= thr"}]}
        seqs = generate_sequences(u, 30, type_cache={})
        st_values = {s["inputs"]["st"] for s in seqs if "st" in s["inputs"]}
        assert st_values and st_values <= {15, 16, 17, 18, 19}, st_values
        mcdc = [s["inputs"] for s in seqs if s["strategy"].startswith("MCDC")]
        # (R80) MC/DC 는 식을 평가해 고른 설계 벡터다 — 열거형 변수는 **열거자 값만** 쓰고, 쌍의 두 행은 결정이 뒤집힌다.
        assert mcdc and all(v["st"] in (16, 17, 18) for v in mcdc), \
            f"MC/DC 벡터가 열거자 값 집합을 벗어났다 — 호출자의 도메인 해상을 안 쓰면 uint8 로 접힌다: {mcdc}"
        pair = u["mcdc_design"]["decisions"][0]["pairs"][0]
        assert pair["decision_a"] != pair["decision_b"] and pair["retained_status"] == "retained"

    def test_unknown_typed_condition_variable_is_not_given_uint8_toggles(self):
        u = {"fid": "F", "name": "Fn", "prototype": "void Fn(void)", "input_vars": ["pt", "n"], "output_vars": [],
             "indirect_vars": [], "calls_list": [], "param_types": {"pt": "ST_X *", "n": "U8"}, "value_domains": {},
             "logic_flow": [{"type": "if", "condition": "pt >= n"}]}
        seqs = generate_sequences(u, 30, type_cache={})
        assert all("pt" not in s["inputs"] for s in seqs)


class TestCacheSchemaMoved:
    def test_schema_version_is_at_least_v25(self):
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION

        assert int(_SOURCE_SECTIONS_SCHEMA_VERSION.lstrip("v")) >= 25


@pytest.mark.parametrize("key", ["typedef_aliases", "enum_domains", "typedef_scan"])
def test_sections_payload_carries_the_new_keys(tmp_path, key):
    from report_gen.uds_generator import generate_uds_source_sections

    (tmp_path / "t.h").write_text("typedef unsigned int U16;\ntypedef enum { A, B } E_T;\n", encoding="utf-8")
    (tmp_path / "a.c").write_text('#include "t.h"\nstatic E_T g_e;\nvoid f(E_T m)\n{\n    g_e = m;\n}\n', encoding="utf-8")
    sec = generate_uds_source_sections(str(tmp_path))
    assert key in sec
    if key == "enum_domains":
        assert sec[key]["E_T"]["values"] == [0, 1]
        f = next(i for i in sec["function_details"].values() if isinstance(i, dict) and i.get("name") == "f")
        assert f["param_value_domains"]["m"]["values"] == [0, 1]
