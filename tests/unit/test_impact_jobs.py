from __future__ import annotations


def test_start_impact_job_completes_with_sync_thread(tmp_path, monkeypatch):
    from workflow.change_trigger import ChangeTrigger
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, **_extra):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(impact_jobs.threading, "Thread", _SyncThread)
    monkeypatch.setattr(
        impact_jobs,
        "run_impact_update",
        lambda trigger, options=None, on_progress=None: {
            "ok": True,
            "dry_run": trigger.dry_run,
            "trigger": trigger.to_dict(),
            "actions": {"uds": {"mode": "AUTO", "status": "completed"}},
        },
    )

    created = impact_jobs.start_impact_job(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="svn",
            base_ref="",
            changed_files=["Sources/APP/Ap_BuzzerCtrl_PDS.c"],
            dry_run=True,
            targets=["uds"],
            metadata={},
        )
    )

    loaded = impact_jobs.load_job(created["job_id"])
    assert created["ok"] is True
    assert loaded["status"] == "completed"
    assert loaded["result"]["actions"]["uds"]["status"] == "completed"


def test_start_impact_job_without_changed_files_completes_cleanly(tmp_path, monkeypatch):
    from workflow.change_trigger import ChangeTrigger
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, **_extra):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(impact_jobs.threading, "Thread", _SyncThread)

    created = impact_jobs.start_impact_job(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="svn",
            base_ref="",
            changed_files=[],
            dry_run=True,
            targets=["uds"],
            metadata={},
        )
    )

    loaded = impact_jobs.load_job(created["job_id"])
    assert loaded["status"] == "completed"
    assert loaded["result"]["warnings"] == ["no changed files detected"]
