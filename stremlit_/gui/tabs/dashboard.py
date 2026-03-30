# /app/gui/tabs/dashboard.py
from __future__ import annotations

import json
import re
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import gui_utils
import report_generator
import config


# ------------------------------------------------------------
# Internal helpers (Data Processing)
def _paged_dataframe(df: pd.DataFrame, *, key: str, page_size_default: int = 1000, height: int = 420) -> None:
    if df is None or df.empty:
        st.info("표시할 데이터 없음")
        return

    total = int(len(df))
    max_render = 200000
    if total > max_render:
        st.warning(f"rows {total} 중 {max_render}까지만 렌더링, 전체는 원본 파일/리포트로 확인")
        df = df.iloc[:max_render].copy()
        total = int(len(df))

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        page_size = st.number_input("page size", min_value=50, max_value=5000, value=int(page_size_default), step=50, key=f"{key}_ps")
    with c2:
        page = st.number_input("page", min_value=1, max_value=max(1, (total - 1)//int(page_size) + 1), value=1, step=1, key=f"{key}_pg")
    with c3:
        st.caption(f"rows {total}, showing {(page-1)*page_size+1} - {min(total, page*page_size)}")

    start = (int(page)-1)*int(page_size)
    end = min(total, start + int(page_size))
    st.dataframe(df.iloc[start:end].copy(), width="stretch", height=height, hide_index=True)

# ------------------------------------------------------------
def _safe_dict(x) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _find_source_roots(root: Optional[Path]) -> List[Path]:
    roots: List[Path] = []
    try:
        cand = st.session_state.get("viewer_source_roots")
        if isinstance(cand, list):
            for p in cand:
                try:
                    rp = Path(str(p)).resolve()
                    if rp.exists() and rp.is_dir():
                        roots.append(rp)
                except Exception:
                    continue
    except Exception:
        pass

    if root:
        try:
            rr = Path(str(root)).resolve()
            if rr.exists() and rr.is_dir():
                roots.append(rr)
        except Exception:
            pass
        # Jenkins build_root candidates from session
        for key in ("viewer_build_root", "jenkins_build_root"):
            try:
                v = st.session_state.get(key)
                if v:
                    br = Path(str(v)).resolve()
                    if br.exists() and br.is_dir():
                        roots.append(br)
            except Exception:
                continue
        # build_root pattern
        broot = _find_build_root_from_path(rr) if root else None
        if broot:
            roots.append(broot)
            for name in ("svn_wc", "svn_wc1", "svn_wc2", "workspace", "repo", "app", "source", "src"):
                cand = broot / name
                if cand.exists() and cand.is_dir():
                    roots.append(cand)
            for rel in (
                "svn_wc/Sources",
                "svn_wc/Sources/APP",
                "svn_wc/Sources/AP",
                "app/PDSM/Sources",
                "app/PDSM/Sources/APP",
                "app/PDSM/Sources/AP",
                "Sources",
                "source",
                "src",
            ):
                cand = broot / rel
                if cand.exists() and cand.is_dir():
                    roots.append(cand)
            try:
                for cand in broot.iterdir():
                    if cand.is_dir() and cand.name.startswith("svn_wc"):
                        roots.append(cand)
                        s2 = cand / "Sources"
                        if s2.exists() and s2.is_dir():
                            roots.append(s2)
            except Exception:
                pass
        for sub in (
            "src",
            "source",
            "sources",
            "app",
            "apps",
            "lib",
            "libs",
            "include",
            "inc",
            "core",
            "modules",
            "components",
            "drivers",
            "platform",
            "hal",
            "middleware",
            "tests",
        ):
            try:
                rp = (root / sub).resolve()
                if rp.exists() and rp.is_dir():
                    roots.append(rp)
            except Exception:
                continue

    uniq: List[Path] = []
    seen = set()
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _collect_source_files(roots: List[Path], limit: int = 500, max_size_mb: int = 4) -> List[Path]:
    exts = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx"}
    out: List[Path] = []
    for r in roots:
        try:
            for p in r.rglob("*"):
                if len(out) >= limit:
                    return out
                if not p.is_file():
                    continue
                if p.suffix.lower() not in exts:
                    continue
                try:
                    if p.stat().st_size > max_size_mb * 1024 * 1024:
                        continue
                except Exception:
                    continue
                out.append(p)
        except Exception:
            continue
    return out


def _rel_from_roots(p: Path, roots: List[Path]) -> str:
    for r in roots:
        try:
            return str(p.resolve().relative_to(r.resolve()).as_posix())
        except Exception:
            continue
    return p.name


def _is_abs_path(s: str) -> bool:
    try:
        if not s:
            return False
        if s.startswith("/"):
            return True
        return bool(re.match(r"^[A-Za-z]:[\\/]", s))
    except Exception:
        return False


def _find_build_root_from_path(p: Path) -> Optional[Path]:
    try:
        cur = p.resolve()
        for _ in range(12):
            if cur.name.startswith("build_"):
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    except Exception:
        pass
    return None


def _normalize_file_for_search(raw_file: str, primary_root: Path) -> str:
    rf = (raw_file or "").replace("\\", "/").strip()
    if not rf:
        return ""
    if rf.endswith(".svn-base"):
        rf = rf[: -len(".svn-base")]
    if not _is_abs_path(rf):
        return rf.lstrip("./")
    try:
        p = Path(rf)
        try:
            rel = p.resolve().relative_to(primary_root.resolve())
            return rel.as_posix()
        except Exception:
            pass
        broot = _find_build_root_from_path(p)
        if broot is not None:
            try:
                rel = p.resolve().relative_to(broot.resolve())
                return rel.as_posix()
            except Exception:
                pass
        parts = [x for x in p.parts if x not in ("/", "\\")]
        tail = parts[-6:] if len(parts) > 6 else parts
        return "/".join([t.strip("/\\") for t in tail if t])
    except Exception:
        return Path(rf).name


def _resolve_source_path(rel: str, roots: List[Path], *, debug: Optional[List[str]] = None) -> Optional[Path]:
    if not rel:
        return None
    rel_norm = _normalize_file_for_search(str(rel), roots[0] if roots else Path.cwd())
    if debug is not None:
        debug.append(f"normalized_rel: {rel_norm}")
    # apply viewer path maps if available
    try:
        maps = st.session_state.get("viewer_path_maps")
        if isinstance(maps, list):
            for m in maps:
                if not isinstance(m, dict):
                    continue
                src = str(m.get("src") or "").replace("\\", "/").rstrip("/")
                dst = str(m.get("dst") or "").replace("\\", "/").rstrip("/")
                if not src or not dst:
                    continue
                if rel_norm.startswith(src):
                    mapped = rel_norm.replace(src, dst, 1).lstrip("/")
                    if debug is not None:
                        debug.append(f"path_map: {rel_norm} -> {mapped}")
                    try:
                        mp = Path(mapped)
                        if mp.is_absolute() and mp.exists() and mp.is_file():
                            if debug is not None:
                                debug.append(f"resolved: {mp}")
                            return mp
                    except Exception:
                        pass
                    for r in roots:
                        try:
                            p = (r / mapped).resolve()
                            if p.exists() and p.is_file():
                                if debug is not None:
                                    debug.append(f"resolved: {p}")
                                return p
                        except Exception:
                            continue
    except Exception:
        pass
    parts = [x for x in rel_norm.split("/") if x]
    # direct join
    for r in roots:
        try:
            p = (r / rel_norm).resolve()
            if p.exists() and p.is_file():
                if debug is not None:
                    debug.append(f"resolved: {p}")
                return p
        except Exception:
            continue
    # tail join (handles mismatched prefixes)
    for r in roots:
        for k in range(min(12, len(parts)), 0, -1):
            tail = "/".join(parts[-k:])
            try:
                p = (r / tail).resolve()
                if p.exists() and p.is_file():
                    if debug is not None:
                        debug.append(f"resolved: {p}")
                    return p
            except Exception:
                continue
    # fallback: filename only
    name = Path(rel_norm).name
    for r in roots:
        try:
            matches: List[Path] = []
            for p in r.rglob("*"):
                if not p.is_file():
                    continue
                if p.name.lower() == name.lower():
                    matches.append(p)
                    if len(matches) >= 8:
                        break
            if matches:
                if debug is not None:
                    debug.append(f"basename_matches[{len(matches)}] in {r}")
                    for m in matches[:5]:
                        debug.append(f"- {m}")
                return matches[0]
        except Exception:
            continue
    return None


def _normalize_symbol_name(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    if s.endswith(")") and "(" in s:
        s = s.split("(")[0].strip()
    return s


def _read_text_smart(path: Path, *, debug: Optional[List[str]] = None) -> str:
    try:
        raw = path.read_bytes()
    except Exception as exc:
        if debug is not None:
            debug.append(f"read_error: {path} ({exc})")
        return ""
    sample = raw[:4096]
    encodings = []
    if b"\x00" in sample:
        encodings = ["utf-16", "utf-16-le", "utf-16-be", "utf-8", "cp949"]
    else:
        encodings = ["utf-8", "cp949", "latin-1"]
    for enc in encodings:
        try:
            text = raw.decode(enc, errors="ignore")
            if debug is not None:
                debug.append(f"decode: {enc}")
            return text
        except Exception:
            continue
    return ""


def _skip_ws_and_comments(text: str, idx: int) -> int:
    n = len(text)
    i = idx
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        if text.startswith("//", i):
            nl = text.find("\n", i + 2)
            if nl < 0:
                return n
            i = nl + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                return n
            i = end + 2
            continue
        break
    return i


def _match_paren(text: str, idx: int) -> int:
    if idx < 0 or idx >= len(text) or text[idx] != "(":
        return -1
    depth = 0
    i = idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        elif ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    i = j
                    break
                j += 1
        i += 1
    return -1


def _skip_attributes(text: str, idx: int) -> int:
    i = _skip_ws_and_comments(text, idx)
    # Skip common attributes between signature and body.
    for _ in range(4):
        if text.startswith("__attribute__", i):
            paren = text.find("(", i)
            end = _match_paren(text, paren) if paren >= 0 else -1
            if end < 0:
                return i
            i = _skip_ws_and_comments(text, end + 1)
            continue
        if text.startswith("__declspec", i):
            paren = text.find("(", i)
            end = _match_paren(text, paren) if paren >= 0 else -1
            if end < 0:
                return i
            i = _skip_ws_and_comments(text, end + 1)
            continue
        if text.startswith("ASM", i):
            paren = text.find("(", i)
            end = _match_paren(text, paren) if paren >= 0 else -1
            if end < 0:
                return i
            i = _skip_ws_and_comments(text, end + 1)
            continue
        break
    return i


def _find_function_definition(text: str, fn: str) -> Tuple[int, int]:
    if not text or not fn:
        return -1, -1
    name_pat = re.compile(rf"\\b{re.escape(fn)}\\b", re.I)
    for m in name_pat.finditer(text):
        name_idx = m.start()
        pos = _skip_ws_and_comments(text, m.end())
        if pos >= len(text) or text[pos] != "(":
            continue
        end_paren = _match_paren(text, pos)
        if end_paren < 0:
            continue
        scan = _skip_attributes(text, end_paren + 1)
        if scan < len(text) and text[scan] == "{":
            return name_idx, scan
        # K&R or macro-heavy style: allow a few lines between ")" and "{"
        i = scan
        line_budget = 20
        while i < len(text) and line_budget > 0:
            i = _skip_ws_and_comments(text, i)
            if i >= len(text):
                break
            if text[i] == "{":
                return name_idx, i
            # Prototype or declaration terminator: stop and continue search.
            if text[i] == ";":
                break
            # Skip preprocessor lines.
            if text[i] == "#":
                nl = text.find("\n", i)
                if nl < 0:
                    break
                i = nl + 1
                line_budget -= 1
                continue
            nl = text.find("\n", i)
            if nl < 0:
                break
            i = nl + 1
            line_budget -= 1
    return -1, -1


def _find_function_definition_loose(text: str, fn: str) -> Tuple[int, int]:
    if not text or not fn:
        return -1, -1
    lower_text = text.lower()
    lower_fn = fn.lower()
    start = 0
    while True:
        idx = lower_text.find(lower_fn, start)
        if idx < 0:
            return -1, -1
        pos = _skip_ws_and_comments(text, idx + len(fn))
        if pos >= len(text) or text[pos] != "(":
            start = idx + 1
            continue
        end_paren = _match_paren(text, pos)
        if end_paren < 0:
            start = idx + 1
            continue
        scan = _skip_attributes(text, end_paren + 1)
        if scan < len(text) and text[scan] == "{":
            return idx, scan
        i = scan
        line_budget = 20
        while i < len(text) and line_budget > 0:
            i = _skip_ws_and_comments(text, i)
            if i >= len(text):
                break
            if text[i] == "{":
                return idx, i
            if text[i] == ";":
                break
            if text[i] == "#":
                nl = text.find("\n", i)
                if nl < 0:
                    break
                i = nl + 1
                line_budget -= 1
                continue
            nl = text.find("\n", i)
            if nl < 0:
                break
            i = nl + 1
            line_budget -= 1
        start = idx + 1


def _build_function_snippet_context(items: List[str], roots: List[Path]) -> Tuple[List[str], List[str]]:
    context_lines: List[str] = []
    debug_lines: List[str] = []
    debug_lines.append("source_roots:")
    for r in roots:
        debug_lines.append(f"- {r}")
    for item in items:
        try:
            if "::" in item:
                file_part, fn = [s.strip() for s in item.split("::", 1)]
            else:
                file_part, fn = "", item.strip()
            fn = _normalize_symbol_name(fn)
            debug_lines.append(f"resolve_request: {file_part} :: {fn}")
            src_path = _resolve_source_path(file_part, roots, debug=debug_lines) if file_part else None
            if src_path:
                text = _read_text_smart(src_path, debug=debug_lines)
                snip = _extract_function_snippet(text, fn, max_lines=80)
                if not snip and fn.startswith(("g_", "s_", "m_")):
                    snip = _extract_function_snippet(text, fn[2:], max_lines=80)
                if snip:
                    context_lines.append(f"[{file_part} :: {fn}]")
                    context_lines.append(snip)
                else:
                    debug_lines.append(f"snippet_not_found: {fn} in {src_path}")
                    context_lines.append(f"[{file_part} :: {fn}] (snippet not found)")
            else:
                context_lines.append(f"[{file_part} :: {fn}] (source not resolved)")
        except Exception:
            continue
    return context_lines, debug_lines


def _extract_function_snippet(text: str, fn: str, *, max_lines: int = 80) -> str:
    if not text or not fn:
        return ""
    fn = _normalize_symbol_name(fn)
    if not fn:
        return ""
    def _extract_block_from_index(start_idx: int) -> str:
        tail = text[start_idx:]
        brace_idx = tail.find("{")
        if brace_idx < 0:
            return ""
        body = tail[brace_idx:]
        lines = body.splitlines()
        # brace matching (best-effort)
        brace = 0
        out_lines: List[str] = []
        for ln in lines:
            brace += ln.count("{")
            brace -= ln.count("}")
            out_lines.append(ln)
            if brace <= 0 and len(out_lines) > 1:
                break
            if len(out_lines) >= max_lines:
                break
        head = text[start_idx : start_idx + tail.find("{")].strip()
        if head:
            return (head + "\n" + "\n".join(out_lines)).strip()
        return "\n".join(out_lines).strip()

    # Prefer definition-level match: find name + params + body "{" without ";".
    name_idx, brace_idx = _find_function_definition(text, fn)
    if name_idx >= 0 and brace_idx >= 0:
        sn = _extract_block_from_index(name_idx)
        if sn:
            return sn
    name_idx, brace_idx = _find_function_definition_loose(text, fn)
    if name_idx >= 0 and brace_idx >= 0:
        sn = _extract_block_from_index(name_idx)
        if sn:
            return sn

    # Fallback: find occurrence and try to build a block from there
    occ_pat = re.compile(rf"\\b{re.escape(fn)}\\b", re.M | re.I)
    m2 = occ_pat.search(text)
    if m2:
        sn = _extract_block_from_index(m2.start())
        if sn:
            return sn
        start_idx = max(0, text.rfind("\n", 0, m2.start()))
        lines = text[start_idx:].splitlines()
        return "\n".join(lines[:max_lines]).strip()
    return ""


def _diagram_include_dot(root: Optional[Path], *, limit: int = 400) -> Tuple[str, str]:
    roots = _find_source_roots(root)
    files = _collect_source_files(roots, limit=500)
    if not files:
        return "", "소스 파일을 찾지 못했음"

    includes: List[Tuple[str, str]] = []
    include_re = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]')

    index = {}
    for f in files:
        index[_rel_from_roots(f, roots)] = f
        index[f.name] = f

    for f in files:
        try:
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = include_re.match(line)
                if not m:
                    continue
                inc = m.group(1).strip()
                target = index.get(inc)
                if target:
                    includes.append((_rel_from_roots(f, roots), _rel_from_roots(target, roots)))
        except Exception:
            continue

    if not includes:
        return "", "include 관계를 찾지 못했음"

    lines = [
        "digraph G {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fillcolor="#f7f7f7"];',
    ]
    for a, b in includes[:limit]:
        lines.append(f'  "{a}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines), ""


def _parse_function_bodies(text: str) -> Dict[str, str]:
    # Very lightweight C/C++ function body parser (best-effort)
    bodies: Dict[str, str] = {}
    sig_re = re.compile(r"^\s*[\w\*\s]+\s+([A-Za-z_][\w]*)\s*\([^;]*\)\s*\{")
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = sig_re.match(lines[i])
        if not m:
            i += 1
            continue
        fn = m.group(1)
        brace = 0
        buf: List[str] = []
        while i < len(lines):
            ln = lines[i]
            brace += ln.count("{")
            brace -= ln.count("}")
            buf.append(ln)
            i += 1
            if brace <= 0:
                break
        bodies[fn] = "\n".join(buf)
    return bodies


def _diagram_call_dot(root: Optional[Path], report_dir: Optional[Path], *, limit: int = 400) -> Tuple[str, str]:
    if not report_dir:
        return "", "리포트 폴더 없음"
    df = gui_utils.load_lizard_dataframe(report_dir)
    if df is None:
        return "", "complexity.csv 미탐지"

    cleaned = gui_utils.clean_lizard_dataframe(df)
    if cleaned is not None:
        df = cleaned
    fcol = gui_utils._pick_column_case_insensitive(df, ["file", "filename", "path", "source_file", "unit"])
    fncol = gui_utils._pick_column_case_insensitive(df, ["function", "function_name", "name", "subprogram"])
    if not (fcol and fncol):
        return "", "함수 목록 컬럼을 찾지 못했음"

    roots = _find_source_roots(root)
    files = _collect_source_files(roots, limit=200)
    if not files:
        return "", "소스 파일을 찾지 못했음"

    func_list = df[[fcol, fncol]].dropna().astype(str)
    func_list = func_list[(func_list[fcol] != "") & (func_list[fncol] != "")]
    func_list = func_list.drop_duplicates().head(200)
    func_names = sorted({str(x) for x in func_list[fncol].tolist()})

    call_edges: List[Tuple[str, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        bodies = _parse_function_bodies(text)
        if bodies:
            for caller, body in bodies.items():
                for fn in func_names:
                    if fn == caller:
                        continue
                    if re.search(rf"\b{re.escape(fn)}\s*\(", body):
                        call_edges.append((caller, fn))
        else:
            for fn in func_names:
                if re.search(rf"\b{re.escape(fn)}\s*\(", text):
                    call_edges.append((_rel_from_roots(f, roots), fn))

    if not call_edges:
        return "", "호출 후보를 찾지 못했음(휴리스틱)"

    lines = [
        "digraph G {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fillcolor="#f7f7f7"];',
    ]
    for a, b in call_edges[:limit]:
        lines.append(f'  "{a}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines), ""


def _diagram_reports_dot(report_dir: Optional[Path]) -> Tuple[str, str]:
    if not report_dir:
        return "", "리포트 폴더 없음"
    nodes = [
        ("analysis_summary.json", report_dir / "analysis_summary.json"),
        ("findings_flat.json", report_dir / "findings_flat.json"),
        ("findings_flat_prod.json", report_dir / "findings_flat_prod.json"),
        ("findings_flat_test.json", report_dir / "findings_flat_test.json"),
        ("cppcheck_findings.json", report_dir / "cppcheck_findings.json"),
        ("coverage.xml", report_dir / "coverage.xml"),
        ("coverage.html", report_dir / "coverage.html"),
        ("complexity.csv", report_dir / "complexity.csv"),
        ("function_changes.json", report_dir / "function_changes.json"),
        ("system.log", report_dir / "system.log"),
        ("lizard_audit.log", report_dir / "lizard_audit.log"),
        ("report.pdf", report_dir / "report.pdf"),
        ("jenkins_scan.json", report_dir / "jenkins_scan.json"),
        ("status.json", report_dir / "status.json"),
    ]
    existing = [name for name, path in nodes if path.exists()]
    if not existing:
        return "", "리포트 파일을 찾지 못했음"

    lines = [
        "digraph G {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fillcolor="#f7f7f7"];',
        '  "Pipeline" -> "Reports";',
    ]
    for n in existing:
        lines.append(f'  "Reports" -> "{n}";')
    lines.append('  "Reports" -> "Dashboard";')
    lines.append("}")
    return "\n".join(lines), ""


def _render_code_diagrams(root: Optional[Path], report_dir: Optional[Path]) -> None:
    with st.expander("🧭 코드/리포트 다이어그램", expanded=False):
        options = ["소스 include 의존", "호출 관계(휴리스틱)", "빌드 산출물/리포트 흐름"]
        sel = st.selectbox("다이어그램 선택", options=options, index=0, key="code_diagram_select")
        edge_limit = st.slider("표시 엣지 수", min_value=50, max_value=800, value=300, step=50, key="code_diagram_edges")
        dot = ""
        err = ""
        if sel == "소스 include 의존":
            dot, err = _diagram_include_dot(root, limit=edge_limit)
        elif sel == "호출 관계(휴리스틱)":
            dot, err = _diagram_call_dot(root, report_dir, limit=edge_limit)
        else:
            dot, err = _diagram_reports_dot(report_dir)
        if err:
            st.info(err)
        if dot:
            try:
                st.graphviz_chart(dot)
            except Exception:
                st.code(dot, language="text")


def _issue_counts_from_summary(summary: dict) -> Dict[str, int]:
    """
    summary.json에서 이슈 개수를 안전하게 추출하는 헬퍼
    """
    res = {
        "cppcheck": 0,
            "clang_tidy": 0,
            "syntax": 0,
            "tests": 0,
            "fuzz": 0,
            "qemu": 0,
            "domain": 0,
        }

    static = _safe_dict(summary.get("static", {}))
    cpp = _safe_dict(static.get("cppcheck", {}))
    tidy = _safe_dict(static.get("clang_tidy", {}))

    def _count_from_block(block: Dict[str, Any]) -> int:
        data = block.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("issues"), list):
                return len(data["issues"])
            if isinstance(data.get("issue_counts"), dict):
                return int(data["issue_counts"].get("total", 0))
        if isinstance(block.get("issues"), list):
            return len(block["issues"])
        if isinstance(block.get("issue_counts"), dict):
            return int(block["issue_counts"].get("total", 0))
        return 0

    res["cppcheck"] = _count_from_block(cpp)
    res["clang_tidy"] = _count_from_block(tidy)

    syntax = _safe_dict(summary.get("syntax", {}))
    res["syntax"] = _count_from_block(syntax)

    tests = _safe_dict(summary.get("tests", {}))
    res["tests"] = _count_from_block(tests)

    fuzz = _safe_dict(summary.get("fuzzing", {}))
    res["fuzz"] = _count_from_block(fuzz)

    qemu = _safe_dict(summary.get("qemu", {}))
    res["qemu"] = _count_from_block(qemu)

    dom = _safe_dict(summary.get("domain_tests", {}))
    res["domain"] = _count_from_block(dom)

    return res


def _coverage_from_summary(summary: dict) -> Tuple[Optional[float], Optional[float]]:
    cov = _safe_dict(summary.get("coverage", {}))
    rate = cov.get("line_rate_pct")
    if rate is None:
        rate = cov.get("line_rate")
    threshold = cov.get("threshold")

    r01 = gui_utils.normalize_rate_0_1(rate)
    t01 = gui_utils.normalize_rate_0_1(threshold)

    rate_val = (r01 * 100.0) if r01 is not None else None
    thr_val = (t01 * 100.0) if t01 is not None else None

    return rate_val, thr_val


# ------------------------------------------------------------
# Header Metrics
# ------------------------------------------------------------
def _render_header_metrics(summary: dict, issues: dict):
    """
    상단 카드 4개: Build, Static, Coverage, QEMU 등
    """
    build = _safe_dict(summary.get("build", {}))
    fuzz = _safe_dict(summary.get("fuzzing", {}))
    qemu = _safe_dict(summary.get("qemu", {}))
    coverage = _safe_dict(summary.get("coverage", {}))

    cols = st.columns(4)

    # Build
    with cols[0]:
        ok = build.get("ok", False)
        st.metric(
            label="Build",
            value="✅ PASS" if ok else "❌ FAIL",
            help=build.get("reason", ""),
        )

    # Static issues
    with cols[1]:
        total_static = issues.get("cppcheck", 0) + issues.get("clang_tidy", 0)
        st.metric(
            label="Static Analysis Issues",
            value=total_static,
            help=f"Cppcheck: {issues.get('cppcheck', 0)}, Clang-Tidy: {issues.get('clang_tidy', 0)}",
        )

    # Coverage
    with cols[2]:
        cov_rate, cov_thr = _coverage_from_summary(summary)
        label = "Coverage"
        if cov_rate is None:
            st.metric(label=label, value="N/A", help="No coverage data")
        else:
            suffix = f"/ {cov_thr:.1f}%" if cov_thr is not None else ""
            st.metric(label=label, value=f"{cov_rate:.1f}%" + suffix)

    # QEMU
    with cols[3]:
        if qemu.get("enabled"):
            val = "✅ PASS" if qemu.get("ok") else "⚠️ WARN"
            help = qemu.get("reason", "")
        else:
            val = "OFF"
            help = "QEMU disabled"
        st.metric(label="QEMU Smoke", value=val, help=help)


# ------------------------------------------------------------
# Pipeline Flow Visualization
# ------------------------------------------------------------
def _render_pipeline_flow(summary: dict, cfg_do_cmake: bool):
    """
    파이프라인 단계를 순서대로 카드로 표현
    """
    steps: List[Dict[str, Any]] = []

    # 1. Build
    build = _safe_dict(summary.get("build", {}))
    if cfg_do_cmake:
        steps.append(
            {
                "name": "Build",
                "status": "PASS" if build.get("ok") else "FAIL",
                "icon": "🏗️",
                "desc": build.get("reason", ""),
            }
        )

    # 2. Tests
    tests = _safe_dict(summary.get("tests", {}))
    if tests.get("enabled"):
        steps.append(
            {
                "name": "Unit Tests",
                "status": "PASS" if tests.get("ok") else "FAIL",
                "icon": "🧪",
                "desc": tests.get("reason", ""),
            }
        )

    # 3. Syntax
    syntax = _safe_dict(summary.get("syntax", {}))
    sy_ok = syntax.get("ok", False)
    sy_skip = syntax.get("reason") == "skipped"
    steps.append(
        {
            "name": "Syntax",
            "status": "PASS" if sy_ok else ("SKIPPED" if sy_skip else "FAIL"),
            "icon": "🔍",
            "desc": "Linter Check",
        }
    )

    # 4. Static
    static = _safe_dict(_safe_dict(summary.get("static", {})).get("cppcheck", {}))
    st_ok = static.get("ok", False)
    st_skip = static.get("reason") == "skipped"
    steps.append(
        {
            "name": "Static",
            "status": "PASS" if st_ok else ("SKIPPED" if st_skip else "FAIL"),
            "icon": "🧱",
            "desc": "Cppcheck / Clang-Tidy",
        }
    )

    # 5. Fuzz
    fuzz = _safe_dict(summary.get("fuzzing", {}))
    if fuzz.get("enabled"):
        steps.append(
            {
                "name": "Fuzz",
                "status": "PASS" if fuzz.get("ok") and not fuzz.get("crash_found") else "FAIL",
                "icon": "💣",
                "desc": "libFuzzer",
            }
        )

    # 6. QEMU
    qemu = _safe_dict(summary.get("qemu", {}))
    if qemu.get("enabled"):
        steps.append(
            {
                "name": "QEMU",
                "status": "PASS" if qemu.get("ok") else "FAIL",
                "icon": "🖥️",
                "desc": "RP2040 ELF Smoke",
            }
        )

    # 7. Domain Tests
    dom = _safe_dict(summary.get("domain_tests", {}))
    if dom.get("enabled"):
        steps.append(
            {
                "name": "Domain",
                "status": "PASS" if dom.get("ok") else "FAIL",
                "icon": "🎭",
                "desc": "Gateway Logic / LIN Domain",
            }
        )

    if not steps:
        st.info("No pipeline steps to display.")
        return

    cols = st.columns(len(steps))
    for col, step in zip(cols, steps):
        with col:
            with st.container(border=True):
                st.markdown(f"{step['icon']} **{step['name']}**")
                st.markdown(
                    f"### {'✅ PASS' if step['status'] == 'PASS' else ('⏭️ SKIP' if step['status']=='SKIPPED' else '❌ FAIL')}"
                )
                if step.get("desc"):
                    st.caption(step["desc"])


# ------------------------------------------------------------
# Git / CI Status Panel
# ------------------------------------------------------------
def _render_git_ci_panel(root: str | Path):
    """Git / Jenkins 상태 요약 패널"""
    st.markdown("#### 🔗 Git / CI Status")

    try:
        git_info = gui_utils.get_git_status(root)
    except Exception:
        git_info = {}

    try:
        ci_info = gui_utils.get_ci_env_info()
    except Exception:
        ci_info = {}

    col1, col2 = st.columns(2)

    # Git 카드
    with col1:
        with st.container(border=True):
            st.markdown("**Git**")
            st.write(
                {
                    "branch": git_info.get("branch") or "-",
                    "commit": git_info.get("commit") or "-",
                    "working_tree": git_info.get("dirty") or "-",
                }
            )

    # CI / Jenkins 카드
    with col2:
        with st.container(border=True):
            st.markdown("**CI / Jenkins**")
            st.write(
                {
                    "is_jenkins": bool(ci_info.get("is_jenkins")),
                    "job_name": ci_info.get("job_name"),
                    "build_number": ci_info.get("build_number"),
                }
            )
            build_url = ci_info.get("build_url")
            if build_url:
                st.markdown(f"[Build URL]({build_url})")


# ------------------------------------------------------------
# Quality Tab
# ------------------------------------------------------------
def render_quality_tab(summary: dict, issues: dict, findings: list):
    """
    Tab 1: 정적 분석, 린트, 요약
    """
    st.markdown("##### 🔍 Static & Lint Overview")

    cpp_issues = issues.get("cppcheck", 0)
    tidy_issues = issues.get("clang_tidy", 0)
    syntax_issues = issues.get("syntax", 0)

    cols = st.columns(3)
    with cols[0]:
        st.metric("Cppcheck Issues", cpp_issues)
    with cols[1]:
        st.metric("Clang-Tidy Issues", tidy_issues)
    with cols[2]:
        st.metric("Syntax Issues", syntax_issues)

    st.divider()
    st.markdown("###### 📋 Flattened Findings")

    if not findings:
        st.info("No findings to display.")
        return

    df = pd.DataFrame(findings)
    # 최소 컬럼 가공
    for col in ["severity", "file", "line", "tool"]:
        if col not in df.columns:
            df[col] = ""

    with st.expander("Filter & View", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            sev = st.selectbox(
                "Severity", options=["(All)"] + sorted(df["severity"].unique().tolist())
            )
        with c2:
            tool = st.selectbox(
                "Tool", options=["(All)"] + sorted(df["tool"].unique().tolist())
            )
        with c3:
            file = st.text_input("File contains", "")

    # bool mask는 Series로 관리
    mask = pd.Series(True, index=df.index)
    if sev != "(All)":
        mask = mask & (df["severity"] == sev)
    if tool != "(All)":
        mask = mask & (df["tool"] == tool)
    if file:
        mask = mask & df["file"].str.contains(file, case=False, na=False)

    df_view = df[mask]

    st.dataframe(
        df_view[
            [
                c
                for c in df_view.columns
                if c
                in [
                    "severity",
                    "tool",
                    "file",
                    "line",
                    "message",
                    "id",
                    "category",
                ]
            ]
        ],
        width="stretch",
        hide_index=True,
    )

    with st.expander("Raw DataFrame"):
        _paged_dataframe(df, key='dash_df', page_size_default=1000, height=420)


# ------------------------------------------------------------
# Testing & Security Tab
# ------------------------------------------------------------
def _render_testing_tab(summary: dict, paths: dict):
    """Tab 2: 테스트 및 보안 (Dynamic Analysis)"""

    # 1. Advanced Test Cards (ASan, Fuzz, etc)
    st.markdown("##### 🛡️ Security & Runtime Tests")

    # Helper to parse summary
    def _get_summ(key):
        return _safe_dict(summary.get(key, {}))

    cols = st.columns(4)

    # ASan
    build_summ = _get_summ("build")
    asan_enabled = _safe_dict(build_summ.get("data", {})).get("asan_enabled", False)
    asan_ok = asan_enabled and build_summ.get("ok", False)
    with cols[0]:
        with st.container(border=True):
            st.markdown("**ASan (Mem)**")
            if asan_ok:
                st.markdown("### ✅ PASS")
            else:
                st.markdown("### ⚠️ OFF/FAIL")

    # Fuzz
    fuzz = _get_summ("fuzzing")
    fuzz_res = "OFF"
    if fuzz.get("enabled"):
        if fuzz.get("crash_found"):
            fuzz_res = "CRASH 💥"
        elif fuzz.get("ok"):
            fuzz_res = "PASS ✅"
        else:
            fuzz_res = "FAIL ❌"
    with cols[1]:
        with st.container(border=True):
            st.markdown("**Fuzzing**")
            st.markdown(f"### {fuzz_res}")

    # QEMU
    qemu = _get_summ("qemu")
    qemu_res = "OFF"
    if qemu.get("enabled"):
        qemu_res = "PASS ✅" if qemu.get("ok") else "FAIL ❌"
    with cols[2]:
        with st.container(border=True):
            st.markdown("**QEMU**")
            st.markdown(f"### {qemu_res}")

    # Domain
    dom = _get_summ("domain_tests")
    dom_res = "OFF"
    if dom.get("enabled"):
        dom_res = "PASS ✅" if dom.get("ok") else "FAIL ❌"
    with cols[3]:
        with st.container(border=True):
            st.markdown("**Domain Logic**")
            st.markdown(f"### {dom_res}")

    st.divider()

    # 2. Coverage
    cov_info = _safe_dict(summary.get("coverage", {}))
    st.markdown("##### ☂️ Code Coverage")

    if cov_info.get("enabled"):
        c1, c2 = st.columns([1, 2])

        rate_val = cov_info.get("line_rate_pct")
        if rate_val is None:
            rate_val = cov_info.get("line_rate")
        r01 = gui_utils.normalize_rate_0_1(rate_val) or 0.0
        t01 = gui_utils.normalize_rate_0_1(cov_info.get("threshold", 0.0)) or 0.0

        line_rate = float(r01) * 100.0
        threshold = float(t01) * 100.0

        with c1:
            # Gauge Chart
            fig = go.Figure(
                go.Indicator(
                    mode="gauge+number",
                    value=line_rate,
                    title={"text": "Line Coverage"},
                    gauge={
                        "axis": {"range": [0, 100]},
                        "bar": {"color": "darkblue"},
                        "steps": [
                            {"range": [0, threshold], "color": "lightgray"},
                            {"range": [threshold, 100], "color": "lightgreen"},
                        ],
                        "threshold": {
                            "line": {"color": "red", "width": 4},
                            "thickness": 0.75,
                            "value": threshold,
                        },
                    },
                )
            )
            fig.update_layout(height=250, margin=dict(t=0, b=0, l=20, r=20))
            st.plotly_chart(fig, width="stretch")

        with c2:
            st.info(f"🎯 Target Threshold: **{threshold:.1f}%**")
            st.caption("커버리지가 목표치보다 낮으면 테스트 케이스를 추가해야 합니다.")

            cov_html = cov_info.get("html")
            if cov_html:
                html_path = Path(cov_html)
                if html_path.exists():
                    with open(html_path, "rb") as f:
                        st.download_button(
                            "📄 Download Full Coverage Report (HTML)",
                            f,
                            file_name="coverage_report.html",
                            mime="text/html",
                            width="stretch",
                        )
    else:
        st.warning("Coverage analysis was skipped or disabled.")

    st.divider()

    # 3. AI Unit Test Plans
    st.markdown("##### 🧪 AI Unit Test Plans (LLM-generated)")
    auto_dir = Path(paths.get("REPORT", ".")) / "auto_generated"

    if not auto_dir.exists():
        st.info(
            "아직 생성된 AI 유닛 테스트 계획이 없습니다. 사이드바에서 테스트 자동 생성 옵션을 활성화한 뒤 파이프라인을 실행하세요."
        )
        return

    plan_files = sorted(auto_dir.glob("test_*.plan.json"))
    if not plan_files:
        st.info(
            "test_*.plan.json 파일이 없습니다. 최신 파이프라인 실행에서 테스트 계획 JSON이 생성되지 않았을 수 있습니다."
        )
        return

    rows: List[Dict[str, Any]] = []
    raw_plans: Dict[str, Any] = {}

    for pf in plan_files:
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            # 파싱 실패해도 원본 문자열을 그대로 저장해서 GUI에서 확인 가능하게 함
            raw_plans[pf.name] = pf.read_text(encoding="utf-8", errors="ignore")
            continue

        raw_plans[pf.name] = data

        src_file = data.get("file") or pf.stem.replace("test_", "")
        language = data.get("language", "")

        funcs = data.get("functions") or []
        if not isinstance(funcs, list):
            funcs = []

        if not funcs:
            rows.append(
                {
                    "Plan": pf.name,
                    "Source": src_file,
                    "Language": language,
                    "Function": "",
                    "Case ID": "",
                    "Description": "",
                    "Inputs": "",
                    "Expected": "",
                }
            )
            continue

        for fn in funcs:
            fname = str(fn.get("name", ""))
            purpose = str(fn.get("purpose", ""))

            cases = fn.get("cases") or []
            if not isinstance(cases, list):
                cases = []

            if not cases:
                rows.append(
                    {
                        "Plan": pf.name,
                        "Source": src_file,
                        "Language": language,
                        "Function": fname,
                        "Case ID": "",
                        "Description": purpose,
                        "Inputs": "",
                        "Expected": "",
                    }
                )
                continue

            for case in cases:
                cid = str(case.get("id", ""))
                desc = str(case.get("description", ""))
                inputs = case.get("inputs") or {}
                expected = case.get("expected") or {}

                def _shorten(obj: Any) -> str:
                    try:
                        s = json.dumps(obj, ensure_ascii=False)
                    except Exception:
                        s = str(obj)
                    if len(s) > 80:
                        return s[:77] + "..."
                    return s

                rows.append(
                    {
                        "Plan": pf.name,
                        "Source": src_file,
                        "Language": language,
                        "Function": fname,
                        "Case ID": cid,
                        "Description": desc or purpose,
                        "Inputs": _shorten(inputs),
                        "Expected": _shorten(expected),
                    }
                )

    if not rows:
        st.info("파싱 가능한 테스트 계획 데이터가 없습니다. plan JSON 포맷을 확인하세요.")
        return

    df = pd.DataFrame(rows)

    # 필터 영역
    with st.expander("🔍 필터 / 검색", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            src_filter = st.selectbox(
                "Source File",
                options=["(All)"]
                + sorted({str(x) for x in df["Source"].unique() if str(x)}),
                index=0,
            )
        with c2:
            func_filter = st.selectbox(
                "Function",
                options=["(All)"]
                + sorted({str(x) for x in df["Function"].unique() if str(x)}),
                index=0,
            )
        with c3:
            plan_filter = st.selectbox(
                "Plan File",
                options=["(All)"]
                + sorted({str(x) for x in df["Plan"].unique() if str(x)}),
                index=0,
            )

    mask = pd.Series(True, index=df.index)
    if src_filter != "(All)":
        mask = mask & (df["Source"] == src_filter)
    if func_filter != "(All)":
        mask = mask & (df["Function"] == func_filter)
    if plan_filter != "(All)":
        mask = mask & (df["Plan"] == plan_filter)

    df_view = df[mask]

    st.markdown("###### 📋 Planned Unit Test Cases")
    _paged_dataframe(df_view, key='dash_df_view', page_size_default=1000, height=420)

    with st.expander("📦 Raw Plan JSON 보기"):
        sel_plan = st.selectbox(
            "Plan file 선택",
            options=sorted(raw_plans.keys()),
        )
        st.json(raw_plans.get(sel_plan, {}))


# ------------------------------------------------------------
# History Tab
# ------------------------------------------------------------
def _render_history_tab(history: list):
    """Tab 3: 히스토리 분석 (schema drift guard 포함)"""
    st.markdown("##### 📜 Trends over time")

    if not history:
        st.info("No history data available yet.")
        return

    df = pd.DataFrame(history)
    if df.empty:
        st.info("history 데이터가 비어있음")
        return

    # timestamp guard
    if "timestamp" in df.columns:
        try:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.sort_values("timestamp")
        except Exception:
            pass
    if "timestamp" not in df.columns or df["timestamp"].isna().all():
        df["timestamp"] = range(1, len(df) + 1)

    # column guards
    def _ensure_numeric(target: str, candidates: list[str], default: float = 0.0) -> None:
        if target in df.columns:
            df[target] = pd.to_numeric(df[target], errors="coerce").fillna(default)
            return
        for c in candidates:
            if c in df.columns:
                df[target] = pd.to_numeric(df[c], errors="coerce").fillna(default)
                return
        df[target] = default

    _ensure_numeric("total_issues", ["issues_total", "issues", "total", "count"])
    _ensure_numeric("complexity_avg", ["ccn_avg", "avg_ccn", "complexity", "avg_complexity"])

    y_cols = [c for c in ["total_issues", "complexity_avg"] if c in df.columns]
    if not y_cols:
        st.info("표시 가능한 지표 컬럼 없음")
        return

    try:
        fig = px.area(
            df,
            x="timestamp",
            y=y_cols,
            labels={"value": "Count", "variable": "Metric"},
            title="Issues & Complexity Trend",
        )
        st.plotly_chart(fig, width="stretch")
    except Exception as e:
        import ui_common
        ui_common.log_exception("dashboard history chart", e)
        st.dataframe(df.tail(30), width="stretch")

    with st.expander("View Raw History Data"):
        try:
            st.dataframe(df.sort_values("timestamp", ascending=False), width="stretch")
        except Exception:
            st.dataframe(df, width="stretch")


def _render_agent_runs_panel(summary: dict) -> None:
    runs = []
    if isinstance(summary, dict):
        ar = summary.get("agent_runs")
        if isinstance(ar, list):
            runs = [r for r in ar if isinstance(r, dict)]
    if not runs:
        return

    st.subheader("Agent Runs Summary")
    total = len(runs)
    ok = sum(1 for r in runs if r.get("ok"))
    rag_used = sum(1 for r in runs if r.get("rag_used"))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Runs", total)
    with c2:
        st.metric("OK", ok)
    with c3:
        st.metric("RAG Used", rag_used)

    rows = []
    for r in runs:
        attempts = r.get("attempts") or []
        if not isinstance(attempts, list):
            attempts = []
        last_review = ""
        for a in reversed(attempts):
            rv = a.get("review") if isinstance(a, dict) else None
            if isinstance(rv, dict) and rv.get("decision"):
                last_review = str(rv.get("decision") or "")
                break
        rows.append(
            {
                "role": str(r.get("role") or ""),
                "stage": str(r.get("stage") or ""),
                "ok": bool(r.get("ok")),
                "attempts": len(attempts),
                "rag_used": bool(r.get("rag_used")),
                "review": last_review,
                "reason": str(r.get("reason") or ""),
            }
        )

    try:
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", height=320)
        if "role" in df.columns:
            df_role = df.groupby("role", dropna=False)["ok"].agg(["count", "sum"]).reset_index()
            df_role = df_role.rename(columns={"sum": "ok"})
            fig = px.bar(df_role, x="role", y="count", title="Agent Runs by Role")
            st.plotly_chart(fig, width="stretch")
    except Exception:
        st.json(rows)



# ------------------------------------------------------------
# Sample Preview (when no results yet)
# ------------------------------------------------------------
def _render_sample_preview(root: str | Path, rep: str, paths: dict, cfg_do_cmake: bool = True):
    """실제 리포트가 없을 때 보여줄 샘플 대시보드 미리보기"""
    st.info(
        "🔍 아직 분석 결과가 없어서, 아래는 **샘플 데이터 미리보기**입니다.\n"
        "실제 파이프라인을 실행하면 이 화면에 임베디드 FW 프로젝트의 결과가 표시됨"
    )

    # 1) 샘플 Summary / Issue 카운트
    sample_summary = {
        "exit_code": 0,
        "failure_stage": None,
        "agent": {
            "applied_changes": []  # 아직 AI 패치 없음
        },
        "static": {
            "cppcheck": {
                "issue_counts": {
                    "total": 12,
                    "error": 2,
                    "warning": 6,
                    "style": 3,
                    "performance": 1,
                    "information": 0,
                }
            }
        },
        # 아래는 파이프라인 단계들이 "아직 실행 안 됨"이라는 의미의 예시
        "build": {"ok": False, "reason": "not_run"},
        "syntax": {"ok": False, "reason": "not_run"},
        "fuzzing": {"enabled": False},
        "qemu": {"enabled": False},
        "tests": {"enabled": False},
        "coverage": {"enabled": False},
        "domain_tests": {"enabled": False},
    }

    sample_issues = _issue_counts_from_summary(sample_summary)

    # 상단 카드 + 파이프라인 플로우를 샘플 데이터로 그려줌
    _render_header_metrics(sample_summary, sample_issues)
    st.write("")  # spacer
    _render_pipeline_flow(sample_summary, cfg_do_cmake)
    st.write("")  # spacer
    _render_git_ci_panel(root)
    st.write("")

    # 2) 예시 테스트/커버리지 요약 테이블
    st.markdown("##### 🧪 예시: 테스트 & 커버리지 요약 (샘플 데이터)")
    sample_rows = [
        {
            "Step": "Syntax Check",
            "Tool": "gcc -fsyntax-only",
            "Status": "NOT RUN",
            "Note": "파이프라인 실행 시 C 문법만 먼저 빠르게 확인",
        },
        {
            "Step": "Unit Tests",
            "Tool": "CTest / Unity",
            "Status": "NOT RUN",
            "Note": "AI가 생성한 테스트 케이스 + 수동 테스트 실행",
        },
        {
            "Step": "Fuzzing",
            "Tool": "libFuzzer / Custom",
            "Status": "OFF",
            "Note": "필요 시 특정 파일에만 집중 퍼징",
        },
        {
            "Step": "Coverage",
            "Tool": "gcovr",
            "Status": "NOT RUN",
            "Note": "라인 커버리지 기준 임계값(예: 80%) 검사",
        },
    ]
    st.table(pd.DataFrame(sample_rows))
    st.caption("※ 위 표는 형식 예시일 뿐이며, 실제 숫자는 파이프라인 실행 후 자동으로 채워짐")


# ------------------------------------------------------------
# Main entry for Dashboard Tab
# ------------------------------------------------------------
def _render_jenkins_build_dashboard(summary, findings, history, root, rep, paths, build_info=None, artifacts=None):
    """Jenkins Viewer용 빌드 대시보드, 로컬 분석 전용 UI 제거 버전"""
    summary = summary or {}
    findings = findings or []
    history = history or []

    j = summary.get("jenkins") if isinstance(summary, dict) else None
    if not isinstance(j, dict):
        j = {}

    st.subheader("🏠 빌드 대시보드(Jenkins)")

    # 상단 메타
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Build", int(j.get("build_number") or (build_info or {}).get("number") or -1))
    with c2:
        st.metric("Result", str(j.get("result") or (build_info or {}).get("result") or "-"))
    with c3:
        st.metric("Job", str(j.get("job_name") or (build_info or {}).get("job_name") or "-"))
    with c4:
        st.metric("Artifacts", int((artifacts or {}).get("count") or 0) if isinstance(artifacts, dict) else 0)

    build_url = str(j.get("build_url") or (build_info or {}).get("url") or "")
    job_url = str(j.get("job_url") or (build_info or {}).get("job_url") or "")
    if build_url or job_url:
        st.caption((f"Job: {job_url}   ·   Build: {build_url}").strip())

    st.caption(f"Build root: {root}")
    if isinstance(paths, dict) and paths.get("REPORT"):
        st.caption(f"Reports dir: {paths.get('REPORT')}")

    _render_agent_runs_panel(summary)



    # -------------------------
    # UT/IT 테스트 요약(VectorCAST)
    # -------------------------
    try:
        tests = summary.get("tests") if isinstance(summary, dict) else {}
        tests = tests if isinstance(tests, dict) else {}
        details = tests.get("details") if isinstance(tests, dict) else {}
        details = details if isinstance(details, dict) else {}

        def _tc_block(name: str) -> Dict[str, Any]:
            b = details.get(name) or {}
            return b if isinstance(b, dict) else {}

        ut = _tc_block("ut")
        it = _tc_block("it")

        def _tc_metrics(b: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[float]]:
            tc = b.get("testcases") or {}
            tc = tc if isinstance(tc, dict) else {}
            ok = tc.get("ok")
            total = tc.get("total")
            try:
                ok_i = int(ok) if ok is not None else None
            except Exception:
                ok_i = None
            try:
                total_i = int(total) if total is not None else None
            except Exception:
                total_i = None
            rate = None
            if total_i and total_i > 0 and ok_i is not None:
                try:
                    rate = float(ok_i) / float(total_i) * 100.0
                except Exception:
                    rate = None
            return ok_i, total_i, rate

        ut_ok, ut_total, ut_rate = _tc_metrics(ut)
        it_ok, it_total, it_rate = _tc_metrics(it)

        cU1, cU2, cU3 = st.columns(3)
        with cU1:
            st.metric("UT TC", f"{ut_ok}/{ut_total}" if (ut_ok is not None and ut_total is not None) else "-", help="VectorCAST UT metrics_report 기반")
        with cU2:
            st.metric("IT TC", f"{it_ok}/{it_total}" if (it_ok is not None and it_total is not None) else "-", help="VectorCAST IT metrics_report 기반")
        with cU3:
            st.metric("UT/IT Pass%", f"UT {ut_rate:.1f}% · IT {it_rate:.1f}%" if (ut_rate is not None and it_rate is not None) else (f"UT {ut_rate:.1f}%" if ut_rate is not None else (f"IT {it_rate:.1f}%" if it_rate is not None else "-")))
    except Exception:
        pass

    # -------------------------
    # Dynamic/QAC 요약(Jenkins Viewer)
    # -------------------------
    try:
        dyn = summary.get("dynamic") or summary.get("runtime") or {}
        if isinstance(dyn, dict) and dyn:
            st.markdown("##### Runtime/동적 분석 요약")
            c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
            def _dyn_count(key: str) -> int:
                v = dyn.get(key)
                if isinstance(v, dict) and "count" in v:
                    try:
                        return int(v.get("count") or 0)
                    except Exception:
                        return 0
                if isinstance(v, list):
                    return len(v)
                return 0
            c1.metric("ASAN", _dyn_count("asan"))
            c2.metric("UBSAN", _dyn_count("ubsan"))
            c3.metric("ASSERT", _dyn_count("assert"))
            c4.metric("TIMEOUT", _dyn_count("timeout"))
            c5.metric("CRC", _dyn_count("crc_mismatch"))
            c6.metric("HardFault", _dyn_count("hardfault"))
            c7.metric("BusFault", _dyn_count("busfault"))
    except Exception:
        pass

    try:
        prqa = summary.get("prqa") if isinstance(summary, dict) else None
        rcr = prqa.get("rcr") if isinstance(prqa, dict) else None
        rcr_sum = rcr.get("summary") if isinstance(rcr, dict) else None
        if isinstance(rcr_sum, dict) and rcr_sum:
            st.markdown("##### QAC(RCR) 요약")
            c1, c2, c3 = st.columns(3)
            c1.metric("Files", rcr_sum.get("Number of Files") or rcr.get("number_of_files") or "-")
            c2.metric("LOC", rcr_sum.get("Lines of Code (source files only)") or rcr.get("loc_source") or "-")
            c3.metric("Diagnostics", rcr_sum.get("Diagnostic Count") or rcr.get("diagnostic_count") or "-")
    except Exception:
        pass

    # -------------------------
    # 프로그램 규모/변경(함수 기준)
    # -------------------------
    try:
        report_dir = None
        if isinstance(paths, dict) and paths.get("REPORT"):
            report_dir = Path(str(paths.get("REPORT")))
        else:
            report_dir = Path(str(root)) / str(rep or "reports")

        df_liz = gui_utils.load_lizard_dataframe(report_dir) if report_dir else None
        if df_liz is None and root:
            df_liz = gui_utils.load_lizard_dataframe(Path(str(root)))
        # 일부 Jenkins 산출물은 build_root/report 또는 reports/report 하위로 떨어질 수 있음
        if df_liz is None:
            try:
                br = Path(str(root)).resolve() if root else None
                for alt in [
                    (br / "report") if br else None,
                    (br / "reports" / "report") if br else None,
                ]:
                    if alt and alt.exists() and alt.is_dir():
                        df_liz = gui_utils.load_lizard_dataframe(alt)
                        if df_liz is not None:
                            break
            except Exception:
                pass
        if df_liz is None and report_dir:
            try:
                for p in gui_utils.list_lizard_candidate_paths(report_dir, limit=20):
                    df_liz = gui_utils.load_lizard_dataframe(p)
                    if df_liz is not None:
                        break
            except Exception:
                pass

        met = gui_utils.code_metrics_from_lizard(df_liz)

        # 이전 빌드(가능한 경우)와 비교
        prev_build_dir: Optional[Path] = None
        try:
            br = Path(str(root)).resolve() if root else None
            parent = br.parent if br else None
            cur_num = None
            if br:
                m = re.search(r"build_(\d+)$", br.name)
                if m:
                    cur_num = int(m.group(1))
            build_nums: List[int] = []
            if parent and parent.exists():
                for p in parent.iterdir():
                    if not p.is_dir():
                        continue
                    m2 = re.search(r"build_(\d+)$", p.name)
                    if m2:
                        build_nums.append(int(m2.group(1)))
            build_nums = sorted(list(dict.fromkeys(build_nums)), reverse=True)
            options = ["자동(이전 빌드)"] + [str(n) for n in build_nums if cur_num is None or n != cur_num]
            sel_compare = st.selectbox("비교 빌드", options=options, index=0, key="jenkins_compare_build")
            if sel_compare != "자동(이전 빌드)" and parent:
                cand = parent / f"build_{sel_compare}"
                if cand.exists():
                    prev_build_dir = cand
                else:
                    st.warning("선택한 비교 빌드가 캐시에 없습니다. 동기화를 먼저 실행하세요.")
            if prev_build_dir is None and br:
                prev_build_dir = gui_utils.find_prev_build_dir(br)
        except Exception:
            prev_build_dir = gui_utils.find_prev_build_dir(Path(str(root)))
        prev_report_dir = (prev_build_dir / str(rep or "reports")) if prev_build_dir else None
        prev_df = gui_utils.load_lizard_dataframe(prev_report_dir) if prev_report_dir else None
        if prev_df is None and prev_build_dir:
            prev_df = gui_utils.load_lizard_dataframe(prev_build_dir)
        if prev_build_dir is None:
            st.info("이전 빌드 캐시가 없어 비교가 제한됩니다. 사이드바에서 '이전 빌드도 동기화'를 실행하세요.")
        prev_met = gui_utils.code_metrics_from_lizard(prev_df) if prev_df is not None else {"code_files": None, "functions": None, "nloc": None}
        diff = gui_utils.summarize_function_diff(df_liz, prev_df, limit=40)

        st.markdown("##### 🧱 프로그램 규모(빌드 기준)")
        cA, cB, cC, cD = st.columns(4)

        def _metric_int(v):
            try:
                if v is None:
                    return None
                return int(round(float(v)))
            except Exception:
                return None

        cur_files = _metric_int(met.get("code_files"))
        cur_funcs = _metric_int(met.get("functions"))
        cur_nloc = _metric_int(met.get("nloc"))

        cm_fallback = summary.get("code_metrics") if isinstance(summary, dict) else None
        if isinstance(cm_fallback, dict):
            if cur_files is None and cm_fallback.get("code_files") is not None:
                cur_files = _metric_int(cm_fallback.get("code_files"))
            if cur_funcs is None and cm_fallback.get("functions") is not None:
                cur_funcs = _metric_int(cm_fallback.get("functions"))
            if cur_nloc is None and cm_fallback.get("nloc") is not None:
                cur_nloc = _metric_int(cm_fallback.get("nloc"))

        prev_files = _metric_int(prev_met.get("code_files"))
        prev_funcs = _metric_int(prev_met.get("functions"))
        prev_nloc = _metric_int(prev_met.get("nloc"))

        with cA:
            delta = (cur_files - prev_files) if (cur_files is not None and prev_files is not None) else None
            st.metric("소스 파일 수", cur_files if cur_files is not None else "-", delta=f"{delta:+d}" if delta is not None else None)
        with cB:
            delta = (cur_nloc - prev_nloc) if (cur_nloc is not None and prev_nloc is not None) else None
            st.metric("라인 수(NLOC)", cur_nloc if cur_nloc is not None else "-", delta=f"{delta:+d}" if delta is not None else None)
        with cC:
            delta = (cur_funcs - prev_funcs) if (cur_funcs is not None and prev_funcs is not None) else None
            st.metric("함수 수", cur_funcs if cur_funcs is not None else "-", delta=f"{delta:+d}" if delta is not None else None)
        with cD:
            st.metric(
                "추가/삭제/변경 함수",
                f"+{int(diff.get('added_count') or 0)} / -{int(diff.get('removed_count') or 0)} / Δ{int(diff.get('modified_count') or 0)}",
            )

        with st.expander("🧩 함수 변경 및 목록(이전 빌드 대비)", expanded=False):
            if prev_df is None:
                st.caption("이전 빌드 없음 또는 이전 빌드에서 complexity/lizard 결과 미탐지")
            else:
                ac = int(diff.get("added_count") or 0)
                rc = int(diff.get("removed_count") or 0)
                mc = int(diff.get("modified_count") or 0)
                if ac == 0 and rc == 0 and mc == 0:
                    st.caption("변경 없음")
                else:
                    c1_, c2_, c3_ = st.columns(3)
                    with c1_:
                        st.caption("추가된 함수(상위 40)")
                        al = diff.get("added_list") or []
                        if not al:
                            st.caption("추가 없음")
                        for s in al:
                            st.write(f"- {s}")
                    with c2_:
                        st.caption("삭제된 함수(상위 40)")
                        rl = diff.get("removed_list") or []
                        if not rl:
                            st.caption("삭제 없음")
                        for s in rl:
                            st.write(f"- {s}")
                    with c3_:
                        st.caption("변경된 함수(복잡도/라인 변화, 상위 40)")
                        ml = diff.get("modified_list") or []
                        if not ml:
                            st.caption("변경 없음(또는 CCN/NLOC 미제공)")
                        for s in ml:
                            st.write(f"- {s}")

            # Controls: force regenerate summary / send to chat
            try:
                last_status = st.session_state.get("ai_action_status")
                if isinstance(last_status, dict):
                    st.caption(
                        f"AI 요청 상태: {last_status.get('action')} · {last_status.get('status')} · {last_status.get('at')}"
                    )
                if not report_dir:
                    st.error("리포트 경로가 없어 AI 요약을 실행할 수 없습니다.")
                    raise RuntimeError("missing_report_dir")
                build_id = str(j.get("build_number") or (build_info or {}).get("number") or "")
                artifacts_hash = gui_utils.compute_artifacts_hash(artifacts if isinstance(artifacts, list) else [])
                sel = []
                if df_liz is not None:
                    df0_tmp = gui_utils.clean_lizard_dataframe(df_liz)
                    if df0_tmp is None:
                        df0_tmp = df_liz
                    fcol = gui_utils._pick_column_case_insensitive(df0_tmp, ["file", "filename", "path", "source_file", "unit"])
                    fncol = gui_utils._pick_column_case_insensitive(df0_tmp, ["function", "function_name", "name", "subprogram"])
                    if fcol and fncol:
                        options = (df0_tmp[fcol].astype(str) + " :: " + df0_tmp[fncol].astype(str)).dropna().unique().tolist()
                        sel = st.multiselect("함수 선택", options=sorted(options)[:200], key="jb_chat_funcs")

                cR1, cR2 = st.columns(2)
                with cR1:
                    if st.button("AI 요약 재생성", key="jb_force_regen"):
                        st.session_state["ai_action_status"] = {
                            "action": "요약 재생성",
                            "status": "진행 중",
                            "at": datetime.now().isoformat(timespec="seconds"),
                        }
                        with st.spinner("AI 요약 재생성 중..."):
                            try:
                                if report_dir:
                                    for fp in [
                                        report_dir / "function_changes.json",
                                        report_dir / "function_changes_history.json",
                                        report_dir / "function_changes.md",
                                        report_dir / "code_summary_overall.json",
                                        report_dir / "code_summary_added.json",
                                        report_dir / "code_summary_removed.json",
                                        report_dir / "code_summary_modified.json",
                                    ]:
                                        if fp.exists():
                                            fp.unlink()
                            except Exception:
                                pass
                            res = gui_utils.generate_function_change_summary(
                                current_report_dir=report_dir,
                                prev_report_dir=prev_report_dir,
                                output_dir=report_dir,
                                build_id=build_id,
                                artifacts_hash=artifacts_hash,
                                enable_ai=True,
                                oai_config_path=getattr(config, "DEFAULT_OAI_CONFIG_PATH", None),
                                limit=50,
                                force=True,
                            )
                            top_fn_lines = []
                            try:
                                df_tmp = gui_utils.clean_lizard_dataframe(df_liz) if df_liz is not None else None
                                if df_tmp is None and df_liz is not None:
                                    df_tmp = df_liz
                                if df_tmp is not None:
                                    fcol = gui_utils._pick_column_case_insensitive(df_tmp, ["file", "filename", "path", "source_file", "unit"])
                                    fncol = gui_utils._pick_column_case_insensitive(df_tmp, ["function", "function_name", "name", "subprogram"])
                                    ccn_col = gui_utils._pick_column_case_insensitive(df_tmp, ["ccn", "cyclomatic_complexity", "complexity", "v(g)", "vg"])
                                    nloc_col = gui_utils._pick_column_case_insensitive(df_tmp, ["nloc", "NLOC", "loc", "lines", "line_count"])
                                    if fcol and fncol:
                                        view = df_tmp.copy()
                                        if ccn_col and ccn_col in view.columns:
                                            view["_ccn"] = pd.to_numeric(view[ccn_col], errors="coerce").fillna(0)
                                        else:
                                            view["_ccn"] = 0
                                        if nloc_col and nloc_col in view.columns:
                                            view["_nloc"] = pd.to_numeric(view[nloc_col], errors="coerce").fillna(0)
                                        else:
                                            view["_nloc"] = 0
                                        view = view.sort_values(["_ccn", "_nloc"], ascending=[False, False]).head(50)
                                        for _, r in view.iterrows():
                                            top_fn_lines.append(
                                                f"{r.get(fcol)} :: {r.get(fncol)} (CCN {int(r.get('_ccn') or 0)}, NLOC {int(r.get('_nloc') or 0)})"
                                            )
                            except Exception:
                                top_fn_lines = []
                            # add snippets for overall summary (top 20 functions)
                            roots = _find_source_roots(Path(str(root)) if root else None)
                            context_lines, debug_lines = _build_function_snippet_context(top_fn_lines[:20], roots)
                            prompt = (
                                "아래 함수 목록과 코드 스니펫만 근거로 전체 코드 요약을 작성해줘.\n"
                                "일반론 금지. 제공된 스니펫/목록 밖의 내용은 추정하지 말고, 추가 자료 요청 문구는 쓰지 마.\n"
                                "스니펫이 없는 항목은 '소스 미탐지'로 표시하고, 해결 방법(소스 루트/경로 매핑 설정)을 제안해줘.\n"
                                "위험 구간, 복잡도 높은 모듈, 개선 우선순위를 짧은 항목으로 정리해줘.\n\n"
                                "상위 함수 목록:\n"
                                + "\n".join(top_fn_lines)
                                + "\n\n상위 함수 스니펫:\n"
                                + "\n".join(context_lines)
                                + "\n\n[DEBUG_PATH_TRACE]\n"
                                + "\n".join(debug_lines)
                            )
                            overall_res = gui_utils.generate_custom_code_summary(
                                report_dir=report_dir,
                                prompt=prompt,
                                oai_config_path=getattr(config, "DEFAULT_OAI_CONFIG_PATH", None),
                                output_name="code_summary_overall.json",
                            )
                            # Group summaries for added/removed/modified
                            group_specs = [
                                ("추가 함수", diff.get("added_list") or [], "code_summary_added.json"),
                                ("삭제 함수", diff.get("removed_list") or [], "code_summary_removed.json"),
                                ("변경 함수", diff.get("modified_list") or [], "code_summary_modified.json"),
                            ]
                            for label, items, out_name in group_specs:
                                try:
                                    if not items:
                                        continue
                                    uniq = []
                                    seen = set()
                                    for it in items:
                                        s = str(it)
                                        if s in seen:
                                            continue
                                        seen.add(s)
                                        uniq.append(s)
                                        if len(uniq) >= 30:
                                            break
                                    ctx, dbg = _build_function_snippet_context(uniq, roots)
                                    grp_prompt = (
                                        "아래 함수 목록과 코드 스니펫만 근거로 변경/동작 영향 요약을 작성해줘.\n"
                                        "일반론 금지. 제공된 스니펫 밖의 내용은 추정하지 말고, 추가 자료 요청 문구는 쓰지 마.\n"
                                        "스니펫을 찾지 못한 항목은 '소스 미탐지'로 표시하고, 해결 방법(소스 루트/경로 매핑 설정)을 제안해줘.\n"
                                        f"대상: {label}\n\n"
                                        + "\n".join(ctx)
                                        + "\n\n[DEBUG_PATH_TRACE]\n"
                                        + "\n".join(dbg)
                                    )
                                    gui_utils.generate_custom_code_summary(
                                        report_dir=report_dir,
                                        prompt=grp_prompt,
                                        oai_config_path=getattr(config, "DEFAULT_OAI_CONFIG_PATH", None),
                                        output_name=out_name,
                                    )
                                except Exception:
                                    continue
                        if isinstance(res, dict) and res.get("ai_error"):
                            st.session_state["ai_action_status"] = {
                                "action": "요약 재생성",
                                "status": f"실패({res.get('ai_error')})",
                                "at": datetime.now().isoformat(timespec="seconds"),
                            }
                            st.error(f"AI 요약 실패: {res.get('ai_error')}")
                        elif isinstance(overall_res, dict) and overall_res.get("ai_error"):
                            st.session_state["ai_action_status"] = {
                                "action": "요약 재생성",
                                "status": f"전체 코드 요약 실패({overall_res.get('ai_error')})",
                                "at": datetime.now().isoformat(timespec="seconds"),
                            }
                            st.error(f"전체 코드 요약 실패: {overall_res.get('ai_error')}")
                        else:
                            st.session_state["ai_action_status"] = {
                                "action": "요약 재생성",
                                "status": "완료",
                                "at": datetime.now().isoformat(timespec="seconds"),
                            }
                            st.success("요약을 다시 생성했어요.")
                        st.rerun()
                with cR2:
                    if st.button("선택 함수 요약 생성", key="jb_funcs_summary_btn"):
                        if sel:
                            st.session_state["ai_action_status"] = {
                                "action": "선택 함수 요약",
                                "status": "진행 중",
                                "at": datetime.now().isoformat(timespec="seconds"),
                            }
                            roots = _find_source_roots(Path(str(root)) if root else None)
                            context_lines: List[str] = []
                            debug_lines: List[str] = []
                            debug_lines.append("source_roots:")
                            for r in roots:
                                debug_lines.append(f"- {r}")
                            for item in sel[:30]:
                                try:
                                    if "::" in item:
                                        file_part, fn = [s.strip() for s in item.split("::", 1)]
                                    else:
                                        file_part, fn = "", item.strip()
                                    debug_lines.append(f"resolve_request: {file_part} :: {fn}")
                                    src_path = _resolve_source_path(file_part, roots, debug=debug_lines) if file_part else None
                                    if src_path:
                                        text = _read_text_smart(src_path, debug=debug_lines)
                                        snip = _extract_function_snippet(text, fn, max_lines=80)
                                        if not snip and fn.startswith(("g_", "s_", "m_")):
                                            snip = _extract_function_snippet(text, fn[2:], max_lines=80)
                                        if snip:
                                            context_lines.append(f"[{file_part} :: {fn}]")
                                            context_lines.append(snip)
                                        else:
                                            debug_lines.append(f"snippet_not_found: {fn} in {src_path}")
                                            context_lines.append(f"[{file_part} :: {fn}] (snippet not found)")
                                    else:
                                        context_lines.append(f"[{file_part} :: {fn}] (source not resolved)")
                                except Exception:
                                    continue
                            prompt = (
                                "아래 함수 목록과 코드 스니펫만 근거로 변경/동작 영향 요약을 작성해줘.\n"
                                "일반론 금지. 제공된 스니펫 밖의 내용은 추정하지 말고, 추가 자료 요청 문구는 쓰지 마.\n"
                                "스니펫을 찾지 못한 항목은 '소스 미탐지'로 표시하고, 해결 방법(소스 루트/경로 매핑 설정)을 제안해줘.\n\n"
                                + "\n".join(context_lines)
                                + "\n\n[DEBUG_PATH_TRACE]\n"
                                + "\n".join(debug_lines)
                            )
                            with st.spinner("선택 함수 요약 생성 중..."):
                                res = gui_utils.generate_custom_code_summary(
                                    report_dir=report_dir,
                                    prompt=prompt,
                                    oai_config_path=getattr(config, "DEFAULT_OAI_CONFIG_PATH", None),
                                    output_name="code_summary_selected.json",
                                )
                            if isinstance(res, dict) and res.get("ai_error"):
                                st.session_state["ai_action_status"] = {
                                    "action": "선택 함수 요약",
                                    "status": f"실패({res.get('ai_error')})",
                                    "at": datetime.now().isoformat(timespec="seconds"),
                                }
                                st.error(f"AI 요약 실패: {res.get('ai_error')}")
                            else:
                                st.session_state["ai_action_status"] = {
                                    "action": "선택 함수 요약",
                                    "status": "완료",
                                    "at": datetime.now().isoformat(timespec="seconds"),
                                }
                                st.success("선택 함수 요약 생성됨")
                        else:
                            st.info("요약할 함수를 선택하세요.")
            except Exception as e:
                st.error(f"AI 요약 UI 오류: {e}")

            try:
                if report_dir:
                    fc_path = report_dir / "function_changes.json"
                else:
                    fc_path = None
                if fc_path and fc_path.exists():
                    fc = gui_utils.load_json(fc_path, default={})
                else:
                    fc = {}
                if isinstance(fc, dict) and (fc.get("ai_summary") or fc.get("diff") or fc.get("top_functions")):
                    with st.expander("🧠 기능 변화 요약", expanded=False):
                        ai_sum = str(fc.get("ai_summary") or "").strip()
                        gen_at = str(fc.get("generated_at") or "")
                        if gen_at:
                            st.caption(f"생성 시각: {gen_at}")
                        if fc.get("ai_error"):
                            st.error(f"AI 요약 오류: {fc.get('ai_error')}")
                        if ai_sum:
                            st.write(ai_sum)
                        else:
                            if fc.get("baseline"):
                                st.caption("AI 요약 없음 (전체 함수 요약만 표시)")
                            else:
                                st.caption("AI 요약 없음 (변경 요약만 표시)")
                        d = fc.get("diff") if isinstance(fc.get("diff"), dict) else {}
                        st.caption(
                            f"추가={int(d.get('added_count') or 0)}, "
                            f"삭제={int(d.get('removed_count') or 0)}, "
                            f"변경={int(d.get('modified_count') or 0)}"
                        )
                        top_rows = fc.get("top_functions") if isinstance(fc.get("top_functions"), list) else []
                        if top_rows:
                            st.markdown("**상위 함수(복잡도/라인 기준)**")
                            try:
                                df_top = pd.DataFrame(top_rows)
                                st.dataframe(df_top, width="stretch", height=280)
                            except Exception:
                                st.code("\n".join([str(r) for r in top_rows[:50]]), language="text")
                # custom summaries
                try:
                    overall_path = report_dir / "code_summary_overall.json" if report_dir else None
                    sel_path = report_dir / "code_summary_selected.json" if report_dir else None
                    added_path = report_dir / "code_summary_added.json" if report_dir else None
                    removed_path = report_dir / "code_summary_removed.json" if report_dir else None
                    modified_path = report_dir / "code_summary_modified.json" if report_dir else None
                    if overall_path and overall_path.exists():
                        overall = gui_utils.load_json(overall_path, default={})
                        if isinstance(overall, dict) and (overall.get("ai_summary") or overall.get("prompt")):
                            with st.expander("🧩 전체 코드 요약", expanded=False):
                                st.caption(f"생성 시각: {overall.get('generated_at')}")
                                st.write(str(overall.get("ai_summary") or ""))
                                if overall.get("prompt"):
                                    st.expander("프롬프트/경로 추적", expanded=False).code(str(overall.get("prompt") or ""), language="text")
                                if overall.get("ai_error"):
                                    st.error(f"AI 요약 오류: {overall.get('ai_error')}")
                    if sel_path and sel_path.exists():
                        sel_sum = gui_utils.load_json(sel_path, default={})
                        if isinstance(sel_sum, dict) and (sel_sum.get("ai_summary") or sel_sum.get("prompt")):
                            with st.expander("🧩 선택 함수 요약", expanded=False):
                                st.caption(f"생성 시각: {sel_sum.get('generated_at')}")
                                st.write(str(sel_sum.get("ai_summary") or ""))
                                if sel_sum.get("prompt"):
                                    st.expander("프롬프트/경로 추적", expanded=False).code(str(sel_sum.get("prompt") or ""), language="text")
                                if sel_sum.get("ai_error"):
                                    st.error(f"AI 요약 오류: {sel_sum.get('ai_error')}")
                    if added_path and added_path.exists():
                        add_sum = gui_utils.load_json(added_path, default={})
                        if isinstance(add_sum, dict) and (add_sum.get("ai_summary") or add_sum.get("prompt")):
                            with st.expander("🧩 추가 함수 요약", expanded=False):
                                st.caption(f"생성 시각: {add_sum.get('generated_at')}")
                                st.write(str(add_sum.get("ai_summary") or ""))
                                if add_sum.get("prompt"):
                                    st.expander("프롬프트/경로 추적", expanded=False).code(str(add_sum.get("prompt") or ""), language="text")
                                if add_sum.get("ai_error"):
                                    st.error(f"AI 요약 오류: {add_sum.get('ai_error')}")
                    if removed_path and removed_path.exists():
                        rem_sum = gui_utils.load_json(removed_path, default={})
                        if isinstance(rem_sum, dict) and (rem_sum.get("ai_summary") or rem_sum.get("prompt")):
                            with st.expander("🧩 삭제 함수 요약", expanded=False):
                                st.caption(f"생성 시각: {rem_sum.get('generated_at')}")
                                st.write(str(rem_sum.get("ai_summary") or ""))
                                if rem_sum.get("prompt"):
                                    st.expander("프롬프트/경로 추적", expanded=False).code(str(rem_sum.get("prompt") or ""), language="text")
                                if rem_sum.get("ai_error"):
                                    st.error(f"AI 요약 오류: {rem_sum.get('ai_error')}")
                    if modified_path and modified_path.exists():
                        mod_sum = gui_utils.load_json(modified_path, default={})
                        if isinstance(mod_sum, dict) and (mod_sum.get("ai_summary") or mod_sum.get("prompt")):
                            with st.expander("🧩 변경 함수 요약", expanded=False):
                                st.caption(f"생성 시각: {mod_sum.get('generated_at')}")
                                st.write(str(mod_sum.get("ai_summary") or ""))
                                if mod_sum.get("prompt"):
                                    st.expander("프롬프트/경로 추적", expanded=False).code(str(mod_sum.get("prompt") or ""), language="text")
                                if mod_sum.get("ai_error"):
                                    st.error(f"AI 요약 오류: {mod_sum.get('ai_error')}")
                except Exception:
                    pass
            except Exception:
                pass

            st.markdown("---")

            _render_code_diagrams(
                Path(str(root)) if root else None,
                Path(str(paths.get("REPORT"))) if isinstance(paths, dict) and paths.get("REPORT") else None,
            )

            # 함수 목록(최신 빌드)
            df0 = gui_utils.clean_lizard_dataframe(df_liz)
            if df0 is None:
                st.caption("함수 목록 없음(lizard/complexity.csv 미탐지)")
                try:
                    if report_dir:
                        cands = gui_utils.list_lizard_candidate_paths(report_dir, limit=20)
                    else:
                        cands = []
                    last_path = gui_utils.get_last_lizard_path()
                    last_err = gui_utils.get_last_lizard_error()
                    if last_path or cands:
                        with st.expander("복잡도 진단 정보", expanded=False):
                            st.write(f"리포트 폴더: {report_dir}")
                            st.write(f"최근 로드 경로: {last_path if last_path else '없음'}")
                            if last_err:
                                st.code(f"마지막 오류: {last_err}", language="text")
                            if cands:
                                st.code("\n".join(str(p) for p in cands), language="text")
                except Exception:
                    pass
            else:
                file_col = gui_utils._pick_column_case_insensitive(df0, ["file", "filename", "path", "source_file", "unit"])  # type: ignore[attr-defined]
                func_col = gui_utils._pick_column_case_insensitive(df0, ["function", "function_name", "name", "subprogram"])  # type: ignore[attr-defined]
                ccn_col = gui_utils._pick_column_case_insensitive(df0, ["ccn", "cyclomatic_complexity", "complexity", "v(g)", "vg"])  # type: ignore[attr-defined]
                nloc_col = gui_utils._pick_column_case_insensitive(df0, ["nloc", "loc", "lines", "line_count"])  # type: ignore[attr-defined]

                cols = [c for c in [file_col, func_col, ccn_col, nloc_col] if c and c in df0.columns]
                view = df0[cols].copy() if cols else df0.copy()

                c1f, c2f, c3f = st.columns(3)
                with c1f:
                    file_opts = ["(전체)"] + sorted({str(x) for x in view[file_col].unique()}) if file_col and file_col in view.columns else ["(전체)"]
                    sel_file = st.selectbox("파일", options=file_opts, index=0, key="jb_func_file")
                with c2f:
                    q = st.text_input("함수 검색", value="", key="jb_func_q")
                with c3f:
                    sort_mode = st.selectbox("정렬", options=["파일/함수", "NLOC 내림차순", "CCN 내림차순"], index=0, key="jb_func_sort")

                try:
                    limit_n = int(st.slider("표시 행 수", min_value=50, max_value=5000, value=300, step=50, key="jb_func_rows"))
                except Exception:
                    limit_n = 300

                if file_col and sel_file != "(전체)":
                    view = view[view[file_col].astype(str) == str(sel_file)]
                if func_col and q.strip():
                    qq = q.strip().lower()
                    view = view[view[func_col].astype(str).str.lower().str.contains(qq, na=False)]

                if sort_mode == "NLOC 내림차순" and nloc_col and nloc_col in view.columns:
                    view["_nloc"] = pd.to_numeric(view[nloc_col], errors="coerce").fillna(0)
                    view = view.sort_values("_nloc", ascending=False).drop(columns=["_nloc"], errors="ignore")
                elif sort_mode == "CCN 내림차순" and ccn_col and ccn_col in view.columns:
                    view["_ccn"] = pd.to_numeric(view[ccn_col], errors="coerce").fillna(0)
                    view = view.sort_values("_ccn", ascending=False).drop(columns=["_ccn"], errors="ignore")
                else:
                    if file_col and func_col and file_col in view.columns and func_col in view.columns:
                        view = view.sort_values([file_col, func_col], ascending=True)

                st.dataframe(view.head(limit_n), width="stretch", height=420)

    except Exception:
        # GUI 프리징 방지: 실패해도 대시보드 계속 렌더
        pass

    # Jenkins Scan 요약(확장자/용량/파일 수)
    jscan = None
    try:
        scan_path = None
        if isinstance(paths, dict):
            scan_path = paths.get("JENKINS_SCAN") or (Path(str(paths.get("REPORT"))) / "jenkins_scan.json" if paths.get("REPORT") else None)
        if scan_path:
            scan_path = Path(str(scan_path))
            if scan_path.exists():
                jscan = json.loads(scan_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        jscan = None

    if isinstance(jscan, dict):
        summ = jscan.get("summary") or {}
        files_total = summ.get("files_total")
        bytes_total = summ.get("bytes_total")
        try:
            files_total = int(files_total) if files_total is not None else None
        except Exception:
            files_total = None
        try:
            bytes_total = int(bytes_total) if bytes_total is not None else None
        except Exception:
            bytes_total = None

        c1, c2, c3 = st.columns(3)
        with c1:
            if files_total is not None:
                st.metric("Files", files_total)
        with c2:
            if bytes_total is not None:
                st.metric("Size(MB)", round(bytes_total / (1024 * 1024), 2))
        with c3:
            kpi = summ.get("kpi_totals") or {}
            try:
                st.metric("FAIL/ERROR", int(kpi.get("FAIL_token", 0)) + int(kpi.get("ERROR_token", 0)))
            except Exception:
                st.metric("FAIL/ERROR", "-")

        # source_roots 표시
        sroots = jscan.get("source_roots")
        if isinstance(sroots, list) and sroots:
            with st.expander("📁 자동 탐지된 소스 루트", expanded=False):
                for s in sroots[:50]:
                    st.write(f"- {s}")
                if len(sroots) > 50:
                    st.caption(f"+{len(sroots) - 50} more")

    # 아티팩트 요약
    if artifacts:
        try:
            art = artifacts or {}
            files = art.get("files") if isinstance(art, dict) else None
            if isinstance(files, dict):
                html_n = len(files.get("html") or [])
                xlsx_n = len(files.get("xlsx") or [])
                others_n = len(files.get("other") or [])
                st.markdown("##### 📦 동기화된 아티팩트 요약")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("HTML", int(html_n))
                with c2:
                    st.metric("XLSX", int(xlsx_n))
                with c3:
                    st.metric("OTHER", int(others_n))
        except Exception:
            pass


    # -------------------------
    # 추가 통계/시각화(요청 반영)
    # -------------------------
    try:
        st.markdown("##### 📊 빌드 요약 시각화")
        issues_count2 = _issue_counts_from_summary(summary)
        cov_rate, cov_thr = _coverage_from_summary(summary)

        cA, cB = st.columns(2)
        with cA:
            # Issue breakdown donut
            try:
                items = [{"category": k, "count": int(v or 0)} for k, v in (issues_count2 or {}).items() if k not in ("total",)]
                items = [it for it in items if it["count"] > 0]
                if items:
                    df_p = pd.DataFrame(items)
                    fig = px.pie(df_p, names="category", values="count", title="Issues Breakdown (static/syntax/tests/fuzz/qemu/domain)")
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info("이슈 카운트 없음(또는 summary에 집계 없음)")
            except Exception:
                pass

        with cB:
            # Coverage gauge (if exists)
            try:
                if cov_rate is not None and isinstance(cov_rate, (int, float)):
                    fig = go.Figure(
                        go.Indicator(
                            mode="gauge+number",
                            value=float(cov_rate),
                            number={"suffix": "%"},
                            title={"text": "Coverage (line)"},
                            gauge={"axis": {"range": [0, 100]}, "threshold": {"value": float(cov_thr) if cov_thr else 0}},
                        )
                    )
                    st.plotly_chart(fig, width="stretch")
            except Exception:
                pass


        # Largest artifacts (stat)
        try:
            base_dir = Path(str(root)).resolve()
            rels: List[str] = []
            if isinstance(jscan, dict):
                f = jscan.get("files")
                if isinstance(f, dict):
                    for k in ["html", "xlsx", "other"]:
                        rels += [str(x) for x in (f.get(k) or [])]
            if not rels and isinstance(artifacts, dict):
                f = artifacts.get("files")
                if isinstance(f, dict):
                    for k in ["html", "xlsx", "other"]:
                        rels += [str(x) for x in (f.get(k) or [])]
            rels = [r for r in rels if r]
            rels = rels[:2000]  # upper bound
            rowsz = []
            for r in rels:
                p = (base_dir / r).resolve()
                # containment: do not allow escaping build root
                if base_dir not in p.parents and p != base_dir:
                    continue
                if p.exists() and p.is_file():
                    try:
                        rowsz.append({"file": r, "mb": round(p.stat().st_size / (1024 * 1024), 3)})
                    except Exception:
                        pass
            if rowsz:
                df_sz = pd.DataFrame(rowsz).sort_values("mb", ascending=False).head(20)
                with st.expander("📦 Top 20 Largest Artifacts", expanded=False):
                    fig = px.bar(df_sz, x="mb", y="file", orientation="h", title="Largest Artifacts (MB)")
                    st.plotly_chart(fig, width="stretch")
                    st.dataframe(df_sz, width="stretch", height=420)
        except Exception:
            pass

    except Exception:
        pass

    # 핵심 리포트 파일(있으면)
    try:
        htmls: List[str] = []
        if isinstance(artifacts, dict):
            files = artifacts.get("files")
            if isinstance(files, dict):
                htmls = list(files.get("html") or [])
        if htmls:
            st.markdown("##### 🧾 주요 HTML 리포트(일부)")
            show = htmls[:10]
            for h in show:
                st.write(f"- {h}")
            if len(htmls) > len(show):
                st.caption(f"+{len(htmls) - len(show)} more, 상세는 '📦 Jenkins 리포트' 탭에서 확인")
        else:
            st.info("HTML 리포트 목록 없음, 사이드바 패턴/Sync 설정 확인 필요")
    except Exception:
        pass

    st.divider()

    tab1, tab2, tab3 = st.tabs(["🔍 Code Quality", "🛡️ Testing & Security", "📈 History"])
    with tab1:
        issues_count = _issue_counts_from_summary(summary)
        render_quality_tab(summary, issues_count, findings)
        # Jenkins Viewer: 툴별 이슈 수 차트 비표시(요청 반영)

    with tab2:
        _render_testing_tab(summary, paths)

        # Dynamic breakdown chart
        try:
            dyn = summary.get("dynamic") or summary.get("runtime") or {}
            if isinstance(dyn, dict):
                items = []
                for k in ["asan", "timeout", "assert", "crc_mismatch", "ubsan", "hardfault", "busfault"]:
                    v = dyn.get(k)
                    c = 0
                    if isinstance(v, dict) and "count" in v:
                        c = int(v.get("count") or 0)
                    elif isinstance(v, list):
                        c = len(v)
                    items.append({"kind": k, "count": c})
                df = pd.DataFrame(items)
                fig = px.bar(df, x="kind", y="count", title="Dynamic 이슈 분해(요약)")
                st.plotly_chart(fig, width="stretch")
        except Exception:
            pass

    with tab3:
        _render_history_tab(history)



def render_dashboard(summary, findings, history, root, rep, paths, cfg_do_cmake=True, mode="local", build_info=None, artifacts=None):
    # 안전 방어
    summary = summary or {}
    findings = findings or []
    history = history or []

    if not summary:
        if str(mode or "local").lower().startswith("jenkins"):
            st.info("Sync 후 build_*/reports/analysis_summary.json 생성 필요")
            return
        _render_sample_preview(root, rep, paths, cfg_do_cmake)
        return

    if str(mode or "local").lower().startswith("jenkins") or str((summary or {}).get("mode") or "").startswith("jenkins"):
        _render_jenkins_build_dashboard(summary, findings, history, root, rep, paths, build_info=build_info, artifacts=artifacts)
        return

    is_sample = bool(summary.get("is_sample"))

    # 🔹 샘플/계획 모드 안내
    if is_sample:
        st.info(
            "⚠️ 아직 실제 파이프라인 실행 리포트가 없어, 현재 대시보드는 **샘플/계획 모드**로 표시 중임\n\n"
            "- 사이드바에서 옵션 설정 후 `분석 시작` 버튼을 누르면 실제 결과가 저장됨\n"
            "- 아래 카드와 표들은 파이프라인이 어떤 식으로 보이는지 보여주기 위한 **예시 데이터**임"
        )


    # 1) 이슈 카운트 집계
    issues_count = _issue_counts_from_summary(summary)

    # 2) 상단 카드 + 파이프라인 플로우
    _render_header_metrics(summary, issues_count)
    with st.expander("🧭 파이프라인 플로우", expanded=False):
        _render_pipeline_flow(summary, cfg_do_cmake)

    _render_agent_runs_panel(summary)

    with st.expander("🌿 Git/CI", expanded=False):
        _render_git_ci_panel(root)

    # 🔹 2-1) Pipeline Plan 표 (있을 때만)
    plan = summary.get("pipeline_plan") or []
    if plan:
        try:
            df_plan = pd.DataFrame(plan)
            col_order = [
                c
                for c in ["order", "step_id", "name", "enabled", "status", "note"]
                if c in df_plan.columns
            ]
            df_plan = df_plan[col_order]
            df_plan = df_plan.rename(
                columns={
                    "order": "순서",
                    "step_id": "ID",
                    "name": "스텝",
                    "enabled": "활성화",
                    "status": "상태",
                    "note": "비고",
                }
            )
            st.markdown("##### 🧭 Pipeline Plan (계획)")
            _paged_dataframe(df_plan, key='dash_plan', page_size_default=500, height=420)
        except Exception as e:
            st.caption(f"Pipeline plan 표시 중 오류: {e}")

    # 3) 탭
    tab1, tab2, tab3 = st.tabs(["🔍 Code Quality", "🛡️ Testing & Security", "📈 History"])

    
    with tab1:
        # 🔸 Flat findings scope (All / Prod / Test)
        scope = st.radio(
            "Findings Scope",
            options=["All", "Prod", "Test"],
            horizontal=True,
            key="cfg_findings_scope",
            help="All=기존 findings_flat + cppcheck_findings, Prod/Test=파이프라인이 분리 저장한 findings_flat_* 사용(없으면 자동 fallback)"
        )

        # Prod/Test 분리 메트릭 (analysis_summary.json에 있을 때만)
        issue_counts = summary.get("issue_counts") if isinstance(summary, dict) else None
        if isinstance(issue_counts, dict):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Flat Findings (Total)", int(issue_counts.get("total", 0)))
            with c2:
                st.metric("Flat Findings (Prod)", int(issue_counts.get("prod", 0)))
            with c3:
                st.metric("Flat Findings (Test)", int(issue_counts.get("test", 0)))

        findings_view = findings or []
        if isinstance(paths, dict):
            if scope == "Prod":
                p = paths.get("FINDINGS_PROD")
                if isinstance(p, Path) and p.exists():
                    findings_view = gui_utils.load_json(p, default=[])
            elif scope == "Test":
                p = paths.get("FINDINGS_TEST")
                if isinstance(p, Path) and p.exists():
                    findings_view = gui_utils.load_json(p, default=[])

        render_quality_tab(summary, issues_count, findings_view)
    with tab2:
        _render_testing_tab(summary, paths)

    with tab3:
        _render_history_tab(history)

    # 4) PDF 버튼
    st.divider()
    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("📄 Generate PDF Report", width="stretch"):
            try:
                out_path = paths["PDF"]
                report_generator.generate_pdf_report(summary, str(out_path))
                st.toast(f"✅ PDF Saved: {out_path}")
            except Exception as e:
                st.error(f"Failed to generate PDF: {e}")
