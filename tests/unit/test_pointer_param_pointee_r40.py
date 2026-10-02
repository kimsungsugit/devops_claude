"""R40 — a pointer parameter's pointee the row sets up (``p[0]`` · ``p[0].a``) is an object of its own.

The generated SUTS rows already carry pointee inputs from the design document (``pst_Queue[0].u8_Count``); the
reference writes ``pProfile[0].s32_SOP``. Until R40 the source oracle held every pointer parameter unknown — ``p->a``
was ``field_unmodeled`` and ``p == NULL`` split the run. A row that sets one of the pointee's values implies the harness
allocated it: the pointer is then known (not null, a harness object of its own — not a program object, not another
parameter's pointee), its pointee members are read and written as ``@pointee:p[0].a`` objects that any write through a
pointer may reach. The project context records each function's ``T *p`` parameters and lays out those pointee types;
MC/DC searches such conditions (member group) when the row sets the pointee up; the clang harness declares the struct
pointee of the modeled members and sets element 0 from the claim.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from generators import c_project_context as cpc  # noqa: E402

ROOT = os.path.join(os.sep, "p40")
H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
#define NULL ((void*)0)
typedef struct { U8 cnt; U16 buf[4]; struct { U8 x; } in; } Q;
typedef struct { U8 v; U8 *hp; } QP;
typedef unsigned char tU8;
typedef enum { E_A = 0, E_B = 3 } E;
typedef struct { tU8 k; E st; } R;
typedef struct { U8 a; } S;
"""
C = """#include "h.h"
U8 g_o;
U8 g_en;
U8 *g_ptr;
void sink(Q *q);
void bump(Q *q);
U8 peek(const Q *q);
void f1(Q *pq) { if (pq == NULL) { g_o = 9U; return; } g_o = (U8)(pq->cnt + pq->in.x); }
void f2(Q *pq) { if ((pq != (Q*)0) && (pq->cnt >= 3U)) { pq->cnt = 0U; pq->buf[1] = 7U; } }
void f3(U8 *pv) { if (!pv) { return; } *pv = (U8)(pv[0] + 1U); }
void f4(Q *pq) { sink(pq); g_o = pq->cnt; }
void f5(Q *pq, Q *pr) { g_o = (U8)(pq == pr); }
void f6(Q *pq) { *g_ptr = 1U; g_o = pq->cnt; }
void f7(Q *pq) { g_o = (U8)(peek(pq) + pq->cnt); }
void f8(Q *pq) { bump(pq); g_o = pq->cnt; }
void f9(Q *pq) { g_o = (U8)((*pq).in.x + pq[0].cnt); }
void f10(Q *pq, Q **pp, void (*cb)(void)) { g_o = pq->cnt; }
U8 bumpr(Q *q);
void f11(Q *pq) { g_o = (U8)(pq->cnt + bumpr(pq)); }
void n1(Q *pq) { if (pq == NULL) { g_o = 9U; } else { g_o = 1U; } }
void d1(Q *pq) { if ((pq != NULL) && (pq->cnt >= 3U) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void d2(U8 *pv) { if ((*pv == 5U) || (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
void d3(Q *pq) { if (((*pq).in.x == 2U) && (pq->buf[1] > 7U)) { g_o = 1U; } else { g_o = 2U; } }
Q *g_q;
U8 g_arr[3];
U8 g_en2;
S g_s;
U8 wq2(void);
void f12(Q *pq) { g_q = pq; g_o = (U8)(pq->cnt + wq2()); }
void f13(Q *pq) { pq->cnt = bumpr(pq); g_o = 1U; }
void f14(Q *pq) { pq->cnt += bumpr(pq); g_o = 1U; }
void f15(Q *pq) { g_ptr = &pq->cnt; g_o = (U8)(pq->cnt + ((*g_ptr = 5U), 0U)); }
void f16(Q *pq) { g_ptr = &pq->cnt; g_o = (U8)(pq->cnt + 1U); }
void f17(R *pr) { g_o = pr->k; }
void f18(Q *pq) { g_o = (U8)(pq->cnt + g_arr[1]); }
void f19(volatile U8 *pv) { g_o = *pv; }
void d4(Q *pq) { U8 t = g_en; if ((t > 3U) && (g_en2 == 1U)) { g_o = 2U; } if ((pq->cnt > 3U) && (g_en == 1U)) { g_o = 3U; } }
void d5(Q *pq) { if ((g_s.a > 1U) && (*g_ptr == 2U)) { g_o = 1U; } else { g_o = 2U; } }
void d6(U8 *pv) { if (((g_s.a > 1U) || (pv == NULL)) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
U8 setp(Q **pp);
void f20(Q *pq) { pq[0].cnt = setp(&pq); g_o = 1U; }
void f21(Q *pq) { (*pq).cnt = setp(&pq); g_o = 1U; }
void f22(R *pr) { if (pr->st == E_B) { g_o = 1U; } else { g_o = 2U; } }
void d7(U8 *pv) { if (((g_s.a > 1U) || (*pv == 2U)) && (g_en == 1U)) { g_o = 1U; } else { g_o = 2U; } }
U8 g_buf[4];
U8 g_o2;
void init(U8 **pp);
U8 wp(U8 *b);
void f23(void) { U8 *lp = g_buf; init(&lp); lp[0] = wp(g_buf); g_o2 = 7U; }
"""
L = """#include "h.h"
void bump(Q *q) { q->cnt = 1U; }
U8 bumpr(Q *q) { q->cnt = 1U; return 0U; }
U8 peek(const Q *q) { return q->cnt; }
extern Q *g_q;
U8 wq2(void) { g_q[0].cnt = 5U; return 1U; }
Q g_alt;
U8 setp(Q **pp) { *pp = &g_alt; return 9U; }
U8 wp(U8 *b) { b[0] = 1U; return 2U; }
"""


def _scope():
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "u.c"): C, os.path.join(ROOT, "l.c"): L}
    context = cpc.build_project_context(files)
    path = os.path.join(ROOT, "u.c")
    return context, path, cpc.build_scopes(context, [path])[path]


CONTEXT, PATH, SCOPE = _scope()


def _unit(name, inputs=()):
    return {"name": name, "source_text": C, "source_path": PATH, "source_text_complete": True,
            "project_scope": SCOPE, "input_vars": list(inputs)}


def _run(name, inputs, outs):
    from generators.c_source_oracle import evaluate_outputs
    (r,) = evaluate_outputs(_unit(name), [inputs], [outs])
    return r


# ── project context ────────────────────────────────────────────────────────────────────────────

def test_a_function_records_its_single_level_pointer_parameters():
    fn = CONTEXT["files"][PATH]["functions"]["f10"][0]
    assert fn["pointer_params"] == [{"name": "pq", "type": "Q"}]   # not ``Q **pp``, not a function pointer
    assert SCOPE["pointer_params"]["d2"] == [{"name": "pv", "type": "U8"}]


def test_the_scope_lays_out_the_pointee_types():
    q = SCOPE["pointee_types"]["Q"]
    assert set(q["members"]) == {".cnt", ".in.x"} and set(q["arrays"]) == {".buf"} and not q["opaque"]
    assert set(SCOPE["pointee_types"]["U8"]["members"]) == {""}


# ── source oracle ──────────────────────────────────────────────────────────────────────────────

def test_a_pointee_the_row_sets_makes_the_pointer_known_and_not_null():
    r = _run("f1", {"pq[0].cnt": 3, "pq[0].in.x": 4}, ["g_o"])
    assert r["outputs"]["g_o"] == {"value": 7, "basis": "assigned"}
    assert any("points to a harness object of its own" in a for a in r["assumptions"])


def test_without_the_pointee_the_pointer_stays_unknown():
    assert "value" not in _run("f1", {}, ["g_o"])["outputs"]["g_o"]
    # the null check itself is undecided (it may be null): both arms stand
    assert "value" not in _run("n1", {}, ["g_o"])["outputs"]["g_o"]
    assert _run("n1", {"pq[0].cnt": 0}, ["g_o"])["outputs"]["g_o"]["value"] == 1


def test_pointee_members_are_written_and_observed():
    out = _run("f2", {"pq[0].cnt": 5}, ["pq[0].cnt", "pq[0].buf[1]", "pq[0].buf[2]"])["outputs"]
    assert out["pq[0].cnt"] == {"value": 0, "basis": "assigned"} and out["pq[0].buf[1]"]["value"] == 7
    assert out["pq[0].buf[2]"]["reason"].startswith("unwritten_output_initial_not_in_inputs:pq[0].buf[2]")   # (2-c)
    low = _run("f2", {"pq[0].cnt": 1, "pq[0].buf[1]": 4}, ["pq[0].cnt", "pq[0].buf[1]"])["outputs"]
    assert low["pq[0].cnt"] == {"value": 1, "basis": "unchanged_input"} and low["pq[0].buf[1]"]["value"] == 4


def test_a_pointee_read_in_a_condition_and_left_unwritten_keeps_the_read_reason():
    # (backlog 2-c) d3 reads pq[0].buf[1] in its condition and never writes it — the function read it
    out = _run("d3", {"pq[0].in.x": 2}, ["pq[0].buf[1]"])["outputs"]
    assert out["pq[0].buf[1]"]["reason"] == "initial_value_not_in_inputs:pq[0].buf[1]"


def test_a_scalar_pointee():
    assert _run("f3", {"pv[0]": 5}, ["pv[0]"])["outputs"]["pv[0]"] == {"value": 6, "basis": "assigned"}


def test_the_forms_of_a_pointee_access():
    out = _run("f9", {"pq[0].cnt": 3, "pq[0].in.x": 4}, ["g_o"])["outputs"]
    assert out["g_o"]["value"] == 7   # ``(*pq).in.x`` · ``pq[0].cnt``


def test_two_parameters_point_to_distinct_objects():
    assert _run("f5", {"pq[0].cnt": 1, "pr[0].cnt": 1}, ["g_o"])["outputs"]["g_o"]["value"] == 0


def test_a_write_through_any_pointer_may_reach_the_pointee():
    assert "value" not in _run("f4", {"pq[0].cnt": 3}, ["g_o"])["outputs"]["g_o"]   # an unknown callee gets pq
    assert "value" not in _run("f6", {"pq[0].cnt": 3}, ["g_o"])["outputs"]["g_o"]   # ``*g_ptr = 1U``
    assert "value" not in _run("f8", {"pq[0].cnt": 3}, ["g_o"])["outputs"]["g_o"]   # bump writes through q


def test_a_pointee_read_unsequenced_with_a_call_that_may_write_it_is_refused():
    # ``pq->cnt + bumpr(pq)``: bumpr (a stub here) may write the pointee — the order is unspecified
    out = _run("f11", {"pq[0].cnt": 3, "bumpr() return": 0}, ["g_o"])["outputs"]
    assert "value" not in out["g_o"], out


def test_a_callee_writing_through_a_global_pointer_is_unsequenced_with_a_pointee_read():
    # (review R40 C1) wq2 writes ``g_q[0].cnt`` (closure: writes g_q, no pointer_write): g_q may hold pq
    out = _run("f12", {"pq[0].cnt": 3}, ["g_o"])
    assert out["reason"] == "call_unsequenced_with_access:wq2", out


def test_a_store_through_the_pointee_beside_a_call_is_sequenced():
    # (review R40 W1) ``pq->cnt = bumpr(pq)``: the pointee is stored after the call, not read beside it
    out = _run("f13", {"pq[0].cnt": 3, "bumpr() return": 4}, ["pq[0].cnt", "g_o"])["outputs"]
    assert out["pq[0].cnt"] == {"value": 4, "basis": "assigned"} and out["g_o"]["value"] == 1
    # ``+=`` reads it beside the call: still refused
    assert _run("f14", {"pq[0].cnt": 3, "bumpr() return": 4}, ["g_o"])["reason"] == "call_unsequenced_with_access:bumpr"


def test_a_pointer_write_in_the_same_expression_may_reach_the_pointee():
    # (review R40 W2) ``g_ptr = &pq->cnt; pq->cnt + ((*g_ptr = 5U), 0U)`` — the control f16 has no such write
    assert _run("f16", {"pq[0].cnt": 3}, ["g_o"])["outputs"]["g_o"]["value"] == 4
    assert _run("f15", {"pq[0].cnt": 3}, ["g_o"])["reason"] == "unsequenced_side_effects"


def test_only_a_value_the_row_sets_allocates_the_pointee():
    # (review R40 W4) ``-`` is no value; a row that states the pointer itself is not a harness object
    assert "value" not in _run("f1", {"pq[0].cnt": "-", "pq[0].in.x": "-"}, ["g_o"])["outputs"]["g_o"]
    # n1 reads no member: only the binding decides ``pq == NULL`` — unbound, both arms stand
    assert "value" not in _run("n1", {"pq[0].cnt": "-"}, ["g_o"])["outputs"]["g_o"]
    assert _run("n1", {"pq[0].cnt": "0U"}, ["g_o"])["outputs"]["g_o"]["value"] == 1
    assert "value" not in _run("f1", {"pq": "NULL", "pq[0].cnt": 3, "pq[0].in.x": 4}, ["g_o"])["outputs"]["g_o"]
    assert _run("f1", {"pq[0].cnt": "3U", "pq[0].in.x": "0x4"}, ["g_o"])["outputs"]["g_o"]["value"] == 7


def test_a_store_through_a_pointer_the_call_may_change_is_unsequenced():
    # (review R40 round 2 W-B) ``pq[0].cnt = setp(&pq)``: the address the store lands at reads pq, which setp may
    #   change — whichever form the store takes (``(*pq).cnt`` too)
    for fn in ("f20", "f21"):
        for inputs in ({"pq[0].cnt": 3, "setp() return": 9}, {"pq[0].cnt": 3}):
            assert _run(fn, inputs, ["pq[0].cnt"])["reason"] == "call_unsequenced_with_access:setp", (fn, inputs)


def test_a_store_through_an_unknown_pointer_keeps_its_order_free():
    # (review R40 round 3 I-1) lp escaped but is no known pointer: the store through it is a write through any pointer
    #   whichever lp it uses — the order does not change the result, the rest of the function stands (as before R40)
    assert _run("f23", {}, ["g_o2"])["outputs"]["g_o2"] == {"value": 7, "basis": "assigned"}


def test_a_blank_pointer_cell_does_not_state_the_pointer():
    # (review R40 round 2 I-c) ``pq = -`` beside ``pq[0].cnt``: nothing said about the pointer — the pointee binds
    assert _run("n1", {"pq": "-", "pq[0].cnt": "0U"}, ["g_o"])["outputs"]["g_o"]["value"] == 1


def test_a_callee_that_writes_through_no_pointer_leaves_the_pointee():
    # peek only reads: the pointee keeps its value, and ``peek(pq) + pq->cnt`` is no unsequenced write
    out = _run("f7", {"pq[0].cnt": 3, "peek() return": 2}, ["g_o"])["outputs"]
    assert out["g_o"] == {"value": 5, "basis": "assigned"}


# ── MC/DC ──────────────────────────────────────────────────────────────────────────────────────

_DOMAINS = {g: {"min": 0, "max": 255, "type": "uint8_t", "source": "declared_type", "origin": "global"}
            for g in ("g_en", "g_en2")}


def _design(name, inputs):
    from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design
    unit = _unit(name, inputs)
    report = build_mcdc_design(unit, declared_domains=dict(_DOMAINS))
    rows = [{"seq_num": i + 1, "inputs": dict(v)} for i, v in enumerate(report["selected_inputs"])]
    finalize_mcdc_design(report, rows, unit)
    return report["decisions"]


def test_a_condition_on_a_pointee_is_designed():
    (d2,) = _design("d2", ["pv[0]", "g_en"])
    assert d2["status"] == "designed", d2["reason"]
    c1 = next(p for p in d2["pairs"] if p["condition_id"] == "C1")
    assert c1["inputs_a"]["pv[0]"] != c1["inputs_b"]["pv[0]"] and c1["retained_status"] == "retained"
    (d3,) = _design("d3", ["pq[0].in.x", "pq[0].buf[1]"])
    assert d3["status"] == "designed", d3["reason"]


def test_a_null_check_cannot_be_paired_but_the_rest_of_the_decision_can():
    # the row sets the pointee up, so ``pq != NULL`` is true on every row: C1 has no pair (partial), C2 · C3 do
    (d1,) = _design("d1", ["pq[0].cnt", "g_en"])
    assert d1["status"] == "partial" and {p["condition_id"] for p in d1["pairs"]} == {"C2", "C3"}


def test_a_pointee_the_row_does_not_set_keeps_the_refusal():
    (d2,) = _design("d2", ["g_en"])
    assert d2.get("evaluation") != "source_path" and d2["reason"] == "unsupported_scalar:pointer_expression"


def test_the_inventory_reads_the_pointees_the_body_reads():
    from generators.mcdc_design import _read_pointee_names
    parser = cpc.shared_parser()
    root = parser.parse(C.encode()).root_node
    fn = next(n for n in root.named_children if n.type == "function_definition" and b"d3(" in n.text)
    assert _read_pointee_names(fn.child_by_field_name("body"), C.encode(), SCOPE, "d3") == ["pq[0].in.x", "pq[0].buf[1]"]


def test_the_pointee_group_is_searched_on_its_own_and_only_it_sets_pointees():
    # (review R40 W3) d4's first decision (a local) is the base group's: its rows carry no pointee — the second one
    #   (through pq) is the pointee group's, with ``pq[0].cnt`` in its rows
    first, second = _design("d4", ["pq[0].cnt", "g_en", "g_en2"])
    assert first.get("evaluation") == "source_path" and "search_group" not in first
    assert first["pairs"] and all("pq[0].cnt" not in {**p["inputs_a"], **p["inputs_b"]} for p in first["pairs"])
    assert second["search_group"] == "pointee" and second["status"] == "designed", second["reason"]
    assert all("pq[0].cnt" in p["inputs_a"] for p in second["pairs"])


def test_a_member_decision_naming_a_pointer_is_searched_without_its_pointee():
    # (review R40 round 2 W-A) ``pv == NULL`` beside ``g_s.a``: the member group's runs never set pointees, so the rows
    #   need not either — R39 searched it (C3 on g_en paired), R40 must too
    (d6,) = _design("d6", ["g_s.a", "g_en"])
    assert d6.get("evaluation") == "source_path" and d6["search_group"] == "struct_member", d6["reason"]
    assert any(p["condition_id"] == "C3" and p["retained_status"] == "retained" for p in d6["pairs"])


def test_a_member_decision_reading_a_pointee_the_row_does_not_set_is_searched_as_in_r39():
    # (review R40 round 3 W-A2) ``*pv`` beside ``g_s.a`` without ``pv[0]`` in the rows: the pointee search cannot take
    #   it, so the member search does (R39 judged ``*pv`` the run's) — C3 on g_en is paired as it was
    (d7,) = _design("d7", ["g_s.a", "g_en"])
    assert d7.get("evaluation") == "source_path" and d7["search_group"] == "struct_member", d7["reason"]
    assert any(p["condition_id"] == "C3" and p["retained_status"] == "retained" for p in d7["pairs"])
    # with the pointee in the rows, the pointee search designs every condition
    (d7p,) = _design("d7", ["g_s.a", "g_en", "pv[0]"])
    assert d7p["search_group"] == "pointee" and d7p["status"] == "designed", d7p["reason"]


def test_a_dereference_not_through_a_pointer_parameter_is_the_runs_to_judge():
    # (review R40 I2) ``*g_ptr`` beside a struct member: routed as in R39 (member group), not refused for the ``*``
    (d5,) = _design("d5", ["g_s.a"])
    assert d5.get("evaluation") == "source_path" and d5["search_group"] == "struct_member"


def test_a_volatile_pointee_parameter_is_volatile():
    # (review R40 I3) ``volatile U8 *pv``: the search never gives it a value, the oracle never reads one
    from generators.mcdc_design import _pointee_input
    assert _pointee_input(SCOPE, "f19", "pv[0]")[2] is True
    assert _pointee_input(SCOPE, "f3", "pv[0]")[2] is False
    assert "value" not in _run("f19", {"pv[0]": 5}, ["g_o"])["outputs"]["g_o"]


def test_a_struct_pointee_under_preprocessing_gaps_keeps_no_layout():
    # (review R40 I4) a member may sit under an #if the unit cannot decide — as a struct global
    root = os.path.join(os.sep, "p40g")
    files = {os.path.join(root, "h.h"): H,
             os.path.join(root, "g.c"): '#include "h.h"\n#include "nope.h"\nU8 g_o;\nvoid fx(Q *pq) { g_o = pq->cnt; }\n'}
    context = cpc.build_project_context(files)
    path = os.path.join(root, "g.c")
    scope = cpc.build_scopes(context, [path])[path]
    assert scope["pointee_types"]["Q"] == {"reason": "preprocessing_gaps"}


# ── generator ──────────────────────────────────────────────────────────────────────────────────

def test_the_generator_types_pointee_inputs_from_the_source():
    from generators.suts import pointee_input_types
    u16 = "uint16_t" if SCOPE["target"]["widths"]["int"] == 16 else "uint32_t"
    types, domains = pointee_input_types(_unit("d3"), ["pq[0].in.x", "pq[0].buf[1]", "pq[0].buf[9]", "pq[0].hp", "g_en"])
    assert (types, domains) == ({"pq[0].in.x": "uint8_t", "pq[0].buf[1]": u16}, {})


def test_a_typedef_the_boundary_table_does_not_know_and_an_enum_pointee_are_typed():
    # (review R40 W5) ``tU8`` by its resolved width (the name alone is an unknown type: blank cells); an enum by its values
    from generators.suts import pointee_input_types
    types, domains = pointee_input_types(_unit("f17"), ["pr[0].k", "pr[0].st"])
    assert types == {"pr[0].k": "uint8_t"}
    assert domains == {"pr[0].st": {"values": [0, 3], "source": "pointee_declaration"}}


def test_the_disclosure_names_the_pointee():
    from generators.suts import summarize_mcdc_design
    from report_gen.generation_disclosures import build_disclosures
    unit = _unit("d2", ["pv[0]", "g_en"])
    from generators.mcdc_design import build_mcdc_design
    unit["mcdc_design"] = build_mcdc_design(unit, declared_domains={
        "g_en": {"min": 0, "max": 255, "type": "uint8_t", "source": "declared_type", "origin": "global"}})
    summary = summarize_mcdc_design([unit])
    assert (summary["pointee_condition_decisions"], summary["pointee_condition_designed"]) == (1, 1)
    assert summary["member_condition_decisions"] == 0
    (item,) = [i for i in build_disclosures("suts", {"mcdc_design_summary": summary}) if i["key"] == "suts_mcdc_design"]
    assert "p[0].a" in item["note"] and "널 아닌 객체" in item["note"]


def test_a_decision_routed_by_its_null_check_is_counted():
    # (review R40 W6) d1's refusal is ``parameter_domain_unresolved:pq`` — counted by the search it had, not the text
    from generators.suts import summarize_mcdc_design
    unit = _unit("d1", ["pq[0].cnt", "g_en"])
    from generators.mcdc_design import build_mcdc_design
    unit["mcdc_design"] = build_mcdc_design(unit, declared_domains=_DOMAINS)
    (d1,) = unit["mcdc_design"]["decisions"]
    assert str(d1["static_reason"]).startswith("parameter_domain_unresolved:pq") and d1["search_group"] == "pointee"
    summary = summarize_mcdc_design([unit])
    assert (summary["pointee_condition_decisions"], summary["pointee_condition_designed"]) == (1, 0)


def test_boundary_rows_move_an_enum_pointee_through_its_enumerators():
    # (review R40 round 2 I-d) the boundary search gets the enum pointee's values too (BV and MC/DC rows had them)
    from generators.boundary_rows import BOUNDARY_PREFIX
    from generators.suts import generate_sequences
    unit = {**_unit("f22", ["pr[0].st"]), "fid": "F1", "output_vars": ["g_o"]}
    seqs = generate_sequences(unit, None, type_cache={}, extended=True)
    # the one boundary (E_A → E_B) is found; its two rows are already there (BV · MC/DC), so none is added
    assert unit["boundary_search"]["boundaries"] == 1, unit["boundary_search"]
    assert not any(str(s.get("strategy") or "").startswith(BOUNDARY_PREFIX) for s in seqs)
    assert {s["inputs"]["pr[0].st"] for s in seqs if s["strategy"].startswith("MCDC")} == {0, 3}


# ── clang harness ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def disk_units(tmp_path_factory):
    from reference_alignment import _load_source
    root = tmp_path_factory.mktemp("pt40") / "src"
    root.mkdir()
    for name, text in (("h.h", H), ("u.c", C), ("l.c", L)):
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    texts, context, _ = _load_source([root])
    path = next(p for p in texts if p.endswith("u.c"))
    scope = cpc.build_scopes(context, [path])[path]
    return lambda fn: {"name": fn, "source_text": texts[path], "source_path": path, "source_text_complete": True,
                       "project_scope": scope}


def test_clang_checks_pointee_claims(disk_units):
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")
    from source_oracle_clang_check import check_claims
    report = check_claims([
        {"unit": disk_units("f1"), "inputs": {"pq[0].cnt": 3, "pq[0].in.x": 4}, "outputs": {"g_o": 7}},
        {"unit": disk_units("f2"), "inputs": {"pq[0].cnt": 5}, "outputs": {"pq[0].cnt": 0, "pq[0].buf[1]": 7}},
        {"unit": disk_units("f3"), "inputs": {"pv[0]": 5}, "outputs": {"pv[0]": 6}},
        # (review R40 C2) the pointee's layout must not hide the unit's arrays from the harness
        {"unit": disk_units("f18"), "inputs": {"pq[0].cnt": 3, "g_arr[1]": 4}, "outputs": {"g_o": 7}}])
    assert (report["checked"], report["agree"], report["mismatch"], report["eval_error"]) == (5, 5, 0, 0)
    wrong = check_claims([{"unit": disk_units("f2"), "inputs": {"pq[0].cnt": 5}, "outputs": {"pq[0].buf[1]": 8}}])
    assert wrong["mismatch"] == 1   # the harness really sets and reads the pointee
