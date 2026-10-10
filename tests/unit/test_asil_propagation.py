"""요구 ASIL → 함수 역전파(N2) — max 병합·정규화·출처 라벨·정직 실패.

배경(실측): C 소스에 @asil 주석이 0건인 프로젝트가 있어 ASIL 축이 죽어 있었다.
trace_link_table의 asil_coverage.by_target(요구별 등급) × UDS_FUNCTION 링크(요구→실 함수명)로
함수 등급을 복원한다.
"""
from __future__ import annotations

from workflow.asil_propagation import (
    ASIL_RANK,
    asil_lookup,
    build_function_asil_map,
    distribution,
    merge_asil_sources,
    normalize_asil,
    top_functions,
)


def _table(**over) -> dict:
    base = {
        "asil_coverage": {"by_target": {"SwCNF_0101": "A", "SwNTR_0301": "D", "SwEI_03": "QM",
                                        "SwBAD_01": "C(D)"}},
        "links": [
            {"target_id": "SwCNF_0101", "related_id": "g_SysOptionCtrl", "related_type": "UDS_FUNCTION"},
            # 같은 함수가 더 높은 등급 요구에도 걸린다 → max(D) 채택(안전측)
            {"target_id": "SwNTR_0301", "related_id": "g_SysOptionCtrl", "related_type": "UDS_FUNCTION"},
            {"target_id": "SwEI_03", "related_id": "Lib_helper", "related_type": "UDS_FUNCTION"},
            # 비표준 등급 요구 — 채택하지 않는다
            {"target_id": "SwBAD_01", "related_id": "bad_fn", "related_type": "UDS_FUNCTION"},
            # 등급 없는 요구로만 연결된 함수 — 미상으로 남는다
            {"target_id": "SwUNKNOWN", "related_id": "orphan_fn", "related_type": "UDS_FUNCTION"},
            # 함수 링크가 아닌 밴드는 무시(SwUFn ID는 함수명이 아니다)
            {"target_id": "SwCNF_0101", "related_id": "SwUFn_3401", "related_type": "VCAST_FUNCTION"},
            {"target_id": "SwCNF_0101", "related_id": "option_control", "related_type": "SDS_COMPONENT"},
        ],
    }
    base.update(over)
    return base


def test_max_asil_across_requirements():
    out = build_function_asil_map(_table())
    assert out["available"] is True
    by = out["by_function"]
    assert by["g_sysoptionctrl"]["asil"] == "D"  # 요구 A와 D에 모두 걸림 → max(D) 채택
    assert by["g_sysoptionctrl"]["targets"] == ["SwCNF_0101", "SwNTR_0301"]
    assert by["g_sysoptionctrl"]["display_name"] == "g_SysOptionCtrl"
    assert by["lib_helper"]["asil"] == "QM"


def test_nonstandard_and_unknown_targets_are_not_adopted():
    out = build_function_asil_map(_table())
    by = out["by_function"]
    assert "bad_fn" not in by      # 'C(D)' 비표준 → 미상(오분류보다 미상)
    assert "orphan_fn" not in by   # 등급 없는 요구만 연결 → 미상
    assert out["stats"]["targets_nonstandard_asil"] == 1
    assert out["stats"]["links_target_without_asil"] == 2  # bad_fn(등급 탈락) + orphan_fn
    assert out["stats"]["uds_function_links"] == 5
    assert out["stats"]["functions_resolved"] == 2


def test_non_function_bands_ignored():
    """VCAST_FUNCTION(SwUFn ID)·SDS_COMPONENT를 함수로 오인하면 허위 ASIL이 퍼진다."""
    by = build_function_asil_map(_table())["by_function"]
    assert "swufn_3401" not in by and "option_control" not in by


def test_honest_failure_reasons():
    assert build_function_asil_map(None)["reason"] == "no_trace_link_table"
    assert build_function_asil_map({"links": []})["reason"] == "no_trace_link_table"
    assert build_function_asil_map({"links": [{"a": 1}]})["reason"] == "no_target_asil"
    empty = build_function_asil_map({"links": [{"target_id": "T", "related_id": "f",
                                                "related_type": "SUTS_TEST"}],
                                     "asil_coverage": {"by_target": {"T": "B"}}})
    assert empty["available"] is False and empty["reason"] == "no_uds_function_links"


def test_merge_prefers_max_and_flags_conflict():
    uds = build_function_asil_map(_table())
    merged, counts = merge_asil_sources({"Lib_helper": "B", "only_comment": "C"}, uds)
    # 주석 B vs 링크 QM → max(B) 채택 + conflict 표면화
    assert merged["lib_helper"]["asil"] == "B"
    assert merged["lib_helper"]["source"] == "both" and merged["lib_helper"]["conflict"] is True
    assert merged["only_comment"]["source"] == "comment_asil"
    assert merged["g_sysoptionctrl"]["source"] == "uds_link"
    assert counts == {"comment_asil": 1, "uds_link": 1, "both": 1, "conflict": 1, "total": 3}


def test_merge_without_conflict_when_equal():
    uds = build_function_asil_map(_table())
    merged, counts = merge_asil_sources({"g_SysOptionCtrl": "D"}, uds)
    assert merged["g_sysoptionctrl"]["asil"] == "D"
    assert merged["g_sysoptionctrl"]["source"] == "both"
    assert merged["g_sysoptionctrl"]["conflict"] is False
    assert counts["conflict"] == 0


def test_normalize_and_lookup_helpers():
    assert normalize_asil(" d ") == "D" and normalize_asil("qm") == "QM"
    assert normalize_asil("C(D)") is None and normalize_asil(None) is None
    merged, _ = merge_asil_sources({}, build_function_asil_map(_table()))
    # 시그니처/스코프가 붙어도 같은 정규화 규약으로 조인된다
    assert asil_lookup(merged, "g_SysOptionCtrl(void)") == "D"
    assert asil_lookup(merged, "Cls::g_SysOptionCtrl") == "D"
    assert asil_lookup(merged, "no_such_fn") is None


def test_distribution_keeps_zero_keys_and_ordering():
    merged, _ = merge_asil_sources({}, build_function_asil_map(_table()))
    dist = distribution(merged)
    assert dist == {"D": 1, "C": 0, "B": 0, "A": 0, "QM": 1}  # 0인 등급도 키 유지
    rows = top_functions(merged)
    assert [r["asil"] for r in rows] == ["D", "QM"]           # 등급 내림차순
    assert ASIL_RANK["D"] > ASIL_RANK["QM"]
