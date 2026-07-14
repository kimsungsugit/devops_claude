from __future__ import annotations


def test_start_impact_job_completes_with_sync_thread(tmp_path, monkeypatch):
    from workflow.change_trigger import ChangeTrigger
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

    # Mock run_impact_update so no real orchestration happens
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

    # Wait for the background thread to finish (with timeout to prevent hang)
    job_id = created["job_id"]
    _wait_for_job(impact_jobs, job_id, timeout=10)

    loaded = impact_jobs.load_job(job_id)
    assert created["ok"] is True
    assert loaded["status"] == "completed"
    assert loaded["result"]["actions"]["uds"]["status"] == "completed"


def test_start_impact_job_without_changed_files_completes_cleanly(tmp_path, monkeypatch):
    from workflow.change_trigger import ChangeTrigger
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

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

    job_id = created["job_id"]
    _wait_for_job(impact_jobs, job_id, timeout=10)

    loaded = impact_jobs.load_job(job_id)
    assert loaded["status"] == "completed"
    # I2: 사유 미상(metadata 비어 있음) → 일반 '감지되지 않음' 문구.
    assert loaded["result"]["warnings"] == ["변경 파일이 감지되지 않았습니다."]


def test_fast_path_surfaces_changeset_vs_authoritative_reason(tmp_path, monkeypatch):
    """I2: '0 영향'의 사유를 표면화 — 빈 Jenkins changeSet(놓쳤을 수 있음)와 권위 svn A:B(신뢰)를
    구분한다(silent-0 정직화)."""
    from workflow.change_trigger import ChangeTrigger
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

    def _run(meta):
        created = impact_jobs.start_impact_job(ChangeTrigger(
            trigger_type="jenkins", scm_id="hdpdm01", source_root=str(tmp_path / "src"),
            scm_type="svn", base_ref="", changed_files=[], dry_run=True, targets=["uds"], metadata=meta,
        ))
        _wait_for_job(impact_jobs, created["job_id"], timeout=10)
        return impact_jobs.load_job(created["job_id"])["result"]["warnings"]

    cs = _run({"changed_files_source": "jenkins_changeset"})
    assert any("changeSet가 비어" in w and "확인" in w for w in cs), cs  # 주의 문구

    sv = _run({"changed_files_source": "svn_revision_range"})
    assert any("권위 svn" in w and "신뢰" in w for w in sv), sv  # 신뢰 문구


def test_start_job_generic_runs_runner_and_completes(tmp_path, monkeypatch):
    """범용 start_job: runner 결과를 잡 result로 저장하고 completed."""
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

    created = impact_jobs.start_job(
        scm_id="kjpds02",
        trigger_type="vectorcast",
        runner=lambda job_id: {"ok": True, "data": {"test_rows_count": 7}, "source": "cloudium"},
        metadata={"job_url": "http://j/job/X"},
    )
    job_id = created["job_id"]
    _wait_for_job(impact_jobs, job_id, timeout=10)

    loaded = impact_jobs.load_job(job_id)
    assert created["ok"] is True
    assert loaded["status"] == "completed"
    assert loaded["result"]["data"]["test_rows_count"] == 7
    assert loaded["result"]["source"] == "cloudium"
    assert loaded["trigger_type"] == "vectorcast"


def test_start_job_generic_failure_is_classified(tmp_path, monkeypatch):
    """runner 예외는 fail_job으로 분류 기록(잡이 멈추지 않고 failed 상태)."""
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")

    def _boom(_job_id):
        raise RuntimeError("worker IPC down")

    created = impact_jobs.start_job(scm_id="x", trigger_type="vectorcast", runner=_boom)
    job_id = created["job_id"]
    _wait_for_job(impact_jobs, job_id, timeout=10)

    loaded = impact_jobs.load_job(job_id)
    assert loaded["status"] == "failed"
    assert loaded["error"]["code"] == "impact_exception"
    assert "worker IPC down" in (loaded["error"]["detail"] or "")


def _wait_for_job(impact_jobs_mod, job_id: str, timeout: float = 10) -> None:
    """Poll job status until terminal, with a hard timeout to prevent hangs."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            job = impact_jobs_mod.load_job(job_id)
        except (KeyError, RuntimeError):
            # KeyError: file not created yet; RuntimeError: partial write / empty file
            time.sleep(0.05)
            continue
        if job.get("status") in {"completed", "failed"}:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def test_partial_failure_preserves_analysis_result(tmp_path, monkeypatch):
    """문서 1개 자동 생성 실패(partial_failure)가 분석 결과 전체를 폐기하지 않는다.

    과거엔 result["ok"]=False → fail_job → 이미 계산된 ISO 증거(변경함수·ASIL·커버리지·회귀·
    audit_path)가 통째로 사라지고 클라이언트엔 error만 갔다. 이제 완료 처리하고 결과를 전달하되,
    message와 actions[t].status="failed"로 실패를 정직하게 표면화한다.
    """
    from workflow.change_trigger import ChangeTrigger
    from workflow import impact_jobs

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(
        impact_jobs,
        "run_impact_update",
        lambda trigger, options=None, on_progress=None: {
            "ok": False,                 # 문서 생성 실패 신호(하위호환)
            "partial_failure": True,     # 분석 자체는 유효
            "dry_run": trigger.dry_run,
            "trigger": trigger.to_dict(),
            "changed_function_types": {"door_run": "BODY"},
            "impact": {"direct": ["door_run"], "indirect_1hop": [], "indirect_2hop": []},
            "asil": {"max_changed": "D", "escalation": True},
            "coverage_gap": {"available": True, "summary": {"evaluated": 1}},
            "audit_path": "reports/impact_audit/x.md",
            "actions": {
                "uds": {"mode": "AUTO", "status": "completed"},
                "sits": {"mode": "AUTO", "status": "failed", "error": "template missing"},
            },
        },
    )

    created = impact_jobs.start_impact_job(
        ChangeTrigger(
            trigger_type="local", scm_id="hdpdm01", source_root=str(tmp_path / "src"),
            scm_type="svn", base_ref="", changed_files=["a.c"], dry_run=True,
            targets=["uds", "sits"], metadata={},
        )
    )
    job_id = created["job_id"]
    _wait_for_job(impact_jobs, job_id, timeout=10)
    loaded = impact_jobs.load_job(job_id)

    # 완료로 처리되고 분석 결과가 보존된다(과거엔 status=failed + result 없음)
    assert loaded["status"] == "completed"
    res = loaded["result"]
    assert res["changed_function_types"] == {"door_run": "BODY"}
    assert res["asil"]["escalation"] is True
    assert res["coverage_gap"]["available"] is True
    assert res["audit_path"]
    # 실패는 감추지 않는다 — message + per-target status
    assert "일부 문서 생성에 실패" in (loaded["message"] or "")
    assert "SITS" in (loaded["message"] or "")
    assert res["actions"]["sits"]["status"] == "failed"
