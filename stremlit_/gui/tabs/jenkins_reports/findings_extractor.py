# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


def _read_tail(path: Path, max_bytes: int = 2 * 1024 * 1024) -> str:
    try:
        if not path or not path.exists():
            return ""
        sz = path.stat().st_size
        if sz <= max_bytes:
            return path.read_text(encoding="utf-8", errors="ignore")
        with path.open("rb") as f:
            f.seek(max(0, sz - max_bytes))
            data = f.read(max_bytes)
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return data.decode(errors="ignore")
    except Exception:
        return ""


def _iter_candidate_text_files(broot: Optional[Path], rdir: Optional[Path]) -> List[Path]:
    """룰 위반/컴파일 에러 후보 로그 파일 수집.
    - reports/ 아래 및 report/ 아래는 재귀 탐색
    - 너무 많은 파일로 느려지는 것을 방지하기 위해 상한 적용
    """
    cands: List[Path] = []
    bases: List[Path] = []
    if rdir:
        bases.append(rdir)
    if broot:
        bases.append(broot / "reports")
        bases.append(broot / "report")
        bases.append(broot)

    preferred = ("jenkins_console.log", "system.log", "pipeline.log", "build.log", "compile.log", "static.log")
    for b in bases:
        if not b or not b.exists():
            continue
        for name in preferred:
            p = b / name
            if p.exists():
                cands.append(p)

    # 재귀 후보(상한)
    def add_rglob(base: Path, pats: Tuple[str, ...], limit: int = 120) -> None:
        if not base.exists():
            return
        n = 0
        for pat in pats:
            for p in base.rglob(pat):
                if p.is_file():
                    cands.append(p)
                    n += 1
                    if n >= limit:
                        return

    for b in bases:
        if not b or not b.exists():
            continue
        bn = b.name.lower()
        # 루트(broot)에서 전부 rglob하면 너무 커질 수 있어 reports/report 위주로
        if bn in ("reports", "report") or (rdir and b.resolve() == rdir.resolve()):
            add_rglob(b, ("*.log", "*.txt", "*.out"), limit=220)
        else:
            cands.extend(sorted(list(b.glob("*.log"))))
            cands.extend(sorted(list(b.glob("*.txt"))))
            cands.extend(sorted(list(b.glob("*.out"))))

    # dedup
    seen: set[str] = set()
    uniq: List[Path] = []
    for p in cands:
        sp = str(p)
        if sp in seen:
            continue
        seen.add(sp)
        uniq.append(p)
    return uniq


def _normalize_severity(x: str) -> str:
    s = (x or "").strip().lower()
    if s in ("fatal", "error", "err"):
        return "error"
    if s in ("warning", "warn"):
        return "warning"
    if s in ("note", "info", "information"):
        return "info"
    return s or "warning"


# 대표적인 컴파일러/정적분석 출력 패턴들
_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("clang", re.compile(r'^(?P<file>[^:\s].*?):(?P<line>\d+):(?P<col>\d+):\s*(?P<sev>warning|error|note):\s*(?P<msg>.*?)(?:\s*\[(?P<rule>[^\]]+)\])?\s*$')),
    ("gcc", re.compile(r'^(?P<file>[^:\s].*?):(?P<line>\d+):\s*(?P<sev>warning|error|note):\s*(?P<msg>.*?)(?:\s*\[(?P<rule>[^\]]+)\])?\s*$')),
    ("cppcheck", re.compile(r'^\[(?P<file>.+?):(?P<line>\d+)\]:\s*(?P<sev>\w+):\s*(?P<msg>.*?)(?:\s*\[(?P<rule>[^\]]+)\])?\s*$')),
    ("msvc", re.compile(r'^(?P<file>.+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*(?P<sev>warning|error)\s*(?P<rule>[A-Za-z]+\d+)?:?\s*(?P<msg>.*)$')),
    ("prqa", re.compile(r'^(?P<file>.+?)\((?P<line>\d+)\)\s*:\s*(?P<msg>.*)$')),
]


def _extract_findings_from_text(text: str, tool_hint: str = "", max_items: int = 2000) -> List[Dict[str, Any]]:
    if not text:
        return []
    items: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for ln in text.splitlines():
        line = ln.strip()
        if not line:
            continue
        for tool_name, pat in _PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            gd = m.groupdict()
            f = (gd.get("file") or "").strip()
            if not f:
                continue
            # 소스 파일 확장자 힌트가 없으면 너무 많은 로그가 잡힐 수 있으므로 최소 필터
            if not re.search(r'\.(c|h|cpp|hpp|cxx|cc|ino|s)$', f, re.IGNORECASE):
                # 그래도 clang/gcc는 잡을 수 있으니, 경로 느낌일 때만 허용
                if "/" not in f and "\\" not in f:
                    continue
            line_no = int(gd.get("line") or 0)
            col_no = int(gd.get("col") or 0) if (gd.get("col") or "").isdigit() else 0
            sev = _normalize_severity(gd.get("sev") or "warning")
            rule = (gd.get("rule") or "").strip()
            msg = (gd.get("msg") or gd.get("message") or "").strip()
            if not msg:
                msg = (gd.get("msg") or "").strip()
            key = (tool_name, f, line_no, col_no, rule, msg)
            if key in seen:
                break
            seen.add(key)
            items.append(
                {
                    "tool": tool_hint or tool_name,
                    "severity": sev,
                    "rule": rule,
                    "file": f,
                    "line": line_no,
                    "col": col_no,
                    "message": msg,
                    "kind": tool_name,
                }
            )
            break
        if len(items) >= max_items:
            break
    return items


def _iter_prqa_html_candidates(broot: Optional[Path], rdir: Optional[Path]) -> List[Path]:
    """PRQA/리포트 HTML 후보 수집.
    - reports/ 및 report/ 아래는 재귀 탐색(상한 적용)
    """
    cands: List[Path] = []
    bases: List[Path] = []
    if rdir:
        bases.append(rdir)
    if broot:
        bases.append(broot / "reports")
        bases.append(broot / "report")
        bases.append(broot)

    def add_glob(base: Path) -> None:
        if base.exists():
            cands.extend(sorted(list(base.glob("*.html"))))

    def add_rglob(base: Path, limit: int = 180) -> None:
        if not base.exists():
            return
        n = 0
        for p in base.rglob("*.html"):
            if p.is_file():
                cands.append(p)
                n += 1
                if n >= limit:
                    break

    for b in bases:
        if not b or not b.exists():
            continue
        bn = b.name.lower()
        if bn in ("reports", "report") or (rdir and b.resolve() == rdir.resolve()):
            add_rglob(b, limit=260)
        else:
            add_glob(b)

    def score(p: Path) -> int:
        n = p.name.upper()
        sc = 0
        if "RCR" in n:
            sc += 30
        if "CRR" in n:
            sc += 25
        if "PRQA" in n or "QAC" in n:
            sc += 20
        if "REPORT" in n:
            sc += 5
        return -sc

    cands.sort(key=score)
    seen = set()
    uniq: List[Path] = []
    for p in cands:
        sp = str(p)
        if sp in seen:
            continue
        seen.add(sp)
        uniq.append(p)
    return uniq


def _iter_qac_sur_html_candidates(broot: Optional[Path], rdir: Optional[Path]) -> List[Path]:
    cands = _iter_prqa_html_candidates(broot, rdir)
    out: List[Path] = []
    for p in cands:
        name = p.name.upper()
        if "SUR" in name or "SUP" in name:
            out.append(p)
    return out


def _extract_findings_from_qac_sur_html(html_path: Path, max_items: int = 2000) -> List[Dict[str, Any]]:
    if not html_path or not html_path.exists():
        return []
    txt = html_path.read_text(encoding="utf-8", errors="ignore")
    if not txt:
        return []

    items: List[Dict[str, Any]] = []
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(txt, "html.parser")
            tables = soup.find_all("table")
            for t in tables:
                rows = t.find_all("tr")
                if not rows:
                    continue
                header_cells = rows[0].find_all(["th", "td"])
                header = [c.get_text(" ", strip=True).lower() for c in header_cells]
                if not header:
                    continue

                def find_idx(keys: List[str]) -> int:
                    for i, h in enumerate(header):
                        for k in keys:
                            if k in h:
                                return i
                    return -1

                i_msg = find_idx(["message"])
                i_sev = find_idx(["severity"])
                i_line = find_idx(["line"])
                if i_msg < 0 or i_sev < 0:
                    continue

                last_msg = ""
                last_sev = ""
                last_line = 0
                for r in rows[1:]:
                    cells = r.find_all(["td", "th"])
                    if not cells:
                        continue
                    vals = [c.get_text(" ", strip=True) for c in cells]
                    msg_val = (vals[i_msg] or "").strip() if i_msg < len(vals) else ""
                    sev_val = (vals[i_sev] or "").strip() if i_sev < len(vals) else ""
                    line_val = (vals[i_line] or "").strip() if (i_line >= 0 and i_line < len(vals)) else ""

                    if msg_val:
                        last_msg = msg_val
                    if sev_val:
                        last_sev = sev_val
                    if line_val and line_val.isdigit():
                        last_line = int(line_val)

                    file_path = ""
                    file_line = 0
                    for c in cells:
                        a = c.find("a")
                        if not a:
                            continue
                        href = a.get("href") or ""
                        title = a.get("title") or ""
                        text_val = a.get_text(" ", strip=True)
                        m_file = re.search(r"([^/\\]+\.(?:c|h|cpp|hpp|cxx|cc))", title or href or text_val, re.IGNORECASE)
                        if not m_file:
                            continue
                        file_path = title or href or text_val
                        cell_text = c.get_text(" ", strip=True)
                        m_line = re.search(r":\s*(\d+)", cell_text)
                        if m_line:
                            file_line = int(m_line.group(1))
                        break

                    if not file_path:
                        continue

                    rule = last_msg or ""
                    if not rule:
                        m_rule = re.search(r"\b(\d{3,4})\b", " ".join(vals))
                        if m_rule:
                            rule = f"qac-{m_rule.group(1)}"

                    use_line = file_line if file_line > 0 else last_line
                    if use_line <= 0:
                        use_line = 0

                    items.append(
                        {
                            "tool": "qac_sur",
                            "severity": last_sev or "warning",
                            "rule": rule,
                            "file": file_path,
                            "line": use_line,
                            "col": 0,
                            "message": f"Helix QAC suppression report ({rule})" if rule else "Helix QAC suppression report",
                            "kind": "qac_sur_html",
                        }
                    )
                    if len(items) >= max_items:
                        break
                if len(items) >= max_items:
                    break
        except Exception:
            items = []

    if items:
        return items[:max_items]

    patt = re.compile(
        r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<fname>[^<]+?\.(?:c|h|cpp|hpp|cxx|cc))</a>\s*:(?P<line>\d+)',
        re.IGNORECASE,
    )
    for m in patt.finditer(txt):
        fname = m.group("fname").strip()
        href = m.group("href").strip()
        line_no = int(m.group("line"))
        back = txt[max(0, m.start() - 400) : m.start()]
        rule = ""
        m_rule = re.search(r"qac-\d{3,4}", back, re.IGNORECASE)
        if m_rule:
            rule = m_rule.group(0).lower()
        items.append(
            {
                "tool": "qac_sur",
                "severity": "warning",
                "rule": rule,
                "file": href or fname,
                "line": line_no,
                "col": 0,
                "message": f"Helix QAC suppression report ({rule})" if rule else "Helix QAC suppression report",
                "kind": "qac_sur_html",
            }
        )
        if len(items) >= max_items:
            break
    return items[:max_items]


def _extract_findings_from_prqa_html(html_path: Path, max_items: int = 1500) -> List[Dict[str, Any]]:
    if not html_path or not html_path.exists():
        return []
    txt = html_path.read_text(encoding="utf-8", errors="ignore")
    if not txt:
        return []
    items: List[Dict[str, Any]] = []
    # 1) BeautifulSoup 기반, "File/Line/Rule/Message" 형태 테이블 탐색
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(txt, "html.parser")
            tables = soup.find_all("table")
            for t in tables:
                rows = t.find_all("tr")
                if not rows:
                    continue
                # header 파악
                header_cells = rows[0].find_all(["th", "td"])
                header = [c.get_text(" ", strip=True).lower() for c in header_cells]
                if not header:
                    continue

                def find_idx(keys: List[str]) -> int:
                    for i, h in enumerate(header):
                        for k in keys:
                            if k in h:
                                return i
                    return -1

                i_file = find_idx(["file", "filename", "소스", "파일"])
                i_line = find_idx(["line", "ln", "행"])
                i_msg = find_idx(["message", "diagnostic", "description", "설명", "메시지"])
                i_rule = find_idx(["rule", "misra", "qac", "id", "규칙", "룰"])
                if i_file < 0 or i_line < 0:
                    continue
                for r in rows[1:]:
                    cells = r.find_all(["td", "th"])
                    if not cells:
                        continue
                    vals = [c.get_text(" ", strip=True) for c in cells]
                    if i_file >= len(vals) or i_line >= len(vals):
                        continue
                    f = (vals[i_file] or "").strip()
                    # 링크가 있으면 href에서 파일명을 우선 추출
                    try:
                        a = cells[i_file].find("a") if i_file < len(cells) else None
                        href = (a.get("href") or "") if a else ""
                        m_f = re.search(r"([^/\\]+\.(?:c|h|cpp|hpp|cxx|cc))", href, re.IGNORECASE)
                        if m_f:
                            f = m_f.group(1)
                    except Exception:
                        pass
                    ln = (vals[i_line] or "").strip()
                    if not re.search(r'\.(c|h|cpp|hpp|cxx|cc|ino|s)$', f, re.IGNORECASE):
                        continue
                    m_ln = re.search(r"\d+", ln)
                    if not m_ln:
                        continue
                    line_no = int(m_ln.group(0))
                    msg = ""
                    if 0 <= i_msg < len(vals):
                        msg = (vals[i_msg] or "").strip()
                    rule = ""
                    if 0 <= i_rule < len(vals):
                        rule = (vals[i_rule] or "").strip()
                    if not msg:
                        msg = f"PRQA diagnostics from {html_path.name}"
                    items.append(
                        {
                            "tool": "prqa",
                            "severity": "warning",
                            "rule": rule,
                            "file": f,
                            "line": line_no,
                            "col": 0,
                            "message": msg,
                            "kind": "prqa_html",
                        }
                    )
                    if len(items) >= max_items:
                        break
                if len(items) >= max_items:
                    break
        except Exception:
            items = []

    if items:
        return items[:max_items]

    # 2) Regex fallback, "path(line)" or "path:line" 패턴 추출
    patt = re.compile(r'(?P<file>(?:[A-Za-z]:)?[\\/][^\s"<]+?\.(?:c|h|cpp|hpp|cxx|cc))\s*(?:\(|:)(?P<line>\d+)', re.IGNORECASE)
    seen = set()
    for m in patt.finditer(txt):
        f = m.group("file").strip()
        line_no = int(m.group("line"))
        key = (f, line_no)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "tool": "prqa",
                "severity": "warning",
                "rule": "",
                "file": f,
                "line": line_no,
                "col": 0,
                "message": f"PRQA diagnostic reference in {html_path.name}",
                "kind": "prqa_html",
            }
        )
        if len(items) >= max_items:
            break
    return items[:max_items]


__all__ = [
    "_read_tail",
    "_iter_candidate_text_files",
    "_normalize_severity",
    "_extract_findings_from_text",
    "_iter_prqa_html_candidates",
    "_iter_qac_sur_html_candidates",
    "_extract_findings_from_qac_sur_html",
    "_extract_findings_from_prqa_html",
]
