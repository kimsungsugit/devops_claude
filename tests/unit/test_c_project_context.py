"""R81 (P2 R2) — project C context: target widths, macros, #if, globals, and the MC/DC engine on top of it.

Every expected value here is what a C compiler for a 16-bit-int target computes (checked against clang
``--target=msp430`` while writing these tests; ``scripts/mcdc_design_clang_oracle.py`` does the same for a tree).
"""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators.mcdc_design import build_mcdc_design, evaluate_decision, finalize_mcdc_design

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef unsigned long U32;
typedef signed char S8;
typedef signed int S16;
typedef signed long S32;
typedef float F32;
#define u8g_T_MAIN ( ( U8 )( 5U ) )
#define u8g_ON ( ( U8 )( 1U ) )
#endif
"""


def _p(name):
    return os.path.join(ROOT, name)


def _scope(main_text, headers=None, main="unit.c", extra_units=None):
    files = {_p("common.h"): COMMON, _p(main): main_text}
    files.update({_p(k): v for k, v in (headers or {}).items()})
    files.update({_p(k): v for k, v in (extra_units or {}).items()})
    context = cpc.build_project_context(files)
    return context, cpc.build_scopes(context, [_p(main)])[_p(main)]


def _unit(text, name, scope, inputs=()):
    # No fixed SUTS row in these engine tests: globals the engine binds may join the vector (inventory mode).
    return {"name": name, "input_vars": list(inputs), "source_text": text, "source_path": _p("unit.c"),
            "source_text_complete": True, "project_scope": scope, "mcdc_free_globals": True}


# ── target model ────────────────────────────────────────────────────────────────────────────────

def test_int_width_comes_from_typedef_testimony_and_conflicts_leave_it_unknown():
    context = cpc.build_project_context({_p("a.h"): COMMON})
    assert context["target"]["widths"] == {"char": 8, "int": 16, "long": 32}
    conflicting = cpc.build_project_context({_p("a.h"): "typedef unsigned int U16;\ntypedef unsigned int UINT32;\n"})
    assert "int" not in conflicting["target"]["widths"]
    assert conflicting["target"]["conflicts"] == ["int"]
    # A name whose signedness contradicts the declaration testifies nothing.
    liar = cpc.build_project_context({_p("a.h"): "typedef signed int U16;\n"})
    assert liar["target"]["widths"] == {}


@pytest.mark.parametrize("text, value, kind, signed", [
    ("40000", 40000, "long", True),        # does not fit a 16-bit int → long
    ("40000U", 40000, "int", False),       # unsigned int holds it
    ("0xFFFF", 65535, "int", False),       # hex: int, then unsigned int
    ("32767", 32767, "int", True),
    ("5UL", 5, "long", False),
])
def test_integer_literal_types_follow_the_16_bit_candidate_lists(text, value, kind, signed):
    widths = {"char": 8, "short": 16, "int": 16, "long": 32}
    got, t = cpc.literal(text, widths)
    assert (got, t["kind"], t["signed"]) == (value, kind, signed)


def test_usual_arithmetic_conversions_on_a_16_bit_int_target():
    w = {"char": 8, "short": 16, "int": 16, "long": 32}
    u16, s16 = cpc.ctype("int", False, w), cpc.ctype("int", True, w)
    u8, s8, s32 = cpc.ctype("char", False, w), cpc.ctype("char", True, w), cpc.ctype("long", True, w)
    common = cpc.usual_conversion(u16, s16, w)
    assert (common["kind"], common["signed"]) == ("int", False)
    assert cpc.convert(-1, common) == 65535          # so (U16)1 < (S16)-1 is true on this target
    common = cpc.usual_conversion(u8, s8, w)
    assert (common["kind"], common["signed"]) == ("int", True)   # both promote to int
    common = cpc.usual_conversion(u16, s32, w)
    assert (common["kind"], common["signed"]) == ("long", True)  # long holds every unsigned int value


# ── macros and the preprocessor ─────────────────────────────────────────────────────────────────

def test_call_shaped_casts_and_nested_macros_evaluate_with_their_types():
    _ctx, scope = _scope('#include "common.h"\n'
                         "#define TIMEOUT ( ( U16 )( 5000U / u8g_T_MAIN ) )   // 5 s\n"
                         "#define WRAP ( ( U8 )( 300U ) )\n")
    assert scope["constants"]["TIMEOUT"]["value"] == 1000
    assert (scope["constants"]["TIMEOUT"]["type"]["kind"], scope["constants"]["TIMEOUT"]["type"]["signed"]) == ("int", False)
    assert scope["constants"]["WRAP"]["value"] == 44   # unsigned conversion wraps modulo 256


def test_include_guard_variant_with_error_arm_is_not_conditional():
    header = ("#ifdef LIB_H\n#error \"Re-include\"\n#else\n#define LIB_H\n"
              "#define LIB_MAX ( ( U8 )( 8U ) )\n#endif\n")
    _ctx, scope = _scope('#include "common.h"\n#include "lib.h"\n', {"lib.h": header})
    assert scope["constants"]["LIB_MAX"]["value"] == 8


def test_if_conditions_are_evaluated_against_the_macro_table():
    cfg = "#define MODE 1\n#if MODE == 1\n#define PICK 10\n#else\n#define PICK 20\n#endif\n"
    _ctx, scope = _scope('#include "cfg.h"\n', {"cfg.h": cfg})
    assert scope["constants"]["PICK"]["value"] == 10
    undecided = "#if SOMETHING(1)\n#define PICK 10\n#endif\n"
    _ctx, scope = _scope('#include "cfg.h"\n', {"cfg.h": undecided})
    assert "PICK" not in scope["constants"]
    assert scope["unresolved_constants"]["PICK"] == "macro_defined_conditionally"


def test_redefinition_with_another_value_is_not_one_constant():
    _ctx, scope = _scope("#define K 1\n#define K 2\n")
    assert "K" not in scope["constants"]          # constants resolve on lookup
    assert scope["unresolved_constants"]["K"] == "macro_value_varies_in_unit"


def test_float_constant_is_accepted_only_when_every_evaluation_format_agrees():
    _ctx, scope = _scope('#include "common.h"\n'
                         "#define LOW ( ( U16 )( 8.50F * ( F32 )100U ) )\n"
                         "#define HIGH ( ( U16 )( 4.74F * ( F32 )100U ) )\n")
    assert scope["constants"]["LOW"]["value"] == 850
    assert "HIGH" not in scope["constants"]
    # Single precision gives 473 (clang/msp430 agrees), wider evaluation 474: the source does not decide it.
    assert scope["unresolved_constants"]["HIGH"].startswith("float_precision_dependent:f64=473")


def test_anonymous_enum_typedef_gives_globals_their_enumerator_domain():
    text = ('#include "common.h"\ntypedef enum { ST_IDLE, ST_RUN = 5, ST_STOP } State;\n'
            "State g_state;\nvoid f(void) { if (g_state == ST_RUN) { } }\n")
    _ctx, scope = _scope(text)
    assert scope["constants"]["ST_STOP"]["value"] == 6
    report = build_mcdc_design(_unit(text, "f", scope))
    assert report["domains"]["g_state"]["values"] == [0, 5, 6]
    assert report["decisions"][0]["status"] == "designed"


def test_extern_const_takes_its_value_from_the_one_definition_in_the_project():
    header = "extern const U8 k_limit;\n"
    _ctx, scope = _scope('#include "common.h"\n#include "cfg.h"\n', {"cfg.h": header},
                         extra_units={"cfg.c": '#include "common.h"\nconst U8 k_limit = 7U;\n'})
    assert scope["constants"]["k_limit"]["value"] == 7
    assert scope["constants"]["k_limit"]["kind"] == "const_object_linked"
    assert "k_limit" not in scope["globals"]


def test_globals_in_inactive_arms_do_not_exist_and_volatile_is_flagged():
    text = ('#include "common.h"\n#define USE_B 0\n#if USE_B\nU8 g_b;\n#endif\n'
            "volatile U8 g_reg;\nU8 g_arr[4];\nU8 g_ok;\n")
    _ctx, scope = _scope(text)
    assert "g_b" not in scope["globals"] and "g_b" not in scope["unresolved_globals"]
    assert scope["globals"]["g_reg"]["volatile"] is True
    assert scope["unresolved_globals"]["g_arr"] == "global_not_scalar:array"
    assert scope["globals"]["g_ok"]["type"]["bits"] == 8


def test_write_closure_is_transitive_and_marks_unknown_callees():
    context = cpc.build_project_context({_p("a.c"): "int g;\nvoid leaf(void) { g = 1; }\nvoid mid(void) { leaf(); }\n"
                                                   "void ext(void) { lib_call(); }\n"})
    closure = cpc.function_write_closure(context)["functions"]
    assert closure["mid"]["writes"] == {"g"}
    assert closure["ext"]["unknown_callees"] == {"lib_call"}


# ── MC/DC engine with the scope ─────────────────────────────────────────────────────────────────

def test_unsigned_comparison_is_designed_with_16_bit_semantics_and_survives_revalidation():
    text = '#include "common.h"\nU16 g_u;\nvoid f(S16 s) { if (g_u < s) { } }\n'
    _ctx, scope = _scope(text)
    report = build_mcdc_design(_unit(text, "f", scope, ["s"]))
    decision = report["decisions"][0]
    assert decision["status"] == "designed"
    assert report["target"]["widths"]["int"] == 16
    # g_u = 1, s = -1: -1 converts to 65535, so the decision is TRUE (a 32-bit host would say false).
    probe = evaluate_decision("g_u < s", {"g_u": 1, "s": -1}, report["domains"], report["constants"],
                              report["target"]["widths"])
    assert probe["decision"] is True
    rows = [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]
    finalize_mcdc_design(report, rows)
    assert {p["retained_status"] for p in decision["pairs"]} == {"retained"}
    # The global is set by the design vector itself.
    assert all("g_u" in v for v in report["selected_inputs"])


def test_macro_constants_in_decisions_are_recorded_for_revalidation():
    text = ('#include "common.h"\n#define LIMIT ( ( U16 )( 5000U / u8g_T_MAIN ) )\n'
            "void f(U16 t) { if (t > LIMIT) { } }\n")
    _ctx, scope = _scope(text)
    report = build_mcdc_design(_unit(text, "f", scope, ["t"]))
    assert report["constants"]["LIMIT"]["value"] == 1000
    pair = report["decisions"][0]["pairs"][0]
    assert {pair["inputs_a"]["t"], pair["inputs_b"]["t"]} & {1000, 1001}


@pytest.mark.parametrize("body, reason", [
    ("g_x = 1U; if (g_x == 2U) { }", "input_modified_before_decision:g_x"),
    ("if (g_x == 2U) { g_x = 0U; }", "unique_cause_pairs_found"),               # the write follows the decision
    ("if (g_y == 1U) { g_x = 0U; } else if (g_x == 2U) { }", "unique_cause_pairs_found"),  # exclusive arm
    ("while (g_x != 3U) { g_x = 3U; }", "input_modified_before_decision:g_x"),  # next iteration
])
def test_writes_rebind_an_input_only_when_they_can_run_first(body, reason):
    text = f'#include "common.h"\nU8 g_x;\nU8 g_y;\nvoid f(void) {{ {body} }}\n'
    _ctx, scope = _scope(text)
    report = build_mcdc_design(_unit(text, "f", scope))
    target = next(d for d in report["decisions"] if "g_x" in d["expression"] and "g_y" not in d["expression"])
    assert target["reason"] == reason


@pytest.mark.parametrize("prefix, reason", [
    ("touch();", "global_modified_by_callee:touch:g_x"),
    ("lib_call();", "global_binding_unverified:unknown_callee:lib_call"),
    ("", "unique_cause_pairs_found"),
])
def test_callees_that_may_write_a_global_before_the_decision_unbind_it(prefix, reason):
    text = (f'#include "common.h"\nU8 g_x;\nvoid touch(void) {{ g_x = 1U; }}\n'
            f"void f(void) {{ {prefix} if (g_x == 2U) {{ }} touch(); }}\n")
    _ctx, scope = _scope(text)
    report = build_mcdc_design(_unit(text, "f", scope))
    assert report["decisions"][0]["reason"] == reason


def test_if_inside_a_body_is_resolved_and_its_condition_is_not_a_decision():
    text = ('#include "common.h"\n#define MODE 1\n'
            "void f(U8 a) {\n#if (MODE == 1) || (MODE == 2)\n if (a == 1U) { }\n#else\n if (a == 9U) { }\n#endif\n"
            "#if UNDECIDED(1)\n if (a == 5U) { }\n#endif\n}\n")
    _ctx, scope = _scope(text)
    report = build_mcdc_design(_unit(text, "f", scope, ["a"]))
    by_expr = {d["expression"]: d for d in report["decisions"]}
    assert set(by_expr) == {"a == 1U", "a == 5U"}          # no `(MODE == 1) || ...`, no inactive `a == 9U`
    assert by_expr["a == 1U"]["status"] == "designed"
    assert by_expr["a == 5U"]["reason"] == "conditional_compilation_unresolved"


def test_identical_coupled_conditions_are_proven_infeasible_not_searched_out():
    text = '#include "common.h"\nvoid f(U8 a, U8 b, U8 c) { if ((a == 1U && b == 1U) || (a == 1U && c == 1U)) { } }\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["a", "b", "c"]))["decisions"][0]
    assert decision["reason"] == "unique_cause_infeasible:coupled_condition"
    assert {c["condition_id"] for c in decision["infeasible_conditions"]} == {"C1", "C3"}
    assert {p["condition_id"] for p in decision["pairs"]} == {"C2", "C4"}


def test_a_decision_over_constants_only_is_a_constant_decision():
    text = '#include "common.h"\n#define A 3\nvoid f(void) { if (A <= 5) { } }\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope))["decisions"][0]
    assert decision["reason"] == "unique_cause_infeasible:constant_decision"
    assert decision["constant_value"] is True


def test_bitmask_terms_are_designed_and_undefined_behavior_inputs_are_skipped():
    text = ('#include "common.h"\nvoid f(U8 m, S16 s) { if ((m & 0x80U) == 0x80U) { } '
            "if (s + 1 > 100) { } if (s - 1 < -32767) { } }\n")
    _ctx, scope = _scope(text)
    decisions = build_mcdc_design(_unit(text, "f", scope, ["m", "s"]))["decisions"]
    assert [d["status"] for d in decisions] == ["designed", "designed", "designed"]
    # s = 32767 would overflow `s + 1`, s = -32768 would overflow `s - 1` (undefined): never a vector. The
    # sampler reaches -32768 *before* the true vector -32767, so the search must step over it, not give up.
    for decision, bad in ((decisions[1], 32767), (decisions[2], -32768)):
        for pair in decision["pairs"]:
            assert bad not in (pair["inputs_a"]["s"], pair["inputs_b"]["s"])
    assert -32767 in {decisions[2]["pairs"][0]["inputs_a"]["s"], decisions[2]["pairs"][0]["inputs_b"]["s"]}


def test_identifier_reasons_name_the_declaration_fact():
    text = ('#include "common.h"\n#define REG PORT.bit\nvoid f(void) { U8 t = 0U; '
            "if (t == 1U) { } if (REG == 1U) { } if (nowhere == 1U) { } }\n")
    _ctx, scope = _scope(text)
    reasons = [d["reason"] for d in build_mcdc_design(_unit(text, "f", scope))["decisions"]]
    assert reasons == ["local_variable_not_input:t", "macro_value_unresolved:REG:register_or_struct_field",
                       "identifier_undeclared:nowhere"]


def test_attach_unit_sources_shares_one_scope_per_file():
    from generators.suts import attach_unit_sources
    text = '#include "common.h"\nvoid f(void) { }\nvoid g(void) { }\n'
    context = cpc.build_project_context({_p("common.h"): COMMON, _p("unit.c"): text})
    units = [{"name": "f", "source_path": _p("unit.c")}, {"name": "g", "source_path": _p("unit.c")}]
    assert attach_unit_sources(units, {_p("unit.c"): text}, context) == 2
    assert units[0]["project_scope"] is units[1]["project_scope"]
    assert units[0]["project_scope"]["target"]["widths"]["int"] == 16


def test_suts_rows_never_carry_a_hidden_global_and_unread_inputs_do_not_block():
    """SUTS mode (no ``mcdc_free_globals``): the row renders the unit's input columns only (R80 review W5)."""
    text = ('#include "common.h"\nU8 g_x;\n'
            "void f(U8 a, U8 *p) { if (g_x == 1U) { } if (a == 2U) { } }\n")
    _ctx, scope = _scope(text)
    unit = {**_unit(text, "f", scope, ["a", "p"]), "mcdc_free_globals": False}
    by_expr = {d["expression"]: d for d in build_mcdc_design(unit)["decisions"]}
    # g_x is resolvable but not a unit input: a pair on it would set a value no row shows.
    assert by_expr["g_x == 1U"]["reason"] == "decision_variable_not_in_unit_inputs:g_x"
    # The pointer input is not read by `a == 2U`: no longer blocks it; the vector leaves it unset.
    assert by_expr["a == 2U"]["status"] == "designed"
    assert by_expr["a == 2U"]["inputs_not_designed"] == ["p"]
    assert all(set(p["inputs_a"]) == {"a"} for p in by_expr["a == 2U"]["pairs"])


def test_suts_mcdc_rows_leave_undesigned_inputs_blank_and_say_so():
    from generators.suts import generate_sequences
    text = '#include "common.h"\nvoid f(U8 a, U8 *p) { if (a == 2U) { } }\n'
    _ctx, scope = _scope(text)
    unit = {"name": "f", "input_vars": ["a", "p"], "output_vars": ["ret"], "param_types": {"a": "U8", "p": "U8 *"},
            "source_text": text, "source_path": _p("unit.c"), "source_text_complete": True, "project_scope": scope}
    rows = [s for s in generate_sequences(unit) if str(s.get("strategy", "")).startswith("MCDC_")]
    assert rows and all("p" not in r["inputs"] and "a" in r["inputs"] for r in rows)
    assert all("설계 밖 입력" in r["description"].split("\n")[0] and "p" in r["description"].split("\n")[0] for r in rows)
    assert {m["pair_id"] for r in rows for m in r["mcdc_design"]}  # both rows kept and revalidated


def test_project_context_reads_the_whole_tree_not_the_documentation_scope(tmp_path):
    """R81 real-run defect: component_map verify=X dropped Include_File_Management.h from the cache → 0 designed."""
    from report_gen.uds_generator import _build_project_context
    (tmp_path / "inc").mkdir()
    header = tmp_path / "inc" / "all.h"
    header.write_text(COMMON, encoding="utf-8")
    unit = tmp_path / "u.c"
    unit.write_text('#include "all.h"\nvoid f(void) { }\n', encoding="utf-8")
    cache = {str(unit): unit.read_text(encoding="utf-8")}      # the documentation scope skipped the header

    def walk(root):
        yield from root.rglob("*")
    context = _build_project_context(cache, [], [tmp_path], walk, lambda p: p.read_text(encoding="utf-8"))
    assert str(header) in context["files"]
    scope = cpc.build_scopes(context, [str(unit)])[str(unit)]
    assert scope["missing_includes"] == [] and scope["constants"]["u8g_T_MAIN"]["value"] == 5


# ── R81 review round 1 — every probe case is a regression test ────────────────────────────────────

def test_c1_unparenthesized_macro_body_is_not_one_value():
    text = ('#include "common.h"\n#define MASK 0x01U | 0x02U\n#define LIM 10U + 5U\n#define OK ( 10U + 5U )\n'
            "void f(U8 x) { if ((x & MASK) != 0U) { } if (x > LIM) { } if (x > OK) { } }\n")
    _ctx, scope = _scope(text)
    reasons = [d["reason"] for d in build_mcdc_design(_unit(text, "f", scope, ["x"]))["decisions"]]
    assert reasons[0] == "macro_value_unresolved:MASK:macro_body_not_parenthesized"
    assert reasons[1] == "macro_value_unresolved:LIM:macro_body_not_parenthesized"
    assert reasons[2] == "unique_cause_pairs_found"


def test_c1_unparenthesized_body_in_if_arithmetic_is_undecided():
    cfg = "#define VER 1 + 1\n#if VER * 2 == 4\n#define LIMIT 100\n#else\n#define LIMIT 200\n#endif\n"
    _ctx, scope = _scope('#include "cfg.h"\n', {"cfg.h": cfg})
    assert "LIMIT" not in scope["constants"]
    assert scope["unresolved_constants"]["LIMIT"] == "macro_defined_conditionally"


def test_c2_after_a_missing_include_even_a_tree_defined_name_is_undecided():
    text = '#include "cfg_missing.h"\n#ifdef USE_B\n#define LIMIT 10U\n#else\n#define LIMIT 20U\n#endif\n'
    _ctx, scope = _scope(text, extra_units={"other.c": "#define USE_B 1\n"})
    assert "LIMIT" not in scope["constants"]


@pytest.mark.parametrize("prefix", ["", '#include "cfg_missing.h"\n'])
def test_c2_names_the_tree_never_defines_or_that_a_missing_header_may_define_are_undecided(prefix):
    text = (prefix + "#ifdef VARIANT_B\n#define LIMIT 10U\n#else\n#define LIMIT 20U\n#endif\n"
            "#if FEATURE_X\n#define F 1\n#endif\n")
    _ctx, scope = _scope(text)
    assert "LIMIT" not in scope["constants"] and "F" not in scope["constants"]
    assert scope["unresolved_constants"]["LIMIT"] == "macro_defined_conditionally"


def test_c2_a_name_the_tree_defines_elsewhere_is_undefined_here():
    """Project-controlled names (defined by some header, not included here) keep the C rule: undefined = 0."""
    text = "#ifdef USE_B\n#define LIMIT 10U\n#else\n#define LIMIT 20U\n#endif\n"
    _ctx, scope = _scope(text, extra_units={"other.c": "#define USE_B 1\n"})
    assert scope["constants"]["LIMIT"]["value"] == 20


@pytest.mark.parametrize("macro, call", [
    ("#define CLR_BIT(A, B) ((A) &= (U8)~(1U << (B)))\n", "CLR_BIT(x, 0U);"),        # (a) parameter
    ("#define CLR(v) clr(&(v))\nvoid clr(U8 *p) { *p = 0U; }\n", "CLR(x);"),         # (b) address escapes
    ("#define SHL(v) ((v) <<= 1U)\n", "SHL(x);"),                                     # (e) <<=
])
def test_c3_macro_invocations_that_write_their_arguments_rebind_them(macro, call):
    text = f'#include "common.h"\n{macro}void f(U8 x, U8 y) {{ {call} if ((x == 1U) && (y == 1U)) {{ }} }}\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["x", "y"]))["decisions"][0]
    assert decision["reason"] == "input_modified_before_decision:x"


def test_c3_object_like_macro_statement_is_a_call_site():
    text = ('#include "common.h"\nU8 g_flag;\n#define CLEAR_FLAG (g_flag = 0U)\n'
            "void f(U8 x) { CLEAR_FLAG; if ((g_flag == 1U) && (x == 1U)) { } }\n")
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["x"]))["decisions"][0]
    # The expansion writes g_flag before the decision (recorded as a write since review round 2).
    assert decision["reason"] == "input_modified_before_decision:g_flag"


def test_c3_file_scope_address_and_block_extern_in_a_callee_count():
    text = ('#include "common.h"\nU8 g_cnt;\nU8 g_m;\nstatic U8 * const s_tbl[1] = { &g_cnt };\n'
            "void set(void) { extern U8 g_m; g_m = 1U; }\n"
            "void f(void) { set(); if (g_cnt == 1U) { } if (g_m == 1U) { } }\n")
    _ctx, scope = _scope(text)
    reasons = [d["reason"] for d in build_mcdc_design(_unit(text, "f", scope))["decisions"]]
    assert reasons == ["global_address_taken:g_cnt", "global_modified_by_callee:set:g_m"]


def test_c3_a_parameter_shadowed_by_a_block_local_is_not_designed():
    text = '#include "common.h"\nvoid f(U8 x, U8 y) { { U8 x = 5U; if ((x == 1U) && (y == 1U)) { } } }\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["x", "y"]))["decisions"][0]
    assert decision["reason"] == "identifier_shadowed_by_local:x"


def test_w1_body_if_on_a_macro_that_changes_value_is_undecided_not_dropped():
    text = ('#include "common.h"\n#define FEAT 1\n'
            "void f(U8 x) {\n#if FEAT == 1\n if (x == 1U) { }\n#endif\n}\n#undef FEAT\n#define FEAT 0\n")
    _ctx, scope = _scope(text)
    decisions = build_mcdc_design(_unit(text, "f", scope, ["x"]))["decisions"]
    assert [d["reason"] for d in decisions] == ["conditional_compilation_unresolved"]


def test_w2_if_arithmetic_with_unsigned_operands_and_negatives_is_undecided():
    cfg = "#if -1 > 0u\n#define PICK 1\n#else\n#define PICK 2\n#endif\n"
    _ctx, scope = _scope('#include "cfg.h"\n', {"cfg.h": cfg})
    assert "PICK" not in scope["constants"]


def test_w3_enum_object_against_a_possibly_negative_operand_is_refused():
    text = ('#include "common.h"\ntypedef enum { E0, E1 } E;\nE g_e;\n'
            "void f(S8 s) { if ((g_e > s) && (s < 0)) { } if (g_e == E1) { } }\n")
    _ctx, scope = _scope(text)
    reasons = [d["reason"] for d in build_mcdc_design(_unit(text, "f", scope, ["s"]))["decisions"]]
    assert reasons == ["enum_underlying_type_implementation_defined", "unique_cause_pairs_found"]


def test_w4_const_objects_and_enumerators_get_the_float_agreement_check_too():
    text = ('#include "common.h"\n#define KM ((U16)(0.29*100.0))\nstatic const U16 KC = (U16)(0.29*100.0);\n'
            "enum { KE = (int)(0.29*100.0) };\n")
    _ctx, scope = _scope(text)
    for name in ("KM", "KE"):
        assert name not in scope["constants"]
        assert scope["unresolved_constants"][name].startswith("float_precision_dependent")
    assert scope["unresolved_constants"]["KC"].startswith("const_initializer_unresolved:float_precision_dependent")


def test_w5_functions_after_a_vendor_syntax_error_are_compiled_and_scanned():
    # Same shape as HDPDM01 Monitor_ADC.c: the initializer after `__attribute__` becomes a top-level compound
    # statement that swallows the functions after it.
    text = ('#include "common.h"\nU8 g_a;\nstatic volatile U32 CSL[2] __attribute__ ((aligned (4))) = {   /* c */\n'
            "0x00D00000U,0x00D2A000U};\nstatic volatile U16 RVL[2] __attribute__ ((aligned (4)));\nstatic U8 s_x;\n"
            "void take(void) { U8 *p = &g_a; *p = 1U; }\nvoid f(U8 x) { if (x == 1U) { } }\n")
    root = cpc.shared_parser().parse(text.encode()).root_node
    swallow = [c for c in root.named_children if c.type == "compound_statement"]
    assert swallow and "function_definition" in [c.type for c in swallow[0].named_children]  # shape reproduced
    context, scope = _scope(text)
    closure = cpc.function_write_closure(context)
    assert "take" in closure["functions"] and "g_a" in closure["address_taken"]
    decision = build_mcdc_design(_unit(text, "f", scope, ["x"]))["decisions"][0]
    assert decision["reason"] == "unique_cause_pairs_found"


def test_i1_guarded_division_never_claims_a_complete_search_without_pairs():
    text = '#include "common.h"\nvoid f(U8 d, U8 n) { if ((d != 0U) && ((n / d) > 3U)) { } }\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["d", "n"]))["decisions"][0]
    assert decision["reason"] in {"unique_cause_pairs_found", "no_pair_undefined_behavior_candidates_skipped"}


def test_i2_int_min_remainder_minus_one_is_undefined():
    w = {"char": 8, "short": 16, "int": 16, "long": 32}
    s16 = cpc.ctype("int", True, w)
    with pytest.raises(cpc.Unresolved, match="signed_overflow"):
        cpc.arith("%", (-32768, s16), (-1, s16), w)


def test_i5_a_scope_for_another_text_of_the_file_is_not_used():
    text = '#include "common.h"\n#define K ((U8)(3U))\nvoid f(U8 x) { if (x == K) { } }\n'
    _ctx, scope = _scope(text)
    unit = {**_unit(text, "f", scope, ["x"]), "source_text": text + "/* edited */\n"}
    report = build_mcdc_design(unit)
    assert report["project_context_status"] == "source_text_mismatch"
    assert report["decisions"][0]["reason"] == "preprocessor_context_unresolved"


def test_a_context_of_another_schema_is_not_attached():
    """Cache payloads of an older context shape would give silently wrong verdicts: no scope, status recorded."""
    from generators.suts import attach_unit_sources
    text = '#include "common.h"\nvoid f(void) { }\n'
    context = cpc.build_project_context({_p("common.h"): COMMON, _p("unit.c"): text})
    old = {**context, "schema_version": cpc.SCHEMA_VERSION - 1}
    units = [{"name": "f", "source_path": _p("unit.c")}]
    attach_unit_sources(units, {_p("unit.c"): text}, old)
    assert "project_scope" not in units[0]
    assert units[0]["project_context_status"] == f"schema_mismatch:{cpc.SCHEMA_VERSION - 1}"


# ── R81 review round 2 — macro-mediated writes the first fix still missed ─────────────────────────

@pytest.mark.parametrize("macros, stmt, target", [
    # object-like macro under an undecided #if (body unknown to the engine)
    ("#if defined(CFG_A)\n#define CLEAR_FLAG (g_flag = 0U)\n#else\n#define CLEAR_FLAG (g_flag = 2U)\n#endif\n",
     "CLEAR_FLAG;", "g_flag"),
    # redefined later in the file (varied)
    ("#define CLEAR_FLAG (g_flag = 0U)\n", "CLEAR_FLAG;", "g_flag"),
    # function-like macro under an undecided #if writes a parameter
    ("#if defined(CFG_A)\n#define SETV(v) ((v) = 1U)\n#endif\n", "SETV(x);", "x"),
    # nested macro writes a parameter
    ("#define CLR_BIT(A, B) ((A) &= (U8)~(1U << (B)))\n#define CLR0(v) CLR_BIT(v, 0U)\n", "CLR0(x);", "x"),
    # object-like alias used as a write target
    ("#define G_ALIAS g_flag\n", "G_ALIAS = 0U;", "g_flag"),
    # object-like macro writing a parameter by name
    ("#define ZERO_X x = 0U\n", "ZERO_X;", "x"),
])
def test_round2_macro_mediated_writes_rebind_the_input(macros, stmt, target):
    tail = "#undef CLEAR_FLAG\n#define CLEAR_FLAG (g_flag = 3U)\n" if macros == "#define CLEAR_FLAG (g_flag = 0U)\n" else ""
    # The decision reads only the written name, so no other refusal can mask a missed write.
    text = (f'#include "common.h"\nU8 g_flag;\n{macros}'
            f"void f(U8 x, U8 y) {{ {stmt} if (({target} == 1U) && (y == 1U)) {{ }} }}\n{tail}")
    _ctx, scope = _scope(text)
    unit = {**_unit(text, "f", scope, ["x", "y"]), "input_vars": ["x", "y", "g_flag"]}
    decision = build_mcdc_design(unit)["decisions"][0]
    # A macro whose body this unit cannot pin down is named as the cause (review round 3 W1); a known body
    # writes the target itself.
    reason = decision["reason"]
    assert reason == f"input_modified_before_decision:{target}" or reason.startswith("input_binding_unverified:macro:")
    if "#if" in macros or "#undef" in tail:
        macro = stmt.split("(")[0].rstrip(";")
        assert reason in {f"input_binding_unverified:macro:{macro}", f"input_modified_before_decision:{target}"}


def test_round2_alias_write_in_a_callee_is_an_unknown_callee():
    text = ('#include "common.h"\nU8 g_cnt;\n#define G_ALIAS g_cnt\nvoid reset(void) { G_ALIAS = 0U; }\n'
            "void f(void) { reset(); if (g_cnt == 1U) { } }\n")
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope))["decisions"][0]
    assert decision["reason"] == "global_binding_unverified:unknown_callee:macro_write:G_ALIAS"


def test_round2_call_to_an_undeclared_name_after_a_missing_include_may_be_a_macro():
    text = '#include "common.h"\n#include "gone.h"\nvoid f(U8 x, U8 y) { RESET(x); if ((x == 1U) && (y == 1U)) { } }\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["x", "y"]))["decisions"][0]
    assert decision["reason"] == "input_binding_unverified:undeclared_after_missing_include:RESET"


def test_round2_enum_object_inside_arithmetic_is_refused():
    text = ('#include "common.h"\ntypedef enum { E0, E1 } E;\nE g_e;\n'
            "void f(U8 y) { if (((g_e - 1) < 0) && (y == 1U)) { } }\n")
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["y"]))["decisions"][0]
    assert decision["reason"] == "enum_underlying_type_implementation_defined"


def test_round2_a_missing_include_after_a_definition_leaves_it_unverified():
    header = "#define TIMEOUT ( 10U )\n"
    text = '#include "common.h"\n#include "a.h"\n#include "gone.h"\nU8 g_v;\n'
    _ctx, scope = _scope(text, {"a.h": header})
    assert "TIMEOUT" not in scope["constants"]
    assert scope["unresolved_constants"]["TIMEOUT"] == "macro_unverified_missing_include"
    assert scope["unresolved_globals"]["g_v"] == "global_unverified_missing_include"
    # A definition after the last unreadable include is still a constant.
    _ctx, scope = _scope('#include "gone.h"\n#define LATE ( 3U )\n')
    assert scope["constants"]["LATE"]["value"] == 3


# ── R81 review round 3 ────────────────────────────────────────────────────────────────────────────

def test_round3_two_level_alias_address_reaches_the_global():
    text = ('#include "common.h"\nU8 g_c;\n#define A2 g_c\n#define A1 A2\nvoid clr(U8 *p) { *p = 0U; }\n'
            "void touch(void) { clr(&A1); }\nvoid f(void) { if (g_c == 1U) { } }\n")
    context, scope = _scope(text)
    assert "g_c" in cpc.function_write_closure(context)["address_taken"]
    assert build_mcdc_design(_unit(text, "f", scope))["decisions"][0]["reason"] == "global_address_taken:g_c"


def test_round3_a_macro_named_like_a_function_is_what_runs():
    text = ('#include "common.h"\nU8 g_c;\nvoid do_clear(void) { g_c = 0U; }\nvoid reset(void) { }\n'
            "#define reset() do_clear()\nvoid f(void) { reset(); if (g_c == 1U) { } }\n")
    _ctx, scope = _scope(text)
    reason = build_mcdc_design(_unit(text, "f", scope))["decisions"][0]["reason"]
    assert reason == "global_modified_by_callee:do_clear:g_c"


@pytest.mark.parametrize("macros, stmt, read", [
    ("#define CLR(v) ((v) = 0U)\n#define SELF x\n", "CLR(SELF);", "x"),   # argument alias
    ("#define ZERO(n) n##_v = 0U\n", "ZERO(x);", "x_v"),                   # token pasting forms `x_v`
])
def test_round3_argument_aliases_and_token_pasting_count_as_writes(macros, stmt, read):
    # The decision reads only the name the expansion writes, so no other refusal can mask a miss.
    text = f'#include "common.h"\n{macros}void f(U8 x, U8 x_v, U8 y) {{ {stmt} if (({read} == 1U) && (y == 1U)) {{ }} }}\n'
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["x", "x_v", "y"]))["decisions"][0]
    assert decision["status"] == "unsupported"
    assert decision["reason"].split(":")[0] in {"input_modified_before_decision", "input_binding_unverified"}


def test_round3_an_undecided_constant_macro_does_not_refuse_unrelated_decisions():
    text = ('#include "common.h"\nU8 g_out;\n#ifdef VARIANT_B\n#define GAIN 2U\n#else\n#define GAIN 3U\n#endif\n'
            "void f(U8 x, U8 y) { g_out = GAIN; if ((x == 1U) && (y == 1U)) { } }\n")
    _ctx, scope = _scope(text)
    assert scope["macro_status"]["GAIN"] == "unknown"
    decision = build_mcdc_design(_unit(text, "f", scope, ["x", "y"]))["decisions"][0]
    assert decision["reason"] == "unique_cause_pairs_found"


def test_round3_a_declared_library_call_after_a_missing_include_is_not_a_macro():
    text = ('#include "common.h"\n#include "gone.h"\nvoid lib_copy(U8 *d, U8 s);\n'
            "void f(U8 x, U8 y) { U8 t; lib_copy(&t, 1U); if ((x == 1U) && (y == 1U)) { } }\n")
    _ctx, scope = _scope(text)
    decision = build_mcdc_design(_unit(text, "f", scope, ["x", "y"]))["decisions"][0]
    assert decision["reason"] == "unique_cause_pairs_found"
