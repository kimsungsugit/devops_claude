"""R39 — a struct object's scalar members are objects of their own name (``g.a`` · ``g.s.x`` · ``g.b[2]``).

The reference SUTS sets struct members as inputs by that name (KJPDS02_PV ``lin_tl_rx_queue.queue_header``). Until R39
every struct global was ``global_not_scalar:struct`` — a read of a member was ``field_unmodeled`` and a condition on it
was ``unsupported_scalar:field_expression``. The project context now records struct bodies and flattens a struct
object's members (unions, bit-fields, const objects and arrays of structs are not modeled; a pointer or unresolved
member flags the struct ``opaque_members``); the source oracle reads and writes ``g.a`` as an object, a write to the
struct (or an enclosing member) makes every member under it unknown; MC/DC searches such conditions in a group of their
own; the clang harness declares a local struct of the modeled members; R19 adds read members as inputs.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from generators import c_project_context as cpc  # noqa: E402

ROOT = os.path.join(os.sep, "p39")
H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef struct { U8 a; U16 b[4]; struct { U8 x; S16 y; } s; } T;
typedef struct { U8 *p; U8 v; } TP;
typedef union { U8 a; U16 w; } TU;
typedef struct { U8 f : 3; U8 k; } TB;
struct tag { U8 m; };
typedef struct tag TT;
"""
C = """#include "h.h"
T g;
T h;
T g_taken;
TP gp;
TU gu;
TB gb;
struct tag gt;
TT gtt;
const T gc = {0};
T garr[2];
volatile T gv;
struct { U8 q; } ga;
U8 g_o;
U8 g_en;
U8 *g_ptr;
void wr(void);
void wrp(void);
void f1(void) { g_o = (U8)(g.a + g.s.x); }
void f2(U8 i) { g.b[i] = 7U; g_o = (U8)g.b[2]; }
void f3(void) { g.s = h.s; g_o = g.s.x; }
void f4(void) { wr(); g_o = g.a; }
void f5(void) { *g_ptr = 1U; g_o = (U8)(g.a + g_taken.a); }
void f6(void) { g.a = 9U; }
void f7(void) { wrp(); g_o = g_taken.a; }
void f8(void) { g_o = gv.a; }
void f9(void) { T g; g.a = 5U; g_o = g.a; }
void f10(void) { wr(); g_o = g_taken.a; }
void f11(void) { g_taken.a = 5U; g.a = 6U; *g_ptr = 1U; g_o = (U8)(g.a + g_taken.a); }
void d1(void) { if ((g.a == 3U) && (g.s.x == 4U)) { g_o = 1U; } else { g_o = 2U; } }
void d3(TP *p) { if ((p->v == 3U) && (g_en == 1U)) { g_o = 1U; } }
U8 *keep(void) { return &g_taken.a; }
"""
L = """#include "h.h"
extern T g;
extern TP gp;
void wr(void) { g.s.x = 1U; }
void wrp(void) { gp.p[0] = 1U; }
"""


def _scope():
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "u.c"): C, os.path.join(ROOT, "l.c"): L}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "u.c")
    return path, cpc.build_scopes(context, [path])[path]


PATH, SCOPE = _scope()


def _unit(name, inputs=()):
    return {"name": name, "source_text": C, "source_path": PATH, "source_text_complete": True,
            "project_scope": SCOPE, "input_vars": list(inputs)}


def _run(name, inputs, outs):
    from generators.c_source_oracle import evaluate_outputs
    (r,) = evaluate_outputs(_unit(name), [inputs], [outs])
    return r["outputs"]


# ── project context ────────────────────────────────────────────────────────────────────────────

def test_a_struct_object_is_flattened_into_member_objects():
    assert SCOPE["struct_globals"]["g"]["members"] == ["a", "b", "s.x", "s.y"]
    assert {k for k in SCOPE["globals"] if k.startswith("g.")} == {"g.a", "g.s.x", "g.s.y"}
    assert SCOPE["arrays"]["g.b"]["length"] == 4 and SCOPE["globals"]["g.s.y"]["typename"] == "S16"
    assert "g" in SCOPE["unresolved_globals"]   # the object itself: a whole-struct read or write is not modeled


def test_tagged_aliased_and_anonymous_structs_are_flattened():
    assert SCOPE["struct_globals"]["gt"]["members"] == ["m"]
    assert SCOPE["struct_globals"]["gtt"]["members"] == ["m"]
    assert SCOPE["struct_globals"]["ga"]["members"] == ["q"]


def test_unions_bit_fields_const_objects_and_arrays_of_structs_are_not_modeled():
    for name in ("gu", "gb", "gc", "garr"):
        assert name not in SCOPE["struct_globals"], name
        assert not any(k.startswith(name + ".") for k in SCOPE["globals"]), name


def test_a_pointer_member_is_left_out_and_flags_the_struct():
    rec = SCOPE["struct_globals"]["gp"]
    assert rec["members"] == ["v"] and rec["opaque_members"] and rec["unmodeled_members"] == ["p"]
    assert not SCOPE["struct_globals"]["g"]["opaque_members"]


def test_a_volatile_struct_makes_its_members_volatile():
    assert SCOPE["globals"]["gv.a"]["volatile"] and SCOPE["arrays"]["gv.b"]["volatile"]


# ── source oracle ──────────────────────────────────────────────────────────────────────────────

def test_members_are_read_and_written_as_objects():
    assert _run("f1", {"g.a": 3, "g.s.x": 4}, ["g_o"])["g_o"] == {"value": 7, "basis": "assigned"}
    assert _run("f6", {}, ["g.a"])["g.a"] == {"value": 9, "basis": "assigned"}
    out = _run("f2", {"i": 2}, ["g_o", "g.b[2]"])
    assert out["g_o"]["value"] == 7 and out["g.b[2]"]["value"] == 7
    assert _run("f2", {"i": 1, "g.b[2]": 5}, ["g_o"])["g_o"]["value"] == 5


def test_a_member_not_set_by_the_sequence_is_unknown():
    assert _run("f1", {"g.a": 3}, ["g_o"])["g_o"]["reason"].startswith("initial_value_not_in_inputs:g.s.x")


def test_a_write_to_an_enclosing_member_makes_every_member_under_it_unknown():
    out = _run("f3", {"g.s.x": 4, "h.s.x": 6, "g.a": 2}, ["g_o", "g.s.x", "g.a"])
    assert "value" not in out["g_o"] and "value" not in out["g.s.x"]
    assert out["g.a"] == {"value": 2, "basis": "unchanged_input"}   # only what lies under ``g.s``


def test_a_callee_that_writes_a_member_makes_the_struct_unknown():
    # the write closure names the struct (``g``), not the member: every member of it
    assert "value" not in _run("f4", {"g.a": 3}, ["g_o"])["g_o"]


def test_a_pointer_write_reaches_a_member_only_when_its_struct_address_was_taken():
    out = _run("f5", {"g.a": 3, "g_taken.a": 4}, ["g_o"])
    assert "value" not in out["g_o"]   # g_taken's address is taken (``&g_taken.a``)
    assert _run("f5", {"g.a": 3}, ["g.a"])["g.a"] == {"value": 3, "basis": "unchanged_input"}
    # a member the function already wrote is reached too; one of a struct whose address no one takes is not
    out = _run("f11", {}, ["g_o", "g.a", "g_taken.a"])
    assert "value" not in out["g_o"] and "value" not in out["g_taken.a"] and out["g.a"]["value"] == 6


def test_a_callee_write_to_a_plain_struct_goes_through_no_pointer():
    # ``g`` has only modeled members: the callee's write to it is to its members — an address-taken object elsewhere
    # keeps its value (before R39 an unmodeled written name was a write through a pointer)
    assert _run("f10", {"g_taken.a": 4}, ["g_o"])["g_o"] == {"value": 4, "basis": "assigned"}


def test_a_write_to_a_struct_with_a_pointer_member_may_go_through_it():
    # ``gp.p[0] = 1U`` in a callee: the closure writes ``gp``, which has a pointer member — opaque, as before R39:
    # an address-taken member is unknown after it; one no pointer can reach keeps its value
    out = _run("f7", {"g.a": 3, "g_taken.a": 4}, ["g_o", "g.a"])
    assert "value" not in out["g_o"] and out["g.a"] == {"value": 3, "basis": "unchanged_input"}


def test_a_volatile_member_is_not_an_input():
    assert _run("f8", {"gv.a": 3}, ["g_o"])["g_o"]["reason"].startswith("volatile_object:gv.a")


def test_a_local_struct_of_the_same_name_is_not_the_global():
    assert "value" not in _run("f9", {"g.a": 3}, ["g_o"])["g_o"]


# ── MC/DC ──────────────────────────────────────────────────────────────────────────────────────

def test_a_condition_on_members_is_designed_in_its_own_group():
    from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design
    unit = _unit("d1", ["g.a", "g.s.x"])
    report = build_mcdc_design(unit)
    (decision,) = report["decisions"]
    assert decision["status"] == "designed", decision["reason"]
    assert decision["static_reason"] == "unsupported_scalar:field_expression"
    c1 = next(p for p in decision["pairs"] if p["condition_id"] == "C1")
    assert c1["inputs_a"]["g.a"] != c1["inputs_b"]["g.a"]
    rows = [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]
    finalize_mcdc_design(report, rows, unit)
    assert {p["retained_status"] for p in decision["pairs"]} == {"retained"}


def test_a_member_through_a_pointer_keeps_the_refusal():
    from generators.mcdc_design import build_mcdc_design
    (decision,) = build_mcdc_design(_unit("d3", ["g_en"]))["decisions"]
    assert decision["status"] == "unsupported" and decision["reason"] == "unsupported_scalar:field_expression"
    assert decision.get("evaluation") != "source_path"


def test_the_member_condition_search_is_counted_and_disclosed():
    from generators.mcdc_design import build_mcdc_design
    from generators.suts import summarize_mcdc_design
    from report_gen.generation_disclosures import build_disclosures
    unit = _unit("d1", ["g.a", "g.s.x"])
    unit["mcdc_design"] = build_mcdc_design(unit)
    summary = summarize_mcdc_design([unit])
    assert (summary["member_condition_decisions"], summary["member_condition_designed"]) == (1, 1)
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary}) if i["key"] == "suts_mcdc_design"]
    assert "구조체 멤버" in item["note"] and "p->a" in item["note"]


# ── inputs ─────────────────────────────────────────────────────────────────────────────────────

def test_a_member_the_function_reads_becomes_a_source_read_input_name():
    from generators.suts import _source_object_decl, source_read_names
    seqs = [{"seq_num": 1, "expected_evidence": {"g_o": {"reason": "initial_value_not_in_inputs:g.s.x"}}},
            {"seq_num": 2, "expected_evidence": {"g_o": {"reason": "initial_value_not_in_inputs:g.b[2]"}}}]
    assert set(source_read_names(seqs)) == {"g.s.x", "g.b[2]"}
    assert _source_object_decl(SCOPE, "g.s.x") == ("U8", "")
    assert _source_object_decl(SCOPE, "g.b[2]") == ("U16", "")
    assert _source_object_decl(SCOPE, "gv.a")[1] == "volatile_object"


# ── clang harness ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def disk_units(tmp_path_factory):
    from reference_alignment import _load_source
    root = tmp_path_factory.mktemp("st39") / "src"
    root.mkdir()
    for name, text in (("h.h", H), ("u.c", C), ("l.c", L)):
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    texts, context, _ = _load_source([root])
    path = next(p for p in texts if p.endswith("u.c"))
    scope = cpc.build_scopes(context, [path])[path]
    return lambda fn: {"name": fn, "source_text": texts[path], "source_path": path, "source_text_complete": True,
                       "project_scope": scope}


def test_clang_checks_member_claims(disk_units):
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")
    from source_oracle_clang_check import check_claims
    report = check_claims([{"unit": disk_units("f1"), "inputs": {"g.a": 3, "g.s.x": 4}, "outputs": {"g_o": 7}},
                           {"unit": disk_units("f2"), "inputs": {"i": 2}, "outputs": {"g_o": 7, "g.b[2]": 7}},
                           {"unit": disk_units("f6"), "inputs": {}, "outputs": {"g.a": 9}}])
    assert (report["checked"], report["agree"], report["mismatch"], report["eval_error"]) == (4, 4, 0, 0)
    wrong = check_claims([{"unit": disk_units("f1"), "inputs": {"g.a": 3, "g.s.x": 4}, "outputs": {"g_o": 8}}])
    assert wrong["mismatch"] == 1   # the harness really reads the members the claim set


# ── review round 1 (C1–C3, W1, W2, I2) ───────────────────────────────────────────────────────────

R1_H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef volatile struct { U8 a; } VT;
typedef const struct { U8 a; } CT;
typedef struct { VT in; U8 k; } TN;
typedef struct { U8 a;
#if (FEATURE == 1)
  U8 *p;
#endif
  U8 v; } TC;
typedef struct { U8 a; union { U8 *p; U16 raw; }; } TA;
typedef struct { TC c; U8 z; } TH;
typedef struct { void (*cb)(void); U8 w; } TF;
typedef struct { U8 a; union { U8 *p; U16 raw; } u; } TU2;
"""
R1_C = """#include "h1.h"
VT g_isr;
CT g_cfg = {5U};
TN g_n;
TC gc;
TA gan;
TH gh;
TF gf;
TU2 gu2;
U8 g_o;
U8 g_x;
void wr_c(void);
void wr_h(void);
U8 *keep(void) { return &g_x; }
void r1(void) { g_o = g_isr.a; }
void r2(void) { g_x = 3U; wr_c(); g_o = g_x; }
void r3(void) { g_x = 3U; wr_h(); g_o = g_x; }
void d5(void) { if ((gf.w == 3U) && (g_x == 1U)) { g_o = 1U; } else { g_o = 2U; } }
"""
R1_L = """#include "h1.h"
extern TC gc;
extern TH gh;
void wr_c(void) { gc.p[0] = 9U; }
void wr_h(void) { gh.c.p[0] = 9U; }
"""


def _r1_scope():
    files = {os.path.join(ROOT, "h1.h"): R1_H, os.path.join(ROOT, "r1.c"): R1_C, os.path.join(ROOT, "l1.c"): R1_L}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "r1.c")
    return path, cpc.build_scopes(context, [path])[path]


R1_PATH, R1_SCOPE = _r1_scope()


def _r1_run(name, inputs, outs):
    from generators.c_source_oracle import evaluate_outputs
    unit = {"name": name, "source_text": R1_C, "source_path": R1_PATH, "source_text_complete": True,
            "project_scope": R1_SCOPE}
    (r,) = evaluate_outputs(unit, [inputs], [outs])
    return r["outputs"]


def test_a_typedef_qualifier_reaches_the_members():
    # (C1) ``typedef volatile struct`` — its objects' members are volatile; ``typedef const struct`` — not modeled
    assert R1_SCOPE["globals"]["g_isr.a"]["volatile"]
    assert _r1_run("r1", {"g_isr.a": 3}, ["g_o"])["g_o"]["reason"].startswith("volatile_object:g_isr.a")
    assert "g_cfg" not in R1_SCOPE["struct_globals"]
    assert R1_SCOPE["globals"]["g_n.in.a"]["volatile"]   # through a nested member of that type


def test_a_body_that_hides_members_is_not_flattened():
    # (C2) ``#if`` around a member, an unnamed union member: the members cannot all be named
    assert "gc" not in R1_SCOPE["struct_globals"] and "gan" not in R1_SCOPE["struct_globals"]
    # a nested struct of such a body is an unmodeled member: the enclosing struct is opaque
    rec = R1_SCOPE["struct_globals"]["gh"]
    assert rec["members"] == ["z"] and rec["unmodeled_members"] == ["c"] and rec["opaque_members"]


def test_a_write_through_a_hidden_pointer_member_still_reaches_pointer_targets():
    # (C2) R39 round 1 called ``gc`` plain and dropped the pointer havoc: ``g_x`` (address taken) kept 3
    assert "value" not in _r1_run("r2", {}, ["g_o"])["g_o"]
    assert "value" not in _r1_run("r3", {}, ["g_o"])["g_o"]


def test_a_named_union_member_is_left_out_and_flags_the_struct():
    # a union member may hold a pointer: the struct is opaque (a nested union must not add nothing and flag nothing)
    rec = R1_SCOPE["struct_globals"]["gu2"]
    assert rec["members"] == ["a"] and rec["unmodeled_members"] == ["u"] and rec["opaque_members"]


def test_a_function_pointer_member_is_named_and_left_out():
    # (I2) ``void (*cb)(void)`` used to make the whole struct unmodeled (unnamed member)
    rec = R1_SCOPE["struct_globals"]["gf"]
    assert rec["members"] == ["w"] and rec["unmodeled_members"] == ["cb"] and rec["opaque_members"]


def test_a_member_of_a_struct_named_twice_in_the_project_is_ambiguous():
    # (C3) unit a: ``static TA s`` (not flattened — an unnamed union member); unit b: ``static TB s`` (flattened). ``s.a``
    # meant a's object; b's callee reads its own ``s.a`` — the integration reading must not take the input for it
    from generators.c_source_oracle import evaluate_outputs
    from generators.integration_oracle import CalleeProvider
    h = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
        "typedef struct { U8 a; union { U8 p; U16 q; }; } TA;\ntypedef struct { U8 a; } TB;\n"
    a = '#include "h2.h"\nstatic TA s;\nU8 g_o;\nU8 b_get(void);\nvoid entry(void) { g_o = b_get(); }\n'
    b = '#include "h2.h"\nstatic TB s;\nU8 b_get(void) { return s.a; }\n'
    files = {os.path.join(ROOT, "h2.h"): h, os.path.join(ROOT, "a.c"): a, os.path.join(ROOT, "b.c"): b}
    context = cpc.build_project_context(files)
    pa, pb = os.path.join(ROOT, "a.c"), os.path.join(ROOT, "b.c")
    scopes = cpc.build_scopes(context, [pa, pb])
    provider = CalleeProvider(context, {p: files[p] for p in (pa, pb)}, scopes, cpc.shared_parser())
    assert "s" in provider.ambiguous_struct_roots and "s.a" not in provider.ambiguous_names   # only b names ``s.a``
    unit = {"name": "entry", "source_text": a, "source_path": pa, "source_text_complete": True,
            "project_scope": scopes[pa], "callee_provider": provider}
    (r,) = evaluate_outputs(unit, [{"s.a": 7}], [["g_o"]])
    assert r["outputs"]["g_o"]["reason"].startswith("object_name_ambiguous_in_project:s.a"), r["outputs"]


def test_the_integration_harness_leaves_member_names_unplaced():
    # (W1) a dotted name declared as a harness member broke the whole entry's compile
    from integration_oracle_clang_check import _declared
    assert _declared(SCOPE, "g.a") is None and _declared(SCOPE, "g_o") is not None


def test_the_inventory_design_takes_the_members_a_function_reads():
    # (W2) the independent MC/DC check designs from the members the body reads (inventory mode)
    from generators.mcdc_design import _read_names, build_mcdc_design
    unit = {**_unit("d1"), "mcdc_free_globals": True, "input_vars": []}
    report = build_mcdc_design(unit)
    (decision,) = report["decisions"]
    assert decision["status"] == "designed", decision["reason"]
    parser = cpc.shared_parser()
    root = parser.parse(C.encode()).root_node
    fn = next(n for n in root.named_children if n.type == "function_definition" and b"d1(" in n.text)
    names = _read_names(fn.child_by_field_name("body"), C.encode())
    assert "g.a" in names and "g.s.x" in names


# ── review round 2 (C3', W2) ─────────────────────────────────────────────────────────────────────

def test_an_external_struct_the_entry_cannot_flatten_is_ambiguous_with_a_static_one():
    # (C3') unit a: ``TA s`` with external linkage, not flattened; unit b: ``static TB s`` flattened
    from generators.c_source_oracle import evaluate_outputs
    from generators.integration_oracle import CalleeProvider
    h = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
        "typedef struct { U8 a; union { U8 p; U16 q; }; } TA;\ntypedef struct { U8 a; } TB;\n"
    a = '#include "h3.h"\nTA s;\nU8 g_o;\nU8 b_get(void);\nvoid entry(void) { g_o = b_get(); }\n'
    b = '#include "h3.h"\nstatic TB s;\nU8 b_get(void) { return s.a; }\n'
    files = {os.path.join(ROOT, "h3.h"): h, os.path.join(ROOT, "a3.c"): a, os.path.join(ROOT, "b3.c"): b}
    context = cpc.build_project_context(files)
    pa, pb = os.path.join(ROOT, "a3.c"), os.path.join(ROOT, "b3.c")
    scopes = cpc.build_scopes(context, [pa, pb])
    assert scopes[pa]["unmodeled_object_linkage"]["s"] is False
    provider = CalleeProvider(context, {p: files[p] for p in (pa, pb)}, scopes, cpc.shared_parser())
    assert "s" in provider.ambiguous_struct_roots
    unit = {"name": "entry", "source_text": a, "source_path": pa, "source_text_complete": True,
            "project_scope": scopes[pa], "callee_provider": provider}
    (r,) = evaluate_outputs(unit, [{"s.a": 7}], [["g_o"]])
    assert r["outputs"]["g_o"]["reason"].startswith("object_name_ambiguous_in_project:s.a"), r["outputs"]


def test_a_member_named_by_a_macro_hides_the_members():
    # (W2) ``U8 MEMBERS;`` with ``#define MEMBERS a; U8 *hp`` is a pointer member the text does not show
    h = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
        "#define MEMBERS a; U8 *hp\ntypedef struct { U8 MEMBERS; U8 v; } TM;\n"
    c = '#include "h4.h"\nTM gmac;\nU8 g_x;\nU8 g_o;\nvoid wr_mac(void);\nU8 *keep(void) { return &g_x; }\n' \
        "void m1(void) { g_x = 3U; wr_mac(); g_o = g_x; }\n"
    lib = '#include "h4.h"\nextern TM gmac;\nvoid wr_mac(void) { gmac.hp[0] = 9U; }\n'
    files = {os.path.join(ROOT, "h4.h"): h, os.path.join(ROOT, "c4.c"): c, os.path.join(ROOT, "l4.c"): lib}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "c4.c")
    scope = cpc.build_scopes(context, [path])[path]
    assert "gmac" not in scope["struct_globals"]
    from generators.c_source_oracle import evaluate_outputs
    unit = {"name": "m1", "source_text": c, "source_path": path, "source_text_complete": True, "project_scope": scope}
    (r,) = evaluate_outputs(unit, [{}], [["g_o"]])
    assert "value" not in r["outputs"]["g_o"]


def test_a_bit_field_body_keeps_no_members():
    # (review I-e) never flattened — the context does not carry its members
    rec = cpc.build_project_context({os.path.join(ROOT, "hb.h"): H})["files"][os.path.join(ROOT, "hb.h")]
    (entry,) = [e for k, v in rec["structs"].items() for e in v if e.get("bit_fields")]
    assert entry["members"] == []


def test_a_member_declaration_that_does_not_parse_hides_the_members():
    # (review round 2 I-a) ``U8 near a;`` (a compiler keyword the grammar does not know): the member names are guesses
    h = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
        "typedef struct { U8 near a; U8 v; } TE;\n"
    c = '#include "h5.h"\nTE ge;\n'
    files = {os.path.join(ROOT, "h5.h"): h, os.path.join(ROOT, "c5.c"): c}
    path = os.path.join(ROOT, "c5.c")
    scope = cpc.build_scopes(cpc.build_project_context(files), [path])[path]
    assert "ge" not in scope["struct_globals"]


def test_a_nested_bit_field_struct_is_an_unmodeled_member():
    # its members are not kept (a pointer beside the bit-fields among them): the enclosing struct is opaque
    h = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
        "typedef struct { U8 f : 3; U8 *p; } TBP;\ntypedef struct { TBP bits; U8 v; } TOB;\n"
    c = '#include "h6.h"\nTOB gob;\n'
    files = {os.path.join(ROOT, "h6.h"): h, os.path.join(ROOT, "c6.c"): c}
    path = os.path.join(ROOT, "c6.c")
    scope = cpc.build_scopes(cpc.build_project_context(files), [path])[path]
    rec = scope["struct_globals"]["gob"]
    assert rec["members"] == ["v"] and rec["unmodeled_members"] == ["bits"] and rec["opaque_members"]


def test_a_macro_member_name_undefined_after_the_struct_still_hides_the_members():
    # (review round 3 W-r3) ``#define MEMBERS …`` used in the body and ``#undef``-ed after it: not in the end-of-unit
    # macro table, yet it named the members
    h = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
        "#define MEMBERS a; U8 *hp\ntypedef struct { U8 MEMBERS; U8 v; } TM;\n#undef MEMBERS\n"
    c = '#include "h7.h"\nTM gmac;\n'
    files = {os.path.join(ROOT, "h7.h"): h, os.path.join(ROOT, "c7.c"): c}
    path = os.path.join(ROOT, "c7.c")
    scope = cpc.build_scopes(cpc.build_project_context(files), [path])[path]
    assert "gmac" not in scope["struct_globals"]
