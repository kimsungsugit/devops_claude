"""R38 — a sequence stub writes no global or static.

A row that sets ``F() return`` stubs F (R14 — the unit-test convention the reference follows: VectorCAST replaces F's
body, and the clang check's stubs do the same). Until R38 the oracle took the return value from the row but still
havocked everything F's body writes — the stub was modeled as the real F with a known return. The body does not run:
what F would write to a global or a static keeps the value the sequence set, nothing F calls runs (no re-entry), and
F's order against the rest of an expression no longer matters. What a stub may put through a pointer argument (the
reference sets ``F() p[0]`` — R23) stays unknown. Without the input, F is the real function as before.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

COMMON = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n"   # widths (R2)
LIB = '''#include "common.h"
U8 g_side;
U8 g_t;
U8 *g_ptr;
void undeclared_hook(void);
U8 cal(void) { g_side = 1U; return 7U; }
U8 fill(U8 *p) { *p = 2U; g_t = 3U; return 0U; }
U8 ext(void) { undeclared_hook(); g_t = 4U; return 1U; }
void undeclared_sink(U8 *p);
U8 ext2(U8 *p) { undeclared_sink(p); return 1U; }
U8 *where(void) { return &g_side; }
U8 nw(U8 *p) { if (p == 0) { return 1U; } return 0U; }
'''
APP = '''#include "common.h"
extern U8 g_side;
extern U8 g_t;
U8 cal(void);
U8 fill(U8 *p);
U8 ext(void);
U8 ext2(U8 *p);
U8 *where(void);
U8 nw(U8 *p);
U8 g_o;
U8 g_s;
void f(void) { g_o = (U8)(cal() + 1U); g_s = g_side; }
void w(void) { U8 v = 0U; (void)fill(&v); g_o = v; g_s = g_t; }
void x(void) { (void)ext(); g_s = g_t; }
void u(void) { g_o = (U8)(cal() + g_side); }
void y(void) { U8 v = 0U; (void)ext2(&v); g_o = v; }
void p2(void) { g_o = (U8)(where() != 0); g_s = g_side; }
void z(void) { U8 v = 0U; (void)nw(&v); g_o = v; }
void wo(void) { U8 v = 0U; (void)fill(&v); g_s = g_t; g_o = v; }
void cp(void) { U8 l = 0U; if ((nw(&l) == 0U) && (l == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void m(void) { (void)cal(); if ((g_side == 1U) && (g_t == 2U)) { g_o = 1U; } else { g_o = 2U; } }
'''


@pytest.fixture(scope="module")
def units(tmp_path_factory):
    from reference_alignment import _load_source

    from generators.c_project_context import build_scopes
    root = tmp_path_factory.mktemp("stub38") / "src"
    root.mkdir()
    for name, text in (("common.h", COMMON), ("lib.c", LIB), ("app.c", APP)):
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    texts, context, _ = _load_source([root])
    app = next(p for p in texts if p.endswith("app.c"))
    scope = build_scopes(context, [app])[app]
    return {fn: {"name": fn, "source_text": texts[app], "source_path": app, "source_text_complete": True,
                 "project_scope": scope} for fn in ("f", "w", "x", "u", "m", "y", "p2", "z", "wo")}


def _run(unit, inputs, outs):
    from generators.c_source_oracle import evaluate_outputs
    (r,) = evaluate_outputs(unit, [inputs], [outs])
    return r


def test_what_the_stubbed_callee_writes_keeps_the_sequence_value(units):
    r = _run(units["f"], {"cal() return": 5, "g_side": 4}, ["g_o", "g_s"])
    assert r["outputs"]["g_o"] == {"value": 6, "basis": "assigned"}
    assert r["outputs"]["g_s"] == {"value": 4, "basis": "assigned"}   # not cal's 1: the stub does not run it
    assert r["schema_version"] == 4   # 3 (R38); 4 (backlog 2-c)
    assert any("a stub writes no global or static" in a for a in r["assumptions"])
    # (review W2) the base line no longer says what a stub may write is unknown
    (base,) = [a for a in r["assumptions"] if a.startswith("callee effects are")]
    assert "a callee the sequence stubs writes no global or static" in base


def test_without_the_stub_the_callee_is_the_real_function(units):
    r = _run(units["f"], {"g_side": 4}, ["g_s"])
    assert "value" not in r["outputs"]["g_s"] and "cal" in r["outputs"]["g_s"]["reason"]
    assert not r.get("stubs")


def test_what_a_stub_may_put_through_a_pointer_argument_stays_unknown(units):
    # fill() writes through its pointer: the stub may put a test-case value in ``v`` (``fill() p[0]``) — unknown. g_t,
    # which no pointer reaches, keeps the sequence's value (fill's own ``g_t = 3U`` does not run)
    r = _run(units["w"], {"fill() return": 0, "g_t": 9}, ["g_o", "g_s"])
    assert "value" not in r["outputs"]["g_o"] and "stub_pointer_argument:fill" in r["outputs"]["g_o"]["reason"]
    assert r["outputs"]["g_s"] == {"value": 9, "basis": "assigned"}


def test_a_stub_calls_nothing_even_when_the_real_callee_calls_unknown_code(units):
    # ext() calls a function no source defines: the real ext would havoc everything; the stub runs none of it
    r = _run(units["x"], {"ext() return": 1, "g_t": 6}, ["g_s"])
    assert r["outputs"]["g_s"] == {"value": 6, "basis": "assigned"}
    real = _run(units["x"], {"g_t": 6}, ["g_s"])
    assert "value" not in real["outputs"]["g_s"]


def test_a_stub_of_a_callee_that_calls_unknown_code_may_still_write_through_its_pointer(units):
    # ext2() hands its pointer to code no source defines — its closure cannot say it writes nothing through it
    r = _run(units["y"], {"ext2() return": 1}, ["g_o"])
    assert "value" not in r["outputs"]["g_o"] and "stub_pointer_argument:ext2" in r["outputs"]["g_o"]["reason"]


def test_an_out_parameter_the_sequence_sets_is_written_by_the_stub(units):
    # (review W1) nw()'s body never writes through p, but the row sets ``nw() p[0]``: VectorCAST's stub writes the test
    # case's value there — the pointee is unknown to the oracle (it used to stay 0)
    r = _run(units["z"], {"nw() return": 0, "nw() p[0]": 5}, ["g_o"])
    assert "value" not in r["outputs"]["g_o"] and "stub_pointer_argument:nw" in r["outputs"]["g_o"]["reason"]
    # without the out-parameter input the stub puts nothing there
    assert _run(units["z"], {"nw() return": 0}, ["g_o"])["outputs"]["g_o"] == {"value": 0, "basis": "assigned"}


def test_an_out_parameter_input_alone_makes_the_callee_a_stub(units):
    # the row sets ``fill() p[0]`` but not its return: fill is a stub all the same — its ``g_t = 3U`` does not run
    r = _run(units["wo"], {"fill() p[0]": 5, "g_t": 9}, ["g_s", "g_o"])
    assert r["outputs"]["g_s"] == {"value": 9, "basis": "assigned"} and r["stubs"] == ["fill"]
    assert "value" not in r["outputs"]["g_o"]
    # (review round 2 Info 2) the record does not claim a return value the sequence never set
    assert any("fill() is a stub (the sequence sets its out-parameters" in a for a in r["assumptions"])
    assert not any("fill() returns the value set" in a for a in r["assumptions"])


def test_a_stub_whose_value_cannot_be_used_is_still_a_stub(units):
    # where() returns a pointer: no number stubs it, but the run still rests on where() being a stub
    r = _run(units["p2"], {"where() return": 1, "g_side": 4}, ["g_o", "g_s"])
    assert r["outputs"]["g_o"]["reason"].startswith("stub_return_type_unresolved:where")
    assert r["outputs"]["g_s"] == {"value": 4, "basis": "assigned"} and r["stubs"] == ["where"]


def test_a_stubbed_call_is_not_unsequenced_with_what_its_body_writes(units):
    # ``cal() + g_side``: the real cal writes g_side, unsequenced with the read — refused. The stub writes nothing
    r = _run(units["u"], {"cal() return": 5, "g_side": 4}, ["g_o"])
    assert r["outputs"]["g_o"] == {"value": 9, "basis": "assigned"}
    real = _run(units["u"], {"g_side": 4}, ["g_o"])
    assert "value" not in real["outputs"]["g_o"]


def test_a_decision_after_a_stubbed_call_is_designed_with_the_stub():
    # ``(void)cal(); if ((g_side == 1U) && (g_t == 2U))``: without a stub cal's write leaves g_side unknown; the stub
    # search (R36) sets ``cal() return`` and the decision reads the sequence's g_side
    from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design
    unit = _app_unit("m", ["g_side", "g_t", "cal() return"])
    report = build_mcdc_design(unit)
    (decision,) = report["decisions"]
    assert decision["status"] == "designed" and decision["stub_inputs"] == ["cal() return"], decision["reason"]
    rows = [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]
    finalize_mcdc_design(report, rows, unit)
    assert {p["retained_status"] for p in decision["pairs"]} == {"retained"}


def _app_unit(name, inputs):
    import os

    from generators import c_project_context as cpc
    root = os.path.join(os.sep, "p38")
    files = {os.path.join(root, "common.h"): COMMON, os.path.join(root, "lib.c"): LIB,
             os.path.join(root, "app.c"): APP}
    path = os.path.join(root, "app.c")
    context = cpc.build_project_context(files)
    return {"name": name, "source_text": APP, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(inputs)}


def test_the_decision_probe_sees_the_out_parameters_a_vector_sets():
    # (review round 2 W3) ``(nw(&l) == 0U) && (l == 1U)``: nw's body never writes through p, so with only ``nw()
    # return`` the stubbed call is inert and the condition copy is exact. A vector that also sets ``nw() p[0]`` has
    # the stub write l — the probe must not call the condition inert for it (it read only the return keys)
    from generators import c_source_oracle as cso
    from generators.mcdc_design import build_mcdc_design
    unit = _app_unit("cp", ["nw() return"])
    (decision,) = build_mcdc_design(unit)["decisions"]
    spec = decision["path_spec"]
    (plain,) = cso.observe_decisions(unit, [{"nw() return": 0}], [spec], inert_stub_calls=True)
    assert plain["decisions"][0]["state"] == "evaluated"
    (out,) = cso.observe_decisions(unit, [{"nw() return": 0, "nw() p[0]": 1}], [spec], inert_stub_calls=True)
    assert out["decisions"][0]["state"] == "effectful_condition", out


def test_clang_agrees_the_stub_writes_nothing(units):
    """The clang harness's stubs write nothing either: the new claims are checked, and a claim that the body ran is
    a mismatch."""
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")
    from source_oracle_clang_check import check_claims
    claims = [{"unit": units["f"], "inputs": {"cal() return": 5, "g_side": 4}, "outputs": {"g_o": 6, "g_s": 4}},
              {"unit": units["w"], "inputs": {"fill() return": 0, "g_t": 9}, "outputs": {"g_s": 9}},
              {"unit": units["u"], "inputs": {"cal() return": 5, "g_side": 4}, "outputs": {"g_o": 9}}]
    report = check_claims(claims)
    assert (report["mismatch"], report["eval_error"]) == (0, 0) and report["checked"] == 4
    wrong = check_claims([{"unit": units["f"], "inputs": {"cal() return": 5, "g_side": 4}, "outputs": {"g_s": 1}}])
    assert wrong["mismatch"] == 1
    # (review W1) the harness's stub writes through its pointers when the claim sets an out-parameter: a claim that
    # the pointee kept its value is not confirmed
    out = check_claims([{"unit": units["z"], "inputs": {"nw() return": 0, "nw() p[0]": 5}, "outputs": {"g_o": 0}}])
    assert out["agree"] == 0
    # (review round 2 Info 1) and when the claim sets the out-parameter alone
    alone = check_claims([{"unit": units["z"], "inputs": {"nw() p[0]": 5}, "outputs": {"g_o": 0}}])
    assert alone["agree"] == 0


def test_the_disclosure_says_what_a_stub_does():
    from report_gen.generation_disclosures import build_disclosures
    ev = {"derived": 3, "derived_assigned": 3, "derived_unchanged_input": 0, "unknown": 0, "proposed": 0,
          "unrecorded": 0, "total": 3, "derived_in_stubbed_sequence": 2}
    note = {i["key"]: i for i in build_disclosures("suts", {"expected_evidence_summary": ev})}["suts_expected_evidence"]
    assert "전역·정적 변수를 쓰지 않는다" in note["note"] and "포인터 인자로 써 넣는 값은 미상" in note["note"]
