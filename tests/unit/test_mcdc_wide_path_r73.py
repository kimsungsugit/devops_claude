"""R73 — the modeled-run search pairs a decision of more conditions than the truth product takes, condition by condition.

A decision the expression engine refuses (a local, an input written before it, a call's value) goes to the modeled-run
search (`mcdc_design._path_design`), which refused it outright past 12 conditions — R72 measured HDPDM01 1 and
KJPDS02_PV 7 such decisions (door state machines, buzzer conditions, the MCU error check). Now each search group's wide
decisions get their own group (same flags, own budget, after every other group: the others' rows, order and budgets
stay) with a targeted climb per condition: move the inputs of the first sibling on the condition's path (in evaluation
order) that does not hold its non-controlling value, keep the best vector, and where no sibling masks the condition move
its own inputs — the pairer takes the pair (short-circuit unique cause). A failed climb is a local best, not a proof.
"""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import c_source_oracle as cso
from generators import mcdc_design as md
from generators import suts
from generators.mcdc_design import build_mcdc_design, search_limits
from generators.suts import summarize_mcdc_design
from report_gen.generation_disclosures import build_disclosures
from tests.unit.test_mcdc_path_design import H, _unit

N = [f"a{i}" for i in range(13)]
# ``t`` is a local: the expression engine refuses every decision reading it (`local_variable_not_input:`)
AND13 = "U8 t = a0; if ((t == 1U) && " + " && ".join(f"(a{i} == {1 + i % 3}U)" for i in range(1, 13)) + ") { g_o = 1U; }"
OR_OF_ANDS = ("U8 t = a0; if (((t == 1U) && (a1 == 2U) && (a2 == 3U)) || ((a3 == 1U) && (a4 == 1U)) || "
              "((a5 == 1U) && (a6 == 1U) && (a7 == 1U)) || ((a8 == 1U) && (a9 == 1U)) || "
              "((a10 == 1U) && (a11 == 1U) && (a12 == 1U))) { g_o = 2U; }")
OR16 = ("U8 t = a0; if ((t == 1U) || " + " || ".join(f"(a{i} == 1U)" for i in range(1, 13))
        + " || (a1 == 7U) || (a2 == 9U) || (a3 == 11U)) { g_o = 3U; }")
SMALL = "if ((a0 > 3U) && (a1 == 2U)) { g_o = 9U; }"


def _src(*bodies):
    return H + "U8 g_o;\nvoid f(" + ", ".join(f"U8 {p}" for p in N) + ") { " + " ".join(bodies) + " }\n"


def _design(*bodies, **kw):
    unit = _unit(_src(*bodies), "f", N)
    return unit, build_mcdc_design(unit, **kw)


def _assert_pairs_hold(unit, decision):
    """Each pair member re-observed on the modeled run: an evaluation with the claimed truths · evaluated conditions ·
    outcome, and the two differ in this condition alone where both evaluated it (short-circuit unique cause)."""
    for pair in decision["pairs"]:
        i = int(pair["condition_id"][1:]) - 1
        runs = cso.observe_decisions(unit, [pair["inputs_a"], pair["inputs_b"]], [decision["path_spec"]])
        for side, run in zip("ab", runs, strict=True):
            claimed = {"truth": pair[f"truth_{side}"], "observed": pair[f"observed_{side}"],
                       "decision": pair[f"decision_{side}"]}
            assert run["status"] == "supported" and claimed in run["decisions"][0]["instances"], (pair["pair_id"], side)
        assert md._short_circuit_unique_cause({"truth": pair["truth_a"], "observed": pair["observed_a"],
                                               "decision": pair["decision_a"]},
                                              {"truth": pair["truth_b"], "observed": pair["observed_b"],
                                               "decision": pair["decision_b"]}, i)


def test_wide_decisions_the_expression_engine_refuses_are_searched_condition_by_condition():
    for body, conditions in ((AND13, 13), (OR_OF_ANDS, 13), (OR16, 16)):
        unit, report = _design(body)
        (d,) = report["decisions"]
        assert d["evaluation"] == "source_path" and d["pair_search"] == "path_targeted", body
        assert len(d["conditions"]) == conditions and d["status"] == "designed" and len(d["pairs"]) == conditions, body
        assert search_limits(d) == []
        _assert_pairs_hold(unit, d)


def test_the_other_decisions_keep_their_design_rows_and_budget():
    # D1 wide (a local), D2 an ordinary modeled-run decision (reads t too), D3 the expression engine's
    body = (AND13, "if ((t == 1U) && (a1 == 3U)) { g_o = 5U; }", SMALL)
    _unit_new, new = _design(*body)
    _unit_old, old = _design(*body, max_wide_conditions=12)   # the cap as before R72 / R73: D1 not searched
    assert old["decisions"][0]["reason"] == "path_refused:decision_or_condition_budget"
    assert new["decisions"][0]["pair_search"] == "path_targeted" and new["decisions"][0]["status"] == "designed"
    for k in (1, 2):
        assert new["decisions"][k]["pairs"] == old["decisions"][k]["pairs"]
        assert new["decisions"][k].get("path_search") == old["decisions"][k].get("path_search")
    n = len(old["selected_inputs"])
    assert new["selected_inputs"][:n] == old["selected_inputs"]
    assert new["wide_vector_count"] == len(new["selected_inputs"]) - n > 0


def test_a_condition_no_value_can_make_decide_ends_the_climb_without_a_pair():
    # ``t == 1U`` and ``t == 2U`` are never true together: under the && neither shows an effect, nor does any other
    body = "U8 t = a0; if ((t == 1U) && (t == 2U) && " + " && ".join(f"(a{i} == 1U)" for i in range(1, 12)) + ") { g_o = 1U; }"
    unit, report = _design(body)
    (d,) = report["decisions"]
    assert d["pair_search"] == "path_targeted" and d["pairs"] == [] and d["status"] == "no_pair_found"
    assert d["reason"] == "path_search_no_pair"
    # (review W3) every condition's climbs stopped at a local best — named, not silent; the frontier after them then
    #   spent this decision's share of the budget (a budget limit, as any cut search)
    #   — only the conditions a run evaluated (review R2-I1): the ones after the always-false ``t == 2U`` never are
    limits = dict(search_limits(d))
    assert limits["targeted_local_best"] == "C1,C2"
    assert "path_budget" in limits


def test_distance_counts_the_conditions_to_change():
    # the climb's objective: it must fall one per right move for a multi-condition sibling, or the climb stops at once
    ir = ["&&", ["&&", ["atom", 0], ["atom", 1]], ["||", ["atom", 2], ["!", ["atom", 3]]]]
    paths = md._sibling_paths(ir)
    assert paths[0] == [("&&", ["||", ["atom", 2], ["!", ["atom", 3]]]), ("&&", ["atom", 1])]
    both = ["&&", ["atom", 0], ["atom", 1]]
    assert md._distance(both, True, {}) == 2                      # unknown counts as one each
    assert md._distance(both, True, {0: True}) == 1
    assert md._distance(both, True, {0: True, 1: True}) == 0
    assert md._distance(both, False, {0: True, 1: True}) == 1     # either side alone decides false
    either = ["||", ["atom", 2], ["!", ["atom", 3]]]
    assert md._distance(either, True, {2: False, 3: True}) == 1
    assert md._distance(either, True, {3: False}) == 0            # !c true decides the ||
    assert md._distance(either, False, {2: False, 3: True}) == 0
    assert md._leaves(ir) == [0, 1, 2, 3]


def test_summary_and_disclosure():
    _unit_a, a = _design(AND13)
    s = summarize_mcdc_design([{"fid": "F1", "name": "f", "mcdc_design": a}])
    assert (s["wide_path_decisions"], s["wide_path_designed"], s["wide_decisions"]) == (1, 1, 0)
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": s}) if i["key"] == "suts_mcdc_design"]
    assert "함수 실행 모델로 탐색한 조건 12 개 초과 결정 1 은" in item["note"] and "(설계 1)" in item["note"]
    assert "불가 증명이 아니다" in item["note"] and "진리값 조합 전체(2^조건 수) 대신" not in item["note"]
    assert "`targeted_local_best`" in item["note"]
    # (review W2) the placement of the new rows is said for the modeled run's wide decisions too
    assert "정본 규모 문서에도 더해지고" in item["note"] and "그 탐색이 고른 행이 바뀔 수 있다" in item["note"]
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": {**s, "wide_path_decisions": 0}})
               if i["key"] == "suts_mcdc_design"]
    assert "함수 실행 모델로 탐색한 조건" not in item["note"]


# an && of ||-pairs and comparisons: the climb's two ways forward (the first unsatisfied sibling in evaluation order,
#   and the condition's own inputs where that sibling was not evaluated) each make up for the other's absence here —
#   both missing it pairs 9 of 13 (R73 mutation check T3 + T4)
MIX = ("U8 t = a0; if ((t != 0U) && ((a1 == 1U) || (a2 == 1U)) && (a3 == 3U) && "
       "((a4 == 2U) || ((a5 == 3U) && (a6 == 1U))) && (a7 < 3U) && (a8 > 2U) && "
       "((a9 == 1U) || (a10 == 2U)) && (a11 != 3U) && (a12 == 2U)) { g_o = 4U; }")


_ROOT = os.path.join(os.sep, "proj")
_COMMON = "#ifndef C_H\n#define C_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\n#endif\n"
_G = [f"g_a{i}" for i in range(13)]


def test_a_wide_modeled_run_decision_the_second_pass_designs_comes_after_the_others():
    # D1 reads a local (modeled run) and g_b — an input only the source reads: the base design has no pair for it,
    #   the R58 second pass designs it with its targeted climb; D2 (reads g_b too) is an ordinary second-pass decision.
    #   D2's vectors come first, as they did before R73 (when D1 was refused)
    src = ('#include "common.h"\n' + "".join(f"U8 {g};\n" for g in _G) + "U8 g_b;\nU8 g_o;\n"
           "void f(void) { U8 t = g_a0; if ((g_b == 1U) && (t == 1U) && "
           + " && ".join(f"({g} == 1U)" for g in _G[1:]) + ") { g_o = 1U; }"
           " if ((g_a0 > 5U) && (g_b > 3U)) { g_o = 2U; } }\n")
    path = os.path.join(_ROOT, "unit.c")
    context = cpc.build_project_context({os.path.join(_ROOT, "common.h"): _COMMON, path: src})
    unit = {"name": "f", "fid": "F1", "source_text": src, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(_G), "output_vars": ["g_o"],
            "param_types": {g: "U8" for g in [*_G, "g_b", "g_o"]}}
    base = build_mcdc_design(dict(unit))
    assert not any(d["pairs"] for d in base["decisions"])
    ext = suts._mcdc_source_read_pass(dict(unit, input_vars=[*_G, "g_b"]), base, lambda: {}, ["g_b"])
    d1, d2 = ext["decisions"]
    assert d1["pair_search"] == "path_targeted" and d1["pairs"] and d2.get("pair_search") is None and d2["pairs"]
    keys = [suts._mcdc_vector_key(v) for v in ext["vectors"]]
    d2_keys = {suts._mcdc_vector_key(p[f"inputs_{s}"]) for p in d2["pairs"] for s in "ab"}
    assert sorted(keys.index(k) for k in d2_keys) == list(range(len(d2_keys)))


# (review: one decision that tells both climb rules apart — the first unsatisfied sibling in evaluation order, and the
#   condition's own inputs where that sibling was not evaluated: either one missing loses pairs here)
TELLS = ("U8 t = a0; if (((((((a1 < 3U) && (a10 != 3U)) && (a7 == 0U)) && (a9 != 3U)) || (((a3 == 2U) && "
         "!((a11 > 4U) || (a7 != 1U))) || !((a5 > 1U) && (a2 == 3U)))) || (a11 > 1U)) || !((((a10 != 4U) && "
         "(t == 1U)) || (a10 > 2U)) && (a12 != 4U))) { g_o = 4U; }")


def test_the_climb_rules_each_find_their_pairs():
    # (review R2-W3: one start only (no restart) pairs 11 — the exact set tells them apart)
    unit, report = _design(TELLS)
    (d,) = report["decisions"]
    assert {p["condition_id"] for p in d["pairs"]} == {f"C{i}" for i in (1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14)}
    _assert_pairs_hold(unit, d)


# (review R2-W3) the target sibling in evaluation order: root first, this decision pairs none
ORDER = ("U8 t = a0; if ((((a2 != 2U) && (a4 != 4U)) && (((((a12 == 2U) && (a11 != 1U)) || (a4 > 3U)) && (t == 1U)) && "
         "((a9 > 1U) && (a9 > 3U)))) && (((a4 < 2U) && (((a8 < 3U) && (a3 > 1U)) || (a1 < 3U))) && ((a12 < 4U) && "
         "(a5 > 2U)))) { g_o = 4U; }")


def test_the_target_sibling_is_taken_in_evaluation_order():
    unit, report = _design(ORDER)
    (d,) = report["decisions"]
    assert {p["condition_id"] for p in d["pairs"]} == {f"C{i}" for i in (1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 14)}
    _assert_pairs_hold(unit, d)


def test_a_condition_whose_inputs_are_not_known_widens_the_moved_inputs():
    # (review R2-I3) ``v`` is written through a pointer (``*p = a3``): its inputs are not followed, so a sibling holding
    #   ``v == 2U`` moves every input — otherwise this decision pairs 7 (C4 · C13 lost)
    body = ("U8 t = a0; U8 v = 0U; U8 *p = &v; *p = a3; if (((a4 > 2U) || (((a8 == 3U) || !((a1 == 1U) || (a11 > 2U))) "
            "|| (!((((a10 < 3U) || (t == 1U)) || (a4 == 0U)) || ((v == 2U) || (a8 < 2U))) || (a7 < 2U)))) && "
            "((a12 != 1U) || !(((a10 != 3U) && (a4 == 2U)) || (a6 > 2U)))) { g_o = 4U; }")
    unit, report = _design(body)
    (d,) = report["decisions"]
    assert {p["condition_id"] for p in d["pairs"]} == {f"C{i}" for i in (1, 2, 3, 4, 10, 11, 12, 13, 14)}
    _assert_pairs_hold(unit, d)


def test_restarts_wait_until_every_condition_had_a_climb_and_the_stub_pass_climbs_them_all():
    # (review R2-W1 · R2-W2) a loop makes each run cost about 400 steps: restarting a failing condition at once spent the
    #   step budget before the last condition (which pairs the others on its way) had a climb — 0 / 14; the stub pass
    #   skipping the conditions the first search paired rebuilt nothing for C13 and C14 — 12 / 14
    body = ("U8 k; U8 r = get(); U8 t = a0; for (k = 0U; k < 40U; k++) { g_x = (U8)(g_x + 1U); } if ((t == 1U) && "
            + " && ".join(f"(a{i} == 1U)" for i in range(1, 12)) + " && ((a12 != 1U) || (r == 3U))) { g_o = 1U; }")
    text = H + "U8 g_x;\nU8 g_o;\nU8 get(void) { return g_x; }\nvoid f(" + ", ".join(f"U8 {p}" for p in N) + ") { " + body + " }\n"
    unit = _unit(text, "f", [*N, "get() return"])
    (d,) = [x for x in build_mcdc_design(unit)["decisions"] if len(x["conditions"]) > 12]
    assert d["pair_search"] == "path_targeted" and len(d["pairs"]) == 14 and d["status"] == "designed"
    _assert_pairs_hold(unit, d)


def test_a_wide_group_does_not_take_the_pointee_group_s_inputs():
    # (review W1) the narrow pointee group adds ``pq[0].cnt`` to the domains it shares; the wide "" group after it must
    #   not search on it (R40 W3: only the pointee group's rows set pointees)
    header = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef struct { U8 cnt; U8 v; } Q;\n"
    globals_ = [f"g_e{i}" for i in range(1, 13)]
    text = ('#include "h.h"\nU8 g_o;\nU8 g_en;\n' + "".join(f"U8 {g};\n" for g in globals_)
            + "void w4(Q *pq) { U8 t = g_en; if ((t > 3U) && " + " && ".join(f"({g} == 1U)" for g in globals_)
            + ") { g_o = 2U; } if ((t > 5U) && (g_e1 == 2U)) { g_o = 4U; } if ((pq->cnt > 3U) && (g_en == 1U)) { g_o = 3U; } }\n")
    root = os.path.join(os.sep, "p73")
    path = os.path.join(root, "u.c")
    context = cpc.build_project_context({os.path.join(root, "h.h"): header, path: text})
    unit = {"name": "w4", "source_text": text, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": ["pq[0].cnt", "g_en", *globals_]}
    declared = {g: {"min": 0, "max": 255, "type": "uint8_t", "source": "declared_type", "origin": "global"}
                for g in ["g_en", *globals_]}
    report = build_mcdc_design(unit, declared_domains=declared)
    wide = report["decisions"][0]
    assert wide["pair_search"] == "path_targeted" and wide["pairs"]
    assert "pq[0].cnt" not in wide["path_search"]["inputs"]
    assert not any("pq[0].cnt" in {**p["inputs_a"], **p["inputs_b"]} for p in wide["pairs"])


def _random_body(seed):
    import random
    rng = random.Random(seed)
    leaves = ["(t == 1U)"] + [f"(a{rng.randint(1, 12)} {rng.choice(['==', '>', '<', '!='])} {rng.randint(0, 4)}U)"
                              for _ in range(rng.randint(13, 16) - 1)]
    rng.shuffle(leaves)

    def tree(items):
        if len(items) == 1:
            return items[0]
        k = rng.randint(1, len(items) - 1)
        left, right = tree(items[:k]), tree(items[k:])
        return ("!" if rng.random() < 0.1 else "") + f"({left} {rng.choice(['&&', '||'])} {right})"
    return "U8 t = a0; if " + tree(leaves) + " { g_o = 4U; }"


def test_every_condition_the_climb_misses_is_named():
    # (review W3) seeded differential: the same decision with the local replaced by its input goes to the expression
    #   engine; a condition it pairs and the climb does not is named on the decision (`targeted_local_best`) or the
    #   decision's search hit its budget — never a silent miss. And the climb finds most of them.
    expr_total = path_total = 0
    for seed in range(8):
        body = _random_body(seed)
        (e,) = _design(body.replace("U8 t = a0; ", "").replace("(t == 1U)", "(a0 == 1U)"))[1]["decisions"]
        (p,) = _design(body)[1]["decisions"]
        paired = {x["condition_id"] for x in p["pairs"]}
        missed = {x["condition_id"] for x in e["pairs"]} - paired
        limits = dict(search_limits(p))
        named = set((limits.get("targeted_local_best") or "").split(",")) - {""}
        assert not missed - named or "path_budget" in limits, (seed, missed, limits)
        expr_total += len(e["pairs"])
        path_total += len(paired)
    assert path_total >= 0.85 * expr_total, (path_total, expr_total)


def _design_params(params, *bodies, **kw):
    text = H + "U8 g_o;\nvoid f(" + ", ".join(f"U8 {p}" for p in params) + ") { " + " ".join(bodies) + " }\n"
    unit = _unit(text, "f", list(params))
    return unit, build_mcdc_design(unit, **kw)


def test_a_condition_on_a_local_moves_the_inputs_the_local_comes_from():
    # (review W3 · I4) ``t = a0 + 1``: the climb moves a0 for ``t == 2U`` — not all 43 inputs (30 the decision never
    #   reads); 800 runs are enough that way (about 600), not with every input moved (about 930)
    params = [f"a{i}" for i in range(13)] + [f"z{i}" for i in range(30)]
    body = ("U8 t = (U8)(a0 + 1U); if ((t == 2U) && " + " && ".join(f"(a{i} == {1 + i % 3}U)" for i in range(1, 13))
            + ") { g_o = 1U; }")
    unit, report = _design_params(params, body, max_path_runs=800)
    (d,) = report["decisions"]
    assert d["status"] == "designed" and len(d["pairs"]) == 13
    _assert_pairs_hold(unit, d)
    assert md._condition_inputs is not None and md._local_sources is not None


def test_each_wide_decision_has_its_own_budget():
    # (review W3, measured) the first wide decision never pairs (``t == 1U && t == 2U``): searched with the second on one
    #   budget, its climbs and frontier spent the step budget and the second got none — each is searched alone now
    #   (on other inputs: the first one's runs, which every decision's pairer sees, do not happen to pair it)
    params = [f"a{i}" for i in range(13)] + [f"b{i}" for i in range(13)]
    never = "U8 t = a0; if ((t == 1U) && (t == 2U) && " + " && ".join(f"(a{i} == 1U)" for i in range(1, 12)) + ") { g_o = 1U; }"
    ok = "U8 u = b0; if ((u == 1U) && " + " && ".join(f"(b{i} == {1 + i % 3}U)" for i in range(1, 13)) + ") { g_o = 2U; }"
    unit, report = _design_params(params, never, ok, max_path_runs=1536)
    first, second = report["decisions"]
    assert first["pairs"] == [] and ("path_budget", "") in search_limits(first)
    assert second["status"] == "designed" and len(second["pairs"]) == 13


def test_the_climb_finds_most_conditions_of_a_mixed_decision():
    unit, report = _design(MIX)
    (d,) = report["decisions"]
    assert d["pair_search"] == "path_targeted" and len(d["conditions"]) == 13 and len(d["pairs"]) >= 10
    _assert_pairs_hold(unit, d)
