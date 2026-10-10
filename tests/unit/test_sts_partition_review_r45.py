"""R45 — what the requirement text leaves unwritten: read it where only one reading means anything, show it where not.

2026-09-30 user direction: what is wrong or undecided is shown in the document and on the web even when there is no
basis to fill it. Three parts:

* **the only meaningful join** (`requirement_oracle.joint`): a lower and an upper bound of one subject written side by
  side with no connective — ``0.8m/s 이상 1.3m/s 이하`` would hold everywhere as *or*, so it is a range; ``4.00V 이하
  4.74V 이상`` would hold nowhere as *and*, so it is either side. Two lower bounds read both ways: still unstated.
* **one quantity split at one value** (`sts_requirement_tc._partition_partners`): ``Manual Assist조건(0.8m/s 미만) 또는
  Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하)`` — held back since R32 C1 (a step told the tester to hold the other name
  false where it holds); each step now writes the other region's verdict at that point. HDPDM01 SwTR_0102/0104's
  0.8 m/s gap (R44).
* **review items**: every fact still held back for a reason a reader can settle is listed — requirement, source,
  sentence, reason, what to decide — in the STS 'Requirement Review' sheet (with the inclusion conflicts) and in the
  generation disclosure.
"""
from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal

import openpyxl
import pytest

from generators.requirement_oracle import extract, join_is_inferred, joint, line_holds
from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import (
    MAX_REVIEW_ITEMS,
    REQUIREMENT_REVIEW_HEADERS,
    REQUIREMENT_REVIEW_SHEET,
    append_requirement_boundary_tcs,
    boundary_steps,
    write_requirement_review_sheet,
)

SPLIT = "- Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하) 인지를 판단한다"
_VERDICT = re.compile(r"^조건 \[.*?\] (성립|불성립) →", re.S)     # how a reader (and the R18 cross scorer) reads a step


def _line(text):
    (req,) = extract(f"ID\tSwTSR_0101\nName\tx\n{text}\n")
    return req["lines"][0]


def _req(desc, rid="SwTR_0102", verification=""):
    return {"id": rid, "name": "n", "description": desc, "verification": verification, "asil": "B"}


@pytest.mark.parametrize("text, join, inferred", [
    ("- u16s_V 가 9V 이상 16V 이하", "and", True),          # or would hold for every voltage
    ("- u16s_V 가 9V 이상, 16V 이하", "and", True),
    ("- u16s_V 가 9V 이상 ~ 16V 이하", "and", True),
    ("- u16s_V 가 9V 이상 9V 이하", "and", True),            # exactly 9 V
    # (review C1) a lower bound above the upper one is how a hysteresis is written — never "either side"
    ("- u16g_M 이 4.00V 이하 4.74V 이상", "unstated", False),
    ("- u16s_V 가 9V 초과 9V 미만", "unstated", False),
    ("- 저전압 8.5V 이하 9.0V 이상 복귀 시 경고", "unstated", False),
    ("- u16s_V 가 9V 이상 16V 이상", "unstated", False),     # two lower bounds: both readings mean something
    ("- u16s_V 가 9V 이상 9V 미만", "unstated", False),      # empty on any grid
    ("- u8g_X 가 10 초과 11 미만", "unstated", False),       # (review I1) empty on the integer grid
    ("- u16s_V 가 9V 이상에서 16V 이하", "unstated", False),  # words between: not side by side
    ("- u16s_V 가 9V 이상 또는 16V 이하", "or", False),       # written: kept as written
])
def test_a_join_the_words_do_not_write_is_read_only_where_one_reading_means_anything(text, join, inferred):
    line = _line(text)
    a, b = line["facts"][:2]
    assert (joint(line, a, b), join_is_inferred(line, a, b)) == (join, inferred)


def test_a_range_binds_its_bounds_before_a_written_connective():
    line = _line("- A 가 4V 이하 또는 5V 이상 6V 이하")
    low, lo, hi = line["facts"]
    assert joint(line, low, hi) == "or" and joint(line, lo, hi) == "and"
    # 4 V or (5 V .. 6 V) — not "any of three" (7 V would hold through ``5V 이상``)
    assert [line_holds(Decimal(v), low, line) for v in ("3", "4.5", "5.5", "7")] == [True, False, True, False]
    assert [line_holds(Decimal(v), hi, line) for v in ("3", "4.5", "5.5", "7")] == [True, False, True, False]
    split = _line(SPLIT)
    manual, tip_low, tip_high = split["facts"]
    assert joint(split, manual, tip_high) == "or"


def test_one_quantity_split_at_one_value_is_stepped_with_the_other_regions_verdict():
    stats, review = Counter(), []
    groups = boundary_steps(_req(SPLIT), stats, None, review)
    rows = [(g["evidence"]["signal"], s["action"].split(" = ")[1].split(" — ")[0], s["expected"])
            for g in groups for s in g["steps"]]
    own = [(name, point, _VERDICT.match(exp).group(1)) for name, point, exp in rows]
    assert own == [("Manual Assist조건", "0.7m/s", "성립"), ("Manual Assist조건", "0.8m/s", "불성립"),
                   ("Manual Assist조건", "0.9m/s", "불성립"),
                   ("Tip-To-Run 조건", "0.7m/s", "불성립"), ("Tip-To-Run 조건", "0.8m/s", "성립"),
                   ("Tip-To-Run 조건", "0.9m/s", "성립"),
                   ("Tip-To-Run 조건", "1.2m/s", "성립"), ("Tip-To-Run 조건", "1.3m/s", "성립"),
                   ("Tip-To-Run 조건", "1.4m/s", "불성립")]
    # the other region's verdict at the same point — the complement at the split, both false past 1.3 m/s
    partner = [re.search(r"같은 양을 나눈 조건 \[[^\]]*\] (성립|불성립)", exp).group(1) for _n, _p, exp in rows]
    assert partner == ["불성립", "성립", "성립", "성립", "불성립", "불성립", "불성립", "불성립", "불성립"]
    assert "그 조건의 판정을 따른다" in rows[1][2] and "이 문장의 동작 대상 아님" in rows[8][2]
    assert not any("불성립 상태로 둔다" in g["evidence"]["combination_note"] for g in groups)
    assert all("같은 양을 나눈 조건" in g["evidence"]["combination_note"] for g in groups)
    assert "원문에 연결어 없음" in groups[1]["evidence"]["combination_note"]      # the inferred range says so
    assert stats["facts_used"] == 3
    # (review I3) nothing held back — what was read is listed for a reader to confirm
    assert sorted((r["kind"], r["reason"], r["fact"]) for r in review) == [
        ("read", "read_as_one_quantity", "0.8m/s 미만"), ("read", "read_as_one_quantity", "0.8m/s 이상"),
        ("read", "read_as_one_quantity", "1.3m/s 이하"), ("read", "read_as_range", "0.8m/s 이상"),
        ("read", "read_as_range", "1.3m/s 이하")]


def test_a_split_whose_other_region_has_no_verdict_is_held_back():
    """(review W4) ``B조건(0.8m/s 이상, 2.0m/s 이상)`` does not say how its two bounds join: no verdict at a point — the
    split is not written, so both stay held back (R32 C1) instead of "판정 미상" steps."""
    stats = Counter()
    assert boundary_steps(_req("- A조건(0.8m/s 미만) 또는 B조건(0.8m/s 이상, 2.0m/s 이상) 인지를 판단한다"), stats) == []
    assert stats["skipped:parenthesis_labels_may_share_a_quantity"] == 1


def test_the_condition_text_groups_a_range_as_the_verdict_does():
    """(review W3) the words the tester reads were ``5V 이상 그리고 4V 이하 그리고 6V 이하`` for a verdict of
    4V 이하 or (5V..6V)."""
    groups = boundary_steps(_req("- u16s_V 가 4V 이하 또는 5V 이상 6V 이하"))
    conditions = {g["evidence"]["value"]: re.match(r"^조건 \[(.*?)\] ", g["steps"][0]["expected"]).group(1)
                  for g in groups}
    assert set(conditions.values()) == {"u16s_V 4V 이하 또는 (5V 이상 그리고 6V 이하)"}
    # a line without a range read from meaning keeps its old wording (no existing step changes)
    (g,) = [g for g in boundary_steps(_req("- u16g_M 이 4.00V 이하 또는 4.74V 이상")) if g["evidence"]["value"] == "4.74"]
    assert g["steps"][0]["expected"].startswith("조건 [u16g_M 4.74V 이상 또는 4.00V 이하] ")


def test_a_range_of_one_subject_is_stepped_and_says_the_join_was_read_not_written():
    groups = boundary_steps(_req("- u16s_V 가 9V 이상 16V 이하"))
    points = [(s["action"].split(" = ")[1].split(" — ")[0], _VERDICT.match(s["expected"]).group(1))
              for g in groups for s in g["steps"]]
    assert points == [("8V", "불성립"), ("9V", "성립"), ("10V", "성립"), ("15V", "성립"), ("16V", "성립"),
                      ("17V", "불성립")]
    assert all("유일한 읽기" in g["evidence"]["combination_note"] for g in groups)


REVIEWABLE = ("- 전압이 8.5V 미만이 아닌 경우 정상\n"          # negated
              "u16g_ApiIn_Vsup\t850 ~ 1,604\n"                 # a range
              "- u16s_V 가 9V 이상 16V 이상\n"                  # a join unstated
              "- 100ms 이상 유지 시 정지\n"                      # an unnamed hold time is a condition — stepped
              "- Application 안정화 시간 : 100ms 이내\n"         # a response constraint: nothing to decide
              "- 암전류는 0.3mA 이하여야 한다\n"                   # an obligation: an output, nothing to decide
              "( u16g_ApiIn_Vsup < u16s_BATT_ERR_LOWER_LIMIT )\n"  # a symbolic comparison: no value to step
              "- 저 전압 고장 검출 기준 전압: 8.50V 이하\n")        # a reference label: names the threshold


def test_only_facts_a_reader_can_settle_become_review_items():
    stats, review = Counter(), []
    boundary_steps(_req(REVIEWABLE), stats, None, review)
    assert sorted(r["reason"] for r in review) == [
        "kind_range", "negated_condition", "same_subject_combination_unstated", "same_subject_combination_unstated"]
    assert all(r["srs_id"] == "SwTR_0102" and r["source"] == "SRS" and r["line"] and r["fact"] for r in review)
    assert stats["skipped:response_constraint"] == 1 and stats["skipped:output_requirement"] == 1
    assert stats["skipped:kind_symbolic"] == 1 and stats["skipped:reference_label"] == 1   # counted, not review items


def test_what_is_no_condition_is_no_review_item_however_it_was_held_back():
    """(review W2) a subject would not make these a step — a deadline, an outcome line, an obligation."""
    review = []
    boundary_steps(_req("- 500ms 이내 응답\n<Output>\n- 8.5V 이하로 출력\n"), Counter(), None, review)
    boundary_steps(_req("- 0.3mA 이하여야 한다"), Counter(), None, review)
    assert review == []
    boundary_steps(_req("- 8.5V 이하 시 정지"), Counter(), None, review)          # a condition with no subject
    assert [r["reason"] for r in review] == ["no_subject_for_value"]


def test_an_inner_deadline_in_a_conditional_clause_is_a_question_not_a_deadline():
    """(review r2 W-R2-2) HDPDM01 SwNTR_0408 ``20ms 이내에 … 되지 않으면`` — a time window of the condition, or a
    deadline? The extractor says deadline; a sentence-final ``이내`` stays out."""
    review = []
    boundary_steps(_req("- 20ms 이내에 Message Flag가 Set/Clear가 되지 않으면 LIN 통신 Error"), Counter(), None, review)
    assert [(r["reason"], r["fact"]) for r in review] == [("deadline_or_window", "20ms 이내")]
    review = []
    boundary_steps(_req("- Application 안정화 시간 : 100ms 이내\n- 100ms 이내에 응답해야 한다"), Counter(), None, review)
    assert review == []


def test_a_range_is_never_promised_a_boundary_step():
    """(review r2 W-R2-1) a range makes no step here, subject or not — the row says what to settle, no more."""
    system = {"SyII_28": {"doc": "SyDS", "name": "Motor Driver Current", "fields": {"Range": "0~5V"}}}
    review = []
    boundary_steps({**_req("- 동작"), "related_id": "SyII_28"}, Counter(), system, review)
    assert [(r["reason"], r["fact_kind"]) for r in review] == [("no_subject_in_value_field", "range")]
    wb = openpyxl.Workbook()
    write_requirement_review_sheet(wb, [{**review[0], "srs_ids": ["SwTR_0102"]}])
    row = list(wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True))[1]
    assert "경계 TC 가 된다" not in row[5] and "하한·상한의 포함" in row[5] and "Motor Driver Current" in row[4]


def test_a_value_field_names_its_quantity_in_the_block_name():
    """(review W1) ``Range: 9 ~ 16V`` of block ``Battery Power``: the document did not leave the subject out."""
    system = {"SyEI_01": {"doc": "SyDS", "name": "Battery Power", "fields": {"Range": "9V 이상 동작"}}}
    req = {**_req("- 동작"), "related_id": "SyEI_01"}
    review = []
    boundary_steps(req, Counter(), system, review)
    assert [(r["reason"], r["block_name"]) for r in review] == [("no_subject_in_value_field", "Battery Power")]
    wb = openpyxl.Workbook()
    write_requirement_review_sheet(wb, [{**review[0], "srs_ids": ["SwTR_0102"]}])
    row = list(wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True))[1]
    assert "블록 이름 'Battery Power'" in row[4] and "블록 이름(Name)" in row[5]
    # the same value in a sentence field is a subject missing from the sentence
    system["SyEI_01"]["fields"] = {"Description": "9V 이상 동작"}
    review = []
    boundary_steps(req, Counter(), system, review)
    assert [r["reason"] for r in review] == ["no_subject_for_value"]


def _append(requirements, system=None):
    tcs, out = [], []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(tcs, requirements, build, _make_tc_id, _classify_steps, system=system,
                                            review_out=out)
    return stats, out


def test_a_block_cited_by_two_requirements_is_one_review_row_naming_both():
    system = {"SySM_04": {"doc": "SyDS", "fields": {"Description": "입력전원 9V~16V 범위에서 정상 동작"}}}
    reqs = [{**_req("- 동작", rid="SwTR_0601"), "related_id": "SySM_04"},
            {**_req("- 동작", rid="SwTSR_0101"), "related_id": "SySM_04"}]
    stats, out = _append(reqs, system)
    held = [r for r in out if r["kind"] == "held_back"]
    assert len(held) == 1 and held[0]["srs_ids"] == ["SwTR_0601", "SwTSR_0101"]
    assert held[0]["source"] == "SyDS SySM_04 · Description" and held[0]["reason"] == "kind_range"
    assert (stats["review_item_count"], stats["review_by_reason"]) == (1, {"kind_range": 1})
    assert stats["traced:skipped:kind_range"] == 2          # the counter still counts each citing requirement


def test_a_reading_is_one_row_per_sentence_with_its_facts():
    """(review I3) what was read is confirmed per sentence, not per fact — and it follows what was held back."""
    stats, out = _append([_req(SPLIT + "\n- 전압이 8.5V 미만이 아닌 경우 정상")])
    assert [(r["kind"], r["reason"], r["fact"]) for r in out] == [
        ("held_back", "negated_condition", "8.5V 미만"),
        ("read", "read_as_one_quantity", "0.8m/s 미만 · 0.8m/s 이상 · 1.3m/s 이하"),
        ("read", "read_as_range", "0.8m/s 이상 · 1.3m/s 이하")]
    assert (stats["review_item_count"], stats["review_read_count"]) == (3, 2)


def test_the_report_keeps_the_first_items_and_the_document_gets_all():
    reqs = [_req(f"- 전압이 {v}V 미만이 아닌 경우 정상", rid=f"SwTR_{v:04d}") for v in range(1, MAX_REVIEW_ITEMS + 6)]
    stats, out = _append(reqs)
    assert stats["review_item_count"] == MAX_REVIEW_ITEMS + 5 == len(out)
    assert len(stats["review_items"]) == MAX_REVIEW_ITEMS
    # none held back: the count is 0, not missing — the disclosure says it looked
    stats, out = _append([_req("- u16s_A 가 10 초과")])
    assert (stats["review_item_count"], stats["review_items"], out) == (0, [], [])


def test_the_inclusion_conflicts_go_to_the_same_sheet():
    system = {"SyII_06": {"doc": "SyDS", "fields": {"Range": "저전압 : 8.5V 이하 500ms 초과"}}}
    req = {**_req("- 저전압 : 8.5V 미만 500ms 초과 시 정지", rid="SwTSR_0104"), "related_id": "SyII_06"}
    stats, out = _append([req], system)
    conflicts = [r for r in out if r["kind"] == "inclusion_conflict"]
    assert stats["inclusion_conflicts"] == len(conflicts) >= 1


def test_the_review_sheet_lists_every_item_and_says_what_to_decide():
    wb = openpyxl.Workbook()
    wb.create_sheet(REQUIREMENT_REVIEW_SHEET)                      # a template made from an earlier output
    stats, out = _append([_req(REVIEWABLE)])
    out.append({"kind": "inclusion_conflict", "srs_id": "SwTSR_0104", "role": "condition", "same_subject": True,
                "within_source": True, "a": {"source": "SRS", "subject": "저전압", "text": "8.5V 이하", "line": "a"},
                "b": {"source": "SRS", "subject": "저전압", "text": "8.5V 미만", "line": "b"}})
    assert write_requirement_review_sheet(wb, out) == len(out) == 5
    assert wb.sheetnames.count(REQUIREMENT_REVIEW_SHEET) == 1
    rows = list(wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True))
    assert list(rows[0]) == REQUIREMENT_REVIEW_HEADERS
    kinds = [r[0] for r in rows[1:]]
    assert kinds.count("검토 필요 조건") == 4 and kinds.count("요구 문서 경계 포함 불일치") == 1
    assert all(r[5] for r in rows[1:])                               # every row says what to decide
    conflict = rows[-1]
    assert conflict[2] == "SRS ↔ SRS" and "한 출처 안의 두 줄" in conflict[4]
    # nothing to review: no sheet, and a template's old one is removed
    assert write_requirement_review_sheet(wb, []) == 0 and REQUIREMENT_REVIEW_SHEET not in wb.sheetnames


def test_generate_sts_writes_the_review_sheet_from_the_generation(tmp_path):
    from generators.sts import generate_sts_xlsm
    items = [{"kind": "held_back", "srs_ids": ["SwTR_0102"], "source": "SRS", "reason": "kind_range",
              "line": "u16g_ApiIn_Vsup\t850 ~ 1,604", "line_sha256": "x", "fact": "850 ~ 1,604", "line_span": [0, 1]}]
    out = generate_sts_xlsm(None, [], {"matrix": [], "summary": {}}, str(tmp_path / "s.xlsm"), requirement_review=items)
    wb = openpyxl.load_workbook(out)
    assert REQUIREMENT_REVIEW_SHEET in wb.sheetnames
    assert list(wb[REQUIREMENT_REVIEW_SHEET].iter_rows(values_only=True))[1][:3] == ("검토 필요 조건", "SwTR_0102", "SRS")
    out2 = generate_sts_xlsm(None, [], {"matrix": [], "summary": {}}, str(tmp_path / "t.xlsm"))
    assert REQUIREMENT_REVIEW_SHEET not in openpyxl.load_workbook(out2).sheetnames


def test_the_generation_keeps_the_review_sheet_error_apart_and_drops_half_added_items(tmp_path, monkeypatch):
    """(review W5 · I6) a failed review sheet is disclosed under its own key; a failed boundary pass leaves no rows."""
    import generators.sts_requirement_tc as rtc
    from generators.sts import generate_sts
    reqs = ["SwTSR_0209: 전압이 8.5V 미만이 아닌 경우 정상 동작한다."]

    def broken(wb, items):
        raise RuntimeError("disk full")
    monkeypatch.setattr(rtc, "write_requirement_review_sheet", broken)
    res = generate_sts(reqs, {}, str(tmp_path / "a.xlsm"), project_config={"project_id": "T"})
    rb = res["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["review_sheet_error"] == "RuntimeError: disk full" and "evidence_sheet_error" not in rb
    monkeypatch.undo()

    captured = {}

    def boom(*a, **kw):
        kw["review_out"].append({"kind": "held_back", "srs_ids": ["X"], "source": "SRS", "reason": "kind_range",
                                 "line": "l", "line_sha256": "s", "fact": "f", "line_span": [0, 1]})
        raise RuntimeError("half way")
    real_xlsm = __import__("generators.sts", fromlist=["generate_sts_xlsm"]).generate_sts_xlsm

    def spy(*a, **kw):
        captured["review"] = list(kw.get("requirement_review") or [])
        return real_xlsm(*a, **kw)
    monkeypatch.setattr(rtc, "append_requirement_boundary_tcs", boom)
    monkeypatch.setattr("generators.sts.generate_sts_xlsm", spy)
    res = generate_sts(reqs, {}, str(tmp_path / "b.xlsm"), project_config={"project_id": "T"})
    assert "half way" in res["quality_report"]["generation_stats"]["requirement_boundary"]["error"]
    assert captured["review"] == []


def test_the_disclosure_shows_the_review_items_and_says_none_was_looked_at_before_r45():
    from report_gen.generation_disclosures import build_disclosures

    def _item(rb):
        items = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"requirement_boundary": rb}})}
        return items.get("sts_requirement_review")
    base = {"tcs": 1, "steps": 3, "facts_used": 1, "facts": 2}
    assert _item(base) is None                                        # an output from before R45
    assert _item({**base, "review_item_count": 0})["value"] == "0건"
    rb = {**base, "review_item_count": 7, "review_by_reason": {"kind_range": 5, "no_subject_for_value": 2},
          "review_items": [{"srs_ids": ["SwTR_0601", "SwTSR_0101"], "source": "SyDS SySM_04 · Description",
                            "fact": "9V~16V", "reason": "kind_range"}] * 6}
    item = _item(rb)
    assert item["value"] == "7건" and item["tone"] == "warning"
    assert "범위 5" in item["note"] and "주어 없음 2" in item["note"] and "SwTR_0601 외 1" in item["note"]
    assert "외 2건" in item["note"] and "'Requirement Review' 시트에 전부 적었다" in item["note"]
    # (review I7) no system document read: the conflicts were not compared — not "in the same sheet"
    assert "불일치 후보도 같은 시트" not in item["note"]
    assert "불일치 후보도 같은 시트" in _item({**rb, "inclusion_conflicts": 0})["note"]
    # (review W5) the sheet failed: not "written there"
    failed = _item({**rb, "review_sheet_error": "RuntimeError: disk full", "review_read_count": 2})
    assert "시트를 쓰지 못했다 — RuntimeError: disk full" in failed["note"] and "전부 적었다" not in failed["note"]
    assert failed["value"] == "7건 · 그중 읽은 결합 2"
