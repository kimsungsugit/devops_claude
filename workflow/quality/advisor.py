"""Quality advisor -- analyzes low scores and suggests improvements."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

_logger = logging.getLogger("workflow.quality.advisor")

# 메트릭별 개선 제안 규칙
_UDS_ADVICE = {
    "called_pct": {
        "label": "Called Functions 커버리지",
        "low_advice": "콜 트리 분석 결과가 누락되었을 수 있습니다. include 경로를 확인하고, 외부 함수 매핑(CALL_TREE_EXTERNAL_MAP)을 추가하세요.",
        "threshold": 95.0,
    },
    "calling_pct": {
        "label": "Calling Functions 커버리지",
        "low_advice": "호출 관계가 불완전합니다. 소스 파일 glob 패턴(DEFAULT_TARGETS_GLOB)을 확장하거나, 헤더 파일 경로를 추가하세요.",
        "threshold": 95.0,
    },
    "description_pct": {
        "label": "함수 설명 완성도",
        "low_advice": "함수 설명이 부족합니다. 소스 코드에 Doxygen 주석을 추가하거나, SDS 문서 경로를 지정하여 AI가 참조하도록 하세요. ref_suds_path 설정을 확인하세요.",
        "threshold": 90.0,
    },
    "asil_pct": {
        "label": "ASIL 레벨 지정율",
        "low_advice": "ASIL 레벨이 TBD인 함수가 많습니다. SDS/SRS 문서에서 안전 요구사항을 매핑하거나, project_config에 기본 ASIL 레벨을 설정하세요.",
        "threshold": 50.0,
    },
    "related_pct": {
        "label": "요구사항 추적성",
        "low_advice": "SRS/SDS 요구사항 ID 연결이 부족합니다. req_docs_paths에 요구사항 문서를 추가하고, RAG KB에 요구사항을 ingest하세요.",
        "threshold": 70.0,
    },
    "input_pct": {
        "label": "입력 파라미터 완성도",
        "low_advice": "함수 입력 파라미터 정보가 누락되었습니다. 소스 코드의 함수 프로토타입이 정확한지 확인하세요.",
        "threshold": 90.0,
    },
    "output_pct": {
        "label": "출력 파라미터 완성도",
        "low_advice": "함수 출력/반환값 정보가 누락되었습니다. void 함수의 포인터 출력 파라미터를 확인하세요.",
        "threshold": 90.0,
    },
}

_STS_ADVICE = {
    "completeness_pct": {
        "label": "테스트 케이스 완성도",
        "low_advice": "테스트 스텝이 2개 미만인 TC가 많습니다. AI 향상(ai_config.enable=true)을 활성화하거나, SDS 문서를 제공하여 더 상세한 스텝을 생성하세요.",
        "threshold": 80.0,
    },
    "requirement_coverage_pct": {
        "label": "요구사항 커버리지(검증방법 무관)",
        "low_advice": "요구사항 ID와 연결되지 않은 TC가 많습니다. SRS 문서 경로(srs_docx_path)를 지정하고, 요구사항 매핑 규칙을 확인하세요.",
        "threshold": 70.0,
    },
    "executable_coverage_pct": {
        "label": "실행 시험 기준 커버리지",
        "low_advice": "요구사항이 실행 시험 없이 코드 리뷰(RVW)로만 덮여 있습니다. 소스 경로(source_root)와 SDS 경로를 지정해 요구-함수 매핑을 확보하면 실행 가능한 TC가 생성됩니다.",
        "threshold": None,
    },
    "review_only_reqs_count": {
        "label": "리뷰로만 덮인 요구 수",
        "low_advice": "",
        "threshold": None,
    },
    "function_tc_coverage_pct": {
        "label": "함수 기준 TC 보유율",
        "low_advice": "요구당 TC 상한(max_tc_per_req)에 걸려 매핑된 함수 대부분이 시험 없이 남습니다. 상한을 올리거나, 요구-함수 매핑을 좁혀(모듈 단위 → 함수 단위 SDS Related ID) 요구당 함수 수를 줄이세요.",
        "threshold": None,
    },
    "functions_without_tc": {
        "label": "시험 없는 매핑 함수 수",
        "low_advice": "",
        "threshold": None,
    },
    "method_diversity_pct": {
        "label": "테스트 방법 다양성",
        "low_advice": "테스트 방법이 단조롭습니다(Boundary/Normal만 사용). Error Guessing, Stress, State Transition 등 다양한 방법론을 포함하도록 AI 프롬프트를 조정하세요.",
        "threshold": 60.0,
    },
    "safety_tc_pct": {
        "label": "안전 관련 TC 비율",
        "low_advice": "안전 관련(safety_related=X) TC가 부족합니다. ASIL 레벨이 지정된 함수에 대해 안전 TC를 추가 생성하세요.",
        "threshold": 10.0,
    },
}

_SUTS_ADVICE = {
    "function_coverage_pct": {
        "label": "함수 커버리지",
        "low_advice": "소스 코드 함수 대비 TC 수가 부족합니다. target_function_names 필터를 제거하거나, 소스 파싱 범위를 확장하세요.",
        "threshold": 80.0,
    },
    "io_coverage_pct": {
        "label": "I/O 커버리지",
        "low_advice": "입출력 변수가 없는 TC가 많습니다. 글로벌 변수 맵(globals_info_map)이 올바르게 파싱되었는지 확인하고, 소스의 extern 선언을 점검하세요.",
        "threshold": 70.0,
    },
    "sequence_fidelity_pct": {
        "label": "시퀀스 충실도",
        "low_advice": "TC당 시퀀스 수가 적습니다. max_sequences 파라미터를 늘리거나, AI 향상을 활성화하세요.",
        "threshold": 50.0,
    },
    "logic_flow_pct": {
        "label": "로직 플로우 보유율",
        "low_advice": "로직 플로우(if/switch/loop)가 추출되지 않은 함수가 많습니다. 소스 코드가 복잡도가 낮은 단순 함수일 수 있으며, 이 경우 정상입니다.",
        "threshold": 40.0,
    },
}

# SwUT/SwIT 커버리지 게이트(evaluate_coverage 메트릭명과 1:1).
# branch/mcdc 는 ASIL 별 threshold(B+/D)라 rule 기본값을 두지 않는다 —
# DB에 기록된 threshold(score_obj.threshold)가 있을 때(=ASIL 게이트 대상)만 제안.
# QM/ASIL A 모듈은 evaluate_coverage 가 threshold=None 으로 저장 → 제안 skip.
_SWUT_ADVICE = {
    # ── 커버리지 FAIL 의 **사유** 구분 (비게이트) ──────────────────────────
    # "커버리지 0%" 와 "측정 자체를 안 함" 은 다른 조치를 요구한다. 예전엔 둘 다 0.0 이라
    # 구분이 불가능했다(HMR 미제공 프로젝트는 오히려 합성값 때문에 100.0 이 나왔다).
    "coverage_unmeasured_axes": {
        "label": "미측정 커버리지 축 수",
        "low_advice": "0 이 아니면 그 축은 실측이 없습니다 — TC 를 늘려도 값이 안 변합니다. VectorCAST 산출물(.cov/HMR)이 수집됐는지, 대상 함수가 하니스에 포함됐는지 먼저 확인하세요.",
        "threshold": None,
    },
    "coverage_measured_functions": {
        "label": "실측 커버리지 함수 수(구문 축 분모)",
        "low_advice": "백분율만 보면 '1개 함수 100%'와 '200개 함수 100%'가 같아 보입니다. 이 값이 작으면 커버리지 수치의 근거가 얇습니다.",
        "threshold": None,
    },
    "coverage_synthesized_rows": {
        "label": "합성(존재표식) 행 수",
        "low_advice": "실측이 아니라 '로그에 있음'을 1/1 로 표현한 행입니다. 집계에서는 제외되지만, 이 값이 크면 문서의 O/X 표기 대부분이 실측 근거가 없다는 뜻입니다.",
        "threshold": None,
    },
    "statement_coverage_pct": {
        "label": "구문 커버리지(Statement)",
        "low_advice": "구문 커버리지가 100% 미만입니다(전 ASIL 필수). 실행되지 않은 코드 라인을 위한 TC를 추가하고, VectorCAST 빌드 산출물(.cov)이 최신인지·대상 함수가 테스트 하니스에 포함됐는지 확인하세요.",
        "threshold": 100.0,
    },
    "branch_coverage_pct": {
        "label": "분기 커버리지(Branch)",
        "low_advice": "분기 커버리지가 미달입니다(ASIL B 이상 필수). if/switch 의 미실행 분기(참·거짓 경계)에 대한 TC를 추가하세요.",
        # threshold 생략 — DB threshold(ASIL B+ 에서 100)가 있을 때만 제안.
    },
    "mcdc_coverage_pct": {
        "label": "MC/DC 커버리지",
        "low_advice": "MC/DC 커버리지가 미달입니다(ASIL D 필수). 복합 조건의 각 피연산자가 독립적으로 결과에 영향을 주는 테스트 조합을 보강하세요.",
        # threshold 생략 — DB threshold(ASIL D 에서 100)가 있을 때만 제안.
    },
    "pass_rate_pct": {
        "label": "테스트 통과율",
        "low_advice": "실패한 TC가 있습니다. SwUTR/SwITR 의 FAIL 항목을 확인해 기대값 또는 구현을 수정하세요. 안전 관련(ASIL C/D) 함수는 자동 수정 금지 — 검토 필수입니다.",
        "threshold": 100.0,
    },
}

# SwReport 통합 Summary roll-up — P/F verdict 집계(커버리지 아님).
_SWREPORT_ADVICE = {
    "pass_rate_pct": {
        "label": "통합 통과율(Pass Rate)",
        "low_advice": "통합 Summary 에 FAIL 항목이 있습니다. 레벨별(SwUT/SwIT/SITS) 산출물의 fail_count 를 추적해 원인 레벨의 테스트를 수정하세요.",
        "threshold": 100.0,
    },
    "overall_pass": {
        "label": "전체 판정(Overall Result)",
        "low_advice": "전체 판정이 Pass 가 아닙니다. 미수행(performed 누락) 또는 실패 항목을 점검하세요.",
        "threshold": 100.0,
    },
}

# SUTR/SITR(시험 **결과** 보고서) — 커버리지 문서와 조치가 다르다. "커버리지를 올려라"
# 가 아니라 "안 돌린 TC 를 돌려라 / 실패를 고쳐라" 다.
_TEST_RESULT_ADVICE = {
    "test_execution_pct": {
        "label": "시험 실행률",
        "low_advice": "등록된 TC 중 실행되지 않은 것이 있습니다. 미실행 TC 는 통과도 실패도 아닌 **시험 공백**이라 결과 보고서의 판정 근거가 되지 못합니다 — VectorCAST 실행 로그가 해당 환경까지 수집됐는지 먼저 확인하세요.",
        "threshold": 100.0,
    },
    "pass_rate_pct": {
        "label": "통과율(미실행 포함)",
        "low_advice": "실패했거나 실행되지 않은 TC 가 있습니다. 실행률이 함께 낮다면 원인은 실패가 아니라 미실행입니다 — 두 지표를 같이 보세요.",
        "threshold": 100.0,
    },
    "executed_pass_rate_pct": {
        "label": "실행분 통과율(문서 표기값)",
        "low_advice": "문서 Test Summary 시트에 찍히는 값입니다. 이 값이 100%인데 위 통과율이 낮다면 **돌린 것은 다 통과했지만 안 돌린 것이 있다**는 뜻입니다.",
        "threshold": None,
    },
    "deviation_cases": {
        "label": "편차(Deviation) 건수",
        "low_advice": "편차는 자동 판정 대상이 아닙니다(ISO 26262 상 audit reviewer 판단). 건수만 참고하고 내용은 직접 검토하세요.",
        "threshold": None,
    },
}

# SwSA(MISRA/HIS 정적·안전분석) — HIS pass% 만 게이트(위반 절대수는 제안 부적합).
_SWSA_ADVICE = {
    "his_pass_pct": {
        "label": "HIS 메트릭 통과율",
        "low_advice": "HIS 메트릭(복잡도/중첩/경로 등) 통과율이 낮습니다. 임계 초과 함수를 리팩터링하거나, 미평가(unbinned) 함수를 QAC 분석 대상에 포함하세요.",
        "threshold": 80.0,
    },
}

# SITS(SW 통합시험 — 시스템 통합시험은 SyITS) — 추적성/IO proxy(실행 커버리지 아님).
_SITS_ADVICE = {
    "requirement_traceability_pct": {
        "label": "요구사항 추적성",
        "low_advice": "시스템 요구사항 ID 와 연결되지 않은 TC 가 많습니다. SRS 문서 경로를 지정하고 related ID 매핑을 보강하세요.",
        "threshold": 70.0,
    },
    "io_coverage_pct": {
        "label": "I/O 커버리지",
        "low_advice": "입출력 변수가 없는 통합 TC 가 많습니다. 시스템 인터페이스(신호/메시지) 정의가 소스에 반영됐는지 확인하세요.",
        "threshold": 60.0,
    },
    # ── 캡 절단 축(비게이트) ── TC 수만 보면 "전부 시험함" 으로 읽히므로 별도 노출.
    "flow_emit_pct": {
        "label": "통합 흐름 생성률(소스에서 찾은 흐름 대비)",
        "low_advice": "소스에서 찾은 통합 흐름 중 일부만 규격에 들어갔습니다(max_flows 캡). 잘린 흐름은 시험 규격에 존재하지 않으므로, 캡을 올리거나 대상 범위를 좁혀 의도적으로 결정하세요.",
        "threshold": None,
    },
    "flows_dropped": {
        "label": "캡으로 제외된 통합 흐름 수",
        "low_advice": "0 이 아니면 그만큼의 흐름이 규격에 없습니다.",
        "threshold": None,
    },
    "dropped_safety_related_flows": {
        "label": "제외된 흐름 중 안전관련(ASIL A~D)",
        "low_advice": "안전관련 흐름이 캡에 잘렸습니다. 선별은 등급 우선이므로 이 값이 0 이 아니면 캡이 안전관련 흐름 수보다 작다는 뜻입니다 — 캡을 올려야 합니다.",
        "threshold": None,
    },
}


def suggest_improvements(
    run_id: int,
    *,
    db_path=None,
) -> Dict[str, Any]:
    """특정 실행의 품질 점수를 분석하여 개선 제안을 반환.

    Returns:
        {
            "run_id": int,
            "doc_type": str,
            "overall_score": float,
            "gate_pass": bool,
            "suggestions": [
                {"metric": str, "label": str, "value": float, "threshold": float, "advice": str, "priority": str}
            ],
            "summary": str,
        }
    """
    from workflow.quality.db import get_session, init_db
    from workflow.quality.models import GenerationRun

    init_db(db_path)

    with get_session(db_path) as session:
        run = session.query(GenerationRun).filter_by(id=run_id).first()
        if not run:
            return {"error": f"run_id {run_id} not found"}

        scores = {s.metric_name: s for s in (run.scores or [])}
        summary = run.summary
        doc_type = run.doc_type

        # 메트릭별 advice 규칙 선택
        if doc_type == "uds":
            advice_rules = _UDS_ADVICE
        elif doc_type == "sts":
            advice_rules = _STS_ADVICE
        elif doc_type == "suts":
            advice_rules = _SUTS_ADVICE
        elif doc_type in ("swut", "swit"):
            advice_rules = _SWUT_ADVICE
        elif doc_type in ("sutr", "sitr"):
            advice_rules = _TEST_RESULT_ADVICE
        elif doc_type == "swreport":
            advice_rules = _SWREPORT_ADVICE
        elif doc_type == "swsa":
            advice_rules = _SWSA_ADVICE
        elif doc_type == "sits":
            advice_rules = _SITS_ADVICE
        else:
            advice_rules = {}

        suggestions: List[Dict[str, Any]] = []
        for metric_name, rule in advice_rules.items():
            score_obj = scores.get(metric_name)
            if not score_obj:
                continue

            value = score_obj.value
            if value is None:
                continue  # 외부 INSERT 등으로 value NULL이면 비교 TypeError 방지
            # 진실원 단일화: DB에 기록된 실제 threshold 우선, 없으면 rule 기본값 폴백.
            # (overall_pass 처럼 evaluator가 threshold 미저장이나 rule엔 threshold 가 있는
            #  메트릭은 rule 폴백으로 제안 생성 — 정상.) DB·rule 둘 다 None 이면
            #  (ASIL 미해당 branch/mcdc 같은 참고지표) 게이트 비대상 → 과잉 제안 방지로 skip.
            rule_threshold = rule.get("threshold")
            if score_obj.threshold is not None:
                threshold = score_obj.threshold
            elif rule_threshold is not None:
                threshold = rule_threshold
            else:
                continue

            if value < threshold:
                gap = threshold - value
                if gap > 30:
                    priority = "high"
                elif gap > 10:
                    priority = "medium"
                else:
                    priority = "low"

                suggestions.append({
                    "metric": metric_name,
                    "label": rule["label"],
                    "value": round(value, 1),
                    "threshold": threshold,
                    "gap": round(gap, 1),
                    "advice": rule["low_advice"],
                    "priority": priority,
                })

        # 우선순위 정렬 (high > medium > low, gap 큰 순)
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda x: (priority_order.get(x["priority"], 9), -x["gap"]))

        # 요약 메시지
        overall = summary.overall_score if summary else 0.0
        gate = summary.gate_pass if summary else False
        high_count = sum(1 for s in suggestions if s["priority"] == "high")

        # 게이트 대상이 0개였던 실행은 "통과/미통과" 로 말할 수 없다 — 검사 자체를 안 했다.
        # recorder 가 `gated_metric_count` 를 남기므로 그 값으로 판별한다(부재=구 실행 → None).
        gated_obj = scores.get("gated_metric_count")
        gated_count = int(gated_obj.value) if (gated_obj and gated_obj.value is not None) else None

        unsupported = not advice_rules
        if gated_count == 0:
            summary_text = (
                f"품질 점수 {overall:.1f}/100 -- **게이트 항목이 0개**라 판정이 성립하지 "
                f"않습니다(통과 아님). threshold 설정 또는 doc_type '{doc_type}' 을 확인하세요."
            )
        elif unsupported:
            # 미정의 doc_type(예: sits 등)을 '모든 항목 통과'(품질 양호)로 위장하지 않는다.
            summary_text = f"doc_type '{doc_type}' 은 개선 제안 규칙이 정의되지 않았습니다."
        elif not suggestions and not gate:
            # 게이트는 미통과인데 제안이 0건 = 실패한 지표에 advice 규칙이 없는 경우다.
            # '모든 항목 통과' 로 말하면 게이트 결과와 정면으로 모순된다.
            summary_text = (
                f"품질 점수 {overall:.1f}/100 -- 게이트 미통과이지만 해당 지표에 개선 제안 "
                f"규칙이 없습니다. 실패 지표는 quality_scores 의 gate_pass=false 행을 확인하세요."
            )
        elif not suggestions:
            summary_text = f"품질 점수 {overall:.1f}/100 -- 모든 항목이 임계값을 통과했습니다."
        elif gate:
            summary_text = f"품질 점수 {overall:.1f}/100 -- 게이트 통과. {len(suggestions)}개 항목 개선 가능."
        else:
            summary_text = f"품질 점수 {overall:.1f}/100 -- 게이트 미통과. {high_count}개 긴급 개선 필요."

        return {
            "run_id": run_id,
            "doc_type": doc_type,
            "overall_score": overall,
            "gate_pass": gate,
            "suggestions": suggestions,
            "suggestion_count": len(suggestions),
            "unsupported": unsupported,
            # 게이트 대상 수 — 0 이면 gate_pass 를 "통과/미통과" 로 읽으면 안 된다.
            # None = 이 지표가 없던 구 실행(판별 불가).
            "gated_metric_count": gated_count,
            "summary": summary_text,
        }
