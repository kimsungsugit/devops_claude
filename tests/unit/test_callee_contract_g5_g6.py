"""Callee summary contract — steps 4b (G5) and 4c (G6): what a callee run as its write closure leaves unproven.

An effects-only call (no world — SUTS — or a world that did not interpret the callee) does not run the callee's body:

* G5 — whether it returns is its text's: `cpc._termination_fact` reads each definition (``never`` · ``straight`` ·
  ``loops``), `cpc._closure_termination` adds what it reaches (functions and macros). ``never`` refuses the run as an
  interpreted call would (``non_terminating_loop:<callee>`` — the same class); ``returns`` needs no word; anything else
  keeps the value and names the callee (``callee_termination_assumed``);
* G6 — undefined behaviour in its body is not judged: the record names it (``callee_ub_unanalysed``).

Both reach each derived cell's evidence and are counted (SUTS: `summarize_expected_evidence`; SITS: the integration
stats), and are said in the generation disclosures. The conformance harness holds the relations (S4 · S5 · S6 — the G5 /
G6 tests and their mutations); these tests hold the facts and the plumbing.
"""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators import callee_contract as cc
from generators.c_source_oracle import evaluate_outputs

ROOT = os.path.join(os.sep, "g5g6")
_CPROJECT = ('<?xml version="1.0"?><cproject><configuration><toolChain superClass="com.freescale.s12z.toolchain.release">'
             '<tool superClass="com.freescale.s12z.toolchain.compiler.1"/></toolChain></configuration></cproject>')
H = """typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_o;
extern U8 g_p;
extern U8 g_k;
void lib(void);
void exit(int code);
void halt(void);
void halt2(void);
void halt_brk(void);
void ret_first(U8 x);
void cond_macro(void);
U8 straight(U8 x);
void dowhile0(void);
void calls_loop(void);
void rec(U8 n);
void uses_wait(void);
void uses_set(void);
U8 uses_twice(U8 x);
void never_stop(void);
void ext(void);
void quit(void);
void loops_plain(void);
void wrapper(void);
void goto_out(void);
void goto_skip(void);
void bare_stmt(void);
void maybe_macro(void);
void opaque_loop(void);
void wdt_kick(void);
void trap_di(void);
void trap_reg(void);
void trap_proto(void);
void trap_wmacro(void);
void str_di(void);
void str_leave(void);
"""
L = """#include "h.h"
#define TRUE 1U
#define WAIT() while (g_k != 0U) {}
#define SET() do { } while (0)
#define TWICE(x) ((U8)((x) * 2U))
#define STOP() break
#define HIDE(x) x##_y
#define DI ((void)0)
#define KICK() (g_o = 1U)
U8 SCI0SR1;
void halt(void) { for (;;) {} }
void halt2(void) { g_p = 1U; while (1U) { g_o = 2U; } }
void halt_brk(void) { for (;;) { if (g_k != 0U) { break; } } }
void ret_first(U8 x) { if (x != 0U) { return; } for (;;) {} }
void cond_macro(void) { while (TRUE) {} }
U8 straight(U8 x) { if (x != 0U) { return 1U; } return 2U; }
void dowhile0(void) { do { g_o = 1U; } while (0); }
void calls_loop(void) { halt_brk(); }
void rec(U8 n) { if (n != 0U) { rec((U8)(n - 1U)); } }
void uses_wait(void) { WAIT(); }
void uses_set(void) { SET(); }
U8 uses_twice(U8 x) { return TWICE(x); }
void never_stop(void) { for (;;) { STOP(); } }
void ext(void) { lib(); }
void quit(void) { exit(1); }
void loops_plain(void) { U8 i; for (i = 0U; i < 3U; i++) { g_o = i; } }
void wrapper(void) { loops_plain(); }
void goto_out(void) { for (;;) { if (g_k != 0U) { goto out; } } out: ; }
void goto_skip(void) { goto skip; for (;;) {} skip: ; }
void bare_stmt(void) { for (;;) { LEAVE; } }
void maybe_macro(void) { for (;;) { LEAVE_IF(g_k); } }
void opaque_loop(void) { for (;;) { HIDE(g); } }
void trap_di(void) { DI; for (;;) {} }
void trap_reg(void) { SCI0SR1; for (;;) {} }
void trap_proto(void) { for (;;) { wdt_kick(); } }
void trap_wmacro(void) { for (;;) { KICK(); } }
void str_di(void) { DI; g_o = 1U; }
void str_leave(void) { LEAVE; g_o = 1U; }
"""
U = """#include "h.h"
U8 g_o;
U8 g_p;
U8 g_k;
void e_halt(void) { g_p = 7U; halt(); g_o = 3U; }
void e_straight(void) { g_o = straight(g_k); g_p = 7U; }
void e_loop(void) { loops_plain(); g_p = 7U; }
void e_rec(void) { rec(g_k); g_p = 7U; }
void e_nested(void) { wrapper(); g_p = 7U; }
void e_goto(void) { g_p = 7U; goto_out(); g_o = 5U; }
void e_trap(void) { g_p = 7U; trap_proto(); g_o = 3U; }
"""


def _p(name):
    return os.path.join(ROOT, name)


FILES = {_p("h.h"): H, _p("l.c"): L, _p("u.c"): U}


@pytest.fixture(scope="module")
def project():
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
        ctx = cpc.build_project_context(FILES, cpc.detect_build_config({_p(".cproject"): _CPROJECT}))
        scopes = cpc.build_scopes(ctx, [p for p in FILES if p.endswith(".c")])
        yield ctx, scopes


def _run(project, name, rows, outs, provider=None):
    ctx, scopes = project
    unit = {"name": name, "source_text": FILES[_p("u.c")], "source_path": _p("u.c"), "source_text_complete": True,
            "project_scope": scopes[_p("u.c")]}
    if provider is not None:
        unit["callee_provider"] = provider
    return evaluate_outputs(unit, rows, [outs] * len(rows))


# ── the facts ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, termination", [
    ("halt", "never"),          # for (;;) {}
    ("halt2", "never"),         # statements before a while (1U) with no way out
    ("halt_brk", "may_not"),    # a break leaves it
    ("ret_first", "may_not"),   # a path returns before the loop
    ("cond_macro", "may_not"),  # while (TRUE): a macro is the unit's to read — no literal
    ("straight", "returns"),
    ("dowhile0", "returns"),    # do { … } while (0) never repeats
    ("calls_loop", "may_not"),  # it reaches a function with a loop
    ("rec", "may_not"),         # recursion
    ("uses_wait", "may_not"),   # a macro that loops
    ("uses_set", "may_not"),    # the closure reads a macro's ``while (`` as a call: unknown code
    ("uses_twice", "returns"),  # a macro that only computes
    ("never_stop", "may_not"),  # a macro may break out of the endless loop
    ("ext", "may_not"),         # unknown code
    ("quit", "may_not"),        # exit leaves otherwise (and is unknown code)
    ("loops_plain", "may_not"),
    ("goto_out", "may_not"),    # (review W1) a goto leaves the endless loop
    ("goto_skip", "may_not"),   # (review W1) a goto skips it
    ("bare_stmt", "may_not"),   # (review I1) a lone name may be a macro the unit cannot read
    ("maybe_macro", "may_not"),  # (review I1) unknown code in the endless loop may leave it
    ("opaque_loop", "may_not"),  # (review I1) a macro whose text hides what it does (token pasting)
    # (review W3) what the context reads cannot leave the loop: a macro it read (``DI``), an object read for its side
    #   effect, a prototype-only function, a writing macro — the trap never returns, as the interpreted path says
    ("trap_di", "never"),
    ("trap_reg", "never"),
    ("trap_proto", "never"),
    ("trap_wmacro", "never"),
    ("str_di", "returns"),      # (review W3) a lone macro it read that only computes: still proven to return
    ("str_leave", "may_not"),   # a lone name no file read defines: a macro that may loop
])
def test_the_closure_says_whether_a_call_returns(project, name, termination):
    ctx, scopes = project
    closure = scopes[_p("u.c")]["effects"]["functions"]
    assert closure[name]["termination"] == termination, name
    verdict = {"never": cc.NEVER, "returns": cc.RETURNS, "may_not": cc.MAY_NOT}[termination]
    assert cc._from_closure(name, closure[name]).termination == verdict


def test_a_context_read_before_the_fact_assumes():
    # a definition record without ``termination`` (a context built before step 4b): nothing proven, nothing refused
    ctx = cpc.build_project_context(FILES, cpc.detect_build_config({_p(".cproject"): _CPROJECT}))
    for defs in ctx["files"][_p("l.c")]["functions"].values():
        for d in defs:
            d.pop("termination", None)
    closure = cpc.function_write_closure(ctx)["functions"]
    assert closure["halt"]["termination"] == closure["straight"]["termination"] == ""
    assert cc._from_closure("halt", closure["halt"]).termination == cc.ASSUMED


# ── the record ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_effects_only_callee_that_never_returns_refuses_the_run(project):
    (rec,) = _run(project, "e_halt", [{}], ["g_o", "g_p"])
    assert rec["status"] == "unsupported" and rec["reason"] == "non_terminating_loop:halt", rec
    # interpreted, the same program refuses as well (the loop is run): the same class, not the same text
    (rec,) = _run(project, "e_halt", [{}], ["g_o", "g_p"], _provider(project))
    assert rec["status"] == "unsupported" and rec["reason"] == "non_terminating_loop", rec


def _provider(project, refuse=frozenset()):
    from tests.unit.test_callee_contract_conformance import ForcedEffectsProvider
    ctx, scopes = project
    return ForcedEffectsProvider(ctx, FILES, scopes, cpc.shared_parser(), refuse=refuse)


def test_a_callee_whose_return_is_proven_names_only_its_unjudged_undefined_behaviour(project):
    (rec,) = _run(project, "e_straight", [{"g_k": 1}], ["g_o", "g_p"])
    assert rec["outputs"]["g_p"]["value"] == 7 and "callee_termination_assumed" not in rec, rec
    assert rec["callee_ub_unanalysed"] == ["straight"]
    assert any(a.startswith("undefined behaviour inside callees run as their write closure") and a.endswith(": straight")
               for a in rec["assumptions"]), rec["assumptions"]


def test_a_callee_whose_return_is_not_proven_is_named_and_the_value_stands(project):
    (rec,) = _run(project, "e_loop", [{}], ["g_p"])
    assert rec["outputs"]["g_p"]["value"] == 7
    assert rec["callee_termination_assumed"] == ["loops_plain"] == rec["callee_ub_unanalysed"]
    assert any(a.startswith("termination of callees run as their write closure") and a.endswith(": loops_plain")
               for a in rec["assumptions"]), rec["assumptions"]


def test_a_trap_that_calls_a_prototype_in_its_loop_refuses_the_run_in_every_mode(project):
    # (review W3) ``for (;;) { wdt_kick(); }``: a prototype-only call cannot leave the loop — effects-only and interpreted
    #   both refuse (round 3 had E keep the value after the trap while I refused)
    (rec,) = _run(project, "e_trap", [{}], ["g_o", "g_p"])
    assert rec["status"] == "unsupported" and rec["reason"] == "non_terminating_loop:trap_proto", rec
    (rec,) = _run(project, "e_trap", [{}], ["g_o", "g_p"], _provider(project))
    assert rec["status"] == "unsupported" and rec["reason"].startswith("non_terminating_loop"), rec


def test_a_callee_that_leaves_its_endless_loop_by_goto_keeps_the_value(project):
    # (review W1) HEAD derived g_o = 5 · g_p = 7 here; a goto is a way out, not a proof the call never returns — the value
    #   stands for the runs where it returns and the callee is named (not refused as ``non_terminating_loop:goto_out``)
    (rec,) = _run(project, "e_goto", [{"g_k": 1}], ["g_o", "g_p"])
    assert rec["status"] != "unsupported", rec
    assert (rec["outputs"]["g_o"]["value"], rec["outputs"]["g_p"]["value"]) == (5, 7), rec["outputs"]
    assert rec["callee_termination_assumed"] == ["goto_out"], rec


def test_an_interpreted_callee_leaves_nothing_unjudged_and_passes_up_what_it_did_not_run(project):
    (rec,) = _run(project, "e_loop", [{}], ["g_p", "g_o"], _provider(project))
    assert rec["outputs"]["g_o"]["value"] == 2 and "callee_termination_assumed" not in rec \
        and "callee_ub_unanalysed" not in rec, rec
    # wrapper is interpreted, loops_plain inside it is not: the record names loops_plain (the joined run's)
    (rec,) = _run(project, "e_nested", [{}], ["g_p"], _provider(project, refuse={"loops_plain"}))
    assert rec["interprocedural"]["inlined"] == {"wrapper": 1} and rec["interprocedural"]["effects_only"] == {
        "loops_plain": 1}, rec["interprocedural"]
    assert rec["callee_termination_assumed"] == ["loops_plain"] == rec["callee_ub_unanalysed"]


# ── the evidence, the counts, the disclosures ───────────────────────────────────────────────────────────────────────

def test_the_cells_carry_the_names_and_the_suts_counts_them(project):
    from generators.test_evidence import apply_sequence_evidence, summarize_expected_evidence
    from report_gen.generation_disclosures import build_disclosures
    ctx, scopes = project
    unit = {"name": "e_loop", "source_text": FILES[_p("u.c")], "source_path": _p("u.c"), "source_text_complete": True,
            "project_scope": scopes[_p("u.c")]}
    seqs = [{"inputs": {}, "expected": {"g_p": ""}}]
    apply_sequence_evidence(unit, seqs)
    item = seqs[0]["expected_evidence"]["g_p"]
    assert item["status"] == "derived" and item["callee_termination_assumed"] == ["loops_plain"] \
        and item["callee_ub_unanalysed"] == ["loops_plain"], item
    counts = summarize_expected_evidence(seqs)
    assert (counts["derived_on_assumed_callee_termination"], counts["derived_with_callee_ub_unanalysed"]) == (1, 1)
    (note,) = [i["note"] for i in build_disclosures("suts", {"expected_evidence_summary": counts})
               if i["key"] == "suts_expected_evidence"]
    assert "1칸은 프로젝트에 정의가 있어 본문 대신 쓰기 closure 로 본 피호출 함수가 돌아온다고 가정한" in note \
        and "미정의 동작을 분석하지 않은" in note, note
    # (R95 review W2) the count names callees with a definition only — code without one is in the blanket assumption
    assert "정의가 없는 코드(프로토타입만 있는 함수 · 함수 포인터)의 종료는 이름 없이" in note, note
    # (review I-r3-1) the blanket assumption speaks of reach and termination — UB in code without a body is said apart
    assert "정의가 없는 코드 안의 미정의 동작은 본문이 없어 분석 대상 밖" in note, note


def test_the_integration_stats_count_cells_on_a_callee_not_interpreted(project):
    # SITS: `rec` re-enters itself — the inner call runs as its write closure (recursion), whose return is not proven
    from generators.integration_oracle import attach_integration_evidence
    from report_gen.generation_disclosures import build_disclosures
    ctx, _scopes = project
    subs = [{"inputs": {"g_k": 2}, "expected": {"g_p": "N/A"}}]
    stats = attach_integration_evidence([{"tc_id": "T1", "entry_fn": "e_rec", "sub_cases": subs}],
                                        {"project_context": ctx, "source_files": FILES},
                                        {"f": {"name": "e_rec", "source_path": _p("u.c")}})
    assert subs[0]["expected"] == {"g_p": 7}
    assert (stats["derived_on_assumed_callee_termination"], stats["derived_with_callee_ub_unanalysed"]) == (1, 1), stats
    (item,) = [i for i in build_disclosures("sits", {"integration_oracle": stats}) if i["key"] == "sits_integration_oracle"]
    assert "1칸은 프로젝트에 정의가 있어 본문 대신 쓰기 closure 로 본 피호출 함수가 돌아온다고 가정한" in item["note"], item["note"]
