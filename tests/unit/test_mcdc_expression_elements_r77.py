"""R77 — the expression engine reads a constant-index element of a modeled global array as an input of its own name.

``(g_a[POS0] == P0) && (g_a[POS2] == P2) && …``: R76 sent every subscript to the path search, whose samples per input
are the function's first 12 constants — the index macros (±1) took those places, so a chain of element comparisons
never saw the constants it compares with (HDPDM01 ``s_DeviceTypeChk`` D1 no pair, its inner branches unreached;
KJPDS02_PV ``u8s_DeviceTypeChk_IsValidPartNo`` · ``u16s_Buzzer_Check``). Now the expression engine takes ``g_a[POS0]`` as
the input ``g_a[0]`` (the row's column) with the element's declared domain, and binds it as it binds a scalar global —
plus what an array's name being a pointer adds: before the decision, a store through a pointer, a call passing an
argument that may point into the array, a function whose pointer writes may land there (the project points-to
analysis) or a macro that may. The inputs the decision does not read start from the enclosing decision's vector, and
every pair member is run on the modeled function: one that reaches the decision otherwise than claimed refutes the
binding. A decision the expression engine then does not take goes exactly where R76 sent it, with R76's reason.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

import pytest

from generators import c_project_context as cpc
from generators import mcdc_design as md
from generators.mcdc_design import build_mcdc_design, evaluate_decision, finalize_mcdc_design
from generators.suts import summarize_mcdc_design
from report_gen.generation_disclosures import build_disclosures

ROOT = os.path.join(os.sep, "p77")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
#endif
"""
POS = "".join(f"#define POS{k} ({k}U)\n" for k in range(10))
UNIT = """#include "common.h"
""" + POS + """#define SET(x) ((x) = 1U)
#define OUTP (*g_ptr)
#define CLR_BUF clr(g_buf)
#define CLR_BUF2() clr(g_buf)
#define CLR_BP clr(g_bp)
#define K1 (1U)
typedef U8 *PU8;
enum en_st { ST_A = 0, ST_B = 1, ST_STOP = 4 };
struct S { U8 *p; U8 n; };
U8 g_part[4];
U8 g_chain[10];
enum en_st g_his[3];
U8 g_state;
U8 g_x;
U8 g_o;
U8 *g_ptr;
volatile U8 g_vol[2];
U8 g_taken[2];
U8 *g_keep = &g_taken[1];
U8 g_buf[4];
U8 *g_bp = g_buf;
struct S g_sp = { g_buf, 0U };
static const U8 c_lut[3] = { 10U, 20U, 30U };
static void peek(U8 *p) { g_o = p[0]; }
static void put(U8 v) { g_o = v; }
static void clr(U8 *p) { p[0] = 0U; }
static void fill(void) { g_part[0] = 1U; }
static void wipe2(void) { g_bp[0] = 7U; }
static void wipe3(void) { g_sp.p[0] = 7U; }
static void wrap(void) { peek(g_buf); }
static void wild(U16 a) { *((U8 *)a) = 1U; }
static void fillx(void) { g_part[0] = 1U; ext_fn(); }
void dev(void) {
    if ((g_part[POS0] == 0x34U) && (g_part[POS2] == 0x41U)) {
        if ((g_part[POS1] == 0x46U) && (g_part[POS3] == 0x52U)) { g_o = 1U; } else { g_o = 2U; }
    } else { g_o = 3U; }
}
void chain(void) {
    if ((g_chain[POS0] == 0x30U) && (g_chain[POS2] == 0x41U) && (g_chain[POS4] == 0x52U) && (g_chain[POS5] == 0x63U)
     && (g_chain[POS6] == 0x74U) && (g_chain[POS7] == 0x85U) && (g_chain[POS8] == 0x96U) && (g_chain[POS9] == 0xA7U)) {
        g_o = 1U;
    } else { g_o = 2U; }
}
void his(void) { if ((g_his[0] == ST_STOP) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void icall(void) { put(g_state); if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void wcall(void) { clr(&g_o); if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void after(void) {
    if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; }
    g_part[1] = 0U; *g_ptr = 2U; peek(g_part); clr(g_part); fill(); SET(g_o);
}
void wbefore(void) { g_part[3] = 0U; if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void pstore(void) { *g_ptr = 1U; if ((g_part[POS1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void pcall(void) { peek(g_part); if ((g_part[POS1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void pcast(void) { peek((PU8)g_x); if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void rr(void) { peek(g_part); if ((g_part[POS1] == 2U) && ((U8)g_state == K1)) { g_o = 1U; } else { g_o = 2U; } }
void mcall(void) { SET(g_o); if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void malias(void) { OUTP = 1U; if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void ncall(void) { fill(); if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void taken(void) { if ((g_taken[0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fa(void) { wipe2(); if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fb(void) { wipe3(); if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fc(void) { CLR_BUF; if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fc2(void) { CLR_BUF2(); if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fd(void) { g_sp.p[0] = 5U; if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fu(void) { wild(g_state); if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void fm(void) { CLR_BP; if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void sib(U8 k) {
    if (k == 1U) { U8 t[2]; t[0] = k; g_o = t[0]; } else { U8 *t = g_buf; t[0] = 9U; }
    if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; }
}
void sib3(U8 k) {
    if (k == 1U) { U8 t[2] = { 0U, 1U }; g_o = t[k]; } else { U8 *t = g_buf; clr(t); }
    if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; }
}
void lap(void) { PU8 t[1]; t[0] = g_buf; t[0][0] = 9U; if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } }
void nx(void) { fillx(); if ((g_part[1] == 2U) && (g_part[2] == 3U)) { g_o = 1U; } else { g_o = 2U; } }
void deep(void) { U8 t = g_part[3]; if (t == 9U) { if ((g_part[1] == 2U) && (g_part[2] == 3U)) { g_o = 1U; } } }
void part(void) { if (g_state != 0U) { if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } } }
void nest3(void) {
    if (g_part[POS0] == 0x34U) { if (g_state == 2U) { if (g_part[POS1] == 0x46U) { g_o = 1U; } } }
}
void fw(void) { wrap(); if ((g_buf[POS0] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void nrow(void) { if ((g_part[POS1] == 2U) && (g_x == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void wsame(void) { g_part[1] = 5U; if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void mixed(void) {
    U8 t = g_x;
    if ((t == 3U) && (g_state == 1U)) { g_o = 4U; }
    if ((g_part[1] == 5U) && (g_state == 2U)) { g_o = 5U; }
}
void ranged(void) { if ((g_part[1] == 200U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void loopf(void) {
    U8 i;
    for (i = 0U; i < 2U; i++) { if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } peek(g_part); }
}
void gotof(void) {
again:
    if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; }
    *g_ptr = 2U;
    if (g_state == 3U) { goto again; }
}
void lfirst(void) { U8 t = g_state; if ((t == 1U) && (g_part[1] == 2U)) { g_o = 1U; } else { g_o = 2U; } }
void efirst(void) { U8 t = g_state; if ((g_part[1] == 2U) && (t == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void range(void) { if ((g_part[7] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void varidx(U8 k) { if ((g_part[k] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void shadowp(U8 *g_part) { if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void shadowl(void) { U8 g_part[4]; g_part[1] = g_state; if ((g_part[1] == 2U) && (g_state == 1U)) { g_o = 1U; } }
void vol(void) { if ((g_vol[0] == 1U) && (g_state == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void lut(U8 x) { if ((x <= c_lut[0]) || (x >= c_lut[2])) { g_o = 1U; } else { g_o = 2U; } }
"""
PART = [f"g_part[{k}]" for k in range(4)]
BUF = [f"g_buf[{k}]" for k in range(4)]
CHAIN = [f"g_chain[{k}]" for k in range(10)]
HIS = [f"g_his[{k}]" for k in range(3)]
ROWS = {"dev": PART, "chain": CHAIN, "his": [*HIS, "g_state"], "taken": ["g_taken[0]", "g_taken[1]", "g_state"],
        "vol": ["g_vol[0]", "g_vol[1]", "g_state"], "lut": ["x"], "varidx": ["k", *PART, "g_state"],
        "nrow": [*PART, "g_ptr"], "mixed": ["g_x", "g_state", *PART], "pcast": [*PART, "g_state", "g_x"],
        **{f: [*BUF, "g_state"] for f in ("fa", "fb", "fc", "fc2", "fd", "fw", "fm", "lap")}, "fu": [*BUF, "g_state"],
        "sib": [*BUF, "g_state", "k"], "sib3": [*BUF, "g_state", "k"], "deep": PART}
_CONTEXT: dict = {}


def _context():
    if not _CONTEXT:
        path = os.path.join(ROOT, "unit.c")
        context = cpc.build_project_context({os.path.join(ROOT, "common.h"): COMMON, path: UNIT})
        _CONTEXT.update(path=path, context=context)
    return _CONTEXT["path"], _CONTEXT["context"]


def _unit(name, inputs=None, free_globals=False):
    path, context = _context()
    scope = cpc.build_scopes(context, [path])[path]
    unit = {"name": name, "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": list(ROWS.get(name, [*PART, "g_state"]) if inputs is None else inputs)}
    if free_globals:
        del unit["input_vars"]
        unit["mcdc_free_globals"] = True
    return unit


def _r76(monkeypatch, unit):
    monkeypatch.setattr(md, "EXPRESSION_ELEMENTS", False)
    try:
        return build_mcdc_design(unit)
    finally:
        monkeypatch.setattr(md, "EXPRESSION_ELEMENTS", True)


def _same_as_r76(r77, r76):
    for d in r77["decisions"]:
        d.pop("element_expression_reason", None)
    return json.dumps(r77, sort_keys=True, default=str) == json.dumps(r76, sort_keys=True, default=str)


def _retained(report):
    finalize_mcdc_design(report, [{"seq_num": i, "inputs": v} for i, v in enumerate(report["selected_inputs"])])
    return [p for d in report["decisions"] for p in d["pairs"]]


def test_a_chain_of_element_comparisons_is_paired_where_the_path_samples_never_reached(monkeypatch):
    # the R76 path search: per input the function's first 12 constants — the index macros 0 · 2 · 4 … (±1) come first
    before = _r76(monkeypatch, _unit("chain"))["decisions"][0]
    assert before["search_group"] == "array_element" and before["status"] != "designed", before["reason"]
    report = build_mcdc_design(_unit("chain"))
    (d,) = report["decisions"]
    assert d["status"] == "designed" and len(d["pairs"]) == 8 and d.get("evaluation") is None, d["reason"]
    assert d["expression_elements"] == sorted(f"g_chain[{k}]" for k in (0, 2, 4, 5, 6, 7, 8, 9))
    assert d["variables"] == [f"g_chain[{k}]" for k in (0, 2, 4, 5, 6, 7, 8, 9)]
    assert "inputs_not_designed" not in d    # every element column has its domain
    # each pair flips its element across the constant it compares with; the indexes are no compared values
    compared = {f"g_chain[{k}]": v for k, v in zip((0, 2, 4, 5, 6, 7, 8, 9), (0x30, 0x41, 0x52, 0x63, 0x74, 0x85, 0x96, 0xA7),
                                                   strict=True)}
    for pair in d["pairs"]:
        name = d["variables"][int(pair["condition_id"][1:]) - 1]
        assert compared[name] in (pair["inputs_a"][name], pair["inputs_b"][name]), pair
    # the row sets every element of the array (the row's columns) — the unread ones at their default
    assert all(set(v) == set(CHAIN) for v in report["selected_inputs"])
    # every pair member reaches the decision on the modeled run with the claimed truths
    assert d["element_run_check"] == {"members": 16, "agrees": 16, "unreached": 0, "not_checked": 0, "differs": []}
    assert all(p["retained_status"] == "retained" for p in _retained(report))


def test_the_inner_branches_start_from_the_enclosing_decision_and_re_evaluate():
    report = build_mcdc_design(_unit("dev"))
    d1, d2 = report["decisions"]
    assert (d1["status"], d2["status"]) == ("designed", "designed"), (d1["reason"], d2["reason"])
    assert d2["expression_elements"] == ["g_part[1]", "g_part[3]"]
    # the indexes (POS0 · POS2) are no compared values: each element samples 0 · 1 · 0x34 ±1 · 0x41 ±1 · 255
    assert d1["values_sampled"] and d1["candidate_space_size"] == 9 * 9
    # (review W3) D2's rows hold D1's true vector in the elements D2 does not read — so they reach D2
    for pair in d2["pairs"]:
        for side in ("a", "b"):
            assert (pair[f"inputs_{side}"]["g_part[0]"], pair[f"inputs_{side}"]["g_part[2]"]) == (0x34, 0x41)
            assert pair[f"run_{side}"] == "agrees"
    assert d2["element_run_check"]["agrees"] == 4
    assert report["domains"]["g_part[1]"]["source"] == "array_element_declaration"
    # the design's report alone re-evaluates the pairs: the index macros are among its constants
    assert {"POS1", "POS3"} <= set(report["constants"])
    widths = report["target"]["widths"]
    for pair in d2["pairs"]:
        for side in ("a", "b"):
            ev = evaluate_decision(d2["expression"], pair[f"inputs_{side}"], report["domains"], report["constants"], widths)
            assert ev["status"] == "supported" and ev["decision"] == pair[f"decision_{side}"], ev
            assert ev["truth"] == pair[f"truth_{side}"]
    assert all(p["retained_status"] == "retained" for p in _retained(report))
    # without the element's domain the subscript is refused as before
    ev = evaluate_decision("g_part[POS1] == 0x46U", {}, {}, report["constants"], widths)
    assert ev == {"status": "unsupported", "reason": md._SUBSCRIPT_REASON, "execution_status": "not_run"}


@pytest.mark.parametrize("name", ["his", "icall", "wcall", "after"])
def test_what_cannot_reach_the_array_before_the_decision_binds(name):
    # an enumeration element · a call passing integers · ``clr(&g_o)`` (the analysis: it writes through its parameter
    #   to g_o only) · events after the decision
    (d,) = [d for d in build_mcdc_design(_unit(name))["decisions"] if d.get("expression_elements")]
    assert d["status"] == "designed", d.get("element_expression_reason")
    assert d["element_run_check"]["agrees"] == d["element_run_check"]["members"] > 0
    if name == "his":
        pair = next(p for p in d["pairs"] if p["condition_id"] == "C1")
        assert 4 in (pair["inputs_a"]["g_his[0]"], pair["inputs_b"]["g_his[0]"])


@pytest.mark.parametrize("name, reason", [
    ("wbefore", "input_modified_before_decision:g_part"),                     # another element: any index unbinds
    ("pstore", "array_element_binding_unverified:g_part:pointer_store"),
    ("pcall", "array_element_binding_unverified:g_part:call_argument:peek"),  # a stub of peek may write through it
    ("pcast", "array_element_binding_unverified:g_part:call_argument:peek"),  # (review I1) a pointer typedef cast
    ("rr", "array_element_binding_unverified:g_part:call_argument:peek"),     # (review W2) after a cast and a constant
    ("mcall", "global_binding_unverified:macro_assignment:SET"),              # a scalar global's judgment already
    ("malias", "array_element_binding_unverified:g_part:macro:OUTP"),         # a store through what a name expands to
    ("ncall", "global_modified_by_callee:fill:g_part"),
    ("taken", "global_address_taken:g_taken"),
    ("nrow", "decision_variable_not_in_unit_inputs:g_x"),                    # refused after the vector's blanks were set
    # (review C1) what the points-to analysis knows: a callee writing through a global pointer · a pointer member · a macro
    #   passing the array · an in-function store through a pointer member · a callee passing it to one a row may stub
    ("fa", "array_element_binding_unverified:g_buf:callee_pointer_write:wipe2"),
    ("fb", "array_element_binding_unverified:g_buf:callee_pointer_write:wipe3"),
    ("fc", "array_element_binding_unverified:g_buf:macro_names_array:CLR_BUF"),
    ("fc2", "array_element_binding_unverified:g_buf:macro_names_array:CLR_BUF2"),
    ("fd", "array_element_binding_unverified:g_buf:pointer_store"),
    ("fw", "array_element_binding_unverified:g_buf:callee_stub_write:wrap:peek"),
    # where a callee's pointer writes land is unknown (an integer made a pointer) · a macro passing a pointer variable
    #   to a function that writes through that parameter
    ("fu", "array_element_binding_unverified:g_buf:pointer_targets_unknown:wild"),
    ("fm", "array_element_binding_unverified:g_buf:macro_passes_pointer:clr"),
    # (review R2 C-R2-1) a name a sibling block declares a pointer · an array of a pointer typedef is no array object
    ("sib", "array_element_binding_unverified:g_buf:pointer_store"),
    ("sib3", "array_element_binding_unverified:g_buf:call_argument:clr"),
    ("lap", "array_element_binding_unverified:g_buf:pointer_store"),
    # (review R2 I-1) a callee that writes the array and calls unknown code: the array's judgment names the write
    ("nx", "global_modified_by_callee:fillx:g_part"),
    # (review R2 W-R2-2) no row reaches it (the enclosing decision reads a local — no expression vector to start from)
    ("deep", "array_element_pair_rows_unreached"),
])
def test_an_element_the_engine_cannot_bind_goes_where_r76_sent_it(monkeypatch, name, reason):
    unit = _unit(name)
    r76 = _r76(monkeypatch, unit)
    r77 = build_mcdc_design(unit)
    (d,) = [d for d in r77["decisions"] if "element_expression_reason" in d]
    assert d["element_expression_reason"] == reason
    assert d["search_group"] == "array_element" and d["static_reason"] == md._SUBSCRIPT_REASON
    # exactly R76's design: the decision, its rows, the report's constants · types · domains
    assert _same_as_r76(r77, r76)


def test_the_modeled_run_refutes_a_binding_the_static_judgment_missed(monkeypatch):
    # with the static judgment off, ``g_part[1] = 5U`` before the decision goes unseen: the run reaches the decision with
    #   other truths than the pairs claim — the decision goes where R76 sent it, its vectors and domains withdrawn
    unit = _unit("wsame")
    r76 = _r76(monkeypatch, unit)
    monkeypatch.setattr(md, "_element_binding_issue", lambda *args: "")
    r77 = build_mcdc_design(unit)
    (d,) = r77["decisions"]
    assert d["element_expression_reason"].startswith("array_element_binding_refuted_by_run:D1:C1:P1:")
    assert _same_as_r76(r77, r76)
    # (review R2 W-R2-1) a write the run cannot place (``wipe2`` through ``g_bp``) leaves the value undetermined there:
    #   unconfirmed — refuted too
    unit = _unit("fa")
    r76 = _r76(monkeypatch, unit)
    r77 = build_mcdc_design(unit)
    (d,) = r77["decisions"]
    assert d["element_expression_reason"].startswith("array_element_binding_refuted_by_run:") and \
        ":undetermined:" in d["element_expression_reason"], d["element_expression_reason"]
    assert _same_as_r76(r77, r76)


def test_a_pair_whose_row_does_not_reach_the_decision_is_withdrawn():
    # (review R2 W-R2-2) D2's C2 pair flips g_state to 0, which the enclosing ``g_state != 0U`` rejects
    report = build_mcdc_design(_unit("part"))
    _d1, d2 = report["decisions"]
    assert d2["status"] == "partial" and d2["reason"] == "element_pair_rows_unreached", d2["reason"]
    assert d2["unreached_pairs"] == ["D2:C2:P1"] and [p["condition_id"] for p in d2["pairs"]] == ["C1"]
    assert d2["element_run_check"]["unreached"] >= 1
    # its rows are withdrawn with it
    assert all(v["g_state"] == 1 for v in report["selected_inputs"] if "g_part[1]" in v)


def test_the_seed_gathers_every_enclosing_decision():
    # (review R2 W-R2-3) element → scalar → element: D3 starts from D1's element and D2's scalar
    _d1, _d2, d3 = build_mcdc_design(_unit("nest3"))["decisions"]
    assert d3["status"] == "designed", d3.get("element_expression_reason") or d3["reason"]
    for pair in d3["pairs"]:
        for side in ("a", "b"):
            assert (pair[f"inputs_{side}"]["g_part[0]"], pair[f"inputs_{side}"]["g_state"]) == (0x34, 2)
    assert d3["element_run_check"]["agrees"] == d3["element_run_check"]["members"]


def test_a_path_decision_beside_an_element_decision_keeps_its_inputs(monkeypatch):
    unit = _unit("mixed")
    r76 = _r76(monkeypatch, unit)["decisions"][0]
    d1, d2 = build_mcdc_design(unit)["decisions"]
    assert d1.get("evaluation") == "source_path" and d2["expression_elements"] == ["g_part[1]"]
    # (review W2) the path groups start from the domains without the elements (R74): D1 searched as in R76
    assert json.dumps(d1, sort_keys=True, default=str) == json.dumps(r76, sort_keys=True, default=str)
    assert d1["path_search"]["inputs"] == ["g_x", "g_state"]


def test_the_element_design_range_narrows_its_domain():
    unit = _unit("ranged")
    unit["uds_param_info"] = {"g_part[1]": {"range": [0, 10]}}
    report = build_mcdc_design(unit)
    (d,) = report["decisions"]
    assert d["expression_elements"] == ["g_part[1]"]
    assert (report["domains"]["g_part[1]"]["min"], report["domains"]["g_part[1]"]["max"]) == (0, 10)
    assert "C1" not in {p["condition_id"] for p in d["pairs"]}    # 200 is outside 0..10


def test_a_loop_or_a_goto_lets_a_later_event_run_before():
    _d1, d2 = build_mcdc_design(_unit("loopf"))["decisions"]
    assert d2["element_expression_reason"] == "array_element_binding_unverified:g_part:call_argument:peek"
    d1, _d2 = build_mcdc_design(_unit("gotof"))["decisions"]
    assert d1["element_expression_reason"] == "array_element_binding_unverified:g_part:pointer_store"


def test_a_refusal_keeps_r76s_reason_whichever_condition_comes_first(monkeypatch):
    # R76 refused at the first unsupported operand: the local ``t`` (general group) or the subscript (element group) —
    #   the expression engine now compiles the element and refuses at ``t`` in both orders; the decision keeps R76's
    for name, group in (("lfirst", ""), ("efirst", "array_element")):
        unit = _unit(name, [*PART, "g_state"])
        r76 = _r76(monkeypatch, unit)
        r77 = build_mcdc_design(unit)
        (d,) = r77["decisions"]
        assert d.get("search_group", "") == group and d["element_expression_reason"].startswith("local_variable_not_input:t")
        assert _same_as_r76(r77, r76), name


@pytest.mark.parametrize("name", ["range", "varidx", "shadowp", "shadowl", "vol", "lut"])
def test_no_element_input_no_change(monkeypatch, name):
    # outside the array · the run's index · a parameter or local hiding the array · volatile · a const table: no input
    unit = _unit(name)
    r76 = _r76(monkeypatch, unit)
    r77 = build_mcdc_design(unit)
    assert all("element_expression_reason" not in d and "expression_elements" not in d for d in r77["decisions"])
    assert json.dumps(r77, sort_keys=True, default=str) == json.dumps(r76, sort_keys=True, default=str)


def test_the_inventory_takes_the_elements_the_decisions_read():
    report = build_mcdc_design(_unit("dev", free_globals=True))
    d1, d2 = report["decisions"]
    assert (d1["status"], d2["status"]) == ("designed", "designed"), (d1["reason"], d2["reason"])
    # no row: a vector sets the elements its decision reads — D2's also D1's, from the enclosing vector (review R2 W-R2-3)
    assert {k for v in report["selected_inputs"] for k in v} == set(PART)
    for pair in d2["pairs"]:
        for side in ("a", "b"):
            assert (pair[f"inputs_{side}"]["g_part[0]"], pair[f"inputs_{side}"]["g_part[2]"]) == (0x34, 0x41)
    assert d2["element_run_check"]["agrees"] == 4
    assert all(p["retained_status"] == "retained" for p in _retained(report))


def test_store_and_argument_readers():
    from workflow.code_parser.c_parser import _make_parser
    raw = (b"void f(U8 *p, U8 v) { U8 t[2]; *p = 1U; p->a = 1U; p[0] = 1U; (p)[1] = 1U; g_a[0] = 1U; t[1] = 1U; "
           b"g.b[1] = 1U; g.s.p->x = 1U; m[1][2] = 1U; v = 1U; ((U8 *)p)[0] = 1U; g.n = 1U; "
           b"h(1U, v, POS1, g_part[v], (U8)v, sizeof(g_part), p, &v, (U8 *)v, g_part, k(1U), \"s\", &g_x, g_chain, *p, "
           b"&g_part[1], (PU8)v, g.n, &g_part); }")
    root = _make_parser().parse(raw).root_node
    stores = [n for n in md._walk(root) if n.type == "assignment_expression"]
    through = [md._store_through_pointer(n.child_by_field_name("left"), raw, {"g_a", "t", "m"}) for n in stores]
    # (review C1) ``g.b[1]`` indexes a member, which may be a pointer
    assert through == [True, True, True, True, False, False, True, True, True, False, True, False]
    call = next(n for n in md._walk(root) if n.type == "call_expression")
    args = [c for c in call.child_by_field_name("arguments").named_children]
    scope = _unit("dev")["project_scope"]
    reach = [md._argument_reaches(a, "g_part", raw, {"v": {}}, {"POS1": {}}, {"g_part", "g_chain"}, scope) for a in args]
    assert reach == [False, False, False, False, False, False, True, False, True, True, True, False, False, False, True,
                     True, True, True, True]


def test_counted_and_disclosed():
    units = []
    for name in ("chain", "dev", "pcall", "malias"):
        unit = _unit(name)
        unit["mcdc_design"] = build_mcdc_design(unit)
        units.append(unit)
    summary = summarize_mcdc_design(units)
    assert (summary["element_expression_decisions"], summary["element_expression_designed"],
            summary["element_expression_partial"], summary["element_expression_no_pair"]) == (3, 3, 0, 0)
    assert (summary["element_run_members"], summary["element_run_agrees"], summary["element_run_unreached"],
            summary["element_run_not_checked"]) == (24, 24, 0, 0)
    assert summary["element_expression_refused"] == 2
    assert summary["element_expression_refusals"] == {"array_element_binding_unverified:call_argument": 1,
                                                      "array_element_binding_unverified:macro": 1}
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary}) if i["key"] == "suts_mcdc_design"]
    assert "식 엔진이 입력으로 읽은 결정 3(설계 3 · 일부 0 · 쌍 없음 0" in item["note"]
    assert "24 행 중 주장과 같음 24 · 결정에 닿지 않음 0" in item["note"]
    assert "받지 못한 2 은 R76 과 같은 사유" in item["note"]
    assert "`array_element_binding_unverified:call_argument` 1" in item["note"]


def _clang():
    found = shutil.which("clang")
    default = r"C:\Program Files\LLVM\bin\clang.exe"
    return found or (default if os.path.isfile(default) else None)


def test_clang_agrees_on_the_element_pairs_and_catches_a_wrong_index():
    clang = _clang()
    if clang is None:
        pytest.skip("clang not installed")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    from mcdc_design_clang_oracle import _checks, check_unit
    path, context = _context()
    entries = []
    for name in ("dev", "chain", "his"):
        unit = _unit(name, free_globals=True)
        entries += list(_checks(path, build_mcdc_design(unit)))
    scope = cpc.build_scopes(context, [path])[path]
    for n in ("POS0", "POS1", "POS2", "POS3", "POS4", "POS5", "POS6", "POS7", "POS8", "POS9", "ST_STOP"):
        assert n in scope["constants"]   # (the prelude writes the constants the scope resolved)
    # the element reads are bound under harness names, each index checked by clang on its own — once per decision
    label, binds, exprs, names = entries[0]
    assert any(b.startswith("#define __mcdc_elem_g_part_0 ") for b in binds) and "__mcdc_elem_g_part_0" in names
    assert ("index:POS0", "(POS0) == 0", 1) in exprs and "g_part[" not in exprs[0][1]
    assert not any(cid.startswith("index:") for cid, _e, _x in entries[1][2])
    with tempfile.TemporaryDirectory() as tmp:
        mismatches, errors, claims = check_unit(path, context, scope, entries, clang, "msp430", tmp)
        assert (mismatches, errors) == ([], []) and claims > 100, (mismatches, errors)
        wrong = [(label, binds, [("index:POS0", "(POS0) == 1", 1)], names)]
        mismatches, errors, _ = check_unit(path, context, scope, wrong, clang, "msp430", tmp)
        assert [m["claim"] for m in mismatches] == [f"{label}:index:POS0"] and errors == []
