"""Independent semantic capability benchmark; exit 1 means unmet requirements.

Synthetic QM examples only. This measures generated test design, not target
execution coverage or superiority over project reference documents.
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def independent_conditions(vectors, decision):
    """Return condition indexes with unique-cause independent-effect pairs.

    Each vector contains independently evaluated atomic Boolean conditions.
    No production MC/DC parser or coverage labels are trusted here.
    """
    covered = set()
    for left, right in combinations(vectors, 2):
        changed = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        if len(changed) == 1 and decision(left) != decision(right):
            covered.add(changed[0])
    return covered


def is_review_marker(value):
    return isinstance(value, str) and value.startswith("[검증 필요]")


def check_rows(rows, oracle=None, observable="y"):
    """Reject numeric guesses; uncomputed behavior must remain visibly unresolved."""
    failures = []
    for row in rows:
        value = row.get("expected", {}).get(observable)
        x = row.get("inputs", {}).get("x")
        if oracle is not None and isinstance(x, (int, float)) and 0 <= x <= 255:
            if value != oracle(x):
                failures.append({"input": x, "expected": oracle(x), "actual": value})
        elif not is_review_marker(value):
            failures.append({"input": x, "expected": "explicit review marker", "actual": value})
    return failures


def run_benchmark():
    from generators.sits import _generate_sub_cases
    from generators.suts import generate_sequences

    unit = {"name": "affine", "input_vars": ["x"], "output_vars": ["return"],
            "param_types": {"x": "uint8_t", "return": "uint16_t"}, "logic_flow": [],
            "source_text": "#include <stdint.h>\nuint16_t affine(uint8_t x) { return 2 * x + 3; }"}
    flow = {"input_vars": ["x"], "expected_vars": ["y"],
            "input_raws": ["U8 x"], "expected_raws": ["U16 y"],
            "call_chain": "Source -> Consumer"}
    results = []
    for name, rows, oracle, observable in [
        ("SUTS_AFFINE_ORACLE", generate_sequences(dict(unit), max_seq=6), lambda x: 2*x+3, "return"),
        ("SUTS_MISSING_BEHAVIOR", generate_sequences({**unit, "source_text": ""}, max_seq=6), None, "return"),
        ("SITS_MISSING_BEHAVIOR", _generate_sub_cases(flow, max_cases=7), None, "y"),
    ]:
        failures = check_rows(rows, oracle, observable)
        results.append({"requirement": name, "passed": not failures, "failures": failures})
    for name, expression, predicate in [
        ("OR", "a > 10 || b > 20", lambda v: v[0] or v[1]),
        ("AND", "a > 10 && b > 20", lambda v: v[0] and v[1]),
    ]:
        rows = generate_sequences({"name": "decision", "input_vars": ["a", "b"],
            "output_vars": [], "param_types": {"a": "uint8_t", "b": "uint8_t"},
            "logic_flow": [{"type": "if", "condition": expression}]}, max_seq=None)
        vectors = [(r["inputs"]["a"] > 10, r["inputs"]["b"] > 20)
                   for r in rows if r["strategy"].startswith("MCDC")]
        covered = independent_conditions(vectors, predicate)
        results.append({"requirement": f"SUTS_MCDC_{name}", "passed": covered == {0, 1},
                        "covered_conditions": sorted(covered), "vectors": vectors})
    return {"schema_version": 2, "scope": "synthetic QM semantic design benchmark", "execution_status": "not_run",
            "passed": all(r["passed"] for r in results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
