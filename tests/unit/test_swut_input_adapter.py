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
    SWTE_LAYOUT,
    VC2025_LAYOUT,
    _detect_log_layout,
    _extract_env_from_filename,
    _norm_env_stem,
    _parse_metric_cell,
    _resolve_report_path,
    collect_swut_session,
    extract_aggregate_coverage,
    extract_execution_results,
    extract_execution_results_with_actual,
)


# ---------------------------------------------------------------------------
# rank3 회귀 — 인접 TC 결과 누설(PASS↔FAIL 오분류) 방지 (index-pairing)
# ---------------------------------------------------------------------------
def test_exec_results_no_adjacent_fail_leak_variant_b():
    """변형 B(h4→h3) + TC1(FAIL)→TC2(PASS) 인접: TC2가 TC1의 FAIL을 상속하면 안 됨.

    과거 sourceline ±20 근사는 TC2.h3_prev(=TC1 FAIL)를 오채택해 TC2를 FAIL로 만들었다.
    """
    html = (
        b"<html><body>"
        b"<h4>Start of SwUFn_0101.001</h4>"
        b"<h3 title='Execution Results'>Execution Results (FAIL)</h3>"
        b"<h4>Start of SwUFn_0102.001</h4>"
        b"<h3 title='Execution Results'>Execution Results (PASS)</h3>"
        b"</body></html>"
    )
    res = extract_execution_results_with_actual(html)
    assert res["SwUFn_0101.001"].passed is False
    assert res["SwUFn_0102.001"].passed is True  # FAIL 누설 없음


def test_exec_results_variant_a_still_correct():
    """변형 A(h3→h4)도 index-pairing으로 정확 — TC1=PASS, TC2=FAIL."""
    html = (
        b"<html><body>"
        b"<h3 title='Execution Results'>Execution Results (PASS)</h3>"
        b"<h4>Start of SwUFn_0201.001</h4>"
        b"<h3 title='Execution Results'>Execution Results (FAIL)</h3>"
        b"<h4>Start of SwUFn_0202.001</h4>"
        b"</body></html>"
    )
    res = extract_execution_results_with_actual(html)
    assert res["SwUFn_0201.001"].passed is True
    assert res["SwUFn_0202.001"].passed is False


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
            merge_function_rows_with_c_parser,
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
# 라운드 89 — VectorCAST 출력 레이아웃 변종 (SWTE / VC2025)
# ---------------------------------------------------------------------------

class TestLogLayout:
    def test_detect_swte_layout(self):
        log = r"C:\fake\rel"
        resolver = _FakeResolver({}, {log, log + r"\01.TestCaseDataReport"})
        assert _detect_log_layout(resolver, log).name == "swte"

    def test_detect_vc2025_layout(self):
        log = r"C:\fake\UT_Report_251104"
        resolver = _FakeResolver({}, {log, log + r"\TestCaseData"})
        warns: list[str] = []
        layout = _detect_log_layout(resolver, log, warns)
        assert layout.name == "vc2025"
        assert any("vc2025" in w for w in warns)

    def test_detect_defaults_to_swte_when_neither(self):
        log = r"C:\fake\empty"
        resolver = _FakeResolver({}, {log})
        # 둘 다 미발견 → SWTE (기존 "하위 폴더 미발견" 흐름에 위임)
        assert _detect_log_layout(resolver, log).name == "swte"

    def test_swte_extract_env_prefix_mode(self):
        # SWTE는 prefix 정규식 — 숫자 뒤 토큰 무시
        assert SWTE_LAYOUT.extract_env(
            "SWTE_01_test_case_data_report.html", "SWTE"
        ) == "SWTE_01"

    def test_vc2025_extract_env_suffix_strip(self):
        # VC2025는 suffix-strip — 숫자 뒤 이름 보존
        assert VC2025_LAYOUT.extract_env(
            "SwUT_01_Lib_sha256_TestCaseDataReport.html", "SWTE"
        ) == "SwUT_01_Lib_sha256"

    def test_vc2025_extract_env_non_matching_returns_empty(self):
        assert VC2025_LAYOUT.extract_env("readme.txt", "SWTE") == ""


class TestNormEnvStem:
    @pytest.mark.parametrize("raw,expected", [
        ("SwUT_11_Lib_SafeWriteQueue_PDS", "swut_11_lib_safewritequeue"),
        ("SwUT_11_Lib_SafeWriteQueue", "swut_11_lib_safewritequeue"),
        ("SwUT_02_DrvIn_Main_PDS", "swut_02_drvin_main"),
        ("Foo_PDS_PDS", "foo"),  # trailing 반복 제거
        ("Foo", "foo"),
    ])
    def test_norm(self, raw, expected):
        assert _norm_env_stem(raw) == expected


class TestResolveReportPath:
    def test_exact_match_returns_exact_no_warning(self):
        folder = r"C:\fake\Aggregate"
        exact = folder + r"\SwUT_01_Foo_AggregateCoverageReport.html"
        resolver = _FakeResolver({exact: b"x"}, {folder})
        warns: list[str] = []
        out = _resolve_report_path(
            resolver, folder, "SwUT_01_Foo",
            VC2025_LAYOUT.cov_suffix, idx_cache={}, out_warnings=warns,
        )
        assert out.replace("/", "\\") == exact
        assert warns == []

    def test_alt_suffix_match_returns_actual_vc2025_aggregate_report(self):
        """KJPDS02 VC2025 logs use _AggregateReport.html without Coverage."""
        folder = r"C:\fake\Aggregate"
        actual = folder + r"\SwIT_SwUFn_0101_AggregateReport.html"
        resolver = _FakeResolver({actual: b"x"}, {folder})
        warns: list[str] = []
        out = _resolve_report_path(
            resolver, folder, "SwIT_SwUFn_0101",
            VC2025_LAYOUT.cov_suffix,
            alt_suffixes=("_AggregateReport.html",),
            idx_cache={}, out_warnings=warns,
        )
        assert out.replace("/", "\\") == actual
        assert warns == []

    def test_pds_mismatch_fuzzy_fallback_with_warning(self):
        # TestCaseData env엔 _PDS, Aggregate 파일엔 _PDS 없음 → 정규화 매칭
        folder = r"C:\fake\Aggregate"
        actual = folder + r"\SwUT_11_Lib_SafeWriteQueue_AggregateCoverageReport.html"
        resolver = _FakeResolver({actual: b"x"}, {folder})
        warns: list[str] = []
        out = _resolve_report_path(
            resolver, folder, "SwUT_11_Lib_SafeWriteQueue_PDS",
            VC2025_LAYOUT.cov_suffix, idx_cache={}, out_warnings=warns,
        )
        assert out.replace("/", "\\") == actual
        assert any("불일치 fallback" in w for w in warns)

    def test_no_candidate_returns_exact_path(self):
        folder = r"C:\fake\Aggregate"
        resolver = _FakeResolver({}, {folder})
        warns: list[str] = []
        out = _resolve_report_path(
            resolver, folder, "SwUT_99_Ghost",
            VC2025_LAYOUT.cov_suffix, idx_cache={}, out_warnings=warns,
        )
        # 후보 0건 → exact 경로 반환 (이후 read에서 FileNotFoundError로 기록)
        assert out.endswith("SwUT_99_Ghost_AggregateCoverageReport.html")
        assert warns == []


class TestCollectVC2025Layout:
    def test_collects_vc2025_with_pds_mismatch(self):
        """VC2025 CamelCase 폴더 + 1 env의 _PDS 파일명 불일치 fallback 통합."""
        log = r"C:\fake\UT_Report_251104"
        tc = log + r"\TestCaseData"
        ex = log + r"\ExecutionResult"
        cov = log + r"\Aggregate"

        files = {
            # env A — 전 폴더 일관
            tc + r"\SwUT_01_Foo_TestCaseDataReport.html":
                _make_tc_html(env="SwUT_01_Foo", component="Foo"),
            ex + r"\SwUT_01_Foo_ExecutionResultReport.html":
                _EXEC_HTML_TEMPLATE.encode("utf-8"),
            cov + r"\SwUT_01_Foo_AggregateReport.html":
                _AGG_HTML_TEMPLATE.encode("utf-8"),
            # env B — TestCaseData만 _PDS, 형제 폴더는 _PDS 없음 (실데이터 패턴)
            tc + r"\SwUT_11_Bar_PDS_TestCaseDataReport.html":
                _make_tc_html(env="SwUT_11_Bar_PDS", component="Bar"),
            ex + r"\SwUT_11_Bar_ExecutionResultReport.html":
                _EXEC_HTML_TEMPLATE.encode("utf-8"),
            cov + r"\SwUT_11_Bar_AggregateCoverageReport.html":
                _AGG_HTML_TEMPLATE.encode("utf-8"),
        }
        dirs = {log, tc, ex, cov}
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="KJPDS02", log_folder=log,
        )
        assert len(session.environments) == 2
        names = {e.env_name for e in session.environments}
        assert names == {"SwUT_01_Foo", "SwUT_11_Bar_PDS"}
        # 두 env 모두 coverage/exec 정상 추출 (fallback 포함)
        for e in session.environments:
            assert len(e.function_coverage) == 2, f"{e.env_name}: {e.parse_errors}"
            assert len(e.test_results) == 2
        # fallback warning 1개 이상 (env B의 3 폴더 중 exec/cov)
        assert any("불일치 fallback" in w for w in session.parse_warnings)


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

    def test_actual_result_composes_nested_array_names(self):
        """VC2025 actual rows keep parent array context instead of bare [0] keys."""
        from backend.services.swut_input_adapter import (
            extract_execution_results_with_actual,
        )

        html = b"""<html><body>
        <h4>Start of SwUFn_0126.001</h4>
        <h3 title="Execution Results">Execution Results (PASS)</h3>
        <table>
          <tr><td class="i2">buf</td><td></td><td></td><td></td></tr>
          <tr>
            <td class="i3">[0]</td><td>unsigned char</td><td>0x0</td>
            <td class="success-marker">&lt;match&gt;</td>
          </tr>
          <tr>
            <td class="i3">[1]</td><td>unsigned char</td><td>0x1</td>
            <td class="success-marker">&lt;match&gt;</td>
          </tr>
        </table>
        <h4>Start of SwUFn_0127.001</h4>
        </body></html>"""

        results = extract_execution_results_with_actual(html)

        assert results["SwUFn_0126.001"].actual_result == {
            "buf[0]": ("0x0", "0x0"),
            "buf[1]": ("0x1", "0x1"),
        }


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


# ---------------------------------------------------------------------------
# B1 — VC2025 exec 폴더명 대체 (KJPDS02 PV 실측 260604: ExecutionResult → Execution)
# ---------------------------------------------------------------------------


def _vc2025_log_folder(
    root: str, exec_dirname: str = "ExecutionResult", include_exec: bool = True,
) -> tuple[dict[str, bytes], set[str]]:
    """VC2025 레이아웃 fixture — exec 폴더명 가변 (B1 대체 후보 검증용)."""
    tc = root + r"\TestCaseData"
    ex = root + "\\" + exec_dirname
    cov = root + r"\Aggregate"
    files = {
        tc + r"\SwUT_01_Foo_TestCaseDataReport.html":
            _make_tc_html(env="SwUT_01_Foo", component="Foo"),
        cov + r"\SwUT_01_Foo_AggregateCoverageReport.html":
            _AGG_HTML_TEMPLATE.encode("utf-8"),
    }
    dirs = {root, tc, cov}
    if include_exec:
        files[ex + r"\SwUT_01_Foo_ExecutionResultReport.html"] = (
            _EXEC_HTML_TEMPLATE.encode("utf-8")
        )
        dirs.add(ex)
    return files, dirs


class TestExecDirAltFallback:
    """B1 — VC2025 레이아웃 실행결과 폴더 대체 후보 (exec_dir_alts)."""

    def test_layout_alt_constants(self):
        """exec_dir_alts 단일 진리원 — VC2025만 ("Execution",), SWTE는 빈 튜플."""
        assert VC2025_LAYOUT.exec_dir == "ExecutionResult"
        assert VC2025_LAYOUT.exec_dir_alts == ("Execution",)
        assert SWTE_LAYOUT.exec_dir_alts == ()

    def test_execution_alt_folder_collected_with_warning(self):
        """KJPDS02 PV 실측: ExecutionResult 미존재 + Execution 존재 → 대체 수집."""
        root = r"C:\fake\1.APP_UT_report_260604"
        files, dirs = _vc2025_log_folder(root, exec_dirname="Execution")
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="KJPDS02", log_folder=root,
        )
        assert len(session.environments) == 1
        env = session.environments[0]
        # 대체 폴더의 ExecutionResult 리포트에서 2 TC (PASS + FAIL) 정상 수집
        assert len(env.test_results) == 2
        passed = sum(1 for r in env.test_results.values() if r.passed)
        assert passed == 1
        assert any(
            "실행결과 폴더 대체 감지" in w and "Execution" in w
            for w in session.parse_warnings
        )
        # 대체 성공 → 미발견 warning 없음
        assert not any("하위 폴더 미발견" in w for w in session.parse_warnings)

    def test_execution_result_primary_unchanged_no_alt_warning(self):
        """기존 HDPDM01 backward compat — ExecutionResult 존재 시 대체 미발동."""
        root = r"C:\fake\UT_Report_251104"
        files, dirs = _vc2025_log_folder(root, exec_dirname="ExecutionResult")
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="HDPDM01", log_folder=root,
        )
        assert len(session.environments) == 1
        assert len(session.environments[0].test_results) == 2
        assert not any(
            "실행결과 폴더 대체 감지" in w for w in session.parse_warnings
        )

    def test_neither_exec_folder_missing_warning(self):
        """ExecutionResult/Execution 둘 다 부재 → 기존 미발견 warning (graceful)."""
        root = r"C:\fake\UT_Report_NOEXEC"
        files, dirs = _vc2025_log_folder(root, include_exec=False)
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="KJPDS02", log_folder=root,
        )
        assert any(
            "하위 폴더 미발견: ExecutionResult" in w
            for w in session.parse_warnings
        )
        assert not any(
            "실행결과 폴더 대체 감지" in w for w in session.parse_warnings
        )
        # env는 tc 파일 기준 수집되나 exec 리포트 부재 → test_results 비어있음
        assert len(session.environments) == 1
        assert session.environments[0].test_results == {}


# ---------------------------------------------------------------------------
# B2 — collect_swut_session(log_folders=...) 다중 폴더 병합 (APP+BOOT 통합 빌드)
# ---------------------------------------------------------------------------

_EXEC_HTML_ONE_TC = """<!DOCTYPE html>
<!-- VectorCAST Report header -->
<html><body>
<!-- ExecutionResults/testcase_header -->
<h3 title="Execution Results">Execution Results (PASS)</h3>
<h4 class="test-start-header">Start of SwUFn_0201.001</h4>
<!-- VectorCAST Report footer -->
</body></html>
"""


def _swte_log_folder(
    root: str, env: str, exec_html: bytes | None = None,
) -> tuple[dict[str, bytes], set[str]]:
    """SWTE 레이아웃 단일 env fixture — B2 다중 폴더 병합 검증용."""
    tc_dir = root + r"\01.TestCaseDataReport"
    ex_dir = root + r"\02.ExecutionResultReport"
    cov_dir = root + r"\03.AggregateCoverageReport"
    files = {
        tc_dir + "\\" + env + "_test_case_data_report.html":
            _make_tc_html(env=env),
        ex_dir + "\\" + env + "_execution_results_report.html":
            exec_html if exec_html is not None
            else _EXEC_HTML_TEMPLATE.encode("utf-8"),
        cov_dir + "\\" + env + "_aggregate_coverage_report.html":
            _AGG_HTML_TEMPLATE.encode("utf-8"),
    }
    return files, {root, tc_dir, ex_dir, cov_dir}


class TestCollectMultiLogFolders:
    """B2 — log_folders 다중 입력 병합 정책 (env 합산 / 중복 first-wins / 우선순위)."""

    def test_two_folders_merged_envs(self):
        """APP+BOOT 시뮬 — env 합산 + source_path ';' join + version 첫 폴더."""
        root_a = r"C:\fakeA\APP_UT_report_260604"
        root_b = r"C:\fakeB\BOOT_UT_report_260604"
        files_a, dirs_a = _swte_log_folder(root_a, "SWTE_01")
        files_b, dirs_b = _swte_log_folder(root_b, "SWTE_02")
        resolver = _FakeResolver({**files_a, **files_b}, dirs_a | dirs_b)
        session = collect_swut_session(
            resolver, project_id="KJPDS02", log_folders=[root_a, root_b],
        )
        assert {e.env_name for e in session.environments} == {"SWTE_01", "SWTE_02"}
        assert session.source_path.split(";") == [root_a, root_b]
        assert session.version == Path(root_a).name
        assert session.source_kind == "log_folder"

    def test_duplicate_env_first_folder_wins_with_warning(self):
        """env_name 중복 — 첫 폴더 우선 + 뒤 항목 skip + 중복 경고 (이중 집계 방지)."""
        root_a = r"C:\fakeA\APP_UT_report_260604"
        root_b = r"C:\fakeB\BOOT_UT_report_260604"
        # 폴더 A exec=2 TC, 폴더 B exec=1 TC — first-wins 식별 마커
        files_a, dirs_a = _swte_log_folder(root_a, "SWTE_01")
        files_b, dirs_b = _swte_log_folder(
            root_b, "SWTE_01", exec_html=_EXEC_HTML_ONE_TC.encode("utf-8"),
        )
        resolver = _FakeResolver({**files_a, **files_b}, dirs_a | dirs_b)
        session = collect_swut_session(
            resolver, project_id="KJPDS02", log_folders=[root_a, root_b],
        )
        assert len(session.environments) == 1
        env = session.environments[0]
        assert env.env_name == "SWTE_01"
        # 첫 폴더(A)의 2 TC 데이터 유지 — 폴더 B(1 TC)는 skip
        assert len(env.test_results) == 2
        assert "SwUFn_0101.001" in env.test_results
        dup_warns = [w for w in session.parse_warnings if "env_name 중복" in w]
        assert len(dup_warns) == 1
        assert "[#2" in dup_warns[0]
        assert "SWTE_01" in dup_warns[0]

    def test_single_log_folder_backward_compat(self):
        """기존 단일 log_folder — 병합/'[#i]' prefix 미적용 (기존 경로 그대로)."""
        root = r"C:\fake\01.Log\v0.01_TEST"
        files, dirs = _swte_log_folder(root, "SWTE_01")
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="HDPDM01", log_folder=root,
        )
        assert len(session.environments) == 1
        assert session.source_path == root
        assert ";" not in session.source_path
        assert not any(w.startswith("[#") for w in session.parse_warnings)

    def test_log_folders_single_item_no_merge_prefix(self):
        """log_folders 1개 — 단일 경로와 동일 동작 (병합/prefix 미적용)."""
        root = r"C:\fake\01.Log\v0.01_TEST"
        files, dirs = _swte_log_folder(root, "SWTE_01")
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="HDPDM01", log_folders=[root],
        )
        assert len(session.environments) == 1
        assert session.source_path == root
        assert not any(w.startswith("[#") for w in session.parse_warnings)

    def test_log_folders_priority_over_log_folder(self):
        """log_folders 비어있지 않으면 log_folder(단일)보다 우선."""
        root_a = r"C:\fakeA\APP_UT_report_260604"
        root_b = r"C:\fakeB\BOOT_UT_report_260604"
        files_a, dirs_a = _swte_log_folder(root_a, "SWTE_01")
        files_b, dirs_b = _swte_log_folder(root_b, "SWTE_02")
        resolver = _FakeResolver({**files_a, **files_b}, dirs_a | dirs_b)
        session = collect_swut_session(
            resolver, project_id="KJPDS02",
            log_folder=root_b, log_folders=[root_a],
        )
        assert session.source_path == root_a
        assert {e.env_name for e in session.environments} == {"SWTE_01"}

    def test_log_folders_empty_falls_back_to_log_folder(self):
        """log_folders=[] (빈 list) → log_folder 단일 fallback."""
        root = r"C:\fake\01.Log\v0.01_TEST"
        files, dirs = _swte_log_folder(root, "SWTE_01")
        resolver = _FakeResolver(files, dirs)
        session = collect_swut_session(
            resolver, project_id="HDPDM01", log_folder=root, log_folders=[],
        )
        assert len(session.environments) == 1
        assert session.source_path == root


class TestAggregateSessionUnmatchedResults:
    """라운드 96-fix W-A — ExecutionResult에만 존재하는 TC의 집계 제외.

    KJPDS02 PV 실측: 'Range' 보조 행 오인 2건 + compound TC 'CTC_*.001' 1건이
    passed에 가산돼 passed(584) > total(581) → Actual Coverage 1.005(>100%)
    가 산출물에 stamp되던 결함. 불변식 passed+failed ≤ total 보장.
    """

    @staticmethod
    def _env_with_unmatched():
        from backend.services.swut_input_adapter import (
            EnvironmentData, ExecutionRow, SwUTSession,
        )
        env = EnvironmentData(
            env_name="SwIT_SwUFn_0104",
            component_name="SwCom_01",
            test_cases={
                "SwIT_SwUFn_0104_01": [object()],
                "SwIT_SwUFn_0104_02": [object()],
            },
            test_results={
                "SwIT_SwUFn_0104_01": ExecutionRow(
                    tc_name="SwIT_SwUFn_0104_01", passed=True),
                "SwIT_SwUFn_0104_02": ExecutionRow(
                    tc_name="SwIT_SwUFn_0104_02", passed=False),
                # TestCaseData에 없는 실행 결과 2건 (보조 행 + compound)
                "Range": ExecutionRow(tc_name="Range", passed=True),
                "CTC_SwIT_SwUFn_0104_01.001": ExecutionRow(
                    tc_name="CTC_SwIT_SwUFn_0104_01.001", passed=True),
            },
        )
        session = SwUTSession(project_id="KJPDS02")
        session.environments.append(env)
        return session

    def test_unmatched_results_excluded_from_pass_fail(self):
        from backend.services.swut_input_adapter import aggregate_session
        session = self._env_with_unmatched()
        agg = aggregate_session(session)
        assert agg["total"] == 2
        assert agg["passed"] == 1
        assert agg["failed"] == 1
        assert agg["tested"] == 2
        assert agg["passed"] + agg["failed"] <= agg["total"]
        assert agg["unmatched_result_tcs"] == [
            ("SwIT_SwUFn_0104", "Range"),
            ("SwIT_SwUFn_0104", "CTC_SwIT_SwUFn_0104_01.001"),
        ]

    def test_unmatched_results_emit_parse_warning_once(self):
        from backend.services.swut_input_adapter import aggregate_session
        session = self._env_with_unmatched()
        aggregate_session(session)
        aggregate_session(session)  # 재호출 — 중복 누적 방지 확인
        warns = [w for w in session.parse_warnings if "[aggregate]" in w]
        assert len(warns) == 1
        assert "Range" in warns[0]

    def test_all_matched_no_warning_backward_compat(self):
        from backend.services.swut_input_adapter import (
            EnvironmentData, ExecutionRow, SwUTSession, aggregate_session,
        )
        env = EnvironmentData(
            env_name="SWTE_01",
            component_name="SysOs_Main",
            test_cases={"SwUFn_0101.001": [object()]},
            test_results={
                "SwUFn_0101.001": ExecutionRow(
                    tc_name="SwUFn_0101.001", passed=True),
            },
        )
        session = SwUTSession(project_id="HDPDM01")
        session.environments.append(env)
        agg = aggregate_session(session)
        assert agg["passed"] == 1 and agg["unmatched_result_tcs"] == []
        assert not [w for w in session.parse_warnings if "[aggregate]" in w]
