"""R2b (P1/G2) — source oracle over the project C context (`generators/c_source_oracle.py`).

Expected values are what a C compiler for a 16-bit-int target computes (the same programs are checked with
clang ``--target=msp430`` constant evaluation by `scripts/source_oracle_clang_check.py`; the last test here runs
that check when clang is installed).
"""
from __future__ import annotations

import os
import shutil

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs
from generators.test_evidence import apply_sequence_evidence

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned short U16S;
typedef unsigned int U16;
typedef unsigned long U32;
typedef signed char S8;
typedef signed int S16;
typedef signed long S32;
typedef float F32;
#endif
"""


def _p(name):
    return os.path.join(ROOT, name)


def _scope(text, extra=None):
    files = {_p("common.h"): COMMON, _p("unit.c"): text}
    files.update({_p(k): v for k, v in (extra or {}).items()})
    context = cpc.build_project_context(files)
    return cpc.build_scopes(context, [_p("unit.c")])[_p("unit.c")]


def _unit(text, name, extra=None):
    return {"name": name, "source_text": text, "source_path": _p("unit.c"), "source_text_complete": True,
            "project_scope": _scope(text, extra)}


def _run(text, name, inputs, outputs, extra=None):
    return evaluate_outputs(_unit(text, name, extra), [inputs], [outputs])[0]


def _values(result):
    return {k: v.get("value", "?" + v.get("reason", "")) for k, v in result["outputs"].items()}


H = '#include "common.h"\n'


# ── 16-bit C arithmetic ─────────────────────────────────────────────────────────────────────────

def test_unsigned_int_arithmetic_wraps_at_16_bits():
    text = H + "U16 g_out;\nvoid f(U16 a, U16 b) { g_out = a + b; }\n"
    assert _values(_run(text, "f", {"a": 65535, "b": 2}, ["g_out"])) == {"g_out": 1}


def test_small_types_promote_to_int_then_convert_on_assignment():
    text = H + "U16 g_w; U8 g_n;\nvoid f(U8 a, U8 b) { g_w = a + b; g_n = a + b; }\n"
    assert _values(_run(text, "f", {"a": 200, "b": 100}, ["g_w", "g_n"])) == {"g_w": 300, "g_n": 44}


def test_signed_overflow_on_a_16_bit_int_refuses_the_whole_evaluation():
    text = H + "S16 g_out;\nvoid f(S16 a) { g_out = a + 1; }\n"
    result = _run(text, "f", {"a": 32767}, ["g_out"])
    assert result["status"] == "unsupported" and result["reason"] == "undefined_behavior:signed_overflow"


def _possible_ub(text, inputs, outputs):
    result = _run(text, "f", inputs, outputs)
    return result, set(result.get("possible_undefined_behavior") or ())


def test_an_unknown_operand_that_may_overflow_signed_int_is_disclosed_as_possible_ub():
    # KJPDS02_PV ``s_DoorStopCaseCheck``: ``s16g_ApiIn_Pos50Deg - s16t_Position_100`` with the callee's return unknown
    # overflows a 16-bit int at -32768 - 90 (clang: "value -32858 is outside the range"). The unconditional writes after
    # it were derived as if the run were defined — now they carry the disclosure.
    text = H + ("S16 g_pos; U8 g_flag; U16 conv(U16 a);\n"
                "void f(void) { S16 p = (S16)conv(31U); if (g_pos >= (S16)(g_pos - p)) { g_flag = 2U; } g_flag = 0U; }\n")
    result, ub = _possible_ub(text, {"g_pos": -32768}, ["g_flag"])
    assert result["outputs"]["g_flag"] == {"value": 0, "basis": "assigned"}
    assert "signed_overflow_unknown_operand" in ub and "possible_ub=" in result["reason"]


@pytest.mark.parametrize("body, expect", [
    ("g_i = g_a + g_b;", False),                    # U8 + U8 ≤ 510: no 16-bit int overflow
    ("g_u = g_w - 1U;", False),                     # unsigned int wraps, defined
    ("g_i = g_s - 1;", True),                       # S16 - 1 at -32768
    ("g_i = g_s * 2;", True),
    ("g_i = -g_s;", True),                          # -(-32768)
    ("g_i = g_s / -1;", True),                      # INT_MIN / -1
    ("g_i = g_s / 2;", False),
    ("g_i = g_a << 2;", False),                     # 255 << 2 = 1020 fits
    ("g_i = g_a << 8;", True),                      # 255 << 8 past the sign bit of a 16-bit int
    ("g_l = (S32)g_s * 2L;", False),                # long arithmetic: 32 bits hold it
    ("g_i = (g_s > 0) ? 1 : 2;", False),            # comparisons never overflow
    ("g_l = (S32)g_s * 1000L + g_s;", False),       # the interval survives the cast and the product
    ("g_i = g_a * 100;", False),                    # 255 * 100 = 25500
    ("g_i = g_a * 200;", True),                     # 51000
    # [-128, 127] stored in a U8 wraps to [0, 255]: the narrower interval must not be trusted after the store
    ("S16 d = (S16)g_a - 128; U8 u = d; g_i = u * 200;", True),
    ("S16 d = (S16)g_a - 128; g_i = d * 200;", False),
    # review round 6 C1: an operator's result is not its operand — the operand's interval must not ride along
    ("g_i = ((S16)g_a | 0x7F00) + 32000;", True),
    ("g_i = (~(S16)g_a) - 32600;", True),
    ("g_i = ((S16)g_a << 6) + 17000;", True),
    ("g_i = ((S16)g_a / -1) - 32600;", True),
    ("g_i = ((((S16)g_a) - 300) < g_s) + 32767;", True),
    ("g_i = ((S16)g_a ? 32000 : 32001) + 1000;", True),
    ("g_i = (((S16)g_a - 300) && g_s) + 32767;", True),
    ("g_i = (S16)((S16)g_a + 65000U) - 32700;", True),
    ("S16 d = (S16)g_a | 0x7F00; g_i = d + 32000;", True),   # nor be stored with the result
    ("S16 d = (S16)g_a; S16 e = d | 0x7F00; g_i = e + 32000;", True),  # a stored interval reused by ``|``
    ("S16 d = (S16)g_a; S16 e = d; g_i = e * 100;", False),  # a plain copy keeps it (255 * 100 fits)
    # review round 6 C2: an untyped operand (a call's return value) is not proof of "cannot overflow"
    ("S16 a = g_s; g_i = a - sconv();", True),     # (``g_s - sconv()`` is refused outright: unsequenced)
    ("g_i = -sconv();", True),
    ("g_i = -32768; g_i -= sconv();", True),
    # review round 7 C1: an unknown write keeps the earlier reason, not the interval of the value it replaced
    ("g_s = (S16)g_a; ext(); g_i = g_s * 100;", True),
    ("S16 d = (S16)g_a; take(&d); g_i = d * 100;", True),
    ("g_arr[0] = (S16)g_a; *g_p = 32767; g_i = g_arr[0] * 100;", True),
    ("g_s = (S16)g_a; g_i = g_s * 100;", False),     # control: nothing wrote g_s in between
    # review round 7 W1: size_t is unsigned and at least 16 bits — against int it cannot overflow
    ("g_w = sizeof(g_s) + 1;", False),
    ("g_l = sizeof(g_s) + g_l;", True),             # against a wider signed type it may
])
def test_possible_signed_overflow_is_judged_by_operand_ranges(body, expect):
    text = H + ("S16 g_s; S16 g_i; S32 g_l; U8 g_a; U8 g_b; U16 g_w; U16 g_u; S16 g_arr[2]; S16 *g_p;\n"
                "S16 sconv(void); void ext(void); void take(S16 *p);\n"
                "void f(void) { " + body + " }\n")
    _result, ub = _possible_ub(text, {}, ["g_i"])
    assert any(u.startswith("signed_overflow_") for u in ub) is expect


def test_pointer_arithmetic_is_disclosed_under_its_own_tag_not_as_signed_overflow():
    text = H + "S16 g_arr[4]; S16 g_i;\nvoid f(S16 *q) { S16 *pp = q; pp = pp + 1; g_i = 0; }\n"
    _result, ub = _possible_ub(text, {}, ["g_i"])
    assert "pointer_arithmetic_untyped" in ub and not any(u.startswith("signed_overflow_") for u in ub)


def test_possible_overflow_under_known_operands_is_not_disclosed_it_is_computed():
    text = H + "S16 g_s; S16 g_i;\nvoid f(void) { g_i = g_s - 1; }\n"
    result, ub = _possible_ub(text, {"g_s": 5}, ["g_i"])
    assert _values(result) == {"g_i": 4} and not ub


def test_unsigned_int_against_negative_int_compares_as_unsigned():
    text = H + "U8 g_r;\nvoid f(U16 u) { if (u > -1) { g_r = 1U; } else { g_r = 2U; } }\n"
    # -1 converts to 65535 (unsigned int): 5 > 65535 is false.
    assert _values(_run(text, "f", {"u": 5}, ["g_r"])) == {"g_r": 2}


def test_long_arithmetic_uses_32_bits():
    text = H + "U32 g_l;\nvoid f(U16 a) { g_l = (U32)a * 1000UL; }\n"
    assert _values(_run(text, "f", {"a": 60000}, ["g_l"])) == {"g_l": 60000000}


# ── unknowns and paths ──────────────────────────────────────────────────────────────────────────

def test_branches_on_an_unset_global_run_both_arms_and_only_agreement_is_derived():
    text = H + ("U8 g_in; U8 g_same; U8 g_diff;\n"
                "void f(void) { if (g_in > 3U) { g_same = 1U; g_diff = 1U; } else { g_same = 1U; g_diff = 2U; } }\n")
    result = _run(text, "f", {}, ["g_same", "g_diff"])
    assert result["outputs"]["g_same"] == {"value": 1, "basis": "assigned"}
    assert result["outputs"]["g_diff"]["reason"].startswith("path_dependent:branch_on_unknown:initial_value_not_in_inputs:g_in")


def test_an_output_no_path_writes_is_its_input_and_is_marked_unchanged():
    text = H + "U8 g_a; U8 g_b;\nvoid f(U8 x) { if (x == 1U) { g_a = 9U; } }\n"
    result = _run(text, "f", {"x": 0, "g_a": 4}, ["g_a", "g_b"])
    assert result["outputs"]["g_a"] == {"value": 4, "basis": "unchanged_input"}
    assert result["outputs"]["g_b"]["reason"] == "initial_value_not_in_inputs:g_b"


def test_an_input_outside_its_declared_type_is_not_executable():
    text = H + "U8 g_out;\nvoid f(U8 x) { g_out = x; }\n"
    assert _run(text, "f", {"x": -1}, ["g_out"])["outputs"]["g_out"]["reason"] == "input_outside_declared_type:x"


def test_volatile_objects_are_never_derived():
    text = H + "volatile U8 g_v; U8 g_c;\nvoid f(void) { g_v = 3U; g_c = g_v; }\n"
    values = _values(_run(text, "f", {}, ["g_v", "g_c"]))
    assert values == {"g_v": "?volatile_object:g_v", "g_c": "?volatile_object:g_v"}


# ── calls ───────────────────────────────────────────────────────────────────────────────────────

def test_a_callee_havocs_only_what_its_write_closure_names():
    text = H + ("U8 g_a; U8 g_b;\nstatic void w(void) { g_a = 0U; }\nstatic void v(void) { w(); }\n"
                "void f(void) { g_a = 1U; g_b = 2U; v(); }\n")
    result = _run(text, "f", {}, ["g_a", "g_b"])
    assert result["outputs"]["g_a"]["reason"] == "written_by_callee:v:g_a"
    assert result["outputs"]["g_b"]["value"] == 2


def test_an_unknown_callee_havocs_every_global_but_not_a_local_that_never_escaped():
    text = H + "U8 g_a;\nextern void lib(void);\nU8 f(U8 x) { U8 r = x + 1U; g_a = 1U; lib(); return r; }\n"
    result = _run(text, "f", {"x": 4}, ["return", "g_a"])
    assert result["outputs"]["return"]["value"] == 5
    assert result["outputs"]["g_a"]["reason"] == "unknown_callee:lib"


def test_a_local_whose_address_escaped_is_havoced_by_the_call():
    text = H + "extern void lib(U8 *p);\nU8 f(void) { U8 r = 1U; lib(&r); return r; }\n"
    assert _run(text, "f", {}, ["return"])["outputs"]["return"]["reason"] == "unknown_callee:lib"


def test_a_local_array_that_decayed_is_reached_by_a_later_pointer_write():
    # ``(U8 *)buf`` / ``q = buf`` let a pointer reach the local array without any ``&`` (review: escape by decay).
    text = H + ("static void clr(U8 *p) { p[0] = 0U; }\n"
                "U8 f(void) { U8 buf[2] = {1U, 2U}; U8 keep = 3U; clr((U8 *)buf); return buf[1] + keep; }\n"
                "U8 g(void) { U8 buf[2] = {1U, 2U}; U8 *q = buf; q[1] = 9U; return buf[1]; }\n")
    assert _run(text, "f", {}, ["return"])["outputs"]["return"]["reason"] == "callee_pointer_write:clr:pointer_write"
    assert _run(text, "g", {}, ["return"])["outputs"]["return"]["reason"] == "subscript_write_through_pointer_or_aggregate"


def test_a_callee_that_only_reads_through_a_pointer_leaves_the_passed_array_known():
    text = H + ("U8 g_buf[2];\nstatic U8 sum(const U8 *p) { return p[0] + p[1]; }\n"
                "void f(void) { g_buf[0] = 4U; (void)sum(g_buf); }\n")
    assert _run(text, "f", {}, ["g_buf[0]"])["outputs"]["g_buf[0]"] == {"value": 4, "basis": "assigned"}


def test_a_callee_writing_through_a_pointer_reaches_arrays_and_address_taken_objects_only():
    # ``p[0] = 0U`` writes through the pointer — the closure used to drop it with the shadowed parameter name.
    # A pointer can only point at an array, an object whose address was taken somewhere, or an escaped local.
    text = H + ("U8 g_a; U8 g_t; U8 g_buf[2]; U8 *g_p;\nstatic void clr(U8 *p) { p[0] = 0U; }\n"
                "void keep(void) { g_p = &g_t; }\nvoid f(void) { g_a = 1U; g_t = 1U; g_buf[1] = 1U; clr(g_p); }\n")
    result = _run(text, "f", {}, ["g_a", "g_t", "g_buf[1]"])
    assert result["outputs"]["g_a"]["value"] == 1
    assert result["outputs"]["g_t"]["reason"] == "callee_pointer_write:clr:pointer_write"
    assert result["outputs"]["g_buf[1]"]["reason"] == "callee_pointer_write:clr:pointer_write"


def test_a_direct_write_through_a_pointer_parameter_reaches_the_same_objects():
    text = H + "U8 g_a; U8 g_buf[2];\nvoid f(U8 *p) { g_a = 1U; g_buf[0] = 2U; *p = 0U; }\n"
    result = _run(text, "f", {}, ["g_a", "g_buf[0]"])
    assert result["outputs"]["g_a"]["value"] == 1
    assert result["outputs"]["g_buf[0]"]["reason"] == "write_through_pointer"


def test_the_call_return_value_is_unknown():
    text = H + "static U8 get(void) { return 3U; }\nU8 f(void) { return get(); }\n"
    assert _run(text, "f", {}, ["return"])["outputs"]["return"]["reason"] == "call_return_value:get"


# ── macros, constants, arrays ───────────────────────────────────────────────────────────────────

def test_integer_macros_aliases_and_function_like_macros_expand_at_the_use_site():
    text = H + ("#define LIMIT ((U8)10U)\n#define OUT_ALIAS g_out\n#define MAX(a, b) (((a) > (b)) ? (a) : (b))\n"
                "U8 g_out; U8 g_m;\nvoid f(U8 x) { if (x > LIMIT) { OUT_ALIAS = 1U; } g_m = MAX(x, 3U); }\n")
    assert _values(_run(text, "f", {"x": 11}, ["g_out", "g_m"])) == {"g_out": 1, "g_m": 11}


def test_an_unparenthesized_macro_body_has_no_value_of_its_own():
    text = H + "#define TWO 1U + 1U\nU8 g_out;\nvoid f(void) { g_out = TWO * 3U; }\n"
    assert _run(text, "f", {}, ["g_out"])["outputs"]["g_out"]["reason"].startswith("macro_body_not_an_operand:TWO")


def test_global_array_elements_are_outputs_and_an_out_of_bounds_index_is_undefined():
    text = H + "U16 g_arr[4];\nvoid f(U8 i) { g_arr[i] = 7U; }\n"
    result = _run(text, "f", {"i": 2, "g_arr[1]": 5}, ["g_arr[2]", "g_arr[1]"])
    assert _values(result) == {"g_arr[2]": 7, "g_arr[1]": 5}
    assert _run(text, "f", {"i": 4}, ["g_arr[0]"])["reason"] == "undefined_behavior:array_index_out_of_bounds"


def test_a_const_lookup_table_is_read_from_its_initializer():
    text = H + "static const U8 k_tab[4] = {10U, 20U, 30U};\nU8 f(U8 i) { return k_tab[i]; }\n"
    assert _values(_run(text, "f", {"i": 1}, ["return"])) == {"return": 20}
    assert _values(_run(text, "f", {"i": 3}, ["return"])) == {"return": 0}  # C zero-fills the rest


def test_preprocessor_arms_inside_the_body_follow_the_unit_configuration():
    text = H + "#define VARIANT_B 1\nU8 g_out;\nvoid f(void) {\n#if VARIANT_B\n g_out = 2U;\n#else\n g_out = 3U;\n#endif\n}\n"
    assert _values(_run(text, "f", {}, ["g_out"])) == {"g_out": 2}
    undecided = H + "U8 g_out;\nvoid f(void) {\n#ifdef FROM_BUILD\n g_out = 2U;\n#endif\n}\n"
    assert _run(undecided, "f", {}, ["g_out"])["reason"] == "conditional_compilation_unresolved"


# ── statements ──────────────────────────────────────────────────────────────────────────────────

def test_loops_iterate_with_concrete_bounds():
    text = H + "U8 f(U8 n) { U8 i; U8 s = 0U; for (i = 0U; i < n; i++) { s += 2U; } return s; }\n"
    assert _values(_run(text, "f", {"n": 5}, ["return"])) == {"return": 10}


def test_switch_falls_through_until_break():
    text = H + ("U8 g_out;\nvoid f(U8 m) { g_out = 0U; switch (m) { case 1U: g_out += 1U; case 2U: g_out += 2U; break;"
                " default: g_out = 9U; break; } }\n")
    assert _values(_run(text, "f", {"m": 1}, ["g_out"])) == {"g_out": 3}
    assert _values(_run(text, "f", {"m": 2}, ["g_out"])) == {"g_out": 2}
    assert _values(_run(text, "f", {"m": 7}, ["g_out"])) == {"g_out": 9}


def test_a_local_shadowing_a_global_does_not_write_the_global():
    text = H + "U8 g;\nvoid f(void) { U8 g = 5U; (void)g; }\n"
    assert _run(text, "f", {"g": 1}, ["g"])["outputs"]["g"] == {"value": 1, "basis": "unchanged_input"}


def test_an_enumeration_objects_arithmetic_is_known_only_when_every_underlying_type_agrees():
    text = H + ("typedef enum { ST_A, ST_B } ST_T;\nST_T g_st; S16 g_x; U8 g_eq;\n"
                "void f(void) { g_eq = (g_st == ST_B) ? 1U : 0U; g_x = g_st - 2; }\n")
    values = _values(_run(text, "f", {"g_st": 1}, ["g_eq", "g_x"]))
    assert values["g_eq"] == 1
    assert values["g_x"] == "?enum_object_type_implementation_defined"


def test_chained_assignment_to_different_objects_is_defined():
    text = H + "U8 g_a; U8 g_b;\nvoid f(void) { g_a = g_b = 3U; }\n"
    assert _values(_run(text, "f", {}, ["g_a", "g_b"])) == {"g_a": 3, "g_b": 3}


@pytest.mark.parametrize("body, reason", [
    ("U8 f(U8 x) { return x + x++; }", "unsequenced_side_effects"),
    ("U8 f(U8 i) { U8 a[4] = {0U}; a[i] = i++; return a[0]; }", "unsequenced_side_effects"),
    ("U8 f(U8 x) { x = x++; return x; }", "unsequenced_side_effects"),
    ("U8 f(U8 c) { g_a = (c ? 1U : 2U) + g_a++; return 0U; }", "unsequenced_side_effects"),   # review W2 ③
    ("U8 f(void) { g_a = INC(g_a); return 0U; }", "macro_side_effect_in_expression:INC"),      # review W2 ①
    ("U8 f(void) { g_a = 5U; g_z = g_a + (rd(), 0U); return 0U; }", "call_unsequenced_with_access:rd"),  # review W3
])
def test_order_dependent_full_expressions_are_refused(body, reason):
    text = H + ("#define INC(v) ((v)++)\nU8 g_a; U8 g_z;\nstatic void rd(void) { g_a = 7U; }\n" + body + "\n")
    assert _run(text, "f", {"x": 1, "i": 1, "c": 1}, ["return"])["reason"] == reason


def test_a_call_that_cannot_touch_the_other_operand_is_allowed():
    text = H + "U8 g_a; U8 g_z; U8 g_o;\nstatic void rd(void) { g_o = 7U; }\nvoid f(void) { g_a = 5U; g_z = g_a + (rd(), 0U); }\n"
    assert _values(_run(text, "f", {}, ["g_z"])) == {"g_z": 5}


def test_side_effects_under_an_unknown_condition_are_refused_even_through_a_macro():
    text = H + "U8 g_a; U8 g_in;\nextern U8 lib(void);\nvoid f(void) { if ((g_in == 1U) && (lib() == 2U)) { g_a = 1U; } }\n"
    assert _run(text, "f", {}, ["g_a"])["reason"] == "side_effect_under_unknown_condition"
    # review C2: the write is only in the expansion — the copy used to drop it
    text = H + "#define CLR (g_a = 0U)\nU8 g_a; U8 g_in; U8 g_z;\nvoid f(void) { g_a = 5U; g_z = (g_in != 0U) ? CLR : 0U; }\n"
    assert _run(text, "f", {}, ["g_a"])["reason"] in {"side_effect_under_unknown_condition",
                                                      "macro_side_effect_in_expression:CLR"}


# ── review round 1 counterexamples (each claimed a value the compiled code does not produce) ────

def test_function_like_macro_arguments_are_substituted_in_one_pass():
    text = H + "#define SUB(a, b) ((a) - (b))\nU16 g_r;\nvoid f(U16 b) { g_r = SUB(b, 1U); }\n"   # review C1
    assert _values(_run(text, "f", {"b": 5}, ["g_r"])) == {"g_r": 4}


def test_an_address_taken_in_one_arm_of_an_unknown_conditional_escapes():
    text = H + ("U8 g_in;\nU8 f(void) { U8 a = 1U; U8 b = 2U; U8 *p = (g_in != 0U) ? &a : &b; *p = 5U; return a; }\n")
    assert "value" not in _run(text, "f", {}, ["return"])["outputs"]["return"]   # review C3


@pytest.mark.parametrize("body", [
    "U8 f(void) { U8 r = 1U; U8 *ptrs[1] = { &r }; *ptrs[0] = 5U; return r; }",
    "U8 f(void) { U8 r = 1U; U8 **pp = (U8 *[]){ &r }; **pp = 6U; return r; }",
])
def test_initializer_items_run_and_their_addresses_escape(body):
    assert "value" not in _run(H + body + "\n", "f", {}, ["return"])["outputs"]["return"]   # review C4


def test_initializer_calls_havoc_what_the_callee_writes():
    text = H + ("typedef struct { U8 m; } S_T;\nU8 g_a;\nstatic U8 bump(void) { g_a = 9U; return 1U; }\n"
                "void f(void) { g_a = 1U; { S_T s = { bump() }; (void)s; } }\n")
    assert _run(text, "f", {}, ["g_a"])["outputs"]["g_a"]["reason"] == "written_by_callee:bump:g_a"


def test_a_parenthesized_write_through_a_pointer_is_a_pointer_write():
    text = H + "U8 g_buf[2];\nstatic void clr(U8 *p) { (p[0]) = 0U; }\nvoid f(void) { g_buf[0] = 4U; clr(g_buf); }\n"
    assert _run(text, "f", {}, ["g_buf[0]"])["outputs"]["g_buf[0]"]["reason"] == "callee_pointer_write:clr:pointer_write"  # C5


def test_an_address_taken_inside_a_macro_body_counts_as_taken():
    text = H + ("#define CFG_PTR (&g_cfg)\nU8 g_cfg; U8 *g_p;\nvoid init(void) { g_p = CFG_PTR; }\n"
                "static void w(void) { *g_p = 3U; }\nU8 f(void) { g_cfg = 1U; w(); return g_cfg; }\n")
    assert "value" not in _run(text, "f", {}, ["return"])["outputs"]["return"]   # review C6


def test_a_static_local_whose_address_is_stored_is_reached_by_a_later_pointer_write():
    text = H + ("U8 *g_p;\nstatic void w(void) { *g_p = 7U; }\n"
                "U8 f(U8 first) { static U8 s; s = 1U; if (first != 0U) { g_p = &s; } w(); return s; }\n")
    assert "value" not in _run(text, "f", {"first": 0}, ["return"])["outputs"]["return"]   # review W1 ①


def test_recursion_back_into_the_function_havocs_its_static_locals():
    text = H + ("U8 f(U8 n);\nstatic void g(void) { (void)f(0U); }\n"
                "U8 f(U8 n) { static U8 s; s = 1U; if (n != 0U) { g(); } return s; }\n")
    assert _run(text, "f", {"n": 1}, ["return"])["outputs"]["return"]["reason"].startswith("recursion_through:g")  # W1 ②


def test_a_conditional_with_an_enumeration_arm_has_no_known_type():
    text = H + "typedef enum { ST_A, ST_B } ST_T;\nST_T g_st; U8 g_r;\nvoid f(U8 c) { g_r = ((c ? -1 : g_st) < 0) ? 1U : 0U; }\n"
    assert "value" not in _run(text, "f", {"c": 1, "g_st": 1}, ["g_r"])["outputs"]["g_r"]   # review W4


def test_a_multi_statement_macro_under_an_unbraced_if_is_refused():
    text = H + "#define SET_BOTH g_a = 1U; g_b = 2U\nU8 g_a; U8 g_b;\nvoid f(U8 c) { if (c != 0U) SET_BOTH; }\n"
    assert _run(text, "f", {"c": 0}, ["g_b"])["reason"] == "multi_statement_macro_in_unbraced_body:SET_BOTH"  # W5


def test_a_declaration_inside_a_switch_body_does_not_leak_out():
    text = H + ("U8 t; U8 g_o;\nvoid f(U8 m) { switch (m) { case 1U: ; U8 t = 3U; (void)t; break; default: break; }"
                " g_o = t; }\n")
    assert _values(_run(text, "f", {"m": 1, "t": 7}, ["g_o"])) == {"g_o": 7}   # review W6


# ── wiring into the Test Evidence contract ──────────────────────────────────────────────────────

def test_sequence_evidence_derives_global_outputs_with_the_project_scope():
    text = H + "U8 g_out;\nU8 f(U8 x) { g_out = x + 1U; return x; }\n"
    unit = {**_unit(text, "f"), "output_vars": ["g_out", "return"]}
    seqs = apply_sequence_evidence(unit, [{"inputs": {"x": 4}, "expected": {}},
                                          {"inputs": {"x": 300}, "expected": {}}])
    assert seqs[0]["expected"] == {"g_out": 5, "return": 4}
    assert {v["status"] for v in seqs[0]["expected_evidence"].values()} == {"derived"}
    assert seqs[0]["expected_evidence"]["g_out"]["oracle_kind"] == "source"
    assert seqs[1]["expected_evidence"]["g_out"]["status"] == "unknown"
    assert seqs[1]["expected_evidence"]["g_out"]["reason"] == "input_outside_declared_type:x"
    assert "g_out" not in seqs[1]["expected"]  # an unknown output keeps its cell empty (P1 contract)


def test_sequence_evidence_without_a_matching_scope_keeps_the_restricted_oracle():
    text = "int f(int x) { return x + 1; }\n"
    seqs = apply_sequence_evidence({"name": "f", "source_text": text, "output_vars": ["return"]},
                                   [{"inputs": {"x": 2}, "expected": {}}])
    assert seqs[0]["expected"] == {"return": 3}
    stale = {**_unit(H + "U8 f(U8 x) { return x; }\n", "f"), "source_text": H + "U8 f(U8 x) { return x + 1U; }\n",
             "output_vars": ["return"]}
    seqs = apply_sequence_evidence(stale, [{"inputs": {"x": 2}, "expected": {}}])
    assert seqs[0]["expected_evidence"]["return"]["status"] == "unknown"  # a scope of another text is never used
    assert seqs[0]["expected_evidence"]["return"]["reason"].startswith("project_scope_mismatch;")  # and says so


def test_the_evidence_summary_separates_assigned_from_unchanged_outputs():
    from generators.test_evidence import summarize_expected_evidence
    text = H + "U8 g_a; U8 g_b;\nvoid f(U8 x) { g_a = x; }\n"
    unit = {**_unit(text, "f"), "output_vars": ["g_a", "g_b"]}
    seqs = apply_sequence_evidence(unit, [{"inputs": {"x": 4, "g_b": 7}, "expected": {}}])
    assert seqs[0]["expected_evidence"]["g_b"]["basis"] == "unchanged_input"
    assert seqs[0]["expected_evidence"]["g_a"]["assumptions"]
    summary = summarize_expected_evidence(seqs)
    assert (summary["derived"], summary["derived_assigned"], summary["derived_unchanged_input"]) == (2, 1, 1)


@pytest.mark.parametrize("possible_ub, message, explained", [
    (["signed_overflow_unknown_operand"], "value -32858 is outside the range of representable values of type 'int'", True),
    (["signed_overflow_untyped_operand"], "left shift of negative value -1", True),
    (["division_by_unknown"], "division by zero", True),
    (["index_unknown"], "cannot refer to element 5 of array of 2 elements in a constant expression", True),
    # a disclosure never excuses an error it cannot cause (review round 7 W1)
    (["division_by_unknown"], "read of uninitialized object is not allowed in a constant expression", False),
    (["pointer_arithmetic_untyped"], "value 40000 is outside the range of representable values of type 'int'", False),
    (["some_future_kind"], "division by zero", False),
    (["shift_by_unknown"], "shift count 16 >= width of type 'int' (16 bits)", True),
    (["shift_by_unknown"], "negative shift count -1", True),
    # review round 8 W1: a callee *named* after a shift is not a shift diagnostic
    (["signed_overflow_unknown_operand"],
     "read of uninitialized object is not allowed in a constant expression | in call to 'do_shift(0)'", False),
    (["shift_by_unknown"], "read of uninitialized object | in call to 'shift_left(0)'", False),
    ([], "division by zero", False),
])
def test_the_clang_check_sets_aside_only_errors_a_disclosed_kind_explains(possible_ub, message, explained):
    from scripts.source_oracle_clang_check import _disclosure_explains
    assert _disclosure_explains(possible_ub, message) is explained


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang (msp430 target) not installed")
def test_every_claim_here_agrees_with_clang_msp430_constant_evaluation(tmp_path):
    from scripts.source_oracle_clang_check import check_claims
    cases = [
        (H + "U16 g_out;\nvoid f(U16 a, U16 b) { g_out = a + b; }\n", "f", {"a": 65535, "b": 2}, ["g_out"]),
        (H + "U16 g_w; U8 g_n;\nvoid f(U8 a, U8 b) { g_w = a + b; g_n = a + b; }\n", "f", {"a": 200, "b": 100}, ["g_w", "g_n"]),
        (H + "U8 g_r;\nvoid f(U16 u) { if (u > -1) { g_r = 1U; } else { g_r = 2U; } }\n", "f", {"u": 5}, ["g_r"]),
        (H + "U32 g_l;\nvoid f(U16 a) { g_l = (U32)a * 1000UL; }\n", "f", {"a": 60000}, ["g_l"]),
        (H + "#define LIMIT ((U8)10U)\n#define MAX(a, b) (((a) > (b)) ? (a) : (b))\nU8 g_out; U8 g_m;\n"
             "void f(U8 x) { if (x > LIMIT) { g_out = 1U; } g_m = MAX(x, 3U); }\n", "f", {"x": 11}, ["g_out", "g_m"]),
        (H + "static const U8 k_tab[4] = {10U, 20U, 30U};\nU8 f(U8 i) { return k_tab[i]; }\n", "f", {"i": 1}, ["return"]),
        (H + "U8 f(U8 n) { U8 i; U8 s = 0U; for (i = 0U; i < n; i++) { s += 2U; } return s; }\n", "f", {"n": 5}, ["return"]),
        (H + "U8 g_out;\nvoid f(U8 m) { g_out = 0U; switch (m) { case 1U: g_out += 1U; case 2U: g_out += 2U; break;"
             " default: g_out = 9U; break; } }\n", "f", {"m": 1}, ["g_out"]),
        (H + "U8 g_a; U8 g_in;\nU8 f(U8 x) { U8 r = x; if (g_in > 3U) { g_a = 1U; } else { g_a = 1U; } return r; }\n",
         "f", {"x": 7}, ["g_a", "return"]),
    ]
    claims = []
    for text, name, inputs, outputs in cases:
        unit = _unit(text, name)
        result = evaluate_outputs(unit, [inputs], [outputs])[0]
        derived = {k: v["value"] for k, v in result["outputs"].items() if "value" in v}
        assert derived, (name, result)
        claims.append({"unit": unit, "inputs": inputs, "outputs": derived})
    total = sum(len(c["outputs"]) for c in claims)
    # Sentinels: the checker must see a wrong value, and a value that secretly depends on an unset global.
    sentinel_unit = _unit(H + "U16 g_out; U8 g_in;\nvoid f(U16 a) { g_out = a + g_in; }\n", "f")
    claims.append({"unit": sentinel_unit, "inputs": {"a": 1, "g_in": 0}, "outputs": {"g_out": 2}})
    claims.append({"unit": sentinel_unit, "inputs": {"a": 1}, "outputs": {"g_out": 1}})
    report = check_claims(claims, work_dir=str(tmp_path))
    assert report["checked"] == total + 2 and report["unchecked"] == 0, report
    assert report["mismatch"] == 2, report  # exactly the two sentinels
    assert {m["claimed"] for m in report["mismatches"]} == {2, 1}


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang (msp430 target) not installed")
def test_the_clang_check_attributes_failures_in_crlf_sources_and_tries_every_enum_type(tmp_path):
    from scripts.source_oracle_clang_check import check_claims
    # CRLF: a wrong claim is a mismatch, not an unplaceable compile error (review W7).
    crlf = _unit((H + "U16 g_out;\nvoid f(U16 a)\n{\n    g_out = a + 1U;\n}\n").replace("\n", "\r\n"), "f")
    report = check_claims([{"unit": crlf, "inputs": {"a": 1}, "outputs": {"g_out": 2}},
                           {"unit": crlf, "inputs": {"a": 1}, "outputs": {"g_out": 99}}], work_dir=str(tmp_path / "a"))
    assert (report["agree"], report["mismatch"], report["unchecked"]) == (1, 1, 0), report
    # An enumeration object compared with -1: equal for int, not for unsigned int — a claim must not pass (review W8).
    text = H + "typedef enum { ST_A, ST_B } ST_T;\nST_T g_st; U8 g_r;\nvoid f(void) { g_r = (g_st > -1) ? 1U : 0U; }\n"
    report = check_claims([{"unit": _unit(text, "f"), "inputs": {"g_st": 1}, "outputs": {"g_r": 1}}],
                          work_dir=str(tmp_path / "b"))
    assert report["mismatch"] == 1 and "enum as unsigned int" in report["mismatches"][0]["clang"], report
    # The oracle itself does not claim it.
    assert "value" not in _run(text, "f", {"g_st": 1}, ["g_r"])["outputs"]["g_r"]


def test_storing_a_call_result_into_an_array_element_is_sequenced():
    text = H + ("U8 g_buf[3]; U8 g_i;\nstatic U8 rd(U8 k) { g_i = k; return k; }\n"
                "void f(void) { U8 i; for (i = 0U; i < 3U; i++) { g_buf[i] = rd(i); } }\n"
                "void h(void) { g_buf[g_i] = rd(1U); }\n")
    assert _run(text, "f", {}, ["g_buf[0]"])["outputs"]["g_buf[0]"]["reason"] == "call_return_value:rd"
    # ...but an index the callee writes is read unsequenced with the call
    assert _run(text, "h", {"g_i": 0}, ["g_buf[0]"])["reason"] == "call_unsequenced_with_access:rd"


# ── review round 2 counterexamples ──────────────────────────────────────────────────────────────

def test_a_macro_that_cannot_be_evaluated_still_havocs_what_it_may_write():
    # round 2 A: an undecided / non-operand macro used as a whole statement or return value
    undecided = H + ("U8 g_a;\n#ifdef EXT_CFG\n#define CLR (g_a = 0U)\n#else\n#define CLR (g_a = 1U)\n#endif\n"
                     "void f(void) { g_a = 5U; CLR; }\n")
    assert "value" not in _run(undecided, "f", {}, ["g_a"])["outputs"]["g_a"]
    non_operand = H + "U8 g_a;\n#define SETA g_a = 0U\nU8 f(void) { g_a = 5U; return SETA; }\n"
    assert "value" not in _run(non_operand, "f", {}, ["g_a"])["outputs"]["g_a"]


@pytest.mark.parametrize("body", [
    "void f(void) { g_x = 1U; g_o = DBL(g_x++); }",    # the expansion evaluates g_x++ twice, unsequenced
    "U8 f(void) { g_x = 1U; return BUMP; }",           # BUMP = g_x + g_x++
])
def test_the_expansion_of_a_macro_is_checked_for_unsequenced_effects(body):
    text = H + "#define DBL(v) ((v) + (v))\n#define BUMP (g_x + g_x++)\nU8 g_x; U8 g_o;\n" + body + "\n"
    assert _run(text, "f", {}, ["g_o"])["reason"] in {"unsequenced_side_effects",   # round 2 B
                                                      "macro_in_order_dependent_expression:DBL"}


def test_direct_self_recursion_havocs_static_locals():
    text = H + "U8 f(U8 x) { static U8 s; s = x; if (x != 0U) { (void)f(0U); } return s; }\n"
    assert "value" not in _run(text, "f", {"x": 1}, ["return"])["outputs"]["return"]   # round 2 Warning A


@pytest.mark.parametrize("body", [
    "U8 f(void) { U8 b[1] = {1U}; g_o = b[0] + (fill(b), 0U); return 0U; }",      # escape in the same expression (B)
    "U8 f(void) { U8 *p = &g_x; g_x = 5U; g_o = g_x + ((*p = 9U), 0U); return 0U; }",  # pointer alias (C)
    "U8 f(void) { g_x = 3U; U8 a[2] = {g_x++, g_x}; return a[1]; }",             # initializer items (D)
    "U8 f(void) { g_x = 5U; g_o = GX + (rd(), 0U); return 0U; }",                # alias macro (E)
])
def test_order_dependence_through_escapes_aliases_and_initializers_is_refused(body):
    text = H + ("#define GX g_x\nU8 g_x; U8 g_o;\nstatic void fill(U8 *q) { q[0] = 9U; }\n"
                "static void rd(void) { g_x = 7U; }\n" + body + "\n")
    result = _run(text, "f", {}, ["g_o", "return"])
    assert result["status"] == "unsupported" and result["reason"].startswith(
        ("unsequenced_side_effects", "call_unsequenced_with_access")), result["reason"]


@pytest.mark.parametrize("macro", ["#define CFG_PTR ((U8 *)&g_cfg)\n", "#define ADDR(v) (&(v))\n#define CFG_PTR ADDR(g_cfg)\n"])
def test_addresses_taken_behind_a_cast_or_a_macro_parameter_count(macro):
    text = H + (macro + "U8 g_cfg; U8 *g_p;\nvoid init(void) { g_p = CFG_PTR; }\n"
                "static void w(void) { *g_p = 3U; }\nU8 f(void) { g_cfg = 1U; w(); return g_cfg; }\n")
    assert "value" not in _run(text, "f", {}, ["return"])["outputs"]["return"]   # round 2 F


def test_a_static_whose_address_a_macro_stores_is_escaped_from_entry():
    text = H + ("#define SAVE(v) (g_p = &(v))\nU8 *g_p;\nstatic void w(void) { *g_p = 7U; }\n"
                "U8 f(U8 first) { static U8 s; s = 1U; if (first != 0U) { SAVE(s); } w(); return s; }\n")
    assert "value" not in _run(text, "f", {"first": 0}, ["return"])["outputs"]["return"]   # round 2 X6


def test_nested_statement_macros_keep_their_locals_apart():
    text = H + ("#define INNER { U8 t = 2U; g_i = t; }\n#define OUTER { U8 t = 1U; INNER; g_o = t; }\n"
                "U8 g_o; U8 g_i;\nvoid f(void) { OUTER; }\n")
    assert _values(_run(text, "f", {}, ["g_o", "g_i"])) == {"g_o": 1, "g_i": 2}   # round 2 H


def test_a_dangling_else_after_a_macro_if_is_refused():
    text = H + "#define M if (g_a != 0U) g_a = 1U\nU8 g_a; U8 g_b;\nvoid f(U8 d) { if (d != 0U) M; else g_b = 2U; }\n"
    assert _run(text, "f", {"d": 0}, ["g_b"])["reason"] == "dangling_else_in_macro:M"   # round 2 J


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang (msp430 target) not installed")
def test_the_clang_check_never_passes_a_run_that_did_not_report_its_canary(tmp_path):
    from scripts.source_oracle_clang_check import check_claims
    unit = _unit(H + "U16 g_out;\nvoid f(U16 a) { g_out = a + 1U; }\n", "f")
    bad = check_claims([{"unit": unit, "inputs": {"a": 1}, "outputs": {"g_out": 99}}], target="bogus-unknown-triple",
                       work_dir=str(tmp_path / "a"))
    assert (bad["agree"], bad["unchecked"]) == (0, 1) and "canary_not_reported" in bad["unchecked_reasons"]  # round 2 C
    string_input = check_claims([{"unit": unit, "inputs": {"a": "0x1"}, "outputs": {"g_out": 99}}], work_dir=str(tmp_path / "b"))
    assert string_input["mismatch"] == 1   # the checker reads "0x1" as the oracle does (round 2 I)


# ── review round 3 counterexamples (gcc/clang give another value than the oracle used to claim) ──

@pytest.mark.parametrize("macro", ["#define AGAIN() ((void)f(0U))\n", "#define AGAIN() CALL_F\n#define CALL_F ((void)f(0U))\n"])
def test_recursion_through_a_macro_havocs_static_locals(macro):
    text = H + macro + "U8 f(U8 x) { static U8 s; s = x; if (x != 0U) { AGAIN(); } return s; }\n"
    assert "value" not in _run(text, "f", {"x": 1}, ["return"])["outputs"]["return"]   # round 3 C1


@pytest.mark.parametrize("body", [
    "void f(void) { g_a = 5U; g_o = g_a + (WRAP, 0U); }",          # nested object-like macro writes (C2)
    "void f(void) { g_x = 10U; g_o = GXP1 + g_x++; }",             # a macro reads what the expression writes (C3)
    "void f(void) { g_x = 5U; g_o = RDX() + (rd(), 0U); }",        # a function-like macro read, a callee write (C3)
    "void f(void) { g_x = 5U; g_o = g_x + ((*g_fp)(), 0U); }",     # a call through a function pointer (C5)
])
def test_order_dependence_hidden_in_macros_or_pointer_calls_is_refused(body):
    text = H + ("#define INNER (g_a = 7U)\n#define WRAP INNER\n#define GXP1 (g_x + 1U)\n#define RDX() (g_x)\n"
                "U8 g_a; U8 g_x; U8 g_o;\nstatic void rd(void) { g_x = 7U; }\nvoid (*g_fp)(void) = rd;\n" + body + "\n")
    result = _run(text, "f", {}, ["g_o"])
    assert result["status"] == "unsupported", result


def test_an_address_taken_through_parentheses_escapes_in_the_same_expression():
    text = H + "U8 g_o;\nstatic void set(U8 *p) { *p = 9U; }\nvoid f(void) { U8 x = 1U; g_o = x + (set(&(x)), 0U); }\n"
    assert _run(text, "f", {}, ["g_o"])["status"] == "unsupported"   # round 3 C6


@pytest.mark.parametrize("macros, init", [
    ("#define ADDR(v) (&(v))\n#define OUTER(y) ADDR(y)\n", "void init(void) { g_p = OUTER(g_cfg); }\n"),   # C7 (a)
    ("#define ADDR(v) (&(v))\n", "U8 *g_q = ADDR(g_cfg);\nvoid init(void) { g_p = g_q; }\n"),              # C7 (b)
])
def test_addresses_taken_through_nested_macros_and_file_scope_initializers_count(macros, init):
    text = H + (macros + "U8 g_cfg; U8 *g_p;\n" + init +
                "static void w(void) { *g_p = 3U; }\nU8 f(void) { g_cfg = 1U; w(); return g_cfg; }\n")
    assert "value" not in _run(text, "f", {}, ["return"])["outputs"]["return"]


def test_a_static_escaping_through_a_chain_of_object_like_macros_is_escaped():
    text = H + ("#define SP (g_p = &s)\n#define SP2 SP\nU8 *g_p;\nstatic void w(void) { *g_p = 7U; }\n"
                "U8 f(U8 first) { static U8 s; s = 1U; if (first != 0U) { SP2; } w(); return s; }\n")
    assert "value" not in _run(text, "f", {"first": 0}, ["return"])["outputs"]["return"]   # round 3 C7 (c)


@pytest.mark.parametrize("body", [
    "void f(U8 d) { if (d != 0U) while (g_c != 0U) M; else g_b = 2U; }",
    "void f(U8 d) { if (d != 0U) for (;;) M; else g_b = 2U; }",
    "void f(U8 d) { if (d != 0U) W; else g_b = 2U; }",
])
def test_a_dangling_else_at_any_depth_is_refused(body):
    text = H + ("#define M if (g_a != 0U) g_a = 1U\n#define W while (g_c != 0U) if (g_a != 0U) g_a = 1U\n"
                "U8 g_a; U8 g_b; U8 g_c;\n" + body + "\n")
    assert _run(text, "f", {"d": 0}, ["g_b"])["reason"].startswith("dangling_else_in_macro:")   # round 3 C4


def test_a_multi_statement_macro_in_an_unbraced_body_is_refused_even_on_an_untaken_path():
    text = H + "#define SET_BOTH g_a = 1U; g_b = 2U\nU8 g_a; U8 g_b;\nvoid f(U8 c) { if (c != 0U) while (g_a) SET_BOTH; }\n"
    assert _run(text, "f", {"c": 0}, ["g_b"])["reason"] == "multi_statement_macro_in_unbraced_body:SET_BOTH"


@pytest.mark.parametrize("text", [
    H + "#define tmp g_x\nU8 g_x;\nvoid f(void) { g_x = 5U; { U8 tmp = 1U; tmp = 9U; } }\n",
    H + "#define v g_x\nU8 g_x;\nvoid f(U8 v) { v = 9U; }\n",
])
def test_a_macro_name_used_as_a_declared_name_is_refused(text):
    assert _run(text, "f", {"g_x": 5}, ["g_x"])["reason"].startswith("macro_named_declarator:")   # round 3 C8


def test_a_bit_test_macro_does_not_take_the_address_of_its_operands():
    context = cpc.build_project_context({_p("common.h"): COMMON, _p("unit.c"): (
        H + "#define TEST_BIT(v, m) ((v) & (m))\n#define PTR_OF(x) ((U8 *)&x)\nU8 g_s; U8 g_o; U8 g_t;\n"
        "void f(void) { g_o = TEST_BIT(g_s, 1U); (void)PTR_OF(g_t); }\n")})
    taken = cpc.function_write_closure(context)["address_taken"]
    assert "g_s" not in taken and "g_t" in taken   # round 3 W1: only unary / pointer-cast ``&``


# ── review round 4 counterexamples ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    "void f(void) { g_i = 0U; g_arr[IDX] = g_i++; }",     # the left index hides a read of g_i (C1)
    "void f(void) { g_i = 0U; ELEM = g_i++; }",
    "void f(void) { g_i = 1U; g_arr[IDX] = rd(); }",
])
def test_a_macro_in_the_assigned_object_makes_the_right_side_order_dependent(body):
    text = H + ("#define IDX (g_i + 0U)\n#define ELEM g_arr[g_i]\nU8 g_i; U8 g_arr[4];\n"
                "static U8 rd(void) { g_i = 0U; return 9U; }\n" + body + "\n")
    assert _run(text, "f", {}, ["g_arr[0]", "g_arr[1]"])["status"] == "unsupported"   # round 4 C1


def test_a_typedef_pointer_write_conflicts_with_the_object_it_may_point_to():
    text = H + "typedef U8 *PT;\nU8 g_x; U8 g_o;\nvoid f(void) { PT q = &g_x; g_x = 5U; g_o = g_x + ((q[0] = 1U), 0U); }\n"
    assert _run(text, "f", {}, ["g_o"])["status"] == "unsupported"   # round 4 C2


@pytest.mark.parametrize("callee", [
    "static void w(void) { U8 *ps[1]; ps[0] = &g_x; ps[0][0] = 7U; }",
    "typedef struct { U8 *p; } S_T;\nstatic void w(void) { S_T a[1]; a[0].p = &g_x; a[0].p[0] = 7U; }",
    "static void w(U8 c) { if (c != 0U) { U8 g_x = 0U; (void)g_x; } g_x = 7U; }",   # C10: block shadow
])
def test_writes_the_closure_used_to_lose_are_seen_by_the_caller(callee):
    text = H + "U8 g_x; U8 g_o;\n" + callee + "\n" + (
        "void f(void) { g_x = 5U; w(" + ("1U" if "U8 c" in callee else "") + "); g_o = g_x; }\n")
    assert "value" not in _run(text, "f", {}, ["g_o"])["outputs"]["g_o"]   # round 4 C3 / C10


def test_two_expansions_of_a_statement_macro_have_their_own_static():
    text = H + "#define M do { static U8 s; U8 t = s; s = 5U; g_o = t; } while (0)\nU8 g_o;\nvoid f(void) { M; M; }\n"
    assert "value" not in _run(text, "f", {}, ["g_o"])["outputs"]["g_o"]   # round 4 C4


def test_a_multi_statement_macro_inside_another_expansion_is_refused():
    text = H + ("#define INNER g_a = 1U; g_b = 2U\n#define OUTER(c) do { if (c) INNER; } while (0)\n"
                "U8 g_a; U8 g_b;\nvoid f(U8 c) { OUTER(c); }\n")
    assert _run(text, "f", {"c": 0}, ["g_b"])["reason"] == "multi_statement_macro_in_unbraced_body:INNER"   # round 4 C5


@pytest.mark.parametrize("macro", ["#define PX ((PT)&g_x)\n", "#define PX ((U8 * const)&g_x)\n"])
def test_addresses_taken_behind_typedef_and_qualified_pointer_casts_count(macro):
    text = H + ("typedef U8 *PT;\n" + macro + "U8 g_x; U8 *g_p;\nvoid init(void) { g_p = PX; }\n"
                "static void w(void) { *g_p = 3U; }\nU8 f(void) { g_x = 1U; w(); return g_x; }\n")
    assert "value" not in _run(text, "f", {}, ["return"])["outputs"]["return"]   # round 4 C6


@pytest.mark.parametrize("text", [
    H + "U8 X;\nU8 f(void) { X = 3U; return X; }\n#define X 7U\n",
    H + "U8 g_o;\nvoid f(void) {\n#ifdef FEAT\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n#define FEAT\n",
])
def test_a_macro_defined_after_the_function_is_not_a_macro_there(text):
    assert _run(text, "f", {}, ["return"])["reason"].startswith("macro_defined_after_function:")   # round 4 C7


def test_non_ascii_characters_and_macro_arguments_inside_literals_are_not_read_as_values():
    text = H + "U16 g_o;\nvoid f(void) { g_o = 'é'; }\n"
    assert "value" not in _run(text, "f", {}, ["g_o"])["outputs"]["g_o"]   # round 4 C8
    text = H + "#define M(c) do { g_o = 'c'; } while (0)\nU8 g_o;\nvoid f(void) { M(1); }\n"
    assert _values(_run(text, "f", {}, ["g_o"])) == {"g_o": 99}   # 'c' stays 'c' (round 4 C9)


def test_pure_macro_calls_and_a_parenthesized_statement_assignment_are_not_refused():
    text = H + ("#define BIT(A, B) (((A) >> (B)) & 0x01U)\n#define CLR_X() (g_x = 0U)\nU8 g_x; U8 g_p;\n"
                "static U8 rd(void) { return 1U; }\n"
                "void f(U8 pid) { g_p = (U8)(BIT(pid, 0U) ^ BIT(pid, 1U)) + rd(); CLR_X(); }\n")
    result = _run(text, "f", {"pid": 3}, ["g_x"])
    assert result["status"] == "supported" and result["outputs"]["g_x"] == {"value": 0, "basis": "assigned"}  # round 4 W1
