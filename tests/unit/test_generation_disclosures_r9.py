"""R9 — generation disclosures for the evidence rounds (MC/DC design, expected-value basis, requirement boundary TCs,
interface contract). Absent keys make no item (an old output is not "0"); present keys always do."""
from __future__ import annotations

from report_gen.generation_disclosures import build_disclosures


def _by_key(items):
    return {i["key"]: i for i in items}


def test_suts_shows_expected_value_basis_and_mcdc_design():
    qr = {"expected_evidence_summary": {"derived": 10, "derived_assigned": 7, "derived_unchanged_input": 3,
                                        "unknown": 5, "proposed": 0, "unrecorded": 0, "total": 15},
          "mcdc_design_summary": {"decisions": 12, "designed": 8, "partial": 1, "unsupported": 3, "retained_pairs": 20,
                                  "truncated_pairs": 2, "invalidated_pairs": 0,
                                  "source_path": {"decisions": 4, "designed": 3}}}
    items = _by_key(build_disclosures("suts", qr))
    ev = items["suts_expected_evidence"]
    assert ev["value"] == "소스 계산 10 (함수가 쓴 값 7 · 입력 그대로 3) · 미상 5 · 제안 0 · 근거 미기록 0 / 전체 15칸"
    assert "not_run" in ev["note"] and ev["tone"] == "info"
    mc = items["suts_mcdc_design"]
    assert mc["value"] == ("결정 12 중 설계 8 · 부분 1 · 쌍 못 찾음 — · 미지원 3 · 유지 쌍 20 "
                           "(함수 실행 모델로 설계한 결정 3 / 4)")
    assert "절단 2 · 무효 0" in mc["note"] and mc["tone"] == "info"
    qr["mcdc_design_summary"]["invalidated_pairs"] = 1
    assert _by_key(build_disclosures("suts", qr))["suts_mcdc_design"]["tone"] == "warning"


def test_an_old_suts_output_without_the_summaries_gets_no_item():
    items = _by_key(build_disclosures("suts", {"total_test_cases": 3}))
    assert "suts_expected_evidence" not in items and "suts_mcdc_design" not in items


def test_sts_shows_requirement_boundary_tcs_with_skip_reasons():
    qr = {"generation_stats": {"requirement_boundary": {"tcs": 23, "steps": 183, "facts": 146, "facts_used": 61,
                                                        "skipped:kind_symbolic": 64, "skipped:response_constraint": 3,
                                                        "skipped:negated_condition": 0}}}
    item = _by_key(build_disclosures("sts", qr))["sts_requirement_boundary"]
    assert item["value"] == "TC 23 · 스텝 183 · 사실 61 / 146"
    assert "기호 비교(값 미상) 64" in item["note"] and "응답 제약(측정 대상) 3" in item["note"]
    assert "부정 절" not in item["note"]   # a zero reason is not listed
    assert "sts_requirement_boundary" not in _by_key(build_disclosures("sts", {"generation_stats": {}}))


def test_sits_shows_the_interface_contract_as_evidence_with_what_it_left_out():
    qr = {"interface_contract": {"cross_module_calls": 721, "used_returns": 145, "global_flows": 1050,
                                 "suggestion_skipped:compared_value_unresolved": 1, "duplicate_function_names": 1,
                                 "ambiguous_functions": 3, "unreadable_source_files": 0, "missing_functions": 15,
                                 "unresolved_calls": 257}}
    item = _by_key(build_disclosures("sits", qr))["sits_interface_contract"]
    assert item["value"] == "흐름별 합계 — 모듈 경계 호출 721 · 쓰이는 반환 145 · 전역 생산→소비 1050"
    assert "적용하지 않았다" in item["note"] and "비교 상수 미해석 1" in item["note"]
    assert "흐름 등장 3회는 계약에서 빠졌다" in item["note"] and "못 찾은 흐름 함수 15회" in item["note"]
    assert "257(흐름별 합계)" in item["note"]
    assert item["tone"] == "warning"
    failed = _by_key(build_disclosures("sits", {"interface_contract": {"error": "RuntimeError: x"}}))
    assert failed["sits_interface_contract"]["value"] == "추출 실패" and failed["sits_interface_contract"]["tone"] == "warning"


def test_a_present_but_sparse_requirement_boundary_block_shows_zero_not_unknown():
    item = _by_key(build_disclosures("sts", {"generation_stats": {"requirement_boundary": {"facts": 4,
                                                                                         "skipped:kind_range": 4}}}))
    assert item["sts_requirement_boundary"]["value"] == "TC 0 · 스텝 0 · 사실 0 / 4"


def test_mcdc_and_evidence_values_account_for_every_decision_and_slot():
    qr = {"expected_evidence_summary": {"derived": 1, "derived_assigned": 1, "derived_unchanged_input": 0,
                                        "unknown": 1, "proposed": 0, "unrecorded": 2, "total": 4},
          "mcdc_design_summary": {"decisions": 5, "designed": 1, "partial": 1, "no_pair_found": 2, "unsupported": 1,
                                  "retained_pairs": 2, "truncated_pairs": 0, "invalidated_pairs": 0,
                                  "unenumerated_functions": 3, "units_not_analyzed": 0}}
    items = _by_key(build_disclosures("suts", qr))
    assert "근거 미기록 2 / 전체 4칸" in items["suts_expected_evidence"]["value"]
    assert "쌍 못 찾음 2" in items["suts_mcdc_design"]["value"]
    assert "결정을 나열하지 못한 함수 3" in items["suts_mcdc_design"]["note"]



def test_sits_contract_shows_distinct_counts_the_basis_of_its_suggestions_and_warns_only_on_a_real_loss():
    """(R7 review round 2 W-4/W-5/W-6) distinct first; a suggestion from type bounds is not an error-propagation value;
    a twice-defined name that no flow uses loses nothing."""
    ic = {"cross_module_calls": 721, "used_returns": 145, "global_flows": 1050, "distinct_cross_module_calls": 232,
          "distinct_used_returns": 58, "distinct_global_flows": 300, "distinct_unresolved_calls": 0,
          "suggestion_basis:return_type_bounds": 144, "suggestion_skipped:compared_value_unresolved": 1,
          "duplicate_function_names": 1, "ambiguous_functions": 0, "unreadable_source_files": 0,
          "keyword_named_definitions": 1, "missing_functions": 0}
    item = _by_key(build_disclosures("sits", {"interface_contract": ic}))["sits_interface_contract"]
    assert item["value"] == ("고유 모듈 경계 호출 232 · 쓰이는 반환 58 · 전역 생산→소비 300 "
                             "(흐름별 합계 721 · 145 · 1050)")
    assert "반환 타입 경계 144 — 오류 비교에서 나온 값이 없어" in item["note"]
    assert "흐름에 나오지 않는다" in item["note"] and "`if` 등) 1개는 무시했다" in item["note"]
    assert item["tone"] == "info"
    ic["suggestion_basis:enum_sibling"] = 2
    assert "오류 비교에서 나온 값이 없어" not in _by_key(build_disclosures("sits", {"interface_contract": ic}))[
        "sits_interface_contract"]["note"]
