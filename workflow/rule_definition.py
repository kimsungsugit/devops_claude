"""팀 코딩 룰 초안 생성(LLM 순수 계산) — 규칙 공식 설명 + 트렌드 + 실코드 증거 기반.

계층 규약(rule_fix_example과 동일): IO/증거 수집은 backend 라우터가 담당, 이 모듈은
주어진 증거(해소 diff·미해소 발췌) → 초안 JSON 계산만 한다. 사용자 요구 "코드룰을
정의할 수 있게끔"의 산출물 — 관측 데이터에 근거한 초안이지 확정 룰이 아니다.

ISO 정직성:
- RULE_DEFINITION_NOTE는 서버 고정 주입(LLM 재량 배제) — 초안은 팀 검토·승인 전 코딩 룰이 아님.
- 공식 설명(RCFInfo)이 주어지면 재발명 금지(인용) — intent는 프로젝트 맥락 풀이만.
- 환각 사후 필터: avoid/comply 코드 식별자가 증거 텍스트 ∪ C 공통 어휘를 벗어나면 폐기.
- 코드 증거 0건이면 호출측이 no_code_evidence로 거부한다(일반론 초안 차단) — 이 모듈은
  증거가 이미 확보된 입력만 받는다.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from workflow.rule_fix_example import code_hallucination_check
from workflow.summary_ai_insight import _extract_json_payload, resolve_effective_model

logger = logging.getLogger(__name__)

RULE_DEFINITION_PROMPT_VERSION = 1

RULE_DEFINITION_NOTE = (
    "이 초안은 빌드 관측 데이터(트렌드·해소 diff·미해소 발췌)에 근거한 제안이며, "
    "팀 검토·승인 전에는 코딩 룰이 아닙니다. 관측은 상관이며 인과 판정이 아닙니다."
)


def definition_hallucination_check(
    definition: Dict[str, Any], evidence_text: str, rule: str
) -> Optional[str]:
    """초안이 입력 근거를 벗어나면 사유 문자열 반환(폐기), 통과면 None.

    판정은 `code_hallucination_check` 단일 출처 — 여기선 이 산출물의 코드 키만 지정한다.
    """
    return code_hallucination_check(
        definition, evidence_text, rule, code_keys=("avoid_pattern", "comply_pattern"),
    )


def build_evidence_text(
    evidence_diffs: List[Dict[str, Any]], unresolved_excerpts: List[Dict[str, Any]]
) -> str:
    """증거 텍스트 조립 — LLM 입력이자 환각 필터의 허용 어휘 원천(단일 출처)."""
    parts: List[str] = []
    for ev in evidence_diffs or []:
        parts.append(f"[해소 구간 diff — {ev.get('file')}]\n{ev.get('text') or ''}")
    for ex in unresolved_excerpts or []:
        parts.append(f"[미해소 파일 발췌 — {ex.get('file')}]\n{ex.get('text') or ''}")
    return "\n\n".join(parts)


def generate_rule_definition(
    *,
    rule: str,
    description: Optional[Dict[str, Any]],
    trend_row: Dict[str, Any],
    evidence_diffs: List[Dict[str, Any]],
    unresolved_excerpts: List[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]] = None,
    agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """팀 룰 초안 생성. 반환 {definition|None, ai_enriched, enrich_reason, model}.

    definition = {intent, rationale, avoid_pattern, comply_pattern, exceptions[],
    evidence_basis, confidence}. 호출 1회(재시도 없음), 실패는 결정론 폴백(증거 자체는
    라우터가 이미 반환).
    """
    if cfg is None:
        try:
            from workflow.impact_ai_guide import _load_impact_oai_config
            cfg = _load_impact_oai_config()
        except Exception:
            logger.warning("rule-definition LLM config 해석 실패 — 결정론 폴백", exc_info=True)
            cfg = None
    model = resolve_effective_model(cfg)
    if not cfg:
        return {"definition": None, "ai_enriched": False, "enrich_reason": "llm_unavailable", "model": model}

    try:
        if agent_call is None:
            from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415
        from prompts import load_prompt

        system = load_prompt("summary_rule_definition")
        evidence_text = build_evidence_text(evidence_diffs, unresolved_excerpts)
        payload = json.dumps({
            "rule": rule,
            "official_description": description or None,
            "trend": {k: trend_row.get(k) for k in ("classification", "first", "latest", "net")},
        }, ensure_ascii=False) + "\n\n" + evidence_text
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="summary_rule_definition")
        parsed = _extract_json_payload(output or "")
        if not isinstance(parsed, dict) or not str(parsed.get("intent") or "").strip():
            return {"definition": None, "ai_enriched": False, "enrich_reason": "llm_empty_or_invalid", "model": model}
        reject = definition_hallucination_check(parsed, evidence_text, rule)
        if reject:
            return {"definition": None, "ai_enriched": False, "enrich_reason": reject, "model": model}
        conf = str(parsed.get("confidence") or "low").lower()
        definition = {
            "intent": str(parsed.get("intent") or ""),
            "rationale": str(parsed.get("rationale") or ""),
            "avoid_pattern": str(parsed.get("avoid_pattern") or ""),
            "comply_pattern": str(parsed.get("comply_pattern") or ""),
            "exceptions": [str(x).strip() for x in (parsed.get("exceptions") or []) if str(x).strip()][:4],
            "evidence_basis": str(parsed.get("evidence_basis") or ""),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        }
        return {"definition": definition, "ai_enriched": True, "enrich_reason": None, "model": model}
    except Exception:
        logger.warning("rule-definition enrichment 실패 — 결정론 폴백", exc_info=True)
        return {"definition": None, "ai_enriched": False, "enrich_reason": "llm_error", "model": model}
