# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from .utils import _download_button, _human_bytes, _paged_dataframe


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


__all__ = ["_render_xlsx", "_collect_files"]
