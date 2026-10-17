"""R83 — what the mutants only the reference killed after R82 needed (PV 10 · HD 7, extended SUTS).

(1) The scenario search runs with the harness the rows have: a pointer member the rows name by itself
(`ReqMsg[0].data`) is a harness buffer (R82) only when the row sets it, so the search holds it at one value too —
without it `&ReqMsg->data[2]` went through an unknown pointer and every SendKey path was reached only uncleanly
(`sf_LinUdsSecurityAccess` 4).
(2) An element of a multi-dimensional array object (`S16 t[5][7][7]`) is bounded per dimension — no pointer arithmetic
that may leave the object (`s_SetPWMTableValue` 4: no clean run took table 1 or 2).
(3) The tree's typedef of an exact-width name under `#ifndef int16_t` is read (`s_MotorSpeedMeasure`:
`(int32_t)a - (int32_t)b` was a possible signed overflow on every path).
(4) Companion rows tell stub returns apart (`s_FanRecircurationCheck`, HD `s_ApiOut_u8bit_DataUpdate_A`: two stubs
feeding one output returned the same value in every row) — the existing rows keep their values (R75: the extended
document holds the reference document's rows unchanged; review R83 C1).
(5) A decision of more than 16 conditions gets sub-condition records — and so fault-exposing boundaries (HD
`s_DoorState_AutoStop_Detection` M49)."""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators import scenario_rows as sr
from generators import suts
from generators.c_source_oracle import evaluate_outputs
from generators.mcdc_design import _pointer_member_input
from generators.suts import extended_unit_sequences, generate_sequences, normalize_pointer_parameters

ROOT = os.path.join(os.sep, "virt_r83")
CPROJECT = """<?xml version="1.0" encoding="UTF-8"?><cproject><storageModule moduleId="org.eclipse.cdt.core.settings">
<cconfiguration id="c1"><storageModule moduleId="cdtBuildSystem"><configuration artifactName="app" name="FLASH">
<folderInfo id="f"><toolChain id="t" superClass="com.freescale.s12z.toolchain">
<tool id="c" superClass="com.freescale.s12z.toolchain.compiler">{options}</tool></toolChain></folderInfo>
</configuration></storageModule></cconfiguration></storageModule>
<storageModule moduleId="refreshScope"><configuration configurationName="FLASH"><resource name="" type="4"/></configuration>
</storageModule></cproject>"""
HEADER = """#ifndef C_H
#define C_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef unsigned long U32;
#ifndef int16_t
typedef signed int   int16_t;
#endif
#ifndef int32_t
typedef signed long int    int32_t;
#endif
#ifndef uint8_t
typedef unsigned char uint8_t;
U8 g_inside;
#endif
#ifndef int8_t
typedef signed int int8_t;
#endif
#ifdef int16_t
#define HAVE_INT16_MACRO 1
#endif
#ifndef uint16_t
typedef unsigned int OTHER16;
#else
typedef unsigned int uint16_t;
#endif
#if !defined(uint32_t)
typedef unsigned long uint32_t;
#endif
#ifndef int64_t
#define int64_t long long
#endif
typedef struct { U8 *data; U16 length; } MSG;
typedef U8 ROW[3];
typedef uint8_t ERRCODE;
#define VALID 0xAAU
typedef enum { LV_OFF = 0, LV_LOW = 1, LV_HIGH = 2 } LV_T;
#define ON 1U
#define SEND_KEY 2U
#define KEY_LEN 6U
U32 read32(const U8 *p);
U8 doors(void);
U8 lvl_closed(void);
U8 lvl_open(void);
LV_T lvl_mode(void);
U8 lvl_step(void);
U8 conv_a(void);
U8 conv_b(void);
U8 check(U8 x);
#endif
"""
SRC = """#include "c.h"
S16 g_tbl[5][7][7];
ROW g_rowtab[2][4];
int16_t g_w16;
U8 g_angle;
U8 g_vsup;
U8 g_cnt;
volatile U8 g_port;
U8 g_hidden;
U8 g_sw0;
U8 g_sw1;
U8 g_sw2;
U8 g_sw3;
U8 g_sw4;
U8 g_sw5;
U8 g_sw6;
U8 g_sw7;
U8 g_sw8;
U8 g_sw9;
U8 g_sw10;
U8 g_sw11;
U8 g_sw12;
U8 g_sw13;
U8 g_sw14;
U8 g_sw15;
U8 g_sw16;
U8 g_sw17;
U8 g_sw18;
U8 g_sw19;
int16_t g_arr16[4];
typedef struct { int16_t v; U8 w; } PT16;
S16 g_rows[2][3];
U16 g_avg;
U16 g_old;
int16_t g_ratio;
U8 g_out;
U8 g_sub;
U16 g_len;
U32 g_key;
U8 g_a; U8 g_b; U8 g_c; U8 g_d; U8 g_e; U8 g_f; U8 g_g; U8 g_h; U8 g_i; U8 g_j;
U8 g_k; U8 g_l; U8 g_m; U8 g_n; U8 g_o; U8 g_p; U8 g_q; U8 g_r; U8 g_s; U8 g_t;
#ifndef int32_t
U8 guarded(U8 x)
{
    return (U8)(x + 1U);
}
#endif
U8 set_tbl(U8 id, U8 idx, S16 v)
{
    U8 r;
    if (idx < 245U)
    {
        U8 a = (U8)(idx / 49U);
        U8 rem = (U8)(idx % 49U);
        U8 b = (U8)(rem / 7U);
        U8 c = (U8)(rem % 7U);
        switch (id)
        {
            case 0U: g_tbl[a][b][c] = v; r = 1U; break;
            case 1U: g_tbl[a][b][c] = (S16)(v + 1); r = 2U; break;
            default: r = 0U; break;
        }
    }
    else
    {
        r = 0U;
    }
    return r;
}
S16 get_rows(U8 i, U8 j)
{
    return g_rows[i][j];
}
U8 shadow(void)
{
    S16 g_tbl[2][2][2];
    g_tbl[1][1][1] = 3;
    return 1U;
}
U8 subrow(void)
{
    S16 *p;
    p = g_rows[1];
    return (U8)(p != 0);
}
void delta(void)
{
    int32_t d;
    d = (int32_t)g_avg - (int32_t)g_old;
    if (d > 100) { g_ratio = (int16_t)100; } else { g_ratio = (int16_t)d; }
}
U32 read32(const U8 *p)
{
    return (U32)p[0];
}
void sec(const MSG *req, MSG *resp)
{
    U32 key;
    if (g_sub == SEND_KEY)
    {
        if (g_len == KEY_LEN)
        {
            key = read32(&req->data[2]);
            if (key == 5U)
            {
                resp->length = 2U;
                resp->data[0] = 0x67U;
            }
        }
    }
}
U8 doors(void)
{
    return g_sub;
}
U8 lvl_closed(void)
{
    return g_sub;
}
U8 lvl_open(void)
{
    return g_sub;
}
LV_T lvl_mode(void)
{
    return LV_OFF;
}
void fan(void)
{
    if (doors() == ON)
    {
        g_out = lvl_closed();
    }
    else
    {
        g_out = lvl_open();
    }
}
U8 lvl_step(void)
{
    return g_sub;
}
void stepped(void)
{
    if (doors() == ON) { g_out = lvl_closed(); } else { g_out = lvl_step(); }
}
U8 conv_a(void)
{
    return g_sub;
}
U8 conv_b(void)
{
    return g_sub;
}
U8 check(U8 x)
{
    return x;
}
void apiout(void)
{
    U8 t;
    t = conv_a();
    if (check(t) == VALID) { g_angle = t; } else { g_cnt++; }
    t = conv_b();
    if (check(t) == VALID) { g_vsup = t; } else { g_cnt++; }
}
void pick(void)
{
    if (lvl_closed() == lvl_open()) { g_out = doors(); } else { g_out = lvl_step(); }
}
U8 rd16(void)
{
    return (U8)(g_w16 > 0);
}
ERRCODE rdalias(U8 x)
{
    return (ERRCODE)x;
}
void forky(void)
{
    if (g_port == 1U) { g_out = lvl_closed(); } else { g_out = lvl_open(); }
}
void forky2(void)
{
    if (g_port == 1U) { g_cnt = 1U; } else { g_cnt = 2U; }
    g_out = (U8)(lvl_closed() + lvl_open());
}
void lossy(void)
{
    g_cnt = lvl_closed();
    g_out = (lvl_open() == 7U) ? 1U : g_hidden;
}
void sw20(void)
{
    switch (g_sub)
    {
        case 0U: g_sw0 = (U8)(conv_a() + lvl_closed()); break;
        case 1U: g_sw1 = (U8)(conv_a() + lvl_closed()); break;
        case 2U: g_sw2 = (U8)(conv_a() + lvl_closed()); break;
        case 3U: g_sw3 = (U8)(conv_a() + lvl_closed()); break;
        case 4U: g_sw4 = (U8)(conv_a() + lvl_closed()); break;
        case 5U: g_sw5 = (U8)(conv_a() + lvl_closed()); break;
        case 6U: g_sw6 = (U8)(conv_a() + lvl_closed()); break;
        case 7U: g_sw7 = (U8)(conv_a() + lvl_closed()); break;
        case 8U: g_sw8 = (U8)(conv_a() + lvl_closed()); break;
        case 9U: g_sw9 = (U8)(conv_a() + lvl_closed()); break;
        case 10U: g_sw10 = (U8)(conv_a() + lvl_closed()); break;
        case 11U: g_sw11 = (U8)(conv_a() + lvl_closed()); break;
        case 12U: g_sw12 = (U8)(conv_a() + lvl_closed()); break;
        case 13U: g_sw13 = (U8)(conv_a() + lvl_closed()); break;
        case 14U: g_sw14 = (U8)(conv_a() + lvl_closed()); break;
        case 15U: g_sw15 = (U8)(conv_a() + lvl_closed()); break;
        case 16U: g_sw16 = (U8)(conv_a() + lvl_closed()); break;
        case 17U: g_sw17 = (U8)(conv_a() + lvl_closed()); break;
        case 18U: g_sw18 = (U8)(conv_a() + lvl_closed()); break;
        case 19U: g_sw19 = (U8)(conv_a() + lvl_closed()); break;
        default: g_out = (U8)(conv_a() + lvl_closed()); break;
    }
}
void gain(void)
{
    g_cnt = lvl_closed();
    g_out = (lvl_open() == 7U) ? g_hidden : 1U;
}
U8 gainret(void)
{
    g_cnt = lvl_closed();
    return (lvl_open() == 7U) ? g_hidden : 1U;
}
int16_t retw(U8 x)
{
    return (int16_t)x - 200;
}
void parw(int16_t v)
{
    g_out = (U8)(v > 0);
}
void unusedw(int16_t v)
{
    g_out = 1U;
}
void bothcalls(void)
{
    if (g_sub == 1U) { g_out = (U8)(conv_a() + conv_b()); } else { g_out = doors(); }
}
U8 nouse(const PT16 *p)
{
    return 0U;
}
void twogroups(void)
{
    g_out = (U8)(conv_a() + lvl_closed());
}
U8 rdarr(U8 i)
{
    return (U8)(g_arr16[i & 3U] > 0);
}
U8 rdpt(const PT16 *p)
{
    return (U8)(p->w + 1U);
}
void idle(void)
{
    g_out = doors();
}
void moded(void)
{
    if (lvl_mode() == LV_HIGH) { g_out = lvl_closed(); } else { g_out = lvl_open(); }
}
void big(void)
{
    if ((g_a == 1U) && (g_b == 1U) && (g_c == 1U) && (g_d == 1U) && (g_e == 1U) && (g_f == 1U) && (g_g == 1U)
        && (g_h == 1U) && (g_i == 1U) && (g_j == 1U) && (g_k == 1U) && (g_l == 1U) && (g_m == 1U) && (g_n == 1U)
        && (g_o == 1U) && (g_p == 1U) && (g_q == 1U) && (g_r == 1U) && ((g_s >= 8U) || (g_t == 5U)))
    {
        g_out = 1U;
    }
    else
    {
        g_out = 0U;
    }
}
"""
PATH = os.path.join(ROOT, "u.c")
_CACHE: dict = {}


def _scope(with_build=True):
    key = ("scope", with_build)
    if key not in _CACHE:
        files = {os.path.join(ROOT, "c.h"): HEADER, PATH: SRC}
        cp = {os.path.join(ROOT, ".cproject"): CPROJECT.format(options="")} if with_build else {}
        ctx = cpc.build_project_context(files, cpc.detect_build_config(cp), roots=[ROOT])
        _CACHE[key] = cpc.build_scopes(ctx, [PATH])[PATH]
    return _CACHE[key]


def _unit(name, ins=(), outs=(), ptypes=None, **extra):
    return {"name": name, "fid": "F_" + name, "source_text": SRC, "source_path": PATH, "source_text_complete": True,
            "project_scope": _scope(), "input_vars": list(ins), "output_vars": list(outs),
            "param_types": dict(ptypes or {}), "uds_param_info": {}, **extra}


def _run(unit, inputs, outs):
    return evaluate_outputs(unit, [inputs], [list(outs)])[0]


TYPES = {**{f"g_sw{i}": "U8" for i in range(20)}, "g_out": "U8", "g_sub": "U8", "g_len": "U16", "g_key": "U32", "g_avg": "U16", "g_old": "U16",
         "g_ratio": "S16", **{f"g_{c}": "U8" for c in "abcdefghijklmnopqrst"}}


# ── (3) an exact-width typedef under `#ifndef` of its own name ───────────────────────────────────────────────────────
def test_the_guarded_exact_width_typedef_is_read_with_its_width():
    scope = _scope()
    assert scope["types"]["int16_t"]["bits"] == 16 and scope["types"]["int16_t"]["signed"] is True
    assert scope["types"]["int32_t"]["bits"] == 32 and scope["types"]["uint8_t"]["signed"] is False
    assert set(scope["exact_width_guards"]) == {"int16_t", "int32_t", "uint8_t"}   # int8_t refused for its width
    assert any("exact-width names" in a and "int16_t" in a for a in scope["pp_assumptions"])
    assert "int16_t" not in scope["assumed_undefined"]   # no #if verdict: the guard alone


def test_a_typedef_whose_width_is_not_the_names_stays_unresolved():
    # `typedef signed int int8_t;` — 16 bits here: had a header made it a macro, it would be 8 bits
    assert "int8_t" not in _scope()["types"]
    assert _scope()["unresolved_types"]["int8_t"] == "exact_width_typedef_mismatch:int8_t"


def test_the_rest_of_the_guarded_group_and_other_ifs_on_the_name_stay_undecided():
    scope = _scope()
    assert scope["unresolved_globals"]["g_inside"] == "global_declared_conditionally"
    assert scope["macro_status"].get("HAVE_INT16_MACRO") == "unknown"   # `#ifdef int16_t` is a feature test


def test_only_the_typedef_of_the_guarded_name_and_only_an_ifndef_is_read():
    scope = _scope()
    assert "OTHER16" not in scope["types"]                       # another name under `#ifndef uint16_t`
    assert "uint32_t" not in scope["types"]                      # `#if !defined(…)` is no `#ifndef` guard
    assert "uint16_t" not in scope["exact_width_guards"]         # a guard whose group held no typedef of its name
    assert "uint16_t" not in scope["types"]                      # the else arm (the name IS a macro) stays undecided
    assert "int64_t" not in scope["exact_width_guards"]          # a group that defines a macro of the name


def test_a_function_defined_under_the_guard_stays_undecided():
    # (review R83 W1) the guard mode reads only the typedef: a function in the group is not compiled for sure
    got = _run(_unit("guarded"), {"x": 1}, ["return"])
    assert got["status"] == "unsupported" and "conditional_compilation" in got["reason"]


def test_a_value_resting_on_the_guard_says_so():
    # (review R83 W3) the assumption reaches the record and the evidence count — only where the function names the type
    got = _run(_unit("delta"), {"g_avg": 300, "g_old": 250}, ["g_ratio"])
    assert got["exact_width_guards"] == ["int16_t", "int32_t"]
    assert any("past its undecided `#ifndef` guard" in a for a in got["assumptions"])
    assert "exact_width_guards" not in _run(_unit("set_tbl"), {"id": 0, "idx": 0, "v": 1}, ["return"])
    from generators.test_evidence import summarize_expected_evidence
    seq = {"expected": {"g_ratio": 50}, "expected_evidence": {"g_ratio": {"status": "derived",
                                                                          "exact_width_guards": ["int16_t"]}}}
    assert summarize_expected_evidence([seq])["derived_on_exact_width_guard"] == 1


def test_an_alias_or_a_global_of_the_type_is_a_use_too():
    # (review R83 W-R2-3) a function naming only `g_w16` (int16_t) or an alias (ERRCODE = uint8_t) rests on the reading
    assert _run(_unit("rd16"), {"g_w16": 5}, ["return"])["exact_width_guards"] == ["int16_t"]
    assert _run(_unit("rdalias"), {"x": 5}, ["return"])["exact_width_guards"] == ["uint8_t"]
    summary = cpc.summarize_build_assumptions([_scope()])
    assert summary["units_with_exact_width_guards"] == 1
    assert summary["exact_width_guard_names"] == ["int16_t", "int32_t", "uint8_t"]
    from report_gen.generation_disclosures import build_disclosures
    note = {i["key"]: i for i in build_disclosures("suts", {"build_assumptions": summary})}
    assert any("정확폭 typedef" in i["note"] for i in note.values())


def test_an_array_or_a_pointee_member_of_the_type_is_a_use_too():
    # (review R83 W-R3-4)
    assert _run(_unit("rdarr"), {"i": 1, "g_arr16[1]": 5}, ["return"]).get("exact_width_guards") == ["int16_t"]
    assert _run(_unit("rdpt"), {"p[0].w": 1, "p[0].v": 2}, ["return"]).get("exact_width_guards") == ["int16_t"]


def test_a_downgraded_cell_drops_the_guard_too():
    # (review R83 I-R2-4) a cell the row's hidden input over the column cap downgrades says no basis of the derivation
    cap = suts._INPUT_COL_END - suts._INPUT_COL_START + 1
    unit = {"input_vars": [f"i{k}" for k in range(cap)], "output_vars": ["o"]}
    seq = {"inputs": {"hidden": 1}, "expected": {"o": 3},
           "expected_evidence": {"o": {"status": "derived", "exact_width_guards": ["int16_t"], "stubs": ["f"]}}}
    suts.render_row_io(unit, [seq])
    ev = seq["expected_evidence"]["o"]
    assert ev["status"] == "unknown" and "exact_width_guards" not in ev and "stubs" not in ev


def test_the_evidence_of_a_row_carries_the_guard(monkeypatch):
    # (review R83 M15) the record's names reach each derived cell through `apply_sequence_evidence`
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    seqs = extended_unit_sequences(_unit("delta", ["g_avg", "g_old"], ["g_ratio"]))
    cells = [s["expected_evidence"]["g_ratio"] for s in seqs
             if (s.get("expected_evidence") or {}).get("g_ratio", {}).get("status") == "derived"]
    assert cells and all(c["exact_width_guards"] == ["int16_t", "int32_t"] for c in cells)


def test_without_the_build_configuration_nothing_changes():
    scope = _scope(with_build=False)
    assert "int16_t" not in scope["types"] and scope["exact_width_guards"] == []
    assert scope["unresolved_types"]["int16_t"].startswith("typedef_conditional_or_conflicting")


def test_a_cast_to_the_exact_width_type_is_typed_and_its_difference_known():
    got = _run(_unit("delta"), {"g_avg": 300, "g_old": 250}, ["g_ratio"])
    assert got["outputs"]["g_ratio"]["value"] == 50 and not got.get("possible_undefined_behavior")
    assert _run(_unit("delta"), {"g_avg": 1000, "g_old": 250}, ["g_ratio"])["outputs"]["g_ratio"]["value"] == 100


# ── (2) multi-dimensional array elements ─────────────────────────────────────────────────────────────────────────────
def test_the_shape_of_a_multi_dimensional_array_is_in_the_scope():
    assert _scope()["array_shapes"]["g_tbl"]["dims"] == [5, 7, 7]
    assert _scope()["array_shapes"]["g_rows"]["dims"] == [2, 3]
    assert "g_tbl" not in _scope()["arrays"]   # still no modeled object
    assert "g_rowtab" not in _scope()["array_shapes"]   # (review R83 I4) `ROW g_rowtab[2][4]` has three dimensions


def test_an_in_bounds_element_write_is_no_possible_undefined_behaviour():
    for idx, expect in ((0, 2), (244, 2)):
        got = _run(_unit("set_tbl"), {"id": 1, "idx": idx, "v": 5}, ["return"])
        assert got["outputs"]["return"]["value"] == expect and not got.get("possible_undefined_behavior")
    assert _run(_unit("set_tbl"), {"id": 7, "idx": 3, "v": 5}, ["return"])["outputs"]["return"]["value"] == 0


def test_an_inner_index_past_its_dimension_is_undefined_and_an_unknown_one_may_be():
    assert "value" not in _run(_unit("get_rows"), {"i": 1, "j": 2}, ["return"])["outputs"]["return"]   # unmodeled
    assert not _run(_unit("get_rows"), {"i": 1, "j": 2}, ["return"]).get("possible_undefined_behavior")
    # `g_rows[0][3]` lies inside the object (element 3 of 6) but past its row: undefined (C11 J.2)
    for i, j in ((0, 3), (2, 0)):
        got = _run(_unit("get_rows"), {"i": i, "j": j}, ["return"])
        assert got["status"] == "unsupported" and got["reason"] == "undefined_behavior:array_index_out_of_bounds"
    assert "index_unknown" in _run(_unit("get_rows"), {"i": 1}, ["return"])["possible_undefined_behavior"]


def test_a_local_of_the_name_is_not_the_global_array():
    # the local 2x2x2 shadows the global 5x7x7: not bounded by the global's shape (it stays pointer arithmetic, as before)
    assert "pointer_arithmetic_untyped" in _run(_unit("shadow"), {}, ["return"])["possible_undefined_behavior"]


def test_a_sub_array_stays_pointer_arithmetic():
    # `g_rows[1]` (one index of two) decays to a pointer — no element access, as before R83
    assert "pointer_arithmetic_untyped" in _run(_unit("subrow"), {}, ["return"])["possible_undefined_behavior"]


def test_the_scenario_search_reaches_every_table_case_cleanly():
    found = sr.find_scenarios(_unit("set_tbl"), {"id": (0, 255), "idx": (0, 255), "v": (-32768, 32767)}, ["return"])
    assert found["report"]["reached_unclean_only"] == 0
    assert found["report"]["reached_clean"] == found["report"]["targets"]


# ── (1) the search's harness is the rows' ────────────────────────────────────────────────────────────────────────────
def test_a_pointer_member_named_by_itself_is_recognised():
    scope = _scope()
    assert _pointer_member_input(scope, "sec", "req[0].data")
    assert not _pointer_member_input(scope, "sec", "req[0].length")      # an integer member
    assert not _pointer_member_input(scope, "sec", "req[0].data[2]")     # an element (R82's buffer input)
    assert not _pointer_member_input(scope, "fan", "req[0].data")        # no such parameter


def test_a_member_of_unknown_type_gets_no_invented_value():
    # (review R83 I5) the rows leave it blank — the search does too
    bounds = {"g_sub": {"min": 0, "max": 255, "mid": 127}, "req[0].data": {"min": 0, "max": 255, "mid": 127}}
    ctx = {"input_vars": ["req[0].data", "g_sub"], "var_types": {"g_sub": "uint8_t"}, "unknown": ["req[0].data"],
           "var_bounds": bounds, "declared": ["g_sub"], "enum_sets": None}
    assert "req[0].data" not in suts._scenario_domains(_unit("sec"), ctx)   # an unknown type: no value
    assert "req[0].data" not in suts._scenario_domains(
        _unit("sec"), {**ctx, "unknown": [], "var_bounds": {"g_sub": bounds["g_sub"]}})   # no middle: no value
    ctx = {**ctx, "unknown": []}
    assert suts._scenario_domains(_unit("sec"), ctx)["req[0].data"] == {"values": [127], "harness_member": True}


def test_without_the_member_the_search_reaches_the_key_path_only_uncleanly():
    doms = {"g_sub": (0, 255), "g_len": (0, 65535), "read32() return": (0, 4294967295)}
    outs = ["resp[0].length", "resp[0].data[0]"]
    bare = sr.find_scenarios(_unit("sec"), doms, outs)["report"]
    assert bare["reached_unclean_only"] > 0
    held = sr.find_scenarios(_unit("sec"), {**doms, "req[0].data": {"values": [127], "harness_member": True}}, outs)
    assert held["report"]["reached_unclean_only"] == 0 and held["report"]["reached_clean"] == held["report"]["targets"]


def test_the_extended_rows_reach_the_key_path_and_count_the_member(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    # the SwUDS lists `req->data` — the input list names the member by itself (R81 normalization leaves it so)
    unit = _unit("sec", ["req[0].data", "resp[0].length", "g_sub", "g_len", "read32() return"],
                 ["resp[0].length", "resp[0].data"], {"req": "const MSG *", "resp": "MSG *"})
    normalize_pointer_parameters([unit])
    assert "req[0].data" in unit["input_vars"]
    seqs = extended_unit_sequences(unit)
    assert any(s["expected"].get("resp[0].length") == 2 for s in seqs)
    assert unit["scenario_rows"]["harness_member_inputs"] == 1
    assert suts.summarize_scenario_rows([unit])["harness_member_inputs"] == 1


def test_the_member_is_no_design_value_list_of_the_second_search(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    rng = {"req[0].data": {"type": "U8", "range": [0, 255]}, "g_sub": {"type": "U8", "range": [0, 3]},
           "g_len": {"type": "U16", "range": [0, 10]}}
    unit = _unit("sec", ["req[0].data", "resp[0].length", "g_sub", "g_len", "read32() return"],
                 ["resp[0].length", "resp[0].data"], {"req": "const MSG *", "resp": "MSG *"}, uds_param_info=rng)
    extended_unit_sequences(unit)
    assert unit["scenario_rows"]["harness_member_inputs"] == 1
    assert unit["scenario_rows"]["outside_design_value_sets"] == 0


# ── (4) stub returns told apart ──────────────────────────────────────────────────────────────────────────────────────
def _fan(monkeypatch, name="fan", stubs=("doors() return", "lvl_closed() return", "lvl_open() return"), **extra):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    return _unit(name, list(stubs), ["g_out"], **extra)


def test_the_extended_document_keeps_every_reference_row_unchanged(monkeypatch):
    # (review R83 C1) R75 — the extended profile holds the reference rows with the same values, stubs too
    ref = {s["strategy"]: s["inputs"] for s in generate_sequences(_fan(monkeypatch), 24, type_cache={})}
    ext = {s["strategy"]: s["inputs"] for s in extended_unit_sequences(_fan(monkeypatch))}
    # (the extended profile may add columns — R19/R82 — never change the reference's cells)
    assert ref and all({c: ext.get(k, {}).get(c) for c in v} == v for k, v in ref.items())


def test_a_companion_row_tells_the_two_levels_apart_on_the_inner_arm(monkeypatch):
    unit = _fan(monkeypatch)
    seqs = extended_unit_sequences(unit)
    rows = [s for s in seqs if s["strategy"].startswith(suts.STUB_APART_PREFIX)]
    assert rows and unit["stub_apart"]["rows"] == len(rows) and all(s["tc_profile"] == "extended" for s in rows)
    # on the `doors() == ON` arm the companion gives the two levels different values — which one ran shows at g_out
    on = [s for s in rows if s["inputs"]["doors() return"] == 1]
    assert on and all(s["inputs"]["lvl_closed() return"] != s["inputs"]["lvl_open() return"] for s in on)
    src = {s["seq_num"]: s for s in seqs}
    for s in rows:
        before = src[s["stub_apart"]["from_sequence"]]
        assert (before["expected"]["g_out"] != s["expected"]["g_out"]) == bool(s["stub_apart"]["outputs_changed"])
        assert {k for k in s["inputs"] if s["inputs"][k] != before["inputs"][k]} == set(s["stub_apart"]["moved"])
        assert s["expected_evidence"]["g_out"]["status"] == "derived"
    assert suts.is_extended_strategy(rows[0]["strategy"])
    assert len({tuple(sorted(s["inputs"].items())) for s in seqs}) == len(seqs)   # no duplicate row


def _counts_add_up(r):
    return r["sources"] == r["rows"] + r["uninformative"] + r["path_changed"] + r["underived"] + r["same_path"] \
        + r["cut_rows"]


def test_one_companion_per_path_and_the_counts_add_up(monkeypatch):
    unit = _fan(monkeypatch)
    seqs = extended_unit_sequences(unit)
    rows = [s for s in seqs if s["strategy"].startswith(suts.STUB_APART_PREFIX)]
    assert len(rows) == unit["stub_apart"]["rows"] == 2   # the open arm and the closed arm
    assert unit["stub_apart"]["same_path"] > 0 and _counts_add_up(unit["stub_apart"])
    assert suts.resolve_seq_gen_method(rows[0]["strategy"]) == suts.resolve_seq_gen_method("COND_COMB_0")


def test_stubs_no_path_calls_tell_nothing(monkeypatch):
    # (review R83 I-R2-1) `idle` calls doors() only: the two levels are never called — telling them apart shows nothing
    unit = _fan(monkeypatch, "idle")
    extended_unit_sequences(unit)
    assert unit["stub_apart"]["rows"] == 0 and unit["stub_apart"]["uninformative"] > 0
    assert _counts_add_up(unit["stub_apart"])


def test_the_path_includes_the_objects_a_row_writes(monkeypatch):
    # (review R83 M02) HDPDM01 `s_ApiOut_u8bit_DataUpdate_A`: every row calls the same stubs; the valid arm writes the
    #   outputs. Deleting `t = conv_b();` shows only on a valid-arm row whose two conversions differ
    unit = _fan(monkeypatch, "apiout", ("check() return", "conv_a() return", "conv_b() return"))
    unit["output_vars"] = ["g_angle", "g_vsup", "g_cnt"]
    seqs = extended_unit_sequences(unit)
    rows = [s for s in seqs if s["strategy"].startswith(suts.STUB_APART_PREFIX)]
    valid = [s for s in rows if s["inputs"]["check() return"] == 0xAA]
    assert valid and all(s["inputs"]["conv_a() return"] != s["inputs"]["conv_b() return"] for s in valid)


def _crafted(monkeypatch, name, stubs, rows, enum=()):
    unit = _fan(monkeypatch, name, stubs)
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    ctx["var_types"] = {**ctx["var_types"], **{k: suts._ENUM_TYPE for k in enum}}
    # an enum stub with its enumerators known has a domain — only the enum rule keeps it still
    ctx["enum_sets"] = {**(ctx.get("enum_sets") or unit.get("value_domains") or {}),
                        **{k: {"values": [0, 1, 2]} for k in enum}}
    seqs = [{"seq_num": i + 1, "strategy": strategy, "inputs": dict(inputs), "expected": {}}
            for i, (strategy, inputs) in enumerate(rows)]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    return unit["stub_apart"], seqs[len(rows):]


def test_a_moved_value_avoids_every_other_stubs_value(monkeypatch):
    # (review R83 M04) closed 0 · open 0 · doors 1: open may not move onto doors' 1
    # (the second row runs the open arm — so telling the closed level from the open one shows something)
    rep_, added = _crafted(monkeypatch, "fan", ("doors() return", "lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"doors() return": 1, "lvl_closed() return": 0, "lvl_open() return": 0}),
                            ("COND_COMB_1", {"doors() return": 0, "lvl_closed() return": 7, "lvl_open() return": 7})])
    first = [s for s in added if s["stub_apart"]["from_sequence"] == 1]
    assert len(first) == 1 and len(set(first[0]["inputs"].values())) == 3


def test_an_existing_row_is_not_added_again(monkeypatch):
    # (review R83 M05) the move of the first row is the second row
    rep_, added = _crafted(monkeypatch, "fan", ("doors() return", "lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"doors() return": 1, "lvl_closed() return": 0, "lvl_open() return": 0}),
                            ("COND_COMB_1", {"doors() return": 1, "lvl_closed() return": 0, "lvl_open() return": 2})])
    assert rep_["duplicates"] == 1 and not added


def test_a_move_that_changes_the_path_is_no_companion(monkeypatch):
    # (review R83 M08) `lvl_closed() == lvl_open()` decides which stub runs: told apart, they take the other arm
    rep_, added = _crafted(monkeypatch, "pick", ("lvl_closed() return", "lvl_open() return", "doors() return",
                                                 "lvl_step() return"),
                           [("COND_COMB_0", {"lvl_closed() return": 4, "lvl_open() return": 4, "doors() return": 4,
                                             "lvl_step() return": 4})])
    assert rep_["path_changed"] == 1 and not added and _counts_add_up(rep_)


def test_an_enum_stub_is_never_moved_even_when_it_collides(monkeypatch):
    # (review R83 M09) the enum is the second of the colliding group: were it a stub to move, it would move
    rep_, added = _crafted(monkeypatch, "moded", ("lvl_closed() return", "lvl_mode() return", "lvl_open() return"),
                           [("COND_COMB_0", {"lvl_closed() return": 0, "lvl_mode() return": 0, "lvl_open() return": 0}),
                            ("COND_COMB_1", {"lvl_closed() return": 3, "lvl_mode() return": 2, "lvl_open() return": 3})],
                           enum=("lvl_mode() return",))
    # (moving the enum 0 → 1 would keep the path — LV_LOW is no LV_HIGH — so only the exclusion keeps it)
    assert added and all("lvl_mode() return" not in s["stub_apart"]["moved"] for s in added)
    assert [s["inputs"]["lvl_mode() return"] for s in added if s["stub_apart"]["from_sequence"] == 1] == [0]


def test_a_fault_injection_or_out_of_design_row_is_no_source(monkeypatch):
    # (review R83 W-R2-1) a robustness row keeps its out-of-range point; a REQ row outside the design range is not valid
    stubs = ("doors() return", "lvl_closed() return", "lvl_open() return")
    rep_, added = _crafted(monkeypatch, "fan", stubs,
                           [("ROBUST_0", {"doors() return": 0, "lvl_closed() return": 0, "lvl_open() return": 0}),
                            ("BV_MIN_INV", {"doors() return": 0, "lvl_closed() return": 0, "lvl_open() return": 0})])
    assert rep_["sources"] == 0 and not added
    # g_sub 50 lies outside its design range 0..3 — the stubs collide inside theirs, but the row is no valid base
    unit = _fan(monkeypatch, "fan", ("g_sub", *stubs), uds_param_info={"g_sub": {"type": "U8", "range": [0, 3]}})
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"g_sub": 50, "doors() return": 0,
                                                                 "lvl_closed() return": 7, "lvl_open() return": 7},
             "expected": {}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert unit["stub_apart"]["sources"] == 0


def test_a_stub_value_outside_its_domain_is_no_collision(monkeypatch):
    # 300 is no U8 value: the two cells are not "the same value" to tell apart — nothing is even tried
    rep_, added = _crafted(monkeypatch, "fan", ("doors() return", "lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"doors() return": 0, "lvl_closed() return": 300, "lvl_open() return": 300})])
    assert rep_["no_value_stubs"] == 0 and rep_["sources"] == 0 and not added


def test_a_forking_source_makes_no_companion(monkeypatch):
    # (review R83 W-R3-1) `g_port` is volatile: the run takes both arms; 127 = 127 derives g_out, a move would not
    rep_, added = _crafted(monkeypatch, "forky", ("lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"lvl_closed() return": 127, "lvl_open() return": 127})])
    assert not added and rep_["underived"] == 1 and _counts_add_up(rep_)


def test_a_forked_source_is_no_source_even_when_its_outputs_stand(monkeypatch):
    # g_cnt forks on `g_port`; g_out stands on both arms and changes with the move — but the run's path is a union of two
    rep_, added = _crafted(monkeypatch, "forky2", ("lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"lvl_closed() return": 7, "lvl_open() return": 7})])
    assert not added and rep_["underived"] == 1


def test_a_move_that_loses_an_output_is_no_companion(monkeypatch):
    # open 7 → 1; moved off 7, g_out is g_hidden — no value: the companion's expectation would not stand
    rep_, added = _crafted(monkeypatch, "lossy", ("lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"lvl_closed() return": 7, "lvl_open() return": 7})])
    assert not added and rep_["underived"] == 1


def test_each_group_must_tell_something_by_itself(monkeypatch):
    # (review R83 W-R3-2) conv_a and the closed level are called, conv_b and the open level never: neither group shows
    #   anything though the union of the groups has two called stubs
    rep_, added = _crafted(monkeypatch, "twogroups",
                           ("conv_a() return", "conv_b() return", "lvl_closed() return", "lvl_open() return"),
                           [("COND_COMB_0", {"conv_a() return": 0, "conv_b() return": 0, "lvl_closed() return": 5,
                                             "lvl_open() return": 5})])
    assert not added and rep_["uninformative"] == 1


def test_a_group_this_path_calls_none_of_tells_nothing(monkeypatch):
    # g_sub 0 takes the doors() arm: conv_a and conv_b collide, both called only on the other arm
    stubs = ("g_sub", "conv_a() return", "conv_b() return", "doors() return")
    unit = _fan(monkeypatch, "bothcalls", stubs)
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"g_sub": 0, "conv_a() return": 3, "conv_b() return": 3,
                                                                 "doors() return": 9}, "expected": {}},
            {"seq_num": 2, "strategy": "COND_COMB_1", "inputs": {"g_sub": 1, "conv_a() return": 4, "conv_b() return": 5,
                                                                 "doors() return": 9}, "expected": {"g_out": 9},
             "expected_evidence": {"g_out": {"status": "derived", "stubs": ["conv_a", "conv_b"]}}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert len(seqs) == 2 and unit["stub_apart"]["uninformative"] == 1


def test_the_other_arm_known_from_a_rows_evidence_is_enough(monkeypatch):
    # the open arm runs only in a row with no collision — its evidence says which stubs it called
    stubs = ("doors() return", "lvl_closed() return", "lvl_open() return")
    unit = _fan(monkeypatch, "fan", stubs)
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"doors() return": 1, "lvl_closed() return": 0,
                                                                 "lvl_open() return": 0}, "expected": {}},
            {"seq_num": 2, "strategy": "COND_COMB_1", "inputs": {"doors() return": 0, "lvl_closed() return": 3,
                                                                 "lvl_open() return": 9}, "expected": {"g_out": 9},
             "expected_evidence": {"g_out": {"status": "derived", "stubs": ["doors", "lvl_open"]}}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert unit["stub_apart"]["rows"] == 1 and seqs[2]["stub_apart"]["from_sequence"] == 1
    del seqs[2]
    seqs[1]["expected_evidence"] = {}
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert unit["stub_apart"]["rows"] == 0 and unit["stub_apart"]["uninformative"] == 1


def test_the_companion_says_which_cells_its_source_left_blank(monkeypatch):
    stubs = ("doors() return", "lvl_closed() return", "lvl_open() return")
    unit = _fan(monkeypatch, "fan", ("g_cnt", *stubs))
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "MCDC_0", "inputs": {"doors() return": 1, "lvl_closed() return": 0,
                                                            "lvl_open() return": 0}, "expected": {}},
            {"seq_num": 2, "strategy": "MCDC_1", "inputs": {"doors() return": 0, "lvl_closed() return": 4,
                                                            "lvl_open() return": 4}, "expected": {}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    added = seqs[2:]
    assert added and all("비운 칸은 그대로 비움: g_cnt" in s["description"] and "g_cnt" not in s["inputs"] for s in added)


def test_the_source_cap_and_a_stub_with_no_value_left_are_counted(monkeypatch):
    stubs = ("doors() return", "lvl_closed() return", "lvl_open() return")
    rows = [("COND_COMB_%d" % i, {"doors() return": 0, "lvl_closed() return": i + 1, "lvl_open() return": i + 1})
            for i in range(suts.MAX_STUB_APART_SOURCES + 2)]
    rep_, _added = _crafted(monkeypatch, "fan", stubs, rows)
    assert rep_["sources"] == suts.MAX_STUB_APART_SOURCES and rep_["cut_sources"] == 2 and _counts_add_up(rep_)
    unit = _fan(monkeypatch, "fan", stubs, uds_param_info={"lvl_open() return": {"type": "U8", "range": [0, 1]}})
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"doors() return": 1, "lvl_closed() return": 0,
                                                                 "lvl_open() return": 0}, "expected": {}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert unit["stub_apart"]["no_value_stubs"] == 1 and unit["stub_apart"]["sources"] == 0   # 0 and 1 are taken


def test_a_stub_with_no_value_to_move_tells_nothing_and_displaces_no_real_companion(monkeypatch):
    # (review R83 W-R4-1) conv_a and the closed level range 0..1, conv_b 0..255: in row 1 conv_b moves (never called), the
    #   closed level has no value left and stays equal to conv_a — nothing told apart; row 2's companion must still come
    rng = {"conv_a() return": {"type": "U8", "range": [0, 1]}, "lvl_closed() return": {"type": "U8", "range": [0, 1]}}
    unit = _fan(monkeypatch, "twogroups", ("conv_a() return", "conv_b() return", "lvl_closed() return"),
                uds_param_info=rng)
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"conv_a() return": 0, "conv_b() return": 0,
                                                                 "lvl_closed() return": 0}, "expected": {}},
            {"seq_num": 2, "strategy": "COND_COMB_1", "inputs": {"conv_a() return": 0, "conv_b() return": 5,
                                                                 "lvl_closed() return": 0}, "expected": {}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    added = seqs[2:]
    assert [s["stub_apart"]["from_sequence"] for s in added] == [2] and unit["stub_apart"]["uninformative"] == 1
    assert added[0]["inputs"]["lvl_closed() return"] != added[0]["inputs"]["conv_a() return"]


def _sw20(monkeypatch, subs):
    unit = _fan(monkeypatch, "sw20", ("g_sub", "conv_a() return", "lvl_closed() return"))
    unit["output_vars"] = ["g_out"] + [f"g_sw{i}" for i in range(20)]
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": i + 1, "strategy": f"COND_COMB_{i}", "expected": {},
             "inputs": {"g_sub": g, "conv_a() return": 5, "lvl_closed() return": 5}} for i, g in enumerate(subs)]
    n = len(seqs)
    suts._append_stub_apart_rows(unit, seqs, ctx)
    return unit["stub_apart"], seqs, seqs[n:]


def test_the_moves_are_judged_against_their_own_source_across_chunks(monkeypatch):
    # (review R83 I-R4-1) 16 sources on the default arm fill the first chunk; the 4 case rows sit in the second —
    #   each companion keeps its own source's `g_sub` and path
    rep_, seqs, added = _sw20(monkeypatch, list(range(30, 46)) + [0, 1, 2, 3])
    assert rep_["rows"] == 5 and rep_["same_path"] == 15 and _counts_add_up(rep_)
    # (review R83 I-R5-4) each companion's change is on its own source's arm
    for s in added:
        g = s["inputs"]["g_sub"]
        assert s["stub_apart"]["outputs_changed"] == ([f"g_sw{g}"] if g < 20 else ["g_out"])


def test_the_row_cap_stops_inside_a_chunk(monkeypatch):
    rep_, _seqs, added = _sw20(monkeypatch, list(range(20)))
    assert len(added) == rep_["rows"] == suts.MAX_STUB_APART_ROWS and rep_["cut_rows"] == 20 - suts.MAX_STUB_APART_ROWS
    assert _counts_add_up(rep_)


def test_a_source_that_derives_nothing_is_no_source(monkeypatch):
    # g_hidden is no input: with open 7 the `?:` reads it — the source derives nothing about g_out (g_cnt is not stated)
    unit = _fan(monkeypatch, "gain", ("lvl_closed() return", "lvl_open() return"))
    unit["output_vars"] = ["g_out"]
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"lvl_closed() return": 7, "lvl_open() return": 7},
             "expected": {}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert unit["stub_apart"]["underived"] == 1 and len(seqs) == 1


def _gain(monkeypatch, name, outputs):
    unit = _fan(monkeypatch, name, ("lvl_closed() return", "lvl_open() return"))
    unit["output_vars"] = list(outputs)
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": 1, "strategy": "COND_COMB_0", "inputs": {"lvl_closed() return": 7, "lvl_open() return": 7},
             "expected": {}}]
    suts._append_stub_apart_rows(unit, seqs, ctx)
    return unit["stub_apart"], seqs[1:]


def test_a_written_value_turning_known_is_another_path(monkeypatch):
    # (review R83 I-R4-3) open 7 → 8 flips `?:`: g_out is written on both arms, unknown (g_hidden) then 1
    rep_, added = _gain(monkeypatch, "gain", ["g_out", "g_cnt"])
    assert rep_["path_changed"] == 1 and not added


def test_an_output_the_move_gains_counts_as_changed(monkeypatch):
    # (review R83 I-R4-3) the return value — no written object — is unknown at the source and 1 after: gained, not lost
    rep_, added = _gain(monkeypatch, "gainret", ["return", "g_cnt"])
    assert rep_["rows"] == 1 and "return" in added[0]["stub_apart"]["outputs_changed"]


@pytest.mark.parametrize("broken_call", [1, 2])   # the source runs · the moves
def test_a_failed_written_record_is_underived(monkeypatch, broken_call):
    # (review R83 I-R4-5) with no record of the written objects the path key would be the stubs alone — on either side
    from generators import c_source_oracle as cso
    real, calls = cso.evaluate_outputs, []

    def broken(unit, vectors, outputs, written=False):
        calls.append(1)
        out = real(unit, vectors, outputs, written=written)
        return [{**r, "written": {}, "written_error": "oracle_exception:X"} for r in out] if len(calls) == broken_call \
            else out
    stubs = ("doors() return", "lvl_closed() return", "lvl_open() return")
    rows = [("COND_COMB_0", {"doors() return": 1, "lvl_closed() return": 0, "lvl_open() return": 0}),
            ("COND_COMB_1", {"doors() return": 0, "lvl_closed() return": 7, "lvl_open() return": 7})]
    unit = _fan(monkeypatch, "fan", stubs)
    generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    ctx = unit.pop("_boundary_ctx")
    seqs = [{"seq_num": i + 1, "strategy": st, "inputs": dict(inp), "expected": {}} for i, (st, inp) in enumerate(rows)]
    monkeypatch.setattr(cso, "evaluate_outputs", broken)
    suts._append_stub_apart_rows(unit, seqs, ctx)
    assert len(seqs) == 2 and unit["stub_apart"]["underived"] == 2


def test_the_functions_own_return_and_parameter_types_count():
    # (review R83 W-R5-1) the body names neither int16_t nor an object of it — the signature does
    assert _run(_unit("retw"), {"x": 5}, ["return"])["exact_width_guards"] == ["int16_t"]
    assert _run(_unit("parw"), {"v": 5}, ["g_out"])["exact_width_guards"] == ["int16_t"]
    assert "exact_width_guards" not in _run(_unit("unusedw"), {"v": 5}, ["g_out"])   # a parameter the body never names


def test_the_parameter_must_be_used_in_the_body(monkeypatch):
    # (review R83 I-R4-2a) the declarator names `p` — the body does not use it
    assert "exact_width_guards" not in _run(_unit("nouse"), {"p[0].v": 1}, ["return"])


def test_a_failing_pass_costs_only_its_rows(monkeypatch):
    # (review R83 M11) the failure comes after a companion was added: it goes too
    real, calls = suts._run_path, []

    def boom(r):
        calls.append(1)
        if len(calls) > 2:
            raise RuntimeError("x")
        return real(r)
    monkeypatch.setattr(suts, "_run_path", boom)
    unit = _fan(monkeypatch)
    seqs = extended_unit_sequences(unit)
    assert unit["stub_apart"] == {"error": "RuntimeError", "rows": 0}
    assert not any(s["strategy"].startswith(suts.STUB_APART_PREFIX) for s in seqs)
    assert suts.summarize_stub_apart([unit])["errors"] == 1


def test_a_design_value_list_keeps_its_values(monkeypatch):
    # (review R83 W2) the step level's design list is {0, 5, 15}: a companion takes a member, never a value outside it
    unit = _fan(monkeypatch, "stepped", ("doors() return", "lvl_closed() return", "lvl_step() return"),
                uds_param_info={"lvl_step() return": {"type": "U8", "values": [0, 5, 15], "range_text": "0, 5, 15"}})
    seqs = extended_unit_sequences(unit)
    rows = [s for s in seqs if s["strategy"].startswith(suts.STUB_APART_PREFIX)]
    moved = [s["stub_apart"]["moved"]["lvl_step() return"][1] for s in rows if "lvl_step() return" in s["stub_apart"]["moved"]]
    assert moved and all(x in (0, 5, 15) for x in moved)


def test_the_apart_value_stays_in_the_domain_and_off_the_taken_values():
    assert suts._apart_value((0, 255), 127, 1, {127}) == 128
    assert suts._apart_value((0, 255), 255, 1, {255}) == 254
    assert suts._apart_value((0, 1), 0, 1, {0, 1}) is None
    assert suts._apart_value([0, 5, 15], 0, 1, {0}) == 5
    assert suts._apart_value([0, 5, 15], 15, 2, {15, 0}) == 5
    assert suts._apart_value(None, 3, 1, set()) is None


def test_an_enum_stub_is_never_moved(monkeypatch):
    unit = _fan(monkeypatch, "moded", ("lvl_closed() return", "lvl_mode() return", "lvl_open() return"))
    unit["value_domains"] = {"lvl_mode() return": {"values": [0, 1, 2], "type": "LV_T"}}
    seqs = extended_unit_sequences(unit)
    rows = [s for s in seqs if s["strategy"].startswith(suts.STUB_APART_PREFIX)]
    assert rows and all("lvl_mode() return" not in s["stub_apart"]["moved"] for s in rows)


def test_the_companions_are_disclosed():
    from report_gen.generation_disclosures import build_disclosures
    sa = {**suts.summarize_stub_apart([{"stub_apart": {"stubs": 3, "sources": 4, "rows": 2, "uninformative": 1,
                                                       "same_path": 1}}])}
    note = {i["key"]: i for i in build_disclosures("suts", {"stub_apart": sa})}["suts_stub_apart_rows"]
    assert note["value"].startswith("2행") and "기존 행은 그대로" in note["note"]
    assert "suts_stub_apart_rows" not in {i["key"] for i in build_disclosures("suts", {"stub_apart": suts.summarize_stub_apart([])})}


def test_the_harness_member_and_the_cap_are_in_the_scenario_sentence():
    from report_gen.generation_disclosures import build_disclosures
    sc = {**suts.summarize_scenario_rows([]), "searched": 1, "targets": 4, "harness_member_inputs": 2,
          "conditions_outcome_only": 1}
    note = {i["key"]: i for i in build_disclosures("suts", {"scenario_rows": sc})}["suts_scenario_rows"]["note"]
    assert "포인터 멤버" in note and "64 개를 넘어" in note


# ── (5) decisions of more than 16 conditions ─────────────────────────────────────────────────────────────────────────
def _big_domains():
    return {f"g_{c}": (0, 255) for c in "abcdefghijklmnopqrst"}


def test_a_decision_of_twenty_conditions_gets_its_boundaries(monkeypatch):
    unit = _unit("big")
    found = sr.find_scenarios(unit, _big_domains(), ["g_out"])
    assert found["report"]["conditions_outcome_only"] == 0
    assert any(r["inputs"].get("g_s") == 8 and r.get("target_kind") == "boundary" for r in found["rows"])
    monkeypatch.setattr(sr, "MAX_ATOMS", 16)
    capped = sr.find_scenarios(unit, _big_domains(), ["g_out"])
    assert capped["report"]["conditions_outcome_only"] == 1
    assert not any(r["inputs"].get("g_s") == 8 and r.get("target_kind") == "boundary" for r in capped["rows"])


def test_the_sub_condition_cap_is_in_the_summary():
    assert suts.summarize_scenario_rows([])["atoms_cap"] == sr.MAX_ATOMS == 64
