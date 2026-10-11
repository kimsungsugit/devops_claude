"""R81 — pointer parameters as the reference writes them (`p[0]` · `p[0].a`), and out-parameters the function only writes.

KJPDS02_PV extended (R80 code): ≈92 of the 137 mutants only the reference killed were in functions with pointer parameters
and no derived expected value at all. Their design tables name a pointer parameter by the pointer alone
(`s_ApplyTemperatureCompensation`: `u16p_Peak`,
`s_sha256_init`: `ctx`), the generated rows put the pointee's value in that cell, and the source oracle read it as the
pointer itself (an address — R40 review W4) and set no pointee up; an out-parameter the function only writes was never set
up either (no row sets its pointee — R40 left `out[0]`). The reference writes `u16p_Peak[0]` · `ctx[0].state[1]`.
(1) A row that observes a pointee (an output `p[0].a`, or the out-parameter itself) has the harness object
(`_Interp.observes_pointee`), and the searches see what the evidence sees (the unit's outputs); (2) the run's writes to
it are written objects (`_written_objects`) the extended profile adds as expected columns, and its reads before a write
are source-read inputs (R19); (3) `normalize_pointer_parameters` renames a scalar pointee's parameter `p` → `p[0]` and
replaces a struct pointee's input by the members the body reaches."""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators import suts
from generators.c_source_oracle import evaluate_outputs, observe_decisions
from generators.suts import extended_unit_sequences, normalize_pointer_parameters, source_read_names

ROOT = os.path.join(os.sep, "proj")
HEADER = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef unsigned long U32;
typedef struct { U32 bitcount; U32 state[8]; U8 buffer[4]; } CTX;
typedef struct { volatile U8 flag; U8 v; } VS;
"""
SRC = """#include "c.h"
U8 g_done;
U16 g_gain;
static void init(CTX *ctx)
{
    ctx->bitcount = 0U;
    ctx->state[0] = 0x6a09e667U; ctx->state[1] = 0xbb67ae85U;
    g_done = 1U;
}
static void addbits(CTX *ctx, U16 n)
{
    ctx->bitcount = ctx->bitcount + (U32)n;
}
void peak(U16 *u16p_Peak, U16 v)
{
    if (v > g_gain) { *u16p_Peak = v - g_gain; } else { *u16p_Peak = 0U; }
}
void comp(U16 *u16p_Peak)
{
    if (*u16p_Peak > 100U) { *u16p_Peak = (U16)(*u16p_Peak - 100U); }
}
U8 guard(U16 *p)
{
    U8 r = 0U;
    if (p != 0) { *p = 7U; r = 1U; }
    return r;
}
void untouched(CTX *ctx, U8 d)
{
    g_done = d;
}
void opaque(void *vp)
{
    g_done = 2U;
}
void mix(CTX *ctx, U16 n)
{
    g_done = (U8)(ctx->bitcount + ctx->state[0] + ctx->state[1] + n);
}
static U8 s_a;
static U8 s_b;
U8 g_o1;
U8 g_o2;
void plain(U8 d)
{
    if (s_a > 3U) { g_o1 = 1U; } else { g_o1 = 2U; }
    g_o2 = (U8)(s_b + d);
}
void vol(VS *vs)
{
    vs->v = vs->flag;
}
void two(CTX *a, CTX *b)
{
    g_done = (U8)(a->bitcount + b->bitcount);
}
void sc(CTX *ctx, U8 d)
{
    if (ctx->bitcount > 5U) { g_done = d; }
}
static U8 s_hidden;
void sc2(CTX *ctx, U8 d)
{
    if (ctx->bitcount > 5U) { s_hidden = d; }
}
static U16 s_cnt;
void tick(U8 d)
{
    s_cnt++;
    g_done = d;
}
"""
FILES = {os.path.join(ROOT, "c.h"): HEADER, os.path.join(ROOT, "u.c"): SRC}
PATH = os.path.join(ROOT, "u.c")
_SCOPE = {}


def _scope():
    if not _SCOPE:
        ctx = cpc.build_project_context(FILES)
        _SCOPE["s"] = cpc.build_scopes(ctx, [PATH])[PATH]
    return _SCOPE["s"]


def _unit(name, ins, outs, ptypes, **extra):
    return {"name": name, "fid": "F_" + name, "source_text": SRC, "source_path": PATH, "source_text_complete": True,
            "project_scope": _scope(), "input_vars": list(ins), "output_vars": list(outs), "param_types": dict(ptypes),
            "uds_param_info": {}, **extra}


def _run(unit, inputs, outs, written=True):
    return evaluate_outputs(unit, [inputs], [outs], written=written)[0]


# ── (1) oracle: an observed pointee is set up ───────────────────────────────────────────────────────────────────────
def test_an_observed_out_parameter_member_is_derived():
    unit = _unit("init", [], [], {})
    got = _run(unit, {}, ["ctx[0].state[1]", "ctx[0].bitcount", "g_done"])
    assert got["outputs"]["ctx[0].state[1]"] == {"value": 0xBB67AE85, "basis": "assigned"}
    assert got["outputs"]["ctx[0].bitcount"]["value"] == 0 and got["outputs"]["g_done"]["value"] == 1


def test_an_unobserved_out_parameter_stays_as_before():
    # nothing names the pointee: no harness object, the write goes through a pointer the model cannot place
    got = _run(_unit("init", [], [], {}), {}, ["g_done"])
    assert got["written"] == {"g_done": True}
    assert not any(k.startswith("ctx") for k in got["written"])


def test_the_out_parameter_named_alone_sets_its_pointee_up_and_says_pointer_value():
    got = _run(_unit("init", [], [], {}), {}, ["ctx", "g_done"])
    assert got["outputs"]["ctx"] == {"reason": "pointer_value"}
    # its written members and elements by the reference's names; the whole pointee / array is not one
    assert got["written"] == {"ctx[0].bitcount": True, "ctx[0].state[0]": True, "ctx[0].state[1]": True,
                              "g_done": True}


def test_a_row_that_states_the_pointer_itself_still_sets_nothing_up():
    # (R40 review W4) `p = 0` in the row is the pointer (NULL / an address), even when the row observes `p[0]`
    got = _run(_unit("peak", [], [], {}), {"v": 15, "u16p_Peak": 0, "g_gain": 3}, ["u16p_Peak[0]"])
    assert "value" not in got["outputs"]["u16p_Peak[0]"]


def test_the_searches_see_the_pointee_the_evidence_sets_up():
    # (R81) a search (`observe_decisions`) runs as the evidence will: the unit's outputs observe `p[0]`, so `p != 0` is
    #   decided on the pointee the evidence allocates — a search that did not see it would rank rows by other outcomes
    unit = _unit("guard", [], ["p[0]", "return"], {})
    ev = _run(unit, {}, ["return"], written=False)
    assert ev["outputs"]["return"]["value"] == 1
    run = observe_decisions(unit, [{}], [], outputs=["return"])[0]
    assert run["status"] == "supported" and run["outputs"]["return"]["value"] == 1
    bare = dict(unit, output_vars=[])
    assert "value" not in _run(bare, {}, ["return"], written=False)["outputs"]["return"]
    assert "value" not in observe_decisions(bare, [{}], [], outputs=["return"])[0]["outputs"]["return"]


# ── (3) normalize ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_scalar_pointee_parameter_is_renamed_with_its_design_rows():
    unit = _unit("comp", ["u16p_Peak"], ["u16p_Peak"], {"u16p_Peak": "U16 *"},
                 uds_param_info={"u16p_Peak": {"range": [0, 500]}}, value_domains={})
    got = normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["u16p_Peak[0]"] and unit["output_vars"] == ["u16p_Peak[0]"]
    assert unit["uds_param_info"] == {"u16p_Peak[0]": {"range": [0, 500]}}
    assert unit["param_types"] == {"u16p_Peak": "U16 *"}
    assert got["renamed"] == 1 and unit["pointer_parameters"]["renamed"] == {"u16p_Peak": "u16p_Peak[0]"}


def test_a_struct_pointee_input_becomes_the_members_the_body_reaches():
    unit = _unit("addbits", ["ctx", "n"], ["ctx"], {"ctx": "CTX *", "n": "U16"})
    got = normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["ctx[0].bitcount", "n"]
    assert unit["output_vars"] == ["ctx"]   # observed — the extended profile adds the written members
    assert got["struct_inputs_replaced"] == 1 and got["struct_outputs_observed"] == 1


def test_a_struct_pointee_input_the_body_never_reaches_is_dropped():
    unit = _unit("untouched", ["ctx", "d"], ["g_done"], {"ctx": "CTX *", "d": "U8"})
    got = normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["d"] and got["struct_inputs_dropped"] == 1


def test_a_pointee_the_source_does_not_lay_out_is_left_and_counted():
    unit = _unit("opaque", ["vp"], ["g_done"], {"vp": "void *"})
    got = normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["vp"] and sum(got["unmodeled"].values()) == 1


def test_units_without_pointer_parameters_are_untouched():
    unit = _unit("peak", ["v"], ["g_done"], {"v": "U16"})
    before = dict(unit)
    assert normalize_pointer_parameters([unit])["units"] == 0
    assert unit == before and "pointer_parameters" not in unit


def test_a_renamed_pointer_keeps_its_address_range_out_of_the_range_conflicts():
    # the design's row of the pointer itself (`0 ~ 0xFFFFFFFF`) is an address range, not a document error
    unit = _unit("comp", ["u16p_Peak"], ["u16p_Peak"], {"u16p_Peak": "U16 *"},
                 uds_param_info={"u16p_Peak": {"range": [0, 0xFFFFFFFF]}})
    normalize_pointer_parameters([unit])
    suts.generate_sequences(unit, None)
    conflicts = " ".join(str(x) for x in (unit.get("range_conflicts") or []))
    assert "u16p_Peak" not in conflicts


# ── (2) extended: written members become columns, reads before a write become inputs ──────────────────────────────
def test_an_only_written_out_parameter_gets_its_members_as_derived_columns(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_done": "U8", "g_gain": "U16"})
    unit = _unit("init", [], ["ctx", "g_done"], {"ctx": "CTX *"})
    normalize_pointer_parameters([unit])
    seqs = extended_unit_sequences(unit)
    added = unit["source_written_outputs"]["added"]
    assert set(added) == {"ctx[0].bitcount", "ctx[0].state[0]", "ctx[0].state[1]"}
    assert added["ctx[0].state[0]"]["type"] == "U32"
    assert all(s["expected"]["ctx[0].state[1]"] == 0xBB67AE85 for s in seqs)
    assert unit["design_output_vars"] == ["ctx", "g_done"]


def test_a_member_read_before_its_write_becomes_an_input(monkeypatch):
    # the design lists `n` only: the run reads `ctx[0].bitcount` before writing it — R19 adds it by the reference's name
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_done": "U8", "g_gain": "U16"})
    unit = _unit("addbits", ["n"], ["ctx"], {"ctx": "CTX *", "n": "U16"})
    normalize_pointer_parameters([unit])
    seqs = extended_unit_sequences(unit)
    assert "ctx[0].bitcount" in unit["source_read_inputs"]["added"]
    assert "ctx[0].bitcount" in unit["input_vars"]
    rows = [s for s in seqs if isinstance(s["inputs"].get("ctx[0].bitcount"), int) and isinstance(s["inputs"].get("n"), int)
            and 0 <= s["inputs"]["ctx[0].bitcount"] <= 0xFFFFFFFF and 0 <= s["inputs"]["n"] <= 0xFFFF]
    assert len(rows) >= 3
    assert all(s["expected"]["ctx[0].bitcount"] == (s["inputs"]["ctx[0].bitcount"] + s["inputs"]["n"]) % 2 ** 32
               for s in rows)


def test_pointee_names_stay_out_of_the_program_object_findings():
    # without the unit (findings · remaining names) a pointee name is not a program object read — as before R81
    seq = {"seq_num": 1, "expected_evidence": {"x": {"reason": "initial_value_not_in_inputs:ctx[0].bitcount"}}}
    assert source_read_names([seq]) == {}
    unit = _unit("addbits", ["n"], ["ctx"], {"ctx": "CTX *", "n": "U16"})
    assert set(source_read_names([seq], unit)) == {"ctx[0].bitcount"}


def test_a_counter_written_from_its_own_initial_value_becomes_input_then_output(monkeypatch):
    # (R81) `s_cnt++` is in neither list: no expected value names its read, so R80 never saw a known value and R19 never
    #   saw the read — the written record's reason (`source_written_unknown`) names it; R19 adds it, then R80 the column
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_done": "U8", "g_gain": "U16"})
    unit = _unit("tick", ["d"], ["g_done"], {"d": "U8"})
    seqs = extended_unit_sequences(unit)
    assert unit["source_read_inputs"]["added"]["s_cnt"]["read_on_model"] is True
    assert "s_cnt" in unit["source_written_outputs"]["added"]
    rows = [s for s in seqs if isinstance(s["inputs"].get("s_cnt"), int) and 0 <= s["inputs"]["s_cnt"] < 0xFFFF]
    assert rows and all(s["expected"]["s_cnt"] == s["inputs"]["s_cnt"] + 1 for s in rows)


def test_an_unwritten_path_initial_value_waits_for_the_column():
    # only a read the model made — a partial write's unwritten-path initial value is R80's next round (R80 fixture shape)
    unit = _unit("tick", ["d"], ["g_done"], {"d": "U8"})
    seq = {"seq_num": 1, "expected_evidence": {},
           "source_written_unknown": {"s_cnt": "unwritten_output_initial_not_in_inputs:s_cnt", "g_done": "x"}}
    assert source_read_names([seq], unit) == {}
    seq["source_written_unknown"] = {"s_cnt": "initial_value_not_in_inputs:s_cnt"}
    assert set(source_read_names([seq], unit)) == {"s_cnt"}
    assert source_read_names([seq]) == {}


# ── review R81 round 1 ──────────────────────────────────────────────────────────────────────────────────────────────
def test_a_unit_without_pointers_adds_its_inputs_as_before(monkeypatch):
    # (review C1) the written record of a column (`g_o2`) names the read its expected value already names: counted once —
    #   counted twice it put `s_b` ahead of `s_a` and added boundary rows to a unit R81 is not about
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_o1": "U8", "g_o2": "U8"})
    unit = _unit("plain", ["d"], ["g_o1", "g_o2"], {"d": "U8"})
    extended_unit_sequences(unit)
    added = unit["source_read_inputs"]["added"]
    assert unit["input_vars"] == ["d", "s_a", "s_b"] and added["s_a"]["slots"] == added["s_b"]["slots"]


def test_a_name_only_a_written_record_names_has_no_cells():
    unit = _unit("tick", ["d"], ["g_done"], {"d": "U8"})
    seq = {"seq_num": 3, "expected_evidence": {"g_done": {"reason": "initial_value_not_in_inputs:g_gain"}},
           "source_written_unknown": {"g_done": "initial_value_not_in_inputs:g_gain",
                                      "s_cnt": "initial_value_not_in_inputs:s_cnt"}}
    got = source_read_names([seq], unit)
    assert got["g_gain"]["slots"] == 1                      # the column's read, once
    assert got["s_cnt"] == {"slots": 0, "sequences": [3], "read": True, "written_unknown": 1}


def test_a_function_the_normalizer_cannot_read_keeps_the_design_names():
    # (review W2) the members it reaches are unknown — not "none": the design's `ctx` stays, and why
    unit = _unit("addbits", ["ctx", "n"], ["ctx"], {"ctx": "CTX *", "n": "U16"}, source_text="")
    got = normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["ctx", "n"]
    assert unit["pointer_parameters"]["unmodeled"] == {"ctx": "function_unread:no_source_text"}
    assert got["unmodeled"] == {"function_unread": 1} and got["struct_inputs_dropped"] == 0


def test_members_beyond_the_input_columns_are_cut_and_counted(monkeypatch):
    monkeypatch.setattr(suts, "_INPUT_COL_END", suts._INPUT_COL_START + 1)   # two input columns
    unit = _unit("mix", ["ctx", "n"], ["g_done"], {"ctx": "CTX *", "n": "U16"})
    got = normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["ctx[0].bitcount", "n"]   # the design's later input keeps its column
    assert unit["pointer_parameters"]["over_cap"] == ["ctx[0].state[0]", "ctx[0].state[1]"]
    assert got["members_over_cap"] == 2 and got["member_inputs_added"] == 1


def test_a_renamed_pointer_address_range_is_counted_as_one():
    unit = _unit("comp", ["u16p_Peak"], ["u16p_Peak"], {"u16p_Peak": "U16 *"},
                 uds_param_info={"u16p_Peak": {"range": [0, 0xFFFFFFFF]}})
    normalize_pointer_parameters([unit])
    suts.generate_sequences(unit, None)
    assert any("u16p_Peak[0]" in str(x) for x in unit["pointer_address_ranges"])
    assert not any("u16p_Peak" in str(x) for x in unit["range_conflicts"])


def test_a_pointee_set_up_only_because_the_row_observes_it_is_said_so():
    # (review W3) the row sets nothing in `ctx[0]`: its values rest on a harness object the row only observes
    got = _run(_unit("init", [], [], {}), {}, ["ctx[0].state[1]"])
    assert got["observed_only_pointees"] == ["ctx"]
    assert any("because the row observes" in a and "ctx" in a for a in got["assumptions"])
    set_up = _run(_unit("addbits", [], [], {}), {"ctx[0].bitcount": 5, "n": 1}, ["ctx[0].bitcount"])
    assert set_up["outputs"]["ctx[0].bitcount"]["value"] == 6 and "observed_only_pointees" not in set_up


def test_pointee_inputs_are_no_input_list_gap(monkeypatch):
    # (review W6) the design names the parameter: the member R19 added is not a program object the input list lacks
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_done": "U8", "g_gain": "U16"})
    unit = _unit("addbits", ["n"], ["ctx"], {"ctx": "CTX *", "n": "U16"})
    seqs = extended_unit_sequences(unit)
    assert "ctx[0].bitcount" in unit["source_read_inputs"]["added"]
    assert "ctx[0].bitcount" not in suts.input_list_gaps(unit, seqs)


def test_the_disclosure_says_what_was_renamed_replaced_and_dropped():
    from report_gen.generation_disclosures import _pointer_parameters_item
    units = [_unit("comp", ["u16p_Peak"], ["u16p_Peak"], {"u16p_Peak": "U16 *"}),
             _unit("untouched", ["ctx", "d"], ["g_done"], {"ctx": "CTX *", "d": "U8"}),
             _unit("init", [], ["ctx", "g_done"], {"ctx": "CTX *"})]
    (item,) = _pointer_parameters_item(normalize_pointer_parameters(units))
    assert item["key"] == "suts_pointer_parameters" and item["tone"] == "warning"
    assert "뺀 설계 입력 1" in item["note"] and "구조체 대상 출력 1" in item["note"] and "NULL 분기" in item["note"]
    assert _pointer_parameters_item(normalize_pointer_parameters([_unit("peak", ["v"], ["g_done"], {"v": "U16"})])) == []


# ── review R81 round 2 ──────────────────────────────────────────────────────────────────────────────────────────────
def test_struct_member_inputs_stay_input_list_gaps(monkeypatch):
    # (review C-R2-1) R39 members are objects of their own name (`g.a` in `globals`): the pointee rule must not drop them
    from tests.unit import test_struct_members_r39 as r39
    path, scope = r39._scope()
    unit = {"name": "f1", "fid": "F_f1", "source_text": r39.C, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": ["g_o"], "output_vars": ["g_o"], "param_types": {}, "uds_param_info": {}}
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_o": "U8"})
    seqs = extended_unit_sequences(unit)
    assert {"g.a", "g.s.x"} <= set(unit["source_read_inputs"]["added"])
    assert {"g.a", "g.s.x"} <= set(suts.input_list_gaps(unit, seqs))


def test_rows_derived_on_an_observed_only_pointee_are_counted():
    from generators.test_evidence import apply_sequence_evidence, summarize_expected_evidence
    unit = _unit("init", [], ["ctx[0].state[1]", "g_done"], {})
    seqs = apply_sequence_evidence(unit, [{"seq_num": 1, "inputs": {}, "expected": {}}])
    assert seqs[0]["expected_evidence"]["ctx[0].state[1]"]["observed_only_pointees"] == ["ctx"]
    assert summarize_expected_evidence(seqs)["derived_on_observed_only_pointee"] == 2


# ── review R81 round 3 ──────────────────────────────────────────────────────────────────────────────────────────────
def test_an_observed_pointer_output_cell_says_so_instead_of_staying_blank():
    # (review W-R3-1) the design's bare `ctx` output sets the pointee up for the row's other values — its cell is no
    #   blank (a blank is no observation for a reader or a harness): it says `pointer_value`
    from generators.test_evidence import apply_sequence_evidence
    unit = _unit("init", [], ["ctx", "g_done"], {})
    (seq,) = apply_sequence_evidence(unit, [{"seq_num": 1, "inputs": {}, "expected": {}}])
    assert seq["expected"]["ctx"] == "[검증 필요] pointer_value" and seq["expected"]["g_done"] == 1
    # a row that states the pointer itself sets nothing up: its cell stays as before (blank unless the row had one)
    (bare,) = apply_sequence_evidence(unit, [{"seq_num": 1, "inputs": {"ctx": 0}, "expected": {}}])
    assert bare["expected_evidence"]["ctx"]["reason"] != "pointer_value" and "ctx" not in bare["expected"]


# ── self-check survivors ────────────────────────────────────────────────────────────────────────────────────────────
def test_a_volatile_pointee_member_is_no_column_or_input():
    unit = _unit("vol", [], [], {})
    scope = unit["project_scope"]
    assert suts._pointee_object_decl(unit, scope, "vs[0].flag") == (None, "volatile_object")
    assert suts._pointee_object_decl(unit, scope, "vs[0].v") == ("U8", "")
    assert suts._pointee_object_decl(unit, scope, "g_done") is None   # not this function's pointee: the program rule


def test_a_written_record_never_overrides_the_cells_rows_name():
    # a non-column counter's reason names `g_gain`, which a column's expected value already names: the rows' count stays
    unit = _unit("tick", ["d"], ["g_done"], {"d": "U8"})
    seq = {"seq_num": 1, "expected_evidence": {"g_done": {"reason": "initial_value_not_in_inputs:g_gain"}},
           "source_written_unknown": {"s_cnt": "initial_value_not_in_inputs:g_gain"}}
    got = source_read_names([seq], unit)
    assert got["g_gain"] == {"slots": 1, "sequences": [1], "read": True}


def test_a_later_run_without_unknown_writes_drops_the_stale_record():
    from generators.test_evidence import apply_sequence_evidence
    unit = _unit("tick", ["d"], ["g_done"], {"d": "U8"})
    seqs = apply_sequence_evidence(unit, [{"seq_num": 1, "inputs": {"d": 3}, "expected": {}}], written=True)
    assert seqs[0]["source_written_unknown"] == {"s_cnt": "initial_value_not_in_inputs:s_cnt"}
    seqs[0]["inputs"]["s_cnt"] = 4
    seqs = apply_sequence_evidence(unit, seqs, written=True)
    assert "source_written_unknown" not in seqs[0] and seqs[0]["source_written"]["s_cnt"] is True


def test_a_struct_input_takes_only_its_own_members():
    unit = _unit("two", ["a"], ["g_done"], {"a": "CTX *", "b": "CTX *"})
    normalize_pointer_parameters([unit])
    assert unit["input_vars"] == ["a[0].bitcount"]


def test_one_units_failure_leaves_the_others_normalized(monkeypatch):
    real = suts._normalize_unit_pointers

    def boom(unit, max_inp):
        if unit["name"] == "comp":
            raise RuntimeError("probe")
        return real(unit, max_inp)
    monkeypatch.setattr(suts, "_normalize_unit_pointers", boom)
    a = _unit("comp", ["u16p_Peak"], ["u16p_Peak"], {"u16p_Peak": "U16 *"})
    b = _unit("peak", ["v"], ["u16p_Peak"], {"u16p_Peak": "U16 *", "v": "U16"})
    got = normalize_pointer_parameters([a, b])
    assert got["errors"] == 1 and a["pointer_parameters"] == {"error": "RuntimeError"} and a["input_vars"] == ["u16p_Peak"]
    assert b["output_vars"] == ["u16p_Peak[0]"] and got["renamed"] == 1


def test_the_disclosure_lists_a_few_dropped_inputs_and_is_built():
    from report_gen.generation_disclosures import build_disclosures
    totals = normalize_pointer_parameters([_unit("untouched", ["ctx", "d"], ["g_done"], {"ctx": "CTX *", "d": "U8"})])
    assert totals["dropped_inputs"] == ["untouched.ctx"]
    items = {i["key"]: i for i in build_disclosures("suts", {"pointer_parameters": totals})}
    assert "(untouched.ctx)" in items["suts_pointer_parameters"]["note"]


def test_a_dropped_pointee_column_reruns_the_rows(monkeypatch):
    # (review I5 · I-R2-1) the final pass drops a pointee column no row derives: the rows run again as the document now
    #   observes them; a pass that drops nothing more stops — no cap flag
    calls = []
    real_apply = suts.apply_sequence_evidence
    monkeypatch.setattr(suts, "apply_sequence_evidence", lambda u, s, **k: calls.append(1) or real_apply(u, s, **k))
    drops = iter([["ctx[0].bitcount"], []])
    monkeypatch.setattr(suts, "_drop_underived_written_outputs", lambda u, s: next(drops))
    unit = _unit("init", [], ["ctx", "g_done"], {})
    unit["source_written_outputs"] = suts._new_written_record()
    unit["source_written_outputs"]["error"] = "x"   # add nothing late: only the drop path runs
    suts.complete_source_written_outputs(unit, [{"seq_num": 1, "inputs": {}, "expected": {}}])
    assert len(calls) == 1 and not unit["source_written_outputs"].get("pointee_rerun_cap_reached")


def test_a_pointee_the_scenario_search_needs_is_added(monkeypatch):
    # (review I4) the design lists `d` in and `ctx` out; reaching `g_done = d` needs `ctx[0].bitcount` — no expected
    #   value names that read (g_done's unwritten path is an observation), the scenario search does (`@pointee:` key)
    monkeypatch.setattr(suts, "_globals_type_cache", {"g_done": "U8", "g_gain": "U16"})
    unit = _unit("sc", ["d"], ["ctx", "g_done"], {"ctx": "CTX *", "d": "U8"})
    extended_unit_sequences(unit)
    assert "ctx[0].bitcount" in unit["source_read_inputs"]["added"]
    # only the scenario search can see it: no output depends on the branch (`s_hidden` is no column, and its unwritten
    #   path is an observation, not a read) — the reach target `s_hidden = d` needs the pointee's value
    unit = _unit("sc2", ["d"], ["ctx"], {"ctx": "CTX *", "d": "U8"})
    extended_unit_sequences(unit)
    added = unit["source_read_inputs"]["added"]
    assert added["ctx[0].bitcount"]["scenario_targets"] >= 1 and added["ctx[0].bitcount"]["slots"] == 0
