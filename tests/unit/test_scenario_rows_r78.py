"""R78 — operating-scenario rows (`generators/scenario_rows.py`, extended SUTS only).

For each statement and branch outcome of a function the search looks, on the source oracle's modeled run, for a vector
that reaches it on one path (no branch on an unknown value) with no undefined behaviour, choosing values the code names
(constants it compares an input with and their neighbours, switch labels, design ranges, small non-zero values; the
type's ends last). Every value below is what C computes on a 16-bit-int target, as the oracle models it."""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators import scenario_rows as sr
from generators.c_source_oracle import evaluate_outputs, observe_decisions
from generators.suts import (
    _base_rank,
    generate_sequences,
    is_extended_strategy,
    resolve_seq_gen_method,
    summarize_scenario_rows,
)

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
#define ST_NORMAL 0U
#define ST_ERROR 1U
#define MOV_CLOSE 3U
#define ERR_TM 30U
#endif
"""
UNIT = """#include "common.h"
U8 g_st;
U8 g_sts;
U8 g_brk;
U16 g_spd;
U16 g_tm;
U8 g_err;
U8 g_o;
S16 g_p;
S16 g_q;
S16 g_r;
S16 g_off;
S16 g_slope;
U16 g_v;
U8 g_hw;
U8 ext(void)
{
    return g_hw;
}
void diag(void)
{
    switch (g_st)
    {
        case ST_NORMAL:
            if ((g_sts == MOV_CLOSE) && (g_brk == 0U) && (g_spd > 500U))
            {
                g_tm++;
                if (g_tm > ERR_TM)
                {
                    g_tm = 0U;
                    g_err = 1U;
                    g_st = ST_ERROR;
                }
            }
            else
            {
                g_tm = 0U;
            }
            break;
        case ST_ERROR:
            g_err = 2U;
            break;
        default:
            g_st = ST_NORMAL;
            break;
    }
}
void ovf(void)
{
    if ((g_p > g_q) && ((g_r + 600) > g_p))
    {
        g_off = (g_p - g_q) / 10;
    }
}
void sign(void)
{
    if (g_slope >= 0)
    {
        g_o = 1U;
    }
    else
    {
        g_o = 2U;
    }
}
void called(void)
{
    if (ext() == 3U)
    {
        g_o = 7U;
    }
    g_err = 4U;
}
U8 g_lvl;
void lvl(void)
{
    switch (g_lvl)
    {
        case 0U:
            g_o = (U8)(g_v + 1U);
            break;
        case 4U:
            if (g_v == 10U)
            {
                g_o = (U8)(g_k + 2U);
            }
            else
            {
                g_o = 5U;
            }
            break;
        default:
            g_o = 3U;
            break;
    }
}
U8 g_x;
U8 g_y;
U8 g_t;
U8 g_hw2;
U16 g_tt;
U8 g_m;
U8 g_la;
U8 g_lb;
U8 g_lc;
U8 g_lw;
U8 g_o2;
U8 g_k;
void pq(void)
{
    if (g_y > 2U)
    {
        g_t = 1U;
    }
    if (g_x > 30U)
    {
        g_o = 5U;
    }
    else
    {
        g_o = g_hw2;
    }
}
void pcap(void)
{
    if (g_tt > 30U)
    {
        g_o = 9U;
    }
    switch (g_m)
    {
        case 2U: g_o = 4U; break;
        case 5U: g_o = 6U; break;
        case 7U: g_o = 8U; break;
        case 11U: g_o = 12U; break;
        case 13U: g_o = 14U; break;
        default: g_o = 15U; break;
    }
}
void lu(void)
{
    if (g_la > 5U)
    {
        if (g_lb > 6U)
        {
            if ((g_lc > 7U) || (g_lw > 1U))
            {
                g_o = 1U;
            }
        }
        g_o2 = 2U;
    }
}
void sw(void)
{
    switch (g_st)
    {
        case 1U:
            g_o = 1U;
            break;
        default:
            g_o = 0U;
            break;
    }
}
U8 g_lv;
void big(void)
{
    switch (g_lv)
    {
        case 0U: g_o = 10U; break;
        case 1U: g_o = 11U; break;
        case 2U: g_o = 12U; break;
        case 3U: g_o = 13U; break;
        case 6U: g_o = 22U; break;
        default: g_o = 30U; break;
    }
    g_t = (U8)(g_t + 40U + 50U + 60U + 70U + 80U + 90U + 100U);
}
U8 g_lw;
void big2(void)
{
    switch (g_lw)
    {
        case 0U: g_o = 10U; break;
        case 1U: g_o = 11U; break;
        case 6U: g_o = 22U; break;
        default: g_o = 30U; break;
    }
    if (g_lw > 30U) { g_t = 1U; }
    if (g_lw > 40U) { g_t = 2U; }
    if (g_lw > 50U) { g_t = 3U; }
}
U8 g_pa;
U8 g_pt;
U8 g_pp;
void polish(void)
{
    if (g_pa > 30U) { g_pp = 1U; }
    if (g_pa > 40U) { g_pp = 2U; }
    if (g_pa > 50U) { g_pp = 3U; }
    if (g_pt > 30U)
    {
        g_o = (U8)(100U / (g_pa - 12U));
    }
}
void never(void)
{
    if ((g_p > 5) && (g_p < 3))
    {
        g_o = 1U;
    }
}
U16 g_w;
U8 g_arr[4];
void twok(void)
{
    if (g_w == 0U)
    {
        g_o = 1U;
    }
    else if (g_w > 5U)
    {
        g_o = 2U;
    }
}
void part(void)
{
    if ((g_arr[0] == 0x30U) && (g_arr[2] == 0x4CU))
    {
        g_o = 1U;
    }
}
void ubfix(void)
{
    S16 t = (S16)(g_p * 200);
    if (g_p > 300)
    {
        g_o = 1U;
    }
    if (g_sts == MOV_CLOSE)
    {
        g_off = t;
    }
}
void pol(void)
{
    g_off = 5;
    if (g_w > 60000U)
    {
        g_o = 1U;
    }
}
void pub(void)
{
    S16 t = (S16)((g_q * 3) + g_p);
    g_off = t;
}
void deref(U8 *p)
{
    if (g_sts == MOV_CLOSE)
    {
        if (*p > 3U)
        {
            g_o = 1U;
        }
    }
}
static U8 s_gate;
void hidden2(void)
{
    g_o = 0U;
    if (g_sts > 10U)
    {
        if (s_gate > 2U)
        {
            g_o = 9U;
        }
    }
}
void hidden(void)
{
    if (g_sts == MOV_CLOSE)
    {
        if (s_gate > 2U)
        {
            g_o = 9U;
        }
    }
}
U16 ratio(void)
{
    U16 r = 100U;
    if (g_v > 1250U)
    {
        r = (U16)(475U - (30U * g_v / 100U));
    }
    return r;
}
"""
U8 = (0, 255)
U16 = (0, 65535)
S16 = (-32768, 32767)


def _unit(name):
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    return {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path]}


DIAG = {"g_st": U8, "g_sts": U8, "g_brk": U8, "g_spd": U16, "g_tm": U16}
DIAG_OUT = ["g_st", "g_tm", "g_err"]


def _reaching(unit, found, text):
    """The scenario rows whose run executes the statement ``text`` (by the oracle's own statement marks)."""
    raw = unit["source_text"].encode()
    start = unit["source_text"].index(text)
    node = cpc.shared_parser().parse(raw).root_node.descendant_for_byte_range(start, start + len(text))
    while node.type != "expression_statement":
        node = node.parent
    key = [node.start_byte, node.end_byte, node.type]
    runs = observe_decisions(unit, [r["inputs"] for r in found["rows"]], [], reach=[key])
    return [r for r, run in zip(found["rows"], runs, strict=True) if any(True in p for p in run["reach"][0])]


# ── the search ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_state_machine_path_is_reached_with_the_values_the_code_names():
    unit = _unit("diag")
    found = sr.find_scenarios(unit, DIAG, DIAG_OUT)
    rep = found["report"]
    assert rep["status"] == "searched" and rep["reached_clean"] == rep["targets"] and rep["not_reached"] == 0
    rows = _reaching(unit, found, "g_err = 1U;")
    assert rows
    for row in rows:
        v = row["inputs"]
        # the path's state, status, brake flag and speed set together; the timer just at its limit (30 → ++ → 31 > 30)
        assert (v["g_st"], v["g_sts"], v["g_brk"]) == (0, 3, 0) and v["g_spd"] in (501,) and v["g_tm"] == 30
    # no row needs a type end or middle: every value is one the code names or a small one
    assert all(x not in (127, 255, 32767, 65535) for r in found["rows"] for x in r["inputs"].values())


def test_the_switch_labels_and_the_timer_below_its_limit_are_reached_too():
    unit = _unit("diag")
    found = sr.find_scenarios(unit, DIAG, DIAG_OUT)
    assert any(r["inputs"]["g_st"] == 1 for r in _reaching(unit, found, "g_err = 2U;"))
    assert all(r["inputs"]["g_st"] not in (0, 1) for r in _reaching(unit, found, "g_st = ST_NORMAL;"))
    below = [r for r in found["rows"] if r["target_kind"] == "branch" and "g_tm > ERR_TM" in r["target_text"]
             and r["target_outcome"] is False]
    assert below and below[0]["inputs"]["g_tm"] < 30


def test_a_vector_that_overflows_is_never_a_scenario():
    unit = _unit("ovf")
    found = sr.find_scenarios(unit, {"g_p": S16, "g_q": S16, "g_r": S16}, ["g_off"])
    rows = _reaching(unit, found, "g_off = (g_p - g_q) / 10;")
    assert rows
    got = evaluate_outputs(unit, [r["inputs"] for r in rows], [["g_off"]] * len(rows))
    assert all(g["status"] == "supported" and "value" in g["outputs"]["g_off"] for g in got)
    assert all(abs(x) < 16384 for r in rows for x in r["inputs"].values())


def test_a_negative_value_takes_the_other_side_of_a_comparison_with_zero():
    unit = _unit("sign")
    found = sr.find_scenarios(unit, {"g_slope": S16}, ["g_o"])
    values = {r["inputs"]["g_slope"] for r in found["rows"]}
    assert any(v < 0 for v in values) and any(v >= 0 for v in values)
    assert -1 in values   # the comparison's own neighbour, not the type's end


def test_a_value_the_row_cannot_set_is_counted_not_claimed():
    unit = _unit("called")
    found = sr.find_scenarios(unit, {"g_err": U8}, ["g_o", "g_err"])
    rep = found["report"]
    # ``ext()`` is no input here: the branch on its value forks — what lies behind it is never reached cleanly
    assert rep["reached_clean"] < rep["targets"]
    assert rep["reached_clean"] + rep["reached_unclean_only"] + rep["not_reached"] == rep["targets"]
    assert not any("g_o = 7U" in r["target_text"] for r in found["rows"])


def test_a_stub_return_value_is_an_input_like_any_other():
    unit = _unit("called")
    found = sr.find_scenarios(unit, {"ext() return": U8}, ["g_o", "g_err"])
    assert found["report"]["reached_clean"] == found["report"]["targets"]
    assert any(r["inputs"]["ext() return"] == 3 for r in _reaching(unit, found, "g_o = 7U;"))


def test_an_arithmetic_threshold_is_crossed_with_a_value_from_the_comparison():
    unit = _unit("ratio")
    found = sr.find_scenarios(unit, {"g_v": U16}, ["return"])
    rows = [r for r in _reaching(unit, found, "r = (U16)(475U - (30U * g_v / 100U));")
            if r["target_kind"] not in sr.EXPOSE_KINDS]    # (R79) a write-exposing row moves g_v off 1251 on purpose
    assert rows and all(r["inputs"]["g_v"] in (1251,) for r in rows)


def test_existing_rows_are_starts_and_duplicates_are_not_added():
    unit = _unit("sign")
    first = sr.find_scenarios(unit, {"g_slope": S16}, ["g_o"])
    again = sr.find_scenarios(unit, {"g_slope": S16}, ["g_o"], [r["inputs"] for r in first["rows"]])
    assert again["rows"] == [] and again["report"]["duplicates"] == len(first["rows"])
    assert again["report"]["reached_clean"] == again["report"]["targets"]


def test_the_search_is_deterministic():
    unit = _unit("diag")
    assert sr.find_scenarios(unit, DIAG, DIAG_OUT) == sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)


def test_budgets_cut_and_say_so(monkeypatch):
    monkeypatch.setattr(sr, "MAX_RUNS", 3)
    monkeypatch.setattr(sr, "MAX_EXPOSE_RUNS", 0)    # (R79) the exposing phase's rows would reach the cut targets
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)["report"]
    assert rep["budget_exhausted"] and rep["runs"] == 3          # what ran, also when the budget stops a batch
    assert rep["budget_cut"] == rep["not_reached"] > 0
    assert rep["reached_clean"] + rep["reached_unclean_only"] + rep["not_reached"] == rep["targets"]
    monkeypatch.setattr(sr, "MAX_RUNS", 800)
    monkeypatch.setattr(sr, "MAX_ROWS", 1)
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)["report"]
    assert rep["rows"] == 1 and rep["cut"] >= 1


@pytest.mark.parametrize("domains, status", [({}, "no_integer_inputs"), ({"g_st": "U8"}, "no_integer_inputs")])
def test_nothing_to_move_is_a_reason(domains, status):
    assert sr.find_scenarios(_unit("diag"), domains, DIAG_OUT)["report"]["status"] == status


def test_no_project_scope_is_a_reason():
    unit = dict(_unit("diag"), project_scope=None)
    assert sr.find_scenarios(unit, DIAG, DIAG_OUT)["report"]["status"] == "no_project_scope"


def test_operating_values_come_first_and_type_ends_last():
    unit = _unit("diag")
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "diag", unit["project_scope"])
    pools, defaults = sr.operating_pools(unit, {k: sr._norm(v) for k, v in DIAG.items()}, fn, raw,
                                         unit["project_scope"], {})
    assert defaults["g_sts"] == 3 and defaults["g_brk"] == 0 and defaults["g_spd"] == 500 and defaults["g_tm"] == 30
    assert defaults["g_st"] == 0                          # a switch label it selects
    assert pools["g_spd"][:3] == [500, 501, 499] and pools["g_spd"][-2:] == [0, 65535] or pools["g_spd"][-1] == 65535


# ── the oracle's statement marks ─────────────────────────────────────────────────────────────────────────────────

def test_statement_marks_and_outputs_agree_with_evaluate_outputs():
    unit = _unit("sign")
    raw = UNIT.encode()
    tree = cpc.shared_parser().parse(raw).root_node
    keys = []
    for text in ("g_o = 1U;", "g_o = 2U;"):
        start = UNIT.index(text)
        node = tree.descendant_for_byte_range(start, start + len(text))
        while node.type != "expression_statement":
            node = node.parent
        keys.append([node.start_byte, node.end_byte, node.type])
    vectors = [{"g_slope": 5}, {"g_slope": -1}]
    runs = observe_decisions(unit, vectors, [], reach=keys, outputs=["g_o"])
    assert [r["reach"][0] for r in runs] == [[[True]], [[]]]
    assert [r["reach"][1] for r in runs] == [[[]], [[True]]]
    assert [r["forked"] for r in runs] == [False, False]
    plain = evaluate_outputs(unit, vectors, [["g_o"]] * 2)
    assert [r["outputs"] for r in runs] == [p["outputs"] for p in plain]


def test_a_statement_after_a_branch_on_an_unknown_value_is_marked_uncertain():
    unit = _unit("called")
    start = UNIT.index("g_err = 4U;")
    node = cpc.shared_parser().parse(UNIT.encode()).root_node.descendant_for_byte_range(start, start + 3)
    while node.type != "expression_statement":
        node = node.parent
    run = observe_decisions(unit, [{}], [], reach=[[node.start_byte, node.end_byte, node.type]], outputs=["g_err"])[0]
    assert run["forked"] is True and run["reach"][0] == [[False], [False]]


# ── the SUTS wiring ─────────────────────────────────────────────────────────────────────────────────────────────

def _seq_unit(name="diag", **kw):
    unit = _unit(name)
    unit.update({"fid": "F1", "input_vars": ["g_st", "g_sts", "g_brk", "g_spd", "g_tm"],
                 "output_vars": ["g_st", "g_tm", "g_err"],
                 "param_types": {"g_st": "U8", "g_sts": "U8", "g_brk": "U8", "g_spd": "U16", "g_tm": "U16",
                                 "g_err": "U8"}})
    unit.update(kw)
    return unit


def test_the_extended_profile_adds_scenario_rows_with_oracle_expectations():
    unit = _seq_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rows = [s for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX)]
    assert rows and all(is_extended_strategy(s["strategy"]) and s["tc_profile"] == "extended" for s in rows)
    assert all(resolve_seq_gen_method(s["strategy"]) == resolve_seq_gen_method("COND_COMB_0") for s in rows)
    deep = [s for s in rows if s["inputs"].get("g_sts") == 3 and s["inputs"].get("g_spd") == 501
            and s["inputs"].get("g_tm") == 30 and s["inputs"].get("g_st") == 0]
    assert deep and deep[0]["expected"]["g_err"] == 1 and deep[0]["expected_evidence"]["g_err"]["status"] == "derived"
    assert all("동작 시나리오" in s["description"] and "미실행" in s["description"] for s in rows)
    assert unit["scenario_rows"]["rows"] == len(rows)


def test_the_reference_profile_has_no_scenario_rows():
    seqs = generate_sequences(_seq_unit(), 24, type_cache={})
    assert not any(s["strategy"].startswith(sr.SCENARIO_PREFIX) for s in seqs)


def test_scenario_rows_never_push_out_the_existing_bases():
    # they are added bases (`find_boundaries` ``extra_bases`` · robustness `MAX_ROBUST_SCENARIO_BASES`), last in the rank
    assert _base_rank({"strategy": "SCN_0"}) > max(_base_rank({"strategy": s}) for s in
                                                   ("BV_MID", "MCDC_0", "COND_COMB_0", "OAT_0_MIN", "BND_0"))


def test_the_boundary_search_runs_the_scenario_bases_after_the_others():
    from generators import boundary_rows as br
    unit = _unit("diag")
    base = [{"inputs": {"g_st": 0, "g_sts": 0, "g_brk": 0, "g_spd": 0, "g_tm": 0}, "strategy": "BV_MID"}]
    alone = br.find_boundaries(unit, base, DIAG, DIAG_OUT)
    scen = sr.find_scenarios(unit, DIAG, DIAG_OUT)["rows"]
    both = br.find_boundaries(unit, base, DIAG, DIAG_OUT,
                              extra_bases=[{"inputs": r["inputs"], "strategy": "SCN"} for r in scen])
    # the first search is the same with or without the extra bases; the extra ones add boundaries behind the AND
    assert both["rows"][:len(alone["rows"])] == alone["rows"]
    assert both["report"]["boundaries"] == alone["report"]["boundaries"]
    assert both["report"]["extra_bases"] >= 1 and both["report"]["extra_boundaries"] >= 1
    assert any(r["variable"] == "g_spd" and (r["lo"], r["hi"]) == (500, 501) for r in both["rows"][len(alone["rows"]):])
    assert not any(r["variable"] == "g_spd" and r["lo"] == 500 for r in alone["rows"])


def test_a_failing_search_costs_only_its_own_rows(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("x")
    monkeypatch.setattr("generators.suts.find_scenarios", boom)
    unit = _seq_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert not any(s["strategy"].startswith(sr.SCENARIO_PREFIX) for s in seqs)
    assert unit["scenario_rows"] == {"error": "RuntimeError", "rows": 0}
    assert summarize_scenario_rows([unit])["errors"] == 1


def test_an_object_the_input_list_misses_is_named_by_the_search():
    found = sr.find_scenarios(_unit("hidden"), {"g_sts": U8}, ["g_o"])
    rep = found["report"]
    # behind `g_sts == 3` the run branches on `s_gate`, which no vector sets: never clean — and the search says what it needed
    # 4 targets: `g_o = 9U`, both outcomes of `s_gate > 2U` (evaluated with s_gate undetermined — reached, not a local
    #   best: review R78 R2 W-R2-2) and `g_sts == 3` true (the run forks after it — no clean run)
    assert rep["reached_clean"] == 1 and rep["reached_unclean_only"] == 4 and rep["local_best"] == 0
    assert rep["needed_inputs"] == {"s_gate": 4} and rep["inputs_needed"] == 1
    assert not any("g_o = 9U" in r["target_text"] for r in found["rows"])


def test_the_input_completion_adds_what_the_search_needed_and_the_next_round_reaches_it():
    from generators.suts import complete_source_read_inputs
    unit = _seq_unit("hidden", input_vars=["g_sts"], output_vars=["g_o"], param_types={"g_sts": "U8", "g_o": "U8"})

    def gen():
        return generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    seqs = complete_source_read_inputs(unit, gen(), gen)
    added = unit["source_read_inputs"]["added"]
    # no row read `s_gate` in the first round (none got past `g_sts == 3` with a value for it) — the search named it
    assert added["s_gate"]["round"] == 1 and added["s_gate"]["scenario_targets"] == 4 and added["s_gate"]["slots"] == 0
    # the second round's search reaches every target cleanly (the row for `g_o = 9U` may be one the suite already has)
    rep = unit["scenario_rows"]
    assert rep["reached_clean"] == rep["targets"] and rep["needed_inputs"] == {}
    deep = [s for s in seqs if s["inputs"].get("g_sts") == 3 and isinstance(s["inputs"].get("s_gate"), int)
            and s["inputs"]["s_gate"] > 2]
    assert deep and deep[0]["expected"]["g_o"] == 9 and deep[0]["expected_evidence"]["g_o"]["status"] == "derived"


def test_without_the_search_the_rows_alone_never_see_the_object(monkeypatch):
    from generators.suts import complete_source_read_inputs
    monkeypatch.setattr("generators.suts.find_scenarios",
                        lambda *_a, **_k: {"rows": [], "report": {"status": "searched", "rows": 0}})
    unit = _seq_unit("hidden", input_vars=["g_sts"], output_vars=["g_o"], param_types={"g_sts": "U8", "g_o": "U8"})

    def gen():
        return generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    complete_source_read_inputs(unit, gen(), gen)
    # the reference catalogue sets g_sts to its type's values — none is 3, so no row reaches the read of s_gate
    assert "s_gate" not in unit["source_read_inputs"]["added"]


def test_a_timer_threshold_outside_the_design_range_is_robustness_rows_first():
    # the design says the timer runs 0~20; the code turns at `g_tm > 30` — the error path needs 30 (++ → 31). R31's
    #   robustness rows (direct comparison constant outside the design range) run first, on a scenario base where the
    #   comparison is live; the second scenario search adds nothing they already reach (review R78 C1)
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rob = [s for s in seqs if s["strategy"].startswith("ROBUST_")]
    assert {s["inputs"]["g_tm"] for s in rob} >= {29, 30, 31}
    err = [s for s in rob if s["expected"].get("g_err") == 1]
    assert err and all(s["inputs"]["g_tm"] >= 30 and s["inputs"]["g_st"] == 0 for s in err)
    fi = [s for s in seqs if s["strategy"].startswith(sr.SCENARIO_FI_PREFIX)]
    assert not {json_key(s) for s in fi} & {json_key(s) for s in rob}
    assert unit["robustness_rows"]["rows"] >= 3 and unit["robustness_rows"]["duplicates"] == 0
    # the rows inside the design range stay inside it
    assert all(0 <= s["inputs"]["g_tm"] <= 20 for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX))


def json_key(s):
    import json
    return json.dumps(s["inputs"], sort_keys=True, default=str)


def _lvl_unit(rng=(0, 3)):
    unit = _unit("lvl")
    unit.update({"fid": "F1", "input_vars": ["g_lvl", "g_v", "g_k"], "output_vars": ["g_o"],
                 "param_types": {"g_lvl": "U8", "g_v": "U16", "g_k": "U8", "g_o": "U8"},
                 "uds_param_info": {"g_lvl": {"range": list(rng)}, "g_v": {"range": [0, 10]},
                                    "g_k": {"range": [0, 5]}}})
    return unit


def test_a_switch_label_outside_the_design_range_is_a_robustness_scenario():
    # the design says the level runs 0~3; the code has a label 4 (HDPDM01 `s_PlayProtectChk` ACTIVATED) — only a value
    #   outside the design range takes it, and no comparison names it (R31 reads comparisons, not labels)
    unit = _lvl_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    fi = [s for s in seqs if s["strategy"].startswith(sr.SCENARIO_FI_PREFIX)]
    assert rep["outside_design_inputs"] == 3 and rep["outside_design_reached"] >= 1 and rep["outside_design_rows"] == len(fi)
    four = [s for s in fi if s["inputs"]["g_lvl"] == 4 and s["inputs"]["g_v"] == 10]
    assert four and four[0]["expected"]["g_o"] == four[0]["inputs"]["g_k"] + 2 and 0 <= four[0]["inputs"]["g_k"] <= 5
    # 6 targets: case 0 and default are reached inside the range, the existing BV_MAX_INV row {4, 11} reaches
    #   `g_o = 5U` and `g_v == 10U` false — only `g_o = 2U` and `g_v == 10U` true are searched again
    assert rep["outside_design_searched"] == 2 and rep["outside_design_reached"] == 2
    # what the target does not need stays in the design range (review R78 W1-b): g_v 0~10, g_k 0~5 (no comparison names
    #   g_k — without its home it would start at a free value past 100)
    assert all(s["scenario"]["outside_design"] == {"g_lvl": s["inputs"]["g_lvl"]} and 0 <= s["inputs"]["g_v"] <= 10
               and 0 <= s["inputs"]["g_k"] <= 5 for s in fi)
    assert all(is_extended_strategy(s["strategy"]) and "설계 범위 밖" in s["description"] for s in fi)
    from generators.suts import resolve_seq_test_method
    assert {resolve_seq_test_method(s["strategy"]) for s in fi} == {resolve_seq_test_method("BV_MAX_INV")}
    # the second search runs after every other extended row — none of them is built on a robustness scenario
    last = max(i for i, s in enumerate(seqs) if not s["strategy"].startswith(sr.SCENARIO_FI_PREFIX))
    assert all(seqs.index(s) > last for s in fi)
    assert rep["outside_design_runs"] > 0 and rep["outside_design_searched"] >= 1


def test_a_target_the_first_search_reached_is_not_searched_again(monkeypatch):
    # the row cap cuts the first search's rows: what it cut stays unreached and the second search may take it, but a
    #   target a kept row reaches is never labelled "only outside the design range" (review R78 W1-a)
    monkeypatch.setattr(sr, "MAX_ROWS", 1)
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    assert rep["rows"] == 1 and rep["cut"] >= 1 and rep["reached_clean"] < rep["targets"]
    for s in seqs:
        if s["strategy"].startswith(sr.SCENARIO_FI_PREFIX):
            # only what the timer outside 0~20 reaches is FI — the ERROR state's `g_err = 2U` (no timer) never is
            assert s["inputs"]["g_tm"] > 20 and s["scenario"]["outside_design"] == {"g_tm": s["inputs"]["g_tm"]}
            assert "g_err = 2U" not in s["scenario"]["target_text"]


def test_no_second_search_when_the_design_range_hides_nothing():
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 40]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    assert rep["outside_design_searched"] == 0 and rep["outside_design_runs"] == 0   # the first search reached all
    assert not any(s["strategy"].startswith(sr.SCENARIO_FI_PREFIX) for s in seqs)


def test_undefined_behaviour_that_may_happen_is_not_clean():
    # `g_q * 3` with g_q unset: no branch, but a possible signed overflow whatever g_p is — the run is no clean scenario
    #   (`g_p * g_q` would not do: g_p = 1 rules the overflow out, and the search finds that)
    found = sr.find_scenarios(_unit("pub"), {"g_p": S16}, ["g_off"])
    rep = found["report"]
    assert rep["reached_clean"] == 0 and rep["reached_unclean_only"] == rep["targets"] and found["rows"] == []
    assert rep["needed_inputs"] == {"g_q": 1}
    both = sr.find_scenarios(_unit("pub"), {"g_p": S16, "g_q": S16}, ["g_off"])["report"]
    assert both["reached_clean"] == both["targets"]


def test_only_program_objects_are_named_as_needed():
    # behind `*p` the run reads through a pointer nobody set — the oracle's read mark is no object to add
    rep = sr.find_scenarios(_unit("deref"), {"g_sts": U8}, ["g_o"])["report"]
    assert rep["reached_clean"] < rep["targets"]
    assert all(sr._NAME.fullmatch(n) for n in rep["needed_inputs"]) and not any("@" in n for n in rep["needed_inputs"])


def test_the_oracle_marks_a_read_through_an_unknown_pointer():
    # the guard above is only worth something if such a mark exists on these runs
    unit = _unit("deref")
    run = observe_decisions(unit, [{"g_sts": 3}], [], reach=[[0, 0, "x"]], outputs=["g_o"])[0]
    assert any(str(n).startswith("@") for n in run["initial_reads"])


def test_a_design_range_that_is_the_whole_type_is_no_operating_value():
    unit = dict(_unit("ratio"), bounds_source={"g_v": "uds_range"})
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "ratio", unit["project_scope"])
    pools, defaults = sr.operating_pools(unit, {"g_v": (0, 65535)}, fn, raw, unit["project_scope"], {})
    assert defaults["g_v"] == 1250 and 32767 not in pools["g_v"][:3]   # its comparison constant, not the type's middle
    narrow, _ = sr.operating_pools(unit, {"g_v": (0, 1000)}, fn, raw, unit["project_scope"], {})
    assert narrow["g_v"][0] == 500                                    # a real design range: its middle first


def test_distinct_values_for_inputs_the_code_compares_with_nothing():
    unit = _unit("pub")
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "pub", unit["project_scope"])
    names = {f"x{i}": S16 for i in range(20)}
    _p, defaults = sr.operating_pools(unit, names, fn, raw, unit["project_scope"], {})
    assert len(set(defaults.values())) == 20 and all(100 < v <= 180 for v in defaults.values())
    assert len({sr._free_value(i) for i in range(sr._FREE_SPAN)}) == sr._FREE_SPAN


def test_a_cut_row_leaves_its_targets_unreached(monkeypatch):
    monkeypatch.setattr(sr, "MAX_ROWS", 1)
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)["report"]
    assert rep["rows"] == 1 and rep["cut"] >= 1
    # the cap full, the targets left are not searched (`cut`) — unreached, or reached only uncleanly by runs already made
    assert rep["budget_cut"] == 0 and rep["local_best"] + rep["climb_cap"] + rep["cut"] == rep["not_reached"]
    assert rep["reached_clean"] + rep["reached_unclean_only"] + rep["not_reached"] \
        == rep["targets"]


def test_covered_vectors_take_their_targets_out_of_the_search():
    first = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)
    again = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT, covered=first["reached_vectors"])["report"]
    assert again["covered_before"] == first["report"]["reached_clean"] == again["targets"]
    assert again["rows"] == 0 and again["reached_clean"] == again["targets"]


def test_every_refused_run_is_a_status_not_a_local_best():
    unit = _unit("diag")
    unit["project_scope"] = dict(unit["project_scope"], target={"widths": {}})   # no int width: every run refused
    unit["project_scope"]["main_file_sha256"] = _unit("diag")["project_scope"]["main_file_sha256"]
    rep = sr.find_scenarios(unit, DIAG, DIAG_OUT)["report"]
    assert rep["status"].startswith("oracle_unsupported:") and rep["reached_clean"] == 0
    assert rep["local_best"] == rep["climb_cap"] == rep["budget_cut"] == 0 and rep["not_reached"] == rep["targets"]


def test_the_extra_boundary_search_has_its_own_budget_dedupe_and_cap(monkeypatch):
    from generators import boundary_rows as br
    unit = _unit("diag")
    base = [{"inputs": {"g_st": 0, "g_sts": 0, "g_brk": 0, "g_spd": 0, "g_tm": 0}, "strategy": "BV_MID"}]
    scen = [{"inputs": r["inputs"], "strategy": "SCN"} for r in sr.find_scenarios(unit, DIAG, DIAG_OUT)["rows"]]
    monkeypatch.setattr(br, "MAX_EVALUATIONS", 5)          # the first search runs dry at once
    got = br.find_boundaries(unit, base, DIAG, DIAG_OUT, extra_bases=scen)["report"]
    assert got["evaluation_budget_exhausted"] and got["extra_boundaries"] >= 1   # the second search still has its own
    dup = br.find_boundaries(unit, base, DIAG, DIAG_OUT, extra_bases=base + scen[:1])["report"]
    assert dup["extra_bases_available"] == 1                 # the base itself is no extra base
    monkeypatch.setattr(br, "MAX_EXTRA_BASES", 1)
    capped = br.find_boundaries(unit, base, DIAG, DIAG_OUT, extra_bases=scen)["report"]
    assert capped["extra_bases"] == 1 and capped["extra_bases_available"] == len(scen) > 1


def test_the_suts_boundary_search_takes_the_scenario_rows_as_extra_bases():
    unit = _seq_unit()
    generate_sequences(unit, None, type_cache={}, extended=True)
    bs = unit["boundary_search"]
    assert bs["extra_bases"] >= 1 and bs["extra_bases"] == min(unit["scenario_rows"]["rows"], 12)


def test_a_failing_second_search_drops_only_its_own_rows(monkeypatch):
    import generators.suts as suts_mod
    real = suts_mod._scenario_row

    def boom(sequences, row, strategy, *a, **k):
        real(sequences, row, strategy, *a, **k)
        if strategy.startswith(sr.SCENARIO_FI_PREFIX):
            raise RuntimeError("x")
    monkeypatch.setattr(suts_mod, "_scenario_row", boom)
    unit = _lvl_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert not any(s["strategy"].startswith(sr.SCENARIO_FI_PREFIX) for s in seqs)
    assert unit["scenario_rows"]["outside_design_error"] == "RuntimeError"
    assert summarize_scenario_rows([unit])["errors"] == 1
    assert all("expected_evidence" in s for s in seqs)


def test_a_name_rows_read_keeps_their_count_when_the_search_needs_it_too():
    from generators.suts import complete_source_read_inputs
    unit = _seq_unit("hidden2", input_vars=["g_sts"], output_vars=["g_o"], param_types={"g_sts": "U8", "g_o": "U8"})

    def gen():
        return generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    complete_source_read_inputs(unit, gen(), gen)
    added = unit["source_read_inputs"]["added"]["s_gate"]
    assert added["slots"] > 0 and "scenario_targets" not in added   # rows with g_sts > 10 read it — their count wins


def test_a_design_range_equal_to_the_type_widens_nothing():
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 65535]}})
    generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    assert rep["outside_design_inputs"] == 0 and rep["outside_design_runs"] == 0


def test_the_robustness_rows_use_a_scenario_base_where_no_other_base_is_live():
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    generate_sequences(unit, None, type_cache={}, extended=True)
    assert unit["robustness_rows"]["live"] >= 1


def _pools(name, domains, **unit_kw):
    unit = dict(_unit(name), **unit_kw)
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, name, unit["project_scope"])
    return sr.operating_pools(unit, {k: sr._norm(v) for k, v in domains.items()}, fn, raw, unit["project_scope"], {})


def test_a_non_zero_comparison_constant_is_the_operating_value():
    pools, defaults = _pools("twok", {"g_w": U16})
    assert defaults["g_w"] == 5 and pools["g_w"][:3] == [5, 6, 4] and 0 in pools["g_w"]   # 0 later, not first


def test_an_element_compared_with_a_constant_starts_at_it():
    pools, defaults = _pools("part", {"g_arr[0]": U8, "g_arr[2]": U8})
    assert defaults == {"g_arr[0]": 0x30, "g_arr[2]": 0x4C}


def test_a_whole_type_design_range_gives_no_middle_to_an_input_compared_with_nothing():
    _p, defaults = _pools("pub", {"g_p": S16}, bounds_source={"g_p": "uds_range"})
    assert 100 < defaults["g_p"] <= 180            # an operating value, not the type's middle (-1)
    _p, narrow = _pools("pub", {"g_p": (-100, 100)}, bounds_source={"g_p": "uds_range"})
    assert narrow["g_p"] == 0                       # a real design range: its middle


def test_a_run_the_values_overflow_on_moves_every_input():
    # the operating value of g_p is 300 (its comparison) and `g_p * 200` overflows there: the target `g_off = t` sits under
    #   `g_sts == 3`, so its control chain names g_sts only — the overflow is fixed by moving g_p
    found = sr.find_scenarios(_unit("ubfix"), {"g_p": S16, "g_sts": U8}, ["g_off", "g_o"])
    row = next(r for r in found["rows"] if r["target_text"] == "g_off = t;")
    assert row["inputs"]["g_sts"] == 3 and abs(row["inputs"]["g_p"] * 200) <= 32767
    assert found["report"]["status"] == "searched"   # some runs refused (overflow), not every run


def test_an_extreme_operating_value_the_target_does_not_need_is_polished_away():
    found = sr.find_scenarios(_unit("pol"), {"g_w": U16}, ["g_off", "g_o"])
    first = next(r for r in found["rows"] if r["target_text"] == "g_off = 5;")
    assert first["inputs"]["g_w"] == 5                 # not its comparison's 60000: the statement needs nothing of it
    assert any(r["inputs"]["g_w"] == 60001 for r in found["rows"])


def test_a_widened_input_starts_and_ends_inside_its_design_range():
    # the search may move g_v anywhere 0..65535, but its home is 0..10: it starts there and comes back there
    found = sr.find_scenarios(_unit("lvl"), {"g_lvl": U8, "g_v": U16}, ["g_o"], home={"g_v": (0, 10)})
    pools, defaults = _pools("lvl", {"g_lvl": U8, "g_v": U16})
    assert all(0 <= r["inputs"]["g_v"] <= 10 for r in found["rows"])
    homed = sr.find_scenarios(_unit("lvl"), {"g_lvl": U8, "g_v": U16}, ["g_o"], home={"g_v": (0, 10)})
    assert homed == found
    raw = _unit("lvl")["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    unit = _unit("lvl")
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "lvl", unit["project_scope"])
    hp, hd = sr.operating_pools(unit, {"g_lvl": U8, "g_v": U16}, fn, raw, unit["project_scope"], {}, home={"g_v": (0, 10)})
    assert 0 <= hd["g_v"] <= 10 and all(0 <= v <= 10 for v in hp["g_v"][:4])
    assert not (0 <= defaults["g_v"] <= 10) or defaults["g_v"] == 10   # without home it starts at its comparison (10)


def test_values_outside_the_home_range_are_moved_back_when_the_target_allows():
    # the climb takes g_v = 11 (outside home 0..10) to make `g_v == 10U` false while g_lvl is 4 — 9 does it too and is home
    found = sr.find_scenarios(_unit("lvl"), {"g_lvl": U8, "g_v": U16}, ["g_o"], home={"g_v": (0, 10)},
                              existing=[{"g_lvl": 4, "g_v": 11}])
    for row in found["rows"]:
        assert 0 <= row["inputs"]["g_v"] <= 10
    # the existing row reaches `g_o = 5U` with g_v = 11 — moved back home it is a new row, not that row's duplicate
    back = [r for r in found["rows"] if r["target_text"] == "g_o = 5U;"]
    assert back and back[0]["inputs"]["g_lvl"] == 4 and back[0]["inputs"]["g_v"] != 10


def test_the_boundary_search_of_the_old_bases_is_the_same_with_scenario_rows(monkeypatch):
    def boundary(with_scenarios):
        if not with_scenarios:
            monkeypatch.setattr("generators.suts.find_scenarios",
                                lambda *_a, **_k: {"rows": [], "reached_vectors": [],
                                                   "report": {"status": "searched", "rows": 0}})
        unit = _seq_unit()
        generate_sequences(unit, None, type_cache={}, extended=True)
        monkeypatch.undo()
        return unit["boundary_search"]
    plain, with_rows = boundary(False), boundary(True)
    from generators.boundary_rows import _PHASE_COUNTERS
    for k in ("bases", "bases_available", "boundaries", "evaluations", "budget_exhausted", *_PHASE_COUNTERS):
        assert plain[k] == with_rows[k], k
    assert with_rows["extra_bases"] >= 1 and plain["extra_bases"] == 0


def test_the_extra_search_counts_apart_from_the_first():
    from generators import boundary_rows as br
    unit = _unit("diag")
    base = [{"inputs": {"g_st": 0, "g_sts": 0, "g_brk": 0, "g_spd": 0, "g_tm": 0}, "strategy": "BV_MID"}]
    alone = br.find_boundaries(unit, base, DIAG, DIAG_OUT)["report"]
    scen = [{"inputs": r["inputs"], "strategy": "SCN"} for r in sr.find_scenarios(unit, DIAG, DIAG_OUT)["rows"]]
    both = br.find_boundaries(unit, base, DIAG, DIAG_OUT, extra_bases=scen)["report"]
    for k in br._PHASE_COUNTERS:
        assert both[k] == alone[k], k
    assert any(both["extra_" + k] for k in br._PHASE_COUNTERS)   # the second search had its own to count


def test_a_stub_return_input_of_the_unit_is_searched():
    unit = _seq_unit("called", input_vars=["g_err", "ext() return"], output_vars=["g_o", "g_err"],
                     param_types={"g_err": "U8", "g_o": "U8"})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    # every target reached on one path: behind `ext() == 3` only with the stub value set (the MC/DC row {0, 3} may be the
    #   one — a scenario equal to it is a duplicate, not a new row)
    rep = unit["scenario_rows"]
    assert rep["reached_clean"] == rep["targets"] and rep["inputs"] == 2
    assert any(s["inputs"].get("ext() return") == 3 and s["expected"].get("g_o") == 7 for s in seqs)


def test_a_bit_input_written_as_hex_is_one_value_for_duplicates_and_covered_rows():
    # a bool / bit input's rows hold "0x0" — the search reads them as the integers they are (review R78 R2 C-R2-1: the
    #   second search re-added existing rows, one as FI, and counted 10 targets as newly reached)
    import json

    from generators.boundary_rows import _as_int
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    unit["param_types"] = dict(unit["param_types"], g_brk="BOOL")
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)

    def key(s):
        return json.dumps({k: _as_int(v) for k, v in s["inputs"].items()}, sort_keys=True)
    others = {key(s) for s in seqs if not s["strategy"].startswith((sr.SCENARIO_PREFIX, sr.SCENARIO_FI_PREFIX))}
    scen = [key(s) for s in seqs if s["strategy"].startswith((sr.SCENARIO_PREFIX, sr.SCENARIO_FI_PREFIX))]
    assert scen and len(set(scen)) == len(scen) and not set(scen) & others
    plain = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    generate_sequences(plain, None, type_cache={}, extended=True)
    for k in ("outside_design_searched", "outside_design_reached"):
        assert unit["scenario_rows"][k] == plain["scenario_rows"][k], k


def test_a_value_moved_home_stays_home_though_an_output_no_longer_derives():
    # {g_x: 31, g_y: 0} is an existing robustness-like row; `g_t = 1U` needs g_y > 2 only — g_x = 10 reaches it too, though
    #   `g_o = g_hw2` then no longer derives: the row keeps g_x home (review R78 R2 W-R2-3)
    home = {"g_x": (0, 20), "g_y": (0, 5)}
    found = sr.find_scenarios(_unit("pq"), {"g_x": U8, "g_y": U8}, ["g_t", "g_o"], existing=[{"g_x": 31, "g_y": 0}],
                              home=home)
    rows = [r for r in found["rows"] if r["target_text"] == "g_t = 1U;"]
    assert rows and all(home[k][0] <= v <= home[k][1] for r in rows for k, v in r["inputs"].items())
    sign = sr.find_scenarios(_unit("sign"), {"g_slope": S16}, ["g_o"])["report"]
    assert sign["reached_clean"] == sign["targets"] and sign["needed_inputs"] == {}   # read but reached: not needed


def test_the_comparisons_outside_the_home_range_keep_their_places_under_the_cap():
    # home 0~20 holds more than the cap's room; `g_tt > 30U` still offers 30 · 31 · 29 — not the type's end
    #   (review R78 R2 W-R2-4)
    stats: dict = {}
    pools, _d = _pools("pcap", {"g_tt": U16, "g_m": U8})
    unit = _unit("pcap")
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "pcap", unit["project_scope"])
    homed, _h = sr.operating_pools(unit, {"g_tt": U16, "g_m": U8}, fn, raw, unit["project_scope"], stats,
                                   home={"g_tt": (0, 20)})
    assert {30, 31, 29} <= set(homed["g_tt"]) and len(homed["g_tt"]) <= sr.MAX_POOL and stats["pools_capped"] >= 1
    assert homed["g_tt"][-2:] == [0, 65535] or {0, 65535} <= set(homed["g_tt"])
    found = sr.find_scenarios(unit, {"g_tt": U16, "g_m": U8}, ["g_o"], home={"g_tt": (0, 20)})
    row = next(r for r in found["rows"] if r["target_text"] == "g_o = 9U;")
    assert row["inputs"]["g_tt"] == 31


@pytest.mark.parametrize("climb", [1, 2, 24])
def test_every_unreached_target_has_one_reason(monkeypatch, climb):
    # a target a later row reaches loses the reason its own search gave (review R78 R2 W-R2-5); a branch evaluated with
    #   an undetermined value is reached uncleanly, and what it read is needed (W-R2-2)
    monkeypatch.setattr(sr, "MAX_CLIMB", climb)
    rep = sr.find_scenarios(_unit("lu"), {"g_la": U8, "g_lb": U8, "g_lc": U8}, ["g_o", "g_o2"])["report"]
    assert rep["reached_clean"] + rep["reached_unclean_only"] + rep["not_reached"] == rep["targets"]
    assert rep["local_best"] + rep["climb_cap"] + rep["budget_cut"] == rep["not_reached"]
    assert "g_lw" in rep["needed_inputs"]


def test_the_reasons_are_told_apart(monkeypatch):
    never = sr.find_scenarios(_unit("never"), {"g_p": S16}, ["g_o"])["report"]
    assert never["local_best"] == 2 and never["not_reached"] == 2   # `g_o = 1U` and the && true: no move gets nearer
    monkeypatch.setattr(sr, "MAX_CLIMB", 0)     # no move at all: what the starts do not reach is cut by the cap
    capped = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)["report"]
    assert capped["climb_cap"] >= 1 and capped["local_best"] == 0 \
        and capped["climb_cap"] + capped["budget_cut"] == capped["not_reached"]


def test_a_switch_label_moves_only_the_switched_input():
    # `default:` under `switch (g_st)` — the climb moves g_st alone, not every input (the case step of the control chain)
    many = {"g_st": U8, "g_sts": U8, "g_brk": U8, "g_spd": U16, "g_tm": U16, "g_p": S16, "g_q": S16}
    rep = sr.find_scenarios(_unit("sw"), many, ["g_o"])["report"]
    assert rep["reached_clean"] == rep["targets"] and rep["runs"] <= 2 * sr.MAX_POOL
    from generators import mcdc_design as md
    raw = UNIT.encode()
    start = UNIT.index("g_o = 0U;")
    node = cpc.shared_parser().parse(raw).root_node.descendant_for_byte_range(start, start + 3)
    while node.type != "expression_statement":
        node = node.parent
    steps = md.control_steps(node, cases=True)
    assert [s[0] for s in steps] == ["case"] and md.control_steps(node) == []


def test_the_second_search_labels_each_row_by_what_it_carries(monkeypatch):
    # a second-search row inside every design range is a scenario the first search missed (SCN, numbered after the
    #   first's), one outside a range is FI (SCNR, numbered on its own) — review R78 R2 U5 · U23 · U24
    import generators.suts as suts_mod
    real = suts_mod.find_scenarios

    def second(unit, domains, outputs, existing=None, **kw):
        if "home" not in kw:
            return real(unit, domains, outputs, existing, **kw)
        row = {"target_kind": "statement", "target_line": 1, "target_text": "x;", "target_outcome": None,
               "targets_reached": 1, "outputs_derived": 1}
        vec = {"g_st": 0, "g_sts": 3, "g_brk": 0, "g_spd": 501}
        return {"rows": [{**row, "inputs": {**vec, "g_tm": 31}}, {**row, "inputs": {**vec, "g_tm": 12}},
                         {**row, "inputs": {**vec, "g_tm": 40}}],
                "reached_vectors": [], "report": {"targets": 5, "covered_before": 2, "reached_clean": 5, "runs": 7,
                                                  "status": "searched", "pools_capped": 2, "starts_capped": 3,
                                                  "not_reached": 1, "reached_unclean_only": 1, "cut": 4,
                                                  "duplicates": 6, "steps": 99, "budget_exhausted": True}}
    monkeypatch.setattr(suts_mod, "find_scenarios", second)
    monkeypatch.setattr(sr, "MAX_ROWS", 1)     # the first search leaves targets so the second one runs
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    first = [s["strategy"] for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX)][:rep["rows"] + rep["expose_rows"]]
    tail = [(s["strategy"], s["inputs"]["g_tm"]) for s in seqs[-3:]]
    assert tail == [("SCNR_0", 31), (f"SCN_{len(first)}", 12), ("SCNR_1", 40)]
    assert rep["outside_design_rows"] == 2 and rep["outside_design_in_range_rows"] == 1
    assert rep["outside_design_searched"] == 3 and rep["outside_design_reached"] == 3 and rep["outside_design_runs"] == 7
    assert (rep["outside_design_pools_capped"], rep["outside_design_starts_capped"], rep["outside_design_not_reached"],
            rep["outside_design_cut"], rep["outside_design_duplicates"], rep["outside_design_steps"]) == (2, 3, 2, 4, 6, 99)
    assert rep["outside_design_budget_exhausted"] is True
    assert "설계 범위 밖" not in seqs[-2]["description"] and "설계 범위 밖" in seqs[-1]["description"]


def test_a_failing_first_search_drops_only_its_own_rows(monkeypatch):
    import generators.suts as suts_mod
    real = suts_mod._scenario_row

    def boom(sequences, row, strategy, *a, **k):
        real(sequences, row, strategy, *a, **k)
        raise RuntimeError("x")
    monkeypatch.setattr(suts_mod, "_scenario_row", boom)
    unit = _seq_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert not any(s["strategy"].startswith((sr.SCENARIO_PREFIX, sr.SCENARIO_FI_PREFIX)) for s in seqs)
    assert unit["scenario_rows"] == {"error": "RuntimeError", "rows": 0}


def test_a_name_only_the_search_needs_counts_at_the_round_cap(monkeypatch):
    import generators.suts as suts_mod
    from generators.suts import complete_source_read_inputs, summarize_source_read_inputs
    monkeypatch.setattr(suts_mod, "_SOURCE_READ_ROUNDS", 0)
    unit = _seq_unit("hidden", input_vars=["g_sts"], output_vars=["g_o"], param_types={"g_sts": "U8", "g_o": "U8"})

    def gen():
        return generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    complete_source_read_inputs(unit, gen(), gen)
    rec = unit["source_read_inputs"]
    assert rec["round_cap_reached"] and "s_gate" in rec["names_beyond_cap"]
    monkeypatch.setattr(suts_mod, "_SOURCE_READ_ROUNDS", 8)
    unit2 = _seq_unit("hidden", input_vars=["g_sts"], output_vars=["g_o"], param_types={"g_sts": "U8", "g_o": "U8"})

    def gen2():
        return generate_sequences(unit2, None, type_cache={}, extended=True, boundary_rows=False)
    complete_source_read_inputs(unit2, gen2(), gen2)
    assert summarize_source_read_inputs([unit2])["names_added_by_scenario_search"] == 1


def test_the_summary_counts_both_searches():
    reports = [{"scenario_rows": {"status": "searched", "rows": 0, "outside_design_rows": 1}},
               {"scenario_rows": {"status": "searched", "rows": 0, "outside_design_in_range_rows": 1}},
               {"scenario_rows": {"status": "searched", "rows": 0, "outside_design_budget_exhausted": True}},
               {"scenario_rows": {"status": "searched", "rows": 0, "outside_design_error": "KeyError"}}]
    got = summarize_scenario_rows(reports)
    assert got["units_with_rows"] == 2 and got["budget_exhausted"] == 1 and got["errors"] == 1


def test_the_extra_boundary_flags_are_their_own(monkeypatch):
    from generators import boundary_rows as br
    unit = _unit("diag")
    base = [{"inputs": {"g_st": 0, "g_sts": 0, "g_brk": 0, "g_spd": 0, "g_tm": 0}, "strategy": "BV_MID"}]
    scen = [{"inputs": r["inputs"], "strategy": "SCN"} for r in sr.find_scenarios(unit, DIAG, DIAG_OUT)["rows"]]
    monkeypatch.setattr(br, "MAX_EXTRA_EVALUATIONS", 3)
    got = br.find_boundaries(unit, base, DIAG, DIAG_OUT, extra_bases=scen)["report"]
    assert got["extra_evaluation_budget_exhausted"] and not got["evaluation_budget_exhausted"] \
        and not got["budget_exhausted"]
    monkeypatch.setattr(br, "MAX_EXTRA_EVALUATIONS", 1500)
    monkeypatch.setattr(br, "MAX_EXTRA_BOUNDARIES", 1)
    got = br.find_boundaries(unit, base, DIAG, DIAG_OUT, extra_bases=scen)["report"]
    assert got["extra_boundary_cap_reached"] and not got["boundary_cap_reached"] and got["extra_boundaries"] == 1
    only = br.find_boundaries(unit, [], DIAG, DIAG_OUT, extra_bases=scen)
    assert only["report"]["status"] == "searched" and only["report"]["bases"] == 0 and only["rows"]


def test_the_start_and_condition_cuts_are_counted(monkeypatch):
    monkeypatch.setattr(sr, "MAX_STARTS", 1)
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT,
                            [{"g_st": i, "g_sts": 0, "g_brk": 0, "g_spd": 0, "g_tm": 0} for i in range(4)])["report"]
    assert rep["starts_capped"] == 3
    monkeypatch.setattr(sr, "MAX_ATOMS", 0)
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT)["report"]
    assert rep["conditions_outcome_only"] == 2          # the AND and the timer comparison (a switch is no condition)


def test_the_covered_rows_check_is_no_part_of_the_budget(monkeypatch):
    # ten covered rows reaching nothing new, a budget of five runs: the check runs outside it and the search still runs
    #   (review R78 R2 I-R2-1 — a unit of hundreds of rows spent the budget on them)
    monkeypatch.setattr(sr, "MAX_RUNS", 5)
    covered = [{"g_st": 9, "g_sts": i, "g_brk": 9, "g_spd": 0, "g_tm": 0} for i in range(10)]
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT, covered=covered)["report"]
    assert rep["runs"] > 11 and rep["covered_before"] >= 1


def test_runs_count_only_what_ran(monkeypatch):
    # a step budget of 1: the first run stops on it, the rest are never run (`search_step_budget`) — not counted
    monkeypatch.setattr(sr, "MAX_STEPS", 1)
    rep = sr.find_scenarios(_unit("diag"), DIAG, DIAG_OUT,
                            [{"g_st": i, "g_sts": 0, "g_brk": 0, "g_spd": 0, "g_tm": 0} for i in range(5)])["report"]
    assert rep["runs"] == 1 and rep["budget_exhausted"]


def test_a_design_value_list_is_counted_as_not_widened():
    unit = _lvl_unit()
    unit["uds_param_info"] = dict(unit["uds_param_info"], g_lvl={"values": [0, 1, 2]})
    generate_sequences(unit, None, type_cache={}, extended=True)
    assert unit["bounds_source"]["g_lvl"] == "uds_values" and unit["scenario_rows"]["outside_design_value_sets"] == 1


def test_an_input_typed_only_by_its_name_is_no_search_input():
    unit = _seq_unit(input_vars=["g_st", "g_sts", "g_brk", "g_spd", "g_tm", "u8x_guess"])
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert not any("u8x_guess" in s["inputs"] for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX))


def test_a_label_past_the_design_range_keeps_its_place_under_the_cap():
    # home 0~3 plus seven body constants: over the cap — label 6 stays a candidate and the free slots are filled
    #   (review R78 R3 W-R3-1: the pool kept 5 of 12 values and lost the label)
    stats: dict = {}
    unit = _unit("big")
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "big", unit["project_scope"])
    pools, _d = sr.operating_pools(unit, {"g_lv": U8, "g_t": U8}, fn, raw, unit["project_scope"], stats,
                                   home={"g_lv": (0, 3)})
    assert 6 in pools["g_lv"] and len(pools["g_lv"]) == sr.MAX_POOL and stats["pools_capped"] >= 1
    found = sr.find_scenarios(unit, {"g_lv": U8, "g_t": U8}, ["g_o", "g_t"], home={"g_lv": (0, 3)})
    assert any(r["inputs"]["g_lv"] == 6 for r in found["rows"])


def test_a_label_past_the_design_range_is_reserved_ahead_of_the_comparison_constants():
    # three comparisons past the home range fill the capped pool's reserved places — the label 6 is reserved with them,
    #   not left to the free slots (none are left) (review R78 R3 W-R3-1; self-check: label reservation removed)
    stats: dict = {}
    unit = _unit("big2")
    raw = unit["source_text"].encode()
    from generators.c_source_oracle import _parsed_function
    _r, fn, _s = _parsed_function(cpc.shared_parser(), raw, "big2", unit["project_scope"])
    pools, _d = sr.operating_pools(unit, {"g_lw": U8}, fn, raw, unit["project_scope"], stats, home={"g_lw": (0, 3)})
    assert 6 in pools["g_lw"] and {30, 40, 50} <= set(pools["g_lw"]) and len(pools["g_lw"]) == sr.MAX_POOL
    found = sr.find_scenarios(unit, {"g_lw": U8}, ["g_o", "g_t"], home={"g_lw": (0, 3)})
    assert any(r["inputs"]["g_lw"] == 6 for r in found["rows"])


def test_polish_brings_an_input_home_through_the_home_range_points_the_pool_did_not_keep():
    # g_pt must leave its home range (> 30); g_pa's capped pool keeps one home value, 12, where the division is by zero —
    #   the climb takes g_pa = 30. Polish moves it home through the range's own points (5 works), not only the pool's
    #   (review R78 R3 I-R3-5; self-check: polish takes the pool's home values only)
    unit = _unit("polish")
    found = sr.find_scenarios(unit, {"g_pa": U8, "g_pt": U8}, ["g_o", "g_pp"],
                              home={"g_pa": (5, 20), "g_pt": (0, 20)})
    rows = [r for r in found["rows"] if r["target_text"].startswith("g_o = (U8)(100U")]
    assert rows and all(r["inputs"]["g_pt"] > 30 and 5 <= r["inputs"]["g_pa"] <= 20 and r["inputs"]["g_pa"] != 12
                        for r in rows)


def test_the_second_search_counts_the_first_search_rows_as_covered():
    # a target a first-search row reaches is never searched again — each scenario row has its own target
    #   (self-check: the first search's rows left out of the second search's covered rows)
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    assert rep["outside_design_runs"] > 0
    first = [s["scenario"] for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX)
             and int(s["strategy"][len(sr.SCENARIO_PREFIX):]) < rep["rows"] + rep["expose_rows"]]
    second = [s["scenario"] for s in seqs if s["strategy"].startswith(sr.SCENARIO_FI_PREFIX)
              or (s["strategy"].startswith(sr.SCENARIO_PREFIX)
                  and int(s["strategy"][len(sr.SCENARIO_PREFIX):]) >= rep["rows"] + rep["expose_rows"])]
    key = lambda sc: (sc["target_kind"], sc["target_line"], sc["target_outcome"])  # noqa: E731
    assert first and not {key(sc) for sc in first} & {key(sc) for sc in second}
    assert rep["outside_design_searched"] < rep["targets"] - rep["covered_before"]


def test_the_second_search_starts_from_the_first_search_rows(monkeypatch):
    # the second search's climb starts are its first `MAX_STARTS` existing rows: the first search's operating vectors
    #   lead them, and they are covered rows (review R78 R3 I-R3-1; self-check: the first search's rows left out)
    import generators.suts as suts_mod
    calls = []
    real = suts_mod.find_scenarios

    def spy(unit, domains, outputs, existing=None, **kw):
        calls.append((list(existing or []), list(kw.get("covered") or []), "home" in kw))
        return real(unit, domains, outputs, existing, **kw)
    monkeypatch.setattr(suts_mod, "find_scenarios", spy)
    unit = _seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["scenario_rows"]
    first = [s["inputs"] for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX)][:rep["rows"] + rep["expose_rows"]]
    second = [c for c in calls if c[2]]
    assert first and second
    existing, covered, _home = second[-1]
    assert existing[:len(first)] == first and all(v in covered for v in first)


def test_the_robustness_scenario_bases_have_their_own_limit(monkeypatch):
    # robustness takes at most `MAX_ROBUST_SCENARIO_BASES` scenario rows as bases, counted apart from the other bases:
    #   with the one scenario row where the comparison is live put last, a limit one short of the scenario rows finds
    #   the comparison not live (its rows then stand on the first base) (self-check: every base counted as a
    #   non-scenario one — the scenario bases had no limit)
    import generators.suts as suts_mod
    seen = {}
    real = suts_mod._append_robustness_rows

    def spy(unit, sequences, *args):
        seen["call"] = (dict(unit), [dict(s) for s in sequences], args)
        return real(unit, sequences, *args)
    monkeypatch.setattr(suts_mod, "_append_robustness_rows", spy)
    generate_sequences(_seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}}), None, type_cache={}, extended=True)
    unit, seqs, args = seen["call"]
    monkeypatch.setattr(suts_mod, "MAX_ROBUST_BASES", 0)         # only the scenario rows are bases

    def live(order, limit):
        monkeypatch.setattr(suts_mod, "MAX_ROBUST_SCENARIO_BASES", limit)
        u = dict(unit)
        real(u, [dict(s) for s in order], *args)
        return u["robustness_rows"]["live"]
    scen = [s for s in seqs if s["strategy"].startswith(sr.SCENARIO_PREFIX)]
    rest = [s for s in seqs if not s["strategy"].startswith(sr.SCENARIO_PREFIX)]
    hot = [i for i, s in enumerate(scen) if live(rest + [s], 1)]
    assert len(scen) >= 2 and len(hot) == 1
    order = rest + [s for i, s in enumerate(scen) if i not in hot] + [scen[hot[0]]]
    assert live(order, len(scen)) == 1 and live(order, len(scen) - 1) == 0


def test_the_search_goes_on_past_the_row_cap(monkeypatch):
    # no row may be added: the targets are still climbed — their objects are still needed and a duplicate still counts
    #   (review R78 R3 W-R3-2)
    first = sr.find_scenarios(_unit("sign"), {"g_slope": S16}, ["g_o"])
    monkeypatch.setattr(sr, "MAX_ROWS", 0)
    rep = sr.find_scenarios(_unit("hidden"), {"g_sts": U8}, ["g_o"])["report"]
    assert rep["rows"] == 0 and rep["cut"] >= 1 and rep["needed_inputs"] == {"s_gate": 4}
    assert rep["local_best"] + rep["climb_cap"] + rep["budget_cut"] + rep["cut"] == rep["not_reached"]
    dup = sr.find_scenarios(_unit("sign"), {"g_slope": S16}, ["g_o"], [r["inputs"] for r in first["rows"]])["report"]
    assert dup["reached_clean"] == dup["targets"] and dup["cut"] == 0


def test_rows_written_as_hex_are_duplicates():
    first = sr.find_scenarios(_unit("sign"), {"g_slope": S16}, ["g_o"])
    hexed = [{k: (hex(v) if v >= 0 else v) for k, v in r["inputs"].items()} for r in first["rows"]]
    again = sr.find_scenarios(_unit("sign"), {"g_slope": S16}, ["g_o"], hexed)
    assert again["rows"] == [] and again["report"]["duplicates"] == len(first["rows"])


def test_no_second_search_after_a_refused_first_one(monkeypatch):
    import generators.suts as suts_mod
    calls = []

    def refused(unit, domains, outputs, existing=None, **kw):
        calls.append(kw)
        return {"rows": [], "reached_vectors": [],
                "report": {"status": "oracle_unsupported:x", "targets": 5, "reached_clean": 0, "rows": 0}}
    monkeypatch.setattr(suts_mod, "find_scenarios", refused)
    generate_sequences(_seq_unit(uds_param_info={"g_tm": {"range": [0, 20]}}), None, type_cache={}, extended=True)
    assert calls and all("home" not in kw for kw in calls)


def test_every_counter_reaches_the_disclosure():
    from generators.suts import SCENARIO_REPORT_KEYS
    from report_gen.generation_disclosures import build_disclosures
    base = {**dict.fromkeys(SCENARIO_REPORT_KEYS, 0), "rows": 3, "targets": 20, "reached_clean": 17, "units": 4,
            "searched": 3, "units_with_rows": 2, "budget_exhausted": 0, "errors": 0, "not_searched": {},
            "cap_per_unit": 16}

    def item(**kw):
        return {i["key"]: i for i in build_disclosures("suts", {"scenario_rows": {**base, **kw}})}["suts_scenario_rows"]
    first = item()
    assert first["value"] == ("3행(세 탐색) · 문장 · 분기 결과 17/20 에 설계 범위 안 값으로 한 경로로 닿음 · 탐색한 unit 3/4 "
                              "(행이 붙은 unit 2)")
    shown_in_value = {"rows", "targets", "reached_clean"}
    silent = [k for k in SCENARIO_REPORT_KEYS if k not in shown_in_value
              and (item(**{k: 7})["note"], item(**{k: 7})["value"]) == (first["note"], first["value"])]
    assert silent == []
    assert item(errors=1)["tone"] == "warning" and "오류로 시나리오 행 없이" in item(errors=1)["note"]
    assert item(budget_exhausted=2)["tone"] == "warning" and first["tone"] == "info"
    assert "no_targets" in item(not_searched={"no_targets": 2})["note"]
    assert "suts_scenario_rows" not in {i["key"] for i in build_disclosures("suts", {})}   # reference profile: no item


def test_the_summary_carries_every_report_key():
    unit = _seq_unit()
    generate_sequences(unit, None, type_cache={}, extended=True)
    got = summarize_scenario_rows([unit, {"scenario_rows": {"status": "no_targets"}}])
    for key in ("targets", "reached_clean", "rows", "cut", "runs", "searched", "units_with_rows", "not_searched"):
        assert key in got
    assert got["searched"] == 1 and got["not_searched"] == {"no_targets": 1} and got["rows"] == unit["scenario_rows"]["rows"]
