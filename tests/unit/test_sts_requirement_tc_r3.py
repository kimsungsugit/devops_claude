"""R5/R6 review round 3 — sentence-scoped verdicts, outcome sections, reference labels, line continuations, monitored
quantities and predicates; the evaluator never lets a subject-less fact take any named point."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from generators.requirement_oracle import extract
from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import BASIS_MARK, append_requirement_boundary_tcs, boundary_steps

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requirement_oracle_eval as ev  # noqa: E402


def _req(desc, rid="SwTR_0202"):
    return {"id": rid, "name": "n", "description": desc, "verification": "", "asil": "B"}


def _build(**kw):
    return _build_tc_dict(test_env="SwTE_01", is_safety=False, derive_inputs=False, **kw)


def test_complementary_sentences_never_give_one_point_two_opposite_verdicts():
    # (review r3 C-1) ``3km/h 이하`` and ``3km/h 초과`` describe two behaviours — each step speaks for its sentence only
    groups = boundary_steps(_req("6. 차량 속도가 3km/h 이하인 상태에서 끼임 발생한 경우 동작 확인\n"
                                 "7. 차량 속도가 3km/h 초과한 상태에서 끼임 발생한 경우 동작 확인"))
    for g in groups:
        for s in g["steps"]:
            assert "요구 동작 미수행" not in s["expected"]
            assert ("이 문장이 기술한 동작 수행" in s["expected"]) != ("이 문장의 동작 대상 아님" in s["expected"])


def test_an_outcome_section_is_not_stimulated_and_a_reference_label_is_not_set():
    stats = Counter()
    groups = boundary_steps(_req("<Pre Condition>\n- u16s_A: 10 초과\n<완료조건>\n(s16g_Pos<=0) &&\n"
                                 "- 저 전압 고장 검출 기준 전압: 8.50V 이하"), stats)
    assert [g["evidence"]["signal"] for g in groups] == ["u16s_A"]
    assert stats["skipped:outcome_section"] == 2 and stats.get("skipped:reference_label", 0) == 0
    stats = Counter()
    assert boundary_steps(_req("- 저 전압 고장 검출 기준 전압: 8.50V 이하"), stats) == []
    assert stats["skipped:reference_label"] == 1


def test_a_condition_joined_to_the_next_line_says_so_and_gets_its_own_tc():
    reqs = [_req("- (u16g_MotorSpeed >= 15000) AND\n- u16s_T: 20 초과\n- u16s_Z: 5 초과")]
    tcs = []
    append_requirement_boundary_tcs(tcs, reqs, _build, _make_tc_id, _classify_steps)
    notes = [tc["precondition"] for tc in tcs]
    assert any("다음 줄 조건 [- u16s_T: 20 초과]과 AND 결합(원문): 성립 상태로 둔다" in n for n in notes)
    assert any("앞 줄 조건 [- (u16g_MotorSpeed >= 15000) AND]과 AND 결합(원문): 성립 상태로 둔다" in n for n in notes)
    # facts carrying such notes do not share a TC (their preconditions would contradict each other's steps)
    assert all(len(tc["requirement_evidence"]) == 1 for tc in tcs if "결합" in (tc["precondition"] or ""))


def test_a_function_word_after_a_parameter_threshold_is_not_its_subject():
    for text in ("- Param_X( 3도 ) 초과 시 경고", "- Param_X( 3도 ) 초과 후 정지", "- Param_X( 3도 ) 초과일 때 정지"):
        (req,) = extract("ID\tSwTR_0202\nName\tx\n" + text + "\n")
        (fact,) = req["lines"][0]["facts"]
        assert fact["monitored"] is None, text
    (req,) = extract("ID\tSwTR_0202\nName\tx\n4. Param_A( 3도 ) 이하의 도어 열림각에서 끼임\n")
    assert req["lines"][0]["facts"][0]["monitored"] == "도어 열림각"


def test_a_conditional_ending_is_not_a_state():
    (g,) = boundary_steps(_req("- 서브네트워크 통신이 60초 이상 중단되면 슬립 천이"))
    assert g["steps"][0]["action"].split(BASIS_MARK)[0].endswith("= 59초")


def test_a_fact_without_a_subject_is_not_killed_by_another_subjects_named_point(tmp_path):
    # (review r3 W4) the generator skipped ``Param_A( 3도 ) 이하`` (no monitored quantity); a point on 열림각 must not
    # count for it
    srs = "ID\tSwTR_0202\nName\tA\n3. Param_A( 3도 ) 초과한 열림각에서 끼임\n4. Param_A( 3도 ) 이하 시 무시\n"
    from test_requirement_oracle_eval import _sts
    gen = _sts(tmp_path / "g.xlsx", [("SwTC_9", "입력 설정 (요구 경계): 열림각 = 3도", "", "SwTR_0202"),
                                      ("", "입력 설정 (요구 경계): 열림각 = 4도", "", "")])
    d = ev.evaluate(srs, gen)["discrimination"]["reference"]
    assert all(m["killed_by_point"] is None for m in d["rows"] if m["signal"] is None)
    assert any(m["killed_by_point"] is not None for m in d["rows"] if m["signal"] == "열림각")
