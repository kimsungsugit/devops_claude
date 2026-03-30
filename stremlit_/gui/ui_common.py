# /app/gui/ui_common.py
# -*- coding: utf-8 -*-
"""Common UI helpers shared across Streamlit tabs.

Goals
- Path containment: prevent path traversal / accidental opens outside project root
- Large download policy: consistent checkbox-gated downloads to avoid memory spikes
- Exception logging: consistent, optionally verbose debug output

Note
- This module should not import any app-specific tabs to avoid circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

import os
import re

import streamlit as st


# ---------------------------
# Debug helpers
# ---------------------------
def _debug_enabled() -> bool:
    # Session toggle (if you ever add one) + env toggle
    try:
        if bool(st.session_state.get("ui_debug", False)):
            return True
    except Exception:
        pass
    return os.environ.get("DEVOPS_PRO_DEBUG", "").strip().lower() in {"1", "true", "yes", "y"}


def log_exception(context: str, e: BaseException) -> None:
    """Standardized exception logging for tabs."""
    # Always show a short message; show traceback only in debug mode
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"[{ts}] ⚠️ {context}: {type(e).__name__}")
    except Exception:
        pass

    if _debug_enabled():
        try:
            st.exception(e)
        except Exception:
            # fallback: do nothing
            pass


# ---------------------------
# Path containment
# ---------------------------
def sanitize_relpath(p: str) -> str:
    """Normalize a user-supplied path as a safe relative POSIX-like path.

    - Converts backslashes to forward slashes
    - Removes leading slashes
    - Drops '.' segments and rejects/strips '..' traversal
    - Returns '.' if empty after normalization
    """
    s = (p or "").strip().replace("\\", "/").replace("\\", "/")
    if not s:
        return "."
    # Disallow absolute paths
    if s.startswith("/") or re_drive_abs(s):
        raise ValueError("absolute path not allowed")
    s = s.lstrip("/")  # just in case

    # PurePosixPath for stable splitting
    parts = []
    for part in PurePosixPath(s).parts:
        if part in ("", "."):
            continue
        if part == "..":
            # hard reject traversal
            raise ValueError("path traversal ('..') not allowed")
        parts.append(part)
    return "/".join(parts) if parts else "."


def re_drive_abs(s: str) -> bool:
    # Windows drive path like C:\...
    try:
        return bool(len(s) >= 3 and s[1] == ":" and (s[2] == "/" or s[2] == "\\"))
    except Exception:
        return False


def safe_resolve_under(base: Path, rel: str) -> Path:
    """Resolve (base / rel) and ensure the result stays under base."""
    base_r = base.resolve()
    rel_s = sanitize_relpath(rel)
    out = (base_r / rel_s).resolve()
    if not out.is_relative_to(base_r):
        raise ValueError("resolved path escapes base directory")
    return out


def is_under_any(path: Path, roots: Iterable[Path]) -> bool:
    """Check if *path* is inside any of the given roots."""
    try:
        p = path.resolve()
    except Exception:
        p = Path(str(path))
    for r in roots:
        try:
            rr = Path(str(r)).resolve()
            if p.is_relative_to(rr):
                return True
        except Exception:
            continue
    return False


# ---------------------------
# Download policy
# ---------------------------
@dataclass(frozen=True)
class DownloadPolicy:
    soft_limit_bytes: int = 20 * 1024 * 1024      # 20 MiB: show checkbox gate above this
    hard_limit_bytes: int = 200 * 1024 * 1024     # 200 MiB: refuse in-app download above this
    checkbox_default: bool = True                 # user requested: default allow on checkbox


def download_button_from_path(
    path: Path,
    label: str,
    *,
    file_name: Optional[str] = None,
    mime: Optional[str] = None,
    policy: DownloadPolicy = DownloadPolicy(),
    key: Optional[str] = None,
) -> None:
    """Render a Streamlit download button with consistent large-file policy."""
    p = Path(str(path))
    if not p.exists() or not p.is_file():
        st.info("다운로드할 파일이 없음")
        return

    try:
        size = int(p.stat().st_size)
    except Exception:
        size = 0

    if size > policy.hard_limit_bytes:
        st.warning("파일이 매우 커서 Streamlit 다운로드 비권장, 로컬/외부 방식 권장")
        st.code(str(p))
        return

    if size > policy.soft_limit_bytes:
        ck_key = key or f"dl_force_{hash(str(p))}"
        allow = st.checkbox("강제 다운로드 허용(메모리 사용 증가)", value=policy.checkbox_default, key=ck_key)
        if not allow:
            st.caption("대용량 파일, 다운로드 버튼 숨김")
            return

    try:
        data = p.read_bytes()
        st.download_button(label, data=data, file_name=(file_name or p.name), mime=mime)
    except Exception as e:
        log_exception("다운로드 실패", e)
