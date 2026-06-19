"""Regression: SDS 함수명 bridge in generate_uds_traceability_matrix.

UDS는 함수를 설계레벨 ID(SwSTR 등)에, SUTS/SITS는 단위 ID에 추적해 SRS 요구사항
(SwTR/SwEI 등)과 직접 안 맞는다. SDS의 component_ids에는 함수명이 들어 있어
"SRS요구사항→함수명"을 제공하므로, 이를 역으로 써서 UDS 함수(source_ids)와
SUTS/SITS unit을 SRS 행에 연결한다(사용자 결정: "SDS로 bridge"). 그 동작을 고정.
"""
from __future__ import annotations

import pytest

from report_gen.requirements import (
    _extract_requirement_blocks,
    _normalize_req_id,
    _safe_docx_open,
    generate_uds_traceability_matrix,
)


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


def test_unmapped_vcast_categories():
    """미추적 VectorCAST subprogram이 unmapped_vcast에 의미 3버킷으로 분류되는지.
    역방향 추적성 공백(시험은 됐으나 이 SRS에 안 닿음) 가시화 — 트리 'SRS 미추적 시험' 루트."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [
        {"requirement_id": "SwUFn_0100", "unit": "foo_func", "source": "SUTS", "testcase": "u0"},
        # 미추적이지만 SUTS 단위시험 존재(함수명 해석됨) → suts_tested (검토 가치 ↑)
        {"requirement_id": "SwUFn_0200", "unit": "secret_hash", "source": "SUTS", "testcase": "u1"},
        # ISR 이름이면서 SUTS 단위시험도 존재 → resolved 우선이라 suts_tested여야(침묵 강등 방지)
        {"requirement_id": "SwUFn_0300", "unit": "my_func", "source": "SUTS", "testcase": "u2"},
    ]
    vcast = [
        {"subprogram": "SwUFn_0100", "testcase": "SwUFn_0100", "result": "pass", "source": "VectorCAST"},  # traced
        {"subprogram": "SwUFn_0200", "testcase": "SwUFn_0200", "result": "fail", "source": "VectorCAST"},  # suts_tested
        {"subprogram": "SwUFn_9999", "testcase": "SwUFn_9999", "result": "pass", "source": "VectorCAST"},  # vcast_only
        {"subprogram": "Tim0_Ch0_ISR", "testcase": "Tim0_Ch0_ISR", "result": "pass", "source": "VectorCAST"},  # isr (단위시험 없음)
        # subprogram이 ISR 이름(_handler)이지만 testcase의 SwUFn_0300이 SUTS로 해석됨 → suts_tested
        {"subprogram": "my_handler", "testcase": "SwUFn_0300", "result": "pass", "source": "VectorCAST"},
        # 'fault'를 부분문자열로 포함하지만 안전 관련 일반 함수 → 무경계 매치 제거로 isr 아님(vcast_only)
        {"subprogram": "default_config", "testcase": "default_config", "result": "pass", "source": "VectorCAST"},
    ]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    # traced된 SwUFn_0100은 미추적 목록에 없어야 한다
    assert "SwUFn_0100" not in by_sub
    assert by_sub["SwUFn_0200"]["category"] == "suts_tested"
    assert by_sub["SwUFn_0200"]["resolved_funcs"] == ["secret_hash"]
    assert by_sub["SwUFn_0200"]["result"] == "fail"
    assert by_sub["SwUFn_9999"]["category"] == "vcast_only"
    assert by_sub["Tim0_Ch0_ISR"]["category"] == "isr"
    # ★resolved 우선: ISR 이름이어도 단위시험이 있으면 suts_tested (침묵 강등 방지)
    assert by_sub["my_handler"]["category"] == "suts_tested"
    assert by_sub["my_handler"]["resolved_funcs"] == ["my_func"]
    # ★정밀 regex: 'default_config'는 'fault' 부분일치 제거로 isr 아님 → vcast_only
    assert by_sub["default_config"]["category"] == "vcast_only"
    # summary 버킷 카운트 (suts_tested 2, vcast_only 2, isr 1)
    assert mx["summary"]["unmapped_vcast_count"] == 5
    assert mx["summary"]["unmapped_suts_tested"] == 2
    assert mx["summary"]["unmapped_vcast_only"] == 2
    assert mx["summary"]["unmapped_isr"] == 1
    # 정렬: suts_tested(신호)가 맨 앞 — 잘림/상단 노출 시 우선 보이도록
    assert mx["unmapped_vcast"][0]["category"] == "suts_tested"


def test_unmapped_vcast_dedup_distinct_subprogram():
    """같은 subprogram이 여러 행으로 와도 미추적 목록엔 distinct 1개만(UI 중복 방지).
    카운트(vcast_*)는 행 기준 그대로, 목록만 dedup."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    vcast = [
        {"subprogram": "SwUFn_9999", "testcase": "tc1", "result": "pass", "source": "VectorCAST"},
        {"subprogram": "SwUFn_9999", "testcase": "tc2", "result": "fail", "source": "VectorCAST"},
    ]
    mx = generate_uds_traceability_matrix(items, vcast_rows=vcast, sds_pairs=sds_pairs)
    subs = [u["subprogram"] for u in mx["unmapped_vcast"]]
    assert subs.count("SwUFn_9999") == 1
    assert mx["summary"]["vcast_input_rows"] == 2          # 행 기준
    assert mx["summary"]["vcast_untraced_rows"] == 2       # 행 기준
    assert mx["summary"]["unmapped_vcast_count"] == 1      # distinct subprogram
    # ★W2: PASS(tc1) 선행 후 FAIL(tc2)이 와도 FAIL이 우선 보존돼야 한다
    # (worst-case 집계 — silent FAIL 손실로 트리 미추적 FAIL 카운트가 과소표시되는 것 방지)
    assert mx["unmapped_vcast"][0]["result"].lower() == "fail"


def test_unmapped_vcast_safety_handler_not_isr():
    """이름이 ISR/_handler 패턴이어도 안전·진단 토큰(fault/diag/safety 등)을 가지면
    isr(인프라, warn=false)로 침묵 강등하지 않고 vcast_only로 둔다 — 안전 핸들러의
    백워드 추적성 검토 신호 보존(재검증 W4). 순수 ISR(안전 토큰 없음)은 그대로 isr."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    vcast = [
        # 이름은 _handler(=ISR 패턴)지만 'fault' 안전 토큰 보유 + SUTS 단위시험 없음 + VectorCAST 단독
        {"subprogram": "Brake_Fault_Handler", "testcase": "tc1", "result": "fail", "source": "VectorCAST"},
        # 안전 토큰 없는 순수 ISR → 그대로 isr
        {"subprogram": "Tim0_Ch0_ISR", "testcase": "tc2", "result": "pass", "source": "VectorCAST"},
    ]
    mx = generate_uds_traceability_matrix(items, vcast_rows=vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["Brake_Fault_Handler"]["category"] == "vcast_only"  # isr로 강등 안 됨
    assert by_sub["Tim0_Ch0_ISR"]["category"] == "isr"
    # ★W4 가시화: 안전 토큰 보유 함수는 safety=True로 플래그(프론트 amber 강조용),
    # 순수 ISR은 False. summary.unmapped_safety도 동기.
    assert by_sub["Brake_Fault_Handler"]["safety"] is True
    assert by_sub["Tim0_Ch0_ISR"]["safety"] is False
    assert mx["summary"]["unmapped_safety"] == 1


# ── SDS 컴포넌트 추출 노이즈 정규화 (라운드 109) ──────────────────────────
# SDS 추출이 함수명에 C 시그니처 조각('( void')·배열 첨자('[10]')·표 아티팩트를
# 붙여 와서 정확매칭 bridge가 실제 함수의 SRS 추적을 silent 누락하던 회귀를 고정.


def test_sds_comp_signature_noise_normalized_recovers_trace():
    """SDS 컴포넌트 's_systemhashcalculate( void'(시그니처 조각 노이즈)가 정규화로
    정확매칭 복구돼 함수명 직접·SUTS 2-hop 양쪽 vcast 추적이 살아난다.
    실데이터 KJPDS02: 이 1함수가 14개 SRS 요구사항 추적을 끊었던 회귀."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["s_systemhashcalculate( void"]}]
    mapping_pairs = [{"requirement_id": "SwSTR_01", "source_ids": ["s_systemhashcalculate"]}]
    suts = [{"requirement_id": "SwUFn_0127", "unit": "s_systemhashcalculate",
             "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0127", "testcase": "v1", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(
        items, mapping_pairs=mapping_pairs, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    row = mx["rows"][0]
    # source_ids bridge 복구 (노이즈 이전엔 누락됐음)
    assert "s_systemhashcalculate" in row["source_ids"]
    # vcast 2-hop 추적 복구 → 미추적에서 빠짐
    assert "SwUFn_0127" not in {u["subprogram"] for u in mx["unmapped_vcast"]}
    assert mx["summary"]["vcast_traced_rows"] == 1
    assert mx["summary"]["vcast_untraced_rows"] == 0


def test_sds_comp_array_subscript_noise_normalized():
    """배열 첨자('[10]'/'[]')도 정규화 — 같은 변수의 [10]/[] 표기 차이가 동일 키로 매칭."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101",
                  "component_ids": ["u8g_partnoinfo[10]", "u8g_partnoinfo[]"]}]
    mapping_pairs = [{"requirement_id": "SwSTR_01", "source_ids": ["u8g_partnoinfo"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    assert "u8g_partnoinfo" in mx["rows"][0]["source_ids"]


def test_sds_comp_korean_description_not_falsely_bridged():
    """한글 설명문 컴포넌트('mcu 이상 감지(레지스터 미지원)')는 괄호 제거 후에도 공백 포함
    문자열이라 함수명 'mcu'와 불일치 → 거짓 bridge 없음(fuzzy 미사용 보장)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["mcu 이상 감지(레지스터 미지원)"]}]
    mapping_pairs = [{"requirement_id": "SwSTR_01", "source_ids": ["mcu"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    assert "mcu" not in (mx["rows"][0]["source_ids"] or [])


# ── 미추적 함수의 SDS 멤버십(sds_reqs) — 역방향 부분추적 표기 (라운드 109) ──


def test_unmapped_vcast_sds_reqs_populated_for_out_of_matrix_req():
    """SRS 미추적이지만 SDS가 매트릭스 밖 req(SwST_08 등)에 명세한 함수는
    sds_reqs가 채워져 'SDS 설계엔 닿음'(SRS만 끊김)을 노출한다."""
    items = [{"id": "SwTR_0101"}]  # 매트릭스 req = SwTR_0101 only
    sds_pairs = [
        {"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]},
        # SwST_08 은 items(매트릭스) 밖 → bar_func은 SRS 행엔 안 닿지만 SDS엔 명세됨
        {"requirement_id": "SwST_08", "component_ids": ["bar_func"]},
    ]
    suts = [{"requirement_id": "SwUFn_0200", "unit": "bar_func", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0200", "testcase": "v1", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    entry = by_sub["SwUFn_0200"]
    assert entry["category"] == "suts_tested"            # 단위시험 존재
    assert _normalize_req_id("SwST_08") in entry["sds_reqs"]  # SDS엔 명세(매트릭스 밖)
    assert mx["summary"]["unmapped_sds_linked"] == 1


def test_unmapped_vcast_sds_reqs_empty_when_absent_from_sds():
    """SDS 어디에도 명세 안 된 미추적 함수 → sds_reqs 빈 배열(프론트 '미명세' 표기).
    모든 미추적 항목이 sds_reqs 키를 갖는 스키마 일관성도 확인."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    vcast = [{"subprogram": "ghost_func", "testcase": "v1", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["ghost_func"]["sds_reqs"] == []
    assert all("sds_reqs" in u for u in mx["unmapped_vcast"])
    assert mx["summary"]["unmapped_sds_linked"] == 0


# ── 요구사항 제목(name) 추출 — 마크다운 헤딩 + 파이프 정제 (라운드110) ──────────
# SRS의 '#### SwTR_0101: Auto Close' 헤딩은 '#' 접두 때문에 파서가 통째로 무시하고,
# 표 파편의 빈/'| ' 잡음 name만 잡혀 요구사항 제목이 빈/잡음으로 표시되던 회귀를 고정.


def test_extract_blocks_captures_markdown_heading_title():
    """'#### SwTR_0101: Auto Close' 마크다운 헤딩에서 깨끗한 제목을 포착한다."""
    text = "\n".join([
        "## General Requirements",
        "### Door 동작 모드",
        "#### SwTR_0101: Auto Close",
        "#### SwTR_0106: 초기화 모드",
        "##### SwTSR_0101: Hall Sensor Power Switch 공급 전원 이상 감지",
    ])
    blocks = _extract_requirement_blocks(text)
    names = {b["id"]: b.get("name") for b in blocks if b.get("id")}
    assert names.get("SwTR_0101") == "Auto Close"
    assert names.get("SwTR_0106") == "초기화 모드"
    assert names.get("SwTSR_0101") == "Hall Sensor Power Switch 공급 전원 이상 감지"


def test_extract_blocks_strips_pipe_artifacts():
    """표 셀 추출로 'name'/'description'에 남는 '| ' 구분자 잡음을 정제한다."""
    text = "\n".join([
        "SwEI_01: | Battery Power Source",
        "Description | 배터리 전원 입력 신호",
    ])
    blocks = _extract_requirement_blocks(text)
    b = next(b for b in blocks if b.get("id") == "SwEI_01")
    assert "|" not in (b.get("name") or "")
    assert b.get("name") == "Battery Power Source"


def test_changelog_id_mention_not_captured_as_requirement():
    """'- SwTSR_0102 삭제' 같은 변경이력 언급은 요구사항으로 포착하지 않는다(삭제된 ID)."""
    text = "\n".join([
        "#### SwTR_0101: Auto Close",
        "- SwTSR_0102 삭제",
        "- SwNTR_0101 내용 수정",
    ])
    blocks = _extract_requirement_blocks(text)
    ids = {b.get("id") for b in blocks}
    assert "SwTR_0101" in ids
    assert "SwTSR_0102" not in ids   # changelog 언급 → 미포착


def test_matrix_requirement_name_picks_clean_longest():
    """매트릭스 행 requirement_name — ID당 파편(빈/제목) 중 정제 후 가장 긴 name 채택."""
    items = [
        {"id": "SwTR_0101", "name": ""},               # 빈 헤더 파편(먼저)
        {"id": "SwTR_0101", "name": "| Auto Close"},   # 표 파편(파이프)
        {"id": "SwTR_0101", "name": "Auto Close"},      # 헤딩 제목
    ]
    mx = generate_uds_traceability_matrix(items)
    row = next(r for r in mx["rows"] if r["requirement_id"] == "SwTR_0101")
    assert row["requirement_name"] == "Auto Close"     # 빈 첫 파편이 아니라 깨끗한 제목


# ── 손상 임베드 파트 복원 docx 로더 (라운드110) ───────────────────────────
# python-docx는 문서를 열 때 모든 파트를 eager 로드 → 깨진 임베드 이미지 1개로 문서 전체가
# 안 열린다. KJPDS02 SDS v2.03이 깨진 image*.png 32개로 sds_pairs=0 되던 회귀를 고정.


def test_safe_docx_open_recovers_from_corrupt_embedded_image():
    """본문은 멀쩡하고 임베드 이미지만 깨진 docx를 _safe_docx_open이 복원해 연다."""
    import io
    import struct
    import zipfile

    docx = pytest.importorskip("docx")
    # 표 + 이미지가 있는 정상 docx 생성
    d = docx.Document()
    tb = d.add_table(rows=1, cols=2)
    tb.rows[0].cells[0].text = "SC ID"
    tb.rows[0].cells[1].text = "SwCom_7"
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )
    d.add_picture(io.BytesIO(png))
    buf = io.BytesIO()
    d.save(buf)
    raw = bytearray(buf.getvalue())

    # 이미지 멤버의 압축 데이터 첫 바이트를 flip → read 시 CRC/zip 오류 유발(로컬헤더 정상,
    # 중앙디렉터리 정상 → 문서 구조는 열리되 그 멤버 read만 실패: 실제 v2.03 증상 재현)
    zin = zipfile.ZipFile(io.BytesIO(bytes(raw)))
    img = next(i for i in zin.infolist() if i.filename.startswith("word/media/"))
    off = img.header_offset
    n, m = struct.unpack("<HH", bytes(raw[off + 26:off + 30]))
    data_start = off + 30 + n + m
    for k in range(data_start, data_start + 6):
        raw[k] ^= 0xFF
    corrupt = bytes(raw)

    # 1) 일반 python-docx 열기는 실패해야(손상 멤버) — 전제 확인
    with pytest.raises(Exception):
        docx.Document(io.BytesIO(corrupt))
    # 2) _safe_docx_open은 손상 이미지를 우회해 열고, 본문 표가 읽혀야 한다
    doc = _safe_docx_open(io.BytesIO(corrupt))
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert "SwCom_7" in cells
