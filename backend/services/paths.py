from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Iterable


def sanitize_relpath(p: str) -> str:
    s = (p or "").strip().replace("\\", "/")
    if not s:
        return "."
    if s.startswith("/") or _is_drive_abs(s):
        raise ValueError("absolute path not allowed")
    s = s.lstrip("/")
    parts = []
    for part in PurePosixPath(s).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal not allowed")
        parts.append(part)
    return "/".join(parts) if parts else "."


def _is_drive_abs(s: str) -> bool:
    return bool(len(s) >= 3 and s[1] == ":" and (s[2] == "/" or s[2] == "\\"))


def safe_resolve_under(base: Path, rel: str) -> Path:
    base_r = base.resolve()
    rel_s = sanitize_relpath(rel)
    out = (base_r / rel_s).resolve()
    if not out.is_relative_to(base_r):
        raise ValueError("resolved path escapes base directory")
    return out


def is_under_any(path: Path, roots: Iterable[Path]) -> bool:
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
