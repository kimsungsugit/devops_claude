"""R82 — what the PV mutants only the reference killed after R81 needed (45, KJPDS02_PV extended).

(1) The scenario search names the inputs a climb needs when it stops at a guard that reads an object no input list names
(`s_DoorState_AutoStop_Check`: the 5th of 8 ANDed conditions reads `u8g_DoorPreCtrl_PlayProtectLvl`) — the objects the
guard names itself.
(2) A write no move can expose — the value it replaces is never known because the object is no input — names the object
(`s_MotorSpeedModeSelection_RearSet`: `s32s_StartSpeed = …`; the reference sets its value before the call) when an
expected column observes it, after the reads.
(3) Harness buffers: a pointer parameter's scalar pointee is a buffer (`pData[1]`), a one-level pointer member of a harness
object the row names points to a buffer of its own (`RespMsg->data[0]`), a callee writing through such an argument stays
inside it; a write that may rebind the member ends that (review C1), a write past what the row names may reach anything.
(4) `(T)(d)[k]` — tree-sitter's subscript of a cast-call — reads as C binds it, `(T)((d)[k])`.
(5) The search's candidate values include constants a function-like macro compares a buffer element with, masked
(`LINTP_IS_CF(d)` → `((d)[0] & 0xF0u) == 0x20u`).
(6) Columns of one buffer are capped (`_BUFFER_ELEMENTS_MAX`), first elements first."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import suts
from generators.c_source_oracle import evaluate_outputs
from generators.mcdc_design import _pointee_input
from generators.suts import extended_unit_sequences, normalize_pointer_parameters

ROOT = os.path.join(os.sep, "proj")
HEADER = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef unsigned long U32;
typedef struct { U8 *data; U16 length; U8 **pp; U8 (*fp)(U8); } MSG;
#define ON 1U
#define OFF 0U
#define FRAME_CF 0x20u
#define IS_CF(d) (((d)[0] & 0xF0u) == FRAME_CF)
#define GETLEN(d) ((U16)((U16)((U16)(((U16)(d)[0] & 0x0Fu) << 8u)) | (U16)((d)[1])))
void copy_bytes(U8 *dst, const U8 *src, U32 n);
void ext_fn(void);
void take(MSG *m);
#define GET_FLAG() ((U8)(g_hw & 0x01U))
#define PP_ACTIVATED ((U8)(0x04U))
#define ERR_BITS ((U16)(0x87E7))
#define STS_NORMAL ((U16)(0x0000))
typedef struct { U8 data[16]; U8 n; } CTX;
typedef struct { U8 a; U8 b; } ST;
typedef enum { EN_IDLE = 0, EN_RUN = 2, EN_STOP = 3 } EN_T;
"""
SRC = """#include "c.h"
U8 g_state;
U8 g_hold;
U8 g_prehold;
U8 g_e2e;
U8 g_lin;
U8 g_pp;
U16 g_sys;
U8 g_heat;
U8 g_heathold;
S16 g_pos;
S16 g_full;
S16 s32s_Start;
U8 g_out;
U16 g_len;
void door(void)
{
    if (g_state == 0U)
    {
        g_state = 0U;
    }
    else
    {
        if (((g_hold == ON) || (g_prehold == ON))
            && (g_e2e == OFF)
            && (g_lin == OFF)
            && (g_pp != PP_ACTIVATED)
            && ((g_sys & ERR_BITS) == STS_NORMAL)
            && (g_heat == OFF)
            && (g_heathold == OFF))
        {
            g_state = 0x0FU;
        }
        else if (g_pos >= g_full)
        {
            g_state = 0x02U;
        }
        else
        {
            g_state = 0x04U;
        }
    }
}
void setall(U8 d)
{
    s32s_Start = (S16)d;
    g_out = (U8)(d + 1U);
}
void setloc(U8 d)
{
    U8 t;
    t = (U8)(d + 2U);
    g_out = t;
}
U8 parse(const U8 *pData)
{
    U8 r = 0U;
    if (IS_CF(pData)) { r = 2U; } else { g_len = GETLEN(pData); if (g_len > 6U) { r = 3U; } }
    return r;
}
void respond(MSG *msg, U8 code)
{
    msg->data[0] = code;
    msg->length = 1U;
}
void fill(MSG *msg, const U8 *src)
{
    msg->length = 7U;
    copy_bytes(msg->data, src, 5U);
}
void clear(U8 *buf, U8 n)
{
    U8 i;
    for (i = 0U; i < n; i++) { buf[i] = 0U; }
}
U16 castsub(const U8 *d)
{
    return (U16)(d)[1];
}
U8 g_buf[4];
ST g_st;
U8 g_arr[3];
void redirect(MSG *msg)
{
    msg->data = g_buf;
    msg->data[0] = 5U;
}
void wholemsg(MSG *msg, const MSG *tmpl)
{
    *msg = *tmpl;
    msg->data[0] = 6U;
}
void ctxclear(CTX *ctx)
{
    U8 i;
    for (i = 0U; i < 16U; i++) { ctx->data[i] = 0U; }
    ctx->n = 0U;
}
void stw(U8 d)
{
    g_st.a = d;
    g_arr[0U] = (U8)(d + 1U);
}
U8 leftmask(const U8 *pData)
{
    U8 r = 0U;
    if ((0xF0u & pData[0]) == 0x10u) { r = 1U; }
    return r;
}
U8 *g_ptr;
U8 g_x;
U8 g_flt_out;
float g_flt;
void unkptr2(MSG *msg)
{
    *g_ptr = 1U;
    msg->data[0] = 5U;
    g_x = g_buf[0];
}
void unkcall(MSG *msg)
{
    ext_fn();
    msg->data[0] = 5U;
    g_x = g_buf[0];
}
void viacallee(MSG *msg)
{
    take(msg);
    msg->data[0] = 5U;
}
void flw(U8 d)
{
    g_flt_out = (U8)g_flt;
    g_out = d;
}
void fill10(MSG *msg)
{
    U8 i;
    for (i = 0U; i < 12U; i++) { msg->data[i] = (U8)(i + 1U); }
}
volatile U8 g_vol;
U8 g_idx;
void tailunk(MSG *msg)
{
    g_arr[0] = 3U;
    msg->data[0] = 1U;
    msg->data[1] = g_vol;
}
void iu(U8 *p)
{
    g_arr[0] = 3U;
    p[g_idx] = 1U;
}
void nd(MSG *msg, U8 c)
{
    msg->length = c;
}
void wpg(U8 *p, U8 d)
{
    g_arr[1] = d;
    p[3] = 1U;
    g_out = d;
}
U8 g_wm;
void wmid(U8 d)
{
    g_wm = 129U;
    g_out = d;
}
EN_T g_en;
void enw(U8 d)
{
    g_en = EN_RUN;
    g_out = d;
}
U8 g_b;
void both(U8 d)
{
    if (d > 3U) { g_b = 0U; } else { g_b = 1U; }
    g_out = d;
}
U8 g_wm2;
void wm2(U8 d, U8 e)
{
    if (d > 10U) { g_wm2 = 130U; } else { g_wm2 = 127U; }
    if ((d > 100U) && (e < 20U)) { g_out = 1U; } else { g_out = 0U; }
}
U8 g_fl;
U8 g_hw;
void ovw(U8 d)
{
    g_fl = GET_FLAG();
    if (g_fl == ON) { g_out = d; } else { g_out = 0U; }
}
void ovb(U8 d)
{
    g_fl = (U8)(g_hw >> 1U);
    if (g_fl > 10U) { g_out = d; } else { g_out = 0U; }
}
U8 g_mode;
void hid(U8 d)
{
    if (g_mode > 30U) { if (g_x == 1U) { g_out = 7U; } }
    g_x = d;
}
U8 g_y;
void ovy(U8 d)
{
    g_fl = GET_FLAG();
    g_y = g_fl;
    g_out = d;
}
void ovsw(U8 d)
{
    g_fl = GET_FLAG();
    switch (g_fl) { case 1U: g_out = d; break; default: g_out = 0U; break; }
}
void capx(U8 d)
{
    g_wm = 129U;
    g_out = (U8)(d + g_x);
}
void setp(U8 *out, U8 d)
{
    *out = (U8)(d + 3U);
}
U16 sum12(const U8 *p)
{
    U16 s = 0U;
    U8 i;
    for (i = 0U; i < 12U; i++) { s = (U16)(s + p[i]); }
    return s;
}
"""
STD = """#include "c.h"
void copy_bytes(U8 *dst, const U8 *src, U32 n) { U32 i; for (i = 0U; i < n; i++) { dst[i] = src[i]; } }
void take(MSG *m) { m->data = 0; }
"""
PATH = os.path.join(ROOT, "u.c")
_CACHE = {}


def _scope():
    if not _CACHE:
        ctx = cpc.build_project_context({os.path.join(ROOT, "c.h"): HEADER, PATH: SRC, os.path.join(ROOT, "std.c"): STD})
        _CACHE["ctx"] = ctx
        _CACHE["scope"] = cpc.build_scopes(ctx, [PATH])[PATH]
    return _CACHE["scope"]


def _unit(name, ins, outs, ptypes=None, **extra):
    return {"name": name, "fid": "F_" + name, "source_text": SRC, "source_path": PATH, "source_text_complete": True,
            "project_scope": _scope(), "input_vars": list(ins), "output_vars": list(outs),
            "param_types": dict(ptypes or {}), "uds_param_info": {}, **extra}


def _run(unit, inputs, outs):
    return evaluate_outputs(unit, [inputs], [outs], written=True)[0]


TYPES = {"g_state": "U8", "g_hold": "U8", "g_prehold": "U8", "g_e2e": "U8", "g_lin": "U8", "g_pp": "U8", "g_sys": "U16",
         "g_heat": "U8", "g_heathold": "U8", "g_pos": "S16", "g_full": "S16", "s32s_Start": "S16", "g_out": "U8",
         "g_len": "U16", "g_st.a": "U8", "g_st.b": "U8", "g_x": "U8", "g_flt_out": "U8", "g_wm": "U8", "g_b": "U8", "g_wm2": "U8"}


# ── (3) harness buffers ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_struct_layout_keeps_one_level_pointer_members_to_integers():
    layout = _scope()["pointee_types"]["MSG"]
    assert set(layout["pointers"]) == {".data"}   # not `U8 **pp`, not a function pointer
    assert ".length" in layout["members"]


def test_a_scalar_pointee_is_a_buffer_of_the_elements_the_row_names():
    unit = _unit("castsub", [], [])
    got = _run(unit, {"d[0]": 0x12, "d[1]": 0x34}, ["return"])
    assert got["outputs"]["return"]["value"] == 0x34
    assert _pointee_input(_scope(), "castsub", "d[1]")[1] == "U8"


def test_a_pointer_member_points_to_a_harness_buffer():
    got = _run(_unit("respond", [], []), {"code": 7, "msg[0].length": 0}, ["msg[0].data[0]", "msg[0].length"])
    assert got["outputs"]["msg[0].data[0]"]["value"] == 7 and got["outputs"]["msg[0].length"]["value"] == 1
    assert not got.get("possible_undefined_behavior")
    assert got["written"]["msg[0].data[0]"] is True
    assert _pointee_input(_scope(), "respond", "msg[0].data[3]")[1] == "U8"


def test_a_callee_writing_through_a_buffer_argument_stays_inside_it():
    # `copy_bytes(msg->data, …)` runs as its write closure: it writes the buffer, not the struct holding the pointer —
    #   the value the row set in the buffer is gone (review R82 W6: the test set none, so a dropped havoc passed)
    got = _run(_unit("fill", [], []), {"msg[0].length": 0, "msg[0].data[0]": 9, "src[0]": 1},
               ["msg[0].length", "msg[0].data[0]"])
    assert got["outputs"]["msg[0].length"]["value"] == 7
    assert "value" not in got["outputs"]["msg[0].data[0]"]


def test_a_rebound_pointer_member_no_longer_points_to_the_harness_buffer():
    # (review R82 C1) `msg->data = g_buf; msg->data[0] = 5U` writes g_buf[0]: the model must not say g_buf[0] is the
    #   row's 1 (nor msg[0].data[0] 5 in a buffer the member left)
    got = _run(_unit("redirect", [], []), {"msg[0].data[0]": 0, "g_buf[0]": 1}, ["g_buf[0]", "msg[0].data[0]"])
    assert "value" not in got["outputs"]["g_buf[0]"] and "value" not in got["outputs"]["msg[0].data[0]"]
    got = _run(_unit("wholemsg", [], []), {"msg[0].data[0]": 0, "tmpl[0].length": 3}, ["msg[0].data[0]", "msg[0].length"])
    assert "value" not in got["outputs"]["msg[0].data[0]"]   # `*msg = *tmpl` copied tmpl's data pointer


def test_a_pointer_member_the_row_does_not_name_is_no_harness_buffer():
    # (review R82 W1) the row sets `msg[0].length` and observes it only: the harness leaves `msg->data` unset — a write
    #   through it is through an unknown pointer, as before R82
    got = _run(_unit("respond", [], []), {"code": 7, "msg[0].length": 0}, ["msg[0].length"])
    assert "pointer_arithmetic_untyped" in got["possible_undefined_behavior"]
    assert got["outputs"]["msg[0].length"]["value"] == 1   # written after the unknown write — known again
    named = _run(_unit("respond", [], []), {"code": 7, "msg[0].length": 0}, ["msg[0].length", "msg[0].data[0]"])
    assert not named["possible_undefined_behavior"] and named["outputs"]["msg[0].data[0]"]["value"] == 7


def test_a_write_past_the_elements_the_row_names_is_said():
    # (review R82 W1) the harness allocates what the row names: buf[0..1] — `clear(buf, 4)` writes past them
    past = _run(_unit("clear", [], []), {"buf[0]": 1, "buf[1]": 1, "n": 4}, ["buf[0]", "buf[1]"])
    assert "harness_buffer_write_beyond_row" in past["possible_undefined_behavior"]
    inside = _run(_unit("clear", [], []), {"buf[0]": 1, "buf[1]": 1, "n": 2}, ["buf[0]", "buf[1]"])
    assert "harness_buffer_write_beyond_row" not in inside["possible_undefined_behavior"]
    assert inside["outputs"]["buf[1]"]["value"] == 0


# ── (4) `(T)(d)[k]` ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_cast_of_a_parenthesized_buffer_element_reads_the_element():
    got = _run(_unit("parse", [], []), {"pData[0]": 0x12, "pData[1]": 0x34}, ["g_len", "return"])
    assert got["outputs"]["g_len"]["value"] == 0x234 and got["outputs"]["return"]["value"] == 3


# ── (6) buffer columns ──────────────────────────────────────────────────────────────────────────────────────────────
def test_a_loop_over_a_buffer_adds_at_most_the_first_elements(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("clear", ["buf", "n"], ["buf"], {"buf": "U8 *", "n": "U8"})
    normalize_pointer_parameters([unit])
    extended_unit_sequences(unit)
    elements = [o for o in unit["output_vars"] if o.startswith("buf[")]
    assert elements == [f"buf[{k}]" for k in range(len(elements))] and len(elements) <= suts._BUFFER_ELEMENTS_MAX
    assert sum(1 for i in unit["input_vars"] if i.startswith("buf[")) <= suts._BUFFER_ELEMENTS_MAX


def test_a_fixed_length_member_array_is_no_harness_buffer_and_keeps_every_element(monkeypatch):
    # (review R82 C2) `ctx->data[16]` is a member array of its own length (R40/R81 — `s_sha256_*`'s bitlen bytes at
    #   `ctx[0].data[56..63]`): the buffer cap must not cut it
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("ctxclear", ["ctx"], ["ctx"], {"ctx": "CTX *"})
    normalize_pointer_parameters([unit])
    extended_unit_sequences(unit)
    assert {f"ctx[0].data[{k}]" for k in range(16)} <= set(unit["output_vars"])
    assert "buffer_elements_full" not in (unit["source_written_outputs"].get("not_added") or {}).values()
    assert suts._harness_buffer_base(unit, _scope(), "ctx[0].data[3]") is None
    assert suts._harness_buffer_base(unit, _scope(), "msg[0].data[3]") is None   # not this unit's parameter
    resp = _unit("respond", [], [])
    assert suts._harness_buffer_base(resp, _scope(), "msg[0].data[3]") == ("msg[0].data", 3)


def test_the_buffer_cap_is_counted_and_disclosed_not_silent():
    from report_gen.generation_disclosures import build_disclosures
    cut = {"added": {}, "not_added": {"buf[8]": "buffer_elements_full"}, "rounds": 1, "remaining": {}}
    units = [{"source_read_inputs": cut, "source_written_outputs": {**cut, "dropped": {}}}, {"name": "none"}]
    sr, sw = suts.summarize_source_read_inputs(units), suts.summarize_source_written_outputs(units)
    assert sr["units_buffer_elements_full"] == 1 and sw["units_buffer_elements_full"] == 1
    assert sr["buffer_elements_max"] == sw["buffer_elements_max"] == suts._BUFFER_ELEMENTS_MAX
    items = {i["key"]: i for i in build_disclosures("suts", {"source_read_inputs": sr, "source_written_outputs": sw})}
    for key in ("suts_source_read_inputs", "suts_source_written_outputs"):
        assert f"원소 열 상한(버퍼 하나에 앞 원소부터 {suts._BUFFER_ELEMENTS_MAX}개)에 막힌 unit 1" in items[key]["note"], key
        assert items[key]["tone"] == "warning", key
    quiet = {i["key"]: i for i in build_disclosures("suts", {"source_read_inputs": {**sr, "units_buffer_elements_full": 0}})}
    assert "원소 열 상한" not in quiet["suts_source_read_inputs"]["note"]


# ── (1) (5) the search names what it needs; macro comparisons give candidates ───────────────────────────────────────
def test_a_climb_stopped_at_a_guard_names_the_unlisted_object_it_reads(monkeypatch):
    # PV `s_DoorState_AutoStop_Check` in small: the design lists every object but `g_pp` (the 4th of 7 ANDed conditions);
    #   no run of the search ever evaluates the decision undetermined (another condition is false whenever `g_pp` is read)
    #   — no path touches the active-hold statement, every climb stops at that guard. HEAD named nothing: 0 such rows
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    ins = ["g_sys", "g_state", "g_hold", "g_heat", "g_heathold", "g_full", "g_pos", "g_lin", "g_e2e", "g_prehold"]
    rng = {"g_sys": [0, 34791], "g_state": [0, 15], "g_full": [-32768, 32767], "g_pos": [-32768, 32767]}
    unit = _unit("door", ins, ["g_state"], uds_param_info={n: {"range": rng.get(n, [0, 1])} for n in ins})
    seqs = extended_unit_sequences(unit)
    added = unit["source_read_inputs"]["added"]
    assert added["g_pp"]["scenario_targets"] >= 1 and added["g_pp"]["read_on_model"] is True
    assert unit["scenario_rows"]["local_best"] == 0
    assert any(s["expected"].get("g_state") == 0x0F for s in seqs)


def test_a_buffer_element_compared_in_a_macro_is_a_candidate_and_needed_reads_follow(monkeypatch):
    # `IS_CF(pData)` compares `(pData)[0] & 0xF0u` with 0x20 inside a macro; the else arm reads `pData[1]` through
    #   `GETLEN` and decides `g_len > 6U` on it — the search reaches both arms and R19 adds `pData[1]`
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("parse", ["pData"], ["return"], {"pData": "const U8 *"})
    normalize_pointer_parameters([unit])
    seqs = extended_unit_sequences(unit)
    assert "pData[1]" in unit["input_vars"]
    returns = {s["expected"].get("return") for s in seqs}
    assert {2, 3} <= returns


# ── (2) a write's prior value ───────────────────────────────────────────────────────────────────────────────────────
def test_an_output_written_on_every_path_gets_its_prior_value_as_an_input(monkeypatch):
    # deleting `s32s_Start = …` leaves the old value: only a row that sets a different one tells
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("setall", ["d"], ["s32s_Start", "g_out"], {"d": "U8"})
    seqs = extended_unit_sequences(unit)
    assert "s32s_Start" in unit["input_vars"]
    rows = [s for s in seqs if isinstance(s["inputs"].get("s32s_Start"), int) and isinstance(s["inputs"].get("d"), int)
            and 0 <= s["inputs"]["d"] <= 255]
    assert any(s["inputs"]["s32s_Start"] != s["inputs"]["d"] for s in rows)


def test_a_prior_value_is_no_read_no_input_gap_and_moves_in_no_one_at_a_time_row(monkeypatch):
    # the function writes `s32s_Start` and `g_out` — it reads neither: recorded apart from the reads the search needed,
    #   no 'input list gap' finding (the design's input list misses nothing), no OAT row (the value is overwritten)
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("setall", ["d"], ["s32s_Start", "g_out"], {"d": "U8"})
    seqs = extended_unit_sequences(unit)
    rep = unit["scenario_rows"]   # the last search's: with both inputs, no write is left whose prior value is unknown
    assert rep["prior_value_needed"] == {} and rep["expose_prior_value_needed"] == 0 and not rep["needed_inputs"]
    added = unit["source_read_inputs"]["added"]
    for n in ("s32s_Start", "g_out"):
        assert added[n]["prior_value_for_write"] >= 1 and added[n]["read_on_model"] is False, n
        assert "scenario_targets" not in added[n], n
    assert not set(suts.input_list_gaps(unit, seqs)) & {"s32s_Start", "g_out"}
    moved = {s["strategy"] for s in seqs if s["strategy"].startswith("OAT_")}
    assert not moved   # `d` is the only input read: BV_MIN / BV_MAX already move it alone
    sr = suts.summarize_source_read_inputs([unit])
    assert sr["names_added_for_write_prior_value"] == 2 and sr["names_added_for_unwritten_outputs"] == 0
    from report_gen.generation_disclosures import build_disclosures
    note = {i["key"]: i for i in build_disclosures("suts", {"source_read_inputs": sr})}["suts_source_read_inputs"]["note"]
    assert "그중 2 이름은 함수가 쓰는 객체의 쓰기 전 값이다" in note


def test_a_local_written_with_no_known_prior_value_is_no_input_to_add(monkeypatch):
    # `t` is uninitialized before `t = …`: the search cannot expose that write either, but `t` is no object a test sets —
    #   it does not reach the input completion ('not added' reasons stay the program objects')
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("setloc", ["d"], ["g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]
    assert "t" not in rec["not_added"] and "t" not in rec["added"]
    assert "t" not in (rec.get("prior_value_not_added") or {})   # (review R82 W-R2-5) nor among the prior values left
    assert "g_out" in rec["added"]


def test_a_struct_member_and_a_misra_index_are_named_as_prior_values(monkeypatch):
    # (review R82 W3) `g_st.a = d` is an object of its own name in the scope; `g_arr[0U]` is the column `g_arr[0]`
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("stw", ["d"], ["g_st.a", "g_arr[0]"], {"d": "U8"})
    extended_unit_sequences(unit)
    added = unit["source_read_inputs"]["added"]
    assert added["g_st.a"]["prior_value_for_write"] >= 1 and added["g_arr[0]"]["prior_value_for_write"] >= 1


def test_a_mask_on_the_left_of_a_masked_comparison_gives_a_candidate_too(monkeypatch):
    # (review R82 I7) `(0xF0u & pData[0]) == 0x10u`: no design value has a high nibble of 1 — only the candidate does
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("leftmask", ["pData"], ["return"], {"pData": "const U8 *"})
    normalize_pointer_parameters([unit])
    seqs = extended_unit_sequences(unit)
    assert any(s["expected"].get("return") == 1 for s in seqs)


def test_the_normalization_names_no_buffer_element_in_either_profile():
    # (review R82 W2) a struct pointee input becomes the members the body reaches — `msg[0].length` — not the elements of
    #   its pointer member's buffer (`msg[0].data[0]`): the reference-format profile keeps the columns it had before R82
    unit = _unit("respond", ["msg", "code"], ["msg"], {"msg": "MSG *", "code": "U8"})
    normalize_pointer_parameters([unit])
    assert "msg[0].length" in unit["input_vars"]
    assert not any(n.startswith("msg[0].data") for n in unit["input_vars"])
    assert _pointee_input(_scope(), "respond", "msg[0].data[0]", buffers=False) is None


# ── review round 2 ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_unknown_pointer_write_or_call_or_callee_rebinds_the_members():
    # (review R82 W-R2-4) every place a pointer member may be rewritten: `*g_ptr = …` and an undefined `ext_fn()` may
    #   reach the harness object (it escaped); `take(msg)` sets `m->data = 0` — the buffer is not what `msg->data` is
    for fn in ("unkptr2", "unkcall"):
        got = _run(_unit(fn, [], []), {"msg[0].data[0]": 1, "g_buf[0]": 7}, ["msg[0].data[0]"])
        assert "value" not in got["outputs"]["msg[0].data[0]"], fn
    got = _run(_unit("viacallee", [], []), {"msg[0].data[0]": 1}, ["msg[0].data[0]"])
    assert "value" not in got["outputs"]["msg[0].data[0]"]


def test_a_member_the_row_names_by_itself_is_a_buffer_as_long_as_the_function_reaches():
    # (review R82 W-R2-1 · W-R2-4) KJPDS02_PV lists `RespMsg[0].data` (the member) as an output: the harness gives it a
    #   buffer — the write lands there, no write-past tag, and the row's assumptions say so
    got = _run(_unit("respond", [], []), {"code": 7, "msg[0].length": 0}, ["msg[0].data", "msg[0].length"])
    assert got["written"]["msg[0].data[0]"] is True and not got["possible_undefined_behavior"]
    assert got["harness_buffers"] == {"msg[0].data": "unbounded"}
    assert any("harness buffers:" in a and "msg[0].data unbounded" in a for a in got["assumptions"])
    plain = _run(_unit("setall", [], []), {"d": 1}, ["g_out"])
    assert "harness_buffers" not in plain and not any("harness buffers" in a for a in plain["assumptions"])


def test_a_write_past_the_named_elements_reaches_any_object_the_pointer_reaches():
    # (review R82 W-R2-1) the tag and the values agree: past the allocation the model claims nothing a pointer reaches
    got = _run(_unit("clear", [], []), {"buf[0]": 1, "buf[1]": 1, "n": 4}, ["buf[0]", "buf[2]"])
    assert "harness_buffer_write_beyond_row" in got["possible_undefined_behavior"]
    assert "value" not in got["outputs"]["buf[2]"]


def test_a_write_whose_new_value_is_unknown_asks_for_no_prior_value(monkeypatch):
    # (review R82 W8 · W-R2-5) `g_flt_out = (U8)g_flt`: no prior value lets a row tell that write's deletion
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("flw", ["d"], ["g_flt_out", "g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]
    assert "g_out" in rec["added"] and "g_flt_out" not in rec["added"]
    assert "g_flt_out" not in (rec.get("prior_value_not_added") or {})


def test_a_prior_value_no_column_observes_is_not_added(monkeypatch):
    # (review R82 I-R2-1) `s32s_Start` is written but no expected column shows it (the R80 output axis off — with it on,
    #   the written object becomes a column and its prior value an input): its deletion shows nowhere
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    monkeypatch.setattr(suts, "_add_written_outputs", lambda *a, **k: [])
    unit = _unit("setall", ["d"], ["g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]
    assert "g_out" in rec["added"] and "s32s_Start" not in unit["input_vars"]
    assert rec["prior_value_not_added"]["s32s_Start"] == "not_observed"


def test_the_masked_candidate_reads_a_mask_on_either_side():
    # (review R82 I7, W-R2-5) asserted on the candidates themselves — the search may reach the row another way
    from generators import scenario_rows as sr
    from generators.c_source_oracle import _parsed_function
    raw = SRC.encode()
    _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, "leftmask", _scope())
    assert sr._element_comparisons(fn, raw, _scope(), {"pData[0]"}) == {"pData[0]": {0x10}}
    _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, "parse", _scope())
    assert 0x20 in sr._element_comparisons(fn, raw, _scope(), {"pData[0]"})["pData[0]"]   # inside `IS_CF`


def test_the_prior_value_counts_reach_the_summary_and_the_exposing_search_sentence():
    # (review R82 W-R2-5: the report keys were in no summed list — a dropped key passed every test)
    from report_gen.generation_disclosures import build_disclosures
    rep = {**dict.fromkeys(suts.SCENARIO_REPORT_KEYS, 0), "expose_targets": 5, "expose_unmodeled": 3,
           "expose_prior_value_needed": 2, "expose_prior_value_unnamed": 1}
    sc = suts.summarize_scenario_rows([{"scenario_rows": rep}, {"scenario_rows": rep}])
    assert sc["expose_prior_value_needed"] == 4 and sc["expose_prior_value_unnamed"] == 2
    note = {i["key"]: i for i in build_disclosures("suts", {"scenario_rows": sc})}["suts_scenario_rows"]["note"]
    assert "쓰기 전 값을 입력으로 청한 쓰기 4" in note and "이름으로 적을 수 없는 쓰기 2" in note


# ── review round 3 ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_member_named_by_itself_stays_unbounded_when_element_columns_are_added(monkeypatch):
    # (review R82 W-R3-1) the design names `msg[0].data`; R80 adds `data[0..7]` (the cap) — the buffer must not shrink to
    #   those 8: else `data[8..11]` become writes past it and every column drops (fill10: 0 columns). Twelve elements
    #   found at once also order the cap by index (`data[10]` sorts before `data[2]` as text — self-check)
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("fill10", ["msg"], ["msg[0].data"], {"msg": "MSG *"})
    seqs = extended_unit_sequences(unit)
    cols = [o for o in unit["output_vars"] if o.startswith("msg[0].data[")]
    assert cols == [f"msg[0].data[{k}]" for k in range(suts._BUFFER_ELEMENTS_MAX)]
    nadd = unit["source_written_outputs"]["not_added"]
    assert {nadd.get(f"msg[0].data[{k}]") for k in range(8, 12)} == {"buffer_elements_full"}
    assert any(s["expected"].get("msg[0].data[7]") == 8 for s in seqs)
    # the oracle alone: element names beside the member keep it unbounded
    got = _run(_unit("tailunk", [], []), {"msg[0].data[0]": 0, "g_arr[0]": 9},
               ["msg[0].data", "msg[0].data[0]", "g_arr[0]"])
    assert got["outputs"]["g_arr[0]"]["value"] == 3 and not got["possible_undefined_behavior"]
    assert got["harness_buffers"] == {"msg[0].data": "unbounded"}


def test_an_unknown_index_on_a_named_buffer_may_write_past_it():
    # (review R82 W-R3-2) `p[g_idx] = 1U` with the row naming `p[0]` only: as a write past the allocation
    got = _run(_unit("iu", [], []), {"p[0]": 0, "g_arr[0]": 9}, ["p[0]", "g_arr[0]"])
    assert "harness_buffer_write_beyond_row" in got["possible_undefined_behavior"]
    assert "value" not in got["outputs"]["g_arr[0]"]


def test_a_buffer_only_observed_is_no_assumption_of_the_row():
    # (review R82 W-R3-3) the output list names `msg[0].data`; the function never reaches it — no harness-buffer sentence
    got = _run(_unit("nd", [], []), {"c": 4, "msg[0].length": 0}, ["msg[0].data", "msg[0].length"])
    assert got["outputs"]["msg[0].length"]["value"] == 4
    assert "harness_buffers" not in got and not any("harness buffers" in a for a in got["assumptions"])


def test_a_prior_value_whose_column_comes_only_in_the_final_pass_says_so(monkeypatch):
    # (review R82 I-R3-1) the rounds see no column for `s32s_Start` (R80 rounds off); the final pass adds it — the prior
    #   value is not 'not observed' then, but observed only after the last round
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    real = suts._add_written_outputs
    monkeypatch.setattr(suts, "_add_written_outputs",
                        lambda unit, seqs, rec, round_: real(unit, seqs, rec, round_) if round_ == "final" else [])
    unit = _unit("setall", ["d"], ["g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    assert "s32s_Start" in unit["output_vars"]
    assert unit["source_read_inputs"]["prior_value_not_added"]["s32s_Start"] == "observed_only_in_final"


def test_buffer_elements_written_past_the_allocation_are_not_never_known(monkeypatch):
    # (review R82 I-R3-2) `clear(buf, n)` with the row naming buf[0..1]: buf[2..] were written past the allocation — not
    #   objects whose value never settled
    seqs = [{"seq_num": 1, "source_written": {"buf[0]": True, "buf[2]": False, "g_out": False},
             "source_written_unknown": {"buf[2]": "harness_buffer_write_beyond_row:buf", "g_out": "path_dependent"},
             "expected": {}, "expected_evidence": {}}]
    unit = _unit("clear", ["n"], ["buf[0]"], {"n": "U8"})
    unit["source_written_outputs"] = suts._new_written_record()
    monkeypatch.setattr(suts, "_add_written_outputs", lambda *a, **k: [])
    suts.complete_source_written_outputs(unit, seqs)
    rec = unit["source_written_outputs"]
    assert "buf[2]" not in rec["never_known"] and rec["written_past_allocation"] == ["buf[2]"]
    assert suts.summarize_source_written_outputs([unit])["names_written_past_allocation"] == 1


def test_the_input_side_buffer_cap_keeps_the_first_elements(monkeypatch):
    # (review R82 I-R3-4) a loop reads 12 bytes of `p`: the completion adds the first `_BUFFER_ELEMENTS_MAX` — the rest
    #   are said (`buffer_elements_full`), not silently left
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("sum12", ["p"], ["return"], {"p": "const U8 *"})
    normalize_pointer_parameters([unit])
    extended_unit_sequences(unit)
    assert [n for n in unit["input_vars"] if n.startswith("p[")] == [f"p[{k}]" for k in range(suts._BUFFER_ELEMENTS_MAX)]
    nadd = unit["source_read_inputs"]["not_added"]
    assert nadd and set(nadd.values()) == {"buffer_elements_full"} and "p[8]" in nadd


def test_the_pointer_member_column_is_said_not_to_be_a_pointer_value():
    # (review R82 W-R2-2 · I-R3-4) a tester moving the document to VectorCAST must not put 0 (NULL) in that column
    from report_gen.generation_disclosures import build_disclosures
    items = {i["key"]: i for i in build_disclosures("suts", {"pointer_parameters": {"units": 1, "renamed": 1}})}
    note = items["suts_pointer_parameters"]["note"]
    assert "포인터 멤버 열 자체의 값은 포인터 값으로 쓰지 않는다" in note and "0 · NULL 이 아니다" in note


def test_a_row_observing_only_a_later_element_still_sets_the_buffer_up():
    # (self-check: `observes_pointee` without buffer elements) the row sets nothing in `buf` and observes `buf[1]` only
    got = _run(_unit("clear", [], []), {"n": 2}, ["buf[1]"])
    assert got["outputs"]["buf[1]"]["value"] == 0


def test_a_write_through_star_p_names_the_pointee_as_its_prior_value(monkeypatch):
    # (self-check: `_written_name` of `*p`) `setp` writes `*out` on every path: the prior value is `out[0]`
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("setp", ["d"], ["out"], {"out": "U8 *", "d": "U8"})   # the design lists the out-parameter as output only
    normalize_pointer_parameters([unit])
    extended_unit_sequences(unit)
    assert unit["source_read_inputs"]["added"]["out[0]"]["prior_value_for_write"] >= 1


def test_a_prior_value_the_search_also_read_is_counted_as_read():
    # (review R82 I1, self-check) a name both a write's prior value and read by the search is the search's
    recs = [{"source_read_inputs": {"added": {
        "a": {"slots": 0, "prior_value_for_write": 1, "read_on_model": True, "scenario_targets": 1},
        "b": {"slots": 0, "prior_value_for_write": 1, "read_on_model": False}}, "not_added": {}, "rounds": 1}}]
    got = suts.summarize_source_read_inputs(recs)
    assert got["names_added_for_write_prior_value"] == 1 and got["names_added_by_scenario_search"] == 1


# ── review round 4 ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_prior_value_added_in_a_later_round_is_not_also_left_not_observed(monkeypatch):
    # (review R82 W-R4-1) round 1 sees no column for `s32s_Start` (R80 off in round 1 only), round 2 adds the column and
    #   the prior value — the record must not also say 'not observed'
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    real = suts._add_written_outputs
    monkeypatch.setattr(suts, "_add_written_outputs",
                        lambda unit, seqs, rec, round_: [] if round_ == 1 else real(unit, seqs, rec, round_))
    unit = _unit("setall", ["d"], ["g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]
    assert "s32s_Start" in rec["added"]
    assert not set(rec["added"]) & set(rec.get("prior_value_not_added") or {})
    assert "not_observed" not in suts.summarize_source_read_inputs([unit])["prior_value_not_added"]


def test_only_the_buffer_elements_written_past_the_allocation_are_counted_so(monkeypatch):
    # (review R82 W-R4-2) `p[3] = 1U` past `p[0]`: the write may reach `g_arr[1]` too (same reason) — that one is an object
    #   whose value never settled, not a buffer element
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("wpg", ["p", "d"], ["p", "g_out"], {"p": "U8 *", "d": "U8"})
    normalize_pointer_parameters([unit])
    extended_unit_sequences(unit)
    sw = unit["source_written_outputs"]
    assert sw.get("written_past_allocation") == ["p[3]"]
    assert "g_arr[1]" in sw["never_known"] or "g_arr[1]" in unit["output_vars"]
    from report_gen.generation_disclosures import build_disclosures
    summ = suts.summarize_source_written_outputs([unit])
    note = {i["key"]: i for i in build_disclosures("suts", {"source_written_outputs": summ})}["suts_source_written_outputs"]
    assert "할당하지 않은 곳)에 쓴 버퍼 원소 1" in note["note"]


def test_an_unknown_index_on_an_unbounded_buffer_is_no_write_past_it():
    # (review R82 round 4, `w32_isnone`) the row names the member itself: as long as the function reaches
    got = _run(_unit("iu", [], []), {"p[0]": 0, "g_arr[0]": 9}, ["p", "p[0]", "g_arr[0]"])
    assert "harness_buffer_write_beyond_row" in got["possible_undefined_behavior"]   # a scalar pointee: extent 1
    got = _run(_unit("respond", [], []), {"code": 7, "msg[0].data": 0}, ["msg[0].length"])
    assert got["harness_buffers"] == {"msg[0].data": "unbounded"}   # named in the inputs only (`w31_inputs_only`)
    assert not got["possible_undefined_behavior"]


def test_the_reach_of_an_unbounded_buffer_is_said():
    # (review R82 I-R4-3) the size a harness needs: the last element the run reached
    got = _run(_unit("fill10", [], []), {"msg[0].length": 0}, ["msg[0].data"])
    assert got["harness_buffer_reach"] == {"msg[0].data": 11}
    assert any("msg[0].data unbounded — reached [11]" in a for a in got["assumptions"])


def test_a_prior_values_fixed_value_differs_from_what_the_function_writes(monkeypatch):
    # (R82 measurement, PV `g_UDS_LinComp_Reset` — 3 kills lost) the exposing search ran out of budget there and every row
    #   kept the prior value at its fixed fill, which was the value written (`u8g_SysUds_UsDoorCtrl = u8g_CLR` over 0): the
    #   write's deletion showed nowhere. `g_wm = 129U` over the U8 fill (129 here) is the same collision
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("wmid", ["d"], ["g_wm", "g_out"], {"d": "U8"})   # the base region's rows keep the fixed value
    seqs = extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]["added"]["g_wm"]
    assert rec["written_values"] == [129]
    fixed = [s["inputs"]["g_wm"] for s in seqs[:unit["base_strategy_count"]] if "g_wm" in s["inputs"]]
    assert fixed and 129 not in fixed
    # (review R82 I-R5-4) the move is recorded, counted and said
    moved = unit["source_read_inputs"]["prior_fixed_values"]["g_wm"]
    assert moved["from"] == 129 and moved["to"] == fixed[0]
    summ = suts.summarize_source_read_inputs([unit])
    assert summ["prior_fixed_values_moved"] == 1 and summ["prior_fixed_values_collide"] == 0
    from report_gen.generation_disclosures import build_disclosures
    note = {i["key"]: i for i in build_disclosures("suts", {"source_read_inputs": summ})}["suts_source_read_inputs"]["note"]
    assert "고정값을 옮긴 이름 1" in note
    desc = seqs[0]["description"].splitlines()
    prior_line = [ln for ln in desc if ln.startswith("쓰기 전 값(함수가 쓰는 객체의 호출 전 값 · 이 행에선 고정값): ")]
    assert prior_line and f"g_wm={fixed[0]}" in prior_line[0]   # (I-R5-5) a prior value, not a read input
    assert not any(ln.startswith("소스가 읽어 더한 입력") for ln in desc)


def test_an_enum_prior_values_fixed_value_stays_an_enumerator(monkeypatch):
    # (review R82 W-R5-1) the SwUDS gives `g_en` the range 0~3 (mid 1); the fill is the enumerator 2, which the function
    #   writes — the moved value must be another enumerator, not 1: a base row holding 1 is no base of the boundary search
    #   (its value set is the enumerators) and the 'an enum is filled with an enumerator' sentence would be false
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("enw", ["d"], ["g_en", "g_out"], {"d": "U8"}, uds_param_info={"g_en": {"range": [0, 3], "type": ""}})
    seqs = extended_unit_sequences(unit)
    assert unit["source_read_inputs"]["added"]["g_en"]["written_values"] == [2]
    base = {s["inputs"]["g_en"] for s in seqs[:unit["base_strategy_count"]] if "g_en" in s["inputs"]}
    assert base and base <= {0, 3}
    assert {s["inputs"]["g_en"] for s in seqs if "g_en" in s["inputs"]} <= {0, 2, 3}
    assert unit["source_read_inputs"]["prior_fixed_values"]["g_en"] == {"from": 2, "to": 0}


def test_the_fill_override_moves_only_a_colliding_prior_only_value_inside_its_domain():
    # (review R82 I-R5-1: `fv_collision_off` · `fv_read_check_off`) a name the search also reads is no prior-only input;
    #   a fill that is not written stays; a range picks its mid, then its midpoint and up; a value set keeps its values
    added = {"a": {"prior_value_for_write": 1, "read_on_model": False, "written_values": [5]},
             "b": {"prior_value_for_write": 1, "read_on_model": True, "written_values": [5]},
             "c": {"prior_value_for_write": 1, "read_on_model": False, "written_values": [7]},
             "e": {"prior_value_for_write": 1, "read_on_model": False, "written_values": [2]},
             "f": {"prior_value_for_write": 1, "read_on_model": False, "written_values": [0, 1]}}
    unit = {"source_read_inputs": {"added": added}}
    fill = {"a": 5, "b": 5, "c": 5, "e": 2, "f": 1}
    doms = {"a": (0, 10), "b": (0, 10), "c": (0, 10), "e": frozenset({0, 2, 3}), "f": [0, 1]}
    moved, collide = suts._prior_fill_overrides(unit, fill, doms, {"a": {"mid": 5}, "e": {"mid": 1}})
    assert moved == {"a": 6, "e": 0} and collide == ["f"]


def test_the_boundary_rows_fill_a_prior_value_off_the_value_written_too():
    # (review R82 I-R5-2) one fill for the rows and the boundary search: `find_boundaries` takes the caller's overrides,
    #   inside the domain only
    from generators.boundary_rows import blank_fill
    assert blank_fill({"x": (0, 255)}, {"x": 129}, overrides={"x": 128}) == {"x": 128}
    assert blank_fill({"x": (0, 255)}, {"x": 129}, overrides={"x": 300}) == {"x": 129}
    assert blank_fill({"e": [0, 2, 3]}, {"e": 2}, overrides={"e": 1}) == {"e": 2}


def test_boundary_rows_on_mcdc_vectors_keep_the_prior_value_off_the_written_ones(monkeypatch):
    # (review R82 I-R5-2, probe q4) the boundary rows built on an MC/DC vector fill `g_wm2` themselves: before, they took
    #   130 — a value the function writes — while every other row held the moved value
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("wm2", ["d", "e"], ["g_wm2", "g_out"], {"d": "U8", "e": "U8"})
    seqs = extended_unit_sequences(unit)
    assert sorted(unit["source_read_inputs"]["added"]["g_wm2"]["written_values"]) == [127, 130]
    bnd = [s for s in seqs if s["strategy"].startswith("BND_")]
    assert bnd and all(s["inputs"].get("g_wm2") not in (127, 130) for s in bnd)
    assert all(s["inputs"].get("g_wm2") not in (127, 130) for s in seqs if "g_wm2" in s["inputs"])


def test_a_prior_value_whose_every_candidate_is_written_is_counted_and_said(monkeypatch):
    # (review R82 I-R5-3) the design value list {0, 1} — the function writes both: the fixed value cannot be moved
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    unit = _unit("both", ["d"], ["g_b", "g_out"], {"d": "U8"},
                 uds_param_info={"g_b": {"values": [0, 1], "range_text": "0, 1"}})
    seqs = extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]
    assert sorted(rec["added"]["g_b"]["written_values"]) == [0, 1]
    assert rec["prior_fixed_values_collide"] == ["g_b"] and "g_b" not in (rec.get("prior_fixed_values") or {})
    summ = suts.summarize_source_read_inputs([unit])
    assert summ["prior_fixed_values_collide"] == 1
    from report_gen.generation_disclosures import build_disclosures
    note = {i["key"]: i for i in build_disclosures("suts", {"source_read_inputs": summ})}["suts_source_read_inputs"]["note"]
    assert "고정값을 옮기지 못한 이름 1 — 그 쓰기의 삭제는 기본 행이 가르지 못한다" in note
    # the exposing search still moves the prior value itself: `g_b = 1U` (d <= 3) over a prior of 0 — a row the fixed
    #   value (1) cannot give (a write's exposure moves the written object, `exposure_inputs`)
    assert any(s["inputs"].get("d") is not None and s["inputs"]["d"] <= 3 and s["inputs"].get("g_b") == 0 for s in seqs)


def test_an_unobserved_prior_value_at_the_round_cap_is_not_one_the_cap_left(monkeypatch):
    # (review R82 I-R4-1, `cap_unobserved_off`) one round, R80 off: `g_x` (read) takes the round; at the cap `g_wm` (no
    #   column observes it) is 'not observed', `g_out` (observed) is a prior value the cap left
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    monkeypatch.setattr(suts, "_add_written_outputs", lambda unit, seqs, rec, round_: [])
    monkeypatch.setattr(suts, "_SOURCE_READ_ROUNDS", 1)
    unit = _unit("capx", ["d"], ["g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    rec = unit["source_read_inputs"]
    assert sorted(rec["added"]) == ["g_x"]
    assert rec["prior_value_not_added"] == {"g_wm": "not_observed"}
    assert rec["prior_values_beyond_cap"] == ["g_out"]


def test_a_late_column_taken_back_by_a_failed_final_pass_is_not_observed_again(monkeypatch):
    # (review R82 I-R4-2, `final_rejudge_off`) the final pass adds `s32s_Start`, then fails and takes it back: the prior
    #   value is 'not observed' — not 'observed only in the final pass' for a column the document no longer has
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))
    real = suts._add_written_outputs
    monkeypatch.setattr(suts, "_add_written_outputs",
                        lambda unit, seqs, rec, round_: real(unit, seqs, rec, round_) if round_ == "final" else [])

    def boom(unit, seqs):
        raise RuntimeError("final drop")

    monkeypatch.setattr(suts, "_drop_underived_written_outputs", boom)
    unit = _unit("setall", ["d"], ["g_out"], {"d": "U8"})
    extended_unit_sequences(unit)
    assert "s32s_Start" not in unit["output_vars"]
    assert unit["source_read_inputs"]["prior_value_not_added"]["s32s_Start"] == "not_observed"


def test_the_reach_names_buffers_only_and_says_an_unknown_index():
    # (review R82 I-R5-1 `i43_reach_any`, I-R5-7) `g_arr[1]` is no harness buffer; `p[g_idx]` reaches an index the run
    #   does not know — the size a harness needs may be more than the reach says
    got = _run(_unit("wpg", [], []), {"p[0]": 0, "d": 1}, ["p[0]", "g_arr[1]"])
    assert got["harness_buffer_reach"] == {"p": 3} and "harness_buffer_reach_unknown" not in got
    got = _run(_unit("iu", [], []), {"p[0]": 0, "g_arr[0]": 9}, ["p", "p[0]", "g_arr[0]"])
    assert got["harness_buffer_reach_unknown"] == ["p"]
    assert any("also at an index the run does not know" in a for a in got["assumptions"])


def test_a_climb_to_a_guard_does_not_move_a_prior_value_the_function_wrote_over():
    # (R82 measurement, HD `g_ApiIn_LinRx_ReadData`: reached targets 41 → 21) `g_fl = GET_FLAG(); if (g_fl == ON)` — the
    #   completion added `g_fl` only as the write's prior value; the guard reads what the function wrote over it, so a
    #   climb that moves only `g_fl` stops (`local_best`). It moves the others (`g_hw`); the same name taken as a read
    #   input (the old view) shows the stop
    from generators import scenario_rows as sr
    doms = {"d": (0, 255), "g_hw": (0, 255), "g_fl": (0, 255)}
    for fn in ("ovw", "ovsw"):   # a guard, a switch's case
        reports = {}
        for read in (False, True):
            unit = _unit(fn, ["d"], ["g_fl", "g_out"], {"d": "U8"})
            unit["source_read_inputs"] = {"added": {"g_fl": {"prior_value_for_write": 1, "read_on_model": read}}}
            reports[read] = sr.find_scenarios(unit, doms, ["g_out", "g_fl"])["report"]
        assert reports[False]["reached_clean"] == reports[False]["targets"] and reports[False]["local_best"] == 0, fn
        assert reports[True]["local_best"] > 0, fn


def test_a_comparison_to_expose_moves_what_it_reads_not_the_prior_value_written_over():
    # (R82) `g_fl = (U8)(g_hw >> 1U); if (g_fl > 10U)`: the boundary target (g_fl at 10 and 11) moves `g_hw`; moving the
    #   written-over prior value `g_fl` only spends runs (the old view needs more than twice as many to get there)
    from generators import scenario_rows as sr
    doms = {"d": (0, 255), "g_hw": (0, 255), "g_fl": (0, 255)}
    reports = {}
    for read in (False, True):
        unit = _unit("ovb", ["d"], ["g_fl", "g_out"], {"d": "U8"})
        unit["source_read_inputs"] = {"added": {"g_fl": {"prior_value_for_write": 1, "read_on_model": read}}}
        found = sr.find_scenarios(unit, doms, ["g_out", "g_fl"])
        reports[read] = {**found["report"], "rows": [r["inputs"] for r in found["rows"]]}
    assert reports[False]["expose_boundary"] == 1 and reports[False]["expose_rows"] >= 1
    # (review R82 I-R6-1) the same rows for fewer runs — the cost is what differs (5 against 12 when measured)
    assert reports[False]["expose_runs"] < reports[True]["expose_runs"]
    assert reports[False]["rows"] == reports[True]["rows"]


def test_a_prior_value_read_on_a_path_no_round_saw_is_still_tried_at_a_local_best():
    # (review R82 W-R6-1) `g_x` was classified written-only (the rounds never reached `g_mode > 30`): at the guard
    #   `g_x == 1U` moving the others gets nowhere — the climb tries the names the guard names once more
    from generators import scenario_rows as sr
    unit = _unit("hid", ["d"], ["g_out", "g_x"], {"d": "U8"})
    unit["source_read_inputs"] = {"added": {"g_x": {"prior_value_for_write": 1, "read_on_model": False}}}
    rep = sr.find_scenarios(unit, {"d": (0, 255), "g_mode": (0, 255), "g_x": (0, 255)}, ["g_out", "g_x"])["report"]
    assert rep["reached_clean"] == rep["targets"] and rep["local_best"] == 0


def test_a_write_reading_a_written_over_prior_value_exposes_through_what_set_it():
    # (review R82 W-R6-2) `g_y = g_fl` after `g_fl = GET_FLAG()`: the write's exposure moves `g_hw` (what `g_fl` holds
    #   by then), not `g_fl` — with `g_y` fixed at 0 only `g_hw` odd (flag 1) shows the write's deletion
    from generators import scenario_rows as sr
    unit = _unit("ovy", ["d"], ["g_out", "g_y", "g_fl"], {"d": "U8"})
    unit["source_read_inputs"] = {"added": {"g_y": {"prior_value_for_write": 1, "read_on_model": False},
                                            "g_fl": {"prior_value_for_write": 1, "read_on_model": False}}}
    found = sr.find_scenarios(unit, {"d": (0, 255), "g_hw": (0, 255), "g_y": (0, 0), "g_fl": (0, 255)},
                              ["g_out", "g_y", "g_fl"])
    assert found["report"]["expose_local_best"] == 0
    assert any(r["inputs"].get("g_hw", 0) & 1 for r in found["rows"])
