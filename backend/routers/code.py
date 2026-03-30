"""Auto-generated router: code"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
from pathlib import Path
from backend.helpers import _extract_call_graph_payload, _extract_dependency_map_payload, _get_source_sections_cached, _to_swcom_from_fn


router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.get("/api/code/call-graph")
def code_call_graph(
    source_root: str,
    focus_function: str = Query(default=""),
    depth: int = Query(default=2, ge=1, le=6),
    max_files: int = Query(default=1200, ge=100, le=5000),
    include_external: bool = Query(default=False),
) -> Dict[str, Any]:
    sections = _get_source_sections_cached(source_root, max_files=max_files)
    graph = _extract_call_graph_payload(
        sections,
        focus_function=focus_function,
        depth=depth,
        include_external=include_external,
    )
    return {"ok": True, "graph": graph}


@router.get("/api/code/dependency-map")
def code_dependency_map(
    source_root: str,
    level: str = Query(default="module"),
    max_files: int = Query(default=1200, ge=100, le=5000),
) -> Dict[str, Any]:
    sections = _get_source_sections_cached(source_root, max_files=max_files)
    dep = _extract_dependency_map_payload(sections, level=level)
    return {"ok": True, "dependency_map": dep}


@router.get("/api/code/globals")
def code_globals(
    source_root: str,
    max_files: int = Query(default=1200, ge=100, le=5000),
) -> Dict[str, Any]:
    sections = _get_source_sections_cached(source_root, max_files=max_files)
    global_vars = sections.get("global_vars") if isinstance(sections.get("global_vars"), list) else []
    static_vars = sections.get("static_vars") if isinstance(sections.get("static_vars"), list) else []
    globals_info = sections.get("globals_info_map") if isinstance(sections.get("globals_info_map"), dict) else {}
    by_name = sections.get("function_details_by_name") if isinstance(sections.get("function_details_by_name"), dict) else {}

    usage_map: Dict[str, List[str]] = {}
    for fn_key, fn_info in by_name.items():
        if not isinstance(fn_info, dict):
            continue
        fn_display = str(fn_info.get("name") or fn_key)
        for gv in (fn_info.get("globals_global") or []):
            gv_name = str(gv).strip().lower()
            if gv_name:
                usage_map.setdefault(gv_name, [])
                if fn_display not in usage_map[gv_name]:
                    usage_map[gv_name].append(fn_display)
        for sv in (fn_info.get("globals_static") or []):
            sv_name = str(sv).strip().lower()
            if sv_name:
                usage_map.setdefault(sv_name, [])
                if fn_display not in usage_map[sv_name]:
                    usage_map[sv_name].append(fn_display)

    def _row_to_dict(row: list, is_static: bool) -> Dict[str, Any]:
        name = str(row[0]).strip() if len(row) > 0 else ""
        typ = str(row[1]).strip() if len(row) > 1 else ""
        rng = str(row[2]).strip() if len(row) > 2 else ""
        init = str(row[3]).strip() if len(row) > 3 else ""
        extra = str(row[4]).strip() if len(row) > 4 else ""
        info = globals_info.get(name.lower(), {}) if isinstance(globals_info, dict) else {}
        file_path = str(info.get("file") or "")
        desc = str(info.get("desc") or extra)
        used_by = usage_map.get(name.lower(), [])
        return {
            "name": name,
            "type": typ or str(info.get("type") or ""),
            "range": rng or str(info.get("range") or ""),
            "init": init or str(info.get("init") or ""),
            "file": file_path,
            "desc": desc,
            "scope": "static" if is_static else "global",
            "used_by": used_by,
        }

    items = []
    for row in global_vars:
        if isinstance(row, (list, tuple)) and len(row) > 0:
            items.append(_row_to_dict(row, False))
    for row in static_vars:
        if isinstance(row, (list, tuple)) and len(row) > 0:
            items.append(_row_to_dict(row, True))

    return {
        "ok": True,
        "globals": items,
        "total_global": sum(1 for i in items if i["scope"] == "global"),
        "total_static": sum(1 for i in items if i["scope"] == "static"),
    }


@router.get("/api/code/preview/function")
def code_preview_function(
    source_root: str,
    function_name: str,
    include_callees: bool = Query(default=True),
    max_files: int = Query(default=1200, ge=100, le=5000),
) -> Dict[str, Any]:
    fn_name = str(function_name or "").strip()
    if not fn_name:
        raise HTTPException(status_code=400, detail="function_name required")
    sections = _get_source_sections_cached(source_root, max_files=max_files)
    by_name = (
        sections.get("function_details_by_name")
        if isinstance(sections.get("function_details_by_name"), dict)
        else {}
    )
    info = by_name.get(fn_name.lower()) if isinstance(by_name, dict) else None
    if not isinstance(info, dict):
        raise HTTPException(status_code=404, detail="function not found")
    code = str(info.get("body") or "").strip()
    signature = str(info.get("signature") or "").strip()
    if not code and signature:
        code = signature + " { /* preview unavailable */ }"
    call_map = sections.get("call_map") if isinstance(sections.get("call_map"), dict) else {}
    callees = []
    if include_callees and isinstance(call_map, dict):
        vals = call_map.get(fn_name) or call_map.get(fn_name.lower()) or []
        if isinstance(vals, list):
            callees = [str(v).strip() for v in vals if str(v).strip()]
    return {
        "ok": True,
        "function_name": fn_name,
        "preview": {
            "signature": signature,
            "code": code,
            "file": str(info.get("file") or ""),
            "id": str(info.get("id") or ""),
            "swcom": _to_swcom_from_fn(info),
            "callees": callees,
        },
    }


