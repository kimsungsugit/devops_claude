"""R80 — outputs the source writes (backlog 2-b on the run model) and enum values outside the enumerators.

The SwUDS output table of HDPDM01 `u8s_SbcmMsg2_LinTmOutCheck` lists the sibling function's `u8s_SbcmMsgLinFailTimer` ·
`u16s_SbcmMsgLinFailTm`; the function writes `u8s_SbcmMsg2LinFailTimer` · `u16s_SbcmMsg2LinFailTm`. A suite that observes
the table's names cannot see a fault in the function's writes (two write-deletion mutants only the reference killed).
(1) The oracle reports the program objects a run *wrote* (`evaluate_outputs(written=True)` — the store, not a walk of the
body: R59's walk counted inactive `#if` arms and discarded macro arguments); (2) the extended profile adds those not in
the output list whose value some row derives as expected columns — in the source-read-input rounds and once more after
the late rows; (3) both profiles list "written, not in the output list" and "listed, written by nobody" in Source
Findings. `s_BuzzerStateCtrl` reaches its `default:` only with a value no enumerator names (the reference used 0 and 4
around 1 ~ 3): (4) a third scenario search, after the design-range (FI) one and on its own budget, widens value-set inputs
over all their enumerators (outside a design range too) and the enumerators' range ±1 — it leaves the earlier searches as
they were (measurement r80c: mixed into the design-range search it moved that search's climbs and lost a kill)."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import source_findings as sf
from generators import suts
from generators.c_source_oracle import evaluate_outputs
from generators.scenario_rows import SCENARIO_FI_PREFIX
from generators.suts import (
    _drop_underived_written_outputs,
    _enum_outside_values,
    _outside_enumerator_domains,
    extended_unit_sequences,
    generate_sequences,
    listed_outputs_not_written,
    output_list_gaps,
    source_written_names,
    summarize_source_written_outputs,
)
from generators.test_evidence import apply_sequence_evidence
from report_gen.generation_disclosures import build_disclosures

ROOT = os.path.join(os.sep, "proj")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef float F32;
typedef enum { B_STOP = 1, B_TWO = 2, B_THREE = 3 } Buz_t;
typedef enum { L_LO = -32768, L_HI = 32767 } Lim_t;
typedef enum { Z0 = 0, Z1 = 1, Z2 = 2 } Z_t;
typedef enum { M1 = 1, M5 = 5, M9 = 9 } Gap_t;
typedef enum { E1 = 1, E2, E3, E4, E5, E6, E7, E8, E9, E10, E11, E12, E13 } Big_t;
typedef struct { U8 a; U8 b; } St;
#define IGNORE(x) ((void)0)
#endif
"""
UNIT = """#include "common.h"
U8 g_t;
U8 g_t2;
U16 g_tm2;
U8 g_misc;
U8 g_buz_out;
U8 g_buf[4];
U8 g_y;
U8 g_x;
U8 g_u;
U8 g_in;
U8 g_w;
volatile U8 g_reg;
F32 g_f;
static Buz_t s_buz;
static Lim_t s_lim;
static Z_t s_z;
static Buz_t s_sa;
static Buz_t s_sb;
U8 g_q;
U8 g_late;
St g_st;
static Gap_t s_gap;
static Big_t s_big;
U8 g_k;
static Buz_t s_mode2;
U8 g_lvl2;
U8 tmout2(U8 d)
{
    U8 r = 0U;
    if (d == 0U) {
        g_t2 = 1U;
        if (g_tm2 > 60U) { g_t2 = 0U; r = 1U; }
    } else {
        g_t2 = 0U;
        g_tm2 = 0U;
    }
    return r;
}
void kinds(U8 d)
{
    U8 g_o = 0U;
    g_o = d;
    g_buf[1] = 5U;
#if 0
    g_x = 1U;
#endif
    g_reg = 1U;
    g_f = 2.0f;
    g_u = g_reg;
    g_misc = (U8)(d + 1U);
}
void ign(U8 d)
{
    g_misc = d;
    IGNORE(g_y = 1U);
}
void branchy(void)
{
    if (g_in > 3U) { g_w = 1U; } else { g_w = 2U; }
}
void opaque(U8 d)
{
    g_misc = d;
    ext_unknown();
}
void buz_stop(void) { s_buz = B_TWO; }
void buzzer(void)
{
    g_misc = (U8)s_buz;
    switch (s_buz) {
    case B_STOP: buz_stop(); break;
    case B_TWO: buz_stop(); break;
    case B_THREE: buz_stop(); break;
    default: s_buz = B_STOP; g_late = 7U; break;
    }
    g_buz_out = (U8)s_buz;
}
void buz3(void)
{
    g_misc = (U8)((U8)s_sa + (U8)s_sb);
    switch (s_sa) {
    case B_STOP: buz_stop(); break;
    case B_TWO: buz_stop(); break;
    case B_THREE: buz_stop(); break;
    default:
        if (s_sb < B_TWO) { g_q = 1U; } else { g_q = 2U; }
        break;
    }
}
U8 cond_w(U8 d)
{
    if (d > 3U) { g_w = 1U; }
    return d;
}
void nested(U8 d)
{
    if (d > 1U) { U8 t; t = d; g_t2 = t; }
}
void stw(U8 d)
{
    g_st.a = d;
}
void pw(U8 *p)
{
    *p = 1U;
}
void gapf(void)
{
    g_misc = (U8)s_gap;
    switch (s_gap) {
    case M1: g_q = 1U; break;
    case M5: g_q = 5U; break;
    case M9: g_q = 9U; break;
    default: g_q = 77U; break;
    }
}
void bigf(void)
{
    g_misc = (U8)s_big;
    switch (s_big) {
    case E1: g_q = 1U; break; case E2: g_q = 2U; break; case E3: g_q = 3U; break; case E4: g_q = 4U; break;
    case E5: g_q = 5U; break; case E6: g_q = 6U; break; case E7: g_q = 7U; break; case E8: g_q = 8U; break;
    case E9: g_q = 9U; break; case E10: g_q = 10U; break; case E11: g_q = 11U; break; case E12: g_q = 12U; break;
    case E13: g_q = 13U; break;
    default: if (g_k > 5U) { g_q = 200U; } break;
    }
}
void mixf(void)
{
    if (g_lvl2 > 6U) { g_q = 1U; } else { g_q = 0U; }
    switch (s_mode2) {
    case B_STOP: g_late = 1U; break;
    case B_TWO: g_late = 2U; break;
    case B_THREE: g_late = 3U; break;
    default: g_late = 9U; break;
    }
}
U8 g_lv;
static Buz_t s_md;
void both(void)
{
    if ((U8)(g_lv * 2U) > 13U) { g_q = 1U; } else { g_q = 0U; }
    switch (s_md) {
    case B_STOP: g_late = 1U; break;
    case B_TWO: g_late = 2U; break;
    case B_THREE: g_late = 3U; break;
    default: if ((U8)(g_lv + 3U) > 12U) { g_late = 9U; } else { g_late = 8U; } break;
    }
}
static Buz_t s_arr[3];
void elem(void)
{
    switch (s_arr[1]) {
    case B_STOP: g_q = 1U; break;
    case B_TWO: g_q = 2U; break;
    case B_THREE: g_q = 3U; break;
    default: if (g_k == 7U) { g_q = 9U; } else { g_q = 8U; } break;
    }
}
void shad(Buz_t g_misc)
{
    if (g_misc == B_TWO) { g_q = 2U; }
}
void pf(Buz_t m, U8 k)
{
    switch (m) {
    case B_STOP: g_q = 1U; break;
    case B_TWO: g_q = 2U; break;
    case B_THREE: g_q = 3U; break;
    default: if (k > 5U) { g_q = 77U; } break;
    }
}
void stopper(void) { buz_stop(); }
U8 g_aa;
U8 g_zz;
void ord2(U8 d)
{
    g_zz = 1U;
    if (d > 200U) { g_aa = 2U; }
}
"""
TYPES = {"g_tm2": "U16", "g_t": "U8", "d": "U8", "g_misc": "U8", "g_k": "U8"}


def _unit(name, inputs, outputs, **kw):
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    unit = {"name": name, "fid": "F_" + name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": list(inputs),
            "output_vars": list(outputs), "param_types": {"d": "U8"}}
    unit.update(kw)
    return unit


def _ext(monkeypatch, name, inputs, outputs):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit(name, inputs, outputs)
    return unit, extended_unit_sequences(unit)


def _derived(seq, var):
    ev = (seq.get("expected_evidence") or {}).get(var) or {}
    return seq["expected"].get(var) if ev.get("status") == "derived" else None


# ── the oracle: what a run wrote ─────────────────────────────────────────────────────────────────────────────────────

def test_a_run_reports_the_program_objects_it_wrote():
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    got = evaluate_outputs(unit, [{"d": 0, "g_tm2": 61}, {"d": 1, "g_tm2": 5}, {"d": 0, "g_tm2": 61}],
                           [["return"]] * 3, written=True)
    # the local ``r`` is no program object; ``g_tm2`` is written on the else path only
    assert got[0]["written"] == {"g_t2": True}
    assert got[1]["written"] == {"g_t2": True, "g_tm2": True}
    plain = evaluate_outputs(unit, [{"d": 0, "g_tm2": 61}], [["return"]])
    assert "written" not in plain[0]


def test_a_value_the_paths_disagree_on_is_not_known():
    # ``g_in`` is not an input: the run forks, each path writes ``g_w`` — written, but no one value
    got = evaluate_outputs(_unit("branchy", [], ["g_w"]), [{}], [["g_w"]], written=True)
    assert got[0]["written"] == {"g_w": False}


def test_the_evidence_carries_the_written_objects_only_when_asked():
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    seqs = [{"seq_num": 1, "inputs": {"d": 1, "g_tm2": 5}, "expected": {}}]
    a = apply_sequence_evidence(unit, [dict(s) for s in seqs], written=True)
    b = apply_sequence_evidence(unit, [dict(s) for s in seqs])
    assert a[0]["source_written"] == {"g_t2": True, "g_tm2": True}
    assert "source_written" not in b[0]
    a[0].pop("source_written")
    assert a == b                       # nothing else changes
    # a later run without the record drops an earlier one (no stale record)
    again = apply_sequence_evidence(unit, [{**seqs[0], "source_written": {"g_x": True}}])
    assert "source_written" not in again[0]


# ── the extended profile: the columns ─────────────────────────────────────────────────────────────────────────────────

def test_the_objects_the_function_writes_become_expected_columns(monkeypatch):
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    rec = unit["source_written_outputs"]
    assert set(rec["added"]) == {"g_t2", "g_tm2"} and rec["rounds"] == 1
    assert unit["design_output_vars"] == ["g_t", "return"]
    assert unit["output_vars"][:2] == ["g_t", "return"] and set(unit["output_vars"][2:]) == {"g_t2", "g_tm2"}
    # the values a fault in a write changes: the timer turned off after the limit, the counter cleared
    assert any(s["inputs"].get("d") == 0 and s["inputs"].get("g_tm2", 0) > 60 and _derived(s, "g_t2") == 0 for s in seqs)
    assert any(s["inputs"].get("d", 0) not in (0, None) and 0 < s["inputs"].get("g_tm2", 0) <= 65535
               and _derived(s, "g_tm2") == 0 for s in seqs)


def test_only_settable_written_objects_with_a_value_are_added(monkeypatch):
    unit, _seqs = _ext(monkeypatch, "kinds", ["d"], ["g_misc"])
    rec = unit["source_written_outputs"]
    # the element is; the shadowing local, the `#if 0` arm, the volatile register and the float are not
    assert set(rec["added"]) == {"g_buf[1]"}
    assert not {"g_o", "g_x", "g_reg", "g_f"} & set(unit["output_vars"])
    # written with a value no run knows (a volatile read): counted, not added
    assert rec["never_known"] == ["g_u"]
    # the round that added the column made the rows again: they state it
    assert all(_derived(s, "g_buf[1]") == 5 for s in _seqs if 0 <= s["inputs"].get("d", -1) <= 255)


def test_a_write_in_a_discarded_macro_argument_is_no_write(monkeypatch):
    unit, _seqs = _ext(monkeypatch, "ign", ["d"], ["g_misc"])
    assert "g_y" not in unit["output_vars"] and not unit["source_written_outputs"]["added"]


def test_the_output_columns_cap_holds(monkeypatch):
    monkeypatch.setattr(suts, "_OUTPUT_COL_END", suts._OUTPUT_COL_START + 1)   # two columns: both taken
    unit, _seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    rec = unit["source_written_outputs"]
    assert not rec["added"] and set(rec["not_added"].values()) == {"output_columns_full"}
    assert unit["output_vars"] == ["g_t", "return"]
    assert summarize_source_written_outputs([unit])["units_output_columns_full"] == 1


def test_one_free_column_takes_the_most_derived_name(monkeypatch):
    monkeypatch.setattr(suts, "_OUTPUT_COL_END", suts._OUTPUT_COL_START + 2)   # one free column
    unit, _seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    rec = unit["source_written_outputs"]
    assert list(rec["added"]) == ["g_t2"] and rec["not_added"] == {"g_tm2": "output_columns_full"}


def test_one_free_column_goes_to_the_name_more_rows_derive(monkeypatch):
    # ``g_zz`` is written on every row, ``g_aa`` only above 200 — by name ``g_aa`` would come first
    monkeypatch.setattr(suts, "_OUTPUT_COL_END", suts._OUTPUT_COL_START + 1)   # one free column after ``g_misc``
    unit, _seqs = _ext(monkeypatch, "ord2", ["d"], ["g_misc"])
    rec = unit["source_written_outputs"]
    assert list(rec["added"]) == ["g_zz"] and rec["not_added"] == {"g_aa": "output_columns_full"}


def test_a_unit_without_inputs_or_outputs_gets_no_columns_but_a_finding(monkeypatch):
    unit, seqs = _ext(monkeypatch, "kinds", [], [])
    rec = unit["source_written_outputs"]
    assert not rec["added"] and rec["not_added"].get("g_buf[1]") == "unit_without_inputs_or_outputs"
    assert unit["output_vars"] == []
    assert "g_buf[1]" in output_list_gaps(unit, seqs)
    assert summarize_source_written_outputs([unit])["not_added"].get("unit_without_inputs_or_outputs", 0) >= 1


def test_the_round_cap_leaves_the_names_to_the_last_pass(monkeypatch):
    monkeypatch.setattr(suts, "_SOURCE_READ_ROUNDS", 0)
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    rec = unit["source_written_outputs"]
    assert rec["round_cap_reached"] is True
    assert {n: a["round"] for n, a in rec["added"].items()} == {"g_t2": "final", "g_tm2": "final"}
    assert any(_derived(s, "g_t2") == 0 for s in seqs)
    assert summarize_source_written_outputs([unit])["units_round_cap_reached"] == 1


def test_an_error_after_a_round_stops_the_output_axis_only(monkeypatch):
    # (review R80 I2) the columns the first round added stay (the rows were made with them), the inputs go on, the last
    #   pass does not run
    real = suts._add_written_outputs
    calls = []

    def second_fails(*a, **k):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("probe")
        return real(*a, **k)
    monkeypatch.setattr(suts, "_add_written_outputs", second_fails)
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    rec = unit["source_written_outputs"]
    assert len(calls) == 2 and rec["error"] == "RuntimeError" and set(rec["added"]) == {"g_t2", "g_tm2"}
    assert "error" not in unit["source_read_inputs"] and "g_t" in unit["source_read_inputs"]["added"]
    assert any(_derived(s, "g_t2") == 0 for s in seqs)


def test_an_error_in_the_rounds_keeps_the_design_lists(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("probe")
    monkeypatch.setattr(suts, "_add_written_outputs", boom)
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    # the input round that follows (``g_t``) does not try the output axis again
    assert len(calls) == 1 and unit["source_read_inputs"]["rounds"] >= 1
    assert unit["output_vars"] == ["g_t", "return"] and "design_output_vars" not in unit
    assert unit["source_written_outputs"]["error"] == "RuntimeError" and seqs
    assert summarize_source_written_outputs([unit])["errors"] == 1
    # the input completion did not stop (review R80 I2)
    assert "error" not in unit["source_read_inputs"] and "g_t" in unit["source_read_inputs"]["added"]


def test_an_error_in_the_r19_rounds_restores_both_lists(monkeypatch):
    # the R19 part fails after round 1 added the output columns: the unit falls back to both design lists
    def boom(*a, **k):
        raise RuntimeError("probe")
    monkeypatch.setattr(suts, "scope_input_types", boom)
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    assert unit["output_vars"] == ["g_t", "return"] and "design_output_vars" not in unit
    assert unit["input_vars"] == ["d", "g_tm2"] and unit["source_read_inputs"]["error"] == "RuntimeError"
    assert unit["source_written_outputs"]["error"] == "RuntimeError" and seqs


def test_an_error_in_the_last_pass_takes_back_its_columns(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("probe")
    monkeypatch.setattr(suts, "_drop_underived_written_outputs", boom)
    unit, seqs = _ext(monkeypatch, "buzzer", [], ["g_misc"])
    rec = unit["source_written_outputs"]
    assert rec["final_error"] == "RuntimeError" and not rec["added"] and "final_initial_not_in_inputs" not in rec
    assert unit["output_vars"] == ["g_misc"] and "design_output_vars" not in unit
    assert not any("g_buz_out" in s["expected"] or "g_buz_out" in (s.get("expected_evidence") or {}) for s in seqs)
    # (R82) `g_buz_out` stays an input (a write's prior value) — the description's expected line no longer states it
    assert not any("g_buz_out=" in ln for s in seqs for ln in s["description"].splitlines() if ln.startswith("Expected:"))


def test_an_added_name_no_row_derives_is_dropped_with_its_cells():
    unit = {"output_vars": ["g_o", "g_a", "g_b"], "design_output_vars": ["g_o"],
            "source_written_outputs": {"added": {"g_a": {"round": 1}, "g_b": {"round": 1}}, "not_added": {},
                                       "dropped": {}},
            "source_read_inputs": {"added": {"g_b": {"read_on_model": False}, "g_c": {}}}}
    unit["output_vars"].append("g_c")
    unit["source_written_outputs"]["added"]["g_c"] = {"round": 1}
    seqs = [{"seq_num": 1, "expected": {"g_o": 1, "g_a": 2, "g_b": "[검증 필요] x"},
             "expected_evidence": {"g_o": {"status": "derived"}, "g_a": {"status": "derived"},
                                   "g_b": {"status": "unknown"}},
             "description": "row\nExpected: g_o=1, g_a=2, g_b=[검증 필요] x\n근거: 소스 계산 (요구 적합성 미검증, 실행 미실시)"}]
    _drop_underived_written_outputs(unit, seqs)
    rec = unit["source_written_outputs"]
    assert list(rec["added"]) == ["g_a"] and rec["dropped"]["g_b"]["input_kept"] is True
    assert rec["dropped"]["g_c"]["input_kept"] is False   # an input added without that mark was read
    assert unit["output_vars"] == ["g_o", "g_a"]
    assert seqs[0]["expected"] == {"g_o": 1, "g_a": 2} and "g_b" not in seqs[0]["expected_evidence"]
    assert seqs[0]["description"].splitlines() == ["row", "Expected: g_o=1, g_a=2",
                                                   "근거: 소스 계산 (요구 적합성 미검증, 실행 미실시)"]
    assert summarize_source_written_outputs([unit])["inputs_kept_for_dropped"] == 1


# ── enum values outside the enumerators (second search) + the late rows' writes ──────────────────────────────────────

def test_the_default_branch_is_reached_with_a_value_no_enumerator_names(monkeypatch):
    unit, seqs = _ext(monkeypatch, "buzzer", [], ["g_misc"])
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_inputs"] == 1 and sc["outside_design_enum_rows"] == 1
    # the enum search's own counters: the targets it searched (the default's statements) and reached
    assert sc["outside_design_enum_searched"] >= 1 and sc["outside_design_enum_reached"] >= 1
    assert sc["outside_design_enum_runs"] > 0 and not sc.get("outside_design_runs")   # no design-range search ran
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert len(fi) == 1 and fi[0]["inputs"]["s_buz"] in (0, 4)
    assert fi[0]["scenario"]["outside_design"] == {"s_buz": fi[0]["inputs"]["s_buz"]}
    assert "열거자 1~3 밖" in fi[0]["description"]
    assert suts.resolve_seq_test_method(fi[0]["strategy"]) == "FI"
    # only that row knows the stored value: the last pass adds the columns, the row states them
    rec = unit["source_written_outputs"]
    assert {n for n, a in rec["added"].items() if a["round"] == "final"} == {"g_buz_out", "s_buz", "g_late"}
    assert _derived(fi[0], "g_buz_out") == 1 and _derived(fi[0], "s_buz") == 1 and _derived(fi[0], "g_late") == 7
    assert summarize_source_written_outputs([unit])["names_added_final"] == 3
    # (review R80 W7) the other rows say why — no blank cell; ``g_late`` is written in the default only: its other paths
    #   need an initial value no round can add — counted there, not as a source-read name left over
    others = [s for s in seqs if s is not fi[0]]
    assert all(str(s["expected"].get("g_buz_out", "")).startswith("[검증 필요]") for s in others)
    assert all(str(s["expected"].get("g_late", "")).startswith("[검증 필요]") for s in others)
    assert rec["final_initial_not_in_inputs"] == ["g_late"]
    assert "g_late" not in unit["source_read_inputs"]["remaining"]
    assert summarize_source_written_outputs([unit])["names_final_initial_not_in_inputs"] == 1


def test_thirteen_enumerators_keep_the_values_around_them_under_the_pool_cap(monkeypatch):
    # (review R80 W-R2-1) the pool cap (12) kept the home values and cut 0 and 14
    unit, seqs = _ext(monkeypatch, "bigf", ["g_k"], ["g_misc"])
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi and all(s["inputs"]["s_big"] in (0, 14) for s in fi)
    assert unit["scenario_rows"]["outside_design_enum_rows"] >= 1   # the enum search's own rows


def test_a_gap_between_enumerators_is_no_home_value(monkeypatch):
    # (review R80 W-R2-3) enumerators 1 · 5 · 9: the default needs a non-enumerator — outside them (0 or 10) is FI; a
    #   value in a gap (2) would have been an in-range scenario
    unit, seqs = _ext(monkeypatch, "gapf", [], ["g_misc"])
    rows = [s for s in seqs if s["strategy"].startswith(("SCN_", SCENARIO_FI_PREFIX))]
    assert not any(s["inputs"].get("s_gap") not in (1, 5, 9) for s in rows if s["strategy"].startswith("SCN_"))
    fi = [s for s in rows if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi and fi[0]["inputs"]["s_gap"] in (0, 10) and _derived(fi[0], "g_q") == 77


def test_an_enum_parameter_is_widened_too(monkeypatch):
    # (review R80 W-R2-2) the type of a parameter comes from the function's declaration
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("pf", ["m", "k"], ["g_q"], param_types={"m": "Buz_t", "k": "U8"},
                 value_domains={"m": {"values": [1, 2, 3], "source": "enum_table"}})
    assert _enum_outside_values(unit, "m", [1, 2, 3]) == [0, 1, 2, 3, 4]
    seqs = extended_unit_sequences(unit)
    reach = [s for s in seqs if s["inputs"].get("m") in (0, 4) and (s["inputs"].get("k") or 0) > 5]
    assert reach and any(_derived(s, "g_q") == 77 for s in reach)


def test_the_enum_search_is_counted_once_it_ran(monkeypatch):
    # (review R80 I-R2-9) a second search that raised did not search
    real = suts.find_scenarios

    def second_fails(unit, domains, outputs, existing=None, **kw):
        if kw.get("expose") is False:
            raise RuntimeError("probe")
        return real(unit, domains, outputs, existing, **kw)
    monkeypatch.setattr(suts, "find_scenarios", second_fails)
    unit, _seqs = _ext(monkeypatch, "buzzer", [], ["g_misc"])
    sc = unit["scenario_rows"]
    # (the buzzer has no design-range input: the only search with expose=False is the enum search)
    assert sc["outside_design_enum_error"] == "RuntimeError" and not sc.get("outside_design_enum_searched")


def test_the_enum_widening_stays_inside_the_declared_type():
    unit = _unit("buzzer", [], ["g_misc"])
    assert _enum_outside_values(unit, "s_buz", [1, 2, 3]) == [0, 1, 2, 3, 4]
    # the underlying type's ends are the enumerators: nothing outside
    assert _enum_outside_values(unit, "s_lim", [-32768, 32767]) == []
    # (review R80 W-R2-2) a value set over an integer type (``#define`` states): ±1 inside its type
    assert _enum_outside_values(unit, "g_misc", [0, 1]) == [0, 1, 2]
    assert _enum_outside_values(unit, "nowhere", [0, 1]) == []
    # (review R80 W4) an enum input holds 0 ~ 127 for the oracle (C11 6.7.2.2p4): from 0, only the upper side
    assert _enum_outside_values(unit, "s_z", [0, 1, 2]) == [0, 1, 2, 3]
    assert _enum_outside_values(unit, "s_z", [0, 127]) == []


def test_a_widened_enum_the_target_does_not_need_goes_back_to_an_enumerator(monkeypatch):
    # (review R80 W3) the default needs ``s_sa`` outside its enumerators; the branch inside reads ``s_sb`` — an enumerator
    #   reaches it, so ``s_sb`` stays one
    unit, seqs = _ext(monkeypatch, "buz3", [], ["g_misc"])
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi and all(set(s["scenario"]["outside_design"]) == {"s_sa"} for s in fi)
    assert all(s["inputs"]["s_sb"] in (1, 2, 3) for s in fi)


def test_an_enum_the_design_ranges_is_widened_to_its_enumerators_and_around():
    # (R80 measurement) HDPDM01 ``s_BuzzerState`` takes the SwUDS range 0x01~0x03: a design range does not change what
    #   FI is — the unit's other enumerators (outside the design) and the enumerators' range ±1
    enum = suts._ENUM_TYPE
    unit = _unit("buzzer", [], ["g_misc"])
    assert _outside_enumerator_domains(unit, {"s_buz": [1, 2, 3]}, {"s_buz": enum}) == {"s_buz": [0, 1, 2, 3, 4]}
    for source in ("uds_range", "hsis_range", "uds_values"):
        unit["bounds_source"] = {"s_buz": source}
        assert _outside_enumerator_domains(unit, {"s_buz": [1, 2, 3]}, {"s_buz": enum}) == {"s_buz": [0, 1, 2, 3, 4]}
    # the design keeps one enumerator: the others are outside the design
    unit["value_domains"] = {"s_buz": {"values": [1, 2, 3]}}
    assert _outside_enumerator_domains(unit, {"s_buz": [2]}, {"s_buz": enum}) == {"s_buz": [0, 1, 2, 3, 4]}
    assert _outside_enumerator_domains(unit, {"s_buz": (1, 3)}, {"s_buz": enum}) == {}              # a range
    assert _outside_enumerator_domains(unit, {"s_buz": [1, 2, 3]}, {"s_buz": "uint8_t"}) == {}     # not a value set
    # not widened: why (review R80 W-R2-2)
    why = {}
    assert _outside_enumerator_domains(unit, {"s_lim": [-32768, 32767], "nowhere": [1, 2]},
                                       {"s_lim": enum, "nowhere": enum}, why) == {}
    assert why == {"s_lim": "nothing_to_widen", "nowhere": "type_unresolved"}


def test_a_design_ranged_enum_reaches_its_default_in_the_document(monkeypatch):
    # the HDPDM01 shape: the design gives the state's range — the FI row reaches the default and states the stored value
    unit = _unit("buzzer", [], ["g_misc"], uds_param_info={"s_buz": {"range": [1, 3]}})
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    seqs = extended_unit_sequences(unit)
    assert unit["bounds_source"]["s_buz"] == "uds_range"
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi and fi[0]["inputs"]["s_buz"] in (0, 4) and _derived(fi[0], "g_buz_out") == 1
    assert "설계 1~3 밖" in fi[0]["description"] and "열거자 1~3 밖" not in fi[0]["description"]


# ── findings (both profiles) ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_reference_profile_finds_the_gaps_without_new_columns(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    seqs = generate_sequences(unit, 10)
    assert unit["output_vars"] == ["g_t", "return"]
    gaps = output_list_gaps(unit, seqs)
    assert set(gaps) == {"g_t2", "g_tm2"} and not any(g["added"] for g in gaps.values())
    assert listed_outputs_not_written(unit, seqs) == (["g_t"], "")
    assert set(source_written_names(seqs)) == {"g_t2", "g_tm2"}


def test_the_extended_profile_reports_the_gap_against_the_design_list(monkeypatch):
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    gaps = output_list_gaps(unit, seqs)
    assert set(gaps) == {"g_t2", "g_tm2"} and all(g["added"] for g in gaps.values())
    assert listed_outputs_not_written(unit, seqs) == (["g_t"], "")


def test_listed_not_written_is_not_judged_past_unknown_code(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("opaque", ["d"], ["g_t"])
    seqs = generate_sequences(unit, 10)
    assert listed_outputs_not_written(unit, seqs) == ([], "unknown_callees")
    unit = _unit("pw", [], ["g_t"])
    assert listed_outputs_not_written(unit, generate_sequences(unit, 10)) == ([], "pointer_write")


def test_a_block_local_or_a_struct_member_write_does_not_stop_the_judgment(monkeypatch):
    # (review R80 W5) the closure counts the block-scope ``t``; ``g_st`` is a struct object
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    for name in ("nested", "stw"):
        unit = _unit(name, ["d"], ["g_t"])
        assert listed_outputs_not_written(unit, generate_sequences(unit, 10)) == (["g_t"], ""), name


def test_a_write_to_a_name_neither_object_nor_local_is_not_judged(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    seqs = generate_sequences(unit, 10)
    scope = dict(unit["project_scope"])
    functions = dict(scope["effects"]["functions"])
    functions["tmout2"] = {**functions["tmout2"], "writes": sorted(functions["tmout2"]["writes"]) + ["zz"]}
    scope["effects"] = {**scope["effects"], "functions": functions}
    unit["project_scope"] = scope
    assert listed_outputs_not_written(unit, seqs) == ([], "writes_unmodeled_name")


def test_a_listed_container_covers_its_written_parts(monkeypatch):
    # (review R80 W6) the design lists the struct / the unexpanded array; the run writes a member / an element
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("stw", ["d"], ["g_st"])
    seqs = generate_sequences(unit, 10)
    assert "g_st.a" in source_written_names(seqs) and "g_st.a" not in output_list_gaps(unit, seqs)
    unit = _unit("kinds", ["d"], ["g_misc", "g_buf"])
    seqs = generate_sequences(unit, 10)
    assert "g_buf[1]" not in output_list_gaps(unit, seqs)


def test_volatile_and_float_writes_are_findings_not_columns(monkeypatch):
    # (review R80 I8) no expected value, but a write the design table omits
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("kinds", ["d"], ["g_misc"])
    gaps = output_list_gaps(unit, generate_sequences(unit, 10))
    assert gaps["g_reg"]["settable"] is False and gaps["g_buf[1]"]["settable"] is True


def test_an_output_only_a_callee_writes_is_no_unwritten_listing(monkeypatch):
    # the unit test stubs ``buz_stop`` — no row writes ``s_buz`` — but the function's write closure does
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("stopper", [], ["s_buz"])
    seqs = generate_sequences(unit, 10)
    assert "s_buz" not in source_written_names(seqs)
    assert listed_outputs_not_written(unit, seqs) == ([], "")


def test_a_name_rows_state_through_r21_is_no_design_output():
    unit = {"output_vars": ["g_t", "g_t2"], "row_io_columns": {"outputs_shown": ["g_t2"]},
            "project_scope": _unit("tmout2", [], [])["project_scope"]}
    seqs = [{"seq_num": 1, "source_written": {"g_t2": True}}]
    assert set(output_list_gaps(unit, seqs)) == {"g_t2"}


def test_the_findings_sheet_rows(monkeypatch):
    unit, seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    found = sf.collect_output_gap_findings([unit], {unit["fid"]: output_list_gaps(unit, seqs)},
                                           {unit["fid"]: listed_outputs_not_written(unit, seqs)[0]}, {unit["fid"]: "TC_1"})
    kinds = {f["kind"]: f for f in found}
    assert set(kinds) == {sf.OUTPUT_GAP_KIND, sf.LISTED_UNWRITTEN_KIND}
    assert set(kinds[sf.OUTPUT_GAP_KIND]["observables"]) == {"g_t2", "g_tm2"}
    assert kinds[sf.LISTED_UNWRITTEN_KIND]["observables"] == ["g_t"]
    assert kinds[sf.OUTPUT_GAP_KIND]["example_tc"] == "TC_1"
    summary = sf.summarize_output_gaps(found, {"F_x": "unknown_callees", "F_y": "unknown_callees"}, 3)
    assert summary == {"functions": 1, "names": 2, "rows": kinds[sf.OUTPUT_GAP_KIND]["occurrences"],
                       "listed_not_written_functions": 1, "listed_not_written_names": 1,
                       "listed_not_written_undecided": 2,
                       "listed_not_written_undecided_reasons": {"unknown_callees": 2}, "rows_written_error": 3}
    import openpyxl
    wb = openpyxl.Workbook()
    assert sf.write_source_findings_sheet(wb, found) == 2
    rows = list(wb[sf.FINDINGS_SHEET].iter_rows(min_row=2, values_only=True))
    assert {r[2] for r in rows} == {sf.OUTPUT_GAP_KIND, sf.LISTED_UNWRITTEN_KIND}
    assert all(r[12] == sf.OUTPUT_GAP_REPRODUCTION for r in rows)


# ── summaries and disclosures ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_disclosures_say_what_was_added_and_found():
    qr = {"source_written_outputs": {"units": 3, "units_with_added": 2, "names_added": 5, "names_added_final": 1,
                                     "names_dropped_underived": 1, "inputs_kept_for_dropped": 1, "names_never_known": 2,
                                     "not_added": {"float_object": 1}, "units_output_columns_full": 0,
                                     "max_rounds": 2, "units_round_cap_reached": 0, "errors": 0},
          "source_findings": {"findings": 0, "by_kind": {}, "functions": 0, "sequences": 0,
                              "output_list_gaps": {"functions": 2, "names": 3, "rows": 9,
                                                   "listed_not_written_functions": 1, "listed_not_written_names": 2,
                                                   "listed_not_written_undecided": 1,
                                                   "listed_not_written_undecided_reasons": {"pointer_write": 1}}},
          "scenario_rows": {"targets": 4, "outside_design_enum_inputs": 1, "outside_design_enum_rows": 1}}
    items = {i["key"]: i for i in build_disclosures("suts", qr)}
    sw = items["suts_source_written_outputs"]
    assert sw["value"] == "unit 2/3 · 이름 5" and sw["tone"] == "info"
    assert "다시 뺀 이름 1" in sw["note"] and "더한 입력이 남은 것 1" in sw["note"] and "float_object 1" in sw["note"]
    og = items["suts_output_list_gaps"]
    assert og["value"] == "함수 2 · 객체 3 · 쓰지 않는 설계 출력 함수 1 · 객체 2 · 판정하지 않은 함수 1"
    assert og["tone"] == "warning" and "listed_output_not_written" in og["note"] and "pointer_write 1" in og["note"]
    assert "값 목록 입력(enum · `#define` 상태값) 1" in items["suts_scenario_rows"]["note"]
    assert "FI 행 1" in items["suts_scenario_rows"]["note"]
    warn = build_disclosures("suts", {"source_written_outputs": {**qr["source_written_outputs"], "errors": 1}})
    assert {i["key"]: i for i in warn}["suts_source_written_outputs"]["tone"] == "warning"


def test_generate_suts_reports_the_written_outputs_and_their_findings(tmp_path):
    (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 g_cnt;\nU8 Fn(U8 a)\n{\n    if (a > 1U) { g_cnt = 5U; }\n"
                                  "    return a;\n}\n", encoding="utf-8")
    ext = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "e.xlsm"), scope="source",
                             tc_profile="extended")["quality_report"]
    ref = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "r.xlsm"), scope="source")[
        "quality_report"]
    # (R86) the reference-scale document takes the extension's columns too — both report the written outputs
    assert ext["source_written_outputs"]["units"] >= 1 and ref["source_written_outputs"]["units"] >= 1
    assert "reference_columns" in ref and "reference_columns" not in ext
    for q in (ext, ref):
        gaps = q["source_findings"]["output_list_gaps"]
        assert set(gaps) == {"functions", "names", "rows", "listed_not_written_functions", "listed_not_written_names",
                             "listed_not_written_undecided", "listed_not_written_undecided_reasons",
                             "rows_written_error"}


def test_a_written_object_the_input_rule_refuses_is_no_candidate():
    # the run model may know a float's value; the columns take what the input rule takes (`_source_object_decl`)
    unit = _unit("kinds", ["d"], ["g_misc"])
    rows = [{"seq_num": 1, "source_written": {"g_f": True, "g_buf[1]": True, "g_reg": True}}]
    new, skipped = suts._written_output_candidates(unit, rows, suts._new_written_record())
    assert new == ["g_buf[1]"] and skipped == {"g_f": "float_object", "g_reg": "volatile_object"}


def test_a_design_without_outputs_keeps_its_reference_rows(monkeypatch):
    # (review R80 C1) the catalog structure comes from the design output list: the VOID_SIDE_EFFECT row of a unit whose
    #   design lists no output stays where the reference profile has it, after the source-written outputs are added
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    ref_unit = _unit("tmout2", ["d"], [], indirect_vars=["g_t"])
    ref = [s["strategy"] for s in generate_sequences(ref_unit, 10)]
    assert "VOID_SIDE_EFFECT" in ref
    unit_ext = _unit("tmout2", ["d"], [], indirect_vars=["g_t"])
    seqs = extended_unit_sequences(unit_ext)
    assert unit_ext["source_written_outputs"]["added"]       # outputs were added
    assert [s["strategy"] for s in seqs][:len(ref)] == ref


def test_the_ai_path_keeps_the_written_record(monkeypatch):
    # (review R80 W2) the AI enhancement re-derives the evidence — with the writes, as the first pass
    import workflow.ai as wai
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    monkeypatch.setattr(wai, "agent_call", lambda *a, **k: "[]", raising=False)
    unit = _unit("kinds", [], [])
    seqs = generate_sequences(unit, 10)
    assert any(s.get("source_written") for s in seqs)
    again = suts.enhance_sequences_with_ai(unit, seqs, {"provider": "stub"})
    assert any("g_buf[1]" in (s.get("source_written") or {}) for s in again)


def test_an_output_round_then_its_initial_value_round(monkeypatch):
    # (review R80 I1) round 1 adds the column only (``g_w`` written above 3); round 2 adds its initial value as an input
    #   for the rows that leave it unwritten (backlog 2-c) — then every row states it
    # (R82) the exposure search already named ``g_w`` in round 1: ``g_w = 1U`` replaces a value no row knew (a write's
    #   prior value) — the same input the initial-value round would add in round 2, now there one round earlier
    unit, seqs = _ext(monkeypatch, "cond_w", ["d"], ["return"])
    assert unit["source_written_outputs"]["rounds"] == 1 and list(unit["source_written_outputs"]["added"]) == ["g_w"]
    got = unit["source_read_inputs"]["added"]["g_w"]
    assert got["round"] == 1 and got["read_on_model"] is False and got["prior_value_for_write"] >= 1
    assert all(_derived(s, "g_w") is not None for s in seqs if "g_w" in s["inputs"] and 0 <= s["inputs"].get("d", -1) <= 255)


def test_a_failing_written_record_keeps_the_derived_values(monkeypatch):
    # (review R80 W1) a side record: its failure is counted and the run's values stand
    from generators import c_source_oracle as oracle

    def boom(interp, finals, *a, **k):   # (R81) `_written_objects` also takes the reasons dict
        raise RuntimeError("probe")
    monkeypatch.setattr(oracle, "_written_objects", boom)
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    got = evaluate_outputs(unit, [{"d": 0, "g_tm2": 61}], [["return"]], written=True)[0]
    assert got["status"] == "supported" and got["outputs"]["return"]["value"] == 1
    assert "written" not in got and got["written_error"] == "oracle_exception:RuntimeError"
    seqs = apply_sequence_evidence(unit, [{"seq_num": 1, "inputs": {"d": 0, "g_tm2": 61}, "expected": {}}], written=True)
    assert seqs[0]["source_written_error"] == "oracle_exception:RuntimeError" and "source_written" not in seqs[0]
    assert seqs[0]["expected"]["return"] == 1
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    extended_unit_sequences(unit)
    assert unit["source_written_outputs"]["rows_written_error"] > 0
    assert summarize_source_written_outputs([unit])["rows_written_error"] > 0


def test_the_output_gap_item_has_its_own_action():
    # (review R80 W8) a fact of the design table — not the default "missing input, regenerate" action
    from backend.services.issue_explainer import rule_action
    text = rule_action("disclosure:suts_output_list_gaps")
    assert text != rule_action("disclosure:sts_traced_system_boundary") and "재생성으로 사라지지 않는다" in text
    assert "SwUDS 출력 표" in text


def test_a_failed_written_record_reaches_the_findings_summary(monkeypatch):
    # (review R80 W-R2-4) both profiles: the rows whose writes are in no finding are counted
    from generators import c_source_oracle as oracle

    def boom(interp, finals, *a, **k):   # (R81) `_written_objects` also takes the reasons dict
        raise RuntimeError("probe")
    monkeypatch.setattr(oracle, "_written_objects", boom)
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("tmout2", ["d", "g_tm2"], ["g_t", "return"])
    seqs = generate_sequences(unit, 10)
    got = suts._summarize_source_findings([unit], {unit["fid"]: seqs})["output_list_gaps"]
    assert got["rows_written_error"] == len(seqs) > 0
    items = {i["key"]: i for i in build_disclosures("suts", {"source_findings": {"findings": 0, "output_list_gaps": got}})}
    assert items["suts_output_list_gaps"]["tone"] == "warning" and "기록이 실패한 행" in items["suts_output_list_gaps"]["note"]


def test_a_unit_with_nothing_to_judge_is_not_counted_undecided(monkeypatch):
    # (review R80 I-R2-4) a design listing only the return value is no undecided listing
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    for outputs, counted in ((["return"], 0), (["g_t"], 1)):
        unit = _unit("opaque", ["d"], outputs)
        seqs = generate_sequences(unit, 10)
        got = suts._summarize_source_findings([unit], {unit["fid"]: seqs})["output_list_gaps"]
        assert got["listed_not_written_undecided"] == counted, outputs


def test_the_containers_of_a_path_include_its_subscript_steps():
    # (review R80 I-R2-6)
    assert suts._containers("g.a[1].b") == ["g", "g.a", "g.a[1]"]
    assert suts._containers("g_buf[1]") == ["g_buf"]
    assert suts._containers("g_x") == []


def test_the_last_pass_after_an_axis_error_still_counts(monkeypatch):
    # (review R80 I-R2-8) no column is added after the error, but the rows' failed records are counted
    from generators import c_source_oracle as oracle

    def boom(*a, **k):
        raise RuntimeError("probe")
    monkeypatch.setattr(suts, "_add_written_outputs", boom)
    monkeypatch.setattr(oracle, "_written_objects", boom)
    unit, _seqs = _ext(monkeypatch, "tmout2", ["d", "g_tm2"], ["g_t", "return"])
    rec = unit["source_written_outputs"]
    assert rec["error"] == "RuntimeError" and rec["rows_written_error"] > 0 and not rec["added"]


def test_the_inv_labels_read_the_design_outputs(monkeypatch):
    # (review R80 I-R2-2 · C1) the BV_*_INV label's clamp/guard reading comes from the design outputs — an added output a
    #   clamp mentions does not change the reference row's label
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    flow = [{"text": "g_buf[1] = clamp(5)"}]
    ref = generate_sequences(_unit("kinds", ["d"], ["g_misc"], logic_flow=flow), 10)
    unit = _unit("kinds", ["d"], ["g_misc"], logic_flow=flow)
    ext = extended_unit_sequences(unit)
    assert "g_buf[1]" in unit["output_vars"]

    def label(seqs):
        return next(s["description"].splitlines()[0] for s in seqs if s["strategy"] == "BV_MIN_INV")
    assert label(ext) == label(ref) and "포화(saturation)" not in label(ext)


def test_a_list_over_the_pool_cap_is_counted():
    # (review R80 W-R2-1) a list domain cut to the pool size counts like a range's
    from generators import scenario_rows as sr
    unit = _unit("bigf", ["g_k"], ["g_misc"])
    rep = sr.find_scenarios(unit, {"s_big": list(range(1, 14))}, ["g_misc"])["report"]
    assert rep["pools_capped"] == 1
    rep = sr.find_scenarios(unit, {"s_big": list(range(1, 12))}, ["g_misc"])["report"]
    assert rep["pools_capped"] == 0


def test_the_enum_search_leaves_the_design_range_search_as_it_was(monkeypatch):
    # (R80 measurement r80c) enum values mixed into the design-range search moved where its climbs ended (HDPDM01
    #   `s_IsDoorStop` lost a row and a generated kill): the enum search is its own, after it — the design-range search's
    #   rows and counters are the same with or without enum widening; the enum search adds the default's FI row
    monkeypatch.setattr(suts, "_globals_type_cache", {**TYPES, "g_lvl2": "U8"})

    def run(widen):
        if not widen:
            monkeypatch.setattr(suts, "_outside_enumerator_domains", lambda *a, **k: {})
        unit = _unit("mixf", ["g_lvl2"], ["g_q"], uds_param_info={"g_lvl2": {"range": [0, 3]}})
        seqs = extended_unit_sequences(unit)
        return unit, seqs
    with_enum, seqs = run(True)
    without, seqs0 = run(False)
    keys = ("outside_design_searched", "outside_design_reached", "outside_design_rows", "outside_design_runs",
            "outside_design_steps", "outside_design_not_reached", "outside_design_in_range_rows")
    assert {k: with_enum["scenario_rows"].get(k) for k in keys} == {k: without["scenario_rows"].get(k) for k in keys}
    assert with_enum["scenario_rows"]["outside_design_runs"] > 0      # the design-range search ran in both
    design_rows = [s["inputs"] for s in seqs0 if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert [s["inputs"] for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)][:len(design_rows)] \
        == design_rows
    sc = with_enum["scenario_rows"]
    assert sc["outside_design_enum_rows"] == 1 and sc["outside_design_enum_runs"] > 0
    enum_fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)][len(design_rows):]
    assert len(enum_fi) == 1 and enum_fi[0]["inputs"]["s_mode2"] in (0, 4) and _derived(enum_fi[0], "g_late") == 9


def test_an_enum_search_error_keeps_the_design_range_rows(monkeypatch):
    # the enum search fails alone: its rows go, the design-range search's rows and the document stay
    monkeypatch.setattr(suts, "_globals_type_cache", {**TYPES, "g_lvl2": "U8"})
    real = suts.find_scenarios
    calls = []

    def third_fails(unit, domains, outputs, existing=None, **kw):
        if kw.get("expose") is False:
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("probe")
        return real(unit, domains, outputs, existing, **kw)
    monkeypatch.setattr(suts, "find_scenarios", third_fails)
    unit = _unit("mixf", ["g_lvl2"], ["g_q"], uds_param_info={"g_lvl2": {"range": [0, 3]}})
    seqs = extended_unit_sequences(unit)
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_error"] == "RuntimeError" and not sc.get("outside_design_error")
    assert sc["outside_design_runs"] > 0 and sc["outside_design_enum_rows"] == 0
    assert not any(s["strategy"].startswith(SCENARIO_FI_PREFIX) and s["inputs"].get("s_mode2") in (0, 4) for s in seqs)
    # (review R80 W-R4-1) the enum search failed alone: counted apart — the unit keeps the other searches' rows
    got = suts.summarize_scenario_rows([unit])
    assert got["enum_errors"] == 1 and got["errors"] == 0


def test_a_design_value_list_with_a_gap_leaves_the_enumerator_in_it_outside(monkeypatch):
    # (review R80 W-R3-1) the design keeps 1 and 3: the case of 2 is outside the design — FI, said so
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("buzzer", [], ["g_misc"], uds_param_info={"s_buz": {"values": [1, 3]}})
    seqs = extended_unit_sequences(unit)
    assert unit["bounds_source"]["s_buz"] == "uds_values"
    two = [s for s in seqs if s["strategy"].startswith(("SCN_", SCENARIO_FI_PREFIX)) and s["inputs"].get("s_buz") == 2]
    assert two and all(s["strategy"].startswith(SCENARIO_FI_PREFIX) for s in two)
    assert "설계 값 1, 3 밖" in two[0]["description"]


def test_a_design_range_wider_than_the_enumerators_is_said_so(monkeypatch):
    # (review R80 W-R3-2) design 0 ~ 10, enumerators 1 ~ 3: 0 is inside the design and no enumerator
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("buzzer", [], ["g_misc"], uds_param_info={"s_buz": {"range": [0, 10]}})
    seqs = extended_unit_sequences(unit)
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi and fi[0]["inputs"]["s_buz"] in (0, 4)
    label = "열거자 1~3 밖 · 설계 0~10 안"
    assert label in fi[0]["description"] and "설계 1~3 밖" not in fi[0]["description"]


def test_the_values_around_a_design_kept_list_survive_the_pool(monkeypatch):
    # (review R80 W-R3-3) 13 enumerators, the design keeps 1 and 3: the ±1 (0 · 14) go first among the outside values
    unit = _unit("bigf", ["g_k"], ["g_misc"], uds_param_info={"s_big": {"values": [1, 3]}})
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    seqs = extended_unit_sequences(unit)
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert any(s["inputs"].get("s_big") in (0, 14) and _derived(s, "g_q") == 200 for s in fi)


def test_the_widening_reasons_and_other_domains():
    enum = suts._ENUM_TYPE
    unit = _unit("kinds", ["d"], ["g_misc"])
    why = {}
    # (review R80 I-R3-1) a float value set has no usable type — not "nothing to widen"
    assert _outside_enumerator_domains(unit, {"g_f": [1, 2]}, {"g_f": enum}, why) == {} and why == {"g_f": "type_unresolved"}
    # (I-R3-2) an element's / a pointer target's enum domain (a dict with the enumerators)
    homes = {}
    bunit = _unit("buzzer", [], ["g_misc"])
    ctype = bunit["project_scope"]["globals"]["s_buz"]["type"]
    # (review R80 I-R4-2) a design range overwrote ``values`` (as `_apply_design_range` does): every enumerator still
    #   comes from the enum type
    got = _outside_enumerator_domains(bunit, {"s_buz": {"values": [1, 2], "min": 1, "max": 2, "ctype": ctype}}, {},
                                      homes=homes)
    assert got == {"s_buz": [0, 1, 2, 3, 4]} and homes["s_buz"] == ([1, 2], [1, 2, 3])
    # (I-R4-3) an integer value list in a dict domain is no enum — counted as a design value list, not widened
    assert _outside_enumerator_domains(bunit, {"g_x": {"values": [0, 5], "min": 0, "max": 5,
                                                       "ctype": {"kind": "int", "bits": 16, "signed": True}}}, {}) == {}
    # (I-R4-1) a stub return's enum domain carries its type — widened by it, not "type unresolved"
    why = {}
    got = _outside_enumerator_domains(bunit, {"getb() return": {"values": [1, 2, 3], "min": 1, "max": 3, "ctype": ctype}},
                                      {}, why)
    assert got == {"getb() return": [0, 1, 2, 3, 4]} and why == {}
    # (I-R3-3) the generation's value sets (pointer targets) before the unit's value domains
    got = _outside_enumerator_domains(_unit("buzzer", [], ["g_misc"]), {"s_buz": [2]}, {"s_buz": enum},
                                      enum_sets={"s_buz": {"values": [1, 2, 3]}})
    assert got == {"s_buz": [0, 1, 2, 3, 4]}


def test_a_parameter_hides_the_global_of_its_name():
    # (review R80 I-R3-6) ``shad(Buz_t g_misc)``: the enum parameter, not the U8 global — 128 is no enum input value
    unit = _unit("shad", ["g_misc"], ["g_q"])
    assert _enum_outside_values(unit, "g_misc", [1, 127]) == [0, 1, 127]
    assert _enum_outside_values(_unit("kinds", ["d"], ["g_misc"]), "g_misc", [1, 127]) == [0, 1, 127, 128]


def _both(monkeypatch, widen=True):
    monkeypatch.setattr(suts, "_globals_type_cache", {**TYPES, "g_lv": "U8"})
    if not widen:
        monkeypatch.setattr(suts, "_outside_enumerator_domains", lambda *a, **k: {})
    unit = _unit("both", ["g_lv"], ["g_q"], uds_param_info={"g_lv": {"range": [0, 3]}})
    return unit, extended_unit_sequences(unit)


def test_both_searches_add_rows_and_the_design_range_one_is_unchanged(monkeypatch):
    # (review R80 I-R4-9) the design-range search adds FI rows here: the same with or without enum widening; the enum
    #   search adds its own after them; the names are unique; the headline counts all of them (W-R4-1)
    from report_gen.generation_disclosures import _scenario_rows_item
    with_enum, sa = _both(monkeypatch)
    monkeypatch.undo()
    without, sb = _both(monkeypatch, widen=False)
    design = [k for k in suts.SCENARIO_REPORT_KEYS if k.startswith("outside_design_") and "enum" not in k]
    assert {k: with_enum["scenario_rows"].get(k) for k in design} == {k: without["scenario_rows"].get(k) for k in design}
    fi_a = [(s["strategy"], s["inputs"]) for s in sa if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    fi_b = [(s["strategy"], s["inputs"]) for s in sb if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi_b and fi_a[:len(fi_b)] == fi_b and len(fi_a) > len(fi_b)
    assert len({name for name, _ in fi_a}) == len(fi_a)
    sc = with_enum["scenario_rows"]
    assert sc["outside_design_enum_rows"] == len(fi_a) - len(fi_b)
    assert sc["outside_design_enum_searched"] == sc["outside_design_enum_reached"] + sc["outside_design_enum_not_reached"]
    summary = suts.summarize_scenario_rows([with_enum])
    rows = sum(1 for s in sa if str(s["strategy"]).startswith(("SCN_", SCENARIO_FI_PREFIX)))
    assert _scenario_rows_item(summary)["value"].startswith(f"{rows}행(세 탐색)") and summary["units_with_rows"] == 1


def test_an_enum_search_error_after_its_rows_drops_them_and_its_counters(monkeypatch):
    # (review R80 I-R4-5 · I-R4-9) the failure comes after the enum search added a row: the row and every counter of
    #   that search go; the design-range rows stay
    real = suts._scenario_row

    def late_fail(sequences, row, strategy, outputs, var_types, outside, span, enums=None):
        real(sequences, row, strategy, outputs, var_types, outside, span, enums)
        if enums:
            raise RuntimeError("probe")
    monkeypatch.setattr(suts, "_scenario_row", late_fail)
    unit, seqs = _both(monkeypatch)
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_error"] == "RuntimeError" and sc["outside_design_rows"] >= 1
    assert all(sc[k] == 0 for k in suts._ENUM_SEARCH_KEYS) and sc["outside_design_enum_budget_exhausted"] is False
    assert sc["outside_design_enum_status"] == ""
    assert not any(s["inputs"].get("s_md") in (0, 4) for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX))


def test_the_enum_search_counts_its_caps(monkeypatch):
    # (review R80 W-R4-2) the list caps cut in this search — recorded as its own
    unit, _seqs = _ext(monkeypatch, "bigf", ["g_k"], ["g_misc"])
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_pools_capped"] >= 1 and sc["outside_design_enum_status"] == "searched"
    assert sc["outside_design_pools_capped"] == 0   # no design-range search ran


def test_a_design_that_keeps_one_enumerator_is_searched_around_it(monkeypatch):
    # (review R80 I-R4-7) the design range keeps only 2 (B_TWO): no first-search domain — the enum search's home is 2
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("buzzer", [], ["g_misc"], uds_param_info={"s_buz": {"range": [2, 2]}})
    seqs = extended_unit_sequences(unit)
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_single_value"] == 1
    fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX)]
    assert fi and all(s["inputs"]["s_buz"] != 2 for s in fi) and "설계 2~2 밖" in fi[0]["description"]


def test_the_enum_row_says_only_value_sets_were_widened(monkeypatch):
    # (review R80 W-R5-1) the enum search leaves the design-range input inside its design range — the row says so
    _unit_, seqs = _both(monkeypatch)
    enum_fi = [s for s in seqs if s["strategy"].startswith(SCENARIO_FI_PREFIX) and s["inputs"].get("s_md") in (0, 4)]
    assert enum_fi and all(0 <= s["inputs"]["g_lv"] <= 3 for s in enum_fi)
    head = enum_fi[0]["description"].splitlines()[0]
    assert "선언 타입 범위로 넓혀" not in head and "설계 범위 입력은 설계 범위 안에서만" in head


def test_a_unit_only_the_enum_search_searched_is_not_reported_unsearched(monkeypatch):
    # (review R80 I-R5-2) the one-value design leaves the first search no input: the enum search ran and added rows
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("buzzer", [], ["g_misc"], uds_param_info={"s_buz": {"range": [2, 2]}})
    extended_unit_sequences(unit)
    got = suts.summarize_scenario_rows([unit])
    assert got["enum_only_searched"] == 1 and got["not_searched"] == {}
    assert got["units_with_rows"] == 1   # its rows are the enum search's only (review R80 W-R4-1)
    from report_gen.generation_disclosures import _scenario_rows_item
    assert "열거자 밖 값 탐색만 한 unit 1" in _scenario_rows_item(got)["note"]


def test_a_failing_enum_preparation_keeps_the_design_range_rows(monkeypatch):
    # (review R80 I-R5-3 · I-R4-4) the preparation raises: the enum search is lost, the design-range search is not
    def boom(*a, **k):
        raise RuntimeError("probe")
    monkeypatch.setattr(suts, "_single_value_enum_domains", boom)
    unit, seqs = _both(monkeypatch)
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_error"] == "RuntimeError" and sc["outside_design_rows"] >= 1
    assert any(s["strategy"].startswith(SCENARIO_FI_PREFIX) for s in seqs)
    got = suts.summarize_scenario_rows([unit])
    assert got["enum_errors"] == 1 and got["errors"] == 0


def test_an_enum_element_with_a_design_range_is_counted_once(monkeypatch):
    # (review R80 I-R5-1) the element's domain is a dict with the enum ctype: the enum search widens it — it is not also
    #   an integer design value list "not widened"
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_q": "U8", "g_k": "U8"})
    unit = _unit("elem", ["s_arr[1]", "g_k"], ["g_q"], uds_param_info={"s_arr[1]": {"range": [1, 2]}})
    extended_unit_sequences(unit)
    sc = unit["scenario_rows"]
    assert sc["outside_design_enum_inputs"] == 1 and sc["outside_design_value_sets"] == 0
