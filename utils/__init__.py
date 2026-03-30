# /app/utils/__init__.py
"""Shared utility modules for the DevOps analysis toolkit."""

from .types import safe_dict, safe_list, fmt_bool
from .file_io import read_text_limited, read_text_safe, write_text_safe, write_json_safe
from .text import trim_text, strip_c_comments, normalize_whitespace
from .log import get_logger

__all__ = [
    "safe_dict",
    "safe_list",
    "fmt_bool",
    "read_text_limited",
    "read_text_safe",
    "write_text_safe",
    "write_json_safe",
    "trim_text",
    "strip_c_comments",
    "normalize_whitespace",
    "get_logger",
]
