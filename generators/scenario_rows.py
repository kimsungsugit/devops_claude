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

Budgets per function (runs · interpreter steps · rows · candidates per input · climb moves · climb starts) are counted
in the report when they cut.
"""
from __future__ import annotations

import re
from typing import Any

from generators import c_project_context as cpc
from generators import mcdc_design as md
from generators.boundary_rows import _as_int
from generators.c_source_oracle import Unsupported, _parsed_function, observe_decisions, scope_matches

SCENARIO_PREFIX = "SCN_"
SCENARIO_FI_PREFIX = "SCNR_"   # a scenario only values outside the design range reach (FI — the SUTS caller's second search)
MAX_ROWS = 16            # scenario rows per function and search
MAX_RUNS = 800           # oracle runs per function and search
MAX_STEPS = 1_500_000    # interpreter steps per function and search (summed over the runs)
MAX_POOL = 12            # candidate values per input
MAX_STARTS = 24          # existing rows tried as climb starts
MAX_CLIMB = 24           # moves per climb
MAX_ATOMS = 16           # conditions of a control condition read as sub-conditions (more: outcome only)
_FREE_SPAN = 80


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


def _extreme(domain, v: int) -> bool:
    """A type end / far value of a wide range — the values the search takes last and polishes away."""
    if isinstance(domain, list):
        return False
    lo, hi = domain
    return hi - lo > 255 and (v in (lo, hi) or abs(v) >= 16384)


_COMPARISONS = frozenset({"<", "<=", ">", ">=", "==", "!="})
# a program object a run read (``g`` · ``g.a.b`` · ``g[2]``) — the oracle's other read marks (``@…``) are not names
_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\[\d+\])?")


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
    for n in md._walk(fn.child_by_field_name("body")):
        op = n.child_by_field_name("operator") if n.type == "binary_expression" else None
        if op is None or md._text(op, raw) not in _COMPARISONS:
            continue
        left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
        for a, b in ((left, right), (right, left)):
            x = _strip(a)
            if x is None or x.type != "subscript_expression" or (arg := md._array_name_node(x)) is None:
                continue
            k = md._index_value(x.child_by_field_name("index"), raw, constants, widths)
            name = f"{md._text(arg, raw)}[{k}]"
            value = _constant(b, raw, constants, widths) if k is not None and name in inputs else None
            if value is not None:
                out.setdefault(name, set()).add(value)
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


def _line_text(node, raw) -> str:
    return " ".join(md._text(node, raw).split())[:80]


def find_scenarios(unit: dict[str, Any], domains: dict[str, Any], outputs: list[str],
                   existing: list[dict[str, Any]] | None = None,
                   covered: list[dict[str, Any]] | None = None,
                   home: dict[str, tuple] | None = None) -> dict[str, Any]:
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
    of the suite instead)."""
    report = {"status": "searched", "targets": 0, "statements": 0, "branches": 0, "reached_clean": 0,
              "reached_unclean_only": 0, "not_reached": 0, "local_best": 0, "climb_cap": 0, "budget_cut": 0,
              "runs": 0, "steps": 0, "rows": 0, "cut": 0, "duplicates": 0, "budget_exhausted": False,
              "pools_capped": 0, "inputs": 0, "covered_before": 0, "starts_capped": 0, "conditions_outcome_only": 0,
              "needed_inputs": {}, "inputs_needed": 0}
    empty: dict[str, Any] = {"rows": [], "reached_vectors": []}
    if not unit.get("source_text") or not scope_matches(unit):
        return {**empty, "report": {**report, "status": "no_project_scope"}}
    doms = {k: d for k, v in domains.items() if (d := _norm(v)) is not None}
    if not doms:
        return {**empty, "report": {**report, "status": "no_integer_inputs"}}
    cap = MAX_ROWS
    home = {k: tuple(v) for k, v in (home or {}).items() if k in doms and isinstance(doms[k], tuple)}
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
    specs, spec_of = [], {}
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
    targets = []   # (kind, node, chain, final) — final: ("reach", watch i) or ("guard", cond i, outcome)
    for s in statements:
        targets.append(("statement", s, md.control_steps(s, cases=True), ("reach", watch_index[_key(s)])))
    for c in conds:
        for outcome in (True, False):
            targets.append(("branch", c, md.control_steps(c.parent, cases=True) + [("guard", c, outcome)],
                            ("guard", cond_index[_key(c)], outcome)))
    report.update(targets=len(targets), statements=len(statements), branches=2 * len(conds))
    if not targets:
        return {**empty, "report": {**report, "status": "no_targets"}}

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

    guards = [list(_key(c)) for c in conds]
    reach_keys = [list(_key(n)) for n in watch]
    cache: dict[tuple, dict] = {}
    spent = [0]

    def vkey(v):
        return tuple(sorted(v.items()))

    run_budget: list = [(0, 0)]   # runs · steps that do not count (the covered rows' check); None while it runs

    def exhausted() -> bool:
        if run_budget[0] is None:
            return False
        return len(cache) - run_budget[0][0] >= MAX_RUNS or spent[0] - run_budget[0][1] >= MAX_STEPS

    def run(vectors: list[dict[str, int]]) -> None:
        todo = list({vkey(v): v for v in vectors if vkey(v) not in cache}.values())
        try:
            for start in range(0, len(todo), 16):
                if exhausted():
                    report["budget_exhausted"] = True
                    return
                runs_left, steps_left = ((16, None) if run_budget[0] is None else
                                         (MAX_RUNS - (len(cache) - run_budget[0][0]),
                                          max(0, MAX_STEPS - (spent[0] - run_budget[0][1]))))
                chunk = todo[start:start + min(16, runs_left)]
                results = observe_decisions(unit, chunk, specs, guards, step_limit=steps_left,
                                            reach=reach_keys, outputs=list(outputs))
                for v, r in zip(chunk, results, strict=True):
                    cache[vkey(v)] = r
                    spent[0] += int(r.get("steps") or 0)
        finally:
            report["runs"], report["steps"] = len(cache), spent[0]

    def clean(r) -> bool:
        return r.get("status") == "supported" and not r.get("forked") and not r.get("possible_undefined_behavior")

    def event(r, step, path) -> bool:
        """Does path ``path`` of run ``r`` satisfy one control step / final event?"""
        kind = step[0]
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
        if final[0] == "reach":
            return any(p for p in ((r.get("reach") or {}).get(final[1]) or []))
        return any(final[2] in p or None in p for p in ((r.get("guards") or {}).get(final[1]) or []))

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

    def reached(r, target) -> bool:
        """The target's final event on a path whose control chain holds, in a clean run."""
        if not clean(r):
            return False
        chain, final = target[2], target[3]
        return any(len(chain) == sum(1 for _ in _prefix(r, chain, p)) and event(r, final, p)
                   for p in range(max(paths_of(r), 1)))

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
        return (False, depth, -distance)

    def blocking_inputs(r, target) -> list[str]:
        """The inputs to move next: those of the first control step the best path does not satisfy (through the locals
        it reads) — every input when the run itself is the obstacle (undefined behaviour, a branch on an unknown value,
        an overflow it may hit): what causes that need not be on the target's control chain."""
        if r.get("status") != "supported" or touched(r, target):
            return list(inputs)
        _depth, step = best_path(r, target)
        if step is None:
            return list(inputs)
        if step[0] == "guard":
            node = step[1] if not isinstance(step[1], int) else conds[step[1]]
            return inputs_of(node)
        if step[0] == "case":
            sw = step[1].parent.parent if step[1].parent is not None else None
            c = sw.child_by_field_name("condition") if sw is not None and sw.type == "switch_statement" else None
            return inputs_of(c) if c is not None else list(inputs)
        return list(inputs)

    def outside(v) -> int:
        return sum(1 for k, x in v.items() if k in home and not home[k][0] <= x <= home[k][1])

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

    def climb(start: dict[str, int], target) -> tuple[dict[str, int] | None, str]:
        """``(vector, "done")`` or ``(None, why)`` — why: ``local_best`` (no single move of the inputs gets nearer),
        ``climb_cap`` (`MAX_CLIMB` moves), ``budget`` (the function's runs or steps are spent)."""
        cur = start
        for _ in range(MAX_CLIMB):
            r = cache[vkey(cur)]
            if standing(r, target)[0]:
                return cur, "done"
            if exhausted():
                report["budget_exhausted"] = True
                return None, "budget"
            names = blocking_inputs(r, target)
            cands = [{**cur, n: x} for n in names for x in pools[n] if x != cur[n]]
            run(cands)
            pool = [cur] + [c for c in cands if vkey(c) in cache]
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
            away = name in home and not home[name][0] <= cur[name] <= home[name][1]
            if not away and not _extreme(doms[name], cur[name]):
                continue
            if away:
                # the home range's own points first, then the pool's home values — not only what the capped pool kept
                #   (review R78 R3 I-R3-5: with many outside comparisons the pool keeps one home value)
                lo, hi = home[name]
                pick = list(dict.fromkeys([(lo + hi) // 2, lo, hi, lo + 1, hi - 1,
                                           *(x for x in pools[name] if lo <= x <= hi)]))[:6]
                pick = [x for x in pick if lo <= x <= hi]
            else:
                pick = [x for x in pools[name][:4] if not _extreme(doms[name], x)]
            cands = [{**cur, name: x} for x in pick if x != cur[name]]
            run(cands)
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
    before = len(cache), spent[0]
    run_budget[0] = None
    run(prior)
    run_budget[0] = (len(cache) - before[0], spent[0] - before[1])
    for v in prior:
        if vkey(v) in cache:
            mark(v)
    report["covered_before"] = sum(done)

    why_of: dict[int, str] = {}
    cut_targets: set = set()
    for i, target in enumerate(targets):
        if done[i]:
            continue
        if exhausted():
            report["budget_exhausted"] = True
            break
        # the row cap does not end the search: a target an existing row reaches costs no row, and the objects the runs
        #   towards the others read are still what the input completion needs (review R78 R3 W-R3-2)
        ranked = sorted(starts + [row["vector"] for row in rows], key=lambda v: score(v, target), reverse=True)
        found, why = None, "local_best"
        for s in ranked[:3]:
            found, why = climb(s, target)
            if found is not None or why == "budget":
                break
        if found is None:
            why_of[i] = why
            continue
        found = polish(found, target)
        if vkey(found) in existing_keys:
            report["duplicates"] += 1
            mark(found)
            held.append(found)
            continue
        if len(rows) >= cap:
            cut_targets.add(i)   # found, but the row cap is full: the row is not added and the target stays unreached
            continue
        rows.append({"vector": found, "target": i, "hit": mark(found)})
        held.append(found)
    # what is still unreached at the end, by why — once, after every row is in (review R78 R2 W-R2-5: a target a later
    #   row reached kept the reason counted when its own search failed). A target whose row the cap cut is `cut` first
    #   (its vector touched it — it is no unclean reach)
    refused = bool(cache) and all(r.get("status") != "supported" for r in cache.values())
    unclean = 0
    for i, target in enumerate(targets):
        if done[i]:
            continue
        if i in cut_targets:
            report["cut"] += 1
        elif any(touched(r, target) for r in cache.values()):
            unclean += 1   # reached, but never on one path without undefined behaviour
        elif refused:
            continue       # the status says why (review R78 R2 W-R2-6)
        elif i in why_of:
            report["budget_cut" if why_of[i] == "budget" else why_of[i]] += 1
        else:
            report["budget_cut"] += 1   # never searched: the budget ran out before its turn
    report["reached_clean"] = sum(done)
    report["reached_unclean_only"] = unclean
    report["not_reached"] = len(targets) - sum(done) - unclean
    report["rows"] = len(rows)
    report["runs"] = sum(1 for r in cache.values() if r.get("reason") != "search_step_budget")   # (review R78 R2 I-R2-4)
    if refused:
        # every run was refused — the first refusal names why (as the boundary search's `oracle_underived`); a refusal
        #   may be a per-run budget too (`execution_budget`), so this says "refused", not "cannot be searched"
        first = next(iter(cache.values()))
        report["status"] = "oracle_unsupported:" + str(first.get("reason") or "")[:60]
    # objects the runs that got to a target not reached cleanly read with no value from the vector — the inputs the
    #   search would need (an object the input list leaves out: HDPDM01 `s_MoveStartClose_GainMeasure` reads the rear
    #   Close gain the SwUDS input table does not list); the SUTS input completion (R19) adds them and searches again
    needed: dict[str, int] = {}
    for i, target in enumerate(targets):
        if done[i]:
            continue
        names = {n for r in cache.values() if touched(r, target) for n in (r.get("initial_reads") or ())
                 if _NAME.fullmatch(str(n)) and n not in doms}
        for n in names:
            needed[n] = needed.get(n, 0) + 1
    report["needed_inputs"] = dict(sorted(needed.items()))
    report["inputs_needed"] = len(needed)
    out = []
    for row in rows:
        kind, node, _steps, final = targets[row["target"]]
        out.append({"inputs": dict(row["vector"]), "target_kind": kind, "target_line": node.start_point[0] + 1,
                    "target_text": _line_text(node, raw), "target_outcome": final[2] if kind == "branch" else None,
                    "targets_reached": len(row["hit"]),
                    "outputs_derived": sum(1 for o in (cache[vkey(row["vector"])].get("outputs") or {}).values()
                                           if "value" in o)})
    return {"rows": out, "reached_vectors": [dict(v) for v in held], "report": report}
