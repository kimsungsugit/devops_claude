from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.schemas import ScmLinkedDocs, ScmRegisterRequest, ScmUpdateRequest
from backend.services.scm_registry import (
    ScmValidationError,
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


# **N15 fix**: _merge_paths가 read-resolver-state → switch_mode write 패턴이라
# 두 SCM 등록 동시 호출 시 last-writer-wins로 한 쪽 prefix 누락 가능.
# Lock으로 read+modify+write 원자성 보장. 단일 사용자 환경이지만 frontend가
# 여러 SCM 등록을 연속 POST하는 케이스 안전성 확보.
_MERGE_LOCK = threading.Lock()


def merge_all_scm_paths_to_cloudium() -> dict:
    """N18 fix: 등록된 모든 SCM entry의 path를 cloudium allowed_prefixes에 일괄 merge.

    backend startup + cloudium 모드 전환 시 호출. 사용자가 SCM 등록 후
    backend 재시작 또는 처음 cloudium 전환 시 자동으로 모든 path 권한 복원 →
    사용자가 SCM 수정 저장 안 해도 추적성/분석 endpoint 통과.

    Returns: {"merged_entries": int, "mode": "cloudium" | "skipped_local"}
    """
    from backend.services.file_resolver import CloudiumFileResolver, get_resolver
    from backend.services.scm_registry import list_registry_entries

    if not isinstance(get_resolver(), CloudiumFileResolver):
        return {"merged_entries": 0, "mode": "skipped_local"}

    count = 0
    for entry in list_registry_entries():
        try:
            _merge_paths_to_cloudium_prefixes(entry)
            count += 1
        except Exception as e:
            import logging
            logging.getLogger("devops_api").warning(
                "SCM entry %s allowed_prefixes merge 실패: %s",
                getattr(entry, "id", "?"), e,
            )
    return {"merged_entries": count, "mode": "cloudium"}


def _merge_paths_to_cloudium_prefixes(entry: Any) -> None:
    """N9 fix (C): cloudium 모드에서 SCM 등록/수정 시 entry의 source_root 및
    linked_docs 부모 디렉토리를 allowed_prefixes에 자동 merge.

    사용자가 SCM 등록 후 별도로 cloudium allowed_prefixes를 갱신하지 않아도
    sync/impact/doc-gen이 곧바로 통과하도록 단일 출처에서 처리.
    local 모드면 no-op. backend 자체 작업 디렉토리(workspace)는 _check_allowed의
    bypass로 별도 처리되므로 여기서는 외부 path만 의미가 있다.

    N15: _MERGE_LOCK으로 read-modify-write race 차단.
    """
    import os
    from backend.services.file_resolver import (
        CloudiumFileResolver,
        get_resolver,
        switch_mode,
    )
    from backend.helpers.common import _parse_path_list

    with _MERGE_LOCK:
        resolver = get_resolver()
        if not isinstance(resolver, CloudiumFileResolver):
            return

        candidates: set[str] = set()
        # source_root는 multi-path string (콤마/세미콜론/뉴라인 구분) 일 수 있음
        src = (getattr(entry, "source_root", "") or "").strip()
        if src:
            for p in _parse_path_list(src):
                parent = os.path.dirname(p.rstrip("/\\")) or p
                if parent:
                    candidates.add(parent)

        linked = getattr(entry, "linked_docs", None)
        if linked is not None:
            try:
                doc_paths = list(linked.model_dump().values())
            except AttributeError:
                doc_paths = [linked.get(k, "") for k in ("srs", "sds", "uds", "sts", "suts", "sits", "hsis", "stp", "vectorcast")]
            # vectorcast는 복수 경로 list — 단일 string 필드와 함께 평탄화한다.
            flat: list[str] = []
            for v in doc_paths:
                if isinstance(v, (list, tuple)):
                    flat.extend(str(x) for x in v)
                else:
                    flat.append(str(v or ""))
            for v in flat:
                v = (v or "").strip()
                if v:
                    parent = os.path.dirname(v.rstrip("/\\")) or v
                    candidates.add(parent)

        if not candidates:
            return

        existing = list(resolver.allowed_prefixes or [])
        existing_norm = {CloudiumFileResolver._normalize_for_compare(p).rstrip("/") for p in existing}
        new_paths: list[str] = []
        for p in candidates:
            np = CloudiumFileResolver._normalize_for_compare(p).rstrip("/")
            if np in existing_norm:
                continue
            # 이미 존재하는 prefix의 하위 디렉토리면 추가 불필요
            if any(np == ep or np.startswith(ep + "/") for ep in existing_norm):
                continue
            new_paths.append(p)
            existing_norm.add(np)

        if not new_paths:
            return

        merged = ",".join(existing + new_paths)
        switch_mode(
            "cloudium",
            allowed_prefixes=merged,
            gate_process=resolver.gate_process,
        )


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
    except ScmValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        # Remaining ValueError path = "id already exists" → conflict.
        raise HTTPException(status_code=409, detail=str(exc))
    _merge_paths_to_cloudium_prefixes(entry)
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
    except ScmValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _merge_paths_to_cloudium_prefixes(entry)
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
