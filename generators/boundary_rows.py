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
