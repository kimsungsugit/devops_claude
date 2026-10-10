"""workflow/coverage_gap.py — 영향 함수 커버리지 ASIL 타깃 대비 gap + 이력 delta."""
from __future__ import annotations


def _rag():
    return {"vcast_summary": {"ut_metrics": {"entries": [
        {"unit": "U", "subprogram": "Ap_Door_Run",
         "statements": {"covered": 10, "total": 10, "rate": 1.0},
         "branches": {"covered": 8, "total": 10, "rate": 0.8},
         "pairs": {"covered": 17, "total": 20, "rate": 0.85}},
        {"unit": "U", "subprogram": "Ap_Helper(void)",
         "statements": {"covered": 5, "total": 5, "rate": 1.0},
         "branches": {"covered": 5, "total": 5, "rate": 1.0},
         "pairs": {"covered": 5, "total": 5, "rate": 1.0}},
    ]}}}


def test_coverage_gap_target_metric_per_asil(tmp_path, monkeypatch):
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = _rag()
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    res = coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run", "Ap_Helper", "Ap_NotTested"],
        {"Ap_Door_Run": "D", "Ap_Helper": "QM", "Ap_NotTested": "B"},
        ["fake.json"], cache_root=str(tmp_path), scm_id="x", update_baseline=True,
    )
    assert res["available"] is True
    byfn = {r["function"]: r for r in res["functions"]}
    # ASIL D → MC/DC 타깃, 0.85 < 1.0 → 미달
    assert byfn["Ap_Door_Run"]["target_metric"] == "mcdc"
    assert byfn["Ap_Door_Run"]["meets_target"] is False
    # ASIL QM → statement 타깃, 1.0 → 충족 (서명 'Ap_Helper(void)'도 정규화 매칭)
    assert byfn["Ap_Helper"]["target_metric"] == "statement"
    assert byfn["Ap_Helper"]["meets_target"] is True
    # 시험 안 된 영향 함수는 커버리지 행 없음
    assert "Ap_NotTested" not in byfn
    assert res["summary"]["below_target"] == 1
    assert res["summary"]["had_baseline"] is False


def test_coverage_gap_historical_delta_regression(tmp_path, monkeypatch):
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = _rag()
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    # 1회차: baseline 스냅샷 기록
    coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run"], {"Ap_Door_Run": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=True,
    )
    # 2회차: MC/DC가 0.85 → 0.70로 하락 → delta 음수 + regressed
    rag["vcast_summary"]["ut_metrics"]["entries"][0]["pairs"]["rate"] = 0.70
    res2 = coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run"], {"Ap_Door_Run": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=True,
    )
    d = res2["functions"][0]
    assert d["delta"] is not None and d["delta"] < 0
    assert res2["summary"]["regressed"] == 1
    assert res2["summary"]["had_baseline"] is True


def test_coverage_gap_unmatched_safety_not_silently_passed(tmp_path, monkeypatch):
    """커버리지에 매칭 안 되는 ASIL C/D 영향 함수는 below_target=0 위장이 아니라 unmatched_safety로 노출(C1/X7)."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = _rag()  # Ap_Door_Run, Ap_Helper만 보유
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    res = coverage_gap.compute_coverage_gap(
        ["Ap_Unseen"], {"Ap_Unseen": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=False,
    )
    assert res["available"] is True
    assert res["summary"]["below_target"] == 0
    assert res["summary"]["unmatched"] == 1
    assert res["summary"]["unmatched_safety"] == 1   # ASIL D 미측정 노출(안전 통과 위장 아님)
    assert res["functions"] == []


def test_coverage_gap_unknown_asil_not_statement_passed(tmp_path, monkeypatch):
    """ASIL 미상 함수는 statement(최저 기준)로 위장 평가하지 않고 meets_target=False로 노출(W1)."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = _rag()
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    res = coverage_gap.compute_coverage_gap(
        ["Ap_Helper"], {"Ap_Helper": ""}, ["fake.json"],   # ASIL 미상(statement는 100%)
        cache_root=str(tmp_path), scm_id="x", update_baseline=False,
    )
    r = res["functions"][0]
    assert r["target_metric"] == "unknown"
    assert r["meets_target"] is False   # statement 100%여도 위장 충족 금지
    assert r.get("asil_unknown") is True
    assert res["summary"]["unknown_asil"] == 1


def test_coverage_gap_no_data_available_false(tmp_path, monkeypatch):
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: {})
    res = coverage_gap.compute_coverage_gap(
        ["foo"], {"foo": "D"}, ["x.json"], cache_root=str(tmp_path), scm_id="x",
    )
    assert res["available"] is False
    assert res["functions"] == []


def test_coverage_gap_matched_but_metric_unmeasured(tmp_path, monkeypatch):
    """매칭됐으나 ASIL 타깃 메트릭(MC/DC)이 미측정(rate=None)인 ASIL D 함수는 '목표 미달(실패)'이
    아니라 '미측정(증거 부재)'으로 분리돼야 한다 — below_target=0, unmeasured/unmeasured_safety로 집계."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = {"vcast_summary": {"ut_metrics": {"entries": [
        {"unit": "U", "subprogram": "Ap_NoMcdc",
         "statements": {"covered": 10, "total": 10, "rate": 1.0},
         "branches": {"covered": 10, "total": 10, "rate": 1.0},
         "pairs": {"covered": 0, "total": 0, "rate": None}},   # MC/DC 컬럼 없음 → 미측정
    ]}}}
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    res = coverage_gap.compute_coverage_gap(
        ["Ap_NoMcdc"], {"Ap_NoMcdc": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=False,
    )
    assert res["available"] is True
    r = res["functions"][0]
    assert r["target_metric"] == "mcdc"
    assert r["current_rate"] is None
    assert r["meets_target"] is False
    assert r["unmeasured_target"] is True          # 미측정 플래그(증거 부재)
    s = res["summary"]
    assert s["below_target"] == 0                   # 실패로 집계 안 됨
    assert s["unmeasured"] == 1
    assert s["unmeasured_safety"] == 1              # ASIL D
    assert s["unmatched"] == 0                       # 매칭은 됨(미매칭 아님)


def test_coverage_gap_same_revision_baseline_flagged(tmp_path, monkeypatch):
    """같은 빌드를 재분석하면 baseline이 자기 자신 → delta=0. '회귀 없음'이 아니라 '비교 불가'."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = _rag()
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    # 1회차: build 1053 스냅샷 기록
    r1 = coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run"], {"Ap_Door_Run": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=True, build_revision="1053",
    )
    assert r1["summary"]["baseline_same_revision"] is False  # 최초엔 baseline 없음
    # 2회차: 같은 빌드(1053) 재분석 → Δ 비교 불가로 표면화
    r2 = coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run"], {"Ap_Door_Run": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=True, build_revision="1053",
    )
    assert r2["summary"]["baseline_same_revision"] is True
    assert r2["summary"]["baseline_revision"] == "1053"


def test_coverage_gap_older_build_does_not_overwrite_baseline(tmp_path, monkeypatch):
    """더 오래된 빌드 분석이 baseline을 과거로 되돌리지 않는다(Δ 기준 훼손 방지)."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    rag = _rag()
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", lambda p: rag)
    coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run"], {"Ap_Door_Run": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=True, build_revision="1053",
    )
    # 과거 빌드(1000)를 나중에 분석 → baseline revision은 1053 유지
    coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run"], {"Ap_Door_Run": "D"}, ["fake.json"],
        cache_root=str(tmp_path), scm_id="x", update_baseline=True, build_revision="1000",
    )
    _funcs, meta = coverage_gap._read_baseline(str(tmp_path), "x")
    assert meta.get("revision") == "1053"


def test_coverage_gap_collision_worst_copy_not_masked(tmp_path, monkeypatch):
    """이름충돌(동명 다른 함수)을 전역 max로 병합하면 최선 copy가 최악 copy의 gap을 은폐한다
    (ISO 26262 구조 커버리지 under-report). collision_names를 주면 worst-copy(min) rate를 노출해
    변경 copy를 특정 못 해도 gap을 재검증 대상에 남긴다."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    # 같은 함수명 writeblock이 서로 다른 unit에 다른 copy로: APP 60% / BOOT 100% (대소문자까지 다름).
    def _rag_of(p):
        if p == "APP":
            return {"vcast_summary": {"ut_metrics": {"entries": [
                {"unit": "EEPROM_APP", "subprogram": "writeblock",
                 "statements": {"rate": 0.6}, "branches": {"rate": 0.6}, "pairs": {"rate": 0.6}}]}}}
        return {"vcast_summary": {"ut_metrics": {"entries": [
            {"unit": "EEPROM_BOOT", "subprogram": "WriteBlock",
             "statements": {"rate": 1.0}, "branches": {"rate": 1.0}, "pairs": {"rate": 1.0}}]}}}
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", _rag_of)

    # collision_names 미전달(구 동작) → 전역 max(100%) → ASIL D가 '충족'으로 위장(버그 재현).
    res_masked = coverage_gap.compute_coverage_gap(
        ["writeblock"], {"writeblock": "D"}, ["APP", "BOOT"],
        cache_root=str(tmp_path), scm_id="c", update_baseline=False)
    assert res_masked["functions"][0]["meets_target"] is True

    # collision_names 전달(fix) → worst-copy(min 0.6) → ASIL D 미달 노출.
    res_fix = coverage_gap.compute_coverage_gap(
        ["writeblock"], {"writeblock": "D"}, ["APP", "BOOT"],
        cache_root=str(tmp_path), scm_id="c", update_baseline=False,
        collision_names={"writeblock"})
    r0 = res_fix["functions"][0]
    assert r0["current_rate"] == 0.6
    assert r0["meets_target"] is False
    assert r0["collision_worst_copy"] is True
    assert res_fix["summary"]["collision_worst_copy"] == 1


def test_coverage_gap_noncollision_keeps_best_evidence(tmp_path, monkeypatch):
    """충돌 fix가 정상 함수를 낮추지 않는다 — 같은 unit의 UT/IT는 여전히 max(최선 증거).
    함수명이 collision_names에 있어도 단일 unit이면 worst-copy로 접지 않는다(false gap 방지)."""
    import backend.routers.jenkins as jk
    from workflow import coverage_gap

    def _rag_of(p):
        # 같은 unit(MOD)의 UT(80%)와 IT(95%) = 동일 함수의 두 측정 → max(95%)가 최선 증거.
        if p == "UT":
            return {"vcast_summary": {"ut_metrics": {"entries": [
                {"unit": "MOD", "subprogram": "foo", "branches": {"rate": 0.8}}]}}}
        return {"vcast_summary": {"it_metrics": {"entries": [
            {"unit": "MOD", "subprogram": "foo", "branches": {"rate": 0.95}}]}}}
    monkeypatch.setattr(jk, "_load_vectorcast_rag_from_cloudium", _rag_of)
    res = coverage_gap.compute_coverage_gap(
        ["foo"], {"foo": "B"}, ["UT", "IT"],
        cache_root=str(tmp_path), scm_id="n", update_baseline=False,
        collision_names={"foo"})
    r0 = res["functions"][0]
    assert r0["current_rate"] == 0.95           # 같은 unit UT/IT는 max
    assert r0["collision_worst_copy"] is False  # 단일 unit → worst-copy 접힘 없음
    assert res["summary"]["collision_worst_copy"] == 0
