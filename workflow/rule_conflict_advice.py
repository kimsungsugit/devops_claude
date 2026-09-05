"""룰 상충 해결 지침 생성(LLM 순수 계산) — "A를 고치면 B에 걸린다"에 대한 실무 답.

계층 규약(rule_fix_example·rule_definition과 동일): 증거 수집·IO는 backend 라우터가
담당하고 이 모듈은 주어진 증거 → 지침 JSON 계산만 한다.

기존 산출물과의 차이:
- rule-fix-example  = 규칙 **하나**의 '위반하지 않는 작성'
- rule-definition   = 규칙 **하나**의 팀 룰 초안
- 이 모듈           = 규칙 **쌍/군집**의 트레이드오프 — 둘 다 만족하는 작성, 처리 순서,
                      어느 쪽을 예외 신청할 것인가

ISO 정직성:
- CONFLICT_ADVICE_NOTE는 서버 고정 주입(LLM 재량 배제) — 상충 후보는 지식 + 관측이지
  인과·확정 판정이 아니다.
- mandatory 규칙은 예외 신청 대상이 아니다 → 프롬프트로 금지하고 **사후로도 폐기**한다
  (프롬프트만으로는 안 지켜지는 것을 이미 여러 번 봤다).
- 환각 사후 필터는 `code_hallucination_check` 단일 출처를 그대로 쓴다.
- 코드 증거 0건이면 호출측이 no_code_evidence로 거부한다 — 이 모듈은 증거가 확보된
  입력만 받는다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from workflow.rule_fix_example import code_hallucination_check
from workflow.summary_ai_insight import _extract_json_payload, resolve_effective_model

logger = logging.getLogger(__name__)

# 2: 자동 생성 파일 지침(직접 수정 금지 → 생성기·예외·검사범위) 추가. 캐시 키에 들어가므로
#    올리지 않으면 프롬프트만 바꾼 채 낡은 지침이 계속 서빙된다.
CONFLICT_ADVICE_PROMPT_VERSION = 2

CONFLICT_ADVICE_NOTE = (
    "이 지침은 큐레이션된 규칙 지식과 이 빌드의 관측(동시 위반·구간 변화)을 근거로 만든 "
    "제안이며, 팀 검토·승인 전에는 코딩 룰이 아닙니다. 상충은 가능성이지 인과 판정이 아닙니다."
)


def build_conflict_evidence_text(
    cooccurrence_excerpts: List[Dict[str, Any]], window_diffs: List[Dict[str, Any]]
) -> str:
    """증거 텍스트 조립 — LLM 입력이자 환각 필터의 허용 어휘 원천(단일 출처).

    두 용도가 같은 문자열을 봐야 필터가 '입력에 있던 식별자'를 정확히 판정한다 —
    따로 만들면 LLM이 본 코드를 필터가 모르는 상태가 되어 멀쩡한 답이 폐기된다.
    """
    parts: List[str] = []
    for ex in cooccurrence_excerpts or []:
        # 발췌의 성격을 라벨로 구분한다 — '고칠 규칙만 위반 중'인 파일을 '동시 위반'이라
        # 적으면 LLM 이 상대 규칙도 이미 걸린 것처럼 서술한다(입력으로 사실을 알린다).
        label = (
            "고칠 규칙만 위반 중인 파일 발췌(상대 규칙은 아직 미발생 — 예방적)"
            if ex.get("basis") == "fixing_only" else "동시 위반 파일 발췌"
        )
        # 자동 생성 파일은 **직접 고치면 재생성 때 되돌아온다**. 이 사실을 입력에 싣지
        # 않으면 LLM 이 태연히 "이 파일의 이 줄을 이렇게 바꾸라"고 답한다.
        if ex.get("generated"):
            label += " · ⚠ 자동 생성 파일(직접 수정 대상 아님 — 생성기 설정·템플릿 또는 예외 신청)"
        parts.append(f"[{label} — {ex.get('file')}]\n{ex.get('text') or ''}")
    for d in window_diffs or []:
        parts.append(f"[구간 변경 diff — {d.get('file')}]\n{d.get('text') or ''}")
    return "\n\n".join(parts)


def _mandatory_rules(rule_meta: List[Dict[str, Any]]) -> set:
    return {
        str(m.get("rule") or "")
        for m in rule_meta or []
        if str(m.get("category") or "").lower() == "mandatory"
    }


def deviation_sanity_check(advice: Dict[str, Any], rule_meta: List[Dict[str, Any]]) -> Optional[str]:
    """mandatory 규칙을 예외 후보로 지목했으면 폐기 사유 반환.

    MISRA mandatory는 deviation 자체가 불가능하다(예: 17.4, 9.1, 13.6). 그걸 '예외 신청
    하라'고 안내하면 규격 위반을 권하는 것이라 프롬프트 금지만으로는 부족하다.
    """
    candidate = str(advice.get("deviation_candidate") or "")
    if not candidate.strip():
        return None
    for rule in _mandatory_rules(rule_meta):
        # ⚠ 단순 부분문자열 검사면 'Rule-8.1' 이 'Rule-8.13' 에 걸려 멀쩡한 지침을 폐기한다
        #    (MISRA 는 8.1 과 8.10~8.14 가 동시에 실재한다). 뒤에 숫자가 안 오는 경우만 매치.
        if rule and re.search(rf"{re.escape(rule)}(?![0-9])", candidate):
            return "mandatory_deviation_suggested"
    return None


def generate_conflict_advice(
    *,
    conflict: Dict[str, Any],
    cooccurrence_excerpts: List[Dict[str, Any]],
    window_diffs: List[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]] = None,
    agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """상충 지침 생성. 반환 {advice|None, ai_enriched, enrich_reason, model}.

    호출 1회(재시도 없음), 실패는 결정론 폴백 — 지식 테이블의 mechanism/resolutions는
    라우터가 이미 반환하므로 LLM이 없어도 화면은 비지 않는다.
    """
    if cfg is None:
        try:
            from workflow.impact_ai_guide import _load_impact_oai_config
            cfg = _load_impact_oai_config()
        except Exception:
            logger.warning("rule-conflict-advice LLM config 해석 실패 — 결정론 폴백", exc_info=True)
            cfg = None
    model = resolve_effective_model(cfg)
    if not cfg:
        return {"advice": None, "ai_enriched": False, "enrich_reason": "llm_unavailable", "model": model}

    fixing = conflict.get("fixing") or []
    risk = conflict.get("risk") or []
    try:
        if agent_call is None:
            from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415
        from prompts import load_prompt

        system = load_prompt("summary_rule_conflict_advice")
        evidence_text = build_conflict_evidence_text(cooccurrence_excerpts, window_diffs)
        payload = json.dumps({
            "conflict_id": conflict.get("id"),
            "kind": conflict.get("kind"),
            "fixing_rules": [
                {k: m.get(k) for k in ("rule", "title", "category", "count")} for m in fixing
            ],
            "risk_rules": [
                {k: m.get(k) for k in ("rule", "title", "category", "count")} for m in risk
            ],
            "known_mechanism": conflict.get("mechanism"),
            "known_resolutions": conflict.get("resolutions"),
            "metric_risk": conflict.get("metric_risk"),
            "evidence_tier": conflict.get("tier"),
            # 손댈 수 없는 파일의 몫 — 실측에서 한 상충의 위반 256건이 **전부** 자동 생성
            # 파일이었다. 그걸 모르면 "코드를 이렇게 고치라"는 지침이 통째로 헛것이 된다.
            "generated_code_share": {
                k: (conflict.get("generated") or {}).get(k)
                for k in ("violations", "attributed_total")
            },
        }, ensure_ascii=False) + "\n\n" + evidence_text
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="summary_rule_conflict_advice")
        parsed = _extract_json_payload(output or "")
        if not isinstance(parsed, dict) or not str(parsed.get("tradeoff") or "").strip():
            return {"advice": None, "ai_enriched": False, "enrich_reason": "llm_empty_or_invalid", "model": model}
        # 환각 필터의 rule 에코 비교는 단일 규칙 산출물 기준이라 여기선 쓰지 않는다
        # (상충은 규칙이 여럿이다) — 코드 식별자 검사만 적용한다.
        reject = code_hallucination_check(
            {k: v for k, v in parsed.items() if k != "rule"}, evidence_text, "",
            code_keys=("both_satisfying_pattern",),
        )
        if reject:
            return {"advice": None, "ai_enriched": False, "enrich_reason": reject, "model": model}
        reject = deviation_sanity_check(parsed, fixing + risk)
        if reject:
            return {"advice": None, "ai_enriched": False, "enrich_reason": reject, "model": model}
        conf = str(parsed.get("confidence") or "low").lower()
        advice = {
            "tradeoff": str(parsed.get("tradeoff") or ""),
            "both_satisfying_pattern": str(parsed.get("both_satisfying_pattern") or ""),
            "recommended_order": str(parsed.get("recommended_order") or ""),
            "deviation_candidate": str(parsed.get("deviation_candidate") or ""),
            "residual_risk": str(parsed.get("residual_risk") or ""),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        }
        return {"advice": advice, "ai_enriched": True, "enrich_reason": None, "model": model}
    except Exception:
        logger.warning("rule-conflict-advice enrichment 실패 — 결정론 폴백", exc_info=True)
        return {"advice": None, "ai_enriched": False, "enrich_reason": "llm_error", "model": model}
