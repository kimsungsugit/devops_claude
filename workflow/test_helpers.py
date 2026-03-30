# /app/workflow/test_helpers.py
"""
Shared helpers for stub/test generation used by both pipeline.py and ai.py.

These were duplicated across the two modules; this module is the single
canonical location.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


def strip_c_comments(text: str) -> str:
    """Remove C block and line comments."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def param_placeholder(param: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (value_expression, buffer_kind) for a C parameter declaration."""
    p = (param or "").strip()
    if not p or p == "void":
        return None, None
    if "..." in p:
        return "0", None
    p = p.split("=", 1)[0].strip()
    if "*" in p or "[" in p:
        if re.search(r"\b(uint8_t|char)\b", p):
            return "buf_u8a", "u8"
        if re.search(r"\b(uint16_t)\b", p):
            return "buf_u16a", "u16"
        if re.search(r"\b(uint32_t)\b", p):
            return "buf_u32a", "u32"
        if re.search(r"\b(uint64_t)\b", p):
            return "buf_u64a", "u64"
        if re.search(r"\b(int8_t|int16_t|int32_t|int|long)\b", p):
            return "buf_i32a", "i32"
        return "buf_u8a", "u8"
    if re.search(r"\b(bool)\b", p):
        return "false", None
    if re.search(r"\b(float|double)\b", p):
        return "0.0", None
    return "0", None


def parse_param_name(raw: str) -> str:
    """Extract the last identifier from a C parameter declaration."""
    ids = re.findall(r"[A-Za-z_]\w*", raw or "")
    if not ids:
        return ""
    return ids[-1]


def alt_buffer(expr: str) -> str:
    """Swap 'a' buffers for 'b' buffers to create an alternate call variant."""
    return (
        expr.replace("buf_u8a", "buf_u8b")
        .replace("buf_u16a", "buf_u16b")
        .replace("buf_u32a", "buf_u32b")
        .replace("buf_u64a", "buf_u64b")
        .replace("buf_i32a", "buf_i32b")
    )


def build_call_variants(func_name: str, params: List[str]) -> List[List[str]]:
    """Build multiple call-argument lists for a C function under test."""
    variants: List[List[str]] = []
    base_args: List[str] = []
    param_names: List[str] = []
    has_ptr = False
    first_scalar_idx: Optional[int] = None
    pid_idx: Optional[int] = None
    len_idx: Optional[int] = None

    for i, raw in enumerate(params):
        name = parse_param_name(raw)
        param_names.append(name)
        expr, buf_kind = param_placeholder(raw)
        if expr is None:
            expr = "0"
        base_args.append(expr)
        if buf_kind:
            has_ptr = True
        if first_scalar_idx is None and buf_kind is None:
            first_scalar_idx = i
        if name and "pid" in name.lower():
            pid_idx = i
        if name and any(k in name.lower() for k in ("len", "size", "count")):
            len_idx = i

    variants.append(list(base_args))

    if has_ptr:
        alt = [alt_buffer(a) for a in base_args]
        if alt != base_args:
            variants.append(alt)

    if pid_idx is not None:
        for v in ("0x00", "0x01", "0x02", "0xFF"):
            args = list(base_args)
            args[pid_idx] = v
            variants.append(args)

    if len_idx is not None:
        for v in ("1", "4", "8", "16"):
            args = list(base_args)
            args[len_idx] = v
            variants.append(args)

    if first_scalar_idx is not None and pid_idx is None:
        for v in ("0", "1", "2", "3", "4", "7", "8", "9", "10", "11", "12", "13", "14", "15", "255"):
            args = list(base_args)
            args[first_scalar_idx] = v
            variants.append(args)

    uniq: List[List[str]] = []
    seen: set = set()
    for v in variants:
        key = "|".join(v)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(v)
        if len(uniq) >= 12:
            break
    return uniq


def is_simple_signature(ret: str, params: str, *, header_found: bool) -> bool:
    """Decide if a function signature is simple enough for stub test generation."""
    if not ret:
        return False
    if "typedef" in ret or "struct" in ret or "enum" in ret:
        return False
    lowered_params = params.lower() if params else ""
    if "va_list" in lowered_params or "..." in lowered_params:
        return False
    if not header_found:
        return False
    return True
