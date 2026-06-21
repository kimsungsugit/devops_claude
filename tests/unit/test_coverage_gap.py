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
