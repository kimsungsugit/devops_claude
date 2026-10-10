"""R31 — robustness rows outside the design range (extended SUTS only).

Where the design documents give an input a range (SwUDS/HSIS) and the function body compares that input directly with a
constant outside the range but inside the declared type (``g_w < 0xFFFFU`` for a timer designed 0..60), the extended
profile adds FI rows at the constant's −1/0/+1 that lie outside the design range and inside the type — boundary value
analysis on the code's own constants (R26 measurement: most mutants only the reference killed on KJPDS02_PV needed an
input outside the range the generated suite used). The expected values come from the same source oracle as every row.
"""
from __future__ import annotations

import os

import pytest

from generators import boundary_rows as br
from generators import c_project_context as cpc
from generators.suts import (
    MAX_ROBUST_ROWS,
    ROBUST_PREFIX,
    ROBUSTNESS_REPORT_KEYS,
    _append_robustness_rows,
    generate_sequences,
    is_extended_strategy,
    resolve_seq_gen_method,
    resolve_seq_test_method,
    summarize_robustness_rows,
)
from report_gen.generation_disclosures import build_disclosures

ROOT = os.path.join(os.sep, "proj31")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed short S16;
typedef signed char S8;
typedef float F32;
#define u16g_MAX 0xFFFFU
#define K_TEN 10U
#define K_S 10
#define DBG_CHECK(c)
#define SEL(c, a, b) ((c) ? (a) : (b))
#define CHECK DBG_CHECK
#define PICK SEL
#define LIM(c) ((c) ? K_TEN : 0U)
#define ON 1U
#define DBGY(c) ((void)ON)
#define STR(c) #c
#define VA(...) (__VA_ARGS__)
#define LOGS(c) log_fn("a//b", (c))
#define QT(c) log_fn("c")
#if 1
#define DBG4(c) ((c) ? 1U : 2U)
#endif
#ifdef NOWHERE_FLAG
#define DBG3(c) (c)
#else
#define DBG3(c) ((c) ? 1U : 2U)
#endif
#endif
"""
UNIT = """#include "common.h"
U8 g_a;
U8 g_b;
U8 g_f;
U8 g_o;
U8 g_z;
U16 g_w;
S16 g_s;
void gt(void) { if (g_a > K_TEN) { g_o = 1U; } else { g_o = 2U; } }
void rev(void) { if (10U < (U16)(g_a)) { g_o = 1U; } else { g_o = 2U; } }
void sat(void) { if (g_w < u16g_MAX) { g_w++; } }
void satf(void) { if (g_f == 1U) { if (g_w < u16g_MAX) { g_w++; } } }
void dead(void) { if (g_b == 7U) { if (g_w < u16g_MAX) { g_w++; } } }
void over(void) { if (g_a > 300U) { g_o = 1U; } else { g_o = 2U; } }
void derived(void) { if ((U16)g_a + 1U > 10U) { g_o = 1U; } else { g_o = 2U; } }
void many(void) { g_o = 0U; if (g_a == 20U) { g_o = 1U; } if (g_a == 40U) { g_o = 2U; } if (g_a == 60U) { g_o = 3U; }
                  if (g_a == 80U) { g_o = 4U; } if (g_a == 100U) { g_o = 5U; } }
void neg(void) { if (g_s < -300) { g_o = 1U; } if ((-200) == g_s) { g_o = 2U; } if (g_s != -K_S) { g_o = 3U; }
                 if (g_s == -K_TEN) { g_o = 7U; } if (g_s == -1U) { g_o = 8U; } if (g_s == -(U16)20) { g_o = 9U; }
                 if (g_s == -(F32)5) { g_o = 10U; }
                 if (g_s == ~5) { g_o = 4U; } if (-400 >= g_s) { g_o = 5U; } if (g_s <= -500) { g_o = 6U; } }
void narrow(void) { if (g_s == (S8)200) { g_o = 1U; } if (g_s == (S8)(250)) { g_o = 2U; } if (g_s == (S8)100) { g_o = 3U; }
                    if (g_s == (S16)(-120)) { g_o = 4U; } }
void shadow(void) { U8 g_a = 3U; if (g_a > 50U) { g_o = 1U; } }
void mneg(void) { if (g_a == -1) { g_o = 1U; } else { g_o = 2U; } }
void adj(void) { g_o = 0U; if (g_a == 20U) { g_o = 1U; } if (g_a == 21U) { g_o = 2U; } }
void ptr(U8 *p) { g_o = 0U; if (p == 9U) { g_o = 1U; } }
void dbg(void) { g_o = 0U; DBG_CHECK(g_a < 200U); if (g_a > 100U) { g_o = 1U; } }
void divd(void) { DBG_CHECK(g_a < 200U); g_o = (U8)(g_a / 10U); }
void sel(void) { g_o = SEL(g_a > 150U, 1U, 2U); }
void cnd(void) { g_o = DBG3(g_a > 150U); }
void cnd4(void) { g_o = DBG4(g_a > 160U); }
void pick(void) { g_o = PICK(g_a > 170U, 1U, 2U); }
void lim(void) { g_o = LIM(g_a > 170U); }
void lim0(void) { g_o = LIM(g_a == 0U); }
void dbgy(void) { DBGY(g_a < 200U); g_o = (U8)(g_a / 10U); }
void strf(void) { g_o = 0U; (void)STR(g_a < 180U); }
void vaf(void) { g_o = VA(g_a > 190U); }
void argc(void) { g_o = SEL(g_a > 195U, 1U); }
void logs(void) { g_o = 0U; LOGS(g_a > 185U); }
void qt(void) { g_o = 0U; QT(g_a > 175U); }
void both(void) { g_o = 0U; (void)DBG3(g_a < 120U); if (g_a < 120U) { g_o = 1U; } }
void alias(void) { g_o = 0U; CHECK(g_a < 210U); }
void many2(void) { g_o = 0U; if (g_a == 10U) { g_o = 1U; } if (g_a == 20U) { g_o = 2U; } if (g_a == 30U) { g_o = 3U; }
                   if (g_a == 40U) { g_o = 4U; } if (g_a == 41U) { g_o = 5U; } if (g_a == 50U) { g_o = 6U; } }
void shadow2(void) { if (g_o == 1U) { U8 g_a = 3U; if (g_a > 50U) { g_o = 2U; } } }
void shadow3(void) { for (U8 g_a = 0U; g_a < 70U; g_a++) { g_o = g_a; } }
void shadow4(void) { void (*g_a)(void) = 0; if (g_a == 0) { g_o = 1U; } }
void ext(void) { extern U8 g_a; if (g_a > 50U) { g_o = 1U; } }
void pp2(void) {
  g_o = 0U;
#if 0
  if (g_a > 50U) { g_o = 1U; }
#else
  if (g_a > 60U) { g_o = 2U; }
#endif
#if 1
  if (g_a > 90U) { g_o = 3U; }
#else
  if (g_a > 95U) { g_o = 4U; }
#endif
}
void zero(void) { if (g_a == 0U) { g_o = 1U; } else { g_o = 2U; } }
void mix(void) { g_o = 0U; if (g_b == 20U) { g_z = 1U; } if (g_b == 40U) { g_z = 2U; } if (g_b == 60U) { g_z = 3U; }
                 if (g_b == 80U) { g_z = 4U; } if (g_b == 100U) { g_z = 5U; } if (g_a > K_TEN) { g_o = 1U; } }
"""
# a unit with a missing include: an ``#ifdef`` of a name another header defines cannot be decided for this build
PP_UNIT = """#include "common.h"
#include "missing.h"
U8 g_a;
U8 g_o;
void ppz(void) {
  g_o = 0U;
  if (g_a == 0U) { g_o = 1U; }
#ifdef ELSEWHERE
  g_o = 5U;
#endif
}
void pp(void) {
  g_o = 0U;
#if 0
  if (g_a > 50U) { g_o = 1U; }
#else
  if (g_a > 60U) { g_o = 2U; }
#endif
#ifdef ELSEWHERE
  if (g_a > 70U) { g_o = 3U; }
#endif
}
"""


def _unit(name, source=UNIT, **kw):
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "other.h"): "#define ELSEWHERE 1\n",
             os.path.join(ROOT, "unit.c"): source}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    unit = {"name": name, "source_text": source, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "fid": "F1"}
    unit.update(kw)
    return unit


def _a(name="gt", rng=(0, 5), **kw):
    return _unit(name, input_vars=["g_a"], output_vars=["g_o"], param_types={"g_a": "U8", "g_o": "U8"},
                 uds_param_info={"g_a": {"range": list(rng)}} if rng else {}, **kw)


def _robust(seqs):
    return [s for s in seqs if str(s.get("strategy") or "").startswith(ROBUST_PREFIX)]


def test_compared_constants_are_the_ones_the_input_meets_directly():
    assert br.compared_constants(_unit("gt"), ["g_a"]) == {"g_a": {10}}          # a macro the scope resolves
    assert br.compared_constants(_unit("rev"), ["g_a"]) == {"g_a": {10}}         # reversed, cast and parenthesised
    assert br.compared_constants(_unit("sat"), ["g_w"]) == {"g_w": {0xFFFF}}
    assert br.compared_constants(_unit("derived"), ["g_a"]) == {}                # ``g_a + 1 > 10`` is not ``g_a`` itself
    assert br.compared_constants(_unit("gt"), ["g_o"]) == {}


def test_a_signed_constant_keeps_its_sign():
    # (review W1) ``-300`` is one signed literal to tree-sitter-c — an unsigned-only pattern dropped it silently;
    #   ``~5`` is no negative number (round 2 G), and ``<=``/``>=`` compare as well (round 2 Q)
    #   A constant is valued as C values it (the oracle's typed literal/arith, review round 3 I-4): ``-K_TEN`` with
    #   ``K_TEN`` = ``10U`` and ``-1U`` are unsigned int (16 bits here) — 65526 and 65535, outside S16, not -10 and -1
    #   ``-(U16)20`` keeps the cast's type (65516), ``-(F32)5`` is a float comparison — not read
    assert br.compared_constants(_unit("neg"), ["g_s"]) == {"g_s": {-300, -200, -10, -400, -500, 65526, 65535, 65516}}


def test_a_constant_the_cast_converts_is_not_read_as_the_literal():
    # (review round 2 W3) ``(S8)200`` is -56 in C — rows at 199..201 would say "the source compares with 200"
    assert br.compared_constants(_unit("narrow"), ["g_s"]) == {"g_s": {100, -120}}


@pytest.mark.parametrize("name", ["shadow", "shadow2", "shadow3", "shadow4"])
def test_a_local_that_shadows_the_input_is_not_the_input(name):
    # top level, an inner block, a ``for`` initialiser, a function-pointer declarator (round 3 M3 / I-5)
    stats = {}
    assert br.compared_constants(_unit(name), ["g_a"], stats) == {} and stats == {"inputs_shadowed": 1}


def test_a_block_scope_extern_is_the_global_itself():
    stats = {}
    assert br.compared_constants(_unit("ext"), ["g_a"], stats) == {"g_a": {50}} and stats == {}


@pytest.mark.parametrize("name, direct, macro_only", [
    ("dbg", {100}, None),       # ``DBG_CHECK`` has one known, empty body: no comparison with 200 in this build
    ("divd", None, None),       # (round 4 W-1(b)) ``g_a / 10`` steps at 200 — the known body settles it, not a probe
    ("sel", {150}, None),       # ``SEL`` uses ``c`` as an expression: read as written
    ("cnd", None, {150}),       # ``DBG3`` is defined under an undecided ``#ifdef``: unknown — used only on a live base
    ("cnd4", {160}, None),      # a definition under a decided ``#if 1`` is the active body
    ("pick", None, {170}),      # an object-like alias: unknown (the oracle does not model it either)
    ("lim", None, {170}),       # a body that uses another macro: unknown here — the oracle expands it
    ("dbgy", None, None),       # (round 5 W-2) a body without the parameter drops it whatever macros it uses
    ("strf", None, {180}),      # ``#c`` stringises — unknown
    ("vaf", None, {190}),       # variadic — unknown
    ("argc", None, {195}),      # argument count differs from the parameters — unknown
    ("logs", {185}, None),      # (round 5 I-1) ``//`` inside a string literal of the body is no comment
    ("qt", None, None),         # the parameter's name inside a string literal is no use of it — dropped
    ("both", {120}, None),      # the same constant outside the macro as well: direct
    ("alias", None, {210}),     # (round 4 W-1(a)) ``CHECK`` is an object-like alias of a macro — the oracle's macro view
])
def test_a_comparison_inside_a_macro_argument_is_read_by_the_macro_body(name, direct, macro_only):
    stats = {}
    assert br.compared_constants(_unit(name), ["g_a"], stats) == ({"g_a": direct} if direct else {})
    assert stats == ({"macro_argument_constants": {"g_a": macro_only}} if macro_only else {})


def test_a_macro_argument_constant_is_used_only_on_a_live_base():
    unit = _a("dbg")
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows) == [99, 100, 101]
    assert unit["robustness_rows"]["macro_argument_unconfirmed"] == 0 and unit["robustness_rows"]["not_live"] == 0
    # the oracle cannot run an undecided macro either — nothing is live, nothing is used
    unit = _a("cnd")
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    assert unit["robustness_rows"]["macro_argument_unconfirmed"] == 1 and unit["robustness_rows"]["not_live"] == 0
    # the oracle expands ``LIM``: the output turns at 170 on a base — used, and the row says what was seen
    unit = _a("lim")
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows) == [169, 170, 171]
    assert all(s["robustness"]["in_macro_argument"] and "매크로의 인자 안 비교" in s["description"] for s in rows)
    assert unit["robustness_rows"]["macro_argument_live"] == 1 and unit["robustness_rows"]["live"] == 1
    # (round 4 I-1) at the type edge nothing is probed — an unknown macro's comparison stays unconfirmed, no row
    unit = _a("lim0", rng=(5, 10))
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    assert unit["robustness_rows"]["macro_argument_unconfirmed"] == 1 and unit["robustness_rows"]["unprobed"] == 0


def test_an_unreadable_body_is_counted_not_reported_as_no_comparison():
    stats = {}
    assert br.compared_constants(_unit("no_such_function"), ["g_a"], stats) == {} and stats == {"body_unread": 1}


def test_only_the_preprocessor_arms_this_build_compiles_are_read():
    # (review W2) a comparison in a dead ``#if 0`` arm was written into the document as "the source compares"; a true
    #   ``#if 1`` does not read its ``#else`` (round 2 A)
    stats = {}
    assert br.compared_constants(_unit("pp", source=PP_UNIT), ["g_a"], stats) == {"g_a": {60}}
    assert stats == {"undecided_preprocessor_blocks": 1}          # ``#ifdef ELSEWHERE`` — missing.h may define it
    assert br.compared_constants(_unit("pp2"), ["g_a"]) == {"g_a": {60, 90}}
    unit = _unit("pp2", input_vars=["g_a"], output_vars=["g_o"],
                 param_types={"g_a": "U8", "g_o": "U8"}, uds_param_info={"g_a": {"range": [0, 5]}})
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows) == [59, 60, 61, 89, 90, 91]
    assert all(s["expected_evidence"]["g_o"]["status"] == "derived" for s in rows)


def test_a_point_the_oracle_derives_nothing_at_is_no_row():
    # (review round 2 W1) every path of ``pp`` meets the undecided ``#ifdef``: nothing is derived, so an FI row there
    #   would carry "[검증 필요]" in every expected cell under a description saying the oracle derived it
    unit = _unit("pp", source=PP_UNIT, input_vars=["g_a"], output_vars=["g_o"],
                 param_types={"g_a": "U8", "g_o": "U8"}, uds_param_info={"g_a": {"range": [0, 5]}})
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    report = unit["robustness_rows"]
    assert report["underived"] == 3 and report["not_live"] == 1 and report["undecided_preprocessor_blocks"] == 1


def test_an_unprobed_point_the_oracle_derives_nothing_at_is_no_row():
    # (review round 3 M9) the type-edge path (live unknown) takes the derivation check too
    unit = _unit("ppz", source=PP_UNIT, input_vars=["g_a"], output_vars=["g_o"],
                 param_types={"g_a": "U8", "g_o": "U8"}, uds_param_info={"g_a": {"range": [5, 10]}})
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    assert unit["robustness_rows"]["unprobed"] == 1 and unit["robustness_rows"]["underived"] == 2


def test_a_unit_without_outputs_gets_no_row():
    unit, ins, _outs, types, bounds = _satf_ctx()
    seqs = [{"strategy": "BV_MID", "inputs": {"g_f": 1, "g_w": 30}, "expected": {}}]
    _append_robustness_rows(unit, seqs, ins, [], types, bounds, set(), {"g_f", "g_w"})
    assert _robust(seqs) == [] and unit["robustness_rows"]["underived"] == 2


def test_a_compared_constant_outside_the_design_range_gets_fi_rows_with_oracle_expectations():
    unit = _a()
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows) == [9, 10, 11]
    for s in rows:
        assert s["expected_evidence"]["g_o"]["status"] == "derived"
        assert s["expected"]["g_o"] == (1 if s["inputs"]["g_a"] > 10 else 2)
        assert s["tc_profile"] == "extended" and is_extended_strategy(s["strategy"])
        assert resolve_seq_test_method(s["strategy"]) == "FI" and resolve_seq_gen_method(s["strategy"]) == "AOR/ABV"
        assert "설계 범위 밖 강건성" in s["description"] and "0~5" in s["description"]
    assert unit["robustness_rows"] == {**dict.fromkeys(ROBUSTNESS_REPORT_KEYS, 0), "inputs_with_design_range": 1,
                                       "compared_constants_outside_design": 1, "live": 1, "rows": 3}
    assert all(s["robustness"]["live"] is True and "확인하지 못했다" not in s["description"] for s in rows)


def test_points_inside_the_design_range_or_already_present_add_no_row():
    # design 0..9, constant 10: 9 is a designed value (no robustness row) and 10 is already the BV_MAX_INV row
    unit = _a(rng=(0, 9))
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert [s["inputs"]["g_a"] for s in _robust(seqs)] == [11]
    assert [s["inputs"]["g_a"] for s in seqs].count(10) == 1 and unit["robustness_rows"]["duplicates"] == 1


def test_overlapping_points_of_adjacent_constants_make_one_row_each():
    # constants 20 and 21: 20 and 21 are points of both — one row each (round 2 C)
    unit = _a("adj")
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows) == [19, 20, 21, 22] and unit["robustness_rows"]["duplicates"] == 2


def test_a_constant_below_an_unsigned_type_is_counted_not_used():
    # ``g_a == -1`` for a U8: the promoted value is never -1 — no row "compares with -1" at g_a = 0 (round 2 B)
    unit = _a("mneg", rng=(1, 5))
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    assert unit["robustness_rows"]["constants_outside_type"] == 1


def test_a_guessed_type_is_not_widened():
    # (review W5) without a declaration the type is a name-pattern/default guess — its width would be an invented domain
    unit = _unit("gt", input_vars=["g_a"], output_vars=["g_o"], param_types={"g_o": "U8"},
                 uds_param_info={"g_a": {"range": [0, 5]}})
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    report = unit["robustness_rows"]
    assert report["inputs_type_unconfirmed"] == 1 and report["inputs_with_design_range"] == 0


def test_a_pointer_input_is_not_widened():
    # (review round 2 I8) ``p == 9`` compares an address; the column holds the pointed-to value (R71)
    unit = _unit("ptr", input_vars=["p"], output_vars=["g_o"], param_types={"p": "U8 *", "g_o": "U8"},
                 uds_param_info={"p": {"range": [0, 5]}})
    generate_sequences(unit, None, type_cache={}, extended=True)
    report = unit["robustness_rows"]
    assert report["inputs_with_design_range"] == 0 and report["inputs_type_unconfirmed"] == 1


def test_a_constant_at_the_type_edge_is_placed_unprobed():
    # constant 0 of a U8: only 0 and 1 of K-2..K+1 are values of the type — too few to see whether a base reaches it
    unit = _a("zero", rng=(5, 10))
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows) == [0, 1] and unit["robustness_rows"]["unprobed"] == 1
    assert all(s["robustness"]["live"] is None and "점이 셋 미만" in s["description"] for s in rows)


def test_a_saturation_guard_is_tested_at_the_guard_inside_the_type():
    # KJPDS02_PV s_LinFailCheckTimer: a timer designed 0..60 saturates at 0xFFFF — 0x10000 is no U16 value
    unit = _unit("sat", input_vars=["g_w"], output_vars=["g_w"], param_types={"g_w": "U16"},
                 uds_param_info={"g_w": {"range": [0, 60]}})
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_w"] for s in rows) == [0xFFFE, 0xFFFF]
    assert {s["inputs"]["g_w"]: s["expected"]["g_w"] for s in rows} == {0xFFFE: 0xFFFF, 0xFFFF: 0xFFFF}


def test_the_rows_use_a_base_where_the_guarded_comparison_is_reached():
    # KJPDS02_PV s_LinFailCheckTimer: the mid row had the LIN-fail flag at 0 — the increment and its saturation guard are
    #   never reached there, so rows on it separate nothing. The base must be one where the comparison is live.
    unit = _unit("satf", input_vars=["g_f", "g_w"], output_vars=["g_w"], param_types={"g_f": "U8", "g_w": "U16"},
                 uds_param_info={"g_f": {"range": [0, 1]}, "g_w": {"range": [0, 60]}})
    rows = [s for s in _robust(generate_sequences(unit, None, type_cache={}, extended=True))
            if s["robustness"]["variable"] == "g_w"]
    assert sorted(s["inputs"]["g_w"] for s in rows) == [0xFFFE, 0xFFFF] and all(s["inputs"]["g_f"] == 1 for s in rows)
    assert {s["inputs"]["g_w"]: s["expected"]["g_w"] for s in rows} == {0xFFFE: 0xFFFF, 0xFFFF: 0xFFFF}


def test_a_comparison_no_base_reaches_is_counted_and_placed_on_the_first_base():
    # ``g_b == 7`` guards the saturation and no base row has g_b = 7 (design 0..5): no live base for g_w's guard — the
    #   rows still go on the first base (liveness chooses the base, it does not drop rows) and the fact is counted
    unit = _unit("dead", input_vars=["g_b", "g_w"], output_vars=["g_w"], param_types={"g_b": "U8", "g_w": "U16"},
                 uds_param_info={"g_b": {"range": [0, 5]}, "g_w": {"range": [0, 60]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rows = _robust(seqs)
    first = next(s for s in seqs if s.get("strategy") == "BV_MID")
    on_w = [s for s in rows if s["robustness"]["variable"] == "g_w"]
    assert sorted(s["inputs"]["g_w"] for s in on_w) == [0xFFFE, 0xFFFF]
    assert all(s["inputs"]["g_b"] == first["inputs"]["g_b"] for s in on_w) and "기준 행 BV_MID" in on_w[0]["description"]
    assert unit["robustness_rows"]["not_live"] == 1
    assert all(s["robustness"]["live"] is False and "확인하지 못했다" in s["description"] for s in on_w)
    assert sorted(s["inputs"]["g_b"] for s in rows if s["robustness"]["variable"] == "g_b") == [6, 7, 8]


def _satf_ctx():
    unit = _unit("satf", input_vars=["g_f", "g_w"], output_vars=["g_w"], param_types={"g_f": "U8", "g_w": "U16"},
                 bounds_source={"g_w": "uds_range"})
    return unit, ["g_f", "g_w"], ["g_w"], {"g_f": "uint8", "g_w": "uint16"}, {"g_w": {"min": 0, "max": 60}}


def test_a_fault_injection_row_is_never_a_base():
    # the only row reaching the guard (g_f = 1) is an FI row: a base holds valid values only — the rows go on the
    #   valid row and the comparison is reported as not reached
    unit, ins, outs, types, bounds = _satf_ctx()
    seqs = [{"strategy": "BV_MID", "inputs": {"g_f": 0, "g_w": 30}, "expected": {"g_w": 30}},
            {"strategy": "ERROR_PATH", "inputs": {"g_f": 1, "g_w": 30}, "expected": {"g_w": 31}}]
    _append_robustness_rows(unit, seqs, ins, outs, types, bounds, set(), {"g_f", "g_w"})
    rows = _robust(seqs)
    assert rows and all(s["inputs"]["g_f"] == 0 for s in rows) and unit["robustness_rows"]["not_live"] == 1


def test_no_valid_base_adds_no_row():
    unit, ins, outs, types, bounds = _satf_ctx()
    seqs = [{"strategy": "BV_MAX_INV", "inputs": {"g_f": 1, "g_w": 61}, "expected": {"g_w": 62}},
            {"strategy": "BV_MID", "inputs": {"g_f": 1, "g_w": 70}, "expected": {"g_w": 71}}]   # a case value off design
    _append_robustness_rows(unit, seqs, ins, outs, types, bounds, set(), {"g_f", "g_w"})
    assert _robust(seqs) == [] and unit["robustness_rows"]["no_base"] == 1


@pytest.mark.parametrize("unit_kw", [
    {"rng": None},            # no design range: the type is the domain — the boundary rows already cover it
    {"rng": (0, 20)},         # the constant is inside the design range
])
def test_no_design_range_or_a_constant_inside_it_adds_no_row(unit_kw):
    unit = _a(**unit_kw)
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []


def test_a_constant_outside_the_type_is_counted_not_used():
    unit = _a("over")
    assert _robust(generate_sequences(unit, None, type_cache={}, extended=True)) == []
    assert unit["robustness_rows"]["constants_outside_type"] == 1


def test_rows_beyond_the_cap_are_counted(monkeypatch):
    probed = []
    real = br.comparison_is_live

    def counting(unit, base, var, points, outputs):
        probed.append(points[1] + 1)
        return real(unit, base, var, points, outputs)
    monkeypatch.setattr(br, "comparison_is_live", counting)
    unit = _a("many")
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert len(rows) == MAX_ROBUST_ROWS and unit["robustness_rows"]["cut"] == 5 * 3 - MAX_ROBUST_ROWS
    # (review round 2 I4) four live constants fill the cap — the fifth is not probed
    assert probed == [20, 40, 60, 80]


def test_the_cap_cuts_points_of_unreached_comparisons_first():
    # g_b's five comparisons only change g_z, which no row observes — they are never live; g_a's is. 18 points for 12
    #   places: the live ones keep theirs even though g_b comes first in the input order
    unit = _unit("mix", input_vars=["g_b", "g_a"], output_vars=["g_o"],
                 param_types={"g_a": "U8", "g_b": "U8", "g_o": "U8"},
                 uds_param_info={"g_a": {"range": [0, 5]}, "g_b": {"range": [0, 5]}})
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert sorted(s["inputs"]["g_a"] for s in rows if s["robustness"]["variable"] == "g_a") == [9, 10, 11]
    assert len(rows) == MAX_ROBUST_ROWS and unit["robustness_rows"]["cut"] == 18 - MAX_ROBUST_ROWS
    assert unit["robustness_rows"]["not_live"] == 5


def test_live_points_already_present_do_not_fill_the_cap_early():
    # (review round 3 M7) design 0..9: constant 10's point 10 is the BV_MAX_INV row. Counting it towards the cap would
    #   stop the probing one constant early and leave the unit under the cap with points cut
    unit = _a("many2", rng=(0, 9))
    rows = _robust(generate_sequences(unit, None, type_cache={}, extended=True))
    assert len(rows) == MAX_ROBUST_ROWS and 51 not in {s["inputs"]["g_a"] for s in rows}


def test_the_reference_profile_has_no_robustness_rows():
    assert _robust(generate_sequences(_a(), 24, type_cache={})) == []


def test_a_failure_costs_only_that_units_rows(monkeypatch):
    def boom(*a, **k):
        raise ValueError("x")
    monkeypatch.setattr(br, "compared_constants", boom)
    unit = _a()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert seqs and _robust(seqs) == [] and unit["robustness_rows"] == {"error": "ValueError", "rows": 0}


def test_a_failure_after_some_rows_rolls_all_of_them_back(monkeypatch):
    real, calls = br.derives_any, []

    def fails_second(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("x")
        return real(*a, **k)
    monkeypatch.setattr(br, "derives_any", fails_second)
    # ``dead``: g_b's rows (live) and the first g_w row (not live, derivation checked) are appended before the second
    #   g_w derivation check fails
    unit = _unit("dead", input_vars=["g_b", "g_w"], output_vars=["g_w"], param_types={"g_b": "U8", "g_w": "U16"},
                 uds_param_info={"g_b": {"range": [0, 5]}, "g_w": {"range": [0, 60]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert len(calls) == 2 and seqs and _robust(seqs) == [] and unit["robustness_rows"] == {"error": "ValueError",
                                                                                              "rows": 0}


def test_the_quality_report_sums_every_unit_key():
    # (review round 2 D) the aggregate is what the disclosure reads — a key missing there vanishes from the document
    full = {k: 1 for k in ROBUSTNESS_REPORT_KEYS}
    units = [{"robustness_rows": full}, {"robustness_rows": {"error": "ValueError", "rows": 0}}, {}]
    assert summarize_robustness_rows(units) == {**full, "cap_per_unit": MAX_ROBUST_ROWS, "units_with_rows": 1,
                                                "errors": 1}


def test_every_counter_reaches_the_disclosure():
    base = {**dict.fromkeys(ROBUSTNESS_REPORT_KEYS, 0), "rows": 3, "compared_constants_outside_design": 5,
            "inputs_with_design_range": 8, "live": 2, "cap_per_unit": 12, "units_with_rows": 1, "errors": 0}

    def note(**kw):
        return {i["key"]: i for i in build_disclosures("suts", {"robustness_rows": {**base, **kw}})}[
            "suts_robustness_rows"]["note"]
    shown_in_value = {"rows", "compared_constants_outside_design", "inputs_with_design_range", "live"}
    value = {i["key"]: i for i in build_disclosures("suts", {"robustness_rows": base})}["suts_robustness_rows"]["value"]
    assert value == "3행 (unit 1 · 설계 범위·선언 타입이 있는 입력 8 · 설계 범위 밖 직접 비교 상수 5, 살아 있는 기준 2)"
    silent = [k for k in ROBUSTNESS_REPORT_KEYS if k not in shown_in_value and note(**{k: 7}) == note()]
    assert silent == []


def test_the_disclosure_names_rows_cap_and_errors():
    qr = {"robustness_rows": {"inputs_with_design_range": 9, "compared_constants_outside_design": 4,
                              "constants_outside_type": 1, "rows": 12, "cut": 3, "duplicates": 0, "cap_per_unit": 12,
                              "units_with_rows": 2, "errors": 0, "live": 3}}
    item = {i["key"]: i for i in build_disclosures("suts", qr)}["suts_robustness_rows"]
    assert item["value"] == "12행 (unit 2 · 설계 범위·선언 타입이 있는 입력 9 · 설계 범위 밖 직접 비교 상수 4, 살아 있는 기준 3)"
    assert "상한 12행에 잘린 점 3" in item["note"] and "타입 밖이라 쓰지 않은 상수 1" in item["note"]
    assert item["tone"] == "warning"
    only_live = {i["key"]: i for i in build_disclosures("suts", {"robustness_rows": {
        "rows": 3, "live": 1, "macro_argument_live": 1}})}["suts_robustness_rows"]["note"]
    assert "매크로의 인자 안에서만 나온 비교 중" in only_live      # (round 5 W-1) the sentence names its subject
    for key, words in (("not_live", "살아 있는 기준 행을 못 찾은 상수 2"), ("macro_argument_unconfirmed", "이 빌드에 있는지 확인하지 못해"),
                       ("macro_argument_live", "꺾임이 다른 원인일 수도"), ("unprobed", "점이 셋 미만"), ("no_base", "유효한 기준 행이 없어"),
                       ("inputs_type_unconfirmed", "타입 폭이 선언으로 확정되지 않아"),
                       ("undecided_preprocessor_blocks", "`#elif` 지시문 2개"), ("underived", "도출하지 못해 만들지 않은 점 2")):
        note = {i["key"]: i for i in build_disclosures("suts", {"robustness_rows": {**qr["robustness_rows"], key: 2}})}
        assert words in note["suts_robustness_rows"]["note"], key
    assert "suts_robustness_rows" not in {i["key"] for i in build_disclosures("suts", {})}
