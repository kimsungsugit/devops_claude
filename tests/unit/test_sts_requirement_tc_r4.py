"""R5/R6 review round 4 — the evaluator counts only what a step asserts; subject-less facts share nothing; joins with a
neighbouring line (a particle, a lone connective) and with a non-numeric condition are written; more negations;
connectives are never subjects; the two texts of a requirement are read apart; raw values stay inside the width the
subject's name declares; a cut quote says so; a failure of the default-on addition is disclosed."""
from __future__ import annotations

from collections import Counter

from generators.requirement_oracle import extract, line_holds, same_subject
from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import append_requirement_boundary_tcs, boundary_steps
from report_gen.generation_disclosures import build_disclosures


def _req(desc, rid="SwTR_0202", verification=""):
    return {"id": rid, "name": "n", "description": desc, "verification": verification, "asil": "B"}


def _build(**kw):
    return _build_tc_dict(test_env="SwTE_01", is_safety=False, derive_inputs=False, **kw)


def _lines(text):
    (req,) = extract("ID\tSwTR_0202\nName\tx\n" + text + "\n")
    return req["lines"]


def test_two_unnamed_hold_times_are_not_one_subject():
    """(C-2) ``… 100ms 이상 유지 그리고 … 300ms 이상 유지``: 101 ms holds the first — it is not ANDed with the second."""
    (line,) = _lines("- u16s_T 가 100ms 이상 유지 그리고 u16s_Q 가 300ms 이상 유지 시 고장")
    durations = [f for f in line["facts"] if f["kind"] == "duration"]
    assert len(durations) == 2 and not same_subject(durations[0], durations[1])
    first = min(durations, key=lambda f: f["value"])
    assert line_holds(101, first, line) is True


def test_a_line_starting_with_a_particle_goes_on_from_the_previous_line():
    """(W-1, SwTSR_0202) the hold time of ``가 50ms 유지되면`` qualifies the previous line's conditions."""
    lines = _lines("- (u16s_A > 10U) && (u16s_B > 5U)\n가 50ms 유지되면 고장")
    assert lines[0]["continues"] == "and" and lines[0]["next_text"] == "가 50ms 유지되면 고장"
    assert lines[1]["joins_previous"] == "and" and lines[1]["previous_text"] == "- (u16s_A > 10U) && (u16s_B > 5U)"
    tcs = []
    append_requirement_boundary_tcs(tcs, [_req("- (u16s_A > 10U) && (u16s_B > 5U)\n가 50ms 유지되면 고장")], _build,
                                    _make_tc_id, _classify_steps)
    hold = next(tc for tc in tcs if "지속 시간" in tc["steps"][0]["action"])
    assert "앞 줄 조건 [- (u16s_A > 10U) && (u16s_B > 5U)]과 AND 결합(원문): 성립 상태로 둔다" in hold["precondition"]


def test_a_connective_alone_on_its_line_joins_the_lines_around_it():
    lines = _lines("- u16s_A: 10 초과\nOR\n- u16s_B: 5 초과")
    assert (lines[0]["continues"], lines[0]["next_text"]) == ("or", "- u16s_B: 5 초과")
    assert (lines[1]["joins_previous"], lines[1]["previous_text"]) == ("or", "- u16s_A: 10 초과")
    lines = _lines("- u16s_A: 10 초과\n- u16s_B: 5 초과")
    assert lines[0]["continues"] == "" and lines[1]["joins_previous"] == ""


def test_a_non_numeric_condition_on_the_line_is_held_as_the_words_join_it():
    """(W-1, SwTR_0104) ``15000 이상이고 MotorDirection 이 Close`` — the second condition is not a fact."""
    (g,) = boundary_steps(_req("- u16g_MotorSpeed: 15000 이상이고 u8g_DrvIn_MotorDirection 이 Close"))
    assert g["evidence"]["combination_note"] == "같은 줄의 다른 조건(원문): 성립 상태로 둔다"
    (g,) = boundary_steps(_req("- u16g_MotorSpeed: 15000 이상 설정"))
    assert g["evidence"]["combination_note"] == ""


def test_not_satisfied_and_out_of_range_turn_the_condition_around():
    """(W-2) ``8.5V 이상을 만족하지 못하면`` is a low-voltage condition — not stepped as ``≥ 8.5``."""
    for text in ("- Battery 전압이 8.5V 이상을 만족하지 못하면 저전압 고장", "- Battery 전압이 8.5V 이상을 벗어나면 저전압 고장"):
        stats = Counter()
        assert boundary_steps(_req(text), stats) == [] and stats["skipped:negated_condition"] == 1, text


def test_a_connective_is_never_a_subject():
    """(W-3) ``8V 미만 OR 16V 초과`` without a subject: nothing is set to "OR = 17V"."""
    for text in ("- 8V 미만 OR 16V 초과 시 고장", "- 8V 미만 or 16V 초과 시 고장", "- 16V 이상이 아니거나 8V 미만 시 고장"):
        (line,) = _lines(text)
        subjects = {f.get("signal") for f in line["facts"]}
        assert not subjects & {"OR", "or", "아니거나", "아니"}, (text, subjects)


def test_the_description_and_the_verification_criteria_are_read_apart():
    """(W-4) an ``<Output>`` heading ending the description does not make the criteria an outcome."""
    stats = Counter()
    groups = boundary_steps(_req("- 동작 설명\n<Output>\n- 모터 정지", verification="- u16s_C: 30 초과"), stats)
    assert [g["evidence"]["signal"] for g in groups] == ["u16s_C"] and not stats.get("skipped:outcome_section")


def test_a_raw_value_stays_inside_the_width_the_name_declares():
    """(I-2) ``u8g_X 45000 이상`` cannot be stimulated; ``u16g_X 0 초과`` has no −1."""
    stats = Counter()
    assert boundary_steps(_req("- u8g_ApiIn_MotorCountSpeed: 45000 이상"), stats) == []
    assert stats["skipped:value_outside_subject_type"] == 1
    stats = Counter()
    (g,) = boundary_steps(_req("- u16g_X: 0 초과"), stats)
    assert [p["point"] for p in g["evidence"]["points"]] == ["0", "1"] and stats["points_outside_subject_type"] == 1
    (g,) = boundary_steps(_req("- Battery 전압이 0.5V 초과"))   # a unit: the name gives no raw width
    assert len(g["evidence"]["points"]) == 3


def test_a_cut_quote_says_so():
    long = "- u16s_A: 10 초과 " + "가" * 200
    (g,) = boundary_steps(_req(long))
    assert g["steps"][0]["expected"].endswith("…")


def test_nothing_added_leaves_the_order_untouched():
    tcs = [{"id": "SwTC_SwTR_0002_01", "srs_id": "SwTR_0002"}, {"id": "SwTC_SwTR_0001_01", "srs_id": "SwTR_0001"}]
    before = [tc["id"] for tc in tcs]
    append_requirement_boundary_tcs(tcs, [_req("설명만", rid="SwTR_0001"), _req("설명만", rid="SwTR_0002")], _build,
                                    _make_tc_id, _classify_steps)
    assert [tc["id"] for tc in tcs] == before


def test_a_failed_addition_is_disclosed_not_silent():
    items = {i["key"]: i for i in build_disclosures(
        "sts", {"generation_stats": {"requirement_boundary": {"error": "ValueError: x"}}})}
    item = items["sts_requirement_boundary"]
    assert item["value"] == "생성 실패" and item["tone"] == "warning" and "ValueError: x" in item["note"]


# ── review round 5 ──────────────────────────────────────────────

def test_a_hold_time_quotes_every_line_of_the_run_it_qualifies():
    """(W-A, SwTSR_0202) four conditions joined by AND over four lines, then ``가 50ms 지속되면``: all four are quoted."""
    text = ("- (u16g_MotorSpeed == 0U) AND\n- (u16g_TargetSpeed == MAX) AND\n- (u8g_Run_F == 1U) AND\n"
            "- (u16g_MotorCurr < REF)\n가 50ms 지속되면 고장 검출")
    lines = _lines(text)
    hold = next(x for x in lines if x["text"].startswith("가 50ms"))
    assert hold["joins_previous"] == "and"
    assert hold["previous_text"] == ("- (u16g_MotorSpeed == 0U) AND / - (u16g_TargetSpeed == MAX) AND / "
                                     "- (u8g_Run_F == 1U) AND / - (u16g_MotorCurr < REF)")
    (g,) = [g for g in boundary_steps(_req(text)) if g["evidence"]["kind"] == "duration"]
    assert "u16g_MotorSpeed == 0U" in g["evidence"]["combination_note"] and \
        "u16g_MotorCurr < REF" in g["evidence"]["combination_note"]


def test_a_section_heading_ends_a_run():
    lines = _lines("- u16s_A: 10 초과 AND\n<Pre Condition>\n- u16s_B: 5 초과")
    assert lines[-1]["joins_previous"] == "" and lines[-1]["previous_text"] == ""


def test_a_demonstrative_starts_a_new_sentence():
    """(W-C) ``이 경우 u16s_B …`` is not the previous line's subject going on."""
    lines = _lines("- u16s_A: 10 초과 시 경고\n이 경우 u16s_B: 5 초과 시 고장")
    assert lines[0]["continues"] == "" and lines[1]["joins_previous"] == ""


def test_only_the_condition_clause_is_read_for_other_conditions():
    """(W-B) a connective in the outcome is not a condition; a mixed clause asks; a line-end AND is reported once."""
    def note(text):
        (g,) = boundary_steps(_req(text))
        return g["evidence"]["combination_note"]
    assert note("- u16s_A: 10 초과 시 모터 정지 또는 경고 출력") == ""
    assert note("- u8g_Dir 이 Close 이고 u16s_A: 10 초과 시 정지 또는 경고 출력") == \
        "같은 줄의 다른 조건(원문): 성립 상태로 둔다"
    assert note("- u8g_Dir 이 Close 이고 u8g_M 이 On 또는 u16s_A: 10 초과 시 정지") == \
        "같은 줄의 다른 조건(원문): 결합이 원문에 명시되지 않음 — 결합 조건 확인 필요"
    notes = [g["evidence"]["combination_note"] for g in boundary_steps(_req("- (u16g_S >= 15000) AND\n- 모터 정지"))]
    assert notes == ["다음 줄 조건 [- 모터 정지]과 AND 결합(원문): 성립 상태로 둔다"]


def test_a_head_connective_is_read_in_any_case_and_after_a_bullet():
    lines = _lines("- u16s_A: 10 초과\n- and u16s_B: 5 초과")
    assert lines[1]["joins_previous"] == "and"


def test_a_negated_fact_yields_no_mutant():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import requirement_oracle_eval as ev

    from generators.requirement_oracle import model
    m = model("ID\tSwTR_0605\nName\tA\n- Battery 전압이 8.5V 이상을 만족하지 못하면 고장\n")
    mutants, excluded = ev.requirement_mutants(m["requirements"])
    assert mutants == [] and excluded == {"negated_condition": 1}


def test_a_failed_boundary_addition_leaves_the_sts_as_it_was(tmp_path, monkeypatch):
    """(W-D) the default-on addition raises after appending: generation goes on with the TC list restored."""
    import generators.sts_requirement_tc as srt
    from generators.sts import generate_sts
    real = srt.append_requirement_boundary_tcs

    def boom(test_cases, *a, **k):
        real(test_cases, *a, **k)
        raise RuntimeError("late failure")
    monkeypatch.setattr(srt, "append_requirement_boundary_tcs", boom)
    reqs = ["SwTSR_0209: u16g_ApiIn_Vsup: 1604 초과 시 고전압 고장을 검출한다."]
    on = generate_sts(reqs, {}, str(tmp_path / "on.xlsm"), project_config={"project_id": "T"})
    off = generate_sts(reqs, {}, str(tmp_path / "off.xlsm"),
                       project_config={"project_id": "T", "requirement_boundary_tcs": False})
    assert on["test_case_count"] == off["test_case_count"]
    assert on["quality_report"]["generation_stats"]["requirement_boundary"] == {"error": "RuntimeError: late failure"}


def test_a_failed_evidence_sheet_is_disclosed_and_the_sts_is_saved(tmp_path, monkeypatch):
    import generators.sts_requirement_tc as srt
    from generators.sts import generate_sts

    def boom(wb, tcs):
        raise ValueError("sheet")
    monkeypatch.setattr(srt, "write_requirement_evidence_sheet", boom)
    on = generate_sts(["SwTSR_0209: u16g_ApiIn_Vsup: 1604 초과 시 고전압 고장을 검출한다."], {},
                      str(tmp_path / "on.xlsm"), project_config={"project_id": "T"})
    rb = on["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["tcs"] == 1 and rb["evidence_sheet_error"] == "ValueError: sheet"
    item = {i["key"]: i for i in build_disclosures("sts", on["quality_report"])}["sts_requirement_boundary"]
    assert item["tone"] == "warning" and "시트를 쓰지 못했다" in item["note"]
