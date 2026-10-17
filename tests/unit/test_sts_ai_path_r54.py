"""R54 — AI 제안 감시 경로: 문서가 정하지 않은(허브) 경계의 HW 감시 블록을 LLM 이 후보 중에서 고르고 그 블록 원문을 인용한다.

사용자 방향(2026-10-02) "진행해" — R52 다음 LLM 후보. 정직성 규약은 R52 와 같다:
* 후보 밖 블록 · 그 블록 원문에 없는 인용은 버린다,
* 인용이 경계 주어(SW 변수면 그 HSIS 행의 이름 · 네트도)의 이름 단어를 적어야 하고, 그 이름이 다른 후보 블록의 이름과도
  맞으면 버린다(이 블록을 가리키지 못한다), 경계 값이 그 블록이 재는 척도 밖이면 버린다,
* 통과해도 경로를 정하지 않는다 — 'Requirement Evidence' 시트 열 · 공시에만,
* 캐시는 원 답, AI 설정이 없으면 캐시만, 호출 실패는 셈하고 다음 배치를 묻지 않는다.
"""
from __future__ import annotations

import json

import openpyxl

from generators.sts_ai_review import _verify_path, path_proposal_text, propose_paths

HW = {
    "HwTSR_0203": {"name": "Hall Sensor Block 전원 Monitor",
                   "full_text": "HwTSR_0203 / Hall Sensor Block 전원 Monitor / Hall Sensor Block 전원이상을 감지하기 위한 "
                                "Monitor Interface를 구성한다. / 허용 오차: ±0.15V"},
    "HwTSR_0204": {"name": "Battery Voltage Monitor",
                   "full_text": "HwTSR_0204 / Battery Voltage Monitor / Battery입력전압 이상 발생 시 Controller의 안전모드 "
                                "천이를 위한 Battery Monitor Interface를 구성한다. / Sampling rate: 200 Sample/sec / "
                                "허용 오차: ±3%"},
}
BLOCKS = ["HwTSR_0203", "HwTSR_0204"]
CFG = {"model": "m-test"}


def _evidence(signal="BAT 전압", value="16.0", line="BAT 전압(16.0V) 초과 시 정지", scale_known=(True, True)):
    return {"srs_id": "SwTSR_0302", "signal": signal, "value": value, "unit": "V", "line": line,
            "line_sha256": line[:6], "kind": "threshold",
            "hw_tolerance": [{"hw_id": b, "scale_known": k} for b, k in zip(BLOCKS, scale_known, strict=True)],
            "hw_tolerance_summary": {"blocks": list(BLOCKS), "certain": False,
                                     "scale_by_block": {b: "known" if k else "unknown" for b, k in zip(BLOCKS, scale_known, strict=True)}}}


def _llm(answers, calls=None):
    def call(cfg, messages, stage=None, meta_out=None):
        if calls is not None:
            calls.append(json.loads(messages[1]["content"]))
        return json.dumps({"answers": answers})
    return call


def _tc(*evidences):
    return [{"id": f"TC_{i}", "requirement_evidence": [e]} for i, e in enumerate(evidences)]


QUOTE = "Battery입력전압 이상 발생 시 Controller의 안전모드 천이를 위한 Battery Monitor Interface를 구성한다."


def test_a_block_naming_the_subject_in_its_own_text_passes():
    got = _verify_path({"hw_id": "HwTSR_0204", "quote": QUOTE}, _evidence(), BLOCKS, HW, {"bat"})
    assert got["status"] == "verified" and got["name"] == "Battery Voltage Monitor"


def test_each_rule_rejects():
    ev = _evidence()
    cases = [({"hw_id": "HwTSR_9999", "quote": QUOTE}, {"bat"}, "block_not_in_candidates"),
             ({"hw_id": "HwTSR_0203", "quote": QUOTE}, {"bat"}, "quote_not_in_block"),      # the other block's text
             ({"hw_id": "HwTSR_0204", "quote": QUOTE}, set(), "subject_has_no_name"),        # 'B+'
             ({"hw_id": "HwTSR_0204", "quote": "Sampling rate: 200 Sample/sec"}, {"bat"}, "quote_does_not_name_subject"),
             ({"hw_id": "HwTSR_0204", "quote": "허용 오차: ±3%"}, {"bat"}, "subject_not_comparable"),
             ({"hw_id": "HwTSR_0204", "quote": QUOTE}, {"bat", "hall"}, "subject_fits_another_block")]
    for answer, words, reason in cases:
        assert _verify_path(answer, ev, BLOCKS, HW, words)["reason"] == reason, reason
    off = _evidence(scale_known=(True, False))
    assert _verify_path({"hw_id": "HwTSR_0204", "quote": QUOTE}, off, BLOCKS, HW, {"bat"})["reason"] == \
        "value_off_block_scale"
    assert _verify_path({"hw_id": None}, ev, BLOCKS, HW, {"bat"})["status"] == "unknown"


def test_one_question_per_distinct_boundary_and_every_member_gets_it():
    calls: list = []
    a, b = _evidence(), _evidence()                         # the same boundary under two TCs
    stats = propose_paths(_tc(a, b), HW, None, ai_config=CFG, llm=_llm(
        [{"id": 0, "hw_id": "HwTSR_0204", "quote": QUOTE}], calls))
    assert len(calls) == 1 and len(calls[0]["items"]) == 1
    assert (stats["eligible"], stats["distinct"], stats["verified"], stats["verified_distinct"]) == (2, 1, 2, 1)
    assert a["ai_path"]["status"] == b["ai_path"]["status"] == "verified"
    assert "AI 제안 감시 경로: HwTSR_0204 Battery Voltage Monitor" in path_proposal_text(a)
    assert "경로 확정 · 판정에 쓰지 않음" in path_proposal_text(a)


def test_a_decided_path_is_not_asked():
    decided = _evidence()
    decided["hw_tolerance_summary"] = {"blocks": ["HwTSR_0204"], "certain": True}
    stats = propose_paths(_tc(decided), HW, None, ai_config=CFG, llm=_llm([]))
    assert stats["eligible"] == 0 and "ai_path" not in decided and path_proposal_text(decided) == "—"


def test_the_hsis_row_names_a_variable_subject():
    """``u16g_ApiIn_Vsup`` names no battery — its HSIS row's net does."""
    rows = [{"id": "HSI_30", "vars": ["u16g_ApiIn_Vsup"], "ids": [], "nets": ["V_BAT_MON"], "name": "V_BAT_MON"}]
    ev = _evidence(signal="u16g_ApiIn_Vsup")
    propose_paths(_tc(ev), HW, rows, ai_config=CFG, llm=_llm([{"id": 0, "hw_id": "HwTSR_0204", "quote": QUOTE}]))
    assert ev["ai_path"]["status"] == "verified"
    alone = _evidence(signal="u16g_ApiIn_Vsup")
    propose_paths(_tc(alone), HW, None, ai_config=CFG, llm=_llm([{"id": 0, "hw_id": "HwTSR_0204", "quote": QUOTE}]))
    assert alone["ai_path"]["reason"] == "quote_does_not_name_subject"


def test_the_cache_holds_the_answer_and_no_ai_reads_it_only(tmp_path):
    cache = tmp_path / "ai.json"
    propose_paths(_tc(_evidence()), HW, None, ai_config=CFG, cache_path=cache,
                  llm=_llm([{"id": 0, "hw_id": "HwTSR_0204", "quote": QUOTE}]))
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert [set(v) for v in saved.values()] == [{"model", "answer"}]

    def no_call(*_a, **_k):
        raise AssertionError("no call without ai_config")
    again = _evidence()
    stats = propose_paths(_tc(again), HW, None, cache_path=cache, llm=no_call)
    assert (stats["cached"], stats["called"], again["ai_path"]["status"]) == (1, False, "verified")
    other = _evidence(value="16.5")                         # another boundary: not asked without AI
    assert propose_paths(_tc(other), HW, None, cache_path=cache, llm=no_call)["not_asked"] == 1


def test_a_failure_is_counted_never_cached_and_stops_the_asking(tmp_path):
    cache = tmp_path / "ai.json"
    calls = []

    def down(cfg, messages, stage=None, meta_out=None):
        calls.append(1)
        raise ConnectionError("refused")
    many = [_evidence(value=str(10 + i)) for i in range(10)]
    stats = propose_paths(_tc(*many), HW, None, ai_config=CFG, cache_path=cache, llm=down)
    assert len(calls) == 1 and stats["call_failed"] == 10 and not cache.exists()

    def refuse(cfg, messages, stage=None, meta_out=None):
        return "cannot"
    refused = _evidence()
    assert propose_paths(_tc(refused), HW, None, ai_config=CFG, llm=refuse)["call_failed"] == 1
    assert refused["ai_path"]["reason"] == "응답을 해석하지 못함"

    def truncated(cfg, messages, stage=None, meta_out=None):
        meta_out["truncated"] = True              # a valid-looking answer in a cut reply is no answer
        return json.dumps({"answers": [{"id": 0, "hw_id": "HwTSR_0204", "quote": QUOTE}]})
    cut = _evidence()
    stats = propose_paths(_tc(cut), HW, None, ai_config=CFG, cache_path=cache, llm=truncated)
    assert stats["call_failed"] == 1 and cut["ai_path"]["reason"] == "응답이 잘림" and not cache.exists()


def test_the_evidence_sheet_has_the_column_and_the_kb_leaves_it_out(tmp_path):
    from generators.sts_requirement_tc import (
        REQUIREMENT_EVIDENCE_HEADERS,
        hw_tolerance_summary,
        write_requirement_evidence_sheet,
    )
    from scripts.sts_findings_to_kb import build_documents
    ev = _evidence()
    ev.update(kind="threshold", op=">", step="0.1", step_basis="written", points=[], combination_note="",
              reference_constant=None, source=None)
    ev["hw_tolerance"] = [{"hw_id": b, "name": HW[b]["name"], "text": "허용 오차: ±3%", "shared": ["SySM_04"],
                           "scaled_by": None, "scale": None, "scale_net_mismatch": None, "scale_conflict": None,
                           "direct": True, "scale_known": True, "size": "0.48", "written_size": None, "unit": "V",
                           "inside": True, "hsis": None, "hsis_mismatch": None} for b in BLOCKS]
    ev["hw_tolerance_summary"] = hw_tolerance_summary(ev)
    propose_paths(_tc(ev), HW, None, ai_config=CFG, llm=_llm([{"id": 0, "hw_id": "HwTSR_0204", "quote": QUOTE}]))
    wb = openpyxl.Workbook()
    write_requirement_evidence_sheet(wb, _tc(ev))
    rows = list(wb["Requirement Evidence"].iter_rows(values_only=True))
    assert rows[0][-1] == REQUIREMENT_EVIDENCE_HEADERS[-1] == "AI Path Proposal (Checked)"
    assert rows[1][-1].startswith("AI 제안 감시 경로: HwTSR_0204")
    wb.save(tmp_path / "HD_STS.xlsm")
    docs = build_documents(str(tmp_path / "HD_STS.xlsm"), "HD", allow_empty=True)
    assert docs and not any("AI 제안" in d["content"] or "AI Path" in d["content"] for d in docs)


def test_the_disclosure_counts_and_warns_on_failure():
    from report_gen.generation_disclosures import build_disclosures

    def item(ai):
        return {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"requirement_boundary": {
            "tcs": 1, "steps": 1, "facts": 1, "facts_used": 1, "ai_path": ai}}})}.get("sts_ai_path")
    base = {"eligible": 43, "distinct": 10, "verified": 14, "rejected": 20, "unknown": 9, "not_asked": 0, "cached": 0,
            "model": "m", "called": True, "asked": 10, "elapsed_s": 3.1}
    got = item(base)
    assert got["value"] == "인용 확인 14 / 43" and got["tone"] == "info" and "경로는 정하지 않는다" in got["note"]
    assert item({**base, "call_failed": 5})["tone"] == "warning"
    assert item({"error": "RuntimeError: x"})["tone"] == "warning"
    assert item({"eligible": 0}) is None


def test_the_generator_asks_only_with_hw_requirements(tmp_path, monkeypatch):
    """No HwRS: no monitor path at all, no key; a HwRS read: the step runs (and says what it found)."""
    from generators import sts as sts_mod
    from generators import sts_requirement_tc as tc_mod
    text = ["SwTSR_0101: 센서 전원 이상 시 고장을 검출한다. Verification: Pull-up Port를 4.85V 미만으로 Setting"]
    out = sts_mod.generate_sts(text, {}, str(tmp_path / "a.xlsm"),
                               project_config={"project_id": "T", "ai_review_cache": str(tmp_path / "ai.json")})
    assert "ai_path" not in out["quality_report"]["generation_stats"]["requirement_boundary"]
    monkeypatch.setattr(tc_mod, "load_hw_requirements", lambda _p: ({}, {"file": "hw.docx"}))
    out = sts_mod.generate_sts(text, {}, str(tmp_path / "b.xlsm"), hwrs_path=str(tmp_path / "hw.docx"),
                               project_config={"project_id": "T", "ai_review_cache": str(tmp_path / "ai.json")})
    assert out["quality_report"]["generation_stats"]["requirement_boundary"]["ai_path"]["eligible"] == 0


# ── review round 1 ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_chosen_blocks_own_name_must_not_say_another_signal():
    """(review W1 b) 'Hall Sensor 전원은 Battery 전압으로부터 공급' in the Hall block tied BAT to the Hall block."""
    hw = {**HW, "HwTSR_0203": {**HW["HwTSR_0203"], "full_text": HW["HwTSR_0203"]["full_text"]
                               + " / Hall Sensor 전원은 Battery 전압으로부터 공급된다."}}
    got = _verify_path({"hw_id": "HwTSR_0203", "quote": "Hall Sensor 전원은 Battery 전압으로부터 공급된다."},
                       _evidence(), BLOCKS, hw, {"bat"})
    assert got["reason"] == "block_name_does_not_fit"


def test_a_generic_named_competitor_is_read_by_its_text():
    """(review W1 a) 'Power Supply Monitor' names nothing to compare — its text says the battery: it competes."""
    hw = {**HW, "HwX_01": {"name": "Power Supply Monitor", "full_text": "Battery 입력 전원을 감시한다."}}
    got = _verify_path({"hw_id": "HwTSR_0204", "quote": QUOTE}, _evidence(), [*BLOCKS, "HwX_01"], hw, {"bat"})
    assert got["reason"] == "subject_fits_another_block"


def test_the_scale_is_read_per_block_before_the_cut_and_a_relative_tolerance_is_said():
    """(review W2) a block cut from the sheet's three skipped the check; a relative tolerance checks no scale."""
    from generators.sts_requirement_tc import hw_tolerance_summary
    tol = [{"hw_id": "HwTSR_0203", "scale_known": True, "relative": False, "size": "0.15", "written_size": None,
            "direct": True},
           {"hw_id": "HwTSR_0204", "scale_known": True, "relative": True, "size": "0.48", "written_size": None,
            "direct": True},
           {"hw_id": "HwTSR_0205", "scale_known": False, "relative": False, "size": None, "written_size": "0.3",
            "direct": True}]
    summary = hw_tolerance_summary({"step": "0.1"}, tol)
    assert summary["scale_by_block"] == {"HwTSR_0203": "known", "HwTSR_0204": "relative", "HwTSR_0205": "unknown"}
    ev = _evidence()
    ev["hw_tolerance"] = tol[:1]                                    # the sheet's cut: the chosen block's entry is gone
    ev["hw_tolerance_summary"] = {**summary, "blocks": BLOCKS + ["HwTSR_0205"], "certain": False}
    got = _verify_path({"hw_id": "HwTSR_0204", "quote": QUOTE}, ev, BLOCKS, HW, {"bat"})
    assert got["status"] == "verified" and got["scale"] == "relative"
    assert "상대 허용오차라 척도는 확인 안 됨" in path_proposal_text({"ai_path": {**got, "model": "m"}})
    hw = {**HW, "HwTSR_0205": {"name": "Battery Sub Monitor", "full_text": "Battery 감시"}}
    off = _verify_path({"hw_id": "HwTSR_0205", "quote": "Battery 감시"}, ev, ["HwTSR_0203", "HwTSR_0205"], hw, {"bat"})
    assert off["reason"] == "value_off_block_scale"


def test_a_refused_path_is_not_asked_and_the_model_sees_the_aliases():
    """(review I5) a path the HSIS refused is a document conflict; (I4) the model reads the aliases the verifier reads."""
    refused = _evidence()
    refused["hw_tolerance_summary"] = {**refused["hw_tolerance_summary"], "path_refused": {"kind": "name"}}
    assert propose_paths(_tc(refused), HW, None, ai_config=CFG, llm=_llm([]))["eligible"] == 0
    calls: list = []
    rows = [{"id": "HSI_30", "vars": ["u16g_ApiIn_Vsup"], "ids": [], "nets": ["V_BAT_MON"], "name": "V_BAT_MON"}]
    propose_paths(_tc(_evidence(signal="u16g_ApiIn_Vsup")), HW, rows, ai_config=CFG, llm=_llm([], calls))
    assert calls[0]["items"][0]["subject_aliases"] == ["V_BAT_MON"]



def test_a_korean_subject_is_compared_with_the_quotes_korean_words():
    """(review W3) '입력전원' against a mixed quote was 'not comparable' — its Korean words are: 입력전압 is no 입력전원."""
    got = _verify_path({"hw_id": "HwTSR_0204", "quote": QUOTE}, _evidence(signal="입력전원"), BLOCKS, HW, {"입력전원"})
    assert got["reason"] == "quote_does_not_name_subject"
    same = _verify_path({"hw_id": "HwTSR_0204", "quote": QUOTE}, _evidence(signal="입력전압"), BLOCKS, HW, {"입력전압"})
    assert same["status"] == "verified"


# ── review round 2 ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_korean_subject_meets_the_competitors_in_korean_and_says_what_it_could_not_compare():
    """(review r2 W1) a Korean-only subject passed the block-name and competitor checks unread ('None') and the cell
    said 'other blocks differ'."""
    hw = {"H1": {"name": "Battery Sense Monitor", "full_text": "배터리 전압을 감시한다."},
          "H2": {"name": "Hall Sensor 배터리 Monitor", "full_text": "Hall 센서 배터리 전원"}}
    ev = _evidence(signal="배터리")
    ev["hw_tolerance_summary"] = {"blocks": ["H1", "H2"], "certain": False, "scale_by_block": {"H1": "known"}}
    got = _verify_path({"hw_id": "H1", "quote": "배터리 전압을 감시한다."}, ev, ["H1", "H2"], hw, {"배터리"})
    assert got["reason"] == "subject_fits_another_block"                # H2's name shares '배터리'
    hw2 = {**hw, "H2": {"name": "Hall Sensor Monitor", "full_text": "Hall 센서 전원"}}
    ok = _verify_path({"hw_id": "H1", "quote": "배터리 전압을 감시한다."}, ev, ["H1", "H2"], hw2, {"배터리"})
    assert ok["status"] == "verified" and (ok["name_check"], ok["others_check"]) == ("not_comparable", "not_comparable")
    text = path_proposal_text({"ai_path": {**ok, "model": "m"}})
    assert "블록 이름과는 대조 불가" in text and "다른 후보 블록과는 이름 대조 불가" in text


def test_a_ratio_the_hsis_did_not_confirm_is_said():
    """(review r2 I4) known only through a monitor ratio the HSIS did not confirm is no plain 'on its scale'."""
    from generators.sts_requirement_tc import hw_tolerance_summary
    tol = [{"hw_id": "H1", "scale_known": True, "relative": False, "size": "0.3", "written_size": None, "direct": True,
            "scale": {"via": "x", "source": "own", "check": "unchecked"}}]
    assert hw_tolerance_summary({"step": "0.1"}, tol)["scale_by_block"] == {"H1": "scaled_unconfirmed"}
    got = {"status": "verified", "hw_id": "H1", "name": "N", "quote": "q", "scale": "scaled_unconfirmed",
           "name_check": "agrees", "others_check": "differ", "model": "m"}
    assert "분압식 환산 척도 위(HSIS 로 확인 안 됨)" in path_proposal_text({"ai_path": got})
