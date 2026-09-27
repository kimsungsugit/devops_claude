"""R33 — requirement-document inconsistency candidates: the SRS and a system block it cites state the same value in the
same unit with the other boundary inclusion (이상 ↔ 초과, 이하 ↔ 미만).

HDPDM01 ``SwTSR_0104``: SRS ``u16g_ApiIn_Vsup 8.50V 미만`` against SyDS ``SySM_04`` ``입력전원 8.5V 이하`` — at exactly
8.5 V the two documents judge differently. The generator reads both documents already; it says where they disagree
and leaves the decision to review (the boundary TCs judge each sentence as written).
"""
from __future__ import annotations

from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import (
    MAX_INCLUSION_CONFLICTS,
    append_requirement_boundary_tcs,
    inclusion_conflicts,
)
from report_gen.generation_disclosures import build_disclosures


def _req(desc, related="SySM_04", rid="SwTSR_0104"):
    return {"id": rid, "name": "n", "description": desc, "verification": "", "asil": "B", "related_id": related}


def _block(text, field="Description", doc="SyDS", **more):
    return {"doc": doc, "fields": {field: text, **more}}


def _pairs(req, system):
    return [(c["a"]["text"], c["b"]["text"], c["a"]["source"].split(" ·")[0], c["b"]["source"].split(" ·")[0])
            for c in inclusion_conflicts(req, system)]


def test_the_same_value_with_the_other_inclusion_across_documents_is_a_candidate():
    req = _req("- u16g_ApiIn_Vsup 8.50V 미만 상태가 500ms 이상 유지 시 고장")
    system = {"SySM_04": _block("입력전원 8.5V 이하 상태로 500ms 초과 유지 시 DTC")}
    got = inclusion_conflicts(req, system)
    assert [(c["a"]["text"], c["b"]["text"]) for c in got] == [("8.50V 미만", "8.5V 이하"), ("500ms 이상", "500ms 초과")]
    first = got[0]
    assert first["srs_id"] == "SwTSR_0104" and first["value"] == "8.50" and first["unit"] == "V"
    assert first["a"]["source"] == "SRS" and first["b"]["source"] == "SyDS SySM_04 · Description"
    assert first["same_subject"] is False           # u16g_ApiIn_Vsup / 입력전원 — the reviewer checks they are one signal
    assert "8.50V 미만" in first["a"]["line"]


def test_the_same_inclusion_or_another_value_or_unit_is_no_candidate():
    req = _req("- u16g_ApiIn_Vsup 8.5V 미만 시 고장")
    for text in ("입력전원 8.5V 미만 시 DTC", "입력전원 8.6V 이하 시 DTC", "입력전류 8.5A 이하 시 DTC",
                 "입력전원 8.5V 이상 시 복귀"):          # 이상 is the other side, not the other inclusion of 미만
        assert inclusion_conflicts(req, {"SySM_04": _block(text)}) == [], text


def test_a_response_time_a_negation_and_one_sources_own_fields_are_no_candidates():
    # ``500ms 이내`` is a response time (measured), not the ``500ms 미만`` condition
    assert _pairs(_req("- 저전압 500ms 미만 유지 후 복귀"), {"SySM_04": _block("500ms 이내에 복귀해야 한다")}) == []
    # a negated condition says the opposite already
    assert _pairs(_req("- 전압 8.5V 이하가 아닌 경우 정상"), {"SySM_04": _block("전압 8.5V 미만 시 DTC")}) == []
    # two fields of one block, or the SRS's description and verification, are one source
    one_block = {"SySM_04": _block("전압 8.5V 미만 시 DTC", Range="전압 8.5V 이하 시 경고")}
    assert _pairs(_req("- 모터 동작"), one_block) == []
    srs_only = {**_req("- 전압 8.5V 미만 시 고장", related=""), "verification": "전압 8.5V 이하 입력"}
    assert inclusion_conflicts(srs_only, {}) == []


def test_two_cited_blocks_can_disagree_too():
    req = _req("- 모터 동작", related="SyTSR_0116, SySM_04")
    system = {"SyTSR_0116": _block("BAT 8.5V 미만 시 정지", field="Description", doc="SyRS"),
              "SySM_04": _block("입력전원 8.5V 이하 시 DTC")}
    assert _pairs(req, system) == [("8.5V 미만", "8.5V 이하", "SyRS SyTSR_0116", "SyDS SySM_04")]


def test_a_pair_is_reported_once():
    req = _req("- 전압 8.5V 미만 시 고장\n- 다시: 전압 8.5V 미만 시 고장")
    assert len(inclusion_conflicts(req, {"SySM_04": _block("전압 8.5V 이하 시 DTC")})) == 1


def _append(reqs, system):
    def build(**kw):
        return _build_tc_dict(test_env="SwTE_01", derive_inputs=False, is_safety=False, **kw)
    return append_requirement_boundary_tcs([], reqs, build, _make_tc_id, _classify_steps, system=system)


def test_the_counts_reach_the_report_and_the_items_are_capped():
    system = {"SySM_04": _block("입력전원 8.5V 이하 시 DTC")}
    reqs = [_req("- u16g_ApiIn_Vsup 8.5V 미만 시 고장", rid=f"SwTSR_{i:04d}") for i in range(MAX_INCLUSION_CONFLICTS + 3)]
    out = _append(reqs, system)
    assert out["inclusion_conflicts"] == MAX_INCLUSION_CONFLICTS + 3
    assert len(out["inclusion_conflict_items"]) == MAX_INCLUSION_CONFLICTS
    # without system documents nothing is traced and nothing is claimed (no key — not 0)
    assert "inclusion_conflicts" not in _append(reqs[:1], None)


def _disclosure(rb):
    items = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"requirement_boundary": rb}})}
    return items.get("sts_requirement_inclusion_conflicts")


def test_the_disclosure_names_the_pairs_and_warns():
    item = {"srs_id": "SwTSR_0104", "value": "8.5", "unit": "V", "same_subject": False,
            "a": {"source": "SRS", "subject": "u16g_ApiIn_Vsup", "text": "8.50V 미만"},
            "b": {"source": "SyDS SySM_04 · Verification criteria", "subject": "입력전원", "text": "8.5V 이하"}}
    d = _disclosure({"tcs": 1, "inclusion_conflicts": 7, "inclusion_conflict_items": [item] * 7})
    assert d["value"] == "7건" and d["tone"] == "warning"
    assert "SwTSR_0104: SRS `u16g_ApiIn_Vsup 8.50V 미만` ↔ SyDS SySM_04 · Verification criteria `입력전원 8.5V 이하`" \
        in d["note"]
    assert "같은 신호인지 먼저 확인" in d["note"] and "외 2건" in d["note"]
    assert _disclosure({"tcs": 1, "inclusion_conflicts": 0, "inclusion_conflict_items": []})["value"] == "0건"
    assert _disclosure({"tcs": 1}) is None               # an output from before R33 (or no system documents)


def test_the_candidates_reach_the_review_list_with_their_own_action():
    # (R30 wiring) a warning disclosure becomes a review issue; this one is a document defect candidate, not a gap
    from backend.services.issue_explainer import rule_action
    from workflow.quality.issues import _from_generation_disclosures
    item = {"srs_id": "SwTSR_0207", "value": "300", "unit": "ms", "same_subject": False,
            "a": {"source": "SRS", "subject": "조건 지속 시간", "text": "300ms 초과"},
            "b": {"source": "SyDS SySM_07 · Verification criteria", "subject": "LIN 통신 지속 시간", "text": "300ms 이상"}}
    items = build_disclosures("sts", {"generation_stats": {"requirement_boundary": {
        "tcs": 1, "inclusion_conflicts": 1, "inclusion_conflict_items": [item]}}})
    issues = _from_generation_disclosures({"present": True, "items": items})
    codes = [i.get("code") or i.get("rule") or i.get("id") for i in issues]
    assert any("sts_requirement_inclusion_conflicts" in str(c) for c in codes), issues
    assert "재생성으로는 사라지지 않는다" in rule_action("disclosure:sts_requirement_inclusion_conflicts")


# ── review round 1 ──────────────────────────────────────────────────────────────────────────────────────────────

def test_same_subject_is_true_only_when_both_name_the_same_subject():
    # (W1/W5) the flag decides whether the disclosure asks the reviewer to check the signal
    same = inclusion_conflicts(_req("- u16g_X 8.5V 미만 시 고장"), {"SySM_04": _block("u16g_X 8.5V 이하 시 DTC")})
    assert [(c["same_subject"], c["subject_missing"]) for c in same] == [(True, False)]
    note = _disclosure({"tcs": 1, "inclusion_blocks_compared": 1, "inclusion_conflicts": 1,
                        "inclusion_conflict_items": same})["note"]
    pairs = note.split(" — SRS 와")[0]              # the pair list leads the note; the explanation follows
    assert "u16g_X" in pairs and "먼저 확인" not in pairs and "주어 없음" not in pairs
    # two different reference timers (both shown as ``조건 지속 시간`` before) are not one subject
    diff = inclusion_conflicts(_req("- 특정 시간(u16s_A_TM : 500ms) 이상 유지 시 고장"),
                               {"SySM_04": _block("u16s_B_TM : 500ms 초과 유지 시 DTC")})
    assert [c["same_subject"] for c in diff] == [False]
    assert (diff[0]["a"]["reference"], diff[0]["b"]["reference"]) == ("u16s_A_TM", "u16s_B_TM")
    # a subjectless side is said to be subjectless, not "named differently"
    none = inclusion_conflicts(_req("- 입력 8.5V 미만, 500ms 이상 유지 시 고장"),
                               {"SySM_04": _block("저전압 8.5V 이하, 500ms 초과 유지 시 DTC")})
    assert all(not c["same_subject"] for c in none)
    item = next(c for c in none if c["unit"] == "V")
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 1, "inclusion_conflicts": 1, "inclusion_conflict_items": [item]})
    assert ("한쪽 주어 없음" in d["note"]) == item["subject_missing"]
    bare = inclusion_conflicts(_req("- 8.5V 미만 시 고장"), {"SySM_04": _block("전압 8.5V 이하 시 DTC")})
    assert [c["subject_missing"] for c in bare] == [True] and bare[0]["a"]["subject"] == "주어 없음"
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 1, "inclusion_conflicts": 1, "inclusion_conflict_items": bare})
    assert "한쪽 주어 없음 — 원문으로 같은 조건인지 확인" in d["note"] and "주어 이름이 다름" not in d["note"]


def test_a_condition_pairs_only_with_a_condition_and_an_outcome_with_an_outcome():
    # (W2) an input condition and an output value of the same number are not one statement
    req = _req("- 전압 8.5V 미만 시 고장")
    for text in ("Output : 출력 전압 8.5V 이하 확인", "출력은 8.5V 이하여야 한다"):
        assert inclusion_conflicts(req, {"SySM_04": _block(text)}) == [], text
    assert inclusion_conflicts(req, {"SySM_04": _block("8.5V 이하 출력", field="Action", doc="SyRS")}) == []
    outs = inclusion_conflicts(_req("- 암전류는 0.3mA 이하여야 한다"), {"SySM_04": _block("암전류는 0.3mA 미만이어야 한다")})
    assert [(c["role"], c["a"]["text"], c["b"]["text"]) for c in outs] == [("outcome", "0.3mA 이하", "0.3mA 미만")]


def test_a_hold_time_that_writes_no_inclusion_disagrees_with_nothing():
    # (W3) ``500ms 동안 유지`` wrote no inclusion; the extractor's ``>=`` is its reading, not the document's
    assert inclusion_conflicts(_req("- 저전압 상태가 500ms 동안 유지되면 고장"),
                               {"SySM_04": _block("저전압 500ms 초과 유지 시 DTC")}) == []


def test_nothing_compared_is_no_zero_and_a_failure_costs_no_tc(monkeypatch):
    # (W4) cited IDs absent from the documents: nothing was compared — "—", not "0건 … 없다"
    out = _append([_req("- 전압 8.5V 미만 시 고장", related="SyXX_99")], {"SySM_04": _block("전압 8.5V 이하")})
    assert out["inclusion_blocks_compared"] == 0 and out["inclusion_conflicts"] == 0
    assert _disclosure(out)["value"] == "—"
    zero = _append([_req("- 전압 8.5V 미만 시 고장")], {"SySM_04": _block("전압 9V 이하")})
    assert _disclosure(zero)["value"] == "0건" and "인용한 블록 1 곳(요구 × 블록)" in _disclosure(zero)["note"]
    # (I8) an exception in the finder is recorded; the boundary TCs stay
    import generators.sts_requirement_tc as st

    def boom(*a, **k):
        raise ValueError("x")
    monkeypatch.setattr(st, "inclusion_conflicts", boom)
    tcs: list = []

    def build(**kw):
        return _build_tc_dict(test_env="SwTE_01", derive_inputs=False, is_safety=False, **kw)
    out = append_requirement_boundary_tcs(tcs, [_req("- 전압 8.5V 미만 시 고장")], build, _make_tc_id, _classify_steps,
                                          system={"SySM_04": _block("전압 8.5V 이하")})
    assert tcs and out["inclusion_conflict_errors"] and "ValueError" in out["inclusion_conflict_errors"][0]
    assert out["inclusion_conflict_error_count"] == 1
    assert _disclosure(out)["tone"] == "warning" and "비교 중 오류로 건너뛴 요구 1개" in _disclosure(out)["note"]


def test_safety_requirements_come_first_and_the_counts_say_requirements_and_values():
    # (I7) SwTSR_0104's pairs must not fall behind "외 N건"; three pairs of one value are one value
    system = {"SyTSR_0116": _block("BAT 8.5V 미만 시 정지", field="Description", doc="SyRS"),
              "SySM_04": _block("입력전원 8.5V 이하 시 DTC")}
    reqs = [_req("- 저전압 8.5V 미만 시 정지", related="SySM_04", rid="SwTR_0605"),
            _req("- u16g_ApiIn_Vsup 8.5V 이하 시 고장", related="SyTSR_0116, SySM_04", rid="SwTSR_0104")]
    out = _append(reqs, system)
    assert [c["srs_id"] for c in out["inclusion_conflict_items"]][0] == "SwTSR_0104"
    assert (out["inclusion_conflict_requirements"], out["inclusion_conflict_values"]) == (2, 2)
    assert _disclosure(out)["value"] == f"{out['inclusion_conflicts']}건 (요구 2 · 값 2)"
    # the pairs lead the note: the review list keeps its head
    assert _disclosure(out)["note"].startswith("SwTSR_0104")


def test_a_value_written_with_other_precision_is_one_pair():
    # (I1) ``8.50`` and ``8.5`` are one value: two SRS lines with them against one block make one pair per line kind
    req = _req("- u16g_X 8.50V 미만 시 고장\n- u16g_X 8.5V 미만 시 경고")
    assert len(inclusion_conflicts(req, {"SySM_04": _block("u16g_X 8.5V 이하 시 DTC")})) == 1


def test_one_value_written_two_ways_counts_once():
    # ``8.50`` and ``8.5`` of one requirement are one value in the "값 N" count
    reqs = [_req("- u16g_X 8.50V 미만 시 고장", rid="SwTSR_0104"), _req("- u16g_Y 8.5V 미만 시 경고", rid="SwTSR_0104")]
    out = _append(reqs, {"SySM_04": _block("u16g_X 8.5V 이하 시 DTC")})
    assert out["inclusion_conflicts"] == 2 and out["inclusion_conflict_values"] == 1


# ── review round 2 ──────────────────────────────────────────────────────────────────────────────────────────────

def _vc(text):
    return _block(text, field="Verification criteria")


def test_a_test_input_is_a_candidate_only_when_it_includes_a_value_the_condition_excludes():
    # (W-A) ``Input :`` is the range a test picks from. Including 8.5 where the SRS excludes it: the test expects a
    #   reaction the requirement does not give — a candidate, tagged. A stricter input only leaves 4.85 untested.
    req = _req("- u16g_X 8.5V 미만 시 고장")
    got = inclusion_conflicts(req, {"SySM_04": _vc("Input : 입력전원 8.5V 이하로 Setting\nOutput : DTC 확인")})
    assert [(c["role"], c["b"]["text"]) for c in got] == [("stimulus", "8.5V 이하")]
    assert inclusion_conflicts(_req("- u16g_X 4.85V 이하 시 고장"),
                               {"SySM_04": _vc("Input 1 : 입력 전압 4.85V 미만으로 Setting")}) == []
    # a test input and an outcome are no pair either (an output value is not a condition the input disagrees with)
    assert inclusion_conflicts(_req("- 출력은 8.5V 미만이어야 한다"), {"SySM_04": _vc("Input : 입력전원 8.5V 이하로 Setting")}) == []
    # ``Precondition :`` too; and two test inputs never make a candidate
    assert inclusion_conflicts(_req("- 전원 9V 초과 시 동작"), {"SySM_04": _vc("Precondition : 전원 9V 이상 인가")})
    assert inclusion_conflicts(_req("- 모터 동작", related="SyA_01, SyB_01"),
                               {"SyA_01": _vc("Input : 전원 9V 이상"), "SyB_01": _vc("Input : 전원 9V 초과")}) == []
    # an SRS ``<Pre Condition>`` heading in the description is the requirement's own condition, not a test input
    pre = inclusion_conflicts(_req("<Pre Condition>\n전원 9V 이상 인가\n<Action>\n동작"),
                              {"SySM_04": _block("전원 9V 초과 시 동작", field="Description", doc="SyRS")})
    assert [c["role"] for c in pre] == ["condition"]


def test_the_disclosure_tags_the_roles_and_shows_the_reference_constant():
    items = [
        {"srs_id": "SwTSR_0104", "value": "8.5", "unit": "V", "role": "stimulus", "same_subject": False,
         "subject_missing": False, "a": {"source": "SRS", "subject": "u16g_X", "text": "8.5V 미만"},
         "b": {"source": "SyDS SySM_04 · Verification criteria", "subject": "입력전원", "text": "8.5V 이하"}},
        {"srs_id": "SwTSR_0104", "value": "0.3", "unit": "mA", "role": "outcome", "same_subject": True,
         "subject_missing": False, "a": {"source": "SRS", "subject": "암전류", "text": "0.3mA 이하"},
         "b": {"source": "SyDS SySM_04 · Description", "subject": "암전류", "text": "0.3mA 미만"}},
        {"srs_id": "SwTSR_0104", "value": "500", "unit": "ms", "role": "condition", "same_subject": False,
         "subject_missing": True, "a": {"source": "SRS", "subject": "조건 지속 시간", "text": "500ms 이상",
                                        "reference": "u16s_Diag_LowBattErrTm"},
         "b": {"source": "SyRS SyTSR_0116 · Description", "subject": "주어 없음", "text": "500ms 초과"}}]
    note = _disclosure({"tcs": 1, "inclusion_blocks_compared": 2, "inclusion_conflicts": 3,
                        "inclusion_conflict_items": items})["note"]
    assert "SwTSR_0104 [시험 입력]: SRS `u16g_X 8.5V 미만`" in note and "SwTSR_0104 [결과]: SRS `암전류 0.3mA 이하`" in note
    assert "`조건 지속 시간 500ms 이상 (기준 u16s_Diag_LowBattErrTm)`" in note
    assert "범위: 인용 블록 2 곳(요구 × 블록)" in note


def test_a_c_style_comparison_and_the_reference_only_for_a_constant():
    # ``u16g_X < 850`` writes its inclusion with ``<``; an identifier subject carries no reference constant
    got = inclusion_conflicts(_req("- u16g_X < 850 이면 고장"), {"SySM_04": _block("u16g_X 850 이하 시 DTC")})
    assert [(c["a"]["text"], c["b"]["text"]) for c in got] == [("850 미만", "850 이하")]
    assert got[0]["a"]["reference"] is None and got[0]["b"]["reference"] is None
    timer = inclusion_conflicts(_req("- 특정 시간(u16s_A_TM : 500ms) 이상 유지 시 고장"),
                                {"SySM_04": _block("저전압 500ms 초과 유지 시 DTC")})
    assert timer[0]["a"]["subject"] == "조건 지속 시간" and timer[0]["a"]["reference"] == "u16s_A_TM"


def test_errors_are_counted_in_full_and_an_unmeasured_run_with_errors_warns():
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 0, "inclusion_conflicts": 0,
                     "inclusion_conflict_errors": ["SwTR_0001: ValueError: x"], "inclusion_conflict_error_count": 7})
    assert d["value"] == "—" and d["tone"] == "warning" and "건너뛴 요구 7개" in d["note"]
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 3, "inclusion_conflicts": 0,
                     "inclusion_conflict_errors": ["SwTR_0001: ValueError: x"], "inclusion_conflict_error_count": 7})
    assert d["value"] == "0건 · 오류 7"


# ── review round 3 ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_stricter_precondition_is_no_candidate():
    assert inclusion_conflicts(_req("- 전원 9V 이상 시 동작"), {"SySM_04": _vc("Precondition : 전원 9V 초과 인가")}) == []


def test_the_srs_verification_text_is_a_test_description_too():
    # (W-1/W-2) the SRS's verification criteria are read as test inputs: a labelled input that includes the value is a
    #   candidate; an unlabelled numbered test item that is stricter is not (it only leaves the value untested)
    labelled = {**_req("- 모터 동작"), "verification": "Input : 입력전원 8.5V 이하"}
    got = inclusion_conflicts(labelled, {"SySM_04": _block("전원 8.5V 미만 시 DTC")})
    assert [(c["role"], c["a"]["source"]) for c in got] == [("stimulus", "SRS")]
    numbered = {**_req("- 모터 동작", related="SyTR_0703"), "verification": "2. 500ms 초과 저전압 상황 동작 확인"}
    assert inclusion_conflicts(numbered, {"SyTR_0703": _block("저전압 500ms 이상 유지되면 정지", doc="SyRS")}) == []


def test_errors_show_next_to_the_pairs_too():
    item = {"srs_id": "SwTSR_0104", "value": "8.5", "unit": "V", "role": "condition", "same_subject": True,
            "subject_missing": False, "a": {"source": "SRS", "subject": "u16g_X", "text": "8.5V 미만"},
            "b": {"source": "SyDS SySM_04 · Description", "subject": "u16g_X", "text": "8.5V 이하"}}
    d = _disclosure({"tcs": 1, "inclusion_blocks_compared": 2, "inclusion_conflicts": 1, "inclusion_conflict_items": [item],
                     "inclusion_conflict_requirements": 1, "inclusion_conflict_values": 1,
                     "inclusion_conflict_errors": ["SwTR_0001: ValueError: x"], "inclusion_conflict_error_count": 3})
    assert d["value"] == "1건 (요구 1 · 값 1) · 오류 3" and "건너뛴 요구 3개" in d["note"].split(" — SRS 와")[0]


def test_a_condition_pair_and_a_test_input_pair_of_the_same_sources_are_both_reported():
    # the role is part of what a pair is: the block's condition and its test input against one SRS condition
    system = {"SySM_04": _block("u16g_X 8.5V 이하 시 DTC", **{"Verification criteria": "Input : u16g_X 8.5V 이하"})}
    got = inclusion_conflicts(_req("- u16g_X 8.5V 미만 시 고장"), system)
    assert sorted(c["role"] for c in got) == ["condition", "stimulus"]
