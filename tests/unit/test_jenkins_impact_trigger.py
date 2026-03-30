from __future__ import annotations


def test_jenkins_impact_trigger_returns_registry_trigger(monkeypatch):
    from backend.routers.jenkins import jenkins_impact_trigger
    from backend.schemas import JenkinsImpactTriggerRequest

    class _FakeTrigger:
        def to_dict(self):
            return {
                "trigger_type": "jenkins",
                "scm_id": "hdpdm01",
                "changed_files": ["a.c"],
                "metadata": {"build_number": 42},
            }

    monkeypatch.setattr("backend.routers.jenkins.build_registry_trigger", lambda **_kwargs: _FakeTrigger())
    monkeypatch.setattr("backend.routers.jenkins.run_impact_update", lambda trigger: {"ok": True, "trigger": trigger.to_dict(), "actions": {"sts": {"mode": "FLAG"}}})

    result = jenkins_impact_trigger(
        JenkinsImpactTriggerRequest(
            scm_id="hdpdm01",
            build_number=42,
            job_url="http://jenkins/job/HDPDM01",
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert result["trigger"]["scm_id"] == "hdpdm01"
    assert result["actions"]["sts"]["mode"] == "FLAG"


def test_jenkins_impact_trigger_async_returns_job(monkeypatch):
    from backend.routers.jenkins import jenkins_impact_trigger_async
    from backend.schemas import JenkinsImpactTriggerRequest

    class _FakeTrigger:
        trigger_type = "jenkins"
        scm_id = "hdpdm01"
        dry_run = True
        targets = ["sts"]
        source_root = "D:/src"
        base_ref = ""

    monkeypatch.setattr("backend.routers.jenkins.build_registry_trigger", lambda **_kwargs: _FakeTrigger())
    monkeypatch.setattr(
        "backend.routers.jenkins.start_impact_job",
        lambda trigger: {"ok": True, "job_id": "impact_2", "status": "queued", "job": {"job_id": "impact_2"}},
    )

    result = jenkins_impact_trigger_async(
        JenkinsImpactTriggerRequest(
            scm_id="hdpdm01",
            build_number=42,
            job_url="http://jenkins/job/HDPDM01",
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert result["job_id"] == "impact_2"
