"""Report Parser 단위 테스트"""
from pathlib import Path
import pytest

from backend.services.report_parsers import (
    _clean_text,
    _first_present,
    _is_worstrules_header,
    _parse_number,
    build_report_summary,
    parse_html_report,
    parse_prqa_rcr_details,
    parse_prqa_rcr_summary,
    read_text_safe,
    resolve_code_metrics,
    resolve_scm_vcast_metrics,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# Helix QAC 포맷 RCR — PRQA와 라벨이 다르다("... (including CMA)", "... (including headers)").
# KJPDS02_* 등이 이 포맷. 파일수/LOC 라벨 변형 + 공통 위반 라벨을 담는다.
_HELIX_RCR_HTML = """<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
<table>
<tr><td>Number of Files (including CMA)</td><td>126</td></tr>
<tr><td>Lines of Code (including headers)</td><td>67464</td></tr>
<tr><td>Total preprocessed code lines (STTLN)</td><td>21194</td></tr>
<tr><td>Diagnostic Count</td><td>496</td></tr>
<tr><td>Rule Violation Count</td><td>558</td></tr>
<tr><td>Violated Rules</td><td>18</td></tr>
<tr><td>Compliant Rules</td><td>211</td></tr>
<tr><td>File Compliance Index</td><td>99</td></tr>
<tr><td>Project Compliance Index</td><td>92</td></tr>
</table></body></html>"""


def _write_report_dir(tmp_path, *, analysis_summary, rcr_html=None):
    """build_report_summary가 읽는 최소 report_dir 픽스처(analysis_summary.json[+RCR html])를 만든다."""
    import json
    rdir = tmp_path / "report"
    rdir.mkdir()
    (rdir / "analysis_summary.json").write_text(
        json.dumps(analysis_summary), encoding="utf-8")
    if rcr_html is not None:
        # RCR을 report_dir 부모(빌드 루트)에 둔다 — KJPDS02_* 실제 레이아웃과 동일.
        (tmp_path / "PROJ_RCR_01012026.html").write_text(rcr_html, encoding="utf-8")
    return rdir


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

    def test_build_summary_picks_newest_rcr_across_locations(self, tmp_path):
        """report/의 오래된 RCR보다 빌드 루트의 최신 RCR을 mtime 기준으로 선택한다.

        파일명 사전순(DDMMYYYY)이나 report/ stale RCR에 오도되지 않도록 위치 무관
        mtime 최신 선택을 고정. (사전순이면 'NEW' < 'OLD'라 stale을 골라 빈 상세가 됨.)
        """
        import os
        build_root = tmp_path / "build_1"
        report_dir = build_root / "report"
        report_dir.mkdir(parents=True)
        stale = report_dir / "NEW_RCR_01012020.html"   # 이름은 사전순 앞이나 mtime은 과거
        stale.write_text("<html><body>empty</body></html>", encoding="utf-8")
        fresh = build_root / "OLD_RCR_01012026.html"    # 이름은 사전순 뒤지만 mtime은 최신
        fresh.write_text(_RCR_HTML, encoding="utf-8")
        os.utime(stale, (1_000_000, 1_000_000))
        os.utime(fresh, (2_000_000, 2_000_000))
        prqa = build_report_summary(report_dir)["kpis"]["prqa"]
        assert len(prqa["violations_by_file"]) > 0     # 최신(fresh) RCR 선택 → 상세 채워짐

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


class TestFirstPresent:
    def test_returns_first_non_none(self):
        d = {"a": None, "b": 5, "c": 9}
        assert _first_present(d, "a", "b", "c") == 5

    def test_all_missing_or_none(self):
        assert _first_present({"a": None}, "a", "x") is None


class TestHelixRcrLabels:
    """Helix QAC 변형 라벨(파일수/LOC)이 PRQA 라벨과 함께 추출되는지(A1)."""

    def test_helix_file_and_loc_labels_extracted(self, tmp_path):
        p = tmp_path / "PROJ_RCR_01012026.html"
        p.write_text(_HELIX_RCR_HTML, encoding="utf-8")
        m = parse_prqa_rcr_summary(p)["metrics"]
        # Helix 변형 라벨로도 파일수/LOC가 회수돼야 한다(과거엔 누락 → number_of_files=0).
        assert m.get("Number of Files (including CMA)") == 126
        assert m.get("Lines of Code (including headers)") == 67464
        # 공통 위반 라벨은 여전히 정상.
        assert m.get("Rule Violation Count") == 558
        assert m.get("Diagnostic Count") == 496


class TestCodeMetricsQacFallback:
    """code_metrics: lizard(complexity.csv) 부재 시 QAC 폴백 + source/reason 표식(A2)."""

    def test_qac_fallback_when_lizard_absent(self, tmp_path):
        # KJPDS02_PV 형태: analysis_summary.code_metrics=all None + QAC RCR/HMR 존재.
        rdir = _write_report_dir(
            tmp_path,
            analysis_summary={
                "code_metrics": {"code_files": None, "functions": None, "nloc": None},
                "prqa": {
                    "rcr": {"ok": True, "summary": {"Rule Violation Count": 558}},
                    "hmr": {"ok": True, "stats": {"functions_total": 881}},
                },
            },
            rcr_html=_HELIX_RCR_HTML,
        )
        cm = build_report_summary(rdir)["kpis"]["code_metrics"]
        assert cm["source"] == "qac"
        assert cm["code_files"] == 126        # Helix RCR "Number of Files (including CMA)"
        assert cm["functions"] == 881         # HMR functions_total
        assert cm["nloc"] == 67464            # Helix RCR "Lines of Code (including headers)"

    def test_lizard_kept_when_present_no_regression(self, tmp_path):
        # HDPDM01 형태: complexity.csv 유래 code_metrics 존재 → 그대로 유지 + source='lizard'.
        rdir = _write_report_dir(
            tmp_path,
            analysis_summary={
                "code_metrics": {"code_files": 30, "functions": 349, "nloc": 4429},
                "prqa": {"rcr": {"ok": True, "summary": {"Rule Violation Count": 577}}},
            },
            rcr_html=_HELIX_RCR_HTML,   # QAC가 있어도 lizard가 우선(폴백 미발동)
        )
        cm = build_report_summary(rdir)["kpis"]["code_metrics"]
        assert cm["source"] == "lizard"
        assert (cm["code_files"], cm["functions"], cm["nloc"]) == (30, 349, 4429)

    def test_absent_marks_reason_when_no_lizard_no_qac(self, tmp_path):
        # 완전 부재: lizard 없음 + QAC 리포트도 없음 → source=None + reason(침묵 제거).
        rdir = _write_report_dir(
            tmp_path,
            analysis_summary={"code_metrics": {"code_files": None, "functions": None, "nloc": None}},
        )
        cm = build_report_summary(rdir)["kpis"]["code_metrics"]
        assert cm["source"] is None
        assert cm["reason"] == "no_complexity_csv_and_no_qac"
        assert cm["code_files"] is None and cm["functions"] is None and cm["nloc"] is None

    def test_code_metrics_json_null_does_not_crash(self, tmp_path):
        # analysis_summary.code_metrics가 JSON null(None)이어도 dict(None) 크래시 없이 처리(방어).
        rdir = _write_report_dir(tmp_path, analysis_summary={"code_metrics": None})
        cm = build_report_summary(rdir)["kpis"]["code_metrics"]
        assert cm["source"] is None and cm["reason"] == "no_complexity_csv_and_no_qac"


class TestResolveCodeMetrics:
    """resolve_code_metrics 공용 헬퍼 — 상세탭(build_report_summary)·대시보드(aggregate_stats) 단일 출처."""

    def test_aggregate_path_reads_cached_prqa_summary(self):
        # aggregate는 live 인자 없이 analysis_summary.prqa(캐시)에서 QAC 폴백을 해석한다.
        summary = {
            "code_metrics": {"code_files": None, "functions": None, "nloc": None},
            "prqa": {
                "rcr": {"summary": {"Number of Files (including CMA)": 126,
                                    "Lines of Code (including headers)": 67464}},
                "hmr": {"stats": {"functions_total": 881}},
            },
        }
        cm = resolve_code_metrics(summary)
        assert cm == {"code_files": 126, "functions": 881, "nloc": 67464, "source": "qac"}

    def test_lizard_present_keeps_values_and_labels_source(self):
        cm = resolve_code_metrics({"code_metrics": {"code_files": 30, "functions": 349, "nloc": 4429}})
        assert cm["source"] == "lizard"
        assert (cm["code_files"], cm["functions"], cm["nloc"]) == (30, 349, 4429)

    def test_live_override_takes_precedence_over_cached(self):
        # build_report_summary 경로: live RCR 파싱값(prqa_metrics)/HMR stats가 캐시보다 우선.
        summary = {
            "code_metrics": {"code_files": None, "functions": None, "nloc": None},
            "prqa": {"rcr": {"summary": {"Lines of Code (source files only)": 99999}}},
        }
        cm = resolve_code_metrics(
            summary,
            prqa_metrics={"Number of Files": 126, "Lines of Code (source files only)": 67464},
            hmr_stats={"functions_total": 881},
        )
        assert cm["nloc"] == 67464 and cm["code_files"] == 126 and cm["functions"] == 881
        assert cm["source"] == "qac"

    def test_absent_everywhere_marks_reason(self):
        cm = resolve_code_metrics({"code_metrics": {}})
        assert cm["source"] is None and cm["reason"] == "no_complexity_csv_and_no_qac"

    def test_non_dict_input_is_safe(self):
        # None/비-dict analysis_summary도 크래시 없이 부재로 처리.
        assert resolve_code_metrics(None)["source"] is None
        assert resolve_code_metrics({"code_metrics": None})["source"] is None


class TestResolveScmVcastMetrics:
    """resolve_scm_vcast_metrics — SCM 로드 이력 payload → 대시보드 경량 지표(상세탭 effVcast 미러)."""

    def test_merged_payload_extracts_coverage_tc_and_pass(self):
        payload = {
            "coverage": {
                "statement": {"covered": 8579, "total": 8622, "rate": 0.995},
                "branch": {"covered": 4044, "total": 4097, "rate": 0.9871},
                "mcdc": {"covered": 0, "total": 0, "rate": None},
            },
            "test_rows_count_ut": 120, "test_rows_count_it": 45,
            "summary_ut": {"total": 120, "passed": 118, "failed": 2, "pass_rate": 0.9833},
            "summary_it": {"total": 45, "passed": 45, "failed": 0, "pass_rate": 1.0},
        }
        m = resolve_scm_vcast_metrics(payload)
        assert m is not None
        assert m["line_rate"] == 0.995          # statement.rate가 대시보드 line_rate 소스
        assert m["branch_rate"] == 0.9871
        assert (m["ut_total"], m["it_total"]) == (120, 45)
        assert (m["ut_passed"], m["it_passed"]) == (118, 45)

    def test_merged_legacy_splits_by_test_rows_source(self):
        # 병합 payload는 vcast_kind가 없고(단일폴더만 보유) split 카운트도 없다(구 payload).
        # test_rows의 행별 source로 분리해야 IT가 UT로 오귀속되지 않는다(reviewer Critical 재현: NE1AW).
        payload = {
            "coverage": {"statement": {"covered": 70, "total": 100, "rate": 0.7},
                         "branch": {"covered": 0, "total": 0, "rate": None},
                         "mcdc": {"covered": 0, "total": 0, "rate": None}},
            "test_rows_count": 5,
            "test_rows": [{"source": "UT"}, {"source": "UT"}, {"source": "UT"},
                          {"source": "IT"}, {"source": "IT"}],
            "summary": {"total": 5, "passed": 4, "failed": 1, "pass_rate": 0.8},
        }
        m = resolve_scm_vcast_metrics(payload)
        assert m is not None
        assert (m["ut_total"], m["it_total"]) == (3, 2)   # kind 추정이었으면 (5, 0)로 오귀속됐음
        # 병합엔 vcast_kind 없어 결합 summary를 어느 쪽에도 안 몰아줌(합격 집계 보류).
        assert m["ut_passed"] is None and m["it_passed"] is None

    def test_single_folder_ut_with_split_injected(self):
        # 단일폴더도 multi 래퍼가 test_rows_count_ut/it·summary_ut/it를 주입한다(jenkins.py:1527-1532).
        payload = {
            "vcast_kind": "UT",
            "coverage": {"statement": {"covered": 90, "total": 100, "rate": 0.9},
                         "branch": {"covered": 0, "total": 0, "rate": None},
                         "mcdc": {"covered": 0, "total": 0, "rate": None}},
            "test_rows_count": 10, "test_rows_count_ut": 10, "test_rows_count_it": 0,
            "summary_ut": {"total": 10, "passed": 9, "failed": 1, "pass_rate": 0.9},
            "summary_it": None,
        }
        m = resolve_scm_vcast_metrics(payload)
        assert m is not None
        assert m["line_rate"] == 0.9
        assert (m["ut_total"], m["it_total"]) == (10, 0)
        assert m["ut_passed"] == 9

    def test_old_payload_without_split_routes_by_kind(self):
        # 2026-07-06 split 이전 payload: test_rows_count_ut/it 부재 → vcast_kind로 결합 카운트 귀속.
        payload_it = {
            "vcast_kind": "IT",
            "coverage": {"statement": {"covered": 7, "total": 10, "rate": 0.7},
                         "branch": {"covered": 0, "total": 0, "rate": None},
                         "mcdc": {"covered": 0, "total": 0, "rate": None}},
            "test_rows_count": 33,
            "summary": {"total": 33, "passed": 30, "failed": 3, "pass_rate": 0.9091},
        }
        m = resolve_scm_vcast_metrics(payload_it)
        assert m is not None
        assert (m["ut_total"], m["it_total"]) == (0, 33)   # IT로 귀속
        assert m["it_passed"] == 30 and m["ut_passed"] is None
        assert m["line_rate"] == 0.7

    def test_mcdc_total_zero_keeps_rate_none_not_zero(self):
        # 대시보드는 statement를 line_rate로 쓰지만, total=0→rate=None 계약을 payload가 지켜야 함.
        payload = {"coverage": {"statement": {"covered": 0, "total": 0, "rate": None}},
                   "test_rows_count_ut": 5, "test_rows_count_it": 0}
        m = resolve_scm_vcast_metrics(payload)
        assert m is not None
        assert m["line_rate"] is None       # 0% 미커버 위장 아님
        assert m["ut_total"] == 5           # TC는 있으니 이력은 유효

    def test_no_coverage_no_tests_returns_none(self):
        assert resolve_scm_vcast_metrics(
            {"coverage": {}, "test_rows_count_ut": 0, "test_rows_count_it": 0}) is None
        assert resolve_scm_vcast_metrics({}) is None
        assert resolve_scm_vcast_metrics(None) is None
