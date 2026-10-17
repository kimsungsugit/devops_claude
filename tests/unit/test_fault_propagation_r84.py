"""R84 — fault-propagating rows of the extended SUTS (`scenario_rows.find_scenarios(propagate=True)`,
`suts._append_propagation_rows`).

Exposing a fault at its site (R79) is not yet seeing it in an output. Of the 20 KJPDS02_PV mutants neither the reference
nor the generated rows killed after R83 the rows ran each site with exposing values, but the changed value died on the
way: a timer at its limit whose other branch writes the state the row already held, a clamp multiplied by a difference
of two inputs the rows held equal, a threshold picked from two inputs the rows held equal, a divisor arm only values
outside the design reach (the second search had no exposing targets — R79 review W3). A propagating target is met only
where changing the site's value (a data-state perturbation — the comparison negated, at its boundary point for a
boundary target; the write left out; ``+`` ``-`` ``*`` with the right operand at the identity; ``/`` ``%`` one step
off) changes an output both runs derive. No mutant of the measuring tool is made or consulted. Values are what C
computes on the oracle's 16-bit-int target."""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators import scenario_rows as sr
from generators import suts
from generators.c_source_oracle import observe_decisions
from generators.suts import (
    PROPAGATE_FI_PREFIX,
    PROPAGATE_PREFIX,
    PROPAGATION_REPORT_KEYS,
    generate_sequences,
    is_extended_strategy,
    resolve_seq_gen_method,
    resolve_seq_test_method,
    summarize_propagation_rows,
)

ROOT = os.path.join(os.sep, "proj_r84")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef signed long S32;
#define TMAX 65535U
#define LIMIT 10U
#endif
"""
UNIT = """#include "common.h"
U16 g_tm;
U8 g_st;
U8 g_det;
U16 g_peak;
U16 g_maxs;
U16 g_max;
U8 g_dev;
S16 g_roll;
U8 g_out;
U8 g_in;
U8 g_tmp;
U16 timer(void)
{
    U16 r;
    r = 0U;
    if (g_det == 1U)
    {
        g_tm = 0U;
        g_st = 1U;
        r = 4U;
    }
    else
    {
        if (g_tm < TMAX)
        {
            g_tm++;
        }
        if (g_tm > LIMIT)
        {
            g_tm = 0U;
            g_st = 0U;
        }
    }
    return r;
}
S32 hold(S16 now, S16 endv, S16 start, S16 assist)
{
    S32 diff;
    S32 y;
    S32 res;
    diff = (S32)assist - (S32)start;
    res = (S32)start;
    if (endv > 0)
    {
        y = ((S32)now * 100L) / (S32)endv;
        if (y > 100L)
        {
            y = 100L;
        }
        res = ((diff * y) / 100L) + (S32)start;
    }
    return res;
}
void thr(void)
{
    U8 slope;
    slope = 0U;
    if (((g_dev == 3U) || (g_dev == 9U)) && (g_roll >= 2))
    {
        slope = 1U;
    }
    if (slope == 1U)
    {
        g_peak = g_maxs;
    }
    else
    {
        g_peak = g_max;
    }
}
S32 divr(S32 num, S32 den)
{
    S32 res;
    if (den > 0L)
    {
        res = (num + (den / 2L)) / den;
    }
    else
    {
        if (num >= 0L)
        {
            res = (num - (den / 2L)) / den;
        }
        else
        {
            res = (num + (den / 2L)) / den;
        }
    }
    return res;
}
U8 g_acc;
S32 lin(S32 a, S32 b)
{
    g_acc += 2U;
    return (a - b) + (a * b);
}
U8 g_buf;
U8 g_res;
U16 g_a;
U16 g_b;
U16 g_k;
U16 g_o;
U8 g_t;
void mask(void)
{
    if (g_b == 3U)
    {
        g_t = 1U;
    }
    g_k = 5U;
    g_o = (U16)((g_k - 5U) * (U16)(g_a - g_b));
}
U8 pchk(U8 *p)
{
    U8 r;
    if ((p != 0) && (g_in > 3U))
    {
        r = p[0];
    }
    else
    {
        r = 0U;
    }
    return r;
}
void ptrcmp(void)
{
    U8 *q;
    q = &g_buf;
    if ((q != 0) && (g_in > 3U))
    {
        g_res = 1U;
    }
    else
    {
        g_res = 2U;
    }
}
void dead(void)
{
    g_tmp = g_in;
    g_tmp = 3U;
    g_out = g_tmp;
}
"""
U8 = (0, 255)
U16 = (0, 65535)
S16 = (-32768, 32767)
_CACHE: dict = {}


def _unit(name):
    if "scope" not in _CACHE:
        files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
        context = cpc.build_project_context(files)
        _CACHE["scope"] = cpc.build_scopes(context, [os.path.join(ROOT, "unit.c")])[os.path.join(ROOT, "unit.c")]
    return {"name": name, "source_text": UNIT, "source_path": os.path.join(ROOT, "unit.c"), "source_text_complete": True,
            "project_scope": _CACHE["scope"]}


def _key(unit, text, kind):
    raw = unit["source_text"].encode()
    start = unit["source_text"].index(text)
    node = cpc.shared_parser().parse(raw).root_node.descendant_for_byte_range(start, start + len(text))
    while node.type != kind:
        node = node.parent
    return [node.start_byte, node.end_byte, node.type]


def _out(unit, vector, outs, perturb=None):
    run = observe_decisions(unit, [vector], [], outputs=outs, perturb=perturb)[0]
    assert run["status"] == "supported", run
    return {k: v.get("value") for k, v in run["outputs"].items()}


def _prop(found, kind, text=None):
    return [r for r in found["rows"] if r["target_kind"] == kind and (text is None or text in r["target_text"])]


# ── the oracle changes one site's value ─────────────────────────────────────────────────────────────────────────

def test_a_boundary_flip_changes_the_comparison_only_where_its_sides_are_equal():
    unit = _unit("timer")
    key = _key(unit, "g_tm < TMAX", "binary_expression")
    at = {"g_det": 0, "g_tm": 65535, "g_st": 1}
    assert _out(unit, at, ["g_st", "g_tm"]) == {"g_st": 0, "g_tm": 0}
    # `<` taken where 65535 == 65535: g_tm wraps to 0, `0 > 10` fails, the state keeps what it held
    assert _out(unit, at, ["g_st", "g_tm"], ["flip_equal", key]) == {"g_st": 1, "g_tm": 0}
    off = {"g_det": 0, "g_tm": 5, "g_st": 1}
    assert _out(unit, off, ["g_st", "g_tm"], ["flip_equal", key]) == _out(unit, off, ["g_st", "g_tm"])


def test_a_flip_negates_a_comparison_on_every_evaluation():
    unit = _unit("thr")
    key = _key(unit, "g_dev == 9U", "binary_expression")
    v = {"g_dev": 0, "g_roll": 5, "g_maxs": 1, "g_max": 2}
    assert _out(unit, v, ["g_peak"]) == {"g_peak": 2}
    assert _out(unit, v, ["g_peak"], ["flip", key]) == {"g_peak": 1}
    # `9 == 9` negated too — the other outcome, whatever the values
    assert _out(unit, {**v, "g_dev": 9}, ["g_peak"], ["flip", key]) == {"g_peak": 2}


def test_a_left_out_write_keeps_the_value_the_object_held():
    unit = _unit("hold")
    key = _key(unit, "y = 100L", "assignment_expression")
    v = {"now": 5, "endv": 1, "start": 0, "assist": 10}
    assert _out(unit, v, ["return"]) == {"return": 10}
    assert _out(unit, v, ["return"], ["skip_write", key]) == {"return": 50}   # y stays 500


def test_drop_right_takes_the_identity_and_step_moves_a_quotient():
    unit = _unit("divr")
    v = {"num": 1, "den": -2}
    assert _out(unit, v, ["return"]) == {"return": -1}
    assert _out(unit, v, ["return"], ["drop_right", _key(unit, "num - (den / 2L)", "binary_expression")]) == \
        {"return": 0}                                                           # 1 / -2
    w = {"num": 4, "den": 2}
    assert _out(unit, w, ["return"]) == {"return": 2}
    assert _out(unit, w, ["return"], ["step", _key(unit, "(num + (den / 2L)) / den", "binary_expression")]) == \
        {"return": 3}
    hold = _unit("hold")
    mul = _key(hold, "(S32)now * 100L", "binary_expression")
    assert _out(hold, {"now": 5, "endv": 10, "start": 0, "assist": 100}, ["return"], ["drop_right", mul]) == \
        {"return": 0}                                                           # y = 5 / 10 instead of 500 / 10


def test_without_a_perturbation_or_at_another_site_the_run_is_the_plain_one():
    unit = _unit("divr")
    v = {"num": 7, "den": 3}
    plain = observe_decisions(unit, [v], [], outputs=["return"])[0]
    elsewhere = observe_decisions(unit, [v], [], outputs=["return"],
                                  perturb=["drop_right", _key(unit, "num - (den / 2L)", "binary_expression")])[0]
    assert elsewhere["outputs"] == plain["outputs"] and elsewhere["steps"] == plain["steps"]
    # a kind that does not fit the operator changes nothing
    assert _out(unit, v, ["return"], ["flip", _key(unit, "(num + (den / 2L)) / den", "binary_expression")]) == \
        _out(unit, v, ["return"])


# ── the search: a met exposure that no output shows is one step from its target ────────────────────────────────

def test_a_masked_boundary_gets_a_row_whose_other_branch_shows():
    # every suite row reaching `g_tm < TMAX` with 65535 holds g_st 0 — what the other branch writes
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 0}, {"g_det": 0, "g_tm": 5, "g_st": 0}, {"g_det": 1, "g_tm": 0, "g_st": 0}]
    doms = {"g_det": U8, "g_tm": U16, "g_st": U8}
    plain = sr.find_scenarios(_unit("timer"), doms, ["g_tm", "g_st", "return"], old, covered=old)
    assert not any(r["inputs"]["g_tm"] == 65535 and r["inputs"]["g_st"] for r in plain["rows"])
    found = sr.find_scenarios(_unit("timer"), doms, ["g_tm", "g_st", "return"], old, covered=old, propagate=True)
    rows = _prop(found, "boundary", "g_tm < TMAX")
    assert rows and rows[0]["inputs"]["g_tm"] == 65535 and rows[0]["inputs"]["g_st"] != 0
    assert rows[0]["inputs"]["g_det"] != 1 and "g_st" in rows[0]["propagated"]
    rep = found["report"]
    assert rep["targets"] == 0 and rep["expose_targets"] == rep["expose_boundary"] + rep["expose_flip"] + \
        rep["expose_write"] + rep["expose_arith"]
    assert rep["expose_reached"] + rep["expose_not_reached"] == rep["expose_targets"]
    assert rep["propagate_perturbed_runs"] > 0 and rep["propagate_checked_rows"] > 0


def test_a_product_masked_by_equal_inputs_gets_them_apart():
    old = [{"now": 5, "endv": 1, "start": 7, "assist": 7}, {"now": 0, "endv": 1, "start": 7, "assist": 7}]
    doms = {k: S16 for k in ("now", "endv", "start", "assist")}
    unit = _unit("hold")
    found = sr.find_scenarios(unit, doms, ["return"], old, covered=old, propagate=True)
    # the clamp's write is met by a row of this search (the first one that also clamps may be another target's) —
    #   with the two inputs apart, and leaving the write out then changes the result
    clamps = [r["inputs"] for r in found["rows"] if r["inputs"]["now"] > r["inputs"]["endv"] > 0]
    assert clamps and clamps[0]["assist"] != clamps[0]["start"]
    key = _key(unit, "y = 100L", "assignment_expression")
    assert _out(unit, clamps[0], ["return"], ["skip_write", key]) != _out(unit, clamps[0], ["return"])
    for v in old:   # the suite's rows clamp too, and leaving the write out changes nothing there
        assert _out(unit, v, ["return"], ["skip_write", key]) == _out(unit, v, ["return"])


def test_a_condition_flip_needs_the_two_arms_to_differ():
    # observable MC/DC: `g_dev == 9U` decides (g_dev not 3, g_roll >= 2), but both arms hand the same value on
    old = [{"g_dev": 3, "g_roll": 5, "g_maxs": 50, "g_max": 50}, {"g_dev": 0, "g_roll": 5, "g_maxs": 50, "g_max": 50},
           {"g_dev": 9, "g_roll": 0, "g_maxs": 50, "g_max": 50}]
    doms = {"g_dev": U8, "g_roll": S16, "g_maxs": U16, "g_max": U16}
    found = sr.find_scenarios(_unit("thr"), doms, ["g_peak"], old, covered=old, propagate=True)
    rows = _prop(found, "flip", "g_dev == 9U")
    assert rows and rows[0]["exposure"] == [v0 := rows[0]["inputs"]["g_dev"], 9] and v0 != 3   # where it decides
    v = rows[0]["inputs"]
    assert v["g_maxs"] != v["g_max"] and v["g_roll"] >= 2 and v["g_dev"] != 3
    assert found["report"]["expose_flip"] == 4   # every comparison of the two decisions


def test_a_row_of_the_suite_that_already_shows_it_is_enough():
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 1}, {"g_det": 0, "g_tm": 5, "g_st": 0}]
    found = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"],
                              old, covered=old, propagate=True)
    assert not _prop(found, "boundary", "g_tm < TMAX")
    assert found["report"]["expose_covered_before"] >= 1


def test_a_negative_divisor_arm_takes_a_divisor_whose_half_counts():
    # `den / 2L` is 0 for den -1: no operand shows there — the propagating search steps to -2 (s32_DivRound)
    found = sr.find_scenarios(_unit("divr"), {"num": (-1000, 1000), "den": (-1000, 1000)}, ["return"],
                              [{"num": 0, "den": -1}, {"num": -1, "den": -1}], covered=[{"num": 0, "den": -1}],
                              propagate=True)
    sub = [r for r in _prop(found, "arith", "num - (den / 2L)") if r.get("operator") == "-"]
    assert sub and sub[0]["inputs"]["den"] <= -2 and sub[0]["inputs"]["num"] >= 0
    flips = _prop(found, "flip", "num >= 0L")
    assert flips and flips[0]["inputs"]["den"] <= -2 and flips[0]["inputs"]["num"] != 0


def test_a_site_no_output_can_show_is_counted_not_rowed():
    # `g_tmp = g_in;` is overwritten before any read: its write exposes (g_in differs from what g_tmp held), never
    #   propagates — the next write does (`g_tmp = 3U` left out hands g_in on)
    old = [{"g_in": 5, "g_tmp": 0}]
    found = sr.find_scenarios(_unit("dead"), {"g_in": U8, "g_tmp": U8}, ["g_out"], old, covered=old, propagate=True)
    assert not _prop(found, "write", "g_tmp = g_in")
    rep = found["report"]
    assert rep["propagate_infected_only"] >= 1 and rep["expose_not_reached"] >= 1


def test_the_search_before_r84_is_unchanged_without_propagate():
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 0}]
    doms = {"g_det": U8, "g_tm": U16, "g_st": U8}
    a = sr.find_scenarios(_unit("timer"), doms, ["g_tm", "g_st", "return"], old, covered=old)
    assert "propagate_perturbed_runs" not in a["report"] and all("propagated" not in r for r in a["rows"])
    assert a["report"]["targets"] > 0


def test_the_suite_rows_checked_per_target_are_capped_and_counted(monkeypatch):
    # (review R84 I-R2-1) a capped check goes on in the target's own search, before any climb: the suite row that
    #   already shows the masked boundary covers it — no row spent on finding it again
    monkeypatch.setattr(sr, "MAX_PROPAGATE_CHECK", 0)
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 1}]
    found = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"],
                              old, covered=old, propagate=True)
    rep = found["report"]
    assert rep["propagate_check_capped"] >= 1 and rep["propagate_checked_rows"] == 0
    assert rep["propagate_check_late"] >= 1 and not _prop(found, "boundary", "g_tm < TMAX")
    assert rep["expose_covered_before"] >= rep["propagate_check_late"]


def test_the_budget_cuts_and_says_so(monkeypatch):
    monkeypatch.setattr(sr, "MAX_PROPAGATE_RUNS", 3)
    old = [{"now": 5, "endv": 1, "start": 7, "assist": 7}]
    found = sr.find_scenarios(_unit("hold"), {k: S16 for k in ("now", "endv", "start", "assist")}, ["return"], old,
                              covered=old, propagate=True)
    rep = found["report"]
    assert rep["expose_budget_exhausted"] and rep["expose_budget_cut"] >= 1


def test_a_perturbed_run_that_is_no_clean_run_shows_nothing():
    # dropping `den / 2L`'s divisor would be `den / 1` — fine; flipping `den > 0L` at den 0 runs `/ den` by zero
    unit = _unit("divr")
    run = observe_decisions(unit, [{"num": 1, "den": 0}], [], outputs=["return"],
                            perturb=["flip", _key(unit, "den > 0L", "binary_expression")])[0]
    assert run["status"] == "unsupported" and "division_by_zero" in run["reason"]


# ── the SUTS step ───────────────────────────────────────────────────────────────────────────────────────────────

def _seq_unit(**kw):
    unit = _unit("divr")
    unit.update({"fid": "F_divr", "input_vars": ["num", "den"], "output_vars": ["return"],
                 "param_types": {"num": "S32", "den": "S32", "return": "S32"}, "uds_param_info": {}})
    unit.update(kw)
    return unit


def test_the_extended_profile_appends_propagating_rows_last_and_keeps_every_row():
    plain_unit = _seq_unit(uds_param_info={"den": {"range": [1, 100]}})
    with pytest.MonkeyPatch.context() as m:
        m.setattr(suts, "_append_propagation_rows", lambda *_a, **_k: None)
        before = generate_sequences(plain_unit, None, type_cache={}, extended=True)
    unit = _seq_unit(uds_param_info={"den": {"range": [1, 100]}})
    after = generate_sequences(unit, None, type_cache={}, extended=True)
    assert len(after) > len(before)
    for a, b in zip(after, before, strict=False):   # the rows before are there unchanged (R75), in their order
        assert a["inputs"] == b["inputs"] and a["strategy"] == b["strategy"]
        assert all(a["expected"].get(k) == v for k, v in b["expected"].items())
    new = after[len(before):]
    assert all(str(s["strategy"]).startswith((PROPAGATE_PREFIX, PROPAGATE_FI_PREFIX)) for s in new)
    assert all(is_extended_strategy(s["strategy"]) and s["tc_profile"] == "extended" for s in new)
    fi = [s for s in new if str(s["strategy"]).startswith(PROPAGATE_FI_PREFIX)]
    # the negative-divisor arm: only values outside the design (1 ~ 100) reach it — an FI row that says so
    assert fi and all(int(s["inputs"]["den"]) < 1 for s in fi)
    assert all(resolve_seq_test_method(s["strategy"]) == resolve_seq_test_method("ROBUST_0") for s in fi)
    assert all("설계 범위 밖 결함 전파" in s["description"] and "설계 1~100 밖" in s["description"] for s in fi)
    assert all(resolve_seq_gen_method(s["strategy"]) == resolve_seq_gen_method("COND_COMB_0") for s in new)
    assert all(s["expected_evidence"]["return"]["status"] == "derived" for s in new)
    rep = unit["propagation_rows"]
    assert rep["status"] == "searched" and rep["fi_rows"] == len(fi) and rep["rows"] + rep["fi_rows"] == len(new)
    assert rep["targets"] == rep["covered_before"] + rep["met_by_rows"] + rep["not_met"]
    assert rep["outside_design_inputs"] == 1 and rep["outside_design_met"] >= 1


def test_the_reference_profile_has_no_propagating_rows():
    seqs = generate_sequences(_seq_unit(), 24, type_cache={})
    assert not any(str(s["strategy"]).startswith(("PROP", )) for s in seqs)


def test_a_failing_step_keeps_the_document_and_says_why(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("x")
    monkeypatch.setattr(suts, "_append_propagation_rows", boom)
    unit = _seq_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert seqs and not any(str(s["strategy"]).startswith(("PROP_", "PROPR_")) for s in seqs)
    assert unit["propagation_rows"] == {"error": "RuntimeError", "rows": 0, "fi_rows": 0}


def test_the_summary_adds_the_unit_reports():
    units = [{"propagation_rows": {**dict.fromkeys(PROPAGATION_REPORT_KEYS, 1), "status": "searched"}},
             {"propagation_rows": {"error": "X", "rows": 0, "fi_rows": 0}},
             {"propagation_rows": {**dict.fromkeys(PROPAGATION_REPORT_KEYS, 0), "status": "no_targets"}}, {}]
    out = summarize_propagation_rows(units)
    assert all(out[k] == 1 for k in PROPAGATION_REPORT_KEYS)
    assert out["units"] == 4 and out["searched"] == 1 and out["errors"] == 1 and out["units_with_rows"] == 1
    assert out["not_searched"] == {"no_targets": 1}
    assert out["cap_per_unit"] == sr.MAX_PROPAGATE_ROWS and out["check_per_target"] == sr.MAX_PROPAGATE_CHECK


def test_the_disclosure_says_what_was_changed_and_how_the_targets_add_up():
    from report_gen.generation_disclosures import build_disclosures
    pr = {**dict.fromkeys(PROPAGATION_REPORT_KEYS, 0), "targets": 10, "covered_before": 6, "met_by_rows": 3,
          "not_met": 1, "local_best": 1, "infected_only": 1, "rows": 2, "fi_rows": 1, "searched": 4,
          "units_with_rows": 2, "cap_per_unit": 16, "check_per_target": 48, "errors": 0, "budget_exhausted": 0}
    note = {i["key"]: i for i in build_disclosures("suts", {"propagation_rows": pr})}["suts_propagation_rows"]
    text = str(note)
    assert "2행 + 설계 범위 밖 FI 1행" in text and "목표 10 = 이미 있던 행이 만족 6 + 이 단계의 행이 만족 3 + 못 만족 1" in text
    assert "데이터 상태 섭동" in text and "상수 변이로 따로 본다" in text and "관측 가능 MC/DC" in text
    assert "suts_propagation_rows" not in {i["key"] for i in build_disclosures(
        "suts", {"propagation_rows": summarize_propagation_rows([])})}


# ── review R84 round 1 ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_target_the_row_cap_cut_is_no_infected_only_one(monkeypatch):
    # (review R84 W1) the masked boundary's row is found but the cap cuts it: cut, not "no move changed an output"
    monkeypatch.setattr(sr, "MAX_PROPAGATE_ROWS", 0)
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 0}]
    rep = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"], old,
                            covered=old, propagate=True)["report"]
    assert rep["expose_cut"] >= 1 and rep["propagate_infected_only"] == 0


def test_the_second_search_checks_this_steps_rows_first(monkeypatch):
    # (review R84 W2) the suite check stops at a cap per target: the first search's rows come first in the second's
    calls = []
    real = suts.find_scenarios
    row = {"inputs": {"num": 7, "den": 3}, "target_kind": "arith", "target_line": 1, "target_text": "x", "exposure": [7, 1],
           "operator": "+", "propagated": ["return"], "exposures_met": 1, "targets_reached": 0}

    def spy(unit, domains, outputs, existing=None, **kw):
        if not kw.get("propagate"):
            return real(unit, domains, outputs, existing, **kw)
        calls.append((kw, list(existing or ())))
        if len(calls) == 1:
            return {"rows": [row], "reached_vectors": [], "report": {
                "status": "searched", "expose_targets": 3, "expose_covered_before": 1, "expose_reached": 2,
                "expose_not_reached": 1, "expose_rows": 1, "propagate_check_capped": 2, "propagate_check_late": 1}}
        return {"rows": [], "reached_vectors": [], "report": {"status": "searched", "expose_targets": 3,
                                                               "expose_covered_before": 3, "expose_reached": 3,
                                                               "propagate_check_capped": 1, "propagate_check_late": 1}}
    monkeypatch.setattr(suts, "find_scenarios", spy)
    unit = _seq_unit(uds_param_info={"den": {"range": [1, 100]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert len(calls) == 2 and "home" in calls[1][0]
    covered = calls[1][0]["covered"]
    assert {k: int(v) for k, v in covered[0].items()} == {"num": 7, "den": 3}       # this step's row first
    assert len(covered) == len(seqs)                                                # then every row before it
    # (review R84 I-R2-4) the climb starts keep the scenario rows first, this step's row where it stands (last)
    assert {k: int(v) for k, v in calls[1][1][-1].items()} == {"num": 7, "den": 3} and calls[1][1] != covered
    rep = unit["propagation_rows"]
    assert (rep["targets"], rep["covered_before"], rep["met_by_rows"], rep["not_met"]) == (3, 1, 2, 0)
    assert rep["outside_design_searched"] == 0 and rep["outside_design_met"] == 0
    # (review R84 I-R3-2) each search's check cuts and late confirmations apart
    assert (rep["check_capped"], rep["check_late"], rep["outside_design_check_capped"],
            rep["outside_design_check_late"]) == (2, 1, 1, 1)


def test_every_value_left_outside_is_named():
    # (review R84 W3) a value-set input and a range input both outside: each says what it is outside of
    seqs: list = []
    row = {"inputs": {"g_lv": 9, "g_tm": 50, "g_x": 1}, "target_kind": "write", "target_line": 3,
           "target_text": "g_o = 1U;", "exposure": [0, 1], "propagated": ["g_o"], "exposures_met": 1}
    suts._propagation_row(seqs, row, "PROPR_0", ["g_o"], {"g_lv": "U8", "g_tm": "U16", "g_x": "U8"},
                          {"g_lv": 9, "g_tm": 50}, {"g_lv": [0, 1, 2], "g_tm": (0, 20)},
                          {"g_lv": {"design": [0, 1, 2], "enumerators": (0, 2)}})
    text = seqs[0]["description"]
    assert "g_lv=9(설계 값 0, 1, 2 밖)" in text and "g_tm=50(설계 0~20 밖)" in text and "g_x" not in text
    assert text.startswith("설계 범위 밖 결함 전파 시나리오")
    assert seqs[0]["propagation"]["outside_design"] == {"g_lv": 9, "g_tm": 50}


def test_a_failing_enum_widening_keeps_the_in_design_rows(monkeypatch):
    # (review R84 I1) the enum preparation alone is lost, as in R80
    def boom(*_a, **_k):
        raise RuntimeError("enum")
    monkeypatch.setattr(suts, "_outside_enumerator_domains", boom)
    unit = _seq_unit(uds_param_info={"den": {"range": [1, 100]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rep = unit["propagation_rows"]
    assert rep["outside_design_enum_error"] == "RuntimeError" and not rep.get("error")
    assert rep["fi_rows"] >= 1 and any(str(s["strategy"]).startswith(PROPAGATE_FI_PREFIX) for s in seqs)
    # (review R84 W-R2-1) and the summary · disclosure say so
    out = summarize_propagation_rows([unit])
    assert out["enum_errors"] == 1 and out["errors"] == 0
    from report_gen.generation_disclosures import build_disclosures
    note = {i["key"]: i for i in build_disclosures("suts", {"propagation_rows": out})}["suts_propagation_rows"]
    assert "열거자 밖 값 넓힘이 실패" in str(note)


def test_a_pointer_comparison_is_unmodeled_not_climbed():
    # (review R84 I2) `p != 0` on the harness's pointee: its decision observes it, its operands never come — counted
    #   as the model not knowing the site, never climbed (no local best)
    old = [{"g_in": 5, "p[0]": 7}]
    found = sr.find_scenarios(_unit("pchk"), {"g_in": U8, "p[0]": U8}, ["return"], old, covered=old, propagate=True)
    rep = found["report"]
    assert rep["expose_flip"] == 2 and rep["expose_local_best"] == 0
    assert rep["expose_unmodeled"] == 3   # `p != 0` and the two writes to the local `r` (no known prior value)
    assert not _prop(found, "flip", "p != 0")


def test_the_check_keeps_to_its_step_cap_and_counts_its_steps(monkeypatch):
    # (review R84 I3) a step cap of 1: the first perturbed run stops on it, the rest are budget stops, not refusals
    monkeypatch.setattr(sr, "MAX_PROPAGATE_CHECK_STEPS", 1)
    old = [{"g_det": 0, "g_tm": 65535, "g_st": v} for v in range(5)]
    rep = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"], old,
                            covered=old, propagate=True)["report"]
    assert rep["propagate_check_capped"] >= 1 and rep["propagate_perturbed_budget"] >= 1
    assert rep["propagate_check_steps"] >= 1
    # (review R84 I-R2-3) a run the check's cap stopped is no "no change": the search runs it again on its budget, and
    #   the suite row with g_st 1 (the other branch's state differs) covers the masked boundary
    assert not _prop(found_rows := sr.find_scenarios(
        _unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"], old, covered=old,
        propagate=True), "boundary", "g_tm < TMAX") and found_rows["report"]["propagate_check_late"] >= 1


def test_a_move_that_stays_in_the_design_comes_before_one_that_leaves_it():
    # (review R84 I-R2-5) `assist` listed first, but every move of it leaves its home (7 ~ 7): moving `start` inside
    #   unmasks the clamp too — the row stays in the design (no FI value needed)
    old = [{"assist": 7, "start": 7, "now": 5, "endv": 1}]
    doms = {"assist": S16, "start": S16, "now": S16, "endv": S16}
    found = sr.find_scenarios(_unit("hold"), doms, ["return"], old, covered=old, home={"assist": (7, 7)},
                              propagate=True)
    clamps = [r["inputs"] for r in found["rows"] if r["inputs"]["now"] > r["inputs"]["endv"] > 0]
    assert clamps and all(v["assist"] == 7 and v["start"] != 7 for v in clamps)


def test_a_late_confirmation_survives_an_error_of_the_phase(monkeypatch):
    # (review R84 W-R3-1) the exposing phase fails after a suite row met a target in the late check: the target stays met
    #   (no row of the phase met it) and the counts agree — the error revert took it back while the counters kept it
    monkeypatch.setattr(sr, "MAX_PROPAGATE_CHECK", 0)
    real = sr.observe_decisions
    n = [0]

    def flaky(*a, **k):
        if k.get("perturb"):
            n[0] += 1
            if n[0] == 4:
                raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(sr, "observe_decisions", flaky)
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 1}, {"g_det": 0, "g_tm": 20, "g_st": 1}]
    rep = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"], old,
                            covered=old, propagate=True)["report"]
    assert rep["expose_error"] == "RuntimeError" and rep["propagate_check_late"] >= 1
    assert rep["expose_reached"] >= rep["expose_covered_before"] >= rep["propagate_check_late"]
    assert rep["expose_reached"] + rep["expose_not_reached"] == rep["expose_targets"]


def test_the_identity_is_zero_for_a_term_and_one_for_a_factor_and_only_plain_writes_are_left_out():
    unit = _unit("lin")
    v = {"a": 10, "b": 3, "g_acc": 1}
    assert _out(unit, v, ["return", "g_acc"]) == {"return": 37, "g_acc": 3}
    assert _out(unit, v, ["return"], ["drop_right", _key(unit, "a - b", "binary_expression")]) == {"return": 40}
    assert _out(unit, v, ["return"], ["drop_right", _key(unit, "a * b", "binary_expression")]) == {"return": 17}
    # `g_acc += 2U` is no write target (R79 takes `=` only): leaving it out is not what this perturbation does
    assert _out(unit, v, ["g_acc"], ["skip_write", _key(unit, "g_acc += 2U", "assignment_expression")]) == {"g_acc": 3}


# ── the self-check's survivors, told apart ────────────────────────────────────────────────────────────────────────

def test_a_perturbed_run_that_is_no_clean_run_never_meets_a_target():
    # every exposure of `endv > 0` (endv held at 0) flips into `/ endv` by zero: no target meets through such a run
    old = [{"now": 5, "endv": 0, "start": 1, "assist": 9}]
    rep = sr.find_scenarios(_unit("hold"), {"now": S16, "endv": (0, 0), "start": S16, "assist": S16}, ["return"], old,
                            covered=old, propagate=True)["report"]
    assert rep["expose_reached"] == 0 and rep["propagate_perturbed_refused"] >= 1


def test_a_run_without_a_derived_output_shows_nothing_and_is_not_perturbed():
    old = [{"g_det": 0, "g_tm": 65535, "g_st": 1}]
    found = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_buf"], old, covered=old,
                              propagate=True)
    assert not found["rows"] and found["report"]["expose_reached"] == 0
    assert found["report"]["propagate_perturbed_runs"] == 0


def test_the_move_kept_inside_the_design_wins_over_the_one_listed_first():
    # (review R84 I-R2-5) `g_a` comes first but every move of it leaves home (3 ~ 3); `g_b` inside unmasks the product
    old = [{"g_a": 3, "g_b": 3, "g_k": 101, "g_t": 0}]
    found = sr.find_scenarios(_unit("mask"), {"g_a": U16, "g_b": U16, "g_k": U16, "g_t": U8}, ["g_o", "g_t"], old,
                              covered=old, home={"g_a": (3, 3)}, propagate=True)
    rows = _prop(found, "write", "g_k = 5U")
    assert rows and rows[0]["inputs"]["g_a"] == 3 and rows[0]["inputs"]["g_b"] != 3


def test_rows_whose_check_run_the_step_cap_stopped_are_checked_late_not_searched_again(monkeypatch):
    # (review R84 I-R3-1 · I-R2-3) the suite row with g_det 1 meets `g_det == 1U` — its check run was stopped by the cap
    monkeypatch.setattr(sr, "MAX_PROPAGATE_CHECK_STEPS", 1)
    old = [{"g_det": 0, "g_tm": 65535, "g_st": v} for v in range(5)]
    found = sr.find_scenarios(_unit("timer"), {"g_det": U8, "g_tm": U16, "g_st": U8}, ["g_tm", "g_st", "return"], old,
                              covered=old, propagate=True)
    rep = found["report"]
    assert not _prop(found, "flip", "g_det == 1U")
    assert rep["propagate_check_late"] == rep["expose_covered_before"] == 5


def test_a_condition_that_does_not_decide_yet_is_climbed_to_decide_first(monkeypatch):
    # `g_dev == 9U` evaluated with g_roll 0 does not decide: the climb makes it decide (g_roll) — treating the mere
    #   evaluation as exposed sends it to single moves that cannot also make the arms differ, and the budget runs out
    monkeypatch.setattr(sr, "MAX_PROPAGATE_RUNS", 30)
    monkeypatch.setattr(sr, "MAX_STARTS", 0)
    old = [{"g_dev": 0, "g_roll": 0, "g_maxs": 50, "g_max": 50}]
    found = sr.find_scenarios(_unit("thr"), {"g_dev": U8, "g_roll": S16, "g_maxs": (50, 50), "g_max": U16}, ["g_peak"],
                              old, covered=old, propagate=True)
    assert _prop(found, "flip", "g_dev == 9U")


def test_rows_of_a_failing_step_are_all_taken_back(monkeypatch):
    # the first search added a row, the second raises: no propagating row stays, the unit says why
    real = suts.find_scenarios
    n = [0]
    row = {"inputs": {"num": 7, "den": 3}, "target_kind": "arith", "target_line": 1, "target_text": "x", "exposure": [7, 1],
           "operator": "+", "propagated": ["return"], "exposures_met": 1, "targets_reached": 0}

    def spy(unit, domains, outputs, existing=None, **kw):
        if not kw.get("propagate"):
            return real(unit, domains, outputs, existing, **kw)
        n[0] += 1
        if n[0] == 1:
            return {"rows": [row], "reached_vectors": [], "report": {
                "status": "searched", "expose_targets": 2, "expose_reached": 1, "expose_not_reached": 1}}
        raise RuntimeError("second")
    monkeypatch.setattr(suts, "find_scenarios", spy)
    unit = _seq_unit(uds_param_info={"den": {"range": [1, 100]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert n[0] == 2 and not any(str(s["strategy"]).startswith(("PROP_", "PROPR_")) for s in seqs)
    assert unit["propagation_rows"] == {"error": "RuntimeError", "rows": 0, "fi_rows": 0}
