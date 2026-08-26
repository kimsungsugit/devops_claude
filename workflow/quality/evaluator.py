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

    # threshold 가 없으면 아래 7개 지표가 전부 비게이트가 되어 **게이트가 통째로
    # 사라진다**. 예전엔 그게 조용히 통과로 기록됐다(`compute_gate_verdict` docstring 의
    # vacuous truth). 이제 fail-closed 로 잡히지만, **왜** 그렇게 됐는지가 남아야 하므로
    # 사유를 로깅하고 지표로도 남긴다.
    thresholds: Dict[str, Any] = {}
    thresholds_error = ""
    try:
        import config
        thresholds = getattr(config, "UDS_QUALITY_GATE_THRESHOLDS", None) or {}
        if not thresholds:
            thresholds_error = "config.UDS_QUALITY_GATE_THRESHOLDS 없음/빈 값"
    except Exception as e:   # noqa: BLE001 - 아래에서 사유를 남기고 fail-closed 로 진행
        thresholds_error = f"config import 실패: {type(e).__name__}: {e}"
    if thresholds_error:
        _logger.warning(
            "UDS 품질 게이트 threshold 를 못 읽었다 (%s) — 7개 필드 지표가 비게이트가 되어 "
            "판정이 성립하지 않는다. compute_gate_verdict 가 fail-closed 로 처리한다.",
            thresholds_error,
        )

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
    # ⚠ `config.UDS_QUALITY_GATE_THRESHOLDS` 에 `global_min`/`static_min` 이 있지만
    #   **일부러 안 쓴다**. 미배선 결함으로 보고 게이트에 붙이지 말 것 — 붙이면 위 사유대로
    #   정상 모듈이 떨어진다. `_compute_quick_quality_gate` 의 `gate_pass` 도 같은 7축만 본다.
    for metric_name, rate_key in (("global_pct", "global_fill"), ("static_pct", "static_fill")):
        metrics.append(_metric(metric_name, _rate_val(rate_key, metric_name)))

    # 실질 인터페이스 채움 — `input_pct`/`output_pct` 와 **다른 질문**이라 나란히 둔다.
    #   input_pct       = "입력 칸에 정보를 적었나"      (`[IN] (none)` 도 채움)
    #   input_real_pct  = "실제로 주고받는 항목이 있나"   (`(none)` 은 미채움)
    # 앞 축만 보면 98.3% 라 "입력이 잘 채워졌다" 로 읽히는데, 그 중 79.4%가 "없음"
    # 표기였다. 뒤 축을 함께 남겨 그 사실이 DB 에서 보이게 한다.
    # ⚠ threshold 를 붙이지 않는 것은 의도다 — `(none)` 은 void 함수의 **정확한** 기술이라
    #   낮다고 결함이 아니다. 판정은 앞 축이 계속 맡는다.
    for metric_name, rate_key in (
        ("input_real_pct", "input_real_fill"),
        ("output_real_pct", "output_real_fill"),
    ):
        metrics.append(_metric(metric_name, _rate_val(rate_key, metric_name)))

    # 근거(신뢰 출처) 축 — 값만 기록하고 판정은 `confidence_gate_pass` 가 그대로 한다.
    #
    # ISO 26262 관점에서 물어야 할 것은 "칸이 채워졌나"(fill)가 아니라 **"근거가 있나"**
    # (trusted)다. 생산자는 이 셋을 이미 계산해 `rates` 에 싣는데
    # (`backend/helpers/uds.py` `_compute_quick_quality_gate`), 여기서 지표로 옮기지
    # 않아 **DB 에는 `confidence_gate_pass` boolean 하나로 뭉개져 남았다** — 떨어져도
    # 셋 중 어느 축인지 알 수 없고, 추이도 볼 수 없었다.
    #
    # ⚠ threshold 를 붙이지 않는 것은 의도다. 붙이면 `compute_gate_verdict` 가 이 셋을
    #   게이트로 세어 `confidence_gate_pass` 와 **이중 판정**이 된다. 판정 주체는 하나로
    #   두고, 여기서는 "어느 축이 얼마였나" 만 남긴다.
    for metric_name, rate_key in (
        ("description_trusted_pct", "description_trusted_fill"),
        ("asil_trusted_pct", "asil_trusted_fill"),
        ("related_trusted_pct", "related_trusted_fill"),
    ):
        metrics.append(_metric(metric_name, _rate_val(rate_key, metric_name)))

    # 산출물 충실도 — payload 가 아니라 **문서에 실제로 들어간 수**를 본다.
    #
    # 위 지표는 전부 payload 를 재는데, 이 라이터는 템플릿 주도라 대응 heading 이 없는
    # 함수는 문서에서 조용히 사라진다. 그래서 payload 가 완벽하면 **문서가 비어 있어도
    # 만점**이 나온다. 실측(2026-08-24, `reports/quality.sqlite` ⋈ gen_stats sidecar):
    #   run 660·661 = 문서 반영 **0/5**(빈 heading 419) 인데 gate PASS · 점수 **100.0**
    #   run 674     = 252/350(72.0%), 미반영 98        인데 gate PASS · 점수 99.5
    #
    # ⚠ `if` 가 핵심이다 — 키가 없으면 `_rate_val` 이 **0.0** 을 돌려주므로, 무조건
    #   넣으면 sidecar 가 없어 **재본 적 없는 실행**이 "반영률 0%" 로 기록된다.
    #   미측정과 최악값을 같은 숫자로 적는 것은 이 저장소가 반복해 고쳐 온 결함이다.
    # ⚠ threshold 를 붙이지 않는 것도 의도다. 템플릿이 **의도된 부분집합**일 수 있어
    #   지금 판정에 넣으면 대량 오탐이 된다(`_run_docx_in_subprocess` 주석과 같은 사유).
    #   베이스라인을 쌓은 뒤 정할 일이고, 그 전까지는 수치를 만점 옆에 보이게만 한다.
    if "artifact_match_fill" in rates:
        metrics.append(_metric("artifact_match_pct", _safe_float(rates, "artifact_match_fill")))

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
    # threshold 를 못 읽은 사실 자체를 지표로 남긴다 — 나중에 DB 를 봤을 때 "왜 게이트
    # 항목이 0개였나" 를 되짚을 수 있어야 한다(비게이트 — 판정은 gated_count 가 한다).
    metrics.append(_metric("quality_thresholds_missing", 1.0 if thresholds_error else 0.0))

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
    # ⚠ 미측정(`None`)은 **지표를 내지 않는다**. `_safe_float` 는 None 을 `0.0` 으로
    #   접는데, 여기서 0% 로 그리면 "한 함수도 안 덮였다" 로 읽힌다 — 못 잰 것과
    #   0인 것은 다르다. 생성기는 소스 함수 수를 모르면 `None` 을 준다(fail-open 방지).
    if isinstance(quality_report, dict) and quality_report.get("function_coverage_pct") is not None:
        metrics.append(
            _metric("function_coverage_pct",
                    _safe_float(quality_report, "function_coverage_pct"), threshold=80.0),
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
        # 이 세 이름은 **유지한다** — 기존 소비처가 이 이름으로 읽는다.
        metrics.append(_metric("flow_emit_pct", _safe_float(flow_cov, "flow_emit_pct")))
        metrics.append(_metric("flows_dropped", _safe_float(flow_cov, "flows_dropped")))
        metrics.append(
            _metric("dropped_safety_related_flows",
                    _safe_float(flow_cov, "dropped_safety_related_count")),
        )
        # ⚠ 나머지는 **손으로 고르지 않는다**. 예전엔 위 3개가 화이트리스트 전부라
        #   생산자(`generators/sits.py:_FLOW_COV_KEYS`)에 키를 추가해도 평가기까지
        #   오지 않았다 — 생산자→리포트 사이에서 이미 한 번 겪은 결함이 한 층 위에
        #   그대로 있었다. 여기서는 **리포트 dict 자체를 출처로** 훑는다.
        _named = {"flow_emit_pct", "flows_dropped", "dropped_safety_related_count"}
        _unrepresentable: List[str] = []
        for _k in sorted(flow_cov):
            if _k in _named:
                continue
            _v = flow_cov[_k]
            # bool 은 int 의 하위형이라 먼저 걸러야 True 가 1.0 으로 새지 않는다.
            if isinstance(_v, bool) or not isinstance(_v, (int, float)):
                _unrepresentable.append(_k)
                continue
            metrics.append(_metric(f"flow_{_k}", float(_v)))
        if _unrepresentable:
            # 숫자가 아니라 못 실은 키가 **몇 개인지**는 남긴다. 조용히 빠지면
            # "그런 축이 없다" 와 구별되지 않는다.
            _logger.debug("SITS 흐름 지표 중 수치화 불가: %s", ", ".join(_unrepresentable))
            metrics.append(_metric("flow_metrics_unrepresentable", float(len(_unrepresentable))))
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

    # ── 미측정 축 표면화 (게이트는 그대로 둔다) ──────────────────────────────
    # `compute_coverage_rollup` 은 실측 분모가 0 이면 이제 None 을 낸다(예전엔 0.0 —
    # "측정 안 함"과 "실측 0%"가 같은 값이었다). `_safe_float` 가 None 을 0.0 으로
    # 접으므로 **게이트 판정 자체는 오늘과 동일**하다(미측정 → 0.0 → threshold 100 FAIL).
    # 일부러 그렇게 둔다: ASIL 필수 커버리지 축을 "미평가" 로 바꾸면 지금 FAIL 하던 것이
    # 판정 없음으로 완화된다. 대신 **FAIL 의 사유**를 아래 지표로 구분 가능하게 만든다
    # ("커버리지가 0%" 가 아니라 "측정 자체를 안 함").
    _unmeasured = [
        ax for ax, key in (
            ("statement", "overall_statement_pct"),
            ("branch", "overall_branch_pct"),
            ("mcdc", "overall_mcdc_pct"),
        )
        if summary.get(key) is None
    ]
    metrics.append(_metric("coverage_unmeasured_axes", float(len(_unmeasured))))
    _measured_fn = (summary.get("measured_functions") or {}) if isinstance(summary, dict) else {}
    metrics.append(_metric("coverage_measured_functions",
                           _safe_float(_measured_fn, "statement")))
    metrics.append(_metric("coverage_synthesized_rows",
                           _safe_float(summary, "synthesized_rows")))

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


def evaluate_swit_coverage(summary: Dict[str, Any], *, asil: Optional[str] = None) -> MetricList:
    """SwIT Coverage Report(SwITCV) summary -> MetricList.

    ## 왜 ``evaluate_coverage`` 를 재사용하지 않나

    SwITCV 는 **구문/분기/MC-DC 문서가 아니다.** 빌더의
    ``_align_function_rows_to_template`` 이 각 함수 행의 statement/branch 를
    `measured=False` 인 O/X 표식(1/1·0/1)으로 덮어쓴다 — 회사 정본 4.Coverage 가
    싣는 값이 그 두 줄(Functions / Function Calls)이기 때문이다. 그래서
    ``compute_coverage_rollup`` 은 SwIT 에서 **항상** 전 축 None 을 낸다.

    그 상태로 ``evaluate_coverage`` 에 넣으면 ``_safe_float`` 가 None 을 0.0 으로
    접어 ``statement_coverage_pct=0 < 100`` → **문서가 재지도 않는 축으로 FAIL 을
    지어낸다.** 게다가 그 FAIL 은 어떤 시험을 더 해도 사라지지 않는다(구조적 영구
    FAIL). 같은 결함을 ``evaluate_test_result`` / ``evaluate_comprehensive_result``
    가 이미 두 번 겪었다 — 거기 docstring 참조.

    실제 피해는 가짜 FAIL 보다 **진짜 미달의 은폐** 쪽이 크다. 2026-08-26 KJPDS02
    PV 실측: 게이트는 ``statement 0%`` 로 FAIL 을 내면서, 정작 정본이 지목한
    미달성 Functions 4건(SwUFn_1005/1167/3519/3554)과 미달 Function Calls 21건은
    **어느 지표에도 나타나지 않았다**.

    ## 게이트 축

    ``function_achievement_pct`` / ``function_call_coverage_pct`` 둘 다 100%
    threshold. ASIL 무관하게 건다 — 통합시험의 함수 달성/호출 커버리지는 등급별
    선택 축이 아니라 SwITCV 가 보고하도록 정의된 값 자체다.

    ⚠ 이건 완화가 아니라 **강화**다. 종전엔 ``pass_rate_pct`` 하나만 실질 게이트였고
      (나머지는 미측정 0% 고정) 그건 늘 100% 였다. 위 실측 문서는 새 축에서
      99.61% / 97.91% 로 **정직하게** 미달한다.
    """
    metrics: MetricList = []

    fn_total = _safe_float(summary, "swit_functions_total")
    fn_achieved = _safe_float(summary, "swit_functions_achieved")
    metrics.append(
        _metric("function_achievement_pct",
                round(fn_achieved / max(fn_total, 1.0) * 100, 2), threshold=100.0),
    )

    calls_total = _safe_float(summary, "swit_function_calls_total")
    calls_covered = _safe_float(summary, "swit_function_calls_covered")
    # 분모 0 = Metric report 부재(레거시 경로) — 그땐 호출 축을 재지 못한 것이므로
    # 0% FAIL 을 지어내지 않고 **미평가**(threshold None)로 둔다. 위 docstring 이
    # 지적한 그 함정을 이 함수 안에서 되풀이하지 않기 위한 분기다.
    metrics.append(
        _metric("function_call_coverage_pct",
                round(calls_covered / max(calls_total, 1.0) * 100, 2),
                threshold=100.0 if calls_total > 0 else None),
    )

    # 참고지표 — 절대수는 threshold 부적합(`evaluate_swsa` 와 같은 판단).
    metrics.append(_metric("swit_functions_total", fn_total))
    metrics.append(_metric("swit_functions_fail", _safe_float(summary, "swit_functions_fail")))
    metrics.append(
        _metric("swit_function_calls_fail_functions",
                _safe_float(summary, "swit_function_calls_fail_functions")),
    )
    # 호출이 없어 분모에서 빠진 함수 수 — 분모가 조용히 줄지 않게 함께 노출한다.
    metrics.append(
        _metric("swit_function_calls_na_functions",
                _safe_float(summary, "swit_function_calls_na_functions")),
    )

    # 정렬 전 VectorCAST 원시 커버리지 — **비게이트**. 문서가 안 싣는 값이지만
    # "측정은 했다" 를 남겨야 미측정과 구분된다(빌더 summary 주석 참조).
    for key, name in (
        ("vcast_raw_statement_pct", "vcast_raw_statement_pct"),
        ("vcast_raw_branch_pct", "vcast_raw_branch_pct"),
    ):
        raw = summary.get(key)
        if isinstance(raw, (int, float)):
            metrics.append(_metric(name, float(raw)))
    metrics.append(
        _metric("vcast_raw_measured_functions",
                _safe_float(summary, "vcast_raw_measured_functions")),
    )

    # 시험 통과율은 커버리지 평가기와 같은 계산을 쓴다(미실행 TC 를 분모에 포함).
    passed = _safe_float(summary, "passed")
    tested = passed + _safe_float(summary, "failed")
    denom = tested + _safe_float(summary, "not_executed")
    metrics.append(_metric("pass_rate_pct", round(passed / max(denom, 1.0) * 100, 2), threshold=100.0))
    metrics.append(_metric("total_tcs", _safe_float(summary, "total_tcs")))
    return metrics


def evaluate_test_result(summary: Dict[str, Any]) -> MetricList:
    """SUTR/SITR(시험 **결과** 보고서) summary -> MetricList.

    ## 왜 커버리지 평가기를 재사용하지 않나

    두 산출물의 summary 는 키가 다르다. SUTR/SITR 은 ``total/tested/passed/failed``
    를 내고 **커버리지 축(``overall_statement_pct`` 등)을 아예 내지 않는다**. 그런데
    ``_safe_float`` 는 부재를 ``0.0`` 으로 접으므로, 커버리지 평가기에 넣으면
    ``statement_coverage_pct=0 < 100`` → **측정하지도 않은 축으로 FAIL 을 지어낸다**.
    시험 결과 보고서는 커버리지 문서가 아니므로 커버리지로 채점하지 않는다.

    ## 통과율 분모를 ``total`` 로 두는 이유

    문서의 Test Summary 시트는 ``passed/tested`` 를 찍는다. 그 값을 게이트로 쓰면
    **스위트의 10%만 돌려도 통과율 100%** 가 되어 시험 공백이 은폐된다(같은 결함을
    ``evaluate_coverage`` 가 이미 겪었다 — 거기 주석 참조). 게이트는 미실행을 분모에
    포함한 ``passed/total`` 로 걸고, 문서에 찍히는 값은 비게이트 참고지표
    ``executed_pass_rate_pct`` 로 함께 남겨 화면과 문서가 서로 모순되지 않게 한다.

    편차(Deviation)는 **점수로 환산하지 않는다** — ISO 26262 상 audit reviewer 가
    직접 판단할 항목이라 자동 판정 대상이 아니다(비게이트 참고지표로만 노출).
    """
    metrics: MetricList = []
    total = _safe_float(summary, "total")
    tested = _safe_float(summary, "tested")
    passed = _safe_float(summary, "passed")

    # 분모 0 은 recorder 의 빈-산출물 skip 이 먼저 걸러내지만, 외부 직접 호출도
    # 있으므로 여기서도 0除 를 막는다(0/0 을 100% 로 접지 않는다 — 아래 max 는
    # 분자도 0 이라 결과가 0.0 이 된다).
    metrics.append(
        _metric("test_execution_pct", round(tested / max(total, 1.0) * 100, 2), threshold=100.0),
    )
    metrics.append(
        _metric("pass_rate_pct", round(passed / max(total, 1.0) * 100, 2), threshold=100.0),
    )
    metrics.append(
        _metric("executed_pass_rate_pct", round(passed / max(tested, 1.0) * 100, 2)),
    )

    metrics.append(_metric("total_tcs", total))
    metrics.append(_metric("tested_tcs", tested))
    metrics.append(_metric("failed_tcs", _safe_float(summary, "failed")))
    metrics.append(_metric("deviation_cases", _safe_float(summary, "deviation_cases_written")))
    metrics.append(_metric("environments", _safe_float(summary, "environments")))
    return metrics


def evaluate_comprehensive_result(summary: Dict[str, Any]) -> MetricList:
    """SwUTCR/SwITCR(**종합**결과서) summary -> MetricList.

    ## 왜 ``evaluate_test_result`` 를 재사용하지 않나 — 분모 키가 다르다

    SUTR/SITR 은 총 TC 를 ``total`` 로 내지만(``swut_sutr_aggregator.py:1292``),
    종합결과서는 ``total_tcs`` 로 낸다(``swut_comprehensive_aggregator.py:1078``).
    ``_safe_float`` 는 부재를 ``0.0`` 으로 접고 통과율은 ``tested / max(total, 1.0)`` 이므로,
    종합결과서를 ``evaluate_test_result`` 에 넣으면 **분모가 1 로 고정돼 tested 가 그대로
    백분율이 된다** — 실행 TC 200 건이 실행률 20000% 로 기록된다. 게이트가 없느니만 못하다.

    키 폴백(``total`` 이 없으면 ``total_tcs``)으로 한 함수에 합치지 않는 이유는 두 산출물이
    같은 스키마라는 잘못된 신호를 남기기 때문이다. 종합결과서는 커버리지 축(함수 수)까지
    함께 담는 **다른 문서**다.

    ## 게이트 축은 SUTR/SITR 과 동일하다

    분모의 출처만 다를 뿐 "미실행을 분모에 포함한 ``passed/total``" 규약은 그대로다
    (``evaluate_test_result`` 주석 참조 — ``passed/tested`` 로 걸면 스위트의 10% 만 돌려도
    100% 가 되어 시험 공백이 은폐된다).

    함수 수는 프로젝트 규모에 비례하는 절대수라 hard-fail 에 부적합하다 → **비게이트
    참고지표**로만 남긴다(``evaluate_swsa`` 가 MISRA 위반 수에 대해 내린 것과 같은 판단).
    """
    metrics: MetricList = []
    total = _safe_float(summary, "total_tcs")
    tested = _safe_float(summary, "tested")
    passed = _safe_float(summary, "passed")

    # 분모 0 은 recorder 의 빈-산출물 skip 이 먼저 걸러내지만 외부 직접 호출도 있으므로
    # 여기서도 0除 를 막는다(분자도 0 이라 결과는 0.0 — 0/0 을 100% 로 접지 않는다).
    metrics.append(
        _metric("test_execution_pct", round(tested / max(total, 1.0) * 100, 2), threshold=100.0),
    )
    metrics.append(
        _metric("pass_rate_pct", round(passed / max(total, 1.0) * 100, 2), threshold=100.0),
    )
    metrics.append(
        _metric("executed_pass_rate_pct", round(passed / max(tested, 1.0) * 100, 2)),
    )

    metrics.append(_metric("total_tcs", total))
    metrics.append(_metric("tested_tcs", tested))
    metrics.append(_metric("failed_tcs", _safe_float(summary, "failed")))
    metrics.append(_metric("environments", _safe_float(summary, "environments")))
    metrics.append(_metric("function_rows", _safe_float(summary, "function_rows")))

    # 자격 함수 수 — 키가 산출물마다 다르고(SwUTCR/SwITCR), override 가 없으면 ``None`` 이다.
    # **있는 것만** 싣는다: 없는 축을 0 으로 채우면 "함수 0개" 라는 없는 사실을 보고하게 된다.
    for key in (
        "swutcr_qualified_function_count", "switcr_qualified_function_count",
        "swutcr_raw_function_count", "switcr_function_count",
    ):
        if isinstance(summary, dict) and summary.get(key) is not None:
            metrics.append(_metric("qualified_function_count", _safe_float(summary, key)))
            break
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


def compute_gate_verdict(metrics: MetricList) -> Dict[str, Any]:
    """MetricList -> 게이트 판정. **검사한 항목이 0개면 PASS 가 아니다.**

    판정을 여기 한 곳에서만 정한다(예전엔 `recorder.py` 안에 인라인이었다).

    ⚠ 예전 구현은 `all(m["gate_pass"] for m in metrics if m["gate_pass"] is not None)` 였다.
    필터를 거친 제너레이터가 비면 `all([])` 은 **True** 다(vacuous truth). 실측 2건:

    | 상황 | 옛 결과 |
    |---|---|
    | 알 수 없는 `doc_type` → `metrics=[]` | `gate_pass=True`, score=0.0 (점수 0인데 통과) |
    | `config.UDS_QUALITY_GATE_THRESHOLDS` 부재/import 실패 | 11개 지표 전부 `threshold=None` → 검사 0건인데 `gate_pass=True`. 게다가 점수가 **다른 규칙**(페널티 없는 `_pct` 평균)으로 계산돼 게이트 점수와 비교 불가가 된다 — 참고지표가 높으면 실측처럼 오히려 **오른다**(64.71 → 68.0) |

    ISO 26262 품질 게이트에서 "검사하지 않음" 을 통과로 기록하면 그 자체가 거짓 증거다.
    그래서 게이트 대상이 0개면 **fail-closed**(False + 사유)로 낸다.

    Returns:
        `{"gate_pass": bool, "gated_count": int, "failed_count": int, "reason": str|None}`
    """
    gated = [m for m in metrics if m.get("gate_pass") is not None]
    if not gated:
        return {
            "gate_pass": False,
            "gated_count": 0,
            "failed_count": 0,
            "reason": "no_gated_metric",
        }
    failed = [m for m in gated if not m.get("gate_pass")]
    return {
        "gate_pass": not failed,
        "gated_count": len(gated),
        "failed_count": len(failed),
        "reason": None,
    }


def compute_overall_score(metrics: MetricList) -> float:
    """MetricList -> 종합 점수 (0~100).

    gate_pass가 있는 메트릭만 점수 계산에 포함.
    gate_pass=False 항목은 0.5x 페널티.

    ⚠ threshold 가 하나도 없으면 아래 폴백(=`_pct` 값 평균)으로 떨어지는데, 그 점수는
    **게이트 점수와 같은 척도가 아니다**(페널티가 없으므로 오히려 높게 나온다). 그 상태는
    `compute_gate_verdict` 가 `reason="no_gated_metric"` 으로 판정하고 recorder 가
    `gated_metric_count=0` 을 함께 기록하므로, 추이 그래프에서 이 점수를 게이트 점수와
    나란히 읽으면 안 된다.
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
