"""Bounded, unique-cause MC/DC design over concrete declared integer inputs.

These are expression-level design pairs, not measured program coverage.
Reachability at the source occurrence remains explicitly unverified.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from typing import Any

from generators.c_test_semantics import _TYPES
from workflow.code_parser.c_parser import _make_parser

# Source-level failures that prevent listing a function's decisions at all.
_ENUMERATION_FAILURES = frozenset({
    "tree_sitter_unavailable", "source_budget", "source_parse_error", "source_ast_budget",
    "function_identity_missing_or_ambiguous", "source_text_incomplete", "source_exception",
})


class Unsupported(ValueError):
    """Unsupported expression or unproven input binding."""


def _walk(node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(reversed(item.named_children))


def _text(node, raw):
    return raw[node.start_byte:node.end_byte].decode()


def _unwrap(node):
    while node.type == "parenthesized_expression":
        children = [c for c in node.named_children if c.type != "comment"]
        if len(children) != 1:
            raise Unsupported("unsupported_parenthesized_expression")
        node = children[0]
    return node


def _display_expression(node, raw):
    """The decision text without the ``if (...)`` clause parentheses (re-evaluable as is)."""
    if node is None:
        return ""
    try:
        return _text(_unwrap(node), raw)
    except Unsupported:
        return _text(node, raw)


def _compile(node, raw, domains):
    atoms, variables, constants = [], set(), set()
    def scalar(n):
        n = _unwrap(n)
        text = _text(n, raw)
        if n.type == "identifier":
            if text not in domains:
                raise Unsupported("missing_declared_domain:" + text)
            variables.add(text)
            return ("var", text)
        if n.type == "number_literal" and re.fullmatch(r"(?:0|[1-9][0-9]*|0[xX][0-9a-fA-F]+)", text):
            value = int(text, 16 if "x" in text.lower() else 10)
            if value > 32767:
                raise Unsupported("literal_target_type_unresolved")
            constants.add(value)
            return ("constant", value)
        if n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) in {"+", "-"}:
            arg = scalar(n.child_by_field_name("argument"))
            if arg[0] != "constant":
                raise Unsupported("arithmetic_operand_unsupported")
            value = arg[1] if text.lstrip().startswith("+") else -arg[1]
            constants.add(value)
            return ("constant", value)
        raise Unsupported("unsupported_scalar:" + n.type)
    def bounds(term):
        if term[0] == "constant":
            return term[1], term[1]
        d = domains[term[1]]
        return d.get("type_min", d["min"]), d.get("type_max", d["max"])
    def build(n):
        n = _unwrap(n)
        if n.type == "binary_expression":
            op = _text(n.child_by_field_name("operator"), raw)
            if op in {"&&", "||"}:
                return (op, build(n.child_by_field_name("left")), build(n.child_by_field_name("right")))
            if op not in {"<", "<=", ">", ">=", "==", "!="}:
                raise Unsupported("unsupported_atom_operator:" + op)
            left, right = scalar(n.child_by_field_name("left")), scalar(n.child_by_field_name("right"))
            lb, rb = bounds(left), bounds(right)
            if (lb[0] == 0 and lb[1] > 32767 and rb[0] < 0) or (rb[0] == 0 and rb[1] > 32767 and lb[0] < 0):
                raise Unsupported("target_dependent_unsigned_comparison")
            atom = (op, left, right)
        elif n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "!":
            return ("!", build(n.child_by_field_name("argument")))
        else:
            atom = ("truth", scalar(n))
        index = len(atoms)
        atoms.append({"condition_id": f"C{index + 1}", "expression": _text(n, raw), "_atom": atom})
        return ("atom", index)
    ir = build(node)
    return ir, atoms, sorted(variables), constants


def _atom_truth(atom, inputs):
    def scalar(term):
        return inputs[term[1]] if term[0] == "var" else term[1]
    a = scalar(atom[1])
    if atom[0] == "truth":
        return bool(a)
    b = scalar(atom[2])
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[atom[0]]


def _atom_variables(atom):
    return [term[1] for term in atom[1:] if term[0] == "var"]


def _evaluate(ir, atoms, inputs):
    truth = [_atom_truth(condition["_atom"], inputs) for condition in atoms]
    observed = [False] * len(atoms)
    def visit(node):
        if node[0] == "atom":
            observed[node[1]] = True
            return truth[node[1]]
        if node[0] == "!":
            return not visit(node[1])
        if node[0] == "&&":
            return visit(node[1]) and visit(node[2])
        return visit(node[1]) or visit(node[2])
    return truth, bool(visit(ir)), observed


def evaluate_decision(expression: str, inputs: dict[str, int], domains: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate pure integer decision truth and short-circuit observations.

    Domain metadata must describe explicit integer declarations. This helper
    verifies expression mathematics only; it cannot authenticate source or
    prove reachability or target execution.
    """
    try:
        parser = _make_parser()
        if parser is None or len(expression) > 20000:
            raise Unsupported("parser_unavailable_or_expression_budget")
        raw = ("int probe(void) { if (" + expression + ") return 1; return 0; }").encode()
        root = parser.parse(raw).root_node
        if root.has_error:
            raise Unsupported("expression_parse_error")
        condition = next(n.child_by_field_name("condition") for n in _walk(root) if n.type == "if_statement")
        if _text(condition, raw) != "(" + expression + ")":
            raise Unsupported("expression_not_consumed_completely")
        ir, atoms, variables, _ = _compile(condition, raw, domains)
        if len(atoms) > 64:
            raise Unsupported("condition_budget")
        for name in variables:
            if type(inputs.get(name)) is not int or not domains[name]["min"] <= inputs[name] <= domains[name]["max"]:
                raise Unsupported("input_outside_declared_domain:" + name)
        truth, decision, observed = _evaluate(ir, atoms, inputs)
        return {"status": "supported", "truth": truth, "decision": decision, "observed": observed,
                "conditions": [{k: v for k, v in c.items() if not k.startswith("_")} for c in atoms],
                "execution_status": "not_run", "reachability": "unverified"}
    except (Unsupported, ValueError, KeyError, TypeError, AttributeError, RecursionError, StopIteration) as exc:
        return {"status": "unsupported", "reason": str(exc), "execution_status": "not_run"}


def _default_value(domain):
    """Value for an input the decision does not read: an enumerator if the domain is enumerated, else closest to 0."""
    if domain.get("values"):
        return min(domain["values"], key=lambda v: (abs(v), v))
    return max(domain["min"], min(0, domain["max"]))


def _realizable_truths(atoms, variables, values, defaults, budget):
    """Per variable-connected component, the atom truth tuples real inputs can realize.

    Atoms sharing a variable are searched together, so shared-variable
    constraints (``a > 10 && a < 20``) stay exact; independent components are
    combined afterwards instead of enumerating their full cartesian product.
    """
    parent = {name: name for name in variables}
    def root(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name
    for condition in atoms:
        names = _atom_variables(condition["_atom"])
        for other in names[1:]:
            parent[root(other)] = root(names[0])
    groups = {}
    for position, name in enumerate(variables):
        groups.setdefault(root(name), []).append(position)
    components, complete, evaluated = [], True, 0
    for positions in groups.values():
        names = [variables[p] for p in positions]
        member_atoms = [i for i, c in enumerate(atoms) if set(_atom_variables(c["_atom"])) & set(names)]
        realized = {}
        space = math.prod(len(values[p]) for p in positions)
        for vector in itertools.islice(itertools.product(*(values[p] for p in positions)), max(0, budget)):
            evaluated += 1
            assignment = dict(zip(names, vector, strict=True))
            probe = {**defaults, **assignment}
            realized.setdefault(tuple(_atom_truth(atoms[i]["_atom"], probe) for i in member_atoms), assignment)
            if len(realized) == 2 ** len(member_atoms):
                break
        else:
            complete = complete and space <= max(0, budget)
        components.append(list(realized.values()))
    return components, complete, evaluated


def _source_decisions(unit, declared_domains=None):
    source = str(unit.get("source_text") or "")
    source_kind = "source" if source else "logic_flow"
    # Incompleteness only matters for text we actually read; without text the flow path decides on its own merits.
    issue = "source_text_incomplete" if source and not unit.get("source_text_complete", True) else ""
    declared_domains = declared_domains or {}
    domains = {}
    parser = _make_parser()
    if parser is None:
        return [], {}, source_kind, "", "tree_sitter_unavailable"
    if source:
        if not unit.get("source_text_complete", True):
            issue = "source_text_incomplete"
        if len(source) > 2_000_000:
            return [], {}, source_kind, "", "source_budget"
        raw = source.encode()
        root = parser.parse(raw).root_node
        if root.has_error:
            return [], {}, source_kind, hashlib.sha256(raw).hexdigest(), "source_parse_error"
        nodes = list(_walk(root))
        if len(nodes) > 50000:
            return [], {}, source_kind, hashlib.sha256(raw).hexdigest(), "source_ast_budget"
        includes = {_text(n.child_by_field_name("path"), raw) for n in nodes if n.type == "preproc_include"}
        types = {"int": (-32767, 32767), "signed int": (-32767, 32767), "_Bool": (0, 1)}
        if "<stdint.h>" in includes:
            types.update(_TYPES)
        if "<stdbool.h>" in includes:
            types["bool"] = (0, 1)
        if includes - {"<stdint.h>", "<stdbool.h>"} or any(n.type.startswith("preproc_") and n.type != "preproc_include" for n in nodes):
            issue = issue or "preprocessor_context_unresolved"
        for n in root.named_children:
            if n.type == "type_definition":
                typ, ident = n.child_by_field_name("type"), n.child_by_field_name("declarator")
                if ident is None or ident.type != "type_identifier" or _text(typ, raw) not in types or _text(ident, raw) in types or len(n.named_children) != 2:
                    issue = issue or "typedef_context_unresolved"
                else:
                    types[_text(ident, raw)] = types[_text(typ, raw)]
        functions = []
        for n in root.named_children:
            if n.type == "function_definition":
                d = n.child_by_field_name("declarator")
                ident = d.child_by_field_name("declarator") if d else None
                if ident and _text(ident, raw) == unit.get("name"):
                    functions.append(n)
        if len(functions) != 1:
            return [], {}, source_kind, hashlib.sha256(raw).hexdigest(), "function_identity_missing_or_ambiguous"
        fn = functions[0]
        params = fn.child_by_field_name("declarator").child_by_field_name("parameters")
        for p in params.named_children:
            if len(params.named_children) == 1 and _text(p, raw) == "void":
                continue
            ident, typ = p.child_by_field_name("declarator"), p.child_by_field_name("type")
            plain = ident is not None and ident.type == "identifier" and len(p.named_children) == 2
            caller = declared_domains.get(_text(ident, raw)) if plain else None
            if plain and _text(typ, raw) not in types and caller and caller.get("origin") == "parameter":
                # The source cannot resolve this parameter's type (project typedef/enum); the caller resolved
                # the *parameter* declaration. A same-named global's type never stands in (R80 review W1).
                domains[_text(ident, raw)] = dict(caller)
                continue
            if ident is None or ident.type != "identifier" or _text(typ, raw) not in types or len(p.named_children) != 2:
                issue = issue or "parameter_domain_unresolved"
                continue
            name, typename = _text(ident, raw), _text(typ, raw)
            lo, hi = types[typename]
            domains[name] = {"min": lo, "max": hi, "type": typename, "source": "source_parameter"}
        body = fn.child_by_field_name("body")
        nodes = list(_walk(body))
        mutated = set()
        for n in nodes:
            operand = n.child_by_field_name("left") if n.type == "assignment_expression" else n.child_by_field_name("argument")
            if n.type in {"assignment_expression", "update_expression"} or (n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "&"):
                if operand is not None:
                    mutated.update(_text(x, raw) for x in _walk(operand) if x.type == "identifier")
            if n.type == "declaration":
                mutated.update(_text(x, raw) for x in n.named_children if x.type == "identifier")
                for child in n.named_children:
                    ident = child.child_by_field_name("declarator")
                    if ident is not None and ident.type == "identifier":
                        mutated.add(_text(ident, raw))
        found = []
        seen = set()
        for n in nodes:
            if n.type in {"if_statement", "while_statement", "do_statement", "for_statement", "conditional_expression"}:
                c = n.child_by_field_name("condition")
                if c is not None:
                    found.append((c, raw, issue, mutated, n.type))
                    seen.update((x.start_byte, x.end_byte) for x in _walk(c))
        # Boolean expressions returned or assigned outside control predicates
        # are decisions too; collect maximal logical trees without duplication.
        for n in nodes:
            if (n.start_byte, n.end_byte) in seen:
                continue
            logical = n.type == "binary_expression" and _text(n.child_by_field_name("operator"), raw) in {"&&", "||"}
            logical |= n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "!"
            if logical:
                found.append((n, raw, issue, mutated, "boolean_expression"))
                seen.update((x.start_byte, x.end_byte) for x in _walk(n))
        found.sort(key=lambda item: item[0].start_byte)
        return found, domains, source_kind, hashlib.sha256(raw).hexdigest(), issue
    # Lossless flow expressions remain useful design inputs, but cannot be
    # relabeled source-derived or prove their source occurrence identity.
    explicit = {**_TYPES, "bool": (0, 1), "_Bool": (0, 1)}
    for name in unit.get("input_vars") or []:
        typename = str((unit.get("param_types") or {}).get(name) or "").strip()
        if typename in explicit:
            lo, hi = explicit[typename]
            domains[name] = {"min": lo, "max": hi, "type": typename, "source": "declared_parameter_metadata"}
        elif name in declared_domains:
            domains[name] = dict(declared_domains[name])
    found = []
    def flow(nodes):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            expression = str(n.get("condition") or "").strip()
            if expression:
                text = ("int probe(void) { if (" + expression + ") return 1; return 0; }").encode()
                root = parser.parse(text).root_node
                # logic_flow renders `&&`/`||` as AND/OR and truncates long text with "..." — not C, so never design on it.
                lossy = "..." in expression or "…" in expression or re.search(r"\b(?:AND|OR|NOT)\b", expression)
                bad = "lossy_condition_text" if lossy else ("expression_parse_error" if root.has_error else "")
                cond = next((x.child_by_field_name("condition") for x in _walk(root) if x.type == "if_statement"), None)
                if cond is not None and _text(cond, text) != "(" + expression + ")":
                    bad = bad or "expression_not_consumed_completely"
                found.append((cond, text, issue or bad, set(), "logic_flow"))
            for key in ("true_body", "false_body", "body", "children"):
                if isinstance(n.get(key), list):
                    flow(n[key])
    flow(unit.get("logic_flow") or [])
    return found, domains, source_kind, "", issue


def build_mcdc_design(unit: dict[str, Any], *, max_candidates: int = 4096, max_conditions: int = 12,
                      max_decisions: int = 64,
                      declared_domains: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Find real-input unique-cause pairs within explicit search budgets.

    Failed search is not infeasibility proof. Unsupported and budget-limited
    decisions remain in the denominator, and source reachability is not claimed.

    ``declared_domains`` maps input names to integer domains the caller resolved
    from a *declaration* (project typedef, enum declaration) — never from a
    naming convention. It only fills names the source/metadata left unresolved.
    """
    report = {"schema_version": 2, "function": unit.get("name", ""), "decisions": [],
              "selected_inputs": [], "execution_status": "not_run", "reachability": "unverified",
              "budgets": {"max_candidates": max_candidates, "max_conditions": max_conditions, "max_decisions": max_decisions,
                          # per variable-connected component, and again for the combination of components
                          "max_candidates_scope": "per_component_and_combination"}}
    try:
        found, domains, source_kind, source_hash, issue = _source_decisions(unit, declared_domains)
    except (ValueError, AttributeError, TypeError, RecursionError) as exc:
        # An exception while listing decisions is an enumeration failure too — without this the function
        # vanished from every count (review round 3 W-B).
        found, domains, source_kind, source_hash, issue = [], {}, "unknown", "", f"source_exception:{type(exc).__name__}"
    report["domains"] = domains
    # Reuse the existing input-domain parser. Only narrow an already explicit
    # declared integer domain; a design range alone cannot invent a C type.
    from generators.suts import enum_bounds, range_bounds
    for name, domain in domains.items():
        domain["type_min"], domain["type_max"] = domain["min"], domain["max"]
        ranged = range_bounds(((unit.get("uds_param_info") or {}).get(name) or {}).get("range"))
        enumerated = enum_bounds((unit.get("value_domains") or {}).get(name))
        constraint = ranged or enumerated
        if constraint:
            lo, hi = constraint.get("min"), constraint.get("max")
            if type(lo) is not int or type(hi) is not int or not domain["min"] <= lo <= hi <= domain["max"]:
                # A design range the declared type cannot hold is a document defect (SUTS `_fits_type` treats it the
                # same way): keep the declared domain, never widen it, and disclose the conflict on the domain.
                # Blanking every decision of the unit here hid 27 real functions behind one phantom row (R80).
                domain["design_range_conflict"] = {"min": lo, "max": hi,
                                                   "source": "uds_range" if ranged else "explicit_enum_values"}
            else:
                kept = [v for v in (domain.get("values") or []) if lo <= v <= hi]
                if domain.get("values") and not kept:
                    # No enumerator lies in the design range: the two documents disagree — keep the declaration.
                    domain["design_range_conflict"] = {"min": lo, "max": hi, "source": "uds_range" if ranged
                                                       else "explicit_enum_values", "reason": "no_enumerator_in_range"}
                    continue
                domain["min"], domain["max"] = lo, hi
                domain["constraint_source"] = "uds_range" if ranged else "explicit_enum_values"
                if kept:
                    domain["values"] = kept
    report["source_kind"], report["source_hash"] = source_kind, source_hash
    if not found and issue.split(":", 1)[0] in _ENUMERATION_FAILURES:
        # Decisions could not be enumerated at all: record the function once as *unenumerated* (not a decision)
        # so it stays visible without inflating the decision count. A function that parsed and has no decisions
        # (even with an unresolved preprocessor context) has no rows (R80 review N3: 99 phantom "decisions").
        found = [(None, b"", issue, set(), "unenumerated")]
    # The emitted row sets exactly the unit's inputs (when known); vectors must use the same key set so that
    # finalize can find both members of a pair among the emitted rows.
    # A unit that *has* an input list sets exactly those inputs — even an empty one (R80 review N1: falling back to
    # the domains emitted identical `{}` rows and misreported every pair as truncated). Only direct callers without
    # an input list (inventory scripts) take the resolved domains as the row.
    row_names = list(unit["input_vars"] or []) if "input_vars" in unit else list(domains)
    selected = {}
    for index, (node, raw, context_issue, mutated, kind) in enumerate(found):
        identity = f"{unit.get('source_path', '')}:{unit.get('name', '')}:{node.start_byte if node else index}"
        did = f"D{index + 1}"
        decision = {"decision_id": did, "expression": _display_expression(node, raw), "kind": kind,
                    "source_kind": source_kind, "source_hash": source_hash,
                    "occurrence_id": identity if source_kind == "source" else f"flow:{unit.get('name', '')}:{index}",
                    "location": {"line": node.start_point.row + 1, "byte": node.start_byte} if node else {},
                    "status": "unenumerated" if kind == "unenumerated" else "unsupported",
                    "reason": context_issue, "conditions": [], "pairs": [],
                    "candidate_count": 0, "search_complete": False, "execution_status": "not_run", "reachability": "unverified"}
        report["decisions"].append(decision)
        try:
            if node is None:
                raise Unsupported(context_issue or "decision_parse_missing")
            def inventory(n):
                n = _unwrap(n)
                if n.type == "binary_expression" and _text(n.child_by_field_name("operator"), raw) in {"&&", "||"}:
                    return inventory(n.child_by_field_name("left")) + inventory(n.child_by_field_name("right"))
                if n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "!":
                    return inventory(n.child_by_field_name("argument"))
                return [_text(n, raw)]
            try:
                decision["conditions"] = [{"condition_id": f"C{i + 1}", "expression": expression}
                                          for i, expression in enumerate(inventory(node))]
            except Unsupported:
                if not context_issue:
                    raise
            # The context defect (lossy flow text, unresolved preprocessor, ...) is the real reason; compiling
            # first let a symptom such as `unsupported_scalar:call_expression` (``(x) OR (...)``) mask it.
            if context_issue:
                raise Unsupported(context_issue)
            ir, atoms, variables, constants = _compile(node, raw, domains)
            decision["conditions"] = [{k: v for k, v in atom.items() if not k.startswith("_")} for atom in atoms]
            if set(variables) & mutated:
                raise Unsupported("input_binding_modified_or_shadowed")
            if set(unit.get("input_vars") or []) - set(domains):
                raise Unsupported("unit_input_domain_unresolved")
            if missing := sorted(set(variables) - set(row_names)):
                # The row cannot set this variable (not a unit input — cap or I/O renaming): a pair designed on it
                # would be emitted without its deciding value and then misreported as truncated (R80 review W5).
                raise Unsupported("decision_variable_not_in_unit_inputs:" + missing[0])
            if index >= max_decisions or len(atoms) > max_conditions:
                raise Unsupported("decision_or_condition_budget")
            values = []
            for name in variables:
                lo, hi = domains[name]["min"], domains[name]["max"]
                if domain_values := domains[name].get("values"):
                    sample = list(domain_values)
                elif hi - lo <= 15:
                    sample = list(range(lo, hi + 1))
                else:
                    sample = list(dict.fromkeys(v for v in [0, 1, -1, *(v + d for v in sorted(constants) for d in (-1, 0, 1)), lo, hi] if lo <= v <= hi))
                values.append(sample)
            size = math.prod(len(v) for v in values)
            decision["candidate_space_size"] = size
            decision["domain_exhaustive"] = all(len(values[i]) == domains[name]["max"] - domains[name]["min"] + 1 for i, name in enumerate(variables))
            by_signature, pairs = {}, {}
            defaults = {name: _default_value(domains[name]) for name in row_names if name in domains}
            components, components_complete, decision["component_candidate_count"] = _realizable_truths(
                atoms, variables, values, defaults, max_candidates)
            combined_size = math.prod(len(c) for c in components)
            for parts in itertools.islice(itertools.product(*components), max(0, max_candidates)):
                inputs = dict(defaults)
                for part in parts:
                    inputs.update(part)
                truth, outcome, observed = _evaluate(ir, atoms, inputs)
                decision["candidate_count"] += 1
                bits = sum((1 << i) for i, v in enumerate(truth) if v)
                row = {"inputs": inputs, "truth": truth, "decision": outcome, "observed": observed}
                for i in range(len(atoms)):
                    if not observed[i] or i in pairs:
                        continue
                    mask = bits & ~(1 << i)
                    other = by_signature.get((i, mask, not truth[i], not outcome))
                    if other is not None:
                        pair = {"pair_id": f"{did}:C{i + 1}:P1", "condition_id": f"C{i + 1}", "retained_status": "pending"}
                        for suffix, member in (("a", other), ("b", row)):
                            for key, value in member.items():
                                pair[f"{key}_{suffix}"] = value
                            selected.setdefault(json.dumps(member["inputs"], sort_keys=True), member["inputs"])
                        pairs[i] = pair
                    else:
                        by_signature.setdefault((i, mask, truth[i], outcome), row)
                if len(pairs) == len(atoms):
                    break
            decision["pairs"] = [pairs[i] for i in sorted(pairs)]
            decision["search_complete"] = components_complete and decision["candidate_count"] == combined_size
            decision["status"] = "designed" if len(pairs) == len(atoms) else ("partial" if pairs else "no_pair_found")
            decision["reason"] = "unique_cause_pairs_found" if len(pairs) == len(atoms) else (
                "no_pair_in_candidate_domain" if decision["search_complete"] else "candidate_budget_exhausted")
        except (Unsupported, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            decision["reason"] = str(exc)
    report["selected_inputs"] = list(selected.values())
    finalize_mcdc_design(report, [])
    return report


def finalize_mcdc_design(report: dict[str, Any], sequences: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind and revalidate retained pairs after output sequence truncation."""
    def normalized(values):
        clean = {}
        for key, value in values.items():
            if isinstance(value, str) and re.fullmatch(r"-?(?:0x[0-9a-fA-F]+|[0-9]+)", value):
                value = int(value, 16 if "0x" in value else 10)
            clean[key] = value
        return clean
    lookup = {}
    for seq in sequences:
        seq["mcdc_design"] = []
        lookup.setdefault(json.dumps(normalized(seq.get("inputs") or {}), sort_keys=True), seq)
    retained = 0
    for decision in report["decisions"]:
        for pair in decision["pairs"]:
            a = lookup.get(json.dumps(pair["inputs_a"], sort_keys=True))
            b = lookup.get(json.dumps(pair["inputs_b"], sort_keys=True))
            pair["seq_a"], pair["seq_b"] = a.get("seq_num") if a else None, b.get("seq_num") if b else None
            pair["retained_status"] = "truncated"
            if a is None or b is None:
                continue
            va = evaluate_decision(decision["expression"], normalized(a["inputs"]), report["domains"])
            vb = evaluate_decision(decision["expression"], normalized(b["inputs"]), report["domains"])
            ci = int(pair["condition_id"][1:]) - 1
            valid = va.get("status") == vb.get("status") == "supported"
            valid = valid and va["decision"] != vb["decision"] and va["observed"][ci] and vb["observed"][ci]
            valid = valid and [i for i, (x, y) in enumerate(zip(va["truth"], vb["truth"], strict=True)) if x != y] == [ci]
            if not valid:
                pair["retained_status"] = "invalidated"
                continue
            pair["retained_status"] = "retained"
            retained += 1
            for role, seq, ev in (("a", a, va), ("b", b, vb)):
                seq["mcdc_design"].append({"decision_id": decision["decision_id"], "pair_id": pair["pair_id"],
                    "condition_id": pair["condition_id"], "role": role, "truth": ev["truth"], "observed": ev["observed"],
                    "decision": ev["decision"], "source_hash": report["source_hash"],
                    "execution_status": "not_run", "reachability": "unverified"})
    # Same definition as the SUTS quality report: an unenumerated function is not a decision.
    report["summary"] = {"total_decisions": sum(d["status"] != "unenumerated" for d in report["decisions"]),
        "unenumerated": sum(d["status"] == "unenumerated" for d in report["decisions"]),
        "total_conditions": sum(len(d["conditions"]) for d in report["decisions"]),
        "unknown_condition_decisions": sum(not d["conditions"] for d in report["decisions"]),
        "unsupported_decisions": sum(d["status"] == "unsupported" for d in report["decisions"]),
        "designed_pairs": sum(len(d["pairs"]) for d in report["decisions"]), "retained_pairs": retained,
        "execution_status": "not_run"}
    return report
