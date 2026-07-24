"""과거 빌드 일괄 캐시(백필) — sync_jenkins_artifacts를 빌드 번호 리스트로 반복.

기존 sync(/api/jenkins/sync*)는 선택 빌드 1개만 캐시한다 — 요약탭의 다빌드 축
(rule-trend/baseline-diff/타임라인)은 캐시 빌드 수가 데이터 상한이므로, Jenkins가
연결돼 있을 때 과거 빌드를 백그라운드로 채워 넣는 경로가 필요하다.

규약:
- Jenkins 미도달은 정직한 실패(`jenkins_unreachable`) — 캐시로 위장하지 않는다.
- 빌드당 try/except 격리 — 한 빌드 실패가 나머지를 죽이지 않고 per_build에 기록.
- job_url당 동시 1개(중복 시작 거부) — 같은 빌드 디렉토리 이중 쓰기 방지.
- 이미 캐시된 빌드는 skip(옵션) — sync_jenkins_artifacts 내부의 소스 센티널 재사용과
  별개로, 아티팩트 재다운로드 자체를 건너뛴다.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_BY_JOB: Dict[str, str] = {}  # job_url → 실행 중 job_id
_MAX_JOBS_KEPT = 20
MAX_BACKFILL_COUNT = 30


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _prune_jobs_locked() -> None:
    if len(_JOBS) <= _MAX_JOBS_KEPT:
        return
    done = [jid for jid, j in _JOBS.items() if j.get("state") != "running"]
    done.sort(key=lambda jid: str(_JOBS[jid].get("finished_at") or ""))
    for jid in done[: len(_JOBS) - _MAX_JOBS_KEPT]:
        _JOBS.pop(jid, None)


def resolve_recent_build_numbers(
    *, job_url: str, username: str, api_token: str, verify_tls: bool,
    count: int, exclude: set,
) -> List[int]:
    """Jenkins에서 최근 빌드 번호를 조회(진행 중 빌드 제외). 연결 실패는 예외 전파."""
    from backend.services.jenkins_service import list_builds

    builds = list_builds(
        job_url=job_url, username=username, api_token=api_token,
        limit=max(count + len(exclude) + 5, count), verify_tls=verify_tls,
    )
    out: List[int] = []
    for b in builds:
        num = b.get("number")
        if not isinstance(num, int) or num in exclude or b.get("building"):
            continue
        out.append(num)
        if len(out) >= count:
            break
    return out


def backfill_status(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def active_job_for(job_url: str) -> Optional[str]:
    with _LOCK:
        return _ACTIVE_BY_JOB.get(job_url)


def start_backfill(
    *, job_url: str, username: str, api_token: str, cache_root: Path,
    verify_tls: bool, patterns: List[str], build_numbers: List[int],
    scm_username: str = "", scm_id: str = "",
) -> Dict[str, Any]:
    """백필 워커 시작 — 수락 즉시 job_id 반환, 진행은 backfill_status로 폴링."""
    job_id = uuid.uuid4().hex
    with _LOCK:
        if job_url in _ACTIVE_BY_JOB:
            return {"accepted": False, "reason": "backfill_already_running", "job_id": _ACTIVE_BY_JOB[job_url]}
        state = {
            "job_id": job_id,
            "job_url": job_url,
            "state": "running",
            "total": len(build_numbers),
            "completed": 0,
            "current_build": None,
            "per_build": [],
            "started_at": _now_iso(),
            "finished_at": None,
        }
        _JOBS[job_id] = state
        _ACTIVE_BY_JOB[job_url] = job_id
        _prune_jobs_locked()

    def _worker() -> None:
        from backend.services.jenkins_service import sync_jenkins_artifacts

        try:
            for num in build_numbers:
                with _LOCK:
                    _JOBS[job_id]["current_build"] = num
                entry: Dict[str, Any] = {"build_number": num, "status": "ok", "error": None}
                try:
                    _info, _root, reports_dir, _dl, _arts = sync_jenkins_artifacts(
                        job_url=job_url, username=username, api_token=api_token,
                        cache_root=cache_root, verify_tls=verify_tls,
                        build_selector=str(num), patterns=patterns,
                        scm_username=scm_username, scm_id=scm_id,
                    )
                    entry["reports_dir"] = str(reports_dir)
                except Exception as exc:
                    # 빌드당 격리 — 실패는 per_build에 정직 기록하고 다음 빌드 계속.
                    logger.warning("backfill build %s failed (%s): %s", num, job_url, exc)
                    entry["status"] = "error"
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                with _LOCK:
                    _JOBS[job_id]["per_build"].append(entry)
                    _JOBS[job_id]["completed"] += 1
        finally:
            with _LOCK:
                _JOBS[job_id]["state"] = (
                    "done" if all(e.get("status") != "error" for e in _JOBS[job_id]["per_build"]) else "done_with_errors"
                )
                _JOBS[job_id]["current_build"] = None
                _JOBS[job_id]["finished_at"] = _now_iso()
                if _ACTIVE_BY_JOB.get(job_url) == job_id:
                    _ACTIVE_BY_JOB.pop(job_url, None)

    threading.Thread(target=_worker, name=f"sync-backfill-{job_id[:8]}", daemon=True).start()
    return {"accepted": True, "job_id": job_id}
