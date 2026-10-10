"""생산자가 낸 흐름 지표가 **평가기·영향도까지** 도달하는가(R9-2).

`test_generators_sits.py::TestFlowStatsReachTheReport` 가 생산자→리포트를 고정했는데,
**같은 결함이 한 층 위에 그대로 있었다**: 평가기(`workflow/quality/evaluator.py`)와
영향도 카드(`workflow/impact_orchestrator.py`)가 **각자 같은 3키를 손으로** 들고 있어,
생산자에 키를 35개까지 늘려도 둘 다 3개만 봤다.

실측(2026-08-18): 생산자 35키 · 리포트 35키 · 평가기 3키 · 프론트 0키.

⚠ 가드를 이름 나열로 쓰면 안 된다 — 그러면 이 가드 자신이 네 번째 손나열이 된다.
  **집합 차집합**으로 검사한다.
"""
from __future__ import annotations

from typing import Any, Dict

from workflow.quality.evaluator import evaluate_sits


def _report(**flow_cov: Any) -> Dict[str, Any]:
    base = {"total_flows_found": 10, "flows_emitted": 8, "flow_emit_pct": 80.0,
            "flows_dropped": 2, "dropped_safety_related_count": 1}
    base.update(flow_cov)
    return {"total_test_cases": 8, "integration_flow_coverage": base}


def _names(report: Dict[str, Any]) -> set:
    return {m["metric_name"] for m in evaluate_sits(report)}


class TestEveryNumericFlowKeyReachesTheEvaluator:
    def test_no_numeric_key_is_silently_dropped(self):
        """리포트에 있는 **모든 수치 키**가 지표가 된다 — 차집합으로 검사."""
        cov = {"total_flows_found": 10, "flows_emitted": 8, "flow_emit_pct": 80.0,
               "flows_dropped": 2, "dropped_safety_related_count": 1,
               "var_candidates_input": 400, "var_budget_cut_input": 318,
               "array_skipped_budget": 3, "fi_unresolved": 2,
               "related_truncated_ids": 7, "strategy_nodes_dropped": 5}
        names = _names({"total_test_cases": 8, "integration_flow_coverage": cov})
        # 이 셋은 예전 이름을 유지한다(기존 소비처 호환).
        legacy = {"flow_emit_pct", "flows_dropped", "dropped_safety_related_flows"}
        numeric = {k for k, v in cov.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}
        expected = {f"flow_{k}" for k in numeric
                    if k not in {"flow_emit_pct", "flows_dropped",
                                 "dropped_safety_related_count"}}
        missing = sorted(expected - names)
        assert not missing, f"평가기에 도달하지 않은 흐름 지표: {missing}"
        assert legacy <= names, sorted(legacy - names)

    def test_a_brand_new_key_arrives_without_touching_the_evaluator(self):
        """새 키를 넣으면 평가기 수정 없이 나타난다 — 이게 손나열과의 차이다."""
        names = _names(_report(some_future_axis_count=42))
        assert "flow_some_future_axis_count" in names, sorted(names)

    def test_non_numeric_keys_are_counted_not_swallowed(self):
        """수치가 아니라 못 싣는 키는 **몇 개인지** 남는다."""
        rep = _report(var_selection_basis="static_call_graph",
                      dropped_entry_fns=["a", "b"])
        by = {m["metric_name"]: m["value"] for m in evaluate_sits(rep)}
        assert by.get("flow_metrics_unrepresentable") == 2.0, by

    def test_booleans_do_not_leak_in_as_one(self):
        """bool 은 int 의 하위형이라 먼저 걸러야 True 가 1.0 으로 새지 않는다."""
        by = {m["metric_name"]: m["value"] for m in evaluate_sits(_report(some_flag=True))}
        assert "flow_some_flag" not in by, by
        assert by.get("flow_metrics_unrepresentable") == 1.0, by


class TestNoThresholdIsAdded:
    """정책: 새 지표에 임계를 붙이지 않는다(기존 프로젝트 pass/fail 을 뒤집는다).

    근거는 `workflow/quality/evaluator.py` 같은 자리의 주석이다.
    """

    def test_new_flow_metrics_are_non_gating(self):
        rep = _report(var_budget_cut_input=318, array_skipped_budget=3)
        for m in evaluate_sits(rep):
            if m["metric_name"].startswith("flow_") and m["metric_name"] != "flow_emit_pct":
                assert m["threshold"] is None, m
                assert m["gate_pass"] is None, m


class TestImpactCardTakesLossAxesFromOneSource:
    """영향도 카드가 손실 축을 **목록 하나**에서 가져오는가."""

    def test_all_nonzero_loss_axes_appear(self):
        from generators.sits import _FLOW_LOSS_KEYS
        from workflow.impact_orchestrator import _flow_loss_fields

        flow: dict = {k: 3 for k in _FLOW_LOSS_KEYS}
        flow["dropped_asil_distribution"] = {"B": 2, "QM": 5}
        flow["dropped_entry_fns"] = ["fn_a", "fn_b"]
        out = _flow_loss_fields(flow)
        missing = sorted({f"flow_{k}" for k in _FLOW_LOSS_KEYS} - set(out))
        assert not missing, f"카드에 안 실린 손실 축: {missing}"

    def test_structures_are_folded_not_dumped(self):
        from workflow.impact_orchestrator import _flow_loss_fields

        out = _flow_loss_fields({"dropped_asil_distribution": {"B": 2, "QM": 5},
                                 "dropped_entry_fns": ["a", "b", "c"]})
        assert out["flow_dropped_asil_distribution"] == "B=2, QM=5", out
        assert out["flow_dropped_entry_fns"] == 3, out

    def test_zero_loss_adds_no_rows(self):
        """손실 0 은 정상이다 — 카드에 줄을 더할 이유가 없다."""
        from generators.sits import _FLOW_LOSS_KEYS
        from workflow.impact_orchestrator import _flow_loss_fields

        assert _flow_loss_fields({k: 0 for k in _FLOW_LOSS_KEYS}) == {}
        assert _flow_loss_fields({}) == {}
        assert _flow_loss_fields(None) == {}

    def test_a_new_loss_key_needs_no_edit_here(self):
        """`_FLOW_LOSS_KEYS` 에 키가 늘면 카드도 자동으로 늘어난다."""
        from generators.sits import _FLOW_LOSS_KEYS
        from workflow.impact_orchestrator import _flow_loss_fields

        out = _flow_loss_fields({k: 1 for k in _FLOW_LOSS_KEYS})
        assert len(out) == len(_FLOW_LOSS_KEYS), (len(out), len(_FLOW_LOSS_KEYS))

    def test_the_card_builder_actually_calls_it(self, tmp_path):
        """⚠ **헬퍼 단독 테스트는 호출부가 값을 버리는 걸 못 본다.**

        `_flow_loss_fields` 를 아무리 검사해도 `_load_linked_doc_summary` 가
        `**{}` 로 바꿔치기되면 초록으로 남는다 — 실제로 뮤테이션이 살아남았다
        ([[feedback_guard_must_change_observable]] 의 그 패턴이 또 났다).
        여기서는 **카드를 만드는 함수의 반환값**을 본다.
        """
        import json

        from workflow.impact_orchestrator import _load_linked_doc_summary

        doc = tmp_path / "sits_out.xlsm"
        (tmp_path / "sits_out.payload.json").write_text(json.dumps({
            "test_case_count": 367,
            "quality_report": {
                "total_test_cases": 367,
                "integration_flow_coverage": {
                    "total_flows_found": 400, "flows_emitted": 367,
                    "flows_dropped": 33, "dropped_safety_related_count": 4,
                    "var_budget_cut_input": 318, "array_skipped_budget": 3,
                    "dropped_entry_fns": ["fn_a", "fn_b"],
                },
            },
        }, ensure_ascii=False), encoding="utf-8")

        card = _load_linked_doc_summary(str(doc))
        assert card, "카드가 비었다 — payload 를 못 읽었다"
        assert card.get("flow_var_budget_cut_input") == 318, card
        assert card.get("flow_array_skipped_budget") == 3, card
        assert card.get("flow_dropped_entry_fns") == 2, card
        # 기존 3키도 그대로 있어야 한다(하위 호환).
        assert card.get("flows_dropped") == 33, card
