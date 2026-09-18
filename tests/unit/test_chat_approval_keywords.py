"""승인 게이트 키워드 false positive 정제 회귀 (R1).

risky_keyword(수정/edit/배포 등)가 들어 있어도 '방법/어떻게/알려' 같은 정보성
질문은 실행 요청이 아니므로 승인 게이트를 띄우지 않는다. 명령형(해줘/진행해)이
있으면 그대로 승인.
"""
from __future__ import annotations

import pytest

import backend.services.assistant_service as svc


def _has_approval(question: str, ui_context=None) -> bool:
    r = svc._build_approval_request(
        question=question, question_type="general", ui_context=ui_context or {},
    )
    return r is not None


@pytest.mark.parametrize("question", [
    "수정 방법을 알려줘",
    "이 함수 어떻게 수정하나요?",
    "수정된 내용 보여줘",
    "배포 방법이 뭐야",
    "커밋 메시지 작성 방법 설명해",  # '작성'은 risky 아님, '방법/설명' 정보성
    "how to modify this function",
])
def test_informational_questions_no_approval(question):
    assert _has_approval(question) is False


@pytest.mark.parametrize("question", [
    "파일을 수정해줘",
    "커밋해줘",
    "지금 배포해",
    "git push 진행해",
    "이 변경을 커밋하고 푸시해주세요",
])
def test_imperative_requests_require_approval(question):
    assert _has_approval(question) is True


def test_no_risky_keyword_no_approval():
    assert _has_approval("커버리지 현황 알려줘") is False
    assert _has_approval("실패한 테스트가 뭐야") is False


def test_force_approval_overrides_informational():
    """force_approval 이면 정보성 질문이어도 승인 게이트(명시적 강제)."""
    assert _has_approval("수정 방법 알려줘", ui_context={"force_approval": True}) is True


def test_is_informational_question_unit():
    assert svc._is_informational_question("수정 방법 알려줘") is True
    assert svc._is_informational_question("어떻게 배포하나요") is True
    assert svc._is_informational_question("수정해줘") is False
    assert svc._is_informational_question("배포 진행해") is False
