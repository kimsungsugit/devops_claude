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

    def test_unplaced_text_sections_are_reported_with_sizes(self):
        """(R50 N38) run 2078: SwRS 요구 절 79,572자가 정본 레이아웃에 자리가 없어 침묵으로 빠졌다."""
        c = IssueCollector()
        U._note_docx_outcome(c, {"payload_functions": 1, "matched_functions": 1, "unmatched_payload_count": 0, "empty_heading_count": 0,
                                 "text_sections_unplaced": {"requirements": 79572}})
        items = {i["code"]: i for i in c.as_list()}
        assert list(items) == ["text_section_unplaced"]
        it = items["text_section_unplaced"]
        assert (it["severity"], it["kind"]) == ("warning", "actual")
        assert "requirements(79,572자)" in it["message"]
        assert it["facts"] == {"sections": ["requirements"], "chars": {"requirements": 79572}}

    def test_empty_unplaced_dict_is_quiet(self):
        c = IssueCollector()
        U._note_docx_outcome(c, {"payload_functions": 1, "matched_functions": 1, "unmatched_payload_count": 0, "empty_heading_count": 0,
                                 "text_sections_unplaced": {}})
        assert _codes(c) == []

    def test_reference_overrides_are_reported_by_previous_source(self):
        """(R50 N38) 정본이 SwDS·모듈상속 값을 덮었다 — run 2079 였다면 여기 327 이 찍혔다. 정본이 권위라 error 가 아니라 warning."""
        c = IssueCollector()
        U._note_docx_outcome(c, {"reference_suds": {"configured": True, "document": "X_v3.03.docx", "identity": {"same_project": True},
                                                    "safety_fields_applied": 660, "safety_fields_blocked": 0, "safety_fields_agreed": 12,
                                                    "safety_fields_overridden": {"sds": 300, "module_inherit": 27}}})
        items = {i["code"]: i for i in c.as_list()}
        assert list(items) == ["reference_overrode_doc_asil"]
        it = items["reference_overrode_doc_asil"]
        assert (it["severity"], it["kind"]) == ("warning", "actual")
        assert "327건" in it["message"] and "sds 300" in it["message"]
        assert it["facts"] == {"document": "X_v3.03.docx", "overridden": 327, "by_source": {"sds": 300, "module_inherit": 27}, "agreed": 12}

    def test_zero_overrides_and_legacy_stats_without_the_key_are_quiet(self):
        """구판 gen_stats(키 없음)와 덮은 게 0건인 run 은 항목을 만들지 않는다."""
        c = IssueCollector()
        U._note_docx_outcome(c, {"reference_suds": {"configured": True, "identity": {"same_project": True}, "safety_fields_overridden": {}}})
        U._note_docx_outcome(c, {"reference_suds": {"configured": True, "identity": {"same_project": True}}})
        U._note_docx_outcome(c, {"reference_suds": {"configured": True, "identity": {"same_project": True}, "safety_fields_overridden": {"sds": 0}}})
        assert _codes(c) == []


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


class TestSdsPartitionMapWiredBelowReference:
    """(R49 N38 → R50) SwDS 파티션 맵을 이 경로의 소스 분석에 **넘긴다** — 단, 정본이 그 값을 덮는 빌더 규칙과 한 세트다.

    R49 라이브 run 2079 에서 같은 배선이 정본 SwUDS 의 ASIL 657건을 35건으로 밀어(ASIL 변경 327 중 A→QM 45) 봉인했었다. R50 이 빌더의 정본
    채움을 "빈칸만" 에서 "`comment`·`uds`·자기 자신 빼고 덮기" 로 바꿔(`provenance.reference_suds_may_override`,
    `tests/unit/test_uds_reference_precedence.py`) 봉인을 풀었다. 배선만 있고 빌더 규칙이 없으면 run 2079 가 재현된다 —
    그래서 이 테스트는 배선과 함께 빌더 술어의 존재도 본다.
    """

    @staticmethod
    def _calls(tree, name):
        import ast
        return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "id", getattr(n.func, "attr", "")) == name]

    def test_source_sections_call_passes_the_partition_map(self):
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(source_of(U._uds_generate_from_paths)))
        calls = self._calls(tree, "generate_uds_source_sections")
        assert calls, "소스 분석 호출을 못 찾았다 — 선택자가 낡았다"
        for call in calls:
            kws = {k.arg for k in call.keywords}
            assert "sds_partition_map" in kws, "SwDS 파티션 맵이 이 경로에 배선돼 있지 않다 — 요구 문서를 읽어도 문서가 같다(run 2078)"

    def test_partition_map_is_built_from_materialized_docx_paths_only(self):
        """`_extract_sds_partition_map` 은 `req_doc_paths`(실체화 사본) 루프 변수로만 부른다 — 원경로(`req_paths`)면 N37 재발."""
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(source_of(U._uds_generate_from_paths)))
        calls = self._calls(tree, "_extract_sds_partition_map")
        assert calls, "파티션 맵 추출 호출이 없다"
        loops = {id(n): n for n in ast.walk(tree) if isinstance(n, ast.For)}
        for call in calls:
            arg = call.args[0]
            assert isinstance(arg, ast.Name), "루프 변수를 그대로 넘겨야 한다(가공하면 어느 목록에서 왔는지 가드가 못 본다)"
            owners = [lp for lp in loops.values() if isinstance(lp.target, ast.Name) and lp.target.id == arg.id]
            assert owners, f"{arg.id} 를 도는 for 루프가 없다"
            for lp in owners:
                assert isinstance(lp.iter, ast.Name) and lp.iter.id == "req_doc_paths", (
                    f"파티션 맵은 실체화 사본 목록(req_doc_paths)만 돌아야 한다 — 지금은 {ast.dump(lp.iter)[:60]}")

    def test_partition_map_failure_facts_carry_the_filename_only(self):
        """실패 항목의 facts 는 파일명만 — 절대 경로는 Gemini 프롬프트·화면에 실린다(R49 리뷰 W1 과 같은 규칙)."""
        src = source_of(U._uds_generate_from_paths)
        assert '"sds_partition_map_failed"' in src
        assert 'facts={"path": Path(_sds_doc).name, "error": type(exc).__name__}' in src

    def test_empty_partition_map_with_docs_present_becomes_an_item(self):
        """(리뷰 W2) 배선했는데 맵이 비면 R49 의 "읽었는데 문서가 같다" 와 같은 모습 — 건수 로그 + 문서가 있을 때만 항목."""
        src = source_of(U._uds_generate_from_paths)
        assert "if req_doc_paths and not _sds_pmap:" in src
        assert '_issues.add("sds_partition_map_empty", "warning", "potential",' in src
        assert '"[UDS] SwDS 파티션 맵 %d건 (SwDS 후보 %d / 요구 문서 %d)"' in src

    def test_builder_precedence_predicate_is_in_place(self):
        """배선의 안전 전제 — 빌더가 `reference_suds_may_override` 로 정본 우선을 강제한다(둘 중 하나만 있으면 안 된다)."""
        from report_gen import docx_builder, provenance
        assert provenance.reference_suds_may_override("sds") is True
        assert "reference_suds_may_override(_prev_src)" in source_of(docx_builder.generate_uds_docx)


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


class TestReferenceMatchingOutcome:
    """(R51 N40) 정본 매칭 계수 → 항목. 중복 이름(정본 품질)은 warning/actual, ID 번호 불일치는 risk/potential."""

    _REF = {"configured": True, "document": "X_v3.03.docx", "identity": {"same_project": True},
            "safety_fields_overridden": {}}

    def test_ambiguous_names_become_a_warning_with_the_sample(self):
        c = IssueCollector()
        sample = [{"name": "main", "id": "SwUFn_0130", "blocks": [{"id": "SwUFn_0101", "asil": "A", "related": "SwCom_01"},
                                                                  {"id": "SwUFn_3563", "asil": "QM", "related": "SwCom_35"}]}]
        U._note_docx_outcome(c, {"reference_suds": {**self._REF, "matching": {"ambiguous_names": 1, "ambiguous_sample": sample,
                                                                               "id_collision_blocks": 0}}})
        items = {i["code"]: i for i in c.as_list()}
        assert list(items) == ["reference_ambiguous_function_name"]
        it = items["reference_ambiguous_function_name"]
        assert (it["severity"], it["kind"]) == ("warning", "actual")
        assert "1개 함수" in it["message"] and "main" in it["message"]
        assert it["facts"] == {"document": "X_v3.03.docx", "ambiguous_names": 1, "sample": sample}

    def test_id_collisions_become_a_risk_with_the_matching_counts(self):
        c = IssueCollector()
        U._note_docx_outcome(c, {"reference_suds": {**self._REF, "matching": {
            "ambiguous_names": 0, "id_collision_blocks": 773, "by_name": 896, "by_name_and_id": 46, "unmatched_blocks": 37}}})
        items = {i["code"]: i for i in c.as_list()}
        assert list(items) == ["reference_id_numbering_differs"]
        it = items["reference_id_numbering_differs"]
        assert (it["severity"], it["kind"]) == ("risk", "potential")
        assert "773개" in it["message"] and "이름 896" in it["message"] and "이름+ID 46" in it["message"]
        assert it["facts"] == {"id_collision_blocks": 773, "by_name": 896, "by_name_and_id": 46, "unmatched_blocks": 37}

    @pytest.mark.parametrize("matching", [None, {}, {"ambiguous_names": 0, "id_collision_blocks": 0},
                                          {"ambiguous_names": True, "id_collision_blocks": "3"}])
    def test_legacy_or_zero_matching_is_quiet(self, matching):
        """구판 gen_stats(키 없음)·0건·정수가 아닌 값은 항목을 만들지 않는다."""
        c = IssueCollector()
        ref = dict(self._REF)
        if matching is not None:
            ref["matching"] = matching
        U._note_docx_outcome(c, {"reference_suds": ref})
        assert c.as_list() == []

    def test_explainer_knows_both_codes(self):
        from backend.services import issue_explainer as IE
        assert IE._RULE_ACTION["reference_ambiguous_function_name"] and IE._RULE_ACTION["reference_id_numbering_differs"]

    def test_builder_matches_reference_blocks_by_name(self):
        """계수의 원천 — 빌더 루프가 `_resolve_reference_target` 을 타고, 옛 `function_details.get(fid)` 우선 매칭이 없다."""
        import re

        from report_gen import docx_builder as DB
        src = source_of(DB.generate_uds_docx)
        assert "_resolve_reference_target(" in src
        assert not re.search(r"target = function_details\.get\(fid\)", src), "정본 블록을 ID 로 먼저 찾는 옛 규칙이 되살아났다"
