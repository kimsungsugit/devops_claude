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

**Traced system requirements (R29, G4(b))**: an SRS block's ``Related ID`` names the system requirements it realises
(``SyTR_0602``, ``SyII_06`` …). When the SyRS / SyDS are given, the same reading is applied to the text fields of
**each directly cited** system block (one hop — the system block's own Related IDs are not followed), and its facts get
steps under the citing SRS requirement, the step quoting the system sentence and naming the block and field it came
from. Nothing is matched by value or by guess: a system block contributes only because the SRS cites it. A fact the SRS
requirement already stepped is not repeated (only the same subject wording counts as the same — an alias is not
guessed); facts of different documents (the SRS, the SyRS, the SyDS) never share a TC, so every TC comes from one
document. What a system block states as an outcome is not stepped: a verification case's ``Output :`` line, the
``Action`` / ``System Behavior`` fields, and an obligation (``암전류는 0.3mA 이하여야 한다``).
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


# ── (R29) system requirements the SRS block cites ────────────────────────────────────────────────────────────────
SYSTEM_ID = re.compile(r"\bSy[A-Za-z]{1,6}_\d+(?:_\d+)?\b")
# the fields of a SyRS / SyDS block that state behaviour or conditions (measured over HDPDM01 and KJPDS02: the rest —
#   Name, Type, ASIL, Priority, Rationale, pin allocation, element names, failure rates — carry no stimulus)
SYSTEM_TEXT_FIELDS = ("Description", "Functional Behavior", "System Behavior", "Condition", "Action", "Range",
                      "Time Constraint", "Verification criteria")
# (R29 review C2) what the system does — a state table's ``Action`` and a block's ``System Behavior`` — is read as an
#   outcome: its values are counted (``outcome_section``) and never stepped
SYSTEM_OUTCOME_FIELDS = frozenset({"Action", "System Behavior"})


def _field_key(name: str) -> str:
    """``Verification Criteria\\n(optional)`` and ``Verification criteria`` are one field."""
    return re.sub(r"\s+", " ", re.sub(r"\(optional\)", "", name, flags=re.IGNORECASE)).strip().casefold()


_FIELD_BY_KEY = {_field_key(f): f for f in SYSTEM_TEXT_FIELDS}


def parse_system_requirement_docx(path: str, label: str) -> tuple[dict[str, dict[str, Any]], int]:
    """``({system ID: {"doc": label, "fields": {field: text}}}, duplicate tables)`` from the attribute tables of a
    SyRS / SyDS docx (the SRS layout: ``ID | SyTR_0602``, ``Description | …``). A key cell merged over two columns
    (``ID | ID | SyOS_01``) reads the last distinct cell; a key written on two rows keeps both, in order (review I4:
    ``Time Constraint`` twice). The first table of an ID wins; later copies are counted. A nested table (a min/typ/max
    grid) is not part of its cell's text — it states no comparison sentence. Raises if the file cannot be read: the
    caller discloses it."""
    from docx import Document
    doc = Document(path)
    out: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for table in doc.tables:
        parts: dict[str, list[str]] = {}
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) < 2 or not cells[0]:
                continue
            values = [c for c in cells[1:] if c and c != cells[0]]
            if values:
                bucket = parts.setdefault(_field_key(cells[0]), [])
                if values[-1] not in bucket:        # the same (also multi-line) value twice is kept once (r2 I4, r3 I1)
                    bucket.append(values[-1])
        cells_map = {k: "\n".join(v) for k, v in parts.items()}
        rid = cells_map.get("id", "")
        if not SYSTEM_ID.fullmatch(rid):
            continue
        if rid in out:
            duplicates += 1
            continue
        out[rid] = {"doc": label, "fields": {_FIELD_BY_KEY[k]: v for k, v in cells_map.items() if k in _FIELD_BY_KEY}}
    return out, duplicates


def load_system_requirements(documents: list[tuple[str, str | None]]) -> tuple[dict[str, dict[str, Any]], list]:
    """Parse the given ``(label, path)`` system documents (``("SyRS", …), ("SyDS", …)``) into one ID map — the first
    document naming an ID wins. Returns the map and one record per document for the quality report: its blocks, the
    IDs another document already had, duplicate tables — or the error that kept it out (never raised: the STS is still
    generated, and the report says the trace was not read)."""
    system: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for label, path in documents:
        if not path:
            continue
        name = re.split(r"[\\/]", str(path))[-1]
        try:
            blocks, duplicates = parse_system_requirement_docx(str(path), label)
        except Exception as exc:  # noqa: BLE001 — an unreadable optional input is disclosed, not fatal
            records.append({"doc": label, "file": name, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        shadowed = [k for k in blocks if k in system]
        for k, v in blocks.items():
            system.setdefault(k, v)
        records.append({"doc": label, "file": name, "blocks": len(blocks), "ids_in_earlier_document": len(shadowed),
                        "duplicate_tables": duplicates})
    return system, records


def cited_system_ids(req: dict[str, Any]) -> list[str]:
    """The system IDs the SRS block's Related ID names, in order, once each."""
    return list(dict.fromkeys(SYSTEM_ID.findall(str(req.get("related_id") or ""))))


def traced_system_facts(req: dict[str, Any], system: dict[str, dict[str, Any]],
                        stats: Counter | None = None) -> list[tuple[dict, dict, dict]]:
    """(line, fact, source) of every text field of each system block the requirement cites. Each field is read as
    its own text (a heading in one never makes the next an outcome), under the SRS requirement's ID."""
    stats = stats if stats is not None else Counter()
    out = []
    for sid in cited_system_ids(req):
        stats["traced:cited"] += 1
        block = system.get(sid)
        if block is None:
            stats["traced:cited_not_in_documents"] += 1
            continue
        for field in SYSTEM_TEXT_FIELDS:
            text = block["fields"].get(field)
            if not text:
                continue
            source = {"doc": block["doc"], "id": sid, "field": field}
            head = "<Output>\n" if field in SYSTEM_OUTCOME_FIELDS else ""
            for b in extract(f"ID\t{req.get('id', '')}\n{head}{text}\n"):
                out += [(line, fact, source) for line in b["lines"] for fact in line["facts"]]
    return out


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


# (review r2 W-4) an obligation ends its sentence: ``0.3mA 이하여야 한다`` / ``…이하로 유지한다`` — never a condition that
#   goes on (``9V 이상이어야 모터가 동작한다`` / ``500ms 이상 유지되어야 고장으로 판정한다`` / ``…유지시``)
_MUST = r"\s*(?:한다|함|합니다)"
_OBLIGATION = re.compile(r"\s*\)?\s*(?:로|으로|를|을|가|이)?\s*(?:유지(?:한다|합니다|해야" + _MUST + r"|하여야" + _MUST
                         + r"|되어야" + _MUST + r")|(?:이)?어야" + _MUST + r"|여야" + _MUST + r"|되어야" + _MUST
                         + r"|하여야" + _MUST + r")\s*(?:[.。]|$|\()")
# a subject that ends in a separator or a postposition is a misread, not a quantity (review W5: ``미만/``, ``위치에
#   따라``, ``내``), and so is one starting with a particle (``와 통신`` from ``Block 와의 통신``). (review r2 W-4) not a
#   comparison word at the end — ``전압 이상 :`` is "voltage abnormality"
_UNCLEAR_SUBJECT = re.compile(r"[/·,:;~\-]$|(?:^|\s)(?:따라|의해|대해|위해|내|중|후|시|때)$|^(?:와|과|의|을|를|에|로)\s")
# an object and its verb read *after* the value (``10ms 이상의 신호를 주입``, KJPDS02_PV SySM_06) — only there: a label
#   before the value may hold one (``도어를 여는 속도 :``, review r2 W-4)
_VERB_PHRASE = re.compile(r"\S(?:을|를)\s+\S")


def _label_shares_a_quantity(line: dict, fact: dict) -> bool:
    """(R32 review C1 · r2 W2) ``Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 …)`` / ``도어 속도가
    0.8m/s 미만이거나 Tip-To-Run 조건(0.8m/s 이상)``: a label before a parenthesis names a condition, not a quantity —
    with another condition (a threshold or a range, not negated, not an obligation) in the same non-empty unit under
    another name, joined to it by a **stated** *or* / *and*, the two may be one quantity (the door speed). Then the
    stated join would make the step hold the other "false" / "true" at a point where it is not the step's to say (a step
    said 불성립 at 0.8 m/s and told the tester to hold Tip-To-Run false there). An unstated join already tells the tester
    to check it and stays."""
    unit = fact.get("unit") or ""
    if not unit:
        return False
    raw = line.get("raw") or line["text"]
    for other in line["facts"]:
        if other is fact or other["kind"] not in {"threshold", "range"} or other.get("status") != "parsed" \
                or other.get("negated") or (other.get("unit") or "") != unit \
                or "paren_owner" not in (fact.get("signal_kind"), other.get("signal_kind")) \
                or (subject_of(other) if other["kind"] == "threshold" else other.get("signal")) == subject_of(fact) \
                or _OBLIGATION.match(raw[other["line_span"][1]:]):
            continue
        if joint(line, fact, other) in {"or", "and"}:
            return True
    return False


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
    if fact["kind"] == "threshold" and _label_shares_a_quantity(line, fact):
        return "parenthesis_labels_may_share_a_quantity"
    if _OBLIGATION.match((line.get("raw") or line["text"])[fact["line_span"][1]:]):
        # (R29 review C2) ``암전류는 0.3mA 이하여야 한다`` / ``최소 전류는 0.3mA 이하로 유지한다``: what the system must
        #   produce, not a condition to set — ``300ms 이상 유지시`` (a condition) is not matched
        return "output_requirement"
    named = subject_of(fact) if fact["kind"] == "threshold" else \
        (fact.get("signal") if fact.get("signal_kind") not in {"parameter", "identifier"} else None)
    if _UNCLEAR_SUBJECT.search(str(named or "").strip()) or \
            (fact.get("signal_kind") == "phrase_after" and _VERB_PHRASE.search(str(named or ""))):
        return "subject_unclear"            # ``4.85V 미만/5.15V 초과`` read ``미만/`` as the subject (review W5)
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
        if f.get("status") != "parsed":
            # (R29 review r2 W-1) a condition without a subject cannot be held "true" or "false" by the words between:
            #   ``전원 8.5V 이하 500ms 미만 유지 후 9V 이상으로 복귀`` — `joint` joins a hold time with anything by *and*,
            #   which asserted both ``8.5V 이하`` and ``9V 이상`` hold. Say the join is for the tester to settle
            how = "unstated"
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


def _fact_key(fact: dict) -> tuple:
    return (fact["kind"], subject_of(fact), fact.get("op"), str(fact.get("value_text")), fact.get("unit"))


def boundary_steps(req: dict[str, Any], stats: Counter | None = None,
                   system: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One group of steps per fact used: ``[{"steps": [...], "evidence": {...}}]``. With ``system`` (parsed SyRS /
    SyDS blocks), the facts of the system blocks the requirement cites follow its own (``evidence["source"]`` names
    the block; counters prefixed ``traced:``)."""
    stats = stats if stats is not None else Counter()
    groups: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    stepped: set[tuple] = set()
    items = [(line, fact, None) for line, fact in requirement_facts(req)]
    if system is not None:
        items += traced_system_facts(req, system, stats)
    for line, fact, source in items:
        prefix = "traced:" if source else ""
        stats[prefix + "facts"] += 1
        why = _skip_reason(line, fact)
        key = (_dedupe_text(line["text"]), *_fact_key(fact))
        if not why and key in seen:
            why = "duplicate_fact"   # the description and the verification criteria repeat the sentence (review W6)
        # (review r2 W-3) only a fact that names its subject is "the same" as another — two unnamed hold times of two
        #   conditions are not one quantity (`same_subject`, review r4 C-2): SySM_04's over-voltage hold was dropped
        if not why and source and subject_of(fact) is not None and _fact_key(fact) in stepped:
            why = "already_stepped"  # the SRS (or another cited block) already steps this subject at this value
        if why:
            stats[prefix + "skipped:" + why] += 1
            continue
        seen.add(key)
        stepped.add(_fact_key(fact))
        value, delta = exact_value(fact), written_step(fact)
        unit = fact.get("unit") or ""
        reference = ""
        if fact.get("signal_kind") == "parameter":
            reference = f" (기준 {fact['signal']} = {fact.get('value_text') or fact['value']}{unit})"
        predicate = f" ({fact['predicate']} 상태)" if fact["kind"] == "duration" and fact.get("predicate") else ""
        condition = _condition_text(line, fact)
        others = _other_conditions(line, fact, line.get("joins_previous") or "")
        # (R29) a traced sentence names where it comes from — after the basis mark, so it is never read as a stimulus
        origin = f" [{source_label(source)} — {req.get('id', '')} Related ID]" if source else ""
        whose = f"시스템 요구 {source['id']} 의 " if source else ""
        steps, used = [], []
        bounds = subject_type_bounds(fact)
        for p in (value - delta, value, value + delta):
            if bounds and not bounds[0] <= p <= bounds[1]:
                stats[prefix + "points_outside_subject_type"] += 1   # ``u16g_X 0 초과`` has no −1 (review r4 I-2)
                continue
            verdict = line_holds(p, fact, line)
            action = (f"{ACTION_PREFIX}{_subject_text(fact)} = {_fmt(p, fact)}{unit}{predicate}{reference}"
                      f"{BASIS_MARK}{fact['raw']}{origin}")
            # (review r3 C-1) the verdict is the sentence's, not the whole requirement's: outside its condition the
            #   sentence claims nothing (another sentence may describe what happens there)
            expected = (f"조건 [{condition}] 성립 → {whose}이 문장이 기술한 동작 수행 확인: {_clip(line['text'], 160)}"
                        if verdict else
                        f"조건 [{condition}] 불성립 → {whose}이 문장의 동작 대상 아님(같은 요구의 다른 문장 판정을 따른다): "
                        f"{_clip(line['text'], 160)}")
            steps.append({"action": action, "expected": expected})
            used.append({"point": _fmt(p, fact), "holds": verdict})
        stats[prefix + "facts_used"] += 1
        stats[prefix + "steps"] += len(steps)
        groups.append({"steps": steps, "evidence": {
            "srs_id": req.get("id", ""), "line": line["text"], "line_sha256": line["sha256"], "span": fact["span"],
            "kind": fact["kind"], "signal": _subject_text(fact),
            "reference_constant": fact["signal"] if reference else None,
            "signal_kind": fact.get("signal_kind", ""), "op": fact["op"],
            "value": fact.get("value_text") or fact["value"], "unit": unit, "step": format(delta, "f"),
            "step_basis": "written_precision", "combination_note": others, "points": used,
            "source": dict(source) if source else None}})
    return groups


# (R33) ``이상`` ↔ ``초과`` and ``이하`` ↔ ``미만``: the same value with the other boundary inclusion
_INCLUSION_FLIP = {">=": ">", ">": ">=", "<=": "<", "<": "<="}
MAX_INCLUSION_CONFLICTS = 30     # items kept for the report (all are counted)


# (R33 review W3) a hold time whose words state no inclusion (``500ms 동안 유지``) got ``>=`` from the extractor: it
#   wrote none, so it disagrees with nothing
_WRITTEN_INCLUSION = re.compile(r"이상|초과|이하|미만|이내|[<>]")


def _conflict_role(line: dict, fact: dict, verification: bool) -> str:
    """``condition`` — or ``outcome`` for what the requirement produces (an ``<Output>``/``Output :`` section, a system
    block's Action / System Behavior, an obligation ``…이하여야 한다``) — the split `_skip_reason` makes for stepping
    (R33 review W2: an input condition and an output value of the same number are not one statement) — or
    ``stimulus`` for anything else of a **verification criteria** field (the SRS ``verification`` text, a block's
    "Verification criteria"): it describes tests — ``Input : 입력전원 8.5V 이하`` / ``Precondition : …`` and the SRS's
    unlabelled ``2. 500ms 초과 저전압 상황 동작 확인`` alike — the range a test chooses its input from, not the
    requirement's condition (R33 review r2 W-A, r3 W-2)."""
    raw = line.get("raw") or line["text"]
    if is_outcome_section(line.get("section") or "") or _OBLIGATION.match(raw[fact["line_span"][1]:]):
        return "outcome"
    return "stimulus" if verification else "condition"


def _joins(ra: str, a: dict, rb: str, b: dict) -> bool:
    """Do two facts of these roles make a candidate? A condition with a condition, an outcome with an outcome — and a
    test input with a condition only when the **input** includes the value the condition excludes (``Input : 8.5V 이하``
    against ``8.5V 미만``: the test expects a reaction where the requirement gives none). A stricter input (``Input :
    4.85V 미만`` against ``4.85V 이하``) only leaves the value untested — no disagreement."""
    if ra == rb:
        return ra != "stimulus"
    if {ra, rb} == {"stimulus", "condition"}:
        stimulus = a if ra == "stimulus" else b
        return stimulus["op"] in {"<=", ">="}
    return False


def inclusion_conflicts(req: dict[str, Any], system: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """(R33) Where the requirement's own text and a system block it cites (or two such blocks) state the **same value in
    the same unit with the other boundary inclusion**, in roles that can disagree (`_joins`: two conditions, two
    outcomes, or a test input that includes a value a condition excludes) — HDPDM01
    ``SwTSR_0104``: SRS ``u16g_ApiIn_Vsup < 8.5V`` against SyDS ``SySM_04`` ``입력전원 8.5V 이하``: 8.5 V is inside one
    document's condition and outside the other's. The link is explicit (the SRS Related ID); the pairing is by value
    and unit only, so ``same_subject`` is true only when both facts name the same subject (`subject_of`) — otherwise the
    reviewer first checks they are one quantity. Which document is right is not decided here; the boundary TCs judge
    each sentence as written. Not candidates: a negated condition, a response time (``500ms 이내``), a hold time that
    writes no inclusion (``500ms 동안 유지``). Pairs are formed within (unit, value) buckets.

    (R43) Two different lines of **one source** (the SRS text, or the fields of one block) are candidates too, marked
    ``within_source`` — HDPDM01 ``SwTSR_0104``'s own text: ``저 전압 고장 검출 기준 전압: 8.50V 이하`` against ``8.50V
    미만인 전압으로 … 유지하는 경우``. Within one source two sentences may also be two conditions or two actions on
    purpose (a warning at ``이하`` and a DTC at ``미만``; items 1·2·3 of one block with their own hold times), so the
    mark tells the reviewer to read both first."""
    items = []
    for key in ("description", "verification"):          # `requirement_facts`, keeping which field a fact is in
        for b in extract(f"ID\t{req.get('id', '')}\n{req.get(key) or ''}\n"):
            items += [(line, fact, None, key == "verification") for line in b["lines"] for fact in line["facts"]]
    items += [(line, fact, source, source.get("field") == "Verification criteria")
              for line, fact, source in traced_system_facts(req, system, Counter())]
    buckets: dict[tuple, list] = {}
    for line, fact, source, verification in items:
        if fact["kind"] not in {"threshold", "duration"} or fact.get("op") not in _INCLUSION_FLIP \
                or not isinstance(fact.get("value"), (int, float)) or isinstance(fact.get("value"), bool) \
                or fact.get("negated") or fact.get("role") == "response_constraint" \
                or not _WRITTEN_INCLUSION.search(str(fact.get("raw") or "")):
            continue            # a response time (``500ms 이내``) is measured, not a condition — not the same statement
        buckets.setdefault((fact.get("unit") or "", exact_value(fact)), []).append(
            (line, fact, source, _conflict_role(line, fact, verification)))
    out: list[dict[str, Any]] = []
    seen: dict[tuple, int] = {}   # key → index in ``out``

    def side(line, fact, source):
        subject = _subject_text(fact) if fact.get("signal_kind") == "parameter" else subject_of(fact)
        return {"source": source_label(source), "subject": subject or "주어 없음", "op": fact["op"],
                "reference": fact["signal"] if fact.get("signal_kind") == "parameter" else None,
                "text": f"{fact.get('value_text') or fact['value']}{fact.get('unit') or ''} {_OP_TEXT[fact['op']]}",
                "line": _clip(line["text"], 160)}

    for (unit, value), group in buckets.items():
        for i, (la, a, sa, ra) in enumerate(group):
            for lb, b, sb, rb in group[i + 1:]:
                within = ((sa or {}).get("doc"), (sa or {}).get("id")) == ((sb or {}).get("doc"), (sb or {}).get("id"))
                if within and _dedupe_text(la["text"]) == _dedupe_text(lb["text"]):
                    # (R43) one line says one thing: a pair within one source is two of its lines — and ``1) X`` in
                    #   the description is the same sentence as ``- X`` in the verification (review I3)
                    continue
                if _INCLUSION_FLIP[a["op"]] != b["op"] or not _joins(ra, a, rb, b):
                    continue
                role = "stimulus" if "stimulus" in (ra, rb) else ra
                key = (unit, value, role, frozenset({((sa or {}).get("doc"), (sa or {}).get("id"), a["op"]),
                                                   ((sb or {}).get("doc"), (sb or {}).get("id"), b["op"])}))
                named = subject_of(a) is not None and subject_of(b) is not None
                same = bool(named and subject_of(a) == subject_of(b))
                if key in seen:
                    # (R43 review I2) one finding per key — but a pair naming one subject says more than the first seen
                    k = seen[key]
                    if same and not out[k]["same_subject"]:
                        out[k].update(same_subject=True, subject_missing=False, a=side(la, a, sa), b=side(lb, b, sb))
                    continue
                seen[key] = len(out)
                out.append({"srs_id": req.get("id", ""), "value": str(exact_value(a)), "unit": unit, "role": role,
                            "same_subject": same, "subject_missing": not named, "within_source": within,
                            "a": side(la, a, sa), "b": side(lb, b, sb)})
    return out


def source_label(source: dict | None) -> str:
    """``SyDS SyII_06 · Range`` — or ``SRS`` for the requirement's own text."""
    return f"{source['doc']} {source['id']} · {source['field']}" if source else "SRS"


def _doc_of(group: dict) -> str:
    """The document a group's fact comes from — ``SRS`` for the requirement's own text, else ``SyRS`` / ``SyDS``."""
    source = group["evidence"]["source"]
    return source["doc"] if source else "SRS"


def append_requirement_boundary_tcs(test_cases: list[dict], requirements: list[dict], build_tc, make_tc_id,
                                    classify, max_steps: int = 12,
                                    system: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Append requirement-boundary TCs after each requirement's existing TCs, numbering on from them. A fact's points
    never split across TCs; a TC holds as many whole facts as fit in ``max_steps`` (at least one), all from the same
    document (the SRS, or the system requirements it cites — R29). Returns the counts for the quality report."""
    stats: Counter = Counter()
    fanout: Counter = Counter()
    conflicts: list[dict[str, Any]] = []
    conflict_errors: list[str] = []
    compared_blocks = 0
    last: dict[str, int] = {}
    for tc in test_cases:
        rid = str(tc.get("srs_id") or "")
        tail = str(tc.get("id") or "").rsplit("_", 1)[-1]
        if rid and tail.isdigit():
            last[rid] = max(last.get(rid, 0), int(tail))
    added: list[dict] = []
    for req in requirements:
        groups = boundary_steps(req, stats, system)
        if system is not None:
            compared_blocks += sum(1 for sid in cited_system_ids(req) if sid in system)
            try:
                conflicts += inclusion_conflicts(req, system)
            except Exception as exc:  # noqa: BLE001 — an optional finding never costs the boundary TCs (review I8)
                conflict_errors.append(f"{req.get('id', '')}: {type(exc).__name__}: {exc}"[:200])
        chunks: list[list[dict]] = []
        for g in groups:
            # a fact with conditions to hold is its own TC: its precondition must not contradict another fact's steps
            #   (review r3 W2); facts without such notes share TCs up to ``max_steps``
            alone = bool(g["evidence"]["combination_note"])
            if not alone and chunks and not chunks[-1][0]["evidence"]["combination_note"] and \
                    _doc_of(chunks[-1][0]) == _doc_of(g) and \
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
            stats["traced:tcs" if chunk[0]["evidence"]["source"] else "tcs"] += 1
            for g in chunk:
                if g["evidence"]["source"]:
                    fanout[g["evidence"]["source"]["id"]] += 1
    if added:   # nothing added: the TC order is left exactly as it was (review r4 I-4)
        order = {r["id"]: i for i, r in enumerate(requirements)}
        test_cases.extend(added)
        test_cases.sort(key=lambda tc: order.get(str(tc.get("srs_id") or ""), len(order)))  # stable
    out: dict[str, Any] = {k: v for k, v in sorted(stats.items())}
    if fanout:
        # (review W5) one system block cited by many SRS requirements is stepped under each: say which blocks carry the
        #   traced facts (the most first, ties by ID) — HDPDM01 ``SySM_04`` alone carried 35 of 74
        out["traced_facts_by_block"] = dict(sorted(fanout.items(), key=lambda kv: (-kv[1], kv[0]))[:10])
        out["traced_blocks_used"] = len(fanout)
    if system is not None:
        # (R33) requirement-document inconsistencies found on the way — counted in full, the first ones itemised: safety
        #   requirements first (review I7: SwTSR_0104 fell behind "외 5건"), then by requirement ID
        # (R43 review W2) within a requirement, pairs across documents first — the disclosure shows five
        conflicts.sort(key=lambda c: (not str(c["srs_id"]).startswith("SwTSR"), str(c["srs_id"]),
                                      bool(c.get("within_source"))))
        # (R43 review W3) one block's own two lines are one finding, however many requirements cite that block (the hub
        #   block SySM_04 carries 35 of HDPDM01's 74 traced facts) — kept under the first requirement in the SORTED list
        #   (round 2 W3), so a safety requirement citing the block keeps it in front
        block_pairs: set = set()
        kept: list[dict[str, Any]] = []
        for c in conflicts:
            if c.get("within_source") and c["a"]["source"] != "SRS":
                bkey = (c["a"]["source"].split(" · ")[0], c["unit"], Decimal(c["value"]), c["role"],
                        frozenset((c["a"]["op"], c["b"]["op"])))
                if bkey in block_pairs:
                    continue
                block_pairs.add(bkey)
            kept.append(c)
        conflicts = kept
        out["inclusion_conflicts"] = len(conflicts)
        # (R43) of them, two lines of one source — read both first: they may be two conditions or actions on purpose
        out["inclusion_conflicts_within_source"] = sum(1 for c in conflicts if c.get("within_source"))
        out["inclusion_conflict_items"] = conflicts[:MAX_INCLUSION_CONFLICTS]
        out["inclusion_conflict_requirements"] = len({c["srs_id"] for c in conflicts})
        out["inclusion_conflict_values"] = len({(c["srs_id"], Decimal(c["value"]), c["unit"]) for c in conflicts})
        # (review W4) how many cited blocks were there to compare with — 0 means nothing was compared, not "none found"
        out["inclusion_blocks_compared"] = compared_blocks
        if conflict_errors:
            out["inclusion_conflict_errors"] = conflict_errors[:5]
            out["inclusion_conflict_error_count"] = len(conflict_errors)
    return out


REQUIREMENT_EVIDENCE_HEADERS = ["Test Case ID", "SRS ID", "Kind", "Subject", "Reference Constant", "Operator", "Value",
                                "Unit", "Step", "Step Basis", "Stimulus Points (holds)", "Other Conditions",
                                "Source Line", "Line SHA-256", "Source Document"]
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
        subject = e.get("signal") or "—"
        if e.get("signal_kind") == "paren_owner":
            subject += " (괄호 앞 명사)"   # (R32 review I4) a weaker subject than a signal name: the reviewer sees it
        ws.append([tc_id, e["srs_id"], e["kind"], subject, e.get("reference_constant") or "—", e["op"],
                   e["value"], e["unit"] or "—", e["step"], e["step_basis"], points, e["combination_note"] or "—",
                   _clip(e["line"], 300), e["line_sha256"], source_label(e.get("source"))])
    return len(rows)
