"""R44 — the G4(b) denominator read by where each reference threshold is written.

The cross scoring (R18) makes mutants from the thresholds the reference STS's testers used as stimuli. Many are not the
requirement's own thresholds: HDPDM01's reference writes system-state boundaries from other documents and uses response
deadlines of cited blocks as stimuli, KJPDS02_PV's writes stimulus values (``8v 이하``), a unit typo (``2.1ms`` for
2.1 m/s) and ADC counts (``485``). Scoring them all as one denominator reads a tester's choice as our miss. Each mutant
now carries its ``provenance`` — ``srs``, ``cited_system`` (a condition fact the generator's own reading of a cited
SyRS/SyDS block yields), ``cited_response_constraint``, ``cited_text_only``, ``project_document`` or
``not_in_given_documents`` — and the cross scoring reports ``by_provenance``. Review R1 C1: the cited class was a text
match first, which put deadlines and a value of another block there.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import requirement_oracle_eval as ev  # noqa: E402

BLOCK = "ID\tSwTR_0601\nName\tAuto\n- 차량 속도 3km/h 이상 시 정지\nRelated ID\tSyII_06, SyTR_0602\n"
OTHER = "ID\tSwTR_0602\nName\tManual\n- 배터리 전압 9V 이상 시 동작\n"
SYSTEM = {"SyII_06": {"doc": "SyDS", "fields": {"Description": "도어 상태 500ms 초과 유지 시 판정"}},
          "SyTR_0602": {"doc": "SyRS", "fields": {"Description": "슬램 1.3m/s 초과 시 정지",
                                                  "Time Constraint": "300ms 이내에 모터를 정지해야 한다",
                                                  "Action": "모터를 2초 이상 역회전"}},
          "SyXX_99": {"doc": "SyRS", "fields": {"Description": "팝업 15도"}}}          # not cited by the block
DOCS = {"SyRS_full.txt": "Pop Up Position(15deg) … 팝업 15도 미만 · 300ms", "Func.txt": "0.8m/s 이상 팁투런 · 1.3m/s"}


def test_the_cited_ids_are_the_related_id_rows_in_order():
    text = BLOCK + "Related ID\tSyTR_0602, SyEI_03\n"
    assert ev._cited_ids(text) == ["SyII_06", "SyTR_0602", "SyEI_03"]
    assert ev._cited_ids("ID\tSwTR_0101\n- no related row") == []


def test_provenance_says_where_the_number_is_written_first_match_wins():
    blocks = {"SwTR_0601": BLOCK, "SwTR_0602": OTHER}
    assert ev.provenance("SwTR_0601", 3, "km/h", blocks, SYSTEM, DOCS) == ("srs", [])
    assert ev.provenance("SwTR_0601", 500, "ms", blocks, SYSTEM, DOCS) == ("cited_system", ["SyDS SyII_06 · Description"])
    assert ev.provenance("SwTR_0601", 0.5, "s", blocks, SYSTEM, DOCS)[0] == "cited_system"      # 500ms in seconds
    # a block the requirement does not cite is not one hop: another document may still write it
    assert ev.provenance("SwTR_0601", 15, "도", blocks, SYSTEM, DOCS) == ("project_document", ["SyRS_full.txt"])
    assert ev.provenance("SwTR_0601", 0.8, "m/s", blocks, SYSTEM, DOCS) == ("project_document", ["Func.txt"])
    assert ev.provenance("SwTR_0601", 2.1, "ms", blocks, SYSTEM, DOCS) == ("not_in_given_documents", [])
    # nothing given to look in: not examined, not "not found"
    assert ev.provenance("SwTR_0601", 500, "ms", blocks, None, None) == (None, [])
    assert ev.provenance("SwTR_0601", 3, "km/h", blocks, None, None) == ("srs", [])
    # a bare number without its unit is not the quantity (list numbers, IDs)
    assert ev.provenance("SwTR_0601", 602, "ms", blocks, SYSTEM, DOCS)[0] == "not_in_given_documents"


def test_a_cited_value_is_cited_even_when_a_document_also_writes_it():
    """(review W2) the cited block is the closer evidence: a SyRS export among the documents must not take it."""
    blocks = {"SwTR_0601": BLOCK}
    assert ev.provenance("SwTR_0601", 1.3, "m/s", blocks, SYSTEM, DOCS) == ("cited_system", ["SyRS SyTR_0602 · Description"])
    # the deadline of a cited block is its own class, before the document that also writes 300ms
    assert ev.provenance("SwTR_0601", 300, "ms", blocks, SYSTEM, DOCS) == (
        "cited_response_constraint", ["SyRS SyTR_0602 · Time Constraint"])


def test_a_cited_number_no_condition_fact_carries_is_text_only():
    """(review C1) the outcome field's ``2초 이상`` is a fact the extractor reads — of what the system does, not a
    condition to step (R29 review C2)."""
    blocks = {"SwTR_0601": BLOCK}
    assert ev.provenance("SwTR_0601", 2, "초", blocks, SYSTEM, DOCS) == ("cited_text_only", ["SyRS SyTR_0602 · Action"])
    assert ev.provenance("SwTR_0601", 2000, "ms", blocks, SYSTEM, None)[0] == "cited_text_only"
    # HDPDM01 SyTSR_0109 as written: ``500ms 내에 … 진입해야 한다`` yields no fact (only ``이내`` is read as a
    #   deadline) — the reference's ``500ms 이상`` stimulus is not a threshold the generator could step
    system = {"SyTSR_0109": {"doc": "SyRS", "fields": {"Description": (
        "ECU는 Motor Position 이상이 발생하면 500ms 내에 작동 중단 상태로 진입해야 한다.\n"
        "Pulse가 감지 되지 않는 상태로 특정시간(300ms) 초과 유지되는 경우")}}}
    block = {"SwTSR_0202": "ID\tSwTSR_0202\n- 모터 위치 이상 판정\nRelated ID\tSyTSR_0109\n"}
    assert ev.provenance("SwTSR_0202", 500, "ms", block, system, DOCS) == (
        "cited_text_only", ["SyRS SyTSR_0109 · Description"])
    assert ev.provenance("SwTSR_0202", 300, "ms", block, system, DOCS)[0] == "cited_system"


def test_a_cited_fact_the_generator_does_not_count_as_a_condition_is_not_cited():
    """(r2 W1) the generator's own split: an ``Output :`` line inside another field (HDPDM01 SyTR_0604), an obligation,
    a negated phrase — each a number the cited text writes, none a condition to step."""
    block = {"SwTR_0107": "ID\tSwTR_0107\n- 암전류 측정\nRelated ID\tSyTR_0604\n"}
    for text, value, unit in (("Input: 도어 닫힘\nOutput: 전류 7mA 이하가 되는 시간 측정", 7, "mA"),
                              ("암전류는 0.3mA 이하여야 한다", 0.3, "mA"),
                              ("차량 속도가 3km/h 이상이 아닌 경우 동작한다", 3, "km/h")):
        system = {"SyTR_0604": {"doc": "SyRS", "fields": {"Verification criteria": text}}}
        assert ev.provenance("SwTR_0107", value, unit, block, system, None) == (
            "cited_text_only", ["SyRS SyTR_0604 · Verification criteria"]), text
    # the same numbers as conditions are cited
    system = {"SyTR_0604": {"doc": "SyRS", "fields": {"Description": "전류 7mA 이상 시 정지"}}}
    assert ev.provenance("SwTR_0107", 7, "mA", block, system, None)[0] == "cited_system"


def test_a_cited_condition_the_generator_does_not_step_says_why():
    """(r2 I1) HDPDM01 SyFN_02: the generator reads the 0.8 m/s condition and holds it back (R32 C1) — the gap shows
    in ``where`` without reading the generator."""
    block = {"SwTR_0102": "ID\tSwTR_0102\n- Assist Close\nRelated ID\tSyFN_02\n"}
    system = {"SyFN_02": {"doc": "SyDS", "fields": {"Description": (
        "Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하) 인지를 판단한다")}}}
    assert ev.provenance("SwTR_0102", 0.8, "m/s", block, system, None) == (
        "cited_system", ["SyDS SyFN_02 · Description (생성기 제외: parenthesis_labels_may_share_a_quantity)"])


def test_the_held_back_cited_mutants_are_counted_per_class(tmp_path):
    """(r3 I1) the cited class's headline splits without opening the rows: 0.8 m/s is read and held back."""
    block = "ID\tSwTR_0102\n- Assist Close\nRelated ID\tSyFN_02\n"
    system = {"SyFN_02": {"doc": "SyDS", "fields": {"Description": (
        "Manual Assist조건(0.8m/s 미만) 또는 Tip-To-Run 조건(0.8m/s 이상 1.3m/s 이하) 인지를 판단한다")}}}
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [("SwTC_1", "도어를 0.8m/s 이상으로 닫음", "Tip-To-Run", "SwTR_0102")]))
    ms, _ = ev.reference_mutants(ref, {"SwTR_0102": block}, None, system, None)
    split = ev.cross_discrimination(ms, ref, self_sourced=True)["by_provenance"]
    assert (split["cited_system"]["killable"], split["cited_system"]["killable_held_back_by_generator"]) == (2, 2)
    # a cited condition the generator steps is not held back
    stepped = {"SyFN_02": {"doc": "SyDS", "fields": {"Description": "도어 속도 0.8m/s 이상 시 Tip-To-Run 판단"}}}
    ms, _ = ev.reference_mutants(ref, {"SwTR_0102": block}, None, stepped, None)
    split = ev.cross_discrimination(ms, ref, self_sourced=True)["by_provenance"]
    assert (split["cited_system"]["killable"], split["cited_system"]["killable_held_back_by_generator"]) == (2, 0)


def test_a_cited_fact_without_a_unit_names_no_quantity():
    """(r3 I2) ``u16s_X 500 이상`` is not the reference's ``500ms`` — a unit-less value is matched to no unit."""
    block = {"SwTR_0601": "ID\tSwTR_0601\n- 판정\nRelated ID\tSyII_06\n"}
    system = {"SyII_06": {"doc": "SyDS", "fields": {"Description": "u16s_DoorTimer 500 이상 시 판정"}}}
    assert ev.provenance("SwTR_0601", 500, "ms", block, system, None) == ("not_in_given_documents", [])


def test_another_srs_block_and_every_document_are_named():
    """(review I1 · I2) ``where`` is the full list; another block of the SRS counts as a project document."""
    blocks = {"SwTR_0601": BLOCK, "SwTR_0602": OTHER}
    assert ev.provenance("SwTR_0601", 9, "V", blocks, SYSTEM, None) == ("project_document", ["SRS SwTR_0602"])
    docs = {"b.txt": "9V 이상", "a.txt": "전압 9 V", "c.txt": "9 A"}
    assert ev.provenance("SwTR_0601", 9, "V", blocks, None, docs) == ("project_document", ["SRS SwTR_0602", "a.txt", "b.txt"])
    # system blocks alone (no documents): still examined
    assert ev.provenance("SwTR_0601", 2.1, "ms", {"SwTR_0601": BLOCK}, SYSTEM, None) == ("not_in_given_documents", [])


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


def _zero():
    return {"mutants": 0, "killable": 0, "killed": 0, "rate_of_killable": None, "killable_against_verdict": 0,
            "killable_held_back_by_generator": 0}


def test_each_mutant_carries_its_provenance_and_the_score_splits_by_it(tmp_path):
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [
        ("SwTC_1", "차량 속도 3km/h 이상으로 주행", "정지", "SwTR_0601"),
        ("", "도어 500ms 이상 유지", "판정", ""),
        ("", "300ms 이내 정지 확인을 위해 300ms 이상 대기", "정지", ""),
        ("", "팝업 15도 미만으로 수동 조작", "상태", ""),
        ("", "2.1ms 이상 속도로 닫음", "정지", "")]))
    ms, _excluded = ev.reference_mutants(ref, {"SwTR_0601": BLOCK}, None, SYSTEM, DOCS)
    by_raw = {m["raw"]: (m["provenance"], m["provenance_where"]) for m in ms}
    assert by_raw == {"3km/h 이상": ("srs", []), "500ms 이상": ("cited_system", ["SyDS SyII_06 · Description"]),
                      "300ms 이상": ("cited_response_constraint", ["SyRS SyTR_0602 · Time Constraint"]),
                      "15도 미만": ("project_document", ["SyRS_full.txt"]), "2.1ms 이상": ("not_in_given_documents", [])}
    gen = ev.read_sts(_sts(tmp_path / "gen.xlsx", [
        ("SwTC_9", "입력 설정 (요구 경계): 차량 속도 = 3km/h 설정",
         "조건 [차량 속도 3km/h 이상] 성립 → 이 문장이 기술한 동작 수행 확인: …", "SwTR_0601"),
        # the cited SyDS writes ``500ms 초과``: at 500ms the generated step expects no judgement, where the
        #   reference's ``500ms 이상`` holds — the two documents disagree (a separation, not a kill)
        ("SwTC_10", "입력 설정 (요구 경계): 도어 상태 지속 시간 = 500ms 설정",
         "조건 [도어 상태 500ms 초과 유지] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0601")]))
    d = ev.cross_discrimination(ms, gen)
    three = {"mutants": 3, "killable": 2, "killed": 0, "rate_of_killable": 0.0, "killable_against_verdict": 0,
             "killable_held_back_by_generator": 0}
    assert d["by_provenance"] == {"srs": {**three, "killed": 2, "rate_of_killable": 1.0},
                                  # at 500ms: the flipped inclusion (> 500) and 501 — the step says 불성립 there
                                  "cited_system": {**three, "killable_against_verdict": 2},
                                  "cited_response_constraint": three, "cited_text_only": _zero(),
                                  # ``15도 미만``: the flipped inclusion and 16 widen it — only 14 can be killed
                                  "project_document": {**three, "killable": 1}, "not_in_given_documents": three}
    assert list(d["by_provenance"]) == list(ev.PROVENANCES)          # every class listed, 0 is a count (review I6)
    assert sum(v["killed"] for v in d["by_provenance"].values()) == d["killed"]
    assert sum(v["killable"] for v in d["by_provenance"].values()) == d["killable_mutants"]
    # without system blocks or documents nothing is classified: no split (not "all srs")
    plain, _ = ev.reference_mutants(ref, {"SwTR_0601": BLOCK})
    assert ev.cross_discrimination(plain, gen)["by_provenance"] is None
    # a suite with no point that states a verdict is not measured: the class kills are not scores (review W3)
    unmeasured = ev.cross_discrimination(ms, ref, self_sourced=True)["by_provenance"]
    assert unmeasured["srs"] == {"mutants": 3, "killable": 2, "killed": None, "rate_of_killable": None,
                                 "killable_against_verdict": None, "killable_held_back_by_generator": 0}


def test_only_killable_mutants_count_as_against_the_verdict(tmp_path):
    """(r2 I2) ``15도 미만`` at 15 with a step saying 성립: the widening mutants ``<= 15`` and ``< 16`` separate there
    (the original says no, the step yes) but no point could ever kill them — they are no missed kill."""
    ref = ev.read_sts(_sts(tmp_path / "ref.xlsx", [("SwTC_1", "팝업 15도 미만으로 수동 조작", "상태", "SwTR_0601")]))
    ms, _ = ev.reference_mutants(ref, {"SwTR_0601": BLOCK}, None, SYSTEM, DOCS)
    gen = ev.read_sts(_sts(tmp_path / "gen.xlsx", [
        ("SwTC_9", "입력 설정 (요구 경계): 팝업 = 15도 설정", "조건 [팝업 15도 이하] 성립 → …", "SwTR_0601")]))
    d = ev.cross_discrimination(ms, gen)
    assert d["separated_against_verdict"] == 2                                      # the suite-wide count (R32)
    assert d["by_provenance"]["project_document"]["killable_against_verdict"] == 0


def test_the_report_classifies_the_thresholds_the_srs_does_not_state(tmp_path):
    ref = _sts(tmp_path / "ref.xlsx", [("SwTC_1", "차량 속도 3km/h 이상으로 주행", "정지", "SwTR_0601"),
                                       ("", "팝업 15도 미만으로 수동 조작", "상태", "")])
    report = ev.evaluate(BLOCK, ref, None, None, DOCS)
    items = {i["raw"]: (i.get("provenance"), i["value"], i["unit"]) for i in report["recall"]["not_stated_in_srs"]}
    assert items == {"15도 미만": ("project_document", 15.0, "도")}
    assert report["cross_source"]["provenance_inputs"] == {
        "system_documents": [], "cited_id_mentions": None, "cited_ids_distinct": None,
        "cited_ids_not_in_system_documents": None, "documents": sorted(DOCS)}
    assert report["cross_source"]["provenance_note"] == ev.PROVENANCE_NOTE
    # (r2 I5) documents only: the cited classes were not examined — None, not a count of 0
    split = report["cross_source"]["reference"]["by_provenance"]
    assert [c for c, v in split.items() if v is None] == ["cited_system", "cited_response_constraint", "cited_text_only"]
    assert split["project_document"]["mutants"] == 3
    # no documents at all: the report says nothing about provenance
    bare = ev.evaluate(BLOCK, ref)
    assert bare["cross_source"]["provenance_inputs"] is None and bare["cross_source"]["provenance_note"] is None
    assert all(i["provenance"] is None for i in bare["recall"]["not_stated_in_srs"])


def test_the_report_reads_the_system_documents_it_is_given(tmp_path, monkeypatch):
    import generators.sts_requirement_tc as tc
    calls = []

    def fake(docs):
        calls.append(docs)
        return SYSTEM, [{"doc": "SyRS", "file": "SyRS.docx", "blocks": 2}, {"doc": "SyDS", "file": "SyDS.docx", "blocks": 1}]
    monkeypatch.setattr(tc, "load_system_requirements", fake)
    ref = _sts(tmp_path / "ref.xlsx", [("SwTC_1", "도어 500ms 이상 유지", "판정", "SwTR_0601")])
    report = ev.evaluate(BLOCK, ref, None, [("SyRS", "SyRS.docx"), ("SyDS", "SyDS.docx")])
    assert calls == [[("SyRS", "SyRS.docx"), ("SyDS", "SyDS.docx")]]
    assert report["cross_source"]["provenance_inputs"]["system_documents"] == [
        {"doc": "SyRS", "file": "SyRS.docx", "blocks": 2}, {"doc": "SyDS", "file": "SyDS.docx", "blocks": 1}]
    assert [i["provenance_where"] for i in report["recall"]["not_stated_in_srs"]] == [["SyDS SyII_06 · Description"]]
    assert report["cross_source"]["reference"]["by_provenance"]["cited_system"]["mutants"] == 3
    # (r2 I3) the block cites SyII_06 and SyTR_0602, both in the given documents
    inputs = report["cross_source"]["provenance_inputs"]
    assert (inputs["cited_id_mentions"], inputs["cited_ids_distinct"], inputs["cited_ids_not_in_system_documents"]) \
        == (2, 2, [])
    missing = ev.evaluate(BLOCK.replace("SyTR_0602", "SyTR_0999"), ref, None,
                          [("SyRS", "SyRS.docx"), ("SyDS", "SyDS.docx")])
    assert missing["cross_source"]["provenance_inputs"]["cited_ids_not_in_system_documents"] == ["SyTR_0999"]


def test_a_system_document_that_was_not_read_fails_the_run(tmp_path, monkeypatch):
    """(review W1) an unread document would move its thresholds to another class without a word."""
    import generators.sts_requirement_tc as tc
    monkeypatch.setattr(tc, "load_system_requirements", lambda docs: (
        {}, [{"doc": "SyRS", "file": "SyRS.docx", "error": "PackageNotFoundError: no such file"}]))
    ref = _sts(tmp_path / "ref.xlsx", [("SwTC_1", "도어 500ms 이상 유지", "판정", "SwTR_0601")])
    with pytest.raises(ev.InputError, match=re.escape("SyRS SyRS.docx: PackageNotFoundError")):
        ev.evaluate(BLOCK, ref, None, [("SyRS", "SyRS.docx")])
    monkeypatch.setattr(tc, "load_system_requirements", lambda docs: ({}, []))      # a pathless entry is skipped
    with pytest.raises(ev.InputError, match="no path"):
        ev.evaluate(BLOCK, ref, None, [("SyRS", None)])
    # (r2 I3) read without error but no requirement table in it (an SRS given as SyRS)
    monkeypatch.setattr(tc, "load_system_requirements", lambda docs: (
        {}, [{"doc": "SyRS", "file": "SRS.docx", "blocks": 0}]))
    with pytest.raises(ev.InputError, match=re.escape("no system requirement table found in: SyRS SRS.docx")):
        ev.evaluate(BLOCK, ref, None, [("SyRS", "SRS.docx")])


def test_the_documents_folder_fails_closed(tmp_path):
    """(review W1 · I3) an empty set would read every unmatched threshold as the tester's own choice."""
    with pytest.raises(ev.InputError, match="not a folder"):
        ev.load_documents(str(tmp_path / "missing"))
    with pytest.raises(ev.InputError, match=re.escape("no *.txt")):
        ev.load_documents(str(tmp_path))
    (tmp_path / "SyRS.txt").write_text("15도", encoding="utf-8")
    # not test specifications: ``sts`` inside a word, requirement ID prefixes, a part number (r2 I4)
    ok = ["Lists.txt", "SwTSR_0101 notes.txt", "SyTSR list.txt", "SwTR_0601.txt", "TC275_datasheet.txt",
          "Latest Specification.txt", "Status.txt"]                      # (r3 I5) ``test`` inside a word
    for name in ok:
        (tmp_path / name).write_text("9V", encoding="utf-8")
    assert sorted(ev.load_documents(str(tmp_path))) == sorted(ok + ["SyRS.txt"])
    for name in ("HDPDM01_STS_v1.txt", "hdpdm01_sts_v1.txt", "STSv1.txt", "(KJPDS02_SwTS) spec.txt", "SWTS.txt",
                 "KJ_SUTR.txt", "SwITR_v2.txt", "SW Test Spec.txt", "Test Report.txt", "TestCase list.txt",
                 "통합시험.txt", "x_TC.txt"):
        (tmp_path / name).write_text("1V", encoding="utf-8")
        with pytest.raises(ev.InputError, match="test specifications"):
            ev.load_documents(str(tmp_path))
        (tmp_path / name).unlink()
    (tmp_path / "blank.txt").write_text(" \n", encoding="utf-8")
    with pytest.raises(ev.InputError, match=re.escape("empty: blank.txt")):
        ev.load_documents(str(tmp_path))
    (tmp_path / "blank.txt").unlink()
    (tmp_path / "cp949.txt").write_bytes("전압".encode("cp949"))
    with pytest.raises(ev.InputError, match=re.escape("not UTF-8: cp949.txt")):
        ev.load_documents(str(tmp_path))


def test_the_cli_exits_2_on_an_input_it_cannot_read(tmp_path, capsys):
    srs = tmp_path / "srs.txt"
    srs.write_text(BLOCK, encoding="utf-8")
    ref = _sts(tmp_path / "ref.xlsx", [("SwTC_1", "차량 속도 3km/h 이상으로 주행", "정지", "SwTR_0601")])
    out = tmp_path / "r.json"
    base = ["--srs", str(srs), "--sts", ref, "--out", str(out)]
    assert ev.main(base + ["--docs-dir", str(tmp_path / "missing")]) == 2
    assert ev.main(base + ["--system-docx", "SyRS"]) == 2
    assert ev.main(base + ["--system-docx", "SyRS="]) == 2
    with pytest.raises(SystemExit) as no_value:                 # (r2 I3) the flag without a value is an error
        ev.main(base + ["--system-docx"])
    assert no_value.value.code == 2
    assert not out.exists()
    assert "error:" in capsys.readouterr().err
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "Func.txt").write_text("15도", encoding="utf-8")
    assert ev.main(base + ["--docs-dir", str(docs)]) == 0 and out.exists()
