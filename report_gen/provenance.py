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
# `comment`(1.00)·`sds`/`srs`/`uds`/`swcom`(0.95)·`rag`(0.85)·`call_graph`(0.80) 은
# 실제 근거를 본 것이므로 약하지 않다.
WEAK_SOURCES = frozenset({"", "unknown", "default", "inference", "module_inherit", "rule"})


def is_weak_source(src: Any) -> bool:
    """이 출처를 더 나은 근거로 덮어써도 되는가.

    ⚠ 하드코딩된 집합 리터럴로 이 판정을 재현하지 말 것 — 새 라벨이 생길 때 한쪽만
    갱신되어 조용히 갈라진다(이 모듈이 생긴 이유).
    """
    return str(src or "").strip().lower() in WEAK_SOURCES


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
