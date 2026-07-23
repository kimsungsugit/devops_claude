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


def _mock_ok_run(monkeypatch, impact_jobs_mod):
    monkeypatch.setattr(
        impact_jobs_mod,
        "run_impact_update",
        lambda trigger, options=None, on_progress=None: {"ok": True, "trigger": trigger.to_dict()},
    )


def test_start_impact_job_stamps_build_and_revision_into_job_metadata(tmp_path, monkeypatch):
    """빌드/리비전이 잡 최상위 metadata로 승격된다 — 완료 전에도 조회 가능해야 한다.

    과거엔 result.trigger.metadata 안에만 있어 completed 이후에만 '어느 빌드의 것인지' 알 수
    있었다. 이력 목록은 queued/running/failed 잡도 라벨링해야 하므로 생성 시점 스탬프가 필요하다.
    """
    from workflow import impact_jobs
    from workflow.change_trigger import ChangeTrigger

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")
    _mock_ok_run(monkeypatch, impact_jobs)

    created = impact_jobs.start_impact_job(ChangeTrigger(
        trigger_type="jenkins", scm_id="hdpdm01", source_root=str(tmp_path / "src"),
        scm_type="svn", base_ref="527", changed_files=["a.c"], dry_run=True, targets=["uds"],
        metadata={
            "source": "api/jenkins/impact/trigger-async",
            "build_number": 412, "job_url": "http://jenkins/job/PDS/",
            "build_revision": "1042", "baseline_revision": "527",
            "changed_files_source": "svn_revision_range",
            "linkage_reason": "svn diff --summarize -r 527:1042",
        },
    ))

    meta = created["job"]["metadata"]  # 생성 직후 스냅샷 = 완료 전 시점
    assert meta["build_number"] == 412
    assert meta["build_revision"] == "1042"
    assert meta["baseline_revision"] == "527"
    assert meta["changed_files_source"] == "svn_revision_range"
    assert meta["job_url"] == "http://jenkins/job/PDS/"
    assert meta["linkage_reason"] == "svn diff --summarize -r 527:1042"
    assert meta["base_ref"] == "527"  # 기존 필드 보존(회귀 방지)
    assert meta["source_root"] == str(tmp_path / "src")
    _wait_for_job(impact_jobs, created["job_id"], timeout=10)


def test_link_metadata_excludes_zero_build_and_snapshot_noise(tmp_path, monkeypatch):
    """로컬 트리거의 build_number=0은 링크로 인정하지 않고, snapshot 같은 대용량 키는 복사하지 않는다.

    0을 그대로 실으면 프론트가 '빌드 #0'으로 오표시한다. snapshot(change_trigger.py:70이 넣는
    전체 파일 목록)을 통째로 복사하면 잡 JSON이 매 실행마다 비대해진다.
    """
    from workflow import impact_jobs
    from workflow.change_trigger import ChangeTrigger

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")
    _mock_ok_run(monkeypatch, impact_jobs)

    created = impact_jobs.start_impact_job(ChangeTrigger(
        trigger_type="local", scm_id="hdpdm01", source_root=str(tmp_path / "src"),
        scm_type="svn", base_ref="", changed_files=["a.c"], dry_run=True, targets=["uds"],
        metadata={"build_number": 0, "snapshot": {"changed_files": ["x"] * 500}},
    ))

    meta = created["job"]["metadata"]
    assert "build_number" not in meta  # 0 → '빌드 #0' 오표시 방지
    assert "snapshot" not in meta      # 잡 JSON 비대화 방지
    _wait_for_job(impact_jobs, created["job_id"], timeout=10)


def test_summarize_job_drops_result_body_but_keeps_counts_and_link_metadata():
    """이력 투영은 result 본문을 빼고 규모 카운트만 남긴다(목록 응답 폭주 방지)."""
    from workflow import impact_jobs

    job = {
        "job_id": "impact_x", "scm_id": "hdpdm01", "status": "completed", "stage": "done",
        "trigger_type": "jenkins", "dry_run": False, "targets": ["uds"],
        "message": "완료되었습니다.", "created_at": "t0", "updated_at": "t1",
        "started_at": "t0", "finished_at": "t1", "error": None,
        "metadata": {"build_number": 412, "build_revision": "1042"},
        "result": {
            # 실제 orchestrator result의 shape — 영향 함수는 'impact' hop 버킷에 들어 있고
            # 'impacted_functions'는 audit_payload에만 있는 키다(픽스처를 지어내면 fake-green).
            "trigger": {"changed_files": ["a.c", "b.c"]},
            "changed_function_types": {"f1": "BODY", "f2": "SIGNATURE"},
            "impact": {
                "direct": ["f1"],
                "indirect_1hop": ["f2", "f3"],
                "indirect_2hop": ["f2"],  # 버킷 간 중복 — 합집합으로 세야 한다
            },
            "actions": {"uds": {"status": "completed"}, "sits": {"status": "failed"}},
            "partial_failure": True,
            "huge_payload": ["x"] * 10000,
        },
    }

    out = impact_jobs._summarize_job(job)

    assert "result" not in out  # 본문 제외가 이 투영의 존재 이유
    assert out["metadata"]["build_number"] == 412
    assert out["metadata"]["build_revision"] == "1042"
    assert out["summary"]["changed_files"] == 2
    assert out["summary"]["changed_functions"] == 2
    assert out["summary"]["impacted_functions"] == 3
    assert out["summary"]["actions"] == {"uds": "completed", "sits": "failed"}
    assert out["summary"]["partial_failure"] is True


def test_summarize_job_backfills_link_fields_from_result_trigger():
    """스탬핑 이전에 만들어진 잡도 빌드/리비전으로 라벨링된다.

    실측(2026-07-20): 기존 잡 207건은 최상위 metadata에 build_number가 없고 같은 값이
    result.trigger.metadata 안에만 있었다. backfill이 없으면 이력 드롭다운이 과거 잡을 전부
    '로컬'로 표시하고, 빌드 재사용 dedup(build_number+job_url 매칭)도 걸리지 않아 이미 분석한
    빌드를 매번 다시 돌린다.
    """
    from workflow import impact_jobs

    out = impact_jobs._summarize_job({
        "job_id": "impact_legacy", "status": "completed",
        "metadata": {"source_root": "D:/src", "base_ref": "1018"},  # 링크 필드 없음(레거시)
        "result": {
            "trigger": {
                "changed_files": ["a.c"],
                "metadata": {
                    "build_number": 122, "job_url": "http://j/job/KJPDS02_PV/",
                    "build_revision": "1063", "baseline_revision": "1018",
                    "changed_files_source": "svn_revision_range",
                },
            },
        },
    })

    assert out["metadata"]["build_number"] == 122
    assert out["metadata"]["build_revision"] == "1063"
    assert out["metadata"]["job_url"] == "http://j/job/KJPDS02_PV/"
    assert out["metadata"]["base_ref"] == "1018"       # 기존 최상위 필드 보존
    assert out["metadata"]["source_root"] == "D:/src"


def test_summarize_job_prefers_stamped_metadata_over_backfill():
    """승격된 값이 result 안의 값과 다르면 승격값이 이긴다(backfill은 '없는 키만' 보충)."""
    from workflow import impact_jobs

    out = impact_jobs._summarize_job({
        "job_id": "impact_x", "status": "completed",
        "metadata": {"build_number": 500, "build_revision": "9999"},
        "result": {"trigger": {"metadata": {"build_number": 122, "build_revision": "1063"}}},
    })

    assert out["metadata"]["build_number"] == 500
    assert out["metadata"]["build_revision"] == "9999"


def test_summarize_job_tolerates_missing_result_and_projects_error():
    """queued(result=None)와 failed(error) 잡도 목록에서 깨지지 않고 사유를 보여준다."""
    from workflow import impact_jobs

    queued = impact_jobs._summarize_job({
        "job_id": "impact_q", "status": "queued", "metadata": {"build_number": 7}, "result": None,
    })
    assert queued["summary"] == {}
    assert queued["metadata"]["build_number"] == 7

    failed = impact_jobs._summarize_job({
        "job_id": "impact_f", "status": "failed", "result": None,
        "error": {"code": "run_lock_active", "title": "이미 실행 중", "detail": "x" * 5000},
    })
    assert failed["error"] == {"code": "run_lock_active", "title": "이미 실행 중"}
    assert "detail" not in failed["error"]  # 장문 detail은 목록에 싣지 않는다


def test_list_job_summaries_labels_history_by_build_and_revision(tmp_path, monkeypatch):
    """e2e: 트리거 → 이력 요약이 빌드/리비전으로 라벨링된다(프론트 이력 드롭다운 계약).

    이 계약이 깨지면 이력 드롭다운이 '어느 빌드인지' 못 보여준다 — 레이어별 단위테스트만으로는
    잡히지 않아 트리거→목록까지 한 번에 확인한다.
    """
    from workflow import impact_jobs
    from workflow.change_trigger import ChangeTrigger

    monkeypatch.setattr(impact_jobs, "JOB_DIR", tmp_path / "jobs")
    _mock_ok_run(monkeypatch, impact_jobs)

    for build_number, revision in ((410, "1030"), (412, "1042")):
        created = impact_jobs.start_impact_job(ChangeTrigger(
            trigger_type="jenkins", scm_id="hdpdm01", source_root=str(tmp_path / "src"),
            scm_type="svn", base_ref="527", changed_files=["a.c"], dry_run=True, targets=["uds"],
            metadata={
                "build_number": build_number, "build_revision": revision,
                "baseline_revision": "527", "changed_files_source": "svn_revision_range",
            },
        ))
        _wait_for_job(impact_jobs, created["job_id"], timeout=10)

    items = impact_jobs.list_job_summaries(scm_id="hdpdm01", limit=10)

    assert len(items) == 2
    labelled = {(i["metadata"]["build_number"], i["metadata"]["build_revision"]) for i in items}
    assert labelled == {(410, "1030"), (412, "1042")}
    assert all(i["status"] == "completed" for i in items)
    assert all("result" not in i for i in items)
    # 다른 SCM의 이력이 섞이지 않는다(오귀속 방지)
    assert impact_jobs.list_job_summaries(scm_id="kjpds02", limit=10) == []


def test_find_latest_job_file_matches_slug_and_picks_latest(tmp_path, monkeypatch):
    # 파일명만으로 slug 매칭 + 타임스탬프 최신을 고른다(본문 파싱 없이 후보 선별).
    from workflow import impact_jobs

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(impact_jobs, "JOB_DIR", jobs)
    slug = "http_192_168_110_40_7000_job_KJPDS02_PV"

    def _touch(name):
        (jobs / name).write_text("{}", encoding="utf-8")

    _touch(f"job_impact_20260101_000000_{slug}_old00001.json")
    _touch(f"job_impact_20260720_101010_{slug}_new00001.json")
    # 다른 slug는 타임스탬프가 더 나중이어도 매칭 안 됨(오귀속 방지).
    _touch("job_impact_20260721_000000_http_other_job_HDPDM01_zzz00001.json")
    _touch("job_notimpact.json")  # 규격 외 파일명 — glob(job_impact_*)에서 제외.

    latest = impact_jobs.find_latest_job_file(slug)
    assert latest is not None
    assert latest.name == f"job_impact_20260720_101010_{slug}_new00001.json"


def test_find_latest_job_file_no_match_or_empty_returns_none(tmp_path, monkeypatch):
    from workflow import impact_jobs

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(impact_jobs, "JOB_DIR", jobs)
    (jobs / "job_impact_20260720_101010_http_other_slug_aaa00001.json").write_text("{}", encoding="utf-8")
    assert impact_jobs.find_latest_job_file("http_192_168_110_40_7000_job_KJPDS02_PV") is None
    assert impact_jobs.find_latest_job_file("") is None  # 빈 scm_id 방어(오매칭 차단)


def test_find_job_files_by_scm_returns_newest_first(tmp_path, monkeypatch):
    # 리스트 변형: slug 매칭 파일을 타임스탬프 내림차순으로 상위 N개(가용성 폴백용).
    from workflow import impact_jobs

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(impact_jobs, "JOB_DIR", jobs)
    slug = "http_x_job_A"
    for ts, uid in [("20260101_000000", "aaa00001"), ("20260720_101010", "bbb00001"), ("20260315_120000", "ccc00001")]:
        (jobs / f"job_impact_{ts}_{slug}_{uid}.json").write_text("{}", encoding="utf-8")
    files = impact_jobs.find_job_files_by_scm(slug, limit=2)
    assert [f.name for f in files] == [
        f"job_impact_20260720_101010_{slug}_bbb00001.json",
        f"job_impact_20260315_120000_{slug}_ccc00001.json",
    ]
    assert impact_jobs.find_job_files_by_scm("", limit=5) == []  # 빈 scm_id 방어
