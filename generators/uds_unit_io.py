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
"""
from __future__ import annotations

import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from generators.uds_design_ids import _DESIGN_ID_PAT

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
    s = re.sub(r"\s*([.\[\]])\s*", r"\1", s)  # `DiagData. OpenFailure [3]`
    s = s.strip().strip(",;")
    if not s or s.lower() in _NA:
        return ""
    # 식별자로 시작하지 않으면(설명문이 이름 칸에 들어온 경우) 버린다.
    if not re.match(r"^[A-Za-z_]", s):
        return ""
    return s


def _cell_lines(tc) -> List[str]:
    """셀 텍스트를 **줄 단위**로.

    ⚠ 문단(`w:p`)만 끊으면 부족하다 — 한 문단 안에서 `w:br` 로 나열하는 칸이 있어
      문단 단위로만 뽑으면 `u8s_A_Fu8s_B_Cnt` 처럼 이름이 뭉친다(실측).
    """
    out: List[str] = []
    for p in tc.findall(f"{_W}p"):
        buf: List[str] = []
        for node in p.iter():
            if node.tag == f"{_W}t":
                buf.append(node.text or "")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                s = "".join(buf).strip()
                if s:
                    out.append(s)
                buf = []
        s = "".join(buf).strip()
        if s:
            out.append(s)
    return out


def _parse_table(tbl) -> Dict[str, List[str]]:
    """함수 표 하나 → `{"inputs": [...], "outputs": [...]}`."""
    inputs: List[str] = []
    outputs: List[str] = []
    mode = ""
    for tr in tbl.findall(f"{_W}tr"):
        cells = [" ".join(_cell_lines(tc)) for tc in tr.findall(f"{_W}tc")]
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
        # 표 머리행(`No | Name | …`)과 키-값 행(`ID | SwUFn_0101`)은 데이터가 아니다.
        if not re.fullmatch(r"\d+", head):
            if head and not head[0].isdigit():
                # `선행조건` · `Called Function` 등을 만나면 파라미터 구간이 끝난 것이다.
                if head not in ("No",):
                    mode = ""
            continue
        if not mode or len(cells) < 2:
            continue
        nm = clean_param_name(cells[1])
        if nm:
            (inputs if mode == "in" else outputs).append(nm)
    return {"inputs": inputs, "outputs": outputs}


def load_uds_unit_io(uds_path: Any) -> Dict[str, Any]:
    """`{"by_name": {함수명: {"inputs": [...], "outputs": [...]}}, "ambiguous": [...]}`.

    ⚠ 호출부는 **로컬로 materialize 된 경로**를 준다(cloudium 경로는 worker 만 연다).
    파싱 실패는 **빈 맵**이다 — 그 경우 호출부는 소스 파싱 결과를 그대로 쓴다.
    지어내지 않는다.
    """
    empty: Dict[str, Any] = {"by_name": {}, "ambiguous": [], "total": 0, "source": ""}
    raw = str(uds_path or "").strip()
    if not raw:
        return empty
    p = Path(raw)
    sig = _signature(p)
    if sig is None:
        return empty
    key = str(p.resolve()) if p.exists() else raw
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and hit[0] == sig and (now - hit[1]) < _CACHE_TTL_SEC:
        return hit[2]
    if p.suffix.lower() != ".docx":
        _logger.info("uds unit-io: unsupported suffix %s (%s)", p.suffix, p.name)
        return empty

    try:
        # ⚠ python-docx 로 통째로 올리지 않는다 — 이 문서는 53MB 다. `word/document.xml`
        #   만 lxml 로 훑는다(이 저장소가 docx 파싱에서 400s→2.6s 로 겪은 축).
        from lxml import etree

        with zipfile.ZipFile(str(p)) as zf:
            xml = zf.read("word/document.xml")
        body = etree.fromstring(xml).find(f"{_W}body")
        if body is None:
            raise ValueError("word/document.xml 에 body 가 없다")
    except Exception as exc:  # noqa: BLE001 — zip/xml/의존성 예외가 모두 여기로 온다
        _logger.warning("uds unit-io: cannot read %s: %s", p.name, exc)
        return empty

    by_name: Dict[str, Dict[str, List[str]]] = {}
    ambiguous: set[str] = set()
    total = 0
    pending: Optional[str] = None   # 직전 문단이 지목한 함수명
    for el in body:
        if el.tag == f"{_W}p":
            text = "".join(t.text or "" for t in el.iter(f"{_W}t")).strip()
            m = _DESIGN_ID_PAT.match(text)
            if m:
                pending = m.group(2)
            continue
        if el.tag != f"{_W}tbl" or pending is None:
            continue
        rec = _parse_table(el)
        total += 1
        if pending in by_name:
            # 같은 이름이 두 번 — 어느 표가 이 함수인지 못 정한다.
            ambiguous.add(pending)
        else:
            by_name[pending] = rec
        pending = None

    for nm in ambiguous:
        by_name.pop(nm, None)

    result: Dict[str, Any] = {
        "by_name": by_name,
        "ambiguous": sorted(ambiguous),
        "total": total,
        "source": p.name,
    }
    _CACHE[key] = (sig, now, result)
    _logger.info(
        "uds unit-io: %s → %d 함수 (표 %d · 동명이인 %d 제외) | 입력 %d · 기대 %d",
        p.name, len(by_name), total, len(ambiguous),
        sum(len(v["inputs"]) for v in by_name.values()),
        sum(len(v["outputs"]) for v in by_name.values()),
    )
    return result


def resolve_unit_io(io_map: Optional[Dict[str, Any]], fn_name: Any) -> Optional[Dict[str, List[str]]]:
    """함수명 → `{"inputs": [...], "outputs": [...]}`. 못 찾으면 **None**.

    None 은 "UDS 에 근거가 없다" 이고, 호출부는 그때 소스 파싱 결과를 유지해야 한다.
    빈 dict 로 바꾸면 "UDS 가 0개라고 적었다" 와 구분이 사라진다.
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
    return None
