"""Regression: SDS 함수명 bridge in generate_uds_traceability_matrix.

UDS는 함수를 설계레벨 ID(SwSTR 등)에, SUTS/SITS는 단위 ID에 추적해 SRS 요구사항
(SwTR/SwEI 등)과 직접 안 맞는다. SDS의 component_ids에는 함수명이 들어 있어
"SRS요구사항→함수명"을 제공하므로, 이를 역으로 써서 UDS 함수(source_ids)와
SUTS/SITS unit을 SRS 행에 연결한다(사용자 결정: "SDS로 bridge"). 그 동작을 고정.
"""
from __future__ import annotations

from report_gen.requirements import generate_uds_traceability_matrix


def test_bridge_fills_uds_source_ids_via_sds_function():
    items = [{"id": "SwTR_0101"}]
    # SDS: SRS 요구사항 → component_ids(함수명 포함)
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["swcom_1", "foo_func"]}]
    # UDS: SwSTR(설계레벨) → 함수명 (SRS와 직접 안 맞음)
    mapping_pairs = [{"requirement_id": "SwSTR_01", "source_ids": ["foo_func", "bar_func"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    row = mx["rows"][0]
    assert row["requirement_id"] == "SwTR_0101"
    # foo_func은 SDS가 이 요구사항에 귀속 → source_ids로 bridge
    assert "foo_func" in row["source_ids"]
    # bar_func은 이 요구사항의 SDS 함수가 아님 → 추가 안 됨
    assert "bar_func" not in row["source_ids"]


def test_bridge_fills_suts_via_unit_function():
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # SUTS: requirement_id는 SwUFn(SRS 불일치)이나 unit=함수명
    vcast = [{"requirement_id": "SwUFn_01", "testcase": "SwUTC_01",
              "unit": "foo_func", "source": "SUTS"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=vcast, sds_pairs=sds_pairs)
    row = mx["rows"][0]
    assert row["suts_count"] >= 1  # unit→SDS→SRS 간접 추적
    assert any(t.get("trace_type") == "indirect" for t in row["suts_tests"])


def test_no_bridge_when_function_absent_in_sds():
    items = [{"id": "SwTR_0101"}]
    # SDS가 다른 함수만 귀속 → bridge 안 됨 (경계 확인)
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["other_func"]}]
    mapping_pairs = [{"requirement_id": "SwSTR_01", "source_ids": ["foo_func"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    row = mx["rows"][0]
    assert "foo_func" not in (row["source_ids"] or [])


def test_sits_two_hop_bridge_via_suts_and_sds():
    """SITS: testcase에 박힌 SwUFn → (SUTS)함수명 → (SDS)SRS 요구사항 2-hop bridge."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # SUTS가 SwUFn_0101 ↔ foo_func 제공
    suts_row = {"requirement_id": "SwUFn_0101", "testcase": "SwUTC_01",
                "unit": "foo_func", "source": "SUTS"}
    # SITS: requirement_id는 SwITC(SRS 불일치), testcase에 SWUFN_0101 임베드
    sits_row = {"requirement_id": "SwITC_0101", "testcase": "SWIT_SWUFN_0101_DEPTH4",
                "source": "SITS"}
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=[suts_row], sds_pairs=sds_pairs, sits_rows=[sits_row])
    row = mx["rows"][0]
    assert row["sits_count"] >= 1
    assert any(t.get("trace_type") == "indirect" for t in row["sits_tests"])


def test_sits_no_bridge_without_suts_funcname():
    """SUTS의 SwUFn↔함수명이 없으면 SITS 2-hop이 성립 안 함 (경계)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    sits_row = {"requirement_id": "SwITC_0101", "testcase": "SWIT_SWUFN_0101_DEPTH4",
                "source": "SITS"}
    mx = generate_uds_traceability_matrix(items, sds_pairs=sds_pairs, sits_rows=[sits_row])
    assert mx["rows"][0]["sits_count"] == 0


def test_direct_id_match_still_works():
    """동일 ID 프로젝트(UDS req_id == SRS req_id)는 SDS 없이도 직접 매핑 유지."""
    items = [{"id": "SwTR_0101"}]
    mapping_pairs = [{"requirement_id": "SwTR_0101", "source_ids": ["direct_func"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs)
    row = mx["rows"][0]
    assert "direct_func" in row["source_ids"]


# ── VectorCAST 함수기반 bridge (신규) ────────────────────────────────────
# vcast 행은 subprogram(거의 SwUFn ID)만 들고 오므로, SUTS/SITS와 동일하게
# 함수명→SRS bridge로 SRS 요구사항에 간접 연결한다. 그 동작/카운트를 고정.


def test_vcast_two_hop_bridge_via_swufn():
    """vcast subprogram(SwUFn) → (SUTS)함수명 → (SDS)SRS 2-hop 으로 indirect/fuzzy 추적."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts_row = {"requirement_id": "SwUFn_0101", "testcase": "SwUTC_01",
                "unit": "foo_func", "source": "SUTS"}
    vcast_row = {"subprogram": "SwUFn_0101", "testcase": "SwUFn_0101 (3 TC)",
                 "result": "pass", "source": "VectorCAST"}
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=[suts_row, vcast_row], sds_pairs=sds_pairs)
    row = mx["rows"][0]
    assert row["vcast_count"] >= 1
    vc = [t for t in row["tests"] if t.get("source") == "VectorCAST"]
    assert vc and all(t.get("trace_type") == "indirect" for t in vc)
    assert all(t.get("confidence") == "fuzzy" for t in vc)
    assert mx["summary"]["vcast_input_rows"] == 1
    assert mx["summary"]["vcast_traced_rows"] == 1
    assert mx["summary"]["vcast_untraced_rows"] == 0


def test_vcast_direct_funcname_match():
    """subprogram이 함수명이면 SDS 함수명 bridge로 직접 매칭(2-hop 불필요)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    vcast_row = {"subprogram": "foo_func", "testcase": "foo_func",
                 "result": "pass", "source": "VectorCAST"}
    mx = generate_uds_traceability_matrix(items, vcast_rows=[vcast_row], sds_pairs=sds_pairs)
    assert mx["rows"][0]["vcast_count"] >= 1
    assert mx["summary"]["vcast_traced_rows"] == 1


def test_vcast_untraced_not_in_matrix_but_counted():
    """SRS 추적 대상 아닌 함수(부트로더/ISR 등)는 매트릭스에서 빠지되 untraced로 카운트."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # SwIFn은 swufn_to_func(=SUTS)에 없어 2-hop no-op, 함수명 직접 매칭도 없음
    vcast_row = {"subprogram": "SwIFn_9999", "testcase": "SwIFn_9999",
                 "result": "pass", "source": "VectorCAST"}
    mx = generate_uds_traceability_matrix(items, vcast_rows=[vcast_row], sds_pairs=sds_pairs)
    assert mx["rows"][0]["vcast_count"] == 0
    assert mx["summary"]["vcast_input_rows"] == 1
    assert mx["summary"]["vcast_traced_rows"] == 0
    assert mx["summary"]["vcast_untraced_rows"] == 1


def test_vcast_dedup_keeps_distinct_subprograms_same_testcase():
    """서로 다른 subprogram이 같은 testcase 명으로 같은 req에 bridge돼도 둘 다 유지
    (dedup 키에 subprogram 포함 — silent drop 방지)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [{"requirement_id": "SwUFn_0101", "unit": "foo_func", "source": "SUTS", "testcase": "u1"},
            {"requirement_id": "SwUFn_0102", "unit": "foo_func", "source": "SUTS", "testcase": "u2"}]
    vcast = [{"subprogram": "SwUFn_0101", "testcase": "SHARED", "result": "pass", "source": "VectorCAST"},
             {"subprogram": "SwUFn_0102", "testcase": "SHARED", "result": "fail", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    vc = [t for t in mx["rows"][0]["tests"] if t.get("source") == "VectorCAST"]
    assert len(vc) == 2


def test_vcast_mixed_confidence_with_exact_sts():
    """STS exact + VectorCAST fuzzy 공존 시 confidence='mixed' (의도된 표시)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    sts_row = {"requirement_id": "SwTR_0101", "testcase": "STS_TC_1", "source": "STS"}
    suts_row = {"requirement_id": "SwUFn_0101", "unit": "foo_func", "source": "SUTS", "testcase": "u1"}
    vcast_row = {"subprogram": "SwUFn_0101", "testcase": "v1", "result": "pass", "source": "VectorCAST"}
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=[sts_row, suts_row, vcast_row], sds_pairs=sds_pairs)
    row = mx["rows"][0]
    assert row["sts_direct"] >= 1
    assert row["vcast_count"] >= 1
    assert row["confidence"] == "mixed"
