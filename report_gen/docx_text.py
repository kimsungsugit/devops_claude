"""python-docx 의 텍스트 접근자와 **같은 문자열**을 xpath 없이 낸다. (R55 N27-c)

`_Cell.text` → `Paragraph.text` → `CT_P.text` 는 문단마다 `xpath("w:r | w:hyperlink")` 를, 런마다
`xpath("w:br | w:cr | w:noBreakHyphen | w:ptab | w:t | w:tab")` 를 새로 평가한다. 60MB 산출물(함수 표 989개 ·
셀 16만 개)을 한 번 걷는 데 xpath 32만 회 = 9.4초 / 12초(cProfile 실측 2026-09-17), 후처리는 그 걷기를 네 번 했다.

여기 세 함수는 python-docx 1.2.0 의 규칙을 그대로 옮긴 것이다 — 규칙이 하나라도 다르면 정본 되읽기
(`requirements._extract_function_info_from_docx`, ASIL·Related 의 출처)가 달라진다:
  · 셀   = 직속 `w:p` 들을 "\\n" 으로 잇는다(중첩 표 안 문단은 제외 — `CT_Tc.p_lst` 와 같다)
  · 문단 = 직속 `w:r` 와 `w:hyperlink`(그 직속 `w:r`)를 문서 순서대로 잇는다(`w:ins`·`w:sdt` 안 런은 python-docx 도 안 본다)
  · 런   = 직속 자식 중 `w:t` 본문 · `w:tab`/`w:ptab` "\\t" · `w:cr` "\\n" · `w:br` 는 `w:type` 이 없거나 textWrapping 이면
           "\\n", page/column 이면 "" · `w:noBreakHyphen` "-" · 그 밖(`w:rPr`·`w:drawing`·`w:sym`·`w:footnoteReference`…)은 ""
가드: `tests/unit/test_uds_postprocess_readback.py::TestFastTextMatchesPythonDocx` 가 변형별로 `cell.text` 와 대조하고,
착수 실측은 산출물(60MB)·정본 v3.03 의 **모든 셀**에서 두 값이 같음을 확인했다(계획서 R55).
"""
from __future__ import annotations

from typing import Any, List

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = f"{{{_W}}}p"
_R = f"{{{_W}}}r"
_HYPERLINK = f"{{{_W}}}hyperlink"
_T = f"{{{_W}}}t"
_TAB = f"{{{_W}}}tab"
_PTAB = f"{{{_W}}}ptab"
_BR = f"{{{_W}}}br"
_CR = f"{{{_W}}}cr"
_NO_BREAK_HYPHEN = f"{{{_W}}}noBreakHyphen"
_BR_TYPE = f"{{{_W}}}type"


def run_text(r: Any) -> str:
    """`CT_R.text` 와 같은 값. `r` 은 `w:r` 요소(또는 `_r` 을 가진 Run 래퍼)."""
    el = getattr(r, "_r", r)
    parts: List[str] = []
    for e in el:
        tag = e.tag
        if tag == _T:
            parts.append(e.text or "")
        elif tag == _TAB or tag == _PTAB:
            parts.append("\t")
        elif tag == _CR:
            parts.append("\n")
        elif tag == _BR:
            parts.append("\n" if (e.get(_BR_TYPE) or "textWrapping") == "textWrapping" else "")
        elif tag == _NO_BREAK_HYPHEN:
            parts.append("-")
    return "".join(parts)


def paragraph_text(p: Any) -> str:
    """`CT_P.text`(= `Paragraph.text`) 와 같은 값. `p` 는 `w:p` 요소(또는 `_p` 를 가진 Paragraph 래퍼)."""
    el = getattr(p, "_p", p)
    parts: List[str] = []
    for e in el:
        tag = e.tag
        if tag == _R:
            parts.append(run_text(e))
        elif tag == _HYPERLINK:
            for r in e:
                if r.tag == _R:
                    parts.append(run_text(r))
    return "".join(parts)


def cell_text(cell: Any) -> str:
    """`_Cell.text` 와 같은 값. `cell` 은 `w:tc` 요소(또는 `_tc` 를 가진 _Cell 래퍼)."""
    tc = getattr(cell, "_tc", cell)
    return "\n".join(paragraph_text(p) for p in tc if p.tag == _P)
