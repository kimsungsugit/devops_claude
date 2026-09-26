"""R15 — behavioural boundary rows (`generators/boundary_rows.py`, extended SUTS only).

For one input the source oracle samples a range's ends and the constants the body names (±1), or a value set whole;
where two neighbouring samples give different derived outputs a bisection finds the adjacent pair and both become rows
when the change is a step (not a slope, not an alternation). Nothing here asserts an expected value — the rows get
theirs from the same oracle as every other row. Every value below is what C computes on a 16-bit-int target (as the
oracle models it)."""
from __future__ import annotations

import os

import pytest

from generators import boundary_rows as br
from generators import c_project_context as cpc
from generators.suts import generate_sequences, is_extended_strategy

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
#define K_SEL 7U
#define K_HUGE 1e400
typedef enum { M_A = 0, M_B = 1, M_C = 5, M_D = 9 } Mode_t;
#endif
"""
UNIT = """#include "common.h"
U8 g_a;
U8 g_b;
U8 g_c;
U8 g_o;
U16 g_w;
Mode_t g_m;
U8 ext(void);
void gt(void) { if (g_a > 10U) { g_o = 1U; } else { g_o = 2U; } }
void eq(void) { if (g_b == K_SEL) { g_o = 5U; } else { g_o = 6U; } }
void twice(void) { U16 x = (U16)g_a * 2U; if (x >= 100U) { g_o = 1U; } else { g_o = 0U; } }
void unknown(void) { if (g_a > 10U) { g_o = ext(); } else { g_o = ext(); } }
void flat(void) { g_o = 4U; }
void lin(void) { g_w = (U16)g_a * 2U; }
void ramp(void) { g_w = (U16)g_a + (U16)g_a; }
void parity(void) { g_o = (U8)(g_a & 1U); }
void mix(void) { g_w = (U16)g_a * 2U; if (g_a > 10U) { g_o = 1U; } else { g_o = 2U; } }
void pick(void) { if (g_a > 10U) { g_o = g_b; } else { g_o = 0U; } }
void sel(void) { if (g_a > 10U) { g_o = g_b; } else { g_o = g_c; } }
void mode(void) { if (g_m > M_B) { g_o = 1U; } else { g_o = 2U; } }
void octal(void) { const char *t = "08:05"; if (g_a > 010) { g_o = 1U; } else { g_o = 2U; } (void)t; }
void tbl(void) { switch (g_m) { case M_A: g_o = 0U; break; case M_B: g_o = 1U; break; default: g_o = 2U; break; } }
void one(void) { if (g_a == 1U) { g_o = 1U; } else { g_o = 0U; } }
void last(void) { if (g_m == M_D) { g_o = 1U; } else { g_o = 0U; } }
S16 g_s;
void neg(void) { if (g_s == -5) { g_o = 1U; } else { g_o = 0U; } }
void sub(void) { g_o = (U8)(g_a - 5U); }
void dev(void) { if (g_b == 3U) { if (g_a > 10U) { g_o = 1U; } else { g_o = 2U; } } }
void guard(void) { if (g_b == 0U) { g_o = 0U; g_w = 0U; return; } if (g_a > 10U) { g_o = 1U; } else { g_o = 2U; } }
S16 g_s2;
#define K_LIM 5
void cneg(void) { switch (g_s2) { case -5: g_o = 1U; break; default: g_o = 0U; break; } }
void nname(void) { if (g_s2 == -K_LIM) { g_o = 1U; } else { g_o = 0U; } }
void negu(void) { S16 t = -40; if (g_a == 7U) { g_o = 2U; } else { g_o = (U8)(t + 44); } }
void huge(void) { if (g_a > 10U) { g_o = (U8)(K_HUGE > 0); } else { g_o = 2U; } }
"""


def _unit(name):
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    return {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path]}


U8 = (0, 255)


def _find(name, base, domains, outputs=("g_o",), **kw):
    return br.find_boundaries(_unit(name), [{"inputs": b, "strategy": f"B{i}"} for i, b in enumerate(base)],
                              domains, list(outputs), **kw)


def _values(found, var):
    return sorted(r["inputs"][var] for r in found["rows"])


# ── the search ────────────────────────────────────────────────────────────

def test_a_threshold_gets_both_adjacent_inputs():
    found = _find("gt", [{"g_a": 0}], {"g_a": U8})
    assert _values(found, "g_a") == [10, 11]
    assert {(r["side"], r["lo"], r["hi"]) for r in found["rows"]} == {("lo", 10, 11), ("hi", 10, 11)}
    assert found["rows"][0]["outputs_changed"] == ["g_o"] and found["report"]["boundaries"] == 1
    assert found["report"]["status"] == "searched"


def test_an_equality_to_a_macro_gets_both_sides():
    found = _find("eq", [{"g_b": 0}], {"g_b": U8})
    assert _values(found, "g_b") == [6, 7, 8]   # (6,7) and (7,8): the shared 7 is one row
    assert found["report"]["boundaries"] == 2


def test_a_threshold_on_a_local_is_found_on_the_input():
    """``x = g_a * 2; x >= 100`` — the flip is at g_a 49 → 50, which no constant in the body names."""
    assert _values(_find("twice", [{"g_a": 0}], {"g_a": U8}), "g_a") == [49, 50]


def test_an_existing_vector_is_not_added_again_and_a_boundary_is_searched_once():
    found = _find("gt", [{"g_a": 0}, {"g_a": 255}], {"g_a": U8}, existing=[{"g_a": 11}])
    assert _values(found, "g_a") == [10] and found["report"]["boundaries"] == 1


def test_an_output_the_oracle_cannot_derive_is_no_boundary():
    found = _find("unknown", [{"g_a": 0}], {"g_a": U8})
    assert found["rows"] == [] and found["report"]["evaluations"] > 0


def test_a_function_without_a_change_adds_nothing():
    found = _find("flat", [{"g_a": 3}], {"g_a": U8})
    assert found["rows"] == [] and found["report"]["boundaries"] == 0


def test_a_linear_stretch_is_skipped_between_samples():
    """The body names ``2``: samples 0,1,2,3,255 all lie on one line — every inner segment is skipped unsearched."""
    found = _find("lin", [{"g_a": 0}], {"g_a": U8}, outputs=("g_w",))
    assert found["rows"] == [] and found["report"]["linear_segments_skipped"] >= 1


def test_a_ramp_the_samples_cannot_see_is_rejected_at_the_pair():
    """No constant in ``g_a + g_a``: one segment 0..255, no neighbour to compare slopes with — the bisection lands on
    0/1 and the step check (the next input, the domain edge on the other side) sees the same slope."""
    found = _find("ramp", [{"g_a": 0}], {"g_a": U8}, outputs=("g_w",))
    assert found["rows"] == [] and found["report"]["slope_steps_rejected"] >= 1


def test_an_alternation_is_no_boundary():
    assert _find("parity", [{"g_a": 4}], {"g_a": U8})["rows"] == []


def test_a_step_is_found_beside_a_slope_on_another_output():
    """The linear ``g_w`` differs across every segment; bisecting on it alone would land anywhere. Per output, only
    ``g_o``'s step at 10 → 11 is a boundary."""
    found = _find("mix", [{"g_a": 0}], {"g_a": U8}, outputs=("g_w", "g_o"))
    assert _values(found, "g_a") == [10, 11]
    assert found["rows"][0]["outputs_changed"] == ["g_w", "g_o"]


# ── bases and fill values ─────────────────────────────────────────────────

def test_a_sparse_base_is_completed_with_the_callers_defaults():
    """An MC/DC vector sets only what its decision reads: with ``g_b`` unset the true branch's output is underived and
    no boundary shows. The caller's mid value (moved by the input's position) completes the base, and each row names
    what was filled."""
    domains = {"g_a": U8, "g_b": U8}
    assert _find("pick", [{"g_a": 0}], domains)["rows"] == []
    found = _find("pick", [{"g_a": 0}], domains, defaults={"g_b": 127, "zz": 1})
    rows = [r for r in found["rows"] if r["variable"] == "g_a"]
    assert sorted((r["inputs"]["g_a"], r["inputs"]["g_b"]) for r in rows) == [(10, 128), (11, 128)]
    assert all(r["filled"] == {"g_b": 128} for r in rows)
    assert all("zz" not in r["inputs"] for r in found["rows"])   # a default outside the domains is not an input
    assert _find("pick", [{"g_a": 0}], domains, defaults={"g_b": 999})["rows"] == []   # outside its domain: unused


def test_two_blank_inputs_a_branch_switches_between_get_different_fill_values():
    """``g_o = g_a > 10 ? g_b : g_c`` — with both filled by the same mid value the output never changes."""
    domains = {"g_a": U8, "g_b": U8, "g_c": U8}
    found = _find("sel", [{"g_a": 0}], domains, defaults={"g_b": 127, "g_c": 127})
    rows = [r for r in found["rows"] if r["variable"] == "g_a"]
    assert sorted(r["inputs"]["g_a"] for r in rows) == [10, 11]
    assert rows[0]["inputs"]["g_b"] != rows[0]["inputs"]["g_c"]


def test_a_base_outside_its_domain_or_not_an_integer_is_not_a_base():
    found = _find("gt", [{"g_a": 256}, {"g_a": "[검증 필요] x"}], {"g_a": U8})
    assert found["rows"] == [] and found["report"]["status"] == "no_usable_base"
    assert found["report"]["bases_available"] == 0


# ── enums (review C2) ─────────────────────────────────────────────────────

def test_an_enum_moves_only_between_enumerators():
    found = _find("mode", [{"g_m": 0}], {"g_m": [0, 1, 5, 9]})
    assert _values(found, "g_m") == [1, 5]   # never 2: not an enumerator
    assert {(r["lo"], r["hi"]) for r in found["rows"]} == {(1, 5)}


def test_an_enum_blank_is_filled_with_an_enumerator():
    found = _find("mode", [{"g_x": 0}], {"g_m": [0, 1, 5, 9], "g_x": U8}, defaults={"g_m": 6, "g_x": 0})
    assert all(r["inputs"]["g_m"] in (0, 1, 5, 9) for r in found["rows"])


def test_a_value_set_too_large_is_not_moved_and_said():
    found = _find("mode", [{"g_m": 0}], {"g_m": list(range(br.MAX_VALUE_SET + 1))})
    assert found["report"]["value_sets_capped"] == 1 and found["rows"] == []


# ── budgets and statuses (review W1·W2) ───────────────────────────────────

def test_no_project_scope_no_input_and_no_output_are_said():
    unit = _unit("gt")
    unit.pop("project_scope")
    assert br.find_boundaries(unit, [], {"g_a": U8}, ["g_o"])["report"]["status"] == "no_project_scope"
    assert _find("gt", [], {})["report"]["status"] == "no_integer_inputs"
    assert _find("gt", [], {"g_a": U8}, outputs=())["report"]["status"] == "no_outputs"


def test_an_oracle_that_derives_nothing_is_not_called_searched():
    found = _find("unknown", [{"g_a": 0}], {"g_a": U8}, outputs=("g_zz",))
    assert found["report"]["status"].startswith("oracle_underived")


def test_the_evaluation_budget_says_so(monkeypatch):
    monkeypatch.setattr(br, "MAX_EVALUATIONS", 3)
    found = _find("gt", [{"g_a": 0}], {"g_a": U8})
    assert found["report"]["evaluation_budget_exhausted"] is True and found["report"]["budget_exhausted"] is True
    assert found["rows"] == []


def test_the_boundary_cap_says_so(monkeypatch):
    monkeypatch.setattr(br, "MAX_BOUNDARIES", 1)
    found = _find("eq", [{"g_b": 0}], {"g_b": U8})
    assert found["report"]["boundaries"] == 1 and found["report"]["boundary_cap_reached"] is True


def test_the_base_cap_says_how_many_bases_there_were(monkeypatch):
    monkeypatch.setattr(br, "MAX_BASES", 1)
    found = _find("gt", [{"g_a": 0}, {"g_a": 255}, {"g_a": 3}], {"g_a": U8})
    assert (found["report"]["bases"], found["report"]["bases_available"]) == (1, 3)


def test_the_constant_cap_applies_per_input_and_says_so(monkeypatch):
    """(round 3 I3) the cap is per input, after the input's domain dropped what it cannot hold."""
    monkeypatch.setattr(br, "MAX_CONSTANTS", 1)
    assert br.body_constants(_unit("eq")) == ([5, 6, 7], 3)
    found = _find("eq", [{"g_b": 0}], {"g_b": U8})
    assert found["report"]["constants_capped_inputs"] == 1


# ── constants (review C1: nothing in a body may crash the generator) ──────

def test_body_constants_read_literals_and_resolved_macros_not_comments_or_floats():
    assert br.body_constants(_unit("eq")) == ([5, 6, 7], 3)
    assert br.body_constants({**_unit("eq"), "name": "missing"}) == ([], 0)


def test_octal_literals_and_digits_in_strings_do_not_crash():
    constants, _ = br.body_constants(_unit("octal"))
    assert 8 in constants and 5 not in constants   # 010 is eight; "08:05" is text
    assert _values(_find("octal", [{"g_a": 0}], {"g_a": U8}), "g_a") == [8, 9]


def test_a_macro_the_resolver_cannot_evaluate_is_skipped():
    constants, _ = br.body_constants(_unit("huge"))
    assert 10 in constants


@pytest.mark.parametrize("value, want", [(7, 7), ("0x1F", 31), ("-3", -3), (True, 1), (2.0, 2), ("1.5", None),
                                         ("[검증 필요] x", None), (None, None)])
def test_as_int(value, want):
    assert br._as_int(value) == want


# ── the SUTS wiring ───────────────────────────────────────────────────────

def _seq_unit(name="gt", **kw):
    unit = _unit(name)
    unit.update({"fid": "F1", "input_vars": ["g_a"], "output_vars": ["g_o"], "param_types": {"g_a": "U8", "g_o": "U8"}})
    unit.update(kw)
    return unit


def test_the_extended_profile_adds_boundary_rows_with_oracle_expectations():
    seqs = generate_sequences(_seq_unit(), None, type_cache={}, extended=True)
    rows = [s for s in seqs if s["strategy"].startswith(br.BOUNDARY_PREFIX)]
    assert rows and all(is_extended_strategy(s["strategy"]) and s["tc_profile"] == "extended" for s in rows)
    assert {10, 11} <= {s["inputs"].get("g_a") for s in seqs}   # both sides of the flip are in the suite
    for s in rows:
        assert s["expected_evidence"]["g_o"]["status"] == "derived"
        assert s["expected"]["g_o"] == (1 if s["inputs"]["g_a"] > 10 else 2)
        assert "행동 경계" in s["description"] and "미실행" in s["description"]


def test_the_reference_profile_has_no_boundary_rows():
    seqs = generate_sequences(_seq_unit(), 24, type_cache={})
    assert not any(s["strategy"].startswith(br.BOUNDARY_PREFIX) for s in seqs)
    assert is_extended_strategy("BND_0") and not is_extended_strategy("BV_MIN")


def test_an_enum_input_of_a_unit_stays_an_enumerator():
    unit = _seq_unit("mode", input_vars=["g_m"], param_types={"g_o": "U8"},
                     value_domains={"g_m": {"values": [0, 1, 5, 9]}})
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    rows = [s for s in seqs if s["strategy"].startswith(br.BOUNDARY_PREFIX)]
    assert all(s["inputs"]["g_m"] in (0, 1, 5, 9) for s in rows)
    assert {1, 5} <= {s["inputs"].get("g_m") for s in seqs}


def test_a_failing_search_costs_only_that_units_rows(monkeypatch):
    from generators import suts

    def boom(*a, **k):
        raise ValueError("invalid literal")
    monkeypatch.setattr(suts, "find_boundaries", boom)
    unit = _seq_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert seqs and not any(s["strategy"].startswith(br.BOUNDARY_PREFIX) for s in seqs)
    assert unit["boundary_search"]["status"] == "error:ValueError"


def test_a_row_names_the_inputs_it_filled():
    unit = _seq_unit("sel", input_vars=["g_a", "g_b", "g_c"],
                     param_types={"g_a": "U8", "g_b": "U8", "g_c": "U8", "g_o": "U8"})
    rows = [s for s in generate_sequences(unit, None, type_cache={}, extended=True)
            if s["strategy"].startswith(br.BOUNDARY_PREFIX)]
    filled = [s for s in rows if s["boundary"]["filled"]]
    assert all("기준 행이 비운 입력을 채움" in s["description"] for s in filled)
    assert all("기준 행이 비운 입력을 채움" not in s["description"] for s in rows if not s["boundary"]["filled"])


def test_the_disclosure_says_rows_boundaries_caps_and_what_was_not_searched():
    from report_gen.generation_disclosures import build_disclosures
    qr = {"boundary_rows": 12, "boundary_search": {
        "units": 10, "searched": 6, "with_rows": 4, "boundaries": 7, "budget_exhausted": 1,
        "evaluation_budget_exhausted": 1, "boundary_cap_reached": 0, "bases_capped": 2, "constants_capped": 0,
        "value_sets_capped": 0, "evaluations": 900, "not_searched": {"no_integer_inputs": 2, "oracle_underived": 1},
        "units_without_search": 1}}
    item = {i["key"]: i for i in build_disclosures("suts", qr)}["suts_boundary_rows"]
    assert item["value"] == "12행 · 경계 7 · 탐색한 unit 6/10 (행이 붙은 unit 4)"
    for text in ("no_integer_inputs", "oracle_underived", "실행이 아니다", "들어가지 않은 unit 1", "평가 상한 1",
                 "기준 행 상한에 잘린 unit 2", "열거자 값만"):
        assert text in item["note"], text
    assert item["tone"] == "warning"
    assert "suts_boundary_rows" not in {i["key"] for i in build_disclosures("suts", {})}   # reference profile: no item


# ── review round 2 ────────────────────────────────────────────────────────

def test_an_evenly_numbered_enum_table_is_not_taken_for_a_slope():
    """(W1) ``case 0 → 0, case 1 → 1, default → 2`` over {0,1,2,3}: a range slope filter would call 0→1 "linear"."""
    found = _find("tbl", [{"g_m": 0}], {"g_m": [0, 1, 2, 3]})
    assert {(r["lo"], r["hi"]) for r in found["rows"]} == {(0, 1), (1, 2)}


def test_an_equality_next_to_the_domain_edge_keeps_both_sides():
    """(W2) ``g_a == 1``: from 0 the only visible neighbour (2) steps straight back — one further (3) stays flat."""
    assert _values(_find("one", [{"g_a": 5}], {"g_a": U8}), "g_a") == [0, 1, 2]


def test_a_negative_constant_is_sampled_on_a_signed_range():
    """(I1) the literal in ``g_s == -5`` is read as 5 — a signed range samples -5 too."""
    assert _values(_find("neg", [{"g_s": 0}], {"g_s": (-32768, 32767)}), "g_s") == [-6, -5, -4]


def test_an_enum_keeps_to_the_design_range_that_set_its_bounds(monkeypatch):
    """(W3) SwUDS range 0~5 over enumerators {0,1,5,9}: 9 is the invalid side, never a value the search may move to."""
    from generators import suts
    seen = []
    real = suts.find_boundaries

    def spy(unit, bases, domains, *a, **k):
        seen.append(domains.get("g_m"))
        return real(unit, bases, domains, *a, **k)
    monkeypatch.setattr(suts, "find_boundaries", spy)
    for kw in ({}, {"uds_param_info": {"g_m": {"range": [0, 5]}}}):
        unit = _seq_unit("last", input_vars=["g_m"], param_types={"g_o": "U8"},
                         value_domains={"g_m": {"values": [0, 1, 5, 9]}}, **kw)
        generate_sequences(unit, None, type_cache={}, extended=True)
    assert seen == [[0, 1, 5, 9], [0, 1, 5]]
    assert unit["bounds_source"].get("g_m") == "uds_range"


def test_a_search_error_turns_the_disclosure_into_a_warning():
    from report_gen.generation_disclosures import build_disclosures
    qr = {"boundary_rows": 0, "boundary_search": {"units": 2, "searched": 1, "with_rows": 0, "boundaries": 0,
                                                  "budget_exhausted": 0, "not_searched": {"error": 1}}}
    item = {i["key"]: i for i in build_disclosures("suts", qr)}["suts_boundary_rows"]
    assert item["tone"] == "warning" and "오류로 경계 행 없이 둔 unit 1" in item["note"]
    assert "예산을 다 쓴 unit 은 없다" in item["note"]
    qr["boundary_search"].pop("budget_exhausted")
    assert "예산을 다 쓴 unit 은 없다" not in {i["key"]: i for i in build_disclosures("suts", qr)}["suts_boundary_rows"]["note"]


def test_only_a_written_negative_is_sampled_with_its_sign():
    assert -5 in br.body_constants(_unit("neg"))[0]
    assert br.body_constants(_unit("sub"))[0] == [5]   # ``g_a - 5U`` is a subtraction, not -5


def test_the_bases_deriving_the_most_outputs_go_first(monkeypatch):
    """A base the function does nothing with (``g_b`` not 3: ``g_o`` never written) hides the boundary behind it."""
    monkeypatch.setattr(br, "MAX_BASES", 1)
    found = _find("dev", [{"g_a": 0, "g_b": 0}, {"g_a": 0, "g_b": 3}], {"g_a": U8, "g_b": U8})
    assert _values(found, "g_a") == [10, 11] and found["rows"][0]["base"] == "B1"


# ── review round 3 ────────────────────────────────────────────────────────

def test_bases_repeating_one_output_state_do_not_push_out_the_base_that_reaches_the_logic():
    """(W1) a guard returning early with every output set derives the most — six copies of that state must not push
    out the one base that reaches ``g_a > 10``. One more candidate never loses a boundary."""
    mid = {"g_a": 127, "g_b": 127}
    guards = [{"g_a": i, "g_b": 0} for i in range(6)]
    six = _find("guard", [mid] + guards[:5], {"g_a": U8, "g_b": U8}, outputs=("g_o", "g_w"))
    seven = _find("guard", [mid] + guards, {"g_a": U8, "g_b": U8}, outputs=("g_o", "g_w"))
    assert (six["report"]["bases_available"], seven["report"]["bases_available"]) == (6, 7)
    assert {(r["variable"], r["lo"]) for r in six["rows"]} <= {(r["variable"], r["lo"]) for r in seven["rows"]}
    assert ("g_a", 10) in {(r["variable"], r["lo"]) for r in seven["rows"]}


def test_a_negative_case_label_and_a_negated_name_are_sampled():
    """(W2) ``case -5:`` and ``== -K_LIM`` — both written negatives."""
    assert -5 in br.body_constants(_unit("cneg"))[0] and -5 in br.body_constants(_unit("nname"))[0]
    s16 = {"g_s2": (-32768, 32767)}
    assert _values(_find("cneg", [{"g_s2": 0}], s16), "g_s2") == [-6, -5, -4]
    assert _values(_find("nname", [{"g_s2": 0}], s16), "g_s2") == [-6, -5, -4]


def test_a_budget_spent_before_any_evaluation_is_not_called_underived(monkeypatch):
    """(I1) nothing was asked of the oracle — "it derives nothing" would be a claim without evidence."""
    monkeypatch.setattr(br, "MAX_EVALUATIONS", 1)
    found = _find("gt", [{"g_a": 0}], {"g_a": U8})
    assert found["report"]["status"] == "budget_exhausted_before_search"
    assert found["report"]["evaluations"] == 0


def test_a_negative_constant_does_not_take_an_unsigned_inputs_cap_slot(monkeypatch):
    """(round 3 I3) body constants -40, 2, 7, 40, 44: with two slots the unsigned ``g_a`` gets 2 and 7 — not -40 it
    cannot hold."""
    assert br.body_constants(_unit("negu"))[0] == [-40, 2, 7, 40, 44]
    monkeypatch.setattr(br, "MAX_CONSTANTS", 2)
    assert _values(_find("negu", [{"g_a": 100}], {"g_a": U8}), "g_a") == [6, 7, 8]
