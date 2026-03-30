"""Auto-generated router: exports"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
import uuid
from pathlib import Path
from datetime import datetime
from backend.helpers import _exports_dir, _invalidate_session_cache, _load_session_meta, _resolve_base_dir, _resolve_export_path, _safe_extract_zip, _save_session_meta, _session_dir


router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.get("/api/exports")
def list_exports(
    base: Optional[str] = None,
    session_id: Optional[str] = Query(default=None),
) -> List[Dict[str, Any]]:
    base_dir = _resolve_base_dir(base)
    exports = _exports_dir(str(base_dir))
    if not exports.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in exports.glob("session_*.zip"):
        if session_id and session_id not in p.name:
            continue
        rows.append(
            {
                "file": p.name,
                "path": str(p),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "download_url": f"/api/exports/download/{p.name}",
            }
        )
    rows.sort(key=lambda x: x.get("mtime") or "", reverse=True)
    return rows


@router.delete("/api/exports/{filename}")
def delete_export(filename: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    export_path = _resolve_export_path(base_dir, filename)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="export not found")
    export_path.unlink()
    return {"ok": True, "file": filename}


@router.post("/api/exports/restore/{filename}")
def restore_export(filename: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    export_path = _resolve_export_path(base_dir, filename)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="export not found")

    session_id = uuid.uuid4().hex[:8]
    session_dir = _session_dir(str(base_dir), session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    file_count = _safe_extract_zip(export_path, session_dir)

    meta = _load_session_meta(session_dir)
    if not meta:
        meta = {"name": f"restored_{session_id}"}
    meta["last_opened"] = datetime.now().isoformat(timespec="seconds")
    _save_session_meta(session_dir, meta)
    _invalidate_session_cache(base_dir)

    return {
        "ok": True,
        "session_id": session_id,
        "name": meta.get("name"),
        "restored_files": file_count,
    }


@router.get("/api/exports/download/{filename}")
def download_export(filename: str, base: Optional[str] = None) -> FileResponse:
    base_dir = _resolve_base_dir(base)
    export_path = _resolve_export_path(base_dir, filename)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(export_path, filename=export_path.name, media_type="application/zip")


@router.post("/api/exports/cleanup")
def cleanup_exports(days: int = Query(default=30, ge=1), base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    exports = _exports_dir(str(base_dir))
    if not exports.exists():
        return {"deleted": 0}
    cutoff = datetime.now().timestamp() - (days * 86400)
    deleted = 0
    for p in exports.glob("session_*.zip"):
        if p.stat().st_mtime < cutoff:
            p.unlink()
            deleted += 1
    return {"deleted": deleted}


