# /app/utils/__init__.py
"""Shared utility modules for the DevOps analysis toolkit."""

from .file_io import read_text_limited, read_text_safe, write_json_safe, write_text_safe
from .log import get_logger
from .text import normalize_whitespace, strip_c_comments, trim_text
from .types import fmt_bool, safe_dict, safe_list

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
