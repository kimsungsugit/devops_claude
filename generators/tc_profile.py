"""시험 케이스 **물량 프로파일** — STS·SUTS·SITS 세 생성기와 준비 게이트가 공유하는 유일한 정의.

사용자 결정(2026-09-19): "정본과 비슷하게 하는 건 그대로 두고, 품질 좋고 그에 맞게 TC 도 작성되고
개수도 늘어나는 **옵션**" — 기본은 그대로 정본 규모이고, 확장은 고를 때만 켜진다.

두 프로파일의 관계는 **포함**이다: 확장 문서는 기본 문서의 시험을 전부 담고(같은 ID·같은 순서)
그 뒤에 덧붙인다. 확장이 기본의 시험을 바꾸거나 밀어내면 두 문서를 나란히 놓고 볼 수 없다.

확장이 늘리는 것은 **근거가 있는 시험**뿐이다 — 값은 같은 경계 출처(설계서 범위 > enum > HSIS >
선언 타입)에서 오고, 모르는 타입은 확장에서도 비운다. 상한을 풀 뿐 값을 지어내지 않는다.

| 문서 | 기본(정본 규모) | 확장 |
|---|---|---|
| STS | 요구당 상한까지, 매핑된 함수를 앞에서부터 | + 시험이 하나도 없는 함수마다, 그 함수를 가장 좁게 가리키는 요구 밑에 분기·경계값 TC |
| SUTS | 전략 24종 상한, 조건 조합 4·switch 6·전역 3·MC/DC 6 | 상한 없음 + 입력마다 최솟값/최댓값 단독 변경(OAT) + 모든 case·전역·조건 |
| SITS | 흐름 120 · sub-case 7 | 찾은 흐름 전부 · sub-case 후보 전부 |
"""
from __future__ import annotations

from typing import Any, Tuple

TC_PROFILE_REFERENCE = "reference"   # 정본 규모(기본)
TC_PROFILE_EXTENDED = "extended"     # 근거 있는 시험을 상한 없이

_KNOWN = (TC_PROFILE_REFERENCE, TC_PROFILE_EXTENDED)


def normalize_tc_profile(value: Any) -> Tuple[str, str]:
    """`(프로파일, 못 알아본 원래 값)`. 빈 값·모르는 값은 **기본(정본 규모)** 으로 간다.

    모르는 값을 확장으로 읽으면 오타 하나가 문서를 열 배로 키운다 — 안전한 쪽은 기본이다.
    못 알아본 값은 버리지 않고 돌려줘서 호출자가 공시할 수 있게 한다(`_suts_normalize_scope` 와 같은 규약).
    """
    raw = str(value or "").strip()
    low = raw.lower()
    if not low:
        return TC_PROFILE_REFERENCE, ""
    if low in _KNOWN:
        return low, ""
    return TC_PROFILE_REFERENCE, raw


def is_extended(value: Any) -> bool:
    return normalize_tc_profile(value)[0] == TC_PROFILE_EXTENDED
