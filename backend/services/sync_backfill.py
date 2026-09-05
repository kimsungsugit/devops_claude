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


def _warm_change_matrix(
    *, job_id: str, job_url: str, cache_root: Path, baseline_build: Optional[int],
) -> None:
    """백필 뒤 변경 영향 셀(함수 축)을 미리 계산해 둔다 — 사용자가 표를 열 때 즉시 채워지도록.

    엔드포인트를 그대로 호출한다(계산 로직 이중화 금지 — 캐시 키·락·봉투 규약이 한 곳에만
    있어야 한다). `pending_cells`는 이미 content_sha로 dedup돼 있어, 동일 트리 N개 빌드는
    셀 1개만 계산된다.
    """
    from backend.routers.summary_insight import summary_change_matrix, summary_change_matrix_cell

    body: Dict[str, Any] = {"job_url": job_url, "cache_root": str(cache_root)}
    if baseline_build is not None:
        body["baseline_build"] = int(baseline_build)
    try:
        matrix = summary_change_matrix({**body, "level": "functions"})
    except Exception as exc:  # noqa: BLE001 — warm 실패가 sync 성과를 되돌리면 안 된다
        logger.warning("backfill warm: matrix query failed (%s): %s", job_url, exc)
        with _LOCK:
            _JOBS[job_id]["matrix"] = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
        return
    if not matrix.get("available"):
        with _LOCK:
            _JOBS[job_id]["matrix"] = {"state": "skipped", "reason": matrix.get("reason")}
        return
    pending = matrix.get("pending_cells") or []
    with _LOCK:
        _JOBS[job_id]["phase"] = "matrix"
        _JOBS[job_id]["matrix"] = {
            "state": "running", "total": len(pending), "completed": 0,
            "baseline_build": (matrix.get("baseline") or {}).get("build_number"),
            "errors": [],
        }
    for item in pending:
        target = item.get("target_build")
        with _LOCK:
            _JOBS[job_id]["matrix"]["current_build"] = target
        try:
            resp = summary_change_matrix_cell({**body, "target_build": target})
            ok = bool(resp.get("available"))
            err = None if ok else str(resp.get("reason") or "unavailable")
        except Exception as exc:  # noqa: BLE001 — 셀당 격리(한 쌍 실패가 나머지를 죽이지 않음)
            logger.warning("backfill warm: cell %s failed: %s", target, exc)
            ok, err = False, f"{type(exc).__name__}: {exc}"
        with _LOCK:
            m = _JOBS[job_id]["matrix"]
            m["completed"] += 1
            if not ok:
                m["errors"].append({"target_build": target, "error": err})
    with _LOCK:
        m = _JOBS[job_id]["matrix"]
        m["state"] = "done" if not m["errors"] else "done_with_errors"
        m["current_build"] = None


def start_backfill(
    *, job_url: str, username: str, api_token: str, cache_root: Path,
    verify_tls: bool, patterns: List[str], build_numbers: List[int],
    scm_username: str = "", scm_id: str = "",
    pin_source: bool = False, warm_matrix: bool = False,
    baseline_build: Optional[int] = None,
) -> Dict[str, Any]:
    """백필 워커 시작 — 수락 즉시 job_id 반환, 진행은 backfill_status로 폴링.

    `pin_source`: 소스를 **빌드 시점 revision**으로 고정한다. 끄면 HEAD 체크아웃이라 과거
    빌드를 오늘 받아오면 전부 오늘의 트리가 되어 빌드 간 비교가 무의미해진다.
    `warm_matrix`: sync가 끝난 뒤 변경 영향 함수 축 셀까지 미리 계산한다(phase="matrix").
    """
    job_id = uuid.uuid4().hex
    with _LOCK:
        if job_url in _ACTIVE_BY_JOB:
            return {"accepted": False, "reason": "backfill_already_running", "job_id": _ACTIVE_BY_JOB[job_url]}
        state = {
            "job_id": job_id,
            "job_url": job_url,
            "state": "running",
            "phase": "sync",
            "pin_source": bool(pin_source),
            "warm_matrix": bool(warm_matrix),
            "total": len(build_numbers),
            "completed": 0,
            "current_build": None,
            "per_build": [],
            "matrix": None,
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
                    info, _root, reports_dir, _dl, _arts = sync_jenkins_artifacts(
                        job_url=job_url, username=username, api_token=api_token,
                        cache_root=cache_root, verify_tls=verify_tls,
                        build_selector=str(num), patterns=patterns,
                        scm_username=scm_username, scm_id=scm_id,
                        pin_source_revision=pin_source,
                    )
                    entry["reports_dir"] = str(reports_dir)
                    checkout = (info or {}).get("checkout") or {}
                    # 고정 성패를 빌드별로 남긴다 — 전부 성공한 것처럼 뭉뚱그리면 어떤 빌드가
                    # 여전히 HEAD 트리인지 알 수 없다.
                    entry["revision"] = checkout.get("revision") or ""
                    entry["revision_source"] = checkout.get("revision_source") or ""
                    if pin_source and checkout.get("pin_error"):
                        entry["status"] = "pin_failed"
                        entry["error"] = f"revision 고정 실패(HEAD로 진행): {checkout['pin_error']}"
                except Exception as exc:
                    # 빌드당 격리 — 실패는 per_build에 정직 기록하고 다음 빌드 계속.
                    logger.warning("backfill build %s failed (%s): %s", num, job_url, exc)
                    entry["status"] = "error"
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                with _LOCK:
                    _JOBS[job_id]["per_build"].append(entry)
                    _JOBS[job_id]["completed"] += 1
            if warm_matrix:
                _warm_change_matrix(
                    job_id=job_id, job_url=job_url, cache_root=cache_root,
                    baseline_build=baseline_build,
                )
        finally:
            with _LOCK:
                _JOBS[job_id]["state"] = (
                    "done" if all(e.get("status") != "error" for e in _JOBS[job_id]["per_build"]) else "done_with_errors"
                )
                _JOBS[job_id]["phase"] = "finished"
                _JOBS[job_id]["current_build"] = None
                _JOBS[job_id]["finished_at"] = _now_iso()
                if _ACTIVE_BY_JOB.get(job_url) == job_id:
                    _ACTIVE_BY_JOB.pop(job_url, None)

    threading.Thread(target=_worker, name=f"sync-backfill-{job_id[:8]}", daemon=True).start()
    return {"accepted": True, "job_id": job_id}
