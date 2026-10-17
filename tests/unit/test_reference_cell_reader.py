"""R26 — one reader for reference cells, one cast judgement in the source oracle.

A reference SUTS writes an enumerator as ``NAME(5)``. The oracle read that notation in *input* cells (R14) but the
measurement scripts' shared ``reference_value`` did not read it in *expected* cells, so R3 alignment and R4 mutant
discrimination dropped KJPDS02_PV's expected enumerators (R24 review r3 C1; the replay read them with a reader of its
own). Now every consumer reads a cell through `generators.c_source_oracle.read_reference_cell`.

The oracle judged ``(U8)(x)`` — which tree-sitter parses as a call of ``(U8)`` — a cast when it evaluated it, but a call
where it asked "can this operand change state?": the right operand of ``&&``/``||`` under an unknown left, the arms of
``?:``, and whether a loop's controlling expression is constant. Those sites now ask the same question.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mutation_eval import evaluate  # noqa: E402
from reference_alignment import align, reference_value  # noqa: E402
from test_reference_alignment import COMMON, _reference  # noqa: E402

from generators import c_project_context as cpc  # noqa: E402
from generators.c_source_oracle import REFERENCE_CELL_KINDS, evaluate_outputs, read_reference_cell  # noqa: E402
from generators.integration_oracle import CalleeProvider  # noqa: E402

CONSTANTS = {"en_on": {"value": 5}, "K_TWO": {"value": 2}, "K_F": {"value": 1.5}}


@pytest.mark.parametrize("cell, expected", [
    (5, (5, "int")), (3.0, (3, "int")), ("0x1F", (31, "int")), ("-1", (-1, "int")), ("12UL", (12, "int")),
    ("08", (8, "int")), ("010", (10, "int")),              # a cell is a spreadsheet value, not C source: decimal
    ("K_TWO", (2, "symbol")),
    ("en_on(5)", (5, "named")), ("en_on ( 5 )", (5, "named")),
    # the unit does not resolve the name: the number is the cell's own statement
    ("en_new(0x3)", (3, "named_unconfirmed")), ("en_neg(-3)", (-3, "named_unconfirmed")),
    ("en_x(08)", (8, "named_unconfirmed")), ("en_x(010)", (10, "named_unconfirmed")),
    ("en_on(4)", (None, "conflict")),                      # the unit's en_on is 5: which one the cell means is unknown
    ("K_F(1)", (None, "conflict")),                        # the unit resolves K_F to 1.5 (review r2 I-b)
    ("MS(100)", (None, "function_like")),                  # a macro call is not the value in its parentheses
    ("-", (None, "no_value")), ("N/A", (None, "no_value")), ("NA", (None, "no_value")), ("", (None, "no_value")),
    (None, (None, "no_value")),
    (2.5, (None, "not_integer")), (True, (None, "not_integer")), ("REG.Bits.P3", (None, "not_integer")),
    ("K_F", (None, "not_integer")),
])
def test_one_reader_for_every_reference_cell(cell, expected):
    got = read_reference_cell(cell, CONSTANTS, {"MS"})
    assert got == expected and got[1] in REFERENCE_CELL_KINDS


def test_a_units_own_na_constant_is_a_value():
    # review I2: before R26 both readers looked the name up first — a unit's enumerator ``NA`` stays a value
    assert read_reference_cell("NA", {"NA": {"value": 3}}) == (3, "symbol")


def test_the_measurement_scripts_read_the_named_notation_through_the_shared_reader():
    assert reference_value("en_on(5)", CONSTANTS) == 5
    assert reference_value("en_on(4)", CONSTANTS) is None
    assert reference_value("MS(100)", CONSTANTS, ["MS"]) is None
    assert reference_value("K_TWO", CONSTANTS) == 2


# ── the oracle's inputs ──────────────────────────────────────────────────────────────────────────────────────────────
ROOT = os.path.join(os.sep, "proj")
TYPES = "typedef unsigned char U8;\ntypedef unsigned int U16;\n"


def _run(text, name, inputs, outputs):
    path = os.path.join(ROOT, "unit.c")
    ctx = cpc.build_project_context({path: TYPES + text})
    unit = {"name": name, "source_text": TYPES + text, "source_path": path, "source_text_complete": True,
            "project_scope": cpc.build_scopes(ctx, [path])[path]}
    return evaluate_outputs(unit, [inputs], [outputs])[0]


def _value(result, slot):
    out = result["outputs"][slot]
    return out.get("value", "?" + out.get("reason", ""))


def test_an_input_written_as_a_macro_call_is_not_read_as_its_argument():
    text = "#define MS(x) ((x) / 5U)\nU8 g_i; U8 g_o;\nvoid f(void) { g_o = g_i; }\n"
    assert _value(_run(text, "f", {"g_i": "MS(100)"}, ["g_o"]), "g_o") == "?input_macro_call_not_a_value:g_i"
    text = "enum E { en_a = 5 };\nU8 g_i; U8 g_o;\nvoid f(void) { g_o = g_i; }\n"
    assert _value(_run(text, "f", {"g_i": "en_a(5)"}, ["g_o"]), "g_o") == 5
    assert _value(_run(text, "f", {"g_i": "en_a(4)"}, ["g_o"]), "g_o") == "?input_name_value_conflict:g_i"
    assert _value(_run(text, "f", {"g_i": "-"}, ["g_o"]), "g_o") == "?input_not_an_integer:g_i"


# ── the oracle's cast judgement ──────────────────────────────────────────────────────────────────────────────────────
def test_a_cast_under_an_unknown_condition_is_not_a_side_effect():
    # g_in is not an input (unknown): the right operand may or may not run — a cast in it changes nothing
    text = "U8 g_in; U8 g_x; U8 g_z;\nvoid f(void) { g_z = (g_in == 1U) && ((U8)(g_x) == 2U); }\n"
    assert _value(_run(text, "f", {"g_x": 3}, ["g_z"]), "g_z") == 0
    text = "U8 g_in; U8 g_x; U8 g_z;\nvoid f(void) { g_z = (g_in == 1U) || ((U8)(g_x) == 3U); }\n"
    assert _value(_run(text, "f", {"g_x": 3}, ["g_z"]), "g_z") == 1
    # both arms of an unknown ``?:`` give the same value
    text = "U8 g_in; U8 g_x; U8 g_z;\nvoid f(void) { g_z = (g_in != 0U) ? (U8)(g_x) : (U8)(g_x); }\n"
    assert _value(_run(text, "f", {"g_x": 5}, ["g_z"]), "g_z") == 5
    # a decided ``?:``: the arm not taken holds a cast — its type is still known
    text = "U8 g_k; U8 g_x; U8 g_z;\nvoid f(void) { g_z = (g_k != 0U) ? (U8)(g_x) : 0U; }\n"
    assert _value(_run(text, "f", {"g_k": 0, "g_x": 5}, ["g_z"]), "g_z") == 0


def test_an_effect_inside_a_cast_still_refuses():
    text = "U8 g_in; U8 g_x; U8 g_z;\nextern U8 lib(void);\nvoid f(void) { g_z = (g_in == 1U) && ((U8)(lib()) == 2U); }\n"
    assert _run(text, "f", {"g_x": 3}, ["g_z"])["reason"] == "side_effect_under_unknown_condition"
    text = "U8 g_in; U8 g_x; U8 g_z;\nvoid f(void) { g_z = (g_in != 0U) ? (U8)(g_x++) : 0U; }\n"
    assert _run(text, "f", {"g_x": 3}, ["g_z"])["reason"] == "side_effect_under_unknown_condition"
    # a call of a parenthesized function name is a call, not a cast
    text = "U8 g_in; U8 g_z;\nU8 lib(U8 v);\nvoid f(void) { g_z = (g_in == 1U) && ((lib)(1U) == 2U); }\n"
    assert _run(text, "f", {}, ["g_z"])["reason"] == "side_effect_under_unknown_condition"


H2 = "#ifndef H_H\n#define H_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\nextern U8 g_out; extern U8 g_in;\n#endif\n"
LOOP_B = ('#include "h.h"\n'
          "void Spin(void) { while ((U8)(1U)) { } }\n"
          "void Hold(void) { while ((U8)(1U)) { if (g_in != 0U) { break; } } }\n"
          "void Drain(void) { while ((U8)(g_in)) { g_in = 0U; } }\n"
          "U8 Rd(void) { return g_in; }\n")
LOOP_A = ('#include "h.h"\nU8 g_out; U8 g_in;\nvoid Spin(void); void Hold(void); void Drain(void); U8 Rd(void);\n'
          "void s(void) { g_out = 1U; Spin(); g_out = 2U; }\n"
          "void h(void) { g_out = 1U; Hold(); g_out = 2U; }\n"
          "void d(void) { g_out = 1U; Drain(); g_out = 2U; }\n"
          "void c(void) { g_out = (g_in != 0U) ? 0U : (U8)(Rd()); }\n")


def _run2(entry, inputs, outputs):
    files = {os.path.join(ROOT, "h.h"): H2, os.path.join(ROOT, "a.c"): LOOP_A, os.path.join(ROOT, "b.c"): LOOP_B}
    ctx = cpc.build_project_context(files)
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    a = os.path.join(ROOT, "a.c")
    unit = {"name": entry, "source_text": files[a], "source_path": a, "source_text_complete": True,
            "project_scope": scopes[a], "callee_provider": CalleeProvider(ctx, files, scopes, cpc.shared_parser())}
    return evaluate_outputs(unit, [inputs], [outputs])[0]


def test_a_loop_whose_condition_is_a_cast_constant_is_a_constant_condition_loop():
    # ``while ((U8)(1U)) { }`` never ends — like ``while (1U) { }``, the caller's later state is never observed
    r = _run2("s", {}, ["g_out"])
    assert r["status"] == "unsupported" and r["reason"] == "non_terminating_loop"
    # with a way out that this input never takes: out of budget, it may never end — never assumed to return
    r = _run2("h", {"g_in": 0}, ["g_out"])
    assert r["status"] == "unsupported" and r["reason"] == "constant_condition_loop_unfinished"
    assert _value(_run2("h", {"g_in": 1}, ["g_out"]), "g_out") == 2
    # review W2 M1: the cast's ARGUMENT is still judged — ``(U8)(g_in)`` reads state, so the loop is not constant
    assert _value(_run2("d", {"g_in": 1}, ["g_out"]), "g_out") == 2


def test_a_call_inside_a_cast_in_the_arm_not_taken_never_runs():
    # review W2 M2: the decided ``?:`` — the arm not taken is only typed; a call in it (inside a cast) must not run
    r = _run2("c", {"g_in": 1}, ["g_out"])
    assert "Rd" not in r["interprocedural"]["inlined"]
    assert r["outputs"]["g_out"].get("reason") == "conditional_type_unresolved"


# ── the measurement scripts ──────────────────────────────────────────────────────────────────────────────────────────
ENUM_UNIT = """#include "common.h"
typedef enum { en_off = 0, en_on = 5 } EState;
U8 g_i;
EState g_s;
void f(void) { if (g_i >= 10U) { g_s = en_on; } else { g_s = en_off; } }
"""


@pytest.fixture()
def enum_tree(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text(ENUM_UNIT, encoding="utf-8", newline="\n")
    return root


def test_alignment_compares_an_expected_enumerator_in_the_named_notation(tmp_path, enum_tree):
    ref = tmp_path / "ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_s"], [
        (1, {"g_i": 10}, {"g_s": "en_on(5)"}),     # agrees — before R26 this cell was "not an integer"
        (2, {"g_i": 0}, {"g_s": "en_on(0)"}),      # the unit's en_on is 5: the cell is not comparable
        (3, {"g_i": 0}, {"g_s": "en_off(0)"})])])
    (rec,) = align(str(ref), [enum_tree])["functions"]
    assert rec["status"] == "aligned" and rec["slots"] == {"agree": 2, "not_comparable": 1}
    assert rec["unknown_reasons"] == {"reference_name_value_conflict": 1}
    assert rec["expected_cells"] == {"named": 2, "conflict": 1}
    assert rec["agree_via_reference_symbol"] == 0      # the notation states its own value — not the current symbol's


def test_mutant_discrimination_counts_an_expected_enumerator_in_the_named_notation(tmp_path, enum_tree):
    ref = tmp_path / "ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_s"],
                      [(1, {"g_i": 9}, {"g_s": "en_off(0)"}), (2, {"g_i": 10}, {"g_s": "en_on(5)"})])])
    report = evaluate(str(ref), str(ref), [enum_tree], None, derived_only=False)
    (rec,) = report["functions"]
    assert rec["suite_slots"]["reference"] == 2 and rec["results"]["killed_by_reference"] > 0
    assert report["summary"]["expected_cells"]["reference"] == {"named": 2}


# ── review round 1: the wiring of the function-like macro set, the clang readers, the replay's cell keys ────────────
MACRO_UNIT = """#include "common.h"
#define MS(x) ((x) / 5U)
U8 g_i;
U8 g_o;
void f(void) { g_o = (U8)(g_i + 1U); }
"""


@pytest.fixture()
def macro_tree(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text(MACRO_UNIT, encoding="utf-8", newline="\n")
    return root


def test_a_macro_call_in_a_reference_cell_is_never_its_argument(tmp_path, macro_tree):
    # review W2 M9/M10/M11: R3 inputs (`_convert_inputs`), R3 expected cells and R4 expected cells all pass the unit's
    # function-like macros — ``MS(100)`` is not 100
    ref = tmp_path / "ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [
        (1, {"g_i": "MS(100)"}, {"g_o": 101}),   # the input is a macro call: unknown in the oracle, not 100
        (2, {"g_i": 4}, {"g_o": "MS(5)"}),       # the expected value is a macro call: not compared as 5
        (3, {"g_i": 4}, {"g_o": 5})])])
    (rec,) = align(str(ref), [macro_tree])["functions"]
    assert rec["slots"] == {"agree": 1, "not_comparable": 2}
    assert rec["expected_cells"] == {"int": 2, "function_like": 1}
    assert rec["unknown_reasons"] == {"input_macro_call_not_a_value": 1, "reference_value_not_integer": 1}
    report = evaluate(str(ref), str(ref), [macro_tree], None, derived_only=False)
    assert report["summary"]["expected_cells"]["reference"] == {"int": 2, "function_like": 1}
    assert report["functions"][0]["suite_slots"]["reference"] == 1


def test_a_named_input_converted_into_its_type_keeps_the_notation(tmp_path, macro_tree):
    # review I1: ``en_x(300)`` into a U8 is held as 44 — the conversion lists the notation, not only its number
    ref = tmp_path / "ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": "en_x(300)"}, {"g_o": 45})])])
    (rec,) = align(str(ref), [macro_tree])["functions"]
    assert rec["input_conversions"] == [{"input": "g_i", "reference": 300, "held": 44, "count": 1,
                                         "written": "en_x(300)"}]
    assert rec["slots"] == {"agree": 1}


def test_the_clang_checks_read_inputs_as_the_oracle_does():
    from integration_oracle_clang_check import _input_value
    from source_oracle_clang_check import _input_int
    consts = {"en_on": {"value": 5}}
    assert _input_int("en_on(5)", consts) == 5 and _input_int("5U", consts) == 5 and _input_int("en_on", consts) == 5
    assert _input_int("en_on(4)", consts) is None                  # a conflict: the oracle leaves it unknown
    assert _input_int("MS(100)", consts, ["MS"]) is None           # a macro call: not its argument
    assert _input_int(3.0, consts) is None                         # the oracle takes only an ``int`` that is not a str
    a = {"constants": {"en_on": {"value": 5}}, "function_like_macros": []}
    b = {"constants": {"en_on": {"value": 4}}, "function_like_macros": []}
    assert _input_value("en_on(5)", [a, a]) == (5, "")
    # review I4: one unit reads 5, another a conflict — the units disagree
    assert _input_value("en_on(5)", [a, b]) == (None, "input_value_differs_between_units")
    # review r2 W1 MX2: ``MS`` is a macro only where unit m includes it; unit a reads ``MS(100)`` as the cell's 100
    m = {"constants": {}, "function_like_macros": ["MS"]}
    assert _input_value("MS(100)", [a, m]) == (None, "input_value_differs_between_units")
    # review r2 I-c: a unit that does not know the name at all does not disagree
    assert _input_value("en_on", [a, {"constants": {}, "function_like_macros": []}]) == (5, "")


def test_every_reader_kind_has_a_replay_cell_key():
    # review X5: the replay maps every kind; its keys stay the four R24 reported
    import history_replay as hr
    assert set(hr.CELL_TAGS) == set(REFERENCE_CELL_KINDS)
    # R24's four keys, plus ``named_unconfirmed`` apart from the unit-confirmed ``named`` (review r2 W3)
    assert {t for t in hr.CELL_TAGS.values() if t} == {"named", "named_unconfirmed", "named_conflict", "no_value",
                                                        "unreadable"}


def test_the_sits_measurement_reads_expected_cells_as_the_oracle_does():
    # review W1: SITS expected cells through the same reader, with the entry unit's constants and macros
    from sits_mutation_eval import as_int
    scope = {"constants": {"en_on": {"value": 5}}, "function_like_macros": ["TIME_MS"]}
    assert as_int("TIME_MS(100)", scope) is None               # a macro call states no value
    assert as_int("en_on(4)", scope) is None                   # a conflict is not an expectation to contradict
    assert as_int("en_on(5)", scope) == 5 and as_int("en_on", scope) == 5
    assert as_int("E_OK (0)", scope) == 0 and as_int("(3)", scope) == 3 and as_int("0x10", scope) == 16
    assert as_int("-", scope) is None and as_int(True, scope) is None and as_int(7.0) == 7


def test_the_sits_reader_reads_a_name_in_every_unit_the_test_reaches():
    # review r2 I-a: the entry's unit does not know ``en_on`` or ``TIME_MS``; the unit that writes the output does
    from sits_mutation_eval import read_cell
    entry = {"constants": {}, "function_like_macros": []}
    writer = {"constants": {"en_on": {"value": 5}}, "function_like_macros": ["TIME_MS"]}
    assert read_cell("en_on(5)", [entry, writer]) == (5, "named")
    assert read_cell("en_on", [entry, writer]) == (5, "symbol")
    assert read_cell("TIME_MS(100)", [entry, writer]) == (None, "function_like")
    assert read_cell("en_on(4)", [entry, writer]) == (None, "conflict")
    other = {"constants": {"en_on": {"value": 6}}, "function_like_macros": []}
    assert read_cell("en_on", [writer, other]) == (None, "units_disagree")   # two units, two values (r3 I2)
    # r3 I1: ``NA`` is a value only where the entry's unit defines it — not wherever the closure reaches
    assert read_cell("NA", [entry, {"constants": {"NA": {"value": 255}}}]) == (None, "no_value")
    assert read_cell("NA", [{"constants": {"NA": {"value": 3}}}, entry]) == (3, "symbol")
    assert read_cell("en_x(3)", [entry]) == (3, "named_unconfirmed")


def test_a_reader_error_on_one_sits_cell_is_counted_not_fatal(monkeypatch):
    # review r4 Info-2: an exception while resolving a name ends neither the run nor silently reads as a value
    import sits_mutation_eval as sme

    from generators import c_source_oracle as oracle

    def boom(value, constants=None, function_like=()):
        raise RuntimeError("resolver")
    monkeypatch.setattr(oracle, "read_reference_cell", boom)
    assert sme.read_cell("en_on", [{"constants": {}}]) == (None, "reader_error:RuntimeError")
