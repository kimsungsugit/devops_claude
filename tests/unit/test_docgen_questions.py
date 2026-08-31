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
         "reason": "통합 흐름 상한",
         "measured": {"api_default": 120, "generator_default": 120, "adjustable": True}},
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
         "reason": "통합 흐름 상한",
         "measured": {"api_default": 120, "generator_default": 120, "adjustable": True}},
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


def test_settled_cap_is_not_asked_again() -> None:
    """스텝이 `ok` 면 질문 목록에도 없어야 한다 — **두 목소리 금지**.

    예전엔 캡이 늘 `needed` 라 이 분기가 사실상 항상 참이었다. 이제 상한이 전량을
    담으면 `ok` 가 나오는데, 그때도 "조정할까요?" 를 물으면 준비 패널은 ✓ 를 그리고
    질문 목록은 결정을 요구한다 — 같은 사실에 화면이 두 말을 한다.
    """
    steps = [
        {"id": "cap_max_flows", "phase": "decision", "state": "ok", "label": "max_flows",
         "reason": "통합 흐름 상한",
         "measured": {"api_default": 120, "generator_default": 120, "adjustable": True,
                      "user_value": 145}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    assert not [i for i in out["questions"] if i["id"] == "cap_max_flows"], out["questions"]


def test_unmeasured_cap_asks_to_measure_not_to_choose() -> None:
    """못 잰 상한에 "조정할까요?" 를 물으면 **조정에 필요한 수를 못 주면서** 결정을
    요구하는 꼴이다. 먼저 할 일은 재는 것이고, 질문 제목이 그렇게 말해야 한다."""
    steps = [
        {"id": "cap_max_flows", "phase": "decision", "state": "unmeasured", "label": "max_flows",
         "reason": "통합 흐름 상한 (전량을 아직 재지 않아 이 상한이 자르는지 알 수 없습니다)",
         "measured": {"api_default": 120, "generator_default": 120, "adjustable": True}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_flows")
    assert "재지 않았습니다" in cap["title"], cap["title"]
    assert "조정할까요" not in cap["title"], cap["title"]


def test_unadjustable_cap_is_still_disclosed_when_ok() -> None:
    """조정 못 하는 상한은 `ok` 여도 남긴다 — 그건 결정이 아니라 **공시**이고,
    그 행이 존재하는 이유 자체다(음성 대조군: 위 suppression 이 과하게 먹지 않는가)."""
    steps = [
        {"id": "cap_max_steps_per_tc", "phase": "decision", "state": "ok",
         "label": "max_steps_per_tc", "reason": "TC 당 스텝 상한",
         "measured": {"api_default": None, "generator_default": 15, "adjustable": False,
                      "adjust_via": "코드 상수로 고정돼 있어 화면에서 바꿀 수단이 없습니다"}},
    ]
    out = q.build_questions("sts", steps, use_llm=False)
    assert [i for i in out["questions"] if i["id"] == "cap_max_steps_per_tc"]


def test_boundary_does_not_resurrect_a_false_cut_claim() -> None:
    """여유 0 이라도 **상한이 전량을 담으면** "지금 잘리고 있습니다" 는 거짓이다.

    `at_boundary` 는 흐름 수와 상한이 **같다**는 뜻이라 아직 잘린 것이 없다. 예전 문구는
    그 상태에도 "지금 잘리고 있습니다"(severity high)를 냈다. 경계 경고 자체는 준비
    패널의 `sits_flows` 행(`여유가 없습니다`)이 계속 들고 있으므로 여기서 중복하지 않는다.
    """
    steps = [
        {"id": "sits_flows", "phase": "material", "state": "degraded", "label": "통합 흐름",
         "measured": {"value": 145, "of": 145, "headroom": 0}},
        {"id": "cap_max_flows", "phase": "decision", "state": "ok", "label": "max_flows",
         "reason": "통합 흐름 상한",
         "measured": {"api_default": 120, "generator_default": 120, "adjustable": True,
                      "user_value": 145}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    assert not [i for i in out["questions"] if i["id"] == "cap_max_flows"]


def test_real_cut_still_raises_a_high_severity_question() -> None:
    """음성 대조군 — **진짜 잘리는** 경우(상한 미설정 + 흐름 초과)는 그대로 high 다.
    위 억제가 과하게 먹어 진짜 경고까지 지우지 않는지 본다."""
    steps = [
        {"id": "sits_flows", "phase": "material", "state": "degraded", "label": "통합 흐름",
         "measured": {"value": 145, "of": 120, "headroom": -25}},
        {"id": "cap_max_flows", "phase": "decision", "state": "needed", "label": "max_flows",
         "reason": "통합 흐름 상한 — 전량 145 중 25개가 빠집니다",
         "measured": {"api_default": 120, "generator_default": 120, "adjustable": True,
                      "suggested": 145, "below_full": 25}},
    ]
    out = q.build_questions("sits", steps, use_llm=False)
    cap = next(i for i in out["questions"] if i["id"] == "cap_max_flows")
    assert cap["severity"] == "high"
    assert "지금 잘리고 있습니다" in cap["title"]


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """캐시가 **무한히 자라지 않는다.**

    키는 측정값 전체의 해시라 상한 입력칸을 한 번 blur 할 때마다 새 키가 생긴다. TTL 만
    두면 만료된 항목도 *다시 조회될 때만* 버려지므로, 한 번 쓰고 안 돌아오는 키는
    프로세스 수명 내내 남는다(이 서버는 `--reload` 없이 며칠씩 떠 있다).

    ⚠ 관측량은 "코드에 상한 상수가 있다" 가 아니라 **실제 사전 크기**다 — 상수만 보면
      sweep 을 지워도 통과한다.
    """
    monkeypatch.setattr(q, "_CACHE_MAX", 8)
    for i in range(60):
        steps = [{"id": "cap_max_flows", "phase": "decision", "state": "needed",
                  "label": "max_flows", "reason": "흐름 상한",
                  "measured": {"api_default": 120, "generator_default": 120,
                               "adjustable": True, "user_value": i}}]
        q.build_questions("sits", steps, use_llm=False)
    assert len(q._CACHE) <= 8, f"캐시가 상한을 넘었다: {len(q._CACHE)}"


def test_cache_evicts_the_oldest_not_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """상한을 넘겨도 **최근에 쓴 키는 살아남는다**(LRU 이지 통째 비우기가 아니다).

    ⚠ 이 단언이 없으면 위 크기 테스트는 `_CACHE.clear()` 로도 통과한다 — 캐시가 있으나
      마나 해지고 LLM 을 행 펼침마다 부르게 된다. 그래서 **상한을 실제로 넘긴 뒤**
      오래된 키가 빠지고 최근 키가 남는 것을 함께 본다(뮤테이션 M54 가 여기서 죽는다).
    """
    monkeypatch.setattr(q, "_CACHE_MAX", 4)

    def ask(n):
        return q.build_questions("sits", [{
            "id": "cap_max_flows", "phase": "decision", "state": "needed",
            "label": "max_flows", "reason": "흐름 상한",
            "measured": {"api_default": 120, "generator_default": 120,
                         "adjustable": True, "user_value": n}}], use_llm=False)

    first = ask(1)
    for n in (2, 3, 4):
        ask(n)
    assert ask(1) is first, "상한 안에서는 그대로 있어야 한다"   # 1 을 맨 뒤로

    ask(5)      # 상한 초과 → 가장 오래된 2 가 빠진다
    ask(6)      # → 3 이 빠진다
    assert len(q._CACHE) == 4
    # 방금 쓴 쪽은 살아 있다(clear() 뮤턴트는 여기서 죽는다).
    assert ask(6) is not None and ask(1) is first
    # 가장 오래된 것은 빠졌다(= 아무것도 안 버리는 뮤턴트는 크기 단언에서 죽는다).
    assert ask(2) is not first


def test_expired_entries_are_dropped_not_just_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """만료된 항목은 **버려진다** — 읽을 때 무시만 하면 자리를 계속 차지한다."""
    monkeypatch.setattr(q, "_CACHE_TTL_S", -1.0)   # 넣는 즉시 만료
    for i in range(5):
        q.build_questions("sits", [{"id": "cap_max_flows", "phase": "decision", "state": "needed",
                                    "label": "max_flows", "reason": "흐름 상한",
                                    "measured": {"api_default": 120, "generator_default": 120,
                                                 "adjustable": True, "user_value": i}}],
                          use_llm=False)
    assert len(q._CACHE) <= 1, f"만료분이 쌓였다: {len(q._CACHE)}"
