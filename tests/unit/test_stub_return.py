"""R14 — a sequence that sets ``F() return`` stubs F for that run: the source oracle takes the value (converted to F's
declared return type) and the clang harness returns the same value, so the claim stays independently checkable. What
F writes stays unknown. Without the input nothing changes."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

COMMON = "typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef signed int S16;\n" \
         "typedef enum { ST_OK = 0, ST_BAD = 1 } St_t;\n"
LIB = '#include "common.h"\nU8 g_side;\nU8 cal(void) { g_side = 1U; return 7U; }\nSt_t check(void) { return ST_OK; }\n' \
      "U8 *where(void) { return &g_side; }\nU16 cnt(void) { return 1U; }\n"
APP = '''#include "common.h"
extern U8 g_side;
U8 cal(void);
St_t check(void);
U8 *where(void);
U16 cnt(void);
U8 g_o;
U8 g_s;
U8 g_d;
void f(void) { g_o = (U8)(cal() + 1U); g_s = g_side; }
void e(void) { if (check() != ST_OK) { g_o = 9U; } else { g_o = 3U; } }
void p(void) { g_o = (U8)(where() != 0); }
void c(void) { g_o = (U8)((cnt() > -1) ? 1U : 0U); }
U8 r(U8 n) { if (n == 0U) { return 0U; } return (U8)(r((U8)(n - 1U)) + 1U); }
void d(void) { g_o = (U8)(200U / g_d); }
void q(void) { g_o = g_s; }
'''


@pytest.fixture(scope="module")
def units(tmp_path_factory):
    from reference_alignment import _load_source

    from generators.c_project_context import build_scopes
    root = tmp_path_factory.mktemp("stub") / "src"
    root.mkdir()
    for name, text in (("common.h", COMMON), ("lib.c", LIB), ("app.c", APP)):
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    texts, context, _ = _load_source([root])
    app = next(p for p in texts if p.endswith("app.c"))
    scope = build_scopes(context, [app])[app]
    return {fn: {"name": fn, "source_text": texts[app], "source_path": app, "source_text_complete": True,
                 "project_scope": scope} for fn in ("f", "e", "p", "c", "r", "d", "q")}


def _run(unit, inputs, outs):
    from generators.c_source_oracle import evaluate_outputs
    (r,) = evaluate_outputs(unit, [inputs], [outs])
    return r


def test_without_the_input_a_return_value_stays_unknown(units):
    r = _run(units["f"], {}, ["g_o"])
    assert r["outputs"]["g_o"]["reason"].startswith("call_return_value:cal")


def test_the_sequence_stub_gives_the_return_value_and_the_callee_effects_stay_unknown(units):
    r = _run(units["f"], {"cal() return": 5}, ["g_o", "g_s"])
    assert r["outputs"]["g_o"] == {"value": 6, "basis": "assigned"}
    assert r["outputs"]["g_s"]["reason"].startswith("written_by_callee:cal")   # the stub says nothing about writes
    assert r["stubs"] == ["cal"] and any("cal() returns the value set" in a for a in r["assumptions"])


def test_a_stub_value_outside_the_declared_return_type_is_not_executable(units):
    r = _run(units["f"], {"cal() return": 300}, ["g_o"])
    assert r["outputs"]["g_o"]["reason"].startswith("input_outside_declared_type:cal() return")


def test_the_reference_name_and_value_notation_is_read_and_checked(units):
    assert _run(units["e"], {"check() return": "ST_BAD (1)"}, ["g_o"])["outputs"]["g_o"]["value"] == 9
    assert _run(units["e"], {"check() return": "ST_OK (0)"}, ["g_o"])["outputs"]["g_o"]["value"] == 3
    conflict = _run(units["e"], {"check() return": "ST_OK (1)"}, ["g_o"])["outputs"]["g_o"]
    assert "input_name_value_conflict:check() return" in conflict["reason"]   # the branch on it is unknown


def test_a_pointer_return_is_not_stubbed_from_a_number(units):
    r = _run(units["p"], {"where() return": 1}, ["g_o"])
    assert r["outputs"]["g_o"]["reason"].startswith("stub_return_type_unresolved:where")


def test_clang_returns_the_same_stub_value(units):
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")
    from source_oracle_clang_check import check_claims
    claims = [{"unit": units["f"], "inputs": {"cal() return": 5}, "outputs": {"g_o": 6}},
              {"unit": units["e"], "inputs": {"check() return": "ST_BAD (1)"}, "outputs": {"g_o": 9}},
              {"unit": units["c"], "inputs": {"cnt() return": 5}, "outputs": {"g_o": 0}}]   # U16 conversion
    report = check_claims(claims)
    assert report["mismatch"] == 0 and report["agree"] == 3
    # (R11) each claim output carries its own verdict (a function that calls others: its stubs are not the check)
    assert [c["verdicts"] for c in claims] == [{"g_o": "agree_with_stubbed_callees"}] * 3
    wrong = check_claims([{"unit": units["f"], "inputs": {"cal() return": 5}, "outputs": {"g_o": 7}}])
    assert wrong["mismatch"] == 1   # the harness really uses the stub value


def test_the_stub_value_takes_the_declared_return_type_in_the_comparison(units):
    """(review R14 W2) ``cnt()`` returns U16 (unsigned int, 16-bit): ``-1`` converts to 65535 and ``5 > 65535`` is
    false. Read as a plain int the stub would give 1."""
    assert _run(units["c"], {"cnt() return": 5}, ["g_o"])["outputs"]["g_o"]["value"] == 0


def test_a_recursive_call_is_not_a_stub_of_the_function_under_test(units):
    """(review R14 W1) the function under test runs for real in its own test: ``r() return`` does not stub r."""
    r = _run(units["r"], {"n": 1, "r() return": 5}, ["return"])
    assert "value" not in r["outputs"]["return"] and not r.get("stubs")


def test_the_name_and_value_notation_is_checked_on_an_ordinary_input_too(units):
    assert _run(units["q"], {"g_s": "ST_BAD (1)"}, ["g_o"])["outputs"]["g_o"]["value"] == 1
    conflict = _run(units["q"], {"g_s": "ST_BAD (0)"}, ["g_o"])["outputs"]["g_o"]
    assert "input_name_value_conflict:g_s" in conflict["reason"]


def test_the_evidence_item_keeps_the_stubs_and_the_summary_counts_them(units):
    from generators.test_evidence import apply_sequence_evidence, summarize_expected_evidence
    seqs = [{"seq_num": 1, "inputs": {"cal() return": 5}, "expected": {"g_o": 0}},
            {"seq_num": 2, "inputs": {}, "expected": {"g_o": 0}}]
    apply_sequence_evidence({**units["f"], "output_vars": ["g_o"]}, seqs)
    assert seqs[0]["expected_evidence"]["g_o"]["stubs"] == ["cal"]
    assert "stubs" not in seqs[1]["expected_evidence"]["g_o"]
    assert summarize_expected_evidence(seqs)["derived_in_stubbed_sequence"] == 1


def test_the_generator_never_stubs_the_unit_itself():
    from generators.suts import _stub_return_names
    assert _stub_return_names(["r", "cal"], {"r", "cal"}, own="r") == ["cal() return"]


def test_the_disclosure_says_how_many_values_rest_on_a_stub():
    from report_gen.generation_disclosures import build_disclosures
    ev = {"derived": 3, "derived_assigned": 3, "derived_unchanged_input": 0, "unknown": 0, "proposed": 0,
          "unrecorded": 0, "total": 3}
    note = {i["key"]: i for i in build_disclosures("suts", {"expected_evidence_summary": ev})}["suts_expected_evidence"]
    assert "stub" not in note["note"]
    ev["derived_in_stubbed_sequence"] = 2
    note = {i["key"]: i for i in build_disclosures("suts", {"expected_evidence_summary": ev})}["suts_expected_evidence"]
    assert "그중 2칸은 피호출 함수의 반환값" in note["note"]


def test_the_ub_probe_lets_an_evaluation_error_in_one_fill_answer(units):
    """(review R14 W2c) ``200 / g_d`` with ``g_d`` unset: fill 0 divides by zero, fill 90 gives 2 (a mismatch against
    the placeholder 0). The probe reports the evaluation error; a plain check reports the mismatch."""
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")
    from source_oracle_clang_check import check_claims
    probe = check_claims([{"unit": units["d"], "inputs": {}, "outputs": {"g_o": 0}}], ub_probe=True)
    plain = check_claims([{"unit": units["d"], "inputs": {}, "outputs": {"g_o": 0}}])
    assert (probe["eval_error"], probe["mismatch"]) == (1, 0)
    assert plain["mismatch"] == 1


def test_the_generator_never_stubs_the_units_own_out_parameters():
    from generators.suts import _stub_out_param_names
    assert _stub_out_param_names(["r", "cal"], {"r", "cal"}, {"r": ["p"], "cal": ["q"]}, own="r") == ["cal() q[0]"]
