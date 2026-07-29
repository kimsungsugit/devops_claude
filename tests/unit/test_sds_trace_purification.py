"""SDS 추적 정화 회귀 테스트 — 함수/컴포넌트 분리 + UDS confidence + 거친입도.

실데이터(KJPDS02)에서 SwTR_0104 한 요구사항이 SDS 413개에 추적되던 것이 인터페이스 함수
fan-out(실 16 SwCom → 382 함수)임을 진단해, SDS 밴드를 실 컴포넌트만 집계하도록 정화한 변경의
회귀 가드. 브리지(UDS/SUTS/VCAST 회복)는 불변, 직접/브리지 UDS confidence 정직화, 거친입도 플래그.
"""
from __future__ import annotations

from report_gen.requirements import generate_uds_traceability_matrix
from report_gen.trace_link_table import build_link_table


def _build():
    comps = [f"SwCom_{i:02d}" for i in range(1, 17)]      # 16 실 컴포넌트
    funcs = [f"g_func_{i}" for i in range(20)]            # 20 인터페이스 함수
    sds_pairs = [
        {"requirement_id": "SwTR_01", "component_ids": comps + funcs, "design_component_ids": comps},
        {"requirement_id": "SwCNF_01", "component_ids": ["SwCom_01", "SwCom_02", "g_func_0"],
         "design_component_ids": ["SwCom_01", "SwCom_02"]},
    ]
    mapping_pairs = [{"requirement_id": "SwTR_01", "source_ids": ["sf_DirectUds"]}]  # 직접 UDS RelatedID
    uds_function_ids = ["g_func_3", "sf_DirectUds"]  # g_func_3=design func → 브리지 회복(indirect)
    req_items = [{"id": "SwTR_01", "name": "기술요구"}, {"id": "SwCNF_01", "name": "구성요구"}]
    m = generate_uds_traceability_matrix(
        req_items, mapping_pairs=mapping_pairs, vcast_rows=[], sds_pairs=sds_pairs,
        sits_rows=[], uds_function_ids=uds_function_ids, component_asil={},
    )
    rows = {r["requirement_id"]: r for r in m["rows"]}
    return m, rows


def test_sds_components_count_only_real_components_not_functions():
    """Phase 1: sds_components는 실 컴포넌트만(함수 fan-out 제외), 함수는 sds_functions로 분리."""
    _, rows = _build()
    assert len(rows["SwTR_01"]["sds_components"]) == 16    # 36(=16+20) 아님
    assert len(rows["SwTR_01"]["sds_functions"]) == 20
    # 함수가 컴포넌트 목록에 섞이지 않음
    assert all(not c.startswith("g_func_") for c in rows["SwTR_01"]["sds_components"])


def test_uds_bridge_recovery_still_works():
    """브리지 불변: design function이 UDS 인벤토리에 있으면 source_ids로 회복(SDS 경유)."""
    _, rows = _build()
    src = rows["SwTR_01"]["source_ids"]
    assert "sf_DirectUds" in src       # 직접 UDS RelatedID
    assert "g_func_3" in src           # 브리지 회복


def test_uds_confidence_honest_direct_vs_bridge():
    """Phase 2: link_table에서 직접 UDS=direct, SDS 브리지 회복 UDS=indirect."""
    m, _ = _build()
    lt = build_link_table(m)
    uds = {lnk["related_id"]: lnk["confidence"] for lnk in lt["links"]
           if lnk["target_id"] == "SwTR_01" and lnk["source"] == "UDS"}
    assert uds.get("sf_DirectUds") == "direct"
    assert uds.get("g_func_3") == "indirect"


def test_sds_band_links_exclude_functions():
    """회귀: SDS_COMPONENT 링크가 함수 fan-out 없이 실 컴포넌트만 → 18(=16+2)건."""
    m, _ = _build()
    lt = build_link_table(m)
    sds_links = [lnk for lnk in lt["links"] if lnk["source"] == "SDS"]
    assert len(sds_links) == 18  # 분리 전이면 39(=36+3)


def test_coarse_requirement_flag():
    """Phase 3: 실 컴포넌트의 >40%에 연결된 거친 요구사항 플래그 + summary 집계."""
    m, rows = _build()
    assert rows["SwTR_01"]["sds_coarse"] is True       # 16/16 = 100%
    assert rows["SwCNF_01"]["sds_coarse"] is False     # 2/16 = 12.5%
    assert m["summary"]["sds_coarse_count"] == 1
    assert m["summary"]["total_sds_components"] == 16


def test_backward_compat_no_design_component_ids():
    """폴백: design_component_ids 부재(구버전 sds_pairs) 시 component_ids로 폴백 — 회귀 없음."""
    sds_pairs = [{"requirement_id": "SwTR_01", "component_ids": ["SwCom_01", "SwCom_02"]}]  # design_* 없음
    m = generate_uds_traceability_matrix(
        [{"id": "SwTR_01", "name": "x"}], mapping_pairs=[], vcast_rows=[],
        sds_pairs=sds_pairs, sits_rows=[], uds_function_ids=[], component_asil={},
    )
    row = m["rows"][0]
    assert set(row["sds_components"]) == {"SwCom_01", "SwCom_02"}  # 폴백으로 전체 사용
    # link_table UDS confidence: source_ids_direct 있으나 빈 → 폴백 direct 유지
    lt = build_link_table(m)
    assert isinstance(lt["links"], list)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
