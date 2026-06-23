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
    assert tuple(out["bands"]) == ("SDS", "UDS", "STS", "SUTS", "SITS", "VectorCAST")


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
