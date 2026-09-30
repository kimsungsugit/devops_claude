"""R42 — the SITS clang harness declares the struct objects the model flattens (R39) and checks their members.

Since R39 the source oracle models a struct global's scalar members and member arrays as objects ``g.a`` / ``g.b[2]``,
and the generated SITS states integrated values for them. The integrated clang harness (R16b) did not model struct
objects at all: an entry that names one did not compile (HDPDM01 at HEAD: ``DiagData`` 777 claims, ``lin_tl_rx_queue``
220), a callee that names one was cut, and a member observable was ``observable_not_in_harness`` (185) — so every value
the model added through R39 in SITS went unchecked. Now such an object is a member of the harness world holding exactly
the members the model flattens; code using any other member still does not compile (cut / group failure — unchecked,
never agreed), and its members are inputs and observables by the model's names.
"""
from __future__ import annotations

import os
import shutil

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs
from generators.integration_oracle import CalleeProvider
from scripts import integration_oracle_clang_check as ioc

ROOT = os.path.join(os.sep, "virt_r42")
COMMON = """#ifndef C42_H
#define C42_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef struct { U8 cnt; U16 arr[4]; struct { U8 x; } in; } DIAG_T;
typedef struct { U8 a; U8 *p; } OPQ_T;
extern DIAG_T g_diag;
extern OPQ_T g_opq;
extern U8 g_out;
void b_bump(void);
U8 b_read(void);
void b_opq(void);
#endif
"""
A = """#include "c42.h"
DIAG_T g_diag;
OPQ_T g_opq;
U8 g_out;
void entry(void) { b_bump(); g_out = (U8)(g_diag.cnt + b_read()); }
void touch(void) { g_diag.arr[1] = 7U; g_diag.in.x = 3U; }
void opq_entry(void) { g_opq.p = 0; g_out = g_opq.a; }
void via_opq(void) { b_opq(); g_out = 4U; }
void local_use(void) { g_diag.cnt = 4U; g_out = (U8)(g_diag.cnt + 1U); }
void other(void) { g_out = 1U; }
"""
B = """#include "c42.h"
void b_bump(void) { g_diag.cnt = (U8)(g_diag.cnt + 1U); }
U8 b_read(void) { return (U8)g_diag.arr[2]; }
void b_opq(void) { g_opq.p = 0; }
"""
FILES = {os.path.join(ROOT, "c42.h"): COMMON, os.path.join(ROOT, "a.c"): A, os.path.join(ROOT, "b.c"): B}
A_PATH = os.path.join(ROOT, "a.c")
needs_clang = pytest.mark.skipif(shutil.which("clang") is None, reason="clang (msp430 target) not installed")


@pytest.fixture(scope="module")
def project():
    ctx = cpc.build_project_context(FILES)
    scopes = cpc.build_scopes(ctx, [p for p in FILES if p.endswith(".c")])
    parser = cpc.shared_parser()
    return FILES, scopes, CalleeProvider(ctx, FILES, scopes, parser), parser


def _claims(project, name, cases):
    files, scopes, provider, _parser = project
    unit = {"name": name, "source_text": files[A_PATH], "source_path": A_PATH, "source_text_complete": True,
            "project_scope": scopes[A_PATH], "callee_provider": provider}
    out = []
    for inputs, outputs, sentinel in cases:
        rec = evaluate_outputs(unit, [inputs], [list(outputs)])[0]
        derived = {k: v["value"] for k, v in rec["outputs"].items() if "value" in v}
        ip = rec.get("interprocedural") or {}
        out.append({"inputs": inputs, "outputs": {**derived, **sentinel}, "possible_ub": [], "derived": derived,
                    "interpreted": set(ip.get("inlined") or ()), "effects_only": set(ip.get("effects_only") or ())})
    return out


def _check(project, name, claims, tmp_path):
    files, scopes, provider, parser = project
    return ioc.check_group(name, A_PATH, claims, files, scopes, provider, parser, work_dir=str(tmp_path / name))


# ── without clang ─────────────────────────────────────────────────────────────────────────────

def test_the_fixture_is_flattened_as_in_the_real_trees(project):
    _files, scopes, _provider, _parser = project
    sg = scopes[A_PATH]["struct_globals"]
    assert sg["g_diag"]["members"] == ["arr", "cnt", "in.x"] and not sg["g_diag"]["opaque_members"]
    assert sg["g_opq"]["members"] == ["a"] and sg["g_opq"]["opaque_members"]   # the pointer member is not modeled


def test_member_names_address_their_object():
    assert ioc._object_name("g.a") == "g" and ioc._object_name("g.s.x") == "g" and ioc._object_name("g.b[2]") == "g"
    assert ioc._object_name("arr[3]") == "arr" and ioc._object_name("x") == "x"
    assert ioc._object_name("F() return") == "F() return"
    assert ioc._MEMBER_NAME.match("g.b[2]").groups() == ("g", "b", "2")
    assert ioc._MEMBER_NAME.match("g.s.x").groups() == ("g", "s.x", None)
    assert ioc._MEMBER_NAME.match("g..a") is None and ioc._MEMBER_NAME.match("g.b[2].c") is None


def test_a_struct_record_holds_the_flattened_members(project):
    _files, scopes, _provider, _parser = project
    rec = ioc._struct_record(scopes[A_PATH], "g_diag")
    assert set(rec["fields"]) == {"arr", "cnt", "in.x"}
    assert rec["fields"]["arr"][0] == "array" and rec["fields"]["arr"][1]["length"] == 4
    assert ioc._struct_record(scopes[A_PATH], "g_out") is None
    # a member the tables do not hold: not a struct the harness can lay out
    broken = {"struct_globals": {"g": {"members": ["a", "b"], "typename": "T", "static": False}},
              "globals": {"g.a": {"type": {"kind": "char", "bits": 8, "signed": False, "rank": 1}}}, "arrays": {}}
    assert ioc._struct_record(broken, "g") is None


def test_two_units_see_one_struct_object_only_when_they_flatten_it_alike(project):
    _files, scopes, _provider, _parser = project
    a = ioc._struct_record(scopes[A_PATH], "g_diag")
    b = ioc._struct_record(scopes[os.path.join(ROOT, "b.c")], "g_diag")
    assert set(ioc._merge_record("struct", a, b, "g_diag")["fields"]) == {"arr", "cnt", "in.x"}
    fewer = {**b, "fields": {k: v for k, v in b["fields"].items() if k != "in.x"}}
    with pytest.raises(ioc._Failure):
        ioc._merge_record("struct", a, fewer, "g_diag")
    other = {**b, "typename": "OTHER_T"}
    with pytest.raises(ioc._Failure):
        ioc._merge_record("struct", a, other, "g_diag")
    wider = {**b, "fields": {**b["fields"], "arr": ("array", {**b["fields"]["arr"][1], "length": 8})}}
    with pytest.raises(ioc._Failure):
        ioc._merge_record("struct", a, wider, "g_diag")


# ── with clang ────────────────────────────────────────────────────────────────────────────────

@needs_clang
def test_member_inputs_and_observables_are_checked_across_units(project, tmp_path):
    claims = _claims(project, "entry", [({"g_diag.cnt": 5, "g_diag.arr[2]": 9}, ["g_out", "g_diag.cnt"], {}),
                                        ({"g_diag.cnt": 5, "g_diag.arr[2]": 9}, ["g_diag.cnt"], {"g_diag.cnt": 7})])
    assert claims[0]["derived"] == {"g_out": 15, "g_diag.cnt": 6}   # b.c's callees read and write the members
    final, notes = _check(project, "entry", claims, tmp_path)
    assert not notes["cut"], notes
    assert {k: v for k, (v, _d) in final.items()} == {(0, "g_out"): "agree", (0, "g_diag.cnt"): "agree",
                                                       (1, "g_diag.cnt"): "mismatch"}


@needs_clang
def test_nested_members_and_member_arrays_are_observables(project, tmp_path):
    claims = _claims(project, "touch", [({"g_diag.arr[3]": 2}, ["g_diag.arr[1]", "g_diag.in.x", "g_diag.arr[3]"], {}),
                                        ({}, ["g_diag.arr[1]"], {"g_diag.arr[1]": 8})])
    assert claims[0]["derived"] == {"g_diag.arr[1]": 7, "g_diag.in.x": 3, "g_diag.arr[3]": 2}
    final, _notes = _check(project, "touch", claims, tmp_path)
    assert {k: v for k, (v, _d) in final.items()} == {(0, "g_diag.arr[1]"): "agree", (0, "g_diag.in.x"): "agree",
                                                       (0, "g_diag.arr[3]"): "agree", (1, "g_diag.arr[1]"): "mismatch"}


@needs_clang
def test_an_input_the_claim_does_not_set_takes_the_fills(project, tmp_path):
    # the member the claim leaves unset varies with the fills: a value resting on it is no agreement
    claims = [{"inputs": {"g_diag.arr[2]": 9}, "outputs": {"g_out": 10}, "possible_ub": []}]
    final, _notes = _check(project, "entry", claims, tmp_path)
    assert final[(0, "g_out")][0] == "mismatch"


@needs_clang
def test_a_member_the_model_does_not_flatten_is_not_observable(project, tmp_path):
    claims = [{"inputs": {"g_opq.a": 3}, "outputs": {"g_opq.p": 0, "g_diag.arr[9]": 0, "g_out.x": 0, "g_diag.in.x": 3},
               "possible_ub": []}]
    final, _notes = _check(project, "touch", claims, tmp_path)
    assert final[(0, "g_opq.p")][0] == final[(0, "g_diag.arr[9]")][0] == "unchecked:observable_not_in_harness"
    assert final[(0, "g_out.x")][0] == "unchecked:observable_not_in_harness"   # a member of no struct object
    assert final[(0, "g_diag.in.x")][0] == "agree"                            # the rest of the claim is still checked


@needs_clang
def test_a_struct_object_only_the_body_names_is_declared(project, tmp_path):
    claims = _claims(project, "local_use", [({}, ["g_out"], {})])
    assert claims[0]["derived"] == {"g_out": 5}
    final, notes = _check(project, "local_use", claims, tmp_path)
    assert final == {(0, "g_out"): ("agree", "")}, notes


@needs_clang
def test_a_member_no_compiled_function_uses_is_placed_from_the_entry_unit(project, tmp_path):
    # ``other`` never names g_diag: the entry unit's declaration places it, and the run leaves it as the claim set it
    claims = _claims(project, "other", [({"g_diag.arr[3]": 2}, ["g_diag.arr[3]", "g_out"], {})])
    assert claims[0]["derived"] == {"g_diag.arr[3]": 2, "g_out": 1}
    final, notes = _check(project, "other", claims, tmp_path)
    assert final == {(0, "g_diag.arr[3]"): ("agree", ""), (0, "g_out"): ("agree", "")}, notes


@needs_clang
def test_code_using_an_unmodeled_member_stays_unchecked(project, tmp_path):
    # an entry naming it: the group fails (never agreed)
    final, notes = _check(project, "opq_entry", [{"inputs": {"g_opq.a": 3}, "outputs": {"g_out": 3},
                                                  "possible_ub": []}], tmp_path)
    assert final is None and "does_not_compile" in notes["failure"], notes
    # (review W-r2-1) the failure names no temporary path: clang's "(unnamed struct at <work dir>…)" is normalized before
    #   the message is cut short (pytest's tmp_path is long enough to put the closing parenthesis past the cut)
    assert "unnamed struct at" not in notes["failure"]
    # a callee naming it: cut — its writes are missing, so only a value it cannot reach is agreed (weakly)
    claims = _claims(project, "via_opq", [({}, ["g_out"], {})])
    assert claims[0]["derived"] == {"g_out": 4}
    final, notes = _check(project, "via_opq", claims, tmp_path)
    assert "b_opq" in notes["cut"] and final[(0, "g_out")][0] == "agree_with_cut_callees"


# ── review round 1: two objects of one name, an enum member, stable failure keys ─────────────────

ROOT2 = os.path.join(os.sep, "virt_r42b")
H2 = """#ifndef H2_H
#define H2_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef struct { U8 cnt; U16 w; } DT;
typedef union { U8 cnt; U16 w; } UT;
enum en_s { S_A = 0, S_B = 1 };
typedef struct { enum en_s st; U8 k; } ES;
extern U8 g_out;
void b_set(void);
void c_set(void);
#endif
"""
A2 = """#include "h2.h"
U8 g_out;
static DT s_d;
ES g_es;
void e1(void) { s_d.cnt = 1U; c_set(); g_out = s_d.cnt; }
void e2(void) { s_d.cnt = 1U; b_set(); g_out = s_d.cnt; }
void f_es(U8 x) { g_es.k = x; g_es.st = x; g_out = (U8)(g_es.st == 200U); }
static U8 s_y;
void b_sety(void);
void e3(void) { s_y = 1U; b_sety(); g_out = s_y; }
"""
B2 = """#include "h2.h"
static UT s_d;
void b_set(void) { s_d.cnt = 9U; }
static BT_UNKNOWN s_y;
void b_sety(void) { s_y = 9U; }
void e5(void) { c_set(); }
"""
C2 = """#include "h2.h"
static DT s_d;
void c_set(void) { s_d.cnt = 9U; }
"""
FILES2 = {os.path.join(ROOT2, "h2.h"): H2, os.path.join(ROOT2, "a2.c"): A2, os.path.join(ROOT2, "b2.c"): B2,
          os.path.join(ROOT2, "c2.c"): C2}
A2_PATH = os.path.join(ROOT2, "a2.c")


@pytest.fixture(scope="module")
def project2():
    ctx = cpc.build_project_context(FILES2)
    scopes = cpc.build_scopes(ctx, [p for p in FILES2 if p.endswith(".c")])
    parser = cpc.shared_parser()
    return FILES2, scopes, CalleeProvider(ctx, FILES2, scopes, parser), parser


def _check2(project2, name, claims, tmp_path, path=A2_PATH):
    files, scopes, provider, parser = project2
    return ioc.check_group(name, path, claims, files, scopes, provider, parser, work_dir=str(tmp_path / name))


def test_the_second_fixture_models_what_it_should(project2):
    _files, scopes, _provider, _parser = project2
    assert "s_d" in scopes[A2_PATH]["struct_globals"] and scopes[A2_PATH]["struct_globals"]["s_d"]["static"]
    b = scopes[os.path.join(ROOT2, "b2.c")]
    assert "s_d" not in b["struct_globals"] and "s_d" in b["unresolved_globals"]   # a union is not modeled
    assert b["unmodeled_object_linkage"]["s_d"] is True


@needs_clang
def test_two_units_static_struct_objects_stay_two(project2, tmp_path):
    # (review W2) c2.c's ``static DT s_d`` is not a2.c's: the entry reads back its own 1, never the callee's 9
    claims = [{"inputs": {}, "outputs": {"g_out": 1, "s_d.cnt": 1}, "possible_ub": []},
              {"inputs": {}, "outputs": {"g_out": 9}, "possible_ub": []}]
    final, notes = _check2(project2, "e1", claims, tmp_path)
    assert final == {(0, "g_out"): ("agree", ""), (0, "s_d.cnt"): ("agree", ""), (1, "g_out"): final[(1, "g_out")]}
    assert final[(1, "g_out")][0] == "mismatch", notes


@needs_clang
def test_an_object_its_own_unit_does_not_model_is_never_another_units(project2, tmp_path):
    # (review W1) b2.c's ``static UT s_d`` (a union — not modeled) must not compile against a2.c's struct member: the
    #   callee is cut, so a value resting on its write is never agreed with
    claims = [{"inputs": {}, "outputs": {"g_out": 9}, "possible_ub": []},
              {"inputs": {}, "outputs": {"g_out": 1}, "possible_ub": []}]
    final, notes = _check2(project2, "e2", claims, tmp_path)
    assert "b_set" in notes["cut"], notes
    assert final[(0, "g_out")][0] == "unchecked:cut_callee_reached"
    assert final[(1, "g_out")][0] == "agree_with_cut_callees"


@needs_clang
def test_an_enum_member_makes_the_claim_hold_for_every_underlying_type(project2, tmp_path):
    # (review I1) ``g_es.st = 200`` is 200 for an int base but -56 for a signed char one: the enum-base loop runs for a
    #   struct whose only enum is a member
    final, _notes = _check2(project2, "f_es", [{"inputs": {"x": 200}, "outputs": {"g_out": 1}, "possible_ub": []},
                                               {"inputs": {"x": 5}, "outputs": {"g_out": 0}, "possible_ub": []}],
                            tmp_path)
    assert final[(0, "g_out")][0] == "mismatch" and final[(1, "g_out")][0] == "agree"


def test_failure_keys_do_not_carry_the_runs_temporary_path():
    # (review I2) one cause, one key — clang names an unnamed struct by its place in this run's work directory
    a = "entry_does_not_compile:no member named 'tl_pdu' in '__oracle_v0::__oracle_world::(unnamed struct at C:/T/x1/g000.cpp:12:3)'"
    b = a.replace("x1/g000.cpp:12:3", "y7/g014.cpp:40:9")
    assert ioc._stable(a) == ioc._stable(b) and "(unnamed struct)" in ioc._stable(a)


@needs_clang
def test_a_static_its_own_unit_cannot_type_is_never_another_units_scalar(project2, tmp_path):
    # (review W1, the internal-linkage half) b2.c's ``static BT_UNKNOWN s_y`` is unresolved there and a2.c's
    #   ``static U8 s_y`` is a scalar world member: without the block the callee's ``s_y = 9U`` would compile against it
    _files, scopes, _provider, _parser = project2
    b = scopes[os.path.join(ROOT2, "b2.c")]
    assert "s_y" in b["unresolved_globals"] and b["unmodeled_object_linkage"]["s_y"] is True
    claims = [{"inputs": {}, "outputs": {"g_out": 9}, "possible_ub": []},
              {"inputs": {}, "outputs": {"g_out": 1}, "possible_ub": []}]
    final, notes = _check2(project2, "e3", claims, tmp_path)
    assert "b_sety" in notes["cut"], notes
    assert final[(0, "g_out")][0] == "unchecked:cut_callee_reached"
    assert final[(1, "g_out")][0] == "agree_with_cut_callees"


@needs_clang
def test_an_observable_the_entry_unit_does_not_model_is_not_another_units(project2, tmp_path):
    # (review I-r2-2) e5's unit (b2.c) holds ``s_d`` as a union it does not model; c2.c's flattened ``static DT s_d`` is
    #   in the world because e5 reaches c_set — the claim's ``s_d.cnt`` must not be read from that other object
    claims = [{"inputs": {}, "outputs": {"s_d.cnt": 9, "g_out": 0}, "possible_ub": []}]
    final, notes = _check2(project2, "e5", claims, tmp_path, path=os.path.join(ROOT2, "b2.c"))
    assert final is not None, notes
    assert final[(0, "s_d.cnt")][0] == "unchecked:observable_not_in_harness"
