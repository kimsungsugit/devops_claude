"""R55 — which side the given documents take where the generated step's verdict is the mutant's.

The cross scoring (R32) does not credit a separation against the step's verdict: the step expects the mutant's verdict
at that point. HDPDM01 has 12 such killable mutants and every one sits where **every given document** (the SRS block and
the SyRS/SyDS blocks its Related ID names) writes ``초과`` and the reference writes ``이상`` (``1.3m/s`` · ``500ms`` ·
``300ms``) — the suite follows the documents, the reference differs from them. The scorer now says so per mutant, and
says the other side too: the documents write the reference's inclusion (read the step — our error candidate), both
(the documents conflict), neither (another value), or the point is not the threshold itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import requirement_oracle_eval as ev  # noqa: E402


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


REF = [("SwTC_1", "도어 1.3m/s 이상으로 열림", "정지", "SwTR_0203")]
STEP_EXCLUSIVE = [("SwTC_9", "입력 설정 (요구 경계): 도어속도 = 1.3m/s 설정",
                   "조건 [도어속도 1.3m/s 초과] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0203")]


def _block(line: str, related: str = "") -> str:
    return "ID\tSwTR_0203\nName\tSlam\n" + line + "\n" + (f"Related ID\t{related}\n" if related else "")


def _score(tmp_path, block, system=None, ref_rows=REF, gen_rows=STEP_EXCLUSIVE):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ref =ev.read_sts(_sts(tmp_path / "ref.xlsx", ref_rows))
    gen = ev.read_sts(_sts(tmp_path / "gen.xlsx", gen_rows))
    ms, _excluded = ev.reference_mutants(ref, {"SwTR_0203": block}, None, system, None)
    return ev.cross_discrimination(ms, gen)


def _classes(d):
    return {c: n for c, n in d["killable_against_verdict_by_documents"]["classes"].items() if n}


def test_the_documents_write_the_steps_inclusion(tmp_path):
    """HDPDM01 SwTR_0203: the SRS ``1.3m/s 초과``, the reference ``1.3m/s 이상`` — the step follows the SRS."""
    d = _score(tmp_path, _block("(슬램모드: 도어속도 1.3m/s 초과)"))
    assert d["killed"] == 0 and d["separated_against_verdict"] == 2           # ``> 1.3`` and ``>= 1.4``, both at 1.3
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
    assert d["killable_against_verdict_by_documents"]["scope"] == ["srs_only"]
    rows = [r for r in d["rows"] if r["killable"]]
    assert {r["against_verdict_documents"] for r in rows} == {"documents_write_the_steps_inclusion"}
    assert rows[0]["written_at_value"] == ["1.3m/s 초과 (SRS)"]


def test_the_documents_write_the_references_inclusion_is_a_step_to_read(tmp_path):
    d = _score(tmp_path, _block("- 도어속도 1.3m/s 이상 시 정지"))
    assert _classes(d) == {"documents_write_the_references_inclusion": 2}


def test_a_cited_block_is_read_and_a_conflict_is_its_own_class(tmp_path):
    system = {"SyTR_0602": {"doc": "SyRS", "fields": {"Description": "슬램모드: 도어속도 1.3m/s 초과"}}}
    d = _score(tmp_path, _block("- 도어 감속", "SyTR_0602"), system)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
    assert d["killable_against_verdict_by_documents"]["scope"] == ["srs_and_cited_system"]
    assert [r for r in d["rows"] if r["killable"]][0]["written_at_value"] == ["1.3m/s 초과 (SyRS SyTR_0602 · Description)"]
    # the SRS writes the reference's inclusion and the cited block the step's: the documents conflict
    d = _score(tmp_path / "c", _block("- 도어속도 1.3m/s 이상 시 정지", "SyTR_0602"), system)
    assert _classes(d) == {"documents_disagree": 2}
    # a block the requirement does not cite is not read
    d = _score(tmp_path / "n", _block("- 도어 감속"), system)
    assert _classes(d) == {"not_written": 2}


def test_only_the_references_direction_counts_and_a_number_needs_its_unit(tmp_path):
    """``1.3m/s 이하`` (an upper bound — another condition: ``정상 속도``) says nothing of the lower bound's inclusion;
    ``1.3`` without its unit is not the quantity; ``13m/s`` is another value."""
    d = _score(tmp_path, _block("- 정상: 도어속도 1.3m/s 이하 · 계수 1.3 이상 · 13m/s 초과"))
    assert _classes(d) == {"not_written": 2}
    assert [r for r in d["rows"] if r["killable"]][0]["written_at_value"] == ["1.3m/s 이하 (SRS)"]


def test_a_point_off_the_threshold_says_nothing_of_its_inclusion(tmp_path):
    """The reference ``16V 이상``; the step at 16.5V judges ``16.8V 이상`` (불성립) — against the ``>= 17`` mutant's
    original verdict there, but not at the threshold."""
    ref = [("SwTC_1", "전원 16V 이상 인가", "", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): 전원 = 16.5V 설정",
            "조건 [전원 16.8V 이상] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0203")]
    d = _score(tmp_path, _block("- 전원 16V 초과 시"), ref_rows=ref, gen_rows=gen)
    assert _classes(d) == {"off_the_threshold": 1}


def test_the_classes_count_exactly_the_killable_mutants_separated_against_the_verdict(tmp_path):
    """The same mutants as by_provenance's killable_against_verdict — every class listed, 0 is a count; a mutant
    another point kills is in no class."""
    system = {"SyTR_0602": {"doc": "SyRS", "fields": {"Description": "슬램모드: 도어속도 1.3m/s 초과"}}}
    d = _score(tmp_path, _block("- 도어 감속", "SyTR_0602"), system)
    assert list(d["killable_against_verdict_by_documents"]["classes"]) == list(ev.AGAINST_VERDICT_CLASSES)
    assert sum(d["killable_against_verdict_by_documents"]["classes"].values()) == \
        sum(c["killable_against_verdict"] for c in d["by_provenance"].values())
    killing = STEP_EXCLUSIVE + [("", "입력 설정 (요구 경계): 도어속도 = 1.3m/s 설정",
                                 "조건 [도어속도 1.3m/s 이상] 성립 → 이 문장이 기술한 동작 수행 확인: …", "")]
    d = _score(tmp_path / "k", _block("(도어속도 1.3m/s 초과)"), gen_rows=killing)
    assert d["killed"] == 2 and d["separated_against_verdict"] == 0 and _classes(d) == {}
    # a suite whose steps state no verdict (the reference itself) is not measured: no zeros that read as counts
    ref = ev.read_sts(_sts(tmp_path / "u.xlsx", REF))
    ms, _excluded = ev.reference_mutants(ref, {"SwTR_0203": _block("(도어속도 1.3m/s 초과)")})
    assert ev.cross_discrimination(ms, ref, self_sourced=True)["killable_against_verdict_by_documents"] is None


def test_the_first_point_against_the_verdict_is_the_one_classed(tmp_path):
    """Two points separate ``>= 1.4`` against the verdict — 1.3 (the threshold) and 1.35 (off it): the row and its class
    keep the first, as `separated_against_verdict` always has."""
    gen = STEP_EXCLUSIVE + [("", "입력 설정 (요구 경계): 도어속도 = 1.35m/s 설정",
                             "조건 [도어속도 1.4m/s 이상] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "")]
    d = _score(tmp_path, _block("(슬램모드: 도어속도 1.3m/s 초과)"), gen_rows=gen)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
    shift = next(r for r in d["rows"] if r["mutant"] == "value_shift" and r["killable"])
    assert shift["separated_against_verdict"] == 1.3 and shift["against_verdict_documents"] == \
        "documents_write_the_steps_inclusion"


def test_an_unkillable_mutant_is_in_no_class(tmp_path):
    """(R44 r2 I2) ``15도 미만`` at 15 with a step saying 성립: the widening mutants separate there against the verdict
    but no point could kill them — they are no missed kill, so no class counts them (the row still says its side)."""
    ref = [("SwTC_1", "팝업 15도 미만으로 수동 조작", "상태", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): 팝업 = 15도 설정", "조건 [팝업 15도 이하] 성립 → …", "SwTR_0203")]
    d = _score(tmp_path, _block("- 팝업 15도 이하에서 수동"), ref_rows=ref, gen_rows=gen)
    assert d["separated_against_verdict"] == 2 and _classes(d) == {}
    assert [r["against_verdict_documents"] for r in d["rows"] if not r["killable"]] == \
        ["documents_write_the_steps_inclusion"] * 2


def test_a_point_in_another_time_unit_is_placed_on_the_threshold(tmp_path):
    """(review W3a) the step's point in seconds against the reference's milliseconds: 0.3 s is the threshold 300 ms."""
    ref = [("SwTC_1", "LIN 이상 300ms 이상 유지", "", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): 조건 지속 시간 = 0.3s 설정",
            "조건 [조건 지속 시간 0.3s 초과] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0203")]
    d = _score(tmp_path, _block("- LIN 통신 이상으로 특정시간(300ms) 초과하여 유지되는 경우"), ref_rows=ref, gen_rows=gen)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}


def test_a_comparison_written_twice_in_one_place_is_listed_once(tmp_path):
    """(review W3b)"""
    d = _score(tmp_path, _block("(슬램모드: 도어속도 1.3m/s 초과) · 재확인 (슬램모드: 도어속도 1.3m/s 초과)"))
    assert [r for r in d["rows"] if r["killable"]][0]["written_at_value"] == ["1.3m/s 초과 (SRS)"]


def test_given_but_empty_system_documents_are_a_scope_examined(tmp_path):
    """(review W3c) ``{}`` is "system documents given" (none of their blocks cited) — not "not given"."""
    d = _score(tmp_path, _block("(슬램모드: 도어속도 1.3m/s 초과)"), {})
    assert d["killable_against_verdict_by_documents"]["scope"] == ["srs_and_cited_system"]


def test_a_killed_row_carries_no_class(tmp_path):
    """(review W1) a row a point on the original's side decides is no separation against the verdict: the row says so
    as the headline does (HDPDM01 had 13 killed rows labelled, 8 of them 'the reference's inclusion')."""
    killing = STEP_EXCLUSIVE + [("", "입력 설정 (요구 경계): 도어속도 = 1.3m/s 설정",
                                 "조건 [도어속도 1.3m/s 이상] 성립 → 이 문장이 기술한 동작 수행 확인: …", "")]
    d = _score(tmp_path, _block("(도어속도 1.3m/s 초과)"), gen_rows=killing)
    killed = [r for r in d["rows"] if r["killed_by_point"] is not None]
    assert len(killed) == 2 and all(r["separated_against_verdict"] == 1.3 for r in killed)
    assert {r["against_verdict_documents"] for r in killed} == {None}


def test_an_upper_bound_reads_a_written_mi_man_and_a_point_below_it_is_off_the_threshold(tmp_path):
    """(review r2 W1) KJPDS02_PV SwTR_0605: the SRS ``8.9V 미만``, the reference ``8.9V 이하`` — the documents' side; and
    a point below an upper-bound threshold (14.5 for ``15도 이하``) says nothing of its inclusion."""
    ref = [("SwTC_1", "B+ 8.9V 이하 인가", "", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): B+ 전압 = 8.9V 설정",
            "조건 [B+ 전압 8.9V 미만] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0203")]
    d = _score(tmp_path, _block("- B+ 전압이 8.9V 미만일 경우 명령 무시"), ref_rows=ref, gen_rows=gen)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
    ref = [("SwTC_1", "팝업 15도 이하로 수동 조작", "", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): 팝업 = 14.5도 설정", "조건 [팝업 14도 이하] 불성립 → …", "SwTR_0203")]
    d = _score(tmp_path / "o", _block("- 팝업 15도 미만에서 수동"), ref_rows=ref, gen_rows=gen)
    assert _classes(d) == {"off_the_threshold": 1}


def test_written_forms_hex_space_and_two_places(tmp_path):
    """(review r2 I4) ``500ms (0x1F4) 초과`` · ``1.3 m/s 초과`` read as written; the same text in the SRS and in a cited
    block is listed for each place."""
    ref = [("SwTC_1", "지속 500ms 이상 유지", "", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): 조건 지속 시간 = 500ms 설정",
            "조건 [조건 지속 시간 500ms 초과] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0203")]
    d = _score(tmp_path, _block("- 지속 시간 500ms (0x1F4) 초과 시"), ref_rows=ref, gen_rows=gen)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
    system = {"SyTR_0602": {"doc": "SyRS", "fields": {"Description": "슬램모드: 도어속도 1.3 m/s 초과"}}}
    d = _score(tmp_path / "s", _block("(슬램모드: 도어속도 1.3 m/s 초과)", "SyTR_0602"), system)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
    assert [r for r in d["rows"] if r["killable"]][0]["written_at_value"] == \
        ["1.3 m/s 초과 (SRS)", "1.3 m/s 초과 (SyRS SyTR_0602 · Description)"]


def test_a_value_in_another_time_unit_is_the_same_quantity(tmp_path):
    ref = [("SwTC_1", "LIN 이상 300ms 이상 유지", "", "SwTR_0203")]
    gen = [("SwTC_9", "입력 설정 (요구 경계): 조건 지속 시간 = 300ms 설정",
            "조건 [조건 지속 시간 300ms 초과] 불성립 → 이 문장이 기술한 동작 미수행 확인: …", "SwTR_0203")]
    d = _score(tmp_path, _block("- LIN 통신 이상으로 특정시간(0.3s) 초과하여 유지되는 경우"), ref_rows=ref, gen_rows=gen)
    assert _classes(d) == {"documents_write_the_steps_inclusion": 2}
