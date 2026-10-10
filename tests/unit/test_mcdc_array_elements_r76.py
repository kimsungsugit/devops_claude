"""R76 — a condition on an array element is searched on the modeled run, with the global array's elements as inputs.

``(g_part[POS0] == PART0) && (g_part[POS2] == PART2)``: the expression engine refuses a subscript
(``unsupported_scalar:subscript_expression``) and no modeled-run group took it — HDPDM01 9 and KJPDS02_PV 23 decisions
had no MC/DC row, among them the device type check whose inner branches no generated row reached (the rows set every
element of ``u8g_SysEepromCtrl_PartNoInfo`` to one value): 40 of the 207 mutants only the reference suite killed in HDPDM01
sat in those functions. Now such a decision has its own search group (like R39's members), whose runs set a global
array's elements as inputs of their own name (``g_part[2]`` — the reference's notation, the SUTS row's columns); a const
table's element is its value and an index the run's value.
"""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import c_source_oracle as cso
from generators import mcdc_design as md
from generators.mcdc_design import build_mcdc_design
from generators.suts import summarize_mcdc_design
from report_gen.generation_disclosures import build_disclosures

ROOT = os.path.join(os.sep, "p76")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#endif
"""
UNIT = """#include "common.h"
#define POS0 (0U)
#define POS2 (2U)
#define PART0 (0x34U)
#define PART2 (0x41U)
#define LAST (2U)
typedef struct { U8 a; } S2;
typedef float F32;
U8 g_part[4];
U8 g_his[3];
U8 g_state;
U8 g_o;
U8 g_l;
U16 g_w;
S2 *g_sp;
U8 g_big[13];
F32 g_f[2];
extern U8 g_ext[];
U8 *g_ptr;
volatile U8 g_vol[2];
static const U8 c_lut[3] = { 10U, 20U, 30U };
static const U16 c_wide[3] = { 10U, 20U, 30U };
void dev(void) {
    if ((g_part[POS0] == PART0) && (g_part[POS2] == PART2)) {
        if (g_part[1] == 0x46U) { g_o = 1U; } else { g_o = 2U; }
    } else {
        g_o = 3U;
    }
}
void his(void) { if ((g_his[0] == 4U) && (g_state == 2U)) { g_o = 1U; } else { g_o = 2U; } }
void lut(U8 x) { if ((x <= c_lut[0]) || (x >= c_lut[2])) { g_o = 1U; } else { g_o = 2U; } }
void idx(U8 i) { if ((i < 3U) && (g_his[i] == 7U)) { g_o = 1U; } else { g_o = 2U; } }
void vol(void) { if ((g_vol[0] == 1U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void param(U8 *p) { if ((p[2] == 1U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void member(void) { if ((g_part[1] == 2U) && (g_sp->a == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void mixed(void) {
    U8 t = g_l;
    if ((t == 3U) && (g_state == 1U)) { g_o = 4U; }
    if ((g_his[1] == 5U) && (g_state == 2U)) { g_o = 5U; }
}
void wide_l(void) { U16 t = g_w; if ((t > c_wide[1]) && (t != 100U) && (t != 200U) && (t != 300U)) { g_o = 1U; } }
void shadow(U8 *g_part) { if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void arrp(U8 a[4]) { if ((a[2] == 1U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void ext(void) { if ((g_ext[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void ptr(void) { if ((g_ptr[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void paren(void) { if (((g_part)[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void ranged(void) { if ((g_part[1] == 200U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void lptr(void) { U8 *q = g_part; if ((q[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void lut_eq(U8 x) { if (x == c_lut[LAST]) { g_o = 1U; } else { g_o = 2U; } }
void bigl(void) {
    U8 t1 = g_big[1]; U8 t2 = g_big[2]; U8 t3 = g_big[3]; U8 t4 = g_big[4]; U8 t5 = g_big[5]; U8 t6 = g_big[6]; U8 t7 = g_big[7]; U8 t8 = g_big[8]; U8 t9 = g_big[9]; U8 t10 = g_big[10]; U8 t11 = g_big[11]; U8 t12 = g_big[12];
    if ((g_big[0] == 1U) && (t1 == 2U) && (t2 == 1U) && (t3 == 2U) && (t4 == 1U) && (t5 == 2U) && (t6 == 1U) && (t7 == 2U) && (t8 == 1U) && (t9 == 2U) && (t10 == 1U) && (t11 == 2U) && (t12 == 1U)) { g_o = 1U; } else { g_o = 2U; }
}
}
void loc(U8 x) { U8 t[2]; t[0] = x; t[1] = 5U; if ((t[0] == 3U) && (t[1] == 5U)) { g_o = 1U; } else { g_o = 2U; } }
void wonly(void) { g_part[3] = 0U; if ((g_part[01] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void big(void) {
    if ((g_big[0] == 1U) && (g_big[1] == 2U) && (g_big[2] == 1U) && (g_big[3] == 2U) && (g_big[4] == 1U) && (g_big[5] == 2U) && (g_big[6] == 1U) && (g_big[7] == 2U) && (g_big[8] == 1U) && (g_big[9] == 2U) && (g_big[10] == 1U) && (g_big[11] == 2U) && (g_big[12] == 1U)) { g_o = 1U; } else { g_o = 2U; }
}
}
"""
PART = [f"g_part[{k}]" for k in range(4)]
HIS = [f"g_his[{k}]" for k in range(3)]


def _unit(name, inputs, free_globals=False):
    path = os.path.join(ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(ROOT, "common.h"): COMMON, path: UNIT})
    scope = cpc.build_scopes(context, [path])[path]
    unit = {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": list(inputs)}
    if free_globals:
        del unit["input_vars"]
        unit["mcdc_free_globals"] = True
    return unit


def _assert_pairs_hold(unit, decision):
    """Each pair member re-observed on the modeled run with the claimed truths · evaluations · outcome."""
    for pair in decision["pairs"]:
        runs = cso.observe_decisions(unit, [pair["inputs_a"], pair["inputs_b"]], [decision["path_spec"]])
        for side, run in zip("ab", runs, strict=True):
            claimed = {"truth": pair[f"truth_{side}"], "observed": pair[f"observed_{side}"],
                       "decision": pair[f"decision_{side}"]}
            assert run["status"] == "supported" and claimed in run["decisions"][0]["instances"], (pair["pair_id"], side)


def test_constant_index_elements_are_searched_and_reach_the_inner_branch():
    unit = _unit("dev", PART)
    d1, d2 = build_mcdc_design(unit)["decisions"]
    for d in (d1, d2):
        assert d["search_group"] == "array_element" and d["static_reason"] == md._SUBSCRIPT_REASON, d["reason"]
        assert d["status"] == "designed", (d["decision_id"], d["reason"], d.get("path_search"))
        _assert_pairs_hold(unit, d)
    c1 = next(p for p in d1["pairs"] if p["condition_id"] == "C1")
    assert {c1["inputs_a"]["g_part[0]"], c1["inputs_b"]["g_part[0]"]} >= {0x34}
    # the inner decision is reached only where both checked elements match: its rows set them so
    for p in d2["pairs"]:
        for side in "ab":
            assert (p[f"inputs_{side}"]["g_part[0]"], p[f"inputs_{side}"]["g_part[2]"]) == (0x34, 0x41)


def test_a_history_element_a_const_table_and_a_run_index():
    for name, inputs in (("his", [*HIS, "g_state"]), ("lut", ["x"]), ("idx", ["i", *HIS])):
        unit = _unit(name, inputs)
        (d,) = build_mcdc_design(unit)["decisions"]
        assert d["search_group"] == "array_element" and d["status"] == "designed", (name, d["reason"])
        _assert_pairs_hold(unit, d)
    # the const table is the program's: its elements are no search input
    (d,) = build_mcdc_design(_unit("lut", ["x"]))["decisions"]
    assert d["path_search"]["inputs"] == ["x"]
    # (review R2 I-R2-3) at a macro index too: ``x == c_lut[LAST]`` holds only at 30 — sampled from the table
    (d,) = build_mcdc_design(_unit("lut_eq", ["x"]))["decisions"]
    assert d["status"] == "designed" and {p["inputs_a"]["x"] for p in d["pairs"]} | {p["inputs_b"]["x"] for p in d["pairs"]} \
        >= {30}, d["reason"]


def test_a_local_array_is_the_runs():
    # the run writes the local's elements: ``t[0]`` follows x, ``t[1]`` is 5 on every run (C2 never false — no pair)
    unit = _unit("loc", ["x"])
    (d,) = build_mcdc_design(unit)["decisions"]
    assert d["search_group"] == "array_element" and d["path_search"]["inputs"] == ["x"], d["reason"]
    assert {p["condition_id"] for p in d["pairs"]} == {"C1"}
    _assert_pairs_hold(unit, d)


def test_a_condition_reaches_the_inputs_of_the_elements_it_reads():
    # (review I6) the wide climb moves the element a condition reads: a constant index its input, any other index every
    #   element of the array; without the element group's reader the array's name is no input at all
    from generators.c_project_context import shared_parser
    raw = b"void f(U8 x) { if ((g_a[POS] == 1U) && (g_a[x] == 2U)) { } }"
    tree = shared_parser().parse(raw)
    atoms = [n for n in md._walk(tree.root_node) if n.type == "binary_expression" and b"==" in raw[n.start_byte:n.end_byte]
             and b"&&" not in raw[n.start_byte:n.end_byte]]
    inputs = {"g_a[0]", "g_a[1]", "g_a[2]", "x", "g_ab[0]"}     # g_ab: another array whose name starts alike
    index_of = lambda n: 2 if md._text(n, raw) == "POS" else None      # noqa: E731
    assert md._condition_inputs(atoms[0], raw, {}, inputs, index_of) == ["g_a[2]"]
    assert sorted(md._condition_inputs(atoms[1], raw, {}, inputs, index_of)) == ["g_a[0]", "g_a[1]", "g_a[2]", "x"]
    assert md._condition_inputs(atoms[0], raw, {}, inputs) == []


def test_a_volatile_element_is_no_input():
    (d,) = build_mcdc_design(_unit("vol", ["g_vol[0]", "g_vol[1]", "g_state"]))["decisions"]
    assert d["search_group"] == "array_element"
    assert "g_vol[0]" not in d["path_search"]["inputs"]
    assert "C1" not in {p["condition_id"] for p in d.get("pairs") or []}


def test_an_element_input_is_inside_its_array_and_no_table():
    scope = _unit("dev", PART)["project_scope"]
    assert md._element_input(scope, "g_part[3]") is not None
    for name in ("g_part[4]", "c_lut[0]", "g_part", "g_state", "p[0]", "g_f[0]", "g_ext[0]", "g_ptr[1]"):
        assert md._element_input(scope, name) is None, name     # (review W2) float · unknown length · a pointer too
    assert md._element_input(scope, "g_vol[1]")[2] is True       # volatile: flagged, never a search input


def test_an_index_through_a_parameter_or_beside_a_member_access_stays_refused():
    (d,) = build_mcdc_design(_unit("param", ["p[0]", "g_state"]))["decisions"]
    assert d["reason"] == md._SUBSCRIPT_REASON and "search_group" not in d
    # a member access through a pointer that is no parameter is not modeled (R39 · R40): the element group does not take
    #   the decision either
    (d,) = build_mcdc_design(_unit("member", PART))["decisions"]
    assert d["reason"] == md._SUBSCRIPT_REASON and "search_group" not in d
    # (review W2 · I3 · R2 W-R2-1) an array parameter is a pointer; an array of unknown length and a pointer object — a
    #   local one too — have no element the run can name; a parameter that hides a global array of the same name is the parameter
    for name, inputs in (("arrp", ["a[2]", "g_state"]), ("ext", ["g_ext[1]", "g_state"]), ("ptr", ["g_ptr[1]", "g_state"]),
                         ("shadow", ["g_part[0]", "g_state"]), ("lptr", [*PART, "g_state"])):
        (d,) = build_mcdc_design(_unit(name, inputs))["decisions"]
        assert d["reason"] == md._SUBSCRIPT_REASON and "search_group" not in d, (name, d["reason"])


def test_a_parenthesized_array_name_and_the_element_design_range():
    unit = _unit("paren", [*PART, "g_state"])
    (d,) = build_mcdc_design(unit)["decisions"]
    assert d["search_group"] == "array_element" and d["status"] == "designed", d["reason"]
    # (review W2) the element's design range narrows its domain as for any input: 200 is outside 0..10 — C1 has no pair
    unit = _unit("ranged", [*PART, "g_state"])
    unit["uds_param_info"] = {"g_part[1]": {"range": [0, 10]}}
    report = build_mcdc_design(unit)
    (d,) = report["decisions"]
    assert d["search_group"] == "array_element"
    assert (report["domains"]["g_part[1]"]["min"], report["domains"]["g_part[1]"]["max"]) == (0, 10)
    assert "C1" not in {p["condition_id"] for p in d.get("pairs") or []}


def test_a_wide_element_decision_is_climbed_with_the_elements():
    # (review W2) thirteen conditions: the wide search (R73) of the element group sets the elements too (the values it
    #   compares with are among the samples — a per-element constant beyond them is R77's: the expression engine)
    unit = _unit("big", [f"g_big[{k}]" for k in range(13)])
    (d,) = build_mcdc_design(unit)["decisions"]
    assert d["search_group"] == "array_element" and d["pair_search"] == "path_targeted", d["reason"]
    assert d["status"] == "designed" and len(d["pairs"]) == 13, (d["reason"], d.get("path_search"))
    # (review R2 I-R2-3) a local the body sets from an element links the condition on it to that element's input: twelve
    #   such conditions climbed by moving every input each step ran out of budget (no pair)
    (d,) = build_mcdc_design(_unit("bigl", [f"g_big[{k}]" for k in range(13)]))["decisions"]
    assert d["search_group"] == "array_element" and d["pair_search"] == "path_targeted"
    assert d["status"] == "designed" and len(d["pairs"]) == 13, (d["reason"], d.get("path_search"))


def test_the_other_decisions_keep_their_design():
    unit = _unit("mixed", ["g_l", "g_state", *HIS])
    both = build_mcdc_design(unit)
    d1, d2 = both["decisions"]
    assert d1.get("search_group", "") == "" and d2["search_group"] == "array_element"
    assert d2["status"] == "designed", d2["reason"]
    alone = build_mcdc_design(unit, only_occurrences={d1["occurrence_id"]})["decisions"][0]
    for key in ("status", "reason", "pairs", "path_search"):
        assert d1.get(key) == alone.get(key), key
    assert d1["path_search"]["inputs"] == ["g_l", "g_state"]          # the elements are the element group's inputs
    # the element group's rows follow the earlier groups' rows
    first = [v for v in both["selected_inputs"] if v.get("g_his[1]") is None]
    assert both["selected_inputs"][:len(first)] == first


def test_the_other_groups_sample_as_before():
    # a local beside a const table: the general group's search samples the literals only — the table's element values
    #   (20) are the element group's (here 0 · 1 · 65535 and 1 · 100 · 200 · 300 ±1 = 13 candidates)
    (d,) = build_mcdc_design(_unit("wide_l", ["g_w"]))["decisions"]
    assert d.get("search_group", "") == "" and d["static_reason"].startswith("local_variable_not_input")
    assert d["path_search"]["samples_capped"] == {"g_w": 13}


def test_the_inventory_reads_the_constant_index_elements():
    unit = _unit("dev", [], free_globals=True)
    d1, _d2 = build_mcdc_design(unit)["decisions"]
    assert {"g_part[0]", "g_part[2]"} <= set(d1["path_search"]["inputs"]), d1.get("path_search")
    assert d1["status"] == "designed", d1["reason"]
    # (review W2 · I4) an octal index is read by the literal reader; an element the body only writes is no input
    (d,) = build_mcdc_design(_unit("wonly", [], free_globals=True))["decisions"]
    assert "g_part[1]" in d["path_search"]["inputs"] and "g_part[3]" not in d["path_search"]["inputs"], d["path_search"]


def test_counted_and_disclosed():
    unit = _unit("dev", PART)
    unit["mcdc_design"] = build_mcdc_design(unit)
    summary = summarize_mcdc_design([unit])
    assert (summary["element_condition_decisions"], summary["element_condition_designed"]) == (2, 2)
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary}) if i["key"] == "suts_mcdc_design"]
    assert "배열 원소" in item["note"] and "별도 예산" in item["note"]
