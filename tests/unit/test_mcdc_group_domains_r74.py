"""R74 — each modeled-run search group starts from the same input domains: a stub value one group's second search used
does not become a plain input of the next group's first search.

`build_mcdc_design` searches the decisions the expression engine refused in groups (R37 call in a condition · R39
struct member · R40 pointee — each with its own budget, so the others' rows stay what they were). Each group's stub
search (R36) recorded the stub return values its pairs used in the report's domains — the very dict the next group's
first search read its inputs from. A later group then searched ``get() return`` from the start: its pairs held only where
``get()`` runs as a stub, but recorded no ``stub_inputs`` (the 'MCDC Design' sheet's Stub Inputs cell · the summary's
stub-input decisions · the clang harness's stub flag), and its design depended on whether an earlier group's decision
happened to need that stub. Latent in the measured documents: HDPDM01 · KJPDS02_PV reference-profile SUTS kept every
cell of every sheet (R73 against R74).
"""
from __future__ import annotations

import os
import re

from generators import c_project_context as cpc
from generators.mcdc_design import build_mcdc_design
from generators.suts import summarize_mcdc_design

ROOT = os.path.join(os.sep, "p74")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#endif
"""
UNIT = """#include "common.h"
typedef struct { U8 a; U8 b; } S;
U8 g_x;
U8 g_en;
U8 g_b;
U8 g_o;
U8 g_t;
S g_s;
U8 get(void) { return g_x; }
void leak(void) {
    U8 r = get();
    if ((r == 3U) && (g_en == 1U)) { g_o = 1U; }
    if ((get() == 3U) && (g_b == 1U)) { g_o = 2U; }
}
void leak_member(void) {
    U8 r = get();
    if ((r == 3U) && (g_en == 1U)) { g_o = 1U; }
    U8 q = get();
    if ((g_s.a == 1U) && (q == 3U)) { g_o = 2U; }
}
void leak_pointee(S *pq) {
    U8 r = get();
    if ((r == 3U) && (g_en == 1U)) { g_o = 1U; }
    U8 q = get();
    if ((pq->a > 3U) && (q == 3U)) { g_o = 3U; }
}
void through_local(void) { U8 t = g_t; if ((t == 1U) && (g_en == 1U)) { g_o = 1U; } }
"""
_STUB = re.compile(r"[A-Za-z_]\w*\(\) return")


def _unit(name, inputs):
    path = os.path.join(ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): COMMON, path: UNIT})
    scope = cpc.build_scopes(context, [path])[path]
    return {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": list(inputs)}


def _stub_marks_hold(report):
    """Every pair whose rows set a stub return value names it in ``stub_inputs`` (pair and decision)."""
    for d in report["decisions"]:
        for p in d.get("pairs") or []:
            used = sorted({k for k in {**p["inputs_a"], **p["inputs_b"]} if _STUB.fullmatch(k)})
            assert (p.get("stub_inputs") or []) == used, (d["decision_id"], p["pair_id"], used)
            assert set(used) <= set(d.get("stub_inputs") or []), (d["decision_id"], used)


def test_a_later_group_records_the_stub_its_pairs_set():
    report = build_mcdc_design(_unit("leak", ["g_en", "g_b", "get() return"]))
    d1, d2 = report["decisions"]
    assert d1.get("search_group", "") == "" and d1["stub_inputs"] == ["get() return"], d1["reason"]
    assert d2["search_group"] == "call_in_condition"
    assert d2["status"] == "designed" and d2["stub_inputs"] == ["get() return"], (d2["reason"], d2.get("stub_inputs"))
    # the group's first search reads the declared inputs only — the stub value is the second search's
    assert "get() return" not in d2["path_search"]["inputs"]
    _stub_marks_hold(report)


def test_a_group_designs_the_same_whether_or_not_an_earlier_group_needed_the_stub():
    unit = _unit("leak", ["g_en", "g_b", "get() return"])
    both = build_mcdc_design(unit)
    d2 = both["decisions"][1]
    alone = build_mcdc_design(unit, only_occurrences={d2["occurrence_id"]})["decisions"][1]
    for key in ("status", "reason", "pairs", "stub_inputs", "path_search", "stub_search"):
        assert d2.get(key) == alone.get(key), key


def test_the_struct_member_group_too():
    report = build_mcdc_design(_unit("leak_member", ["g_en", "g_s.a", "get() return"]))
    d1, d2 = report["decisions"]
    assert d1["stub_inputs"] == ["get() return"], d1["reason"]
    assert d2.get("search_group") == "struct_member", d2["reason"]
    assert d2["status"] == "designed" and d2["stub_inputs"] == ["get() return"], (d2["reason"], d2.get("stub_inputs"))
    assert "get() return" not in d2["path_search"]["inputs"]
    _stub_marks_hold(report)


def test_the_pointee_group_too():
    # (review W1) the pointee group, last of the narrow groups, took the earlier group's stub value as well
    report = build_mcdc_design(_unit("leak_pointee", ["pq[0].a", "g_en", "get() return"]))
    d1, d2 = report["decisions"]
    assert d1["stub_inputs"] == ["get() return"], d1["reason"]
    assert d2.get("search_group") == "pointee", d2["reason"]
    assert d2["status"] == "designed" and d2["stub_inputs"] == ["get() return"], (d2["reason"], d2.get("stub_inputs"))
    assert "get() return" not in d2["path_search"]["inputs"]
    _stub_marks_hold(report)


def test_the_report_still_collects_what_a_group_searched():
    # (review W2) g_t reaches the search only through the local t: the group's first search adds its domain (to its own
    # copy now) and the report must keep it — the design range's conflict with U8 is summarised from the report
    unit = _unit("through_local", ["g_t", "g_en"])
    unit["uds_param_info"] = {"g_t": {"range": [0, 1000]}}
    report = build_mcdc_design(unit)
    assert report["decisions"][0]["path_search"]["inputs"] == ["g_t", "g_en"]
    assert report["domains"]["g_t"]["design_range_conflict"] == {"min": 0, "max": 1000, "source": "uds_range"}
    unit["mcdc_design"] = report
    assert summarize_mcdc_design([unit])["design_range_conflicts"] == ["through_local.g_t"]
