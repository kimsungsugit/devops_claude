"""R35 — ``TRUE``/``FALSE`` are names to the preprocessor, keywords to tree-sitter-c.

tree-sitter-c parses ``TRUE``/``FALSE`` (and ``true``/``false``) as ``true``/``false`` nodes. KJPDS02_PV's Processor
Expert drivers compare with ``(byte)TRUE`` — a project macro (``#define TRUE 1U``). The source oracle returned
"bool_keyword_unmodeled" (111 expected cells of 12 functions stayed unknown) and MC/DC design refused the decision
(``unsupported_scalar:true`` — 14 decisions). Every "is this a name?" question now asks `cpc.is_name_node`: a macro the
unit defines gives its value; a name nothing defines (``true`` without a parsed <stdbool.h>) stays unresolved — no
value invented.

PV's ``TRUE`` is defined under an undecided ``#ifdef __MISRA__`` (``1u`` or ``1``). Reading such a macro used to count
as a possible write of anything (every known value lost — ``ADC_MONITOR_Enable`` returned 0, then unknown). An
undecided macro is now judged by every definition the tree has, as MC/DC design already judged it.
"""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs
from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design

ROOT = os.path.join(os.sep, "p35")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#define TRUE 1U
#define FALSE 0U
#endif
"""
UNIT = """#include "common.h"
U8 g_en;
U8 g_on;
U8 g_o;
void f(void) { if (g_en == (U8)TRUE) { g_o = 5U; } else { g_o = 6U; } }
void h(void) { if (g_en == true) { g_o = 1U; } else { g_o = 2U; } }
void m(void) { if ((g_en == (U8)TRUE) && (g_on == FALSE)) { g_o = 1U; } else { g_o = 2U; } }
"""
# Processor Expert's PE_Types.h: the value depends on a name only the toolchain may define
UNDECIDED = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#ifdef __MISRA__
#define TRUE 1u
#define FALSE 0u
#else
#define TRUE 1
#define FALSE 0
#endif
#ifdef __MISRA__
#define CUR (g_p)
#define SETS (g_p = 1U)
#else
#define CUR 0U
#define SETS 1U
#endif
#endif
"""
UNDECIDED_UNIT = """#include "common.h"
U8 g_en;
U8 g_o;
U8 g_p;
U8 g_q;
U8 rd(void) { return 1U; }
U8 r(void) { g_o = TRUE; return 0U; }
void u(void) { g_p = 5U; g_o = (U8)SETS; }
void s(void) { g_p = 5U; SETS; }
void q(void) { g_p = 7U; g_o = (U8)(rd() == TRUE); }
void c(void) { g_p = 7U; g_o = (U8)(rd() == CUR); }
void a(void) { g_o = (U8)(g_en && (g_p == TRUE)); g_q = 3U; }
"""


def _unit(name, header=COMMON, text=UNIT, **kw):
    path = os.path.join(ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): header, path: text})
    unit = {"name": name, "source_text": text, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path]}
    unit.update(kw)
    return unit


def _outputs(name, names, header=COMMON, text=UNIT, **inputs):
    (res,) = evaluate_outputs(_unit(name, header, text), [inputs], [names])
    return res.get("outputs") or {}


def _g_o(name, **inputs):
    return _outputs(name, ["g_o"], **inputs).get("g_o")


def test_a_project_true_macro_gives_its_value():
    assert _g_o("f", g_en=1) == {"value": 5, "basis": "assigned"}
    assert _g_o("f", g_en=0) == {"value": 6, "basis": "assigned"}


def test_a_name_nothing_defines_stays_unresolved():
    # ``true`` with no <stdbool.h> in the parsed tree: the preprocessor would not know it either
    got = _g_o("h", g_en=1)
    assert "value" not in got and got["reason"].endswith("identifier_unresolved:true")


def test_mcdc_designs_a_decision_comparing_with_the_macros():
    report = build_mcdc_design(_unit("m", input_vars=["g_en", "g_on"], mcdc_free_globals=True))
    (decision,) = report["decisions"]
    assert decision["status"] == "designed", decision
    assert {c["expression"] for c in decision["conditions"]} == {"g_en == (U8)TRUE", "g_on == FALSE"}
    assert len(decision["pairs"]) == 2                       # both conditions shown to act independently
    # the re-validation after the row cap reads the same constants the design used (review C1: TRUE/FALSE were left
    # out of ``report["constants"]`` and every pair came back "invalidated")
    assert set(report["constants"]) >= {"TRUE", "FALSE"}
    rows = [{"seq_num": i + 1, "inputs": {k: v for k, v in vec.items()}}
            for i, vec in enumerate(v for p in decision["pairs"] for v in (p["inputs_a"], p["inputs_b"]))]
    finalize_mcdc_design(report, rows)
    assert [p["retained_status"] for p in decision["pairs"]] == ["retained", "retained"]


def test_the_not_false_idiom_is_one_value_for_the_oracle_and_the_design():
    # ``#define TRUE (!FALSE)``: the constant evaluator reads the ``false`` node as the name it is
    header = COMMON.replace("#define TRUE 1U", "#define TRUE (!FALSE)")
    assert _outputs("f", ["g_o"], header=header, g_en=1)["g_o"] == {"value": 5, "basis": "assigned"}
    report = build_mcdc_design(_unit("m", header=header, input_vars=["g_en", "g_on"], mcdc_free_globals=True))
    (decision,) = report["decisions"]
    assert decision["status"] == "designed", decision
    assert report["constants"]["TRUE"]["value"] == 1


def test_reading_an_undecided_constant_macro_loses_nothing_else():
    # (review W2) every definition of TRUE is a constant: its value is unknown, nothing else is
    got = _outputs("r", ["return", "g_o"], header=UNDECIDED, text=UNDECIDED_UNIT)
    assert got["return"] == {"value": 0, "basis": "returned"} or got["return"].get("value") == 0, got
    assert "value" not in got["g_o"] and "macro_body_unknown:TRUE" in got["g_o"]["reason"]


def test_an_undecided_macro_that_may_write_still_forgets_what_it_may_write():
    # one definition of SETS assigns g_p: reading it must not keep g_p = 5 (inside a larger expression the run is
    # refused; as a statement of its own every value it may write is forgotten)
    got = _outputs("u", ["g_p", "g_o"], header=UNDECIDED, text=UNDECIDED_UNIT)
    assert "value" not in got["g_p"] and got["g_p"]["reason"] == "macro_side_effect_in_expression:SETS", got
    got = _outputs("s", ["g_p"], header=UNDECIDED, text=UNDECIDED_UNIT)
    assert "value" not in got["g_p"] and got["g_p"]["reason"].endswith("macro_body_unknown:SETS"), got


def test_order_of_evaluation_refuses_only_a_macro_that_may_read_an_object():
    # TRUE reads nothing in any definition: a call beside it cannot change it (g_p stays known)
    got = _outputs("q", ["g_p", "g_o"], header=UNDECIDED, text=UNDECIDED_UNIT)
    assert got["g_p"].get("value") == 7, got
    # CUR may read g_p: with a call in the same expression the order matters — refused as before
    got = _outputs("c", ["g_p", "g_o"], header=UNDECIDED, text=UNDECIDED_UNIT)
    assert "value" not in got["g_o"] and "macro_in_order_dependent_expression:CUR" in got["g_o"]["reason"], got


def test_an_undecided_constant_macro_is_no_hidden_call_under_an_unknown_condition():
    # g_en unknown: the right operand of && may or may not run. TRUE hides no call in any definition, so the run goes
    # on (it used to be refused as "side_effect_under_unknown_condition" and g_q = 3U was lost with it)
    got = _outputs("a", ["g_o", "g_q"], header=UNDECIDED, text=UNDECIDED_UNIT, g_p=1)
    assert got["g_q"] == {"value": 3, "basis": "assigned"}, got
    assert "value" not in got["g_o"], got


# (review R35 round 1 C1) text a scan cannot read: a call through an expression, a pasted name, an address after a cast
OPAQUE = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_p;
extern U8 (*g_fp)(void);
U8 wr(void);
#define WR (g_p = 9U)
#ifdef __MISRA__
#define HOOK_IND ((*g_fp)())
#define HOOK_PASTE W##R
#define PTR_LOC ((U8 *)&loc)
#define HOOK (wr())
#define COND (g_p && g_en)
#else
#define HOOK_IND 0U
#define HOOK_PASTE 0U
#define PTR_LOC ((U8 *)0)
#define HOOK 0U
#define COND 0U
#endif
#ifdef __MISRA__
#define TRUE 1u
#else
#define TRUE 1
#endif
#endif
"""
OPAQUE_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 g_en;
U8 (*g_fp)(void);
U8 wr(void) { g_p = 9U; return 0U; }
void ind(void) { g_p = 5U; g_o = HOOK_IND; }
void ind_stmt(void) { g_p = 5U; HOOK_IND; }
void paste(void) { g_p = 5U; g_o = HOOK_PASTE; }
void loc_esc(void) { U8 loc = 1U; U8 *p; p = PTR_LOC; *p = 5U; g_o = loc; }
void hook(void) { g_p = 5U; HOOK; }
void m3(void) { U8 l = g_en; if ((l == (U8)TRUE) && (g_p == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void m4(void) { U8 l = g_en; if ((l == 1U) && (g_p == COND)) { g_o = 1U; } else { g_o = 2U; } }
"""


def test_an_undecided_macro_whose_text_hides_its_effect_is_never_read_as_effect_free():
    for fn, name, stale in (("ind", "g_p", 5), ("ind_stmt", "g_p", 5), ("paste", "g_p", 5), ("loc_esc", "g_o", 1)):
        got = _outputs(fn, [name], header=OPAQUE, text=OPAQUE_UNIT)[name]
        assert got.get("value") != stale and "value" not in got, (fn, got)
    scope = _unit("ind", header=OPAQUE, text=OPAQUE_UNIT)["project_scope"]
    assert [m for m in ("HOOK_IND", "HOOK_PASTE", "PTR_LOC") if cpc.undecided_macro_view(scope, m) is None] == [
        "HOOK_IND", "HOOK_PASTE", "PTR_LOC"]
    assert cpc.undecided_macro_view(scope, "TRUE") is not None


def test_an_undecided_macro_that_may_call_a_function_forgets_what_the_call_may_write():
    got = _outputs("hook", ["g_p"], header=OPAQUE, text=OPAQUE_UNIT)["g_p"]
    assert "value" not in got and got["reason"].endswith("macro_body_unknown:HOOK"), got


def test_the_view_is_none_when_the_tree_is_not_the_whole_story():
    ok = {"writes": False, "calls": [], "names": [], "function_like": False, "opaque": False, "conditional_ops": False}
    base = {"effects": {"macros": {"TRUE": ok}}}
    view = cpc.undecided_macro_view(base, "TRUE")
    assert view is not None and view["opaque"] is False and view["reach_names"] == () and view["cast_words"] == ()
    assert cpc.undecided_macro_view({**base, "missing_includes": ["gone.h"]}, "TRUE") is None
    assert cpc.undecided_macro_view({**base, "build_defines": {"defines": {"TRUE": "1"}}}, "TRUE") is None
    assert cpc.undecided_macro_view({"effects": {"macros": {"TRUE": {**ok, "opaque": True}}}}, "TRUE") is None
    old = {k: v for k, v in ok.items() if k != "opaque"}          # a closure built by code before R35
    assert cpc.undecided_macro_view({"effects": {"macros": {"TRUE": old}}}, "TRUE") is None
    assert cpc.undecided_macro_view(base, "OTHER") is None


def test_the_path_design_sees_an_undecided_constant_as_a_value_not_as_hidden_conditions():
    unit = _unit("m3", header=OPAQUE, text=OPAQUE_UNIT, input_vars=["g_en", "g_p"], mcdc_free_globals=True)
    (d,) = build_mcdc_design(unit)["decisions"]
    assert "hidden_in_macro" not in d["reason"] and "macro_body_unknown" in d["reason"], d["reason"]
    unit = _unit("m4", header=OPAQUE, text=OPAQUE_UNIT, input_vars=["g_en", "g_p"], mcdc_free_globals=True)
    (d,) = build_mcdc_design(unit)["decisions"]
    assert d["reason"] == "path_refused:decision_conditions_hidden_in_macro:COND", d["reason"]


def test_if_through_a_macro_whose_body_is_true_follows_the_same_rule_as_if_true():
    # ``#define EN TRUE`` + ``#if EN``: TRUE is a name here as in ``#if TRUE``; a unit that does not see its definition
    # reads it as undefined under the disclosed assumption that headers outside the tree define no project name
    cfg = """#ifndef CFG_H
#define CFG_H
typedef unsigned char U8;
typedef unsigned int U16;
#define EN TRUE
#if EN
#define MODE 1U
#else
#define MODE 2U
#endif
#if TRUE
#define MODE2 1U
#else
#define MODE2 2U
#endif
#endif
"""
    text = '#include "cfg.h"\nU8 g_o;\nU8 g_p;\nvoid e(void) { g_o = MODE; g_p = MODE2; }\n'
    path = os.path.join(ROOT, "u2.c")
    files = {os.path.join(ROOT, "cfg.h"): cfg, os.path.join(ROOT, "other.h"): "#define TRUE 1U\n", path: text}
    context = cpc.build_project_context(files)
    scope = cpc.build_scopes(context, [path])[path]
    unit = {"name": "e", "source_text": text, "source_path": path, "source_text_complete": True, "project_scope": scope}
    (res,) = evaluate_outputs(unit, [{}], [["g_o", "g_p"]])
    got = res["outputs"]
    assert got["g_o"] == got["g_p"] and "value" in got["g_o"], got


# (review R35 round 2 C1') an undecided macro whose own text is clean but names an opaque active macro
CHAIN = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_p;
extern U8 (*g_fp)(void);
#define WR (g_p = 9U)
#define CALL_FP ((*g_fp)())
#define PASTE_A W##R
#define PTR_A ((U8 *)&loc)
#ifdef __MISRA__
#define HOOK1 CALL_FP
#define HOOK2 PASTE_A
#define HOOK3 PTR_A
#else
#define HOOK1 0U
#define HOOK2 0U
#define HOOK3 ((U8 *)0)
#endif
#endif
"""
CHAIN_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 (*g_fp)(void);
U8 w(void) { g_p = 9U; return 0U; }
void c1(void) { g_p = 5U; g_o = HOOK1; }
void c2(void) { g_p = 5U; g_o = HOOK2; }
void c3(void) { U8 loc = 1U; U8 *p; p = HOOK3; *p = 5U; g_o = loc; }
void c1s(void) { g_p = 5U; HOOK1; }
"""


def test_opacity_is_transitive_through_a_mentioned_macro():
    for fn, name, stale in (("c1", "g_p", 5), ("c2", "g_p", 5), ("c3", "g_o", 1), ("c1s", "g_p", 5)):
        got = _outputs(fn, [name], header=CHAIN, text=CHAIN_UNIT)[name]
        assert "value" not in got, (fn, got, stale)
    scope = _unit("c1", header=CHAIN, text=CHAIN_UNIT)["project_scope"]
    assert [m for m in ("HOOK1", "HOOK2", "HOOK3") if cpc.undecided_macro_view(scope, m) is None] == [
        "HOOK1", "HOOK2", "HOOK3"]


# (review R35 round 2 C2) a line splice kept in a body hides ``name(`` and ``)(`` from the text scan
SPLICE = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_p;
extern U8 (*g_fp)(void);
#ifdef __MISRA__
#define H_CONT ((*g_fp) @BS@@NL@  ())
#define H_NAME wr @BS@@NL@  ()
#else
#define H_CONT 0U
#define H_NAME 0U
#endif
#endif
""".replace("@BS@", chr(92)).replace("@NL@", chr(10))
SPLICE_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 (*g_fp)(void);
U8 wr(void) { g_p = 9U; return 0U; }
void k1(void) { g_p = 5U; g_o = H_CONT; }
void k2(void) { g_p = 5U; g_o = H_NAME; }
"""


def test_a_line_splice_in_a_body_is_opaque():
    for fn in ("k1", "k2"):
        got = _outputs(fn, ["g_p"], header=SPLICE, text=SPLICE_UNIT)["g_p"]
        assert "value" not in got, (fn, got)


# (review R35 round 2 W1) an inert macro indexing the left side: the right side stays the safe top, so a macro read in
# its call's argument (sequenced before the call) is not an order question
INDEX = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#ifdef __MISRA__
#define IDX 1u
#define CUR (g_p)
#else
#define IDX 1
#define CUR 0U
#endif
#endif
"""
INDEX_UNIT = """#include "common.h"
U8 g_arr[4];
U8 g_p;
U8 g_q;
U8 id(U8 v) { return v; }
void f(void) { g_arr[IDX] = id(CUR); g_q = 3U; }
"""


def test_an_inert_left_index_keeps_the_right_side_the_safe_top():
    got = _outputs("f", ["g_q"], header=INDEX, text=INDEX_UNIT)["g_q"]
    assert got == {"value": 3, "basis": "assigned"}, got


# (review R35 round 3 C3) an undecided macro that names a local hands out its address without an ``&`` in its text
ESCAPE = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_d;
extern U8 g_arr[2];
#define LP (la)
#ifdef __MISRA__
#define ARR2 LP
#define OBJ loc
#define ARR (la)
#else
#define OBJ g_d
#define ARR (g_arr)
#define ARR2 (g_arr)
#endif
#endif
"""
ESCAPE_UNIT = """#include "common.h"
U8 g_d;
U8 g_arr[2];
U8 g_o;
void put(U8 *q) { *q = 5U; }
void a(void) { U8 loc = 1U; U8 *p; p = &OBJ; *p = 5U; g_o = loc; }
void b(void) { U8 la[2] = {1U, 2U}; U8 *p; p = ARR; *p = 5U; g_o = la[0]; }
void c(void) { U8 la[2] = {1U, 2U}; put(ARR); g_o = la[0]; }
void d(void) { U8 loc = 1U; put(&OBJ); g_o = loc; }
void f(void) { U8 la[2] = {1U, 2U}; U8 *p; p = ARR2; *p = 5U; g_o = la[0]; }
"""


def test_an_undecided_macro_naming_a_local_may_hand_out_its_address():
    for fn in "abcdf":
        got = _outputs(fn, ["g_o"], header=ESCAPE, text=ESCAPE_UNIT)["g_o"]
        assert "value" not in got, (fn, got)


# (review R35 round 3 W1) a chain of undecided macros longer than the depth cut-off: the verdict must not depend on
# which vector asked first
_CHAIN = ["#ifndef COMMON_H", "#define COMMON_H", "typedef unsigned char U8;", "typedef unsigned int U16;"]
for _branch, _leaf in (("#ifdef __MISRA__", "1u"), ("#else", "1")):
    _CHAIN += [_branch] + [f"#define M{i} (M{i + 1})" for i in range(10)] + [f"#define M10 {_leaf}"]
LONG_CHAIN = "\n".join([*_CHAIN, "#endif", "#endif", ""])
LONG_CHAIN_UNIT = """#include "common.h"
U8 g_en;
U8 g_a;
U8 g_o;
U8 g_q;
U8 rd(void) { return 1U; }
void f(void) { if (g_en == 1U) { g_a = (U8)(rd() == M5); } g_o = (U8)(rd() == M0); g_q = 3U; }
"""


def test_the_judgment_of_a_long_macro_chain_does_not_depend_on_row_order():
    def run(order):
        (unit,) = [_unit("f", header=LONG_CHAIN, text=LONG_CHAIN_UNIT)]
        res = evaluate_outputs(unit, [{"g_en": e} for e in order], [["g_q"]] * len(order))
        return {e: r["outputs"]["g_q"] for e, r in zip(order, res, strict=True)}
    assert run([1, 0]) == run([0, 1])
    assert run([0]) == {0: run([1, 0])[0]} and run([1]) == {1: run([0, 1])[1]}


# (review R35 round 3 W2) ``Hook`` is a typedef in another root and a function pointer here: ``((Hook)())`` is a call
COLLIDE = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_p;
extern U8 (*Hook)(void);
#define CAST_CALL ((Hook)())
#ifdef __MISRA__
#define H_TD ((Hook)())
#define H_TD2 CAST_CALL
#else
#define H_TD 0U
#define H_TD2 0U
#endif
#endif
"""
COLLIDE_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 (*Hook)(void);
void k3(void) { g_p = 5U; g_o = H_TD; }
void k4(void) { g_p = 5U; g_o = H_TD2; }
"""


def test_a_name_the_tree_also_declares_as_an_object_is_no_cast():
    path = os.path.join(ROOT, "unit.c")
    files = {os.path.join(ROOT, "common.h"): COLLIDE, os.path.join(ROOT, "other.h"): "typedef unsigned char Hook;\n",
             path: COLLIDE_UNIT}
    scope = cpc.build_scopes(cpc.build_project_context(files), [path])[path]
    for fn in ("k3", "k4"):   # k4: through the active macro it mentions — the cast words are closed like the names
        unit = {"name": fn, "source_text": COLLIDE_UNIT, "source_path": path, "source_text_complete": True,
                "project_scope": scope}
        (res,) = evaluate_outputs(unit, [{}], [["g_p"]])
        assert "value" not in res["outputs"]["g_p"], (fn, res["outputs"])
    assert cpc.undecided_macro_view(scope, "H_TD") is None and cpc.undecided_macro_view(scope, "H_TD2") is None


# (review R35 round 3 W3) a body whose brackets do not pair up: the call is formed with a mentioned macro's ``(``
UNBALANCED = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
U8 wr(U8 v);
#define LP (
#ifdef __MISRA__
#define H_UNBAL (wr LP 0U))
#else
#define H_UNBAL 0U
#endif
#endif
"""
UNBALANCED_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 wr(U8 v) { g_p = 9U; return v; }
void u(void) { g_p = 5U; g_o = H_UNBAL; }
"""


def test_a_body_with_unpaired_brackets_is_opaque():
    got = _outputs("u", ["g_p"], header=UNBALANCED, text=UNBALANCED_UNIT)["g_p"]
    assert "value" not in got, got
    assert cpc.macro_body_opaque("(") and not cpc.macro_body_opaque('"("') and not cpc.macro_body_opaque("1u")


def _scope_of(files, path):
    return cpc.build_scopes(cpc.build_project_context(files), [path])[path]


def _run(scope, text, path, fn, names):
    unit = {"name": fn, "source_text": text, "source_path": path, "source_text_complete": True, "project_scope": scope}
    (res,) = evaluate_outputs(unit, [{}], [names])
    return res["outputs"]


# (review R35 round 4 C4) ``Hook`` is a typedef in one arm of an undecided #if and a function pointer in the other
CONDITIONAL_TYPEDEF = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#ifdef __MISRA__
extern U8 (*Hook)(void);
#define H_TD ((Hook)())
#else
typedef unsigned char Hook;
#define H_TD 0U
#endif
#endif
"""
CONDITIONAL_TYPEDEF_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
#ifdef __MISRA__
U8 (*Hook)(void);
#endif
U8 w(void) { g_p = 9U; return 0U; }
void k6(void) { g_p = 5U; g_o = H_TD; }
"""


def test_a_conditional_typedef_is_no_cast_word():
    path = os.path.join(ROOT, "unit.c")
    scope = _scope_of({os.path.join(ROOT, "common.h"): CONDITIONAL_TYPEDEF, path: CONDITIONAL_TYPEDEF_UNIT}, path)
    assert "value" not in _run(scope, CONDITIONAL_TYPEDEF_UNIT, path, "k6", ["g_p"])["g_p"]
    assert "Hook" not in scope["typedef_names"]


# (review R35 round 4 C4) a constant evaluation that tried ``Hook`` as a type records it in ``unresolved_types``:
# the view must not change with what was evaluated before
HISTORY = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 (*Hook)(void);
#define HK0 ((Hook)(0U))
#ifdef __MISRA__
#define H_TD ((Hook)())
#else
#define H_TD 0U
#endif
#endif
"""
HISTORY_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 (*Hook)(void);
U8 w(void) { g_p = 9U; return 0U; }
void k7(void) { g_p = 5U; g_o = H_TD; }
"""


def test_the_view_does_not_change_with_what_was_evaluated_before():
    path = os.path.join(ROOT, "unit.c")
    files = {os.path.join(ROOT, "common.h"): HISTORY, os.path.join(ROOT, "other.h"): "typedef unsigned char Hook;" + chr(10),
             path: HISTORY_UNIT}
    first = _run(_scope_of(files, path), HISTORY_UNIT, path, "k7", ["g_p"])
    scope = _scope_of(files, path)
    try:
        scope["constants"]["HK0"]          # a lazy constant lookup tries ``Hook`` as a type
    except KeyError:
        pass
    assert "Hook" in scope["unresolved_types"]
    after = _run(scope, HISTORY_UNIT, path, "k7", ["g_p"])
    assert first == after and "value" not in after["g_p"], (first, after)


# (review R35 round 4 W1) a function-pointer parameter hiding the typedef ``Hook``: ``((Hook)())`` calls it
SHADOW = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef unsigned char Hook;
#ifdef __MISRA__
#define H_TD ((Hook)())
#else
#define H_TD 0U
#endif
#endif
"""
SHADOW_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
void k10(U8 (*Hook)(void)) { g_p = 5U; g_o = H_TD; }
"""


def test_a_parenthesized_parameter_declarator_is_a_name_the_function_declares():
    path = os.path.join(ROOT, "unit.c")
    scope = _scope_of({os.path.join(ROOT, "common.h"): SHADOW, path: SHADOW_UNIT}, path)
    assert "value" not in _run(scope, SHADOW_UNIT, path, "k10", ["g_p"])["g_p"]


# (review R35 round 5 W1) ``Hook`` is a typedef of the unit and, later, a macro: ``(Hook)()`` rescans into a call
CAST_MACRO = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef unsigned char Hook;
extern U8 (*g_fp)(void);
#define Hook g_fp
#ifdef __MISRA__
#define H_TD ((Hook)())
#else
#define H_TD 0U
#endif
#endif
"""
CAST_MACRO_UNIT = """#include "common.h"
U8 g_p;
U8 g_o;
U8 (*g_fp)(void);
U8 w(void) { g_p = 9U; return 0U; }
void m1(void) { g_p = 5U; g_o = H_TD; }
"""


def test_a_cast_word_that_is_also_a_macro_is_no_cast():
    path = os.path.join(ROOT, "unit.c")
    scope = _scope_of({os.path.join(ROOT, "common.h"): CAST_MACRO, path: CAST_MACRO_UNIT}, path)
    assert "Hook" in scope["typedef_names"]
    assert cpc.undecided_macro_view(scope, "H_TD") is None
    assert "value" not in _run(scope, CAST_MACRO_UNIT, path, "m1", ["g_p"])["g_p"]
