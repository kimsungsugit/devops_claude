"""R56 — the MC/DC path search budget per function is ×4 the R2c budget (6,144 runs · 120,000 steps).

KJPDS02_PV (same inputs): ×1 793 · ×2 808 · ×4 824 · ×16 834 designed decisions of 1,469 — no designed decision lost, no
expected value changed. The budget stays a deterministic cost bound and is written in every report.
"""
from __future__ import annotations

import json

from generators.mcdc_design import PATH_SEARCH_RUNS, PATH_SEARCH_STEPS, build_mcdc_design
from tests.unit.test_mcdc_path_design import H, _unit

# a decision on two locals, each the XOR of two inputs: the pair needs both XORs placed — beyond 1,536 runs
XOR = H + ("U8 g_o;\nvoid f(U8 a, U8 b, U8 c, U8 d, U8 e) { U8 t = (U8)(a ^ b); U8 u = (U8)(c ^ d); "
           "if ((t == 77U) && (u == 13U) && (e == 5U)) { g_o = 1U; } }\n")
INPUTS = ["a", "b", "c", "d", "e"]


def test_the_default_budget_is_written_in_the_report():
    report = build_mcdc_design(_unit(XOR, "f", INPUTS))
    assert (PATH_SEARCH_RUNS, PATH_SEARCH_STEPS) == (6144, 120_000)
    assert report["budgets"]["max_path_runs"] == 6144 and report["budgets"]["max_path_steps"] == 120_000


def test_a_decision_the_old_budget_could_not_pair_is_designed():
    old = build_mcdc_design(_unit(XOR, "f", INPUTS), max_path_runs=1536, max_path_steps=30_000)["decisions"][-1]
    assert (old["status"], old["reason"]) == ("no_pair_found", "path_search_no_pair")
    new = build_mcdc_design(_unit(XOR, "f", INPUTS))["decisions"][-1]
    assert (new["status"], new["reason"]) == ("designed", "unique_cause_pairs_found")
    assert len(new["pairs"]) == 3 and 1536 < new["path_search"]["runs"] <= PATH_SEARCH_RUNS
    assert new["search_complete"] is False                     # a found pair proves the pair, not the search complete


def test_the_budget_is_in_the_summary_and_the_disclosure():
    """(review I1) the document says which budget designed it — the same source under another budget pairs otherwise."""
    from generators.suts import summarize_mcdc_design
    from report_gen.generation_disclosures import build_disclosures
    summary = summarize_mcdc_design([{"mcdc_design": build_mcdc_design(_unit(XOR, "f", INPUTS))}])
    assert summary["path_search_budget"] == [{"max_path_runs": 6144, "max_path_steps": 120_000}]
    item = {i["key"]: i for i in build_disclosures("suts", {"mcdc_design_summary": summary})}["suts_mcdc_design"]
    assert "벡터 6,144 · 인터프리터 단계 120,000" in item["note"]
    # a caller's own budget is written too; no report, no budget sentence
    other = summarize_mcdc_design([{"mcdc_design": build_mcdc_design(_unit(XOR, "f", INPUTS), max_path_runs=64,
                                                                     max_path_steps=500)},
                                   {"mcdc_design": build_mcdc_design(_unit(XOR, "f", INPUTS))}])
    assert other["path_search_budget"] == [{"max_path_runs": 64, "max_path_steps": 500},
                                           {"max_path_runs": 6144, "max_path_steps": 120_000}]
    none = summarize_mcdc_design([{}])
    assert none["path_search_budget"] is None
    item = {i["key"]: i for i in build_disclosures("suts", {"mcdc_design_summary": none})}["suts_mcdc_design"]
    assert "탐색 예산" not in item["note"]


def test_the_raised_budget_is_still_deterministic():
    first = build_mcdc_design(_unit(XOR, "f", INPUTS))
    again = build_mcdc_design(_unit(XOR, "f", INPUTS))
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(again, sort_keys=True, default=str)
