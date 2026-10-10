"""전용 FI(고장 주입) TC 축 — 판정 규칙과 발행 경로(R8-4).

정본(KJPDS02_PV_SwITS v1.02) 실측 54건 — 다른 조합 **0건**:

    REQ, IFT ↔ AOR, AEC   49   (동등분할 · 무효 등가류 EC1/EC7 포함)
    FI       ↔ AOR/ABV     5   (경계값분석 · `SwITC_FI_SwFn_07/34/36/37/41`)

즉 정본은 무효 경계 서브케이스를 가진 TC 를 FI 로 **올리지 않는다**. FI 는 전용 TC 다.

⚠ 옛 판정(`sub_cases` 라벨에 "ERR" 이 있으면 TC 전체가 FI)은 **살아 있는 지뢰**였다:
  오류전파 블록이 `len(sub_cases) < max_cases` 에 막혀 `max_subcases=7` 에서만 잠잠했고,
  기본값 `_DEFAULT_SUBCASES=14` 로 부르면 **전 TC 가 FI 로 뒤집혔다**.
"""
from __future__ import annotations

from typing import Any, Dict

from generators.sits import (
    _DEFAULT_SUBCASES,
    _SITS_GEN_BOUNDARY,
    _SITS_GEN_DEFAULT,
    _SITS_METHOD_DEFAULT,
    _SITS_METHOD_FAULT,
    _sits_gen_method,
    _sits_test_method,
    generate_itc_list,
)


def _flow(name: str = "Ap_Door_Run", **kw: Any) -> Dict[str, Any]:
    f: Dict[str, Any] = {
        "entry_fn": name, "call_chain": f"{name} -> Drv_Set", "module_name": "Ap",
        "input_vars": ["u8g_x", "u16g_y"],
        "input_raws": ["[IN] U8 u8g_x", "[IN] U16 u16g_y"],
        "expected_vars": ["u8g_out"], "expected_raws": ["[OUT] U8 u8g_out"],
        "indirect_vars": [], "asil": "A", "logic_flow": [], "related_ids": ["SwCom_01"],
    }
    f.update(kw)
    return f


class TestSubCaseBudgetDoesNotFlipTheTestMethod:
    """지뢰 회귀 — 예산을 올려도 일반 TC 는 `REQ, IFT` 여야 한다."""

    def test_raising_the_budget_keeps_req_ift(self):
        for mc in (7, 10, _DEFAULT_SUBCASES):
            itcs = generate_itc_list([_flow()], max_subcases=mc)
            assert itcs[0]["test_method"] == _SITS_METHOD_DEFAULT, (mc, itcs[0])
            assert _sits_test_method(itcs[0]) == _SITS_METHOD_DEFAULT, mc

    def test_error_propagation_subcase_does_not_promote_the_whole_tc(self):
        """서브케이스가 오류전파여도 TC 는 FI 가 아니다(정본 AEC↔FI 조합 0건)."""
        itcs = generate_itc_list([_flow()], max_subcases=_DEFAULT_SUBCASES)
        labels = [s.get("case_label", "") for s in itcs[0]["sub_cases"]]
        assert any("ERR" in str(x).upper() for x in labels),             "오류전파 서브케이스가 안 생겨 이 테스트가 아무것도 검증 못 한다"
        assert itcs[0]["test_method"] == _SITS_METHOD_DEFAULT, itcs[0]


class TestDedicatedFiTestCases:
    def test_fi_tc_is_emitted_for_a_requested_design_id(self):
        fi = [{**_flow("u16s_HallPower_Check"), "fi_design_id": "SwFn_34"}]
        itcs = generate_itc_list([_flow()], max_subcases=7, fi_flows=fi)
        fis = [t for t in itcs if t["test_method"] == _SITS_METHOD_FAULT]
        assert len(fis) == 1, itcs
        assert fis[0]["tc_id"] == "SwITC_FI_SwFn_34", fis[0]

    def test_fi_tc_uses_the_boundary_generation_method(self):
        """정본에서 FI 는 **항상** `AOR/ABV` 와 짝이다(다른 조합 0건)."""
        fi = [{**_flow("u16s_HallPower_Check"), "fi_design_id": "SwFn_34"}]
        itcs = generate_itc_list([_flow()], max_subcases=7, fi_flows=fi)
        f = next(t for t in itcs if t["test_method"] == _SITS_METHOD_FAULT)
        assert f["gen_method"] == _SITS_GEN_BOUNDARY, f
        assert _sits_gen_method(f["gen_method"], f["test_method"]) == _SITS_GEN_BOUNDARY
        n = next(t for t in itcs if t["test_method"] == _SITS_METHOD_DEFAULT)
        assert _sits_gen_method(n["gen_method"], n["test_method"]) == _SITS_GEN_DEFAULT

    def test_no_fi_without_a_request(self):
        """추측해서 발행하지 않는다 — 정본의 선별은 안전분석 산출물이다."""
        itcs = generate_itc_list([_flow()], max_subcases=_DEFAULT_SUBCASES)
        assert all(t["test_method"] != _SITS_METHOD_FAULT for t in itcs), itcs

    def test_fi_counts_reach_the_report(self):
        from generators.sits import _FLOW_COV_KEYS

        assert {"fi_emitted", "fi_requested", "fi_unresolved"} <= set(_FLOW_COV_KEYS)

    def test_zero_is_distinguishable_from_not_requested(self):
        stats: Dict[str, Any] = {}
        generate_itc_list([_flow()], max_subcases=7, stats_out=stats)
        assert stats["fi_requested"] == 0 and stats["fi_emitted"] == 0, stats
        stats2: Dict[str, Any] = {}
        generate_itc_list([_flow()], max_subcases=7, stats_out=stats2,
                          fi_flows=[{**_flow(), "fi_design_id": "SwFn_34"}])
        assert stats2["fi_requested"] == 1 and stats2["fi_emitted"] == 1, stats2

    def test_design_id_without_an_id_is_skipped_not_emitted_blank(self):
        stats: Dict[str, Any] = {}
        generate_itc_list([_flow()], max_subcases=7, stats_out=stats,
                          fi_flows=[{**_flow(), "fi_design_id": ""}])
        assert stats["fi_emitted"] == 0 and stats["fi_requested"] == 1, stats
