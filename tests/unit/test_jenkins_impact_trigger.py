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


def test_get_build_changed_files_parses_changeset(monkeypatch):
    from backend.services import jenkins_service

    fixture = {
        "changeSet": {"items": [
            {"affectedPaths": ["Sources/APP/Ap_Door.c", "docs/readme.md"], "commitId": "abc123"},
            {"paths": [{"file": "Sources/APP/Ap_Door.h"}], "commitId": "def456"},
        ]},
        "actions": [{"lastBuiltRevision": {"SHA1": "deadbeef"}}],
    }
    monkeypatch.setattr(jenkins_service.JenkinsClient, "_open_json", lambda self, url: fixture)

    out = jenkins_service.get_build_changed_files(
        job_url="http://jenkins/job/HDPDM01", build_number=42, username="u", api_token="t", verify_tls=True,
    )
    # .c/.h 만 (docs/readme.md 제외), 정렬
    assert out["files"] == ["Sources/APP/Ap_Door.c", "Sources/APP/Ap_Door.h"]
    assert out["revision"] == "deadbeef"   # lastBuiltRevision이 commitId보다 우선
    assert out["all_count"] == 3


def test_resolve_jenkins_changed_files_injects_build_changeset(monkeypatch):
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config", lambda: {"username": "u", "token": "t", "baseUrl": "http://j", "verifyTls": True})
    monkeypatch.setattr(jsvc, "get_build_changed_files", lambda **k: {"files": ["a.c", "b.h"], "revision": "rev1", "all_count": 2})

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X")
    )
    assert files == ["a.c", "b.h"]
    assert use_only is True
    assert meta["changed_files_source"] == "jenkins_changeset"
    assert meta["build_revision"] == "rev1"
    assert meta["jenkins_changed_file_count"] == 2


def test_resolve_jenkins_changed_files_fallback_without_credentials(monkeypatch):
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config", lambda: {"username": "", "token": "", "verifyTls": True})
    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X")
    )
    assert files is None
    assert use_only is False
    assert meta["changed_files_source"] == "local_diff_fallback"


def test_resolve_jenkins_changed_files_rejects_foreign_job_url(monkeypatch):
    """SSRF 방지: job_url이 설정된 baseUrl 하위가 아니면 서버 토큰을 안 보내고 fallback."""
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config",
                        lambda: {"username": "u", "token": "t", "baseUrl": "http://jenkins.local", "verifyTls": True})

    def _boom(**_k):
        raise AssertionError("get_build_changed_files must NOT be called for foreign job_url")

    monkeypatch.setattr(jsvc, "get_build_changed_files", _boom)

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://evil.example/job/X")
    )
    assert files is None
    assert use_only is False
    assert "baseUrl" in meta["linkage_reason"]


def test_resolve_jenkins_changed_files_fallback_without_build(monkeypatch):
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x")  # build_number=0, job_url=""
    )
    assert files is None
    assert use_only is False
    assert meta["changed_files_source"] == "local_diff_fallback"
    assert "no build_number/job_url" in meta["linkage_reason"]
