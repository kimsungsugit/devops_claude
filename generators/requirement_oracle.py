"""Quantitative requirement model (R5, P3): what a requirement sentence states as a checkable condition.

A requirement oracle for STS — independent of the source code. From the requirement text (SRS), each requirement block
yields *facts*: a signal compared with a value (``u16g_ApiIn_Vsup: 1604 초과`` → ``u16g_ApiIn_Vsup > 1604``,
``Battery 전압이 8.5V미만`` → ``Battery 전압 < 8.5 V``), how facts on one line combine (``또는``/``||`` → or,
``이고``/``&&`` → and), and a hold time (``500ms이상 유지`` → duration ≥ 500 ms). Every fact keeps its source span
(offsets into the text) and the hash of its line, so a test case built on it can say where its judgement comes from.

Nothing is inferred beyond the words: a fact needs an explicit number and an explicit comparison word or operator;
the signal is the C identifier or the noun phrase the sentence attaches to the number — when neither is found the fact
is kept with ``signal: None`` and status ``partial`` (a value with no subject is not a testable condition). Units are
those written; no scaling (``8.50 V`` is not converted to ADC counts — that needs the HSIS/design resolution).

Every numeric fact keeps ``value_text`` — the number **as written** (``4.00``, ``0x1FF0``): its precision is the only
step the text states. ``이내`` bounds a response the system must meet (``안정화 시간 : 100ms 이내``) — ``role:
response_constraint``, not a stimulus. A condition whose clause is negated (``… 미만이 아닌 경우``, ``… 되지
않으면``) carries ``negated: True``. A value in parentheses after an identifier (``Param_X( 3도 ) 초과한 열림각``) and a
named hold time (``u16s_X_TM : 100ms``) are *reference constants*: ``signal_kind: parameter`` with the quantity actually
compared kept as ``monitored`` (``열림각``) when the sentence names it.

How two facts of a line join is read from the words **between them** (``joint``): ``또는``/``||`` → or, ``이고``/
``&&`` → and, a hold time → and (it qualifies the condition), anything else — a comma, nothing, two different
connectives — unstated. ``holds``/``line_holds`` give the verdict of a point for one fact or for a line's conditions on
one subject (the single definition the STS generator and the evaluator share); ``written_step`` is one unit of the
precision a value is written with.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Any

SCHEMA_VERSION = 1

_REQ_ID = re.compile(r"\b(Sw(?:TR|TSR|EI|NF|ST|STR|SR|FR|FN|IF|RS)_[A-Za-z0-9_]+?\d+)\b")
_UNIT = r"(?:km/h|m/s|step|deg|KPH|℃|°C|mV|mA|ms|Hz|V|s|초|분|도|%|A)"  # longest first: ``step`` is not ``s``
_NUM = r"0[xX][0-9A-Fa-f]+|-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"
_KOREAN_OP = {"이상": ">=", "이하": "<=", "미만": "<", "초과": ">", "이내": "<="}
_C_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
# a C identifier as projects name signals: lower-case prefix + underscore (u16g_ApiIn_Vsup) or CamelCase (DoorPitch)
# no ``\b``: Korean particles are word characters (``u16g_ApiIn_MotorSpeed가``)
_SIGNAL_IDENT = re.compile(r"(?<![A-Za-z0-9_])(?:[a-z][a-z0-9]{0,5}_[A-Za-z0-9_]+|[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)"
                           r"(?![A-Za-z0-9_])")

_KOREAN_FACT = re.compile(rf"(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?\s*(?P<op>이상|이하|미만|초과|이내)")
_C_FACT = re.compile(rf"(?P<lhs>{_C_IDENT})\s*(?P<op>>=|<=|==|!=|>|<)\s*(?P<rhs>{_NUM}|{_C_IDENT})")
# ``Param_AntipinchReverseActAngle( 3도 ) 초과`` — the value in parentheses right after the signal it sets
_PAREN_FACT = re.compile(rf"(?P<sig>{_C_IDENT})\s*\(\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?\s*\)\s*(?P<op>이상|이하|미만|초과)")
_COLON_FACT = re.compile(rf"(?P<sig>{_C_IDENT})\s*:\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?\s*(?P<op>이상|이하|미만|초과)")
_RANGE_FACT = re.compile(rf"(?P<lo>{_NUM})\s*(?P<unit1>{_UNIT})?\s*~\s*(?P<hi>{_NUM})\s*(?P<unit>{_UNIT})?")
_DURATION = re.compile(
    rf"(?:(?P<sym>{_C_IDENT})\s*:\s*)?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>ms|초|s|분)\s*\)?\s*"
    rf"(?P<op>이상|초과|이내)?\s*(?:하여|해서|하여서)?\s*(?:동안|을|를)?\s*(?:유지|지속|동안|경과)")
_OR = re.compile(r"또는|이거나|\bOR\b|\|\|")
_AND = re.compile(r"이고|그리고|\bAND\b|&&")
_TIME_UNITS = {"ms": 0.001, "s": 1.0, "초": 1.0, "분": 60.0}
_C_KEYWORDS = frozenset({"if", "else", "while", "for", "return", "define", "U8", "U16", "U32", "S8", "S16", "S32", "F32"})


def _number(text: str) -> float | int:
    text = text.replace(",", "")
    if text.lower().startswith("0x"):
        return int(text, 16)
    return float(text) if "." in text else int(text)


def split_requirements(text: str) -> list[dict[str, Any]]:
    """Requirement blocks: from each ``ID<TAB>Sw..._nn`` attribute line to the next one (the SRS table layout)."""
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^ID\t(Sw[A-Za-z]+_[A-Za-z0-9_]+)\s*$", text)]
    blocks = []
    for i, (start, req_id) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        # the heading line just above (``3.3.6.4<TAB>SwTR_0605: title``) belongs to the previous block's tail — cut it
        tail = re.search(r"(?m)^\d+(?:\.\d+)+\t", text[start:end])
        if tail and tail.start() > 0:
            end = start + tail.start()
        blocks.append({"req_id": req_id, "start": start, "end": end, "text": text[start:end]})
    return blocks


_PARTICLE = re.compile(r"(이|가|은|는|의|을|를|에서|로|으로)$")
_NOT_SUBJECT = frozenset({"특정", "기준", "시간", "범위인", "상태", "경우", "값이", "값", "이상", "이하", "미만", "초과", "또는", "이거나",
                          "거나", "그리고", "상태로", "상태에서", "전압으로", "만약", "만일"})
_NEGATION = re.compile(r"않|아닌|아니|아닐|아님|없|제외|못|벗어나")
# (R20) not a subject word: a whole quantity token (``500ms``, ``8.6V)이``, ``10ms마다``) or a time postposition
#   (``이내에``, ``동안``, ``후``). Whole-token matches only — ``2차 전압`` keeps ``2차`` (review W1: a leading digit alone
#   cut the subject to ``전압``).
_TIME_POSTPOSITION = re.compile(r"(?:이내|동안|이후|이전|후|뒤|전|경과|마다)(?:에|에도|부터)?")
_QUANTITY_WORD = re.compile(rf"[-+]?(?:{_NUM})(?:{_UNIT})?\)?(?:{_TIME_POSTPOSITION.pattern})?")
_CLAUSE_END = re.compile(r"[,.;→]|경우|때|시\b|면\s")
# ``0.6m/s이상의 Door 속도`` — the subject follows the value
_SUBJECT_AFTER = re.compile(r"^\s*의\s+([A-Za-z가-힣][A-Za-z0-9가-힣_]*(?:\s+[A-Za-z가-힣][A-Za-z0-9가-힣_]*)?)")
# ``… 초과한 열림각에서`` / ``… 이하의 도어 열림각`` — the quantity a parameter threshold is compared with
_MONITORED_AFTER = re.compile(r"^\s*(?:한|인|하는|된|일|의)?\s*([A-Za-z가-힣][A-Za-z0-9가-힣_]*)"
                              r"(?:\s+([A-Za-z가-힣][A-Za-z0-9가-힣_]*))?")
# words that follow a comparison but name nothing (review round 3 W3: ``초과 시`` gave the subject "시")
_FUNCTION_WORDS = frozenset({"시", "후", "때", "및", "또는", "경우", "동안", "이상", "이하", "미만", "초과", "이내", "상태",
                             "값", "조건", "경과", "유지", "지속", "이면", "이고", "되면", "하면"})
# ``15초이상 끊길 경우`` — what lasts that long
_PREDICATE_AFTER = re.compile(r"^\s*([가-힣]+)")
_VERB_END = re.compile(r"(?:다|며|면|고|서|는데|하여|되어|인|한|할|된|될|길|질)$")


def _signal_before(line: str, pos: int) -> tuple[str | None, str]:
    """The subject of a number at ``pos``: the last C identifier / CamelCase name before it in its clause, else the
    one or two words right before it with the particle removed (``Battery 전압이`` → ``Battery 전압``).
    ``(None, "")`` when there is none."""
    # ``(`` opens a clause only while it is still open at the value: ``Load(Average)는 70% 이하`` keeps ``Load(Average)``
    open_paren = line.rfind("(", 0, pos)
    if open_paren >= 0 and ")" in line[open_paren:pos]:
        open_paren = -1
    clause_start = max([line.rfind(sep, 0, pos) for sep in (",", "또는", "이거나", "||", " OR ", " or ", "및", "- ", "·",
                                                            ":")]
                       + [open_paren])
    clause = line[clause_start + 1 if clause_start >= 0 else 0:pos]
    idents = [m for m in _SIGNAL_IDENT.finditer(clause) if m.group(0) not in _C_KEYWORDS]
    if idents:
        return idents[-1].group(0), "identifier"
    tokens = [t for t in re.split(r"\s+", clause.strip(" (-")) if t]
    words: list[str] = []
    for token in reversed(tokens[-3:]):
        bare = _PARTICLE.sub("", token.strip("()[]"))
        if _QUANTITY_WORD.fullmatch(bare) or _TIME_POSTPOSITION.fullmatch(bare):
            # (R20) ``B+ < 8.6V)이 500ms 이내에 9V 이상``: a quantity or a time postposition among the words before the
            #   value is another condition, not the subject — ``500ms 이내에`` was the subject of ``9V 이상`` (KJPDS02
            #   SwTR_0605). The subject words collected after it (nearer the value) stay.
            break
        if not bare or bare in _NOT_SUBJECT or not re.search(r"[A-Za-z가-힣]", bare) \
                or bare.upper() in {"OR", "AND"} or re.search(r"(?:거나|이고|하고)$", bare) \
                or re.search(r"(?:며|면|여|서|고|되|는데)$", token):   # a verb ending closes the clause before it
            break
        words.insert(0, bare)
        if bare != token:           # a particle ends the subject phrase: the word before may still belong to it
            continue
        if len(words) >= 2:
            break
    phrase = " ".join(words[-2:]).strip(" ·•-")
    if phrase:
        return phrase, "phrase"
    # ``저 전압 고장 검출 기준 전압: 8.50V 이하`` — a label ending in ``:`` right before the value names it
    label = re.search(r"(?:^|[-·•]\s*|\t)([^:\t]{2,40}?)\s*:\s*$", line[:pos])
    if label and re.search(r"[A-Za-z가-힣]", label.group(1)) and not re.search(r"\d\s*$", label.group(1)):
        idents = [m.group(0) for m in _SIGNAL_IDENT.finditer(label.group(1)) if m.group(0) not in _C_KEYWORDS]
        if idents:
            # ``s16g_ApiIn_MotorPosition 입력: 0 이하`` — the label names a signal: that is the subject (review r2 W5)
            return idents[-1], "identifier"
        name = label.group(1).strip(" -·•")
        if "기준" in name:
            # ``저 전압 고장 검출 기준 전압: 8.50V 이하`` names the threshold itself, not a quantity to set (r3 W1)
            return name, "reference_label"
        return name, "label"
    return None, ""


def _share_subjects(line: str, facts: list[dict]) -> None:
    """``A 이 8.5V미만이거나 16.04V 이상``: a value whose clause names no subject, joined to the previous fact only by a
    connective, compares the same subject (``subject_shared``)."""
    for prev, fact in zip(facts, facts[1:], strict=False):   # pairs of neighbours: lengths differ by one
        if fact["kind"] not in {"threshold", "range"} or prev["kind"] not in {"threshold", "range"}:
            continue
        between = line[prev["_end"]:fact["_start"]]
        connective = re.fullmatch(r"\s*(?:이거나|거나|또는|or|OR|,|이고|고)?\s*(?:인|인\s*경우)?\s*", between)
        if prev.get("signal") and connective and (not fact.get("signal") or fact.get("signal_kind") == "phrase"):
            fact["signal"], fact["signal_kind"], fact["subject_shared"] = prev["signal"], prev["signal_kind"], True


def _line_facts(line: str, offset: int) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []
    if line.count(">") >= 4:
        return facts  # a folder path (``전사 폴더>현보>…``), not a condition

    def free(a, b):
        return all(b <= s or a >= e for s, e in taken)

    for m in _DURATION.finditer(line):
        if not free(m.start("num"), m.end()):
            continue
        taken.append((m.start("num"), m.end()))
        op = _KOREAN_OP.get(m.group("op") or "", ">=" if "유지" in m.group(0) or "지속" in m.group(0) else "==")
        value = _number(m.group("num"))
        facts.append({"kind": "duration", "signal": m.group("sym"), "op": op, "value": value, "unit": m.group("unit"),
                      # (review r2 C-B) ``u16s_MAGNET_ERR_TM : 100ms`` names the reference time, not what is held
                      **({"signal_kind": "parameter"} if m.group("sym") else {}),
                      "value_text": m.group("num"), "seconds": round(value * _TIME_UNITS[m.group("unit")], 6),
                      "span": [offset + m.start(), offset + m.end()], "raw": m.group(0),
                      **({"role": "response_constraint"} if m.group("op") == "이내" else {})})
    for m in _PAREN_FACT.finditer(line):
        if not free(m.start(), m.end()) or m.group("sig") in _C_KEYWORDS:
            continue
        taken.append((m.start(), m.end()))
        # (review r2 C-B) ``Param_X( 3도 ) 초과한 열림각``: Param_X is the reference constant; the opening angle is set
        mon = _MONITORED_AFTER.match(line[m.end():])
        monitored = None
        if mon:
            first = _PARTICLE.sub("", mon.group(1))
            second = _PARTICLE.sub("", mon.group(2) or "")
            if first and first not in _FUNCTION_WORDS and first not in _NOT_SUBJECT and not _VERB_END.search(first):
                # ``도어 열림각에서`` — a second noun belongs to the name; a particle on the first word ends it
                two = second and mon.group(1) == first and second not in _FUNCTION_WORDS \
                    and not _VERB_END.search(second) and second not in _NOT_SUBJECT
                monitored = f"{first} {second}" if two else first
        facts.append({"kind": "threshold", "signal": m.group("sig"), "signal_kind": "parameter",
                      "monitored": monitored,
                      "op": _KOREAN_OP[m.group("op")], "value": _number(m.group("num")), "unit": m.group("unit") or "",
                      "value_text": m.group("num"), "span": [offset + m.start(), offset + m.end()], "raw": m.group(0)})
    for m in _COLON_FACT.finditer(line):
        if not free(m.start(), m.end()):
            continue
        taken.append((m.start(), m.end()))
        facts.append({"kind": "threshold", "signal": m.group("sig"), "signal_kind": "identifier",
                      "op": _KOREAN_OP[m.group("op")], "value": _number(m.group("num")), "unit": m.group("unit") or "",
                      "value_text": m.group("num"), "span": [offset + m.start(), offset + m.end()], "raw": m.group(0)})
    for m in _C_FACT.finditer(line):
        if not free(m.start(), m.end()) or m.group("lhs") in _C_KEYWORDS:
            continue
        taken.append((m.start(), m.end()))
        rhs = m.group("rhs")
        numeric = re.fullmatch(_NUM, rhs) is not None
        facts.append({"kind": "threshold" if numeric else "symbolic", "signal": m.group("lhs"), "signal_kind": "identifier",
                      "op": m.group("op"), "value": _number(rhs) if numeric else None,
                      "value_text": rhs if numeric else None, "reference": None if numeric else rhs, "unit": "",
                      "span": [offset + m.start(), offset + m.end()], "raw": m.group(0)})
    for m in _RANGE_FACT.finditer(line):
        if not free(m.start(), m.end()):
            continue
        taken.append((m.start(), m.end()))
        signal, how = _signal_before(line, m.start())
        facts.append({"kind": "range", "signal": signal, "signal_kind": how, "op": "in_range",
                      "value": [_number(m.group("lo")), _number(m.group("hi"))],
                      "value_text": [m.group("lo"), m.group("hi")],
                      "unit": m.group("unit") or m.group("unit1") or "",
                      "span": [offset + m.start(), offset + m.end()], "raw": m.group(0)})
    for m in _KOREAN_FACT.finditer(line):
        if not free(m.start(), m.end()):
            continue
        taken.append((m.start(), m.end()))
        signal, how = _signal_before(line, m.start())
        after = _SUBJECT_AFTER.match(line[m.end():])
        if after and how not in {"identifier", "label"}:
            # ``0.6m/s이상의 Door 속도`` — the noun the value qualifies comes after it (review W5); a verb (``값을
            # 입력한다``) or a non-subject word is not one (review r2 W5)
            words = after.group(1).split()
            if words and _VERB_END.search(words[-1]) and len(words) > 1:
                words = words[:-1]
            noun = _PARTICLE.sub("", " ".join(words)).strip()
            if noun and noun.split()[0] not in _NOT_SUBJECT and not _VERB_END.search(noun):
                signal, how = noun, "phrase_after"
        unit = m.group("unit") or ""
        value = _number(m.group("num"))
        fact = {"kind": "threshold", "signal": signal, "signal_kind": how, "op": _KOREAN_OP[m.group("op")],
                "value": value, "unit": unit, "value_text": m.group("num"),
                "span": [offset + m.start(), offset + m.end()], "raw": m.group(0)}
        if unit in _TIME_UNITS and how != "identifier" and signal:
            # ``LIN 통신이 15초이상 끊길 경우`` — how long a condition lasts, not a value to set (review W5); the verb
            # says what lasts (``끊길``) — without it the step would read "keep the communication" (review r2 W6)
            fact.update(kind="duration", seconds=round(value * _TIME_UNITS[unit], 6))
            pred = _PREDICATE_AFTER.match(line[m.end():])
            if pred and not re.search(r"(?:면|으면|면서|거나|고)$", pred.group(1)):
                fact["predicate"] = pred.group(1)   # ``끊길`` — not ``중단되면`` (a condition, review r3 W5)
        if m.group("op") == "이내":
            fact["role"] = "response_constraint"
        facts.append(fact)
    facts.sort(key=lambda f: f["span"][0])
    cells = line.split("\t")
    row = cells[0].strip(" -[]") if len(cells) > 1 else ""   # ``- [u8g_X]<TAB>…`` too
    if row and _SIGNAL_IDENT.fullmatch(row):
        # a table row (``u16g_ApiIn_Vsup<TAB>850 ~ 1,604<TAB>8.50V ~ 16.04V``): its values describe the row's signal
        for f in facts:
            if not f.get("signal") or f.get("signal_kind") == "phrase":
                f["signal"], f["signal_kind"] = row, "table_row"
    for f in facts:
        f["_start"], f["_end"] = f["span"][0] - offset, f["span"][1] - offset
    _share_subjects(line, facts)
    for f in facts:
        # (review C2) a negation in the rest of the clause turns the condition around: ``8.5V 미만이 아닌 경우``
        rest = line[f["_end"]:]
        end = _CLAUSE_END.search(rest)
        if _NEGATION.search(rest[:end.end() if end else len(rest)]):
            f["negated"] = True
        del f["_start"], f["_end"]
    for f in facts:
        f["line_span"] = [f["span"][0] - offset, f["span"][1] - offset]   # within the raw line (joint reads it)
    for f in facts:
        f["status"] = "parsed" if f.get("signal") or f["kind"] == "duration" else "partial"
        if f["status"] == "partial":
            f["reason"] = "no_subject_for_value"
    return facts


def _combination(line: str, facts: list[dict]) -> str:
    conditions = [f for f in facts if f["kind"] in {"threshold", "symbolic", "range"}]
    if len(conditions) < 2:
        return "single"
    between = line
    if _OR.search(between) and not _AND.search(between):
        return "or"
    if _AND.search(between) and not _OR.search(between):
        return "and"
    return "mixed_or_unstated"


_OUTCOME_SECTION = re.compile(r"완료|output|출력|결과|expected", re.IGNORECASE)


def is_outcome_section(section: str) -> bool:
    """``<완료조건>`` / ``<Output>``: what the requirement produces, not a condition to stimulate (review r3 W6)."""
    return bool(section) and bool(_OUTCOME_SECTION.search(section))


def exact_value(fact: dict[str, Any]) -> Decimal:
    """The fact's value as written, exactly (``4.74`` is not the binary float 4.7400000000000002)."""
    text = fact.get("value_text")
    if isinstance(text, str) and text:
        t = text.replace(",", "")
        return Decimal(int(t, 16)) if t.lower().lstrip("-").startswith("0x") else Decimal(t)
    return Decimal(str(fact["value"]))


def holds(point, fact: dict[str, Any], op: str | None = None, value=None) -> bool:
    """Does ``point`` satisfy the fact's comparison (optionally with another operator / value — a mutant)? Exact
    decimal arithmetic on the written values."""
    op = op or fact["op"]
    value = exact_value(fact) if value is None else Decimal(str(value))
    point = Decimal(str(point))
    return {"<": point < value, "<=": point <= value, ">": point > value, ">=": point >= value,
            "==": point == value, "!=": point != value}[op]


_COMPARISONS = {"<", "<=", ">", ">=", "==", "!="}


def subject_of(fact: dict[str, Any]) -> str | None:
    """What a stimulus sets for this fact: the monitored quantity of a parameter threshold, else the signal."""
    return fact.get("monitored") if fact.get("signal_kind") == "parameter" and fact["kind"] == "threshold" \
        else fact.get("signal")


def same_subject(fact: dict[str, Any], other: dict[str, Any]) -> bool:
    """Two conditions on one subject. A fact without a subject (an unnamed hold time) shares it with nothing — two
    unnamed hold times of two conditions are not one quantity (review r4 C-2)."""
    if subject_of(fact) is None:
        return False
    return other is not fact and other.get("kind") == fact.get("kind") and subject_of(other) == subject_of(fact) \
        and (other.get("unit") or "") == (fact.get("unit") or "") and isinstance(other.get("value"), (int, float)) \
        and other.get("op") in _COMPARISONS


def _separator(text: str) -> str:
    has_or, has_and = bool(_OR.search(text)), bool(_AND.search(text))
    return "or" if has_or and not has_and else "and" if has_and and not has_or else "unstated"


def joint(line: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> str:
    """How two facts of one line join, read from the words between them: ``or`` / ``and`` / ``unstated``. A hold time
    and a condition join by *and* (``A 또는 B 인 상태로 100ms 유지``: the time qualifies the condition). With facts in
    between, every separator on the way must be the same connective."""
    if (a["kind"] == "duration") != (b["kind"] == "duration"):
        return "and"
    raw = line.get("raw") or line["text"]
    ordered = sorted(line["facts"], key=lambda f: f["line_span"][0])
    i, j = sorted((ordered.index(a), ordered.index(b)))
    seps = {_separator(raw[ordered[k]["line_span"][1]:ordered[k + 1]["line_span"][0]]) for k in range(i, j)}
    return seps.pop() if len(seps) == 1 else "unstated"


def condition_part_join(line: dict[str, Any], fact: dict[str, Any]) -> str:
    """How the fact joins the rest of its condition clause on the same line, read from that clause only: ``and`` /
    ``or`` / ``unstated`` (both or an unclear mix) / ``""`` (no connective — nothing else in the clause). The part after
    the clause end (``… 초과 시 정지 또는 경고``) is the outcome, not a condition (review r5 W-B)."""
    raw = line.get("raw") or line["text"]
    end = _CLAUSE_END.search(raw, fact["line_span"][1])
    part = raw[:end.start() if end else len(raw)]
    part = _TAIL_AND.sub("", _TAIL_OR.sub("", part.rstrip()))
    part = _HEAD_AND.sub("", _HEAD_OR.sub("", part))
    has_or, has_and = bool(_OR.search(part)), bool(_AND.search(part))
    if not has_or and not has_and:
        return ""
    return "or" if has_or and not has_and else "and" if has_and and not has_or else "unstated"


def line_holds(point, fact: dict[str, Any], line: dict[str, Any], override: tuple | None = None) -> bool | None:
    """The line's verdict at ``point`` over every condition on the fact's subject, joined as the line states
    (``4.00V 이하 또는 4.74V 이상``: 5 V holds through the second). ``override`` = (op, value) replaces ``fact``'s
    comparison (a mutant). ``None`` when two conditions share the subject but the words between them do not say how
    they join (or say both)."""
    siblings = [f for f in line["facts"] if same_subject(fact, f)]
    own = holds(point, fact, *(override or ()))
    if not siblings:
        return own
    joins = {joint(line, fact, f) for f in siblings}
    if len(joins) != 1 or "unstated" in joins:
        return None
    verdicts = [own] + [holds(point, f) for f in siblings]
    return any(verdicts) if joins == {"or"} else all(verdicts)


def written_step(fact: dict[str, Any]) -> Decimal:
    """One unit of the precision the value is written with (``4.00`` → 0.01; hex and integers → 1)."""
    text = str(fact.get("value_text") or fact.get("value")).replace(",", "")
    if text.lower().lstrip("-").startswith("0x") or "." not in text:
        return Decimal(1)
    return Decimal(1).scaleb(-len(text.split(".", 1)[1]))


_TAIL_AND = re.compile(r"(?:\bAND|&&|그리고|이고)\s*$")
_TAIL_OR = re.compile(r"(?:\bOR|\|\||또는|이거나)\s*$")
_BULLET = r"^\s*(?:[-·•*]\s*)?"
_HEAD_AND = re.compile(_BULLET + r"(?:AND\b|&&|그리고\b)", re.IGNORECASE)
_HEAD_OR = re.compile(_BULLET + r"(?:OR\b|\|\||또는\b)", re.IGNORECASE)
# ``가 50ms 유지되면 …`` — the line goes on from the previous one's subject (its conditions last that long: *and*). Only
#   when a value or a parenthesis follows: ``이 경우 u16s_B …`` is a new sentence (review r5 W-C)
_HEAD_PARTICLE = re.compile(r"^\s*(?:이|가|은|는|을|를|의|에서|으로|로)\s+(?=[-+(\d])")
_LONE = re.compile(r"^\s*(AND|OR|&&|\|\||그리고|또는)\s*$", re.IGNORECASE)


def _connective(word: str) -> str:
    return "and" if word.upper() in {"AND", "&&", "그리고"} else "or"


def extract(text: str) -> list[dict[str, Any]]:
    """Every requirement block with the facts of its lines (``lines``: one entry per line with facts). A line joined
    to a neighbour says how (``continues`` — its end, a connective alone on the next line; ``joins_previous`` — its
    head, a particle continuing the previous line's subject, a lone connective before it) and quotes that neighbour
    (``next_text`` / ``previous_text``), so a stepped fact never hides the conditions it depends on (review r4 W-1)."""
    out = []
    for block in split_requirements(text):
        lines = []
        pos = block["start"]
        section = ""
        # the last non-empty line, its line-end connective, a connective alone on a line, and the run of lines joined
        #   to each other up to here (``A AND`` / ``B AND`` / ``C`` / ``가 50ms 지속되면``: the hold time quotes all
        #   three — review r5 W-A)
        previous_text, prev_tail, pending = "", "", ""
        chain: list[str] = []
        open_line = None                   # the last fact line, until the next non-empty line
        for raw_line in block["text"].split("\n"):
            head = re.fullmatch(r"\s*<\s*([^<>]{1,40}?)\s*>\s*", raw_line)
            if head:
                section = head.group(1)   # ``<Pre Condition>`` / ``<완료조건>`` / ``<Output>``: the role of what follows
            stripped = raw_line.strip()
            lone = _LONE.match(raw_line)
            if lone:
                pending = _connective(lone.group(1))
                if open_line is not None and not open_line["continues"]:
                    open_line["continues"] = pending
                prev_tail = prev_tail or pending
                pos += len(raw_line) + 1
                continue
            if not stripped:
                pos += len(raw_line) + 1
                continue
            facts = _line_facts(raw_line, pos)
            tail = raw_line.rstrip()
            tail_join = "and" if _TAIL_AND.search(tail) else "or" if _TAIL_OR.search(tail) else ""
            joins = "and" if _HEAD_AND.match(raw_line) or _HEAD_PARTICLE.match(raw_line) else \
                "or" if _HEAD_OR.match(raw_line) else pending or prev_tail
            if head:
                joins = ""                 # a section heading ends every run
            chain = chain + [previous_text] if joins and previous_text else []
            if open_line is not None:
                if joins and not open_line["continues"]:
                    open_line["continues"] = joins
                if open_line["continues"]:
                    open_line["next_text"] = stripped
                open_line = None
            if facts:
                open_line = {"section": section,
                             # a line that ends in a connective joins the next one (review r3 W6)
                             "continues": tail_join,
                             "joins_previous": joins, "previous_text": " / ".join(chain) if joins else "",
                             "next_text": "",
                             "text": stripped, "raw": raw_line, "span": [pos, pos + len(raw_line)],
                             "sha256": hashlib.sha256(stripped.encode()).hexdigest(),
                             "combination": _combination(raw_line, facts), "facts": facts}
                lines.append(open_line)
            pending = ""
            previous_text, prev_tail = stripped, ("" if head else tail_join)
            pos += len(raw_line) + 1
        out.append({"req_id": block["req_id"], "span": [block["start"], block["end"]], "lines": lines,
                    "facts": sum(len(x["facts"]) for x in lines),
                    "parsed_facts": sum(f["status"] == "parsed" for x in lines for f in x["facts"])})
    return out


def model(text: str) -> dict[str, Any]:
    requirements = extract(text)
    return {"schema_version": SCHEMA_VERSION, "requirements": requirements,
            "summary": {"requirements": len(requirements),
                        "with_facts": sum(bool(r["facts"]) for r in requirements),
                        "facts": sum(r["facts"] for r in requirements),
                        "parsed_facts": sum(r["parsed_facts"] for r in requirements)}}
