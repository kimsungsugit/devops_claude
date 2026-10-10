"""R57 — requirement oracle defects the AI fact review found (HDPDM01 · KJPDS02_PV, both).

`scripts/requirement_fact_ai_review.py` asked an LLM whether each extracted fact is what its sentence states and
checked the answers against the sentence. Its disagreements held four parser defects:
* a table line ``- [u16g_X]<TAB>-0x000~0x1FE: 0~510KPH`` gave the physical range the raw range as its subject,
* ``Verification criteria<TAB><Sleep Mode 진입 확인1>`` was read as ``criteria < Sleep``,
* ``N 동안`` before a condition ending in its clause (``15초 동안 … 비활성화 된 경우`` · ``200ms 동안 … 넘어설 때``)
  was read as ``== N`` — no order comparison, so the STS dropped these timers without a word,
* ``0 ~ 2.4 mm/s`` lost its unit.
Review round 1 narrowed each fix (an angle title only where a title starts, the held condition stops at its clause, a
negated held condition stays negated, a number label looks back for the identifier).
"""
from __future__ import annotations

import pytest

from generators.requirement_oracle import extract


def _facts(body: str, req_id: str = "SwTR_0605"):
    text = f"ID\t{req_id}\nName\tx\n{body}\n"
    (req,) = extract(text)
    return [f for line in req["lines"] for f in line["facts"]]


@pytest.mark.parametrize("line, signal, value, unit", [
    ("- [u16g_ApiIn_LinRx_VehicleSpeed]\t-0x000~0x1FE: 0~510KPH", "u16g_ApiIn_LinRx_VehicleSpeed", [0, 510], "KPH"),
    ("- [s16g_ApiIn_LinRx_LongAcceleration]\t-0x0000~0xFFFE: -4.1768~4.1765", "s16g_ApiIn_LinRx_LongAcceleration",
     [-4.1768, 4.1765], ""),
    ("- [s16g_ApiIn_LinRx_X]\t-12: 0~5V", "s16g_ApiIn_LinRx_X", [0, 5], "V"),          # a plain number label too
])
def test_a_number_range_before_a_colon_is_not_the_subject_the_identifier_before_it_is(line, signal, value, unit):
    facts = _facts(line, "SwEI_02")
    physical = facts[-1]
    assert (physical["signal"], physical["value"], physical["unit"]) == (signal, value, unit)
    assert all(f["signal"] == signal for f in facts if f["kind"] == "range")


def test_a_system_line_without_a_table_row_takes_the_identifier_or_no_subject():
    """(review W4) ``8) Vehicle Speed - [u16g_X]<TAB>-0x000~0x1FE: 0~510KPH`` — a SyDS line has no table row; a
    value-only ``Range`` cell names nothing: no subject (the review asks) instead of the raw range."""
    facts = _facts("8) Vehicle Speed - [u16g_ApiIn_LinRx_VehicleSpeed]\t-0x000~0x1FE: 0~510KPH", "SwEI_02")
    assert facts[-1]["signal"] == "u16g_ApiIn_LinRx_VehicleSpeed"
    facts = _facts("Range\t-0x000~0x1FE: 0~510KPH", "SwEI_02")
    assert facts[-1]["signal"] is None and facts[-1]["status"] == "partial"


def test_a_colon_fact_after_a_hex_number_names_no_hex_tail():
    """(review W4) ``-0x000~0x1FE: 510KPH 이하`` read ``x1FE`` as the subject — now the identifier before it."""
    facts = _facts("- [u16g_ApiIn_LinRx_VehicleSpeed]\t-0x000~0x1FE: 510KPH 이하", "SwEI_02")
    assert all("x1FE" not in str(f.get("signal")) for f in facts)
    assert facts[-1]["signal"] == "u16g_ApiIn_LinRx_VehicleSpeed" and facts[-1]["value"] == 510


def test_a_word_label_before_a_colon_still_names_the_value():
    """The label rule stays for words: ``저 전압 고장 검출 기준 전압: 8.50V 이하`` · ``Sensor Range: 0~5V``."""
    (f,) = _facts("- 저 전압 고장 검출 기준 전압: 8.50V 이하")
    assert (f["signal"], f["signal_kind"]) == ("저 전압 고장 검출 기준 전압", "reference_label")
    (r,) = _facts("- Sensor Range: 0~5V")
    assert (r["signal"], r["signal_kind"], r["value"]) == ("Sensor Range", "label", [0, 5])


@pytest.mark.parametrize("line", [
    "Verification criteria\t<Sleep Mode 진입 확인1>",
    "Verification criteria\t<Output 확인>",
    "Input\t<완료조건 Door Close>",
    "<Output>\t- a_x > 3",          # a title at the line's start; the comparison after it stays (checked below)
])
def test_an_angle_bracket_title_is_no_comparison(line):
    facts = _facts(line, "SwTR_0107")
    assert all(f["signal"] != "criteria" and f.get("reference") not in ("Sleep", "Output") for f in facts)
    assert facts == [] or [(f["signal"], f["op"]) for f in facts] == [("a_x", ">")]


def test_c_comparisons_around_angle_brackets_stay_comparisons():
    """(review W1) ``u16g_Vsup<850 이면 Low, u16g_Vsup>1604 이면 High`` is two comparisons, not a title."""
    facts = _facts("- u16g_Vsup<850 이면 Low, u16g_Vsup>1604 이면 High")
    assert [(f["signal"], f["op"], f["value"]) for f in facts] == [("u16g_Vsup", "<", 850), ("u16g_Vsup", ">", 1604)]
    facts = _facts("- 조건: a_x <b_y 이고 c_z> d_w")
    assert [(f["signal"], f["op"]) for f in facts] == [("a_x", "<"), ("c_z", ">")]


@pytest.mark.parametrize("line, op, value", [
    ("- u8t_i<u8s_NTC_LAST_INDEX", "<", "u8s_NTC_LAST_INDEX"),           # no space: still a comparison
    ("- (a_cnt <b_max) && (c_cnt> d_min)", "<", "b_max"),                 # an operator inside: no title
    ("- u16s_X < 0x10", "<", 16),
])
def test_a_c_comparison_stays_a_comparison(line, op, value):
    f = _facts(line)[0]
    assert f["op"] == op and (f.get("reference") or f.get("value")) == value


@pytest.mark.parametrize("line, value, unit", [
    ("- 15초 동안 LIN 통신이 비활성화 된 경우에 Sleep mode 로 천이한다.", 15, "초"),
    ("- Door가 Auto Close중 200ms 동안 Motor current level이 u16s_LIMIT이상 넘어설 때 Fail 판단.", 200, "ms"),
    ("- 2초 동안 입력이 유지되면 동작한다", 2, "초"),
    ("- 15초 동안 비활성화시 Sleep 진입", 15, "초"),
    ("- 2초 동안 입력이 없을 시 경고", 2, "초"),
    ("- 3초 동안 신호가 끊어지면 Fail", 3, "초"),
    ("- 200ms 동안 과전류 발생시 정지", 200, "ms"),
])
def test_a_time_a_condition_lasts_is_at_least_that_long(line, value, unit):
    (d,) = [f for f in _facts(line, "SwTSR_0209") if f["kind"] == "duration"]
    assert (d["op"], d["value"], d["unit"], d["status"]) == (">=", value, unit, "parsed")


def test_a_negated_held_condition_is_a_review_item_not_a_silent_drop():
    """``300ms동안 수신되지 않으면`` — ordered now (it was ``==`` and the STS dropped it without a word); the negation
    stays, so the STS asks to write it without one (``미수신 300ms``) instead of stepping a time with no predicate
    (review W3)."""
    (d,) = [f for f in _facts("- LIN Message가 300ms동안 수신되지 않으면 LIN 통신 Fail로 처리하도록 함.", "SwTSR_0209")
            if f["kind"] == "duration"]
    assert d["op"] == ">=" and d.get("negated") is True and "holds_clause" not in d


@pytest.mark.parametrize("line", [
    "- CPU Load 측정 시간 / 측정 횟수: 10분 동안 / 총 3회",              # a measuring period
    "- 측정 10분 동안. 이상이 있는 경우 보고",                            # the ending is in the next sentence
    "- Motor를 5초 동안 구동하고, 전류가 10A 이상이면 정지",              # an output's time before the condition (W2)
    "- 9V 미만이면 5초 동안 부저를 울리고, 복귀하면 정지",
    "- 5초 동안 부저를 울리고 복귀하면 정지",
    "- 5초 동안 LED를 점등한다(단, IGN ON인 경우 제외)",
    "- 5초 동안 화면 표시",                                               # nouns ``화면`` · ``표시`` are no endings
    "- 동작 중 5초 동안 부저를 울린다",
    "- 5초 동안 하면서 확인",                                              # ``면서`` is no condition
    "- 5초 경과 후 문이 열린 경우",                                         # ``경과``: not a ``동안`` time
])
def test_a_time_with_no_condition_in_its_clause_stays_unordered(line):
    (d,) = [f for f in _facts(line, "SwTSR_0209") if f["kind"] == "duration"]
    assert d["op"] == "==", line


def test_a_negated_hold_time_is_still_negated():
    """``300ms 이상 유지되지 않으면`` — the time itself is what the sentence denies (unchanged)."""
    (d,) = [f for f in _facts("- 입력이 300ms 이상 유지되지 않으면 무시", "SwTSR_0209") if f["kind"] == "duration"]
    assert d["op"] == ">=" and d.get("negated") is True


def test_mm_per_second_is_a_unit():
    _raw, physical = _facts("u16g_ApiIn_MotorSpeed\t0 ~ 60000\t0 ~ 2.4 mm/s", "SwTSR_0209")
    assert (physical["value"], physical["unit"]) == ([0, 2.4], "mm/s")
    (t,) = _facts("- 도어 속도가 1.3m/s 초과")
    assert t["unit"] == "m/s"


def test_a_negated_sibling_is_held_as_its_complement():
    """(review W3) ``전압이 9V 이상이 아닌 상태로 5초 이상 유지되는 경우``: stepping the time, the other condition must be
    held the other way round — it said "[전압 9V 이상]: 성립 상태로 둔다", the opposite precondition."""
    from collections import Counter

    from generators.sts_requirement_tc import boundary_steps
    desc = "- 전압이 9V 이상이 아닌 상태로 5초 이상 유지되는 경우 Fail로 판단한다."
    (group,) = boundary_steps({"id": "SwTR_0605", "description": desc, "verification": ""}, Counter(), None, [])
    assert group["evidence"]["combination_note"] == "다른 조건 [전압 9V 이상 (원문이 부정)]: 불성립 상태로 둔다"


def _notes(desc):
    from collections import Counter

    from generators.sts_requirement_tc import boundary_steps
    groups = boundary_steps({"id": "SwTR_0605", "description": desc, "verification": ""}, Counter(), None, [])
    return {g["evidence"]["signal"]: g["evidence"].get("combination_note") for g in groups}


def test_a_negated_sibling_in_an_or_line_is_held_true():
    """``…이 아닌 경우 또는 온도가 50도 이상``: to see the temperature alone, the negated voltage clause must be false —
    the voltage comparison holds."""
    notes = _notes("- 전압이 9V 이상이 아닌 경우 또는 온도가 50도 이상인 경우 Fail로 판단한다.")
    assert notes["온도"] == "다른 조건 [전압 9V 이상 (원문이 부정)]: 성립 상태로 둔다"


def test_a_negation_on_the_predicate_is_not_flipped():
    """(review r2 W1) ``300ms동안 수신되지 않고``: the negation belongs to 수신 — the non-reception must last, so
    "불성립" would be backwards; the words do not settle it, the note says so."""
    notes = _notes("- LIN Message가 300ms동안 수신되지 않고 전압이 9V 이상인 경우 Fail로 판단한다.")
    assert notes["전압"].startswith("다른 조건 [조건 지속 시간 300ms 와 같음 (원문이 부정)]: 부정의 범위 확인 필요")


def test_an_unstated_join_stays_unstated_and_a_mixed_group_asks():
    notes = _notes("- 전압이 9V 이상이 아니거나 온도가 50도 이상인 경우 Fail로 판단한다.")
    assert notes["온도"] == "다른 조건 [전압 9V 이상]: 결합이 원문에 명시되지 않음 — 결합 조건 확인 필요"
    notes = _notes("- 전압이 9V 이상이 아니고 전압이 16V 이하인 상태로 5초 이상 유지되는 경우 Fail로 판단한다.")
    assert "결합 조건 확인 필요" in notes["조건 지속 시간"] and "불성립 상태로 둔다" not in notes["조건 지속 시간"]
