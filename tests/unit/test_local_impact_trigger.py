from __future__ import annotations


def test_local_impact_trigger_returns_registry_trigger(monkeypatch):
    from backend.routers.local import local_impact_trigger
    from backend.schemas import LocalImpactTriggerRequest

    class _FakeTrigger:
        def to_dict(self):
            return {
                "trigger_type": "local",
                "scm_id": "hdpdm01",
                "changed_files": ["a.c"],
                "dry_run": True,
            }

    monkeypatch.setattr("backend.routers.local.build_registry_trigger", lambda **_kwargs: _FakeTrigger())
    monkeypatch.setattr("backend.routers.local.run_impact_update", lambda trigger: {"ok": True, "trigger": trigger.to_dict(), "actions": {"uds": {"mode": "AUTO"}}})

    result = local_impact_trigger(
        LocalImpactTriggerRequest(
            scm_id="hdpdm01",
            dry_run=True,
            targets=["uds"],
            manual_changed_files=["a.c"],
        )
    )

    assert result["ok"] is True
    assert result["trigger"]["scm_id"] == "hdpdm01"
    assert result["actions"]["uds"]["mode"] == "AUTO"


def test_local_impact_trigger_async_returns_job(monkeypatch):
    from backend.routers.local import local_impact_trigger_async
    from backend.schemas import LocalImpactTriggerRequest

    class _FakeTrigger:
        trigger_type = "local"
        scm_id = "hdpdm01"
        dry_run = True
        targets = ["uds"]
        source_root = "D:/src"
        base_ref = ""

    monkeypatch.setattr("backend.routers.local.build_registry_trigger", lambda **_kwargs: _FakeTrigger())
    monkeypatch.setattr(
        "backend.routers.local.start_impact_job",
        lambda trigger: {"ok": True, "job_id": "impact_1", "status": "queued", "job": {"job_id": "impact_1"}},
    )

    result = local_impact_trigger_async(
        LocalImpactTriggerRequest(
            scm_id="hdpdm01",
            dry_run=True,
            targets=["uds"],
            manual_changed_files=["a.c"],
        )
    )

    assert result["ok"] is True
    assert result["job_id"] == "impact_1"
