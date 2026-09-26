"""생성 공시(R77 N110) — `quality_report` → 화면이 읽는 항목 목록.

## 왜 이 테스트가 있나

STS/SUTS/SITS 생성기는 R71~R76 동안 "무엇을 자르고·비우고·못 했는가" 를 `quality_report` 에
계속 늘려 적었는데, 2026-09-20 실측으로 **`frontend-v2/src` 에서 그 키를 읽는 곳이 0건**이었다.
공시는 도달해야 공시다 — 이 파일은 그 도달 경로(생산자 dict → `build_disclosures` → evidence
섹션 → 엔드포인트)를 관측량으로 고정한다.

## 무엇을 겨누나

1. **0 과 부재는 다른 뜻이다.** 키가 없으면 항목을 만들지 않고(구판 산출물에 "0" 을 적으면
   "손실 없음" 이라는 거짓이 된다), 키가 있고 0 이면 "절단 없음" 을 적극적으로 말한다.
2. **비운 칸은 결함이 아니다.** `unknown_type_var_slots` 는 지어내지 않은 칸이라 `info` 이고,
   상한 절단·범위 충돌·보강 실패는 사람이 손대야 풀리므로 `warning` 이다. 둘을 같은 색으로
   접으면 "지어내지 않았다" 가 "잘못됐다" 로 읽힌다.
3. **STS 는 프로파일을 `generation_stats` 안에 적는다.** 최상위만 보던 첫 판은 실측 payload
   두 개(295 TC · 2,209 TC)에서 프로파일 줄이 통째로 사라졌다 — 화면에서 두 문서가 구별되지
   않는다. 아래 `TestStsProfileLivesUnderGenerationStats` 가 그 회귀를 잡는다.

픽스처의 값은 2026-09-20 실측 payload(`.devops_pro_cache/hbrnd2/exports/{sts,suts}/…063139·
063254·063433.payload.json`)에서 옮겼다. SITS 는 그 캐시에 산출물이 없어 생산자
(`generators/sits.py::generate_sits_quality_report` + `_FLOW_COV_KEYS`)의 계약에서 만들었다.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from report_gen.generation_disclosures import (
    DISCLOSURE_DOC_TYPES,
    DISCLOSURE_TONES,
    build_disclosures,
)

# ── 실측 payload 에서 옮긴 quality_report (값 그대로) ────────────────────────

_STS_REFERENCE = {
    "total_test_cases": 295,
    "safety_test_cases": 142,
    "gen_method_distribution": {"AOR": 142, "ECA": 99, "BAA": 54},
    "generation_stats": {
        "max_tc_per_req": 5,
        "tc_profile": "reference",
        "tc_profile_unknown_value": "",
        "extended_functions": 0,
        "extended_tcs": 0,
        "extended_boundary_tcs": 0,
        "extended_functions_without_detail": 0,
        "extended_functions_without_steps": 0,
        "extended_functions_placed_by_safety": 0,
        "mapped_functions": 1036,
        "functions_with_tc": 93,
        "functions_without_tc": 943,
        "requirements_truncated": ["SwCNF_0101", "SwCNF_0102", "SwCNF_0201", "SwEI_02"],
        "requirements_truncated_count": 50,
        "boundary_tc_candidates": 40,
        "boundary_tc_kept": 22,
        "boundary_tc_cut_by_function_cap": 8,
        "boundary_tc_cut_by_req_cap": 10,
        "boundary_tc_unavailable": 102,
        "requirement_function_mapping": {
            "functions_total": 1146,
            "functions_by_path": {"own_related": 0, "sds_exact": 666, "sds_substring": 155,
                                  "sds_name_in_key": 141, "sds_normalized": 61},
            "unlinked": 110,
            "links": 8556,
        },
    },
}

_STS_EXTENDED = {
    "total_test_cases": 2209,
    "safety_test_cases": 1886,
    "gen_method_distribution": {"AOR": 875, "BAA": 410, "ECA": 924},
    "generation_stats": {
        **_STS_REFERENCE["generation_stats"],
        "tc_profile": "extended",
        "extended_functions": 943,
        "extended_tcs": 1914,
        "extended_boundary_tcs": 280,
        "extended_functions_placed_by_safety": 423,
        "functions_with_tc": 1036,
        "functions_without_tc": 0,
    },
}

_SUTS = {
    "asil_evidence_distribution": {"uds": 718, "uds+override": 215},
    "override_only_unit_count": 0,
    "override_only_units": [],
    "bounds_source_distribution": {"uds_range": 6430, "type": 2274, "unknown": 142, "enum": 51},
    "range_conflicts": [
        "lin_frame_flag_tbl(SwUDS 0~255 vs bool)",
        "s32s_DecelPos(SwUDS 134217727~2147483648 vs int32_t)",
        "u8t_MaxCount(SwUDS 0~65535 vs uint8_t)",
    ],
    "range_conflict_count": 7,
    "pointer_address_range_count": 54,
    "srs_req_link_distribution": {"sts_mapping": 896},
    "verify_needed_expected_slots": 82,
    "units_with_srs_req_ids": 896,
    "unknown_type_var_slots": 146,
    "units_with_unknown_type_vars": 94,
    "total_test_cases": 933,
    "total_sequences": 8741,
    "gen_method_distribution": {"AEC, ABV": 280, "ABV, AOR": 286, "ABV": 244, "AOR": 123},
    "tc_profile": "reference",
    "tc_profile_unknown_value": "",
    "caps_requested": {"max_sequences": 24},
    "caps_effective": {"max_sequences": 24},
    "enrichment_errors": [],
    "extended_sequences": 0,
    "sequences_beyond_reference_cap": 0,
}

# `generators/sits.py` 계약(`generate_sits_quality_report` + `_FLOW_COV_KEYS` + `resolve_profile_caps`).
_SITS = {
    "total_test_cases": 120,
    "total_sub_cases": 640,
    "synthetic_only_related_count": 11,
    "gen_method_distribution": {"AOR, AEC": 78, "AOR/ABV": 42},
    "integration_flow_coverage": {
        "total_flows_found": 173,
        "flows_emitted": 120,
        "flows_dropped": 53,
        "max_flows": 120,
        "dropped_safety_related_count": 9,
        "dropped_in_design_doc_count": 3,
        "dropped_entry_fns": ["Eol_Task", "Motor_Drv", "Lin_Rx"],
        "chain_truncated_flows": 4,
        "chain_max_nodes": 40,
        "related_truncated_ids": 17,
        "array_skipped_budget": 6,
        "var_budget_cut_input": 12,
        "var_budget_cut_expected": 5,
    },
    "tc_profile": "reference",
    "tc_profile_unknown_value": "",
    "caps_requested": {"max_subcases": 7, "max_flows": 120},
    "caps_effective": {"max_subcases": 7, "max_flows": 120},
}


def _by_key(items):
    return {it["key"]: it for it in items}


# ==============================================================
# 1. 계약 — 항목의 모양과 tone 어휘
# ==============================================================

class TestItemShape:

    @pytest.mark.parametrize("doc_type, qr", [("sts", _STS_REFERENCE), ("sts", _STS_EXTENDED),
                                              ("suts", _SUTS), ("sits", _SITS)])
    def test_every_item_has_the_four_fields_and_a_known_tone(self, doc_type, qr):
        items = build_disclosures(doc_type, qr)
        assert items, f"{doc_type}: 실측 payload 인데 공시가 0건이다"
        for it in items:
            assert set(it) == {"key", "label", "value", "note", "tone"}, it
            assert it["tone"] in DISCLOSURE_TONES, it
            # 화면이 그대로 그리므로 빈 label/value 는 빈 줄이 된다.
            assert it["label"].strip() and it["value"].strip() and it["note"].strip(), it

    @pytest.mark.parametrize("doc_type, qr", [("sts", _STS_REFERENCE), ("suts", _SUTS), ("sits", _SITS)])
    def test_keys_are_unique(self, doc_type, qr):
        keys = [it["key"] for it in build_disclosures(doc_type, qr)]
        assert len(keys) == len(set(keys)), keys

    def test_unknown_doc_type_still_gets_the_common_items(self):
        """문서 종류를 모른다고 프로파일·상한까지 감출 이유는 없다."""
        got = _by_key(build_disclosures("swut", _SUTS))
        assert "tc_profile" in got and "caps" in got
        assert not [k for k in got if k.startswith(("sts_", "suts_", "sits_"))]

    def test_non_dict_report_is_an_empty_list_not_a_crash(self):
        assert build_disclosures("sts", None) == []
        assert build_disclosures("sts", []) == []

    def test_doc_type_set_is_the_single_source(self):
        assert DISCLOSURE_DOC_TYPES == frozenset({"sts", "suts", "sits"})


# ==============================================================
# 2. 0 과 부재 — 이 모듈의 핵심 계약
# ==============================================================

class TestZeroIsNotAbsence:

    def test_absent_key_makes_no_item(self):
        """구판 산출물(축을 기록한 적 없음)에 "0" 을 적으면 "손실 없음" 이라는 거짓이 된다."""
        got = _by_key(build_disclosures("sts", {"generation_stats": {}}))
        for key in ("sts_requirements_truncated", "sts_boundary_tc", "sts_function_tc",
                    "sts_unlinked_functions", "sts_max_tc_per_req"):
            assert key not in got, key
        assert build_disclosures("sts", {}) == []

    def test_zero_truncation_is_stated_not_hidden(self):
        """"상한에 걸린 요구 0건" 은 적극적인 사실이다 — 항목이 사라지면 구판과 구별되지 않는다."""
        got = _by_key(build_disclosures("sts", {"generation_stats": {"requirements_truncated_count": 0}}))
        it = got["sts_requirements_truncated"]
        assert it["value"] == "0건"
        assert it["tone"] == "info"
        assert "상한에 걸린 요구가 없다" in it["note"]

    def test_nonzero_truncation_is_a_warning_with_examples(self):
        it = _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_requirements_truncated"]
        assert it["value"] == "50건"
        assert it["tone"] == "warning"
        assert "SwCNF_0101" in it["note"]

    def test_unknown_profile_value_is_hidden_when_empty_and_warned_when_set(self):
        """빈 문자열이 **정상**이라 그때는 항목이 없다. 값이 있으면 오타 하나가 문서 규모를 바꾼 것."""
        assert "tc_profile_unknown_value" not in _by_key(build_disclosures("suts", _SUTS))
        got = _by_key(build_disclosures("suts", {**_SUTS, "tc_profile_unknown_value": "exteded"}))
        assert got["tc_profile_unknown_value"]["value"] == "exteded"
        assert got["tc_profile_unknown_value"]["tone"] == "warning"

    def test_override_only_zero_is_hidden_but_nonzero_warns(self):
        """정상값이 0 인 축 — 0 을 늘 보이면 잡음이 되고, 0 이 아니면 스냅샷이 낡았다는 뜻이다."""
        assert "suts_override_only" not in _by_key(build_disclosures("suts", _SUTS))
        got = _by_key(build_disclosures("suts", {**_SUTS, "override_only_unit_count": 3,
                                                 "override_only_units": ["Foo_Init", "Bar_Run"]}))
        assert got["suts_override_only"]["value"] == "3개"
        assert got["suts_override_only"]["tone"] == "warning"
        assert "Foo_Init" in got["suts_override_only"]["note"]

    def test_a_bool_is_not_counted_as_a_number(self):
        """`True` 가 1 로 세어지면 개수가 거짓말을 한다 — bool 은 int 의 하위형이다."""
        got = _by_key(build_disclosures("sts", {"generation_stats": {"requirements_truncated_count": True}}))
        assert "sts_requirements_truncated" not in got


# ==============================================================
# 3. STS — 프로파일 자리와 절단 축
# ==============================================================

class TestStsProfileLivesUnderGenerationStats:
    """실측 회귀: STS 는 `generation_stats` 안에, SUTS·SITS 는 최상위에 프로파일을 적는다.

    최상위만 보던 첫 판은 STS 두 문서에서 프로파일 줄이 사라져, 295 TC 문서와 2,209 TC 문서가
    화면에서 구별되지 않았다."""

    def test_reference_profile_is_read_from_generation_stats(self):
        it = _by_key(build_disclosures("sts", _STS_REFERENCE))["tc_profile"]
        assert it["value"] == "정본 규모(기본)"
        assert "상한에 걸린 시험은 이 문서에 없다" in it["note"]

    def test_extended_profile_says_it_contains_the_reference_document(self):
        it = _by_key(build_disclosures("sts", _STS_EXTENDED))["tc_profile"]
        assert it["value"] == "확장"
        assert "전부 담고" in it["note"]

    def test_top_level_profile_wins_over_generation_stats(self):
        """두 자리에 다 있으면 최상위가 이긴다 — alt 는 없을 때의 폴백일 뿐."""
        qr = {"tc_profile": "extended", "generation_stats": {"tc_profile": "reference"}}
        assert _by_key(build_disclosures("sts", qr))["tc_profile"]["value"] == "확장"


class TestStsTruncationAxes:

    def test_function_coverage_carries_its_denominator_and_the_lost_count(self):
        it = _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_function_tc"]
        assert it["value"] == "93 / 1036"
        assert "943개 함수는 요구당 TC 상한에 밀려" in it["note"]
        assert it["tone"] == "warning"

    def test_full_coverage_in_the_extended_document_is_not_a_warning(self):
        it = _by_key(build_disclosures("sts", _STS_EXTENDED))["sts_function_tc"]
        assert it["value"] == "1036 / 1036"
        assert it["tone"] == "info"
        assert "밀려" not in it["note"]

    def test_boundary_tc_shows_candidates_kept_and_both_caps(self):
        it = _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_boundary_tc"]
        assert it["value"] == "후보 40 · 남김 22 · 잘림 18 (요구 상한 10 · 함수 상한 8)"
        assert it["tone"] == "warning"

    def test_boundary_unavailable_is_honesty_not_a_defect(self):
        it = _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_boundary_unavailable"]
        assert it["value"] == "102건"
        assert it["tone"] == "info"
        assert "지어내지 않은 것" in it["note"]

    def test_weak_mapping_basis_is_separated_from_exact_matches(self):
        it = _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_mapping_basis"]
        # 155(sds_substring) + 141(sds_name_in_key) = 296
        assert it["value"] == "자체 Related 0 · 이름 정확 666 · 정규화 61 · 약한 근거 296"
        assert it["tone"] == "warning"

    def test_fuzzy_enrichment_links_are_weak_and_bridge_only_is_shown(self):
        """(R77 N107) 문서 보강의 추측 매칭으로만 붙은 함수(`enrich_fuzzy`)도 약한 근거다. 설계 ID 로만 붙은 함수는 따로 보인다."""
        qr = {"generation_stats": {"requirement_function_mapping": {
            "functions_by_path": {"own_related": 557, "sds_exact": 182, "sds_normalized": 15, "sds_substring": 128,
                                  "sds_name_in_key": 141, "enrich_fuzzy": 110},
            "design_id_bridge_only": 13, "unlinked": 0}}}
        it = _by_key(build_disclosures("sts", qr))["sts_mapping_basis"]
        assert it["value"] == "자체 Related 557 · 이름 정확 182 · 정규화 15 · 약한 근거 379 · 설계 ID 경유 13"
        assert it["tone"] == "warning" and "추측" in it["note"]

    def test_extended_block_is_hidden_in_the_reference_document(self):
        """기본 문서에서 확장 0 을 늘어놓으면 그 문서의 공시가 확장 이야기로 덮인다."""
        assert "sts_extended" not in _by_key(build_disclosures("sts", _STS_REFERENCE))
        it = _by_key(build_disclosures("sts", _STS_EXTENDED))["sts_extended"]
        assert it["value"] == "함수 943 · TC 1914 (경계값 280)"
        assert "423개는 안전 요구 밑에" in it["note"]

    def test_safety_test_cases_carry_the_total_as_denominator(self):
        assert _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_safety_test_cases"]["value"] == "142 / 295"

    def test_max_tc_per_req_is_disclosed_so_the_cap_has_a_number(self):
        assert _by_key(build_disclosures("sts", _STS_REFERENCE))["sts_max_tc_per_req"]["value"] == "5"


# ==============================================================
# 4. SUTS
# ==============================================================

class TestSutsItems:

    def test_blank_slots_are_info_because_they_were_not_invented(self):
        """예전엔 이 칸을 전부 uint8 로 지어낸 0/127/255 로 채웠다 — 비운 것이 개선이다."""
        it = _by_key(build_disclosures("suts", _SUTS))["suts_unknown_type_slots"]
        assert it["value"] == "146칸 (94개 unit)"
        assert it["tone"] == "info"
        assert "지어내지 않은 것" in it["note"]

    def test_bounds_source_distribution_is_sorted_by_count(self):
        it = _by_key(build_disclosures("suts", _SUTS))["suts_bounds_source"]
        assert it["value"] == "uds_range 6430 · type 2274 · unknown 142 · enum 51"

    def test_range_conflicts_warn_and_name_a_few(self):
        it = _by_key(build_disclosures("suts", _SUTS))["suts_range_conflicts"]
        assert it["value"] == "7건"
        assert it["tone"] == "warning"
        assert "lin_frame_flag_tbl" in it["note"]

    def test_zero_range_conflicts_is_info_and_still_shown(self):
        it = _by_key(build_disclosures("suts", {**_SUTS, "range_conflict_count": 0, "range_conflicts": []}))
        assert it["suts_range_conflicts"]["tone"] == "info"
        assert "어긋난 변수가 없다" in it["suts_range_conflicts"]["note"]

    def test_pointer_ranges_are_a_separate_axis_not_a_document_error(self):
        it = _by_key(build_disclosures("suts", _SUTS))["suts_pointer_address_ranges"]
        assert it["value"] == "54건" and it["tone"] == "info"
        assert "문서 오류가 아니라" in it["note"]

    def test_verify_needed_slots_reach_the_screen(self):
        assert _by_key(build_disclosures("suts", _SUTS))["suts_verify_needed"]["value"] == "82칸"

    def test_enrichment_errors_name_the_stage_and_reason(self):
        got = _by_key(build_disclosures("suts", _SUTS))
        assert got["suts_enrichment_errors"]["value"] == "0건"
        assert got["suts_enrichment_errors"]["tone"] == "info"
        bad = _by_key(build_disclosures("suts", {**_SUTS, "enrichment_errors": [
            {"stage": "hsis_ranges", "error": "HSIS 문서를 열지 못했다"}]}))
        it = bad["suts_enrichment_errors"]
        assert it["value"] == "1건" and it["tone"] == "warning"
        assert "hsis_ranges" in it["note"] and "HSIS 문서를 열지 못했다" in it["note"]

    def test_asil_evidence_warns_only_when_some_unit_has_no_basis(self):
        assert _by_key(build_disclosures("suts", _SUTS))["suts_asil_evidence"]["tone"] == "info"
        it = _by_key(build_disclosures("suts", {**_SUTS, "asil_evidence_distribution": {"uds": 700, "none": 33}}))
        assert it["suts_asil_evidence"]["tone"] == "warning"
        assert "근거 없는 unit 이 33개" in it["suts_asil_evidence"]["note"]

    def test_caps_state_the_difference_when_the_profile_lifted_them(self):
        same = _by_key(build_disclosures("suts", _SUTS))["caps"]
        assert same["value"] == "max_sequences 24"
        assert "그대로 걸었다" in same["note"]
        lifted = _by_key(build_disclosures("suts", {**_SUTS, "tc_profile": "extended",
                                                    "caps_effective": {"max_sequences": None}}))["caps"]
        assert lifted["value"] == "max_sequences 상한 없음"
        assert "요청 상한은 max_sequences 24" in lifted["note"]

    def test_extended_sequence_block_is_hidden_in_the_reference_document(self):
        assert "suts_extended" not in _by_key(build_disclosures("suts", _SUTS))
        it = _by_key(build_disclosures("suts", {**_SUTS, "extended_sequences": 8824,
                                                "sequences_beyond_reference_cap": 0}))["suts_extended"]
        assert it["value"] == "확장 전략 8824 · 상한 해제분 0"


# ==============================================================
# 5. SITS
# ==============================================================

class TestSitsItems:

    def test_flow_cap_denominator_is_what_was_found_not_what_was_emitted(self):
        it = _by_key(build_disclosures("sits", _SITS))["sits_flows"]
        assert it["value"] == "120 / 173 (제외 53)"
        assert it["tone"] == "warning"
        assert "규격에 아예 없다" in it["note"]

    def test_emitting_everything_is_not_a_warning(self):
        qr = {"integration_flow_coverage": {"total_flows_found": 88, "flows_emitted": 88, "flows_dropped": 0}}
        it = _by_key(build_disclosures("sits", qr))["sits_flows"]
        assert it["value"] == "88 / 88" and it["tone"] == "info"
        assert "전부 실었다" in it["note"]

    def test_dropped_safety_flows_get_their_own_warning_with_names(self):
        it = _by_key(build_disclosures("sits", _SITS))["sits_dropped_critical"]
        assert it["value"] == "안전 관련 9 · 설계서 등재 3"
        assert "Eol_Task" in it["note"] and it["tone"] == "warning"

    def test_zero_critical_drops_is_folded_into_the_flow_item(self):
        """같은 사실을 두 줄로 말하지 않는다 — 흐름 항목이 이미 "전부 실었다" 고 말한다."""
        qr = {"integration_flow_coverage": {"total_flows_found": 88, "flows_emitted": 88, "flows_dropped": 0,
                                            "dropped_safety_related_count": 0, "dropped_in_design_doc_count": 0}}
        assert "sits_dropped_critical" not in _by_key(build_disclosures("sits", qr))

    def test_chain_and_related_truncation_are_separate_from_flow_drop(self):
        got = _by_key(build_disclosures("sits", _SITS))
        assert got["sits_chain_truncated"]["value"] == "4개 흐름"
        assert "40" in got["sits_chain_truncated"]["note"]
        assert got["sits_related_truncated"]["value"] == "17개"
        assert got["sits_var_budget_cut"]["value"] == "입력 12 · 기대 5"
        assert got["sits_array_skipped"]["value"] == "6건"

    def test_synthetic_only_related_is_not_traceability(self):
        it = _by_key(build_disclosures("sits", _SITS))["sits_synthetic_only"]
        assert it["value"] == "11건" and it["tone"] == "warning"
        assert "추적성 근거로 세지 말 것" in it["note"]

    def test_strategy_sheet_error_is_surfaced(self):
        got = _by_key(build_disclosures("sits", {**_SITS, "strategy_sheet_error": "openpyxl: sheet 없음"}))
        assert got["sits_strategy_error"]["tone"] == "warning"
        assert "openpyxl: sheet 없음" in got["sits_strategy_error"]["note"]

    def test_sub_cases_carry_the_tc_count(self):
        assert _by_key(build_disclosures("sits", _SITS))["sits_sub_cases"]["value"] == "640건 / TC 120"


# ==============================================================
# 6. evidence 섹션 — 부재는 반드시 사유와 함께
# ==============================================================

def _artifact(suffix: str, payload) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp())
    out = d / f"doc{suffix}"
    out.write_bytes(b"PK\x03\x04dummy")
    if payload is not None:
        out.with_suffix(".payload.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


class TestGenerationSection:

    def test_xlsm_payload_carries_items_and_the_doc_type_it_used(self):
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "suts", "quality_report": _SUTS})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is True
        assert sec["doc_type_hint"] == "suts"
        got = _by_key(sec["items"])
        assert got["suts_range_conflicts"]["value"] == "7건"
        assert got["suts_unknown_type_slots"]["tone"] == "info"

    @pytest.mark.parametrize("suffix", [".xlsm", ".xlsx"])
    def test_both_spreadsheet_suffixes_are_read(self, suffix):
        """(뮤턴트 E5 생존 자리) 접미사 목록에서 `.xlsx` 를 지워도 아무 테스트가 안 깨졌다 —
        `.xlsx` 로 나가는 산출물이 생기면 공시가 통째로 "해당 없음" 이 된다."""
        from report_gen.evidence import DISCLOSURE_ARTIFACT_SUFFIXES, read_evidence

        assert suffix in DISCLOSURE_ARTIFACT_SUFFIXES
        out = _artifact(suffix, {"artifact_type": "suts", "quality_report": _SUTS})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is True and sec["items"]

    def test_doc_type_comes_from_the_payload_not_the_path(self):
        """경로를 클라이언트가 보내지 않는다는 보안 규약 유지 — 파일 이름은 근거가 아니다."""
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "sts", "quality_report": _STS_REFERENCE})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["doc_type_hint"] == "sts"
        assert "sts_boundary_tc" in _by_key(sec["items"])

    def test_missing_payload_is_absent_with_a_reason_not_an_empty_list(self):
        from report_gen.evidence import read_evidence

        sec = read_evidence(str(_artifact(".xlsm", None)), sections=("generation",))["generation"]
        assert sec["present"] is False
        assert "payload" in sec["reason"]
        assert "items" not in sec         # 빈 목록으로 접으면 "공시할 것 없음" 으로 읽힌다

    def test_payload_without_quality_report_says_so(self):
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "sts", "summary": {}})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is False
        # (리뷰 I8) 키 부재·형식 오류·빈 dict 의 사유가 갈렸다 — 여기는 **키 부재** 분기다.
        assert "quality_report 키 없음" in sec["reason"]

    def test_docx_output_is_not_applicable_rather_than_a_read_failure(self):
        """UDS payload 에도 `quality_report` 는 없다 — 그걸 "읽기 실패" 로 적으면 사라진 공시를 찾게 된다."""
        from report_gen.evidence import read_evidence

        out = _artifact(".docx", {"artifact_type": "uds", "functions": []})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is False
        assert "해당 없음" in sec["reason"]

    def test_unparsable_payload_is_absent_with_the_exception(self):
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", None)
        out.with_suffix(".payload.json").write_text("{not json", encoding="utf-8")
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is False
        assert "읽기 실패" in sec["reason"]

    def test_old_generator_payload_gives_an_empty_list_not_an_absence(self):
        """`items: []` 는 "이 산출물이 아는 축을 하나도 기록하지 않았음" — `present:false` 와 다른 사실이다."""
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "sts", "quality_report": {"total_test_cases": 3}})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is True and sec["items"] == []

    def test_section_is_in_the_default_set_and_selectable(self):
        from report_gen.evidence import EVIDENCE_SECTIONS, read_evidence

        assert "generation" in EVIDENCE_SECTIONS
        out = _artifact(".xlsm", {"artifact_type": "suts", "quality_report": _SUTS})
        assert "generation" in read_evidence(str(out))

    def test_selecting_generation_does_not_open_the_other_readers(self):
        """관측량: 다른 리더가 **호출되지 않는다**. 대조군: 전량 호출은 같은 조건에서 터진다."""
        import report_gen.evidence as ev

        def _boom(*_a, **_k):
            raise AssertionError("reference 섹션을 읽었다")

        out = _artifact(".xlsm", {"artifact_type": "suts", "quality_report": _SUTS})
        orig = ev.read_reference_enrichment
        ev.read_reference_enrichment = _boom
        try:
            assert ev.read_evidence(str(out), sections=("generation",))["generation"]["present"] is True
            with pytest.raises(AssertionError, match="reference"):
                ev.read_evidence(str(out))
        finally:
            ev.read_reference_enrichment = orig


# ==============================================================
# 7. 엔드포인트 — 공시가 화면까지 도달하는가
# ==============================================================

@pytest.fixture
def api(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.dependencies.auth import require_user
    from backend.routers import quality
    from workflow.quality import db as qdb

    db_file = tmp_path / "q.db"
    monkeypatch.setattr(qdb, "_default_db_path", lambda: db_file)
    app = FastAPI()
    app.include_router(quality.router)
    app.dependency_overrides[require_user] = lambda: "tester"

    def make_run(doc_type, output_path=None):
        from workflow.quality.recorder import record_run
        return record_run(doc_type, {"x": 1},
                          output_path=str(output_path) if output_path else None, db_path=db_file)

    return TestClient(app), make_run


class TestEndpointCarriesTheDisclosures:

    def test_suts_run_gets_its_items(self, api):
        client, make_run = api
        out = _artifact(".xlsm", {"artifact_type": "suts", "quality_report": _SUTS})
        body = client.get(f"/api/quality/runs/{make_run('suts', out)}/evidence").json()
        assert body["expected_sidecars"]["generation"] is True
        got = _by_key(body["generation"]["items"])
        assert got["suts_verify_needed"]["value"] == "82칸"
        assert got["tc_profile"]["value"] == "정본 규모(기본)"

    def test_uds_run_says_not_applicable_rather_than_missing(self, api):
        client, make_run = api
        out = _artifact(".docx", {"artifact_type": "uds"})
        body = client.get(f"/api/quality/runs/{make_run('uds', out)}/evidence").json()
        assert body["expected_sidecars"]["generation"] is False
        assert body["generation"]["present"] is False
        assert "해당 없음" in body["generation"]["reason"]

    def test_run_without_output_path_still_answers_with_a_reason(self, api):
        client, make_run = api
        body = client.get(f"/api/quality/runs/{make_run('sts')}/evidence").json()
        assert body["generation"]["present"] is False
        assert body["generation"]["reason"]


# ==============================================================
# 8. deep 리뷰 후속 — 부재를 0 으로 접지 않는다
# ==============================================================
# 아래 전부 **재현 가능한 지적**이었다: 첫 판은 `_int(...) or 0` 을 표시·단정에 써서, 그 축을
# 기록하지 않은 산출물이 "잘림 0 · 제외 0 · 자체 Related 0" 으로 보였다. 화면에서 `0` 은
# "손실 없음" 이라는 단언이고 `—` 는 "안 쟀다" 라, 둘을 접으면 공시가 거짓 증거가 된다.

class TestAbsentCountsAreNotZero:

    def test_sits_missing_drop_count_is_derived_not_assumed_zero(self):
        """(W2) 재현: `flows_dropped` 없이 173/120 → 예전엔 info · "전부 실었다"."""
        it = _by_key(build_disclosures("sits", {
            "integration_flow_coverage": {"total_flows_found": 173, "flows_emitted": 120}}))["sits_flows"]
        assert it["value"] == "120 / 173 (제외 53, 유도)"
        assert it["tone"] == "warning"
        assert "전부 실었다" not in it["note"]

    def test_sits_unknowable_drop_count_says_so(self):
        """분자도 없으면 유도할 수 없다 — 그때는 "미기록"(warning)이지 0 이 아니다."""
        it = _by_key(build_disclosures("sits", {
            "integration_flow_coverage": {"total_flows_found": 173}}))["sits_flows"]
        assert it["value"] == "— / 173 (제외 수 미기록)"
        assert it["tone"] == "warning"
        assert "전부 실었다고 읽지 말 것" in it["note"]

    def test_sits_derived_zero_may_still_say_all_were_emitted(self):
        """분자 == 분모면 유도한 0 도 확인된 0 이다 — 이때만 "전부 실었다"."""
        it = _by_key(build_disclosures("sits", {
            "integration_flow_coverage": {"total_flows_found": 88, "flows_emitted": 88}}))["sits_flows"]
        assert it["value"] == "88 / 88" and it["tone"] == "info"
        assert "전부 실었다" in it["note"]

    def test_sits_partial_critical_drop_counts_show_a_dash(self):
        it = _by_key(build_disclosures("sits", {"integration_flow_coverage": {
            "total_flows_found": 100, "flows_emitted": 90, "flows_dropped": 10,
            "dropped_safety_related_count": 4}}))["sits_dropped_critical"]
        assert it["value"] == "안전 관련 4 · 설계서 등재 —"

    def test_sits_partial_var_budget_cut_shows_a_dash(self):
        it = _by_key(build_disclosures("sits", {
            "integration_flow_coverage": {"var_budget_cut_expected": 5}}))["sits_var_budget_cut"]
        assert it["value"] == "입력 — · 기대 5"

    def test_boundary_cut_without_the_two_axes_is_unrecorded_not_zero(self):
        """(X7) 재현: `{"boundary_tc_candidates": 40}` → 예전엔 "잘림 0" · info."""
        it = _by_key(build_disclosures("sts", {
            "generation_stats": {"boundary_tc_candidates": 40}}))["sts_boundary_tc"]
        assert it["value"] == "후보 40 · 남김 — · 잘림 —"
        assert it["tone"] == "warning"
        assert "0 으로 읽지 말 것" in it["note"]

    def test_one_missing_boundary_axis_makes_the_total_unrecorded(self):
        """한 축만 있으면 합계를 말할 수 없다 — 있는 축만 더하면 손실을 축소 보고한다."""
        it = _by_key(build_disclosures("sts", {"generation_stats": {
            "boundary_tc_candidates": 40, "boundary_tc_kept": 22,
            "boundary_tc_cut_by_req_cap": 10}}))["sts_boundary_tc"]
        assert it["value"] == "후보 40 · 남김 22 · 잘림 —"
        assert it["tone"] == "warning"

    def test_mapping_basis_shows_dashes_for_the_axes_it_did_not_count(self):
        """(X7) 재현: `{"enrich_fuzzy": 110}` → 예전엔 "자체 Related 0 · 이름 정확 0 · 정규화 0"."""
        it = _by_key(build_disclosures("sts", {"generation_stats": {
            "requirement_function_mapping": {"functions_by_path": {"enrich_fuzzy": 110}}}}))["sts_mapping_basis"]
        assert it["value"] == "자체 Related — · 이름 정확 — · 정규화 — · 약한 근거 110"
        assert it["tone"] == "warning"

    def test_mapping_basis_without_any_weak_axis_is_unrecorded_not_zero(self):
        it = _by_key(build_disclosures("sts", {"generation_stats": {
            "requirement_function_mapping": {"functions_by_path": {"sds_exact": 666}}}}))["sts_mapping_basis"]
        assert it["value"] == "자체 Related — · 이름 정확 666 · 정규화 — · 약한 근거 —"
        assert it["tone"] == "info"
        assert "0 으로 읽지 말 것" in it["note"]

    def test_function_tc_warns_even_when_the_without_key_is_missing(self):
        """(I7) 재현: `{"functions_with_tc": 92, "mapped_functions": 1036}` → 예전엔 info."""
        it = _by_key(build_disclosures("sts", {"generation_stats": {
            "functions_with_tc": 92, "mapped_functions": 1036}}))["sts_function_tc"]
        assert it["value"] == "92 / 1036"
        assert it["tone"] == "warning"
        assert "나머지 944개" in it["note"]

    def test_function_tc_without_a_denominator_says_the_loss_is_unrecorded(self):
        it = _by_key(build_disclosures("sts", {"generation_stats": {"functions_with_tc": 92}}))["sts_function_tc"]
        assert it["value"] == "92"
        assert "기록되지 않았다" in it["note"]

    def test_extended_thin_shows_a_dash_for_the_axis_it_did_not_count(self):
        gs = {**_STS_EXTENDED["generation_stats"], "extended_functions_without_steps": 7}
        gs.pop("extended_functions_without_detail")
        it = _by_key(build_disclosures("sts", {**_STS_EXTENDED, "generation_stats": gs}))["sts_extended_thin"]
        assert it["value"] == "상세 없음 — · 절차 없음 7"


class TestCapsDoNotBorrowTheRequestedValue:

    def test_missing_effective_caps_is_a_warning_not_the_requested_value(self):
        """(W5) 재현: 요청만 기록된 산출물이 "요청한 상한을 그대로 걸었다" 고 단정했다."""
        it = _by_key(build_disclosures("suts", {"caps_requested": {"max_sequences": 24}}))["caps"]
        assert it["value"] == "(적용 상한 미기록)"
        assert it["tone"] == "warning"
        assert "그대로 걸렸다고 읽지 말 것" in it["note"]
        assert "max_sequences 24" in it["note"]      # 요청값은 note 에만

    def test_both_caps_empty_is_a_warning_without_the_claim(self):
        it = _by_key(build_disclosures("suts", {"caps_requested": {}, "caps_effective": {}}))["caps"]
        assert it["value"] == "(적용 상한 미기록)"
        assert it["tone"] == "warning"
        assert "그대로 걸었다" not in it["note"]

    def test_effective_only_states_the_cap_without_claiming_it_matched(self):
        it = _by_key(build_disclosures("sits", {"caps_effective": {"max_flows": None}}))["caps"]
        assert it["value"] == "max_flows 상한 없음"
        assert it["tone"] == "info"
        assert "그대로 걸었다" not in it["note"]


class TestEmptyQualityReportIsNotAnOldGenerator:
    """(I8) `backend/helpers/common.py` 가 실패 경로에서 `quality_report` 를 `{}` 로 쓴다 —
    그걸 `present:True, items:[]` 로 내면 **실패한 산출물이 "아무것도 자르지 않았다"** 로 읽힌다."""

    def test_empty_dict_is_absent_with_its_own_reason(self):
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "sts", "quality_report": {}})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is False
        assert "비었다" in sec["reason"] and "끝까지 가지 못한" in sec["reason"]
        assert "공시를 남기기 전" not in sec["reason"]

    def test_missing_key_blames_the_old_generator(self):
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "sts", "summary": {}})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is False
        assert "키 없음" in sec["reason"] and "공시를 남기기 전 생성기" in sec["reason"]

    @pytest.mark.parametrize("bad, name", [([1, 2], "list"), ("x", "str"), (None, "NoneType")])
    def test_wrong_type_is_a_broken_record_not_an_old_generator(self, bad, name):
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"artifact_type": "sts", "quality_report": bad})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is False
        assert "기록이 깨졌다" in sec["reason"] and name in sec["reason"]
        assert "공시를 남기기 전" not in sec["reason"]

    def test_payload_without_artifact_type_still_reports_the_common_axes(self):
        """`doc_type_hint: None` — 문서 종류를 몰라도 프로파일·상한은 말할 수 있다."""
        from report_gen.evidence import read_evidence

        out = _artifact(".xlsm", {"quality_report": _SUTS})
        sec = read_evidence(str(out), sections=("generation",))["generation"]
        assert sec["present"] is True
        assert sec["doc_type_hint"] is None
        got = _by_key(sec["items"])
        assert got["tc_profile"]["value"] == "정본 규모(기본)"
        assert not [k for k in got if k.startswith("suts_")]   # 종류를 모르면 전용 축은 못 낸다
