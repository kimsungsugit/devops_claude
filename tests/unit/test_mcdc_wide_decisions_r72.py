"""R72 — a decision of more conditions than the truth product takes (12) is paired condition by condition.

The expression engine enumerated the 2^n truth combinations of a decision's variable-connected components and refused a
decision of 13 or more conditions outright (`decision_or_condition_budget`) — the door state machines' 14~25-condition
decisions had no MC/DC row at all. `mcdc_design._wide_pairs` pairs them one condition at a time (two tuples of its
component that differ in it alone, then the other components chosen depth first while the three-valued decision can
still follow it) and evaluates every pair on its concrete inputs. The product engine (<= 12 conditions) is unchanged and
the new vectors follow every other vector of the function.
"""
from __future__ import annotations

import os
import random

import pytest

from generators import c_project_context as cpc
from generators import mcdc_design as md
from generators import suts
from generators.mcdc_design import build_mcdc_design, evaluate_decision, search_limits
from generators.suts import complete_source_read_inputs, generate_sequences, summarize_mcdc_design
from report_gen.generation_disclosures import build_disclosures
from tests.unit.test_mcdc_path_design import H, _unit

N13 = [f"a{i}" for i in range(13)]
AND13 = " && ".join(f"(a{i} == {i}U)" for i in range(13))
# an OR of ANDs with a shared variable (``a0 > 3U && a0 < 9U``) — 14 conditions
OR14 = ("((a0 > 3U) && (a0 < 9U) && (a1 == 2U)) || ((a2 == 1U) && (a3 == 1U)) || ((a4 == 1U) && (a5 == 1U) && (a6 == 1U))"
        " || ((a7 == 1U) && (a8 == 1U)) || ((a9 == 1U) && (a10 == 1U) && (a11 == 1U) && (a12 == 1U))")
# a negated group and a mixed nesting — 13 conditions
MIXED13 = ("!((a0 == 1U) || (a1 == 1U)) && ((a2 > 5U) || !(a3 < 2U)) && (((a4 == 1U) && (a5 == 1U)) || (a6 != 0U))"
           " && ((a7 == 7U) || (a8 == 8U) || (a9 == 9U)) && (a10 >= 10U) && ((a11 <= 3U) || (a12 == 200U))")


def _src(*decisions, params=N13, name="w"):
    body = " ".join(f"if ({d}) {{ g_o = {k + 1}U; }}" for k, d in enumerate(decisions))
    return H + "U8 g_o;\nvoid " + name + "(" + ", ".join(f"U8 {p}" for p in params) + ") { " + body + " }\n"


def _design(*decisions, params=N13, **kw):
    return build_mcdc_design(_unit(_src(*decisions, params=params), "w", list(params)), **kw)


def _assert_pairs_hold(report, decision):
    """Every pair re-evaluated independently: the condition flips alone, the outcome follows it."""
    n = len(decision["conditions"])
    # the constants · widths · types the design used — as `finalize_mcdc_design` re-evaluates
    kw = {"constants": report["constants"], "widths": (report.get("target") or {}).get("widths"),
          "types": report.get("types")}
    for pair in decision["pairs"]:
        i = int(pair["condition_id"][1:]) - 1
        a = evaluate_decision(decision["expression"], pair["inputs_a"], report["domains"], **kw)
        b = evaluate_decision(decision["expression"], pair["inputs_b"], report["domains"], **kw)
        assert a["status"] == b["status"] == "supported", (a, b)
        assert a["truth"][i] != b["truth"][i] and a["decision"] != b["decision"]
        assert a["observed"][i] and b["observed"][i]
        assert [a["truth"][j] for j in range(n) if j != i] == [b["truth"][j] for j in range(n) if j != i]
        assert (a["truth"], a["decision"], a["observed"]) == (pair["truth_a"], pair["decision_a"], pair["observed_a"])


@pytest.mark.parametrize("expression, conditions", [(AND13, 13), (OR14, 14), (MIXED13, 13)])
def test_a_wide_decision_is_paired_condition_by_condition(expression, conditions):
    report = _design(expression)
    (d,) = report["decisions"]
    assert len(d["conditions"]) == conditions and d["pair_search"] == "per_condition"
    assert d["status"] == "designed" and d["reason"] == "unique_cause_pairs_found" and len(d["pairs"]) == conditions
    assert search_limits(d) == []
    _assert_pairs_hold(report, d)
    # both members of every pair are emitted rows
    keys = {tuple(sorted(v.items())) for v in report["selected_inputs"]}
    assert all(tuple(sorted(p[f"inputs_{s}"].items())) in keys for p in d["pairs"] for s in ("a", "b"))


def test_twelve_conditions_keep_the_product_engine():
    twelve = " && ".join(f"(a{i} == {i}U)" for i in range(12))
    (d,) = _design(twelve)["decisions"]
    assert d["status"] == "designed" and "pair_search" not in d


def test_the_earlier_rows_and_slots_stay_where_they_were():
    # D1 is wide, D2 an ordinary decision: D2's design and the vectors before the wide ones are those of the old engine
    small = "(a0 == 1U) && (a1 == 2U)"
    new = _design(AND13, small)
    old = _design(AND13, small, max_wide_conditions=12)     # the cap as before R72: D1 refused
    assert old["decisions"][0]["reason"] == "decision_or_condition_budget"
    assert new["decisions"][1]["pairs"] == old["decisions"][1]["pairs"]
    n = len(old["selected_inputs"])
    assert new["selected_inputs"][:n] == old["selected_inputs"] and len(new["selected_inputs"]) > n


def test_a_condition_no_candidate_can_pair_is_said_and_the_search_was_complete():
    # ``a0 > 5U`` and ``a0 < 3U`` are never true together: neither can show its effect; the other group can
    expression = "((a0 > 5U) && (a0 < 3U)) || (" + " && ".join(f"(a{i} == {i}U)" for i in range(1, 13)) + ")"
    report = _design(expression)
    (d,) = report["decisions"]
    assert d["status"] == "partial" and {p["condition_id"] for p in d["pairs"]} == {f"C{i}" for i in range(3, 15)}
    assert d["search_complete"] is True and d["reason"] == "no_pair_in_candidate_domain"
    assert search_limits(d) == [("sampled_values", "")]   # the candidates were samples of U8, not the domain
    _assert_pairs_hold(report, d)


def test_a_decision_that_is_never_true_has_no_pair_and_says_the_candidates_were_all_searched():
    (d,) = _design("(a0 > 5U) && (a0 < 3U) && " + AND13)["decisions"]
    assert d["status"] == "no_pair_found" and d["search_complete"] is True
    assert d["reason"] == "no_pair_in_candidate_domain" and search_limits(d) == [("sampled_values", "")]


def test_a_condition_that_reads_no_input_is_known_and_never_flips():
    # ``3U > 2U`` is true on every vector: the others are paired through it, it has no pair of its own
    report = _design(AND13 + " && (3U > 2U)")
    (d,) = report["decisions"]
    assert len(d["conditions"]) == 14 and len(d["pairs"]) == 13 and "C14" not in {p["condition_id"] for p in d["pairs"]}
    assert d["status"] == "partial"
    _assert_pairs_hold(report, d)


def test_identical_conditions_are_a_proof_not_a_failed_search():
    expression = "(a0 == 0U) && " + AND13
    (d,) = _design(expression)["decisions"]
    assert d["reason"] == "unique_cause_infeasible:coupled_condition"
    assert {c["condition_id"] for c in d["infeasible_conditions"]} == {"C1", "C2"}
    assert len(d["pairs"]) == 12 and search_limits(d) == []


def test_the_step_budget_cuts_the_search_and_says_so(monkeypatch):
    # each condition of AND13 needs about two steps per other condition (false first — masked — then true): 16 steps
    #   cut every condition, while 16 vectors still complete each component (its list: 0 · 1 · the decision's
    #   constants ±1 · 255 — 15 values) — the cut, not an incomplete list, is what makes the search incomplete
    real, lists = md._realizable_truths, []

    def spy(*args, **kw):
        out = real(*args, **kw)
        lists.append(out[1])
        return out
    monkeypatch.setattr(md, "_realizable_truths", spy)
    (d,) = _design(AND13, max_candidates=16)["decisions"]
    assert lists == [True]
    assert d["pair_search"] == "per_condition" and d["search_complete"] is False
    assert d["status"] in ("partial", "no_pair_found") and d["reason"] == "candidate_budget_exhausted"
    assert ("candidate_budget", "") in search_limits(d)


def test_past_the_wide_cap_the_decision_is_not_searched():
    params = [f"a{i}" for i in range(65)]
    (d,) = _design(" && ".join(f"(a{i} == {i}U)" for i in range(65)), params=params)["decisions"]
    assert d["reason"] == "decision_or_condition_budget" and search_limits(d) == [("condition_cap", "65>64")]
    (d,) = _design(AND13, max_wide_conditions=12)["decisions"]
    assert search_limits(d) == [("condition_cap", "13>12")]


def test_the_path_search_keeps_the_cap_of_twelve():
    # a local in the decision sends it to the modeled run — not paired condition by condition (R73)
    text = H + ("U8 g_o;\nvoid wl(U8 a) { U8 t = (U8)(a + 1U); if ("
                + " && ".join(f"(t == {i}U)" for i in range(13)) + ") { g_o = 1U; } }\n")
    (d,) = build_mcdc_design(_unit(text, "wl", ["a"]))["decisions"]
    assert d["reason"] == "path_refused:decision_or_condition_budget" and "pair_search" not in d


# (R72 measurement) HD ``s_BuzzerStateStop`` D1, globals as parameters: ``PP != PP`` is never true (the source compares
#   a variable with itself), so C7 · C8 cannot show an effect; ``Ds == 5U`` twice is a proven coupling (C13 · C15)
BUZZER = """( ( Old != Sts ) && ( Sts == 3U ) )
    ||  ( ( Latch == 1U ) && ( DrSts == 0U ) && ( FullMv == 1U ) && ( FullMvOld != FullMv ) )
    ||  ( ( ( ( PP == 2U ) && ( PP != PP ) )
        ||  ( ( ( Sys & 0x01U ) == 0x01U ) || ( ( Sys & 0x02U ) == 0x02U ) || ( ( Sys & 0x04U ) == 0x04U )
            || ( ( Sys & 0x08U ) == 0x08U ) ) )
      &&  ( ( ( Ds == 5U ) && ( DsOld == 3U ) )
        ||  ( ( ( Ds == 5U ) || ( Ds == 7U ) ) && ( MvOld == 0U ) && ( Mv != 0U ) ) ) )"""
BUZZER_PARAMS = ["Old", "Sts", "Latch", "DrSts", "FullMv", "FullMvOld", "PP", "Sys", "Ds", "DsOld", "MvOld", "Mv"]


def test_a_masked_branch_is_dropped_at_once_not_searched_to_the_end():
    params = [f"U16 {p}" if p == "Sys" else f"U8 {p}" for p in BUZZER_PARAMS]
    text = H + "U8 g_o;\nvoid b(" + ", ".join(params) + ") { if (" + BUZZER + ") { g_o = 1U; } }\n"
    report = build_mcdc_design(_unit(text, "b", BUZZER_PARAMS))
    (d,) = report["decisions"]
    # without the masking check the default 4,096 steps ran out before the first condition was paired
    assert d["search_complete"] is True and d["reason"] == "no_pair_in_candidate_domain"
    assert {p["condition_id"] for p in d["pairs"]} == {f"C{i}" for i in (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 14, 16, 17, 18)}
    assert {c["condition_id"] for c in d["infeasible_conditions"]} == {"C13", "C15"}
    _assert_pairs_hold(report, d)


def test_sibling_paths():
    ir = ["||", ["&&", ["atom", 0], ["!", ["atom", 1]]], ["atom", 2]]
    paths = md._sibling_paths(ir)
    assert paths[0] == [("||", ["atom", 2]), ("&&", ["!", ["atom", 1]])]
    assert paths[1] == [("||", ["atom", 2]), ("&&", ["atom", 0])]
    assert paths[2] == [("||", ["&&", ["atom", 0], ["!", ["atom", 1]]])]


def test_kleene_tells_known_from_unknown():
    ir = ["||", ["&&", ["atom", 0], ["atom", 1]], ["!", ["atom", 2]]]
    assert md._kleene(ir, {}) is None
    assert md._kleene(ir, {2: False}) is True          # ``!c`` true decides the OR
    assert md._kleene(ir, {0: False, 2: True}) is False
    assert md._kleene(ir, {0: True, 2: True}) is None  # b still decides
    assert md._kleene(ir, {0: True, 1: True}) is True


# c11 false decides the second group before c12's component is reached: the rest of the vector is filled from it
TAIL = "(" + " && ".join(f"(a{i} == {i}U)" for i in range(11)) + ") || ((a11 == 11U) && ({}))"


def test_a_component_without_any_evaluable_vector_gives_no_row(monkeypatch):
    # every vector of one component undefined: no full vector can be evaluated, so no pair — also where that component
    #   is only needed to fill the rest of a decided branch (an empty list there must not end the search with an error)
    real = md._realizable_truths

    def none_realized(*args, realized_out=None, **kw):
        out = real(*args, realized_out=realized_out, **kw)
        if realized_out is not None:
            # c13's component (``a12``) — components come in variable-name order, so look it up by its condition
            (c,) = [k for k, (members, _r) in enumerate(realized_out) if 12 in members]
            realized_out[c] = (realized_out[c][0], {})
        return out
    monkeypatch.setattr(md, "_realizable_truths", none_realized)
    (d,) = _design(TAIL.format("a12 == 12U"))["decisions"]
    assert d["pairs"] == [] and d["status"] == "no_pair_found"


def test_the_rest_of_a_decided_branch_takes_a_value_its_component_realized_not_the_default():
    # U8's default 0 makes ``100U / a12`` undefined: the rows of the first group's pairs fill a12 from its component
    report = _design(TAIL.format("(100U / a12) == 5U"))
    (d,) = report["decisions"]
    assert {p["condition_id"] for p in d["pairs"]} == {f"C{i}" for i in range(1, 12)}
    assert all(p["inputs_a"]["a12"] != 0 for p in d["pairs"])
    _assert_pairs_hold(report, d)


def test_every_pair_the_search_claims_holds_on_evaluation(monkeypatch):
    # the three-valued search only yields where the outcome follows the condition: each claim costs two evaluations
    calls = [0]
    real = md._evaluate

    def counted(*args, **kw):
        calls[0] += 1
        return real(*args, **kw)
    monkeypatch.setattr(md, "_evaluate", counted)
    # (the undefined default: a first try with ``a12 = 0`` would fail and the search would back up to the same pair)
    for expression in (AND13, OR14, MIXED13, TAIL.format("a12 == 12U"), TAIL.format("(100U / a12) == 5U")):
        calls[0] = 0
        (d,) = _design(expression)["decisions"]
        assert calls[0] == 2 * len(d["pairs"]), expression


def test_summary_and_disclosure():
    units = [{"fid": "F1", "name": "w", "mcdc_design": _design(AND13)},
             {"fid": "F2", "name": "w", "mcdc_design": _design("((a0 > 5U) && (a0 < 3U)) || (" + AND13 + ")")}]
    s = summarize_mcdc_design(units)
    assert (s["wide_decisions"], s["wide_designed"]) == (2, 1)
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": s}) if i["key"] == "suts_mcdc_design"]
    assert "조건이 12 개보다 많은 결정 2 은 진리값 조합 전체(2^조건 수) 대신 조건마다 짝지었다" in item["note"]
    assert "조건 64 개까지 · 조건마다 탐색 4096 단계" in item["note"] and "설계 1)" in item["note"]
    # (review W3) the reference document gains rows where the function's base slots were free — not "unchanged"
    assert "기존 행의 자리 · 이름은 그대로다" in item["note"] and "정본 규모 문서에도 더해지고" in item["note"]
    assert "정본 규모 자리는 그대로다" not in item["note"]
    # (R72 measurement) the extended profile's searches take the new rows as bases · candidates
    assert "새 행이 더해지면 그 탐색이 고른 행이 바뀔 수 있다" in item["note"]
    for summary in ({k: v for k, v in s.items() if not k.startswith("wide_")}, {**s, "wide_decisions": 0}):
        (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary})
                   if i["key"] == "suts_mcdc_design"]
        assert "조건마다 짝지었다" not in item["note"]


def test_a_condition_that_reads_no_input_and_is_undefined_is_an_undefined_candidate_not_a_complete_search():
    # (review W1) ``(1U / 0U)`` is undefined on every vector: no pair can be evaluated — said as the product engine says it
    (d,) = _design(AND13 + " && (((U8)1U / (U8)0U) == 0U)")["decisions"]
    assert d["pairs"] == [] and d["reason"] == "no_pair_undefined_behavior_candidates_skipped"
    (small,) = _design("(a0 == 0U) && (((U8)1U / (U8)0U) == 0U)")["decisions"]
    assert small["reason"] == d["reason"]


def test_each_condition_has_its_own_step_budget():
    # (review W4) shared by the decision, an independent && chain lost its last conditions from 46 on (AND64: 32 pairs)
    params = [f"a{i}" for i in range(64)]
    (d,) = _design(" && ".join(f"(a{i} == {i}U)" for i in range(64)), params=params)["decisions"]
    assert d["status"] == "designed" and len(d["pairs"]) == 64 and d["search_complete"] is True


def test_a_condition_no_realized_tuple_changes_is_known_before_the_search():
    # (review W5) ``a62 != a62`` is false on every vector: every other condition is masked by it at once — a complete
    #   search with no pair, where the steps of 62 conditions used to run out (about ten seconds for one decision)
    params = [f"a{i}" for i in range(63)]
    (d,) = _design(" && ".join(f"(a{i} == {i}U)" for i in range(62)) + " && (a62 != a62)", params=params)["decisions"]
    assert d["pairs"] == [] and d["search_complete"] is True and d["reason"] == "no_pair_in_candidate_domain"
    # the reviewer's worst shape: each ``(a || b)`` group leaves three combinations, so unknown until the last
    #   component the search walks 3^8 of them per condition (past 4,096 steps) — known up front, none
    params = [f"a{i}" for i in range(8)] + [f"b{i}" for i in range(8)] + ["k"]
    groups = " && ".join(f"((a{i} == 1U) || (b{i} == 1U))" for i in range(8))
    (d,) = _design(groups + " && (k != k)", params=params)["decisions"]
    assert len(d["conditions"]) == 17 and d["pairs"] == []
    assert d["search_complete"] is True and d["reason"] == "no_pair_in_candidate_domain"


def test_the_decision_has_a_total_step_cap_over_its_conditions():
    # (review W5) 40 steps a condition is enough for AND20 (about 39 each), 16 × 40 for the decision is not
    params = [f"a{i}" for i in range(20)]
    (d,) = _design(" && ".join(f"(a{i} == {i}U)" for i in range(20)), params=params, max_candidates=40)["decisions"]
    assert d["status"] == "partial" and 0 < len(d["pairs"]) < 20 and d["search_complete"] is False
    assert d["reason"] == "candidate_budget_exhausted" and ("candidate_budget", "") in search_limits(d)
    assert md._WIDE_STEP_FACTOR == 16


def test_the_wide_cap_is_the_cap_the_pairs_are_re_evaluated_under():
    # (review I1) a larger cap would design pairs `evaluate_decision` refuses (every pair invalidated): clamped
    report = _design(AND13, max_wide_conditions=100)
    assert report["budgets"]["max_wide_conditions"] == 64   # what the design used
    params = [f"a{i}" for i in range(65)]
    (d,) = _design(" && ".join(f"(a{i} == {i}U)" for i in range(65)), params=params, max_wide_conditions=100)["decisions"]
    assert d["reason"] == "decision_or_condition_budget" and search_limits(d) == [("condition_cap", "65>64")]


# (review W2) one function: D1 13 conditions over the design inputs, D2 reads ``g_b`` — an input only the source reads
_ROOT = os.path.join(os.sep, "proj")
_COMMON = "#ifndef C_H\n#define C_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\n#endif\n"
_G = [f"g_a{i}" for i in range(13)]


def _source(first):
    return ('#include "common.h"\n' + "".join(f"U8 {g};\n" for g in _G) + "U8 g_b;\nU8 g_o;\n"
            "void f(void) { if (" + first + " && ".join(f"({g} == {i}U)" for i, g in enumerate(_G)) + ") { g_o = 1U; }"
            " if ((g_a0 > 5U) && (g_b > 3U)) { g_o = 2U; } }\n")


def _r58_unit(first=""):
    src = _source(first)
    path = os.path.join(_ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(_ROOT, "common.h"): _COMMON, path: src})
    return {"name": "f", "fid": "F1", "source_text": src, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(_G), "output_vars": ["g_o"],
            "param_types": {g: "U8" for g in [*_G, "g_b", "g_o"]}}


def test_the_second_pass_vectors_keep_their_row_names_after_the_wide_vectors():
    unit = _r58_unit()

    def gen():
        return generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    rows = complete_source_read_inputs(unit, gen(), gen)
    mcdc = {s["strategy"]: s["inputs"] for s in rows if s["strategy"].startswith("MCDC_")}
    d1, d2 = unit["mcdc_design"]["decisions"]
    assert d1["pair_search"] == "per_condition" and d1["status"] == "designed"
    assert d2["input_scope"] == "with_source_read_inputs" and d2["status"] == "designed"
    keys = {suts._mcdc_vector_key(p[f"inputs_{s}"]) for p in d2["pairs"] for s in "ab"}
    # D2's second-pass vectors are MCDC_7.. as before R72 (no base vector of its own); the wide decision's take the
    #   seven base slots and then follow them
    second = sorted(name for name, v in mcdc.items() if suts._mcdc_vector_key(v) in keys)
    assert second == [f"MCDC_{k}" for k in range(7, 7 + len(keys))]
    wide = sorted((int(n.split("_")[1]) for n, v in mcdc.items() if suts._mcdc_vector_key(v) not in keys))
    assert wide[:7] == list(range(7)) and min(wide[7:]) == 7 + len(keys)
    # (review C1) the wide rows after the second pass are the base design's: its finalize holds every pair, and their
    #   label names no second-pass design
    assert [p["retained_status"] for p in d1["pairs"]] == ["retained"] * 13
    second_label = "소스가 읽어 더한 입력까지 쓴 설계"
    for s in rows:
        if s["strategy"].startswith("MCDC_"):
            first = s["description"].split("\n")[0]
            assert (second_label in first) == (suts._mcdc_vector_key(s["inputs"]) in keys), (s["strategy"], first)
    # the reference profile: the wide decision fills the free base slots
    ref = _r58_unit()
    ref_rows = generate_sequences(ref, None, type_cache={})
    assert sorted(s["strategy"] for s in ref_rows if s["strategy"].startswith("MCDC_")) == [f"MCDC_{k}" for k in range(7)]


def test_without_a_second_pass_the_wide_rows_past_the_base_slots_are_base_rows():
    # (review C1b) every input is a design input: no second pass — MCDC_7.. are the wide decision's own rows
    unit = dict(_r58_unit(), input_vars=[*_G, "g_b"])
    rows = generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    mcdc = [s for s in rows if s["strategy"].startswith("MCDC_")]
    assert len(mcdc) > 7
    assert not (unit["mcdc_design"].get("source_read_pass") or {}).get("decisions_adopted")
    assert not any("소스가 읽어 더한 입력까지 쓴 설계" in s["description"] for s in mcdc)
    d1 = unit["mcdc_design"]["decisions"][0]
    assert d1["pair_search"] == "per_condition"
    assert {p["retained_status"] for p in d1["pairs"]} == {"retained"} and len(d1["pairs"]) == 13


def test_a_wide_decision_the_second_pass_designs_comes_after_the_others():
    # (review W2a) D1 reads g_b too: both are designed by the second pass — D2's vectors first, as without R72
    unit = _r58_unit("(g_b == 1U) && ")
    base = build_mcdc_design(dict(unit))
    assert [d["reason"] for d in base["decisions"]] == ["decision_variable_not_in_unit_inputs:g_b"] * 2
    ext = suts._mcdc_source_read_pass(dict(unit, input_vars=[*_G, "g_b"]), base, lambda: {}, ["g_b"])
    d1, d2 = ext["decisions"]
    assert d1["pair_search"] == "per_condition" and d2.get("pair_search") is None
    keys = [suts._mcdc_vector_key(v) for v in ext["vectors"]]
    d2_keys = {suts._mcdc_vector_key(p[f"inputs_{s}"]) for p in d2["pairs"] for s in "ab"}
    assert sorted(keys.index(k) for k in d2_keys) == list(range(len(d2_keys)))


def _random_tree(rng, n, pool):
    def atom():
        k, k2, c = rng.randrange(5), rng.randrange(5), rng.choice([0, 1, 2, 3, 5])
        return rng.choice([f"(a{k} == {c}U)", f"(a{k} != {c}U)", f"(a{k} > {c}U)", f"(a{k} < {c}U)",
                           f"((a{k} & {c}U) == {c}U)", f"(a{k} < a{k2})", f"((a{k} + a{k2}) == {c}U)",
                           f"((100U / a{k}) == {c + 20}U)"])
    if n == 1:
        a = rng.choice(pool) if pool and rng.random() < 0.2 else atom()
        pool.append(a)
        return ("!" + a) if rng.random() < 0.2 else a
    left = rng.randrange(1, n)
    s = f"({_random_tree(rng, left, pool)} {rng.choice(['&&', '||'])} {_random_tree(rng, n - left, pool)})"
    return ("!" + s) if rng.random() < 0.2 else s


def test_the_condition_by_condition_search_finds_what_the_product_finds():
    # (review I6) seeded differential: forced to pair condition by condition (`max_conditions=0`), the same decisions
    #   as the exhaustive product engine — the same paired conditions, reason and completeness
    rng = random.Random(72)
    params = [f"a{i}" for i in range(5)]
    compared = 0
    for _ in range(60):
        expression = _random_tree(rng, rng.randrange(2, 9), [])
        product = _design(expression, params=params, max_conditions=64, max_candidates=1 << 16)
        wide = _design(expression, params=params, max_conditions=0, max_candidates=1 << 16)
        (p,), (w,) = product["decisions"], wide["decisions"]
        if "unsupported" in (p["status"], w["status"]):
            continue
        compared += 1
        assert w["pair_search"] == "per_condition"
        assert {x["condition_id"] for x in w["pairs"]} == {x["condition_id"] for x in p["pairs"]}, expression
        assert w["reason"] == p["reason"], expression
        assert p["status"] == "designed" or w["search_complete"] == p["search_complete"], expression
        _assert_pairs_hold(wide, w)
    assert compared >= 40
