"""Tests for backend.services.swut_input_adapter.

SWTE 변종 HTML fragment fixture를 in-memory bytes로 생성해 extractors와
collect_from_log_folder 통합 동작을 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.swut_input_adapter import (  # noqa: E402
    CoverageStats,
    EnvironmentData,
    FunctionCoverage,
    SwUTSession,
    ExecutionRow,
    _extract_env_from_filename,
    _parse_metric_cell,
    collect_swut_session,
    extract_aggregate_coverage,
    extract_execution_results,
)


# ---------------------------------------------------------------------------
# Helpers — minimal HTML fixtures
# ---------------------------------------------------------------------------

_AGG_HTML_TEMPLATE = """<!DOCTYPE html>
<!-- VectorCAST Report header -->
<html><body>
<h2>Metrics</h2>
<table class="metrics">
<tbody>
<tr>
  <th>Unit</th><th>Subprogram</th><th>Complexity</th>
  <th>Statement+Branch</th><th>MC|DC</th>
</tr>
<tr>
  <th>SysOs_Main</th><th>main</th><th>3</th>
  <th class="success">8 / 8 (100%)</th>
  <th class="success">2 / 2 (100%)</th>
</tr>
<tr>
  <th>SysOs_Main</th><th>s_SysMain_Init</th><th>2</th>
  <th class="success">61 / 61 (100%)</th>
  <th class="success">19 / 19 (100%)</th>
</tr>
<tr>
  <th>GRAND TOTALS</th><th>10</th><th>16</th>
  <th class="success">69 / 69 (100%)</th>
  <th class="success">21 / 21 (100%)</th>
</tr>
</tbody>
</table>
<!-- VectorCAST Report footer -->
</body></html>
"""

_EXEC_HTML_TEMPLATE = """<!DOCTYPE html>
<!-- VectorCAST Report header -->
<html><body>
<!-- ExecutionResults/testcase_header -->
<h3 title="Execution Results">Execution Results (PASS)</h3>
<h4 class="test-start-header">Start of SwUFn_0101.001</h4>
<!-- ExecutionResults/testcase_header -->
<h3 title="Execution Results">Execution Results (FAIL)</h3>
<h4 class="test-start-header">Start of SwUFn_0101.002</h4>
<!-- VectorCAST Report footer -->
</body></html>
"""


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------

class TestParseMetricCell:
    @pytest.mark.parametrize("text,covered,total,pct", [
        ("69 / 69 (100%)", 69, 69, 1.0),
        ("8/8(100%)", 8, 8, 1.0),
        ("3 / 5 (60%)", 3, 5, 0.6),
        ("0 / 4 (0%)", 0, 4, 0.0),
    ])
    def test_parses(self, text, covered, total, pct):
        s = _parse_metric_cell(text)
        assert s.covered == covered
        assert s.total == total
        assert s.coverage_pct == pytest.approx(pct, abs=0.01)

    def test_empty_returns_zero(self):
        s = _parse_metric_cell("")
        assert s.covered == 0
        assert s.total == 0

    def test_invalid_returns_zero(self):
        s = _parse_metric_cell("no metric here")
        assert s.covered == 0


class TestExtractEnvFromFilename:
    @pytest.mark.parametrize("name,expected", [
        ("SWTE_01_test_case_data_report.html", "SWTE_01"),
        ("SWTE_34_execution_results_report.html", "SWTE_34"),
        ("SWTE_999_aggregate_coverage_report.html", "SWTE_999"),
        ("random_file.html", ""),
    ])
    def test_extract(self, name, expected):
        assert _extract_env_from_filename(name) == expected

    @pytest.mark.parametrize("name,expected", [
        # 36-fix: SwIT 실 환경 파일명 (사용자 환경 NE_GN7)
        ("SwITC_21_test_case_data_report.html", "SwITC_21"),
        ("SwITC_21_execution_results_report.html", "SwITC_21"),
        ("SwITC_21_aggregate_coverage_report.html", "SwITC_21"),
        ("SwITC_5_test_case_data_report.html", "SwITC_5"),
        ("SwITC_100_test_case_data_report.html", "SwITC_100"),
        ("SWTE_01_test_case_data_report.html", ""),  # SwUT 파일은 거부 (도메인 분리)
        ("random_file.html", ""),
    ])
    def test_extract_swit_prefix(self, name, expected):
        """36-fix: env_prefix="SwITC" 지원 — 사용자 실 환경 SwIT log 파일명 매칭."""
        assert _extract_env_from_filename(name, env_prefix="SwITC") == expected


# 37차: _resolve_latest_release_folder — 01.Log 상위 폴더 → latest release 자동 선택
class TestResolveLatestReleaseFolder:
    """37차: 사용자가 release 폴더 직접 지정 안 해도 자동으로 latest 선택."""

    def _make_release(self, root, name: str) -> None:
        """release 디렉토리 + 01.TestCaseDataReport sub-folder 생성."""
        rel = root / name
        (rel / "01.TestCaseDataReport").mkdir(parents=True, exist_ok=True)

    def test_case_a_direct_release_folder_returns_as_is(self, tmp_path):
        """release 폴더 직접 지정 (01.TestCaseDataReport 존재) → 그대로 반환."""
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        self._make_release(tmp_path, "v2.02_240219")
        direct = tmp_path / "v2.02_240219"
        warns: list[str] = []
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(direct), out_warnings=warns,
        )
        assert result == str(direct)
        assert not warns, "case A는 warning 없어야 함"

    def test_case_b_log_parent_picks_latest_by_date_suffix(self, tmp_path):
        """01.Log 상위 폴더 → 날짜 suffix 최대값 자동 선택."""
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # 3 release 생성 — 날짜 suffix 정렬: 240219 < 240315 < 241201
        for name in ("v2.02_240219", "v2.03_240315", "v2.10_241201"):
            self._make_release(tmp_path, name)
        warns: list[str] = []
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        assert result == str(tmp_path / "v2.10_241201")
        assert any("auto-resolved" in w for w in warns)
        assert any("v2.10_241201" in w for w in warns)

    def test_case_c_empty_folder_returns_original_with_warning(self, tmp_path):
        """후보 0건 → 원본 path 유지 + warning."""
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        warns: list[str] = []
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        assert result == str(tmp_path)
        assert any("미발견" in w for w in warns)

    def test_case_b_skips_non_release_pattern_dirs(self, tmp_path):
        """v<버전>_<날짜> 패턴 아닌 디렉토리는 후보에서 제외."""
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # release 1개 + 무관 디렉토리 2개
        self._make_release(tmp_path, "v2.02_240219")
        (tmp_path / "backup").mkdir()
        (tmp_path / "tmp_2024").mkdir()
        warns: list[str] = []
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        # 1 후보만 매칭 → 그게 latest
        assert result == str(tmp_path / "v2.02_240219")

    def test_case_b_skips_release_pattern_without_subfolder(self, tmp_path):
        """v<버전>_<날짜> 패턴이지만 01.TestCaseDataReport 없으면 후보 제외 (검증)."""
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # 'v2.10_241201'은 빈 디렉토리 (01.TestCaseDataReport 없음) → 후보 거부
        # 'v2.02_240219'만 실제 release → 선택
        (tmp_path / "v2.10_241201").mkdir()
        self._make_release(tmp_path, "v2.02_240219")
        warns: list[str] = []
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        assert result == str(tmp_path / "v2.02_240219")

    def test_w1_mixed_suffix_lengths_emit_warning(self, tmp_path):
        """37차 reviewer W1: YYMMDD (6) + YYYYMMDD (8) 혼재 감지 시 명시 warning."""
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # 6자리 240219 vs 8자리 20240219 — lexical 비교: '20240219' > '240219'
        # → 8자리가 latest로 선택되지만 실제 날짜는 동일 → 사용자에게 혼재 명시
        self._make_release(tmp_path, "v2.02_240219")     # 6자리
        self._make_release(tmp_path, "v2.03_20240219")   # 8자리 (실제로 같은 날짜)
        warns: list[str] = []
        _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        assert any("자리수 혼재" in w for w in warns), (
            f"혼재 감지 warning 미발생: {warns}"
        )

    def test_w2_resolver_exists_failure_emits_warning_not_silent(self, tmp_path):
        """37차 reviewer W2: resolver.exists() 예외 시 silent 아닌 warning 누적."""
        from backend.services.swut_input_adapter import _resolve_latest_release_folder

        class _ExplodingResolver:
            mode = "local"
            def exists(self, path: str) -> bool:
                raise PermissionError("test: gate OFF simulation")

        warns: list[str] = []
        result = _resolve_latest_release_folder(
            _ExplodingResolver(), str(tmp_path), out_warnings=warns,
        )
        # 원본 path 유지 + warning 누적 (silent 아님)
        assert result == str(tmp_path)
        assert any("resolver.exists() 예외" in w for w in warns), (
            f"W2 silent fallback fix 미적용: {warns}"
        )


class TestCoverageStats:
    def test_passed_when_full(self):
        assert CoverageStats(8, 8, 1.0).passed is True

    def test_not_passed_when_partial(self):
        assert CoverageStats(3, 5, 0.6).passed is False

    def test_not_passed_when_zero_total(self):
        assert CoverageStats(0, 0, 0.0).passed is False


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

class TestExtractAggregateCoverage:
    def test_extracts_functions_and_grand_total(self):
        funcs, total = extract_aggregate_coverage(_AGG_HTML_TEMPLATE.encode("utf-8"))
        assert len(funcs) == 2
        assert funcs[0].unit_id == "SysOs_Main"
        assert funcs[0].statement.covered == 8
        assert funcs[0].statement.total == 8
        assert funcs[1].statement.covered == 61
        assert funcs[1].statement.total == 61
        assert total.unit_id == "GRAND TOTALS"
        assert total.statement.covered == 69
        assert total.statement.total == 69
        assert total.branch.covered == 21
        assert total.branch.total == 21

    def test_empty_html_returns_empty(self):
        funcs, total = extract_aggregate_coverage(b"<html><body></body></html>")
        assert funcs == []
        assert total.statement.total == 0


class TestExtractExecutionResults:
    def test_extracts_pass_fail(self):
        results = extract_execution_results(_EXEC_HTML_TEMPLATE.encode("utf-8"))
        assert "SwUFn_0101.001" in results
        assert "SwUFn_0101.002" in results
        assert results["SwUFn_0101.001"].passed is True
        assert results["SwUFn_0101.002"].passed is False

    def test_empty_html_returns_empty(self):
        assert extract_execution_results(b"<html></html>") == {}


# ---------------------------------------------------------------------------
# collect_from_log_folder — using fake resolver
# ---------------------------------------------------------------------------

class _FakeResolver:
    """In-memory resolver — tests/unit/test_swut_input_adapter.py 전용.

    29차 W25: msys64 mingw Python의 ``os.sep='/'`` quirk로 ``os.path.join``이
    forward slash로 합쳐지면 등록된 backslash dirs/files와 mismatch — 양 형식
    동시 등록 + 조회 시 normalize.
    """

    @staticmethod
    def _normalize(path: str) -> str:
        # Windows 드라이브 문자 + 경로 — backslash로 통일.
        return path.replace("/", "\\")

    def __init__(self, files: dict[str, bytes], dirs: set[str]):
        self.files = {self._normalize(k): v for k, v in files.items()}
        self.dirs = {self._normalize(d) for d in dirs}

    def exists(self, path: str) -> bool:
        n = self._normalize(path)
        return n in self.files or n in self.dirs

    def is_file(self, path: str) -> bool:
        return self._normalize(path) in self.files

    def is_dir(self, path: str) -> bool:
        return self._normalize(path) in self.dirs

    def read_bytes(self, path: str) -> bytes:
        return self.files[self._normalize(path)]

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False) -> list[str]:
        import fnmatch
        n = self._normalize(path)
        out = []
        for fp in self.files:
            if fp.startswith(n + "\\"):
                tail = fp[len(n) + 1:]
                if "\\" not in tail and fnmatch.fnmatch(tail, pattern):
                    out.append(fp)
        return out


def _make_tc_html(env: str = "SWTE_01", component: str = "SysOs_Main") -> bytes:
    return ("""<!DOCTYPE html>
<!-- VectorCAST Report header -->
<html><head><meta/><meta/><meta/></head><body>
    <title>Test Case Data Report</title>
    <h2>Configuration Data</h2>
    <!-- TestcaseSectionsHeader -->
    <h2 class="testcase_section">""" + env + """.001</h2>
    <h3>Test Case Configuration</h3>
    <table><tbody>
    <tr><th>Unit Under Test</th><td>""" + component + """</td><th>Subprogram</th><td>main</td></tr>
    <tr><th>Test Case Name</th><td>""" + env + """.001</td></tr>
    </tbody></table>
    <!-- TestCaseData -->
    <h3>Test Case Data</h3>
    <table><tbody></tbody></table>
</body></html>""").encode("utf-8")


class TestCollectFromLogFolder:
    @pytest.fixture
    def fake_session_setup(self):
        log_root = r"C:\fake\01.Log\v0.01_TEST"
        tc_dir = log_root + r"\01.TestCaseDataReport"
        ex_dir = log_root + r"\02.ExecutionResultReport"
        cov_dir = log_root + r"\03.AggregateCoverageReport"

        files = {
            tc_dir + r"\SWTE_01_test_case_data_report.html":
                _make_tc_html(env="SWTE_01", component="SysOs_Main"),
            ex_dir + r"\SWTE_01_execution_results_report.html":
                _EXEC_HTML_TEMPLATE.encode("utf-8"),
            cov_dir + r"\SWTE_01_aggregate_coverage_report.html":
                _AGG_HTML_TEMPLATE.encode("utf-8"),
        }
        dirs = {log_root, tc_dir, ex_dir, cov_dir}
        return log_root, _FakeResolver(files, dirs)

    def test_collects_one_environment(self, fake_session_setup):
        log_root, resolver = fake_session_setup
        session = collect_swut_session(
            resolver, project_id="HDPDM01", log_folder=log_root,
        )
        assert session.project_id == "HDPDM01"
        assert session.source_kind == "log_folder"
        assert len(session.environments) == 1
        env = session.environments[0]
        assert env.env_name == "SWTE_01"
        # ExecutionResult fixture에서 2 TC (PASS + FAIL)
        assert len(env.test_results) == 2
        passed = sum(1 for r in env.test_results.values() if r.passed)
        assert passed == 1
        # AggregateCoverage fixture: 2 function + GRAND TOTAL
        assert len(env.function_coverage) == 2
        assert env.grand_total.statement.covered == 69

    def test_missing_log_folder_raises(self):
        resolver = _FakeResolver({}, set())
        with pytest.raises(ValueError, match="둘 중 하나"):
            collect_swut_session(resolver, project_id="HDPDM01")

    def test_empty_log_folder_emits_warning(self):
        log_root = r"C:\fake\empty"
        resolver = _FakeResolver({}, {log_root})
        session = collect_swut_session(
            resolver, project_id="HDPDM01", log_folder=log_root,
        )
        assert session.environments == []
        # 하위 폴더 미발견 + 환경 0건 warning 둘 다
        assert len(session.parse_warnings) >= 2

    def test_allowed_roots_blocks_outside_path(self, tmp_path):
        """deep-reviewer 시나리오 B: log_folder가 allowed_roots 밖이면 거부."""
        from backend.services.swut_input_adapter import collect_from_log_folder
        outside = tmp_path / "outside"
        outside.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        resolver = _FakeResolver({}, {str(outside)})
        with pytest.raises(ValueError, match="not within allowed_roots"):
            collect_from_log_folder(
                resolver, str(outside), project_id="HDPDM01",
                allowed_roots=[str(allowed)],
            )

    def test_allowed_roots_accepts_subdirectory(self, tmp_path):
        from backend.services.swut_input_adapter import collect_from_log_folder
        sub = tmp_path / "project" / "log"
        sub.mkdir(parents=True)
        resolver = _FakeResolver({}, {str(sub)})
        session = collect_from_log_folder(
            resolver, str(sub), project_id="HDPDM01",
            allowed_roots=[str(tmp_path / "project")],
        )
        assert session.project_id == "HDPDM01"


# ---------------------------------------------------------------------------
# Dataclass shapes (regression — frontend 호환성)
# ---------------------------------------------------------------------------

class TestDataclassFields:
    def test_environment_data_defaults(self):
        e = EnvironmentData()
        assert e.env_name == ""
        assert e.test_cases == {}
        assert e.test_results == {}
        assert e.function_coverage == []
        assert e.parse_errors == []

    def test_test_execution_defaults(self):
        te = ExecutionRow(tc_name="X.001")
        assert te.tc_name == "X.001"
        assert te.passed is False
        assert te.events == []

    def test_function_coverage_defaults(self):
        fc = FunctionCoverage()
        assert fc.unit_id == ""
        assert fc.statement.total == 0

    def test_session_defaults(self):
        s = SwUTSession()
        assert s.environments == []
        assert s.parse_warnings == []
