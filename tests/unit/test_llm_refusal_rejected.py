"""LLM 거절문이 UDS 설명 칸에 실리지 않는가 — §6 후보 10.

## 경위 — dead code 를 지우려다 그 안에서 유일하게 필요한 검사를 찾았다

`workflow/ai_validator.py` 는 프로덕션 호출자 0건이라 **한 번도 발화한 적이 없었다**.
공개 API 6개 중 4개는 이미 배선된 live 구현과 중복이었다:

| ai_validator API | 이미 있는 live 구현 |
|---|---|
| JSON fence-strip/파싱 | `summary_ai_insight._extract_json_payload` (5모듈) · `uds_ai._extract_json_payload` |
| evidence grounding facade | `uds_ai.py:11,795` 가 `llm_semantic_validator.validate_evidence` 를 **직접** 호출 |
| retry 루프 | `uds_ai.py:846-872` |
| 시크릿/환각 검사 | `ai.py::redact_known_secrets` · `sanitize_messages` |

중복이 아닌 것은 **거절문구 검사** 하나였고(한국어 비율 검사도 있었으나 판정 소비처
설계가 없다), 그 공백은 실측된다:

    _is_generic_description("I'm sorry, I cannot generate a description…") -> False
    len(그 문장) == 61  >  min_len(5 또는 10)                              -> 채택

즉 거절문이 AI 설명 채택 관문(`uds_ai.py::_process_batch`)을 통과하고, 그 뒤
`description_source="ai"` 는 신뢰 출처라 `function_analyzer._finalize_function_fields`
의 `trusted_desc` 화이트리스트에서 **내용검사를 면제**받아 원문 그대로 실린다.

## 과대 주장 금지 — 관측된 오염은 0건이다

`outputs/`·`.devops_pro_cache/` 의 JSON 에서 실제 거절문 오염 사례는 **0건 관측**이다.
납품 DOCX 는 zip 바이너리라 이 방법으로 확인하지 못했다(= 오염 여부 **측정 실패**,
"오염 없음" 아님). 이 파일이 고정하는 것은 *"오염이 일어났다"* 가 아니라
*"막는 검사가 없었고 이제 있다"* 이다.

## 가져오지 않은 것

`validate_function_description` 의 `min_length=20` 은 **의도적으로 제외**했다. 실사용
채택 기준이 `len > 5`(1패스) / `len > 10`(2패스)라, 20자로 올리면 6~20자 정상 한국어
설명이 새로 거절된다 — 고치려던 문제와 무관한 회귀다.

## 판정이 아니라 카운터였던 것 (정정)

조사 초안은 `_classify_description_quality(...) -> "high"` 를 게이트 뒤집힘으로 서술했다.
반증에서 확인: 그 함수의 프로덕션 유일 호출부는 `validation.py:747` 이고 결과는
`desc_high/desc_med/desc_low` **집계 증가에만** 쓰인다 — 아무것도 차단하지 않는다.
따라서 이 라운드가 움직이는 것은 **차단 동작**(uds_ai 채택 · trusted_desc 면제)이고,
품질 리포트 수치는 그 부수 효과다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report_gen.function_analyzer import (
    _LLM_REFUSAL_PATTERNS,
    _finalize_function_fields,
    _is_generic_description,
    is_llm_refusal,
)
from tests.unit._source_probe import source_of

# 패턴 하나당 **그 패턴만** 담은 표본. 한 문장이 여러 패턴을 동시에 만족하면 패턴을
# 지워도 다른 패턴이 덮어 뮤테이션이 살아남는다 — 실제로 그렇게 한 번 생존했다
# (`"죄송합니다. … 생성할 수 없습니다."` 가 두 패턴을 동시에 만족했다).
REFUSAL_SAMPLES = {
    "as an ai": "As an AI language model, I do not have access to the source.",
    "i'm sorry": "I'm sorry — the requested content is unavailable.",
    "i am sorry": "I am sorry, but that request is out of scope.",
    "i cannot": "I cannot produce that output.",
    "i can't": "I can't help with this request.",
    "죄송합니다": "죄송합니다. 다른 방식으로 시도해 주세요.",
    "제공할 수 없습니다": "요청하신 내용은 제공할 수 없습니다.",
    "생성할 수 없습니다": "해당 함수의 설명을 생성할 수 없습니다.",
    "답변할 수 없습니다": "이 질문에는 답변할 수 없습니다.",
}
REFUSALS = list(REFUSAL_SAMPLES.values())

LEGIT = [
    "버저 출력을 제어한다.",
    "ADC 채널을 초기화하고 변환을 시작한다.",
    "Controls the buzzer output based on the requested pattern.",
    "CAN 메시지를 파싱해 상태를 갱신한다.",
    # 경계 — 짧지만 정상. `min_length=20` 을 가져왔다면 여기서 거절됐을 것들.
    "버저를 끈다.",
    "타이머 리셋.",
]


class TestRefusalDetection:
    @pytest.mark.parametrize("text", REFUSALS)
    def test_refusals_are_detected(self, text):
        assert is_llm_refusal(text) is True

    def test_every_pattern_has_an_independent_sample(self):
        """패턴 목록과 표본이 **1:1** 이어야 한다.

        ⚠ 이 단언이 뮤테이션 M4(한국어 패턴 1개 삭제)를 잡는 장치다. 표본을 패턴
        목록에서 파생시키면 자기참조라 항상 통과한다 — 표본은 **독립 하드코딩**이고,
        여기서 양방향으로 맞춘다:
          - 패턴을 지우면 → 집합 불일치 + 그 표본의 탐지 실패
          - 패턴을 추가하고 표본을 안 만들면 → 집합 불일치
        """
        assert set(_LLM_REFUSAL_PATTERNS) == set(REFUSAL_SAMPLES), (
            "거절 패턴 목록과 표본이 어긋났다 — 표본 없는 패턴은 사실상 검증되지 않는다"
        )

    @pytest.mark.parametrize(("pattern", "sample"), sorted(REFUSAL_SAMPLES.items()))
    def test_each_pattern_is_individually_load_bearing(self, pattern, sample):
        """표본이 **그 패턴 하나로만** 잡히는지 — 겹치면 삭제를 못 잡는다."""
        matched = [p for p in _LLM_REFUSAL_PATTERNS if p in sample.lower()]
        assert matched == [pattern], (
            f"표본 {sample!r} 이 패턴 {matched} 에 동시에 걸린다 — 표본을 좁힐 것"
        )

    @pytest.mark.parametrize("text", LEGIT)
    def test_legitimate_descriptions_pass(self, text):
        assert is_llm_refusal(text) is False

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_empty_is_not_a_refusal(self, text):
        """빈 값은 '거절' 이 아니라 '없음' 이다 — 다른 축에서 처리한다."""
        assert is_llm_refusal(text) is False

    def test_case_insensitive(self):
        assert is_llm_refusal("I'M SORRY, I CANNOT DO THAT") is True

    def test_generic_pattern_list_does_not_cover_refusals(self):
        """상투구 목록으로는 안 잡힌다 — 별도 축이 필요한 이유(실측)."""
        for text in REFUSALS:
            assert _is_generic_description(text) is False, (
                f"{text!r} 가 상투구로 잡힌다면 별도 축이 불필요하다 — 전제를 다시 확인할 것"
            )


class TestAcceptanceGateRejectsRefusals:
    """`uds_ai::_process_batch` 의 채택 관문이 실제로 거절문을 거른다."""

    def test_batch_gate_calls_the_detector(self):
        from workflow import uds_ai

        source = source_of(uds_ai)
        assert "is_llm_refusal(desc)" in source, (
            "AI 설명 채택 관문이 거절문 검사를 안 부른다 — `len > min_len` 이 유일한 "
            "내용 관문으로 돌아갔다"
        )

    def test_min_length_gate_alone_would_accept_a_refusal(self):
        """대조군 — 길이 기준만으로는 못 막는다는 사실을 값으로 고정."""
        refusal = REFUSALS[0]
        assert len(refusal) > 10, "이 거절문이 짧아졌다면 다른 표본으로 바꿀 것"


class TestTrustedSourceNoLongerExemptsRefusals:
    """`description_source="ai"` 가 내용검사를 면제받던 마지막 구멍."""

    def test_ai_sourced_refusal_is_not_passed_through_verbatim(self):
        out = _finalize_function_fields({
            "name": "g_ap_buzzerctrl_func",
            "description": REFUSALS[0],
            "description_source": "ai",
        })
        assert out["description"] != REFUSALS[0], (
            "신뢰 출처라는 이유로 거절문이 원문 그대로 통과했다"
        )
        assert not is_llm_refusal(out["description"])

    def test_ai_sourced_legitimate_description_still_passes_through(self):
        """대조군 — 게이트가 `ai` 출처를 통째로 막은 게 아니다."""
        desc = "버저 출력을 제어한다."
        out = _finalize_function_fields({
            "name": "g_ap_buzzerctrl_func",
            "description": desc,
            "description_source": "ai",
        })
        assert out["description"] == desc

    @pytest.mark.parametrize("source", ["comment", "sds", "reference"])
    def test_other_trusted_sources_are_guarded_too(self, source):
        """출처와 무관하게 거절문은 신뢰 대상이 아니다."""
        out = _finalize_function_fields({
            "name": "g_ap_buzzerctrl_func",
            "description": REFUSALS[0],
            "description_source": source,
        })
        assert out["description"] != REFUSALS[0]


class TestDeadValidatorIsGone:
    """중복이던 5개 API 는 삭제됐다 — 되살아나면 다시 중복이 된다."""

    def test_module_is_deleted(self):
        assert not (Path(__file__).resolve().parents[2] / "workflow" / "ai_validator.py").exists(), (
            "`workflow/ai_validator.py` 가 되살아났다 — 6개 API 중 4개가 live 구현과 "
            "중복이라 배선하면 이중 검사가 된다. 되살릴 거면 중복부터 정리할 것"
        )

    def test_no_module_imports_it(self):
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            [sys.executable, "-c", "import workflow.ai_validator"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert out.returncode != 0, "삭제했는데 여전히 import 된다"
