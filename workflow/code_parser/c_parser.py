from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from tree_sitter import Language, Parser  # type: ignore
    from tree_sitter_c import language as c_language  # type: ignore
except Exception:  # pragma: no cover
    Language = None  # type: ignore
    Parser = None  # type: ignore
    c_language = None  # type: ignore


@dataclass
class CFunction:
    name: str
    signature: str
    is_static: bool
    file: str
    calls: List[str]
    used_globals: List[str]
    comment_desc: str
    comment_asil: str
    comment_related: str
    comment_precondition: str
    body_text: str
    comment_params: List[Dict[str, str]] = None  # [{"name": "x", "desc": "..."}]
    comment_return: str = ""


def _run_preprocessor(
    path: Path,
    *,
    cpp_path: str = "gcc",
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
) -> Optional[bytes]:
    include_dirs = include_dirs or []
    defines = defines or []

    def _uniq(seq: List[str]) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        for x in seq:
            k = str(x or "").strip()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    candidates = _uniq([cpp_path, "gcc", "clang", "cl.exe"])
    for tool in candidates:
        t = tool.lower()
        if t.endswith("cl.exe") or t == "cl":
            args = [tool, "/nologo", "/EP", str(path)]
            for inc in include_dirs:
                args.append(f"/I{inc}")
            for d in defines:
                args.append(f"/D{d}")
        else:
            args = [tool, "-E", str(path)]
            for inc in include_dirs:
                args.extend(["-I", inc])
            for d in defines:
                args.extend(["-D", d])
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        except Exception:
            continue
    return None


def _run_preprocessor_fallback(
    path: Path,
    *,
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
    cpp_path: str = "gcc",
) -> Tuple[Optional[bytes], str]:
    include_dirs = include_dirs or []
    defines = defines or []
    tried: List[str] = []
    for cand in [cpp_path, "clang"]:
        tool = str(cand or "").strip()
        if not tool or tool in tried:
            continue
        tried.append(tool)
        data = _run_preprocessor(
            path,
            cpp_path=tool,
            include_dirs=include_dirs,
            defines=defines,
        )
        if data is not None:
            return data, tool
    return None, "no-preprocess"


def _node_text(src: bytes, node) -> str:
    try:
        return src[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _find_ident(node) -> Optional[str]:
    if node.type == "identifier":
        return node.text.decode("utf-8", errors="ignore")
    for child in node.children:
        name = _find_ident(child)
        if name:
            return name
    return None


def _walk(node):
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        if cur.children:
            stack.extend(reversed(cur.children))


_CALLBACK_REGISTER_PATTERNS = re.compile(
    r"\b(?:register|set|install|add|attach|bind)_?\w*(?:callback|handler|hook|listener|func)\b",
    re.I,
)

_STD_LIB_FUNCS = frozenset({
    "printf", "sprintf", "snprintf", "fprintf", "scanf", "sscanf",
    "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "memmove", "memcmp",
    "strlen", "strcpy", "strncpy", "strcmp", "strncmp", "strcat", "strncat",
    "strstr", "strchr", "strrchr", "strtol", "strtoul", "atoi", "atol",
    "abs", "labs", "fabs", "sqrt", "pow", "log", "exp",
    "assert", "exit", "abort",
})

_REGEX_DEF_PAT = re.compile(
    r"^[\t ]*((?:static\s+)?[A-Za-z_][\w\s\*\(\),]*?)\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*\{",
    flags=re.M,
)


def _extract_calls(func_node, src: bytes) -> List[str]:
    calls: Set[str] = set()
    body = func_node.child_by_field_name("body")
    if not body:
        return []
    for node in _walk(body):
        if node.type == "call_expression":
            target = node.child_by_field_name("function")
            if target is None and node.children:
                target = node.children[0]
            if target is None:
                continue
            if target.type == "parenthesized_expression":
                inner = _find_ident(target)
                if inner:
                    calls.add(inner)
                continue
            name = _find_ident(target)
            if name:
                calls.add(name)
                if _CALLBACK_REGISTER_PATTERNS.match(name):
                    args = node.child_by_field_name("arguments")
                    if args:
                        for arg_node in args.children:
                            if arg_node.type == "identifier":
                                cb_name = arg_node.text.decode("utf-8", errors="ignore")
                                if cb_name and not cb_name.isupper():
                                    calls.add(cb_name)
        elif node.type == "assignment_expression":
            right = node.child_by_field_name("right")
            if right and right.type == "identifier":
                rname = right.text.decode("utf-8", errors="ignore")
                left = node.child_by_field_name("left")
                if left:
                    lt = _node_text(src, left)
                    if "handler" in lt.lower() or "callback" in lt.lower() or "func" in lt.lower():
                        if rname and not rname.isupper():
                            calls.add(rname)
    return sorted(calls - _STD_LIB_FUNCS)


def _extract_calls_from_body_text(body_text: str) -> List[str]:
    calls: Set[str] = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", str(body_text or "")):
        name = str(m.group(1) or "").strip()
        if not name or name.lower() in {"if", "for", "while", "switch", "return", "sizeof"}:
            continue
        if name in _STD_LIB_FUNCS:
            continue
        calls.add(name)
    return sorted(calls)


def _extract_leading_comment(src: bytes, start_byte: int) -> str:
    try:
        text = src[:start_byte].decode("utf-8", errors="ignore")
    except Exception:
        return ""
    if not text.strip():
        return ""
    # Block comment
    end_idx = text.rfind("*/")
    if end_idx != -1:
        start_idx = text.rfind("/*", 0, end_idx)
        if start_idx != -1:
            tail = text[end_idx + 2 :].strip()
            if not tail:
                return text[start_idx + 2 : end_idx].strip()
    # Line comments
    lines = text.splitlines()
    collected: List[str] = []
    for ln in reversed(lines):
        stripped = ln.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith("//"):
            collected.append(stripped[2:].strip())
        else:
            break
    return "\n".join(reversed(collected)).strip()


def _parse_comment_fields(comment: str) -> Tuple[str, str, str, str, str, List[Dict[str, str]], str]:
    """Returns (desc, asil, related, precondition, range_text, params, return_desc)."""
    if not comment:
        return "", "", "", "", "", [], ""
    asil = ""
    related = ""
    precondition = ""
    range_text = ""
    desc = ""
    params: List[Dict[str, str]] = []
    return_desc = ""
    def _is_noise_desc(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return True
        if re.fullmatch(r"[-=*#_/\\.\s]{4,}", t):
            return True
        if re.search(r"\b\d+\s*-\s*BIT\s+REGISTERS\b", t, flags=re.I):
            return True
        if re.search(r"\bREGISTERS?\b", t, flags=re.I) and re.search(r"[*=-]{3,}", t):
            return True
        return False
    brief_lines: List[str] = []
    details_lines: List[str] = []
    in_details = False
    for raw in comment.splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line:
            continue
        m_brief = re.match(r"@brief\s+(.*)", line, flags=re.I)
        if m_brief:
            brief_lines.append(m_brief.group(1).strip())
            in_details = False
            continue
        m_details = re.match(r"@details?\s+(.*)", line, flags=re.I)
        if m_details:
            details_lines.append(m_details.group(1).strip())
            in_details = True
            continue
        if in_details and not line.startswith("@"):
            details_lines.append(line)
            continue
        if line.startswith("@"):
            in_details = False
        if not asil:
            m = re.search(r"\bASIL\b[:\s-]+([A-Za-z0-9-]+)", line, flags=re.I)
            if m:
                asil = m.group(1).strip()
                continue
        if not related:
            m = re.search(r"\bRelated ID\b[:\s]+(.+)", line, flags=re.I)
            if m:
                related = m.group(1).strip()
                continue
        if not precondition:
            m = re.search(r"(?:@pre|Pre-?condition|Precondition|Require(?:ment)?)\b[:\s]+(.+)", line, flags=re.I)
            if m:
                precondition = m.group(1).strip()
                continue
            m = re.search(r"선행조건[:\s]+(.+)", line)
            if m:
                precondition = m.group(1).strip()
                continue
        if not range_text:
            m = re.search(r"\bRange\b[:\s]+(.+)", line, flags=re.I)
            if m:
                range_text = m.group(1).strip()
                continue
            m = re.search(r"\bValue Range\b[:\s]+(.+)", line, flags=re.I)
            if m:
                range_text = m.group(1).strip()
                continue
        if not desc:
            m = re.search(r"\bDescription\b[:\s]+(.+)", line, flags=re.I)
            if m:
                cand = m.group(1).strip()
                if not _is_noise_desc(cand):
                    desc = cand
                continue
        m_param = re.match(r"@param\s+(?:\[(?:in|out|in,\s*out)\]\s*)?(\w+)\s*(.*)", line, flags=re.I)
        if m_param:
            params.append({"name": m_param.group(1).strip(), "desc": m_param.group(2).strip()})
            in_details = False
            continue
        m_ret = re.match(r"@(?:return|retval)\s+(.*)", line, flags=re.I)
        if m_ret:
            return_desc = m_ret.group(1).strip()
            in_details = False
            continue
        if not desc:
            if _is_noise_desc(line):
                continue
            if re.match(r"@(?:note|see|warning|file|author|date|version|since|deprecated|todo|bug|throws|exception)\b", line, flags=re.I):
                continue
            desc = line
    if not desc and brief_lines:
        desc = " ".join(brief_lines).strip()
    if details_lines:
        details_text = " ".join(details_lines).strip()
        if desc:
            desc = f"{desc} {details_text}".strip()
        else:
            desc = details_text
    if params and desc:
        param_names = ", ".join(p["name"] for p in params)
        if return_desc:
            desc = f"{desc} (params: {param_names}; returns: {return_desc})"
        else:
            desc = f"{desc} (params: {param_names})"
    elif not desc and params:
        param_names = ", ".join(p["name"] for p in params)
        desc = f"Parameters: {param_names}"
        if return_desc:
            desc += f"; Returns: {return_desc}"
    elif not desc and return_desc:
        desc = f"Returns: {return_desc}"
    return desc, asil, related, precondition, range_text, params, return_desc


def _extract_function_defs(
    root, src: bytes, file_path: str, globals_set: Set[str]
) -> List[CFunction]:
    functions: List[CFunction] = []
    for node in root.children:
        if node.type != "function_definition":
            continue
        decl = node.child_by_field_name("declarator")
        decl_text = _node_text(src, decl) if decl else ""
        name = _find_ident(decl) if decl else None
        if not name:
            continue
        prefix = _node_text(src, node.child_by_field_name("type")) or ""
        is_static = "static" in prefix
        signature = (prefix + " " + decl_text).strip()
        calls = _extract_calls(node, src)
        used_globals: Set[str] = set()
        body = node.child_by_field_name("body")
        body_text = _node_text(src, body) if body else ""
        if body:
            for n in _walk(body):
                if n.type == "identifier":
                    ident = n.text.decode("utf-8", errors="ignore")
                    parent = getattr(n, "parent", None)
                    if parent is not None and parent.type == "call_expression":
                        continue
                    if ident in globals_set and ident != name:
                        used_globals.add(ident)
        comment = _extract_leading_comment(src, node.start_byte)
        desc, asil, related, precondition, _, c_params, c_return = _parse_comment_fields(comment)
        functions.append(
            CFunction(
                name=name,
                signature=signature,
                is_static=is_static,
                file=file_path,
                calls=calls,
                used_globals=sorted(used_globals),
                comment_desc=desc,
                comment_asil=asil,
                comment_related=related,
                comment_precondition=precondition,
                body_text=body_text,
                comment_params=c_params or None,
                comment_return=c_return,
            )
        )
    return functions


def _extract_function_defs_regex_fallback(
    text: str,
    file_path: str,
    globals_set: Set[str],
) -> List[CFunction]:
    if not text:
        return []
    functions: List[CFunction] = []
    keywords = {"if", "for", "while", "switch", "return", "sizeof"}
    text_bytes = text.encode("utf-8", errors="ignore")
    for match in _REGEX_DEF_PAT.finditer(text):
        prefix = str(match.group(1) or "").strip()
        name = str(match.group(2) or "").strip()
        params = " ".join(str(match.group(3) or "").replace("\n", " ").split())
        if not name or name in keywords:
            continue
        brace_start = match.end() - 1
        depth = 0
        brace_end = brace_start
        for idx in range(brace_start, len(text)):
            ch = text[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    brace_end = idx
                    break
        body_text = text[brace_start + 1 : brace_end].strip() if brace_end > brace_start else ""
        used_globals: Set[str] = set()
        for ident in re.findall(r"\b([A-Za-z_]\w*)\b", body_text):
            if ident in globals_set and ident != name:
                used_globals.add(ident)
        try:
            start_byte = len(text[: match.start()].encode("utf-8", errors="ignore"))
        except Exception:
            start_byte = 0
        comment = _extract_leading_comment(text_bytes, start_byte)
        desc, asil, related, precondition, _, c_params, c_return = _parse_comment_fields(comment)
        functions.append(
            CFunction(
                name=name,
                signature=f"{prefix} {name}({params})".strip(),
                is_static="static" in prefix.lower().split(),
                file=file_path,
                calls=_extract_calls_from_body_text(body_text),
                used_globals=sorted(used_globals),
                comment_desc=desc,
                comment_asil=asil,
                comment_related=related,
                comment_precondition=precondition,
                body_text=body_text,
                comment_params=c_params or None,
                comment_return=c_return,
            )
        )
    return functions


def _extract_globals(root, src: bytes) -> List[str]:
    globals_list: List[str] = []
    for node in root.children:
        if node.type != "declaration":
            continue
        decl_text = _node_text(src, node)
        # Skip function prototypes/declarations at global scope.
        if "(" in decl_text and ")" in decl_text:
            continue
        name = _find_ident(node) or ""
        if name and name not in globals_list:
            globals_list.append(name)
    return globals_list


def _extract_global_decls(root, src: bytes) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for node in root.children:
        if node.type != "declaration":
            continue
        type_node = node.child_by_field_name("type")
        type_text = _node_text(src, type_node).strip() if type_node else ""
        decl_text = _node_text(src, node)
        # Skip function declarations/prototypes and function pointer typedef-like declarations.
        if "(" in decl_text and ")" in decl_text:
            continue
        range_text = ""
        range_source = ""
        if decl_text:
            m = re.search(r"(0x[0-9A-Fa-f]+|\\d+)\\s*~\\s*(0x[0-9A-Fa-f]+|\\d+)", decl_text)
            if m:
                range_text = f"{m.group(1)} ~ {m.group(2)}"
                range_source = "decl"
        comment = _extract_leading_comment(src, node.start_byte)
        desc_text = ""
        if comment:
            dtext, _, _, _, rtext, _, _ = _parse_comment_fields(comment)
            desc_text = dtext or ""
            if rtext:
                range_text = rtext
                range_source = "comment"
        is_static = "static" in decl_text
        handled = False
        for child in node.children:
            if child.type != "init_declarator":
                continue
            handled = True
            decl_node = child.child_by_field_name("declarator") or child
            name = _find_ident(decl_node) or ""
            init_node = child.child_by_field_name("value")
            init_text = _node_text(src, init_node).strip() if init_node else ""
            if not name:
                continue
            results.append(
                {
                    "name": name,
                    "type": type_text,
                    "init": init_text,
                    "range": range_text,
                    "decl": decl_text,
                    "range_source": range_source,
                    "is_static": "true" if is_static else "false",
                    "desc": desc_text,
                }
            )
        if not handled:
            name = _find_ident(node) or ""
            if name:
                results.append(
                    {
                        "name": name,
                        "type": type_text,
                        "init": "",
                        "range": range_text,
                        "decl": decl_text,
                        "range_source": range_source,
                        "is_static": "true" if is_static else "false",
                        "desc": desc_text,
                    }
                )
    return results


def parse_c_project(
    source_root: str,
    *,
    max_files: int = 300,
    preprocess: bool = False,
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
    cpp_path: str = "gcc",
) -> Dict[str, List[Dict[str, any]]]:
    root = Path(source_root).resolve()
    if not root.exists():
        return {"functions": [], "globals": [], "scanned": []}
    allowed = {".c", ".h", ".cpp", ".hpp"}
    functions: List[Dict[str, any]] = []
    globals_list: Set[str] = set()
    globals_detailed: List[Dict[str, str]] = []
    scanned: List[str] = []
    preprocess_stats: Dict[str, int] = {"gcc": 0, "clang": 0, "no-preprocess": 0}
    parser = None
    if Parser is not None and c_language is not None:
        parser = Parser()
        lang = c_language()
        try:
            parser.set_language(lang)
        except Exception:
            if Language is not None:
                parser.language = Language(lang)
            else:
                raise
    count = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() not in allowed:
                continue
            path = Path(dirpath) / name
            count += 1
            if count > max_files:
                break
            scanned.append(str(path))
            try:
                preprocessor_used = "no-preprocess"
                if preprocess:
                    data, preprocessor_used = _run_preprocessor_fallback(
                        path,
                        include_dirs=include_dirs,
                        defines=defines,
                        cpp_path=cpp_path,
                    )
                else:
                    data = None
                if data is None:
                    preprocessor_used = "no-preprocess"
                    data = path.read_bytes()
                preprocess_stats[preprocessor_used] = preprocess_stats.get(preprocessor_used, 0) + 1
            except Exception:
                continue
            raw_text = ""
            try:
                raw_text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                raw_text = ""
            file_globals: Set[str] = set()
            funcs: List[CFunction] = []
            if parser is not None:
                tree = parser.parse(data)
                root_node = tree.root_node
                file_globals = set(_extract_globals(root_node, data))
                funcs = _extract_function_defs(root_node, data, str(path), file_globals)
            if not funcs:
                funcs = _extract_function_defs_regex_fallback(raw_text, str(path), file_globals)
            for f in funcs:
                functions.append(
                    {
                        "name": f.name,
                        "signature": f.signature,
                        "is_static": f.is_static,
                        "file": f.file,
                        "calls": f.calls,
                        "used_globals": f.used_globals,
                        "comment_desc": f.comment_desc,
                        "comment_asil": f.comment_asil,
                        "comment_related": f.comment_related,
                        "comment_precondition": f.comment_precondition,
                        "body": f.body_text,
                    }
                )
            if parser is not None:
                tree = parser.parse(data)
                root_node = tree.root_node
                for g in _extract_globals(root_node, data):
                    if not g:
                        continue
                    globals_list.add(g)
                    globals_detailed.append({"name": g, "file": str(path)})
                for g in _extract_global_decls(root_node, data):
                    if not isinstance(g, dict):
                        continue
                    name = g.get("name") or ""
                    if not name:
                        continue
                    globals_list.add(name)
                    g["file"] = str(path)
                    globals_detailed.append(g)
        if count > max_files:
            break
    return {
        "functions": functions,
        "globals": sorted(globals_list),
        "globals_detailed": globals_detailed,
        "scanned": scanned,
        "preprocess_stats": preprocess_stats,
    }
