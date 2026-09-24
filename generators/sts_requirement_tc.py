"""Requirement boundary test cases for STS (R6, P3/G4) — built from the requirement text alone.

`generators/requirement_oracle.py` reads a requirement's own sentences into facts (``u16g_ApiIn_Vsup: 1604 초과``,
``Battery 전압이 8.5V미만``, ``특정시간(300ms)초과하여 유지``). For each parsed threshold or hold time this module writes
one test step per stimulus point around it:

* threshold ``subject op v``: ``v − δ``, ``v``, ``v + δ`` — the points where ``<`` and ``<=`` (``>`` and ``>=``) differ
  and where ``v`` moved by one step would change the verdict;
* hold time ``≥ t``: the condition lasting ``t − δ``, ``t``, ``t + δ``.

``δ`` is **one unit of the precision the value is written with** (``8.5`` → ``0.1``, ``4.00`` → ``0.01``,
``1604``/``0x1FF0`` → ``1``): the requirement states no tolerance or resolution, so none is invented — the step is
disclosed as ``written_precision`` per fact.

**What is set**: the subject the requirement compares. For ``Param_X( 3도 ) 초과한 열림각`` that is the opening angle
(``열림각 = 2도``, with ``Param_X = 3도`` as the reference) — never the constant itself; a parameter threshold whose
compared quantity the sentence does not name is not stepped. A hold time is the condition's duration (``LIN 통신 지속
시간 = 14초 (끊길 상태)``); a named time constant is its reference.

**The verdict** of each step is the one **the sentence** gives at that point: every condition of the line on the same
subject, joined by the words between them (``4.00V 이하 또는 4.74V 이상`` at 5 V: the second holds → the behaviour
the sentence describes happens). A point where the sentence's condition does not hold is *not in that sentence's
scope* — it is not claimed that the requirement does nothing there (another sentence of the same requirement may cover
it: ``3km/h 이하`` / ``3km/h 초과`` — review round 3 C-1). Conditions on other subjects are held false when joined
by *or*, true when joined by *and* (a hold time is always *and*); a join the words do not state — also with the next or
previous line — is left to the tester ("결합 조건 확인 필요"). A fact with such conditions gets a TC of its own, so its
precondition never contradicts another fact's steps. Not turned into steps, each with its reason: a fact without a
subject, a non-numeric comparison, a range, an operator that is not an order comparison, a negated clause (``… 아닌
경우``), a response constraint (``100ms 이내``), an outcome (``<완료조건>`` / ``<Output>`` sections), a label that names
a reference (``기준 전압: …``), a same-subject join the line does not state, a raw value outside the width the subject's
name declares (``u8g_X 45000 이상``), and a sentence already written.
"""
from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Any

from generators.requirement_oracle import (
    condition_part_join,
    exact_value,
    extract,
    is_outcome_section,
    joint,
    line_holds,
    same_subject,
    subject_of,
    written_step,
)

_ORDER = {"<", "<=", ">", ">="}
_OP_TEXT = {"<": "미만", "<=": "이하", ">": "초과", ">=": "이상", "==": "와 같음", "!=": "이 아님"}
ACTION_PREFIX = "입력 설정 (요구 경계): "   # the STS step classifier reads this as boundary value analysis (BAA)
BASIS_MARK = " — 근거: "                   # the requirement text quoted after it is not a stimulus
DURATION_SUFFIX = " 지속 시간"


def _fmt(value: Decimal, fact: dict[str, Any]) -> str:
    text = str(fact.get("value_text") or "")
    bare = text.lower().lstrip("-")
    if bare.startswith("0x"):
        digits = len(bare) - 2
        return ("-" if value < 0 else "") + "0x" + format(abs(int(value)), "X").zfill(digits)   # keep base and width
    decimals = len(text.split(".", 1)[1]) if "." in text else 0
    return f"{value:.{decimals}f}"


def requirement_facts(req: dict[str, Any]) -> list[tuple[dict, dict]]:
    """(line, fact) pairs of a requirement's description and verification criteria — read as two texts, so an
    ``<Output>`` heading at the end of the description never makes the criteria an outcome (review r4 W-4)."""
    pairs = []
    for key in ("description", "verification"):
        blocks = extract(f"ID\t{req.get('id', '')}\n{req.get(key) or ''}\n")
        pairs += [(line, fact) for block in blocks for line in block["lines"] for fact in line["facts"]]
    return pairs


_TYPED = re.compile(r"^([us])(8|16|32)[a-z]*_", re.IGNORECASE)


def subject_type_bounds(fact: dict[str, Any]) -> tuple[int, int] | None:
    """(review r4 I-2) ``u8g_…`` / ``s16s_…``: the declared width in the name bounds a unit-less raw value; a value with
    a unit (``8.5V``) is a physical quantity whose scaling the name does not give — no bound."""
    name = subject_of(fact) or ""
    m = _TYPED.match(name)
    if not m or fact.get("unit") or fact["kind"] != "threshold":
        return None
    bits = int(m.group(2))
    return (0, 2 ** bits - 1) if m.group(1).lower() == "u" else (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"   # a cut quote says so (review r4 I-3)


def _skip_reason(line: dict, fact: dict) -> str:
    if fact["status"] != "parsed":
        return str(fact.get("reason") or "not_parsed")
    if fact["kind"] not in {"threshold", "duration"}:
        return "kind_" + fact["kind"]
    if fact.get("op") not in _ORDER or not isinstance(fact.get("value"), (int, float)) \
            or isinstance(fact.get("value"), bool):
        return "not_an_order_comparison"
    if fact.get("role") == "response_constraint":
        return "response_constraint"
    if fact.get("negated"):
        return "negated_condition"
    if is_outcome_section(line.get("section") or ""):
        return "outcome_section"            # ``<완료조건>`` / ``<Output>``: produced, not stimulated (review r3 W6)
    if fact.get("signal_kind") == "reference_label":
        return "reference_label"            # ``기준 전압: 8.50V 이하`` names the threshold, not what to set (r3 W1)
    if fact["kind"] == "threshold" and fact.get("signal_kind") == "parameter" and not fact.get("monitored"):
        return "monitored_quantity_unknown"
    if line_holds(exact_value(fact), fact, line) is None:
        return "same_subject_combination_unstated"
    bounds = subject_type_bounds(fact)
    if bounds and not bounds[0] <= exact_value(fact) <= bounds[1]:
        return "value_outside_subject_type"   # ``u8g_X 45000 이상``: no stimulus can reach it (review r4 I-2)
    return ""


def _subject_text(fact: dict) -> str:
    if fact["kind"] == "duration":
        named = fact.get("signal") if fact.get("signal_kind") not in {"parameter", "identifier"} else None
        return (named or "조건") + DURATION_SUFFIX
    return subject_of(fact) or ""


def _condition_text(line: dict, fact: dict) -> str:
    parts = [fact] + [f for f in line["facts"] if same_subject(fact, f)]
    joins = {joint(line, fact, f) for f in parts[1:]}
    joiner = " 또는 " if joins == {"or"} else " 그리고 "
    return _subject_text(fact) + " " + joiner.join(
        f"{f.get('value_text') or f['value']}{f.get('unit') or ''} {_OP_TEXT[f['op']]}" for f in parts)


def _fact_text(f: dict) -> str:
    subject = _subject_text(f) if f["kind"] in {"threshold", "duration"} else (f.get("signal") or "")
    if f["kind"] in {"threshold", "duration"} and f.get("op") in _OP_TEXT:
        ref = f" (기준 {f['signal']})" if f.get("signal_kind") == "parameter" else ""
        return f"{subject} {f.get('value_text') or f['value']}{f.get('unit') or ''} {_OP_TEXT[f['op']]}{ref}".strip()
    return str(f.get("raw", "")).strip()


def _other_conditions(line: dict, fact: dict, joined_prev: str = "") -> str:
    """How to hold the line's conditions on other subjects while this one is stepped — one entry per subject (its
    conditions joined as the line joins them, review r3 W2), plus a join with a neighbouring line (r3 W6)."""
    notes, done = [], []
    for f in line["facts"]:
        if f is fact or same_subject(fact, f) or f["kind"] not in {"threshold", "duration", "symbolic", "range"}:
            continue
        if any(same_subject(f, g) for g in done):
            continue
        done.append(f)
        group = [f] + [g for g in line["facts"] if g is not fact and same_subject(f, g)]
        inner = {joint(line, f, g) for g in group[1:]}
        text = (" 또는 " if inner == {"or"} else " 그리고 ").join(_fact_text(g) for g in group)
        how = joint(line, fact, f)
        state = {"or": "불성립 상태로 둔다", "and": "성립 상태로 둔다"}.get(how, "결합이 원문에 명시되지 않음 — 결합 조건 확인 필요")
        notes.append(f"다른 조건 [{text}]: {state}")
    hold = {"or": "불성립 상태로 둔다", "and": "성립 상태로 둔다"}
    if not notes and len([f for f in line["facts"] if f["kind"] in {"threshold", "symbolic", "range", "duration"}]) == 1:
        # (review r4 W-1) a non-numeric condition in the same clause (``… 이상이고 MotorDirection 이 Close``) is not a
        #   fact, but the words say how it joins: hold it accordingly — or say the join is unclear (review r5 W-B)
        how = condition_part_join(line, fact)
        if how:
            notes.append("같은 줄의 다른 조건(원문): "
                         + hold.get(how, "결합이 원문에 명시되지 않음 — 결합 조건 확인 필요"))
    if line.get("continues"):
        quoted = f" [{_clip(line['next_text'], 80)}]" if line.get("next_text") else ""
        notes.append(f"다음 줄 조건{quoted}과 {line['continues'].upper()} 결합(원문): {hold[line['continues']]}")
    if joined_prev:
        # every line of the run joined up to here (``A AND`` / ``B AND`` / ``C``), not only the last (review r5 W-A)
        quoted = f" [{_clip(line.get('previous_text') or '', 300)}]" if line.get("previous_text") else ""
        notes.append(f"앞 줄 조건{quoted}과 {joined_prev.upper()} 결합(원문): {hold[joined_prev]}")
    return "; ".join(notes)


def _dedupe_text(text: str) -> str:
    """``2) X``, ``- X``, ``① X`` are the same sentence (review r3 I1)."""
    return re.sub(r"^[\s\-·•*]*(?:\(?\d+[.)]|[①-⑳])?\s*", "", text).strip()


def boundary_steps(req: dict[str, Any], stats: Counter | None = None) -> list[dict[str, Any]]:
    """One group of steps per fact used: ``[{"steps": [...], "evidence": {...}}]``."""
    stats = stats if stats is not None else Counter()
    groups: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for line, fact in requirement_facts(req):
        stats["facts"] += 1
        why = _skip_reason(line, fact)
        key = (_dedupe_text(line["text"]), fact["kind"], subject_of(fact), fact.get("op"),
               str(fact.get("value_text")), fact.get("unit"))
        if not why and key in seen:
            why = "duplicate_fact"   # the description and the verification criteria repeat the sentence (review W6)
        if why:
            stats["skipped:" + why] += 1
            continue
        seen.add(key)
        value, delta = exact_value(fact), written_step(fact)
        unit = fact.get("unit") or ""
        reference = ""
        if fact.get("signal_kind") == "parameter":
            reference = f" (기준 {fact['signal']} = {fact.get('value_text') or fact['value']}{unit})"
        predicate = f" ({fact['predicate']} 상태)" if fact["kind"] == "duration" and fact.get("predicate") else ""
        condition = _condition_text(line, fact)
        others = _other_conditions(line, fact, line.get("joins_previous") or "")
        steps, used = [], []
        bounds = subject_type_bounds(fact)
        for p in (value - delta, value, value + delta):
            if bounds and not bounds[0] <= p <= bounds[1]:
                stats["points_outside_subject_type"] += 1   # ``u16g_X 0 초과`` has no −1 (review r4 I-2)
                continue
            verdict = line_holds(p, fact, line)
            action = (f"{ACTION_PREFIX}{_subject_text(fact)} = {_fmt(p, fact)}{unit}{predicate}{reference}"
                      f"{BASIS_MARK}{fact['raw']}")
            # (review r3 C-1) the verdict is the sentence's, not the whole requirement's: outside its condition the
            #   sentence claims nothing (another sentence may describe what happens there)
            expected = (f"조건 [{condition}] 성립 → 이 문장이 기술한 동작 수행 확인: {_clip(line['text'], 160)}"
                        if verdict else
                        f"조건 [{condition}] 불성립 → 이 문장의 동작 대상 아님(같은 요구의 다른 문장 판정을 따른다): "
                        f"{_clip(line['text'], 160)}")
            steps.append({"action": action, "expected": expected})
            used.append({"point": _fmt(p, fact), "holds": verdict})
        stats["facts_used"] += 1
        stats["steps"] += len(steps)
        groups.append({"steps": steps, "evidence": {
            "srs_id": req.get("id", ""), "line": line["text"], "line_sha256": line["sha256"], "span": fact["span"],
            "kind": fact["kind"], "signal": _subject_text(fact),
            "reference_constant": fact["signal"] if reference else None,
            "signal_kind": fact.get("signal_kind", ""), "op": fact["op"],
            "value": fact.get("value_text") or fact["value"], "unit": unit, "step": format(delta, "f"),
            "step_basis": "written_precision", "combination_note": others, "points": used}})
    return groups


def append_requirement_boundary_tcs(test_cases: list[dict], requirements: list[dict], build_tc, make_tc_id,
                                    classify, max_steps: int = 12) -> dict[str, Any]:
    """Append requirement-boundary TCs after each requirement's existing TCs, numbering on from them. A fact's points
    never split across TCs; a TC holds as many whole facts as fit in ``max_steps`` (at least one). Returns the counts
    for the quality report."""
    stats: Counter = Counter()
    last: dict[str, int] = {}
    for tc in test_cases:
        rid = str(tc.get("srs_id") or "")
        tail = str(tc.get("id") or "").rsplit("_", 1)[-1]
        if rid and tail.isdigit():
            last[rid] = max(last.get(rid, 0), int(tail))
    added: list[dict] = []
    for req in requirements:
        groups = boundary_steps(req, stats)
        chunks: list[list[dict]] = []
        for g in groups:
            # a fact with conditions to hold is its own TC: its precondition must not contradict another fact's steps
            #   (review r3 W2); facts without such notes share TCs up to ``max_steps``
            alone = bool(g["evidence"]["combination_note"])
            if not alone and chunks and not chunks[-1][0]["evidence"]["combination_note"] and \
                    sum(len(x["steps"]) for x in chunks[-1]) + len(g["steps"]) <= max(max_steps, 1):
                chunks[-1].append(g)
            else:
                chunks.append([g])
        rid = req["id"]
        for chunk in chunks:
            steps = [s for g in chunk for s in g["steps"]]
            last[rid] = last.get(rid, 0) + 1
            method, gen, review_only = classify(steps)
            tc = build_tc(tc_id=make_tc_id(rid, last[rid]), req=req, steps=steps, test_method=method, gen_method=gen,
                          review_only=review_only)
            tc["requirement_evidence"] = [g["evidence"] for g in chunk]
            notes = list(dict.fromkeys(g["evidence"]["combination_note"] for g in chunk
                                       if g["evidence"]["combination_note"]))
            if notes:
                tc["precondition"] = "\n".join([p for p in [tc.get("precondition") or ""] if p] + notes)
            tc["requirement_boundary"] = True
            added.append(tc)
            stats["tcs"] += 1
    if added:   # nothing added: the TC order is left exactly as it was (review r4 I-4)
        order = {r["id"]: i for i, r in enumerate(requirements)}
        test_cases.extend(added)
        test_cases.sort(key=lambda tc: order.get(str(tc.get("srs_id") or ""), len(order)))  # stable
    return {k: v for k, v in sorted(stats.items())}


REQUIREMENT_EVIDENCE_HEADERS = ["Test Case ID", "SRS ID", "Kind", "Subject", "Reference Constant", "Operator", "Value",
                                "Unit", "Step", "Step Basis", "Stimulus Points (holds)", "Other Conditions",
                                "Source Line", "Line SHA-256"]
REQUIREMENT_EVIDENCE_SHEET = "Requirement Evidence"


def write_requirement_evidence_sheet(wb, test_cases: list[dict]) -> int:
    """'Requirement Evidence' sheet: which requirement sentence each boundary step comes from. Returns rows written.
    A sheet of that name already in the workbook (a template made from an earlier output) is removed first — also when
    this document has no boundary TC, so an old sheet never describes a document it does not belong to."""
    if REQUIREMENT_EVIDENCE_SHEET in wb.sheetnames:
        del wb[REQUIREMENT_EVIDENCE_SHEET]
    rows = [(tc["id"], e) for tc in test_cases for e in tc.get("requirement_evidence") or []]
    if not rows:
        return 0
    ws = wb.create_sheet(REQUIREMENT_EVIDENCE_SHEET)
    ws.append(REQUIREMENT_EVIDENCE_HEADERS)
    for tc_id, e in rows:
        points = ", ".join(f"{p['point']}({'T' if p['holds'] else 'F'})" for p in e["points"])
        ws.append([tc_id, e["srs_id"], e["kind"], e.get("signal") or "—", e.get("reference_constant") or "—", e["op"],
                   e["value"], e["unit"] or "—", e["step"], e["step_basis"], points, e["combination_note"] or "—",
                   _clip(e["line"], 300), e["line_sha256"]])
    return len(rows)
