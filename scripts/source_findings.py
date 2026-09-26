"""Reproduce SUTS source findings with clang (R10) — is each proven-undefined run undefined for clang too?

Reads a generated SUTS workbook ("Test Evidence" sheet), rebuilds the findings of `generators/source_findings.py`
(one per function and undefined-behaviour kind) and re-evaluates each example vector with clang constant evaluation
(`scripts/source_oracle_clang_check.check_claims`). clang rejects undefined behaviour during constant evaluation, so:

* ``reproduced`` — clang stops on undefined behaviour of that kind (its message for the kind: ``signed integer
  overflow`` / ``outside the range of representable values`` for an overflow, ``division by zero``, a shift count note);
* ``other_evaluation_error`` — clang stops on something else on that run (another UB kind, an out-of-range read) —
  not counted either way in the model false-positive rate;
* ``not_reproduced`` — clang evaluates every fill to a value: the oracle's finding is not confirmed (a false positive
  of the model, reported);
* ``unchecked:<reason>`` — the harness could not be built or evaluated (a limit, not a verdict).

Undetermined state is filled three ways by the harness; the check runs in *UB-probe* mode — an evaluation error in any
fill answers it, the asserted value being a placeholder (review round 1 W6). The clang message of every reproduced
finding is kept. This checks the *model*; whether callers can produce the example inputs is still the reviewer's
call.

Usage:
    .venv/Scripts/python.exe scripts/source_findings.py --xlsm SUTS.xlsm --source-root ROOT[,ROOT2] --out f.json [--clang]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_UB = re.compile(r"undefined_behavior:([a-z_]+)")
# what clang says for each kind (stricter than the disclosure vocabulary: an overflow is not a division by zero)
_SHIFT = r"shift count \S+ >= width|negative shift count|left shift of negative|signed left shift discards"
_KIND_MESSAGE = {
    "array_index_out_of_bounds": re.compile(r"cannot refer to element|past-the-end"),   # (review I2)
    "signed_overflow": re.compile(r"signed integer overflow|outside the range of representable values"),
    "division_by_zero": re.compile(r"division by zero"),
    "shift_count_out_of_range": re.compile(_SHIFT),
    "signed_left_shift_overflow": re.compile(_SHIFT + r"|outside the range of representable values"),
    "float_to_int_out_of_range": re.compile(r"outside the range of representable values"),
}


def read_findings(xlsm: str) -> list[dict[str, Any]]:
    import openpyxl
    wb = openpyxl.load_workbook(xlsm, read_only=True)
    try:
        rows = wb["Test Evidence"].iter_rows(values_only=True)
        header = list(next(rows))
        found: dict[tuple, dict[str, Any]] = {}
        for row in rows:
            d = dict(zip(header, row, strict=False))
            m = _UB.search(str(d.get("Reason") or ""))
            if not m:
                continue
            key = (d.get("Source path"), d.get("Function"), m.group(1))
            f = found.setdefault(key, {"source_path": d.get("Source path"), "function": d.get("Function"),
                                       "function_id": d.get("Function ID"), "kind": m.group(1), "occurrences": 0,
                                       "sequences": set(),
                                       "example": {"inputs": json.loads(d.get("Inputs JSON") or "{}"),
                                                   "observable": d.get("Observable"),
                                                   "test_case": d.get("Test Case ID"), "sequence": d.get("Sequence")}})
            f["occurrences"] += 1
            f["sequences"].add(d.get("Sequence"))
        for f in found.values():
            f["sequences"] = len(f["sequences"])
        return sorted(found.values(), key=lambda f: (str(f["function"]), f["kind"]))
    finally:
        wb.close()


def _units(findings: list[dict], roots: list[Path]) -> dict[tuple, dict]:
    from reference_alignment import _load_source

    from generators.c_project_context import build_scopes
    texts, context, _unread = _load_source(roots)
    by_resolved = {str(Path(p).resolve()): p for p in texts}
    paths = sorted({by_resolved.get(str(Path(f["source_path"]).resolve()), "") for f in findings} - {""})
    scopes = build_scopes(context, paths)
    units = {}
    for f in findings:
        path = by_resolved.get(str(Path(f["source_path"]).resolve()))
        if path and path in scopes:
            units[(f["source_path"], f["function"])] = {"name": f["function"], "source_text": texts[path],
                                                        "source_path": path, "project_scope": scopes[path]}
    return units


def reproduce(findings: list[dict], roots: list[Path], clang_exe: str = "clang") -> Counter:
    from source_oracle_clang_check import check_claims
    units = _units(findings, roots)
    verdicts: Counter = Counter()
    for f in findings:
        unit = units.get((f["source_path"], f["function"]))
        if unit is None:
            f["reproduction"] = "unchecked:source_not_found"
        else:
            # the asserted value is a placeholder: UB-probe mode lets an evaluation error in any fill answer
            claim = {"unit": unit, "inputs": f["example"]["inputs"], "outputs": {f["example"]["observable"]: 0}}
            try:
                report = check_claims([claim], clang=clang_exe, ub_probe=True)
            except Exception as exc:  # noqa: BLE001 — one harness failure is that finding's verdict, not the run's
                f["reproduction"] = f"unchecked:error:{type(exc).__name__}"
            else:
                reasons = report.get("unchecked_reasons") or {}
                if report.get("eval_error"):
                    message = str((report.get("eval_errors") or [{}])[0].get("clang") or "")
                    f["clang"] = message[:300]
                    kind_re = _KIND_MESSAGE.get(f["kind"])
                    f["reproduction"] = "reproduced" if kind_re and kind_re.search(message) else "other_evaluation_error"
                elif report.get("checked"):
                    f["reproduction"] = "not_reproduced"   # every fill evaluated to a value
                else:
                    f["reproduction"] = "unchecked:" + (",".join(sorted(reasons)) or "none")
        verdicts[f["reproduction"].split(":")[0] if f["reproduction"].startswith("unchecked") else f["reproduction"]] += 1
    return verdicts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsm", required=True)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--clang", action="store_true")
    ap.add_argument("--clang-exe", default="clang")
    args = ap.parse_args(argv)
    roots = [Path(r.strip()) for r in re.split(r"[,;]", args.source_root) if r.strip()]
    from reference_alignment import _guard_output
    _guard_output(Path(args.out), args.xlsm, roots, inputs=(args.xlsm,))
    findings = read_findings(args.xlsm)
    verdicts = reproduce(findings, roots, args.clang_exe) if args.clang else Counter()
    summary = {"findings": len(findings), "by_kind": dict(Counter(f["kind"] for f in findings)),
               "sequences": sum(f["sequences"] for f in findings),
               "blocked_expected_slots": sum(f["occurrences"] for f in findings),
               "reproduction": dict(verdicts) if args.clang else "not_run"}
    if args.clang:
        # the model's rate against clang (not whether a finding is a defect): other evaluation errors are neither
        judged = verdicts.get("reproduced", 0) + verdicts.get("not_reproduced", 0)
        summary["model_false_positive_rate"] = round(verdicts.get("not_reproduced", 0) / judged, 4) if judged else None
    Path(args.out).write_text(json.dumps({"xlsm": args.xlsm, "summary": summary, "findings": findings},
                                         ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
