"""SwUDS 문서에서 **설계 ID**(`SwUFn_xxxx`)를 읽는다.

## 무엇을 푸는가

시험 규격서의 `Related ID / SUDS` 칸과 `TC_ID` 는 **SwUDS 가 부여한 설계 ID** 를
가리켜야 한다. 정본 실측(KJPDS02_SwUTS v1.02): `TC_ID = "SwUTC_" + SUDS` 가
**1,013 / 1,014** 에서 성립한다.

생성기는 그동안 `SwUFn_{소스파싱순번:04d}` 를 만들어 두 칸에 넣었다. 모양은 같지만
**다른 설계 요소를 가리킨다** — 정본과 교집합이 251개 중 178개뿐이었다. 틀린 ID 가
추적성으로 보이는 것은 빈칸보다 나쁘다(`[[project_provenance_laundering]]` 계열).

## 근거는 문서 안에 있다

SwUDS 본문에 `SwUFn_0101: main` 형태의 문단이 함수마다 있다(실측 1,035개).
그대로 읽어 `함수명 → 설계 ID` 로 만든다.

## 동명이인은 채우지 않는다

같은 함수명이 서로 다른 설계 ID 를 갖는 경우가 있다(다른 모듈의 static 함수 —
실측 9건: `SCI0_Init` 이 `SwUFn_2901` 과 `SwUFn_3515` 양쪽). 이름만으로는 어느
쪽인지 정할 수 없으므로 **후보에서 제외한다**. 임의로 하나를 고르면 0.9% 를 채우는
대신 그 0.9% 가 조용히 틀린다.

실측 정합: 유일 이름 기준 정본 1,014건 중 **1,001건 일치(98.7%)** · 이름 미발견 4 ·
동명이인 9(제외 대상).

## 머리말의 이름은 식별자까지 (R65)

머리말 문단은 이름 뒤에 표시를 붙인다 — HDPDM01 SwUDS v1.07 에서 `u8s_DataValidCheck(New)` ·
`s_DoorState_TipToRun_Detection(NEW)` 18 개 · `s_RemoteSleepCheckTimer(삭제)` 1 개. 예전엔 `(\\S+)` 로
표시까지 이름에 넣어 그 18 함수가 설계 ID · 입출력 표 · 범위 · ASIL 을 **전부** 잃었다(소스 함수 이름과
맞지 않으므로). 이름은 머리말의 첫 식별자이고, 표시는 따로 읽는다: `(삭제)` 류는(붙었든 공백 뒤든) 문서가
그 설계를 지웠다는 뜻이라 매핑하지 않고(`deleted`), 알려진 표시(`(New)` · `(수정)` …)는 이름을 바꾸지 않으며
(`marked`), 모르는 괄호 표시는 유효한 설계로 단정하지 않는다(`unread` — 공시).

함수 표의 `Name` 행이 머리말과 다르면(대소문자 말고) 그 이름도 **별칭**으로 둔다 — HDPDM01 머리말
`g_DrvIn_MotorPosition` · `u16_sMotorShortBattA1_Check` 는 표 `Name` 행(`g_DrvIn_MotorPostion` ·
`u16s_MotorShortBattA1_Check`)이 소스의 실제 이름이었다. 별칭이 어느 머리말 이름(삭제 · 표 없는 머리말 포함)과
같거나 두 표가 같은 별칭을 적으면 쓰지 않고(어느 표인지 못 정한다 — 동명이인과 같은 규칙), 별칭이 가리키는
머리말 이름이 소스에도 함수로 있으면 호출부가 `restrict_aliases` 로 뺀다(한 표가 두 함수의 근거가 되지 않게).
별칭 계산은 두 로더(이 모듈 · `uds_unit_io`)가 `name_row_aliases` 하나를 같은 항목으로 부른다.
"""
from __future__ import annotations

import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 본문 문단 `SwUFn_0101: main` — 설계 ID 머리말인지 판정만 한다(이름은 `read_design_heading`).
_DESIGN_ID_PAT = re.compile(r"^(SwUFn_\d+)\s*[:：]\s*(\S+)")
_HEADING = re.compile(r"^(SwUFn_\d+)\s*[:：]\s*([A-Za-z_]\w*)(.*)$")
# 문서가 그 설계를 지웠다는 표시 — 괄호 안 어디에 있든(`(삭제)` · `(New, 삭제)` · `(삭제됨)`) 이 표는 소스 함수의 설계가
#   아니다(리뷰 R65 W2: 공백 뒤 `(삭제)` 를 이름으로 읽어 같은 이름의 `(New)` 설계와 동명이인이 됐다)
_DELETED_WORD = (r"(?:(?:삭제|폐기)\s*(?:되었음|하였음|했음|됨|함|된|처리\s*됨|처리)?|미사용|"
                 r"사용\s*(?:안\s*함|하지\s*않음|안\s*됨)|"
                 r"deleted?|removed?|del|obsolete|unused|not\s+used)")
_DELETED_PHRASE = re.compile(rf"{_DELETED_WORD}(?:\s+{_DELETED_WORD})*", re.I)
# 같은 이름 머리말 사이의 선택(`select_live_headings`)은 삭제 낱말을 **낱말로** 찾는다 — 부분문자열이면 `Delay` · `Model` ·
#   `삭제버튼` 에 걸려 동명이인(다른 모듈의 static 함수)인데 한쪽을 골랐다(리뷰 R65 4차 W1)
#   영어 낱말의 경계는 식별자 글자 전체(`_` · 숫자 포함 — `DEL_FLAG` 는 삭제가 아니다; 5차 I1)
_DELETED_ANY = re.compile(r"(?<![A-Za-z0-9_])(?:deleted?|removed?|del|obsolete|unused|not\s+used)(?![A-Za-z0-9_])|"
                          r"(?:삭제|폐기)(?:\s*(?:되었음|하였음|했음|됨|함|된|처리\s*됨|처리))?(?![가-힣])|"
                          r"미사용(?![가-힣])|"
                          r"사용\s*(?:안\s*함|하지\s*않음|안\s*됨)", re.I)
# 삭제 표시와 함께 써도 되는 상태 낱말 · 버전 · 날짜 · 조사(`(New, 삭제)` · `(v1.05에서 삭제)` · `(Rev.3 삭제)` ·
#   `(deleted in v1.05)` · `(삭제된 함수)`) — 그 밖의 낱말이 섞이면 설명이다(리뷰 R65 2차 N1: `(DTC 이력 삭제)` ·
#   `(삭제 예정)` 은 기능 설명이지 설계 삭제가 아니다; 3차 I1 이 놓치는 변형을 찾았다)
#   경계는 ASCII 기준이다 — 한글 바로 앞에서는 `\b` 가 서지 않는다(`v1.05에서`)
_STATUS_WORDS = re.compile(r"(?<![A-Za-z])(?:new|added|modified|changed|updated|in|from|function)(?![A-Za-z])|"
                           r"(?<![A-Za-z0-9.])(?:rev\.?\s*|r|v)?\d+(?:\.\d+)*(?![0-9.])|신규|추가|수정|변경|에서|함수",
                           re.I)
# 문단 스타일이 목차인 문단은 머리말이 아니다(리뷰 R65 2차 N7 — `main<탭>12` 가 실제 머리말과 동명이인이 된다). 스타일
#   ID 는 언어마다 다르다(영문 `TOC1` · 한국어 Word 는 숫자 `11` — 3차 I2) — `styles.xml` 의 스타일 이름(`toc 1`)으로 판정한다
_TOC_STYLE = re.compile(r"^toc", re.I)


def _is_deletion_mark(mark: str) -> bool:
    """표시 전체가 삭제 상태인가 — 괄호 · 대괄호 표시는 걷고 상태 낱말 · 버전 · 날짜 · 조사를 뺀 나머지가 삭제 낱말뿐일 때,
    괄호 없는 꼬리 글(` - 삭제` · ` 삭제 함수`)은 대시를 걷은 글이 **삭제 낱말뿐**일 때만(설명 글일 수 있다)."""
    if not re.match(r"^[(\[]", mark):
        bare = re.sub(r"^[\s\-–—:]+", "", mark).strip(" .")
        return bool(bare) and bool(_DELETED_PHRASE.fullmatch(bare))
    if re.search("함수", mark) and re.search(r"추가|신규|(?<![A-Za-z])new(?![A-Za-z])", mark, re.I):
        # `(삭제 함수 추가)` · `(신규 삭제 함수)` — 지우는 기능을 더했다는 설명이다(리뷰 R65 4차 I2)
        return False
    rest = _STATUS_WORDS.sub(" ", mark)
    rest = re.sub(r"[\s,/·;:+&()\[\]\-–—.]+", " ", rest).strip()
    return bool(rest) and bool(_DELETED_PHRASE.fullmatch(rest))


def select_live_headings(entries: List[Dict[str, Any]]) -> None:
    """(리뷰 R65 3차 I1) 같은 이름의 머리말이 여럿이고 그중 표시에 삭제 낱말이 **없는** 것이 하나뿐이면 그것을 쓰고, 나머지는
    `superseded`(쓰지 않음 — 공시)로 둔다. `f_x(삭제함)` + `f_x(New)` 를 동명이인으로 둘 다 잃지 않게 — 삭제 표현을 다
    알아보지 못해도 닫힌다. 삭제 낱말이 없는 것이 둘 이상이면(다른 모듈의 static 함수) 그대로 동명이인이다."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        if e.get("status") in ("plain", "marked") and e.get("name"):
            groups.setdefault(e["name"], []).append(e)
    for name, group in groups.items():
        if len(group) < 2:
            continue
        live = [e for e in group if not _DELETED_ANY.search(e.get("mark") or "")]
        if len(live) == 1:
            for e in group:
                if e is not live[0]:
                    e["status"] = "superseded"
                    e["superseded_by"] = live[0]["text"]

# (경로, mtime_ns, size) → 결과. 53MB docx 파싱이 수 초라 매 호출 재파싱은 못 쓴다.
_CACHE: Dict[str, Tuple[Tuple[int, int], float, Dict[str, Any]]] = {}
_CACHE_TTL_SEC = 600.0


def read_design_heading(text: Any) -> Optional[Dict[str, str]]:
    """머리말 문단 → `{"id", "name", "mark", "status", "text"}`. 설계 ID 머리말이 아니면 None.

    `status`: `plain`(이름뿐 · 공백 뒤 설명 글 — 옛 `(\\S+)` 와 같은 이름) · `deleted`(표시 전체가 삭제 상태 — `(삭제)` ·
    `(New, 삭제)` · ` - 삭제` · `[삭제]`, 붙었든 공백 뒤든; 매핑하지 않는다) · `marked`(그 밖의 괄호 표시 — `(New)` ·
    `(Internal -> Interface 이동)` · `(DTC 이력 삭제)`; 이름은 그대로, 표시는 공시) · `unread`(이름이 식별자로 시작하지
    않거나 괄호가 아닌 글이 이름에 붙음 — `main-old`). 같은 이름 머리말 사이의 선택은 `select_live_headings`.
    """
    s = " ".join(str(text or "").split())
    head = _DESIGN_ID_PAT.match(s)
    if not head:
        return None
    m = _HEADING.match(s)
    if not m:
        return {"id": head.group(1), "name": "", "mark": "", "status": "unread", "text": s}
    did, name, rest = m.group(1), m.group(2), m.group(3)
    mark = rest.strip()
    paren = re.fullmatch(r"\(([^()]*)\)", mark)
    if not mark or mark == "()":
        status = "plain"
    elif _is_deletion_mark(mark):
        status = "deleted"
    elif paren:
        status = "marked"
    elif rest[:1].isspace():
        status = "plain"
    else:
        status = "unread"
    return {"id": did, "name": name, "mark": mark if status != "plain" else "", "status": status, "text": s}


# 문단 글에 넣지 않는 하위 트리 — 글상자 · 도형 · 대체 콘텐츠(python-docx `Paragraph.text` 도 넣지 않는다). HDPDM01
#   머리말 `SwUFn_3531: LinUdsToTp` 문단에 도형 속 번호 `2` · `1`(Choice · Fallback 두 벌)이 들어 있어 `2211SwUFn_3531…` 로
#   읽혔다(옛 `uds_unit_io` 도 같은 이유로 그 표를 놓쳤다).
_SKIP_TEXT_TAGS = {f"{_W}txbxContent", f"{_W}drawing", f"{_W}pict", f"{_W}object"}
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
# 글 노드: 글 · 탭(위치 탭 포함) · 줄바꿈 · 비분리 하이픈(Ctrl+Shift+- 로 입력한 음수 부호 — 리뷰 R65 2차 N5: `-240` 이
#   `240` 이 됐다)
_TEXT_TAGS = {f"{_W}t", f"{_W}tab", f"{_W}ptab", f"{_W}br", f"{_W}cr", f"{_W}noBreakHyphen"}


def text_of_node(node) -> str:
    """`iter_text_nodes` 가 낸 노드의 글 — 탭 · 위치 탭은 공백, 줄바꿈은 `\n`, 비분리 하이픈은 `-`."""
    tag = node.tag
    if tag == f"{_W}t":
        return node.text or ""
    if tag == f"{_W}noBreakHyphen":
        return "-"
    if tag in (f"{_W}br", f"{_W}cr"):
        return "\n"
    return " "


def iter_text_nodes(el) -> Iterator[Any]:
    """`el` 아래 글 노드를 문서 순서로 — 글상자 · 도형 안은 건너뛰고, 대체 콘텐츠(`mc:AlternateContent`)는 첫 `mc:Choice`
    만 읽는다(둘 중 하나라는 뜻 — 통째로 건너뛰면 그 안의 글 run 이 사라진다; 리뷰 R65 2차 N6)."""
    stack = [iter(el)]
    while stack:
        for node in stack[-1]:
            tag = node.tag
            if tag in _SKIP_TEXT_TAGS:
                continue
            if tag == f"{_MC}AlternateContent":
                # 첫 Choice 에 글이 없으면 Fallback(규격상 Choice 를 처리할 수 없을 때 쓰는 쪽 — 3차 I5)
                pick = next((c for c in (node.find(f"{_MC}Choice"), node.find(f"{_MC}Fallback"))
                             if c is not None and any(True for _ in iter_text_nodes(c))), None)
                if pick is not None:
                    stack.append(iter(pick))
                    break
                continue
            if tag in _TEXT_TAGS:
                yield node
            if len(node):
                stack.append(iter(node))
                break
        else:
            stack.pop()


def _text(el) -> str:
    """요소의 글 — 탭 · 줄바꿈은 공백으로(python-docx `Paragraph.text` 처럼; 리뷰 R65 I5: `f_x<탭>Init` 이 `f_xInit` 이 되지
    않게), 글상자 · 도형 안 글은 넣지 않는다."""
    return " ".join("".join(text_of_node(n) for n in iter_text_nodes(el)).split())


def table_name_row(tbl) -> str:
    """함수 표 `[ Function Information ]` 의 `Name` 행 값(라벨 다음 칸) — 없으면 빈 문자열."""
    for tr in tbl.findall(f"{_W}tr"):
        cells = [_text(tc) for tc in tr.findall(f"{_W}tc")]
        if cells and cells[0] == "Name":
            return next((c for c in cells[1:] if c != "Name"), "")
        if cells and re.match(r"^\[\s*(Input|Output)\s+Parameters", cells[0], re.I):
            return ""
    return ""


def read_docx_body(p: Path):
    """`word/document.xml` 의 body(lxml). python-docx 로 통째로 올리지 않는다 — 53MB 문서다."""
    from lxml import etree

    with zipfile.ZipFile(str(p)) as zf:
        xml = zf.read("word/document.xml")
    body = etree.fromstring(xml).find(f"{_W}body")
    if body is None:
        raise ValueError("word/document.xml 에 body 가 없다")
    return body


def read_toc_style_ids(p: Path) -> set:
    """`word/styles.xml` 에서 이름이 `toc N` 인 문단 스타일의 ID(한국어 Word 는 숫자 ID `11` · `22` …). 없거나 못 읽으면 빈
    집합 — 그때는 ID 가 `TOC` 로 시작하는 스타일만 목차로 본다."""
    from lxml import etree

    try:
        with zipfile.ZipFile(str(p)) as zf:
            root = etree.fromstring(zf.read("word/styles.xml"))
    except (KeyError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        _logger.debug("uds design-id: styles.xml unreadable in %s: %s", p.name, exc)
        return set()
    out = set()
    for st in root.findall(f"{_W}style"):
        nm = st.find(f"{_W}name")
        if nm is not None and re.fullmatch(r"toc\s*\d+", (nm.get(f"{_W}val") or "").strip(), re.I):
            out.add(st.get(f"{_W}styleId") or "")
    return out - {""}


def read_error_text(exc: BaseException, p: Path) -> str:
    """읽기 실패 사유 — 공시에 실리므로 로컬 · 임시 경로는 파일 이름으로 바꾼다(리뷰 R65 I7 · 2차 N8: OSError 의 글은 경로를
    이스케이프해 담아 치환이 맞지 않는다 — `strerror` 와 파일 이름으로 쓴다)."""
    if isinstance(exc, OSError) and exc.strerror:
        return f"{type(exc).__name__}: {exc.strerror} ({p.name})"[:200]
    msg = str(exc)
    for path in sorted({str(p), str(p.parent), str(p.resolve()) if p.exists() else ""} - {""}, key=len, reverse=True):
        msg = msg.replace(path, p.name if path.endswith(p.name) else "…")
    return f"{type(exc).__name__}: {msg}"[:200]


def iter_design_entries(body, toc_styles: Optional[set] = None) -> Iterator[Dict[str, Any]]:
    """body 의 설계 ID 머리말마다 `read_design_heading` 결과 + `table`(다음 머리말 전의 첫 표 — 없으면 None).

    머리말과 표는 body 바로 아래 형제다(python-docx `doc.paragraphs` 와 같은 범위 — 표 안 문단은 머리말이 아니다).
    목차 문단(`toc_styles` — `read_toc_style_ids` — 또는 ID 가 `TOC` 로 시작하는 스타일)은 건너뛴다.
    """
    toc = set(toc_styles or ())
    cur: Optional[Dict[str, Any]] = None
    for el in body:
        if el.tag == f"{_W}p":
            # 빠른 거름(리뷰 R65 2차 N14) — 설계 ID 가 없는 문단은 정밀 판독하지 않는다(run 이 갈라도 이어 붙여 본다)
            if "SwUFn" not in "".join(t.text or "" for t in el.iter(f"{_W}t")):
                continue
            ps = el.find(f"{_W}pPr/{_W}pStyle")
            if ps is not None and ((ps.get(f"{_W}val") or "") in toc or _TOC_STYLE.match(ps.get(f"{_W}val") or "")):
                continue
            h = read_design_heading(_text(el))
            if h is not None:
                if cur is not None:
                    yield cur
                cur = {**h, "table": None}
            continue
        if el.tag == f"{_W}tbl" and cur is not None and cur["table"] is None:
            cur["table"] = el
    if cur is not None:
        yield cur


def name_row_aliases(entries: List[Dict[str, Any]]) -> Tuple[Dict[str, str], List[str]]:
    """머리말 항목들(`iter_design_entries`) → (표 `Name` 행 별칭 → 머리말 이름, 쓰지 않은 별칭 설명).

    두 로더(`load_uds_design_ids` · `load_uds_unit_io`)가 **같은 항목으로 이 함수 하나**를 부른다(리뷰 R65 W1 — 따로 세면
    한쪽은 설계 ID, 다른 쪽은 입출력 표를 다른 함수에서 가져왔다). 대소문자만 다른 것은 별칭이 아니다(조회가 이미 대소문자를
    가리지 않는다). 별칭이 **어느 머리말 이름**(삭제 · 못 읽은 · 표 없는 머리말 포함)과 같거나 두 표가 같은 별칭을 적으면
    쓰지 않는다 — 어느 표인지 못 정한다. 삭제 · 못 읽은 머리말의 표는 별칭을 내지 않는다.
    """
    headed = {str(e.get("name") or "").lower() for e in entries if e.get("name")}
    claims: Dict[str, List[str]] = {}
    for e in entries:
        if e.get("status") not in ("plain", "marked") or e.get("table") is None:
            continue
        head, row = e["name"], table_name_row(e["table"])
        if not row or not re.fullmatch(r"[A-Za-z_]\w*", row) or row.lower() == head.lower():
            continue
        claims.setdefault(row, []).append(head)
    aliases: Dict[str, str] = {}
    dropped: List[str] = []
    for row, heads in sorted(claims.items()):
        if row.lower() in headed:
            dropped.append(f"{row}(다른 머리말 이름)")
        elif len(set(heads)) > 1:
            dropped.append(f"{row}({'·'.join(sorted(set(heads)))} 두 표)")
        else:
            aliases[row] = heads[0]
    return aliases, dropped


def restrict_aliases(mapping: Optional[Dict[str, Any]], source_functions: Any) -> Optional[Dict[str, Any]]:
    """(리뷰 R65 W1) 별칭이 가리키는 머리말 이름이 **소스에도 함수로 있으면** 그 별칭을 쓰지 않는다 — 그 표는 머리말 함수의
    것일 수 있어(표 `Name` 행이 다른 함수를 베낀 경우) 한 표가 두 함수의 근거가 된다. 캐시된 결과를 바꾸지 않도록 얕은 사본을
    돌려준다. 뺀 별칭은 `alias_dropped_source` 에 남는다.

    별칭은 이 함수를 거친 맵(`aliases_checked`)에서만 조회된다(리뷰 R65 2차 N2 — 소스 함수 목록을 넘기지 않은 호출처가
    확인 안 된 별칭을 쓰지 않게; 로더의 `source_functions` 인자가 이 함수를 부른다)."""
    if not mapping:
        return mapping
    known = {str(x).lower() for x in (source_functions or ()) if x}
    aliases = mapping.get("aliases") or {}
    keep = {a: h for a, h in aliases.items() if h.lower() not in known}
    return {**mapping, "aliases": keep, "aliases_checked": True,
            "alias_dropped_source": sorted(f"{a}→{h}" for a, h in aliases.items() if a not in keep)}


def checked_aliases(mapping: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """조회에 쓸 별칭 — `restrict_aliases` 를 거친 맵의 것만(아니면 빈 dict)."""
    return dict((mapping or {}).get("aliases") or {}) if (mapping or {}).get("aliases_checked") else {}


def _signature(p: Path) -> Optional[Tuple[int, int]]:
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError as exc:
        _logger.debug("uds design-id: stat failed for %s: %s", p, exc)
        return None


def load_uds_design_ids(uds_path: str, source_functions: Any = None) -> Dict[str, Any]:
    """`{"by_name": {함수명: 설계ID}, "ambiguous": [...], "total": n, "aliases": {표 Name 행: 머리말 이름}, ...}`.

    ⚠ 호출부는 **로컬로 materialize 된 경로**를 준다(cloudium 경로는 worker 만 연다).

    파싱 실패는 빈 맵이다 — 그 경우 호출부는 ID 칸을 비워야 하고, **순번으로
    대체하면 안 된다**(그게 원래 결함이다).
    `source_functions`(소스 함수 이름들)를 주면 `restrict_aliases` 를 거친 사본을 돌려준다 — 별칭은 그때만 조회된다.
    """
    result = _load_uds_design_ids(uds_path)
    return restrict_aliases(result, source_functions) if source_functions is not None else result


def _load_uds_design_ids(uds_path: str) -> Dict[str, Any]:
    empty: Dict[str, Any] = {"by_name": {}, "ambiguous": [], "total": 0, "source": "", "aliases": {},
                             "marked": [], "deleted": [], "unread_headings": [], "alias_conflicts": []}
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
        _logger.info("uds design-id: unsupported suffix %s (%s)", p.suffix, p.name)
        return empty
    try:
        body = read_docx_body(p)
    except Exception as exc:  # noqa: BLE001 — zip/xml/의존성 예외가 모두 여기로 온다
        _logger.warning("uds design-id: cannot open %s: %s", p.name, exc)
        return {**empty, "read_error": read_error_text(exc, p)}

    entries = list(iter_design_entries(body, read_toc_style_ids(p)))
    select_live_headings(entries)
    seen: Dict[str, str] = {}
    ambiguous: set[str] = set()
    marked: List[str] = []
    deleted: List[str] = []
    unread: List[str] = []
    superseded: List[str] = []
    for e in entries:
        if e["status"] == "deleted":
            deleted.append(e["text"])
            continue
        if e["status"] == "unread":
            unread.append(e["text"])
            continue
        if e["status"] == "superseded":
            superseded.append(f"{e['text']} → {e['superseded_by']}")
            continue
        if e["status"] == "marked":
            marked.append(e["text"])
        design_id, fn_name = e["id"], e["name"]
        prev = seen.get(fn_name)
        if prev is None:
            seen[fn_name] = design_id
        elif prev != design_id:
            # 동명이인 — 이름만으로 못 고른다. 아래에서 통째로 뺀다.
            ambiguous.add(fn_name)

    for name in ambiguous:
        seen.pop(name, None)
    aliases, alias_conflicts = name_row_aliases(entries)
    aliases = {a: h for a, h in aliases.items() if h in seen}

    result: Dict[str, Any] = {
        "by_name": seen,
        "ambiguous": sorted(ambiguous),
        "total": len(entries),
        "source": p.name,
        "aliases": aliases,
        "marked": marked,
        "deleted": deleted,
        "unread_headings": unread,
        "superseded_headings": superseded,
        "alias_conflicts": alias_conflicts,
    }
    _CACHE[key] = (sig, now, result)
    _logger.info(
        "uds design-id: %s → %d ids (문단 %d · 동명이인 %d 제외 · 표시 붙은 머리말 %d · 삭제 %d · 표 Name 별칭 %d)",
        p.name, len(seen), len(entries), len(ambiguous), len(marked), len(deleted), len(aliases),
    )
    return result


def resolve_design_id(design_ids: Optional[Dict[str, Any]], fn_name: Any) -> str:
    """함수명 → 설계 ID. 못 찾으면 **빈 문자열**(순번으로 대체하지 않는다).

    머리말 이름 → 대소문자만 다른 머리말 이름 → 표 `Name` 행 별칭(R65 — `restrict_aliases` 를 거친 맵에서만) 순서다.
    """
    if not design_ids:
        return ""
    by_name = design_ids.get("by_name") or {}
    name = str(fn_name or "").strip()
    if not name:
        return ""
    got = by_name.get(name)
    if got:
        return str(got)
    # 대소문자만 다른 표기는 같은 함수로 본다(문서 표기 흔들림). 그래도 못 찾으면 빈칸.
    lowered = name.lower()
    for k, v in by_name.items():
        if k.lower() == lowered:
            return str(v)
    aliases = checked_aliases(design_ids)
    head = aliases.get(name) or next((h for a, h in aliases.items() if a.lower() == lowered), None)
    if head and by_name.get(head):
        return str(by_name[head])
    return ""
