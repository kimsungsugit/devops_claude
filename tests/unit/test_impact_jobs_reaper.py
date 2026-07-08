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
