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
    # HTTP 경로(/api/scm/impact-job/{job_id})에서 유입되는 job_id를 무검증 결합하면 Windows
    # 백슬래시/절대경로로 JOB_DIR 밖 .json을 읽는 traversal이 된다(load_job). 정상 job_id는
    # 'impact_<ts>_<scm>_<uuid8>'로 alnum/_/- 뿐이라 sanitize해도 무변형(왕복 안전).
    safe = _sanitize_fragment(job_id)
    return JOB_DIR / f"job_{safe}.json"


def _write_job(job: Dict[str, Any]) -> Dict[str, Any]:
    path = _job_path(str(job.get("job_id") or ""))
    with _JOB_LOCK:
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job


# running으로 남았으나 heartbeat(15s 주기)가 이 시간 이상 끊기면 프로세스 사망으로 간주.
# 20×heartbeat = 5분. heartbeat는 별도 daemon 스레드라 프로세스가 살아있는 한(장시간 subprocess
# 중에도) 계속 갱신되므로, 이 임계를 넘긴 running은 프로세스 orphan으로 볼 수 있다.
_STALE_RUNNING_SEC = 300


def _load_job_raw(job_id: str) -> Dict[str, Any]:
    """순수 읽기(회수 side-effect 없음). update_job이 재귀 없이 재사용."""
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


def _reap_if_stale(raw: Dict[str, Any]) -> Dict[str, Any]:
    """heartbeat가 끊긴 orphan running 잡을 failed로 회수(lazy, 접근 시점).

    프로세스 재시작/크래시로 daemon 스레드가 죽으면 job JSON은 'running'으로 남고 폴링
    클라이언트가 영구 running으로 관측한다. updated_at이 _STALE_RUNNING_SEC를 넘긴 running만
    failed로 표시. 아직 fresh하거나 terminal(completed/failed)이면 그대로 반환.
    """
    if not isinstance(raw, dict) or raw.get("status") != "running":
        return raw
    try:
        ts = datetime.fromisoformat(str(raw.get("updated_at") or ""))
    except (ValueError, TypeError):
        return raw
    now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
    if (now - ts).total_seconds() < _STALE_RUNNING_SEC:
        return raw
    job_id = str(raw.get("job_id") or "")
    if not job_id:
        return raw
    try:
        return fail_job(job_id, _build_error(
            "job_orphaned",
            "실행이 중단되었습니다(프로세스 재시작 등).",
            "heartbeat가 5분 이상 끊겨 orphan으로 회수했습니다. 다시 실행하세요.",
            retryable=True,
        ))
    except Exception:
        return raw


def load_job(job_id: str) -> Dict[str, Any]:
    return _reap_if_stale(_load_job_raw(job_id))


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
    job = _load_job_raw(job_id)  # 순수 읽기 — reap 래퍼(load_job)를 쓰면 fail_job→update_job 재귀.
    # heartbeat(모든 필드 None인 순수 touch)가 이미 종료된 잡을 되살리지 않도록 무시.
    # complete_job/fail_job과 heartbeat의 read-modify-write race로 completed→running 되돌림 방지(W1).
    if (
        job.get("status") in {"completed", "failed"}
        and status is None and stage is None and message is None
        and progress is None and result is None and error is None
    ):
        return job
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
        items.append(_reap_if_stale(raw))  # orphan running을 목록에서도 failed로 표면화
        if len(items) >= max(1, int(limit)):
            break
    return items


def _prune_jobs(keep: int = 200) -> None:
    """완료/실패한 오래된 잡 파일을 상한(keep) 초과분만 정리(누적 디스크 방지). best-effort.

    VectorCAST 잡 result는 test_rows 포함 시 수백 KB~MB라 누적이 빠르다. 최신 keep개는
    보존하고, 그 너머의 terminal(completed/failed) 잡만 삭제한다(running 잡은 절대 삭제 안 함).
    """
    try:
        files = sorted(JOB_DIR.glob("job_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return
    for path in files[keep:]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict) and raw.get("status") in {"completed", "failed"}:
            try:
                path.unlink()
            except OSError:
                continue


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
        # 변경 파일 0 fast-path — 페이로드 shape를 정상 실행과 동일하게 채운다. 과거엔 classification/
        # function_meta/asil/coverage_gap/regression_test_set/impact_traversal이 통째로 빠져 프론트가
        # undefined를 읽고(옵셔널 체이닝에 의존) 패널이 조용히 사라졌다 — 계약 발산 방지(X3).
        complete_job(
            job_id,
            {
                "ok": True,
                "dry_run": bool(trigger.dry_run),
                "trigger": trigger.to_dict(),
                "changed_function_types": {},
                "change_details": {},
                "function_diffs": {},
                "impact": {"direct": [], "indirect_1hop": [], "indirect_2hop": []},
                "warnings": ["no changed files detected"],
                "actions": {},
                "function_meta": {},
                "regression_test_set": {"suts": {}, "sits": {}, "summary": {
                    "suts_tc_count": 0, "sits_chain_count": 0, "impacted_function_count": 0,
                    "coverage_target": "", "mcdc_required": False,
                }},
                "asil": {
                    "max_changed": "", "escalation": False, "mcdc_required": False,
                    "coverage_target": "", "unknown_changed_count": 0,
                },
                "coverage_gap": {"available": False, "reason": "변경 파일 없음 — 커버리지 평가 생략"},
                "classification": {
                    "granularity": "file", "source": "", "signature_distinguished": False,
                    "line_classified_file_count": 0, "narrow_removed_count": 0,
                    "narrow_removed_functions": [],
                    "evidenced_function_count": 0, "fattened_function_count": 0,
                },
                "impact_traversal": {
                    "truncated": False, "truncated_at_hop": 0,
                    "max_impacted_functions": int(getattr(options, "max_impacted_functions", 0) or 0),
                    "max_hop": int(getattr(options, "max_hop", 0) or 0),
                },
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
            update_job(job_id)  # status 재설정 없이 updated_at만 갱신(W1 race 회피)

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
        # 부분 실패(분석은 성공, 일부 문서 자동 생성만 실패) — 전체를 fail로 버리면 이미 계산된
        # ISO 증거(변경함수·ASIL·커버리지·회귀시험·audit_path)가 통째로 사라진다. 결과를 그대로
        # 전달하고 완료 처리하되, actions[target].status="failed"와 warnings로 실패를 표면화한다.
        if result.get("partial_failure") and result.get("actions"):
            _failed = [
                t for t, info in (result.get("actions") or {}).items()
                if isinstance(info, dict) and info.get("status") == "failed"
            ]
            # complete_job은 message를 "완료되었습니다."로 고정하므로 직접 update_job으로 완료 처리
            # (부분 실패 사실을 message에 남긴다 — 성공으로 위장 금지).
            update_job(
                job_id,
                status="completed",
                stage="done",
                message=(
                    "분석은 완료했으나 일부 문서 생성에 실패했습니다: "
                    f"{', '.join(t.upper() for t in sorted(_failed)) or '일부 대상'}"
                ),
                result=result,
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


def start_job(
    *,
    scm_id: str,
    trigger_type: str,
    runner,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """범용 백그라운드 잡 — runner(job_id)->result dict를 user context를 상속한 스레드에서 실행.

    cloudium worker 접근(resolver ContextVar)이 필요한 무거운 작업(예: VectorCAST 원격
    폴더 파싱 수 분)을 동기 HTTP 대신 잡으로 돌려 프록시/브라우저 타임아웃과 컴포넌트
    언마운트 abort를 피한다. 폴링은 기존 /api/scm/impact-job/{id}(+/result)를 재사용한다.
    runner 예외는 _classify_exception으로 분류해 fail_job에 기록한다.
    """
    _prune_jobs()
    job = create_job(scm_id=scm_id, trigger_type=trigger_type, dry_run=False, metadata=metadata)
    job_id = str(job["job_id"])

    def _exec() -> None:
        update_job(job_id, status="running", stage="prepare", message="실행을 시작합니다.")
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(15):
                try:
                    j = load_job(job_id)
                except Exception:
                    return
                if str(j.get("status") or "") != "running":
                    return
                # status는 재설정하지 않고 updated_at만 갱신 — stale read와 runner의
                # complete_job 사이 race로 completed를 running으로 되돌리는 것을 방지.
                update_job(job_id)

        hb = threading.Thread(target=heartbeat, name=f"job-heartbeat-{job_id}", daemon=True)
        hb.start()
        try:
            result = runner(job_id)
            complete_job(job_id, result if isinstance(result, dict) else {"ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 — 분류 후 fail_job에 기록
            fail_job(job_id, _classify_exception(exc))
        finally:
            heartbeat_stop.set()
            hb.join(timeout=1)

    try:
        from backend.user_context import wrap_with_user
        target = wrap_with_user(_exec)
    except ImportError:
        target = _exec
    thread = threading.Thread(target=target, name=f"job-{job_id}", daemon=True)
    thread.start()
    return {"ok": True, "job_id": job_id, "status": "queued", "job": load_job(job_id)}


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
    try:
        from backend.user_context import wrap_with_user
        _target = wrap_with_user(_run_job)
    except ImportError:
        _target = _run_job
    thread = threading.Thread(
        target=_target,
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
