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
    b_sum, a_sum = before["summary"], after["summary"]

    # ── 무엇이 달라져도 되는지를 **화이트리스트**로 못박는다 ──────────────────
    #
    # ⚠ 2026-09-02: 여기 있던 커버리지 단언은 **한 번도 아무것도 재지 않았다**.
    #   `for key in ("coverage_pct", "full_coverage_pct", "safety_pct"):`
    #       assert before["summary"].get(key) == after["summary"].get(key)
    #   그 세 키는 `generate_uds_traceability_matrix` 의 summary 에 **존재하지 않는다**
    #   (`coverage_pct` 계열은 `jenkins.py::_cache_trace_summary` 가 따로 파생하고,
    #    `safety_pct` 는 죽은 `/api/local/traceability` 안에만 있다). `.get()` 이 양쪽
    #   모두 `None` 을 돌려주니 `None == None` — 주석은 "커버리지 지표 완전 일치"라고
    #   적혀 있는데 실제로는 **빈 단언 3개**였다.
    #
    # 그래서 "고른 몇 개가 같다"가 아니라 **"허용한 것 말고는 전부 같다"** 로 뒤집는다.
    # 이러면 나중에 summary 에 키가 늘어도 자동으로 덮이고, 없는 키를 비교하는 방식으로
    # 다시 빈 단언이 되는 길이 막힌다.
    SUMMARY_MAY_CHANGE = {"total_sds_components"}   # 접기가 줄이는 것은 SDS 밴드 수치뿐
    ROW_MAY_CHANGE = {"sds_components", "sds_functions"}

    _assert_same_except(b_sum, a_sum, SUMMARY_MAY_CHANGE, "summary")
    _assert_same_except(b_row, a_row, ROW_MAY_CHANGE, "row")

    # 설계 연결 여부(has_design 의 SDS 절) — 허용 키 안에서도 **판정은** 불변이어야 한다
    assert (bool(b_row["sds_components"]) or bool(b_row["sds_functions"])) is \
           (bool(a_row["sds_components"]) or bool(a_row["sds_functions"]))
    # 밴드 수치는 실제로 내려간다(= 픽스처가 접기를 정말 일으켰다)
    assert a_sum["total_sds_components"] < b_sum["total_sds_components"]
    assert a_sum["mapped_sds_count"] <= b_sum["mapped_sds_count"]


def _assert_same_except(before, after, may_change, label):
    """`may_change` 를 뺀 **모든** 키가 같은지 본다 — 빈 단언이 될 수 없게.

    세 가지를 함께 강제한다:
      1. 키 집합이 같다 (한쪽에만 생긴 키를 `.get()` 이 `None` 으로 뭉개지 못하게)
      2. `may_change` 의 키가 **실제로 존재한다** (오타·삭제된 키를 허용 목록에 남겨
         두면 그 항목은 아무 일도 안 한다)
      3. `may_change` 중 **최소 하나는 실제로 달라졌다** (안 달라졌다면 픽스처가
         변화를 못 만든 것이고, 그러면 이 테스트 전체가 vacuous 다)
    """
    assert set(before) == set(after), (
        f"{label}: 키 집합이 다르다 — "
        f"before-only={sorted(set(before) - set(after))} "
        f"after-only={sorted(set(after) - set(before))}"
    )
    missing = sorted(k for k in may_change if k not in before)
    assert not missing, f"{label}: 허용 목록에 없는 키가 있다(오타/삭제?) — {missing}"
    for key in sorted(set(before) - may_change):
        assert before[key] == after[key], f"{label}[{key}]: {before[key]!r} -> {after[key]!r}"
    changed = sorted(k for k in may_change if before[k] != after[k])
    assert changed, (
        f"{label}: 허용한 키가 하나도 안 변했다 — 픽스처가 접기를 못 일으켰고, "
        f"그러면 이 비교는 아무것도 재지 않는다 (may_change={sorted(may_change)})"
    )


# ── 거친 입도 단일 출처 (Jenkins ↔ local lockstep) ──────────────────────────
#
# 이 지표는 밴드 정화 전까지 **한 번도 발화하지 않았다**. 분모가 상태명·설계ID·목차줄까지
# 세던 동안 HDPDM01 기준 201 이었고 임계가 80.4 인데 최대 행이 34 였다(0/63). 정화로
# 분모가 33 이 되자 임계 13.2 에서 8건이 드러났다. 즉 분모 오염이 지표를 죽인다 —
# 두 모드가 각자 세면 같은 문서가 모드에 따라 다른 값을 낸다.

def test_annotate_coarse_denominator_is_row_based_distinct():
    """분모는 행에 실제로 실린 sds_components 의 distinct(대소문자 무시)."""
    from report_gen.requirements import annotate_sds_coarse

    rows = [
        {"sds_components": ["SwCom_01", "SwCom_02", "SwCom_03"]},
        {"sds_components": ["swcom_01", "SwCom_04", "SwCom_05"]},   # swcom_01 은 중복
    ]
    total, coarse = annotate_sds_coarse(rows)
    assert total == 5                       # 01·02·03·04·05
    assert coarse == 2                      # 3 > 0.4*5 = 2.0 → 두 행 다


def test_annotate_coarse_skips_small_denominator():
    """컴포넌트 5개 미만이면 비율이 무의미 — 플래그 자체를 달지 않는다."""
    from report_gen.requirements import annotate_sds_coarse

    rows = [{"sds_components": ["SwCom_01", "SwCom_02", "SwCom_03"]}]
    total, coarse = annotate_sds_coarse(rows)
    assert (total, coarse) == (3, 0)
    assert "sds_coarse" not in rows[0]      # 미적용은 False 가 아니라 부재(오독 방지)


def test_annotate_coarse_boundary_is_strict_greater():
    """정확히 40%는 coarse 아님 — '초과'가 계약이다."""
    from report_gen.requirements import annotate_sds_coarse

    rows = [{"sds_components": [f"SwCom_{i:02d}" for i in range(1, 5)]},      # 4/10 = 40%
            {"sds_components": [f"SwCom_{i:02d}" for i in range(1, 11)]}]     # 10/10
    total, coarse = annotate_sds_coarse(rows)
    assert total == 10
    assert rows[0]["sds_coarse"] is False
    assert rows[1]["sds_coarse"] is True
    assert coarse == 1


def test_annotate_coarse_tolerates_junk_rows():
    """None·비-dict 행이 섞여도 죽지 않는다(캐시 복원 경로 방어)."""
    from report_gen.requirements import annotate_sds_coarse

    assert annotate_sds_coarse(None) == (0, 0)
    assert annotate_sds_coarse([None, "x", {"sds_components": None}]) == (0, 0)


def test_both_modes_use_the_shared_coarse_helper():
    """구조 가드 — 한쪽이 자기 식으로 다시 세면 모드 간 값이 갈린다.

    `total_sds_components` 도 같은 헬퍼의 행 기준 분모를 써야 한다. local 은 예전에
    `sds_req_to_design_comps` 전량(매트릭스에 없는 요구의 컴포넌트 포함)을 세서
    거친 입도 임계의 분모와 표시 총수가 어긋나 있었다.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    local_src = (root / "backend" / "routers" / "local.py").read_text(encoding="utf-8", errors="ignore")
    req_src = (root / "report_gen" / "requirements.py").read_text(encoding="utf-8", errors="ignore")

    assert "annotate_sds_coarse(rows)" in local_src, "local 경로가 공용 헬퍼를 안 쓴다"
    assert '"sds_coarse_count": sds_coarse_count' in local_src, "local summary 에 키가 없다"
    # local 이 분모를 자기 식으로 다시 세면 안 된다.
    assert "len({c for cs in sds_req_to_design_comps.values() for c in cs})" not in local_src
    # 판정식은 헬퍼 안에만 있어야 한다.
    assert req_src.count("_SDS_COARSE_RATIO * total") == 1
    assert "0.4 * _total_sds_comps" not in req_src


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
