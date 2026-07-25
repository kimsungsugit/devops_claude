"""test_design_advisor — 기법 매핑·ASIL 조인·미측정≠미달·band_missing 억제·접미사 정규화."""
from __future__ import annotations

from workflow.test_design_advisor import (
    TECHNIQUE_CATALOG,
    build_coverage_rows,
    compute_design_test_gap,
    derive_technique_recommendations,
    normalize_related_id,
)


def _e(name, st_cov, st_tot, br_cov, br_tot, ccn=5, unit="a.c"):
    return {"unit": unit, "subprogram": name, "ccn": ccn,
            "statements": {"covered": st_cov, "total": st_tot},
            "branches": {"covered": br_cov, "total": br_tot}}


# ── normalize / rows ────────────────────────────────────────────────────────

def test_normalize_related_id_variants():
    assert normalize_related_id("SwUFn_012 (3 TC)") == "SwUFn_012"
    assert normalize_related_id("g_SysOptionCtrl (14 TC)") == "g_SysOptionCtrl"
    assert normalize_related_id("  plain_fn  ") == "plain_fn"
    assert normalize_related_id(None) == ""


def test_build_rows_asil_join_and_mcdc_unmeasured():
    rows = build_coverage_rows(
        [_e("Safe_Fn", 5, 10, 1, 4), _e("plain_fn", 8, 8, 2, 2)],
        [],
        {"Safe_Fn": "C", "other": "D"},
    )
    by = {r["function"]: r for r in rows}
    safe = by["Safe_Fn"]
    assert safe["asil"] == "C" and safe["target_metric"] == "branch"
    assert safe["statement"] == 0.5 and safe["branch"] == 0.25  # covered/total 우선(스케일 무결)
    assert safe["mcdc"] is None  # 데이터 부재 — 항상 None(정직)
    assert by["plain_fn"]["asil"] is None and by["plain_fn"]["target_metric"] is None


def test_build_rows_asil_d_is_unmeasured_target_not_fail():
    rows = build_coverage_rows([_e("d_fn", 10, 10, 4, 4)], [], {"d_fn": "D"})
    r = rows[0]
    assert r["target_metric"] == "mcdc" and r["unmeasured_target"] is True
    assert r["meets_target"] is None  # 미측정 — 충족/미달 판정 자체를 안 한다


def test_build_rows_nonstandard_asil_treated_unknown():
    rows = build_coverage_rows([_e("f", 1, 2, 1, 2)], [], {"f": "C(D)"})
    assert rows[0]["asil"] is None  # 비표준 표기는 미상 — 오분류 방지


# ── 기법 매핑 ────────────────────────────────────────────────────────────────

def test_technique_mapping_and_priority():
    rows = build_coverage_rows(
        [
            _e("zero_fn", 0, 10, 0, 4, ccn=3),                 # 미커버
            _e("mcdc_fn", 10, 10, 4, 4, ccn=8),                # ASIL D — MC/DC 미측정
            _e("complex_branch", 9, 10, 3, 6, ccn=22),         # ASIL C 분기 미달 + 고 ccn
            _e("simple_branch", 9, 10, 3, 6, ccn=4),           # 분기 미달 + 저 ccn(ASIL 미상)
            _e("stmt_gap", 9, 10, 4, 4, ccn=2),                # 구문만 미달(ASIL 미상)
            _e("clean_fn", 10, 10, 4, 4, ccn=1),               # 갭 없음 — 미포함
        ],
        [],
        {"mcdc_fn": "D", "complex_branch": "C"},
    )
    out = derive_technique_recommendations(rows)
    by = {i["function"]: i for i in out["items"]}
    assert "clean_fn" not in by
    assert by["zero_fn"]["gap_kind"] == "uncovered"
    assert by["mcdc_fn"]["gap_kind"] == "unmeasured_metric"
    assert by["mcdc_fn"]["techniques"][0] == "mcdc_measurement"
    assert "robustness" in by["mcdc_fn"]["techniques"]           # ASIL B+ 강건성 부가
    assert by["complex_branch"]["gap_kind"] == "below_target"     # 타깃(branch) 미달
    assert "decision_condition" in by["complex_branch"]["techniques"]  # ccn>=10
    assert by["simple_branch"]["gap_kind"] == "branch_gap"        # 타깃 미상 — 일반 갭 명칭
    assert "equivalence_partitioning" in by["simple_branch"]["techniques"]
    assert by["stmt_gap"]["gap_kind"] == "statement_gap"
    # 정렬: 심각도(uncovered → unmeasured → below_target …)
    kinds = [i["gap_kind"] for i in out["items"]]
    assert kinds.index("uncovered") < kinds.index("unmeasured_metric") < kinds.index("below_target")
    # basis는 수치 인용 + MC/DC 미측정 명시
    assert "구문 0%" in by["zero_fn"]["basis"] and "MC/DC 미측정" in by["mcdc_fn"]["basis"]
    s = out["summary"]
    assert s["uncovered"] == 1 and s["mcdc_unmeasured_safety"] == 1 and s["below_target"] == 1
    assert s["asil_unknown_with_gap"] == 3  # zero_fn/simple_branch/stmt_gap


def test_technique_top_n_omitted():
    rows = build_coverage_rows([_e(f"f{i}", 1, 2, 1, 2) for i in range(40)], [], {})
    out = derive_technique_recommendations(rows, top_n=10)
    assert len(out["items"]) == 10 and out["items_omitted"] == 30


# ── 설계-시험 갭 ─────────────────────────────────────────────────────────────

def _lt(links):
    return {"links": links}


def _l(rtype, rid, tid):
    return {"related_type": rtype, "related_id": rid, "target_id": tid}


def test_design_gap_normal_and_suffix_dedup():
    lt = _lt([
        _l("UDS_FUNCTION", "fn_a", "REQ-1"),
        _l("UDS_FUNCTION", "fn_b", "REQ-2"),
        _l("SUTS_TEST", "SwUTC_001", "REQ-1"),
        _l("VCAST_FUNCTION", "fn_a (3 TC)", "REQ-1"),
        _l("VCAST_FUNCTION", "fn_a (5 TC)", "REQ-1"),  # 접미사 정규화 → distinct 1
    ])
    g = compute_design_test_gap(lt)
    assert g["available"] is True
    assert g["totals"]["vcast_functions_distinct"] == 1  # " (N TC)" 정규화 병합
    assert g["band_missing"] == {"suts": False, "vcast": False}
    assert g["targets_with_uds_no_suts"] == [{"target_id": "REQ-2", "uds_count": 1}]
    assert g["targets_with_uds_no_any_test"] == [{"target_id": "REQ-2", "uds_count": 1}]


def test_design_gap_band_missing_suppresses_enumeration():
    # HDPDM01 재현: SUTS 밴드 전체 0 — 요구별 'SUTS 없음' 열거는 허위 경보라 억제.
    lt = _lt([
        _l("UDS_FUNCTION", "fn_a", "REQ-1"),
        _l("UDS_FUNCTION", "fn_b", "REQ-2"),
        _l("VCAST_FUNCTION", "fn_a", "REQ-1"),
    ])
    g = compute_design_test_gap(lt)
    assert g["band_missing"]["suts"] is True
    assert g["targets_with_uds_no_suts"] == [] and g["no_suts_suppressed"] is True
    # 존재하는 밴드(VCAST) 기준의 '어떤 시험도 없음'은 유효 — REQ-2
    assert g["targets_with_uds_no_any_test"] == [{"target_id": "REQ-2", "uds_count": 1}]


def test_design_gap_both_bands_missing_fully_suppressed():
    g = compute_design_test_gap(_lt([_l("UDS_FUNCTION", "fn_a", "REQ-1")]))
    assert g["band_missing"] == {"suts": True, "vcast": True}
    assert g["targets_with_uds_no_suts"] == [] and g["targets_with_uds_no_any_test"] == []
    assert g["no_any_suppressed"] is True


def test_design_gap_cap_and_reason():
    lt = _lt(
        [_l("UDS_FUNCTION", f"fn{i}", f"REQ-{i:03}") for i in range(60)]
        + [_l("SUTS_TEST", "T1", "REQ-000")]
    )
    g = compute_design_test_gap(lt, cap=50)
    assert len(g["targets_with_uds_no_suts"]) == 50 and g["no_suts_omitted"] == 9
    assert compute_design_test_gap(None) == {"available": False, "reason": "no_trace_link_table"}
    assert compute_design_test_gap({"links": []})["available"] is False


def test_catalog_iso_refs_present():
    # 카탈로그는 표 참조를 항상 동반(가이드 출처 명시 — 심사 판정 아님)
    assert len(TECHNIQUE_CATALOG) == 8
    assert all(c.get("iso_ref", "").startswith("ISO 26262-6") for c in TECHNIQUE_CATALOG.values())
