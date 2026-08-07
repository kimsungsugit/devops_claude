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

from workflow.quality.advisor import _SWUT_ADVICE, _TEST_RESULT_ADVICE  # noqa: E402
from workflow.quality.db import get_session, init_db  # noqa: E402
from workflow.quality.evaluator import evaluate_coverage, evaluate_test_result  # noqa: E402
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
