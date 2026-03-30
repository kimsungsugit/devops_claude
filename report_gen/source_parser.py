"""report_gen.source_parser - Auto-split from report_generator.py"""
# Re-import common dependencies
import re
import os
import json
import csv
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

_logger = logging.getLogger("report_generator")

_CALL_SKIP_WORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "case",
    "else",
}
_STATIC_STORAGE_WORDS = (
    "static",
    "STATIC",
    "FAST_STATIC",
    "NEAR_STATIC",
    "STATIC_VAR",
    "STATIC_DATA",
    "FAR_STATIC",
    "SECTION_STATIC",
)
_DECL_QUALIFIER_WORDS = {
    "const",
    "volatile",
    "register",
    "signed",
    "unsigned",
    "short",
    "long",
    "auto",
}


def _iter_c_statements(text: str, top_level_only: bool = False) -> List[str]:
    if not text:
        return []
    clean = _strip_c_comments(text)
    statements: List[str] = []
    cur: List[str] = []
    brace_depth = 0
    paren_depth = 0
    bracket_depth = 0
    in_preprocessor = False
    at_line_start = True
    prev = ""
    for ch in clean:
        if at_line_start:
            if ch in " \t":
                pass
            elif ch == "#":
                in_preprocessor = True
            at_line_start = False
        if ch == "\n":
            if in_preprocessor and prev != "\\":
                in_preprocessor = False
            at_line_start = True
            if not top_level_only or brace_depth == 0:
                cur.append(ch)
            prev = ch
            continue
        if in_preprocessor:
            prev = ch
            continue
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        if not top_level_only or brace_depth == 0:
            cur.append(ch)
        if ch == ";" and paren_depth == 0 and bracket_depth == 0 and (not top_level_only or brace_depth == 0):
            stmt = "".join(cur).strip()
            if stmt:
                statements.append(stmt)
            cur = []
        prev = ch
    tail = "".join(cur).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_decl_items(text: str) -> List[str]:
    items: List[str] = []
    cur: List[str] = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for ch in str(text or ""):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
        if ch == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            token = "".join(cur).strip()
            if token:
                items.append(token)
            cur = []
            continue
        cur.append(ch)
    token = "".join(cur).strip()
    if token:
        items.append(token)
    return items


def _extract_decl_name_and_type(decl: str, base_type: str) -> Tuple[str, str]:
    text = str(decl or "").strip().rstrip(";")
    text = text.split("=", 1)[0].strip()
    if not text:
        return "", ""
    m_func_ptr = re.search(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)", text)
    if m_func_ptr:
        name = str(m_func_ptr.group(1) or "").strip()
        return name, f"{base_type} *".strip()
    m_name = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", text)
    if not m_name:
        return "", ""
    name = str(m_name.group(1) or "").strip()
    prefix = text[: m_name.start()].strip()
    pointer_suffix = " *" if "*" in prefix else ""
    return name, f"{base_type}{pointer_suffix}".strip()


def _parse_c_declaration_statement(stmt: str) -> List[Dict[str, str]]:
    compact = " ".join(str(stmt or "").replace("\n", " ").split()).strip().rstrip(";")
    if not compact:
        return []
    if compact.startswith("#"):
        return []
    if re.match(r"^\s*typedef\b", compact):
        return []
    if re.search(r"\b(?:if|for|while|switch)\b", compact):
        return []
    # Strip __attribute__((...)) annotations before parsing
    compact = re.sub(r"__attribute__\s*\(\(.*?\)\)", "", compact).strip()

    storage_words: List[str] = []
    qualifiers: List[str] = []
    type_tokens: List[str] = []
    tokens = compact.split()
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        upper_tok = tok.upper()
        lower_tok = tok.lower()
        if tok in _STATIC_STORAGE_WORDS:
            storage_words.append(tok)
            idx += 1
            continue
        if lower_tok == "extern":
            storage_words.append(tok)
            idx += 1
            continue
        if lower_tok in _DECL_QUALIFIER_WORDS:
            qualifiers.append(tok)
            idx += 1
            continue
        if lower_tok in {"struct", "enum", "union"} and idx + 1 < len(tokens):
            type_tokens.extend([tok, tokens[idx + 1]])
            idx += 2
            continue
        type_tokens.append(tok)
        idx += 1
        break
    remainder = " ".join(tokens[idx:]).strip()
    if not remainder and type_tokens:
        remainder = type_tokens.pop()
    if not type_tokens:
        return []
    # Only reject function declarations; allow () in initializer (e.g. static int x = fn())
    name_part = remainder.split("=", 1)[0] if "=" in remainder else remainder
    if "(" in name_part and "(*" not in name_part:
        return []

    base_type = " ".join(qualifiers + type_tokens).strip()
    results: List[Dict[str, str]] = []
    for item in _split_decl_items(remainder):
        name, dtype = _extract_decl_name_and_type(item, base_type)
        if not name or not dtype:
            continue
        results.append(
            {
                "name": name,
                "type": dtype,
                "init": item.split("=", 1)[1].strip() if "=" in item else "",
                "static": "true" if any(tok in _STATIC_STORAGE_WORDS for tok in storage_words) else "false",
                "extern": "true" if any(tok.lower() == "extern" for tok in storage_words) else "false",
            }
        )
    return results

def _read_text_limited(path: Path, max_bytes: int = 200000) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    if max_bytes and len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _strip_c_comments(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
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
        start = m.end() - 1  # points to "{"
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


def _extract_c_global_candidates(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for stmt in _iter_c_statements(text, top_level_only=True):
        for item in _parse_c_declaration_statement(stmt):
            gname = str(item.get("name") or "").strip()
            gtype = str(item.get("type") or "").strip()
            if not gname or not gtype:
                continue
            if gname in seen:
                continue
            seen.add(gname)
            out.append(
                {
                    "name": gname,
                    "type": gtype,
                    "init": str(item.get("init") or "").strip(),
                    "static": str(item.get("static") or "false").strip().lower(),
                    "extern": str(item.get("extern") or "false").strip().lower(),
                }
            )
    return out


def _extract_local_static_candidates(body_text: str) -> List[str]:
    """Return names of local static variables declared inside a function body.

    Strategy: combine AST-based detection (tree-sitter) with regex-based
    scanning.  AST handles standard ``static`` and custom macro storage words
    accurately; regex supplements with function-pointer declarators
    (``(*pfCb)``) that tree-sitter cannot parse cleanly.
    """
    if not body_text:
        return []
    regex_names = _extract_local_static_candidates_regex(body_text)
    ast_names = _extract_local_static_candidates_ast(body_text)
    if ast_names is None:
        return regex_names
    # Merge: AST results first, then any regex-only names appended
    seen: Set[str] = set(ast_names)
    merged = list(ast_names)
    for name in regex_names:
        if name not in seen:
            seen.add(name)
            merged.append(name)
    return merged


def _extract_local_static_candidates_regex(body_text: str) -> List[str]:
    """Regex-based local static variable detection (fallback)."""
    _static_kw_pat = re.compile(
        r"\b(?:" + "|".join(re.escape(w) for w in _STATIC_STORAGE_WORDS) + r")\b"
    )
    names: List[str] = []
    seen: Set[str] = set()
    for stmt in _iter_c_statements(body_text, top_level_only=False):
        if not _static_kw_pat.search(stmt):
            continue
        for item in _parse_c_declaration_statement(stmt):
            if str(item.get("static") or "").lower() != "true":
                continue
            name = str(item.get("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _extract_local_static_candidates_ast(body_text: str) -> Optional[List[str]]:
    """AST-based local static variable detection using tree-sitter.

    Returns a list of variable names on success, or None if tree-sitter is
    unavailable or parsing fails (caller falls back to regex).
    """
    try:
        from tree_sitter import Language, Parser  # type: ignore
        import tree_sitter_c as tsc  # type: ignore
    except ImportError:
        return None

    # Wrap the function body in a dummy function so the parser sees valid C
    wrapped = b"void __dummy__(void) {\n" + body_text.encode("utf-8", errors="replace") + b"\n}\n"
    try:
        lang = Language(tsc.language())
        parser = Parser(lang)
        tree = parser.parse(wrapped)
    except Exception:
        return None

    names: List[str] = []
    seen: Set[str] = set()
    _ast_collect_static_decls(tree.root_node, wrapped, names, seen)
    return names


_STATIC_STORAGE_BYTES = {w.encode() for w in _STATIC_STORAGE_WORDS}


def _ast_collect_static_decls(
    node: Any, source: bytes, names: List[str], seen: Set[str]
) -> None:
    """Recursively walk an AST node and collect names of static variable declarations.

    Handles both the standard C ``static`` keyword (parsed as
    ``storage_class_specifier``) and project-specific macro aliases such as
    ``FAST_STATIC`` or ``STATIC`` (parsed as type identifiers by tree-sitter).
    """
    if node.type == "declaration":
        is_static = any(
            (
                child.type == "storage_class_specifier"
                and source[child.start_byte : child.end_byte] == b"static"
            )
            or source[child.start_byte : child.end_byte] in _STATIC_STORAGE_BYTES
            for child in node.children
        )
        if is_static:
            for child in node.children:
                _ast_collect_declarator_names(child, source, names, seen)
    for child in node.children:
        _ast_collect_static_decls(child, source, names, seen)


def _ast_collect_declarator_names(
    node: Any, source: bytes, names: List[str], seen: Set[str]
) -> None:
    """Extract declared variable names from an AST declarator node."""
    if node.type in ("identifier",):
        name = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    elif node.type in (
        "init_declarator",
        "pointer_declarator",
        "array_declarator",
        "parenthesized_declarator",
    ):
        for child in node.children:
            _ast_collect_declarator_names(child, source, names, seen)
    elif node.type == "declaration":
        # Nested (e.g. for-loop init)
        for child in node.children:
            _ast_collect_declarator_names(child, source, names, seen)


def _extract_fallback_call_names(
    source_text: str,
    func_name: str,
    function_name_set: Set[str],
    body_text: str = "",
    max_candidates: int = 50,
) -> List[str]:
    if not source_text or not func_name or not function_name_set:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep

    search_text = str(body_text or "")
    if not search_text:
        pat = re.compile(rf"\b{re.escape(func_name)}\s*\([^;]*?\)\s*\{{", flags=re.M)
        m = pat.search(source_text)
        if m:
            start = m.end() - 1
            depth = 0
            end = start
            for idx in range(start, len(source_text)):
                ch = source_text[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx
                        break
            if end > start:
                search_text = source_text[start + 1 : end]
        if not search_text:
            m = re.search(rf"\b{re.escape(func_name)}\b", source_text)
            if m:
                left = max(0, m.start() - 2500)
                right = min(len(source_text), m.end() + 2500)
                search_text = source_text[left:right]
    clean = _strip_comments_and_strings(search_text)
    if not clean:
        return []
    lines = [ln for ln in clean.splitlines() if not ln.lstrip().startswith("#")]
    clean = "\n".join(lines)
    candidates: List[str] = []
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", clean):
        name = str(m.group(1) or "").strip()
        if (
            not name
            or name == func_name
            or name.lower() in _CALL_SKIP_WORDS
            or name not in function_name_set
        ):
            continue
        if name not in candidates:
            candidates.append(name)
        if len(candidates) >= max_candidates:
            break
    for m in re.finditer(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\(", clean):
        name = str(m.group(1) or "").strip()
        if (
            not name
            or name == func_name
            or name.lower() in _CALL_SKIP_WORDS
            or name not in function_name_set
        ):
            continue
        if name not in candidates:
            candidates.append(name)
        if len(candidates) >= max_candidates:
            break
    return candidates[:max_candidates]


def _extract_macro_call_names(
    body_text: str,
    macro_call_map: Dict[str, List[str]],
    max_candidates: int = 50,
) -> List[str]:
    if not body_text or not macro_call_map:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep

    clean = _strip_comments_and_strings(body_text)
    if not clean:
        return []
    candidates: List[str] = []
    for macro_name, target_names in macro_call_map.items():
        if not macro_name or not target_names:
            continue
        if not re.search(rf"\b{re.escape(macro_name)}\b\s*(?:\(|$)", clean, flags=re.M):
            continue
        for name in target_names:
            if not name or name in candidates:
                continue
            candidates.append(name)
            if len(candidates) >= max_candidates:
                return candidates[:max_candidates]
    return candidates[:max_candidates]


def _extract_function_pointer_call_targets(
    body_text: str,
    function_name_set: Set[str],
    max_candidates: int = 20,
) -> List[str]:
    if not body_text or not function_name_set:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep

    clean = _strip_comments_and_strings(body_text)
    if not clean:
        return []
    alias_to_target: Dict[str, str] = {}
    assign_patterns = [
        re.compile(r"\b([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)\s*;"),
        re.compile(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\([^;]*?\)\s*=\s*&?\s*([A-Za-z_]\w*)\s*;"),
    ]
    for pat in assign_patterns:
        for m in pat.finditer(clean):
            alias = str(m.group(1) or "").strip()
            target = str(m.group(2) or "").strip()
            if not alias or not target or target not in function_name_set or alias in function_name_set:
                continue
            alias_to_target[alias] = target

    candidates: List[str] = []
    for alias, target in alias_to_target.items():
        if re.search(rf"\b{re.escape(alias)}\s*\(", clean) or re.search(
            rf"\(\s*\*\s*{re.escape(alias)}\s*\)\s*\(",
            clean,
        ):
            if target not in candidates:
                candidates.append(target)
            if len(candidates) >= max_candidates:
                break
    return candidates[:max_candidates]


def _extract_comment_lines(text: str) -> List[str]:
    if not text:
        return []
    lines: List[str] = []
    for ln in text.splitlines():
        if "//" in ln:
            lines.append(ln.split("//", 1)[1].strip())
    for match in re.finditer(r"/\*([\s\S]*?)\*/", text):
        block = match.group(1)
        for ln in block.splitlines():
            cleaned = ln.strip().lstrip("*").strip()
            if cleaned:
                lines.append(cleaned)
    return lines


def _scan_source_comment_patterns(source_root: str, max_files: int = 300) -> List[Dict[str, Any]]:
    root = Path(source_root).resolve()
    if not root.exists():
        return []
    allowed = {".c", ".h", ".cpp", ".hpp"}
    pattern = re.compile(r"\b(logic|flow|state|diagram)\b", flags=re.I)
    items: List[Dict[str, Any]] = []
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            raw = _read_text_limited(p)
            if not raw:
                continue
            comments = _extract_comment_lines(raw)
            for ln in comments:
                if pattern.search(ln):
                    items.append(
                        {
                            "title": f"{p.name} (comment)",
                            "description": ln.strip()[:240],
                        }
                    )
                if len(items) >= 80:
                    break
            if len(items) >= 80:
                break
        if scanned > max_files or len(items) >= 80:
            break
    return items


def _scan_source_requirement_ids(source_root: str, max_files: int = 800) -> List[str]:
    root = Path(source_root).resolve()
    if not root.exists():
        return []
    allowed = {".c", ".h", ".cpp", ".hpp"}
    ids: set[str] = set()
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            text = _read_text_limited(p)
            if not text:
                continue
            for rid in re.findall(r"\bSw(?:TR|TSR|Com|Fn)_\d+\b", text):
                ids.add(rid)
        if scanned > max_files:
            break
    return sorted(ids)


def _scan_source_function_names(source_root: str, max_files: int = 800) -> Dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.exists():
        return {"names": [], "scanned": 0}
    allowed = {".c", ".h", ".cpp", ".hpp"}
    names: set[str] = set()
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            raw = _read_text_limited(p)
            if not raw:
                continue
            text = _strip_c_comments(raw)
            for fn, _, _ in _extract_c_prototypes(text):
                names.add(fn)
            for fn, _, _ in _extract_c_definitions(text):
                names.add(fn)
        if scanned > max_files:
            break
    return {"names": sorted(names), "scanned": scanned}


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
