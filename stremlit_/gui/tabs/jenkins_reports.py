# /app/gui/tabs/jenkins_reports.py
from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

import gui_utils
import ui_common


def _job_slug(job_url: str) -> str:
    s = (job_url or "").strip().rstrip("/")
    m = re.search(r"/job/([^/]+)/\d+/?$", s)
    if m:
        return m.group(1)
    m = re.search(r"/job/([^/]+)/?$", s)
    if m:
        return m.group(1)
    return re.sub(r"[^A-Za-z0-9_]+", "_", s)[-40:] or "job"


try:
    # 패키지 구조인 경우
    from gui.tabs import editor as editor_tab  # type: ignore
except Exception:  # pragma: no cover
    try:
        # 상대 import 가능한 경우
        from . import editor as editor_tab  # type: ignore
    except Exception:  # pragma: no cover
        editor_tab = None  # type: ignore

def _as_path(p) -> Optional[Path]:
    if not p:
        return None
    try:
        return Path(str(p))
    except Exception:
        return None


def _read_json(p: Optional[Path], default: Any) -> Any:
    if not p:
        return default
    try:
        return gui_utils.load_json(str(p), default=default)
    except Exception:
        return default

def _normalize_rule_id(rule: Any) -> str:
    """Normalize rule label to match catalog keys."""
    try:
        return gui_utils.normalize_rule_label(str(rule or ""))
    except Exception:
        return str(rule or "").strip()



def _download_button(path: Path, label: str):
    """Unified large download policy (checkbox default allow)."""
    try:
        ui_common.download_button_from_path(path, label, key=f"jr_dl_{path.name}")
    except Exception as e:
        ui_common.log_exception("jenkins_reports download", e)

def _human_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "-"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n)
    for u in units:
        if v < 1024.0 or u == units[-1]:
            return f"{v:.1f} {u}"
        v /= 1024.0
    return f"{n} B"


def _paged_dataframe(df: pd.DataFrame, *, key: str, page_size_default: int = 1000, height: int = 420) -> None:
    if df is None or df.empty:
        st.info("표시할 데이터 없음")
        return

    total = int(len(df))
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        page_size = st.number_input("page size", min_value=50, max_value=5000, value=int(page_size_default), step=50, key=f"{key}_ps")
    with c2:
        page = st.number_input("page", min_value=1, max_value=max(1, (total - 1) // int(page_size) + 1), value=1, step=1, key=f"{key}_pg")
    with c3:
        st.caption(f"rows {total}, showing {(page-1)*page_size+1} - {min(total, page*page_size)}")

    start = (int(page) - 1) * int(page_size)
    end = min(total, start + int(page_size))
    st.dataframe(df.iloc[start:end].copy(), width="stretch", height=height, hide_index=True)


def _extract_env_rows_snippet(path: Path, *, target_file: str, before: int = 6, after: int = 6, max_window_bytes: int = 2 * 1024 * 1024) -> str:
    # 대형 environment_report.html 대응
    # - 파일 전체 iframe 전송 금지
    # - target_file 행 주변 tr 일부만 추출해 작은 html로 렌더링
    import mmap

    tf = (target_file or "").strip()
    if not tf:
        return ""

    with path.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            needle = tf.encode("utf-8", errors="ignore")
            pos = mm.find(needle)
            if pos < 0:
                base = tf.replace("\\", "/").split("/")[-1].encode("utf-8", errors="ignore")
                pos = mm.find(base)
                if pos < 0:
                    return ""

            def find_prev(p: int, token: bytes, limit: int) -> int:
                s = max(0, p - limit)
                sub = mm[s:p]
                j = sub.rfind(token)
                return (s + j) if j >= 0 else -1

            def find_next(p: int, token: bytes, limit: int) -> int:
                e = min(len(mm), p + limit)
                sub = mm[p:e]
                j = sub.find(token)
                return (p + j) if j >= 0 else -1

            tr0 = find_prev(pos, b"<tr", max_window_bytes)
            if tr0 < 0:
                tr0 = max(0, pos - max_window_bytes)

            tr1 = find_next(pos, b"</tr>", max_window_bytes)
            if tr1 < 0:
                tr1 = min(len(mm), pos + max_window_bytes)
            else:
                tr1 = tr1 + len(b"</tr>")

            start = tr0
            end = tr1
            for _ in range(int(before)):
                p = find_prev(start, b"<tr", max_window_bytes)
                if p < 0:
                    break
                start = p
            for _ in range(int(after)):
                p = find_next(end, b"</tr>", max_window_bytes)
                if p < 0:
                    break
                end = p + len(b"</tr>")

            html_rows = mm[start:end].decode("utf-8", errors="ignore")

            safe_tf = tf.replace('"', "&quot;")
            wrapper = '''
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body {{ font-family: sans-serif; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td, th {{ border: 1px solid #ddd; padding: 6px; font-size: 12px; }}
  tr.target {{ outline: 3px solid #f4b400; background: #fff7cc; }}
</style>
</head>
<body>
<div style="margin:6px 0; font-weight:600;">environment_report snippet, target {safe_tf}</div>
<table>
<tbody>
{rows}
</tbody>
</table>
<script>
(function(){{
  const tf = {tf_js};
  const base = tf.replaceAll('\\','/').split('/').pop();
  const rows = Array.from(document.querySelectorAll('tr'));
  let best = null;
  for (const r of rows) {{
    const t = r.innerText || '';
    if (t.includes(tf) || t.includes(base)) {{ best = r; break; }}
  }}
  if (best) {{
    best.classList.add('target');
    best.scrollIntoView({{behavior:'auto', block:'center'}});
  }}
}})();
</script>
</body>
</html>
'''
            return wrapper.format(rows=html_rows, tf_js=json.dumps(tf), safe_tf=safe_tf).strip()
        finally:
            mm.close()


def _read_text_tail(path: Path, *, max_bytes: int = 512 * 1024) -> str:
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0

    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read(max_bytes)
    return data.decode("utf-8", errors="ignore")


def _read_text_slice(path: Path, *, start: int, max_bytes: int) -> str:
    """대형 파일을 특정 오프셋부터 일부만 읽기"""
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0

    if size <= 0:
        return ""

    start = max(0, min(int(start), max(0, size - 1)))
    max_bytes = max(1, int(max_bytes))

    with path.open("rb") as f:
        try:
            f.seek(start)
        except Exception:
            try:
                f.seek(0)
            except Exception:
                pass
        data = f.read(max_bytes)
    return data.decode("utf-8", errors="ignore")


def _extract_html_wrapper(path: Path, *, head_probe_bytes: int = 512 * 1024) -> tuple[str, str]:
    """HTML 일부 렌더를 위한 wrapper(head + body open tag) 추출

    Returns:
      (prefix, suffix)
      - prefix: <html>..<head>..</head><body ...>
      - suffix: </body></html>
    """
    try:
        probe = _read_text_slice(path, start=0, max_bytes=head_probe_bytes)
    except Exception:
        probe = ""

    if not probe:
        return ("<html><body>", "</body></html>")

    low = probe.lower()
    bpos = low.find("<body")
    if bpos >= 0:
        # body tag 끝('>') 까지 확보
        end = probe.find(">", bpos)
        if end >= 0:
            prefix = probe[: end + 1]
            # prefix가 <html...>를 포함하지 않는 경우 보정
            if "<html" not in low[: max(0, bpos)]:
                prefix = "<html>" + prefix
            return (prefix, "</body></html>")

    # body 태그를 못 찾는 경우 - head까지만 확보 시도
    h_end = low.find("</head>")
    if h_end >= 0:
        prefix = probe[: h_end + len("</head>")] + "<body>"
        if "<html" not in low[: h_end]:
            prefix = "<html>" + prefix
        return (prefix, "</body></html>")

    # 최후 fallback
    return ("<html><body>", "</body></html>")


def _find_in_file(path: Path, needle: str, *, max_scan_bytes: int = 80 * 1024 * 1024) -> Optional[int]:
    """파일에서 needle 첫 등장 위치(byte offset)를 찾음(대형 파일 대응)
    - 너무 큰 파일에서 전체 스캔을 피하기 위해 max_scan_bytes 제한
    """
    if not needle:
        return None
    try:
        nb = needle.encode("utf-8")
    except Exception:
        return None
    if not nb:
        return None

    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0
    if size <= 0:
        return None

    limit = min(size, int(max_scan_bytes))
    chunk = 2 * 1024 * 1024
    overlap = max(0, len(nb) - 1)
    pos = 0
    prev = b""
    try:
        with path.open("rb") as f:
            while pos < limit:
                buf = f.read(min(chunk, limit - pos))
                if not buf:
                    break
                hay = prev + buf
                idx = hay.find(nb)
                if idx >= 0:
                    return max(0, pos - len(prev)) + idx
                pos += len(buf)
                if overlap > 0:
                    prev = hay[-overlap:]
                else:
                    prev = b""
    except Exception:
        return None
    return None

def _inject_env_row_scroll_js(html: str, *, target_file: str) -> str:
    """VectorCAST environment_report.html에서 td.i0(파일 행) 텍스트로 스크롤/하이라이트"""
    tf = (target_file or "").strip()
    if not tf:
        return html

    tf_js = json.dumps(tf)
    js = f"""
<script>
(function() {{
  try {{
    const target = {tf_js};
    const tds = Array.from(document.querySelectorAll('td.i0'));
    let hit = null;
    for (const td of tds) {{
      const txt = (td.textContent || '').trim();
      if (txt === target) {{ hit = td; break; }}
    }}
    // fallback: 부분 일치(경로/표시 차이 대응)
    if (!hit) {{
      for (const td of tds) {{
        const txt = (td.textContent || '').trim();
        if (txt && (txt.endsWith(target) || txt.includes(target))) {{ hit = td; break; }}
      }}
    }}
    if (hit) {{
      const tr = hit.closest('tr') || hit;
      tr.scrollIntoView({{ behavior: 'instant', block: 'center' }});
      // highlight
      tr.style.outline = '3px solid #ffbf00';
      tr.style.outlineOffset = '2px';
      hit.style.fontWeight = '700';
      hit.style.background = 'rgba(255, 191, 0, 0.18)';
    }}
  }} catch (e) {{ /* noop */ }}
}})();
</script>
"""

    if "</body>" in html.lower():
        # case-insensitive replace
        idx = html.lower().rfind("</body>")
        return html[:idx] + js + html[idx:]
    return html + js


def _render_html(path: Path, *, height: int = 700, env_row_target: str = ""):
    # MessageSizeError 방지, 대형 html은 전체 iframe 전송 금지
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0

    st.caption(f"{path.name}, size {_human_bytes(size)}")
    _download_button(path, "📥 HTML 다운로드")

    EMBED_LIMIT = 3 * 1024 * 1024  # 3MiB
    if size <= EMBED_LIMIT:
        html = path.read_text(errors="ignore")
        if env_row_target:
            html = _inject_env_row_scroll_js(html, target_file=env_row_target)
        st.components.v1.html(html, height=height, scrolling=True)
        return

    if env_row_target:
        snippet = _extract_env_rows_snippet(path, target_file=env_row_target)
        if snippet:
            st.info("대형 HTML, 행 주변 snippet 렌더링, 전체 HTML은 다운로드로 확인")
            st.components.v1.html(snippet, height=min(900, height), scrolling=True)
            return

    st.warning("HTML이 매우 커서 전체 렌더링은 제한됨, 분할/검색 기반 부분 렌더 + tail 미리보기 + 다운로드 제공")

    # -----------------------------
    # 부분 렌더(분할/검색)
    # -----------------------------
    prefix, suffix = _extract_html_wrapper(path)
    max_render = 1_800_000  # Streamlit message size 여유

    # 상태 저장(파일별)
    sk = f"big_html_off_{str(path)}"
    if sk not in st.session_state:
        st.session_state[sk] = 0

    with st.expander("🔎 대형 HTML 부분 보기", expanded=True):
        mode = st.selectbox("보기 방식", ["앞부분", "끝부분", "오프셋(MB)", "검색"], key=f"big_html_mode_{path}")

        # 검색
        if mode == "검색":
            q = st.text_input("검색어(텍스트)", value="", key=f"big_html_q_{path}")
            c1, c2 = st.columns([1, 3])
            with c1:
                do = st.button("검색", key=f"big_html_find_{path}")
            with c2:
                st.caption("파일이 매우 크면 최대 80MB까지만 스캔")
            if do and q:
                pos = _find_in_file(path, q)
                if pos is None:
                    st.info("검색어를 찾지 못함(제한 범위/인코딩 영향 가능)")
                else:
                    # 앞쪽 여유를 두고 렌더
                    st.session_state[sk] = max(0, int(pos) - 200_000)
                    st.success(f"검색 위치로 이동: { _human_bytes(pos) }")

        # 오프셋 지정
        if mode == "오프셋(MB)":
            try:
                size_mb = max(1.0, float(size) / (1024.0 * 1024.0))
            except Exception:
                size_mb = 1.0
            off_mb = st.number_input("시작 오프셋(MB)", min_value=0.0, max_value=float(size_mb), value=float(st.session_state[sk]) / (1024.0 * 1024.0), step=1.0, key=f"big_html_offmb_{path}")
            st.session_state[sk] = int(float(off_mb) * 1024.0 * 1024.0)

        if mode == "끝부분":
            st.session_state[sk] = max(0, int(size) - max_render)
        if mode == "앞부분":
            st.session_state[sk] = 0

        start = int(st.session_state.get(sk) or 0)
        seg = _read_text_slice(path, start=start, max_bytes=max_render)
        # wrapper와 충돌하는 태그 제거
        seg = re.sub(r"(?is)</?\s*(html|head|body)\b[^>]*>", "", seg)

        try:
            st.components.v1.html(prefix + seg + suffix, height=height, scrolling=True)
        except Exception:
            st.code(seg, language="html")

    st.caption("tail 미리보기")
    st.code(_read_text_tail(path, max_bytes=512 * 1024), language="html")

def _render_xlsx(path: Path):
    # MessageSizeError 방지, 대형 시트 전체 dataframe 전송 금지
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0

    st.caption(f"{path.name}, size {_human_bytes(size)}")
    _download_button(path, "📥 EXCEL 다운로드")

    try:
        xls = pd.ExcelFile(path)
        sheets = xls.sheet_names
        sheet = st.selectbox("시트 선택", sheets, key=f"xls_sheet_{path}")
        nrows = st.number_input("미리보기 nrows", min_value=100, max_value=10000, value=2000, step=100, key=f"xls_n_{path}")
        df = pd.read_excel(path, sheet_name=sheet, nrows=int(nrows))
        st.caption("엑셀 미리보기, 전체는 다운로드로 확인")
        _paged_dataframe(df, key=f"xls_{path}_{sheet}", page_size_default=500, height=420)
    except Exception as e:
        st.error(f"엑셀 표시 실패: {e}")

def _top_n(df: pd.DataFrame, col: str, n: int = 15) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns:
        return pd.DataFrame()
    return df.sort_values(col, ascending=False).head(n)


def _build_kpi_df(jscan: dict) -> pd.DataFrame:
    summ = (jscan or {}).get("summary", {})
    rows = [
        {"KPI": "FAIL", "count": int(summ.get("FAIL_token", 0))},
        {"KPI": "ERROR", "count": int(summ.get("ERROR_token", 0))},
        {"KPI": "WARN", "count": int(summ.get("WARN_token", 0))},
        {"KPI": "PASS", "count": int(summ.get("PASS_token", 0))},
    ]
    return pd.DataFrame(rows)


def _build_ext_df(jscan: dict) -> pd.DataFrame:
    summ = (jscan or {}).get("summary", {})
    ext = (summ or {}).get("ext_counts", {}) or {}
    rows = [{"ext": k, "count": int(v)} for k, v in ext.items()]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("count", ascending=False).head(25)
    return df

def _normalize_items(x: Any) -> List[Dict[str, Any]]:
    if isinstance(x, dict) and isinstance(x.get("items"), list):
        return [i for i in x["items"] if isinstance(i, dict)]
    if isinstance(x, list):
        return [i for i in x if isinstance(i, dict)]
    return []



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


def _iter_prqa_xml_candidates(broot: Optional[Path], rdir: Optional[Path]) -> List[Path]:
    cands: List[Path] = []
    bases: List[Path] = []
    if rdir:
        bases.append(rdir)
    if broot:
        bases.append(broot / "reports")
        bases.append(broot / "report")
        bases.append(broot)

    for b in bases:
        if not b or not b.exists():
            continue
        try:
            for p in b.rglob("*.xml"):
                n = p.name.lower()
                if "prqa" in n or "qac" in n or "rcr" in n or "diagnostic" in n:
                    cands.append(p)
        except Exception:
            continue

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


def _extract_findings_from_prqa_xml(xml_path: Path, max_items: int = 2000) -> List[Dict[str, Any]]:
    if not xml_path or not xml_path.exists():
        return []
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return []

    def _find_val(elem, keys: List[str]) -> str:
        for k in keys:
            for kk in (k, k.lower(), k.upper()):
                if kk in elem.attrib and str(elem.attrib.get(kk)).strip():
                    return str(elem.attrib.get(kk)).strip()
        for k in keys:
            for child in elem.findall(f".//{k}"):
                if child.text and str(child.text).strip():
                    return str(child.text).strip()
        return ""

    items: List[Dict[str, Any]] = []
    for elem in root.iter():
        tag = str(elem.tag).lower()
        if tag not in ("annotation", "diagnostic", "issue", "violation", "finding"):
            continue
        file_val = _find_val(elem, ["file", "path", "filename", "source"])
        line_val = _find_val(elem, ["line", "line_num", "lineNumber"])
        rule_val = _find_val(elem, ["rule", "id", "qac", "misra", "check"])
        msg_val = _find_val(elem, ["message", "text", "desc", "description"])
        sev_val = _find_val(elem, ["severity", "level", "grade"])

        if not file_val and not rule_val and not msg_val:
            continue
        line_num = 0
        try:
            line_num = int(str(line_val or "0").strip())
        except Exception:
            line_num = 0
        if line_num <= 0 and file_val:
            m = re.search(r"[:(](\d+)[)]?$", file_val)
            if m:
                try:
                    line_num = int(m.group(1))
                    file_val = re.sub(r"[:(]\d+[)]?$", "", file_val).strip()
                except Exception:
                    line_num = 0

        items.append(
            {
                "tool": "prqa_xml",
                "severity": sev_val or "warning",
                "rule": rule_val,
                "message": msg_val or f"PRQA XML diagnostic in {xml_path.name}",
                "file": file_val,
                "line": line_num,
                "kind": "prqa_xml",
            }
        )
        if len(items) >= max_items:
            break
    return items

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
                        text = a.get_text(" ", strip=True)
                        m_file = re.search(r"([^/\\]+\.(?:c|h|cpp|hpp|cxx|cc))", title or href or text, re.IGNORECASE)
                        if not m_file:
                            continue
                        file_path = title or href or text
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
        back = txt[max(0, m.start() - 400):m.start()]
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
                    for i,h in enumerate(header):
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
                        a = cells[i_file].find('a') if i_file < len(cells) else None
                        href = (a.get('href') or '') if a else ''
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
    seen=set()
    for m in patt.finditer(txt):
        f=m.group("file").strip()
        line_no=int(m.group("line"))
        key=(f,line_no)
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


def _maybe_fill_findings_json(rdir: Optional[Path], items: List[Dict[str, Any]]) -> None:
    """reports/findings.json 이 비어있을 때(또는 없음) 합성 이슈로 채움.
    - 원본이 존재하면 .bak 저장 후 덮어씀(캐시 로컬에만 적용)
    - 항상 findings_filled.json도 같이 저장
    """
    if not rdir or not rdir.exists() or not items:
        return
    try:
        filled = rdir / "findings_filled.json"
        filled.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # auto fill on/off
    try:
        auto_fill = bool(st.session_state.get("auto_fill_findings_json", True))
    except Exception:
        auto_fill = True
    if not auto_fill:
        return

    target = rdir / "findings.json"
    try:
        if target.exists():
            try:
                raw = target.read_text(encoding="utf-8", errors="ignore").strip()
                if raw and raw != "[]":
                    return  # 이미 내용 있음
            except Exception:
                # 읽기 실패면 덮어쓰기 시도는 하지 않음
                return
            # backup
            try:
                bak = rdir / "findings.json.bak"
                if not bak.exists():
                    bak.write_text(raw if raw else "[]", encoding="utf-8")
            except Exception:
                pass
        # write
        target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return

def _synthesize_findings_for_editor(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> List[Dict[str, Any]]:
    # 0) 캐시 파일 우선
    if rdir and rdir.exists():
        cache = rdir / "findings_synth.json"
        if cache.exists():
            cached = _normalize_items(_read_json(cache, default=None))
            if cached:
                return cached

    items: List[Dict[str, Any]] = []

    # 1) 로그에서 추출
    for p in _iter_candidate_text_files(broot, rdir):
        txt = _read_tail(p)
        if not txt:
            continue
        tool_hint = "log"
        if "cppcheck" in p.name.lower():
            tool_hint = "cppcheck"
        if "clang" in p.name.lower():
            tool_hint = "clang"
        if "prqa" in p.name.lower() or "qac" in p.name.lower():
            tool_hint = "prqa"
        got = _extract_findings_from_text(txt, tool_hint=tool_hint)
        if got:
            items.extend(got)
        if len(items) >= 2000:
            break

    # 2) PRQA HTML에서 추출(가능한 경우)
    if len(items) < 2000:
        for html in _iter_qac_sur_html_candidates(broot, rdir):
            got = _extract_findings_from_qac_sur_html(html)
            if got:
                items.extend(got)
            if len(items) >= 2000:
                break

    if len(items) < 2000:
        for html in _iter_prqa_html_candidates(broot, rdir):
            got = _extract_findings_from_prqa_html(html)
            if got:
                items.extend(got)
            if len(items) >= 2000:
                break

    # 2b) PRQA/QAC XML에서 추출(가능한 경우)
    if len(items) < 2000:
        for xml in _iter_prqa_xml_candidates(broot, rdir):
            got = _extract_findings_from_prqa_xml(xml)
            if got:
                items.extend(got)
            if len(items) >= 2000:
                break

    # dedup
    uniq: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for it in items:
        key = (
            str(it.get("tool") or ""),
            str(it.get("file") or ""),
            int(it.get("line") or 0),
            int(it.get("col") or 0),
            str(it.get("rule") or ""),
            str(it.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
        if len(uniq) >= 2000:
            break

    # 캐시 저장
    if rdir and rdir.exists():
        try:
            (rdir / "findings_synth.json").write_text(json.dumps(uniq, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return uniq


def _collect_findings_for_editor(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> List[Dict[str, Any]]:
    # 1) reports_dir 내 별도 파일 우선(비어있으면 계속)
    if rdir and rdir.exists():
        for name in ("findings.json", "findings_merged.json", "findings_all.json", "issues.json"):
            p = rdir / name
            if p.exists():
                data = _read_json(p, default=None)
                items = _normalize_items(data)
                if items:
                    return items

    # 2) analysis_summary.json 내부 키 fallback
    for k in ("findings", "issues", "items", "all_findings", "merged_findings"):
        items = _normalize_items((summary or {}).get(k))
        if items:
            return items

    # 3) 없으면 합성 생성
    return _synthesize_findings_for_editor(broot, rdir, summary)


def _guess_project_root(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> str:
    # summary에 경로가 있으면 우선 사용
    if isinstance(summary, dict):
        paths = summary.get("paths") or {}
        if isinstance(paths, dict):
            pr = paths.get("project_root") or paths.get("root") or ""
            if pr:
                return str(Path(str(pr)).resolve())
        pr2 = summary.get("project_root") or ""
        if pr2:
            return str(Path(str(pr2)).resolve())

    # build_root 기반 추정
    # SVN checkout 경로 우선(svn_wc)
    if broot:
        basep = Path(broot)
        for rel in (
            "svn_wc",
            "svn_wc/Sources",
            "svn_wc/Sources/APP",
            "svn_wc/Sources/App",
            "svn_wc/source",
            "svn_wc/src",
        ):
            cand = basep / rel
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    # Jenkins 캐시에서 소스 스냅샷이 자주 위치하는 경로 후보 우선
    for base in [broot, rdir]:
        if not base:
            continue
        try:
            basep = Path(base)
        except Exception:
            continue
        for rel in (
            "app/PDSM/Sources",
            "app/PDSM/Source",
            "app/PDSM/src",
            "app/Sources",
            "Sources",
            "source",
            "src",
        ):
            cand = basep / rel
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    for base in [broot, (broot.parent if broot else None), rdir]:
        if not base:
            continue
        for name in ("workspace", "repo", "source", "src", "project", "code"):
            cand = (Path(base) / name)
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    return str((broot or rdir or Path(".")).resolve())


def _collect_source_roots(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> List[str]:
    """Jenkins Viewer에서 코드 루트 후보 수집
    - svn_wc가 있으면 최우선
    - build_root/app/PDSM/Sources 등 스냅샷 경로 후보 포함
    - 중복 제거 후 우선순위 유지
    """
    roots: List[Path] = []

    def add(p: Optional[Path]) -> None:
        if not p:
            return
        try:
            rp = Path(p).resolve()
        except Exception:
            rp = Path(p)
        if rp.exists() and rp.is_dir() and rp not in roots:
            roots.append(rp)

    # 0) summary에 지정된 루트
    if isinstance(summary, dict):
        paths = summary.get("paths") or {}
        if isinstance(paths, dict):
            pr = paths.get("project_root") or paths.get("root") or ""
            if pr:
                add(Path(str(pr)))
        pr2 = summary.get("project_root") or ""
        if pr2:
            add(Path(str(pr2)))

    # 1) svn_wc 우선
    if broot:
        b = Path(broot)
        for rel in (
            "svn_wc",
            "svn_wc/Sources",
            "svn_wc/Sources/APP",
            "svn_wc/Sources/App",
            "svn_wc/src",
            "svn_wc/source",
        ):
            add(b / rel)

    # 2) 스냅샷 후보
    for base in (broot, rdir, (rdir.parent if rdir else None)):
        if not base:
            continue
        bp = Path(base)
        for rel in (
            "app/PDSM/Sources",
            "app/PDSM",
            "app/Sources",
            "Sources",
            "source",
            "src",
        ):
            add(bp / rel)

    # 3) fallback
    add(broot)
    add(rdir)

    # 4) jenkins_scan.json의 자동 추정 루트
    # - app/... 또는 svn_wc/... 형태가 빌드마다 달라질 수 있어 scan 결과를 우선 반영
    try:
        jscan = (summary or {}).get("jenkins_scan") if isinstance(summary, dict) else None
        rels = (jscan or {}).get("source_roots") if isinstance(jscan, dict) else None
        if broot and isinstance(rels, list):
            for rel in rels:
                if not rel:
                    continue
                try:
                    add(Path(broot) / str(rel))
                except Exception:
                    continue
    except Exception:
        pass

    return [str(p) for p in roots]



def _set_editor_open_request(item: Dict[str, Any]) -> None:
    file_path = str(item.get("file") or item.get("path") or "")
    line = item.get("line") or item.get("lineNumber") or 0
    st.session_state["editor_open_file"] = file_path
    st.session_state["editor_open_line"] = int(line) if str(line).isdigit() or isinstance(line, int) else 0
    st.session_state["editor_open_message"] = str(item.get("message") or item.get("msg") or "")
    st.session_state["editor_open_tool"] = str(item.get("tool") or item.get("source") or "jenkins")
    st.session_state["editor_open_severity"] = str(item.get("severity") or item.get("level") or "")
    st.session_state["editor_open_rule"] = str(item.get("rule") or item.get("check") or item.get("id") or "")
    st.session_state["editor_open_kind"] = str(item.get("kind") or item.get("category") or "")
    st.session_state["editor_open_key"] = f"{file_path}:{line}:{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


def _render_findings_editor_bridge(items: List[Dict[str, Any]], broot: Optional[Path] = None, rdir: Optional[Path] = None) -> None:
    st.subheader("🧩 룰 위반/이슈 → Editor 열기")
    if not items:
        st.info("findings/이슈 데이터 미발견, reports_dir에 findings.json 생성 또는 analysis_summary.json에 findings 포함 필요")
        return

    try:
        rule_catalog = gui_utils.load_rule_catalog(Path.cwd(), extra_roots=[p for p in [broot, rdir, (rdir.parent if rdir else None)] if p])
    except Exception:
        rule_catalog = {}

    rows = []
    for it in items:
        f = str(it.get("file") or it.get("path") or "")
        ln = it.get("line") or it.get("lineNumber") or 0
        try:
            ln = int(ln)
        except Exception:
            ln = 0
        rule = str(it.get("rule") or it.get("check") or it.get("id") or "")
        msg = str(it.get("message") or it.get("msg") or "")
        if not (f or rule or msg):
            continue
        openable = bool(f) and ln > 0
        rows.append(
            {
                "tool": str(it.get("tool") or it.get("source") or ""),
                "severity": str(it.get("severity") or it.get("level") or ""),
                "rule": rule,
                "message": msg,
                "file": f,
                "line": ln,
                "source": str(it.get("source") or it.get("tool") or "findings"),
                "openable": openable,
                "_raw": it,
            }
        )

    if not rows:
        st.info("file/line 포함 이슈 없음, Editor 연결 불가")
        return

    df = pd.DataFrame(rows)
    src_opts = []
    if "source" in df.columns:
        try:
            src_opts = sorted({str(x) for x in df["source"].fillna("unknown").unique()})
        except Exception:
            src_opts = []
    src_sel = st.selectbox("source 필터", options=["전체"] + src_opts, index=0, key="jr_findings_source")
    only_openable = st.checkbox("파일/라인 있는 항목만", value=True, key="jr_findings_openable")
    q = st.text_input("필터(rule/message/file)", value="", key="jr_findings_q")
    max_topn = max(1, len(df))
    topn = st.number_input(
        "표시 개수(Top N)",
        min_value=1,
        max_value=max_topn,
        value=min(120, max_topn),
        step=10,
        key="jr_findings_topn",
    )

    dfv = df.copy()
    if src_sel != "전체" and "source" in dfv.columns:
        dfv = dfv[dfv["source"].astype(str) == str(src_sel)]
    if only_openable and "openable" in dfv.columns:
        dfv = dfv[dfv["openable"] == True]
    if q.strip():
        qq = q.strip().lower()
        dfv = dfv[
            dfv["rule"].astype(str).str.lower().str.contains(qq)
            | dfv["message"].astype(str).str.lower().str.contains(qq)
            | dfv["file"].astype(str).str.lower().str.contains(qq)
        ]

    dfv = dfv.sort_values(["severity", "file", "line"], ascending=[True, True, True]).head(int(topn)).reset_index(drop=True)
    st.caption(f"총 {len(df)}개 중 {len(dfv)}개 표시")

    for i, r in dfv.iterrows():
        c1, c2 = st.columns([1, 9])
        with c1:
            openable = bool(r.get("openable"))
            if st.button("↗ Editor", key=f"jr_open_{i}", disabled=not openable):
                _set_editor_open_request(r["_raw"] if isinstance(r.get("_raw"), dict) else r.to_dict())
                st.session_state["_jr_view_mode_next"] = "🧩 Editor"
                st.success("Editor 이동 요청 저장 (선택된 이슈 기준)")
                st.rerun()
        with c2:
            rule_id = str(r.get("rule") or "")
            description = gui_utils.rule_desc(rule_id, rule_catalog)
            st.caption(f"[{r.get('tool')}/{r.get('severity')}] {r.get('file')}:{int(r.get('line') or 0)}")
            
            if rule_id:
                st.text_input(
                    "Rule",
                    value=rule_id,
                    key=f"jr_finding_rule_tooltip_{i}",
                    disabled=True,
                    help=description or "설명 없음",
                    label_visibility="collapsed"
                )

            msg = str(r.get("message") or "")
            if msg:
                st.code(msg, language="text")


def _render_overview(summary: dict):
    j = (summary or {}).get("jenkins", {}) or {}
    cov = (summary or {}).get("coverage", {}) or {}
    tests = (summary or {}).get("tests", {}) or {}

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("빌드 번호", str(j.get("build_number", "-")))
        st.caption(j.get("job_url", ""))
    with c2:
        st.metric("빌드 결과", str(j.get("result") or ""))
        st.caption(j.get("build_url", ""))
    with c3:
        rate = cov.get("line_rate_pct")
        if rate is None:
            rate = cov.get("line_rate")
        thr = cov.get("threshold")
        lr01 = gui_utils.normalize_rate_0_1(rate)
        tr01 = gui_utils.normalize_rate_0_1(thr)
        st.metric("라인 커버리지", f"{(lr01*100.0):.1f}%" if lr01 is not None else "-")
        st.caption(f"threshold {(tr01*100.0):.1f}%" if tr01 is not None else "")
    with c4:
        ok = tests.get("ok")
        st.metric("테스트", "OK" if ok else "FAIL")
        basis = cov.get("basis", "")
        st.caption(basis)

    # progress bars
    rate_val = cov.get("line_rate_pct")
    if rate_val is None:
        rate_val = cov.get("line_rate")
    if isinstance(rate_val, (int, float)):
        r01 = gui_utils.normalize_rate_0_1(rate_val)
        if r01 is not None:
            st.progress(min(max(float(r01), 0.0), 1.0), text=f"Line: {float(r01)*100.0:.1f}%")
    if isinstance(cov.get("branch_rate"), (int, float)):
        r01 = gui_utils.normalize_rate_0_1(cov.get("branch_rate"))
        if r01 is not None:
            st.progress(min(max(float(r01), 0.0), 1.0), text=f"Branch: {float(r01)*100.0:.1f}%")
    if isinstance(cov.get("call_rate"), (int, float)):
        r01 = gui_utils.normalize_rate_0_1(cov.get("call_rate"))
        if r01 is not None:
            st.progress(min(max(float(r01), 0.0), 1.0), text=f"Call: {float(r01)*100.0:.1f}%")


def _render_vectorcast(summary: dict):
    vc = (summary or {}).get("vectorcast", {}) or {}
    if not vc:
        st.info("VectorCAST 리포트 파싱 결과 없음")
        return

    # UT/IT grand totals (metrics report)
    c1, c2 = st.columns(2)
    for col, (label, key) in zip([c1, c2], [("UT", "ut_metrics"), ("IT", "it_metrics")]):
        with col:
            m = vc.get(key) or {}
            gt = (m.get("grand_totals") or {}) if isinstance(m, dict) else {}
            st_cov = (gt.get("statements") or {}) if isinstance(gt, dict) else {}
            br_cov = (gt.get("branches") or {}) if isinstance(gt, dict) else {}
            if isinstance(st_cov, dict) and st_cov.get("total", 0):
                r01 = gui_utils.normalize_rate_0_1(st_cov.get('rate', 0.0)) or 0.0
                st.metric(f"{label} Statements", f"{r01*100.0:.1f}%")
            if isinstance(br_cov, dict) and br_cov.get("total", 0):
                r01 = gui_utils.normalize_rate_0_1(br_cov.get('rate', 0.0)) or 0.0
                st.metric(f"{label} Branches", f"{r01*100.0:.1f}%")

    # --- worst coverage drilldown (environment report) ---
    st.session_state.setdefault("vc_env_open", {"path": "", "file": ""})

    for label, key in [("UT", "ut_env"), ("IT", "it_env")]:
        env = vc.get(key)
        if not isinstance(env, dict) or not env.get("ok"):
            continue

        env_path = str(env.get("path") or "")
        p = Path(env_path) if env_path else None
        st.subheader(f"{label} 환경별 커버리지(파일 기준)")

        metric = st.radio(
            f"{label} worst 기준",
            options=["Statements", "Branches"],
            horizontal=True,
            key=f"vc_{label}_worst_metric",
        )
        worst = env.get("worst_statements") if metric == "Statements" else env.get("worst_branches")
        worst = worst or []

        # 목록(파일 클릭 시 해당 HTML에서 해당 행으로 점프)
        head = st.columns([3, 1, 1])
        head[0].markdown("**file**")
        head[1].markdown("**statements%**")
        head[2].markdown("**branches%**")

        for i, r in enumerate(worst[:20]):
            st_cov = (r.get("statements") or {}).get("rate")
            br_cov = (r.get("branches") or {}).get("rate")
            f = str(r.get("file") or "")
            cols = st.columns([3, 1, 1])
            with cols[0]:
                if st.button(f, key=f"vc_file_{label}_{metric}_{i}") and p and p.exists():
                    st.session_state["vc_env_open"] = {"path": str(p), "file": f, "label": label}
            cols[1].write(f"{float(st_cov)*100.0:.1f}" if isinstance(st_cov, (int, float)) else "-")
            cols[2].write(f"{float(br_cov)*100.0:.1f}" if isinstance(br_cov, (int, float)) else "-")

        # 미리보기
        opened = st.session_state.get("vc_env_open") or {}
        if opened.get("label") == label and opened.get("path"):
            op = Path(str(opened.get("path")))
            if op.exists():
                st.caption(f"Environment report: {op.name}  | jump: {opened.get('file')}")
                _render_html(op, height=760, env_row_target=str(opened.get("file") or ""))
            else:
                st.warning("선택한 HTML 파일이 존재하지 않음")

    # complexity.csv preview (if exists in reports_dir)
    # handled in main render below


def _load_vectorcast_rag(rdir: Optional[Path]) -> Dict[str, Any]:
    if not rdir:
        return {}
    p = rdir / "vectorcast_rag" / "vectorcast_rag.json"
    return gui_utils.load_json(p, default={}) if p.exists() else {}


def _render_vectorcast_detail(rdir: Optional[Path]) -> None:
    payload = _load_vectorcast_rag(rdir)
    rows = payload.get("test_rows") if isinstance(payload, dict) else None
    details = payload.get("testcase_details") if isinstance(payload, dict) else None
    has_rows = isinstance(rows, list) and bool(rows)
    has_details = isinstance(details, list) and bool(details)
    if not has_rows and not has_details:
        st.info("VectorCAST test details not available.")
        return

    if has_rows:
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame()

    if has_rows:
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            src_opts = sorted(df.get("source", pd.Series()).dropna().unique().tolist())
            src = st.multiselect("Source", options=src_opts, default=[], key="vcast_src_filter")
        with c2:
            req_q = st.text_input("Requirement ID filter", value="", key="vcast_req_filter")
        with c3:
            tc_q = st.text_input("Testcase filter", value="", key="vcast_tc_filter")

        stub_q = st.text_input("Stub filter", value="", key="vcast_stub_filter")

        df_f = df.copy()
        if src:
            df_f = df_f[df_f.get("source").isin(src)]
        if req_q.strip() and "requirement_id" in df_f.columns:
            df_f = df_f[df_f["requirement_id"].astype(str).str.contains(req_q.strip(), case=False, na=False)]
        if tc_q.strip() and "testcase" in df_f.columns:
            df_f = df_f[df_f["testcase"].astype(str).str.contains(tc_q.strip(), case=False, na=False)]
        if stub_q.strip():
            if "stubs_list" in df_f.columns:
                df_f = df_f[df_f["stubs_list"].astype(str).str.contains(stub_q.strip(), case=False, na=False)]
            elif "stubs" in df_f.columns:
                df_f = df_f[df_f["stubs"].astype(str).str.contains(stub_q.strip(), case=False, na=False)]

        show_cols = [c for c in [
            "source", "report", "unit", "subprogram", "testcase", "requirement_id",
            "test_script", "stubs", "stubs_list", "result", "environment"
        ] if c in df_f.columns]
        st.caption(f"rows={len(df_f)}")
        st.dataframe(df_f[show_cols], width="stretch", height=420)

    if has_details:
        st.subheader("Test Case Data")
        ddf = pd.DataFrame(details)
        if not ddf.empty:
            show_cols = [c for c in ["testcase", "configuration", "data", "input_data", "expected_data"] if c in ddf.columns]
            st.dataframe(ddf[show_cols], width="stretch", height=420)


def _render_vectorcast_simulation(rdir: Optional[Path]) -> None:
    if not rdir:
        st.info("reports dir not available.")
        return

    sim_json = rdir / "vectorcast_simulations.json"
    sim_md = rdir / "vectorcast_simulations.md"
    payload = _load_vectorcast_rag(rdir)
    rows = payload.get("test_rows") if isinstance(payload, dict) else []
    rows = rows if isinstance(rows, list) else []

    st.caption("Simulation = mock run (no real execution).")
    mode = st.radio("Mode", options=["UT", "IT"], horizontal=True, key="vcast_sim_mode")
    note = st.text_input("Note", value="", key="vcast_sim_note")

    if st.button(f"Simulate {mode}"):
        now = datetime.now().isoformat(timespec="seconds")
        src_rows = [r for r in rows if (r.get("source") == mode)]
        entry = {
            "time": now,
            "mode": mode,
            "note": note,
            "rows_count": len(src_rows),
            "status": "simulated",
        }
        try:
            prev = gui_utils.load_json(sim_json, default=[])
            if not isinstance(prev, list):
                prev = []
            prev.append(entry)
            sim_json.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
            lines = [
                "# VectorCAST Simulation History",
                "",
            ]
            for e in prev[-100:]:
                lines.append(f"- {e.get('time')} | {e.get('mode')} | rows={e.get('rows_count')} | {e.get('note')}")
            sim_md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
            st.success(f"Simulated {mode}: rows={len(src_rows)}")
        except Exception as e:
            st.error(f"Simulation save failed: {e}")


def _render_prqa(summary: dict):
    prqa = (summary or {}).get("prqa", {}) or {}
    if not prqa:
        st.info("PRQA(QAC) 요약 없음")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("CRR(Code Review) 요약")
        crr = prqa.get("crr") or {}
        if crr.get("ok"):
            st.json(crr.get("summary", {}))
        else:
            st.caption("CRR 없음/파싱 실패")
    with c2:
        st.subheader("RCR(Rule Compliance) 요약")
        rcr = prqa.get("rcr") or {}
        if rcr.get("ok"):
            st.json(rcr.get("summary", {}))
        else:
            st.caption("RCR 없음/파싱 실패")

    hmr = prqa.get("hmr") or {}
    if not hmr.get("ok"):
        st.caption("HMR(xlsx) 없음/파싱 실패")
        return

    st.subheader("HMR(HIS Metrics) 복잡도(v(G)) 분석")
    stats = hmr.get("stats", {}) or {}
    st.caption(f"functions_total={stats.get('functions_total')}, vg_max={stats.get('vg_max')}, vg_p95={stats.get('vg_p95')}, vg_mean={stats.get('vg_mean')}")

    rows = hmr.get("rows") or hmr.get("top_vg") or []
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("HMR 데이터 없음")
        return

    # normalize columns
    for col in ("file", "function"):
        if col in df.columns:
            df[col] = df[col].astype(str)
    if "vg" in df.columns:
        df["vg"] = pd.to_numeric(df["vg"], errors="coerce").fillna(0).astype(int)

    max_vg = int(df["vg"].max() if "vg" in df.columns and not df.empty else 0)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        min_vg = st.slider("min v(G)", 0, max(0, max_vg), value=min(10, max_vg), key="hmr_min_vg")
    with c2:
        topn = st.number_input("Top N(필터 적용 후)", min_value=10, max_value=1000, value=200, step=10, key="hmr_topn")
    with c3:
        file_q = st.text_input("파일 필터(부분 일치)", value="", key="hmr_file_q")

    df_f = df.copy()
    if file_q.strip():
        df_f = df_f[df_f["file"].str.contains(file_q.strip(), case=False, na=False)]
    df_f = df_f[df_f["vg"] >= int(min_vg)]

    # file-level grouping (chart/table)
    with st.expander("📁 소스 파일별 그룹핑", expanded=True):
        g = df_f.groupby("file", dropna=False).agg(
            functions=("function", "count"),
            vg_max=("vg", "max"),
            vg_mean=("vg", "mean"),
            calls_sum=("calls", "sum") if "calls" in df_f.columns else ("vg", "count"),
        ).reset_index()
        g = g.sort_values(["vg_max", "functions"], ascending=[False, False])
        st.dataframe(g.head(60), width="stretch", height=360)
        try:
            st.bar_chart(g.head(30).set_index("file")[["vg_max"]], height=320)
        except Exception:
            pass

    # choose files to drilldown
    files = sorted([x for x in df_f["file"].dropna().unique().tolist() if str(x).strip()])
    picked_files = st.multiselect("드릴다운 파일 선택(미선택=자동 Top)", options=files, default=[], key="hmr_files")
    if picked_files:
        df_d = df_f[df_f["file"].isin(picked_files)].copy()
    else:
        # auto: top files by vg_max
        top_files = (
            df_f.groupby("file")["vg"].max().sort_values(ascending=False).head(10).index.tolist()
        )
        df_d = df_f[df_f["file"].isin(top_files)].copy()

    # function-level table (after filters)
    df_d = df_d.sort_values(["vg", "calls"], ascending=[False, False]) if "calls" in df_d.columns else df_d.sort_values(["vg"], ascending=[False])
    df_d = df_d.head(int(topn))

    st.subheader("🔎 함수 단위 상세(파일별)")
    if df_d.empty:
        st.info("필터 조건에서 표시할 항목 없음")
        return

    show_cols = [c for c in ["function", "vg", "calls", "calling", "level", "file"] if c in df_d.columns]
    for f, sub in df_d.groupby("file"):
        vmax = int(sub["vg"].max()) if "vg" in sub.columns and not sub.empty else 0
        with st.expander(f"{f}  (n={len(sub)}, max v(G)={vmax})", expanded=False):
            st.dataframe(sub[show_cols], width="stretch", height=420)



# -----------------------------------------------------------------------------
# PRQA RCR(룰 컴플라이언스) 상세 파서
# -----------------------------------------------------------------------------

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


def _find_latest_matching(files: List[Path], patterns: List[str]) -> Optional[Path]:
    """파일 리스트에서 패턴(정규식/대소문자 무시)에 매칭되는 최신 파일 반환"""
    if not files:
        return None
    regs = [re.compile(p, re.I) for p in patterns if p]
    cand: List[Path] = []
    for p in files:
        name = p.name
        if any(r.search(name) for r in regs):
            cand.append(p)
    if not cand:
        return None
    cand.sort(key=lambda x: (x.stat().st_mtime if x.exists() else 0, x.name), reverse=True)
    return cand[0]


def _html_table_to_df(table) -> pd.DataFrame:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        rows.append([c.get_text(" ", strip=True) for c in cells])
    if not rows:
        return pd.DataFrame()
    header = rows[0]
    body = rows[1:]
    # header 중복/빈칸 처리
    header2 = []
    seen = {}
    for h in header:
        h = (h or "").strip() or "col"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        header2.append(h)
    df = pd.DataFrame(body, columns=header2)
    return df



def _load_findings_any(rdir: Optional[Path]) -> List[Dict[str, Any]]:
    """reports dir에서 findings 계열을 최대한 모아서 리스트로 반환"""
    if not rdir:
        return []
    cand_names = [
        "findings.json",
        "cpp_findings.json",
        "findings_synth.json",
        "findings_filled.json",
        "findings_merged.json",
    ]
    out: List[Dict[str, Any]] = []
    seen = set()
    for name in cand_names:
        p = (rdir / name)
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                key = (str(it.get("tool")), str(it.get("rule")), str(it.get("file")), str(it.get("line")), str(it.get("message")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
    return out


def _build_rule_desc_map(findings: List[Dict[str, Any]], max_per_rule: int = 3) -> Dict[str, str]:
    """룰별 대표 설명 생성, message 기반"""
    tmp: Dict[str, List[str]] = {}
    for it in findings:
        rule = (it.get("rule") or it.get("parent_rule") or it.get("rule_id") or "")
        rule = str(rule).strip()
        if not rule:
            continue
        msg = str(it.get("message") or it.get("desc") or it.get("description") or "").strip()
        if not msg:
            continue
        msg = re.sub(r"\s+", " ", msg)
        if rule not in tmp:
            tmp[rule] = []
        if msg not in tmp[rule] and len(tmp[rule]) < max_per_rule:
            tmp[rule].append(msg)
    out: Dict[str, str] = {}
    for rule, msgs in tmp.items():
        out[rule] = " / ".join(msgs)
    return out



def _parse_prqa_rcr_html(html_path: Path) -> Dict[str, Any]:
    """
    PRQA Rule Compliance Report(RCR)에서 주요 표 파싱
    - Diagnostics Per Parent Rules: 중요도(공통/의무/필수/합계) 파일별 분포
    - Most Violated Rules: 상위 룰 매트릭스(파일 x 룰)
    - File Status(있을 경우): 파일별 상태
    """
    if not html_path or not html_path.exists():
        return {}
    if BeautifulSoup is None:
        return {"_error": "bs4(BeautifulSoup) 미설치, pip install beautifulsoup4 필요"}
    try:
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    except Exception as e:
        return {"_error": f"RCR HTML 로드 실패: {e}"}

    def find_table_after_heading(title: str):
        h = soup.find(lambda tag: tag.name in ("h1", "h2", "h3", "h4") and title.lower() in tag.get_text(" ", strip=True).lower())
        if not h:
            return None
        return h.find_next("table")

    out: Dict[str, Any] = {}

    # 1) Diagnostics Per Parent Rules
    t1 = find_table_after_heading("Diagnostics Per Parent Rules")
    if t1:
        df1 = _html_table_to_df(t1)
        if not df1.empty:
            # 숫자 컬럼 변환
            for c in df1.columns:
                if c.lower() != "files":
                    df1[c] = pd.to_numeric(df1[c].astype(str).str.replace(",", ""), errors="coerce").fillna(0).astype(int)
            out["diagnostics_per_parent_rules"] = df1

            # Mandatory/Required 합계 추출(열 이름 기준)
            mand_req: Dict[str, int] = {}
            for c in df1.columns:
                cl = str(c).strip().lower()
                if "mandatory" in cl or "required" in cl:
                    try:
                        mand_req[str(c)] = int(pd.to_numeric(df1[c], errors="coerce").fillna(0).sum())
                    except Exception:
                        pass
            if mand_req:
                out["mandatory_required_totals"] = mand_req

    # 2) Most Violated Rules
    t2 = find_table_after_heading("Most Violated Rules")
    if t2:
        df2 = _html_table_to_df(t2)
        if not df2.empty:
            # 첫 컬럼 파일명, 나머지 룰 count
            for c in df2.columns[1:]:
                df2[c] = pd.to_numeric(df2[c].astype(str).str.replace(",", ""), errors="coerce").fillna(0).astype(int)
            out["most_violated_rules_matrix"] = df2

            # 룰별 합계
            rule_totals = df2.drop(columns=[df2.columns[0]]).sum(axis=0).sort_values(ascending=False)
            out["rule_totals"] = rule_totals.reset_index().rename(columns={"index": "rule", 0: "count"})

    # 3) File Status(있으면)
    t3 = find_table_after_heading("File Status")
    if t3:
        df3 = _html_table_to_df(t3)
        if not df3.empty:
            out["file_status"] = df3

    # 4) Detail diagnostics (file/line)
    detail_rows: List[Dict[str, Any]] = []
    try:
        def _pick_col(cols: List[str], keys: List[str]) -> Optional[str]:
            for c in cols:
                cl = str(c).strip().lower()
                for k in keys:
                    if k in cl:
                        return c
            return None

        seen = set()
        for table in soup.find_all("table"):
            df = _html_table_to_df(table)
            if df.empty:
                continue
            cols = [str(c) for c in df.columns]
            file_col = _pick_col(cols, ["file", "path", "source"])
            line_col = _pick_col(cols, ["line", "ln"])
            rule_col = _pick_col(cols, ["rule", "misra", "qac", "id"])
            msg_col = _pick_col(cols, ["message", "diagnostic", "description", "desc", "text"])
            sev_col = _pick_col(cols, ["severity", "level", "kind", "type"])
            if not file_col:
                continue
            for _, row in df.iterrows():
                fval = str(row.get(file_col) or "").strip()
                if not fval or fval.lower() in ("total", "summary"):
                    continue
                line_val = 0
                if line_col:
                    try:
                        line_val = int(str(row.get(line_col) or "").strip() or "0")
                    except Exception:
                        line_val = 0
                if line_val <= 0:
                    import re as _re
                    m = _re.search(r"[:(](\d+)[)]?$", fval)
                    if m:
                        try:
                            line_val = int(m.group(1))
                            fval = _re.sub(r"[:(]\d+[)]?$", "", fval).strip()
                        except Exception:
                            line_val = 0
                rule_val = str(row.get(rule_col) or "").strip() if rule_col else ""
                msg_val = str(row.get(msg_col) or "").strip() if msg_col else ""
                sev_val = str(row.get(sev_col) or "").strip() if sev_col else ""
                if not rule_val and msg_val:
                    import re as _re
                    m = _re.search(r"Rule\s*[-_]?(\d+(?:\.\d+)*)", msg_val, _re.I)
                    if m:
                        rule_val = f"Rule-{m.group(1)}"
                key = (fval, line_val, rule_val, msg_val)
                if key in seen:
                    continue
                seen.add(key)
                detail_rows.append({
                    "tool": "prqa_rcr_detail",
                    "severity": sev_val or "rcr",
                    "rule": rule_val,
                    "file": fval,
                    "line": line_val,
                    "message": msg_val,
                    "source": "rcr_detail",
                })
                if len(detail_rows) >= 2000:
                    break
            if len(detail_rows) >= 2000:
                break
    except Exception:
        detail_rows = []

    if detail_rows:
        out["detail_findings"] = detail_rows


    out["source_file"] = str(html_path)
    return out


def _render_prqa_rcr_detail(broot: Optional[Path], rdir: Optional[Path], artifacts: Optional[List[dict]]):
    st.subheader("📏 PRQA Rule Compliance(RCR) 상세")
    files = _collect_files(broot, rdir, artifacts)
    rcr = _find_latest_matching(files, [r"_RCR_.*\.html?$", r"rule.*compliance.*\.html?$"])
    if not rcr:
        st.info("RCR(룰 컴플라이언스) HTML 미발견, 아티팩트 패턴에 '*_RCR_*.html' 포함 확인 필요")
        return

    # Load the comprehensive rule catalog
    try:
        rule_catalog = gui_utils.load_rule_catalog(Path.cwd(), extra_roots=[p for p in [broot, rdir, (rdir.parent if rdir else None)] if p])
    except Exception:
        rule_catalog = {}

    parsed = _parse_prqa_rcr_html(rcr)
    if not parsed:
        st.warning("RCR 파싱 결과 없음")
        return
    if isinstance(parsed, dict) and parsed.get("_error"):
        st.error(parsed.get("_error"))
        st.caption(f"대상 파일: {rcr.name}")
        return

    st.caption(f"대상 파일: {rcr.name}")

    # 1) Diagnostics Per Parent Rules
    df_diag = parsed.get("diagnostics_per_parent_rules")
    if isinstance(df_diag, pd.DataFrame) and not df_diag.empty:
        st.markdown("#### 중요도(Parent Rules) 파일별 분포")
        mand_req = parsed.get("mandatory_required_totals")
        if isinstance(mand_req, dict) and mand_req:
            st.markdown("##### QAC Mandatory/Required 합계")
            mdf = pd.DataFrame([{"category": k, "count": v} for k, v in mand_req.items()])
            st.dataframe(mdf, width="stretch", height=180)
        show_n = st.slider("표시 파일 수(Top N)", min_value=10, max_value=200, value=50, step=10, key="rcr_topn_files")
        dfv = df_diag.copy()
        # Total Violations 컬럼 우선 정렬
        total_col = next((c for c in dfv.columns if "total" in c.lower()), None)
        if total_col:
            dfv = dfv.sort_values(total_col, ascending=False)
        st.dataframe(dfv.head(show_n), width="stretch", height=360)

        # 차트(Top 30)
        topc = dfv.head(min(30, len(dfv))).set_index(dfv.columns[0])
        # 범주 컬럼만 선택
        num_cols = [c for c in topc.columns if c != dfv.columns[0]]
        if num_cols:
            st.bar_chart(topc[num_cols], height=320)

        # 룰 위반 합계
        st.markdown("##### 전체 합계")
        sums = dfv.drop(columns=[dfv.columns[0]]).sum(axis=0).sort_values(ascending=False)
        sdf = sums.reset_index().rename(columns={"index": "category", 0: "count"})
        st.dataframe(sdf, width="stretch", height=200)

    # 2) Most violated rules
    df_rules = parsed.get("rule_totals")
    df_mat = parsed.get("most_violated_rules_matrix")
    if isinstance(df_rules, pd.DataFrame) and not df_rules.empty:
        st.markdown("#### 최다 위반 룰 Top")
        topn = st.slider("표시 룰 수(Top N)", min_value=5, max_value=200, value=15, step=5, key="rcr_topn_rules")
        q_rule = st.text_input("룰 검색(코드/설명)", value="", key="rcr_rule_q")
        min_cnt = st.number_input("최소 위반 수", min_value=0, max_value=99999, value=1, step=1, key="rcr_rule_min")

        df_show = df_rules.copy()
        if "rule" in df_show.columns and rule_catalog:
            df_show["설명"] = df_show["rule"].astype(str).map(lambda x: gui_utils.rule_desc(_normalize_rule_id(x), rule_catalog))
        if min_cnt and "count" in df_show.columns:
            try:
                df_show = df_show[pd.to_numeric(df_show["count"], errors="coerce").fillna(0) >= int(min_cnt)]
            except Exception:
                pass
        if q_rule.strip():
            qq = q_rule.strip().lower()
            try:
                df_show = df_show[
                    df_show["rule"].astype(str).str.lower().str.contains(qq)
                    | df_show.get("설명", pd.Series([], dtype=str)).astype(str).str.lower().str.contains(qq)
                ]
            except Exception:
                pass
        st.dataframe(df_show.head(topn), width="stretch", height=320)

        try:
            st.bar_chart(df_show.head(min(30, len(df_show))).set_index("rule")[["count"]], height=320)
        except Exception:
            pass


    if isinstance(df_mat, pd.DataFrame) and not df_mat.empty:
        st.markdown("#### 파일 x 룰 매트릭스(상위 룰)")
        # 사용자가 선택한 룰만 보기
        rule_cols = list(df_mat.columns[1:])
        default_sel = rule_cols[: min(8, len(rule_cols))]
        sel_rules = st.multiselect("표시할 룰", options=rule_cols, default=default_sel, key="rcr_rules_sel")
        cols = [df_mat.columns[0]] + (sel_rules or [])
        dfm = df_mat[cols].copy() if cols else df_mat.copy()
        st.dataframe(dfm.head(100), width="stretch", height=420)
        st.caption("표가 크면 상위 100행만 표시, 다운로드는 '파일 탐색/미리보기'에서 원본 HTML 선택 후 다운로드 권장")

    # 3) File status
    df_fs = parsed.get("file_status")
    if isinstance(df_fs, pd.DataFrame) and not df_fs.empty:
        with st.expander("File Status 표", expanded=False):
            st.dataframe(df_fs.head(200), width="stretch", height=420)


# -----------------------------------------------------------------------------
# Jenkins 캐시 빌드 히스토리(다운로드된 build_* 폴더 기준)
# -----------------------------------------------------------------------------

def _scan_cached_builds_from_build_root(broot: Optional[Path]) -> pd.DataFrame:
    if broot is None:
        return pd.DataFrame()
    p = Path(broot)
    job_dir = p.parent if p.name.startswith("build_") else p
    if not job_dir.exists():
        return pd.DataFrame()

    rows: List[dict] = []
    for d in job_dir.glob("build_*"):
        if not d.is_dir():
            continue
        m = re.match(r"build_(\d+)", d.name)
        bnum = int(m.group(1)) if m else -1

        # 기본 메타(폴더 mtime)
        dt = datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        rep_dir = d / "reports"
        summ_p = rep_dir / "analysis_summary.json"
        status_p = rep_dir / "status.json"

        result = ""
        tests_fail = None
        cov_line = None
        prqa_total = None

        if summ_p.exists():
            try:
                summ = json.loads(summ_p.read_text(encoding="utf-8", errors="ignore"))
                # Jenkins build result
                jb = summ.get("jenkins_build") or summ.get("build") or {}
                if isinstance(jb, dict):
                    result = str(jb.get("result") or jb.get("status") or "")
                # tests
                tests = summ.get("tests") or {}
                if isinstance(tests, dict):
                    tests_fail = tests.get("failed") or tests.get("failures")
                # coverage
                cov = summ.get("coverage") or {}
                if isinstance(cov, dict):
                    cov_line = (
                        cov.get("line_rate_pct")
                        or cov.get("line_rate")
                        or cov.get("line")
                        or cov.get("line_coverage")
                    )
                # prqa totals(있으면)
                prqa = summ.get("prqa") or {}
                if isinstance(prqa, dict):
                    prqa_total = prqa.get("total") or prqa.get("violations_total")
            except Exception:
                pass

        if status_p.exists() and not result:
            try:
                stj = json.loads(status_p.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(stj, dict):
                    result = str(stj.get("result") or stj.get("status") or result)
            except Exception:
                pass

        rows.append(
            {
                "build": bnum if bnum >= 0 else d.name,
                "mtime": dt,
                "result": result,
                "tests_failed": tests_fail,
                "coverage_line": cov_line,
                "prqa_total": prqa_total,
                "reports_dir": str(rep_dir) if rep_dir.exists() else "",
            }
        )

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # 정렬: build 번호 내림차순
    if "build" in df.columns:
        # build가 숫자 아닌 경우 대비
        try:
            df["_build_num"] = pd.to_numeric(df["build"], errors="coerce")
            df = df.sort_values(["_build_num", "mtime"], ascending=[False, False]).drop(columns=["_build_num"])
        except Exception:
            df = df.sort_values("mtime", ascending=False)
    return df


def _render_build_history(broot: Optional[Path]) -> None:
    st.subheader("📅 빌드 히스토리(캐시 기준)")
    df = _scan_cached_builds_from_build_root(broot)
    if df.empty:
        st.info("캐시된 build_* 폴더 미발견, Sync를 여러 빌드에 대해 수행 시 표시")
        return
    st.dataframe(df, width="stretch", height=360)
    # 간단 차트
    if "tests_failed" in df.columns:
        try:
            dft = df[["build", "tests_failed"]].copy()
            dft["tests_failed"] = pd.to_numeric(dft["tests_failed"], errors="coerce")
            dft = dft.dropna()
            if not dft.empty:
                st.bar_chart(dft.set_index("build")[["tests_failed"]], height=240)
        except Exception:
            pass
    if "coverage_line" in df.columns:
        try:
            dfc = df[["build", "coverage_line"]].copy()
            dfc["coverage_line"] = pd.to_numeric(dfc["coverage_line"], errors="coerce")
            dfc = dfc.dropna()
            if not dfc.empty:
                st.bar_chart(dfc.set_index("build")[["coverage_line"]], height=240)
        except Exception:
            pass


def _collect_files(build_root: Optional[Path], reports_dir: Optional[Path], artifacts: Optional[List[dict]]) -> List[Path]:
    """Jenkins Viewer 파일 수집
    우선순위
    1) reports_dir/jenkins_scan.json (빠름)
    2) artifacts 목록
    3) 제한된 확장자 패턴 rglob (fallback)
    """
    files: List[Path] = []
    broot = Path(build_root).resolve() if build_root else None
    rdir = Path(reports_dir).resolve() if reports_dir else None

    # 1) jenkins_scan.json 기반
    if broot and rdir:
        jp = rdir / "jenkins_scan.json"
        if jp.exists():
            try:
                data = json.loads(jp.read_text(encoding="utf-8", errors="ignore") or "{}")
                fdict = (data or {}).get("files", {}) or {}
                for cat in ("html", "xlsx", "log", "other"):
                    for rel in fdict.get(cat, []) or []:
                        try:
                            cand = (broot / str(rel)).resolve()
                            if cand.exists() and cand.is_file():
                                files.append(cand)
                        except Exception:
                            pass
            except Exception:
                pass

    # 2) artifacts 목록
    if artifacts and broot:
        for a in artifacts:
            rel = a.get("local_path") or a.get("path") or a.get("relativePath") or a.get("relative_path")
            if not rel:
                continue
            pp = Path(str(rel))
            cand = pp if pp.is_absolute() else (broot / str(rel))
            if cand.exists() and cand.is_file():
                files.append(cand)

    # 3) fallback 제한 스캔
    if not files:
        pats = ["*.html", "*.htm", "*.xlsx", "*.xls", "*.csv", "*.json", "*.xml", "*.log", "*.txt", "*.pdf"]
        if broot and broot.exists():
            for pat in pats:
                for p in broot.rglob(pat):
                    if p.is_file():
                        files.append(p)
        if rdir and rdir.exists():
            for pat in pats:
                for p in rdir.rglob(pat):
                    if p.is_file():
                        files.append(p)

    # dedup
    uniq: Dict[str, Path] = {}
    for p in files:
        try:
            uniq[str(p.resolve())] = p
        except Exception:
            uniq[str(p)] = p
    return sorted(uniq.values(), key=lambda p: (p.suffix.lower(), p.name.lower()))


def render_jenkins_reports(
    *,
    build_root: Optional[str],
    reports_dir: Optional[str],
    build_info: Optional[Dict[str, Any]] = None,
    artifacts: Optional[List[dict]] = None,
):
    """
    Jenkins Viewer 탭
    - reports_dir의 analysis_summary/status/jenkins_scan 기반 요약 + 차트
    - 파일(HTML/XLSX/CSV) 브라우저/미리보기
    """
    broot = _as_path(build_root)
    rdir = _as_path(reports_dir)

    # load summaries
    summary = _read_json(rdir / "analysis_summary.json" if rdir else None, default={})
    status = _read_json(rdir / "status.json" if rdir else None, default={})
    jscan = _read_json(rdir / "jenkins_scan.json" if rdir else None, default={})

    if not broot and not rdir:
        st.info("Jenkins 동기화 후 build_root/reports_dir가 설정되면 표시됨")
        return

    # Count diagnostics (RCR vs WARN token vs findings)
    rcr_total = None
    rcr_file = None
    rcr_parsed = None
    rcr_rules_df = None
    rcr_diag_df = None
    try:
        files = _collect_files(broot, rdir, artifacts)
        rcr = _find_latest_matching(files, [r"_RCR_.*\.html?$", r"rule.*compliance.*\.html?$"])
        if rcr:
            parsed = _parse_prqa_rcr_html(rcr)
            if isinstance(parsed, dict) and not parsed.get("_error"):
                rcr_parsed = parsed
                df_rules = parsed.get("rule_totals")
                if isinstance(df_rules, pd.DataFrame):
                    rcr_rules_df = df_rules
                    if "count" in df_rules.columns:
                        rcr_total = int(pd.to_numeric(df_rules["count"], errors="coerce").fillna(0).sum())
                if rcr_total is None:
                    df_diag = parsed.get("diagnostics_per_parent_rules")
                    if isinstance(df_diag, pd.DataFrame):
                        rcr_diag_df = df_diag
                        total_col = next((c for c in df_diag.columns if "total" in str(c).lower()), None)
                        if total_col:
                            rcr_total = int(pd.to_numeric(df_diag[total_col], errors="coerce").fillna(0).sum())
            rcr_file = rcr.name
    except Exception:
        pass

    st.session_state.setdefault("auto_fill_findings_json", True)
    # findings for Editor bridge
    findings_items = _collect_findings_for_editor(broot, rdir, summary if isinstance(summary, dict) else {})
    # Optional: include RCR-derived entries for filtering
    include_rcr = st.checkbox("RCR 항목을 Editor 목록에 포함", value=True, key="jr_include_rcr")
    include_rcr_detail = st.checkbox("RCR \uc0c1\uc138(\ud30c\uc77c/\ub77c\uc778) \ud3ec\ud568", value=True, key="jr_include_rcr_detail")
    if include_rcr and rcr_parsed:
        rcr_items = []
        if isinstance(rcr_rules_df, pd.DataFrame) and not rcr_rules_df.empty:
            for _, row in rcr_rules_df.head(300).iterrows():
                rule_id = str(row.get("rule") or "")
                try:
                    cnt = int(pd.to_numeric(row.get("count"), errors="coerce"))
                except Exception:
                    cnt = int(row.get("count") or 0)
                if not rule_id:
                    continue
                rcr_items.append({
                    "tool": "prqa_rcr",
                    "severity": "rcr",
                    "rule": rule_id,
                    "message": f"RCR rule violations: {cnt}",
                    "file": "",
                    "line": 0,
                    "source": "rcr_rule",
                })
        if isinstance(rcr_diag_df, pd.DataFrame) and not rcr_diag_df.empty:
            file_col = rcr_diag_df.columns[0]
            total_col = next((c for c in rcr_diag_df.columns if "total" in str(c).lower()), None)
            if total_col:
                for _, row in rcr_diag_df.head(300).iterrows():
                    fpath = str(row.get(file_col) or "")
                    if not fpath:
                        continue
                    cnt = int(pd.to_numeric(row.get(total_col), errors="coerce").fillna(0))
                    rcr_items.append({
                        "tool": "prqa_rcr",
                        "severity": "rcr",
                        "rule": "RCR:FileTotal",
                        "message": f"RCR total violations in file: {cnt}",
                        "file": fpath,
                        "line": 0,
                        "source": "rcr_file",
                    })
        if include_rcr_detail:
            detail = rcr_parsed.get("detail_findings") if isinstance(rcr_parsed, dict) else None
            if isinstance(detail, list) and detail:
                rcr_items.extend(detail[:2000])

        if rcr_items:
            findings_items = list(findings_items or []) + rcr_items
    # Count diagnostics panel
    try:
        warn_token = int(((jscan or {}).get("summary") or {}).get("WARN_token", 0))
        findings_json_count = None
        if rdir:
            fj = _read_json(rdir / "findings.json", default=None)
            if isinstance(fj, list):
                findings_json_count = len(fj)
            elif isinstance(fj, dict):
                items = fj.get("items") or fj.get("findings") or fj.get("issues") or []
                findings_json_count = len(items) if isinstance(items, list) else 0
        with st.expander("\uce74\uc6b4\ud2b8 \uc9c4\ub2e8", expanded=False):
            st.caption("\uacbd\uace0 \ud1a0\ud070\uc740 \ub85c\uadf8/HTML \ubb38\uc790\uc5f4 \uc2a4\uce94 \uacb0\uacfc\uc774\uba70, RCR \ub8f0 \uc704\ubc18 \ud569\uacc4\uc640 \ub3d9\uc77c\ud558\uc9c0 \uc54a\uc744 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
            st.write(
                f"\uacbd\uace0 \ud1a0\ud070: {warn_token} / "
                f"RCR \ub8f0 \uc704\ubc18 \ud569\uacc4: {rcr_total if rcr_total is not None else '-'} / "
                f"findings.json: {findings_json_count if findings_json_count is not None else '-'} / "
                f"Editor \ud45c\uc2dc(\ud569\uc131 \ud3ec\ud568): {len(findings_items) if isinstance(findings_items, list) else 0}"
            )
            if rcr_file:
                st.caption(f"RCR source: {rcr_file}")
            if rcr_total is not None and warn_token is not None and rcr_total != warn_token:
                st.warning("\uacbd\uace0 \ud1a0\ud070\uacfc RCR \ub8f0 \uc704\ubc18 \ud569\uacc4\uac00 \ub2e4\ub985\ub2c8\ub2e4. RCR(\ub8f0 \uc704\ubc18)\uacfc \ub85c\uadf8 \uacbd\uace0 \ud1a0\ud070\uc740 \uc9d1\uacc4 \uae30\uc900\uc774 \ub2e4\ub985\ub2c8\ub2e4.")
    except Exception:
        pass

    # rule label normalization
    try:
        for it in findings_items:
            if isinstance(it, dict) and it.get('rule') is not None:
                it['rule'] = _normalize_rule_id(it.get('rule'))
    except Exception:
        pass

    # pseudo-tabs (수평 토글)
    st.session_state.setdefault("jr_view_mode", "📦 Reports")
    # jr_view_mode 위젯 생성 전, 요청된 뷰 모드 적용 처리
    next_vm = st.session_state.pop("_jr_view_mode_next", None)
    if next_vm:
        st.session_state["jr_view_mode"] = next_vm

    view_mode = st.radio("보기", options=["📦 Reports", "🧩 Editor"], horizontal=True, key="jr_view_mode")

    if view_mode == "🧩 Editor":
        st.header("🧩 Editor (Jenkins Viewer)")
        if editor_tab is None or not hasattr(editor_tab, "render_editor"):
            st.error("editor 모듈 로드 실패, /app/gui/tabs/editor.py 경로 및 import 구조 확인 필요")
            return
        # build/job 정보 추출 (키/캐시용)
        job_url = (summary or {}).get("jenkins", {}).get("job_url", "") or (build_info or {}).get("job_url", "")
        build_no = (summary or {}).get("jenkins", {}).get("build_number", "") or (build_info or {}).get("build_number", "")
        if not build_no and broot:
            build_no = str(broot.name).replace("build_", "")
        key_base = f"{_job_slug(job_url)}:{build_no}"

        source_roots = _collect_source_roots(broot, rdir, summary if isinstance(summary, dict) else {})
        project_root_guess = _guess_project_root(broot, rdir, summary if isinstance(summary, dict) else {})
        if not source_roots:
            source_roots = [project_root_guess]

        # 선택값 복원/저장
        ss_key = f"jr_code_root:{key_base}"
        st.session_state.setdefault(ss_key, source_roots[0])
        try:
            cur = st.session_state.get(ss_key) or source_roots[0]
        except Exception:
            cur = source_roots[0]
        try:
            idx0 = source_roots.index(cur) if cur in source_roots else 0
        except Exception:
            idx0 = 0

        sel_root = st.selectbox("코드 루트", options=source_roots, index=idx0, key=f"jr_code_root_sel:{key_base}")
        st.session_state[ss_key] = sel_root
        st.session_state["viewer_project_root"] = sel_root
        st.session_state["viewer_code_root"] = sel_root
        st.session_state["viewer_source_roots"] = source_roots
        st.caption(f"project_root: {sel_root}")

        # AI 설정 경로는 환경마다 다름, 필요 시 수동 입력
        st.session_state.setdefault("jr_oai_config_path", "")
        oai_path = st.text_input(
            "oai_config_path(옵션)",
            value=str(st.session_state.get("jr_oai_config_path") or ""),
            key="jr_oai_config_path",
        )
        editor_prefix = f"jr_editor:{key_base}"

        st.warning("Deviation 처리에 문제가 있으면 반드시 수정해야 합니다. 승인되지 않은 경고는 그대로 넘기지 마세요.")

        rule_catalog = gui_utils.load_rule_catalog(
            Path.cwd(),
            extra_roots=[p for p in [broot, rdir, (rdir.parent if rdir else None)] if p],
        )

        with st.expander("Deviation 배치 처리/엑셀", expanded=False):
            if not rdir:
                st.info("reports_dir가 없어서 Deviation 배치 처리를 사용할 수 없습니다.")
            else:
                st.caption("WARN 중심으로 Deviation을 자동 생성하고 .xlsx로 내보낼 수 있습니다.")
                author = st.text_input("author(선택)", value="", key=f"{editor_prefix}_dev_author")
                only_warn = st.checkbox("WARN만 자동 처리", value=True, key=f"{editor_prefix}_dev_warn_only")
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("WARN Deviation 자동 생성", key=f"{editor_prefix}_dev_auto"):
                        res = gui_utils.auto_deviations_for_findings(
                            findings_items,
                            rdir,
                            rule_catalog=rule_catalog,
                            only_warnings=only_warn,
                            default_author=author,
                            status="Pending",
                        )
                        st.session_state[f"{editor_prefix}_dev_last"] = res
                        st.success(f"생성 {res.get('created', 0)}건, 건너뜀 {res.get('skipped', 0)}건 (총 {res.get('total', 0)}건)")
                with c2:
                    if st.button("Deviation .xlsx 내보내기", key=f"{editor_prefix}_dev_export"):
                        out = gui_utils.export_deviations_xlsx(rdir)
                        if out:
                            st.session_state[f"{editor_prefix}_dev_xlsx"] = str(out)
                            st.success(f"저장됨: {out}")
                        else:
                            st.error("xlsx 내보내기 실패: pandas가 필요할 수 있습니다.")
                out_path = st.session_state.get(f"{editor_prefix}_dev_xlsx")
                if out_path:
                    try:
                        _download_button(Path(out_path), "Deviation .xlsx 다운로드")
                    except Exception:
                        pass

                last_res = st.session_state.get(f"{editor_prefix}_dev_last")
                if isinstance(last_res, dict):
                    with st.expander("Deviation 생성 상세", expanded=False):
                        st.caption(f"batch_id: {last_res.get('batch_id')}")
                        st.write(
                            f"생성 {int(last_res.get('created') or 0)}건, "
                            f"건너뜀 {int(last_res.get('skipped') or 0)}건, "
                            f"총 {int(last_res.get('total') or 0)}건"
                        )
                        st.caption(
                            "건너뜀 사유: "
                            f"WARN 아님 {int(last_res.get('skipped_non_warn') or 0)}건, "
                            f"중복 {int(last_res.get('skipped_duplicate') or 0)}건, "
                            f"형식 오류 {int(last_res.get('skipped_invalid') or 0)}건"
                        )
                        items = last_res.get("items") if isinstance(last_res.get("items"), list) else []
                        if items:
                            try:
                                st.dataframe(items, width="stretch", height=260)
                            except Exception:
                                st.code("\n".join([str(i) for i in items[:50]]), language="text")

        editor_tab.render_editor(
            sel_root,
            findings_items,
            status,
            oai_config_path=oai_path or None,
            suppressions_path=None,
            reports_dir=rdir,
            rule_catalog=rule_catalog,
            widget_key_prefix=editor_prefix,
        )
        return

        
    # ---- Overview ----
    st.header("📦 Jenkins 리포트 (요약/분석)")
    if summary:
        _render_overview(summary)

    # KPI / EXT charts
    with st.expander("📌 Jenkins 스캔 요약", expanded=True):
        kpi_df = _build_kpi_df(jscan)
        ext_df = _build_ext_df(jscan)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("FAIL/ERROR/WARN/PASS 토큰")
            if not kpi_df.empty:
                st.dataframe(kpi_df, width="stretch", height=220)
                st.bar_chart(kpi_df.set_index("KPI"), height=260)
        with c2:
            st.subheader("확장자 분포(Top 25)")
            if not ext_df.empty:
                st.dataframe(ext_df, width="stretch", height=220)
                st.bar_chart(ext_df.set_index("ext"), height=260)

        summ = (jscan or {}).get("summary", {})
        st.caption(f"files_total={summ.get('files_total')}, bytes_total={summ.get('bytes_total')}")

    # ---- Findings -> Editor bridge ----
    with st.expander("🧩 룰 위반/이슈 → Editor 열기", expanded=False):
        _render_findings_editor_bridge(findings_items, broot=broot, rdir=rdir)
    
    # ---- Deeper summaries ----
    with st.expander("🧪 VectorCAST 요약", expanded=False):
        _render_vectorcast(summary)
        with st.expander("VectorCAST Details (requirements/tests/stubs)", expanded=False):
            _render_vectorcast_detail(rdir)
        with st.expander("VectorCAST UT/IT Simulation", expanded=False):
            _render_vectorcast_simulation(rdir)

        # complexity.csv
        if rdir:
            cpath = rdir / "complexity.csv"
            if cpath.exists():
                try:
                    cdf = pd.read_csv(cpath)
                    st.subheader("복잡도(Top 20)")
                    top = cdf.sort_values("ccn", ascending=False).head(20)
                    st.dataframe(top, width="stretch", height=360)
                    st.bar_chart(top.set_index("function")[["ccn"]], height=320)
                except Exception as e:
                    st.caption(f"complexity.csv 읽기 실패: {e}")

    with st.expander("🧾 PRQA(QAC) 요약", expanded=False):
        _render_prqa(summary)

    with st.expander("📏 PRQA Rule Compliance(RCR) 상세", expanded=False):
        _render_prqa_rcr_detail(broot, rdir, artifacts)

    # ---- File browser ----
    st.divider()
    st.subheader("파일 탐색/미리보기")

    files = _collect_files(broot, rdir, artifacts)
    # filter
    ext_options = sorted({p.suffix.lower() for p in files if p.suffix})
    default_cands = [".html", ".xlsx", ".csv"]
    default_ext = [x for x in default_cands if x in ext_options]

    # 세션에 저장된 이전 선택값이 options 밖이면 Streamlit이 예외 발생, 교집합으로 정규화
    prev = st.session_state.get("jr_ext_filter")
    if isinstance(prev, str):
        prev = [prev]
    if isinstance(prev, (list, tuple, set)):
        st.session_state["jr_ext_filter"] = [x for x in list(prev) if x in ext_options]

    only = st.multiselect(
        "확장자 필터",
        options=ext_options,
        default=default_ext,
        key="jr_ext_filter",
    )
    view_files = [p for p in files if (not only or p.suffix.lower() in only)]
    labels = []
    for p in view_files:
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        labels.append(f"{p.name}  ({size} bytes)")

    if not view_files:
        st.info("표시할 파일 없음")
        return

    sel_idx = st.selectbox("파일 선택", range(len(view_files)), format_func=lambda i: labels[i])
    sel = view_files[int(sel_idx)]

    st.caption(str(sel))
    c1, c2 = st.columns([1, 1])
    with c1:
        _download_button(sel, "📥 파일 다운로드")
    with c2:
        st.caption(f"mtime={sel.stat().st_mtime if sel.exists() else '-'}")

    # preview
    suffix = sel.suffix.lower()
    if suffix in (".html", ".htm"):
        _render_html(sel, height=760)
    elif suffix in (".xlsx", ".xlsm", ".xls"):
        _render_xlsx(sel)
    elif suffix in (".csv",):
        try:
            df = pd.read_csv(sel)
            st.dataframe(df, width="stretch", height=520)
        except Exception:
            st.text(sel.read_text(errors="ignore")[:200000])
    else:
        st.caption(f"{sel.name}  ({sel.stat().st_size} bytes)")
        try:
            st.text(sel.read_text(errors="ignore")[:200000])
        except Exception:
            st.info("텍스트로 표시 불가(바이너리 가능)")
