"""(R90) SUTS 기대값 ↔ 설계 대조 — 소스로 계산한 기대값이 **설계가 그 출력에 적은 값 범위** 안에 있나.

## 왜

SUTS 의 확정 기대값은 C 소스를 실행해 얻는다(`generators.c_source_oracle` · 근거는 `Test Evidence`). 그래서 기대값은
늘 코드와 같다 — 코드가 설계와 어긋나도 기대값은 코드를 따라가고, 그 어긋남은 어디에도 드러나지 않는다(변이 시험이
보는 것은 "시험이 코드의 변화를 잡나" 지 "코드가 설계대로인가" 가 아니다). 이 대조는 그 빈자리를 **정보로** 채운다:
기대값과 행은 그대로 두고(행은 라운드를 넘어 안정해야 한다), 칸마다 설계가 무엇을 말했고 그 값이 거기 드는지 적는다.

## 무엇과 대조하나 (실측 2026-10-16 — 설계서가 출력마다 적는 것)

- **SwUDS 출력 표의 `Value Range`**(`[ Output Parameters ]`, `generators.uds_unit_io` 가 출력 행만 `out_info` 로 따로
  싣는다): HDPDM01 v1.07 출력 행 1,568 중 범위 1,460 · 값 목록 8(선언 타입 전폭보다 좁은 것 669),
  KJPDS02_PV v3.03 출력 행 2,799 중 범위 2,559 · 값 목록 6(좁은 것 1,218). 가장 많고 함수에 묶인 진술이다.
  반환값: 설계서가 `Return` 행을 적었으면 그것, 없고 본문의 모든 `return` 이 같은 변수 하나를 돌려주면 그 변수의 출력 행
  (HDPDM01 은 `Return` 행이 6 함수뿐이고 63 함수가 돌려주는 지역 변수 `u8t_Result` 로 적는다 — 본문이 증명할 때만 읽는다).
- **HSIS SW 값 범위**(`unit["hsis_bounds"]`) — SwUDS 출력 표가 그 출력의 값 범위를 주지 않을 때만(설계서가 더 구체적이다):
  출력 행이 없음 · 함수 표가 없음 · 같은 이름의 표가 둘 · 지정한 SwUDS 를 못 읽음 · SwUDS 를 주지 않음 · 행에 범위가 없음 ·
  행의 범위 칸을 못 읽음. 마지막 경우(설계서가 무엇을 적었는데 못 읽었다)는 HSIS 범위 밖이어도 단정하지 않는다
  (`outside_design:design_cell_unread`). 포인터 행의 주소 범위는 HSIS 로 넘기지 않는다(`pointer_row_address`).
- 쓰지 않는 것(지어내지 않는다):
  - 출력 행 `Description` 의 `0x00: WDI Low` 같은 값 설명(HDPDM01 528 · PV 541 행) — 값의 **뜻풀이**이지 값 집합의 전부가
    아니다(`0x01: CLOSE 0x02: OPEN` 행의 범위는 `0x00 ~ 0x04`). 거기 없는 값을 '설계 밖' 이라 하면 거짓 경보다.
  - `Reset Value` — 초기값이지 함수가 낸 값의 제약이 아니다.
  - SRS 정량 사실(`generators.requirement_oracle`) — 문장의 주어가 신호 · 임계 조건(자극)이고, 단위 함수 출력 칸 하나에
    묶이는 근거가 문장에 없다.

## 판정 (`Design Check` 열 · 품질 보고서 `design_check`)

확정값(`derived`)이고 함수가 쓴 값(`basis` 가 `unchanged_input` 이 아님)인 칸만 대조한다:

- `consistent` — 설계 범위 안(값 목록이면 그 값 중 하나).
- `consistent:type_full_width` — 안이지만 설계 범위가 값의 타입 전폭(소스 타입, 모르면 설계 행의 타입)이다: **어긋날 수
  없던 대조**라 '범위 안' 에 넣지 않는다(리뷰 W2 — HDPDM01 리뷰 덤프 2,086 칸; 원문이 있으면 반환 변수 별칭 `u8t_Result` 로
  읽히는 칸이 더해진다). 포인터 행(`U32 *`)의 `0 ~ 0xFFFFFFFF` 처럼
  주소 범위일 수도 있는 칸도 여기로 온다(리뷰 I8).
- `conflicting_design` — 같은 출력을 설계 행 둘이 다르게 적었고 값이 한 행 안 · 다른 행 밖이다(고르지 않는다).
- `outside_design` — 밖이고, 그 행이 넣은 입력이 **모두** 설계서가 적은 범위 · 값 목록(stub 한 피호출 반환값은 그 함수의 설계
  Return) 안이며, 기대값이 stub 값에 기대지 않고, 설계와 소스의 부호 표기가 어긋나지 않으며, 그 이름의 정의가 하나이고(같은
  이름이 여럿이면 표가 어느 빌드의 것인지 모른다), HSIS 로 대조했다면 SwUDS 행이 못 읽은 범위를 적지 않았다: **코드와 설계가
  어긋난 후보**다. 설계 오류인지 코드 오류인지는 이 대조가 정하지 않는다. 공시의 머리 수는 이것만 센다.
- `outside_design:undesigned_input` — 밖이지만 설계 진술 없이 넣은 입력이 있다(설계서 입력 표에 범위가 없어 타입 폭만 ·
  타입도 모름 · 수가 아닌 값 · 설계 Return 이 없는(또는 같은 빌드를 못 정한) 피호출의 stub 값 · 설계 범위와 소스 타입의 부호
  표기가 달라 대조하지 못한 입력). 설계가 그 입력을 말하면 판정이 갈릴 수 있다. 입력도 출력과 같이 같은 폭 · 부호만 다른 설계
  타입이면 비트 패턴으로 대조한다(HDPDM01 `s16g_…Gain=-1` 은 설계 U16 `0~65535` 안이다).
- `outside_design:stub_value` — 밖이지만 기대값이 stub 한 피호출 함수의 반환값(시험이 정한 값)에 기댄다.
- `outside_design:type_differs` — 밖이지만 설계 범위가 소스 타입과 부호 표기가 다르다(부호 없는 변수에 음수 범위 · 부호 있는
  변수의 음수 값에 부호 없는 범위) — 표기 차이일 수 있다. 같은 폭 · 부호만 다른 두 타입(설계 `S16` · 소스 `uint16_t`)은
  비트 패턴으로 대조한다(리뷰 W3).
- `outside_design:ambiguous_value_list` — 설계가 값 둘 목록(`0x00, 0xFF` — '값 둘' 인지 쉼표로 쓴 범위인지 문서가 말하지
  않는다)이고 값이 두 값 **사이**다: 값 둘로 읽으면 밖, 범위로 읽으면 안이라 단정하지 않는다. 두 값과 같으면 `consistent`,
  두 값 밖(테두리 밖)이면 어느 읽기로도 밖이라 위 판정으로 간다. 입력 쪽 값 둘 목록도 같은 규칙(사이면 '진술 없음').
- `outside_design:twin_definition` — 밖이지만 같은 이름의 정의가 여럿(APP · BOOT `EEPROM_Init`)이고 진술은 이름으로 찾은
  SwUDS 표 하나다 — 그 표가 이 빌드의 설계라는 근거가 문서에 없어 단정하지 않는다(2차 W-A).
- `outside_design:design_cell_unread` — 밖이지만 그 진술은 HSIS 범위이고, SwUDS 행은 범위 칸에 무엇을 적었는데 읽지
  못했다(`0x05` 값 하나 등) — 설계서가 다른 말을 했을 수 있어 단정하지 않는다(2차 I-2).
- `outside_design_on_out_of_design_input` — 밖이지만 그 행이 설계 밖 입력을 넣었다(강건성 · 오류 경로 행). 결함 주장이 아니다.
- `no_design_statement:<사유>` — 설계가 이 출력의 값을 말하지 않았다(사유와 함께 — 빈칸으로 숨기지 않는다).
- `not_checked:<사유>` — 대조할 값이 아니다(확정값이 아님 · 함수가 쓰지 않은 값 · 정수가 아님).

`Design Basis` 열은 근거다: 문서(지정한 원래 파일 이름) · 표(머리말 이름 · `Output Parameters` · 행 번호) · 칸 원문 · 읽은
범위, 같은 출력을 두 행이 다르게 적었으면 그 행들, 같은 이름의 정의가 여럿(APP · BOOT)이면 그 사실, 밖으로 나간 입력, 설계
진술 없이 넣은 입력, stub 한 피호출 함수.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from generators.uds_unit_io import _INT_CANON, _full_range, _statement_signature, document_int_type, uds_param_key

_logger = logging.getLogger(__name__)

CONSISTENT = "consistent"
CONSISTENT_FULL_WIDTH = "consistent:type_full_width"
CONFLICTING = "conflicting_design"
OUTSIDE = "outside_design"
OUTSIDE_UNDESIGNED_INPUT = "outside_design:undesigned_input"
OUTSIDE_STUB_VALUE = "outside_design:stub_value"
OUTSIDE_TYPE_DIFFERS = "outside_design:type_differs"
OUTSIDE_AMBIGUOUS_VALUES = "outside_design:ambiguous_value_list"
OUTSIDE_TWIN = "outside_design:twin_definition"
OUTSIDE_CELL_UNREAD = "outside_design:design_cell_unread"
OUTSIDE_ON_INPUT = "outside_design_on_out_of_design_input"
NO_STATEMENT = "no_design_statement"
NOT_CHECKED = "not_checked"

#: 밖이지만 어긋남을 단정하지 않는 판정 — 공시 머리 수에 넣지 않는다(리뷰 W1 · 2차 W-A · I-2)
WEAK_OUTSIDE = (OUTSIDE_UNDESIGNED_INPUT, OUTSIDE_STUB_VALUE, OUTSIDE_TYPE_DIFFERS, OUTSIDE_AMBIGUOUS_VALUES,
                OUTSIDE_TWIN, OUTSIDE_CELL_UNREAD)

#: 공시 · 품질 보고서에 싣는 표본 수 — 전량은 시트에 있다.
SAMPLE_N = 20
#: 근거 칸에 이름을 몇 개까지 적나 — 넘으면 "외 N"(잘린 사실을 숨기지 않는다).
_LIST_N = 4

_IDX = re.compile(r"\[[^\]]*\]")
_STUB_RETURN = re.compile(r"^([A-Za-z_]\w*)\(\) return$")

#: 설계 진술 없이 넣은 입력 — 근거 칸 글
_UNDESIGNED_TEXT = {
    "type_width": "설계 범위 없음 · 선언 타입 폭 안",
    "type_unknown": "설계 범위 없음 · 타입도 모름",
    "not_numeric": "수가 아닌 값 — 대조 안 함",
    "stub_callee_undesigned": "피호출 함수의 설계 Return 없음",
    "stub_callee_ambiguous": "같은 이름의 피호출 정의 여럿 — 같은 빌드를 못 정함",
    "type_differs": "설계 범위와 소스 타입의 부호 표기가 다름 — 대조 안 함",
    "ambiguous_value_list": "설계 값 둘 사이 — 값 둘인지 쉼표로 쓴 범위인지 설계서가 말하지 않음",
}


def check_bucket(check: str) -> str:
    """품질 보고서 `by_check` 의 칸 — 대조하지 않은 칸은 갈래(`no_design_statement` · `not_checked`, 사유는
    `not_compared_by_reason`), 대조한 칸은 판정 그대로. 시트의 `Design Check` 열을 같은 함수로 묶으면 보고서와 같다."""
    head = check.split(":", 1)[0]
    return head if head in (NO_STATEMENT, NOT_CHECKED) else check


def _cut(items: List[str], n: int = _LIST_N) -> str:
    return ", ".join(items[:n]) + (f" 외 {len(items) - n}" if len(items) > n else "")


def uds_output_rows(uds_rec: Optional[Dict[str, Any]], io_map: Optional[Dict[str, Any]],
                    doc_name: Optional[str] = None, function: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """unit 에 싣는 SwUDS 출력 표 — `{"doc", "heading", "rows"}`.

    Args:
        uds_rec: `resolve_unit_io` 가 찾은 이 함수의 표(없으면 None).
        io_map: `load_uds_unit_io` 결과. 캐시된 맵이다 — 바꾸지 않는다.
        doc_name: 지정한 SwUDS 의 **원래 파일 이름**(리뷰 C1 — 파일 접근기 경유면 `io_map["source"]` 는 실행마다 다른 임시
            사본 이름이다). 주면 "SwUDS 를 지정했다" 는 뜻이기도 하다.
        function: 함수 이름 — 같은 이름의 표가 둘이라 빠진 함수(`io_map["ambiguous"]`)를 사유로 가른다.

    Returns:
        SwUDS 를 지정하지 않았고 맵도 없으면 None. 지정했는데 표를 하나도 못 읽었으면 `rows` None ·
        `document_unread`. 읽었는데 이 함수의 표가 없으면 `rows` None(같은 이름의 표가 둘이면 `ambiguous`).
    """
    doc = str(doc_name or (io_map or {}).get("source") or "SwUDS")
    if not io_map or not (io_map.get("by_name") or io_map.get("total")):
        # 지정했는데 출력 표를 하나도 못 읽었다 — '문서 없음' 과 다르다(리뷰 W5: 대조 0 칸이 "밖 없음" 으로 읽혔다)
        return {"doc": doc, "heading": None, "rows": None, "document_unread": True} if doc_name else None
    if uds_rec is None:
        fn = str(function or "")
        amb = {str(x).lower() for x in (io_map.get("ambiguous") or ())}
        return {"doc": doc, "heading": None, "rows": None, **({"ambiguous": True} if fn and fn.lower() in amb else {})}
    return {"doc": doc, "heading": str(uds_rec.get("heading") or ""), "rows": dict(uds_rec.get("out_info") or {})}


def _doc_width(type_text: Any) -> Optional[Tuple[bool, int]]:
    """설계 행 Type 칸의 정수 폭 — 포인터 행(`U16 *`)은 가리키는 타입."""
    return document_int_type(str(type_text or "").replace("*", " "))


def _pointee_fits(rec: Dict[str, Any]) -> bool:
    """포인터 행(`U16 *`)의 범위 · 값 목록이 가리키는 타입 폭 안인가 — 그래야 가리키는 값의 범위다. 가리키는 타입의 폭을
    문서가 말하지 않았으면(typedef · 구조체) 모른다 — 대조하지 않는다."""
    full = _full_range(_doc_width(rec.get("type")))
    vals = list(rec.get("range") or ()) + list(rec.get("values") or ())
    return bool(full and vals and full[0] <= min(int(x) for x in vals) and max(int(x) for x in vals) <= full[1])


def _row_reading(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """설계 행 하나가 값에 대해 말한 것 — `{"kind": "range", "range"}` · `{"kind": "values", "values"}` · None(말하지 않음 ·
    포인터 행의 주소 범위)."""
    if "*" in str(rec.get("type") or "") and not _pointee_fits(rec):
        return None
    if rec.get("range"):
        return {"kind": "range", "range": (int(rec["range"][0]), int(rec["range"][1]))}
    if rec.get("values"):
        got: Dict[str, Any] = {"kind": "values", "values": sorted(int(x) for x in rec["values"])}
        if rec.get("two_value_list"):
            got["two_value_list"] = True
        return got
    return None


def _inside(reading: Dict[str, Any], v: Any) -> bool:
    if reading["kind"] == "range":
        return reading["range"][0] <= v <= reading["range"][1]
    return v in reading["values"]


def _between_two_values(reading: Dict[str, Any], v: Any) -> bool:
    """값 둘 목록(`0x00, 0xFF` — 값 둘인지 쉼표로 쓴 범위인지 설계서가 말하지 않는다)의 두 값 **사이**인가. 그 값은 값 둘로
    읽으면 밖 · 범위로 읽으면 안이라 단정하지 않는다. 두 값과 같으면 어느 읽기로도 안, 두 값 밖(테두리 밖)이면 어느 읽기로도
    밖이다."""
    vals = reading.get("values") or ()
    return bool(reading.get("kind") == "values" and reading.get("two_value_list") and len(vals) == 2
                and vals[0] < v < vals[1])


def _reading_text(reading: Dict[str, Any]) -> str:
    if reading["kind"] == "range":
        return f"{reading['range'][0]}~{reading['range'][1]}"
    return "값 " + ",".join(str(x) for x in reading["values"])


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_number(value: Any) -> Optional[float]:
    """입력 값 — 정수 · 실수(설계 범위와 크기로 견준다). 수가 아니면 None."""
    got = _as_int(value)
    if got is not None:
        return got
    return value if isinstance(value, float) else None


def _reinterpret(v: int, width: Tuple[bool, int]) -> int:
    """같은 폭의 비트 패턴을 `width` 의 부호로 읽은 값(`65531` U16 → S16 `-5`)."""
    signed, bits = width
    u = v & ((1 << bits) - 1)
    return u - (1 << bits) if signed and u >= 1 << (bits - 1) else u


def _source_type(unit: Dict[str, Any], name: str) -> str:
    types = unit.get("var_types") or {}
    return str(types.get(name) or types.get(_IDX.sub("", name)) or "")


def _value_domain(design_type: Any, src_type: str, readings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """값이 놓이는 타입 — 설계 행의 타입(`design_type`, 표가 아니면 None)과 소스 타입이 같은 폭 · 부호만 다르면 비트 패턴으로
    읽고(리뷰 W3 — HDPDM01 `s16g_…Gain=-1` 이 설계 U16 `0~65535` 밖 입력으로 보였다), 설계 범위가 값의 타입 전폭이면 어긋날 수
    없는 대조다(리뷰 W2). 값의 정의역: 비트 패턴으로 읽으면 설계 타입, 아니면 소스 타입, 모르면 설계 행의 타입."""
    from generators.suts import _TYPE_BOUNDARIES

    tb = _TYPE_BOUNDARIES.get(src_type) if src_type != "float" else None
    # 소스 타입 이름이 표 밖의 철자(`sint16_t`)여도 폭이 정해진 정수면 읽는다(같은 판독기 — `document_int_type`)
    src_w = _INT_CANON.get(src_type) or (document_int_type(src_type) if src_type else None)
    src_full = (int(tb["min"]), int(tb["max"])) if tb else _full_range(src_w)
    doc_w = _doc_width(design_type) if design_type is not None else None
    reinterpret = bool(doc_w and src_w and doc_w[1] == src_w[1] and doc_w[0] != src_w[0])
    domain = _full_range(doc_w) if reinterpret else (src_full or _full_range(doc_w))
    full_width = bool(domain) and all(r["kind"] == "range" and r["range"][0] <= domain[0] and domain[1] <= r["range"][1]
                                      for r in readings)
    lo = min((r["range"][0] if r["kind"] == "range" else r["values"][0]) for r in readings)
    hi = max((r["range"][1] if r["kind"] == "range" else r["values"][-1]) for r in readings)
    return {"doc_w": doc_w, "src_type": src_type, "src_full": src_full, "reinterpret": reinterpret,
            "full_width": full_width, "span": (lo, hi)}


def _in_design_terms(dom: Dict[str, Any], value: Any) -> Any:
    """값을 설계 타입의 표기로 — 같은 폭 · 부호만 다르면 비트 패턴(`65531` → S16 `-5`), 아니면 그대로."""
    return _reinterpret(value, dom["doc_w"]) if dom.get("reinterpret") and isinstance(value, int) else value


def _sign_notation_differs(dom: Dict[str, Any], value: Any) -> bool:
    """설계 범위와 소스 타입의 부호 표기가 다른가 — 부호 없는 변수에 음수 범위, 부호 있는 변수의 음수 값에 그 타입 최댓값을 넘는
    (부호 없는 표기의) 범위. 비트 패턴으로 이미 읽었으면 아니다."""
    src = dom.get("src_full")
    if dom.get("reinterpret") or not src:
        return False
    lo, hi = dom["span"]
    if src[0] >= 0:
        return lo < 0
    return hi > src[1] and value < 0


def _path_parts(p: Any) -> List[str]:
    return [x for x in str(p or "").replace("\\", "/").split("/") if x]


def _shared_prefix(a: List[str], b: List[str]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):     # 길이가 다른 두 경로의 앞부분 — 짧은 쪽에서 멈춘다
        if x.lower() != y.lower():
            break
        n += 1
    return n


class DesignChecker:
    """unit 들의 설계 진술 색인 — 쓰는 곳(시트 · 품질 보고서)마다 하나 만든다. 행을 바꾸지 않는다.

    `units` 는 그 문서의 unit 전부다(같은 이름의 정의 · stub 한 피호출 함수의 설계 Return 을 찾는다) — 시트와 보고서가 같은
    목록으로 만들어야 판정이 같다."""

    def __init__(self, units: Optional[List[Dict[str, Any]]] = None) -> None:
        self._index: Dict[int, Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Tuple[str, Dict[str, Any]]]]]] = {}
        # 이름 → 그 이름의 unit 전부(APP · BOOT 처럼 같은 이름의 정의가 여럿일 수 있다 — 첫 것을 고르지 않는다, 리뷰 I6)
        self._by_name: Dict[str, List[Dict[str, Any]]] = {}
        for u in units or ():
            self._by_name.setdefault(str(u.get("name") or ""), []).append(u)
        # 원문 → {함수 이름: 모든 return 이 돌려주는 식별자("" = 증명 못 함)} · None = 원문을 읽지 못함. 파일당 한 번 파싱(리뷰 I7)
        self._alias_by_text: Dict[str, Optional[Dict[str, str]]] = {}
        self._stmt: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self._memo: Dict[Tuple[int, str], Tuple[Dict[str, Any], str, Dict[str, Any]]] = {}
        # 위 색인은 `id(unit)` 로 찾는다 — 본 unit 을 붙잡아 둔다(놓아 준 dict 의 id 를 새 dict 가 물려받으면 다른 unit 의
        #   진술 · 근거를 돌려준다)
        self._seen: Dict[int, Dict[str, Any]] = {}

    def _pin(self, unit: Dict[str, Any]) -> int:
        self._seen[id(unit)] = unit
        return id(unit)

    # ── 설계 행 찾기 ─────────────────────────────────────────────────────────
    def _rows_index(self, unit: Dict[str, Any]):
        got = self._index.get(id(unit))
        if got is None:
            exact: Dict[str, Dict[str, Any]] = {}
            by_key: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
            for name, rec in ((unit.get("uds_output_rows") or {}).get("rows") or {}).items():
                if isinstance(rec, dict):
                    exact[str(name)] = rec
                    by_key.setdefault(uds_param_key(str(name)), []).append((str(name), rec))
            got = self._index[self._pin(unit)] = (exact, by_key)
        return got

    def _find_row(self, unit: Dict[str, Any], var: str):
        """`var` 의 설계 행 — `(이름, 행, 같은 열쇠의 다른 진술 [(이름, 행)])`. 이름이 그대로 있으면 그 행(`x[1]`), 없으면 같은 열쇠
        (`p->m` = `p[0].m`)의 행들 — 그 행들이 다른 말을 하면 첫 행을 고르지 않고 함께 돌려준다(리뷰 I1)."""
        exact, by_key = self._rows_index(unit)
        if var in exact:
            return var, exact[var], []
        group = by_key.get(uds_param_key(str(var or ""))) or []
        if not group:
            return None
        first = group[0]
        sig = _statement_signature(first[1])
        return first[0], first[1], [g for g in group[1:] if _statement_signature(g[1]) != sig]

    def _alias_table(self, text: str) -> Optional[Dict[str, str]]:
        """원문 하나의 함수마다 '모든 `return` 이 돌려주는 식별자' — 파일당 한 번 파싱한다(리뷰 I7: unit 마다 파일 전체를 다시
        파싱해 KJPDS02_PV 16.9 s). 못 읽으면 None."""
        if text in self._alias_by_text:
            return self._alias_by_text[text]
        table: Optional[Dict[str, str]] = None
        try:
            from generators.c_project_context import shared_parser
            from generators.mcdc_design import _function_name

            parser = shared_parser()
            if parser is not None:
                raw = text.encode("utf-8")
                root = parser.parse(raw).root_node
                defs: Dict[str, List[Any]] = {}
                stack = [root]
                while stack:
                    n = stack.pop()
                    if n.type == "function_definition":
                        defs.setdefault(_function_name(n, raw)[0], []).append(n)
                        continue
                    stack.extend(n.named_children)
                # 같은 이름의 정의가 둘이면(`#if` 갈래) 어느 본문인지 모른다 — 증명 못 함("")
                table = {name: (_single_returned_identifier(nodes[0], raw) if len(nodes) == 1 else "")
                         for name, nodes in defs.items() if name}
        except Exception as exc:  # noqa: BLE001 — 별칭은 정보다: 못 읽으면 사유(`return_alias_unreadable`)가 칸에 남는다
            _logger.debug("design check: return alias parse failed: %s", exc)
            table = None
        self._alias_by_text[text] = table
        return table

    def _return_alias(self, unit: Dict[str, Any]) -> Tuple[str, str]:
        """본문의 모든 `return` 이 같은 식별자 하나(`return u8t_Result;` · `return (x);`)를 돌려주면 `(그 이름, "")`, 아니면
        `("", 사유)` — 원문이 없거나 온전하지 않거나 파싱하지 못했으면 `return_alias_unreadable`(리뷰 I3: 예전엔 '출력 표에
        없음' 으로 보였다), 본문이 증명하지 못하면 `not_in_design_outputs`. 지어내지 않는다."""
        text = str(unit.get("source_text") or "")
        name = str(unit.get("name") or "")
        if not text or not name or not unit.get("source_text_complete", True):
            return "", "return_alias_unreadable"
        table = self._alias_table(text)
        if table is None or name not in table:
            return "", "return_alias_unreadable"
        return (table[name], "") if table[name] else ("", "not_in_design_outputs")

    # ── 설계 진술 ────────────────────────────────────────────────────────────
    def statement(self, unit: Dict[str, Any], var: str) -> Dict[str, Any]:
        """출력 `var` 에 대해 설계가 적은 것 — `{"status": "stated", "source", "kind", "range"|"values", "text", "where", ...,
        ["conflicting"]}` 또는 `{"status": "none", "reason", ["text", "where"]}`."""
        key = (id(unit), var)
        got = self._stmt.get(key)
        if got is None:
            got = self._stmt[(self._pin(unit), var)] = self._statement(unit, var)
        return got

    def _statement(self, unit: Dict[str, Any], var: str) -> Dict[str, Any]:
        block = unit.get("uds_output_rows")
        reason = "no_design_document"
        alias = ""
        found = None
        if isinstance(block, dict):
            if block.get("rows") is None:
                reason = ("design_document_unread" if block.get("document_unread")
                          else "ambiguous_design_table" if block.get("ambiguous") else "no_design_table")
            else:
                found = self._find_row(unit, var)
                reason = "not_in_design_outputs"
                if found is None and uds_param_key(str(var or "")) == "return":
                    # 설계서가 반환값을 `Return` 이 아니라 돌려주는 변수(`u8t_Result`)로 적은 표 — 본문의 모든 `return` 이 그
                    #   변수 하나를 돌려줄 때만 그 행을 반환값의 설계로 읽는다(HDPDM01 출력 표 63 함수가 이 꼴)
                    alias, why = self._return_alias(unit)
                    found = self._find_row(unit, alias) if alias else None
                    if not alias:
                        reason = why
        if found is not None:
            dname, rec, others = found
            where = f"{block.get('doc')} · {block.get('heading') or unit.get('name', '')} [Output Parameters] " \
                    f"No {rec.get('no') or '(병합)'} `{dname}`"
            if alias:
                where += f" (본문의 모든 return 이 `{alias}` 를 돌려준다)"
            text = str(rec.get("range_text") or "")
            base: Dict[str, Any] = {"where": where, "text": text, "design_name": dname, "type": str(rec.get("type") or "")}
            alts = [(dname, r) for r in rec.get("conflicting_rows") or () if isinstance(r, dict)] + list(others)
            if alts:
                base["conflicting"] = [{"name": n, "no": str(r.get("no") or ""), "text": str(r.get("range_text") or ""),
                                        "reading": _row_reading(r)} for n, r in alts]
            if rec.get("two_value_list"):
                base["two_value_list"] = True
            reading = _row_reading(rec)
            if reading is not None:
                return {"status": "stated", "source": "SwUDS", **reading, **base}
            if "*" in base["type"] and (rec.get("range") or rec.get("values")):
                # 포인터 행의 범위가 가리키는 타입에 안 들어가면 주소 범위다(`0 ~ 0xFFFFFFFF` — R76 N98 과 같은 판단)
                return {"status": "none", "reason": "pointer_row_address", **base}
            # 행이 범위를 말하지 않았거나 못 읽은 칸 — 다음 출처(HSIS)로, 없으면 사유와 원문(경계값 출처 순서 `_bounds_of` 와 같다).
            #   못 읽은 칸(`range_unread`) 위의 HSIS 대조는 밖이어도 단정하지 않는다(`classify` — 2차 I-2)
            reason = (f"range_unread:{rec['range_unread']}" if rec.get("range_unread")
                      else "design_table_without_range_column" if rec.get("range_column_missing")
                      else "design_row_without_range")
            hs = self._hsis(unit, var)
            if hs:
                return {**hs, "uds_row": where, "uds_row_text": text, "uds_row_reason": reason}
            return {"status": "none", "reason": reason, **base}
        # SwUDS 가 이 출력의 행을 주지 않았다(출력 행 없음 · 함수 표 없음 · 같은 이름의 표 둘 · 지정한 문서를 못 읽음 · SwUDS 를
        #   주지 않음) — HSIS 가 이 변수의 범위를 적었으면 그것으로
        hs = self._hsis(unit, var)
        if hs:
            return hs
        return {"status": "none", "reason": reason}

    @staticmethod
    def _hsis(unit: Dict[str, Any], var: str) -> Optional[Dict[str, Any]]:
        bounds = unit.get("hsis_bounds") or {}
        for name in (var, _IDX.sub("", var)):
            rng = bounds.get(name)
            if rng:
                text = str((unit.get("hsis_range_text") or {}).get(name) or "")
                return {"status": "stated", "source": "HSIS", "kind": "range", "range": (int(rng[0]), int(rng[1])),
                        # 근거 글은 `HSIS · `name` SW Value Range `원문` → lo~hi`(`_basis_text` 가 출처 · `Value Range` 를 붙인다)
                        "text": text, "where": f"· `{name}` SW", "design_name": name, "type": ""}
        return None

    # ── 값의 타입 ────────────────────────────────────────────────────────────
    @staticmethod
    def _domain(unit: Dict[str, Any], var: str, st: Dict[str, Any]) -> Dict[str, Any]:
        """출력 `var` 의 값이 놓이는 타입(`_value_domain`)."""
        if st.get("status") != "stated":
            return {}
        readings = [st] + [a["reading"] for a in st.get("conflicting") or () if a.get("reading")]
        return _value_domain(st.get("type") if st.get("source") == "SwUDS" else None, _source_type(unit, var), readings)

    @staticmethod
    def _type_differs(dom: Dict[str, Any], value: Any) -> bool:
        return _sign_notation_differs(dom, value)

    # ── 입력 ─────────────────────────────────────────────────────────────────
    def _callee(self, unit: Dict[str, Any], name: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """stub 한 피호출 함수의 unit — 이름이 하나면 그것, 여럿(APP · BOOT)이면 이 unit 과 **같은 빌드**(소스 경로가 가장 길게
        겹치는 것 하나)만. 겹침이 같은 후보가 둘 이상이면 고르지 않는다(리뷰 I6 — 예전엔 unit 순서로 첫 것)."""
        cands = self._by_name.get(name) or []
        if not cands:
            return None, "unknown"
        if len(cands) == 1:
            return cands[0], ""
        me = _path_parts(unit.get("source_path"))
        scored = [(_shared_prefix(me, _path_parts(c.get("source_path"))), c) for c in cands]
        best = max(s for s, _c in scored)
        tops = [c for s, c in scored if s == best]
        if best == 0 or len(tops) != 1:
            return None, "ambiguous"
        return tops[0], ""

    def _inputs(self, unit: Dict[str, Any], inputs: Dict[str, Any]) -> Tuple[List[str], List[Tuple[str, str]]]:
        """행이 넣은 입력 → `(설계 밖 입력 글, 설계 진술 없이 넣은 입력 [(이름, 사유)])`.

        설계 진술: 설계서 입력 표의 범위 · 값 목록(포인터 행은 가리키는 값의 범위일 때만 — 가리키는 타입 전폭이면 주소 범위와
        가를 수 없어 진술로 보지 않는다), stub 한 피호출 반환값(`F() return`)은 같은 빌드의 F 의 설계 Return. 진술이 없으면 선언
        타입 폭 밖인지만 보고 그 입력은 '진술 없음' 으로 적는다(리뷰 I5 — 타입을 모르면 그렇게 적는다). 수가 아닌 값도
        '진술 없음'(대조하지 않았다)."""
        from generators.suts import _TYPE_BOUNDARIES

        info = unit.get("uds_param_info") or {}
        types = unit.get("var_types") or {}
        out: List[str] = []
        undesigned: List[Tuple[str, str]] = []
        for name, raw in (inputs or {}).items():
            v = _as_number(raw)
            if v is None:
                undesigned.append((name, "not_numeric"))
                continue
            stub = _STUB_RETURN.match(str(name))
            how = ""
            # 설계 진술(읽음)과 그 진술이 적힌 타입 · 무엇의 진술인지(글)
            reading: Optional[Dict[str, Any]] = None
            design_type: Any = None
            what = "설계"
            if stub:
                callee, why = self._callee(unit, stub.group(1))
                cs = self.statement(callee, "return") if callee is not None else {}
                if cs.get("status") == "stated":
                    # stub 값이 피호출 함수의 설계 Return 밖이면 그 행은 설계 밖 입력에 기댄다(그 함수가 낼 수 없는 값)
                    reading, what = cs, f"{stub.group(1)} 설계 Return"
                    design_type = cs.get("type") if cs.get("source") == "SwUDS" else None
                else:
                    how = "stub_callee_ambiguous" if why == "ambiguous" else "stub_callee_undesigned"
            else:
                rec = info.get(name) or info.get(_IDX.sub("", name)) or {}
                reading = _row_reading(rec) if isinstance(rec, dict) else None
                if reading is not None and "*" in str(rec.get("type") or ""):
                    full = _full_range(_doc_width(rec.get("type")))
                    if reading["kind"] == "range" and full and reading["range"][0] <= full[0] and full[1] <= reading["range"][1]:
                        reading = None      # `U32 *` 의 `0 ~ 0xFFFFFFFF` — 주소 범위와 가를 수 없다(리뷰 I8)
                design_type = rec.get("type", "") if isinstance(rec, dict) else None
            if reading is not None:
                # 같은 폭 · 부호만 다른 설계 타입이면 비트 패턴으로(리뷰 W3 — HDPDM01 `s16g_…Gain=-1` vs 설계 U16 `0~65535`)
                dom = _value_domain(design_type, _source_type(unit, name), [reading])
                dv = _in_design_terms(dom, v)
                if not _inside(reading, dv):
                    if _between_two_values(reading, dv):
                        # 값 둘 목록의 두 값 사이 — 그 입력이 설계 밖인지 설계서가 정하지 않았다(값 둘 · 범위 두 읽기가 갈린다)
                        undesigned.append((name, "ambiguous_value_list"))
                    elif _sign_notation_differs(dom, v):
                        undesigned.append((name, "type_differs"))
                    else:
                        out.append(f"{name}={v} ({what} {_reading_text(reading)})"
                                   + (f" — 비트 패턴 {dv}" if dv != v else ""))
                continue
            t = str(types.get(name) or "")
            tb = _TYPE_BOUNDARIES.get(t) if t != "float" else None
            if tb and not tb["min"] <= v <= tb["max"]:
                out.append(f"{name}={v} (타입 {t} {tb['min']}~{tb['max']})")
            else:
                undesigned.append((name, how or ("type_width" if tb else "type_unknown")))
        return out, undesigned

    # ── 판정 ─────────────────────────────────────────────────────────────────
    def classify(self, unit: Dict[str, Any], seq: Dict[str, Any], var: str) -> Dict[str, Any]:
        """칸 하나 → `{"check": 판정, "basis": 근거 글, "statement": 설계 진술, ["design_basis", "value", ...]}`."""
        ev = (seq.get("expected_evidence") or {}).get(var) or {}
        if ev.get("status") != "derived":
            return {"check": f"{NOT_CHECKED}:not_derived", "basis": ""}
        if ev.get("basis") == "unchanged_input":
            # 함수가 이 행에서 쓰지 않았다 — 값은 행이 넣은 입력 그대로라 함수의 결과가 아니다
            return {"check": f"{NOT_CHECKED}:unchanged_input", "basis": ""}
        value = _as_int((seq.get("expected") or {}).get(var))
        # 같은 출력의 진술 · 근거 글은 행마다 같다 — 한 번 만들어 같은 객체를 쓴다(KJPDS02_PV 확장 문서는 소스 계산 칸이
        #   십수만이라 행마다 근거 글을 새로 만들면 시트 셀이 그만큼의 문자열을 따로 든다)
        memo = self._memo.get((id(unit), var))
        if memo is None:
            st0 = self.statement(unit, var)
            memo = self._memo[(self._pin(unit), var)] = (st0, self._basis_text(st0) + self._twin_note(unit, st0),
                                                         self._domain(unit, var, st0))
        st, basis, dom = memo
        if value is None:
            return {"check": f"{NOT_CHECKED}:value_not_integer", "basis": basis, "statement": st}
        if st["status"] != "stated":
            return {"check": f"{NO_STATEMENT}:{st['reason']}", "basis": basis, "statement": st}
        design_basis = basis
        dv = _in_design_terms(dom, value)
        if dv != value:
            basis = basis + (f" · 같은 폭 · 부호만 다른 타입(설계 `{st.get('type')}` · 소스 {dom['src_type']}) — 비트 패턴으로 "
                             f"대조: {value} → {dv}")
        readings = [st] + [a["reading"] for a in st.get("conflicting") or () if a.get("reading")]
        inside = [_inside(r, dv) for r in readings]
        if all(inside):
            return {"check": CONSISTENT_FULL_WIDTH if dom.get("full_width") else CONSISTENT, "basis": basis,
                    "statement": st}
        if any(inside):
            # 설계 행 둘이 다른 말을 하고 값이 한쪽에만 든다 — 어느 행이 맞는지 이 대조가 고르지 않는다
            return {"check": CONFLICTING, "basis": basis + " · 값이 설계 행 한쪽 안 · 다른 쪽 밖", "statement": st,
                    "design_basis": design_basis, "value": value}
        res: Dict[str, Any] = {"statement": st, "value": value, "design_basis": design_basis,
                               "inputs_outside": [], "inputs_undesigned": []}
        between = [r for r in readings if _between_two_values(r, dv)]
        if between:
            # 값 둘 목록의 두 값 사이 — 값 둘로 읽으면 밖, 쉼표로 쓴 범위로 읽으면 안이다. 설계서가 어느 쪽인지 말하지 않았으니
            #   단정하지 않는다(두 값 밖이면 어느 읽기로도 밖이라 아래로 간다)
            vals = between[0]["values"]
            res["check"] = OUTSIDE_AMBIGUOUS_VALUES
            res["basis"] = basis + (f" · 값 {dv} 이 값 둘 {vals[0]},{vals[1]} 사이 — 값 둘이면 밖 · 쉼표로 쓴 범위면 안이라 "
                                    "단정하지 않는다")
            return res
        if self._type_differs(dom, value):
            res["check"] = OUTSIDE_TYPE_DIFFERS
            res["basis"] = basis + (f" · 설계 범위가 소스 타입 {dom['src_type']} 와 부호 표기가 다르다 — 표기 차이일 수 있어 "
                                    "어긋남을 단정하지 않는다")
            return res
        bad_in, undesigned = self._inputs(unit, seq.get("inputs") or {})
        if bad_in:
            basis += " · 설계 밖 입력: " + _cut(bad_in)
        elif undesigned:
            # 설계 진술 안의 입력만으로 밖이 됐다고 단정할 수 없다 — 설계가 말하지 않은 입력이 있다
            basis += " · 설계 진술 없이 넣은 입력: " + _cut([f"{n}({_UNDESIGNED_TEXT[h]})" for n, h in undesigned])
        stubs = [str(s) for s in ev.get("stubs") or ()]
        if stubs:
            basis += " · stub 한 피호출: " + _cut(stubs)
        # (2차 I-2) SwUDS 행이 범위 칸에 무엇을 적었는데 읽지 못해 HSIS 범위로 대조했다 — 설계서가 다른 말을 했을 수 있다
        cell_unread = str(st.get("uds_row_reason") or "").startswith("range_unread:")
        # (2차 W-A) 같은 이름의 정의가 여럿(APP · BOOT)인데 이름으로 찾은 SwUDS 표 하나 — 그 표가 이 빌드의 설계라는 근거가
        #   문서에 없다(HSIS 진술은 변수의 진술이라 해당 없다)
        twin = st.get("source") == "SwUDS" and len(self._by_name.get(str(unit.get("name") or "")) or []) >= 2
        if not (bad_in or undesigned or stubs):
            if cell_unread:
                basis += " · SwUDS 행의 범위 칸을 읽지 못해 HSIS 범위로 대조했다 — 단정하지 않는다"
            elif twin:
                basis += " · 같은 이름의 정의가 여럿이라 이름으로 찾은 표가 이 빌드의 설계인지 모른다 — 단정하지 않는다"
        res["basis"] = basis
        res["inputs_outside"] = bad_in
        res["inputs_undesigned"] = [] if bad_in else [n for n, _h in undesigned]
        res["check"] = (OUTSIDE_ON_INPUT if bad_in else OUTSIDE_UNDESIGNED_INPUT if undesigned
                        else OUTSIDE_STUB_VALUE if stubs else OUTSIDE_CELL_UNREAD if cell_unread
                        else OUTSIDE_TWIN if twin else OUTSIDE)
        return res

    def _twin_note(self, unit: Dict[str, Any], st: Dict[str, Any]) -> str:
        """같은 이름의 정의가 여럿(APP · BOOT 빌드)인데 이름으로 찾은 SwUDS 표 하나와 대조했다는 사실(리뷰 I6)."""
        if not (st.get("uds_row") or (st.get("where") and st.get("source") != "HSIS")):
            return ""       # 이름으로 찾은 설계 표를 쓰지 않았다(HSIS 진술 · 진술 없음)
        twins = self._by_name.get(str(unit.get("name") or "")) or []
        if len(twins) < 2:
            return ""
        parts = [_path_parts(u.get("source_path")) for u in twins]
        common = 0
        while all(len(p) > common + 1 for p in parts) and len({p[common].lower() for p in parts}) == 1:
            common += 1
        shown = sorted({"/".join(p[common:]) or "(경로 없음)" for p in parts})
        return (f" · 같은 이름의 정의 {len(twins)}개({_cut(shown, 3)}) — 이름으로 찾은 설계 표 하나와 대조했다"
                "(빌드마다 표가 따로인지 설계서가 말하지 않는다)")

    @staticmethod
    def _basis_text(st: Dict[str, Any]) -> str:
        if not st.get("where"):
            return ""
        s = f"{st.get('source', 'SwUDS')} {st['where']} Value Range `{st.get('text', '')}`"
        if st.get("status") == "stated":
            s += " → " + _reading_text(st)
        if st.get("two_value_list"):
            s += (" (값 둘 — '값 둘' 인지 쉼표로 쓴 범위인지 설계서가 말하지 않는다; 두 값과 같으면 안 · 두 값 밖이면 밖 · "
                  "사이면 단정하지 않는다)")
        if st.get("conflicting"):
            alts = [f"`{a['text']}`" + (f"(No {a['no']}" + (f" `{a['name']}`" if a["name"] != st.get("design_name") else "")
                                        + ")" if a.get("no") else "") for a in st["conflicting"]]
            s += " · 같은 출력의 다른 행: " + _cut(alts, 3)
        if st.get("uds_row"):
            s += (f" (SwUDS 행 {st['uds_row']} 은 범위를 적지 않았다)" if st.get("uds_row_reason") == "design_row_without_range"
                  else f" (SwUDS 행 {st['uds_row']} 의 범위 칸 `{st.get('uds_row_text', '')}` 을 읽지 못했다 — "
                       f"{st.get('uds_row_reason', '')})")
        return s


def _single_returned_identifier(fn_node: Any, raw: bytes) -> str:
    """함수 정의 하나의 모든 `return` 이 같은 식별자 하나를 돌려주면 그 이름, 아니면 ""."""
    idents, stack = set(), [fn_node]
    while stack:
        n = stack.pop()
        if n.type == "return_statement":
            expr = [c for c in n.named_children if c.type != "comment"]
            e = expr[0] if len(expr) == 1 else None
            while e is not None and e.type == "parenthesized_expression" and len(e.named_children) == 1:
                e = e.named_children[0]
            if e is None or e.type != "identifier":
                return ""
            idents.add(raw[e.start_byte:e.end_byte].decode("utf-8", "replace"))
            continue
        stack.extend(n.named_children)
    return next(iter(idents)) if len(idents) == 1 else ""


def summarize_design_check(units: List[Dict[str, Any]], all_sequences: Dict[str, List[Dict[str, Any]]],
                           uds_given: bool) -> Dict[str, Any]:
    """품질 보고서 `design_check` — 칸 판정 분포 · 설계 진술이 있는 출력(함수 · 이름) · 설계 밖 표본(전량은 시트).

    `outside_*` 는 어긋남을 단정할 수 있는 칸(`outside_design`)만, 약한 후보(`outside_design:<사유>`)는 사유마다 따로 센다."""
    chk = DesignChecker(units)
    by_check: Counter = Counter()
    no_stmt: Counter = Counter()
    by_source: Counter = Counter()
    outputs: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
    outside: Dict[Tuple[str, str], Dict[str, Any]] = {}
    weak: Dict[str, set] = {k: set() for k in WEAK_OUTSIDE}
    outside_in: set = set()
    conflicting_out: set = set()
    full_width_out: set = set()
    conflicting = set()
    derived = 0
    for unit in units:
        fid = str(unit.get("fid") or "")
        for seq in all_sequences.get(fid) or []:
            for var in dict.fromkeys([*(seq.get("expected") or {}), *(seq.get("expected_evidence") or {})]):
                res = chk.classify(unit, seq, var)
                check = res["check"]
                if check == f"{NOT_CHECKED}:not_derived":
                    continue
                derived += 1
                by_check[check_bucket(check)] += 1
                if check.startswith(NO_STATEMENT + ":") or check.startswith(NOT_CHECKED + ":"):
                    no_stmt[check] += 1
                st = res.get("statement")
                # 열쇠는 fid — 같은 이름의 정의가 둘(APP · FBL 의 static 함수)이면 이름으로 묶지 않는다
                key = (fid, var)
                if st is not None:
                    outputs.setdefault(key, st if st.get("status") == "stated" else None)
                    if st.get("status") == "stated":
                        by_source[st["source"]] += 1
                    if st.get("conflicting"):
                        conflicting.add(key)
                if check == OUTSIDE:
                    o = outside.setdefault(key, {"function": str(unit.get("name") or ""), "output": var, "values": set(),
                                                 "rows": 0, "design": res["design_basis"]})
                    o["values"].add(res["value"])
                    o["rows"] += 1
                elif check in weak:
                    weak[check].add(key)
                elif check == OUTSIDE_ON_INPUT:
                    outside_in.add(key)
                elif check == CONFLICTING:
                    conflicting_out.add(key)
                elif check == CONSISTENT_FULL_WIDTH:
                    full_width_out.add(key)
    stated = [k for k, v in outputs.items() if v]
    samples = []
    ordered = sorted(outside.values(), key=lambda x: (x["function"], x["output"]))
    for o in ordered[:SAMPLE_N]:
        vals = sorted(o["values"])
        samples.append(f"{o['function']}.{o['output']} = {','.join(str(v) for v in vals[:5])}"
                       + (f" 외 {len(vals) - 5}" if len(vals) > 5 else "") + f" ({o['rows']}행) ← {o['design']}")
    summary = {
        "uds_given": bool(uds_given),
        "derived_slots": derived,
        "by_check": dict(by_check),
        "not_compared_by_reason": dict(no_stmt),
        "stated_slots_by_source": dict(by_source),
        "outputs": len(outputs), "outputs_with_statement": len(stated),
        "functions_with_statement": len({k[0] for k in stated}),
        "functions": len({k[0] for k in outputs}),
        "consistent_slots": int(by_check.get(CONSISTENT, 0)),
        # 설계 범위가 값의 타입 전폭 — 어긋날 수 없던 대조(리뷰 W2)
        "type_full_width_slots": int(by_check.get(CONSISTENT_FULL_WIDTH, 0)),
        "type_full_width_outputs": len(full_width_out),
        # 어긋남을 단정할 수 있는 칸만(리뷰 W1)
        "outside_slots": int(by_check.get(OUTSIDE, 0)),
        "outside_outputs": len(outside), "outside_functions": len({k[0] for k in outside}),
        "outside_on_input_slots": int(by_check.get(OUTSIDE_ON_INPUT, 0)),
        "outside_on_input_outputs": len(outside_in),
        "conflicting_design_slots": int(by_check.get(CONFLICTING, 0)),
        "conflicting_design_outputs": len(conflicting_out),
        "conflicting_design_rows": len(conflicting),
        "outside_samples": samples,
        "outside_samples_total": len(ordered),
    }
    for label, keys in weak.items():
        tag = label.split(":", 1)[1]
        summary[f"outside_{tag}_slots"] = int(by_check.get(label, 0))
        summary[f"outside_{tag}_outputs"] = len(keys)
    return summary
