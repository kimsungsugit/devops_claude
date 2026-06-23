"""VectorCAST 노트 코드 → (Test Method, Generation Method) 정규화 (DC-4).

C# TResultParser ``Lib/VectorCAST/TestMethodMap.cs`` 포팅. SwUTS/SwITS 스펙 시트가
정규값(``REQ``/``ABV`` 등)을 직접 담는 경우엔 이 매핑이 불필요하나, 스펙 작성 편차로
미정규 노트(``REQ/BA`` 원문)가 들어오면 C# 감사본과 동일하게 정규화한다.

매핑표(사용자 확정, C# 원본과 동일):
    REQ/BA -> Test Method=REQ, Gen Method=AOR/ABV
    REQ/FI -> Test Method=FI,  Gen Method=AOR/ABV
    REQ/EC -> Test Method=REQ, Gen Method=AOR/AEC
    REQ/RA -> REQ/BA 와 동일 (오타 별칭)
    REQ/F  -> REQ/FI 와 동일 (오타 별칭)

미매핑 코드는 ``mapped=False`` + 원본 노트(Trim)를 method로 그대로 반환(가시화).
"""

from __future__ import annotations

from typing import Tuple

# 대소문자 무시 — 키는 모두 대문자로 저장하고 조회 시 upper()로 정규화.
_MAP: dict[str, Tuple[str, str]] = {
    "REQ/BA": ("REQ", "AOR/ABV"),
    "REQ/FI": ("FI", "AOR/ABV"),
    "REQ/EC": ("REQ", "AOR/AEC"),
    "REQ/RA": ("REQ", "AOR/ABV"),  # 오타: REQ/BA 와 동일
    "REQ/F": ("FI", "AOR/ABV"),    # 오타: REQ/FI 와 동일
}


def map_test_method_note(note: str | None) -> Tuple[str, str, bool]:
    """노트 문자열 → (method, gen_method, mapped).

    매핑되면 (정규 method, 정규 gen_method, True). 미매핑이면 (원본노트 Trim, "", False).
    """
    key = (note or "").strip()
    hit = _MAP.get(key.upper())
    if hit is not None:
        return hit[0], hit[1], True
    return key, "", False
