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

## 축이 둘이다 — 물량과 **근거**

위 표는 **물량** 축이다. 2026-09-20 실측에서 드러난 최대 결손은 물량이 아니라 근거였다:
STS 스텝 8,130행 중 기대결과가 **관측 가능한 것이 26%**(구체값 685 + 경로/분기 1,483)뿐이고,
나머지 60%는 `기대 결과와 일치`(1,128) · `입력 경계 최솟값 설정`(840) · 서술(3,048) 로
**무엇을 보고 합격인지 말하지 않는다**.

그래서 중간 단계 `recommended` 를 둔다 — **물량은 정본 규모 그대로 두고 근거만 올린다**.

    reference  ⊂  recommended  ⊂  extended
    (물량 기본)    (물량 기본 +      (물량 확장 +
                   근거 보강)        근거 보강)

⚠ 두 축을 한 선택지에 묶은 것은 사용자 결정(프리셋 3단계)이다. 그 대가로 "물량은 확장인데
근거는 기본" 은 고를 수 없다 — 그 조합이 필요해지면 선택지를 축별로 쪼개야 한다.

⚠ **근거 축이 지금 바꾸는 것은 STS 뿐이다**(`is_evidence_enriched` docstring 참조).
라이브 실측(HDPDM01, 같은 입력): TC 449 **불변** · 관측 가능한 기대결과 33.9% → 60.0%.
"""
from __future__ import annotations

from typing import Any, Tuple

TC_PROFILE_REFERENCE = "reference"       # 정본 규모(기본)
TC_PROFILE_RECOMMENDED = "recommended"   # 물량은 정본 규모, 시험 근거만 보강
TC_PROFILE_EXTENDED = "extended"         # 근거 보강 + 상한 없이

_KNOWN = (TC_PROFILE_REFERENCE, TC_PROFILE_RECOMMENDED, TC_PROFILE_EXTENDED)

#: 근거 보강이 켜지는 프로파일. `extended` 가 `recommended` 를 **포함**한다는 규약의 구현체다.
_EVIDENCE_ON = (TC_PROFILE_RECOMMENDED, TC_PROFILE_EXTENDED)


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
    """**물량** 상한을 푸는가 — `extended` 에서만 참.

    ⚠ `recommended` 가 생겨도 이 술어의 뜻은 바뀌지 않는다. 기존 호출부
    (`sts.generate_test_cases` · `suts.generate_suts` · `sits.resolve_profile_caps`)가
    이 값으로 **상한**을 풀기 때문에, 여기에 `recommended` 를 섞으면 "물량은 그대로"
    라는 약속이 깨진다.
    """
    return normalize_tc_profile(value)[0] == TC_PROFILE_EXTENDED


def is_evidence_enriched(value: Any) -> bool:
    """**시험 근거**를 보강하는가 — `recommended` 이상에서 참.

    보강이 늘리는 것은 문장의 **정확도**이지 TC 수가 아니다. 기대결과를 관측 가능한
    형태로 바꾸고(반환값 · **쓰기** 전역 · 경계 실값), 하한 위반 스텝을 더한다.

    ⚠ 근거를 **지어내지 않는다**: 반환 타입·전역·경계값을 모르면 현행 문장을 그대로
    두고 그 수를 공시한다(`generation_disclosures` 의 "비운 칸은 warning 이 아니다" 규약).
    `[IN]` 전역은 함수가 **읽기만** 하므로 "갱신/값 변화" 의 근거가 아니다 — 방향 태그를
    버리고 이름만 쓰면 안 일어나는 일을 단언하게 된다(실측 HDPDM01: 370 중 164).

    ⚠ **지금 산출이 바뀌는 것은 STS 뿐이다.**
      - SUTS — 값 칸이 이미 99% 차 있다(실측 61,973칸 중 비움 539). 보강 대상이 아니다.
      - SITS — 경계 sub-case 를 낸 흐름 **수만** 공시한다. Gen Method 칸에 ABV 를 붙이는
        안은 되돌렸다(사유 3건은 `generators/sits.py` 의 `_SITS_BV_MIN_DISTINCT` 블록).
      두 문서에도 이 값을 받아 두는 것은 프리셋이 문서 종류마다 갈리면 "확장인데 근거는
      기본" 같은 조합이 다시 생기기 때문이다 — 게이트 `effect` 가 문서별로 무엇이 바뀌는지 적는다.
    """
    return normalize_tc_profile(value)[0] in _EVIDENCE_ON
