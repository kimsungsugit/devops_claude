"""LLM 질문층 — **LLM 이 숫자를 만들지 못하게** 하는 것이 이 파일의 본체다.

측정·판정·수치는 코드가, 문장화만 LLM 이 한다. ISO 26262 증거에 LLM 이 지어낸 수치가
섞이면 그 자체가 거짓 증거이므로, 응답에 프롬프트 밖 숫자가 있으면 통째로 버리고 룰
문장으로 폴백한다. 그리고 **폴백은 선택이 아니라 필수다** — LLM 이 없거나 죽어도 화면은
살아 있어야 한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.services import docgen_questions as q


@pytest.fixture(autouse=True)
def _clean_cache():
    q.clear_cache()
    yield
    q.clear_cache()


def _steps() -> List[Dict[str, Any]]:
    return [
        {"id": "swds", "phase": "input", "state": "needed", "label": "SwDS(설계서)",
         "effect": "ASIL·Related·설명의 SwDS 출처가 빠집니다"},
        {"id": "cap_max_subcases", "phase": "decision", "state": "needed",
         "label": "max_subcases", "reason": "TC 당 sub-case 상한",
         "measured": {"api_default": 7, "generator_default": 14}},
        {"id": "chain_asil", "phase": "chain", "state": "degraded", "label": "ASIL 등급 출처",
         "chain": [
             {"source": "comment", "input": "source_comment", "input_label": "소스 주석",
              "have": False, "grounded": True},
             {"source": "sds", "input": "swds", "input_label": "SwDS(설계서)",
              "have": False, "grounded": True},
         ]},
        {"id": "form_release_sw_version", "phase": "decision", "state": "needed",
         "label": "release_sw_version"},
    ]


# ── 숫자 지어내기 방지 ──────────────────────────────────────────────────────

def test_numbers_from_facts_are_allowed() -> None:
    facts = {"functions": 435, "documented": 82}
    assert q.invented_numbers("함수 435개 중 82개에 주석이 있습니다", facts) == []


def test_invented_number_is_detected() -> None:
    """프롬프트에 없던 수치는 잡아야 한다 — 사용자는 그걸 측정값으로 읽는다."""
    facts = {"functions": 435}
    assert "200" in q.invented_numbers("435개 중 200개가 비었습니다", facts)


def test_decimal_notation_variants_are_same_value() -> None:
    """`2.80` 과 `2.8` 은 같은 값이다 — 표기 차이로 오탐을 내면 폴백만 남는다."""
    facts = {"pct": 2.8}
    assert q.invented_numbers("비율은 2.80% 입니다", facts) == []


def test_empty_text_has_no_invention() -> None:
    assert q.invented_numbers("", {"a": 1}) == []


def test_llm_body_rejected_when_it_invents(monkeypatch: pytest.MonkeyPatch) -> None:
    """지어낸 수치가 있으면 **통째로 버린다** — 일부만 지우면 문맥이 깨진 채 남는다."""
    monkeypatch.setattr(
        "workflow.ai.agent_call_text",
        lambda *a, **k: "함수 435개 중 999개가 비어 있습니다",
        raising=False,
    )
    question = {"title": "t", "body": "기본", "facts": {"functions": 435}}
    assert q._llm_body({"model": "x"}, question) is None


def test_llm_body_accepted_when_grounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "workflow.ai.agent_call_text",
        lambda *a, **k: "함수 435개가 대상입니다. SwDS 를 연결하면 채워집니다.",
        raising=False,
    )
    question = {"title": "t", "body": "기본", "facts": {"functions": 435}}
    assert q._llm_body({"model": "x"}, question) is not None


# ── 폴백 ────────────────────────────────────────────────────────────────────

def test_questions_work_without_llm() -> None:
    """LLM 을 끄면 룰 문장으로 나온다 — 화면이 LLM 에 의존해 죽으면 안 된다."""
    out = q.build_questions("sits", _steps(), use_llm=False)
    assert out["questions"], "질문이 하나도 안 나왔다"
    assert out["llm_used"] is False
    assert out["llm_reason"]
    for item in out["questions"]:
        assert item["generated_by"] == "rule"
        assert item["body"].strip()


def test_llm_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 이 예외를 던져도 질문은 나온다."""
    def _boom(*_a, **_k):
        raise RuntimeError("no api key")
    monkeypatch.setattr("workflow.ai.load_oai_config", lambda *_a, **_k: {"model": "x"},
                        raising=False)
    monkeypatch.setattr("workflow.ai.agent_call_text", _boom, raising=False)
    out = q.build_questions("sits", _steps(), use_llm=True)
    assert out["questions"]
    assert out["llm_used"] is False
    assert all(i["generated_by"] == "rule" for i in out["questions"])


def test_generated_by_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """문장의 출처를 숨기지 않는다 — 화면이 "AI 가 썼다" 를 표시할 수 있어야 한다."""
    monkeypatch.setattr("workflow.ai.load_oai_config", lambda *_a, **_k: {"model": "x"},
                        raising=False)
    monkeypatch.setattr("workflow.ai.agent_call_text",
                        lambda *a, **k: "SwDS 를 연결하면 됩니다.", raising=False)
    out = q.build_questions("sits", _steps(), use_llm=True)
    assert out["llm_used"] is True
    assert any(i["generated_by"] == "llm" for i in out["questions"])


# ── 질문 내용 ───────────────────────────────────────────────────────────────

def test_asil_choice_never_offers_qm() -> None:
    """근거 부재를 QM(안전 관련 아님)으로 바꾸면 under-classification 이다."""
    out = q.build_questions("uds", _steps(), use_llm=False)
    asil = next(i for i in out["questions"] if i["id"] == "accept_tbd_asil")
    values = {o["value"] for o in asil["options"]}
    labels = " ".join(o["label"] for o in asil["options"])
    assert "qm" not in {v.lower() for v in values}
    assert "QM" not in labels
    assert "tbd" in values


def test_missing_optional_input_becomes_confirm() -> None:
    out = q.build_questions("uds", _steps(), use_llm=False)
    swds = next(i for i in out["questions"] if i["id"] == "proceed_without_swds")
    assert swds["kind"] == "confirm"
    # 없이 진행할 때의 영향이 문장에 있어야 결정할 수 있다.
    assert "SwDS 출처가 빠집니다" in swds["body"]


def test_cap_question_exposes_both_defaults() -> None:
    """API 기본값이 생성기 기본값보다 작다는 사실이 질문에 담겨야 한다."""
    out = q.build_questions("sits", _steps(), use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_subcases")
    assert cap["facts"]["api_default"] == 7
    assert cap["facts"]["generator_default"] == 14


def test_release_version_is_never_defaulted() -> None:
    """임의 버전을 찍으면 납품 문서 표지에 틀린 릴리스가 박힌다."""
    out = q.build_questions("sutr", _steps(), use_llm=False)
    ver = next(i for i in out["questions"] if i["id"] == "form_release_sw_version")
    assert "임의 값으로 채우지 않습니다" in ver["body"]
    assert ver["severity"] == "high"


def test_no_steps_yields_no_questions() -> None:
    out = q.build_questions("uds", [], use_llm=False)
    assert out["questions"] == []
    assert out["llm_reason"]


def test_flow_cap_at_boundary_is_high_severity() -> None:
    """이미 잘리고 있으면 심각도가 올라간다.

    실측(kjpds02_pv): 흐름 145 / 캡 120 → **여유 -25**. 안전등급 높은 흐름까지 규격에서
    사라질 수 있는데 `medium` 으로 두면 사용자가 지나친다.
    """
    steps = [
        {"id": "sits_flows", "phase": "material", "state": "degraded", "label": "통합 흐름",
         "measured": {"value": 145, "of": 120, "headroom": -25}},
        {"id": "cap_max_flows", "phase": "decision", "state": "needed", "label": "max_flows",
         "reason": "통합 흐름 상한", "measured": {"api_default": None, "generator_default": 120}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_flows")
    assert cap["severity"] == "high"
    assert cap["facts"]["headroom"] == -25
    assert "잘리고" in cap["title"] or "빠집니다" in cap["body"]


def test_flow_cap_with_headroom_stays_medium() -> None:
    steps = [
        {"id": "sits_flows", "phase": "material", "state": "ok", "label": "통합 흐름",
         "measured": {"value": 84, "of": 120, "headroom": 36}},
        {"id": "cap_max_flows", "phase": "decision", "state": "needed", "label": "max_flows",
         "reason": "통합 흐름 상한", "measured": {"api_default": None, "generator_default": 120}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_flows")
    assert cap["severity"] == "medium"


def test_unadjustable_cap_says_so() -> None:
    """`api_default is None` 은 "API 가 안 받는다" 이지 "값이 비었다" 가 아니다.

    라이브에서 **"현재 None 이고"** 로 나왔다 — 사용자에게 아무 뜻도 아니다.
    """
    steps = [
        {"id": "cap_max_flows", "phase": "decision", "state": "needed", "label": "max_flows",
         "reason": "상한", "measured": {"api_default": None, "generator_default": 120}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_flows")
    assert "None" not in cap["body"]
    assert "조정할 수 없" in cap["body"]


def test_facts_carry_measurements_not_prose() -> None:
    """`facts` 는 코드가 채운 측정값이다 — 여기 문장이 섞이면 검증이 무의미해진다."""
    out = q.build_questions("sits", _steps(), use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_subcases")
    assert set(cap["facts"]) >= {"cap", "api_default", "generator_default"}
