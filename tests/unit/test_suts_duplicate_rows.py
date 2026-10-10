"""R23 — rows whose inputs equal an earlier row of the same TC (`generators/suts.py` `_drop_duplicate_rows`).

The oracle is deterministic, so such a row states the same expected values again. Extended strategy rows (OAT, SWITCH/
GLOBAL beyond the reference slots) are dropped before evidence — and before the MC/DC finalize binds row numbers into
the pairs; reference-catalog rows are kept (R75: the extended document starts with the reference document) and counted;
MC/DC vector rows are never dropped (pairs find rows by vector). Every value below is what C computes on a 16-bit-int
target (as the oracle models it)."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators.suts import (
    TC_PROFILE_EXTENDED,
    _drop_duplicate_rows,
    generate_sequences,
    summarize_duplicate_rows,
)

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
U8 g_f;
U8 g_o;
void flag(void) { if ((g_a > 10U) && (g_f != 0U)) { g_o = 1U; } else { g_o = 2U; } }
"""


def _unit(name, input_vars, **kw):
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    unit = {"name": name, "fid": "F1", "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(input_vars),
            "output_vars": ["g_o"], "param_types": {"g_a": "U8", "g_f": "bool", "g_o": "U8"}}
    unit.update(kw)
    return unit


def test_an_extended_row_equal_to_an_earlier_row_is_dropped_and_the_rest_renumbered():
    # a 0/1 flag: its minimum equals its mid value, so OAT on it repeats BV_MID
    unit = _unit("flag", ["g_a", "g_f"])
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    keys = [tuple(sorted(s["inputs"].items())) for s in seqs if s["strategy"].startswith(("OAT_", "SWITCH_", "GLOBAL_"))
            and s.get("tc_profile") == TC_PROFILE_EXTENDED]
    earlier = {tuple(sorted(s["inputs"].items())) for s in seqs if s.get("tc_profile") != TC_PROFILE_EXTENDED}
    assert not set(keys) & earlier                                    # no extended strategy row repeats a reference row
    assert unit["duplicate_rows"]["extended_rows_dropped"] >= 1
    assert [s["seq_num"] for s in seqs] == list(range(1, len(seqs) + 1))


def test_the_reference_profile_keeps_its_duplicates_and_counts_them():
    unit = _unit("flag", ["g_a"], param_types={"g_a": "U8", "g_o": "U8"})    # one input: MIXED equals BV_MIN
    seqs = generate_sequences(unit, 24, type_cache={})
    names = [s["strategy"] for s in seqs]
    assert "MIXED" in names and "BV_MIN" in names
    assert unit["duplicate_rows"]["extended_rows_dropped"] == 0
    assert unit["duplicate_rows"]["reference_rows_duplicated"] >= 1


def test_mcdc_boundary_and_fill_rows_are_never_dropped():
    seqs = [{"seq_num": 1, "strategy": "BV_MID", "inputs": {"a": 1}},
            {"seq_num": 2, "strategy": "MCDC_7", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 3, "strategy": "BND_0", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 4, "strategy": "FILLED_MCDC_0", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 5, "strategy": "OAT_0_MIN", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 6, "strategy": "SWITCH_9", "inputs": {"a": 2}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 7, "strategy": "GLOBAL_4", "inputs": {"a": 2}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 8, "strategy": "SWITCH_10", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED}]
    unit: dict = {}
    kept = _drop_duplicate_rows(unit, seqs, extended=True)
    assert [s["strategy"] for s in kept] == ["BV_MID", "MCDC_7", "BND_0", "FILLED_MCDC_0", "SWITCH_9"]
    assert [s["seq_num"] for s in kept] == [1, 2, 3, 4, 5]
    assert unit["duplicate_rows"] == {"reference_rows_duplicated": 0, "extended_rows_dropped": 3,
                                      "extended_rows_duplicated_kept": 3}
    unit = {}
    base = [{"seq_num": 1, "strategy": "BV_MIN", "inputs": {"a": 0}}, {"seq_num": 2, "strategy": "MIXED", "inputs": {"a": 0}}]
    assert _drop_duplicate_rows(unit, base, extended=False) == base
    assert unit["duplicate_rows"] == {"reference_rows_duplicated": 1, "extended_rows_dropped": 0,
                                      "extended_rows_duplicated_kept": 0}


def test_an_unmarked_row_is_never_dropped_even_with_an_extended_strategy_name():
    # review W1 M1: the tc_profile marker, not the name alone, says a row is extended
    unit: dict = {}
    seqs = [{"seq_num": 1, "strategy": "BV_MID", "inputs": {"a": 1}},
            {"seq_num": 2, "strategy": "SWITCH_2", "inputs": {"a": 1}}]
    assert _drop_duplicate_rows(unit, seqs, extended=True) == seqs
    assert unit["duplicate_rows"]["reference_rows_duplicated"] == 1


def test_the_summary_and_the_disclosure():
    from report_gen.generation_disclosures import build_disclosures
    units = [{"duplicate_rows": {"reference_rows_duplicated": 3, "extended_rows_dropped": 5,
                                 "extended_rows_duplicated_kept": 2}},
             {"duplicate_rows": {"reference_rows_duplicated": 0, "extended_rows_dropped": 1}}, {"name": "x"}]
    q = summarize_duplicate_rows(units)
    assert q == {"units": 2, "reference_rows_duplicated": 3, "units_with_reference_duplicates": 1, "extended_rows_dropped": 6,
                 "extended_rows_duplicated_kept": 2}
    item = {i["key"]: i for i in build_disclosures("suts", {"duplicate_rows": q})}["suts_duplicate_rows"]
    assert item["value"] == "정본 규모 행 3(unit 1, 남김) · 확장 행 6(뺌)"
    assert "MC/DC" in item["note"] and "R75" not in item["note"] and "남긴 확장 MC/DC 행 2" in item["note"]
    only_dropped = summarize_duplicate_rows([units[1]])       # review W1 M9: extended drops alone still disclose
    assert "suts_duplicate_rows" in {i["key"] for i in build_disclosures("suts", {"duplicate_rows": only_dropped})}
    quiet = summarize_duplicate_rows([units[2]])
    assert "suts_duplicate_rows" not in {i["key"] for i in build_disclosures("suts", {"duplicate_rows": quiet})}


# ── review round 1 ──────────────────────────────────────────────────────────────────────────────────────────────

SW_UNIT = """#include "common.h"
U8 a; U8 b; U8 c; U8 d; U8 e; U8 o;
void fn(void) {
  if ((a > 10U) && (b > 20U) && (c > 30U) && (d > 40U)) { o = 1U; }
  else if ((e > 50U) || (b > 60U) || (c > 70U)) { o = 2U; }
  else { o = 3U; }
}
"""


def _sw_unit():
    # a 9-case switch on `a`, one case at the U8 mid value 127: the extended SWITCH_7 row equals BV_MID and is dropped —
    # before R23's fix the MC/DC rows after it were renumbered but the pairs kept the old numbers (review R1 C1)
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): SW_UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    cases = [{"value": v, "label": f"C{v}"} for v in range(7)] + [{"value": 127, "label": "CMID"}, {"value": 9, "label": "C9"}]
    return {"name": "fn", "fid": "F1", "source_text": SW_UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": ["a", "b", "c", "d", "e"],
            "output_vars": ["o"], "param_types": {v: "U8" for v in "abcdeo"},
            "logic_flow": [{"type": "switch", "variable": "a", "cases": cases}]}


def _norm(d):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, str):
            try:
                v = int(v, 16 if v.lower().startswith("0x") else 10)
            except ValueError:
                pass
        out[k] = v
    return out


def test_a_dropped_switch_row_leaves_every_mcdc_pair_pointing_at_its_own_rows():
    unit = _sw_unit()
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    assert unit["duplicate_rows"]["extended_rows_dropped"] >= 1
    assert not any(s["strategy"] == "SWITCH_7" for s in seqs)          # the case equal to BV_MID
    by_seq = {s["seq_num"]: s for s in seqs}
    pairs = [p for dec in unit["mcdc_design"]["decisions"] for p in dec.get("pairs") or []
             if p.get("retained_status") == "retained"]
    assert pairs
    for p in pairs:
        for side in "ab":
            row = by_seq[p[f"seq_{side}"]]
            assert row["strategy"].startswith("MCDC_") and _norm(row["inputs"]) == _norm(p[f"inputs_{side}"]), (p["pair_id"], side)


def test_the_disclosure_shows_kept_mcdc_duplicates_alone_and_the_cap_note_only_when_extended():
    # review R2 I-a / I-b
    from report_gen.generation_disclosures import build_disclosures
    q = {"units": 1, "reference_rows_duplicated": 0, "units_with_reference_duplicates": 0, "extended_rows_dropped": 0,
         "extended_rows_duplicated_kept": 1}
    items = {i["key"]: i for i in build_disclosures("suts", {"duplicate_rows": q})}
    assert "suts_duplicate_rows" in items and "상한을 넘어" not in items["suts_duplicate_rows"]["note"]
    ext = {i["key"]: i for i in build_disclosures("suts", {"duplicate_rows": q, "tc_profile": "extended"})}
    assert "상한을 넘어" in ext["suts_duplicate_rows"]["note"]

