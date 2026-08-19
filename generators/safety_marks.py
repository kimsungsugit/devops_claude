"""ISO 26262 안전 판정 — 규격서 3종(STS·SUTS·SITS)의 **단일 출처**.

## 왜 별도 모듈인가

같은 판정이 세 벌 있었다: `suts.resolve_safety_related` · `sits._safety_mark` ·
`sts._safety_mark`. 세 구현은 실측상 동작이 완전히 같았지만(2026-08-19 대조), 안전 판정을
고친 커밋 3건(`fe9481e`·`e69b9dd`·`fb385d8`)이 **`sts.py` 를 한 번도 안 건드렸다**. 다음
수정에서 갈라지는 건 시간 문제였다 — 이 저장소가 "복제 → 한쪽만 수정" 으로 반복해 겪은
실패다.

`suts.py` 에 두고 나머지가 가져다 쓰는 방법도 있었지만, `sts.py` 가 무거운 `suts` 를
모듈 로드 시점에 끌어오게 된다. 안전 판정은 자기 이름의 자리를 가질 만한 축이다.

## 규약 (바꾸지 말 것)

- `O` = 안전 관련 · `X` = 비안전 · **빈칸 = 근거 없음**.
- **근거 부재를 `X` 로 단정하지 않는다.** `X` 는 "확인했고 안전 관련이 아니다" 라는
  주장이다. 모르는 것을 그렇게 적으면 under-classification 이고, 정본에도 빈칸이
  137개 있다(SUTS 실측) — 빈칸이 정직한 표기다.
- `TBD` 는 반대 주장이 아니라 **근거 부재**다. `QM`(안전요구 면제)으로 바꾸지 않는다.
"""
from __future__ import annotations

from typing import Any

#: 안전 등급으로 인정하는 값. `ASIL B` 처럼 접두가 붙은 표기도 받는다.
_SAFETY_GRADES = ("A", "B", "C", "D")

#: "확인했고 안전 관련이 아니다" 를 뜻하는 유일한 값.
_NON_SAFETY = "QM"


def resolve_safety_related(asil: Any) -> str:
    """정본의 `Safety Related` 칸 값 — ``O`` / ``X`` / ``""``.

    ⚠ 과거 SUTS 판은 ``"X" if is_safety else ""`` 였다. **의미가 정반대**였고, ASIL 을
    가진 단위가 문서상 "비안전" 으로 읽혔다. 정본은 `O` 566 · `X` 311 로 두 값을 다
    쓰며 `O` 가 안전 관련이다(실측).
    """
    val = str(asil or "").strip().upper()
    if val in _SAFETY_GRADES or val.startswith("ASIL"):
        return "O"
    if val == _NON_SAFETY:
        return "X"
    return ""


def is_safety_asil(asil: Any) -> bool:
    """등급 문자열이 **안전 관련**인가 — 근거가 없으면 False.

    `sts.py` 안에만 이 술어가 네 벌 있었고 그중 하나만 표기가 달랐다
    (`not in ("TBD", "")` vs `!= "TBD"`). 앞의 truthy 검사 때문에 `""` 가지가
    도달 불가였어서 동작은 같았지만, 읽는 사람은 "여기만 다른 규칙" 으로 읽는다.

    ⚠ `resolve_safety_related` 와 **완전히 같지는 않다** — 알 수 없는 등급(예 `"Z"`)을
      여기서는 True(보수적으로 안전 취급)로, 저기서는 빈칸(근거 없음)으로 낸다.
      **둘 다 "비안전" 을 주장하지 않는다**는 점이 규약이고, 그것만 정합이면 된다.
      여기를 `resolve_safety_related` 와 강제로 맞추면 미상 등급이 비안전으로
      내려가 under-classification 이 된다 — 고치는 방향이 반대다.
      (`test_safety_marks.py` 가 이 계약을 강제한다. `O` 를 내는 입력은 여기서도 True.)
    """
    val = str(asil or "").strip().upper()
    if not val or val == "TBD":
        return False
    return _NON_SAFETY not in val
