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


# ── R18 (gap ③): mutants from the reference's own thresholds, scored on both suites ───────────────────────────

def _cross(ref_rows, gen_rows, tmp_path, srs=SRS):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ref = _sts(tmp_path / "ref.xlsx", ref_rows)
    gen = _sts(tmp_path / "gen.xlsx", gen_rows)
    return ev.evaluate(srs, ref, gen)["cross_source"]


def test_reference_thresholds_become_mutants_at_their_written_step(reference):
    ref = ev.read_sts(reference)
    ms, excluded = ev.reference_mutants(ref, {"SwTR_0202": "3도 초과 …"})
    by = {(m["req_id"], m["mutant"], str(m["m_value"]), m["m_op"]) for m in ms}
    # ``3도 초과`` → ``>=3`` · ``>2`` · ``>4``; ``50도 미만`` → ``<=50`` · ``<49`` · ``<51`` (step of the written number)
    assert {("SwTR_0202", "boundary_inclusion", "3", ">="), ("SwTR_0202", "value_shift", "2", ">"),
            ("SwTR_0202", "value_shift", "4", ">"), ("SwTR_0202", "boundary_inclusion", "50", "<=")} <= by
    assert {m["raw"]: m["stated_in_srs"] for m in ms} == {"3도 초과": True, "50도 미만": False}
    assert {m["raw"]: m["srs_block_found"] for m in ms} == {"3도 초과": True, "50도 미만": True}
    assert excluded == {}


def test_widening_mutants_are_marked_unkillable():
    # R18 review W1: ``x > 3`` → ``x >= 3`` or ``x > 2`` only widens the condition — no point where the written
    # comparison holds can separate it
    assert ev._killable(">", ev.Decimal(3), ">", ev.Decimal(4)) and ev._killable(">=", ev.Decimal(3), ">", ev.Decimal(3))
    assert not ev._killable(">", ev.Decimal(3), ">=", ev.Decimal(3)) and not ev._killable(">", ev.Decimal(3), ">", ev.Decimal(2))
    assert ev._killable("<", ev.Decimal(3), "<", ev.Decimal(2)) and not ev._killable("<", ev.Decimal(3), "<=", ev.Decimal(3))


def test_a_cross_source_mutant_is_killed_only_where_the_written_comparison_holds(tmp_path):
    cs = _cross([("SwTC_1", "열림각 0.8m/s 이상 속도로 닫음", "정지", "SwTR_0203")],
                [("SwTC_9", "입력 설정 (요구 경계): 닫힘 속도 = 0.8m/s 설정", "", "SwTR_0203"),
                 ("", "입력 설정 (요구 경계): 닫힘 속도 = 0.7m/s 설정", "", "")], tmp_path)
    d = cs["generated"]
    rows = {(m["mutant"], m["m_op"], m["m_value"]): m for m in d["rows"]}
    assert rows[("boundary_inclusion", ">", 0.8)]["killed_by_point"] == 0.8   # 0.8 >= 0.8, not > 0.8
    assert rows[("value_shift", ">=", 0.9)]["killed_by_point"] == 0.8          # 0.8 >= 0.8, not >= 0.9
    assert rows[("value_shift", ">=", 0.9)]["killed_by_signal"] == "닫힘 속도"
    # 0.7 separates ``>= 0.7`` only where the written comparison does not hold: not a kill, only either-side
    assert rows[("value_shift", ">=", 0.7)]["killed_by_point"] is None and not rows[("value_shift", ">=", 0.7)]["killable"]
    assert (d["killed"], d["killed_either_side"], d["killable_mutants"], d["rate_of_killable"]) == (2, 3, 2, 1.0)
    assert (d["killed_single_subject"], d["killed_multi_subject"], d["killed_unnamed_subject"]) == (2, 0, 0)
    assert d["measurable"] and d["rate_either_side"] == 1.0
    # the reference's own row: its region *is* the threshold — only its points count (review C1)
    r = cs["reference"]
    assert r["self_sourced"] and r["killed"] == 0 and r["killed_optimistic"] is None and r["rate_optimistic"] is None
    # ... while the generated suite, scored on mutants it did not produce, keeps its optimistic rate
    assert d["killed_optimistic"] == 2 and not d["self_sourced"]


def test_the_generated_suite_is_scored_and_the_reference_is_not_credited_for_it(tmp_path):
    # review W6: a kill only the generated suite makes must show in its row and not in the reference's
    cs = _cross([("SwTC_1", "전원을 16V 이상 인가", "", "SwEI_01")],
                [("SwTC_9", "전원을 16V로 설정한다.", "", "SwEI_01")], tmp_path)
    assert cs["generated"]["killed"] == 2 and cs["reference"]["killed"] == 0
    assert cs["generated"]["stated_in_srs"] == {"mutants": 0, "killed": 0}          # ``16V`` is not in SwEI_01's text
    assert cs["generated"]["not_stated_in_srs"] == {"mutants": 3, "killed": 2}


def test_units_time_scaling_and_a_point_on_another_quantity(tmp_path):
    srs = "ID\tSwTR_0605\nName\tT\n- 저전압 300ms 이상 유지 시\n"
    cs = _cross([("SwTC_1", "저전압 300ms 이상 유지", "", "SwTR_0605")],
                [("SwTC_9", "입력 설정 (요구 경계): 저전압 지속 시간 = 0.3s 설정", "", "SwTR_0605"),
                 ("", "열림각 300도로 설정", "", "")], tmp_path, srs)
    d = cs["generated"]
    killed = {(m["m_op"], m["m_value"]) for m in d["rows"] if m["killed_by_point"] is not None}
    assert killed == {(">", 300.0), (">=", 301.0)}                      # 0.3 s is 300 ms; 300도 is no time at all
    assert all(m["points"] == [0.3] for m in d["rows"])
    assert d["stated_in_srs"] == {"mutants": 3, "killed": 2}


def test_output_judgements_and_duplicates_are_not_extra_mutants(tmp_path):
    # review W2: a threshold only in the expected-result column is an output judgement, not a stimulus boundary;
    # the same threshold written twice is one boundary; its two sides (``이상``/``미만``) are two
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "각도 50도 이상 열림", "전류 7mA 이상", "SwTR_0201"),
        ("", "각도 50도 이상 열림", "", ""),
        ("", "각도 50도 미만 열림", "", "")]))
    ms, excluded = ev.reference_mutants(ref, {})
    assert len(ms) == 6 and excluded == {"expected_result_only": 1}
    assert {m["op"] for m in ms} == {">=", "<"}


def test_a_threshold_the_srs_states_only_as_a_response_constraint_is_left_out(tmp_path):
    srs = "ID\tSwTR_0301\nName\tC\n- CPU 부하가 50% 이하로 유지되어야 한다\n- 응답은 100ms 이내\n"
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [("SwTC_1", "응답 100ms 이하 확인", "", "SwTR_0301")]))
    from generators.requirement_oracle import model
    facts = {r["req_id"]: [(f, line) for line in r["lines"] for f in line["facts"]] for r in model(srs)["requirements"]}
    assert {f.get("role") for f, _l in facts["SwTR_0301"] if f.get("value") == 100} == {"response_constraint"}
    ms, excluded = ev.reference_mutants(ref, {"SwTR_0301": srs}, facts)
    assert ms == [] and excluded == {"srs_states_it_as_output": 1}
    # without the SRS facts it would be a stimulus boundary like any other
    ms, excluded = ev.reference_mutants(ref, {"SwTR_0301": srs})
    assert len(ms) == 3 and excluded == {} and not any(m["recalled_by_extractor"] for m in ms)


def test_thresholds_are_read_with_sign_separators_and_case(tmp_path):
    # review W5: ``-4도 이하`` lost its sign, ``1,000ms`` became 0, the tail of ``0x1FF0 이상`` became ``0 이상``,
    # and ``9v 이상`` was not read at all
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "경사 -4도 이하에서 1,000ms 이상 유지, 9v 이상 인가, 값 0x1FF0 이상", "", "SwTR_0001")]))
    got = {(t["value"], t["unit"], t["op"]) for t in ref["SwTR_0001"]["thresholds"]}
    assert got == {(-4.0, "도", "<="), (1000.0, "ms", ">="), (9.0, "V", ">=")}


def test_the_report_scores_each_suite_on_the_source_it_did_not_produce(reference, tmp_path):
    gen = _sts(tmp_path / "gen.xlsx", [("SwTC_9", "전원을 16.04V로 설정한다.", "", "SwEI_01")])
    report = ev.evaluate(SRS, reference, gen)
    cs = report["cross_source"]
    assert cs["source"].startswith("reference STS thresholds") and cs["reference"]["self_sourced"]
    ms, _excluded = ev.reference_mutants(ev.read_sts(reference), {})
    assert cs["generated"]["mutants"] == cs["reference"]["mutants"] == len(ms)
    assert cs["boundaries"] == len({(m["req_id"], m["value"], m["unit"]) for m in ms})
    # the stated split comes from the SRS blocks the report reads
    assert {r["raw"]: r["stated_in_srs"] for r in cs["generated"]["rows"]} == {"3도 초과": True, "50도 미만": False}


# ── R18 review round 2 ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_number_glued_to_a_word_is_still_a_threshold_but_a_hex_tail_is_not(tmp_path):
    # W-B: ``\\w`` in the left boundary also rejected Hangul — ``열림각15도 이상`` was silently dropped
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "열림각15도 이상, 전압을9V 이상, 속도가3km/h 이하, (20도 이상), 값 0x1FF0 이상", "", "SwTR_0001")]))
    got = {(t["value"], t["unit"], t["op"]) for t in ref["SwTR_0001"]["thresholds"]}
    assert got == {(15.0, "도", ">="), (9.0, "V", ">="), (3.0, "km/h", "<="), (20.0, "도", ">=")}


def test_written_sign_separators_and_precision_reach_the_mutants(tmp_path):
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "경사 -4도 이하, 1,000ms 이상 유지, 속도 1.3m/s 이상, 속도 1.30m/s 이상", "", "SwTR_0001")]))
    ms, _excluded = ev.reference_mutants(ref, {})
    shifts = {(m["raw"].split()[0], float(m["m_value"])) for m in ms if m["mutant"] == "value_shift"}
    assert {("-4도", -5.0), ("-4도", -3.0), ("1,000ms", 999.0), ("1,000ms", 1001.0)} <= shifts
    # ``1.3`` and ``1.30`` are one boundary, moved by the finer written step (I2)
    speed = sorted(float(m["m_value"]) for m in ms if m["unit"] == "m/s" and m["mutant"] == "value_shift")
    assert speed == [1.29, 1.31]


def test_a_judgement_copied_into_the_action_cell_is_not_a_stimulus(tmp_path):
    # W-A: KJPDS02 SwNTR_0301 writes its acceptance criteria (``CPU 부하 70%이하``) in both cells of the row
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "CPU 부하 70%이하 확인", "CPU 부하 70%이하", "SwNTR_0301"),
        ("SwTC_2", "각도 15도 이상 열림", "정지", "SwTR_0201")]))
    ms, excluded = ev.reference_mutants(ref, {})
    assert {m["req_id"] for m in ms} == {"SwTR_0201"} and excluded == {"judgement_copied_to_action": 1}


def test_regions_follow_the_point_unit_rule_and_a_missing_block_is_marked(tmp_path):
    # W4 both arms: a unitless region / point is not the ``15도`` boundary; I3: no SRS block for the requirement
    cs = _cross([("SwTC_1", "각도 15도 이상 열림", "", "SwTR_0999")],
                [("SwTC_9", "각도 15 이상 열림, 각도 = 15 설정", "", "SwTR_0999")], tmp_path)
    g = cs["generated"]
    assert g["killed"] == 0 and g["killed_optimistic"] == 0 and not g["measurable"] and g["rate"] is None
    assert all(r["srs_block_found"] is False for r in g["rows"])
    cs = _cross([("SwTC_1", "각도 15도 이상 열림", "", "SwTR_0999")],
                [("SwTC_9", "각도 15도 이상 열림", "", "SwTR_0999")], tmp_path / "b")
    assert cs["generated"]["killed_optimistic"] == 3    # a region in the same unit at the same value


def test_both_sides_of_one_boundary_and_the_subject_split(tmp_path):
    # I1: ``15도 이상`` and ``15도 미만`` are one boundary, two thresholds. W-E: an unnamed point is its own category,
    # two named subjects in one unit make a kill "multi"
    cs = _cross([("SwTC_1", "각도 15도 이상 열림", "", "SwTR_0201"), ("", "각도 15도 미만 닫힘", "", "")],
                [("SwTC_9", "입력 설정 (요구 경계): 열림각 = 15도 설정", "", "SwTR_0201"),
                 ("", "입력 설정 (요구 경계): 경사각 = 30도 설정", "", "")], tmp_path)
    assert (cs["thresholds"], cs["boundaries"]) == (2, 1)
    g = cs["generated"]
    assert g["killed"] > 0 and g["killed_multi_subject"] == g["killed"] and g["killed_single_subject"] == 0
    cs = _cross([("SwTC_1", "각도 15도 이상 열림", "", "SwTR_0201")],
                [("SwTC_9", "전원 인가 후 15도로 설정", "", "SwTR_0201")], tmp_path / "u")
    assert cs["generated"]["killed"] == cs["generated"]["killed_unnamed_subject"] > 0


def test_an_unmeasured_reference_reports_no_rate(tmp_path):
    # W-D: the reference writes regions — with no point in a compatible unit its 0 is not a score
    cs = _cross([("SwTC_1", "각도 15도 이상 열림", "", "SwTR_0201")],
                [("SwTC_9", "입력 설정 (요구 경계): 열림각 = 15도 설정", "", "SwTR_0201")], tmp_path)
    r = cs["reference"]
    assert not r["measurable"] and r["rate"] is None and r["rate_of_killable"] is None and r["killed"] == 0


def test_the_report_excludes_a_threshold_the_srs_states_as_a_response_constraint(tmp_path):
    srs = "ID\tSwTR_0301\nName\tC\n- 응답은 100ms 이내\n"
    ref = _sts(tmp_path / "ref.xlsx", [("SwTC_1", "응답 100ms 이하 확인", "", "SwTR_0301")])
    report = ev.evaluate(srs, ref)
    assert report["cross_source"]["excluded"] == {"srs_states_it_as_output": 1}
    assert report["cross_source"]["reference"]["mutants"] == 0


# ── R18 review round 3 ─────────────────────────────────────────────────────────────────────────────────────────

def test_subject_groups_do_not_depend_on_the_order_of_the_points():
    # W-1: a generic name that ends two specific ones used to merge them — or not — depending on which came first
    names = ["기준 전압", "저 전압 고장 검출 기준 전압", "과 전압 고장 검출 기준 전압"]
    for order in (names, names[::-1], names[1:] + names[:1]):
        groups = ev._subject_groups([{"signal": n} for n in order])
        assert sorted(groups) == ["과 전압 고장 검출 기준 전압", "저 전압 고장 검출 기준 전압"], order
    # a spelling that ends a longer one is that one
    assert ev._subject_groups([{"signal": "Low Power mode 천이 시간"},
                               {"signal": "High -> Low Power mode 천이 시간"}]) == ["High -> Low Power mode 천이 시간"]


def test_a_copied_judgement_is_left_out_only_where_every_action_row_copies_it(tmp_path):
    # W-2: one row copies the criterion into both cells, another row stimulates it — it stays; a threshold in one
    # row's action and another row's judgement stays too
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "부하 70%이하 확인", "부하 70%이하", "SwNTR_0301"),
        ("SwTC_2", "부하 70%이하로 설정", "", ""),
        ("SwTC_3", "전압 9V 이상 인가", "", "SwTR_0605"),
        ("SwTC_4", "대기", "전압 9V 이상 유지", "")]))
    ms, excluded = ev.reference_mutants(ref, {})
    assert {m["req_id"] for m in ms} == {"SwNTR_0301", "SwTR_0605"} and len(ms) == 6 and excluded == {}


def test_units_and_numbers_the_documents_write():
    # I-e units, I-b signs in the stated check, I-1 a comma list's last element
    assert ev._stated_in("Sleep mode 암전류: 300uA 이하", 300, "uA")
    assert ev._stated_in("경사 -4도 이하", -4, "도") and not ev._stated_in("경사 -4도 이하", 4, "도")
    assert ev._stated_in("Task(5,10,50ms)", 50, "ms") and ev._stated_in("1,000ms 유지", 1000, "ms")
    got = [(m.group("num"), ev._unit(m.group("unit"))) for m in ev._COMPARATOR.finditer(
        "속도 3KM/H 이하, 전압 500mv 이상, 전류 7uA 미만")]
    assert got == [("3", "km/h"), ("500", "mV"), ("7", "uA")]


def test_a_unitless_threshold_is_left_out_and_counted(tmp_path):
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [("SwTC_1", "카운트 485 이하 확인", "", "SwTR_0001")]))
    ms, excluded = ev.reference_mutants(ref, {})
    assert ms == [] and excluded == {"no_unit": 1}


def test_the_r5_discrimination_is_not_measured_without_points(reference):
    # W-3: the reference writes regions — its R5/R6 0 is "no point", not a score
    d = ev.evaluate(SRS, reference)["discrimination"]["reference"]
    assert d["measurable"] is True   # this fixture has 7V/16V points in SwEI_01
    r = ev.discrimination([{**m, "killable": True} for m in []], {})
    assert r["measurable"] is False and r["rate"] is None

