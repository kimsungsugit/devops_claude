"""Tests for backend.services.swut_input_adapter.

SWTE 변종 HTML fragment fixture를 in-memory bytes로 생성해 extractors와
collect_from_log_folder 통합 동작을 검증.
"""
from __future__ import annotations

import os
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

    def test_w6_large_candidate_count_performance(self, tmp_path):
        """38차 W6: 100개 후보 디렉토리 → 1초 미만 처리 (성능)."""
        import time
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # 100 release 후보 + 01.TestCaseDataReport 각각
        for i in range(100):
            yymmdd = f"24{i // 30 + 1:02d}{(i % 28) + 1:02d}"  # YYMMDD
            ver_minor = i % 100
            self._make_release(tmp_path, f"v2.{ver_minor:02d}_{yymmdd}")
        warns: list[str] = []
        t0 = time.perf_counter()
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"100 후보 처리 1초 초과: {elapsed:.3f}s"
        assert "v2." in os.path.basename(result)
        assert any("100개 후보" in w for w in warns)

    def test_w6_symlink_release_folder_recognized(self, tmp_path):
        """38차 W6: symlink로 가리킨 release 폴더도 정상 후보로 인정 (POSIX 한정).

        Windows에서는 symlink 권한 제약으로 skip — 환경 검증.
        """
        import platform
        from backend.services.file_resolver import LocalFileResolver
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # 실 release 생성 후 symlink 추가
        real = tmp_path / "real_v2.02_240219"
        (real / "01.TestCaseDataReport").mkdir(parents=True)
        link = tmp_path / "v2.10_241201"
        try:
            os.symlink(str(real), str(link), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            import pytest as _pytest
            _pytest.skip(f"symlink unsupported ({platform.system()})")
        warns: list[str] = []
        result = _resolve_latest_release_folder(
            LocalFileResolver(), str(tmp_path), out_warnings=warns,
        )
        # symlink target은 v2.10_241201 이름 — 후보 인정되면 selected
        assert "v2.10_241201" in result

    def test_c2_cloudium_list_dir_returns_directories(self, tmp_path):
        """38차 C2: cloudium 모드 fallback — list_dir이 디렉토리 반환 시 자동 latest."""
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        # Create 2 release folders
        self._make_release(tmp_path, "v2.02_240219")
        self._make_release(tmp_path, "v2.10_241201")

        class _CloudiumLike:
            mode = "cloudium"
            def exists(self, path: str) -> bool:
                return os.path.exists(path)
            def list_dir(self, path: str, pattern: str = "*", recursive: bool = False) -> list[str]:
                # cloudium worker처럼 디렉토리 포함 반환 (디렉토리 enum 가능 가정)
                return [os.path.join(path, n) for n in os.listdir(path)]

        warns: list[str] = []
        result = _resolve_latest_release_folder(
            _CloudiumLike(), str(tmp_path), out_warnings=warns,
        )
        # v2.10_241201이 선택됨
        assert os.path.basename(result) == "v2.10_241201"
        assert any("auto-resolved (cloudium)" in w for w in warns)

    def test_c2_cloudium_list_dir_files_only_graceful(self, tmp_path):
        """38차 C2: cloudium worker가 파일만 반환 시 graceful warning + 원본 유지."""
        from backend.services.swut_input_adapter import _resolve_latest_release_folder
        self._make_release(tmp_path, "v2.02_240219")

        class _FilesOnlyCloudium:
            mode = "cloudium"
            def exists(self, path: str) -> bool:
                return os.path.exists(path)
            def list_dir(self, path: str, pattern: str = "*", recursive: bool = False) -> list[str]:
                # 파일만 반환 (디렉토리 무시) — 일부 worker 버전 시뮬레이션
                return []

        warns: list[str] = []
        result = _resolve_latest_release_folder(
            _FilesOnlyCloudium(), str(tmp_path), out_warnings=warns,
        )
        assert result == str(tmp_path)  # 원본 유지
        assert any("cloudium worker" in w for w in warns)

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
        """라운드 76 자체평가 fix #4 — unit_id가 component name(SysOs_Main)이 아닌
        함수명(main / s_SysMain_Init). vcast HTML table[2] R1/R2가 같은 component
        다른 함수 패턴 (R2 first cell 빈)이라 함수 단위 추출이 정확."""
        funcs, total = extract_aggregate_coverage(_AGG_HTML_TEMPLATE.encode("utf-8"))
        assert len(funcs) == 2
        assert funcs[0].unit_id == "main"  # 라운드 76 fix — Subprogram(함수명)
        assert funcs[0].name == "main"
        assert funcs[0].statement.covered == 8
        assert funcs[0].statement.total == 8
        assert funcs[1].unit_id == "s_SysMain_Init"  # 같은 component 다른 함수
        assert funcs[1].statement.covered == 61
        assert funcs[1].statement.total == 61
        assert total.statement.covered == 69
        assert total.statement.total == 69
        assert total.branch.covered == 21
        assert total.branch.total == 21


class TestRound77ComponentName:
    """라운드 77 T1201/T1202 — FunctionCoverage.component_name 필드 + extract 명시 주입."""

    def test_extract_assigns_component_name(self):
        """extract_aggregate_coverage가 vcast row의 component name을 fc.component_name에 주입."""
        funcs, total = extract_aggregate_coverage(_AGG_HTML_TEMPLATE.encode("utf-8"))
        assert len(funcs) == 2
        # 두 함수 모두 같은 component (SysOs_Main) — extract가 current_component 추적
        assert funcs[0].component_name == "SysOs_Main"
        assert funcs[1].component_name == "SysOs_Main"

    def test_function_coverage_default_component_name_empty(self):
        """FunctionCoverage 신규 필드 default `""` — backward-compat."""
        from backend.services.swut_input_adapter import FunctionCoverage
        fc = FunctionCoverage(unit_id="SwUFn_0101", name="main")
        assert fc.component_name == ""  # default

    def test_flatten_sub_functions_assigns_module_as_component(self):
        """flatten_sub_functions가 module_name을 component_name에 주입."""
        from backend.services.swut_input_adapter import flatten_sub_functions
        from backend.services.vcast_parser import MetricsBank, SubFunctionExecution
        mb = MetricsBank(environment="SWTE_01")
        mb.sub_functions["ModA"] = [
            SubFunctionExecution(order="1", name="fn_a", executed=True),
            SubFunctionExecution(order="2", name="fn_b", executed=False),
        ]
        result = flatten_sub_functions(mb, component_name="comp_test")
        assert len(result) == 2
        # sub_functions의 parent module = component_name
        assert result[0].component_name == "ModA"
        assert result[1].component_name == "ModA"

    def test_merge_c_parser_assigns_file_stem_as_component(self):
        """merge_function_rows_with_c_parser가 c_parser only row의 file.stem을 component_name 주입."""
        from backend.services.swut_input_adapter import (
            merge_function_rows_with_c_parser, FunctionCoverage,
        )
        agg = {"function_rows": [], "function_asil_map": {}}
        c_map = {
            "fn_alpha": {"file": "Cpu.c"},
            "fn_beta": {"file": "Ap_DoorCtrl_PDS.c"},
        }
        merged = merge_function_rows_with_c_parser(agg, c_map)
        assert len(merged) == 2
        names = {fc.name: fc for fc in merged}
        assert names["fn_alpha"].component_name == "Cpu"
        assert names["fn_beta"].component_name == "Ap_DoorCtrl_PDS"

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


# ---------------------------------------------------------------------------
# 58차 F1 — extract_execution_results_with_actual (BeautifulSoup actual 추출)
# ---------------------------------------------------------------------------


class TestExtractExecutionResultsWithActual:
    """F1: VectorCAST ExecutionResult.html → ExecutionRow.actual_result Dict."""

    def test_pass_distinction(self):
        """`<h3>Execution Results (PASS)</h3>` → ExecutionRow.passed=True."""
        from backend.services.swut_input_adapter import (
            extract_execution_results_with_actual,
        )
        html = b"""<html><body>
        <h4>Start of SwUFn_0101.001</h4>
        <h3 title="Execution Results">Execution Results (PASS)</h3>
        </body></html>"""
        results = extract_execution_results_with_actual(html)
        assert "SwUFn_0101.001" in results
        row = results["SwUFn_0101.001"]
        assert row.passed is True

    def test_fail_distinction(self):
        """`(FAIL)` → passed=False."""
        from backend.services.swut_input_adapter import (
            extract_execution_results_with_actual,
        )
        html = b"""<html><body>
        <h4>Start of SwUFn_0103.001</h4>
        <h3 title="Execution Results">Execution Results (FAIL)</h3>
        </body></html>"""
        results = extract_execution_results_with_actual(html)
        assert results["SwUFn_0103.001"].passed is False

    def test_empty_actual_graceful(self):
        """actual_result HTML 패턴 없으면 빈 dict — graceful (예외 없음)."""
        from backend.services.swut_input_adapter import (
            extract_execution_results_with_actual,
        )
        html = b"""<html><body>
        <h4>Start of SwUFn_0101.001</h4>
        <h3 title="Execution Results">Execution Results (PASS)</h3>
        </body></html>"""
        results = extract_execution_results_with_actual(html)
        assert results["SwUFn_0101.001"].actual_result == {}

    def test_multiple_tcs(self):
        """h3 → h4 변형 A (실 VectorCAST format) — 2개 ExecutionRow 추출."""
        from backend.services.swut_input_adapter import (
            extract_execution_results_with_actual,
        )
        html = b"""<html><body>
        <h3 title="Execution Results">Execution Results (PASS)</h3>
        <h4>Start of SwUFn_0101.001</h4>
        <h3 title="Execution Results">Execution Results (FAIL)</h3>
        <h4>Start of SwUFn_0102.001</h4>
        </body></html>"""
        results = extract_execution_results_with_actual(html)
        assert "SwUFn_0101.001" in results
        assert "SwUFn_0102.001" in results
        assert results["SwUFn_0101.001"].passed is True
        assert results["SwUFn_0102.001"].passed is False


# ---------------------------------------------------------------------------
# 59차 F4-B — extract_step_iterations (Iteration anchor 추출 인프라)
# ---------------------------------------------------------------------------


class TestExtractStepIterationsF4B:
    """F4-B: VectorCAST HTML → step별 input dict list. KJPDS02 v1.01 호환 인프라.

    HDPDM01 NE_GN7 v2.02 fixture에는 Iteration 라벨 0건 (라이브 검증 결과) — 본
    인프라는 미래 KJPDS02 환경 호환 보장.
    """

    def test_no_iteration_label_returns_empty_list_per_tc(self):
        """HDPDM01 fixture 패턴 — Iteration 라벨 없음 → 모든 TC empty list."""
        from backend.services.swut_input_adapter import extract_step_iterations
        html = b"""<html><body>
        <h4>Start of SwUFn_0101.001</h4>
        <h3 title="Execution Results">Execution Results (PASS)</h3>
        <h4>Start of SwUFn_0102.001</h4>
        </body></html>"""
        results = extract_step_iterations(html)
        assert "SwUFn_0101.001" in results
        assert results["SwUFn_0101.001"] == []
        assert results["SwUFn_0102.001"] == []

    def test_iteration_label_extracts_step_dicts(self):
        """Iteration N anchor + INPUT VALUE 라벨 → step별 dict list."""
        from backend.services.swut_input_adapter import extract_step_iterations
        html = b"""<html><body>
        <h4>Start of SwITC_0101_01</h4>
        <h5>Iteration 1</h5>
        <table><tr>
            <td>INPUT VALUE</td><td>u16_var_a</td><td>1</td>
        </tr><tr>
            <td>INPUT VALUE</td><td>u16_var_b</td><td>0</td>
        </tr></table>
        <h5>Iteration 2</h5>
        <table><tr>
            <td>INPUT VALUE</td><td>u16_var_a</td><td>2</td>
        </tr><tr>
            <td>INPUT VALUE</td><td>u16_var_b</td><td>5</td>
        </tr></table>
        <h4>Start of SwITC_0101_02</h4>
        </body></html>"""
        results = extract_step_iterations(html)
        assert "SwITC_0101_01" in results
        steps = results["SwITC_0101_01"]
        assert len(steps) == 2
        assert steps[0] == {"u16_var_a": "1", "u16_var_b": "0"}
        assert steps[1] == {"u16_var_a": "2", "u16_var_b": "5"}

    def test_test_step_label_also_recognized(self):
        """`Test Step N`, `Step N`, `Sequence Step N` 변형도 인식 (대소문자 무시)."""
        from backend.services.swut_input_adapter import extract_step_iterations
        html = b"""<html><body>
        <h4>Start of SwITC_0001</h4>
        <h5>Test Step 1</h5>
        <table><tr>
            <td>INPUT VALUE</td><td>var1</td><td>10</td>
        </tr></table>
        <h5>Test Step 2</h5>
        <table><tr>
            <td>INPUT VALUE</td><td>var1</td><td>20</td>
        </tr></table>
        </body></html>"""
        results = extract_step_iterations(html)
        steps = results["SwITC_0001"]
        assert len(steps) == 2
        assert steps[0]["var1"] == "10"
        assert steps[1]["var1"] == "20"


# ---------------------------------------------------------------------------
# 라운드 75 — flatten_sub_functions helper (T1007)
# ---------------------------------------------------------------------------

class TestFlattenSubFunctions:
    """vcast_parser.MetricsBank.sub_functions 평탄화."""

    def _make_bank(self, sub_functions):
        from backend.services.swut_input_adapter import flatten_sub_functions  # noqa: F401
        from backend.services.vcast_parser import MetricsBank, SubFunctionExecution
        mb = MetricsBank(environment="SWTE_01")
        for module_name, items in sub_functions.items():
            mb.sub_functions[module_name] = [
                SubFunctionExecution(order=str(i + 1), name=name, executed=executed)
                for i, (name, executed) in enumerate(items)
            ]
        return mb

    def test_normal_flatten_unit_id_auto_generation(self):
        from backend.services.swut_input_adapter import flatten_sub_functions
        bank = self._make_bank({
            "ModA": [("fnA_1", True), ("fnA_2", False)],
            "ModB": [("fnB_1", True)],
        })
        result = flatten_sub_functions(bank, component_name="SysOs_Main")
        assert len(result) == 3
        names = {fc.name for fc in result}
        assert names == {"fnA_1", "fnA_2", "fnB_1"}
        # unit_id 자동 생성 — SwUFn_<component>_<module_idx>_<suborder>
        unit_ids = {fc.unit_id for fc in result}
        for uid in unit_ids:
            assert uid.startswith("SwUFn_SysOs_Main_")

    def test_empty_sub_functions_returns_empty(self):
        from backend.services.swut_input_adapter import flatten_sub_functions
        bank = self._make_bank({})
        assert flatten_sub_functions(bank) == []

    def test_executed_false_yields_zero_coverage(self):
        from backend.services.swut_input_adapter import flatten_sub_functions
        bank = self._make_bank({"Mod": [("fn_unexec", False), ("fn_exec", True)]})
        result = flatten_sub_functions(bank, component_name="C1")
        unexec = next(fc for fc in result if fc.name == "fn_unexec")
        exec_fc = next(fc for fc in result if fc.name == "fn_exec")
        assert unexec.statement.covered == 0
        assert unexec.statement.total == 1
        assert exec_fc.statement.covered == 1
        assert exec_fc.statement.total == 1

    def test_name_dedup_conflict_warning(self):
        from backend.services.swut_input_adapter import flatten_sub_functions
        bank = self._make_bank({
            "ModA": [("fn_same", True)],
            "ModB": [("fn_same", False)],  # 동일 name — 첫 entry 보존
        })
        warnings: list[str] = []
        result = flatten_sub_functions(bank, out_warnings=warnings)
        assert len(result) == 1
        assert result[0].name == "fn_same"
        assert result[0].statement.covered == 1  # ModA의 첫 entry executed=True 보존
        assert any("dedup 충돌" in w for w in warnings)

    def test_metrics_bank_none_returns_empty(self):
        from backend.services.swut_input_adapter import flatten_sub_functions
        assert flatten_sub_functions(None) == []


# ---------------------------------------------------------------------------
# 라운드 76 — enhance_function_coverage_with_file helper (T1104)
# ---------------------------------------------------------------------------

class TestEnhanceFunctionCoverageWithFile:
    """vcast FunctionCoverage에 c_parser file 정보 주입."""

    def test_normal_matching_injects_file(self):
        from backend.services.swut_input_adapter import (
            enhance_function_coverage_with_file, FunctionCoverage,
        )
        function_rows = [
            FunctionCoverage(unit_id="SwUFn_0101", name="main", file=""),
            FunctionCoverage(unit_id="SwUFn_0102", name="fn_other", file=""),
        ]
        c_map = {
            "main": {"file": "main.c"},
            "fn_other": {"file": "other.c"},
        }
        n = enhance_function_coverage_with_file(function_rows, c_map)
        assert n == 2
        assert function_rows[0].file == "main.c"
        assert function_rows[1].file == "other.c"

    def test_no_matching_keeps_empty(self):
        from backend.services.swut_input_adapter import (
            enhance_function_coverage_with_file, FunctionCoverage,
        )
        function_rows = [
            FunctionCoverage(unit_id="SwUFn_0101", name="vcast_only", file=""),
        ]
        c_map = {"different_fn": {"file": "different.c"}}
        n = enhance_function_coverage_with_file(function_rows, c_map)
        assert n == 0
        assert function_rows[0].file == ""

    def test_partial_matching_only_inject_matched(self):
        from backend.services.swut_input_adapter import (
            enhance_function_coverage_with_file, FunctionCoverage,
        )
        function_rows = [
            FunctionCoverage(unit_id="SwUFn_0101", name="main", file=""),
            FunctionCoverage(unit_id="SwUFn_0102", name="vcast_only", file=""),
        ]
        c_map = {"main": {"file": "main.c"}}
        n = enhance_function_coverage_with_file(function_rows, c_map)
        assert n == 1
        assert function_rows[0].file == "main.c"
        assert function_rows[1].file == ""
