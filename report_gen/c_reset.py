# -*- coding: utf-8 -*-
"""전역/정적 변수의 **Reset Value** 판정 — 값과 **출처**를 함께 낸다.

## 왜 출처까지 적는가 (실측 2026-08-26)

정본 SUDS 의 `Reset Value` 열은 **한 가지 뜻이 아니다**. 같은 변수에 두 값을 적는
심볼이 465개 중 **16개(칸으로는 2,191 중 100 = 4.6%)** 다:

    u8g_ApiIn_LinRx_LatchState    0x00 × 8칸 · 0x03 × 11칸
    u8g_ApiIn_LinRx_MovementReq   0x00 × 13칸 · 0x04 × 1칸
    u16g_ApiIn_MotorTempLvl       0x00 × 7칸 · 0x41 × 1칸

두 뜻이 섞여 있다 — ① **C 정적 저장기간**(main 진입 전 0) 과 ② **리셋 함수가 넣는 값**.
`g_ApiIn_LinRx_ReadData_Reset()` 이 `u8g_ApiIn_LinRx_LatchState = u8g_LATCH_UNKNOWNED`
(=`0x03`) 를 대입하므로 둘 다 사실이고, 어느 쪽을 적었는지는 칸마다 다르다.

표시 없이 값만 적으면 우리도 그 모호함을 그대로 물려받는다. 특히 `0x00` 은
"주변온도 0 에서 시작한다" 처럼 **우리가 세운 적 없는 운용 주장**이 될 수 있다
(그 신호의 실제 초기값은 `0xFF`=무효 표식이다). 그래서 값 옆에 근거를 적는다 —
이 저장소가 `Value Range` 의 `(타입 폭)` 에서 이미 한 번 내린 결정과 같다.

## 규칙과 실측 정밀도 (정본 대조, 단일 심볼 칸 기준)

    ① 선언 초기화식              → 그 값            (배열이면 첫 원소)
    ② 리셋/초기화 이름 함수의 **상수 대입이 하나뿐** → 그 값
       · 값이 갈리면            → 비움
       · 상수가 아닌 값을 넣으면 → 비움 (리셋 후 값을 우리가 모른다)
    ③ 배치 주소(`@0x…`)로 선언된 변수 → 비움 (리셋 값이 MCU 데이터시트에 있다)
    ④ 그 외                     → 0                 (C 정적 저장기간 보장)

    채움 1,862칸 · 정밀도 **96.5%**
      · `Reset 함수`     1,853칸  96.4%
      · `정적 저장기간`       9칸 100.0%

⚠ 남은 3.5%(66칸)의 **41칸은 정본이 스스로 갈린 심볼**이다 — 우리 값이 그 심볼의
   다른 칸에 정본 값으로 실제로 적혀 있다. 대조 대상의 모호성이지 우리 오류가 아니다.

⚠ 규칙 ④를 **거부권 없이** 쓰면(전부 0) 정밀도가 93.7% 로 내려가고, 실패가 하필
   `u8g_ApiIn_LinRx_*` 같은 외부 인터페이스 신호 34칸에 몰린다. ISO 26262 에서
   유효성을 가장 따지는 자리라 그 조합은 쓰지 않는다.

## 레지스터 판정은 **배치 주소 문법**으로 한다

`REG_` 접두나 MCU 헤더 파일명으로 거르면 프로젝트 이름이 규칙에 박힌다. 실측으로
`extern volatile ADC0STSSTR REG_ADC0STS @0x00000602;` 의 `@0x…` 로 잡으면 355개 중
**353개가 일치**하고, 어긋난 2개(`RSA_Exponent_E`·`RSA_Modulus_N`)는 MCU 헤더에 있을
뿐 레지스터가 아니다 — **배치 주소 쪽이 더 정확하다**.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 출처 라벨. 셀에는 `값 (출처)` 로 실린다.
RESET_SRC_DECL = "선언"
RESET_SRC_FUNC = "Reset 함수"
RESET_SRC_ZERO = "정적 저장기간"

#: 못 정한 사유 — 셀은 비우고 이 문자열만 payload 에 남긴다.
SKIP_DECL_NONNUMERIC = "선언값 비수치"
SKIP_CONFLICT = "리셋 대입 상충"
SKIP_RUNTIME = "리셋이 런타임 값"
SKIP_PLACED = "배치 주소(데이터시트)"

#: 함수 이름에 `reset`/`init` 이 **한 마디로** 들어간 것만. 부분 문자열로 보면
#: `initiate_transfer` 같은 이름이 걸린다.
_RESET_FN_RE = re.compile(r"(?:^|_)(?:reset|init)(?:$|_)", re.I)

#: `x = v;` 만. ⚠ 앞에 `*`·`.`·`->` 가 오면 대상이 그 변수가 아니다.
#: ⚠ `x[0] = v` · `s.m = v` 는 **일부러 제외**한다 — 변수 전체의 리셋 값이 아니다.
_ASSIGN_RE = re.compile(r"(?<![\w*.>])([A-Za-z_]\w*)\s*=\s*([^=;][^;]*);")

#: `extern volatile T NAME @0x00000602;` — 메모리 맵 배치.
PLACED_GLOBAL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*@\s*0[xX][0-9A-Fa-f]+")

_NUM_RE = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F]+|\d+)$")
_CAST_RE = re.compile(r"^\(\s*(?:un)?signed\b[\w\s]*\)|^\(\s*[A-Za-z_]\w*\s*\)")

_WIDTH_BY_TYPE = {
    "u8": 2, "s8": 2, "char": 2, "int8": 2, "uint8": 2, "l_u8": 2, "byte": 2,
    "u16": 4, "s16": 4, "short": 4, "int16": 4, "uint16": 4, "l_u16": 4, "word": 4,
    "u32": 8, "s32": 8, "long": 8, "int32": 8, "uint32": 8, "l_u32": 8, "dword": 8,
}


def is_reset_function(name: Any) -> bool:
    """이름에 `reset`/`init` 이 한 마디로 든 함수인가.

    ⚠ "어느 함수가 시동 시 도는가" 를 호출 그래프로 풀려던 것이 R5 에서 이 축을
      막고 있었는데, 실소스는 그 답을 **이름에 적어 두고 있었다**
      (`g_ApiIn_LinRx_ReadData_Reset`·`g_DrvIn_Main_Reset`·`PE_low_level_init_1` …
      대입이 있는 함수 364개 중 35개).
    """
    return bool(_RESET_FN_RE.search(str(name or "")))


def collect_reset_assignments(
    body_map: Dict[str, str],
) -> Dict[str, List[Tuple[str, str]]]:
    """`{변수: [(함수, 대입식 원문), …]}` — 리셋/초기화 이름 함수 안의 대입만.

    `body_map` 은 `source_parser._extract_c_function_bodies` 산출물이다(주석이
    지워진 텍스트를 넣을 것 — 주석 안 대입을 세면 없는 초기화를 만들어낸다).
    """
    out: Dict[str, List[Tuple[str, str]]] = {}
    for fname, body in (body_map or {}).items():
        if not is_reset_function(fname):
            continue
        for m in _ASSIGN_RE.finditer(str(body or "")):
            out.setdefault(m.group(1), []).append((str(fname), m.group(2).strip()))
    return out


def _outer_parens_match(text: str) -> bool:
    """맨 앞 `(` 가 **맨 뒤 `)`** 와 짝인가.

    ⚠ 이걸 안 보고 `^\\((.*)\\)$` 로 벗기면 `(U16)(0x1234)` 가 `U16)(0x1234` 가 된다.

    ⚠ **지금은 `startswith("(") and endswith(")")` 와 결과가 같다** — 위 루프가 캐스트를
      먼저 걷어내서 짝이 어긋난 채로 여기 도달하는 입력이 없기 때문이다(실측: 실물
      매크로 모양 220개 대조, 차이 0). 그래도 **우연히 맞는 규칙은 채택하지 않는다** —
      이 시리즈가 `void` 판정에서 그렇게 4개월을 잃었다
      (`report_gen/c_return.py` 참조). 순서가 바뀌면 이 판정이 유일한 방어다.
    """
    if len(text) < 2 or not text.startswith("(") or not text.endswith(")"):
        return False
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i == len(text) - 1
    return False


def as_constant(text: Any, macro_values: Optional[Dict[str, Any]] = None,
                _depth: int = 0) -> Optional[int]:
    """`( ( U8 )( 0xFFU ) )` · `(U16)(0x1234)` · `0x00` · `12U` · 매크로 → 정수.

    못 접으면 `None` — 그건 "런타임 값" 이라 리셋 값으로 쓰지 않는다.

    ⚠ 매크로가 매크로를 가리키는 사슬을 따라가되 깊이를 막는다. 안 막으면 순환
      매크로 하나에 문서 생성이 통째로 멈춘다.
    """
    s = re.sub(r"\s+", "", str(text or ""))
    if not s:
        return None
    for _ in range(8):                       # 캐스트 → 균형 잡힌 바깥 괄호 순
        nxt = _CAST_RE.sub("", s)
        # ⚠ `nxt` 가 비면 그건 캐스트가 아니라 **괄호 친 매크로**였다(`(u8g_BASE)`).
        #   정규식만으로 `(U8)x` 와 `(A)` 를 못 가르므로, 뒤에 아무것도 안 남으면
        #   캐스트로 보지 않고 아래 괄호 벗기기로 넘긴다.
        if nxt != s and nxt:
            s = nxt
            continue
        if _outer_parens_match(s):
            s = s[1:-1]
            continue
        break
    bare = re.sub(r"[uUlL]+$", "", s)
    if _NUM_RE.match(bare):
        try:
            return int(bare, 16) if bare.lower().lstrip("+-").startswith("0x") else int(bare, 10)
        except ValueError:
            return None
    if macro_values and _depth < 4:
        hit = macro_values.get(s)
        if isinstance(hit, int):
            return hit
        if hit is not None:
            return as_constant(hit, macro_values, _depth + 1)
    return None


def hex_width_of(ctype: Any) -> int:
    """타입 폭에 맞춘 16진 자릿수. 모르면 2 — 정본도 `0x00` 을 기본으로 쓴다."""
    text = re.sub(r"\b(?:const|volatile|static|extern|unsigned|signed)\b", " ",
                  str(ctype or ""), flags=re.I)
    text = re.sub(r"\[.*$|\*", " ", text)
    for tok in text.split():
        hit = _WIDTH_BY_TYPE.get(tok.strip().lower())
        if hit:
            return hit
    return 2


def format_reset(value: int, ctype: Any) -> str:
    """`0x03` · `0x0000` — 정본 표기(폭 맞춘 16진)를 따른다."""
    width = hex_width_of(ctype)
    if value < 0:
        return f"-0x{-value:0{width}X}"
    return f"0x{value:0{width}X}"


def _first_initializer(init: Any) -> str:
    """`{0x00, 0x1D, …}` → `0x00`. 배열은 첫 원소가 리셋 값이다."""
    text = str(init or "").strip()
    if text.startswith("{"):
        text = text[1:]
    return text.split(",")[0].strip().rstrip("}").strip()


def resolve_reset(
    ginfo: Optional[Dict[str, Any]],
    assignments: Optional[Sequence[Tuple[str, str]]] = None,
    macro_values: Optional[Dict[str, Any]] = None,
    *,
    placed: bool = False,
) -> Tuple[str, str]:
    """`(셀에 적을 문자열, 출처)`. 못 정하면 `("", 사유)`.

    ⚠ **모르면 비운다.** 근거 없는 `0x00` 은 값 부재보다 나쁘다 — 빈 칸이면 하지
      않았을 주장을 틀리게 하는 것이라, 이 저장소가 Phase 3(설명 밀림)·R8(멤버 행)
      에서 두 번 고친 모양이다.
    """
    info = ginfo if isinstance(ginfo, dict) else {}
    ctype = info.get("type")

    init = str(info.get("init") or "").strip()
    if init:
        n = as_constant(_first_initializer(init), macro_values)
        if n is None:
            return "", SKIP_DECL_NONNUMERIC
        return f"{format_reset(n, ctype)} ({RESET_SRC_DECL})", RESET_SRC_DECL

    consts, runtime = set(), False
    for _fn, expr in (assignments or ()):
        n = as_constant(expr, macro_values)
        if n is None:
            runtime = True
        else:
            consts.add(n)
    if len(consts) > 1:
        return "", SKIP_CONFLICT
    if consts:
        n = next(iter(consts))
        return f"{format_reset(n, ctype)} ({RESET_SRC_FUNC})", RESET_SRC_FUNC
    if runtime:
        # 리셋 함수가 값을 넣긴 하는데 우리가 그 값을 모른다 → `0` 이라 적으면 거짓.
        return "", SKIP_RUNTIME
    if placed:
        return "", SKIP_PLACED
    return f"{format_reset(0, ctype)} ({RESET_SRC_ZERO})", RESET_SRC_ZERO


def placed_global_names(text: Any) -> Iterable[str]:
    """배치 주소로 선언된 이름들 — 그 변수의 리셋 값은 소스에 없다."""
    return (m.group(1) for m in PLACED_GLOBAL_RE.finditer(str(text or "")))
