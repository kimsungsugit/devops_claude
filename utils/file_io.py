# /app/utils/file_io.py
"""Safe file I/O helpers used across the project."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def read_text_limited(path: Path, max_bytes: int = 200_000) -> str:
    """Read text from *path* with an optional byte-size cap.

    Returns an empty string on any filesystem error.
    """
    try:
        data = path.read_bytes()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.debug("read_text_limited: cannot read %s: %s", path, exc)
        return ""
    if max_bytes and len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8", errors="ignore")
    except (UnicodeDecodeError, ValueError):
        return ""


def read_text_safe(path: Path, encoding: str = "utf-8") -> str:
    """Read the full text of *path*, returning empty string on error."""
    try:
        return path.read_text(encoding=encoding, errors="ignore")
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.debug("read_text_safe: cannot read %s: %s", path, exc)
        return ""


def write_text_safe(path: Path, content: str, encoding: str = "utf-8") -> bool:
    """Write *content* to *path*, creating parent dirs. Returns success flag."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return True
    except (PermissionError, OSError) as exc:
        logger.warning("write_text_safe: failed to write %s: %s", path, exc)
        return False


def write_json_safe(
    path: Path,
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> bool:
    """Serialize *data* as JSON and write to *path*. Returns success flag."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=ensure_ascii, indent=indent),
            encoding="utf-8",
        )
        return True
    except (TypeError, PermissionError, OSError) as exc:
        logger.warning("write_json_safe: failed to write %s: %s", path, exc)
        return False


def load_json_safe(path: Path, default: Any = None) -> Any:
    """Load JSON from *path*; return *default* on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError) as exc:
        logger.debug("load_json_safe: cannot load %s: %s", path, exc)
        return default
