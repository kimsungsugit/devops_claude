"""Mutant discrimination of unit-test suites on the current source (R4 — G1 baseline).

Two suites are compared on the same functions: the reference SUTS (its vectors and stated expected values) and a
generated SUTS (its vectors and the expected values its Test Evidence marks ``derived``). Mutants are made from the
unchanged function text by one small edit each and executed by the source oracle (`generators/c_source_oracle.py`)
— a model of the source, not a target run:

* relational ``<`` ``<=`` ``>`` ``>=`` ``==`` ``!=`` swapped, ``&&``/``||`` swapped, binary ``+``/``-`` swapped;
* an integer literal ±1 (same base and suffix);
* an expression statement that assigns deleted (blanked; the ``;`` stays).

Every edit keeps the text's length, so the unit's resolved project scope (macro table, compile states by byte offset,
callee write closures) is reused with only the text hash replaced — a mutant never needs the tree re-read. An edit
that cannot keep the length (``9`` → ``10`` with no blank to absorb it) is not made.

A suite **kills** a mutant when, for one of its sequences, a slot it states an integer for — and that the unmutated
function reproduces (the suite passes on the original) — comes out as a different determined value. A mutant is
**distinguished** when any sampled vector (both suites' vectors plus a deterministic sample over the input types)
gives a different determined output than the original; one that is not stays *undecided* (possibly equivalent —
reported, never counted as killed or survived). Kill rates are over distinguished mutants.

These kills are *source-consistency* kills: the expected values of both suites agree with the code. They measure
which inputs tell behaviours apart, not requirement conformance (that is the STS round's measure).

Usage:
    .venv/Scripts/python.exe scripts/mutation_eval.py --reference REF.xlsm --generated GEN.xlsm --source-root ROOT
        --alignment r3_align.json --out mut.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_REL_SWAPS = {"<": [">", "<="], ">": ["<", ">="], "<=": ["<", ">="], ">=": [">", "<="], "==": ["!="], "!=": ["=="]}
_LOGIC_SWAPS = {"&&": ["||"], "||": ["&&"]}
_ARITH_SWAPS = {"+": ["-"], "-": ["+"]}
_LITERAL = re.compile(r"(0[xX][0-9a-fA-F]+|[0-9]+)([uUlL]*)")


def _fit(raw: bytes, start: int, end: int, replacement: str) -> tuple[int, int, bytes] | None:
    """The edit ``raw[start:end] → replacement`` at the same length: pad with blanks, or absorb blanks that follow."""
    new = replacement.encode()
    length = end - start
    if len(new) <= length:
        return start, end, new + b" " * (length - len(new))
    extra = len(new) - length
    if raw[end:end + extra] == b" " * extra:
        return start, end + extra, new
    return None


def _literal_variants(text: str) -> list[str]:
    m = _LITERAL.fullmatch(text)
    if not m:
        return []
    digits, suffix = m.group(1), m.group(2)
    hexa = digits.lower().startswith("0x")
    value = int(digits, 16) if hexa else int(digits, 10)
    out = []
    for v in (value + 1, value - 1):
        if v < 0:
            continue
        body = (("0x" if digits[:2] == "0x" else "0X") + format(v, "X" if digits[2:].isupper() else "x")) if hexa else str(v)
        out.append(body + suffix)
    return out


def mutants_of(fn, raw: bytes) -> list[dict[str, Any]]:
    """One-edit, same-length mutants of a function body, in source order (deterministic)."""
    body = fn.child_by_field_name("body")
    out: list[dict[str, Any]] = []
    stack = [body] if body is not None else []
    nodes = []
    while stack:
        n = stack.pop()
        nodes.append(n)
        if n.type.startswith("preproc_"):
            continue  # preprocessor text is not run-time code
        stack.extend(reversed(n.named_children))
    for n in sorted(nodes, key=lambda x: (x.start_byte, x.end_byte)):
        if n.type == "binary_expression":
            op = n.child_by_field_name("operator")
            text = raw[op.start_byte:op.end_byte].decode()
            for table, kind in ((_REL_SWAPS, "relational"), (_LOGIC_SWAPS, "logical"), (_ARITH_SWAPS, "arithmetic")):
                for rep in table.get(text, []):
                    fit = _fit(raw, op.start_byte, op.end_byte, rep)
                    if fit:
                        out.append({"operator": kind, "start": fit[0], "end": fit[1], "original": text, "replacement": rep,
                                    "line": n.start_point[0] + 1, "edit": fit[2]})
        elif n.type == "number_literal" and n.parent is not None and n.parent.type not in {"array_declarator"}:
            text = raw[n.start_byte:n.end_byte].decode()
            for rep in _literal_variants(text):
                fit = _fit(raw, n.start_byte, n.end_byte, rep)
                if fit:
                    out.append({"operator": "literal", "start": fit[0], "end": fit[1], "original": text,
                                "replacement": rep, "line": n.start_point[0] + 1, "edit": fit[2]})
        elif n.type == "expression_statement":
            inner = [c for c in n.named_children if c.type != "comment"]
            if len(inner) == 1 and inner[0].type == "assignment_expression":
                span = raw[inner[0].start_byte:inner[0].end_byte]
                blank = bytes(b if b in (10, 13) else 32 for b in span)
                out.append({"operator": "statement_deletion", "start": inner[0].start_byte, "end": inner[0].end_byte,
                            "original": span.decode(errors="replace")[:60], "replacement": "",
                            "line": n.start_point[0] + 1, "edit": blank})
    for i, m in enumerate(out):
        m["id"] = f"M{i + 1}"
    return out


def _apply(raw: bytes, mutant: dict) -> bytes:
    edited = raw[:mutant["start"]] + mutant["edit"] + raw[mutant["end"]:]
    assert len(edited) == len(raw)
    return edited


def _suite_from_workbook(path: str, generated: bool) -> tuple[dict[str, list[dict]], list[str]]:
    """Function name → [{"inputs", "expected": {slot: raw cell}}] and the names used by more than one unit; a generated
    suite states only ``derived`` slots. Cells are read into integers per function later, with that function's
    constants — the same reading R3 used (review r2 W-D: an enumerator name the reference wrote is a stated value)."""
    from tools.export_suts_vectorcast import bare_fn_name, build_vectorcast_model
    model = build_vectorcast_model(path)
    suites: dict[str, list[dict]] = {}
    units_per_name = Counter(bare_fn_name(u["unit_name"]) for u in model["units"])
    for unit in model["units"]:
        name = bare_fn_name(unit["unit_name"])
        for case in unit["test_cases"]:
            expected = {}
            for slot, value in (case.get("expected") or {}).items():
                if generated and (case.get("expected_evidence") or {}).get(slot, {}).get("status") != "derived":
                    continue
                if value is not None and str(value).strip() != "":
                    expected[slot] = value
            suites.setdefault(name, []).append({"inputs": dict(case.get("inputs") or {}), "expected": expected,
                                                "sequence": case.get("sequence_no")})
    return suites, sorted(n for n, k in units_per_name.items() if k > 1)


def _sample_vectors(names: list[str], scope: dict, params: dict, count: int, seed: str) -> list[dict]:
    """A deterministic sample over the input names' declared types (boundaries and pseudo-random values)."""
    from reference_alignment import _object_type

    from generators import c_project_context as cpc
    rng = random.Random(hashlib.sha256(seed.encode()).hexdigest())
    domains = {}
    for name in names:
        t = _object_type(scope, params, name)
        if isinstance(t, dict) and not cpc.is_float(t) and not t.get("enum"):
            lo, hi = (0, 1) if t.get("kind") == "_Bool" else cpc.type_range(t)
            domains[name] = (lo, hi)
    out = []
    for i in range(count):
        v = {}
        for name, (lo, hi) in domains.items():
            v[name] = [lo, hi, 0 if lo <= 0 <= hi else lo, 1 if lo <= 1 <= hi else hi][i % 4] if i < 4 else rng.randint(lo, hi)
        out.append(v)
    return out


def evaluate(reference: str, generated: str, roots: list[Path], alignment: dict | None, max_mutants: int = 60,
             sample: int = 24, derived_only: bool = True) -> dict:
    """``derived_only``: the generated suite states only the slots its Test Evidence marks ``derived`` (a generated
    SUTS); ``False`` reads it like a reference (every integer it states) — for comparing two reference-style suites."""
    from reference_alignment import _convert_inputs, _definitions, _load_source, _param_types, reference_value

    from generators import c_project_context as cpc
    from generators.c_project_context import build_scopes
    from generators.c_source_oracle import Unsupported, _parsed_function, evaluate_outputs
    ref_suite, ref_names_dup = _suite_from_workbook(reference, generated=False)
    gen_suite, gen_names_dup = _suite_from_workbook(generated, generated=derived_only)
    texts, context, _unread = _load_source(roots)
    definitions = {name: sorted(set(paths)) for name, paths in _definitions(texts).items()}
    # (R3 review W5) suites are keyed by function name: a name the reference uses for two units (the application's and
    # the boot loader's ``WriteBlock``) would merge their sequences — such names are left out and listed
    # (review r2 W-C) the generated suite may also name two units alike (one per definition): excluded the same way
    duplicates = set((alignment or {}).get("summary", {}).get("duplicate_reference_names") or []) | set(ref_names_dup) \
        | set(gen_names_dup)
    if alignment is not None:
        targets = {f["function"]: f.get("source_path") for f in alignment["functions"] if f["status"] == "aligned"}
    else:
        targets = {name: paths[0] for name, paths in definitions.items() if len(paths) == 1}
    excluded = sorted(n for n in targets if n in duplicates)
    targets = {n: p for n, p in targets.items() if p and n in ref_suite and n in gen_suite and n not in duplicates}
    scopes = build_scopes(context, sorted(set(targets.values())))
    functions, totals = [], Counter()
    by_operator: dict[str, Counter] = {}
    for name, path in sorted(targets.items()):
        scope = scopes[path]
        raw = texts[path].encode()
        unit = {"name": name, "source_text": texts[path], "source_path": path, "source_text_complete": True,
                "project_scope": scope}
        try:
            _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, name, scope)
        except Unsupported as exc:
            functions.append({"function": name, "status": "unsupported", "reason": str(exc)})
            continue
        params = _param_types(unit)
        constants = scope.get("constants") if scope.get("constants") is not None else {}
        suites = {}
        for label, suite in (("reference", ref_suite[name]), ("generated", gen_suite[name])):
            cases = []
            for case in suite:
                inputs, _conv = _convert_inputs(scope, params, case["inputs"])
                expected = {s: v for s, raw in case["expected"].items()
                            if (v := reference_value(raw, constants)) is not None}
                cases.append({"inputs": inputs, "expected": expected})
            suites[label] = cases
        slots = sorted({s for cases in suites.values() for c in cases for s in c["expected"]})
        names = sorted({k for cases in suites.values() for c in cases for k in c["inputs"]} | set(params))
        vectors = [c["inputs"] for cases in suites.values() for c in cases] + \
            _sample_vectors(names, scope, params, sample, f"{path}:{name}")
        original = evaluate_outputs(unit, vectors, [slots] * len(vectors))
        base = [{s: o["value"] for s, o in r["outputs"].items() if "value" in o} for r in original]
        # a suite slot counts only where the unmutated function reproduces the stated value (the suite passes)
        passing = {label: [{s: e for s, e in c["expected"].items() if base_row.get(s) == e}
                           for c, base_row in zip(cases, base[offset:offset + len(cases)], strict=True)]
                   for label, cases, offset in (("reference", suites["reference"], 0),
                                                ("generated", suites["generated"], len(suites["reference"])))}
        mutants = mutants_of(fn, raw)
        for m in mutants:
            by_operator.setdefault(m["operator"], Counter())
        truncated = max(0, len(mutants) - max_mutants)
        mutants = mutants[:max_mutants]
        record = {"function": name, "source_path": path, "mutants": len(mutants), "mutants_not_made_budget": truncated,
                  "suite_slots": {k: sum(len(p) for p in v) for k, v in passing.items()},
                  "results": Counter(), "survivors": {"reference": [], "generated": []}, "only_reference": []}
        for mutant in mutants:
            edited = _apply(raw, mutant)
            munit = dict(unit, source_text=edited.decode("utf-8"),
                         project_scope=dict(scope, main_file_sha256=hashlib.sha256(edited).hexdigest()))
            got = evaluate_outputs(munit, vectors, [slots] * len(vectors))
            rows = [{s: o["value"] for s, o in r["outputs"].items() if "value" in o} for r in got]
            distinguished = any(s in b and s in m and b[s] != m[s] for b, m in zip(base, rows, strict=True) for s in m)
            killed, by_slot = {}, {}
            for label, offset in (("reference", 0), ("generated", len(suites["reference"]))):
                by_slot[label] = sorted({s for i, stated in enumerate(passing[label]) for s, e in stated.items()
                                         if s in rows[offset + i] and rows[offset + i][s] != e})
                killed[label] = bool(by_slot[label])
            if not distinguished and not any(killed.values()):
                record["results"]["undecided"] += 1
                continue
            record["results"]["distinguished"] += 1
            by_operator[mutant["operator"]]["distinguished"] += 1
            for label in ("reference", "generated"):
                if killed[label]:
                    record["results"][f"killed_by_{label}"] += 1
                    by_operator[mutant["operator"]][f"killed_by_{label}"] += 1
                else:
                    record["survivors"][label].append({k: mutant[k] for k in ("id", "operator", "line", "original",
                                                                             "replacement")})
            if killed["reference"] and not killed["generated"]:
                # why the generated suite missed it: it states no value for the output that told the reference apart,
                # or it does but none of its vectors separates the mutant there
                states = {s for stated in passing["generated"] for s in stated}
                why = ("generated_states_no_value_for_output" if not set(by_slot["reference"]) & states
                       else "generated_vectors_do_not_separate")
                record["only_reference"].append({"id": mutant["id"], "operator": mutant["operator"],
                                                 "line": mutant["line"], "slots": by_slot["reference"], "why": why})
        record["results"] = dict(record["results"])
        for k, v in record["results"].items():
            totals[k] += v
        totals["mutants"] += len(mutants)
        totals["only_reference"] += len(record["only_reference"])
        for miss in record["only_reference"]:
            totals["only_reference:" + miss["why"]] += 1
        functions.append(record)
    dist = totals["distinguished"]
    summary = {**dict(totals),
               "reference_kill_rate": round(totals["killed_by_reference"] / dist, 4) if dist else None,
               "generated_kill_rate": round(totals["killed_by_generated"] / dist, 4) if dist else None,
               "functions": sum(1 for f in functions if "mutants" in f),
               "excluded_duplicate_reference_names": excluded,
               # per operator: which kinds of change each suite tells apart (distinguished mutants only)
               "by_operator": {op: dict(c) for op, c in sorted(by_operator.items())}}
    if dist:
        summary["generated_minus_reference_pp"] = round(100 * (summary["generated_kill_rate"] - summary["reference_kill_rate"]), 1)
    return {"reference": reference, "generated": generated, "source_roots": [str(r) for r in roots],
            "kind": "source-consistency mutant kill (unit level); not requirement conformance, not a target run",
            "execution_status": "not_run", "summary": summary, "functions": functions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reference", required=True)
    ap.add_argument("--generated", required=True)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--alignment", default="", help="R3 alignment JSON: only its aligned functions are compared")
    ap.add_argument("--max-mutants", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    roots = [Path(r.strip()) for r in re.split(r"[,;]", args.source_root) if r.strip()]
    from reference_alignment import _guard_output
    _guard_output(Path(args.out), args.reference, roots, inputs=(args.generated, args.alignment))  # review r2 Info 6
    alignment = json.loads(Path(args.alignment).read_text(encoding="utf-8")) if args.alignment else None
    report = evaluate(args.reference, args.generated, roots, alignment, max_mutants=args.max_mutants)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
