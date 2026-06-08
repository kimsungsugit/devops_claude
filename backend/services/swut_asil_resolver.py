"""C 소스 → function_id → ASIL 등급 매핑 resolver (30차 W21).

ISO 26262 ASIL A audit evidence 자동 생성 시 함수별 안전 등급 차이를
audit reviewer에게 노출하기 위해, C 소스 Doxygen 주석의 ``@asil`` 태그를
파싱해서 ``{function_id: asil_letter}`` 매핑을 생성한다.

기존 자산 재활용:
    - ``workflow.code_parser.c_parser.parse_c_project`` — tree-sitter / regex
      fallback으로 함수 정의 + ``comment_asil`` 필드 추출 (기존 ASIL 추출
      로직 그대로 재사용 — 신규 파서 작성 금지)
    - Hyundai 컨벤션: 함수명 자체에 ``SwUFn_NNNN`` 패턴 포함되거나 함수명
      바로 옆 Doxygen 주석에 ``Related ID: SwUFn_NNNN`` 명시 가정.

Fail-safe (deep-reviewer X8 추상화 적정성):
    - c_source_root 미존재 / 빈 디렉토리 → 빈 dict + warning
    - tree-sitter 미설치 → regex fallback (c_parser 내부 자동)
    - 함수명에 SwUFn 패턴 없음 → unknown 분류 (warning 1건)
    - ``@asil`` 태그 부재 → 해당 function_id를 skip + warning

ASIL audit 영향:
    매핑 못한 함수는 reviewer 검토 시 "단일 ASIL 등급으로 fallback" 명시
    필수. 본 resolver는 draft 생성기 — manual review 의무 동일.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# c_parser 기존 자산 — circular import 방지 위해 함수 내부 lazy import 사용 가능하나
# 본 모듈은 backend.services 하위라 workflow 의존성은 정적 OK.
from workflow.code_parser.c_parser import parse_c_project


# Hyundai 컨벤션 — 함수명 또는 Related ID 주석에서 SwUFn_NNNN 추출.
_FUNCTION_ID_RE = re.compile(r"(SwUFn_\d+)")

# ASIL 등급 정규화 — "@asil ASIL-B", "ASIL: C", "ASIL D", "ASIL_D" 등 단일 문자로.
# c_parser는 word boundary 패턴 사용해 "ASIL_D" 통째로는 추출 못 하지만, 본
# 정규화는 raw input이 어떤 형식이든 defensively 처리 (호출자 무관).
_ASIL_NORMALIZE_RE = re.compile(r"ASIL[\s\-:_]*([A-D]|QM)", re.IGNORECASE)

SYSTEM_SOURCE_ROOT_BLACKLIST: tuple[str, ...] = (
    # Windows
    "c:/windows", "c:/program files", "c:/programdata",
    # Linux
    "/etc", "/root", "/sys", "/proc", "/dev", "/boot",
    "/var/log", "/usr/bin", "/usr/sbin", "/usr/lib",
    # macOS
    "/applications", "/library", "/system", "/private",
    "/usr/local/bin", "/usr/local/sbin",
)


def is_blocked_source_root(c_source_root: str | Path) -> bool:
    """Return True when a C source root points at a system directory."""
    if not c_source_root:
        return False
    abs_root_norm = str(Path(c_source_root).resolve()).replace("\\", "/").lower()
    return any(
        abs_root_norm == bad or abs_root_norm.startswith(bad + "/")
        for bad in SYSTEM_SOURCE_ROOT_BLACKLIST
    )


@dataclass
class AsilResolveResult:
    """C 소스 ASIL 추출 결과.

    Attributes:
        function_asil_map: SwUFn_NNNN → "A"/"B"/"C"/"D"/"QM" 단일 문자.
        unknown_function_ids: 입력 function_ids 중 매핑 못한 항목.
        c_function_count: parse_c_project가 발견한 C 함수 총 개수 (진단용).
        warnings: 사용자에게 노출할 안내 — 사용자 입력 path 오류, 매핑 0건 등.
    """

    function_asil_map: dict[str, str] = field(default_factory=dict)
    unknown_function_ids: list[str] = field(default_factory=list)
    c_function_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _normalize_asil(raw: str) -> str:
    """Doxygen 주석의 ASIL 표기를 단일 문자로 정규화.

    1순위: ``ASIL`` 키워드 + separator + letter 패턴.
        예: ``"ASIL-B"`` / ``"ASIL: C"`` / ``"asil_d"`` → ``"B"`` / ``"C"`` / ``"D"``.
    2순위 (fallback): c_parser가 이미 letter만 추출한 경우 ("B", "D", "QM").
        c_parser regex ``\\bASIL\\b[:\\s-]+([A-Za-z0-9-]+)`` 는 ``@asil B`` 같은
        Doxygen 표준 형식에서 group(1) = "B"만 반환하므로 이 경로가 활성화.

    매칭 실패 시 빈 문자열 — 호출자가 unknown으로 분류.
    """
    if not raw:
        return ""
    m = _ASIL_NORMALIZE_RE.search(raw)
    if m:
        return m.group(1).upper()
    cleaned = raw.strip().upper()
    if cleaned in ("A", "B", "C", "D", "QM"):
        return cleaned
    return ""


def _extract_function_id(c_function_name: str, related_id: str = "") -> str:
    """C 함수명 또는 Related ID 주석에서 SwUFn_NNNN 추출.

    1순위: 함수명 자체에 SwUFn_NNNN 포함 (Hyundai 컨벤션)
    2순위: ``Related ID: SwUFn_NNNN`` 주석 (c_parser comment_related 필드)
    매칭 실패 시 빈 문자열.
    """
    for candidate in (c_function_name, related_id):
        if not candidate:
            continue
        m = _FUNCTION_ID_RE.search(candidate)
        if m:
            return m.group(1)
    return ""


def resolve_function_asil_map(
    c_source_root: str | Path,
    function_ids: Iterable[str] | None = None,
    *,
    allowed_roots: list[str] | None = None,
    max_files: int = 300,
) -> AsilResolveResult:
    """C 소스 디렉토리에서 함수별 ASIL 등급을 추출.

    Args:
        c_source_root: C 소스 디렉토리 (옵션 — 빈 string / None이면 빈 dict).
        function_ids: 매핑 대상 SwUFn_NNNN 집합 (None이면 모두 매핑 시도).
            제공 시 매핑 못한 항목은 ``unknown_function_ids`` 에 누적.
        allowed_roots: path traversal 방어 — None이면 검증 skip (router 진입
            전에 검증 의무). 제공 시 abs path가 어느 root 하위인지 확인.
        max_files: c_parser 안전 한도 — DoS 방어.

    Returns:
        :class:`AsilResolveResult`.
    """
    result = AsilResolveResult()

    # 1) 입력 검증 — 빈 path는 정상 케이스 (옵션 필드 미제공).
    if not c_source_root:
        return result

    root_path = Path(c_source_root)
    if not root_path.exists():
        result.warnings.append(
            f"c_source_root '{c_source_root}' 미존재 — ASIL 추출 skip"
        )
        return result

    if not root_path.is_dir():
        result.warnings.append(
            f"c_source_root '{c_source_root}' 디렉토리 아님 — ASIL 추출 skip"
        )
        return result

    # 2) Path traversal 방어 — deep-reviewer X5/S3.
    abs_root_norm = str(root_path.resolve()).replace("\\", "/").lower()

    # 2a) 시스템 디렉토리 blacklist — allowed_roots 부재 시 backstop.
    # Windows + POSIX(Linux) + macOS 모두 커버. ISO 26262 audit 도구가 임의
    # 디렉토리 scan 못하도록 명시적 거부. 31차 prep D7: macOS 추가.
    _BLACKLIST = (
        # Windows
        "c:/windows", "c:/program files", "c:/programdata",
        # Linux
        "/etc", "/root", "/sys", "/proc", "/dev", "/boot",
        "/var/log", "/usr/bin", "/usr/sbin", "/usr/lib",
        # macOS (31차 prep D7 추가)
        "/applications", "/library", "/system", "/private",
        "/usr/local/bin", "/usr/local/sbin",
    )
    for bad in _BLACKLIST:
        if abs_root_norm == bad or abs_root_norm.startswith(bad + "/"):
            result.warnings.append(
                f"c_source_root '{c_source_root}' 시스템 디렉토리 — 거부 "
                "(ASIL audit 도구는 사용자 프로젝트 source만 scan 허용)"
            )
            return result

    # 2b) allowed_roots 검증 — 명시 제공 시 root 하위만 허용.
    if allowed_roots is not None:
        ok = False
        for root in allowed_roots:
            abs_a = str(Path(root).resolve()).replace("\\", "/").lower()
            if abs_root_norm.startswith(abs_a.rstrip("/") + "/") or abs_root_norm == abs_a:
                ok = True
                break
        if not ok:
            result.warnings.append(
                f"c_source_root '{c_source_root}' allowed_roots 외부 — 거부"
            )
            return result

    # 3) c_parser 호출 — fail-safe.
    try:
        parsed = parse_c_project(str(root_path), max_files=max_files)
    except Exception as e:  # pragma: no cover - parse 자체 실패 robust
        result.warnings.append(
            f"parse_c_project 예외 '{type(e).__name__}: {e}' — ASIL 추출 skip"
        )
        return result

    functions = parsed.get("functions") or []
    result.c_function_count = len(functions)

    # 4) C 함수 → function_id 매핑 + ASIL 정규화.
    requested = set(function_ids) if function_ids is not None else None
    seen_ids: set[str] = set()
    for fn in functions:
        name = fn.get("name") or ""
        related = fn.get("comment_related") or ""
        fn_id = _extract_function_id(name, related)
        if not fn_id:
            continue
        asil_raw = fn.get("comment_asil") or ""
        asil = _normalize_asil(asil_raw)
        if not asil:
            continue
        # 가장 최근 정의가 우선 (중복 시 마지막 값으로 덮어쓰기).
        result.function_asil_map[fn_id] = asil
        seen_ids.add(fn_id)

    # 5) 매핑 못한 function_ids 누적.
    if requested is not None:
        result.unknown_function_ids = sorted(requested - seen_ids)

    # 6) 진단 warning — 사용자가 c_source_root는 줬는데 매핑 0건이면 명시.
    if result.c_function_count == 0:
        result.warnings.append(
            f"c_source_root '{c_source_root}' 에서 C 함수 0개 발견 — "
            "디렉토리 / max_files / tree-sitter 설치 확인"
        )
    elif not result.function_asil_map:
        result.warnings.append(
            f"C 함수 {result.c_function_count}개 발견했으나 SwUFn_NNNN + "
            "@asil 매칭 0건 — 함수명/주석 컨벤션 확인 (Hyundai 'SwUFn_' 포함 또는 "
            "'Related ID: SwUFn_NNNN' 주석 + '@asil ASIL-X')"
        )

    return result


__all__ = [
    "AsilResolveResult",
    "resolve_function_asil_map",
]
