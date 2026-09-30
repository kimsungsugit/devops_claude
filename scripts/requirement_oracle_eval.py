"""Requirement oracle evaluation (R5, G4) against a reference STS — independent of the extractor.

Two measures, both scored on what a *reference* (or generated) STS workbook says, never on the extractor's own output:

* **recall of reference thresholds** (G4 a): every threshold the reference STS uses in a test action or judgement
  (``15도 미만``, ``0.8m/s 이상``, ``5도( 0x05 ) 이하``) for an SRS ID is a gold item. It is recalled when the
  extractor found a fact with that value (unit-compatible) in the same requirement. The operator agreement is reported
  separately (the STS may state the other side of a threshold: ``15도 이상`` tests ``15도 미만``'s complement).
  Tolerance checks (``7 ± 5%``) are output judgements, not requirement thresholds — counted, not scored.
  Precision has no independent gold here: the facts are exported for a reviewer (``--review-csv``) and precision is
  reported ``None`` until labelled — a model grading its own extraction is not a measurement.

* **requirement-mutant discrimination** (G4 b): each parsed threshold / duration fact yields mutants — the boundary
  inclusion flipped (``>=`` ↔ ``>``) and the value moved one written step (``8.5`` → ``8.4``/``8.6``; ``4.00`` → ±0.01).
  A suite discriminates a mutant when one of its stimulus *points* for that requirement falls where the **line's**
  verdict (every condition on that subject, joined as the line joins them) **holds for the original and not for the
  mutant** — the step there expects the behaviour, and the mutant would not produce it. A point where the original
  verdict is false does not count (review r4 C-1): outside its condition a sentence claims nothing (another sentence of
  the requirement may act there), so a test at that point has no expectation the mutant could contradict. Separations
  on either side are reported as ``killed_either_side`` — an upper bound that holds only if the suite also asserts
  non-action.
  A point is a number in a test action: unnamed with a unit (``전원을 7V로 설정한다``) for any subject of that unit, or
  named (``u16g_ApiIn_Vsup = 1605``) for that subject only; a requirement quote after ``— 근거:`` is not a point. A
  comparator region in a test action (``0.8m/s 이상 빠르기``) counts only in the ``optimistic`` rate, as if the tester
  had picked the boundary value itself. Response constraints (``100ms 이내``) are measured, not stimulated — no mutant.

  ⚠ **Not independent for a generated STS built by `generators/sts_requirement_tc.py`**: it writes its points from
  the same extractor and the same written-precision step, so every fact it uses is discriminated by construction. The
  number measures whether it wrote every fact it could, and the reference's number measures what the reference tests —
  an independent mutant source (human-labelled facts, `--review-csv`) is needed before either is called superior.

* **cross-source discrimination** (R18, gap ③): mutants made from the **reference STS's own thresholds** — boundaries
  human testers wrote, independent of the extractor — scored on both suites with the same point rule. The verdict is
  the single comparison the tester wrote (``15도 미만`` → ``x < 15``), and a point is a stimulus of that requirement in
  a compatible unit **whose step states its verdict** and states the original's there (R32 review C2: a generated
  boundary step's ``조건 […] 성립/불성립 →``; a step that says 불성립 where the original holds contradicts it rather
  than killing the mutant — ``separated_against_verdict``; a stimulus with no written verdict —
  ``separated_verdict_unknown`` — asserts nothing). The threshold names no subject, so a point on another quantity of
  the same unit could be credited — kills are split by whether the requirement has one subject in that unit
  (``killed_single_subject``) or several (``killed_multi_subject``, an upper bound). This source favours what the reference chose to test, the
  extractor's favours what the SRS states — the generated suite is scored here on mutants it did not produce (the
  reference's own row is self-sourced: its regions are the thresholds, so only its points are reported). Thresholds
  the SRS block does not state are kept — a suite built from the SRS alone cannot know them (they may come from a
  system specification, a scenario precondition, or an SRS revision the reference was not written against).
  Left out and counted (``excluded``): thresholds only in the expected-result column, ones every row writes in both
  its action and its expected cell (``judgement_copied_to_action``), ones the SRS states only as a response constraint,
  unitless ones (``no_unit``). ``killable`` marks mutants a point can kill at all (a widening mutant never can); kills
  are split into ``killed_single_subject`` / ``killed_multi_subject`` / ``killed_unnamed_subject`` (the last is 0 by
  construction since R32: an unnamed stimulus comes from a step that writes no verdict), and a suite with no point in a
  compatible unit **with a written verdict** is not measured (``measurable`` false — a human-written reference is never
  measured here: its steps write no verdict in that form; the R5 ``discrimination`` needs a usable point).

* **provenance** (R44): each cross mutant, and each recall item the SRS block does not state, says where its number is
  written — ``srs``, ``cited_system`` (a condition fact of a cited SyRS/SyDS block: what the generator reads),
  ``cited_response_constraint``, ``cited_text_only``, ``project_document``, ``not_in_given_documents`` (`PROVENANCE_NOTE`)
  — and the cross scoring reports ``by_provenance``. Only with ``--system-docx`` and/or ``--docs-dir``; an input asked
  for and not read fails the run (exit 2) rather than moving its thresholds to another class.

Usage:
    .venv/Scripts/python.exe scripts/requirement_oracle_eval.py --srs SRS.txt --sts STS.xlsm [--sts-generated GEN.xlsm]
        --out r5.json [--review-csv facts.csv] [--system-docx SyRS=SyRS.docx SyDS=SyDS.docx] [--docs-dir DOCS]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generators.requirement_oracle import (  # noqa: E402
    exact_value,
    is_outcome_section,
    line_holds,
    subject_of,
    written_step,
)

# longest first (``5step`` is not s); ``8v 이하``/``Km/h`` as the documents write them (R18 review W5)
_UNIT = r"(?:[Kk]m/h|KM/H|KPH|m/s|step|sec|ms|deg|℃|°C|mV|mv|mA|uA|µA|Hz|V|v|s|초|분|도|%|A)"
_NUM = r"\d+(?:\.\d+)?"
# a written threshold: its own number — not the tail of ``0x1FF0``, with its sign (``-4도``) and without its thousands
# separators (``1,000ms``) — R18 review W5
# (not ``\w``: Hangul is a word character, and ``열림각15도 이상`` / ``전압을9V 이상`` are thresholds — R18 review R2 W-B;
#  after a comma only a thousands group is refused — ``1,000`` is one number, ``Task(5,10,50ms)`` ends in ``50ms`` — R3 I-1)
_CMP_NUM = r"(?<![0-9A-Za-z_.])(?!(?<=\d,)\d{3}(?!\d))-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_OPS = {"이상": ">=", "이하": "<=", "미만": "<", "초과": ">"}
_COMPARATOR = re.compile(rf"(?P<num>{_CMP_NUM})\s*(?P<unit>{_UNIT})?\s*(?:\(\s*0x[0-9A-Fa-f]+\s*\))?\s*"
                         rf"(?P<op>이상|이하|미만|초과)")
_TOLERANCE = re.compile(rf"(?P<num>{_CMP_NUM})\s*(?P<unit>{_UNIT})?\s*±\s*(?P<tol>{_NUM})\s*(?P<tunit>{_UNIT})?")
_POINT = re.compile(rf"(?P<num>{_CMP_NUM})\s*(?P<unit>{_UNIT})\s*(?:\(\s*0x[0-9A-Fa-f]+\s*\))?\s*(?:로|으로|에서|를|을|만큼)?\s*"
                    rf"(?:설정|인가|유지|입력|회전|이동|열|닫|대기|경과)")
# ``u16g_ApiIn_Vsup = 1605 설정`` — a named stimulus; its unit may be absent (a raw ADC count)
_NAMED_POINT = re.compile(rf"(?P<sig>[A-Za-z_][A-Za-z0-9_]*|[가-힣A-Za-z][가-힣A-Za-z0-9_ ]{{0,30}}?)\s*=\s*"
                          rf"(?P<num>-?(?:0[xX][0-9A-Fa-f]+|{_NUM}))\s*(?P<unit>{_UNIT})?(?=\s*(?:설정|유지|$))")
_BASIS_MARK = " — 근거:"   # a quoted requirement after it is not a stimulus (``generators/sts_requirement_tc.BASIS_MARK``)
# ``입력 설정 (요구 경계): <subject> = <value><unit> …`` — the generated step names its subject verbatim (``B+``,
# ``Load(Average)``, ``LIN 통신 지속 시간``): read it by position, not by a name pattern (review r2 W2)
_BOUNDARY_STEP = re.compile(rf"^입력 설정 \(요구 경계\):\s*(?P<sig>.+?)\s+=\s+(?P<num>-?(?:0[xX][0-9A-Fa-f]+|{_NUM}))"
                            rf"\s*(?P<unit>{_UNIT})?")
_DURATION_SUFFIX = " 지속 시간"
# (R29) a step the generator traced to a system block names it after the basis mark:
#   ``… — 근거: 500ms 초과 [SyDS SyII_06 · Range — SwTR_0601 Related ID]`` (``generators/sts_requirement_tc``)
_TRACED = re.compile(r"\[(?P<doc>Sy[A-Za-z]+) (?P<id>Sy[A-Za-z]+_[0-9_]+) · [^\]]*? — \S+ Related ID\]\s*$")
# (R32 review C2) the verdict a generated boundary step expects at its point, from its expected result (column L):
#   ``조건 [저전압 8.5V 이하] 성립 → …`` / ``조건 [...] 불성립 → …`` (``generators/sts_requirement_tc.boundary_steps``)
_VERDICT = re.compile(r"^조건 \[.*?\] (성립|불성립) →", re.S)


def _num(text: str) -> float:
    return float(int(text, 16)) if text.lower().lstrip("-").startswith("0x") else float(text)
_SHEETS = ("3.SW Integration Test Spec", "3.SW Test Spec", "2.SW Test Spec")
_SRS_ID = re.compile(r"Sw[A-Za-z]+_[A-Za-z0-9_]+")


def _unit(u: str | None) -> str:
    u = (u or "").strip()
    return {"sec": "s", "초": "s", "deg": "도", "°C": "℃", "KPH": "km/h", "Km/h": "km/h", "KM/H": "km/h", "v": "V",
            "mv": "mV", "µA": "uA"}.get(u, u)


_TIME = {"ms": 0.001, "s": 1.0, "분": 60.0}


def _seconds(value: float, unit: str) -> float | None:
    return value * _TIME[unit] if unit in _TIME else None


def _same_quantity(a: float, ua: str, b: float, ub: str) -> bool:
    """Equal values in compatible units: same unit, either side unitless, or two time units."""
    ua, ub = _unit(ua), _unit(ub)
    if ua == ub or not ua or not ub:
        return abs(a - b) < 1e-9
    sa, sb = _seconds(a, ua), _seconds(b, ub)
    return sa is not None and sb is not None and abs(sa - sb) < 1e-9


def read_sts(path: str) -> dict[str, dict[str, list]]:
    """SRS ID → {"thresholds", "tolerances", "points", "regions"} from the test action (K) and expected result (L)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        name = next((s for s in _SHEETS if s in wb.sheetnames), None)
        if name is None:
            raise ValueError(f"no STS spec sheet in {Path(path).name}: {wb.sheetnames}")
        out: dict[str, dict[str, list]] = {}
        srs = None
        for row_no, row in enumerate(wb[name].iter_rows(min_row=4, values_only=True), start=4):
            cells = list(row) + [None] * 13
            ids = _SRS_ID.findall(str(cells[12] or ""))
            if ids:
                srs = ids[0]
            if srs is None:
                continue
            slot = out.setdefault(srs, {"thresholds": [], "tolerances": [], "points": [], "regions": []})
            for col, role in ((10, "action"), (11, "expected")):
                text = str(cells[col] or "").split(_BASIS_MARK)[0]
                taken = []
                for m in _TOLERANCE.finditer(text):
                    taken.append((m.start(), m.end()))
                    slot["tolerances"].append({"value": float(m.group("num").replace(",", "")), "unit": _unit(m.group("unit")),
                                               "raw": m.group(0), "role": role})
                for m in _COMPARATOR.finditer(text):
                    if any(s <= m.start() < e for s, e in taken):
                        continue
                    item = {"value": float(m.group("num").replace(",", "")), "unit": _unit(m.group("unit")),
                            "op": _OPS[m.group("op")], "raw": m.group(0), "role": role, "row": row_no,
                            "text": m.group("num").replace(",", "")}   # as written: sign and decimal places
                    slot["thresholds"].append(item)
                    if role == "action":
                        slot["regions"].append(item)
                if role == "action" and (b := _BOUNDARY_STEP.match(text)):
                    traced = _TRACED.search(str(cells[col] or ""))
                    verdict = _VERDICT.match(str(cells[11] or ""))
                    slot["points"].append({"value": _num(b.group("num")), "unit": _unit(b.group("unit")),
                                           "signal": b.group("sig").strip(), "raw": b.group(0),
                                           "traced": f"{traced.group('doc')} {traced.group('id')}" if traced else None,
                                           "holds": None if verdict is None else verdict.group(1) == "성립"})
                elif role == "action":
                    named = []
                    for m in _NAMED_POINT.finditer(text):
                        named.append((m.start("num"), m.end()))
                        slot["points"].append({"value": _num(m.group("num")), "unit": _unit(m.group("unit")),
                                               "signal": m.group("sig").strip(), "raw": m.group(0)})
                    for m in _POINT.finditer(text):
                        if any(s <= m.start() < e for s, e in named):
                            continue
                        slot["points"].append({"value": float(m.group("num").replace(",", "")),
                                               "unit": _unit(m.group("unit")), "signal": None, "raw": m.group(0)})
        return out
    finally:
        wb.close()


def _fact_values(fact: dict) -> list[float]:
    v = fact.get("value")
    if isinstance(v, list):
        return [float(x) for x in v if isinstance(x, (int, float))]
    return [float(v)] if isinstance(v, (int, float)) else []


def _stated_in(text: str, value: float, unit: str) -> bool:
    """The quantity is written in the requirement's own text: the number followed by a compatible unit (``3도``,
    ``300ms`` for ``0.3 s``). A bare number is not enough — list numbers (``15. …``), IDs (``SyEI_03``) and other
    quantities (``50스텝`` for ``50도``) would make gold items the text never states."""
    for m in re.finditer(rf"(?P<num>{_CMP_NUM})\s*(?P<unit>{_UNIT})", text):
        if _same_quantity(float(m.group("num").replace(",", "")), m.group("unit"), value, unit):
            return True
    return False


_RELATED = re.compile(r"(?m)^Related ID\t(.*)$")
# (R44) where a reference threshold's number is written — the G4(b) denominator read by what the generator can know
PROVENANCES = ("srs", "cited_system", "cited_response_constraint", "cited_text_only", "project_document",
               "not_in_given_documents")
_CITED_CLASSES = ("cited_system", "cited_response_constraint", "cited_text_only")
_HELD_BACK = " (생성기 제외: "
PROVENANCE_NOTE = (
    "first match wins. srs: the number + a compatible unit in the requirement's own block (an upper bound: another "
    "sentence of the block may write it). cited_system: a condition fact the generator's own reading of a cited "
    "SyRS/SyDS block yields — what the generator can know. cited_response_constraint: the extractor reads it as a "
    "deadline (``300ms 이내에 … 해야 한다``), which the reference used as a stimulus — not a threshold to step. "
    "cited_text_only: a cited block's text has the number but no condition fact does (an outcome — a result field, an "
    "``Output :`` line, an obligation —, a negated or unparsed phrase, another quantity, a deadline the extractor does "
    "not read — ``500ms 내에 … 진입해야 한다`` — or an extractor gap: read the source). A cited_system entry the "
    "generator reads but does not step says why (``생성기 제외: …``). "
    "project_document: another SRS block or a given requirement/design document "
    "writes the number (an upper bound: no link to the requirement is checked). not_in_given_documents: none does — "
    "the tester's own value, a unit typo, a raw count (a lower bound: a document not given may write it)")


def _related_rows(block_text: str) -> str:
    """The SRS block's ``Related ID`` rows as the generator's ``related_id`` field."""
    return ", ".join(m.group(1) for m in _RELATED.finditer(block_text or ""))


def _cited_ids(block_text: str) -> list[str]:
    """The system IDs the SRS block's ``Related ID`` rows name — the generator's own `cited_system_ids` (review I4)."""
    from generators.sts_requirement_tc import cited_system_ids
    return cited_system_ids({"related_id": _related_rows(block_text)})


def provenance(req: str, value: float, unit: str, blocks: dict[str, str], system: dict[str, dict] | None,
               documents: dict[str, str] | None) -> tuple[str | None, list[str]]:
    """(R44) Where the reference STS's threshold is written, first match wins:

    * ``srs`` — the requirement's own block;
    * ``cited_system`` — a fact **the generator's own reading** of a SyRS/SyDS block the Related ID names yields
      (`traced_system_facts`: one hop) that the generator counts as a condition (review R1 C1: matching the block text
      alone put two deadlines and a value of another block here; r2 W1: an ``Output :`` line, an obligation, a negated
      or unparsed phrase is no condition — HDPDM01 SyTR_0604 ``Output: 전류 7mA 이하가 되는 시간 측정``). One the
      generator reads but does not step carries its reason (``(생성기 제외: parenthesis_labels_may_share_a_quantity)``);
    * ``cited_response_constraint`` — such a fact is a response constraint (``300ms 이내에 … 해야 한다``): a
      deadline, not a stimulus threshold (R18 leaves the SRS's own out the same way);
    * ``cited_text_only`` — a cited block's text has the number, as no such fact (HDPDM01 SyTSR_0109 ``500ms 내에 …
      진입해야 한다``: a deadline the extractor reads no fact from);
    * ``project_document`` — another block of the SRS or a given requirement/design document writes it (no link to
      this requirement is checked);
    * ``not_in_given_documents`` — none does: the tester's stimulus value, a unit typo, a raw count.

    The cited classes come before ``project_document``: a block the requirement names is the closer evidence (a SyRS
    export among the documents would otherwise take a cited deadline). ``where`` names every matching block·field or
    document. ``None`` when neither system blocks nor documents were given (not examined). See `PROVENANCE_NOTE`."""
    from generators.sts_requirement_tc import (
        SYSTEM_OUTCOME_FIELDS,
        _conflict_role,
        _skip_reason,
        traced_system_facts,
    )
    block = blocks.get(req) or ""
    if _stated_in(block, value, unit):
        return "srs", []
    if system is None and documents is None:
        return None, []
    # (R44 review r2 W1) a condition as the generator decides it — the split its own `_conflict_role` makes (an
    #   ``Output :`` line inside another field, an obligation ``…이하여야 한다``), not negated, outside the outcome
    #   fields — and a unit written on both sides (a unit-less fact names no quantity: r2 I5). A value without a
    #   subject (status ``partial``) is still a condition the generator reads: it says ``no_subject_for_value``
    facts = [(line, fact, src) for line, fact, src in traced_system_facts(
                 {"id": req, "related_id": _related_rows(block)}, system or {})
             if src["field"] not in SYSTEM_OUTCOME_FIELDS and not fact.get("negated")
             and _conflict_role(line, fact, False) != "outcome" and fact.get("unit")
             and any(_same_quantity(value, unit, x, fact["unit"]) for x in _fact_values(fact))]
    for cls, deadline in (("cited_system", False), ("cited_response_constraint", True)):
        # (r2 I1) a condition the generator reads but does not step says why — the gap diagnoses itself
        #   (only `_skip_reason`: ``duplicate_fact`` / ``already_stepped`` are decided later, in `boundary_steps` — no
        #   mark does not mean the block steps it there)
        where = sorted({f"{src['doc']} {src['id']} · {src['field']}"
                        + (f"{_HELD_BACK}{why})" if (why := _skip_reason(line, fact)) and not deadline else "")
                        for line, fact, src in facts if (fact.get("role") == "response_constraint") == deadline})
        if where:
            return cls, where
    text_only = sorted(f"{(system or {})[sid].get('doc', '')} {sid} · {field}"
                       for sid in _cited_ids(block) if sid in (system or {})
                       for field, text in ((system or {})[sid].get("fields") or {}).items()
                       if _stated_in(str(text), value, unit))
    if text_only:
        return "cited_text_only", text_only
    hits = [f"SRS {rid}" for rid, text in sorted(blocks.items()) if rid != req and _stated_in(text, value, unit)]
    hits += [name for name, text in sorted((documents or {}).items()) if _stated_in(text, value, unit)]
    if hits:
        return "project_document", hits
    return "not_in_given_documents", []


# a test specification or report by its acronym as a whole token, any case (``HDPDM01_STS_v1`` · ``hdpdm01_sts`` ·
#   ``STSv1`` · ``(KJPDS02_SwTS)`` · ``SUTR``) — not ``sts`` inside a word (``Lists``), and not the requirement ID
#   prefixes ``SwTR`` · ``SwTSR`` · ``SyTR`` · ``SyTSR`` (``SyTS`` + ``R`` is not ``SyTS``); ``TC`` alone, not a part
#   number (``TC275_datasheet``); ``test spec/report/case``; ``시험`` (r2 I4). A false hit stops the run with the
#   file's name — the safe side
_TEST_SPEC_NAME = re.compile(
    r"(?i)(?<![a-z])(?:STS|SwTS|SITS|SwITS|SUTS|SwUTS|SyTS|SyITS|SUTR|SwUTR|SITR|SwITR)(?![a-uw-z])"
    r"|(?<![a-z])TC(?![a-z0-9])|(?<![a-z])test[ _-]?(?:spec|report|case)|시험")


class InputError(ValueError):
    """(R44 review W1) an input the provenance split was asked to read and could not — the CLI exits 2."""


def load_documents(folder: str) -> dict[str, str]:
    """(R44 review W1 · I3) The ``--docs-dir`` texts — the ``*.txt`` directly in the folder, not in its subfolders — or
    InputError: a missing or empty folder, an empty file or one that is not UTF-8 (r2 I3), or a test specification (its
    values are the testers' own — they would make the tester's choices read as project documents). A silent empty set
    would turn every unmatched threshold into ``not_in_given_documents``."""
    root = Path(folder)
    if not root.is_dir():
        raise InputError(f"--docs-dir is not a folder: {folder}")
    files = sorted(root.glob("*.txt"))
    if not files:
        raise InputError(f"--docs-dir holds no *.txt: {folder}")
    docs = {}
    for f in files:
        if _TEST_SPEC_NAME.search(f.stem):
            raise InputError(f"--docs-dir must not hold test specifications: {f.name}")
        try:
            docs[f.name] = f.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"--docs-dir file is not UTF-8: {f.name} ({exc.reason})") from None
        if not docs[f.name].strip():
            raise InputError(f"--docs-dir file is empty: {f.name}")
    return docs


def recall(requirements: list[dict], sts: dict, blocks: dict[str, str]) -> dict[str, Any]:
    """Only gold items whose number the SRS block itself writes are scored: a threshold the reference STS took from
    elsewhere (system spec, design) is not one the requirement text states — counted as ``not_stated_in_srs``."""
    facts_by_req = {r["req_id"]: [f for line in r["lines"] for f in line["facts"]] for r in requirements}
    items, found, op_agree, missing, not_stated = 0, 0, 0, [], []
    for req, slot in sorted(sts.items()):
        gold = {(t["value"], t["unit"]): t for t in slot["thresholds"]}  # distinct per requirement
        for (value, unit), t in sorted(gold.items()):
            if not _stated_in(blocks.get(req, ""), value, unit):
                not_stated.append({"req_id": req, "raw": t["raw"], "value": value, "unit": unit,
                                   "srs_block_found": req in blocks})
                continue
            items += 1
            hits = [f for f in facts_by_req.get(req, []) if any(_same_quantity(value, unit, x, f.get("unit") or "")
                                                                 for x in _fact_values(f))]
            if hits:
                found += 1
                complement = {">=": "<", "<": ">=", "<=": ">", ">": "<="}
                if any(f.get("op") in (t["op"], complement[t["op"]]) for f in hits):
                    op_agree += 1
            else:
                missing.append({"req_id": req, "raw": t["raw"], "in_srs_model": req in facts_by_req})
    return {"gold_items": items, "recalled": found, "recall": round(found / items, 4) if items else None,
            "operator_consistent": op_agree, "missing": missing, "not_stated_in_srs": not_stated}


def _tokens(x: str) -> list[str]:
    return re.sub(r"[^0-9A-Za-z가-힣_]+", " ", x).split()


def _same_signal(a: str, b: str) -> bool:
    """The same subject written with or without leading words / punctuation (``High -> Low Power mode 천이 시간`` read back
    from a test action as ``Low Power mode 천이 시간``): one normalized name ends the other. The shorter must still name
    something — an identifier or at least two words (``전압`` alone ends every voltage)."""
    na, nb = _tokens(a), _tokens(b)
    if not na or not nb:
        return False
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) < 2 and "_" not in short[0] and not re.search(r"[a-z][A-Z]", short[0]) and short != long_:
        return False
    return long_[-len(short):] == short


def requirement_mutants(requirements: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Mutants of every parsed order comparison, and the facts left out with why."""
    flip = {">=": ">", ">": ">=", "<=": "<", "<": "<="}
    out, excluded = [], Counter()
    for r in requirements:
        for line in r["lines"]:
            for f in line["facts"]:
                if f["status"] != "parsed" or f["kind"] not in {"threshold", "duration"} or f.get("op") not in flip:
                    continue
                if not isinstance(f.get("value"), (int, float)) or isinstance(f.get("value"), bool):
                    continue
                if f.get("role") == "response_constraint":
                    excluded["response_constraint"] += 1
                    continue
                if f.get("negated"):
                    excluded["negated_condition"] += 1   # ``8.5V 이상을 만족하지 못하면``: the sense is reversed
                    continue
                if is_outcome_section(line.get("section") or ""):
                    excluded["outcome_section"] += 1   # ``<완료조건>`` / ``<Output>``: produced, not stimulated
                    continue
                value, step = exact_value(f), written_step(f)
                # the subject a stimulus sets: a parameter threshold's monitored quantity (review r2 C-B)
                base = {"req_id": r["req_id"], "signal": subject_of(f), "kind": f["kind"], "unit": _unit(f.get("unit")),
                        "op": f["op"], "value": float(value), "value_text": f.get("value_text"),
                        "raw": f.get("raw", ""), "_fact": f, "_line": line}
                out.append({**base, "mutant": "boundary_inclusion", "m_op": flip[f["op"]], "m_value": value})
                for d in (-step, step):
                    out.append({**base, "mutant": "value_shift", "m_op": f["op"], "m_value": value + d})
    return out, dict(excluded)


def discrimination(mutants: list[dict], sts: dict) -> dict[str, Any]:
    """``killed``: a stimulus point separates the mutant (strict). ``killed_optimistic`` also credits a comparator region
    in a test action at the fact's own value and unit (``15도 이상`` for ``15도 미만``) as if the tester had chosen the
    boundary value — an upper bound for a suite that states regions, not points."""
    killed, either, optimistic, by_kind, total = 0, 0, 0, Counter(), Counter()
    unjudgeable = 0
    rows = []

    def compatible(a, b):
        # same unit, or two time units (``300ms`` against ``0.3 s`` — the verdict scales it, review r2 W3)
        a, b = _unit(a), _unit(b)
        return a == b or (_seconds(1.0, a) is not None and _seconds(1.0, b) is not None)

    def usable(p, m):
        if m["kind"] == "duration":
            # a hold time is stimulated by how long the condition lasts: a ``… 지속 시간`` point, or an unnamed time
            named_ok = not p.get("signal") or p["signal"].endswith(_DURATION_SUFFIX.strip())
            return named_ok and bool(p["unit"]) and compatible(p["unit"], m["unit"] or "s")
        if p.get("signal"):
            # a named point stimulates its own subject only — a fact with no subject is not "any subject" (r3 W4)
            same_unit = not m["unit"] or not p["unit"] or compatible(p["unit"], m["unit"])
            return same_unit and bool(m.get("signal")) and _same_signal(p["signal"], m["signal"])
        # an unnamed point has a unit; a unit-less fact (a raw count) needs a named point
        return bool(m["unit"]) and bool(p["unit"]) and compatible(p["unit"], m["unit"])

    def line_verdict(p, m, override=None):
        # the point in the fact's unit (``300ms`` against ``0.3 s``), exact decimals
        return line_holds(Decimal(str(p["value"])) * _scale(p["unit"], m["unit"]), m["_fact"], m["_line"], override)

    for m in mutants:
        total[m["mutant"]] += 1
        slot = sts.get(m["req_id"]) or {}
        candidates = [p for p in slot.get("points", []) if usable(p, m)]
        points = [p["value"] for p in candidates]
        hit = side = None
        judged = True
        for p in candidates:
            a, b = line_verdict(p, m), line_verdict(p, m, (m["m_op"], m["m_value"]))
            if a is None or b is None:
                judged = False
                break
            if a and not b:
                hit = p["value"]      # the step expects the behaviour here; the mutant does not produce it
                break
            if a != b and side is None:
                side = p["value"]     # separated only where the original claims nothing
        if not judged:
            unjudgeable += 1
        if hit is not None or side is not None:
            either += 1
        region = next((r["raw"] for r in slot.get("regions", []) if _same_quantity(r["value"], r["unit"], m["value"],
                                                                                   m["unit"])), None)
        if hit is not None:
            killed += 1
            by_kind[m["mutant"]] += 1
        if hit is not None or region is not None:
            optimistic += 1
        rows.append({**{k: v for k, v in m.items() if not k.startswith("_")}, "m_value": float(m["m_value"]),
                     "points": points, "killed_by_point": hit, "separated_where_original_false": side,
                     "boundary_region": region})
    n = len(mutants)
    # (R18 review R3 W-3) a suite with no usable point for any mutant is not measured by points: its 0 is no score
    measurable = any(r["points"] for r in rows)
    return {"mutants": n, "measurable": measurable, "killed": killed,
            "rate": round(killed / n, 4) if n and measurable else None,
            "killed_either_side": either, "rate_either_side": round(either / n, 4) if n and measurable else None,
            "killed_optimistic": optimistic, "rate_optimistic": round(optimistic / n, 4) if n else None,
            "unjudgeable_combination": unjudgeable,
            "by_kind": {k: {"mutants": total[k], "killed": by_kind[k]} for k in total}, "rows": rows}


_COMPARE = {">=": lambda x, v: x >= v, ">": lambda x, v: x > v, "<=": lambda x, v: x <= v, "<": lambda x, v: x < v}
_FLIP = {">=": ">", ">": ">=", "<=": "<", "<": "<="}


def _units_compatible(a: str | None, b: str | None) -> bool:
    """Both units written and the same quantity: the same unit, or two time units (``300ms`` / ``0.3 s``). A threshold
    or a point without a unit cannot be placed without a subject (points and regions judged alike — R18 review W4)."""
    a, b = _unit(a), _unit(b)
    if not a or not b:
        return False
    return a == b or (_seconds(1.0, a) is not None and _seconds(1.0, b) is not None)


def _killable(op: str, value: Decimal, m_op: str, m_value: Decimal) -> bool:
    """Is there a point where the written comparison holds and the mutant's does not? A mutant that only widens the
    condition (``<`` → ``<=``, the value moved outward) can never be killed by a point that asserts the behaviour."""
    if op in {">=", ">"}:
        return m_value > value or (m_value == value and op == ">=" and m_op == ">")
    return m_value < value or (m_value == value and op == "<=" and m_op == "<")


def reference_mutants(reference: dict, blocks: dict[str, str] | None = None,
                      facts_by_req: dict[str, list] | None = None, system: dict[str, dict] | None = None,
                      documents: dict[str, str] | None = None) -> tuple[list[dict], dict[str, int]]:
    """(R18) Mutants of every distinct order threshold the reference STS writes **as a stimulus** for a requirement:
    the boundary inclusion flipped and the value moved one **written** step (``0.8`` → ±0.1, ``15`` → ±1, the finest
    when a value is written twice). Left out, counted (R18 review W2, I4, R2 W-A): a threshold only in the
    expected-result column (an output judgement); one every row writes in **both** its action and its expected cell
    (acceptance criteria copied, ``CPU 부하 70%이하``); one the SRS states only as a response constraint
    (``100ms 이내``); a unitless one. Each mutant carries whether the SRS block states the quantity, whether the block
    exists, and whether the extractor recalled it."""
    out, excluded = [], Counter()
    for req, slot in sorted(reference.items()):
        groups: dict[tuple, dict] = {}
        for t in slot["thresholds"]:
            if t["op"] not in _FLIP:
                excluded["not_an_order_comparison"] += 1
                continue
            text = t.get("text") or str(t["value"])
            key = (Decimal(text), _unit(t["unit"]), t["op"])
            g = groups.setdefault(key, {"text": text, "roles": set(), "raw": t["raw"], "rows": {}})
            g["roles"].add(t["role"])
            g["rows"].setdefault(t.get("row"), set()).add(t["role"])
            if len(text.split(".")[1] if "." in text else "") > len(g["text"].split(".")[1] if "." in g["text"] else ""):
                g["text"] = text   # the finer written precision (``1.30`` over ``1.3`` — R18 review I2)
        for (value, unit, op), g in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
            if "action" not in g["roles"]:
                excluded["expected_result_only"] += 1
                continue
            if all(roles == {"action", "expected"} for r, roles in g["rows"].items() if "action" in roles and r is not None) \
                    and any(r is not None for r in g["rows"]):
                # every row that writes it as an action also writes it as that row's judgement: acceptance criteria
                # copied into both cells (KJPDS02 SwNTR_0301 ``CPU 부하 70%이하``) — R18 review R2 W-A
                excluded["judgement_copied_to_action"] += 1
                continue
            if not unit:
                excluded["no_unit"] += 1   # a point cannot be placed on a unitless threshold without its subject (I-d)
                continue
            block = (blocks or {}).get(req)
            stated = _stated_in(block or "", float(value), unit)
            same = [(f, line) for f, line in (facts_by_req or {}).get(req, [])
                    if any(_same_quantity(float(value), unit, x, f.get("unit") or "") for x in _fact_values(f))]
            # a response constraint (``100ms 이내``) is measured, not stimulated. (Not by section: a section says where
            # a line sits, not what its value does — R2 I-a; since R22 an attribute row such as the verification
            # criteria also ends an ``<Output>`` section, so ``Param( 3도 ) 초과한 열림각`` is no longer read as Output)
            if same and all(f.get("role") == "response_constraint" for f, _line in same):
                excluded["srs_states_it_as_output"] += 1
                continue
            step = Decimal(1).scaleb(-len(g["text"].split(".")[1]) if "." in g["text"] else 0)
            prov, where = provenance(req, float(value), unit, blocks or {}, system, documents)
            base = {"req_id": req, "unit": unit, "op": op, "value": value, "raw": g["raw"], "stated_in_srs": stated,
                    "srs_block_found": block is not None, "recalled_by_extractor": bool(same),
                    "provenance": prov, "provenance_where": where}
            for mutant, m_op, m_value in (("boundary_inclusion", _FLIP[op], value), ("value_shift", op, value - step),
                                          ("value_shift", op, value + step)):
                out.append({**base, "mutant": mutant, "m_op": m_op, "m_value": m_value,
                            "killable": _killable(op, value, m_op, m_value)})
    return out, dict(excluded)


def _subject_groups(points: list[dict]) -> list[str]:
    """Distinct subjects among named points: a name that ends a longer one (``Low Power mode 천이 시간`` /
    ``High -> Low Power mode 천이 시간``) is that one; two long names a short one ends both of stay two
    (``저 전압 … 기준 전압`` / ``과 전압 … 기준 전압``). Longest first, so the result does not depend on the order
    the points come in (R18 review R3 W-1)."""
    names = sorted({p.get("signal") for p in points if p.get("signal")}, key=lambda x: (-len(_tokens(x)), x))
    groups: list[str] = []
    for name in names:
        if not any(_same_signal(name, g) for g in groups):
            groups.append(name)
    return groups


def cross_discrimination(mutants: list[dict], sts: dict, self_sourced: bool = False) -> dict[str, Any]:
    """(R18) ``killed``: a point of the requirement, in a compatible unit, where the written comparison holds and the
    mutant's does not **and the suite's step expects the behaviour there** (its verdict is *성립*). (R32 review C2) the
    verdict was not read before: a point where the step itself says *불성립* separated the mutant and was counted — a
    test that expects no behaviour where the original has it does not kill the mutant, it contradicts the original
    (HDPDM01 18 of 25 kills, KJPDS02_PV 9 of 13 came from such points). A separation against the step's verdict is
    ``separated_against_verdict`` — two documents disagree (SyDS ``500ms 초과`` vs the reference ``500ms 이상``) or the
    step judges the complementary condition (``활성화 구간 50도 미만`` against the reference's ``50도 이상``);
    one at a point whose verdict is not written (a stimulus of another kind of step) is ``separated_verdict_unknown``
    — neither is a kill. ``killed_either_side`` counts a separation on either side where the step's verdict is the
    original's; ``killed_optimistic`` also credits a comparator region at the threshold's own value (``15도 이상``), as if
    the tester had chosen the boundary value itself — **not reported for the suite the thresholds came from**: its
    regions *are* those thresholds, so the number would be fixed by construction (R18 review C1). A suite with no point
    in a compatible unit for any mutant is not measured (``measurable`` false, rates None — R2 W-D). A point names its
    subject only sometimes: kills are split into ``killed_single_subject`` (the requirement's same-unit points name one
    subject), ``killed_multi_subject`` (several — another quantity of that unit could have supplied it, an upper bound)
    and ``killed_unnamed_subject`` (an unnamed point: any quantity of that unit — R2 W-E)."""
    killed = either = optimistic = with_points = killable = single = multi = unnamed = via_trace = 0
    against_verdict = verdict_unknown = 0
    by_stated = Counter()
    by_provenance: dict[str | None, Counter] = {}
    recall = Counter()
    rows = []
    for m in mutants:
        slot = sts.get(m["req_id"]) or {}
        # the requirement's own points first: a kill is credited to a traced system point only when none of them kills
        points = sorted((p for p in slot.get("points", []) if _units_compatible(p["unit"], m["unit"])),
                        key=lambda p: bool(p.get("traced")))
        # (R32 review r2 W1) only a point whose step states a verdict can kill — without one the suite is not measured
        #   here (its 0 would read as a score)
        with_points += any(p.get("holds") is not None for p in points)
        hit = side = against = unknown = None
        for p in points:
            x = Decimal(str(p["value"])) * _scale(p["unit"], m["unit"])
            a, b = _COMPARE[m["op"]](x, m["value"]), _COMPARE[m["m_op"]](x, m["m_value"])
            if a == b:
                continue
            verdict = p.get("holds")
            if verdict is None:
                unknown = unknown or p          # the step states no verdict here: nothing is asserted
                continue
            if verdict != a:
                against = against or p          # the step expects the mutant's verdict: the documents disagree
                continue
            if a and not b and hit is None:
                hit = p
            if side is None:
                side = p
        region = next((r["raw"] for r in slot.get("regions", []) if _units_compatible(r["unit"], m["unit"])
                       and _same_quantity(r["value"], r["unit"], float(m["value"]), m["unit"])), None)
        # (R29 review I1) a kill by the requirement's own point is classified among its own points: points traced to a
        #   system block add subjects of the same unit, which would demote an own kill to "several subjects"
        pool = [p for p in points if not p.get("traced")] if hit is not None and not hit.get("traced") else points
        subjects = _subject_groups(pool)
        killed += hit is not None
        against_verdict += side is None and against is not None
        verdict_unknown += side is None and against is None and unknown is not None
        via_trace += hit is not None and bool(hit.get("traced"))
        either += hit is not None or side is not None
        optimistic += hit is not None or region is not None
        killable += m["killable"]
        if hit is not None:
            if not hit.get("signal"):
                unnamed += 1
            elif len(subjects) == 1 and all(p.get("signal") for p in pool):
                single += 1
            else:
                multi += 1
        by_stated[(m["stated_in_srs"], hit is not None)] += 1
        cls = by_provenance.setdefault(m.get("provenance"), Counter())
        cls["mutants"] += 1
        cls["killable"] += m["killable"]
        cls["killed"] += hit is not None
        # (r2 I2) of the killable ones only: an unkillable mutant's separation says nothing of a kill the suite missed
        cls["killable_against_verdict"] += bool(m["killable"]) and side is None and against is not None
        # (r3 I1) a cited condition the generator reads but steps nowhere (every place says why): the class's headline
        #   splits without opening the rows
        where = m.get("provenance_where") or []
        cls["killable_held_back_by_generator"] += bool(m["killable"]) and m.get("provenance") == "cited_system" \
            and bool(where) and all(_HELD_BACK in w for w in where)
        recall[(m["recalled_by_extractor"], hit is not None)] += 1
        rows.append({**m, "value": float(m["value"]), "m_value": float(m["m_value"]),
                     "points": [p["value"] for p in points], "killed_by_point": None if hit is None else hit["value"],
                     "killed_by_trace": None if hit is None else hit.get("traced"),
                     "killed_by_signal": None if hit is None else (hit.get("signal") or ""),
                     "separated_against_verdict": None if against is None else against["value"],
                     "separated_verdict_unknown": None if unknown is None else unknown["value"],
                     "subjects_in_unit": subjects, "boundary_region": None if self_sourced else region})
    n = len(mutants)
    measurable = bool(with_points)

    def rate(k, d):
        return round(k / d, 4) if measurable and d else None
    stated = sum(v for (st, _k), v in by_stated.items() if st)
    return {"mutants": n, "measurable": measurable, "killed": killed, "rate": rate(killed, n),
            "killed_either_side": either, "rate_either_side": rate(either, n),
            "killed_optimistic": None if self_sourced else optimistic,
            "rate_optimistic": None if self_sourced or not n else round(optimistic / n, 4),
            "self_sourced": self_sourced,
            "self_sourced_note": "the suite the thresholds came from: its regions are those thresholds, so the "
                                 "optimistic rate would be fixed by construction — not reported" if self_sourced else "",
            # an unkillable mutant never satisfies "holds and the mutant does not": every kill is of a killable one
            "killable_mutants": killable, "rate_of_killable": rate(killed, killable),
            "killed_single_subject": single, "killed_multi_subject": multi, "killed_unnamed_subject": unnamed,
            # (R32 review C2) separations that are no kill — see the docstring
            "separated_against_verdict": against_verdict, "separated_verdict_unknown": verdict_unknown,
            # (R29) kills only a point traced to a system block made (the requirement's own points kill none of them)
            "killed_via_traced_system": via_trace,
            "mutants_with_a_point_in_unit": with_points,
            "stated_in_srs": {"mutants": stated, "killed": by_stated[(True, True)]},
            "not_stated_in_srs": {"mutants": n - stated, "killed": by_stated[(False, True)]},
            # (R44) by where the threshold is written — the classes the generator can read (srs, cited_system) are the
            #   fair target; a deadline used as a stimulus or a number no given document writes is not a miss. Every
            #   class is listed (0 is a count); None unless every mutant is classified — without system blocks or
            #   documents the ones the SRS states would read as a complete split of "srs" only. Kills are None when
            #   the suite is not measured (its 0 would read as a score — R32 review r2 W1)
            "by_provenance": None if not by_provenance or None in by_provenance else {
                prov: {"mutants": c["mutants"], "killable": c["killable"],
                       "killed": c["killed"] if measurable else None, "rate_of_killable": rate(c["killed"], c["killable"]),
                       "killable_against_verdict": c["killable_against_verdict"] if measurable else None,
                       "killable_held_back_by_generator": c["killable_held_back_by_generator"]}
                for prov, c in ((prov, by_provenance.get(prov, Counter())) for prov in PROVENANCES)},
            "recalled_by_extractor": {"killed": recall[(True, True)], "not_killed": recall[(True, False)]},
            "not_recalled": {"killed": recall[(False, True)], "not_killed": recall[(False, False)]},
            "rows": rows}


def _scale(point_unit: str, fact_unit: str) -> Decimal:
    """Factor turning a point in ``point_unit`` into ``fact_unit`` (``300ms`` against ``0.3 s``); 1 otherwise."""
    a, b = _seconds(1.0, _unit(point_unit)), _seconds(1.0, _unit(fact_unit))
    if a is None or b is None or a == b:
        return Decimal(1)
    return Decimal(str(a)) / Decimal(str(b))


def evaluate(srs_text: str, sts_path: str, generated_path: str | None = None,
             system_docs: list[tuple[str, str | None]] | None = None,
             documents: dict[str, str] | None = None) -> dict[str, Any]:
    """``system_docs`` (``[("SyRS", path), ("SyDS", path)]``) and ``documents`` (name → text of the project's other
    requirement and design documents — not test specifications, which hold the testers' own values) let the cross
    scoring say where each reference threshold is written (R44 `provenance`)."""
    from generators.requirement_oracle import model, split_requirements
    system = None
    system_records: list = []
    if system_docs:
        from generators.sts_requirement_tc import load_system_requirements
        system, system_records = load_system_requirements(system_docs)
        failed = [r for r in system_records if r.get("error")]
        if failed or len(system_records) != len(system_docs):
            # (R44 review W1) a document asked for and not read would move its thresholds to another class silently
            raise InputError("system document not read: " + "; ".join(
                f"{r['doc']} {r['file']}: {r['error']}" for r in failed) if failed else "a system document has no path")
        empty = [r for r in system_records if not r.get("blocks")]
        if empty:
            # (r2 I3) read, but no requirement table in it (an SRS given as SyRS, another template): not a system input
            raise InputError("no system requirement table found in: " + "; ".join(
                f"{r['doc']} {r['file']}" for r in empty))
    m = model(srs_text)
    blocks = {b["req_id"]: b["text"] for b in split_requirements(srs_text)}
    reference = read_sts(sts_path)
    mutants, excluded = requirement_mutants(m["requirements"])
    report = {"srs_model": m["summary"], "reference_sts": sts_path,
              "reference_items": {"thresholds": sum(len(s["thresholds"]) for s in reference.values()),
                                  "tolerances": sum(len(s["tolerances"]) for s in reference.values()),
                                  "points": sum(len(s["points"]) for s in reference.values()),
                                  "regions": sum(len(s["regions"]) for s in reference.values())},
              "recall": recall(m["requirements"], reference, blocks),
              "precision": None, "precision_note": "no independent gold — see --review-csv",
              "mutants_excluded": excluded,
              "independence_note": "a generated STS built from the same extractor is discriminated by construction",
              "discrimination": {"reference": discrimination(mutants, reference)}}
    generated = read_sts(generated_path) if generated_path else None
    if generated is not None:
        report["discrimination"]["generated"] = discrimination(mutants, generated)
    # (R18) the other direction: mutants from the reference's own thresholds (independent of the extractor)
    facts_by_req = {r["req_id"]: [(f, line) for line in r["lines"] for f in line["facts"]] for r in m["requirements"]}
    cross, cross_excluded = reference_mutants(reference, blocks, facts_by_req, system, documents)
    for item in report["recall"]["not_stated_in_srs"]:
        # (R44) where the thresholds the SRS block does not state are written
        item["provenance"], item["provenance_where"] = provenance(item["req_id"], item["value"], item["unit"], blocks,
                                                                  system, documents)
    report["cross_source"] = {
        "source": "reference STS thresholds (human-written), stimuli only", "thresholds": len(cross) // 3,
        "boundaries": len({(x["req_id"], x["value"], x["unit"]) for x in cross}), "excluded": cross_excluded,
        "note": "the generated suite is scored on mutants it did not produce (the reference's thresholds); the "
                "reference's own row shows its points only — its regions are these thresholds (self-sourced). A point "
                "counts for any subject of the requirement in a compatible unit (the threshold names none): see "
                "killed_single_subject / killed_multi_subject. A point kills only where its step states a verdict and "
                "states the original's (R32): separated_against_verdict / separated_verdict_unknown are no kills",
        "reference": cross_discrimination(cross, reference, self_sourced=True),
        "provenance_inputs": None if system is None and documents is None else {
            "system_documents": [{k: r[k] for k in r if k in ("doc", "file", "blocks")} for r in system_records],
            # (r2 I3) a cited ID the given system documents do not hold cannot be classified as cited — say how many
            "cited_id_mentions": None if system is None else sum(len(_cited_ids(b)) for b in blocks.values()),
            "cited_ids_distinct": None if system is None else len({s for b in blocks.values() for s in _cited_ids(b)}),
            "cited_ids_not_in_system_documents": None if system is None else sorted(
                {sid for b in blocks.values() for sid in _cited_ids(b) if sid not in system}),
            "documents": sorted(documents or {})},
        "provenance_note": None if system is None and documents is None else PROVENANCE_NOTE}
    if generated is not None:
        report["cross_source"]["generated"] = cross_discrimination(cross, generated)
    if system is None:
        # (r2 I5) no system document given: the cited classes were not examined — not a count of 0
        for suite in ("reference", "generated"):
            split = (report["cross_source"].get(suite) or {}).get("by_provenance")
            if split:
                split.update({c: None for c in _CITED_CLASSES})
    return report


def write_review_csv(srs_text: str, path: str) -> int:
    from generators.requirement_oracle import model
    rows = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["req_id", "line", "kind", "signal", "op", "value", "unit", "status", "raw", "verdict(correct/wrong)"])
        for r in model(srs_text)["requirements"]:
            for line in r["lines"]:
                for f in line["facts"]:
                    w.writerow([r["req_id"], line["text"][:160], f["kind"], f.get("signal") or "", f.get("op"),
                                json.dumps(f.get("value")), f.get("unit") or "", f["status"], f.get("raw", ""), ""])
                    rows += 1
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--srs", required=True, help="SRS text export (read-only)")
    ap.add_argument("--sts", required=True, help="reference STS workbook (read-only)")
    ap.add_argument("--sts-generated", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--review-csv", default="")
    ap.add_argument("--system-docx", nargs="+", default=[], metavar="LABEL=PATH",   # (r2 I3) no value is an error
                    help="(R44) cited system documents, e.g. SyRS=path.docx SyDS=path.docx")
    ap.add_argument("--docs-dir", default="", help="(R44) folder of *.txt requirement/design documents (no test specs)")
    args = ap.parse_args(argv)
    text = Path(args.srs).read_text(encoding="utf-8")
    bad = [x for x in args.system_docx if "=" not in x or not x.split("=", 1)[0] or not x.split("=", 1)[1]]
    if bad:
        print(f"error: --system-docx wants LABEL=PATH: {bad}", file=sys.stderr)
        return 2
    system_docs = [tuple(x.split("=", 1)) for x in args.system_docx] or None
    try:
        documents = load_documents(args.docs_dir) if args.docs_dir else None
        report = evaluate(text, args.sts, args.sts_generated or None, system_docs, documents)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.review_csv:
        report["review_csv_rows"] = write_review_csv(text, args.review_csv)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    d = report["discrimination"]
    print(json.dumps({"recall": report["recall"]["recall"], "gold": report["recall"]["gold_items"],
                      "operator_consistent": report["recall"]["operator_consistent"],
                      "not_stated_in_srs": len(report["recall"]["not_stated_in_srs"]),
                      **{k: (v["killed"] if v["measurable"] else None, v["killed_optimistic"], v["mutants"])
                         for k, v in d.items()},
                      **{f"cross_{k}": (v["killed"] if v["measurable"] else None, v["killed_optimistic"], v["mutants"])
                         for k, v in report["cross_source"].items() if isinstance(v, dict) and "killed" in v},
                      **{f"cross_{k}_by_provenance": v.get("by_provenance")
                         for k, v in report["cross_source"].items() if isinstance(v, dict) and v.get("by_provenance")}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
