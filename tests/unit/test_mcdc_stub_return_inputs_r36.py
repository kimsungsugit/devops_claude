"""R36 — the MC/DC path design searches the stub return inputs a SUTS row sets.

KJPDS02_PV: 67 of 207 ``path_evaluation:undetermined`` decisions read a value a call returned before the decision
(``r = F(); if ((r == 3U) && ...)``). The SUTS row already carries ``F() return`` as an input (R14: VectorCAST stubs the
callee and injects its return value — the source oracle takes it, `stub_return`), but the path search only varied
inputs with a declared domain, so ``r`` stayed unknown on every run. The domain is F's declared return type, under the
oracle's own conditions: a project function with one integer return type, not the function under test.
"""
from __future__ import annotations

import json
import os

from generators import c_project_context as cpc
from generators.mcdc_design import _stub_return_domain, build_mcdc_design, finalize_mcdc_design
from generators.suts import summarize_mcdc_design
from report_gen.generation_disclosures import build_disclosures

ROOT = os.path.join(os.sep, "p36")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef float F32;
#endif
"""
UNIT = """#include "common.h"
U8 g_b;
U8 g_x;
U8 g_en;
U8 g_o;
U8 g_arr[2];
U8 get(void) { return g_x; }
U8 *ptr(void) { return g_arr; }
F32 flt(void) { return 1.0f; }
void f(void) { U8 r = get(); if ((r == 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void two(void) {
    U8 r = get();
    if ((g_en == 1U) && (g_b == 2U)) { g_o = 5U; }
    if ((r == 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; }
}
void mix(void) {
    U8 r = 3U;
    if (g_b == 1U) { r = get(); }
    if ((g_en == 1U) && (r == 3U)) { g_o = 1U; } else { g_o = 2U; }
}
void none(void) { U8 r = get(); if ((r == 3U) && (r == 4U)) { g_o = 1U; } }
U8 st(void) { return 3U; }
void retry(void) {
    U8 k = get();
    if ((k == 1U) && (g_b == 2U)) { g_o = 1U; } else { g_o = 2U; }
    if (g_b == 7U) { while (st() != 3U) { g_x = 0U; } }
}
U8 self(U8 n) { U8 r = 0U; if ((n > 0U) && (g_en == 1U)) { r = self(n - 1U); } if ((r == 2U) && (g_en == 1U)) { return 1U; } return 0U; }
"""


def _unit(name, inputs):
    path = os.path.join(ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): COMMON, path: UNIT})
    scope = cpc.build_scopes(context, [path])[path]
    return {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": list(inputs)}


def test_a_decision_on_a_returned_value_is_designed_with_the_stub_input():
    unit = _unit("f", ["g_en", "get() return"])
    report = build_mcdc_design(unit)
    (decision,) = report["decisions"]
    assert decision["status"] == "designed", (decision["status"], decision.get("reason"))
    assert decision["evaluation"] == "source_path"
    assert report["domains"]["get() return"]["source"] == "stub_return"
    assert (report["domains"]["get() return"]["min"], report["domains"]["get() return"]["max"]) == (0, 255)
    # C1 ``r == 3U`` flips with the stub value alone and changes the outcome (short-circuit unique cause, R2c: C2 is not
    # evaluated on the false side, so its input may differ there)
    by_condition = {p["condition_id"]: p for p in decision["pairs"]}
    c1 = by_condition["C1"]
    assert c1["inputs_a"]["get() return"] != c1["inputs_b"]["get() return"]
    assert c1["truth_a"][0] != c1["truth_b"][0] and c1["decision_a"] != c1["decision_b"]
    assert [i for i in range(2) if c1["observed_a"][i] and c1["observed_b"][i]
            and c1["truth_a"][i] != c1["truth_b"][i]] == [0]
    # the pairs survive the re-run on the emitted rows
    rows = [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]
    finalize_mcdc_design(report, rows, unit)
    assert {p["retained_status"] for p in decision["pairs"]} == {"retained"}


def test_without_the_stub_input_the_decision_stays_undetermined():
    (decision,) = build_mcdc_design(_unit("f", ["g_en"]))["decisions"]
    assert decision["status"] == "unsupported" and decision["reason"].startswith("path_evaluation:undetermined")


def test_only_what_the_oracle_takes_as_a_stub_gets_a_domain():
    scope = _unit("f", [])["project_scope"]
    assert _stub_return_domain("get() return", scope, "f")["ctype"]["bits"] == 8
    assert _stub_return_domain("ptr() return", scope, "f") is None          # a pointer: not a stubbed value
    assert _stub_return_domain("flt() return", scope, "f") is None          # floating: not modeled
    assert _stub_return_domain("nowhere() return", scope, "f") is None      # no definition in the project
    assert _stub_return_domain("self() return", scope, "self") is None      # the function under test runs for real
    assert _stub_return_domain("get() r[0]", scope, "f") is None            # an out-parameter cell, not a return
    assert _stub_return_domain("get() return.a", scope, "f") is None        # the whole name, not a prefix of it


def test_only_the_decisions_that_need_a_stub_value_get_one():
    # D1 reads globals only: designed by the first search, its rows set no stub (they would say "F is a stub" — R36
    # review W3); D2 reads what get() returned: designed by the second search, and says so
    report = build_mcdc_design(_unit("two", ["g_en", "g_b", "get() return"]))
    d1, d2 = report["decisions"]
    assert d1["status"] == "designed" and not d1.get("stub_inputs")
    assert all("get() return" not in p[f"inputs_{s}"] for p in d1["pairs"] for s in ("a", "b"))
    assert d2["status"] == "designed" and d2["stub_inputs"] == ["get() return"]
    assert all("get() return" in p[f"inputs_{s}"] for p in d2["pairs"] for s in ("a", "b"))
    selected = [json.dumps(v, sort_keys=True) for v in report["selected_inputs"]]
    assert len(selected) == len(set(selected))
    for d in (d1, d2):
        for p in d["pairs"]:
            assert json.dumps(p["inputs_a"], sort_keys=True) in selected
            assert json.dumps(p["inputs_b"], sort_keys=True) in selected


def _keys(vectors):
    return [json.dumps(v, sort_keys=True) for v in vectors]


def test_the_first_search_pairs_and_rows_stay_in_place():
    # C1 is paired on the ``g_b != 1`` path (r stays 3) by the first search; C2 needs r != 3, i.e. a stub value. The
    # second search adds C2 only — C1's pair and every first-search row keep their places (the reference profile renders
    # the first MC/DC vectors only: replacing C1's pair lost it there — R36 review round 2 C1)
    without = build_mcdc_design(_unit("mix", ["g_en", "g_b"]))
    report = build_mcdc_design(_unit("mix", ["g_en", "g_b", "get() return"]))
    (first,) = [d for d in without["decisions"] if "g_en" in d["expression"]]
    (merged,) = [d for d in report["decisions"] if "g_en" in d["expression"]]
    assert first["status"] == "partial" and [p["condition_id"] for p in first["pairs"]] == ["C1"]
    assert merged["status"] == "designed" and [p["condition_id"] for p in merged["pairs"]] == ["C1", "C2"]
    assert merged["pairs"][0] == first["pairs"][0] and "stub_inputs" not in merged["pairs"][0]
    assert merged["pairs"][1]["stub_inputs"] == ["get() return"] and merged["stub_inputs"] == ["get() return"]
    assert merged["path_search"] == first["path_search"] and merged["stub_search"]["inputs"][-1] == "get() return"
    assert merged["static_reason"] == first["static_reason"] and merged["static_reason"].startswith("local_variable")
    first_rows = _keys(without["selected_inputs"])
    assert _keys(report["selected_inputs"])[:len(first_rows)] == first_rows


def test_a_decision_the_second_search_cannot_improve_is_left_as_it_was():
    # ``(r == 3U) && (r == 4U)``: no value of r gives a pair — the second search changes nothing, not even the record
    report = build_mcdc_design(_unit("none", ["get() return"]))
    reference = build_mcdc_design(_unit("none", []))
    assert report["decisions"] == reference["decisions"]
    assert report["stub_search"]["decisions_searched"] == 1 and report["stub_search"]["decisions_improved"] == 0
    assert "get() return" not in report["domains"]


def test_a_merge_that_pairs_some_conditions_is_partial(monkeypatch):
    # the second search pairs only C2 (simulated): the decision is partial with C2's stub pair, not "designed"
    from generators import mcdc_design as md
    real = md._path_design

    def second_pairs_c2_only(unit, report, candidates, *args, **kwargs):
        real(unit, report, candidates, *args, **kwargs)
        if kwargs.get("extra_domains"):
            for d, _n, _r in candidates:
                d["pairs"] = [p for p in d.get("pairs") or [] if p["condition_id"] == "C2"]
    monkeypatch.setattr(md, "_path_design", second_pairs_c2_only)
    (decision,) = md.build_mcdc_design(_unit("f", ["g_en", "get() return"]))["decisions"]
    assert decision["status"] == "partial" and decision["reason"] == "path_search_incomplete"
    assert [p["condition_id"] for p in decision["pairs"]] == ["C2"] and decision["stub_inputs"] == ["get() return"]


def test_a_failing_second_search_leaves_the_first_result(monkeypatch):
    # the second search changes the decisions, then fails: every one goes back to the first search's result
    from generators import mcdc_design as md
    real = md._path_design

    def fails_after_running(unit, report, candidates, *args, **kwargs):
        real(unit, report, candidates, *args, **kwargs)
        if kwargs.get("extra_domains"):
            raise RuntimeError("second search")
    monkeypatch.setattr(md, "_path_design", fails_after_running)
    report = md.build_mcdc_design(_unit("f", ["g_en", "get() return"]))
    reference = build_mcdc_design(_unit("f", ["g_en"]))
    assert report["decisions"] == reference["decisions"]
    assert report["stub_search"]["error"] == "RuntimeError" and report["stub_search"]["decisions_improved"] == 0
    unit = _unit("f", ["g_en", "get() return"])
    unit["mcdc_design"] = report
    assert summarize_mcdc_design([unit])["stub_search_errors"] == 1


def test_every_selected_row_belongs_to_a_pair():
    for name, inputs in (("two", ["g_en", "g_b", "get() return"]), ("mix", ["g_en", "g_b", "get() return"])):
        report = build_mcdc_design(_unit(name, inputs))
        paired = {k for d in report["decisions"] for p in d.get("pairs") or []
                  for k in _keys([p["inputs_a"], p["inputs_b"]])}
        assert set(_keys(report["selected_inputs"])) == paired, name


def test_a_retry_loop_on_a_stub_value_keeps_the_search_budget():
    # ``while (st() != 3U)`` never ends for a stub value other than 3 (the first search, where ``st()`` is unknown, never
    # got past it; the second one sets it): each run stops at what the function's step budget has left — it ran to the
    # loop budget, several times over (R36 review W2) — and the decision is still designed on the runs that skip it
    report = build_mcdc_design(_unit("retry", ["g_b", "get() return", "st() return"]), max_path_steps=30_000)
    (decision,) = [d for d in report["decisions"] if "k == 1U" in d["expression"]]
    assert decision["stub_inputs"] == ["get() return", "st() return"]
    assert decision["stub_search"]["steps"] <= 30_000, decision["stub_search"]
    assert decision["status"] == "designed", decision["reason"]


def test_the_summary_and_the_disclosure_count_the_stub_designs():
    unit = _unit("two", ["g_en", "g_b", "get() return"])
    unit["mcdc_design"] = build_mcdc_design(unit)
    summary = summarize_mcdc_design([unit])
    assert (summary["stub_input_decisions"], summary["stub_input_pairs"], summary["stub_input_pairs_retained"]) == (1, 2, 0)
    assert (summary["stub_search_decisions"], summary["stub_search_improved"]) == (1, 1)
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary}) if i["key"] == "suts_mcdc_design"]
    assert "stub 반환값" in item["note"] and "Stub Inputs" in item["note"]
