# tests/unit/test_impact_report_coverage_axes.py
"""영향도 리포트가 부풀린 커버리지 **하나만** 싣던 것.

## 회귀 대상 (2026-07-29 실측)

`_load_linked_doc_summary` 가 STS 품질 리포트에서 `requirement_coverage["pct"]` 만
뽑아 실었다. 그 값은 **검증방법 무관** 커버리지라 RVW(수동 코드리뷰)만으로 커버된
요구도 분자에 든다. 같은 품질 리포트 안에 정직한 축들이 이미 있었는데 전부 유실됐다:

    영향도 리포트에 실림      requirement pct    100.0
    같은 리포트에 있는데 안 실림  실행시험 기준      87.3
                              함수 기준          6.4   (무시험 함수 699개)
                              생성기 경고        2건

리포트 독자는 "요구 커버리지 100%" 만 보고 나머지를 보지 못했다.

키는 **additive** 다 — 값이 없는 구 payload·다른 문서종(SUTS/SITS)은 렌더러가 줄 자체를
생략하므로 기존 산출물 형태가 깨지지 않는다.
"""
from __future__ import annotations

import json

import pytest

from workflow.impact_orchestrator import _load_linked_doc_summary


def _payload(tmp_path, quality, **extra):
    doc = tmp_path / "sts.xlsm"
    doc.write_text("x", encoding="utf-8")
    body = {"quality_report": quality}
    body.update(extra)
    doc.with_suffix(".payload.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return str(doc)


_STS_QUALITY = {
    "total_test_cases": 121,
    "requirement_coverage": {
        "total_reqs": 63, "covered_reqs": 63, "pct": 100.0,
        "executable_covered_reqs": 55, "executable_pct": 87.3,
        "review_only_reqs": ["R1"], "review_only_count": 8,
    },
    "generation_stats": {
        "mapped_functions": 747, "functions_with_tc": 48,
        "functions_without_tc": 699, "function_tc_coverage_pct": 6.4,
    },
    "coverage_warnings": ["요구 8건이 RVW 로만 커버됨", "캡으로 함수 699개 무시험"],
}


class TestHonestAxesReachTheSummary:
    def test_inflated_axis_is_still_carried(self, tmp_path):
        """기존 키는 그대로 — 소비처를 깨지 않는다."""
        s = _load_linked_doc_summary(_payload(tmp_path, _STS_QUALITY))
        assert s["requirement_coverage_pct"] == 100.0

    @pytest.mark.parametrize(("key", "want"), [
        ("executable_coverage_pct", 87.3),
        ("review_only_reqs", 8),
        ("function_tc_coverage_pct", 6.4),
        ("functions_without_tc", 699),
    ])
    def test_honest_axis_is_carried(self, tmp_path, key, want):
        s = _load_linked_doc_summary(_payload(tmp_path, _STS_QUALITY))
        assert s[key] == want, f"{key} 가 영향도 리포트에 전달되지 않는다"

    def test_generator_warnings_are_carried(self, tmp_path):
        """수치보다 경고가 행동을 바꾼다 — 예전엔 통째로 유실됐다."""
        s = _load_linked_doc_summary(_payload(tmp_path, _STS_QUALITY))
        assert len(s["coverage_warnings"]) == 2

    def test_sits_flow_cap_axes_are_carried(self, tmp_path):
        q = {"total_test_cases": 120, "integration_flow_coverage": {
            "total_flows_found": 145, "flows_emitted": 120, "flows_dropped": 25,
            "flow_emit_pct": 82.8, "dropped_safety_related_count": 0}}
        s = _load_linked_doc_summary(_payload(tmp_path, q))
        assert s["flows_dropped"] == 25
        assert s["flow_emit_pct"] == 82.8
        assert s["dropped_safety_related_flows"] == 0


class TestBackwardCompatible:
    def test_old_payload_without_new_keys_does_not_crash(self, tmp_path):
        """구 payload 는 새 키가 빈 문자열이면 된다(렌더러가 줄을 생략한다)."""
        s = _load_linked_doc_summary(_payload(
            tmp_path, {"total_test_cases": 5, "requirement_coverage": {"pct": 50.0}}))
        assert s["requirement_coverage_pct"] == 50.0
        assert s["executable_coverage_pct"] == ""
        assert s["functions_without_tc"] == ""
        assert s["coverage_warnings"] == []

    def test_missing_payload_returns_empty(self, tmp_path):
        assert _load_linked_doc_summary(str(tmp_path / "nope.xlsm")) == {}

    def test_empty_linked_doc_returns_empty(self):
        assert _load_linked_doc_summary("") == {}

    @pytest.mark.parametrize("bad", [None, [], "문자열", 3])
    def test_non_dict_quality_sections_do_not_crash(self, tmp_path, bad):
        s = _load_linked_doc_summary(_payload(
            tmp_path, {"requirement_coverage": bad, "generation_stats": bad,
                       "integration_flow_coverage": bad, "coverage_warnings": bad}))
        assert s["requirement_coverage_pct"] == ""
        assert s["coverage_warnings"] == []


class TestRenderedArtifactShowsTheAxes:
    """요약 dict 에만 담고 렌더러가 안 쓰면 리포트 독자는 여전히 못 본다."""

    @staticmethod
    def _render(tmp_path, monkeypatch, quality):
        import workflow.impact_orchestrator as mod
        from workflow.change_trigger import ChangeTrigger

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        linked = _payload(tmp_path, quality)
        trig = ChangeTrigger(trigger_type="manual", scm_id="T", source_root=str(tmp_path),
                             scm_type="git", base_ref="HEAD", changed_files=["a.c"])
        out = mod._write_review_artifact("sts", trig, {}, {}, None, linked)
        return (tmp_path / "reports" / "impact_audit" /
                out.split("impact_audit")[-1].lstrip("\\/")).read_text(encoding="utf-8") \
            if "impact_audit" in out else ""

    def test_all_axes_and_warnings_appear_in_markdown(self, tmp_path, monkeypatch):
        txt = self._render(tmp_path, monkeypatch, _STS_QUALITY)
        assert "87.3" in txt, "실행시험 기준 커버리지가 리포트에 안 보인다"
        assert "6.4" in txt, "함수 기준 커버리지가 리포트에 안 보인다"
        assert "699" in txt, "무시험 함수 수가 리포트에 안 보인다"
        assert "RVW" in txt, "생성기 경고가 리포트에 안 보인다"

    def test_label_states_the_axis(self, tmp_path, monkeypatch):
        """`100.0` 옆에 축이 안 적히면 '다 커버됐다' 로 읽힌다."""
        txt = self._render(tmp_path, monkeypatch, _STS_QUALITY)
        assert "검증방법 무관" in txt

    def test_absent_axes_do_not_emit_empty_rows(self, tmp_path, monkeypatch):
        """대조군 — 값이 없는 문서종에서 빈 행이 지면만 차지하면 안 된다."""
        txt = self._render(tmp_path, monkeypatch,
                           {"total_test_cases": 5, "requirement_coverage": {"pct": 50.0}})
        assert "함수 기준 시험 커버리지" not in txt
        assert "캡으로 제외된 통합 흐름" not in txt
