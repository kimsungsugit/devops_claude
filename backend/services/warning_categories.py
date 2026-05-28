"""Warning prefix 카테고리 단일 출처 (60차 F6 Round 5 NF3).

SwUT/SwIT routers의 `_build_result_to_response`가 warnings 1024B 초과 시
sentinel breakdown 라벨을 만든다. 카테고리는 SwUT/SwIT 동일해야 하므로 단일
출처로 추출 — 신규 prefix (예: [c_source], [asil]) 도입 시 2곳 동시 수정 위험
제거.
"""
from __future__ import annotations


# 알려진 warning prefix — known_prefixes에 매칭 안 되면 'other' 카테고리로 분류.
# F6 Round 4 NW7/NW8 fix에서 정의. NF3에서 단일 출처로 추출.
# 라운드 C 추가: [semantic] (llm_semantic_validator) + [judge] (LLM-as-a-Judge).
# F6 Round 5 NF3 단일 출처 패턴 — SwUT/SwIT routers의 sentinel breakdown에 자동 통합.
KNOWN_WARNING_PREFIXES: tuple[str, ...] = (
    "[hmr]", "[swuts]", "[layout]", "[semantic]", "[judge]",
)


def categorize_warnings(warnings: list[str]) -> dict[str, int]:
    """warning list → 카테고리별 카운트 dict.

    카테고리:
        - `ambiguous`: `[hmr] ambiguous` 시작 (F6 Round 4 NW7 정밀 매칭).
            stamp summary 메시지의 'ambiguous skipped: N' substring 오분류 방지.
        - `hmr` / `swuts` / `layout`: 각 prefix로 시작
        - `semantic` / `judge`: 라운드 C 신규 — LLM hallucination 검증 결과
        - `other`: 위 prefix 어디에도 매칭 안 됨 (NF8 비-category 노출)

    Returns:
        {category: count} dict. 0인 카테고리도 포함 (caller에서 filter).
    """
    return {
        "ambiguous": sum(1 for w in warnings if w.startswith("[hmr] ambiguous")),
        "hmr": sum(1 for w in warnings if w.startswith("[hmr]")),
        "swuts": sum(1 for w in warnings if w.startswith("[swuts]")),
        "layout": sum(1 for w in warnings if w.startswith("[layout]")),
        "semantic": sum(1 for w in warnings if w.startswith("[semantic]")),
        "judge": sum(1 for w in warnings if w.startswith("[judge]")),
        "other": sum(
            1 for w in warnings
            if not any(w.startswith(p) for p in KNOWN_WARNING_PREFIXES)
        ),
    }


def format_breakdown_label(warnings: list[str]) -> str:
    """warning list → breakdown 라벨 string (sentinel 메시지에 포함).

    F6 Round 7 NW11 fix: 라벨에 hierarchical 관계 명시. `ambiguous`는 `hmr`의
    subset (`[hmr] ambiguous` startswith로 정의) — audit reviewer가 단순 합산
    (1+2=3)으로 오해하지 않도록 라벨 앞에 `[ambiguous⊂hmr]` 힌트 prefix 부착.
    카운트 0이면 hint 생략.

    Returns:
        예) "[ambiguous⊂hmr] ambiguous=5, hmr=6, swuts=3, other=2"
        — 0 카운트는 자동 제거. 모두 0이면 "uncategorized".
    """
    breakdown = categorize_warnings(warnings)
    parts = [f"{k}={v}" for k, v in breakdown.items() if v]
    if not parts:
        return "uncategorized"
    label = ", ".join(parts)
    # ambiguous가 hmr의 subset임을 명시 (둘 다 카운트 > 0일 때만 hint)
    if breakdown["ambiguous"] > 0 and breakdown["hmr"] > 0:
        return f"[ambiguous⊂hmr] {label}"
    return label


__all__ = [
    "KNOWN_WARNING_PREFIXES",
    "categorize_warnings",
    "format_breakdown_label",
]
