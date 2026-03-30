from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.schemas import ScmLinkedDocs, ScmRegisterRequest, ScmUpdateRequest
from backend.services.scm_registry import (
    delete_entry,
    get_registry_entry,
    list_registry_entries,
    register_entry,
    replace_linked_docs,
    update_entry,
)
from backend.services.local_service import svn_info_url
from workflow.impact_audit import list_impact_audits
from workflow.impact_changes import list_change_logs, list_function_history, list_module_history, load_change_log
from workflow.impact_jobs import list_jobs, load_job


router = APIRouter()


def _git_status(entry: Any) -> Dict[str, Any]:
    source_root = Path(str(entry.source_root or "")).expanduser()
    git_ok = shutil.which("git") is not None
    root_ok = source_root.exists() and source_root.is_dir()
    repo_ok = (source_root / ".git").exists() if root_ok else False
    branch = ""
    head = ""
    if git_ok and root_ok and repo_ok:
        try:
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=str(source_root),
                text=True,
                timeout=15,
            ).strip()
        except Exception:
            branch = ""
        try:
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(source_root),
                text=True,
                timeout=15,
            ).strip()
        except Exception:
            head = ""
    return {
        "tool_available": git_ok,
        "source_root_exists": root_ok,
        "repo_detected": repo_ok,
        "branch": branch,
        "head": head,
        "ok": bool(git_ok and root_ok),
    }


def _svn_status(entry: Any) -> Dict[str, Any]:
    svn_ok = shutil.which("svn") is not None
    source_root = Path(str(entry.source_root or "")).expanduser()
    root_ok = source_root.exists() and source_root.is_dir()
    return {
        "tool_available": svn_ok,
        "source_root_exists": root_ok,
        "repo_detected": (source_root / ".svn").exists() if root_ok else False,
        "ok": bool(svn_ok and (root_ok or str(entry.scm_url or "").strip())),
    }


@router.post("/api/scm/register")
def scm_register(req: ScmRegisterRequest) -> Dict[str, Any]:
    try:
        entry = register_entry(req)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "item": entry.model_dump(mode="json")}


@router.get("/api/scm/list")
def scm_list() -> Dict[str, Any]:
    items = [entry.model_dump(mode="json") for entry in list_registry_entries()]
    return {"ok": True, "items": items, "count": len(items)}


@router.put("/api/scm/update/{entry_id}")
def scm_update(entry_id: str, req: ScmUpdateRequest) -> Dict[str, Any]:
    try:
        entry = update_entry(entry_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return {"ok": True, "item": entry.model_dump(mode="json")}


@router.delete("/api/scm/delete/{entry_id}")
def scm_delete(entry_id: str) -> Dict[str, Any]:
    deleted = delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return {"ok": True, "deleted": entry_id}


@router.get("/api/scm/status/{entry_id}")
def scm_status(entry_id: str) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    mode = str(entry.scm_type or "git").lower()
    if mode == "svn":
        status = _svn_status(entry)
    else:
        status = _git_status(entry)
    if entry.scm_password_env:
        status["password_env_present"] = bool(__import__("os").environ.get(entry.scm_password_env))
    if entry.webhook_secret_env:
        status["webhook_secret_env_present"] = bool(__import__("os").environ.get(entry.webhook_secret_env))
    return {"ok": True, "item": entry.model_dump(mode="json"), "status": status}


@router.post("/api/scm/test/{entry_id}")
def scm_test(entry_id: str) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    scm_type = str(entry.scm_type or "git").lower()
    if scm_type == "svn":
        info = svn_info_url(repo_url=entry.scm_url, username=entry.scm_username or "")
        return {"ok": info.get("rc") == 0, "result": info}
    status = _git_status(entry)
    return {"ok": bool(status.get("ok")), "result": status}


@router.post("/api/scm/{entry_id}/link-docs")
def scm_link_docs(entry_id: str, linked_docs: ScmLinkedDocs) -> Dict[str, Any]:
    try:
        entry = replace_linked_docs(entry_id, linked_docs)
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return {"ok": True, "item": entry.model_dump(mode="json")}


@router.get("/api/scm/audit/{entry_id}")
def scm_audit(entry_id: str, limit: int = 10) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_impact_audits(entry_id, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/impact-job/{job_id}")
def scm_impact_job(job_id: str) -> Dict[str, Any]:
    try:
        job = load_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="impact job not found")
    return {"ok": True, "job": job}


@router.get("/api/scm/impact-job/{job_id}/result")
def scm_impact_job_result(job_id: str) -> Dict[str, Any]:
    try:
        job = load_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="impact job not found")
    status = str(job.get("status") or "")
    if status == "completed":
        return {"ok": True, "job": job, "result": job.get("result") or {}}
    if status == "failed":
        return {
            "ok": False,
            "job": job,
            "error": job.get("error") or {},
        }
    raise HTTPException(status_code=409, detail="impact job still running")


@router.get("/api/scm/impact-jobs/{entry_id}")
def scm_impact_jobs(entry_id: str, limit: int = 10) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_jobs(scm_id=entry_id, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/change-history/{entry_id}")
def scm_change_history(entry_id: str, limit: int = 20) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_change_logs(entry_id, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/change-history/detail/{run_id}")
def scm_change_history_detail(run_id: str) -> Dict[str, Any]:
    try:
        item = load_change_log(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="change log not found")
    return {"ok": True, "item": item}


@router.get("/api/scm/change-history/function/{entry_id}/{function_name}")
def scm_change_history_function(entry_id: str, function_name: str, limit: int = 20) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_function_history(entry_id, function_name, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/change-history/module/{entry_id}/{module_name}")
def scm_change_history_module(entry_id: str, module_name: str, limit: int = 20) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_module_history(entry_id, module_name, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}
