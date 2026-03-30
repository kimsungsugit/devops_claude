# /app/utils/types.py
"""Type-safe helper functions used across the project."""

from __future__ import annotations

from typing import Any, Dict, List


def safe_dict(x: Any) -> Dict[str, Any]:
    """Return *x* if it is a dict, otherwise return an empty dict."""
    return x if isinstance(x, dict) else {}


def safe_list(x: Any) -> List[Any]:
    """Return *x* if it is a list, otherwise return an empty list."""
    return x if isinstance(x, list) else []


def fmt_bool(x: Any) -> str:
    """Format a boolean-ish value as YES / NO / N/A."""
    if x is True:
        return "YES"
    if x is False:
        return "NO"
    return "N/A"


def safe_int(x: Any, default: int = 0) -> int:
    """Coerce *x* to int; return *default* on failure."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def safe_float(x: Any, default: float = 0.0) -> float:
    """Coerce *x* to float; return *default* on failure."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default
