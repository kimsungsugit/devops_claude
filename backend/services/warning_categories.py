"""Warning prefix 카테고리 단일 출처 (60차 F6 Round 5 NF3).

SwUT/SwIT routers의 `_build_result_to_response`가 warnings 1024B 초과 시
sentinel breakdown 라벨을 만든다. 카테고리는 SwUT/SwIT 동일해야 하므로 단일
출처로 추출 — 신규 prefix (예: [c_source], [asil]) 도입 시 2곳 동시 수정 위험
제거.
"""
from __future__ import annotations

import json

# 알려진 warning prefix — known_prefixes에 매칭 안 되면 'other' 카테고리로 분류.
# F6 Round 4 NW7/NW8 fix에서 정의. NF3에서 단일 출처로 추출.
# 라운드 C 추가: [semantic] (llm_semantic_validator) + [judge] (LLM-as-a-Judge).
# 2026-08-25 추가: [evidence] — 등록됐는데 파일이 없는 **선택 증빙**(SwITCR 의
#   fault_injection_result / switcr_reference 등). 이 prefix 가 없으면 `other` 로
#   묻혀, 헤더 한도 초과 시 사용자는 "증빙이 빠졌다"는 사실 자체를 못 본다.
# F6 Round 5 NF3 단일 출처 패턴 — SwUT/SwIT routers의 sentinel breakdown에 자동 통합.
KNOWN_WARNING_PREFIXES: tuple[str, ...] = (
    "[hmr]", "[swuts]", "[layout]", "[semantic]", "[judge]", "[extraction]",
    "[evidence]",
)


def categorize_warnings(warnings: list[str]) -> dict[str, int]:
    """warning list → 카테고리별 카운트 dict.

    카테고리:
        - `ambiguous`: `[hmr] ambiguous` 시작 (F6 Round 4 NW7 정밀 매칭).
            stamp summary 메시지의 'ambiguous skipped: N' substring 오분류 방지.
        - `hmr` / `swuts` / `layout`: 각 prefix로 시작
        - `semantic` / `judge`: 라운드 C 신규 — LLM hallucination 검증 결과
        - `evidence`: 선택 증빙이 등록만 되고 파일이 없어 빠진 경우
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
        "extraction": sum(1 for w in warnings if w.startswith("[extraction]")),
        "evidence": sum(1 for w in warnings if w.startswith("[evidence]")),
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


#: `X-*-Warnings` 헤더 예산(바이트). 세 라우터가 같은 값을 쓴다.
WARNINGS_HEADER_BUDGET = 1024

#: sentinel 이 들어갈 자리. 남은 개수가 sentinel 길이를 바꿔 예산 계산이 순환하므로,
#: 자리를 넉넉히 예약해 끊는다(`breakdown` 라벨이 길어질 수 있다).
_SENTINEL_RESERVE = 260


def warnings_header_json(
    warnings: list[str], *, budget: int = WARNINGS_HEADER_BUDGET,
) -> str:
    """경고 목록 → `X-*-Warnings` 헤더에 실을 JSON 문자열.

    ⚠ 예전에는 예산을 넘으면 **본문을 통째로 버리고 개수만** 남겼다. 그런데 이 저장소의
      정직성은 경고를 사람이 **읽는 것**에 걸려 있다 — 2026-08-25 실측에서 SwITCR 이
      경고 17건을 냈는데 화면엔 `(17 warnings … breakdown: other=17)` 뿐이라, 바로 그
      빌드에서 새로 낸 "선택 증빙이 빠졌다" 경고가 사용자에게 닿지 않았다.

    이제는 **들어가는 만큼 싣고, 못 실은 개수를 말한다.** sentinel 은 **맨 앞**에 둔다 —
    뒤에 두면 목록을 스크롤하지 않는 화면에서 "더 있다" 는 사실이 안 보인다.

    ⚠ breakdown 은 **전체** 기준으로 센다(남긴 것만 세면 숫자가 화면과 어긋난다).
    ⚠ `ensure_ascii=True` 라 한글 한 자가 `\\uXXXX` 6바이트다 — 예산은 그 기준이다.
    """
    full = json.dumps(warnings, ensure_ascii=True)
    if len(full) <= budget:
        return full

    label = format_breakdown_label(warnings)
    kept: list[str] = []
    used = 2                                  # "[]"
    for w in warnings:
        item = json.dumps(w, ensure_ascii=True)
        add = len(item) + (1 if kept else 0)  # 앞 항목이 있으면 콤마 1
        if used + add > budget - _SENTINEL_RESERVE:
            break
        kept.append(w)
        used += add

    dropped = len(warnings) - len(kept)
    out = json.dumps(
        [f"(+{dropped} warnings — 헤더 한도 초과로 생략, breakdown: {label})", *kept],
        ensure_ascii=True,
    )
    if len(out) <= budget:
        return out

    # 예약이 모자랄 만큼 라벨이 길다 — 본문을 포기하고 sentinel 만 남긴다.
    # ⚠ 이때 개수는 **전체**로 되돌린다. `dropped` 를 그대로 쓰면 버린 `kept` 만큼
    #   숫자가 모자라 "몇 건이 어디 갔는지" 가 안 맞는다.
    # ⚠ **JSON 문자열을 잘라내지 않는다.** 중간에서 끊으면 프론트 `JSON.parse` 가
    #   깨진다 — 30차 W21 deep-reviewer 가 고친 바로 그 결함이다. 대신 라벨을 줄인다.
    base = f"({len(warnings)} warnings — 헤더 한도 초과로 생략"
    for lab in (label, label[:120] + "...", ""):
        out = json.dumps(
            [f"{base}, breakdown: {lab})" if lab else f"{base})"], ensure_ascii=True,
        )
        if len(out) <= budget:
            return out
    return out          # 라벨 없이도 넘는 건 예산이 비정상 — 유효 JSON 을 우선한다


__all__ = [
    "KNOWN_WARNING_PREFIXES",
    "WARNINGS_HEADER_BUDGET",
    "categorize_warnings",
    "format_breakdown_label",
    "warnings_header_json",
]
