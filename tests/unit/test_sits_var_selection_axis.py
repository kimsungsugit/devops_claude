"""관측 대상 선별 축이 **산출물에서 보이는가**(R9-1).

정본(KJPDS02_PV_SwITS v1.02)은 관측 대상을 VectorCAST 실행 결과에서 고르고 우리는 정적
호출 그래프만 본다. 깊이는 이미 최적점이다 — `generators/sits.py:_VAR_SCAN_DEPTH` 주석의
깊이별 실측표에서 깊이 3 은 회수 +18 에 총량 +273(정밀도 21.1%→17.7%)이다. 즉 **더 담아서
줄지 않는 격차**다.

그래서 이 축은 닫지 않고 **보이게** 만든다. 산출물만 보면 "82칸을 채웠다" 와 "후보 400 중
82 만 담았다" 가 같은 모양이었다.

⚠ 세기를 추가하면서 담는 규칙은 **바뀌면 안 된다**. 여기 첫 클래스가 그걸 고정한다 —
  계측을 넣다가 산출물을 바꾸면 8라운드 정본 대조가 통째로 무효가 된다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from generators.sits import (
    _FLOW_COV_KEYS,
    _FLOW_LOSS_KEYS,
    _FLOW_LOSS_NAME_MARKERS,
    _MAX_INPUT_PARAMS,
    collect_integration_flows,
)


def _f(name: str, file: str, calls: List[str], **kw: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": name, "file": file, "calls_list": list(calls),
        "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
        "asil": "B",
    }
    d.update(kw)
    return d


def _fd(n_globals: int) -> Dict[str, Any]:
    """진입점이 다른 모듈 함수를 부르고, 그 함수가 전역 n개를 건드린다."""
    return {
        "F1": _f("Ap_Door_Run", "Ap_Door.c", ["Drv_Motor_Set"]),
        "F2": _f("Drv_Motor_Set", "Drv_Motor.c", [],
                 globals_global=[f"[INDIRECT] U8 g_var_{i:03d}" for i in range(n_globals)]),
    }


def _run(n_globals: int):
    stats: Dict[str, Any] = {}
    flows = collect_integration_flows(_fd(n_globals), stats_out=stats, sds_map={})
    flow = next(f for f in flows if f["entry_fn"] == "Ap_Door_Run")
    return flow, stats


class TestCountingDoesNotChangeWhatIsEmitted:
    """세기를 추가해도 **실리는 것**은 그대로여야 한다."""

    def test_budget_still_caps_the_emitted_columns(self):
        flow, _ = _run(_MAX_INPUT_PARAMS + 40)
        assert len(flow["input_vars"]) <= _MAX_INPUT_PARAMS, len(flow["input_vars"])

    def test_names_and_raws_stay_paired(self):
        """SITS 는 이름과 원문을 **인덱스로** 짝짓는다 — 길이가 어긋나면 값이 밀린다."""
        flow, _ = _run(_MAX_INPUT_PARAMS + 40)
        assert len(flow["input_vars"]) == len(flow["input_raws"]), flow

    def test_small_input_is_emitted_whole(self):
        """예산 안쪽이면 후보가 전부 실린다(세기가 필터로 둔갑하지 않는다)."""
        flow, stats = _run(5)
        for i in range(5):
            assert f"g_var_{i:03d}" in flow["input_vars"], flow["input_vars"]
        assert stats["var_budget_cut_input"] == 0, stats


class TestTheCeilingIsVisible:
    """못 담은 후보 수가 산출물에 남는가."""

    def test_dropped_candidates_are_counted(self):
        """⚠ 관계를 **정확히** 단언한다.

        처음엔 `cut >= over - len(vars) + 1 or cut > 0` 로 썼다가 뮤테이션(`cut += 0`)이
        살아남았다 — 앞 항이 음수가 돼 `0 >= -41` 로 **항상 참**이었다. 느슨한 `or` 는
        가드가 아니다.
        """
        over = 40
        flow, stats = _run(_MAX_INPUT_PARAMS + over)
        assert stats["var_candidates_input"] == _MAX_INPUT_PARAMS + over, stats
        # 후보 122 · 열 82 → 못 담은 것 정확히 40. 0 이면 "예산이 넉넉했다" 와 구별 안 됨.
        assert stats["var_budget_cut_input"] == over, stats
        assert len(flow["input_vars"]) == _MAX_INPUT_PARAMS, len(flow["input_vars"])

    def test_cut_is_zero_when_budget_is_enough(self):
        _, stats = _run(3)
        assert stats["var_budget_cut_input"] == 0, stats
        assert stats["var_candidates_input"] >= 3, stats

    def test_basis_is_stated_not_implied(self):
        """정본과 다른 집합이 나오는 **이유**를 산출물이 말한다.

        수치만 있으면 30% 일치가 결함으로 읽힌다. 원리적 차이는 사실대로 적는다.
        """
        _, stats = _run(3)
        assert stats["var_selection_basis"] == "static_call_graph", stats
        assert stats["var_scan_depth"] >= 1, stats
        assert stats["var_scan_nodes_max"] >= 1, stats

    def test_axis_reaches_the_quality_report(self):
        from generators.sits import generate_sits_quality_report

        _, stats = _run(_MAX_INPUT_PARAMS + 10)
        cov = generate_sits_quality_report(
            [], total_source_functions=2, flow_stats=stats)["integration_flow_coverage"]
        for key in ("var_selection_basis", "var_scan_depth", "var_candidates_input",
                    "var_budget_cut_input", "var_candidates_expected",
                    "var_budget_cut_expected"):
            assert key in cov, f"{key} 가 리포트에 없다"


class TestLossKeysAreASingleSource:
    """손실 축 목록이 소비처마다 갈라지지 않는가.

    ⚠ 이 저장소는 같은 결함을 **세 층**에서 겪었다: 생산자→리포트, 리포트→평가기,
      리포트→영향도. 세 번 다 "손으로 나열한 목록" 이 원인이었다.
    """

    def test_loss_keys_are_a_subset_of_reported_keys(self):
        missing = sorted(set(_FLOW_LOSS_KEYS) - set(_FLOW_COV_KEYS))
        assert not missing, f"리포트에 실리지 않는 손실 키: {missing}"

    def test_every_loss_named_key_is_registered(self):
        """이름 규약을 따르는 키가 목록에서 빠지면 실패.

        새 손실 키를 만든 사람이 `_FLOW_LOSS_KEYS` 를 잊어도 여기서 걸린다 — 잊으면
        영향도 카드가 조용히 옛 목록만 싣는다.
        """
        named = {
            k for k in _FLOW_COV_KEYS
            if any(m.strip("_") in k for m in _FLOW_LOSS_NAME_MARKERS)
        }
        missing = sorted(named - set(_FLOW_LOSS_KEYS))
        assert not missing, (
            f"손실 이름 규약을 따르는데 _FLOW_LOSS_KEYS 에 없다: {missing}")

    def test_markers_are_not_empty(self):
        """규약 어휘가 비면 위 가드가 **공허하게 통과**한다."""
        assert _FLOW_LOSS_NAME_MARKERS, "손실 이름 어휘가 비었다"
        assert _FLOW_LOSS_KEYS, "손실 키 목록이 비었다"
