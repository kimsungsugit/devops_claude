"""SwUT 빌더 입력 어댑터.

Coverage Report / SUTR xlsx 생성을 위한 데이터를 두 가지 소스 중 하나에서
통일된 형태로 추출한다.

## 입력 소스 (우선순위)
1. **Jenkins build artifact** (있으면 우선) — 본 라운드에서는 인터페이스만 정의,
   실제 fetch 로직은 별도 작업 (`workflow/vcast_traceability.py` 또는
   `backend/services/jenkins_adapter.py` 확장).
2. **Log folder** (cloudium 또는 local) — VectorCAST SWTE 변종 출력 폴더 구조:
   ```
   <log_root>/v<VER>_<YYMMDD>/
     <PROJECT>_SwUTR_v<VER>_<YYMMDD>.xlsm   (통합 결과 또는 template)
     01.TestCaseDataReport/
       SWTE_<NN>_test_case_data_report.html
     02.ExecutionResultReport/
       SWTE_<NN>_execution_results_report.html
     03.AggregateCoverageReport/
       SWTE_<NN>_aggregate_coverage_report.html
   ```

## 변종 호환성
표준 VectorCAST 출력과 우리 SWTE 출력은 일부 layout이 다르다.
- TestCaseData: 기존 `vcast_parser`로 처리 (이전 라운드 `_read_tc_header`
  dynamic offset patch 적용 완료)
- ExecutionResult / AggregateCoverage: 본 모듈의 lightweight BS4 추출기
  사용 (parser가 기대하는 `<span>...(123/456 100%)</span>` 패턴이 SWTE 변종에
  없어 0건 추출 문제 회피)

## ISO 26262 Tool Qualification
본 어댑터의 출력은 자동 추출 draft. 빌더가 xlsx로 생성할 때
`is_auto_generated=True` 메타데이터 부착 의무.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CoverageStats:
    """Statement/Branch 카운트.

    VectorCAST AggregateCoverage Metrics 표의 한 셀 (예: "69 / 69 (100%)")
    형태를 정규화한 데이터.
    """
    covered: int = 0
    total: int = 0
    coverage_pct: float = 0.0  # 0.0~1.0

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.covered == self.total


@dataclass
class FunctionCoverage:
    """단위 함수(SwUFn_xxxx)별 커버리지 — Coverage Report 3.Coverage 시트의 한 행."""
    unit_id: str = ""  # 예: SwUFn_0101
    name: str = ""      # 예: main
    statement: CoverageStats = field(default_factory=CoverageStats)
    branch: CoverageStats = field(default_factory=CoverageStats)
    mcdc: CoverageStats = field(default_factory=CoverageStats)
    complexity: int = 0


@dataclass
class TestExecution:
    """TC별 실행 결과 — SUTR Test Log 시트의 행."""
    tc_name: str = ""             # 예: SwUFn_0101.001
    component: str = ""           # 예: SysOs_Main
    subprogram: str = ""          # 예: main
    passed: bool = False
    events: list[str] = field(default_factory=list)


@dataclass
class EnvironmentData:
    """1개 SWTE 환경의 모든 데이터."""
    env_name: str = ""            # 예: SWTE_01
    component_name: str = ""      # 예: SysOs_Main
    environment_name: str = ""    # VectorCAST internal env name
    test_cases: dict[str, Any] = field(default_factory=dict)  # tc_name -> TestCaseItem (TCBank.test_cases)
    test_results: dict[str, TestExecution] = field(default_factory=dict)
    function_coverage: list[FunctionCoverage] = field(default_factory=list)
    grand_total: FunctionCoverage = field(default_factory=FunctionCoverage)
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class SwUTSession:
    """Coverage Report / SUTR 빌더의 통합 입력."""
    project_id: str = ""
    version: str = ""              # 예: v2.02_240219
    source_kind: str = ""          # "log_folder" | "jenkins_cache"
    source_path: str = ""
    environments: list[EnvironmentData] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lightweight HTML extractors (SWTE 변종 전용)
# ---------------------------------------------------------------------------

_RE_PCT = re.compile(r"(\d+)\s*/\s*(\d+)\s*\((\d+(?:\.\d+)?)\s*%\)")


def _parse_metric_cell(text: str) -> CoverageStats:
    """`69 / 69 (100%)` 형태 → CoverageStats."""
    if not text:
        return CoverageStats()
    m = _RE_PCT.search(text)
    if not m:
        return CoverageStats()
    covered, total, pct = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return CoverageStats(covered=covered, total=total, coverage_pct=pct / 100.0)


def extract_aggregate_coverage(html_bytes: bytes) -> tuple[list[FunctionCoverage], FunctionCoverage]:
    """SWTE AggregateCoverage HTML → per-function metrics + GRAND TOTALS.

    Returns:
        (functions, grand_total) — functions 리스트와 합산 행.
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for SWTE extractors")
    soup = BeautifulSoup(html_bytes, "html.parser")

    # Metrics h2 섹션의 표 찾기 — "Metrics" 또는 "Statement+Branch" 컬럼 헤더 보유
    table = None
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        # Metrics 표는 "Statement+Branch" 또는 "Statement" 헤더 포함
        if any("Statement" in h for h in headers) and any("Branch" in h for h in headers[:8]):
            table = tbl
            break
        # GRAND TOTALS 행 보유한 표 — fallback
        body_text = tbl.get_text(" ")
        if "GRAND TOTALS" in body_text and ("Statement" in body_text or "Branch" in body_text):
            table = tbl
            break

    if table is None:
        return ([], FunctionCoverage())

    functions: list[FunctionCoverage] = []
    grand_total = FunctionCoverage(unit_id="GRAND_TOTALS", name="GRAND TOTALS")

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 4:
            continue
        first = cells[0].get_text(strip=True)
        if not first or first in ("Unit", "Subprogram", "Complexity"):
            continue

        # 셀 위치는 VectorCAST 표준: Unit/Subprogram/Complexity/Statement+Branch/MC|DC
        # 그러나 SWTE는 두 컬럼만 metric일 수 있어 동적 매핑.
        # 마지막 % 패턴이 있는 모든 셀을 추출하고, 첫 셀은 unit_id 가정.
        metric_cells = [c.get_text(" ", strip=True) for c in cells]
        metrics = [_parse_metric_cell(t) for t in metric_cells if _RE_PCT.search(t)]

        fc = FunctionCoverage(unit_id=first, name=first)
        # Complexity 추출
        try:
            cplx = next(int(t) for t in metric_cells[1:4]
                        if t.isdigit())
            fc.complexity = cplx
        except StopIteration:
            pass
        if len(metrics) >= 1:
            fc.statement = metrics[0]
        if len(metrics) >= 2:
            fc.branch = metrics[1]
        if len(metrics) >= 3:
            fc.mcdc = metrics[2]

        if "GRAND TOTAL" in first.upper():
            grand_total = fc
        else:
            functions.append(fc)

    return (functions, grand_total)


def extract_execution_results(html_bytes: bytes) -> dict[str, TestExecution]:
    """SWTE ExecutionResult HTML → TC별 pass/fail + 이벤트 로그.

    `<h4 class="test-start-header">Start of SwUFn_0101.001</h4>` 같은 패턴
    + 직후 `<h3>Execution Results (PASS)</h3>` 또는 `(FAIL)` 추출.
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for SWTE extractors")
    soup = BeautifulSoup(html_bytes, "html.parser")

    results: dict[str, TestExecution] = {}

    # 패턴 1: <h3 title="Execution Results">...Execution Results (PASS)</h3>
    # 각 testcase 섹션마다 1개씩
    for h3 in soup.find_all("h3", title=re.compile("Execution Results", re.I)):
        text = h3.get_text(" ", strip=True)
        passed = "(PASS)" in text or "PASS" in text and "FAIL" not in text
        # TC 이름은 직후 형제/자식의 'Start of SwUFn_...' h4에서
        tc_name = ""
        # 인접한 다음 형제 또는 sibling 트리 탐색
        for sib in h3.find_all_next(["h4"], limit=5):
            sib_text = sib.get_text(strip=True)
            m = re.match(r"Start of (SwUFn_\d+\.\d+|\S+)", sib_text)
            if m:
                tc_name = m.group(1)
                break
        if tc_name and tc_name not in results:
            results[tc_name] = TestExecution(tc_name=tc_name, passed=passed)
    return results


# ---------------------------------------------------------------------------
# Path-based input
# ---------------------------------------------------------------------------

def _read_via_resolver(resolver: Any, path: str) -> bytes:
    """resolver(local 또는 cloudium) 통해 bytes read."""
    return resolver.read_bytes(path)


def _list_dir_via_resolver(resolver: Any, path: str, pattern: str = "*") -> list[str]:
    return resolver.list_dir(path, pattern=pattern, recursive=False)


def _parse_testcase_data_via_temp(resolver: Any, html_path: str) -> Any:
    """기존 vcast_parser를 임시 파일 거쳐 호출.

    parser가 path 입력만 받으므로 worker bytes를 dump → parse → unlink.
    """
    from backend.services.vcast_parser import (
        ReportType,
        VCASTVersion,
        parse_vcast_report,
    )
    data = _read_via_resolver(resolver, html_path)
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
        tf.write(data)
        tmp = Path(tf.name)
    try:
        return parse_vcast_report(tmp, ReportType.TestCaseData, VCASTVersion.Ver2025)
    finally:
        tmp.unlink(missing_ok=True)


def _extract_env_from_filename(name: str) -> str:
    """`SWTE_01_test_case_data_report.html` → `SWTE_01`."""
    m = re.match(r"(SWTE_\d+)", name)
    return m.group(1) if m else ""


def collect_from_log_folder(
    resolver: Any,
    log_folder: str,
    project_id: str = "",
    version: str | None = None,
    parse_warnings: list[str] | None = None,
) -> SwUTSession:
    """Log 폴더(`.../v<VER>_<DATE>/`)에서 모든 SWTE 환경 데이터 수집.

    Args:
        resolver: file_resolver (LocalFileResolver 또는 CloudiumResolver).
        log_folder: SWTE 출력 root (xlsm + 01/02/03 sub-folder 보유).
        project_id: HDPDM01 등.
        version: log_folder 끝 폴더명 (예: "v2.02_240219"). None이면 path에서 추출.
        parse_warnings: 호출자 전달 list — extract 실패 시 사유 append.

    Returns:
        SwUTSession (environments 채워짐, parse_warnings 누적).
    """
    warnings = parse_warnings if parse_warnings is not None else []
    session = SwUTSession(
        project_id=project_id,
        version=version or Path(log_folder).name,
        source_kind="log_folder",
        source_path=log_folder,
        parse_warnings=warnings,
    )

    # 1) 3 sub-folder 존재 확인
    sub_tc = os.path.join(log_folder, "01.TestCaseDataReport")
    sub_exec = os.path.join(log_folder, "02.ExecutionResultReport")
    sub_cov = os.path.join(log_folder, "03.AggregateCoverageReport")

    for sub_path, label in [
        (sub_tc, "01.TestCaseDataReport"),
        (sub_exec, "02.ExecutionResultReport"),
        (sub_cov, "03.AggregateCoverageReport"),
    ]:
        if not resolver.exists(sub_path):
            warnings.append(f"하위 폴더 미발견: {label}")

    # 2) TestCaseDataReport의 .html 파일들로 env 목록 빌드
    tc_files = _list_dir_via_resolver(resolver, sub_tc, pattern="*.html")
    env_names = sorted({_extract_env_from_filename(Path(f).name)
                        for f in tc_files
                        if _extract_env_from_filename(Path(f).name)})

    # 3) 각 env마다 3 파일 추출
    for env in env_names:
        env_data = EnvironmentData(env_name=env)

        # TestCaseData
        tc_path = os.path.join(sub_tc, f"{env}_test_case_data_report.html")
        try:
            tcbank = _parse_testcase_data_via_temp(resolver, tc_path)
            env_data.component_name = getattr(tcbank, "component_name", "")
            env_data.environment_name = getattr(tcbank, "environment", "")
            env_data.test_cases = dict(getattr(tcbank, "test_cases", {}) or {})
            parse_err = getattr(tcbank, "parse_error", None)
            if parse_err:
                env_data.parse_errors.append(f"TestCaseData: {parse_err}")
        except Exception as e:
            env_data.parse_errors.append(f"TestCaseData: {type(e).__name__}: {e}")

        # ExecutionResult
        exec_path = os.path.join(sub_exec, f"{env}_execution_results_report.html")
        try:
            data = _read_via_resolver(resolver, exec_path)
            env_data.test_results = extract_execution_results(data)
        except Exception as e:
            env_data.parse_errors.append(f"ExecutionResult: {type(e).__name__}: {e}")

        # AggregateCoverage
        cov_path = os.path.join(sub_cov, f"{env}_aggregate_coverage_report.html")
        try:
            data = _read_via_resolver(resolver, cov_path)
            funcs, total = extract_aggregate_coverage(data)
            env_data.function_coverage = funcs
            env_data.grand_total = total
        except Exception as e:
            env_data.parse_errors.append(f"AggregateCoverage: {type(e).__name__}: {e}")

        session.environments.append(env_data)

    if not session.environments:
        warnings.append(f"환경(SWTE_xx) 0건 — '{sub_tc}' 폴더 listing 검증 필요")

    return session


# ---------------------------------------------------------------------------
# Jenkins cache (interface 정의만, 구현은 다음 라운드)
# ---------------------------------------------------------------------------

def collect_from_jenkins_cache(
    project_id: str,
    build_number: int | None = None,
    parse_warnings: list[str] | None = None,
) -> SwUTSession | None:
    """Jenkins build cache에서 SWTE 출력 수집.

    현재 라운드: 인터페이스만 정의. 실제 구현은 ``backend/services/jenkins_adapter.py``
    의 ``scan_jenkins_build_root`` 와 통합 작업으로 다음 라운드 예정.
    """
    warnings = parse_warnings if parse_warnings is not None else []
    warnings.append(
        "Jenkins cache fetcher는 아직 미구현 — log_folder fallback 사용 필요"
    )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_swut_session(
    resolver: Any,
    project_id: str,
    *,
    jenkins_build_number: int | None = None,
    log_folder: str | None = None,
) -> SwUTSession:
    """Jenkins 캐시 우선, 없으면 log_folder fallback.

    Args:
        resolver: file_resolver.
        project_id: 예) "HDPDM01".
        jenkins_build_number: Jenkins build 번호. None이면 latest.
        log_folder: fallback path (`U:\\...\\01.Log\\v<VER>_<DATE>`).

    Returns:
        SwUTSession — environments 채워짐. session.parse_warnings 확인 의무.

    Raises:
        ValueError: 두 입력 모두 미제공 또는 Jenkins/log 둘 다 실패 시.
    """
    warnings: list[str] = []

    # 1) Jenkins 시도
    if jenkins_build_number is not None:
        session = collect_from_jenkins_cache(
            project_id, jenkins_build_number, parse_warnings=warnings,
        )
        if session is not None and session.environments:
            session.parse_warnings = warnings
            return session
        warnings.append("Jenkins cache 실패 — log_folder fallback 시도")

    # 2) log_folder fallback
    if log_folder:
        return collect_from_log_folder(
            resolver, log_folder, project_id=project_id, parse_warnings=warnings,
        )

    raise ValueError(
        "jenkins_build_number 또는 log_folder 둘 중 하나는 반드시 지정해야 합니다"
    )
