"""Operating-scenario rows for the extended SUTS profile (R78).

Why (HDPDM01 extended SUTS vs the reference, R72 measurement): of the mutants only the reference killed, 200 were ones
the generated vectors did not tell apart. The generated rows set inputs to 0, the type's middle (127 · 32767) or its
ends and move one input at a time from such a base; the reference writer first fixes a vector on which the function
actually runs — the states and flags of a path set together, distinct non-zero values, a timer just below its limit —
and varies from there. Without such a vector a statement no row reaches (66 of the 200), a row that reaches it with an
extreme value the arithmetic overflows on (44 undetermined · 32 reach unknown), or a row on which a zero hides the
change (54).

Per function this module searches, on the source oracle's modeled run, for vectors that reach each statement and
each branch outcome of the body **cleanly** — one path (no branch on an unknown value), no undefined behaviour — with
values the code names. Each input starts at an *operating value*: a non-zero constant it is compared with (``x > K``,
``K == x``, ``a[K] == C``) or a switch label it selects, the middle of its design range, an enumerator, else a distinct
non-zero value. The search moves an input only among its candidates — the constants it is compared with and their
neighbours (so ``-1`` beside ``x >= 0``), switch labels, design-range ends, the body's other constants, small values,
and the type's ends last — and only the inputs of the first condition on the way that does not yet take the needed
outcome (through the locals that condition reads; every input when the run itself is the obstacle). A climb keeps the
vector that satisfies more of the target's control chain, then more of that condition's sub-conditions
(`mcdc_design._distance`), then the cleaner run with more derived outputs and fewer values outside the home range or at
the type's ends; it stops at a local best (counted, never a proof). No mutant is consulted: the rows are ordinary
sequences whose expected values the same oracle derives afterwards (`test_evidence.apply_sequence_evidence`); the SUTS
boundary (R15) and robustness (R31) searches take them as **added** bases after their own.

(R79) Reaching a statement is not yet seeing a fault in it. Of the 22 mutants only the reference still killed after
R78 (HDPDM01), 18 sat where a generated row ran — on values where the fault changes nothing: a comparison never
evaluated with its two sides equal (``Tm > TIME`` after ``Tm++`` met with 0 and 32767, the reference has TIME - 1), an
assignment that writes the value already there (a timer cleared while 0, two stubs both returning 127), an arithmetic
operator on an operand that hides it (``x * 5 / 100`` with x = 10 is 0; ``145 / -50`` and ``145 / -51`` are both -2).
After the reach targets, each function also gets *fault-exposing* targets, searched the same way on their own budget
and row cap: a relational condition evaluated with equal sides while it decides its decision's outcome (boundary
values at the point of use); an assignment executed replacing a different value; an arithmetic operator with a
non-zero right operand (``+`` ``-``), no zero operand (``*``), a dividend at a non-zero multiple of the divisor (``/``
``%`` — the quotient's step). The model records the operands and the replaced values as it runs
(`observe_decisions(operands=, writes=)`); the climb adds a secant step — the value of one input that brings the watched
quantity to what the target needs, from its change over one probe move (``Tm`` 0 → 19, ``x`` 10 → 20, 145 → 150).
These are test-design criteria (boundary values, data-flow writes, operand values), not mutants: no mutant is
generated or consulted.

(R84) Exposing a fault at its site is not yet seeing it in an output. Of the 20 KJPDS02_PV mutants neither the reference
nor the generated rows killed after R83, the rows ran the site with the exposing values but the changed value died on
the way: a timer at its limit (`ErrTm < u16g_MAX` with ErrTm 65535) whose other branch writes the state the row already
held; a clamp `y = 0` multiplied by `Diff = Assist - Start` with the two equal; a threshold chosen from two inputs the
rows held equal (slope and normal current); a clamp whose other arm is the same value unless `EndStep < 0` — and the
first two rounds left out the search over values outside the design (R79 review W3), where `den <= -2` and
`num != 0` were what `s32_DivRound`'s negative-divisor arm needed. With ``propagate`` the search has one kind of
target per site — the fault-exposing ones (boundary · write · arithmetic) and every comparison of a decision (a
condition taking the other outcome, observable MC/DC — Whalen et al., ICSE 2013) — met only where the site's value,
changed, changes an observed output: the run is repeated with that one value changed (a data-state perturbation, as
in Voas' PIE: the comparison negated — at its boundary point for a boundary target —, the write left out, the right
operand of ``+`` ``-`` ``*`` as the identity, ``/`` ``%`` one step off; `observe_decisions(perturb=)`), and an output
both runs derive must differ. No mutant of the measuring tool is generated or consulted; the perturbations are of the
same kinds of faults, so the literal mutants (a constant changed — no target here) are the held-out check. A row that
meets the infection but not the propagation is one step from its target: the climb then tries one other input at a
time and stops at the first move that propagates. Rows already in the suite that meet a target are checked first
(at most `MAX_PROPAGATE_CHECK` per target, the rest counted).

Budgets per function (runs · interpreter steps · rows · candidates per input · climb moves · climb starts) are counted
in the report when they cut.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from generators import c_project_context as cpc
from generators import mcdc_design as md
from generators.boundary_rows import _as_int
from generators.c_source_oracle import (
    Unsupported,
    _parsed_function,
    _substitute,
    cast_unary_operand,
    observe_decisions,
    scope_matches,
)

_log = logging.getLogger(__name__)
SCENARIO_PREFIX = "SCN_"
SCENARIO_FI_PREFIX = "SCNR_"   # a scenario only values outside the design range reach (FI — the SUTS caller's second search)
MAX_ROWS = 16            # scenario rows per function and search
MAX_RUNS = 800           # oracle runs per function and search
MAX_STEPS = 1_500_000    # interpreter steps per function and search (summed over the runs)
MAX_POOL = 12            # candidate values per input
MAX_STARTS = 24          # existing rows tried as climb starts
MAX_CLIMB = 24           # moves per climb
# conditions of a control condition read as sub-conditions (more: outcome only). (R83) 16 → 64: a decision of more had no
#   sub-condition record, so no fault-exposing boundary of its conditions either (HDPDM01 `s_DoorState_AutoStop_Detection`:
#   ``u8g_ApiIn_MotorCountSpeed >= u16s_ASSIST_START_SPEED1`` in a 26-condition `else if` never met at 8 — `>` survived).
#   A record costs one evaluation of the condition's tree per sub-condition (the outcome with that one flipped)
MAX_ATOMS = 64
MAX_EXPOSE_ROWS = 16     # (R79) fault-exposing rows per function and search
MAX_EXPOSE_RUNS = 800    # (R79) their own oracle runs per function and search, after the reach targets'
MAX_EXPOSE_STEPS = 1_500_000
MAX_PROPAGATE_ROWS = 16      # (R84) fault-propagating rows per function and search
MAX_PROPAGATE_RUNS = 800     # (R84) their oracle runs (plain and perturbed) per function and search
MAX_PROPAGATE_STEPS = 1_500_000
MAX_PROPAGATE_CHECK = 48     # (R84) suite rows checked per target before the search (perturbed runs each)
MAX_PROPAGATE_CHECK_RUNS = 2_000   # (R84) and those checks' perturbed runs per function and search
MAX_PROPAGATE_CHECK_STEPS = 1_500_000   # (R84) and their interpreter steps
PROPAGATE_KINDS = ("boundary", "flip", "write", "arith")
_FREE_SPAN = 80
_RELATIONAL = {"<", "<=", ">", ">="}
_ARITH = {"+", "-", "*", "/", "%"}
EXPOSE_KINDS = ("boundary", "write", "arith")
_FAR = 10 ** 9


def _stopped_by_budget(reason: Any) -> bool:
    """A run a step budget stopped — by the reason's head: (R90 re-review 3 W-R3-3) a budget reason may name what spent
    it (``execution_budget:polling_way_out_search``)."""
    return str(reason or "").split(":", 1)[0] in ("search_step_budget", "execution_budget")


def _free_value(i: int) -> int:
    """The operating value of the i-th input the code compares with nothing (no design range): 101 + 11·i mod 80 — no two
    of the first 80 share one (11 and 80 are coprime: a difference of two is never 0), each is past the divisors such
    code scales by (``x * 10 / 20``, ``x / (10 - 60)`` — a value under 50 makes the second 0 and hides the constants;
    HDPDM01 `s_AstOutCompensate`), and the product of two (at most 180 · 179) stays inside a signed 16-bit ``int``. A
    run they overflow on is no clean scenario: the climb then moves every input (`find_scenarios.blocking_inputs`)."""
    return 101 + (11 * i) % _FREE_SPAN


def _norm(domain: Any) -> tuple | list | None:
    """``(lo, hi)`` for an integer range, a sorted list for a value set, else None."""
    if isinstance(domain, (list, set, frozenset)):
        vals = sorted({int(v) for v in domain if isinstance(v, int) and not isinstance(v, bool)})
        return vals or None
    if isinstance(domain, tuple) and len(domain) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                              for v in domain):
        return domain if domain[0] <= domain[1] else None
    if isinstance(domain, dict):
        if domain.get("values"):
            return _norm(list(domain["values"]))
        lo, hi = domain.get("min"), domain.get("max")
        return _norm((lo, hi)) if isinstance(lo, int) and isinstance(hi, int) else None
    return None


def _whole_type(domain) -> bool:
    """A range that is a whole 8/16/32-bit integer type — a design document that writes it says nothing the declaration
    does not (HDPDM01 SwUDS gives `U16` gains ``0 ~ 65535``): its middle is the type's middle, no operating value."""
    if not isinstance(domain, tuple):
        return False
    return domain in {(0, 2 ** b - 1) for b in (8, 16, 32)} | {(-2 ** (b - 1), 2 ** (b - 1) - 1) for b in (8, 16, 32)}


def _inside(domain, v: int) -> bool:
    return v in domain if isinstance(domain, list) else domain[0] <= v <= domain[1]


def _at_home(home, v: int) -> bool:
    """(R80 review W-R3-1) A value at home: inside a range's bounds, or a member of a value set (a design value list,
    the enumerators a design keeps) — a value between a set's members is not at home."""
    return v in home if isinstance(home, list) else home[0] <= v <= home[1]


def _extreme(domain, v: int) -> bool:
    """A type end / far value of a wide range — the values the search takes last and polishes away."""
    if isinstance(domain, list):
        return False
    lo, hi = domain
    return hi - lo > 255 and (v in (lo, hi) or abs(v) >= 16384)


_COMPARISONS = frozenset({"<", "<=", ">", ">=", "==", "!="})
# a program object a run read (``g`` · ``g.a.b`` · ``g[2]``) — the oracle's other read marks (``@…``) are not names
_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\[\d+\])?")
_POINTEE_NAME = re.compile(r"[A-Za-z_]\w*\[0\](?:\.[A-Za-z_]\w*)*(?:\[\d+\])?")   # (R81) `p[0]` · `p[0].a` · `p[0].b[2]`


#: (review R82 I4) how deep the candidate reader follows function-like macros a macro expansion invokes
_MACRO_CANDIDATE_DEPTH = 4


def _written_name(assignment, raw: bytes) -> str:
    """(R82) The object an assignment writes, by the name a row sets it by — `g` · `g.a` · `a[3]` · `p->a` as `p[0].a` ·
    `*p` as `p[0]` — or "" (an index that is no constant, a cast, a call …). The input completion decides whether it is
    an object a test may set (`suts._unit_object_decl`)."""
    left = assignment.child_by_field_name("left")
    if left is None:
        return ""
    text = "".join(md._text(left, raw).split())
    if text.startswith("*") and re.fullmatch(r"\*\(?[A-Za-z_]\w*\)?", text):
        return text.strip("*()") + "[0]"
    text = re.sub(r"^([A-Za-z_]\w*)->", r"\1[0].", text)
    text = re.sub(r"\[(\d+)[uUlL]*\]", r"[\1]", text)   # (review R82 W3) MISRA `g_arr[0U]` as the column `g_arr[0]`
    return text if _NAME.fullmatch(text) or _POINTEE_NAME.fullmatch(text) else ""


def _strip(node):
    """``(x)`` · ``(U8)x`` → x."""
    while node is not None and node.type in ("parenthesized_expression", "cast_expression"):
        node = node.child_by_field_name("value") if node.type == "cast_expression" else \
            next((c for c in node.named_children if c.type != "comment"), None)
    return node


def _constant(node, raw, constants, widths) -> int | None:
    """The value of a literal, an integer macro / enumerator, or a negated one — None for anything else. A candidate
    value only: a cast on the constant is stripped without converting (``(S8)200`` reads 200 — the comparison's own
    reading is `boundary_rows.compared_constants`'s; a wrong candidate costs runs, never a claim)."""
    x = _strip(node)
    sign = 1
    if x is not None and x.type == "unary_expression" and md._text(x.child_by_field_name("operator"), raw) == "-":
        sign, x = -1, _strip(x.child_by_field_name("argument"))
    if x is None or x.type not in ("number_literal", "identifier"):
        return None
    got = md._body_constants([x], raw, constants, widths)
    return sign * got[0] if len(got) == 1 else None


def _element_comparisons(fn, raw, scope, inputs: set[str]) -> dict[str, set[int]]:
    """Input ``a[k]`` → the constants ``a[K] <op> C`` compares it with (a constant index K — `mcdc_design._index_value`, the
    R76 reader). `boundary_rows.compared_constants` reads plain names only; the element inputs (R76 · R77) are named by
    their constant index."""
    constants = scope["constants"] if scope.get("constants") is not None else {}
    widths = (scope.get("target") or {}).get("widths") or {}
    out: dict[str, set[int]] = {}
    if not any("[" in str(n) for n in inputs):
        return out   # (review R82 I4) no element input: nothing to read, no macro to expand

    def read(top, text):
        for n in md._walk(top):
            op = n.child_by_field_name("operator") if n.type == "binary_expression" else None
            if op is None or md._text(op, text) not in _COMPARISONS:
                continue
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            for a, b in ((left, right), (right, left)):
                x = _strip(a)
                if x is not None and x.type == "binary_expression" and md._text(x.child_by_field_name("operator"), text) == "&":
                    # (R82) a masked comparison `(E & M) == C` or `(M & E) == C` (review R82 I7): C (with the mask's
                    #   bits) is a value E takes there
                    sides = [_strip(x.child_by_field_name("left")), _strip(x.child_by_field_name("right"))]
                    x = next((s for s in sides if s is not None and s.type == "subscript_expression"), None)
                if x is None or x.type != "subscript_expression" or (arg := md._array_name_node(x)) is None:
                    continue
                k = md._index_value(x.child_by_field_name("index"), text, constants, widths)
                name = f"{md._text(arg, text)}[{k}]"
                value = _constant(b, text, constants, widths) if k is not None and name in inputs else None
                if value is not None:
                    out.setdefault(name, set()).add(value)

    # (R82) and the comparisons a function-like macro the body invokes holds (`LINTP_IS_CF(pData)` →
    #   `(((pData)[0] & 0xF0u) == LINTP_CF)` — a LIN frame parser compares its buffer's bytes only through macros), and the
    #   macros that expansion invokes (review R82 I4: `IS_CF` → `GET_PCI`), each invocation once
    bodies = scope.get("function_like_macro_bodies") or {}
    params = scope.get("function_like_macro_params") or {}
    parser = cpc.shared_parser()
    seen: set[tuple] = set()

    def expand(top, text, depth):
        for n in md._walk(top) if bodies and parser is not None and depth <= _MACRO_CANDIDATE_DEPTH else ():
            f = n.child_by_field_name("function") if n.type == "call_expression" else None
            name = md._text(f, text) if f is not None and f.type == "identifier" else ""
            if name not in bodies or name not in params:
                continue
            args = n.child_by_field_name("arguments")
            argv = [md._text(a, text) for a in (args.named_children if args is not None else []) if a.type != "comment"]
            if len(argv) != len(params[name] or ()) or (name, tuple(argv)) in seen:
                continue
            seen.add((name, tuple(argv)))
            try:
                node, eraw = cpc._parse_body(_substitute(bodies[name], params[name], argv), parser)
            except Exception as exc:  # noqa: BLE001 — a candidate value only: an expansion it cannot read gives none
                _log.debug("macro expansion unread for candidates (%s): %s", name, exc)
                continue
            if node is not None:
                read(node, eraw)
                expand(node, eraw, depth + 1)

    body = fn.child_by_field_name("body")
    read(body, raw)
    expand(body, raw, 1)
    return out


def _switch_labels(fn, raw, scope, inputs: set[str]) -> dict[str, list[int]]:
    """Input → the case labels of every ``switch`` whose controlling expression is that input (cast or parenthesized)."""
    constants = scope["constants"] if scope.get("constants") is not None else {}
    widths = (scope.get("target") or {}).get("widths") or {}
    out: dict[str, list[int]] = {}
    for n in md._walk(fn.child_by_field_name("body")):
        if n.type != "switch_statement":
            continue
        x = _strip(n.child_by_field_name("condition"))
        if x is None or x.type != "identifier" or md._text(x, raw) not in inputs:
            continue
        name = md._text(x, raw)
        body = n.child_by_field_name("body")
        for case in (body.named_children if body is not None else ()):
            v = case.child_by_field_name("value") if case.type == "case_statement" else None
            if v is None:
                continue
            got = md._body_constants([v], raw, constants, widths)
            if len(got) == 1:
                out.setdefault(name, []).append(got[0])
    return out


def operating_pools(unit: dict[str, Any], domains: dict[str, Any], fn, raw, scope, stats: dict[str, Any],
                    home: dict[str, tuple] | None = None) -> tuple[dict[str, list[int]], dict[str, int]]:
    """``(pools, defaults)``: per input, its candidate values in the order the search tries them (the operating value
    first) and its operating value. See the module docstring for the order. ``home``: inputs whose domain was widened
    past their design range (the caller's second search) → that range — its values come first and the operating value
    is one of them, so a value outside it appears only where the search needs one."""
    from generators.boundary_rows import compared_constants
    home = home or {}
    names = list(domains)
    compared = compared_constants(unit, names, stats)
    for name, ks in (stats.get("macro_argument_constants") or {}).items():
        compared.setdefault(name, set()).update(ks)   # a macro argument's comparison is a candidate, never a claim
    for name, ks in _element_comparisons(fn, raw, scope, set(names)).items():
        compared.setdefault(name, set()).update(ks)
    labels = _switch_labels(fn, raw, scope, set(names))
    constants = scope["constants"] if scope.get("constants") is not None else {}
    widths = (scope.get("target") or {}).get("widths") or {}
    body_consts = md._body_constants([fn.child_by_field_name("body")], raw, constants, widths)
    design = {v for v, src in (unit.get("bounds_source") or {}).items()
              if src in ("uds_range", "hsis_range", "uds_values") and not _whole_type(domains.get(v))}
    pools: dict[str, list[int]] = {}
    defaults: dict[str, int] = {}
    free = 0
    for name in names:
        dom = domains[name]
        ks = sorted(compared.get(name, ()), key=lambda k: (k == 0, abs(k), k))   # non-zero first, smaller first
        lab = list(dict.fromkeys(labels.get(name, ())))
        if isinstance(dom, list):
            head = [v for v in lab + ks if v in dom]
            order = list(dict.fromkeys(head + [dom[len(dom) // 2]] + dom))
            if name in home:
                # (review R80 W3) the home values first; (W-R2-1) the values outside them are what the widened search is
                #   for — they keep slots (at most half a pool) after every home value the cap allows; (W-R3-3) the
                #   widened list's ends first among them — the ±1 no enumerator names
                inside = [v for v in order if _at_home(home[name], v)]
                outside = [v for v in order if not _at_home(home[name], v)]
                ends = [v for v in (dom[0], dom[-1]) if v in outside]
                outside = ends + [v for v in outside if v not in ends]
                keep = outside[:MAX_POOL // 2]
                if len(inside) > MAX_POOL or len(outside) > len(keep):
                    stats["pools_capped"] = int(stats.get("pools_capped") or 0) + 1
                pools[name] = inside[:MAX_POOL] + keep
                defaults[name] = pools[name][0]
                continue
            if len(order) > MAX_POOL:
                stats["pools_capped"] = int(stats.get("pools_capped") or 0) + 1   # (review R80 W-R2-1) a list too
            pools[name] = order[:MAX_POOL]
            defaults[name] = order[0]
            continue
        lo, hi = dom
        span = home.get(name) or ((lo, hi) if name in design else None)
        cand: list[int] = []
        if span is not None and not any(span[0] <= k <= span[1] for k in ks + lab):
            cand.append((span[0] + span[1]) // 2)
        for k in lab:
            cand.append(k)
        for k in ks:
            cand += [k, k + 1, k - 1]
        if span is not None:
            cand += [(span[0] + span[1]) // 2, span[0], span[1], span[0] + 1, span[1] - 1]
        if not ks and not lab and span is None:
            small = _free_value(free)
            free += 1
            cand.append(small if lo <= small <= hi else (hi if hi - lo <= 1 else (lo + hi) // 2))
        cand += [c for c in body_consts if c not in (0, 1, -1)]
        cand += [1, 0, -1, 2]
        cand += [lo, hi]
        order = [v for v in dict.fromkeys(cand) if lo <= v <= hi]
        ends = [v for v in (lo, hi) if v not in order[:MAX_POOL - 2]]
        if name in home:
            # the home range first, in the order above — a value outside it is a candidate the search reaches for last;
            #   but the constants it is compared with (and their neighbours) outside the range are what a widened search
            #   is for: they keep their places under the cap ahead of the other home values (review R78 R2 W-R2-4)
            #   — and so are the switch labels outside it (review R78 R3 W-R3-1: a state machine's label past the design
            #   range); the slots left go to the other values in their order, the type's ends last
            inside = [v for v in order if span[0] <= v <= span[1]]
            needed = [v for v in dict.fromkeys([*lab, *(x for k in ks for x in (k, k + 1, k - 1))])
                      if lo <= v <= hi and not span[0] <= v <= span[1]]
            rest = [v for v in order if v not in inside and v not in needed]
            if len(inside) + len(needed) + len(rest) > MAX_POOL:
                stats["pools_capped"] = int(stats.get("pools_capped") or 0) + 1
                keep = max(1, MAX_POOL - 2 - len(needed))
                head = inside[:keep] + needed[:MAX_POOL - 2 - min(keep, len(inside))]
                tail = [v for v in (lo, hi) if v not in head]
                room = MAX_POOL - len(head) - len(tail)
                order = head + [v for v in inside[keep:] + rest if v not in head and v not in tail][:room] + tail
            else:
                order = inside + needed + rest
        elif len(order) > MAX_POOL:
            stats["pools_capped"] = int(stats.get("pools_capped") or 0) + 1
            # the type ends stay candidates (last) — a value only they reach is still reachable
            order = order[:MAX_POOL - 2] + ends
        pools[name] = order
        defaults[name] = order[0]
    return pools, defaults


def _case_entry(case):
    """The first statement a jump to this label runs (the label's own value excluded) — None for an empty label."""
    value = case.child_by_field_name("value")
    return next((c for c in case.named_children if c != value and c.type != "comment"), None)


def _key(node) -> tuple:
    return (node.start_byte, node.end_byte, node.type)


def _operator(node, raw) -> str:
    op = node.child_by_field_name("operator")
    return md._text(op, raw) if op is not None else ""


def _reads_a_variable(node, raw, constants) -> bool:
    """(R79 review I5) The expression reads something a row can set: a name that is no integer macro / enumerator
    (``NUM_CH > 2U`` and ``MAX * 10U`` are fixed), or a call's value (a stub input)."""
    for x in md._walk(node):
        if x.type != "identifier":
            continue
        parent = x.parent
        if parent is not None and parent.type == "call_expression" and parent.child_by_field_name("function") == x:
            return True
        if md._text(x, raw) not in constants:
            return True
    return False


def _nondegenerate(op, rec) -> bool:
    """(R79) Operands on which a fault in the operator shows: a non-zero right operand of ``+`` ``-`` (``x - 0`` is
    ``x + 0``), no zero operand of ``*``, a dividend at a non-zero multiple of the divisor of ``/`` ``%`` (``100 / 50``
    is not ``100 / 51``; ``145 / 50`` is ``145 / 51``)."""
    left, right = rec
    if left is None or right is None:
        return False
    if op in ("/", "%"):
        return right != 0 and left != 0 and left % right == 0
    if op == "*":
        return left != 0 and right != 0
    return right != 0


def _arith_gap(op, rec) -> int:
    """(R79) How far one evaluation is from `_nondegenerate` — for ``/`` ``%`` the distance to the nearest non-zero
    multiple of the divisor."""
    left, right = rec
    if left is None or right is None:
        return _FAR
    if op in ("/", "%"):
        if right == 0:
            return _FAR
        d, a = abs(right), abs(left)
        if a < d:
            return d - a
        m = a % d
        return min(m, d - m)
    if op == "*":
        return int(left == 0) + int(right == 0)
    return int(right == 0)


def _multiple_near(left, right):
    """(R79) The non-zero multiple of ``right`` nearest ``left`` (on the side of ``left``)."""
    d = abs(right)
    k = max(1, round(abs(left) / d))
    return k * d if left >= 0 else -k * d


def _conditionally_evaluated(x, holder, raw) -> bool:
    """(R79 review W-R3-1) ``x`` sits under a part its statement evaluates on some runs only — a ``?:`` arm, the right
    side of ``&&`` / ``||``: no record yet is no proof the model cannot record it."""
    child, node = x, x.parent
    while node is not None and node != holder:
        if node.type == "conditional_expression" and child != node.child_by_field_name("condition"):
            return True
        if node.type == "binary_expression" and _operator(node, raw) in ("&&", "||") and \
                child == node.child_by_field_name("right"):
            return True
        child, node = node, node.parent
    return False


def _records(r, field, index, path=None, size=2) -> list:
    """(R79) The watched evaluations of one operator / assignment on a run (one path, or all): pairs, or for
    ``decides`` the ``(left, right, decides)`` triples."""
    seq = (r.get(field) or {}).get(index) or []
    paths = [seq[path]] if path is not None and path < len(seq) else ([] if path is not None else seq)
    return [x for p in paths for x in (p or ()) if isinstance(x, (tuple, list)) and len(x) == size]


def _line_text(node, raw) -> str:
    return " ".join(md._text(node, raw).split())[:80]


def find_scenarios(unit: dict[str, Any], domains: dict[str, Any], outputs: list[str],
                   existing: list[dict[str, Any]] | None = None,
                   covered: list[dict[str, Any]] | None = None,
                   home: dict[str, tuple] | None = None, expose: bool = True,
                   propagate: bool = False) -> dict[str, Any]:
    """``{"rows": [{"inputs", "target_kind", "target_line", "target_text", "target_outcome", "targets_reached",
    "outputs_derived"}], "reached_vectors": [...], "report": {...}}``.

    ``domains``: the inputs the search may set — ``(lo, hi)``, a value list, or a ``{"min","max"}``/``{"values"}`` dict;
    nothing else gets a value (a row leaves it blank, as every other row does). ``outputs``: the outputs whose derived
    count ranks clean vectors. ``existing``: input vectors already in the suite — climb starts (their values outside
    ``domains`` are dropped) and duplicates (a scenario equal to one of them is not added again, but the targets it
    reaches count as reached: the suite has that row). ``covered``: vectors whose clean runs already reach some targets
    — those targets are not searched (``covered_before``; the caller's second search over wider domains looks only for
    what the first did not reach). ``home``: widened inputs → their design range (`operating_pools`); a found vector's
    value outside it is moved back inside wherever the target stays reached, so what is left outside is what the
    target needs. A target is *reached* only by a vector the suite then holds — a row this search adds or an existing
    duplicate; once `MAX_ROWS` rows are added the search goes on (a duplicate costs no row; `needed_inputs` keeps
    growing) but a new row is not added — its target is ``cut`` and stays unreached. ``reached_vectors``: the vectors
    that reached targets (rows and duplicates) — what a caller may pass as ``covered`` (the SUTS caller passes every row
    of the suite instead).

    (R84) ``propagate``: no reach targets — the fault-propagating ones only (`PROPAGATE_KINDS`, see the module text), on
    their own budget (`MAX_PROPAGATE_RUNS` · `MAX_PROPAGATE_STEPS`, perturbed runs included) and row cap
    (`MAX_PROPAGATE_ROWS`); the report's ``expose_*`` keys count them, ``propagate_*`` the perturbed runs, the suite rows
    checked and the targets whose best was a met infection that no move propagated. A row says which outputs changed
    (``propagated``)."""
    report = {"status": "searched", "targets": 0, "statements": 0, "branches": 0, "reached_clean": 0,
              "reached_unclean_only": 0, "not_reached": 0, "local_best": 0, "climb_cap": 0, "budget_cut": 0,
              "runs": 0, "steps": 0, "rows": 0, "cut": 0, "duplicates": 0, "budget_exhausted": False,
              "pools_capped": 0, "inputs": 0, "covered_before": 0, "starts_capped": 0, "conditions_outcome_only": 0,
              "needed_inputs": {}, "inputs_needed": 0,
              # (R79) fault-exposing targets: counted apart (their own budget · rows)
              "expose_targets": 0, "expose_boundary": 0, "expose_write": 0, "expose_arith": 0,
              "expose_covered_before": 0, "expose_reached": 0, "expose_rows": 0, "expose_not_reached": 0,
              "expose_cut": 0, "expose_unmodeled": 0, "expose_local_best": 0, "expose_budget_cut": 0,
              "expose_budget_exhausted": False, "expose_runs": 0, "expose_steps": 0, "expose_duplicates": 0,
              "reached_by_exposing_rows": 0, "expose_refused": 0, "expose_error_cut": 0, "expose_met_by_reach_rows": 0}
    if propagate:
        # (R84) the propagating search's own counts — flip targets, perturbed runs, suite rows checked, and the targets
        #   whose site the rows / climbs did expose without any output changing
        report.update(expose_flip=0, propagate_perturbed_runs=0, propagate_perturbed_refused=0,
                      propagate_perturbed_budget=0, propagate_checked_rows=0, propagate_check_capped=0,
                      propagate_check_late=0, propagate_check_steps=0, propagate_infected_only=0)
    empty: dict[str, Any] = {"rows": [], "reached_vectors": []}
    if not unit.get("source_text") or not scope_matches(unit):
        return {**empty, "report": {**report, "status": "no_project_scope"}}
    doms = {k: d for k, v in domains.items() if (d := _norm(v)) is not None}
    if not doms:
        return {**empty, "report": {**report, "status": "no_integer_inputs"}}
    cap = MAX_ROWS
    # (review R80 W3) an enumerator list widened by ±1 has its home range too (the enumerators' ends)
    home = {k: (sorted(v) if isinstance(v, list) else tuple(v)) for k, v in (home or {}).items()
            if k in doms and isinstance(doms[k], (tuple, list))}
    scope = unit["project_scope"]
    raw = str(unit["source_text"]).encode()
    try:
        _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, str(unit.get("name") or ""), scope)
    except (Unsupported, cpc.Unresolved, AttributeError) as exc:
        return {**empty, "report": {**report, "status": "function_unread:" + str(exc)[:60]}}
    body = fn.child_by_field_name("body")
    if body is None:
        return {**empty, "report": {**report, "status": "function_unread"}}

    # ── targets: statements and branch outcomes the build compiles ─────────────────────────────────────────────
    statements, conds = [], []
    for node, undecided in md._live_nodes(body, raw, scope):
        if undecided:
            continue
        if node.type in ("expression_statement", "return_statement") and \
                any(c.type != "comment" for c in node.named_children):
            statements.append(node)
        if node.type in ("if_statement", "while_statement", "for_statement"):
            c = node.child_by_field_name("condition")
            if c is not None:
                conds.append(c)
    entries = [e for n in md._walk(body) if n.type == "case_statement" and (e := _case_entry(n)) is not None]
    watch = list({_key(n): n for n in statements + entries}.values())
    watch_index = {_key(n): i for i, n in enumerate(watch)}
    cond_index = {_key(c): i for i, c in enumerate(conds)}
    specs, spec_of, spec_atoms = [], {}, []
    for c in conds:
        atoms: list = []
        try:
            ir = md._path_ir(c, raw, atoms)
        except Unsupported:
            report["conditions_outcome_only"] += 1   # its outcome still counts; no sub-condition distance
            continue
        if len(atoms) > MAX_ATOMS:
            report["conditions_outcome_only"] += 1
            continue
        spec_of[_key(c)] = (len(specs), ir)
        specs.append({"key": list(_key(c)), "atoms": [list(_key(a)) for a in atoms], "ir": ir})
        spec_atoms.append(atoms)
    targets = []   # (kind, node, chain, final) — final: ("reach", watch i) or ("guard", cond i, outcome)
    for s in statements if not propagate else ():
        targets.append(("statement", s, md.control_steps(s, cases=True), ("reach", watch_index[_key(s)])))
    for c in conds if not propagate else ():
        for outcome in (True, False):
            targets.append(("branch", c, md.control_steps(c.parent, cases=True) + [("guard", c, outcome)],
                            ("guard", cond_index[_key(c)], outcome)))
    report.update(targets=len(targets), statements=len(statements) if not propagate else 0,
                  branches=2 * len(conds) if not propagate else 0)
    if not targets and not propagate:
        return {**empty, "report": {**report, "status": "no_targets"}}
    # (R79) fault-exposing targets — searched after every reach target, on their own budget and row cap; ``expose``
    #   False leaves them out (the SUTS second search over widened domains — review R79 W3: its rows are FI rows)
    n_reach = len(targets)
    constants = scope.get("constants") if isinstance(scope.get("constants"), dict) else {}
    operand_nodes: list = []
    write_nodes: list = []
    spec_cond = {}
    for c in conds if expose or propagate else ():
        got = spec_of.get(_key(c))
        if got is None:
            continue
        spec_cond[got[0]] = c
        for ai, a in enumerate(spec_atoms[got[0]]):
            if a.type != "binary_expression" or not _reads_a_variable(a, raw, constants):
                continue
            op = _operator(a, raw)
            if op in _RELATIONAL:
                targets.append(("boundary", a, md.control_steps(c.parent, cases=True),
                                ("bound", len(operand_nodes), got[0], ai)))
            if propagate and op in _COMPARISONS:
                # (R84) the condition taking the other outcome where it decides the decision (observable MC/DC) — a
                #   relational one has its boundary target too (its boundary point may be where no fault shows)
                targets.append(("flip", a, md.control_steps(c.parent, cases=True),
                                ("flip", len(operand_nodes), got[0], ai)))
            if op in _RELATIONAL or (propagate and op in _COMPARISONS):
                operand_nodes.append(a)
    for s in statements if expose or propagate else ():
        e = next((x for x in s.named_children if x.type != "comment"), None)
        if s.type == "expression_statement" and e is not None and e.type == "assignment_expression" and \
                _operator(e, raw) == "=":
            targets.append(("write", s, md.control_steps(s, cases=True), ("write", len(write_nodes))))
            write_nodes.append(e)
    seen_ops: set = set()
    holder_of: dict = {}   # arith operand index → the watched statement holding it (None in a condition)
    for holder, at in ([(s, s) for s in statements] + [(c, c.parent) for c in conds]) if expose or propagate else ():
        for x in md._walk(holder):
            if x.type == "binary_expression" and _key(x) not in seen_ops and \
                    (op := _operator(x, raw)) in _ARITH and _reads_a_variable(x, raw, constants) and \
                    cast_unary_operand(x, raw, scope) is None:   # (review R79 I-R3-2) ``(S16)-1800`` is a cast
                seen_ops.add(_key(x))
                holder_of[len(operand_nodes)] = None if _conditionally_evaluated(x, holder, raw) else \
                    watch_index.get(_key(holder))
                targets.append(("arith", x, md.control_steps(at, cases=True), ("arith", len(operand_nodes), op)))
                operand_nodes.append(x)
    report.update(expose_targets=len(targets) - n_reach,
                  expose_boundary=sum(1 for t in targets[n_reach:] if t[0] == "boundary"),
                  expose_write=sum(1 for t in targets[n_reach:] if t[0] == "write"),
                  expose_arith=sum(1 for t in targets[n_reach:] if t[0] == "arith"))
    operand_keys = [list(_key(n)) for n in operand_nodes]
    write_keys = [list(_key(n)) for n in write_nodes]
    perturb_of: dict[int, list] = {}   # (R84) target index → the perturbation its propagation check runs
    if propagate:
        report["expose_flip"] = sum(1 for t in targets if t[0] == "flip")
        if not targets:
            return {**empty, "report": {**report, "status": "no_targets"}}
        for i, t in enumerate(targets):
            kind, final = t[0], t[3]
            if kind in ("boundary", "flip"):
                perturb_of[i] = ["flip_equal" if kind == "boundary" else "flip", operand_keys[final[1]]]
            elif kind == "write":
                perturb_of[i] = ["skip_write", write_keys[final[1]]]
            else:
                perturb_of[i] = ["drop_right" if final[2] in ("+", "-", "*") else "step", operand_keys[final[1]]]

    inputs = list(doms)
    report["inputs"] = len(inputs)
    stats: dict[str, Any] = {}
    pools, defaults = operating_pools(unit, doms, fn, raw, scope, stats, home)
    report["pools_capped"] = int(stats.get("pools_capped") or 0)
    input_set = set(inputs)
    sources = md._local_sources(body, raw)
    cond_inputs = {}

    def inputs_of(node) -> list[str]:
        k = _key(node)
        if k not in cond_inputs:
            cond_inputs[k] = md._condition_inputs(node, raw, sources, input_set) or list(inputs)
        return cond_inputs[k]

    # (R82 measurement, HD `g_ApiIn_LinRx_ReadData`: reached targets 41 → 21) an input the completion added only as a
    #   write's prior value — the model never read its initial value: a guard naming it reads what the function wrote
    #   over it (`u8s_SbcmMsg_F = l_flg_tst_…(); if (u8s_SbcmMsg_F == u8g_ON)`), so moving it decides nothing and the
    #   climb stopped there (before R82 the name was no input and the climb moved every input). A climb to a guard, a
    #   case or a comparison moves the others first (`control_inputs_of`); at a local best it tries the written-only
    #   names that step names once more (`prior_named` — review R82 W-R6-1: the classification is the round's that
    #   added the name, a wider domain may open a path reading its initial value)
    added = ((unit.get("source_read_inputs") or {}).get("added")) or {}
    written_only = {n for n, a in added.items() if isinstance(a, dict) and a.get("prior_value_for_write")
                    and not a.get("read_on_model", True)} & input_set
    movable = [n for n in inputs if n not in written_only] or list(inputs)
    control_inputs: dict = {}

    def control_inputs_of(node) -> list[str]:
        k = _key(node)
        if k not in control_inputs:
            control_inputs[k] = md._condition_inputs(node, raw, sources, input_set - written_only) or movable
        return control_inputs[k]

    guards = [list(_key(c)) for c in conds]
    reach_keys = [list(_key(n)) for n in watch]
    cache: dict[tuple, dict] = {}
    spent = [0]

    def vkey(v):
        return tuple(sorted(v.items()))

    run_budget: list = [(0, 0)]   # runs · steps that do not count (the covered rows' check); None while it runs
    limits = [MAX_RUNS, MAX_STEPS]   # (R79) the phase's: the reach targets', then the fault-exposing targets'
    flag = ["budget_exhausted"]
    perturbed = [0]   # (R84) perturbed runs so far — runs of the budget like the plain ones
    psteps = [0]      # (R84) and their interpreter steps

    def nruns() -> int:
        return len(cache) + perturbed[0]

    def exhausted() -> bool:
        if run_budget[0] is None:
            return False
        return nruns() - run_budget[0][0] >= limits[0] or spent[0] - run_budget[0][1] >= limits[1]

    def run(vectors: list[dict[str, int]]) -> None:
        todo = list({vkey(v): v for v in vectors if vkey(v) not in cache}.values())
        try:
            for start in range(0, len(todo), 16):
                if exhausted():
                    report[flag[0]] = True
                    return
                runs_left, steps_left = ((16, None) if run_budget[0] is None else
                                         (limits[0] - (nruns() - run_budget[0][0]),
                                          max(0, limits[1] - (spent[0] - run_budget[0][1]))))
                chunk = todo[start:start + min(16, runs_left)]
                results = observe_decisions(unit, chunk, specs, guards, step_limit=steps_left,
                                            reach=reach_keys, outputs=list(outputs), operands=operand_keys,
                                            writes=write_keys)
                for v, r in zip(chunk, results, strict=True):
                    cache[vkey(v)] = r
                    vec_of[id(r)] = v
                    spent[0] += int(r.get("steps") or 0)
        finally:
            report["runs"], report["steps"] = len(cache), spent[0]

    def clean(r) -> bool:
        return r.get("status") == "supported" and not r.get("forked") and not r.get("possible_undefined_behavior")

    vec_of: dict[int, dict[str, int]] = {}   # (R84) id(run) → its vector (runs stay in the cache: ids are stable)
    pcache: dict[tuple, tuple | None] = {}   # (R84) (vector, target i) → outputs the perturbed run changed; None: no run
    index_of = {id(t): i for i, t in enumerate(targets)}

    def prun(vectors: list[dict[str, int]], ti: int) -> None:
        """(R84) The perturbed runs of target ``ti`` for those vectors (already run plainly): the outputs both runs
        derive and the perturbation changed — () when none changed, None when the perturbed run is no clean run (it
        refuses, branches on an unknown value, may hit undefined behaviour): a change there is not shown."""
        todo = []
        for v in {vkey(v): v for v in vectors if (vkey(v), ti) not in pcache and vkey(v) in cache}.values():
            if any("value" in (o or {}) for o in (cache[vkey(v)].get("outputs") or {}).values()):
                todo.append(v)
            else:
                pcache[(vkey(v), ti)] = ()   # no output the plain run derives — no change can show; no run
        for start in range(0, len(todo), 16):
            if exhausted():
                report[flag[0]] = True
                return
            # (review R84 I3) the suite rows' check (no search budget) keeps to its own step cap
            runs_left, steps_left = ((16, max(0, MAX_PROPAGATE_CHECK_STEPS - psteps[0])) if run_budget[0] is None else
                                     (limits[0] - (nruns() - run_budget[0][0]),
                                      max(0, limits[1] - (spent[0] - run_budget[0][1]))))
            chunk = todo[start:start + min(16, runs_left)]
            results = observe_decisions(unit, chunk, [], [], step_limit=steps_left, outputs=list(outputs),
                                        perturb=perturb_of[ti])
            for v, pr in zip(chunk, results, strict=True):
                perturbed[0] += 1
                report["propagate_perturbed_runs"] += 1
                spent[0] += int(pr.get("steps") or 0)
                psteps[0] += int(pr.get("steps") or 0)
                if run_budget[0] is None:
                    report["propagate_check_steps"] += int(pr.get("steps") or 0)
                if not clean(pr):
                    # (review R84 I3 · I-R2-3) a run a step budget stopped — never started, or cut by its share of what
                    #   was left — is counted apart from one the model refuses; one the suite check stopped is not kept
                    #   (the search phase has its own budget and runs it again)
                    stopped = _stopped_by_budget(pr.get("reason"))
                    report["propagate_perturbed_budget" if stopped else "propagate_perturbed_refused"] += 1
                    if not (stopped and run_budget[0] is None):
                        pcache[(vkey(v), ti)] = None
                    continue
                base = cache[vkey(v)].get("outputs") or {}
                got = pr.get("outputs") or {}
                pcache[(vkey(v), ti)] = tuple(sorted(
                    o for o in base if "value" in (base.get(o) or {}) and "value" in (got.get(o) or {})
                    and base[o]["value"] != got[o]["value"]))

    def propagated(r, target) -> bool:
        """(R84) The perturbation of ``target``'s site changes an output of run ``r`` (one perturbed run, cached)."""
        v = vec_of.get(id(r))
        ti = index_of.get(id(target))
        if v is None or ti is None:
            return False
        if (vkey(v), ti) not in pcache:
            prun([v], ti)
        return bool(pcache.get((vkey(v), ti)))

    def prepare(vectors: list[dict[str, int]], target) -> None:
        """(R84) The perturbed runs a ranking of those vectors for ``target`` needs, in batches: those whose plain run
        meets the target's infection."""
        if not propagate:
            return
        ti = index_of[id(target)]
        prun([v for v in vectors if vkey(v) in cache and infected(cache[vkey(v)], target)], ti)

    def event(r, step, path) -> bool:
        """Does path ``path`` of run ``r`` satisfy one control step / final event?"""
        kind = step[0]
        if kind == "bound":
            # (R79 review W1) on one evaluation: the two sides equal and the condition deciding the outcome
            return any(a is not None and a == b and d for a, b, d in _records(r, "decides", step[1], path, 3))
        if kind == "flip":
            # (R84) an evaluation where the condition decides the decision's outcome
            return any(d for _a, _b, d in _records(r, "decides", step[1], path, 3))
        if kind == "arith":
            return any(_nondegenerate(step[2], x) for x in _records(r, "operands", step[1], path))
        if kind == "write":
            return any(a is not None and b is not None and a != b for a, b in _records(r, "writes", step[1], path))
        if kind == "guard":
            i = cond_index.get(_key(step[1])) if not isinstance(step[1], int) else step[1]
            seq = (r.get("guards") or {}).get(i) or []
            return path < len(seq) and step[2] in seq[path]
        if kind == "case":
            entry = _case_entry(step[1])
            i = watch_index.get(_key(entry)) if entry is not None else None
            seq = ((r.get("reach") or {}).get(i) or []) if i is not None else []
            return path < len(seq) and bool(seq[path])
        # ("reach", i): reached on this path with no unknown branch before it
        seq = (r.get("reach") or {}).get(step[1]) or []
        return path < len(seq) and True in seq[path]

    def touched(r, target) -> bool:
        """Some path of a supported run gets to the target at all (also after a branch on an unknown value) — for a branch
        outcome, a path that evaluates the condition with that outcome or with an undetermined one (review R78 R2
        W-R2-2: `s_gate > 2U` read with s_gate unknown is reached, not a local best, and s_gate is what it needs)."""
        final = target[3]
        if r.get("status") != "supported":
            return False
        if final[0] in ("bound", "flip"):
            return bool(_records(r, "decides", final[1], size=3)) or bool(_records(r, "operands", final[1]))
        if final[0] == "arith":
            return bool(_records(r, "operands", final[1]))
        if final[0] == "write":
            return bool(_records(r, "writes", final[1]))
        if final[0] == "reach":
            return any(p for p in ((r.get("reach") or {}).get(final[1]) or []))
        return any(final[2] in p or None in p for p in ((r.get("guards") or {}).get(final[1]) or []))

    blocked_memo: dict[tuple, tuple] = {}

    def blocked_reads(r, target) -> set:
        """(R82) Objects the run read with no value from the vector that the guard its best path stops at names — what
        the climb needs to go on, though no path gets to the target. PV `s_DoorState_AutoStop_Check`: the 5th of 8
        ANDed conditions reads `u8g_DoorPreCtrl_PlayProtectLvl`, which no input list names; with it unknown the decision
        is false while a later condition is, and undetermined (ranked further) once that one holds — every climb stopped
        there ('local best') and no path reached the statement, so the search never named it. Only the objects the guard
        names itself (review R82 W6: every read of a run whose guard is undetermined changed no PV function's rows)."""
        if r.get("status") != "supported":
            return set()
        memo = (id(r), id(target))   # (review R82 I5) once per run and target — the runs stay in the cache
        if memo not in blocked_memo:
            blocked_memo[memo] = best_path(r, target)
        _depth, step = blocked_memo[memo]
        if step is None or step[0] != "guard":
            return set()
        node = step[1] if not isinstance(step[1], int) else conds[step[1]]
        words = set(re.findall(r"[A-Za-z_]\w*", raw[node.start_byte:node.end_byte].decode("utf-8", "replace")))
        out = set()
        for n in r.get("initial_reads") or ():
            name = str(n)[len("@pointee:"):] if str(n).startswith("@pointee:") else str(n)
            if re.split(r"[\[.]", name, maxsplit=1)[0] in words:
                out.add(n)
        return out

    def paths_of(r) -> int:
        lists = list((r.get("guards") or {}).values()) + list((r.get("reach") or {}).values())
        return max((len(x) for x in lists), default=0)

    def best_path(r, target) -> tuple[int, Any]:
        """``(depth, step)``: the control steps satisfied in order on the run's best path, and the first one it does not."""
        _kind, _node, chain, final = target
        best_depth, step = -1, None
        for p in range(max(paths_of(r), 1)):
            depth = 0
            for s in chain:
                if not event(r, s, p):
                    break
                depth += 1
            if depth > best_depth:
                best_depth, step = depth, (chain[depth] if depth < len(chain) else final)
        return best_depth, step

    def infected(r, target) -> bool:
        """The target's final event on a path whose control chain holds, in a clean run."""
        if not clean(r):
            return False
        chain, final = target[2], target[3]
        return any(len(chain) == sum(1 for _ in _prefix(r, chain, p)) and event(r, final, p)
                   for p in range(max(paths_of(r), 1)))

    def reached(r, target) -> bool:
        """`infected` — and (R84, ``propagate``) the perturbation of the site changes an output of the run."""
        return infected(r, target) and (not propagate or propagated(r, target))

    def _prefix(r, chain, p):
        for s in chain:
            if not event(r, s, p):
                return
            yield s

    def standing(r, target) -> tuple:
        """``(done, depth, -distance)`` of one run for one target: done = `reached`; depth = control steps satisfied in
        order on the best path; distance = sub-conditions of the first unsatisfied guard still to change
        (`mcdc_design._distance` on that run's evaluation of it)."""
        if r.get("status") != "supported":
            return (False, -1, 0)
        if reached(r, target):
            return (True, len(target[2]) + 1, 0)
        if propagate and infected(r, target):
            return (False, len(target[2]) + 1, 0)   # (R84) the site exposed, no output changed: one step from done
        depth, blocking = best_path(r, target)
        distance = 0
        if blocking is not None and blocking[0] == "guard":
            node = blocking[1] if not isinstance(blocking[1], int) else conds[blocking[1]]
            want = blocking[2]
            got = spec_of.get(_key(node))
            obs = ((r.get("decisions") or {}).get(got[0]) or {}) if got else {}
            if got and obs.get("state") == "evaluated":
                distance = min(md._distance(got[1], want, {j: bool(t) for j, (t, o) in
                                                           enumerate(zip(inst["truth"], inst["observed"], strict=True))
                                                           if o}) for inst in obs["instances"])
            elif got:
                distance = len(specs[got[0]]["atoms"]) + 1
        elif blocking is not None and blocking[0] in ("bound", "arith", "write", "flip"):
            distance = exposure_gap(r, blocking)
        return (False, depth, -distance)

    def exposure_gap(r, final) -> int:
        """(R79) How far a run that gets to a fault-exposing target is from it: the sides' difference, the operands'
        distance from non-degenerate, a write of the same value (1) or of an unknown one (2)."""
        if final[0] == "write":
            recs = _records(r, "writes", final[1])
            if any(a is not None and b is not None for a, b in recs):
                return 1
            return 2 if recs else _FAR
        if final[0] == "arith":
            return min((_arith_gap(final[2], x) for x in _records(r, "operands", final[1])), default=_FAR)
        if final[0] == "flip":
            # (R84) evaluated with a known outcome but not deciding (1), evaluated otherwise (2)
            if _records(r, "decides", final[1], size=3):
                return 1
            return 2 if _records(r, "operands", final[1]) else _FAR
        # the sides' difference on an evaluation where the condition decides; 1 more where it does not (yet)
        gaps = [abs(a - b) + (0 if d else 1) for a, b, d in _records(r, "decides", final[1], size=3)
                if a is not None and b is not None]
        return min(gaps, default=_FAR)

    def exposure_known(r, target) -> bool:
        """(R79) The run evaluated the target's site with what its judgment needs: both operands, or both the replaced
        and the written value."""
        if target[0] == "boundary":
            return any(a is not None and b is not None for a, b, _d in _records(r, "decides", target[3][1], size=3))
        if target[0] == "flip":
            return bool(_records(r, "decides", target[3][1], size=3))   # (R84) its outcome known on an evaluation
        field = "writes" if target[0] == "write" else "operands"
        return any(a is not None and b is not None for a, b in _records(r, field, target[3][1]))

    def exposure_inputs(target) -> list[str]:
        """(R79) The inputs to move at a fault-exposing target: those its statement / expression reads (through locals
        — every input when it reads none it can set), and for a comparison the decision's other conditions (that make
        it decide)."""
        kind, node, _chain, final = target
        if kind == "write":
            # (R82, review W-R6-2) the right side's reads but a written-only input (the function wrote over it first),
            #   else every input — the write's own prior value among them (its left side is no read of the statement)
            names = md._condition_inputs(node, raw, sources, input_set - written_only) or list(inputs)
        else:
            # (R82) a comparison or an operation never reads a written-only input — they move the others
            names = list(control_inputs_of(node))
        if kind in ("boundary", "flip") and final[2] in spec_cond:
            names = list(dict.fromkeys(names + list(control_inputs_of(spec_cond[final[2]]))))
        return names

    def measure(r, target):
        """(R79) ``(quantity, wanted)`` for the secant step: the sides' difference and 0, or the dividend and the
        nearest non-zero multiple of the divisor — None where the target has no such quantity on this run."""
        if target[0] == "boundary":
            recs = [(a, b) for a, b, _d in _records(r, "decides", target[3][1], size=3) if a is not None and b is not None]
            return (recs[0][0] - recs[0][1], 0) if recs else None
        recs = [(a, b) for a, b in _records(r, "operands", target[3][1]) if a is not None and b is not None]
        if not recs:
            return None
        left, right = recs[0]
        if target[3][2] in ("/", "%") and right != 0:
            return left, _multiple_near(left, right)
        return None

    def secant(cur: dict[str, int], r, target, names: list[str]) -> list[dict[str, int]]:
        """(R79) For each of the first inputs: one probe move (+1, else +16) measures how the watched quantity moves
        with it; the value that brings it to what the target needs (and its neighbours) are candidates."""
        m0 = measure(r, target)
        if m0 is None:
            return []
        e0, want = m0
        out: list[dict[str, int]] = []
        todo = list(names[:4])
        for delta in (1, 16):
            # (review R79 I6) one batch of probes per step size
            probes = {}
            for n in todo:
                x1 = cur[n] + delta if _inside(doms[n], cur[n] + delta) else cur[n] - delta
                if _inside(doms[n], x1):
                    probes[n] = {**cur, n: x1}
            run(list(probes.values()))
            for n, probe in probes.items():
                rr = cache.get(vkey(probe))
                m1 = measure(rr, target) if rr is not None and clean(rr) else None
                if m1 is None or m1[0] == e0:
                    continue
                slope = (m1[0] - e0) / (probe[n] - cur[n])
                x = cur[n] + round((want - e0) / slope)
                out += [{**cur, n: v} for v in (x, x - 1, x + 1) if v != cur[n] and _inside(doms[n], v)]
                todo.remove(n)
        return out

    def blocking_inputs(r, target) -> list[str]:
        """The inputs to move next: those of the first control step the best path does not satisfy (through the locals
        it reads) — every input when the run itself is the obstacle (undefined behaviour, a branch on an unknown value,
        an overflow it may hit): what causes that need not be on the target's control chain."""
        exposing = target[0] in EXPOSE_KINDS or target[0] == "flip"
        if r.get("status") != "supported" or (not exposing and touched(r, target)):
            return list(inputs)
        _depth, step = best_path(r, target)
        if step is None:
            return list(inputs)
        if exposing and step is target[3]:
            # (R79) the target's site runs: its own inputs — every input when the run itself is the obstacle
            return exposure_inputs(target) if clean(r) else list(inputs)
        if step[0] == "guard":
            node = step[1] if not isinstance(step[1], int) else conds[step[1]]
            return control_inputs_of(node)
        if step[0] == "case":
            sw = step[1].parent.parent if step[1].parent is not None else None
            c = sw.child_by_field_name("condition") if sw is not None and sw.type == "switch_statement" else None
            return control_inputs_of(c) if c is not None else list(inputs)
        return list(inputs)

    def prior_named(r, target) -> list:
        """(review R82 W-R6-1) The written-only inputs the step a climb is blocked at names — its guard, its switch, or
        the target's own comparison / operation."""
        if not written_only or r.get("status") != "supported":
            return []
        _depth, step = best_path(r, target)
        node = None
        if step is not None and step[0] == "guard":
            node = step[1] if not isinstance(step[1], int) else conds[step[1]]
        elif step is not None and step[0] == "case":
            sw = step[1].parent.parent if step[1].parent is not None else None
            node = sw.child_by_field_name("condition") if sw is not None and sw.type == "switch_statement" else None
        elif step is not None and target[0] in ("boundary", "arith", "flip") and step is target[3]:
            node = target[1]
        return [n for n in inputs_of(node) if n in written_only] if node is not None else []

    def outside(v) -> int:
        return sum(1 for k, x in v.items() if k in home and not _at_home(home[k], x))

    def quality(v, r) -> tuple:
        """Among vectors of equal standing: clean, more derived outputs, fewer values outside the home range, fewer
        extreme values, more operating values."""
        derived = sum(1 for o in (r.get("outputs") or {}).values() if "value" in o)
        extreme = sum(1 for k, x in v.items() if _extreme(doms[k], x))
        at_home = sum(1 for k, x in v.items() if x == defaults[k])
        return (clean(r), derived, -outside(v), -extreme, at_home)

    def score(v, target) -> tuple:
        r = cache[vkey(v)]
        return standing(r, target) + quality(v, r)

    def propagate_step(cur: dict[str, int], target) -> tuple[dict[str, int] | None, str]:
        """(R84) A vector whose site is exposed while no output changes: one input at a time — the others before the
        site's own (moving those may lose the exposure) —, all its candidates, the first input with a move that keeps
        the exposure and changes an output (of those, the best by `quality`). A masking value (`Diff = Assist - Start`
        with the two equal, a state already holding what the other branch writes) is one input away; two at once are
        not tried (``local_best``)."""
        own = set(exposure_inputs(target))
        order = [x for x in inputs if x not in own] + [x for x in inputs if x in own]
        # (review R84 I-R2-5) every input's moves that stay at home first, then those that leave it (the widened search
        #   — an FI row only where no in-design move propagates)
        for at_home in (True, False):
            for n in order:
                if exhausted():
                    report[flag[0]] = True
                    return None, "budget"
                # its candidates and small steps from where it is (`s32_DivRound`: `den` -1 → -2 makes `den / 2L` count)
                steps = [cur[n] + s * d for d in (1, 16) for s in (1, -1)]
                cands = [{**cur, n: x} for x in dict.fromkeys(pools[n] + [x for x in steps if _inside(doms[n], x)])
                         if x != cur[n] and (n not in home or _at_home(home[n], x)) == at_home]
                if not cands:
                    continue
                run(cands)
                prepare(cands, target)
                ok = [c for c in cands if vkey(c) in cache and reached(cache[vkey(c)], target)]
                if ok:
                    return max(ok, key=lambda v: quality(v, cache[vkey(v)])), "done"
        return None, ("budget" if exhausted() else "local_best")

    def climb(start: dict[str, int], target) -> tuple[dict[str, int] | None, str]:
        """``(vector, "done")`` or ``(None, why)`` — why: ``local_best`` (no single move of the inputs gets nearer),
        ``climb_cap`` (`MAX_CLIMB` moves), ``budget`` (the function's runs or steps are spent)."""
        cur = start
        for _ in range(MAX_CLIMB):
            r = cache[vkey(cur)]
            if standing(r, target)[0]:
                return cur, "done"
            if exhausted():
                report[flag[0]] = True
                return None, "budget"
            if propagate and infected(r, target):
                return propagate_step(cur, target)
            names = blocking_inputs(r, target)
            cands = [{**cur, n: x} for n in names for x in pools[n] if x != cur[n]]
            if target[0] in ("boundary", "arith") and clean(r) and best_path(r, target)[1] is target[3]:
                cands += secant(cur, r, target, names)
                if propagate and target[0] == "arith":
                    # (R84) an operand at the identity (`den / 2L` is 0 for den -1): small steps of what it reads, as a
                    #   write of the value already there takes below — the search before R84 is left as it was
                    cands += [{**cur, n: cur[n] + s * d} for n in names[:4] for d in (1, 4, 16, 64) for s in (1, -1)
                              if _inside(doms[n], cur[n] + s * d)]
            elif target[0] == "write" and clean(r) and best_path(r, target)[1] is target[3]:
                # (R79) a write of the value already there: a small step of an input it reads moves the written value
                #   off it (`475 - 30 * v / 100` is 100 at v = 1251, 99 at 1255) — nearer than any other candidate
                cands += [{**cur, n: cur[n] + s * d} for n in names[:4] for d in (1, 4, 16, 64) for s in (1, -1)
                          if _inside(doms[n], cur[n] + s * d)]
            run(cands)
            prepare(cands, target)
            pool = [cur] + [c for c in cands if vkey(c) in cache]
            best = max(pool, key=lambda v: score(v, target))
            if score(best, target) <= score(cur, target):
                # (review R82 W-R6-1) the written-only names the blocking step names, once — before giving up
                late = [n for n in prior_named(r, target) if n not in names]
                if late:
                    more = [{**cur, n: x} for n in late for x in pools[n] if x != cur[n]]
                    run(more)
                    prepare(more, target)
                    pool += [c for c in more if vkey(c) in cache]
                    best = max(pool, key=lambda v: score(v, target))
            if score(best, target) <= score(cur, target):
                return None, ("budget" if exhausted() else "local_best")
            cur = best
        return (cur, "done") if standing(cache[vkey(cur)], target)[0] else (None, "climb_cap")

    def polish(v: dict[str, int], target) -> dict[str, int]:
        """Values outside the home range moved back inside, and extreme values replaced by operating ones, where the target
        stays reached cleanly. A value moved home is kept even when fewer outputs derive — what is left outside is then
        what the target needs, as the row says (review R78 R2 W-R2-3); an extreme value is replaced only with no fewer
        derived outputs."""
        cur = v
        for name in inputs:
            if exhausted():
                break
            away = name in home and not _at_home(home[name], cur[name])
            if not away and not _extreme(doms[name], cur[name]):
                continue
            if away:
                # the home range's own points first, then the pool's home values — not only what the capped pool kept
                #   (review R78 R3 I-R3-5: with many outside comparisons the pool keeps one home value)
                h = home[name]
                if isinstance(h, list):
                    # (review R80 W-R3-1) a value set's own members — its middle first, then the others
                    # (review R80 I-R4-8) the pool's home members first (labels, compared constants), then the rest
                    pick = [x for x in dict.fromkeys([*(x for x in pools[name] if x in h), h[len(h) // 2], *h])
                            if _inside(doms[name], x)][:6]
                else:
                    lo, hi = h
                    # (review R80 W3) a list domain's own values only — an enumerator, not a value between them;
                    #   (W-R2-3) filtered before the cut, so a gap's middle does not take an enumerator's place
                    pick = [x for x in dict.fromkeys([(lo + hi) // 2, lo, hi, lo + 1, hi - 1,
                                                      *(x for x in pools[name] if lo <= x <= hi)])
                            if lo <= x <= hi and _inside(doms[name], x)][:6]
            else:
                pick = [x for x in pools[name][:4] if not _extreme(doms[name], x)]
            cands = [{**cur, name: x} for x in pick if x != cur[name]]
            run(cands)
            prepare(cands, target)
            ok = [c for c in cands if vkey(c) in cache and standing(cache[vkey(c)], target)[0]
                  and (away or quality(c, cache[vkey(c)]) >= quality(cur, cache[vkey(cur)]))]
            if ok:
                cur = ok[0]
        return cur

    def as_vector(e) -> dict[str, int]:
        """A suite row's values on the search's inputs, read as the rows hold them (``"0x1"`` for a bit/bool input —
        review R78 R2 C-R2-1: one reading, `boundary_rows._as_int`, for starts, duplicates and covered rows)."""
        out = {}
        for k, x in (e or {}).items():
            iv = _as_int(x)
            if k in doms and iv is not None:
                out[k] = iv
        return out

    v0 = dict(defaults)
    starts = [v0]
    seen_starts = {vkey(v0)}
    for e in existing or ():
        v = {**defaults, **{k: x for k, x in as_vector(e).items() if _inside(doms[k], x)}}
        if vkey(v) in seen_starts:
            continue
        if len(starts) >= MAX_STARTS + 1:
            report["starts_capped"] += 1
            continue
        seen_starts.add(vkey(v))
        starts.append(v)
    existing_keys = {vkey(as_vector(e)) for e in existing or ()}
    run(starts)
    rows: list[dict[str, Any]] = []
    held: list[dict[str, int]] = []    # vectors the suite holds after this search that reached targets
    done = [False] * len(targets)

    def mark(v):
        r = cache[vkey(v)]
        hit = []
        for i, t in enumerate(targets):
            if not done[i] and standing(r, t)[0]:
                done[i] = True
                hit.append(i)
        return hit

    prior, prior_keys = [], set()
    for c in covered or ():
        v = as_vector(c)
        if set(v) == set(doms) and vkey(v) not in prior_keys:
            prior_keys.add(vkey(v))
            prior.append(v)
    # the covered rows' runs check what the suite already reaches — they are no part of the search's budget (review
    #   R78 R2 I-R2-1: a unit of hundreds of rows spent it on them)
    before = nruns(), spent[0]
    run_budget[0] = None
    run(prior)
    masked_rows: dict[int, list] = {}   # (R84) target i → suite rows that expose its site without changing an output
    check_rest: dict[int, list] = {}    # (review R84 I-R2-1) target i → the exposing suite rows a capped check left
    late_met: set = set()               # (review R84 W-R3-1) targets a suite row met in that late check
    if not propagate:
        for v in prior:
            if vkey(v) in cache:
                mark(v)
    else:
        # (R84) per target: the suite rows that expose the site, in batches, until one changes an output — at most
        #   `MAX_PROPAGATE_CHECK` (the rest counted: the target is then searched though a later row might have met it)
        for i, t in enumerate(targets):
            cand = [v for v in prior if vkey(v) in cache and infected(cache[vkey(v)], t)]
            checked, capped = 0, False
            for start in range(0, len(cand), 16):
                if checked >= MAX_PROPAGATE_CHECK or perturbed[0] >= MAX_PROPAGATE_CHECK_RUNS or \
                        psteps[0] >= MAX_PROPAGATE_CHECK_STEPS:
                    capped = True
                    break
                chunk = cand[start:start + 16]
                prun(chunk, i)
                checked += len(chunk)
                if any(pcache.get((vkey(v), i)) for v in chunk):
                    done[i] = True
                    break
            # the rest — and (review R84 I-R3-1) the rows whose run the step cap stopped (not cached) — in the target's
            #   own search, first (its budget)
            stopped = [v for v in cand[:checked] if (vkey(v), i) not in pcache] if not done[i] else []
            if not done[i] and (capped or stopped):
                report["propagate_check_capped"] += 1
                check_rest[i] = stopped + cand[checked:]
            report["propagate_checked_rows"] += checked
            masked_rows[i] = [v for v in cand[:checked] if pcache.get((vkey(v), i)) == ()][:4]
    run_budget[0] = (nruns() - before[0], spent[0] - before[1])
    report["covered_before"] = sum(done[:n_reach])
    report["expose_covered_before"] = sum(done[n_reach:])

    why_of: dict[int, str] = {}
    cut_targets: set = set()
    duplicate_key = ["duplicates"]

    def search(i, target, row_cap) -> None:
        """One target: climbs from the best starts, then its row — or a duplicate, or cut by the row cap."""
        if propagate and check_rest.get(i):
            # (review R84 I-R2-1) the suite rows its capped check left, before any climb: a target a suite row meets is
            #   covered (no row — a re-search found such a row again and spent a row of the cap on it)
            rest = check_rest.pop(i)
            for start in range(0, len(rest), 16):
                if exhausted():
                    report[flag[0]] = True   # (review R84 I-R3-3)
                    break
                prun(rest[start:start + 16], i)
                if any(pcache.get((vkey(v), i)) for v in rest[start:start + 16]):
                    done[i] = True
                    late_met.add(i)
                    report["expose_covered_before"] += 1
                    report["propagate_check_late"] += 1
                    return
            masked_rows[i] = (masked_rows.get(i, []) + [v for v in rest if pcache.get((vkey(v), i)) == ()])[:4]
        # (review R79 I1) only the starts that ran: one the budget never ran has no standing to rank by
        # (R84) and the suite rows that already expose the site — one move from changing an output
        pool = [v for v in starts + [row["vector"] for row in rows] + masked_rows.get(i, []) if vkey(v) in cache]
        prepare(pool, target)
        # (review R84 C1) one vector once — in the propagating search only: before R84 a start equal to a row was climbed
        #   twice (the second a cached no-op), and taking a third start instead changed which targets a spent budget left
        ranked = sorted(({vkey(v): v for v in pool}.values() if propagate else pool), key=lambda v: score(v, target),
                        reverse=True)
        found, why = None, ("local_best" if ranked else "budget")
        for s in ranked[:3]:
            found, why = climb(s, target)
            if found is not None or why == "budget":
                break
        if found is None:
            why_of[i] = why
            return
        found = polish(found, target)
        if vkey(found) in existing_keys:
            report[duplicate_key[0]] += 1
            mark(found)
            held.append(found)
            return
        if sum(1 for row in rows if (row["target"] >= n_reach) == (i >= n_reach)) >= row_cap:
            cut_targets.add(i)   # found, but the row cap is full: the row is not added and the target stays unreached
            return
        rows.append({"vector": found, "target": i, "hit": mark(found)})
        held.append(found)

    for i, target in enumerate(targets[:n_reach]):
        if done[i]:
            continue
        if exhausted():
            report["budget_exhausted"] = True
            break
        # the row cap does not end the search: a target an existing row reaches costs no row, and the objects the runs
        #   towards the others read are still what the input completion needs (review R78 R3 W-R3-2)
        search(i, target, cap)
    reach_cut = [len(cache), spent[0]]
    reach_done = list(done)
    reach_runs = list(cache.values())
    refused = bool(reach_runs) and all(r.get("status") != "supported" for r in reach_runs)
    report["expose_met_by_reach_rows"] = sum(reach_done[n_reach:]) - report["expose_covered_before"]

    def never_recorded(target) -> bool:
        """(R79 review I-R2-1) An operator the model never records — in a macro's argument (its expansion is other
        text), on pointers: its statement runs on a clean path, its operands never come."""
        final = target[3]
        if propagate and final[0] in ("bound", "flip"):
            # (review R84 I2) a comparison evaluated on a clean run (its decision's instance observed it) whose operands
            #   never came — a pointer comparison (`p != NULL`): no perturbation of it is ever seen
            return not any(_records(r, "operands", final[1]) for r in cache.values()) and any(
                clean(r) and any(len(inst.get("observed") or ()) > final[3] and inst["observed"][final[3]]
                                 for inst in (((r.get("decisions") or {}).get(final[2]) or {}).get("instances") or ()))
                for r in cache.values())
        w = holder_of.get(final[1]) if final[0] == "arith" else None
        return w is not None and not any(_records(r, "operands", final[1]) for r in cache.values()) and any(
            clean(r) and any(True in p for p in ((r.get("reach") or {}).get(w) or [])) for r in cache.values())

    if len(targets) > n_reach and refused:
        # (R79 review W-R2-2) the oracle refused every reach run: the exposing targets are not searched either —
        #   counted as such (the unit's status says why)
        report["expose_refused"] = len(targets) - n_reach - sum(done[n_reach:])
    elif len(targets) > n_reach:
        # (R79) the fault-exposing targets: their own runs · steps · rows and duplicates, after every reach target. A
        #   reach target a row of this phase reaches is reached (the suite holds the row) and counted as such
        #   (`reached_by_exposing_rows` — review R79 W2b); the reach phase's classification below reads its own runs
        run_budget[0] = (nruns(), spent[0])
        limits[:] = [MAX_PROPAGATE_RUNS, MAX_PROPAGATE_STEPS] if propagate else [MAX_EXPOSE_RUNS, MAX_EXPOSE_STEPS]
        flag[0] = "expose_budget_exhausted"
        duplicate_key[0] = "expose_duplicates"
        n_rows, n_held = len(rows), len(held)
        try:
            for i in range(n_reach, len(targets)):
                target = targets[i]
                if done[i]:
                    continue
                if exhausted():
                    report["expose_budget_exhausted"] = True
                    break
                if (any(touched(r, target) for r in cache.values()) and not any(
                        exposure_known(r, target) for r in cache.values() if r.get("status") == "supported")) \
                        or never_recorded(target):
                    # its site runs, never with known operands / a known replaced value (an object no input sets — an
                    #   output only written; an operator the model does not record): no move tells, so no search
                    why_of[i] = "unmodeled"
                    continue
                search(i, target, MAX_PROPAGATE_ROWS if propagate else MAX_EXPOSE_ROWS)
        except Exception as exc:  # noqa: BLE001 — the exposing phase never costs the reach phase's rows (review R79 I1)
            _log.warning("fault-exposing search failed (%s): %s", unit.get("name"), exc, exc_info=True)
            report["expose_error"] = type(exc).__name__
            del rows[n_rows:]
            del held[n_held:]
            done[:] = reach_done
            for j in late_met:
                done[j] = True   # (review R84 W-R3-1) a suite row met it — no row of this phase, nothing to undo
            report["expose_duplicates"] = 0
            cut_targets.difference_update(range(n_reach, len(targets)))   # (review R79 I-R3-1) their rows are gone
            for j in range(n_reach, len(targets)):
                if not done[j] and why_of.get(j) != "unmodeled":
                    why_of[j] = "error"   # (review R79 I-R2-2) cut off by the error, not by a budget
    report["reached_by_exposing_rows"] = sum(1 for i in range(n_reach) if done[i] and not reach_done[i])
    # what is still unreached at the end, by why — once, after every row is in (review R78 R2 W-R2-5: a target a later
    #   row reached kept the reason counted when its own search failed). A target whose row the cap cut is `cut` first
    #   (its vector touched it — it is no unclean reach). The reach phase's runs only (review R79 W2b)
    unclean = 0
    for i, target in enumerate(targets[:n_reach]):
        if done[i]:
            continue
        if i in cut_targets:
            report["cut"] += 1
        elif any(touched(r, target) for r in reach_runs):
            unclean += 1   # reached, but never on one path without undefined behaviour
        elif refused:
            continue       # the status says why (review R78 R2 W-R2-6)
        elif i in why_of:
            report["budget_cut" if why_of[i] == "budget" else why_of[i]] += 1
        else:
            report["budget_cut"] += 1   # never searched: the budget ran out before its turn
    report["reached_clean"] = sum(done[:n_reach])
    report["reached_unclean_only"] = unclean
    report["not_reached"] = n_reach - sum(done[:n_reach]) - unclean
    report["rows"] = sum(1 for row in rows if row["target"] < n_reach)
    runs = list(cache.values())
    report["runs"] = sum(1 for r in runs[:reach_cut[0]] if r.get("reason") != "search_step_budget")   # (review R78 R2 I-R2-4)
    report["steps"] = reach_cut[1]
    # (R79) the fault-exposing targets
    report["expose_reached"] = sum(done[n_reach:])
    report["expose_rows"] = sum(1 for row in rows if row["target"] >= n_reach)
    report["expose_runs"] = sum(1 for r in runs[reach_cut[0]:] if r.get("reason") != "search_step_budget")
    report["expose_steps"] = spent[0] - reach_cut[1]
    for i in range(n_reach, len(targets)):
        if done[i]:
            continue
        report["expose_not_reached"] += 1
        if refused:
            continue                            # `expose_refused`
        if i in cut_targets:
            report["expose_cut"] += 1
        elif why_of.get(i) == "error":
            report["expose_error_cut"] += 1
        elif why_of.get(i) == "unmodeled":
            report["expose_unmodeled"] += 1
        elif why_of.get(i) in ("local_best", "climb_cap"):
            report["expose_local_best"] += 1   # a local best or the climb's move cap
            if propagate and any(infected(r, targets[i]) for r in cache.values()):
                # (R84; review W1) of those: some run exposed the site and no single move changed an output — not a
                #   target the row cap, the budget or an error cut
                report["propagate_infected_only"] += 1
        else:
            report["expose_budget_cut"] += 1
    if refused:
        # every run was refused — the first refusal names why (as the boundary search's `oracle_underived`); a refusal
        #   may be a per-run budget too (`execution_budget`), so this says "refused", not "cannot be searched"
        first = reach_runs[0]
        report["status"] = "oracle_unsupported:" + str(first.get("reason") or "")[:60]
    # objects the runs that got to a target not reached cleanly read with no value from the vector — the inputs the
    #   search would need (an object the input list leaves out: HDPDM01 `s_MoveStartClose_GainMeasure` reads the rear
    #   Close gain the SwUDS input table does not list); the SUTS input completion (R19) adds them and searches again
    needed: dict[str, int] = {}
    for i, target in enumerate(targets[:n_reach]):
        if done[i]:
            continue
        # (R81, review I4) a pointer parameter's pointee the run read (`@pointee:ctx[0].bitcount`) by the reference's name
        #   — the input completion keeps it only for this unit's pointer parameters (`_unit_object_decl`)
        # (R82) and what the guard a climb stopped at read with no value
        names = {m for r in reach_runs
                 for n in ((r.get("initial_reads") or ()) if touched(r, target) else blocked_reads(r, target))
                 for m in [str(n)[len("@pointee:"):] if str(n).startswith("@pointee:") else str(n)]
                 if (_NAME.fullmatch(m) or (str(n).startswith("@pointee:") and _POINTEE_NAME.fullmatch(m)))
                 and m not in doms}
        for n in names:
            needed[n] = needed.get(n, 0) + 1
    # (R82) a write no move can expose: it runs, but the value it replaces is never known — the object is no input (an
    #   output the function writes on every path). Deleting that write leaves the old value, which the suite then cannot
    #   tell from the new one (PV `s_MotorSpeedModeSelection_RearSet`: `s32s_StartSpeed = …` — the reference sets the
    #   object's value before the call). The object is what the search needs: the input completion adds it and the next
    #   round's exposing search picks a value the write changes. Kept apart from `needed_inputs`: the function writes the
    #   object there, it does not read it — no gap in the input list (`source_findings`), no read on the model
    prior_values: dict[str, int] = {}
    written_values: dict[str, set] = {}   # the values those writes put there — the prior value a row needs differs
    unnamed = 0
    # (review R82 I-R2-2) objects a test sets: the translation unit's (`g` · `g.a` · `a[k]`) and this function's pointer
    #   parameters' pointees (`p[0]…`) — an uninitialized local written is no prior value to ask for
    settable = set(scope.get("globals") or {}) | set(scope.get("arrays") or {}) | set(md._pointer_params(
        scope, str(unit.get("name") or "")))
    for i in range(n_reach, len(targets)):
        if done[i] or why_of.get(i) != "unmodeled" or targets[i][0] != "write":
            continue
        # (review R82 W8) only where the replaced value alone is missing: some run wrote a known value (a write whose new
        #   value is unknown too — `g_y = (U8)g_flt` — is not exposed by a prior value either)
        if not any(a is None and b is not None for r in cache.values() if r.get("status") == "supported"
                   for a, b in _records(r, "writes", targets[i][3][1])):
            continue
        name = _written_name(write_nodes[targets[i][3][1]], raw)
        if not name:
            unnamed += 1   # (review R82 W3) an index no constant names, a cast, a call … — counted, not silent
        elif name not in doms and (name in settable or re.split(r"[\[.]", name, maxsplit=1)[0] in settable):
            prior_values[name] = prior_values.get(name, 0) + 1
            written_values.setdefault(name, set()).update(
                b for r in cache.values() if r.get("status") == "supported"
                for a, b in _records(r, "writes", targets[i][3][1]) if a is None and b is not None)
    report["expose_prior_value_needed"] = sum(prior_values.values())
    report["expose_prior_value_unnamed"] = unnamed
    report["prior_value_needed"] = dict(sorted(prior_values.items()))
    # (R82 measurement: PV `g_UDS_LinComp_Reset` — its exposing search ran out of budget; the rows' fixed prior value 0
    #   was the value `u8g_SysUds_UsDoorCtrl = u8g_CLR` writes, so deleting that write showed nowhere)
    report["prior_value_written"] = {n: sorted(v) for n, v in sorted(written_values.items())}
    report["needed_inputs"] = dict(sorted(needed.items()))
    report["inputs_needed"] = len(needed)
    out = []
    for row in rows:
        kind, node, _steps, final = targets[row["target"]]
        r = cache[vkey(row["vector"])]
        entry = {"inputs": dict(row["vector"]), "target_kind": kind, "target_line": node.start_point[0] + 1,
                 "target_text": _line_text(node, raw), "target_outcome": final[2] if kind == "branch" else None,
                 # (review R79 W2a) the statements · branch outcomes it reached first; the exposing targets apart
                 "targets_reached": sum(1 for i in row["hit"] if i < n_reach),
                 "exposures_met": sum(1 for i in row["hit"] if i >= n_reach),
                 "outputs_derived": sum(1 for o in (r.get("outputs") or {}).values() if "value" in o)}
        if propagate:
            # (R84) the outputs the perturbed run changed — what a fault at the site changes on this row
            entry["propagated"] = list(pcache.get((vkey(row["vector"]), row["target"])) or ())
        if kind in EXPOSE_KINDS or kind == "flip":
            # (R79) the values that show it: the equal sides, the operands, the replaced and written values
            if kind == "boundary":
                ok = [x[:2] for x in _records(r, "decides", final[1], size=3) if x[0] is not None and x[0] == x[1] and x[2]]
            elif kind == "flip":
                ok = [x[:2] for x in _records(r, "decides", final[1], size=3) if x[2]]   # (R84) where it decides
            else:
                recs = _records(r, "writes" if kind == "write" else "operands", final[1])
                ok = [x for x in recs if (kind == "write" and x[0] is not None and x[1] is not None and x[0] != x[1])
                      or (kind == "arith" and _nondegenerate(final[2], x))]
            entry["exposure"] = list(ok[0]) if ok else None
            if kind == "arith":
                entry["operator"] = final[2]
        out.append(entry)
    return {"rows": out, "reached_vectors": [dict(v) for v in held], "report": report}
