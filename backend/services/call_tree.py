from __future__ import annotations

import re
import json
import csv
import io
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


_CODE_EXTS = {".c", ".h", ".cpp", ".hpp"}
_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "catch",
    "case",
    "do",
    "else",
}

_EXTERNAL_HEADER_MAP = {
    "stdio.h": {
        "printf",
        "sprintf",
        "snprintf",
        "scanf",
        "puts",
        "putchar",
        "getchar",
        "fopen",
        "fclose",
        "fread",
        "fwrite",
        "fprintf",
        "fscanf",
    },
    "string.h": {
        "memcpy",
        "memset",
        "memcmp",
        "strlen",
        "strcpy",
        "strncpy",
        "strcat",
        "strncat",
        "strcmp",
        "strncmp",
        "strchr",
        "strrchr",
        "strstr",
    },
    "stdlib.h": {
        "malloc",
        "free",
        "calloc",
        "realloc",
        "atoi",
        "atof",
        "strtol",
        "strtoul",
        "exit",
        "abs",
        "rand",
        "srand",
    },
    "math.h": {"sin", "cos", "tan", "sqrt", "pow", "fabs", "floor", "ceil"},
}


def _classify_external(name: str) -> Dict[str, str]:
    for header, funcs in _EXTERNAL_HEADER_MAP.items():
        if name in funcs:
            return {"header": header, "library": header.replace(".h", "")}
    return {"header": "unknown", "library": "unknown"}


def _build_external_lookup(custom_map: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, str]]:
    lookup: Dict[str, Dict[str, str]] = {}
    for header, funcs in _EXTERNAL_HEADER_MAP.items():
        for name in funcs:
            lookup[name] = {"header": header, "library": header.replace(".h", "")}
    for item in custom_map or []:
        if not isinstance(item, dict):
            continue
        header = str(item.get("header") or "unknown")
        library = str(item.get("library") or header.replace(".h", ""))
        names = item.get("names") or item.get("name")
        if isinstance(names, str):
            names = [n.strip() for n in names.replace("\n", ",").split(",") if n.strip()]
        if not isinstance(names, list):
            continue
        for name in names:
            if not name:
                continue
            lookup[str(name)] = {"header": header, "library": library}
    return lookup


def _normalize_tokens(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for item in values:
        raw = str(item).replace("\\", "/").strip().strip("/")
        if raw:
            out.append(raw)
    return out


def _matches_filters(rel_path: str, include: List[str], exclude: List[str]) -> bool:
    rel_norm = rel_path.replace("\\", "/").strip("/")
    if exclude:
        for token in exclude:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return False
    if include:
        for token in include:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return True
        return False
    return True


def _strip_comments_and_strings(text: str) -> str:
    out = []
    i = 0
    length = len(text)
    in_block = False
    in_line = False
    in_str = False
    in_chr = False
    while i < length:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < length else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
            i += 1
            continue
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == "\"":
                in_str = False
            i += 1
            continue
        if in_chr:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_chr = False
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if ch == "\"":
            in_str = True
            i += 1
            continue
        if ch == "'":
            in_chr = True
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _iter_source_files(
    root_dir: Path,
    include_paths: List[str],
    exclude_paths: List[str],
    max_files: int,
) -> List[Path]:
    out: List[Path] = []
    for path in root_dir.rglob("*"):
        if len(out) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in _CODE_EXTS:
            continue
        rel = path.relative_to(root_dir).as_posix()
        if not _matches_filters(rel, include_paths, exclude_paths):
            continue
        out.append(path)
    return out


def _load_compile_commands(path: Path, source_root: Path) -> List[Path]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    files: List[Path] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        file_value = item.get("file")
        if not file_value:
            continue
        file_path = Path(str(file_value))
        if not file_path.is_absolute():
            directory = Path(str(item.get("directory") or "")).resolve()
            if directory:
                file_path = (directory / file_path).resolve()
        if file_path.suffix.lower() not in _CODE_EXTS:
            continue
        try:
            if file_path.exists() and file_path.is_file() and file_path.resolve().is_relative_to(source_root):
                files.append(file_path.resolve())
        except Exception:
            continue
    uniq = sorted({p for p in files})
    return uniq


def _scan_functions(source_files: List[Path]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    func_defs: Dict[str, Dict[str, Any]] = {}
    duplicates: List[Dict[str, Any]] = []
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", re.MULTILINE)
    for path in source_files:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        cleaned = _strip_comments_and_strings(raw)
        for match in pattern.finditer(cleaned):
            name = match.group(1)
            if name in _KEYWORDS:
                continue
            start = match.end() - 1
            depth = 0
            end = None
            for idx in range(start, len(cleaned)):
                if cleaned[idx] == "{":
                    depth += 1
                elif cleaned[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx
                        break
            if end is None:
                continue
            body = cleaned[start + 1 : end]
            if name in func_defs:
                duplicates.append({"name": name, "path": str(path)})
                continue
            func_defs[name] = {"name": name, "path": str(path), "body": body}
    return func_defs, duplicates


def _extract_calls(
    body: str,
    known_funcs: Set[str],
    external_lookup: Dict[str, Dict[str, str]],
) -> Tuple[List[str], List[Dict[str, str]]]:
    calls: Set[str] = set()
    externals: Dict[str, Dict[str, str]] = {}
    if not body:
        return [], []
    call_pat = re.compile(r"\b([A-Za-z_]\w*)\s*\(", re.MULTILINE)
    for match in call_pat.finditer(body):
        callee = match.group(1)
        if callee in _KEYWORDS:
            continue
        if callee in known_funcs:
            calls.add(callee)
        else:
            if callee not in externals:
                externals[callee] = {"name": callee, **external_lookup.get(callee, _classify_external(callee))}
    return sorted(calls), [externals[k] for k in sorted(externals.keys())]


def _build_tree(
    name: str,
    call_map: Dict[str, List[str]],
    external_map: Dict[str, List[Dict[str, str]]],
    max_depth: int,
    depth: int,
    visited: Set[str],
    include_external: bool,
) -> Dict[str, Any]:
    node: Dict[str, Any] = {"name": name, "calls": []}
    if depth >= max_depth:
        node["truncated"] = True
        return node
    if name in visited:
        node["cycle"] = True
        return node
    visited.add(name)
    for callee in call_map.get(name, []):
        node["calls"].append(
            _build_tree(callee, call_map, external_map, max_depth, depth + 1, set(visited), include_external)
        )
    if include_external:
        node["externals"] = external_map.get(name, [])
    return node


def build_call_tree(
    source_root: Path,
    entries: List[str],
    include_paths: Optional[List[str]] = None,
    exclude_paths: Optional[List[str]] = None,
    max_depth: int = 5,
    max_files: int = 2000,
    include_external: bool = False,
    compile_commands_path: Optional[Path] = None,
    external_map: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    root_dir = Path(source_root).resolve()
    include_tokens = _normalize_tokens(include_paths)
    exclude_tokens = _normalize_tokens(exclude_paths)
    compile_db = compile_commands_path or (root_dir / "compile_commands.json")
    if compile_db.exists():
        src_files = _load_compile_commands(compile_db, root_dir)
        src_files = [
            p for p in src_files
            if _matches_filters(p.relative_to(root_dir).as_posix(), include_tokens, exclude_tokens)
        ]
        src_files = src_files[:max_files]
    else:
        src_files = _iter_source_files(root_dir, include_tokens, exclude_tokens, max_files)
    func_defs, duplicates = _scan_functions(src_files)
    known = set(func_defs.keys())
    call_map: Dict[str, List[str]] = {}
    external_map: Dict[str, List[Dict[str, str]]] = {}
    external_lookup = _build_external_lookup(external_map)
    for name, info in func_defs.items():
        calls, externals = _extract_calls(info.get("body", ""), known, external_lookup)
        call_map[name] = calls
        external_map[name] = externals
    trees = []
    missing = []
    for entry in entries:
        if entry not in known:
            missing.append(entry)
            continue
        trees.append(_build_tree(entry, call_map, external_map, max_depth, 0, set(), include_external))
    edges = sum(len(v) for v in call_map.values())
    return {
        "source_root": str(root_dir),
        "entries": entries,
        "trees": trees,
        "missing": missing,
        "stats": {
            "files_scanned": len(src_files),
            "functions": len(known),
            "edges": edges,
            "duplicates": len(duplicates),
            "compile_commands": str(compile_db) if compile_db.exists() else "",
        },
    }


def call_tree_to_csv(payload: Dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    job_url = (meta or {}).get("job_url", "")
    build_selector = (meta or {}).get("build_selector", "")
    build_root = (meta or {}).get("build_root", "")
    writer.writerow(["entry_root", "parent", "callee", "type", "header", "library", "depth", "path", "job_url", "build_selector", "build_root"])

    def _walk(node: Dict[str, Any], depth: int, path: str, entry_root: str) -> None:
        parent = node.get("name")
        for child in node.get("calls") or []:
            child_name = child.get("name")
            child_path = f"{path} > {child_name}" if path else str(child_name)
            writer.writerow([
                entry_root,
                parent,
                child_name,
                "internal",
                "",
                "",
                depth + 1,
                child_path,
                job_url,
                build_selector,
                build_root,
            ])
            _walk(child, depth + 1, child_path, entry_root)
        for ext in node.get("externals") or []:
            ext_name = ext.get("name")
            ext_path = f"{path} > {ext_name}" if path else str(ext_name)
            writer.writerow([
                entry_root,
                parent,
                ext_name,
                "external",
                ext.get("header"),
                ext.get("library"),
                depth + 1,
                ext_path,
                job_url,
                build_selector,
                build_root,
            ])

    for root in payload.get("trees") or []:
        root_name = root.get("name")
        _walk(root, 0, str(root_name), str(root_name))
    return buf.getvalue()


def call_tree_to_html(payload: Dict[str, Any], template: Optional[str] = None) -> str:
    def _render_node(node: Dict[str, Any]) -> str:
        name = node.get("name", "")
        flags = []
        if node.get("cycle"):
            flags.append("cycle")
        if node.get("truncated"):
            flags.append("truncated")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        html = [f"<li><strong>{name}</strong>{flag_text}"]
        externals = node.get("externals") or []
        if externals:
            html.append("<ul>")
            for ext in externals:
                html.append(
                    f"<li>{ext.get('name')} <em>[{ext.get('header')} | {ext.get('library')}]</em></li>"
                )
            html.append("</ul>")
        children = node.get("calls") or []
        if children:
            html.append("<ul>")
            for child in children:
                html.append(_render_node(child))
            html.append("</ul>")
        html.append("</li>")
        return "".join(html)

    tree_parts = ["<ul>"]
    for root in payload.get("trees") or []:
        tree_parts.append(_render_node(root))
    tree_parts.append("</ul>")
    tree_html = "".join(tree_parts)

    raw_template = (template or "").strip()
    if raw_template:
        if "{{tree}}" in raw_template or "{{content}}" in raw_template:
            return raw_template.replace("{{tree}}", tree_html).replace("{{content}}", tree_html)
        return raw_template + tree_html

    parts = [
        "<html><head><meta charset='utf-8'/>",
        "<style>body{font-family:Arial,sans-serif;font-size:13px} ul{list-style:disc;margin-left:16px}</style>",
        "</head><body>",
        "<h3>Function Call Tree</h3>",
        tree_html,
        "</body></html>",
    ]
    return "".join(parts)
