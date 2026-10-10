"""개정 이력(History) 시트에 **이번 개정을 한 행 덧붙인다**.

## 왜 필요한가

납품 정본을 템플릿으로 쓰면(`docgen_template_source`) 과거 개정 이력이 그대로
딸려온다. 그걸 지우면 문서가 어디서 왔는지 사라지고, 그대로 두면 "이번에 다시
만들었다" 는 사실이 문서에 없다. 개정 이력의 본래 쓰임대로 **다음 행에 덧붙인다**
(사용자 결정, 2026-08-12).

## 정본 구조 (KJPDS02_SwUTS v1.02 실측)

    r2  B: ■ Revision History
    r4  B:Version  C:Date  D:변경위치  E:Description  F:변경ID  G:Author  H:Reviewer  I:Approver
    r5~ B:v0.10   C:25.09.16  E:소프트웨어 단위 테스트 사양서 초안 작성  G:주희영 …

헤더 라벨을 **찾아서** 열을 정한다 — 문서마다 열이 조금씩 다르고(SwTS 는 `변경위치`가
있고 없고), 번호를 박으면 다른 문서에서 엉뚱한 칸에 쓴다.

## 쓰지 않는 경우

- History 시트가 없으면 아무것도 하지 않는다(새로 만들지 않는다 — 템플릿의 서식을
  흉내 낸 시트는 납품본과 다르다).
- 같은 버전이 이미 마지막 행에 있으면 **덧붙이지 않는다**(재생성 때마다 같은 행이
  쌓이면 이력이 아니라 로그가 된다).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)

_HISTORY_SHEETS = ("History", "history", "Revision History")

# 헤더 라벨 → 이 모듈이 쓰는 필드. 라벨은 문서마다 대소문자·공백이 흔들린다.
_LABEL_FIELDS = {
    "version": ("version", "버전"),
    "date": ("date", "일자", "날짜"),
    "description": ("description", "설명", "변경내용", "내용"),
    "author": ("author", "작성자"),
}


def _norm(v: Any) -> str:
    return str(v or "").strip().lower().replace(" ", "").replace("\n", "")


def find_history_columns(ws: Any, max_scan_rows: int = 12) -> Dict[str, Any]:
    """헤더 행을 찾아 `{field: col}` + `header_row` 를 돌려준다. 못 찾으면 빈 dict."""
    for r in range(1, max_scan_rows + 1):
        found: Dict[str, int] = {}
        for c in range(1, 16):
            label = _norm(ws.cell(row=r, column=c).value)
            if not label:
                continue
            for field, aliases in _LABEL_FIELDS.items():
                if field in found:
                    continue
                if any(label == _norm(a) for a in aliases):
                    found[field] = c
        # Version 과 Date 가 같은 행에 있으면 그게 헤더다.
        if "version" in found and "date" in found:
            found_any: Dict[str, Any] = dict(found)
            found_any["header_row"] = r
            return found_any
    return {}


# 이력 행의 Version 칸은 `v1.02` · `1.02` · `V0.10` 같은 모양이다.
_VERSION_RE = re.compile(r"^v?\d+\.\d+$", re.I)


def _last_history_row(ws: Any, col: int, start: int, limit: int = 400) -> int:
    """마지막 **이력** 행. 값이 있는 마지막 행이 아니다.

    ⚠ 정본 History 시트 78행에 `<End of Document>` 가 있다. "값이 있는 마지막 행" 으로
      찾으면 그걸 마지막 이력으로 오인하고, 버전 파싱에 실패해 이력이 **한 줄도
      안 붙는다**(실제로 그렇게 동작했다). 버전 모양인 행만 센다.
    """
    last = start
    for r in range(start + 1, start + limit):
        if _VERSION_RE.match(str(ws.cell(row=r, column=col).value or "").strip()):
            last = r
    return last


def _bump(version: str) -> str:
    """`v1.02` → `v1.03`. 형식을 못 읽으면 원본을 그대로 돌려준다(지어내지 않는다)."""
    raw = str(version or "").strip()
    m = re.match(r"^(v?)(\d+)\.(\d+)$", raw, re.I)
    if not m:
        return raw
    prefix, major, minor = m.group(1), m.group(2), m.group(3)
    return f"{prefix}{major}.{int(minor) + 1:0{len(minor)}d}"


def append_history_row(
    wb: Any,
    *,
    version: str = "",
    description: str = "",
    author: str = "",
    today: Optional[str] = None,
) -> Optional[str]:
    """마지막 이력 다음 행에 이번 개정을 적는다. 적은 버전 문자열 또는 `None`.

    Args:
        version: 이번 문서 버전. 비면 **마지막 이력의 다음 버전**으로 올린다.
        description: 변경 설명. 비면 자동 생성.
    """
    try:
        name = next((n for n in _HISTORY_SHEETS if n in wb.sheetnames), "")
        if not name:
            return None
        ws = wb[name]
        cols = find_history_columns(ws)
        if not cols:
            _logger.info("history: 헤더(Version/Date)를 못 찾아 이력을 덧붙이지 않는다")
            return None

        hdr = int(cols["header_row"])
        vcol = int(cols["version"])
        last = _last_history_row(ws, vcol, hdr)
        prev_version = str(ws.cell(row=last, column=vcol).value or "").strip() if last > hdr else ""

        new_version = str(version or "").strip() or _bump(prev_version) or "v1.00"
        if prev_version and _norm(prev_version) == _norm(new_version):
            # 재생성마다 같은 행이 쌓이면 이력이 아니라 로그가 된다.
            _logger.info("history: 마지막 행이 이미 %s — 덧붙이지 않는다", new_version)
            return None

        row = last + 1
        ws.cell(row=row, column=vcol, value=new_version)
        if "date" in cols:
            ws.cell(row=row, column=int(cols["date"]), value=today or date.today().strftime("%y.%m.%d"))
        if "description" in cols:
            ws.cell(
                row=row, column=int(cols["description"]),
                value=description or "- 자동 생성 (소스/설계 문서 기준 재작성)",
            )
        if author and "author" in cols:
            ws.cell(row=row, column=int(cols["author"]), value=author)
        _logger.info("history: %s 행 추가 (row=%d, 이전=%s)", new_version, row, prev_version or "없음")
        return new_version
    except Exception as exc:  # noqa: BLE001 — 이력 실패가 문서 생성을 막으면 안 된다
        _logger.warning("history: 행 추가 실패 — %s", exc)
        return None
