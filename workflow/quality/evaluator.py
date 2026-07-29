"""Quality evaluators for UDS, STS, SUTS documents."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("workflow.quality.evaluator")

MetricResult = Dict[str, Any]  # {"metric_name": str, "value": float, "gate_pass": bool|None, "threshold": float|None}
MetricList = List[MetricResult]


def _metric(name: str, value: float, *, threshold: Optional[float] = None) -> MetricResult:
    """단일 메트릭 dict 생성."""
    gate_pass = None
    if threshold is not None:
        gate_pass = value >= threshold
    return {
        "metric_name": name,
        "value": round(value, 2),
        "gate_pass": gate_pass,
        "threshold": threshold,
    }


def _safe_float(d: Any, key: str, default: float = 0.0) -> float:
    """dict에서 안전하게 float 추출."""
    if not isinstance(d, dict):
        return default
    v = d.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_uds(quality_eval: Dict[str, Any]) -> MetricList:
    """_build_quality_evaluation() 반환 dict -> MetricList.

    Args:
        quality_eval: UDS 품질 평가 dict. quick_gate.fields, accuracy 등 포함.
    """
    metrics: MetricList = []

    try:
        import config
        thresholds = getattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {})
    except Exception:
        thresholds = {}

    quick_gate = quality_eval.get("quick_gate") or {}
    # 실제 생산자 backend._compute_quick_quality_gate 는 quick_gate.rates.*_fill(0~100)
    # 형태로 산출한다. 과거 코드는 quick_gate.fields.*_pct 를 읽었으나 그 구조를 만드는
    # 생산자가 없어 dead path 였다(연결 시 전 함수 0점 기록 위험). rates 우선·fields 폴백.
    rates = quick_gate.get("rates") or {}
    legacy_fields = quick_gate.get("fields") or {}

    def _rate_val(rate_key: str, metric_name: str) -> float:
        # 실제 rates.*_fill 우선, 레거시 fields.*_pct 폴백.
        return _safe_float(rates, rate_key) if rate_key in rates else _safe_float(legacy_fields, metric_name)

    # 게이트·점수 반영 핵심 7필드 — backend quick_gate.gate_pass 기준과 정렬 (T5 진실원 통일).
    # (메트릭명=_pct, 실제 rates 키=_fill, config threshold 키=_min)
    gated_mappings = [
        ("called_pct", "called_fill", "called_min"),
        ("calling_pct", "calling_fill", "calling_min"),
        ("input_pct", "input_fill", "input_min"),
        ("output_pct", "output_fill", "output_min"),
        ("description_pct", "description_fill", "description_min"),
        ("asil_pct", "asil_fill", "asil_min"),
        ("related_pct", "related_fill", "related_min"),
    ]
    for metric_name, rate_key, threshold_key in gated_mappings:
        metrics.append(_metric(metric_name, _rate_val(rate_key, metric_name),
                               threshold=thresholds.get(threshold_key)))

    # 참고지표 — quick_gate 도 게이트에서 제외. 전역/정적 변수 적은 정상 모듈의 구조적
    # 저평가를 막기 위해 값은 기록하되 threshold=None → overall_score/gate 미반영.
    for metric_name, rate_key in (("global_pct", "global_fill"), ("static_pct", "static_fill")):
        metrics.append(_metric(metric_name, _rate_val(rate_key, metric_name)))

    # Accuracy 메트릭
    accuracy = quality_eval.get("accuracy") or {}
    for acc_key in ["called_pct", "calling_pct"]:
        acc_val = _safe_float(accuracy, acc_key)
        if acc_val > 0:
            metrics.append(_metric(f"accuracy_{acc_key}", acc_val))

    # Gate pass 메트릭
    metrics.append(
        _metric("gate_pass", 100.0 if quality_eval.get("gate_pass") else 0.0),
    )
    metrics.append(
        _metric("confidence_gate_pass", 100.0 if quality_eval.get("confidence_gate_pass") else 0.0),
    )

    return metrics


def evaluate_sts(quality_report: Dict[str, Any]) -> MetricList:
    """generators/sts.py generate_quality_report() 반환 dict -> MetricList.

    Args:
        quality_report: STS 품질 리포트 dict.
    """
    metrics: MetricList = []

    total = _safe_float(quality_report, "total_test_cases")

    # 완성도
    metrics.append(
        _metric("completeness_pct", _safe_float(quality_report, "completeness_pct"), threshold=80.0),
    )

    # 안전 TC 비율
    safety = _safe_float(quality_report, "safety_test_cases")
    safety_pct = round(safety / max(total, 1) * 100, 2)
    metrics.append(_metric("safety_tc_pct", safety_pct))

    # 요구사항 커버리지 — 검증방법을 가리지 않은 값(= ID 연결률). 게이트는 이 축을 유지한다
    # (지표 라벨·조언이 "요구사항 ID와 연결되지 않은 TC" 를 말하므로 의미가 맞다).
    req_cov = quality_report.get("requirement_coverage") or {}
    cov_pct = _safe_float(req_cov, "covered_pct", default=_safe_float(req_cov, "pct"))
    metrics.append(_metric("requirement_coverage_pct", cov_pct, threshold=70.0))

    # 실행 시험 기준 커버리지 — **비게이트**(현 pass/fail 을 바꾸지 않기 위해).
    # 위 값은 코드 리뷰(RVW)로만 덮인 요구도 포함하므로 둘이 갈린다.
    # 실측: 소스 함수를 하나도 못 잡은 경우 위 값은 100.0%, 이 값은 57.1%(27건이 리뷰만).
    # 즉 게이트 통과 여부를 위 숫자만으로 읽으면 "시험됨"으로 오독한다.
    if "executable_pct" in req_cov:
        metrics.append(_metric("executable_coverage_pct", _safe_float(req_cov, "executable_pct")))
        metrics.append(_metric("review_only_reqs_count", _safe_float(req_cov, "review_only_count")))

    # 함수 기준 커버리지 — **비게이트**. 요구당 TC 상한(max_tc_per_req)이 함수 루프를 끊어
    # 매핑된 함수 대부분이 시험 없이 남는데, 위 두 값은 전부 요구 단위라 그걸 못 본다.
    # 실측(HDPDM01): 요구 커버리지 100.0% / 실행시험 87.3% 인데 함수 기준은 6.4%(747→48)였다.
    gen_stats = quality_report.get("generation_stats") or {}
    if "function_tc_coverage_pct" in gen_stats:
        metrics.append(
            _metric("function_tc_coverage_pct", _safe_float(gen_stats, "function_tc_coverage_pct")))
        metrics.append(
            _metric("functions_without_tc", _safe_float(gen_stats, "functions_without_tc")))

    # 테스트 방법 다양성 (종류 수 / 5, 상한 100%)
    methods = quality_report.get("test_method_distribution") or {}
    method_count = len([k for k in methods if k != "?"])
    diversity_pct = round(min(method_count / 5.0, 1.0) * 100, 2)
    metrics.append(_metric("method_diversity_pct", diversity_pct))

    # 총 TC 수 (참고용)
    metrics.append(_metric("total_test_cases", total))

    return metrics


def evaluate_suts(quality_report: Dict[str, Any]) -> MetricList:
    """generators/suts.py generate_suts_quality_report() 반환 dict -> MetricList.

    Args:
        quality_report: SUTS 품질 리포트 dict.
    """
    metrics: MetricList = []

    total = _safe_float(quality_report, "total_test_cases")

    # 함수 커버리지
    metrics.append(
        _metric("function_coverage_pct", _safe_float(quality_report, "function_coverage_pct"), threshold=80.0),
    )

    # I/O 커버리지
    metrics.append(
        _metric("io_coverage_pct", _safe_float(quality_report, "io_coverage_pct"), threshold=70.0),
    )

    # 시퀀스 충실도 (avg/6 상한 100%)
    avg_seq = _safe_float(quality_report, "avg_sequences_per_tc")
    seq_fidelity = round(min(avg_seq / 6.0, 1.0) * 100, 2)
    metrics.append(_metric("sequence_fidelity_pct", seq_fidelity))

    # 로직 플로우 보유율
    with_logic = _safe_float(quality_report, "with_logic_count")
    logic_pct = round(with_logic / max(total, 1) * 100, 2)
    metrics.append(_metric("logic_flow_pct", logic_pct))

    # 총 TC / 시퀀스 수 (참고용)
    metrics.append(_metric("total_test_cases", total))
    metrics.append(_metric("total_sequences", _safe_float(quality_report, "total_sequences")))

    return metrics


def evaluate_sits(quality_report: Dict[str, Any]) -> MetricList:
    """generators/sits.py SITS quality_report -> MetricList.

    SITS는 SW 통합시험 스펙(추적성/IO 커버리지 proxy — 실행 커버리지 아님). 시스템 통합시험은 SyITS다.
    """
    metrics: MetricList = []
    total = _safe_float(quality_report, "total_test_cases")

    # 요구사항 추적성 — **합성 SwCom을 제외한** 실제 요구/설계 ID 기준.
    # 과거엔 related_coverage_pct(Related ID 필드 보유율)를 그대로 썼는데, SITS 생성기가
    # 모든 flow에 순번 기반 SwCom_XX를 무조건 삽입하므로 그 값은 사실상 항상 100%였다 →
    # 요구 링크가 0건이어도 threshold 70을 통과했다. 구 리포트엔 새 키가 없어 0.0으로
    # 떨어지고 게이트가 실패하는데, 그게 "미측정을 통과로 바꾸지 않는" fail-closed 방향이다.
    metrics.append(
        _metric("requirement_traceability_pct",
                _safe_float(quality_report, "requirement_traceability_pct"), threshold=70.0),
    )
    # Related ID 필드 보유율은 서식 채움 지표로 별도 보존(게이트 미반영 — threshold 없음).
    metrics.append(
        _metric("related_field_filled_pct", _safe_float(quality_report, "related_coverage_pct")),
    )
    metrics.append(
        _metric("synthetic_only_related_count",
                _safe_float(quality_report, "synthetic_only_related_count")),
    )
    # I/O 커버리지 (입출력 변수 보유 TC 비율)
    metrics.append(
        _metric("io_coverage_pct", _safe_float(quality_report, "io_coverage_pct"), threshold=60.0),
    )
    # 테스트 방법 다양성 (생성 방법 종류 수 / 3, 상한 100%)
    methods = quality_report.get("gen_method_distribution") or {}
    method_count = len([k for k in methods if k and k != "?"])
    metrics.append(_metric("method_diversity_pct", round(min(method_count / 3.0, 1.0) * 100, 2)))
    # 통합 밀도 (TC당 sub-case 평균 / 7, 상한 100%)
    avg_sub = _safe_float(quality_report, "avg_sub_cases_per_tc")
    metrics.append(_metric("integration_density_pct", round(min(avg_sub / 7.0, 1.0) * 100, 2)))

    metrics.append(_metric("total_test_cases", total))

    # ── 통합 흐름 캡 절단 축 (비게이트) ─────────────────────────────────────
    # total_test_cases 는 **생성된** 흐름 수라 캡에 잘린 흐름이 있어도 줄지 않는다.
    # 분모를 소스에서 찾은 흐름 수로 되돌린 값을 별도로 노출한다. threshold 를 안 거는
    # 이유는 기존 프로젝트의 pass/fail 을 뒤집지 않기 위해서다(정책 결정 사항).
    flow_cov = quality_report.get("integration_flow_coverage") or {}
    if flow_cov.get("total_flows_found") is not None:
        metrics.append(_metric("flow_emit_pct", _safe_float(flow_cov, "flow_emit_pct")))
        metrics.append(_metric("flows_dropped", _safe_float(flow_cov, "flows_dropped")))
        metrics.append(
            _metric("dropped_safety_related_flows",
                    _safe_float(flow_cov, "dropped_safety_related_count")),
        )
    return metrics


def evaluate_swreport(summary: Dict[str, Any]) -> MetricList:
    """SwReport 통합 Summary(ES95411 roll-up) -> MetricList.

    전 레벨 산출물의 P/F verdict 집계(커버리지 아님). performed/fail 기반 pass-rate.
    """
    metrics: MetricList = []
    performed = _safe_float(summary, "performed_count")
    fail = _safe_float(summary, "fail_count")

    pass_rate = round((performed - fail) / max(performed, 1.0) * 100, 2)
    metrics.append(_metric("pass_rate_pct", pass_rate, threshold=100.0))

    overall_pass = 100.0 if str(summary.get("overall_result", "")).strip().lower() == "pass" else 0.0
    metrics.append(_metric("overall_pass", overall_pass))

    metrics.append(_metric("performed_count", performed))
    metrics.append(_metric("fail_count", fail))
    return metrics


def evaluate_coverage(summary: Dict[str, Any], *, asil: Optional[str] = None) -> MetricList:
    """SwUT/SwIT Coverage Report summary -> MetricList (ISO 26262 커버리지 게이트).

    구문(전 ASIL)·분기(ASIL B+)·MC-DC(ASIL D)에 ASIL별 100% threshold. asil 미지정 시
    분기/MC-DC 는 참고지표(threshold=None)로 점수 미반영 — QM/A 모듈 과잉 FAIL 방지.
    """
    metrics: MetricList = []
    a = str(asil or "").upper().strip()

    metrics.append(
        _metric("statement_coverage_pct", _safe_float(summary, "overall_statement_pct"), threshold=100.0),
    )
    metrics.append(
        _metric("branch_coverage_pct", _safe_float(summary, "overall_branch_pct"),
                threshold=100.0 if a in ("B", "C", "D") else None),
    )
    metrics.append(
        _metric("mcdc_coverage_pct", _safe_float(summary, "overall_mcdc_pct"),
                threshold=100.0 if a == "D" else None),
    )

    passed = _safe_float(summary, "passed")
    tested = passed + _safe_float(summary, "failed")
    # 미실행 TC(시험 공백)를 분모에 포함한다 — 안 넣으면 스위트의 10%만 돌려도
    # pass_rate 100%·게이트 통과로 남아 ISO 26262 시험 완전성이 은폐된다(실측:
    # passed=10/failed=0/not_executed=90 → 옛 계산 10/10=100%). **name 단위로 일치**
    # 시킨다: passed/failed(test_results 행)·not_executed 모두 이름 단위인데,
    # total_tcs 는 compound TC 의 서브아이템 granular(Σlen(tc_list))라 분모로 쓰면
    # 완전실행 스위트를 오탐 FAIL 시킬 수 있다(deep-review W1). not_executed 부재면
    # 실행분(tested)으로 폴백 — 데이터부재 과도 penalty·0除 방지.
    denom = tested + _safe_float(summary, "not_executed")
    metrics.append(_metric("pass_rate_pct", round(passed / max(denom, 1.0) * 100, 2), threshold=100.0))

    metrics.append(_metric("total_tcs", _safe_float(summary, "total_tcs")))
    return metrics


def evaluate_swsa(quality_data: Dict[str, Any]) -> MetricList:
    """SwSA(MISRA/HIS 정적·안전분석) -> MetricList.

    HIS pass% 만 게이트(threshold). MISRA/Secure/중복 위반 수는 프로젝트 규모에 비례하는
    절대수라 hard-fail 부적합(ASIL A 도구) → threshold 없는 참고지표(trend 비교용).
    HIS pass% 는 metric 별 (binned − fail)/total 평균이며 **unbinned(미평가) 함수는
    분자에서 제외** — '미평가'를 Pass 로 오기재하지 않기 위함.
    """
    metrics: MetricList = []
    rates = []
    for m in quality_data.get("his_metrics") or []:
        total = _safe_float(m, "total")
        if total <= 0:
            continue
        passed = total - _safe_float(m, "fail") - _safe_float(m, "unbinned")
        rates.append(max(0.0, passed) / total * 100)
    his_pass = round(sum(rates) / len(rates), 2) if rates else 0.0
    metrics.append(_metric("his_pass_pct", his_pass, threshold=80.0))

    # 위반 수 — 참고지표(threshold 없음). QAC extraction_failed 시 호출자가 미포함.
    metrics.append(_metric("misra_active_violations", _safe_float(quality_data, "misra_active")))
    metrics.append(_metric("secure_active_violations", _safe_float(quality_data, "secure_active")))
    metrics.append(_metric("duplication_fail_blocks", _safe_float(quality_data, "pmd_fail")))
    return metrics


def compute_overall_score(metrics: MetricList) -> float:
    """MetricList -> 종합 점수 (0~100).

    gate_pass가 있는 메트릭만 점수 계산에 포함.
    gate_pass=False 항목은 0.5x 페널티.
    """
    scored = [m for m in metrics if m.get("threshold") is not None]
    if not scored:
        # threshold가 없으면 _pct 메트릭의 value 평균
        vals = [m["value"] for m in metrics if m.get("metric_name", "").endswith("_pct")]
        return round(sum(vals) / max(len(vals), 1), 2)

    total = 0.0
    count = 0
    for m in scored:
        val = float(m.get("value", 0))
        if not m.get("gate_pass"):
            val *= 0.5  # 페널티
        total += val
        count += 1

    return round(total / max(count, 1), 2)
