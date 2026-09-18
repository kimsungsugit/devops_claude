"""report_gen.trace_link_table.build_link_table 단위 테스트.

검증 축:
- 결정성(P2): 같은 입력 → byte-identical 출력 (JSON round-trip 포함)
- 정확성: 밴드별 링크 파생, target/related 매핑, dedup
- 커버리지: 부동소수 % (정수나눗셈 절삭 없음), 0건 target(uncovered) 추출
- 래핑 허용: {"matrix": {...}} 와 top-level 모두 처리
"""

import json

from report_gen.trace_link_table import BANDS, build_link_table


def _sample_matrix():
    """6레벨 일부가 채워진 현실적 매트릭스 fixture."""
    return {
        "total_requirements": 3,
        "rows": [
            {
                "requirement_id": "SwTR_001",
                "requirement_name": "도어 잠금 제어",
                "sds_components": ["SwCom_01", "SwCom_02"],
                "source_ids": ["g_doorctrl_lock", "g_doorctrl_unlock"],
                "sts_tests": [{"testcase": "TC_STS_001", "source": "STS", "confidence": "exact"}],
                "suts_tests": [
                    {"testcase": "TC_SUTS_001", "source": "SUTS", "trace_type": "indirect"}
                ],
                "sits_tests": [],
                "tests": [
                    {"testcase": "TC_STS_001", "source": "STS"},
                    {"subprogram": "g_doorctrl_lock", "source": "VectorCAST", "confidence": "fuzzy"},
                ],
            },
            {
                "requirement_id": "SwTR_002",
                "requirement_name": "속도 감시",
                "sds_components": ["SwCom_02"],  # SwCom_02 는 SwTR_001 와 공유 (열 dedup 확인)
                "source_ids": [],
                "sts_tests": [],
                "suts_tests": [],
                "sits_tests": [{"testcase": "TC_SITS_009", "source": "SITS", "confidence": "exact"}],
                "tests": [],
            },
            {
                # 추적 0건 — uncovered_targets 에 잡혀야 함 (hiMA 0카운트 핑크밴드 대응)
                "requirement_id": "SwTR_003",
                "requirement_name": "미추적 요구",
                "sds_components": [],
                "source_ids": [],
                "sts_tests": [],
                "suts_tests": [],
                "sits_tests": [],
                "tests": [],
            },
        ],
    }


def test_links_derived_per_band():
    out = build_link_table(_sample_matrix())
    links = out["links"]
    # SwTR_001: SDS 2 + UDS 2 + STS 1 + SUTS 1 + VCAST 1 = 7
    t1 = [lk for lk in links if lk["target_id"] == "SwTR_001"]
    by_type = {lk["related_type"] for lk in t1}
    assert by_type == {"SDS_COMPONENT", "UDS_FUNCTION", "STS_TEST", "SUTS_TEST", "VCAST_FUNCTION"}
    assert len(t1) == 7
    # SUTS 행은 trace_type=indirect → confidence indirect 로 반영
    suts = [lk for lk in t1 if lk["related_type"] == "SUTS_TEST"][0]
    assert suts["confidence"] == "indirect"


def test_deterministic_byte_identical():
    """같은 입력을 2회 빌드 → JSON 직렬화가 완전히 동일(P2 결정성)."""
    a = build_link_table(_sample_matrix())
    b = build_link_table(_sample_matrix())
    assert json.dumps(a, sort_keys=False, ensure_ascii=False) == json.dumps(
        b, sort_keys=False, ensure_ascii=False
    )
    # links 순서도 정렬로 고정 — 첫 링크가 정렬 최소값
    assert a["links"] == b["links"]


def test_json_round_trip_stable():
    out = build_link_table(_sample_matrix())
    reloaded = json.loads(json.dumps(out, ensure_ascii=False))
    assert reloaded == out


def test_column_dedup_across_targets():
    out = build_link_table(_sample_matrix())
    # SwCom_02 는 두 요구에서 참조되지만 열 헤더엔 1번만
    assert out["columns"]["SDS"].count("SwCom_02") == 1
    assert "SwCom_01" in out["columns"]["SDS"]


def test_uncovered_targets_and_float_coverage():
    out = build_link_table(_sample_matrix())
    cov = out["coverage"]
    assert cov["uncovered_targets"] == ["SwTR_003"]
    # SDS 밴드: 3개 중 2개 target 링크 → 66.7% (정수나눗셈이면 66.0 으로 절삭됐을 값)
    assert cov["by_band"]["SDS"]["linked_targets"] == 2
    assert cov["by_band"]["SDS"]["pct"] == round(2 * 100.0 / 3, 1)
    assert cov["by_band"]["SDS"]["pct"] == 66.7


def test_accepts_wrapped_matrix():
    wrapped = {"matrix": _sample_matrix()}
    out = build_link_table(wrapped)
    assert out["stats"]["target_count"] == 3
    assert out["stats"]["link_count"] > 0


def test_empty_and_malformed_safe():
    assert build_link_table({})["links"] == []
    assert build_link_table({"rows": []})["stats"]["target_count"] == 0
    # 비-dict row / 빈 requirement_id 는 스킵
    out = build_link_table({"rows": [None, {"requirement_id": ""}, "x"]})
    assert out["stats"]["target_count"] == 0


def test_bands_constant_order():
    out = build_link_table(_sample_matrix())
    assert out["bands"] == list(BANDS)
    # SyRS=상위(맨앞), HSIS는 SDS 뒤(design-arm), SyTS/SyITS(시스템 시험)는 SITS 뒤.
    assert tuple(out["bands"]) == ("SyRS", "SDS", "HSIS", "UDS", "STS", "SUTS", "SITS", "SyTS", "SyITS", "VectorCAST")


def test_hsis_band_extracted():
    """HSIS 인터페이스 밴드 — row.hsis_signals → HSIS_SIGNAL 링크 + coverage.by_band(시스템 레벨 design-arm)."""
    matrix = {"rows": [
        {"requirement_id": "SwEI_01", "hsis_signals": ["HSI_13", "u16g_ApiIn_Vsup"], "asil": "A"},
        {"requirement_id": "SwTR_01", "sds_components": ["g_comp"], "asil": "A"},
    ]}
    out = build_link_table(matrix)
    hsis_links = [lk for lk in out["links"] if lk["related_type"] == "HSIS_SIGNAL"]
    assert len(hsis_links) == 2
    assert all(lk["source"] == "HSIS" and lk["target_id"] == "SwEI_01" for lk in hsis_links)
    assert set(out["columns"]["HSIS"]) == {"HSI_13", "u16g_ApiIn_Vsup"}
    assert out["coverage"]["by_band"]["HSIS"]["linked_targets"] == 1
    # 결정성 — 같은 입력 → 동일 링크 순서
    assert build_link_table(matrix)["links"] == out["links"]


def test_system_test_bands_extracted():
    """SyTS/SyITS 시스템 시험 밴드 — syts_tests/syits_tests → SYTS_TEST/SYITS_TEST 링크."""
    matrix = {"rows": [
        {"requirement_id": "SwNTSR_0101",
         "syts_tests": [{"testcase": "SyTC_01", "source": "SyTS"}],
         "syits_tests": [{"testcase": "SyITC_01", "source": "SyITS"}],
         "asil": "A"},
    ]}
    out = build_link_table(matrix)
    rtypes = {lk["related_type"] for lk in out["links"]}
    assert "SYTS_TEST" in rtypes and "SYITS_TEST" in rtypes
    assert out["columns"]["SyTS"] == ["SyTC_01"]
    assert out["columns"]["SyITS"] == ["SyITC_01"]
    assert out["coverage"]["by_band"]["SyITS"]["linked_targets"] == 1


def test_syrs_parent_band_excluded_from_coverage_total():
    """SyRS=상위 provenance — 밴드/링크엔 집계되나 하위 커버리지 total·uncovered_targets엔 미포함(W1).

    상위참조만 있고 설계·시험이 0인 요구가 covered로 오인되면 안 된다(감사본 전방추적 갭 정직).
    """
    matrix = {"rows": [
        {"requirement_id": "SwTR_99", "syrs_parents": ["SyTR_5"]},  # 상위만, 하위 0
        {"requirement_id": "SwTR_01", "sds_components": ["g_c"]},   # 설계 有
    ]}
    out = build_link_table(matrix)
    # SyRS 밴드/링크는 존재
    assert out["coverage"]["by_band"]["SyRS"]["linked_targets"] == 1
    assert any(lk["related_type"] == "SYRS_PARENT" for lk in out["links"])
    # 그러나 SwTR_99의 하위 total은 0 → uncovered_targets에 포함
    assert out["coverage"]["by_target"]["SwTR_99"]["total"] == 0
    assert "SwTR_99" in out["coverage"]["uncovered_targets"]
    assert "SwTR_01" not in out["coverage"]["uncovered_targets"]


# ── ASIL 결합(P5) ─────────────────────────────────────────────────────


def _asil_matrix():
    """ASIL 부여 매트릭스 — A(시험 有), D(시험 全無=갭), C(SUTS만=SITS갭), QM, 미상."""
    return {
        "rows": [
            {  # ASIL A + STS 시험 → 갭 없음(A/B는 시험 1개면 충족)
                "requirement_id": "R_A1", "asil": "A",
                "sds_components": ["c1"], "source_ids": [],
                "sts_tests": [{"testcase": "T1", "source": "STS"}],
                "suts_tests": [], "sits_tests": [], "tests": [],
            },
            {  # ASIL D + 설계만(시험 전무) → SUTS·SITS 둘 다 갭
                "requirement_id": "R_D1", "asil": "D",
                "sds_components": ["c2"], "source_ids": ["f2"],
                "sts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
            },
            {  # ASIL C + SUTS만 → SITS 갭
                "requirement_id": "R_C1", "asil": "C",
                "sds_components": ["c3"], "source_ids": [],
                "sts_tests": [], "suts_tests": [{"testcase": "U3", "source": "SUTS"}],
                "sits_tests": [], "tests": [],
            },
            {  # QM — 시험 없어도 갭 아님
                "requirement_id": "R_Q1", "asil": "QM",
                "sds_components": ["c4"], "source_ids": [],
                "sts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
            },
            {  # ASIL 미상(빈 문자열) — UNKNOWN, 갭 아님
                "requirement_id": "R_U1", "asil": "",
                "sds_components": ["c5"], "source_ids": [],
                "sts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
            },
        ],
    }


def test_asil_coverage_structure():
    ac = build_link_table(_asil_matrix())["asil_coverage"]
    assert ac["has_asil"] is True
    bl = ac["by_level"]
    assert bl["A"]["targets"] == 1
    assert bl["D"]["targets"] == 1
    assert bl["C"]["targets"] == 1
    assert bl["QM"]["targets"] == 1
    assert bl["UNKNOWN"]["targets"] == 1  # 빈 asil → UNKNOWN
    assert ac["by_target"]["R_D1"] == "D"
    assert "R_U1" not in ac["by_target"]  # 빈 asil은 by_target 미기록


def test_asil_gap_detection():
    out = build_link_table(_asil_matrix())
    gaps = {g["target_id"]: g["missing"] for g in out["asil_coverage"]["gaps"]}
    assert "R_A1" not in gaps           # A + 시험 1개 → 충족
    assert gaps["R_D1"] == ["SUTS", "SITS"]  # D + 시험 전무
    assert gaps["R_C1"] == ["SITS"]     # C + SUTS만
    assert "R_Q1" not in gaps           # QM → 기대 없음
    assert "R_U1" not in gaps           # 미상 → 기대 없음
    assert out["stats"]["asil_gap_count"] == 2


def test_asil_ab_system_only_test_is_gap():
    """결정1(wide): ASIL A/B가 시스템시험(SyTS/SyITS)으로만 검증되면 SW-레벨 시험 부재로
    ANY_TEST 갭 + test_covered 미집계. C/D는 원래 SUTS·SITS 직접검사라 무영향.

    프론트 hasTestData / 백엔드 _row_has_sw_tests와 동일한 SW 시험 밴드 집합(SyTS/SyITS 제외)."""
    matrix = {"rows": [
        {  # ASIL B + SyTS만 → SW 시험 없음 → ANY_TEST 갭
            "requirement_id": "R_B_sys", "asil": "B",
            "sds_components": ["cb"],
            "syts_tests": [{"testcase": "SyTC_1", "source": "SyTS"}],
            "sts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
        },
        {  # ASIL A + SyITS만 → 동일하게 갭
            "requirement_id": "R_A_sys", "asil": "A",
            "sds_components": ["ca"],
            "syits_tests": [{"testcase": "SyITC_1", "source": "SyITS"}],
            "sts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
        },
        {  # 대조군: ASIL A + STS(SW 시험) → 충족
            "requirement_id": "R_A_sw", "asil": "A",
            "sds_components": ["cs"],
            "sts_tests": [{"testcase": "T1", "source": "STS"}],
            "syts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
        },
    ]}
    ac = build_link_table(matrix)["asil_coverage"]
    gaps = {g["target_id"]: g["missing"] for g in ac["gaps"]}
    assert gaps["R_B_sys"] == ["ANY_TEST"]   # 시스템시험만 → SW 시험 없음
    assert gaps["R_A_sys"] == ["ANY_TEST"]
    assert "R_A_sw" not in gaps              # STS(SW) → 충족
    # test_covered: SW 시험 있는 것만 집계(시스템-only 제외)
    assert ac["by_level"]["A"]["test_covered"] == 1  # R_A_sw만
    assert ac["by_level"]["B"]["test_covered"] == 0  # R_B_sys는 시스템-only → 미집계


def test_asil_gaps_deterministic_and_sorted():
    a = build_link_table(_asil_matrix())["asil_coverage"]["gaps"]
    b = build_link_table(_asil_matrix())["asil_coverage"]["gaps"]
    assert a == b  # 결정적
    # ASIL 높은 순(D > C)
    assert [g["target_id"] for g in a] == ["R_D1", "R_C1"]


def test_asil_absent_graceful():
    out = build_link_table(_sample_matrix())  # asil 필드 없는 기존 매트릭스
    assert out["asil_coverage"]["has_asil"] is False
    assert out["asil_coverage"]["gaps"] == []
    assert out["asil_coverage"]["unknown_count"] == 0  # asil 자체가 없으면 미상 0
    assert out["stats"]["asil_gap_count"] == 0


def test_asil_unknown_count_surfaced():
    # 빈 asil(R_U1)은 갭과 별개로 unknown_count에 잡혀야 함(reviewer WARN-B 감사 사각 해소)
    ac = build_link_table(_asil_matrix())["asil_coverage"]
    assert ac["unknown_count"] == 1
    assert all(g["target_id"] != "R_U1" for g in ac["gaps"])  # 미상은 갭 아님
