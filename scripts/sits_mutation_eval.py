"""SITS interface-fault discrimination by the interprocedural source oracle (R16 — G5, 격차 ②).

R8 (`scripts/sits_interface_eval.py`) scored the necessary conditions only (a test exercises the faulty function and
writes an expectation for the right variable). This harness **evaluates** each interface fault: it makes the faulty
source, runs every test row of both suites through the interprocedural oracle on the original and the faulty code, and
reports two kills per suite, with the same rules for the reference and the generated SITS:

* **stated** — one of its rows states an integer expectation that the original integrated code reproduces (the suite
  passes on the original — a stale or wrong expectation judges nothing) and the faulty code gives a **different
  determined** value for;
* **input** — one of its rows gives a different determined value on the faulty code than on the original, on any
  variable **either suite** observes (both suites are read on the same observation set — review round 2 W3 — so this
  compares their *stimuli* on equal terms, whatever they wrote as expectations).

⚠ The generated suite's expectations **are this oracle's own values** (R16): its stated kills are self-consistent by
construction, and every one of them is also an input kill. The input kill compares the two suites' stimuli on equal
terms; the stated kill says how many of a suite's written expectations a model run can hold to the code.

A fault is *distinguished* when any row of either suite gives a different determined value on any variable its test
observes (the denominator; a fault no row distinguishes is *undecided* — possibly equivalent under these inputs, or
out of the model's reach — reported, never counted; ``not_exercised`` counts the faults no test's call closure
reaches). A reference row that sets ``f() return`` makes ``f`` a stub in that run (the unit-test convention the oracle
follows), which the generated rows never do — reported, not adjusted. A mutant keeps the original's project write
closure (what a callee run as effects only may write): conservative — it can hide a difference, never invent one.

Faults (from the current source, as R8): ``global_write_lost`` — every statement in the producer that assigns the
global loses its target (``g = f(x);`` → ``f(x);``, ``g++;`` blanked) — a write in any other position (a ``for``
clause, inside a larger expression) leaves the fault without an edit; ``arguments_swapped`` — the arguments of the
two named parameters swap places (text length unchanged);
``return_not_propagated`` — for a result assigned (``x = f(…);``) the assignment is blanked to ``f(…);``. A checked or
returned result has no same-length edit that only drops the use: counted as ``not_mutable``.

The oracle is a model of the source (hardware, interrupts and other tasks are outside it), not a target run: kills are
source-consistency kills, as in R4.

Usage:
    .venv/Scripts/python.exe scripts/sits_mutation_eval.py --source-root ROOT --reference REF.xlsm
        --generated GEN.xlsm --out r16_mut.json [--max-faults N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_NAMED_VALUE = re.compile(r"^\s*(?:[A-Za-z_]\w*\s*)?\(\s*([-+]?(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*\s*\)\s*$")
_NUMBER = re.compile(r"^\s*([-+]?(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*\s*$")


def as_int(value) -> int | None:
    """A written integer expectation: ``5``, ``0x10``, ``5U``, ``E_OK (0)``, ``(3)``; anything else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    m = _NUMBER.match(str(value)) or _NAMED_VALUE.match(str(value))
    if not m:
        return None
    text = m.group(1)
    return int(text, 16) if "x" in text.lower() else int(text, 10)


def _input_name(name: str) -> str:
    from sits_interface_eval import _RETURN_COL
    m = _RETURN_COL.match(name)
    return f"{m.group(1)}() return" if m else name.strip()


def _rows(test: dict) -> list[tuple[dict, dict]]:
    """(inputs, expected) per row, input names in the oracle's form (``f() return``) and values as written."""
    out = []
    for i, row in enumerate(test["rows"]):
        exp = test["expected_rows"][i] if i < len(test["expected_rows"]) else {}
        out.append(({_input_name(k): v for k, v in row.items()}, dict(exp)))
    return out


# ── faults as edits ─────────────────────────────────────────────────────────────────────────────────────────────────
def _write_target(e, raw: bytes) -> str:
    target = e.child_by_field_name("left") if e.type == "assignment_expression" else \
        e.child_by_field_name("argument") if e.type == "update_expression" else None
    while target is not None and target.type in {"subscript_expression", "parenthesized_expression"}:
        target = target.child_by_field_name("argument") or (target.named_children[0] if target.named_children else None)
    return raw[target.start_byte:target.end_byte].decode() if target is not None and target.type == "identifier" else ""


def _statement_writes(fn, raw: bytes, name: str) -> tuple[list[tuple[int, int]], int]:
    """(blank spans, writes elsewhere): for each expression statement whose one expression writes ``name``, the span
    that removes the write and keeps the rest (``g = f(x)`` → the ``g =`` part; ``g++`` → all of it); and how many
    writes to ``name`` sit anywhere else (a ``for`` clause, a comma, a larger expression) — review W2."""
    from generators.interface_contract import _walk
    spans, total = [], 0
    body = fn.child_by_field_name("body")
    for e in _walk(body) if body is not None else ():
        if e.type not in {"assignment_expression", "update_expression"} or _write_target(e, raw) != name:
            continue
        total += 1
        parent = e.parent
        if parent is None or parent.type != "expression_statement":
            continue
        if e.type == "update_expression":
            spans.append((e.start_byte, e.end_byte))
        else:
            right = e.child_by_field_name("right")
            spans.append((e.start_byte, right.start_byte if right is not None else e.end_byte))
    return spans, total - len(spans)


def _call_nodes(fn, raw: bytes, callee: str, line: int):
    from generators.interface_contract import _callee_name, _walk
    body = fn.child_by_field_name("body")
    return [n for n in (_walk(body) if body is not None else ())
            if n.type == "call_expression" and n.start_point[0] + 1 == line and _callee_name(n, raw) == callee]


def fault_edit(fault: dict, index) -> tuple[str, bytes] | str:
    """(path, faulty text) of the file that defines ``fault["at"]``, or why the fault has no edit."""
    fn, raw, path = index.defs[fault["at"]]
    edits: list[tuple[int, int, bytes]] = []
    if fault["kind"] == "global_write_lost":
        spans, elsewhere = _statement_writes(fn, raw, fault["global"])
        if not spans or elsewhere:
            return "write_not_a_statement"   # a write the edit would leave in place does not model a lost write
        edits = [(s, e, b" " * (e - s)) for s, e in spans]
    elif fault["kind"] == "arguments_swapped":
        calls = _call_nodes(fn, raw, fault["callee"], fault["line"])
        if len(calls) != 1:
            return "call_not_unique"
        from generators.interface_contract import _params
        args = [a for a in calls[0].child_by_field_name("arguments").named_children if a.type != "comment"]
        callee = index.defs.get(fault["callee"])
        params = [x["name"] for x in (_params(callee[0], callee[1]) or [])] if callee else []
        try:
            # (review W3) by the parameters the fault names — ``f(x, y, x)``: the first ``x`` is not always the one
            i, j = params.index(fault["params"][0]), params.index(fault["params"][1])
        except (ValueError, IndexError, TypeError):
            return "arguments_not_found"
        if len(params) != len(args):
            return "arguments_not_found"
        a, b = sorted((args[i], args[j]), key=lambda x: x.start_byte)
        ta, tb = raw[a.start_byte:a.end_byte], raw[b.start_byte:b.end_byte]
        edits = [(a.start_byte, b.end_byte, tb + raw[a.end_byte:b.start_byte] + ta)]
    elif fault["kind"] == "return_not_propagated":
        if fault.get("use") != "assigned":
            return "not_mutable:" + str(fault.get("use"))
        calls = _call_nodes(fn, raw, fault["callee"], fault["line"])
        if len(calls) != 1:
            return "call_not_unique"
        parent = calls[0].parent
        while parent is not None and parent.type in {"parenthesized_expression", "cast_expression"}:
            parent = parent.parent
        if parent is None or parent.type != "assignment_expression" or parent.parent is None \
                or parent.parent.type != "expression_statement":
            return "assignment_not_a_statement"
        if raw[calls[0].end_byte:parent.end_byte].strip():
            return "assignment_shape_unmodeled"   # ``x = (U8)(f())``: blanking the head would leave a ``)``
        edits =[(parent.start_byte, calls[0].start_byte, b" " * (calls[0].start_byte - parent.start_byte))]
        # a cast between (``x = (U8)f()``) is blanked with the target: what is left is ``f();``
    else:
        return "unknown_kind"
    out = raw
    for s, e, new in sorted(edits, reverse=True):
        out = out[:s] + new + out[e:]
    if len(out) != len(raw):
        return "length_changed"
    return path, out


# ── evaluation ──────────────────────────────────────────────────────────────────────────────────────────────────────
class Project:
    """Texts, scopes and the callee provider of one version of the source (the original, or with one file edited)."""

    def __init__(self, context, files, scopes, parser):
        from generators.integration_oracle import CalleeProvider
        self.context, self.files, self.scopes, self.parser = context, files, scopes, parser
        self.provider = CalleeProvider(context, files, scopes, parser)

    def edited(self, path: str, raw: bytes) -> Project:
        text = raw.decode("utf-8")
        files = {**self.files, path: text}
        scopes = dict(self.scopes)
        if path in scopes:
            # same length: the scope's positions (compile states, macro sites) hold; only the text hash is new
            scopes[path] = {**scopes[path], "main_file_sha256": hashlib.sha256(text.encode()).hexdigest()}
        return Project(self.context, files, scopes, self.parser)

    def run(self, entry: str, entry_path: str, rows: list[tuple[dict, dict]], outputs: list[str]) -> list[dict]:
        from generators.c_source_oracle import evaluate_outputs
        unit = {"name": entry, "source_text": self.files[entry_path], "source_path": entry_path,
                "source_text_complete": True, "project_scope": self.scopes[entry_path], "callee_provider": self.provider}
        records = evaluate_outputs(unit, [r[0] for r in rows], [outputs] * len(rows))
        return [{k: v.get("value") for k, v in (rec.get("outputs") or {}).items()} for rec in records]


_W: dict[str, Any] = {}   # per process: the source, its index and the original project (`_setup`)


def _setup(roots: list[Path]) -> dict[str, Any]:
    import os

    from sits_interface_eval import call_graph, faults

    # the generator's own source stage (build configuration, toolchain headers): the oracle sees what SITS saw
    from backend.services import file_resolver as _fr
    from generators import c_project_context as cpc
    from generators.interface_contract import SourceIndex, file_scope_globals
    _fr._resolver = _fr.LocalFileResolver()
    from backend.helpers import _get_source_sections_cached
    report_data = _get_source_sections_cached(",".join(str(r) for r in roots))
    context, files = report_data["project_context"], dict(report_data["source_files"])
    staged = {os.path.normcase(os.path.abspath(p)): t for p, t in files.items()}
    texts: dict[str, str] = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() in (".c", ".h") and p.is_file():
                # (review W4) a unit's text is the source stage's (line ends normalized): faults and their byte edits
                # are made on the text the oracle's scopes were built from, never on the disk bytes
                text = staged.get(os.path.normcase(os.path.abspath(str(p))))
                if text is None:
                    try:
                        text = p.read_bytes().decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                texts[str(p)] = text
    parser = cpc.shared_parser()
    index = SourceIndex(texts, parser)
    graph = call_graph(index)
    units = [p for p in files if p.lower().endswith(".c") and p in context["files"]]
    return {"index": index, "graph": graph, "faults": faults(index, graph, file_scope_globals(texts, parser)),
            "base": Project(context, files, cpc.build_scopes(context, units), parser),
            "key_of": {os.path.normcase(os.path.abspath(p)): p for p in files}}


def _init_worker(roots):
    _W.update(_setup(roots))


def _project_path(env, path):
    import os
    return env["key_of"].get(os.path.normcase(os.path.abspath(path)))


def _original_job(test: dict) -> list[dict]:
    return _W["base"].run(test["entry"], test["path"], test["rows"], test["outputs"])


def _fault_job(job: tuple[dict, list[dict]]) -> dict:
    """One fault against the tests that exercise it (rows with a determined observed value). See the module doc."""
    fault, tests = job
    record = {**{x: fault.get(x) for x in ("kind", "at", "callee", "global", "line", "params")},
              "tests": len(tests), "distinguished": False, "killed_by": {"reference": None, "generated": None},
              "input_killed_by": {"reference": None, "generated": None}}
    edit = fault_edit(fault, _W["index"])
    if isinstance(edit, str):
        record["edit"] = edit
        return record
    path = _project_path(_W, edit[0])
    if path is None or path not in _W["base"].scopes:
        record["edit"] = "unit_not_in_source_stage"
        return record
    if _W["base"].files[path].encode("utf-8") != _W["index"].defs[fault["at"]][1]:
        # (review W4) the source stage read another text (line ends, replacement characters): positions would not match
        record["edit"] = "text_mismatch"
        return record
    record["edit"] = "made"
    if not tests:
        return record
    mutant = _W["base"].edited(path, edit[1])
    for t in tests:
        faulty = mutant.run(t["entry"], t["path"], t["rows"], t["outputs"])
        for orig, bad, passing in zip(t["original"], faulty, t["passing"], strict=True):
            changed = [n for n, v in orig.items() if v is not None and bad.get(n) is not None and bad[n] != v]
            if changed:
                record["distinguished"] = True
                if record["input_killed_by"][t["suite"]] is None:
                    record["input_killed_by"][t["suite"]] = t["tc_id"]
            if record["killed_by"][t["suite"]] is None and any(n in passing for n in changed):
                record["killed_by"][t["suite"]] = t["tc_id"]
    return record


def evaluate(roots: list[Path], reference: str, generated: str, max_faults: int | None = None, workers: int = 4,
             progress=print) -> dict[str, Any]:
    """Every row with a determined value on the shared observation set is run on each fault that its test's call
    closure reaches; the stated kill uses the row's reproduced expectations, the input kill and *distinguished* the
    whole observation set (see the module doc)."""
    from concurrent.futures import ProcessPoolExecutor

    from sits_interface_eval import _chain_functions, _exercised, read_sits
    t0 = time.time()
    env = _setup(roots)
    index, graph, base = env["index"], env["graph"], env["base"]
    fault_list = env["faults"][:max_faults] if max_faults else env["faults"]
    suites = {"reference": read_sits(reference), "generated": read_sits(generated)}
    tests = []
    skipped = Counter()
    for suite, items in suites.items():
        for t in items:
            chain = [f for f in _chain_functions(t["chain"]) if f in graph]
            if not chain:
                skipped[f"{suite}:no_source_function_in_chain"] += 1
                continue
            entry = chain[0]
            if entry in index.duplicates:
                skipped[f"{suite}:entry_ambiguous"] += 1
                continue
            rows = _rows(t)
            if not rows or not (t["expected"] or any(e for _i, e in rows)):
                skipped[f"{suite}:no_rows_or_observables"] += 1
                continue
            outputs: list[str] = []   # set below: the observation set both suites share
            path = _project_path(env, index.defs[entry][2])
            if path is None or path not in base.scopes:
                skipped[f"{suite}:entry_unit_not_in_source_stage"] += 1
                continue
            tests.append({"suite": suite, "tc_id": t["tc_id"], "entry": entry, "path": path,
                          "exercised": _exercised(chain, graph, "first_closure"), "rows": rows, "outputs": outputs})
    observed = list(dict.fromkeys(n for t in tests for n in [*(e for _i, row in t["rows"] for e in row)]))
    observed = list(dict.fromkeys([*observed, *(n for suite_tests in suites.values() for t in suite_tests
                                                for n in t["expected"])]))
    for t in tests:
        t["outputs"] = observed
    progress(f"faults {len(fault_list)} · tests {len(tests)} · observed names {len(observed)} · skipped "
             f"{dict(skipped)} · {time.time() - t0:.0f}s")
    pool = ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(roots,)) if workers > 0 else None
    if pool is None:
        _W.update(env)
    run_map = pool.map if pool is not None else map
    compact: list[dict] = []
    try:
        originals = list(run_map(_original_job, [{k: t[k] for k in ("entry", "path", "rows", "outputs")} for t in tests]))
        # ``determined``: the model gave a value for the stated slot (``reproduced`` + ``contradicted``); the rest it
        # could not evaluate — a limit of the model, not a verdict on the suite
        stats = {s: {"stated_integer": 0, "determined": 0, "reproduced": 0, "contradicted": 0, "rows": 0,
                     "rows_judging": 0, "rows_determined": 0, "observed_determined": 0} for s in suites}
        for t, original in zip(tests, originals, strict=True):
            keep = []
            for (inputs, e), orig in zip(t["rows"], original, strict=True):
                stated = {n: as_int(v) for n, v in e.items() if as_int(v) is not None}
                passing = {n: v for n, v in stated.items() if orig.get(n) == v}
                known = {n: v for n, v in orig.items() if v is not None}
                stats[t["suite"]]["rows"] += 1
                stats[t["suite"]]["stated_integer"] += len(stated)
                stats[t["suite"]]["reproduced"] += len(passing)
                determined = sum(1 for n in stated if orig.get(n) is not None)
                stats[t["suite"]]["determined"] += determined
                stats[t["suite"]]["contradicted"] += determined - len(passing)
                stats[t["suite"]]["observed_determined"] += len(known)
                if passing:
                    stats[t["suite"]]["rows_judging"] += 1
                if known:
                    stats[t["suite"]]["rows_determined"] += 1
                    keep.append((inputs, passing, known))
            if keep:
                compact.append({"suite": t["suite"], "tc_id": t["tc_id"], "entry": t["entry"], "path": t["path"],
                                "exercised": t["exercised"], "rows": [(i, {}) for i, _p, _o in keep],
                                "outputs": list(dict.fromkeys(n for _i, _p, o in keep for n in o)),
                                "passing": [p for _i, p, _o in keep], "original": [o for _i, _p, o in keep]})
        progress(f"originals evaluated · {stats} · {time.time() - t0:.0f}s")
        jobs = [(f, [{k: v for k, v in t.items() if k != "exercised"} for t in compact if f["at"] in t["exercised"]])
                for f in fault_list]
        results = []
        for k, record in enumerate(run_map(_fault_job, jobs)):
            # (review R3 I-2) reached by any test's call closure — whether or not that test has a determined row
            record["reached"] = any(fault_list[k]["at"] in t["exercised"] for t in tests)
            results.append(record)
            if (k + 1) % 50 == 0:
                progress(f"{k + 1}/{len(fault_list)} faults · {time.time() - t0:.0f}s")
    finally:
        if pool is not None:
            pool.shutdown()
    edits = Counter(str(r.get("edit")).split(":", 1)[0] for r in results)
    distinguished = [r for r in results if r["distinguished"]]
    summary: dict[str, Any] = {"faults": len(results), "edits": dict(edits), "distinguished": len(distinguished),
                               "not_exercised": sum(1 for r in results if r.get("edit") == "made" and not r["reached"]),
                               "reached_without_determined_row": sum(1 for r in results if r.get("edit") == "made"
                                                                     and r["reached"] and not r["tests"]),
                               "undecided": sum(1 for r in results if r.get("edit") == "made" and r["tests"]
                                                and not r["distinguished"]),
                               "observed_names": len(observed)}
    made = sum(1 for r in results if r.get("edit") == "made")
    summary["made"] = made
    for s in suites:
        killed = [r for r in distinguished if r["killed_by"][s]]
        input_killed = [r for r in distinguished if r["input_killed_by"][s]]
        summary[s] = {"killed": len(killed), "kill_rate": round(len(killed) / len(distinguished), 4) if distinguished else None,
                      "input_killed": len(input_killed),
                      "input_kill_rate": round(len(input_killed) / len(distinguished), 4) if distinguished else None,
                      "killed_per_made_edit": round(len(killed) / made, 4) if made else None,
                      "by_kind": dict(Counter(r["kind"] for r in killed)),
                      "input_by_kind": dict(Counter(r["kind"] for r in input_killed)),
                      "tests": sum(1 for t in tests if t["suite"] == s),
                      "tests_judging": sum(1 for t in compact if t["suite"] == s), **stats[s]}
    summary["only_reference"] = sum(1 for r in distinguished if r["killed_by"]["reference"] and not r["killed_by"]["generated"])
    summary["only_generated"] = sum(1 for r in distinguished if r["killed_by"]["generated"] and not r["killed_by"]["reference"])
    summary["input_only_reference"] = sum(1 for r in distinguished
                                          if r["input_killed_by"]["reference"] and not r["input_killed_by"]["generated"])
    summary["input_only_generated"] = sum(1 for r in distinguished
                                          if r["input_killed_by"]["generated"] and not r["input_killed_by"]["reference"])
    summary["distinguished_by_kind"] = dict(Counter(r["kind"] for r in distinguished))
    summary["faults_by_kind"] = dict(Counter(r["kind"] for r in results))
    summary["elapsed_s"] = round(time.time() - t0, 1)
    return {"source_roots": [str(r) for r in roots], "reference_path": reference, "generated_path": generated,
            "kind": "interprocedural source-oracle evaluation of interface faults — a model of the code, not a target run",
            "skipped_tests": dict(skipped), "summary": summary, "faults": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--generated", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-faults", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4, help="processes (0 = in this process)")
    args = ap.parse_args(argv)
    roots = [Path(r.strip()) for r in re.split(r"[,;]", args.source_root) if r.strip()]
    from reference_alignment import _guard_output
    _guard_output(Path(args.out), args.reference, roots, inputs=(args.generated,))
    report = evaluate(roots, args.reference, args.generated, args.max_faults or None, args.workers,
                      progress=lambda m: print(m, flush=True))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
