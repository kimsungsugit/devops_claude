"""Auto-generated router: sessions"""
from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import shutil
import subprocess
import sys
import traceback
import logging
from time import time
import uuid
import zipfile
import asyncio
from pathlib import Path

from backend.schemas import (
    ReportZipRequest,
    RunRequest,
    SessionConfigPayload,
    SessionNamePayload,
    StopRequest,
)
from datetime import datetime
from backend.helpers import _augment_path, _collect_tool_paths, _create_zip_file, _exports_dir, _invalidate_session_cache, _load_session_meta, _read_json, _resolve_base_dir, _resolve_source_root_from_cfg, _save_session_meta, _session_dir, _track_process, _write_json
from backend.services.files import list_log_candidates, list_report_files, read_csv_rows, tail_text
from backend.services.paths import safe_resolve_under
from backend.services.report_parsers import build_report_summary, build_report_comparisons, find_project_report_dirs
from backend.state import session_list_cache as _session_list_cache, SESSION_CACHE_TTL as _SESSION_CACHE_TTL

repo_root = Path(__file__).resolve().parents[2]

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.get("/api/sessions")
def list_sessions(base: Optional[str] = None) -> List[Dict[str, Any]]:
    base_dir = _resolve_base_dir(base)
    cache_key = str(base_dir.resolve())
    current_time = time()
    
    # 캐시 확인
    if cache_key in _session_list_cache:
        cached_data, cache_time = _session_list_cache[cache_key]
        if current_time - cache_time < _SESSION_CACHE_TTL:
            return cached_data
    
    sessions_dir = base_dir / "sessions"
    if not sessions_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in sessions_dir.iterdir():
        if not p.is_dir():
            continue
        summary_path = p / "analysis_summary.json"
        generated_at = ""
        if summary_path.exists():
            try:
                data = _read_json(summary_path, default={})
                if isinstance(data, dict):
                    generated_at = str(data.get("generated_at") or "")
            except Exception:
                generated_at = ""
        meta = _load_session_meta(p)
        rows.append(
            {
                "id": p.name,
                "path": str(p),
                "generated_at": generated_at,
                "name": str(meta.get("name") or ""),
                "last_opened": str(meta.get("last_opened") or ""),
            }
        )
    rows.sort(key=lambda x: x.get("generated_at") or "", reverse=True)
    
    # 캐시 저장
    _session_list_cache[cache_key] = (rows, current_time)
    return rows


@router.post("/api/sessions/{session_id}/name")
def set_session_name(session_id: str, payload: SessionNamePayload, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    meta = _load_session_meta(session_dir)
    meta["name"] = payload.name.strip()
    _save_session_meta(session_dir, meta)
    _invalidate_session_cache(base_dir)
    return {"ok": True, "id": session_id, "name": meta["name"]}


@router.post("/api/sessions/new")
def create_session(base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_id = uuid.uuid4().hex[:8]
    session_dir = _session_dir(str(base_dir), session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    _save_session_meta(session_dir, {"name": "", "last_opened": datetime.now().isoformat(timespec="seconds")})
    _invalidate_session_cache(base_dir)
    return {"id": session_id, "path": str(session_dir)}


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    try:
        shutil.rmtree(session_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to delete session: {exc}") from exc
    _invalidate_session_cache(base_dir)
    return {"ok": True, "id": session_id}


@router.get("/api/sessions/{session_id}/data")
def get_session_data(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    summary = _read_json(session_dir / "analysis_summary.json", default={})
    findings = _read_json(session_dir / "findings_flat.json", default=[])
    history = _read_json(session_dir / "history.json", default=[])
    status = _read_json(session_dir / "run_status.json", default={})
    return {
        "summary": summary,
        "findings": findings,
        "history": history,
        "status": status,
        "report_dir": str(session_dir),
    }


@router.get("/api/sessions/{session_id}/config")
def get_session_config(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    cfg_path = session_dir / "run_config.json"
    cfg = _read_json(cfg_path, default={}) if cfg_path.exists() else {}
    return {"config": cfg or {}, "path": str(cfg_path)}


@router.post("/api/sessions/{session_id}/config")
def save_session_config(
    session_id: str,
    payload: SessionConfigPayload,
    base: Optional[str] = None,
) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = session_dir / "run_config.json"
    cfg = dict(payload.config or {})
    _write_json(cfg_path, cfg)
    return {"ok": True, "path": str(cfg_path)}


@router.get("/api/sessions/{session_id}/log")
def get_session_log(session_id: str, base: Optional[str] = None, max_lines: int = 200) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    log_path = session_dir / "system.log"
    if not log_path.exists():
        return {"lines": []}
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        return {"lines": lines[-max_lines:]}
    except Exception:
        return {"lines": []}


@router.post("/api/sessions/{session_id}/export")
def export_session(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    out_dir = _exports_dir(str(base_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"session_{session_id}_{ts}.zip"
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in session_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(session_dir)
                zf.write(p, arcname=str(rel))
    meta = _load_session_meta(session_dir)
    meta["last_export"] = datetime.now().isoformat(timespec="seconds")
    meta["last_export_path"] = str(out_path)
    _save_session_meta(session_dir, meta)
    return {"file": out_path.name, "path": str(out_path)}


@router.post("/api/sessions/{session_id}/run")
def start_run(session_id: str, req: RunRequest, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    report_dir = _session_dir(str(base_dir), session_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = report_dir / "run_config.json"
    status_path = report_dir / "run_status.json"
    log_path = report_dir / "system.log"

    cfg = dict(req.config or {})
    resolved, root = _resolve_source_root_from_cfg(cfg, req.project_root)
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise HTTPException(status_code=400, detail="project_root not found")
    cfg["project_root"] = str(root_path)
    _write_json(cfg_path, cfg)

    cmd = [
        sys.executable,
        "-m",
        "workflow.runner",
        "--config",
        str(cfg_path),
        "--status",
        str(status_path),
        "--log",
        str(log_path),
    ]
    env = os.environ.copy()
    env["PATH"] = _augment_path(env.get("PATH", ""), _collect_tool_paths())
    env["PYTHON"] = sys.executable
    env["PYTHONIOENCODING"] = "utf-8"
    repo_str = str(repo_root)
    py_path = env.get("PYTHONPATH", "")
    if repo_str not in py_path.split(os.pathsep):
        env["PYTHONPATH"] = os.pathsep.join([repo_str, py_path]) if py_path else repo_str
    proc = subprocess.Popen(cmd, cwd=repo_str, env=env)
    _track_process(session_id, proc.pid, str(status_path))
    return {
        "pid": proc.pid,
        "status_path": str(status_path),
        "log_path": str(log_path),
        "resolved": resolved,
    }


@router.get("/api/sessions/{session_id}/report/complexity")
def session_complexity(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    report_dir = session_dir
    csv_path = report_dir / "complexity.csv"
    return {"rows": read_csv_rows(csv_path)}


@router.get("/api/sessions/{session_id}/report/docs")
def session_docs(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    doc_path = session_dir / "docs" / "html" / "index.html"
    if not doc_path.exists():
        return {"ok": False, "html": ""}
    return {"ok": True, "html": doc_path.read_text(encoding="utf-8", errors="ignore")}


@router.get("/api/sessions/{session_id}/report/docs/static/{path:path}")
def session_docs_static(session_id: str, path: str, base: Optional[str] = None) -> FileResponse:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    docs_dir = session_dir / "docs" / "html"
    if not docs_dir.exists():
        raise HTTPException(status_code=404, detail="docs not found")
    rel = path or "index.html"
    try:
        target = safe_resolve_under(docs_dir, rel)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target))


@router.get("/api/sessions/{session_id}/report/logs")
def session_logs(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    report_dir = session_dir
    logs = list_log_candidates(report_dir)
    out = {k: [str(p.relative_to(report_dir)) for p in v] for k, v in logs.items()}
    return {"logs": out}


@router.get("/api/sessions/{session_id}/report/logs/read")
def session_logs_read(session_id: str, path: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    report_dir = session_dir
    try:
        target = safe_resolve_under(report_dir, path)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="log not found")
    return {"path": str(target), "text": tail_text(target)}


@router.get("/api/sessions/{session_id}/report/files")
def session_report_files(session_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    report_dir = session_dir
    return list_report_files(report_dir)


@router.get("/api/sessions/{session_id}/report/files/download")
def session_report_files_download(session_id: str, path: str, base: Optional[str] = None) -> FileResponse:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    report_dir = session_dir
    try:
        target = safe_resolve_under(report_dir, path)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target), filename=target.name)


@router.get("/api/sessions/{session_id}/report/files/download/zip")
def session_report_files_download_zip(session_id: str, base: Optional[str] = None) -> FileResponse:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    out_dir = _exports_dir(str(base_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"session_{session_id}_reports_{ts}.zip"
    
    # 파일 수를 먼저 확인하여 작은 경우만 동기 처리
    file_count = sum(1 for _ in session_dir.rglob("*") if _.is_file())
    if file_count > 1000:
        # 큰 경우 백그라운드 스레드로 처리하되, 여기서는 동기 처리로 유지
        # (실제 백그라운드 처리는 별도 엔드포인트로 분리하는 것이 좋음)
        pass
    
    _create_zip_file(session_dir, out_path)
    return FileResponse(out_path, filename=out_path.name, media_type="application/zip")


@router.post("/api/sessions/{session_id}/report/files/download/zip/select")
def session_report_files_download_zip_select(
    session_id: str,
    req: ReportZipRequest,
    base: Optional[str] = None,
) -> FileResponse:
    base_dir = _resolve_base_dir(base)
    session_dir = _session_dir(str(base_dir), session_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    out_dir = _exports_dir(str(base_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"session_{session_id}_reports_{ts}.zip"
    paths = req.paths or []
    if not paths:
        raise HTTPException(status_code=400, detail="paths required")
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 파일 목록을 먼저 수집
        files_to_add = []
        for rel in paths:
            try:
                target = safe_resolve_under(session_dir, rel)
                if target.exists() and target.is_file():
                    files_to_add.append((target, rel))
            except Exception:
                continue
        # 수집된 파일들을 추가
        for target, rel in files_to_add:
            try:
                zf.write(target, arcname=rel)
            except Exception:
                continue
    return FileResponse(out_path, filename=out_path.name, media_type="application/zip")


def _is_process_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


@router.post("/api/run/stop")
def stop_run(req: StopRequest) -> Dict[str, Any]:
    pid = int(req.pid or 0)
    if pid <= 0:
        raise HTTPException(status_code=400, detail="invalid pid")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    else:
        os.kill(pid, 15)
    if req.status_path:
        try:
            path = Path(req.status_path).expanduser().resolve()
            data = _read_json(path, default={})
            if not isinstance(data, dict):
                data = {}
            data.update(
                {
                    "state": "stopped",
                    "phase": "stopped",
                    "message": "stopped by user",
                    "stopped_at": datetime.now().isoformat(),
                }
            )
            _write_json(path, data)
        except Exception:
            pass
    return {"ok": True}


@router.get("/api/reports/local/summary")
def local_report_summary() -> Dict[str, Any]:
    from backend.cache import cached_response

    def _compute():
        roots = find_project_report_dirs(repo_root)
        summaries = [build_report_summary(root, project_root=repo_root) for root in roots]
        comparisons = build_report_comparisons([s for s in summaries if s.get("source", {}).get("job_slug")])
        return {"reports": summaries, "comparisons": comparisons}

    return cached_response("local_report_summary", _compute, ttl=30.0)

