"""M7 회귀 그물 — orphan running 잡 lazy 회수(_reap_if_stale).

프로세스 재시작/크래시로 heartbeat가 끊긴 running 잡이 영구 running으로 관측되던 문제를,
접근 시점(load_job/list_jobs)에 stale running → failed(job_orphaned)로 회수하는지 검증.
backend를 import하지 않아 bcrypt 없이 실행 가능.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import workflow.impact_jobs as ij


def _mk_job(job_id: str, status: str, updated_at: str) -> dict:
    return {
        "job_id": job_id, "scm_id": "hdpdm01", "status": status,
        "stage": "running", "message": "", "progress": {},
        "created_at": updated_at, "updated_at": updated_at,
        "started_at": updated_at, "finished_at": None,
        "result": None, "error": None,
    }


def test_stale_running_is_reaped_to_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    stale = (datetime.now() - timedelta(seconds=ij._STALE_RUNNING_SEC + 60)).astimezone().isoformat(timespec="seconds")
    ij._write_job(_mk_job("impact_x_stale", "running", stale))

    job = ij.load_job("impact_x_stale")

    assert job["status"] == "failed"
    assert (job.get("error") or {}).get("code") == "job_orphaned"
    # 파일에도 반영되어 다음 폴링부터 즉시 failed
    assert ij._load_job_raw("impact_x_stale")["status"] == "failed"


def test_fresh_running_is_not_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    fresh = datetime.now().astimezone().isoformat(timespec="seconds")
    ij._write_job(_mk_job("impact_x_fresh", "running", fresh))

    job = ij.load_job("impact_x_fresh")

    assert job["status"] == "running"


def test_completed_job_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    old = (datetime.now() - timedelta(hours=2)).astimezone().isoformat(timespec="seconds")
    ij._write_job(_mk_job("impact_x_done", "completed", old))

    job = ij.load_job("impact_x_done")

    assert job["status"] == "completed"  # terminal은 회수 대상 아님


def test_list_jobs_surfaces_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    stale = (datetime.now() - timedelta(seconds=ij._STALE_RUNNING_SEC + 60)).astimezone().isoformat(timespec="seconds")
    ij._write_job(_mk_job("impact_x_l", "running", stale))

    items = ij.list_jobs(scm_id="hdpdm01", limit=10)

    assert items and items[0]["status"] == "failed"


def test_malformed_updated_at_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    ij._write_job(_mk_job("impact_x_bad", "running", "not-a-timestamp"))

    job = ij.load_job("impact_x_bad")

    assert job["status"] == "running"  # 파싱 실패는 그대로 둔다(오회수 방지)


def test_completed_not_reverted_by_explicit_running(tmp_path, monkeypatch):
    """terminal(completed)은 최종 상태 — 늦은 on_progress/heartbeat가 status='running'을 명시
    전달해도 되돌리지 않는다(결과 보존). terminal-regression 가드 회귀(가드 제거 시 실패)."""
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    fresh = datetime.now().astimezone().isoformat(timespec="seconds")
    ij._write_job(_mk_job("impact_done2", "running", fresh))
    ij.complete_job("impact_done2", {"ok": True, "marker": "keep"})
    # 늦은 progress 업데이트가 running으로 되돌리려 시도(과거엔 그대로 반영돼 결과 유실).
    ij.update_job("impact_done2", status="running", stage="late", message="stale")
    raw = ij._load_job_raw("impact_done2")
    assert raw["status"] == "completed"                        # 되돌아가지 않음
    assert (raw.get("result") or {}).get("marker") == "keep"   # 결과 보존


def test_completed_not_reverted_by_touch(tmp_path, monkeypatch):
    """heartbeat 순수 touch(all-None)가 이미 완료된 잡을 되살리거나 결과를 지우지 않는다."""
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    fresh = datetime.now().astimezone().isoformat(timespec="seconds")
    ij._write_job(_mk_job("impact_done3", "running", fresh))
    ij.complete_job("impact_done3", {"ok": True, "marker": "keep"})
    ij.update_job("impact_done3")  # heartbeat 순수 touch
    raw = ij._load_job_raw("impact_done3")
    assert raw["status"] == "completed"
    assert (raw.get("result") or {}).get("marker") == "keep"


def test_completed_result_survives_concurrent_touches(tmp_path, monkeypatch):
    """원자적 RMW 회귀 그물: complete_job과 heartbeat touch가 동시에 돌아도 completed+result가
    유실되지 않는다(update_job이 read-modify-write 전체를 _JOB_LOCK으로 직렬화). 과거엔 읽기가
    락 밖이라 heartbeat가 stale running 스냅샷으로 completed를 덮어써 결과가 유실됐다.
    락이 제거되면 이 테스트가 간헐 실패로 잡아낸다(fix 상태에선 항상 통과)."""
    import threading
    monkeypatch.setattr(ij, "JOB_DIR", tmp_path / "jobs")
    fresh = datetime.now().astimezone().isoformat(timespec="seconds")
    stop = threading.Event()

    def toucher() -> None:
        while not stop.is_set():
            try:
                ij.update_job("impact_race")  # heartbeat 순수 touch(연속)
            except Exception:
                pass

    ij._write_job(_mk_job("impact_race", "running", fresh))
    t = threading.Thread(target=toucher, daemon=True)
    t.start()
    try:
        for _ in range(150):
            ij._write_job(_mk_job("impact_race", "running", fresh))  # 강제 리셋(guard 우회)
            ij.complete_job("impact_race", {"ok": True, "marker": "R"})
            raw = ij._load_job_raw("impact_race")
            assert raw["status"] == "completed", f"completed가 {raw['status']}로 되돌려짐(race)"
            assert (raw.get("result") or {}).get("marker") == "R", "완료 결과 유실(race)"
    finally:
        stop.set()
        t.join(timeout=1)
