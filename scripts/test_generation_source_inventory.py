"""Measure MC/DC design support on an unchanged source tree, including failures.

This is a capability inventory, not execution coverage or reference superiority.
Declared parameters are the unit inputs. With the project context (default) typedefs, integer
macros, enumerators and globals are resolved from their declarations in the same tree — a global
becomes an input only when its entry value provably survives to the decision. Nothing is guessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _oracle_probe(unit: dict, fn, raw: bytes) -> dict:
    """(R2b) Source oracle capability on one probe vector: every parameter and every modeled object the body names
    set to 0 (in range for every integer type). Outputs: the return value and every modeled object the body writes.
    One vector says what the oracle *can* derive, not what a document's sequences will get."""
    from generators.c_project_context import _function_effects
    from generators.c_source_oracle import evaluate_outputs
    from generators.mcdc_design import _function_name
    scope = unit["project_scope"]
    fx = _function_effects(fn, raw)
    _name, fdecl = _function_name(fn, raw)
    inputs = {}
    for prm in fdecl.child_by_field_name("parameters").named_children if fdecl is not None else []:
        d = prm.child_by_field_name("declarator")
        if d is not None and d.type == "identifier":
            inputs[raw[d.start_byte:d.end_byte].decode("utf-8", errors="replace")] = 0
    arrays, globals_ = scope.get("arrays") or {}, scope.get("globals") or {}
    for name in set(fx["idents"]) | set(fx["writes"]):
        if name in globals_:
            inputs[name] = 0
        elif name in arrays and arrays[name].get("length"):
            inputs.update({f"{name}[{k}]": 0 for k in range(arrays[name]["length"])})
    rtype = raw[fn.child_by_field_name("type").start_byte:fn.child_by_field_name("type").end_byte].decode("utf-8", errors="replace")
    outputs = [] if rtype.strip() == "void" else ["return"]
    for name in fx["writes"]:
        if name in arrays and arrays[name].get("length"):
            outputs.extend(f"{name}[{k}]" for k in range(arrays[name]["length"]))
        else:
            outputs.append(name)
    result = evaluate_outputs(unit, [inputs], [outputs])[0]
    slots = result["outputs"].values()
    return {"status": result["status"], "reason": result.get("reason", ""), "outputs": len(outputs),
            "derived": sum("value" in v for v in slots),
            "assigned": sum(v.get("basis") == "assigned" for v in slots),
            "possible_undefined_behavior": result.get("possible_undefined_behavior") or [],
            "unknown_reasons": dict(Counter(v["reason"].split(":", 1)[0] for v in slots if "reason" in v))}


def inventory(source_root: Path, project_context: bool = True) -> dict:
    from generators.c_project_context import build_project_context, build_scopes
    from generators.mcdc_design import build_mcdc_design
    from workflow.code_parser.c_parser import _make_parser

    parser = _make_parser()
    if parser is None:
        raise RuntimeError("tree_sitter_unavailable")
    scopes, context = {}, None
    if project_context:
        texts, unread = {}, []
        for path in sorted(source_root.rglob("*")):
            if path.suffix.lower() in (".c", ".h") and path.is_file():
                try:
                    texts[str(path.resolve())] = path.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    unread.append(str(path.resolve()))  # not authoritative context — and not a toolchain header
        from generators.c_project_context import detect_build_config
        cproject = Path(source_root) / ".cproject"
        build = detect_build_config({str(cproject): cproject.read_text(encoding="utf-8", errors="replace")}
                                    if cproject.is_file() else {})
        context = build_project_context(texts, build)
        context["incomplete_files"] = unread
        scopes = build_scopes(context, [p for p in texts if p.lower().endswith(".c")])
    files, functions = [], []
    for path in sorted(source_root.rglob("*.c")):
        raw = path.read_bytes()
        # Lossy decoding must not be represented as authoritative complete source.
        try:
            source = raw.decode("utf-8")
            complete = True
        except UnicodeDecodeError:
            source = raw.decode("utf-8", errors="replace")
            complete = False
        root = parser.parse(raw).root_node
        file_record = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                       "parse_error": root.has_error, "utf8_complete": complete,
                       "syntactic_decisions": 0}
        files.append(file_record)

        def text(node):
            return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace") if node else ""

        def visit(node):
            if (node.type in ("if_statement", "while_statement", "for_statement", "do_statement", "conditional_expression")
                    and node.child_by_field_name("condition") is not None):
                file_record["syntactic_decisions"] += 1
            if node.type == "function_definition":
                decl = node.child_by_field_name("declarator")
                while decl and decl.type != "function_declarator":
                    decl = decl.child_by_field_name("declarator")
                name_node = decl.child_by_field_name("declarator") if decl else None
                params_node = decl.child_by_field_name("parameters") if decl else None
                if name_node and name_node.type == "identifier":
                    param_types = {}
                    for param in params_node.named_children if params_node else []:
                        pd = param.child_by_field_name("declarator")
                        if pd and pd.type == "identifier":
                            param_types[text(pd)] = text(param.child_by_field_name("type"))
                    unit = {"name": text(name_node), "input_vars": list(param_types),
                            "param_types": param_types, "source_text": source,
                            "source_path": str(path.resolve()), "source_text_complete": complete,
                            # no fixed SUTS row here: globals the engine binds may join the vector
                            "mcdc_free_globals": True,
                            "source_text_reason": "" if complete else "non_utf8_source"}
                    if str(path.resolve()) in scopes:
                        unit["project_scope"] = scopes[str(path.resolve())]
                    report = build_mcdc_design(unit)
                    record = {"path": str(path.resolve()), "function": unit["name"],
                              "line": node.start_point[0] + 1, "design": report}
                    if unit.get("project_scope"):
                        record["oracle"] = _oracle_probe(unit, node, raw)
                    functions.append(record)
            for child in node.named_children:
                visit(child)
        visit(root)
    decisions = [d for f in functions for d in f["design"].get("decisions", [])]
    located = [d for d in decisions if d.get("expression")]
    reasons = Counter(d.get("reason", "") for d in decisions if d.get("reason"))
    return {"schema_version": 2, "scope": "current source capability inventory; not execution coverage",
            "input_scope": ("declared parameters + declaration-resolved globals whose entry value is bound"
                            if project_context else "declared function parameters only; global-state injection unbound"),
            "project_context": {"enabled": project_context,
                                "target": (context or {}).get("target"),
                                "files": len((context or {}).get("files") or {})},
            "inventory_status": "empty_source" if not files else "partial" if any(f["parse_error"] or not f["utf8_complete"] for f in files) else "parsed",
            "decision_count_is_lower_bound": any(f["parse_error"] for f in files),
            "execution_status": "not_run", "files": files, "functions": functions,
            "summary": {"files": len(files), "functions": len(functions),
                        "syntactic_decisions": sum(f["syntactic_decisions"] for f in files),
                        "parse_error_files": sum(f["parse_error"] for f in files),
                        "non_utf8_files": sum(not f["utf8_complete"] for f in files),
                        "located_decision_entries": len(located),
                        "unlocated_issue_entries": len(decisions) - len(located),
                        "decisions_with_designed_pairs": sum(bool(d.get("pairs")) for d in located),
                        "status_counts": dict(Counter(d.get("status", "") for d in located).most_common()),
                        "compound_decisions": sum(len(d.get("conditions") or []) > 1 for d in located),
                        "compound_fully_paired": sum(len(d.get("conditions") or []) > 1 and d.get("status") == "designed"
                                                     for d in located),
                        # every condition paired, or proven to have no unique-cause pair (identical coupled twin)
                        "compound_paired_or_proven": sum(
                            len(d.get("conditions") or []) > 1 and (d.get("status") == "designed" or
                                                                    str(d.get("reason", "")).startswith("unique_cause_infeasible:"))
                            for d in located),
                        "reason_category_counts": dict(Counter(str(d.get("reason", "")).split(":", 1)[0]
                                                               for d in decisions if d.get("reason")).most_common()),
                        "reason_counts": dict(reasons.most_common()),
                        "source_oracle": _oracle_summary(functions)}}


def _oracle_summary(functions: list[dict]) -> dict | None:
    probes = [f["oracle"] for f in functions if "oracle" in f]
    if not probes:
        return None
    unknown: Counter = Counter()
    for probe in probes:
        unknown.update(probe["unknown_reasons"])
    return {"probe": "one vector per function: every parameter and named modeled object = 0",
            "functions": len(functions), "probed": len(probes),
            "functions_with_derived_output": sum(p["derived"] > 0 for p in probes),
            "functions_with_assigned_derived_output": sum(p["assigned"] > 0 for p in probes),
            "functions_without_outputs": sum(p["outputs"] == 0 for p in probes),
            "functions_unsupported": sum(p["status"] != "supported" for p in probes),
            "function_unsupported_reasons": dict(Counter(p["reason"].split(":", 1)[0] for p in probes
                                                         if p["status"] != "supported").most_common()),
            "outputs": sum(p["outputs"] for p in probes), "outputs_derived": sum(p["derived"] for p in probes),
            "outputs_assigned": sum(p["assigned"] for p in probes),
            "output_unknown_reasons": dict(unknown.most_common())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-project-context", action="store_true",
                        help="scope-less baseline (R1 behavior): project headers are not resolved")
    args = parser.parse_args()
    if not args.source_root.is_dir():
        parser.error("source_root must be an existing directory")
    report = inventory(args.source_root, project_context=not args.no_project_context)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report["summary"].items() if k != "reason_counts"}))


if __name__ == "__main__":
    main()
