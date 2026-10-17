"""R30 — Q-2 payload 배선: 품질 게이트가 자기 산출물을 되읽지 않게 (계획서 §2.2 Q-2).

실측(2026-09-04)이 계획 전제를 두 번 뒤집었다:

  1. 후보 파일명 `*.payload.full.json` 의 **라이터가 코드에 없다**(디스크 33개는 옛 하네스 산출물). 실 라이터
     5곳은 `*.payload.json` → 게이트는 payload 를 한 번도 못 읽고 DOCX 를 되읽어 채점했다. 그 경로에서
     DOCX 추출기가 설명에 `reference`(정본에서 읽음 = 신뢰 출처)를 붙여 **High 가 "비어 있지 않음" 과 동의어**였다.
  2. payload 함수 집합 ≠ 문서 항목 집합이다(실측 5/429 · 335/418 · 469/426). 429항목 문서의 payload 5개는
     **문서에 하나도 없었다**(템플릿 heading 미매칭). payload 전체를 채점하면 문서와 무관한 점수, 문서 전체를
     채점하면 생성되지 않은 stub 419개가 분모를 끌어내린다 → **문서 ∩ payload** 를 채점하고 양쪽 차집합을 head 에.

원칙: 되읽은 설명의 출처는 `generated_doc`(약한 출처) · 잰 집합이 문서 전체가 아니면 그 수를 숨기지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.unit.test_quality_gate_r29 import _doc_per_fn, _fn, _metric_line, _run, _section

pytest.importorskip("docx")

LONG = "이 함수는 센서 원시값을 읽어 보정 계수를 곱한 뒤 전역 버퍼에 저장하고 상태를 갱신한다"


def _payload(tmp: Path, name: str, funcs: List[Dict[str, Any]]) -> Path:
    p = tmp / name
    p.write_text(json.dumps({"docx_path": "x", "summary": {},
                             "function_details": {f"SwUFn_{i:04d}": f for i, f in enumerate(funcs, 1)}},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _pf(name: str, **over: Any) -> Dict[str, Any]:
    base = {"name": name, "prototype": f"int {name}(int a, int *out)", "description": LONG,
            "description_source": "comment", "asil": "B", "related": "SwFn_001",
            "inputs": ["a"], "outputs": ["out"], "calls_list": ["helper"], "calling": ["main"],
            "globals_global": ["G"], "globals_static": ["S"]}
    base.update(over)
    return base


# ==============================================================
# 1. 실 라이터의 이름을 읽는다
# ==============================================================

class TestPayloadJsonIsLoaded:

    def test_payload_json_is_a_candidate_and_named_in_the_head(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Payload: `u.payload.json` · functions `1`" in text
        assert got["payload_present"] is True and got["payload_file"] == "u.payload.json"

    def test_current_writer_wins_over_legacy_snapshot(self, tmp_path):
        """리뷰 C2: legacy `*.payload.full.json` 은 DOCX **이전** 스냅샷이고 `.payload.json` 은 DOCX 직후에 쓰인다
        (실측 mtime full 09:52:05 → docx 10:03:25 → json 10:03:26, 8쌍 중 1쌍은 globals_static 36함수가 다르다).
        legacy 를 먼저 고르면 문서를 만든 값이 아닌 것으로 채점한다."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        _payload(tmp_path, "u.docx.payload.full.json", [_pf("fn_1", description_source="sds")])
        text, _ = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Payload: `u.payload.json`" in text

    def test_legacy_name_is_still_read_when_it_is_the_only_one(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        _payload(tmp_path, "u.docx.payload.full.json", [_pf("fn_1")])
        text, _ = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Payload: `u.docx.payload.full.json`" in text

    def test_only_candidate_broken_is_reported_as_read_error_not_absence(self, tmp_path):
        """리뷰 W1: "없음" 과 "있는데 못 읽음" 은 다르다 — 후자를 없음으로 내면 채점 모드가 조용히 바뀐다."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        (tmp_path / "u.payload.json").write_text('{"function_details": {"SwUFn_0001": {"name": "fn_1"', encoding="utf-8")
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Payload: `none` — 읽기 실패 `u.payload.json: JSONDecodeError" in text
        assert got["payload_present"] is False
        assert got["payload_read_error"] and got["payload_read_error"].startswith("u.payload.json: JSONDecodeError")
        assert "- Scored fields source: `document`" in text

    def test_payload_with_zero_functions_is_its_own_state(self, tmp_path):
        """리뷰 C1: 라이터(`local.py`/`jenkins.py`)는 빈 dict 도 쓴다 — "읽었는데 함수 0" 이 자기 대조로 떨어지면서
        head 는 payload 를 읽었다고 광고하고 차집합에 `None` 이 찍혔다."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)", desc=LONG)])
        _payload(tmp_path, "u.payload.json", [])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert "None" not in text
        assert "- Payload: `u.payload.json` · functions `0` (함수 0개 — 생성 결과가 비어 있어 교집합 0)" in text
        assert "- Total functions: `0`" in text
        assert got["entries_not_in_payload"] == {"count": 1, "total": 1}
        assert got["payload_not_in_document"] == {"count": 0, "total": 0}
        assert "- Gate pass: `False`" in text

    def test_compat_wrapper_returns_the_dict(self, tmp_path):
        from report_gen.validation import _load_uds_payload_for_docx, _load_uds_payload_with_source

        (tmp_path / "t.docx").write_text("dummy")
        _payload(tmp_path, "t.payload.json", [_pf("fn_1")])
        data, src = _load_uds_payload_with_source(str(tmp_path / "t.docx"))
        assert src is not None and src.name == "t.payload.json"
        assert _load_uds_payload_for_docx(str(tmp_path / "t.docx")) == data
        assert _load_uds_payload_with_source(str(tmp_path / "none.docx")) == ({}, None)

    def test_broken_payload_falls_through_to_next_candidate(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        (tmp_path / "u.docx.payload.full.json").write_text("{not json", encoding="utf-8")
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        text, _ = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Payload: `u.payload.json`" in text


# ==============================================================
# 2. 채점 집합 = 문서 ∩ payload
# ==============================================================

class TestScoredSetIsTheIntersection:

    def test_payload_functions_missing_from_the_document_are_not_scored(self, tmp_path):
        """실측 5/429: payload 5개가 문서에 0개 — 그 5개로 채점하면 문서와 무관한 점수다."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)"), _fn("void fn_2(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("other_a"), _pf("other_b"), _pf("other_c")])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Total functions: `0`" in text
        assert got["document_entries"] == 2
        assert got["entries_not_in_payload"] == {"count": 2, "total": 2}
        assert got["payload_not_in_document"] == {"count": 3, "total": 3}
        assert "- Gate pass: `False`" in text
        assert "모두 통과" not in text

    def test_document_stubs_not_in_payload_are_outside_the_denominator_but_counted(self, tmp_path):
        """생성되지 않은 템플릿 stub 은 필드 품질이 아니라 문서 커버리지의 축이다 — 분모 밖, 수는 head 에."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)"), _fn("void fn_2(void)"), _fn("void fn_3(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Total functions: `1`" in text
        assert got["entries_not_in_payload"] == {"count": 2, "total": 3}
        assert got["payload_not_in_document"] == {"count": 0, "total": 1}
        assert "문서 항목 2개는 payload 에 없어" in text
        assert "`1` / `1`" in _metric_line(text, "Description fill")
        # 커버리지는 판정 밖이지만 head·리더·산문에 있다 — 재채점 실측: 426항목 중 18개 채점 문서가 True 가 됐다
        assert "- Scored entries: `1` / `3` — 문서 커버리지 33.3%, 판정 밖" in text
        assert got["scored_entries"] == {"count": 1, "total": 3}
        assert "- Scored fields source: `payload`" in text

    def test_head_ratio_lines_are_not_parsed_as_metrics(self, tmp_path):
        """리뷰 W2: 라벨·backtick 비율·괄호 조합은 지표 포맷이다 — head 줄에 괄호를 쓰면 파서가 지표로 잡는다."""
        from report_gen.gate_report import parse_gate_report, to_rate_map

        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)"), _fn("void fn_2(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        text, _ = _run(d, tmp_path / "p.quality_gate.md")
        parsed = parse_gate_report(text)
        assert not {k for k in parsed["metrics"] if k.startswith(("scored", "document", "payload", "distinct", "prototype"))}
        assert set(to_rate_map(parsed)) <= {"description_fill", "input_fill", "output_fill", "globals_global_fill",
                                            "globals_static_fill", "called_fill", "calling_fill"}

    def test_duplicate_names_are_counted_as_rows_and_distinct_functions(self, tmp_path):
        """리뷰 W3: 같은 함수명이 세 SwUFn 에 있으면 한 payload 행이 세 번 채점된다 — 행 수 ≠ 함수 수."""
        rows = _fn("void main(void)")
        rows = [("Name", "main") if k == "Name" else (k, v) for k, v in rows]
        d = _doc_per_fn(tmp_path, [rows, rows, rows])
        _payload(tmp_path, "u.payload.json", [_pf("main")])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert "- Total functions: `3`" in text
        assert "- Distinct scored functions: `1`" in text
        assert got["distinct_scored_functions"] == 1

    def test_none_marker_interfaces_are_counted_but_noted(self, tmp_path):
        """리뷰 I4: `["[OUT] (none)"]` 는 채움으로 센다(evaluator 규약) — 사이드카엔 _real 동반축이 없으니 note 로."""
        d = _doc_per_fn(tmp_path, [_fn("int fn_1(int a, int *o)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1", inputs=["[IN] (none)"], outputs=["[OUT] (none)"])])
        text, _ = _run(d, tmp_path / "p.quality_gate.md")
        assert "`1` / `1`" in _metric_line(text, "Output fill")
        assert '"(none)" 표기(파라미터 없음) — 입력 1개 · 출력 1개' in text

    def test_none_marker_helper(self):
        from report_gen.validation import _is_none_marker_list

        assert _is_none_marker_list(["[IN] (none)"]) and _is_none_marker_list("N/A") and _is_none_marker_list(["-", "none"])
        assert not _is_none_marker_list(["[IN] a", "[IN] (none)"]) and not _is_none_marker_list([]) and not _is_none_marker_list("a")

    def test_pass_prose_names_the_uncovered_entries(self, tmp_path):
        """"모두 통과" 가 무엇에 대한 통과인지 — 생성되지 않은 항목 수를 같은 문장에 둔다."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)"), _fn("void fn_2(void)"), _fn("void fn_3(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        zero = {k: 0.0 for k in ("description_fill_rate", "input_fill_rate", "output_fill_rate",
                                 "globals_global_fill_rate", "globals_static_fill_rate", "called_fill_rate",
                                 "calling_fill_rate", "asil_non_tbd_rate", "related_non_tbd_rate", "traceability_rate")}
        text, got = _run(d, tmp_path / "p.quality_gate.md", thresholds=zero)
        assert "- Gate pass: `True`" in text
        assert "3개 중 2개는 생성되지 않아 채점 밖입니다" in text
        assert "문서 커버리지 33.3%" in text
        assert "None" not in text

    def test_pass_prose_without_stubs_has_no_caveat(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        zero = {k: 0.0 for k in ("description_fill_rate", "input_fill_rate", "output_fill_rate",
                                 "globals_global_fill_rate", "globals_static_fill_rate", "called_fill_rate",
                                 "calling_fill_rate", "asil_non_tbd_rate", "related_non_tbd_rate", "traceability_rate")}
        text, _ = _run(d, tmp_path / "p.quality_gate.md", thresholds=zero)
        assert "- 모든 품질 게이트를 통과했습니다. 정기적인 재검증을 권장합니다." in text
        assert "생성되지 않아" not in text

    def test_payload_fields_win_over_document_cells_when_present(self, tmp_path):
        """문서 Prototype 이 비어도 payload 의 prototype 으로 슬롯을 센다 — 미측정이 측정으로."""
        d = _doc_per_fn(tmp_path, [_fn("", inputs="", outputs="")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1")])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert got["unmeasured_count"] == 0
        assert "`1` / `1`" in _metric_line(text, "Input fill")
        assert "`1` / `1`" in _metric_line(text, "Output fill")
        assert got["prototype_unreadable"] == {"count": 0, "total": 1}

    def test_empty_payload_values_do_not_erase_document_cells(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("int fn_1(int a, int *o)", inputs="a", outputs="o")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1", prototype="", inputs=[], outputs=None)])
        text, _ = _run(d, tmp_path / "p.quality_gate.md")
        assert "`1` / `1`" in _metric_line(text, "Input fill")
        assert "`1` / `1`" in _metric_line(text, "Output fill")

    def test_merge_helper_contract(self):
        from report_gen.validation import _merge_payload_over_doc

        out = _merge_payload_over_doc({"a": "doc", "b": "doc", "c": ["doc"]},
                                      {"a": "", "b": "pay", "c": [], "d": None, "e": {"k": 1}})
        assert out == {"a": "doc", "b": "pay", "c": ["doc"], "e": {"k": 1}}


# ==============================================================
# 3. 출처 세탁 차단
# ==============================================================

class TestDescriptionSourceIsNotLaundered:

    def test_docx_fallback_never_yields_high(self, tmp_path):
        """되읽은 설명은 유래를 알 수 없다 — 예전엔 `reference` 가 붙어 전부 High 였다."""
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)", desc=LONG), _fn("void fn_2(void)", desc="짧다")])
        text, got = _run(d, tmp_path / "p.quality_gate.md")
        assert got["payload_present"] is False
        assert got["description_quality"]["high"]["count"] == 0
        assert got["description_quality"]["medium"]["count"] == 1     # 길면 medium
        assert got["description_quality"]["low"]["count"] == 1        # 짧으면 low
        assert "- Payload: `none` — 문서 자기 대조" in text
        assert "generated_doc" in "\n".join(_section(text, "Description Quality Grade"))

    def test_payload_sources_do_yield_high(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)", desc="짧다"), _fn("void fn_2(void)", desc="짧다")])
        _payload(tmp_path, "u.payload.json", [_pf("fn_1", description_source="comment"),
                                              _pf("fn_2", description_source="inference")])
        _, got = _run(d, tmp_path / "p.quality_gate.md")
        assert got["description_quality"]["high"]["count"] == 1
        assert got["description_quality"]["high"]["count"] + got["description_quality"]["medium"]["count"] \
            + got["description_quality"]["low"]["count"] == 2

    def test_reference_label_from_the_docx_extractor_is_ignored_in_fallback(self, tmp_path):
        """추출기의 `reference` 는 "정본에서 읽음" 이다 — 생성 산출물을 되읽은 경우엔 그 뜻이 아니다."""
        import docx

        from report_gen.requirements import _extract_function_info_from_docx

        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)", desc=LONG)])
        rows = list(_extract_function_info_from_docx(docx.Document(str(d))).values())
        assert rows and rows[0].get("description_source") == "reference"     # 추출기는 여전히 그렇게 붙인다
        _, got = _run(d, tmp_path / "p.quality_gate.md")
        assert got["description_quality"]["high"]["count"] == 0                # 게이트는 그 라벨을 믿지 않는다


# ==============================================================
# 4. 리더 — 구판은 None, 0 이 아니다
# ==============================================================

class TestReaderFields:

    def test_legacy_report_has_none_for_every_new_field(self, tmp_path):
        from report_gen.evidence import read_gate_report

        p = tmp_path / "old.quality_gate.md"
        p.write_text("# UDS Field Quality Gate Report\n\n- Total functions: `4`\n- Gate pass: `False`\n",
                     encoding="utf-8")
        got = read_gate_report(p)
        assert got["payload_present"] is None and got["payload_file"] is None
        assert got["document_entries"] is None and got["scored_entries"] is None
        assert got["payload_read_error"] is None and got["distinct_scored_functions"] is None
        assert got["entries_not_in_payload"] is None and got["payload_not_in_document"] is None

    def test_fallback_report_reads_present_false_not_none(self, tmp_path):
        d = _doc_per_fn(tmp_path, [_fn("void fn_1(void)")])
        _, got = _run(d, tmp_path / "p.quality_gate.md")
        assert got["payload_present"] is False
        assert got["document_entries"] == 1
        assert got["entries_not_in_payload"] is None          # payload 가 없으면 차집합은 정의되지 않는다
