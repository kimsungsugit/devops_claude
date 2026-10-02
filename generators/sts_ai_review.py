"""(R52) AI 제안 — 요구 원문이 적지 않은 주어를 LLM 이 **후보 이름 중에서** 고르고, 그 근거를 **준 원문 그대로** 인용하게 한다.

사용자 방향(2026-10-01) "AI 활용해서(LLM) 진행해야할 것들은 리스트 뽑아주고 진행해": 'Requirement Review' 시트의 검토 항목 중
"값이 무엇의 값인지(주어) 원문에 없음" 류는 사람이 문서를 뒤져 신호를 정해야 한다 — 그 첫 후보를 LLM 이 낸다.

정직성 규약(이 모듈의 본체):
* 이름은 **후보 목록**(그 블록 이름, 그 문장 · 인용 블록 · 인용 요구 원문의 SW 변수와 네트, HSIS 신호 이름 · 변수 — 요구
  태그 제외)에 있는 것만 받는다 — 목록 밖 이름은 지어낸 것으로 보고 버린다. 목록을 상한에서 자르면 센다(리뷰 C1).
* 인용은 준 원문에 **글자 그대로** 있어야 하고(공백만 정규화), 사실의 숫자를 **모두** 숫자 경계로 적고, 그 이름(글자 그대로
  또는 이름 단어)을 적되 **다른 후보는 가리키지 않아야** 한다 — 아니면 버린다.
* 통과한 제안도 **대응이 맞다는 뜻이 아니다**: 이름이 실재하고 인용이 원문에 있다는 것만 확인됐다. 생성기는 이 제안을
  스텝·판정·경계 점에 쓰지 않는다 — 검토 시트 'AI 제안' 열과 공시에만 적고, 사람이 확인해 문서에 적으면 그때 경계 TC 가 된다.
* 호출은 ``ai_config`` 가 있을 때만. 캐시는 판정이 아니라 **원 답**(키: 문장 sha · 사실 · 사유 · 후보 · 모델이 본 원문 ·
  프롬프트 판)을 남겨 매번 오늘 규칙으로 다시 판정한다. 해석 못 한 답 · 빠진 답 · 잘린 답은 '정하지 못함' 이 아니라
  '호출 실패' 로 세고 캐시하지 않는다(리뷰 W3). ``ai_config`` 가 없으면 **캐시만** 읽는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

_logger = logging.getLogger(__name__)

SUBJECT_REASONS = frozenset({"no_subject_for_value", "subject_unclear", "no_subject_in_value_field",
                             "monitored_quantity_unknown"})
MAX_ASK = 150            # items asked per generation (the rest: "not_asked" — counted, never silent)
BATCH = 8                # items per LLM request
MAX_CANDIDATES = 80      # (review C1) HDPDM01 had 54~72 — 40 cut the HSIS names and the block name off every item
PROMPT_VERSION = "2"     # (review W4) in the cache key: a changed prompt asks again
_SW_VAR = re.compile(r"\b[us]\d+[gs]?_[A-Za-z]+_[A-Za-z0-9_]+\b")
_NET = re.compile(r"\b[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+\b")
_SPACE = re.compile(r"\s+")
_LABEL = re.compile(r"\[([A-Za-z][A-Za-z0-9_\-]*)\]")
_REQ_TOKEN = re.compile(r"(?:^|_)REQ(?:_|$)", re.IGNORECASE)
# (review r3) not inside a name (``u16g`` · ``V_BAT_12V`` · ``EN1``); hex and thousands as one token
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])([-\u2212\u2013\u2011\uff0d\u00b1]?)"
                     r"(0[xX][0-9A-Fa-f]+|\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|\d+(?:\.\d+)?)")
# (review r4 W1) the unit written right after a number \u2014 '5V' is no '5ms'
_UNIT_AFTER = re.compile(r"\s*\[?\s*([A-Za-z%\u2103\u00b0\u03a9\u00b5\u03bc]+(?:/[A-Za-z]+)?)")   # (review r5 I) ``4.85V/5.14V`` is V, not ``v/``
# a unit that makes a number a measured value (a count — ``3회`` · ``2 개`` — is none)
_MEASURE_UNITS = frozenset({"v", "mv", "kv", "a", "ma", "ua", "ms", "msec", "us", "ns", "s", "sec", "min", "h", "hz",
                            "khz", "mhz", "rpm", "%", "\u2103", "deg", "\u00b0", "m/s", "km/h", "\u03c9", "ohm", "kohm",
                            "bit", "lsb"})
_CACHE_LOCK = threading.Lock()
STATUS_TEXT = {"verified": "원문 인용·이름 실재 확인 — 대응은 사람 확인", "unknown": "AI 가 원문으로 정하지 못함",
               "rejected": "검증 실패로 버림", "not_asked": "묻지 않음(상한·AI 미호출)", "call_failed": "AI 호출 실패"}

SYSTEM_PROMPT = (
    "You help review automotive software requirements (ISO 26262). For each item, a requirement sentence gives a value "
    "(e.g. '4.85V 미만') but does not say which signal or variable the value is compared with. Choose that subject ONLY "
    "from the item's candidate list, and support it with ONE quote copied EXACTLY (character for character) from the "
    "item's texts that contains BOTH the value and the subject's name (or a word of it). A value-only 'Range' field's "
    "subject may be the block's own name. If no such quote exists, answer subject null. Never invent names or quotes.\n"
    "Return JSON only: {\"answers\": [{\"id\": <item id>, \"subject\": <candidate or null>, \"quote\": <exact substring "
    "or null>, \"reason\": <one short Korean sentence>}]}")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", str(text or "")).strip()


def _text_groups(item: dict[str, Any], requirements: dict[str, dict],
                 system: dict[str, dict[str, Any]] | None) -> tuple[list[str], list[str], list[str]]:
    """What the item may quote, nearest first: its sentence · the cited system block's fields (the item's source block)
    · the citing requirements' description and verification."""
    src = str(item.get("source") or "")
    m = re.match(r"(?:SyRS|SyDS) (\S+) · ", src)
    block = (system or {}).get(m.group(1)) if m else None
    own = [str(item.get("line") or "")]
    cited = [str(v) for v in ((block or {}).get("fields") or {}).values()]
    reqs = []
    for rid in item.get("srs_ids") or []:
        req = requirements.get(str(rid)) or {}
        reqs += [str(req.get("description") or ""), str(req.get("verification") or "")]
    return ([t for t in own if t.strip()], [t for t in cited if t.strip()], [t for t in reqs if t.strip()])


def _texts(item: dict[str, Any], requirements: dict[str, dict], system: dict[str, dict[str, Any]] | None) -> list[str]:
    own, cited, reqs = _text_groups(item, requirements, system)
    return own + reqs + cited


def _names_in(text: str) -> list[str]:
    # a requirement tag is no signal: ``[FS_REQ_MD_20]`` (KJPDS02_PV SRS) was proposed as the subject of '9V 이상'
    labels = set(_LABEL.findall(text))
    return _SW_VAR.findall(text) + [n for n in _NET.findall(text) if not re.fullmatch(r"(?:Sw|Sy|Hw)[A-Z]+_\d+", n)
                                    and n not in labels and not _REQ_TOKEN.search(n)]


def _candidates(item: dict[str, Any], requirements: dict[str, dict], system: dict[str, dict[str, Any]] | None,
                hsis_rows: list[dict[str, Any]] | None) -> tuple[list[str], int]:
    """``(names, cut)`` — the block's own name, the names of the item's sentence, of the cited block's fields, the HSIS
    rows' variables and names, then the citing requirements' names; at most `MAX_CANDIDATES` (``cut`` names dropped —
    counted, review C1: the order once put the HSIS and the block name last, and the cap took them)."""
    own, cited, reqs = _text_groups(item, requirements, system)
    names: list[str] = [str(item["block_name"])] if item.get("block_name") else []
    for t in own + cited:
        names += _names_in(t)
    for r in hsis_rows or []:
        names += list(r.get("vars") or []) + ([r["name"]] if r.get("name") else [])
    for t in reqs:
        names += _names_in(t)
    names = list(dict.fromkeys(n for n in names if n))
    return names[:MAX_CANDIDATES], max(0, len(names) - MAX_CANDIDATES)


def candidate_names(item: dict[str, Any], requirements: dict[str, dict], system: dict[str, dict[str, Any]] | None,
                    hsis_rows: list[dict[str, Any]] | None) -> list[str]:
    """The names a subject may be (`_candidates`)."""
    return _candidates(item, requirements, system, hsis_rows)[0]


def _key(item: dict[str, Any], cands: list[str], texts: list[str]) -> str:
    """The cache key — the prompt's version, the sentence (sha), the fact, the reason, the candidates and the texts the
    model saw (review W4: two blocks with one sentence and the same candidates shared an answer, and a changed
    description kept the old one). The model is in the value (shown in the cell)."""
    return hashlib.sha256("\x1f".join([PROMPT_VERSION, str(item.get("line_sha256")), str(item.get("fact")),
                                       str(item.get("reason")), *cands, "\x1e", *texts]).encode("utf-8")).hexdigest()


_REJECT_TEXT = {"name_not_in_candidates": "후보 목록에 없는 이름(지어낸 이름)",
                "quote_not_in_texts": "인용이 준 원문에 없음",
                "quote_does_not_link": "인용이 그 이름과 이 값을 함께 적지 않음",
                "quote_names_several": "인용이 다른 후보도 가리킴(이 이름을 가리키지 못함)",
                "subject_bound_elsewhere": "인용이 그 이름에 다른 값을 적음"}


def _token(name: str) -> str:
    """``name`` as a whole token: no word character either side, and no ``-`` joining it to one (``V_BAT`` is not written
    in ``V_BAT-MON`` — review r2 I1; a bullet ``-u16g_X`` still writes ``u16g_X`` — r3 I)."""
    return rf"(?<![A-Za-z0-9_])(?<![A-Za-z0-9_]-){re.escape(name)}(?![A-Za-z0-9_])(?!-[A-Za-z0-9_])"


def _written(name: str, text: str) -> bool:
    """``name`` written in ``text`` as a whole token (``MOTOR_SPEED`` is not written in ``MOTOR_SPEED_MAX``)."""
    return bool(re.search(_token(name), text))


_SIGNS = "-−–‑－±"     # hyphen-minus, minus, en dash, no-break hyphen, full-width (review r3 · r4 I), plus-minus


def _canon(number: str) -> str:
    """One spelling of a number: ``1,604`` = ``1604``, ``5.0`` = ``5``, ``0XFF`` = ``0xff`` (review r3 I — both sides
    read alike, so a spelling never decides)."""
    n = number.replace(",", "").lower()
    if n.startswith("0x"):
        return f"0x{int(n, 16):x}"          # (review r4 I) 0x000F = 0x0F
    whole, dot, frac = n.partition(".")
    whole, frac = whole.lstrip("0") or "0", frac.rstrip("0")
    return f"{whole}.{frac}" if dot and frac else whole


def _numbers(text: str) -> list[str]:
    """The numbers of ``text`` with their sign (review r2 W2: '-0.5V 이하' passed on '0.5V 이하'), canonical (`_canon`).
    A digit inside a name is no number (review r3 W1: ``u16g_…`` read as 16, ``V_BAT_12V`` as 12, ``EN1`` as 1). A sign is
    a ``-`` right before the digits and not after an ASCII letter, digit, ``.`` or ``)`` — ``0-5V`` and ``4.5V - 5.1V``
    are ranges, ``최소-5V`` is negative."""
    return [n for n, _unit in _values(text)]


def _values(text: str) -> list[tuple[str, str]]:
    """``(number, unit)`` of `_numbers` — the unit written right after it (``2.1[m/s]`` → ``m/s``), ``""`` when none. A
    ``±`` stays with its number (``±0.5`` is no ``0.5`` — review r4 I)."""
    text = str(text or "")
    out = []
    for m in _NUMBER.finditer(text):
        mark = m.group(1)
        # the pattern already keeps a ``-`` after an ASCII letter, digit or ``.`` out of the sign; ``(4.5)-5.1`` is a range too
        sign = "±" if mark == "±" else ("-" if mark and (text[m.start() - 1] if m.start() else "") != ")" else "")
        unit = _UNIT_AFTER.match(text, m.end())
        out.append((sign + _canon(m.group(2)), unit.group(1).lower().replace("°c", "℃") if unit else ""))
    return out


def _bound_elsewhere(name: str, quote: str, numbers: list[str], *, operator_only: bool) -> bool:
    """``name`` is written with a value of its own — the first number right after it (``:`` · ``=`` between) is not one
    of the item's: ``u16s_HALLPOWER_ERR_TM : 300ms`` names the 300 ms, not the 4.85 V the sentence gave
    ``u16g_ApiIn_HallSnsrLevel`` (KJPDS02_PV SySM_04 — the right name was rejected for it). A name followed by the item's
    value, by no value, or by a parenthesis (``Y(0~5V)`` describes its range — review r3 W3) is not bound elsewhere."""
    found = False
    for m in re.finditer(_token(name), quote):
        found = True
        rest = quote[m.end():m.end() + 20]
        # (review r4 W2) ``X == 300`` · ``X >= 300ms`` bind too; a parenthesis does not (``Y(0~5V)`` — r3 W3)
        lead = re.match(rf"\s*\)?\s*(?:(?P<op>[:=]=?|[<>]=?|[≥≤])|[은는이가])?\s*(?=[{_SIGNS}]?\d)", rest)
        if not lead:
            return False
        value = _values(rest[lead.end():])[:1]
        if not lead.group("op"):
            # (review r5) without an operator, a count (``Y가 3회 연속``) is no value of the name: to excuse a competitor
            #   an operator is needed; to reject the subject (``X 는 300ms`` · ``X 10ms 동안``) the number must be a measure
            if operator_only or not value or value[0][1] not in _MEASURE_UNITS:
                return False
        if not value or value[0][0] in numbers:
            return False
    return found          # not written here: nothing excuses it (the default must not)


def _verify(answer: dict[str, Any], item: dict[str, Any], cands: list[str], texts: list[str],
            synonyms: dict[str, frozenset] | None = None) -> dict[str, Any]:
    """(R52) A proposal passes only when the quote is in the texts, writes every number of the item's value (as a
    number — review W1: '5V 미만' passed on '15V'; '0~5V' passed on any '0'), and names the subject — or, for a value-only
    field (``Range``), the subject is the block's own name (its Name is what the field measures).

    It must point to this name and no other: another candidate written in the quote (review W2 — two variables and one
    value passed both), or, when the subject itself is not written, sharing the quote's name words (``Motor`` — every name
    of KJPDS02_PV carries it: ``u16g_DrvIn_MOTOR_C_FB`` passed for a door speed in m/s) rejects it. The names of one HSIS
    row are one signal (``synonyms`` — review I1: a row's net did not compete with its variable)."""
    from generators.sts_requirement_tc import _name_words, _names_agree
    subject, quote = answer.get("subject"), answer.get("quote")
    reason = _norm(answer.get("reason") or "")[:200]
    if not subject:
        return {"status": "unknown", "subject": None, "quote": None, "reason": reason}
    subject = str(subject)
    if subject not in cands:
        return {"status": "rejected", "subject": subject[:80], "quote": None, "reason": "name_not_in_candidates"}
    q = _norm(quote or "")
    if len(q) < 4 or not any(q in _norm(t) for t in texts):
        return {"status": "rejected", "subject": subject, "quote": q[:120] or None, "reason": "quote_not_in_texts"}
    numbers = _numbers(str(item.get("fact") or ""))
    quoted = _values(q)
    # every number of the value, with its unit when both sides write one (review r4 W1: '5V 미만' passed on '5ms')
    has_value = bool(numbers) and all(any(n == qn and (not u or not qu or u == qu) for qn, qu in quoted)
                                      for n, u in _values(str(item.get("fact") or "")))
    words = _name_words(q)
    literal = _written(subject, q)
    # (review r2 W4) without the name itself, every word of it must be in the quote — one shared word ('speed') tied
    #   ``u16g_ApiIn_MotorCountSpeed`` to a door speed
    own = _name_words(subject)
    names = literal or (bool(own) and all(_names_agree({w}, words) for w in own))
    block = item.get("reason") == "no_subject_in_value_field" and subject == str(item.get("block_name") or "")
    if not ((has_value and names) or block):
        return {"status": "rejected", "subject": subject, "quote": q[:120], "reason": "quote_does_not_link"}
    if literal and _bound_elsewhere(subject, q, numbers, operator_only=False):
        # (review r3 W2) the name written with a value of its own: '4.85V 미만이 u16s_HALLPOWER_ERR_TM : 300ms' gives the
        #   time constant its 300 ms — the rule that excuses a competitor rejects the subject
        return {"status": "rejected", "subject": subject, "quote": q[:120], "reason": "subject_bound_elsewhere"}
    by_block = block and not (has_value and names)
    same = (synonyms or {}).get(subject, frozenset())
    # (review r2 W1) a block name the quote ties to the value is a quote reading like any other: the competitors count
    if not by_block and (any(c != subject and c not in same and
                             ((_written(c, q) and not _bound_elsewhere(c, q, numbers, operator_only=True)) or
                              (not literal and _names_agree(_name_words(c), words))) for c in cands)
                         or _listed(subject, q)):
        return {"status": "rejected", "subject": subject, "quote": q[:120], "reason": "quote_names_several"}
    # (R52) the block's own name for a value-only field is no reading of the model's quote — the field itself is the
    #   evidence (a quote of the block's description, without the value, was shown as the proposal's ground)
    return {"status": "verified", "subject": subject, "quote": (_norm(item.get("line") or "") if by_block else q)[:200],
            "reason": reason, "by": "block_name" if by_block else ("quote" if literal else "words")}


_UNIT_WORDS = frozenset({"v", "mv", "kv", "a", "ma", "ua", "ms", "us", "ns", "s", "sec", "min", "hz", "khz", "mhz", "rpm",
                         "deg", "m", "mm", "cm", "km", "kb", "mb", "bit", "bits", "byte", "bytes", "lsb", "msb", "ohm",
                         "kohm", "bps", "kbps", "dc", "ac", "pwm"})


def _listed(name: str, quote: str) -> bool:
    """``name`` is one of a list of names written in one parenthesis — ``Control Signal(EN1, EN2, INA, INB, SE_EN) :
    0~5V``: the value belongs to all of them (HDPDM01 SyII_19), the quote pins none (a name without ``_`` is no
    candidate here). (review r2 W3) Only names make a list: ``(u8g_ApiIn_DoorSpeed [m/s])`` · ``(u16g_X, 0x0~0xFF,
    offset : 4V)`` hold one name and its unit or values."""
    for group in re.findall(r"\(([^()]*)\)", quote):
        if not _written(name, group):
            continue
        others = [f.strip() for f in re.split(r"[,/·;|]|\s+(?:및|또는|and|or)\s+", group)
                  if f.strip() and not _written(name, f)]
        if any(re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]+", f) and f.lower() not in _UNIT_WORDS for f in others):
            return True
    return False


def _parse(reply: str | None) -> list[dict[str, Any]]:
    text = (reply or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else {}
        except (ValueError, TypeError):
            data = {}
    answers = data.get("answers") if isinstance(data, dict) else None
    return [a for a in (answers or []) if isinstance(a, dict)]


def _int_or(value: Any, default: int) -> int:
    try:
        return int(value) if value is not None and value != "" else default
    except (TypeError, ValueError):
        return default


def _answer_id(answer: dict[str, Any]) -> int | None:
    """(review W3) ``"0"`` and ``0`` are one item."""
    try:
        return int(str(answer.get("id")).strip())
    except (TypeError, ValueError):
        return None


def _load_cache(path: Path | None) -> tuple[dict[str, Any], str]:
    """``(answers, error)``. (review W5) A file that is no JSON is moved aside, never overwritten by the next save; a file
    that cannot be read is said (and the save skipped — it would replace what it could not read)."""
    if not path or not path.is_file():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        data = None
    except OSError as exc:
        return {}, f"캐시를 읽지 못함 — {type(exc).__name__}"
    if isinstance(data, dict):
        return data, ""
    # no JSON, or JSON that is no answer map (review r2 I3) — kept aside, never overwritten by the next save
    aside = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        path.replace(aside)
    except OSError:
        return {}, f"손상된 캐시를 옮기지 못함({path.name})"
    _logger.warning("AI 제안 캐시가 답 목록이 아니라 옮김: %s", aside)
    return {}, ""


def _save_cache(path: Path | None, updates: dict[str, Any]) -> str:
    """Merge ``updates`` into the cache — ``""`` or what went wrong (review W5: a replace over a file another thread had
    open raised on Windows and the generation's answers were lost; the error went to the whole step's)."""
    if not path or not updates:
        return ""
    with _CACHE_LOCK:      # (X1) generations may run side by side: re-read, merge, replace atomically
        data, err = _load_cache(path)
        if err:
            return err
        data.update(updates)
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=path.name + ".",
                                             suffix=".tmp", delete=False) as fh:
                tmp = fh.name          # (review r2 I2) before writing: a full disk mid-dump left the file behind
                json.dump(data, fh, ensure_ascii=False, indent=1)
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    return ""
                except PermissionError:        # a reader has it open (Windows) — brief, then again
                    if attempt == 4:
                        raise
                    time.sleep(0.2 * (attempt + 1))
        except OSError as exc:
            _logger.warning("AI 제안 캐시 저장 실패: %s", exc, exc_info=True)
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    _logger.debug("임시 파일을 지우지 못함: %s", tmp)
            return f"캐시 저장 실패 — {type(exc).__name__}"
    return ""


def _synonyms(hsis_rows: list[dict[str, Any]] | None) -> dict[str, frozenset]:
    out: dict[str, frozenset] = {}
    for r in hsis_rows or []:
        names = frozenset(str(n) for n in [*(r.get("vars") or []), *([r["name"]] if r.get("name") else []),
                                            *(r.get("nets") or [])])
        for n in names:
            out[n] = out.get(n, frozenset()) | names
    return out


def propose_subjects(items: list[dict[str, Any]], requirements: list[dict], system: dict[str, dict[str, Any]] | None,
                     hsis_rows: list[dict[str, Any]] | None = None, *, ai_config: dict[str, Any] | None = None,
                     cache_path: str | Path | None = None, llm: Callable[..., str | None] | None = None,
                     on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Give every held-back subject item an ``ai_proposal`` (``{"status", "subject", "quote", "reason", "model",
    "cached"}``) and return the counts for the quality report. ``llm`` — ``workflow.ai.llm_call`` by default.

    (review W6) A failed call stops the asking: the remaining batches are ``call_failed`` without a call (a stalled
    service with the default retries took up to half an hour a batch); this step's retries and read timeout are short."""
    started = time.monotonic()
    reqs = {str(r.get("id")): r for r in requirements}
    eligible = [it for it in items if it.get("kind") == "held_back" and it.get("reason") in SUBJECT_REASONS]
    model = str((ai_config or {}).get("model_override") or (ai_config or {}).get("model") or "")
    cache_file = Path(cache_path) if cache_path else None
    with _CACHE_LOCK:
        cache, cache_error = _load_cache(cache_file)
    synonyms = _synonyms(hsis_rows)
    stats: dict[str, Any] = {"eligible": len(eligible), "verified": 0, "unknown": 0, "rejected": 0, "not_asked": 0,
                             "call_failed": 0, "cached": 0, "asked": 0, "model": model or None, "called": bool(ai_config),
                             "candidates_cut": 0, "hsis_rows": len(hsis_rows or [])}
    todo: list[tuple[dict[str, Any], list[str], list[str], str]] = []
    for it in eligible:
        cands, cut = _candidates(it, reqs, system, hsis_rows)
        stats["candidates_cut"] += bool(cut)
        texts = _texts(it, reqs, system)
        key = _key(it, cands, texts)
        hit = cache.get(key)
        if isinstance(hit, dict) and isinstance(hit.get("answer"), dict):
            # the raw answer is cached, never the verdict: today's checks judge it (a rule tightened since applies)
            it["ai_proposal"] = {**_verify(hit["answer"], it, cands, texts, synonyms), "model": hit.get("model"),
                                 "cached": True}
            stats["cached"] += 1
        elif not ai_config or not cands or len(todo) >= MAX_ASK:
            it["ai_proposal"] = {"status": "not_asked", "subject": None, "quote": None,
                                 "reason": "후보 이름 없음" if ai_config and not cands else "", "model": None,
                                 "cached": False}
        else:
            todo.append((it, cands, texts, key))
    if todo:
        if llm is None:
            from workflow.ai import llm_call as llm
        cfg = dict(ai_config or {}, temperature=0,
                   # (review r2 I4) 1..2 — `llm_call` reads 0 as "the default" (10); the read timeout is honoured by
                   #   the Gemini SDK path only (the others read LLM_READ_TIMEOUT) — the stop after a failure bounds them
                   retries=max(1, min(_int_or((ai_config or {}).get("retries"), 2), 2)),
                   read_timeout=max(10, min(_int_or((ai_config or {}).get("read_timeout"), 120), 120)))
        updates: dict[str, Any] = {}
        stopped = ""
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            if on_progress:
                on_progress(f"AI 제안 {min(start + BATCH, len(todo))}/{len(todo)}")
            answers: dict[int | None, dict[str, Any]] = {}
            failure, answered = stopped, model
            if not stopped:
                payload = [{"id": i, "value": it.get("fact"), "sentence": it.get("line"),
                            "candidates": cands, "texts": texts} for i, (it, cands, texts, _key_) in enumerate(batch)]
                stats["asked"] += len(batch)
                meta: dict[str, Any] = {}
                try:
                    reply = llm(cfg, [{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)}],
                                meta_out=meta, stage="sts_review_subject")
                except Exception as exc:  # noqa: BLE001 — a proposal never costs the STS; the count says it failed
                    _logger.warning("AI 제안 호출 실패: %s", exc, exc_info=True)
                    reply = None
                answered = str(meta.get("model") or model)
                parsed = _parse(reply)
                if reply is None:
                    failure = stopped = "호출 실패 — 남은 항목은 묻지 않음"
                elif meta.get("truncated"):
                    failure = "응답이 잘림"
                elif not parsed:
                    failure = "응답을 해석하지 못함"
                answers = {_answer_id(a): a for a in parsed}
            for i, (it, cands, texts, key) in enumerate(batch):
                answer = answers.get(i)
                if failure or answer is None:
                    # (review W3) no answer is no "could not decide" — counted as a failure, never cached
                    it["ai_proposal"] = {"status": "call_failed", "subject": None, "quote": None,
                                         "reason": failure or "응답에 이 항목이 없음", "model": answered, "cached": False}
                    continue
                it["ai_proposal"] = {**_verify(answer, it, cands, texts, synonyms), "model": answered, "cached": False}
                updates[key] = {"model": answered, "answer": {k: answer.get(k) for k in ("subject", "quote", "reason")}}
        cache_error = _save_cache(cache_file, updates) or cache_error
    for it in eligible:
        stats[it["ai_proposal"]["status"]] += 1
    # a block's own name for a value-only field repeats what the review sheet already says — counted apart, so the
    #   proposals that tie a name to the value in the text are not inflated by it
    stats["verified_by_block_name"] = sum(1 for it in eligible if it["ai_proposal"].get("by") == "block_name")
    # (review r2 W4) the name's words without the name itself are weaker than the name written — counted apart
    stats["verified_by_words"] = sum(1 for it in eligible if it["ai_proposal"].get("by") == "words")
    stats["verified_by_quote"] = stats["verified"] - stats["verified_by_block_name"] - stats["verified_by_words"]
    stats["elapsed_s"] = round(time.monotonic() - started, 1)
    if cache_error:
        stats["cache_error"] = cache_error
    return stats


def proposal_text(item: dict[str, Any]) -> str:
    """The 'AI 제안' cell: the subject and the quote with what was (and was not) checked — ``—`` when none. The model's
    own words are marked as its (review I3)."""
    p = item.get("ai_proposal")
    if not p:
        return "—"
    head = f"[{STATUS_TEXT.get(p['status'], p['status'])}]"
    if p["status"] == "verified":
        if p.get("by") == "block_name":
            return (f"AI 제안: 주어 = {p['subject']} — 값만 적는 칸 '{p['quote']}' 의 블록 이름 {head} (모델 "
                    f"{p.get('model') or '—'}" + (", 캐시" if p.get("cached") else "") + "). 스텝·판정에 쓰지 않음")
        how = ("인용이 이름의 단어를 모두 값과 함께 적음 — 이름 그대로는 아님" if p.get("by") == "words"
               else "인용이 이름과 값을 함께 적음")
        return (f"AI 제안: 주어 = {p['subject']} — 근거 인용 '{p['quote']}'({how}) {head} (모델 {p.get('model') or '—'}"
                + (", 캐시" if p.get("cached") else "") + "). 스텝·판정에 쓰지 않음")
    if p["status"] == "rejected":
        return f"{head} AI 가 낸 '{p.get('subject') or '—'}' — {_REJECT_TEXT.get(p.get('reason'), p.get('reason'))}"
    if p["status"] == "unknown":
        return head + (f" AI 설명: {p['reason']}" if p.get("reason") else "")
    return head + (f" {p['reason']}" if p.get("reason") else "")


# ── (R54) AI 제안: 감시 경로가 정해지지 않은 경계의 HW 감시 블록 ─────────────────────────────────────────────────────────
#
# 경계 값의 시스템 블록을 HW 요구 블록 여럿이 인용(허브)하면 생성기는 감시 경로를 정하지 않는다(R49/R50 — 이름 대조는
# 추측이라 하지 않는다). LLM 은 그 후보 블록 중 하나를 고르고 **그 블록 원문**에서 무엇을 감시하는지 적은 문장을 인용한다.
# 통과 조건: 후보 안의 블록 · 인용이 그 블록 원문에 있음 · 경계 주어(또는 그 SW 변수의 HSIS 행 이름)의 이름 단어가 인용과
# 맞고 다른 후보 블록의 이름과는 맞지 않음 · 경계 값이 그 블록이 재는 척도 위. 통과해도 경로를 정하지 않는다 — 'Requirement
# Evidence' 시트의 열과 공시에만, 사람이 확인해 HW 문서(또는 SRS Related ID)에 적으면 그때 경로가 된다.

PATH_PROMPT_VERSION = "path-2"   # (review I3) a domain prefix: never one of R52's keys
PATH_SYSTEM_PROMPT = (
    "You help review automotive HW/SW test specifications (ISO 26262). For each item, a requirement boundary value "
    "(subject, value, sentence) is linked to several candidate HW monitor blocks. Choose the ONE candidate block that "
    "monitors that subject, and support it with ONE quote copied EXACTLY (character for character) from THAT block's "
    "text which says what the block monitors. The subject may also be known by its aliases (its HSIS signal name and "
    "nets). If no candidate's text says it monitors this subject, answer hw_id null. "
    "Never invent IDs or quotes.\n"
    "Return JSON only: {\"answers\": [{\"id\": <item id>, \"hw_id\": <candidate id or null>, \"quote\": <exact substring "
    "of that block's text or null>, \"reason\": <one short Korean sentence>}]}")
_PATH_REJECT_TEXT = {"block_not_in_candidates": "후보 밖 블록(지어낸 ID)",
                     "quote_not_in_block": "인용이 고른 블록의 원문에 없음",
                     "quote_does_not_name_subject": "인용이 경계 주어(또는 그 HSIS 이름)를 적지 않음",
                     "subject_not_comparable": "주어와 인용을 단어로 대조할 수 없음(한글 주어 ↔ 영문 · 혼용 원문)",
                     "block_name_does_not_fit": "고른 블록의 이름이 경계 주어와 맞지 않음",
                     "subject_fits_another_block": "경계 주어가 다른 후보 블록과도 맞음",
                     "subject_has_no_name": "경계 주어에 대조할 이름이 없음(B+ 같은 기호 · 일반어뿐)",
                     "value_off_block_scale": "경계 값을 그 블록 척도로 확인할 수 없음(분압비 미기재 · 척도 밖)"}


def _path_items(test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The boundary evidences whose monitor path is undecided (``hw_tolerance_summary`` not ``certain``, two blocks or
    more) — in the order of the TCs."""
    out = []
    for tc in test_cases:
        for e in tc.get("requirement_evidence") or []:
            summary = e.get("hw_tolerance_summary") or {}
            # two blocks or more is an undecided path (`certain` means one block — the same test, once); (review I5) a
            #   path the HSIS refused (it points to a block named for another signal) is a document conflict to settle
            if summary and len(summary.get("blocks") or []) > 1 and not summary.get("path_refused"):
                out.append(e)
    return out


def _aliases(evidence: dict[str, Any], hsis_rows: list[dict[str, Any]] | None) -> list[str]:
    """(review I4) The HSIS row's name and nets of a SW-variable subject — what the verifier also reads, told to the
    model too."""
    from generators.sts_requirement_tc import _hsis_row
    row = _hsis_row(str(evidence.get("signal") or ""), hsis_rows or [])
    return list(dict.fromkeys(x for x in [row.get("name") or "", *row.get("nets", [])] if x)) if row else []


def _subject_words(evidence: dict[str, Any], hsis_rows: list[dict[str, Any]] | None) -> set[str]:
    """The name words of the boundary's subject — and, for a SW variable, of its HSIS row's name and nets (the row says
    which signal it is: ``u16g_ApiIn_Vsup`` → its net's ``BAT``)."""
    from generators.sts_requirement_tc import _hsis_row, _name_words
    signal = str(evidence.get("signal") or "")
    words = set(_name_words(signal))
    row = _hsis_row(signal, hsis_rows or [])
    if row:
        words |= _name_words(row.get("name") or "", *row.get("nets", []))
    return words


def _path_key(evidence: dict[str, Any], blocks: list[str], hw: dict[str, dict[str, Any]], words: set[str]) -> str:
    return hashlib.sha256("\x1f".join([PATH_PROMPT_VERSION, str(evidence.get("signal")), str(evidence.get("value")),
                                       str(evidence.get("unit")), str(evidence.get("line_sha256")), *blocks, "\x1e",
                                       *(str((hw.get(b) or {}).get("full_text") or "") for b in blocks), "\x1e",
                                       *sorted(words)]).encode("utf-8")).hexdigest()


def _verify_path(answer: dict[str, Any], evidence: dict[str, Any], blocks: list[str], hw: dict[str, dict[str, Any]],
                 words: set[str]) -> dict[str, Any]:
    """(R54) The proposed block passes only when it is a candidate, the quote is in its own text, the quote names the
    boundary's subject (a word of it, or of its HSIS row), no other candidate block's name does, and the value is on
    the block's scale (its tolerance is known at the value, directly or through a monitor ratio)."""
    from generators.sts_requirement_tc import _name_words
    hw_id, quote = answer.get("hw_id"), answer.get("quote")
    reason = _norm(answer.get("reason") or "")[:200]
    if not hw_id:
        return {"status": "unknown", "hw_id": None, "quote": None, "reason": reason}
    hw_id = str(hw_id)
    if hw_id not in blocks:
        return {"status": "rejected", "hw_id": hw_id[:40], "quote": None, "reason": "block_not_in_candidates"}
    q = _norm(quote or "")
    if len(q) < 4 or q not in _norm((hw.get(hw_id) or {}).get("full_text") or ""):
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120] or None, "reason": "quote_not_in_block"}
    if not words:
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120], "reason": "subject_has_no_name"}
    agree = _agree_script(words, _name_words(q))
    if agree is None:       # (review W3) nothing in the same script to compare: no reading, no "not written"
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120], "reason": "subject_not_comparable"}
    if not agree:
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120], "reason": "quote_does_not_name_subject"}
    # (review W1) the chosen block's own name must not say another signal (a quote 'Hall Sensor 전원은 Battery 전압으로
    #   부터' tied BAT to the Hall block), and no other candidate may fit — by its name, or by its text when its name is
    #   generic words only (``Power Supply Monitor`` names nothing to compare)
    # (review r2 W1) the same script on both sides for all three readings; what cannot be compared is said in the cell
    own = _agree_script(words, _name_words((hw.get(hw_id) or {}).get("name") or ""))
    if own is False:
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120], "reason": "block_name_does_not_fit"}
    others = []
    for b in blocks:
        if b == hw_id:
            continue
        other = _name_words((hw.get(b) or {}).get("name") or "") or _name_words((hw.get(b) or {}).get("full_text") or "")
        others.append(_agree_script(words, other))
    if any(others):
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120], "reason": "subject_fits_another_block"}
    # (review W2) the block's scale from every candidate before the sheet's cut; a relative tolerance checks no scale
    scale = ((evidence.get("hw_tolerance_summary") or {}).get("scale_by_block") or {}).get(hw_id, "unchecked")
    if scale == "unknown":
        return {"status": "rejected", "hw_id": hw_id, "quote": q[:120], "reason": "value_off_block_scale"}
    return {"status": "verified", "hw_id": hw_id, "name": str((hw.get(hw_id) or {}).get("name") or ""),
            "quote": q[:200], "reason": reason, "scale": scale,
            "name_check": "agrees" if own else "not_comparable",
            "others_check": "not_comparable" if any(o is None for o in others) else "differ"}


def _agree_script(a: set[str], b: set[str]) -> bool | None:
    """`_names_agree`, and where it cannot compare (one side Korean only — review r2 W1) the Korean words of both sides
    and the other words of both sides compared apart: ``True`` when either agrees, ``False`` when one could be compared
    and none agrees, ``None`` when nothing in the same script is on both sides."""
    from generators.sts_requirement_tc import _names_agree
    got = _names_agree(a, b)
    if got is not None:
        return got
    ka = {w for w in a if re.fullmatch(r"[가-힣]+", w)}
    kb = {w for w in b if re.fullmatch(r"[가-힣]+", w)}
    parts = [_names_agree(x, y) for x, y in ((ka, kb), (a - ka, b - kb)) if x and y]
    parts = [p for p in parts if p is not None]
    return any(parts) if parts else None


def propose_paths(test_cases: list[dict[str, Any]], hw: dict[str, dict[str, Any]] | None,
                  hsis_rows: list[dict[str, Any]] | None = None, *, ai_config: dict[str, Any] | None = None,
                  cache_path: str | Path | None = None, llm: Callable[..., str | None] | None = None,
                  on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Give every boundary evidence with an undecided monitor path an ``ai_path`` (``{"status", "hw_id", "quote",
    "reason", "model", "cached"}``) and return the counts. One question per distinct boundary (the same subject, value,
    sentence and candidates share the answer). The cache holds the raw answer; a failed call stops the asking."""
    started = time.monotonic()
    items = _path_items(test_cases) if hw else []
    model = str((ai_config or {}).get("model_override") or (ai_config or {}).get("model") or "")
    cache_file = Path(cache_path) if cache_path else None
    with _CACHE_LOCK:
        cache, cache_error = _load_cache(cache_file)
    groups: dict[str, list[dict[str, Any]]] = {}
    meta_of: dict[str, tuple[list[str], set[str]]] = {}
    for e in items:
        blocks = list((e.get("hw_tolerance_summary") or {}).get("blocks") or [])
        words = _subject_words(e, hsis_rows)
        key = _path_key(e, blocks, hw or {}, words)
        groups.setdefault(key, []).append(e)
        meta_of[key] = (blocks, words)
    stats: dict[str, Any] = {"eligible": len(items), "distinct": len(groups), "verified": 0, "unknown": 0,
                             "rejected": 0, "not_asked": 0, "call_failed": 0, "cached": 0, "asked": 0,
                             "model": model or None, "called": bool(ai_config)}
    proposals: dict[str, dict[str, Any]] = {}
    todo: list[str] = []
    for key, members in groups.items():
        blocks, words = meta_of[key]
        hit = cache.get(key)
        if isinstance(hit, dict) and isinstance(hit.get("answer"), dict):
            proposals[key] = {**_verify_path(hit["answer"], members[0], blocks, hw or {}, words),
                              "model": hit.get("model"), "cached": True}
            stats["cached"] += 1
        elif not ai_config or len(todo) >= MAX_ASK:
            proposals[key] = {"status": "not_asked", "hw_id": None, "quote": None, "reason": "", "model": None,
                              "cached": False}
        else:
            todo.append(key)
    if todo:
        if llm is None:
            from workflow.ai import llm_call as llm
        cfg = dict(ai_config or {}, temperature=0,
                   retries=max(1, min(_int_or((ai_config or {}).get("retries"), 2), 2)),
                   read_timeout=max(10, min(_int_or((ai_config or {}).get("read_timeout"), 120), 120)))
        updates: dict[str, Any] = {}
        stopped = ""
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            if on_progress:
                on_progress(f"AI 감시 경로 제안 {min(start + BATCH, len(todo))}/{len(todo)}")
            answers: dict[int | None, dict[str, Any]] = {}
            failure, answered = stopped, model
            if not stopped:
                payload = []
                for i, key in enumerate(batch):
                    e, (blocks, _w) = groups[key][0], meta_of[key]
                    payload.append({"id": i, "subject": e.get("signal"), "subject_aliases": _aliases(e, hsis_rows),
                                    "value": f"{e.get('value')}{e.get('unit') or ''}", "sentence": e.get("line"),
                                    "candidates": [{"hw_id": b, "name": (hw or {}).get(b, {}).get("name"),
                                                    "text": str((hw or {}).get(b, {}).get("full_text") or "")[:1500]}
                                                   for b in blocks]})
                stats["asked"] += len(batch)
                meta: dict[str, Any] = {}
                try:
                    reply = llm(cfg, [{"role": "system", "content": PATH_SYSTEM_PROMPT},
                                      {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)}],
                                meta_out=meta, stage="sts_review_monitor_path")
                except Exception as exc:  # noqa: BLE001 — a proposal never costs the STS; the count says it failed
                    _logger.warning("AI 감시 경로 제안 호출 실패: %s", exc, exc_info=True)
                    reply = None
                answered = str(meta.get("model") or model)
                parsed = _parse(reply)
                if reply is None:
                    failure = stopped = "호출 실패 — 남은 항목은 묻지 않음"
                elif meta.get("truncated"):
                    failure = "응답이 잘림"
                elif not parsed:
                    failure = "응답을 해석하지 못함"
                answers = {_answer_id(a): a for a in parsed}
            for i, key in enumerate(batch):
                answer = answers.get(i)
                if failure or answer is None:
                    proposals[key] = {"status": "call_failed", "hw_id": None, "quote": None,
                                      "reason": failure or "응답에 이 항목이 없음", "model": answered, "cached": False}
                    continue
                blocks, words = meta_of[key]
                proposals[key] = {**_verify_path(answer, groups[key][0], blocks, hw or {}, words), "model": answered,
                                  "cached": False}
                updates[key] = {"model": answered, "answer": {k: answer.get(k) for k in ("hw_id", "quote", "reason")}}
        cache_error = _save_cache(cache_file, updates) or cache_error
    for key, members in groups.items():
        for e in members:
            e["ai_path"] = proposals[key]
        stats[proposals[key]["status"]] += len(members)
    stats["verified_distinct"] = sum(1 for p in proposals.values() if p["status"] == "verified")
    stats["elapsed_s"] = round(time.monotonic() - started, 1)
    if cache_error:
        stats["cache_error"] = cache_error
    return stats


def path_proposal_text(evidence: dict[str, Any]) -> str:
    """The 'AI Path Proposal (Checked)' cell — ``—`` when the path was decided (or no HW tolerance)."""
    p = evidence.get("ai_path")
    if not p:
        return "—"
    head = f"[{STATUS_TEXT.get(p['status'], p['status'])}]"
    if p["status"] == "verified":
        scale = {"known": "값이 그 블록의 절대 허용오차 척도 위",
                 "scaled_unconfirmed": "값이 분압식 환산 척도 위(HSIS 로 확인 안 됨)",
                 "relative": "상대 허용오차라 척도는 확인 안 됨"}.get(p.get("scale"), "척도 확인 안 됨")
        name = "블록 이름과 맞음" if p.get("name_check") == "agrees" else "블록 이름과는 대조 불가"
        others = ("다른 후보 블록과는 이름 대조 불가" if p.get("others_check") == "not_comparable"
                  else "다른 후보 블록과는 안 맞음")
        return (f"AI 제안 감시 경로: {p['hw_id']} {p.get('name') or ''} — 그 블록 원문 인용 '{p['quote']}'(경계 주어의 이름이 "
                f"인용과 맞음 · {name} · {others} · {scale}) {head} (모델 {p.get('model') or '—'}"
                + (", 캐시" if p.get("cached") else "") + "). 경로 확정 · 판정에 쓰지 않음")
    if p["status"] == "rejected":
        return (f"{head} AI 가 낸 '{p.get('hw_id') or '—'}' — "
                f"{_PATH_REJECT_TEXT.get(p.get('reason'), p.get('reason'))}")
    if p["status"] == "unknown":
        return head + (f" AI 설명: {p['reason']}" if p.get("reason") else "")
    return head + (f" {p['reason']}" if p.get("reason") else "")
