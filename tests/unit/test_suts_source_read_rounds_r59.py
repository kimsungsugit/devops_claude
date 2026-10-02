"""R59 — source-read input rounds 3 -> 8 (`generators/suts.py`, extended SUTS only).

R19 adds, round by round, the program objects the oracle reports as read before written; an added input can open a
path that reads the next one, so a chain of branches needs one round per level. With 3 rounds KJPDS02_PV
`s_MotorSpeedModeSelection_RearSet` kept `u8g_DoorPreCtrl_CompensateLvl` (its fourth branch) unset and its rows derived
one cell (34 with 8 rounds). The search stops at the first round that adds nothing, so the cap only costs where it is
needed; a unit still finding names at the cap is recorded (`round_cap_reached`) and counted."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import suts
from generators.suts import complete_source_read_inputs, generate_sequences, summarize_source_read_inputs

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
#endif
"""
UNIT = """#include "common.h"
U8 g_a;
U8 g_b;
U8 g_c;
U8 g_d;
U8 g_e;
U8 g_o;
void deep(void)
{
    if (g_a > 1U) { if (g_b > 1U) { if (g_c > 1U) { if (g_d > 1U) { if (g_e > 1U) { g_o = 1U; } } } } }
}
"""


def _unit():
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    return {"name": "deep", "fid": "F1", "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": ["g_a"], "output_vars": ["g_o"],
            "param_types": {"g_a": "U8", "g_o": "U8"}}


def _ext(unit):
    seqs = generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    return complete_source_read_inputs(unit, seqs, lambda: generate_sequences(unit, None, type_cache={}, extended=True,
                                                                             boundary_rows=False))


def _derived(seqs):
    return [s for s in seqs if ((s.get("expected_evidence") or {}).get("g_o") or {}).get("status") == "derived"]


def test_five_nested_branches_take_five_rounds_and_nothing_is_left():
    assert suts._SOURCE_READ_ROUNDS == 8
    unit = _unit()
    seqs = _ext(unit)
    rec = unit["source_read_inputs"]
    # round 1: g_o (left unchanged on the arms not taken — its cells need the initial value; backlog 2-c marks it
    #   `read_on_model: False`, so the input-list gap finding leaves it out); then one branch deeper per round
    assert {n: r["round"] for n, r in rec["added"].items()} == {"g_o": 1, "g_b": 2, "g_c": 3, "g_d": 4, "g_e": 5}
    assert [n for n, r in rec["added"].items() if not r["read_on_model"]] == ["g_o"]
    assert rec["rounds"] == 5 and rec["remaining"] == {} and not rec.get("round_cap_reached")
    assert any(s["expected"]["g_o"] == 1 for s in _derived(seqs))


def test_three_rounds_left_a_name_and_the_cap_is_recorded(monkeypatch):
    monkeypatch.setattr(suts, "_SOURCE_READ_ROUNDS", 3)
    unit = _unit()
    seqs = _ext(unit)
    rec = unit["source_read_inputs"]
    assert rec["rounds"] == 3 and rec["round_cap_reached"] is True and rec["names_beyond_cap"] == ["g_d"]
    assert set(rec["remaining"]) == {"g_d"} and "g_e" not in unit["input_vars"]
    # the innermost assignment is never derived without the missing inputs
    assert not any(s["expected"].get("g_o") == 1 for s in _derived(seqs))
    s = summarize_source_read_inputs([unit])
    assert (s["round_cap"], s["units_round_cap_reached"], s["names_beyond_cap"], s["names_remaining"]) == (3, 1, 1, 1)


def test_a_cap_equal_to_the_rounds_needed_did_not_cut_anything(monkeypatch):
    # review R59 W1: five rounds needed, cap five — the fifth round added the last name and nothing is beyond it
    monkeypatch.setattr(suts, "_SOURCE_READ_ROUNDS", 5)
    unit = _unit()
    _ext(unit)
    rec = unit["source_read_inputs"]
    assert rec["rounds"] == 5 and rec["round_cap_reached"] is False and rec["names_beyond_cap"] == []
    assert rec["remaining"] == {}


def test_the_disclosure_names_the_cap_and_the_units_that_reached_it(monkeypatch):
    from report_gen.generation_disclosures import build_disclosures
    monkeypatch.setattr(suts, "_SOURCE_READ_ROUNDS", 3)
    unit = _unit()
    _ext(unit)
    (item,) = [i for i in build_disclosures("suts", {"source_read_inputs": summarize_source_read_inputs([unit])})
               if i["key"] == "suts_source_read_inputs"]
    assert "상한 3회차" in item["note"] and "다음 회차가 더했을 이름 1(unit 1)" in item["note"]
    assert item["tone"] == "warning"
    monkeypatch.setattr(suts, "_SOURCE_READ_ROUNDS", 8)
    full = _unit()
    _ext(full)
    (item,) = [i for i in build_disclosures("suts", {"source_read_inputs": summarize_source_read_inputs([full])})
               if i["key"] == "suts_source_read_inputs"]
    assert "상한 8회차" in item["note"] and "다음 회차가 더했을" not in item["note"]
