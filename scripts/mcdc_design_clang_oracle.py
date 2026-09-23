"""Independent check of MC/DC design pairs with a real C front end (clang, 16-bit-int target).

The engine evaluates decisions itself (``generators/mcdc_design.py`` + ``generators/c_project_context.py``).
This script asks clang to evaluate the *same source text* instead: for every designed pair it emits the
project's scalar typedefs and the unit's object-like macro definitions verbatim, binds each input as
``#define name ((Type)(value))`` and checks, as ``_Static_assert``, the decision outcome and every condition's
truth the engine claims. Nothing runs on a target — clang folds the constant expressions with the target's
integer model (``--target``; msp430 has the S12Z widths: char 8, short 16, int 16, long 32).

It is a check of expression semantics only (promotions, conversions, macro values, short-circuit truth), not
of reachability or execution. What is *not* independent here: enumerator and const-object values and the scalar
typedefs are emitted from the engine's resolution; enum-typed inputs are bound as ``int`` (the engine's model);
the preprocessor configuration (which ``#if`` arm is active) and input binding (writes before the decision) are
the engine's claims and are not checked by this oracle.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _decisions(source_root: Path):
    from generators.c_project_context import build_project_context, build_scopes
    from generators.mcdc_design import build_mcdc_design
    from workflow.code_parser.c_parser import _make_parser

    texts = {}
    for path in sorted(source_root.rglob("*")):
        if path.suffix.lower() in (".c", ".h") and path.is_file():
            try:
                texts[str(path.resolve())] = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
    context = build_project_context(texts)
    units = [p for p in texts if p.lower().endswith(".c")]
    scopes = build_scopes(context, units)
    parser = _make_parser()
    for path in units:
        raw = texts[path].encode("utf-8")
        stack = [parser.parse(raw).root_node]
        while stack:
            node = stack.pop()
            stack.extend(node.named_children)
            if node.type != "function_definition":
                continue
            decl = node.child_by_field_name("declarator")
            while decl is not None and decl.type != "function_declarator":
                decl = decl.child_by_field_name("declarator")
            name_node = decl.child_by_field_name("declarator") if decl is not None else None
            if name_node is None or name_node.type != "identifier":
                continue
            params = []
            plist = decl.child_by_field_name("parameters")
            for p in plist.named_children if plist is not None else []:
                d = p.child_by_field_name("declarator")
                if d is not None and d.type == "identifier":
                    params.append(raw[d.start_byte:d.end_byte].decode())
            unit = {"name": raw[name_node.start_byte:name_node.end_byte].decode(), "input_vars": params,
                    "source_text": texts[path], "source_path": path, "source_text_complete": True, "mcdc_free_globals": True,
                    "project_scope": scopes[path]}
            yield path, unit, build_mcdc_design(unit), context, scopes[path]


def _prelude(context, scope):
    """Scalar typedefs of the unit and its macros, as written in the source."""
    lines = ["/* generated: independent evaluation of engine MC/DC claims */"]
    typedef_lines = []
    for name, t in scope["types"].items():
        if " " in name or name.startswith("enum ") or t.get("enum"):
            continue
        base = {"char": "char", "short": "short", "int": "int", "long": "long", "_Bool": "_Bool",
                "float": "float", "double": "double"}[t["kind"]]
        if t["kind"] not in ("_Bool", "float", "double"):
            base = ("signed " if t["signed"] else "unsigned ") + base
        typedef_lines.append(f"typedef {base} {name};")
    lines += sorted(typedef_lines)
    for name, c in scope["constants"].items():
        if c.get("kind") == "macro":
            body = None
            for defs in (context["files"].get(c["file"]) or {}).get("macros", {}).get(name, []):
                if defs.get("line") == c.get("line"):
                    body = defs["body"]
            if body is not None:
                lines.append(f"#define {name} {body}")
        else:  # enumerators / const objects: engine values (not an independent check of those)
            lines.append(f"#define {name} ({c['value']})")
    return lines


def _checks(path, report):
    """(label, expression text, expected int) for every retained design claim of a decision."""
    domains = report["domains"]
    for decision in report["decisions"]:
        for pair in decision.get("pairs") or []:
            for side in ("a", "b"):
                inputs = pair[f"inputs_{side}"]
                # An enum-typed input is bound as ``int`` (the engine's model of an enumeration object).
                binds = [f"#define {n} (({'int' if (domains[n].get('ctype') or {}).get('enum') else domains[n]['type']})({v}))"
                         for n, v in sorted(inputs.items()) if n in domains]
                label = f"{Path(path).name}:{report['function']}:{pair['pair_id']}:{side}"
                exprs = [("decision", decision["expression"], int(pair[f"decision_{side}"]))]
                for cond, truth in zip(decision["conditions"], pair[f"truth_{side}"], strict=True):
                    exprs.append((cond["condition_id"], cond["expression"], int(truth)))
                yield label, binds, exprs, list(inputs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source_root", type=Path)
    ap.add_argument("--target", default="msp430", help="clang target with the ECU's integer widths")
    ap.add_argument("--clang", default="clang")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    results = {"target": args.target, "units": 0, "pairs_checked": 0, "claims_checked": 0, "mismatches": [],
               "compile_errors": [], "scope": "expression semantics only; not execution, not reachability"}
    by_unit: dict[str, list] = {}
    for path, _unit, report, context, scope in _decisions(args.source_root):
        entries = list(_checks(path, report))
        if not entries:
            continue
        by_unit.setdefault(path, [context, scope, []])[2].extend(entries)
    with tempfile.TemporaryDirectory() as tmp:
        for path, (context, scope, entries) in by_unit.items():
            results["units"] += 1
            lines = _prelude(context, scope)
            index = {}
            for label, binds, exprs, names in entries:
                results["pairs_checked"] += 1
                lines += binds
                for cid, expr, expected in exprs:
                    results["claims_checked"] += 1
                    tag = f"C{len(index)}"
                    index[tag] = {"claim": f"{label}:{cid}", "expected": expected, "expression": " ".join(expr.split())}
                    lines += ["_Static_assert((", expr, f") == {expected}, \"{tag}\");"]
                lines += [f"#undef {n}" for n in names]
            # Self-check: one deliberately false claim per file. If the run does not report it, the failure
            # parsing is broken and a real mismatch would pass silently — the unit counts as an oracle error.
            lines += ["_Static_assert((", "1 + 1", ') == 3, "SENTINEL");']
            src = Path(tmp) / (Path(path).stem + "_oracle.c")
            src.write_text("\n".join(lines) + "\n", encoding="utf-8")
            proc = subprocess.run([args.clang, f"--target={args.target}", "-std=c11", "-fsyntax-only",
                                   "-ferror-limit=0", "-Wno-everything", str(src)],
                                  capture_output=True, text=True, timeout=300)
            # clang: "error: static assertion failed due to requirement '...': C12" (message unquoted)
            failed = set(re.findall(r"static assertion failed.*?:\s*(C\d+|SENTINEL)\s*$", proc.stderr, re.M))
            if "SENTINEL" not in failed:
                results["compile_errors"].append({"unit": Path(path).name, "errors": ["sentinel_not_reported"], "count": 1})
            failed.discard("SENTINEL")
            results["mismatches"] += [index[t] for t in sorted(failed, key=lambda x: int(x[1:]))]
            other = [ln for ln in proc.stderr.splitlines() if "error:" in ln and "static assertion failed" not in ln]
            if other:
                results["compile_errors"].append({"unit": Path(path).name, "errors": other[:5], "count": len(other)})
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in results.items()}
    print(json.dumps(summary))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if results["mismatches"] or results["compile_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
