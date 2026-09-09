"""게이트 임계 **단일 출처** — 평가기(판정)와 어드바이저(제안)가 같은 숫자를 본다.

## 왜 이 모듈이 있나 (R42 N6)

`evaluator.py` 는 `_metric(..., threshold=100.0)` 처럼 리터럴로 임계를 걸고,
`advisor.py` 의 규칙 표는 같은 숫자를 `"threshold": 100.0` 으로 **다시** 적고 있었다.
실측 17쌍 — 값은 전부 일치했으므로 지금 화면이 틀리지는 않았다. 잠복이다.

잠복이 깨지는 자리는 정해져 있다: 어드바이저는 DB 에 기록된 `score.threshold` 를
먼저 쓰고, 그것이 `None` 인 행(구판 실행·평가기가 비게이트로 둔 축)에서만 규칙 표의
리터럴로 폴백한다. 즉 **한쪽만 고치면 그 순간부터 옛 실행의 제안이 게이트와 다른
숫자로 "미달 임계 N" 을 말한다** — 사용자에겐 둘 다 "게이트 기준"으로 보인다.
이 저장소가 이미 이름 붙인 형태다(판정 복제 금지, 단일 출처).

UDS 축은 여기 없다 — `config.UDS_QUALITY_GATE_THRESHOLDS` 가 이미 정본이고
`advisor._uds_gate_threshold` 가 **호출 시점에** 그것을 읽는다(R32 Q-10). 두 정본을
하나로 합치는 건 값 이동을 부르는 정책 결정이라 여기서 하지 않는다.

## 축(axis) 이름은 문서 종류가 아니라 **평가 함수**다

`sutr` 과 `sitr` 은 같은 `evaluate_test_result` 로 채점되고, `swutcr`/`switcr` 은
`evaluate_comprehensive_result` 로 간다. 문서 종류를 키로 잡으면 같은 값을 또
두 번 적게 되므로(그게 지금 고치는 결함이다) 축은 평가 함수 단위로 둔다.
"""
from __future__ import annotations

from typing import Dict, Optional

# 평가기가 **게이트로 거는** 임계. 여기 있는 값이 곧 판정 기준이고, 어드바이저의
# 폴백도 같은 값을 읽는다. 조건부로 비게이트가 되는 축(분모 0 → `_gate_if_applicable`,
# ASIL 등급에 따른 branch/mcdc)도 **걸릴 때의 값**은 여기서 온다.
GATE_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "sts": {
        "completeness_pct": 80.0,
        "requirement_coverage_pct": 70.0,
    },
    "suts": {
        "function_coverage_pct": 80.0,
        "io_coverage_pct": 70.0,
    },
    "sits": {
        "requirement_traceability_pct": 70.0,
        "io_coverage_pct": 60.0,
    },
    "coverage": {          # evaluate_coverage — SwUT 커버리지 문서
        "statement_coverage_pct": 100.0,
        "branch_coverage_pct": 100.0,
        "mcdc_coverage_pct": 100.0,
        "pass_rate_pct": 100.0,
    },
    "swit_coverage": {
        "function_achievement_pct": 100.0,
        "function_call_coverage_pct": 100.0,
        "pass_rate_pct": 100.0,
    },
    "swreport": {
        "pass_rate_pct": 100.0,
    },
    "test_result": {       # sutr · sitr
        "pass_rate_pct": 100.0,
        "test_execution_pct": 100.0,
    },
    "comprehensive": {     # swutcr · switcr
        "pass_rate_pct": 100.0,
        "test_execution_pct": 100.0,
    },
    "swsa": {
        "his_pass_pct": 80.0,
    },
}

# 평가기가 **게이트로 걸지 않는** 축인데 어드바이저만 임계를 갖는 것들.
#
# 이 표에 있다는 것은 "게이트는 이 축으로 판정하지 않는다" 는 사실 그대로다 —
# 값이 임계 아래여도 미달이 아니라 참고다. `suggest_improvements` 는 이런 축의
# 제안을 `gated=False` · `priority=low` 로 낸다(R40 N5). 게이트 임계와 **다른 표**에
# 두는 이유가 그것이다: 같은 표에 섞으면 다음 사람이 "게이트 기준" 으로 읽는다.
ADVISORY_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "sts": {
        "method_diversity_pct": 60.0,
        "safety_tc_pct": 10.0,
    },
    "suts": {
        "logic_flow_pct": 40.0,
        "sequence_fidelity_pct": 50.0,
    },
    "swreport": {
        "overall_pass": 100.0,
    },
}


def gate_threshold(axis: str, metric: str) -> Optional[float]:
    """`axis` 축에서 `metric` 이 게이트로 걸리는 임계. 게이트 축이 아니면 `None`.

    ⚠ `None` 은 "0" 이 아니라 **그 축으로 판정하지 않는다**는 뜻이다. 호출부가 이걸
    `or 0.0` 으로 접으면 임계 0 = 무조건 통과가 되어 게이트가 조용히 사라진다.
    """
    return GATE_THRESHOLDS.get(axis, {}).get(metric)


def advisory_threshold(axis: str, metric: str) -> Optional[float]:
    """게이트가 아닌 **참고** 임계. 제안 문구를 낼 때만 쓴다."""
    return ADVISORY_THRESHOLDS.get(axis, {}).get(metric)


def any_threshold(axis: str, metric: str) -> Optional[float]:
    """게이트 임계 우선, 없으면 참고 임계. 어드바이저 규칙의 폴백 해석용."""
    v = gate_threshold(axis, metric)
    return v if v is not None else advisory_threshold(axis, metric)


def require_gate_threshold(axis: str, metric: str) -> float:
    """게이트 임계를 **반드시** 얻는다 — 표에 없으면 `KeyError`.

    평가기가 쓰는 입구다. `gate_threshold` 의 `None` 을 그대로 `_metric(threshold=...)`
    에 넘기면 그 축은 **비게이트**가 되어 조용히 무조건 통과한다 — 표에서 키 하나를
    지우거나 오타를 내는 것만으로 게이트가 사라지고, 화면은 "통과" 로 보인다.
    표는 코드 상수이므로 불일치는 데이터 사고가 아니라 개발 시점 결함이다. 죽는 편이 낫다.
    """
    try:
        return float(GATE_THRESHOLDS[axis][metric])
    except (KeyError, TypeError, ValueError) as exc:
        raise KeyError(
            f"게이트 임계 미정의: axis={axis!r} metric={metric!r} — "
            f"workflow/quality/thresholds.py 의 GATE_THRESHOLDS 에 추가하세요"
        ) from exc
