"""R79 — fault-exposing targets of the scenario search (`generators/scenario_rows.py`, extended SUTS only).

Reaching a statement is not seeing a fault in it: after the reach targets, each function also gets targets on which a
fault would change the result — a relational condition evaluated with equal sides while it decides its decision, an
assignment replacing a different value, an arithmetic operator on operands that do not hide it. The model records the
operands and the replaced values (`observe_decisions(operands=, writes=)`). No mutant is made or consulted. Every value
below is what C computes on a 16-bit-int target, as the oracle models it."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import scenario_rows as sr
from generators.c_source_oracle import observe_decisions
from generators.suts import SCENARIO_REPORT_KEYS, generate_sequences, summarize_scenario_rows

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
#define TIME_LIMIT 20U
#define NUM_CH 4U
#define ADD1(x) ((x) + 1U)
#endif
"""
UNIT = """#include "common.h"
U16 g_tmr;
U8 g_flag;
void tm_check(void)
{
    g_tmr++;
    if (g_tmr > TIME_LIMIT)
    {
        g_flag = 1U;
    }
    else
    {
        g_flag = 0U;
    }
}
U16 g_ctm;
U8 g_go;
void clear_tm(void)
{
    if (g_go == 1U)
    {
        g_ctm = 0U;
    }
}
U16 g_off;
S16 g_res;
void comp(void)
{
    g_res = ((S16)g_off) / (10 - 60);
}
S16 g_pos;
S16 g_ref;
void refpos(void)
{
    g_ref = g_pos - (g_pos * 5 / 100);
}
U8 g_ra;
U8 g_rb;
U8 get_a(void)
{
    return g_ra;
}
U8 get_b(void)
{
    return g_rb;
}
U8 g_oa;
U8 g_ob;
void two(void)
{
    U8 t;
    t = get_a();
    g_oa = t;
    t = get_b();
    g_ob = t;
}
U8 g_lx;
U8 g_lz;
void loop_eq(void)
{
    U8 k;
    g_lz = 0U;
    for (k = 0U; k < 2U; k++)
    {
        if ((k >= g_lx) && (k == 1U))
        {
            g_lz = 1U;
        }
    }
}
U8 g_ma;
U8 g_mb;
U16 g_mo;
void mul(void)
{
    g_mo = (U16)(g_ma * g_mb);
}
U8 g_ac;
U8 g_ad;
U16 g_ao;
void add(void)
{
    g_ao = (U16)(g_ac + g_ad);
}
S16 g_nn;
S16 g_nq;
void negdiv(void)
{
    g_nq = (g_nn + 3) / 50;
}
void ptrw(U8 *p)
{
    *p = 3U;
}
U8 g_hx;
U8 g_ho;
U8 s_hid;
void hid(void)
{
    if (g_hx > 5U)
    {
        if (s_hid > 2U)
        {
            g_ho = 1U;
        }
    }
}
U8 g_kx;
U8 g_ky;
U8 g_kz;
void masked2(void)
{
    if ((g_kx > 5U) && (g_ky != 0U))
    {
        g_kz = 1U;
    }
}
U8 g_q;
U8 g_qr;
void cst(void)
{
    if (NUM_CH > 2U)
    {
        g_q = 1U;
    }
    if (g_qr > 3U)
    {
        g_q = 2U;
    }
}
U16 g_dv;
U8 g_dq;
void coarse(void)
{
    if ((g_dv / 16U) > 3U)
    {
        g_dq = 1U;
    }
}
S16 g_cs;
U16 g_cu;
U8 g_co;
void mixed(void)
{
    if (g_cs > g_cu)
    {
        g_co = 1U;
    }
}
U8 g_wx;
U8 g_w8;
void wrap(void)
{
    g_w8 = g_wx + 250U;
}
U8 g_u0;
U8 g_u1;
U8 g_u2;
U8 g_u3;
U8 g_u4;
U8 g_u5;
U8 g_uz;
void many(void)
{
    if ((g_u0 > 1U) && (g_u1 > 1U) && (g_u2 > 1U) && (g_u3 > 1U) && (g_u4 > 1U))
    {
        g_uz = 1U;
    }
    g_uz = (U8)(g_uz + g_u5);
}
U8 g_e1;
U8 g_e2;
U8 g_e3;
U8 g_e4;
U16 g_e5;
U8 g_eq;
void coarse5(void)
{
    g_eq = (U8)(g_e1 | g_e2 | g_e3 | g_e4);
    if ((g_e5 / 16U) > 3U)
    {
        g_eq = 1U;
    }
}
U8 g_ux;
U8 s_unk;
U8 g_uo;
void unknown2(void)
{
    if ((g_ux > 5U) && (s_unk == 1U))
    {
        g_uo = 1U;
    }
}
U8 g_mq;
U8 g_mr;
void macarg(void)
{
    g_mr = (U8)ADD1(g_mq * 3U);
}
U8 g_go2;
void gt(void)
{
    goto done;
done:
    g_go2 = (U8)(g_go2 + 1U);
}
U8 g_tb;
U8 g_tc;
U16 g_to;
void tern(void)
{
    g_to = (g_tb > 5U) ? (U16)(g_tb * g_tc) : 0U;
}
U8 g_aa;
U8 g_ab;
U8 g_ao2;
void andright(void)
{
    g_ao2 = (U8)((g_aa > 5U) && ((g_aa + g_ab) > 7U));
}
U16 g_rd;
U16 g_rn;
U16 tret(void)
{
    return (g_rd > 9U) ? (U16)(g_rn / g_rd) : 0U;
}
S16 g_cst;
void castneg(void)
{
    g_cst = (S16)-1800;
}
U16 g_tx;
U16 g_d1;
U16 g_d2;
void twodiv(void)
{
    g_d1 = g_tx / 101U;
    g_d2 = (g_tx + 3U) / 50U;
}
U16 g_sv;
U16 scale(void)
{
    U16 r = 100U;
    if (g_sv > 1250U)
    {
        r = (U16)(475U - (30U * g_sv / 100U));
    }
    return r;
}
U8 g_x;
U8 g_y;
U8 g_z;
void masked(void)
{
    if ((g_x > 5U) && (g_y == 1U))
    {
        g_z = 1U;
    }
    else
    {
        g_z = 0U;
    }
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


def _key(unit, text, kind):
    raw = unit["source_text"].encode()
    start = unit["source_text"].index(text)
    node = cpc.shared_parser().parse(raw).root_node.descendant_for_byte_range(start, start + len(text))
    while node.type != kind:
        node = node.parent
    return [node.start_byte, node.end_byte, node.type]


def _exposing(found, kind):
    return [r for r in found["rows"] if r["target_kind"] == kind]


# ── the model records what a fault would change ────────────────────────────────────────────────────────────────

def test_the_model_records_operands_and_replaced_values_without_a_step():
    unit = _unit("tm_check")
    cmp_key = _key(unit, "g_tmr > TIME_LIMIT", "binary_expression")
    wr_key = _key(unit, "g_flag = 1U", "assignment_expression")
    plain = observe_decisions(unit, [{"g_tmr": 19, "g_flag": 0}], [])[0]
    watched = observe_decisions(unit, [{"g_tmr": 19, "g_flag": 0}], [], operands=[cmp_key], writes=[wr_key])[0]
    assert watched["operands"][0] == [[(20, 20)]]            # g_tmr after ++ meets the limit
    assert watched["writes"][0] == [[]]                       # 20 > 20 is false: the true arm does not run
    assert watched["steps"] == plain["steps"]                 # watching costs no step (budgets stay what they were)
    hit = observe_decisions(unit, [{"g_tmr": 20, "g_flag": 7}], [], writes=[wr_key])[0]
    assert hit["writes"][0] == [[(7, 1)]]                     # the value replaced, the value written
    unset = observe_decisions(unit, [{"g_tmr": 20}], [], writes=[wr_key], reach=[_key(unit, "g_flag = 1U;", "expression_statement")])[0]
    assert unset["writes"][0] == [[(None, 1)]] and "g_flag" not in unset["initial_reads"]   # the peek records no read


# ── boundary: equal sides, the condition deciding ──────────────────────────────────────────────────────────────

def test_a_comparison_after_an_increment_is_met_at_its_boundary():
    # `g_tmr++; if (g_tmr > 20)`: the branch targets are reached far from the limit; the boundary target asks for
    #   g_tmr = 19 — after ++ the two sides are equal and `>` against `>=` decides (HDPDM01 s_AssistDeactivation)
    #   — the suite's rows already reach both arms with 0 and 32767, as HDPDM01's did
    old = [{"g_tmr": 0, "g_flag": 0}, {"g_tmr": 32767, "g_flag": 0}]
    found = sr.find_scenarios(_unit("tm_check"), {"g_tmr": U16, "g_flag": U8}, ["g_flag", "g_tmr"], old, covered=old)
    rep = found["report"]
    rows = _exposing(found, "boundary")
    assert rep["reached_clean"] == rep["targets"] and rep["rows"] == 0
    assert rep["expose_boundary"] == 1 and rows and rows[0]["inputs"]["g_tmr"] == 19 and rows[0]["exposure"] == [20, 20]
    assert rep["expose_reached"] >= 1 and rep["expose_rows"] == len([r for r in found["rows"]
                                                                       if r["target_kind"] in sr.EXPOSE_KINDS])


def test_the_boundary_needs_the_condition_to_decide():
    # `(g_x > 5) && (g_y == 1)`: at g_x = 5 the decision is false whatever g_y is unless g_y == 1 — only then does
    #   the comparison decide; the row has both. The climb starts nearest at (0, 0): (5, 0) has equal sides but the
    #   comparison does not decide there (review R79 W4: a start with g_y = 1 hid a missing check)
    old = [{"g_x": 0, "g_y": 0, "g_z": 0}, {"g_x": 200, "g_y": 1, "g_z": 0}]
    found = sr.find_scenarios(_unit("masked"), {"g_x": U8, "g_y": U8, "g_z": U8}, ["g_z"], old, covered=old)
    rows = [r for r in _exposing(found, "boundary") if "g_x" in r["target_text"]]
    assert rows and rows[0]["inputs"]["g_x"] == 5 and rows[0]["inputs"]["g_y"] == 1


# ── write: a different value replaced ──────────────────────────────────────────────────────────────────────────

def test_a_clear_is_met_with_a_value_to_clear():
    # `g_ctm = 0U` with g_ctm already 0 shows nothing if it is deleted — the write target asks for a non-zero timer
    old = [{"g_ctm": 0, "g_go": 1}, {"g_ctm": 0, "g_go": 0}]
    found = sr.find_scenarios(_unit("clear_tm"), {"g_ctm": U16, "g_go": U8}, ["g_ctm"], old, covered=old)
    rows = _exposing(found, "write")
    assert rows and rows[0]["inputs"]["g_go"] == 1 and rows[0]["inputs"]["g_ctm"] != 0
    assert rows[0]["exposure"] == [rows[0]["inputs"]["g_ctm"], 0]


def test_two_stubs_returning_the_same_value_hide_the_second_call():
    # t = get_a(); … t = get_b(); — with both stubs at 127 the second assignment writes what t held (HDPDM01
    #   s_ApiOut_u8bit_DataUpdate_A: the reference gives the two conversions different values)
    doms = {"get_a() return": U8, "get_b() return": U8, "g_oa": U8, "g_ob": U8}
    old = [{"get_a() return": 127, "get_b() return": 127, "g_oa": 0, "g_ob": 0}]
    found = sr.find_scenarios(_unit("two"), doms, ["g_oa", "g_ob"], old, covered=old)
    rows = [r for r in _exposing(found, "write") if "get_b" in r["target_text"]]
    assert rows and rows[0]["inputs"]["get_a() return"] != rows[0]["inputs"]["get_b() return"]


def test_a_write_of_the_value_already_there_moves_by_a_small_step():
    # at g_sv = 1251 (the comparison's neighbour, R78's row) the assignment writes 100 — what r already holds; a small
    #   step of g_sv (not the type's end) makes it write something else
    found = sr.find_scenarios(_unit("scale"), {"g_sv": U16}, ["return"], [{"g_sv": 1251}], covered=[{"g_sv": 1251}])
    rows = _exposing(found, "write")
    assert rows and 1251 < rows[0]["inputs"]["g_sv"] <= 1251 + 64 and rows[0]["exposure"][0] == 100
    assert rows[0]["exposure"][1] != 100


# ── arith: operands that do not hide the operator ──────────────────────────────────────────────────────────────

def test_a_division_by_a_constant_is_met_at_a_multiple_of_the_divisor():
    # ((S16)g_off) / (10 - 60): 145 / -50 and 145 / -51 are both -2 — a dividend at a multiple of 50 tells them apart
    #   (HDPDM01 s_AstOutCompensate; the secant step moves g_off to the nearest multiple)
    old = [{"g_off": 145}]
    found = sr.find_scenarios(_unit("comp"), {"g_off": (0, 1000)}, ["g_res"], old, covered=old)
    rows = [r for r in _exposing(found, "arith") if r.get("operator") == "/"]
    assert rows and rows[0]["inputs"]["g_off"] % 50 == 0 and rows[0]["inputs"]["g_off"] != 0


def test_a_scaled_term_is_met_where_it_is_not_zero():
    # g_pos - (g_pos * 5 / 100): with g_pos = 0 or 10 the term is 0 and `-` against `+` shows nothing — g_pos = 20 is
    #   the first value where the division steps (HDPDM01 s_ReboundProtection; the reference has 20)
    old = [{"g_pos": 0}, {"g_pos": 10}]
    found = sr.find_scenarios(_unit("refpos"), {"g_pos": (0, 1000)}, ["g_ref"], old, covered=old)
    ops = {r.get("operator"): r for r in _exposing(found, "arith")}
    assert "/" in ops and ops["/"]["inputs"]["g_pos"] * 5 % 100 == 0 and ops["/"]["inputs"]["g_pos"] >= 20
    assert found["report"]["expose_arith"] == 3      # `-` · `*` · `/` (the constant-only `5 / 100` part is not one)
    for r in found["rows"]:
        assert r["inputs"]["g_pos"] * 5 // 100 != 0 or r["target_kind"] not in sr.EXPOSE_KINDS


# ── the reach targets stay what they were ──────────────────────────────────────────────────────────────────────

def test_the_reach_targets_rows_and_counters_do_not_change():
    # against the search with no exposing target at all (R78's): the reach rows — order, values, the count of what
    #   each reached first (review R79 W2a: it counted the exposing targets too, and the row text said so) — and the
    #   reach counters are the same
    unit = _unit("masked")
    doms, outs = {"g_x": U8, "g_y": U8, "g_z": U8}, ["g_z"]
    old = [{"g_x": 0, "g_y": 0, "g_z": 0}]
    with_exposure = sr.find_scenarios(unit, doms, outs, old, covered=old)
    without = sr.find_scenarios(unit, doms, outs, old, covered=old, expose=False)
    keys = ("targets", "reached_clean", "reached_unclean_only", "not_reached", "rows", "runs", "steps", "cut",
            "duplicates", "covered_before", "budget_exhausted", "local_best", "budget_cut", "needed_inputs")
    assert {k: with_exposure["report"][k] for k in keys} == {k: without["report"][k] for k in keys}
    n = without["report"]["rows"]
    assert [{k: v for k, v in r.items() if k != "exposures_met"} for r in with_exposure["rows"][:n]] == \
        [{k: v for k, v in r.items() if k != "exposures_met"} for r in without["rows"]]
    assert without["report"]["expose_targets"] == 0 and without["report"]["expose_rows"] == 0
    assert with_exposure["report"]["expose_rows"] >= 1 and len(with_exposure["rows"]) > n


def test_a_reach_budget_spent_leaves_the_exposing_phase_its_own(monkeypatch):
    # one run for the reach targets (the first start): the phase stops; the exposing phase runs on its own budget, and
    #   what its rows reach of the reach targets is counted as reached — and attributed (review R79 W2b · I1)
    monkeypatch.setattr(sr, "MAX_RUNS", 1)
    doms = {"g_x": U8, "g_y": U8, "g_z": U8}
    rep = sr.find_scenarios(_unit("masked"), doms, ["g_z"])["report"]
    alone = sr.find_scenarios(_unit("masked"), doms, ["g_z"], expose=False)["report"]
    assert rep["budget_exhausted"] and rep["runs"] == 1 == alone["runs"] and rep["expose_runs"] > 0
    assert rep["steps"] == alone["steps"] and rep["expose_steps"] > 0   # the reach steps leave the exposing phase's out
    assert not rep.get("expose_error") and rep["reached_by_exposing_rows"] >= 1
    assert rep["reached_clean"] == alone["reached_clean"] + rep["reached_by_exposing_rows"]
    # the reach phase's classification reads its own runs: what is still unreached is counted as before
    assert rep["budget_cut"] <= alone["budget_cut"] and rep["rows"] == alone["rows"]


def test_equal_sides_and_deciding_are_one_evaluation():
    # `for k in 0..1: if ((k >= g_lx) && (k == 1))`: with g_lx = 0 the sides are equal at k = 0, where the comparison
    #   does not decide, and it decides at k = 1, where they differ — not exposed; g_lx = 1 is (review R79 W1)
    old = [{"g_lx": 0, "g_lz": 0}, {"g_lx": 2, "g_lz": 0}]
    found = sr.find_scenarios(_unit("loop_eq"), {"g_lx": U8, "g_lz": U8}, ["g_lz"], old, covered=old)
    rows = [r for r in _exposing(found, "boundary") if "k >= g_lx" in r["target_text"]]
    assert rows and rows[0]["inputs"]["g_lx"] == 1 and rows[0]["exposure"] == [1, 1]


def test_a_product_needs_both_operands_non_zero():
    old = [{"g_ma": 0, "g_mb": 5}]
    found = sr.find_scenarios(_unit("mul"), {"g_ma": U8, "g_mb": U8}, ["g_mo"], old, covered=old)
    rows = [r for r in _exposing(found, "arith") if r.get("operator") == "*"]
    assert rows and rows[0]["inputs"]["g_ma"] != 0 and rows[0]["inputs"]["g_mb"] != 0


def test_a_sum_needs_its_right_operand_non_zero():
    old = [{"g_ac": 5, "g_ad": 0}]
    found = sr.find_scenarios(_unit("add"), {"g_ac": U8, "g_ad": U8}, ["g_ao"], old, covered=old)
    rows = [r for r in _exposing(found, "arith") if r.get("operator") == "+"]
    assert rows and rows[0]["inputs"]["g_ad"] != 0


def test_a_negative_dividend_moves_to_the_nearest_multiple():
    # (g_nn + 3) / 50 over g_nn in -1000..-1: no candidate of the pool is a multiple (50 and 3 are outside the range,
    #   -1000 + 3 and -1 + 3 are not); the secant takes the start -501 (dividend -498) to -503 — the nearest multiple
    #   on the dividend's side, which a positive one would leave the range for
    found = sr.find_scenarios(_unit("negdiv"), {"g_nn": (-1000, -1)}, ["g_nq"])
    rows = [r for r in _exposing(found, "arith") if r.get("operator") == "/"]
    assert rows and (rows[0]["inputs"]["g_nn"] + 3) % 50 == 0 and rows[0]["inputs"]["g_nn"] < 0


def test_a_write_through_a_pointer_is_counted_not_searched():
    # the row sets no pointee: the value `*p = 3U` replaces is never known — counted, not searched
    rep = sr.find_scenarios(_unit("ptrw"), {"g_ctm": U16}, ["g_ctm"])["report"]
    assert rep["expose_write"] == 1 and rep["expose_unmodeled"] == 1 and rep["expose_local_best"] == 0


def test_the_second_search_has_no_exposing_targets(monkeypatch):
    import generators.suts as suts_mod
    calls = []
    real = suts_mod.find_scenarios

    def spy(unit, domains, outputs, existing=None, **kw):
        calls.append(kw)
        return real(unit, domains, outputs, existing, **kw)
    monkeypatch.setattr(suts_mod, "find_scenarios", spy)
    unit = _unit("tm_check")
    unit.update({"fid": "F1", "input_vars": ["g_tmr"], "output_vars": ["g_flag", "g_tmr"],
                 "param_types": {"g_tmr": "U16", "g_flag": "U8"}, "uds_param_info": {"g_tmr": {"range": [0, 10]}}})
    generate_sequences(unit, None, type_cache={}, extended=True)
    second = [kw for kw in calls if "home" in kw]
    assert second and all(kw.get("expose") is False for kw in second)
    assert all(kw.get("expose", True) for kw in calls if "home" not in kw)


def test_each_phase_has_its_own_row_cap(monkeypatch):
    # no reach row may be added; the boundary row is the exposing phase's own
    monkeypatch.setattr(sr, "MAX_ROWS", 0)
    old = [{"g_tmr": 0, "g_flag": 0}, {"g_tmr": 32767, "g_flag": 0}]
    rep = sr.find_scenarios(_unit("tm_check"), {"g_tmr": U16, "g_flag": U8}, ["g_flag", "g_tmr"], old,
                            covered=old)["report"]
    assert rep["rows"] == 0 and rep["expose_rows"] >= 1


def test_a_target_an_existing_row_exposes_costs_no_row():
    old = [{"g_tmr": 0, "g_flag": 0}, {"g_tmr": 32767, "g_flag": 0}, {"g_tmr": 19, "g_flag": 0}]
    found = sr.find_scenarios(_unit("tm_check"), {"g_tmr": U16, "g_flag": U8}, ["g_flag", "g_tmr"], old, covered=old)
    assert found["report"]["expose_covered_before"] >= 1 and not _exposing(found, "boundary")


def test_the_row_cap_of_the_exposing_targets_is_their_own(monkeypatch):
    monkeypatch.setattr(sr, "MAX_EXPOSE_ROWS", 0)
    old = [{"g_pos": 0}]
    found = sr.find_scenarios(_unit("refpos"), {"g_pos": (0, 1000)}, ["g_ref"], old, covered=old)
    rep = found["report"]
    assert rep["expose_rows"] == 0 and rep["expose_cut"] >= 1 and rep["rows"] == len(found["rows"])


def test_an_unobserved_comparison_has_no_decides_record():
    # `(g_kx > 5) && (g_ky != 0)` at (0, 1): the short circuit never evaluates the second condition — only the first
    #   gets a record (the probe evaluates both: a record from it would claim an evaluation that did not happen); the
    #   first decides (flipped, the second makes the decision true)
    unit = _unit("masked2")
    k0 = _key(unit, "g_kx > 5U", "binary_expression")
    k1 = _key(unit, "g_ky != 0U", "binary_expression")
    spec = {"key": _key(unit, "(g_kx > 5U) && (g_ky != 0U)", "binary_expression"), "atoms": [k0, k1],
            "ir": ["&&", ["atom", 0], ["atom", 1]]}
    r = observe_decisions(unit, [{"g_kx": 0, "g_ky": 1}], [spec], operands=[k0, k1])[0]
    assert r["decides"][0] == [[(0, 5, True)]] and r["decides"][1] == [[]]


def test_a_flip_into_an_unknown_condition_does_not_decide():
    # `(g_ux > 5) && (s_unk == 1)` at g_ux = 5: false on the short circuit; flipped, the decision reads s_unk, which
    #   no input sets — the outcome would be undetermined, so the comparison is not shown to decide
    unit = _unit("unknown2")
    k0 = _key(unit, "g_ux > 5U", "binary_expression")
    k1 = _key(unit, "s_unk == 1U", "binary_expression")
    spec = {"key": _key(unit, "(g_ux > 5U) && (s_unk == 1U)", "binary_expression"), "atoms": [k0, k1],
            "ir": ["&&", ["atom", 0], ["atom", 1]]}
    r = observe_decisions(unit, [{"g_ux": 5}], [spec], operands=[k0])[0]
    assert r["decides"][0] == [[(5, 5, False)]]


def test_an_operator_in_a_macro_argument_is_counted_not_searched():
    # `ADD1(g_mq * 3U)`: the macro's expansion is other text — the model never records that `*` (review R79 I-R2-1)
    rep = sr.find_scenarios(_unit("macarg"), {"g_mq": U8, "g_mr": U8}, ["g_mr"])["report"]
    assert rep["expose_arith"] >= 1 and rep["expose_unmodeled"] >= 1 and rep["expose_local_best"] == 0


def test_an_operator_on_a_part_the_reach_rows_skipped_is_searched():
    # `?:` arms and the right of `&&` run on some evaluations only: the reach phase's runs may never take them — that
    #   is no proof the model cannot record them (review R79 W-R3-1: they were counted unmodeled, no row)
    for name, doms, outs, op in (("tern", {"g_tb": U8, "g_tc": U8, "g_to": U16}, ["g_to"], "*"),
                                 ("andright", {"g_aa": U8, "g_ab": U8, "g_ao2": U8}, ["g_ao2"], "+"),
                                 ("tret", {"g_rd": U16, "g_rn": U16}, ["return"], "/")):
        found = sr.find_scenarios(_unit(name), doms, outs)
        rep = found["report"]
        assert rep["expose_unmodeled"] == 0, name
        assert any(r.get("operator") == op for r in found["rows"]) or rep["expose_reached"] >= 1, name


def test_a_cast_of_a_negative_constant_is_no_target():
    # `(S16)-1800` parses as a subtraction of 1800 from `(S16)` — it is a cast (review R79 I-R3-2)
    rep = sr.find_scenarios(_unit("castneg"), {"g_cst": S16}, ["g_cst"])["report"]
    assert rep["expose_arith"] == 0


def test_a_unit_the_oracle_refuses_has_no_exposing_search():
    # every run refused (goto): the exposing targets are counted as refused, not as local bests (review R79 W-R2-2)
    rep = sr.find_scenarios(_unit("gt"), {"g_go2": U8}, ["g_go2"])["report"]
    assert rep["status"].startswith("oracle_unsupported") and rep["expose_targets"] >= 1
    assert rep["expose_refused"] == rep["expose_targets"] == rep["expose_not_reached"]
    assert rep["expose_local_best"] == rep["expose_budget_cut"] == rep["expose_runs"] == 0


def test_an_error_in_the_exposing_phase_keeps_the_reach_rows(monkeypatch):
    # the division's secant raises: the phase's rows are dropped, the reach rows and counters are those of the search
    #   without exposing targets, and the targets the error cut are counted as such (review R79 I1 · I-R2-2)
    def boom(left, right):
        raise RuntimeError("probe")
    monkeypatch.setattr(sr, "_multiple_near", boom)
    old = [{"g_off": 145}]
    found = sr.find_scenarios(_unit("comp"), {"g_off": (0, 1000)}, ["g_res"], old, covered=old)
    alone = sr.find_scenarios(_unit("comp"), {"g_off": (0, 1000)}, ["g_res"], old, covered=old, expose=False)
    rep = found["report"]
    assert rep["expose_error"] == "RuntimeError" and rep["expose_rows"] == 0 and rep["expose_error_cut"] >= 1
    assert found["rows"] == alone["rows"] and rep["reached_clean"] == alone["report"]["reached_clean"]
    # what was classified before the error stays so (the write `g_res = …` replaces a value no input sets); a row the
    #   error dropped leaves no "row cap" behind (review R79 I-R3-1)
    assert rep["expose_unmodeled"] == 1 and rep["expose_cut"] == 0


def test_an_error_after_a_cut_leaves_no_cut(monkeypatch):
    # g_tx / 101 is met by the start (101) but the row cap (0) cuts it; (g_tx + 3) / 50 then needs the secant, which
    #   raises: the phase's result is dropped — its cut too, counted with what the error cut (review R79 I-R3-1)
    def boom(left, right):
        raise RuntimeError("probe")
    monkeypatch.setattr(sr, "_multiple_near", boom)
    monkeypatch.setattr(sr, "MAX_EXPOSE_ROWS", 0)
    monkeypatch.setattr(sr, "MAX_ROWS", 0)      # no reach row meets them first
    rep = sr.find_scenarios(_unit("twodiv"), {"g_tx": (0, 1000)}, ["g_d1", "g_d2"])["report"]
    assert rep["expose_error"] == "RuntimeError" and rep["expose_cut"] == 0 and rep["expose_error_cut"] >= 2


def test_the_comparison_operands_are_recorded_as_compared():
    # S16 against U16 on a 16-bit int: -1 is converted to 65535 — the sides are equal (review R79 I3)
    unit = _unit("mixed")
    k = _key(unit, "g_cs > g_cu", "binary_expression")
    r = observe_decisions(unit, [{"g_cs": -1, "g_cu": 65535}], [], operands=[k])[0]
    assert r["operands"][0] == [[(65535, 65535)]]


def test_the_written_value_is_the_stored_one():
    # U8 g_w8 = g_wx + 250U at g_wx = 10: 260 is stored as 4
    unit = _unit("wrap")
    k = _key(unit, "g_w8 = g_wx + 250U", "assignment_expression")
    r = observe_decisions(unit, [{"g_wx": 10, "g_w8": 0}], [], writes=[k])[0]
    assert r["writes"][0] == [[(0, 4)]]


def test_the_gap_to_a_divisor_multiple_is_to_the_first_non_zero_one():
    assert sr._arith_gap("/", (10, 50)) == 40 and sr._arith_gap("/", (145, -50)) == 5 and sr._arith_gap("/", (0, 7)) == 7
    assert sr._arith_gap("*", (0, 3)) == 1 and sr._arith_gap("+", (3, 0)) == 1 and sr._arith_gap("/", (3, 0)) == sr._FAR


def test_a_constant_comparison_is_no_target():
    # `NUM_CH > 2U` compares two fixed values — no row can make its sides equal (review R79 I5)
    found = sr.find_scenarios(_unit("cst"), {"g_qr": U8, "g_q": U8}, ["g_q"])
    assert found["report"]["expose_boundary"] == 1


def test_a_coarse_quantity_takes_the_larger_probe():
    # (g_dv / 16) > 3: a step of 1 rarely moves g_dv / 16 — the second probe (+16) gives the slope, and g_dv lands in
    #   48..63 where g_dv / 16 is 3
    old = [{"g_dv": 0, "g_dq": 0}, {"g_dv": 1000, "g_dq": 0}]
    found = sr.find_scenarios(_unit("coarse"), {"g_dv": U16, "g_dq": U8}, ["g_dq"], old, covered=old)
    rows = _exposing(found, "boundary")
    assert rows and 48 <= rows[0]["inputs"]["g_dv"] <= 63


def test_a_comparison_that_does_not_decide_moves_the_other_conditions():
    # `(g_kx > 5) && (g_ky != 0)`: the start (5, 0) has equal sides, but only g_ky != 0 lets the comparison decide —
    #   the climb moves the decision's other input too (no reach row may help: none is added)
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(sr, "MAX_ROWS", 0)
    try:
        old = [{"g_kx": 0, "g_ky": 0, "g_kz": 0}]
        found = sr.find_scenarios(_unit("masked2"), {"g_kx": U8, "g_ky": U8, "g_kz": U8}, ["g_kz"], old, covered=old)
    finally:
        mp.undo()
    rows = [r for r in _exposing(found, "boundary") if "g_kx" in r["target_text"]]
    assert rows and rows[0]["inputs"]["g_kx"] == 5 and rows[0]["inputs"]["g_ky"] != 0


def test_an_exposing_target_moves_its_own_inputs_only():
    # five inputs decide `g_uz` and a sixth is added to it: the `+` target's climb moves g_uz · g_u5, not the five
    #   (every input would cost runs on each move)
    old = [{"g_u0": 0, "g_u1": 0, "g_u2": 0, "g_u3": 0, "g_u4": 0, "g_u5": 0, "g_uz": 0}]
    doms = {k: U8 for k in old[0]}
    rep = sr.find_scenarios(_unit("many"), doms, ["g_uz"], old, covered=old, expose=True)["report"]
    alone = sr.find_scenarios(_unit("many"), doms, ["g_uz"], old, covered=old, expose=False)["report"]
    assert rep["expose_reached"] >= 1 and rep["expose_runs"] < 60 and alone["runs"] == rep["runs"]


def test_the_secant_probes_the_targets_own_input():
    # (g_e5 / 16) > 3 with four other inputs listed first: the secant probes the comparison's input (g_e5), not the
    #   first four of the function's inputs — which do not move g_e5 / 16 at all
    old = [{"g_e1": 0, "g_e2": 0, "g_e3": 0, "g_e4": 0, "g_e5": 0, "g_eq": 0},
           {"g_e1": 0, "g_e2": 0, "g_e3": 0, "g_e4": 0, "g_e5": 1000, "g_eq": 0}]
    doms = {"g_e1": U8, "g_e2": U8, "g_e3": U8, "g_e4": U8, "g_e5": U16, "g_eq": U8}
    found = sr.find_scenarios(_unit("coarse5"), doms, ["g_eq"], old, covered=old)
    rows = [r for r in _exposing(found, "boundary") if "g_e5" in r["target_text"]]
    assert rows and 48 <= rows[0]["inputs"]["g_e5"] <= 63


def test_the_reach_phase_classifies_with_its_own_runs(monkeypatch):
    # one run for the reach targets: the inner `s_hid > 2U` is never touched by it — budget cut, nothing needed. The
    #   exposing phase's runs get there (s_hid unknown); they do not turn it into an unclean reach or a needed input
    #   (review R79 W2b)
    monkeypatch.setattr(sr, "MAX_RUNS", 1)
    rep = sr.find_scenarios(_unit("hid"), {"g_hx": U8}, ["g_ho"])["report"]
    alone = sr.find_scenarios(_unit("hid"), {"g_hx": U8}, ["g_ho"], expose=False)["report"]
    assert rep["expose_runs"] > 0 and rep["needed_inputs"] == alone["needed_inputs"] == {}
    # a target the exposing rows reach leaves the unreached counts; none joins them from the exposing runs
    assert rep["reached_unclean_only"] <= alone["reached_unclean_only"]


def test_an_existing_row_found_by_an_exposing_target_is_its_duplicate():
    # the covered rows reach every reach target; the existing row 19 is no covered one — the boundary target finds it
    covered = [{"g_tmr": 0, "g_flag": 0}, {"g_tmr": 32767, "g_flag": 0}]
    old = covered + [{"g_tmr": 19, "g_flag": 0}]
    doms = {"g_tmr": U16, "g_flag": U8}
    rep = sr.find_scenarios(_unit("tm_check"), doms, ["g_flag", "g_tmr"], old, covered=covered)["report"]
    alone = sr.find_scenarios(_unit("tm_check"), doms, ["g_flag", "g_tmr"], old, covered=covered, expose=False)["report"]
    assert rep["duplicates"] == alone["duplicates"] and rep["expose_duplicates"] >= 1


def test_starts_the_budget_never_ran_are_not_ranked(monkeypatch):
    # no reach run at all: the exposing phase ranks only starts that ran — none — and stops on its budget, no error
    #   (review R79 I1: an unrun start had no standing — KeyError, and the phase's rows were dropped)
    monkeypatch.setattr(sr, "MAX_RUNS", 0)
    old = [{"g_tmr": 1, "g_flag": 0}, {"g_tmr": 2, "g_flag": 0}, {"g_tmr": 3, "g_flag": 0}]
    rep = sr.find_scenarios(_unit("tm_check"), {"g_tmr": U16, "g_flag": U8}, ["g_flag", "g_tmr"], old)["report"]
    assert not rep.get("expose_error") and rep["expose_not_reached"] == rep["expose_targets"]


def test_the_exposing_budget_starts_at_the_phase(monkeypatch):
    # the reach phase spends more runs than the exposing phase has: its budget still starts fresh at the switch
    monkeypatch.setattr(sr, "MAX_EXPOSE_RUNS", 2)
    old = [{"g_tmr": 0, "g_flag": 0}, {"g_tmr": 32767, "g_flag": 0}]
    rep = sr.find_scenarios(_unit("tm_check"), {"g_tmr": U16, "g_flag": U8}, ["g_flag", "g_tmr"], old,
                            covered=old)["report"]
    assert rep["runs"] > 2 and rep["expose_runs"] >= 1


def test_an_exhausted_or_failed_exposing_phase_warns():
    from report_gen.generation_disclosures import build_disclosures
    base = {**dict.fromkeys(SCENARIO_REPORT_KEYS, 0), "rows": 3, "targets": 20, "reached_clean": 17, "units": 4,
            "searched": 3, "units_with_rows": 2, "budget_exhausted": 0, "errors": 0, "not_searched": {},
            "cap_per_unit": 16}

    def item(**kw):
        return {i["key"]: i for i in build_disclosures("suts", {"scenario_rows": {**base, **kw}})}["suts_scenario_rows"]
    assert item()["tone"] == "info"
    assert item(expose_budget_exhausted=1)["tone"] == "warning" and item(expose_errors=1)["tone"] == "warning"


# ── SUTS: the rows say what they expose; the report is summed ──────────────────────────────────────────────────

def test_the_summary_carries_the_exposing_counters():
    rep = {k: 1 for k in SCENARIO_REPORT_KEYS}
    out = summarize_scenario_rows([{"scenario_rows": {**rep, "status": "searched", "expose_budget_exhausted": True,
                                                      "expose_error": "KeyError"}}])
    assert all(out[k] == 1 for k in SCENARIO_REPORT_KEYS if k.startswith("expose_"))
    assert out["expose_budget_exhausted"] == 1 and out["units_with_rows"] == 1 and out["expose_errors"] == 1
    only = summarize_scenario_rows([{"scenario_rows": {**dict.fromkeys(SCENARIO_REPORT_KEYS, 0), "expose_rows": 2,
                                                       "status": "searched"}}])
    assert only["units_with_rows"] == 1      # a unit with exposing rows only has rows


def test_a_write_row_says_which_value_it_replaces_with_which():
    from generators.suts import _scenario_row
    seqs: list = []
    row = {"inputs": {"g_ctm": 7, "g_go": 1}, "target_kind": "write", "target_line": 30, "target_text": "g_ctm = 0U;",
           "target_outcome": None, "targets_reached": 0, "exposures_met": 1, "exposure": [7, 0]}
    _scenario_row(seqs, row, "SCN_0", ["g_ctm"], {"g_ctm": "U16", "g_go": "U8"}, {}, {})
    assert "이전 값 7 을 다른 값 0 로 바꾼다" in seqs[0]["description"]
    assert "처음 만족한 결함 노출 목표 1개" in seqs[0]["description"]


def _seq_unit():
    unit = _unit("comp")
    unit.update({"fid": "F1", "input_vars": ["g_off"], "output_vars": ["g_res"],
                 "param_types": {"g_off": "U16", "g_res": "S16"}, "uds_param_info": {"g_off": {"range": [0, 999]}}})
    return unit


def test_a_sequence_row_says_which_fault_its_values_expose():
    # the catalogue rows put g_off at 0, its range ends and middle (499) — none a multiple of 50 but 0 (where the
    #   quotient is 0 whatever the divisor): the division row is the search's, and its text says what it shows. The
    #   assignment `g_res = …` replaces a value no input sets (g_res is only an output): counted, not searched
    #   (`expose_unmodeled`)
    unit = _seq_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rows = [s for s in seqs if (s.get("scenario") or {}).get("target_kind") == "arith"]
    assert rows, [s["strategy"] for s in seqs]
    value = int(str(rows[0]["inputs"]["g_off"]), 0)
    assert value % 50 == 0 and value != 0 and rows[0]["scenario"]["operator"] == "/"
    assert "결함이 드러나는 값 시나리오" in rows[0]["description"] and "`/`" in rows[0]["description"]
    # it says what the search checks — the value there — not that a fault reaches an output (review R79 W-R2-1)
    assert "출력까지 드러나는지는 이 탐색이 보장하지 않는다" in rows[0]["description"]
    rep = unit["scenario_rows"]
    assert rep["expose_rows"] >= 1 and rep["expose_unmodeled"] == 1 and rep["expose_local_best"] == 0
