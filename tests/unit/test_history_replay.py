"""R24 (G1 b) — historical change replay (`scripts/history_replay.py`).

A VectorCAST aggregate coverage report lists the unit's code as it was tested; two runs give an older and a newer body
of every changed function. Each pair is replayed on the current source: a suite detects the change when a value it
states passes on the newer body and fails on the older one. A change is a documented fix only through quoted evidence.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from history_replay import (  # noqa: E402
    UNREAD,
    changed_functions,
    evaluate,
    listing_functions,
    listing_units,
    main,
)
from test_reference_alignment import COMMON, _reference  # noqa: E402

NEW_F = "void f( void )\n{\n  if( g_i >= 10U )\n  {\n    g_o = 1U;\n  }\n  else\n  {\n    g_o = 0U;\n  }\n}"
OLD_F = NEW_F.replace(">=", ">")                     # the older code: the threshold itself went the other way
REFACTOR_F = NEW_F.replace("if( g_i >= 10U )", "if( ( g_i >= 10U ) )")
HEADER = '#include "common.h"\nU8 g_i;\nU8 g_o;\nU8 g_p;\nU8 g_q;\nU8 g_arr[3];\nU8 *g_ptr;\nU8 h( void );\n'


def _report(unit: str, body_lines: list[tuple[str, str]], vc2025: bool = False) -> str:
    """An aggregate coverage report: ``body_lines`` = [(prefix, code)] — prefix ``""`` for an uncovered line."""
    spans = []
    for number, (prefix, code) in enumerate(body_lines, start=1):
        cls = "full-cvg success-marker" if prefix else "na-cvg"
        content = html.escape(prefix.ljust(15) + code)
        if vc2025:
            content = f"<strong>{str(number).rjust(6)}</strong> " + content
        spans.append(f'<span class="{cls}">{content}</span>')
    return (f"<html><body><h3>Code Coverage for {unit}</h3><table><tr><th>Unit</th><td>{unit}</td></tr></table>"
            '<pre class="aggregate-coverage">' + "\n".join(spans) + "</pre></body></html>")


def _lines(body: str, name: str = "f") -> list[tuple[str, str]]:
    """Every line uncovered, with the function entry marker after the opening brace (as VectorCAST lists it)."""
    out = [("", "U8 g_i;"), ("", "U8 g_o;")]
    for i, line in enumerate(body.split("\n")):
        out.append(("", line))
        if i == 1:
            out.append(("1 0     (T)", name))
    return out


# ── listing ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_both_report_layouts_list_the_same_code_without_the_coverage_columns():
    lines = [("", "#include \"common.h\""), ("", "void f( void )"), ("", "{"), ("1 0     (T)", "f"),
             ("1 1     (T)(F)", "if( g_i > 10U ) { g_o = 1U; }"), ("1 2      *", "g_o = 2U;"), ("", "}")]
    old_layout = listing_units(_report("unit", lines))
    new_layout = listing_units(_report("unit", lines, vc2025=True))
    assert old_layout == new_layout
    text = old_layout["unit"]
    assert "if( g_i > 10U )" in text and "g_o = 2U;" in text
    assert "(T)" not in text and "\nf\n" not in text          # markers and the function entry line are not code


def test_an_outcome_the_run_did_not_reach_is_a_mark_too():
    # review C1: ``( )`` is how a report marks an uncovered outcome — ``( )(F)``, ``(T)( )``, ``( )( )`` and a ``( )``
    # entry line; code that starts with ``(`` (a cast, a register access) is code
    lines = [("", "void f( void )"), ("", "{"), ("4 0     ( )", "f"),
             ("14 11   ( )(F)", "while( g_i < 3U );"), ("12 2    (T)( )", "if( g_o == 0x5AU )"),
             ("4 9     ( )( )", "while( g_p == 1U );"), ("2 10", "(void)g_q;"), ("5 10", "((g_p) = (U8)(0x20U));"),
             ("", "}")]
    text = listing_units(_report("unit", lines, vc2025=True))["unit"]
    body = [ln.strip() for ln in text.split("\n") if ln.strip()]
    assert body == ["void f( void )", "{", "while( g_i < 3U );", "if( g_o == 0x5AU )", "while( g_p == 1U );",
                    "(void)g_q;", "((g_p) = (U8)(0x20U));", "}"]
    assert UNREAD not in text


def test_a_mark_the_layout_does_not_know_is_never_compared(tmp_path):
    for d, mark in (("old", "(T)(F)"), ("new", "1 3     (TT)")):
        (tmp_path / d).mkdir()
        body = _lines(NEW_F)
        body[5] = ((mark if d == "new" else "1 1     " + mark), "if( g_i >= 10U )")
        (tmp_path / d / "r.html").write_text(_report("unit", body), encoding="utf-8")
    new, stats = listing_functions(tmp_path / "new")
    assert UNREAD in new[("unit", "f")] and stats["residue_lines"] == 1
    assert stats["unparsed_functions"] == [("unit", "f")]
    old, old_stats = listing_functions(tmp_path / "old")
    assert old_stats["unparsed_functions"] == [] and old_stats["residue_lines"] == 0


def test_a_column_wider_than_the_fixed_layout_is_still_cut_at_the_code():
    text = listing_units(_report("unit", [("1234 5678 (T)(F)", "if( a ) { b = 1U; }")]))["unit"]
    assert text.strip() == "if( a ) { b = 1U; }"


def test_changed_added_and_removed_functions_between_two_logs(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "a.html").write_text(_report("unit", _lines(OLD_F) + [("", "void gone( void ) { }")]), encoding="utf-8")
    (old_dir / "b.html").write_text(_report("dropped_unit", [("", "void k( void ) { }")]), encoding="utf-8")
    (new_dir / "a.html").write_text(_report("unit", _lines(NEW_F + "\n/* note */") + [("", "void h( void ) { }")]),
                                    encoding="utf-8")
    (new_dir / "other.html").write_text("<html>no listing</html>", encoding="utf-8")
    (old, _s1), (new, _s2) = listing_functions(old_dir), listing_functions(new_dir)
    assert set(old) == {("unit", "f"), ("unit", "gone"), ("dropped_unit", "k")}
    assert set(new) == {("unit", "f"), ("unit", "h")}
    # review I1: a unit the newer run does not list is not code removed
    assert changed_functions(old, new) == {"changed": [("unit", "f")], "added": [("unit", "h")],
                                           "removed": [("unit", "gone")], "units_only_old": ["dropped_unit"],
                                           "units_only_new": []}
    # comments and white space are not a change
    same = {("unit", "f"): NEW_F.replace("\n", " ") + " // x"}
    assert changed_functions({("unit", "f"): NEW_F}, same)["changed"] == []


def test_a_unit_two_reports_list_differently_is_ambiguous_not_first_wins(tmp_path):
    # review W3: an application's and a boot loader's ``EEPROM`` in one run — which body is compared would be decided
    # by file order alone
    d = tmp_path / "log"
    d.mkdir()
    (d / "a.html").write_text(_report("unit", _lines(NEW_F) + [("", "void same( void ) { }")]), encoding="utf-8")
    (d / "b.html").write_text(_report("unit", _lines(OLD_F) + [("", "void same( void ) { }")]), encoding="utf-8")
    _functions, stats = listing_functions(d)
    assert stats["units_in_several_reports"] == ["unit"] and stats["ambiguous_functions"] == [("unit", "f")]


# ── replay ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "common.h").write_text(COMMON, encoding="utf-8", newline="\n")
    (root / "unit.c").write_text(HEADER + NEW_F + "\n", encoding="utf-8", newline="\n")
    ref, gen = tmp_path / "docs" / "ref.xlsm", tmp_path / "gen.xlsm"
    ref.parent.mkdir()
    # the reference tests the threshold (10); the "generated" suite only far values (0, 200)
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"],
                      [(1, {"g_i": 10}, {"g_o": 1}), (2, {"g_i": 0}, {"g_o": 0})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"],
                      [(1, {"g_i": 0}, {"g_o": 0}), (2, {"g_i": 200}, {"g_o": 1})])])
    alignment = {"functions": [{"function": "f", "status": "aligned", "source_path": str((root / "unit.c").resolve())}]}
    return root, ref, gen, alignment


def _logs(tmp_path, old_body, new_body, unit="unit"):
    old_dir, new_dir = tmp_path / "log_old", tmp_path / "log_new"
    for d, body in ((old_dir, old_body), (new_dir, new_body)):
        d.mkdir(parents=True, exist_ok=True)
        (d / "r.html").write_text(_report(unit, _lines(body)), encoding="utf-8")
    return old_dir, new_dir


def _replay(tmp_path, project, old_body, new_body, **kw):
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, old_body, new_body)
    report = evaluate(str(kw.pop("ref", ref)), str(kw.pop("gen", gen)), [root], alignment, old_dir, new_dir,
                      derived_only=False, **kw)
    return report, report["functions"][0]


def test_a_suite_detects_a_change_only_when_it_fails_before_and_passes_after(tmp_path, project):
    report, rec = _replay(tmp_path, project, OLD_F, NEW_F)
    assert rec["status"] == "replayed" and rec["distinguished"] and rec["current_equals_new"] is True
    assert not rec["distinguished_only_on_unstated"]
    # g_i == 10: 1 after the change, 0 before — only the reference states a value there
    assert rec["reference"]["detects"] and rec["reference"]["examples"][0] == {"case": 1, "slot": "g_o", "expected": 1,
                                                                             "before": 0}
    assert not rec["generated"]["detects"] and rec["generated"]["slots_passing_after"] == 2
    s = report["summary"]
    assert s["replayed"] == 1 and s["detected_by_reference"] == 1 and s["detected_by_generated"] == 0
    assert s["only_reference"] == 1 and s["only_generated"] == 0 and s["current_differs_from_new"] == 0
    assert s["missed_by_both"] == 0 and s["undecided"] == 0 and s["no_suite"] == 0     # review I7: zeros are reported


def test_a_change_only_the_sample_separates_is_replayed_and_missed_by_both(tmp_path, project):
    # review W5 M2: the status follows "distinguished", not "detected" — neither suite has a value between 10 and 199
    root, _ref, _gen, alignment = project
    ref, gen = tmp_path / "docs" / "far_ref.xlsm", tmp_path / "far_gen.xlsm"
    for path in (ref, gen):
        _reference(path, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0}),
                                                                           (2, {"g_i": 255}, {"g_o": 1})])])
    report, rec = _replay(tmp_path, project, NEW_F.replace("10U", "200U"), NEW_F, ref=ref, gen=gen)
    assert rec["status"] == "replayed" and rec["distinguished"] and not rec["separated_on_suite_inputs"]
    assert rec["reference"]["verdict"] == rec["generated"]["verdict"] == "missed"
    assert report["summary"]["missed_by_both"] == 1 and report["summary"]["separated_on_suite_inputs"] == 0


def test_an_undetermined_old_value_is_never_a_failure_before(tmp_path, project):
    # review W5 M1: the older body reads g_q, which no suite vector sets — at the suites' vectors its g_o is unknown,
    # not "different"; only the sample (which sets g_q) separates the pair
    old = NEW_F.replace("g_o = 1U;", "g_o = g_q;")
    report, rec = _replay(tmp_path, project, old, NEW_F)
    assert rec["status"] == "replayed" and not rec["separated_on_suite_inputs"]
    assert not rec["reference"]["detects"] and not rec["generated"]["detects"]
    # review r2 C: the suites state g_o where the older value is unknown — not a miss either
    assert rec["reference"]["verdict"] == "undetermined" and rec["generated"]["verdict"] == "undetermined"
    s = report["summary"]
    assert s["missed_by_both"] == 0 and s["undetermined_reference"] == 1 and s["undetermined_generated"] == 1
    assert rec["distinguishing_example"]["vector"].startswith("sample#") and rec["distinguishing_example"]["slot"] == "g_o"


def test_a_change_on_an_output_no_suite_states_is_distinguished_and_missed(tmp_path, project):
    # review W2: g_p = 5U → 6U touches nothing the suites state — "undecided" would call it possibly equivalent
    new = NEW_F.replace("g_o = 0U;", "g_o = 0U; g_p = 6U;")
    report, rec = _replay(tmp_path, project, new.replace("6U", "5U"), new)
    assert rec["status"] == "replayed" and rec["distinguished_only_on_unstated"]
    assert rec["slots"] == {"stated": 1, "written_only": 1}
    assert not rec["reference"]["detects"] and not rec["generated"]["detects"]
    assert report["summary"]["distinguished_only_on_unstated"] == 1 and report["summary"]["missed_by_both"] == 1


def test_an_equivalent_change_is_undecided_never_a_miss(tmp_path, project):
    report, rec = _replay(tmp_path, project, REFACTOR_F, NEW_F)
    assert rec["status"] == "undecided" and not rec["distinguished"] and rec["compared_slots"] > 0
    assert report["summary"]["detected_by_reference"] == 0 and report["summary"]["undecided"] == 1


def test_two_bodies_that_never_determine_the_same_slot_are_not_comparable(tmp_path, project):
    # review W4: nothing was compared — that is not "may be equivalent". (An object a body does not write keeps its
    # value — determined; an unknown callee may write anything, so only what is assigned after it is determined.)
    new = "void f( void )\n{\n  g_o = h();\n  g_p = 1U;\n}"
    old = "void f( void )\n{\n  g_p = h();\n  g_o = 1U;\n}"
    _report_, rec = _replay(tmp_path, project, old, new)
    assert rec["status"] == "not_comparable" and rec["compared_slots"] == 0
    assert rec["determined"]["new"] > 0 and rec["determined"]["old"] > 0


def test_current_equals_new_is_none_when_nothing_is_compared(tmp_path, project):
    # review W1: the current body determines only g_o, the newer listing only g_p — no common slot is no evidence of
    # equality (the pair itself still differs on g_p, which no suite states)
    root = project[0]
    (root / "unit.c").write_text(HEADER + "void f( void )\n{\n  g_p = h();\n  g_o = 1U;\n}\n",
                                 encoding="utf-8", newline="\n")
    new = "void f( void )\n{\n  g_o = h();\n  g_p = 1U;\n}"
    report, rec = _replay(tmp_path, project, new.replace("g_p = 1U", "g_p = 2U"), new)
    assert rec["current_equals_new"] is None and rec["current_new_compared_slots"] == 0
    assert rec["current_only_determined"] > 0 and rec["status"] == "replayed"
    assert report["summary"]["current_differs_from_new"] == 0


def test_a_body_that_determines_nothing_is_not_replayable_not_undecided(tmp_path, project):
    # the older code read a global the current code removed: nothing it computes is determined — a pair the current
    # code cannot run, not "the bodies may be equivalent"
    report, rec = _replay(tmp_path, project, NEW_F.replace("g_i", "g_removed"), NEW_F)
    assert rec["status"] == "not_replayable" and rec["reason"] == "old_body_determines_no_output"
    assert rec["determined"]["old"] == 0 and rec["determined"]["new"] > 0 and rec["oracle_reasons"]
    assert "reference" not in rec and report["summary"]["not_replayable_reasons"] == {"old_body_determines_no_output": 1}
    # the newer side the same way (the listing's form may be what the oracle refuses)
    _r2, rec2 = _replay(tmp_path / "b", project, NEW_F, "void f( void )\n{\n  g_o = h();\n}")
    assert rec2["status"] == "not_replayable" and rec2["reason"] == "new_body_determines_no_output"


def test_nothing_determined_anywhere_is_not_replayable(tmp_path, project):
    # review W4 / W5 M3: current, newer and older all return an unknown callee's value
    root, ref, gen, alignment = project
    (root / "unit.c").write_text(HEADER + "void f( void )\n{\n  g_o = h();\n}\n", encoding="utf-8", newline="\n")
    _report_, rec = _replay(tmp_path, project, "void f( void )\n{\n  g_o = (U8)(h() + 1U);\n}",
                            "void f( void )\n{\n  g_o = h();\n}")
    assert rec["status"] == "not_replayable" and rec["reason"] == "no_body_determines_output"


def test_the_suites_are_judged_on_the_newer_body_and_a_later_change_is_marked(tmp_path, project):
    # the current code moved on after the newer log (threshold 20): the pair is still the logs' pair
    root, ref, gen, alignment = project
    (root / "unit.c").write_text(HEADER + NEW_F.replace("10U", "20U") + "\n", encoding="utf-8", newline="\n")
    report, rec = _replay(tmp_path, project, OLD_F, NEW_F)
    assert rec["status"] == "replayed" and rec["current_equals_new"] is False
    assert rec["reference"]["detects"] and report["summary"]["current_differs_from_new"] == 1


def test_a_calibration_change_is_flagged_literal_only_and_sampled_at_the_constants(tmp_path, project):
    # review I2: "changed" is the macro-expanded text — a value that came in through a macro is a change too; review r2:
    # the random sample rarely lands between 10 and 12, so the changed literals ±1 are vectors as well
    root, _ref, _gen, alignment = project
    ref, gen = tmp_path / "docs" / "far_ref.xlsm", tmp_path / "far_gen.xlsm"
    for path in (ref, gen):
        _reference(path, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0})])])
    report, rec = _replay(tmp_path, project, NEW_F.replace("10U", "12U"), NEW_F, ref=ref, gen=gen, sample=0)
    assert rec["literal_only"] is True and report["summary"]["literal_only"] == 1
    assert rec["literal_vectors"] == 6 and rec["status"] == "replayed"          # 10±1 and 12±1 separate the pair
    _r2, rec2 = _replay(tmp_path / "b", project, OLD_F, NEW_F)
    assert "literal_only" not in rec2


def test_an_array_element_write_is_a_slot_and_a_local_is_not(tmp_path, project):
    # review r2 W2: ``g_arr[1]`` is observed (constant index, through parentheses); a local ``t`` never is
    new = NEW_F.replace("{\n  if", "{\n  U8 t;\n  t = 0U;\n  (g_arr[1]) = 1U;\n  if", 1)
    report, rec = _replay(tmp_path, project, new.replace("(g_arr[1]) = 1U", "(g_arr[1]) = 2U"), new)
    assert rec["status"] == "replayed" and rec["distinguished_only_on_unstated"]
    assert rec["slots"] == {"stated": 1, "written_only": 1} and rec["distinguishing_example"]["slot"] == "g_arr[1]"
    _r2, rec2 = _replay(tmp_path / "b", project, new.replace("t = 0U", "t = g_i"), new)
    assert rec2["status"] == "undecided" and rec2["slots"]["written_only"] == 1          # g_arr[1] only, never t
    # review r3 W3: only a number changed, and no vector could reach it (an unused local) — not "maybe equivalent"
    _r3, rec3 = _replay(tmp_path / "c", project, new.replace("t = 0U", "t = 1U"), new)
    assert rec3["status"] == "calibration_not_reached" and rec3["reference"]["verdict"] is None


def test_a_difference_in_writes_the_oracle_does_not_observe_is_not_undecided(tmp_path, project):
    # review r2 W2: a pointer write differs — the pair is not "maybe equivalent"
    new = NEW_F.replace("{\n  if", "{\n  *g_ptr = 1U;\n  if", 1)
    _report_, rec = _replay(tmp_path, project, new.replace("*g_ptr = 1U", "*g_ptr = 2U"), new)
    assert rec["unobserved_write_difference"] and rec["status"] == "unobserved_difference"


def test_a_changed_parameter_list_is_not_run(tmp_path, project):
    report, rec = _replay(tmp_path, project, NEW_F.replace("void f( void )", "void f( U8 x )"), NEW_F)
    assert rec["status"] == "signature_changed" and rec["signature_change"] == "types"
    assert rec["params"] == {"new": [], "old": ["U8 x"]} and report["summary"]["signature_changed"] == 1
    # review r3 Info: only the parameter's name changed — reported apart (its inputs would bind to nothing)
    _r2, rec2 = _replay(tmp_path / "b", project, NEW_F.replace("void f( void )", "void f( U8 y )"),
                        NEW_F.replace("void f( void )", "void f( U8 /* in */ x )"))
    assert rec2["status"] == "signature_changed" and rec2["signature_change"] == "rename"


def test_a_harness_error_is_recorded_per_function(tmp_path, project, monkeypatch):
    # review I4: a failure inside one function's replay is that function's record, and the run goes on
    from generators import c_source_oracle

    def boom(*_a, **_k):
        raise TypeError("probe")
    monkeypatch.setattr(c_source_oracle, "evaluate_outputs", boom)
    report, rec = _replay(tmp_path, project, OLD_F, NEW_F)
    assert rec["status"] == "not_replayable" and rec["reason"].startswith("harness_error:TypeError")
    assert report["summary"]["not_replayable_reasons"] == {"harness_error": 1}


def test_neither_listed_body_determining_anything_names_both(tmp_path, project):
    # review r2 M28: the current body is determined, neither listed body is
    _report_, rec = _replay(tmp_path, project, "void f( void )\n{\n  g_o = (U8)(h() + 1U);\n}",
                            "void f( void )\n{\n  g_o = h();\n}")
    assert rec["status"] == "not_replayable" and rec["reason"] == "neither_body_determines_output"


def test_a_stmt_zero_line_with_code_is_code_and_a_mark_after_the_columns_is_residue():
    # review I6: only "<n> 0 <mark> <identifier>" is the entry line; review r2 M30: a leftover mark is found on the
    # fixed-column path too, and ``(U8)`` / ``(void)`` at the start of code are not marks
    text = listing_units(_report("unit", [("3 0     (T)", "g_o = 1U;"), ("2 10", "(U8)g_q;"),
                                          ("1234 567 (T)(F)(T)  ", "x = 1U;")]))["unit"]
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert lines[0].strip() == "g_o = 1U;" and lines[1].strip() == "(U8)g_q;"
    assert lines[2].startswith(UNREAD)


def test_a_documented_fix_comes_only_from_quoted_evidence(tmp_path, project):
    evidence = {"functions": {"f": [{"document": "Problem List", "id": "TDL_1", "quote": "threshold fixed"}],
                              "not_changed": [{"document": "Release Sheet", "id": "-", "quote": "x"}]}}
    report, rec = _replay(tmp_path, project, OLD_F, NEW_F, evidence=evidence)
    assert rec["documented_fix"][0]["id"] == "TDL_1"
    d = report["documented_fixes"]
    assert d["changes"] == 1 and d["replayed"] == 1 and d["detected_by_reference"] == 1 and d["detected_by_generated"] == 0
    assert d["evidence_functions_not_changed_here"] == ["not_changed"]
    plain, rec2 = _replay(tmp_path / "b", project, OLD_F, NEW_F)
    assert "documented_fix" not in rec2 and plain["documented_fixes"]["changes"] == 0


def test_a_listing_of_another_unit_or_an_unaligned_function_is_not_replayed(tmp_path, project):
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F, unit="other_unit")
    report = evaluate(str(ref), str(gen), [root], alignment, old_dir, new_dir, derived_only=False)
    assert report["functions"][0]["status"] == "unit_mismatch"
    report = evaluate(str(ref), str(gen), [root], {"functions": []}, old_dir, new_dir, derived_only=False)
    assert report["functions"][0]["status"] == "no_suite"


def test_a_name_two_units_define_is_ambiguous(tmp_path, project):
    # review W5 M4: ``f`` in two units of the listing — which body belongs to the suites' ``f`` is not decidable
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    for d, body in ((old_dir, OLD_F), (new_dir, NEW_F)):
        (d / "other.html").write_text(_report("other_unit", _lines(body)), encoding="utf-8")
    report = evaluate(str(ref), str(gen), [root], alignment, old_dir, new_dir, derived_only=False)
    assert [r["status"] for r in report["functions"]] == ["ambiguous_name", "ambiguous_name"]
    # a suite that names two units alike is ambiguous the same way
    report = evaluate(str(ref), str(gen), [root], {**alignment, "summary": {"duplicate_reference_names": ["f"]}},
                      *_logs(tmp_path / "c", OLD_F, NEW_F), derived_only=False)
    assert report["functions"][0]["status"] == "ambiguous_name"


def test_an_ambiguous_or_unread_listing_is_never_compared(tmp_path, project):
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    (new_dir / "second.html").write_text(_report("unit", _lines(REFACTOR_F.replace("10U", "11U"))), encoding="utf-8")
    report = evaluate(str(ref), str(gen), [root], alignment, old_dir, new_dir, derived_only=False)
    assert report["functions"][0]["status"] == "ambiguous_listing"
    assert report["listing"]["new"]["ambiguous_functions"] == [["unit", "f"]] or \
        report["listing"]["new"]["ambiguous_functions"] == [("unit", "f")]
    old_dir2, new_dir2 = _logs(tmp_path / "u", OLD_F, NEW_F)
    body = _lines(NEW_F)
    body[5] = ("1 3     (TT)", "if( g_i >= 10U )")
    (new_dir2 / "r.html").write_text(_report("unit", body), encoding="utf-8")
    report = evaluate(str(ref), str(gen), [root], alignment, old_dir2, new_dir2, derived_only=False)
    assert report["functions"][0]["status"] == "listing_unparsed"


def test_the_report_is_never_written_into_a_log_or_over_an_input(tmp_path, project):
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    align_path = tmp_path / "align.json"
    align_path.write_text(json.dumps(alignment), encoding="utf-8")
    base = ["--old-log", str(old_dir), "--new-log", str(new_dir), "--reference", str(ref), "--generated", str(gen),
            "--source-root", str(root), "--alignment", str(align_path)]
    with pytest.raises(SystemExit, match="log folder"):
        main(base + ["--out", str(new_dir / "replay.json")])
    with pytest.raises(SystemExit, match="input of this run"):
        main(base + ["--out", str(align_path)])
    out = tmp_path / "out" / "replay.json"
    out.parent.mkdir()
    assert main(base + ["--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["changes"] == 1
    assert [p.name for p in out.parent.iterdir()] == ["replay.json"]       # review I7: no partial file left behind


def test_a_spliced_body_is_judged_in_the_same_context_as_the_current_one(tmp_path, project, monkeypatch):
    # what the loader adds after building (the files it could not read) decides whether an unresolved include is the
    # toolchain's; the rebuilt context of a spliced body must keep it, or the two bodies run under different rules
    import reference_alignment

    from generators import c_project_context as cpc
    real_load, real_scopes = reference_alignment._load_source, cpc.build_scopes
    seen = []

    def load(roots):
        texts, context, unread = real_load(roots)
        context["incomplete_files"] = ["unreadable.h"]
        return texts, context, unread

    def scopes(context, paths):
        seen.append(context.get("incomplete_files"))
        return real_scopes(context, paths)
    monkeypatch.setattr(reference_alignment, "_load_source", load)
    monkeypatch.setattr(cpc, "build_scopes", scopes)
    _report_, rec = _replay(tmp_path, project, OLD_F, NEW_F)
    assert rec["status"] == "replayed"
    assert len(seen) == 3 and all(s == ["unreadable.h"] for s in seen)   # current, newer, older


def test_a_report_that_lists_no_code_is_counted_not_silently_dropped(tmp_path):
    # a unit the run did not instrument has a report but no listing: its functions are simply absent from that log
    d = tmp_path / "log"
    d.mkdir()
    (d / "a.html").write_text(_report("unit", _lines(NEW_F)), encoding="utf-8")
    (d / "b.html").write_text('<style>pre.aggregate-coverage {}</style><h3>Code Coverage for other</h3>'
                              "<p>File Is Not Instrumented For Coverage.</p>", encoding="utf-8")
    _functions, stats = listing_functions(d)
    assert stats["reports"] == 2 and stats["reports_without_listing"] == ["b.html"] and stats["units"] == 1


def test_an_unread_listing_is_reported_before_any_other_status(tmp_path, project):
    # review r2 M33: the order of the checks is part of the contract — an unread body is never compared or excused
    root, ref, gen, _alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    body = _lines(NEW_F)
    body[5] = ("1 3     (TT)", "if( g_i >= 10U )")
    (new_dir / "r.html").write_text(_report("unit", body), encoding="utf-8")
    report = evaluate(str(ref), str(gen), [root], {"functions": []}, old_dir, new_dir, derived_only=False)
    assert report["functions"][0]["status"] == "listing_unparsed"


def test_a_name_two_units_define_in_the_older_log_only_is_ambiguous(tmp_path, project):
    # review r2 M29: the name is counted over both logs
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    (old_dir / "other.html").write_text(_report("other_unit", _lines(OLD_F)), encoding="utf-8")
    report = evaluate(str(ref), str(gen), [root], alignment, old_dir, new_dir, derived_only=False)
    assert [r["status"] for r in report["functions"]] == ["ambiguous_name"]


def test_a_failed_write_leaves_no_partial_report(tmp_path, project, monkeypatch):
    # review r2: the temporary file is removed when the report cannot be written
    import history_replay
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    align_path = tmp_path / "align.json"
    align_path.write_text(json.dumps(alignment), encoding="utf-8")
    out = tmp_path / "out" / "replay.json"
    out.parent.mkdir()
    real = history_replay.json.dumps

    def failing(obj, *a, **k):
        if isinstance(obj, dict) and "functions" in obj:
            raise ValueError("probe")
        return real(obj, *a, **k)
    monkeypatch.setattr(history_replay.json, "dumps", failing)
    with pytest.raises(ValueError, match="probe"):
        main(["--old-log", str(old_dir), "--new-log", str(new_dir), "--reference", str(ref), "--generated", str(gen),
              "--source-root", str(root), "--alignment", str(align_path), "--out", str(out)])
    assert list(out.parent.iterdir()) == []


# ── review round 3 ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_enumerator_written_with_its_value_is_a_stated_value(tmp_path, project):
    # review r3 C1: KJPDS02 writes ``en_s_Buzzer_3_Flashing_Long(5)`` — dropping it turned a detection into a miss
    root, _ref, gen, _alignment = project
    (root / "unit.c").write_text(HEADER + "#define K_ONE 1U\n" + NEW_F + "\n", encoding="utf-8", newline="\n")
    ref = tmp_path / "docs" / "named_ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"],
                      [(1, {"g_i": "en_ten(10)"}, {"g_o": "en_on(1)"}), (2, {"g_i": 0}, {"g_o": "K_ONE(2)"})])])
    report, rec = _replay(tmp_path, project, OLD_F, NEW_F, ref=ref)
    assert rec["reference"]["verdict"] == "detected" and rec["reference"]["examples"][0]["expected"] == 1
    # review r4 I1: counted per suite and role — K_ONE is 1, not 2
    assert rec["suite_cells"]["reference_expected_named"] == 1 and rec["suite_cells"]["reference_inputs_named"] == 1
    assert rec["suite_cells"]["reference_expected_named_conflict"] == 1
    assert report["summary"]["suite_cells_reference_expected_named"] == 1


def test_an_unknown_older_value_on_any_stated_slot_is_undetermined_not_missed(tmp_path, project):
    # review r3 W1 case A: the pair separates only on g_p; the suites state g_o, which the older body leaves unknown
    new = NEW_F.replace("{\n  if", "{\n  g_p = 1U;\n  if", 1)
    old = "void f( void )\n{\n  g_o = h();\n  g_p = 2U;\n}"
    report, rec = _replay(tmp_path, project, old, new)
    assert rec["status"] == "replayed" and rec["distinguished_only_on_unstated"]
    assert rec["reference"]["verdict"] == rec["generated"]["verdict"] == "undetermined"
    assert report["summary"]["missed_by_both"] == 0


def test_a_known_failure_before_with_an_unknown_value_after_is_undetermined(tmp_path, project):
    # review r3 W1 case B: at the reference's g_i == 10 the newer g_o is unknown (it reads g_q, which the suite never
    # sets) and the older one is 0, not the stated 1 — a failure before whose "pass after" cannot be shown
    new = NEW_F.replace("g_o = 1U;", "g_o = g_q;")
    _report_, rec = _replay(tmp_path, project, OLD_F, new)
    assert rec["status"] == "replayed" and rec["reference"]["verdict"] == "undetermined"


def test_a_failure_wins_over_an_unknown_value_in_the_verdict(tmp_path, project):
    # review r3 N1: one stated slot fails before (g_p), another is unknown before (g_o) — the suite detects the change
    root, _ref, gen, _alignment = project
    ref = tmp_path / "docs" / "two_ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o", "g_p"], [(1, {"g_i": 10}, {"g_o": 1, "g_p": 1})])])
    new = NEW_F.replace("{\n  if", "{\n  g_p = 1U;\n  if", 1)
    old = "void f( void )\n{\n  g_p = 2U;\n  g_o = g_q;\n}"
    _report_, rec = _replay(tmp_path, project, old, new, ref=ref)
    assert rec["reference"]["verdict"] == "detected" and rec["reference"]["slots_unknown"] >= 1


def test_a_separated_pair_with_an_unobserved_difference_too_is_replayed(tmp_path, project):
    # review r3 N5: "unobserved difference" only replaces "undecided", never a pair the vectors separate
    new = NEW_F.replace("{\n  if", "{\n  *g_ptr = 1U;\n  if", 1)
    old = OLD_F.replace("{\n  if", "{\n  *g_ptr = 2U;\n  if", 1)
    _report_, rec = _replay(tmp_path, project, old, new)
    assert rec["unobserved_write_difference"] and rec["status"] == "replayed"


def test_a_write_one_body_adds_that_is_never_compared_is_not_undecided(tmp_path, project):
    # review r3 W5: the newer body sets g_p from a pointer read the oracle does not model — g_p is never compared
    new = NEW_F.replace("{\n  if", "{\n  g_p = *g_ptr;\n  if", 1)
    _report_, rec = _replay(tmp_path, project, NEW_F, new)
    assert rec["status"] == "difference_not_compared" and rec["never_compared_writes"] == ["g_p"]


def test_the_example_names_the_suite_whose_vector_separated_the_pair(tmp_path, project):
    # review r3 N17 / N22: the reference's g_i == 0 does not separate, the generated g_i == 10 does
    root, _ref, _gen, _alignment = project
    ref, gen = tmp_path / "docs" / "zero_ref.xlsm", tmp_path / "ten_gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": 1})])])
    _report_, rec = _replay(tmp_path, project, OLD_F, NEW_F, ref=ref, gen=gen)
    assert rec["distinguishing_example"]["vector"] == "generated#1" and rec["separated_on_suite_inputs"]
    assert rec["distinguishing_example"]["inputs_total"] >= 1
    # only the first sample vector (every input at its minimum) separates this pair: not a suite's own vector
    far_ref, far_gen = tmp_path / "docs" / "far2_ref.xlsm", tmp_path / "far2_gen.xlsm"
    for path in (far_ref, far_gen):
        _reference(path, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 100}, {"g_o": 0})])])
    new = "void f( void )\n{\n  if( g_i == 0U )\n  {\n    g_o = 1U;\n  }\n  else\n  {\n    g_o = 0U;\n  }\n}"
    _r2, rec2 = _replay(tmp_path / "b", project, new.replace("== 0U", "== 7U"), new, ref=far_ref, gen=far_gen)
    assert rec2["status"] == "replayed" and not rec2["separated_on_suite_inputs"]
    assert rec2["distinguishing_example"]["vector"].startswith("sample#")


def test_body_facts_writes_and_locals():
    import history_replay as hr
    facts = hr._body_facts("void f( U8 x, void (*cb)( void ) )\n{\n  U8 a, b;\n  extern U8 g_e;\n  x = 1U;\n"
                           "  cb = 0;\n  b = 1U;\n  g_e = 2U;\n  g_p++;\n  g_arr[010] = 1U;\n"
                           "  g_arr[((U8)(0x02U))] = 3U;\n  g_arr[g_i] = 4U;\n  a++;\n}")
    # review r3 M19 / M19b / N13 / extern / function-pointer parameter / octal / a macro-expanded index
    assert facts["writes"] == {"g_e", "g_p", "g_arr[8]", "g_arr[2]"}
    assert facts["other_writes"] == {"g_arr[g_i]=4U"}
    assert facts["params"] == ["U8 x", "void (*cb)( void )"] and facts["param_types"] == ["U8 _", "void (*_)( void )"]
    # review r3 W4: a renamed loop index is not a difference in the unit's state
    a = hr._body_facts("void f( void )\n{\n  U8 i;\n  for( i = 0U; i < 2U; i++ ) { }\n}")
    b = hr._body_facts("void f( void )\n{\n  U8 u8t_HistoryIdx;\n  for( u8t_HistoryIdx = 0U; u8t_HistoryIdx < 2U; "
                       "u8t_HistoryIdx++ ) { }\n}")
    assert a["other_writes"] == b["other_writes"] == set() and a["writes"] == b["writes"] == set()


def test_changed_literals_and_their_vectors(project):
    # review r3 N23 / N16: hex literals are read; a vector never leaves an input's type
    import history_replay as hr

    from generators import c_project_context as cpc
    assert hr._changed_literals("x = 0x0AU;", "x = 0x0CU;") == [10, 12]
    root = project[0]
    files = {str(root / "common.h"): COMMON, str(root / "unit.c"): HEADER + NEW_F + "\n"}
    context = cpc.build_project_context(files)
    scope = cpc.build_scopes(context, [str(root / "unit.c")])[str(root / "unit.c")]
    assert hr._literal_vectors(["g_i", "h"], scope, {}, [300]) == [{"g_i": 255}] * 3


def test_a_whitespace_difference_between_two_reports_is_not_ambiguous_and_any_unread_one_is(tmp_path):
    # review r3 M26 / M32
    d = tmp_path / "log"
    d.mkdir()
    (d / "a.html").write_text(_report("unit", _lines(NEW_F)), encoding="utf-8")
    (d / "b.html").write_text(_report("unit", _lines(NEW_F.replace("if( g_i", "if(  g_i"))), encoding="utf-8")
    _functions, stats = listing_functions(d)
    assert stats["units_in_several_reports"] == ["unit"] and stats["ambiguous_functions"] == []
    body = _lines(NEW_F)
    body[5] = ("1 3     (TT)", "if( g_i >= 10U )")
    (d / "c.html").write_text(_report("unit", body), encoding="utf-8")
    _functions, stats = listing_functions(d)
    assert stats["unparsed_functions"] == [("unit", "f")]


def test_a_failed_replace_leaves_no_temporary_file(tmp_path, project, monkeypatch):
    # review r3 M25b: the temporary file exists when the rename fails — it is removed
    import history_replay
    root, ref, gen, alignment = project
    old_dir, new_dir = _logs(tmp_path, OLD_F, NEW_F)
    align_path = tmp_path / "align.json"
    align_path.write_text(json.dumps(alignment), encoding="utf-8")
    out = tmp_path / "out" / "replay.json"
    out.parent.mkdir()

    def refuse(*_a, **_k):
        raise OSError("probe")
    monkeypatch.setattr(history_replay.os, "replace", refuse)
    with pytest.raises(OSError, match="probe"):
        main(["--old-log", str(old_dir), "--new-log", str(new_dir), "--reference", str(ref), "--generated", str(gen),
              "--source-root", str(root), "--alignment", str(align_path), "--out", str(out)])
    assert list(out.parent.iterdir()) == []


def test_no_vector_at_all_is_not_replayable_not_a_crash(tmp_path, project):
    # review r3 Info: no suite case and no sample — nothing to compare, and no division by zero
    import history_replay as hr
    from reference_alignment import _load_source
    root = project[0]
    texts, context, _unread = _load_source([root])
    path = str((root / "unit.c").resolve())
    rec = hr.replay_function(texts, context, path, "f", "void f( void )\n{\n  g_o = g_q;\n}",
                             "void f( void )\n{\n  g_o = g_i;\n}", {}, sample=0)
    assert rec["status"] == "not_replayable" and rec["compared_share"] == 0 and rec["vectors"] == 0


def test_integer_literals_are_read_in_their_base():
    # a decimal ``10`` is ten, ``010`` is eight, ``0x10`` sixteen — found while tracing the named-value test
    import history_replay as hr
    assert [hr._int_literal(t) for t in ("10", "10U", "010", "0", "0x10", "0X1fUL", "08", "1.5")] == \
        [10, 10, 8, 0, 16, 31, None, None]


# ── review round 4 ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_stated_slot_neither_body_determines_is_undetermined(tmp_path, project):
    # review r4 W-A: at the suites' own inputs both bodies leave g_o unknown (it comes from g_q, which they never set);
    # only the sample separates the pair — neither suite "missed" it
    # (review r5 W2) both bodies read g_q at g_i >= 10: at the suites' own vectors neither determines g_o there
    new = NEW_F.replace("g_o = 1U;", "g_o = g_q;")
    old = NEW_F.replace("g_o = 1U;", "g_o = (U8)(g_q + 1U);")
    report, rec = _replay(tmp_path, project, old, new)
    assert rec["status"] == "replayed"
    assert rec["reference"]["verdict"] == rec["generated"]["verdict"] == "undetermined"
    assert report["summary"]["missed_by_both"] == 0


def test_an_unknown_after_value_with_a_passing_before_value_is_not_unknown(tmp_path, project):
    # review r4 N3c: after is unknown but before equals the stated value — nothing suggests a failure: missed, not unknown
    far_ref = tmp_path / "docs" / "one_ref.xlsm"
    _reference(far_ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0})])])
    new = NEW_F.replace("g_o = 0U;", "g_o = g_q;")            # after: unknown at g_i == 0 (g_q never set)
    old = NEW_F.replace(">=", ">")                              # before: 0 at g_i == 0, as stated
    _report_, rec = _replay(tmp_path, project, old, new, ref=far_ref, gen=far_ref)
    assert rec["status"] == "replayed" and rec["reference"]["slots_unknown"] == 0
    assert rec["reference"]["verdict"] == "missed"


def test_an_unreadable_cell_counts_only_where_its_own_case_does_not_show_the_bodies_equal(tmp_path, project):
    # review r4 W-C: the reference writes a register text at g_i == 0 where both bodies give 0 — that case cannot hide
    # a failure; "-" states no value at all
    ref, gen = tmp_path / "docs" / "text_ref.xlsm", tmp_path / "text_gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": "REG.Bits.P3"}),
                                                                       (2, {"g_i": 1}, {"g_o": "-"})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0})])])
    _report_, rec = _replay(tmp_path, project, NEW_F.replace("10U", "200U"), NEW_F, ref=ref, gen=gen)
    assert rec["status"] == "replayed" and rec["reference"]["verdict"] == "missed"
    assert rec["suite_cells"]["reference_expected_unreadable"] == 1 and rec["suite_cells"]["reference_expected_no_value"] == 1
    # the same text where the case itself separates the bodies (g_i == 50: 1 after, 0 before) is undetermined
    ref2 = tmp_path / "docs" / "text_ref2.xlsm"
    _reference(ref2, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 50}, {"g_o": "REG.Bits.P3"})])])
    _r2, rec2 = _replay(tmp_path / "b", project, NEW_F.replace("10U", "200U"), NEW_F, ref=ref2, gen=gen)
    assert rec2["reference"]["verdict"] == "undetermined"


def test_named_values_negative_and_function_like_macro():
    # review r4 I2: ``NAME(-3)`` is -3; ``MS(100)`` is a macro call, not an enumerator's value; ``NAME(08)`` unreadable
    import history_replay as hr
    assert hr._NAMED_VALUE.fullmatch("en_neg(-3)").group(2) == "-3"
    assert hr._int_literal("08") is None


def test_named_value_cells_through_a_replay(tmp_path, project):
    root = project[0]
    (root / "unit.c").write_text(HEADER + "#define MS(x) ((x) / 5U)\n" + NEW_F + "\n", encoding="utf-8",
                                 newline="\n")
    ref = tmp_path / "docs" / "cells_ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 10}, {"g_o": "MS(5)"}),
                                                                       (2, {"g_i": 0}, {"g_o": "en_z(-0)"}),
                                                                       (3, {"g_i": 0}, {"g_o": "en_x(08)"})])])
    _report_, rec = _replay(tmp_path, project, OLD_F, NEW_F, ref=ref)
    cells = rec["suite_cells"]
    assert cells.get("reference_expected_unreadable") == 2 and cells.get("reference_expected_named") == 1


def test_a_pointer_output_write_is_kept_and_a_renamed_local_index_is_not_a_difference():
    # review r4 W-B: ``*u16p_Peak = …`` (an output parameter) differs — reported; ``his[i-1]`` vs ``his[k-1]`` does not
    import history_replay as hr
    a = hr._body_facts("void f( U16 *p )\n{\n  *p = 1U;\n}")
    b = hr._body_facts("void f( U16 *p )\n{\n  *p = g_q;\n}")
    assert a["other_writes"] != b["other_writes"] and a["other_writes"] == {"*$L0=1U"}
    c = hr._body_facts("void f( void )\n{\n  U8 i;\n  for( i = 1U; i < 3U; i++ ) { g_arr[i - 1U] = 0U; }\n}")
    d = hr._body_facts("void f( void )\n{\n  U8 k;\n  for( k = 1U; k < 3U; k++ ) { g_arr[k - 1U] = 0U; }\n}")
    # (review r5 W1) the index's own assignments travel with the write that uses it — renamed alike
    assert c["other_writes"] == d["other_writes"] == {"g_arr[$L0-1U]=0U", "$L0=1U", "$L0++"}
    assert c["writes"] == d["writes"] == set()
    # a difference that reaches a member/pointer write only through a local's value is a difference (HD
    # ``s_DiagEepromRead``: the byte order computed into a local, then stored through a member)
    e = hr._body_facts("void f( void )\n{\n  U8 i;\n  i = g_q;\n  g_arr[i] = 0U;\n}")
    f = hr._body_facts("void f( void )\n{\n  U8 i;\n  i = g_i;\n  g_arr[i] = 0U;\n}")
    assert e["other_writes"] != f["other_writes"] and "$L0=g_q" in e["other_writes"]
    # a local that feeds nothing kept is still not the unit's state
    g = hr._body_facts("void f( void )\n{\n  U8 t;\n  t = 1U;\n  g_o = 0U;\n}")
    assert g["other_writes"] == set() and g["writes"] == {"g_o"}


def test_a_pointer_output_difference_is_an_unobserved_difference(tmp_path, project):
    # review r4 W-B: the write goes through a local pointer — kept (renamed), so the difference is reported
    new = NEW_F.replace("{\n  if", "{\n  U8 *p = g_ptr;\n  *p = 1U;\n  if", 1)
    _report_, rec = _replay(tmp_path, project, new.replace("*p = 1U", "*p = 2U"), new)
    assert rec["status"] == "unobserved_difference"


def test_a_function_level_static_is_the_units_state():
    # review r4 I5: a change in what a function-level ``static`` holds is reported, never dropped as a local's
    import history_replay as hr
    a = hr._body_facts("void f( void )\n{\n  static U8 s_cnt = 0U;\n  s_cnt = 1U;\n}")
    b = hr._body_facts("void f( void )\n{\n  static U8 s_cnt = 0U;\n  s_cnt = 2U;\n}")
    assert a["other_writes"] != b["other_writes"] and a["writes"] == set()


def test_pointer_spacing_is_not_a_signature_change():
    # review r4 I4
    import history_replay as hr
    a = hr._body_facts("void f( U8 *p )\n{\n}")
    b = hr._body_facts("void f( U8* p )\n{\n}")
    assert a["params"] == b["params"] == ["U8*p"] and a["param_types"] == ["U8*_"]


def test_an_operator_change_on_a_shared_literal_is_sampled_at_that_literal(tmp_path, project):
    # review r4 I3: ``>=`` → ``>`` keeps its literal 10; the vectors at 10±1 separate the pair even with far suites
    root, _ref, _gen, _alignment = project
    ref, gen = tmp_path / "docs" / "far3_ref.xlsm", tmp_path / "far3_gen.xlsm"
    for path in (ref, gen):
        _reference(path, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 200}, {"g_o": 1})])])
    _report_, rec = _replay(tmp_path, project, OLD_F, NEW_F, ref=ref, gen=gen, sample=0)
    assert rec["literal_vectors"] == 3 and rec["status"] == "replayed"


def test_writes_only_one_body_makes_that_are_compared_equal_stay_undecided(tmp_path, project):
    # review r4 W5b: the newer body adds ``g_p = 0U`` — g_p's starting value is sampled, and where both give 0 they
    # agree; where they differ the pair is separated — a compared write never becomes "difference_not_compared"
    new = NEW_F.replace("{\n  if", "{\n  g_p = g_p;\n  if", 1)
    _report_, rec = _replay(tmp_path, project, NEW_F, new)
    assert rec["status"] == "undecided" and "never_compared_writes" not in rec


def test_a_never_compared_write_wins_over_calibration(tmp_path, project):
    # review r4 P2 (made non-vacuous in r5): only a number changed — the element index — and neither written element is
    # ever determined (a pointer read): the unseen writes are named, not "calibration not reached"
    new = NEW_F.replace("{\n  if", "{\n  g_arr[1] = *g_ptr;\n  if", 1)
    old = new.replace("g_arr[1]", "g_arr[2]")
    _report_, rec = _replay(tmp_path, project, old, new)
    assert rec["literal_only"] and rec["status"] == "difference_not_compared"
    assert rec["never_compared_writes"] == ["g_arr[1]", "g_arr[2]"]


def test_a_negative_named_value_and_generated_cells_counted_under_generated(tmp_path, project):
    # review r5 C1f / I1: ``en_m(-1)`` is -1; a generated suite's named inputs are counted under "generated"
    root = project[0]
    (root / "unit.c").write_text(HEADER + "S16 g_s;\n" + NEW_F.replace("g_o = 1U;", "g_s = -1;") + "\n",
                                 encoding="utf-8", newline="\n")
    new = NEW_F.replace("g_o = 1U;", "g_s = -1;")
    ref = tmp_path / "docs" / "neg_ref.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i", "g_s"], ["g_s"],
                      [(1, {"g_i": 10, "g_s": 0}, {"g_s": "en_m(-1)"})])])
    gen = tmp_path / "named_gen.xlsm"
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": "en_ten(10)"}, {"g_o": 0})])])
    _report_, rec = _replay(tmp_path, project, new.replace(">=", ">"), new, ref=ref, gen=gen)
    assert rec["reference"]["verdict"] == "detected"
    assert rec["suite_cells"].get("generated_inputs_named") == 1 and "reference_inputs_named" not in rec["suite_cells"]


def test_a_no_value_cell_where_the_case_separates_is_not_unknown(tmp_path, project):
    # review r5 WC_no_value_unreadable: ``-`` states nothing — even where its case separates the bodies it is no
    # evidence either way (unlike an unreadable text)
    ref, gen = tmp_path / "docs" / "d_ref.xlsm", tmp_path / "d_gen.xlsm"
    _reference(ref, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 50}, {"g_o": "-"})])])
    _reference(gen, [("SwUTC_1", "void f( void )", ["g_i"], ["g_o"], [(1, {"g_i": 0}, {"g_o": 0})])])
    _report_, rec = _replay(tmp_path, project, NEW_F.replace("10U", "200U"), NEW_F, ref=ref, gen=gen)
    assert rec["reference"]["verdict"] == "missed"


def test_a_literal_after_a_keyword_is_read(tmp_path, project):
    # review r5 I2: ``return 10U`` / ``case 10U:`` — white space is dropped only to compare lines
    import history_replay as hr
    # unshared literals first (0, 1, 2), then the 10 on the changed ``return`` line — lost when read from ``return10U``
    assert hr._changed_literals("x = 1U;\nreturn 10U;", "x = 2U;\nreturn  10U + 0U;") == [0, 1, 2, 10]
