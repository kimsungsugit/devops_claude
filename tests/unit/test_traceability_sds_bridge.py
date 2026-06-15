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
