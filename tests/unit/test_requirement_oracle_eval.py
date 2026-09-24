"""R5 (G4) — requirement oracle evaluation against an STS workbook (`scripts/requirement_oracle_eval.py`).

The gold comes from the STS, never from the extractor: a threshold the STS uses counts only when the requirement text
itself writes that quantity, and a suite discriminates a requirement mutant only with a stimulus *point*.
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import requirement_oracle_eval as ev  # noqa: E402

SRS = (
    "ID\tSwTR_0202\nName\tAnti\n"
    "3. Param_AntipinchReverseActAngle( 3도 ) 초과한 열림각에서 끼임 발생한 경우 동작 확인\n"
    "ID\tSwEI_01\nName\tBatt\n"
    "- Battery 전압이 8.5V미만이거나 16.04V 이상인 경우\n"
    "5. 차량 내부 압력에 따른 출력 보상 기능 확인\n"
)


def _sts(path: Path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "3.SW Integration Test Spec"
    ws.append(["", "Test Case"])
    ws.append(["", "Test Case ID"])
    ws.append(["", "ID"])
    for tc, action, expected, srs in rows:
        ws.append(["", tc, "", "", "", "", "", "", "d", "", action, expected, srs])
    wb.save(path)
    return str(path)


@pytest.fixture
def reference(tmp_path):
    return _sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "열림각 3도 초과 상태에서 끼임", "LIN_AntiPinchFlag = On", "SwTR_0202"),
        ("", "O_Door = 50도 미만", "정지", ""),            # 50 is not in SwTR_0202's text: not scored
        ("SwTC_2", "전원을 7V로 설정한다.", "전압 레벨: 7 ± 5%", "SwEI_01"),
        ("", "전원을 16V로 설정한다.", "전압 레벨: 16 ± 5%", ""),
        ("", "5 초 대기", "", ""),                           # "5." list number in SRS is not a 5 s threshold
    ])


def test_gold_counts_only_quantities_the_requirement_text_writes(reference):
    report = ev.evaluate(SRS, reference)
    r = report["recall"]
    assert (r["gold_items"], r["recalled"]) == (1, 1)
    assert [x["raw"] for x in r["not_stated_in_srs"]] == ["50도 미만"]
    assert report["precision"] is None  # no independent gold: never self-graded


def test_a_missing_fact_lowers_recall(reference, monkeypatch):
    import generators.requirement_oracle as ro
    real = ro._line_facts
    monkeypatch.setattr(ro, "_line_facts", lambda line, off: [] if "Param_" in line else real(line, off))
    r = ev.evaluate(SRS, reference)["recall"]
    assert (r["gold_items"], r["recalled"]) == (1, 0) and r["missing"][0]["raw"] == "3도 초과"


def test_only_points_on_the_changed_side_discriminate_a_mutant(reference):
    d = ev.evaluate(SRS, reference)["discrimination"]["reference"]
    rows = {(m["value"], m["mutant"], m["m_op"], m["m_value"]): m for m in d["rows"]}
    # 16.04 V >= : points 7 and 16 V never sit between 16.03 / 16.04 / 16.05 -> nothing killed there
    assert rows[(16.04, "boundary_inclusion", ">", 16.04)]["killed_by_point"] is None
    # 8.5 V < : no point at 8.4..8.6 either — a 7 V point is below every variant
    assert all(m["killed_by_point"] is None for m in d["rows"] if m["value"] == 8.5)
    assert d["killed"] == 0 and d["mutants"] == len(d["rows"]) > 0


def test_a_point_at_the_threshold_kills_the_inclusion_mutant(tmp_path):
    gen = _sts(tmp_path / "gen.xlsx", [("SwTC_9", "전원을 16.04V로 설정한다.", "", "SwEI_01"),
                                        ("", "전원을 16.03V로 설정한다.", "", "")])
    d = ev.evaluate(SRS, gen)["discrimination"]["reference"]
    rows = {(m["value"], m["mutant"], m["m_value"]): m for m in d["rows"]}
    killed = {k for k, m in rows.items() if m["killed_by_point"] is not None}
    assert (16.04, "boundary_inclusion", 16.04) in killed      # 16.04 >= 16.04 but not > 16.04
    assert (16.04, "value_shift", 16.05) in killed             # 16.04 >= 16.04 but not >= 16.05
    # (review r4 C-1) 16.03 separates ``>= 16.03`` only where the original does not hold — nothing is asserted there
    assert (16.04, "value_shift", 16.03) not in killed
    assert rows[(16.04, "value_shift", 16.03)]["separated_where_original_false"] == 16.03
    assert d["killed_either_side"] == d["killed"] + 1


def test_a_region_counts_only_in_the_optimistic_rate(tmp_path):
    gen = _sts(tmp_path / "gen.xlsx", [("SwTC_9", "열림각 3도 초과 상태에서 끼임", "", "SwTR_0202")])
    d = ev.evaluate(SRS, gen)["discrimination"]["reference"]
    three = [m for m in d["rows"] if m["value"] == 3]
    assert three and all(m["killed_by_point"] is None and m["boundary_region"] for m in three)
    assert d["killed"] == 0 and d["killed_optimistic"] == len(three)


def test_a_named_point_counts_only_for_its_own_signal(tmp_path):
    srs = "ID\tSwTR_0202\nName\tA\n- u16s_A: 10 초과\n- u16s_B: 10 초과\n"
    gen = _sts(tmp_path / "gen.xlsx", [("SwTC_9", "u16s_A = 11 설정", "", "SwTR_0202")])
    d = ev.evaluate(srs, gen)["discrimination"]["reference"]
    killed = {m["signal"] for m in d["rows"] if m["killed_by_point"] is not None}
    assert killed == {"u16s_A"}


def test_signal_names_match_through_leading_words_and_punctuation():
    assert ev._same_signal("High -> Low Power mode 천이 시간", "Low Power mode 천이 시간")
    assert ev._same_signal("· Application 안정화 시간", "Application 안정화 시간")
    assert not ev._same_signal("u16s_A", "u16s_B") and not ev._same_signal("", "x")


def test_a_workbook_without_the_spec_sheet_is_an_error_not_an_empty_suite(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Cover"
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(ValueError, match="no STS spec sheet"):
        ev.read_sts(str(tmp_path / "x.xlsx"))


# ── review round 2 ──────────────────────────────────────────────────────────


def test_a_generated_step_names_its_subject_by_position(tmp_path):
    # (review r2 W2) ``B+`` / ``Load(Average)`` are not identifiers: the step is read by its layout
    srs = "ID\tSwTR_0605\nName\tA\n4. B+ 8.9V 미만 사용자 작동 명령 처리 확인\n"
    gen = _sts(tmp_path / "g.xlsx", [("SwTC_9", "입력 설정 (요구 경계): B+ = 8.8V — 근거: 8.9V 미만", "", "SwTR_0605"),
                                      ("", "입력 설정 (요구 경계): B+ = 8.9V — 근거: 8.9V 미만", "", "")])
    d = ev.evaluate(srs, gen)["discrimination"]["reference"]
    # (review r4 C-1) at 8.8 V the sentence acts and ``< 8.8`` would not: killed. ``<= 8.9`` / ``< 9.0`` act *more* —
    #   they differ only at 8.9 V, where the sentence claims nothing: separated, not killed
    assert {(m["mutant"], m["m_value"]) for m in d["rows"] if m["killed_by_point"] is not None} == {("value_shift", 8.8)}
    assert d["killed_either_side"] == 3


def test_a_quoted_requirement_after_the_basis_mark_is_not_a_point(tmp_path):
    srs = "ID\tSwTR_0605\nName\tA\n- Battery 전압이 8.5V 미만\n"
    gen = _sts(tmp_path / "g.xlsx", [("SwTC_9", "확인 — 근거: 전원을 8.5V로 설정한다", "", "SwTR_0605")])
    d = ev.evaluate(srs, gen)["discrimination"]["reference"]
    assert d["killed"] == 0 and all(not m["points"] for m in d["rows"])


def test_a_time_point_in_another_unit_is_scaled(tmp_path):
    # (review r2 W3) 0.3 s against a 300ms hold time
    srs = "ID\tSwTSR_0207\nName\tA\n- LIN 통신 이상으로 특정시간(300ms)초과하여 유지되는 경우\n"
    gen = _sts(tmp_path / "g.xlsx", [("SwTC_9", "입력 설정 (요구 경계): 조건 지속 시간 = 0.3s", "", "SwTSR_0207")])
    d = ev.evaluate(srs, gen)["discrimination"]["reference"]
    # ``>= 300ms`` acts more than ``> 300ms``: the scaled 0.3 s point separates them on the side that claims nothing
    assert any(m["mutant"] == "boundary_inclusion" and m["separated_where_original_false"] == 0.3 for m in d["rows"])


def test_a_response_constraint_yields_no_mutant():
    srs = "ID\tSwNTR_0102\nName\tA\n· Application 안정화 시간 : 100ms 이내\n"
    mutants, excluded = ev.requirement_mutants(__import__("generators.requirement_oracle", fromlist=["model"])
                                               .model(srs)["requirements"])
    assert mutants == [] and excluded == {"response_constraint": 1}


def test_one_generic_word_does_not_name_a_subject():
    assert not ev._same_signal("전압", "저 전압 고장 검출 기준 전압")
    assert ev._same_signal("u16g_A", "u16g_A") and ev._same_signal("기준 전압", "저 전압 고장 검출 기준 전압")
