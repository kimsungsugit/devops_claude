"""R5 (P3) — quantitative requirement model (`generators/requirement_oracle.py`).

Sentences are the HDPDM01 SRS's own phrasing (the SRS text layout: ``ID<TAB>Sw..._nn`` opens a requirement).
"""
from __future__ import annotations

import pytest

from generators.requirement_oracle import extract, model


def _facts(body: str, req_id: str = "SwTR_0605"):
    text = f"ID\t{req_id}\nName\tx\n{body}\n"
    (req,) = extract(text)
    return [f for line in req["lines"] for f in line["facts"]], req


@pytest.mark.parametrize("sentence, signal, op, value, unit", [
    ("- Low 배터리 전압인가 u16g_ApiIn_Vsup: 850 미만", "u16g_ApiIn_Vsup", "<", 850, ""),
    ("- High 배터리 전압인가 u16g_ApiIn_Vsup: 1604 초과", "u16g_ApiIn_Vsup", ">", 1604, ""),
    ("Motor가 u16g_ApiIn_MotorSpeed 값이 15000 이상이 고", "u16g_ApiIn_MotorSpeed", ">=", 15000, ""),
    ("6. 차량 속도가 3km/h 이하인 상태에서 끼임 발생한 경우", "차량 속도", "<=", 3, "km/h"),
    ("- 저 전압 고장 검출 기준 전압: 8.50V 이하", "저 전압 고장 검출 기준 전압", "<=", 8.5, "V"),
    ("- MCU 입력전원이 4.23V이하로 내려가면", "MCU 입력전원", "<=", 4.23, "V"),
    ("- u16s_Tip2RunDetectCnt > 8", "u16s_Tip2RunDetectCnt", ">", 8, ""),
    ("- Stack Pointer값이 0x1FF0이상이면", "Stack Pointer값", ">=", 0x1FF0, ""),
    # a closed parenthesis belongs to the subject; a bullet does not
    ("- Load(Average)는 70% 이하.", "Load(Average)", "<=", 70, "%"),
])
def test_a_threshold_keeps_its_subject_comparison_value_and_unit(sentence, signal, op, value, unit):
    facts, _ = _facts(sentence)
    (fact,) = [f for f in facts if f["kind"] == "threshold"]
    assert (fact["signal"], fact["op"], fact["value"], fact["unit"], fact["status"]) == (signal, op, value, unit, "parsed")


def test_or_joined_values_share_the_subject_and_the_hold_time_is_a_duration():
    facts, req = _facts("- Position Sensor의 Main 전원(u16g_ApiIn_MagnetLevel)이 4.00V 이하 또는 4.74V 이상인 상태로 "
                        "특정 시간(u16s_MAGNET_ERR_TM : 100ms) 이상 유지 시", "SwTSR_0101")
    low, high = [f for f in facts if f["kind"] == "threshold"]
    assert (low["signal"], low["op"], low["value"]) == ("u16g_ApiIn_MagnetLevel", "<=", 4.0)
    assert (high["signal"], high["op"], high["value"], high.get("subject_shared")) == ("u16g_ApiIn_MagnetLevel", ">=", 4.74, True)
    (hold,) = [f for f in facts if f["kind"] == "duration"]
    assert (hold["signal"], hold["op"], hold["seconds"]) == ("u16s_MAGNET_ERR_TM", ">=", 0.1)
    assert req["lines"][0]["combination"] == "or"


def test_c_style_disjunctions_are_facts_with_an_or_combination():
    facts, req = _facts("- 오른쪽 도어: DoorPitch >= 8 || DoorRoll <= -4, 도어 Positon 50도 이상", "SwTR_0201")
    assert [(f["signal"], f["op"], f["value"]) for f in facts] == [
        ("DoorPitch", ">=", 8), ("DoorRoll", "<=", -4), ("도어 Positon", ">=", 50)]
    assert req["lines"][0]["combination"] == "or"


def test_a_symbolic_comparison_names_the_constant_it_compares_with():
    facts, _ = _facts("( u16g_ApiIn_Vsup < u16s_BATT_ERR_LOWER_LIMIT )")
    (fact,) = facts
    assert (fact["kind"], fact["signal"], fact["op"], fact["reference"]) == ("symbolic", "u16g_ApiIn_Vsup", "<",
                                                                            "u16s_BATT_ERR_LOWER_LIMIT")


def test_a_table_row_names_its_ranges():
    facts, _ = _facts("u16g_ApiIn_Vsup\t850 ~ 1,604\t8.50V ~ 16.04V", "SwTSR_0209")
    raw, physical = facts
    assert (raw["signal"], raw["value"], raw["unit"]) == ("u16g_ApiIn_Vsup", [850, 1604], "")
    assert (physical["signal"], physical["value"], physical["unit"]) == ("u16g_ApiIn_Vsup", [8.5, 16.04], "V")


def test_a_value_without_a_subject_is_partial_not_a_condition():
    facts, _ = _facts("2. 500ms 초과 저전압 상황 동작 확인")
    (fact,) = facts
    assert fact["status"] == "partial" and fact["signal"] is None and fact["reason"] == "no_subject_for_value"


def test_a_folder_path_is_not_a_requirement_condition():
    facts, _ = _facts("전사 폴더>현보>미래경영본부>연구소>선행연구팀>1000 프로젝트>1200 자동차")
    assert facts == []


def test_every_fact_points_back_to_its_text():
    text = "ID\tSwTR_0605\nName\tx\n- Low 배터리 전압인가 u16g_ApiIn_Vsup: 850 미만\n"
    (req,) = extract(text)
    (line,) = req["lines"]
    (fact,) = line["facts"]
    assert text[fact["span"][0]:fact["span"][1]] == "u16g_ApiIn_Vsup: 850 미만"
    assert len(line["sha256"]) == 64


def test_requirement_blocks_split_on_their_id_rows():
    text = "ID\tSwTR_0101\nDescription\ta 3km/h 이하\n3.3.1.2\tSwTR_0102: t\nID\tSwTR_0102\nDescription\tb 5km/h 초과\n"
    reqs = model(text)["requirements"]
    assert [r["req_id"] for r in reqs] == ["SwTR_0101", "SwTR_0102"]
    assert [r["lines"][0]["facts"][0]["value"] for r in reqs] == [3, 5]


def test_a_value_in_parentheses_after_its_parameter_is_that_parameters_threshold():
    facts, _ = _facts("3. Param_AntipinchReverseActAngle( 3도 ) 초과한 열림각에서 끼임 발생한 경우 동작 확인", "SwTR_0202")
    (fact,) = facts
    assert (fact["signal"], fact["op"], fact["value"], fact["unit"]) == ("Param_AntipinchReverseActAngle", ">", 3, "도")


def test_a_hold_time_written_as_exceeding_then_held_is_a_duration():
    facts, _ = _facts("- LIN 통신 이상으로 특정시간(300ms)초과하여 유지되는 경우", "SwTSR_0207")
    (hold,) = [f for f in facts if f["kind"] == "duration"]
    assert (hold["op"], hold["value"], hold["unit"], hold["seconds"]) == (">", 300, "ms", 0.3)


def test_a_response_time_bound_is_a_constraint_not_a_stimulus():
    facts, _ = _facts("· Application 안정화 시간 : 100ms 이내")
    (f,) = facts
    assert (f["signal"], f["kind"], f["op"], f["value"], f.get("role")) == (
        "Application 안정화 시간", "duration", "<=", 100, "response_constraint")


def test_the_number_is_kept_as_written():
    facts, _ = _facts("- Position Sensor 전원(u16g_ApiIn_MagnetLevel)이 4.00V 이하 또는 4.74V 이상")
    assert [f["value_text"] for f in facts] == ["4.00", "4.74"]
    facts, _ = _facts("- Stack Pointer값이 0x1FF0이상이면")
    assert facts[0]["value_text"] == "0x1FF0"


def test_a_negated_clause_is_marked():
    facts, _ = _facts("- 전압이 8.5V 미만이 아닌 경우 정상, u16s_B: 20 초과 시 경고")
    assert [(f["value"], bool(f.get("negated"))) for f in facts] == [(8.5, True), (20, False)]
    facts, _ = _facts("- 만약 20ms 이내에 Flag가 Set 되지 않으면 오류")
    assert facts[0].get("negated") and facts[0]["signal"] != "만약"


def test_a_subject_after_the_value_is_the_subject():
    facts, _ = _facts("- Close 방향으로 0.6m/s이상의 Door 속도가 감지되면")
    assert (facts[0]["signal"], facts[0]["signal_kind"]) == ("Door 속도", "phrase_after")


def test_a_time_value_on_a_phrase_subject_is_how_long_the_condition_lasts():
    facts, _ = _facts("- LIN 통신이 15초이상 끊길 경우 오류")
    assert (facts[0]["kind"], facts[0]["signal"], facts[0]["seconds"]) == ("duration", "LIN 통신", 15.0)


def test_a_line_is_judged_over_every_condition_on_the_subject():
    from decimal import Decimal

    from generators.requirement_oracle import line_holds
    text = "ID\tSwTSR_0101\nName\tx\n- u16g_M 이 4.00V 이하 또는 4.74V 이상\n- u16s_V 가 9V 이상 16V 이하\n"
    (req,) = extract(text)
    or_line, unstated = req["lines"]
    low, high = or_line["facts"]
    assert line_holds(Decimal("5"), low, or_line) is True           # the other condition holds
    assert line_holds(Decimal("4.5"), low, or_line) is False
    assert line_holds(Decimal("4.00"), low, or_line, ("<", Decimal("4.00"))) is False   # a mutant of 4.00 이하
    assert line_holds(Decimal("12"), unstated["facts"][0], unstated) is None           # joining not stated


def test_negations_ending_in_other_forms_are_marked():
    for text in ("- 전압이 8.5V 미만이 아닐 때 정상 동작", "- 전압이 8.5V 미만 아님 확인"):
        facts, _ = _facts(text)
        assert facts[0].get("negated"), text


def test_a_label_that_names_a_signal_gives_the_signal():
    facts, _ = _facts("- s16g_ApiIn_MotorPosition 입력: 0 이하의 값을 입력한다")
    assert (facts[0]["signal"], facts[0]["signal_kind"]) == ("s16g_ApiIn_MotorPosition", "identifier")


def test_a_noun_after_the_value_does_not_replace_an_identifier_subject():
    facts, _ = _facts("- u16g_Speed 가 3km/h 이하의 차량 속도")
    assert facts[0]["signal"] == "u16g_Speed"


@pytest.mark.parametrize("sentence", [
    # KJPDS02 SwRS SwTR_0605 [FS_REQ_MD_20]: the time phrase before ``9V`` was taken for its subject (R20)
    "도어 닫힘 작동중, 배터리 저전압(B+ < 8.6V)이 500ms 이내에 9V 이상으로 복귀할 경우 남은 작동을 수행한다.",
    "전압이 100ms 동안 9V 이상이면",
    "전원 인가 200ms 후에 5V 이상이면",
])
def test_a_quantity_or_time_phrase_before_a_value_is_not_its_subject(sentence):
    facts, _ = _facts(sentence)
    v = [f for f in facts if f["kind"] == "threshold" and f.get("unit") == "V" and f["value"] in (9, 5)]
    assert v and v[0]["signal"] is None, v                 # unnamed, not "500ms 이내에" / "100ms 동안"
    assert all(not str(f.get("signal") or "").endswith(")") for f in facts)   # nor "8.6V)"


@pytest.mark.parametrize("sentence, subject", [
    ("- 배터리 전압이 9V 이상이면", "배터리 전압"),
    ("- 후방 센서가 5V 이상이면", "후방 센서"),        # a word merely starting like a time postposition is a word
    ("- 전원이 9V 이상이면", "전원"),
    ("- 이전값이 9V 이상이면", "이전값"),
    ("- 2차 전압이 5V 이상이면", "2차 전압"),          # review W1: a leading digit alone is no quantity token
    ("- 10ms마다 전압이 5V 이상이면", "전압"),
])
def test_subject_words_that_only_look_like_quantities_or_time_words_are_kept(sentence, subject):
    facts, _ = _facts(sentence)
    assert facts[0]["signal"] == subject

