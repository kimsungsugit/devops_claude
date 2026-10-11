"""R4 (P0/G1) — mutant discrimination of unit-test suites (`scripts/mutation_eval.py`).

Mutants are one-edit, same-length changes of the function text; both suites are judged on the same mutants by the
source oracle. A suite kills a mutant only through a slot it states *and* the unmutated function reproduces.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mutation_eval import _apply, _fit, _literal_variants, evaluate, mutants_of  # noqa: E402
from test_reference_alignment import COMMON, _reference  # noqa: E402

from generators import c_project_context as cpc  # noqa: E402


def _fn(text: str, name: str):
    from generators.mcdc_design import _function_name
    raw = text.encode()
    stack = [cpc.shared_parser().parse(raw).root_node]
    while stack:
        n = stack.pop()
        if n.type == "function_definition" and _function_name(n, raw)[0] == name:
            return n, raw
        stack.extend(n.named_children)
    raise AssertionError(name)


def test_every_mutant_keeps_the_text_length_so_the_scope_stays_valid():
    text = "void f(void) { if (a < 9U && b != 0U) { c = a + 1U; } x = 0x0FU; }\n"
    fn, raw = _fn(text, "f")
    mutants = mutants_of(fn, raw)
    assert mutants and all(len(_apply(raw, m)) == len(raw) for m in mutants)
    ops = {(m["operator"], m["original"], m["replacement"]) for m in mutants}
    assert ("relational", "<", ">") in ops and ("relational", "<", "<=") in ops  # ``<=`` absorbs the blank after
    assert ("logical", "&&", "||") in ops and ("arithmetic", "+", "-") in ops
    assert ("literal", "9U", "10U") in ops and ("literal", "0x0FU", "0x10U") in ops
    assert any(m["operator"] == "statement_deletion" for m in mutants)


def test_an_edit_that_cannot_keep_the_length_is_not_made():
    assert _fit(b"a<9", 1, 2, "<=") is None                  # no blank to absorb the extra character
    assert _fit(b"a< 9", 1, 2, "<=") == (1, 3, b"<=")
    assert _fit(b"a<=9", 1, 3, "<") == (1, 3, b"< ")
    assert _literal_variants("0U") == ["1U"]                  # never a negative literal


def test_preprocessor_text_is_not_mutated():
    text = "void f(void) {\n#if A > 1\n  x = 1U;\n#endif\n}\n"
    fn, raw = _fn(text, "f")
    assert all(raw[m["start"]:m["end"]] != b">" for m in mutants_of(fn, raw))


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text('#include "common.h"\nU8 g_i;\nU8 g_o;\n'
                                 "void f(void) { if (g_i >= 10U) { g_o = 1U; } else { g_o = 0U; } }\n",
                                 encoding="utf-8", newline="\n")
    return root


def test_boundary_vectors_kill_what_mid_range_vectors_cannot(tmp_path, tree):
    # the reference tests the threshold itself (9, 10); the "generated" suite only far values (0, 200)
    ref, gen = tmp_path / "ref.xlsm", tmp_path / "gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"],
                      [(1, {"g_i": 9}, {"g_o": 0}), (2, {"g_i": 10}, {"g_o": 1})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"],
                      [(1, {"g_i": 0}, {"g_o": 0}), (2, {"g_i": 200}, {"g_o": 1})])])
    report = evaluate(str(ref), str(gen), [tree], None, derived_only=False)
    (rec,) = report["functions"]
    results = rec["results"]
    assert results["killed_by_reference"] > results.get("killed_by_generated", 0)
    # ``>=`` → ``>`` flips only at g_i == 10: the reference kills it, the far values do not
    boundary = [m for m in rec["only_reference"] if m["operator"] == "relational"]
    assert boundary and all(m["why"] == "generated_vectors_do_not_separate" for m in boundary)
    rel = report["summary"]["by_operator"]["relational"]
    assert rel["killed_by_reference"] > rel.get("killed_by_generated", 0) and rel["distinguished"] >=         rel["killed_by_reference"]


def test_a_slot_the_original_does_not_reproduce_never_kills(tmp_path, tree):
    ref = tmp_path / "ref.xlsm"
    # a wrong expected value (g_i=10 → 0) makes that slot fail on the original: it may not count as a kill
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": 0})])])
    report = evaluate(str(ref), str(ref), [tree], None)
    (rec,) = report["functions"]
    assert rec["suite_slots"] == {"reference": 0, "generated": 0}
    assert not rec["results"].get("killed_by_reference")


def test_a_name_two_units_share_is_left_out_not_merged(tmp_path, tree):
    # review r2 W-C: the generated suite names two units ``f`` (one per definition) — their sequences must not merge
    ref, gen = tmp_path / "ref.xlsm", tmp_path / "gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": 1})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": 1})]),
                     ("SwUTC_2", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0})])])
    report = evaluate(str(ref), str(gen), [tree], None, derived_only=False)
    assert report["functions"] == [] and report["summary"]["excluded_duplicate_reference_names"] == ["f"]
    report = evaluate(str(gen), str(ref), [tree], None, derived_only=False)
    assert report["functions"] == [] and report["summary"]["excluded_duplicate_reference_names"] == ["f"]


def test_an_enumerator_the_reference_wrote_is_a_stated_value(tmp_path, tree):
    # review r2 W-D: R3 reads ``K_ONE`` through the unit's constants — R4 must too, or the reference loses its kills
    (tree / "unit.c").write_text((tree / "unit.c").read_text(encoding="utf-8") + "#define K_ONE 1U\n",
                                 encoding="utf-8", newline="\n")
    ref = tmp_path / "ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": "K_ONE"})])])
    report = evaluate(str(ref), str(ref), [tree], None, derived_only=False)
    (rec,) = report["functions"]
    assert rec["suite_slots"]["reference"] == 1 and rec["results"]["killed_by_reference"] > 0


def test_the_report_may_not_overwrite_the_generated_suite(tmp_path, tree):
    import mutation_eval
    ref, gen = tmp_path / "docs" / "ref.xlsm", tmp_path / "gen.xlsm"
    ref.parent.mkdir()
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": 1})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": 1})])])
    with pytest.raises(SystemExit, match="input of this run"):
        mutation_eval.main(["--reference", str(ref), "--generated", str(gen), "--source-root", str(tree),
                            "--out", str(gen)])


def test_a_suite_does_not_borrow_the_pointee_the_other_suite_observes(tmp_path):
    # (R81 review W1) observing `p[0]` sets the pointee up (`_Interp.observes_pointee`): each suite's rows observe their
    #   own columns — the generated rows state `g` only, so `p != 0` stays undecided for them and `g` (a + 1 or a) is no
    #   value they reproduce; with the union of both suites' columns they ran allocated and took kills on `g`
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text('#include "common.h"\nU8 g;\n'
                                 "void f(U16 *p, U8 a) { if (p != 0) { *p = 1U; g = (U8)(a + 1U); } else { g = a; } }\n",
                                 encoding="utf-8", newline="\n")
    ref, gen = tmp_path / "ref.xlsm", tmp_path / "gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( U16 *p, U8 a )", ["a"], ["p[0]"], [(1, {"a": 5}, {"p[0]": 1})])])
    _reference(gen, [("SwUTC_1", "void f( U16 *p, U8 a )", ["a"], ["g"], [(1, {"a": 5}, {"g": 6})])])
    (rec,) = evaluate(str(ref), str(gen), [root], None, derived_only=False)["functions"]
    assert rec["suite_slots"] == {"reference": 1, "generated": 0}
    assert not rec["results"].get("killed_by_generated")


def test_a_column_no_suite_states_does_not_decide_equivalence(tmp_path):
    # (R81 review W-R2-1) a row computes every column it has (to set its harness up) — a mutant that changes only a
    #   column no suite states a value for (`h`: the reference wrote a text) is not "distinguished"
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text('#include "common.h"\nU8 g;\nU8 h;\nvoid f(U8 a) { g = a; h = (U8)(a + 3U); }\n',
                                 encoding="utf-8", newline="\n")
    ref, gen = tmp_path / "ref.xlsm", tmp_path / "gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( U8 a )", ["a"], ["g", "h"], [(1, {"a": 5}, {"g": 5, "h": "변화"})])])
    _reference(gen, [("SwUTC_1", "void f( U8 a )", ["a"], ["g"], [(1, {"a": 5}, {"g": 5})])])
    (rec,) = evaluate(str(ref), str(gen), [root], None, derived_only=False, sample=0)["functions"]
    assert not rec["results"].get("distinguished")


def test_a_row_observing_its_pointer_output_cell_runs_with_the_pointee(tmp_path):
    # (R81 review W-R3-1) the generated row's `[검증 필요] pointer_value` cell for `p` is an observation: the row runs
    #   with `p`'s pointee set up, as the generator derived `g` — so `g` reproduces and counts
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text('#include "common.h"\nU8 g;\n'
                                 "void f(U16 *p, U8 a) { if (p != 0) { *p = 1U; g = a; } }\n",
                                 encoding="utf-8", newline="\n")
    ref, gen = tmp_path / "ref.xlsm", tmp_path / "gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( U16 *p, U8 a )", ["a"], ["p[0]"], [(1, {"a": 5}, {"p[0]": 1})])])
    _reference(gen, [("SwUTC_1", "void f( U16 *p, U8 a )", ["a"], ["p", "g"],
                      [(1, {"a": 5}, {"p": "[검증 필요] pointer_value", "g": 5})])])
    (rec,) = evaluate(str(ref), str(gen), [root], None, derived_only=False, sample=0)["functions"]
    assert rec["suite_slots"]["generated"] == 1
