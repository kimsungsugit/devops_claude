"""R57 — `scripts/requirement_fact_ai_review.py`: an LLM's verdict on each extracted fact counts only after the
sentence confirms its quote and the answer names the fact; the precision it gives is labelled AI, never human."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import requirement_fact_ai_review as rv  # noqa: E402

SRS = ("ID\tSwTR_0601\nName\tx\n"
       "- B+ 전압이 8.9V 미만일 경우 명령을 무시한다.\n"
       "- [u16g_ApiIn_X]\t-0x00~0xFF: 0~25V, 명령 10회 반복\n"
       "ID\tSwTR_0602\nName\ty\n"
       "- 500ms 초과 저전압 상황 동작 확인\n")


def _items():
    return rv.facts_of(SRS)


def _by(items, raw):
    return next(it for it in items if it["fact"]["raw"] == raw)


def _a(it, **kw):
    """An answer about this fact (it echoes the fact's parser text, as the prompt asks)."""
    return {"parser_text": it["fact"]["raw"], **kw}


def test_every_fact_comes_with_its_sentence_and_context():
    items = _items()
    assert [(it["req_id"], it["fact"]["raw"], it["fact"]["status"]) for it in items] == [
        ("SwTR_0601", "8.9V 미만", "parsed"), ("SwTR_0601", "0x00~0xFF", "parsed"), ("SwTR_0601", "0~25V", "parsed"),
        ("SwTR_0602", "500ms 초과", "partial")]
    assert _by(items, "8.9V 미만")["sentence"].startswith("- B+ 전압이 8.9V 미만")


def test_a_verdict_counts_only_when_the_sentence_confirms_it():
    it = _by(_items(), "8.9V 미만")
    assert rv.check(_a(it, verdict="correct", quote="B+ 전압이 8.9V 미만일"), it)["status"] == "agree"
    # the quote must be in the sentence (whitespace aside) …
    assert rv.check(_a(it, verdict="correct", quote="B+ 전압이 8.9V 이하일"), it)["why"] == "quote_not_in_sentence"
    assert rv.check(_a(it, verdict="correct", quote="B+   전압이 8.9V 미만일"), it)["status"] == "agree"
    # … and a "correct" quote must hold the fact itself, not another part of the sentence
    assert rv.check(_a(it, verdict="correct", quote="명령을 무시한다"), it)["why"] == "quote_misses_the_fact"
    wrong = rv.check(_a(it, verdict="wrong_comparison", quote="8.9V 미만", reason="x"), it)
    assert (wrong["status"], wrong["verdict"]) == ("disagree", "wrong_comparison")
    assert rv.check(_a(it, verdict="wrong_subject", quote="8.9V 미만", subject_in_sentence="배터리 전류"),
                    it)["why"] == "subject_not_in_sentence"
    assert rv.check(_a(it, verdict="wrong_subject", quote="8.9V 미만", subject_in_sentence="B+ 전압"),
                    it)["status"] == "disagree"
    assert rv.check(_a(it, verdict="cannot_tell", quote=None), it)["status"] == "cannot_tell"
    assert rv.check(_a(it, verdict="maybe", quote="8.9V 미만"), it)["why"] == "verdict_unknown"
    assert rv.check(_a(it, verdict="correct", quote=3), it)["why"] == "quote_not_in_sentence"


def test_an_answer_about_another_fact_is_not_this_facts_verdict():
    """(review W6) an id shifted onto the neighbour: the echoed parser text says whose answer it is."""
    it = _by(_items(), "0~25V")
    other = {"parser_text": "0x00~0xFF", "verdict": "correct", "quote": "0~25V"}
    assert rv.check(other, it)["why"] == "answer_for_another_fact"
    assert rv.check({"verdict": "correct", "quote": "0~25V"}, it)["why"] == "answer_for_another_fact"   # no echo


def test_a_value_is_anchored_as_a_whole_number_with_its_unit():
    """(review W5) a one-character value text is no anchor by itself: ``0`` is not in ``10회``, ``5V`` not in ``15V``."""
    it = _by(_items(), "0~25V")
    assert rv.check(_a(it, verdict="correct", quote="0~25V"), it)["status"] == "agree"
    assert rv.check(_a(it, verdict="correct", quote="25V"), it)["status"] == "agree"
    assert rv.check(_a(it, verdict="correct", quote="명령 10회"), it)["why"] == "quote_misses_the_fact"
    srs = "ID\tSwTR_0601\nName\tx\n- B+ 전압이 15V 이상 또는 5V 이상일 경우\n"
    five = next(i for i in rv.facts_of(srs) if i["fact"]["raw"] == "5V 이상")
    assert rv.check(_a(five, verdict="correct", quote="15V 이상"), five)["why"] == "quote_misses_the_fact"
    assert rv.check(_a(five, verdict="correct", quote="또는 5V"), five)["status"] == "agree"


def test_a_quote_from_the_joined_line_counts_and_one_from_elsewhere_does_not():
    it = dict(_by(_items(), "8.9V 미만"), previous="저전압 판단: B+ 8.9V 미만", next="")
    assert rv.check(_a(it, verdict="correct", quote="B+ 8.9V 미만"), it)["status"] == "agree"
    alone = dict(it, previous="")
    assert rv.check(_a(alone, verdict="correct", quote="B+ 8.9V 미만"), alone)["why"] == "quote_not_in_sentence"


def test_the_cache_key_is_what_the_model_was_shown():
    it = _by(_items(), "8.9V 미만")
    assert rv._key(it) == rv._key(dict(it))
    assert rv._key(it) != rv._key(dict(it, previous="다른 앞 줄"))
    assert rv._key(it) != rv._key(dict(it, sentence=it["sentence"] + " "))


def _fake(answers_for, calls, meta=None):
    def llm(cfg, messages, meta_out=None, stage=None):
        calls.append(json.loads(messages[1]["content"]))
        items = calls[-1]["items"]
        if meta_out is not None:
            meta_out["model"] = "fake-model"
            meta_out.update(meta or {})
        out = answers_for(items)
        return None if out is None else json.dumps({"answers": out}, ensure_ascii=False)
    return llm


def _all_correct(items):
    return [{"id": i["id"], "parser_text": i["fact"]["parser_text"], "verdict": "correct",
             "quote": i["fact"]["parser_text"]} for i in items]


def test_raw_answers_are_cached_and_judged_again(tmp_path):
    cache = tmp_path / "c.json"
    calls = []
    items = _items()
    run = rv.review(items, ai_config={"model": "m"}, cache_path=cache, llm=_fake(_all_correct, calls))
    assert run["asked"] == 4 and run["call_failed"] == 0 and len(calls) == 1
    assert {it["ai"]["status"] for it in items} == {"agree"} and all(not it["ai"]["cached"] for it in items)
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert len(stored) == 4 and all(set(v["answer"]) == {"parser_text", "verdict", "quote", "subject_in_sentence",
                                                         "reason"} for v in stored.values())
    again = _items()
    run = rv.review(again, ai_config=None, cache_path=cache)
    assert run["cached"] == 4 and run["asked"] == 0 and {it["ai"]["status"] for it in again} == {"agree"}
    assert run["answer_models"] == {"fake-model": 4}            # who answered, though no model is configured now
    key = next(iter(stored))
    stored[key]["answer"]["quote"] = "not in any sentence"
    cache.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    third = _items()
    rv.review(third, ai_config=None, cache_path=cache)
    assert sum(it["ai"]["status"] == "unverified" for it in third) == 1


def test_answers_are_matched_by_id_not_by_position(tmp_path):
    items = _items()
    rv.review(items, ai_config={"model": "m"}, cache_path=tmp_path / "c.json",
              llm=_fake(lambda its: list(reversed(_all_correct(its))), []))
    assert {it["ai"]["status"] for it in items} == {"agree"}


def test_an_id_answered_twice_is_no_answer(tmp_path):
    """(review W6) ``wrong_value`` then ``correct`` for one id: the last one used to win silently."""
    def twice(its):
        out = []
        for a in _all_correct(its):
            out += [dict(a, verdict="wrong_value"), a]
        return out
    items = _items()
    run = rv.review(items, ai_config={"model": "m"}, cache_path=tmp_path / "c.json", llm=_fake(twice, []))
    assert run["call_failed"] == 4 and {it["ai"]["why"] for it in items} == {"answered twice"}
    assert not (tmp_path / "c.json").exists()


def test_a_failed_call_stops_the_asking_and_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "BATCH", 2)
    cache = tmp_path / "c.json"
    calls = []
    items = _items()
    run = rv.review(items, ai_config={"model": "m"}, cache_path=cache, llm=_fake(lambda _i: None, calls))
    assert len(calls) == 1 and run["asked"] == 2 and run["call_failed"] == 4    # the second batch is not asked
    assert {it["ai"]["status"] for it in items} == {"call_failed"} and not cache.exists()


def test_a_truncated_or_unread_reply_is_a_failure_not_a_verdict(tmp_path):
    items = _items()
    run = rv.review(items, ai_config={"model": "m"}, cache_path=tmp_path / "t.json",
                    llm=_fake(_all_correct, [], meta={"truncated": True}))
    assert run["call_failed"] == 4 and {it["ai"]["why"] for it in items} == {"reply truncated"}
    items = _items()
    run = rv.review(items, ai_config={"model": "m"}, cache_path=tmp_path / "c.json",
                    llm=_fake(lambda its: _all_correct(its)[:2], []))
    assert run["call_failed"] == 2 and [it["ai"]["status"] for it in items] == ["agree", "agree", "call_failed",
                                                                               "call_failed"]
    assert items[2]["ai"]["why"] == "item missing from the reply"


def test_the_limit_and_no_ai_leave_facts_not_asked_and_counted(tmp_path):
    items = _items()
    run = rv.review(items, ai_config={"model": "m"}, cache_path=tmp_path / "c.json",
                    llm=_fake(_all_correct, []), limit=1)
    assert run["asked"] == 1 and run["not_asked"] == 3
    items = _items()
    assert rv.review(items, ai_config=None, cache_path=tmp_path / "none.json")["not_asked"] == 4


def test_the_summary_separates_partial_facts_and_counts_only_judged_answers(tmp_path):
    items = _items()

    def answers(its):
        out = _all_correct(its)
        for a, i in zip(out, its, strict=True):
            if i["fact"]["parser_text"] == "0x00~0xFF":
                a.update(verdict="not_a_condition", quote="0x00~0xFF")
            if i["fact"]["parser_text"] == "8.9V 미만":
                a.update(verdict="cannot_tell")
        return out
    rv.review(items, ai_config={"model": "m"}, cache_path=tmp_path / "c.json", llm=_fake(answers, []))
    s = rv.summarize(items)
    assert (s["parsed"]["facts"], s["parsed"]["agree"], s["parsed"]["disagree"], s["parsed"]["cannot_tell"]) == \
        (3, 1, 1, 1)
    # cannot_tell is no judgement: agree / (agree + disagree) only
    assert s["parsed"]["ai_agreement"] == 0.5 and s["parsed"]["disagree_by_verdict"] == {"not_a_condition": 1}
    assert (s["partial"]["facts"], s["partial"]["agree"], s["partial"]["ai_agreement"]) == (1, 1, 1.0)
    assert rv.summarize([])["parsed"]["ai_agreement"] is None             # nothing judged: no rate


def test_main_without_ai_writes_the_report_and_the_csv(tmp_path):
    srs = tmp_path / "srs.txt"
    srs.write_text(SRS, encoding="utf-8")
    out, table = tmp_path / "r.json", tmp_path / "r.csv"
    assert rv.main(["--srs", str(srs), "--out", str(out), "--csv", str(table), "--no-ai",
                    "--cache", str(tmp_path / "c.json")]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["label"].startswith("AI 라벨") and report["summary"]["parsed"]["not_asked"] == 3
    assert "주어·비교 판정은 AI 판단" in report["anchoring"]
    rows = table.read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 5 and rows[0].endswith("human_verdict(correct/wrong)")
