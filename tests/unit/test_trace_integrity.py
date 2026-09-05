"""report_gen.trace_integrity.build_integrity_audit 단위 테스트.

검증: 정규화 충돌(raw N→canonical 1) 표면화, 상향 dangling(SRS 부재) namespace 그룹핑,
placeholder 보수 탐지, clean 신호, 결정적 정렬, 빌더 end-to-end 통합.
"""

from report_gen.trace_integrity import build_integrity_audit


def _audit(**kw):
    base = dict(req_ids=[], norm_to_raws={}, referenced={}, related_ids={})
    base.update(kw)
    return build_integrity_audit(**base)


# ── 정규화 충돌 ──
def test_collision_detected():
    a = _audit(
        req_ids=["SWRS_001"],
        norm_to_raws={"SWRS_001": ["SwRS_001", "SwRS_ 001", "swrs_001"]},
    )
    cols = a["id_collisions"]
    assert len(cols) == 1
    c = cols[0]
    assert c["canonical"] == "SWRS_001"
    assert c["variant_count"] == 3
    assert c["variants"] == ["SwRS_ 001", "SwRS_001", "swrs_001"]  # 정렬됨
    assert a["stats"]["collision_count"] == 1
    assert a["stats"]["collision_affected_raw"] == 3
    assert a["stats"]["clean"] is False


def test_no_collision_when_single_raw():
    a = _audit(req_ids=["A"], norm_to_raws={"A": ["A"], "B": ["B", "B"]})
    # 'B'의 raw가 둘 다 동일 → distinct 1 → 충돌 아님
    assert a["id_collisions"] == []
    assert a["stats"]["clean"] is True


def test_collision_deterministic_sorted():
    nr = {
        "X": ["x1", "x2"],                  # variant 2
        "Y": ["y1", "y2", "y3", "y4"],      # variant 4
        "Z": ["z1", "z2", "z3"],            # variant 3
    }
    a1 = _audit(norm_to_raws=nr)
    a2 = _audit(norm_to_raws=dict(reversed(list(nr.items()))))
    # 변형 많은 순(-count), 동률 canonical 사전순 → 입력 순서 무관 동일
    order = [c["canonical"] for c in a1["id_collisions"]]
    assert order == ["Y", "Z", "X"]
    assert [c["canonical"] for c in a2["id_collisions"]] == order


# ── 상향 dangling ──
def test_dangling_refs_namespace_grouped():
    a = _audit(
        req_ids=["SWRS_001", "SWRS_002"],
        referenced={
            "SDS": {"SWRS_001": "SwRS_001", "SWST_500": "SwST_500"},  # SWST_500 부재
            "UDS": {"SWFN_900": "SwFn_900"},                          # SWFN_900 부재
        },
    )
    assert a["stats"]["dangling_count"] == 2
    assert a["dangling_by_namespace"]["SDS"] == {"SWST": 1}
    assert a["dangling_by_namespace"]["UDS"] == {"SWFN": 1}
    sds = a["dangling_refs"]["SDS"]
    assert sds == [
        {"ref_id": "SwST_500", "normalized": "SWST_500", "namespace": "SWST",
         "severity": "foreign", "layer": "SwDS(설계)"}
    ]


def test_dangling_severity_suspect_vs_foreign():
    # SRS universe namespace = {SWRS}. SWRS_999 부재 → suspect(오타 의심).
    # SWFN_900 → foreign(SRS에 없는 namespace = 다른 계층).
    a = _audit(
        req_ids=["SWRS_001", "SWRS_002"],
        referenced={"UDS": {"SWRS_999": "SwRS_999", "SWFN_900": "SwFn_900"}},
    )
    assert a["stats"]["dangling_count"] == 2
    assert a["stats"]["dangling_suspect_count"] == 1
    assert a["stats"]["dangling_foreign_count"] == 1
    refs = {d["normalized"]: d["severity"] for d in a["dangling_refs"]["UDS"]}
    assert refs["SWRS_999"] == "suspect"
    assert refs["SWFN_900"] == "foreign"
    # suspect가 목록 앞에 정렬
    assert a["dangling_refs"]["UDS"][0]["severity"] == "suspect"


def test_dangling_all_foreign_zero_suspect():
    # KJPDS02 실데이터 형태: SRS=SWEI/SWTR..., UDS 참조=SWSTR/SWST(전혀 다른 계층) → 전부 foreign.
    a = _audit(
        req_ids=["SWEI_01", "SWTR_05"],
        referenced={"UDS": {"SWSTR_01": "SwSTR_01", "SWST_09": "SwST_09"}},
    )
    assert a["stats"]["dangling_suspect_count"] == 0
    assert a["stats"]["dangling_foreign_count"] == 2


def test_dangling_excludes_valid_refs():
    a = _audit(
        req_ids=["SWRS_001"],
        referenced={"SDS": {"SWRS_001": "SwRS_001"}},  # universe에 있음 → dangling 아님
    )
    assert a["stats"]["dangling_count"] == 0
    assert a["dangling_refs"] == {}
    assert a["stats"]["clean"] is True


# ── placeholder ──
def test_placeholder_detection():
    a = _audit(related_ids={"SDS": ["SwCom_01", "SwCom_XX", "g_real", "TBD", "f_??"]})
    found = a["placeholder_ids"]["SDS"]
    assert "SwCom_XX" in found and "TBD" in found and "f_??" in found
    assert "SwCom_01" not in found and "g_real" not in found
    assert a["stats"]["placeholder_count"] == 3


def test_placeholder_conservative_single_letter():
    # MAX/ANNUAL 등 단일 X·경계 없는 NN은 placeholder 아님(false positive 방지)
    a = _audit(related_ids={"UDS": ["MAX_SPEED", "ANNUAL_RESET", "g_connect", "0xFF"]})
    assert a["placeholder_ids"] == {}
    assert a["stats"]["placeholder_count"] == 0


def test_dangling_layer_labeled_swds():
    # 설계계층 라벨(추가형): SwSTR/SwST/SwTK는 SwDS(설계) 계층으로 명시되어야 함.
    # SRS namespace는 SWTR/SWEI 등 → SwSTR은 foreign이고 layer='SwDS(설계)'.
    a = _audit(
        req_ids=["SwTR_01", "SwEI_02"],
        referenced={"UDS": {"SWSTR_07": "SwSTR_07", "SWST_03": "SwST_03", "SWTK_01": "SwTK_01"}},
    )
    foreign = a["dangling_refs"]["UDS"]
    assert all(d["layer"] == "SwDS(설계)" for d in foreign)        # 각 항목에 layer 필드
    assert a["dangling_layer_summary"] == {"SwDS(설계)": 3}        # foreign 계층 집계
    assert a["stats"]["dangling_foreign_count"] == 3
    assert a["stats"]["dangling_suspect_count"] == 0


def test_dangling_layer_summary_excludes_suspect():
    # suspect(SRS namespace 내 부재)는 계층차가 아니므로 layer_summary에 포함 안 됨.
    a = _audit(
        req_ids=["SwTR_01"],                          # srs namespace = {SWTR}
        referenced={"UDS": {"SWTR_99": "SwTR_99",     # suspect (SWTR namespace 공유)
                            "SWSTR_07": "SwSTR_07"}},  # foreign (SwDS 설계)
    )
    assert a["stats"]["dangling_suspect_count"] == 1
    assert a["stats"]["dangling_foreign_count"] == 1
    assert a["dangling_layer_summary"] == {"SwDS(설계)": 1}        # suspect 제외, foreign만


def test_placeholder_lowercase_identifier_not_matched():
    # 적대검증 Info fix: 소문자 xx/nn run은 실제 C 식별자이지 placeholder 아님.
    # placeholder 관례(SwCom_XX)는 대문자 → 대문자 한정으로 오탐 제거.
    a = _audit(related_ids={"UDS": ["EEPROM_xx_write", "g_nnn_idx", "CAN_xx_handler"],
                            "SDS": ["SwCom_XX"]})
    assert a["placeholder_ids"].get("UDS", []) == []        # 소문자 → 미매칭
    assert "SwCom_XX" in a["placeholder_ids"].get("SDS", [])  # 대문자 → 여전히 매칭
    assert a["stats"]["placeholder_count"] == 1


# ── clean / graceful ──
def test_clean_when_empty():
    a = _audit()
    assert a["stats"]["clean"] is True
    assert a["stats"]["collision_count"] == 0
    assert a["id_collisions"] == [] and a["dangling_refs"] == {} and a["placeholder_ids"] == {}


def test_clean_false_with_any_finding():
    assert _audit(related_ids={"SDS": ["x_XX"]})["stats"]["clean"] is False


# ── 빌더 end-to-end 통합 ──
def test_builder_emits_integrity_with_collision_and_dangling():
    from report_gen.requirements import generate_uds_traceability_matrix

    items = [{"id": "SwRS_001"}, {"id": "SwRS_ 001"}, {"id": "SwRS_002"}]
    mapping = [{"requirement_id": "SwFn_900", "source_ids": ["g_orphan", "bar_XX"]}]
    sds = [{"requirement_id": "SwRS_002", "component_ids": ["SwCom_XX"]}]
    m = generate_uds_traceability_matrix(items, mapping_pairs=mapping, sds_pairs=sds)
    intg = m.get("integrity")
    assert isinstance(intg, dict)
    # SwRS_001/SwRS_ 001 → 같은 canonical 충돌
    assert intg["stats"]["collision_count"] == 1
    # SwFn_900 → SRS 부재 dangling(UDS)
    assert intg["stats"]["dangling_count"] >= 1
    # bar_XX(UDS), SwCom_XX(SDS) → placeholder
    assert intg["stats"]["placeholder_count"] >= 2
    assert intg["stats"]["clean"] is False


def test_builder_integrity_clean_on_consistent_input():
    from report_gen.requirements import generate_uds_traceability_matrix

    items = [{"id": "SwRS_001"}, {"id": "SwRS_002"}]
    mapping = [{"requirement_id": "SwRS_001", "source_ids": ["g_func"]}]
    sds = [{"requirement_id": "SwRS_002", "component_ids": ["SwCom_01"]}]
    m = generate_uds_traceability_matrix(items, mapping_pairs=mapping, sds_pairs=sds)
    assert m["integrity"]["stats"]["clean"] is True
