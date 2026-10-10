"""R2c (P2/G3) — MC/DC design on the modeled function run (`mcdc_design._path_design` over
`c_source_oracle.observe_decisions`).

The expression engine designs a decision only when its operands are the function's inputs at entry. A decision that reads
a local, an input rewritten before it, or a global a callee may change is designed here by running the whole function
in the source oracle per input vector and observing what each condition holds when the decision is reached. Every
expected value below is what a C compiler for a 16-bit-int target computes (clang ``--target=msp430``).
"""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs, observe_decisions
from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef signed long S32;
#endif
"""
H = '#include "common.h"\n'


def _p(name):
    return os.path.join(ROOT, name)


def _unit(text, name, inputs=None, free_globals=True):
    files = {_p("common.h"): COMMON, _p("unit.c"): text}
    context = cpc.build_project_context(files)
    scope = cpc.build_scopes(context, [_p("unit.c")])[_p("unit.c")]
    unit = {"name": name, "source_text": text, "source_path": _p("unit.c"), "source_text_complete": True,
            "project_scope": scope}
    if inputs is not None:
        unit["input_vars"] = list(inputs)
    if free_globals:
        unit["mcdc_free_globals"] = True
    return unit


def _design(text, name, inputs=None, free_globals=True):
    unit = _unit(text, name, inputs, free_globals)
    return unit, build_mcdc_design(unit)


def _rows(report):
    """SUTS-like rows: one per selected vector (what `generate_sequences` emits for MC/DC slots)."""
    return [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]


def _truth_of(unit, decision, inputs):
    r = observe_decisions(unit, [inputs], [decision["path_spec"]])[0]
    return r["decisions"][0]


def test_a_decision_on_a_local_is_designed_on_the_modeled_run():
    text = H + "U8 g_out;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U); if ((t > 3U) && (b == 1U)) { g_out = 1U; } }\n"
    unit, report = _design(text, "f", ["a", "b"])
    d = report["decisions"][0]
    assert d["static_reason"] == "local_variable_not_input:t"
    assert d["evaluation"] == "source_path" and d["status"] == "designed"
    for pair in d["pairs"]:
        # the independent effect holds on the run: re-observe both vectors
        for side in ("a", "b"):
            got = _truth_of(unit, d, pair[f"inputs_{side}"])
            assert got["state"] == "evaluated"
            assert {"truth": pair[f"truth_{side}"], "observed": pair[f"observed_{side}"],
                    "decision": pair[f"decision_{side}"]} in got["instances"]
        # vectors set only the function's inputs — never the local
        assert set(pair["inputs_a"]) <= {"a", "b", "g_out"}
    c1 = next(p for p in d["pairs"] if p["condition_id"] == "C1")
    # t = a + 1 > 3 ⇔ a > 2: the pair straddles that threshold; the side where C1 holds needs b == 1 (C2 decides),
    # on the other side C2 is skipped by the short circuit — its value is a don't-care
    assert {c1["inputs_a"]["a"] > 2, c1["inputs_b"]["a"] > 2} == {True, False}
    true_side = "a" if c1["truth_a"][0] else "b"
    assert c1[f"inputs_{true_side}"]["b"] == 1 and c1[f"observed_{true_side}"] == [True, True]


def test_an_input_rewritten_before_the_decision_is_read_after_the_write():
    text = H + "void f(U8 x, U8 y) { if (x > 10U) { x = 10U; } if ((x == 10U) || (y == 0U)) { } }\n"
    unit, report = _design(text, "f", ["x", "y"])
    d = report["decisions"][1]
    assert d["static_reason"] == "input_modified_before_decision:x"
    assert d["status"] == "designed"
    c1 = next(p for p in d["pairs"] if p["condition_id"] == "C1")
    # x == 10 after the clamp for every x >= 10; where C1 is false C2 decides, so that side needs y != 0
    false_side = "a" if c1["truth_a"][0] is False else "b"
    assert c1[f"inputs_{false_side}"]["y"] != 0 and c1[f"inputs_{false_side}"]["x"] < 10
    assert c1["inputs_" + ("b" if false_side == "a" else "a")]["x"] >= 10


def test_a_guarded_decision_is_reached_by_climbing_its_guard_chain():
    text = H + ("U8 g_mode; U8 g_cnt;\n"
                "void f(U8 a, U8 b) { U8 t; if (g_mode != 3U) { return; } if (g_cnt < 7U) { return; }\n"
                "  t = (U8)(a * 2U); if ((t >= 20U) && (b != 0U)) { g_cnt = 0U; } }\n")
    unit, report = _design(text, "f", ["a", "b"])
    d = report["decisions"][2]
    assert d["static_reason"].startswith("local_variable_not_input:")
    assert d["status"] == "designed", d.get("path_search")
    for pair in d["pairs"]:
        # every member of a pair passes both guards: g_mode == 3 and g_cnt >= 7
        for side in ("a", "b"):
            assert pair[f"inputs_{side}"]["g_mode"] == 3 and pair[f"inputs_{side}"]["g_cnt"] >= 7


def test_in_suts_mode_a_global_outside_the_row_is_not_an_input_and_blocks_honestly():
    # The same function with the unit's row = parameters only: g_mode is never set by a row, the guard is undetermined.
    text = H + ("U8 g_mode;\n"
                "void f(U8 a, U8 b) { U8 t; if (g_mode != 3U) { return; } t = (U8)(a * 2U);"
                " if ((t >= 20U) && (b != 0U)) { } }\n")
    _unit_, report = _design(text, "f", ["a", "b"], free_globals=False)
    d = report["decisions"][1]
    assert d["evaluation"] == "source_path" and d["pairs"] == []
    assert d["status"] == "unsupported"
    # g_mode unset: one path returns before the decision, the other reaches it — never "determined"
    assert d["reason"] == "path_evaluation:path_dependent_reach"


def test_a_loop_decision_pairs_evaluations_of_one_run():
    text = H + "U8 g_buf[4];\nvoid f(U8 n) { U8 i; for (i = 0U; i < n; i++) { g_buf[i & 3U] = 0U; } }\n"
    unit, report = _design(text, "f", ["n"])
    d = report["decisions"][0]
    assert d["static_reason"].startswith(("local_variable_not_input:i", "input_modified_before_decision"))
    assert d["status"] == "designed"
    pair = d["pairs"][0]
    # both evaluations may come from one vector (i < n true, then false)
    assert pair["decision_a"] != pair["decision_b"]


def test_a_condition_the_short_circuit_skips_may_be_undefined_without_blocking_the_pair():
    text = H + "U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = a; if ((t != 0U) && ((U8)(100U / t) > b)) { g_o = 1U; } }\n"
    unit, report = _design(text, "f", ["a", "b"])
    d = report["decisions"][0]
    c1 = next(p for p in d["pairs"] if p["condition_id"] == "C1")
    side = "a" if c1["truth_a"][0] is False else "b"
    # t == 0: the division is undefined but never evaluated — its truth is not determined ("-" on the sheet)
    assert c1[f"truth_{side}"][1] is None and c1[f"observed_{side}"] == [True, False]


def test_a_condition_that_calls_is_not_observed_on_a_copy():
    text = H + "U8 rd(void);\nvoid f(U8 a) { U8 t = a; if ((t > 1U) && (rd() == 2U)) { } }\n"
    _u, report = _design(text, "f", ["a"])
    d = report["decisions"][0]
    assert d["status"] == "unsupported" and d["reason"] == "path_evaluation:effectful_condition"


def test_a_macro_that_writes_a_local_in_place_is_seen_by_the_run():
    # ``ZERO(x)`` pastes ``x_v``: the expansion writes a parameter directly (a callee could not)
    text = H + "#define ZERO(n) n##_v = 0U\nU8 g_o;\nvoid f(U8 x, U8 x_v) { ZERO(x); g_o = x_v; }\n"
    out = evaluate_outputs(_unit(text, "f"), [{"x": 1, "x_v": 5}], [["g_o"]])[0]["outputs"]["g_o"]
    assert "value" not in out and out["reason"].startswith("macro_call_unmodeled:ZERO")


def test_finalize_revalidates_path_pairs_on_the_emitted_rows():
    text = H + "void f(U8 a, U8 b) { U8 t = (U8)(a + 1U); if ((t > 3U) && (b == 1U)) { } }\n"
    unit, report = _design(text, "f", ["a", "b"])
    rows = _rows(report)
    finalize_mcdc_design(report, rows, unit)
    d = report["decisions"][0]
    assert {p["retained_status"] for p in d["pairs"]} == {"retained"}
    # without the unit (no source to re-run) the same pairs cannot be revalidated
    finalize_mcdc_design(report, _rows(report))
    assert {p["retained_status"] for p in d["pairs"]} == {"invalidated"}
    # the source changed under the design (threshold 3 → 9, same length): the C1 pair no longer realizes its claim
    stale = _unit(text.replace("t > 3U", "t > 9U"), "f", ["a", "b"])
    finalize_mcdc_design(report, _rows(report), stale)
    c1 = next(p for p in d["pairs"] if p["condition_id"] == "C1")
    assert c1["retained_status"] == "invalidated"


def test_undefined_behaviour_before_the_decision_is_not_an_observation():
    text = H + "void f(S16 a, U8 b) { S16 t = (S16)(a + 30000); if ((t > 0) && (b == 1U)) { } }\n"
    unit, report = _design(text, "f", ["a", "b"])
    d = report["decisions"][0]
    for pair in d["pairs"]:
        for side in ("a", "b"):
            # a + 30000 overflows a 16-bit int for a > 2767: no member of a pair is such an input
            assert pair[f"inputs_{side}"]["a"] <= 2767


def test_the_static_verdict_is_kept_when_the_expression_engine_designs_the_decision():
    text = H + "void f(U8 a, U8 b) { if ((a > 3U) && (b == 1U)) { } }\n"
    _u, report = _design(text, "f", ["a", "b"])
    d = report["decisions"][0]
    assert d["status"] == "designed" and "evaluation" not in d and "static_reason" not in d


def test_a_pointer_subscript_read_is_disclosed_like_pointer_arithmetic():
    # ``p[i]`` is ``*(p + i)``: the element may lie outside the object — clang found ``tbl[255]`` of a 64-element buffer
    text = H + "S16 g_o;\nvoid f(const S16 *p, U8 i) { g_o = (S16)(p[i] > 0); }\n"
    r = evaluate_outputs(_unit(text, "f"), [{"i": 3}], [["g_o"]])[0]
    assert "pointer_arithmetic_untyped" in r["possible_undefined_behavior"]


def test_the_path_search_is_deterministic_and_bounded_by_its_step_budget():
    text = H + ("U8 g_mode; U8 g_cnt;\n"
                "void f(U8 a, U8 b) { U8 t; if (g_mode != 3U) { return; } if (g_cnt < 7U) { return; }\n"
                "  t = (U8)(a * 2U); if ((t >= 20U) && (b != 0U)) { g_cnt = 0U; } }\n")
    import json
    first = build_mcdc_design(_unit(text, "f", ["a", "b"]))
    again = build_mcdc_design(_unit(text, "f", ["a", "b"]))
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(again, sort_keys=True, default=str)
    tight = build_mcdc_design(_unit(text, "f", ["a", "b"]), max_path_steps=50)
    search = tight["decisions"][2]["path_search"]
    assert search["budget_exhausted"] is True
    # the budget is checked between chunks of 16 runs: it is exceeded by at most one chunk
    assert search["runs"] <= 16 + 1 and tight["decisions"][2]["search_complete"] is False


def test_path_pairs_hold_under_clang_and_a_flipped_claim_is_caught():
    import shutil
    import sys
    if shutil.which("clang") is None:
        import pytest
        pytest.skip("clang not installed")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    from mcdc_design_clang_oracle import _path_claims
    from source_oracle_clang_check import check_claims, decision_claim
    text = H + ("U8 g_out;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U); U8 i;\n"
                "  if ((t > 3U) && (b == 1U)) { g_out = 1U; }\n"
                "  for (i = 0U; i < b; i++) { g_out = (U8)(g_out + 1U); } }\n")
    unit, report = _design(text, "f", ["a", "b"])
    claims = _path_claims(unit, report)
    assert claims
    good = check_claims(claims)
    assert good["mismatch"] == 0 and good["eval_error"] == 0 and good["agree"] == len(claims), good
    # flip one claimed outcome: clang must refute it
    bad = dict(claims[0])
    pair = report["decisions"][0]["pairs"][0]
    bad["outputs"] = {decision_claim(0, pair["truth_a"], pair["observed_a"], not pair["decision_a"]): 1}
    bad["inputs"] = pair["inputs_a"]
    refuted = check_claims([bad])
    assert refuted["mismatch"] == 1, refuted


# ── R2c deep review round 1 counterexamples ─────────────────────────────────────────────────────

def test_c1_a_decision_inside_a_macro_argument_is_not_designed():
    # ``#define DBG(...)`` drops its arguments, ``report(#c)`` only stringifies: neither is a decision after preprocessing
    for macros, call in (("#define DBG(...)\n", 'DBG("%d", (t > 3U) && (b == 1U));'),
                         ("void report(const char *s);\n#define CHK(c) report(#c)\n", "CHK((t > 3U) && (b == 1U));")):
        text = H + macros + f"U8 g_o;\nvoid f(U8 a, U8 b) {{ U8 t = (U8)(a + 1U); {call} g_o = t; }}\n"
        _u, report = _design(text, "f", ["a", "b"])
        (d,) = report["decisions"]
        assert d["pairs"] == [] and d["reason"].startswith("decision_inside_macro_argument:")


def test_c2_an_undeclared_callee_after_a_missing_include_may_write_a_parameter():
    files_text = '#include "common.h"\n#include "gone.h"\nvoid f(U8 x, U8 y) { RESET(x); if ((x == 1U) && (y == 1U)) { } }\n'
    unit, report = _design(files_text, "f", ["x", "y"])
    (d,) = report["decisions"]
    assert d["status"] != "designed" and not any(p["condition_id"] == "C1" for p in d["pairs"])
    out = evaluate_outputs(unit, [{"x": 1, "y": 1}], [["return"]])[0]
    assert out["status"] == "supported"


def test_c3_a_macro_that_hides_conditions_is_not_one_condition():
    text = H + ("#define BOTH(x, y) (((x) > 3U) && ((y) == 1U))\nU8 g_o;\n"
                "void f(U8 a, U8 b) { U8 t = (U8)(a + 1U); if ((t != 9U) && BOTH(t, b)) { g_o = 1U; } }\n")
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    (d,) = report["decisions"]
    assert d["pairs"] == [] and d.get("path_refusal") == "decision_conditions_hidden_in_macro:BOTH"
    assert d["reason"] == "path_refused:decision_conditions_hidden_in_macro:BOTH"


def test_w3_a_guard_seen_only_under_an_unknown_condition_does_not_break_the_run():
    text = H + ("volatile U8 g_v; U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U);\n"
                "  if ((t > 5U) && (b == 2U)) { g_o = 2U; }\n"
                "  g_o = (g_v != 0U) ? ((a > 3U) ? ((t > 1U) && (b == 1U)) : 0U) : 0U; }\n")
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    assert report["decisions"][0]["status"] == "designed"


def test_w4_a_prescan_failure_is_a_refusal_for_every_vector_and_never_raises(monkeypatch):
    import generators.c_source_oracle as cso
    text = H + "U8 g_o;\nvoid f(U8 a) { g_o = a; }\n"
    unit = _unit(text, "f", ["a"])

    def boom(self):
        raise ValueError("boom")
    monkeypatch.setattr(cso._Interp, "prescan", boom)
    cso._TREES.cache = None  # a fresh function entry: its prescan verdict is not cached yet
    got = evaluate_outputs(unit, [{"a": 1}, {"a": 2}], [["g_o"], ["g_o"]])
    assert [r["status"] for r in got] == ["unsupported", "unsupported"]
    assert observe_decisions(unit, [{"a": 1}], [])[0]["status"] == "unsupported"


def test_possible_ub_before_the_decision_leaves_it_undetermined():
    text = H + ("S16 g_s; S16 g_q; U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U); g_q = (S16)(g_s + 30000);"
                " if ((t > 3U) && (b == 1U)) { g_o = 1U; } }\n")
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    (d,) = report["decisions"]
    assert d["pairs"] == [] and d["reason"] == "path_evaluation:undetermined:possible_undefined_behavior_before_decision"


def test_a_decision_under_an_unknown_short_circuit_is_maybe_evaluated_never_designed():
    text = H + ("volatile U8 g_v; U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U);"
                " g_o = (U8)((g_v != 0U) && (((t > 3U) || (b == 1U)) ? 1U : 0U)); }\n")
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    inner = next(d for d in report["decisions"] if d["expression"].startswith("(t > 3U)"))
    assert inner["pairs"] == [] and inner["reason"] == "path_evaluation:maybe_evaluated"


def test_finalize_rechecks_unique_cause_not_just_that_both_evaluations_happened():
    text = H + "void f(U8 a, U8 b) { U8 t = (U8)(a + 1U); if ((t > 3U) && (b == 1U)) { } }\n"
    unit, report = _design(text, "f", ["a", "b"])
    pair = report["decisions"][0]["pairs"][0]
    for key in ("inputs", "truth", "observed", "decision"):
        pair[f"{key}_b"] = pair[f"{key}_a"]  # both members the same real evaluation: no independent effect
    finalize_mcdc_design(report, _rows(report), unit)
    assert pair["retained_status"] == "invalidated"


def test_the_function_cache_never_hands_one_scope_another_scopes_definition():
    # one text, two configurations: which definition of ``f`` is compiled depends on the scope, never on the cache
    text = '#include "common.h"\n#include "cfg.h"\n#if CFG == 1\nU8 f(void) { return 1U; }\n#else\nU8 f(void) { return 2U; }\n#endif\n'
    values = []
    for cfg in ("#define CFG 1\n", "#define CFG 0\n"):
        files = {_p("common.h"): COMMON, _p("cfg.h"): cfg, _p("unit.c"): text}
        context = cpc.build_project_context(files)
        scope = cpc.build_scopes(context, [_p("unit.c")])[_p("unit.c")]
        unit = {"name": "f", "source_text": text, "source_path": _p("unit.c"), "source_text_complete": True,
                "project_scope": scope}
        values.append(evaluate_outputs(unit, [{}], [["return"]])[0]["outputs"]["return"].get("value"))
    assert values == [1, 2]


def test_the_sheet_marks_unevaluated_and_undetermined_conditions_as_dont_care():
    from generators.suts import _mcdc_truth_text, _mcdc_vector_label
    assert _mcdc_truth_text([False, True], [True, False]) == "F-"
    assert _mcdc_truth_text([True, None], [True, True]) == "T-"
    label = _mcdc_vector_label([{"decision_id": "D1", "condition_id": "C1", "role": "a", "truth": [False, None],
                                 "observed": [True, False], "decision": False, "evaluation": "source_path",
                                 "possible_ub": ["pointer_arithmetic_untyped"]}])
    assert "조건[F-]" in label and "함수 실행 모델 설계" in label and "pointer_arithmetic_untyped" in label


def test_an_unmodeled_macro_argument_holds_a_maybe_evaluated_decision_in_the_oracle():
    # the oracle's own verdict, below the design's refusal: ``DBG(...)`` may drop its argument
    from generators.mcdc_design import _path_ir
    text = H + 'U8 g_o;\n#define DBG(...)\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U); DBG("%d", (t > 3U) && (b == 1U)); g_o = t; }\n'
    unit = _unit(text, "f", ["a", "b"])
    raw = text.encode()
    root = cpc.shared_parser().parse(raw).root_node
    stack, node = [root], None
    while stack:
        n = stack.pop()
        if n.type == "binary_expression" and raw[n.start_byte:n.end_byte].startswith(b"(t > 3U) &&"):
            node = n
        stack.extend(n.children)
    atoms = []
    ir = _path_ir(node, raw, atoms)
    spec = {"key": [node.start_byte, node.end_byte, node.type], "ir": ir,
            "atoms": [[a.start_byte, a.end_byte, a.type] for a in atoms]}
    (r,) = observe_decisions(unit, [{"a": 5, "b": 1}], [spec])
    assert r["decisions"][0]["state"] == "maybe_evaluated"


# ── R2c deep review round 2 counterexamples ─────────────────────────────────────────────────────

def test_n_c1_a_decision_in_the_argument_of_an_undeclared_callee_after_a_missing_include():
    # ``gone.h`` may define ``ASSERT(x)`` as ``((void)0)``: the decision may not exist after preprocessing
    text = ('#include "common.h"\n#include "gone.h"\nU8 g_o;\n'
            "void f(U8 a, U8 b) { U8 t = (U8)(a + 1U); ASSERT((t > 3U) && (b == 1U)); g_o = t; }\n")
    _u, report = _design(text, "f", ["a", "b"])
    (d,) = report["decisions"]
    assert d["pairs"] == [] and d["status"] != "designed"


def test_n_w1_a_condition_with_its_own_boolean_operators_is_refused_not_designed():
    text = H + ("U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U);"
                " if ((t != 9U) && ((((t > 3U) || (b == 1U))) != 0U)) { g_o = 1U; } }\n")
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    (d,) = report["decisions"]
    assert d["pairs"] == [] and d["reason"] == "path_refused:nested_boolean_in_condition"
    assert d["static_reason"] == "local_variable_not_input:t"


def test_n_w3_a_decision_inside_sizeof_is_never_evaluated():
    text = H + "U8 g_o;\nvoid f(U8 a, U8 b) { g_o = (U8)sizeof((a > 3U) && (b == 1U)); }\n"
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    (d,) = report["decisions"]
    assert d["pairs"] == [] and d["reason"] == "decision_in_unevaluated_operand"


def test_i_b_a_macro_defined_only_in_an_inactive_arm_does_not_host_the_call():
    text = H + ("#define CFG_X 0\n#if CFG_X\n#define Chk(c) (c)\n#endif\nU8 Chk(U8 c);\n"
                "void f(U8 a, U8 b) { (void)Chk((a > 3U) && (b == 1U)); }\n")
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    (d,) = report["decisions"]
    assert not str(d["reason"]).startswith("decision_inside_macro_argument")


def test_i_a_a_volatile_global_is_never_a_search_input():
    text = H + ("volatile U8 g_v; U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + g_v);"
                " if ((t > 3U) && (b == 1U) && (g_v == 0U)) { g_o = 1U; } }\n")
    _u, report = _design(text, "f", ["a", "b"])
    d = report["decisions"][0]
    assert "g_v" not in (d.get("path_search") or {}).get("inputs", [])


# ── R2c deep review round 3 counterexamples ─────────────────────────────────────────────────────

@pytest.mark.parametrize("body, reason", [
    ("g_o = (U8)_Generic((a > 3U) && (b == 1U), int: 1, default: 0);", "decision_in_unevaluated_operand"),
    ("g_o = (U8)__builtin_constant_p((a > 3U) && (b == 1U));", "decision_in_unevaluated_operand:__builtin_constant_p"),
    ("switch (a) { case ((3U > 1U) && (2U > 1U)): g_o = 1U; break; default: break; }",
     "decision_in_constant_expression:case_label"),
    ("static U8 s = ((3U > 1U) && (2U > 1U)) ? 1U : 0U; g_o = (U8)(s + a + b);",
     "decision_in_constant_expression:static_initializer"),
])
def test_round3_decisions_the_run_never_evaluates_are_refused_by_the_expression_engine(body, reason):
    text = H + f"U8 g_o;\nvoid f(U8 a, U8 b) {{ {body} }}\n"
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    assert any(d["reason"] == reason and d["pairs"] == [] for d in report["decisions"]), \
        [(d["expression"], d["reason"]) for d in report["decisions"]]


def test_round3_a_builtin_that_does_not_evaluate_its_argument_hides_a_path_decision():
    text = H + "U8 g_o;\nvoid f(U8 a, U8 b) { U8 t = (U8)(a + 1U); g_o = (U8)__builtin_constant_p((t > 3U) && (b == 1U)); }\n"
    _u, report = _design(text, "f", ["a", "b"], free_globals=False)
    (d,) = report["decisions"]
    assert d["pairs"] == [] and d["status"] != "designed"


def test_round3_a_constant_decision_in_an_undeclared_callee_argument_is_not_proven_infeasible():
    text = ('#include "common.h"\n#include "gone.h"\n#define A_ON 1U\n'
            "void f(U8 a) { ASSERT((A_ON == 1U) && (a == a)); }\n")
    _u, report = _design(text, "f", ["a"], free_globals=False)
    (d,) = report["decisions"]
    assert d["reason"] == "decision_inside_macro_argument:ASSERT"
