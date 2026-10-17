"""R71 (N77) — 경계값의 타입은 선언이 정한다: 포인터는 가리키는 타입, 한정자는 걷고, 모르는 타입은 값을 지어내지 않는다.

실측(KJPDS02, 2026-09-19, unit 1,146 · 변수 13,081칸): 파라미터는 타입 출처가 없어 전부 이름 패턴·기본값(uint8)으로 갔다 —
`bool ADC_EnUser` 가 0/127/255, `U16 *Values` 가 uint8, `const ParamMapEntry_t *pt` 가 0/127/255, `void *` 전역 12개 전부 uint8.
STS 의 `_generate_simple_steps` 는 `[IN] bool Val` 통째를 변수명으로 써 `[IN] bool Val=255` 를 찍었다(R67 관찰).
"""
from __future__ import annotations

import pytest

from generators.suts import (
    _UNKNOWN_TYPE,
    _normalize_type,
    _param_decl_types,
    collect_unit_functions,
    generate_sequences,
    generate_suts_quality_report,
    get_boundary_values,
    infer_variable_type,
)

# ─── 1. 선언 → 타입 키 ─────────────────────────────────────────────────────────

class TestNormalizeType:
    @pytest.mark.parametrize("raw, expected", [
        ("U16*", "uint16_t"),                      # 포인터는 가리키는 타입
        ("U16 *", "uint16_t"),
        ("l_u8 *", "uint8_t"),
        ("__far U8 *", "uint8_t"),                 # 메모리 한정자
        ("volatile uint8_t", "uint8_t"),           # cv 한정자
        ("const unsigned short", "uint16_t"),
        ("U8[8]", "uint8_t"),                      # 배열은 원소 타입
        ("bool", "bool"),
        ("BOOL", "bool"),
        ("l_bool", "bool"),
        ("float", "float"),
        ("uint32_t", "uint32_t"),
        ("int8", "int8_t"),
        ("unsigned short int", "uint16_t"),
    ])
    def test_declared_scalars_and_pointees(self, raw, expected):
        assert _normalize_type(raw) == expected

    @pytest.mark.parametrize("raw", ["void *", "void", "const ParamMapEntry_t *", "ST_SAFE_WRITE_QUEUE", "enum en_g_DoorState",
                                     "LinTpMessageType *", "EEPROM_TAddress_Const", "l_ifc_handle", "void (*)(void)"])
    def test_unknown_declarations_are_unknown_not_uint8(self, raw):
        """선언은 있는데 우리가 모르는 타입 — `""` 로 떨어뜨리면 이름 패턴·기본값이 uint8 을 지어낸다."""
        assert _normalize_type(raw) == _UNKNOWN_TYPE

    @pytest.mark.parametrize("raw", ["struct ST_Bits *", "T_InhibitTime", "Bitmask_t", "tBitField", "ST_Orbit",
                                     "PointerType", "uint8_t_ptr_t", "MyBoolean_t"])
    def test_no_substring_match_on_aggregate_or_typedef_names(self, raw):
        """(리뷰 C1) 부분문자열로 맞추면 `ST_Bits`·`T_InhibitTime` 이 `bit`(0/1), `PointerType` 이 `int` 가 된다 —
        포인터를 uint8 로 접던 결함을 bool 로 접는 결함으로 바꾸는 것이다."""
        assert _normalize_type(raw) == _UNKNOWN_TYPE

    @pytest.mark.parametrize("raw", ["int", "unsigned", "unsigned int", "long", "unsigned long", "char", "double", "signed"])
    def test_width_ambiguous_c_types_are_unknown(self, raw):
        """(리뷰 W1·W2) `int` 는 S12Z 계열에서 16비트다 — 폭을 모르는 이름에 32비트 경계를 적지 않는다. `char` 는 부호가
        구현 정의, `double` 은 경계표가 없다."""
        assert _normalize_type(raw) == _UNKNOWN_TYPE

    def test_empty_declaration_is_empty(self):
        assert _normalize_type("") == "" and _normalize_type("   ") == ""


class TestBoundaryValues:
    def test_unknown_has_no_boundary_values(self):
        assert get_boundary_values(_UNKNOWN_TYPE) == {}

    def test_known_and_legacy_fallback_unchanged(self):
        """`uint8_t` 표는 그대로, 타입 키가 아닌 문자열은 종전대로 기본 경계(기존 계약 — `test_generators_suts.py`)."""
        assert get_boundary_values("uint8_t")["max"] == 255
        assert get_boundary_values("completely_unknown_type")["max"] == 255


class TestInferVariableType:
    def test_declared_unknown_does_not_fall_to_name_pattern_or_default(self):
        assert infer_variable_type("ADC0CBP", {"ADC0CBP": "void *"}) == _UNKNOWN_TYPE
        assert infer_variable_type("u8g_Struct", {"u8g_Struct": "ST_X"}) == _UNKNOWN_TYPE, "이름에 u8 이 있어도 선언이 이긴다"

    def test_pointer_declaration_gives_the_pointee(self):
        assert infer_variable_type("Values", {"Values": "U16*"}) == "uint16_t"
        assert infer_variable_type("p", {"p": "l_u8 *"}) == "uint8_t"

    def test_member_paths_keep_the_name_pattern_route(self):
        """`s.Word` 는 캐시 키가 아니다 — 구조체 root 가 unknown 이어도 멤버는 이름 패턴(WORD→uint16)이 맡는다."""
        assert infer_variable_type("_ADC0CTL.Word", {"_ADC0CTL": "ADC0CTLSTR"}) == "uint16_t"

    def test_undeclared_name_keeps_the_default(self):
        """선언이 없는 이름의 기본값(uint8)은 이 라운드가 바꾸지 않는다(N92 정책 축)."""
        assert infer_variable_type("someRandomVar", {}) == "uint8_t"


# ─── 2. 파라미터 선언 타입 ─────────────────────────────────────────────────────

class TestParamDeclTypes:
    def test_roots_and_types(self):
        got = _param_decl_types(["[IN] U16 *Values", "[IN] bool Val (idx: i)", "[OUT] return U8",
                                 "[INOUT] ST_Q* pst_Queue->ast_Queue", "[IN] const ParamMapEntry_t *pt_Entry",
                                 "/* [IN] */ l_u8 msg_length", "[IN] Val"])
        assert got["Values"] == "U16 *"
        assert got["Val"] == "bool", "주석형 꼬리 `(idx: i)` 는 이름이 아니다"
        assert "return" not in got
        assert got["pst_Queue"] == "ST_Q *"
        assert got["pt_Entry"] == "const ParamMapEntry_t *"
        assert got["msg_length"] == "l_u8"
        assert len(got) == 5, "타입 없는 `[IN] Val` 은 항목이 아니다"

    def test_comment_block_garbage_is_not_a_declaration(self):
        """(리뷰 W3) 이름 축과 같은 shape·길이 가드 — Processor Expert 주석 블록이 통째로 딸려온 문자열을 타입으로 등록하지 않는다."""
        got = _param_decl_types(["[IN] void) * * This method is implemented as a macro", "[IN] " + "x" * 130 + " y",
                                 "[IN] U8 ok"])
        assert got == {"ok": "U8"}, got

    def test_unit_carries_param_types(self):
        d = {"SwUFn_0101": {"id": "SwUFn_0101", "name": "Fn", "prototype": "void Fn(bool Val, U16 *Values)",
                            "inputs": ["[IN] bool Val", "[IN] U16 *Values"], "outputs": [],
                            "globals_global": [], "globals_static": [], "logic_flow": []}}
        u = collect_unit_functions(d, sds_map={})[0]
        assert u["param_types"] == {"Val": "bool", "Values": "U16 *"}


# ─── 3. 시퀀스 ────────────────────────────────────────────────────────────────

def _unit(**kw):
    base = {"fid": "SwUFn_0101", "name": "Fn", "prototype": "void Fn(void)", "input_vars": [], "output_vars": [],
            "indirect_vars": [], "logic_flow": [], "calls_list": [], "param_types": {}}
    base.update(kw)
    return base


class TestSequences:
    def test_param_declaration_beats_global_cache_and_bool_is_zero_one(self):
        u = _unit(input_vars=["Val", "Values"], param_types={"Val": "bool", "Values": "U16 *"})
        seqs = generate_sequences(u, 6, type_cache={"Val": "uint8_t"})
        by = {s["strategy"]: s for s in seqs}
        assert by["BV_MAX"]["inputs"]["Val"] == "0x1", by["BV_MAX"]["inputs"]
        assert by["BV_MAX"]["inputs"]["Values"] == 65535, "포인터는 가리키는 타입(U16)의 경계"
        assert u["var_types"] == {"Val": "bool", "Values": "uint16_t"} and u["unknown_type_vars"] == []

    def test_unknown_typed_var_is_left_blank_not_fabricated(self):
        u = _unit(input_vars=["Val", "pt_Entry"], output_vars=["pt_Out"],
                  param_types={"Val": "bool", "pt_Entry": "const ParamMapEntry_t *", "pt_Out": "void *"})
        seqs = generate_sequences(u, 24, type_cache={})
        assert seqs, "시퀀스 자체는 나온다"
        for s in seqs:
            assert "pt_Entry" not in s["inputs"] and "pt_Out" not in s["expected"], (s["strategy"], s["inputs"], s["expected"])
            assert "pt_Entry=" not in s["description"], "라벨도 모르는 타입을 토글한다고 말하지 않는다(COND_COMB)"
        assert sorted(u["unknown_type_vars"]) == ["pt_Entry", "pt_Out"]
        assert sum(1 for s in seqs if s["strategy"].startswith("COND_COMB_")) == 1, "토글 대상은 타입을 아는 Val 하나"

    def test_no_io_unit_indirect_globals_of_unknown_type_are_blank_and_recorded(self):
        """(리뷰 C2) I/O 없는 unit 의 간접 전역 경로 — `const ParamMapEntry_t *` 전역이 NORMAL 0 / ERROR 256 을 받았고,
        조기 return 이라 `var_types` 가 없어 품질 리포트가 그 unit 을 0 으로 오보했다."""
        u = _unit(input_vars=[], output_vars=[], indirect_vars=["pt_Entry", "u8g_Cnt"], prototype="void Fn(void)")
        seqs = generate_sequences(u, 6, type_cache={"pt_Entry": "const ParamMapEntry_t *", "u8g_Cnt": "U8"})
        by = {s["strategy"]: s for s in seqs}
        assert "pt_Entry" not in by["NORMAL_CALL"]["inputs"] and "pt_Entry" not in by["ERROR_PATH"]["expected"]
        assert by["ERROR_PATH"]["inputs"]["u8g_Cnt"] == 256
        assert u["unknown_type_vars"] == ["pt_Entry"] and u["var_types"]["u8g_Cnt"] == "uint8_t"

    def test_unknown_typed_indirect_global_is_not_toggled(self):
        """(리뷰 C2) GLOBAL_n / VOID_SIDE_EFFECT 경로 — `void *` 전역이 `{pt_G: 0}` 로 서지 않는다."""
        u = _unit(input_vars=["n"], output_vars=[], indirect_vars=["pt_G", "u8g_Flag"], param_types={"n": "U8"})
        seqs = generate_sequences(u, 24, type_cache={"pt_G": "void *", "u8g_Flag": "U8"})
        labels = " | ".join(s["description"] for s in seqs)
        assert "pt_G=" not in labels and all("pt_G" not in s["inputs"] and "pt_G" not in s["expected"] for s in seqs)
        assert any(s["strategy"].startswith("GLOBAL_") and "u8g_Flag" in s["inputs"] for s in seqs)
        assert "pt_G" in u["unknown_type_vars"]

    def test_impact_draft_resolver_returns_none_for_unknown_declarations(self):
        """(리뷰 C3) 영향도 초안의 `resolve_var_type` 은 미상을 `None` 으로 낸다 — 센티널 `unknown` 이 프론트 `unknownTypes`
        배너를 비껴가 "타입 'unknown'" 으로 새면 안 된다. 선언이 구조체면 어노테이션·이름 규칙으로도 내려가지 않는다."""
        from workflow.impact_doc_draft import resolve_var_type

        assert resolve_var_type("g_DoorState", {"g_DoorState": "en_g_DoorState"}) is None
        assert resolve_var_type("u16g_Addr", {"u16g_Addr": "EEPROM_TAddress"}, annot_types={"u16g_Addr": "uint16_t"}) is None
        assert resolve_var_type("u8g_Counter", {"u8g_Counter": "U32"}) == {"type": "uint32_t", "source": "globals_map"}

    def test_loop_var_falls_back_to_a_typed_input(self):
        u = _unit(input_vars=["p", "n"], param_types={"p": "void *", "n": "U8"},
                  logic_flow=[{"type": "loop", "condition": "i < count"}])
        seqs = generate_sequences(u, 24, type_cache={})
        loop = [s for s in seqs if s["strategy"] == "LOOP_MAX"]
        assert loop and loop[0]["inputs"].get("n") == 255 and "p=" not in loop[0]["description"], loop

    def test_all_inputs_unknown_gives_sequences_with_empty_inputs(self):
        u = _unit(input_vars=["p"], param_types={"p": "void *"})
        seqs = generate_sequences(u, 6, type_cache={})
        assert seqs and all(not s["inputs"] for s in seqs)

    def test_global_cache_is_not_mutated_by_param_types(self):
        cache = {"g": "uint16_t"}
        u = _unit(input_vars=["g", "Val"], param_types={"Val": "bool"})
        generate_sequences(u, 3, type_cache=cache)
        assert cache == {"g": "uint16_t"}

    def test_validation_warning_separates_deliberate_blanks(self):
        """(리뷰 W5) 검증기의 "I/O 없는 TC" 는 시트만 본다 — 일부러 비운 칸의 수를 경고 옆에 적어 두 0 을 갈라 읽게 한다."""
        from pathlib import Path

        from generators.suts import _note_unknown_type_slots

        v: dict = {"warnings": ["58/933 TCs lack I/O variables"]}
        _note_unknown_type_slots(v, {"unknown_type_var_slots": 613, "units_with_unknown_type_vars": 334})
        assert any("613개(334 unit)" in w for w in v["warnings"]), v
        v2: dict = {}
        _note_unknown_type_slots(v2, {"unknown_type_var_slots": 0})
        assert not v2.get("warnings"), "0 이면 적지 않는다"
        src = (Path(__file__).resolve().parents[2] / "generators" / "suts.py").read_text(encoding="utf-8")
        assert "_note_unknown_type_slots(validation, quality)" in src[src.index("def generate_suts("):]

    def test_quality_report_counts_unknown_slots_and_type_distribution(self):
        units = [
            _unit(fid="a", name="a", var_types={"x": "uint8_t", "p": _UNKNOWN_TYPE}, unknown_type_vars=["p"]),
            _unit(fid="b", name="b", var_types={"y": "bool"}, unknown_type_vars=[]),
        ]
        q = generate_suts_quality_report(units, {}, 2)
        assert q["var_type_distribution"] == {"uint8_t": 1, _UNKNOWN_TYPE: 1, "bool": 1}
        assert q["unknown_type_var_slots"] == 1 and q["units_with_unknown_type_vars"] == 1


# ─── 4. STS 단순 스텝 ─────────────────────────────────────────────────────────

class TestStsSimpleSteps:
    def test_split_param_decl(self):
        from generators.sts import _split_param_decl

        assert _split_param_decl("[IN] const U16 *Values (idx: i)") == ("const U16 *", "Values")
        assert _split_param_decl("[IN] bool Val") == ("bool", "Val")
        assert _split_param_decl("[IN] EEPROM_TAddress Addr (idx: index)") == ("EEPROM_TAddress", "Addr")
        assert _split_param_decl("Val") == ("", "Val")
        assert _split_param_decl("") == ("", "")

    def test_bool_param_gets_zero_one_and_a_bare_name(self):
        from generators.sts import _classify_steps, _generate_simple_steps

        tcs = _generate_simple_steps({"name": "f", "inputs": ["[IN] bool Val"], "calls_list": []})
        assert len(tcs) == 3
        acts = [s["action"] for s in tcs[1]]
        assert any("Val=0" in a for a in acts) and any("Val=1" in a for a in acts), acts
        assert not any("[IN] bool Val=" in a for a in acts), "선언 문자열 통째가 변수명으로 쓰였다"
        assert _classify_steps(tcs[1])[1] == "BAA"

    def test_unknown_typed_params_give_no_boundary_tc(self):
        from generators.sts import _generate_simple_steps

        tcs = _generate_simple_steps({"name": "f", "inputs": ["[IN] void *p", "[IN] EEPROM_TAddress Addr (idx: index)"],
                                      "calls_list": []})
        assert len(tcs) == 1, "경계값을 아는 입력이 하나도 없으면 경계·범위초과 TC 를 만들지 않는다"
        assert not any("(idx" in s["action"] or "[IN]" in s["action"] for s in tcs[0]), [s["action"] for s in tcs[0]]
        assert any("void * p" in s["action"] and "EEPROM_TAddress Addr" in s["action"] for s in tcs[0]), \
            "값을 못 만든 입력은 선언(타입 이름)으로 표기한다"

    def test_pointer_to_scalar_uses_the_pointee(self):
        from generators.sts import _generate_simple_steps

        tcs = _generate_simple_steps({"name": "f", "inputs": ["[IN] U16 *Values"], "calls_list": []})
        assert any("Values=65535" in s["action"] for s in tcs[1]), [s["action"] for s in tcs[1]]
