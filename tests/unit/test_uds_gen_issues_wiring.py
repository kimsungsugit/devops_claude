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


class TestReadRequirementDocs:
    """(N37) 경로 지정 요구 문서는 공용 판독기 `read_requirement_doc` 으로 — cloudium U: 문서가 여기서만 직독이라 매 run 탈락했다."""

    def _patch(self, monkeypatch, table):
        from backend.services import resolver_helpers as RH
        calls = []

        def fake(path_str, *, allow=None):
            calls.append((path_str, allow))
            return table[path_str]
        monkeypatch.setattr(RH, "read_requirement_doc", fake)
        return calls

    def test_paths_go_through_shared_reader_with_allow(self, monkeypatch, tmp_path):
        local = tmp_path / "KJPDS02_SwRS.docx"
        calls = self._patch(monkeypatch, {r"U:\proj\KJPDS02_SwRS.docx": (local, "SwTR_0101 요구", "")})
        c = IssueCollector()
        texts, doc_paths, skipped = U._read_requirement_docs(c, [], [r"U:\proj\KJPDS02_SwRS.docx"])
        assert texts == ["SwTR_0101 요구"] and skipped == []
        assert doc_paths == [str(local)], "하류(Path 직독)에는 실체화된 로컬 경로가 가야 한다"
        assert calls == [(r"U:\proj\KJPDS02_SwRS.docx", U._is_allowed_req_doc)]
        assert _codes(c) == []

    def test_skip_reason_becomes_an_item_and_missing_is_actual(self, monkeypatch):
        self._patch(monkeypatch, {
            "U:/a/b/SwRS.docx": (None, "", "SwRS.docx: 접근 거부 — 워커 미응답"),
            "U:/a/b/SwDS.docx": (None, "", "SwDS.docx: 파일 없음 — 경로가 바뀌었거나 문서가 이동/개정됐을 수 있다"),
        })
        c = IssueCollector()
        texts, doc_paths, skipped = U._read_requirement_docs(c, [], ["U:/a/b/SwRS.docx", "", "U:/a/b/SwDS.docx"])
        assert texts == [] and doc_paths == []
        assert skipped == ["U:/a/b/SwRS.docx", "U:/a/b/SwDS.docx"], "탈락 경로는 호출부가 Reference 절에서 뺀다"
        items = c.as_list()
        assert [i["code"] for i in items] == ["requirement_doc_skipped", "requirement_doc_skipped", "requirements_missing"]
        assert "워커 미응답" in items[0]["message"]
        # facts 에는 파일명만 — 절대 경로는 Gemini 프롬프트·화면에 실린다(리뷰 W1)
        assert items[0]["facts"] == {"path": "SwRS.docx", "source": "path"}
        assert "U:/" not in str(items[0]["facts"]) and "U:/" not in items[0]["message"]
        assert items[2]["kind"] == "actual", "준 문서가 있는데 전부 탈락 = 된 문제"
        assert items[2]["facts"] == {"req_paths": 2, "req_files": 0, "skipped": 2}, "빈 항목은 시도가 아니다(리뷰 I3)"

    def test_no_docs_at_all_is_potential(self, monkeypatch):
        self._patch(monkeypatch, {})
        c = IssueCollector()
        U._read_requirement_docs(c, [], [])
        items = c.as_list()
        assert [i["code"] for i in items] == ["requirements_missing"] and items[0]["kind"] == "potential"

    def test_upload_temp_files_still_read_directly(self, monkeypatch, tmp_path):
        calls = self._patch(monkeypatch, {})
        f = tmp_path / "SwRS.txt"
        f.write_text("SwTR_0001 업로드 요구", encoding="utf-8")
        c = IssueCollector()
        texts, doc_paths, skipped = U._read_requirement_docs(c, [f], [])
        assert texts == ["SwTR_0001 업로드 요구"] and doc_paths == [] and calls == [] and skipped == []
        assert _codes(c) == []

    def test_upload_parser_missing_is_named_not_typeerror(self, monkeypatch, tmp_path):
        """`workflow.rag` 미설치면 `_read_text_from_file` 이 None — TypeError 로 위장하지 않는다(리뷰 I5)."""
        self._patch(monkeypatch, {})
        monkeypatch.setattr(U, "_read_text_from_file", None)
        f = tmp_path / "SwRS.docx"
        f.write_bytes(b"x")
        c = IssueCollector()
        texts, doc_paths, _ = U._read_requirement_docs(c, [f], [])
        assert texts == [] and doc_paths == [str(f)], ".docx 는 표 파서가 따로 연다(종전 동작)"
        items = c.as_list()
        assert items[0]["code"] == "requirement_doc_skipped" and "미설치" in items[0]["message"] and "TypeError" not in items[0]["message"]

    def test_body_delegates_and_has_no_direct_exists_loop(self):
        src = source_of(U._uds_generate_from_paths)
        assert "req_texts, req_doc_paths, _req_skipped = _read_requirement_docs(_issues, req_file_paths, req_paths)" in src
        assert "for path_str in req_paths:" not in src, "옛 `Path(path_str)…exists()` 직독 루프가 되살아났다"
        # req_map 은 한 번만(60%) — 82% 에서 같은 문서를 다시 열던 자리를 지웠다(리뷰 W3)
        assert src.count("_build_req_map_from_doc_paths(") == 1
        # 읽지 못한 문서는 1.4 Reference 에 올리지 않는다(리뷰 I2)
        assert "s not in _req_skipped" in src


class TestSdsPartitionMapNotWiredHere:
    """(R49 N38) SwDS 파티션 맵은 이 경로의 소스 분석에 넘기지 **않는다** — 라이브 run 2079 에서 정본 SwUDS 의 ASIL 657건이
    35건으로 밀리고 A→QM 327건이 났다(그 자리는 comment > override > sds 라 정본보다 위). 빈칸 채움 자리로 넣기 전까지 봉인."""

    def test_source_sections_call_has_no_partition_map(self):
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(source_of(U._uds_generate_from_paths)))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", "")) == "generate_uds_source_sections"]
        assert calls, "소스 분석 호출을 못 찾았다 — 선택자가 낡았다"
        for call in calls:
            kws = {k.arg for k in call.keywords}
            assert "sds_partition_map" not in kws, "정본(참조 SwUDS) ASIL 을 SDS 이름매칭이 덮는다 — N38 설계 판단 전엔 넣지 말 것"


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
