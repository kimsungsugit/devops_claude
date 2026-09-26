"""R21 — what a row sets or states is a column of its TC (`generators/suts.py` `render_row_io`, both profiles).

A GLOBAL row sets an indirect global to its minimum; a unit without inputs/outputs sets and states its indirect globals
in its call sequences. The spec sheet writes only the `input_vars`/`output_vars` columns, so those values were not in
the document while the oracle derived expected values from them. They become columns (first-use order); an input that
cannot be shown (column cap) takes the derived slots of the rows using it out of "derived". Every value below is what C
computes on a 16-bit-int target (as the oracle models it)."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import suts
from generators.suts import generate_sequences, render_row_io, summarize_row_io

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
U8 g_gain;
U8 g_o;
void close_gain(void) { if (g_a > 10U) { g_o = g_gain; } else { g_o = 0U; } }
void touch(void) { g_b = (U8)(g_b + 1U); }
"""


def _unit(name, input_vars, output_vars=("g_o",), **kw):
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    unit = {"name": name, "fid": "F1", "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(input_vars),
            "output_vars": list(output_vars), "param_types": {"g_a": "U8", "g_b": "U8", "g_o": "U8", "g_gain": "U8"}}
    unit.update(kw)
    return unit


def test_a_global_row_input_becomes_a_column_and_only_that_row_has_a_value():
    unit = _unit("close_gain", ["g_a"], indirect_vars=["g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    g = next(s for s in seqs if s["strategy"] == "GLOBAL_0")
    assert g["inputs"]["g_gain"] == 0 and "g_gain" not in unit["input_vars"]     # the hidden input before R21
    assert g["expected_evidence"]["g_o"]["status"] == "derived"                  # …that a derived value rested on
    rec = render_row_io(unit, seqs)
    assert unit["input_vars"] == ["g_a", "g_gain"] and rec["inputs_shown"] == ["g_gain"]
    assert [s["strategy"] for s in seqs if "g_gain" in s["inputs"]] == ["GLOBAL_0"]
    assert rec["downgraded_slots"] == 0 and rec["inputs_over_cap"] == []


def test_a_unit_without_inputs_or_outputs_shows_what_its_call_sequences_set_and_state():
    unit = _unit("touch", [], output_vars=(), indirect_vars=["g_b"])
    seqs = generate_sequences(unit, 24, type_cache={})
    assert any("g_b" in (s.get("inputs") or {}) for s in seqs)
    rec = render_row_io(unit, seqs)
    assert unit["input_vars"] == ["g_b"] and unit["output_vars"] == ["g_b"]
    assert rec["inputs_shown"] == ["g_b"] and rec["outputs_shown"] == ["g_b"]


def test_an_input_over_the_column_cap_takes_its_rows_out_of_derived(monkeypatch):
    monkeypatch.setattr(suts, "_INPUT_COL_END", suts._INPUT_COL_START)            # one input column
    unit = _unit("close_gain", ["g_a"], indirect_vars=["g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    rec = render_row_io(unit, seqs)
    assert unit["input_vars"] == ["g_a"] and rec["inputs_over_cap"] == ["g_gain"]
    g = next(s for s in seqs if s["strategy"] == "GLOBAL_0")
    assert g["expected_evidence"]["g_o"] == {**g["expected_evidence"]["g_o"], "status": "unknown",
                                             "reason": "input_not_in_document:g_gain", "oracle_kind": "none"}
    assert g["expected"]["g_o"].endswith("input_not_in_document:g_gain")
    assert rec["downgraded_slots"] >= 1
    others = [s for s in seqs if "g_gain" not in s["inputs"]]
    assert any(s["expected_evidence"]["g_o"]["status"] == "derived" for s in others)   # untouched


def test_an_output_over_the_column_cap_is_counted_not_asserted(monkeypatch):
    monkeypatch.setattr(suts, "_OUTPUT_COL_END", suts._OUTPUT_COL_START)          # one output column (taken by g_b)
    unit = _unit("touch", [], output_vars=("g_o",), indirect_vars=["g_b"])
    seqs = [{"seq_num": 1, "inputs": {}, "expected": {"g_o": 1, "g_b": 2}, "expected_evidence": {}}]
    rec = render_row_io(unit, seqs)
    assert unit["output_vars"] == ["g_o"] and rec["outputs_over_cap"] == ["g_b"] and rec["downgraded_slots"] == 0


def test_nothing_hidden_changes_nothing():
    unit = _unit("close_gain", ["g_a", "g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    before = [dict(s["inputs"]) for s in seqs]
    rec = render_row_io(unit, seqs)
    assert unit["input_vars"] == ["g_a", "g_gain"] and rec["inputs_shown"] == [] and rec["outputs_shown"] == []
    assert [s["inputs"] for s in seqs] == before


def test_the_summary_and_the_disclosure():
    from report_gen.generation_disclosures import build_disclosures
    units = [{"row_io_columns": {"inputs_shown": ["a", "b"], "inputs_over_cap": ["c"], "outputs_shown": ["d"],
                                 "outputs_over_cap": [], "downgraded_slots": 3}},
             {"row_io_columns": {"inputs_shown": [], "inputs_over_cap": [], "outputs_shown": [], "outputs_over_cap": [],
                                 "downgraded_slots": 0}},
             {"name": "no record"}]
    q = summarize_row_io(units)
    assert q == {"units": 2, "units_with_inputs_shown": 1, "inputs_shown": 2, "units_with_outputs_shown": 1,
                 "outputs_shown": 1, "inputs_over_cap": 1, "outputs_over_cap": 0, "downgraded_slots": 3}
    item = {i["key"]: i for i in build_disclosures("suts", {"row_io_columns": q})}["suts_row_io_columns"]
    assert item["value"] == "입력 2(unit 1) · 기대값 1(unit 1)"
    assert "보이지 못한 입력 1" in item["note"] and "확정 칸 3" in item["note"] and item["tone"] == "warning"
    quiet = summarize_row_io([units[1]])
    assert "suts_row_io_columns" not in {i["key"] for i in build_disclosures("suts", {"row_io_columns": quiet})}


def test_generate_suts_renders_the_row_inputs_in_both_profiles(tmp_path):
    # the production path: the sheet gets the column, the quality report counts it
    (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 g_x;\nU8 g_y;\nU8 Fn(U8 a)\n{\n    if (a > 1) { return g_x; }\n"
                                  "    g_y = 1;\n    return 0;\n}\n", encoding="utf-8")
    for profile in ("", "extended"):
        out = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / f"u{profile}.xlsm"),
                                 scope="source", tc_profile=profile)
        q = out["quality_report"]["row_io_columns"]
        assert set(q) >= {"units", "inputs_shown", "downgraded_slots"} and q["downgraded_slots"] == 0


# ── review round 1 ──────────────────────────────────────────────────────────────────────────────────────────────

def test_two_hidden_names_are_shown_in_first_use_order():
    unit = _unit("close_gain", ["g_a"])
    seqs = [{"seq_num": 1, "inputs": {"g_a": 1, "g_z": 3}, "expected": {}},
            {"seq_num": 2, "inputs": {"g_a": 1, "g_gain": 2, "g_z": 4}, "expected": {}}]
    assert render_row_io(unit, seqs)["inputs_shown"] == ["g_z", "g_gain"]
    assert unit["input_vars"] == ["g_a", "g_z", "g_gain"]


def test_a_shown_global_that_other_rows_read_unset_stays_an_input_list_gap():
    # review W1: showing the GLOBAL row's global as a column erased the gap the other rows still have
    from generators.suts import input_list_gaps
    unit = _unit("close_gain", ["g_a"], indirect_vars=["g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    before = input_list_gaps(unit, seqs)
    render_row_io(unit, seqs)
    after = input_list_gaps(unit, seqs)
    assert "g_gain" in before and after.get("g_gain") == before["g_gain"]


def test_a_downgraded_slot_keeps_no_derivation_provenance(monkeypatch):
    # review I1: basis / assumptions / stubs described a value that is no longer claimed
    monkeypatch.setattr(suts, "_INPUT_COL_END", suts._INPUT_COL_START)
    unit = _unit("close_gain", ["g_a"], indirect_vars=["g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    g = next(s for s in seqs if s["strategy"] == "GLOBAL_0")
    assert "basis" in g["expected_evidence"]["g_o"]
    render_row_io(unit, seqs)
    ev = g["expected_evidence"]["g_o"]
    assert not {"basis", "assumptions", "stubs"} & set(ev)
    assert "근거: 소스 계산" not in g["description"] and "input_not_in_document:g_gain" in g["description"]


def test_generate_suts_writes_the_shown_name_into_the_tc_row(tmp_path, monkeypatch):
    # review W2: the production path — the sheet's TC row carries the column and every evidence input is a column
    import json

    import openpyxl
    (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 Fn(U8 a)\n{\n    return a;\n}\n", encoding="utf-8")
    real = suts.generate_sequences

    def with_hidden(unit, *a, **k):
        seqs = real(unit, *a, **k)
        for s in seqs[:1]:
            s["inputs"] = {**(s.get("inputs") or {}), "g_hidden_probe": 7}
        return seqs
    monkeypatch.setattr(suts, "generate_sequences", with_hidden)
    out = tmp_path / "u.xlsm"
    q = suts.generate_suts(source_root=str(tmp_path), output_path=str(out), scope="source")["quality_report"]
    assert q["row_io_columns"]["inputs_shown"] >= 1
    wb = openpyxl.load_workbook(out, read_only=True)
    cols, rows = {}, wb["2.SW Unit Test Spec"].iter_rows(min_row=5, values_only=True)
    for row in rows:
        if isinstance(row[2], str) and row[2].startswith("SwUTC_"):
            cols[row[2]] = {c for c in row[8:104] if c not in (None, "")}
    assert any("g_hidden_probe" in c for c in cols.values())
    try:
        ev = wb["Test Evidence"].iter_rows(values_only=True)
        head = next(ev)
        ix = {k: i for i, k in enumerate(head)}
        for r in ev:
            assert set(json.loads(r[ix["Inputs JSON"]] or "{}")) <= cols.get(r[ix["Test Case ID"]], set())
    finally:
        wb.close()     # review R2 I-d


# ── review round 2 ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_downgrade_drops_stub_provenance_and_names_every_over_cap_input(monkeypatch):
    # review R2 I-a: a stubbed callee and two over-cap inputs in one row
    monkeypatch.setattr(suts, "_INPUT_COL_END", suts._INPUT_COL_START)
    unit = _unit("close_gain", ["g_a"])
    seqs = [{"seq_num": 1, "inputs": {"g_a": 1, "g_p": 2, "g_q": 3}, "expected": {"g_o": 0},
             "expected_evidence": {"g_o": {"status": "derived", "oracle_kind": "source", "reason": "x", "basis": "b",
                                           "assumptions": ["a"], "stubs": ["F"], "callees_interpreted": ["G"]}},
             "description": "label\nExpected: g_o=0\n근거: 소스 계산 (요구 적합성 미검증, 실행 미실시)"}]
    render_row_io(unit, seqs)
    ev = seqs[0]["expected_evidence"]["g_o"]
    assert ev["reason"] == "input_not_in_document:g_p,g_q" and not {"basis", "assumptions", "stubs",
                                                                      "callees_interpreted"} & set(ev)


def test_a_row_with_nothing_expected_gets_no_bare_expected_line(monkeypatch):
    monkeypatch.setattr(suts, "_INPUT_COL_END", suts._INPUT_COL_START)
    unit = _unit("close_gain", ["g_a"])
    seqs = [{"seq_num": 1, "inputs": {"g_a": 1, "g_p": 2}, "expected": {}, "expected_evidence": {},
             "description": "label"}]
    render_row_io(unit, seqs)
    assert seqs[0]["description"] == "label"


def test_a_second_call_keeps_what_the_first_showed():
    # review R2 I-c: a second pass found nothing new and wiped the record the gap finding reads
    from generators.suts import input_list_gaps
    unit = _unit("close_gain", ["g_a"], indirect_vars=["g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    render_row_io(unit, seqs)
    render_row_io(unit, seqs)
    assert unit["row_io_columns"]["inputs_shown"] == ["g_gain"] and "g_gain" in input_list_gaps(unit, seqs)



def test_a_second_call_keeps_the_downgrade_count(monkeypatch):
    # review R3: dropping the count merge reset the disclosed number of downgraded slots to 0
    monkeypatch.setattr(suts, "_INPUT_COL_END", suts._INPUT_COL_START)
    unit = _unit("close_gain", ["g_a"], indirect_vars=["g_gain"])
    seqs = generate_sequences(unit, 24, type_cache={})
    first = render_row_io(unit, seqs)["downgraded_slots"]
    assert first >= 1 and render_row_io(unit, seqs)["downgraded_slots"] == first
