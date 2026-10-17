"""Callee summary contract — the conformance harness (step 1; `generators.callee_contract`, steps 2–4, holds to it).

A call is produced in several ways (design: ``callee_contract_design.md``): interpreted (``_World.inline``), effects only
inside a world, effects only without a world (SUTS), a sequence stub, unknown code. Each way is a *mode*; the same C
shape is run in every mode that applies and the modes are compared by precision:

    T  the callee body pasted literally into the caller (world present)
    I  the callee interpreted (`_World.inline`, a `CalleeProvider` world — SITS style)
    Ew effects only inside a world (`ForcedEffectsProvider` refuses the shape's callees: ``forced_effects_only``)
    E0 effects only, no world (SUTS style: `evaluate_outputs` without a provider)
    U  prototype only / a function pointer (unknown code)
    S  the sequence stub (``F() return`` / ``F() p[0]`` input rows; ``Sw`` the same inside a world)
    IS the same stub written as a C body and interpreted

    T >= I >= Ew,  I >= E0,  Ew / E0 >= U,  IS >= S

`verdict` compares a weaker mode's cell with a stronger mode's: a weaker mode may know less, never more, and never
something else. CONTRADICTION (two values differ) and INVENTION (the weak mode confirms a value the strong mode does not)
must be 0. Where the strong mode refuses the record for a *program* reason (undefined behaviour, a path that never
returns) the weak value is ``ok_disclosed`` only when the weak record discloses that very assumption for one of the
shape's callees — the blanket "termination of callees is not proven" names no callee and does not count. A strong
refusal for the step budget is inconclusive. A strong refusal for a *model* reason (the strong mode gave up — a polling
loop whose body reads its flag, a parse it does not read) with a weak value is ``model_gap``: no proof the weak value is
wrong, but the precision order is broken there — every such cell must be listed in `MODEL_GAPS` with why.

Tests assert relations between modes, not modelling choices: F6 (register storage) is being finished conservatively
(after any callee not interpreted every volatile object is unknown, the polling memo goes, a loop body reading any polled
register refuses, a call not provably free of volatile access is unsequenced against register reads) — a weak mode that
becomes less precise keeps every relation below. Absolute values are asserted only where they are program facts.

Known gaps (`callee_contract_design.md` "Gaps found") are separate tests, excluded from the shape tests: a precision gap
(the weak mode knows less than it could — G8, G11) is `xfail(strict=True)`; a gap that confirms a wrong value (G4, G5,
G6 — INVENTION) is a SOUNDNESS FINDING and is not xfailed (G5 / G6 hold since steps 4b / 4c: an effects-only callee
that never returns refuses the run, one whose termination or undefined behaviour is not judged is named on the
record). The guard is proven able to fail by mutations — of the harness's relations and of steps 4b / 4c.
"""
from __future__ import annotations

import os
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

import pytest

from generators import c_project_context as cpc
from generators import c_source_oracle as cso
from generators.c_source_oracle import Unsupported, evaluate_outputs
from generators.integration_oracle import CalleeProvider

ROOT = os.path.join(os.sep, "cc_conf")
ROOT14 = os.path.join(os.sep, "cc_conf14")

# an S12Z build target (big-endian, bit-fields from the least significant bit) — as tests/unit/test_register_model_r90.py
_CPROJECT = ('<?xml version="1.0"?><cproject><configuration><toolChain superClass="com.freescale.s12z.toolchain.release">'
             '<tool superClass="com.freescale.s12z.toolchain.compiler.1"/></toolChain></configuration></cproject>')

H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
typedef union { U8 Byte; struct { U8 F :1; U8 G :1; U8 :6; } Bits; } RSTR;
extern volatile RSTR REG_A @0x00000390;
extern volatile RSTR REG_B @0x00000391;
#define A_F REG_A.Bits.F
#define A_F_MASK 0x01U
#define A_G REG_A.Bits.G
#define A_G_MASK 0x02U
#define B_F REG_B.Bits.F
#define B_F_MASK 0x01U
extern U8 g_o;
extern U8 g_p;
extern U8 g_n;
extern U8 g_q;
extern U8 g_k;
extern U8 g_d;
typedef U8 (*FP)(void);
void Wait(void);
U8 Rd(void);
void Put(U8 *p);
void Halt(void);
U8 Div(U8 d);
U8 Bad(U8 v);
U8 GetG(void);
U8 GetR(void);
U8 Rec(U8 n);
U8 Seven(void);
void SetSome(U8 c);
U8 Chk(U8 v);
U8 Inc(void);
U8 CastUse(void);
U8 Helper(U8 v);
U8 Rec2(void);
void WaitU(void);
U8 GetU(void);
void PutU(U8 *p);
void SetU(U8 c);
U8 Rd_is(void);
void Put_is(U8 *p);
U8 Div_is(U8 d);
U8 GetG_is(void);
U8 GetR_is(void);
U8 Chk_is(U8 v);
"""
# the callees (their own translation unit)
L = """#include "h.h"
void Wait(void) { while (REG_A.Bits.F == 1U) {} }
U8 Rd(void) { return (U8)REG_A.Bits.F; }
void Put(U8 *p) { *p = 9U; }
void Halt(void) { for (;;) {} }
U8 Div(U8 d) { if (d == 0U) { return (U8)(10U / d); } return 2U; }
U8 Bad(U8 v) { U8 z = 0U; if (v > 3U) { return (U8)(10U / z); } return (U8)(20U / z); }
U8 GetG(void) { return g_k; }
U8 GetR(void) { return REG_A.Byte; }
U8 Rec(U8 n) { if (n == 0U) { return 0U; } return (U8)(Rec((U8)(n - 1U)) + 1U); }
U8 Seven(void) { return 7U; }
void SetSome(U8 c) { if (c != 0U) { g_q = 1U; } }
U8 Chk(U8 v) { g_n = (U8)(g_n + 1U); return (U8)(v > 2U); }
U8 Inc(void) { g_n = (U8)(g_n + 1U); return g_n; }
U8 CastUse(void) { return (U8)((Inc()) + 1U); }
U8 Helper(U8 v) { if (v == 0x80U) { return Rec2(); } return (U8)(v + 1U); }
U8 Rec2(void) { return Helper(1U); }
"""
# the sequence stubs written as C bodies (mode IS): the value the row's ``F() return`` / ``F() p[0]`` gives, nothing else
LS = """#include "h.h"
U8 Rd_is(void) { return 1U; }
void Put_is(U8 *p) { p[0] = 4U; }
U8 Div_is(U8 d) { return 6U; }
U8 GetG_is(void) { return 6U; }
U8 GetR_is(void) { return 6U; }
U8 Chk_is(U8 v) { return 1U; }
"""
# the entries: ``sN`` (I · Ew · E0 · S), ``sN_t`` (T), ``sN_u`` (U), ``sN_is`` (IS)
U = """#include "h.h"
U8 g_o;
U8 g_p;
U8 g_n;
U8 g_q;
U8 g_k;
U8 g_d;
void s1(void) { Wait(); g_o = REG_A.Byte; g_p = 7U; }
void s1_t(void) { while (REG_A.Bits.F == 1U) {} g_o = REG_A.Byte; g_p = 7U; }
void s1_u(void) { WaitU(); g_o = REG_A.Byte; g_p = 7U; }
void s2(void) { g_n = 0U; while (REG_A.Bits.F == 1U) { g_n = Rd(); } g_p = 7U; }
void s2_t(void) { g_n = 0U; while (REG_A.Bits.F == 1U) { g_n = (U8)REG_A.Bits.F; } g_p = 7U; }
void s2_is(void) { g_n = 0U; while (REG_A.Bits.F == 1U) { g_n = Rd_is(); } g_p = 7U; }
void s3(void) { U8 t = 5U; g_q = 3U; Put(&t); g_o = t; Put(&g_q); g_p = 7U; }
void s3_t(void) { U8 t = 5U; U8 *p; g_q = 3U; p = &t; *p = 9U; g_o = t; p = &g_q; *p = 9U; g_p = 7U; }
void s3_u(void) { U8 t = 5U; g_q = 3U; PutU(&t); g_o = t; PutU(&g_q); g_p = 7U; }
void s3_is(void) { U8 t = 5U; g_q = 3U; Put_is(&t); g_o = t; Put_is(&g_q); g_p = 7U; }
void s4(void) { g_p = 7U; Halt(); g_o = 3U; }
void s4_t(void) { g_p = 7U; for (;;) {} g_o = 3U; }
void s5(void) { g_p = 7U; g_o = Div(g_d); }
void s5_t(void) { U8 r; U8 d = g_d; g_p = 7U; if (d == 0U) { r = (U8)(10U / d); } else { r = 2U; } g_o = r; }
void s5_is(void) { g_p = 7U; g_o = Div_is(g_d); }
void s6(void) { g_p = 7U; g_o = Bad(g_d); }
void s6_t(void) { U8 r; U8 z = 0U; g_p = 7U; if (g_d > 3U) { r = (U8)(10U / z); } else { r = (U8)(20U / z); } g_o = r; }
void s7(void) { g_o = GetG(); g_p = 7U; }
void s7_t(void) { g_o = g_k; g_p = 7U; }
void s7_u(void) { g_o = GetU(); g_p = 7U; }
void s7_is(void) { g_o = GetG_is(); g_p = 7U; }
void s8(void) { g_o = GetR(); g_p = REG_A.Byte; }
void s8_t(void) { g_o = REG_A.Byte; g_p = REG_A.Byte; }
void s8_is(void) { g_o = GetR_is(); g_p = REG_A.Byte; }
void s9(void) { g_q = 5U; g_o = Rec(g_k); g_p = 7U; }
void s10(void) { FP f = &Seven; g_q = 5U; g_o = f(); g_p = 7U; }
void s10_t(void) { g_q = 5U; g_o = 7U; g_p = 7U; }
void s11(void) { g_q = 5U; SetSome(g_k); g_o = g_q; g_p = 7U; }
void s11_t(void) { U8 c; g_q = 5U; c = g_k; if (c != 0U) { g_q = 1U; } g_o = g_q; g_p = 7U; }
void s11_u(void) { g_q = 5U; SetU(g_k); g_o = g_q; g_p = 7U; }
void s12a(void) { g_n = 0U; if ((g_k > 1U) && (Chk(g_k) != 0U)) { g_o = 1U; } else { g_o = 2U; } g_p = 7U; }
void s12a_t(void) {
    U8 r = 0U;
    g_n = 0U;
    if (g_k > 1U) { g_n = (U8)(g_n + 1U); r = (U8)(g_k > 2U); }
    if ((g_k > 1U) && (r != 0U)) { g_o = 1U; } else { g_o = 2U; }
    g_p = 7U;
}
void s12a_is(void) { g_n = 0U; if ((g_k > 1U) && (Chk_is(g_k) != 0U)) { g_o = 1U; } else { g_o = 2U; } g_p = 7U; }
void s12b(void) { g_n = 0U; g_o = (g_k > 1U) ? Chk(g_k) : 9U; g_p = 7U; }
void s12b_t(void) { g_n = 0U; if (g_k > 1U) { g_n = (U8)(g_n + 1U); g_o = (U8)(g_k > 2U); } else { g_o = 9U; } g_p = 7U; }
void s12b_is(void) { g_n = 0U; g_o = (g_k > 1U) ? Chk_is(g_k) : 9U; g_p = 7U; }
void s12c(void) { U8 i = 0U; g_n = 0U; while ((i < 3U) && (Chk(i) == 0U)) { i++; } g_o = i; g_p = 7U; }
void s12c_t(void) {
    U8 i = 0U;
    U8 r = 0U;
    g_n = 0U;
    while (i < 3U) { g_n = (U8)(g_n + 1U); r = (U8)(i > 2U); if (r != 0U) { break; } i++; }
    g_o = i;
    g_p = 7U;
}
void s12c_is(void) { U8 i = 0U; g_n = 0U; while ((i < 3U) && (Chk_is(i) == 0U)) { i++; } g_o = i; g_p = 7U; }
void s13(void) { g_o = (U8)(REG_A.Bits.F + (Wait(), 0U)); g_p = 7U; }
void s13_t1(void) { U8 t = (U8)REG_A.Bits.F; while (REG_A.Bits.F == 1U) {} g_o = (U8)(t + 0U); g_p = 7U; }
void s13_t2(void) { U8 t; while (REG_A.Bits.F == 1U) {} t = (U8)REG_A.Bits.F; g_o = (U8)(t + 0U); g_p = 7U; }
void s15(void) { g_n = 1U; g_o = CastUse(); g_p = 7U; }
void s15_t(void) { g_n = 1U; g_o = (U8)(Inc() + 1U); g_p = 7U; }
void s16(void) { while ((REG_A.Byte != 0U) && (Helper(REG_A.Byte) != 0U)) {} g_o = Helper(4U); g_p = 7U; }
void g8(void) { g_o = (U8)(Chk(1U) + GetG()); g_p = 7U; }
void g8_is(void) { g_o = (U8)(Chk_is(1U) + GetG()); g_p = 7U; }
"""
# (S14, R89) two source roots are two builds: each defines ``drv`` — a call links within its own build
H14 = "typedef unsigned char U8;\ntypedef unsigned int U16;\nextern U8 g_v;\nextern U8 g_p;\nU8 drv(void);\n"
FILES14 = {
    os.path.join(ROOT14, "app", "m.h"): H14,
    os.path.join(ROOT14, "boot", "m.h"): H14,
    os.path.join(ROOT14, "app", "main.c"): '#include "m.h"\nU8 g_v;\nU8 g_p;\n'
                                           "void s14(void) { g_v = drv(); g_p = 7U; }\n"
                                           "void s14_t(void) { g_v = 1U; g_p = 7U; }\n",
    os.path.join(ROOT14, "app", "drv.c"): '#include "m.h"\nU8 drv(void) { return 1U; }\n',
    os.path.join(ROOT14, "boot", "drv.c"): '#include "m.h"\nU8 drv(void) { return 2U; }\n',
}


def _p(name):
    return os.path.join(ROOT, name)


FILES = {_p("h.h"): H, _p("l.c"): L, _p("ls.c"): LS, _p("u.c"): U}


@dataclass
class Project:
    files: dict
    context: dict
    scopes: dict
    entry_path: str


@pytest.fixture(scope="module")
def projects():
    """Every in-memory project built once for the module (the S12Z target pins one byte order and bit allocation)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
        yield _build_projects()


def _build_projects():
    build = cpc.detect_build_config({_p(".cproject"): _CPROJECT})
    ctx = cpc.build_project_context(FILES, build)
    scopes = cpc.build_scopes(ctx, [p for p in FILES if p.endswith(".c")])
    ctx14 = cpc.build_project_context(FILES14, roots=[os.path.join(ROOT14, "app"), os.path.join(ROOT14, "boot")])
    scopes14 = cpc.build_scopes(ctx14, [p for p in FILES14 if p.endswith(".c")])
    return {"main": Project(FILES, ctx, scopes, _p("u.c")),
            "twins": Project(FILES14, ctx14, scopes14, os.path.join(ROOT14, "app", "main.c"))}


# ── modes ────────────────────────────────────────────────────────────────────────────────────────────────────────────

class ForcedEffectsProvider(CalleeProvider):
    """A world whose provider refuses to give the definitions of ``refuse``: those calls run as their write closure
    inside an otherwise interpreted run (mode Ew) — what a budget, a depth or an unsequenced site does to a callee."""

    def __init__(self, context, files, scopes, parser, refuse=frozenset()):
        super().__init__(context, files, scopes, parser)
        self.refuse = frozenset(refuse)

    def definition(self, name, caller_unit):
        if name in self.refuse:
            raise Unsupported("forced_effects_only")
        return super().definition(name, caller_unit)


MODES = ("T", "I", "Ew", "E0", "U", "S", "Sw", "IS")
# (weak, strong): the strong mode is at least as precise as the weak one
PAIRS = (("I", "T"), ("Ew", "T"), ("E0", "T"), ("U", "T"), ("Ew", "I"), ("E0", "I"), ("U", "I"), ("U", "Ew"),
         ("U", "E0"), ("S", "IS"), ("Sw", "IS"))


@dataclass(frozen=True)
class Shape:
    sid: str
    title: str
    entries: dict            # mode → entry function (T: a tuple = the orders C allows, joined)
    rows: tuple              # the rows every mode runs (S / Sw add ``stubs``)
    outs: tuple
    callees: frozenset       # the callees Ew refuses and a disclosure must name
    stubs: dict = field(default_factory=dict)
    project: str = "main"


def _all(entry, t=None, u=None, is_=None, stubbed=False):
    out = {"I": entry, "Ew": entry, "E0": entry}
    if t is not None:
        out["T"] = t
    if u is not None:
        out["U"] = u
    if is_ is not None:
        out["IS"] = is_
    if stubbed:
        out["S"] = out["Sw"] = entry
    return out


SHAPES = (
    Shape("S1", "register poll without write", _all("s1", "s1_t", "s1_u"),
          ({"REG_A.Byte": 1}, {"REG_A.Byte": 0}, {"REG_A.Byte": 3}, {}),
          ("g_o", "g_p", "REG_A.Byte", "REG_A.Bits.F"), frozenset({"Wait"})),
    Shape("S2", "callee reads the flag inside the caller's polled loop body", _all("s2", "s2_t", is_="s2_is", stubbed=True),
          ({"REG_A.Byte": 1}, {"REG_A.Byte": 0}), ("g_n", "g_p", "REG_A.Byte"), frozenset({"Rd"}),
          stubs={"Rd() return": 1}),
    Shape("S3", "write through a pointer parameter", _all("s3", "s3_t", "s3_u", "s3_is", stubbed=True),
          ({},), ("g_o", "g_q", "g_p"), frozenset({"Put"}), stubs={"Put() p[0]": 4}),
    Shape("S4", "never-returning callee", _all("s4", "s4_t"), ({},), ("g_o", "g_p"), frozenset({"Halt"})),
    Shape("S5", "undefined behaviour on one callee path", _all("s5", "s5_t", is_="s5_is", stubbed=True),
          ({"g_d": 0}, {"g_d": 5}, {}), ("g_o", "g_p"), frozenset({"Div"}), stubs={"Div() return": 6}),
    Shape("S6", "undefined behaviour on every callee path", _all("s6", "s6_t"),
          ({"g_d": 0}, {"g_d": 5}, {}), ("g_o", "g_p"), frozenset({"Bad"})),
    Shape("S7", "return of a global", _all("s7", "s7_t", "s7_u", "s7_is", stubbed=True),
          ({"g_k": 4, "g_q": 3},), ("g_o", "g_p", "g_q"), frozenset({"GetG"}), stubs={"GetG() return": 6}),
    Shape("S8", "return of a register", _all("s8", "s8_t", is_="s8_is", stubbed=True),
          ({"REG_A.Byte": 5}, {"REG_A.Byte": 1}), ("g_o", "g_p", "REG_A.Byte"), frozenset({"GetR"}),
          stubs={"GetR() return": 6}),
    Shape("S9", "recursion", _all("s9"), ({"g_k": 2}, {"g_k": 0}), ("g_o", "g_p", "g_q"), frozenset({"Rec"})),
    Shape("S10", "function pointer call", _all("s10", "s10_t"), ({"g_q": 1},), ("g_o", "g_p", "g_q"),
          frozenset({"Seven"})),
    Shape("S11", "writes on some paths only", _all("s11", "s11_t", "s11_u"),
          ({"g_k": 0}, {"g_k": 1}, {}), ("g_o", "g_q", "g_p"), frozenset({"SetSome"})),
    Shape("S12a", "call in &&", _all("s12a", "s12a_t", is_="s12a_is", stubbed=True),
          ({"g_k": 0}, {"g_k": 2}, {"g_k": 3}, {}), ("g_o", "g_n", "g_p"), frozenset({"Chk"}),
          stubs={"Chk() return": 1}),
    Shape("S12b", "call in ?:", _all("s12b", "s12b_t", is_="s12b_is", stubbed=True),
          ({"g_k": 0}, {"g_k": 2}, {"g_k": 3}, {}), ("g_o", "g_n", "g_p"), frozenset({"Chk"}),
          stubs={"Chk() return": 1}),
    Shape("S12c", "call in a loop condition", _all("s12c", "s12c_t", is_="s12c_is", stubbed=True),
          ({},), ("g_o", "g_n", "g_p"), frozenset({"Chk"}), stubs={"Chk() return": 1}),
    Shape("S13", "a call beside a register read in one expression", _all("s13", ("s13_t1", "s13_t2")),
          ({"REG_A.Byte": 1}, {"REG_A.Byte": 0}), ("g_o", "g_p"), frozenset({"Wait"})),
    Shape("S14", "twin definitions in two builds (R89)", _all("s14", "s14_t"), ({},), ("g_v", "g_p"),
          frozenset({"drv"}), project="twins"),
    Shape("S15", "(Inc()) + 1U cast-call parse inside a callee", _all("s15", "s15_t"), ({},), ("g_o", "g_n", "g_p"),
          frozenset({"CastUse", "Inc"})),
    Shape("S16", "hypothetical-probe leak (lk1)", _all("s16"), ({"REG_A.Byte": 1}, {"REG_A.Byte": 0}),
          ("g_o", "g_p"), frozenset({"Helper", "Rec2"})),
)
SHAPE_BY_ID = {s.sid: s for s in SHAPES}
# (G8) a stubbed call beside an interpreted one: J3 (`CalleeSummary.effectful` of the callee's closure —
#   `_Interp.mark_unordered_calls`) reads the stubbed callee's closure, not the stub
G8_SHAPE = Shape("G8", "stubbed effectful call beside an interpreted one", {"Sw": "g8", "IS": "g8_is"},
                 ({"g_k": 4},), ("g_o", "g_p"), frozenset({"Chk", "GetG"}), stubs={"Chk() return": 1})


# ── running a mode ──────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Cell:
    kind: str                # "value" | "unknown" | "refused"
    value: int | None = None
    reason: str = ""
    cls: str = ""            # refused: program_ub | program_termination | budget | model


_PROGRAM_UB = ("undefined_behavior:", "unsequenced_side_effects")
_PROGRAM_TERMINATION = ("non_terminating_loop", "constant_condition_loop_unfinished")
_BUDGET = ("execution_budget", "loop_iteration_budget", "path_budget", "polling_loop_exit_search_budget")


def refusal_class(reason: str) -> str:
    """The class of a record's refusal by its reason's prefix (the design's ``REFUSAL_CLASS``)."""
    if reason.startswith(_PROGRAM_UB):
        return "program_ub"
    if reason.startswith(_PROGRAM_TERMINATION):
        return "program_termination"
    if reason.startswith(_BUDGET):
        return "budget"
    return "model"


def _cells(record, outs):
    if record.get("status") != "supported":
        reason = str(record.get("reason") or "")
        return {o: Cell("refused", reason=reason, cls=refusal_class(reason)) for o in outs}
    out = {}
    for o in outs:
        got = (record.get("outputs") or {}).get(o) or {}
        out[o] = Cell("value", value=got["value"]) if "value" in got else Cell("unknown", reason=str(got.get("reason")))
    return out


def _provider(project, mode, shape):
    if mode in ("I", "T", "IS", "Sw"):
        return CalleeProvider(project.context, project.files, project.scopes, cpc.shared_parser())
    if mode == "Ew":
        return ForcedEffectsProvider(project.context, project.files, project.scopes, cpc.shared_parser(),
                                     refuse=shape.callees)
    return None   # E0 · U · S: no world (SUTS style)


def run_mode(project, shape, mode, entry=None):
    """``[(cells, record)]`` per row of ``shape`` in ``mode`` — one `evaluate_outputs` call (the rows share the
    function's kept answers, as a generation's do)."""
    entry = entry or shape.entries[mode]
    rows = [dict(r, **shape.stubs) if mode in ("S", "Sw") else dict(r) for r in shape.rows]
    path = project.entry_path
    unit = {"name": entry, "source_text": project.files[path], "source_path": path, "source_text_complete": True,
            "project_scope": project.scopes[path]}
    provider = _provider(project, mode, shape)
    if provider is not None:
        unit["callee_provider"] = provider
    records = evaluate_outputs(unit, rows, [list(shape.outs)] * len(rows))
    return [(_cells(r, shape.outs), r) for r in records]


def _join_orders(per_order):
    """T of a shape whose callee runs indeterminately sequenced (C11 6.5.2.2p10): one cell per allowed order, joined —
    a value only where every order gives it."""
    joined = []
    for rows in zip(*per_order, strict=True):
        cells, records = {}, [rec for _c, rec in rows]
        for o in rows[0][0]:
            got = [c[o] for c, _r in rows]
            refused = next((c for c in got if c.kind == "refused"), None)
            if refused is not None:
                cells[o] = refused
            elif all(c.kind == "value" for c in got) and len({c.value for c in got}) == 1:
                cells[o] = got[0]
            else:
                cells[o] = Cell("unknown", reason="order_dependent:" + "|".join(str(c.value) for c in got))
        joined.append((cells, records[0]))
    return joined


def run_shape(projects, shape):
    """``{mode: [(cells, record)] per row}`` for every mode the shape has."""
    project = projects[shape.project]
    out = {}
    for mode, entry in shape.entries.items():
        if isinstance(entry, tuple):
            out[mode] = _join_orders([run_mode(project, shape, mode, e) for e in entry])
        else:
            out[mode] = run_mode(project, shape, mode)
    return out


# ── the verdict ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _discloses(record, cls, callees, strong_reason):
    """Does the weak record disclose the assumption the strong mode's refusal is about — for one of ``callees``?"""
    texts = [a for a in record.get("assumptions") or () if isinstance(a, str)]
    if cls == "program_termination":
        return any(("terminat" in a or "never return" in a) and any(c in a for c in callees) for a in texts)
    if cls == "program_ub":
        kind = strong_reason.split(":", 2)[1] if strong_reason.startswith("undefined_behavior:") else strong_reason
        if any(kind and kind in str(k) for k in record.get("possible_undefined_behavior") or ()):
            return True
        return any("undefined" in a and any(c in a for c in callees) for a in texts)
    return False


def verdict(weak: Cell, strong: Cell, weak_record=None, callees=frozenset()) -> str:
    """ok · ok_disclosed · inconclusive · model_gap · CONTRADICTION · INVENTION (see the module doc)."""
    if strong.kind == "refused" and strong.cls == "budget":
        return "inconclusive"
    if weak.kind != "value":
        return "ok"
    if strong.kind == "value":
        return "ok" if weak.value == strong.value else "CONTRADICTION"
    if strong.kind == "refused" and strong.cls in ("program_ub", "program_termination"):
        return "ok_disclosed" if _discloses(weak_record or {}, strong.cls, callees, strong.reason) else "INVENTION"
    if strong.kind == "refused":
        return "model_gap"
    return "INVENTION"


def verdicts(shape, results, pairs=PAIRS):
    """``[(weak, strong, row, cell, verdict, weak cell, strong cell)]`` over the pairs both modes of which ran."""
    out = []
    for weak, strong in pairs:
        if weak not in results or strong not in results:
            continue
        for i, ((wc, wr), (sc, _sr)) in enumerate(zip(results[weak], results[strong], strict=True)):
            for o in shape.outs:
                out.append((weak, strong, i, o, verdict(wc[o], sc[o], wr, shape.callees), wc[o], sc[o]))
    return out


_BAD = ("CONTRADICTION", "INVENTION")

# (shape, weak, strong) → the design gap the pair reproduces: excluded from the shape tests, tested in its own xfail
KNOWN_GAPS = {
    ("S4", "Ew", "I"): "G5", ("S4", "E0", "I"): "G5", ("S4", "Ew", "T"): "G5", ("S4", "E0", "T"): "G5",
    ("S5", "Ew", "I"): "G6", ("S5", "E0", "I"): "G6", ("S5", "Ew", "T"): "G6", ("S5", "E0", "T"): "G6",
    ("S6", "Ew", "I"): "G6", ("S6", "E0", "I"): "G6", ("S6", "Ew", "T"): "G6", ("S6", "E0", "T"): "G6",
    ("S13", "I", "T"): "G4", ("S13", "Ew", "T"): "G4", ("S13", "E0", "T"): "G4",
    # (the E modes against I: equal today — both read left to right; whichever F6's sequencing rule refuses first)
    ("S13", "Ew", "I"): "G4", ("S13", "E0", "I"): "G4",
}
# (shape, weak, strong, cell) → why a weak value beside a strong model refusal is no wrong value. Accepted only where T
#   (the same code with the callee pasted in) gives the weak mode's value for that cell (`_bad`).
MODEL_GAPS: dict[tuple, str] = {
    ("S15", "Ew", "I", "g_p"): "G11: I refuses the run for `(Inc()) + 1U` in the callee (cast_parse_of_parenthesized_"
                               "expression in callee_contract.REFUSING_MODEL_IN_CALLEE); the callee's closure holds the hidden call — "
                               "g_p = 7",
    ("S15", "E0", "I", "g_p"): "G11: as for Ew",
}

_CACHE: dict[str, dict] = {}


@pytest.fixture(scope="module")
def shape_results(projects):
    """Each shape's modes run once for the module (lazily: a test of one shape runs that shape only)."""
    _CACHE.clear()

    def get(sid):
        if sid not in _CACHE:
            shape = SHAPE_BY_ID.get(sid) or (G8_SHAPE if sid == "G8" else None)
            _CACHE[sid] = run_shape(projects, shape)
        return _CACHE[sid]
    yield get
    _CACHE.clear()


def _model_gap_accepted(results, row, cell, wc):
    """A listed model gap stands only where T (the callee pasted in) gives the weak mode's value for the cell."""
    t = results.get("T")
    return t is None or (t[row][0][cell].kind == "value" and t[row][0][cell].value == wc.value)


def _bad(shape, results, gaps=None):
    """The CONTRADICTION / INVENTION / unaccepted model_gap cells, outside (``gaps`` None) or inside the given gaps."""
    bad = []
    for weak, strong, i, o, v, wc, sc in verdicts(shape, results):
        gap = KNOWN_GAPS.get((shape.sid, weak, strong))
        if (gaps is None and gap is not None) or (gaps is not None and gap not in gaps):
            continue
        if v in _BAD or (v == "model_gap" and not ((shape.sid, weak, strong, o) in MODEL_GAPS
                                                    and _model_gap_accepted(results, i, o, wc))):
            bad.append((weak, strong, i, o, v, wc, sc))
    return bad


# ── the shapes ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sid", [s.sid for s in SHAPES])
def test_a_weaker_mode_never_contradicts_nor_invents(sid, shape_results):
    shape = SHAPE_BY_ID[sid]
    results = shape_results(sid)
    assert not _bad(shape, results), _bad(shape, results)


def _value(results, mode, row, cell):
    c = results[mode][row][0][cell]
    return c.value if c.kind == "value" else c


def test_s4_a_never_returning_callee_is_refused_when_interpreted(shape_results):
    results = shape_results("S4")
    for mode in ("T", "I"):
        cells, record = results[mode][0]
        assert record["status"] == "unsupported" and record["reason"] == "non_terminating_loop", (mode, record["reason"])


def test_s6_undefined_behaviour_on_every_callee_path_refuses_the_interpreted_run(shape_results):
    results = shape_results("S6")
    for mode in ("T", "I"):
        for _cells, record in results[mode]:
            assert record["status"] == "unsupported" and record["reason"].startswith("undefined_behavior:division_by_zero")


def test_s5_undefined_behaviour_on_the_only_path_refuses_and_elsewhere_the_callee_value_stands(shape_results):
    results = shape_results("S5")
    assert results["I"][0][1]["reason"].startswith("undefined_behavior:division_by_zero")   # g_d = 0: the only path
    assert _value(results, "I", 1, "g_o") == 2 == _value(results, "T", 1, "g_o")            # g_d = 5
    assert _value(results, "S", 0, "g_o") == 6 == _value(results, "IS", 0, "g_o")           # the stub never divides


def test_s7_the_callee_returns_the_global_and_the_stub_its_row_value(shape_results):
    results = shape_results("S7")
    assert _value(results, "I", 0, "g_o") == 4 == _value(results, "T", 0, "g_o")
    assert _value(results, "S", 0, "g_o") == 6 == _value(results, "IS", 0, "g_o") == _value(results, "Sw", 0, "g_o")
    assert _value(results, "S", 0, "g_q") == 3   # a stub writes no global


def test_s8_the_stub_of_a_register_reader_returns_its_row_value(shape_results):
    results = shape_results("S8")
    for row in (0, 1):
        assert _value(results, "S", row, "g_o") == 6 == _value(results, "Sw", row, "g_o") == _value(results, "IS", row,
                                                                                                    "g_o")


def test_s11_a_callee_writing_on_some_paths(shape_results):
    results = shape_results("S11")
    assert [_value(results, "I", i, "g_o") for i in (0, 1)] == [5, 1] == [_value(results, "T", i, "g_o") for i in (0, 1)]
    assert results["I"][2][0]["g_o"].kind == "unknown" and results["T"][2][0]["g_o"].kind == "unknown"


def test_s12_calls_in_conditions_run_where_the_short_circuit_runs_them(shape_results):
    a, b, c = (shape_results(s) for s in ("S12a", "S12b", "S12c"))
    # g_k = 0: Chk never runs — g_n stays 0; g_k = 3: it runs once
    assert (_value(a, "I", 0, "g_n"), _value(a, "I", 2, "g_n"), _value(a, "I", 2, "g_o")) == (0, 1, 1)
    assert (_value(b, "I", 0, "g_n"), _value(b, "I", 2, "g_o"), _value(b, "I", 1, "g_o")) == (0, 1, 0)
    assert (_value(c, "I", 0, "g_o"), _value(c, "I", 0, "g_n")) == (3, 3)


def test_s14_a_call_links_within_its_own_build(shape_results):
    results = shape_results("S14")
    assert _value(results, "I", 0, "g_v") == 1 == _value(results, "T", 0, "g_v")


def test_s16_a_callee_failing_on_a_hypothetical_flag_value_runs_for_real(shape_results):
    # A hypothetical flag value must leave no trace on the real run: no callee recorded as failed / effects-only by the
    #   search, and a value — when the model gives one — is the program's (5). F6 r5 refuses this loop as
    #   `polling_loop_condition_changes_state` (the condition calls a callee that changes state): honest, so only the
    #   relation is asserted here (a refusal of the model's own is not a value it invented).
    results = shape_results("S16")
    for row in (0, 1):
        cells, record = results["I"][row]
        if cells["g_o"].kind == "value":
            assert cells["g_o"].value == 5, (row, cells)
            assert record["interprocedural"]["failed"] == {} and record["interprocedural"]["effects_only"] == {}
        else:
            assert cells["g_o"].kind == "refused" and cells["g_o"].cls == "model", (row, cells)
            assert "recursion" not in str(record.get("interprocedural", {}).get("failed", {})), (row, record)


def test_every_comparison_compares_values_somewhere(shape_results):
    """The relations are not vacuous: each main pair meets cells where both modes give a value (and agree)."""
    agree = Counter()
    for shape in SHAPES:
        for weak, strong, _i, _o, v, wc, sc in verdicts(shape, shape_results(shape.sid)):
            if v == "ok" and wc.kind == "value" and sc.kind == "value":
                agree[(weak, strong)] += 1
    for pair in (("I", "T"), ("Ew", "T"), ("E0", "T"), ("Ew", "I"), ("E0", "I"), ("U", "I"), ("S", "IS"), ("Sw", "IS")):
        assert agree[pair] >= 3, (pair, agree)


# ── known gaps (`callee_contract_design.md` "Gaps found") ──────────────────────────────────────────────────────────
# A gap that confirms a wrong value (INVENTION / CONTRADICTION) is a SOUNDNESS FINDING: its test is NOT xfailed — it
# stays red until the producer is fixed (G4 by F6's register sequencing rule, G5 / G6 by steps 4b / 4c). Precision gaps
# (the weak mode knows less than it could) are `xfail(strict=True)`.

def _gap_bad(shape_results, sid, gap):
    shape = SHAPE_BY_ID[sid]
    return _bad(shape, shape_results(sid), gaps={gap})


def _finding(gap, bad):
    return f"SOUNDNESS FINDING {gap}: " + "; ".join(
        f"{w} vs {s} row {i} {o}: {v} weak={wc.value if wc.kind == 'value' else wc.kind} "
        f"strong={sc.value if sc.kind == 'value' else sc.reason}" for w, s, i, o, v, wc, sc in bad)


def test_g4_a_call_beside_a_register_read_is_order_dependent(shape_results):
    # `REG_A.Bits.F + (Wait(), 0U)`: the read and Wait's body are indeterminately sequenced (C11 6.5.2.2p10) — read
    #   before Wait, the row's 1; after it, whatever ended the poll. No mode may confirm one order's value.
    bad = _gap_bad(shape_results, "S13", "G4")
    assert not bad, _finding("G4", bad)


def test_g5_effects_only_assumes_termination_without_saying_so(shape_results):
    # `Halt()` is `for (;;) {}`: interpreted (and pasted) the run is refused non_terminating_loop; run as effects only
    #   the caller goes on — no disclosure names the callee whose return it assumed
    bad = _gap_bad(shape_results, "S4", "G5")
    assert not bad, _finding("G5", bad)


@pytest.mark.parametrize("sid", ["S5", "S6"])
def test_g6_effects_only_undefined_behaviour_is_not_disclosed(sid, shape_results):
    # `Div(0)` / `Bad(v)` divide by zero on the run's only path: interpreted the run is refused undefined_behavior; run
    #   as effects only the caller's other outputs keep their values, the UB unanalysed and undisclosed
    bad = _gap_bad(shape_results, sid, "G6")
    assert not bad, _finding("G6", bad)


def test_g5_g6_effects_only_says_what_it_did_not_judge_naming_the_callee(shape_results):
    # (steps 4b / 4c) `Halt` loops for ever: run as effects only the run is refused as interpreted (the same class);
    #   `Wait` polls (its text does not prove it returns) and `Div` may divide by zero: the values stand, each named
    s4, s5, s1 = (shape_results(s) for s in ("S4", "S5", "S1"))
    for mode in ("Ew", "E0"):
        assert s4[mode][0][1]["reason"] == "non_terminating_loop:Halt", (mode, s4[mode][0][1]["reason"])
        record = s5[mode][1][1]   # g_d = 5: Div returns 2 — the call's undefined behaviour is not judged
        assert record["status"] == "supported" and record["callee_ub_unanalysed"] == ["Div"], (mode, record)
        assert "callee_termination_assumed" not in record   # Div has no loop: its return is proven
        record = s1[mode][1][1]
        assert record["callee_termination_assumed"] == ["Wait"] and record["callee_ub_unanalysed"] == ["Wait"], record
    for mode in ("I", "T"):   # interpreted / pasted: nothing left unjudged
        assert all("callee_ub_unanalysed" not in rec and "callee_termination_assumed" not in rec
                   for _c, rec in s5[mode]), mode


@pytest.mark.xfail(strict=True, reason="G8: J3 (`CalleeSummary.effectful` of the closure) reads a stubbed callee's "
                                       "closure — a stub writes nothing, yet the interpreted call beside it is run as "
                                       "effects only (precision)")
def test_g8_a_stub_beside_an_interpreted_call_keeps_it_interpreted(shape_results):
    results = shape_results("G8")
    sw, is_ = results["Sw"][0][0]["g_o"], results["IS"][0][0]["g_o"]
    assert is_.kind == "value" and sw.kind == "value" and sw.value == is_.value, (sw, is_)


@pytest.mark.xfail(strict=True, reason="G11: `cast_parse_of_parenthesized_expression` in `REFUSING_MODEL_IN_CALLEE` "
                                       "refuses the integrated run though cpc `_cast_hidden_call` put the hidden call in "
                                       "the closure — I is less precise than E0 (precision)")
def test_g11_a_cast_parse_inside_a_callee_does_not_refuse_the_integrated_run(shape_results):
    results = shape_results("S15")
    for _cells, record in results["I"]:
        assert record["status"] == "supported", record["reason"]


# ── the guard can fail: mutations it must report ──────────────────────────────────────────────────────────────────

def _fresh_trees(monkeypatch):
    """A new per-text cache: a mutated run must not read answers an unmutated one kept (`_TREES`)."""
    monkeypatch.setattr(cso._TREES, "cache", OrderedDict(), raising=False)


def _bad_verdicts(projects, sid):
    shape = SHAPE_BY_ID[sid]
    return Counter(v for *_x, v, _w, _s in verdicts(shape, run_shape(projects, shape)) if v in _BAD)


def test_mutation_effects_only_keeps_registers_is_reported(projects, monkeypatch):
    # m1: a callee not interpreted no longer makes the registers it may read unknown — the registers consumer's hook
    #   (`callee_contract._consume_registers` → `havoc_volatile_storage`; the interpreted and pasted runs of S1 do not
    #   reach it: their poll havocs by `havoc_base`)
    _fresh_trees(monkeypatch)
    monkeypatch.setattr(cso._Interp, "havoc_volatile_storage", lambda self, *a, **k: None)
    bad = _bad_verdicts(projects, "S1")
    assert bad["INVENTION"] > 0, bad


def test_mutation_a_stub_writing_a_global_is_reported(projects, monkeypatch):
    # m2: the sequence stub writes a global (R38: it writes none)
    _fresh_trees(monkeypatch)
    original = cso._Interp.stubbed_call

    def leaky(self, state, name, info, view, arg_nodes=(), raw=b""):
        state.store["g_q"] = 42
        return original(self, state, name, info, view, arg_nodes, raw)
    monkeypatch.setattr(cso._Interp, "stubbed_call", leaky)
    assert _bad_verdicts(projects, "S7")["CONTRADICTION"] > 0


def test_mutation_a_join_that_picks_the_first_path_is_reported(projects, monkeypatch):
    # m3: the callee's final paths are not joined — the first one stands for all
    _fresh_trees(monkeypatch)
    original = cso._World.join
    monkeypatch.setattr(cso._World, "join", staticmethod(lambda sub, finals, name: original(sub, finals[:1], name)))
    assert sum(_bad_verdicts(projects, "S11").values()) > 0


def test_mutation_effects_only_termination_unsaid_is_reported(projects, monkeypatch):
    # m4 (step 4b off): an effects-only callee returns, said by nobody — `Halt()` (``for (;;) {}``) no longer refuses
    #   the run and is named nowhere: the caller's later values are INVENTIONs against the interpreted run's refusal
    from generators import callee_contract as cc
    _fresh_trees(monkeypatch)
    monkeypatch.setattr(cc, "effects_termination", lambda name, summary: cc.Termination(
        verdict=cc.RETURNS, evidence="", assumed=frozenset()))
    assert _bad_verdicts(projects, "S4")["INVENTION"] > 0


def test_mutation_effects_only_undefined_behaviour_unsaid_is_reported(projects, monkeypatch):
    # m5 (step 4c off): the undefined behaviour an effects-only callee may have is named nowhere — `Div(0)` divides by
    #   zero on the run's only path: g_p = 7 is an INVENTION against the interpreted run's refusal
    from generators import callee_contract as cc
    _fresh_trees(monkeypatch)
    monkeypatch.setattr(cc, "effects_ub_unanalysed", lambda name, summary: frozenset())
    assert _bad_verdicts(projects, "S5")["INVENTION"] > 0


# ── the harness's own verdict table ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("weak, strong, expected", [
    (Cell("value", 1), Cell("value", 1), "ok"),
    (Cell("value", 1), Cell("value", 2), "CONTRADICTION"),
    (Cell("value", 1), Cell("unknown", reason="x"), "INVENTION"),
    (Cell("unknown", reason="x"), Cell("value", 1), "ok"),
    (Cell("refused", reason="r", cls="model"), Cell("value", 1), "ok"),
    (Cell("value", 1), Cell("refused", reason="execution_budget", cls="budget"), "inconclusive"),
    (Cell("value", 1), Cell("refused", reason="non_terminating_loop", cls="program_termination"), "INVENTION"),
    (Cell("value", 1), Cell("refused", reason="undefined_behavior:division_by_zero", cls="program_ub"), "INVENTION"),
    (Cell("value", 1), Cell("refused", reason="polling_loop_body_reads_flag:REG_A", cls="model"), "model_gap"),
])
def test_the_verdict_table(weak, strong, expected):
    assert verdict(weak, strong, {}, frozenset({"F"})) == expected


def test_a_disclosure_must_name_the_callee():
    strong = Cell("refused", reason="non_terminating_loop", cls="program_termination")
    blanket = {"assumptions": ["reachability and termination of callees are not proven"]}
    named = {"assumptions": ["callee Halt assumed to terminate (effects only)"]}
    assert verdict(Cell("value", 1), strong, blanket, frozenset({"Halt"})) == "INVENTION"
    assert verdict(Cell("value", 1), strong, named, frozenset({"Halt"})) == "ok_disclosed"
    ub = Cell("refused", reason="undefined_behavior:division_by_zero", cls="program_ub")
    assert verdict(Cell("value", 1), ub, {"possible_undefined_behavior": ["division_by_zero_on_unknown_branch"]},
                   frozenset({"Div"})) == "ok_disclosed"


@pytest.mark.parametrize("reason, cls", [
    ("undefined_behavior:division_by_zero", "program_ub"), ("unsequenced_side_effects", "program_ub"),
    ("non_terminating_loop", "program_termination"), ("constant_condition_loop_unfinished", "program_termination"),
    ("execution_budget", "budget"), ("execution_budget:polling_way_out_search", "budget"),
    ("loop_iteration_budget", "budget"), ("polling_loop_exit_search_budget:65536", "budget"),
    ("polling_loop_body_reads_flag:REG_A", "model"), ("cast_parse_of_parenthesized_expression", "model"),
])
def test_refusal_classes(reason, cls):
    assert refusal_class(reason) == cls
