"""AI 응답 검증 레이어

⚠ **이 모듈은 프로덕션에서 호출되지 않는다**(2026-07-30 확인 — importer 는
`tests/unit/test_ai_validator.py` 뿐). 아래 목록은 **제공하는 API** 이지 지금 돌고 있는
검사가 아니다. "민감정보 노출 방지" 를 하고 있다고 읽으면 안 된다.

실제로 도는 것은 다른 곳에 있다:
  · 나가는 프롬프트의 시크릿 가리기 → `workflow/ai.py::sanitize_messages`
    (정규식 추측이 아니라 **env 의 실제 값과 대조** — 여기 `_check_safety` 의
     `password\\s*[=:]` · IP 정규식은 이 저장소에선 오탐이 심하다. 프롬프트에
     Jenkins URL 과 C 소스가 늘 들어가 거의 매 호출 경고가 뜬다 = 소음)
  · 응답 완결성(절단·차단) → `workflow/ai.py::note_finish_reason_value`
  · 환각 차단 allow-list → `workflow/rule_fix_example.py::code_hallucination_check`
  · 근거 정합 → `workflow/llm_semantic_validator.py`

제공 API(미사용):
- 구조 검증: JSON 파싱, 필수 필드 확인
- 품질 검증: 최소 길이, 언어 일관성, 할루시네이션 감지
- 안전성 검증: 코드 인젝션, 민감정보 노출 방지 — **응답**만 보고 경고만 낸다(차단 아님)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable


@dataclass
class ValidationResult:
    """검증 결과"""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    cleaned_text: str = ""

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def validate_llm_response(
    response: Optional[str],
    *,
    min_length: int = 10,
    max_length: int = 50000,
    expected_format: str = "text",  # "text", "json", "code"
    required_fields: List[str] = None,
    language_hint: str = "ko",  # "ko", "en", "any"
    context_keywords: List[str] = None,
    banned_patterns: List[str] = None,
) -> ValidationResult:
    """Validate LLM response quality and structure.

    Args:
        response: Raw LLM output
        min_length: Minimum acceptable length
        max_length: Maximum acceptable length
        expected_format: Expected output format
        required_fields: Required JSON fields (for json format)
        language_hint: Expected language
        context_keywords: Keywords that should appear in response
        banned_patterns: Regex patterns that should NOT appear
    """
    result = ValidationResult()

    if response is None or not response.strip():
        result.add_error("LLM 응답이 비어있습니다")
        return result

    text = response.strip()
    result.cleaned_text = text

    # Length check
    if len(text) < min_length:
        result.add_error(f"응답이 너무 짧습니다 ({len(text)}자 < {min_length}자)")
    if len(text) > max_length:
        result.add_warning(f"응답이 너무 깁니다 ({len(text)}자). {max_length}자로 잘립니다")
        text = text[:max_length]
        result.cleaned_text = text

    # Format validation
    if expected_format == "json":
        result = _validate_json(text, result, required_fields)
    elif expected_format == "code":
        result = _validate_code(text, result)

    # Hallucination detection
    result = _check_hallucination(text, result)

    # Safety check
    result = _check_safety(text, result, banned_patterns)

    # Language consistency
    if language_hint != "any":
        result = _check_language(text, result, language_hint)

    # Context relevance
    if context_keywords:
        result = _check_relevance(text, result, context_keywords)

    # Clean markdown artifacts
    result.cleaned_text = _clean_markdown_artifacts(result.cleaned_text)

    return result


def validate_function_description(description: str, function_name: str = "") -> ValidationResult:
    """Validate AI-generated function description."""
    result = validate_llm_response(
        description,
        min_length=20,
        max_length=2000,
        language_hint="ko",
        banned_patterns=[
            r"(?i)I (don't|cannot|can't) ",
            r"(?i)as an AI",
            r"(?i)I'm sorry",
        ],
    )

    if result.valid and function_name:
        # Check if description seems relevant to the function
        name_parts = re.split(r'[_A-Z]', function_name)
        name_parts = [p.lower() for p in name_parts if len(p) > 2]
        if name_parts and not any(p in description.lower() for p in name_parts[:3]):
            result.add_warning(f"설명이 함수 '{function_name}'와 관련 없어 보입니다")

    return result


def validate_test_case(test_json: str, source_context: str = "") -> ValidationResult:
    """Validate AI-generated test case."""
    result = validate_llm_response(
        test_json,
        min_length=50,
        expected_format="json",
        required_fields=["test_name", "inputs", "expected"],
    )

    if result.valid:
        try:
            data = json.loads(result.cleaned_text)
            if isinstance(data, dict):
                if not data.get("test_name"):
                    result.add_error("test_name이 비어있습니다")
                if not data.get("inputs") and not data.get("expected"):
                    result.add_warning("inputs과 expected가 모두 비어있습니다")
        except json.JSONDecodeError:
            pass  # already handled in format validation

    return result


def validate_evidence_grounding(
    text: str,
    evidence: List[Dict[str, Any]],
    *,
    function_set: Optional[Any] = None,  # set / frozenset / None
    file_resolver: Optional[Any] = None,
) -> ValidationResult:
    """라운드 C T507: evidence grounding facade — llm_semantic_validator wrapping.

    `workflow.llm_semantic_validator.validate_evidence`를 ai_validator의
    `ValidationResult` 형식으로 변환. uds_ai.py + ai_validator.py 양쪽에서
    호출 가능. `[semantic]` prefix warning을 ValidationResult.warnings로 push —
    `warning_categories` breakdown 자동 통합.

    function_set None이면 함수명 매칭 skip (회귀 fixture 환경 호환).
    file_resolver None이면 source_file 존재 검증 skip.

    Args:
        text: LLM 응답 텍스트 (현재는 사용 안 함, 향후 evidence와 text 일치성
            검증 확장용).
        evidence: ``[{source_type, source_file, excerpt, score}, ...]``.
        function_set: c_parser parse_c_project 결과의 function 이름 set.
        file_resolver: backend.services.file_resolver.get_resolver() 반환 객체.

    Returns:
        ValidationResult — valid=True (semantic warning만이라 reject 안 함),
        warnings에 [semantic] prefix 메시지 push.
    """
    result = ValidationResult()
    result.cleaned_text = text or ""
    if not evidence:
        return result  # evidence 없으면 _quality_warnings가 별도 처리
    try:
        from workflow.llm_semantic_validator import validate_evidence as _sem_validate
    except ImportError:
        result.add_warning("[semantic] validator 미설치 — 검증 skip")
        return result
    sem_report = _sem_validate(
        evidence, function_set=function_set, file_resolver=file_resolver,
    )
    for msg in sem_report.warning_messages:
        result.add_warning(msg)
    if not sem_report.passed:
        result.add_warning(
            f"[semantic] score={sem_report.score:.2f} (passed=False)"
        )
    return result


def retry_with_validation(
    llm_fn: Callable[..., Optional[str]],
    validator: Callable[[str], ValidationResult],
    max_retries: int = 2,
    **llm_kwargs,
) -> tuple:
    """Call LLM with automatic retry on validation failure.

    Returns: (cleaned_text, validation_result)
    """
    last_result = ValidationResult()
    last_result.add_error("모든 시도 실패")

    for attempt in range(max_retries + 1):
        response = llm_fn(**llm_kwargs)
        if response is None:
            continue

        result = validator(response)
        if result.valid:
            return result.cleaned_text, result

        last_result = result

    return "", last_result


# ── Internal validators ──────────────────────────────────────────────

def _validate_json(text: str, result: ValidationResult, required_fields: List[str] = None) -> ValidationResult:
    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    result.cleaned_text = cleaned

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        result.add_error(f"JSON 파싱 실패: {e}")
        return result

    if required_fields and isinstance(data, dict):
        missing = [f for f in required_fields if f not in data]
        if missing:
            result.add_error(f"필수 필드 누락: {', '.join(missing)}")

    return result


def _validate_code(text: str, result: ValidationResult) -> ValidationResult:
    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:\w+)?\s*\n?', '', text.strip())
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    result.cleaned_text = cleaned

    # Basic syntax check for C code
    if '{' in cleaned and '}' in cleaned:
        open_count = cleaned.count('{')
        close_count = cleaned.count('}')
        if abs(open_count - close_count) > 2:
            result.add_warning(f"중괄호 불균형: {{ {open_count}개, }} {close_count}개")

    return result


def _check_hallucination(text: str, result: ValidationResult) -> ValidationResult:
    """Detect common LLM hallucination patterns."""
    patterns = [
        (r"(?:https?://)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?", "URL이 포함되어 있습니다 (할루시네이션 가능)"),
        (r"\b(?:version|v)\s*\d+\.\d+\.\d+", "버전 번호가 포함되어 있습니다 (검증 필요)"),
        (r"(?i)according to (?:the )?(?:documentation|manual|spec)", "외부 문서 참조 (검증 필요)"),
    ]
    for pattern, msg in patterns:
        if re.search(pattern, text):
            result.add_warning(msg)
    return result


def _check_safety(text: str, result: ValidationResult, banned: List[str] = None) -> ValidationResult:
    """Check for unsafe content."""
    # Sensitive data patterns
    sensitive = [
        (r'(?i)(?:password|passwd|secret)\s*[=:]\s*\S+', "비밀번호/시크릿이 포함되어 있습니다"),
        (r'(?i)api[_-]?key\s*[=:]\s*["\']?\S{20,}', "API 키가 포함되어 있습니다"),
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', "IP 주소가 포함되어 있습니다"),
    ]
    for pattern, msg in sensitive:
        if re.search(pattern, text):
            result.add_warning(msg)

    if banned:
        for pattern in banned:
            if re.search(pattern, text):
                result.add_error(f"금지된 패턴 감지: {pattern}")

    return result


def _check_language(text: str, result: ValidationResult, lang: str) -> ValidationResult:
    """Check language consistency."""
    if lang == "ko":
        # Check if Korean characters are present (at least 10% for mixed docs)
        korean_chars = len(re.findall(r'[\uac00-\ud7af]', text))
        total_alpha = len(re.findall(r'[a-zA-Z\uac00-\ud7af]', text))
        if total_alpha > 50 and korean_chars / max(total_alpha, 1) < 0.05:
            result.add_warning("한국어 콘텐츠가 거의 없습니다 (영어 응답일 수 있음)")
    return result


def _check_relevance(text: str, result: ValidationResult, keywords: List[str]) -> ValidationResult:
    """Check if response is relevant to context."""
    text_lower = text.lower()
    found = sum(1 for kw in keywords if kw.lower() in text_lower)
    if keywords and found / len(keywords) < 0.2:
        result.add_warning(f"컨텍스트 키워드 매칭률 낮음: {found}/{len(keywords)}")
    return result


def _clean_markdown_artifacts(text: str) -> str:
    """Remove common markdown/LLM artifacts from response."""
    # Remove thinking tags
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    # Remove triple backtick fences (already content)
    text = re.sub(r'^```\w*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    # Remove "Here is" / "Here's" preamble
    text = re.sub(r'^(?:Here(?:\'s| is) (?:the|a|an) \w+[^.]*\.\s*\n?)', '', text, flags=re.IGNORECASE)
    return text.strip()
