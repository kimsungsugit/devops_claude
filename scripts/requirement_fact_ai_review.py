"""(R57) AI review of the requirement oracle's facts — a proxy for G4(a) precision while no human labels exist.

`generators.requirement_oracle.model` reads every SRS sentence into facts (subject · comparison · value · unit). G4(a)
precision — how many of those facts the sentence really states — needs an independent judge; ``--review-csv`` of
`scripts/requirement_oracle_eval.py` waits for a person. Here an LLM reads each sentence with the facts the parser took
from it and says, per fact, ``correct`` or what is wrong (subject · value · comparison · unit · not a condition) and
quotes the sentence. Its answer counts only when the quote is in the sentence (or the line before/after it) and, for
``correct``, holds the fact's own text — an answer that fails that is ``unverified``, never a verdict.

This is **AI labelling, not human review**: the precision it gives is "the LLM agrees", reported as such; every
disagreement is listed with the sentence for a person to settle (``--csv`` has an empty column for that). Facts with no
subject (status ``partial``) are judged on value · comparison · unit only and counted apart.

The raw answers are cached (key: prompt version · sentence · context · fact — the answering model is stored with the
answer and counted, as in R52, so ``--no-ai`` reads them) and judged by today's checks on every run; an answer that cannot be read, a missing item and a failed call are ``call_failed`` (not cached) and the
first failed call stops the asking.

usage: requirement_fact_ai_review.py --srs SRS.txt --out review.json [--csv review.csv] [--cache cache.json]
                                     [--no-ai] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROMPT_VERSION = "fact-2"
BATCH = 12                       # facts per request (a line's facts stay together)
VERDICTS = ("correct", "wrong_subject", "wrong_value", "wrong_comparison", "wrong_unit", "not_a_condition",
            "cannot_tell")
SYSTEM_PROMPT = (
    "You check facts a parser extracted from automotive software requirement sentences (ISO 26262; Korean and "
    "English). Each item gives a sentence (and, when the parser joined it with the line before or after, that line) "
    "and one fact the parser read "
    "from it: subject (the signal or variable compared — null when the parser found none), comparison (>=, >, <=, <, "
    "==, !=, in_range), value (a number, a [low, high] range, or a reference name) and unit. Decide whether the "
    "SENTENCE states that fact:\n"
    "- correct: it does (for a null subject, judge comparison, value and unit only);\n"
    "- wrong_subject: the value is compared with something else than the subject given (say what in "
    "subject_in_sentence, copied from the sentence, or null);\n"
    "- wrong_value / wrong_comparison / wrong_unit: that part differs from the sentence (이상 is >=, 초과 is >, "
    "이하 is <=, 미만 is <);\n"
    "- not_a_condition: the text is no comparison of a quantity (an ID, a version, a list number, a label);\n"
    "- cannot_tell: the sentence alone does not decide it.\n"
    "Give quote: the shortest part of the sentence (or its context) that shows your answer, copied EXACTLY character "
    "for character, and parser_text: the item's fact parser_text copied unchanged. Never invent text. Return JSON only: "
    "{\"answers\": [{\"id\": <item id>, \"parser_text\": <the fact's parser_text>, \"verdict\": <one of the words "
    "above>, \"quote\": <exact substring>, \"subject_in_sentence\": <text or null>, \"reason\": <one short Korean "
    "sentence>}]}")


def _space(text: Any) -> str:
    from generators.sts_ai_review import _norm
    return _norm(text)


def facts_of(srs_text: str) -> list[dict[str, Any]]:
    """Every fact the oracle reads, with its sentence and context, in document order."""
    from generators.requirement_oracle import model
    out = []
    for r in model(srs_text)["requirements"]:
        for li, line in enumerate(r["lines"]):
            for fi, f in enumerate(line["facts"]):
                out.append({"req_id": r["req_id"], "line_no": li, "fact_no": fi, "sentence": line["text"],
                            "previous": line.get("previous_text") or "", "next": line.get("next_text") or "",
                            "fact": f})
    return out


def _shown(f: dict[str, Any]) -> dict[str, Any]:
    """The fact as the model sees it — what it claims, not how the parser got there."""
    value = f.get("value_text") if f.get("value_text") is not None else f.get("value")
    if f.get("kind") == "symbolic":
        value = f.get("reference")
    return {"subject": f.get("signal"), "comparison": f.get("op"), "value": value, "unit": f.get("unit") or "",
            "kind": f.get("kind"), "parser_text": f.get("raw")}


def _key(item: dict[str, Any]) -> str:
    # (review I2) the prompt itself is in the key: an edit without a version bump still asks again
    blob = json.dumps([PROMPT_VERSION, hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(), item["sentence"],
                       item["previous"], item["next"], _shown(item["fact"])], ensure_ascii=False, sort_keys=True)
    return "fact-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _anchored(quote: str, f: dict[str, Any]) -> bool:
    """(review W5) The quote holds the fact's own text, or one of its values as a whole number with the unit written
    after it — ``0`` is not found in ``10회``, ``5V 이상`` not in ``15V 이상``. Only the value is anchored: the subject
    and the comparison are the AI's judgement (said in the report)."""
    raw = _space(f.get("raw"))
    if raw and re.search(rf"(?<![0-9A-Za-z_.]){re.escape(raw)}", quote):
        return True                     # not inside a longer number or name (``5V 이상`` in ``15V 이상``)
    values = f.get("value_text") if isinstance(f.get("value_text"), list) else [f.get("value_text")]
    if f.get("kind") == "symbolic" and f.get("reference"):
        values = [f["reference"]]
    unit = str(f.get("unit") or "")
    for v in values:
        if v is None or not str(v).strip():
            continue
        pat = rf"(?<![0-9A-Za-z_.]){re.escape(str(v).strip())}(?![0-9A-Za-z_])"
        if unit:
            pat = rf"(?<![0-9A-Za-z_.]){re.escape(str(v).strip())}\s*{re.escape(unit)}"
        if re.search(pat, quote):
            return True
    return False


def check(answer: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Today's rules on one raw answer: ``{"status", "verdict", "quote", "subject_in_sentence", "reason", "why"}``.
    ``status`` — ``agree`` (correct, verified) · ``disagree`` (a wrong_* verdict, verified) · ``cannot_tell`` ·
    ``unverified`` (the answer fails a check: ``why`` says which)."""
    verdict = str(answer.get("verdict") or "").strip()
    quote = answer.get("quote") if isinstance(answer.get("quote"), str) else ""
    subject = answer.get("subject_in_sentence") if isinstance(answer.get("subject_in_sentence"), str) else None
    out = {"verdict": verdict, "quote": quote or None, "subject_in_sentence": subject,
           "reason": str(answer.get("reason") or "")[:300], "why": ""}
    texts = [_space(item["sentence"]), _space(item["previous"]), _space(item["next"])]
    if verdict not in VERDICTS:
        return {**out, "status": "unverified", "why": "verdict_unknown"}
    # (review W6) the answer names the fact it is about: an id shifted onto a neighbour is caught here
    if _space(answer.get("parser_text")) != _space(item["fact"].get("raw")):
        return {**out, "status": "unverified", "why": "answer_for_another_fact"}
    if verdict == "cannot_tell":
        return {**out, "status": "cannot_tell"}
    q = _space(quote)
    if not q or not any(q in t for t in texts if t):
        return {**out, "status": "unverified", "why": "quote_not_in_sentence"}
    f = item["fact"]
    if verdict == "correct":
        if not _anchored(q, f):
            return {**out, "status": "unverified", "why": "quote_misses_the_fact"}
        return {**out, "status": "agree"}
    if verdict == "wrong_subject" and subject and not any(_space(subject) in t for t in texts if t):
        return {**out, "status": "unverified", "why": "subject_not_in_sentence"}
    return {**out, "status": "disagree"}


def review(items: list[dict[str, Any]], *, ai_config: dict[str, Any] | None, cache_path: Path | None,
           llm: Callable[..., str | None] | None = None, limit: int | None = None) -> dict[str, Any]:
    """Give every item an ``ai`` result and return the run's record (asked · cached · failed · model)."""
    from generators.sts_ai_review import _answer_id, _load_cache, _parse, _save_cache
    model = str((ai_config or {}).get("model_override") or (ai_config or {}).get("model") or "")
    cache, cache_error = _load_cache(cache_path)
    todo = []
    run = {"model": model or None, "called": bool(ai_config), "asked": 0, "cached": 0, "call_failed": 0,
           "not_asked": 0, "cache_error": cache_error or None}
    for item in items:
        key = _key(item)
        hit = cache.get(key)
        if isinstance(hit, dict) and isinstance(hit.get("answer"), dict):
            item["ai"] = {**check(hit["answer"], item), "model": hit.get("model"), "cached": True}
            run["cached"] += 1
        elif not ai_config or (limit is not None and len(todo) >= limit):
            item["ai"] = {"status": "not_asked", "verdict": None, "quote": None, "why": "", "cached": False}
            run["not_asked"] += 1
        else:
            todo.append((item, key))
    if todo:
        if llm is None:
            from workflow.ai import llm_call as llm
        cfg = dict(ai_config or {}, temperature=0, retries=2, read_timeout=120)
        updates: dict[str, Any] = {}
        stopped = ""
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            answers: dict[int | None, dict[str, Any]] = {}
            failure, answered = stopped, model
            ids: Counter = Counter()
            if not stopped:
                payload = [{"id": i, "sentence": it["sentence"], "line_before": it["previous"],
                            "line_after": it["next"], "fact": _shown(it["fact"])} for i, (it, _k) in enumerate(batch)]
                run["asked"] += len(batch)
                meta: dict[str, Any] = {}
                try:
                    reply = llm(cfg, [{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)}],
                                meta_out=meta, stage="requirement_fact_review")
                except Exception as exc:  # noqa: BLE001 — the run reports the failure; nothing is guessed
                    print(f"AI call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                    reply = None
                answered = str(meta.get("model") or model)
                parsed = _parse(reply)
                if reply is None:
                    failure = stopped = "call failed — the rest is not asked"
                elif meta.get("truncated"):
                    failure = "reply truncated"
                elif not parsed:
                    failure = "reply not read"
                ids = Counter(_answer_id(a) for a in parsed)
                # (review W6) an id answered twice is no answer: the last one used to win silently
                answers = {_answer_id(a): a for a in parsed if ids[_answer_id(a)] == 1}
            for i, (it, key) in enumerate(batch):
                answer = answers.get(i)
                if failure or answer is None:
                    why = failure or ("answered twice" if ids.get(i, 0) > 1 else "item missing from the reply")
                    it["ai"] = {"status": "call_failed", "verdict": None, "quote": None,
                                "why": why, "model": answered, "cached": False}
                    run["call_failed"] += 1
                    continue
                it["ai"] = {**check(answer, it), "model": answered, "cached": False}
                updates[key] = {"model": answered, "answer": {k: answer.get(k) for k in
                                                             ("parser_text", "verdict", "quote", "subject_in_sentence",
                                                              "reason")}}
        run["cache_error"] = _save_cache(cache_path, updates) or run["cache_error"]
    run["answer_models"] = dict(Counter(str(it["ai"].get("model")) for it in items
                                        if it["ai"]["status"] not in ("not_asked", "call_failed")).most_common())
    return run


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by the parser's status (``parsed`` · ``partial``) and the AI's; the proxy precision is ``agree`` over
    ``agree + disagree`` of the parsed facts — None when none was judged."""
    out: dict[str, Any] = {}
    for status in ("parsed", "partial"):
        group = [it for it in items if it["fact"].get("status") == status]
        counts = Counter(it["ai"]["status"] for it in group)
        verdicts = Counter(it["ai"]["verdict"] for it in group if it["ai"]["status"] == "disagree")
        judged = counts["agree"] + counts["disagree"]
        out[status] = {"facts": len(group), **{s: counts[s] for s in ("agree", "disagree", "cannot_tell",
                                                                      "unverified", "call_failed", "not_asked")},
                       "disagree_by_verdict": dict(verdicts.most_common()),
                       "unverified_by_check": dict(Counter(it["ai"]["why"] for it in group
                                                           if it["ai"]["status"] == "unverified").most_common()),
                       "ai_agreement": round(counts["agree"] / judged, 4) if judged else None}
    return out


def _row(it: dict[str, Any]) -> dict[str, Any]:
    f = it["fact"]
    return {"req_id": it["req_id"], "sentence": it["sentence"], "fact": _shown(f), "parser_status": f.get("status"),
            "ai_status": it["ai"]["status"], "ai_verdict": it["ai"].get("verdict"), "quote": it["ai"].get("quote"),
            "subject_in_sentence": it["ai"].get("subject_in_sentence"), "reason": it["ai"].get("reason"),
            "why": it["ai"].get("why")}


def write_csv(items: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["req_id", "sentence", "subject", "comparison", "value", "unit", "parser_status", "ai_status",
                    "ai_verdict", "quote", "subject_in_sentence", "ai_reason", "human_verdict(correct/wrong)"])
        for it in items:
            r = _row(it)
            w.writerow([r["req_id"], r["sentence"][:300], r["fact"]["subject"] or "", r["fact"]["comparison"],
                        json.dumps(r["fact"]["value"], ensure_ascii=False), r["fact"]["unit"], r["parser_status"],
                        r["ai_status"], r["ai_verdict"] or "", r["quote"] or "", r["subject_in_sentence"] or "",
                        r["reason"] or "", ""])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--srs", required=True, help="SRS text export (read-only)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", default="", help="every fact with the AI's verdict and an empty column for a person")
    ap.add_argument("--cache", default=str(Path(__file__).resolve().parents[1] / ".devops_pro_cache"
                                           / "requirement_fact_ai_review.json"))
    ap.add_argument("--no-ai", action="store_true", help="cached answers only")
    ap.add_argument("--limit", type=int, default=None, help="ask at most N facts (the rest: not_asked, counted)")
    args = ap.parse_args(argv)
    started = time.monotonic()
    items = facts_of(Path(args.srs).read_text(encoding="utf-8"))
    ai_config = None
    if not args.no_ai:
        from workflow.ai import load_oai_config
        ai_config = load_oai_config(None)
        if not ai_config:
            print("error: no AI configuration (OAI_CONFIG_LIST) — use --no-ai for cached answers only", file=sys.stderr)
            return 2
    run = review(items, ai_config=ai_config, cache_path=Path(args.cache) if args.cache else None, limit=args.limit)
    report = {"srs": args.srs, "label": "AI 라벨 — 사람 검토 아님(불일치는 사람이 정할 목록)",
              "anchoring": "인용은 사실의 값(과 단위)·원문만 고정한다 — 주어·비교 판정은 AI 판단",
              "prompt_version": PROMPT_VERSION, "run": {**run, "elapsed_s": round(time.monotonic() - started, 1)},
              "summary": summarize(items),
              "disagreements": [_row(it) for it in items if it["ai"]["status"] == "disagree"],
              "unverified": [_row(it) for it in items if it["ai"]["status"] == "unverified"],
              "cannot_tell": [_row(it) for it in items if it["ai"]["status"] == "cannot_tell"]}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.csv:
        write_csv(items, args.csv)
    # (review I3) ASCII on stdout: a redirected cp949 console cannot encode every character of the run record
    print(json.dumps({"label": "AI label - not human review (ai_agreement = agree / (agree + disagree))",
                      "summary": report["summary"], "run": report["run"]}))
    return 0 if not run["call_failed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
