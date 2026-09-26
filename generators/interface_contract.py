"""Interface contract of an integration flow (R7, P4/G5) — read from the source text, never guessed.

For every call along a flow that crosses a module (file) boundary, the caller's own text says:

* **how the callee's return value is used**: ``ignored`` (expression statement), ``checked`` (a comparison, a
  condition, ``!f()``), ``assigned`` (stored — the name it goes to is kept), ``returned`` (handed up), ``passed`` (an
  argument of another call) — and, when checked against named or literal values, **which** values
  (``LinRecv() != ERROR_OK`` → ``ERROR_OK``). Those values are the error-propagation contract;
* **the argument bindings**: callee parameter ← argument text, with the parameter's declared type when the callee's
  definition is readable (``(U8 id, U16 len)`` ← ``(msg.id, n)``) — two arguments of one type can be swapped
  unnoticed, which is what an interface test must be able to tell apart;
* **global producer → consumer**: a global written (assignment / ``++``/``--``) in one module and read in another
  within the flow.

Nothing is inferred about behaviour: a callee whose definition cannot be read keeps ``params: None``; a return value
of a ``void`` callee is not an interface; a call the parser cannot name (a function pointer, a call through an
expression) is listed in ``unresolved_calls`` with its text. A typedef cast with a parenthesized operand
(``(U16)(f())``) parses like a call of ``(U16)`` — a parenthesized typedef name applied to one operand is read as the
cast it is (review round 2 W-2). A module is a source **file** (its path — two files with one name in two roots are two
modules); a function defined more than once is ambiguous and left out of the contract (listed); a ``function_definition``
named by a C keyword (``if`` — preprocessor debris the parser cannot resolve) is not a function (round 2 W-5).

The contract is **evidence, not a change to the tests** (R7 review round 1 W1): every callee on an integration flow is
integrated code, so injecting its return value would turn an integration case into a stub case. For each used return
the contract only *suggests* the values an error-propagation test should drive it to (from the source: the compared
constant and a neighbour on the other side of the check, another enumerator, the declared type's bounds) — shown in the
"Interface Evidence" sheet as not applied.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from report_gen.c_return import returns_value

_COMPARE = {"==", "!=", "<", "<=", ">", ">="}
_LITERAL = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*")
_C_KEYWORDS = frozenset({"if", "else", "while", "for", "do", "switch", "case", "default", "return", "sizeof", "goto",
                         "break", "continue"})
_TRUTH_PARENTS = {"if_statement", "while_statement", "do_statement", "condition_clause"}


def _text(node, raw: bytes) -> str:
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace") if node is not None else ""


def _callee_name(call, raw: bytes) -> str:
    f = call.child_by_field_name("function")
    return _text(f, raw) if f is not None and f.type == "identifier" else ""


def _unwrap_up(node):
    parent = node.parent
    while parent is not None and parent.type == "parenthesized_expression":
        node, parent = parent, parent.parent
    return node, parent


def is_cast_call(call, raw: bytes, types) -> bool:
    """``(U16)(f())`` — tree-sitter does not know typedef names and parses a cast whose operand is parenthesized as a
    call of ``(U16)``. A parenthesized typedef name applied to exactly one operand is that cast (round 2 W-2)."""
    f = call.child_by_field_name("function")
    if f is None or f.type != "parenthesized_expression":
        return False
    inner = f.named_children
    args = call.child_by_field_name("arguments")
    operands = [a for a in args.named_children if a.type != "comment"] if args is not None else []
    return len(inner) == 1 and inner[0].type in {"identifier", "type_identifier"} and _text(inner[0], raw) in types \
        and len(operands) == 1


def _up(node, raw: bytes, types):
    """Unwrap parentheses and value-keeping casts above ``node`` (``(U8)f()``, ``(U16)(f())``)."""
    node, parent = _unwrap_up(node)
    while parent is not None:
        if parent.type == "cast_expression" and _text(parent.child_by_field_name("type"), raw).strip() != "void":
            node, parent = _unwrap_up(parent)       # ``(U8)f()`` — the value still flows on (review W4)
        elif parent.type == "argument_list" and parent.parent is not None and is_cast_call(parent.parent, raw, types):
            node, parent = _unwrap_up(parent.parent)
        else:
            return node, parent
    return node, parent


def _truth_use(node, parent, raw: bytes) -> dict[str, Any] | None:
    if parent.type == "unary_expression" and _text(parent.child_by_field_name("operator"), raw) == "!":
        return {"use": "checked", "operator": "!", "against": "0"}
    # ``for (init; cond; update)``: only the condition is a test (round 3 W1 — ``for (i = f(); …)`` is an assignment)
    if parent.type in _TRUTH_PARENTS or \
            (parent.type in {"for_statement", "conditional_expression"} and parent.child_by_field_name("condition") == node):
        return {"use": "checked", "operator": "truth", "against": "0"}
    return None


_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "==", "!=": "!="}


def return_use(call, raw: bytes, types=frozenset()) -> dict[str, Any]:
    """How the caller uses the value of ``call``. Casts (``(U8)f()``, ``(U16)(f())`` when ``types`` names ``U16``)
    and an assignment inside a test (``if ((x = f()) != OK)``, ``if ((x = f()))``) are looked through; a comparison is
    reported with the call on the left (``10U < f()`` → ``f() > 10U``)."""
    node, parent = _up(call, raw, types)
    if parent is None:
        return {"use": "unknown"}
    if parent.type == "expression_statement":
        return {"use": "ignored"}
    if parent.type == "cast_expression":
        return {"use": "ignored", "note": "cast_to_void"}
    if parent.type == "assignment_expression" and parent.child_by_field_name("right") == node:
        target = _text(parent.child_by_field_name("left"), raw).strip()
        outer_node, outer = _up(parent, raw, types)
        if outer is not None and outer.type == "binary_expression" and \
                _text(outer.child_by_field_name("operator"), raw) in _COMPARE | {"&&", "||"}:
            node, parent = outer_node, outer    # ``(x = f()) != OK`` — stored and checked (review W4)
        elif outer is not None and (truth := _truth_use(outer_node, outer, raw)) is not None:
            return truth                        # ``if ((x = f()))`` — stored and tested (round 2 W-2)
        else:
            return {"use": "assigned", "to": target}
    if parent.type == "binary_expression":
        op = _text(parent.child_by_field_name("operator"), raw)
        if op in _COMPARE:
            left = parent.child_by_field_name("left") == node
            other = parent.child_by_field_name("right") if left else parent.child_by_field_name("left")
            # the operator as seen from the call's side (review W2): ``10U < f()`` is ``f() > 10U``
            return {"use": "checked", "operator": op if left else _FLIP[op], "against": _text(other, raw).strip()}
        if op in {"&&", "||"}:
            return {"use": "checked", "operator": op, "against": ""}
        return {"use": "operand", "operator": op}
    truth = _truth_use(node, parent, raw)
    if truth is not None:
        return truth
    if parent.type == "init_declarator":
        return {"use": "assigned", "to": _text(parent.child_by_field_name("declarator"), raw).strip()}
    if parent.type == "return_statement":
        return {"use": "returned"}
    if parent.type == "argument_list":
        return {"use": "passed", "to": _callee_name(parent.parent, raw) if parent.parent is not None else ""}
    if parent.type == "switch_statement":
        return {"use": "checked", "operator": "switch", "against": ""}
    return {"use": parent.type}


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _params(fn, raw: bytes) -> list[dict[str, str]] | None:
    decl = fn.child_by_field_name("declarator")
    while decl is not None and decl.type != "function_declarator":
        decl = decl.child_by_field_name("declarator")
    plist = decl.child_by_field_name("parameters") if decl is not None else None
    if plist is None:
        return None
    out = []
    for p in plist.named_children:
        if p.type != "parameter_declaration":
            continue
        typ = _text(p.child_by_field_name("type"), raw).strip()
        d = p.child_by_field_name("declarator")
        name = ""
        stars = ""
        while d is not None:
            if d.type == "identifier":
                name = _text(d, raw)
                break
            if d.type == "pointer_declarator":
                stars += "*"
            if d.type == "array_declarator":
                stars += "[]"
            d = d.child_by_field_name("declarator")
        if typ == "void" and not name:
            continue
        out.append({"name": name, "type": (typ + " " + stars).strip()})
    return out


def _return_type(fn, raw: bytes) -> str:
    typ = _text(fn.child_by_field_name("type"), raw).strip()
    decl = fn.child_by_field_name("declarator")
    return typ + ("*" if decl is not None and decl.type == "pointer_declarator" else "")


class SourceIndex:
    """Function name → (definition node, raw bytes, file) over a set of source files (first definition per name is
    kept; every duplicate name is listed in ``duplicates``), and the typedef names of every file (``types`` — to read
    ``(U16)(f())`` as a cast)."""

    def __init__(self, texts: dict[str, str], parser):
        self.defs: dict[str, tuple[Any, bytes, str]] = {}
        self.duplicates: set[str] = set()
        self.types: set[str] = set()
        self.keyword_definitions = 0
        for path, text in sorted(texts.items()):
            is_c = path.lower().endswith(".c")
            if not is_c and not path.lower().endswith(".h"):
                continue
            raw = text.encode("utf-8")
            for n in _walk(parser.parse(raw).root_node):
                if n.type == "type_definition":
                    for d in n.children_by_field_name("declarator"):
                        while d is not None and d.type not in {"type_identifier", "identifier"}:
                            d = d.child_by_field_name("declarator")
                        if d is not None:
                            self.types.add(_text(d, raw))
                if not is_c or n.type != "function_definition":
                    continue
                decl = n.child_by_field_name("declarator")
                while decl is not None and decl.type not in {"function_declarator"}:
                    decl = decl.child_by_field_name("declarator")
                ident = decl.child_by_field_name("declarator") if decl is not None else None
                name = _text(ident, raw) if ident is not None and ident.type == "identifier" else ""
                if not name:
                    continue
                if name in _C_KEYWORDS:
                    self.keyword_definitions += 1   # ``else if (…)`` broken by the preprocessor: not a function
                    continue
                if name in self.defs:
                    self.duplicates.add(name)
                    continue
                self.defs[name] = (n, raw, path)

    def module(self, name: str) -> str:
        """The file that defines ``name`` (its path: two ``util.c`` in two roots are two modules — review W6)."""
        entry = self.defs.get(name)
        return entry[2] if entry else ""

    @staticmethod
    def label(module: str) -> str:
        return Path(module).stem if module else ""


def _writes_and_reads(fn, raw: bytes, globals_: set[str]) -> tuple[set[str], set[str]]:
    writes, reads = set(), set()
    body = fn.child_by_field_name("body")
    for n in _walk(body) if body is not None else ():
        if n.type == "assignment_expression":
            left = n.child_by_field_name("left")
            base = left
            while base is not None and base.type in {"subscript_expression", "field_expression",
                                                    "parenthesized_expression"}:
                base = base.child_by_field_name("argument") or (base.named_children[0] if base.named_children else None)
            if base is not None and base.type == "identifier" and _text(base, raw) in globals_:
                writes.add(_text(base, raw))
        elif n.type == "update_expression":
            arg = n.child_by_field_name("argument")
            if arg is not None and arg.type == "identifier" and _text(arg, raw) in globals_:
                writes.add(_text(arg, raw))
        elif n.type == "identifier" and _text(n, raw) in globals_:
            parent = n.parent
            if parent is not None and parent.type == "assignment_expression" and parent.child_by_field_name("left") == n \
                    and _text(parent.child_by_field_name("operator"), raw) == "=":
                continue
            reads.add(_text(n, raw))
    return writes, reads


def flow_contract(chain: list[str], index: SourceIndex, globals_: set[str]) -> dict[str, Any]:
    """The interface points of one flow: the functions of ``chain`` (entry first) and the calls between them."""
    ambiguous = [f for f in dict.fromkeys(chain) if f in index.duplicates]
    members = [f for f in dict.fromkeys(chain) if f in index.defs and f not in index.duplicates]
    member_set = set(members)
    calls, unresolved = [], []
    for caller in members:
        fn, raw, path = index.defs[caller]
        body = fn.child_by_field_name("body")
        for n in _walk(body) if body is not None else ():
            if n.type != "call_expression" or is_cast_call(n, raw, index.types):
                continue
            callee = _callee_name(n, raw)
            if not callee:
                unresolved.append({"caller": caller, "text": _text(n, raw)[:80], "line": n.start_point[0] + 1})
                continue
            if callee not in member_set or index.module(callee) == index.module(caller):
                continue
            cfn, craw, _cpath = index.defs[callee]
            ret = _return_type(cfn, craw)
            params = _params(cfn, craw)
            args = [_text(a, raw).strip() for a in n.child_by_field_name("arguments").named_children
                    if a.type != "comment"]
            point = {"caller": caller, "caller_module": index.label(index.module(caller)), "callee": callee,
                     "callee_module": index.label(index.module(callee)), "line": n.start_point[0] + 1,
                     "return_type": ret,
                     "args": args, "params": params}
            if params is not None and len(params) == len(args):
                point["bindings"] = [{"param": p["name"], "type": p["type"], "arg": a} for p, a in zip(params, args, strict=True)]
                types = [p["type"] for p in params]
                point["swappable_pairs"] = [[params[i]["name"], params[j]["name"]] for i in range(len(params))
                                            for j in range(i + 1, len(params))
                                            if types[i] == types[j] and args[i] != args[j]]
            if returns_value(ret):
                point["return_use"] = return_use(n, raw, index.types)
            calls.append(point)
    rw = {f: _writes_and_reads(index.defs[f][0], index.defs[f][1], globals_) for f in members}
    flows = []
    for g in sorted(globals_):
        producers = [f for f in members if g in rw[f][0]]
        consumers = [f for f in members if g in rw[f][1]]
        for p in producers:
            for c in consumers:
                if index.module(p) != index.module(c):
                    flows.append({"global": g, "producer": p, "producer_module": index.label(index.module(p)),
                                  "consumer": c, "consumer_module": index.label(index.module(c))})
    return {"functions": members, "missing_functions": [f for f in dict.fromkeys(chain) if f not in index.defs],
            "ambiguous_functions": ambiguous, "calls": calls, "unresolved_calls": unresolved, "global_flows": flows}


# ── (R7) suggested return values for an error-propagation test (evidence only) ──────

_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+\(?[ \t]*(?:\([ \t]*\w+[ \t]*\)[ \t]*)?"
                     r"([-+]?(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*[ \t]*\)?[ \t]*(?://.*|/\*.*?\*/[ \t]*)?$", re.M)


def _int(text: str) -> int:
    text = text.rstrip("uUlL")
    digits = text.lstrip("+-")
    if digits.lower().startswith("0x"):
        return int(text, 16)
    if len(digits) > 1 and digits.startswith("0") and set(digits) <= set("01234567"):
        return int(text, 8)   # ``010`` is eight in C (MISRA 7.1 forbids it — still read as C does)
    return int(text)


def int_defines(texts: dict[str, str]) -> dict[str, int]:
    """Object-like macros whose body is one integer (``#define ERROR_OK (0U)``); a name defined twice with different
    values is dropped (which one applies depends on the build)."""
    seen: dict[str, set[int]] = {}
    for text in texts.values():
        for m in _DEFINE.finditer(text):
            seen.setdefault(m.group(1), set()).add(_int(m.group(2)))
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def enumerators(texts: dict[str, str], parser) -> dict[str, tuple[int, tuple[str, ...]]]:
    """Enumerator name → (value, the names of its enum in order) for every enum whose values are all explicit or
    implicit integers."""
    out: dict[str, tuple[int, tuple[str, ...]]] = {}
    conflicting: set[str] = set()
    for path, text in texts.items():
        raw = text.encode("utf-8")
        for n in _walk(parser.parse(raw).root_node):
            if n.type != "enumerator_list":
                continue
            names, values, nxt = [], [], 0
            ok = True
            for e in n.named_children:
                if e.type != "enumerator":
                    continue
                name = _text(e.child_by_field_name("name"), raw)
                v = e.child_by_field_name("value")
                if v is not None:
                    vt = _text(v, raw).strip().strip("()")
                    if not _LITERAL.fullmatch(vt):
                        ok = False
                        break
                    nxt = _int(vt)
                names.append(name)
                values.append(nxt)
                nxt += 1
            if ok and names:
                group = tuple(names)
                for name, value in zip(names, values, strict=True):
                    if name in out and out[name][0] != value:
                        conflicting.add(name)   # two enums give it two values: which applies is the build's (Info 4)
                    out.setdefault(name, (value, group))
    return {k: v for k, v in out.items() if k not in conflicting}


def injection_values(point: dict[str, Any], defines: dict[str, int], enums: dict[str, tuple[int, tuple[str, ...]]],
                     type_bounds) -> tuple[list[str], str]:
    """Two or more values to inject for a used return, and where they come from — or ``([], reason)``.

    ``checked`` against ``A``: ``A`` and a value on the other side of the check — another enumerator of ``A``'s enum,
    or the integer next to it (``==``/``!=``: ``A+1``; ``<``: ``A−1`` and ``A``; ``>``: ``A`` and ``A+1``) when ``A`` is
    a literal or an integer macro. A truth test: ``0`` and ``1``. ``assigned``/``returned``: the declared return type's
    minimum and maximum. Nothing else is invented."""
    use = point.get("return_use") or {}
    kind = use.get("use")
    if kind == "checked":
        op, against = use.get("operator"), str(use.get("against") or "").strip()
        if op in {"truth", "!", "&&", "||"}:
            return ["0", "1"], "truth_value"
        if op == "switch" or not against:
            return [], "switch_cases_not_modeled"
        if against in enums:
            value, group = enums[against]
            # (round 2 W-1) a sibling dropped as conflicting is not "another value" — it is not known at all
            other = next((g for g in group if g != against and g in enums and enums[g][0] != value), None)
            if other is None:
                return [], "enum_has_no_other_value"
            return [f"{against} ({value})", f"{other} ({enums[other][0]})"], "enum_sibling"
        if against in defines:
            base, label = defines[against], against
        elif _LITERAL.fullmatch(against):
            base, label = _int(against), ""
        else:
            return [], "compared_value_unresolved"
        # ``f() < A``: A−1 holds, A does not; ``f() > A`` / ``==`` / ``!=``: A and A+1 fall on different sides
        pair = [base - 1, base] if op in {"<", ">="} else [base, base + 1]
        bounds = type_bounds(point.get("return_type") or "")
        if bounds and not all(bounds[0] <= v <= bounds[1] for v in pair):
            return [], "neighbour_outside_return_type"   # ``U8 f() == 0xFFU`` has no 256 (review W3)
        return [f"{label} ({v})" if label and v == base else str(v) for v in pair], "compared_value_and_neighbour"
    if kind in {"assigned", "returned"}:
        bounds = type_bounds(point.get("return_type") or "")
        if not bounds:
            return [], "return_type_bounds_unknown"
        return [str(bounds[0]), str(bounds[1])], "return_type_bounds"
    return [], f"return_not_used:{kind}"


def file_scope_globals(texts: dict[str, str], parser) -> set[str]:
    """Names declared at file scope (not functions): the objects a module can share."""
    names = set()
    for path, text in texts.items():
        if not path.lower().endswith(".c"):
            continue
        raw = text.encode("utf-8")
        for n in parser.parse(raw).root_node.named_children:
            if n.type != "declaration":
                continue
            for d in n.children_by_field_name("declarator"):
                while d is not None and d.type not in {"identifier", "function_declarator"}:
                    d = d.child_by_field_name("declarator")
                if d is not None and d.type == "identifier":
                    names.add(_text(d, raw))
    return names


def attach_interface_contract(itcs: list[dict[str, Any]], texts: dict[str, str], parser, type_bounds,
                              unreadable: list[str] | None = None) -> dict[str, Any]:
    """Add each ITC's interface contract (``itc["interface_contract"]``) with, for every used cross-module return, the
    values an error-propagation test should drive it to (``suggestion``, not applied — review round 1 W1). The ITC's
    inputs and cases are **not** changed. Returns the counts for the quality report (unreadable files included — a
    function in them is missing from every contract, review W5)."""
    index = SourceIndex(texts, parser)
    globals_ = file_scope_globals(texts, parser)
    defines, enums = int_defines(texts), enumerators(texts, parser)
    # (round 3 I1) the headline counts exist even at 0 — a zero next to "—" reads as "not recorded"
    stats: Counter = Counter({"flows": 0, "cross_module_calls": 0, "used_returns": 0, "global_flows": 0,
                              "unresolved_calls": 0, "missing_functions": 0, "ambiguous_functions": 0})
    # (round 2 W-4) flows overlap: the per-flow sums count one call once per flow that holds it — keep the distinct too
    distinct: dict[str, set] = {"calls": set(), "used_returns": set(), "global_flows": set(), "unresolved": set()}
    for itc in itcs:
        chain = [p.strip().rstrip("()").strip() for p in re.split(r"->|→", str(itc.get("call_chain") or ""))
                 if p.strip()]
        contract = flow_contract(chain, index, globals_)
        itc["interface_contract"] = contract
        stats["flows"] += 1
        stats["cross_module_calls"] += len(contract["calls"])
        stats["global_flows"] += len(contract["global_flows"])
        stats["unresolved_calls"] += len(contract["unresolved_calls"])
        stats["missing_functions"] += len(contract["missing_functions"])
        stats["ambiguous_functions"] += len(contract["ambiguous_functions"])
        distinct["global_flows"].update((g["global"], g["producer"], g["consumer"]) for g in contract["global_flows"])
        distinct["unresolved"].update((u["caller"], u["line"], u["text"]) for u in contract["unresolved_calls"])
        for point in contract["calls"]:
            key = (point["caller"], point["callee"], point["line"])
            distinct["calls"].add(key)
            use = (point.get("return_use") or {}).get("use")
            if use not in {"checked", "assigned", "returned"}:
                continue
            distinct["used_returns"].add(key)
            stats["used_returns"] += 1
            values, basis = injection_values(point, defines, enums, type_bounds)
            if len(values) < 2:
                point["suggestion"] = {"skipped": basis}
                stats["suggestion_skipped:" + basis] += 1
                continue
            point["suggestion"] = {"column": f"{point['callee']}() return", "values": values, "basis": basis}
            stats["suggestion_basis:" + basis] += 1
    stats["duplicate_function_names"] = len(index.duplicates)
    stats["keyword_named_definitions"] = index.keyword_definitions
    stats["unreadable_source_files"] = len(unreadable or [])
    stats["distinct_cross_module_calls"] = len(distinct["calls"])
    stats["distinct_used_returns"] = len(distinct["used_returns"])
    stats["distinct_global_flows"] = len(distinct["global_flows"])
    stats["distinct_unresolved_calls"] = len(distinct["unresolved"])
    return {k: v for k, v in sorted(stats.items())}


INTERFACE_EVIDENCE_HEADERS = ["Test Case ID", "Kind", "Caller", "Caller Module", "Callee / Global", "Callee Module",
                              "Line", "Return Use", "Suggested Stimulus (not applied)", "Suggested Values",
                              "Value Basis / Skip Reason", "Bindings (param ← arg)", "Same-Type Argument Pairs"]


def write_interface_evidence_sheet(wb, itcs: list[dict[str, Any]]) -> int:
    """'Interface Evidence' sheet — every interface point of every ITC, with its suggestion (not applied) or why
    there is none."""
    rows = []
    for itc in itcs:
        contract = itc.get("interface_contract") or {}
        for p in contract.get("calls") or []:
            use = p.get("return_use") or {}
            inj = p.get("suggestion") or {}
            use_text = "—" if not use else use.get("use", "") + (
                f" {use.get('operator', '')} {use.get('against', '')}".rstrip() if use.get("operator") else "")
            rows.append([itc.get("tc_id", ""), "call", p["caller"], p["caller_module"], p["callee"], p["callee_module"],
                         p["line"], use_text if returns_value(p.get("return_type")) else "void",
                         inj.get("column", "—"), ", ".join(inj.get("values") or []) or "—",
                         inj.get("basis") or inj.get("skipped") or "—",
                         "; ".join(f"{b['param']} ← {b['arg']}" for b in p.get("bindings") or []) or "—",
                         "; ".join("/".join(x) for x in p.get("swappable_pairs") or []) or "—"])
        for g in contract.get("global_flows") or []:
            rows.append([itc.get("tc_id", ""), "global", g["producer"], g["producer_module"], g["global"],
                         g["consumer_module"], "—", "—", "—", "—", f"read by {g['consumer']}", "—", "—"])
    if not rows:
        return 0
    ws = wb.create_sheet("Interface Evidence")
    ws.append(INTERFACE_EVIDENCE_HEADERS)
    for r in rows:
        ws.append(r)
    return len(rows)
