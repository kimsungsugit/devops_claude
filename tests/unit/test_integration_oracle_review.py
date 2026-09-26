"""(R16 review round 1) Wrong values the interprocedural oracle used to claim — each case is the reviewer's probe, the
comment says what the C program really does. A derived value must be that value; otherwise the slot is unknown."""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import Unsupported, evaluate_outputs
from generators.integration_oracle import CalleeProvider

ROOT = os.path.join(os.sep, "virt_r16r")
H = """#ifndef H_H
#define H_H
typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_out; extern U8 g_in;
U8 latch(U8 v);
void via_c(void);
void Clear(U8 *p);
U8 *GetBPtr(void);
void SetB(void);
U8 GetB(void);
void Wipe(U8 *p);
void NoInline(void);
U8 inner(U8 v);
U8 nest(void);
void *vp(void);
#endif
"""
B = """#include "h.h"
U8 latch(U8 v) { static U8 last; U8 prev; prev = last; last = v; return prev; }
U8 b_arr[2];
U8 *GetBPtr(void) { return b_arr; }
void SetB(void) { b_arr[0] = 5U; }
U8 GetB(void) { return b_arr[0]; }
void Clear(U8 *p) { p[0] = 0U; }
void NoInline(void) { (void)latch(9U); goto x; x: ; }
U8 inner(U8 v) { static U8 last; U8 p; p = last; last = v; return p; }
U8 nest(void) { return inner(5U); }
void *vp(void) { return 0; }
"""
C = """#include "h.h"
void via_c(void) { (void)latch(7U); }
void Wipe(U8 *p) { p[0] = 0U; }
"""
A = """#include "h.h"
U8 g_out; U8 g_in;
static U8 s_buf[2];
void e_rawid(void) { (void)latch(3U); via_c(); g_out = latch(4U); }
void e_haveptr(U8 *q) { *q = 1U; s_buf[0] = 5U; Clear(s_buf); g_out = s_buf[0]; }
void e_worldarr(void) { SetB(); Wipe(GetBPtr()); g_out = GetB(); }
void e_noinline(void) { (void)latch(3U); NoInline(); g_out = latch(4U); }
void e_observe(void) { SetB(); Wipe(GetBPtr()); }
void e_nested(void) { (void)nest(); g_out = nest(); }
void e_voidp(void) { (void)vp(); }
"""


def _run(entry, outputs, inputs=None, extra=None):
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "a.c"): A, os.path.join(ROOT, "b.c"): B,
             os.path.join(ROOT, "c.c"): C, **(extra or {})}
    ctx = cpc.build_project_context(files)
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    a = os.path.join(ROOT, "a.c")
    unit = {"name": entry, "source_text": files[a], "source_path": a, "source_text_complete": True,
            "project_scope": scopes[a], "callee_provider": CalleeProvider(ctx, files, scopes, cpc.shared_parser())}
    return evaluate_outputs(unit, [inputs or {}], [outputs])[0]


def _out(r, name):
    return r["outputs"][name].get("value"), r["outputs"][name].get("reason", "")


def test_c1_one_static_whichever_unit_calls_the_function():
    # latch's ``last`` is one object: 3, then 7 (via c.c), and the last call returns 7
    assert _out(_run("e_rawid", ["g_out"]), "g_out")[0] == 7


def test_c2_a_callee_run_as_effects_may_change_an_interpreted_function_static():
    # NoInline (goto: not interpreted) calls latch(9): the real result is 9 — never the 3 of the first call
    value, reason = _out(_run("e_noinline", ["g_out"]), "g_out")
    assert value is None and reason == "callee_not_interpreted:NoInline"


def test_c3_a_pointer_write_after_an_earlier_one_still_reaches_the_caller_array():
    # *q made the pointer mark once already; Clear(s_buf) writes s_buf[0] = 0 — never the 5 before it
    assert _out(_run("e_haveptr", ["g_out"]), "g_out")[0] in (None, 0)


def test_c4_an_array_only_another_unit_declares_is_reached_by_pointer_writes():
    assert _out(_run("e_worldarr", ["g_out"]), "g_out")[0] in (None, 0)          # really 0, never 5
    assert _out(_run("e_observe", ["b_arr[0]"]), "b_arr[0]")[0] in (None, 0)
    assert _out(_run("e_observe", ["b_arr[1]"], {"b_arr[1]": 4}), "b_arr[1]")[0] is None   # the input may be overwritten


def test_i1_a_nested_callee_static_survives_the_outer_join():
    assert _out(_run("e_nested", ["g_out"]), "g_out")[0] == 5


def test_c6_a_static_inline_in_an_included_header_is_the_callee():
    inl = os.path.join(ROOT, "inl.h")
    a = A.replace('#include "h.h"', '#include "h.h"\n#include "inl.h"') + "void usesinl(void) { g_out = clampx(9U); }\n"
    extra = {inl: '#include "h.h"\nstatic U8 clampx(U8 v) { return (U8)(v > 5U ? 5U : v); }\n',
             os.path.join(ROOT, "b.c"): B + "U8 clampx(U8 v) { return 99U; }\n", os.path.join(ROOT, "a.c"): a}
    r = _run("usesinl", ["g_out"], extra=extra)
    assert _out(r, "g_out")[0] is None   # really 5 (the header's), never b.c's 99
    assert r["interprocedural"]["failed"]["clampx"] == "definition:defined_in_included_file"


def test_w1_an_extern_object_declared_with_two_types_is_not_one_object():
    extra = {os.path.join(ROOT, "d.c"): '#include "h.h"\nextern U16 g_wide;\nvoid d_set(void) { g_wide = 300U; }\n',
             os.path.join(ROOT, "a.c"): A + "U8 g_wide;\nvoid d_set(void);\nvoid e_wide(void) { d_set(); }\n"}
    r = _run("e_wide", ["g_wide"], extra=extra)
    assert r["interprocedural"]["failed"]["d_set"] == "linkage_collision:g_wide"


def test_i3_a_pointer_returning_function_is_not_void():
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "a.c"): A, os.path.join(ROOT, "b.c"): B,
             os.path.join(ROOT, "c.c"): C}
    ctx = cpc.build_project_context(files)
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    prov = CalleeProvider(ctx, files, scopes, cpc.shared_parser())
    raw, fn, scope, shared, _path = prov.definition("vp", os.path.join(ROOT, "a.c"))
    from generators.c_source_oracle import _Interp, _State, _World
    sub = _Interp(fn, raw, scope, {}, cpc.shared_parser(), shared)
    state = _State()
    state.mode = "return"
    _merged, value = _World.join(sub, [state], "vp")
    assert not value.v.reason.startswith("void_call_value")


def test_provider_refuses_what_it_cannot_bind():
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "a.c"): A}
    ctx = cpc.build_project_context(files)
    scopes = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])
    prov = CalleeProvider(ctx, files, scopes, cpc.shared_parser())
    with pytest.raises(Unsupported, match="no_definition_in_project"):
        prov.definition("latch", os.path.join(ROOT, "a.c"))


# ── round 2 ──────────────────────────────────────────────────────────────────────────────────────────────────────
H2 = "#ifndef H_H\n#define H_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\nextern U8 g_out; extern U8 g_in;\n#endif\n"


def _run2(sources, entry, inputs, outputs, roots=()):
    files = {os.path.join(ROOT, "h.h"): H2, **{os.path.join(ROOT, k): v for k, v in sources.items()}}
    ctx = cpc.build_project_context(files, roots=roots)
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    a = os.path.join(ROOT, "a.c")
    unit = {"name": entry, "source_text": files[a], "source_path": a, "source_text_complete": True,
            "project_scope": scopes[a], "callee_provider": CalleeProvider(ctx, files, scopes, cpc.shared_parser())}
    return evaluate_outputs(unit, [inputs], [outputs])[0]


RD_B = ('#include "h.h"\nU8 buf[4];\nU8 idx;\nU8 Rd(void) { U8 v = buf[idx]; idx++; return v; }\n'
        "U8 sub2(U8 a, U8 b) { return (U8)(a - b); }\nU8 Pure(U8 a) { return a; }\n")
RD_A = ('#include "h.h"\nU8 g_out; U8 g_in;\nU8 Rd(void); U8 sub2(U8 a, U8 b); U8 Pure(U8 a);\n'
        "void e1(void) { g_out = (U8)(Rd() - Rd()); }\n"
        "void e2(void) { g_out = sub2(Rd(), Rd()); }\n"
        "void e3(void) { U8 a = Rd(); U8 b = Rd(); g_out = (U8)(a - b); }\n"
        "void e4(void) { g_out = (U8)(Pure(1U) + Pure(2U)); }\n")
RD_IN = {"idx": 0, "buf[0]": 10, "buf[1]": 3, "buf[2]": 0, "buf[3]": 0}


def test_r2_c1_unordered_effectful_calls_are_not_given_one_order():
    for entry in ("e1", "e2"):
        r = _run2({"a.c": RD_A, "b.c": RD_B}, entry, RD_IN, ["g_out"])
        assert _out(r, "g_out")[0] is None   # 7 left to right, 249 right to left: unspecified (C11 6.5.2.2p10)
    # sequenced by the statements: 10 - 3
    assert _out(_run2({"a.c": RD_A, "b.c": RD_B}, "e3", RD_IN, ["g_out"]), "g_out")[0] == 7
    # two calls without effects: order cannot matter
    assert _out(_run2({"a.c": RD_A, "b.c": RD_B}, "e4", {}, ["g_out"]), "g_out")[0] == 3   # 1 + 2


def test_r2_c3_a_callee_that_never_returns_refuses_the_run():
    b = '#include "h.h"\nU8 WDG;\nvoid Reset(void) { WDG = 0xFFU; while (1U) { } }\nvoid Spin(void) { for (;;) { } }\n' \
        "void Poll(void) { while (1U) { if (g_in == 0U) { break; } g_in--; } }\n"
    a = '#include "h.h"\nU8 g_out; U8 g_in;\nvoid Reset(void); void Spin(void); void Poll(void);\n' \
        "void f(void) { g_out = 1U; if (g_in > 3U) { Reset(); } g_out = 2U; }\n" \
        "void s(void) { Spin(); g_out = 2U; }\nvoid p(void) { Poll(); g_out = 2U; }\n"
    r = _run2({"a.c": a, "b.c": b}, "f", {"g_in": 5}, ["g_out"])
    assert r["status"] == "unsupported" and r["reason"] == "non_terminating_loop"
    assert _run2({"a.c": a, "b.c": b}, "s", {}, ["g_out"])["reason"] == "non_terminating_loop"
    # ``while (1U)`` with a break is not endless; the path that does not call Reset is untouched
    assert _out(_run2({"a.c": a, "b.c": b}, "p", {"g_in": 2}, ["g_out"]), "g_out")[0] == 2
    assert _out(_run2({"a.c": a, "b.c": b}, "f", {"g_in": 1}, ["g_out"]), "g_out")[0] == 2


def test_r2_c2_a_c_file_included_into_the_caller_is_that_text_not_its_own_unit():
    calib = "U8 calib_fn(U8 v) { return (U8)(v * CALIB_GAIN); }\n"
    a = '#include "h.h"\n#define CALIB_GAIN 3U\n#include "calib.c"\nU8 g_out; U8 g_in;\nvoid f(void) { g_out = calib_fn(2U); }\n'
    r = _run2({"a.c": a, "calib.c": '#include "h.h"\n#define CALIB_GAIN 1U\n' + calib}, "f", {}, ["g_out"])
    assert _out(r, "g_out")[0] is None   # really 6 (a.c's gain), never calib.c's own 2
    assert r["interprocedural"]["failed"]["calib_fn"] == "definition:defined_in_included_file"


def test_r2_w1_a_name_two_objects_share_binds_to_neither():
    b = '#include "h.h"\nstatic U8 s_init;\nU8 B_IsReady(void) { return s_init; }\n'
    c = '#include "h.h"\nstatic U8 s_init;\nvoid C_Set(void) { s_init = 1U; }\n'
    a = '#include "h.h"\nU8 g_out; U8 g_in;\nU8 B_IsReady(void);\nvoid f(void) { g_out = B_IsReady(); }\n'
    r = _run2({"a.c": a, "b.c": b, "c.c": c}, "f", {"s_init": 1}, ["g_out", "s_init"])
    assert _out(r, "g_out") == (None, "object_name_ambiguous_in_project:s_init")
    assert _out(r, "s_init") == (None, "observable_name_ambiguous_in_project:s_init")


def test_r2_w4_undefined_behaviour_in_a_callee_refuses_the_run():
    b = '#include "h.h"\nU8 Bad(void) { U8 i = 1U; i = i++ + 1U; return i; }\n'
    a = '#include "h.h"\nU8 g_out; U8 g_in;\nU8 Bad(void);\nvoid f(void) { g_out = Bad(); g_in = 3U; }\n'
    r = _run2({"a.c": a, "b.c": b}, "f", {}, ["g_out", "g_in"])
    assert r["status"] == "unsupported" and r["reason"] == "unsequenced_side_effects"


# ── round 3 ──────────────────────────────────────────────────────────────────────────────────────────────────────
R3_B = ('#include "h.h"\nU8 buf[4];\nU8 idx;\nU8 Rd(void) { U8 v = buf[idx]; idx++; return v; }\n'
        "U8 Inc(void) { g_in++; return g_in; }\nU8 Wr(void) { g_in = 10U; return 0U; }\nU8 Get(void) { return g_in; }\n"
        "U8 First(U8 a, U8 b) { (void)b; return a; }\n"
        "U8 F(U8 v) { static U8 last; U8 p; p = last; last = v; return p; }\nU8 G(U8 a, U8 b) { return (U8)(a + b); }\n"
        "void WaitFlag(void) { while (1U) { if (g_in != 0U) { break; } } }\n"
        "void Sw(void) { while (1U) { switch (g_in) { case 0U: break; default: g_in = 0U; break; } } }\n")
R3_A = ('#include "h.h"\n#define PAR(a) (a)\nU8 g_out; U8 g_in; U8 g_out2;\n'
        "U8 Rd(void); U8 Inc(void); U8 Wr(void); U8 Get(void); U8 First(U8 a, U8 b); U8 F(U8 v); U8 G(U8 a, U8 b);\n"
        "void WaitFlag(void); void Sw(void);\n"
        "void w1(void) { g_out = (U8)(Get() + (g_in = 5U)); }\n"
        "void w2(void) { g_out = First(PAR(Inc()), Wr()); }\n"
        "void w3(void) { g_out = G(F(1U), F(2U)); }\n"
        "void w4(void) { g_out = 1U; WaitFlag(); g_out2 = 2U; }\n"
        "void w5(void) { Sw(); g_out = 3U; }\n"
        "void w6(void) { g_out = (Inc()) + 1U; }\n")
R3_IN = {"idx": 0, "buf[0]": 1, "buf[1]": 2, "buf[2]": 0, "buf[3]": 0, "g_in": 0}


def _r3(entry, outputs=("g_out",), inputs=None):
    return _run2({"a.c": R3_A, "b.c": R3_B}, entry, dict(R3_IN if inputs is None else inputs), list(outputs))


def test_r3_c1_a_call_unordered_with_the_callers_own_write_is_not_given_one_order():
    # Get() reads g_in while the caller writes it in the same expression: 0 + 5 or 5 + 5 (C11 6.5.2.2p10)
    assert _out(_r3("w1"), "g_out")[0] is None


def test_r3_c2_a_call_inside_a_macro_argument_carries_the_mark_into_the_expansion():
    # First(PAR(Inc()), Wr()): 1 if Inc runs first, 11 if Wr does
    assert _out(_r3("w2"), "g_out")[0] is None


def test_r3_w2_a_callee_with_a_static_local_is_effectful():
    # G(F(1U), F(2U)): F's static ``last`` makes the order visible (1 + 0 or 0 + 2 after an unknown entry state)
    r = _r3("w3")
    assert _out(r, "g_out")[0] is None and "F" not in r["interprocedural"]["inlined"]


def test_r3_c3_a_constant_condition_loop_that_runs_out_never_returns():
    r = _r3("w4", ("g_out", "g_out2"), {"g_in": 0})
    assert r["status"] == "unsupported" and r["reason"] == "constant_condition_loop_unfinished"
    assert _out(_r3("w4", ("g_out2",), {"g_in": 1}), "g_out2")[0] == 2


def test_r3_w2_a_break_inside_a_switch_does_not_leave_the_loop():
    r = _r3("w5")
    assert r["status"] == "unsupported" and r["reason"] == "non_terminating_loop"


def test_r3_c4_a_parenthesized_call_read_as_a_cast_is_refused_not_dropped():
    r = _r3("w6", ("g_out", "g_in"))
    assert r["status"] == "unsupported" and r["reason"] == "cast_parse_of_parenthesized_expression"


# ── round 4 ──────────────────────────────────────────────────────────────────────────────────────────────────────
R4_B = ('#include "h.h"\nvolatile U8 REG;\nU8 Wr(void) { g_in = 10U; return 1U; }\nU8 Inc(void) { g_in++; return 0U; }\n'
        "U8 Outer(void) { return (Inc()) + 1U; }\nU8 Side(void) { g_out2 = 7U; return 0U; }\n"
        "void Poll(void) { for (;;) { if (REG != 0U) { break; } } }\n")
R4_A = ('#include "h.h"\nU8 g_out; U8 g_in; U8 g_out2;\nU8 Wr(void); U8 Outer(void); U8 Side(void); void Poll(void);\n'
        "void v1(void) { g_in += Wr(); g_out = g_in; }\n"
        "void v2(void) { g_out = (U8)(Outer() + Side()); }\n"
        "void v3(void) { Poll(); g_out = 1U; }\n"
        "void v4(void (*q)(void)) { g_out = (U8)(((void (*)(void))q) != 0); g_out2 = 4U; }\n")


def _r4(entry, outputs=("g_out",), inputs=None):
    return _run2({"a.c": R4_A, "b.c": R4_B}, entry, dict(inputs or {"g_in": 0}), list(outputs))


def test_r4_c1_a_compound_assignment_reads_its_target_unsequenced_with_the_call():
    # g_in += Wr(): the read of g_in may come before (0 + 1) or after (10 + 1) Wr's body — C11 6.5.16p3
    assert _out(_r4("v1"), "g_out")[0] is None


def test_r4_w1_a_call_hidden_in_a_cast_misparse_is_in_the_write_closure():
    # Outer runs as effects only (unordered with Side, which writes only g_out2): its hidden Inc() writes g_in — never
    # "unchanged" (review R5: a partner that also wrote g_in made this pass without the closure fix)
    r = _r4("v2", ("g_in",), {"g_in": 1})
    assert _out(r, "g_in")[0] is None


def test_r4_w3_a_polling_loop_that_has_a_way_out_falls_back_as_before():
    assert _out(_r4("v3"), "g_out")[0] == 1


def test_r4_w2_a_real_type_with_parentheses_is_a_cast_not_a_refusal():
    r = _r4("v4", ("g_out", "g_out2"))
    assert r["status"] == "supported" and _out(r, "g_out2")[0] == 4


def test_r4_closure_scan_records_the_hidden_call_by_name():
    parser = cpc.shared_parser()
    raw = b"U8 Outer(void) { g = f(1); return (Inc()) + 1U; }\n"
    fn = parser.parse(raw).root_node.named_children[0]
    assert cpc._function_effects(fn, raw)["calls"] == ["Inc", "f"]


def test_r4_a_compound_assignment_to_a_local_no_callee_can_reach_keeps_the_call_interpreted():
    a = R4_A + "void v5(void) { U8 err = 2U; err |= Wr(); g_out = err; }\n"
    r = _run2({"a.c": a, "b.c": R4_B}, "v5", {"g_in": 0}, ["g_out"])
    assert _out(r, "g_out")[0] == 3 and r["interprocedural"]["inlined"].get("Wr") == 1
