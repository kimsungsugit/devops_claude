"""SwCom 정본 diff — **개수만 보던 것**을 이름·값까지 넓힌 뒤의 가드.

## 왜 개수로는 부족한가

`generate_swcom_context_diff_report` 는 저장소에서 유일한 정본↔생성물 직접 diff 인데
행 **수**만 셌다. 그러면 두 가지가 통째로 안 보인다:

1. 개수가 같은데 **다른 변수**를 적고 있는 경우 — diff 가 `none` 이라 적는다.
2. 같은 변수인데 **Type/Value Range 가 다른** 경우 — 행 수는 그대로다.

⚠ 값 판정은 `uds_reference_parity.value_verdict` **단일 출처**를 쓴다. 여기에 두 번째
정의를 두면 한쪽만 고쳐져 갈린다 — 이 저장소가 반복해 겪은 판정 복제 패턴이다.
표기차(`0x00 ~ 0xFF` = `0 ~ 255`)를 불일치로 세면 지표가 거짓으로 나빠진다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from report_gen.validation import generate_swcom_context_diff_report
from tests.unit._source_probe import source_of

docx = pytest.importorskip("docx", reason="python-docx 없이는 이 리포트를 만들 수 없다")

_HEADER = ["Name", "Type", "Value Range", "Reset Value", "Description"]


def _write(path: Path, sections):
    """`sections` = [(SwCom 이름, 'Global variables'|'Static Variables', [행...])]"""
    doc = docx.Document()
    for swcom, heading, rows in sections:
        doc.add_paragraph(swcom)
        doc.add_paragraph(heading)
        table = doc.add_table(rows=1 + len(rows), cols=5)
        for c, text in enumerate(_HEADER):
            table.rows[0].cells[c].text = text
        for r, row in enumerate(rows, start=1):
            for c, text in enumerate(row):
                table.rows[r].cells[c].text = str(text)
    doc.save(str(path))
    return str(path)


def _report(tmp_path, ref_sections, tgt_sections) -> str:
    ref = _write(tmp_path / "ref.docx", ref_sections)
    tgt = _write(tmp_path / "tgt.docx", tgt_sections)
    out = generate_swcom_context_diff_report(ref, tgt, str(tmp_path / "diff.md"))
    return Path(out).read_text(encoding="utf-8")


_ROW_A = ["u8g_A", "U8", "0x00 ~ 0x01", "0x00", "Flag A"]
_ROW_B = ["u8g_B", "U8", "0x00 ~ 0x01", "0x00", "Flag B"]


class TestRowCountsStillWork:
    def test_identical_documents_report_no_count_difference(self, tmp_path):
        """음성 대조군 — 완전 일치가 diff 를 내면 지표를 못 믿는다."""
        spec = [("SwCom_01", "Global variables", [_ROW_A])]
        text = _report(tmp_path, spec, spec)
        assert "## Row Count Differences" in text
        body = text.split("## Row Count Differences")[1].split("##")[0]
        assert "- none" in body

    def test_a_count_difference_is_still_reported(self, tmp_path):
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A, _ROW_B])],
            [("SwCom_01", "Global variables", [_ROW_A])],
        )
        assert "SwCom_01: global `2` -> `1`" in text


class TestNameAxis:
    def test_same_count_different_names_is_caught(self, tmp_path):
        """⚠ 개수 diff 만 보던 시절엔 이게 `none` 이었다."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A])],
            [("SwCom_01", "Global variables", [_ROW_B])],
        )
        count_body = text.split("## Row Count Differences")[1].split("##")[0]
        assert "- none" in count_body, "개수는 같아야 이 시험의 뜻이 산다"
        assert "only in reference (`1`)" in text
        assert "u8g_A" in text.split("## Name Sets")[1]

    def test_recall_is_reported(self, tmp_path):
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A, _ROW_B])],
            [("SwCom_01", "Global variables", [_ROW_A])],
        )
        assert "matched `1` · recall `50.0%`" in text

    def test_empty_reference_section_is_unmeasured_not_zero(self, tmp_path):
        """분모 0 을 0.0% 로 적으면 재본 적 없는 축이 최악값으로 둔갑한다."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A])],
            [("SwCom_01", "Global variables", [_ROW_A])],
        )
        assert "static: reference `0`" in text
        assert "recall `미측정(정본 0행)`" in text

    def test_target_only_names_are_not_called_defects(self, tmp_path):
        """결정 3 — 정본은 하한선이지 상한선이 아니다."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A])],
            [("SwCom_01", "Global variables", [_ROW_A, _ROW_B])],
        )
        assert "only in target (`1`, 정본은 하한선이므로 결함 아님)" in text

    def test_placeholder_names_are_not_counted(self, tmp_path):
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A, ["N/A", "", "", "", ""]])],
            [("SwCom_01", "Global variables", [_ROW_A])],
        )
        assert "reference `1` · target `1` · matched `1`" in text


class TestValueAxis:
    def test_notation_difference_counts_as_reproduced(self, tmp_path):
        """⚠ 표기차를 불일치로 세면 range 재현율이 거짓으로 0% 가 된다(SUTS R26)."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", ["u8g_A U8 0x00~0xFF 0x00 Flag".split()])],
            [("SwCom_01", "Global variables",
              [["u8g_A", "U8", "0 ~ 255 (타입 폭)", "0x00", "Flag"]])],
        )
        line = [x for x in text.splitlines() if x.startswith("- global/range:")][0]
        assert "reproduced `1` (100.0%)" in line and "notation `1`" in line

    def test_a_narrower_design_range_is_a_real_mismatch(self, tmp_path):
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables",
              [["u8g_A", "U8", "0x00 ~ 0x03", "0x00", "Flag"]])],
            [("SwCom_01", "Global variables",
              [["u8g_A", "U8", "0 ~ 255 (타입 폭)", "0x00", "Flag"]])],
        )
        line = [x for x in text.splitlines() if x.startswith("- global/range:")][0]
        assert "mismatch `1`" in line
        assert "ref `0x00 ~ 0x03` -> `0 ~ 255 (타입 폭)`" in text

    def test_our_na_is_missing_not_mismatch(self, tmp_path):
        """'적을 게 없었다' 와 '틀리게 적었다' 는 대응이 다르다."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A])],
            [("SwCom_01", "Global variables", [["u8g_A", "U8", "N/A", "0x00", "Flag A"]])],
        )
        line = [x for x in text.splitlines() if x.startswith("- global/range:")][0]
        assert "missing `1`" in line and "mismatch `0`" in line

    def test_reference_na_is_excluded_from_the_denominator(self, tmp_path):
        """정본이 '근거 없음' 이라 적은 칸을 재현 대상으로 세면 우리 근거를 지워야 오른다."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [["u8g_A", "U8", "N/A", "0x00", "Flag A"]])],
            [("SwCom_01", "Global variables", [_ROW_A])],
        )
        line = [x for x in text.splitlines() if x.startswith("- global/range:")][0]
        assert "denominator `0`" in line and "미측정(분모 0)" in line

    def test_value_axis_only_looks_at_matched_names(self, tmp_path):
        """이름이 없으면 값을 비교할 수 없다 — 이름 축 결손을 값 축에 겹쳐 세면 안 된다."""
        text = _report(
            tmp_path,
            [("SwCom_01", "Global variables", [_ROW_A, _ROW_B])],
            [("SwCom_01", "Global variables", [_ROW_A])],
        )
        line = [x for x in text.splitlines() if x.startswith("- global/type:")][0]
        assert "denominator `1`" in line


class TestVerdictIsASingleSource:
    def test_module_delegates_to_the_parity_comparator(self):
        """두 번째 정의를 두면 한쪽만 고쳐져 갈린다."""
        from report_gen import validation

        body = source_of(validation._value_verdict)
        assert "from report_gen.uds_reference_parity import value_verdict" in body
        assert "return value_verdict(column, ref_value, our_value)" in body

    def test_fallback_says_it_lost_normalisation(self, monkeypatch):
        """모듈을 못 읽으면 조용히 열화하지 말고 사유를 결과에 남긴다."""
        import builtins

        from report_gen import validation

        real = builtins.__import__

        def _boom(name, *a, **k):
            if name == "report_gen.uds_reference_parity":
                raise ImportError("simulated")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _boom)
        same, reason = validation._value_verdict("range", "0x00 ~ 0xFF", "0 ~ 255")
        assert same is False and "표기 정규화 없음" in reason
