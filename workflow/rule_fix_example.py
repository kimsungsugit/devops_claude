"""룰 fix 예시 생성(LLM 순수 계산) — 실제 diff 발췌를 근거로 '위반하지 않는 작성' 예시.

계층 규약(summary_ai_insight와 동일): IO는 backend/services/rule_fix_examples.py가 담당,
이 모듈은 주어진 diff 발췌 → 예시 JSON 계산만 한다.

ISO 정직성:
- correlation_note는 **서버가 고정 문구로 주입**(LLM 재량 배제) — "이 diff가 위반 감소의
  원인"이라는 인과 단정은 프롬프트에서도 금지한다(상관≠인과).
- 환각 사후 필터: 예시 코드의 식별자가 diff 발췌 식별자 ∪ C 키워드/표준 타입에 없으면 폐기.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Optional

from workflow.summary_ai_insight import _extract_json_payload, resolve_effective_model

logger = logging.getLogger(__name__)

FIX_EXAMPLE_PROMPT_VERSION = 1

CORRELATION_NOTE = (
    "이 파일의 위반 감소와 아래 변경은 같은 빌드 구간에서 관측된 상관이며, "
    "인과(이 변경 때문에 감소)가 검증된 것은 아닙니다."
)

# C 키워드/표준 타입/AUTOSAR·MISRA 문서에 흔한 토큰 — 환각 필터의 허용 어휘.
_C_COMMON = {
    "if", "else", "for", "while", "do", "switch", "case", "default", "break", "continue",
    "return", "goto", "sizeof", "typedef", "struct", "union", "enum", "static", "const",
    "volatile", "extern", "void", "char", "short", "int", "long", "float", "double",
    "signed", "unsigned", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t",
    "int16_t", "int32_t", "int64_t", "boolean", "bool", "true", "false", "null",
    "u8", "u16", "u32", "s8", "s16", "s32", "define", "include", "pragma", "inline",
}
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _identifiers(text: str) -> set:
    return {m.group(0).lower() for m in _IDENT_RE.finditer(text or "")}


def hallucination_check(example: Dict[str, Any], diff_text: str, rule: str) -> Optional[str]:
    """예시가 입력 근거를 벗어나면 사유 문자열 반환(폐기), 통과면 None."""
    echoed_rule = str(example.get("rule") or "").strip()
    if echoed_rule and echoed_rule != rule:
        return "rule_echo_mismatch"
    allowed = _identifiers(diff_text) | _C_COMMON
    for key in ("avoid_pattern", "compliant_pattern"):
        code = str(example.get(key) or "")
        if not code.strip():
            continue
        idents = _identifiers(code)
        unknown = {i for i in idents if i not in allowed}
        # 새 지역 변수명 한둘은 허용(설명용 예시) — 그러나 절반 이상이 미지 식별자면
        # diff와 무관한 코드를 지어낸 것으로 간주한다.
        if idents and len(unknown) > max(2, len(idents) // 2):
            return "hallucinated_identifiers"
    return None


def generate_fix_example(
    *, rule: str, diff_excerpt: str, rule_context: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None, agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """예시 생성. 반환 {example|None, ai_enriched, enrich_reason, model}.

    cfg 미전달 시 impact_ai_guide._load_impact_oai_config 해석(LLM 미설정=정상 폴백).
    호출은 1회(재시도 없음 — 비용 상한), 실패는 결정론 폴백(diff 자체가 증거).
    """
    if cfg is None:
        try:
            from workflow.impact_ai_guide import _load_impact_oai_config
            cfg = _load_impact_oai_config()
        except Exception:
            logger.warning("fix-example LLM config 해석 실패 — 결정론 폴백", exc_info=True)
            cfg = None
    model = resolve_effective_model(cfg)
    if not cfg:
        return {"example": None, "ai_enriched": False, "enrich_reason": "llm_unavailable", "model": model}

    try:
        if agent_call is None:
            from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415
        from prompts import load_prompt

        system = load_prompt("summary_rule_fix_example")
        payload = json.dumps({
            "rule": rule,
            "rule_context": rule_context or {},
        }, ensure_ascii=False) + "\n\n[실제 변경 diff 발췌]\n" + (diff_excerpt or "")
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="summary_fix_example")
        parsed = _extract_json_payload(output or "")
        if not isinstance(parsed, dict) or not str(parsed.get("compliant_pattern") or "").strip():
            return {"example": None, "ai_enriched": False, "enrich_reason": "llm_empty_or_invalid", "model": model}
        reject = hallucination_check(parsed, diff_excerpt, rule)
        if reject:
            return {"example": None, "ai_enriched": False, "enrich_reason": reject, "model": model}
        conf = str(parsed.get("confidence") or "low").lower()
        example = {
            "explanation": str(parsed.get("explanation") or ""),
            "avoid_pattern": str(parsed.get("avoid_pattern") or ""),
            "compliant_pattern": str(parsed.get("compliant_pattern") or ""),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        }
        return {"example": example, "ai_enriched": True, "enrich_reason": None, "model": model}
    except Exception:
        logger.warning("fix-example enrichment 실패 — 결정론 폴백", exc_info=True)
        return {"example": None, "ai_enriched": False, "enrich_reason": "llm_error", "model": model}
