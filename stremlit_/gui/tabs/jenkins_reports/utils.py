# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

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


__all__ = [
    "_job_slug",
    "_as_path",
    "_read_json",
    "_normalize_rule_id",
    "_download_button",
    "_human_bytes",
    "_paged_dataframe",
    "_read_text_tail",
    "_read_text_slice",
    "_find_in_file",
]
