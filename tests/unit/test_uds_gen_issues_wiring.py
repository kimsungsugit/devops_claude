"""(R48-b) UDS 파이프라인의 문제 수집 배선 — `backend/helpers/uds.py`.

- `_note_*` 헬퍼 4종: 관측값(소스 캡·DOCX 통계·리포트 결과·quick gate) → 수집기 어휘. 성공/정상은 항목을 만들지 않는다.
- 래퍼 `_uds_generate_from_paths` 가 수집기 컨텍스트를 열고, 본체 시그니처를 그대로 보인다(`inspect.signature`).
- 소스 가드: 진행 콜백·완료 결과·품질 run meta 세 표면에 `issue_payload(_issues)` 가 실린다 — 하나가 빠지면 그 표면만 "문제 0건" 이 된다.
"""
from __future__ import annotations

import inspect

import pytest

from report_gen.gen_issues import IssueCollector
from tests.unit._source_probe import source_of

pytest.importorskip("fastapi")

from backend.helpers import uds as U  # noqa: E402


def _codes(c: IssueCollector):
    return [i["code"] for i in c.as_list()]


class TestNoteSourceCaps:
    def test_no_truncation_no_items(self):
        c = IssueCollector()
        U._note_source_caps(c, {"category_caps": {"any_truncated": False}, "file_scan": {"truncated": False},
                               "globals_scan": {"measured": True, "c_total": 5, "c_cap": 10, "h_total": 1, "h_cap": 10, "read_truncated_files": 0}})
        assert _codes(c) == []
        U._note_source_caps(c, "not a dict")
        assert _codes(c) == []

    def test_each_cap_axis_is_reported_with_facts(self):
        c = IssueCollector()
        U._note_source_caps(c, {
            "category_caps": {"any_truncated": True, "cap": 120, "truncated": {"macros": 12941, "interfaces": 300}},
            "file_scan": {"truncated": True, "cap": 1200},
            "globals_scan": {"measured": True, "c_total": 2000, "c_cap": 1500, "c_scanned": 1500, "h_total": 10, "h_cap": 100, "h_scanned": 10,
                             "read_truncated_files": 2, "read_truncated_detail": [{"file": "IO_Map.h", "bytes": 665000, "cap": 200000}]},
        })
        items = c.as_list()
        assert [i["code"] for i in items] == ["source_cap_reached", "source_cap_reached", "source_cap_reached", "source_read_truncated"]
        assert "macros" in items[0]["message"] and items[0]["facts"]["cap"] == 120
        assert items[1]["facts"] == {"cap": 1200, "axis": "files"}
        assert items[2]["facts"]["c_total"] == 2000
        assert items[3]["facts"]["files"] == 2 and items[3]["facts"]["detail"][0]["file"] == "IO_Map.h"
        assert all(i["kind"] == "actual" and i["severity"] == "warning" and i["stage"] == "source" for i in items)


class TestNoteDocxOutcome:
    def test_missing_stats_is_potential_not_silence(self):
        c = IssueCollector()
        U._note_docx_outcome(c, {})
        assert _codes(c) == ["gen_stats_missing"] and c.as_list()[0]["kind"] == "potential"

    def test_unmatched_and_identity(self):
        c = IssueCollector()
        U._note_docx_outcome(c, {
            "payload_functions": 1157, "matched_functions": 943, "match_pct": 81.5, "unmatched_payload_count": 214, "empty_heading_count": 3,
            "reference_suds": {"configured": True, "document": "X_v3.03.docx", "identity": {"same_project": False, "reason": "no_shared_tokens"},
                               "safety_fields_applied": 0, "safety_fields_blocked": 305},
        })
        items = {i["code"]: i for i in c.as_list()}
        assert items["docx_unmatched_functions"]["facts"] == {"payload_functions": 1157, "matched": 943, "match_pct": 81.5, "unmatched": 214, "empty_headings": 3}
        assert items["reference_identity_blocked"]["severity"] == "error" and items["reference_identity_blocked"]["facts"]["blocked"] == 305

    def test_same_project_true_and_full_match_are_quiet(self):
        c = IssueCollector()
        U._note_docx_outcome(c, {"payload_functions": 10, "matched_functions": 10, "unmatched_payload_count": 0, "empty_heading_count": 0,
                                 "reference_suds": {"configured": True, "identity": {"same_project": True}}})
        assert _codes(c) == []

    def test_unknown_identity_is_potential(self):
        c = IssueCollector()
        U._note_docx_outcome(c, {"reference_suds": {"configured": True, "document": "d", "identity": {}, "safety_fields_applied": 1, "safety_fields_blocked": 0}})
        assert _codes(c) == ["reference_identity_unknown"]


class TestNoteReport:
    def test_ok_is_quiet(self):
        c = IssueCollector()
        U._note_report(c, True, "", "accuracy report", 300)
        assert _codes(c) == []

    def test_timeout_vs_failure(self):
        c = IssueCollector()
        U._note_report(c, False, "accuracy report timeout (300s)", "accuracy report", 300)
        U._note_report(c, False, "boom: ValueError", "field quality gate report", 120)
        items = c.as_list()
        assert [i["code"] for i in items] == ["report_timeout:accuracy_report", "report_failed:field_quality_gate_report"]
        assert items[0]["facts"] == {"report": "accuracy report", "seconds": 300, "timed_out": True}
        assert "300초" in items[0]["message"] and "ValueError" in items[1]["message"]


class TestNoteQuickGate:
    def test_failing_axes_and_missing_thresholds(self):
        c = IssueCollector()
        U._note_quick_gate(c, {
            "rates": {"called_fill": 0.5, "input_fill": 0.95, "description_fill": 0.2},
            "thresholds": {"called_min": 0.95, "input_min": 0.9, "description_min": 0.0},
            "thresholds_missing": ["asil_trusted_min"],
        })
        items = {i["code"]: i for i in c.as_list()}
        assert "gate_fail:called_fill" in items and items["gate_fail:called_fill"]["facts"] == {"axis": "called_fill", "rate": 0.5, "threshold": 0.95}
        assert "gate_fail:input_fill" not in items
        assert "gate_fail:description_fill" not in items, "임계 0 은 '이 축은 보지 않는다' — 미달이 아니다"
        # 경계: 임계와 **같으면** 통과다(게이트 `_axis_pass` 는 `>=`) — `<=` 로 바뀌면 통과 축이 미달로 보인다(뮤테이션 M19).
        c2 = IssueCollector()
        U._note_quick_gate(c2, {"rates": {"asil_fill": 0.9, "description_fill": 0.0}, "thresholds": {"asil_min": 0.9, "description_min": 0.0}, "thresholds_missing": []})
        assert _codes(c2) == []
        assert items["threshold_missing:asil_trusted_min"]["severity"] == "error"

    def test_non_dict_is_quiet(self):
        c = IssueCollector()
        U._note_quick_gate(c, None)
        assert _codes(c) == []


class TestWrapperAndSurfaces:
    def test_body_uses_outer_collector_when_present(self):
        """바깥 `use_collector()` 가 있으면 그 수집기에 쌓인다(테스트·상위 호출자가 목록을 받아볼 수 있게)."""
        from report_gen.gen_issues import current_collector, use_collector
        with use_collector() as c:
            assert current_collector() is c
        # 시그니처는 그대로(호출부 4곳·가드가 인자 이름을 본다)
        sig = inspect.signature(U._uds_generate_from_paths)
        assert "reference_suds_path" in sig.parameters and "progress_cb" in sig.parameters
        src = source_of(U._uds_generate_from_paths)
        assert "_issues = current_collector() or IssueCollector()" in src

    def test_three_surfaces_carry_the_issue_payload(self):
        src = source_of(U._uds_generate_from_paths)   # 현재 파일 기준(저장소 규약 — 맨 getsource 금지)
        # 진행 콜백 · 완료 결과 · 품질 run meta
        assert 'payload = {"stage": stage, "percent": percent, "message": message, **issue_payload(_issues)}' in src
        assert src.count("**issue_payload(_issues)") >= 3
        assert "_note_quick_gate(_issues, _qg)" in src and "_record_uds_run(\n            _qg," in src
        assert "_note_docx_outcome(_issues, _read_gen_stats(out_path))" in src
        assert src.count("_note_report(_issues,") >= 7, "후처리 리포트 7종 전부 결과를 남겨야 한다(accuracy 300초 타임아웃이 매 run 조용했다)"
