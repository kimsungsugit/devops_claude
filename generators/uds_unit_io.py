"""SwUDS 문서에서 함수별 **Input / Output Parameters** 를 읽는다.

## 왜 이게 시험 입력·기대결과의 출처인가

SUTS 는 SwUDS(단위 상세 설계)를 근거로 만드는 문서다. 정본 SwUDS 는 함수마다 표를
하나 두고, 그 안에 `[ Input Parameters ]` · `[ Output Parameters ]` 를
`No | Name | Type | Value Range | Reset Value | Description` 로 적는다. 즉 **정본
SUTS 의 Inpt/ExpR 열은 소스 파싱 결과가 아니라 이 표**다.

실측(2026-08-14, KJPDS02_PV — SwUDS 함수 1,026 · 정본 SUTS 1,005, 이름 교집합 1,001).
첨자를 지운 이름 집합으로 재현율/정밀도를 재면:

                       입력 재현율 · 과다      기대 재현율 · 과다
    소스 파싱(현행)      84.3%  ·  617          84.0%  ·  550
    **SwUDS**           88.0%  ·  110          83.6%  ·  348
    SwUDS + 우리 `return` 표기                  **94.1%** ·  358

즉 UDS 로 바꾸면 **더 많이 맞히면서 과다는 1/6** 이 된다. 기대결과 축만 예외인데,
정본이 쓰는 VectorCAST 표기(`return` · `f() p[0]() m`)를 UDS 가 안 적기 때문이다 —
그건 우리 것을 남긴다.

⚠ `사용 전역변수` 칸은 **쓰지 않는다**. 방향이 없어서 입력·기대 양쪽에 넣으면 과다가
  110 → 1,079 로 터진다(실측). 방향을 아는 두 표만 쓴다.

## 문서 표기를 정본 표기로

- `->` 는 여기서 안 건드린다. 정본은 `p[0].m` 으로 적는데(실측: 정본 `->` 1건 vs
  `[0].` 498건), 그 변환은 `generators.suts._vc_pointer_notation` **한 곳**에만 둔다.
  여기서 또 변환하면 규칙이 두 벌이 된다.
- `[x]` 는 문서의 **자리표시자**다(UDS 123건 vs 정본 SUTS **0건**). 그대로 옮기면
  정본에 없는 이름을 만들어 내므로 첨자를 떼고 base 로 둔다 — 실제 원소 펼침은
  소스에서 얻은 크기로 `_expand_array_entries` 가 한다.
- `DiagData. OpenFailure [3]` 처럼 문서에 공백 오타가 있다(20건). 식별자 사이 공백만
  지운다.

## 동명이인은 채우지 않는다

같은 함수명이 서로 다른 설계 ID 로 두 번 나오는 경우가 있다(실측 9건: `main` ·
`SCI0_Init` 등 — 다른 모듈의 static 함수). 어느 쪽 표인지 이름만으로 못 정하므로
**후보에서 뺀다**. 임의로 하나를 고르면 그 함수의 시험 변수가 조용히 틀린다
(`[[project_provenance_laundering]]` 계열: 틀린 근거는 빈칸보다 나쁘다).

## 문서 판독 (R65 — 사용자 방향 10-06 "입력문서를 제대로 읽지 못하면 아무것도 진행할 수가 없어")

R63 판독 실측(같은 파일을 lxml 로 독립 판독해 대조)이 찾은 손실을 읽는다:

- **머리말 이름**: `u8s_DataValidCheck(New)` 처럼 표시가 붙은 머리말(HDPDM01 18 함수)과 머리말 오타(표 `Name` 행이
  소스 이름 — 2 함수)는 `generators.uds_design_ids.iter_design_entries` 한 판독기로 읽는다.
- **행의 열은 그리드 열**: `w:gridSpan` · `w:gridBefore` 를 펼쳐 머리행과 같은 좌표로 읽는다(python-docx `row.cells`
  와 같은 규칙) — 칸 하나가 여러 열을 덮는 행이 다른 열을 이름으로 읽지 않는다.
- **세로 병합으로 번호 칸이 빈 행**(`No` 칸이 위 행과 병합 — HDPDM01 10 행 · 7 함수)도 이름 칸이 지시자면 파라미터 행이다.
- **이름은 지시자만**: `pst_Queue-> ast_Queue[x].u8_Data` 의 `->` 둘레 공백을 지우고(KJPDS02_PV 11 행), 지시자
  (`a.b` · `p->m` · 첨자)가 아닌 글(`if( … )` 가 이름 칸에 든 행)이나 숫자로 시작하는 오타(`8g_…`)는 이름으로 쓰지 않고
  `reading.rows_unread` 에 사유와 원문으로 남긴다.
- **Value Range 판독기 하나**(`read_value_range`): 행의 Type 칸(문서가 적은 타입)과 함께 읽는다 — 아래 함수 docstring.
  못 읽은 칸도 원문과 사유를 남겨(`range_unread` · `range_text`) 공시가 "문서를 이렇게 고치면 설계 범위로 시험한다" 를
  말할 수 있게 한다.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from generators.uds_design_ids import (
    checked_aliases,
    iter_design_entries,
    iter_text_nodes,
    name_row_aliases,
    read_docx_body,
    read_error_text,
    read_toc_style_ids,
    restrict_aliases,
    select_live_headings,
    text_of_node,
)

_logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 표 안 섹션 머리. 정본 표기는 `[ Input Parameters ]` 지만 공백 흔들림을 허용한다.
_SEC_IN = re.compile(r"^\[\s*Input\s+Parameters", re.I)
_SEC_OUT = re.compile(r"^\[\s*Output\s+Parameters", re.I)
_SEC_END = re.compile(r"^\[\s*(Logic\s+Diagram|Function\s+Information)", re.I)

# 값이 없다는 표기들. 이걸 이름으로 받으면 열에 `N/A` 가 박힌다.
_NA = {"", "n/a", "na", "n.a", "-", "--", "없음", "none"}

# 첨자는 **전부** 뗀다 — UDS 의 `name[N]` 은 원소 참조가 아니라 **선언 크기**다.
#
# 실측(2026-08-14, KJPDS02_PV):
#   · `ADC_MONITOR_Init` UDS 입력 = `CSL[9]` · `RVL[9]`  (소스 선언 `U8 CSL[8]`)
#   · 정본 SUTS 는 같은 unit 을 `CSL[0]`…`CSL[7]` 로 **펼쳐** 적는다
# 그대로 옮기면 ①정본에 없는 이름 `CSL[9]` 이 생기고 ②이미 첨자가 붙어 있어
# `_expand_array_entries` 가 **원소 확장을 건너뛴다**. 첫 판이 정확히 그래서 입력
# 일치가 5,029 → 2,725 로 무너졌고, 사라진 맞춤 2,419건 중 **2,391건(98.8%)** 이
# 이 경로였다.
# ⚠ 선언 크기를 **크기 힌트로도 쓰지 않는다** — 위 예에서 UDS 는 9, 소스는 8 이다.
#   문서 숫자를 믿으면 없는 원소를 하나 더 만들어 낸다. 크기는 소스에서만 얻는다.
# `[x]` 같은 자리표시자도 같은 규칙으로 사라진다(정본 SUTS 에 `[x]` 0건 · UDS 123건).
_ANY_IDX = re.compile(r"\[[^\]]*\]")

_CACHE: Dict[str, Tuple[Tuple[int, int], float, Dict[str, Any]]] = {}
_CACHE_TTL_SEC = 600.0


def _signature(p: Path) -> Optional[Tuple[int, int]]:
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError as exc:
        _logger.debug("uds unit-io: stat failed for %s: %s", p, exc)
        return None


def clean_param_name(raw: Any) -> str:
    """문서 표기 → 이름. 못 쓰는 값이면 빈 문자열.

    ⚠ 포인터 `->` 변환은 **여기서 하지 않는다**(위 모듈 주석 참조).
    """
    s = str(raw or "").strip()
    if s.lower() in _NA:
        return ""
    s = _ANY_IDX.sub("", s)                  # 선언 크기·자리표시자 첨자 제거
    # `DiagData. OpenFailure [3]` · (R65) `pst_Queue-> ast_Queue` — 지시자 연산자 둘레 공백
    s = re.sub(r"\s*(->|[.\[\]])\s*", r"\1", s)
    s = s.strip().strip(",;")
    if not s or s.lower() in _NA:
        return ""
    # 식별자로 시작하지 않으면(설명문이 이름 칸에 들어온 경우) 버린다.
    if not re.match(r"^[A-Za-z_]", s):
        return ""
    return s


# (R65) 이름 칸은 지시자여야 한다 — `a` · `a.b` · `p->m`(첨자는 `clean_param_name` 이 뗐다).
_DESIGNATOR = re.compile(r"^[A-Za-z_]\w*(?:(?:\.|->)[A-Za-z_]\w*)*$")


def _cell_lines(tc) -> List[str]:
    """셀 텍스트를 **줄 단위**로.

    ⚠ 문단(`w:p`)만 끊으면 부족하다 — 한 문단 안에서 `w:br` 로 나열하는 칸이 있어
      문단 단위로만 뽑으면 `u8s_A_Fu8s_B_Cnt` 처럼 이름이 뭉친다(실측).
    """
    out: List[str] = []
    for p in tc.findall(f"{_W}p"):
        buf: List[str] = []
        # (R65) 글상자 · 도형 안 글은 칸의 글이 아니다 · 비분리 하이픈은 `-` · 탭은 공백(머리말과 같은 판독 — `text_of_node`)
        for node in iter_text_nodes(p):
            piece = text_of_node(node)
            if piece == "\n":
                s = "".join(buf).strip()
                if s:
                    out.append(s)
                buf = []
            else:
                buf.append(piece)
        s = "".join(buf).strip()
        if s:
            out.append(s)
    return out


_NUM_HEX = re.compile(r"^([-+]?)0[xX]([0-9a-fA-F]+)$")
_NUM_DEC = re.compile(r"^[-+]?\d+$")
# `FFFF` · `7FFFFFFF` — 0x 없이 적은 16진. 대문자 16진 글자만, 숫자가 하나 섞였거나 전부 F 일 때만 16진으로 확정한다
#   (리뷰 R65 I2: `AB` · `cell` 같은 낱말을 수로 읽지 않는다)
_NUM_BARE_HEX = re.compile(r"^(?!\d+E\d+$)(?:(?=[0-9A-F]*[A-F])(?=[0-9A-F]*[0-9])[0-9A-F]{2,}|F{2,})$")
_RANGE_SEP = re.compile(r"\s*(?:~|\.{2,3}|\bto\b)\s*", re.I)
_EXCLUDE_NOTE = re.compile(r"^(?P<v>\S+?)\s*(?:제외|excluded|excluding|except)$|^(?:except|excluding)\s+(?P<w>\S+)$",
                           re.I)
# 정수 타입 이름 — 대소문자를 가리지 않는다(리뷰 R65 W4: `SINT16` · `INT16` 을 못 알아보면 `0x7FFF ~ 0x8000` 이 32767 ~ 32768)
_INT_TYPE = re.compile(r"^(?:([su])(8|16|32|64)(?:_t)?|(u|s)?int(8|16|32|64)(?:_t)?)$", re.I)
_INT_CANON = {"uint8_t": (False, 8), "int8_t": (True, 8), "uint16_t": (False, 16), "int16_t": (True, 16),
              "uint32_t": (False, 32), "int32_t": (True, 32), "uint64_t": (False, 64), "int64_t": (True, 64)}
# `_normalize_type` 가 `_t` 없이 돌려주는 표 키도(리뷰 R65 2차 N11)
_INT_CANON.update({k[:-2]: v for k, v in list(_INT_CANON.items())})


def document_int_type(type_text: Any) -> Optional[Tuple[bool, int]]:
    """(R65) 문서 Type 칸 → `(부호 있음, 비트)` — 폭이 정해진 정수 타입만(`U8` · `S16` · `SINT16` · `uint32_t` · `byte`
    · `unsigned short` 처럼 SUTS 타입 표 `_normalize_type` 가 아는 이름 포함).

    포인터(`*`)는 None(포인터 칸의 범위는 주소다 — SUTS `_is_pointer_decl` 이 따로 다룬다), 배열 첨자는 떼고 원소 타입,
    `int` · `long` 처럼 타깃마다 폭이 다른 이름 · typedef · enum · bool 도 None(폭을 문서가 말하지 않았다).
    """
    t = " ".join(str(type_text or "").split())
    if not t or "*" in t:
        return None
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"\b(?:const|volatile|static)\b", "", t, flags=re.I).strip()
    m = _INT_TYPE.match(t)
    if m:
        if m.group(1):
            return (m.group(1).lower() == "s", int(m.group(2)))
        return ((m.group(3) or "").lower() != "u", int(m.group(4)))
    # SUTS 타입 표와 같은 이름 규칙(늦게 부른다 — suts 가 이 모듈을 import 한다)
    from generators.suts import _normalize_type

    return _INT_CANON.get(_normalize_type(t))


def _full_range(width: Optional[Tuple[bool, int]]) -> Optional[Tuple[int, int]]:
    if not width:
        return None
    return (-(1 << (width[1] - 1)), (1 << (width[1] - 1)) - 1) if width[0] else (0, (1 << width[1]) - 1)


def _literal(tok: str) -> Optional[Tuple[int, str, int]]:
    """정수 글자 → (값, 종류 `hex`/`dec`/`barehex`, 16진 자릿수). 실수 · 단위가 붙은 글은 None."""
    tok = re.sub(r"[uUlL]+$", "", tok.strip())
    m = _NUM_HEX.match(tok)
    if m:
        v = int(m.group(2), 16)
        return (-v if m.group(1) == "-" else v, "hex", len(m.group(2)))
    if _NUM_DEC.match(tok):
        return (int(tok), "dec", 0)
    if _NUM_BARE_HEX.match(tok):
        return (int(tok, 16), "barehex", len(tok))
    return None


def _signed(lit: Tuple[int, str, int], width: Optional[Tuple[bool, int]]) -> int:
    """2의 보수 — 문서 타입이 부호 있는 정수이고 16진 글자가 **그 폭의 자릿수 그대로**일 때만(`0xFF10` S16 = -240)."""
    v, kind, digits = lit
    if width and width[0] and kind in ("hex", "barehex") and digits * 4 == width[1] and v >= 1 << (width[1] - 1):
        return v - (1 << width[1])
    return v


def _signed_full_pair(la: Tuple[int, str, int], lb: Tuple[int, str, int]) -> Optional[int]:
    """`0x8000 ~ 0x7FFF`(최소 ~ 최대) 또는 `0x7FFF ~ 0x8000`(최대 ~ 최소) — 같은 자릿수 16진으로 쓴 부호 있는 전폭이면 그 비트
    (8 · 16 · 32), 아니면 None."""
    if not (la[1] == lb[1] == "hex" and la[2] == lb[2] and la[2] * 4 in (8, 16, 32)):
        return None
    half = 1 << (la[2] * 4 - 1)
    return la[2] * 4 if {la[0], lb[0]} == {half, half - 1} else None


def _read_pair(a: str, b: str, width: Optional[Tuple[bool, int]], notation: List[str]) -> Dict[str, Any]:
    la, lb = _literal(a), _literal(b)
    if la is None or lb is None:
        return {"unread": "not_a_number"}
    if "barehex" in (la[1], lb[1]):
        other = lb if la[1] == "barehex" else la
        # 0x 없는 16진은 짝이 두 진법에서 같은 값(한 자리 십진)이거나 16진일 때만 — `10 ~ FF` 는 10 이 16 일 수 있다
        if other[1] == "dec" and not 0 <= other[0] <= 9:
            return {"unread": "hex_without_prefix"}
        notation.append("hex_without_prefix")
    bits = _signed_full_pair(la, lb)
    if bits and width is None:
        # (R74 · 리뷰 R65 W4) 타입을 모를 때는 **정확히 전폭인** 부호 있는 쌍만 — 최소 ~ 최대든 최대 ~ 최소든. 자릿수만 보고
        #   고치면 내림차순 표기 `0xFFFF ~ 0x0000` 이 (-1, 0) 이 된다(리뷰 C2)
        notation.extend(["signed_hex"] + (["descending_full_width"] if la[0] < lb[0] else []))
        return {"range": (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)}
    if bits and width and (not width[0] or width[1] != bits):
        # 부호 없는 타입(`U16`)이나 폭이 다른 타입에 부호 전폭 표기 — 같은 행이 서로 다른 말을 한다(HDPDM01 U16 4 행 —
        #   그대로 읽으면 32767 ~ 32768 두 값). 고르지 않는다
        return {"unread": "signed_notation_unsigned_type" if not width[0] else "signed_notation_width_differs"}
    lo, hi = _signed(la, width), _signed(lb, width)
    if (lo, hi) != (la[0], lb[0]):
        notation.append("signed_hex")
    full = _full_range(width)
    if full and (min(lo, hi) < full[0] or max(lo, hi) > full[1]):
        # 문서가 같은 행에 적은 타입이 담을 수 없는 값 — `0x7FFFF ~ 0x8000`(S16, F 다섯) 같은 오타 후보
        return {"unread": "outside_document_type"}
    if lo > hi:
        # `최대 ~ 최소` 는 **타입 전체를 위에서 아래로** 적은 것만 읽는다(HDPDM01 `0x7FFF ~ 0x8000` S16 283 행 — 옛 판독은
        #   32767 ~ 32768 로 읽어 '범위 충돌' 로 공시했다). 그 밖의 내림차순(`0xFF10 ~ 0x00F0` 에 부호 타입이 없음,
        #   `0x7FFFFFF~ 0x80000000` 자릿수가 다른 오타)은 적지 않은 범위를 만들어 낸다 — 읽지 않는다.
        if full is None or (hi, lo) != full:
            if la[1] == lb[1] == "hex" and la[2] != lb[2]:
                return {"unread": "digit_count_differs"}
            # 적힌 순서는 오름차순인데 2의 보수로 읽으니 거꾸로 — `0x00F0 ~ 0x80F0`(S16) 같은 다른 부호 표기 후보
            return {"unread": "signed_hex_out_of_order" if la[0] < lb[0] else "descending"}
        lo, hi = hi, lo
        notation.append("descending_full_width")
    if lo == hi:
        # `0x05 ~ 0x05` 는 값 하나다 — 값 하나는 범위로 읽지 않는다(리뷰 R65 2차 N5 — 같은 규칙)
        return {"unread": "single_value"}
    return {"range": (lo, hi)}


def read_value_range(text: Any, type_text: Any = "") -> Dict[str, Any]:
    """(R65) 설계서 `Value Range` 칸 하나 → 무엇이 적혀 있나. **지어내지 않는다** — 못 읽으면 사유만.

    - `{}`: 아무것도 안 적었다(빈칸 · `N/A`).
    - `{"range": (lo, hi)}`: `0x00 ~ 0x01` · `0 ~ 100` · `0x0000U ~ 0xFFFFU` · `0 ... 10` · `array 0x00 ~ 0xFF`(배열 원소의
      범위) · `0x00000000~0x FFFFFFFF`(0x 뒤 공백) · `1,000 ~ 2,000` · 연속인 값 목록 `0x00, 0x01`.
    - `{"values": [...]}`: 연속이 아닌 값 목록 `0, 5, 15` · `0x0000, 0x08DC, 0x09A6` — 설계가 정한 값 집합.
    - `{"unread": 사유}`: `single_value`(값 하나 — 범위인지 기본값인지 문서가 말하지 않는다; 그 값만 넣으면 다른 분기를
      시험하지 않는다) · `multiple_intervals`(`0x00 ~ 0x40, 0x80`) · `descending` · `signed_hex_out_of_order` ·
      `digit_count_differs` · `outside_document_type` · `signed_notation_unsigned_type` ·
      `signed_notation_width_differs` · `not_a_number` ·
      `hex_without_prefix` · `type_in_range_column` · `ambiguous_comma` · `excludes_inner_value` · `excludes_unreadable` ·
      `annotation_disagrees` · `unread_annotation` · `no_value`.
    - `notation`: 읽은 표기(`signed_hex` · `descending_full_width` · `array_elements` · `decimal_annotation_agrees` ·
      `excluded_endpoint` · `value_list_contiguous` · `two_value_list` · `trailing_comma` · `hex_without_prefix`).

    `type_text` 는 같은 행의 Type 칸이다. 부호 있는 정수 타입이면 그 폭 자릿수의 16진을 2의 보수로 읽는다(`0xFF10 ~
    0x00F0` S16 = -240 ~ 240 — KJPDS02_PV LIN 가속도), 괄호 십진 주석(`(-240~240)`)은 읽은 범위와 같을 때 확인으로 쓰고,
    타입이 부호를 말하지 않았을 때(타입 없음 · 부호 있는 타입)만 16진을 제 자릿수 폭의 2의 보수로 다시 읽어 주석과 같으면
    받는다(다르면 `annotation_disagrees`). 괄호 제외(`0x00~0xFF(0x00제외)`)는 끝값일 때만 범위를 줄인다.
    """
    s = " ".join(str(text or "").split())
    if s.lower() in _NA:
        return {}
    notation: List[str] = []
    width = document_int_type(type_text)
    s = re.sub(r"0[xX]\s+(?=[0-9a-fA-F])", "0x", s)
    if re.search(r"\d,\d{3}(?!\d)", s) and re.search(r",\s", s):
        # 천 단위 쉼표와 목록 쉼표가 한 칸에 — `0, 100,200` 은 목록인지 큰 수인지 모른다(리뷰 R65 I1)
        return {"unread": "ambiguous_comma", "notation": notation}
    s = re.sub(r"(?<![\w.])(\d{1,3}(?:,\d{3})+)(?![\w.])", lambda m: m.group(1).replace(",", ""), s)
    note = ""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", s)
    if m and m.group(1):
        s, note = m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^array\b\s*(.*)$", s, re.I)
    if m:
        s = m.group(1).strip()
        notation.append("array_elements")
        if not s:
            return {"unread": "no_value", "notation": notation}
    if _INT_TYPE.match(s) or s.lower() in ("bool", "boolean", "byte", "word"):
        return {"unread": "type_in_range_column", "notation": notation}
    items = [x.strip() for x in s.split(",")]
    if len(items) > 1 and items[-1] == "":
        items.pop()
        notation.append("trailing_comma")
    res: Dict[str, Any]
    if len(items) > 1:
        if any(_RANGE_SEP.search(x) for x in items):
            return {"unread": "multiple_intervals", "notation": notation}
        vals = []
        for x in items:
            lit = _literal(x)
            if lit is None or lit[1] == "barehex":
                return {"unread": "not_a_number", "notation": notation}
            vals.append(_signed(lit, width))
        out = sorted(set(vals))
        full = _full_range(width)
        if full and (out[0] < full[0] or out[-1] > full[1]):
            return {"unread": "outside_document_type", "notation": notation}
        if out[-1] - out[0] + 1 == len(out):
            # `0x00, 0x01` 은 두 끝 사이 정수를 전부 적었다 — `0x00 ~ 0x01` 과 같은 집합
            notation.append("value_list_contiguous")
            res = {"range": (out[0], out[-1])}
        else:
            if len(out) == 2:
                # 두 값 목록은 '값 둘' 인지 '쉼표로 쓴 범위' 인지 문서가 말하지 않는다 — 값 둘로 읽고 표기를 세어 공시한다
                notation.append("two_value_list")
            res = {"values": out}
    else:
        one = items[0] if items else ""
        parts = _RANGE_SEP.split(one)
        if len(parts) == 1:
            return {"unread": "single_value" if _literal(one) else "not_a_number", "notation": notation}
        if len(parts) != 2:
            return {"unread": "not_a_number", "notation": notation}
        res = _read_pair(parts[0], parts[1], width, notation)
        if res.get("unread") in ("outside_document_type", "signed_notation_unsigned_type",
                                 "signed_notation_width_differs"):
            res["notation"] = notation
            return res
    if note:
        ex = _EXCLUDE_NOTE.match(note)
        if ex:
            lit = _literal(ex.group("v") or ex.group("w") or "")
            if lit is None or "range" not in res:
                return {"unread": "excludes_unreadable", "notation": notation}
            v = _signed(lit, width)
            lo, hi = res["range"]
            if v == lo and lo < hi:
                res["range"] = (lo + 1, hi)
            elif v == hi and lo < hi:
                res["range"] = (lo, hi - 1)
            else:
                return {"unread": "excludes_inner_value", "notation": notation}
            if res["range"][0] == res["range"][1]:
                # 제외하고 남은 값이 하나 — 값 하나는 범위로 읽지 않는다(3차 I4 — `x ~ x` 와 같은 규칙)
                return {"unread": "single_value", "notation": notation}
            notation.append("excluded_endpoint")
        else:
            alt = read_value_range(note)
            if "range" not in alt:
                return {"unread": "unread_annotation", "notation": notation}
            if tuple(res.get("range") or ()) == tuple(alt["range"]):
                notation.append("decimal_annotation_agrees")
            else:
                # 타입 칸이 부호를 말하지 않았어도 십진 주석이 말할 수 있다 — 16진을 제 자릿수 폭의 2의 보수로 읽어 같을 때만.
                #   ⚠ 타입이 **부호 없음**이면 하지 않는다(리뷰 R65 W3: U16 칸에 -240 을 만들었다), 결과도 타입 폭 안이어야 한다
                parts = _RANGE_SEP.split(s)
                la = _literal(parts[0]) if len(parts) == 2 else None
                lb = _literal(parts[1]) if len(parts) == 2 else None
                full = _full_range(width)
                if (width is None or (width[0] and width[1] == la[2] * 4)) and la and lb \
                        and la[1] == lb[1] == "hex" and la[2] == lb[2] and la[2] * 4 in (8, 16, 32, 64) \
                        and (_signed(la, (True, la[2] * 4)), _signed(lb, (True, la[2] * 4))) == tuple(alt["range"]) \
                        and (full is None or full[0] <= alt["range"][0] <= alt["range"][1] <= full[1]):
                    notation[:] = [x for x in notation if x != "signed_hex"] + ["signed_hex", "decimal_annotation_agrees"]
                    res = {"range": tuple(alt["range"])}
                else:
                    return {"unread": "annotation_disagrees", "notation": notation}
    res["notation"] = notation
    return res


def parse_value_range(text: Any, type_text: Any = "") -> Optional[Tuple[int, int]]:
    """설계서의 `Value Range` 칸 → `(lo, hi)` 정수. 못 읽으면 None(지어내지 않는다) — `read_value_range` 의 범위만.

    (R74) 표기는 `0x00 ~ 0x01` · `0x0000~0xFFFF` · `0 ~ 100` 이고, 부호 있는 타입은 2의 보수 16진으로 적는다
    (`0x8000 ~ 0x7FFF` = -32768 ~ 32767 — 실측 KJPDS02 555행). 타입(`type_text`)을 모르면 **정확히 전폭인** 쌍만
    부호 있는 값으로 읽는다(최소 ~ 최대 · 최대 ~ 최소). 실수·단위가 섞인 표기(`9 to 16V`)는 대상이 아니다. 값
    목록(`0, 5, 15`)은 범위가 아니다.
    """
    rng = read_value_range(text, type_text).get("range")
    return (int(rng[0]), int(rng[1])) if rng else None


def _row_cells(tr) -> List[Tuple[str, bool]]:
    """(R65) 행의 칸을 **그리드 열**로 — `w:gridBefore` · `w:gridSpan` 을 펼친다(python-docx `row.cells` 와 같은 규칙).
    각 칸은 `(글, 세로 병합 이어짐)`. 칸 하나가 여러 열을 덮으면 같은 글이 그 열마다 온다."""
    out: List[Tuple[str, bool]] = []
    trpr = tr.find(f"{_W}trPr")
    gb = trpr.find(f"{_W}gridBefore") if trpr is not None else None
    if gb is not None:
        try:
            out.extend([("", False)] * int(gb.get(f"{_W}val") or 0))
        except ValueError:
            pass
    for tc in tr.findall(f"{_W}tc"):
        pr = tc.find(f"{_W}tcPr")
        span, cont = 1, False
        if pr is not None:
            gs = pr.find(f"{_W}gridSpan")
            if gs is not None:
                try:
                    span = max(1, int(gs.get(f"{_W}val") or 1))
                except ValueError:
                    span = 1
            vm = pr.find(f"{_W}vMerge")
            cont = vm is not None and (vm.get(f"{_W}val") or "continue") == "continue"
        text = " ".join(_cell_lines(tc))
        out.extend([(text, cont)] * span)
    return out


def _parse_table(tbl, function: str = "", stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """함수 표 하나 → `{"inputs": [...], "outputs": [...], "asil": "...", "description": "...", "param_info": {...}}`.

    ASIL 은 `[ Function Information ]` 블록의 `ASIL` 행이다(값 예: `A` · `QM` · `N/A`).
    (R74) `Description` 행과, 파라미터 표(`No | Name | Type | Value Range | Reset Value | Description`)의 **Type·Value Range**
    도 읽는다 — 설계서가 직접 적은 타입과 범위라 시험 경계값의 가장 강한 출처다(`param_info[이름] = {"type", "range"}`,
    `N/A` 는 싣지 않는다). (R65) 값 목록은 `values`, 못 읽은 칸은 `range_unread`(사유) — 둘 다 `range_text`(원문)와 함께.
    `stats` 에 판독 사실(행 · 이어진 행 · 못 읽은 행 · 범위 판독 결과)을 더한다.
    """
    st = stats if stats is not None else {}
    inputs: List[str] = []
    outputs: List[str] = []
    asil = ""
    description = ""
    param_info: Dict[str, Dict[str, Any]] = {}
    # 파라미터 표의 열은 **머리행으로 찾는다**(리뷰 C1) — `No | Name | Type | Value Range | …` 순서를 상수(2·3)로 박으면
    #   열 순서가 다른 양식에서 `Reset Value` 를 범위로 읽고도 "설계서가 말했다" 고 적는다(HSIS·SUTS 2템플릿과 같은 결함형).
    #   머리행을 못 만난 표는 옛 순서(2·3)로 읽고 그 사실을 `param_col_layout` 에 남긴다.
    col_name, col_type, col_range = 1, 2, 3
    col_layout = "fixed"
    mode = ""
    for tr in tbl.findall(f"{_W}tr"):
        grid = _row_cells(tr)
        cells = [c[0] for c in grid]
        if not cells:
            continue
        head = cells[0].strip()
        if _SEC_IN.match(head):
            mode = "in"
            continue
        if _SEC_OUT.match(head):
            mode = "out"
            continue
        if _SEC_END.match(head) or head.startswith("["):
            mode = ""
            continue
        # (R65) 번호 칸이 비었는데(위 행과 세로 병합 · 빈 칸 — HDPDM01 10 행은 병합 표시 없이 비어 있었다) 이름 칸이 있는 행 —
        #   번호 칸이 병합 이어짐이거나 Type 칸이 채워졌을 때만 파라미터 행이다(리뷰 R65 I4: `"" | Reserved` 같은 행은 아니다)
        continued = (bool(mode) and head == "" and len(cells) > col_name >= 0 and bool(cells[col_name].strip())
                     and (grid[0][1] or (0 <= col_type < len(cells)
                                         and cells[col_type].strip().lower() not in _NA)))
        # 표 머리행(`No | Name | …`)과 키-값 행(`ID | SwUFn_0101`)은 데이터가 아니다.
        if not re.fullmatch(r"\d+", head) and not continued:
            # 키-값 행의 값은 라벨 칸(그리드 여러 열을 덮을 수 있다) **바로 다음 칸**이다 — 비었으면 빈 값(리뷰 R65 I3: 다음
            #   쌍의 라벨을 값으로 집지 않는다)
            _value = next((c.strip() for c in cells[1:] if c.strip() != head), "")
            if head.upper() == "ASIL" and len(cells) > 1:
                asil = _value
            if head.lower() == "description" and len(cells) > 1 and not mode and not description:
                if _value.lower() not in _NA:
                    description = _value
            if head == "No" and mode:
                _low = [c.strip().lower() for c in cells]
                _cn = next((i for i, c in enumerate(_low) if c == "name"), -1)
                _ct = next((i for i, c in enumerate(_low) if c == "type"), -1)
                _cr = next((i for i, c in enumerate(_low) if c.startswith("value range") or c == "range"), -1)
                if _cn >= 0:
                    col_name = _cn
                # 못 찾은 열은 **읽지 않는다**(-1) — 옛 상수로 다른 열을 범위라 부르지 않는다.
                col_type, col_range = _ct, _cr
                col_layout = "header"
            if head and not head[0].isdigit():
                # `선행조건` · `Called Function` 등을 만나면 파라미터 구간이 끝난 것이다.
                if head not in ("No",):
                    mode = ""
            continue
        if not mode or len(cells) < 2:
            continue
        raw_name = cells[col_name] if len(cells) > col_name else ""
        nm = clean_param_name(raw_name)
        if not nm or not _DESIGNATOR.match(nm):
            if raw_name.strip() and raw_name.strip().lower() not in _NA:
                st.setdefault("rows_unread", []).append({
                    "function": function, "section": mode, "text": " ".join(raw_name.split())[:120],
                    "reason": "name_not_identifier" if not nm else "name_not_a_designator"})
            continue
        st["param_rows"] = st.get("param_rows", 0) + 1
        if continued:
            st["rows_continued"] = st.get("rows_continued", 0) + 1
        (inputs if mode == "in" else outputs).append(nm)
        _ty = cells[col_type].strip() if 0 <= col_type < len(cells) else ""
        _raw = cells[col_range] if 0 <= col_range < len(cells) else ""
        _read = read_value_range(_raw, _ty) if 0 <= col_range < len(cells) else {}
        _rec: Dict[str, Any] = {}
        if _ty and _ty.lower() not in _NA:
            _rec["type"] = _ty
        if "range" in _read:
            _rec["range"] = [_read["range"][0], _read["range"][1]]
            st["range_read"] = st.get("range_read", 0) + 1
        elif "values" in _read:
            _rec["values"] = list(_read["values"])
            st["values_read"] = st.get("values_read", 0) + 1
        elif "unread" in _read:
            _rec["range_unread"] = _read["unread"]
            _by = st.setdefault("range_unread_by_reason", {})
            _by[_read["unread"]] = _by.get(_read["unread"], 0) + 1
            _samples = st.setdefault("range_unread_samples", {}).setdefault(_read["unread"], [])
            if len(_samples) < 5:
                _samples.append(f"{function}.{nm} `{' '.join(str(_raw).split())}`")
        if _read:
            # (R77 N113) 원문도 같이 싣는다 — 상충 공시가 해석된 수만 보이면(`134217727~2147483648`) 문서의 오타
            #   (`0x7FFFFFF~ 0x80000000`, F 가 일곱)인지 파서의 오독인지 읽는 사람이 가를 수 없다.
            _rec["range_text"] = " ".join(str(_raw).split())
            for tag in _read.get("notation") or ():
                _nt = st.setdefault("range_notation", {})
                _nt[tag] = _nt.get(tag, 0) + 1
        if _rec and nm not in param_info:
            param_info[nm] = _rec
    return {"inputs": inputs, "outputs": outputs, "asil": asil, "description": description, "param_info": param_info,
            "param_col_layout": col_layout}


def load_uds_unit_io(uds_path: Any, source_functions: Any = None) -> Dict[str, Any]:
    """`_load_uds_unit_io` + (소스 함수 이름을 주면) 표 `Name` 행 별칭을 `restrict_aliases` 로 확인한 사본 — 별칭은 그때만
    조회된다(리뷰 R65 2차 N2)."""
    result = _load_uds_unit_io(uds_path)
    return restrict_aliases(result, source_functions) if source_functions is not None else result


def _load_uds_unit_io(uds_path: Any) -> Dict[str, Any]:
    """`{"by_name": {함수명: {"inputs": [...], "outputs": [...]}}, "ambiguous": [...], "aliases": {...}, "reading": {...}}`.

    ⚠ 호출부는 **로컬로 materialize 된 경로**를 준다(cloudium 경로는 worker 만 연다).
    파싱 실패는 **빈 맵**이다 — 그 경우 호출부는 소스 파싱 결과를 그대로 쓴다. 지어내지 않는다.
    (R65) 못 읽은 이유는 `reading.read_error` 에 남는다(빈 맵이 "문서가 0 개라고 했다" 로 읽히지 않게).
    `reading` 은 판독 사실이다: 머리말 · 표 · 표시 붙은 머리말 · 삭제 표시 · 표 `Name` 행 별칭 · 파라미터 행 · 세로 병합으로
    이어진 행 · 이름으로 못 읽은 행 · Value Range 판독(범위 · 값 목록 · 사유별 못 읽음과 표본 · 표기).
    """
    empty: Dict[str, Any] = {"by_name": {}, "ambiguous": [], "total": 0, "source": "", "aliases": {}, "reading": {}}
    raw = str(uds_path or "").strip()
    if not raw:
        return empty
    p = Path(raw)
    sig = _signature(p)
    if sig is None:
        return {**empty, "reading": {"read_error": "file_not_found"}}
    key = str(p.resolve()) if p.exists() else raw
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and hit[0] == sig and (now - hit[1]) < _CACHE_TTL_SEC:
        return hit[2]
    if p.suffix.lower() != ".docx":
        _logger.info("uds unit-io: unsupported suffix %s (%s)", p.suffix, p.name)
        return {**empty, "reading": {"read_error": f"unsupported_suffix:{p.suffix.lower()}"}}

    try:
        # ⚠ python-docx 로 통째로 올리지 않는다 — 이 문서는 53MB 다. `word/document.xml`
        #   만 lxml 로 훑는다(이 저장소가 docx 파싱에서 400s→2.6s 로 겪은 축).
        body = read_docx_body(p)
    except Exception as exc:  # noqa: BLE001 — zip/xml/의존성 예외가 모두 여기로 온다
        _logger.warning("uds unit-io: cannot read %s: %s", p.name, exc)
        return {**empty, "reading": {"read_error": read_error_text(exc, p)}}

    by_name: Dict[str, Dict[str, Any]] = {}
    ambiguous: set[str] = set()
    total = 0
    stats: Dict[str, Any] = {}
    headings = 0
    marked: List[str] = []
    deleted: List[str] = []
    unread_headings: List[str] = []
    entries = list(iter_design_entries(body, read_toc_style_ids(p)))
    select_live_headings(entries)
    superseded: List[str] = []
    for e in entries:
        headings += 1
        if e["status"] == "deleted":
            deleted.append(e["text"])
            continue
        if e["status"] == "unread":
            unread_headings.append(e["text"])
            continue
        if e["status"] == "superseded":
            superseded.append(f"{e['text']} → {e['superseded_by']}")
            continue
        if e["status"] == "marked":
            marked.append(e["text"])
        if e["table"] is None:
            continue
        name = e["name"]
        rec = _parse_table(e["table"], name, stats)
        total += 1
        if name in by_name:
            # 같은 이름이 두 번 — 어느 표가 이 함수인지 못 정한다.
            ambiguous.add(name)
        else:
            by_name[name] = rec

    for nm in ambiguous:
        by_name.pop(nm, None)
    # 별칭은 설계 ID 로더와 같은 항목 · 같은 함수로 센다(리뷰 R65 W1)
    aliases, alias_conflicts = name_row_aliases(entries)
    aliases = {a: h for a, h in aliases.items() if h in by_name}

    reading = {
        "headings": headings, "tables": total, "functions": len(by_name), "ambiguous": len(ambiguous),
        "marked_headings": marked, "deleted_headings": deleted, "unread_headings": unread_headings,
        "superseded_headings": superseded,
        # 매핑에 쓰인 머리말 이름(표가 없어도 — 설계 ID 로더는 그 이름을 매핑한다; 리뷰 R65 4차 I1)
        "live_heading_names": sorted({e["name"] for e in entries if e["status"] in ("plain", "marked")}),
        "name_row_aliases": [f"{h} ← 표 Name `{a}`" for a, h in sorted(aliases.items())],
        "alias_conflicts": alias_conflicts,
        **{k: stats.get(k, 0) for k in ("param_rows", "rows_continued", "range_read", "values_read")},
        "rows_unread": stats.get("rows_unread", []),
        "range_unread_by_reason": stats.get("range_unread_by_reason", {}),
        "range_unread_samples": stats.get("range_unread_samples", {}),
        "range_notation": stats.get("range_notation", {}),
    }
    result: Dict[str, Any] = {
        "by_name": by_name,
        "ambiguous": sorted(ambiguous),
        "total": total,
        "source": p.name,
        "aliases": aliases,
        "reading": reading,
    }
    _CACHE[key] = (sig, now, result)
    _logger.info(
        "uds unit-io: %s → %d 함수 (표 %d · 동명이인 %d 제외 · 표시 머리말 %d · 표 Name 별칭 %d) | 입력 %d · 기대 %d "
        "| 파라미터 행 %d(이어진 행 %d) · 못 읽은 행 %d · 범위 %d · 값 목록 %d · 못 읽은 범위 %d",
        p.name, len(by_name), total, len(ambiguous), len(marked), len(aliases),
        sum(len(v["inputs"]) for v in by_name.values()),
        sum(len(v["outputs"]) for v in by_name.values()),
        reading["param_rows"], reading["rows_continued"], len(reading["rows_unread"]), reading["range_read"],
        reading["values_read"], sum(reading["range_unread_by_reason"].values()),
    )
    return result


def resolve_unit_io(io_map: Optional[Dict[str, Any]], fn_name: Any) -> Optional[Dict[str, List[str]]]:
    """함수명 → `{"inputs": [...], "outputs": [...]}`. 못 찾으면 **None**.

    None 은 "UDS 에 근거가 없다" 이고, 호출부는 그때 소스 파싱 결과를 유지해야 한다.
    빈 dict 로 바꾸면 "UDS 가 0개라고 적었다" 와 구분이 사라진다.
    머리말 이름 → 대소문자만 다른 머리말 이름 → 표 `Name` 행 별칭(R65 — `restrict_aliases` 를 거친 맵에서만) 순서다.
    """
    if not io_map:
        return None
    by_name = io_map.get("by_name") or {}
    name = str(fn_name or "").strip()
    if not name:
        return None
    got = by_name.get(name)
    if got is not None:
        return got
    lowered = name.lower()
    for k, v in by_name.items():
        if k.lower() == lowered:
            return v
    aliases = checked_aliases(io_map)
    head = aliases.get(name) or next((h for a, h in aliases.items() if a.lower() == lowered), None)
    if head is not None and head in by_name:
        return by_name[head]
    return None
