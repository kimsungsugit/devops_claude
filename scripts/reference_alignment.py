"""Offline alignment of a reference SUTS with the current source (R3 — no SVN access).

The reference unit-test specification was written against a source revision we cannot check out. Instead of a revision
diff, every reference sequence is re-evaluated on the *current* source by the source oracle
(`generators/c_source_oracle.py`) and each expected value the reference states is compared with what the current
source computes for the same inputs:

* ``agree``      — the oracle derives the reference's value;
* ``disagree``   — the oracle derives a different value (the source changed since the reference, the reference is wrong,
                   or the oracle's model is — with ``--clang`` each derived value is re-checked by clang constant
                   evaluation, so a clang-confirmed disagreement is a statement about the source, not the model);
* ``not_comparable`` — the oracle does not determine the slot (its reason is kept), or the reference value is not an
                   integer (``-``, register fields, text).

Per reference unit: ``aligned`` (≥ 1 comparable slot, all agree, and at least one agreeing value the function
*computed* — not only an input it left unchanged), ``echo_only`` (every agreement is an input the function did not
write: it says nothing about the code), ``divergent`` (≥ 1 disagreement), ``unknown`` (nothing comparable — the reasons
are kept), ``no_reference_expectation`` (the reference states no expected value for the unit), ``ambiguous_definition``
(several definitions of the name, none preferred by the evidence), ``not_in_source`` / ``definition_not_parsed`` (no
parsed definition now), ``no_sequences`` (the unit has no test sequence), ``error:<type>`` (the evaluation raised —
the unit is kept, the run goes on). ``aligned`` means only that the sampled vectors agree — it is the unit range where
a reference comparison (R4, R9) is meaningful, not a proof that the function is unchanged. Agreements are split by
basis (``assigned`` / ``unchanged_input``); ``agree_via_reference_symbol`` counts, *within* them, the agreements where
the reference wrote a name the current source resolves (its value today, not when the reference was written). The
evidence strength (agreeing / all stated slots) is reported per unit.

Inputs outside the declared type (the reference writes ``-1`` into a ``U8``) are converted the way C converts the value
assigned to that object (``-1`` → ``255``) — that is what a test harness assignment does — and every distinct
conversion is listed per unit (``input_conversions`` with a count). Inputs that are not integers (an enumerator name)
are resolved through the unit's constants; anything else is passed as is (the oracle then reports
``input_not_an_integer``).

A name defined more than once (the application and the boot loader both define ``EEPROM_Init``) is evaluated on every
definition. Only a definition with comparable slots can claim the unit; the one with the most agreements wins and keeps
its disagreements (a definition is never chosen for having none). When several share the most agreements the path is
ambiguous: every one of them disagreeing makes the unit ``divergent`` (the reference differs from the source whichever
it belongs to), some disagreeing makes it ``ambiguous_definition`` with those disagreements kept, none makes it
``ambiguous_definition`` — never ``aligned``. Every candidate's counts are kept.

Usage:
    .venv/Scripts/python.exe scripts/reference_alignment.py --reference REF.xlsm --source-root ROOT --out out.json [--clang]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_INT = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*")


def reference_value(value: Any, constants: dict | None = None) -> int | None:
    """An integer the reference cell states, else None (``-``, ``N/A``, register text, floats)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value or "").strip()
    if _INT.fullmatch(text):
        text = text.rstrip("uUlL")
        return int(text, 16) if "x" in text.lower() else int(text, 10)
    if constants is not None and text in constants and isinstance(constants[text].get("value"), int):
        return constants[text]["value"]
    return None


def _object_type(scope: dict, fn_params: dict, name: str):
    """C type of an input name: a parameter, a scalar global or an array element ``a[k]`` (None if unmodeled)."""
    m = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", name.strip())
    if not m:
        return None
    base, index = m.group(1), m.group(2)
    if index is None and base in fn_params:
        return fn_params[base]
    if index is None and base in (scope.get("globals") or {}):
        return scope["globals"][base]["type"]
    if index is not None and base in (scope.get("arrays") or {}):
        return scope["arrays"][base]["type"]
    return None


def _convert_inputs(scope: dict, fn_params: dict, inputs: dict) -> tuple[dict, list]:
    """Reference inputs as the objects would hold them after assignment; conversions are returned for disclosure."""
    from generators import c_project_context as cpc
    constants = scope.get("constants") if scope.get("constants") is not None else {}
    out, converted = {}, []
    for name, raw in (inputs or {}).items():
        value = reference_value(raw, constants)
        if value is None:
            out[name] = raw
            continue
        t = _object_type(scope, fn_params, name)
        if isinstance(t, dict) and not cpc.is_float(t) and not t.get("enum"):
            lo, hi = (0, 1) if t.get("kind") == "_Bool" else cpc.type_range(t)
            if not lo <= value <= hi:
                try:
                    held = cpc.convert(value, t)
                except cpc.Unresolved:
                    out[name] = value
                    continue
                converted.append({"input": name, "reference": value, "held": held})
                value = held
        out[name] = value
    return out, converted


def _load_source(roots: list[Path]) -> tuple[dict, dict, list]:
    from generators.c_project_context import build_project_context, detect_build_config
    texts, unread = {}, []
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() in (".c", ".h") and p.is_file():
                try:
                    texts[str(p.resolve())] = p.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    unread.append(str(p.resolve()))
    cprojects = {str(r / ".cproject"): (r / ".cproject").read_text(encoding="utf-8", errors="replace")
                 for r in roots if (r / ".cproject").is_file()}
    context = build_project_context(texts, detect_build_config(cprojects), roots=[str(r.resolve()) for r in roots])
    context["incomplete_files"] = unread
    return texts, context, unread


def _definitions(texts: dict) -> dict[str, list[str]]:
    """Function name → files that define it (by parse, not by text search)."""
    from generators.mcdc_design import _function_name
    from workflow.code_parser.c_parser import _make_parser
    parser = _make_parser()
    out: dict[str, list[str]] = {}
    for path, text in texts.items():
        if not path.lower().endswith(".c"):
            continue
        raw = text.encode()
        stack = [parser.parse(raw).root_node]
        while stack:
            n = stack.pop()
            if n.type == "function_definition":
                name = _function_name(n, raw)[0]
                if name:
                    out.setdefault(name, []).append(path)
                continue
            stack.extend(n.named_children)
    return out


def _param_types(unit: dict) -> dict:
    """Declared scalar parameter types of the unit's function (as the oracle resolves them)."""
    from generators import c_project_context as cpc
    from generators.c_source_oracle import Unsupported, _parsed_function
    from generators.mcdc_design import _function_name, _scope_type
    scope = unit["project_scope"]
    raw = unit["source_text"].encode()
    try:
        _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, unit["name"], scope)
    except Unsupported:
        return {}  # the oracle refuses this function anyway (its reason is on every slot): inputs pass unconverted
    _name, fdecl = _function_name(fn, raw)
    out = {}
    for p in fdecl.child_by_field_name("parameters").named_children if fdecl is not None else []:
        d, typ = p.child_by_field_name("declarator"), p.child_by_field_name("type")
        if d is None or typ is None or d.type != "identifier":
            continue
        try:
            out[raw[d.start_byte:d.end_byte].decode()] = _scope_type(scope, raw[typ.start_byte:typ.end_byte].decode())
        except cpc.Unresolved:
            continue
    return out


def _clang_confirm(claims: list[dict], clang_exe: str) -> Counter:
    """Re-check each disagreeing derived value with clang (one harness per claim): ``clang`` on the disagreement entry is
    ``confirms_source_value`` (the current source computes the value the oracle says — the reference differs from the
    source), ``confirms_with_stubbed_callees`` (the same, but the function calls others whose effects clang took from
    the oracle's stubs — not independent there), ``contradicts_oracle`` (an oracle defect: its value is not what clang
    computes), ``eval_error`` or ``unchecked:<reason>``. Returns the verdict counts."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from source_oracle_clang_check import check_claims
    verdicts = Counter()
    for claim in claims:
        entry = claim.pop("_entry")
        try:
            report = check_claims([claim], clang=clang_exe)
        except Exception as exc:  # noqa: BLE001 — one harness failure must not lose the whole report (review r2 Info 4)
            entry["clang"] = f"error:{type(exc).__name__}"
            verdicts[entry["clang"]] += 1
            continue
        if report["agree"]:
            stubbed = report.get("agree_with_stubbed_callees")
            entry["clang"] = "confirms_with_stubbed_callees" if stubbed else "confirms_source_value"
        elif report["mismatch"]:
            entry["clang"] = "contradicts_oracle"
        elif report["eval_error"]:
            entry["clang"] = "eval_error"
        elif report["unchecked_reasons"]:
            entry["clang"] = "unchecked:" + ",".join(sorted(report["unchecked_reasons"]))
        else:
            entry["clang"] = "unchecked"
        verdicts[entry["clang"]] += 1
    return verdicts


def _choose_definition(candidates: list[dict]) -> tuple[dict | None, list[dict]]:
    """(R3 review C1, round 2 W-A) The definition a reference unit belongs to: only candidates with comparable slots may
    claim it, and only by agreements — fewer disagreements never break a tie (that would pick the definition for
    hiding one). Returns ``(chosen, tied)``: ``chosen`` when one candidate has the most agreements, else ``None`` with
    the candidates sharing that count (empty when nothing is comparable)."""
    comparable = [c for c in candidates if c["slots"]["agree"] + c["slots"]["disagree"]]
    if not comparable:
        return None, []
    top = max(c["slots"]["agree"] for c in comparable)
    tied = [c for c in comparable if c["slots"]["agree"] == top]
    return (tied[0], tied) if len(tied) == 1 else (None, tied)


def _guard_output(out: Path, reference: str, roots: list[Path], inputs: tuple[str, ...] = ()) -> None:
    """(R3 review Info 6) Never write the report into the read-only inputs (the reference's folder, a source tree) nor
    over another input file of the run."""
    target = out.resolve()
    if any(target == Path(p).resolve() for p in inputs if p):
        raise SystemExit(f"refusing to write {target}: it is an input of this run")
    for protected in [Path(reference).resolve().parent, *(r.resolve() for r in roots)]:
        if target == protected or protected in target.parents:
            raise SystemExit(f"refusing to write {target}: inside read-only input {protected}")


def align(reference: str, roots: list[Path], clang: bool = False, clang_exe: str = "clang") -> dict:
    from generators.c_project_context import build_scopes
    from generators.c_source_oracle import evaluate_outputs
    from tools.export_suts_vectorcast import bare_fn_name, build_vectorcast_model
    model = build_vectorcast_model(reference)
    texts, context, unread = _load_source(roots)
    definitions = {name: sorted(set(paths)) for name, paths in _definitions(texts).items()}
    needed = sorted({path for u in model["units"] for path in definitions.get(bare_fn_name(u["unit_name"]), [])})
    scopes = build_scopes(context, needed)
    functions, claims, slot_counts = [], [], Counter()

    def compare(ref_unit, name, path):
        """Evaluate the reference sequences on one definition."""
        unit = {"name": name, "source_text": texts[path], "source_path": path, "source_text_complete": True,
                "project_scope": scopes[path]}
        params = _param_types(unit)
        constants = scopes[path].get("constants") if scopes[path].get("constants") is not None else {}
        vectors, outs, conversions = [], [], []
        for case in ref_unit["test_cases"]:
            inputs, converted = _convert_inputs(scopes[path], params, case.get("inputs") or {})
            vectors.append(inputs)
            outs.append(list((case.get("expected") or {}).keys()))
            conversions.append(converted)
        slots, reasons, bases, disagreements, found = Counter(), Counter(), Counter(), [], []
        via_symbol = 0
        for case, inputs, converted, result in zip(ref_unit["test_cases"], vectors, conversions,
                                                    evaluate_outputs(unit, vectors, outs), strict=True):
            for slot, expected_raw in (case.get("expected") or {}).items():
                expected = reference_value(expected_raw, constants)
                got = result["outputs"].get(slot) or {}
                if expected is None:
                    # the reference states no integer here: nothing to compare, whatever the oracle says (r2 Info 1)
                    kind = "not_comparable"
                    reasons["reference_value_not_integer"] += 1
                elif "value" not in got:
                    kind = "not_comparable"
                    reasons[str(got.get("reason", "")).split(":", 1)[0]] += 1
                elif got["value"] == expected:
                    kind = "agree"
                    # (review W1) an input left unchanged "agrees" without the code doing anything
                    bases[str(got.get("basis") or "unknown")] += 1
                    if reference_value(expected_raw) is None:
                        # a name the reference wrote agrees through its *current* value (review Info 5) — counted
                        # within the bases above, not as one more basis (review r2 W-E)
                        via_symbol += 1
                else:
                    kind = "disagree"
                    entry = {"sequence": case.get("sequence_no"), "output": slot, "reference": expected,
                             "source": got["value"], "basis": got.get("basis"), "inputs": inputs,
                             "input_conversions": converted,
                             "possible_ub": result.get("possible_undefined_behavior") or []}
                    disagreements.append(entry)
                    found.append({"unit": unit, "inputs": inputs, "outputs": {slot: got["value"]},
                                  "possible_ub": entry["possible_ub"], "_entry": entry})
                slots[kind] += 1
        distinct = Counter((c["input"], c["reference"], c["held"]) for cs in conversions for c in cs)
        return {"path": path, "slots": slots, "reasons": reasons, "bases": bases, "via_symbol": via_symbol,
                "disagreements": disagreements, "claims": found,
                "conversions": [{"input": i, "reference": r, "held": h, "count": n} for (i, r, h), n in distinct.items()]}

    def summarize(candidate):
        return {"path": candidate["path"], **{k: candidate["slots"][k] for k in ("agree", "disagree", "not_comparable")},
                "top_reason": candidate["reasons"].most_common(1)[0][0] if candidate["reasons"] else ""}

    for ref_unit in model["units"]:
        name = bare_fn_name(ref_unit["unit_name"])
        cases = ref_unit["test_cases"]
        # (review W5) the unit key: the reference's TC ID; the Related ID is ``fid`` (``SwUFn_2105``)
        record = {"function": name, "reference_signature": ref_unit["unit_name"],
                  "tc_id": (cases[0].get("base_tc_id") if cases else "") or "", "related_id": ref_unit.get("fid") or "",
                  "sequences": len(cases), "slots": {}, "unknown_reasons": {}, "disagreements": [],
                  "input_conversions": []}
        functions.append(record)
        if not cases:
            record["status"] = "no_sequences"  # (review r2 Info 2)
            continue
        if not any(case.get("expected") for case in cases):
            record["status"] = "no_reference_expectation"  # (review W3) nothing to compare — not "unknown"
            continue
        where = definitions.get(name, []) if name else []
        if not where:
            named = name and any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", t)
                                 for p, t in texts.items() if p.lower().endswith(".c"))
            # named in a .c file but no parsed definition: ``ISR(Cpu_Interrupt) { ... }`` — a macro forms it
            record["status"] = "definition_not_parsed" if named else "not_in_source"
            continue
        candidates, failed = [], []
        for path in where:
            try:
                candidates.append(compare(ref_unit, name, path))
            except Exception as exc:  # noqa: BLE001 — one defect must not end the run nor vanish (review Info 2)
                failed.append({"path": path, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        if failed:
            record["failed_definitions"] = failed
        if not candidates:
            record["status"] = f"error:{failed[0]['error'].split(':', 1)[0]}"
            continue
        if len(where) > 1:
            record["defined_in"] = where
            record["candidates"] = [summarize(c) for c in candidates]
            chosen, tied = _choose_definition(candidates)
            if chosen is None:
                record["matched_definition"] = ""
                # per candidate: summing them would count every slot once per definition (review r2 Info 3)
                record["unknown_reasons_by_definition"] = {c["path"]: dict(c["reasons"].most_common())
                                                           for c in candidates}
                if not tied:
                    record["status"] = "unknown"
                    continue
                # (review r2 W-A / W-B) equal agreement: which definition is unknown, the disagreements are not
                disagreeing = [c for c in tied if c["slots"]["disagree"]]
                record["status"] = "divergent" if len(disagreeing) == len(tied) else "ambiguous_definition"
                record["tied_definitions"] = [c["path"] for c in tied]
                record["disagreements"] = [dict(e, definition=c["path"]) for c in disagreeing for e in c["disagreements"]]
                if clang:
                    claims.extend(claim for c in disagreeing for claim in c["claims"])
                continue
            record["matched_definition"] = chosen["path"]
        else:
            chosen = candidates[0]
        slots, bases = chosen["slots"], chosen["bases"]
        record.update(source_path=chosen["path"],
                      source_sha256=hashlib.sha256(texts[chosen["path"]].encode()).hexdigest(),
                      slots=dict(slots), agree_basis=dict(bases), agree_via_reference_symbol=chosen["via_symbol"],
                      unknown_reasons=dict(chosen["reasons"].most_common()),
                      disagreements=chosen["disagreements"], input_conversions=chosen["conversions"],
                      evidence_strength=round(slots["agree"] / sum(slots.values()), 4) if sum(slots.values()) else None)
        if clang:
            claims.extend(chosen["claims"])
        for kind, n in slots.items():
            slot_counts[kind] += n
        if slots["disagree"]:
            record["status"] = "divergent"
        elif slots["agree"]:
            computed = slots["agree"] - bases.get("unchanged_input", 0)
            record["status"] = "aligned" if computed > 0 else "echo_only"
        else:
            record["status"] = "unknown"
    verdicts = _clang_confirm(claims, clang_exe) if clang and claims else Counter()
    status = Counter(f["status"] for f in functions)
    aligned = [f for f in functions if f["status"] == "aligned"]
    names = Counter(f["function"] for f in functions)
    return {
        "reference": reference, "reference_sha256": hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
        "source_roots": [str(r) for r in roots], "unreadable_source_files": unread,
        "method": "reference vectors re-evaluated on the current source by the source oracle (no SVN revision)",
        "execution_status": "not_run",
        "summary": {"functions": len(functions), "status": dict(status.most_common()), "slots": dict(slot_counts),
                    "agree_basis": dict(sum((Counter(f.get("agree_basis") or {}) for f in functions), Counter())),
                    "agree_via_reference_symbol": sum(f.get("agree_via_reference_symbol") or 0 for f in functions),
                    # units whose slots are not in ``slots`` (no single definition to count them against)
                    "units_without_slot_totals": sum(1 for f in functions if f.get("tied_definitions")
                                                     or f.get("unknown_reasons_by_definition")),
                    "multiply_defined_units": sum(1 for f in functions if f.get("defined_in")),
                    # (review W5) names the reference uses for more than one unit: consumers keyed by name must not
                    # merge them
                    "duplicate_reference_names": sorted(n for n, k in names.items() if k > 1),
                    "unreadable_source_files": len(unread),
                    "clang": dict(verdicts) if clang else None,
                    "aligned_functions": sorted({f["function"] for f in aligned}),
                    "aligned_units": [{"function": f["function"], "tc_id": f["tc_id"], "source_path": f["source_path"]}
                                      for f in aligned],
                    "divergent_functions": sorted({f["function"] for f in functions if f["status"] == "divergent"})},
        "functions": functions,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reference", required=True, help="reference SUTS workbook (read-only)")
    ap.add_argument("--source-root", required=True, help="current source root(s), ',' or ';' separated")
    ap.add_argument("--out", required=True)
    ap.add_argument("--clang", action="store_true", help="re-check every disagreeing derived value with clang")
    ap.add_argument("--clang-exe", default="clang")
    args = ap.parse_args(argv)
    roots = [Path(r.strip()) for r in re.split(r"[,;]", args.source_root) if r.strip()]
    _guard_output(Path(args.out), args.reference, roots)
    report = align(args.reference, roots, clang=args.clang, clang_exe=args.clang_exe)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    s = report["summary"]
    print(json.dumps({k: s[k] for k in ("status", "slots", "agree_basis", "agree_via_reference_symbol",
                                        "multiply_defined_units",
                                        "duplicate_reference_names", "unreadable_source_files", "clang")},
                     ensure_ascii=False))
    errors = sum(n for k, n in s["status"].items() if k.startswith("error:"))
    return 1 if errors or (s["clang"] or {}).get("contradicts_oracle") else 0


if __name__ == "__main__":
    raise SystemExit(main())
