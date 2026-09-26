"""arch_playbook — 후보를 '어디를 어떻게'까지 끌어내리는 상세 개선안.

여기서 지키는 계약은 전부 정직성 쪽이다: 재료가 없으면 detail 을 만들지 않고, 분할 축이
없으면 군집을 지어내지 않으며, 코드는 스케치라고 매번 말한다. 하나라도 무너지면 화면이
"이 함수를 이렇게 고치세요"라고 근거 없이 지시하게 된다.
"""
from __future__ import annotations

from workflow.arch_playbook import (
    PLAYBOOK_VERSION,
    attach_playbooks,
    build_playbook,
    playbook_coverage,
)

# 실측(KJPDS02_PV build_125)에서 나온 형태를 그대로 축소한 것 — 값은 그때 관측된 것을 쓴다.
ARCH = {
    "available": True,
    "playbook_inputs": {
        "split_axis": {
            # 연결성분으로 깨끗이 갈리는 파일(실측 Ap_DoorPreCtrl_PDS.c 78/46/9/1, 절단면 0)
            "APP/split_ok.c": {
                "available": True, "axis": "call_component", "total_functions": 12,
                "n_groups": 2, "cut_calls": 0, "max_share": 0.583, "cover": 1.0,
                "groups": [
                    {"label": None, "functions": ["s_Env_Calc", "s_Env_Read"], "size": 7},
                    {"label": None, "functions": ["s_Perf_Track"], "size": 5},
                ],
            },
            # 이름 접두사로 갈리는 파일(실측 Sys_UDS_LinComp_PDS.c WDBI 36 / RDBI 27)
            "SYSTEM/prefix_ok.c": {
                "available": True, "axis": "name_prefix", "total_functions": 63,
                "n_groups": 2, "cut_calls": 3, "max_share": 0.4, "cover": 0.7,
                "groups": [
                    {"label": "s_UDS_WDBI", "functions": ["s_UDS_WDBI_A"], "size": 36},
                    {"label": "s_UDS_RDBI", "functions": ["s_UDS_RDBI_A"], "size": 27},
                ],
            },
            # 실측 8개 중 6개가 이랬다 — 최대 덩어리 95%
            "APP/no_axis.c": {
                "available": False, "reason": "no_natural_split",
                "components": 4, "largest_component_share": 0.953,
            },
        },
        "cycle_edge_functions": {
            "SYSTEM/a.c|SYSTEM/b.c": [
                {"caller": "A_Tick", "callee": "B_Notify"},
                {"caller": "A_Init", "callee": "B_Reset"},
            ],
            "Generated_Code/Cpu.c|Generated_Code/PT6.c": [
                {"caller": "PE_Initialize_Peripherals", "callee": "PT6_Init"},
            ],
        },
    },
}


def _cand(kind, target, **kw):
    return {"kind": kind, "target": target, **kw}


# ── 순환 끊기 ────────────────────────────────────────────────────────────────

def test_break_cycle_names_the_real_function_pair():
    """파일 쌍만으로는 못 고친다 — 실제 caller/callee 가 나와야 한다."""
    pb = build_playbook(_cand("break_cycle", "SYSTEM/a.c → SYSTEM/b.c", files=["SYSTEM/a.c", "SYSTEM/b.c"]), ARCH)
    assert pb is not None
    assert "B_Notify" in pb["summary"]
    assert any("A_Tick" in s for s in pb["steps"])
    assert "s_cb_B_Notify" in pb["sketch"]["after"]
    # 같은 간선의 나머지 호출도 숨기지 않는다(1곳만 고치면 끝이라는 오해 방지)
    assert "A_Init → B_Reset" in pb["impact"]["other_pairs"]
    assert pb["stub_plan"]["what"]


def test_break_cycle_without_material_returns_none():
    """간선 함수 쌍이 없으면 상세를 만들지 않는다 — 빈 절차는 정보가 아니다."""
    assert build_playbook(_cand("break_cycle", "X/unknown.c → Y/unknown.c"), ARCH) is None


def test_generated_code_is_flagged_not_refactored():
    pb = build_playbook(_cand("break_cycle", "Generated_Code/Cpu.c → Generated_Code/PT6.c"), ARCH)
    assert pb is not None
    assert any("자동 생성" in c for c in pb["caveats"])


# ── 파일 분할 ────────────────────────────────────────────────────────────────

def test_split_proposes_files_per_component():
    pb = build_playbook(_cand("split_god_file", "APP/split_ok.c", functions=12), ARCH)
    assert pb is not None
    files = [p["file"] for p in pb["split_proposal"]]
    assert len(files) == 2 and all(f.startswith("split_ok_") and f.endswith(".c") for f in files)
    # 절단면 0 은 '그냥 잘라도 파일 간 의존이 안 생긴다'는 뜻 — 그 사실을 말해야 판단이 선다
    assert "0" not in pb["summary"] or "호출이 0" in pb["summary"]
    assert pb["impact"]["cut_calls"] == 0


def test_split_uses_prefix_label_as_file_name():
    """이름 축이면 군집 라벨이 그대로 파일명이 된다 — part1 보다 훨씬 설명적이다."""
    pb = build_playbook(_cand("split_god_file", "SYSTEM/prefix_ok.c", functions=63), ARCH)
    names = [p["file"] for p in pb["split_proposal"]]
    assert "prefix_ok_s_UDS_WDBI.c" in names or any("WDBI" in n for n in names)
    assert pb["impact"]["cut_calls"] == 3


def test_split_file_name_drops_stem_tokens_and_scope_prefix():
    """`Sys_UDS_LinComp_PDS` + 라벨 `s_UDS_WDBI` → `..._WDBI.c` (`..._s_UDS_WDBI.c` 아님)."""
    arch = {"playbook_inputs": {"split_axis": {"SYSTEM/Sys_UDS_LinComp_PDS.c": {
        "available": True, "axis": "name_prefix", "n_groups": 2, "cut_calls": 0,
        "max_share": 0.4, "cover": 0.7,
        "groups": [
            {"label": "s_UDS_WDBI", "functions": ["s_UDS_WDBI_A", "s_UDS_WDBI_B"], "size": 36},
            {"label": "s_UDS_RDBI", "functions": ["s_UDS_RDBI_A"], "size": 27},
        ],
    }}}}
    pb = build_playbook(_cand("split_god_file", "SYSTEM/Sys_UDS_LinComp_PDS.c"), arch)
    names = [p["file"] for p in pb["split_proposal"]]
    assert names == ["Sys_UDS_LinComp_PDS_WDBI.c", "Sys_UDS_LinComp_PDS_RDBI.c"]


def test_tiny_groups_become_residual_not_their_own_file():
    """함수 1개짜리 .c 는 분할이 아니라 소음이다 — 실측에서 함수 이름이 통째로 파일명이 됐다."""
    arch = {"playbook_inputs": {"split_axis": {"APP/x.c": {
        "available": True, "axis": "call_component", "n_groups": 3, "cut_calls": 0,
        "max_share": 0.58, "cover": 1.0,
        "groups": [
            {"label": None, "functions": ["s_Env_A", "s_Env_B"], "size": 78},
            {"label": None, "functions": ["s_Perf_A", "s_Perf_B"], "size": 46},
            {"label": None, "functions": ["g_Ap_DoorPreCtrl_GetActiveHoldingTm"], "size": 1},
        ],
    }}}}
    pb = build_playbook(_cand("split_god_file", "APP/x.c"), arch)
    names = [p["file"] for p in pb["split_proposal"]]
    assert len(names) == 2
    assert not any("GetActiveHoldingTm" in n for n in names)
    assert any("나머지 1개 함수" in s for s in pb["steps"])


def test_single_function_group_gets_no_label():
    """함수가 1개면 '공통 접두사'가 그 이름 전체가 된다 — 라벨로 쓰면 안 된다."""
    from workflow.arch_playbook import _common_prefix_label

    assert _common_prefix_label(["g_Ap_DoorPreCtrl_GetActiveHoldingTm"]) is None
    assert _common_prefix_label(["s_Env_A_calc", "s_Env_A_read"]) == "s_Env_A"
    assert _common_prefix_label(["s_Env_Calc", "g_Perf_Track"]) is None


def test_split_without_axis_says_so_and_proposes_nothing():
    """실측 god_file 8개 중 6개가 이 경로다 — 억지 군집 대신 '없다'고 말한다."""
    pb = build_playbook(_cand("split_god_file", "APP/no_axis.c", functions=107), ARCH)
    assert pb is not None
    assert "기계적 분할선이 없다" in pb["summary"]
    assert "split_proposal" not in pb
    assert pb["sketch"] is None
    assert pb["impact"]["largest_component_share"] == 0.953


def test_split_without_material_returns_none():
    assert build_playbook(_cand("split_god_file", "APP/never_measured.c"), ARCH) is None


# ── 스텁 시임 (사용자 요구의 핵심) ─────────────────────────────────────────────

def test_seam_dispatch_table_gets_entry_replacement_plan():
    pb = build_playbook(_cand(
        "seam_for_pointer", "s_UDS_WDBI_HandleStdDid",
        pointer_symbols=["s_uds_wdbi_did_tbl[u8t_Index].pf_Handler"], ref_functions=[]), ARCH)
    assert pb is not None
    assert "테이블" in pb["summary"]
    assert "s_uds_wdbi_did_tbl[0].pf_Handler = &Stub_Handler;" in pb["sketch"]["after"]
    assert any("경계" in s or "NULL" in s for s in pb["steps"])


def test_seam_single_pointer_uses_register_api():
    pb = build_playbook(_cand("seam_for_pointer", "s_Lib_SafeWriteQueue_ExecuteWrite",
                              pointer_symbols=["pfn_WriteExecute"], ref_functions=[]), ARCH)
    assert "pfn_WriteExecute" in pb["stub_plan"]["what"][0]
    assert "Register_" in pb["sketch"]["after"]


def test_seam_without_symbols_returns_none():
    """개수만 있고 심볼이 없으면 스텁을 끼울 지점을 특정할 수 없다."""
    assert build_playbook(_cand("seam_for_pointer", "PE_Initialize_GPIO_Part1",
                                pointer_symbols=[], ref_functions=[]), ARCH) is None


# ── 나머지 종류 ──────────────────────────────────────────────────────────────

def test_extract_pure_on_generated_code_wraps_instead_of_editing():
    """생성 코드에 '함수를 추출하라'고 하면 다음 생성 때 사라진다 — 래퍼로 유도해야 한다."""
    pb = build_playbook(_cand("extract_pure", "ADC_MONITOR_HWEnDi",
                              files=["Generated_Code/ADC_MONITOR.c"], basis="구문 41% · 복잡도 7"), ARCH)
    assert any("래퍼" in s for s in pb["steps"])
    assert any("자동 생성" in c for c in pb["caveats"])


def test_extract_pure_on_normal_code_extracts():
    pb = build_playbook(_cand("extract_pure", "AppDecide", files=["APP/x.c"]), ARCH)
    assert any("추출" in s for s in pb["steps"])
    assert pb["caveats"] == []


def test_layer_violation_needs_both_functions():
    pb = build_playbook(_cand("layer_violation", "low → high",
                              functions=["s_LowTick", "g_HighNotify"], files=["BSW/l.c"]), ARCH)
    assert "g_HighNotify" in pb["summary"]
    assert build_playbook(_cand("layer_violation", "x", functions=["only_one"]), ARCH) is None


def test_inject_global_keeps_read_write_caveat():
    pb = build_playbook(_cand("inject_global", "g_shared",
                              functions=["f1", "f2"], basis="3개 모듈 · 9개 함수가 참조"), ARCH)
    assert "g_shared" in pb["sketch"]["before"]
    assert any("읽기/쓰기" in c for c in pb["caveats"])


# ── 공통 계약 ────────────────────────────────────────────────────────────────

def test_every_sketch_declares_it_is_a_sketch():
    """타입을 지어내지 않은 대신, 그대로 컴파일되지 않는다고 매번 말해야 한다."""
    cands = [
        _cand("break_cycle", "SYSTEM/a.c → SYSTEM/b.c"),
        _cand("seam_for_pointer", "f", pointer_symbols=["pfn_X"]),
        _cand("extract_pure", "g", files=["APP/x.c"]),
        _cand("inject_global", "g_v", functions=["a"]),
        _cand("layer_violation", "l → h", functions=["a", "b"]),
    ]
    for c in cands:
        pb = build_playbook(c, ARCH)
        assert pb["sketch"] is not None and "컴파일되지 않는다" in pb["sketch"]["note"]


def test_unknown_kind_and_broken_arch_are_survivable():
    assert build_playbook(_cand("no_such_kind", "x"), ARCH) is None
    assert build_playbook(_cand("break_cycle", "a → b"), {}) is None
    assert build_playbook(_cand("split_god_file", "APP/split_ok.c"), None) is None


def test_attach_is_additive_and_never_drops_candidates():
    cands = [
        _cand("break_cycle", "SYSTEM/a.c → SYSTEM/b.c"),
        _cand("split_god_file", "APP/never_measured.c"),   # 재료 없음
    ]
    out = attach_playbooks(cands, ARCH)
    assert len(out) == 2
    assert out[0]["detail"]["version"] == PLAYBOOK_VERSION
    assert "detail" not in out[1]
    assert out[0]["kind"] == "break_cycle" and out[0]["target"] == "SYSTEM/a.c → SYSTEM/b.c"
    # 원본 미변경(호출자가 같은 리스트를 다시 쓰는 경우 오염 금지)
    assert "detail" not in cands[0]


def test_coverage_counts_missing_details():
    out = attach_playbooks([
        _cand("break_cycle", "SYSTEM/a.c → SYSTEM/b.c"),
        _cand("split_god_file", "APP/never_measured.c"),
    ], ARCH)
    assert playbook_coverage(out) == {"total": 2, "with_detail": 1, "without_detail": 1}
