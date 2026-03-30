from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional

from workflow.change_trigger import ChangeTrigger
from workflow.impact_orchestrator import ImpactOptions, run_impact_update


REPO_ROOT = Path(__file__).resolve().parents[1]
JOB_DIR = REPO_ROOT / "reports" / "impact_jobs"
_JOB_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sanitize_fragment(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip())
    return text.strip("_") or "job"


def _job_path(job_id: str) -> Path:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    return JOB_DIR / f"job_{job_id}.json"


def _write_job(job: Dict[str, Any]) -> Dict[str, Any]:
    path = _job_path(str(job.get("job_id") or ""))
    with _JOB_LOCK:
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job


def load_job(job_id: str) -> Dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise KeyError(job_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"failed to read job state: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("invalid job state")
    return raw


def update_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    message: Optional[str] = None,
    progress: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    job = load_job(job_id)
    if status is not None:
        job["status"] = status
        if status == "running" and not job.get("started_at"):
            job["started_at"] = _now_iso()
    if stage is not None:
        job["stage"] = stage
    if message is not None:
        job["message"] = message
    if progress is not None:
        job["progress"] = dict(progress)
    if result is not None:
        job["result"] = result
    if error is not None:
        job["error"] = error
    job["updated_at"] = _now_iso()
    if job.get("status") in {"completed", "failed"}:
        job["finished_at"] = _now_iso()
    return _write_job(job)


def create_job(
    *,
    scm_id: str,
    trigger_type: str,
    dry_run: bool,
    targets: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"impact_{ts}_{_sanitize_fragment(scm_id)}_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "scm_id": scm_id,
        "trigger_type": trigger_type,
        "dry_run": bool(dry_run),
        "targets": list(targets or []),
        "status": "queued",
        "stage": "prepare",
        "message": "실행 대기 중입니다.",
        "progress": {},
        "metadata": dict(metadata or {}),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    return _write_job(job)


def complete_job(job_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return update_job(
        job_id,
        status="completed",
        stage="done",
        message="완료되었습니다.",
        result=result,
    )


def fail_job(job_id: str, error: Dict[str, Any]) -> Dict[str, Any]:
    title = str(error.get("title") or "실행에 실패했습니다.")
    return update_job(
        job_id,
        status="failed",
        stage="done",
        message=title,
        error=error,
    )


def list_jobs(*, scm_id: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for path in sorted(JOB_DIR.glob("job_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        if scm_id and str(raw.get("scm_id") or "") != str(scm_id):
            continue
        items.append(raw)
        if len(items) >= max(1, int(limit)):
            break
    return items


def _build_error(code: str, title: str, detail: str = "", *, retryable: bool = False) -> Dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "detail": detail,
        "retryable": bool(retryable),
    }


def _classify_exception(exc: Exception) -> Dict[str, Any]:
    message = str(exc or "").strip()
    lower = message.lower()
    if isinstance(exc, FileNotFoundError):
        return _build_error(
            "file_not_found",
            "필수 경로를 찾을 수 없습니다.",
            message or "source_root 또는 산출물 경로를 확인하세요.",
            retryable=False,
        )
    if "registry entry not found" in lower:
        return _build_error(
            "registry_not_found",
            "SCM registry 항목을 찾을 수 없습니다.",
            "선택한 registry가 삭제되었거나 잘못 지정되었습니다.",
            retryable=False,
        )
    if "svn" in lower and ("e170013" in lower or "not a working copy" in lower or "unable to connect" in lower):
        return _build_error(
            "svn_connection_error",
            "SVN 작업복사본 또는 연결 상태를 확인하세요.",
            message,
            retryable=True,
        )
    if "git" in lower and ("not a git repository" in lower or "could not read" in lower):
        return _build_error(
            "git_connection_error",
            "Git 저장소 상태를 확인하세요.",
            message,
            retryable=True,
        )
    return _build_error(
        "impact_exception",
        "Impact 실행 중 예외가 발생했습니다.",
        f"{message}\n{traceback.format_exc(limit=5)}",
        retryable=True,
    )


def _run_job(job_id: str, trigger: ChangeTrigger, options: ImpactOptions) -> None:
    if not (trigger.changed_files or []):
        complete_job(
            job_id,
            {
                "ok": True,
                "dry_run": bool(trigger.dry_run),
                "trigger": trigger.to_dict(),
                "changed_function_types": {},
                "impact": {"direct": [], "indirect_1hop": [], "indirect_2hop": []},
                "warnings": ["no changed files detected"],
                "actions": {},
            },
        )
        return

    update_job(
        job_id,
        status="running",
        stage="prepare",
        message="실행을 시작합니다.",
        progress={"changed_files": len(trigger.changed_files or [])},
    )

    def on_progress(stage: str, message: str, progress: Optional[Dict[str, Any]] = None) -> None:
        update_job(job_id, status="running", stage=stage, message=message, progress=progress or {})

    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(15):
            try:
                job = load_job(job_id)
            except Exception:
                return
            if str(job.get("status") or "") != "running":
                return
            update_job(job_id, status="running")

    heartbeat_thread = threading.Thread(target=heartbeat, name=f"impact-job-heartbeat-{job_id}", daemon=True)
    heartbeat_thread.start()

    try:
        result = run_impact_update(trigger, options=options, on_progress=on_progress)
        if result.get("ok"):
            complete_job(job_id, result)
            return
        if result.get("reason") == "active_lock":
            fail_job(
                job_id,
                _build_error(
                    "run_lock_active",
                    "다른 impact 실행이 진행 중입니다.",
                    "현재 실행 중인 작업이 끝난 뒤 다시 시도하세요.",
                    retryable=True,
                ),
            )
            return
        fail_job(
            job_id,
            _build_error(
                "impact_failed",
                "Impact 실행에 실패했습니다.",
                str(result.get("error") or result.get("reason") or "unknown error"),
                retryable=True,
            ),
        )
    except Exception as exc:
        fail_job(job_id, _classify_exception(exc))
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)


def start_impact_job(trigger: ChangeTrigger, *, options: Optional[ImpactOptions] = None) -> Dict[str, Any]:
    job = create_job(
        scm_id=trigger.scm_id,
        trigger_type=trigger.trigger_type,
        dry_run=trigger.dry_run,
        targets=trigger.targets,
        metadata={"source_root": trigger.source_root, "base_ref": trigger.base_ref},
    )
    job_id = str(job["job_id"])
    update_job(
        job_id,
        message="작업이 큐에 등록되었습니다.",
        progress={"changed_files": len(trigger.changed_files or [])},
    )
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, trigger, options or ImpactOptions()),
        name=f"impact-job-{job_id}",
        daemon=True,
    )
    thread.start()
    started = load_job(job_id)
    return {
        "ok": True,
        "job_id": job_id,
        "status": started.get("status", "queued"),
        "job": started,
    }
