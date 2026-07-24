"""Regression: SDS 함수명 bridge in generate_uds_traceability_matrix.

UDS는 함수를 설계레벨 ID(SwSTR 등)에, SUTS/SITS는 단위 ID에 추적해 SRS 요구사항
(SwTR/SwEI 등)과 직접 안 맞는다. SDS의 component_ids에는 함수명이 들어 있어
"SRS요구사항→함수명"을 제공하므로, 이를 역으로 써서 UDS 함수(source_ids)와
SUTS/SITS unit을 SRS 행에 연결한다(사용자 결정: "SDS로 bridge"). 그 동작을 고정.
"""
from __future__ import annotations

import pytest

from report_gen.requirements import (
    _classify_unmapped_layer,
    _extract_requirement_blocks,
    _normalize_req_id,
    _safe_docx_open,
    _sds_comp_key,
    _strip_ret_type_prefix,
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


# ── UDS(단위설계) 연동 신호 — SRS 미추적이어도 함수가 단위설계엔 존재하는지 ──────────
# 사용자 질문("SDS 미추적이어도 UDS엔 연동돼 있나"). SRS 역추적이 끊긴 함수라도 UDS
# 인벤토리에 있으면 '시험+단위설계 완료, SDS 아키텍처 roll-up만 누락'(정당한 입도차),
# 없으면 시험만 존재하는 진짜 설계 공백으로 구분한다. KJPDS02 실데이터 661 UDS연동/1 갭.


def test_unmapped_vcast_in_uds_via_resolved_func():
    """미추적 SwUFn이 SUTS로 함수명 해석되고 그 함수가 UDS 인벤토리에 있으면
    in_uds=True, uds_funcs=[정규 함수명], summary unmapped_uds_linked=1."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # SwUFn_0200 은 SDS에 없어 SRS 미추적이지만, SUTS로 s_sha256_transform 해석되고
    # 그 함수는 UDS 단위설계 인벤토리에 존재한다.
    suts = [{"requirement_id": "SwUFn_0200", "unit": "s_sha256_transform", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0200", "testcase": "SwUFn_0200", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=suts + vcast, sds_pairs=sds_pairs,
        uds_function_ids=["s_sha256_transform", "other_func"],
    )
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    entry = by_sub["SwUFn_0200"]
    assert entry["in_uds"] is True
    assert entry["uds_funcs"] == ["s_sha256_transform"]
    assert mx["summary"]["unmapped_uds_linked"] == 1
    assert mx["summary"]["unmapped_design_gap"] == 0


def test_unmapped_vcast_design_gap_when_not_in_uds():
    """해석된 함수가 UDS 인벤토리에도 없으면 in_uds=False(진짜 설계 공백) +
    summary unmapped_design_gap 카운트. 모든 항목이 in_uds/uds_funcs 키를 갖는다."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # 해석은 되지만(ghost_unit) UDS 인벤토리엔 없음 → 진짜 갭
    suts = [{"requirement_id": "SwUFn_0300", "unit": "ghost_unit", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0300", "testcase": "SwUFn_0300", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=suts + vcast, sds_pairs=sds_pairs,
        uds_function_ids=["unrelated_func"],
    )
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    entry = by_sub["SwUFn_0300"]
    assert entry["in_uds"] is False
    assert entry["uds_funcs"] == []
    assert all("in_uds" in u and "uds_funcs" in u for u in mx["unmapped_vcast"])
    assert mx["summary"]["unmapped_design_gap"] == 1
    assert mx["summary"]["unmapped_uds_linked"] == 0


def test_unmapped_app_design_gap_is_app_leaf_and_not_in_uds():
    """진짜 '실 finding' = APP_LEAF ∩ 미설계(in_uds=False) — layer축(app_leaf 전체)이 아니라 design축.
    design_gap(전 계층 미설계)과 구별: LIB 계층의 미설계 함수는 design_gap엔 잡히나 app_design_gap엔 안 잡힌다."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # (a) 앱 leaf(도메인명), UDS에도 없음 → 진짜 앱 갭(app_design_gap)
    suts_a = [{"requirement_id": "SwUFn_0400", "unit": "s_appleaf_ctrl", "source": "SUTS", "testcase": "u1"}]
    vc_a = [{"subprogram": "SwUFn_0400", "testcase": "SwUFn_0400", "result": "pass", "source": "VectorCAST"}]
    # (b) LIB(crc32) 계층, UDS에도 없음 → design_gap이나 app_design_gap 아님(정당한 범위경계)
    suts_b = [{"requirement_id": "SwUFn_0401", "unit": "s_crc32_calc", "source": "SUTS", "testcase": "u2"}]
    vc_b = [{"subprogram": "SwUFn_0401", "testcase": "SwUFn_0401", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=suts_a + vc_a + suts_b + vc_b, sds_pairs=sds_pairs,
        uds_function_ids=["unrelated_func"],  # 둘 다 UDS 인벤토리에 없음
    )
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0400"]["layer"] == "APP_LEAF" and by_sub["SwUFn_0400"]["in_uds"] is False
    assert by_sub["SwUFn_0401"]["layer"] == "LIB_UTIL" and by_sub["SwUFn_0401"]["in_uds"] is False
    assert mx["summary"]["unmapped_design_gap"] == 2       # 둘 다 미설계(전 계층)
    assert mx["summary"]["unmapped_app_design_gap"] == 1   # 진짜 앱 갭은 (a)만 — 라벨축 정직화의 핵심


def test_unmapped_vcast_swufn_id_echo_not_counted_as_uds():
    """★UDS 인벤토리가 SwUFn ID도 포함(함수명+ID)하므로, subprogram이 SwUFn ID인 경우
    그 ID 자기-매칭(메아리)을 in_uds로 오인하면 안 된다. 함수명 해석이 없으면 in_uds=False."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    # SUTS 해석 없음. uds_function_ids에 SwUFn ID 자체가 들어있어도 echo로 in_uds 되면 안 됨.
    vcast = [{"subprogram": "SwUFn_0500", "testcase": "SwUFn_0500", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(
        items, vcast_rows=vcast, sds_pairs=sds_pairs,
        uds_function_ids=["SwUFn_0500", "real_func"],  # ID echo 함정
    )
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    entry = by_sub["SwUFn_0500"]
    assert entry["in_uds"] is False        # ID 메아리는 신호 아님
    assert entry["uds_funcs"] == []
    assert mx["summary"]["unmapped_uds_linked"] == 0


# ── 반환형 헝가리안 접두사 불일치 보정 (라운드111) ────────────────────────────
# SDS는 'u16s_MotorSpdCtrl_AutoOpen'(반환형 접두사)으로, 테스트/VectorCAST는
# 's_MotorSpdCtrl_AutoOpen'으로 표기해 정확매칭 bridge가 끊겨 도어모터 4함수가
# 각 11개 SRS 요구사항 추적을 잃던 실버그를 base alias로 복구. 단 base가 별도 SDS
# 키로 존재하면(서로 다른 함수 가능) alias 생략해 거짓 병합을 막는다(충돌 안전).


def test_strip_ret_type_prefix_helper():
    """반환형 토큰(u8/u16/u32/s8/s16/s32)만 제거, 저장클래스(s/g/l) 직전일 때만."""
    assert _strip_ret_type_prefix("u16s_motorspdctrl_autoopen") == "s_motorspdctrl_autoopen"
    assert _strip_ret_type_prefix("u8g_drvin_datavalidation_f") == "g_drvin_datavalidation_f"
    assert _strip_ret_type_prefix("s16g_doorprectrl_slopelvl") == "g_doorprectrl_slopelvl"
    # 저장클래스 접두사 없는 'u8_foo'는 건드리지 않음('_foo' 오염 방지)
    assert _strip_ret_type_prefix("u8_foo") == "u8_foo"
    # 접두사 없는 일반 함수 불변
    assert _strip_ret_type_prefix("s_sha256_transform") == "s_sha256_transform"
    assert _strip_ret_type_prefix("g_lib_init") == "g_lib_init"


def test_sds_ret_type_prefix_alias_bridges_unprefixed_test_func():
    """SDS 'u16s_X' ↔ 테스트 's_X' 불일치를 base alias로 연결 → SRS 추적 복구."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["u16s_MotorSpdCtrl_AutoOpen"]}]
    suts = [{"requirement_id": "SwUFn_0500", "unit": "s_motorspdctrl_autoopen", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0500", "testcase": "SwUFn_0500", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    # 미추적에서 빠지고(추적됨) SwTR_0101 행에 VectorCAST 추적으로 연결
    subs = {u["subprogram"] for u in mx["unmapped_vcast"]}
    assert "SwUFn_0500" not in subs
    row = next(r for r in mx["rows"] if _normalize_req_id(r["requirement_id"]) == "SWTR_0101")
    assert row.get("vcast_count", 0) > 0


def test_sds_ret_type_prefix_alias_skipped_on_collision():
    """base가 별도 SDS 키로 이미 존재하면 alias 생략 — 서로 다른 함수일 수 있어 거짓
    req 병합을 막는다(충돌 안전, under-trace가 over-trace보다 안전한 ISO 기본값)."""
    items = [{"id": "SwTR_0101"}, {"id": "SwTR_0202"}]
    sds_pairs = [
        {"requirement_id": "SwTR_0101", "component_ids": ["g_foo"]},      # 정확형
        {"requirement_id": "SwTR_0202", "component_ids": ["u16g_foo"]},   # 접두사형(다른 req)
    ]
    suts = [{"requirement_id": "SwUFn_0600", "unit": "g_foo", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0600", "testcase": "SwUFn_0600", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    r101 = next(r for r in mx["rows"] if _normalize_req_id(r["requirement_id"]) == "SWTR_0101")
    r202 = next(r for r in mx["rows"] if _normalize_req_id(r["requirement_id"]) == "SWTR_0202")
    assert r101.get("vcast_count", 0) > 0   # g_foo 테스트 → 0101 연결(정확매칭)
    assert r202.get("vcast_count", 0) == 0  # u16g_foo의 0202로 alias 누수 없음


def test_sds_ret_type_prefix_alias_skipped_on_multi_prefix_collapse():
    """2+ 접두사형(u8g_X·s8g_X — 반환형 다른 별개 함수 가능)이 같은 base로 모이면 alias
    생략 — 서로 다른 함수 req의 union(거짓연결) 방지(라운드111 강화). 실데이터
    g_doorctrl_slipchkspd(u8g_/s8g_) 케이스."""
    items = [{"id": "SwTR_0101"}, {"id": "SwTR_0202"}]
    sds_pairs = [
        {"requirement_id": "SwTR_0101", "component_ids": ["u8g_foo"]},
        {"requirement_id": "SwTR_0202", "component_ids": ["s8g_foo"]},
    ]
    suts = [{"requirement_id": "SwUFn_0700", "unit": "g_foo", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0700", "testcase": "SwUFn_0700", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    resolved = set()
    for u in mx["unmapped_vcast"]:
        for f in (u.get("resolved_funcs") or []):
            resolved.add(f.lower())
    assert "g_foo" in resolved              # 모호 → alias 생략 → 여전히 미추적
    r101 = next(r for r in mx["rows"] if _normalize_req_id(r["requirement_id"]) == "SWTR_0101")
    r202 = next(r for r in mx["rows"] if _normalize_req_id(r["requirement_id"]) == "SWTR_0202")
    assert r101.get("vcast_count", 0) == 0  # 어느 쪽으로도 거짓연결 안 됨
    assert r202.get("vcast_count", 0) == 0


# ── ASIL 안전기제 safety 플래그 — 해석함수명 적용 + default 오탐 방지 (라운드111) ──
# safety 플래그가 subprogram(대개 SwUFn ID, 안전토큰 無)에만 적용돼 ASIL 자가진단·가드
# 함수가 amber 검토우선에 안 걸리던 누락을 보강. + 'default' 속 'fault' 부분일치 오탐 방지.


def test_safety_flag_via_resolved_func_name():
    """safety는 SwUFn ID subprogram이어도 SUTS 해석 함수명(s_StackGuardCheck)에 적용된다."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [{"requirement_id": "SwUFn_0900", "unit": "s_StackGuardCheck", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0900", "testcase": "SwUFn_0900", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0900"]["safety"] is True
    assert mx["summary"]["unmapped_safety"] >= 1


def test_safety_flag_no_false_positive_on_default():
    """'HandleDefault' 속 'fault' 부분일치로 거짓 safety 플래그되면 안 됨((?<!de)fault)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [{"requirement_id": "SwUFn_0901", "unit": "s_MotorBattShortRun_HandleDefault", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0901", "testcase": "SwUFn_0901", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0901"]["safety"] is False


def test_safety_flag_guarded_arithmetic_and_genuine_fault():
    """ASIL 방어적 가드 연산(*_Guarded)·진짜 fault(ClearFaults)는 flag(거짓 default와 구분)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [
        {"requirement_id": "SwUFn_0902", "unit": "u32s_ApiIn_AddU32_Guarded", "source": "SUTS", "testcase": "u1"},
        {"requirement_id": "SwUFn_0903", "unit": "s_DriveIC_ClearFaults", "source": "SUTS", "testcase": "u2"},
    ]
    vcast = [
        {"subprogram": "SwUFn_0902", "testcase": "SwUFn_0902", "result": "pass", "source": "VectorCAST"},
        {"subprogram": "SwUFn_0903", "testcase": "SwUFn_0903", "result": "pass", "source": "VectorCAST"},
    ]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0902"]["safety"] is True   # guarded 연산
    assert by_sub["SwUFn_0903"]["safety"] is True   # clearfaults (진짜 fault)


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


# ── ISO 26262 미추적 함수 계층(layer) 분류 (라운드112) ────────────────────────
# 미추적 함수를 'SwDS가 어느 계층에서 명세해야 하는가'로 분류해 '애플리케이션 설계 공백
# (APP_LEAF=실 finding)'과 '정당한 범위 경계(BSW/부트/라이브러리)'를 정직히 구분한다.


def test_classify_unmapped_layer_helper():
    """계층 분류기: 인프라(부트/BSW/라이브러리)는 잡고, 애플리케이션은 기본값 APP_LEAF."""
    # BOOT/REPROG/EEPROM (선두 앵커)
    assert _classify_unmapped_layer(["sf_runcrc32verification"]) == "BOOT_REPROG"
    assert _classify_unmapped_layer(["s_syseepromctrl_writedata_direct"]) == "BOOT_REPROG"
    assert _classify_unmapped_layer(["eepromreadversiondata"]) == "BOOT_REPROG"
    # BSW/driver/HAL
    assert _classify_unmapped_layer(["adc_monitor_init"]) == "BSW_DRIVER"
    assert _classify_unmapped_layer(["s_drvin_spi_writedrv8706"]) == "BSW_DRIVER"
    assert _classify_unmapped_layer(["lin_lld_sci_init"]) == "BSW_DRIVER"
    # LIB/util
    assert _classify_unmapped_layer(["s_sha256_transform"]) == "LIB_UTIL"
    assert _classify_unmapped_layer(["s16s_latgforce2slope_conv"]) == "LIB_UTIL"
    # APP_LEAF (기본값 = 검토 대상). 애플리케이션 leaf — 인프라 토큰 없음.
    assert _classify_unmapped_layer(["u16s_motorcurrent_check"]) == "APP_LEAF"
    assert _classify_unmapped_layer(["s_isdoorclosed"]) == "APP_LEAF"
    assert _classify_unmapped_layer(["u8s_countup_guarded"]) == "APP_LEAF"  # 안전은 직교 플래그
    # 빈 입력 → 안전측 기본값
    assert _classify_unmapped_layer([]) == "APP_LEAF"
    # TEST_ARTIFACT — 순수 C 식별자 아님 / range-test 산출물
    assert _classify_unmapped_layer(["Range"]) == "TEST_ARTIFACT"
    assert _classify_unmapped_layer(["<<INIT>>"]) == "TEST_ARTIFACT"


def test_classify_layer_does_not_swallow_app_function_with_midword_eeprom():
    """중간에 'eeprom'이 든 애플리케이션 함수를 BOOT로 잘못 삼키면 안 됨(공백 은닉 방지)."""
    # 앵커(^eep)가 아니라 중간 'eeprom' — 애플리케이션 previousctrl 리셋
    assert _classify_unmapped_layer(["s_ap_previousctrl_reseteepromparams"]) == "APP_LEAF"


def test_unmapped_layer_field_and_summary_counts():
    """unmapped_vcast 각 항목에 layer 필드 + summary layer 카운트가 합이 맞아야."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [
        {"requirement_id": "SwUFn_0910", "unit": "u16s_motorcurrent_check", "source": "SUTS", "testcase": "u1"},
        {"requirement_id": "SwUFn_0911", "unit": "sf_runcrc32verification", "source": "SUTS", "testcase": "u2"},
        {"requirement_id": "SwUFn_0912", "unit": "adc_monitor_init", "source": "SUTS", "testcase": "u3"},
    ]
    vcast = [
        {"subprogram": "SwUFn_0910", "testcase": "SwUFn_0910", "result": "pass", "source": "VectorCAST"},
        {"subprogram": "SwUFn_0911", "testcase": "SwUFn_0911", "result": "pass", "source": "VectorCAST"},
        {"subprogram": "SwUFn_0912", "testcase": "SwUFn_0912", "result": "pass", "source": "VectorCAST"},
    ]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0910"]["layer"] == "APP_LEAF"
    assert by_sub["SwUFn_0911"]["layer"] == "BOOT_REPROG"
    assert by_sub["SwUFn_0912"]["layer"] == "BSW_DRIVER"
    s = mx["summary"]
    layer_sum = (
        s["unmapped_layer_app_leaf"]
        + s["unmapped_layer_bsw_driver"]
        + s["unmapped_layer_boot_reprog"]
        + s["unmapped_layer_lib_util"]
        + s["unmapped_layer_test_artifact"]
        + s["unmapped_layer_unresolved"]   # §H: 분류불가 6번째 버킷(정합식 유지)
    )
    assert layer_sum == s["unmapped_vcast_count"]
    assert s["unmapped_layer_app_leaf"] >= 1
    assert s["unmapped_layer_boot_reprog"] >= 1
    assert s["unmapped_layer_bsw_driver"] >= 1


def test_safety_flag_e2e_crc_clock_range_monitors():
    """라운드112: E2E/CRC/range/CPU클록 안전·무결성 기제가 safety 플래그된다."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [
        {"requirement_id": "SwUFn_0920", "unit": "u8s_e2e_ac_profilecheck_sbcm0", "source": "SUTS", "testcase": "u1"},
        {"requirement_id": "SwUFn_0921", "unit": "u8g_lib_u16bit_rangecheck", "source": "SUTS", "testcase": "u2"},
        {"requirement_id": "SwUFn_0922", "unit": "u8s_cpupllstatuscheck", "source": "SUTS", "testcase": "u3"},
        {"requirement_id": "SwUFn_0923", "unit": "sf_runcrc32verification", "source": "SUTS", "testcase": "u4"},
    ]
    vcast = [
        {"subprogram": f"SwUFn_092{i}", "testcase": f"SwUFn_092{i}", "result": "pass", "source": "VectorCAST"}
        for i in range(4)
    ]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0920"]["safety"] is True  # E2E profile check
    assert by_sub["SwUFn_0921"]["safety"] is True  # range check
    assert by_sub["SwUFn_0922"]["safety"] is True  # CPU PLL status monitor
    assert by_sub["SwUFn_0923"]["safety"] is True  # CRC32 verification


def test_safety_flag_no_false_positive_on_write2eeprom():
    """'writE2Eeprom'(write2eeprom) 속 'e2e' substring으로 거짓 safety 플래그되면 안 됨."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["foo_func"]}]
    suts = [{"requirement_id": "SwUFn_0930", "unit": "s_write2eeprom_partno", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_0930", "testcase": "SwUFn_0930", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    by_sub = {u["subprogram"]: u for u in mx["unmapped_vcast"]}
    assert by_sub["SwUFn_0930"]["safety"] is False


def test_sds_comp_key_strips_leading_underscore():
    """_sds_comp_key는 선행 언더스코어를 제거해 '_entrypoint'↔'entrypoint' bridge를 잇는다."""
    assert _sds_comp_key("_entrypoint") == "entrypoint"
    assert _sds_comp_key("entrypoint") == "entrypoint"
    # 일반 함수는 불변(선행 _ 없음)
    assert _sds_comp_key("s_motorstatectrl") == "s_motorstatectrl"
    # 전부 언더스코어/빈값은 버려짐
    assert _sds_comp_key("___") == ""


def test_leading_underscore_func_bridges_to_matrix():
    """SDS 'entrypoint' ↔ 테스트 '_entrypoint'(선행 _) 정규화 불일치로 끊겼던 SRS 추적 복구.

    SwUFn → (SUTS)'_entrypoint' → (SDS)'entrypoint' → 매트릭스 req(SwTR_0106) 2-hop 완전 bridge.
    """
    items = [{"id": "SwTR_0106"}]
    # SDS는 'entrypoint'(선행 _ 없음)로 명세
    sds_pairs = [{"requirement_id": "SwTR_0106", "component_ids": ["swcom_35", "entrypoint"]}]
    # SUTS unit은 '_entrypoint'(선행 _) — 정규화 불일치
    suts = [{"requirement_id": "SwUFn_1710", "unit": "_entrypoint", "source": "SUTS", "testcase": "u1"}]
    vcast = [{"subprogram": "SwUFn_1710", "testcase": "SwUFn_1710", "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(items, vcast_rows=suts + vcast, sds_pairs=sds_pairs)
    # 매트릭스 req로 완전 bridge → 미추적 목록에 없어야
    assert all(u["subprogram"] != "SwUFn_1710" for u in mx["unmapped_vcast"])
    row = mx["rows"][0]
    assert row["requirement_id"] == "SwTR_0106"
    assert row["test_count"] >= 1  # _entrypoint 시험이 SRS 행에 연결됨


# ── 설계-ID bridge(SRS→SDS→UDS, SwFn/SwSTR/SwST/SwTK; SwCom 제외) ──
# UDS 함수의 Related ID 설계ID를 SDS의 설계ID→SRS요구 매핑으로 이어 UDS 밴드에 부착.
# 여기 함수명(foo_func 등)은 SDS component_ids에 없으므로 name-bridge로는 안 붙고,
# 오직 설계ID bridge로만 붙는다 → 이 경로를 단독 고정한다.

def test_design_id_bridge_swfn_attaches_but_swcom_does_not():
    """load-bearing: SwFn(tight)은 브리지되고 SwCom(loose)은 제외된다."""
    items = [{"id": "SwTR_0101"}]
    # SDS: SwTR_0101을 설계ID SwFn_05·SwCom_03에 귀속
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["SwFn_05", "SwCom_03"]}]
    # UDS Related ID: SwFn_05는 foo_func가, SwCom_03은 comp_only_func가 참조
    mapping_pairs = [
        {"requirement_id": "SwFn_05", "source_ids": ["foo_func"]},
        {"requirement_id": "SwCom_03", "source_ids": ["comp_only_func"]},
    ]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    row = mx["rows"][0]
    # SwFn bridge → foo_func 부착 (mutation A: 2c 주입 제거 시 실패)
    assert "foo_func" in row["source_ids"]
    # SwCom 제외 → comp_only_func 미부착 (mutation B: 정규식에 COM 추가 시 실패)
    assert "comp_only_func" not in row["source_ids"]
    # SDS 경유 '추정'이라 direct엔 안 들어감 (over-trace 안전판)
    assert row.get("source_ids_direct") == []


def test_design_id_bridge_swstr_swst_swtk():
    """SwSTR/SwST/SwTK 세 tight namespace 모두 브리지된다."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101",
                  "component_ids": ["SwSTR_02", "SwST_03", "SwTK_04"]}]
    mapping_pairs = [
        {"requirement_id": "SwSTR_02", "source_ids": ["str_func"]},
        {"requirement_id": "SwST_03", "source_ids": ["st_func"]},
        {"requirement_id": "SwTK_04", "source_ids": ["tk_func"]},
    ]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    sids = mx["rows"][0]["source_ids"]
    assert "str_func" in sids and "st_func" in sids and "tk_func" in sids


def test_design_id_bridge_ignores_non_matrix_req():
    """설계ID가 매트릭스 밖 요구(SwTR_9999)에만 귀속되면 브리지 안 함(req_id_set 게이트)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_9999", "component_ids": ["SwFn_05"]}]
    mapping_pairs = [{"requirement_id": "SwFn_05", "source_ids": ["foo_func"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    assert "foo_func" not in (mx["rows"][0]["source_ids"] or [])


def test_design_id_bridge_excludes_swufn_id_value():
    """source_ids의 자기 SwUFn ID 값은 밴드에서 제외(함수명만 부착)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["SwFn_05"]}]
    # 파서는 source_ids에 함수명 + 자기 SwUFn ID를 함께 넣는다
    mapping_pairs = [{"requirement_id": "SwFn_05", "source_ids": ["foo_func", "SwUFn_0203"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    sids = mx["rows"][0]["source_ids"]
    assert "foo_func" in sids
    assert "SwUFn_0203" not in sids


def test_design_id_bridge_excludes_junk_field_labels():
    """source_ids에 필드라벨 junk('Name'/'ID')가 있어도 요구에 부착되지 않는다 (deep-review C1 방어심층).

    파서 echo 가드가 1차 차단하나, 문서군 편차로 junk가 mapping_pairs에 새어도 bridge가
    막는지 고정. mutation: _UDS_FUNC_JUNK를 비우면 이 테스트 실패.
    """
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["SwFn_05"]}]
    mapping_pairs = [{"requirement_id": "SwFn_05", "source_ids": ["real_fn", "Name", "ID"]}]
    mx = generate_uds_traceability_matrix(items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs)
    sids = mx["rows"][0]["source_ids"]
    assert "real_fn" in sids
    assert "Name" not in sids and "ID" not in sids


# ── SUTS/VectorCAST test-row 설계-ID 브리지 (UDS 브리지의 test-arm 확장) ──
# 시험 함수가 SDS에 이름은 없지만 UDS Related ID 설계ID(SwFn 등)로 SRS에 닿는 경우를
# name-bridge가 놓치던 것을 보완. SUTS/VectorCAST 밴드 43→64.

def test_suts_design_id_bridge():
    """SUTS unit 함수가 UDS 설계ID(SwFn)로 SRS에 연결(SDS에 이름 없어 name-bridge는 미스)."""
    items = [{"id": "SwTR_0101"}]
    # SDS는 설계ID SwFn_05로만 귀속(함수명 foo_func는 SDS에 없음)
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["SwFn_05"]}]
    mapping_pairs = [{"requirement_id": "SwFn_05", "source_ids": ["foo_func"]}]
    suts = [{"requirement_id": "SwUFn_01", "unit": "foo_func", "source": "SUTS", "testcase": "t1"}]
    mx = generate_uds_traceability_matrix(
        items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs, vcast_rows=suts)
    row = mx["rows"][0]
    assert row["suts_count"] >= 1            # 설계ID 브리지로만 도달 (mutation: 미배선→0)
    assert any(t.get("trace_type") == "indirect" for t in row["suts_tests"])


def test_vcast_design_id_bridge():
    """VectorCAST subprogram(SwUFn)→(SUTS)함수명→(UDS 설계ID)→SRS 로 연결."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["SwFn_05"]}]
    mapping_pairs = [{"requirement_id": "SwFn_05", "source_ids": ["foo_func"]}]
    suts = [{"requirement_id": "SwUFn_01", "unit": "foo_func", "source": "SUTS", "testcase": "s1"}]
    vcast = [{"subprogram": "SwUFn_01", "testcase": "SwUFn_01 (2 TC)",
              "result": "pass", "source": "VectorCAST"}]
    mx = generate_uds_traceability_matrix(
        items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs, vcast_rows=suts + vcast)
    assert mx["rows"][0]["vcast_count"] >= 1
    assert mx["summary"]["vcast_traced_rows"] == 1
    assert mx["summary"]["vcast_untraced_rows"] == 0


def test_suts_vcast_design_bridge_swcom_excluded():
    """test-row 설계-ID 브리지도 SwCom은 제외한다(UDS와 동일 안전판 상속)."""
    items = [{"id": "SwTR_0101"}]
    sds_pairs = [{"requirement_id": "SwTR_0101", "component_ids": ["SwCom_03"]}]
    mapping_pairs = [{"requirement_id": "SwCom_03", "source_ids": ["comp_fn"]}]
    suts = [{"requirement_id": "SwUFn_01", "unit": "comp_fn", "source": "SUTS", "testcase": "t1"}]
    mx = generate_uds_traceability_matrix(
        items, mapping_pairs=mapping_pairs, sds_pairs=sds_pairs, vcast_rows=suts)
    assert mx["rows"][0]["suts_count"] == 0   # SwCom 제외 → 브리지 안 됨
