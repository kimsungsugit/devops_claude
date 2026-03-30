from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List
from workflow.function_module_map import build_function_module_index

try:
    from docx import Document  # type: ignore
    from docx.document import Document as DocxDocument  # type: ignore
    from docx.oxml.table import CT_Tbl  # type: ignore
    from docx.oxml.text.paragraph import CT_P  # type: ignore
    from docx.table import Table  # type: ignore
    from docx.text.paragraph import Paragraph  # type: ignore
except ImportError:  # pragma: no cover
    Document = None  # type: ignore
    DocxDocument = None  # type: ignore
    CT_Tbl = None  # type: ignore
    CT_P = None  # type: ignore
    Table = None  # type: ignore
    Paragraph = None  # type: ignore


_FUNCTION_PATTERN = re.compile(
    r"\b(?:ap_[A-Za-z0-9_]+|g_[A-Za-z0-9_]+|s_[A-Za-z0-9_]+|v_[A-Za-z0-9_]+|u(?:8|16|32|64)[A-Za-z0-9_]+)\b"
)
_MODULE_PATTERN = re.compile(r"\bSwCom[_ ]?\d+\b|\b[A-Z][A-Za-z0-9]+Ctrl\b|\b[A-Z][A-Za-z0-9]+(?:Module|Manager|System)\b")
_DIRECT_MODULE_HEADING_PATTERN = re.compile(r"^(SwCom[_ ]?\d+)\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_GENERIC_MODULE_SECTION_HEADINGS = {
    "software component information",
    "component folder struct",
    "revision history",
    "task scheduling summary",
}


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _paragraph_style_name(paragraph: Any) -> str:
    try:
        return str(paragraph.style.name or "")
    except Exception:
        return ""


def _iter_block_items(doc: Any):
    if DocxDocument is None:
        return
    parent_elm = doc.element.body
    for child in parent_elm.iterchildren():
        if CT_P is not None and isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif CT_Tbl is not None and isinstance(child, CT_Tbl):
            yield Table(child, doc)


def _table_to_text(table: Any) -> str:
    lines: List[str] = []
    for row in getattr(table, "rows", []):
        cells = []
        for cell in getattr(row, "cells", []):
            text = _normalize_whitespace(getattr(cell, "text", ""))
            if text:
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines).strip()


def _split_sds_sections(path: Path) -> List[Dict[str, Any]]:
    if Document is None:
        raise RuntimeError("python-docx not installed")
    doc = Document(str(path))
    sections: List[Dict[str, Any]] = []
    current_heading = "Document Overview"
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        text = "\n".join(line for line in current_lines if line).strip()
        if text:
            sections.append({"heading": current_heading, "text": text})
        current_lines = []

    for block in _iter_block_items(doc):
        if Paragraph is not None and isinstance(block, Paragraph):
            text = str(block.text or "").strip()
            if not text:
                continue
            style_name = _paragraph_style_name(block).lower()
            is_heading = "heading" in style_name or ("title" in style_name and len(text) < 120)
            if is_heading:
                flush()
                current_heading = text
            else:
                current_lines.append(text)
        elif Table is not None and isinstance(block, Table):
            table_text = _table_to_text(block)
            if table_text:
                current_lines.append(table_text)
    flush()
    if not sections:
        body = "\n".join(_normalize_whitespace(p.text) for p in doc.paragraphs if str(p.text or "").strip()).strip()
        if body:
            sections.append({"heading": "Document Overview", "text": body})
    return sections


def _extract_functions(*values: str) -> List[str]:
    found = []
    seen = set()
    for value in values:
        for match in _FUNCTION_PATTERN.findall(str(value or "")):
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


def _extract_modules(*values: str) -> List[str]:
    found = []
    seen = set()
    for value in values:
        for match in _MODULE_PATTERN.findall(str(value or "")):
            token = _normalize_whitespace(match)
            if token and token not in seen:
                seen.add(token)
                found.append(token)
    return found


def _derive_modules_from_functions(functions: List[str]) -> List[str]:
    derived: List[str] = []
    seen = set()
    for func in functions:
        parts = [part for part in str(func or "").split("_") if part]
        if len(parts) < 2:
            continue
        core = parts[1]
        token = re.sub(r"[^A-Za-z0-9]", "", core)
        if not token:
            continue
        label = token[:1].upper() + token[1:]
        if label not in seen:
            seen.add(label)
            derived.append(label)
    return derived


def _is_toc_section(heading: str, text: str) -> bool:
    heading_norm = _normalize_whitespace(heading).lower()
    if heading_norm in {"contents", "table of contents"}:
        return True
    text_norm = str(text or "")
    lines = [line.strip() for line in text_norm.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    toc_line_pattern = re.compile(r"^\d+(?:\.\d+)*[\.\t ]+.+?\d+$")
    toc_like = sum(1 for line in lines[:20] if toc_line_pattern.match(line))
    return toc_like >= 5


def _extract_direct_heading_module(heading: str) -> str:
    match = _DIRECT_MODULE_HEADING_PATTERN.match(_normalize_whitespace(heading))
    if not match:
        return ""
    return _normalize_whitespace(match.group(1)).replace(" ", "_")


def _is_generic_multi_module_section(heading: str, modules: List[str], funcs: List[str]) -> bool:
    heading_norm = _normalize_whitespace(heading).lower()
    module_set = {_normalize_whitespace(module).lower() for module in modules if _normalize_whitespace(module)}
    if heading_norm in _GENERIC_MODULE_SECTION_HEADINGS:
        return True
    return not funcs and len(module_set) >= 3


def build_sds_view_model(
    path: str,
    *,
    max_items: int = 500,
    changed_functions: Dict[str, str] | None = None,
    changed_files: List[str] | None = None,
    flagged_modules: List[str] | None = None,
) -> Dict[str, Any]:
    target = Path(str(path or "")).expanduser().resolve()
    if not target.exists() or target.is_dir():
        raise FileNotFoundError(str(target))
    if target.suffix.lower() != ".docx":
        raise ValueError("SDS view currently supports .docx only")

    sections = _split_sds_sections(target)
    changed_map = {str(name): str(kind or "").upper() for name, kind in (changed_functions or {}).items()}
    function_module_index = build_function_module_index(changed_map, changed_files=list(changed_files or []))
    derived_flagged_modules = _derive_modules_from_functions(list(changed_map.keys()))
    derived_flagged_modules += [str(info.get("best_module") or "") for info in function_module_index.values() if str(info.get("best_module") or "").strip()]
    flagged_module_set = {
        str(name).strip().lower()
        for name in ([*(flagged_modules or []), *derived_flagged_modules])
        if str(name).strip()
    }
    function_map: Dict[str, Dict[str, Any]] = {}
    module_map: Dict[str, Dict[str, Any]] = {}
    section_items: List[Dict[str, Any]] = []

    def ensure_item(store: Dict[str, Dict[str, Any]], key: str, *, kind: str, title: str, function_name: str = "", module_name: str = "") -> Dict[str, Any]:
        item = store.get(key)
        if item is None:
            item = {
                "id": f"{kind}:{key}",
                "kind": kind,
                "title": title,
                "functionName": function_name or "",
                "moduleName": module_name or "",
                "summary": "",
                "sections": [],
                "relatedFunctions": [],
                "relatedModules": [],
                "changed": False,
                "reviewRequired": False,
                "changeTypes": [],
            }
            store[key] = item
        return item

    def append_section(item: Dict[str, Any], section_block: Dict[str, Any], *, prioritize: bool = False) -> None:
        sections_list = item["sections"]
        heading = str(section_block.get("heading") or "")
        if any(str(existing.get("heading") or "") == heading for existing in sections_list):
            return
        if prioritize:
            sections_list.insert(0, section_block)
        else:
            sections_list.append(section_block)

    for index, section in enumerate(sections):
        heading = _normalize_whitespace(section.get("heading"))
        text = str(section.get("text") or "").strip()
        is_toc = _is_toc_section(heading, text)
        funcs = [] if is_toc else _extract_functions(heading, text)
        modules = [] if is_toc else _extract_modules(heading, text)
        direct_heading_module = "" if is_toc else _extract_direct_heading_module(heading)
        if direct_heading_module:
            modules = [direct_heading_module]
        if not modules and funcs:
            modules = _derive_modules_from_functions(funcs)
        section_block = {"heading": heading or f"Section {index + 1}", "text": text}
        if not is_toc and _is_generic_multi_module_section(heading, modules, funcs):
            section_items.append(
                {
                    "id": f"section:{index + 1}",
                    "kind": "section",
                    "title": heading or f"Section {index + 1}",
                    "functionName": "",
                    "moduleName": "",
                    "summary": _normalize_whitespace(text)[:240],
                    "sections": [section_block],
                    "relatedFunctions": funcs,
                    "relatedModules": modules,
                    "changed": False,
                    "reviewRequired": False,
                    "changeTypes": [],
                }
            )
            continue

        if funcs:
            for func in funcs:
                item = ensure_item(function_map, func, kind="function", title=func, function_name=func)
                append_section(item, section_block, prioritize=bool(direct_heading_module))
                item["relatedFunctions"] = sorted(set(item["relatedFunctions"] + funcs))
                item["relatedModules"] = sorted(set(item["relatedModules"] + modules))
                if direct_heading_module or not item["summary"]:
                    item["summary"] = _normalize_whitespace(text)[:240]
                if func in changed_map:
                    item["changed"] = True
                    item["changeTypes"] = sorted(set(item["changeTypes"] + [changed_map[func]]))
                    mapping = function_module_index.get(func) or {}
                    if mapping.get("module_candidates"):
                        item["moduleCandidates"] = list(mapping.get("module_candidates") or [])
                        item["matchSources"] = [str(candidate.get("source") or "") for candidate in item["moduleCandidates"] if str(candidate.get("source") or "").strip()]
                    if str(mapping.get("best_module") or "").strip():
                        item["relatedModules"] = sorted(set(item["relatedModules"] + [str(mapping.get("best_module"))]))
                    if mapping.get("source_files"):
                        item["sourceFiles"] = list(mapping.get("source_files") or [])
                    item["matchConfidence"] = float(mapping.get("best_confidence") or 0)
                if any(module.strip().lower() in flagged_module_set for module in modules):
                    item["reviewRequired"] = True
            for module in modules:
                module_item = ensure_item(module_map, module, kind="module", title=module, module_name=module)
                append_section(module_item, section_block, prioritize=module == direct_heading_module)
                module_item["relatedFunctions"] = sorted(set(module_item["relatedFunctions"] + funcs))
                module_item["relatedModules"] = sorted(set(module_item["relatedModules"] + modules))
                if module == direct_heading_module or not module_item["summary"]:
                    module_item["summary"] = _normalize_whitespace(text)[:240]
                if module.strip().lower() in flagged_module_set:
                    module_item["reviewRequired"] = True
        elif modules:
            for module in modules:
                item = ensure_item(module_map, module, kind="module", title=module, module_name=module)
                append_section(item, section_block, prioritize=module == direct_heading_module)
                item["relatedFunctions"] = sorted(set(item["relatedFunctions"] + funcs))
                item["relatedModules"] = sorted(set(item["relatedModules"] + modules))
                if module == direct_heading_module or not item["summary"]:
                    item["summary"] = _normalize_whitespace(text)[:240]
                if module.strip().lower() in flagged_module_set:
                    item["reviewRequired"] = True
        else:
            section_items.append(
                {
                    "id": f"section:{index + 1}",
                    "kind": "section",
                    "title": heading or f"Section {index + 1}",
                    "functionName": "",
                    "moduleName": "",
                    "summary": _normalize_whitespace(text)[:240],
                    "sections": [section_block],
                    "relatedFunctions": [],
                    "relatedModules": [],
                    "changed": False,
                    "reviewRequired": False,
                    "changeTypes": [],
                }
            )

    for module, item in module_map.items():
        related_funcs = list(item.get("relatedFunctions") or [])
        matched_change_types = sorted({changed_map[name] for name in related_funcs if name in changed_map})
        if matched_change_types:
            item["changed"] = True
            item["changeTypes"] = matched_change_types
        confidence = 0.0
        source_files: List[str] = []
        for func in related_funcs:
            mapping = function_module_index.get(func) or {}
            if str(mapping.get("best_module") or "").strip().lower() == str(module).strip().lower():
                confidence = max(confidence, float(mapping.get("best_confidence") or 0))
                item["moduleCandidates"] = list(mapping.get("module_candidates") or [])
                item["matchSources"] = [str(candidate.get("source") or "") for candidate in item["moduleCandidates"] if str(candidate.get("source") or "").strip()]
            source_files.extend(list(mapping.get("source_files") or []))
        if confidence:
            item["matchConfidence"] = confidence
        if source_files:
            item["sourceFiles"] = sorted(set(source_files))
        if module.strip().lower() in flagged_module_set:
            item["reviewRequired"] = True

    for item in function_map.values():
        if any(str(module).strip().lower() in flagged_module_set for module in (item.get("relatedModules") or [])):
            item["reviewRequired"] = True

    items: List[Dict[str, Any]] = list(function_map.values()) + list(module_map.values()) + section_items
    items.sort(
        key=lambda item: (
            0 if item.get("reviewRequired") else 1 if item.get("changed") else 2,
            0 if item["kind"] == "function" else 1 if item["kind"] == "module" else 2,
            -float(item.get("matchConfidence") or 0),
            item["title"].lower(),
        )
    )
    if max_items > 0:
        items = items[: max_items]
    return {
        "path": str(target),
        "generatedAt": "",
        "items": items,
        "counts": {
            "functions": sum(1 for item in items if item["kind"] == "function"),
            "modules": sum(1 for item in items if item["kind"] == "module"),
            "sections": sum(1 for item in items if item["kind"] == "section"),
        },
    }
