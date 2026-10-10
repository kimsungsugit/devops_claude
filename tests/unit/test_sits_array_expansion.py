"""SITS 도 배열을 **원소 단위로** 적는다(R8-3).

정본(KJPDS02_PV_SwITS v1.02)은 `g_sys_error_his[0]`…`[15]` ·
`u8g_SysEepromCtrl_PartNoInfo[0]`…`[9]` 처럼 원소별로 펼쳐 적는다. 우리는 base 한
칸으로 내고 있었다 — 같은 대상을 **다른 입도로** 부르는 것이라 과다와 미달이 동시에
생긴다(실측: 정본 `[N]` 셀 414 vs 우리 179).

⚠ 크기 판정은 SUTS 자산에 위임한다(`_array_sizes`/`_expand_array_entries`). 여기서
  다시 쓰면 한쪽만 고쳐진다 — 이 저장소가 반복해 겪은 형태다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from generators.sits import _MAX_EXP_PARAMS, _MAX_INPUT_PARAMS, collect_integration_flows


def _f(name: str, file: str, calls: List[str], **kw: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": name, "file": file, "calls_list": list(calls),
        "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
        "asil": "B",
    }
    d.update(kw)
    return d


def _fd(**entry_kw: Any) -> Dict[str, Any]:
    """진입점 하나가 다른 모듈을 부르는 최소 통합 흐름."""
    return {
        "F1": _f("Ap_Door_Run", "Ap_Door.c", ["Drv_Motor_Set"], **entry_kw),
        "F2": _f("Drv_Motor_Set", "Drv_Motor.c", []),
    }


def _flow(fd: Dict[str, Any], stats: Dict[str, Any] | None = None, **kw: Any):
    flows = collect_integration_flows(fd, stats_out=stats, sds_map={}, **kw)
    return next(f for f in flows if f["entry_fn"] == "Ap_Door_Run")


class TestArraysAreExpandedToElements:
    def test_input_globals_expand(self):
        f = _flow(_fd(globals_global=["[INDIRECT] U8 g_hist (size: 4)"]))
        assert f["input_vars"] == [f"g_hist[{i}]" for i in range(4)], f["input_vars"]

    def test_expected_outputs_expand(self):
        """입력만 펼치면 한 행에서 같은 변수가 두 이름으로 나온다(SUTS 실측 120건)."""
        f = _flow(_fd(outputs=["[OUT] U16 u16g_buf (size: 3)"]))
        assert f["expected_vars"] == [f"u16g_buf[{i}]" for i in range(3)], f["expected_vars"]

    def test_declared_size_comes_from_globals_info_map_when_the_tail_is_absent(self):
        """문서 유래 이름엔 `(size: N)` 꼬리가 없다 — 선언표가 유일한 크기 출처다."""
        f = _flow(_fd(globals_global=["[INDIRECT] U8 g_hist"]),
                  globals_info_map={"g_hist": {"type": "U8", "array": "[4]"}})
        assert f["input_vars"] == [f"g_hist[{i}]" for i in range(4)], f["input_vars"]

    def test_scalar_names_are_untouched(self):
        f = _flow(_fd(globals_global=["[INDIRECT] U8 g_flag"]))
        assert f["input_vars"] == ["g_flag"], f["input_vars"]


class TestRawsStayPairedWithNames:
    """⚠ SITS 고유 위험 — 이름과 원문을 **인덱스로** 짝짓는다.

    `_generate_sub_cases` 가 `expected_raws[ev_idx]` 로 원문을 찾는다. 이름만 늘리면
    원소마다 **다른 변수의** 타입·경계값이 붙는다. 값이 틀리는 게 아니라 짝이 밀린다.
    """

    def test_input_names_and_raws_have_equal_length(self):
        f = _flow(_fd(globals_global=["[INDIRECT] U8 g_hist (size: 4)",
                                      "[INDIRECT] U8 g_flag"]))
        assert len(f["input_vars"]) == len(f["input_raws"]), f

    def test_expected_names_and_raws_have_equal_length(self):
        f = _flow(_fd(outputs=["[OUT] U16 u16g_buf (size: 3)", "[OUT] U8 u8g_state"]))
        assert len(f["expected_vars"]) == len(f["expected_raws"]), f

    def test_each_element_carries_its_own_base_raw(self):
        """원소의 원문은 **자기 base 의 것**이어야 한다 — 뒤 변수 것이 오면 짝이 밀린 것."""
        f = _flow(_fd(globals_global=["[INDIRECT] U8 g_hist (size: 3)",
                                      "[INDIRECT] U16 g_other"]))
        # `strict=True` — 길이가 어긋나면 조용히 짧은 쪽에서 멈추는 게 아니라
        # 실패해야 한다. 이 테스트가 보려는 결함이 정확히 그 길이 어긋남이다.
        pairs = dict(zip(f["input_vars"], f["input_raws"], strict=True))
        for i in range(3):
            assert "g_hist" in pairs[f"g_hist[{i}]"], pairs
        assert "g_other" in pairs["g_other"], pairs


class TestBudgetAndReporting:
    def test_budget_is_the_reference_column_capacity(self):
        """예산이 정본 열 수와 같아야 원소가 그만큼 들어간다(옛 주석은 67/70 이었다)."""
        assert _MAX_INPUT_PARAMS == 82
        assert _MAX_EXP_PARAMS == 113

    def test_oversized_array_keeps_the_base_name_and_is_reported(self):
        """예산을 넘으면 **자르지 않고 안 펼친다** — 그리고 그 사실을 보고한다."""
        big = _MAX_INPUT_PARAMS + 10
        stats: Dict[str, Any] = {}
        f = _flow(_fd(globals_global=[f"[INDIRECT] U8 g_big (size: {big})"]), stats)
        assert f["input_vars"] == ["g_big"], f["input_vars"]
        assert stats["array_skipped_budget"] >= 1, stats

    def test_expansion_counts_reach_the_quality_report(self):
        from generators.sits import _FLOW_COV_KEYS

        assert {"array_expanded_inputs", "array_expanded_expected",
                "array_elements_emitted", "array_skipped_budget",
                "array_size_map_entries", "array_struct_types"} <= set(_FLOW_COV_KEYS),             _FLOW_COV_KEYS

    def test_struct_member_axis_is_counted_separately(self):
        """구조체 멤버 배열은 별도 축이다.

        ⚠ 전역 선언 수에 합치면 **0 인지 아닌지 안 보인다**. 실제로 이 맵이 캐시에
          없어 0 인 채로 돌던 것을 진단하는 데 한 라운드가 들었다
          (`_SOURCE_SECTIONS_SCHEMA_VERSION` v11 → v12).
        """
        stats: Dict[str, Any] = {}
        _flow(_fd(globals_global=["[INDIRECT] U8 g_flag"]), stats,
              struct_members={"MyT": {"buf": "[4]"}})
        assert stats["array_struct_types"] == 1, stats
        stats2: Dict[str, Any] = {}
        _flow(_fd(globals_global=["[INDIRECT] U8 g_flag"]), stats2)
        assert stats2["array_struct_types"] == 0, stats2

    def test_zero_expansion_is_distinguishable_from_broken_wiring(self):
        """0 이 '펼칠 게 없었다'인지 '맵이 안 왔다'인지 구분된다."""
        stats: Dict[str, Any] = {}
        _flow(_fd(globals_global=["[INDIRECT] U8 g_flag"]), stats,
              globals_info_map={"g_x": {"type": "U8", "array": "[4]"}})
        assert stats["array_expanded_inputs"] == 0
        assert stats["array_size_map_entries"] >= 1, stats
