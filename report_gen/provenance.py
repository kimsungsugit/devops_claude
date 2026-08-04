# report_gen/provenance.py
"""필드 출처(provenance) 어휘의 **판정 단일 출처**.

## 왜 이 모듈이 생겼나 (2026-07-31)

`description_source` / `asil_source` / `related_source` 는 값이 어디서 왔는지를 적는
필드다. 보고서 표에 라벨로 찍히고(`report_gen/validation.py::src_labels`) 신뢰도
점수로 환산된다(`src_score`). 그런데 **"이 출처는 약한가?"** 라는 같은 판정이 저장소
곳곳에 서로 다른 리터럴로 복제돼 있었다:

| 위치 | 당시 판정식 |
|---|---|
| `docx_builder.py` `_weak_sources` | `{"", "inference", "default", "module_inherit"}` |
| `docx_builder.py` RAG enrich | `!= "inference"` |
| `docx_builder.py` 이름 병합 | `== "inference"` |
| `docx_builder.py` AI desc 게이트 | `in {"inference", "rule", ""}` |
| `function_analyzer.py` 신뢰도 | `in {"inference", "module_inherit", "default", "rule", ""}` |
| `requirements.py` SDS 매칭 | `in {"", "inference"}` |
| `routers/local.py` HSIS 승격 | `in {"inference", ""}` |

전부 "약한 출처면 더 나은 근거로 덮어써도 된다" 는 **같은 판정**인데 집합이 제각각이라,
새 라벨을 하나 도입하면 어떤 곳은 덮어쓰고 어떤 곳은 안 덮어쓴다. 실제로 `unknown`
(미상)을 도입하려다 이 문제를 만났다 — 7곳 중 5곳이 `unknown` 을 강한 출처로 오인해
**"출처를 모른다" 가 "출처가 확정됐다" 처럼 굳는** 상태가 됐다.

이 저장소가 반복해 겪은 실패 모드다(`_is_hsis_data_row`·`_ratchet_core`·`_artifact_check`
가 같은 이유로 단일화됐다). 그래서 판정을 여기 하나로 둔다.

⚠ 라벨 어휘와 **점수**의 정본은 `report_gen/validation.py` 의 `src_labels`/`src_score`
다. 여기는 "약한가?" 판정과 미기록 시 붙일 라벨만 담는다. 새 라벨을 추가하면 양쪽을
같이 갱신할 것.
"""
from __future__ import annotations

from typing import Any

# 값이 "아직 아무것도 없다" 는 뜻으로 쓰이는 자리표시자.
PLACEHOLDER_VALUES = frozenset({"", "tbd", "n/a", "na", "-", "none"})

# 더 나은 근거가 나타나면 **덮어써도 되는** 출처.
#   - ""              : 아무도 기록하지 않음
#   - "unknown"       : 값은 있는데 출처 미상 (0.30)
#   - "default"       : 근거 없이 자리만 채움 (0.30)
#   - "inference"     : 생성기가 추론/합성 (0.60)
#   - "module_inherit": 모듈에서 물려받음 (0.70)
#   - "rule"          : 이름 규칙 등 기계적 규칙 (0.75)
#   - "generated_doc" : 자기 산출물(생성 DOCX)에서 회수, 원 유래 불명 (0.30)
# `comment`(1.00)·`sds`/`srs`/`uds`/`swcom`(0.95)·`rag`(0.85)·`call_graph`(0.80) 은
# 실제 근거를 본 것이므로 약하지 않다.
#
# ⚠ 이 집합과 `validation.py::src_score` 는 **함께 움직여야 한다**. 실제로 한 번
#   갈라졌다: `generated_doc`(0.30)을 점수표에만 넣고 여기 빠뜨려, 최약체가 여기선
#   "강한 출처" 로 분류됐다. 경계는 `tests/unit/test_confidence_provenance_laundering.py`
#   의 `TestWeakSourceTableAgreesWithScores` 가 양방향으로 고정한다.
WEAK_SOURCES = frozenset(
    {"", "unknown", "default", "generated_doc", "inference", "module_inherit", "rule"}
)

# 약함/강함을 가르는 점수 경계. `rule`(0.75)까지가 약함, `call_graph`(0.80)부터 강함.
WEAK_SCORE_MAX = 0.75

# 같은 뜻의 다른 표기. **점수·약함 판정 모두 이 표를 거친 뒤에 한다.**
#
# ⚠ 2026-07-31 실측 — 이 표가 `validation.py` 지역 변수(`_src_aliases`)로만 있었고
#   `WEAK_SOURCES` 는 별칭을 몰랐다. 그래서 `srs_default_qm` 이
#   **점수는 0.30(최약체)인데 `is_weak_source()` 는 강함**이라고 답했다 —
#   더 나은 근거(주석 `@asil` 1.00, SDS 0.95)가 와도 그 칸을 덮지 못했다.
#   커밋 6e53bba(`generated_doc`)가 막으려던 갈라짐이 **별칭 축에서 재발**한 것이고,
#   그걸 지키는 가드는 `src_score` 리터럴만 AST 로 읽어 별칭을 구조적으로 못 봤다.
#   그래서 표를 여기로 올리고 `validation.py` 가 이걸 가져다 쓴다.
#
# `srs_default_qm` 은 생산자가 사라졌지만(근거 없는 QM 지어내기를 제거했다) **남긴다** —
# 디스크의 옛 payload 가 아직 이 라벨을 달고 있어 재처리 시 판정 대상이 된다.
SOURCE_ALIASES = {
    "hsis": "sds",
    "srs_default_qm": "default",   # SRS 에 없어서 QM 기본 — 기본값이다 (legacy payload 전용)
}

# ⚠ `sds_match` 는 **일부러 여기 없다**(2026-08-04, §6 후보 20).
#
# 예전엔 `"sds_match": "sds"` 로 접혀 0.95(정본 문서)를 받았다. 그런데 생산 지점
# (`report_gen/requirements.py:1593-1598`)은 *"설명을 SDS 에서 가져온 경우"* 의
# **else 분기**다 — 즉 이 라벨의 뜻은 정확히 *"설명이 SDS 에서 오지 **않았다**"* 이고,
# SDS 급 신용은 과대다. 같은 사실이 §6 후보 19 를 기각시킨 근거이기도 했다.
#
# 실측이 뒷받침한다: 이 라벨이 붙은 행 중 `comment_description` 보유가 **0행**이라
# 주석 유래 가능성도 없고, 표본에서 설명 문구가 `function_analyzer.py:901` 의 **함수명
# 템플릿**이었다. 그래서 `report_gen/validation.py` 에 **자기 라벨·자기 점수(0.80)** 를
# 갖는다 — `call_graph` 와 같은 "보조 증거" 티어다.
#
# ⚠ 0.75 이하로는 내리지 않는다. `WEAK_SCORE_MAX` 아래로 가면 `is_weak_source()` 가
#   True 가 되어 RAG·AI·HSIS 덮어쓰기 3경로가 새로 열리고, 그건 점수 정직화가 아니라
#   **산출물 내용 변경**이다(1,900+행 대상). 여기서 하려는 일이 아니다.


def canonical_source(src: Any) -> str:
    """별칭을 정본 라벨로 접는다. 어휘에 없으면 소문자 정규화만 해서 돌려준다."""
    s = str(src or "").strip().lower()
    return SOURCE_ALIASES.get(s, s)


def is_weak_source(src: Any) -> bool:
    """이 출처를 더 나은 근거로 덮어써도 되는가.

    ⚠ 하드코딩된 집합 리터럴로 이 판정을 재현하지 말 것 — 새 라벨이 생길 때 한쪽만
    갱신되어 조용히 갈라진다(이 모듈이 생긴 이유).
    ⚠ **별칭을 먼저 접는다.** 안 접으면 `srs_default_qm`(=`default`, 0.30) 같은
    최약체가 "어휘에 없음 → 강함" 으로 분류된다(2026-07-31 실측 회귀).
    """
    return canonical_source(src) in WEAK_SOURCES


def unrecorded_source(value: Any, *, generic: bool = False) -> str:
    """출처가 기록되지 않은 필드에 붙일 라벨 — **값이 무엇인지 보고** 정한다.

    ⚠ 실측(2026-07-31): 예전엔 미기록을 전부 `"inference"` 로 확정했다. 사람이 쓴 설명,
    실제 등급 `C`, 실제 `SwFn_07` 을 넣고 생성했더니 **셋 다 `inference`** 였다 —
    아무것도 추론하지 않았는데 보고서 표에 "추론" 으로 찍히고 점수가 0.60 이 된다.
    반대로 근거 없이 자리만 채운 값도 같은 0.60 을 받아 **두 방향으로 동시에** 틀렸다.

    생산자(`report_gen/function_analyzer.py`)는 **자기가 한 행위에 묶어서** 라벨한다
    (합성했을 때만 `inference`, QM 을 채웠을 때만 `default`). 이 함수는 그 규약을
    출처 미기록 케이스로 확장한 것이다.

    Returns:
        `"default"`   — 값 자체가 없다(자리표시자). 근거 없이 칸만 채운 상태
        `"inference"` — 생성기가 만든 일반 문구. 실제로 추론이 있었다
        `"unknown"`   — 실제 값인데 출처가 기록되지 않았다. **모른다는 것 자체가 정보다**
    """
    v = str(value or "").strip().lower()
    if v in PLACEHOLDER_VALUES:
        return "default"
    if generic:
        return "inference"
    return "unknown"


def has_evidence_value(value: Any) -> bool:
    """이 값이 **출처를 붙일 만한 실값**인가. 자리표시자면 False.

    출처 라벨은 "이 값이 어디서 왔는가" 를 뜻한다. 값이 없는데 라벨만 올리면 그 칸은
    *근거는 있는데 내용이 없다* 는 불가능한 상태가 되고, `validation.py::_score_for`
    가 값 유무를 안 보므로 **빈 칸이 0.95(강한 출처) 점수를 받는다**.

    ⚠ 실측(2026-08-04) — 값을 건드리지 않고 라벨만 올리던 사이트가 3곳 있었다:

    | 사이트 | 하던 일 |
    |---|---|
    | `backend/routers/local.py` HSIS 승격 | 약한 출처면 `description` 을 안 보고 `hsis`(→별칭 `sds`) |
    | `tools/generate_uds_local.py` 같은 승격 | 동일 |
    | `report_gen/requirements.py` SDS 매칭 | `description` 이 비어도 `sds_match` |

    세 곳 모두 디스크 실측 잔여는 0건이었지만(마지막에 `docx_builder.py` 가 자리표시자를
    `default` 로 되돌리는 안전망 하나가 막고 있었다), **유입 경로 자체는 열려 있었다** —
    안전망 한 겹에 의존하는 상태와 유입이 없는 상태는 회귀 위험이 다르다.

    ⚠ `backend/helpers/common.py::_has_meaningful_value` 와 **다른 축**이다. 그쪽은
    "이 필드가 채워졌는가"(채움률 분자)라 리스트도 받고 판정 집합도 다르며, 바꾸면
    공표된 채움률이 움직인다. 여기는 "출처 라벨을 붙여도 되는가" 판정이므로 어휘를
    `PLACEHOLDER_VALUES` 에 맞춘다. 둘을 합치지 말 것.

    ⚠ `str(value or "")` 관용구를 쓰지 않는다 — `0`·`False` 가 falsy 라 `""` 로 접혀
    **실값이 자리표시자로 분류된다**. 같은 파일 `unrecorded_source` 는 아직 그 관용구를
    쓰는데, 거기는 바꾸면 공표된 출처 라벨이 움직이므로 이 함수만 정확히 한다.
    """
    if value is None:
        return False
    return str(value).strip().lower() not in PLACEHOLDER_VALUES
