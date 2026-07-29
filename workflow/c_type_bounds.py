"""C 타입 → 경계값 **표시 테이블**의 단일 출처.

이 저장소에는 경계값 테이블이 네 벌 있었고 성격이 둘로 갈린다:

1. **실 문서 산출값** — `generators/suts.py:_TYPE_BOUNDARIES`(5점 dict),
   `generators/sits.py:_BOUNDARY_SETS`(7점 list). 이 값은 실제 xlsm 셀에 쓰이므로
   바꾸면 산출물이 바뀐다. **불가침** — 여기로 합치지 않는다.
2. **표시/프롬프트용 표기** — 영향도 카드의 경계값 pill(프론트)과 AI grounding(백엔드).
   목적이 동일하고 값도 동일해야 하는데 두 벌로 복제돼 있었다. **이 모듈이 그 단일 출처**다.

프론트 `frontend-v2/src/impactBoundary.js`의 `cTypeBoundaries`는 JS 런타임 사정상
별도 구현으로 남지만, `tests/fixtures/c_type_bounds.json`을 **양쪽이 함께 assert**하므로
드리프트하면 `tests/unit/test_c_type_bounds_mirror.py`와 `impactBoundary.test.js`가 동시에
깨진다(1번 계열과의 수치 정합도 같은 테스트가 검사한다).

⚠ 미상 타입(enum/struct/typedef)은 **빈 리스트**를 돌려준다 — 숫자를 지어내지 않는다.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# unsigned는 0x hex(주소/데이터/레지스터 관례 — 실제 시험 내용과 진법이 같아야 대조가 된다),
# signed는 음수 경계가 있어 2의보수 hex가 오히려 헷갈리므로 10진 유지.
C_TYPE_ALIAS: Dict[str, str] = {
    "u8": "u8", "uint8": "u8", "uint8_t": "u8", "unsigned char": "u8", "uchar": "u8", "byte": "u8",
    "u16": "u16", "uint16": "u16", "uint16_t": "u16", "unsigned short": "u16", "unsigned short int": "u16", "ushort": "u16", "word": "u16",
    "u32": "u32", "uint32": "u32", "uint32_t": "u32", "unsigned int": "u32", "unsigned": "u32", "unsigned long": "u32", "uint": "u32", "ulong": "u32", "dword": "u32",
    "s8": "s8", "int8": "s8", "int8_t": "s8", "sint8": "s8", "signed char": "s8", "char": "s8",
    "s16": "s16", "int16": "s16", "int16_t": "s16", "sint16": "s16", "short": "s16", "signed short": "s16", "short int": "s16",
    "s32": "s32", "int32": "s32", "int32_t": "s32", "sint32": "s32", "int": "s32", "signed int": "s32", "long": "s32", "signed long": "s32", "signed": "s32",
    "boolean": "bool", "bool": "bool", "_bool": "bool", "bool_t": "bool",
}
C_TYPE_BOUNDS: Dict[str, List[Tuple[str, str]]] = {
    "u8": [("MIN", "0x0"), ("MID", "0x80"), ("MAX", "0xFF"), ("INV", "0x100(범위초과)")],
    "u16": [("MIN", "0x0"), ("MID", "0x8000"), ("MAX", "0xFFFF")],
    "u32": [("MIN", "0x0"), ("MID", "0x80000000"), ("MAX", "0xFFFFFFFF")],
    "s8": [("MIN", "-128"), ("MID", "0"), ("MAX", "127")],
    "s16": [("MIN", "-32768"), ("MID", "0"), ("MAX", "32767")],
    "s32": [("MIN", "-2147483648"), ("MID", "0"), ("MAX", "2147483647")],
    "bool": [("FALSE", "0"), ("TRUE", "1")],
}
FLOAT_TYPES = {
    "float", "f32", "float32", "single", "double", "f64", "float64",
    "real", "real32", "real64", "float32_t", "float64_t",
}

# 경계값은 없지만 **프로젝트가 타입으로 인정하는** 토큰. `generators/sits.py`의 타입 정규식이
# U64/S64를 인정하고 폭만 32비트로 접어 쓴다(경계값 정의가 없어서). 이 집합은 "이게 타입이냐"
# 어휘 판정 전용이며 `C_TYPE_ALIAS`에 넣으면 안 된다 — 거기 넣으면 `c_type_boundaries()`가
# `C_TYPE_BOUNDS[key]`에서 KeyError로 죽는다(경계값 항목이 없으므로).
_WIDE_TYPE_TOKENS = {
    "u64", "s64", "uint64", "uint64_t", "int64", "int64_t", "sint64",
    "unsigned long long", "signed long long", "long long",
}

# 타입 어휘 전체 — "이 토큰이 C 타입인가"만 묻는 곳에서 쓴다(예: AI 산문 환각 게이트가
# `U16`의 16을 '값'으로 오인하지 않도록 면제). ⚠ 여기서 폭을 `\d{1,2}` 같은 패턴으로 열면
# `U48`·`u7` 처럼 **없는 타입이 면제되어** 환각이 그대로 통과한다(실측).
KNOWN_TYPE_TOKENS: set = set(C_TYPE_ALIAS) | FLOAT_TYPES | _WIDE_TYPE_TOKENS

# 정규화 키 → generators 계열 타입명. 1번 계열(_TYPE_BOUNDARIES)과의 수치 대조에 쓴다.
GENERATOR_TYPE_NAME: Dict[str, str] = {
    "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t",
    "s8": "int8_t", "s16": "int16_t", "s32": "int32_t", "bool": "bool",
}

_QUALIFIER_RE = re.compile(r"\b(?:const|volatile|register)\b")
_WS_RE = re.compile(r"\s+")


def normalize_c_type(type_str: str) -> str:
    """C 타입 문자열 → 정규화 키('u16' 등). 미상/포인터/배열/float는 ''."""
    if not type_str:
        return ""
    raw = str(type_str)
    if "*" in raw or "[" in raw:
        return ""
    t = _WS_RE.sub(" ", _QUALIFIER_RE.sub(" ", raw)).strip().lower()
    if t in FLOAT_TYPES:
        return ""
    return C_TYPE_ALIAS.get(t, "")


def c_type_boundaries(type_str: str) -> List[Tuple[str, str]]:
    """C 타입 문자열 → [(label, value)]. 미상 타입(enum/struct/typedef)은 [](환각 금지)."""
    if not type_str:
        return []
    raw = str(type_str)
    if "*" in raw or "[" in raw:
        return [("NULL", "NULL"), ("유효", "유효 포인터/버퍼")]
    t = _WS_RE.sub(" ", _QUALIFIER_RE.sub(" ", raw)).strip().lower()
    if t in FLOAT_TYPES:
        return [("0", "0.0"), ("음수", "음의 경계값"), ("양수", "양의 경계값"), ("특수", "NaN/±Inf(해당 시)")]
    key = C_TYPE_ALIAS.get(t)
    return list(C_TYPE_BOUNDS[key]) if key else []


def fixture_payload() -> Dict[str, object]:
    """`tests/fixtures/c_type_bounds.json`과 동일 구조 — Python·vitest 공용 대조 기준."""
    return {
        "alias": dict(C_TYPE_ALIAS),
        "bounds": {k: [[lab, val] for lab, val in v] for k, v in C_TYPE_BOUNDS.items()},
        "float_types": sorted(FLOAT_TYPES),
        "pointer": [["NULL", "NULL"], ["유효", "유효 포인터/버퍼"]],
        "float_cases": [["0", "0.0"], ["음수", "음의 경계값"], ["양수", "양의 경계값"], ["특수", "NaN/±Inf(해당 시)"]],
    }
