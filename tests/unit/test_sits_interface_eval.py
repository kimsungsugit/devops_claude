"""R8 (G5) — SITS interface-fault scoring (`scripts/sits_interface_eval.py`).

Both suites are judged by what they stimulate and observe, against faults read from the source: a used return value
that is not propagated (a test must inject that return with two values), a global write lost (a test must observe the
global), two same-type arguments swapped (a test must set both sources to different values).
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import sits_interface_eval as ev  # noqa: E402

LIN = """typedef unsigned char U8;
U8 g_lin_state;
U8 LinReady(void) { return g_lin_state; }
void LinSetup(U8 id, U8 len) { g_lin_state = (U8)(id + len); }
"""
APP = """typedef unsigned char U8;
extern U8 g_lin_state;
U8 g_app_out;
U8 g_id;
U8 g_len;
void AppStep(void) {
    if (LinReady() == 3U) { g_app_out = 2U; }
    LinSetup(g_id, g_len);
    g_app_out = g_lin_state;
}
"""


@pytest.fixture
def src(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "lin.c").write_text(LIN, encoding="utf-8", newline="\n")
    (root / "app.c").write_text(APP, encoding="utf-8", newline="\n")
    return root


def _sits(path: Path, sheet: str, tests, expected=0):
    """tests: [(tc_id, chain, inputs [names], expected [names], rows [{name: value}])]."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    header = [None] * 20
    header[7], header[14] = "Input", "Expected Result"
    ws.append(["Software Integration Test Spec"])
    ws.append(header)
    ws.append([None, "TC ID"])
    for tc_id, chain, inputs, expected_names, rows in tests:
        r = [None] * 22
        r[1] = tc_id
        for j, n in enumerate(inputs):
            r[7 + j] = n
        for j, n in enumerate(expected_names):
            r[14 + j] = n
        ws.append(r)
        for k, row in enumerate(rows):
            v = [None] * 22
            v[2], v[3] = k + 1, chain if k == 0 else None
            for j, n in enumerate(inputs):
                v[7 + j] = row.get(n)
            for j, _n in enumerate(expected_names):
                v[14 + j] = expected[k] if isinstance(expected, list) else expected
            ws.append(v)
    wb.save(path)
    return str(path)


def test_faults_come_from_the_source(src):
    from generators import c_project_context as cpc
    from generators.interface_contract import SourceIndex
    texts = {str(p): p.read_text(encoding="utf-8") for p in src.glob("*.c")}
    index = SourceIndex(texts, cpc.shared_parser())
    faults = ev.faults(index, ev.call_graph(index), {"g_lin_state", "g_app_out", "g_id", "g_len"})
    kinds = sorted((f["kind"], f.get("callee") or f.get("global")) for f in faults)
    assert kinds == [("arguments_swapped", "LinSetup"), ("global_write_lost", "g_lin_state"),
                     ("return_not_propagated", "LinReady")]


def test_a_return_is_told_apart_only_by_injecting_two_values(src, tmp_path):
    two = _sits(tmp_path / "two.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"],
         [{"LinReady() return": "3"}, {"LinReady() return": "4"}])])
    one = _sits(tmp_path / "one.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"],
         [{"LinReady() return": "3"}, {"LinReady() return": "3"}])])
    r = ev.evaluate([src], one, two)
    assert r["generated"]["by_kind"]["return_not_propagated"]["discriminated"] == 1
    assert r["reference"]["by_kind"]["return_not_propagated"]["discriminated"] == 0


def test_a_lost_global_write_is_told_apart_by_observing_the_global(src, tmp_path):
    seen = _sits(tmp_path / "seen.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinSetup", ["g_id"], ["g_lin_state"], [{"g_id": 1}])])
    blind = _sits(tmp_path / "blind.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinSetup", ["g_id"], ["g_app_out"], [{"g_id": 1}])])
    r = ev.evaluate([src], blind, seen)
    assert r["generated"]["by_kind"]["global_write_lost"]["discriminated"] == 1
    assert r["reference"]["by_kind"]["global_write_lost"]["discriminated"] == 0


def test_swapped_arguments_need_both_sources_set_differently(src, tmp_path):
    diff = _sits(tmp_path / "d.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep", ["g_id", "g_len"], ["g_app_out"], [{"g_id": 1, "g_len": 2}])])
    same = _sits(tmp_path / "s.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep", ["g_id", "g_len"], ["g_app_out"], [{"g_id": 1, "g_len": 1}])])
    r = ev.evaluate([src], same, diff)
    assert r["generated"]["by_kind"]["arguments_swapped"]["discriminated"] == 1
    assert r["reference"]["by_kind"]["arguments_swapped"]["discriminated"] == 0


def test_a_test_that_does_not_exercise_the_function_tells_nothing_apart(src, tmp_path):
    ref = _sits(tmp_path / "r.xlsx", "4.SW Integration Test Spec", [
        ("SwITC_01", "LinReady", ["LinReady() return"], ["g_lin_state"],
         [{"LinReady() return": "3"}, {"LinReady() return": "4"}])])
    r = ev.evaluate([src], ref)
    # LinReady's closure holds neither the caller (AppStep) nor the producer (LinSetup)
    assert r["reference"]["discriminated"] == 0 and set(r["reference"]["rate_by_rule"]) == {
        "first_closure", "last_closure_and_chain", "chain_only"}


def test_a_placeholder_expectation_tells_nothing_apart(src, tmp_path):
    # (review round 1 C1) ``[검증 필요]`` / ``—`` / N/A is not an expectation
    for placeholder in ("[검증 필요] callee_pointer_write", "—", "-", "N/A", "[검증 필요]\ncallee_pointer_write", "–",
                        "TBD"):
        path = tmp_path / f"p{abs(hash(placeholder))}.xlsx"
        gen = _sits(path, "3.SW Integration Test Spec", [
            ("SwITC_01", "AppStep -> LinSetup", ["g_id"], ["g_lin_state"], [{"g_id": 1}])], expected=placeholder)
        r = ev.evaluate([src], gen)
        assert r["reference"]["discriminated"] == 0 and r["reference"]["tests_with_concrete_expectation"] == 0


def test_both_suites_are_judged_by_the_same_rule(src, tmp_path):
    # (review C2) the same chain gives the same credit whichever workbook it is in
    rows = [{"LinReady() return": "3"}, {"LinReady() return": "4"}]
    a = _sits(tmp_path / "a.xlsx", "4.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"], rows)])
    b = _sits(tmp_path / "b.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"], rows)])
    r = ev.evaluate([src], a, b)
    assert r["reference"]["by_kind"] == r["generated"]["by_kind"]
    assert r["reference"]["rate_by_rule"] == r["generated"]["rate_by_rule"]


def test_a_workbook_without_the_spec_sheet_is_an_error(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Cover"
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(ValueError, match="no SITS spec sheet"):
        ev.read_sits(str(tmp_path / "x.xlsx"))


# ── deep review round 2 ──────────────────────────────────────────────

def test_the_expectation_gate_holds_for_injected_returns_and_swapped_arguments(src, tmp_path):
    """(m11) injecting two return values or setting two argument sources apart tells nothing without an expectation."""
    ret = _sits(tmp_path / "r.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"],
         [{"LinReady() return": "3"}, {"LinReady() return": "4"}])], expected="[검증 필요] x")
    swap = _sits(tmp_path / "s.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep", ["g_id", "g_len"], ["g_app_out"], [{"g_id": 1, "g_len": 2}])], expected="—")
    r = ev.evaluate([src], ret, swap)
    assert r["reference"]["by_kind"]["return_not_propagated"]["discriminated"] == 0
    assert r["generated"]["by_kind"]["arguments_swapped"]["discriminated"] == 0


def test_only_the_rows_with_an_expectation_count(src, tmp_path):
    """(m4) the two injected values must both sit in rows that write an expectation."""
    half = _sits(tmp_path / "h.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"],
         [{"LinReady() return": "3"}, {"LinReady() return": "4"}])], expected=["2", "[검증 필요] x"])
    both = _sits(tmp_path / "b.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinReady", ["LinReady() return"], ["g_app_out"],
         [{"LinReady() return": "3"}, {"LinReady() return": "4"}])], expected=["2", "0"])
    r = ev.evaluate([src], half, both)
    assert r["reference"]["by_kind"]["return_not_propagated"]["discriminated"] == 0
    assert r["generated"]["by_kind"]["return_not_propagated"]["discriminated"] == 1


def test_the_last_function_rule_also_credits_the_chain(src, tmp_path):
    """(m5) ``AppStep -> LinSetup``: LinSetup's closure lacks AppStep, the chain holds it."""
    t = _sits(tmp_path / "t.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep -> LinSetup", ["LinReady() return"], ["g_app_out"],
         [{"LinReady() return": "3"}, {"LinReady() return": "4"}])])
    rates = ev.evaluate([src], t)["reference"]["rate_by_rule"]
    assert rates["last_closure_and_chain"] == rates["chain_only"] == round(1 / 3, 4)


def test_an_unreadable_source_file_is_counted_and_the_inputs_are_recorded(src, tmp_path):
    (src / "latin.c").write_bytes("/* caf\xe9 */\nint z(void) { return 0; }\n".encode("latin-1"))
    ref = _sits(tmp_path / "r.xlsx", "3.SW Integration Test Spec", [
        ("SwITC_01", "AppStep", ["g_id"], ["g_app_out"], [{"g_id": 1}])])
    r = ev.evaluate([src], ref)
    assert [Path(p).name for p in r["unreadable_source_files"]] == ["latin.c"]
    assert r["reference_path"] == ref and r["generated_path"] is None


def test_the_generator_reads_every_root_and_counts_what_it_could_not_read(tmp_path):
    from generators.sits import _read_source_texts
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "x.c").write_text("int x;\n", encoding="utf-8")
    (b / "y.h").write_text("int y;\n", encoding="utf-8")
    (b / "z.c").write_bytes(b"\xff\xfe")
    texts, unread = _read_source_texts(f"{a};{b},{tmp_path / 'missing'}")
    assert sorted(Path(p).name for p in texts) == ["x.c", "y.h"] and [Path(p).name for p in unread] == ["z.c"]
