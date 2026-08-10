"""문서 생성 **필드 출처 사슬**의 단일 출처 — "이 입력이 없으면 어느 칸이 비는가".

## 왜 이 모듈이 생겼나

생성 화면이 답하지 못하는 질문이 있었다 — **"SwDS 를 안 주면 무엇이 안 채워지나"**.
답은 코드에 이미 있다(`report_gen/docx_builder.py` 등이 `*_source` 를 대입한다). 다만
그 사슬이 **4개 파일에 흩어져 단계별로 실행**되고, 덮어쓸지는 순서가 아니라
`provenance.is_weak_source()`(점수 0.75 이하) 판정이 정한다. 그래서 사람이 읽을 수 있는
형태가 아무 데도 없었다.

## ⚠ "순위 사슬" 이 아니다

`comment → sds → 끝` 같은 1·2순위 표로 그리면 **틀린다**(설계 라운드에서 두 번 그렇게
그렸다가 두 번 다 정정했다). 실제 구조는 **출처 후보 집합 + 강도 우선 덮어쓰기**다:

- 대입 지점이 `requirements.py`(enrich) → `function_analyzer.py`(finalize) →
  `docx_builder.py`(build) → `validation.py`(회수) → `local.py`(HSIS 승격) 순으로 흩어져 있고,
- 뒤 단계가 앞 값을 덮을 수도, 못 덮을 수도 있다(약한 출처만 덮인다).

그래서 이 모듈은 **"입력이 있으면 어떤 출처가 붙을 수 있는가"** 만 말한다.
**최종 칸 수는 단정하지 않는다** — 모듈 상속(`module_inherit`)이 같은 모듈의 한 함수
등급을 모듈 전체로 번지게 하므로 입력 유무만으로 계산할 수 없다.

## ⚠ 점수·약함 판정을 복제하지 말 것

라벨→점수는 `report_gen/validation.py::src_score`, 약함 판정은
`report_gen/provenance.py::is_weak_source` 가 정본이다. 여기서 집합 리터럴로 다시 적으면
새 라벨이 생길 때 한쪽만 갱신되어 조용히 갈라진다(그 사고가 이미 두 번 났다 —
`generated_doc` 축과 `srs_default_qm` 별칭 축).

## ⚠ `backend/helpers/common.py::_normalize_field_source` 를 쓰지 말 것

그 함수는 6개 라벨만 알고 나머지(`unknown`·`default`·`rag`·`call_graph`·`uds`·`swcom`·
`generated_doc`)를 전부 `inference` 로 접는다 — `provenance.py` 가 고친 결함의 잔재다.
출처를 사람에게 보여줄 때는 `provenance.canonical_source()` + `validation.src_labels` 를 쓴다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from report_gen.provenance import canonical_source

# ── 입력 축 ────────────────────────────────────────────────────────────────
# 게이트가 "있다/없다" 를 판정하는 단위. 화면의 준비 단계 항목과 1:1 대응한다.
INPUT_SOURCE_COMMENT = "source_comment"   # C 소스의 함수 앞 주석
INPUT_SWDS = "swds"                       # SW 설계서(SDS/SwDS)
INPUT_SWRS = "swrs"                       # SW 요구사항(SRS/SwRS)
INPUT_HSIS = "hsis"                       # HW-SW 인터페이스 명세
INPUT_UDS_DOC = "uds_doc"                 # 기존 UDS 문서(재사용)
INPUT_KB = "kb"                           # RAG 지식베이스 인덱스
INPUT_REFERENCE = "reference"             # 레퍼런스 문서
INPUT_AI = "ai"                           # AI 활성 + API 키
INPUT_CALL_GRAPH = "call_graph"           # 소스 콜그래프(파싱 산출)

INPUT_LABELS: Dict[str, str] = {
    INPUT_SOURCE_COMMENT: "소스 주석",
    INPUT_SWDS: "SwDS(설계서)",
    INPUT_SWRS: "SwRS(요구사항)",
    INPUT_HSIS: "HSIS",
    INPUT_UDS_DOC: "UDS 문서",
    INPUT_KB: "지식베이스",
    INPUT_REFERENCE: "레퍼런스 문서",
    INPUT_AI: "AI 생성",
    INPUT_CALL_GRAPH: "콜그래프",
}

# ── 출처 라벨 → 그 출처가 붙으려면 필요한 입력 ──────────────────────────────
#
# `None` 은 **입력이 필요 없다**는 뜻이다(생성기 내부에서 만든다). 그 출처들은
# 게이트가 "확보" 로 세면 안 된다 — 근거가 아니라 자리 채움이기 때문이다.
#
# ⚠ 별칭은 `canonical_source()` 로 접은 뒤 조회한다. `hsis` 는 `sds` 로 접히므로
#   여기 키는 접힌 뒤 이름이어야 하는데, **HSIS 는 SwDS 와 다른 입력**이다.
#   그래서 별칭 접기 **전** 원본 라벨도 함께 받는다(`source_input()` 참조).
SOURCE_REQUIRED_INPUT: Dict[str, Optional[str]] = {
    "comment": INPUT_SOURCE_COMMENT,
    "sds": INPUT_SWDS,
    "sds_match": INPUT_SWDS,
    "srs": INPUT_SWRS,
    "uds": INPUT_UDS_DOC,
    "swcom": INPUT_SWDS,
    "rag": INPUT_KB,
    "reference": INPUT_REFERENCE,
    "ai": INPUT_AI,
    "call_graph": INPUT_CALL_GRAPH,
    # 입력 불필요 — 생성기 내부 산출. 근거가 아니다.
    "module_inherit": None,
    "rule": None,
    "inference": None,
    "default": None,
    "unknown": None,
    "generated_doc": None,
}

# 별칭 접기 **전에** 판정해야 하는 라벨. `hsis` 는 `canonical_source()` 가 `sds` 로
# 접지만 입력 축은 HSIS 문서다 — 접고 나서 조회하면 "SwDS 가 있으니 채워진다" 는
# 틀린 안내가 된다.
PRE_ALIAS_SOURCE_INPUT: Dict[str, str] = {
    "hsis": INPUT_HSIS,
}


def source_input(src: Any) -> Optional[str]:
    """출처 라벨 → 필요한 입력 키. 입력이 필요 없으면 ``None``.

    ⚠ 별칭을 접기 **전에** `PRE_ALIAS_SOURCE_INPUT` 를 먼저 본다(위 주석 참조).
    """
    raw = str(src or "").strip().lower()
    if raw in PRE_ALIAS_SOURCE_INPUT:
        return PRE_ALIAS_SOURCE_INPUT[raw]
    return SOURCE_REQUIRED_INPUT.get(canonical_source(raw))


# ── 필드별 출처 후보 ────────────────────────────────────────────────────────
#
# 코드에서 실제로 대입되는 라벨 전수(2026-08-10 전수 조사). 대입 위치를 함께 적어
# 드리프트 가드(`tests/unit/test_docgen_field_sources.py`)가 소스와 대조할 수 있게 한다.
#
# ⚠ 순서는 우선순위가 **아니다**(모듈 docstring 참조). 표시 순서일 뿐이다.
FIELD_SOURCES: Dict[str, List[str]] = {
    "asil": [
        "comment",          # docx_builder.py:2100
        "sds",              # docx_builder.py:2110
        "srs",              # docx_builder.py:2147
        # ⚠ 기존 UDS 문서에서 등급을 **직독**하는 경로. 드리프트 가드가 3차로 잡아냈다
        #   (`_build_uds_asil_map`. 저장소가 [A] 38건 under-report 를 고치며 넣은 배선이다).
        "uds",              # requirements.py:1660
        "module_inherit",   # docx_builder.py:2062
        "generated_doc",    # validation.py:1413
        "default",          # docx_builder.py:2172
    ],
    "related": [
        "comment",          # docx_builder.py:2103
        "sds",              # docx_builder.py:2116 · requirements.py:1582
        "srs",              # docx_builder.py:2142
        "hsis",             # local.py:614
        "call_graph",       # docx_builder.py:2553,2559
        "reference",        # docx_builder.py:3158,3166
        "rule",             # docx_builder.py:3161 · function_analyzer.py:1097 · helpers/uds.py:427
        "inference",        # docx_builder.py:2160 · function_analyzer.py:1090
        "generated_doc",    # validation.py:1418
        "default",          # docx_builder.py:2175
    ],
    "description": [
        "comment",          # validation.py:1403
        "sds",              # docx_builder.py:2122 · requirements.py:1590
        "sds_match",        # requirements.py:1598
        "hsis",             # local.py:603
        "rag",              # docx_builder.py:2316
        "reference",        # docx_builder.py:2392 · requirements.py:535,565
        "ai",               # docx_builder.py:2598,2605
        "inference",        # docx_builder.py:2227,2240 · function_analyzer.py:1062,1077
        "generated_doc",    # validation.py:1410
    ],
}

FIELD_LABELS: Dict[str, str] = {
    "asil": "ASIL 등급",
    "related": "Related ID",
    "description": "함수 설명",
}


def chain_state(field: str, available: Dict[str, bool]) -> List[Dict[str, Any]]:
    """필드 하나의 **출처별 가용 상태**를 낸다.

    Args:
        field: ``asil`` / ``related`` / ``description``.
        available: 입력 키 → 가용 여부. **키가 없으면 "모름"** 이고 ``False`` 와 다르다
            (확인 실패를 "없음" 으로 접지 않는다 — 이 저장소의 반복 규약).

    Returns:
        ``[{"source", "input", "input_label", "have": True|False|None,
            "grounded": bool}, …]``
        - ``have=None`` 은 **확인하지 못함**이다. ``False``(확인했고 없음)와 구분한다.
        - ``grounded=False`` 는 입력이 필요 없는 출처(생성기 내부 산출)라는 뜻이고,
          게이트는 이걸 "확보" 로 세면 안 된다.

    ⚠ 출처의 **한국어 라벨은 내지 않는다.** 정본은 `report_gen/validation.py` 의
    `src_labels` 인데 그건 `generate_asil_related_confidence_report` **함수 내부의 지역
    변수**라 밖에서 읽을 수 없고, 여기 다시 적으면 복제가 되어 갈라진다(이 저장소가 같은
    이유로 `provenance.py` 를 만들었다). 화면이 필요로 하면 `validation.py` 의 표를 모듈
    상수로 승격하는 **별건** 리팩터로 푼다 —
    `tests/unit/test_confidence_provenance_laundering.py` 가 그 표를 AST 로 읽으므로
    승격 시 그 가드를 함께 확인해야 한다. 그때까지는 출처 **코드 그대로** 노출한다
    (조용히 빈 칸이 되는 것보다 낫다 — `DocGenStatusBoard.metricLabel` 과 같은 규약).
    """
    out: List[Dict[str, Any]] = []
    for src in FIELD_SOURCES.get(field, []):
        need = source_input(src)
        have: Optional[bool]
        if need is None:
            have = None
        elif need in available:
            have = bool(available[need])
        else:
            have = None
        out.append({
            "source": src,
            "input": need,
            "input_label": INPUT_LABELS.get(need or "", ""),
            "have": have,
            "grounded": need is not None,
        })
    return out


def missing_grounded_inputs(field: str, available: Dict[str, bool]) -> List[str]:
    """이 필드에서 **근거 있는 출처가 하나도 확보되지 않았을 때** 비어 있는 입력 목록.

    하나라도 확보돼 있으면 빈 리스트를 준다 — "무엇이 부족한가" 는 *전부 비었을 때만*
    의미가 있고, 일부만 없는 상태를 결핍으로 보고하면 정상 구성을 결함처럼 그린다.

    ⚠ 확인하지 못한 입력(``have is None``)은 **없음으로 세지 않는다.** 그 상태는
    호출자가 `unknown` 으로 따로 보고해야 한다.
    """
    rows = [r for r in chain_state(field, available) if r["grounded"]]
    if any(r["have"] is True for r in rows):
        return []
    return [str(r["input"]) for r in rows if r["have"] is False]
