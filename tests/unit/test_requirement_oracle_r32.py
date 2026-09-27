"""R32 (G4(b)) — requirement extractor: the noun a parenthesis qualifies, a subject particle written apart, and which
condition a hold time qualifies.

R29 left most traced system facts without a subject (HDPDM01 70 · KJPDS02_PV 69) — ``저전압(8.5V 이하, 500ms 초과)``,
``Manual Assist조건(0.8m/s 미만)``: the value opens a parenthesis and the clause inside names nothing. And `joint` joined a
hold time with any condition of the line by *and*, so a named subject made a step assert another condition's hold time.
"""
from __future__ import annotations

import pytest

from generators.requirement_oracle import extract, joint
from generators.sts_requirement_tc import boundary_steps


def _facts(text):
    lines = [line for b in extract(f"ID\tSwTR_0001\n{text}\n") for line in b["lines"] if line["facts"]]
    return lines[0] if lines else {"facts": []}


def _subjects(text):
    return [(f["kind"], f.get("signal"), f.get("signal_kind"), f["op"], f["value"]) for f in _facts(text)["facts"]]


@pytest.mark.parametrize("text, expected", [
    ("모터 동작상태에서 저전압(8.5V 이하, 500ms 초과) 및 고전압 (16.5V 이상 500ms 초과) 발생 시 정지한다",
     [("threshold", "저전압", "paren_owner", "<=", 8.5), ("duration", "저전압", "paren_owner", ">", 500),
      ("threshold", "고전압", "paren_owner", ">=", 16.5), ("duration", "고전압", "paren_owner", ">", 500)]),
    ("감지하여 Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하) 인지를 판단한다",
     [("threshold", "Manual Assist조건", "paren_owner", "<", 0.8),
      ("threshold", "Tip-To-Run 조건", "paren_owner", ">=", 0.8),
      ("threshold", "Tip-To-Run 조건", "paren_owner", "<=", 1.3)]),
    ("Input 3 : 차속 입력(10km/h 이상) , Motor 연결 해제", [("threshold", "차속 입력", "paren_owner", ">=", 10)]),
    # a particle ends the owner — ``이상의`` before ``속도``, ``동작상태에서`` before ``저전압`` (above)
    ("도어의 속도를 모니터 하여 정상속도 이상의 속도(1.3m/s 초과) 로 구동될 경우 정지",
     [("threshold", "속도", "paren_owner", ">", 1.3)]),
    # ``이상인 경우(`` names nothing: no subject is invented
    ("일정 속도 이상인 경우(1.3m/s 초과) Motor Short Brake 를 통해 정지", [("threshold", None, "", ">", 1.3)]),
    # a verb form before the parenthesis names no quantity (``감소한(`` — the speed that fell is not "감소한")
    ("도어 속도가 감소한(0.5m/s 미만) 경우 정지", [("threshold", None, "", "<", 0.5)]),
    # a later clause inside the parenthesis is not owned by the noun before it: ``Close(수동 조작, 0.8m/s 이상 빠르기)``
    ("3. Open(수동)-> 1초 대기 -> Close(수동 조작, 0.8m/s 이상 빠르기)", [("threshold", None, "", ">=", 0.8)]),
    # a subject particle written apart; an object particle is not a subject marker
    ("LDF에 따라 스케줄링 된 LIN Signal 이 300ms 이상 수신되지 않는 경우",
     [("duration", "LIN Signal", "phrase", ">=", 300)]),
    ("Input : 주기적으로 Watchdog Input 을 10ms 이상 Disable", [("threshold", None, "", ">=", 10)]),
    ("Battery 전압 은 9V 이상", [("threshold", "Battery 전압", "phrase", ">=", 9)]),
    # only the particle right before the value is skipped: ``설정 은`` is not part of the subject
    ("설정 은 전압 이 9V 이상", [("threshold", "전압", "phrase", ">=", 9)]),
    ("설정 은 전압 9V 이상", [("threshold", "전압", "phrase", ">=", 9)]),      # (r2 W6) a particle after a word stays
    # (review W3) not an owner: a when-clause, a range, a requirement ID, a time postposition
    ("도어 속도 감소시(0.5m/s 미만) 정지", [("threshold", None, "", "<", 0.5)]),
    ("도어 속도가 기준 이상일때(1.3m/s 초과) 정지", [("threshold", None, "", ">", 1.3)]),
    ("PWM Signal : 0~5V(65535 이하)", [("range", "PWM Signal", "label", "in_range", [0, 5]),
                                       ("threshold", None, "", "<=", 65535)]),
    ("참조 SwTR_0102(3도 이하)", [("threshold", None, "", "<=", 3)]),
    ("IGN ON 이후(9V 이상) 동작", [("threshold", None, "", ">=", 9)]),
    # (review W3) a time in a parenthesis after a state name is not the state's hold time — it may be the result
    ("CAN 미수신 시 Sleep 모드(15초 이상) 진입", [("threshold", None, "", ">=", 15)]),
    # the owner window is two words, a word with a parenthesis / a number / no letter ends it
    ("Close 동작 시 모터 과전류 조건(10A 이상)", [("threshold", "과전류 조건", "paren_owner", ">=", 10)]),
    ("CPU Load(Avg) 조건(70% 이하)", [("threshold", "조건", "paren_owner", "<=", 70)]),
    ("공급 9V 전원(16V 이하)", [("threshold", "전원", "paren_owner", "<=", 16)]),
    ("B1 전원(16V 이하)", [("threshold", "B1 전원", "paren_owner", "<=", 16)]),
    ("- 전원(16V 이하)", [("threshold", "전원", "paren_owner", "<=", 16)]),
])
def test_the_subject_a_value_compares(text, expected):
    assert _subjects(text) == expected


def test_a_table_rows_signal_wins_and_the_owner_stays_in_its_cell():
    # (review W2) ``split()`` crossed the tab and pulled the row's signal into the owner; the row's signal is the subject
    assert _subjects("u16g_ApiIn_Vsup\t저전압(8.5V 이하)") == [("threshold", "u16g_ApiIn_Vsup", "table_row", "<=", 8.5)]
    assert _subjects("B+ 전압\t정상(9V 이상)") == [("threshold", "정상", "paren_owner", ">=", 9)]


def test_a_parenthesis_that_names_its_own_subject_keeps_it():
    # ``Load(Average)는 70% 이하`` — the parenthesis closed before the value: the clause names it as before
    assert _subjects("CPU Load(Average)는 70% 이하") == [("threshold", "CPU Load(Average)", "phrase", "<=", 70)]


def _pair(text, a, b):
    line = _facts(text)
    facts = line["facts"]
    return joint(line, facts[a], facts[b])


def test_a_named_hold_time_qualifies_its_own_subject_only():
    text = "모터 동작상태에서 저전압(8.5V 이하, 500ms 초과) 및 고전압 (16.5V 이상 500ms 초과) 발생 시 정지한다"
    assert _pair(text, 0, 1) == "and"          # 저전압 and its 500ms
    assert _pair(text, 2, 3) == "and"          # 고전압 and its 500ms
    assert _pair(text, 0, 3) == "unstated"     # 고전압's 500ms says nothing of 저전압 (was "and")
    assert _pair(text, 1, 2) == "unstated"


def test_an_unnamed_hold_time_in_a_parenthesis_with_conditions_qualifies_those_only():
    # KJPDS02_PV SwTR_0605 (the R29 residual): the 250ms belongs to the normal range, not to ``B+ 전압 8.9V 미만``
    text = "B+ 전압이 8.9V 미만일 경우 작동을 제한하며 B+ 전압이 정상범위(9V~16V 250ms 유지)로 진입시 복귀한다"
    line = _facts(text)
    below, rng, hold = (next(f for f in line["facts"] if f["kind"] == k) for k in ("threshold", "range", "duration"))
    assert joint(line, hold, rng) == "and"
    assert joint(line, hold, below) != "and"


@pytest.mark.parametrize("text", [
    # (review W1) the same residual, written without the parenthesis / with the time alone in one / nested / after a
    #   sentence end with no space — the 250ms (500ms) never qualifies ``8.9V 미만``
    "B+ 전압이 8.9V 미만일 경우 작동을 제한하며, 9V 이상 250ms 유지 시 복귀한다",
    "B+ 전압이 8.9V 미만일 경우 제한하며 B+ 전압 9V~16V(250ms 유지)로 진입시 복귀한다",
    "B+ 전압이 8.9V 미만일 경우 제한하며 정상범위(9V~16V (250ms 유지))로 진입시 복귀한다",
    "B+ 전압이 8.9V 미만인 상태를 제한한다.이후 9V 이상 500ms 동안 유지되면 복귀",
    "B+ 전압 8.9V 미만을 감지하며 9V 이상 250ms 유지 시 복귀한다",          # ``…며`` ends the clause
    "B+ 전압 8.9V 미만, 9V 이상 250ms 유지 시 복귀한다",                    # a comma ends it
    # the parenthesis around the hold time holds a condition: it bounds the hold time even without a clause end
    "전압 A 8.9V 미만 상태(전압 B 9V 이상 250ms 유지)에서 동작",
    # ... also when the time sits in an inner parenthesis of its own
    "전압 A 8.9V 미만 상태(전압 B 9V 이상 (250ms 유지))에서 동작",
    # (review r2 W6) every clause end counts: 시 · 면 · 경우 · 때 · a sentence end
    "B+ 전압 8.9V 미만 감지 시 9V 이상 250ms 유지 후 복귀",
    "B+ 전압이 8.9V 미만이면 제한하고 9V 이상 250ms 유지 후 복귀",
    "B+ 전압 8.9V 미만인 경우 제한하고 9V 이상 250ms 유지 후 복귀",
    "B+ 전압 8.9V 미만일 때 제한하고 9V 이상 250ms 유지 후 복귀",
    "B+ 전압 8.9V 미만을 제한한다. 9V 이상 250ms 유지 후 복귀",
    # (review r2 W5) an unmatched ``)`` of a list number does not erase the clause end before it; full-width commas and
    #   parentheses are clause ends and parentheses too; ``…함.`` ends a sentence
    "B+ 전압이 8.9V 미만일 경우 제한하며 2) 9V 이상 250ms 유지 시 복귀",
    "B+ 전압 8.9V 미만，9V 이상 250ms 유지 시 복귀",
    "B+ 전압이 8.9V 미만일 경우 제한하며 정상범위（9V~16V 250ms 유지）로 진입시 복귀",
    "전압 A 8.9V 미만 상태（전압 B 9V 이상 250ms 유지）에서 동작",      # only the full-width parenthesis separates
    "B+ 전압 8.9V 미만을 제한함.이후 9V 이상 250ms 유지 시 복귀",
    # (review r2 W6) the innermost parenthesis holding a condition bounds the time, not an outer one
    "상태(B+ 전압 8.9V 미만, 정상범위(9V~16V 250ms 유지))",
    # (review r3 W1) inside the bounding parenthesis its own clauses still split; so does a closed inner one
    "상태(B+ 전압 8.9V 미만, 9V 이상 250ms 유지)",
    "A(B(8.9V 미만), 9V 이상 250ms 유지)",
    # (review r3 W3) a clause end after an unmatched ``)`` is still a clause end
    "B+ 전압이 8.9V 미만 2) 조건일 경우 9V 이상 250ms 유지 시 복귀",
])


def test_an_unnamed_hold_time_qualifies_its_own_clause_only(text):
    line = _facts(text)
    below = next(f for f in line["facts"] if f["kind"] == "threshold" and f["value"] == 8.9)
    hold = next(f for f in line["facts"] if f["kind"] == "duration")
    other = next(f for f in line["facts"] if f is not below and f is not hold)
    assert joint(line, hold, below) != "and" and joint(line, hold, other) == "and"


def test_a_closed_parenthesis_between_them_does_not_end_the_clause():
    # (review r3 W3) ``(단, 시동 제외)`` is an aside: its comma is not the clause's
    line = _facts("B+ 전압 9V 이상 (단, 시동 제외) 250ms 유지 시 복귀")
    hold = next(f for f in line["facts"] if f["kind"] == "duration")
    volt = next(f for f in line["facts"] if f["kind"] == "threshold")
    assert joint(line, hold, volt) == "and"


def test_a_hold_time_before_its_condition_is_bounded_by_the_clause_too():
    # (review r2 W6) the other direction: the time comes first
    text = "500ms 동안 유지되면, 전압 9V 이상에서 복귀"
    line = _facts(text)
    hold = next(f for f in line["facts"] if f["kind"] == "duration")
    volt = next(f for f in line["facts"] if f["kind"] == "threshold")
    assert joint(line, hold, volt) != "and"


def test_a_comma_inside_the_conditions_own_parenthesis_does_not_end_its_clause():
    text = "배터리 저전압(u16g_Vsup < 850, 시동조건 제외)이 500ms 초과하여 유지될 경우 작동을 중지"
    line = _facts(text)
    cond = next(f for f in line["facts"] if f["kind"] != "duration")
    hold = next(f for f in line["facts"] if f["kind"] == "duration")
    assert joint(line, hold, cond) == "and"


def test_an_unnamed_hold_time_alone_in_its_parenthesis_qualifies_the_condition_before_it():
    text = "Main 전원(u16g_ApiIn_MagnetLevel)이 4.00V 이하 또는 4.74V 이상인 상태로 특정 시간(u16s_TM : 100ms) 이상 유지 시"
    line = _facts(text)
    hold = next(f for f in line["facts"] if f["kind"] == "duration")
    assert {joint(line, hold, f) for f in line["facts"] if f is not hold} == {"and"}


def test_a_hold_time_in_another_sentence_qualifies_nothing_here():
    text = "B+ 전압이 9V 이상이면 동작한다. 이후 500ms 동안 유지되면 완료로 본다"
    line = _facts(text)
    volt = next(f for f in line["facts"] if f["kind"] == "threshold")
    hold = next(f for f in line["facts"] if f["kind"] == "duration")
    assert joint(line, hold, volt) != "and"


def test_parenthesis_labels_over_one_unit_are_not_stepped():
    # (review C1) Manual Assist조건 / Tip-To-Run 조건 name one door speed: a step on one said 불성립 at 0.8 m/s, where the
    #   line judges Tip-To-Run — neither is stepped (their hold times of different conditions are unaffected)
    from collections import Counter
    stats = Counter()
    req = {"id": "SwTR_0102", "name": "n", "asil": "B", "verification": "",
           "description": "- Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하) 인지를 판단한다"}
    assert boundary_steps(req, stats) == []
    # the two labels joined by 또는; ``1.3m/s 이하`` joins ``0.8m/s 이상`` of its own label without a connective
    assert stats["skipped:parenthesis_labels_may_share_a_quantity"] == 2
    assert stats["skipped:same_subject_combination_unstated"] == 1
    one = {**req, "description": "- 도어 속도가 Tip-To-Run 조건(0.8m/s 이상) 인지를 판단한다"}
    assert [g["evidence"]["signal"] for g in boundary_steps(one)] == ["Tip-To-Run 조건"]


@pytest.mark.parametrize("desc, stepped", [
    # (review r2 W2) a range as the other label's value, and a plain subject joined to a label: both sides are held back
    ("- Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8~1.3m/s) 인지를 판단한다", []),
    ("- 도어 속도가 0.8m/s 미만이거나 Tip-To-Run 조건(0.8m/s 이상) 인지를 판단한다", []),
    # two labels over different units are two quantities; a label and another quantity of the unit with no stated
    #   join stay (the note says the join is to be checked)
    ("- 과전류 조건(10A 이상) 이고 차속 입력(10km/h 이상) 이면 정지한다", ["과전류 조건", "차속 입력"]),
    ("- 저전압(8.5V 이하) 및 고전압(16.5V 이상) 발생 시 정지한다", ["저전압", "고전압"]),
    # a hold time of a label is never held back by another quantity's threshold of its unit
    ("- 저전압(8.5V 이하, 500ms 초과) 또는 u16s_Timer: 100ms 이상 이면 정지한다", ["저전압", "저전압 지속 시간", "u16s_Timer"]),
    # (review r3 W3) an *and* is a stated join too; a unit-less value names no quantity to share; a negated condition
    #   and an output obligation are no condition to share with
    ("- 과전류 조건(10A 이상) 이고 모터 전류 12A 이하 이면 정지한다", []),
    ("- 모드A(3 이상) 또는 모드B(3 미만) 이면 전환한다", ["모드A", "모드B"]),
    ("- Tip-To-Run 조건(0.8m/s 이상) 또는 도어 속도가 0.5m/s 미만이 아닌 경우 판단한다", ["Tip-To-Run 조건"]),
    ("- Tip-To-Run 조건(0.8m/s 이상) 또는 도어 속도는 1.5m/s 이하여야 한다", ["Tip-To-Run 조건"]),
])
def test_which_parenthesis_labels_are_held_back(desc, stepped):
    req = {"id": "SwTR_0102", "name": "n", "asil": "B", "verification": "", "description": desc}
    assert sorted(g["evidence"]["signal"] for g in boundary_steps(req)) == sorted(stepped)


def test_the_skip_reason_reads_in_korean_on_the_disclosure():
    # (review r2 W3 · r3 I4) a key without a label reached the screen as English
    from report_gen.generation_disclosures import build_disclosures
    qr = {"generation_stats": {"requirement_boundary": {
        "tcs": 1, "steps": 3, "facts_used": 1, "facts": 3, "skipped:parenthesis_labels_may_share_a_quantity": 2}}}
    note = {i["key"]: i for i in build_disclosures("sts", qr)}["sts_requirement_boundary"]["note"]
    assert "괄호 앞 이름이 같은 단위의 다른 조건과 결합(한 양일 수 있음) 2" in note
    assert "parenthesis_labels" not in note


def test_the_evidence_sheet_marks_a_parenthesis_label_subject():
    import openpyxl

    from generators.sts_requirement_tc import write_requirement_evidence_sheet
    req = {"id": "SwTR_0102", "name": "n", "asil": "B", "verification": "",
           "description": "- 도어 속도가 Tip-To-Run 조건(0.8m/s 이상) 인지를 판단한다"}
    (g,) = boundary_steps(req)
    wb = openpyxl.Workbook()
    assert write_requirement_evidence_sheet(wb, [{"id": "SwTC_1", "requirement_evidence": [g["evidence"]]}]) == 1
    ws = wb["Requirement Evidence"]
    assert ws.cell(2, 4).value == "Tip-To-Run 조건 (괄호 앞 명사)"


def test_the_step_holds_only_the_conditions_the_line_joins_to_it():
    req = {"id": "SwTR_0605", "name": "n", "asil": "B", "verification": "",
           "description": "- 모터 동작상태에서 저전압(8.5V 이하, 500ms 초과) 및 고전압 (16.5V 이상 500ms 초과) 발생 시 정지한다"}
    groups = boundary_steps(req)
    # ``및`` is no stated join: the two labels stay, and the notes say to check how they combine (review r2 W2)
    assert [g["evidence"]["kind"] for g in groups] == ["threshold", "duration", "threshold", "duration"]
    low = next(g["evidence"]["combination_note"] for g in groups
               if g["evidence"]["signal"] == "저전압" and g["evidence"]["kind"] == "threshold")
    assert "[저전압 지속 시간 500ms 초과]: 성립 상태로 둔다" in low
    assert "[고전압 16.5V 이상]: 결합이 원문에 명시되지 않음" in low
    assert "[고전압 지속 시간 500ms 초과]: 결합이 원문에 명시되지 않음" in low     # was "성립 상태로 둔다"
