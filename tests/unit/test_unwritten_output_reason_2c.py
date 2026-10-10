"""Backlog 2-c — 'the observation needs the initial value' is not 'the function read it' (`generators/c_source_oracle.py`,
`generators/suts.py`).

An output written only on some paths holds its initial value on the others. The oracle used to give that cell the reason
`initial_value_not_in_inputs:X`, the same as a read before write: R19 then added X as an input (right — the cell needs
it) and the source findings called X 'read before written, missing from the input list' (wrong — the function never
read it). The path now records the objects it read while unset (`_State.initial_reads`); an output the path neither
wrote nor read gets `unwritten_output_initial_not_in_inputs:X`. R19 still adds it, marked `read_on_model: False`, and
the input-list gap finding leaves it out. 'Not read' is on the modeled run: an interpreted callee's reads are recorded;
a callee summarized by its write closure may read what the model never sees read (the disclosure says so)."""
from __future__ import annotations

import os
import types

import pytest

from generators import c_project_context as cpc
from generators import c_source_oracle as cso
from generators.suts import (
    complete_source_read_inputs,
    generate_sequences,
    input_list_gaps,
    source_read_names,
    summarize_source_read_inputs,
)

ROOT = os.path.join(os.sep, "proj")
H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
"""


def _run(text, name, inputs, outputs):
    path = os.path.join(ROOT, "unit.c")
    scope = cpc.build_scopes(cpc.build_project_context({path: text}), [path])[path]
    unit = {"name": name, "source_text": text, "source_path": path, "source_text_complete": True,
            "project_scope": scope}
    return cso.evaluate_outputs(unit, [inputs], [outputs])[0]


def _reason(result, name):
    return result["outputs"][name].get("reason")


# ── oracle ──────────────────────────────────────────────────────────────────────────────────────

def test_an_output_written_on_another_path_is_not_read_on_this_one():
    text = H + "U8 g_o;\nvoid f(U8 x) { if (x == 1U) { g_o = 9U; } }\n"
    assert _reason(_run(text, "f", {"x": 0}, ["g_o"]), "g_o") == "unwritten_output_initial_not_in_inputs:g_o"
    assert _run(text, "f", {"x": 1}, ["g_o"])["outputs"]["g_o"] == {"value": 9, "basis": "assigned"}


def test_an_output_read_in_a_condition_and_left_unwritten_keeps_the_read_reason():
    # the store never holds g_o (a read is not stored) — only the path's read record tells it was read
    text = H + "U8 g_o; U8 g_x;\nvoid f(void) { if (g_o > 1U) { g_x = 1U; } else { g_x = 1U; } }\n"
    result = _run(text, "f", {}, ["g_o", "g_x"])
    assert _reason(result, "g_o") == "initial_value_not_in_inputs:g_o"
    assert result["outputs"]["g_x"] == {"value": 1, "basis": "assigned"}


def test_a_read_modify_write_output_is_read():
    text = H + "U8 g_o;\nvoid f(void) { g_o += 1U; }\n"
    assert "initial_value_not_in_inputs:g_o" in _reason(_run(text, "f", {}, ["g_o"]), "g_o")


def test_an_unwritten_array_element_is_marked_too():
    # (a pointee: `test_pointer_param_pointee_r40.py` — `pq[0].buf[2]`)
    text = H + "U8 g_buf[4];\nvoid f(U8 x) { if (x == 1U) { g_buf[2] = 3U; } }\n"
    assert _reason(_run(text, "f", {"x": 0}, ["g_buf[2]"]), "g_buf[2]") == \
        "unwritten_output_initial_not_in_inputs:g_buf[2]"


# review C1: the verdict is every final path's, not the first path's — the same function with its arms swapped, an
#   early return, a switch: g_s is read on one path and written on another
@pytest.mark.parametrize("body", [
    "if (g_a > 1U) { g_x = 1U; } else { if (g_s == 1U) { g_s = 2U; } }",
    "if (g_a <= 1U) { if (g_s == 1U) { g_s = 2U; } } else { g_x = 1U; }",
    "if (g_a == 0U) { return; } if (g_s == 1U) { g_s = 2U; }",
    "switch (g_a) { case 1U: if (g_s == 1U) { g_s = 2U; } break; default: g_x = 1U; break; }",
], ids=["read_else", "read_then", "early_return", "switch"])
def test_a_read_on_any_final_path_is_a_read(body):
    text = H + "U8 g_a; U8 g_s; U8 g_x;\nvoid f(void) { " + body + " }\n"
    assert _reason(_run(text, "f", {}, ["g_s"]), "g_s") == "initial_value_not_in_inputs:g_s"


# review C2: an operand that runs on some executions (unknown left side of && / ||, unknown ?: condition) reads
@pytest.mark.parametrize("body", [
    "if ((g_a > 1U) && (g_s > 1U)) { g_x = 1U; }",
    "if ((g_a > 1U) || (g_s > 1U)) { g_x = 1U; }",
    "g_x = (g_a > 1U) ? g_s : 0U;",
], ids=["and", "or", "conditional"])
def test_an_operand_that_runs_on_some_executions_reads(body):
    text = H + "U8 g_a; U8 g_s; U8 g_x;\nvoid f(void) { " + body + " }\n"
    assert _reason(_run(text, "f", {}, ["g_s"]), "g_s") == "initial_value_not_in_inputs:g_s"


def test_the_arm_a_decided_conditional_does_not_take_reads_nothing():
    text = H + "U8 g_a; U8 g_s; U8 g_x;\nvoid f(void) { g_x = (g_a > 1U) ? g_s : 0U; }\n"
    assert _reason(_run(text, "f", {"g_a": 0}, ["g_s"]), "g_s") == "unwritten_output_initial_not_in_inputs:g_s"


# review W1: a read the model cannot place keeps the read reason for what it may reach — and only for that
def test_a_read_through_a_pointer_the_model_cannot_place_reaches_an_array():
    text = H + "U8 g_buf[4]; U8 g_x;\nvoid f(void) { U8 *p = g_buf; if (p[2] == 1U) { g_x = 1U; } }\n"
    assert _reason(_run(text, "f", {}, ["g_buf[2]"]), "g_buf[2]") == "initial_value_not_in_inputs:g_buf[2]"


def test_a_read_at_an_unknown_index_reads_the_array():
    text = H + "U8 g_buf[4]; U8 g_i; U8 g_x;\nvoid f(void) { if (g_buf[g_i] == 1U) { g_x = 1U; } }\n"
    assert _reason(_run(text, "f", {}, ["g_buf[2]"]), "g_buf[2]") == "initial_value_not_in_inputs:g_buf[2]"


def test_an_unknown_pointer_read_does_not_reach_a_scalar_whose_address_is_never_taken():
    text = H + ("U8 g_o; U8 g_x; U8 *g_p;\n"
                "void f(U8 x) { if (*g_p == 1U) { g_x = 1U; } if (x == 1U) { g_o = 1U; } }\n")
    assert _reason(_run(text, "f", {"x": 0}, ["g_o"]), "g_o") == "unwritten_output_initial_not_in_inputs:g_o"


def test_an_interpreted_callee_reading_through_its_pointer_parameter_reads():
    text = H + ("U8 g_buf[4]; U8 g_x;\n"
                "static U8 rd(const U8 *p) { return p[2]; }\n"
                "void f(void) { if (rd(g_buf) == 1U) { g_x = 1U; } }\n")
    assert _reason(_run_with_callees(text, "f", {}, ["g_buf[2]"]), "g_buf[2]") == \
        "initial_value_not_in_inputs:g_buf[2]"


def _run_with_callees(text, name, inputs, outputs):
    from generators.integration_oracle import CalleeProvider
    path = os.path.join(ROOT, "unit.c")
    files = {path: text}
    ctx = cpc.build_project_context(files)
    scopes = cpc.build_scopes(ctx, [path])
    unit = {"name": name, "source_text": text, "source_path": path, "source_text_complete": True,
            "project_scope": scopes[path], "callee_provider": CalleeProvider(ctx, files, scopes, cpc.shared_parser())}
    return cso.evaluate_outputs(unit, [inputs], [outputs])[0]


READS = "if (g_o > 1U) { g_x = 1U; } else { g_x = 1U; }"


@pytest.mark.parametrize("arms", [(READS, "g_x = 3U;"), ("g_x = 3U;", READS)], ids=["read_then", "read_else"])
def test_a_read_on_one_interpreted_callee_path_is_a_read_after_the_join(arms):
    # the callee forks on an unset global; only one of its paths reads g_o — the read in either arm (the join starts
    #   from the first final path)
    text = H + ("U8 g_a; U8 g_o; U8 g_x;\n"
                "static void h(U8 x) { if (x == 1U) { " + arms[0] + " } else { " + arms[1] + " } }\n"
                "void f(void) { h(g_a); }\n")
    assert _reason(_run_with_callees(text, "f", {}, ["g_o"]), "g_o") == "initial_value_not_in_inputs:g_o"


def test_a_callee_run_as_its_effects_only_reads_what_its_body_names():
    # no callee provider: h runs as its write closure (g_x) — review round 2: it may read what its body names (g_o)
    text = H + ("U8 g_o; U8 g_x;\n"
                "static void h(void) { if (g_o > 1U) { g_x = 1U; } else { g_x = 2U; } }\n"
                "void f(void) { h(); }\n")
    result = _run(text, "f", {}, ["g_o", "g_x"])
    assert _reason(result, "g_x") == "written_by_callee:h:g_x"
    assert _reason(result, "g_o") == "initial_value_not_in_inputs:g_o"


def test_a_callee_run_as_its_effects_only_does_not_read_what_it_never_names():
    text = H + ("U8 g_o; U8 g_x;\n"
                "static void h(void) { g_x = 1U; }\n"
                "void f(U8 x) { h(); if (x == 1U) { g_o = 1U; } }\n")
    assert _reason(_run(text, "f", {"x": 0}, ["g_o"]), "g_o") == "unwritten_output_initial_not_in_inputs:g_o"


def test_what_a_callee_reaches_through_a_macro_it_uses_is_read():
    text = H + ("U8 g_o; U8 g_x;\n#define LEVEL (g_o)\n"
                "static void h(void) { if (LEVEL > 1U) { g_x = 1U; } }\n"
                "void f(void) { h(); }\n")
    assert _reason(_run(text, "f", {}, ["g_o"]), "g_o") == "initial_value_not_in_inputs:g_o"


_NO_POINTERS = types.SimpleNamespace(world=None, arrays={}, address_taken=set())


def test_observing_twice_on_one_state_gives_the_same_answer_and_leaves_no_read_behind():
    state = cso._State()

    def read():   # what `_Interp.initial` does for an unset object
        state.initial_reads.add("g")
        return cso.Unknown("initial_value_not_in_inputs:g")

    first = cso._unwritten(read, "g", "g", state, _NO_POINTERS)
    second = cso._unwritten(read, "g", "g", state, _NO_POINTERS)
    assert first.reason == second.reason == "unwritten_output_initial_not_in_inputs:g"
    assert state.initial_reads == set()
    # another final path's read counts (review C1) and leaves this state's record as it was
    assert cso._unwritten(read, "g", "g", state, _NO_POINTERS, {"g"}).reason == "initial_value_not_in_inputs:g"
    assert state.initial_reads == set()
    state.initial_reads.add("g")   # the function's own read stays
    assert cso._unwritten(read, "g", "g", state, _NO_POINTERS).reason == "initial_value_not_in_inputs:g"
    assert state.initial_reads == {"g"}


def test_a_fork_copies_the_read_record():
    state = cso._State()
    state.initial_reads.add("g")
    copy = state.copy()
    copy.initial_reads.add("h")
    assert state.initial_reads == {"g"} and copy.initial_reads == {"g", "h"}


# ── SUTS (R19 and the source findings) ──────────────────────────────────────────────────────────

def test_source_read_names_tell_a_read_from_an_observation_only():
    seqs = [
        {"seq_num": 1, "expected_evidence": {
            "g_o": {"reason": "unwritten_output_initial_not_in_inputs:g_o"},
            "g_y": {"reason": "path_dependent:branch_on_unknown:initial_value_not_in_inputs:g_b"}}},
        {"seq_num": 2, "expected_evidence": {
            "g_o": {"reason": "unwritten_output_initial_not_in_inputs:g_o"},
            "g_p": {"reason": "initial_value_not_in_inputs:g_p"}}},
        {"seq_num": 3, "expected_evidence": {"g_p": {"reason": "unwritten_output_initial_not_in_inputs:g_p"}}},
    ]
    got = source_read_names(seqs)
    assert got["g_o"] == {"slots": 2, "sequences": [1, 2], "read": False}
    assert got["g_b"]["read"] is True
    # one slot where the function read it is enough — a later observation-only slot does not undo it
    assert got["g_p"] == {"slots": 2, "sequences": [2, 3], "read": True}


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
U8 g_o;
void cond(void)
{
    if (g_a > 1U) { if (g_b > 1U) { g_o = 1U; } }
}
"""


def _unit():
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "unit.c"): UNIT}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "unit.c")
    return {"name": "cond", "fid": "F1", "source_text": UNIT, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(context, [path])[path], "input_vars": ["g_a"], "output_vars": ["g_o"],
            "param_types": {"g_a": "U8", "g_o": "U8"}}


def _ext(unit):
    seqs = generate_sequences(unit, None, type_cache={}, extended=True, boundary_rows=False)
    return complete_source_read_inputs(unit, seqs, lambda: generate_sequences(unit, None, type_cache={}, extended=True,
                                                                             boundary_rows=False))


def test_r19_still_adds_the_unwritten_output_but_the_gap_finding_names_only_what_the_function_read():
    unit = _unit()
    seqs = _ext(unit)
    added = unit["source_read_inputs"]["added"]
    # g_o is needed for the cells where the branch is not taken — added, marked as not read
    assert added["g_o"]["read_on_model"] is False
    assert added["g_b"]["read_on_model"] is True
    assert set(input_list_gaps(unit, seqs)) == {"g_b"}
    s = summarize_source_read_inputs([unit])
    assert s["names_added"] == 2 and s["names_added_for_unwritten_outputs"] == 1


def test_without_r19_the_gap_finding_still_names_only_what_the_function_read():
    # the base profile (no R19): the gap finding reads the row reasons directly
    unit = _unit()
    seqs = [{"seq_num": 1, "expected_evidence": {
        "g_o": {"reason": "unwritten_output_initial_not_in_inputs:g_o"},
        "g_x": {"reason": "path_dependent:branch_on_unknown:initial_value_not_in_inputs:g_b"}}}]
    assert set(input_list_gaps(unit, seqs)) == {"g_b"}


def test_the_disclosure_says_which_added_names_the_function_did_not_read():
    from report_gen.generation_disclosures import build_disclosures
    unit = _unit()
    _ext(unit)
    (item,) = [i for i in build_disclosures("suts", {"source_read_inputs": summarize_source_read_inputs([unit])})
               if i["key"] == "suts_source_read_inputs"]
    assert "그중 1 이름은 함수 실행 모델에서 읽힌 근거가 없고" in item["note"]
    assert "입력 목록 결손 소견에는 넣지 않는다" in item["note"]
    assert "모델이 읽음을 귀속하지 못하면 읽은 것으로 둔다" in item["note"]


def test_a_dereference_the_model_cannot_place_reaches_an_address_taken_object():
    text = H + "U8 g_v; U8 g_x;\nvoid f(void) { U8 *p = &g_v; if (*p == 1U) { g_x = 1U; } }\n"
    assert _reason(_run(text, "f", {}, ["g_v"]), "g_v") == "initial_value_not_in_inputs:g_v"


def test_a_member_read_through_a_pointer_the_model_cannot_place_reaches_the_struct():
    text = H + ("typedef struct { U8 a; U8 b; } S;\nS g_s; U8 g_x;\n"
                "void f(void) { S *p = &g_s; if (p->a == 1U) { g_x = 1U; } }\n")
    assert _reason(_run(text, "f", {}, ["g_s.a"]), "g_s.a") == "initial_value_not_in_inputs:g_s.a"


def test_an_operand_that_runs_on_some_executions_reads_even_when_it_is_undefined_there():
    # the shift is out of range for a 16-bit int: undefined where it runs — what it read before stays a read
    text = H + "U8 g_a; U8 g_s; U8 g_x;\nvoid f(void) { if ((g_a > 1U) && ((g_s << 20) > 1)) { g_x = 1U; } }\n"
    result = _run(text, "f", {}, ["g_s"])
    assert result["possible_undefined_behavior"] == ["operand_under_unknown_condition"]
    assert _reason(result, "g_s") == "initial_value_not_in_inputs:g_s"


# ── review round 2 W1: reads the model does not evaluate, fail-closed ──────────────────────────────────────────────

ST = "typedef struct { U8 a; U8 b; } S;\n"


@pytest.mark.parametrize("body", [
    "S t = g_s; if (t.a == 1U) { g_x = 1U; }",
    "g_c = g_s;",
], ids=["local_copy", "struct_assignment"])
def test_a_whole_struct_read_reads_its_members(body):
    text = H + ST + "S g_s; S g_c; U8 g_x;\nvoid f(void) { " + body + " }\n"
    assert _reason(_run(text, "f", {}, ["g_s.a"]), "g_s.a") == "initial_value_not_in_inputs:g_s.a"


def test_a_struct_passed_by_value_to_an_interpreted_callee_is_read():
    text = H + ST + ("S g_s; U8 g_x;\n"
                     "static U8 rd(S v) { return v.a; }\n"
                     "void f(void) { if (rd(g_s) == 1U) { g_x = 1U; } }\n")
    assert _reason(_run_with_callees(text, "f", {}, ["g_s.a"]), "g_s.a") == "initial_value_not_in_inputs:g_s.a"


def test_a_member_of_an_object_a_macro_names_is_read():
    text = H + ST + "S g_s; U8 g_x;\n#define OBJ g_s\nvoid f(void) { if (OBJ.a == 1U) { g_x = 1U; } }\n"
    assert _reason(_run(text, "f", {}, ["g_s.a"]), "g_s.a") == "initial_value_not_in_inputs:g_s.a"


def test_an_undecided_macro_reads_every_object_its_definitions_name():
    text = H + ("U8 g_s; U8 g_t; U8 g_x;\n#if (CFG_SEL == 1)\n#define SRC g_s\n#else\n#define SRC g_t\n#endif\n"
                "void f(void) { if (SRC == 1U) { g_x = 1U; } }\n")
    result = _run(text, "f", {}, ["g_s", "g_t"])
    assert _reason(result, "g_s") == "initial_value_not_in_inputs:g_s"
    assert _reason(result, "g_t") == "initial_value_not_in_inputs:g_t"


def test_a_part_read_of_one_member_array_does_not_reach_a_sibling_member():
    # review round 2 I-b: an unknown index into g_t.t reads g_t.t[*], not g_t.a
    text = H + ("typedef struct { U8 t[4]; U8 a; } T;\nT g_t; U8 g_i; U8 g_x;\n"
                "void f(U8 x) { if (g_t.t[g_i] == 1U) { g_x = 1U; } if (x == 1U) { g_t.a = 1U; } }\n")
    result = _run(text, "f", {"x": 0}, ["g_t.t[2]", "g_t.a"])
    assert _reason(result, "g_t.t[2]") == "initial_value_not_in_inputs:g_t.t[2]"
    assert _reason(result, "g_t.a") == "unwritten_output_initial_not_in_inputs:g_t.a"


def test_an_object_whose_address_is_taken_in_another_function_is_reachable():
    # review round 2 M3: `&g_v` in another function (project-wide address_taken), not on this path
    text = H + ("U8 g_v; U8 g_x; U8 *g_p;\nvoid put(U8 *d);\n"
                "void other(void) { put(&g_v); }\n"
                "void f(void) { if (*g_p == 1U) { g_x = 1U; } }\n")
    assert _reason(_run(text, "f", {}, ["g_v"]), "g_v") == "initial_value_not_in_inputs:g_v"


def test_a_callee_run_as_its_effects_only_may_read_through_a_pointer_it_is_given():
    # no provider: rd's closure names only p — the array it reads through p is reachable by a pointer
    text = H + ("U8 g_buf[4]; U8 g_x;\n"
                "static U8 rd(const U8 *p) { return p[2]; }\n"
                "void f(void) { if (rd(g_buf) == 1U) { g_x = 1U; } }\n")
    assert _reason(_run(text, "f", {}, ["g_buf[2]"]), "g_buf[2]") == "initial_value_not_in_inputs:g_buf[2]"


def test_a_callee_whose_macro_text_is_opaque_may_read_anything():
    text = H + ("U8 g_o; U8 g_x;\n#define CAT(a, b) a##b\n"
                "static void h(void) { g_x = CAT(g_, o); }\n"
                "void f(U8 x) { h(); if (x == 1U) { g_o = 1U; } }\n")
    assert _reason(_run(text, "f", {"x": 0}, ["g_o"]), "g_o") == "initial_value_not_in_inputs:g_o"


def test_an_added_name_the_last_rows_read_is_a_gap_after_all():
    # review round 2 I-e: added for an unwritten output, but a final row (an MC/DC vector's blank cell) read it
    unit = _unit()
    unit["source_read_inputs"] = {"added": {"g_o": {"read_on_model": False}, "g_b": {"read_on_model": False}}}
    unit["input_vars"] = ["g_a", "g_o", "g_b"]   # R19 added both
    seqs = [{"seq_num": 1, "expected_evidence": {"g_x": {"reason": "initial_value_not_in_inputs:g_o"}}}]
    gaps = input_list_gaps(unit, seqs)
    assert set(gaps) == {"g_o"} and gaps["g_o"]["added"] is True


# review round 3 W1: code the model cannot see (a function defined nowhere, inline assembly, an unmodeled macro call)
#   may read anything — whichever arm it is in
@pytest.mark.parametrize("arms", [("g_a = 0U;", "ext();"), ("ext();", "g_a = 0U;"),
                                  ("g_a = 0U;", "__asm__ volatile (\"nop\");")],
                         ids=["unknown_callee_else", "unknown_callee_then", "inline_asm"])
def test_code_the_model_cannot_see_may_read_anything(arms):
    text = H + ("U8 g_a; U8 g_o;\nvoid ext(void);\n"
                "void f(U8 x) { if (g_a > 1U) { " + arms[0] + " } else { " + arms[1] + " } if (x == 1U) { g_o = 1U; } }\n")
    reason = _reason(_run(text, "f", {"x": 0}, ["g_o"]), "g_o")
    assert not reason.startswith("unwritten_output_initial_not_in_inputs")


def test_macro_read_marks_are_computed_once_per_macro():
    text = H + ("U8 g_s; U8 g_t; U8 g_x;\n#if (CFG_SEL == 1)\n#define SRC g_s\n#else\n#define SRC g_t\n#endif\n"
                "void f(void) { if (SRC == 1U) { g_x = 1U; } if (SRC == 2U) { g_x = 2U; } }\n")
    calls = []
    real = cso._Interp.macro_read_marks

    def counting(self, name):
        calls.append(name)
        return real(self, name)

    cso._Interp.macro_read_marks = counting
    try:
        result = _run(text, "f", {}, ["g_s", "g_t"])
    finally:
        cso._Interp.macro_read_marks = real
    assert calls == ["SRC"]
    assert _reason(result, "g_s") == "initial_value_not_in_inputs:g_s"



def test_a_macro_the_model_cannot_evaluate_reads_through_the_macros_it_names():
    # PAIR is not one operand (a comma list): unevaluated — it names INNER, which names g_s
    text = H + ("U8 g_s; U8 g_t; U8 g_x;\n#define INNER g_s\n#define PAIR INNER, g_t\n"
                "void f(U8 x) { if ((PAIR) == 1U) { g_x = 1U; } if (x == 1U) { g_s = 1U; } }\n")
    result = _run(text, "f", {"x": 0}, ["g_s"])
    assert _reason(result, "g_s") == "initial_value_not_in_inputs:g_s", result
