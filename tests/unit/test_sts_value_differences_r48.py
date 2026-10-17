"""R48 — requirement-document **value** differences: one threshold written with two values.

R33/R43 pair the same value written with the other inclusion (``8.5V 이하`` ↔ ``8.5V 미만``). R46 left out a value
difference (``5.14V`` in the SRS ↔ ``5.15V`` in the SyRS) — pairing two different numbers is a guess unless something
says they are one threshold. `value_differences` pairs an SRS condition value that no cited system block states with a
cited condition on the **same side** in the same unit only when (`_DIFF_TIERS`), within 5% of each other, the two name
the same subject, the values are within one written step of the coarser writing, or each side states exactly one value
in that unit and side — and hold times at any distance only as the hold times of one condition (review W1 · W2: without
the cap ``9V 이상 구동`` ↔ ``16V 초과 정지`` and ``100ms`` ↔ ``1초`` were paired). The opposite side (an entry ``미만`` and its
recovery ``이상``) is never paired; two thresholds of one quantity on one side may be (``8.5V`` ↔ ``8.9V``, 4.5% apart,
when each side writes only one), and the guidance says to check it is one threshold first (review W3, r2 I4). Shown in the 'Requirement
Review' sheet, the quality report, the generation disclosure and the gate board — never decided, never used.
"""
from __future__ import annotations

import openpyxl

from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import (
    REQUIREMENT_REVIEW_SHEET,
    append_requirement_boundary_tcs,
    if_filled,
    value_differences,
    write_requirement_review_sheet,
)


def _req(desc, related, rid="SwTR_0605", verification=""):
    return {"id": rid, "name": "n", "description": desc, "verification": verification, "asil": "B",
            "related_id": related}


def _sy(field_text, sid="SyTR_1305", field="Description", doc="SyRS"):
    return {sid: {"doc": doc, "name": "n", "fields": {field: field_text}}}


def _pairs(req, system):
    return [(d["srs"]["text"], [(o["text"], o["tiers"]) for o in d["others"]]) for d in value_differences(req, system)]


def test_same_subject_one_step_apart():
    """KJPDS02 ``SwTR_0605``: SRS ``저전압 8.6V 이하`` ↔ SyRS ``SyTR_1305`` ``저전압 8.5V 이하``."""
    req = _req("- 저전압 8.6V 이하 시 경고", "SyTR_1305")
    system = _sy("- 저전압 8.5V 이하 시 경고")
    (d,) = value_differences(req, system)
    assert (d["srs"]["subject"], d["srs"]["text"], d["side"], d["unit"], d["value"]) == \
        ("저전압", "8.6V 이하", "upper", "V", "8.6")
    (o,) = d["others"]
    assert (o["source"], o["subject"], o["text"], o["tiers"]) == \
        ("SyRS SyTR_1305 · Description", "저전압", "8.5V 이하", ["same_subject", "within_step", "only_pair"])
    assert d["subject_missing"] is False


def test_within_one_step_of_the_coarser_writing():
    """HDPDM01 ``SwTSR_0102`` ``5.14V 이상`` ↔ ``5.15V 초과``; ``SwTR_0605`` ``16.04V`` ↔ ``16.1V`` (step 0.1)."""
    assert _pairs(_req("- u16g_ApiIn_HallSnsrLevel 이 5.14V 이상 시 고장", "SyTSR_0114"),
                  _sy("- 센서 전원이 5.15V 초과 시 고장", "SyTSR_0114")) == \
        [("5.14V 이상", [("5.15V 초과", ["within_step", "only_pair"])])]
    got = _pairs(_req("- Battery 전압이 8.5V미만이거나 16.04V 이상 시 경고", "SyTR_1305"),
                 _sy("- B+ 전압 16.1V 이상 또는 고전압 16.5V 이상 시 경고"))
    assert got == [("16.04V 이상", [("16.1V 이상", ["within_step"])])]    # 16.5 is not paired: 0.46 V apart


def test_the_only_value_on_each_side_when_near():
    """The one V lower bound each side states, 3.8% apart and more than a written step: ``only_pair`` alone."""
    (d,) = value_differences(_req("- u16g_ApiIn_Vsup 가 10.2V 이상 시 경고", "SyTR_1305"), _sy("- 전원이 10.6V 이상 시 경고"))
    assert [(o["subject"], o["text"], o["tiers"]) for o in d["others"]] == [("전원", "10.6V 이상", ["only_pair"])]
    assert d["subject_missing"] is False and d["tiers"] == ["only_pair"]


def test_distant_values_are_not_one_threshold():
    """(review W1 · W2) ``SwTR_0104`` SRS ``Door 속도 0.6m/s이상`` ↔ SyDS ``SyFN_02`` ``Tip-To-Run 조건 0.8m/s 이상`` (25%
    apart — 0.6 may be Manual Assist's unwritten lower bound); one quantity's two thresholds; an integer second's step."""
    req = _req("- 0.6m/s이상의 Door 속도로 열림 시 Assist", "SyFN_02", rid="SwTR_0104")
    system = _sy("- Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하)", "SyFN_02", doc="SyDS")
    assert value_differences(req, system) == []
    assert value_differences(_req("- 배터리 전압 9V 이상 시 모터 구동", "SyTR_1305"),
                             _sy("- 배터리 전압 16V 초과 시 모터 정지")) == []
    assert value_differences(_req("- 입력 신호가 100ms 이하 시 무시", "SyTR_1305"), _sy("- 입력 신호가 1초 이하 시 무시")) == []


def test_a_hysteresis_is_not_paired():
    """``8.5V 미만`` (entry) and ``8.9V 미만`` (recovery) — other subjects, 0.4 V apart, several values: no pair."""
    req = _req("- Battery 전압 8.5V 미만 시 저전압, 9.2V 이상 시 해제", "SyTR_1305")
    system = _sy("- B+ 전압 8.9V 미만 시 진입\n- B+ 전압 8.7V 미만 500ms 유지 시 경고")
    assert value_differences(req, system) == []


def test_a_value_the_block_also_states_is_no_difference():
    """``8.5V 미만`` ↔ ``8.5V 이하`` is R33's inclusion conflict; a value stated on both sides is not a difference even
    with another near value."""
    req = _req("- 저전압 8.5V 미만 시 경고", "SyTR_1305")
    assert value_differences(req, _sy("- 저전압 8.5V 이하 또는 저전압 8.6V 이하 시 경고")) == []


def test_other_sides_units_and_roles_are_not_paired():
    req = _req("- 저전압 8.6V 이하 시 경고", "SyTR_1305")
    assert value_differences(req, _sy("- 저전압 8.5V 이상 시 해제")) == []                    # other side
    assert value_differences(req, _sy("- 저전압 8.5A 이하 시 경고")) == []                    # other unit, near value
    # a verification criteria field describes tests; an obligation is an outcome; an input range is a design domain
    assert value_differences(req, _sy("Input : 저전압 8.5V 이하 인가", field="Verification criteria")) == []
    assert value_differences(req, _sy("- 저전압은 8.5V 이하여야 한다")) == []
    assert value_differences(req, _sy("저전압(8.5V 이하), 5V", field="Input Information", doc="SyDS")) == []
    # the SRS verification text is a test, not the requirement's condition
    assert value_differences(_req("- 경고", "SyTR_1305", verification="- 저전압 8.6V 이하 입력"),
                             _sy("- 저전압 8.5V 이하 시 경고")) == []
    # an uncited block is never compared
    assert value_differences(_req("- 저전압 8.6V 이하 시 경고", "SyTR_0101"), _sy("- 저전압 8.5V 이하 시 경고")) == []


def test_units_are_compared_normalised_and_hold_times_of_one_condition_count():
    """``0.3s`` and ``300ms`` are one value (no difference). HDPDM01 ``SwTSR_0104``: ``8.50V 미만 … 500ms 이상 유지`` ↔ SyRS
    ``SyTSR_0116`` ``BAT 8.5V미만 … 300ms 이상 유지`` — the hold times of one condition, however far apart."""
    assert value_differences(_req("- 저전압 0.3s 이상 유지 시 경고", "SyTR_1305"),
                             _sy("- 저전압 300ms 이상 유지 시 경고")) == []
    got = _pairs(_req("- u16g_ApiIn_Vsup 가 8.50V 미만인 상태가 u16s_ERR_TM : 500ms 이상 유지 시 고장", "SyTSR_0116"),
                 _sy("- BAT 8.5V미만 상태가 300ms 이상 유지 시 고장", "SyTSR_0116"))
    assert got == [("500ms 이상", [("300ms 이상", ["same_condition"])])]
    # a near condition (8.60 ↔ 8.5, KJPDS02) holds one condition too; another condition does not
    assert _pairs(_req("- u16g_ApiIn_Vsup 가 8.60V 이하인 상태가 u16s_ERR_TM : 500ms 이상 유지 시 고장", "SyTSR_0116"),
                  _sy("- BAT 8.5V미만 상태가 300ms 이상 유지 시 고장", "SyTSR_0116"))[-1] == \
        ("500ms 이상", [("300ms 이상", ["same_condition"])])
    assert _pairs(_req("- u16g_ApiIn_Vsup 가 4.00V 이하인 상태가 u16s_ERR_TM : 100ms 이상 유지 시 고장", "SyTSR_0114"),
                  _sy("- 센서 전원 4.85V 미만 상태가 300ms 이상 유지 시 고장", "SyTSR_0114")) == []


def test_a_hold_time_continues_the_sentence_of_the_line_above():
    """SyRS ``SyTSR_0116`` breaks one sentence over two lines — ``… BAT 범위 8.5V미만의 BAT`` / ``전압으로 특정시간(300ms)
    이상 유지하는 경우.``: the hold time holds the condition above it. A line above that ends its sentence does not."""
    req = _req("- u16g_ApiIn_Vsup 가 8.50V 미만인 상태가 u16s_ERR_TM : 500ms 이상 유지 시 고장", "SyTSR_0116", rid="SwTSR_0104")
    broken = _sy("PDSM 의 정상동작 BAT 범위 8.5V미만의 BAT\n전압으로 특정시간(300ms) 이상 유지하는 경우.", "SyTSR_0116")
    (d,) = value_differences(req, broken)
    assert [(o["text"], o["tiers"], o["srs_is"]) for o in d["others"]] == [("300ms 이상", ["same_condition"], "larger")]
    ended = _sy("BAT 8.5V미만 시 경고한다.\n전압으로 특정시간(300ms) 이상 유지하는 경우.", "SyTSR_0116")
    assert value_differences(req, ended) == []
    apart = _sy("BAT 8.5V미만의 BAT\n\n전압으로 특정시간(300ms) 이상 유지하는 경우.", "SyTSR_0116")   # not the line right above
    assert value_differences(req, apart) == []
    # (review r2 I2) a list item starts anew: ``1) … 16.5V 초과 경고`` / ``2) 300ms 이상 유지 시 DTC 저장``
    item = _sy("1) BAT 8.5V미만의 BAT\n2) 특정시간(300ms) 이상 유지 시 DTC 저장", "SyTSR_0116")
    assert value_differences(req, item) == []


def test_the_held_conditions_of_other_names_are_flagged():
    """(review r2 I1) ``모터 전류 10A 이상 … 500ms`` ↔ ``배터리 전류 10.2A 이상 … 300ms``: one condition by value, two
    names — kept (documents name one signal differently: ``u16g_ApiIn_Vsup`` ↔ ``BAT``) and flagged in the sheet."""
    req = _req("- 모터 전류 10A 이상인 상태가 u16s_A_TM : 500ms 이상 유지 시 정지", "SyTR_1305")
    # the currents 10A ↔ 10.2A are a near pair of their own; the hold times pair through them
    (d,) = [x for x in value_differences(req, _sy("- 배터리 전류 10.2A 이상 상태가 300ms 이상 유지 시 정지")) if x["time"]]
    assert d["others"][0]["held_subjects"] == ["모터 전류", "배터리 전류"]
    wb = openpyxl.Workbook()
    write_requirement_review_sheet(wb, [{**d, "kind": "value_difference"}])
    (row,) = [r for r in wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True) if r[0] == "요구 문서 값 차이 후보"]
    assert "유지하는 조건의 주어 이름이 다름(모터 전류 ↔ 배터리 전류" in row[4]


def test_two_unnamed_values_are_not_the_same_subject():
    """HDPDM01 ``SwTSR_0202`` ``50ms 유지`` ↔ SyRS ``SyTSR_0109`` ``300ms 이상 유지`` — neither names what lasts nor what it
    holds: no pair (far apart), and near ones are never "the same subject" (no name is no sameness)."""
    assert value_differences(_req("- 50ms 이상 유지되면 고장", "SyTSR_0109", rid="SwTSR_0202"),
                             _sy("- 300ms 이상 유지 시 고장", "SyTSR_0109")) == []
    (d,) = value_differences(_req("- 290ms 이상 유지되면 고장", "SyTSR_0109", rid="SwTSR_0202"),
                             _sy("- 300ms 이상 유지 시 고장", "SyTSR_0109"))
    assert [o["tiers"] for o in d["others"]] == [["only_pair"]] and d["subject_missing"] is True
    assert d["time"] is True and d["others"][0]["srs_is"] == "smaller"


def test_a_period_is_no_hold_time():
    """(review W4) ``Pulse 주기 10ms 이하`` ↔ ``5ms 이하`` is not a hold time: no hold-time direction note."""
    (d,) = value_differences(_req("- Pulse 주기 5.2ms 이하 시 정상", "SySM_06"), _sy("- Pulse 주기 5ms 이하 시 정상", "SySM_06"))
    assert d["time"] is False
    wb = openpyxl.Workbook()
    write_requirement_review_sheet(wb, [{**d, "kind": "value_difference"}])
    (row,) = [r for r in wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True) if r[0] == "요구 문서 값 차이 후보"]
    assert "유지시간" not in row[4]


def test_a_repeated_block_sentence_is_one_counterpart_and_counterparts_are_capped():
    system = _sy("- 저전압 8.5V 이하 시 경고\n2) 저전압 8.5V 이하 시 경고")
    (d,) = value_differences(_req("- 저전압 8.6V 이하 시 경고", "SyTR_1305"), system)
    assert d["other_count"] == 1
    # (review I7) four near counterparts: three kept, nearest first, all counted
    four = _sy("- 저전압 8.5V 이하 시 경고\n- 저전압 8.52V 이하 시 알림\n- 저전압 8.55V 이하 시 기록\n- 저전압 8.58V 이하 시 표시")
    (d,) = value_differences(_req("- 저전압 8.6V 이하 시 경고", "SyTR_1305"), four)
    assert [o["text"] for o in d["others"]] == ["8.58V 이하", "8.55V 이하", "8.52V 이하"] and d["other_count"] == 4


def test_the_sheet_flags_follow_the_first_counterpart():
    """(review I2 · I7) the reason's flags: a missing subject, another name, a hold time's direction."""
    def reason(req, system):
        wb = openpyxl.Workbook()
        write_requirement_review_sheet(wb, [{**d, "kind": "value_difference"} for d in value_differences(req, system)])
        return [r[4] for r in wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True) if r[0] == "요구 문서 값 차이 후보"]
    (missing,) = reason(_req("- u16g_A 가 5.14V 이상 시 고장", "SyTSR_0114"), _sy("- 5.15V 초과 시 고장", "SyTSR_0114"))
    assert "한쪽 주어 없음" in missing and "주어 이름이 다름" not in missing
    (other,) = reason(_req("- u16g_A 가 5.14V 이상 시 고장", "SyTSR_0114"), _sy("- 센서 전원 5.15V 초과 시 고장", "SyTSR_0114"))
    assert "주어 이름이 다름" in other
    (longer,) = reason(_req("- u16g_ApiIn_Vsup 가 8.50V 미만인 상태가 u16s_ERR_TM : 500ms 이상 유지 시 고장", "SyTSR_0116"),
                       _sy("- BAT 8.5V미만 상태가 300ms 이상 유지 시 고장", "SyTSR_0116"))
    assert "같은 조건의 유지시간" in longer and "유지시간: SRS 가 더 김" in longer


def _append(requirements, system):
    tcs, out = [], []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(tcs, requirements, build, _make_tc_id, _classify_steps, system=system,
                                            review_out=out)
    return stats, out, tcs


def test_the_report_the_sheet_and_the_tcs():
    reqs = [_req("- 저전압 8.6V 이하 시 경고", "SyTR_1305"), _req("- 고전압 16.4V 이상 시 경고", "SyTR_1305", rid="SwTSR_0104")]
    system = _sy("- 저전압 8.5V 이하 시 경고\n- 고전압 16.5V 이상 시 경고")
    stats, out, tcs = _append(reqs, system)
    assert stats["value_differences"] == 2 and stats["value_difference_requirements"] == 2
    assert stats["value_difference_by_tier"] == {"same_subject": 2, "within_step": 2, "only_pair": 2}
    # safety requirements first, as the R33 conflicts
    assert [d["srs_id"] for d in stats["value_difference_items"]] == ["SwTSR_0104", "SwTR_0605"]
    rows = [r for r in out if r["kind"] == "value_difference"]
    assert len(rows) == 2 and "맞는 값으로 한쪽을 고친다" in if_filled(rows[0])
    wb = openpyxl.Workbook()
    write_requirement_review_sheet(wb, out)
    sheet = [r for r in wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True) if r[0] == "요구 문서 값 차이 후보"]
    assert len(sheet) == 2
    kind, rid, where, fact, reason, decide, filled, evidence, line, _sha, ai = sheet[0]    # (R52) + the AI column
    assert ai == "—"             # a value difference is no subject question
    assert (rid, where) == ("SwTSR_0104", "SRS ↔ SyRS SyTR_1305 · Description")
    assert fact == "고전압 16.4V 이상 ↔ 고전압 16.5V 이상"
    assert "같은 주어" in reason and "한 눈금 안" in reason and "같은 임계(한 조건)인지" in decide and evidence == "—"
    assert "다른 임계" in filled and "결함 아님" in filled                     # (review W3) not "unify one quantity"
    # the boundary TCs are what they were: each sentence is stepped as written
    assert sorted({e["value"] for tc in tcs for e in tc["requirement_evidence"]}) == ["16.4", "16.5", "8.5", "8.6"]


def test_a_failure_is_disclosed_and_costs_nothing(monkeypatch):
    import generators.sts_requirement_tc as M

    def boom(req, system):
        raise ValueError("x")
    monkeypatch.setattr(M, "value_differences", boom)
    stats, out, tcs = _append([_req("- 저전압 8.6V 이하 시 경고", "SyTR_1305")], _sy("- 저전압 8.5V 이하 시 경고"))
    assert stats["value_differences"] == 0 and stats["value_difference_error_count"] == 1
    assert stats["value_difference_errors"][0].startswith("SwTR_0605: ValueError")
    assert tcs and not [r for r in out if r["kind"] == "value_difference"]


def test_no_system_documents_no_key():
    stats, _out, _tcs = _append([_req("- 저전압 8.6V 이하 시 경고", "SyTR_1305")], None)
    assert "value_differences" not in stats


# ── web and gate ──────────────────────────────────────────────────────────────────────────────────────────────────

def _disclosure(rb):
    from report_gen.generation_disclosures import build_disclosures
    items = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"requirement_boundary": rb}})}
    return items.get("sts_requirement_value_differences")


def test_the_disclosure_states():
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "inclusion_conflicts": 0, "inclusion_blocks_compared": 2}
    assert _disclosure({"tcs": 1}) is None                                    # before R48 / no system documents
    assert _disclosure({**base, "value_differences": 0, "inclusion_blocks_compared": 0})["value"] == "—"
    zero = _disclosure({**base, "value_differences": 0})
    assert zero["value"] == "0건" and zero["tone"] != "warning"
    item = {"srs_id": "SwTR_0605", "srs": {"subject": "저전압", "text": "8.6V 이하"},
            "others": [{"source": "SyRS SyTR_1305 · Description", "subject": "저전압", "text": "8.5V 이하",
                        "tiers": ["same_subject", "within_step"]}], "other_count": 1}
    got = _disclosure({**base, "value_differences": 1, "value_difference_requirements": 1,
                       "value_difference_by_tier": {"same_subject": 1, "within_step": 1},
                       "value_difference_items": [item]})
    assert got["value"] == "1건 (요구 1)" and got["tone"] == "warning"
    assert "SwTR_0605: SRS `저전압 8.6V 이하` ↔ SyRS SyTR_1305 · Description `저전압 8.5V 이하` [같은 주어·한 눈금 안]" \
        in got["note"]
    assert "두 단계 임계" in got["note"] and "어느 값이 맞는지는 생성기가 정하지 않는다" in got["note"]
    assert got["note"].endswith("전부 STS 'Requirement Review' 시트에 있다.")
    # (review W5) a sheet that failed on its own is not where the items are
    failed = _disclosure({**base, "value_differences": 1, "value_difference_items": [item], "review_sheet_error": "boom"})
    assert "시트를 쓰지 못했다 — boom" in failed["note"] and "value_difference_items" in failed["note"]


def test_the_gate_board_carries_it_with_an_action():
    from backend.services.issue_explainer import rule_action
    from report_gen.generation_disclosures import build_disclosures
    from workflow.quality.issues import _from_generation_disclosures
    rb = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "inclusion_conflicts": 0, "inclusion_blocks_compared": 2,
          "value_differences": 1, "value_difference_requirements": 1, "value_difference_items": []}
    items = build_disclosures("sts", {"generation_stats": {"requirement_boundary": rb}})
    codes = [i["code"] for i in _from_generation_disclosures({"present": True, "items": items})]
    assert "disclosure:sts_requirement_value_differences" in codes
    action = rule_action("disclosure:sts_requirement_value_differences")
    assert "같은 임계" in action and "다른 임계" in action and "재생성으로는 사라지지 않는다" in action
