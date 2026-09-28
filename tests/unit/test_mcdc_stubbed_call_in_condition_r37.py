"""R37 — a call inside a condition, where the SUTS row stubs the callee.

``if ((get() == 3U) && (g_en == 1U))``: the expression engine refuses a call operand (``unsupported_scalar:call_expression``
— KJPDS02_PV 62 decisions) and the path search refused every condition holding a call (``effectful_condition``: a call
in one condition could change what a later one reads). Where the row stubs the callee (``get() return`` — R14/R36), the
call's value is the row's and (R38) a stub writes no global or static — the condition may be observed like any other,
unless the stub may put something through a pointer argument. The stub-value search (R36) then pairs it.
"""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design

ROOT = os.path.join(os.sep, "p37")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#endif
"""
UNIT = """#include "common.h"
U8 g_x;
U8 g_en;
U8 g_o;
U8 g_buf[2];
U8 get(void) { return g_x; }
U8 getw(void) { g_en = 0U; return g_x; }
U8 getp(U8 *p) { *p = 1U; return g_x; }
U8 *g_ptr;
U8 getq(void) { *g_ptr = 1U; return g_x; }
#define EN (g_en)
U8 g_a;
U8 g_c;
U8 g_d;
U8 g_e;
U8 g_in;
void rec(void);
U8 getr(void) { rec(); return g_x; }
void starve(void) {
    U8 l = g_a;
    if ((getq() == 3U) && (g_en == 1U)) { g_o = 1U; }
    if (g_d == 5U) { if (g_e == 6U) { if ((l == 7U) && (g_c == 9U)) { g_o = 2U; } else { g_o = 3U; } } }
}
void shadow(U8 (*get)(void)) { if ((get() == 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void rec(void) { static U8 s; s = g_in; if ((getr() == 3U) && (s == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void before(void) { if ((g_en == 1U) && (getw() == 3U)) { g_o = 1U; } else { g_o = 2U; } }
void call(void) { if ((get() == 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void writes(void) { if ((getw() == 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void macro_read(void) { if ((getw() == 3U) && (EN == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void pointer(void) { if ((getp(&g_buf[0]) == 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
"""


def _unit(name, inputs):
    path = os.path.join(ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): COMMON, path: UNIT})
    scope = cpc.build_scopes(context, [path])[path]
    return {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": list(inputs)}


def test_a_stubbed_call_in_a_condition_is_designed():
    unit = _unit("call", ["g_en", "get() return"])
    report = build_mcdc_design(unit)
    (decision,) = report["decisions"]
    assert decision["status"] == "designed", (decision["reason"], decision.get("stub_search"))
    assert decision["static_reason"] == "unsupported_scalar:call_expression"
    assert decision["path_search"]["observations"] == {"effectful_condition": decision["path_search"]["runs"]}
    assert decision["stub_inputs"] == ["get() return"]
    c1 = next(p for p in decision["pairs"] if p["condition_id"] == "C1")
    assert c1["inputs_a"]["get() return"] != c1["inputs_b"]["get() return"]
    rows = [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]
    finalize_mcdc_design(report, rows, unit)
    assert {p["retained_status"] for p in decision["pairs"]} == {"retained"}


def test_the_call_condition_search_is_counted_and_disclosed():
    from generators.suts import summarize_mcdc_design
    from report_gen.generation_disclosures import build_disclosures
    unit = _unit("call", ["g_en", "get() return"])
    unit["mcdc_design"] = build_mcdc_design(unit)
    summary = summarize_mcdc_design([unit])
    assert (summary["call_condition_decisions"], summary["call_condition_designed"]) == (1, 1)
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary}) if i["key"] == "suts_mcdc_design"]
    assert "조건 안에 호출이 있는 결정 1" in item["note"] and "별도 예산" in item["note"]


def test_a_stub_writes_nothing_the_decision_reads():
    # (R38) getw()'s body writes g_en, which the other condition reads — directly or through the macro EN. As a stub
    # its body does not run: the condition is observed, and (the macro beside a stubbed call reads the same whichever
    # order runs) so is the macro's
    for name in ("writes", "macro_read"):
        (decision,) = build_mcdc_design(_unit(name, ["g_en", "getw() return"]))["decisions"]
        assert decision["status"] == "designed" and decision["stub_inputs"] == ["getw() return"],             (name, decision["reason"])


def test_an_unobservable_decision_does_not_starve_the_ones_after_it():
    # (review C1) the getq() decision stays effectful (the stub may write through a pointer) on every vector: it was
    # searched "around" as if reached and took the function's whole budget — the guarded ``(l == 7U) && (g_c == 9U)``
    # after it lost its pairs
    inputs = ["g_a", "g_c", "g_d", "g_e", "g_en", "getq() return"]
    decisions = build_mcdc_design(_unit("starve", inputs))["decisions"]
    first = decisions[0]
    (second,) = [d for d in decisions if "l == 7U" in d["expression"]]
    assert first["reason"] == "path_evaluation:effectful_condition"
    assert second["status"] == "designed", (second["reason"], second.get("path_search"))


def test_a_parameter_that_hides_the_callee_is_no_stub():
    # (review W1) ``get`` here is the function-pointer parameter: the row's ``get() return`` controls nothing
    (decision,) = build_mcdc_design(_unit("shadow", ["g_en", "get() return"]))["decisions"]
    assert decision["status"] != "designed" and not decision.get("stub_inputs"), decision["reason"]


def test_a_stub_does_not_reenter_the_function():
    # (review W2, R38) getr()'s body calls rec() — as a stub it runs nothing: rec's statics keep their value
    (decision,) = build_mcdc_design(_unit("rec", ["g_in", "getr() return"]))["decisions"]
    assert decision["status"] == "designed" and decision["stub_inputs"] == ["getr() return"], decision["reason"]


def test_a_condition_before_the_call_reads_the_state_the_decision_starts_from():
    # (review I1) C1 ``g_en == 1U`` is evaluated before getw() writes g_en — both readings agree; designed
    (decision,) = build_mcdc_design(_unit("before", ["g_en", "getw() return"]))["decisions"]
    assert decision["status"] == "designed" and decision["stub_inputs"] == ["getw() return"], decision["reason"]


def test_a_call_that_writes_through_a_pointer_or_is_not_stubbed_stays_refused():
    # a stub may put a test-case value through a pointer argument (``getp() p[0]`` — R23): not observed
    (decision,) = build_mcdc_design(_unit("pointer", ["g_en", "getp() return"]))["decisions"]
    assert decision["reason"] == "path_evaluation:effectful_condition"
    (decision,) = build_mcdc_design(_unit("call", ["g_en"]))["decisions"]      # the row does not stub get()
    assert decision["reason"] == "path_evaluation:effectful_condition"


# (review round 2) the decisions after a newly searched call decision keep what they had before R37
LATER = """#include "common.h"
U8 g_k; U8 g_a; U8 g_b; U8 g_c; U8 g_d; U8 g_e; U8 g_f; U8 g_en; U8 g_o; U8 g_p0; U8 *g_ptr;
U8 get(void) { return g_b; }
U8 getq(void) { *g_ptr = 1U; return g_b; }
U8 getw(void) { g_en = 0U; return g_b; }
U8 get2(void) { return g_a; }
void base_unsupported(void) {
    U8 l = g_a;
    g_o = (U8)(100U / g_k);
    if ((KIND() == 3U) && (g_en == 1U)) { g_o = 1U; }
    if (g_d == 5U) { if (g_e == 6U) { if ((l == 7U) && (g_c == 9U)) { g_o = 2U; } else { g_o = 3U; } } }
}
void many_constants(void) {
    U8 l = g_a;
    if ((KIND() == 21U) && (g_en == 31U) && (g_f == 41U) && (g_b == 51U)) { g_o = 1U; }
    if (g_d == 5U) { if (g_e == 6U) { if ((l == 7U) && (g_c == 9U)) { g_o = 2U; } else { g_o = 3U; } } }
}
void budget(void) {
    U8 l = get2();
    if ((get() == 21U) && (g_en == 31U)) { g_o = 1U; }
    if (g_d == 5U) { if ((l == 7U) && (g_c == 9U)) { g_o = 2U; } else { g_o = 3U; } }
}
void late_pair(void) {
    if ((getq() == 3U) && (g_en == 1U)) { g_o = 1U; }
    if (g_d == 5U) { if ((get() == 7U) && (g_c == 9U)) { g_o = 2U; } else { g_o = 3U; } }
}
void second_search(void) {
    U8 l = get2();
    if ((get() == 21U) && (g_en == 31U) && (g_a == 41U) && (g_b == 51U)) { g_o = 1U; }
    if (g_d == 5U) { if ((l == 7U) && (g_c == 9U)) { g_o = 2U; } else { g_o = 3U; } }
}
"""


def _later_decisions(name, kind, inputs):
    text = LATER.replace("KIND", kind)
    path = os.path.join(ROOT, "later.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): COMMON, path: text})
    unit = {"name": name, "source_text": text, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(inputs)}
    return build_mcdc_design(unit)["decisions"]


def _later(name, kind, inputs):
    (decision,) = [d for d in _later_decisions(name, kind, inputs) if "l == 7U" in d["expression"]]
    return decision


def test_a_base_vector_the_run_cannot_complete_still_skips_the_unobservable_decision():
    # (R2-C1) g_k = 0 at the base vector: the whole run is unsupported (division by zero) — the skip must read the
    # decision's own state from the record, or the call decision burns the budget the guards after it need. Before R37
    # (the call decision was not searched) ``g_d == 5U`` and ``g_e == 6U`` were designed; they still are
    for kind in ("getq", "getw", "get"):
        decisions = _later_decisions("base_unsupported", kind,
                                     ["g_k", "g_a", "g_c", "g_d", "g_e", "g_en", kind + "() return"])
        guards = [d for d in decisions if d["expression"] in ("g_d == 5U", "g_e == 6U")]
        assert [d["status"] for d in guards] == ["designed", "designed"], (kind, [d["reason"] for d in guards])


def test_the_decisions_of_r36_keep_their_own_budget():
    # (review R3-C1) an observable call decision observed on every run of the others' search cost steps: the R36
    # stub design of ``(l == 7U) && (g_c == 9U)`` ran out of budget. Searched apart, both are designed
    decisions = _later_decisions("budget", "get", ["g_p0", "g_c", "g_d", "g_en", "get() return", "get2() return"])
    first, last = decisions[0], decisions[-1]
    assert last["status"] == "designed" and "get2() return" in last["stub_inputs"], last["reason"]
    assert first["status"] in {"designed", "partial", "no_pair_found", "unsupported"}   # its own search, own budget


def test_an_unobservable_call_decision_leaves_the_budget_to_the_next_one():
    # two call decisions searched together: the getq() stub may write through a pointer — effectful on every vector;
    # searching "around" it (it counts as reached) would take the budget the get() decision under the guard needs
    decisions = _later_decisions("late_pair", "get", ["g_c", "g_d", "g_en", "getq() return", "get() return"])
    first, last = decisions[0], decisions[-1]
    assert first["reason"] == "path_evaluation:effectful_condition", first["reason"]
    assert last["status"] == "designed" and last["stub_inputs"], (last["reason"], last.get("stub_search"))


def test_a_newly_searched_decision_does_not_crowd_the_samples():
    # (R2-C2) the call decision's four constants came first and pushed 5, 6, 7 and 9 out of the 12 samples
    for kind in ("getq", "getw", "get"):
        d = _later("many_constants", kind, ["g_a", "g_b", "g_c", "g_d", "g_e", "g_f", "g_en", kind + "() return"])
        assert d["status"] == "designed", (kind, d["reason"])


def test_the_second_search_serves_the_earlier_decisions_first():
    # (R2-W1) the stub-value design of ``(l == 7U) && (g_c == 9U)`` (R36) keeps its budget and samples when the
    # observable-but-unpairable call decision joins the second search
    d = _later("second_search", "get", ["g_c", "g_d", "g_en", "get() return", "get2() return"])
    assert d["status"] == "designed" and "get2() return" in d["stub_inputs"], d["reason"]


# (review round 4 C1) a decision of R36's group (it reads a local) with a stubbed call in a condition
R36_GROUP_COMMON = ("#ifndef COMMON_H\n#define COMMON_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\n"
                    "typedef enum { E0 = 0, E1 = 1, E2 = 2 } E3;\n#endif\n")
R36_GROUP = """#include "common.h"
E3 g_a; E3 g_c; E3 g_d; E3 g_e; U8 g_o;
E3 get(void) { return E1; }
E3 get2(void) { return E2; }
void two(void) {
    U8 l = (U8)g_a;
    U8 m = (U8)get2();
    if ((l == 1U) && (get() == E1)) { g_o = 1U; }
    if ((g_d == E2) && (g_e == E2)) { if ((m == 2U) && (g_c == E2)) { g_o = 2U; } else { g_o = 3U; } }
}
"""


def test_the_decisions_of_r36_see_the_oracle_judge_as_in_r36():
    # D1 ``(l == 1U) && (get() == E1)`` reaches the path search by its local (R36's group): the stubbed-call judgment is
    # the call group's only — D1 stays effectful and D3's R36 stub design (found around it) is kept
    path = os.path.join(ROOT, "r36group.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): R36_GROUP_COMMON, path: R36_GROUP})
    unit = {"name": "two", "source_text": R36_GROUP, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path],
            "input_vars": ["g_a", "g_c", "g_d", "g_e", "get() return", "get2() return"]}
    decisions = build_mcdc_design(unit)["decisions"]
    first, last = decisions[0], decisions[-1]
    assert first["reason"] == "path_evaluation:effectful_condition", first["reason"]
    assert last["status"] == "designed" and "get2() return" in last["stub_inputs"], last["reason"]
