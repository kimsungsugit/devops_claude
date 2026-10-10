"""(R67) A cast to a typedef name before a unary minus, and const tables the program holds.

``(S16)-1800`` — the grammar does not know ``S16`` names a type and parses a subtraction ``S16 - 1800``; every reader read
an undeclared identifier. KJPDS02_PV writes 23 (motor-control limits ``s16t_Angle < ( S16 )-1800``, clamps, the macro
``SLOPE_MIN_DEG ((S16)-20)``, the lookup tables ``{ (S16)-4000, … }``). The four readers — the constant evaluator
(macros, const initializers), the source oracle, the MC/DC decision model and the compared-constant walk — now read it as
the cast it is when the name is a type there (`c_project_context.paren_cast_unary` finds the shape; each reader judges
the name like ``(T)(x)``).

A const table whose values a unit does not hold (audit #45): the reader asked the test for an initial value
(`initial_value_not_in_inputs:tab[0]`) — a value a test cannot set (ROM) and a false 'read the inputs lack' finding. Index
designators are read now, an extern table takes its one definition's values, and what is still not held says why. A
design document that lists a const table as an input no longer makes the rows set it.

Values claimed here are checked against the program compiled with gcc where a host compiler is present.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from generators import c_project_context as cpc
from generators.boundary_rows import compared_constants
from generators.c_source_oracle import evaluate_outputs
from generators.mcdc_design import build_mcdc_design, evaluate_decision

ROOT = os.path.join(os.sep, "virt_r67")
H = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\ntypedef signed long S32;\n"
#: the host compiles the same program with the target's widths (a 16-bit ``int`` is ``short`` on the host) — every value
#   compared below fits and converts the same way at either width of ``int``
H_HOST = "typedef unsigned char U8;\ntypedef unsigned short U16;\ntypedef signed short S16;\ntypedef signed long S32;\n"
_GCC = shutil.which("gcc") or (r"C:\msys64\mingw64\bin\gcc.exe" if os.path.exists(r"C:\msys64\mingw64\bin\gcc.exe")
                               else None)


def _ctx(files, roots=None):
    return cpc.build_project_context({os.path.join(ROOT, k): v for k, v in {"t.h": H, **files}.items()},
                                     roots=roots or [ROOT])


def _scope(files, unit="a.c", roots=None):
    path = os.path.join(ROOT, unit)
    return cpc.build_scopes(_ctx(files, roots), [path])[path]


def _unit(files, name, unit="a.c", inputs=None, roots=None):
    path = os.path.join(ROOT, unit)
    scope = _scope(files, unit, roots)
    u = {"name": name, "source_text": cpc.apply_body_projection(scope, files[unit]), "source_path": path,
         "source_text_complete": True, "project_scope": scope}
    if inputs is not None:
        u["input_vars"] = list(inputs)
    return u


def _run(files, name, inputs, outs, unit="a.c"):
    (r,) = evaluate_outputs(_unit(files, name, unit), [inputs], [outs])
    return {o: r["outputs"].get(o, {}).get("value", r["outputs"].get(o, {}).get("reason", r.get("reason"))) for o in outs}


def _gcc(tmp_path, files, main_body):
    if _GCC is None:
        return None
    for k, v in {"t.h": H_HOST, **files}.items():
        (tmp_path / k).write_text(v, encoding="utf-8")
    (tmp_path / "main.c").write_text('#include <stdio.h>\n#include "t.h"\n' + main_body, encoding="utf-8")
    srcs = [str(tmp_path / k) for k in files if k.endswith(".c")] + [str(tmp_path / "main.c")]
    exe = str(tmp_path / "prog.exe")
    subprocess.run([_GCC, "-O0", "-w", "-o", exe, *srcs], check=True, capture_output=True, timeout=120)
    return subprocess.run([exe], check=True, capture_output=True, text=True, timeout=60).stdout.split()


# ── the shape ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr, want", [
    ("(S16)-1800", ("S16", "-", "number_literal")),
    ("( S16 )-1800", ("S16", "-", "number_literal")),
    ("(S16)+a", ("S16", "+", "identifier")),
    ("(S16)-f(x)", ("S16", "-", "call_expression")),
    ("(S16)-a[1]", ("S16", "-", "subscript_expression")),
    ("(S16)-a = b", ("S16", "-", None)),        # the grammar grouped the right side under the misparse
    ("(S16)*p", None),                          # a dereference: not this reader's shape (stays unknown)
    ("(S16)&x", None),
    ("a - b", None),
    ("(a + b) - c", None),
])
def test_paren_cast_unary_shape(expr, want):
    parser = cpc.shared_parser()
    raw = ("void f(void){ q = " + expr + "; }").encode()
    root = parser.parse(raw).root_node
    shapes = []
    stack = [root]
    while stack:
        n = stack.pop()
        s = cpc.paren_cast_unary(n, raw)
        if s is not None:
            shapes.append((s[0], s[1], None if s[2] is None else s[2].type))
        stack.extend(n.named_children)
    assert shapes == ([want] if want else [])


# ── the constant evaluator: macros, const objects, const tables ────────────────────────────────────

CONSTS = ('#include "t.h"\n#define K_NEG ((S16)-90)\n#define K_SP (( S16 )-90)\n#define K_U ((U16)-1)\n'
          "#define K_PLUS ((S16)+7)\nstatic const S16 k_lim = (S16)-50;\n"
          "static const S16 tab[3] = { (S16)-4000, (S16)-700, (S16)0 };\nvoid f(void) { }\n")


def test_the_constant_evaluator_reads_the_cast():
    scope = _scope({"a.c": CONSTS})
    got = {n: scope["constants"][n]["value"] for n in ("K_NEG", "K_SP", "K_U", "K_PLUS")}
    assert got == {"K_NEG": -90, "K_SP": -90, "K_U": 65535, "K_PLUS": 7}      # (U16)-1 wraps on a 16-bit int target
    assert scope["arrays"]["tab"]["values"] == [-4000, -700, 0]
    assert scope["constants"]["k_lim"]["value"] == -50


def test_a_name_that_is_a_macro_or_object_stays_a_subtraction():
    text = ('#include "t.h"\n#define W 10\nstatic const S16 g_c = 3;\n#define A ((W)-1)\n#define B ((g_c)-1)\n'
            "void f(void) { }\n")
    scope = _scope({"a.c": text})
    assert scope["constants"]["A"]["value"] == 9          # W is a macro: (W)-1 is a subtraction
    assert "B" not in scope["constants"]                  # g_c is an object, not a type: no constant, no cast


# ── the oracle ─────────────────────────────────────────────────────────────────────────────────────

ORACLE = {"a.c": '#include "t.h"\n#define SLOPE_MIN ((S16)-20)\nS16 g_out;\nS16 g_clamp;\nU16 g_u;\n'
                 "void f(S16 a)\n{\n    if (a < ( S16 )-1800) { g_out = 1; } else { g_out = 2; }\n"
                 "    g_clamp = (a < SLOPE_MIN) ? (S16)-20 : a;\n    g_u = (U16)-1;\n}\n"}


@pytest.mark.parametrize("a", [-1801, -1800, -21, -20, 5])
def test_the_oracle_reads_the_cast_and_gcc_agrees(tmp_path, a):
    got = _run(ORACLE, "f", {"a": a}, ["g_out", "g_clamp", "g_u"])
    assert got == {"g_out": 1 if a < -1800 else 2, "g_clamp": -20 if a < -20 else a, "g_u": 65535}
    out = _gcc(tmp_path, ORACLE, f'extern S16 g_out, g_clamp; extern U16 g_u; void f(S16 a);\n'
                                 f'int main(void) {{ f({a}); printf("%d %d %u", g_out, g_clamp, (unsigned)g_u); return 0; }}\n')
    if out is not None:
        assert out == [str(got["g_out"]), str(got["g_clamp"]), str(got["g_u"])]


def test_a_second_cast_the_grammar_split_off_stays_unknown():
    """``(U16)-1 + (U16)+2`` parses as ``((U16) - 1 + (U16)) + 2``: the second cast's operand is no subtree — not
    regrouped by guess, and the reason names the split cast rather than an undeclared identifier."""
    text = '#include "t.h"\nU16 g_u;\nvoid f(void)\n{\n    g_u = (U16)-1 + (U16)+2;\n}\n'
    assert _run({"a.c": text}, "f", {}, ["g_u"]) == {"g_u": "cast_operand_split_by_grammar:U16"}


def test_a_parameter_named_like_the_typedef_hides_it():
    """C11 6.2.1p4: ``S16`` the parameter hides ``S16`` the typedef — ``(S16)-1`` is ``S16 - 1``."""
    text = '#include "t.h"\nS16 g_out;\nvoid f(U16 S16)\n{\n    g_out = (S16)-1;\n}\n'
    assert _run({"a.c": text}, "f", {"S16": 5}, ["g_out"]) == {"g_out": 4}


def test_a_regrouped_right_side_is_refused_not_guessed():
    text = '#include "t.h"\nS16 g_out;\nS16 b;\nvoid f(S16 a)\n{\n    g_out = (S16)-a = b;\n}\n'
    got = _run({"a.c": text}, "f", {"a": 1, "b": 2}, ["g_out"])
    assert "cast_operand_grouping_unread:S16" in str(got["g_out"])


# ── MC/DC and the compared constants ─────────────────────────────────────────────────────────────

MCDC = {"a.c": '#include "t.h"\nS16 h(S16 a, S16 b)\n{\n    if ((a < (S16)-1800) && (b > ( S16 )-5))\n    {\n'
               "        return 1;\n    }\n    return 0;\n}\n"}


def test_mcdc_designs_the_pair_across_the_cast_constant():
    rep = build_mcdc_design(_unit(MCDC, "h", inputs=["a", "b"]))
    (d,) = rep["decisions"]
    assert d["status"] == "designed" and d["reason"] == "unique_cause_pairs_found"
    assert [c["expression"] for c in d["conditions"]] == ["a < (S16)-1800", "b > ( S16 )-5"]
    assert rep["types"]["S16"]["bits"] == 16
    # finalize re-evaluates every pair from the report alone (no scope): the recorded type reads the same cast
    for p in d["pairs"]:
        for side in ("a", "b"):
            inputs = p[f"inputs_{side}"] if f"inputs_{side}" in p else p[side]
            truth = evaluate_decision(d["expression"], inputs, rep["domains"], rep.get("constants"),
                                      (rep.get("target") or {}).get("widths"), rep.get("types"))
            assert truth["decision"] == ((inputs["a"] < -1800) and (inputs["b"] > -5))


def test_the_compared_constant_walk_reads_the_cast():
    unit = _unit(MCDC, "h", inputs=["a", "b"])
    got = compared_constants(unit, ["a", "b"])
    assert {k: sorted(v) for k, v in got.items()} == {"a": [-1800], "b": [-5]}


# ── const tables ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("init, length, want", [
    ("{ [1] = 5U }", "3", [0, 5, 0]),
    ("{ 1U, [3] = 4U, 5U }", "6", [1, 0, 0, 4, 5, 0]),      # the next item continues after the designator
    ("{ [2] = 1U, [0] = 7U, 8U }", "3", [7, 8, 1]),         # (C11 6.7.9p17)
    ("{ [1] = 1U, [1] = 2U }", "2", [0, 2]),                # a later initializer of the same element overrides it
    ("{ [4] = 9U }", "", [0, 0, 0, 0, 9]),                  # no declared length: the largest index sets it
])
def test_index_designators_are_read(init, length, want, tmp_path):
    text = f'#include "t.h"\nstatic const U8 tab[{length}] = {init};\nU8 g_o;\nvoid f(U8 i) {{ g_o = tab[i]; }}\n'
    scope = _scope({"a.c": text})
    assert scope["arrays"]["tab"]["values"] == want
    out = _gcc(tmp_path, {"a.c": text}, "extern U8 g_o; void f(U8 i);\nint main(void) { int i; for (i = 0; i < "
               f"{len(want)}; i++) {{ f((U8)i); printf(\"%u \", (unsigned)g_o); }} return 0; }}\n")
    if out is not None:
        assert [int(x) for x in out] == want


@pytest.mark.parametrize("init, why", [
    ("{ {1U, 2U}, {3U, 4U} }", "nested_initializer_list"),
    ("{ 1U, X_UNKNOWN }", "element_unresolved:identifier_undeclared"),
    ("{ [5] = 1U }", "initializer_past_length"),
])
def test_what_is_not_read_says_why(init, why):
    text = f'#include "t.h"\nstatic const U8 tab[3] = {init};\nvoid f(void) {{ }}\n'
    a = _scope({"a.c": text})["arrays"]["tab"]
    assert a["values"] is None and a["values_unread"] == why


def test_an_unread_const_table_is_no_input_the_test_lacks():
    """Audit #45: the oracle used to answer `initial_value_not_in_inputs:tab[0]` — R19 then asked for the element as an
    input and the source findings reported a read the inputs lack. A const table is the program's own value."""
    text = ('#include "t.h"\nstatic const U8 tab[3] = { 1U, X_UNKNOWN, 2U };\nU8 g_o;\nvoid f(U8 i) { g_o = tab[i]; }\n')
    got = _run({"a.c": text}, "f", {"i": 0}, ["g_o"])
    assert got["g_o"] == "const_values_unread:tab:element_unresolved:identifier_undeclared"


LINKED = {
    "cfg.h": '#include "t.h"\nextern const U8 cfg_tab[];\n',
    "cfg.c": '#include "cfg.h"\nconst U8 cfg_tab[4] = { 3U, (U8)-1, 7U };\n',
    "a.c": '#include "cfg.h"\nU8 g_o;\nvoid f(U8 i) { g_o = cfg_tab[i]; }\n',
}


def test_an_extern_table_takes_its_one_definitions_values(tmp_path):
    a = _scope(LINKED)["arrays"]["cfg_tab"]
    assert a["values"] == [3, 255, 7, 0] and a["length"] == 4 and a["values_source"].endswith("cfg.c")
    assert [_run(LINKED, "f", {"i": i}, ["g_o"])["g_o"] for i in range(4)] == [3, 255, 7, 0]
    out = _gcc(tmp_path, LINKED, "extern U8 g_o; void f(U8 i);\nint main(void) { int i; for (i = 0; i < 4; i++) "
                                 "{ f((U8)i); printf(\"%u \", (unsigned)g_o); } return 0; }\n")
    if out is not None:
        assert [int(x) for x in out] == [3, 255, 7, 0]


def test_a_definition_in_another_build_is_not_linked():
    """APP and BOOT are separate builds: the BOOT tree's definition is not the APP unit's table."""
    files = {"app/t.h": H, "boot/t.h": H, "app/cfg.h": '#include "t.h"\nextern const U8 cfg_tab[];\n',
             "app/a.c": '#include "cfg.h"\nU8 g_o;\nvoid f(U8 i) { g_o = cfg_tab[i]; }\n',
             "boot/cfg.c": '#include "t.h"\nconst U8 cfg_tab[2] = { 1U, 2U };\n'}
    a = _scope(files, unit="app/a.c", roots=[os.path.join(ROOT, "app"), os.path.join(ROOT, "boot")])["arrays"]["cfg_tab"]
    assert a["values"] is None and a["values_unread"] == "no_initializer_in_unit"


@pytest.mark.parametrize("definitions, why", [
    ({"cfg.c": '#include "cfg.h"\nconst U8 cfg_tab[2] = { 1U, 2U };\n',
      "cfg2.c": '#include "cfg.h"\nconst U8 cfg_tab[2] = { 3U, 4U };\n'}, "defined_in_several_units"),
    ({"cfg.c": '#include "t.h"\nconst U16 cfg_tab[2] = { 1U, 2U };\n'}, "linked_definition_disagrees"),
    ({"cfg.c": '#include "cfg.h"\nconst U8 cfg_tab[2] = { 1U, X_UNKNOWN };\n'},
     "linked_definition_unread:element_unresolved:identifier_undeclared"),
])
def test_a_link_that_cannot_be_made_says_why(definitions, why):
    files = {"cfg.h": LINKED["cfg.h"], "a.c": LINKED["a.c"], **definitions}
    a = _scope(files)["arrays"]["cfg_tab"]
    assert a["values"] is None and a["values_unread"] == why


# ── SUTS: a const object the design lists as an input ───────────────────────────────────────────

def test_a_design_listed_const_input_is_not_set_by_any_row():
    from generators import suts as gsuts
    from report_gen.generation_disclosures import build_disclosures

    fd = {"F1": {"name": "f", "prototype": "void f(U8 u8t_Temp)", "inputs": ["U8 u8t_Temp"], "outputs": [],
                 "globals_static": ["[IN] u8s_ShiftBitLut (size: 9) (idx: u8t_Temp)", "[OUT] g_o"]},
          "F2": {"name": "g", "prototype": "void g(U8 u8s_ShiftBitLut)", "inputs": ["U8 u8s_ShiftBitLut"], "outputs": []}}
    gim = {"u8s_ShiftBitLut": {"type": "const U8", "array": "[9]"}, "g_o": {"type": "U8"}}
    io = {"by_name": {"f": {"inputs": ["u8s_ShiftBitLut", "u8t_Temp"], "outputs": ["g_o"]},
                      "g": {"inputs": ["u8s_ShiftBitLut"], "outputs": []}}}
    units = {u["name"]: u for u in gsuts.collect_unit_functions(fd, gim, sds_map={}, uds_io_map=io)}
    assert units["f"]["uds_const_inputs"] == ["u8s_ShiftBitLut"]
    assert not any(v.startswith("u8s_ShiftBitLut") for v in units["f"]["input_vars"])
    assert "u8t_Temp" in units["f"]["input_vars"]
    # a parameter of that name is the function's own input, not the const global
    assert units["g"]["uds_const_inputs"] == []
    assert any(v.startswith("u8s_ShiftBitLut") for v in units["g"]["input_vars"])
    q = gsuts.summarize_uds_const_inputs(list(units.values()))
    assert q == {"units": 1, "names": 1, "samples": ["f: u8s_ShiftBitLut"]}
    item = next(i for i in build_disclosures("suts", {"uds_const_inputs": q}) if i["key"] == "suts_uds_const_inputs")
    assert "f: u8s_ShiftBitLut" in item["note"] and item["value"] == "unit 1 · 이름 1"
    assert not [i for i in build_disclosures("suts", {"uds_const_inputs": {"units": 0, "names": 0, "samples": []}})
                if i["key"] == "suts_uds_const_inputs"]


@pytest.mark.parametrize("decl, const", [
    ("const U8", True), ("U8 const", True), ("U8 * const", True), ("const U8 * const", True),
    ("const U8 *", False),      # the pointer is the object a test sets; const belongs to what it points to
    ("const U8 * *", False), ("U8", False), ("", False),
])
def test_the_object_itself_is_const(decl, const):
    from generators.suts import _object_is_const
    assert _object_is_const("x", {"x": {"type": decl}}) is const


def test_a_design_listed_pointer_to_const_stays_an_input():
    """Only the const *object* leaves the rows — a pointer to const data is set by the test."""
    from generators import suts as gsuts

    fd = {"F1": {"name": "f", "prototype": "void f(void)", "inputs": [], "outputs": [],
                 "globals_global": ["[IN] p_data", "[IN] k_tab", "[OUT] g_o"]}}
    gim = {"p_data": {"type": "const U8 *"}, "k_tab": {"type": "const U8", "array": "[2]"}, "g_o": {"type": "U8"}}
    io = {"by_name": {"f": {"inputs": ["p_data", "k_tab"], "outputs": ["g_o"]}}}
    (u,) = gsuts.collect_unit_functions(fd, gim, sds_map={}, uds_io_map=io)
    assert u["uds_const_inputs"] == ["k_tab"]
    assert "p_data" in u["input_vars"] and not any(v.startswith("k_tab") for v in u["input_vars"])


# ── review round 1 ───────────────────────────────────────────────────────────────────────────────

def test_a_static_tentative_table_is_zero_not_another_units_definition(tmp_path):
    """(review W-1) ``static const U8 cfg_tab[3];`` has internal linkage: zero at the end of its unit (C11 6.9.2p2) — the
    other unit's ``cfg_tab`` is a different object."""
    files = {"a.c": '#include "t.h"\nstatic const U8 cfg_tab[3];\nU8 g_o;\nvoid f(U8 i) { g_o = cfg_tab[i]; }\n',
             "cfg.c": '#include "t.h"\nconst U8 cfg_tab[3] = { 7U, 8U, 9U };\n'}
    a = _scope(files)["arrays"]["cfg_tab"]
    assert a["values"] == [0, 0, 0] and a["values_source"] == "tentative_definition"
    assert [_run(files, "f", {"i": i}, ["g_o"])["g_o"] for i in range(3)] == [0, 0, 0]
    out = _gcc(tmp_path, files, "extern U8 g_o; void f(U8 i);\nint main(void) { int i; for (i = 0; i < 3; i++) "
                                "{ f((U8)i); printf(\"%u \", (unsigned)g_o); } return 0; }\n")
    if out is not None:
        assert [int(x) for x in out] == [0, 0, 0]


def test_a_static_tentative_scalar_is_zero_and_only_declarations_link(tmp_path):
    """(review W-1) the scalar linkage had the same hole: ``static const U8 k_lim;`` is 0, and a unit's own tentative
    definition (``const U8 k_two;`` — external, no initializer) does not take another unit's value either."""
    files = {"a.c": '#include "t.h"\nstatic const U8 k_lim;\nconst U8 k_two;\nU8 g_o;\nU8 g_p;\n'
                    "void f(void) { g_o = k_lim; g_p = k_two; }\n",
             "cfg.c": '#include "t.h"\nconst U8 k_lim = 5U;\n'}
    scope = _scope(files)
    assert scope["constants"]["k_lim"]["value"] == 0
    assert "k_two" not in scope["constants"]
    got = _run(files, "f", {}, ["g_o", "g_p"])
    assert got["g_o"] == 0 and got["g_p"] != 5


def test_mcdc_refuses_a_cast_to_an_enumeration_type():
    """(review W-2) ``(ETYPE)-1`` is UINT_MAX when the implementation picks unsigned for the enumeration (gcc does) — a pair
    designed on signed int would be invalid. Every cast shape is refused, as the oracle refuses it."""
    text = ('#include "t.h"\ntypedef enum { E_A, E_B } ETYPE;\nS16 h(S16 a, S16 b)\n{\n'
            "    if ((a < (ETYPE)-1) && (b > 0)) { return 1; }\n    if ((a < (ETYPE)(-1)) && (b > 0)) { return 2; }\n"
            "    if ((a < (ETYPE)b) && (b > 0)) { return 3; }\n    return 0;\n}\n")
    rep = build_mcdc_design(_unit({"a.c": text}, "h", inputs=["a", "b"]))
    assert len(rep["decisions"]) == 3
    for d in rep["decisions"]:
        assert d["status"] != "designed", d["expression"]
        assert "enum" in str(d.get("static_reason") or d.get("reason")), d


def test_an_oversized_designator_is_no_table():
    """(review I-1) ``{ [2000000] = 1U }`` would build two million elements — not a lookup table."""
    text = '#include "t.h"\nstatic const U8 tab[] = { [2000000] = 1U };\nstatic const U8 big[100000] = { 1U };\nvoid f(void) { }\n'
    arrays = _scope({"a.c": text})["arrays"]
    assert (arrays["tab"]["values"], arrays["tab"]["values_unread"]) == (None, "length_over_budget")
    assert (arrays["big"]["values"], arrays["big"]["values_unread"]) == (None, "length_over_budget")


def test_a_converting_cast_constant_is_missed_not_invented():
    """(review I-5) ``x == (U8)-1`` compares with 255 after a converting cast — the walk misses it rather than invent -1."""
    text = '#include "t.h"\nU8 g_o;\nvoid f(U8 x)\n{\n    if (x == (U8)-1) { g_o = 1U; }\n}\n'
    assert compared_constants(_unit({"a.c": text}, "f", inputs=["x"]), ["x"]) == {}


def test_linked_values_carry_the_defining_units_assumptions():
    """(review I-5) the defining unit decided the value under its own #if verdicts (R17: FEATURE_X undefined on the build
    configuration's evidence) — the reading unit inherits them."""
    from tests.unit.test_build_defines_r17 import CPROJECT
    files = {"cfg.h": LINKED["cfg.h"], "a.c": LINKED["a.c"],
             "cfg.c": '#include "cfg.h"\n#ifdef FEATURE_X\n#define V 5U\n#else\n#define V 4U\n#endif\n'
                      "const U8 cfg_tab[2] = { V, 1U };\n"}
    ctx = cpc.build_project_context({os.path.join(ROOT, k): v for k, v in {"t.h": H, **files}.items()},
                                    cpc.detect_build_config({os.path.join(ROOT, ".cproject"): CPROJECT.format(options="")}),
                                    roots=[ROOT])
    path = os.path.join(ROOT, "a.c")
    scope = cpc.build_scopes(ctx, [path])[path]
    assert scope["arrays"]["cfg_tab"]["values"] == [4, 1]
    assert "FEATURE_X" in scope["assumed_undefined"]


@pytest.mark.parametrize("definitions", [
    {"cfg.c": '#include "t.h"\nstatic const U8 cfg_tab[2] = { 1U, 2U };\n'},     # internal linkage: not the program's
    {"cfg_def.h": '#include "t.h"\nconst U8 cfg_tab[2] = { 1U, 2U };\n'},       # a header is not a translation unit
])
def test_only_an_external_definition_in_a_c_file_links(definitions):
    files = {"cfg.h": LINKED["cfg.h"], "a.c": LINKED["a.c"], **definitions}
    a = _scope(files)["arrays"]["cfg_tab"]
    assert a["values"] is None and a["values_unread"] == "no_initializer_in_unit"


def test_a_macro_of_the_typedefs_name_wins_in_the_oracle():
    """(review I-5) the preprocessor replaces ``S16`` before the compiler sees a type: ``(S16)-1`` is ``(2)-1``."""
    text = '#include "t.h"\n#define S16 2\nint g_out;\nvoid f(void)\n{\n    g_out = (S16)-1;\n}\n'
    assert _run({"a.c": text}, "f", {}, ["g_out"]) == {"g_out": 1}


def test_mcdc_reevaluation_keeps_a_variable_named_like_a_recorded_type():
    """(review I-5) without a scope, a name the design recorded as a type is a cast only when it is no input."""
    t16 = {"kind": "int", "bits": 16, "signed": True, "rank": 3}
    dom = {"x": {"min": -100, "max": 100, "ctype": t16}, "a": {"min": -100, "max": 100, "ctype": t16}}
    got = evaluate_decision("(x)-1 < a", {"x": 5, "a": 3}, dom, {}, {"char": 8, "short": 16, "int": 16, "long": 32,
                                                                      "long long": 64}, {"x": t16})
    assert got["decision"] is False         # 5 - 1 < 3 is false; read as the cast of -1 it would be true


def test_a_pointer_typedef_split_off_says_its_type_is_unmodeled():
    """(review I-7) the reason names what the model lacks — a scalar for ``PU8`` — not a grammar split."""
    text = '#include "t.h"\ntypedef U8 *PU8;\nU16 g_u;\nvoid f(void)\n{\n    g_u = (U16)-1 + (PU8)+2;\n}\n'
    assert _run({"a.c": text}, "f", {}, ["g_u"]) == {"g_u": "cast_type_unmodeled:PU8"}


def test_a_value_from_another_units_definition_is_named_in_the_assumptions():
    """(review I-2) the record's source hash covers the function's own file — the table's footing is named."""
    (r,) = evaluate_outputs(_unit(LINKED, "f"), [{"i": 1}], [["g_o"]])
    assert r["outputs"]["g_o"]["value"] == 255
    assert any("cfg_tab (cfg.c)" in a for a in r.get("assumptions") or ()), r.get("assumptions")


def test_a_member_path_of_a_const_object_is_not_dropped():
    """(review I-4 c) ``g_cfg.p[0].m`` may cross a pointer member to writable data — only the const object's own
    elements leave the rows."""
    from generators import suts as gsuts

    fd = {"F1": {"name": "f", "prototype": "void f(void)", "inputs": [], "outputs": [],
                 "globals_global": ["[IN] g_cfg", "[OUT] g_o"]}}
    gim = {"g_cfg": {"type": "const CFG_T"}, "g_o": {"type": "U8"}}
    io = {"by_name": {"f": {"inputs": ["g_cfg->p->m", "g_cfg"], "outputs": ["g_o"]}}}
    (u,) = gsuts.collect_unit_functions(fd, gim, sds_map={}, uds_io_map=io)
    assert u["uds_const_inputs"] == ["g_cfg"]
    assert any(v.startswith("g_cfg.p") or v.startswith("g_cfg[0]") or "p[0]" in v for v in u["input_vars"]), u["input_vars"]


def test_mcdc_keeps_an_enumeration_cast_every_permitted_type_agrees_on():
    """(review W-2) 0..127 is the same value under every type the implementation may pick — the cast of ``1`` is
    designed as before (the oracle's `enum_dual` keeps such a value too) when the other side cannot be negative (an
    enumeration operand against a possibly negative one is refused as for enumeration objects, review W-A)."""
    text = ('#include "t.h"\ntypedef enum { E_A, E_B } ETYPE;\nS16 h(U8 a, S16 b)\n{\n'
            "    if ((a == (ETYPE)1) && (b > ( S16 )-5)) { return 1; }\n    return 0;\n}\n")
    (d,) = build_mcdc_design(_unit({"a.c": text}, "h", inputs=["a", "b"]))["decisions"]
    assert d["status"] == "designed", d


# ── review round 2 ───────────────────────────────────────────────────────────────────────────────

ENUM_H = '#include "t.h"\ntypedef enum { E_A, E_B } ETYPE;\n'


def test_a_constant_converted_to_an_enumeration_type_outside_0_127_has_no_value():
    """(review C-1) ``((ETYPE)-1)`` is UINT_MAX under gcc's unsigned choice and 255 under -fshort-enums — the evaluator
    gave -1. Only 0..127 converts alike under every type the implementation may pick."""
    text = (ENUM_H + "#define E_NONE ((ETYPE)-1)\n#define E_ONE ((ETYPE)1)\nstatic const ETYPE k_none = (ETYPE)-1;\n"
            "static const ETYPE k_tab[2] = { (ETYPE)1, (ETYPE)200 };\nvoid f(void) { }\n")
    scope = _scope({"a.c": text})
    assert "E_NONE" not in scope["constants"] and "enum_underlying" in scope["unresolved_constants"]["E_NONE"]
    assert scope["constants"]["E_ONE"]["value"] == 1
    assert "k_none" not in scope["constants"]
    assert scope["arrays"]["k_tab"]["values"] is None
    assert "enum_underlying" in scope["arrays"]["k_tab"]["values_unread"]


def test_mcdc_refuses_a_comparison_with_an_enumeration_typed_constant_that_may_be_negative():
    """(review W-A) ``s >= (ETYPE)0`` with ``s = -1``: under an unsigned choice -1 converts to UINT_MAX and compares true —
    a pair designed on signed int would be invalid."""
    text = (ENUM_H + "#define E_ZERO ((ETYPE)0)\nS16 h(S16 s, S16 b)\n{\n"
            "    if ((s >= (ETYPE)0) && (b > 0)) { return 1; }\n    if ((s >= E_ZERO) && (b > 0)) { return 2; }\n"
            "    if (((ETYPE)1 - 2 < s) && (b > 0)) { return 3; }\n    return 0;\n}\n")
    rep = build_mcdc_design(_unit({"a.c": text}, "h", inputs=["s", "b"]))
    assert len(rep["decisions"]) == 3
    for d in rep["decisions"]:
        assert d["status"] != "designed", d["expression"]


def test_a_const_scalar_without_a_held_value_is_no_input_the_test_lacks():
    """(review W-B) as for tables: ``extern const U8 k_lim;`` whose one definition does not evaluate is the program's value —
    not `initial_value_not_in_inputs` (a false 'input list gap'), and a row that sets it does not make it so."""
    files = {"cfg.h": '#include "t.h"\nextern const U8 k_lim;\n',
             "cfg.c": '#include "cfg.h"\nconst U8 k_lim = X_UNKNOWN;\n',
             "a.c": '#include "cfg.h"\nU8 g_o;\nvoid f(void) { g_o = k_lim; }\n'}
    assert _run(files, "f", {}, ["g_o"])["g_o"].startswith("const_values_unread:k_lim:")
    assert _run(files, "f", {"k_lim": 3}, ["g_o"])["g_o"].startswith("const_values_unread:k_lim:")


def test_a_const_scalar_links_to_the_definition_in_its_own_build():
    """(review I-d) APP and BOOT both define ``k_lim``: the APP unit takes the APP definition (before: two definitions,
    no link; and a BOOT-only definition was taken by APP)."""
    files = {"app/t.h": H, "boot/t.h": H, "app/cfg.h": '#include "t.h"\nextern const U8 k_lim;\n',
             "app/cfg.c": '#include "cfg.h"\nconst U8 k_lim = 3U;\n',
             "app/a.c": '#include "cfg.h"\nU8 g_o;\nvoid f(void) { g_o = k_lim; }\n',
             "boot/cfg.c": '#include "t.h"\nconst U8 k_lim = 9U;\n'}
    roots = [os.path.join(ROOT, "app"), os.path.join(ROOT, "boot")]
    assert _scope(files, unit="app/a.c", roots=roots)["constants"]["k_lim"]["value"] == 3
    only_boot = {k: v for k, v in files.items() if k != "app/cfg.c"}
    assert "k_lim" not in _scope(only_boot, unit="app/a.c", roots=roots)["constants"]


# ── review round 3 ───────────────────────────────────────────────────────────────────────────────

ENUM_ARITH = (ENUM_H + "#define E_ONE ((ETYPE)1)\n#define E_M1 (E_ONE - 2)\n#define E_P1 (E_ONE + 1)\n#define E_NEG (-E_ONE)\n"
              "#define E_NOT (!E_ONE)\nS32 g_o;\nS32 g_w;\n"
              "void f(void)\n{\n    switch (E_M1) { case -1: g_o = 1; break; default: g_o = 9; break; }\n    g_w = E_M1;\n}\n")


def test_arithmetic_on_an_enumeration_operand_has_a_value_only_when_every_type_agrees(tmp_path):
    """(review W-R3-2) ``E_ONE - 2`` is -1 for int and UINT_MAX for unsigned int (gcc's choice for this enum): no one
    value. ``!E_ONE`` is 0 under every choice."""
    scope = _scope({"a.c": ENUM_ARITH})
    for name in ("E_M1", "E_P1", "E_NEG"):
        assert name not in scope["constants"], name
        assert "enum_underlying" in scope["unresolved_constants"][name], name
    assert scope["constants"]["E_NOT"]["value"] == 0
    out = _gcc(tmp_path, {"a.c": ENUM_ARITH}, "extern S32 g_o, g_w; void f(void);\n"
                                              "int main(void) { f(); printf(\"%ld %ld\", (long)g_o, (long)g_w); return 0; }\n")
    if out is not None:
        assert out == ["9", "-1"] or out == ["1", "-1"]     # the host's choice — the model claims neither


def test_a_switch_on_such_a_value_takes_no_branch_by_accident():
    """(review C-R3-1) the switch converted -1 into the enumeration and matched no label — default by accident (9); gcc
    takes ``case -1`` on the hosts tried. Unknown, so no branch is claimed."""
    got = _run({"a.c": ENUM_ARITH}, "f", {}, ["g_o", "g_w"])
    assert not isinstance(got["g_o"], int) and not isinstance(got["g_w"], int), got


def test_mcdc_keeps_enumeration_comparisons_in_either_operand_order():
    """(review W-R3-1) ``e == E_BIG`` and ``E_BIG == e`` (an enumerator above 127 — the enumeration's type holds it under
    every choice) are designed alike; the comparison type carries no enumeration tag."""
    text = ('#include "t.h"\ntypedef enum { E_A, E_B, E_BIG = 200 } ETYPE;\nS16 h(ETYPE e, S16 b)\n{\n'
            "    if ((e == E_BIG) && (b > 0)) { return 1; }\n    if ((E_BIG == e) && (b > 0)) { return 2; }\n    return 0;\n}\n")
    rep = build_mcdc_design(_unit({"a.c": text}, "h", inputs=["e", "b"]))
    assert [d["status"] for d in rep["decisions"]] == ["designed", "designed"], rep["decisions"]


def test_the_compared_constant_walk_misses_an_enumeration_cast_outside_0_127():
    """(review round 3 I-1) ``x == (ETYPE)-1`` has no one value to sit rows at."""
    text = ENUM_H + "U8 g_o;\nvoid f(S16 x)\n{\n    if (x == (ETYPE)-1) { g_o = 1U; }\n    if (x == (ETYPE)3) { g_o = 2U; }\n}\n"
    got = compared_constants(_unit({"a.c": text}, "f", inputs=["x"]), ["x"])
    assert {k: sorted(v) for k, v in got.items()} == {"x": [3]}


def test_mcdc_samples_the_value_a_converting_cast_gives():
    """(review round 3 I-6) ``x == (U16)-2`` compares with 65534 — the search samples there."""
    text = '#include "t.h"\nS16 h(U16 x, S16 b)\n{\n    if ((x == (U16)-2) && (b > 0)) { return 1; }\n    return 0;\n}\n'
    (d,) = build_mcdc_design(_unit({"a.c": text}, "h", inputs=["x", "b"]))["decisions"]
    assert d["status"] == "designed", d
    assert any(p.get("inputs_a", p.get("a", {})).get("x") == 65534 or p.get("inputs_b", p.get("b", {})).get("x") == 65534
               for p in d["pairs"]), d["pairs"]


def test_a_const_pointers_pointee_is_a_design_input_that_stays():
    """(review round 3 I-3) ``U8 * const p``: the pointer is const, ``p[0]`` is writable data the test sets."""
    from generators import suts as gsuts

    fd = {"F1": {"name": "f", "prototype": "void f(void)", "inputs": [], "outputs": [],
                 "globals_global": ["[IN] p_buf", "[OUT] g_o"]}}
    gim = {"p_buf": {"type": "U8 * const"}, "g_o": {"type": "U8"}}
    io = {"by_name": {"f": {"inputs": ["p_buf", "p_buf[0]"], "outputs": ["g_o"]}}}
    (u,) = gsuts.collect_unit_functions(fd, gim, sds_map={}, uds_io_map=io)
    assert u["uds_const_inputs"] == ["p_buf"] and "p_buf[0]" in u["input_vars"]


def test_a_typedef_const_table_is_never_zero_filled():
    """(review round 3 I-4 · round 2 I-b) ``typedef const U8 CU8; static CU8 t[3] = {…};`` — the declaration does not say
    const, so its initializer is not kept; it must not read as a tentative definition's zeros. (The model does not carry
    const through a typedef yet — the table is then no const table at all: a remaining gap, recorded in the plan.)"""
    text = '#include "t.h"\ntypedef const U8 CU8;\nstatic CU8 t[3] = { 1U, 2U, 3U };\nvoid f(void) { }\n'
    a = _scope({"a.c": text})["arrays"]["t"]
    assert a["values"] is None and a.get("values_source") != "tentative_definition"


def test_a_file_outside_every_root_links_to_nothing():
    """(review round 3 I-5) with roots, a file in none of them is in no build."""
    files = {"app/t.h": H, "app/cfg.h": '#include "t.h"\nextern const U8 cfg_tab[];\n',
             "app/a.c": '#include "cfg.h"\nU8 g_o;\nvoid f(U8 i) { g_o = cfg_tab[i]; }\n',
             "elsewhere/cfg.c": '#include "../app/t.h"\nconst U8 cfg_tab[2] = { 1U, 2U };\n'}
    a = _scope(files, unit="app/a.c", roots=[os.path.join(ROOT, "app")])["arrays"]["cfg_tab"]
    assert a["values"] is None
    assert cpc._same_build({"roots": []}, "x.c", "y.c") is True
    assert cpc._same_build({"roots": [os.path.join(ROOT, "app")]}, os.path.join(ROOT, "o", "x.c"),
                           os.path.join(ROOT, "o", "y.c")) is False


def test_a_member_of_a_const_table_the_design_lists_leaves_the_rows():
    """KJPDS02_PV ``u16s_ApiIn_MotorTemp_Conv``: the design lists ``s_NTCLookupTable.s16_Temperature`` /
    ``.u16_AdcValue`` of ``static const`` NTC table — members of the const object, not through a pointer."""
    from generators import suts as gsuts

    fd = {"F1": {"name": "f", "prototype": "U16 f(U16 u16t_Data)", "inputs": ["U16 u16t_Data"], "outputs": [],
                 "globals_static": ["[IN] s_NTCLookupTable", "[OUT] g_o"]}}
    gim = {"s_NTCLookupTable": {"type": "const NTC_T", "array": "[11]"}, "g_o": {"type": "U16"}}
    io = {"by_name": {"f": {"inputs": ["u16t_Data", "s_NTCLookupTable.s16_Temperature", "s_NTCLookupTable.u16_AdcValue"],
                            "outputs": ["g_o"]}}}
    (u,) = gsuts.collect_unit_functions(fd, gim, sds_map={}, uds_io_map=io)
    assert sorted(u["uds_const_inputs"]) == ["s_NTCLookupTable.s16_Temperature", "s_NTCLookupTable.u16_AdcValue"]
    assert u["input_vars"] == ["u16t_Data"]


# ── review round 4 ───────────────────────────────────────────────────────────────────────────────

def test_a_conditional_with_an_enumeration_arm_has_no_one_type():
    """(review W-R4-1) ``((1 ? 200 : E_ONE) - 300) > 0`` is 1 under gcc's unsigned choice and 0 under -fshort-enums."""
    text = (ENUM_H + "#define E_ONE ((ETYPE)1)\n#define K1 (((1 ? 200 : E_ONE) - 300) > 0)\n"
            "#define K2 (((0 ? E_ONE : 200) - 300) > 0)\n#define K3 ((1 ? 200 : 7) - 300)\nvoid f(void) { }\n")
    scope = _scope({"a.c": text})
    for name in ("K1", "K2"):
        assert name not in scope["constants"] and "enum_underlying" in scope["unresolved_constants"][name], name
    assert scope["constants"]["K3"]["value"] == -100


def test_every_choice_refusing_alike_keeps_its_reason():
    """(review round 4 I-2) ``E_ONE / 0`` is a division by zero under every choice — said so."""
    text = ENUM_H + "#define E_ONE ((ETYPE)1)\n#define K (E_ONE / 0)\nvoid f(void) { }\n"
    scope = _scope({"a.c": text})
    assert "K" not in scope["constants"]                  # constants resolve on first lookup
    assert scope["unresolved_constants"]["K"] == "division_by_zero"


@pytest.mark.parametrize("cond", ["(-e) && (b > 0)", "(~e) && (b > 0)", "((S16)-e < -1) && (b > 0)"])
def test_mcdc_refuses_unary_arithmetic_on_an_enumeration_operand(cond):
    """(review W-R4-2) implementation-defined, refused when compiled — not 'undefined behavior candidates' later."""
    text = ENUM_H + "S16 h(ETYPE e, S16 b)\n{\n    if (" + cond + ") { return 1; }\n    return 0;\n}\n"
    (d,) = build_mcdc_design(_unit({"a.c": text}, "h", inputs=["e", "b"]))["decisions"]
    assert d["status"] != "designed"
    assert "enum_underlying" in str(d.get("static_reason") or d.get("reason")), d
    assert "undefined_behavior" not in str(d.get("reason")), d


SWITCH = ('#include "t.h"\ntypedef enum { E_A, E_B, E_BIG = 200 } ETYPE;\nU8 g_o;\n'
          "void f(ETYPE e)\n{\n    switch (e) { case E_A: g_o = 1U; break; case E_BIG: g_o = 2U; break; default: g_o = 9U; break; }\n}\n"
          "void g(S16 x)\n{\n    switch (x) { case 1: g_o = 1U; break; case 0xFFFF: g_o = 2U; break; default: g_o = 9U; break; }\n}\n")


def test_a_switch_takes_the_label_that_matches_exactly(tmp_path):
    """(review W-R4-3) labels are distinct after conversion (C11 6.8.4.2p3): an exact match is certain even when another
    label converts implementation-defined (``case 0xFFFF`` for a 16-bit int). gcc agrees."""
    assert _run({"a.c": SWITCH}, "f", {"e": 0}, ["g_o"]) == {"g_o": 1}
    assert _run({"a.c": SWITCH}, "f", {"e": 1}, ["g_o"]) == {"g_o": 9}
    assert _run({"a.c": SWITCH}, "g", {"x": 1}, ["g_o"]) == {"g_o": 1}
    out = _gcc(tmp_path, {"a.c": SWITCH}, "typedef enum { E_A, E_B, E_BIG = 200 } ETYPE;\n"
                                          "extern U8 g_o; void f(ETYPE e); void g(S16 x);\n"
                                          "int main(void) { f(E_A); printf(\"%u \", (unsigned)g_o); f(E_B); "
                                          "printf(\"%u \", (unsigned)g_o); g(1); printf(\"%u\", (unsigned)g_o); return 0; }\n")
    if out is not None:
        assert out == ["1", "9", "1"]


def test_a_switch_with_no_exact_match_and_an_unconverted_label_claims_no_branch():
    """(review round 3 C-R3-1 · round 4 I-1) ``x = -1`` against ``case 0xFFFF`` (implementation-defined as a 16-bit int): it
    may be that label — the switch must not fall to default by accident."""
    got = _run({"a.c": SWITCH}, "g", {"x": -1}, ["g_o"])
    assert not isinstance(got["g_o"], int) and "branch_on_unknown" in str(got["g_o"]), got


def test_a_float_converted_to_an_enumeration_type_outside_0_127_has_no_value():
    """(review round 5) ``(ETYPE)300.0`` is 300 under gcc's default and 44 under -fshort-enums."""
    text = ENUM_H + "#define K3 ((ETYPE)300.0)\n#define K4 ((ETYPE)3.0)\nvoid f(void) { }\n"
    scope = _scope({"a.c": text})
    assert "K3" not in scope["constants"] and "enum_underlying" in scope["unresolved_constants"]["K3"]
    assert scope["constants"]["K4"]["value"] == 3
