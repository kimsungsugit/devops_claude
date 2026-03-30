"""report_gen.requirements - Auto-split from report_generator.py"""
# Re-import common dependencies
import re
import os
import json
import csv
import logging
import time
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from report_gen.function_analyzer import _normalize_symbol_name
from report_gen.source_parser import (
    _scan_source_requirement_ids,
    _scan_source_function_names,
    _extract_comment_lines,
)
from report_gen.utils import (
    _normalize_swcom_label,
    _normalize_related_ids,
    _dedupe_multiline_text,
    _normalize_asil_value,
)

_logger = logging.getLogger("report_generator")

_REQ_ID_PAT = re.compile(r"\b(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)\b", re.I)

def _extract_requirements_from_comments(text: str) -> List[str]:
    results: List[str] = []
    for ln in _extract_comment_lines(text):
        m = re.search(r"(REQ|Requirement|요구사항)\s*[:\-]\s*(.+)", ln, flags=re.I)
        if m:
            results.append(m.group(2).strip())
    return results


def _extract_table_section(lines: List[str], header: str, stop_headers: List[str], max_rows: int) -> List[str]:
    header_idx = None
    for i, ln in enumerate(lines):
        if header.lower() in ln.lower():
            header_idx = i
            break
    if header_idx is None:
        return []
    rows: List[str] = []
    for ln in lines[header_idx + 1 :]:
        if not ln.strip():
            if rows:
                break
            continue
        if any(h.lower() in ln.lower() for h in stop_headers):
            break
        rows.append(ln.strip())
        if len(rows) >= max_rows:
            break
    return rows


def _normalize_table_row(row: str) -> List[str]:
    if not row:
        return []
    parts = re.split(r"\s{2,}|\t+", row.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_function_blocks(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.splitlines()]
    blocks: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    state = ""
    current_swcom = ""
    for ln in lines:
        line = ln.strip()
        if re.match(r"^SwCom_\d+\b", line):
            current_swcom = line
            continue
        m_header = re.search(r"\b(SwUFn_\d+)\s*:\s*(.+)$", line)
        if m_header:
            if current:
                blocks.append(current)
                current = {}
            current["header"] = line
            current["id"] = m_header.group(1).strip()
            current["name"] = m_header.group(2).strip()
            if current_swcom:
                current["swcom"] = current_swcom
            state = ""
            continue
        if re.search(r"\bSwUFn_\d+", line):
            if current:
                blocks.append(current)
                current = {}
            current["header"] = line
            if current_swcom:
                current["swcom"] = current_swcom
            state = ""
            continue
        if not current:
            continue
        if line.startswith("["):
            state = line.lower()
            continue
        if not line:
            continue
        if line.startswith("ID"):
            current["id"] = line.split(None, 1)[-1].strip()
        elif line.startswith("Name"):
            current["name"] = line.split(None, 1)[-1].strip()
        elif line.startswith("Prototype"):
            current["prototype"] = line.split(None, 1)[-1].strip()
        elif line.startswith("Description"):
            current["description"] = line.split(None, 1)[-1].strip()
        elif line.startswith("ASIL"):
            current["asil"] = line.split(None, 1)[-1].strip()
        elif line.startswith("Related ID"):
            current["related"] = line.split(None, 1)[-1].strip()
        elif line.startswith("Called Function"):
            current["called"] = line.split(None, 1)[-1].strip()
        elif line.startswith("Calling Function"):
            current["calling"] = line.split(None, 1)[-1].strip()
        elif line.startswith("사용 전역변수"):
            current["globals"] = line.split(None, 1)[-1].strip()
        elif line.startswith("선행조건"):
            current["precondition"] = line.split(None, 1)[-1].strip()
        elif "input param" in state:
            current.setdefault("inputs", []).append(line)
        elif "output param" in state:
            current.setdefault("outputs", []).append(line)
        elif "logic diagram" in state:
            current["logic"] = "present"
    if current:
        blocks.append(current)
    return blocks


def _docx_to_text(doc) -> str:
    lines: List[str] = []
    try:
        for p in doc.paragraphs:
            text = (p.text or "").strip()
            if text:
                lines.append(text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        text = (p.text or "").strip()
                        if text:
                            lines.append(text)
    except Exception:
        pass
    return "\n".join(lines)


def _extract_function_info_from_docx(doc) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}

    def _norm_label(raw: str) -> str:
        s = re.sub(r"\s+", " ", raw).strip().lower()
        s = re.sub(r"[\[\]()（）]", "", s).strip()
        return s

    def _is_param_header_row(cells: List[str]) -> bool:
        norms = [c.strip().lower() for c in cells]
        return "no" in norms and ("name" in norms or "type" in norms)

    def _parse_param_row(cells: List[str]) -> str:
        if len(cells) < 3:
            return ""
        no_val = cells[0].strip()
        if not no_val or not no_val[0].isdigit():
            return ""
        name = cells[1].strip() if len(cells) > 1 else ""
        ptype = cells[2].strip() if len(cells) > 2 else ""
        vrange = cells[3].strip() if len(cells) > 3 else ""
        reset = cells[4].strip() if len(cells) > 4 else ""
        desc = cells[5].strip() if len(cells) > 5 else ""
        if not name or name.upper() in {"N/A", "-", "NONE"}:
            return ""
        parts = [name]
        if ptype and ptype.upper() not in {"N/A", "-"}:
            parts[0] = f"{name} : {ptype}"
        if vrange and vrange.upper() not in {"N/A", "-"}:
            parts.append(f"range: {vrange}")
        if reset and reset.upper() not in {"N/A", "-"}:
            parts.append(f"reset: {reset}")
        entry = parts[0]
        if len(parts) > 1:
            entry += " (" + ", ".join(parts[1:]) + ")"
        return entry

    try:
        for table in doc.tables:
            if not table.rows:
                continue
            header = [c.text.strip() for c in table.rows[0].cells]
            if not header:
                continue
            header_joined = " ".join(header)
            if "Function Information" not in header_joined and "[ Function Information ]" not in header_joined:
                continue
            fn_id = ""
            if len(table.rows) > 1:
                for cell in table.rows[1].cells:
                    m = re.search(r"(SwUFn_\d+)", cell.text or "")
                    if m:
                        fn_id = m.group(1)
                        break
            if not fn_id:
                continue
            info: Dict[str, Any] = {"id": fn_id}
            last_label_norm = ""
            collecting_params = ""
            skip_next_header = False
            for row in table.rows[2:]:
                cells = [c.text.strip() for c in row.cells]
                if not cells:
                    continue
                label = cells[0].strip()
                label_norm = _norm_label(label) if label else ""

                # Extract value from non-label cells BEFORE any label checks
                # so that value is available when processing input/output parameter rows.
                values: List[str] = []
                value_seen: Set[str] = set()
                for cell in cells[1:]:
                    cval = str(cell or "").strip()
                    if not cval or cval == label:
                        continue
                    if cval in value_seen:
                        continue
                    value_seen.add(cval)
                    values.append(cval)
                value = "\n".join([v for v in values if v]).strip()
                if not value and values:
                    value = values[-1].strip()

                if skip_next_header and _is_param_header_row(cells):
                    skip_next_header = False
                    continue

                if collecting_params and label and label[0].isdigit():
                    entry = _parse_param_row(cells)
                    if entry:
                        key = "inputs" if collecting_params == "input" else "outputs"
                        direction = "[IN]" if collecting_params == "input" else "[OUT]"
                        info.setdefault(key, []).append(f"{direction} {entry}")
                    continue

                if label_norm in {"input parameters", "[ input parameters ]"}:
                    if value and value.upper() not in {"N/A", "TBD", "-", "NONE"}:
                        params = [ln.strip() for ln in value.splitlines() if ln.strip() and ln.strip().upper() not in {"N/A", "-"}]
                        if params:
                            for p in params:
                                info.setdefault("inputs", []).append(f"[IN] {p}" if not p.startswith("[") else p)
                    collecting_params = "input"
                    last_label_norm = "input parameters"
                    skip_next_header = True
                    continue
                if label_norm in {"output parameters", "[ output parameters ]"}:
                    if value and value.upper() not in {"N/A", "TBD", "-", "NONE"}:
                        params = [ln.strip() for ln in value.splitlines() if ln.strip() and ln.strip().upper() not in {"N/A", "-"}]
                        if params:
                            for p in params:
                                info.setdefault("outputs", []).append(f"[OUT] {p}" if not p.startswith("[") else p)
                    collecting_params = "output"
                    last_label_norm = "output parameters"
                    skip_next_header = True
                    continue

                if collecting_params and label_norm and not label[0].isdigit():
                    collecting_params = ""

                if not label_norm and last_label_norm and value:
                    if last_label_norm in {"description", "called function", "calling function"}:
                        prev = str(info.get({
                            "description": "description",
                            "called function": "called",
                            "calling function": "calling",
                        }.get(last_label_norm, ""), "") or "").strip()
                        joined = "\n".join([x for x in [prev, value] if x]).strip()
                        joined = _dedupe_multiline_text(joined)
                        if last_label_norm == "description":
                            info["description"] = joined
                            if joined.strip():
                                info["description_source"] = "reference"
                        elif last_label_norm == "called function":
                            info["called"] = joined
                        elif last_label_norm == "calling function":
                            info["calling"] = joined
                        continue
                    if last_label_norm in {
                        "used globals global", "used globals (global)", "used global variable global", "used global variableglobal", "used global variables global", "used global variablesglobal",
                        "used globals static", "used globals (static)", "used global variable static", "used global variablestatic", "used global variables static", "used global variablesstatic",
                        "사용 전역변수", "사용 전역 변수",
                    }:
                        key = "globals"
                        if "static" in last_label_norm:
                            key = "globals_static"
                        elif "global" in last_label_norm:
                            key = "globals_global"
                        prev_list = list(info.get(key) or [])
                        prev_list.extend([ln.strip() for ln in value.splitlines() if ln.strip()])
                        info[key] = prev_list
                        continue
                if not label_norm:
                    continue
                last_label_norm = label_norm
                if label_norm == "name":
                    info["name"] = _normalize_symbol_name(value)
                elif label_norm == "prototype":
                    info["prototype"] = value
                elif label_norm == "description":
                    info["description"] = _dedupe_multiline_text(value)
                    if value.strip():
                        info["description_source"] = "reference"
                elif label_norm == "asil":
                    info["asil"] = _normalize_asil_value(value)
                elif label_norm == "related id":
                    info["related"] = _normalize_related_ids(value)
                elif label_norm in {"precondition", "선행조건"}:
                    info["precondition"] = _dedupe_multiline_text(value, na_to_empty=True) or "N/A"
                elif label_norm == "called function":
                    info["called"] = value
                elif label_norm == "calling function":
                    info["calling"] = value
                elif label_norm in {"used globals global", "used globals (global)", "used global variable global", "used global variableglobal", "used global variables global", "used global variablesglobal"}:
                    info["globals_global"] = [ln.strip() for ln in value.splitlines() if ln.strip()]
                elif label_norm in {"used globals static", "used globals (static)", "used global variable static", "used global variablestatic", "used global variables static", "used global variablesstatic"}:
                    info["globals_static"] = [ln.strip() for ln in value.splitlines() if ln.strip()]
                elif label_norm in {"사용 전역변수", "사용 전역 변수"}:
                    all_vars = [ln.strip() for ln in value.splitlines() if ln.strip()]
                    info["globals"] = all_vars
                    from config import STATIC_VAR_PREFIXES, GLOBAL_VAR_PREFIXES
                    for var in all_vars:
                        v_stripped = var.split(",")[0].strip().split(":")[0].strip()
                        if any(v_stripped.startswith(p) for p in STATIC_VAR_PREFIXES):
                            info.setdefault("globals_static", []).append(var)
                        elif any(v_stripped.startswith(p) for p in GLOBAL_VAR_PREFIXES):
                            info.setdefault("globals_global", []).append(var)
                        else:
                            info.setdefault("globals_global", []).append(var)
                elif label_norm == "logic diagram":
                    info["logic"] = value
            result[fn_id] = info
    except Exception:
        return result
    return result


def _extract_sds_partition_map(doc_path: str) -> Dict[str, Dict[str, str]]:
    try:
        import docx  # type: ignore
    except Exception:
        return {}
    if not doc_path:
        return {}
    path = Path(doc_path)
    if not path.exists():
        return {}
    try:
        doc = docx.Document(str(path))
    except Exception:
        return {}
    mapping: Dict[str, Dict[str, str]] = {}

    def _collapse_adjacent_duplicates(values: List[str]) -> List[str]:
        result: List[str] = []
        for value in [str(v or "").strip() for v in values]:
            if not value:
                result.append("")
                continue
            if result and result[-1] == value:
                continue
            result.append(value)
        return result

    def _add_entry(name: str, asil: str, related: str, desc: str) -> None:
        key = str(name or "").strip().lower()
        if not key:
            return
        entry = mapping.get(key, {})
        if asil and not entry.get("asil"):
            entry["asil"] = asil
        if related and not entry.get("related"):
            entry["related"] = related
        if desc and not entry.get("description"):
            entry["description"] = desc
        mapping[key] = entry

    def _find_col(norm_headers: List[str], keywords: List[str]) -> int:
        for kw in keywords:
            for i, h in enumerate(norm_headers):
                if kw == h or kw in h:
                    return i
        return -1

    swcom_asil_map: Dict[str, str] = {}

    for table in doc.tables:
        if not table.rows:
            continue
        header = [c.text.strip() for c in table.rows[0].cells]
        header_norm = [h.lower() for h in header]
        header_joined = " ".join(header_norm)

        if "software component information" in header_joined:
            sc_data: Dict[str, str] = {}
            func_rows: List[Dict[str, str]] = []
            in_interface = False
            iface_header: List[str] = []
            for row in table.rows[1:]:
                cells = [c.text.strip() for c in row.cells]
                compact_cells = _collapse_adjacent_duplicates(cells)
                first = cells[0].lower() if cells else ""
                last_val = ""
                for c in reversed(cells):
                    cv = c.strip()
                    if cv and cv != cells[0].strip():
                        last_val = cv
                        break
                if not last_val:
                    last_val = cells[-1].strip() if cells else ""

                if first in {"sc id", "sc_id"}:
                    m = re.search(r"SwCom_\d+", last_val, re.I)
                    if m:
                        sc_data["id"] = m.group(0)
                elif first in {"sc name", "sc_name"}:
                    sc_data["name"] = last_val
                elif first in {"sc description", "sc_description"}:
                    sc_data["description"] = last_val[:500]
                elif first == "asil":
                    sc_data["asil"] = last_val
                elif first in {"related id", "related_id"}:
                    sc_data["related"] = last_val
                elif "sw component interface" in first or "component interface" in first:
                    in_interface = True
                    continue
                elif first == "no" and ("name" in " ".join(cells).lower()):
                    in_interface = True
                    iface_header = [c.lower() for c in compact_cells]
                    continue
                elif "software component design" in first or "component design" in first:
                    in_interface = False
                    continue

                if in_interface and first and first[0].isdigit():
                    fname = ""
                    fdesc = ""
                    name_idx = -1
                    desc_idx = -1
                    if iface_header:
                        for i, header_name in enumerate(iface_header):
                            h = str(header_name or "").strip().lower()
                            if name_idx < 0 and h == "name":
                                name_idx = i
                            if desc_idx < 0 and "description" in h:
                                desc_idx = i
                    if name_idx >= 0 and name_idx < len(compact_cells):
                        fname = compact_cells[name_idx].strip()
                    if desc_idx >= 0 and desc_idx < len(compact_cells):
                        fdesc = compact_cells[desc_idx].strip()
                    if not fname:
                        for cv in compact_cells[1:]:
                            token = cv.strip()
                            if token and not token[0].isdigit():
                                fname = token
                                break
                    if not fdesc:
                        for cv in reversed(compact_cells[1:]):
                            token = cv.strip()
                            if token and token != fname and not re.fullmatch(r"(?:static\s+)?(?:void|u8|u16|u32|u64|s8|s16|s32|s64|enum)(?:\s*\(\s*void\s*\))?", token, re.I):
                                fdesc = token
                                break
                    if fname:
                        func_rows.append({"name": fname, "desc": fdesc})

            sc_id = sc_data.get("id", "")
            sc_name = sc_data.get("name", "")
            sc_asil = sc_data.get("asil", "") or swcom_asil_map.get(sc_id.lower(), "")
            sc_related = sc_data.get("related", "")
            sc_desc = sc_data.get("description", "")
            if sc_id:
                _add_entry(sc_id, sc_asil, sc_related, sc_desc)
            if sc_name:
                _add_entry(sc_name, sc_asil, sc_related, sc_desc)
            for fr in func_rows:
                fn = fr["name"].rstrip("()").strip()
                _add_entry(fn, sc_asil, sc_related, fr.get("desc", ""))
            continue

        idx_comp_id = _find_col(header_norm, ["comp id", "component id", "swcom"])
        idx_comp_name = _find_col(header_norm, ["component name", "comp name"])
        idx_comp_asil = _find_col(header_norm, ["asil", "safety level", "safety"])
        if idx_comp_id >= 0 and idx_comp_name >= 0 and idx_comp_asil >= 0:
            for row in table.rows[1:]:
                cells = [c.text.strip() for c in row.cells]
                if idx_comp_id >= len(cells):
                    continue
                cid = cells[idx_comp_id]
                cname = cells[idx_comp_name] if idx_comp_name < len(cells) else ""
                casil = cells[idx_comp_asil] if idx_comp_asil < len(cells) else ""
                if cid and casil:
                    swcom_asil_map[cid.lower()] = casil
                    _add_entry(cid, casil, "", "")
                    if cname:
                        _add_entry(cname, casil, "", "")
            continue

        idx_name = _find_col(header_norm, [
            "partition name", "component name", "module name", "name",
            "function", "function name", "sw component", "swcom",
        ])
        idx_asil = _find_col(header_norm, [
            "asil", "safety level", "safety", "safety class", "integrity level",
        ])
        idx_rel = _find_col(header_norm, [
            "related id", "related", "requirement", "req id", "trace",
            "traceability", "parent id",
        ])
        idx_desc = _find_col(header_norm, [
            "description", "desc", "function description", "purpose",
        ])
        if idx_name < 0:
            attr_idx = next((idx for idx, col in enumerate(header_norm) if col.startswith("attribute")), -1)
            cont_idx = next((idx for idx, col in enumerate(header_norm) if col == "contents"), -1)
            if attr_idx >= 0 and cont_idx >= 0:
                block: Dict[str, str] = {}
                for row in table.rows[1:]:
                    cells = [c.text.strip() for c in row.cells]
                    if attr_idx < len(cells) and cont_idx < len(cells):
                        block[cells[attr_idx].lower()] = cells[cont_idx]
                bid = block.get("id", "")
                if bid and re.match(r"Sw\w+_\d+", bid):
                    _add_entry(
                        block.get("name", bid),
                        block.get("asil", ""),
                        block.get("related id", block.get("related", "")),
                        block.get("description", "")[:500],
                    )
                    _add_entry(
                        bid,
                        block.get("asil", ""),
                        block.get("related id", block.get("related", "")),
                        block.get("description", "")[:500],
                    )
            continue
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if idx_name >= len(cells):
                continue
            _add_entry(
                cells[idx_name],
                cells[idx_asil] if idx_asil >= 0 and idx_asil < len(cells) else "",
                cells[idx_rel] if idx_rel >= 0 and idx_rel < len(cells) else "",
                cells[idx_desc] if idx_desc >= 0 and idx_desc < len(cells) else "",
            )

    _asil_pat = re.compile(r"\bASIL[\s\-_]*([A-D](?:\s*\([A-D]\))?)\b|\bQM\b", re.I)
    _module_heading_pat = re.compile(
        r"^(?:\d+\.?\d*\.?\s+)?(?:Module|Component|Partition|Software\s+Unit|SwCom|SW\s*Component)\s*[:\-_]?\s*(.+)",
        re.I,
    )
    _swcom_pat = re.compile(r"\bSwCom[_\s-]*(\d+)\b", re.I)
    current_module = ""
    current_asil = ""
    desc_buffer: List[str] = []
    for para in doc.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue
        heading_m = _module_heading_pat.match(txt)
        swcom_m = _swcom_pat.search(txt)
        is_heading = hasattr(para, "style") and para.style and "heading" in str(para.style.name or "").lower()
        if heading_m or is_heading or swcom_m:
            if current_module and desc_buffer:
                _add_entry(current_module, "", "", " ".join(desc_buffer).strip())
                desc_buffer = []
            candidate = heading_m.group(1).strip() if heading_m else txt
            candidate = re.sub(r"^\d+\.?\d*\.?\s*", "", candidate).strip()
            if candidate:
                current_module = candidate
                current_asil = ""
            continue
        if current_module:
            asil_m = _asil_pat.search(txt)
            if asil_m:
                asil_val = "QM" if asil_m.group(0).strip().upper().startswith("QM") else asil_m.group(1)[0].upper()
                _add_entry(current_module, asil_val, "", "")
                current_asil = asil_val
            req_ids = re.findall(r"\b(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)\b", txt)
            if req_ids:
                _add_entry(current_module, "", ", ".join(req_ids), "")
            if not asil_m and not req_ids and len(txt) > 10 and not txt.startswith(("Table", "Figure")):
                desc_buffer.append(txt)
    if current_module and desc_buffer:
        _add_entry(current_module, "", "", " ".join(desc_buffer).strip()[:500])

    return mapping


def _load_component_map() -> Dict[str, Dict[str, str]]:
    try:
        path = Path(__file__).resolve().parent / "docs" / "component_map.json"
    except Exception:
        return {}
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    mapping: Dict[str, Dict[str, str]] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        file_name = str(row.get("file") or "").strip()
        component = str(row.get("component") or "").strip()
        verify = str(row.get("verify") or "").strip().upper()
        structure = str(row.get("structure") or "").strip()
        if not file_name or not component:
            continue
        component = _normalize_swcom_label(component)
        mapping[file_name] = {
            "component": component,
            "verify": verify,
            "structure": structure,
        }
        mapping[Path(file_name).stem] = {
            "component": component,
            "verify": verify,
            "structure": structure,
        }
    return mapping


def _build_req_map_from_texts(texts: List[str]) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for txt in texts:
        for block in _extract_requirement_blocks(txt):
            name = str(block.get("name") or "").strip()
            rid = str(block.get("id") or "").strip()
            asil = str(block.get("asil") or "").strip()
            related = str(block.get("related_ids") or block.get("related") or "").strip()
            if name:
                mapping[name.lower()] = {"asil": asil, "related": related or rid}
            if rid:
                mapping[rid.lower()] = {"asil": asil, "related": related or rid}
        current_id = ""
        for raw in txt.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = re.search(r"\b(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)\b", line)
            if m:
                current_id = m.group(1)
            asil_match = re.search(
                r"\bASIL\b(?:\s*[:|\-]\s*|\s+)?((?:ASIL-)?(?:A|B|C|D)|QM)\b",
                line,
                re.I,
            )
            if m and asil_match:
                mapping[m.group(1).lower()] = {
                    "asil": _normalize_asil_value(asil_match.group(1)),
                    "related": mapping.get(m.group(1).lower(), {}).get("related", m.group(1)),
                }
            if current_id and line.lower().startswith("related id"):
                related_val = line.split(None, 2)[-1].strip() if " " in line else ""
                mapping[current_id.lower()] = {
                    "asil": mapping.get(current_id.lower(), {}).get("asil", ""),
                    "related": related_val,
                }
            if current_id and asil_match and not m:
                mapping[current_id.lower()] = {
                    "asil": _normalize_asil_value(asil_match.group(1)),
                    "related": mapping.get(current_id.lower(), {}).get("related", current_id),
                }
    return mapping


def _build_req_map_from_doc_paths(doc_paths: List[str], texts: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}

    def _merge_entry(key: str, asil: str = "", related: str = "") -> None:
        norm_key = str(key or "").strip().lower()
        if not norm_key:
            return
        entry = mapping.get(norm_key, {})
        asil_norm = _normalize_asil_value(asil)
        related_norm = _normalize_related_ids(related)
        if asil_norm and not entry.get("asil"):
            entry["asil"] = asil_norm
        if related_norm and not entry.get("related"):
            entry["related"] = related_norm
        mapping[norm_key] = entry

    def _is_req_id(value: str) -> bool:
        return bool(re.match(r"^Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+$", str(value or "").strip(), re.I))

    def _table_rows(table: Any) -> List[List[str]]:
        rows: List[List[str]] = []
        for row in table.rows:
            cells: List[str] = []
            for cell in row.cells:
                parts = [p.text.strip() for p in cell.paragraphs if (p.text or "").strip()]
                cell_text = "\n".join(parts).strip() if parts else (cell.text or "").strip()
                cells.append(cell_text)
            rows.append(cells)
        return rows

    try:
        import docx  # type: ignore
    except Exception:
        docx = None  # type: ignore

    if docx:
        for raw_path in doc_paths or []:
            path = Path(str(raw_path or "").strip())
            if not path.exists() or path.suffix.lower() != ".docx":
                continue
            try:
                doc = docx.Document(str(path))
            except Exception:
                continue

            for table in doc.tables:
                rows = _table_rows(table)
                if not rows:
                    continue
                header = [str(c or "").strip().lower() for c in rows[0]]

                attr_idx = next((idx for idx, col in enumerate(header) if col.startswith("attribute")), -1)
                cont_idx = next((idx for idx, col in enumerate(header) if col == "contents"), -1)
                if attr_idx >= 0 and cont_idx >= 0:
                    block: Dict[str, str] = {}
                    for row in rows[1:]:
                        if attr_idx >= len(row) or cont_idx >= len(row):
                            continue
                        label = str(row[attr_idx] or "").strip().lower()
                        value = str(row[cont_idx] or "").strip()
                        if label and value:
                            block[label] = value
                    rid = str(block.get("id") or "").strip()
                    if _is_req_id(rid):
                        asil = block.get("asil", "")
                        related = block.get("related id", block.get("related", rid))
                        _merge_entry(rid, asil, related)
                        name = str(block.get("name") or "").strip()
                        if name:
                            _merge_entry(name, asil, related)
                    continue

                header_joined = " ".join(header)
                if not header_joined:
                    continue

                id_idx = -1
                for idx, col in enumerate(header):
                    if col == "id" or col.endswith(" id"):
                        id_idx = idx
                        break
                asil_idx = next((idx for idx, col in enumerate(header) if col == "asil" or "asil" in col), -1)
                related_idx = next(
                    (
                        idx for idx, col in enumerate(header)
                        if col in {"related id", "related", "parent id", "traceability", "trace"}
                        or "related id" in col
                    ),
                    -1,
                )
                name_idx = next((idx for idx, col in enumerate(header) if col == "name" or col.endswith(" name")), -1)
                if id_idx < 0:
                    continue
                for row in rows[1:]:
                    if id_idx >= len(row):
                        continue
                    rid = str(row[id_idx] or "").strip()
                    if not _is_req_id(rid):
                        continue
                    asil = row[asil_idx] if asil_idx >= 0 and asil_idx < len(row) else ""
                    related = row[related_idx] if related_idx >= 0 and related_idx < len(row) else rid
                    _merge_entry(rid, asil, related)
                    if name_idx >= 0 and name_idx < len(row):
                        name = str(row[name_idx] or "").strip()
                        if name:
                            _merge_entry(name, asil, related)

    text_map = _build_req_map_from_texts(texts or [])
    for key, value in text_map.items():
        if key not in mapping:
            mapping[key] = dict(value)
            continue
        if value.get("asil") and not mapping[key].get("asil"):
            mapping[key]["asil"] = value["asil"]
        if value.get("related") and not mapping[key].get("related"):
            mapping[key]["related"] = value["related"]
    return mapping


def enrich_function_details_with_docs(
    function_details: Dict[str, Dict[str, Any]],
    function_table_rows: Optional[List[List[Any]]] = None,
    *,
    req_doc_paths: Optional[List[str]] = None,
    sds_doc_paths: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(function_details, dict) or not function_details:
        return function_details

    req_paths = [str(p).strip() for p in (req_doc_paths or []) if str(p).strip()]
    sds_paths = [str(p).strip() for p in (sds_doc_paths or []) if str(p).strip()]
    req_map = _build_req_map_from_doc_paths(req_paths) if req_paths else {}

    sds_map: Dict[str, Dict[str, str]] = {}
    for path in sds_paths:
        for key, value in _extract_sds_partition_map(path).items():
            if key not in sds_map:
                sds_map[key] = dict(value)
                continue
            for field in ("asil", "related", "description"):
                if value.get(field) and not sds_map[key].get(field):
                    sds_map[key][field] = value[field]

    fid_to_swcom: Dict[str, str] = {}
    if isinstance(function_table_rows, list):
        for row in function_table_rows:
            if not isinstance(row, list) or len(row) < 4:
                continue
            swcom = str(row[0] or "").strip()
            fid = str(row[2] or "").strip()
            if swcom and fid:
                fid_to_swcom[fid] = swcom

    def _normalize_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

    def _extract_related_ids(value: str) -> Set[str]:
        return {m.group(1).upper() for m in _REQ_ID_PAT.finditer(str(value or ""))}

    def _tokenize_text(value: str) -> List[str]:
        words = re.split(r"[^a-z0-9]+", str(value or "").lower())
        return [w for w in words if len(w) >= 3]

    def _prototype_candidates(info: Dict[str, Any]) -> List[str]:
        prototype = str(info.get("prototype") or "").strip()
        if not prototype:
            return []
        parts: List[str] = [prototype]
        m = re.match(r"^\s*([A-Za-z_]\w*(?:\s*\*+)?)\s+([A-Za-z_]\w*)\s*\((.*)\)\s*$", prototype)
        if m:
            ret_type = m.group(1).strip()
            fn_name = m.group(2).strip()
            params = m.group(3).strip()
            parts.extend([ret_type, fn_name])
            if params and params.lower() != "void":
                for chunk in params.split(","):
                    token = str(chunk).strip()
                    if token:
                        parts.append(token)
        return [p for p in parts if p]

    def _module_candidates(info: Dict[str, Any], fid: str) -> List[str]:
        candidates: List[str] = []
        func_name = str(info.get("name") or "").strip()
        if func_name:
            candidates.append(func_name)
            stripped = re.sub(r"^[gs]_", "", func_name, flags=re.I)
            if stripped != func_name:
                candidates.append(stripped)
            words = re.sub(r"([a-z])([A-Z])", r"\1 \2", stripped.replace("_", " "))
            words = re.sub(r"\bctrl\b", "control", words, flags=re.I)
            words = re.sub(r"\bdiag\b", "diagnostic", words, flags=re.I)
            if words.strip():
                candidates.append(words)
        module_name = str(info.get("module_name") or "").strip()
        if module_name:
            candidates.append(module_name)
            base = re.sub(r"_pds$", "", module_name, flags=re.I)
            candidates.append(base)
            tokenized = re.sub(r"([a-z])([A-Z])", r"\1 \2", base.replace("_", " "))
            tokenized = re.sub(r"\bctrl\b", "control", tokenized, flags=re.I)
            tokenized = re.sub(r"\bdiag\b", "diagnostic", tokenized, flags=re.I)
            tokenized = re.sub(r"\bprev(?:ious)?\b", "previous", tokenized, flags=re.I)
            words = [w for w in tokenized.split() if w.lower() not in {"ap", "drv", "sys", "pds", "main", "func"}]
            if words:
                candidates.append(" ".join(words))
        swcom = fid_to_swcom.get(fid, "")
        if swcom:
            candidates.append(swcom)
        return [c for c in dict.fromkeys([c.strip() for c in candidates if c and c.strip()])]

    def _find_sds_info(info: Dict[str, Any], fid: str) -> Tuple[Optional[str], Optional[Dict[str, str]], str]:
        candidates = _module_candidates(info, fid)
        swcom_direct_fallback: Tuple[Optional[str], Optional[Dict[str, str]], str] = (None, None, "")
        for candidate in candidates:
            direct = sds_map.get(candidate.lower())
            if direct:
                if candidate.lower().startswith("swcom_"):
                    swcom_direct_fallback = (candidate.lower(), direct, "direct")
                    continue
                return candidate.lower(), direct, "direct"

        norm_candidates = [_normalize_key(c) for c in candidates]
        for candidate, nc in zip(candidates, norm_candidates):
            if not nc:
                continue
            for key, value in sds_map.items():
                nk = _normalize_key(key)
                if nk and nc == nk:
                    if str(key).lower().startswith("swcom_"):
                        swcom_direct_fallback = (key, value, "normalized_exact")
                        continue
                    return key, value, "normalized_exact"

        related_ids = _extract_related_ids(str(info.get("related") or info.get("comment_related") or ""))
        proto_texts = _prototype_candidates(info)
        proto_tokens: Set[str] = set()
        for text in proto_texts + candidates:
            proto_tokens.update(_tokenize_text(text))
        best_key: Optional[str] = None
        best_value: Optional[Dict[str, str]] = None
        best_score = 0
        for key, value in sds_map.items():
            if str(key or "").lower().startswith("swcom_"):
                continue
            score = 0
            sds_related_ids = _extract_related_ids(str(value.get("related") or ""))
            overlap = related_ids & sds_related_ids
            if overlap:
                score += len(overlap) * 10
            sds_tokens = set(_tokenize_text(key))
            sds_tokens.update(_tokenize_text(str(value.get("description") or "")))
            token_overlap = proto_tokens & sds_tokens
            if token_overlap:
                score += min(len(token_overlap), 6) * 2
            if score > best_score and (overlap or len(token_overlap) >= 2):
                best_key = key
                best_value = value
                best_score = score
        if best_key and best_value:
            return best_key, best_value, "related_prototype"

        # Containment matching is intentionally strict to avoid generic terms
        # like "Lib" or "Main" matching unrelated SDS rows.
        for candidate, nc in zip(candidates, norm_candidates):
            if len(nc) < 6:
                continue
            cand_words = [w for w in re.split(r"[^a-z0-9]+", candidate.lower()) if len(w) >= 4]
            if not cand_words:
                continue
            for key, value in sds_map.items():
                nk = _normalize_key(key)
                if len(nk) < 6:
                    continue
                key_words = [w for w in re.split(r"[^a-z0-9]+", key.lower()) if len(w) >= 4]
                if not key_words:
                    continue
                if nc in nk or nk in nc:
                    overlap = set(cand_words) & set(key_words)
                    if overlap:
                        return key, value, "normalized_overlap"
        if swcom_direct_fallback[0] and swcom_direct_fallback[1]:
            return swcom_direct_fallback
        return None, None, ""

    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        sds_key, sds_info, sds_match_mode = _find_sds_info(info, str(fid))
        if sds_info:
            sds_scope = "swcom" if str(sds_key or "").lower().startswith("swcom_") else "function"
            if sds_scope == "swcom":
                mapping_confidence = 0.55
            elif sds_match_mode == "direct":
                mapping_confidence = 0.95
            elif sds_match_mode == "normalized_exact":
                mapping_confidence = 0.85
            elif sds_match_mode == "related_prototype":
                mapping_confidence = 0.8
            else:
                mapping_confidence = 0.7
            info["sds_match_key"] = sds_key or ""
            info["sds_match_mode"] = sds_match_mode
            info["sds_match_scope"] = sds_scope
            info["mapping_confidence"] = mapping_confidence
            current_related = str(info.get("related") or "").strip()
            current_asil = str(info.get("asil") or "").strip().upper()
            if (not current_related) or current_related in {"TBD", "N/A", "-"}:
                if sds_info.get("related"):
                    info["related"] = sds_info["related"]
                    info["related_source"] = "sds"
            if (not current_asil) or current_asil in {"TBD", "N/A", "-"}:
                if sds_info.get("asil"):
                    info["asil"] = _normalize_asil_value(sds_info["asil"])
                    info["asil_source"] = "sds"
            desc = str(info.get("description") or "").strip()
            if (not desc or desc.lower().startswith("function")) and sds_info.get("description"):
                info["description"] = sds_info["description"]
                info["description_source"] = "sds"
            elif str(info.get("description_source") or "").strip() in {"", "inference"}:
                info["description_source"] = "sds_match"

        related = str(info.get("related") or "").strip()
        matched_req_with_asil = False
        matched_req_without_asil = False
        if related and req_map:
            for match in _REQ_ID_PAT.finditer(related):
                req = req_map.get(match.group(1).lower())
                if not isinstance(req, dict):
                    continue
                req_asil_raw = str(req.get("asil") or "").strip()
                if req_asil_raw:
                    matched_req_with_asil = True
                else:
                    matched_req_without_asil = True
                asil = _normalize_asil_value(req.get("asil", ""))
                cur_asil = str(info.get("asil") or "").strip().upper()
                if asil and ((not cur_asil) or cur_asil in {"TBD", "N/A", "-"}):
                    info["asil"] = asil
                    info["asil_source"] = "srs"
                    break
        cur_asil = str(info.get("asil") or "").strip().upper()
        if (
            related
            and matched_req_without_asil
            and not matched_req_with_asil
            and ((not cur_asil) or cur_asil in {"TBD", "N/A", "-"})
        ):
            info["asil"] = "QM"
            info["asil_source"] = "srs_default_qm"

    return function_details


def _split_doc_function_blocks(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    blocks: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for ln in text.splitlines():
        line = ln.strip()
        m = re.match(r"^(SwUFn_\d+)\s*:\s*(.+)$", line)
        if m:
            if current:
                blocks.append(current)
            current = {"id": m.group(1), "title": f"{m.group(1)}: {m.group(2).strip()}", "lines": []}
            continue
        if current:
            current["lines"].append(line)
    if current:
        blocks.append(current)
    return blocks


def _collect_section_lines(lines: List[str], header: str) -> List[str]:
    results: List[str] = []
    collecting = False
    for ln in lines:
        line = ln.strip()
        if not line:
            if collecting and results:
                continue
        if line.startswith(header):
            collecting = True
            tail = line[len(header) :].strip()
            if tail:
                results.append(tail)
            continue
        if collecting:
            if (
                line.startswith("[")
                or line.startswith("ID")
                or line.startswith("Name")
                or line.startswith("Prototype")
                or line.startswith("Description")
                or line.startswith("ASIL")
                or line.startswith("Related ID")
                or line.startswith("선행조건")
                or line.startswith("사용 전역변수")
                or line.startswith("Called Function")
                or line.startswith("Calling Function")
            ):
                collecting = False
                continue
            if re.match(r"^SwUFn_\d+", line):
                collecting = False
                continue
            if line:
                results.append(line)
    return results


def _extract_state_tokens(lines: List[str]) -> List[str]:
    states: List[str] = []
    for ln in lines:
        for token in re.findall(r"\bST_[A-Za-z0-9_]+\b", ln):
            if token not in states:
                states.append(token)
    return states


def _extract_requirements_from_doc(text: str) -> List[str]:
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.splitlines()]
    blocks: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    collecting_desc = False
    desc_lines: List[str] = []
    stop_keys = {
        "Rationale",
        "Priority",
        "Status",
        "Risk",
        "Reuse",
        "Verification criteria",
        "System State",
        "Software State",
        "Type",
    }

    def _flush() -> None:
        nonlocal current, desc_lines, collecting_desc
        if not current:
            return
        if desc_lines:
            current["description"] = " ".join(desc_lines).strip()
        blocks.append(current)
        current = {}
        desc_lines = []
        collecting_desc = False

    for raw in lines:
        line = raw.strip()
        if not line:
            if collecting_desc:
                collecting_desc = False
            continue

        m = re.search(r"\b(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)\b", line)
        if line.startswith("ID") and m:
            _flush()
            current = {"id": m.group(1)}
            continue
        if re.match(r"^Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+[:\s]", line):
            _flush()
            current = {"id": m.group(1) if m else line.split()[0]}
            if ":" in line:
                current["name"] = line.split(":", 1)[1].strip()
            continue

        if not current:
            continue

        if line.startswith("Name"):
            current["name"] = line.split(None, 1)[-1].strip()
            continue
        if line.startswith("Description"):
            desc = line.split(None, 1)[-1].strip()
            if desc and desc != "Description":
                desc_lines.append(desc)
            collecting_desc = True
            continue
        asil_line_match = re.match(
            r"^(?:ASIL|Safety\s*Level|Safety\s*Class|Integrity\s*Level)[\s\-_:]*(.*)$",
            line, re.I,
        )
        if asil_line_match:
            collecting_desc = False
            asil_val = asil_line_match.group(1).strip()
            if not asil_val:
                asil_val = line.split(None, 1)[-1].strip() if len(line.split(None, 1)) > 1 else ""
            if asil_val:
                norm = re.match(r"(?:ASIL[\s\-_]*)?([A-D])\s*(?:\([A-D]\))?|QM", asil_val, re.I)
                current["asil"] = norm.group(0).strip() if norm else asil_val
            continue
        related_match = re.match(r"^(?:Related\s*ID|Related\s*Req|Trace(?:ability)?|Parent\s*ID)[\s:]*(.*)$", line, re.I)
        if related_match:
            collecting_desc = False
            related_val = related_match.group(1).strip().lstrip(":").strip()
            if related_val:
                current["related_id"] = related_val
            continue
        if any(line.startswith(k) for k in stop_keys):
            collecting_desc = False
            continue
        if collecting_desc:
            desc_lines.append(line)

    _flush()
    results: List[str] = []
    for block in blocks:
        rid = block.get("id") or ""
        name = block.get("name") or ""
        desc = block.get("description") or ""
        asil = block.get("asil") or ""
        related = block.get("related_id") or ""
        parts = []
        if rid:
            parts.append(rid)
        if name:
            parts.append(name)
        if desc:
            parts.append(f"- {desc}")
        if asil:
            parts.append(f"[ASIL:{asil}]")
        if related:
            parts.append(f"[Related:{related}]")
        if parts:
            results.append(" ".join(parts))
    return results


def _extract_requirements_fallback(text: str, max_items: int = 200) -> List[str]:
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits: List[str] = []
    req_keywords = re.compile(
        r"\b(shall|must|should|requirement|requirements|specification|spec)\b",
        re.I,
    )
    ko_keywords = re.compile(r"(요구|요건|필수|해야|기능|명세)")
    id_keywords = re.compile(r"\b(REQ|SRS|SDS|SR|SWR|SYS|SW)-?\d+\b", re.I)
    for ln in lines:
        if req_keywords.search(ln) or ko_keywords.search(ln) or id_keywords.search(ln):
            hits.append(ln)
            if len(hits) >= max_items:
                break
    return hits


def _extract_doc_section(text: str, title: str) -> str:
    if not text or not title:
        return ""
    title_clean = re.escape(title.strip())
    pattern = re.compile(rf"^\s*\d+(?:\.\d+)*\s+{title_clean}\s*$", re.I)
    lines = text.splitlines()
    start = None
    for idx, ln in enumerate(lines):
        if pattern.match(ln.strip()):
            start = idx + 1
            break
    if start is None:
        return ""
    collected: List[str] = []
    for ln in lines[start:]:
        if re.match(r"^\s*\d+(?:\.\d+)*\s+\S+", ln.strip()):
            break
        if ln.strip():
            collected.append(ln.rstrip())
    return "\n".join(collected).strip()


def _extract_requirement_blocks(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.splitlines()]
    blocks: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    collecting_desc = False
    desc_lines: List[str] = []
    stop_keys = {
        "Rationale",
        "Priority",
        "Status",
        "Risk",
        "Reuse",
        "Related ID",
        "Verification criteria",
        "ASIL",
        "System State",
        "Software State",
        "Type",
    }

    def _flush() -> None:
        nonlocal current, desc_lines, collecting_desc
        if not current:
            return
        if desc_lines:
            current["description"] = " ".join(desc_lines).strip()
        blocks.append(current)
        current = {}
        desc_lines = []
        collecting_desc = False

    id_re = re.compile(r"\b(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)\b")
    for raw in lines:
        line = raw.strip()
        if not line:
            if collecting_desc:
                collecting_desc = False
            continue

        m = id_re.search(line)
        if line.startswith("ID") and m:
            _flush()
            current = {"id": m.group(1)}
            continue
        if re.match(r"^Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+[:\s]", line):
            _flush()
            current = {"id": m.group(1) if m else line.split()[0]}
            if ":" in line:
                current["name"] = line.split(":", 1)[1].strip()
            continue

        if not current:
            continue

        if line.startswith("Name"):
            current["name"] = line.split(None, 1)[-1].strip()
            continue
        if line.startswith("Description"):
            desc = line.split(None, 1)[-1].strip()
            if desc and desc != "Description":
                desc_lines.append(desc)
            collecting_desc = True
            continue
        if line.startswith("Related ID"):
            current["related_ids"] = line.split(None, 1)[-1].strip()
            continue
        if any(line.startswith(k) for k in stop_keys):
            collecting_desc = False
            continue
        if collecting_desc:
            desc_lines.append(line)

    _flush()
    return blocks


def generate_uds_requirements_preview(texts: List[str]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for txt in texts:
        items.extend(_extract_requirement_blocks(txt))
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for item in items:
        key = (item.get("id") or "", item.get("name") or "", item.get("description") or "")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    counts: Dict[str, int] = {}
    for item in uniq:
        rid = str(item.get("id") or "")
        m = re.match(r"^(Sw[A-Za-z]+)_\d+", rid)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return {"items": uniq, "counts": counts}


def generate_uds_requirements_mapping(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mappings: List[Dict[str, Any]] = []
    for item in items:
        rid = str(item.get("id") or "")
        if rid and not (rid.startswith("SwTR_") or rid.startswith("SwTSR_")):
            continue
        related = str(item.get("related_ids") or "")
        swcom = re.findall(r"\bSwCom_\d+\b", related)
        swfn = re.findall(r"\bSwFn_\d+\b", related)
        if not swcom and not swfn:
            continue
        mappings.append(
            {
                "requirement_id": rid,
                "requirement_name": item.get("name") or "",
                "related_swcom": swcom,
                "related_swfn": swfn,
            }
        )
    return mappings


def _extract_doc_function_names(texts: List[str]) -> List[str]:
    names: set[str] = set()
    for txt in texts:
        if not txt:
            continue
        for name in re.findall(r"\b[gs]_[A-Za-z0-9_]+\b", txt):
            names.add(name)
    return sorted(names)


def generate_uds_function_mapping(texts: List[str], source_root: str) -> Dict[str, Any]:
    doc_funcs = _extract_doc_function_names(texts)
    source_info = _scan_source_function_names(source_root)
    source_funcs = set(source_info.get("names") or [])
    matched = [fn for fn in doc_funcs if fn in source_funcs]
    missing = [fn for fn in doc_funcs if fn not in source_funcs]

    fuzzy_matched: List[Dict[str, str]] = []
    still_missing: List[str] = []
    source_lower_map = {s.lower(): s for s in source_funcs}
    for fn in missing:
        fn_lower = fn.lower()
        if fn_lower in source_lower_map:
            fuzzy_matched.append({"doc": fn, "source": source_lower_map[fn_lower], "method": "case_insensitive"})
            continue
        fn_stripped = re.sub(r"^(g_|s_|static\s+)", "", fn)
        found = False
        for sfn in source_funcs:
            sfn_stripped = re.sub(r"^(g_|s_|static\s+)", "", sfn)
            if fn_stripped and sfn_stripped and fn_stripped.lower() == sfn_stripped.lower():
                fuzzy_matched.append({"doc": fn, "source": sfn, "method": "prefix_stripped"})
                found = True
                break
        if not found:
            still_missing.append(fn)

    return {
        "doc_functions": doc_funcs,
        "matched": matched,
        "fuzzy_matched": fuzzy_matched,
        "missing": still_missing,
        "source_scanned": int(source_info.get("scanned") or 0),
    }


def _normalize_trace_mapping_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rid = str(entry.get("requirement_id") or entry.get("requirement") or entry.get("req_id") or "").strip()
    if not rid:
        return None
    raw_sources = (
        entry.get("source_ids")
        or entry.get("source_id")
        or entry.get("source")
        or entry.get("sources")
        or []
    )
    source_ids: List[str] = []
    if isinstance(raw_sources, str):
        source_ids = [s.strip() for s in raw_sources.split(",") if s.strip()]
    elif isinstance(raw_sources, list):
        source_ids = [str(s).strip() for s in raw_sources if str(s).strip()]
    else:
        source_ids = [str(raw_sources).strip()] if str(raw_sources).strip() else []
    if not source_ids:
        return None
    return {"requirement_id": rid, "source_ids": source_ids}


def _parse_traceability_json(text: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except Exception:
        return []
    items: List[Dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("mappings"), list):
        data = data.get("mappings")
    if isinstance(data, list):
        for raw in data:
            if not isinstance(raw, dict):
                continue
            item = _normalize_trace_mapping_entry(raw)
            if item:
                items.append(item)
        return items
    if isinstance(data, dict):
        for rid, src in data.items():
            item = _normalize_trace_mapping_entry({"requirement_id": rid, "source_ids": src})
            if item:
                items.append(item)
    return items


def _parse_traceability_csv(text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        reader = csv.DictReader(StringIO(text))
    except Exception:
        return []
    if not reader.fieldnames:
        return []
    for row in reader:
        if not isinstance(row, dict):
            continue
        item = _normalize_trace_mapping_entry(row)
        if item:
            items.append(item)
    return items


def _parse_traceability_text(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    trimmed = text.strip()
    if not trimmed:
        return []
    if trimmed.startswith("{") or trimmed.startswith("["):
        items = _parse_traceability_json(trimmed)
        if items:
            return items
    return _parse_traceability_csv(trimmed)


def generate_uds_traceability_mapping(
    items: List[Dict[str, Any]],
    mapping_texts: List[str],
    function_details: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    req_ids = sorted({str(x.get("id") or "").strip() for x in items if str(x.get("id") or "").strip()})
    mappings: Dict[str, List[str]] = {}
    for text in mapping_texts:
        for entry in _parse_traceability_text(text):
            rid = entry["requirement_id"]
            srcs = entry["source_ids"]
            if rid not in mappings:
                mappings[rid] = []
            for src in srcs:
                if src not in mappings[rid]:
                    mappings[rid].append(src)
    if function_details:
        for fid, info in function_details.items():
            related = str(info.get("comment_related") or info.get("related") or "").strip()
            fn_name = str(info.get("name") or "").strip()
            if related and related.upper() not in {"TBD", "N/A", "-"}:
                for rid in re.findall(r"Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK|Com)_\d+", related):
                    src_label = fn_name or fid
                    mappings.setdefault(rid, [])
                    if src_label not in mappings[rid]:
                        mappings[rid].append(src_label)
    req_id_set = set(req_ids)
    if req_ids:
        req_lower_map = {r.lower(): r for r in req_ids}
        for rid_key in list(mappings.keys()):
            if rid_key not in req_id_set:
                canonical = req_lower_map.get(rid_key.lower())
                if canonical:
                    mappings.setdefault(canonical, []).extend(mappings.pop(rid_key))
    mapped_req_ids = [rid for rid in req_ids if rid in mappings]
    missing_req_ids = [rid for rid in req_ids if rid not in mappings]
    extra_mapping = [rid for rid in mappings.keys() if rid not in req_id_set]
    source_ids: List[str] = []
    for srcs in mappings.values():
        for src in srcs:
            if src not in source_ids:
                source_ids.append(src)
    mapping_pairs = [
        {"requirement_id": rid, "source_ids": mappings[rid]} for rid in mapped_req_ids
    ]
    return {
        "total_requirements": len(req_ids),
        "mapped_requirements": mapped_req_ids,
        "missing_requirements": missing_req_ids,
        "extra_mapping": extra_mapping,
        "mapping_pairs": mapping_pairs,
        "total_sources": len(source_ids),
    }


def _normalize_vcast_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("requirement_id") or "").strip()
        if not rid:
            continue
        out.setdefault(rid, []).append(
            {
                "testcase": row.get("testcase") or row.get("subprogram") or "",
                "result": row.get("result") or "",
                "unit": row.get("unit") or "",
                "report": row.get("report") or "",
                "source": row.get("source") or "",
            }
        )
    return out


def generate_uds_traceability_matrix(
    items: List[Dict[str, Any]],
    mapping_pairs: Optional[List[Dict[str, Any]]] = None,
    vcast_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    req_ids = sorted({str(x.get("id") or "").strip() for x in items if str(x.get("id") or "").strip()})
    mapping_pairs = mapping_pairs or []
    map_lookup: Dict[str, List[str]] = {}
    for row in mapping_pairs:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("requirement_id") or "").strip()
        if not rid:
            continue
        srcs = row.get("source_ids") or []
        if isinstance(srcs, str):
            srcs = [s.strip() for s in srcs.split(",") if s.strip()]
        elif isinstance(srcs, list):
            srcs = [str(s).strip() for s in srcs if str(s).strip()]
        else:
            srcs = []
        map_lookup[rid] = srcs

    vcast_map = _normalize_vcast_rows(vcast_rows or [])

    matrix: List[Dict[str, Any]] = []
    mapped_source_count = 0
    mapped_test_count = 0
    for rid in req_ids:
        tests = vcast_map.get(rid, [])
        test_ids = [t.get("testcase") for t in tests if t.get("testcase")]
        if map_lookup.get(rid):
            mapped_source_count += 1
        if test_ids:
            mapped_test_count += 1
        matrix.append(
            {
                "requirement_id": rid,
                "source_ids": map_lookup.get(rid, []),
                "tests": tests,
                "test_ids": test_ids,
                "test_count": len(tests),
            }
        )
    return {
        "total_requirements": len(req_ids),
        "rows": matrix,
        "summary": {
            "requirement_count": len(req_ids),
            "mapped_source_count": mapped_source_count,
            "mapped_test_count": mapped_test_count,
        },
        "has_source_mapping": any(r.get("source_ids") for r in matrix),
        "has_tests": any(r.get("test_count") for r in matrix),
    }


def generate_uds_requirements_compare(
    items: List[Dict[str, Any]],
    source_root: str,
) -> Dict[str, Any]:
    req_ids = sorted({str(x.get("id") or "") for x in items if str(x.get("id") or "")})
    source_ids = _scan_source_requirement_ids(source_root)
    source_set = set(source_ids)
    matched = [rid for rid in req_ids if rid in source_set]
    missing = [rid for rid in req_ids if rid not in source_set]
    source_only = [rid for rid in source_ids if rid not in set(req_ids)]
    return {
        "total_requirements": len(req_ids),
        "matched": matched,
        "missing": missing,
        "source_only": source_only,
        "source_scanned": len(source_ids),
    }


def generate_uds_requirements_from_docs(texts: List[str]) -> str:
    lines: List[str] = []
    for txt in texts:
        lines.extend(_extract_requirements_from_doc(txt))
        if not lines:
            lines.extend(_extract_requirements_fallback(txt))
    seen = set()
    uniq: List[str] = []
    for ln in lines:
        if ln in seen:
            continue
        seen.add(ln)
        uniq.append(ln)
    return "\n".join(uniq).strip()
