# -*- coding: utf-8 -*-
"""
Jenkins -> DevOps Pro GUI adapter

목표
- Jenkins에서 내려받은 build_root(아티팩트 폴더)를 스캔
- GUI가 읽는 최소 산출물 생성/정규화
  * reports_dir/analysis_summary.json
  * reports_dir/status.json
  * reports_dir/jenkins_scan.json
  * reports_dir/complexity.csv (VectorCAST metrics 기반)
- Jenkins Dashboard/Reports 탭에서 바로 쓸 수 있는 요약 지표 확장
  * VectorCAST(UT/IT) Full/Metrics/Environment 리포트 파싱
  * PRQA(QAC) CRR/RCR HTML 요약 파싱
  * PRQA HIS Metrics(XLSX) 요약(상위 복잡도 함수 목록 등)

파서 정책
- HTML: BeautifulSoup(bs4) 우선 사용
- pandas는 선택(optional)로만 사용 (csv/xlsx 편의)
"""

from __future__ import annotations

import csv
import shutil
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

def _norm_rate_0_1(value: Any) -> float:
    """Normalize rate that may be 0..1 or 0..100 (percent).
    Returns a float, clamped to >=0.
    """
    try:
        v = float(value)
    except Exception:
        return 0.0
    if v <= 1.0:
        return max(0.0, v)
    if v <= 100.0:
        return max(0.0, v / 100.0)
    if v <= 10000.0:
        return max(0.0, v / 10000.0)
    return max(0.0, v)


# -----------------------------------------------------------------------------
# IO helpers
# -----------------------------------------------------------------------------

def _write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_text_safe(path: Path, *, max_bytes: int = 2_000_000) -> str:
    """
    큰 파일(로그/HTML) 파싱 방어
    """
    path = Path(path)
    try:
        with path.open("rb") as f:
            raw = f.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(text: str) -> str:
    import html.parser  # type: ignore

    class _TextExtractor(html.parser.HTMLParser):  # type: ignore
        def __init__(self):
            super().__init__()
            self.parts: List[str] = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() in ("br", "p", "li"):
                self.parts.append("\\n")

        def handle_endtag(self, tag):
            if tag.lower() in ("p", "li"):
                self.parts.append("\\n")

        def handle_data(self, data):
            self.parts.append(data)

    parser = _TextExtractor()
    parser.feed(text)
    raw = "".join(parser.parts)
    raw = raw.replace("\\r", "")
    raw = raw.replace("\\t", " ").replace("\\f", " ").replace("\\v", " ")
    raw = re.sub(r"[ ]+", " ", raw)
    raw = re.sub(r"\\n\\s+", "\\n", raw)
    return raw.strip()


def _extract_tables_html(text: str) -> List[List[List[str]]]:
    import html.parser  # type: ignore

    class _TableParser(html.parser.HTMLParser):  # type: ignore
        def __init__(self):
            super().__init__()
            self.in_table = False
            self.in_tr = False
            self.in_cell = False
            self.tables: List[List[List[str]]] = []
            self.cur_rows: List[List[str]] = []
            self.cur_row: List[str] = []
            self._buf: List[str] = []

        def handle_starttag(self, tag, attrs):
            t = tag.lower()
            if t == "table":
                self.in_table = True
                self.cur_rows = []
            elif t == "tr" and self.in_table:
                self.in_tr = True
                self.cur_row = []
            elif t in ("th", "td") and self.in_tr:
                self.in_cell = True
                self._buf = []

        def handle_endtag(self, tag):
            t = tag.lower()
            if t in ("th", "td") and self.in_cell:
                text = re.sub(r"\\s+", " ", "".join(self._buf)).strip()
                self.cur_row.append(text)
                self.in_cell = False
            elif t == "tr" and self.in_tr:
                if self.cur_row:
                    self.cur_rows.append(self.cur_row)
                self.in_tr = False
                self.cur_row = []
            elif t == "table" and self.in_table:
                if self.cur_rows:
                    self.tables.append(self.cur_rows)
                self.in_table = False
                self.cur_rows = []

        def handle_data(self, data):
            if self.in_cell:
                self._buf.append(data)

    parser = _TableParser()
    parser.feed(text)
    return parser.tables


def _table_kv(rows: List[List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        key = (row[0] or "").strip()
        val = (row[1] or "").strip()
        if key:
            out[key] = val
    return out


def _split_h2_sections(text: str) -> List[Tuple[str, str]]:
    parts = re.split(r"(?is)<h2[^>]*>(.*?)</h2>", text)
    out: List[Tuple[str, str]] = []
    if len(parts) < 2:
        return out
    for i in range(1, len(parts), 2):
        title = re.sub(r"(?is)<[^>]+>", "", parts[i]).strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out.append((title, body))
    return out


def _extract_h4_section(text: str, heading: str) -> str:
    pat = rf"(?is)<h4[^>]*>\s*{re.escape(heading)}\s*</h4>(.*?)(?=<h4[^>]*>|<h2[^>]*>|$)"
    m = re.search(pat, text)
    if not m:
        return ""
    return _strip_html(m.group(1))


# -----------------------------------------------------------------------------
# Basic scan
# -----------------------------------------------------------------------------

_KPI_PATTERNS = {
    "FAIL_token": re.compile(r"\bFAIL\b", re.IGNORECASE),
    "ERROR_token": re.compile(r"\bERROR\b", re.IGNORECASE),
    "WARN_token": re.compile(r"\bWARN(ING)?\b", re.IGNORECASE),
    "PASS_token": re.compile(r"\bPASS\b", re.IGNORECASE),
}

_TEXT_EXTS_LOG = (
    ".log", ".txt", ".out", ".err", ".stdout", ".stderr",
    ".md", ".rst", ".json", ".xml", ".yml", ".yaml",
)


def discover_source_roots(build_root: Path, max_candidates: int = 8) -> List[str]:
    """
    build_root 아래에서 '소스 루트'로 보이는 디렉터리 후보를 추정
    - 프로젝트(잡)/빌드번호에 따라 build_root 하위 구조가 달라질 수 있으므로
      고정 경로를 가정하지 않고 동적으로 탐색
    - 반환: build_root 기준 상대경로(posix), 점수 높은 순
    """
    build_root = Path(build_root)

    try:
        js = _read_json(build_root / "reports" / "jenkins_scan.json")
        roots = (js.get("source_roots") or []) if isinstance(js, dict) else []
        out = []
        for rel in roots:
            try:
                p = (build_root / str(rel)).resolve()
                if p.exists() and p.is_dir():
                    out.append(str(p.relative_to(build_root)).replace("\\", "/"))
            except Exception:
                continue
        if out:
            return out[:max_candidates]
    except Exception:
        pass

    build_root = Path(build_root)

    # 빠른 경로(자주 나오는 구조) 우선
    # - 프로젝트/잡에 따라 workspace를 통째로 artifact로 올리거나
    #   svn checkout(root=svn_wc) 형태로 올리는 경우가 있어
    #   app/* 와 svn_wc/* 양쪽을 모두 우선 후보로 둠
    quick = [
        # 예: build_300/app/PDSM/Sources/AP/Buzzer/...
        build_root / "app" / "PDSM" / "Sources",
        build_root / "app" / "PDSM" / "Sources" / "APP",
        build_root / "app" / "PDSM" / "Sources" / "AP",
        # 예: build_26/svn_wc/Sources/APP/...
        build_root / "svn_wc" / "Sources",
        build_root / "svn_wc" / "Sources" / "APP",
        build_root / "svn_wc" / "Sources" / "AP",
        # 기타
        build_root / "PDSM" / "Sources",
        build_root / "Sources",
        build_root / "src",
        build_root / "source",
    ]
    cand_dirs: List[Path] = [p for p in quick if p.exists() and p.is_dir()]

    # Walk 탐색(이름 패턴 기반 후보 수집)
    name_hits = {"sources", "source", "src"}
    skip_dirs = {".git", ".svn", ".hg", "reports", "build", "out", "dist", "__pycache__", ".devops_pro_cache"}
    max_walk_dirs = 20000  # 안전 장치

    walked = 0
    for root, dirs, files in os.walk(build_root):
        walked += 1
        if walked > max_walk_dirs:
            break

        # prune
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

        rpath = Path(root)
        dname = rpath.name.lower()
        if dname in name_hits:
            cand_dirs.append(rpath)
            continue

        # '.../PDSM/Sources' 형태도 후보로 가중
        if len(rpath.parts) >= 2 and rpath.parts[-2].lower() == "pdsm" and rpath.parts[-1].lower() == "sources":
            cand_dirs.append(rpath)

    # 중복 제거
    uniq: Dict[str, Path] = {}
    for p in cand_dirs:
        try:
            rel = str(p.relative_to(build_root)).replace("\\", "/")
        except Exception:
            continue
        uniq[rel] = p

    # 점수 계산
    src_exts = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"}
    def score_dir(p: Path) -> Tuple[int, int, int]:
        # (src_file_count, has_build_files, depth_penalty)
        cnt = 0
        try:
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in src_exts:
                    cnt += 1
                    if cnt >= 5000:
                        break
        except Exception:
            pass

        has_build = 0
        for fn in ("CMakeLists.txt", "Makefile", "meson.build", "BUILD", "build.gradle"):
            if (p / fn).exists():
                has_build = 1
                break

        depth = len(str(p.relative_to(build_root)).replace("\\", "/").split("/"))
        return (cnt, has_build, -depth)

    scored: List[Tuple[Tuple[int,int,int], str]] = []
    for rel, p in uniq.items():
        s = score_dir(p)
        # 소스 파일이 거의 없는 'src' 폴더는 제외(노이즈)
        if s[0] < 5 and s[1] == 0:
            continue
        scored.append((s, rel))

    scored.sort(key=lambda x: (x[0][0], x[0][1], x[0][2]), reverse=True)
    return [rel for _, rel in scored[:max_candidates]]


def scan_jenkins_build_root(build_root: Path) -> Dict[str, Any]:
    """
    build_root 아래 파일 스캔
    - html/xlsx/log 목록
    - KPI 토큰 간이 카운트(FAIL/ERROR/WARN/PASS)
    - 확장자 분포(ext_counts) + 총 용량(bytes_total)

    주의
    - 대용량 로그는 max_bytes로 상한
    """
    build_root = Path(build_root)

    html_files: List[str] = []
    xlsx_files: List[str] = []
    log_files: List[str] = []
    other_files: List[str] = []

    kpis_by_file: Dict[str, Dict[str, int]] = {}
    ext_counts: Dict[str, int] = {}
    bytes_total = 0

    MAX_BYTES_HTML = 800_000
    MAX_BYTES_LOG = 2_000_000

    for p in build_root.rglob("*"):
        if not p.is_file():
            continue

        try:
            bytes_total += int(p.stat().st_size)
        except Exception:
            pass

        rel = str(p.relative_to(build_root)).replace("\\", "/")
        low = rel.lower()
        ext = (p.suffix.lower() or "").lstrip(".")
        if ext:
            ext_counts[ext] = int(ext_counts.get(ext, 0)) + 1
        else:
            ext_counts["(no_ext)"] = int(ext_counts.get("(no_ext)", 0)) + 1

        if low.endswith((".html", ".htm")):
            html_files.append(rel)
            txt = _read_text_safe(p, max_bytes=MAX_BYTES_HTML)
            kpis = {k: 0 for k in _KPI_PATTERNS}
            for k, rx in _KPI_PATTERNS.items():
                try:
                    kpis[k] = len(rx.findall(txt))
                except Exception:
                    kpis[k] = 0
            kpis_by_file[rel] = kpis

        elif low.endswith((".xlsx", ".xlsm", ".xls")):
            xlsx_files.append(rel)

        elif low.endswith(_TEXT_EXTS_LOG):
            log_files.append(rel)
            txt = _read_text_safe(p, max_bytes=MAX_BYTES_LOG)
            kpis = {k: 0 for k in _KPI_PATTERNS}
            for k, rx in _KPI_PATTERNS.items():
                try:
                    kpis[k] = len(rx.findall(txt))
                except Exception:
                    kpis[k] = 0
            kpis_by_file[rel] = kpis

        else:
            other_files.append(rel)

    html_files.sort()
    xlsx_files.sort()
    log_files.sort()
    other_files.sort()

    # 전체 카운트 요약
    fail_total = sum(k.get("FAIL_token", 0) for k in kpis_by_file.values())
    error_total = sum(k.get("ERROR_token", 0) for k in kpis_by_file.values())
    warn_total = sum(k.get("WARN_token", 0) for k in kpis_by_file.values())
    pass_total = sum(k.get("PASS_token", 0) for k in kpis_by_file.values())

    
    # source root candidates (relative to build_root)
    # - 일부 Jenkins job은 아티팩트로 전체 소스 트리를 포함(svn_wc/**, app/** 등)
    # - 리포트가 절대경로/축약 경로를 섞어 내보내는 경우가 많아, GUI(Editor)에서 탐색 루트로 사용
    source_roots = discover_source_roots(build_root)
    return {
        "root": str(build_root),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "source_roots": source_roots,
        "files": {
            "html": html_files,
            "xlsx": xlsx_files,
            "log": log_files,
            "other": other_files,
        },
        "kpis_by_file": kpis_by_file,
        "summary": {
            "files_total": int(len(html_files) + len(xlsx_files) + len(log_files) + len(other_files)),
            "bytes_total": int(bytes_total),
            "ext_counts": dict(sorted(ext_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "html_count": len(html_files),
            "xlsx_count": len(xlsx_files),
            "log_count": len(log_files),
            "other_count": len(other_files),
            "FAIL_token": fail_total,
            "ERROR_token": error_total,
            "WARN_token": warn_total,
            "PASS_token": pass_total,
            "fail_error_tokens": int(fail_total) + int(error_total),
        },
    }


_RUNTIME_PATTERNS = {
    "asan": re.compile(r"AddressSanitizer|ASAN", re.I),
    "ubsan": re.compile(r"UndefinedBehaviorSanitizer|UBSAN|runtime error:", re.I),
    "timeout": re.compile(r"\btimeout\b|\btimed out\b", re.I),
    "assert": re.compile(r"assert(?:ion)? failed|\bASSERT\b", re.I),
    "crc_mismatch": re.compile(r"\bcrc\b.*mismatch|mismatch.*\bcrc\b", re.I),
    "hardfault": re.compile(r"\bHardFault\b|\bHard Fault\b", re.I),
    "busfault": re.compile(r"\bBusFault\b|\bBus Fault\b", re.I),
}


def _scan_runtime_summary(build_root: Path, jscan: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    logs = ((jscan.get("files") or {}).get("log") or []) if isinstance(jscan, dict) else []
    if not isinstance(logs, list) or not logs:
        return summary

    # limit log scanning to avoid heavy IO
    scan_logs = logs[:6]
    for key in _RUNTIME_PATTERNS:
        summary[key] = {"count": 0, "files": [], "samples": []}

    for rel in scan_logs:
        try:
            path = build_root / str(rel)
            txt = _read_text_safe(path, max_bytes=800_000)
        except Exception:
            continue

        for key, rx in _RUNTIME_PATTERNS.items():
            try:
                hits = rx.findall(txt)
                if not hits:
                    continue
                summary[key]["count"] = int(summary[key]["count"]) + len(hits)
                if rel not in summary[key]["files"]:
                    summary[key]["files"].append(rel)
                # collect sample lines
                if summary[key]["samples"] is not None and len(summary[key]["samples"]) < 5:
                    for line in txt.splitlines():
                        if rx.search(line):
                            summary[key]["samples"].append(line.strip()[:200])
                        if len(summary[key]["samples"]) >= 5:
                            break
            except Exception:
                continue

    # drop empty entries
    cleaned: Dict[str, Any] = {}
    for key, block in summary.items():
        try:
            if int(block.get("count", 0)) > 0:
                cleaned[key] = block
        except Exception:
            continue
    return cleaned


# -----------------------------------------------------------------------------
# Parsing helpers
# -----------------------------------------------------------------------------

def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        s = str(v).strip()
        if not s:
            return default
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else default
    except Exception:
        return default


def _parse_ratio(s: Any) -> Tuple[int, int, float]:
    """
    "69 / 79 (75%)" -> (69, 79, 0.75)
    "30/30 (100%)" -> (30, 30, 1.0)
    """
    if s is None:
        return 0, 0, 0.0
    txt = str(s).strip()
    m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
    a = int(m.group(1)) if m else 0
    b = int(m.group(2)) if m else 0
    m2 = re.search(r"\(\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*\)", txt)
    r = float(m2.group(1)) / 100.0 if m2 else (float(a) / float(b) if b > 0 else 0.0)
    return a, b, r


def _parse_hhmmss(s: Any) -> int:
    if s is None:
        return 0
    txt = str(s).strip()
    m = re.match(r"^\s*(\d+)\s*:\s*(\d+)\s*(?::\s*(\d+)\s*)?$", txt)
    if not m:
        return 0
    hh = int(m.group(1))
    mm = int(m.group(2))
    ss = int(m.group(3) or "0")
    return hh * 3600 + mm * 60 + ss


def _soup(path: Path) -> Optional[Any]:
    if BeautifulSoup is None:
        return None
    html = _read_text_safe(path, max_bytes=2_000_000)
    if not html.strip():
        return None
    return BeautifulSoup(html, "html.parser")


def _table_matrix(table) -> Tuple[List[str], List[List[str]]]:
    """
    bs4 <table> -> (headers, rows)
    - thead/th 우선
    - 헤더가 비어있으면 첫 행(td/th)을 헤더로 간주
    """
    # headers
    headers: List[str] = []
    thead = table.find("thead")
    if thead:
        tr = thead.find("tr")
        if tr:
            headers = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
    if not headers:
        # fallback: first tr
        tr = table.find("tr")
        if tr:
            headers = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]

    # normalize empty headers
    norm_headers: List[str] = []
    for i, h in enumerate(headers):
        h2 = (h or "").strip()
        if not h2:
            h2 = "NAME" if i == 0 else f"COL_{i}"
        norm_headers.append(h2)

    # body rows
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        # skip header row duplicates
        if len(cells) == len(norm_headers) and [c.strip() for c in cells] == [h.strip() for h in norm_headers]:
            continue
        # try align length
        if len(cells) < len(norm_headers):
            cells = cells + [""] * (len(norm_headers) - len(cells))
        elif len(cells) > len(norm_headers):
            cells = cells[:len(norm_headers)]
        rows.append(cells)

    # remove first row if it looks like header
    if rows and all((rows[0][i] or "").strip().upper() == (norm_headers[i] or "").strip().upper() for i in range(len(norm_headers))):
        rows = rows[1:]

    return norm_headers, rows


def _find_table_by_headers(soup_obj, required: List[str]) -> Optional[Any]:
    req = {r.strip().upper() for r in required if r and r.strip()}
    for t in soup_obj.find_all("table"):
        headers, _ = _table_matrix(t)
        hs = {h.strip().upper() for h in headers}
        if req.issubset(hs):
            return t
    return None


def _relpath_str(base: Path, path: Optional[Path]) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _summarize_jenkins_scan_md(jscan: Dict[str, Any]) -> str:
    summary = jscan.get("summary") if isinstance(jscan, dict) else {}
    files = jscan.get("files") if isinstance(jscan, dict) else {}
    root = jscan.get("root") if isinstance(jscan, dict) else ""
    scanned_at = jscan.get("scanned_at") if isinstance(jscan, dict) else ""

    lines = [
        "# Jenkins Scan Summary",
        "",
        f"- root: {root}",
        f"- scanned_at: {scanned_at}",
        f"- files_total: {summary.get('files_total', 0)}",
        f"- bytes_total: {summary.get('bytes_total', 0)}",
        f"- html_count: {summary.get('html_count', 0)}",
        f"- xlsx_count: {summary.get('xlsx_count', 0)}",
        f"- log_count: {summary.get('log_count', 0)}",
        f"- other_count: {summary.get('other_count', 0)}",
        "",
        "## File Buckets",
    ]
    for key in ("html", "xlsx", "log", "other"):
        entries = files.get(key, []) if isinstance(files, dict) else []
        lines.append(f"- {key}: {len(entries)}")
    lines.append("")
    lines.append("## Source Roots")
    for r in (jscan.get("source_roots") or []) if isinstance(jscan, dict) else []:
        lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


def _normalize_header_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip().upper()


def _map_vcast_header(name: str) -> str:
    norm = _normalize_header_name(name)
    if not norm:
        return ""
    if "REQUIREMENT" in norm or norm in ("REQ", "REQ ID", "REQ-ID", "REQID"):
        return "requirement_id"
    if "TEST SCRIPT" in norm or norm in ("SCRIPT", "TEST PROCEDURE", "PROCEDURE"):
        return "test_script"
    if "STUB" in norm:
        return "stubs"
    if norm in ("TESTCASE", "TEST CASE", "TEST NAME"):
        return "testcase"
    if norm == "UNIT":
        return "unit"
    if norm == "SUBPROGRAM":
        return "subprogram"
    if norm == "ENVIRONMENT":
        return "environment"
    if norm in ("RESULT", "STATUS", "OUTCOME"):
        return "result"
    return ""


def _extract_vcast_test_rows(path: Path, max_rows: int = 5000) -> List[Dict[str, Any]]:
    path = Path(path)
    soup_obj = _soup(path)
    if soup_obj is None:
        return []

    rows_out: List[Dict[str, Any]] = []
    for tbl in soup_obj.find_all("table"):
        headers, rows = _table_matrix(tbl)
        if not headers:
            continue
        mapped_headers = [_map_vcast_header(h) for h in headers]
        if not any(mapped_headers):
            continue
        for row in rows:
            if len(rows_out) >= max_rows:
                break
            entry: Dict[str, Any] = {}
            for idx, key in enumerate(mapped_headers):
                if not key:
                    continue
                val = row[idx] if idx < len(row) else ""
                if val:
                    entry[key] = val
            if "stubs" in entry:
                raw = str(entry.get("stubs") or "")
                entry["stubs_list"] = [x.strip() for x in re.split(r"[;,|]", raw) if x.strip()]
            if entry:
                rows_out.append(entry)
        if len(rows_out) >= max_rows:
            break
    return rows_out


def _summarize_vcast_rag_md(payload: Dict[str, Any]) -> str:
    lines = [
        "# VectorCAST RAG Summary",
        "",
        f"- build_root: {payload.get('build_root', '')}",
        f"- scanned_at: {payload.get('scanned_at', '')}",
        f"- ut_reports: {len(payload.get('ut_reports', []))}",
        f"- it_reports: {len(payload.get('it_reports', []))}",
        f"- test_rows: {payload.get('test_rows', 0)}",
        f"- testcase_details: {payload.get('testcase_details', 0)}",
        "",
        "## UT Reports",
    ]
    for p in payload.get("ut_reports", []):
        lines.append(f"- {p}")
    lines.append("")
    lines.append("## IT Reports")
    for p in payload.get("it_reports", []):
        lines.append(f"- {p}")
    lines.append("")
    return "\n".join(lines)


def _write_jenkins_scan_bundle(reports_dir: Path, jscan: Dict[str, Any]) -> None:
    bundle_dir = reports_dir / "jenkins_scan_export"
    _write_json(bundle_dir / "jenkins_scan.json", jscan)
    _write_markdown(bundle_dir / "jenkins_scan.md", _summarize_jenkins_scan_md(jscan))


def _write_vectorcast_rag_bundle(
    *,
    reports_dir: Path,
    build_root: Path,
    jscan: Dict[str, Any],
    vcast: Dict[str, Any],
    vcast_detail: Dict[str, Any],
    ut_reports: List[Path],
    it_reports: List[Path],
) -> None:
    bundle_dir = reports_dir / "vectorcast_rag"
    ut_rel = [_relpath_str(build_root, p) for p in ut_reports if p]
    it_rel = [_relpath_str(build_root, p) for p in it_reports if p]

    test_rows: List[Dict[str, Any]] = []
    for p in ut_reports:
        if p:
            for row in _extract_vcast_test_rows(p):
                row["source"] = "UT"
                row["report"] = _relpath_str(build_root, p)
                test_rows.append(row)
    for p in it_reports:
        if p:
            for row in _extract_vcast_test_rows(p):
                row["source"] = "IT"
                row["report"] = _relpath_str(build_root, p)
                test_rows.append(row)

    payload = {
        "build_root": str(build_root),
        "scanned_at": jscan.get("scanned_at") if isinstance(jscan, dict) else "",
        "ut_reports": ut_rel,
        "it_reports": it_rel,
        "vcast_summary": vcast,
        "vcast_detail": vcast_detail,
        "test_rows": test_rows,
        "test_rows_count": len(test_rows),
    }

    tc_details: List[Dict[str, Any]] = []
    tc = vcast_detail.get("testcase_data") if isinstance(vcast_detail, dict) else None
    if isinstance(tc, dict) and tc.get("ok"):
        for item in (tc.get("testcases") or []):
            if isinstance(item, dict):
                tc_details.append(item)
    payload["testcase_details"] = tc_details
    payload["testcase_details_count"] = len(tc_details)
    _write_json(bundle_dir / "vectorcast_rag.json", payload)
    _write_markdown(bundle_dir / "vectorcast_rag.md", _summarize_vcast_rag_md({
        "build_root": payload["build_root"],
        "scanned_at": payload["scanned_at"],
        "ut_reports": ut_rel,
        "it_reports": it_rel,
        "test_rows": payload["test_rows_count"],
        "testcase_details": payload.get("testcase_details_count", 0),
    }))


def _import_pandas():
    try:
        import pandas as pd  # type: ignore
        return pd
    except Exception:
        return None


# -----------------------------------------------------------------------------
# VectorCAST parsers
# -----------------------------------------------------------------------------

def parse_vcast_full_report(path: Path) -> Dict[str, Any]:
    """
    VectorCAST Manage Report (…_full_report.html)
    - "ALL" row 기반 요약
    """
    path = Path(path)
    soup_obj = _soup(path)
    if soup_obj is None:
        return {"ok": False, "reason": "bs4_missing_or_empty", "path": str(path)}

    tbl = _find_table_by_headers(soup_obj, ["TESTCASES"])
    if tbl is None:
        return {"ok": False, "reason": "no_status_table", "path": str(path)}

    headers, rows = _table_matrix(tbl)
    # normalize headers
    headers_u = [h.strip().upper() for h in headers]
    # build row dicts
    out_rows: List[Dict[str, str]] = []
    for r in rows:
        d = {headers_u[i]: (r[i] if i < len(r) else "") for i in range(len(headers_u))}
        out_rows.append(d)

    all_row = None
    # the first column is usually NAME/blank
    name_key = "NAME" if "NAME" in headers_u else headers_u[0]
    for d in out_rows:
        if str(d.get(name_key, "")).strip().upper() == "ALL":
            all_row = d
            break
    if all_row is None and out_rows:
        all_row = out_rows[0]

    row = all_row or {}
    out: Dict[str, Any] = {"ok": True, "path": str(path)}

    # build / expected / testcases / execute time
    if "BUILD" in row:
        out["build"] = str(row.get("BUILD") or "")
    if "EXPECTED" in row:
        ok_e, tot_e, r_e = _parse_ratio(row.get("EXPECTED"))
        out["expected"] = {"ok": ok_e, "total": tot_e, "rate": r_e}
    if "TESTCASES" in row:
        ok_t, tot_t, r_t = _parse_ratio(row.get("TESTCASES"))
        out["testcases"] = {"ok": ok_t, "total": tot_t, "rate": r_t}
    if "EXECUTE TIME" in row:
        out["execute_time_sec"] = _parse_hhmmss(row.get("EXECUTE TIME"))
        out["execute_time"] = str(row.get("EXECUTE TIME") or "")
    if "BUILD TIME" in row:
        out["build_time_sec"] = _parse_hhmmss(row.get("BUILD TIME"))
        out["build_time"] = str(row.get("BUILD TIME") or "")

    # coverage-like columns that can appear in full report
    for key in ("STATEMENTS", "BRANCHES", "FUNCTIONS", "FUNCTION CALLS"):
        if key in row:
            c_ok, c_tot, c_rate = _parse_ratio(row.get(key))
            out[key.lower().replace(" ", "_")] = {"covered": c_ok, "total": c_tot, "rate": c_rate}

    return out


def parse_vcast_metrics_report(path: Path) -> Dict[str, Any]:
    """
    VectorCAST Metrics Report (…_metrics_report.html)

    주의: VectorCAST HTML의 totals 행 형태가 2가지가 섞임
      - (일반) Unit 열이 비어있고 Subprogram == "TOTALS"
      - (샘플) Unit 열이 "TOTALS" / "GRAND TOTALS" 로 들어오고,
              Subprogram/Complexity 열에 숫자(개수/합계)가 들어옴

    처리
    - 현재 유닛(current_unit)을 ffill
    - Unit=="TOTALS" -> 직전 current_unit의 totals로 취급
    - Unit=="GRAND TOTALS" -> grand_totals로 취급
    """
    path = Path(path)
    soup_obj = _soup(path)
    if soup_obj is None:
        return {"ok": False, "reason": "bs4_missing_or_empty", "path": str(path)}

    tbl = _find_table_by_headers(soup_obj, ["UNIT", "SUBPROGRAM", "COMPLEXITY"])
    if tbl is None:
        return {"ok": False, "reason": "no_metrics_table", "path": str(path)}

    headers, rows = _table_matrix(tbl)
    cols = [c.strip().upper() for c in headers]

    # normalize row dicts
    dict_rows: List[Dict[str, str]] = []
    for r in rows:
        d = {cols[i]: (r[i] if i < len(r) else "") for i in range(len(cols))}
        dict_rows.append(d)

    current_unit = ""
    entries: List[Dict[str, Any]] = []
    unit_totals: Dict[str, Any] = {}
    grand_totals: Dict[str, Any] = {}

    def _collect_cov(d: Dict[str, str]) -> Dict[str, Any]:
        ft: Dict[str, Any] = {}
        ft["complexity_total"] = _to_int(d.get("COMPLEXITY"), 0)
        # coverage columns
        for col in ("STATEMENTS", "BRANCHES", "PAIRS", "FUNCTIONS", "FUNCTION CALLS"):
            if col in cols:
                a, b, rr = _parse_ratio(d.get(col))
                ft[col.lower().replace(" ", "_")] = {"covered": a, "total": b, "rate": rr}
        return ft

    for d in dict_rows:
        unit_cell = (d.get("UNIT") or "").strip()
        subp = (d.get("SUBPROGRAM") or "").strip()

        # totals rows variants
        if unit_cell.upper() == "TOTALS":
            # totals for previous unit
            if current_unit:
                ft = _collect_cov(d)
                unit_totals[current_unit] = ft
            continue

        if unit_cell.upper() == "GRAND TOTALS":
            grand_totals = _collect_cov(d)
            # GRAND TOTALS 행에서는 COMPLEXITY 컬럼에 총합이 들어오고, SUBPROGRAM은 subprogram count처럼 보임
            grand_totals["subprogram_count"] = _to_int(d.get("SUBPROGRAM"), 0)
            continue

        # normal row: update current unit if provided
        if unit_cell:
            current_unit = unit_cell

        unit = current_unit
        if not unit or not subp:
            continue

        # older style totals: Subprogram=="TOTALS"
        if subp.upper() in ("TOTALS", "TOTAL"):
            ft = _collect_cov(d)
            unit_totals[unit] = ft
            continue

        e: Dict[str, Any] = {"unit": unit, "subprogram": subp, "ccn": _to_int(d.get("COMPLEXITY"), 0)}
        for col in ("STATEMENTS", "BRANCHES", "PAIRS", "FUNCTIONS", "FUNCTION CALLS"):
            if col in cols:
                a, b, rr = _parse_ratio(d.get(col))
                e[col.lower().replace(" ", "_")] = {"covered": a, "total": b, "rate": rr}
        entries.append(e)

    return {
        "ok": True,
        "path": str(path),
        "entries": entries,
        "unit_totals": unit_totals,
        "grand_totals": grand_totals,
    }


def parse_vcast_environment_report(path: Path) -> Dict[str, Any]:
    """
    VectorCAST Environment Coverage Report (…_environment_report.html)
    - 파일별(상위 i0) Statements/Branches 비율을 뽑아 worst 리스트를 만든다
    """
    path = Path(path)
    soup_obj = _soup(path)
    if soup_obj is None:
        return {"ok": False, "reason": "bs4_missing_or_empty", "path": str(path)}

    # 이 리포트는 "File / Environment" 헤더를 사용
    tbl = _find_table_by_headers(soup_obj, ["FILE / ENVIRONMENT", "STATEMENTS", "BRANCHES"])
    if tbl is None:
        return {"ok": False, "reason": "no_env_table", "path": str(path)}

    # 헤더/행 파싱을 직접 수행(클래스 i0/i1 구분을 위해)
    headers, _ = _table_matrix(tbl)
    cols = [c.strip().upper() for c in headers]

    by_file: List[Dict[str, Any]] = []
    for tr in tbl.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        first = tds[0]
        classes = set(first.get("class") or [])
        is_file_row = ("i0" in classes)  # VectorCAST: i0 = file, i1 = environment path
        name = first.get_text(" ", strip=True)
        if not name:
            continue

        # build row values
        cells = [c.get_text(" ", strip=True) for c in tds]
        # pad
        if len(cells) < len(cols):
            cells = cells + [""] * (len(cols) - len(cells))
        row = {cols[i]: cells[i] for i in range(min(len(cols), len(cells)))}

        st_cov = row.get("STATEMENTS")
        br_cov = row.get("BRANCHES")
        st_a, st_b, st_r = _parse_ratio(st_cov)
        br_a, br_b, br_r = _parse_ratio(br_cov)

        if is_file_row:
            by_file.append({
                "file": name,
                "statements": {"covered": st_a, "total": st_b, "rate": st_r},
                "branches": {"covered": br_a, "total": br_b, "rate": br_r},
            })

    # worst lists
    worst_statements = sorted(by_file, key=lambda d: float(d["statements"]["rate"] or 0.0))[:15]
    worst_branches = sorted(by_file, key=lambda d: float(d["branches"]["rate"] or 0.0))[:15]

    return {
        "ok": True,
        "path": str(path),
        "by_file": by_file,
        "worst_statements": worst_statements,
        "worst_branches": worst_branches,
        # UI에서 HTML row 점프에 활용하기 위한 힌트(현재는 file name 기반 스크롤)
        "row_locator": {"kind": "vcast_env", "match": "td.i0_text"},
    }


def parse_vcast_execution_result_report(path: Path) -> Dict[str, Any]:
    text = _read_text_safe(path)
    if not text:
        return {"ok": False, "reason": "empty", "path": str(path)}

    tables = _extract_tables_html(text)
    if not tables:
        return {"ok": False, "reason": "no_tables", "path": str(path)}

    config = _table_kv(tables[0]) if tables else {}
    testcases: List[Dict[str, str]] = []
    for rows in tables[1:]:
        item = _table_kv(rows)
        if item:
            testcases.append(item)

    return {
        "ok": True,
        "path": str(path),
        "config": config,
        "testcases": testcases,
    }


def parse_vcast_metrics_simple_report(path: Path) -> Dict[str, Any]:
    text = _read_text_safe(path)
    if not text:
        return {"ok": False, "reason": "empty", "path": str(path)}

    tables = _extract_tables_html(text)
    if not tables:
        return {"ok": False, "reason": "no_tables", "path": str(path)}

    config = _table_kv(tables[0]) if tables else {}
    entries: List[Dict[str, Any]] = []

    for rows in tables[1:]:
        if not rows:
            continue
        headers = [h.strip().upper() for h in rows[0]]
        if not headers or "UNIT" not in headers or "SUBPROGRAM" not in headers:
            continue
        unit_idx = headers.index("UNIT")
        sub_idx = headers.index("SUBPROGRAM")
        ccn_idx = headers.index("COMPLEXITY") if "COMPLEXITY" in headers else None
        st_idx = headers.index("STATEMENTS") if "STATEMENTS" in headers else None
        br_idx = headers.index("BRANCHES") if "BRANCHES" in headers else None

        current_unit = ""
        for row in rows[1:]:
            if len(row) <= max(unit_idx, sub_idx):
                continue
            unit = (row[unit_idx] or "").strip()
            subp = (row[sub_idx] or "").strip()
            if unit:
                current_unit = unit
            unit = current_unit or unit
            if not unit or not subp:
                continue
            item: Dict[str, Any] = {"unit": unit, "subprogram": subp}
            if ccn_idx is not None and ccn_idx < len(row):
                item["ccn"] = _to_int(row[ccn_idx], 0)
            if st_idx is not None and st_idx < len(row):
                a, b, rr = _parse_ratio(row[st_idx])
                item["statements"] = {"covered": a, "total": b, "rate": rr}
            if br_idx is not None and br_idx < len(row):
                a, b, rr = _parse_ratio(row[br_idx])
                item["branches"] = {"covered": a, "total": b, "rate": rr}
            entries.append(item)

        break

    return {
        "ok": True,
        "path": str(path),
        "config": config,
        "entries": entries,
    }


def parse_vcast_testcase_data_report(path: Path) -> Dict[str, Any]:
    text = _read_text_safe(path)
    if not text:
        return {"ok": False, "reason": "empty", "path": str(path)}

    sections = _split_h2_sections(text)
    if not sections:
        return {"ok": False, "reason": "no_sections", "path": str(path)}

    config: Dict[str, str] = {}
    testcases: List[Dict[str, Any]] = []

    for title, body in sections:
        if not title:
            continue
        if title.strip().lower() == "configuration data":
            tables = _extract_tables_html(body)
            if tables:
                config = _table_kv(tables[0])
            continue

        tables = _extract_tables_html(body)
        tc_cfg = _table_kv(tables[0]) if len(tables) >= 1 else {}
        tc_data = _table_kv(tables[1]) if len(tables) >= 2 else {}

        item = {
            "testcase": title,
            "configuration": tc_cfg,
            "data": tc_data,
            "input_data": _extract_h4_section(body, "Input Test Data"),
            "expected_data": _extract_h4_section(body, "Expected Test Data"),
            "input_user_code": _extract_h4_section(body, "Test Case / Parameter Input User Code"),
            "expected_user_code": _extract_h4_section(body, "Test Case / Parameter Expected User Code"),
        }
        testcases.append(item)

    return {
        "ok": True,
        "path": str(path),
        "config": config,
        "testcases": testcases,
    }


def write_complexity_csv(entries: List[Dict[str, Any]], out_csv: Path) -> None:
    """
    GUI '복잡도' 탭에서 읽는 complexity.csv 생성 (lizard 스타일)
    - file, function, ccn, nloc
    nloc는 대략 Statements total을 사용(없으면 1)
    """
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "function", "ccn", "nloc"])
        w.writeheader()
        for e in entries:
            unit = str(e.get("unit") or "")
            func = str(e.get("subprogram") or "")
            ccn = _to_int(e.get("ccn"), 0)

            nloc = 1
            st = e.get("statements")
            if isinstance(st, dict):
                nloc = _to_int(st.get("total"), 1) or 1

            w.writerow({"file": unit, "function": func, "ccn": ccn, "nloc": nloc})


def compute_code_metrics_from_complexity_csv(path: Path) -> Dict[str, Optional[int]]:
    """
    complexity.csv(lizard 스타일) 기반 코드 규모 요약
    - code_files: 파일 수
    - functions: 함수 수 (file::function unique)
    - nloc: NLOC 합계 (중복 키는 최대값 사용)
    """
    out: Dict[str, Optional[int]] = {"code_files": None, "functions": None, "nloc": None}
    try:
        path = Path(str(path))
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return out
    except Exception:
        return out

    raw = None
    used_enc = "utf-8"
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            raw = path.read_text(encoding=enc, errors="ignore")
            used_enc = enc
            break
        except Exception:
            raw = None
    if not raw:
        return out

    lines = raw.splitlines()

    # 헤더 라인 탐색
    header_idx = 0
    header_line = lines[0] if lines else ""
    for i, ln in enumerate(lines[:80]):
        lnu = (ln or "").strip().lower()
        if not lnu:
            continue
        if ("file" in lnu and "function" in lnu) or ("unit" in lnu and "subprogram" in lnu):
            header_idx = i
            header_line = ln
            break

    # delimiter 추정
    delim = ","
    try:
        if ";" in header_line:
            delim = ";"
        elif "\t" in header_line:
            delim = "\t"
        else:
            import csv as _csv
            sample = "\n".join(lines[header_idx:header_idx + 10])
            try:
                delim = _csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"]).delimiter  # type: ignore[attr-defined]
            except Exception:
                delim = ","
    except Exception:
        delim = ","

    # DictReader
    import csv as _csv
    from io import StringIO

    sio = StringIO("\n".join(lines[header_idx:]))
    reader = _csv.DictReader(sio, delimiter=delim)

    def _get(row: dict, keys: list[str]) -> str:
        for k in keys:
            if k in row and row.get(k) is not None:
                return str(row.get(k) or "").strip()
        return ""

    files: set[str] = set()
    keys: set[str] = set()
    nloc_max: Dict[str, int] = {}

    for row in reader:
        if not isinstance(row, dict):
            continue
        f = _get(row, ["file", "File", "filename", "path", "unit", "Unit"])
        fn = _get(row, ["function", "Function", "function_name", "name", "subprogram", "Subprogram"])
        if not f and not fn:
            continue
        fu = f.strip()
        fnu = fn.strip()
        if not fu and not fnu:
            continue

        # totals 방어
        if fu.upper() in ("TOTALS", "GRAND TOTALS", "GRAND_TOTALS", "SUMMARY"):
            continue
        if fnu.upper() in ("TOTALS", "GRAND TOTALS", "GRAND_TOTALS", "SUMMARY"):
            continue

        files.add(fu)
        k = f"{fu}::{fnu}"
        keys.add(k)

        nloc_s = _get(row, ["nloc", "NLOC", "loc", "lines", "line_count"])
        try:
            nv = int(float(nloc_s)) if str(nloc_s).strip() else 0
        except Exception:
            nv = 0
        if nv > 0:
            prev = nloc_max.get(k, 0)
            if nv > prev:
                nloc_max[k] = nv

    if files:
        out["code_files"] = int(len(files))
    if keys:
        out["functions"] = int(len(keys))
    if nloc_max:
        out["nloc"] = int(sum(nloc_max.values()))
    return out

# -----------------------------------------------------------------------------
# PRQA(QAC) parsers
# -----------------------------------------------------------------------------

def parse_prqa_summary_html(path: Path) -> Dict[str, Any]:
    """
    PRQA Code Review / Rule Compliance Report에서 첫 요약 테이블 추출
    예:
      - Number of Files
      - Lines of Code (source files only)
      - Total preprocessed code line
      - Diagnostic Count
    """
    path = Path(path)
    soup_obj = _soup(path)
    if soup_obj is None:
        return {"ok": False, "reason": "bs4_missing_or_empty", "path": str(path)}

    tables = soup_obj.find_all("table")
    if not tables:
        return {"ok": False, "reason": "no_table", "path": str(path)}

    t0 = tables[0]
    out: Dict[str, Any] = {"ok": True, "path": str(path), "kind": (soup_obj.title.string.strip() if soup_obj.title and soup_obj.title.string else "")}
    kv: Dict[str, Any] = {}
    for tr in t0.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) != 2:
            continue
        k, v = cells[0], cells[1]
        if not k:
            continue
        key = re.sub(r"\s+", " ", k).strip()
        kv[key] = _to_int(v, _to_int(v, 0)) if re.search(r"\d", str(v)) else v

    out["summary"] = kv
    # canonical fields
    out["number_of_files"] = _to_int(kv.get("Number of Files"))
    out["loc_source"] = _to_int(kv.get("Lines of Code (source files only)"))
    out["loc_preprocessed"] = _to_int(kv.get("Total preprocessed code line"))
    out["diagnostic_count"] = _to_int(kv.get("Diagnostic Count"))
    return out


def parse_prqa_his_metrics_xlsx(path: Path, *, top_n: int = 30, max_rows: int = 5000) -> Dict[str, Any]:
    """
    PRQA HIS Metrics Report (xlsx)
    - v(G) 기반 상위 함수
    """
    pd = _import_pandas()
    if pd is None:
        return {"ok": False, "reason": "pandas_missing", "path": str(path)}
    path = Path(path)

    try:
        xls = pd.ExcelFile(str(path))
        sheet = xls.sheet_names[0]
        raw = pd.read_excel(str(path), sheet_name=sheet, header=1)
    except Exception as e:
        return {"ok": False, "reason": f"xlsx_read_failed: {e}", "path": str(path)}

    # raw: 첫 2행이 헤더 성격(위/아래)
    if raw.shape[0] < 3:
        return {"ok": False, "reason": "xlsx_too_small", "path": str(path)}

    # 컬럼 7개 고정 가정(샘플 기준)
    cols = ["index", "function", "vg", "level", "calling", "calls", "file"]
    data = raw.iloc[2:].copy()
    data = data.iloc[:, : len(cols)]
    data.columns = cols

    # 타입 정리
    data["vg"] = pd.to_numeric(data["vg"], errors="coerce").fillna(0).astype(int)
    data["level"] = pd.to_numeric(data["level"], errors="coerce").fillna(0).astype(int)
    data["calling"] = pd.to_numeric(data["calling"], errors="coerce").fillna(0).astype(int)
    data["calls"] = pd.to_numeric(data["calls"], errors="coerce").fillna(0).astype(int)

    # 노이즈 행 제거(샘플에서 "Level 0" 같은 그룹 행이 섞여 들어옴)
    data["function"] = data["function"].astype(str)
    data["file"] = data["file"].astype(str)
    data = data[~data["function"].str.match(r"^\s*Level\b", case=False, na=False)]
    data = data[~data["file"].str.match(r"^\s*(nan|none)\s*$", case=False, na=False)]

    # top + rows
    data_sorted = data.sort_values(["vg", "calls"], ascending=[False, False])
    top = data_sorted.head(int(top_n))
    top_list: List[Dict[str, Any]] = []
    for _, r in top.iterrows():
        top_list.append({
            "function": str(r.get("function") or ""),
            "vg": int(r.get("vg") or 0),
            "level": int(r.get("level") or 0),
            "calling": int(r.get("calling") or 0),
            "calls": int(r.get("calls") or 0),
            "file": str(r.get("file") or ""),
        })

    # UI 필터/그룹핑용: 상위 max_rows만 유지
    rows_list: List[Dict[str, Any]] = []
    trimmed = data_sorted.head(int(max_rows))
    for _, r in trimmed.iterrows():
        rows_list.append({
            "function": str(r.get("function") or ""),
            "vg": int(r.get("vg") or 0),
            "level": int(r.get("level") or 0),
            "calling": int(r.get("calling") or 0),
            "calls": int(r.get("calls") or 0),
            "file": str(r.get("file") or ""),
        })

    # file-level stats for charting
    file_stats: List[Dict[str, Any]] = []
    try:
        g = data.groupby("file", dropna=False)
        fs = g.agg(
            functions=("function", "count"),
            vg_max=("vg", "max"),
            vg_mean=("vg", "mean"),
            calls_sum=("calls", "sum"),
        ).reset_index()
        fs = fs.sort_values(["vg_max", "functions"], ascending=[False, False]).head(200)
        for _, r in fs.iterrows():
            file_stats.append({
                "file": str(r.get("file") or ""),
                "functions": int(r.get("functions") or 0),
                "vg_max": int(r.get("vg_max") or 0),
                "vg_mean": float(r.get("vg_mean") or 0.0),
                "calls_sum": int(r.get("calls_sum") or 0),
            })
    except Exception:
        pass

    stats = {
        "functions_total": int(data.shape[0]),
        "vg_max": int(data["vg"].max() if data.shape[0] else 0),
        "vg_p95": int(data["vg"].quantile(0.95) if data.shape[0] else 0),
        "vg_mean": float(data["vg"].mean() if data.shape[0] else 0.0),
    }

    return {
        "ok": True,
        "path": str(path),
        "stats": stats,
        "top_vg": top_list,
        "rows": rows_list,
        "file_stats": file_stats,
        "trimmed_rows": int(len(rows_list)),
    }


# -----------------------------------------------------------------------------
# Glue
# -----------------------------------------------------------------------------

def _find_one(build_root: Path, patterns: List[str]) -> Optional[Path]:
    hits: List[Path] = []
    for pat in patterns:
        hits.extend(list(Path(build_root).rglob(pat)))

    if not hits:
        return None

    def _key(p: Path):
        try:
            mt = p.stat().st_mtime
        except Exception:
            mt = 0.0
        return (len(str(p)), -mt)

    hits.sort(key=_key)
    return hits[0]


def _find_one_in_roots(roots: List[Path], patterns: List[str]) -> Optional[Path]:
    for root in roots:
        if not root:
            continue
        try:
            hit = _find_one(root, patterns)
        except Exception:
            hit = None
        if hit:
            return hit
    return None


def _env_float(name: str, default: float) -> float:
    v = (os.environ.get(name) or "").strip()
    if not v:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _ratio_all_ok(r: Any) -> Optional[bool]:
    if not isinstance(r, dict):
        return None
    tot = _to_int(r.get("total"), 0)
    ok = _to_int(r.get("ok"), 0)
    if tot <= 0:
        return None
    return ok >= tot


def ensure_gui_summary(
    *,
    reports_dir: Path,
    build_root: Path,
    build_info: Dict[str, Any],
    coverage_threshold: Optional[float] = None,
) -> None:
    """
    Jenkins 동기화 이후 GUI가 읽을 수 있는 최소 파일 생성 + 리포트 요약

    생성/갱신
    - reports_dir/analysis_summary.json
    - reports_dir/status.json
    - reports_dir/jenkins_scan.json
    - reports_dir/complexity.csv (metrics report 기반)
    """
    reports_dir = Path(reports_dir)
    build_root = Path(build_root)

    # 1) scan
    jscan = scan_jenkins_build_root(build_root)
    _write_json(reports_dir / "jenkins_scan.json", jscan)
    _write_jenkins_scan_bundle(reports_dir, jscan)

    # 2) locate VectorCAST reports (UT/IT)
    search_roots = [build_root, reports_dir, reports_dir.parent]
    ut_full = _find_one_in_roots(search_roots, ["*UT*_full_report.html", "*_UT_*_full_report.html", "*UT_full_report.html", "*UT*_full*.html"])
    ut_metrics = _find_one_in_roots(search_roots, ["*UT*_metrics_report.html", "*_UT_*_metrics_report.html", "*UT_metrics_report.html", "*UT*_metrics*.html"])
    ut_env = _find_one_in_roots(search_roots, ["*UT*_environment_report.html", "*_UT_*_environment_report.html", "*UT_environment_report.html", "*UT*_environment*.html"])

    it_full = _find_one_in_roots(search_roots, ["*IT*_full_report.html", "*_IT_*_full_report.html", "*IT_full_report.html", "*IT*_full*.html"])
    it_metrics = _find_one_in_roots(search_roots, ["*IT*_metrics_report.html", "*_IT_*_metrics_report.html", "*IT_metrics_report.html", "*IT*_metrics*.html"])
    it_env = _find_one_in_roots(search_roots, ["*IT*_environment_report.html", "*_IT_*_environment_report.html", "*IT_environment_report.html", "*IT*_environment*.html"])

    agg_cov = _find_one_in_roots(search_roots, ["*AggregateCoverageReport.html", "*AggregateCoverage*.html"])
    exec_res = _find_one_in_roots(search_roots, ["*ExecutionResultReport.html", "*ExecutionResult*.html"])
    metrics_rep = _find_one_in_roots(search_roots, ["*MetricsReport.html", "*MetricsReport*.html"])
    tc_data = _find_one_in_roots(search_roots, ["*TestCaseDataReport.html", "*TestCaseData*.html"])

    vcast: Dict[str, Any] = {}
    vcast_detail: Dict[str, Any] = {}
    complexity_csv_written = False

    if ut_full:
        vcast["ut_full"] = parse_vcast_full_report(ut_full)
    if ut_metrics:
        vcast["ut_metrics"] = parse_vcast_metrics_report(ut_metrics)
        if vcast["ut_metrics"].get("ok") and not complexity_csv_written:
            try:
                write_complexity_csv(vcast["ut_metrics"].get("entries", []), reports_dir / "complexity.csv")
                complexity_csv_written = True
            except Exception:
                pass
    if ut_env:
        vcast["ut_env"] = parse_vcast_environment_report(ut_env)

    if it_full:
        vcast["it_full"] = parse_vcast_full_report(it_full)
    if it_metrics:
        vcast["it_metrics"] = parse_vcast_metrics_report(it_metrics)
        if vcast["it_metrics"].get("ok") and not complexity_csv_written:
            try:
                write_complexity_csv(vcast["it_metrics"].get("entries", []), reports_dir / "complexity.csv")
                complexity_csv_written = True
            except Exception:
                pass
    if it_env:
        vcast["it_env"] = parse_vcast_environment_report(it_env)

    if agg_cov:
        vcast_detail["aggregate_coverage"] = parse_vcast_metrics_simple_report(agg_cov)
    if metrics_rep:
        vcast_detail["metrics"] = parse_vcast_metrics_simple_report(metrics_rep)
    if exec_res:
        vcast_detail["execution_result"] = parse_vcast_execution_result_report(exec_res)
    if tc_data:
        vcast_detail["testcase_data"] = parse_vcast_testcase_data_report(tc_data)

    _write_vectorcast_rag_bundle(
        reports_dir=reports_dir,
        build_root=build_root,
        jscan=jscan,
        vcast=vcast,
        vcast_detail=vcast_detail,
        ut_reports=[p for p in (ut_full, ut_metrics, ut_env) if p],
        it_reports=[p for p in (it_full, it_metrics, it_env) if p],
    )


    # 2-b) complexity.csv 확보 (metrics 생성 실패/미다운로드 케이스 대비)
    comp_out = (reports_dir / "complexity.csv")
    try:
        if not comp_out.exists() or comp_out.stat().st_size <= 0:
            cand = _find_one(build_root, ["*complexity.csv", "*Complexity*.csv", "*lizard*.csv", "*Lizard*.csv"])
            if cand and cand.exists() and cand.is_file():
                try:
                    if cand.resolve() != comp_out.resolve():
                        # 너무 큰 파일은 제외 (뷰어 프리징 방지)
                        if cand.stat().st_size <= 80 * 1024 * 1024:
                            shutil.copy2(cand, comp_out)
                except Exception:
                    pass
    except Exception:
        pass

    code_metrics = compute_code_metrics_from_complexity_csv(comp_out)

    # 3) PRQA (QAC) reports
    prqa: Dict[str, Any] = {}
    crr = _find_one(build_root, ["*_CRR_*.html", "*CRR*.html"])
    rcr = _find_one(build_root, ["*_RCR_*.html", "*RCR*.html"])
    hmr_xlsx = _find_one(build_root, ["*_HMR_*.xlsx", "*HMR*.xlsx"])

    if crr:
        prqa["crr"] = parse_prqa_summary_html(crr)
    if rcr:
        prqa["rcr"] = parse_prqa_summary_html(rcr)
    if hmr_xlsx:
        prqa["hmr"] = parse_prqa_his_metrics_xlsx(hmr_xlsx, top_n=30)

    # 4) derive high-level metrics for dashboard
    # build_ok: jenkins scan token을 힌트로 삼되, build_info에 실패 플래그가 있으면 우선
    build_ok = True
    try:
        if isinstance(build_info, dict):
            if build_info.get("result") and str(build_info.get("result")).upper() not in ("SUCCESS", "UNSTABLE"):
                build_ok = False
    except Exception:
        pass
    if int(jscan.get("summary", {}).get("fail_error_tokens", 0)) > 0:
        # 토큰은 과탐 가능하니 build_ok를 강제로 False로 만들지 않음
        pass

    exit_code = 0 if build_ok else 1

    tests_summary: Dict[str, Any] = {}
    tests_ok: Optional[bool] = None

    runtime_summary = _scan_runtime_summary(build_root, jscan)

    if isinstance(vcast.get("ut_full"), dict) and vcast["ut_full"].get("ok"):
        tests_summary["ut"] = {
            "testcases": vcast["ut_full"].get("testcases"),
            "expected": vcast["ut_full"].get("expected"),
            "execute_time": vcast["ut_full"].get("execute_time"),
        }
        ok_tc = _ratio_all_ok(vcast["ut_full"].get("testcases"))
        ok_ex = _ratio_all_ok(vcast["ut_full"].get("expected"))
        for v in (ok_tc, ok_ex):
            if v is not None:
                tests_ok = v if tests_ok is None else (tests_ok and v)

    if isinstance(vcast.get("it_full"), dict) and vcast["it_full"].get("ok"):
        tests_summary["it"] = {
            "testcases": vcast["it_full"].get("testcases"),
            "expected": vcast["it_full"].get("expected"),
            "execute_time": vcast["it_full"].get("execute_time"),
        }
        ok_tc = _ratio_all_ok(vcast["it_full"].get("testcases"))
        ok_ex = _ratio_all_ok(vcast["it_full"].get("expected"))
        for v in (ok_tc, ok_ex):
            if v is not None:
                tests_ok = v if tests_ok is None else (tests_ok and v)

    # fallback: vcast 파싱이 없으면 build_ok 사용
    if tests_ok is None:
        tests_ok = build_ok

    # 5) coverage threshold 결정
    thr_raw = float(coverage_threshold) if coverage_threshold is not None else _env_float("DEVOPS_JENKINS_COVERAGE_THRESHOLD", 0.8)
    thr = _norm_rate_0_1(thr_raw)

    coverage: Dict[str, Any] = {"line_rate": 0.0, "threshold": thr}
    # UT metrics 우선
    if isinstance(vcast.get("ut_metrics"), dict):
        gt = (vcast["ut_metrics"].get("grand_totals") or {})
        stcov = gt.get("statements")
        if isinstance(stcov, dict) and _to_int(stcov.get("total"), 0) > 0:
            coverage["line_rate"] = _norm_rate_0_1(stcov.get("rate") or 0.0)
            coverage["basis"] = "vcast_ut_statements"
            coverage["covered"] = _to_int(stcov.get("covered"), 0)
            coverage["total"] = _to_int(stcov.get("total"), 0)
        brcov = gt.get("branches")
        if isinstance(brcov, dict) and _to_int(brcov.get("total"), 0) > 0:
            coverage["branch_rate"] = _norm_rate_0_1(brcov.get("rate") or 0.0)
            coverage["branches_covered"] = _to_int(brcov.get("covered"), 0)
            coverage["branches_total"] = _to_int(brcov.get("total"), 0)

    # IT metrics fallback: statements -> branches -> functions/calls
    if float(coverage.get("line_rate", 0.0) or 0.0) <= 0.0 and isinstance(vcast.get("it_metrics"), dict):
        gt = (vcast["it_metrics"].get("grand_totals") or {})
        stcov = gt.get("statements")
        if isinstance(stcov, dict) and _to_int(stcov.get("total"), 0) > 0:
            coverage["line_rate"] = _norm_rate_0_1(stcov.get("rate") or 0.0)
            coverage["basis"] = "vcast_it_statements"
            coverage["covered"] = _to_int(stcov.get("covered"), 0)
            coverage["total"] = _to_int(stcov.get("total"), 0)
        brcov = gt.get("branches")
        if isinstance(brcov, dict) and _to_int(brcov.get("total"), 0) > 0 and "branch_rate" not in coverage:
            coverage["branch_rate"] = _norm_rate_0_1(brcov.get("rate") or 0.0)
            coverage["branches_covered"] = _to_int(brcov.get("covered"), 0)
            coverage["branches_total"] = _to_int(brcov.get("total"), 0)

        if float(coverage.get("line_rate", 0.0) or 0.0) <= 0.0:
            fncov = gt.get("functions")
            if isinstance(fncov, dict) and _to_int(fncov.get("total"), 0) > 0:
                coverage["line_rate"] = _norm_rate_0_1(fncov.get("rate") or 0.0)
                coverage["basis"] = "vcast_it_functions"
                coverage["covered"] = _to_int(fncov.get("covered"), 0)
                coverage["total"] = _to_int(fncov.get("total"), 0)
        callcov = gt.get("function_calls")
        if isinstance(callcov, dict) and _to_int(callcov.get("total"), 0) > 0:
            coverage["call_rate"] = _norm_rate_0_1(callcov.get("rate") or 0.0)
            coverage["calls_covered"] = _to_int(callcov.get("covered"), 0)
            coverage["calls_total"] = _to_int(callcov.get("total"), 0)

    cov_ok = float(coverage.get("line_rate", 0.0) or 0.0) >= float(coverage.get("threshold", thr) or thr)
    coverage["ok"] = bool(cov_ok)
    coverage["enabled"] = True

    # failure_stage: GUI가 보기 쉽게
    failure_stage = ""
    if not build_ok:
        failure_stage = "jenkins"
    elif not tests_ok:
        failure_stage = "tests"
    elif not cov_ok:
        failure_stage = "coverage"

    steps = [
        {"order": 1, "step_id": "jenkins", "name": "Jenkins", "enabled": True, "status": "ok" if build_ok else "fail", "note": "viewer_mode"},
        {"order": 2, "step_id": "tests", "name": "Tests", "enabled": True, "status": "ok" if tests_ok else "fail", "note": "vectorcast"},
        {"order": 3, "step_id": "coverage", "name": "Coverage", "enabled": True, "status": "ok" if cov_ok else "warn", "note": coverage.get("basis", "unknown")},
        {"order": 4, "step_id": "docs", "name": "Docs", "enabled": False, "status": "skipped", "note": "viewer_mode"},
    ]

    # 6) status.json (GUI 공통 포맷)
    # Jenkins build meta (GUI 공통 status.json에서 사용)
    j_result = str(build_info.get("result") or "")
    building = False
    try:
        if isinstance(build_info, dict):
            building = bool(build_info.get("building"))
    except Exception:
        building = False
    if not str(j_result).strip() and building:
        j_result = "BUILDING"
    j_ts = build_info.get("timestamp")
    j_ts_iso = ""
    try:
        if isinstance(j_ts, (int, float)) and float(j_ts) > 0:
            j_ts_iso = datetime.fromtimestamp(float(j_ts) / 1000.0).isoformat(timespec="seconds")
        else:
            j_ts_iso = str(j_ts or "")
    except Exception:
        j_ts_iso = str(j_ts or "")
    status = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "result": j_result,
        "status": j_result,
        "timestamp": j_ts_iso,
        "build_number": int(build_info.get("number") or -1),
        "build_url": str(build_info.get("url") or ""),
        "building": bool(build_info.get("building")) if isinstance(build_info, dict) else False,
        "duration_ms": int(build_info.get("duration") or 0) if isinstance(build_info, dict) and isinstance(build_info.get("duration"), (int, float)) else None,
        "code_metrics": code_metrics if isinstance(code_metrics, dict) else {},
        "job_url": str(build_info.get("job_url") or ""),
        "exit_code": int(exit_code),
        "failure_stage": failure_stage,
        "steps": steps,
    }
    _write_json(reports_dir / "status.json", status)

    # 7) analysis_summary.json (GUI 공통 키 + Jenkins 확장)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_dir": str(reports_dir),
        "build_root": str(build_root),
        "mode": "jenkins_viewer",
        "jenkins": {
            "job_url": str(build_info.get("job_url") or ""),
            "build_number": int(build_info.get("number") or -1),
            "build_url": str(build_info.get("url") or ""),
            "result": str(build_info.get("result") or ""),
            "building": bool(build_info.get("building")) if isinstance(build_info, dict) else False,
            "duration_ms": int(build_info.get("duration") or 0) if isinstance(build_info, dict) and isinstance(build_info.get("duration"), (int, float)) else None,
        },
        "build": {"ok": bool(build_ok)},
        "tests": {"ok": bool(tests_ok), "details": tests_summary},
        "coverage": coverage,
        "dynamic": runtime_summary,
        "code_metrics": code_metrics if isinstance(code_metrics, dict) else {},
        "jenkins_scan": jscan.get("summary", {}),
        "vectorcast": vcast,
        "vectorcast_detail": vcast_detail,
        "prqa": prqa,
    }
    _write_json(reports_dir / "analysis_summary.json", summary)
