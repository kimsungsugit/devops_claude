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

**What the text leaves unwritten (R45)**: a lower bound below an upper bound of one subject side by side with no
connective has one meaningful reading, a range (`requirement_oracle.joint`; a lower bound above the upper one is a
hysteresis, not read), and two names that split one unit at one value (``Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run
조건(0.8m/s 이상 …)``) are one quantity in two regions — each step writes the other region's verdict at its point. What
was read so is listed to confirm; a fact still held back for a reason a reader can settle (a missing subject, a range's
inclusion, an unwritten join …) is listed with what to decide — the 'Requirement Review' sheet and the generation
disclosure — never filled by a guess.

**Evidence and what filling would improve (R46)**: for each held-back fact, the other sentences of the given documents
(every SRS requirement, every SyRS / SyDS block — also a SyDS element's ``Input Information``) that state **the same
value in the same unit in a form this module steps** are quoted as candidates (``BAT 전압(9V 이상 16.0V 이하)`` for a
``Range`` cell's ``9 ~ 16V``) — never used: the same number may be another quantity. Each item also says what writing
the missing part into the requirement would produce, **tried in that very sentence** (`fill_guidance`: the fill is
written in, the sentence read again; the value must step under the written name and nothing stepped before may stop —
else the text says what still holds it back); what only a rewrite can settle (a negation, a deadline, a label) gets an
example that keeps the sentence's meaning.

**Input cells (R47)**: a SyDS element's ``Input Information`` (``BAT 전압(9V 이상 16.0V 이하)`` · ``Watchdog Input(Pulse
주기 5ms 이하)`` · ``Motor Rotation : …, 5000RPM 초과``) is read as the other text fields are — its bounds step under the
SRS requirement that cites the block, in TCs of their own after every other traced fact. A cell writes a normal range
and a trigger alike, so a step says only whether the input is inside or outside what the cell writes; the element's
reaction is the requirement's other sentences' to decide.
"""
from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Any

from generators.requirement_oracle import (
    condition_part_join,
    condition_units,
    exact_value,
    extract,
    is_outcome_section,
    join_is_inferred,
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
_VERDICT_TEXT = {True: "성립", False: "불성립", None: "판정 미상(결합 미기재)"}

# (R45) held-back facts a reader can settle — 2026-09-30 user direction: what is wrong or undecided is shown in the
#   document and on the web even when there is no basis to fill it. The rest (an outcome, a response constraint, a
#   symbolic or equality comparison, a repeat) is no condition to step at all. Each: why it is held back, what to decide.
REVIEW_TEXT = {
    "no_subject_for_value": ("값이 무엇의 값인지(주어) 원문에 없음", "이 값과 비교하는 신호·변수를 정하면 경계 TC 가 된다"),
    "subject_unclear": ("주어로 읽힌 말이 신호 이름이 아님", "비교하는 신호·변수 확인"),
    "kind_range": ("범위(~)의 경계 포함 여부가 적혀 있지 않음", "하한·상한의 포함(이상/초과, 이하/미만) 확인"),
    "parenthesis_labels_may_share_a_quantity": ("괄호 앞 이름 둘이 같은 단위 — 같은 양인지 원문에 없음",
                                                "두 조건이 한 신호의 구간인지, 다른 신호인지 확인"),
    "same_subject_combination_unstated": ("같은 주어의 조건 결합(그리고/또는)이 적혀 있지 않음", "결합 확인"),
    "negated_condition": ("부정 절 — 부정이 조건 전체에 걸리는지 서술어에 걸리는지 원문으로 가려야 함", "부정의 범위 확인"),
    "monitored_quantity_unknown": ("기준 상수가 비교하는 감시량이 적혀 있지 않음", "감시하는 신호 확인"),
    # (R45 review W1) a value-only field (a block's ``Range``) names its quantity in the block name, not in the cell —
    #   the document did not leave it out; the generator does not read the name as a subject
    "no_subject_in_value_field": ("값 전용 칸(Range)이라 주어가 이 칸에 없음 — 블록 이름이 이 값의 주어일 수 있음",
                                  # (R46 review I7) the generator never reads the Name: no promise here — the 'If
                                  #   Filled' column says what writing the name into the cell produces
                                  "블록 이름(Name)이 이 값과 비교하는 신호인지 확인"),
}
    # (R45 review r2 W-R2-2) ``20ms 이내에 … 되지 않으면`` / ``500ms 이내에 9V 이상으로 복귀할 경우``: the extractor reads
    #   every ``이내`` as a deadline, but in a conditional clause it may be the condition's time window
REVIEW_TEXT["deadline_or_window"] = ("'이내' 가 조건 절 안에 있음 — 응답 기한인지 조건의 시간 창인지 원문에 가려야 함",
                                     "응답 기한이면 측정 대상(스텝 아님), 조건의 시간 창이면 경계 TC 대상 — 어느 쪽인지 확인")
# (review r2 W-R2-1) a range never becomes a boundary step here, even with a subject: no promise of one
RANGE_DECIDE = {
    "no_subject_for_value": "이 범위와 비교하는 신호, 그리고 하한·상한의 포함(이상/초과, 이하/미만) 확인",
    "no_subject_in_value_field": "블록 이름(Name)이 이 범위의 주어인지, 그리고 하한·상한의 포함(이상/초과, 이하/미만) 확인",
}
REVIEW_REASONS = frozenset(REVIEW_TEXT) - {"no_subject_in_value_field", "deadline_or_window"}   # skip → review
_VALUE_FIELDS = frozenset({"Range"})
_WINDOW_CLAUSE = re.compile(r"않으면|하면|되면|이면|경우|(?<=[가-힣])면(?=\s|$|,)|\s시(?=\s|$|,)|때")
# (R45 review I3) what the generator **read** where the words are silent — stepped, and shown so a reader can confirm it
READ_TEXT = {
    "read_as_range": ("연결어 없이 붙은 하한·상한을 범위(그리고)로 읽어 스텝함",
                      "범위가 맞는지 확인(다른 뜻이면 이 경계 TC 의 판정이 바뀐다)"),
    "read_as_one_quantity": ("같은 단위를 한 값에서 나누는 두 이름을 한 양의 두 구간으로 읽어 스텝함",
                             "두 이름이 한 신호의 구간인지 확인(다른 신호면 상대 구간의 판정은 근거가 없다)"),
}
MAX_REVIEW_ITEMS = 30     # items kept for the quality report (all counted; the document lists all)


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
#   Name, Type, ASIL, Priority, Rationale, pin allocation, element names, failure rates — carry no stimulus).
#   (R47) a SyDS element's ``Input Information`` (``BAT 전압(9V 이상 16.0V 이하), 5V, …`` · ``Watchdog Input(Pulse 주기
#   5ms 이하)`` · ``5000RPM 초과``) states where the element's input is — R46 read it as evidence only
SYSTEM_TEXT_FIELDS = ("Description", "Functional Behavior", "System Behavior", "Condition", "Action", "Range",
                      "Time Constraint", "Verification criteria", "Input Information")
# (R47) what a step on an input cell says: the input is inside or outside what the cell writes (a normal range or a
#   trigger — the cell does not say which), never the element's reaction. ⚠ a field stating what the element puts out
#   (an "Output Information") belongs to `SYSTEM_OUTCOME_FIELDS`, not here (review X5)
SYSTEM_INPUT_FIELDS = frozenset({"Input Information"})
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
        out[rid] = {"doc": label, "fields": {_FIELD_BY_KEY[k]: v for k, v in cells_map.items() if k in _FIELD_BY_KEY},
                    # (R45 review W1) not read for facts — a ``Range`` value's subject is often the block's name
                    "name": cells_map.get("name", "")}
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
    its own text (a heading in one never makes the next an outcome), under the SRS requirement's ID. (R47) The input
    ranges come after every other traced fact, so a TC numbered before R47 keeps its number."""
    stats = stats if stats is not None else Counter()
    out, inputs = [], []
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
            (inputs if field in SYSTEM_INPUT_FIELDS else out).extend(
                (line, fact, source) for line in _field_lines(str(req.get("id", "")), field, text)
                for fact in line["facts"])
    return out + inputs


def _field_lines(anchor: str, field: str, text: str) -> list[dict[str, Any]]:
    """The fact lines of one system block field, read under the SRS ID ``anchor`` (`extract` opens a block at an SRS
    ID line — the ID names nothing else here). An outcome field is read under an ``<Output>`` heading."""
    head = "<Output>\n" if field in SYSTEM_OUTCOME_FIELDS else ""
    return [line for b in extract(f"ID\t{anchor}\n{head}{text}\n") for line in b["lines"]]


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


# (R45) the comparison that holds exactly where the other does not, at the same value
_COMPLEMENT = {">=": "<", "<": ">=", ">": "<=", "<=": ">"}


def _condition_fact(f: dict) -> bool:
    return f["kind"] == "threshold" and f.get("op") in _COMPLEMENT and not f.get("negated") \
        and isinstance(f.get("value"), (int, float)) and not isinstance(f.get("value"), bool)


def _partition_partners(line: dict, fact: dict) -> list[dict]:
    """(R45) ``Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하)``: two names, one unit, joined
    by *or*, that **split the unit at one value** — one of them ``< v`` (``<= v``), the other ``>= v`` (``> v``), one name
    a parenthesis owner — are one quantity in two regions, not two quantities to hold apart. R32 review C1 held both back
    because a step on one told the tester to hold the other false where it holds; with the split written that way, each
    point's verdict of the other name is known, and the step writes it. The other names' facts of that unit on the line
    are returned (empty: not such a split)."""
    unit = fact.get("unit") or ""
    name = subject_of(fact)
    if not unit or not name or not _condition_fact(fact):
        return []
    in_unit = [f for f in line["facts"] if _condition_fact(f) and (f.get("unit") or "") == unit and subject_of(f)]
    mine = [f for f in in_unit if subject_of(f) == name]
    others = [f for f in in_unit if subject_of(f) != name]
    split = {subject_of(g) for f in mine for g in others
             if g["op"] == _COMPLEMENT[f["op"]] and exact_value(g) == exact_value(f)
             and "paren_owner" in (f.get("signal_kind"), g.get("signal_kind")) and joint(line, f, g) == "or"}
    partners = [g for g in others if subject_of(g) in split]
    heads: dict[str, dict] = {}
    for g in partners:
        heads.setdefault(str(subject_of(g)), g)
    # (R45 review W4) a region whose own conditions do not join as written (``B조건(0.8m/s 이상, 2.0m/s 이상)``) has no
    #   verdict at a point: no split — back to the R32 C1 hold
    if any(line_holds(exact_value(g), g, line) is None for g in heads.values()):
        return []
    return partners


def _label_shares_a_quantity(line: dict, fact: dict, partners: list[dict] | None = None) -> bool:
    """(R32 review C1 · r2 W2) ``Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 …)`` / ``도어 속도가
    0.8m/s 미만이거나 Tip-To-Run 조건(0.8m/s 이상)``: a label before a parenthesis names a condition, not a quantity —
    with another condition (a threshold or a range, not negated, not an obligation) in the same non-empty unit under
    another name, joined to it by a **stated** *or* / *and*, the two may be one quantity (the door speed). Then the
    stated join would make the step hold the other "false" / "true" at a point where it is not the step's to say (a step
    said 불성립 at 0.8 m/s and told the tester to hold Tip-To-Run false there). An unstated join already tells the tester
    to check it and stays. (R45) A partner of a split at one value (`_partition_partners`) is no longer a doubt."""
    unit = fact.get("unit") or ""
    if not unit:
        return False
    raw = line.get("raw") or line["text"]
    for other in line["facts"]:
        if other is fact or any(other is p for p in partners or ()) \
                or other["kind"] not in {"threshold", "range"} or other.get("status") != "parsed" \
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
    if fact["kind"] == "threshold" and _label_shares_a_quantity(line, fact, _partition_partners(line, fact)):
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


def _not_a_condition(line: dict, fact: dict) -> bool:
    """A deadline (``100ms 이내``), an outcome line (``<Output>`` / ``Output :`` / a system Action) or an obligation
    (``…이하여야 한다``) — what the requirement produces or bounds, never a stimulus (`_conflict_role`)."""
    return fact.get("role") == "response_constraint" or _conflict_role(line, fact, False) == "outcome"


def _review_reason(line: dict, fact: dict, why: str, source: dict | None) -> str:
    """(R45) Why a held-back fact is a review item — ``""`` when it is not one. (review W2) A response constraint, an
    outcome line or an obligation is no condition to decide (a subject would not make it a step) — except (r2 W-R2-2)
    an ``이내`` inside a conditional clause (``… 이내에 … 되지 않으면``), which may be the condition's time window."""
    raw = line.get("raw") or line["text"]
    if fact.get("role") == "response_constraint" and _conflict_role(line, fact, False) != "outcome" \
            and _WINDOW_CLAUSE.search(raw[fact["line_span"][1]:fact["line_span"][1] + 60]):
        return "deadline_or_window"
    if why not in REVIEW_REASONS or _not_a_condition(line, fact):
        return ""
    if why == "no_subject_for_value" and source and source["field"] in _VALUE_FIELDS:
        return "no_subject_in_value_field"
    return why


def _review_item(req: dict, line: dict, fact: dict, source: dict | None, reason: str, kind: str,
                 block_name: str = "") -> dict[str, Any]:
    item = {"srs_id": req.get("id", ""), "source": source_label(source), "reason": reason, "kind": kind,
            "line": line["text"], "line_sha256": line["sha256"], "fact": str(fact.get("raw") or ""),
            "fact_kind": fact.get("kind", ""), "line_span": list(fact.get("line_span") or []),
            "block_name": block_name, **_numeric_identity(fact)}
    if kind == "held_back":
        # (R46 review W1) what filling would do, tried in this very sentence
        try:
            item["if_filled"], item["fill_check"] = fill_guidance(line, fact, reason)
        except Exception as exc:  # noqa: BLE001 — guidance never costs the review item or the boundary TCs
            item["if_filled"], item["fill_check"] = f"— (채우기 안내를 만들지 못함: {type(exc).__name__})", "unchecked"
    return item


def _numeric_identity(fact: dict) -> dict[str, Any]:
    """(R46) What a review item's value is, exactly and JSON-safe — ``{"unit", "op", "value"}`` for a comparison,
    ``{"unit", "lo", "hi"}`` for a range (``0x1000 ~ 0x2000`` → ``4096`` / ``8192``); ``{}`` for anything else. The
    evidence search matches other sentences on it."""
    unit = fact.get("unit") or ""
    value = fact.get("value")
    if fact.get("kind") == "range" and isinstance(value, list) and len(value) == 2:
        texts = fact.get("value_text") or [None, None]
        try:
            lo, hi = (exact_value({"value_text": t, "value": v}) for t, v in zip(texts, value, strict=True))
        except (ArithmeticError, ValueError, TypeError):
            return {}
        return {"unit": unit, "lo": str(lo), "hi": str(hi)}
    if fact.get("kind") in {"threshold", "duration"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"unit": unit, "op": fact.get("op"), "value": str(exact_value(fact))}
    return {}


def _subject_text(fact: dict) -> str:
    if fact["kind"] == "duration":
        named = fact.get("signal") if fact.get("signal_kind") not in {"parameter", "identifier"} else None
        return (named or "조건") + DURATION_SUFFIX
    return subject_of(fact) or ""


def _condition_text(line: dict, fact: dict) -> str:
    def one(f):
        return f"{f.get('value_text') or f['value']}{f.get('unit') or ''} {_OP_TEXT[f['op']]}"
    units, join = condition_units(line, fact)
    if any(len(u) > 1 for u in units):
        # (R45 review W3) a range read from meaning is one unit, as `line_holds` judges it: ``4V 이하 또는 (5V 이상
        #   그리고 6V 이하)`` — in written order
        joiner = " 또는 " if join == "or" else " 그리고 "
        return _subject_text(fact) + " " + joiner.join(
            ("(" if len(units) > 1 and len(u) > 1 else "") + " 그리고 ".join(one(f) for f in u)
            + (")" if len(units) > 1 and len(u) > 1 else "") for u in units)
    parts = [fact] + [f for f in line["facts"] if same_subject(fact, f)]
    joins = {joint(line, fact, f) for f in parts[1:]}
    joiner = " 또는 " if joins == {"or"} else " 그리고 "
    return _subject_text(fact) + " " + joiner.join(one(f) for f in parts)


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
    partners = _partition_partners(line, fact)
    siblings = [g for g in line["facts"] if same_subject(fact, g)]
    if any(join_is_inferred(line, a, b) for a in [fact] + siblings for b in [fact] + siblings if a is not b):
        # (R45) the words give no connective between the subject's bounds; the one meaningful reading was taken
        notes.append(f"같은 주어의 결합 [{_condition_text(line, fact)}]: 원문에 연결어 없음 — 항상 참·항상 거짓이 아닌 "
                     "유일한 읽기로 판정")
    for f in line["facts"]:
        if f is fact or same_subject(fact, f) or f["kind"] not in {"threshold", "duration", "symbolic", "range"}:
            continue
        if any(same_subject(f, g) for g in done):
            continue
        done.append(f)
        group = [f] + [g for g in line["facts"] if g is not fact and same_subject(f, g)]
        inner = {joint(line, f, g) for g in group[1:]}
        text = (" 또는 " if inner == {"or"} else " 그리고 ").join(_fact_text(g) for g in group)
        if any(f is p for p in partners):
            # (R45) one quantity in two regions: the other name is neither held true nor false — its verdict at each
            #   point is written in the step (R32 review C1 said "불성립 상태로 둔다" where it held)
            notes.append(f"같은 양을 나눈 조건 [{_condition_text(line, f)}]: 원문의 두 이름이 같은 단위를 한 값에서 "
                         "나눈다 — 한 양의 두 구간으로 읽어 각 점에서의 판정을 스텝 기대 결과에 적는다")
            continue
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
                   system: dict[str, dict[str, Any]] | None = None,
                   review: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One group of steps per fact used: ``[{"steps": [...], "evidence": {...}}]``. With ``system`` (parsed SyRS /
    SyDS blocks), the facts of the system blocks the requirement cites follow its own (``evidence["source"]`` names
    the block; counters prefixed ``traced:``). (R45) ``review`` receives every fact held back for a reason a reader can
    settle (`REVIEW_REASONS` — a missing subject, an unwritten join, a range's inclusion …): the requirement ID, the
    source, the sentence, the fact and the reason — shown in the document and on the web, never filled by a guess."""
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
            reason = _review_reason(line, fact, why, source) if review is not None else ""
            if reason:
                block_name = str(((system or {}).get(source["id"]) or {}).get("name") or "") \
                    if reason == "no_subject_in_value_field" and source else ""
                review.append(_review_item(req, line, fact, source, reason, "held_back", block_name))
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
        input_cell = bool(source) and source["field"] in SYSTEM_INPUT_FIELDS   # (R47)
        # (R45) the other region(s) of one quantity split at a value: one fact per name — its verdict is the line's
        heads: dict[str, dict] = {}
        for g in _partition_partners(line, fact):
            heads.setdefault(str(subject_of(g)), g)  # the name's first fact: its conditions read in written order
        partner_heads = list(heads.values())
        if review is not None:
            # (R45 review I3) what was read, not written — stepped, and listed for a reader to confirm
            if partner_heads:
                review.append(_review_item(req, line, fact, source, "read_as_one_quantity", "read"))
            if any(join_is_inferred(line, fact, g) for g in line["facts"] if same_subject(fact, g)):
                review.append(_review_item(req, line, fact, source, "read_as_range", "read"))
        for p in (value - delta, value, value + delta):
            if bounds and not bounds[0] <= p <= bounds[1]:
                stats[prefix + "points_outside_subject_type"] += 1   # ``u16g_X 0 초과`` has no −1 (review r4 I-2)
                continue
            verdict = line_holds(p, fact, line)
            action = (f"{ACTION_PREFIX}{_subject_text(fact)} = {_fmt(p, fact)}{unit}{predicate}{reference}"
                      f"{BASIS_MARK}{fact['raw']}{origin}")
            # (review r3 C-1) the verdict is the sentence's, not the whole requirement's: outside its condition the
            #   sentence claims nothing (another sentence may describe what happens there)
            partner_verdicts = [(g, line_holds(p, g, line)) for g in partner_heads]
            other = " · ".join(f"[{_condition_text(line, g)}] {_VERDICT_TEXT[v]}" for g, v in partner_verdicts)
            if input_cell:
                # (R47 review W1 · W4) an input cell states where the input is, not what the element does: a normal range
                #   (SySM_04 ``BAT 전압(9V 이상 16.0V 이하)`` — inside it a power monitor reports *no* fault) and a
                #   trigger (SyFN_10 ``5000RPM 초과``) read alike, so neither side claims a reaction — the requirement's
                #   other sentences decide it. First, also over a split of one quantity (which would claim an action)
                expected = (f"조건 [{condition}] {'성립' if verdict else '불성립'} → {whose}입력 칸이 적은 범위 "
                            f"{'안' if verdict else '밖'}" + (f"(같은 양을 나눈 조건 {other})" if partner_heads else "")
                            + f" — 요소의 반응(이상 판정·리셋 등)은 같은 요구의 다른 문장 판정을 따른다: "
                            f"{_clip(line['text'], 160)}")
            elif partner_heads:
                # (R45) the stepped condition's verdict stays first (``조건 […] 성립 →`` is what a reader — and the
                #   cross scorer — takes as the step's verdict); the other region's follows, at the same point
                if verdict:
                    expected = (f"조건 [{condition}] 성립 → {whose}이 문장이 이 조건에 기술한 동작 수행 확인"
                                f"(같은 양을 나눈 조건 {other}): {_clip(line['text'], 160)}")
                elif any(v for _g, v in partner_verdicts):
                    expected = (f"조건 [{condition}] 불성립 → {whose}이 조건의 구간 아님(같은 양을 나눈 조건 {other} — "
                                f"그 조건의 판정을 따른다): {_clip(line['text'], 160)}")
                else:
                    # outside every region the line names (``1.4m/s`` past Tip-To-Run's 1.3 and Manual Assist's 0.8):
                    #   the sentence claims nothing there — or, when a region's verdict is unknown, says so
                    expected = (f"조건 [{condition}] 불성립 → {whose}이 문장의 동작 대상 아님(같은 양을 나눈 조건 {other} — "
                                f"같은 요구의 다른 문장 판정을 따른다): {_clip(line['text'], 160)}")
            else:
                expected = (f"조건 [{condition}] 성립 → {whose}이 문장이 기술한 동작 수행 확인: {_clip(line['text'], 160)}"
                            if verdict else
                            f"조건 [{condition}] 불성립 → {whose}이 문장의 동작 대상 아님(같은 요구의 다른 문장 판정을 "
                            f"따른다): {_clip(line['text'], 160)}")
            steps.append({"action": action, "expected": expected})
            used.append({"point": _fmt(p, fact), "holds": verdict})
        stats[prefix + "facts_used"] += 1
        stats[prefix + "steps"] += len(steps)
        if input_cell:
            # (R47 review I4) the disclosure tells the input ranges apart — the traced counts grew with them
            stats["traced:input_range_facts_used"] += 1
            stats["traced:input_range_steps"] += len(steps)
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


def _is_input(group: dict) -> bool:
    """(R47) A group stepped from a SyDS element's input range (`SYSTEM_INPUT_FIELDS`)."""
    source = group["evidence"]["source"]
    return bool(source) and source["field"] in SYSTEM_INPUT_FIELDS


# ── (R46) evidence for review items, and what filling the gap would improve ──────────────────────────────────────────
# 2026-09-30 user direction: what is missing is first looked for in the other documents; what is still missing is shown
#   with what filling it would improve. A candidate is quoted, never used — the same number may be another quantity.
MAX_EVIDENCE = 3          # candidates quoted per item (all are counted)
_EVIDENCE_ANCHOR = "SwEvidence_0"   # `extract` opens a block at an SRS ID line; a system block is read under this one
_DOC_ORDER = {"SRS": 0, "SyRS": 1, "SyDS": 2}


def _steppable(line: dict, fact: dict) -> bool:
    """A fact this module would turn into boundary steps (`_skip_reason` empty) — the form a candidate must have."""
    return fact["kind"] in {"threshold", "duration"} and not _skip_reason(line, fact)


# (R46 review I1) one quantity written in two units is one value: ``3초`` = ``3s`` = ``3000ms``
_UNIT_SCALE = {"ms": ("s", Decimal("0.001")), "s": ("s", Decimal(1)), "초": ("s", Decimal(1)), "분": ("s", Decimal(60)),
               "mV": ("V", Decimal("0.001")), "mA": ("A", Decimal("0.001")), "℃": ("°C", Decimal(1)),
               "KPH": ("km/h", Decimal(1)), "rpm": ("RPM", Decimal(1))}   # (R47 review I2)


def _match_key(unit: str, value: Decimal) -> tuple[str, Decimal]:
    base, scale = _UNIT_SCALE.get(unit, (unit, Decimal(1)))
    return base, value * scale


def review_evidence_corpus(requirements: list[dict], system: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Every steppable fact of the given documents, by value: all SRS requirements (description and verification
    criteria) and all SyRS / SyDS blocks — not only the cited ones — every text field (a SyDS element's ``Input
    Information`` too). ``singles[(unit, value)]`` — one comparison; ``ranges[(unit, lo, hi)]`` — a line's lower and upper bound of one
    subject (``BAT 전압(9V 이상 16.0V 이하)``); units normalised (`_match_key`). Each candidate: where (``SRS
    SwTR_0605`` / ``SyDS SyEL_05 · Input Information``), the condition as the steps would write it, its operator,
    whether it names its subject (an unnamed hold time does not) and how weakly (a noun before a parenthesis), the line
    and its hash, and the SRS requirement or system block it belongs to (a related sentence or not)."""
    singles: dict[tuple, list] = {}
    ranges: dict[tuple, list] = {}
    documents: list[str] = ["SRS"]

    def add(line: dict, where: str, owner: str) -> None:
        ok = [f for f in line["facts"] if _steppable(line, f)]
        for f in ok:
            singles.setdefault(_match_key(f.get("unit") or "", exact_value(f)), []).append(
                {"where": where, "owner": owner, "condition": _condition_text(line, f), "op": f["op"],
                 # an unnamed hold time (``특정시간(300ms) 이상 유지``) names no subject to borrow
                 "named": _subject_text(f) != "조건" + DURATION_SUFFIX,
                 "weak": f.get("signal_kind") == "paren_owner",     # (review I12, as R32 I4)
                 "line": _clip(line["text"], 160), "line_sha256": line["sha256"]})
        for lo in ok:
            for hi in ok:
                if lo is hi or lo["op"] not in {">", ">="} or hi["op"] not in {"<", "<="} or not same_subject(lo, hi) \
                        or not exact_value(lo) < exact_value(hi):
                    continue
                unit = lo.get("unit") or ""
                ranges.setdefault(_match_key(unit, exact_value(lo)) + _match_key(unit, exact_value(hi))[1:], []).append(
                    {"where": where, "owner": owner, "condition": _condition_text(line, lo), "op": "range",
                     "named": True, "weak": lo.get("signal_kind") == "paren_owner",
                     "line": _clip(line["text"], 160), "line_sha256": line["sha256"]})

    for req in requirements:
        seen: set[int] = set()
        for line, _ in requirement_facts(req):
            if id(line) not in seen:
                seen.add(id(line))
                add(line, f"SRS {req.get('id', '')}", str(req.get("id", "")))
    for sid, block in (system or {}).items():
        if block["doc"] not in documents:
            documents.append(block["doc"])
        for field, text in ((f, block["fields"].get(f)) for f in SYSTEM_TEXT_FIELDS):
            if text:
                for line in _field_lines(_EVIDENCE_ANCHOR, field, text):
                    add(line, source_label({"doc": block["doc"], "id": sid, "field": field}), sid)
    return {"singles": singles, "ranges": ranges, "documents": documents}


def _relation(item_op: str | None, cand_op: str) -> str:
    """(R46 review W3) how a candidate's comparison stands to the item's: ``same``; ``flip`` — the other boundary
    inclusion (``이상`` ↔ ``초과``, the R33 "경계 포함 불일치" of the same sheet); ``opposite`` — the other side
    (``이하`` ↔ ``초과``: the complement or another condition); ``range`` — a range item has no written inclusion."""
    if cand_op == "range":
        return "range"
    if cand_op == item_op:
        return "same"
    return "flip" if _INCLUSION_FLIP.get(str(item_op)) == cand_op else "opposite"


_RELATION_ORDER = {"range": 0, "same": 0, "flip": 1, "opposite": 2}


def _evidence_for(item: dict[str, Any], corpus: dict[str, Any], cited: dict[str, list[str]]) -> list[dict[str, Any]] | None:
    """The candidates for one held-back item — ``None`` when the item has no unit (a bare ``3`` — or ``0 ~ 65535``, the
    domain of every 16-bit variable — matches everywhere: review I2). The item's own fact is never a candidate (it is
    not steppable); another comparison of its sentence can be (review W4: ``u16g_A 가 4.85V 미만 시 경고, 4.85V 미만
    유지 시 정지``). An unnamed hold time counts only in a related requirement (it names no subject, and the value alone
    is no link). Related sentences (the item's requirements and the blocks they cite) first, then the same comparison,
    the other inclusion, the other side; then SRS · SyRS · SyDS."""
    unit = item.get("unit") or ""
    if not unit:
        return None
    if item.get("lo") is not None:
        pool = corpus["ranges"].get(_match_key(unit, Decimal(item["lo"])) + _match_key(unit, Decimal(item["hi"]))[1:], [])
    elif item.get("value") is not None:
        pool = corpus["singles"].get(_match_key(unit, Decimal(item["value"])), [])
    else:
        return None
    ids = [str(x) for x in item.get("srs_ids") or [item.get("srs_id")] if x]
    related = set(ids) | {sid for rid in ids for sid in cited.get(rid, [])}
    out: list[dict[str, Any]] = []
    keys: set[tuple] = set()
    for c in pool:
        key = (c["where"], c["condition"])
        if key in keys or not (c["named"] or c["owner"] in related):
            continue
        keys.add(key)
        out.append({"where": c["where"], "condition": c["condition"], "line": c["line"],
                    "line_sha256": c["line_sha256"], "related": c["owner"] in related, "weak_subject": c["weak"],
                    "inclusion": _relation(item.get("op"), c["op"])})
    out.sort(key=lambda c: (not c["related"], _RELATION_ORDER[c["inclusion"]],
                            _DOC_ORDER.get(c["where"].split(" ", 1)[0], len(_DOC_ORDER))))
    return out


# ── what filling the gap would do — tried in the item's own sentence (review W1) ─────────────────────────────────────
# The fill is written into the sentence, the sentence read again alone, and the item's value must then step under the
# written name while no value of the sentence that stepped before stops (``Pull-Up 전원 : 2.25V 이상 ~ Pull-Up 전원
# 2.75V 이하`` — the name written twice makes both unstated, and 2.25 V lost its step). What cannot be written in
# (a negation, a deadline, a label, a join whose meaning the shape does not tell) is a rewrite: its example keeps the
# sentence's meaning, and its form is exercised by tests.
# (review r2 I-b) placeholders a document does not use; (r2 W7) the Korean one is two words — a one-word name is read
#   together with an unparticled word before it (``따라 대상신호``), as a reader's own two-word name (``도어 각도``) is not
_FILL_NAME = "채움 신호"
_FILL_IDENT = "u16g_FillSignal"    # a C identifier — a noun after the value can take a Korean name's place
_FILL_MONITORED = "채움량"
_SEPARATOR_GAP = re.compile(r"[\s,~∼/]*")
_FILL_STEPS = "이 값의 경계 스텝(값−분해능·값·값+분해능)이 생긴다"
_VERIFIED = " — 이 문장에 넣어 확인"
_REWRITE = " — 예시 형태는 시험으로 확인, 원문 뜻대로 다시 쓸 것"
_SUBJECT_REASONS = frozenset({"no_subject_for_value", "subject_unclear", "no_subject_in_value_field"})


def _alone(raw: str) -> dict[str, Any] | None:
    """The line read again on its own (no heading, no neighbour) — both sides of a fill are read this way. (review r2)
    Whether a fact of a review item's line steps depends on the line alone: its section only says "outcome", and an
    outcome line makes no review item."""
    got = [ln for b in extract(f"ID\t{_EVIDENCE_ANCHOR}\n{raw}\n") for ln in b["lines"]]
    return got[0] if len(got) == 1 else None


def _value_key(f: dict) -> tuple:
    return (f.get("unit") or "", exact_value(f), f.get("op"))


def _stepped_by_key(line: dict | None) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = {}
    if line is None:
        return out
    for f in line["facts"]:
        if isinstance(f.get("value"), (int, float)) and not isinstance(f.get("value"), bool) and _steppable(line, f):
            out.setdefault(_value_key(f), []).append(f)
    return out


def _baseline(raw: str) -> Counter:
    """How many facts of each (unit, value, operator) step in the line as written (review r2 I-c: counted, so one of two
    equal comparisons lost is seen)."""
    return Counter({k: len(v) for k, v in _stepped_by_key(_alone(raw)).items()})


# (review r3 I-h) the other reasons a filled sentence may still not step, in words
_SKIP_TEXT = {"value_outside_subject_type": "값이 신호 이름이 선언한 폭 밖", "output_requirement": "의무문(출력)으로 읽힘",
              "outcome_section": "결과 절로 읽힘", "reference_label": "기준 이름표로 읽힘",
              "response_constraint": "응답 기한('이내')으로 읽힘", "not_an_order_comparison": "크기 비교가 아님",
              "kind_range": REVIEW_TEXT["kind_range"][0], "kind_symbolic": "값이 아니라 이름과 비교"}


def _try_fill(raw: str, targets: list[tuple[tuple, str | None]], baseline: Counter) -> str:
    """``""`` when every target value steps under its name (``None``: under any name) and every value that stepped
    before still steps as often; otherwise why not, in the review's own words."""
    line = _alone(raw)
    if line is None:
        return "다시 읽지 못함"
    stepped = _stepped_by_key(line)
    for key, name in targets:
        hits = stepped.get(key, [])
        if not hits:
            held = [f for f in line["facts"] if isinstance(f.get("value"), (int, float))
                    and not isinstance(f.get("value"), bool) and _value_key(f) == key]
            why = _skip_reason(line, held[0]) if held else ""
            if not why:
                return "그 값을 다시 읽지 못함"
            return REVIEW_TEXT[why][0] if why in REVIEW_TEXT else _SKIP_TEXT.get(why, f"스텝 조건이 아님({why})")
        if name is not None and not any(name in {subject_of(f), f.get("signal")} for f in hits):
            return f"적은 이름이 주어로 읽히지 않음(주어로 '{_subject_text(hits[0])}' 를 읽음)"
    lost = sorted(k for k, n in baseline.items() if len(stepped.get(k, [])) < n)
    if lost:
        return "같은 줄의 " + ", ".join(f"{k[1]}{k[0]} {_OP_TEXT.get(k[2], k[2])}" for k in lost) + " 스텝이 사라짐"
    return ""


def _placeholders(text: str) -> str:
    return text.replace(_FILL_IDENT, "u16g_<신호>").replace(_FILL_NAME, "<신호>").replace(_FILL_MONITORED, "<감시량>")


def _excerpt(raw: str, start: int, end: int) -> str:
    """The changed part of a filled sentence with a little context, placeholders shown as such."""
    a, b = max(0, start - 30), min(len(raw), end + 12)
    return _placeholders(("…" if a else "") + raw[a:b].strip() + ("…" if b < len(raw) else ""))


def _bounds(a: dict, b: dict) -> str:
    """How two comparisons of one quantity stand: ``range`` — a lower bound below an upper one (only *and* means
    anything, R45); ``apart`` — the lower above the upper: outside a band (*or* — ``4.85V 미만/5.15V 초과``) or an entry
    and a return (a hysteresis — ``8.5V 이하, 9.0V 이상 복귀``), which the shape does not tell (review r2 W8, as R45 C1);
    ``one_side`` — two bounds on one side (either join means something); ``empty`` — both sides of one value or an
    empty range on the written grid (``9V 미만 9V 이상`` · ``10 초과 11 미만``: *and* never holds, *or* always does —
    review r3 I-g, as R45 I1)."""
    lower = [f for f in (a, b) if f["op"] in {">", ">="}]
    upper = [f for f in (a, b) if f["op"] in {"<", "<="}]
    if len(lower) != 1 or len(upper) != 1:
        return "one_side"
    lo_f, hi_f = lower[0], upper[0]
    grid = min(written_step(lo_f), written_step(hi_f))
    lo = exact_value(lo_f) + (grid if lo_f["op"] == ">" else 0)
    hi = exact_value(hi_f) - (grid if hi_f["op"] == "<" else 0)
    if lo <= hi:
        return "range"
    return "apart" if exact_value(lo_f) > exact_value(hi_f) else "empty"


_APART = ("대역 밖(이거나)인지, 진입·복귀 같은 두 조건(히스테리시스 — 두 문장으로 나눠 적기)인지 원문 뜻으로 정해야 한다 — 모양으로는 "
          "가를 수 없다")
_EMPTY = ("같은 값의 양쪽이거나 빈 범위라 '이고' 면 늘 거짓, '이거나' 면 늘 참이다 — 원문 뜻을 정해 다시 써야 한다(결합어만으로는 뜻이 "
          "생기지 않는다)")


def _previous_in_unit(line: dict, fact: dict) -> dict | None:
    """The comparison right before ``fact`` in its unit, joined to it by nothing but a separator (``/`` ``~`` ``,``)."""
    raw = line.get("raw") or line["text"]
    s = fact["line_span"][0]
    before = [f for f in line["facts"] if f is not fact and f["kind"] in {"threshold", "duration"}
              and f.get("op") in _ORDER and (f.get("unit") or "") == (fact.get("unit") or "")
              and f["line_span"][1] <= s]
    if not before:
        return None
    prev = max(before, key=lambda f: f["line_span"][1])
    return prev if _SEPARATOR_GAP.fullmatch(raw[prev["line_span"][1]:s]) else None


def _joined(line: dict, prev: dict, fact: dict, conn: str, name: str | None) -> tuple[str, int, int]:
    """``prev`` and ``fact`` joined by ``conn`` (the separator between them replaced), with ``name`` written once before
    ``prev`` — the filled line and the span of the change."""
    raw = line.get("raw") or line["text"]
    s, e = fact["line_span"]
    p0, p1 = prev["line_span"]
    head = (name + " ") if name else ""
    filled = raw[:p0] + head + raw[p0:p1] + conn + " " + raw[s:]
    return filled, p0, p1 + len(head) + len(conn) + 1 + (e - s)


def _fill_subject(line: dict, fact: dict, baseline: Counter) -> tuple[str, str]:
    raw = line.get("raw") or line["text"]
    s, e = fact["line_span"]
    key = _value_key(fact)
    prev = _previous_in_unit(line, fact)
    if prev is not None:
        prev_name = subject_of(prev)
        name = None if prev_name else _FILL_NAME
        shape = _bounds(prev, fact)
        if shape == "range":
            # one quantity's lower and upper bound: join them (``2.25V 이상이고 2.75V 이하``) — naming the value again
            #   makes both an unstated join (review W1)
            filled, a, b = _joined(line, prev, fact, "이고", name)
            if not _try_fill(filled, [(key, prev_name or _FILL_NAME), (_value_key(prev), prev_name or _FILL_NAME)],
                             baseline):
                how = "결합어로 이어" if prev_name else "신호 이름을 한 번 적고 결합어로 이어"
                return (f"앞 값과 같은 신호면 {how} 적으면(예: '{_excerpt(filled, a, b)}') {_FILL_STEPS}{_VERIFIED}"
                        + ("(신호 이름만 다시 적으면 결합 미기재로 두 값이 모두 보류된다)" if prev_name else ""), "verified")
        elif shape == "apart":
            filled, a, b = _joined(line, prev, fact, "이거나", name)
            example = "" if _try_fill(filled, [(key, prev_name or _FILL_NAME)], baseline) else \
                f" 대역 밖이면 예: '{_excerpt(filled, a, b)}'(이 문장에 넣어 스텝 확인)."
            return f"앞 값과 한 신호면 {_APART}.{example}", "rewrite"
        elif shape == "empty":
            return f"앞 값과 한 신호면 {_EMPTY}. 다른 신호면 비교하는 신호 이름을 값 앞에 적는다", "rewrite"
    whys = []
    attempts = ((raw[:s] + _FILL_NAME + " " + raw[s:], _FILL_NAME, "비교하는 신호 이름을 값 앞에"),
                (raw[:s] + _FILL_IDENT + " " + raw[s:], _FILL_IDENT, "비교하는 변수 이름(C 식별자)을 값 앞에"))
    for filled, name, how in attempts:
        why = _try_fill(filled, [(key, name)], baseline)
        if not why:
            start = filled.index(name)
            note = f" — 한국어 이름은 이 문장에서 주어로 읽히지 않는다: {whys[0]}" if name == _FILL_IDENT else ""
            return (f"{how} 적으면(예: '{_excerpt(filled, start, start + len(name) + 1 + e - s)}') {_FILL_STEPS}"
                    f"{_VERIFIED}{note}", "verified")
        whys.append(why)
    return f"이 문장에서는 신호 이름을 적어도 스텝되지 않는다 — {whys[-1]}. 그것까지 원문에서 풀어야 한다", "needs_more"


def _fill_range(line: dict, fact: dict, baseline: Counter) -> tuple[str, str]:
    raw = line.get("raw") or line["text"]
    s, e = fact["line_span"]
    lo_t, hi_t = (str(t) for t in fact["value_text"])
    unit = fact.get("unit") or ""
    named = fact.get("signal") and not _UNCLEAR_SUBJECT.search(str(fact.get("signal")).strip())
    insert = "" if named else _FILL_NAME + " "
    written = raw[s:e]
    # (review r2 I-a) the range's match ends in the space before what follows (``0 ~ 5000 RPM``): keep it
    body = f"{lo_t}{unit} 이상이고 {hi_t}{unit} 이하" + written[len(written.rstrip()):]
    filled = raw[:s] + insert + body + raw[e:]
    lo = {"value_text": lo_t, "value": fact["value"][0]}
    hi = {"value_text": hi_t, "value": fact["value"][1]}
    name = None if named else _FILL_NAME
    why = _try_fill(filled, [((unit, exact_value(lo), ">="), name), ((unit, exact_value(hi), "<="), name)], baseline)
    if why:
        return f"이 문장에서는 두 비교로 적어도 스텝되지 않는다 — {why}. 그것까지 원문에서 풀어야 한다", "needs_more"
    return (f"하한·상한의 포함과 주어를 정해 두 비교로 적으면(예: '{_excerpt(filled, s, s + len(insert) + len(body))}' — "
            f"포함은 정한 대로) 하한·상한의 경계 스텝이 생긴다{_VERIFIED}(`~` 범위로는 주어가 있어도 스텝하지 않는다)", "verified")


def _fill_join(line: dict, fact: dict, baseline: Counter) -> tuple[str, str]:
    raw = line.get("raw") or line["text"]
    siblings = [g for g in line["facts"] if same_subject(fact, g) and joint(line, fact, g) == "unstated"]
    if not siblings:
        return "같은 주어의 두 조건 사이에 '이고'(그리고) 또는 '이거나'(또는)를 원문 뜻대로 적는다", "rewrite"
    other = min(siblings, key=lambda g: abs(g["line_span"][0] - fact["line_span"][0]))
    first, second = sorted((fact, other), key=lambda f: f["line_span"][0])
    shape = _bounds(first, second)
    if shape == "apart":
        return f"두 조건이 {_APART}", "rewrite"          # (review r2 W8) ``8.5V 이하, 9.0V 이상 복귀``
    if shape == "empty":
        return f"두 조건이 {_EMPTY}", "rewrite"          # (review r3 I-g) ``9V 미만 9V 이상``
    if not _SEPARATOR_GAP.fullmatch(raw[first["line_span"][1]:second["line_span"][0]]):
        return ("같은 주어의 두 조건 사이에 '이고'(그리고) 또는 '이거나'(또는)를 원문 뜻대로 적는다(사이의 말까지 다시 써야 해 이 "
                "문장에 넣어 보지는 못했다)", "rewrite")
    works = []
    for conn in ("이고",) if shape == "range" else ("이고", "이거나"):
        filled, a, b = _joined(line, first, second, conn, None)
        if not _try_fill(filled, [(_value_key(fact), subject_of(fact))], baseline):
            works.append((filled, a, b))
    if not works:
        return "이 문장에서는 결합어를 적어도 스텝되지 않는다 — 원문을 다시 써야 한다", "needs_more"
    filled, a, b = works[0]
    which = "이고·이거나 어느 쪽이든 스텝된다" if len(works) == 2 else "하한·상한이라 뜻 있는 결합은 이고뿐"
    return f"두 조건 사이에 원문 뜻대로 결합어를 적으면(예: '{_excerpt(filled, a, b)}' — {which}) {_FILL_STEPS}{_VERIFIED}", \
        "verified"


def _fill_monitored(line: dict, fact: dict, baseline: Counter) -> tuple[str, str]:
    raw = line.get("raw") or line["text"]
    e = fact["line_span"][1]
    filled = raw[:e] + "인 " + _FILL_MONITORED + raw[e:]
    why = _try_fill(filled, [(_value_key(fact), _FILL_MONITORED)], baseline)
    if why:
        return f"이 문장에서는 감시량을 적어도 스텝되지 않는다 — {why}", "needs_more"
    return (f"기준 상수 뒤에 비교하는 감시량을 적으면(예: '{_excerpt(filled, fact['line_span'][0], e + 2 + len(_FILL_MONITORED))}'"
            f") {_FILL_STEPS}{_VERIFIED}", "verified")


# (review r2 W5) a negation on the comparison itself: ``… 미만이 아닌/아니면/아닐/아님``, ``… 이상을 벗어나면``, ``… 이하 제외``,
#   ``… 이하가 되지 않으면`` — its example is the complement
#   (review r3 W9) and a hold time's own verb negated: ``300ms 이상 유지하지 않으면`` / ``… 지속되지 않으면`` — held less long
_NEGATED_COMPARISON = re.compile(r"\s*(?:이|가|을|를|은|는)?\s*(?:아(?:닌|니|닐|님)|벗어나|제외|(?:(?:유지|지속)\s*)?(?:하|되)지\s*않)")
# (review r3 W9 · r4 W10) a negated clause — every ending of ``않`` / ``못`` / ``아니`` / ``없`` (``되지 않은 경우``, ``받지
#   못하는``, ``아닐 경우``), but not the adverb ``없이`` (``이상 없이 복귀할 경우`` is a positive clause)
_NEGATIVE_WINDOW = re.compile(r"않|못|아(?:니|닌|닐|님)|없(?!이)")


def _fill_rewrite(line: dict, fact: dict, reason: str) -> str:
    """(review W2 · r2 W5 · W6) An example that keeps the sentence's meaning: a negated comparison is the complement
    (``8.5V 미만이 아닌`` → ``8.5V 이상``); a hold time with a negated predicate names the negation (``300ms 이상 수신되지
    않는`` → ``미수신 300ms 이상``); any other negation gets no example with a comparison word in it. ``이내`` is read as
    ``이하``: in a negative clause the non-event outlasts it (``20ms 이내에 … 되지 않으면`` → ``20ms 초과 유지되면``), in a
    positive one the condition lasts at most that long (``500ms 이내에 9V 이상으로 복귀`` → ``500ms 이하 유지 후``)."""
    raw = line.get("raw") or line["text"]
    e = fact["line_span"][1]
    value = f"{fact.get('value_text') or fact.get('value')}{fact.get('unit') or ''}"
    if reason == "negated_condition":
        if _NEGATED_COMPARISON.match(raw[e:]) and fact.get("op") in _COMPLEMENT:
            return (f"비교에 걸린 부정은 반대 비교로 적으면(예: '<신호> {value} {_OP_TEXT[_COMPLEMENT[fact['op']]]}') "
                    f"{_FILL_STEPS}{_REWRITE}")
        if (fact.get("unit") or "") in _TIME_UNIT_NAMES:
            return (f"부정을 조건 이름에 담아 부정 없이 적으면(예: '<신호> 미수신 {fact.get('raw')}' — '수신되지 않는' → '미수신' "
                    f"처럼) {_FILL_STEPS}{_REWRITE}")
        return ("부정이 비교에 걸리는지(반대 비교로) 서술어에 걸리는지(부정을 조건 이름에) 정해 부정 없이 적으면 이 값의 경계 스텝이 "
                "생긴다 — 원문 뜻대로 다시 쓸 것")
    if reason == "deadline_or_window":
        if _NEGATIVE_WINDOW.search(raw[e:e + 60]):
            example = f"'<조건> 이 {value} 초과 유지되면'"
        else:
            example = f"'<조건> 이 {value} 이하 유지 후'"
        return (f"조건의 시간 창이면 {example} 처럼 유지 시간으로 적으면 경계 스텝이 생기고(원문 '이내' 를 이하로 읽음 — 문서의 "
                f"다른 곳이 '미만'이면 경계 포함 불일치), 응답 기한이면 지금대로(측정 항목) 둔다{_REWRITE}")
    if reason == "parenthesis_labels_may_share_a_quantity":
        return ("괄호 앞 이름 대신 비교하는 신호 이름을 적는다 — 두 조건이 한 신호면 같은 이름과 결합어로, 다른 신호면 각자의 이름으로"
                f"(예: 'u16s_Speed 가 0.8m/s 미만 또는 u16s_Speed 가 2.0m/s 이상'){_REWRITE}")
    return "—"


_TIME_UNIT_NAMES = frozenset({"ms", "s", "초", "분"})


def fill_guidance(line: dict, fact: dict, reason: str) -> tuple[str, str]:
    """(R46) What writing the gap into the requirement would produce, and how that was checked: ``verified`` — written
    into this sentence and read again, the value steps and nothing stepped before stops; ``needs_more`` — tried here
    and not enough (the text says what else holds it back); ``rewrite`` — the sentence has to be rewritten or its
    meaning decided first (a negation, a deadline, a label, a lower bound above an upper one), the example's form is
    exercised by tests."""
    raw = line.get("raw") or line["text"]
    baseline = _baseline(raw)
    if fact["kind"] == "range" and isinstance(fact.get("value_text"), list) and len(fact["value_text"]) == 2:
        return _fill_range(line, fact, baseline)
    if fact["kind"] not in {"threshold", "duration"} or not isinstance(fact.get("value"), (int, float)) \
            or isinstance(fact.get("value"), bool):
        return "—", "rewrite"
    if reason in _SUBJECT_REASONS:
        return _fill_subject(line, fact, baseline)
    if reason == "same_subject_combination_unstated":
        return _fill_join(line, fact, baseline)
    if reason == "monitored_quantity_unknown":
        return _fill_monitored(line, fact, baseline)
    return _fill_rewrite(line, fact, reason), "rewrite"


_FILL_READ = "확인만 — 이미 스텝했다. 원문에 연결어나 한 신호 이름을 적으면 이 확인 항목이 사라진다"
_FILL_CONFLICT = "한쪽 포함으로 통일하면 이 후보가 사라진다(경계 스텝은 지금도 각 문장대로 판정한다)"


def if_filled(item: dict[str, Any]) -> str:
    """(R46) The item's 'If Filled' text: a held-back item carries its own (`fill_guidance`, made where the sentence
    is at hand); a reading is to confirm; a conflict disappears when one inclusion is chosen."""
    if item.get("if_filled"):
        return str(item["if_filled"])
    if item.get("kind") == "inclusion_conflict":
        return _FILL_CONFLICT
    if item.get("kind") == "read":
        return _FILL_READ
    return "—"


def attach_review_evidence(items: list[dict[str, Any]], requirements: list[dict],
                           system: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """(R46) Give every held-back item with a value its ``evidence`` (the first `MAX_EVIDENCE` candidates) and
    ``evidence_total`` — ``None`` when not searched. Returns the counts for the quality report: items searched, items
    with a candidate (and with a related one), the documents searched, and how each 'If Filled' was checked."""
    held = [it for it in items if it.get("kind") == "held_back"]
    fill_checks = dict(sorted(Counter(str(it.get("fill_check") or "unchecked") for it in held).items()))
    if not held:
        return {"review_evidence_searched": 0, "review_evidence_found": 0, "review_evidence_related": 0,
                "review_evidence_documents": [], "review_fill_checks": fill_checks}
    corpus = review_evidence_corpus(requirements, system)
    cited = {str(r.get("id", "")): cited_system_ids(r) for r in requirements}
    # everything is computed before any item changes — a failure leaves every item as it was (the caller discloses it)
    updates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    searched = found = related = 0
    for it in held:
        cands = _evidence_for(it, corpus, cited)
        if cands is None:
            updates.append((it, {"evidence": None}))    # not searched: no unit — the same number is everywhere
            continue
        searched += 1
        found += bool(cands)
        related += any(c["related"] for c in cands)
        updates.append((it, {"evidence": cands[:MAX_EVIDENCE], "evidence_total": len(cands)}))
    for it, update in updates:
        it.update(update)
    return {"review_evidence_searched": searched, "review_evidence_found": found,
            "review_evidence_related": related, "review_evidence_documents": corpus["documents"],
            "review_fill_checks": fill_checks}


_INCLUSION_TAG = {"flip": " [포함 다름]", "opposite": " [방향 반대]"}


def _evidence_text(item: dict[str, Any]) -> str:
    """The sheet's evidence cell: the candidates, or that none was found in the documents searched, why none was
    searched, or that the search failed — ``—`` for an item that is no gap (a reading, a conflict) or an output from
    before R46."""
    if item.get("evidence_error"):
        return f"근거 탐색 실패 — {item['evidence_error']}"
    if "evidence" not in item:
        return "—"
    cands = item["evidence"]
    if cands is None:
        return "탐색 안 함 — 단위 없는 값(같은 수가 흔해 짝짓지 않는다)"
    if not cands:
        return "준 문서의 다른 문장에 같은 값·단위를 스텝할 수 있게 적은 곳 없음 — 적을 말부터 요구 문서에서 정해야 한다"
    parts = [f"{c['where']}: {c['condition']}" + (" [괄호 앞 명사]" if c.get("weak_subject") else "")
             + (" [같은 요구·인용]" if c.get("related") else "") + _INCLUSION_TAG.get(str(c.get("inclusion")), "")
             + f" — {c['line']}" for c in cands]
    more = int(item.get("evidence_total") or len(cands)) - len(cands)
    return ("; ".join(parts) + (f" 외 {more}건" if more > 0 else "")
            + " (같은 값을 스텝할 수 있게 적은 다른 문장 — 같은 양인지 확인 후 옮길 것)")


def append_requirement_boundary_tcs(test_cases: list[dict], requirements: list[dict], build_tc, make_tc_id,
                                    classify, max_steps: int = 12,
                                    system: dict[str, dict[str, Any]] | None = None,
                                    review_out: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Append requirement-boundary TCs after each requirement's existing TCs, numbering on from them. A fact's points
    never split across TCs; a TC holds as many whole facts as fit in ``max_steps`` (at least one), all from the same
    document (the SRS, or the system requirements it cites — R29). Returns the counts for the quality report.
    (R45) ``review_out`` receives **every** review item for the document's 'Requirement Review' sheet — the held-back
    facts a reader can settle (one row per sentence and fact, however many requirements cite that block) and the
    requirement-document inclusion conflicts; the report keeps the first `MAX_REVIEW_ITEMS` and the counts."""
    stats: Counter = Counter()
    fanout: Counter = Counter()
    review: list[dict[str, Any]] = []
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
        groups = boundary_steps(req, stats, system, review)
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
            # (R47 review W3) an input range never joins a behaviour sentence's TC: a TC numbered before R47 keeps
            #   its steps (it did only by the data's luck — a note or a full last TC), and one TC says one kind of thing
            if not alone and chunks and not chunks[-1][0]["evidence"]["combination_note"] and \
                    _doc_of(chunks[-1][0]) == _doc_of(g) and _is_input(chunks[-1][0]) == _is_input(g) and \
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
            if _is_input(chunk[0]):
                stats["traced:input_range_tcs"] += 1
            for g in chunk:
                if g["evidence"]["source"]:
                    fanout[g["evidence"]["source"]["id"]] += 1
    if added:   # nothing added: the TC order is left exactly as it was (review r4 I-4)
        order = {r["id"]: i for i, r in enumerate(requirements)}
        test_cases.extend(added)
        test_cases.sort(key=lambda tc: order.get(str(tc.get("srs_id") or ""), len(order)))  # stable
    out: dict[str, Any] = {k: v for k, v in sorted(stats.items())}
    # (R45) one row per held-back sentence and fact: a block cited by several requirements names them all
    merged: dict[tuple, dict[str, Any]] = {}
    for item in review:
        # a held-back fact is its own row; a reading is one row per sentence (its facts listed)
        span = tuple(item["line_span"]) if item["kind"] == "held_back" else None
        key = (item["source"], item["line_sha256"], span, item["reason"])
        row = merged.setdefault(key, {**item, "srs_ids": [], "facts": []})
        if item["srs_id"] not in row["srs_ids"]:
            row["srs_ids"].append(item["srs_id"])
        if item["fact"] not in row["facts"]:
            row["facts"].append(item["fact"])
            row["fact"] = " · ".join(row["facts"])
    for row in merged.values():
        del row["facts"]
    review_items = [{k: v for k, v in r.items() if k != "srs_id"} for r in merged.values()]
    review_items.sort(key=lambda r: (not str(r["srs_ids"][0]).startswith("SwTSR"), str(r["srs_ids"][0]), r["source"]))
    # held back first (what the documents leave undecided), then what was read (to confirm)
    review_items.sort(key=lambda r: r["kind"] != "held_back")
    out["review_item_count"] = len(review_items)
    out["review_read_count"] = sum(1 for r in review_items if r["kind"] == "read")
    out["review_by_reason"] = dict(sorted(Counter(r["reason"] for r in review_items).items()))
    try:
        # (R46) the other sentences of the given documents that state an item's value steppably, and what filling
        #   the gap would improve
        out.update(attach_review_evidence(review_items, requirements, system))
    except Exception as exc:  # noqa: BLE001 — an optional finding never costs the boundary TCs (as review I8)
        out["review_evidence_error"] = f"{type(exc).__name__}: {exc}"[:200]
        for r in review_items:
            if r["kind"] == "held_back":
                r["evidence_error"] = out["review_evidence_error"]   # (review I4) the sheet says so, not "—"
    out["review_items"] = review_items[:MAX_REVIEW_ITEMS]
    if review_out is not None:
        review_out.extend(review_items)
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
        if review_out is not None:
            review_out.extend({**c, "kind": "inclusion_conflict"} for c in conflicts)   # the document lists them all
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


REQUIREMENT_REVIEW_HEADERS = ["Kind", "SRS ID", "Source Document", "Fact", "Reason", "To Decide",
                              # (R46) what writing the gap into the requirement produces · other sentences of the given
                              #   documents that state the value steppably (quoted, never used)
                              "If Filled", "Evidence (Other Sentences)", "Source Line", "Line SHA-256"]
REQUIREMENT_REVIEW_SHEET = "Requirement Review"
_CONFLICT_ROLE_TEXT = {"condition": "조건끼리", "outcome": "결과 기준끼리", "stimulus": "시험 입력(검증 기준) ↔ 요구 조건"}


def write_requirement_review_sheet(wb, items: list[dict[str, Any]] | None) -> int:
    """(R45) 'Requirement Review' sheet: what the requirement documents leave undecided or state two ways — the facts
    held back from boundary steps for a reason a reader can settle (`REVIEW_TEXT`), what the generator read where the
    words are silent (`READ_TEXT`, stepped — to confirm) and the inclusion conflicts (R33/R43).
    Nothing here is filled by the generator: each row says what to decide. A sheet of that name from a template made of
    an earlier output is removed first; no item — no sheet (the quality report's counts say whether it was looked at).
    Returns rows written."""
    if REQUIREMENT_REVIEW_SHEET in wb.sheetnames:
        del wb[REQUIREMENT_REVIEW_SHEET]
    if not items:
        return 0
    ws = wb.create_sheet(REQUIREMENT_REVIEW_SHEET)
    ws.append(REQUIREMENT_REVIEW_HEADERS)
    for it in items:
        if it.get("kind") == "inclusion_conflict":
            a, b = it.get("a") or {}, it.get("b") or {}
            flag = (" · 한 출처 안의 두 줄(다른 조건·동작일 수 있음)" if it.get("within_source") else "") + (
                "" if it.get("same_subject") else " · 한쪽 주어 없음" if it.get("subject_missing") else " · 주어 이름이 다름")
            ws.append(["요구 문서 경계 포함 불일치", it.get("srs_id", ""), f"{a.get('source')} ↔ {b.get('source')}",
                       f"{a.get('subject')} {a.get('text')} ↔ {b.get('subject')} {b.get('text')}",
                       f"같은 값·단위를 경계 포함만 달리 적음({_CONFLICT_ROLE_TEXT.get(str(it.get('role')), it.get('role'))})"
                       + flag,
                       "어느 쪽이 맞는지 문서 검토로 정한다(경계 TC 는 각 문장대로 판정)",
                       if_filled(it), "—",
                       _clip(f"{a.get('line')} ↔ {b.get('line')}", 300), "—"])
            continue
        reason = str(it.get("reason"))
        why, decide = {**REVIEW_TEXT, **READ_TEXT}.get(reason, (reason, "원문 확인"))
        if it.get("fact_kind") == "range" and reason in RANGE_DECIDE:
            decide = RANGE_DECIDE[reason]      # (review r2 W-R2-1) a range makes no boundary step, subject or not
        if it.get("block_name"):
            why += f" (블록 이름 '{_clip(str(it['block_name']), 80)}')"
        ws.append(["읽은 결합 — 확인" if it.get("kind") == "read" else "검토 필요 조건",
                   ", ".join(it.get("srs_ids") or []), it.get("source", ""), it.get("fact") or "—",
                   why, decide, if_filled(it), _clip(_evidence_text(it), 1000),
                   _clip(str(it.get("line") or ""), 300), it.get("line_sha256") or "—"])
    return len(items)
