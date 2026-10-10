"""프로젝트 요약 탭 — 빌드별 변경 영향 타임라인(build_timeline) + change-log 빌드 주소화.

⚠ impact 테스트는 동기·단독 실행 규약(_RUN_FILE_LOCK import-시점 바인딩) — 병렬 시 유령 실패.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


def _record(
    *,
    run_id,
    scm_id="kj",
    build_number=None,
    build_revision=None,
    changed_types=None,
    function_meta=None,
    actions=None,
    asil=None,
    coverage=None,
    impact=None,
    changed_files=None,
):
    from workflow import impact_changes

    metadata = {}
    if build_number is not None:
        metadata["build_number"] = build_number
    if build_revision is not None:
        metadata["build_revision"] = build_revision
        metadata["baseline_revision"] = "1018"
    return impact_changes.build_change_log(
        run_id=run_id,
        trigger={
            "scm_id": scm_id,
            "trigger_type": "jenkins",
            "base_ref": "1018",
            "changed_files": changed_files or [],
            "metadata": metadata,
        },
        result={
            "changed_function_types": changed_types or {},
            "function_meta": function_meta or {},
            "actions": actions or {},
            "asil": asil or {},
            "coverage_gap": coverage or {},
            "impact": impact or {},
        },
        previous_linked_docs={},
    )


# --------------------------------------------------------------------------- #
# 2a. change-log 빌드 주소화 (additive)
# --------------------------------------------------------------------------- #
def test_build_change_log_adds_build_addressing_and_safety_rollup():
    cl = _record(
        run_id="impact_20260324_120000",
        build_number=124,
        build_revision="1053",
        changed_types={"door_run": "SIGNATURE", "door_init": "BODY"},
        function_meta={
            "door_run": {"asil": "ASIL C"},
            "door_init": {"asil": "A"},
            "unrelated": {"asil": "D"},  # 변경 함수 아님 → changed_function_asil 제외
        },
        actions={
            "uds": {"mode": "AUTO", "status": "completed", "functions": ["door_run"], "function_count": 1},
            "sds": {"mode": "FLAG", "status": "review_required", "functions": ["door_run"], "function_count": 1},
        },
        asil={"max_changed": "ASIL C", "mcdc_required": True, "unknown_changed_count": 2},
        coverage={"available": True, "summary": {"regressed": 1, "unmatched_safety": 0, "unmeasured_safety": 2}},
        impact={"direct": ["door_run"], "indirect_1hop": ["helper"], "indirect_2hop": []},
    )
    # 신규 additive 키
    assert cl["build_number"] == 124
    assert cl["build_revision"] == "1053"
    assert cl["baseline_revision"] == "1018"
    assert cl["max_asil"] == "ASIL C"
    assert cl["mcdc_required"] is True
    assert cl["asil_unknown_count"] == 2
    assert cl["changed_function_asil"] == {"door_run": "ASIL C", "door_init": "A"}
    assert cl["actions_rollup"]["auto"] == 1
    assert cl["actions_rollup"]["flag"] == 1
    assert cl["actions_rollup"]["doc_modes"] == {"uds": "AUTO", "sds": "FLAG"}
    assert cl["coverage_gap_summary"] == {"measured": True, "regressed": 1, "unmatched_safety": 0, "unmeasured_safety": 2}
    assert cl["partial_failure"] is False
    # 기존 키 불변(회귀 방지)
    assert cl["changed_functions"] == {"door_init": "BODY", "door_run": "SIGNATURE"}
    assert "summary" in cl and "documents" in cl and "impact_counts" in cl
    assert cl["impact_counts"] == {"direct": 1, "indirect_1hop": 1, "indirect_2hop": 0}


def test_build_change_log_additive_defaults_when_metadata_and_asil_missing():
    """metadata/asil 부재 프로젝트도 크래시 없이 graceful default."""
    cl = _record(
        run_id="impact_x",
        changed_types={"foo": "BODY"},
        actions={"uds": {"mode": "AUTO", "status": "completed"}},
    )
    assert cl["build_number"] is None
    assert cl["build_revision"] is None
    assert cl["max_asil"] is None
    assert cl["mcdc_required"] is False
    assert cl["asil_unknown_count"] == 0
    assert cl["changed_function_asil"] == {}  # function_meta 없음
    assert cl["actions_rollup"]["auto"] == 1
    # coverage_gap 미제공 → measured False(증거부재를 '측정 후 0'과 구분 — ISO 정직성)
    assert cl["coverage_gap_summary"] == {"measured": False, "regressed": 0, "unmatched_safety": 0, "unmeasured_safety": 0}


# --------------------------------------------------------------------------- #
# 2b. build_timeline (join + rollup)
# --------------------------------------------------------------------------- #
def test_build_timeline_join_and_cumulative_rollup(tmp_path, monkeypatch):
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")

    # 최신(A, build 124) — door_run(ASIL C 시그니처)·door_init(A)
    a = _record(
        run_id="impact_20260324_120000",
        build_number=124, build_revision="1053",
        changed_types={"door_run": "SIGNATURE", "door_init": "BODY"},
        function_meta={"door_run": {"asil": "ASIL C"}, "door_init": {"asil": "A"}},
        actions={"uds": {"mode": "AUTO", "status": "completed"}, "sds": {"mode": "FLAG", "status": "review_required"}},
        asil={"max_changed": "ASIL C", "mcdc_required": True, "unknown_changed_count": 0},
        coverage={"available": True, "summary": {"regressed": 1}},
        impact={"direct": ["door_run"], "indirect_1hop": ["helper"]},
        changed_files=["Sources/APP/Ap_Door.c"],
    )
    # 이전(B, build 123) — door_run(중복)·motor_ctrl(D 신규)
    b = _record(
        run_id="impact_20260324_110000",
        build_number=123, build_revision="1050",
        changed_types={"door_run": "BODY", "motor_ctrl": "NEW"},
        function_meta={"door_run": {"asil": "ASIL C"}, "motor_ctrl": {"asil": "D"}},
        actions={"uds": {"mode": "AUTO", "status": "completed"}},
        asil={"max_changed": "ASIL D", "mcdc_required": True, "unknown_changed_count": 0},
        coverage={"available": True, "summary": {"regressed": 0}},
        impact={"direct": ["motor_ctrl"]},
        changed_files=["Sources/APP/Ap_Motor.c"],
    )
    impact_changes.write_change_log(a)
    impact_changes.write_change_log(b)

    data = impact_changes.build_timeline("kj", limit=50)
    rows = data["rows"]
    rollup = data["rollup"]

    # 최신순 정렬(A=124 먼저)
    assert [r["build_number"] for r in rows] == [124, 123]
    assert rows[0]["max_asil_bucket"] == "C"
    assert rows[0]["auto_docs"] == 1 and rows[0]["flag_docs"] == 1
    assert rows[0]["coverage_regressed"] == 1
    assert rows[0]["coverage_measured"] is True
    assert rows[1]["max_asil_bucket"] == "D"

    # 누적 롤업
    assert rollup["analyzed_build_count"] == 2
    # distinct 함수 union = {door_run, door_init, motor_ctrl}
    assert rollup["distinct_changed_functions"] == 3
    assert rollup["distinct_changed_files"] == 2
    assert rollup["cumulative_auto_docs"] == 2
    assert rollup["cumulative_flag_docs"] == 1
    assert rollup["cumulative_coverage_regressed"] == 1
    assert rollup["mcdc_required_any"] is True
    # ASIL 분포(distinct-함수, 충돌 max): door_run=C, door_init=A, motor_ctrl=D
    assert rollup["asil_distribution"] == {"D": 1, "C": 1, "B": 0, "A": 1, "QM": 0, "unknown": 0}
    assert rollup["revision_range"] == {"base_ref": "1018", "min_build_revision": 1050, "max_build_revision": 1053}


def test_build_timeline_empty_history(tmp_path, monkeypatch):
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    data = impact_changes.build_timeline("kj", limit=50)
    assert data["rows"] == []
    assert data["rollup"]["analyzed_build_count"] == 0
    assert data["rollup"]["distinct_changed_functions"] == 0
    assert data["rollup"]["revision_range"]["min_build_revision"] is None


def test_build_timeline_durable_old_record_without_build_addressing(tmp_path, monkeypatch):
    """빌드 주소화 이전 구 레코드도 행 생성 + distinct union은 changed_functions 이름으로 보강."""
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    old = {
        "run_id": "impact_20250101_000000",
        "timestamp": "2025-01-01T00:00:00",
        "scm_id": "kj",
        "changed_files": ["legacy.c"],
        "changed_functions": {"legacy_fn": "BODY"},  # build_number/changed_function_asil 없음
        "summary": {},
    }
    impact_changes.write_change_log(old)
    data = impact_changes.build_timeline("kj", limit=50)
    assert len(data["rows"]) == 1
    assert data["rows"][0]["build_number"] is None
    assert data["rows"][0]["changed_functions_count"] == 1
    # 증거부재≠QM → unknown 버킷
    assert data["rollup"]["distinct_changed_functions"] == 1
    assert data["rollup"]["asil_distribution"]["unknown"] == 1
    assert data["rollup"]["asil_distribution"]["QM"] == 0


def test_build_timeline_coverage_measured_distinguishes_unmeasured(tmp_path, monkeypatch):
    """coverage_gap available=False(vcast 미연결)면 row.coverage_measured=False → 프론트가
    '정상' 대신 '커버리지 미측정' 표시(증거부재≠충족, ISO 정직성 — reviewer Critical #1)."""
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    unmeasured = _record(
        run_id="impact_20260324_120000", build_number=200, build_revision="1060",
        changed_types={"f": "BODY"}, coverage={"available": False},
    )
    measured_clean = _record(
        run_id="impact_20260324_110000", build_number=199, build_revision="1059",
        changed_types={"g": "BODY"}, coverage={"available": True, "summary": {"regressed": 0}},
    )
    impact_changes.write_change_log(unmeasured)
    impact_changes.write_change_log(measured_clean)
    rows = impact_changes.build_timeline("kj", limit=50)["rows"]
    by_build = {r["build_number"]: r for r in rows}
    assert by_build[200]["coverage_measured"] is False  # 미측정 → '정상' 위장 금지
    assert by_build[199]["coverage_measured"] is True   # 측정 후 회귀 0 → 진짜 정상


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ASIL C", "C"),
        ("C", "C"),
        ("ASIL D", "D"),
        ("QM", "QM"),
        ("qm", "QM"),
        ("TBD", "unknown"),
        ("", "unknown"),
        ("-", "unknown"),
        ("UNKNOWN", "unknown"),
        (None, "unknown"),
    ],
)
def test_norm_asil_bucket(value, expected):
    from workflow.impact_changes import _norm_asil_bucket

    assert _norm_asil_bucket(value) == expected


def test_asil_rank_max_merge_keeps_higher():
    """충돌 시 실제 등급이 QM/미상을 이긴다(안전측 max)."""
    from workflow.impact_changes import _asil_rank

    assert _asil_rank("ASIL D") > _asil_rank("ASIL A")
    assert _asil_rank("A") > _asil_rank("QM")
    assert _asil_rank("QM") == _asil_rank("") == 0


# --------------------------------------------------------------------------- #
# 2c. GET /api/scm/build-timeline/{entry_id}
# --------------------------------------------------------------------------- #
def test_scm_build_timeline_endpoint(tmp_path, monkeypatch):
    from backend.routers import scm
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    monkeypatch.setattr(scm, "get_registry_entry", lambda eid: {"id": eid} if eid == "kj" else None)

    impact_changes.write_change_log(
        _record(
            run_id="impact_20260324_120000",
            build_number=124, build_revision="1053",
            changed_types={"door_run": "SIGNATURE"},
            function_meta={"door_run": {"asil": "ASIL C"}},
            actions={"uds": {"mode": "AUTO", "status": "completed"}},
            asil={"max_changed": "ASIL C", "mcdc_required": True, "unknown_changed_count": 0},
        )
    )

    # job_url 없이 → Jenkins 보강 skip, change-log 타임라인만
    resp = scm.scm_build_timeline("kj", limit=50, job_url="")
    assert resp["ok"] is True
    assert resp["entry_id"] == "kj"
    assert len(resp["rows"]) == 1
    assert resp["rows"][0]["build_number"] == 124
    assert "build_result" not in resp["rows"][0]  # 보강 안 함
    assert resp["enrich_note"] == ""
    assert resp["rollup"]["distinct_changed_functions"] == 1


def test_scm_build_timeline_endpoint_404_unknown_entry(monkeypatch):
    from backend.routers import scm

    monkeypatch.setattr(scm, "get_registry_entry", lambda eid: None)
    with pytest.raises(HTTPException) as exc:
        scm.scm_build_timeline("nope")
    assert exc.value.status_code == 404


def test_scm_build_timeline_cache_merge(tmp_path, monkeypatch):
    """cache_root(opt-in) 전달 시 로컬 캐시 빌드가 병합된다 — Jenkins 무의존(Phase E).

    분석된 빌드(124)는 cached 주석만, 미분석 캐시 빌드(125)는 analyzed:false+cached:true 행.
    """
    from backend.routers import scm
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    monkeypatch.setattr(scm, "get_registry_entry", lambda eid: {"id": eid})
    impact_changes.write_change_log(
        _record(run_id="impact_20260324_120000", build_number=124, build_revision="1053",
                changed_types={"foo": "BODY"}, actions={"uds": {"mode": "AUTO", "status": "completed"}})
    )
    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: [
            {"build_number": 125, "result": "SUCCESS", "timestamp_iso": "2026-07-24T13:00:11", "revision": "1075"},
            {"build_number": 124, "result": "SUCCESS", "timestamp_iso": "2026-07-22T13:00:00", "revision": "1053"},
        ],
    )
    resp = scm.scm_build_timeline("kj", limit=50, job_url="http://j/job/X/", cache_root=str(tmp_path))
    assert resp["cache_merge"] == {"attempted": True, "merged": 1, "added": 1}
    by = {r["build_number"]: r for r in resp["rows"]}
    assert by[124]["analyzed"] is True and by[124]["cached"] is True
    assert by[125]["analyzed"] is False and by[125]["cached"] is True
    assert by[125]["build_revision"] == "1075" and by[125]["build_result"] == "SUCCESS"
    assert by[125]["coverage_measured"] is False  # 미측정을 정상으로 위장하지 않음
    # 정렬: 최신(125) 먼저
    assert [r["build_number"] for r in resp["rows"]] == [125, 124]


def test_scm_build_timeline_no_cache_root_keeps_legacy_shape(tmp_path, monkeypatch):
    """cache_root 미전달 → 기존 동작 100%(cache_merge.attempted=False, 행 추가 없음)."""
    from backend.routers import scm
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    monkeypatch.setattr(scm, "get_registry_entry", lambda eid: {"id": eid})
    resp = scm.scm_build_timeline("kj", limit=50, job_url="")
    assert resp["cache_merge"] == {"attempted": False, "merged": 0, "added": 0}
    assert resp["rows"] == []


def test_scm_build_timeline_ssrf_fail_closed(tmp_path, monkeypatch):
    """job_url이 서버 baseUrl 하위가 아니면 서버 토큰을 싣지 않고 note로 고지(SSRF 차단)."""
    from backend.routers import scm
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    monkeypatch.setattr(scm, "get_registry_entry", lambda eid: {"id": eid})
    impact_changes.write_change_log(
        _record(run_id="impact_20260324_120000", build_number=124, build_revision="1053",
                changed_types={"foo": "BODY"}, actions={"uds": {"mode": "AUTO", "status": "completed"}})
    )
    # baseUrl은 다른 호스트 → job_url이 하위 아님 → 보강 미수행
    monkeypatch.setattr(
        "backend.routers.config.get_jenkins_config",
        lambda: {"baseUrl": "http://ci.example.com", "username": "u", "token": "t", "verifyTls": True},
    )
    resp = scm.scm_build_timeline("kj", limit=50, job_url="http://evil.internal/steal", include_all=True)
    assert "SSRF" in resp["enrich_note"]
    assert "build_result" not in resp["rows"][0]
