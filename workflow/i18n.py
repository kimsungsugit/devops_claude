# workflow/i18n.py
"""Internationalization (i18n) support for document generation.

Provides language-specific labels, prompts, and templates for generating
UDS/STS/SUTS documents in multiple languages (Korean default, English option).
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ("ko", "en")
DEFAULT_LANGUAGE = os.environ.get("DOC_LANGUAGE", "ko")


_LABELS: Dict[str, Dict[str, str]] = {
    "ko": {
        "project_name": "프로젝트명",
        "overview": "개요",
        "requirements": "요구사항",
        "interfaces": "인터페이스",
        "function_table": "함수 테이블",
        "function_details": "함수 상세",
        "global_data": "전역 데이터",
        "unit_structure": "유닛 구조",
        "notes": "비고",
        "generated_at": "생성 일시",
        "description": "설명",
        "inputs": "입력",
        "outputs": "출력",
        "precondition": "사전조건",
        "called_functions": "호출 함수",
        "calling_functions": "피호출 함수",
        "logic_flow": "로직 흐름",
        "asil_level": "ASIL 등급",
        "related_requirements": "관련 요구사항",
        "test_case_id": "테스트 케이스 ID",
        "test_method": "테스트 방법",
        "test_steps": "테스트 절차",
        "expected_result": "기대 결과",
        "test_environment": "테스트 환경",
        "traceability": "추적성",
        "quality_report": "품질 리포트",
        "compliance": "준수율",
        "pass": "통과",
        "fail": "실패",
        "warning": "경고",
    },
    "en": {
        "project_name": "Project Name",
        "overview": "Overview",
        "requirements": "Requirements",
        "interfaces": "Interfaces",
        "function_table": "Function Table",
        "function_details": "Function Details",
        "global_data": "Global Data",
        "unit_structure": "Unit Structure",
        "notes": "Notes",
        "generated_at": "Generated At",
        "description": "Description",
        "inputs": "Inputs",
        "outputs": "Outputs",
        "precondition": "Precondition",
        "called_functions": "Called Functions",
        "calling_functions": "Calling Functions",
        "logic_flow": "Logic Flow",
        "asil_level": "ASIL Level",
        "related_requirements": "Related Requirements",
        "test_case_id": "Test Case ID",
        "test_method": "Test Method",
        "test_steps": "Test Steps",
        "expected_result": "Expected Result",
        "test_environment": "Test Environment",
        "traceability": "Traceability",
        "quality_report": "Quality Report",
        "compliance": "Compliance",
        "pass": "Pass",
        "fail": "Fail",
        "warning": "Warning",
    },
}

_AI_PROMPTS: Dict[str, Dict[str, str]] = {
    "ko": {
        "func_desc_system": "당신은 임베디드 C 소프트웨어 문서화 전문가입니다. 함수 설명을 한국어로 작성하세요.",
        "func_desc_instruction": "다음 C 함수들에 대해 한국어로 간결하고 정확한 설명을 작성하세요.",
        "test_case_system": "당신은 자동차 소프트웨어 테스트 전문가입니다. 한국어로 테스트 케이스를 작성하세요.",
    },
    "en": {
        "func_desc_system": "You are an embedded C software documentation expert. Write function descriptions in English.",
        "func_desc_instruction": "Write concise and accurate descriptions for the following C functions in English.",
        "test_case_system": "You are an automotive software testing expert. Write test cases in English.",
    },
}


def get_label(key: str, lang: Optional[str] = None) -> str:
    """Get a localized label string."""
    language = (lang or DEFAULT_LANGUAGE).lower()[:2]
    if language not in SUPPORTED_LANGUAGES:
        language = "ko"
    return _LABELS.get(language, _LABELS["ko"]).get(key, key)


def get_labels(lang: Optional[str] = None) -> Dict[str, str]:
    """Get all labels for a language."""
    language = (lang or DEFAULT_LANGUAGE).lower()[:2]
    if language not in SUPPORTED_LANGUAGES:
        language = "ko"
    return dict(_LABELS.get(language, _LABELS["ko"]))


def get_ai_prompt(key: str, lang: Optional[str] = None) -> str:
    """Get a localized AI prompt template."""
    language = (lang or DEFAULT_LANGUAGE).lower()[:2]
    if language not in SUPPORTED_LANGUAGES:
        language = "ko"
    return _AI_PROMPTS.get(language, _AI_PROMPTS["ko"]).get(key, "")


def localize_uds_payload(
    payload: Dict[str, Any],
    lang: Optional[str] = None,
) -> Dict[str, Any]:
    """Add localized field labels to a UDS payload for document generation."""
    labels = get_labels(lang)
    payload["_labels"] = labels
    payload["_language"] = (lang or DEFAULT_LANGUAGE).lower()[:2]
    return payload
