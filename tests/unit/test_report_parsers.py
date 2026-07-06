"""Report Parser 단위 테스트"""
from pathlib import Path
import pytest

from backend.services.report_parsers import (
    _clean_text,
    _is_worstrules_header,
    _parse_number,
    build_report_summary,
    parse_html_report,
    parse_prqa_rcr_details,
    read_text_safe,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestCleanText:
    def test_basic(self):
        assert _clean_text("  hello   world  ") == "hello world"

    def test_none(self):
        assert _clean_text(None) == ""

    def test_newlines(self):
        assert _clean_text("a\n  b\n  c") == "a b c"


class TestParseNumber:
    def test_integer(self):
        assert _parse_number("42") == 42.0

    def test_float(self):
        assert _parse_number("3.14") == 3.14

    def test_percentage(self):
        assert _parse_number("85%") == 85.0

    def test_comma(self):
        assert _parse_number("1,234") == 1234.0

    def test_none(self):
        assert _parse_number(None) is None

    def test_invalid(self):
        assert _parse_number("abc") is None


class TestReadTextSafe:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_text_safe(f) == "hello world"

    def test_read_nonexistent(self, tmp_path):
        f = tmp_path / "missing.txt"
        assert read_text_safe(f) == ""

    def test_size_limit(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 1000, encoding="utf-8")
        result = read_text_safe(f, max_bytes=100)
        assert len(result) == 100


class TestParseHtmlReport:
    def test_parse_qac_fixture(self):
        path = FIXTURES / "qac_his_new.html"
        if not path.exists():
            pytest.skip("fixture missing")
        result = parse_html_report(path)
        assert result["title"] is not None
        assert "error" not in result

    def test_parse_missing_file(self):
        result = parse_html_report(Path("/nonexistent.html"))
        assert result.get("error") == "missing_file"

    def test_parse_vcast_fixture(self):
        path = FIXTURES / "vcast_metrics.html"
        if not path.exists():
            pytest.skip("fixture missing")
        result = parse_html_report(path)
        assert result["title"] is not None
        assert len(result["tables"]) > 0


# ── PRQA/Helix QAC RCR 위반 상세 (파일 × 규칙 매트릭스) ──────────────────────
# 신형(숫자 앵커 WorstRules1 + M3CM/Secure C 다중 그룹 테이블) 리포트 형태를 재현.
# DiagsPerParents(‘Total Violations’ 열)·FileStatus는 매트릭스에서 제외돼야 한다.
_RCR_HTML = """<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="worstrules">
  <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
  <div class="subsec"><h5>M3CM</h5></div>
  <table border="1">
   <tr><th>Files</th><th>Rule-2.1</th><th>Rule-8.6</th></tr>
   <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>3</td><td>5</td></tr>
   <tr><td align="left"><a href="..\\src\\bar.c" title="..\\src\\bar.c">bar.c</a></td><td>0</td><td>10</td></tr>
   <tr><td align="left"><a>RCMA</a></td><td>0</td><td>7</td></tr>
   <tr><td align="left"><a href="..\\src\\zero.h" title="..\\src\\zero.h">zero.h</a></td><td>0</td><td>0</td></tr>
  </table>
  <div class="subsec"><h5>Secure C</h5></div>
  <table border="1">
   <tr><th>Files</th><th>C-INT-002</th></tr>
   <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>2</td></tr>
  </table>
 </div>
 <div class="diags">
  <div class="sec"><h3><a name="DiagsPerParents1">Diagnostics Per Parent Rules</a></h3></div>
  <table border="1">
   <tr><th>Files</th><th>Rule 1</th><td><b>Total Violations</b></td></tr>
   <tr><td align="left"><a href="..\\src\\ghost.c" title="..\\src\\ghost.c">ghost.c</a></td><td>99</td><td><b>99</b></td></tr>
  </table>
 </div>
 <div class="analstat">
  <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
  <table border="1" id="filestat">
   <tr><th>Files</th><th>Active Diagnostics</th><th>Violated Rules</th><th>Violation Count</th><th>Compliance Index</th></tr>
   <tr><td align="left"><a href="..\\src\\bar.c" title="..\\src\\bar.c">bar.c</a></td><td>10</td><td>1</td><td>10</td><td>95.00%</td></tr>
   <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>8</td><td>3</td><td>10</td><td>98.00%</td></tr>
   <tr><td align="left">Total</td><td>18</td><td>4</td><td>9999</td><td>99.00%</td></tr>
  </table>
 </div>
</body></html>"""


class TestWorstRulesHeader:
    def test_worstrules_signature(self):
        assert _is_worstrules_header(["Files", "Rule-2.1", "Rule-8.6"]) is True
        assert _is_worstrules_header(["Files", "C-INT-002"]) is True

    def test_diagsperparents_excluded(self):
        # ‘Total Violations’ 열 보유 → 배제
        assert _is_worstrules_header(["Files", "Rule 1", "Total Violations"]) is False

    def test_filestatus_excluded(self):
        assert _is_worstrules_header(
            ["Files", "Active Diagnostics", "Violated Rules", "Violation Count", "Compliance Index"]
        ) is False

    def test_non_file_table_excluded(self):
        assert _is_worstrules_header(["Group", "Rule", "Status"]) is False
        assert _is_worstrules_header([]) is False


class TestPrqaRcrDetails:
    def _parse(self, tmp_path):
        p = tmp_path / "PROJ_RCR_01012026.html"
        p.write_text(_RCR_HTML, encoding="utf-8")
        return parse_prqa_rcr_details(p)

    def test_violations_by_file_matrix(self, tmp_path):
        res = self._parse(tmp_path)
        vbf = {f["file"]: f for f in res["violations_by_file"]}
        # foo.c 는 M3CM(Rule-2.1=3, Rule-8.6=5) + Secure C(C-INT-002=2) 병합 → total 10
        assert vbf["foo.c"]["total"] == 10
        foo_rules = {r["rule"]: r["count"] for r in vbf["foo.c"]["rules"]}
        assert foo_rules == {"Rule-8.6": 5, "Rule-2.1": 3, "C-INT-002": 2}
        # 규칙은 건수 내림차순 정렬
        assert [r["rule"] for r in vbf["foo.c"]["rules"]] == ["Rule-8.6", "Rule-2.1", "C-INT-002"]
        # bar.c = Rule-8.6 10
        assert vbf["bar.c"]["total"] == 10
        # RCMA(앵커 href 없음)도 위반 있으면 포함, path 는 빈 문자열
        assert vbf["RCMA"]["total"] == 7
        assert vbf["RCMA"]["path"] == ""

    def test_zero_row_and_diags_excluded(self, tmp_path):
        res = self._parse(tmp_path)
        files = {f["file"] for f in res["violations_by_file"]}
        assert "zero.h" not in files          # 전부 0 → 제외
        assert "ghost.c" not in files          # DiagsPerParents 테이블 → 매트릭스 제외

    def test_counts_are_int(self, tmp_path):
        res = self._parse(tmp_path)
        for f in res["violations_by_file"]:
            assert isinstance(f["total"], int)
            for r in f["rules"]:
                assert isinstance(r["count"], int)

    def test_sorted_by_total_desc_then_name(self, tmp_path):
        res = self._parse(tmp_path)
        order = [f["file"] for f in res["violations_by_file"]]
        # bar.c(10)·foo.c(10) 동점 → 파일명 오름차순, 이어서 RCMA(7)
        assert order == ["bar.c", "foo.c", "RCMA"]

    def test_top_rules_merged_from_all_groups(self, tmp_path):
        res = self._parse(tmp_path)
        totals = {r["rule"]: r["count"] for r in res["top_rules"]}
        assert totals["Rule-8.6"] == 22        # 5 + 10 + 7 (foo/bar/RCMA)
        assert totals["Rule-2.1"] == 3
        assert totals["C-INT-002"] == 2
        # 내림차순
        assert res["top_rules"][0]["rule"] == "Rule-8.6"

    def test_top_files_enriched(self, tmp_path):
        res = self._parse(tmp_path)
        tf = {f["file"]: f for f in res["top_files"]}
        assert tf["foo.c"]["violated_rules"] == 3
        assert tf["foo.c"]["compliance_index"] == "98.00%"
        assert tf["bar.c"]["violated_rules"] == 1
        assert tf["bar.c"]["path"] == "../src/bar.c"   # 역슬래시 정규화
        # FileStatus 말미 'Total' 집계 행은 파일이 아니므로 top_files에서 제외
        assert "Total" not in tf

    def test_missing_file_graceful(self, tmp_path):
        res = parse_prqa_rcr_details(tmp_path / "nope.html")
        assert "error" in res

    def test_build_summary_finds_rcr_in_parent(self, tmp_path):
        """RCR HTML이 report/ 하위가 아니라 빌드 루트(부모)에 있어도 심층 상세를 복원한다.

        KJPDS02_* Jenkins 잡은 RCR을 빌드 루트에 두는데 _detect_reports_dir는 report/를
        반환해, report_dir 스캔이 RCR을 놓쳐 top_rules/top_files/violations_by_file이
        전부 비던 회귀. build_report_summary의 부모 디렉토리 폴백을 고정한다.
        """
        build_root = tmp_path / "build_99"
        report_dir = build_root / "report"
        report_dir.mkdir(parents=True)
        (build_root / "PROJ_RCR_01012026.html").write_text(_RCR_HTML, encoding="utf-8")
        prqa = build_report_summary(report_dir)["kpis"]["prqa"]
        assert len(prqa["violations_by_file"]) > 0   # 부모 폴백으로 RCR 발견
        assert len(prqa["top_rules"]) > 0
        assert len(prqa["top_files"]) > 0

    def test_same_basename_different_path_not_merged(self, tmp_path):
        # 동일 basename(config.c)이 APP/BOOT 두 경로에 존재 → full path 키로 분리돼야 함
        html = (
            '<html><body><div class="sec"><h3><a name="WorstRules1">x</a></h3></div>'
            '<table border="1"><tr><th>Files</th><th>Rule-2.1</th></tr>'
            '<tr><td><a href="..\\APP\\config.c" title="..\\APP\\config.c">config.c</a></td><td>3</td></tr>'
            '<tr><td><a href="..\\BOOT\\config.c" title="..\\BOOT\\config.c">config.c</a></td><td>5</td></tr>'
            "</table></body></html>"
        )
        p = tmp_path / "PROJ_RCR.html"
        p.write_text(html, encoding="utf-8")
        res = parse_prqa_rcr_details(p)
        vbf = res["violations_by_file"]
        assert len(vbf) == 2                       # 오병합 없이 2건
        paths = sorted(f["path"] for f in vbf)
        assert paths == ["../APP/config.c", "../BOOT/config.c"]
        totals = sorted(f["total"] for f in vbf)
        assert totals == [3, 5]                    # 합산(8) 아님
