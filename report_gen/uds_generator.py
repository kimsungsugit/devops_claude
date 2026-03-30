"""report_gen.uds_generator - Auto-split from report_generator.py"""
# Re-import common dependencies
import re

# ---------------------------------------------------------------------------
# Payload field name constants
# ---------------------------------------------------------------------------
# Two-level naming convention:
#
#   Function-level  (per-function dict, value = List[str] of variable names):
#     KEY_FN_GLOBALS  — global  variables *used* by this function
#     KEY_FN_STATICS  — static  variables *used* by this function
#
#   Module-level  (top-level payload, value = List[List[str]] 5-column table):
#     KEY_MOD_GLOBALS — global  variable *definitions* table for the whole module
#     KEY_MOD_STATICS — static  variable *definitions* table for the whole module
#
# Legacy alias: some older sidecar JSONs may still use the bare key "globals"
# which maps to KEY_FN_GLOBALS.  Readers must handle the fallback
# (see validation.py _extract_payload_function_details).
#
KEY_FN_GLOBALS = "globals_global"   # per-function: global var names list
KEY_FN_STATICS = "globals_static"   # per-function: static var names list
KEY_MOD_GLOBALS = "global_vars"     # module-level: global var definitions table
KEY_MOD_STATICS = "static_vars"     # module-level: static var definitions table
# Legacy key kept for backward compat when reading old sidecar JSON files
KEY_FN_GLOBALS_LEGACY = "globals"
# ---------------------------------------------------------------------------
import os
import json
import csv
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from io import BytesIO, StringIO
from html import escape

from report.constants import (
    DEFAULT_TYPE_RANGES,
    UDS_SERVICE_TABLE,
    UDS_DID_PATTERNS,
    UDS_SERVICE_ID_PATTERNS,
)
from report_gen.source_parser import (
    _extract_doxygen_asil_tags,
    _extract_file_header_asil,
)
from report_gen.function_analyzer import (
    _parse_signature_outputs,
    _is_static_var,
    _fallback_function_description,
    _parse_signature_params,
    _extract_logic_flow,
    _extract_condition_branch_calls,
    _normalize_symbol_name,
    _enhance_function_description,
    _normalize_bracket_expr,
    _is_generic_description,
    _collect_var_usage,
    _extract_logic_terminal_paths,
    _format_param_entry,
    _enhance_description_text,
    _extract_return_type,
    _split_param,
    _extract_primary_condition,
    _infer_precondition_from_body,
)
from report_gen.requirements import (
    _load_component_map,
    _extract_requirements_from_comments,
    _collect_section_lines,
    _normalize_table_row,
    _split_doc_function_blocks,
    _extract_function_blocks,
    _extract_state_tokens,
    _extract_table_section,
)
from report_gen.source_parser import (
    _scan_source_comment_patterns,
    _extract_c_macros,
    _read_text_limited,
    _strip_c_comments,
    _extract_c_prototypes,
    _extract_c_global_candidates,
    _extract_c_function_bodies,
    _extract_c_macro_defs,
    _extract_c_definitions,
    _extract_local_static_candidates,
    _extract_fallback_call_names,
    _extract_macro_call_names,
    _extract_function_pointer_call_targets,
)
from report_gen.uds_text import (
    _merge_logic_ai_items,
    _apply_uds_rules,
    _merge_section_text,
    _ai_document_text,
    _uds_lines_to_html,
    _ai_evidence_lines,
    _uds_logic_html,
)
from report_gen.utils import (
    _normalize_swcom_label,
    _infer_type_from_decl,
    _extract_simple_call_names,
    _safe_dict,
    _infer_type_from_file,
)

_logger = logging.getLogger("report_generator")

def generate_uds_logic_items(
    texts: List[str],
    mode: str,
    source_root: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    mode = str(mode or "").strip().lower()
    if mode not in {"call_tree", "state_table", "comment_pattern"}:
        return []
    if mode == "comment_pattern":
        return _scan_source_comment_patterns(source_root)
    items: List[Dict[str, Any]] = []
    for txt in texts:
        for block in _split_doc_function_blocks(txt):
            lines = block.get("lines") or []
            title = block.get("title") or block.get("id") or "Logic Diagram"
            desc = ""
            if mode == "call_tree":
                called = _collect_section_lines(lines, "Called Function")
                calling = _collect_section_lines(lines, "Calling Function")
                parts: List[str] = []
                if called:
                    parts.append("Called: " + ", ".join(called[:12]))
                if calling:
                    parts.append("Calling: " + ", ".join(calling[:12]))
                desc = " / ".join(parts) if parts else "N/A"
            elif mode == "state_table":
                states = _extract_state_tokens(lines)
                if states:
                    desc = "States: " + ", ".join(states[:20])
                else:
                    desc = "N/A"
            items.append({"title": title, "description": desc})
            if len(items) >= limit:
                return items
    return items


def _group_function_blocks_by_swcom(blocks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for block in blocks:
        swcom = str(block.get("swcom") or "").strip() or "SwCom_Unknown"
        groups.setdefault(swcom, []).append(block)
    return groups


def _format_function_block_lines(block: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    header = str(block.get("header") or "")
    if header:
        lines.append(header)
    if block.get("id"):
        lines.append(f"ID\t{block.get('id')}")
    if block.get("name"):
        lines.append(f"Name\t{block.get('name')}")
    if block.get("prototype"):
        lines.append(f"Prototype\t{block.get('prototype')}")
    if block.get("description"):
        lines.append(f"Description\t{block.get('description')}")
    if block.get("asil"):
        lines.append(f"ASIL\t{block.get('asil')}")
    if block.get("related"):
        lines.append(f"Related ID\t{block.get('related')}")
    if block.get("precondition"):
        lines.append(f"선행조건\t{block.get('precondition')}")
    if block.get("globals"):
        lines.append(f"사용 전역변수\t{block.get('globals')}")
    if block.get("called"):
        lines.append(f"Called Function\t{block.get('called')}")
    if block.get("calling"):
        lines.append(f"Calling Function\t{block.get('calling')}")
    inputs = block.get("inputs") or []
    if inputs:
        lines.append("[ Input Parameters ]")
        lines.extend(inputs)
    outputs = block.get("outputs") or []
    if outputs:
        lines.append("[ Output Parameters ]")
        lines.extend(outputs)
    if block.get("logic"):
        lines.append("[ Logic Diagram ]")
        lines.append("Logic Diagram: present")
    return lines


def parse_uds_preview_html(html: str) -> Dict[str, List[str]]:
    if not html:
        return {}
    sections = {"Overview": [], "Requirements": [], "Interfaces": [], "UDS Frames": [], "Notes": []}
    for name in sections.keys():
        m = re.search(rf"<h3>{re.escape(name)}</h3>(.*?)<h3>|<h3>{re.escape(name)}</h3>(.*)$", html, re.S)
        if not m:
            continue
        block = m.group(1) or m.group(2) or ""
        items = re.findall(r"<li>(.*?)</li>", block, flags=re.S)
        cleaned = [re.sub(r"<.*?>", "", i).strip() for i in items if i.strip()]
        sections[name] = cleaned
    return sections


def generate_uds_source_sections(
    source_root: str,
    component_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, str]:
    root = Path(source_root).resolve()
    if not root.exists():
        return {}
    allowed = {".c", ".h", ".cpp", ".hpp"}
    try:
        import config as _cfg
        max_files = getattr(_cfg, "UDS_MAX_SOURCE_FILES", 1200)
        max_items = getattr(_cfg, "UDS_MAX_FUNCTION_ITEMS", 120)
    except Exception:
        max_files = 1200
        max_items = 120
    files: List[Path] = []
    ext_counts: Dict[str, int] = {}
    top_dirs: Dict[str, int] = {}
    interfaces: List[str] = []
    internals: List[str] = []
    unknowns: List[str] = []
    macros: List[str] = []
    reqs: List[str] = []
    common_macros: List[str] = []
    type_defs: List[str] = []
    param_defs: List[str] = []
    version_defs: List[str] = []
    global_data: List[str] = []
    global_vars: List[List[str]] = []
    static_vars: List[List[str]] = []
    macro_defs: List[List[str]] = []
    calibration_params: List[List[str]] = []
    function_table_rows: List[List[str]] = []
    function_details: Dict[str, Dict[str, Any]] = {}
    function_details_by_name: Dict[str, Dict[str, Any]] = {}
    call_map: Dict[str, List[str]] = {}
    fallback_functions: List[Dict[str, Any]] = []
    module_map: Dict[str, str] = {}
    globals_info_map: Dict[str, Dict[str, str]] = {}
    manual_globals_info_map: Dict[str, Dict[str, str]] = {}
    source_text_cache: Dict[str, str] = {}
    if component_map is None:
        component_map = _load_component_map()

    def _upsert_signature(items: List[str], signature: str, display: str) -> None:
        if not signature:
            return
        for idx, item in enumerate(items):
            if item.startswith(signature):
                items[idx] = display
                return
        items.append(display)

    truncated = False
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            ext = p.suffix.lower()
            if ext not in allowed:
                continue
            if component_map:
                mapped = component_map.get(p.name) or component_map.get(p.stem)
                if isinstance(mapped, dict):
                    verify = str(mapped.get("verify") or "").strip().upper()
                    if verify == "X":
                        continue
            files.append(p)
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            rel = p.relative_to(root)
            top = rel.parts[0] if rel.parts else "."
            top_dirs[top] = top_dirs.get(top, 0) + 1
            if len(files) >= max_files:
                truncated = True
                break
        if truncated:
            break

    doc_texts: List[str] = []
    _doxygen_tags_by_file: Dict[str, Dict[str, Dict[str, str]]] = {}
    _file_header_asil: Dict[str, str] = {}
    for p in files:
        raw = _read_text_limited(p)
        text = _strip_c_comments(raw)
        reqs.extend(_extract_requirements_from_comments(raw))
        dox_tags = _extract_doxygen_asil_tags(raw)
        if dox_tags:
            _doxygen_tags_by_file[str(p)] = dox_tags
        hdr_asil = _extract_file_header_asil(raw)
        if hdr_asil:
            _file_header_asil[str(p)] = hdr_asil
        for g in _extract_c_global_candidates(text):
            gname = str(g.get("name") or "").strip()
            if not gname:
                continue
            prev = manual_globals_info_map.get(gname, {})
            manual_globals_info_map[gname] = {
                "type": str(g.get("type") or prev.get("type") or "").strip(),
                "file": str(p),
                "range": str(prev.get("range") or "").strip(),
                "init": str(g.get("init") or prev.get("init") or "").strip(),
                "range_source": str(prev.get("range_source") or "").strip(),
                "static": str(g.get("static") or prev.get("static") or "false").strip().lower(),
                "desc": str(prev.get("desc") or "").strip(),
            }
        if p.suffix.lower() in {".h", ".hpp"}:
            for name, params, is_extern in _extract_c_prototypes(text):
                signature = f"{name}({params})"
                if name.startswith("g_"):
                    interfaces.append(signature)
                elif name.startswith("s_"):
                    internals.append(signature)
                elif is_extern:
                    interfaces.append(signature)
                else:
                    interfaces.append(signature)
            macros.extend(_extract_c_macros(text))
            for m_name, m_val in _extract_c_macro_defs(text):
                macro_defs.append([m_name, "", m_val, ""])
        else:
            body_map = _extract_c_function_bodies(text)
            for name, params, is_static in _extract_c_definitions(text):
                signature = f"{name}({params})"
                if name.startswith("g_"):
                    interfaces.append(signature)
                elif name.startswith("s_"):
                    internals.append(signature)
                elif is_static:
                    internals.append(signature)
                else:
                    unknowns.append(signature)
                body_text = str(body_map.get(name) or "")
                calls_list = _extract_simple_call_names(body_text)
                dox_info = _doxygen_tags_by_file.get(str(p), {}).get(name, {})
                file_asil = _file_header_asil.get(str(p), "")
                c_asil = dox_info.get("asil", "") or file_asil
                c_related = dox_info.get("requirement", "")
                c_desc = dox_info.get("brief", "")
                fallback_functions.append(
                    {
                        "name": name,
                        "signature": signature,
                        "is_static": bool(is_static),
                        "file": str(p),
                        "calls": calls_list,
                        "used_globals": [],
                        "comment_desc": c_desc,
                        "comment_asil": c_asil,
                        "comment_related": c_related,
                        "comment_precondition": "",
                        "body": body_text,
                    }
                )
            source_text_cache[str(p)] = raw
            macros.extend(_extract_c_macros(text))
            for m_name, m_val in _extract_c_macro_defs(text):
                macro_defs.append([m_name, "", m_val, ""])

        lines = raw.splitlines()
        stop_headers = [
            "Type Definition",
            "Parameter Definition",
            "Version Information",
            "Software Unit Structure",
        ]
        cm = _extract_table_section(lines, "Common Macro Definition", stop_headers, 30)
        td = _extract_table_section(lines, "Type Definition", stop_headers, 30)
        pd = _extract_table_section(lines, "Parameter Definition", stop_headers, 30)
        vd = _extract_table_section(lines, "Version Information", stop_headers, 10)
        common_macros.extend(cm)
        type_defs.extend(td)
        param_defs.extend(pd)
        version_defs.extend(vd)

        if (
            len(interfaces) >= max_items
            and len(internals) >= max_items
            and len(macros) >= max_items
            and len(reqs) >= max_items
        ):
            break

    # additional documentation files (txt/md) for structured templates
    doc_files = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in {".txt", ".md"}:
                continue
            p = Path(dirpath) / name
            doc_texts.append(_read_text_limited(p))
            doc_files += 1
            if doc_files >= 20:
                break
        if doc_files >= 20:
            break

    function_blocks: List[Dict[str, Any]] = []
    for txt in doc_texts:
        function_blocks.extend(_extract_function_blocks(txt))
        cm = _extract_table_section(
            txt.splitlines(),
            "Common Macro Definition",
            ["Type Definition", "Parameter Definition", "Version Information", "Software Unit Structure"],
            30,
        )
        td = _extract_table_section(
            txt.splitlines(),
            "Type Definition",
            ["Parameter Definition", "Version Information", "Software Unit Structure"],
            30,
        )
        pd = _extract_table_section(
            txt.splitlines(),
            "Parameter Definition",
            ["Version Information", "Software Unit Structure"],
            30,
        )
        vd = _extract_table_section(
            txt.splitlines(),
            "Version Information",
            ["Software Unit Structure"],
            10,
        )
        common_macros.extend(cm)
        type_defs.extend(td)
        param_defs.extend(pd)
        version_defs.extend(vd)

    fallback_function_name_set: Set[str] = {
        str(fn.get("name") or "").strip()
        for fn in fallback_functions
        if str(fn.get("name") or "").strip()
    }

    # AST 기반 보강 (가능 시)
    try:
        from workflow.code_parser import parse_c_project  # type: ignore
    except Exception:
        parse_c_project = None  # type: ignore
    if parse_c_project is not None:
        try:
            ast_result = parse_c_project(str(root), max_files=max_files, preprocess=True)
        except Exception:
            ast_result = {"functions": [], "globals": []}
        module_ids: Dict[str, int] = {}
        module_order = [
            k for k, _ in sorted(top_dirs.items(), key=lambda x: (-x[1], x[0]))
        ]
        next_module_idx = 1
        for name in module_order:
            module_ids[name] = next_module_idx
            next_module_idx += 1
        globals_detailed = ast_result.get("globals_detailed", []) or []
        function_name_set: Set[str] = set()
        used_identifier_set: Set[str] = set()
        for ftmp in ast_result.get("functions", []) or []:
            if isinstance(ftmp, dict):
                n = str(ftmp.get("name") or "").strip()
                if n:
                    function_name_set.add(n)
                body_blob = str(ftmp.get("body_text") or ftmp.get("body") or "")
                if body_blob:
                    used_identifier_set.update(
                        re.findall(r"\b[A-Za-z_]\w*\b", _strip_c_comments(body_blob))
                    )
        function_name_set.update(fallback_function_name_set)
        globals_info_map = dict(manual_globals_info_map)
        static_name_map: Dict[str, bool] = {}
        for gk, gv in globals_info_map.items():
            try:
                static_name_map[gk] = str((gv or {}).get("static") or "").strip().lower() == "true"
            except Exception:
                static_name_map[gk] = False
        macro_name_set: Set[str] = set()
        for row in macro_defs:
            if row:
                macro_name_set.add(str(row[0]).strip())
        for row in common_macros:
            cols = _normalize_table_row(row)
            if cols:
                macro_name_set.add(str(cols[0]).strip())
        macro_value_map: Dict[str, str] = {}
        for row in macro_defs:
            if len(row) >= 3:
                macro_value_map[str(row[0]).strip()] = str(row[2]).strip()
        for row in common_macros:
            cols = _normalize_table_row(row)
            if len(cols) >= 3:
                macro_value_map[str(cols[0]).strip()] = str(cols[2]).strip()
        if globals_detailed:
            for g in globals_detailed:
                if not isinstance(g, dict):
                    continue
                gname = str(g.get("name") or "").strip()
                if gname in function_name_set:
                    continue
                if gname in macro_name_set:
                    continue
                gtype = str(g.get("type") or "").strip()
                gfile = str(g.get("file") or "").strip()
                grange = str(g.get("range") or "").strip()
                gdecl = str(g.get("decl") or "").strip()
                # Skip function prototypes accidentally surfaced as globals.
                if gdecl and "(" in gdecl and ")" in gdecl:
                    continue
                if not gtype and gdecl:
                    gtype = _infer_type_from_decl(gdecl, gname)
                if gtype.lower() == "void" and re.match(r"^[gs]_", gname):
                    continue
                if not gtype and gfile:
                    gtype, init_from_file = _infer_type_from_file(gfile, gname)
                    if not g.get("init") and init_from_file:
                        g = dict(g)
                        g["init"] = init_from_file
                if gtype.lower() == "void" and re.match(r"^[gs]_", gname):
                    continue
                is_static = str(g.get("is_static") or "").strip().lower() == "true"
                if not is_static and gname:
                    from config import STATIC_VAR_PREFIXES
                    if any(gname.startswith(p) for p in STATIC_VAR_PREFIXES):
                        is_static = True
                if gname:
                    prev = globals_info_map.get(gname, {}) if isinstance(globals_info_map.get(gname), dict) else {}
                    incoming_desc = str(g.get("desc") or "").strip()
                    static_name_map[gname] = is_static
                    globals_info_map[gname] = {
                        "type": gtype or str(prev.get("type") or "").strip(),
                        "file": gfile or str(prev.get("file") or "").strip(),
                        "range": grange or str(prev.get("range") or "").strip(),
                        "init": str(g.get("init") or "").strip() or str(prev.get("init") or "").strip(),
                        "range_source": str(g.get("range_source") or "").strip().lower(),
                        "static": "true" if is_static else "false",
                        "desc": incoming_desc or str(prev.get("desc") or "").strip(),
                    }
        for src_file in [f for f in files if f.suffix.lower() == ".c"][:200]:
            try:
                src_text = src_file.read_text(encoding="utf-8", errors="replace")
                source_text_cache[str(src_file)] = src_text
            except Exception:
                continue
            for g in _extract_c_global_candidates(src_text):
                vname = str(g.get("name") or "").strip()
                if vname and str(g.get("static") or "").strip().lower() == "true":
                    static_name_map[vname] = True
        try:
            import config as _cfg
            _global_prefixes = tuple(getattr(_cfg, "GLOBAL_VAR_PREFIXES", ())) + tuple(
                getattr(_cfg, "STATIC_VAR_PREFIXES", ())
            )
        except Exception:
            _global_prefixes = ("g_", "s_", "u8g_", "u16g_", "u32g_", "u8s_", "u16s_", "u32s_")
        _extern_added = 0
        c_source_texts = [text for path, text in source_text_cache.items() if str(path).lower().endswith(".c")]
        for hdr_file in [f for f in files if f.suffix.lower() == ".h"][:300]:
            try:
                hdr_text = hdr_file.read_text(encoding="utf-8", errors="replace")
                source_text_cache[str(hdr_file)] = hdr_text
            except Exception:
                continue
            for item in _extract_c_global_candidates(hdr_text):
                if str(item.get("extern") or "").strip().lower() != "true":
                    continue
                etype = str(item.get("type") or "").strip()
                ename = str(item.get("name") or "").strip()
                if not ename or ename in globals_info_map or ename in function_name_set or ename in macro_name_set:
                    continue
                if etype.lower() in {"void"}:
                    continue
                used_in_body = ename in used_identifier_set
                used_in_source = used_in_body or any(
                    re.search(rf"\b{re.escape(ename)}\b", src_text) for src_text in c_source_texts
                )
                if not used_in_source:
                    continue
                if (not any(ename.startswith(p) for p in _global_prefixes)) and not used_in_body:
                    continue
                globals_info_map[ename] = {
                    "type": etype,
                    "file": str(hdr_file),
                    "range": "",
                    "init": "",
                    "range_source": "extern_usage" if used_in_body else "extern_weak_usage",
                    "static": "false",
                    "desc": "",
                }
                _extern_added += 1
        if _extern_added > 0:
            _logger.info("extern variable scan: added %d variables from headers", _extern_added)
        if globals_info_map:
            globals_info_map = {
                k: v for k, v in globals_info_map.items() if str(v.get("type") or "").strip()
            }
        macro_globals_map: Dict[str, List[str]] = {}
        macro_call_map: Dict[str, List[str]] = {}
        if globals_info_map:
            global_names = list(globals_info_map.keys())
            for row in macro_defs:
                if len(row) >= 3:
                    m_name = str(row[0]).strip()
                    m_val = str(row[2]).strip()
                    if not m_name or not m_val:
                        continue
                    hits = [g for g in global_names if re.search(rf"\b{re.escape(g)}\b", m_val)]
                    if hits:
                        macro_globals_map[m_name] = hits
                    call_hits: List[str] = []
                    for call_name in _extract_simple_call_names(m_val):
                        if call_name in function_name_set and call_name not in call_hits:
                            call_hits.append(call_name)
                    if call_hits:
                        macro_call_map[m_name] = call_hits[:10]

        # 접근자 함수 패턴: get_*/set_* 함수가 전역변수를 반환/설정하는 패턴 감지
        _accessor_globals_map: Dict[str, List[str]] = {}
        if globals_info_map:
            for fn in ast_result.get("functions", []) or []:
                if not isinstance(fn, dict):
                    continue
                fname = str(fn.get("name") or "").strip()
                if not fname:
                    continue
                fname_lower = fname.lower()
                is_accessor = (
                    fname_lower.startswith("get_") or fname_lower.startswith("set_")
                    or fname_lower.startswith("get") or fname_lower.startswith("set")
                )
                if not is_accessor:
                    continue
                body = str(fn.get("body_text") or fn.get("body") or "").strip()
                used = fn.get("used_globals") or []
                if not isinstance(used, list):
                    used = []
                accessed_globals = [g for g in used if g in globals_info_map]
                if not accessed_globals and body:
                    for gname in list(globals_info_map.keys())[:500]:
                        if re.search(rf"\b{re.escape(gname)}\b", body):
                            accessed_globals.append(gname)
                if accessed_globals:
                    _accessor_globals_map[fname.lower()] = accessed_globals[:10]
            if _accessor_globals_map:
                _logger.info("Accessor function globals: %d accessor functions detected", len(_accessor_globals_map))

        callee_signature_map: Dict[str, str] = {}
        for f2 in ast_result.get("functions", []) or []:
            if not isinstance(f2, dict):
                continue
            n2 = str(f2.get("name") or "").strip()
            s2 = str(f2.get("signature") or "").strip()
            if n2 and s2 and n2 not in callee_signature_map:
                callee_signature_map[n2] = s2

        def _merge_call_candidates(
            fn_name: str,
            file_path: str,
            body_text: str,
            ast_calls: List[str],
        ) -> Tuple[List[str], str]:
            merged: List[str] = []
            source_parts: List[str] = []
            for name in ast_calls or []:
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if merged:
                source_parts.append("ast")
            for name in _extract_simple_call_names(body_text):
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if len(merged) > len(ast_calls or []):
                source_parts.append("body")
            macro_calls = _extract_macro_call_names(body_text, macro_call_map)
            for name in macro_calls:
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if macro_calls:
                source_parts.append("macro")
            fptr_calls = _extract_function_pointer_call_targets(body_text, function_name_set)
            for name in fptr_calls:
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if fptr_calls:
                source_parts.append("fptr")
            if not merged:
                fb = _extract_fallback_call_names(
                    source_text_cache.get(file_path, ""),
                    fn_name,
                    function_name_set,
                    body_text,
                )
                for name in fb:
                    if name and name != fn_name and name not in merged:
                        merged.append(name)
                if fb:
                    source_parts.append("fallback")
            return merged[:50], "+".join(source_parts) if source_parts else ""

        for fn in ast_result.get("functions", []) or []:
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name") or "").strip()
            signature = str(fn.get("signature") or name).strip()
            is_static = bool(fn.get("is_static"))
            file_path = str(fn.get("file") or "").strip()
            calls = fn.get("calls") or []
            used_globals = fn.get("used_globals") or []
            comment_desc = str(fn.get("comment_desc") or "").strip()
            comment_asil = str(fn.get("comment_asil") or "").strip()
            comment_related = str(fn.get("comment_related") or "").strip()
            comment_precond = str(fn.get("comment_precondition") or "").strip()
            if not name:
                continue
            if file_path and file_path not in source_text_cache:
                try:
                    source_text_cache[file_path] = Path(file_path).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    source_text_cache[file_path] = ""
            if not isinstance(calls, list):
                calls = []
            calls = [str(c).strip() for c in calls if str(c).strip()]
            body_text_full = str(fn.get("body_text") or fn.get("body") or "")
            calls, calls_source = _merge_call_candidates(name, file_path, body_text_full, calls)
            if calls_source:
                fn["calls_source"] = calls_source
            if isinstance(calls, list):
                call_map[name] = [str(c).strip() for c in calls if str(c).strip()]
            call_suffix = ""
            if isinstance(calls, list) and calls:
                call_suffix = f" calls: {', '.join([str(c) for c in calls[:6] if c])}"
            file_suffix = f" [{Path(file_path).name}]" if file_path else ""
            display = f"{signature}{file_suffix}{call_suffix}".strip()
            if is_static:
                _upsert_signature(internals, signature, display)
            else:
                _upsert_signature(interfaces, signature, display)
            module_name = "Module"
            if file_path:
                try:
                    rel = Path(file_path).resolve().relative_to(root)
                    module_name = rel.parts[0] if rel.parts else "Module"
                except Exception:
                    module_name = "Module"
            if component_map and file_path:
                key = Path(file_path).name
                mapped = component_map.get(key) or component_map.get(Path(file_path).stem)
                if isinstance(mapped, dict) and mapped.get("component"):
                    module_name = str(mapped.get("component"))
                    module_name = _normalize_swcom_label(module_name)
            module_map[name] = module_name
            if module_name not in module_ids:
                module_ids[module_name] = next_module_idx
                next_module_idx += 1
            mod_idx = module_ids.get(module_name, 0)
            counter = sum(1 for r in function_table_rows if r[1] == module_name) + 1
            fn_id = f"SwUFn_{mod_idx:02d}{counter:02d}" if mod_idx else f"SwUFn_{counter:04d}"
            lname = name.lower()
            if lname.startswith("s_"):
                fn_type = "Internal"
            elif lname.startswith("g_"):
                fn_type = "I/F"
            else:
                fn_type = "Internal" if is_static else "I/F"
            function_table_rows.append(
                [
                    f"SwCom_{mod_idx:02d}" if mod_idx else "SwCom_00",
                    module_name,
                    fn_id,
                    name,
                    fn_type,
                    "",
                ]
            )
            if fn_id not in function_details:
                used_globals_list: List[str] = []
            inputs_list: List[str] = []
            outputs_list: List[str] = []
            globals_static: List[str] = []
            globals_global: List[str] = []
            body_text = str(fn.get("body") or "")
            if body_text:
                params = _parse_signature_params(signature)
                param_names: List[str] = []
                for p in params:
                    _, pname, _ = _split_param(p)
                    if pname:
                        param_names.append(pname)
                param_usage = _collect_var_usage(body_text, param_names)
                global_names = list(globals_info_map.keys())
                global_usage = _collect_var_usage(body_text, global_names, macro_globals_map)
                for p in params:
                    ptype, pname, array_part = _split_param(p)
                    if not pname:
                        continue
                    u = param_usage.get(pname, {})
                    direction = "IN"
                    if u.get("inout"):
                        direction = "INOUT"
                    elif u.get("lhs") and not u.get("rhs"):
                        direction = "OUT"
                    elif u.get("rhs"):
                        direction = "IN"
                    names = [pname]
                    for member_name in sorted(list(u.get("members") or [])):
                        if member_name not in names:
                            names.append(member_name)
                    index_vals: List[str] = []
                    for idx_expr in u.get("indexes") or []:
                        norm, _ = _normalize_bracket_expr(str(idx_expr), macro_value_map)
                        if norm:
                            index_vals.append(norm)
                    index_vals = list(dict.fromkeys(index_vals))
                    pointer_range = "*" in ptype or "*" in p
                    for disp_name in names:
                        display = _format_param_entry(
                            disp_name,
                            ptype,
                            array_part,
                            index_vals,
                            macro_value_map,
                            pointer_range,
                            bool(u.get("divisor")),
                        )
                        if direction in {"IN", "INOUT"}:
                            inputs_list.append(f"[{direction}] {display}")
                        if direction in {"OUT", "INOUT"}:
                            outputs_list.append(f"[{direction}] {display}")
                for gname, u in global_usage.items():
                    if not u.get("lhs") and not u.get("rhs") and not u.get("inout"):
                        continue
                    direction = "INOUT" if u.get("inout") or (u.get("lhs") and u.get("rhs")) else "OUT" if u.get("lhs") else "IN"
                    names = [gname]
                    for member_name in sorted(list(u.get("members") or [])):
                        if member_name not in names:
                            names.append(member_name)
                    index_vals: List[str] = []
                    for idx_expr in u.get("indexes") or []:
                        norm, _ = _normalize_bracket_expr(str(idx_expr), macro_value_map)
                        if norm:
                            index_vals.append(norm)
                    index_vals = list(dict.fromkeys(index_vals))
                    for disp_name in names:
                        display = _format_param_entry(
                            disp_name,
                            "",
                            "",
                            index_vals,
                            macro_value_map,
                            False,
                            bool(u.get("divisor")),
                        )
                        entry = f"[{direction}] {display}"
                        if _is_static_var(gname, static_name_map):
                            globals_static.append(entry)
                        else:
                            globals_global.append(entry)
            else:
                if isinstance(used_globals, list):
                    call_set = set([str(c).strip() for c in calls] if isinstance(calls, list) else [])
                    for g in used_globals:
                        gname = str(g).strip()
                        if not gname or gname in call_set:
                            continue
                        used_globals_list.append(gname)
                globals_static = [g for g in used_globals_list if _is_static_var(g, static_name_map)]
                globals_global = [g for g in used_globals_list if not _is_static_var(g, static_name_map)]
                inputs_list = _parse_signature_params(signature, tag_direction=True)
                outputs_list = _parse_signature_outputs(signature, name)
            if body_text:
                local_static_set = set(g.strip() for g in globals_static)
                for ls_name in _extract_local_static_candidates(body_text):
                    if ls_name and ls_name not in local_static_set:
                        globals_static.append(ls_name)
                        local_static_set.add(ls_name)
            return_type = _extract_return_type(signature, name)
            if return_type and "void" not in return_type:
                m = re.search(r"\b(U8|U16|U32|S8|S16|S32)\b", return_type)
                base = m.group(1) if m else return_type.split()[-1]
                range_text = DEFAULT_TYPE_RANGES.get(base, "")
                return_entry = (
                    f"[OUT] return {return_type} (range: {range_text})"
                    if range_text
                    else f"[OUT] return {return_type}"
                )
                outputs_list = [return_entry] + outputs_list
            called_list = [str(c).strip() for c in calls if str(c).strip()] if isinstance(calls, list) else []
            called_sig_lines: List[str] = []
            for callee in called_list:
                sig = callee_signature_map.get(callee, "")
                if sig:
                    called_sig_lines.append(sig)
                else:
                    called_sig_lines.append(callee)
            called_text = "\n".join(called_sig_lines)
            desc_text = _enhance_description_text(
                name,
                comment_desc or _fallback_function_description(name, called_list),
                called_list,
            )
            if _is_generic_description(desc_text):
                module_hint = Path(file_path).stem if file_path else ""
                desc_text = _enhance_function_description(name, called_list, module_hint)
            true_calls, false_calls = _extract_condition_branch_calls(body_text)
            term_return, term_error = _extract_logic_terminal_paths(body_text)
            if name.lower() == "main" and called_list:
                init_first = called_list[0]
                follow_calls = ", ".join(called_list[1:6]) if len(called_list) > 1 else ""
                if follow_calls:
                    desc_text = (
                        f"Power-on 시 {init_first}를 호출해 시스템을 초기화하고, 이후 {follow_calls}를 순차 호출한다."
                    )
                else:
                    desc_text = f"Power-on 시 {init_first}를 호출해 시스템을 초기화한다."
            system_os_rules = {
                "s_sysmain_init": "시스템 초기 진입 시 주요 상태 변수/타이머를 초기화한다.",
                "s_systemoperation": "주기적으로 시스템 운전 상태를 갱신하고 동작 조건을 점검한다.",
                "s_systemdiagnosis": "진단 상태를 평가하고 오류 플래그를 갱신한다.",
                "s_systemmanagement": "시스템 상태 전이를 관리하고 운영 플래그를 유지한다.",
                "s_sysctrl_errorprotection": "오류 보호 로직을 수행하여 위험 상태를 차단한다.",
                "g_sysctrl_errorprotection": "오류 보호 로직을 수행하여 위험 상태를 차단한다.",
            }
            rkey = name.lower()
            if (not comment_desc) and rkey in system_os_rules:
                chain = ", ".join(called_list[:4]) if called_list else ""
                desc_text = system_os_rules[rkey]
                if chain:
                    desc_text = f"{desc_text} 호출 체인: {chain}."
            inferred_precond = comment_precond
            if not inferred_precond and body_text:
                inferred_precond = _infer_precondition_from_body(body_text, name)
            detail = {
                "id": fn_id,
                "name": name,
                "prototype": signature,
                "description": desc_text,
                "asil": comment_asil or "TBD",
                "related": comment_related or "TBD",
                "description_source": "comment" if comment_desc else "inference",
                "asil_source": "comment" if comment_asil else "inference",
                "related_source": "comment" if comment_related else "inference",
                "inputs": inputs_list,
                "outputs": outputs_list,
                "precondition": inferred_precond,
                "file": str(file_path) if file_path else "",
                "module_name": Path(file_path).stem if file_path else "",
                "comment_description": comment_desc,
                "comment_asil": comment_asil,
                "comment_related": comment_related,
                "globals_global": globals_global,
                "globals_static": globals_static,
                "called": called_text,
                "calls_list": called_list,
                "logic_condition": _extract_primary_condition(body_text),
                "logic_true_calls": true_calls,
                "logic_false_calls": false_calls,
                "logic_return_path": term_return,
                "logic_error_path": term_error,
                "logic_flow": _extract_logic_flow(body_text, called_list),
                "logic": "Auto(call tree)" if called_list else "",
            }
            function_details[fn_id] = detail
            function_details_by_name[name.lower()] = detail
        # Fallback when AST parser returns no functions (parser unavailable).
        if (not function_table_rows) and fallback_functions:
            for fn in fallback_functions:
                name = str(fn.get("name") or "").strip()
                signature = str(fn.get("signature") or name).strip()
                is_static = bool(fn.get("is_static"))
                file_path = str(fn.get("file") or "").strip()
                calls = fn.get("calls") or []
                if not name:
                    continue
                if file_path and file_path not in source_text_cache:
                    try:
                        source_text_cache[file_path] = Path(file_path).read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        source_text_cache[file_path] = ""
                if not isinstance(calls, list):
                    calls = []
                calls = [str(c).strip() for c in calls if str(c).strip()]
                calls, calls_source = _merge_call_candidates(
                    name,
                    file_path,
                    str(fn.get("body") or ""),
                    calls,
                )
                if calls_source:
                    fn["calls_source"] = calls_source
                call_map[name] = [str(c).strip() for c in calls if str(c).strip()]
                module_name = "Module"
                if file_path:
                    try:
                        rel = Path(file_path).resolve().relative_to(root)
                        module_name = rel.parts[0] if rel.parts else "Module"
                    except Exception:
                        module_name = "Module"
                if component_map and file_path:
                    key = Path(file_path).name
                    mapped = component_map.get(key) or component_map.get(Path(file_path).stem)
                    if isinstance(mapped, dict) and mapped.get("component"):
                        module_name = str(mapped.get("component"))
                        module_name = _normalize_swcom_label(module_name)
                module_map[name] = module_name
                if module_name not in module_ids:
                    module_ids[module_name] = next_module_idx
                    next_module_idx += 1
                mod_idx = module_ids.get(module_name, 0)
                counter = sum(1 for r in function_table_rows if r[1] == module_name) + 1
                fn_id = f"SwUFn_{mod_idx:02d}{counter:02d}" if mod_idx else f"SwUFn_{counter:04d}"
                fn_type = "Internal" if is_static else "I/F"
                if name.lower().startswith("s_"):
                    fn_type = "Internal"
                elif name.lower().startswith("g_"):
                    fn_type = "I/F"
                function_table_rows.append(
                    [
                        f"SwCom_{mod_idx:02d}" if mod_idx else "SwCom_00",
                        module_name,
                        fn_id,
                        name,
                        fn_type,
                        "",
                    ]
                )
                called_list = [str(c).strip() for c in calls if str(c).strip()] if isinstance(calls, list) else []
                inputs_list = [f"[IN] {p}" for p in _parse_signature_params(signature)]
                outputs_list = _parse_signature_outputs(signature, name)
                desc_text = _enhance_description_text(
                    name,
                    _fallback_function_description(name, called_list),
                    called_list,
                )
                if _is_generic_description(desc_text):
                    module_hint = Path(file_path).stem if file_path else ""
                    desc_text = _enhance_function_description(name, called_list, module_hint)
                body_text = str(fn.get("body") or "")
                global_names = list(globals_info_map.keys())
                global_usage = _collect_var_usage(body_text, global_names) if body_text and global_names else {}
                globals_global: List[str] = []
                globals_static: List[str] = []
                _seen_globals: set = set()
                for gname, gusage in global_usage.items():
                    if not isinstance(gusage, dict):
                        continue
                    if not any(bool(gusage.get(k)) for k in ["lhs", "rhs", "inout", "members", "indexes", "divisor"]):
                        continue
                    is_static_g = bool(static_name_map.get(gname, False))
                    if is_static_g:
                        globals_static.append(gname)
                    else:
                        globals_global.append(gname)
                    _seen_globals.add(gname.lower())
                # 접근자 함수 호출을 통한 간접 globals
                if _accessor_globals_map and called_list:
                    for callee in called_list:
                        callee_lower = callee.strip().lower()
                        accessor_globals = _accessor_globals_map.get(callee_lower, [])
                        for ag in accessor_globals:
                            if ag.lower() not in _seen_globals:
                                is_static_g = bool(static_name_map.get(ag, False))
                                if is_static_g:
                                    globals_static.append(f"[INDIRECT] {ag}")
                                else:
                                    globals_global.append(f"[INDIRECT] {ag}")
                                _seen_globals.add(ag.lower())
                if body_text:
                    local_static_set = set(str(x).strip() for x in globals_static)
                    for ls_name in _extract_local_static_candidates(body_text):
                        if ls_name and ls_name not in local_static_set:
                            globals_static.append(ls_name)
                            local_static_set.add(ls_name)
                true_calls, false_calls = _extract_condition_branch_calls(body_text)
                term_return, term_error = _extract_logic_terminal_paths(body_text)
                detail = {
                    "id": fn_id,
                    "name": name,
                    "prototype": signature,
                    "description": desc_text,
                    "asil": "TBD",
                    "related": "TBD",
                    "description_source": "inference",
                    "asil_source": "inference",
                    "related_source": "inference",
                    "inputs": inputs_list,
                    "outputs": outputs_list,
                    "precondition": "N/A",
                    "file": str(file_path) if file_path else "",
                    "module_name": Path(file_path).stem if file_path else "",
                    "comment_description": "",
                    "comment_asil": "",
                    "comment_related": "",
                    "globals_global": globals_global,
                    "globals_static": globals_static,
                    "called": "\n".join(called_list),
                    "calls_list": called_list,
                    "logic_condition": _extract_primary_condition(body_text),
                    "logic_true_calls": true_calls,
                    "logic_false_calls": false_calls,
                    "logic_return_path": term_return,
                    "logic_error_path": term_error,
                    "logic_flow": _extract_logic_flow(body_text, called_list),
                    "logic": "Auto(call tree)" if called_list else "",
                }
                function_details[fn_id] = detail
                function_details_by_name[name.lower()] = detail
        if globals_detailed:
            for g in globals_detailed:
                if not isinstance(g, dict):
                    continue
                gname = str(g.get("name") or "").strip()
                if gname in macro_name_set:
                    continue
                gfile = str(g.get("file") or "").strip()
                gtype = str(g.get("type") or "").strip()
                ginit = str(g.get("init") or "").strip()
                is_static = str(g.get("is_static") or "").strip().lower() == "true"
                if not gname:
                    continue
                if not gtype and gname in globals_info_map:
                    gtype = str(globals_info_map.get(gname, {}).get("type") or "").strip()
                if not gtype and gfile:
                    gtype2, init2 = _infer_type_from_file(gfile, gname)
                    if gtype2:
                        gtype = gtype2
                    if init2 and not ginit:
                        ginit = init2
                if not gtype:
                    continue
                file_suffix = f" [{Path(gfile).name}]" if gfile else ""
                global_data.append(f"{gname}{file_suffix}".strip())
                row = [gname, gtype, "", ginit, ""]
                if is_static:
                    static_vars.append(row)
                else:
                    global_vars.append(row)
        else:
            if globals_info_map:
                for gname, info in globals_info_map.items():
                    gname = str(gname or "").strip()
                    if not gname or gname in macro_name_set:
                        continue
                    gtype = str((info or {}).get("type") or "").strip()
                    gfile = str((info or {}).get("file") or "").strip()
                    ginit = str((info or {}).get("init") or "").strip()
                    is_static = str((info or {}).get("static") or "").strip().lower() == "true"
                    if not gtype:
                        continue
                    file_suffix = f" [{Path(gfile).name}]" if gfile else ""
                    global_data.append(f"{gname}{file_suffix}".strip())
                    row = [gname, gtype, "", ginit, ""]
                    if is_static:
                        static_vars.append(row)
                    else:
                        global_vars.append(row)
            else:
                for g in ast_result.get("globals", []) or []:
                    if not isinstance(g, str):
                        continue
                    if g.strip():
                        if g.strip() in macro_name_set:
                            continue
                        global_data.append(g.strip())

    # 문서 기반 Function 블록 정보로 보강
    if function_blocks:
        for block in function_blocks:
            if not isinstance(block, dict):
                continue
            bid = str(block.get("id") or "").strip()
            bname = str(block.get("name") or "").strip()
            target = None
            if bid and bid in function_details:
                target = function_details.get(bid)
            if target is None and bname:
                target = function_details_by_name.get(bname.lower())
            if not isinstance(target, dict):
                continue
            for key in ["description", "asil", "related", "precondition", "logic"]:
                if not target.get(key) and block.get(key):
                    target[key] = block.get(key)
            if block.get("inputs") and not target.get("inputs"):
                target["inputs"] = block.get("inputs")
            if block.get("outputs") and not target.get("outputs"):
                target["outputs"] = block.get("outputs")
            if block.get("called") and not target.get("called"):
                target["called"] = block.get("called")

    def _unique(items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    interfaces = _unique(interfaces)[:max_items]
    internals = _unique(internals)[:max_items]
    unknowns = _unique(unknowns)[:max_items]
    macros = _unique(macros)[:max_items]
    reqs = _unique(reqs)[:max_items]
    common_macros = _unique(common_macros)[:max_items]
    type_defs = _unique(type_defs)[:max_items]
    param_defs = _unique(param_defs)[:max_items]
    version_defs = _unique(version_defs)[:max_items]
    global_data = _unique(global_data)[: max_items * 2]
    macro_defs = macro_defs[: max_items * 2]
    if param_defs:
        for row in param_defs:
            cols = _normalize_table_row(row)
            if len(cols) >= 3:
                calibration_params.append([cols[0], cols[1], cols[2], cols[3] if len(cols) > 3 else ""])

    type_range_map: Dict[str, str] = {}
    for row in type_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            rng = str(cols[2]).strip()
            if not rng or rng.upper() in {"-", "N/A"}:
                continue
            type_range_map[cols[0]] = rng
            type_range_map[cols[1]] = rng
    default_type_ranges = {
        "U8": "0 ~ 255",
        "U16": "0 ~ 65535",
        "U32": "0 ~ 4294967295",
        "S8": "-128 ~ 127",
        "S16": "-32768 ~ 32767",
        "S32": "-2147483648 ~ 2147483647",
    }
    if not type_range_map:
        type_range_map = dict(default_type_ranges)
    param_range_map: Dict[str, str] = {}
    for row in param_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            param_range_map[cols[0]] = cols[2]
    macro_value_map: Dict[str, str] = {}
    for row in macro_defs:
        if len(row) >= 3:
            macro_value_map[str(row[0]).strip()] = str(row[2]).strip()
    for row in common_macros:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            macro_value_map[str(cols[0]).strip()] = str(cols[2]).strip()
    macro_range_map: Dict[str, str] = {}
    for m_name in macro_value_map.keys():
        m = re.match(r"(.+)_MIN$", m_name)
        if m:
            base = m.group(1)
            max_key = f"{base}_MAX"
            if max_key in macro_value_map:
                macro_range_map[base] = f"{macro_value_map[m_name]} ~ {macro_value_map[max_key]}"
    for gname, info in globals_info_map.items():
        source = str(info.get("range_source") or "").strip().lower()
        if source == "comment":
            continue
        current = str(info.get("range") or "").strip()
        init = str(info.get("init") or "").strip()
        resolved = ""
        if init and init in macro_value_map:
            base = init.replace("_MIN", "").replace("_MAX", "")
            if base in macro_range_map:
                resolved = macro_range_map[base]
            if not resolved and init in macro_value_map:
                resolved = macro_value_map.get(init, "")
        if not resolved and gname in param_range_map:
            resolved = param_range_map[gname]
        if not resolved:
            gtype = info.get("type") or ""
            if gtype in type_range_map:
                resolved = type_range_map[gtype]
            if not resolved and gtype in default_type_ranges:
                resolved = default_type_ranges[gtype]
        if not resolved and init:
            resolved = init
        if not resolved and current:
            resolved = current
        if resolved:
            info["range"] = resolved

    if globals_info_map:
        new_global_vars: List[List[str]] = []
        new_static_vars: List[List[str]] = []
        # fallback from global/static rows if info_map missing fields
        for row in global_vars + static_vars:
            if not row:
                continue
            name = str(row[0] or "").strip()
            if not name:
                continue
            info = globals_info_map.setdefault(name, {})
            if len(row) > 1 and not info.get("type"):
                info["type"] = str(row[1] or "").strip()
            if len(row) > 2 and not info.get("range"):
                info["range"] = str(row[2] or "").strip()
            if len(row) > 3 and not info.get("init"):
                info["init"] = str(row[3] or "").strip()
        for name, info in globals_info_map.items():
            if not str(info.get("type") or "").strip():
                continue
            row = [
                name,
                info.get("type") or "",
                info.get("range") or "",
                info.get("init") or "",
                "",
            ]
            if info.get("static") == "true":
                new_static_vars.append(row)
            else:
                new_global_vars.append(row)
        if new_global_vars:
            global_vars = new_global_vars
        if new_static_vars:
            static_vars = new_static_vars

    top_sorted = sorted(top_dirs.items(), key=lambda x: (-x[1], x[0]))
    top_list = ", ".join([k for k, _ in top_sorted[:5]]) if top_sorted else "N/A"
    file_count = len(files)

    ext_summary = ", ".join([f"{k}:{v}" for k, v in sorted(ext_counts.items())]) or "N/A"
    overview_lines = [
        f"Source root: {root}",
        f"Files scanned: {file_count} ({ext_summary})",
        f"Top modules: {top_list}",
        f"Public interfaces: {len(interfaces)}, Internal functions: {len(internals)}, Global data: {len(global_data)}",
    ]
    if truncated:
        overview_lines.append("Scan truncated to first 400 files.")

    requirements_lines: List[str] = []
    for row in common_macros:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            requirements_lines.append(
                f"Common Macro: {cols[0]} ({cols[1]}={cols[2]})"
            )
    for row in type_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            requirements_lines.append(
                f"Type Definition: {cols[1]} = {cols[0]} ({cols[2]})"
            )
    for row in param_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            requirements_lines.append(
                f"Parameter: {cols[0]} ({cols[1]}={cols[2]})"
            )
    if version_defs:
        versions = []
        for row in version_defs:
            cols = _normalize_table_row(row)
            if len(cols) >= 2:
                versions.append(f"{cols[0]}={cols[1]}")
        if versions:
            requirements_lines.append(f"Version Information: {', '.join(versions)}")
    for req in reqs:
        requirements_lines.append(f"Requirement: {req}")
    if not requirements_lines:
        requirements_lines = [
            "Source-only draft. Verify against requirements and safety goals.",
            "Derive test cases from public interfaces and internal flows.",
            "Update with system-level requirements when available.",
        ]

    if function_blocks:
        for block in function_blocks[:max_items]:
            name = block.get("name") or block.get("id") or "UnknownFunction"
            desc = block.get("description") or "Description TBD"
            proto = block.get("prototype") or "Prototype TBD"
            asil = block.get("asil") or "TBD"
            line = f"Function Spec: {name} {proto} - {desc} (ASIL {asil})"
            requirements_lines.append(line)

    interfaces_lines = interfaces or ["N/A"]

    from report.constants import UDS_SERVICE_TABLE, UDS_DID_PATTERNS, UDS_SERVICE_ID_PATTERNS
    did_entries: List[str] = []
    service_entries: List[str] = []
    did_function_map: Dict[str, List[str]] = {}
    _did_pats = [re.compile(p, re.I) for p in UDS_DID_PATTERNS]
    _sid_pats = [re.compile(p, re.I) for p in UDS_SERVICE_ID_PATTERNS]
    for fn in (ast_result.get("functions", []) if parse_c_project is not None else fallback_functions):
        fn_name = str(fn.get("name") or "").strip()
        fn_body = str(fn.get("body") or "").strip()
        if not fn_name or not fn_body:
            continue
        for pat in _did_pats:
            for dm in pat.finditer(fn_body):
                did_val = dm.group(0).strip()
                if did_val and did_val not in did_entries:
                    did_entries.append(did_val)
                did_function_map.setdefault(did_val, [])
                if fn_name not in did_function_map[did_val]:
                    did_function_map[did_val].append(fn_name)
        for pat in _sid_pats:
            for sm in pat.finditer(fn_body):
                sid_raw = sm.group(0).strip()
                if sid_raw.startswith("0x") or sid_raw.startswith("0X"):
                    try:
                        sid_int = int(sid_raw, 16)
                        svc_name = UDS_SERVICE_TABLE.get(sid_int, "")
                        entry = f"0x{sid_int:02X} {svc_name} -> {fn_name}" if svc_name else f"{sid_raw} -> {fn_name}"
                    except ValueError:
                        entry = f"{sid_raw} -> {fn_name}"
                else:
                    entry = f"{sid_raw} -> {fn_name}"
                if entry not in service_entries:
                    service_entries.append(entry)

    frames_lines: List[str] = []
    if did_entries:
        frames_lines.append("=== DID Definitions ===")
        for d in did_entries[:40]:
            handlers = did_function_map.get(d, [])
            handler_str = f" (handlers: {', '.join(handlers[:5])})" if handlers else ""
            frames_lines.append(f"  {d}{handler_str}")
    if service_entries:
        frames_lines.append("=== UDS Service Mappings ===")
        frames_lines.extend(f"  {s}" for s in service_entries[:40])
    if not frames_lines:
        frames_lines = internals or ["N/A"]
    else:
        if internals:
            frames_lines.append("=== Internal Functions ===")
            frames_lines.extend(internals[:30])

    notes_lines = [
        "Generated from source-only scan.",
        "Function list is heuristic; review for accuracy.",
    ]
    if unknowns:
        notes_lines.append(f"Unclassified functions: {len(unknowns)}")
    if function_blocks:
        logic_count = sum(1 for b in function_blocks if b.get("logic") == "present")
        if logic_count:
            notes_lines.append(f"Logic diagram referenced: {logic_count} items")
    if not doc_texts:
        notes_lines.append("No artifact text docs found; fallback rules applied.")

    detail_lines: List[str] = []
    detail_lines.append("Software Unit Design")
    detail_lines.append("1. Common Macro Definition")
    detail_lines.extend(common_macros or ["N/A"])
    detail_lines.append("")
    detail_lines.append("2. Type Definition")
    detail_lines.extend(type_defs or ["N/A"])
    detail_lines.append("")
    detail_lines.append("3. Parameter Definition")
    detail_lines.extend(param_defs or ["N/A"])
    detail_lines.append("")
    detail_lines.append("4. Version Information")
    detail_lines.extend(version_defs or ["N/A"])
    detail_lines.append("")
    # 템플릿 기반 문서는 별도 섹션/표로 렌더링되므로 중복 나열을 피한다.
    max_blocks = 120
    if function_blocks:
        detail_lines.append("6. Function Information")
        grouped = _group_function_blocks_by_swcom(function_blocks)
        total_added = 0
        for swcom in sorted(grouped.keys()):
            detail_lines.append("")
            detail_lines.append(swcom)
            for block in grouped[swcom]:
                if total_added >= max_blocks:
                    detail_lines.append("[...truncated...]")
                    break
                detail_lines.extend(_format_function_block_lines(block))
                detail_lines.append("")
                total_added += 1
            if total_added >= max_blocks:
                break
    else:
        detail_lines.append("6. Function Information")
        detail_lines.append("N/A")

    # Backfill calling/input/output with normalized call graph and signature parsing.
    reverse_callers: Dict[str, List[str]] = {}
    reverse_callers_compact: Dict[str, List[str]] = {}
    compact_name_to_raw: Dict[str, str] = {}
    if isinstance(call_map, dict):
        for caller_name, callee_list in call_map.items():
            caller_norm = _normalize_symbol_name(str(caller_name or "")).lower()
            caller_comp = re.sub(r"[^a-z0-9]", "", caller_norm)
            if not caller_norm or not isinstance(callee_list, list):
                continue
            if caller_comp and caller_name:
                compact_name_to_raw.setdefault(caller_comp, str(caller_name).strip())
            for callee_name in callee_list:
                callee_norm = _normalize_symbol_name(str(callee_name or "")).lower()
                callee_comp = re.sub(r"[^a-z0-9]", "", callee_norm)
                if not callee_norm:
                    continue
                reverse_callers.setdefault(callee_norm, []).append(caller_norm)
                if callee_comp:
                    reverse_callers_compact.setdefault(callee_comp, []).append(caller_norm)
    for _, vals in list(reverse_callers.items()):
        seen_callers: List[str] = []
        for v in vals:
            if v and v not in seen_callers:
                seen_callers.append(v)
        vals[:] = seen_callers
    for _, vals in list(reverse_callers_compact.items()):
        seen_callers: List[str] = []
        for v in vals:
            if v and v not in seen_callers:
                seen_callers.append(v)
        vals[:] = seen_callers

    def _has_values(v: Any) -> bool:
        if isinstance(v, list):
            return any(str(x).strip() and str(x).strip().upper() not in {"N/A", "TBD", "-"} for x in v)
        text = str(v or "").strip()
        return bool(text) and text.upper() not in {"N/A", "TBD", "-"}

    calling_map: Dict[str, List[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            callee_lower = callee.lower() if callee else ""
            if callee_lower:
                calling_map.setdefault(callee_lower, [])
                if caller not in calling_map[callee_lower]:
                    calling_map[callee_lower].append(caller)

    def _call_edges(name: str) -> List[str]:
        if not name:
            return []
        vals = call_map.get(name)
        if vals is None:
            vals = call_map.get(name.lower(), [])
        return list(vals or [])

    def _get_2hop_calls(fn_name: str) -> List[str]:
        direct = _call_edges(fn_name)
        indirect: List[str] = []
        for d in direct:
            for hop2 in _call_edges(d):
                if hop2 not in direct and hop2 != fn_name and hop2 not in indirect:
                    indirect.append(hop2)
        return indirect

    def _get_2hop_callers(fn_name: str) -> List[str]:
        direct = calling_map.get(fn_name.lower(), [])
        indirect: List[str] = []
        for d in direct:
            for hop2 in calling_map.get(d.lower(), []):
                if hop2 not in direct and hop2 != fn_name and hop2 not in indirect:
                    indirect.append(hop2)
        return indirect

    def _entry_var_name(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        m = re.match(r"^\[(?:IN|OUT|INOUT|INDIRECT|INDIRECT2)\]\s+(.+)", text)
        if m:
            return m.group(1).split("|")[0].strip()
        return text.split("|")[0].strip()

    def _has_direct_globals(info: Dict[str, Any]) -> bool:
        for key in ("globals_global", "globals_static"):
            for item in info.get(key) or []:
                text = str(item or "").strip()
                if not text or text.upper() in {"N/A", "-"}:
                    continue
                if text.startswith("[INDIRECT"):
                    continue
                return True
        return False

    def _module_name_for(info: Dict[str, Any]) -> str:
        fname = str(info.get("name") or "").strip()
        return str(module_map.get(fname) or info.get("module_name") or "").strip()

    def _should_propagate_2hop(caller_info: Dict[str, Any], bridge_info: Dict[str, Any], leaf_info: Dict[str, Any]) -> bool:
        caller_module = _module_name_for(caller_info)
        bridge_module = _module_name_for(bridge_info)
        leaf_module = _module_name_for(leaf_info)
        if not caller_module or caller_module != bridge_module or caller_module != leaf_module:
            return False
        bridge_calls = bridge_info.get("calls_list") or []
        if len(bridge_calls) > 5:
            return False
        if not _has_direct_globals(leaf_info):
            return False
        return True

    for _, info in list(function_details.items()):
        if not isinstance(info, dict):
            continue
        fn_name = _normalize_symbol_name(str(info.get("name") or "")).lower()
        proto = str(info.get("prototype") or "").strip()
        if not _has_values(info.get("inputs")) and proto:
            info["inputs"] = _parse_signature_params(proto)
        if not _has_values(info.get("outputs")) and proto:
            info["outputs"] = _parse_signature_outputs(proto, str(info.get("name") or ""))
        if (not str(info.get("calling") or "").strip()) or str(info.get("calling") or "").strip().upper() in {"N/A", "TBD", "-"}:
            callers = list(reverse_callers.get(fn_name, []))
            fn_comp = re.sub(r"[^a-z0-9]", "", fn_name)
            callers += list(reverse_callers_compact.get(fn_comp, []))
            if callers:
                normalized_names: List[str] = []
                for c in callers:
                    ck = re.sub(r"[^a-z0-9]", "", str(c or "").lower())
                    normalized_names.append(compact_name_to_raw.get(ck, c))
                dedup = list(dict.fromkeys([str(x).strip() for x in normalized_names if str(x).strip()]))
                info["calling"] = "\n".join(dedup)
            else:
                info["calling"] = "N/A"
        hop2_called = _get_2hop_calls(fn_name) if fn_name else []
        hop2_callers = _get_2hop_callers(fn_name) if fn_name else []
        if hop2_called:
            info["called_indirect"] = hop2_called[:20]
        if hop2_callers:
            info["calling_indirect"] = hop2_callers[:20]
        if fn_name:
            function_details_by_name[fn_name] = info

    # ── 간접 Globals 추적: same-module direct/2-hop globals를 제한적으로 caller에 전파 ──
    if call_map and function_details_by_name:
        _indirect_propagated = 0
        for caller_name, callee_list in call_map.items():
            caller_info = function_details_by_name.get(caller_name.lower())
            if not isinstance(caller_info, dict):
                continue
            caller_gg = caller_info.get("globals_global") or []
            caller_gs = caller_info.get("globals_static") or []
            if not isinstance(caller_gg, list):
                caller_gg = []
            if not isinstance(caller_gs, list):
                caller_gs = []
            existing_gg_names = set()
            for g in caller_gg:
                gs = str(g or "").strip()
                vname = _entry_var_name(gs)
                if vname:
                    existing_gg_names.add(vname.lower())
            existing_gs_names = set()
            for g in caller_gs:
                gs = str(g or "").strip()
                vname = _entry_var_name(gs)
                if vname:
                    existing_gs_names.add(vname.lower())
            added = False
            for callee_name in callee_list:
                callee_info = function_details_by_name.get(callee_name.lower())
                if not isinstance(callee_info, dict):
                    continue
                if _module_name_for(caller_info) and _module_name_for(caller_info) != _module_name_for(callee_info):
                    continue
                for g in (callee_info.get("globals_global") or []):
                    gs = str(g or "").strip()
                    if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                        continue
                    var_name = _entry_var_name(gs)
                    if var_name.lower() not in existing_gg_names:
                        caller_gg.append(f"[INDIRECT] {var_name}")
                        existing_gg_names.add(var_name.lower())
                        added = True
                for g in (callee_info.get("globals_static") or []):
                    gs = str(g or "").strip()
                    if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                        continue
                    var_name = _entry_var_name(gs)
                    if var_name.lower() not in existing_gs_names:
                        caller_gs.append(f"[INDIRECT] {var_name}")
                        existing_gs_names.add(var_name.lower())
                        added = True
                for leaf_name in _call_edges(callee_name):
                    leaf_info = function_details_by_name.get(str(leaf_name).lower())
                    if not isinstance(leaf_info, dict):
                        continue
                    if not _should_propagate_2hop(caller_info, callee_info, leaf_info):
                        continue
                    for g in (leaf_info.get("globals_global") or []):
                        gs = str(g or "").strip()
                        if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                            continue
                        var_name = _entry_var_name(gs)
                        if var_name.lower() not in existing_gg_names:
                            caller_gg.append(f"[INDIRECT2] {var_name}")
                            existing_gg_names.add(var_name.lower())
                            added = True
                    for g in (leaf_info.get("globals_static") or []):
                        gs = str(g or "").strip()
                        if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                            continue
                        var_name = _entry_var_name(gs)
                        if var_name.lower() not in existing_gs_names:
                            caller_gs.append(f"[INDIRECT2] {var_name}")
                            existing_gs_names.add(var_name.lower())
                            added = True
            if added:
                caller_info["globals_global"] = caller_gg
                caller_info["globals_static"] = caller_gs
                _indirect_propagated += 1
        if _indirect_propagated > 0:
            _logger.info("Indirect globals propagation: %d caller functions updated", _indirect_propagated)
            for fid, info in function_details.items():
                if not isinstance(info, dict):
                    continue
                fname = str(info.get("name") or "").strip().lower()
                src = function_details_by_name.get(fname)
                if isinstance(src, dict):
                    for gk in ("globals_global", "globals_static"):
                        sv = src.get(gk)
                        if isinstance(sv, list) and sv:
                            info[gk] = list(sv)

    return {
        "overview": "\n".join(overview_lines),
        "requirements": "\n".join(requirements_lines),
        "interfaces": "\n".join(interfaces_lines),
        "uds_frames": "\n".join(frames_lines),
        "notes": "\n".join(notes_lines),
        "unit_structure": "\n".join(
            [
                f"Interfaces: {len(interfaces)}",
                f"Internals: {len(internals)}",
                f"Global data: {len(global_data)}",
            ]
        ),
        "global_data": "\n".join(global_data),
        "interface_functions": "\n".join(interfaces),
        "internal_functions": "\n".join(internals),
        "global_vars": global_vars,
        "static_vars": static_vars,
        "macro_defs": macro_defs,
        "calibration_params": calibration_params,
        "function_table_rows": function_table_rows,
        "function_details": function_details,
        "function_details_by_name": function_details_by_name,
        "call_map": call_map,
        "calling_map": calling_map,
        "module_map": module_map,
        "globals_info_map": globals_info_map,
        "common_macros": common_macros,
        "type_defs": type_defs,
        "param_defs": param_defs,
        "version_defs": version_defs,
        "software_unit_design": "\n".join(detail_lines).strip(),
        "did_function_map": did_function_map,
        "did_entries": did_entries,
        "service_entries": service_entries,
    }


def generate_uds_preview_markdown(uds_payload: Dict[str, Any]) -> str:
    payload = _safe_dict(uds_payload)
    summary = _safe_dict(payload.get("summary", {}))
    project = payload.get("project_name") or summary.get("project") or summary.get("project_name") or "UDS Spec"
    generated_at = payload.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    ai_sections = payload.get("ai_sections")
    overview = _apply_uds_rules(
        _merge_section_text(payload.get("overview", "") or "", ai_sections, "overview"),
        "overview",
    )
    requirements = _apply_uds_rules(
        _merge_section_text(payload.get("requirements", "") or "", ai_sections, "requirements"),
        "requirements",
    )
    interfaces = _apply_uds_rules(
        _merge_section_text(payload.get("interfaces", "") or "", ai_sections, "interfaces"),
        "interfaces",
    )
    uds_frames = _apply_uds_rules(
        _merge_section_text(payload.get("uds_frames", "") or "", ai_sections, "uds_frames"),
        "uds_frames",
    )
    notes_text = _merge_section_text(
        payload.get("notes", "") or "",
        ai_sections,
        "notes",
        append_base=True,
    )
    evidence_lines = _ai_evidence_lines(ai_sections)
    if evidence_lines:
        notes_text = "\n".join([notes_text, "Evidence:"] + evidence_lines).strip()
    notes = _apply_uds_rules(notes_text, "notes")
    software_unit_design = payload.get("software_unit_design", "") or ""

    detailed_doc = _ai_document_text(ai_sections)
    lines = [
        f"# {project}",
        "",
        f"- Job URL: {payload.get('job_url') or ''}",
        f"- Build: {payload.get('build_number') or ''}",
        f"- Generated at: {generated_at}",
        "",
        "## Overview",
        overview or "- N/A",
        "",
        "## Requirements",
        requirements or "- N/A",
        "",
        "## Interfaces",
        interfaces or "- N/A",
        "",
        "## UDS Frames",
        uds_frames or "- N/A",
        "",
        "## Notes",
        notes or "- N/A",
        "",
        "## Software Unit Design",
        software_unit_design or "- N/A",
        "",
    ]
    if detailed_doc:
        lines += ["## Detailed UDS", detailed_doc, ""]
    return "\n".join(lines).rstrip() + "\n"


def generate_uds_preview_html(uds_payload: Dict[str, Any]) -> str:
    payload = _safe_dict(uds_payload)
    summary = _safe_dict(payload.get("summary", {}))
    project = payload.get("project_name") or summary.get("project") or summary.get("project_name") or "UDS Spec"
    generated_at = payload.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    ai_sections = payload.get("ai_sections")
    overview = _apply_uds_rules(
        _merge_section_text(payload.get("overview", "") or "", ai_sections, "overview"),
        "overview",
    )
    requirements = _apply_uds_rules(
        _merge_section_text(payload.get("requirements", "") or "", ai_sections, "requirements"),
        "requirements",
    )
    interfaces = _apply_uds_rules(
        _merge_section_text(payload.get("interfaces", "") or "", ai_sections, "interfaces"),
        "interfaces",
    )
    uds_frames = _apply_uds_rules(
        _merge_section_text(payload.get("uds_frames", "") or "", ai_sections, "uds_frames"),
        "uds_frames",
    )
    notes_text = _merge_section_text(
        payload.get("notes", "") or "",
        ai_sections,
        "notes",
        append_base=True,
    )
    evidence_lines = _ai_evidence_lines(ai_sections)
    if evidence_lines:
        notes_text = "\n".join([notes_text, "Evidence:"] + evidence_lines).strip()
    notes = _apply_uds_rules(notes_text, "notes")
    software_unit_design = payload.get("software_unit_design", "") or ""

    project_html = escape(str(project))
    job_url_html = escape(str(payload.get("job_url") or ""))
    build_html = escape(str(payload.get("build_number") or ""))
    generated_html = escape(str(generated_at))

    logic_items = payload.get("logic_diagrams")
    logic_items = _merge_logic_ai_items(logic_items, ai_sections)
    logic_html = (
        _uds_logic_html(logic_items) if isinstance(logic_items, list) else "<p>N/A</p>"
    )
    detailed_doc = _ai_document_text(ai_sections)

    return "\n".join(
        [
            "<div class=\"uds-doc\">",
            f"<h2>{project_html}</h2>",
            "<ul>",
            f"<li><strong>Job URL:</strong> {job_url_html}</li>",
            f"<li><strong>Build:</strong> {build_html}</li>",
            f"<li><strong>Generated at:</strong> {generated_html}</li>",
            "</ul>",
            "<h3>Overview</h3>",
            _uds_lines_to_html(overview),
            "<h3>Requirements</h3>",
            _uds_lines_to_html(requirements),
            "<h3>Interfaces</h3>",
            _uds_lines_to_html(interfaces),
            "<h3>UDS Frames</h3>",
            _uds_lines_to_html(uds_frames),
            "<h3>Notes</h3>",
            _uds_lines_to_html(notes),
            "<h3>Detailed UDS</h3>",
            f"<pre>{escape(detailed_doc) if detailed_doc else 'N/A'}</pre>",
            "<h3>Logic Diagrams</h3>",
            logic_html,
            "<h3>Software Unit Design</h3>",
            "<pre>" + escape(software_unit_design or "N/A") + "</pre>",
            "</div>",
        ]
    )


def generate_uds_preview_html(uds_payload: Dict[str, Any]) -> str:
    payload = _safe_dict(uds_payload)
    summary = _safe_dict(payload.get("summary", {}))
    project = payload.get("project_name") or summary.get("project") or summary.get("project_name") or "UDS Spec"
    generated_at = payload.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    ai_sections = payload.get("ai_sections")
    overview = _apply_uds_rules(
        _merge_section_text(payload.get("overview", "") or "", ai_sections, "overview"),
        "overview",
    )
    requirements = _apply_uds_rules(
        _merge_section_text(payload.get("requirements", "") or "", ai_sections, "requirements"),
        "requirements",
    )
    interfaces = _apply_uds_rules(
        _merge_section_text(payload.get("interfaces", "") or "", ai_sections, "interfaces"),
        "interfaces",
    )
    uds_frames = _apply_uds_rules(
        _merge_section_text(payload.get("uds_frames", "") or "", ai_sections, "uds_frames"),
        "uds_frames",
    )
    notes_text = _merge_section_text(
        payload.get("notes", "") or "",
        ai_sections,
        "notes",
        append_base=True,
    )
    evidence_lines = _ai_evidence_lines(ai_sections)
    if evidence_lines:
        notes_text = "\n".join([notes_text, "Evidence:"] + evidence_lines).strip()
    notes = _apply_uds_rules(notes_text, "notes")
    detailed_doc = _ai_document_text(ai_sections)
    software_unit_design = payload.get("software_unit_design", "") or ""

    project_html = escape(str(project))
    job_url_html = escape(str(payload.get("job_url") or ""))
    build_html = escape(str(payload.get("build_number") or ""))
    generated_html = escape(str(generated_at))

    logic_items = payload.get("logic_diagrams")
    logic_items = _merge_logic_ai_items(logic_items, ai_sections)
    logic_html = (
        _uds_logic_html(logic_items) if isinstance(logic_items, list) else "<p>N/A</p>"
    )

    return "\n".join(
        [
            "<div class=\"uds-doc\">",
            f"<h2>{project_html}</h2>",
            "<ul>",
            f"<li><strong>Job URL:</strong> {job_url_html}</li>",
            f"<li><strong>Build:</strong> {build_html}</li>",
            f"<li><strong>Generated at:</strong> {generated_html}</li>",
            "</ul>",
            "<h3>Overview</h3>",
            _uds_lines_to_html(overview),
            "<h3>Requirements</h3>",
            _uds_lines_to_html(requirements),
            "<h3>Interfaces</h3>",
            _uds_lines_to_html(interfaces),
            "<h3>UDS Frames</h3>",
            _uds_lines_to_html(uds_frames),
            "<h3>Notes</h3>",
            _uds_lines_to_html(notes),
            "<h3>Detailed UDS</h3>",
            f"<pre>{escape(detailed_doc) if detailed_doc else 'N/A'}</pre>",
            "<h3>Logic Diagrams</h3>",
            logic_html,
            "<h3>Software Unit Design</h3>",
            "<pre>" + escape(software_unit_design or "N/A") + "</pre>",
            "</div>",
        ]
    )
