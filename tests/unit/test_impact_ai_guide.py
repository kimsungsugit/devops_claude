"""Tests for workflow.impact_ai_guide (deterministic parts)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workflow.impact_ai_guide import (
    assess_risk,
    analyze_cross_document_impact,
    generate_impact_guide,
    ImpactGuideContext,
)


class TestAssessRisk:
    def test_empty_changes(self):
        risk = assess_risk({}, {}, {})
        assert risk.grade == "LOW"
        assert risk.score == 0

    def test_qm_body_change(self):
        changed = {"func_a": "BODY"}
        by_name = {"func_a": {"asil": "QM"}}
        risk = assess_risk(changed, by_name, {"direct": ["func_a"]})
        assert risk.grade in ("LOW", "MEDIUM")
        assert not risk.asil_escalation

    def test_asil_d_signature_critical(self):
        changed = {"safety_func": "SIGNATURE"}
        by_name = {"safety_func": {"asil": "D"}}
        impact = {"direct": ["safety_func"], "indirect_1hop": ["dep1", "dep2", "dep3"]}
        risk = assess_risk(changed, by_name, impact)
        assert risk.grade in ("HIGH", "CRITICAL")
        assert risk.asil_escalation
        assert risk.max_asil == "D"
        assert any("safety_func" in sf for sf in risk.affected_safety_functions)

    def test_asil_b_escalation(self):
        changed = {"brake_ctrl": "BODY"}
        by_name = {"brake_ctrl": {"asil": "B"}}
        risk = assess_risk(changed, by_name, {"direct": ["brake_ctrl"]})
        assert risk.asil_escalation

    def test_large_scope_high(self):
        changed = {f"func_{i}": "BODY" for i in range(10)}
        by_name = {f"func_{i}": {"asil": "A"} for i in range(10)}
        impact = {"direct": [f"func_{i}" for i in range(10)],
                  "indirect_1hop": [f"dep_{i}" for i in range(15)]}
        risk = assess_risk(changed, by_name, impact)
        assert risk.score >= 25  # at least MEDIUM
        assert risk.grade in ("MEDIUM", "HIGH", "CRITICAL")

    def test_mixed_asil(self):
        changed = {"qm_func": "BODY", "asil_c_func": "HEADER"}
        by_name = {"qm_func": {"asil": "QM"}, "asil_c_func": {"asil": "C"}}
        risk = assess_risk(changed, by_name, {"direct": list(changed.keys())})
        assert risk.max_asil == "C"


class TestAnalyzeCrossDocumentImpact:
    def test_signature_affects_all(self):
        changed = {"func_a": "SIGNATURE"}
        result = analyze_cross_document_impact(changed)
        assert "uds" in result
        assert "suts" in result
        assert "sits" in result
        assert "sts" in result

    def test_body_change(self):
        changed = {"func_a": "BODY"}
        result = analyze_cross_document_impact(changed)
        assert "uds" in result
        assert "suts" in result
        assert "sds" in result  # BODY now affects SDS (design description update)

    def test_filtered_targets(self):
        changed = {"func_a": "SIGNATURE"}
        result = analyze_cross_document_impact(changed, targets=["uds", "suts"])
        assert "uds" in result
        assert "suts" in result
        assert "sits" not in result

    def test_empty_changes(self):
        result = analyze_cross_document_impact({})
        assert result == {}


class TestGenerateImpactGuide:
    def test_basic_guide(self):
        ctx = ImpactGuideContext(
            changed_types={"brake_ctrl": "BODY"},
            impact_groups={"direct": ["brake_ctrl"]},
            by_name={"brake_ctrl": {"asil": "QM", "description": "Brake control"}},
        )
        guide = generate_impact_guide(ctx)
        assert guide.risk.grade in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert guide.executive_summary
        assert guide.generated_at
        assert isinstance(guide.cross_doc_impacts, dict)
        assert isinstance(guide.review_checklist, list)

    def test_high_risk_has_checklist(self):
        ctx = ImpactGuideContext(
            changed_types={"safety_func": "SIGNATURE"},
            impact_groups={"direct": ["safety_func"], "indirect_1hop": ["dep1", "dep2"]},
            by_name={"safety_func": {"asil": "D"}},
        )
        guide = generate_impact_guide(ctx)
        assert guide.risk.asil_escalation
        # Should have CRITICAL priority item in checklist
        critical_items = [c for c in guide.review_checklist if c.get("priority") == "CRITICAL"]
        assert len(critical_items) >= 1

    def test_to_dict(self):
        ctx = ImpactGuideContext(
            changed_types={"func_a": "BODY"},
            impact_groups={},
            by_name={},
        )
        guide = generate_impact_guide(ctx)
        d = guide.to_dict()
        assert "executive_summary" in d
        assert "risk" in d
        assert "review_checklist" in d
        assert "cross_doc_impacts" in d
        assert "ai_enriched" in d

    def test_empty_context(self):
        ctx = ImpactGuideContext(
            changed_types={},
            impact_groups={},
            by_name={},
        )
        guide = generate_impact_guide(ctx)
        assert guide.risk.grade == "LOW"

    def test_test_recommendations_for_new(self):
        ctx = ImpactGuideContext(
            changed_types={"new_func": "NEW"},
            impact_groups={"direct": ["new_func"]},
            by_name={"new_func": {"asil": "A"}},
            suts_tcs={},  # no existing TCs
        )
        guide = generate_impact_guide(ctx)
        assert len(guide.test_recommendations) >= 1
        assert any("신규" in r.get("test_type", "") or "NEW" in r.get("test_type", "")
                    for r in guide.test_recommendations)


def test_unknown_asil_not_silently_defaulted_to_qm():
    """ASIL 정보가 없으면 QM(비안전)으로 단정하지 않고 UNKNOWN으로 표시 + 수동확인 체크리스트(안전측, CLAUDE.md #4)."""
    from workflow.impact_ai_guide import generate_impact_guide, ImpactGuideContext

    g = generate_impact_guide(ImpactGuideContext(
        changed_types={"foo": "BODY"},
        impact_groups={"direct": ["foo"], "indirect_1hop": [], "indirect_2hop": []},
        by_name={},  # ASIL 정보 없음
    )).to_dict()
    assert g["risk"]["unknown_asil_count"] >= 1
    assert g["risk"]["max_asil"] == "UNKNOWN"
    assert g["risk"]["grade"] != "LOW"   # 미상이면 LOW 단정 금지
    assert any("ASIL 미상" in c.get("item", "") for c in g["review_checklist"])


def test_known_asil_still_classified():
    """명시적 ASIL D는 정상 분류(회귀 보호)."""
    from workflow.impact_ai_guide import generate_impact_guide, ImpactGuideContext

    g = generate_impact_guide(ImpactGuideContext(
        changed_types={"safety_fn": "SIGNATURE"},
        impact_groups={"direct": ["safety_fn"], "indirect_1hop": [], "indirect_2hop": []},
        by_name={"safety_fn": {"asil": "D"}},
    )).to_dict()
    assert g["risk"]["max_asil"] == "D"
    assert g["risk"]["unknown_asil_count"] == 0
    assert g["risk"]["asil_escalation"] is True
