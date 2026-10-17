"""추적성 매트릭스의 UDS 함수 ASIL max-merge 검증(요구사항 ASIL under-report 해소).

generate_uds_traceability_matrix에 uds_function_asil을 주면, 요구사항에 연결된 UDS 소스함수의
ASIL이 comp_asil_map에 max-merge돼 요구사항 ASIL(row.asil, _asil_keys=sds_list+src_list 조회)에
반영된다. SDS 컴포넌트 ASIL만으론 UDS 함수 단위 안전등급(보안접근 등)이 누락돼 요구사항이
under-report되던 것을 해소. 안전 불변: max(등급 낮추기 없음)·미제공 시 기존 동작 불변.
"""
from __future__ import annotations

from report_gen.requirements import generate_uds_traceability_matrix


def _row(matrix: dict, rid: str) -> dict:
    for r in matrix.get("rows", []):
        if str(r.get("requirement_id")) == rid:
            return r
    raise AssertionError(f"row {rid} not found in matrix")


def test_matrix_reflects_uds_function_asil():
    """요구사항이 UDS 함수(A)에 연결·SDS 없음 → 요구사항 ASIL=A(uds_function_asil 반영)."""
    items = [{"id": "SwTR_001", "name": "보안 접근"}]
    mp = [{"requirement_id": "SwTR_001", "source_ids": ["s_uds_securityaccessalgorithm"]}]
    m = generate_uds_traceability_matrix(
        items, mapping_pairs=mp, component_asil={},
        uds_function_asil={"s_uds_securityaccessalgorithm": "A"},
    )
    assert _row(m, "SwTR_001")["asil"] == "A"


def test_matrix_uds_does_not_lower_sds():
    """SDS 컴포넌트=A, 같은 요구사항 UDS 함수=QM → max로 A 유지(등급 낮추기 없음)."""
    items = [{"id": "SwTR_002"}]
    mp = [{"requirement_id": "SwTR_002", "source_ids": ["s_foo"]}]
    sp = [{"requirement_id": "SwTR_002", "component_ids": ["comp_x"]}]
    m = generate_uds_traceability_matrix(
        items, mapping_pairs=mp, sds_pairs=sp,
        component_asil={"comp_x": "A"}, uds_function_asil={"s_foo": "QM"},
    )
    assert _row(m, "SwTR_002")["asil"] == "A"


def test_matrix_uds_raises_above_sds():
    """SDS 컴포넌트=QM, UDS 함수=A → max로 A 상향(under-report 해소 — 핵심 케이스)."""
    items = [{"id": "SwTR_003"}]
    mp = [{"requirement_id": "SwTR_003", "source_ids": ["s_safe"]}]
    sp = [{"requirement_id": "SwTR_003", "component_ids": ["comp_y"]}]
    m = generate_uds_traceability_matrix(
        items, mapping_pairs=mp, sds_pairs=sp,
        component_asil={"comp_y": "QM"}, uds_function_asil={"s_safe": "A"},
    )
    assert _row(m, "SwTR_003")["asil"] == "A"


def test_matrix_without_uds_asil_backward_compat():
    """uds_function_asil 미제공 → 기존 동작 불변(SDS/UDS ASIL 없으면 빈 문자열)."""
    items = [{"id": "SwTR_004"}]
    mp = [{"requirement_id": "SwTR_004", "source_ids": ["s_bar"]}]
    m = generate_uds_traceability_matrix(items, mapping_pairs=mp, component_asil={})
    assert _row(m, "SwTR_004").get("asil", "") == ""
