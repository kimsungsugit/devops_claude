"""영향도 분석 AI 가이드 서비스

결정론적 리스크 평가 + LLM 기반 가이드 생성.
LLM 미설정 시에도 리스크 평가, 크로스 문서 영향 분석은 동작합니다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ASIL 등급 위험도 순서
_ASIL_RANK = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}

# 변경 유형별 위험 가중치
_CHANGE_WEIGHT = {
    "SIGNATURE": 4,
    "NEW": 3,
    "DELETE": 3,
    "BODY": 2,
    "VARIABLE": 2,
    "HEADER": 1,
}

# 문서 유형별 영향받는 변경 유형
_DOC_CHANGE_SENSITIVITY: Dict[str, Dict[str, str]] = {
    "uds": {
        "SIGNATURE": "함수 인터페이스 변경 → UDS 입출력/프로토타입 섹션 업데이트 필요",
        "BODY": "로직 변경 → UDS 설명/로직 다이어그램 업데이트 필요",
        "NEW": "신규 함수 → UDS 신규 섹션 생성 필요",
        "DELETE": "삭제된 함수 → UDS 해당 섹션 제거 필요",
        "VARIABLE": "변수 변경 → UDS 글로벌/로컬 변수 목록 업데이트",
        "HEADER": "헤더 변경 → UDS 인터페이스/의존성 정보 확인",
    },
    "suts": {
        "SIGNATURE": "인터페이스 변경 → 모든 TC 입출력값 재검증 필요",
        "BODY": "로직 변경 → 경계값/기대값 재계산 필요",
        "NEW": "신규 함수 → TC 신규 생성 필요",
        "DELETE": "삭제 → 관련 TC 제거",
        "VARIABLE": "변수 변경 → 관련 TC 입출력 매핑 확인",
    },
    "sits": {
        "SIGNATURE": "인터페이스 변경 → 콜체인 전체 재검증",
        "BODY": "로직 변경 → 통합 테스트 기대값 재확인",
        "NEW": "신규 함수 → 콜체인에 포함 여부 확인",
        "DELETE": "삭제 → 콜체인 단절 확인",
        "VARIABLE": "변수 변경 → 통합 테스트 데이터 흐름 재확인",
        "HEADER": "헤더 변경 → 콜체인 인터페이스 의존성 확인",
    },
    "sts": {
        "SIGNATURE": "인터페이스 변경 → STS 요구사항 검증 방법 재검토",
        "BODY": "로직 변경 → STS 요구사항 기대 동작 재확인",
        "NEW": "신규 함수 → STS 요구사항 매핑 추가",
        "DELETE": "삭제 → STS 요구사항 커버리지 재확인",
        "VARIABLE": "변수 변경 → STS 요구사항 입출력 매핑 확인",
    },
    "sds": {
        "SIGNATURE": "아키텍처 인터페이스 변경 → SDS 모듈 인터페이스 업데이트",
        "BODY": "로직 변경 → SDS 설계 설명 업데이트 필요",
        "NEW": "신규 컴포넌트 → SDS 설계 추가",
        "DELETE": "컴포넌트 삭제 → SDS 설계 제거",
        "VARIABLE": "변수 변경 → SDS 데이터 흐름/인터페이스 업데이트",
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RiskAssessment:
    """리스크 평가 결과."""
    grade: str  # LOW, MEDIUM, HIGH, CRITICAL
    score: int  # 0~100
    asil_escalation: bool
    max_asil: str
    justification: str
    affected_safety_functions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade": self.grade,
            "score": self.score,
            "asil_escalation": self.asil_escalation,
            "max_asil": self.max_asil,
            "justification": self.justification,
            "affected_safety_functions": self.affected_safety_functions,
        }


@dataclass
class ImpactGuide:
    """종합 AI 가이드 결과."""
    executive_summary: str
    risk: RiskAssessment
    review_checklist: List[Dict[str, str]]
    test_recommendations: List[Dict[str, str]]
    cross_doc_impacts: Dict[str, List[str]]
    generated_at: str = ""
    ai_enriched: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executive_summary": self.executive_summary,
            "risk": self.risk.to_dict(),
            "review_checklist": self.review_checklist,
            "test_recommendations": self.test_recommendations,
            "cross_doc_impacts": self.cross_doc_impacts,
            "generated_at": self.generated_at or datetime.now().isoformat(),
            "ai_enriched": self.ai_enriched,
        }


@dataclass
class ImpactGuideContext:
    """가이드 생성에 필요한 컨텍스트 번들."""
    changed_types: Dict[str, str]  # {func_name: change_type}
    impact_groups: Dict[str, List[str]]  # {direct/1hop/2hop: [func_name, ...]}
    by_name: Dict[str, Dict[str, Any]]  # function details
    uds_fn_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    suts_tcs: Dict[str, List[str]] = field(default_factory=dict)
    sits_chains: Dict[str, List[str]] = field(default_factory=dict)
    linked_docs: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 1. 결정론적 리스크 평가 (LLM 불필요)
# ---------------------------------------------------------------------------

def assess_risk(
    changed_types: Dict[str, str],
    by_name: Dict[str, Dict[str, Any]],
    impact_groups: Dict[str, List[str]],
) -> RiskAssessment:
    """Assess risk based on ASIL levels, change types, and impact scope.

    Fully deterministic — no LLM required.
    """
    if not changed_types:
        return RiskAssessment(
            grade="LOW", score=0, asil_escalation=False, max_asil="QM",
            justification="변경된 함수 없음",
        )

    # Collect ASIL levels of all impacted functions
    all_impacted = set()
    for group_fns in impact_groups.values():
        all_impacted.update(group_fns)
    all_impacted.update(changed_types.keys())

    asil_levels: List[str] = []
    safety_funcs: List[str] = []
    for fn in all_impacted:
        info = by_name.get(fn)
        if info is None:
            info = by_name.get(fn.lower())
        if info is None:
            info = {}
        asil = str(info.get("asil") or "QM").strip().upper()
        if asil in _ASIL_RANK:
            asil_levels.append(asil)
            if _ASIL_RANK.get(asil, 0) >= 2:  # B, C, D
                safety_funcs.append(f"{fn} (ASIL {asil})")

    max_asil = max(asil_levels, key=lambda a: _ASIL_RANK.get(a, 0)) if asil_levels else "QM"

    # Calculate risk score (0-100)
    # Components: ASIL weight (40%), change type weight (30%), scope weight (30%)
    asil_score = _ASIL_RANK.get(max_asil, 0) * 10  # 0-40

    change_scores = [_CHANGE_WEIGHT.get(ct, 1) for ct in changed_types.values()]
    avg_change = sum(change_scores) / len(change_scores) if change_scores else 0
    change_score = min(avg_change * 7.5, 30)  # 0-30

    total_impacted = len(all_impacted)
    scope_score = min(total_impacted * 3, 30)  # 0-30

    total_score = int(asil_score + change_score + scope_score)

    # ASIL escalation: direct change to ASIL B+ function
    direct_fns = set(changed_types.keys())
    asil_escalation = any(
        _ASIL_RANK.get(str((by_name.get(fn) or {}).get("asil") or "QM").strip().upper(), 0) >= 2
        for fn in direct_fns
    )

    # Grade
    if total_score >= 70 or (asil_escalation and max_asil in ("C", "D")):
        grade = "CRITICAL"
    elif total_score >= 50 or asil_escalation:
        grade = "HIGH"
    elif total_score >= 25:
        grade = "MEDIUM"
    else:
        grade = "LOW"

    # Justification
    parts = []
    parts.append(f"최대 ASIL: {max_asil}")
    parts.append(f"직접 변경: {len(changed_types)}개 함수")
    parts.append(f"총 영향 범위: {total_impacted}개 함수")
    if safety_funcs:
        parts.append(f"안전 관련 함수: {', '.join(safety_funcs[:5])}")
    change_types_str = ", ".join(set(changed_types.values()))
    parts.append(f"변경 유형: {change_types_str}")

    return RiskAssessment(
        grade=grade,
        score=total_score,
        asil_escalation=asil_escalation,
        max_asil=max_asil,
        justification="; ".join(parts),
        affected_safety_functions=safety_funcs[:10],
    )


# ---------------------------------------------------------------------------
# 2. 크로스 문서 영향 분석 (LLM 불필요)
# ---------------------------------------------------------------------------

def analyze_cross_document_impact(
    changed_types: Dict[str, str],
    targets: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Map changed functions to affected document sections.

    Returns {doc_type: [impact_description, ...]}
    """
    targets = targets or list(_DOC_CHANGE_SENSITIVITY.keys())
    result: Dict[str, List[str]] = {}

    for doc_type in targets:
        sensitivity = _DOC_CHANGE_SENSITIVITY.get(doc_type, {})
        impacts: List[str] = []
        for fn, change_type in changed_types.items():
            desc = sensitivity.get(change_type)
            if desc:
                impacts.append(f"[{fn}] {change_type} → {desc}")
        if impacts:
            result[doc_type] = impacts

    return result


# ---------------------------------------------------------------------------
# 3. LLM 기반 가이드 생성 (선택적)
# ---------------------------------------------------------------------------

def _build_guide_prompt_context(ctx: ImpactGuideContext, risk: RiskAssessment) -> str:
    """Build context string for LLM prompt."""
    lines = [
        f"## 변경 분석 컨텍스트",
        f"- 리스크 등급: {risk.grade} (점수: {risk.score}/100)",
        f"- 최대 ASIL: {risk.max_asil}",
        f"- ASIL 에스컬레이션: {'예' if risk.asil_escalation else '아니오'}",
        f"",
        f"## 변경된 함수 ({len(ctx.changed_types)}개)",
    ]
    for fn, ct in list(ctx.changed_types.items())[:20]:
        info = ctx.by_name.get(fn) or {}
        asil = info.get("asil", "QM")
        lines.append(f"- {fn}: {ct} (ASIL {asil})")

    if ctx.impact_groups:
        for group, fns in ctx.impact_groups.items():
            if fns:
                lines.append(f"\n## 영향 범위 — {group} ({len(fns)}개)")
                for fn in fns[:10]:
                    lines.append(f"- {fn}")

    if ctx.suts_tcs:
        lines.append(f"\n## 기존 테스트 케이스")
        for fn, tcs in list(ctx.suts_tcs.items())[:10]:
            lines.append(f"- {fn}: {', '.join(tcs[:5])}")

    return "\n".join(lines)


def generate_change_summary(ctx: ImpactGuideContext, risk: RiskAssessment) -> str:
    """Generate executive summary using LLM.

    Falls back to deterministic summary if LLM unavailable.
    """
    try:
        from workflow.ai import agent_call
        from prompts import load_prompt

        system = load_prompt("impact_guide")
        context = _build_guide_prompt_context(ctx, risk)
        user_msg = (
            f"{context}\n\n"
            f"위 변경 분석을 바탕으로 ISO 26262 관점의 영향도 요약을 작성하세요.\n"
            f"포함 항목: 변경 범위 요약, 리스크 판단 근거, 리뷰 우선순위, 권고사항."
        )
        result = agent_call(system_prompt=system, user_prompt=user_msg, role="analysis")
        if result and isinstance(result, str):
            return result
    except Exception as e:
        logger.debug("LLM 가이드 생성 실패, 결정론적 폴백 사용: %s", e)

    # Deterministic fallback
    return _deterministic_summary(ctx, risk)


def suggest_test_additions(
    ctx: ImpactGuideContext,
    risk: RiskAssessment,
) -> List[Dict[str, str]]:
    """Suggest new test cases using LLM.

    Falls back to deterministic suggestions if LLM unavailable.
    """
    try:
        from workflow.ai import agent_call
        from prompts import load_prompt

        system = load_prompt("impact_test_advisor")
        context = _build_guide_prompt_context(ctx, risk)
        user_msg = (
            f"{context}\n\n"
            f"위 변경에 대해 추가해야 할 테스트 케이스를 제안하세요.\n"
            f"JSON 배열로 응답: [{{\"function\": ..., \"test_type\": ..., \"description\": ..., \"rationale\": ...}}]"
        )
        result = agent_call(system_prompt=system, user_prompt=user_msg, role="analysis")
        if result:
            text = result if isinstance(result, str) else str(result)
            # Extract JSON array from response
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end > start:
                return json.loads(text[start:end + 1])
    except Exception as e:
        logger.debug("LLM 테스트 제안 실패, 결정론적 폴백 사용: %s", e)

    # Deterministic fallback
    return _deterministic_test_suggestions(ctx)


# ---------------------------------------------------------------------------
# 4. 종합 가이드 생성 (메인 엔트리포인트)
# ---------------------------------------------------------------------------

def generate_impact_guide(ctx: ImpactGuideContext) -> ImpactGuide:
    """Generate comprehensive impact guide.

    Always produces a result — LLM enriches but is not required.
    """
    # Step 1: deterministic risk assessment
    risk = assess_risk(ctx.changed_types, ctx.by_name, ctx.impact_groups)

    # Step 2: cross-document impact (deterministic)
    cross_doc = analyze_cross_document_impact(ctx.changed_types)

    # Step 3: review checklist (deterministic)
    checklist = _build_review_checklist(ctx, risk, cross_doc)

    # Step 4: try LLM for summary and test suggestions
    ai_enriched = False
    summary = _deterministic_summary(ctx, risk)
    test_recs = _deterministic_test_suggestions(ctx)

    try:
        llm_summary = generate_change_summary(ctx, risk)
        if llm_summary and llm_summary != summary:
            summary = llm_summary
            ai_enriched = True
    except Exception:
        pass

    try:
        llm_tests = suggest_test_additions(ctx, risk)
        if llm_tests:
            test_recs = llm_tests
            ai_enriched = True
    except Exception:
        pass

    return ImpactGuide(
        executive_summary=summary,
        risk=risk,
        review_checklist=checklist,
        test_recommendations=test_recs,
        cross_doc_impacts=cross_doc,
        generated_at=datetime.now().isoformat(),
        ai_enriched=ai_enriched,
    )


# ---------------------------------------------------------------------------
# Deterministic fallbacks
# ---------------------------------------------------------------------------

def _deterministic_summary(ctx: ImpactGuideContext, risk: RiskAssessment) -> str:
    """Generate summary without LLM."""
    lines = [
        f"# 영향도 분석 요약",
        f"",
        f"**리스크 등급**: {risk.grade} (점수: {risk.score}/100)",
        f"**최대 ASIL**: {risk.max_asil}",
        f"**ASIL 에스컬레이션**: {'예 — 안전 관련 함수 직접 변경' if risk.asil_escalation else '아니오'}",
        f"",
        f"## 변경 범위",
        f"- 직접 변경: {len(ctx.changed_types)}개 함수",
    ]

    total_impacted = sum(len(fns) for fns in ctx.impact_groups.values())
    lines.append(f"- 간접 영향: {total_impacted}개 함수")

    if risk.affected_safety_functions:
        lines.append(f"")
        lines.append(f"## 안전 관련 함수")
        for sf in risk.affected_safety_functions[:5]:
            lines.append(f"- {sf}")

    change_counts: Dict[str, int] = {}
    for ct in ctx.changed_types.values():
        change_counts[ct] = change_counts.get(ct, 0) + 1
    lines.append(f"")
    lines.append(f"## 변경 유형 분포")
    for ct, cnt in sorted(change_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {ct}: {cnt}건")

    return "\n".join(lines)


def _deterministic_test_suggestions(ctx: ImpactGuideContext) -> List[Dict[str, str]]:
    """Generate test suggestions without LLM."""
    suggestions = []
    for fn, change_type in list(ctx.changed_types.items())[:10]:
        existing_tcs = ctx.suts_tcs.get(fn, [])
        if change_type == "SIGNATURE":
            suggestions.append({
                "function": fn,
                "test_type": "경계값 재검증",
                "description": f"{fn}의 인터페이스 변경으로 모든 경계값 TC 재검증 필요",
                "rationale": f"기존 TC {len(existing_tcs)}개 — 입출력 타입 변경 시 경계값 재계산",
            })
        elif change_type in ("NEW",):
            suggestions.append({
                "function": fn,
                "test_type": "신규 TC 생성",
                "description": f"{fn} 신규 함수에 대한 TC 생성 필요 (BV_MIN/MID/MAX/INV)",
                "rationale": "신규 함수는 최소 경계값 분석(ABV) 기반 TC 필요",
            })
        elif change_type == "BODY" and not existing_tcs:
            suggestions.append({
                "function": fn,
                "test_type": "TC 신규 생성",
                "description": f"{fn} 로직 변경되었으나 기존 TC 없음 — 신규 생성 권장",
                "rationale": "로직 변경 + TC 미존재 = 커버리지 갭",
            })
    return suggestions


def _build_review_checklist(
    ctx: ImpactGuideContext,
    risk: RiskAssessment,
    cross_doc: Dict[str, List[str]],
) -> List[Dict[str, str]]:
    """Build review checklist from risk and cross-doc analysis."""
    checklist: List[Dict[str, str]] = []

    if risk.asil_escalation:
        checklist.append({
            "priority": "CRITICAL",
            "item": "ASIL 에스컬레이션 — 안전 분석 담당자 리뷰 필수",
            "scope": f"함수: {', '.join(risk.affected_safety_functions[:3])}",
        })

    for doc_type, impacts in cross_doc.items():
        checklist.append({
            "priority": "HIGH" if doc_type in ("uds", "suts") else "MEDIUM",
            "item": f"{doc_type.upper()} 문서 업데이트 검토 ({len(impacts)}건)",
            "scope": impacts[0] if impacts else "",
        })

    if risk.grade in ("HIGH", "CRITICAL"):
        checklist.append({
            "priority": "HIGH",
            "item": "회귀 테스트 실행 — 영향 범위 내 모든 TC 재실행",
            "scope": f"총 {sum(len(fns) for fns in ctx.impact_groups.values())}개 함수 영향",
        })

    return checklist
