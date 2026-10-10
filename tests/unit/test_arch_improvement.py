"""아키텍처 개선(To-Be) 제안 — 결정론 후보 6종·근거 인용·환각 필터·정직 폴백(Q3).

핵심 계약: 결정론 후보는 LLM 없이 항상 나오고 임계 미달이면 만들지 않는다(모든 파일을 후보로
라벨링 금지). AI 목표 구조는 후보가 있을 때만 호출하며, 입력 심볼 밖 노드는 폐기한다.
"""
from __future__ import annotations

import json

from workflow.arch_improvement import (
    ARCH_IMPROVEMENT_NOTE,
    TESTABILITY_KINDS,
    build_candidates,
    generate_target_design,
    summarize,
)

ARCH = {
    "available": True,
    "module_graph": {
        "nodes": [{"module": "APP", "files": 2, "functions": 6}, {"module": "LIB", "files": 1, "functions": 3}],
        "edges": [{"from": "APP", "to": "LIB", "calls": 4}],
    },
    "file_graph": {
        "nodes": [{"file": "APP/a.c", "module": "APP"}, {"file": "APP/b.c", "module": "APP"}],
        "edges": [
            {"from": "APP/a.c", "to": "APP/b.c", "calls": 9},
            {"from": "APP/b.c", "to": "APP/a.c", "calls": 2},   # 더 싼 간선 — 끊기 후보
        ],
    },
    "cycles": {"file_sccs": [{"files": ["APP/a.c", "APP/b.c"], "size": 2}]},
    "layer_graph": {
        "available": True, "reverse_total": 87,
        "reverse_pairs": [{"caller": "PE_Init", "caller_layer": "BSW_DRIVER", "caller_file": "BSW/pe.c",
                           "callee": "Ap_Main", "callee_layer": "APP_LEAF", "callee_file": "APP/a.c"}],
    },
    "refactor_candidates": [
        {"kind": "god_file", "file": "APP/a.c", "basis": "함수 20개 · 본문 900줄 · 유입 3파일 · 유출 2파일"},
        {"kind": "mutual_dependency", "files": ["APP/a.c", "APP/b.c"], "basis": "상호 호출"},
    ],
    "coverage_complexity": {
        "available": True,
        "priority": [{"function": "ADC_HWEnDi", "file": "APP/adc.c", "statement": 0.4118,
                      "complexity": 7, "complexity_source": "vcast_ccn"}],
    },
    "global_coupling": {
        "available": True,
        "top": [
            {"global": "g_shared", "modules": 2, "functions": 39, "functions_sample": ["hi_fn", "lo_fn"]},
            {"global": "g_local", "modules": 1, "functions": 5, "functions_sample": ["x_fn"]},
        ],
    },
    # v7: 실제 심볼이 있어야 시임 후보다(원시 func_refs 는 MCU 레지스터 참조를 대량 포함 —
    # 실측 2,708건 중 실제 함수 2건. 개수만 보고 후보를 만들면 전부 오탐이 된다).
    "indirect_calls": {"top": [
        {"function": "ptr_user", "func_refs": 0, "pointer_calls": 1, "file": "BSW/b.c",
         "ref_functions": [], "pointer_symbols": ["pfn_Handler"]},
        {"function": "reg_toucher", "func_refs": 0, "pointer_calls": 0, "file": "BSW/c.c",
         "ref_functions": [], "pointer_symbols": []},   # 심볼 0 — 후보가 되면 안 된다
    ]},
    "coupling": {"cross_file_call_ratio": 0.27, "top_pairs": []},
}


def _by_kind(cands):
    out = {}
    for c in cands:
        out.setdefault(c["kind"], []).append(c)
    return out


def test_break_cycle_picks_cheapest_edge():
    """순환은 **끊는 비용이 가장 싼 간선**을 짚어야 실행 가능한 제안이 된다."""
    c = _by_kind(build_candidates(ARCH))["break_cycle"][0]
    assert c["target"] == "APP/b.c → APP/a.c"      # 9회가 아니라 2회짜리
    assert "호출 2회" in c["basis"]
    assert c["effort"] == "low"


def test_layer_candidate_keeps_heuristic_caveat():
    c = _by_kind(build_candidates(ARCH))["layer_violation"][0]
    assert c["target"] == "PE_Init → Ap_Main"
    assert "함수명 추정값" in c["basis"]           # 계층 축 한계 승계
    assert "87" in c["basis"]


def test_testability_candidates_present_with_numeric_basis():
    by = _by_kind(build_candidates(ARCH))
    assert by["extract_pure"][0]["target"] == "ADC_HWEnDi"
    assert "41%" in by["extract_pure"][0]["basis"] and "복잡도 7" in by["extract_pure"][0]["basis"]
    assert by["inject_global"][0]["target"] == "g_shared"
    assert "읽기/쓰기 미구분" in by["inject_global"][0]["basis"]
    assert by["seam_for_pointer"][0]["target"] == "ptr_user"
    assert by["seam_for_pointer"][0]["pointer_symbols"] == ["pfn_Handler"]


def test_seam_candidate_requires_real_symbol():
    """개수만 있고 실제 심볼이 없는 항목은 시임 후보가 아니다.

    v7 이전에는 원시 func_refs 순으로 top 을 뽑아 MCU 레지스터(DDRADL·CPMUINT)를 참조하는
    초기화 함수가 '함수포인터 참조 27'로 1순위 후보였다 — 스텁을 끼울 포인터가 아예 없는 곳이다.
    """
    targets = {c["target"] for c in build_candidates(ARCH) if c["kind"] == "seam_for_pointer"}
    assert "ptr_user" in targets
    assert "reg_toucher" not in targets


def test_single_module_global_is_not_a_candidate():
    """한 모듈 안의 전역은 테스트 격리 부담이 작다 — 후보로 만들지 않는다(허위 신호 방지)."""
    targets = {c["target"] for c in build_candidates(ARCH) if c["kind"] == "inject_global"}
    assert "g_shared" in targets and "g_local" not in targets


def test_only_god_file_from_refactor_candidates():
    kinds = _by_kind(build_candidates(ARCH))
    assert [c["target"] for c in kinds["split_god_file"]] == ["APP/a.c"]   # mutual_dependency는 제외


def test_no_candidates_when_metrics_are_clean():
    clean = {"available": True, "module_graph": {"nodes": [], "edges": []},
             "file_graph": {"nodes": [], "edges": []}, "cycles": {"file_sccs": []},
             "layer_graph": {"available": False}, "refactor_candidates": [],
             "coverage_complexity": {"available": False}, "global_coupling": {"available": False},
             "indirect_calls": {"top": []}}
    assert build_candidates(clean) == []


def test_summary_splits_structural_and_testability():
    s = summarize(build_candidates(ARCH))
    assert s["total"] == s["structural"] + s["testability"]
    assert s["testability"] == sum(v for k, v in s["by_kind"].items() if k in TESTABILITY_KINDS)
    assert s["testability"] >= 3      # extract_pure · inject_global · seam_for_pointer


# ── AI 목표 구조 ────────────────────────────────────────────────────────────

def test_no_llm_call_without_candidates():
    """후보가 없으면 AI를 부르지 않는다 — 근거 없는 목표 구조는 허구다."""
    calls = []
    out = generate_target_design(arch=ARCH, candidates=[], cfg={"model": "m"},
                                 agent_call=lambda *a, **k: calls.append(1))
    assert out["target_design"] is None and out["enrich_reason"] == "no_candidates"
    assert calls == []


def test_llm_unavailable_returns_deterministic_only():
    out = generate_target_design(arch=ARCH, candidates=build_candidates(ARCH), cfg={})
    assert out["ai_enriched"] is False and out["enrich_reason"] == "llm_unavailable"


def test_target_design_filters_hallucinated_nodes():
    payload = {
        "nodes": [
            {"module": "APP", "members": ["APP/a.c"], "role": "응용", "is_new": False},
            {"module": "Diag_New", "members": ["ADC_HWEnDi"], "role": "진단 분리", "is_new": True},
            # 입력에 없는 심볼만 담은 노드 — 폐기 대상
            {"module": "Ghost", "members": ["nonexistent_fn", "no/such/file.c"], "role": "허구"},
        ],
        "edges": [
            {"from": "APP", "to": "Diag_New", "why": "진단 호출"},
            {"from": "APP", "to": "Ghost", "why": "폐기된 노드 참조"},
        ],
        "rationale": ["순환 2파일 · 최소 비용 간선 2회"],
    }
    out = generate_target_design(arch=ARCH, candidates=build_candidates(ARCH),
                                cfg={"model": "gemini"},
                                agent_call=lambda *a, **k: json.dumps(payload, ensure_ascii=False))
    td = out["target_design"]
    assert out["ai_enriched"] is True
    assert [n["module"] for n in td["nodes"]] == ["APP", "Diag_New"]
    assert td["dropped_nodes"] == 1
    # 폐기된 노드를 가리키는 엣지도 남기지 않는다(유령 노드 방지)
    assert [(e["from"], e["to"]) for e in td["edges"]] == [("APP", "Diag_New")]
    assert td["rationale"] == ["순환 2파일 · 최소 비용 간선 2회"]


def test_all_nodes_filtered_is_honest():
    payload = {"nodes": [{"module": "Ghost", "members": ["nope_fn"]}], "edges": []}
    out = generate_target_design(arch=ARCH, candidates=build_candidates(ARCH),
                                 cfg={"model": "m"},
                                 agent_call=lambda *a, **k: json.dumps(payload))
    assert out["target_design"] is None and out["enrich_reason"] == "all_nodes_filtered"


def test_llm_error_falls_back_without_raising():
    def _boom(*a, **k):
        raise RuntimeError("network down")

    out = generate_target_design(arch=ARCH, candidates=build_candidates(ARCH),
                                 cfg={"model": "m"}, agent_call=_boom)
    assert out["ai_enriched"] is False and out["enrich_reason"] == "llm_error"


def test_note_is_server_fixed():
    assert "검증된 설계가 아닙니다" in ARCH_IMPROVEMENT_NOTE
    assert "휴리스틱" in ARCH_IMPROVEMENT_NOTE


def test_cap_keeps_at_least_one_of_each_kind():
    """실측 회귀: 단순 절단은 정렬 뒤쪽(테스트 용이성)을 통째로 날렸다 — 종류별 최소 1건 보장."""
    many = dict(ARCH)
    many["cycles"] = {"file_sccs": [{"files": [f"f{i}.c", f"g{i}.c"], "size": 2} for i in range(4)]}
    many["file_graph"] = {
        "nodes": [{"file": f"f{i}.c", "module": "M"} for i in range(4)],
        "edges": [{"from": f"f{i}.c", "to": f"g{i}.c", "calls": 1} for i in range(4)],
    }
    many["refactor_candidates"] = [
        {"kind": "god_file", "file": f"big{i}.c", "basis": f"함수 {20 + i}개"} for i in range(4)
    ]
    cands = build_candidates(many, top_n=6)
    kinds = {c["kind"] for c in cands}
    # 구조 후보만으로 6칸을 채울 수 있지만 테스트 용이성 종류도 살아남아야 한다
    assert "extract_pure" in kinds or "inject_global" in kinds or "seam_for_pointer" in kinds
    assert len(cands) == 6


def test_default_cap_covers_all_per_kind_caps():
    from workflow.arch_improvement import DEFAULT_TOP_N, PER_KIND_CAP

    assert DEFAULT_TOP_N == sum(PER_KIND_CAP.values())
    s = summarize(build_candidates(ARCH))
    assert s["testability"] > 0          # 기본 상한에서 테스트 후보가 잘리지 않는다
    assert s["omitted"] == 0


def test_summary_reports_omitted():
    cands = build_candidates(ARCH, top_n=2)
    s = summarize(cands, omitted=len(build_candidates(ARCH)) - len(cands))
    assert s["total"] == 2 and s["omitted"] > 0
