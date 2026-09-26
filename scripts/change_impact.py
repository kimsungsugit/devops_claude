"""Change impact on a generated SUTS (R12) — which test expectations the current source no longer produces.

No SVN is needed: every derived expected value in a generated SUTS ("Test Evidence" sheet) carries the inputs of its
sequence. **Every** derived row is re-derived by the source oracle on the current tree (review round 1 C1: a file hash
cannot stand for the value — the value also depends on the headers the file includes, and a changed ``#define`` in a
header changes it with the ``.c`` text untouched). Per row:

* ``same_value`` / ``value_changed`` (the regression impact: the TC's expectation must be revised, or the change is a
  defect) / ``no_longer_determined`` (the oracle cannot derive it now — reason kept);
* ``function_removed`` (no definition of the name anywhere now) — a function that moved to another file is evaluated
  there and marked ``moved_to``;
* ``source_missing`` (the file is gone and the function is nowhere) / ``source_unreadable`` (the file is there but not
  UTF-8 — never read with a guessed encoding).

The recorded file hash is compared too, as information (``source_text_changed``, with CRLF/LF normalised — the
generator's local mode hashes text read with universal newlines) — for **every** row, derived or not: a changed file
whose rows are all ``[검증 필요]`` cannot be re-derived, but its test cases are still to re-check
(``changed_files_without_derived_rows`` / ``tests_on_changed_files_not_rederived``, review round 2 W1). A recorded path
that no longer resolves is listed (``source_paths_not_compared``) — "no change" is never said of a file not compared.
Functions whose rows are all non-derived cannot be re-checked and are listed (``functions_without_derived_rows``). The
impacted test cases are those with a row that is not ``same_value``. A workbook without the columns this needs is
refused (an older SUTS without ``Inputs JSON`` would re-derive with no inputs and report false impact — round 2 W2). This re-derives with the same model (not a target run): it tells what to re-check, not which side
is right.

Usage:
    .venv/Scripts/python.exe scripts/change_impact.py --xlsm OLD_SUTS.xlsm --source-root ROOT[,ROOT2] --out impact.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


REQUIRED_COLUMNS = ("Function", "Test Case ID", "Sequence", "Observable", "Expected", "Status", "Source path",
                    "Source SHA256", "Inputs JSON")


def read_rows(xlsm: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Derived rows, and the functions that have no derived row at all (they cannot be re-checked)."""
    return read_workbook(xlsm)[:2]


def read_workbook(xlsm: str) -> tuple[list[dict[str, Any]], list[str], dict[str, dict[str, Any]]]:
    """Derived rows, the functions without one, and per recorded source file: its recorded hashes and test cases (every
    row — review round 2 W1)."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsm, read_only=True)
    try:
        rows = wb["Test Evidence"].iter_rows(values_only=True)
        header = list(next(rows))
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"'Test Evidence' lacks {missing}: an older SUTS cannot be re-derived faithfully")
        out, seen, derived_fns = [], set(), set()
        files: dict[str, dict[str, Any]] = {}
        for row in rows:
            d = dict(zip(header, row, strict=False))
            key = (d.get("Source path"), d.get("Function"))
            seen.add(key)
            if d.get("Source path"):
                f = files.setdefault(str(d["Source path"]), {"hashes": set(), "tests": set(), "derived": False})
                if d.get("Source SHA256"):
                    f["hashes"].add(str(d["Source SHA256"]))
                f["tests"].add(d.get("Test Case ID"))
                f["derived"] = f["derived"] or d.get("Status") == "derived"
            if d.get("Status") != "derived":
                continue
            derived_fns.add(key)
            out.append({"function": d.get("Function"), "function_id": d.get("Function ID"),
                        "test_case": d.get("Test Case ID"), "sequence": d.get("Sequence"),
                        "observable": d.get("Observable"), "expected": d.get("Expected"),
                        "source_path": d.get("Source path"), "source_hash": d.get("Source SHA256"),
                        "inputs": json.loads(d.get("Inputs JSON") or "{}")})
        return out, sorted(f"{fn} ({Path(str(path)).name if path else '—'})" for path, fn in seen - derived_fns
                           if fn), files
    finally:
        wb.close()


def read_derived_rows(xlsm: str) -> list[dict[str, Any]]:
    return read_rows(xlsm)[0]


def _norm(path) -> str:
    return str(Path(str(path)).resolve()).lower()


def _hashes(text: str) -> set[str]:
    return {hashlib.sha256(text.encode()).hexdigest(),
            hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()}


def _same(got, expected) -> bool:
    """The re-derived value against the written one: as text, or as the same integer (``0x6`` is 6)."""
    a, b = str(got).strip(), str(expected).strip()
    if a == b:
        return True
    try:
        return int(a, 0) == int(b, 0)
    except ValueError:
        return False


def impact(rows: list[dict[str, Any]], roots: list[Path], files: dict[str, dict[str, Any]] | None = None
           ) -> dict[str, Any]:
    from reference_alignment import _definitions, _load_source

    from generators.c_project_context import build_scopes
    from generators.c_source_oracle import evaluate_outputs
    texts, context, unread = _load_source(roots)
    by_norm = {_norm(p): p for p in texts}
    unreadable = {_norm(p) for p in unread}
    defined = _definitions(texts)   # every definition now: a function may have moved to another file
    targets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    status: Counter = Counter()
    for r in rows:
        path = by_norm.get(_norm(r["source_path"]))
        where = defined.get(r["function"], [])
        if path is not None:
            r["source_text_changed"] = r["source_hash"] not in _hashes(texts[path])
        if path is not None and path in where:
            targets[(path, r["function"])].append(r)
        elif _norm(r["source_path"]) in unreadable:
            # before "moved": a same-named static function elsewhere is not this one (review round 2 I3)
            r["impact"] = "source_unreadable"
            status[r["impact"]] += 1
        elif len(where) == 1:
            r["moved_to"] = where[0]
            targets[(where[0], r["function"])].append(r)
        elif where:
            r["impact"], r["now"] = "no_longer_determined", "defined_in_several_files:" + ",".join(where)
            status[r["impact"]] += 1
        else:
            r["impact"] = "function_removed" if path is not None else "source_missing"
            status[r["impact"]] += 1
    scopes = build_scopes(context, sorted({p for p, _fn in targets})) if targets else {}
    for (path, fn), members in targets.items():
        unit = {"name": fn, "source_text": texts[path], "source_path": path, "source_text_complete": True,
                "project_scope": scopes[path]}
        by_vector: dict[str, list[dict]] = defaultdict(list)
        for r in members:
            by_vector[json.dumps(r["inputs"], sort_keys=True)].append(r)
        vectors = [json.loads(k) for k in by_vector]
        outs = [[r["observable"] for r in by_vector[k]] for k in by_vector]
        for key, result in zip(by_vector, evaluate_outputs(unit, vectors, outs), strict=True):
            for r in by_vector[key]:
                got = result["outputs"].get(r["observable"]) or {}
                if "value" not in got:
                    r["impact"], r["now"] = "no_longer_determined", str(got.get("reason", ""))[:120]
                elif _same(got["value"], r["expected"]):
                    r["impact"] = "same_value"
                else:
                    r["impact"], r["now"] = "value_changed", got["value"]
                status[r["impact"]] += 1
    impacted = defaultdict(list)
    for r in rows:
        if r["impact"] != "same_value":
            # ``source_text_changed: False`` — the .c text is the same: the value moved with a header, or with the
            # model itself (a newer oracle derives what an older one could not, or refuses what it now proves undefined)
            impacted[r["test_case"]].append({k: r.get(k) for k in ("function", "sequence", "observable", "expected",
                                                                   "impact", "now", "moved_to", "source_text_changed")})
    changed, not_compared, unrederived, unrederived_tests = set(), [], [], set()
    for recorded, f in sorted((files or {}).items()):
        path = by_norm.get(_norm(recorded))
        if path is None:
            if _norm(recorded) not in unreadable:
                not_compared.append(recorded)   # moved tree or deleted file: not "unchanged" (review round 2 I4)
            continue
        if not f["hashes"]:
            not_compared.append(recorded)   # no hash recorded: nothing to compare its text against (round 3 W-a)
            continue
        if not f["hashes"] & _hashes(texts[path]):
            changed.add(recorded)
            if not f["derived"]:
                unrederived.append(recorded)
                unrederived_tests |= {t for t in f["tests"] if t}
    changed |= {r["source_path"] for r in rows if r.get("source_text_changed")}
    return {"rows": len(rows), "status": dict(status),
            "changed_files": sorted(changed),
            "changed_files_without_derived_rows": unrederived,
            "tests_on_changed_files_not_rederived": sorted(unrederived_tests),
            "source_paths_not_compared": not_compared,
            "unreadable_source_files": len(unread),
            "impacted_test_cases": {tc: v for tc, v in sorted(impacted.items())},
            "impacted_count": len(impacted),
            "note": "every derived row re-derived by the same source oracle — what to re-check, not which side is "
                    "right; not a target run"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsm", required=True, help="an earlier generated SUTS (read-only)")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    roots = [Path(r.strip()) for r in re.split(r"[,;]", args.source_root) if r.strip()]
    from reference_alignment import _guard_output
    _guard_output(Path(args.out), args.xlsm, roots, inputs=(args.xlsm,))
    rows, without, files = read_workbook(args.xlsm)
    report = {"xlsm": args.xlsm, "source_roots": [str(r) for r in roots], **impact(rows, roots, files),
              "functions_without_derived_rows": without}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("rows", "status", "impacted_count", "unreadable_source_files")} |
                     {"changed_files": len(report["changed_files"]),
                      "changed_files_without_derived_rows": len(report["changed_files_without_derived_rows"]),
                      "tests_on_changed_files_not_rederived": len(report["tests_on_changed_files_not_rederived"]),
                      "source_paths_not_compared": len(report["source_paths_not_compared"]),
                      "functions_without_derived_rows": len(without)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
