"""R43 — boundary-inclusion conflict candidates within one source (the SRS text, or one system block).

R33 compared the SRS with the blocks it cites (and two blocks) but skipped two lines of one source. HDPDM01
``SwTSR_0104``'s own text states the low-battery threshold twice with the other inclusion — ``저 전압 고장 검출 기준
전압: 8.50V 이하`` and ``8.50V 미만인 전압으로 특정 시간 … 이상 유지하는 경우`` — and SyRS ``SyTSR_0109`` writes one
``300ms`` hold as 초과 / 이상 / 초과 in its items 1·2·3. Such pairs are candidates now, marked ``within_source``: two
lines of one document may also be two conditions or two actions on purpose, so the disclosure asks to read both.
"""
from __future__ import annotations

from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import append_requirement_boundary_tcs, inclusion_conflicts
from report_gen.generation_disclosures import build_disclosures


def _req(desc, related="", rid="SwTSR_0104", verification=""):
    return {"id": rid, "name": "n", "description": desc, "verification": verification, "asil": "B",
            "related_id": related}


def _block(text, field="Description", doc="SyRS", **more):
    return {"doc": doc, "fields": {field: text, **more}}


def test_two_lines_of_the_srs_text_with_the_other_inclusion_are_a_candidate():
    req = _req("저 전압 고장 검출 기준 전압: 8.50V 이하\n"
               "- PDSM 의 정상동작 BAT(u16g_ApiIn_Vsup) 범위인 8.50V 미만인 전압으로 특정 시간 이상 유지하는 경우")
    got = inclusion_conflicts(req, {})
    assert [(c["a"]["text"], c["b"]["text"], c["within_source"]) for c in got] == [("8.50V 이하", "8.50V 미만", True)]
    assert got[0]["a"]["source"] == got[0]["b"]["source"] == "SRS"


def test_items_of_one_block_are_a_candidate_and_one_finding_per_pair_of_inclusions():
    block = _block("1. Pulse 미감지 상태로 특정시간(300ms) 초과 유지되는 경우\n"
                   "2. Pulse Speed 초과 상태로 특정시간(300ms) 이상 유지되는 경우\n"
                   "3. 방향이 반대인 상태로 특정시간(300ms) 초과 유지되는 경우")
    got = inclusion_conflicts(_req("- 모터 정지", related="SyTSR_0109", rid="SwTSR_0202"), {"SyTSR_0109": block})
    # 1↔2 and 2↔3 are one finding: the same value, the same block, 초과 against 이상
    assert [(c["value"], c["unit"], c["within_source"]) for c in got] == [("300", "ms", True)]
    assert got[0]["a"]["source"].startswith("SyRS SyTSR_0109")


def test_one_line_is_never_paired_with_itself():
    # a single line naming both inclusions (a range written with both ends at one value) is one statement, not a pair
    assert inclusion_conflicts(_req("- 전압 8.5V 이하 또는 8.5V 미만 구간 판정"), {}) == []


def test_pairs_across_sources_are_not_within_source():
    got = inclusion_conflicts(_req("- u16g_ApiIn_Vsup 8.50V 미만 시 고장", related="SySM_04"),
                              {"SySM_04": _block("입력전원 8.5V 이하 시 DTC", doc="SyDS")})
    assert [c["within_source"] for c in got] == [False]


def test_the_same_inclusion_within_one_source_is_no_candidate():
    assert inclusion_conflicts(_req("- 전압 8.5V 미만 시 고장\n- 다시: 전압 8.5V 미만 시 DTC"), {}) == []


def _append(reqs, system):
    def build(**kw):
        return _build_tc_dict(test_env="SwTE_01", derive_inputs=False, is_safety=False, **kw)
    return append_requirement_boundary_tcs([], reqs, build, _make_tc_id, _classify_steps, system=system)


def test_the_report_counts_the_within_source_candidates_apart():
    within = _req("저 전압 기준: 8.50V 이하\n- 8.50V 미만인 전압으로 유지하는 경우", related="SySM_04")
    across = _req("- u16g_X 9.0V 미만 시 고장", related="SySM_04", rid="SwTSR_0105")
    out = _append([within, across], {"SySM_04": _block("u16g_X 9.0V 이하 시 DTC", doc="SyDS")})
    assert out["inclusion_conflicts"] == 2 and out["inclusion_conflicts_within_source"] == 1


def _disclosure(rb):
    items = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"requirement_boundary": rb}})}
    return items.get("sts_requirement_inclusion_conflicts")


def test_the_disclosure_marks_a_within_source_pair_and_counts_them():
    item = {"srs_id": "SwTSR_0104", "value": "8.50", "unit": "V", "same_subject": False, "subject_missing": False,
            "within_source": True,
            "a": {"source": "SRS", "subject": "저 전압 고장 검출 기준 전압", "text": "8.50V 이하"},
            "b": {"source": "SRS", "subject": "u16g_ApiIn_Vsup", "text": "8.50V 미만"}}
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 1, "inclusion_conflicts": 1,
                     "inclusion_conflicts_within_source": 1, "inclusion_conflict_items": [item]})
    assert d["value"] == "1건 · 그중 한 출처 안 1"
    pairs = d["note"].split(" — SRS 와")[0]
    assert "한 출처 안의 두 줄 — 다른 조건·다른 동작일 수 있으니 원문 확인" in pairs
    assert "같은 신호인지 먼저 확인" in pairs            # the subject flag still follows
    # a pair across sources carries no within-source mark
    across = {**item, "within_source": False, "b": {**item["b"], "source": "SyDS SySM_04 · Description"}}
    d2 = _disclosure({"tcs": 1, "inclusion_blocks_compared": 1, "inclusion_conflicts": 1,
                      "inclusion_conflicts_within_source": 0, "inclusion_conflict_items": [across]})
    assert d2["value"] == "1건" and "한 출처 안의 두 줄" not in d2["note"].split(" — SRS 와")[0]


# ── review round 1 ──────────────────────────────────────────────────────────────────────────────

def _within_item(**more):
    return {"srs_id": "SwTSR_0104", "value": "8.50", "unit": "V", "same_subject": False, "subject_missing": True,
            "within_source": True, "a": {"source": "SRS", "subject": "주어 없음", "text": "8.50V 이하"},
            "b": {"source": "SRS", "subject": "주어 없음", "text": "8.50V 미만"}, **more}


def test_candidates_found_without_a_cited_block_are_shown_not_called_unmeasured():
    # (C1) no cited block was compared, but one source's own lines disagree: "unmeasured" would hide them
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 0, "inclusion_conflicts": 1,
                     "inclusion_conflicts_within_source": 1, "inclusion_conflict_items": [_within_item()]})
    assert d["value"] == "1건 · 그중 한 출처 안 1" and d["tone"] == "warning"
    assert "문서 간 비교는 미측정" in d["note"] and "SwTSR_0104" in d["note"]
    # nothing compared and nothing found stays "—" (unmeasured, not 0)
    assert _disclosure({"tcs": 1, "inclusion_blocks_compared": 0, "inclusion_conflicts": 0,
                        "inclusion_conflicts_within_source": 0, "inclusion_conflict_items": []})["value"] == "—"


def test_an_output_from_before_r43_keeps_the_r33_scope():
    # (W1) the disclosure is rebuilt from a stored payload: an R33~R42 output never looked within one source
    old = {"srs_id": "SwTSR_0104", "value": "8.5", "unit": "V", "same_subject": False,
           "a": {"source": "SRS", "subject": "u16g_X", "text": "8.5V 미만"},
           "b": {"source": "SyDS SySM_04 · Description", "subject": "입력전원", "text": "8.5V 이하"}}
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 3, "inclusion_conflicts": 1, "inclusion_conflict_items": [old]})
    assert "한 출처(SRS 원문 또는 한 블록) 안의 쌍은 보지 않는다" in d["note"] and "서로 다른 두 줄" not in d["note"]
    zero = _disclosure({"tcs": 1, "inclusion_blocks_compared": 3, "inclusion_conflicts": 0, "inclusion_conflict_items": []})
    assert "안의 쌍은 보지 않는다" in zero["note"]
    new_zero = _disclosure({"tcs": 1, "inclusion_blocks_compared": 3, "inclusion_conflicts": 0,
                            "inclusion_conflicts_within_source": 0, "inclusion_conflict_items": []})
    assert "두 줄 사이에서" in new_zero["note"] and "보지 않는다" not in new_zero["note"]


def test_a_requirements_pairs_across_documents_are_listed_before_its_own_lines():
    # (W2) the disclosure shows five: within one requirement the cross-document pairs come first
    req = _req("저 전압 기준: 8.50V 이하\n- u16g_X 8.50V 미만인 전압으로 유지하는 경우", related="SySM_04")
    out = _append([req], {"SySM_04": _block("u16g_X 8.5V 이하 시 DTC", doc="SyDS")})
    assert [c["within_source"] for c in out["inclusion_conflict_items"]] == [False, True]


def test_a_blocks_own_pair_counts_once_however_many_requirements_cite_it():
    # (W3) the defect is in one block: three citing requirements do not make three findings
    block = _block("1. A 상태로 특정시간(300ms) 초과 유지되는 경우\n2. B 상태로 특정시간(300ms) 이상 유지되는 경우")
    reqs = [_req("- 모터 정지", related="SyTSR_0109", rid=f"SwTSR_020{i}") for i in range(3)]
    out = _append(reqs, {"SyTSR_0109": block})
    assert out["inclusion_conflicts"] == 1 and out["inclusion_conflicts_within_source"] == 1


def test_a_same_subject_pair_within_one_source_still_carries_the_mark():
    # (W5 M7) a warning at 이하 and a DTC at 미만 of one signal may be two actions on purpose
    item = _within_item(same_subject=True, subject_missing=False,
                        a={"source": "SRS", "subject": "u16g_V", "text": "8.5V 이하"},
                        b={"source": "SRS", "subject": "u16g_V", "text": "8.5V 미만"})
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 1, "inclusion_conflicts": 1,
                     "inclusion_conflicts_within_source": 1, "inclusion_conflict_items": [item]})
    assert "한 출처 안의 두 줄" in d["note"].split(" — SRS 와")[0]


def test_a_within_pair_and_a_cross_pair_of_one_value_are_two_findings():
    # (W5 M11) SwTSR_0104: the SRS's own 이하/미만 and the SRS 미만 against the block's 이하 are different findings
    req = _req("저 전압 기준: 8.50V 이하\n- u16g_X 8.50V 미만인 전압으로 유지하는 경우", related="SySM_04")
    got = inclusion_conflicts(req, {"SySM_04": _block("u16g_X 8.5V 이하 시 DTC", doc="SyDS")})
    assert sorted(c["within_source"] for c in got) == [False, True]


def test_two_blocks_of_one_document_are_two_sources():
    # (W5 M10) one source is one block, not one document kind
    req = _req("- 모터 정지", related="SyTSR_0116, SyTSR_0117")
    got = inclusion_conflicts(req, {"SyTSR_0116": _block("BAT 8.5V 미만 시 정지"),
                                    "SyTSR_0117": _block("BAT 8.5V 이하 시 정지")})
    assert [c["within_source"] for c in got] == [False]


def test_a_pair_naming_one_subject_wins_the_shared_key():
    # (I2) ``A 8.5V 이하 / B 8.5V 미만 / A 8.5V 미만``: the A↔A pair is the finding, not the first-seen A↔B
    got = inclusion_conflicts(_req("- u16g_A 8.5V 이하 시 경고\n- u16g_B 8.5V 미만 시 차단\n- u16g_A 8.5V 미만 시 DTC"), {})
    assert len(got) == 1 and got[0]["same_subject"] is True and got[0]["subject_missing"] is False
    assert (got[0]["a"]["subject"], got[0]["b"]["subject"]) == ("u16g_A", "u16g_A")   # (round 2 W2) the shown pair too


def test_one_sentence_numbered_two_ways_is_not_a_pair():
    # (I3) ``1) X`` in the description and ``- X`` in the verification are one sentence
    req = _req("1) 전압 8.5V 이하 또는 8.5V 미만 구간 판정", verification="- 전압 8.5V 이하 또는 8.5V 미만 구간 판정")
    assert inclusion_conflicts(req, {}) == []


# ── review round 2 ──────────────────────────────────────────────────────────────────────────────

def test_the_srs_own_pairs_of_two_requirements_are_two_findings():
    # (W1) only a block's own pair is counted once across requirements — each requirement's SRS text is its own
    reqs = [_req("저 전압 기준: 8.5V 이하\n- 8.5V 미만인 전압으로 유지하는 경우", related="SySM_04", rid=f"SwTSR_010{i}")
            for i in range(2)]
    out = _append(reqs, {"SySM_04": _block("모터 동작", doc="SyDS")})
    assert (out["inclusion_conflicts"], out["inclusion_conflicts_within_source"]) == (2, 2)


def test_two_values_of_one_block_are_two_findings():
    # (W1) the once-per-block key holds the value
    block = _block("1. A 8.5V 초과 시 경고\n2. B 8.5V 이상 시 정지\n3. C 9.0V 초과 시 경고\n4. D 9.0V 이상 시 정지")
    out = _append([_req("- 모터", related="SyTSR_0109", rid="SwTSR_0201"),
                   _req("- 모터", related="SyTSR_0109", rid="SwTSR_0202")], {"SyTSR_0109": block})
    assert (out["inclusion_conflicts"], out["inclusion_conflicts_within_source"]) == (2, 2)


def test_the_same_pair_in_two_blocks_is_two_findings():
    # (W1) the once-per-block key holds the block
    one = "1. A 상태로 특정시간(300ms) 초과 유지\n2. B 상태로 특정시간(300ms) 이상 유지"
    out = _append([_req("- 모터", related="SyTSR_0109, SyTSR_0117", rid="SwTSR_0201")],
                  {"SyTSR_0109": _block(one), "SyTSR_0117": _block(one)})
    assert out["inclusion_conflicts_within_source"] == 2


def test_a_blocks_own_pair_stays_with_the_safety_requirement_that_cites_it():
    # (round 2 W3) counted once — under the first requirement of the SORTED list: the safety requirement comes first
    block = _block("1. A 상태로 특정시간(300ms) 초과 유지\n2. B 상태로 특정시간(300ms) 이상 유지")
    out = _append([_req("- 모터", related="SySM_09", rid="SwTR_0101"),
                   _req("- 모터", related="SySM_09", rid="SwTSR_0999")], {"SySM_09": block})
    assert out["inclusion_conflicts"] == 1 and out["inclusion_conflict_items"][0]["srs_id"] == "SwTSR_0999"
