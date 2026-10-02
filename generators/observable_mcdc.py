"""(R60, extended SUTS profile) MC/DC pairs whose two rows reach the decision as claimed and differ in an output the
function writes.

A unique-cause pair only flips the decision. When the logic after it hides the flip — an inner condition is false, a
later write overwrites the result — both rows give the same outputs, and a test with these rows cannot tell a wrong
operator in that condition from the right one (measured, R56 HDPDM01: 244 of 800 retained pairs had equal derived
outputs on both rows; the reference SUTS killed operator mutants in exactly such gates, e.g. the nine-condition
``s_DoorState_AutoStop_Detection`` guard). This is the observability idea of Observable MC/DC (Whalen et al.,
ICSE 2013), measured on the source oracle instead of proven along a propagation path.

A pair is **observable** when (1) on the modeled run each of its two rows evaluates the decision with the truth values
and outcome the pair claims (`c_source_oracle.observe_decisions` — for a decision designed on its expression too: the
expression design does not check that the decision is reached, review R60 round 3 W2), and (2) the rows differ in a
**written output**: stated by both rows, derived on both, different values, written by at least one of the two runs
(``basis == "assigned"`` — an output neither run wrote only echoes its input, review R60 C1), and not a copy of an
input the two rows set differently (each row's value equals that row's value of one such input — an edge-detect latch
``u8s_Old = u8g_Sw`` differs whenever its input does, round 2 W1). The copy rule cannot tell a latch from a 0/1 flag
that happens to equal a moved 0/1 input: such a pair is reported as ``copy_only``, not counted as observable (round 3
W1). Even an observable pair does not attribute the difference to the decision (no path proof): it is a necessary
condition for an operator in the condition to show, not a sufficient one.

For each retained pair that is not observable, search a second pair for the same condition: keep the inputs on which
the decision depends at the pair's values — an expression-designed decision: exactly the inputs its expression reads
(`decision["variables"]`); a decision designed on the modeled run: the inputs where the pair's two rows differ — and
take the other inputs from another row of the same test case (boundary-row base order; values inside the boundary
domains; a blank cell may be filled). The first candidate that is observable as defined above becomes two extended
rows. The pair the reference-size slots hold is never changed.

Budgets are deterministic: ``MAX_CANDIDATES`` overlays per pair, ``MAX_EVALUATIONS`` oracle vectors per function
(output evaluations and model re-checks alike, the re-check at the oracle's default step limit).
"""
from __future__ import annotations

from typing import Any

from generators.boundary_rows import _as_int
from generators.c_source_oracle import evaluate_outputs, scope_matches

MAX_CANDIDATES = 48
MAX_EVALUATIONS = 2000
# observable · searched (a found pair, rows added or reused) · copy_only (the only written differences seen were copies of
# a moved input) · masked (candidates derived, no written difference) · underived (no candidate derived an output on
# both rows) · recheck_refused (rows did differ, but the model did not confirm the decision as the pair claims — it
# evaluated it otherwise, or could not tell: path-dependent, undetermined, budget — review R60 round 4 W2) ·
# no_candidate (no other row offers a value inside the domain for an input the overlay may move) · budget_exhausted ·
# not_checked (reason) · evidence_mismatch (set later by the caller's confirmation)
STATUSES = ("observable", "searched", "copy_only", "masked", "underived", "recheck_refused", "no_candidate",
            "budget_exhausted", "not_checked", "evidence_mismatch")
# why a searched pair's own rows were not observable
OWN_ROWS = ("equal", "underived", "copy_only", "unreached")


class _Stop(Exception):
    pass


def vector_key(inputs: dict[str, Any]) -> tuple | None:
    """The integer input vector of a row (None when a cell is not an integer) — the one key for 'the same row' (review
    R60 round 3 W3: the search keyed rows by integers, the reuse by formatted JSON — ``1`` vs ``"0x1"``)."""
    out = []
    for k, v in (inputs or {}).items():
        n = _as_int(v)
        if n is None:
            return None
        out.append((k, n))
    return tuple(sorted(out))


def _slots(result: dict[str, Any], outputs: list[str]) -> tuple:
    """Per output ``(value, basis)`` when derived, else None."""
    out = result.get("outputs") or {}
    return tuple(((out.get(o) or {}).get("value"), (out.get(o) or {}).get("basis")) if "value" in (out.get(o) or {})
                 else None for o in outputs)


def written_difference(a: tuple, b: tuple, outputs: list[str], stated: set[str],
                       inputs_a: dict[str, Any], inputs_b: dict[str, Any], copies: list[str] | None = None) -> list[str]:
    """Outputs stated by both rows, derived on both, with different values, written by at least one of the two runs and
    not a copy of an input the two rows set differently (those are appended to ``copies``). The one judgment for the
    search and the confirmation (review R60 round 2 W4)."""
    moved = [k for k in set(inputs_a) | set(inputs_b) if inputs_a.get(k) != inputs_b.get(k)]
    out = []
    for name, x, y in zip(outputs, a, b, strict=True):
        if name not in stated or x is None or y is None or x[0] == y[0]:
            continue
        if x[1] == "unchanged_input" and y[1] == "unchanged_input":
            continue   # an echo of the inputs the two rows set — not what the function did (review R60 C1)
        if any(x[0] == inputs_a.get(k) and y[0] == inputs_b.get(k) for k in moved):
            if copies is not None:
                copies.append(name)
            continue   # a copy of a moved input (latch) — differs whatever the decision did (round 2 W1)
        out.append(name)
    return out


def evidence_slots(seq: dict[str, Any], outputs: list[str]) -> tuple:
    """A row's derived ``(value, basis)`` per output from its attached evidence (the same shape as an oracle run)."""
    ev = seq.get("expected_evidence") or {}
    exp = seq.get("expected") or {}
    out = []
    for o in outputs:
        item = ev.get(o) or {}
        out.append((_as_int(exp.get(o)), item.get("basis")) if item.get("status") == "derived"
                   and _as_int(exp.get(o)) is not None else None)
    return tuple(out)


def rows_differ(a: dict[str, Any], b: dict[str, Any], copies: list[str] | None = None) -> list[str]:
    """The written outputs two attached rows differ in — `written_difference` over their stated outputs."""
    stated = set(a.get("expected") or {}) & set(b.get("expected") or {})
    names = sorted(stated)
    ia = {k: _as_int(v) for k, v in (a.get("inputs") or {}).items()}
    ib = {k: _as_int(v) for k, v in (b.get("inputs") or {}).items()}
    return written_difference(evidence_slots(a, names), evidence_slots(b, names), names, stated, ia, ib, copies)


def _both_derived(a: dict[str, Any], b: dict[str, Any]) -> bool:
    names = sorted(set(a.get("expected") or {}) & set(b.get("expected") or {}))
    return any(x is not None and y is not None for x, y in zip(evidence_slots(a, names), evidence_slots(b, names),
                                                                strict=True))


def find_observable_pairs(unit: dict[str, Any], sequences: list[dict[str, Any]], outputs: list[str],
                          domains: dict[str, Any], bases: list[dict[str, Any]], *,
                          max_candidates: int = MAX_CANDIDATES, max_evaluations: int = MAX_EVALUATIONS,
                          stated_of: dict[tuple, set] | None = None) -> dict[str, Any]:
    """``{"marks": [(pair, mark)], "rows": [{"pair", "decision", "role", "inputs", "mark", "base"}], "report": {...}}`` —
    nothing is written to the unit here (the caller applies the marks after the rows exist).

    ``domains``: the boundary-row domains — an overlay value outside its input's domain (a ``BV_*_INV`` row) is not
    used. ``bases``: rows in priority order whose inputs are overlay sources. Every retained pair gets a mark, also when
    the unit cannot be searched (``not_checked`` with the reason), so the counts add up to the retained pairs.
    ``stated_of``: an existing row's outputs by `vector_key` — a candidate equal to that row becomes that row, so only
    what it states can count (review R60 round 2 W4). The pair's own rows are judged from their attached evidence.
    """
    report = {"pairs": 0, "evaluations": 0, "evaluation_budget_exhausted": False, "rows": 0,
              **{s: 0 for s in STATUSES}, "searched_own_rows": {k: 0 for k in OWN_ROWS}}
    design = unit.get("mcdc_design") or {}
    retained = [(d, p) for d in design.get("decisions") or [] for p in d.get("pairs") or []
                if p.get("retained_status") == "retained"]
    why_not = "no_outputs" if not outputs else ("no_project_scope" if not unit.get("source_text")
                                                 or not scope_matches(unit) else "")
    if why_not:
        marks = [(p, {"status": "not_checked", "reason": why_not}) for _d, p in retained]
        report.update(pairs=len(marks), not_checked=len(marks), status=why_not)
        return {"marks": marks, "rows": [], "report": report}
    by_seq = {s.get("seq_num"): s for s in sequences}
    memo: dict[tuple, tuple] = {}
    budget = [max_evaluations]

    def charge(n: int) -> None:
        if budget[0] < n:
            report["evaluation_budget_exhausted"] = True
            raise _Stop
        budget[0] -= n
        report["evaluations"] += n

    def run(vectors: list[dict[str, int]]) -> list[tuple]:
        todo = list({tuple(sorted(v.items())): v for v in vectors if tuple(sorted(v.items())) not in memo}.items())
        if todo:
            charge(len(todo))
            for (k, _v), r in zip(todo, evaluate_outputs(unit, [v for _k, v in todo], [outputs] * len(todo)),
                                  strict=True):
                memo[k] = _slots(r, outputs)
        return [memo[tuple(sorted(v.items()))] for v in vectors]

    confirmed: dict[tuple, bool] = {}

    def reaches_as_claimed(decision: dict[str, Any], pair: dict[str, Any], vectors: tuple) -> bool:
        """Does each row evaluate the decision on the modeled run as the pair claims (truth values and outcome)? A row
        the model cannot judge counts as not confirmed. Memoised per (decision, row, claim) — the pairs of one decision
        share rows (review R60 round 4 I2)."""
        from generators import c_source_oracle as cso
        spec = decision.get("path_spec") or decision.get("reach_spec")
        claims = []
        for side, vec in zip(("a", "b"), vectors, strict=True):
            claimed = {"truth": list(pair.get(f"truth_{side}") or []), "observed": list(pair.get(f"observed_{side}") or []),
                       "decision": pair.get(f"decision_{side}")}
            claims.append(((id(decision), tuple(sorted(vec.items())), repr(claimed)), vec, claimed))
        todo = [(k, vec, c) for k, vec, c in claims if k not in confirmed]
        if todo:
            charge(len(todo))
            # the default step limit, as finalize's revalidation (round 2 W2: a smaller cap refused heavy functions)
            runs = cso.observe_decisions(unit, [vec for _k, vec, _c in todo], [spec], inert_stub_calls=str(
                decision.get("static_reason") or "").startswith("unsupported_scalar:call_expression"))
            for (k, _vec, claimed), r in zip(todo, runs, strict=True):
                s = (r or {}).get("decisions", {}).get(0) or {}
                confirmed[k] = bool(r and r.get("status") == "supported" and s.get("state") == "evaluated"
                                    and claimed in s["instances"])
        return all(confirmed[k] for k, _v, _c in claims)

    def ints(vector: dict[str, Any] | None) -> dict[str, int] | None:
        out: dict[str, int] = {}
        for k, v in (vector or {}).items():
            n = _as_int(v)
            if n is None:
                return None
            out[k] = n
        return out

    def inside(name: str, value: int) -> bool:
        dom = domains.get(name)
        if isinstance(dom, tuple):
            return dom[0] <= value <= dom[1]
        if isinstance(dom, (list, set, frozenset)):
            return value in dom
        return False

    overlays_src = [(b.get("seq_num"), ints(b.get("inputs") or {})) for b in bases]
    every = set(outputs)
    marks: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rows: list[dict[str, Any]] = []
    for decision, pair in retained:
        report["pairs"] += 1
        path = decision.get("evaluation") == "source_path"
        variables = None if path else decision.get("variables")
        ra, rb = by_seq.get(pair.get("seq_a")), by_seq.get(pair.get("seq_b"))
        a = ints(ra.get("inputs")) if ra is not None else None
        b = ints(rb.get("inputs")) if rb is not None else None
        reason = ("rows_or_variables_unknown" if a is None or b is None or (not path and variables is None)
                  else "pair_within_one_row" if pair.get("seq_a") == pair.get("seq_b")
                  # (review R60 W4) two evaluations of one run (a loop): no overlay can separate them
                  else "no_reach_spec" if not (decision.get("path_spec") or decision.get("reach_spec")) else "")
        if reason:
            marks.append((pair, {"status": "not_checked", "reason": reason}))
            report["not_checked"] += 1
            continue
        try:
            copies: list[str] = []
            changed = rows_differ(ra, rb, copies)
            # a pair designed on the modeled run was confirmed on exactly these rows by finalize's revalidation (retained
            #   means confirmed); an expression-designed pair never was (round 4 I1)
            if changed and (path or reaches_as_claimed(decision, pair, (a, b))):
                marks.append((pair, {"status": "observable", "seq_a": pair["seq_a"], "seq_b": pair["seq_b"],
                                     "outputs_changed": changed}))
                report["observable"] += 1
                continue
            own = ("unreached" if changed else "copy_only" if copies
                   else "equal" if _both_derived(ra, rb) else "underived")
            copy_seen = bool(copies) and not changed
            derived = False
            refused = bool(changed)   # the own rows differed but were not confirmed (round 4 I5: not 'copy only')
            fixed = set(variables or ()) if not path else {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
            seen: set[tuple] = set()
            found = None
            tried = 0
            for src, values in overlays_src:
                if tried >= max_candidates:
                    break
                if values is None or src in (pair["seq_a"], pair["seq_b"]):
                    continue
                # (review R60 I3) a blank cell of the pair's rows may be filled from the base row
                overlay = {k: v for k, v in values.items() if k not in fixed and inside(k, v) and a.get(k) != v}
                okey = tuple(sorted(overlay.items()))
                if not overlay or okey in seen:
                    continue
                seen.add(okey)
                tried += 1
                a2, b2 = {**a, **overlay}, {**b, **overlay}
                s2a, s2b = run([a2, b2])
                derived = derived or any(x is not None and y is not None for x, y in zip(s2a, s2b, strict=True))
                stated = every & (stated_of or {}).get(vector_key(a2), every) & (stated_of or {}).get(vector_key(b2), every)
                cand_copies: list[str] = []
                changed2 = written_difference(s2a, s2b, outputs, stated, a2, b2, cand_copies)
                if not changed2:
                    copy_seen = copy_seen or bool(cand_copies)
                    continue
                if not reaches_as_claimed(decision, pair, (a2, b2)):
                    refused = True
                    continue
                found = (a2, b2, changed2, src, sorted(overlay))
                break
        except _Stop:
            marks.append((pair, {"status": "budget_exhausted"}))
            report["budget_exhausted"] += 1
            continue
        if found is None:
            status = ("recheck_refused" if refused else "copy_only" if copy_seen else "no_candidate" if not tried
                      else "masked" if derived else "underived")
            marks.append((pair, {"status": status, "own_rows": own, "candidates_tried": tried}))
            report[status] += 1
            continue
        a2, b2, changed2, src, moved = found
        mark = {"status": "searched", "own_rows": own, "outputs_changed": changed2, "overlay_from_sequence": src,
                "overlay_inputs": moved, "candidates_tried": tried, "evaluation": "source_path" if path else "expression"}
        marks.append((pair, mark))
        report["searched"] += 1
        report["searched_own_rows"][own] += 1
        for role, vec in (("a", a2), ("b", b2)):
            rows.append({"pair": pair, "decision": decision, "role": role, "inputs": vec, "base": src, "mark": mark})
    return {"marks": marks, "rows": rows, "report": report}
