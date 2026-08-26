"""시험 **결과** 보고서(SUTR/SITR)의 품질 평가 — 커버리지 평가기와 분리한 이유.

## 왜 이 테스트가 있나 (실측 2026-08-07)

### 1. 기록 자체가 없었다

`record_run` 호출이 SwUT/SwIT 라우터의 **coverage 경로에만** 있었다
(`_do_coverage_build` / `_do_swit_coverage_build`). SUTR·SITR 은 몇 번을 만들어도
Quality DB 에 행이 남지 않았고, 생성 현황 화면은 방금 만든 문서를 계속 "미생성"
으로 표시했다. 사용자가 볼 수 있는 증상은 "버튼을 눌러도 아무 일도 안 일어남" 인데
실제로는 파일이 만들어지고 있었다.

### 2. 커버리지 평가기에 넣으면 FAIL 을 **지어낸다**

두 산출물의 summary 스키마가 다르다:

    coverage : overall_statement_pct / overall_branch_pct / overall_mcdc_pct / total_tcs
    SUTR/SITR: total / tested / passed / failed / deviation_cases_written

`_safe_float` 는 없는 키를 `0.0` 으로 접는다. 그래서 SUTR summary 를
`evaluate_coverage` 에 넣으면 `statement_coverage_pct = 0.0 < 100` → **측정하지도
않은 축으로 FAIL**이 기록된다. 시험 결과 보고서는 커버리지 문서가 아니다.

### 3. 통과율 분모를 `tested` 로 두면 시험 공백이 은폐된다

문서의 Test Summary 시트는 `passed/tested` 를 찍는다. 그 값을 게이트로 쓰면
100개 중 10개만 실행하고 10개 다 통과했을 때 **통과율 100% · 게이트 통과**가 된다.
같은 결함을 `evaluate_coverage` 가 이미 겪었고(거기 주석 참조) 분모에 미실행을
포함하도록 고쳤다. 여기서도 같은 규약을 지킨다.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from workflow.quality.advisor import (  # noqa: E402
    _COMPREHENSIVE_ADVICE,
    _SWIT_COVERAGE_ADVICE,
    _SWUT_ADVICE,
    _TEST_RESULT_ADVICE,
)
from workflow.quality.db import get_session, init_db  # noqa: E402
from workflow.quality.evaluator import (  # noqa: E402
    evaluate_comprehensive_result,
    evaluate_coverage,
    evaluate_swit_coverage,
    evaluate_test_result,
)
from workflow.quality.models import GenerationRun  # noqa: E402
from workflow.quality.recorder import record_run, record_test_result_run  # noqa: E402

# 실제 SUTR 빌드 summary 의 부분집합 (swut_sutr_aggregator.py 의 dict 구성 그대로).
SUTR_SUMMARY = {
    "environments": 3,
    "total": 100,
    "tested": 80,
    "passed": 76,
    "failed": 4,
    "deviation_cases_written": 2,
    "test_log_rows_written": 80,
}

# 실제 SwUTCR 빌드 summary 의 부분집합 (`swut_comprehensive_aggregator.py` 의 dict 그대로).
# ⚠ **`total` 키가 없다** — 총 TC 는 `total_tcs` 다. 이 한 글자 차이가 아래 테스트의 전부다.
SWUTCR_SUMMARY = {
    "environments": 3,
    "total_tcs": 100,
    "tested": 80,
    "passed": 76,
    "failed": 4,
    "function_rows": 169,
    "swutcr_qualified_function_count": 150,
    "swutcr_raw_function_count": 169,
}


@pytest.fixture
def qdb():
    return pathlib.Path(tempfile.mkdtemp()) / "q.db"


def _by_name(metrics):
    return {m["metric_name"]: m for m in metrics}


# ── 1. 평가기 자체 ────────────────────────────────────────────────────────

def test_gates_execution_and_pass_rate():
    m = _by_name(evaluate_test_result(SUTR_SUMMARY))
    # 80/100 실행, 76/100 통과 — 둘 다 100% 임계라 FAIL.
    assert m["test_execution_pct"]["value"] == 80.0
    assert m["test_execution_pct"]["gate_pass"] is False
    assert m["pass_rate_pct"]["value"] == 76.0
    assert m["pass_rate_pct"]["gate_pass"] is False


def test_pass_rate_denominator_is_total_not_tested():
    """미실행을 분모에서 빼면 '10개만 돌리고 100% 통과' 가 만들어진다."""
    m = _by_name(evaluate_test_result(
        {"total": 100, "tested": 10, "passed": 10, "failed": 0},
    ))
    assert m["pass_rate_pct"]["value"] == 10.0        # 100.0 이면 시험 공백 은폐
    assert m["pass_rate_pct"]["gate_pass"] is False
    # 문서에 찍히는 값(실행분 통과율)은 100% 가 맞다 — 다만 **비게이트**여야 한다.
    assert m["executed_pass_rate_pct"]["value"] == 100.0
    assert m["executed_pass_rate_pct"]["gate_pass"] is None


def test_deviation_is_not_scored():
    """편차는 ISO 26262 상 audit reviewer 판단 — 자동 판정 대상이 아니다."""
    m = _by_name(evaluate_test_result(SUTR_SUMMARY))
    assert m["deviation_cases"]["value"] == 2.0
    assert m["deviation_cases"]["threshold"] is None
    assert m["deviation_cases"]["gate_pass"] is None


def test_no_coverage_axis_is_fabricated():
    """음성 대조군 — 커버리지 축이 **아예 없어야** 한다.

    같은 summary 를 커버리지 평가기에 넣으면 0% FAIL 이 만들어지는 걸 함께 보여,
    이 분리가 무엇을 막고 있는지 테스트가 스스로 증명하게 한다.
    """
    ours = _by_name(evaluate_test_result(SUTR_SUMMARY))
    for axis in ("statement_coverage_pct", "branch_coverage_pct", "mcdc_coverage_pct"):
        assert axis not in ours

    wrong = _by_name(evaluate_coverage(SUTR_SUMMARY))
    assert wrong["statement_coverage_pct"]["value"] == 0.0
    assert wrong["statement_coverage_pct"]["gate_pass"] is False


def test_zero_total_does_not_become_full_marks():
    """0/0 을 100% 로 접지 않는다."""
    m = _by_name(evaluate_test_result({"total": 0, "tested": 0, "passed": 0}))
    assert m["test_execution_pct"]["value"] == 0.0
    assert m["pass_rate_pct"]["value"] == 0.0


# ── 2. recorder 배선 ──────────────────────────────────────────────────────

def test_recorded_run_uses_test_result_metrics(qdb):
    run_id = record_run("sutr", SUTR_SUMMARY, project_root="HDPDM01", db_path=qdb)
    assert run_id > 0
    init_db(qdb)
    with get_session(qdb) as s:
        run = s.query(GenerationRun).filter_by(id=run_id).one()
        names = {sc.metric_name for sc in run.scores}
        assert "test_execution_pct" in names
        assert "statement_coverage_pct" not in names   # 커버리지로 채점되지 않았다
        assert run.summary.gate_pass is False
        # 분모는 함수가 아니라 TC 수 — else 분기(total_test_cases)로 새면 0 이 된다.
        assert run.summary.fn_count == 100


def test_empty_output_is_skipped_by_total_key(qdb):
    """`total_tcs`(커버리지 키)로 판정하면 **모든** SUTR 이 빈 산출물로 skip 된다."""
    assert record_run("sutr", {"total": 0, "tested": 0}, db_path=qdb) == -1
    # 비지 않았으면 기록돼야 한다 — skip 조건이 과하게 넓지 않은지 확인.
    assert record_run("sutr", {"total": 5, "tested": 5, "passed": 5}, db_path=qdb) > 0


def test_helper_stamps_kind_and_project(qdb):
    run_id = record_test_result_run(
        "sitr", SUTR_SUMMARY,
        project_id="KJPDS02", asil_level="ASIL B", release_sw_version="1.02",
        db_path=qdb,
    )
    assert run_id > 0
    init_db(qdb)
    with get_session(qdb) as s:
        run = s.query(GenerationRun).filter_by(id=run_id).one()
        assert run.doc_type == "sitr"
        assert run.project_root == "KJPDS02"
        import json
        meta = json.loads(run.meta_json or "{}")
        assert meta["kind"] == "sitr"
        assert meta["release_sw_version"] == "1.02"


# ── 3. advisor 배선 ──────────────────────────────────────────────────────

def test_advice_table_is_not_the_coverage_one():
    """'커버리지를 올려라' 는 SUTR 에 줄 조치가 아니다."""
    assert _TEST_RESULT_ADVICE is not _SWUT_ADVICE
    assert "test_execution_pct" in _TEST_RESULT_ADVICE
    assert "statement_coverage_pct" not in _TEST_RESULT_ADVICE


def test_advice_reaches_sutr_runs(qdb):
    from workflow.quality.advisor import suggest_improvements
    run_id = record_run("sutr", SUTR_SUMMARY, project_root="HDPDM01", db_path=qdb)
    out = suggest_improvements(run_id, db_path=qdb)
    metrics = {s["metric"] for s in (out.get("suggestions") or [])}
    # 실행률·통과율 둘 다 미달이므로 제안이 나와야 한다(빈 제안 = 배선 누락).
    assert "test_execution_pct" in metrics


# ── 4. 종합결과서(SwUTCR/SwITCR) — **분모 키가 또 다르다** ────────────────────
#
# 이 저장소가 같은 함정에 두 번 빠졌다. 1차는 위 §2(커버리지 평가기에 SUTR 을 넣어
# 측정하지 않은 축으로 FAIL 을 지어냄), 2차가 여기다: SUTR 평가기에 종합결과서를
# 넣으면 분모(`total`)가 없어 `_safe_float` 가 0 으로 접고, `max(total, 1.0)` 때문에
# **tested 값이 그대로 백분율**이 된다. FAIL 을 지어내는 것보다 나쁘다 — 게이트가
# 100% 를 훌쩍 넘겨 통과하므로 **아무도 이상을 못 느낀다.**


def test_comprehensive_denominator_is_total_tcs():
    m = _by_name(evaluate_comprehensive_result(SWUTCR_SUMMARY))
    # 100 개 중 80 개 실행 → 80%. 분모를 `total` 로 바꾸면 8000.0 이 되어 여기서 죽는다.
    assert m["test_execution_pct"]["value"] == 80.0
    assert m["pass_rate_pct"]["value"] == 76.0
    # 문서 Summary 시트 표기값은 실행분 기준 — 두 축을 함께 보여야 공백이 드러난다.
    assert m["executed_pass_rate_pct"]["value"] == 95.0


def test_sutr_evaluator_on_comprehensive_summary_is_absurd():
    """**음성 대조군** — 왜 평가기를 나눴는지 수치로 못 박는다.

    이 단언이 깨졌다면 `evaluate_test_result` 가 `total_tcs` 폴백을 얻은 것이다.
    그건 개선이 아니라 두 산출물이 같은 스키마라는 잘못된 신호다 — 나눈 이유가
    분모만이 아니기 때문이다(종합결과서는 커버리지 축까지 함께 담는 다른 문서다).
    """
    m = _by_name(evaluate_test_result(SWUTCR_SUMMARY))
    assert m["test_execution_pct"]["value"] == 8000.0


def test_comprehensive_scale_metrics_are_not_gated():
    """규모(함수 수·환경 수)는 프로젝트에 비례하는 절대수 — hard-fail 부적합."""
    by_name = _by_name(evaluate_comprehensive_result(SWUTCR_SUMMARY))
    assert by_name["qualified_function_count"]["value"] == 150.0
    for name in ("qualified_function_count", "function_rows", "environments",
                 "total_tcs", "tested_tcs", "failed_tcs"):
        assert by_name[name]["threshold"] is None, name
    # 게이트 축은 둘뿐이다 — 늘리면 여기서 알아차린다.
    gated = {x["metric_name"] for x in evaluate_comprehensive_result(SWUTCR_SUMMARY)
             if x["threshold"] is not None}
    assert gated == {"test_execution_pct", "pass_rate_pct"}


def test_comprehensive_absent_function_count_is_not_zero():
    """없는 축을 0 으로 채우면 '함수 0개' 라는 **없는 사실**을 보고하게 된다."""
    summary = {k: v for k, v in SWUTCR_SUMMARY.items()
               if k not in ("swutcr_qualified_function_count", "swutcr_raw_function_count")}
    names = {x["metric_name"] for x in evaluate_comprehensive_result(summary)}
    assert "qualified_function_count" not in names


def test_switcr_uses_its_own_function_count_key():
    """SwITCR 은 키 이름이 다르다(`switcr_*`) — 한쪽만 보면 SwIT 축이 통째로 빈다."""
    summary = dict(SWUTCR_SUMMARY)
    del summary["swutcr_qualified_function_count"]
    del summary["swutcr_raw_function_count"]
    summary["switcr_qualified_function_count"] = 88
    m = _by_name(evaluate_comprehensive_result(summary))
    assert m["qualified_function_count"]["value"] == 88.0


def test_recorder_dispatches_comprehensive_doc_types(qdb):
    for doc_type in ("swutcr", "switcr"):
        run_id = record_run(doc_type, SWUTCR_SUMMARY, project_root="HDPDM01", db_path=qdb)
        assert run_id > 0, doc_type
        init_db(qdb)
        with get_session(qdb) as s:
            run = s.query(GenerationRun).filter_by(id=run_id).one()
            scores = {sc.metric_name: sc.value for sc in run.scores}
            assert scores["test_execution_pct"] == 80.0, doc_type
            # 커버리지로도 SUTR 로도 채점되지 않았다.
            assert "statement_coverage_pct" not in scores, doc_type
            # 규모 분모는 TC 수다. `total` 키를 보면 0 이 되어 **규모 0 인 실행**처럼 보인다.
            assert run.summary.fn_count == 100, doc_type


def test_comprehensive_empty_output_is_skipped_by_total_tcs(qdb):
    """빈 산출물 skip 도 같은 키를 봐야 한다 — `total` 을 보면 **전부** skip 된다."""
    assert record_run("swutcr", {"total_tcs": 0, "tested": 0}, db_path=qdb) == -1
    assert record_run("switcr", {"total_tcs": 0, "tested": 0}, db_path=qdb) == -1
    # 과하게 넓지 않은지 — 비지 않은 것은 기록돼야 한다.
    assert record_run("swutcr", {"total_tcs": 5, "tested": 5, "passed": 5}, db_path=qdb) > 0


def test_comprehensive_advice_table_is_its_own():
    """SUTR 표를 재사용하면 조치문이 틀린다 — 종합결과서의 미실행은 '로그를 더 모아라'
    가 아니라 '어느 레벨 산출물이 비었는가' 로 되짚어야 한다."""
    assert _COMPREHENSIVE_ADVICE is not _TEST_RESULT_ADVICE
    assert _COMPREHENSIVE_ADVICE is not _SWUT_ADVICE
    assert "test_execution_pct" in _COMPREHENSIVE_ADVICE
    assert "statement_coverage_pct" not in _COMPREHENSIVE_ADVICE


def test_advice_reaches_comprehensive_runs(qdb):
    """doc_type 분기가 없으면 advisor 가 '규칙이 정의되지 않았습니다' 로 답한다."""
    from workflow.quality.advisor import suggest_improvements
    run_id = record_run("swutcr", SWUTCR_SUMMARY, project_root="HDPDM01", db_path=qdb)
    out = suggest_improvements(run_id, db_path=qdb)
    metrics = {s["metric"] for s in (out.get("suggestions") or [])}
    assert "test_execution_pct" in metrics
    assert "정의되지 않았습니다" not in (out.get("summary") or "")


# ── SwITCV — 커버리지 문서지만 **구문/분기 문서는 아니다** ────────────────────
# 2026-08-26 KJPDS02 PV 실측: 빌더가 statement/branch 를 O/X 표식으로 덮어쓰므로
# roll-up 은 늘 None 이고, evaluate_coverage 에 넣으면 0% 영구 FAIL 이 된다.
SWITCV_SUMMARY = {
    "environments": 45,
    "total_tcs": 611, "passed": 611, "failed": 0,
    "function_rows": 1014,
    "overall_statement_pct": None, "overall_branch_pct": None, "overall_mcdc_pct": None,
    "measured_functions": {"statement": 0, "branch": 0, "mcdc": 0},
    "synthesized_rows": 1014,
    "vcast_raw_statement_pct": 31.59, "vcast_raw_branch_pct": 26.54,
    "vcast_raw_measured_functions": 712,
    "swit_functions_total": 1014, "swit_functions_achieved": 1010, "swit_functions_fail": 4,
    "swit_function_calls_functions": 590, "swit_function_calls_na_functions": 424,
    "swit_function_calls_covered": 1643, "swit_function_calls_total": 1678,
    "swit_function_calls_fail_functions": 21,
}


def test_recorder_splits_swit_from_swut(qdb):
    """swut 은 실측 구문 커버리지를 내고 swit 은 안 낸다 — 같은 평가기를 쓰면 안 된다."""
    run_id = record_run("swit", SWITCV_SUMMARY, project_root="KJPDS02", db_path=qdb)
    assert run_id > 0
    init_db(qdb)
    with get_session(qdb) as s:
        run = s.query(GenerationRun).filter_by(id=run_id).one()
        scores = {sc.metric_name: sc.value for sc in run.scores}
        gated = {sc.metric_name for sc in run.scores if sc.threshold is not None}
    # 문서 자신의 축으로 채점한다.
    assert scores["function_achievement_pct"] == 99.61
    assert scores["function_call_coverage_pct"] == 97.91
    # 재지도 않은 축은 아예 기록되지 않는다(0.0 으로도 남기지 않는다).
    assert "statement_coverage_pct" not in scores
    assert "mcdc_coverage_pct" not in scores
    assert gated == {"function_achievement_pct", "function_call_coverage_pct", "pass_rate_pct"}


def test_swut_still_uses_the_coverage_evaluator(qdb):
    """과잉 분기 방지 — SwUTCV 는 진짜 구문 커버리지를 내므로 그대로 채점돼야 한다."""
    run_id = record_run(
        "swut",
        {"overall_statement_pct": 99.45, "overall_branch_pct": 95.0,
         "measured_functions": {"statement": 1014}, "synthesized_rows": 0,
         "passed": 10, "failed": 0, "total_tcs": 10},
        project_root="KJPDS02", db_path=qdb,
    )
    assert run_id > 0
    init_db(qdb)
    with get_session(qdb) as s:
        run = s.query(GenerationRun).filter_by(id=run_id).one()
        scores = {sc.metric_name: sc.value for sc in run.scores}
    assert scores["statement_coverage_pct"] == 99.45
    assert "function_achievement_pct" not in scores


def test_swit_advice_table_is_its_own():
    """SwUT 표를 재사용하면 '구문 커버리지가 100% 미만입니다' 라는 틀린 조치가 나간다."""
    assert _SWIT_COVERAGE_ADVICE is not _SWUT_ADVICE
    assert "function_achievement_pct" in _SWIT_COVERAGE_ADVICE
    assert "statement_coverage_pct" not in _SWIT_COVERAGE_ADVICE


def test_advice_reaches_swit_runs(qdb):
    """doc_type 분기가 없으면 advisor 가 '규칙이 정의되지 않았습니다' 로 답한다."""
    from workflow.quality.advisor import suggest_improvements
    run_id = record_run("swit", SWITCV_SUMMARY, project_root="KJPDS02", db_path=qdb)
    out = suggest_improvements(run_id, db_path=qdb)
    metrics = {s["metric"] for s in (out.get("suggestions") or [])}
    assert "function_achievement_pct" in metrics
    assert "정의되지 않았습니다" not in (out.get("summary") or "")


def test_swit_gate_would_have_been_unfixable_before():
    """가드가 헛돌지 않음을 보인다 — 옛 경로로는 어떤 시험을 더 해도 FAIL 이다."""
    old = {m["metric_name"]: m for m in evaluate_coverage(SWITCV_SUMMARY)}
    assert old["statement_coverage_pct"]["gate_pass"] is False
    # 함수 달성/호출을 100% 로 만들어도 옛 평가기는 여전히 FAIL 이다.
    perfect = {**SWITCV_SUMMARY, "swit_functions_achieved": 1014,
               "swit_function_calls_covered": 1678}
    still = {m["metric_name"]: m for m in evaluate_coverage(perfect)}
    assert still["statement_coverage_pct"]["gate_pass"] is False
    # 새 평가기에서는 통과한다.
    now = [m for m in evaluate_swit_coverage(perfect) if m["threshold"] is not None]
    assert now and all(m["gate_pass"] for m in now)
