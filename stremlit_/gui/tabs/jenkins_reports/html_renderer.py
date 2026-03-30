# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from .utils import _download_button, _find_in_file, _human_bytes, _read_text_slice, _read_text_tail


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
            wrapper = """
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
  const base = tf.replaceAll('\\\\','/').split('/').pop();
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
"""
            return wrapper.format(rows=html_rows, tf_js=json.dumps(tf), safe_tf=safe_tf).strip()
        finally:
            mm.close()


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

    embed_limit = 3 * 1024 * 1024  # 3MiB
    if size <= embed_limit:
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
                    st.success(f"검색 위치로 이동: {_human_bytes(pos)}")

        # 오프셋 지정
        if mode == "오프셋(MB)":
            try:
                size_mb = max(1.0, float(size) / (1024.0 * 1024.0))
            except Exception:
                size_mb = 1.0
            off_mb = st.number_input(
                "시작 오프셋(MB)",
                min_value=0.0,
                max_value=float(size_mb),
                value=float(st.session_state[sk]) / (1024.0 * 1024.0),
                step=1.0,
                key=f"big_html_offmb_{path}",
            )
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


__all__ = ["_extract_env_rows_snippet", "_extract_html_wrapper", "_inject_env_row_scroll_js", "_render_html"]
