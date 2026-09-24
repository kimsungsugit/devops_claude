"""(R16) SITS interface-fault harness — fault edits and the kill rule on a small in-memory project."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import sits_mutation_eval as sme  # noqa: E402

from generators import c_project_context as cpc  # noqa: E402
from generators.interface_contract import SourceIndex  # noqa: E402

ROOT = os.path.join(os.sep, "virt_r16m")
H = """typedef unsigned char U8;
typedef unsigned int U16;
extern U8 g_a;
extern U8 g_b;
extern U8 g_c;
U8 prod(U8 x, U8 y);
U8 get(void);
"""
A = """#include "m.h"
U8 g_a;
U8 g_b;
U8 g_c;
void entry(void) {
    g_a = prod(g_b, g_c);
    g_c = (U8)(get());
    if (get() == 2U) { g_b = 1U; }
}
void entry2(void) { U8 r; r = (U8)get(); g_b = r; }
U8 tri(U8 x, U8 y, U8 z);
void entry3(void) { g_c = tri(g_a, g_b, g_a); }
"""
B = """#include "m.h"
U8 prod(U8 x, U8 y) { g_c = 7U; g_c++; return (U8)(x - y); }
U8 get(void) { return 3U; }
U8 side(void) { g_c = get(); return 1U; }
void loopw(void) { U8 i; for (i = 0U; i < 2U; g_b++) { i++; } g_b = 1U; }
U8 tri(U8 x, U8 y, U8 z) { return (U8)(x - y + z); }
"""


def _files():
    return {os.path.join(ROOT, "m.h"): H, os.path.join(ROOT, "a.c"): A, os.path.join(ROOT, "b.c"): B}


@pytest.fixture()
def env():
    files = _files()
    ctx = cpc.build_project_context(files)
    parser = cpc.shared_parser()
    units = [p for p in files if p.endswith(".c")]
    project = sme.Project(ctx, files, cpc.build_scopes(ctx, units), parser)
    index = SourceIndex(files, parser)
    saved = dict(sme._W)
    sme._W.clear()
    sme._W.update({"index": index, "base": project, "key_of": {os.path.normcase(os.path.abspath(p)): p for p in files}})
    yield index, project
    sme._W.clear()
    sme._W.update(saved)


def test_as_int_reads_written_integers_only():
    assert [sme.as_int(v) for v in (5, "0x10", "7U", "E_OK (0)", "(3)", "-2", 4.0)] == [5, 16, 7, 0, 3, -2, 4]
    assert [sme.as_int(v) for v in (True, "[검증 필요] x", "N/A", "1.5", None, 2.5)] == [None] * 6


def test_global_write_lost_blanks_every_statement_write(env):
    index, _ = env
    path, text = sme.fault_edit({"kind": "global_write_lost", "at": "prod", "global": "g_c"}, index)
    assert path.endswith("b.c")
    body = text.decode()
    assert "g_c = 7U" not in body and "g_c++" not in body and len(text) == len(B.encode())
    assert "return (U8)(x - y);" in body and " 7U;" in body   # the right-hand side stays (its effects are not the fault)
    _path, text = sme.fault_edit({"kind": "global_write_lost", "at": "side", "global": "g_c"}, index)
    assert "get();" in text.decode() and "g_c = get()" not in text.decode()
    # a write the edit would leave (the ``for`` clause) — the fault has no edit rather than a half one
    assert sme.fault_edit({"kind": "global_write_lost", "at": "loopw", "global": "g_b"}, index) == "write_not_a_statement"


def test_arguments_swapped_keeps_length(env):
    index, _ = env
    fault = {"kind": "arguments_swapped", "at": "entry", "callee": "prod", "line": 6, "args": ["g_b", "g_c"],
             "params": ["x", "y"]}
    _path, text = sme.fault_edit(fault, index)
    assert "prod(g_c, g_b)" in text.decode() and len(text) == len(A.encode())
    # by parameter, not by the first text match: tri(g_a, g_b, g_a) with y/z swapped → tri(g_a, g_a, g_b)
    fault = {"kind": "arguments_swapped", "at": "entry3", "callee": "tri", "line": 12, "args": ["g_b", "g_a"],
             "params": ["y", "z"]}
    _path, text = sme.fault_edit(fault, index)
    assert "tri(g_a, g_a, g_b)" in text.decode()


def test_return_not_propagated_only_for_a_plain_assignment(env):
    index, _ = env
    _path, text = sme.fault_edit({"kind": "return_not_propagated", "at": "entry2", "callee": "get", "line": 10,
                                  "use": "assigned"}, index)
    assert "r = (U8)get()" not in text.decode() and "get();" in text.decode()
    # ``(U8)(get())``: tree-sitter may read the cast as a call — either way no edit that only drops the use
    assert sme.fault_edit({"kind": "return_not_propagated", "at": "entry", "callee": "get", "line": 7,
                           "use": "assigned"}, index) in {"assignment_shape_unmodeled", "assignment_not_a_statement"}
    assert sme.fault_edit({"kind": "return_not_propagated", "at": "entry", "callee": "get", "line": 8,
                           "use": "checked"}, index) == "not_mutable:checked"


def _test(suite, rows, passing, original, outputs):
    return {"suite": suite, "tc_id": f"{suite}_1", "entry": "entry", "path": os.path.join(ROOT, "a.c"),
            "rows": [(r, {}) for r in rows], "outputs": outputs, "passing": passing, "original": original}


def test_a_fault_is_killed_only_by_a_reproduced_expectation_it_changes(env):
    _, project = env
    rows = [{"g_b": 9, "g_c": 4}]
    original = project.run("entry", os.path.join(ROOT, "a.c"), [(r, {}) for r in rows], ["g_a", "g_c"])
    assert original == [{"g_a": 5, "g_c": 3}]
    swap = {"kind": "arguments_swapped", "at": "entry", "callee": "prod", "line": 6, "args": ["g_b", "g_c"],
            "params": ["x", "y"]}
    record = sme._fault_job((swap, [_test("generated", rows, [{"g_a": 5}], [{"g_a": 5}], ["g_a"]),
                                    _test("reference", rows, [{"g_c": 3}], [{"g_c": 3, "g_a": 5}], ["g_c", "g_a"])]))
    assert record["edit"] == "made" and record["distinguished"]
    # g_a becomes (U8)(4 - 9) = 251: the generated row that states g_a kills it; the reference row states only g_c —
    # but it observes g_a too, so its stimulus reveals the fault (input kill)
    assert record["killed_by"] == {"generated": "generated_1", "reference": None}
    assert record["input_killed_by"] == {"generated": "generated_1", "reference": "reference_1"}
    lost = {"kind": "global_write_lost", "at": "prod", "global": "g_c"}
    record = sme._fault_job((lost, [_test("reference", rows, [{"g_c": 3}], [{"g_c": 3}], ["g_c"])]))
    # entry overwrites g_c after prod: the lost write is invisible here — not distinguished, never counted as killed
    assert record["distinguished"] is False and record["killed_by"]["reference"] is None


def test_a_fault_without_an_edit_says_why(env):
    record = sme._fault_job(({"kind": "return_not_propagated", "at": "entry", "callee": "get", "line": 8,
                              "use": "returned"}, []))
    assert record["edit"] == "not_mutable:returned" and record["distinguished"] is False


def test_evaluate_reads_both_suites_on_one_observation_set(env, monkeypatch):
    import sits_interface_eval as sie
    index, project = env
    graph = sie.call_graph(index)
    swap = {"kind": "arguments_swapped", "at": "entry", "callee": "prod", "line": 6, "args": ["g_b", "g_c"],
            "params": ["x", "y"]}
    unreached = {"kind": "global_write_lost", "at": "loopw", "global": "g_b"}
    setup = {"index": index, "graph": graph, "faults": [swap, unreached], "base": project,
             "key_of": {os.path.normcase(os.path.abspath(p)): p for p in _files()}}
    monkeypatch.setattr(sme, "_setup", lambda roots: setup)

    def fake_read(path):
        observed = "g_c" if path == "ref" else "g_a"
        value = 3 if path == "ref" else 5
        return [{"tc_id": f"{path}_1", "chain": "entry", "title": "", "inputs": ["g_b", "g_c"], "expected": [observed],
                 "rows": [{"g_b": 9, "g_c": 4}], "expected_rows": [{observed: value}]}]
    monkeypatch.setattr(sie, "read_sits", fake_read)
    report = sme.evaluate([Path(ROOT)], "ref", "gen", workers=0, progress=lambda m: None)
    s = report["summary"]
    assert s["observed_names"] == 2 and s["distinguished"] == 1
    # the reference wrote only g_c (unchanged by the swap) but its stimulus changes g_a — read on the shared set
    assert (s["reference"]["killed"], s["reference"]["input_killed"]) == (0, 1)
    assert (s["generated"]["killed"], s["generated"]["input_killed"]) == (1, 1)
    # loopw's write sits in a for clause: no edit; the swap is made and reached
    assert s["edits"] == {"made": 1, "write_not_a_statement": 1} and s["not_exercised"] == 0
