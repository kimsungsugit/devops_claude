"""Behavioural boundary rows for the extended SUTS profile (R15 — gap 1 of the HDPDM01 comparison).

R4 showed the generated vectors reach the right outputs but rarely sit where a comparison flips: of the mutants only the
reference killed, 491/572 were outputs the generated suite *did* record, with vectors on the same side of every
threshold. R4b moved MC/DC pairs onto the boundary and lost more than it gained (the wide pairs also killed other
mutants), so this module **adds** rows and moves nothing.

For a base row B and one input x, the source oracle runs B with x at sample points. An integer range is sampled at its
ends, B's own value and every integer constant the function body names (literal or resolved macro/enumerator) with its
neighbours; a closed value set (an enum's enumerators) is sampled whole. Where two neighbouring samples give different
*derived* outputs, a bisection per changed output narrows a range gap to adjacent values ``lo, lo + 1`` (in a value set
the two neighbouring enumerators already are adjacent — no value between them is ever used). Both vectors become rows
when the change there is a **step** — not the local slope (``g_o = g_a * 2`` changes at every input and has no
boundary; the samples either side decide) and not an alternation (``g_a & 1``). Segments between a constant and its
neighbour go first. A boundary found once (same input, same ``lo``) is not searched again from another base.

The rows are ordinary sequences: their expected values come from the same oracle afterwards
(`generators.test_evidence.apply_sequence_evidence`) — nothing here asserts a value. No mutant is consulted, so the
R4 mutation harness measures these rows as it measures every other row. The search is the oracle's model of the code,
not a target run; a boundary it cannot see (an output it cannot derive) is not searched. Every budget cut is counted in
the report (bases, constants, value sets, evaluations, boundaries).
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

from generators import c_project_context as cpc
from generators.c_source_oracle import Unsupported, _parsed_function, evaluate_outputs, scope_matches

BOUNDARY_PREFIX = "BND_"
# Budgets per function — a search that runs out says so in its report; nothing is cut silently.
MAX_EVALUATIONS = 1000
MAX_BASES = 6
MAX_CONSTANTS = 48
MAX_VALUE_SET = 64
MAX_BOUNDARIES = 32

_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
# (review C1) string and character literals hold digits that are not constants (``"08:05"``, ``'\012'``)
_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_FLOAT = re.compile(r"(?<![\w.])(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fFlL]?")
_INT = re.compile(r"(?<![\w.])(0[xX][0-9A-Fa-f]+|0[0-7]*|[1-9]\d*)[uUlL]*(?![\w.])")
_IDENT = re.compile(r"\b[A-Za-z_]\w*\b")
# a unary minus before a literal (``x == -5``, ``(-5)``, ``return -1``) — not a subtraction (``a - 5``)
# (review round 3 W2) also ``case -5:``, ``{-40, -30}`` and ``-K_LIM`` (a named constant, negated)
_NEG_CONTEXT = r"(?:[=(,?:<>!&|+*/%~\[{]|\breturn|\bcase)\s*-\s*"
_NEGATIVE = re.compile(_NEG_CONTEXT + r"(0[xX][0-9A-Fa-f]+|0[0-7]*|[1-9]\d*)[uUlL]*(?![\w.])")
_NEGATIVE_NAME = re.compile(_NEG_CONTEXT + r"([A-Za-z_]\w*)\b(?!\s*\()")


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 0) if re.fullmatch(r"-?(?:0[xX][0-9A-Fa-f]+|0|[1-9]\d*)", text) else None
        except ValueError:
            return None
    return None


def _c_int(literal: str) -> int:
    """A C integer literal's value — ``0x1F``, octal ``010`` (= 8), decimal."""
    if literal[:2] in ("0x", "0X"):
        return int(literal, 16)
    return int(literal, 8) if literal.startswith("0") and len(literal) > 1 else int(literal)


def body_constants(unit: dict[str, Any]) -> tuple[list[int], int]:
    """``(constants, total)``: every integer constant the function body names — literals (a written negative with its
    sign) and identifiers the project scope resolves to an integer. The ``MAX_CONSTANTS`` cap is applied per input,
    after dropping what that input's domain cannot hold (review round 3 I3: negatives no longer crowd out an unsigned
    input's thresholds)."""
    scope = unit.get("project_scope")
    raw = str(unit.get("source_text") or "").encode()
    try:
        _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, str(unit.get("name") or ""), scope)
        body = fn.child_by_field_name("body")
        text = raw[body.start_byte:body.end_byte].decode("utf-8", errors="replace")
    except (Unsupported, cpc.Unresolved, AttributeError):  # no body, no constants: the domain ends are still sampled
        return [], 0
    text = _FLOAT.sub(" ", _STRING.sub(" ", _COMMENT.sub(" ", text)))
    values = {_c_int(m.group(1)) for m in _INT.finditer(text)}
    # (review round 2 I1) a written negative literal is sampled with its sign — only where the body writes one: negating
    #   every constant doubled the samples of each signed input and spent the budget before the reaching bases
    values |= {-_c_int(m.group(1)) for m in _NEGATIVE.finditer(text)}
    # ⚠ not ``… or {}``: the lazy map is an empty dict until asked, and ``or`` would swap it for a plain one
    constants = (scope or {}).get("constants")
    if constants is None:
        constants = {}
    negated = set(_NEGATIVE_NAME.findall(text))
    for name in dict.fromkeys(_IDENT.findall(text)):
        try:
            entry = constants.get(name)   # the lazy map answers None for a name it cannot resolve
        except (ValueError, ArithmeticError, RecursionError, TypeError, KeyError):
            # (review C1) a macro the resolver chokes on (``1e400`` overflows) is simply not a sample point
            continue
        if isinstance(entry, dict) and isinstance(entry.get("value"), int) and not isinstance(entry["value"], bool):
            values.add(entry["value"])
            if name in negated:
                values.add(-entry["value"])
    ordered = sorted(values)
    return ordered, len(ordered)


_COMPARISON_OPS = frozenset({"<", "<=", ">", ">=", "==", "!="})
_PREPROC_CONDITIONAL = frozenset({"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"})


def _bare(node):
    """``(x)`` / ``(U16)x`` / ``((U16)(x))`` → the operand itself."""
    while node is not None and node.type in ("parenthesized_expression", "cast_expression"):
        if node.type == "cast_expression":
            node = node.child_by_field_name("value")
        else:
            inner = [c for c in node.named_children if c.type != "comment"]
            node = inner[-1] if inner else None
    return node


def _declared_locals(body, raw: bytes) -> set[str]:
    """Names a function body declares (any arm, any depth) — ``U8 x = 0, *p, a[3];`` → {x, p, a}; ``void (*f)(void)``
    → {f}. A block-scope ``extern`` names the global itself, so it is no local."""
    names: set[str] = set()
    stack = [body] if body is not None else []
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.type != "declaration" or any(
                c.type == "storage_class_specifier" and raw[c.start_byte:c.end_byte].strip() == b"extern"
                for c in node.children):
            continue
        for d in node.children_by_field_name("declarator"):
            while d is not None and d.type != "identifier":
                d = d.child_by_field_name("declarator") or next(
                    (c for c in d.named_children if c.type == "identifier" or c.type.endswith("declarator")), None)
            if d is not None:
                names.add(raw[d.start_byte:d.end_byte].decode("utf-8", errors="replace"))
    return names


def _macro_argument_kind(scope: dict[str, Any], name: str, index: int, count: int) -> str:
    """What becomes of argument ``index`` of an invocation of macro ``name`` (``count`` arguments): "direct" — the one
    known body uses that parameter as an expression and invokes no macro (``SEL(c, a, b) ((c) ? (a) : (b))``); "dropped"
    — the body never uses it (``DBG_CHECK(c)`` with an empty body: no comparison in this build, like a dead ``#if``
    arm); "unknown" — anything else (several or conditional bodies, ``#undef``, an object-like alias, ``#``/``##``,
    ``__VA_ARGS__``, a macro inside the body). The oracle's view of the macro: which names are macros and which body is
    active (``macro_status`` "active" · ``macro_bodies`` · ``pp_bodies`` — a definition under a decided ``#if`` too)."""
    definition = (scope.get("pp_bodies") or {}).get(name) or {}
    body = (scope.get("macro_bodies") or {}).get(name)
    params = definition.get("params") if definition.get("function_like") else None
    status = scope.get("macro_status") or {}
    if status.get(name) != "active" or body is None or not isinstance(params, list) or len(params) != count \
            or not 0 <= index < count or "..." in params:
        return "unknown"
    # the stored body is comment-free already (`cpc.strip_comments`, literal-aware) — only string literals go here
    tokens = set(_IDENT.findall(_STRING.sub(" ", body)))
    if params[index] not in tokens:
        # (review round 5 W-2) an argument reaches the expansion only through its parameter (C11 6.10.3.1): a body
        #   without it drops the argument whatever other macros the body uses
        return "dropped"
    if "#" in body or any(t in status for t in tokens):
        return "unknown"
    return "direct"


def compared_constants(unit: dict[str, Any], names: list[str], stats: dict | None = None) -> dict[str, set[int]]:
    """(R31) For each name: the integer constants the function body compares it with **directly** (``x < K``,
    ``K >= x``, ``(U16)x == K``, ``(U16)(x) != K``) — a literal (``0xFFFF``, ``-5``, ``(-300)``) or an identifier the
    project scope resolves to an integer (``u16g_MAX``), valued as C values it: the oracle's own typed literal and unary
    arithmetic (`cpc.literal` / `cpc.arith` — ``-1U`` is the type's maximum, not -1; review round 3 I-4). Only the arms
    of ``#if``/``#ifdef``/``#elif`` this build compiles (the oracle's verdict, `cpc.pp_condition`) — a directive it cannot
    decide is not read, with every arm after it, and is counted in ``stats["undecided_preprocessor_blocks"]`` (R31 review
    W2: a comparison in a dead ``#if`` arm was written as "the source compares"). A cast on the constant's side keeps the
    constant only when the value fits the cast type (``(S8)200`` is -56 in C — review round 2 W3); a cast type the scope
    cannot size drops it. A comparison inside a macro invocation's argument may not exist in this build (``DBG_CHECK(x <
    200)`` may expand to nothing — review round 3 W-1). With the macro's one known body the argument is read as written
    or dropped (`_macro_argument_kind`, review round 4 W-1(b): a liveness probe alone was fooled by ``g_a / 10`` stepping
    at 200); otherwise such a constant, when no direct comparison gives it too, is returned in
    ``stats["macro_argument_constants"]`` ({name: set}) instead — the caller uses it only on a base where the original
    code turns at those points. A callee is a macro whenever the oracle says so (``macro_status`` — also names under an
    undecided ``#if``, ``#undef``-ed ones and object-like aliases; review round 4 W-1(a)). A name the body declares as a local is not the input there —
    it is skipped and counted in ``stats["inputs_shadowed"]``. Not a constant another expression reaches (``x + 1 < K``,
    ``a[x] == K``). Known limits (they miss, never invent): character literals, constant expressions (``K - 1``), ``~K``,
    a target whose ``int`` width is unknown (the literal has no C type), ``x == -1`` for an unsigned type as wide as
    ``int`` (C compares it with the type's maximum — the constant is then outside the declared type and counted there by
    the caller). A cast on the **input's** side is stripped (``(U8)x == 200`` is read as ``x`` against 200 — the rows sit
    where that comparison turns for the untruncated values). Empty, and ``stats["body_unread"] = 1``, when the body cannot
    be read."""
    from generators.c_source_oracle import cast_call_operand
    from generators.mcdc_design import _scope_type
    stats = stats if stats is not None else {}
    scope = unit.get("project_scope")
    raw = str(unit.get("source_text") or "").encode()
    out: dict[str, set[int]] = {}
    in_macro: dict[str, set[int]] = {}
    try:
        _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, str(unit.get("name") or ""), scope)
        body = fn.child_by_field_name("body")
    except (Unsupported, cpc.Unresolved, AttributeError):
        stats["body_unread"] = 1
        return out
    shadowed = set(names) & _declared_locals(body, raw)
    if shadowed:
        stats["inputs_shadowed"] = len(shadowed)
    wanted = set(names) - shadowed
    constants = (scope or {}).get("constants")
    if constants is None:
        constants = {}
    widths = ((scope or {}).get("target") or {}).get("widths") or {}
    macros = set((scope or {}).get("macro_status") or ()) | set((scope or {}).get("function_like_macros") or ())

    def text(node) -> str:
        return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def bare(node):
        """`_bare`, and ``(U16)(x)`` — the oracle's one cast judgement (`c_source_oracle.cast_call_operand`, R26)."""
        while True:
            node = _bare(node)
            operand = cast_call_operand(node, raw, scope)
            if operand is None:
                return node
            node = operand

    def peel(node) -> tuple[Any, list[str]]:
        """``((S8)(200))`` → (the literal, ["S8"]) — the cast types, outermost first."""
        casts: list[str] = []
        while node is not None:
            if node.type == "parenthesized_expression":
                inner = [c for c in node.named_children if c.type != "comment"]
                node = inner[-1] if inner else None
            elif node.type == "cast_expression":
                t = node.child_by_field_name("type")
                casts.append(text(t) if t is not None else "")
                node = node.child_by_field_name("value")
            else:
                operand = cast_call_operand(node, raw, scope)
                if operand is None:
                    break
                callee = [c for c in node.child_by_field_name("function").named_children if c.type != "comment"]
                casts.append(text(callee[0]))
                node = operand
        return node, casts

    def cast_type(cast: str) -> dict | None:
        try:
            t = _scope_type(scope, cast)
        except (cpc.Unresolved, KeyError, TypeError):
            return None
        if not isinstance(t, dict) or not isinstance(t.get("bits"), int) or t.get("kind") in ("float", "double"):
            return None
        return t

    def typed(node) -> tuple[int, dict] | None:
        node, casts = peel(node)
        got = atom(node)
        for cast in reversed(casts):
            t = cast_type(cast)
            if got is None or t is None:
                return None
            lo, hi = cpc.type_range(t)
            if not lo <= got[0] <= hi:
                return None             # a converting cast: C compares with another value — miss rather than invent
            got = (got[0], t)
        return got

    def atom(node) -> tuple[int, dict] | None:
        try:
            if node is None:
                return None
            if node.type == "number_literal":
                v, t = cpc.literal(text(node), widths)
                return (v, t) if isinstance(v, int) and not cpc.is_float(t) else None
            if node.type == "unary_expression":
                op = node.child_by_field_name("operator")
                arg = node.child_by_field_name("argument")
                inner = typed(arg) if arg is not None and op is not None and text(op) in ("-", "+") else None
                return cpc.arith(text(op), None, inner, widths) if inner is not None else None
            if node.type == "identifier":
                entry = constants.get(text(node))
                if isinstance(entry, dict) and isinstance(entry.get("value"), int) and not isinstance(entry["value"], bool) \
                        and isinstance(entry.get("type"), dict):
                    return entry["value"], entry["type"]
        except (cpc.Unresolved, ValueError, ArithmeticError, RecursionError, TypeError, KeyError):
            return None
        return None

    stack = [(body, False)] if body is not None else []
    while stack:
        node, inside_macro = stack.pop()
        if node.type in _PREPROC_CONDITIONAL:
            verdict = cpc.pp_condition(scope, node, raw, set())
            cond, name, alt = (node.child_by_field_name("condition"), node.child_by_field_name("name"),
                               node.child_by_field_name("alternative"))
            if verdict is None:
                stats["undecided_preprocessor_blocks"] = stats.get("undecided_preprocessor_blocks", 0) + 1
                continue
            if verdict:
                stack.extend((c, inside_macro) for c in node.named_children if c not in (cond, name, alt))
            elif alt is not None:
                stack.append((alt, inside_macro))
            continue
        callee = node.child_by_field_name("function") if node.type == "call_expression" else None
        if callee is not None and callee.type == "identifier" and text(callee) in macros:
            args_node = node.child_by_field_name("arguments")
            args = [c for c in args_node.named_children if c.type != "comment"] if args_node is not None else []
            for i, arg in enumerate(args):
                kind = _macro_argument_kind(scope or {}, text(callee), i, len(args))
                if kind != "dropped":
                    stack.append((arg, inside_macro or kind == "unknown"))
            continue
        stack.extend((c, inside_macro) for c in node.named_children)
        if node.type != "binary_expression":
            continue
        op = node.child_by_field_name("operator")
        if op is None or text(op) not in _COMPARISON_OPS:
            continue
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        for this, other in ((left, right), (right, left)):
            this = bare(this)               # the input's side sheds its casts; the constant's side keeps them for typed()
            if this is not None and this.type == "identifier" and text(this) in wanted:
                got = typed(other)
                if got is not None:
                    (in_macro if inside_macro else out).setdefault(text(this), set()).add(got[0])
    only_in_macro = {n: ks - out.get(n, set()) for n, ks in in_macro.items() if ks - out.get(n, set())}
    if only_in_macro:
        stats["macro_argument_constants"] = only_in_macro
    return out


def comparison_is_live(unit: dict[str, Any], base: dict[str, int], var: str, points: list[int],
                       outputs: list[str]) -> bool:
    """(R31) Does ``base`` reach the code's comparison of ``var`` with a constant among ``points`` (ascending, at least
    three)? — some integer output the oracle derives at every point is **not affine** over them: ``x + 1`` below a
    saturation guard and flat at it, a step at ``x > K``, a spike at ``x == K``. An output unchanged, or changing at one
    rate over all points, says this base never meets the comparison there (the guarded branch is not taken). Only the
    original code is evaluated — no mutant is consulted. A limit: an output non-linear in ``var`` for another reason
    (``var & 1``, ``var / 10``) also answers yes. The answer picks a base row; only for a comparison inside an argument
    of a macro whose body is not known does it also decide whether the constant is used (`compared_constants`)."""
    results = evaluate_outputs(unit, [{**base, var: p} for p in points], [outputs] * len(points))
    sigs = [_signature(r, outputs) for r in results]
    for k in range(len(outputs)):
        vals = [s[k] for s in sigs]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
            continue
        slopes = {Fraction(vals[i + 1] - vals[i], points[i + 1] - points[i]) for i in range(len(vals) - 1)}
        if len(slopes) > 1:
            return True
    return False


def derives_any(unit: dict[str, Any], inputs: dict[str, int], outputs: list[str]) -> bool:
    """(R31 review round 2 W1) Does the oracle derive at least one of ``outputs`` at ``inputs``? A row whose every
    expectation stays "[검증 필요]" asserts nothing the oracle stands behind."""
    if not outputs:
        return False
    return any(v is not None for v in _signature(evaluate_outputs(unit, [inputs], [outputs])[0], outputs))


def _signature(result: dict[str, Any], outputs: list[str]) -> tuple:
    slots = result.get("outputs") or {}
    return tuple((slots.get(o) or {}).get("value") for o in outputs)


def _differs(a: tuple, b: tuple) -> list[int]:
    """Output positions derived on both sides with different values — only such a change is a boundary."""
    return [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x is not None and y is not None and x != y]


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _slope(points: list[int], sigs: list[tuple], i: int, k: int) -> Fraction | None:
    a, b = sigs[i][k], sigs[i + 1][k]
    if not (isinstance(a, int) and isinstance(b, int)) or isinstance(a, bool) or isinstance(b, bool):
        return None
    return Fraction(b - a, points[i + 1] - points[i])


def _inside_slope(points: list[int], sigs: list[tuple], i: int, k: int) -> bool:
    """Segment ``i`` of output ``k`` lies inside a linear stretch: its slope equals that of every neighbouring segment
    (at least one). A step has a different slope from its flat neighbours; ``g_o = g_a * 2`` has one slope throughout."""
    own = _slope(points, sigs, i, k)
    if own is None:
        return False
    near = [_slope(points, sigs, j, k) for j in (i - 1, i + 1) if 0 <= j < len(points) - 1]
    near = [n for n in near if n is not None]
    return bool(near) and all(n == own for n in near)


class _Axis:
    """Where one input may move: an integer range ``(lo, hi)`` or a closed value set (sorted enumerators)."""

    def __init__(self, domain: Any):
        if isinstance(domain, (list, frozenset, set)):
            self.values = sorted(domain)
            self.lo, self.hi = self.values[0], self.values[-1]
        else:
            self.values = None
            self.lo, self.hi = domain

    def contains(self, v: int) -> bool:
        return v in self.values if self.values is not None else self.lo <= v <= self.hi

    def adjacent(self, p: int, q: int) -> bool:
        return self.values is not None or q - p == 1

    def before(self, v: int) -> int | None:
        if self.values is not None:
            i = self.values.index(v)
            return self.values[i - 1] if i > 0 else None
        return v - 1 if v - 1 >= self.lo else None

    def after(self, v: int) -> int | None:
        if self.values is not None:
            i = self.values.index(v)
            return self.values[i + 1] if i + 1 < len(self.values) else None
        return v + 1 if v + 1 <= self.hi else None

    def middle(self) -> int:
        return self.values[len(self.values) // 2] if self.values is not None else (self.lo + self.hi) // 2


def _fill_values(axes: dict[str, "_Axis"], defaults: dict[str, int] | None) -> dict[str, int]:
    """A value for each input a row leaves blank: the caller's mid value, moved by the input's position in a range wide
    enough (two inputs a branch switches between must differ), an enumerator for a value set."""
    fill: dict[str, int] = {}
    wide = [k for k, a in axes.items() if a.values is None]
    for k, v in (defaults or {}).items():
        axis = axes.get(k)
        if axis is None:
            continue
        if axis.values is not None:
            fill[k] = v if axis.contains(v) else axis.middle()   # an enum is filled with an enumerator
        elif axis.contains(v):
            n = wide.index(k)
            fill[k] = min(v + n, axis.hi) if axis.hi - axis.lo > 2 * len(axes) else v
    return fill


def blank_fill(domains: dict[str, Any], defaults: dict[str, int] | None) -> dict[str, int]:
    """(R19) The fill `find_boundaries` gives a base row's blank inputs, for callers that fill a row themselves (the
    extended SUTS fills MC/DC vectors). Same domains, same rule — one definition."""
    axes = {var: _Axis(dom) for var, dom in domains.items()
            if dom and not (isinstance(dom, (list, frozenset, set)) and len(dom) > MAX_VALUE_SET)}
    return _fill_values(axes, defaults)


def find_boundaries(unit: dict[str, Any], bases: list[dict[str, Any]], domains: dict[str, Any],
                    outputs: list[str], existing: list[dict[str, Any]] | None = None,
                    defaults: dict[str, int] | None = None) -> dict[str, Any]:
    """``{"rows": [{"inputs", "variable", "side", "lo", "hi", "base", "outputs_changed", "filled"}], "report": {...}}``.

    ``bases``: input vectors (``{"inputs": {var: value}, "strategy": name}``) in priority order. A base with a value
    outside its input's domain (a ``BV_*_INV`` row) is not a base — a row built on it would carry the invalid value.
    With more than ``MAX_BASES`` candidates the leading ones are run once and ranked: a distinct output state first,
    more derived outputs first; the priority order only breaks ties.
    ``domains``: inputs that may move — a ``(min, max)`` tuple for an integer range, a ``list``/``set``/``frozenset``
    for a closed value set (an enum's enumerators; only those values are ever used, never bisected, and no slope or
    alternation filter applies to them). Nothing else is a domain.
    ``existing``: input vectors already in the suite — a boundary side equal to one of them is not added again.
    ``defaults``: a value for each domain input a base leaves blank (an MC/DC vector sets only what its decision
    reads — with the rest unset, most outputs are underived and no boundary can show). The caller's mid value; in a
    range wide enough each blank input is moved by its position so two inputs a branch switches between differ
    (``gain = T < 11 ? G_M30 : G_M10`` shows no step when both hold the same value). Rows name what was filled.
    """
    report = {"status": "searched", "evaluations": 0, "bases": 0, "bases_available": 0, "boundaries": 0, "rows": 0,
              "budget_exhausted": False, "evaluation_budget_exhausted": False, "boundary_cap_reached": False,
              "constants": 0, "constants_total": 0, "value_sets_capped": 0, "linear_segments_skipped": 0,
              "slope_steps_rejected": 0, "bisect_underived": 0}
    if not unit.get("source_text") or not scope_matches(unit):
        return {"rows": [], "report": {**report, "status": "no_project_scope"}}
    if not outputs or not domains:
        return {"rows": [], "report": {**report, "status": "no_outputs" if not outputs else "no_integer_inputs"}}
    axes: dict[str, _Axis] = {}
    for var, dom in domains.items():
        if isinstance(dom, (list, frozenset, set)) and len(dom) > MAX_VALUE_SET:
            report["value_sets_capped"] += 1   # sampled whole or not at all: a larger set is not moved
            continue
        if dom:
            axes[var] = _Axis(dom)
    constants, report["constants_total"] = body_constants(unit)
    report["constants"] = len(constants)
    report["constants_capped_inputs"] = 0
    seen_vectors = {tuple(sorted((k, _as_int(v)) for k, v in (e or {}).items())) for e in (existing or [])}
    found: set[tuple[str, int]] = set()
    rows: list[dict[str, Any]] = []
    budget = [MAX_EVALUATIONS]
    memo: dict[tuple, tuple] = {}   # the oracle is deterministic per vector: bisection and the step check revisit points

    def run(vectors: list[dict[str, int]]) -> list[tuple]:
        keys = [tuple(sorted(v.items())) for v in vectors]
        todo = list({k: v for v, k in zip(vectors, keys, strict=True) if k not in memo}.items())
        if budget[0] < len(todo):
            report["budget_exhausted"] = report["evaluation_budget_exhausted"] = True
            raise _Stop
        if todo:
            budget[0] -= len(todo)
            report["evaluations"] += len(todo)
            results = evaluate_outputs(unit, [v for _k, v in todo], [outputs] * len(todo))
            for (k, _v), r in zip(todo, results, strict=True):
                memo[k] = _signature(r, outputs)
                if r.get("status") == "unsupported":
                    report.setdefault("oracle_unsupported_reason", str(r.get("reason") or "")[:80])
        return [memo[k] for k in keys]

    fill = _fill_values(axes, defaults)
    usable: list[tuple[dict[str, int], str, list[str]]] = []
    for base in bases:
        values = {k: _as_int(v) for k, v in (base.get("inputs") or {}).items()}
        if any(v is None for v in values.values()) or any(k in axes and not axes[k].contains(v)
                                                           for k, v in values.items()):
            continue
        filled = [k for k in fill if k not in values]
        values = {**{k: fill[k] for k in filled}, **values}
        if not any(k in axes for k in values) or values in [u[0] for u in usable]:
            continue
        usable.append((values, str(base.get("strategy") or ""), filled))
    report["bases_available"] = len(usable)
    if len(usable) > MAX_BASES:
        # A base that reaches no derived output hides every boundary behind it (``DeviceType`` at its mid value is no
        #   device the function knows). Run the leading candidates once and prefer bases reaching a **different** output
        #   state, most derived outputs first; bases repeating a state already chosen go last (review round 3 W1: a guard
        #   that returns early with every output set to a safe value derives the most, and six copies of that state
        #   pushed out the one base that reaches the logic). The priority order breaks ties.
        head = usable[:min(MAX_BASES * 3, budget[0])]   # (review round 3 I1) ranking never spends the whole budget
        sigs = run([u[0] for u in head])
        by_count = sorted(range(len(head)), key=lambda i: -sum(v is not None for v in sigs[i]))
        seen_states: set[tuple] = set()
        first, repeats = [], []
        for i in by_count:
            (repeats if sigs[i] in seen_states else first).append(i)
            seen_states.add(sigs[i])
        usable = [head[i] for i in first + repeats] + usable[len(head):]
    usable = usable[:MAX_BASES]
    report["bases"] = len(usable)
    if not usable:
        return {"rows": [], "report": {**report, "status": "no_usable_base"}}

    def one(vector: dict[str, int]) -> tuple:
        return run([vector])[0]

    def bisect(values, var, p, q, sp, sq, k):
        """Adjacent ``(lo, hi, s_lo, s_hi)`` where output ``k`` changes — ``None`` when the middle leaves it underived."""
        while q - p > 1:
            m = (p + q) // 2
            sm = one({**values, var: m})
            if sm[k] is None:
                report["bisect_underived"] += 1
                return None
            if sm[k] != sp[k]:
                q, sq = m, sm
            else:
                p, sp = m, sm
        return p, q, sp, sq

    def is_step(values, var, lo, hi, s_lo, s_hi, k):
        """The change of output ``k`` from ``lo`` to ``hi`` of a **range** is neither the local slope (``g_o = g_a * 2``
        changes at every input) nor an alternation (``g_a & 1`` flips back at the next input and again after it). A side
        outside the domain or underived tells nothing. A value set is never asked (review round 2 W1): its enumerators'
        numbering is not a scale, so a "slope" there would depend on how the enum was numbered, not on the code."""
        a, b = s_lo[k], s_hi[k]
        if not (_number(a) and _number(b)):
            return True
        step, sides = b - a, []

        def at(x):
            got = one({**values, var: x})[k]
            return got if _number(got) else None

        left_v = at(lo - 1) if lo - 1 >= axes[var].lo else None
        right_v = at(hi + 1) if hi + 1 <= axes[var].hi else None
        if left_v is not None:
            sides.append(a - left_v)
        if right_v is not None:
            sides.append(right_v - b)
        if not sides:
            return True
        if all(s == step for s in sides):
            return False                     # a slope
        if not all(s == -step for s in sides):
            return True
        if len(sides) == 2:
            return False                     # steps back on both sides: an alternation
        # (review round 2 W2) one visible side steps straight back: ``x == 1`` next to the domain edge does that too —
        #   look one further out on that side. An alternation flips again; a spike stays flat.
        x2 = (hi + 2) if right_v is not None else (lo - 2)
        if not axes[var].lo <= x2 <= axes[var].hi:
            return True
        far = at(x2)
        if far is None:
            return True
        again = (far - right_v) if right_v is not None else (left_v - far)
        return again != step

    try:
        for values, strategy, filled in usable:
            for var in [k for k in values if k in axes]:
                axis = axes[var]
                if axis.values is not None:
                    points = list(axis.values)
                else:
                    near = [c for c in constants if axis.lo - 1 <= c <= axis.hi + 1]
                    if len(near) > MAX_CONSTANTS:
                        report["constants_capped_inputs"] += 1
                        near = near[:MAX_CONSTANTS]
                    points = sorted({p for c in near for p in (c - 1, c, c + 1) if axis.contains(p)}
                                    | {axis.lo, axis.hi, values[var]})
                sigs = run([{**values, var: p} for p in points])
                # adjacent samples first: a named constant sits there (``x > K`` flips between K and K + 1)
                segments = sorted((i for i in range(len(points) - 1) if _differs(sigs[i], sigs[i + 1])),
                                  key=lambda i: not axis.adjacent(points[i], points[i + 1]))
                for i in segments:
                    p, q, sp, sq = points[i], points[i + 1], sigs[i], sigs[i + 1]
                    changed_here = _differs(sp, sq)
                    pending = [k for k in changed_here
                               if axis.values is not None or not _inside_slope(points, sigs, i, k)]
                    report["linear_segments_skipped"] += len(changed_here) - len(pending)
                    while pending:
                        k = pending.pop(0)
                        hit = (p, q, sp, sq) if axis.adjacent(p, q) else bisect(values, var, p, q, sp, sq, k)
                        if hit is None:
                            continue
                        lo, hi, s_lo, s_hi = hit
                        changed = _differs(s_lo, s_hi)
                        if k not in changed or (var, lo) in found:
                            continue
                        if axis.values is None and not is_step(values, var, lo, hi, s_lo, s_hi, k):
                            report["slope_steps_rejected"] += 1
                            continue
                        found.add((var, lo))
                        pending = [j for j in pending if j not in changed]
                        for side, value in (("lo", lo), ("hi", hi)):
                            vector = {**values, var: value}
                            key = tuple(sorted(vector.items()))
                            if key in seen_vectors:
                                continue
                            seen_vectors.add(key)
                            rows.append({"inputs": vector, "variable": var, "side": side, "lo": lo, "hi": hi,
                                         "base": strategy, "outputs_changed": [outputs[j] for j in changed],
                                         "filled": {f: vector[f] for f in filled if f != var}})
                        report["boundaries"] += 1
                        if report["boundaries"] >= MAX_BOUNDARIES:
                            report["budget_exhausted"] = report["boundary_cap_reached"] = True
                            raise _Stop
    except _Stop:
        pass
    if not memo and report["evaluation_budget_exhausted"]:
        report["status"] = "budget_exhausted_before_search"   # (review round 3 I1) nothing was asked, nothing is known
    elif not memo or all(all(v is None for v in sig) for sig in memo.values()):
        # (review W2) the oracle derived no output at all: not "searched" — say why
        report["status"] = "oracle_underived" + (f":{report['oracle_unsupported_reason']}"
                                                 if report.get("oracle_unsupported_reason") else "")
    return {"rows": rows, "report": {**report, "rows": len(rows)}}


class _Stop(Exception):
    """A search budget is spent (the report says which) — what was found so far stands."""
