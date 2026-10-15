"""R85 — the reference-scale SUTS keeps its row count and gives the room of the type-boundary catalogue rows to code rows
(`suts._reference_scale_block` · `suts._code_rows`).

Measured (R85): of the mutants only the reference killed, HDPDM01 554 · KJPDS02_PV 487, 80 % · 51 % were a value the
reference gives an input and the generated rows never did — 88 % · 65 % of those values a constant the function body
compares that input with (K, K±1). An input the design gives no range got the type's ends and middle only, never the
points the code splits it at. The code rows come from the dynamic scenario search the extended profile has had since R78
(statements · branch outcomes) and R79 (fault-exposing values), run on the design inputs only so that both profiles hold
the same rows (the extended document starts with the reference-scale one — R75). No mutant is made or consulted. Values
are what C computes on the oracle's 16-bit-int target."""
from __future__ import annotations

import inspect
import json
import os

import pytest

from generators import c_project_context as cpc
from generators import suts
from generators.suts import (
    _REFERENCE_KEEP,
    CATALOG_PREFIX,
    CODE_PREFIX,
    REFERENCE_CODE_REPORT_KEYS,
    generate_sequences,
    is_extended_strategy,
    resolve_seq_gen_method,
    resolve_seq_test_method,
    summarize_reference_code_rows,
)
from generators.tc_profile import TC_PROFILE_EXTENDED
from report_gen.generation_disclosures import build_disclosures

ROOT = os.path.join(os.sep, "proj_r85")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#define ON_MODE 3U
#define T_LIM 600U
#endif
"""
UNIT = """#include "common.h"
U8 g_mode;
U16 g_tmr;
U8 g_res;
U8 g_cnt;
void ctl(void)
{
    if (g_mode == ON_MODE)
    {
        if (g_tmr >= T_LIM)
        {
            g_res = 2U;
            g_cnt = 0U;
        }
        else
        {
            g_res = 1U;
            g_cnt = g_cnt + 1U;
        }
    }
    else
    {
        g_res = 0U;
    }
}
"""
TYPES = {"g_mode": "U8", "g_tmr": "U16", "g_res": "U8", "g_cnt": "U8"}
_CACHE: dict = {}


def _unit(**kw):
    if "scope" not in _CACHE:
        files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
        context = cpc.build_project_context(files)
        _CACHE["scope"] = cpc.build_scopes(context, [os.path.join(ROOT, "unit.c")])[os.path.join(ROOT, "unit.c")]
    unit = {"name": "ctl", "fid": "F_ctl", "source_text": UNIT, "source_path": os.path.join(ROOT, "unit.c"),
            "source_text_complete": True, "project_scope": _CACHE["scope"],
            "input_vars": ["g_mode", "g_tmr", "g_cnt"], "output_vars": ["g_res", "g_cnt"], "param_types": {},
            "uds_param_info": {}}
    unit.update(kw)
    return unit


def _int(v):
    return int(str(v), 0)


def _names(rows):
    return [s["strategy"] for s in rows]


def test_the_reference_scale_document_keeps_its_row_count_and_gives_the_room_to_code_rows():
    unit = _unit()
    rows = generate_sequences(unit, 24, type_cache=TYPES)
    rec = unit["reference_code_rows"]
    assert set(REFERENCE_CODE_REPORT_KEYS) <= set(rec)
    # the count of the document before R85: the catalogue up to the cap
    assert rec["budget"] == min(24, unit["base_strategy_count"]) == len(rows) == rec["catalogue"]
    code = [s for s in rows if s["strategy"].startswith(CODE_PREFIX)]
    assert code and rec["status"] == "searched" and rec["rows"] == len(code)
    # every MC/DC design row stays; the code rows take the room of the other catalogue rows. The two FI rows hold no
    #   design range here — U8 −1 / 256, U16 65536 — so they are no kept rows (review R85 W-R4-3) and fill last
    assert len([s for s in rows if s["strategy"].startswith("MCDC_")]) == rec["kept"] == 3
    assert {"MCDC_0", "MCDC_1", "MCDC_2"} <= set(_names(rows)) and rec["fi_out_of_type"] == 2
    assert not {"BV_MIN_INV", "BV_MAX_INV"} & set(_names(rows))
    assert rec["displaced"] == rec["catalogue"] - rec["budget"] + rec["rows"]
    assert _names(rows)[-len(code):] == [f"{CODE_PREFIX}{i}" for i in range(len(code))]
    assert all(not s.get("tc_profile") and not is_extended_strategy(s["strategy"]) for s in rows)
    assert [s["seq_num"] for s in rows] == list(range(1, len(rows) + 1))


def test_a_code_row_steps_on_the_points_the_code_splits_its_inputs_at():
    # the design gives g_mode / g_tmr no range: the catalogue rows put them at 0 · the middle · the ends — none is 3, so
    #   `g_tmr >= T_LIM` is never evaluated by them and g_res = 2 is never derived
    rows = generate_sequences(_unit(), 24, type_cache=TYPES)
    catalogue = [s for s in rows if not s["strategy"].startswith(CODE_PREFIX)]
    code = [s for s in rows if s["strategy"].startswith(CODE_PREFIX)]
    assert not any(s["expected"].get("g_res") == 2 for s in catalogue)
    reach = [s for s in code if s["expected"].get("g_res") == 2]
    assert reach and _int(reach[0]["inputs"]["g_mode"]) == 3 and _int(reach[0]["inputs"]["g_tmr"]) >= 600
    assert reach[0]["expected_evidence"]["g_res"]["status"] == "derived"
    # the boundary point of `g_tmr >= T_LIM` (both values equal, the condition decides) is a code row too
    assert any(_int(s["inputs"].get("g_tmr", -1)) == 600 and _int(s["inputs"].get("g_mode", -1)) == 3 for s in code)
    assert all(s["description"].startswith("코드 기준 행(정본 규모 · 설계 입력만): ") for s in code)
    assert all(s["code_row"]["target_kind"] in ("statement", "branch", "boundary", "write", "arith") for s in code)


def test_the_extended_document_starts_with_the_reference_scale_document():
    ref = generate_sequences(_unit(), 24, type_cache=TYPES)
    unit = _unit()
    ext = generate_sequences(unit, None, type_cache=TYPES, extended=True)
    head = ext[:len(ref)]
    assert _names(head) == _names(ref)
    for a, b in zip(head, ref, strict=True):    # the same design values (R75)
        assert {k: a["inputs"].get(k) for k in ("g_mode", "g_tmr", "g_cnt")} == \
            {k: b["inputs"].get(k) for k in ("g_mode", "g_tmr", "g_cnt")}
    displaced = [s for s in ext if s["strategy"].startswith(CATALOG_PREFIX)]
    rec = unit["reference_code_rows"]
    assert len(displaced) == rec["displaced"] >= 1
    assert ext[len(ref):len(ref) + len(displaced)] == displaced     # right after the reference-scale block
    assert all("정본 규모 문서에 들지 못한 카탈로그 행" in s["description"] for s in displaced)
    # the extension is told by its names alone — the displaced rows too (R75)
    assert [s.get("tc_profile") == TC_PROFILE_EXTENDED for s in ext] == [is_extended_strategy(s["strategy"]) for s in ext]
    assert [s["seq_num"] for s in ext] == list(range(1, len(ext) + 1))


def test_a_displaced_catalogue_row_keeps_its_methods_and_a_code_row_is_an_equivalence_class_row():
    for name in ("BV_MIN_INV", "BV_MAX_INV", "BV_MID", "COND_COMB_0", "GLOBAL_1", "MIXED"):
        assert resolve_seq_test_method(CATALOG_PREFIX + name) == resolve_seq_test_method(name)
        assert resolve_seq_gen_method(CATALOG_PREFIX + name) == resolve_seq_gen_method(name)
        assert is_extended_strategy(CATALOG_PREFIX + name) and not is_extended_strategy(name)
    assert resolve_seq_gen_method("CODE_0") == resolve_seq_gen_method("SCN_0") == resolve_seq_gen_method("COND_COMB_0")
    assert resolve_seq_test_method("CODE_0") == resolve_seq_test_method("BV_MID")
    assert not is_extended_strategy("CODE_3")
    assert suts._base_rank({"strategy": CATALOG_PREFIX + "BV_MID"}) == suts._base_rank({"strategy": "BV_MID"})


def test_the_kept_rows_come_first_when_the_cap_is_tight():
    # before R85 a cap of 4 kept BV_MIN_INV … BV_MAX and no MC/DC row (MC/DC is last in the catalogue)
    unit = _unit()
    rows = generate_sequences(unit, 4, type_cache=TYPES)
    mcdc = [s for s in rows if s["strategy"].startswith("MCDC_")]
    kept = [s for s in rows if s["strategy"].startswith(_REFERENCE_KEEP)]
    assert len(rows) == 4 and len(mcdc) == 3 and len(kept) == unit["reference_code_rows"]["kept"] == 3
    # the rest of the room: a code row (the FI rows hold U8 256 — no kept rows, review R85 W-R4-3)
    assert len(rows) - len(kept) == unit["reference_code_rows"]["rows"] == 1
    # a cap below the kept rows: the first kept rows in the keep order (MC/DC first), nothing else (review R85 I7 · M4)
    unit = _unit()
    rows = generate_sequences(unit, 2, type_cache=TYPES)
    assert _names(rows) == ["MCDC_0", "MCDC_1"] and unit["reference_code_rows"]["status"] == "no_room"


def test_switch_case_rows_are_kept_rows_too():
    # (review R85 I7 · M2) switch case rows are kept before the type-boundary rows (no source here: no code rows)
    cases = [{"value": v, "label": f"C{v}"} for v in range(4)]
    unit = {"fid": "F", "name": "Fn", "input_vars": ["a", "b"], "output_vars": ["o"], "indirect_vars": [],
            "param_types": {"a": "U8", "b": "U8", "o": "U8"}, "uds_param_info": {},
            "logic_flow": [{"type": "switch", "variable": "a", "cases": cases}]}
    rows = generate_sequences(unit, 4, type_cache={})
    # the four case rows (kept rows: MC/DC → switch → loop → void → FI in its types)
    assert _names(rows) == ["SWITCH_0", "SWITCH_1", "SWITCH_2", "SWITCH_3"]
    assert unit["reference_code_rows"]["status"] == "no_room"
    unit = dict(unit)
    rows = generate_sequences(unit, 8, type_cache={})   # room left: the search runs — and says it could not
    assert unit["reference_code_rows"]["status"] == "no_project_scope"     # (review R85 W3) the search's own status
    # U8 −1 / 256: no kept rows, and the fill takes them last (after the rows with other inputs)
    assert not {"BV_MIN_INV", "BV_MAX_INV"} & set(_names(rows)) and unit["reference_code_rows"]["fi_out_of_type"] == 2
    summary = summarize_reference_code_rows([unit])
    assert summary["searched"] == 0 and summary["not_searched"] == {"no_project_scope": 1}
    assert summary["fi_out_of_type"] == 2
    # a design range inside the type: the FI rows hold values the harness can load — kept after the case rows
    unit = dict(unit, uds_param_info={"a": {"range": [1, 100]}, "b": {"range": [1, 100]}})
    rows = generate_sequences(unit, 6, type_cache={})
    assert _names(rows) == ["BV_MIN_INV", "BV_MAX_INV", "SWITCH_0", "SWITCH_1", "SWITCH_2", "SWITCH_3"]
    assert unit["reference_code_rows"]["kept"] == 6 and unit["reference_code_rows"]["fi_out_of_type"] == 0


def test_the_rest_of_the_room_takes_rows_that_set_a_new_input_first_and_duplicates_last(monkeypatch):
    # (review R85 W2 · I7 · M3) synthetic catalogue: the MC/DC row and the code row set `a`; GLOBAL_0 alone sets `g`
    rows = [{"strategy": "BV_MIN", "inputs": {"a": 0}}, {"strategy": "MIXED", "inputs": {"a": 0}},
            {"strategy": "BV_MAX", "inputs": {"a": 9}}, {"strategy": "GLOBAL_0", "inputs": {"a": 5, "g": 0}},
            {"strategy": "MCDC_0", "inputs": {"a": 3}}]
    code = [{"strategy": "CODE_0", "inputs": {"a": 4}}]
    monkeypatch.setattr(suts, "_code_rows", lambda *_a, **_k: ([dict(c) for c in code], {"status": "searched"}, []))

    def block(budget):
        unit = {"name": "f"}
        out = suts._reference_scale_block(unit, [dict(r) for r in rows], len(rows), budget, {"input_vars": ["a"]},
                                          False, {})
        return _names(out), unit["reference_code_rows"]
    names, rec = block(3)
    assert names == ["GLOBAL_0", "MCDC_0", "CODE_0"] and rec["fill"] == 1 and rec["displaced"] == 3
    names, _rec = block(5)       # then the distinct rows in catalogue order — the duplicate MIXED last
    assert names == ["BV_MIN", "BV_MAX", "GLOBAL_0", "MCDC_0", "CODE_0"]
    names, _rec = block(6)
    assert names == ["BV_MIN", "MIXED", "BV_MAX", "GLOBAL_0", "MCDC_0", "CODE_0"]
    # a code row equal to a catalogue row gives its place to that row (the catalogue row keeps its name and role)
    code[:] = [{"strategy": "CODE_0", "inputs": {"a": 9}}, {"strategy": "CODE_1", "inputs": {"a": 4}}]
    names, rec = block(3)
    assert names == ["BV_MAX", "MCDC_0", "CODE_0"] and rec["same_as_catalogue"] == 1 and rec["rows"] == 1


def test_a_target_only_a_cut_row_reached_is_not_counted_as_reached(monkeypatch):
    # (review R85 W4) three rows found, room for one: the targets the two cut rows first reached are not the document's
    found = {"rows": [{"inputs": {"g_mode": 3, "g_tmr": 600}, "target_kind": "branch", "target_line": 9,
                       "target_text": "g_tmr >= T_LIM", "target_outcome": True, "targets_reached": 2},
                      {"inputs": {"g_mode": 3, "g_tmr": 1}, "target_kind": "statement", "target_line": 16,
                       "target_text": "g_res = 1U", "target_outcome": None, "targets_reached": 1},
                      {"inputs": {"g_mode": 3, "g_tmr": 600}, "target_kind": "boundary", "target_line": 9,
                       "target_text": "g_tmr >= T_LIM", "target_outcome": None, "targets_reached": 0,
                       "exposures_met": 1, "exposure": [600, 600]}],
             "report": {"status": "searched", "targets": 5, "reached_clean": 3, "expose_targets": 2,
                        "expose_reached": 1, "rows": 2, "expose_rows": 1}}
    full = _unit()
    generate_sequences(full, 24, type_cache=TYPES)
    monkeypatch.setattr(suts, "find_scenarios", lambda *_a, **_k: found)
    unit = _unit()
    generate_sequences(unit, full["reference_code_rows"]["kept"] + 1, type_cache=TYPES)
    rec = unit["reference_code_rows"]
    assert (rec["rows"], rec["found"], rec["cut"], rec["cut_expose"]) == (1, 3, 2, 1)
    assert (rec["reached_clean"], rec["expose_reached"]) == (2, 0)
    # (review R85 W-R3-3) the targets the cut rows first reached have their own count
    assert (rec["cut_reached"], rec["cut_exposed"]) == (1, 1)


def test_the_extended_document_starts_with_the_reference_scale_document_whatever_the_cap():
    # (review R85 C1) `generate_suts` passes its `max_sequences` as the extension's reference budget
    for cap in (2, 4, 6, 8, 10, 12, 24, None):
        ref = generate_sequences(_unit(), cap, type_cache=TYPES)
        ext = generate_sequences(_unit(), None, type_cache=TYPES, extended=True, reference_cap=cap)
        assert _names(ext[:len(ref)]) == _names(ref), cap
        tags = [s.get("tc_profile") == TC_PROFILE_EXTENDED for s in ext]
        assert tags == [is_extended_strategy(s["strategy"]) for s in ext], cap
    # a small budget moves an MC/DC row out of the block — still that vector's row in the extended document
    unit = _unit()
    ext = generate_sequences(unit, None, type_cache=TYPES, extended=True, reference_cap=2)
    moved = [s for s in ext if s["strategy"] == CATALOG_PREFIX + "MCDC_2"]
    assert moved and moved[0]["mcdc_design"]
    summary = unit["mcdc_design"]["summary"]
    assert summary["designed_pairs"] and summary["retained_pairs"] == summary["designed_pairs"]
    # with no cap the reference-scale document has the whole catalogue's row count (review R85 W5)
    unit = _unit()
    assert len(generate_sequences(unit, None, type_cache=TYPES)) == unit["base_strategy_count"]


def test_the_increment_of_the_extended_document_counts_each_row_once():
    rows = {"F": [{"strategy": "BV_MID"}, {"strategy": "CODE_0"},
                  {"strategy": "CATALOG_MIXED", "tc_profile": TC_PROFILE_EXTENDED},
                  {"strategy": "OAT_0_MIN", "tc_profile": TC_PROFILE_EXTENDED},
                  {"strategy": "BND_0", "tc_profile": TC_PROFILE_EXTENDED}]}
    assert suts.profile_increment(rows, True) == (2, 1)
    assert suts.profile_increment(rows, False) == (0, 0)


def test_the_base_order_is_the_catalogue_order_whatever_the_block_did():
    # (review R85 W1) the block puts the code rows and the kept rows before displaced catalogue rows; the base candidates
    #   keep the catalogue order, the code rows are added bases (after the others, like the scenario rows)
    # the slot each catalogue row was made in (`catalogue_slot`, review R85 I-7): BV_MIN 1 · BV_MID 2 · COND_COMB_0 6 ·
    #   SWITCH_0 10 · GLOBAL_0 19 · MCDC_0 23 — an extended row (OAT) has none
    slots = {"BV_MIN": 1, "MCDC_0": 23, "CATALOG_COND_COMB_0": 6, "CATALOG_GLOBAL_0": 19, "BV_MID": 2, "SWITCH_0": 10}
    rows = [{"strategy": s, **({"catalogue_slot": slots[s]} if s in slots else {})}
            for s in ("BV_MIN", "MCDC_0", "CODE_0", "CATALOG_COND_COMB_0", "CATALOG_GLOBAL_0", "BV_MID", "OAT_0_MIN",
                      "SWITCH_0", "SCN_0")]
    assert _names(suts._base_order(suts._search_rows(rows))) == [
        "BV_MID", "MCDC_0", "CATALOG_COND_COMB_0", "BV_MIN", "SWITCH_0", "CATALOG_GLOBAL_0", "OAT_0_MIN", "SCN_0"]
    # (review R85 I-R4-2) the code rows never reach a search — the rank helpers do not deal with them
    assert not suts._is_scenario({"strategy": "CODE_1"})
    # the generator marks the slot where it makes the row
    rows = generate_sequences(_unit(), None, type_cache=TYPES, extended=True)
    made = [s for s in rows if s.get("catalogue_slot") is not None]
    assert made and all(not is_extended_strategy(s["strategy"]) or s["strategy"].startswith(CATALOG_PREFIX)
                        for s in made)
    assert all(s.get("catalogue_slot") is None for s in rows if s["strategy"].startswith(("OAT_", CODE_PREFIX)))


def test_no_room_and_no_design_inputs_skip_the_search(monkeypatch):
    calls = []
    real = suts.find_scenarios
    monkeypatch.setattr(suts, "find_scenarios", lambda *a, **k: calls.append(1) or real(*a, **k))
    full = _unit()
    generate_sequences(full, 24, type_cache=TYPES)
    unit = _unit()
    rows = generate_sequences(unit, full["reference_code_rows"]["kept"], type_cache=TYPES)
    assert unit["reference_code_rows"]["status"] == "no_room" and len(calls) == 1
    assert all(s["strategy"].startswith(_REFERENCE_KEEP) for s in rows)
    unit = _unit(design_input_vars=[])
    generate_sequences(unit, 24, type_cache=TYPES)
    assert unit["reference_code_rows"]["status"] == "no_design_inputs" and len(calls) == 1
    assert not unit["reference_code_rows"]["rows"]


def test_a_failing_code_search_keeps_the_catalogue_rows(monkeypatch):
    plain = _unit()
    with monkeypatch.context() as m:
        # a search that found nothing (review R85 W-R2-2: a 2-tuple here took the error path too — a tautology)
        m.setattr(suts, "_code_rows", lambda *_a, **_k: ([], {"status": "searched"}, []))
        before = generate_sequences(plain, 24, type_cache=TYPES)
    assert plain["reference_code_rows"]["status"] == "searched" and len(before) == plain["reference_code_rows"]["budget"]

    def boom(*_a, **_k):
        raise RuntimeError("search failed")
    monkeypatch.setattr(suts, "find_scenarios", boom)
    unit = _unit()
    rows = generate_sequences(unit, 24, type_cache=TYPES)
    rec = unit["reference_code_rows"]
    assert rec["status"] == "error" and rec["error"] == "RuntimeError" and rec["rows"] == 0
    # the document of before R85: the catalogue rows in their order, values and all
    assert _names(rows) == _names(before) and [s["inputs"] for s in rows] == [s["inputs"] for s in before]
    summary = summarize_reference_code_rows([unit])
    assert summary["errors"] == 1
    item = next(i for i in build_disclosures("suts", {"reference_code_rows": summary})
                if i["key"] == "suts_reference_code_rows")
    assert "카탈로그 행만으로 채운 unit 1" in item["note"] and item["tone"] != "info"


def test_the_code_search_runs_on_design_inputs_once_for_all_the_extended_rounds(monkeypatch):
    # g_cnt is read but not in the design's input list: the extension adds it (R19) and generates again per round —
    #   the code rows are the reference-scale document's, searched on the design inputs, once
    calls = []
    real = suts.find_scenarios

    def spy(*a, **k):
        if inspect.stack()[1].function == "_code_rows":
            calls.append(sorted(a[1]))
        return real(*a, **k)
    monkeypatch.setattr(suts, "find_scenarios", spy)
    # the generator's type table — the one `extended_unit_sequences` reads too
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    ref = generate_sequences(_unit(input_vars=["g_mode", "g_tmr"]), 24)
    assert calls == [["g_mode", "g_tmr"]]
    unit = _unit(input_vars=["g_mode", "g_tmr"])
    ext = suts.extended_unit_sequences(unit)
    assert "g_cnt" in unit["input_vars"] and calls == [["g_mode", "g_tmr"]] * 2
    assert "_code_rows_cache" not in unit
    # (review R85 C-R2-1) the whole reference-scale block, not only its code rows: the fixed values the extension gives
    #   its added input do not change which catalogue rows fill the room
    assert _names(ext[:len(ref)]) == _names(ref)
    code_ref = [s for s in ref if s["strategy"].startswith(CODE_PREFIX)]
    code_ext = [s for s in ext if s["strategy"].startswith(CODE_PREFIX)]
    assert code_ref and _names(code_ext) == _names(code_ref)
    for a, b in zip(code_ext, code_ref, strict=True):
        assert {k: a["inputs"].get(k) for k in ("g_mode", "g_tmr")} == {k: b["inputs"].get(k) for k in ("g_mode", "g_tmr")}
        # the added input: the catalogue rows' fixed value (R19), said in the row
        assert "g_cnt" in a["inputs"] and "g_cnt" not in b["inputs"] and "소스가 읽어 더한 입력" in a["description"]


def test_the_summary_and_the_disclosure_say_how_the_room_was_used():
    units = [_unit(), _unit(design_input_vars=[])]
    for u in units:
        generate_sequences(u, 24, type_cache=TYPES)
    summary = summarize_reference_code_rows(units)
    rec = units[0]["reference_code_rows"]
    assert summary["units"] == 2 and summary["searched"] == 1 and summary["no_design_inputs"] == 1
    assert summary["rows"] == rec["rows"] and summary["displaced"] == rec["displaced"] + \
        units[1]["reference_code_rows"]["displaced"]
    assert summary["cap_per_search"] == suts._SCENARIO_MAX_ROWS
    item = next(i for i in build_disclosures("suts", {"reference_code_rows": summary})
                if i["key"] == "suts_reference_code_rows")
    assert item["tone"] == "info" and f"{rec['rows']}행" in item["value"]
    for text in ("행 수를 예전 그대로", "MC/DC 설계 벡터", "타입 경계값", "CATALOG_", "설계 입력이 없어 찾지 않은 unit 1",
                 f"깨끗하지 않게만 닿음 {summary['reached_unclean_only']}", f"닿지 못함 {summary['not_reached']}",
                 f"자리를 준 행 {summary['same_as_catalogue']}", f"탐색 실행 {summary['runs']}"):
        assert text in item["note"], text
    assert "suts_reference_code_rows" not in {i["key"] for i in build_disclosures("suts", {})}


@pytest.mark.parametrize("cap", [3, 12])
def test_an_extended_call_with_a_cap_cuts_its_catalogue_part_at_the_cap(cap):
    # as before R85: the cap cuts the catalogue part (here the reference-scale block, then the displaced and the extended
    #   catalogue rows); the rows the extension then appends (MC/DC fill · scenario rows) come after it
    ref = generate_sequences(_unit(), cap, type_cache=TYPES)
    # the same reference budget as the reference-scale document (`generate_suts` passes its `max_sequences`)
    rows = generate_sequences(_unit(), cap, type_cache=TYPES, extended=True, boundary_rows=False, reference_cap=cap)
    appended = (suts.MCDC_FILL_PREFIX, suts.SCENARIO_PREFIX, suts.SCENARIO_FI_PREFIX)
    head = [s for s in rows if not s["strategy"].startswith(appended)]
    assert rows[:len(head)] == head and len(head) == cap
    assert _names(head)[:len(ref)] == _names(ref)
    assert [s["seq_num"] for s in rows] == list(range(1, len(rows) + 1))


@pytest.mark.parametrize("cap", [4, 6, 8, 10, 12, 24])
def test_the_extended_rounds_keep_the_reference_scale_block_whatever_the_cap(monkeypatch, cap):
    # (review R85 C-R2-1 · W-R2-4) g_cnt is read but not designed: the extension adds it (R19) with a fixed value in the
    #   catalogue rows; the block is chosen on the reference-scale view, through every round (the round lambda passes the
    #   reference budget too)
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    ref = generate_sequences(_unit(input_vars=["g_mode", "g_tmr"]), cap)
    unit = _unit(input_vars=["g_mode", "g_tmr"])
    ext = suts.extended_unit_sequences(unit, reference_cap=cap)
    assert "g_cnt" in unit["input_vars"]
    assert _names(ext[:len(ref)]) == _names(ref), cap
    for a, b in zip(ext, ref, strict=False):   # the extension is longer — its first len(ref) rows
        assert {k: a["inputs"].get(k) for k in ("g_mode", "g_tmr")} == {k: b["inputs"].get(k) for k in ("g_mode", "g_tmr")}


def test_generate_suts_passes_its_sequence_cap_as_the_extensions_reference_budget(tmp_path, monkeypatch):
    # (review R85 W-R2-4) the extended document starts with the reference-scale document of the same cap
    (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 Fn(U8 a, U8 b)\n{\n    if (a > 1) { return b; }\n"
                                  "    return 0;\n}\n", encoding="utf-8")
    seen = []
    real = suts.extended_unit_sequences

    def spy(unit, reference_cap=suts._DEFAULT_SEQ_COUNT):
        seen.append(reference_cap)
        return real(unit, reference_cap)
    monkeypatch.setattr(suts, "extended_unit_sequences", spy)
    suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "e.xlsm"), scope="source",
                       tc_profile="extended", max_sequences=7)
    assert seen and set(seen) == {7}


def test_the_search_pools_hold_no_code_row_and_put_the_scenario_rows_first():
    # (review R85 W-R2-1 · I-R4-2) the extension's bounded pools: its scenario rows first, no reference-scale code row
    rows = [{"strategy": s, "inputs": {"a": i}} for i, s in enumerate(("BV_MID", "CODE_0", "CODE_1", "SCN_0", "SCNR_0"))]
    assert _names(suts._scenario_rows_first(suts._search_rows(rows))) == ["SCN_0", "SCNR_0", "BV_MID"]
    assert _names(suts._base_order([r for r in suts._search_rows(rows) if suts._is_scenario(r)])) == ["SCN_0", "SCNR_0"]


def test_a_code_row_says_which_fixed_inputs_are_read_and_which_are_prior_values(monkeypatch):
    # (review R85 I4 · I-6 M5) as the catalogue rows say it (R82)
    row = {"inputs": {"g_mode": 3}, "target_kind": "branch", "target_line": 8, "target_text": "g_mode == ON_MODE",
           "target_outcome": True, "targets_reached": 1}
    monkeypatch.setattr(suts, "find_scenarios", lambda *_a, **_k: {"rows": [row], "report": {"status": "searched"}})
    ctx = {"input_vars": ["g_mode"], "output_vars": ["g_res"], "var_types": {"g_mode": "U8"}, "var_bounds": {},
           "unknown": [], "declared": ["g_mode"], "enum_sets": None}
    rows, _rep, cut = suts._code_rows(_unit(), [], ctx, 1, {"g_cnt": 5, "g_res": 1}, frozenset({"g_res"}))
    text = rows[0]["description"]
    assert not cut and rows[0]["inputs"] == {"g_mode": 3, "g_cnt": 5, "g_res": 1}
    read = [ln for ln in text.splitlines() if ln.startswith("소스가 읽어 더한 입력")]
    wrote = [ln for ln in text.splitlines() if ln.startswith("쓰기 전 값")]
    # (review R85 W-R3-2) each input on its own line only
    assert read == ["소스가 읽어 더한 입력(설계서 입력 표 밖 · 이 행에선 고정값): g_cnt=5"]
    assert wrote == ["쓰기 전 값(함수가 쓰는 객체의 호출 전 값 · 이 행에선 고정값): g_res=1"]


def test_a_design_without_outputs_has_its_code_rows_observe_the_indirect_globals():
    # (review R85 I5 · I-6 M6) like the VOID_SIDE_EFFECT row — otherwise a code row observes nothing
    unit = _unit(output_vars=[], indirect_vars=["g_res", "g_cnt"])
    rows = generate_sequences(unit, 24, type_cache=TYPES)
    code = [s for s in rows if s["strategy"].startswith(CODE_PREFIX)]
    assert code and all({"g_res", "g_cnt"} <= set(s["expected"]) for s in code)


def test_a_displaced_mc_dc_row_still_gets_its_fill_row_and_the_displaced_rows_stay():
    # (review R85 I-6 M12 · I-2) a small budget moves MCDC_2 out of the block: its fill row is there as for the others,
    #   and no displaced catalogue row is dropped as a duplicate (before R85 they were reference-scale rows)
    unit = _unit()
    ext = generate_sequences(unit, None, type_cache=TYPES, extended=True, reference_cap=2)
    mcdc = [s for s in ext if suts._catalog_name(s["strategy"]).startswith("MCDC_")]
    fills = [s for s in ext if s["strategy"].startswith(suts.MCDC_FILL_PREFIX)]
    assert len(mcdc) == 3 and len(fills) == unit["mcdc_fill"]["rows"] >= 1
    assert {f["mcdc_fill"]["from_sequence"] for f in fills} <= {s["seq_num"] for s in mcdc}
    # (review R85 W-R3-2) the displaced MC/DC row has its own fill row, and keeps its note after the label rewrite
    moved = next(s for s in mcdc if s["strategy"] == CATALOG_PREFIX + "MCDC_2")
    assert any(f["mcdc_fill"]["from_sequence"] == moved["seq_num"] for f in fills)
    assert moved["description"].startswith("정본 규모 문서에 들지 못한 카탈로그 행")
    assert len([s for s in ext if s["strategy"].startswith(CATALOG_PREFIX)]) == unit["reference_code_rows"]["displaced"]

def test_the_code_search_cache_is_keyed_by_its_start_rows(monkeypatch):
    # the cached search is re-used only for the same domains, outputs and start rows (the kept rows)
    calls = []
    real = suts.find_scenarios
    monkeypatch.setattr(suts, "find_scenarios", lambda *a, **k: calls.append(1) or real(*a, **k))
    bounds = {"g_mode": {"min": 0, "max": 255, "mid": 127}, "g_tmr": {"min": 0, "max": 65535, "mid": 32767}}
    ctx = {"input_vars": ["g_mode", "g_tmr"], "output_vars": ["g_res"], "var_types": dict(TYPES), "var_bounds": bounds,
           "unknown": [], "declared": ["g_mode", "g_tmr"], "enum_sets": None}
    unit = _unit()
    assert set(suts._scenario_domains(unit, ctx)) == {"g_mode", "g_tmr"}
    suts._code_rows(unit, [{"inputs": {"g_mode": 0, "g_tmr": 0}}], ctx, 4, {})
    suts._code_rows(unit, [{"inputs": {"g_mode": 0, "g_tmr": 0}}], ctx, 4, {})
    assert len(calls) == 1
    suts._code_rows(unit, [{"inputs": {"g_mode": 3, "g_tmr": 0}}], ctx, 4, {})
    assert len(calls) == 2
    # (review R85 I-R4-1) the same start rows, but an outside-design row among them is no covered row: a new search
    suts._code_rows(unit, [{"inputs": {"g_mode": 3, "g_tmr": 0}, "strategy": "BV_MAX_INV"}], ctx, 4, {})
    assert len(calls) == 3
    # the same covered rows (none) from other start rows: a new search too
    suts._code_rows(unit, [{"inputs": {"g_mode": 9, "g_tmr": 1}, "strategy": "BV_MAX_INV"}], ctx, 4, {})
    assert len(calls) == 4


@pytest.mark.parametrize("cap", [0, -3])
def test_a_cap_of_zero_or_below_is_no_room(cap):
    # (review R85 I-9) not a negative budget (a negative slice would keep all rows but the last ones)
    unit = _unit()
    assert generate_sequences(unit, cap, type_cache=TYPES) == []
    rec = unit["reference_code_rows"]
    assert rec["budget"] == 0 and rec["kept"] == 0 and rec["status"] == "no_room"

@pytest.mark.parametrize("variant", ["globals_no_additions", "ranges_with_addition", "globals_with_addition"])
@pytest.mark.parametrize("cap", [4, 6, 8, 10, 24])
def test_both_profiles_choose_the_same_block(monkeypatch, variant, cap):
    # (review R85 W-R3-1) the first extended call (a unit the extension adds nothing to — its first call is the
    #   document), a code row equal to BV_MID through the rounds (design ranges, g_cnt added), and GLOBAL rows with an
    #   added input: the extended document starts with the reference-scale document
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    kw = {"globals_no_additions": {"input_vars": ["g_mode", "g_tmr", "g_cnt", "g_res"], "indirect_vars": ["g_res", "g_cnt"]},
          "ranges_with_addition": {"input_vars": ["g_mode", "g_tmr"],
                                   "uds_param_info": {"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}}},
          "globals_with_addition": {"input_vars": ["g_mode", "g_tmr"], "indirect_vars": ["g_res", "g_cnt"]}}[variant]
    base = _unit(**kw)
    ref = generate_sequences(base, cap)
    unit = _unit(**kw)
    ext = suts.extended_unit_sequences(unit, reference_cap=cap)
    if variant == "globals_no_additions":     # no rounds: the first extended call is the document
        assert not (unit.get("source_read_inputs") or {}).get("added")
    assert _names(ext[:len(ref)]) == _names(ref), (variant, cap)
    for a, b in zip(ext, ref, strict=False):   # the extension is longer — its first len(ref) rows
        assert {k: a["inputs"].get(k) for k in ("g_mode", "g_tmr")} == {k: b["inputs"].get(k) for k in ("g_mode", "g_tmr")}
    assert unit["reference_code_rows"]["same_as_catalogue"] == base["reference_code_rows"]["same_as_catalogue"]


def test_unclean_only_reach_is_recorded_and_disclosed():
    # (review R85 W-R3-2 · W-R2-3) with g_tmr left out of the design inputs the inner branch reads a value no row gives:
    #   the search reaches it only uncleanly — counted, not a row
    unit = _unit(input_vars=["g_mode"])
    generate_sequences(unit, 24, type_cache=TYPES)
    rec = unit["reference_code_rows"]
    assert rec["reached_unclean_only"] >= 1
    summary = summarize_reference_code_rows([unit])
    item = next(i for i in build_disclosures("suts", {"reference_code_rows": summary})
                if i["key"] == "suts_reference_code_rows")
    assert f"깨끗하지 않게만 닿음 {rec['reached_unclean_only']}" in item["note"]


def _poisoned(real):
    # (review R85 W-R4-4) code rows that would move every step that looks at them: vectors on the code's constants and
    #   more outputs than the design lists
    def code_rows(*a, **k):
        rows, rep, cut = real(*a, **k)
        extra = [{"seq_num": 0, "inputs": {"g_mode": gm, "g_tmr": gt, "g_cnt": 7},
                  "expected": {v: "[검증 필요] scenario" for v in ("g_res", "g_cnt", "g_mode", "g_tmr")},
                  "strategy": f"{CODE_PREFIX}P{i}", "description": "poison", "code_row": {}}
                 for i, (gm, gt) in enumerate(((3, 600), (3, 599), (3, 0), (1, 600)))]
        return rows + extra, rep, cut
    return code_rows


@pytest.mark.parametrize("poison", [False, True])
@pytest.mark.parametrize("kw", [{}, {"input_vars": ["g_mode", "g_tmr"]}, {"indirect_vars": ["g_res", "g_cnt"]},
                                {"uds_param_info": {"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}}},
                                {"uds_param_info": {"g_tmr": {"range": [0, 500]}}}])
def test_the_extension_runs_as_if_the_code_rows_were_not_there(monkeypatch, kw, poison):
    # (R85 measurement: with the code rows as existing / covered rows the extended document lost 34 HDPDM01 kills —
    #   its scenario and boundary rows thinned) every extended row but the code rows is the row the extension made
    #   without them, in the same order (the catalogue rows by their slot, the rest by document order), with the same
    #   columns
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    with monkeypatch.context() as m:
        if poison:
            m.setattr(suts, "_code_rows", _poisoned(suts._code_rows))
        with_code = suts.extended_unit_sequences(_unit(**kw))
    with monkeypatch.context() as m:
        m.setattr(suts, "_code_rows", lambda *_a, **_k: ([], {"status": "isolated"}, []))
        without = suts.extended_unit_sequences(_unit(**kw))

    def view(rows):
        return [(suts._catalog_name(s["strategy"]), json.dumps(s["inputs"], sort_keys=True, default=str),
                 tuple(sorted(s.get("expected") or {}))) for s in suts._search_rows(rows)]
    assert any(s["strategy"].startswith(CODE_PREFIX) for s in with_code)
    assert view(with_code) == view(without)


@pytest.mark.parametrize("kw", [{}, {"uds_param_info": {"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}}},
                                {"input_vars": ["g_mode", "g_tmr"], "indirect_vars": ["g_res", "g_cnt"]}])
def test_no_extended_search_starts_from_or_counts_a_code_row(monkeypatch, kw):
    # every search of the extension (scenario, outside-design, propagation …) gets its start and covered rows without the
    #   reference-scale code rows — only the code search itself sees them. The searches get the rows' own input dicts, so
    #   the check is by identity with every code row made in any round (a code row equal to another row would hide it from
    #   a value comparison)
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    calls, made = [], []
    real_search, real_code = suts.find_scenarios, suts._code_rows

    def spy(*a, **k):
        calls.append((inspect.stack()[1].function, bool(k.get("propagate")),
                      list(a[3] if len(a) > 3 else k.get("existing") or []) + list(k.get("covered") or [])))
        return real_search(*a, **k)

    def code_spy(*a, **k):
        out = real_code(*a, **k)
        made.extend(s["inputs"] for s in out[0])
        return out
    monkeypatch.setattr(suts, "find_scenarios", spy)
    monkeypatch.setattr(suts, "_code_rows", code_spy)
    rows = suts.extended_unit_sequences(_unit(**kw))
    searches = [c for c in calls if c[0] != "_code_rows"]
    assert made and any(s["strategy"].startswith(CODE_PREFIX) for s in rows)
    assert any(prop for _f, prop, _rows in searches) and all(given for _f, _p, given in searches)
    for _f, _prop, given in searches:
        assert not any(v is c for v in given for c in made)


def test_the_outside_design_propagation_search_checks_no_code_row(monkeypatch):
    # the second propagation search (outside the design) runs when the first one leaves a target unmet — its checked rows
    #   are this step's rows and the rows before them, code rows left out like everywhere else in the extension
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    calls, made = [], []
    real_search, real_code = suts.find_scenarios, suts._code_rows

    def spy(*a, **k):
        if k.get("propagate") and not any(c.get("propagate") for c in calls):
            calls.append(dict(k))
            return {"rows": [], "reached_vectors": [], "report": {"status": "searched", "expose_targets": 1,
                                                                   "expose_not_reached": 1}}
        calls.append(dict(k))
        return real_search(*a, **k)

    def code_spy(*a, **k):
        out = real_code(*a, **k)
        made.extend(s["inputs"] for s in out[0])
        return out
    monkeypatch.setattr(suts, "find_scenarios", spy)
    monkeypatch.setattr(suts, "_code_rows", code_spy)
    unit = _unit(uds_param_info={"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}})
    suts.extended_unit_sequences(unit)
    second = [c for c in calls if c.get("propagate") and "home" in c]
    assert made and second and all(c["covered"] for c in second)
    assert not any(v is m for c in second for v in c["covered"] for m in made)
    assert unit["propagation_rows"]["outside_design_inputs"] >= 1


def test_an_extended_row_equal_to_a_code_row_is_not_dropped_as_its_duplicate():
    # before R85 the OAT row was there (the extension runs as if the code rows were not); a code row is never dropped
    #   either — an extended row with a code row's inputs is said and counted instead (`_note_rows_equal_to_code_rows`)
    rows = [{"seq_num": 1, "strategy": "CODE_0", "inputs": {"a": 1}},
            {"seq_num": 2, "strategy": "OAT_0_MIN", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED},
            {"seq_num": 3, "strategy": "OAT_1_MIN", "inputs": {"a": 1}, "tc_profile": TC_PROFILE_EXTENDED}]
    unit = {"name": "f"}
    kept = suts._drop_duplicate_rows(unit, [dict(r) for r in rows], True)
    assert _names(kept) == ["CODE_0", "OAT_0_MIN"] and unit["duplicate_rows"]["extended_rows_dropped"] == 1


def test_an_fi_row_holds_its_types_or_it_is_no_kept_row():
    # (review R85 W-R4-3) the same type table the catalogue made the values from; bool · bit only below zero; enum ·
    #   unknown · float pass. (review R85 W-R5-1) only a declared type vetoes — a guessed one (`uint8_t` by default) never
    types = {"a": "uint8_t", "b": "uint16_t", "f": "bool", "e": "enum", "u": "unknown", "x": "float"}
    d = set(types)
    assert suts._holds_declared_types({"a": 255, "b": 65535}, types, d)
    assert not suts._holds_declared_types({"a": 256}, types, d) and not suts._holds_declared_types({"b": -1}, types, d)
    assert not suts._holds_declared_types({"a": "0x100"}, types, d) and suts._holds_declared_types({"a": "0xFF"}, types, d)
    assert suts._holds_declared_types({"f": "0x2", "e": 99, "u": 70000, "x": 1001.0, "a": "n/a"}, types, d)
    assert not suts._holds_declared_types({"f": -1}, types, d)
    assert suts._holds_declared_types({"a": 256, "b": -1, "f": -1}, types, set())
    # a design range inside the type: BV_MAX_INV holds 7 · 1201 · 101 (kept); BV_MIN_INV holds −1 (filled last)
    unit = _unit(uds_param_info={"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}, "g_cnt": {"range": [0, 100]}})
    rows = generate_sequences(unit, 24, type_cache=TYPES)
    rec = unit["reference_code_rows"]
    assert "BV_MAX_INV" in _names(rows) and rec["kept"] == 4 and rec["fi_out_of_type"] == 1
    assert {k: _int(v) for k, v in next(s for s in rows if s["strategy"] == "BV_MAX_INV")["inputs"].items()} == \
        {"g_mode": 7, "g_tmr": 1201, "g_cnt": 101}


def test_the_code_search_starts_from_the_fi_rows_but_does_not_count_them_as_covering(monkeypatch):
    # (review R85 I-R4-1) a target an FI row (outside the design) reaches still gets an in-range row
    seen = []
    real = suts.find_scenarios

    def spy(unit, domains, outputs, existing=None, **k):
        if inspect.stack()[1].function == "_code_rows":
            seen.append((list(existing or []), list(k.get("covered") or [])))
        return real(unit, domains, outputs, existing, **k)
    monkeypatch.setattr(suts, "find_scenarios", spy)
    unit = _unit(uds_param_info={"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}, "g_cnt": {"range": [0, 100]}})
    rows = generate_sequences(unit, 24, type_cache=TYPES)
    fi = [{k: v for k, v in s["inputs"].items()} for s in rows if s["strategy"] == "BV_MAX_INV"]
    (existing, covered), = seen
    assert fi and fi[0] in existing and fi[0] not in covered and len(covered) == len(existing) - 1


def test_an_extended_row_with_a_code_rows_inputs_is_said_and_counted(monkeypatch):
    # (review R85 W-R4-1) the extension searches as if the code rows were not there — it may find a code row's vector
    #   again; the row stays (other rows name it as their base) and says so
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit(uds_param_info={"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}, "g_cnt": {"range": [0, 100]}})
    rows = suts.extended_unit_sequences(unit)
    same = [s for s in rows if s.get("same_inputs_as_code_row")]
    code = {s["strategy"]: s["inputs"] for s in rows if s["strategy"].startswith(CODE_PREFIX)}
    assert same and unit["reference_code_rows"]["extension_same_inputs"] == len(same)
    for s in same:
        assert s["tc_profile"] == TC_PROFILE_EXTENDED and s["inputs"] == code[s["same_inputs_as_code_row"]]
        assert s["description"].count(f"정본 규모 코드 기준 행 {s['same_inputs_as_code_row']} 와 입력이 같음") == 1
    suts._note_rows_equal_to_code_rows(unit, rows)   # again: counted once more, said once
    assert all(s["description"].count("정본 규모 코드 기준 행") == 1 for s in same)
    assert unit["reference_code_rows"]["extension_same_inputs"] == len(same)
    summary = summarize_reference_code_rows([unit])
    note = {i["key"]: i for i in build_disclosures("suts", {"reference_code_rows": summary})}["suts_reference_code_rows"]
    assert f"코드 기준 행과 입력이 같은 확장 행이 {len(same)}" in note["note"]
    # (review R85 I-R5-4) a reference-scale run has no extended row to speak of
    plain = summarize_reference_code_rows([dict(unit, reference_code_rows=dict(unit["reference_code_rows"],
                                                                                 extension_same_inputs=0))])
    note = {i["key"]: i for i in build_disclosures("suts", {"reference_code_rows": plain})}["suts_reference_code_rows"]
    assert "입력이 같은 확장 행" not in note["note"]


@pytest.mark.parametrize("cap", [6, 8, 12, 24])
def test_the_extended_cap_keeps_every_catalogue_and_extension_row(monkeypatch, cap):
    # (review R85 W-R4-2) the gate says the extension drops no catalogue or extension row at a cap — the cap sets the
    #   reference-scale block only (its code rows follow the cap)
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    full = suts.extended_unit_sequences(_unit(), None)
    capped = suts.extended_unit_sequences(_unit(), cap)

    def names(rows):
        return sorted(suts._catalog_name(s["strategy"]) for s in rows if not s["strategy"].startswith(CODE_PREFIX))
    assert names(capped) == names(full)
    assert sum(1 for s in capped if s["strategy"].startswith(CODE_PREFIX)) <= \
        sum(1 for s in full if s["strategy"].startswith(CODE_PREFIX))


# (review R85 W-R5-1 · I-R5-1) a typedef the generator's type table does not know — the source model knows it
COMMON_T = """#ifndef COMMON_T_H
#define COMMON_T_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef unsigned int T_Tmr;
typedef unsigned char boolean;
#define T_LIM 600U
#endif
"""
UNIT_T = """#include "common_t.h"
T_Tmr g_tmr;
boolean g_en;
U8 g_res;
void ctl(void)
{
    if ((g_en != 0U) && (g_tmr >= T_LIM))
    {
        g_res = 2U;
    }
    else
    {
        g_res = 1U;
    }
}
"""


def _unit_t():
    if "scope_t" not in _CACHE:
        files = {os.path.join(ROOT, "common_t.h"): COMMON_T, os.path.join(ROOT, "unit_t.c"): UNIT_T}
        context = cpc.build_project_context(files)
        _CACHE["scope_t"] = cpc.build_scopes(context, [os.path.join(ROOT, "unit_t.c")])[os.path.join(ROOT, "unit_t.c")]
    return {"name": "ctl", "fid": "F_ctl", "source_text": UNIT_T, "source_path": os.path.join(ROOT, "unit_t.c"),
            "source_text_complete": True, "project_scope": _CACHE["scope_t"], "input_vars": ["g_tmr", "g_en"],
            "output_vars": ["g_res"], "param_types": {}, "uds_param_info": {"g_tmr": {"range": [0, 1200]}}}


def test_a_row_outside_the_design_is_turned_away_only_on_evidence():
    # (review R85 W-R5-1) a guessed type vetoes nothing: g_tmr's type left out of the cache is guessed `uint8_t`, yet the
    #   source model holds 1201 in the declared U16 — BV_MAX_INV stays a kept row
    types = {k: v for k, v in TYPES.items() if k != "g_tmr"}
    unit = _unit(uds_param_info={"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}, "g_cnt": {"range": [0, 100]}})
    rows = generate_sequences(unit, 24, type_cache=types)
    rec = unit["reference_code_rows"]
    assert "BV_MAX_INV" in _names(rows) and rec["kept"] == 4 and rec["fi_out_of_type"] == 1
    # (review R85 I-R5-1) the source model refuses what the table cannot judge: −1 in a design-range typedef
    #   (`T_Tmr`, unsigned) and in a `boolean`
    unit = _unit_t()
    rows = generate_sequences(unit, 24, type_cache={"g_tmr": "T_Tmr", "g_en": "boolean", "g_res": "U8"})
    low = suts._oracle_refused_inputs(unit, [{"g_tmr": -1, "g_en": "0x1"}, {"g_tmr": 700, "g_en": "0x1"}], ["g_res"])
    assert low == [True, False]
    rec = unit["reference_code_rows"]   # BV_MIN_INV refused (filled last); BV_MAX_INV 1201 · boolean 0x2 held (kept)
    assert rec["fi_out_of_type"] == 1 and rec["kept"] == sum(1 for s in rows if s["strategy"].startswith("MCDC_")) + 1
    # no source model to ask (no scope): only the declared-type rule — nothing refused
    assert suts._oracle_refused_inputs({"name": "f"}, [{"a": 999}], ["o"]) == [False]


UNIT_T2 = """#include "common_t.h"
T_Tmr g_tmr;
boolean g_en;
U8 g_res;
void ctl2(void)
{
    if ((g_tmr >= T_LIM) && (g_en != 0U))
    {
        g_res = 2U;
    }
    else
    {
        g_res = 1U;
    }
}
"""


def test_the_source_model_alone_turns_a_row_away():
    # (R85 self-check) the earlier case also had boolean −1, which the type table vetoes by itself — here the only
    #   input is the design-range typedef `T_Tmr` (unsigned): the table holds −1, the source model refuses it, and that
    #   refusal alone keeps BV_MIN_INV out of the kept rows; 1201 sits in the declared U16 and stays
    path = os.path.join(ROOT, "unit_t2.c")
    if "scope_t2" not in _CACHE:
        files = {os.path.join(ROOT, "common_t.h"): COMMON_T, path: UNIT_T2}
        _CACHE["scope_t2"] = cpc.build_scopes(cpc.build_project_context(files), [path])[path]
    unit = {"name": "ctl2", "fid": "F_ctl2", "source_text": UNIT_T2, "source_path": path, "source_text_complete": True,
            "project_scope": _CACHE["scope_t2"], "input_vars": ["g_tmr"], "output_vars": ["g_res"], "param_types": {},
            "uds_param_info": {"g_tmr": {"range": [0, 1200]}}}
    rows = generate_sequences(unit, 24, type_cache={"g_tmr": "T_Tmr", "g_en": "boolean", "g_res": "U8"})
    assert suts._holds_declared_types({"g_tmr": -1}, {"g_tmr": "range"}, {"g_tmr"})
    assert suts._oracle_refused_inputs(unit, [{"g_tmr": -1}, {"g_tmr": 1201}], ["g_res"]) == [True, False]
    rec = unit["reference_code_rows"]
    assert rec["fi_out_of_type"] == 1   # BV_MIN_INV (filled last, if room); BV_MAX_INV kept
    assert rec["kept"] == sum(1 for s in rows if s["strategy"].startswith("MCDC_")) + 1


UNIT_T3 = """#include "common_t.h"
T_Tmr g_tmr;
U8 g_cnt;
U8 g_res;
void ctl3(void)
{
    if (g_cnt == 0U)
    {
        g_res = 0U;
    }
    else if (g_tmr >= T_LIM)
    {
        g_res = 2U;
    }
    else
    {
        g_res = 1U;
    }
}
"""


def test_the_outside_rows_are_judged_without_the_extensions_fixed_inputs(monkeypatch):
    # (R85 self-check) g_cnt is read but not designed: without it the source model cannot tell whether g_tmr is read,
    #   so −1 is not refused; the extension adds g_cnt (R19) at a fixed non-zero value, which would make the model read
    #   g_tmr and refuse −1. The block is judged on the reference-scale view, so both profiles keep the same rows
    path = os.path.join(ROOT, "unit_t3.c")
    if "scope_t3" not in _CACHE:
        files = {os.path.join(ROOT, "common_t.h"): COMMON_T, path: UNIT_T3}
        _CACHE["scope_t3"] = cpc.build_scopes(cpc.build_project_context(files), [path])[path]

    def unit():
        return {"name": "ctl3", "fid": "F_ctl3", "source_text": UNIT_T3, "source_path": path,
                "source_text_complete": True, "project_scope": _CACHE["scope_t3"], "input_vars": ["g_tmr"],
                "output_vars": ["g_res"], "param_types": {}, "uds_param_info": {"g_tmr": {"range": [0, 1200]}}}
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_tmr": "T_Tmr", "g_cnt": "U8", "g_res": "U8"})
    ref_unit, ext_unit = unit(), unit()
    ref = generate_sequences(ref_unit, 24)
    ext = suts.extended_unit_sequences(ext_unit)
    fixed = next(s for s in ext if suts._catalog_name(s["strategy"]) == "BV_MIN_INV")["inputs"]
    assert fixed.get("g_cnt") not in (None, 0)   # the premise: the extension fixes g_cnt at a value that reads g_tmr
    assert suts._oracle_refused_inputs(unit(), [{"g_tmr": -1}, {"g_tmr": -1, "g_cnt": fixed["g_cnt"]}],
                                       ["g_res"]) == [False, True]
    assert ref_unit["reference_code_rows"]["fi_out_of_type"] == ext_unit["reference_code_rows"]["fi_out_of_type"] == 0
    assert _names(ext[:len(ref)]) == _names(ref)


def _void_unit(**kw):
    return _unit(input_vars=["g_mode", "g_tmr"], output_vars=[], indirect_vars=["g_res", "g_cnt"], **kw)


def test_the_side_effect_row_follows_the_outside_design_rules(monkeypatch):
    # (review R85 W-R5-3) VOID_SIDE_EFFECT puts every input at its boundary plus one, as BV_MAX_INV does: past the type
    #   it is no kept row, inside it it is kept but covers nothing for the code search
    ext = generate_sequences(_void_unit(), None, type_cache=TYPES, extended=True)
    void = next(s for s in ext if suts._catalog_name(s["strategy"]) == "VOID_SIDE_EFFECT")
    assert {k: _int(v) for k, v in void["inputs"].items() if k in ("g_mode", "g_tmr")} == {"g_mode": 256, "g_tmr": 65536}
    # BV_MIN_INV (−1) · BV_MAX_INV and the side-effect row (256 · 65536): none kept, all three filled last — the code row
    #   takes the room the side-effect row would have had
    unit = _void_unit()
    rows = generate_sequences(unit, None, type_cache=TYPES)
    rec = unit["reference_code_rows"]
    assert rec["fi_out_of_type"] == 3 and rec["kept"] == 3 and rec["rows"] >= 1
    assert "VOID_SIDE_EFFECT" not in _names(rows) and rec["displaced"] == rec["rows"]
    seen = []
    real = suts.find_scenarios

    def spy(u, domains, outputs, existing=None, **k):
        if inspect.stack()[1].function == "_code_rows":
            seen.append((list(existing or []), list(k.get("covered") or [])))
        return real(u, domains, outputs, existing, **k)
    monkeypatch.setattr(suts, "find_scenarios", spy)
    unit = _void_unit(uds_param_info={"g_mode": {"range": [0, 6]}, "g_tmr": {"range": [0, 1200]}})
    rows = generate_sequences(unit, 24, type_cache=TYPES)
    void = next(s for s in rows if s["strategy"] == "VOID_SIDE_EFFECT")
    vin = {k: v for k, v in void["inputs"].items() if k in ("g_mode", "g_tmr")}
    (existing, covered), = seen
    assert {k: _int(v) for k, v in vin.items()} == {"g_mode": 7, "g_tmr": 1201}
    assert vin in existing and vin not in covered
