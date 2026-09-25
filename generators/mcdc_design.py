"""Bounded, unique-cause MC/DC design over concrete declared integer inputs.

These are expression-level design pairs, not measured program coverage.
Reachability at the source occurrence remains explicitly unverified.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
from collections import Counter
from typing import Any

from generators import c_project_context as cpc
from generators.c_test_semantics import _TYPES
from workflow.code_parser.c_parser import _make_parser

# Source-level failures that prevent listing a function's decisions at all.
_ENUMERATION_FAILURES = frozenset({
    "tree_sitter_unavailable", "source_budget", "source_parse_error", "source_ast_budget",
    "function_identity_missing_or_ambiguous", "source_text_incomplete", "source_exception",
    "function_not_compiled_in_configuration",
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


_ARITH_OPS = frozenset({"+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"})


def _compile(node, raw, domains, constants=None, widths=None, types=None):
    """Decision → IR over atoms.

    ``constants`` maps names to ``{"value", "type"}`` resolved from declarations (object-like macros,
    enumerators). ``widths`` (target integer widths from typedef testimony) switches comparisons to exact
    C semantics: every operand then needs a C type, and both sides go through the usual arithmetic
    conversions (``U16 < S16`` compares as ``unsigned int`` on a 16-bit-int target). With widths, operands
    may also be integer arithmetic, bitwise and cast expressions (``(x & MASK) == MASK``, ``(S16)u < s``);
    ``types`` resolves a cast's type name to a C type (callable or dict).
    """
    atoms, variables, values_seen = [], set(), set()
    constants = {} if constants is None else constants  # a lazy constants map is empty until asked
    def lift(fn, *args):
        try:
            return fn(*args)
        except cpc.Unresolved as exc:
            raise Unsupported(str(exc)) from exc
    def cast_type(type_node):
        text = " ".join(_text(type_node, raw).split())
        if callable(types):
            return lift(types, text)
        if isinstance(types, dict) and text in types:
            return types[text]
        raise Unsupported("cast_type_unresolved:" + text)
    def term(n):
        n = _unwrap(n)
        text = _text(n, raw)
        if n.type == "identifier":
            if text in domains:
                variables.add(text)
                t = domains[text].get("ctype") if widths else None
                if widths and t is None:
                    raise Unsupported("operand_c_type_unresolved:" + text)
                return ("var", text, t)
            if text in constants:
                value = constants[text]["value"]
                values_seen.add(value)
                return ("constant", value, constants[text]["type"] if widths else None)
            raise Unsupported("missing_declared_domain:" + text)
        if n.type == "number_literal" and widths:
            value, t = lift(cpc.literal, text, widths)
            values_seen.add(value)
            return ("constant", value, t)
        if n.type == "number_literal" and re.fullmatch(r"(?:0|[1-9][0-9]*|0[xX][0-9a-fA-F]+)", text):
            value = int(text, 16 if "x" in text.lower() else 10)
            if value > 32767:
                raise Unsupported("literal_target_type_unresolved")
            values_seen.add(value)
            return ("constant", value, None)
        op = _text(n.child_by_field_name("operator"), raw) if n.type in {"unary_expression", "binary_expression"} else ""
        if n.type == "unary_expression" and op in {"+", "-", "~"}:
            arg = term(n.child_by_field_name("argument"))
            if arg[0] == "constant" and op != "~":
                if widths:
                    value, t = lift(cpc.arith, op, None, (arg[1], arg[2]), widths)
                else:
                    value, t = (arg[1] if op == "+" else -arg[1]), None
                values_seen.add(value)
                return ("constant", value, t)
            if not widths:
                raise Unsupported("arithmetic_operand_unsupported")
            return ("expr", (op, (arg,), widths), lift(cpc.promote, arg[2], widths))
        if not widths:
            raise Unsupported("unsupported_scalar:" + n.type)
        if n.type == "binary_expression" and op in _ARITH_OPS:
            left, right = term(n.child_by_field_name("left")), term(n.child_by_field_name("right"))
            if cpc.is_float(left[2]) or cpc.is_float(right[2]):
                raise Unsupported("floating_operand")
            if _contains_enum(left) or _contains_enum(right):
                # Arithmetic on an enumeration object depends on its implementation-defined type (review round 2 W1).
                raise Unsupported("enum_underlying_type_implementation_defined")
            t = lift(cpc.promote, left[2], widths) if op in {"<<", ">>"} else lift(cpc.usual_conversion, left[2], right[2], widths)
            if left[0] == right[0] == "constant":
                value, t = lift(cpc.arith, op, (left[1], left[2]), (right[1], right[2]), widths)
                values_seen.add(value)
                return ("constant", value, t)
            return ("expr", (op, (left, right), widths), t)
        if n.type == "cast_expression":
            t = cast_type(n.child_by_field_name("type"))
            inner = term(n.child_by_field_name("value"))
            if cpc.is_float(t) or cpc.is_float(inner[2]):
                raise Unsupported("floating_operand")
            return ("cast", inner, t)
        if n.type == "call_expression":
            f, args = n.child_by_field_name("function"), n.child_by_field_name("arguments")
            inner_names = [c for c in f.named_children if c.type != "comment"] if f is not None and f.type == "parenthesized_expression" else []
            arg_nodes = [c for c in args.named_children if c.type != "comment"] if args is not None else []
            if len(inner_names) == 1 and inner_names[0].type in {"identifier", "type_identifier"} and len(arg_nodes) == 1:
                # ``(T)(x)`` is a cast exactly when ``T`` names a type.
                t = cast_type(inner_names[0])
                inner = term(arg_nodes[0])
                if cpc.is_float(t) or cpc.is_float(inner[2]):
                    raise Unsupported("floating_operand")
                return ("cast", inner, t)
        raise Unsupported("unsupported_scalar:" + n.type)
    def bounds(t):
        if t[0] == "constant":
            return t[1], t[1]
        d = domains[t[1]]
        return d.get("type_min", d["min"]), d.get("type_max", d["max"])
    def build(n):
        n = _unwrap(n)
        if n.type == "binary_expression":
            op = _text(n.child_by_field_name("operator"), raw)
            if op in {"&&", "||"}:
                return (op, build(n.child_by_field_name("left")), build(n.child_by_field_name("right")))
            if op in {"<", "<=", ">", ">=", "==", "!="}:
                left, right = term(n.child_by_field_name("left")), term(n.child_by_field_name("right"))
                if widths:
                    if cpc.is_float(left[2]) or cpc.is_float(right[2]):
                        raise Unsupported("floating_operand")
                    if (_enum_object(left) and _may_be_negative(right, domains)) or \
                            (_enum_object(right) and _may_be_negative(left, domains)):
                        # An enumeration object's type is implementation-defined (C11 6.7.2.2p4): compilers pick
                        # unsigned int when no enumerator is negative, and then -1 compares as UINT_MAX (review W3).
                        raise Unsupported("enum_underlying_type_implementation_defined")
                    atom = (op, left, right, lift(cpc.usual_conversion, left[2], right[2], widths))
                else:
                    lb, rb = bounds(left), bounds(right)
                    if (lb[0] == 0 and lb[1] > 32767 and rb[0] < 0) or (rb[0] == 0 and rb[1] > 32767 and lb[0] < 0):
                        raise Unsupported("target_dependent_unsigned_comparison")
                    atom = (op, left, right, None)
            elif widths and op in _ARITH_OPS:
                atom = ("truth", term(n))
            else:
                raise Unsupported("unsupported_atom_operator:" + op)
        elif n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "!":
            return ("!", build(n.child_by_field_name("argument")))
        else:
            atom = ("truth", term(n))
        index = len(atoms)
        atoms.append({"condition_id": f"C{index + 1}", "expression": _text(n, raw), "_atom": atom})
        return ("atom", index)
    ir = build(node)
    return ir, atoms, sorted(variables), values_seen


def _contains_enum(term):
    if term[0] == "var":
        return bool((term[2] or {}).get("enum"))
    if term[0] == "cast":
        return _contains_enum(term[1])
    if term[0] == "expr":
        return any(_contains_enum(a) for a in term[1][1])
    return False


def _enum_object(term):
    return term[0] == "var" and bool((term[2] or {}).get("enum"))


def _may_be_negative(term, domains):
    if term[0] == "constant":
        return term[1] < 0
    if term[0] == "var":
        return domains[term[1]]["min"] < 0
    return bool((term[2] or {}).get("signed"))


def _term_value(term, inputs):
    """Value of a compiled operand under C semantics; raises ``cpc.Unresolved`` on undefined behavior."""
    kind = term[0]
    if kind == "var":
        return inputs[term[1]]
    if kind == "constant":
        return term[1]
    if kind == "cast":
        return cpc.convert(_term_value(term[1], inputs), term[2])
    op, args, widths = term[1]
    if len(args) == 1:
        return cpc.arith(op, None, (_term_value(args[0], inputs), args[0][2]), widths)[0]
    return cpc.arith(op, (_term_value(args[0], inputs), args[0][2]), (_term_value(args[1], inputs), args[1][2]), widths)[0]


def _atom_truth(atom, inputs):
    a = _term_value(atom[1], inputs)
    if atom[0] == "truth":
        return bool(a)
    b = _term_value(atom[2], inputs)
    if atom[3] is not None:
        a, b = cpc.convert(a, atom[3]), cpc.convert(b, atom[3])
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[atom[0]]


def _term_variables(term):
    if term[0] == "var":
        return [term[1]]
    if term[0] == "cast":
        return _term_variables(term[1])
    if term[0] == "expr":
        return [name for arg in term[1][1] for name in _term_variables(arg)]
    return []


def _atom_variables(atom):
    terms = atom[1:2] if atom[0] == "truth" else atom[1:3]
    return list(dict.fromkeys(name for t in terms for name in _term_variables(t)))


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


def evaluate_decision(expression: str, inputs: dict[str, int], domains: dict[str, dict[str, Any]],
                      constants: dict[str, dict[str, Any]] | None = None,
                      widths: dict[str, int] | None = None,
                      types: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Evaluate pure integer decision truth and short-circuit observations.

    Domain metadata must describe explicit integer declarations. This helper
    verifies expression mathematics only; it cannot authenticate source or
    prove reachability or target execution. ``constants``/``widths`` are the
    ones the design used (``report["constants"]``, ``report["target"]["widths"]``).
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
        ir, atoms, variables, _ = _compile(condition, raw, domains, constants, widths, types)
        if len(atoms) > 64:
            raise Unsupported("condition_budget")
        for name in variables:
            if type(inputs.get(name)) is not int or not domains[name]["min"] <= inputs[name] <= domains[name]["max"]:
                raise Unsupported("input_outside_declared_domain:" + name)
        truth, decision, observed = _evaluate(ir, atoms, inputs)
        return {"status": "supported", "truth": truth, "decision": decision, "observed": observed,
                "conditions": [{k: v for k, v in c.items() if not k.startswith("_")} for c in atoms],
                "execution_status": "not_run", "reachability": "unverified"}
    except (Unsupported, cpc.Unresolved, ValueError, KeyError, TypeError, AttributeError, RecursionError, StopIteration) as exc:
        return {"status": "unsupported", "reason": str(exc), "execution_status": "not_run"}


def _default_value(domain):
    """Value for an input the decision does not read: an enumerator if the domain is enumerated, else closest to 0."""
    if domain.get("values"):
        return min(domain["values"], key=lambda v: (abs(v), v))
    return max(domain["min"], min(0, domain["max"]))


def _realizable_truths(atoms, variables, values, defaults, budget, skipped=None):
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
            try:
                truths = tuple(_atom_truth(atoms[i]["_atom"], probe) for i in member_atoms)
            except cpc.Unresolved:
                # undefined behavior for this input (overflow, division by zero): not a test vector
                if skipped is not None:
                    skipped[0] += 1
                continue
            realized.setdefault(truths, assignment)
            if len(realized) == 2 ** len(member_atoms):
                break
        else:
            complete = complete and space <= max(0, budget)
        components.append(list(realized.values()))
    return components, complete, evaluated


def _function_name(fn, raw):
    d = fn.child_by_field_name("declarator")
    while d is not None and d.type != "function_declarator":
        d = d.child_by_field_name("declarator")
    ident = d.child_by_field_name("declarator") if d is not None else None
    return (_text(ident, raw) if ident is not None and ident.type == "identifier" else ""), d


def _has_error(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            return True
        stack.extend(n.children)
    return False


_CONDITIONAL_BLOCKS = frozenset({"preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif", "preproc_elifdef"})
_PP_BRANCHES = frozenset({"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"})
_PP_LINES = frozenset({"preproc_def", "preproc_function_def", "preproc_call", "preproc_include"})


def _in_preproc_condition(node):
    """Inside the condition of an ``#if``/``#elif`` — preprocessor arithmetic, never a run-time decision."""
    child, parent = node, node.parent
    while parent is not None:
        if parent.type in _PP_BRANCHES and parent.child_by_field_name("condition") == child:
            return True
        child, parent = parent, parent.parent
    return False


def _live_nodes(root, raw, scope):
    """Nodes the configuration compiles, with an ``undecided`` flag for ``#if`` arms the macro state cannot decide.

    Inactive arms are skipped entirely (their writes, calls and decisions do not exist in this build); the
    ``#if`` condition itself is preprocessor arithmetic and never a decision.
    """
    out, stack = [], [(root, False)]
    while stack:
        n, undecided = stack.pop()
        if n.type in _PP_BRANCHES:
            cond, name, alt = n.child_by_field_name("condition"), n.child_by_field_name("name"), n.child_by_field_name("alternative")
            arm = [c for c in n.named_children if c != cond and c != name and c != alt]
            verdict = cpc.pp_condition(scope, n, raw)
            chosen = [] if verdict is False else arm
            other = [] if verdict is True else ([alt] if alt is not None else [])
            flag = undecided or verdict is None
            stack.extend((c, flag) for c in reversed(chosen + other))
            continue
        if n.type == "preproc_else":
            stack.extend((c, undecided) for c in reversed(n.named_children))
            continue
        if n.type in _PP_LINES:
            continue
        out.append((n, undecided))
        stack.extend((c, undecided) for c in reversed(n.named_children))
    return out
_LOOPS = frozenset({"while_statement", "do_statement", "for_statement"})


def _scope_domain(t, typename, scope, source, **extra):
    """Integer domain of a resolved C type; an enum-typed object ranges over its enumerators (the declared value set)."""
    lo, hi = cpc.type_range(t)
    domain = {"min": lo, "max": hi, "type": typename, "source": source, "ctype": t, **extra}
    if t.get("enum"):
        enum = (scope.get("enum_types") or {}).get(t["enum"]) or {}
        values = sorted({scope["constants"][m["name"]]["value"] for m in enum.get("members") or []
                         if m["name"] in scope["constants"]})
        if not values or len(values) != len(enum.get("members") or []):
            raise cpc.Unresolved("enum_values_unresolved:" + t["enum"])
        domain.update(min=values[0], max=values[-1], values=values)
    return domain


def _scope_type(scope, text):
    text = " ".join(str(text).split())
    if text in scope["types"]:
        return scope["types"][text]
    if text in scope["unresolved_types"]:
        raise cpc.Unresolved(scope["unresolved_types"][text])
    kind = cpc.base_kind(text)
    if kind is None:
        raise cpc.Unresolved("type_undeclared:" + text)
    if kind[1] is None:
        raise cpc.Unresolved("plain_char_signedness_unknown")
    return cpc.ctype(kind[0], kind[1], scope["target"]["widths"])


def _compile_state(fn, states):
    """Preprocessor state of a function definition (``None`` = not compiled in this build). Definitions inside a
    file-level parse-recovery container are events of their own (`cpc._events`), so the lookup is direct."""
    return states.get(fn.start_byte)


def _scoped_source_decisions(unit, scope, declared_domains):
    """Source path with the translation unit's resolved project scope (typedefs, macros, enumerators, globals).

    Unlike the scope-less path, an unresolved include or ``#define`` elsewhere does not block the function:
    each decision fails only on what *it* reads, with that identifier's own reason.
    """
    source = str(unit.get("source_text") or "")
    issue = "" if unit.get("source_text_complete", True) else "source_text_incomplete"
    parser = _make_parser()
    if parser is None:
        return [], {}, "source", "", "tree_sitter_unavailable", {}
    if len(source) > 2_000_000:
        return [], {}, "source", "", "source_budget", {}
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()
    root = parser.parse(raw).root_node
    matches = []
    stack = [root]
    visited = 0
    while stack:
        n = stack.pop()
        visited += 1
        if visited > 200000:
            return [], {}, "source", digest, "source_ast_budget", {}
        if n.type == "function_definition":
            if _function_name(n, raw)[0] == unit.get("name"):
                matches.append(n)
            continue
        stack.extend(n.named_children)
    states = scope.get("main_file_states") if scope.get("main_file_sha256") == digest else None
    if states is not None and matches:
        # Definitions the configuration does not compile (inactive ``#if`` arm) are not this function.
        compiled = [n for n in matches if _compile_state(n, states) is not None]
        if not compiled:
            return [], {}, "source", digest, "function_not_compiled_in_configuration", {}
        matches = compiled
    if len(matches) != 1:
        return [], {}, "source", digest, "function_identity_missing_or_ambiguous", {}
    fn = matches[0]
    if _has_error(fn):
        # Errors elsewhere in the file (vendor extensions such as ``__interrupt`` or ``@address``) do not make this
        # function's tree unreliable; an error inside it does.
        return [], {}, "source", digest, "source_parse_error", {}
    if states is not None:
        if _compile_state(fn, states) == "unknown":
            issue = issue or "conditional_compilation_unresolved"
    else:
        # No preprocessor state for this text (hash mismatch): any enclosing ``#if`` is undecided.
        ancestor = fn.parent
        while ancestor is not None:
            if ancestor.type in _CONDITIONAL_BLOCKS:
                issue = issue or "conditional_compilation_unresolved"
                break
            ancestor = ancestor.parent
    extra = {"scope": scope, "params": {}, "param_reasons": {}, "locals": set(), "calls": [], "loops": [],
             "writes": [], "has_goto": False, "effects": scope.get("effects") or {}}
    macro_bodies = scope.get("macro_bodies") or {}
    macro_status = scope.get("macro_status") or {}
    known_functions = (scope.get("effects") or {}).get("functions") or {}
    tree_macros = (scope.get("effects") or {}).get("macros") or {}

    def macro_writes(name, depth=0):
        """May expanding this macro write — itself or through a macro it invokes (transitive)?

        A macro whose body this unit cannot pin down (undecided ``#if`` / redefined) is judged by the union of every
        definition in the tree — the same view the callee closure uses (review round 3 W1)."""
        if depth > 6:
            return True
        if macro_status.get(name) != "active":
            union = tree_macros.get(name)
            if union is None or scope.get("missing_includes"):
                return True
            return union["writes"] or any(c in macro_status and macro_writes(c, depth + 1) for c in union["calls"])
        body = macro_bodies.get(name, "")
        fx = cpc.macro_side_effects(body)
        if fx["writes"] and "##" in body:
            return True
        return fx["writes"] or any(c in macro_status and macro_writes(c, depth + 1) for c in fx["calls"])

    def macro_targets(name, depth=0):
        """Names an active macro's expansion mentions (object-like aliases expanded); ``*`` if unknowable
        (undecided/redefined body, or token pasting ``##`` that forms names we cannot see)."""
        body = macro_bodies.get(name, "")
        if macro_status.get(name) != "active" or depth > 6 or "##" in body:
            return {"*"}
        names = set(re.findall(r"\b[A-Za-z_]\w*\b", body))
        for inner in [x for x in names if x in macro_status]:
            names |= macro_targets(inner, depth + 1)
        return names

    def expand(name):
        return macro_targets(name) if name in macro_status else {name}

    def record_writes(position, node, names, cause=""):
        extra["writes"].extend((position, name, node, cause) for name in names)
    domains = {}
    _, fdecl = _function_name(fn, raw)
    params = fdecl.child_by_field_name("parameters")
    for p in params.named_children:
        if p.type != "parameter_declaration":
            continue
        ident, typ = p.child_by_field_name("declarator"), p.child_by_field_name("type")
        if ident is None:
            continue  # ``(void)`` or an unnamed parameter
        name = cpc._declared_name(ident, raw)
        extra["params"][name] = ident.type
        quals = [_text(c, raw) for c in p.named_children if c.type == "type_qualifier"]
        caller = (declared_domains or {}).get(name)
        try:
            if ident.type != "identifier":
                raise cpc.Unresolved("parameter_not_scalar:" + ident.type.replace("_declarator", ""))
            if "volatile" in quals:
                raise cpc.Unresolved("volatile_parameter")
            t = _scope_type(scope, _text(typ, raw))
            domains[name] = _scope_domain(t, _text(typ, raw), scope, "source_parameter")
        except cpc.Unresolved as exc:
            if ident.type == "identifier" and caller and caller.get("origin") == "parameter" and caller.get("ctype"):
                domains[name] = dict(caller)
            else:
                extra["param_reasons"][name] = str(exc)
    body = fn.child_by_field_name("body")
    live = _live_nodes(body, raw, scope)
    undecided = {(n.start_byte, n.end_byte, n.type) for n, flag in live if flag}
    nodes = [n for n, _flag in live]
    # Writes are kept with their position: only a write that can execute before an evaluation rebinds the input
    # (see `_rebinding_write`). The scope-less path keeps the whole-body set.
    mutated: set[str] = set()
    for n in nodes:
        operand = n.child_by_field_name("left") if n.type == "assignment_expression" else n.child_by_field_name("argument")
        if n.type in {"assignment_expression", "update_expression"} or (n.type in {"unary_expression", "pointer_expression"} and _text(n, raw).lstrip().startswith("&")):
            if operand is not None:
                for x in _walk(operand):
                    if x.type != "identifier":
                        continue
                    # A write target that is a macro writes what it expands to (``G_ALIAS = 0U``).
                    target = _text(x, raw)
                    record_writes(n.start_byte, n, expand(target), cause=("macro:" + target) if target in macro_status else "")
        if n.type == "declaration":
            for child in n.named_children:
                name = cpc._declared_name(child, raw) if child.type not in {"type_qualifier", "storage_class_specifier", "primitive_type", "type_identifier", "sized_type_specifier", "struct_specifier", "enum_specifier", "union_specifier"} else ""
                if name:
                    extra["locals"].add(name)
        if n.type in {"goto_statement", "labeled_statement"}:
            extra["has_goto"] = True
        if n.type == "call_expression":
            f = n.child_by_field_name("function")
            callee = _text(f, raw) if f is not None and f.type == "identifier" else "<indirect>"
            extra["calls"].append((n.start_byte, callee, n))
            args = n.child_by_field_name("arguments")
            if callee in macro_status and macro_writes(callee):
                # A macro that (possibly through another macro) assigns or takes an address may do it to its
                # *arguments* (``CLR_BIT(x, 0U)``, ``CLR(v) clr(&(v))``) or to names in its own text: all written.
                # Argument names are expanded too (``CLR(SELF)`` with ``#define SELF x``, review round 3 C1).
                written = {t for x in _walk(args) if x.type == "identifier" for t in expand(_text(x, raw))}
                record_writes(n.start_byte, n, written | macro_targets(callee), cause="macro:" + callee)
            elif callee not in macro_status and callee not in known_functions and callee != "<indirect>" \
                    and callee not in (scope.get("prototypes") or ()) and scope.get("missing_includes"):
                # Declared nowhere we can read, after a missing include: it may be a macro from that header.
                record_writes(n.start_byte, n, {"*"}, cause="undeclared_after_missing_include:" + callee)
        if n.type == "identifier" and _text(n, raw) in macro_status and not (
                n.parent is not None and n.parent.type == "call_expression" and n.parent.child_by_field_name("function") == n):
            name = _text(n, raw)
            fx = cpc.macro_side_effects(macro_bodies.get(name, ""))
            if macro_status[name] != "active" or fx["writes"] or fx["calls"]:
                # An object-like macro with effects (``CLEAR_FLAG;`` = ``(g_flag = 0U)``, ``ZERO_X`` = ``x = 0U``) or
                # one whose body is not known is a call site that may write what it names (review C3c, round 2 C1).
                extra["calls"].append((n.start_byte, name, n))
                if macro_writes(name):
                    record_writes(n.start_byte, n, macro_targets(name), cause="macro:" + name)
        if n.type in _LOOPS:
            extra["loops"].append((n.start_byte, n.end_byte))
    def decision_issue(n):
        return issue or ("conditional_compilation_unresolved" if (n.start_byte, n.end_byte, n.type) in undecided else "")
    found, seen = [], set()
    for n in nodes:
        if n.type in {"if_statement", "while_statement", "do_statement", "for_statement", "conditional_expression"}:
            c = n.child_by_field_name("condition")
            if c is not None:
                found.append((c, raw, decision_issue(n), mutated, n.type))
                seen.update((x.start_byte, x.end_byte) for x in _walk(c))
    for n in nodes:
        if (n.start_byte, n.end_byte) in seen:
            continue
        logical = n.type == "binary_expression" and _text(n.child_by_field_name("operator"), raw) in {"&&", "||"}
        logical |= n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "!"
        if logical:
            found.append((n, raw, decision_issue(n), mutated, "boolean_expression"))
            seen.update((x.start_byte, x.end_byte) for x in _walk(n))
    found.sort(key=lambda item: item[0].start_byte)
    # Globals the decisions read become inputs through their declaration — added before the design-range
    # narrowing so an SwUDS range applies to them as to parameters. Binding is checked per decision.
    globals_ = scope.get("globals") or {}
    extra["global_reasons"] = {}
    for node, *_ in found:
        for x in _walk(node):
            name = _text(x, raw) if x.type == "identifier" else ""
            if not name or name in domains or name in extra["params"] or name in extra["locals"] or name not in globals_:
                continue
            g = globals_[name]
            try:
                domains[name] = _scope_domain(g["type"], g["typename"], scope, "global_declaration", origin="global",
                                              declared_at=f"{os.path.basename(g['file'])}:{g['line']}")
            except cpc.Unresolved as exc:
                extra["global_reasons"][name] = str(exc)
    return found, domains, "source", digest, issue, extra


def _identifier_reason(name, extra):
    """Why a decision identifier has no domain — the specific declaration fact, not a generic miss."""
    scope = extra.get("scope") or {}
    if name in extra.get("params", {}):
        return f"parameter_domain_unresolved:{name}:{extra['param_reasons'].get(name, 'unknown')}"
    if name in extra.get("locals", set()):
        return "local_variable_not_input:" + name
    if name in extra.get("global_reasons", {}):
        return f"global_domain_unresolved:{name}:{extra['global_reasons'][name]}"
    if name in (scope.get("unresolved_globals") or {}):
        return f"global_domain_unresolved:{name}:{scope['unresolved_globals'][name]}"
    if name in (scope.get("unresolved_constants") or {}):
        return f"macro_value_unresolved:{name}:{scope['unresolved_constants'][name]}"
    if name in (scope.get("function_like_macros") or {}):
        return "function_like_macro:" + name
    return "identifier_undeclared:" + name + (":partial_context" if scope.get("missing_includes") else "")


def _may_precede(event, decision, extra):
    """Can ``event`` (a write or call node) execute before ``decision`` is evaluated in the same invocation?

    Yes if it is in a loop enclosing the decision (a later iteration), or with ``goto``. Otherwise it must be
    lexically earlier (or inside the decision) and not in the other arm of an ``if`` whose arm holds the decision
    — the two arms are exclusive. ``switch`` arms are not treated as exclusive (fall-through)."""
    if extra.get("has_goto"):
        return True
    if any(lo <= decision.start_byte < hi and lo <= event.start_byte < hi for lo, hi in extra.get("loops", [])):
        return True
    if event.start_byte >= decision.end_byte:
        return False
    ancestor = event.parent
    while ancestor is not None:
        if ancestor.type == "if_statement":
            arms = [ancestor.child_by_field_name("consequence"), ancestor.child_by_field_name("alternative")]
            spans = [(a.start_byte, a.end_byte) for a in arms if a is not None]
            event_arm = next((i for i, (lo, hi) in enumerate(spans) if lo <= event.start_byte < hi), None)
            decision_arm = next((i for i, (lo, hi) in enumerate(spans) if lo <= decision.start_byte < hi), None)
            if event_arm is not None and decision_arm is not None and event_arm != decision_arm:
                return False
        ancestor = ancestor.parent
    return True


def _rebinding_write(name, decision, extra):
    """Reason a write to ``name`` — or to anything (``*``: an expansion we cannot see) — can run before this
    evaluation (see `_may_precede`), or ``""``. A ``*`` write names its cause, not the variable (review round 3 W1)."""
    for _pos, target, node, cause in extra.get("writes", []):
        if target in (name, "*") and _may_precede(node, decision, extra):
            if target == "*":
                return "input_binding_unverified:" + (cause or "unknown_expansion")
            return "input_modified_before_decision:" + name
    return ""


def _global_binding_issue(name, decision, extra):
    """Reason the value at the decision may differ from the value set at function entry, or ``""``.

    Callees that can run before this evaluation — lexically earlier calls, calls inside the decision itself, and
    every call inside a loop that encloses the decision — must not (transitively) write the global; unknown or
    indirect code might.
    """
    scope = extra.get("scope") or {}
    info = (scope.get("globals") or {}).get(name) or {}
    if info.get("volatile"):
        return "volatile_input_unmodeled:" + name
    if info.get("const"):
        return "const_object_not_input:" + name
    effects = extra.get("effects") or {}
    if name in (effects.get("address_taken") or set()):
        return "global_address_taken:" + name
    functions = effects.get("functions") or {}
    macros = {**(scope.get("macro_bodies") or scope.get("function_like_macro_bodies") or {}),
              "__status__": scope.get("macro_status") or {}, "__tree__": effects.get("macros") or {},
              "__missing_includes__": bool(scope.get("missing_includes"))}
    for _, callee, call in extra.get("calls", []):
        if not _may_precede(call, decision, extra):
            continue
        reason = _callee_writes(callee, name, functions, macros, 0)
        if reason:
            return reason
    return ""


def _callee_writes(callee, name, functions, macros, depth):
    if callee == "<indirect>":
        return "global_binding_unverified:indirect_call"
    scope_status = macros.get("__status__", {})
    if callee in scope_status and scope_status[callee] != "active":
        # Body undecided in this unit: judge by every definition in the tree (review round 3 W1).
        union = macros.get("__tree__", {}).get(callee)
        if union is None or union["writes"] or macros.get("__missing_includes__"):
            return "global_binding_unverified:macro_body_unknown:" + callee
        for inner in union["calls"]:
            reason = _callee_writes(inner, name, functions, macros, depth + 1) if depth < 4 else "global_binding_unverified:depth"
            if reason:
                return reason
        return ""
    if callee in functions and callee not in macros:
        # (A macro of the same name is expanded instead of calling the function — review round 3 C1.)
        info = functions[callee]
        if name in info["writes"]:
            return f"global_modified_by_callee:{callee}:{name}"
        if info["unknown_callees"]:
            return f"global_binding_unverified:unknown_callee:{sorted(info['unknown_callees'])[0]}"
        return ""
    if callee in macros and depth < 4:
        body = macros[callee]
        fx = cpc.macro_side_effects(body)
        if re.search(r"\b" + re.escape(name) + r"\b", body) and fx["writes"]:
            return f"global_modified_by_callee:{callee}:{name}"
        if fx["writes"]:
            # The macro assigns / takes an address (``<<=`` included) — possibly of this global via an argument.
            return "global_binding_unverified:macro_assignment:" + callee
        for inner in fx["calls"]:
            reason = _callee_writes(inner, name, functions, macros, depth + 1)
            if reason:
                return reason
        return ""
    return "global_binding_unverified:unknown_callee:" + callee


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
        seen = {(x.start_byte, x.end_byte) for x in nodes if _in_preproc_condition(x)}
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


def _apply_design_range(unit, name, domain):
    """Narrow a declared domain to the unit's SwUDS design range (or explicit enumerated values) — never widen it."""
    from generators.suts import enum_bounds, range_bounds
    domain["type_min"], domain["type_max"] = domain["min"], domain["max"]
    ranged = range_bounds(((unit.get("uds_param_info") or {}).get(name) or {}).get("range"))
    enumerated = enum_bounds((unit.get("value_domains") or {}).get(name))
    constraint = ranged or enumerated
    if not constraint:
        return
    lo, hi = constraint.get("min"), constraint.get("max")
    if type(lo) is not int or type(hi) is not int or not domain["min"] <= lo <= hi <= domain["max"]:
        # A design range the declared type cannot hold is a document defect (SUTS `_fits_type` treats it the
        # same way): keep the declared domain, never widen it, and disclose the conflict on the domain.
        # Blanking every decision of the unit here hid 27 real functions behind one phantom row (R80).
        domain["design_range_conflict"] = {"min": lo, "max": hi,
                                           "source": "uds_range" if ranged else "explicit_enum_values"}
        return
    kept = [v for v in (domain.get("values") or []) if lo <= v <= hi]
    if domain.get("values") and not kept:
        # No enumerator lies in the design range: the two documents disagree — keep the declaration.
        domain["design_range_conflict"] = {"min": lo, "max": hi, "source": "uds_range" if ranged
                                           else "explicit_enum_values", "reason": "no_enumerator_in_range"}
        return
    domain["min"], domain["max"] = lo, hi
    domain["constraint_source"] = "uds_range" if ranged else "explicit_enum_values"
    if kept:
        domain["values"] = kept


# (R2c) Reasons the *expression* engine gives up on a decision whose value the function itself determines: it reads a
# local, an input the function rewrites before the decision, or a global a callee / pointer may change. The source
# oracle runs the whole function instead (`c_source_oracle.observe_decisions`) and reports what each condition holds
# when the decision is reached on the modeled run.
_PATH_FAMILY = ("local_variable_not_input:", "input_modified_before_decision:", "global_address_taken:",
                "global_binding_unverified:", "global_modified_by_callee:", "input_binding_unverified:",
                "identifier_shadowed_by_local:")
_PATH_SAMPLES = 12


def _path_ir(node, raw, atoms):
    """The ``&&``/``||``/``!`` structure of a decision with its conditions as leaves (same order as the inventory)."""
    n = _unwrap(node)
    if n.type == "binary_expression" and _text(n.child_by_field_name("operator"), raw) in {"&&", "||"}:
        op = _text(n.child_by_field_name("operator"), raw)
        return [op, _path_ir(n.child_by_field_name("left"), raw, atoms), _path_ir(n.child_by_field_name("right"), raw, atoms)]
    if n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "!":
        return ["!", _path_ir(n.child_by_field_name("argument"), raw, atoms)]
    atoms.append(n)
    return ["atom", len(atoms) - 1]


def _enclosing_function(node):
    while node is not None and node.type != "function_definition":
        node = node.parent
    return node


def _body_constants(nodes, raw, constants_map, widths):
    """Integer values the text names (literals, integer macros, enumerators) — in order of first appearance."""
    out = []
    for root in nodes:
        for x in _walk(root):
            try:
                if x.type == "number_literal" and widths:
                    value, t = cpc.literal(_text(x, raw), widths)
                    if not cpc.is_float(t):
                        out.append(value)
                elif x.type == "identifier" and _text(x, raw) in constants_map:
                    c = constants_map[_text(x, raw)]
                    if not cpc.is_float(c["type"]):
                        out.append(c["value"])
            except (cpc.Unresolved, KeyError, TypeError, ValueError):
                continue
    return list(dict.fromkeys(v for v in out if type(v) is int))


def _path_samples(domain, constants):
    if domain.get("values"):
        return list(domain["values"])
    lo, hi = domain["min"], domain["max"]
    if hi - lo <= 15:
        return list(range(lo, hi + 1))
    candidates = [0, 1, -1, lo, hi] + [c + d for c in constants for d in (0, -1, 1)]
    return list(dict.fromkeys(v for v in candidates if lo <= v <= hi))[:_PATH_SAMPLES]


def _exits(stmt):
    """Does this statement always leave the enclosing block (``return``/``break``/``continue``/``goto``)?"""
    if stmt is None:
        return False
    if stmt.type in {"return_statement", "break_statement", "continue_statement", "goto_statement"}:
        return True
    if stmt.type == "compound_statement":
        body = [c for c in stmt.named_children if c.type != "comment"]
        return bool(body) and _exits(body[-1])
    if stmt.type == "else_clause":
        inner = [c for c in stmt.named_children if c.type != "comment"]
        return bool(inner) and _exits(inner[-1])
    if stmt.type == "if_statement":
        return _exits(stmt.child_by_field_name("consequence")) and _exits(stmt.child_by_field_name("alternative"))
    return False


def _guard_chain(node):
    """Control conditions a statement sits under, outermost first, with the outcome that leads to it: an ``if`` arm
    (true / false), a loop body (true, at least once), a ``?:`` arm, and an earlier ``if`` in an enclosing block whose one
    arm always leaves the block (``if (x != 3U) { return; }`` — the other outcome leads on). ``switch`` and ``do``
    impose none we can read."""
    chain = []
    child, parent = node, node.parent
    while parent is not None and parent.type != "function_definition":
        if parent.type == "compound_statement":
            early = []
            for sibling in parent.named_children:
                if sibling.start_byte >= child.start_byte:
                    break
                if sibling.type == "if_statement" and sibling.child_by_field_name("condition") is not None:
                    cons, alt = sibling.child_by_field_name("consequence"), sibling.child_by_field_name("alternative")
                    if _exits(cons) and not _exits(alt):
                        early.append((sibling.child_by_field_name("condition"), False))
                    elif alt is not None and _exits(alt) and not _exits(cons):
                        early.append((sibling.child_by_field_name("condition"), True))
            chain.extend(reversed(early))
        cond = parent.child_by_field_name("condition")
        if parent.type in {"if_statement", "conditional_expression"} and cond is not None and cond != child:
            arms = [(parent.child_by_field_name("consequence"), True), (parent.child_by_field_name("alternative"), False)]
            for arm, outcome in arms:
                if arm is not None and arm.start_byte <= node.start_byte < arm.end_byte:
                    chain.append((cond, outcome))
        elif parent.type in {"while_statement", "for_statement"} and cond is not None:
            body = parent.child_by_field_name("body")
            if body is not None and body.start_byte <= node.start_byte < body.end_byte:
                chain.append((cond, True))
        child, parent = parent, parent.parent
    return list(reversed(chain))


def _read_names(body, raw):
    """Identifiers the body reads, in order — a name that only ever stands left of a plain ``=`` is written, not read
    (an input only it assigns would spend the search budget for nothing: R2c review round 1 I2)."""
    out = []
    for x in _walk(body):
        if x.type != "identifier":
            continue
        parent = x.parent
        if parent is not None and parent.type == "assignment_expression" and parent.child_by_field_name("left") == x \
                and _text(parent.child_by_field_name("operator"), raw) == "=":
            continue
        out.append(_text(x, raw))
    return list(dict.fromkeys(out))


def _macro_argument_host(node, raw, scope):
    """The macro (active in this unit, or one its configuration cannot decide) whose argument list contains this node,
    or ``""`` — a macro defined only in an inactive arm is not one here: the call is the function (review round 2 I-b)."""
    status = (scope or {}).get("macro_status") or {}
    parent = node.parent
    while parent is not None and parent.type != "function_definition":
        if parent.type == "call_expression":
            f, args = parent.child_by_field_name("function"), parent.child_by_field_name("arguments")
            name = _text(f, raw) if f is not None and f.type == "identifier" else ""
            undeclared = bool((scope or {}).get("missing_includes")) and name and name not in status \
                and name not in ((scope or {}).get("prototypes") or ()) \
                and name not in (((scope or {}).get("effects") or {}).get("functions") or {})
            if name and (name in status or undeclared) and args is not None \
                    and args.start_byte <= node.start_byte and node.end_byte <= args.end_byte:
                # an undeclared name after a missing include may be that header's macro (review round 3 I1)
                return name
        parent = parent.parent
    return ""


# builtins that evaluate their argument like a function would — every other ``__builtin_*`` may not
# (``__builtin_constant_p``, ``__builtin_types_compatible_p``, ``__builtin_choose_expr``, ``__builtin_object_size``)
EVALUATING_BUILTINS = frozenset({"__builtin_expect", "__builtin_abs", "__builtin_labs", "__builtin_popcount",
                                 "__builtin_clz", "__builtin_ctz", "__builtin_bswap16", "__builtin_bswap32"})


def _not_a_run_time_decision(node, raw, scope):
    """Why this decision is not evaluated when the function runs, or ``""``: inside ``sizeof``/``_Alignof``/``_Generic``
    (unevaluated operands, C11 6.5.3.4p2 / 6.5.1.1p3), inside a builtin that need not evaluate its argument, or a
    compile-time constant (a ``case`` label, an array size, a ``static`` initializer — evaluated once, before)."""
    child, parent = node, node.parent
    while parent is not None and parent.type != "function_definition":
        if parent.type in {"sizeof_expression", "alignof_expression", "generic_expression"}:
            return "decision_in_unevaluated_operand"
        if parent.type == "call_expression":
            f = parent.child_by_field_name("function")
            name = _text(f, raw) if f is not None and f.type == "identifier" else ""
            if name.startswith("__builtin_") and name not in EVALUATING_BUILTINS:
                return "decision_in_unevaluated_operand:" + name
        if parent.type == "case_statement" and parent.child_by_field_name("value") == child:
            return "decision_in_constant_expression:case_label"
        if parent.type == "array_declarator":
            return "decision_in_constant_expression:array_size"
        if parent.type == "declaration" and any(c.type == "storage_class_specifier" and _text(c, raw) == "static"
                                                for c in parent.children):
            return "decision_in_constant_expression:static_initializer"
        child, parent = parent, parent.parent
    return ""


def _refuse_path(decision, why):
    """(R2c review round 2 N-W2) A decision the path engine turns away says so in its reason — the expression engine's
    reason alone reads as if the path engine had never looked."""
    if decision.get("path_refusal"):
        return  # the first refusal is the cause — a later safety net must not overwrite it (review round 3 I3)
    decision["path_refusal"] = why
    decision.setdefault("static_reason", decision.get("reason", ""))
    decision["reason"] = "path_refused:" + why


def _macro_hides_conditions(atom, raw, scope):
    """Name of a macro in this condition whose expansion (transitively) holds ``&&``, ``||`` or ``?:`` — or whose body
    this unit cannot see — else ``""``. Integer constants are values, never conditions."""
    status = (scope or {}).get("macro_status") or {}
    constants = scope["constants"] if (scope or {}).get("constants") is not None else {}
    bodies = {**((scope or {}).get("macro_bodies") or {}), **((scope or {}).get("function_like_macro_bodies") or {})}
    stack = [(t, t) for t in dict.fromkeys(_text(x, raw) for x in _walk(atom) if x.type == "identifier")
             if t in status and t not in constants]
    seen = set()
    while stack:
        name, root = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        body = bodies.get(name)
        if status.get(name) != "active" or body is None or re.search(r"&&|\|\||\?", body):
            return root
        stack.extend((t, root) for t in re.findall(r"[A-Za-z_]\w*", body) if t in status and t not in constants)
    return ""


def _path_design(unit, report, candidates, row_names, domains, scope, selected, *, max_conditions, max_runs,
                 max_steps):
    """(R2c) Unique-cause pairs for decisions the expression engine could not bind, found on the modeled function run.

    Inputs are the unit's row inputs with a declared domain (inventory mode: plus every scalar global the function
    reads). Search, per decision: climb towards it along its guard chain (one input changed at a time, keeping the
    vector that satisfies more of the chain), then vary the reaching vectors — one input at a time, then the product
    of the inputs that changed its observation. Never complete: ``search_complete`` stays false (a failed search is no
    proof). A decision in a loop is evaluated once per iteration: every distinct evaluation is a candidate row.

    Budget: ``max_runs`` vectors and ``max_steps`` interpreter steps summed over them, per function — a deterministic
    cost bound (a vector costs what its run executes), so the same source always gets the same design."""
    from generators import c_source_oracle as cso
    if not cso.scope_matches(unit):
        for decision, _node, _raw in candidates:
            _refuse_path(decision, "project_scope_missing_or_mismatched")
        return
    fn = _enclosing_function(candidates[0][1])
    raw = candidates[0][2]
    specs = []
    for decision, node, _raw in candidates:
        atoms = []
        try:
            ir = _path_ir(node, raw, atoms)
        except Unsupported as exc:
            _refuse_path(decision, str(exc))
            continue
        if len(atoms) > max_conditions:
            _refuse_path(decision, "decision_or_condition_budget")
            continue
        hidden = next((h for a in atoms if (h := _macro_hides_conditions(a, raw, scope))), "")
        if hidden:
            # ``BOTH(t, b)`` = ``(((t) > 3U) && ((b) == 1U))``: after preprocessing the decision has more conditions
            # than this text shows — a pair on the macro as one condition flips two (R2c review round 1 C3)
            _refuse_path(decision, "decision_conditions_hidden_in_macro:" + hidden)
            continue
        if any(x.type == "binary_expression" and _text(x.child_by_field_name("operator"), raw) in {"&&", "||"}
               for a in atoms for x in _walk(a)):
            # ``((a || b) != 0U)`` as one condition: the inner ``b`` would never get a pair, yet the decision would
            # read "designed" (review round 2 N-W1) — the expression engine refuses the same shape
            _refuse_path(decision, "nested_boolean_in_condition")
            continue
        specs.append((decision, {"key": [node.start_byte, node.end_byte, node.type],
                                 "atoms": [[a.start_byte, a.end_byte, a.type] for a in atoms], "ir": ir}, atoms, node))
    if not specs or fn is None:
        return
    # inputs: the row's inputs with a declared domain; inventory mode adds the scalar globals the function reads
    names = list(row_names)
    globals_ = scope.get("globals") or {}
    if unit.get("mcdc_free_globals"):
        names += [n for n in _read_names(fn.child_by_field_name("body"), raw) if n in globals_ and n not in names]
    inputs = []
    for name in names:
        if name in globals_ and (globals_[name].get("volatile") or globals_[name].get("const")):
            continue  # the run never reads an input value for these (review round 2 I-a)
        if name not in domains and name in globals_:
            g = globals_[name]
            try:
                domains[name] = _scope_domain(g["type"], g["typename"], scope, "global_declaration", origin="global",
                                              declared_at=f"{os.path.basename(g['file'])}:{g['line']}")
            except cpc.Unresolved:
                continue
            _apply_design_range(unit, name, domains[name])
        if name in domains:
            inputs.append(name)
    widths = (scope.get("target") or {}).get("widths") or {}
    constants_map = scope["constants"] if scope.get("constants") is not None else {}
    chains = [_guard_chain(node) for _d, _s, _a, node in specs]
    guard_nodes = list({(g.start_byte, g.end_byte, g.type): g for chain in chains for g, _o in chain}.values())
    guard_index = {(g.start_byte, g.end_byte, g.type): i for i, g in enumerate(guard_nodes)}
    decision_constants = _body_constants([a for _d, _s, atoms, _n in specs for a in atoms] + guard_nodes, raw,
                                         constants_map, widths)
    body_constants = _body_constants([fn.child_by_field_name("body")], raw, constants_map, widths)
    constants = list(dict.fromkeys(decision_constants + body_constants))
    samples = {name: _path_samples(domains[name], constants) for name in inputs}
    base = {name: _default_value(domains[name]) for name in inputs}
    cache: dict[tuple, tuple] = {}
    order: list[dict] = []  # vectors in the order they ran — every scan below is deterministic
    plan = [spec for _d, spec, _a, _n in specs]
    guards = [[g.start_byte, g.end_byte, g.type] for g in guard_nodes]
    pairers = [_Pairer(decision["decision_id"], len(atoms)) for decision, _s, atoms, _n in specs]
    tallies = [Counter() for _ in specs]
    spent = [0]

    def vkey(v):
        return tuple(sorted(v.items()))

    def exhausted():
        return len(cache) >= max_runs or spent[0] >= max_steps

    def observation(r, index):
        if r["status"] != "supported":
            return {"state": "unsupported", "reason": r["reason"]}
        return r["decisions"].get(index) or {"state": "missing"}

    def run(vectors):
        """Run the vectors not run yet (in chunks: the step budget is checked between them); feed every observation to
        the decisions' pair finders. Returns the vectors that ran."""
        todo, seen = [], set()
        for v in vectors:
            k = vkey(v)
            if k not in cache and k not in seen:
                todo.append(v)
                seen.add(k)
        added = []
        for start in range(0, len(todo), 16):
            if exhausted():
                break
            chunk = todo[start:start + max(0, min(16, max_runs - len(cache)))]
            for v, r in zip(chunk, cso.observe_decisions(unit, chunk, plan, guards), strict=True):
                cache[vkey(v)] = (v, r)
                order.append(v)
                added.append(v)
                spent[0] += int(r.get("steps") or 0)
                for index in range(len(specs)):
                    s = observation(r, index)
                    tallies[index][s["state"] + (":" + s["reason"].split(":", 1)[0] if s.get("reason") else "")] += 1
                    if s["state"] == "evaluated":
                        for inst in s["instances"]:
                            pairers[index].add(v, inst, r.get("possible_undefined_behavior") or [])
        return added

    def reaches(v, index):
        return observation(cache[vkey(v)][1], index)["state"] not in ("unreached", "missing", "unsupported")

    def progress(v, index):
        """(reached, guards of the chain satisfied in order on the best path) — the climb's objective."""
        r = cache[vkey(v)][1]
        if r["status"] != "supported":
            return (False, -1)
        if reaches(v, index):
            return (True, len(chains[index]))
        best = 0
        paths = r.get("guards") or {}
        for path in range(max((len(p) for p in paths.values()), default=0)):
            depth = 0
            for g, outcome in chains[index]:
                seq = (paths.get(guard_index[(g.start_byte, g.end_byte, g.type)]) or [])
                if path >= len(seq) or outcome not in seq[path]:
                    break
                depth += 1
            best = max(best, depth)
        return (False, best)

    def neighbours(v):
        return [{**v, name: value} for name in inputs for value in samples[name] if value != v[name]]

    run([base])
    for index in range(len(specs)):
        if pairers[index].complete() or not order:
            continue
        # 1. climb towards the decision along its guard chain
        best = max(order, key=lambda v: progress(v, index))
        while not progress(best, index)[0] and not exhausted():
            added = run(neighbours(best))
            if not added:
                break
            candidate = max(added, key=lambda v: progress(v, index))
            if progress(candidate, index) <= progress(best, index):
                break
            best = candidate
        # 2. around the vectors that reach it, breadth first: one input at a time from each (a vector a neighbour found
        #    joins the frontier — ``A && B`` needs A true before B's input matters), then the product of the inputs
        #    that changed its observation
        frontier = [v for v in order if reaches(v, index)]
        on_frontier = {vkey(v) for v in frontier}
        expanded = 0
        while expanded < len(frontier) and not exhausted() and not pairers[index].complete():
            for v in run(neighbours(frontier[expanded])):
                if reaches(v, index) and vkey(v) not in on_frontier:
                    frontier.append(v)
                    on_frontier.add(vkey(v))
            expanded += 1
        if frontier and not pairers[index].complete() and not exhausted():
            anchor = frontier[0]
            here = observation(cache[vkey(anchor)][1], index)
            influence = [name for name in inputs
                         if any(vkey({**anchor, name: value}) in cache
                                and observation(cache[vkey({**anchor, name: value})][1], index) != here
                                for value in samples[name])]
            if influence:
                combos = itertools.islice(itertools.product(*(samples[name] for name in influence)),
                                          max(0, max_runs - len(cache)))
                run([{**anchor, **dict(zip(influence, combo, strict=True))} for combo in combos])
    for index, (decision, spec, atoms, _node) in enumerate(specs):
        pairs = pairers[index].pairs
        states = tallies[index]
        decision.update(evaluation="source_path", static_reason=decision["reason"], path_spec=spec,
                        conditions=[{"condition_id": f"C{i + 1}", "expression": _text(a, raw)} for i, a in enumerate(atoms)],
                        path_search={"runs": len(cache), "steps": spent[0], "budget_exhausted": exhausted(),
                                     "inputs": inputs, "guards": len(chains[index]),
                                     "observations": dict(states.most_common())},
                        candidate_count=len(cache), search_complete=False)
        for pair in pairs.values():
            for side in ("a", "b"):
                # same key form as the expression path's vectors: one vector, one row
                selected.setdefault(json.dumps(pair[f"inputs_{side}"], sort_keys=True), pair[f"inputs_{side}"])
        decision["pairs"] = [pairs[i] for i in sorted(pairs)]
        if len(pairs) == len(atoms):
            decision["status"], decision["reason"] = "designed", "unique_cause_pairs_found"
        elif pairs:
            decision["status"], decision["reason"] = "partial", "path_search_incomplete"
        elif states.get("evaluated"):
            decision["status"], decision["reason"] = "no_pair_found", "path_search_no_pair"
        else:
            # never determined on any run: keep "unsupported" with what the modeled run says instead of the binding
            top = next(iter(states.most_common(1)), ("no_run", 0))[0]
            decision["reason"] = "path_evaluation:" + top
    for name in inputs:
        report["domains"].setdefault(name, domains[name])


def _short_circuit_unique_cause(a, b, i):
    """Unique cause with short-circuit don't-care: condition ``i`` is evaluated in both and differs, the outcome differs,
    and every other condition evaluated in *both* has the same value — one the short circuit skips on either side cannot
    have caused the difference (VectorCAST's MC/DC tables mark it as don't-care too)."""
    if a["decision"] == b["decision"] or not (a["observed"][i] and b["observed"][i]) or a["truth"][i] == b["truth"][i]:
        return False
    return all(j == i or not (a["observed"][j] and b["observed"][j]) or a["truth"][j] == b["truth"][j]
               for j in range(len(a["truth"])))


class _Pairer:
    """Unique-cause pairs of one decision, found incrementally as evaluations arrive (`_short_circuit_unique_cause`).
    The two evaluations may come from one run (two iterations of a loop). Evaluations are compared per distinct
    evaluated pattern, so the cost does not grow with the number of runs that repeat a pattern."""

    def __init__(self, decision_id, conditions):
        self.did, self.n, self.pairs, self.groups = decision_id, conditions, {}, {}

    def complete(self):
        return len(self.pairs) == self.n

    def add(self, inputs, inst, possible_ub=()):
        # ``possible_ub``: undefined behaviour the run may have *after* the decision (disclosed, as for outputs)
        row = {"inputs": inputs, "truth": inst["truth"], "decision": inst["decision"], "observed": inst["observed"],
               "possible_ub": list(possible_ub)}
        pattern = tuple(t if o else "*" for t, o in zip(inst["truth"], inst["observed"], strict=True))
        for i in range(self.n):
            if i in self.pairs or not inst["observed"][i]:
                continue
            mine = self.groups.setdefault((i, inst["truth"][i], inst["decision"]), {})
            if pattern in mine:
                continue
            mine[pattern] = row
            for other in self.groups.get((i, not inst["truth"][i], not inst["decision"]), {}).values():
                if _short_circuit_unique_cause(other, row, i):
                    pair = {"pair_id": f"{self.did}:C{i + 1}:P1", "condition_id": f"C{i + 1}", "retained_status": "pending"}
                    for suffix, member in (("a", other), ("b", row)):
                        for key, value in member.items():
                            pair[f"{key}_{suffix}"] = value
                    self.pairs[i] = pair
                    break


def _path_revalidation(decision, lookup, unit, normalized):
    """(R2c) Re-run the oracle on every emitted row a pair of this decision names.

    ``{row key: {pair_id + side: evaluate_decision-shaped}}`` — each side is checked for *its* claimed evaluation among
    the row's evaluations (a loop may evaluate the decision several times in one run)."""
    from generators import c_source_oracle as cso
    if unit is None:
        return {}
    keys = {}
    for pair in decision["pairs"]:
        for side in ("a", "b"):
            row = lookup.get(json.dumps(pair[f"inputs_{side}"], sort_keys=True))
            if row is not None:
                v = normalized(row["inputs"])
                keys.setdefault(json.dumps(v, sort_keys=True), v)
    runs = dict(zip(keys, cso.observe_decisions(unit, list(keys.values()), [decision["path_spec"]]), strict=True))
    out = {}
    for pair in decision["pairs"]:
        for side in ("a", "b"):
            row = lookup.get(json.dumps(pair[f"inputs_{side}"], sort_keys=True))
            r = runs.get(json.dumps(normalized(row["inputs"]), sort_keys=True)) if row is not None else None
            s = (r or {}).get("decisions", {}).get(0) or {}
            claimed = {"truth": pair.get(f"truth_{side}"), "observed": pair.get(f"observed_{side}"),
                       "decision": pair.get(f"decision_{side}")}
            if r and r["status"] == "supported" and s.get("state") == "evaluated" and claimed in s["instances"]:
                out[(pair["pair_id"], side)] = {"status": "supported", **claimed}
    return out


def build_mcdc_design(unit: dict[str, Any], *, max_candidates: int = 4096, max_conditions: int = 12,
                      max_decisions: int = 64, max_path_runs: int = 1536, max_path_steps: int = 30_000,
                      declared_domains: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Find real-input unique-cause pairs within explicit search budgets.

    Failed search is not infeasibility proof. Unsupported and budget-limited
    decisions remain in the denominator, and source reachability is not claimed.

    ``declared_domains`` maps input names to integer domains the caller resolved
    from a *declaration* (project typedef, enum declaration) — never from a
    naming convention. It only fills names the source/metadata left unresolved.
    """
    report = {"schema_version": 3, "function": unit.get("name", ""), "decisions": [],
              "selected_inputs": [], "execution_status": "not_run", "reachability": "unverified",
              "budgets": {"max_candidates": max_candidates, "max_conditions": max_conditions, "max_decisions": max_decisions,
                          "max_path_runs": max_path_runs, "max_path_steps": max_path_steps,
                          # per variable-connected component, and again for the combination of components
                          "max_candidates_scope": "per_component_and_combination"}}
    extra: dict[str, Any] = {}
    try:
        scope_text_matches = bool(unit.get("project_scope")) and unit["project_scope"].get("main_file_sha256") == \
            hashlib.sha256(str(unit.get("source_text") or "").encode()).hexdigest()
        if unit.get("project_scope") and not scope_text_matches:
            # The scope describes another text of this file: none of its facts may be used (review I5).
            report["project_context_status"] = "source_text_mismatch"
        if unit.get("source_text") and scope_text_matches:
            found, domains, source_kind, source_hash, issue, extra = _scoped_source_decisions(
                unit, unit["project_scope"], declared_domains)
        else:
            found, domains, source_kind, source_hash, issue = _source_decisions(unit, declared_domains)
    except (ValueError, AttributeError, TypeError, RecursionError) as exc:
        # An exception while listing decisions is an enumeration failure too — without this the function
        # vanished from every count (review round 3 W-B).
        found, domains, source_kind, source_hash, issue = [], {}, "unknown", "", f"source_exception:{type(exc).__name__}"
    scope = extra.get("scope") or {}
    widths = (scope.get("target") or {}).get("widths") or None
    constants_map = scope["constants"] if scope.get("constants") is not None else {}  # lazy: empty until asked
    report["domains"] = domains
    report["constants"] = {}
    report["types"] = {}
    def cast_type(text):
        t = _scope_type(scope, text)
        report["types"][text] = t
        return t
    if widths:
        # Exact C conversions below rest on this testimony; re-validation (finalize) uses the same widths.
        report["target"] = {"widths": widths, "basis": "typedef_name_testimony"}
    # Reuse the existing input-domain parser. Only narrow an already explicit
    # declared integer domain; a design range alone cannot invent a C type.
    for name, domain in domains.items():
        _apply_design_range(unit, name, domain)
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
    path_candidates = []
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
            if host := _macro_argument_host(node, raw, scope):
                # ``DBG("%d", (a > 3U) && (b == 1U))``: the expansion decides whether (and how often) this text is a
                # decision at all — ``#define DBG(...)`` drops it (R2c review round 1 C1 / I1)
                raise Unsupported("decision_inside_macro_argument:" + host)
            if not_run := _not_a_run_time_decision(node, raw, scope):
                # ``sizeof((a > 3U) && (b == 1U))`` is never evaluated (C11 6.5.3.4p2), ``case (A && B):`` is folded
                # by the compiler — not decisions of the run (R2c review rounds 2 N-W3 / 3 W1 W2 I1)
                raise Unsupported(not_run)
            try:
                ir, atoms, variables, constants = _compile(node, raw, domains, constants_map, widths,
                                                           cast_type if scope else None)
            except Unsupported as exc:
                if extra and str(exc).startswith("missing_declared_domain:"):
                    raise Unsupported(_identifier_reason(str(exc).split(":", 1)[1], extra)) from exc
                raise
            decision["conditions"] = [{k: v for k, v in atom.items() if not k.startswith("_")} for atom in atoms]
            for x in _walk(node):
                name = _text(x, raw) if x.type == "identifier" else ""
                if name in constants_map and name not in domains:
                    c = constants_map[name]
                    report["constants"][name] = {"value": c["value"], "type": c["type"], "kind": c.get("kind", ""),
                                                 "declared_at": f"{os.path.basename(c.get('file', ''))}:{c.get('line', '')}"}
            if set(variables) & mutated:
                raise Unsupported("input_binding_modified_or_shadowed")
            for name in variables if extra else []:
                if name in extra["params"] and name in extra["locals"]:
                    # A block-scope declaration reuses the parameter's name: which object the decision reads depends
                    # on scopes this engine does not track (review C3g, MISRA 5.3).
                    raise Unsupported("identifier_shadowed_by_local:" + name)
                if reason := _rebinding_write(name, node, extra):
                    raise Unsupported(reason)
                if name not in extra["params"] and (reason := _global_binding_issue(name, node, extra)):
                    raise Unsupported(reason)
            # An input the decision does not read cannot change its outcome: a missing domain for it (pointer, array,
            # struct) no longer blocks the decision (R80 carry-over — one pointer parameter blocked every decision of
            # the function). The vector leaves it unset and says so; the row shows a blank cell, never a guess.
            if not_designed := sorted(set(row_names) - set(domains)):
                decision["inputs_not_designed"] = not_designed
            # Globals resolved from their declaration may join the vector only where no fixed row exists (inventory /
            # oracle). A SUTS row renders the unit's input columns only: a global outside them would be a hidden input
            # (R80 review W5; the exporter reports it as `stale_mcdc_pair_input`) — the UDS input list omits it.
            engine_globals = [v for v in variables if v not in row_names and unit.get("mcdc_free_globals")
                              and domains[v].get("source") == "global_declaration"]
            if missing := sorted(set(variables) - set(row_names) - set(engine_globals)):
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
            defaults = {name: _default_value(domains[name]) for name in [*row_names, *engine_globals] if name in domains}
            ub_skipped = [0]
            components, components_complete, decision["component_candidate_count"] = _realizable_truths(
                atoms, variables, values, defaults, max_candidates, ub_skipped)
            combined_size = math.prod(len(c) for c in components)
            for parts in itertools.islice(itertools.product(*components), max(0, max_candidates)):
                inputs = dict(defaults)
                for part in parts:
                    inputs.update(part)
                decision["candidate_count"] += 1
                try:
                    truth, outcome, observed = _evaluate(ir, atoms, inputs)
                except cpc.Unresolved:
                    decision["undefined_behavior_candidates"] = decision.get("undefined_behavior_candidates", 0) + 1
                    continue
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
            # A condition identical to another one (same compiled atom) always has the same truth value as its twin:
            # it can never flip alone, so no unique-cause pair exists for it — a proof, not a failed search
            # (``A && B || A && C``; masking MC/DC would be needed). Recorded per condition.
            infeasible = []
            for i in range(len(atoms)):
                twin = next((j for j in range(len(atoms)) if j != i and atoms[j]["_atom"] == atoms[i]["_atom"]), None)
                if i not in pairs and twin is not None:
                    infeasible.append({"condition_id": f"C{i + 1}", "coupled_with": f"C{twin + 1}",
                                       "reason": "strongly_coupled_identical_condition"})
            if infeasible:
                decision["infeasible_conditions"] = infeasible
            if not variables:
                # Every operand is a constant: the decision always has one value (the other outcome is unreachable),
                # so no condition can show an independent effect.
                _truth, decision["constant_value"], _observed = _evaluate(ir, atoms, {})
                decision["reason"] = "unique_cause_infeasible:constant_decision"
            elif len(pairs) == len(atoms):
                decision["reason"] = "unique_cause_pairs_found"
            elif len(pairs) + len(infeasible) == len(atoms):
                decision["reason"] = "unique_cause_infeasible:coupled_condition"
            elif ub_skipped[0] or decision.get("undefined_behavior_candidates"):
                # Every condition is evaluated per candidate, so an input that is undefined only in a condition the
                # short circuit would skip (``d != 0 && n / d > 3``) is dropped too: not a proof of no pair (review I1).
                decision["undefined_behavior_candidates"] = decision.get("undefined_behavior_candidates", 0) + ub_skipped[0]
                decision["reason"] = "no_pair_undefined_behavior_candidates_skipped"
            else:
                decision["reason"] = "no_pair_in_candidate_domain" if decision["search_complete"] else "candidate_budget_exhausted"
        except (Unsupported, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            decision["reason"] = str(exc)
            if extra and node is not None and str(exc).startswith(_PATH_FAMILY) and index < max_decisions:
                path_candidates.append((decision, node, raw))
    if path_candidates:
        try:
            _path_design(unit, report, path_candidates, row_names, domains, scope, selected,
                         max_conditions=max_conditions, max_runs=max_path_runs, max_steps=max_path_steps)
        except Exception as exc:  # noqa: BLE001 — a defect here must not stop the SUTS document (review round 1 W4)
            for decision, _node, _raw in path_candidates:
                if decision.get("evaluation") != "source_path":
                    _refuse_path(decision, f"path_design_exception:{type(exc).__name__}")
    report["selected_inputs"] = list(selected.values())
    names = set((scope or {}).get("assumed_undefined") or ()) | set((scope or {}).get("assumed_undefined_body") or ())
    if names:
        # (R17 review R2 W1) the live arms of this unit's #if rest on build-configuration evidence for these names
        report["assumed_undefined"] = sorted(names)
    finalize_mcdc_design(report, [])
    return report


def finalize_mcdc_design(report: dict[str, Any], sequences: list[dict[str, Any]],
                         unit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind and revalidate retained pairs after output sequence truncation.

    A decision designed on the modeled run (``evaluation == "source_path"``, R2c) is revalidated by running the source
    oracle again on both emitted rows — ``unit`` (with its project scope) is required for that; without it such pairs
    are ``invalidated``."""
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
        path_checks = _path_revalidation(decision, lookup, unit, normalized) \
            if decision.get("evaluation") == "source_path" and decision["pairs"] else {}
        for pair in decision["pairs"]:
            a = lookup.get(json.dumps(pair["inputs_a"], sort_keys=True))
            b = lookup.get(json.dumps(pair["inputs_b"], sort_keys=True))
            pair["seq_a"], pair["seq_b"] = a.get("seq_num") if a else None, b.get("seq_num") if b else None
            pair["retained_status"] = "truncated"
            if a is None or b is None:
                continue
            if decision.get("evaluation") == "source_path":
                va = path_checks.get((pair["pair_id"], "a")) or {"status": "unsupported"}
                vb = path_checks.get((pair["pair_id"], "b")) or {"status": "unsupported"}
            else:
                widths = (report.get("target") or {}).get("widths")
                va = evaluate_decision(decision["expression"], normalized(a["inputs"]), report["domains"],
                                       report.get("constants"), widths, report.get("types"))
                vb = evaluate_decision(decision["expression"], normalized(b["inputs"]), report["domains"],
                                       report.get("constants"), widths, report.get("types"))
            ci = int(pair["condition_id"][1:]) - 1
            valid = va.get("status") == vb.get("status") == "supported"
            if valid and decision.get("evaluation") == "source_path":
                valid = _short_circuit_unique_cause(va, vb, ci)  # (R2c) the rule the path search designed with
            else:
                valid = valid and va["decision"] != vb["decision"] and va["observed"][ci] and vb["observed"][ci]
                valid = valid and [i for i, (x, y) in enumerate(zip(va["truth"], vb["truth"], strict=True))
                                   if x != y] == [ci]
            if not valid:
                pair["retained_status"] = "invalidated"
                continue
            pair["retained_status"] = "retained"
            retained += 1
            for role, seq, ev in (("a", a, va), ("b", b, vb)):
                seq["mcdc_design"].append({"decision_id": decision["decision_id"], "pair_id": pair["pair_id"],
                    "condition_id": pair["condition_id"], "role": role, "truth": ev["truth"], "observed": ev["observed"],
                    "decision": ev["decision"], "source_hash": report["source_hash"],
                    "evaluation": decision.get("evaluation") or "expression",
                    # (R2c review round 1 W7) undefined behaviour the run may have after the decision — disclosed
                    "possible_ub": list(pair.get(f"possible_ub_{role}") or []),
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
