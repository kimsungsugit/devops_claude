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


# ── canonical 접기(라운드114) — I2 합집합 불변식 ────────────────────────────
#
# SwCom 표는 ID(`swcom_14`)와 이름(`door control`)을 별개 키로 등록한다. 밴드에서 둘을
# canonical 로 접으면 표시는 1개가 되지만, 접힌 원 키가 어디로 갔는지 소비처가 모르면
# 차집합(`sds_functions` = component_ids − sds_components)이 **둘 다 함수로** 집어삼킨다.
# 그래서 `folded_component_ids` 를 함께 싣고, 아래 세 테스트가 그 계약을 고정한다.


def _folded_matrix(design, folded=None, comps=None):
    pair = {
        "requirement_id": "SwTR_01",
        "component_ids": comps if comps is not None else ["swcom_14", "door control", "g_iface"],
        "design_component_ids": design,
    }
    if folded is not None:
        pair["folded_component_ids"] = folded
    m = generate_uds_traceability_matrix(
        [{"id": "SwTR_01", "name": "x"}], mapping_pairs=[], vcast_rows=[],
        sds_pairs=[pair], sits_rows=[], uds_function_ids=[], component_asil={},
    )
    return m, m["rows"][0]


def test_folded_alias_not_double_counted_as_function():
    """B8 — 접힌 원 키는 sds_functions 로 새지 않는다."""
    _, row = _folded_matrix(["SwCom_14"], folded=["swcom_14", "door control"])
    assert row["sds_components"] == ["SwCom_14"]
    assert row["sds_functions"] == ["g_iface"]     # 접힌 두 키가 아니라 진짜 함수만


def test_missing_folded_field_degrades_to_pre_folding_behaviour():
    """B9 — 구 응답·구 캐시(folded 필드 부재)는 접기 이전 동작 그대로.

    새 필드를 모르는 저장분이 조용히 다른 수치를 내면 안 된다. 부재 = 빈 집합 = 무동작.
    """
    _, row = _folded_matrix(["SwCom_14"])           # folded 미제공
    assert row["sds_components"] == ["SwCom_14"]
    assert set(row["sds_functions"]) == {"swcom_14", "door control", "g_iface"}


def test_union_invariant_components_plus_folded_plus_functions_covers_all():
    """B10 — I2 항등식: sds_components ∪ folded ∪ sds_functions ⊇ component_ids.

    누락(커버리지 하락)과 중복(밴드 부풀림)을 동시에 차단하는 유일한 어서션이다.
    """
    _, row = _folded_matrix(["SwCom_14"], folded=["swcom_14", "door control"])
    union = {c.lower() for c in row["sds_components"]} | {"swcom_14", "door control"} \
        | {c.lower() for c in row["sds_functions"]}
    assert union >= {"swcom_14", "door control", "g_iface"}
    # 중복 없음: components 와 functions 는 교집합이 비어야 한다.
    assert not ({c.lower() for c in row["sds_components"]}
                & {c.lower() for c in row["sds_functions"]})


def test_coverage_and_asil_invariant_under_purification():
    """C11 — 정화 전/후로 **커버리지와 ASIL 은 변하지 않는다**.

    밴드에서 뺀 것이 `sds_functions` 로 흘러가고 `has_design` 이 둘의 OR 을 보기 때문에
    (`jenkins.py` `_row_bands`/`local.py`/`SrsSdsSection.jsx` 3-site 동일) 커버리지는
    구조적으로 불변이어야 한다. 이 어서션이 깨지면 I2 가 새고 있다는 뜻이다.
    """
    comps = ["swcom_14", "door control", "g_iface"]
    asil = {"swcom_14": "B", "door control": "B", "g_iface": "B"}

    def _run(pair_extra):
        pair = {"requirement_id": "SwTR_01", "component_ids": comps, **pair_extra}
        return generate_uds_traceability_matrix(
            [{"id": "SwTR_01", "name": "x"}], mapping_pairs=[], vcast_rows=[],
            sds_pairs=[pair], sits_rows=[], uds_function_ids=[], component_asil=asil,
        )

    before = _run({"design_component_ids": ["swcom_14", "door control"]})   # 접기 전(66 상태)
    after = _run({"design_component_ids": ["SwCom_14"],
                  "folded_component_ids": ["swcom_14", "door control"]})    # 접기 후(33 상태)

    b_row, a_row = before["rows"][0], after["rows"][0]
    # 설계 연결 여부(has_design 의 SDS 절) 완전 일치
    assert (bool(b_row["sds_components"]) or bool(b_row["sds_functions"])) is \
           (bool(a_row["sds_components"]) or bool(a_row["sds_functions"]))
    # 행 ASIL 완전 일치 — 롤업은 sds_list(전체) 기반이라 접기와 무관
    assert b_row.get("asil") == a_row.get("asil")
    # 커버리지 지표 완전 일치
    for key in ("coverage_pct", "full_coverage_pct", "safety_pct"):
        assert before["summary"].get(key) == after["summary"].get(key), key
    # 밴드 수치만 내려간다
    assert after["summary"]["total_sds_components"] < before["summary"]["total_sds_components"]
    assert after["summary"]["mapped_sds_count"] <= before["summary"]["mapped_sds_count"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
