# tests/unit/test_uds_docx_writeback.py
"""UDS DOCX 검증이 **입력 대비** 대조를 하지 않던 것.

## 회귀 대상 (2026-07-29 실측)

`validate_uds_docx_structure` 는 문서 **내부 정합성**만 봤다 — heading 수 ↔ FunctionInfo
표 수, logic 행 ↔ 이미지 수. "몇 개가 들어와야 했는가" 를 모르므로 양방향 불일치가
통째로 침묵했다:

    payload 함수 1개든 100개든 → 문서는 항상 SwUFn 섹션 429개, ok=True, issues 0건

DOCX 는 XLSM 라이터와 달리 **템플릿 주도**다(이미 있는 SwUFn heading 을 함수명으로 매칭해
채운다). 실 데이터(소스 900 / 템플릿 함수명 421, 빌더 정규화 기준 교집합 271):

    · 문서에 못 실리는 소스 함수  629개 (69.9%)  ← 조용히 누락
    · 데이터 없는 템플릿 heading  150개          ← 빈 함수 명세로 출력

⚠ `ok` 판정은 **바꾸지 않는다**. 템플릿이 부분집합을 담는 게 의도일 수 있어 이걸 실패로
만들면 정상 산출물이 대량 오탐된다. 대신 수치를 `warnings` 로 드러내
"ok=True 니까 다 들어갔다" 는 오독을 막는다.
"""
from __future__ import annotations

import json

import pytest

from report_gen.validation import (
    _docx_heading_function_names,
    _norm_fn_key,
    _payload_function_names,
    validate_uds_docx_structure,
)


class _Style:
    def __init__(self, name):
        self.name = name


class _Para:
    def __init__(self, text, style="Heading 3"):
        self.text = text
        self.style = _Style(style)


class _Doc:
    def __init__(self, paras):
        self.paragraphs = paras


# ---------------------------------------------------------------------------
# 함수명 키 — 빌더와 같은 정규화를 써야 한다
# ---------------------------------------------------------------------------

class TestNameKeyMatchesBuilder:
    def test_case_difference_is_absorbed(self):
        """실측: 템플릿 `ADC0_Stop_current_workaround` vs 소스 `ADC0_stop_...`.

        검증기가 자체 정규화를 만들면 빌더는 매칭했는데 검증기는 '누락' 이라 한다
        (정확일치 교집합 211 vs 빌더 정규화 271 — 60건 차이).
        """
        assert _norm_fn_key("ADC0_Stop_current_workaround") == _norm_fn_key("ADC0_stop_current_workaround")

    @pytest.mark.parametrize("bad", [None, "", "   "])
    def test_blank_names_produce_blank_key(self, bad):
        assert _norm_fn_key(bad) == ""


class TestDocxHeadingExtraction:
    def test_swufn_headings_are_picked_up(self):
        doc = _Doc([_Para("SwUFn_0101: main"), _Para("SwUFn_0102: BATS_Init")])
        assert _docx_heading_function_names(doc) == {_norm_fn_key("main"), _norm_fn_key("BATS_Init")}

    def test_non_heading_paragraphs_are_ignored(self):
        doc = _Doc([_Para("SwUFn_0101: main", style="Normal")])
        assert _docx_heading_function_names(doc) == set()

    def test_heading_without_swufn_is_ignored(self):
        doc = _Doc([_Para("2. Interface Functions")])
        assert _docx_heading_function_names(doc) == set()


class TestPayloadSidecarReading:
    def test_names_are_extracted(self, tmp_path):
        p = tmp_path / "u.payload.json"
        p.write_text(json.dumps({"function_details": {
            "F1": {"name": "main"}, "F2": {"name": "BATS_Init"}}}), encoding="utf-8")
        names, err = _payload_function_names(p)
        assert err == ""
        assert names == {_norm_fn_key("main"), _norm_fn_key("BATS_Init")}

    def test_unreadable_sidecar_reports_reason(self, tmp_path):
        p = tmp_path / "u.payload.json"
        p.write_text("{ not json", encoding="utf-8")
        names, err = _payload_function_names(p)
        assert names == set() and err

    def test_wrong_shape_reports_reason(self, tmp_path):
        p = tmp_path / "u.payload.json"
        p.write_text(json.dumps({"function_details": [1, 2]}), encoding="utf-8")
        _, err = _payload_function_names(p)
        assert "dict" in err

    def test_blank_names_are_dropped(self, tmp_path):
        p = tmp_path / "u.payload.json"
        p.write_text(json.dumps({"function_details": {
            "F1": {"name": ""}, "F2": {"name": "  "}, "F3": {"name": "main"}}}), encoding="utf-8")
        names, _ = _payload_function_names(p)
        assert names == {_norm_fn_key("main")}


# ---------------------------------------------------------------------------
# 검증기 통합 — 실제 docx 를 만들어 확인
# ---------------------------------------------------------------------------

def _make_docx(path, fn_names):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    for i, nm in enumerate(fn_names, start=1):
        d.add_heading(f"SwUFn_{i:04d}: {nm}", level=3)
        t = d.add_table(rows=1, cols=3)
        t.rows[0].cells[0].text = "Function Information"
    d.save(str(path))


class TestInputComparison:
    def test_missing_sidecar_is_not_a_pass(self, tmp_path):
        """대조를 **못 한** 것과 '대조하고 깨끗함' 은 달라야 한다."""
        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main"])
        v = validate_uds_docx_structure(str(doc))
        assert v["expected_functions"] is None
        assert any("대조 불가" in w for w in v["warnings"])

    def test_dropped_source_functions_are_reported(self, tmp_path):
        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main"])
        doc.with_suffix(".payload.json").write_text(json.dumps({"function_details": {
            "F1": {"name": "main"}, "F2": {"name": "BATS_Init"}, "F3": {"name": "Gone_Fn"}}}),
            encoding="utf-8")
        v = validate_uds_docx_structure(str(doc))
        assert v["expected_functions"] == 3
        assert v["matched_functions"] == 1
        assert len(v["payload_functions_missing_from_docx"]) == 2
        assert any("문서에 없다" in w for w in v["warnings"])

    def test_empty_template_headings_are_reported(self, tmp_path):
        """데이터 없는 heading 은 **빈 함수 명세**로 나간다 — 침묵하면 안 된다."""
        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main", "Ghost_A", "Ghost_B"])
        doc.with_suffix(".payload.json").write_text(
            json.dumps({"function_details": {"F1": {"name": "main"}}}), encoding="utf-8")
        v = validate_uds_docx_structure(str(doc))
        assert len(v["docx_headings_without_payload"]) == 2
        assert any("빈 함수 명세" in w for w in v["warnings"])

    def test_counts_are_not_derived_from_the_truncated_list(self, tmp_path):
        """예시 리스트는 50개까지만 담는다 — 그 길이를 개수로 되짚으면 안 된다.

        실측에서 실제로 났다: 경고엔 `629개` 인데 요약 줄은 `50건 이상` 이었다.
        (이 저장소가 반복해 겪은 함정 — 절단을 소비처에서 길이로 되짚지 말 것)
        """
        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main"])
        many = {f"F{i}": {"name": f"Fn_{i:04d}"} for i in range(120)}
        many["KEEP"] = {"name": "main"}
        doc.with_suffix(".payload.json").write_text(
            json.dumps({"function_details": many}), encoding="utf-8")
        v = validate_uds_docx_structure(str(doc))
        assert v["missing_from_docx_count"] == 120
        assert len(v["payload_functions_missing_from_docx"]) == 50   # 예시는 절단
        assert "120" in " ".join(v["warnings"])

    def test_report_uses_the_untruncated_count(self, tmp_path):
        from report_gen.validation import generate_uds_validation_report

        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main"])
        many = {f"F{i}": {"name": f"Fn_{i:04d}"} for i in range(120)}
        many["KEEP"] = {"name": "main"}
        doc.with_suffix(".payload.json").write_text(
            json.dumps({"function_details": many}), encoding="utf-8")
        rep = tmp_path / "v.md"
        generate_uds_validation_report(str(doc), str(rep))
        txt = rep.read_text(encoding="utf-8")
        # ⚠ 여기서 재는 것은 **개수**(절단 전 120)이지 서식이 아니다. 예전엔
        #   `` `120건` `` 리터럴을 단언해서, 단위를 backtick 밖으로 옮기자 의미가
        #   그대로인데 죽었다. 철자를 재는 가드는 사실이 바뀔 때가 아니라 표기가
        #   바뀔 때 운다 — 값은 리더가 실제로 뽑아 오는 경로로 확인한다.
        from report_gen.evidence import read_docx_validation

        assert read_docx_validation(rep)["missing_from_docx"] == 120, txt
        assert "50건" not in txt, "절단된 리스트 길이를 개수로 썼다"
        assert "`50`" not in txt, "절단된 리스트 길이를 개수로 썼다"

    def test_perfect_match_has_no_input_warning(self, tmp_path):
        """대조군 — 다 맞으면 경고가 없어야 한다(경고 남발 방지)."""
        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main", "BATS_Init"])
        doc.with_suffix(".payload.json").write_text(json.dumps({"function_details": {
            "F1": {"name": "main"}, "F2": {"name": "BATS_Init"}}}), encoding="utf-8")
        v = validate_uds_docx_structure(str(doc))
        assert v["expected_functions"] == v["matched_functions"] == 2
        assert v["warnings"] == []

    def test_ok_verdict_is_not_flipped(self, tmp_path):
        """`ok` 는 내부 정합성만 본다 — 템플릿 부분집합을 실패로 만들면 대량 오탐."""
        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main"])
        doc.with_suffix(".payload.json").write_text(json.dumps({"function_details": {
            "F1": {"name": "main"}, "F2": {"name": "Gone"}}}), encoding="utf-8")
        v = validate_uds_docx_structure(str(doc))
        assert v["warnings"], "경고는 나야 한다"
        assert v["ok"] is True, "내부 정합성은 멀쩡한데 ok 를 뒤집었다"


class TestReportShowsTheComparison:
    """요약 dict 에만 담고 리포트가 안 쓰면 독자는 여전히 못 본다."""

    def test_markdown_contains_counts_and_warnings(self, tmp_path):
        from report_gen.validation import generate_uds_validation_report

        doc = tmp_path / "u.docx"
        _make_docx(doc, ["main"])
        doc.with_suffix(".payload.json").write_text(json.dumps({"function_details": {
            "F1": {"name": "main"}, "F2": {"name": "Gone_Fn"}}}), encoding="utf-8")
        rep = tmp_path / "v.md"
        generate_uds_validation_report(str(doc), str(rep))
        txt = rep.read_text(encoding="utf-8")
        assert "Payload 함수 수" in txt
        assert "Warnings" in txt
        assert "Gone_Fn" in txt.lower() or "gone_fn" in txt.lower()
