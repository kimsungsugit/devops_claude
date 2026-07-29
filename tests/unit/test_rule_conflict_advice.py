"""rule_conflict_advice — 상충 지침 생성의 사후 게이트.

프롬프트로 금지한 것은 지켜지지 않는다는 전제로, 서버가 **사후에도** 막아야 하는 것:
- mandatory 규칙을 예외(deviation) 후보로 지목한 지침 → 규격 위반을 권하는 셈이라 폐기
- 증거에 없는 식별자로 지어낸 코드 → 환각 필터(`code_hallucination_check` 단일 출처)
"""
from __future__ import annotations

import json

from workflow.rule_conflict_advice import (
    build_conflict_evidence_text,
    deviation_sanity_check,
    generate_conflict_advice,
)

_RULE_META = [
    {"rule": "Rule-15.5", "category": "advisory"},
    {"rule": "Rule-17.4", "category": "mandatory"},
    {"rule": "Rule-8.1", "category": "mandatory"},
]


def test_deviation_sanity_check_rejects_mandatory_target():
    assert deviation_sanity_check({"deviation_candidate": "Rule-17.4를 예외 신청"}, _RULE_META) \
        == "mandatory_deviation_suggested"


def test_deviation_sanity_check_allows_advisory_target():
    assert deviation_sanity_check({"deviation_candidate": "Rule-15.5를 예외로"}, _RULE_META) is None
    assert deviation_sanity_check({"deviation_candidate": ""}, _RULE_META) is None


def test_deviation_sanity_check_does_not_confuse_rule_8_1_with_8_13():
    """부분문자열 검사면 mandatory 'Rule-8.1'이 'Rule-8.13'에 걸려 멀쩡한 지침이 폐기된다."""
    assert deviation_sanity_check({"deviation_candidate": "Rule-8.13은 advisory라 예외 가능"}, _RULE_META) is None
    assert deviation_sanity_check({"deviation_candidate": "Rule-8.1 자체를 예외로"}, _RULE_META) \
        == "mandatory_deviation_suggested"


def test_evidence_text_is_single_source_for_prompt_and_filter():
    text = build_conflict_evidence_text(
        [{"file": "a.c", "text": "uint16_t u16s_LIN_FAIL_TM;"}],
        [{"file": "b.c", "text": "-int x;\n+uint8_t x;"}],
    )
    assert "동시 위반 파일 발췌 — a.c" in text
    assert "구간 변경 diff — b.c" in text
    assert "u16s_LIN_FAIL_TM" in text


_CONFLICT = {
    "id": "cast-cascade", "kind": "fix_induces", "tier": "cooccurrence",
    "fixing": [{"rule": "Rule-10.4", "title": "same type", "category": "required", "count": 26}],
    "risk": [{"rule": "Rule-10.8", "title": "composite cast", "category": "required", "count": 5}],
    "mechanism": "캐스팅이 복합식에 걸린다", "resolutions": ["단항 피연산자에 캐스팅"],
    "metric_risk": [],
}
_EXCERPTS = [{"file": "a.c", "text": "uint16_t u16s_LIN_FAIL_TM = 300U / u8g_T_MAIN;"}]


def _agent(payload: dict):
    return lambda cfg, msgs, **kw: json.dumps(payload, ensure_ascii=False)


def test_generate_conflict_advice_returns_advice_from_evidence(monkeypatch, tmp_path):
    out = generate_conflict_advice(
        conflict=_CONFLICT, cooccurrence_excerpts=_EXCERPTS, window_diffs=[],
        cfg={"model": "x"},
        agent_call=_agent({
            "tradeoff": "u16s_LIN_FAIL_TM 캐스팅이 10.8에 걸린다",
            "both_satisfying_pattern": "uint16_t u16s_LIN_FAIL_TM = (uint16_t)300U;",
            "recommended_order": "피연산자별 캐스팅 먼저",
            "deviation_candidate": "", "residual_risk": "가독성", "confidence": "high",
        }),
    )
    assert out["ai_enriched"] is True
    assert out["advice"]["tradeoff"].startswith("u16s_LIN_FAIL_TM")
    assert out["advice"]["confidence"] == "high"


def test_generate_conflict_advice_discards_hallucinated_code():
    out = generate_conflict_advice(
        conflict=_CONFLICT, cooccurrence_excerpts=_EXCERPTS, window_diffs=[],
        cfg={"model": "x"},
        agent_call=_agent({
            "tradeoff": "충돌한다",
            # 증거에 없는 식별자만으로 지어낸 코드
            "both_satisfying_pattern": "SomeUnknownStruct_t zzz = MakeUpHelper(alphaBeta, gammaDelta);",
            "confidence": "high",
        }),
    )
    assert out["advice"] is None and out["enrich_reason"] == "hallucinated_identifiers"


def test_generate_conflict_advice_discards_mandatory_deviation():
    conflict = {**_CONFLICT, "risk": [{"rule": "Rule-17.4", "category": "mandatory", "count": 0}]}
    out = generate_conflict_advice(
        conflict=conflict, cooccurrence_excerpts=_EXCERPTS, window_diffs=[],
        cfg={"model": "x"},
        agent_call=_agent({
            "tradeoff": "충돌한다", "both_satisfying_pattern": "",
            "deviation_candidate": "Rule-17.4에 대해 예외를 신청하라", "confidence": "high",
        }),
    )
    assert out["advice"] is None and out["enrich_reason"] == "mandatory_deviation_suggested"


def test_generate_conflict_advice_falls_back_without_llm():
    out = generate_conflict_advice(
        conflict=_CONFLICT, cooccurrence_excerpts=_EXCERPTS, window_diffs=[], cfg={},
    )
    assert out["advice"] is None and out["enrich_reason"] == "llm_unavailable"


def test_generate_conflict_advice_rejects_empty_llm_output():
    out = generate_conflict_advice(
        conflict=_CONFLICT, cooccurrence_excerpts=_EXCERPTS, window_diffs=[],
        cfg={"model": "x"}, agent_call=_agent({"tradeoff": "  "}),
    )
    assert out["advice"] is None and out["enrich_reason"] == "llm_empty_or_invalid"
