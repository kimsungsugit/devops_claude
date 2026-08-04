"""LLM 응답의 semantic 검증 (라운드 C 신규).

UDS LLM 파이프라인의 evidence가 실제 source와 일치하는지 구조적으로 검증.
evidence dict의 ``source_file`` 실제 존재 / 함수명이 c_parser function set에 존재 /
line range 유효성 / excerpt non-empty 검사.

(옛 docstring 은 *"기존 ``workflow/ai_validator.py::_check_hallucination`` (URL/version
regex만)의 약점을 보완"* 이라 적었다. 그 모듈은 프로덕션 호출자가 0이라 보완할 기존
동작 자체가 없었고, 2026-08-04 에 삭제했다 — §6 후보 10.)

audit reviewer가 LLM 응답을 manual review할 때 false confidence를 줄이는 게
목적. SemanticReport.score를 confidence 계산에 weighted contribution.

ISO 26262 영향: tool_qualification "auto-generated draft + manual review 의무"
정책 신뢰성 향상. semantic_validated=True는 evidence가 구조적으로 검증됨을
의미하지만 manual review 의무는 유지.

재사용:
    - ``workflow/code_parser/c_parser.parse_c_project`` 의 functions 결과 →
      caller가 function_set frozenset으로 변환 후 전달.
    - ``backend/services/file_resolver.get_resolver().exists/read_text`` —
      source_file 존재 검증 (Cloudium/Local dual mode).
    - ``workflow/uds_ai._normalize_evidence_item`` evidence schema 유지 (변경 X).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set


# evidence excerpt에서 함수명 추출 — 라인 (uds_ai.py:91-92 source_file와 동일 정규식 패턴 활용)
_FUNCTION_NAME_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
# evidence excerpt에서 line range hint 추출 — "L123" / "line 45-67" / "lines 100~120"
_LINE_HINT_RE = re.compile(
    r"(?:L|line[s]?\s*)(\d+)(?:\s*[-~]\s*(\d+))?",
    re.IGNORECASE,
)


class _ResolverProtocol(Protocol):
    """file_resolver duck typing — exists 또는 read_text 검사 가능한 객체."""
    def exists(self, path: str) -> bool: ...


@dataclass
class SemanticFinding:
    """단일 evidence item의 semantic 검증 결과."""
    index: int                     # evidence list 내 위치
    severity: str                  # "info" / "warning" / "error"
    category: str                  # "source_file" / "function" / "line_range" / "excerpt"
    message: str                   # 사람-친화 메시지 (한글)
    source_file: str = ""          # 검사 대상 path
    excerpt_preview: str = ""      # excerpt 처음 80자

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "source_file": self.source_file,
            "excerpt_preview": self.excerpt_preview,
        }


@dataclass
class SemanticReport:
    """evidence list 전체의 semantic 검증 결과.

    passed: 모든 항목에서 error 0건 (warning은 허용 — false positive 위험).
    score: 0.0~1.0. (valid_items + 0.5 * warning_only_items) / total_items.
    findings: 모든 finding (severity 무관).
    summary: 카테고리별 카운트 — caller가 [semantic] warning prefix로 사용.
    """
    passed: bool = True
    score: float = 1.0
    findings: List[SemanticFinding] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    checked_count: int = 0  # 실제 검사한 evidence 수
    skipped_count: int = 0  # 검사 skip (function_set None 등 환경 부재)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "checked_count": self.checked_count,
            "skipped_count": self.skipped_count,
            "summary": dict(self.summary),
            "findings": [f.to_dict() for f in self.findings[:50]],  # 50건 cap
        }

    @property
    def warning_messages(self) -> List[str]:
        """`[semantic]` prefix 형식 — warning_categories breakdown 호환."""
        return [
            f"[semantic] {f.category}: {f.message}"
            for f in self.findings if f.severity in ("warning", "error")
        ]


def _extract_function_names(excerpt: str) -> Set[str]:
    """excerpt에서 함수 호출 패턴 추출. ``foo()`` / ``s_Init( void )`` 등."""
    if not excerpt:
        return set()
    return {m.group(1) for m in _FUNCTION_NAME_RE.finditer(excerpt)}


def _extract_line_range(excerpt: str) -> Optional[tuple[int, int]]:
    """excerpt에서 line range 힌트 추출. ``L123`` / ``line 45-67`` 등."""
    if not excerpt:
        return None
    m = _LINE_HINT_RE.search(excerpt)
    if not m:
        return None
    try:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start <= 0 or end < start:
            return None
        return (start, end)
    except (ValueError, TypeError):
        return None


def _check_source_file(
    source_file: str,
    file_resolver: Optional[_ResolverProtocol],
) -> Optional[str]:
    """source_file 존재 확인. 정상=None, 결함=메시지 string."""
    if not source_file:
        return None  # 빈 source_file은 evidence_missing — _quality_warnings가 별도 emit
    if file_resolver is None:
        return None  # resolver 없으면 skip (회귀 fixture 또는 환경 부재)
    try:
        if not file_resolver.exists(source_file):
            return f"source_file 미존재 ({source_file})"
    except Exception as exc:
        # exists() 자체 예외 — Cloudium worker 통신 오류 등. graceful warning.
        return f"source_file 검증 실패 ({type(exc).__name__}: {source_file})"
    return None


def _check_function_match(
    excerpt: str,
    function_set: Optional[Set[str]],
) -> Optional[str]:
    """excerpt 내 함수 호출이 function_set에 존재하는지 검사.

    function_set None이면 skip (c_parser 미실행 환경).
    excerpt에 함수 패턴 0건이면 skip (자유 텍스트).
    """
    if function_set is None or not excerpt:
        return None
    extracted = _extract_function_names(excerpt)
    if not extracted:
        return None
    # 알려진 C keyword 또는 stdlib 함수는 excerpt에 흔히 등장 — 검사 제외
    _C_KEYWORDS = {
        "if", "while", "for", "switch", "return", "sizeof", "typedef",
        "static", "extern", "const", "void", "int", "char", "float",
        "double", "unsigned", "signed", "long", "short", "struct", "union",
        "enum", "goto", "break", "continue", "do", "else", "case", "default",
        # 흔한 stdlib
        "printf", "scanf", "memcpy", "memset", "strlen", "strcpy", "malloc",
        "free", "fopen", "fclose", "fread", "fwrite",
    }
    candidates = extracted - _C_KEYWORDS
    if not candidates:
        return None
    unknown = candidates - function_set
    if unknown:
        # warning만 — false positive 위험 (매크로/inline 함수 c_parser 누락 가능)
        preview = ", ".join(sorted(unknown)[:5])
        return f"function_set 매칭 실패 (excerpt 함수: {preview})"
    return None


def _check_line_range(
    excerpt: str,
    source_file: str,
    file_resolver: Optional[_ResolverProtocol],
) -> Optional[str]:
    """excerpt의 line hint가 source_file의 실제 line count 내인지 검증."""
    line_range = _extract_line_range(excerpt)
    if line_range is None:
        return None
    if file_resolver is None or not source_file:
        return None
    try:
        # read_text 사용 — Cloudium/Local dual mode 자동 dispatch
        text = file_resolver.read_text(source_file)  # type: ignore[attr-defined]
        total_lines = text.count("\n") + 1
    except Exception:
        return None  # read 실패는 _check_source_file에서 이미 emit
    start, end = line_range
    if end > total_lines:
        return (
            f"line range {start}-{end} 무효 (실제 파일 line {total_lines})"
        )
    return None


def validate_evidence(
    evidence: List[Dict[str, Any]],
    *,
    function_set: Optional[Set[str]] = None,
    file_resolver: Optional[_ResolverProtocol] = None,
) -> SemanticReport:
    """evidence list 전체의 semantic 검증.

    Args:
        evidence: ``[{source_type, source_file, excerpt, score}, ...]`` (uds_ai.py
            evidence schema 호환).
        function_set: c_parser parse_c_project 결과의 ``{f["name"] for f in functions}``
            frozenset. None이면 함수명 매칭 skip (회귀 fixture 또는 환경 부재).
        file_resolver: backend.services.file_resolver.get_resolver() 반환 객체.
            None이면 source_file 존재/line range 검증 skip.

    Returns:
        SemanticReport(passed, score, findings, summary, checked_count, skipped_count).
        passed=True 조건: error 0건 (warning은 허용).
        score: weighted (valid + 0.5 * warning_only) / total.
    """
    report = SemanticReport()
    if not evidence:
        return report  # 빈 list — passed=True, score=1.0 default

    summary: Dict[str, int] = {
        "source_file_missing": 0,
        "function_unmatched": 0,
        "line_range_invalid": 0,
        "excerpt_empty": 0,
    }

    valid_count = 0      # 모든 검사 통과
    warning_count = 0    # warning만 (error 없음)
    error_count = 0      # error 1건 이상

    for idx, item in enumerate(evidence):
        if not isinstance(item, dict):
            report.skipped_count += 1
            continue
        report.checked_count += 1
        source_file = str(item.get("source_file") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        excerpt_preview = excerpt[:80] if excerpt else ""

        item_warnings = 0  # 이 evidence item의 warning 수
        item_errors = 0    # 이 evidence item의 error 수

        # 1. excerpt non-empty
        if not excerpt:
            report.findings.append(SemanticFinding(
                index=idx, severity="warning", category="excerpt",
                message="excerpt 비어있음",
                source_file=source_file, excerpt_preview="",
            ))
            summary["excerpt_empty"] += 1
            item_warnings += 1

        # 2. source_file 존재 (warning — c_parser 미실행 또는 worker 부재 시 false positive)
        sf_msg = _check_source_file(source_file, file_resolver)
        if sf_msg:
            report.findings.append(SemanticFinding(
                index=idx, severity="warning", category="source_file",
                message=sf_msg,
                source_file=source_file, excerpt_preview=excerpt_preview,
            ))
            summary["source_file_missing"] += 1
            item_warnings += 1

        # 3. function 매칭 (warning — 매크로/inline 누락 가능)
        fn_msg = _check_function_match(excerpt, function_set)
        if fn_msg:
            report.findings.append(SemanticFinding(
                index=idx, severity="warning", category="function",
                message=fn_msg,
                source_file=source_file, excerpt_preview=excerpt_preview,
            ))
            summary["function_unmatched"] += 1
            item_warnings += 1

        # 4. line range 유효성 (warning)
        lr_msg = _check_line_range(excerpt, source_file, file_resolver)
        if lr_msg:
            report.findings.append(SemanticFinding(
                index=idx, severity="warning", category="line_range",
                message=lr_msg,
                source_file=source_file, excerpt_preview=excerpt_preview,
            ))
            summary["line_range_invalid"] += 1
            item_warnings += 1

        if item_errors > 0:
            error_count += 1
        elif item_warnings > 0:
            warning_count += 1
        else:
            valid_count += 1

    total = report.checked_count
    if total == 0:
        report.score = 1.0
    else:
        report.score = (valid_count + 0.5 * warning_count) / total
    report.passed = error_count == 0
    report.summary = summary
    return report


__all__ = [
    "SemanticFinding",
    "SemanticReport",
    "validate_evidence",
]
