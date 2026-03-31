"""C code parsing utilities for extracting prototypes, definitions, macros, and globals.

Canonical low-level C parsing lives here.  ``report_gen.source_parser``
re-uses these functions via its own copies (kept in sync); higher-level
modules (e.g. report_gen.uds_generator) should import from
``report_gen.source_parser`` to avoid circular dependencies.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _strip_c_comments(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def _strip_comments_and_strings(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    text = re.sub(r"\"(\\\\.|[^\"])*\"", "\"\"", text)
    text = re.sub(r"'(\\\\.|[^'])+'", "''", text)
    return text


def _extract_c_prototypes(text: str) -> List[Tuple[str, str, bool]]:
    if not text:
        return []
    results: List[Tuple[str, str, bool]] = []
    for match in re.finditer(
        r"^[\t ]*(extern\s+)?[A-Za-z_][\w\s\*\(\),]*?\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*;",
        text,
        flags=re.M,
    ):
        is_extern = bool(match.group(1))
        name = match.group(2)
        params = " ".join(match.group(3).replace("\n", " ").split())
        results.append((name, params, is_extern))
    return results


def _extract_c_definitions(text: str) -> List[Tuple[str, str, bool]]:
    if not text:
        return []
    keywords = {"if", "for", "while", "switch", "return", "sizeof"}
    results: List[Tuple[str, str, bool]] = []
    for match in re.finditer(
        r"^[\t ]*(static\s+)?[A-Za-z_][\w\s\*\(\),]*?\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*\{",
        text,
        flags=re.M,
    ):
        is_static = bool(match.group(1))
        name = match.group(2)
        if name in keywords:
            continue
        params = " ".join(match.group(3).replace("\n", " ").split())
        results.append((name, params, is_static))
    return results


def _extract_c_function_bodies(text: str) -> Dict[str, str]:
    if not text:
        return {}
    out: Dict[str, str] = {}
    pat = re.compile(
        r"^[\t ]*(?:static\s+)?[A-Za-z_][\w\s\*\(\),]*?\s+([A-Za-z_]\w*)\s*\([^;]*?\)\s*\{",
        flags=re.M,
    )
    for m in pat.finditer(text):
        name = str(m.group(1) or "").strip()
        if not name:
            continue
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = text[start + 1 : end].strip() if end > start else ""
        if body:
            out[name] = body
    return out


_STDLIB_NAMES = frozenset({
    "printf", "sprintf", "snprintf", "fprintf", "scanf", "sscanf",
    "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "memmove", "memcmp",
    "strlen", "strcpy", "strncpy", "strcmp", "strncmp", "strcat", "strncat",
    "strstr", "strchr", "strrchr", "strtol", "strtoul", "atoi", "atol",
    "abs", "labs", "fabs", "sqrt", "pow", "log", "exp",
    "assert", "exit", "abort",
})

_CALLBACK_RE = re.compile(
    r"\b(?:register|set|install|add|attach|bind)[_]?\w*(?:callback|handler|hook|listener|func)\b",
    re.I,
)


def _extract_simple_call_names(body_text: str) -> List[str]:
    if not body_text:
        return []
    text = _strip_comments_and_strings(body_text)
    skip = {"if", "for", "while", "switch", "return", "sizeof", "case", "else"}
    names: List[str] = []
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", text):
        name = str(m.group(1) or "").strip()
        if not name or name.lower() in skip:
            continue
        if name in _STDLIB_NAMES:
            continue
        if name.isupper():
            continue
        if name not in names:
            names.append(name)
        if _CALLBACK_RE.match(name):
            args_start = m.end()
            depth = 1
            pos = args_start
            while pos < len(text) and depth > 0:
                if text[pos] == "(":
                    depth += 1
                elif text[pos] == ")":
                    depth -= 1
                pos += 1
            args_text = text[args_start:pos - 1] if pos > args_start else ""
            for arg in args_text.split(","):
                arg = arg.strip()
                if re.match(r"^[A-Za-z_]\w*$", arg) and not arg.isupper() and arg not in skip and arg not in _STDLIB_NAMES:
                    if arg not in names:
                        names.append(arg)
    for m in re.finditer(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\(", text):
        name = str(m.group(1) or "").strip()
        if not name or name.lower() in skip:
            continue
        if name not in names:
            names.append(name)
    for m in re.finditer(r"\.(?:handler|callback|func|fn)\s*=\s*([A-Za-z_]\w*)", text):
        name = str(m.group(1) or "").strip()
        if name and not name.isupper() and name not in names and name not in _STDLIB_NAMES:
            names.append(name)
    return names


def _extract_c_macros(text: str) -> List[str]:
    if not text:
        return []
    results: List[str] = []
    for match in re.finditer(r"^[\t ]*#\s*define\s+([A-Za-z_]\w+)", text, flags=re.M):
        results.append(match.group(1))
    return results


def _extract_c_macro_defs(text: str) -> List[Tuple[str, str]]:
    if not text:
        return []
    results: List[Tuple[str, str]] = []
    for match in re.finditer(
        r"^[\t ]*#\s*define[ \t]+([A-Za-z_]\w+)[ \t]+([^\r\n]+)",
        text,
        flags=re.M,
    ):
        name = match.group(1).strip()
        val = match.group(2).strip()
        if name:
            results.append((name, val))
    return results


def _extract_doxygen_asil_tags(text: str) -> Dict[str, Dict[str, str]]:
    """Extract ASIL/safety/requirement tags from Doxygen comments preceding functions."""
    if not text:
        return {}
    result: Dict[str, Dict[str, str]] = {}
    comment_pat = re.compile(
        r"/\*\*(.*?)\*/\s*"
        r"(?:static\s+)?[A-Za-z_][\w\s\*]*?\s+([A-Za-z_]\w*)\s*\(",
        flags=re.S,
    )
    for m in comment_pat.finditer(text):
        body = m.group(1)
        func_name = m.group(2).strip()
        if not func_name:
            continue
        info: Dict[str, str] = {}
        asil_m = re.search(r"@(?:asil|ASIL)\s+([A-D]|QM)\b", body, re.I)
        if asil_m:
            info["asil"] = asil_m.group(1).upper()
        safety_m = re.search(r"@(?:safety|SAFETY)\s+(.+?)(?:\n|$)", body)
        if safety_m:
            info["safety"] = safety_m.group(1).strip()
            if not info.get("asil"):
                asil_in_safety = re.search(r"\b(ASIL[\s\-_]*[A-D]|QM)\b", info["safety"], re.I)
                if asil_in_safety:
                    raw = asil_in_safety.group(1).upper().replace(" ", "").replace("-", "").replace("_", "")
                    info["asil"] = raw.replace("ASIL", "") if raw.startswith("ASIL") else raw
        req_ids: List[str] = []
        for req_m in re.finditer(
            r"@(?:requirement|req|related)\s+(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)",
            body,
            re.I,
        ):
            req_ids.append(req_m.group(1))
        if req_ids:
            info["requirement"] = ", ".join(req_ids)
        brief_m = re.search(r"@brief\s+(.+?)(?:\n|$)", body)
        if brief_m:
            info["brief"] = brief_m.group(1).strip()
        if info:
            result[func_name] = info
    return result


def _extract_file_header_asil(text: str) -> str:
    """Extract module-level ASIL from file header comment block."""
    if not text:
        return ""
    header_m = re.match(r"\s*/\*\*(.*?)\*/", text, flags=re.S)
    if not header_m:
        header_m = re.match(r"\s*/\*(.*?)\*/", text, flags=re.S)
    if not header_m:
        return ""
    header = header_m.group(1)
    asil_m = re.search(
        r"\b(?:ASIL[\s\-_:]*([A-D](?:\s*\([A-D]\))?)|QM)\b",
        header,
        re.I,
    )
    if asil_m:
        if asil_m.group(0).strip().upper().startswith("QM"):
            return "QM"
        return asil_m.group(1)[0].upper() if asil_m.group(1) else ""
    return ""


def _extract_c_global_candidates(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    out: List[Dict[str, str]] = []
    for raw in text.splitlines():
        line = str(raw or "").strip()
        if not line or line.startswith("#"):
            continue
        if "(" in line or ")" in line or not line.endswith(";"):
            continue
        m = re.match(
            r"^(?:(static)\s+)?(?:(extern)\s+)?(?:(const)\s+)?([A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)\s+([A-Za-z_]\w*)\s*(?:=\s*([^;]+))?;",
            line,
        )
        if not m:
            continue
        gtype = " ".join(str(m.group(4) or "").split()).strip()
        gname = str(m.group(5) or "").strip()
        ginit = str(m.group(6) or "").strip()
        if not gname or not gtype:
            continue
        out.append(
            {
                "name": gname,
                "type": gtype,
                "init": ginit,
                "static": "true" if bool(m.group(1)) else "false",
            }
        )
    return out
