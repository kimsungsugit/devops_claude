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
class ExecutionRow:
    """TC별 실행 결과 — SUTR Test Log 시트의 행.

    이름이 ``TestExecution`` 이었으나 pytest의 ``Test`` prefix와 충돌해
    collection warning이 매 라운드 누적되어 ``ExecutionRow`` 로 rename
    (deep-reviewer X5).
    """
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
    test_results: dict[str, ExecutionRow] = field(default_factory=dict)
    function_coverage: list[FunctionCoverage] = field(default_factory=list)
    grand_total: FunctionCoverage = field(default_factory=FunctionCoverage)
    parse_errors: list[str] = field(default_factory=list)
    # 30차 W21: function_id (SwUFn_NNNN) → ASIL 등급 (A/B/C/D/QM) 매핑.
    # router에서 swut_asil_resolver를 호출해 채워 넣음 (default 빈 dict).
    function_asil_map: dict[str, str] = field(default_factory=dict)


@dataclass
class SwUTSession:
    """Coverage Report / SUTR 빌더의 통합 입력."""
    project_id: str = ""
    version: str = ""              # 예: v2.02_240219
    source_kind: str = ""          # "log_folder" | "jenkins_cache"
    source_path: str = ""
    environments: list[EnvironmentData] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


def aggregate_session(session: SwUTSession) -> dict[str, Any]:
    """SwUTSession 의 통합 집계 (Coverage + SUTR 빌더 공통, deep-reviewer W3).

    Keys:
        total/total_tcs (alias) — test_cases 합
        tested — test_results 합
        passed/failed — execution pass 결과
        failed_tcs — (env_name, tc_name) 페어
        not_executed/not_executed_tcs — test_cases - test_results 차집합
        function_count/function_rows — function_coverage 평탄화
        tc_to_components — tc_name → set(component_name)
        deviated — 0 (deviation_generator 결과는 빌더가 별도 주입)
    """
    total = 0
    passed = 0
    failed = 0
    failed_tcs: list[tuple[str, str]] = []
    not_executed_tcs: list[str] = []
    all_functions: list[FunctionCoverage] = []
    tc_to_components: dict[str, set[str]] = {}
    function_asil_map: dict[str, str] = {}  # 30차 W21

    for env in session.environments:
        all_functions.extend(env.function_coverage)
        for tc_name, tc_list in env.test_cases.items():
            total += len(tc_list) if tc_list else 1
            tc_to_components.setdefault(tc_name, set()).add(env.component_name)
        for tc_name, r in env.test_results.items():
            if r.passed:
                passed += 1
            else:
                failed += 1
                failed_tcs.append((env.env_name, tc_name))
        # test_cases 키 - test_results 키 차집합 (실측 미실행)
        tc_keys = set(env.test_cases.keys())
        exec_keys = set(env.test_results.keys())
        not_executed_tcs.extend(sorted(tc_keys - exec_keys))
        # 30차 W21: 환경별 function_asil_map 통합. 동일 function_id가 여러 env에
        # 다르게 매핑된 경우 마지막 값 우선 (실 운영에서는 동일 함수가 다른 ASIL로
        # 등록될 가능성 0 — Hyundai 컨벤션은 함수 ID 글로벌 unique).
        function_asil_map.update(env.function_asil_map)

    tested = passed + failed
    return {
        "total": total,
        "total_tcs": total,  # alias for backward compat
        "tested": tested,
        "passed": passed,
        "failed": failed,
        "failed_tcs": failed_tcs,
        "not_executed_tcs": not_executed_tcs,
        "not_executed": len(not_executed_tcs),
        "function_count": len(all_functions),
        "function_rows": all_functions,
        "tc_to_components": tc_to_components,
        "function_asil_map": function_asil_map,  # 30차 W21
        "deviated": 0,
    }


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


def extract_execution_results(html_bytes: bytes) -> dict[str, ExecutionRow]:
    """SWTE ExecutionResult HTML → TC별 pass/fail + 이벤트 로그.

    `<h4 class="test-start-header">Start of SwUFn_0101.001</h4>` 같은 패턴
    + 직후 `<h3>Execution Results (PASS)</h3>` 또는 `(FAIL)` 추출.
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for SWTE extractors")
    soup = BeautifulSoup(html_bytes, "html.parser")

    results: dict[str, ExecutionRow] = {}

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
            results[tc_name] = ExecutionRow(tc_name=tc_name, passed=passed)
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


# 37차: log_folder 자동 latest release 선택 — `v<버전>_<YYMMDD>` 패턴.
# 사용자가 `01.Log/` 상위 폴더만 지정해도 그 안의 최신 release 폴더 자동 선택.
_RELEASE_FOLDER_RE = re.compile(r"^v[\d.]+_(\d{6,8})(?:[_-].+)?$")


def _resolve_latest_release_folder(
    resolver: Any,
    log_folder: str,
    out_warnings: list[str] | None = None,
) -> str:
    """log_folder 안에 `01.TestCaseDataReport` 가 없으면 `v<버전>_<날짜>` 후보 중
    날짜 suffix 최대값을 가진 디렉토리로 자동 재할당.

    예:
        log_folder = `U:\\...\\01.Log\\`  (사용자가 상위 폴더만 지정)
        → 그 안의 `v2.02_240219 / v2.03_240315 / v2.10_241201` 중 `v2.10_241201` 선택

    동작:
        1. `<log_folder>/01.TestCaseDataReport` exists? → True면 그대로 반환 (case A)
        2. False면 sub 디렉토리 enumerate 시도 — Local resolver는 `os.scandir`
           직접 호출, Cloudium은 list_dir이 파일만 반환하니 지원 안 함 (graceful warning)
        3. 후보 디렉토리 중 `v<버전>_<YYMMDD>` 패턴 매칭 → 날짜 suffix 최대값 선택
        4. 후보 0건 또는 cloudium 한계 시 원본 path 유지 (graceful)

    Args:
        resolver: file_resolver — mode 확인용 (local만 자동 탐색 지원)
        log_folder: 사용자가 입력한 path
        out_warnings: 자동 재할당 사유 누적용

    Returns:
        실제 사용할 log_folder path (자동 선택되면 변경, 아니면 원본)
    """
    # Case A 빠른 경로: sub-folder 이미 존재 → 그대로 사용
    sub_tc = os.path.join(log_folder, "01.TestCaseDataReport")
    try:
        if resolver.exists(sub_tc):
            return log_folder
    except Exception as e:
        # 37차 reviewer W2: resolver.exists 실패 원인을 silent로 삼키지 말 것.
        # cloudium 게이트 OFF / IPC 통신 실패 / path 형식 오류 등을 사용자가 인지하도록
        # warning 누적 후 원본 path 유지 (기존 흐름에 위임).
        if out_warnings is not None:
            out_warnings.append(
                f"resolver.exists() 예외 ({type(e).__name__}: {e}) — "
                "자동 latest 탐색 skip, 원본 경로 유지"
            )
        return log_folder

    # Case B: sub-folder 미존재 → log_folder가 상위 (예: `01.Log/`) 가정.
    # 자동 latest 탐색 시도.
    resolver_mode = getattr(resolver, "mode", "local")
    if resolver_mode != "local":
        # 38차 C2: Cloudium 모드 fallback. list_dir이 파일만 반환하는 한계 회피 —
        # 알려진 패턴(`v*_*`)을 resolver.exists로 brute-force 검사하지 않고,
        # list_dir 결과에 디렉토리가 포함됐는지 시도 (worker 버전이 디렉토리 반환하면 동작).
        # 못 찾으면 graceful warning 유지 (기존 동작).
        try:
            entries = resolver.list_dir(log_folder, pattern="*", recursive=False)
        except Exception as e:  # noqa: BLE001
            if out_warnings is not None:
                out_warnings.append(
                    f"cloudium list_dir 실패 ({type(e).__name__}) — "
                    "자동 latest 탐색 skip, 원본 경로 유지"
                )
            return log_folder

        # 57차 T319 diag — cloudium list_dir 결과 확인
        import logging as _logging
        _diag_logger = _logging.getLogger(__name__)
        _diag_logger.info(
            f"_resolve_latest_release_folder cloudium: log_folder={log_folder!r}, "
            f"list_dir entries={len(entries)}: {entries[:10]}"
        )

        # entries는 절대 경로 list. 각 entry에 대해 `<entry>/01.TestCaseDataReport`
        # 존재 + 이름이 v<버전>_<날짜> 패턴이면 후보.
        candidates_c: list[tuple[str, str]] = []
        for entry_path in entries:
            name = os.path.basename(entry_path.rstrip("/\\"))
            m = _RELEASE_FOLDER_RE.match(name)
            if not m:
                _diag_logger.debug(
                    f"  entry skip (no pattern match): name={name!r}"
                )
                continue
            sub_check = os.path.join(entry_path, "01.TestCaseDataReport")
            try:
                if not resolver.exists(sub_check):
                    _diag_logger.debug(
                        f"  entry skip (sub-dir미발견): {sub_check!r}"
                    )
                    continue
            except Exception as e:  # noqa: BLE001
                _diag_logger.debug(
                    f"  entry skip (exists 예외 {type(e).__name__}): {sub_check!r}"
                )
                continue
            candidates_c.append((m.group(1), entry_path))
        _diag_logger.info(
            f"  candidates_c ({len(candidates_c)}): "
            f"{[(d, os.path.basename(p)) for d, p in candidates_c[:5]]}"
        )

        if not candidates_c:
            if out_warnings is not None:
                out_warnings.append(
                    f"log_folder '{log_folder}'에 01.TestCaseDataReport 없음 — "
                    "cloudium worker가 디렉토리 enum 미지원 또는 v<버전>_<YYMMDD> "
                    "후보 0건. release 폴더 직접 지정 권장"
                )
            return log_folder

        candidates_c.sort(key=lambda x: x[0], reverse=True)
        latest_path = candidates_c[0][1]
        if out_warnings is not None:
            out_warnings.append(
                f"log_folder auto-resolved (cloudium): "
                f"'{os.path.basename(latest_path)}' (날짜 suffix 최대값 / "
                f"{len(candidates_c)}개 후보 중 latest)"
            )
        return latest_path

    # Local 모드: os.scandir 직접 사용 (list_dir은 파일만 반환하므로 우회)
    try:
        candidates: list[tuple[str, str]] = []  # (날짜suffix, path)
        with os.scandir(log_folder) as it:
            for entry in it:
                if not entry.is_dir():
                    continue
                m = _RELEASE_FOLDER_RE.match(entry.name)
                if not m:
                    continue
                # 추가 검증: 후보 디렉토리에 `01.TestCaseDataReport` 존재해야 진짜 release
                if not os.path.isdir(os.path.join(entry.path, "01.TestCaseDataReport")):
                    continue
                date_suffix = m.group(1)
                candidates.append((date_suffix, entry.path))

        if not candidates:
            if out_warnings is not None:
                out_warnings.append(
                    f"log_folder '{log_folder}'에 01.TestCaseDataReport 없음 — "
                    f"v<버전>_<YYMMDD> 패턴 sub 폴더도 미발견. 사용자 입력 경로 확인 필요"
                )
            return log_folder

        # 37차 reviewer W1: 날짜 suffix lexical 정렬은 **동일 자리수 끼리만** 날짜
        # 순서와 일치. YYMMDD (6자리) 끼리 또는 YYYYMMDD (8자리) 끼리는 정확하나
        # 6/8 혼재 시 lexical 정렬 부정확 — 실 환경은 6자리 통일 가정. 혼재 감지 시
        # 사용자에게 명시 warning.
        suffix_lengths = {len(s) for s, _ in candidates}
        if len(suffix_lengths) > 1 and out_warnings is not None:
            out_warnings.append(
                f"날짜 suffix 자리수 혼재 감지 ({sorted(suffix_lengths)}) — "
                "lexical 정렬이 날짜 순서와 불일치 가능. 실 환경 폴더 명명 통일 권장"
            )
        candidates.sort(key=lambda x: x[0], reverse=True)
        latest_path = candidates[0][1]
        latest_name = os.path.basename(latest_path)
        if out_warnings is not None:
            out_warnings.append(
                f"log_folder auto-resolved: '{latest_name}' (날짜 suffix 최대값 / "
                f"{len(candidates)}개 후보 중 latest)"
            )
        return latest_path
    except (OSError, PermissionError) as e:
        if out_warnings is not None:
            out_warnings.append(
                f"log_folder 자동 탐색 실패 ({type(e).__name__}): {e} — 원본 경로 유지"
            )
        return log_folder


def preview_release_candidates(
    resolver: Any,
    log_folder: str,
) -> dict[str, Any]:
    """38차 W4 — frontend dry-run preview용.

    `_resolve_latest_release_folder`를 호출하되 빌드 안 하고 후보 list + 선택 결과만
    반환. 사용자가 빌드 전에 어떤 release가 자동 선택될지 확인 가능.

    Args:
        resolver: file_resolver.
        log_folder: 사용자 입력 path.

    Returns:
        {
          "input_log_folder": str,
          "resolved_log_folder": str,
          "auto_resolved": bool,
          "candidates": [{"name": str, "date_suffix": str, "is_latest": bool}, ...],
          "warnings": [str, ...],
        }
    """
    warnings: list[str] = []
    resolved = _resolve_latest_release_folder(resolver, log_folder, out_warnings=warnings)
    auto_resolved = resolved != log_folder

    # 후보 list 재수집 — 38차 reviewer W3 fix: Case A에서는 부모 dir scan하지 않음
    # (release 폴더 직접 지정한 사용자에게 형제 release들이 후보로 노출되면 혼란).
    # Case A는 candidates 비움 — auto_resolved=False 의미가 "release 폴더 그대로 사용".
    candidates: list[dict[str, Any]] = []
    resolver_mode = getattr(resolver, "mode", "local")
    if resolver_mode == "local" and auto_resolved:
        # Case B만 — log_folder가 상위 폴더이고 안에 release 후보 있음을 의미
        try:
            scan_root = log_folder
            if os.path.isdir(scan_root):
                with os.scandir(scan_root) as it:
                    raw: list[tuple[str, str]] = []
                    for entry in it:
                        if not entry.is_dir():
                            continue
                        m = _RELEASE_FOLDER_RE.match(entry.name)
                        if not m:
                            continue
                        if not os.path.isdir(os.path.join(entry.path, "01.TestCaseDataReport")):
                            continue
                        raw.append((m.group(1), entry.name))
                    raw.sort(key=lambda x: x[0], reverse=True)
                    for i, (date_suffix, name) in enumerate(raw):
                        candidates.append({
                            "name": name,
                            "date_suffix": date_suffix,
                            "is_latest": i == 0,
                        })
        except (OSError, PermissionError) as e:
            warnings.append(f"preview 후보 enum 실패 ({type(e).__name__}): {e}")

    return {
        "input_log_folder": log_folder,
        "resolved_log_folder": resolved,
        "auto_resolved": auto_resolved,
        "candidates": candidates,
        "warnings": warnings,
    }


def _extract_env_from_filename(name: str, *, env_prefix: str = "SWTE") -> str:
    """`<env_prefix>_NN_test_case_data_report.html` → `<env_prefix>_NN`.

    Args:
        env_prefix: SwUT="SWTE" (VectorCAST 환경 명명) / SwIT="SwITC" (Integration TC).
            기본값은 SwUT 명명 — backward compat.

    예:
        SwUT: `SWTE_01_test_case_data_report.html` → `SWTE_01`
        SwIT: `SwITC_21_test_case_data_report.html` → `SwITC_21` (36-fix)
    """
    m = re.match(rf"({re.escape(env_prefix)}_\d+)", name)
    return m.group(1) if m else ""


def collect_from_log_folder(
    resolver: Any,
    log_folder: str,
    project_id: str = "",
    version: str | None = None,
    parse_warnings: list[str] | None = None,
    allowed_roots: list[str] | None = None,
    *,
    env_prefix: str = "SWTE",
) -> SwUTSession:
    """Log 폴더(`.../v<VER>_<DATE>/`)에서 모든 환경 데이터 수집.

    Args:
        resolver: file_resolver (LocalFileResolver 또는 CloudiumResolver).
        log_folder: 출력 root (xlsm + 01/02/03 sub-folder 보유).
        project_id: HDPDM01 등.
        version: log_folder 끝 폴더명 (예: "v2.02_240219"). None이면 path에서 추출.
        parse_warnings: 호출자 전달 list — extract 실패 시 사유 append.
        allowed_roots: 신뢰 가능한 root prefix 화이트리스트 — endpoint 노출 시점에
            의무 주입 (deep-reviewer 시나리오 B / path traversal 방어).
            ``None`` 이면 검증 skip (CLI/내부 호출 가정).
        env_prefix: 환경 명명 prefix — SwUT="SWTE" (default), SwIT="SwITC" (36-fix).
            html 파일명 `<env_prefix>_NN_*.html` 매칭에 사용.

    Raises:
        ValueError: allowed_roots 지정 시 log_folder가 prefix에 속하지 않으면 거부.

    Returns:
        SwUTSession (environments 채워짐, parse_warnings 누적).
    """
    # deep-reviewer 시나리오 B: path traversal 방어 — endpoint 노출 시 의무.
    if allowed_roots is not None:
        from pathlib import Path as _P
        abs_log = str(_P(log_folder).resolve()).replace("\\", "/").lower()
        ok = False
        for root in allowed_roots:
            abs_root = str(_P(root).resolve()).replace("\\", "/").lower()
            if abs_log.startswith(abs_root.rstrip("/") + "/") or abs_log == abs_root:
                ok = True
                break
        if not ok:
            raise ValueError(
                f"log_folder '{log_folder}' is not within allowed_roots {allowed_roots}"
            )

    warnings = parse_warnings if parse_warnings is not None else []

    # 37차: log_folder가 `01.Log/` 같은 상위 폴더면 자동으로 latest release 디렉토리
    # (`v<버전>_<YYMMDD>` 패턴 중 날짜 suffix 최대값) 선택. Case A (사용자가 release
    # 폴더 직접 지정)면 그대로 통과 — backward compat.
    input_log_folder = log_folder
    log_folder = _resolve_latest_release_folder(resolver, log_folder, out_warnings=warnings)

    # 57차 T319 diag — release folder 자동 선택 결과 + sub-folder 존재 여부
    import logging as _logging
    _diag_logger = _logging.getLogger(__name__)
    _diag_logger.info(
        f"collect_from_log_folder diag: input={input_log_folder!r}, "
        f"resolved_release={log_folder!r}, env_prefix={env_prefix!r}"
    )

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
            _diag_logger.warning(f"collect_from_log_folder: 하위 폴더 미발견 {sub_path!r}")
        else:
            _diag_logger.info(f"collect_from_log_folder: 하위 폴더 존재 {sub_path!r}")

    # 2) TestCaseDataReport의 .html 파일들로 env 목록 빌드
    tc_files = _list_dir_via_resolver(resolver, sub_tc, pattern="*.html")
    _diag_logger.info(
        f"collect_from_log_folder: list_dir({sub_tc!r}, *.html) → "
        f"{len(tc_files)} files: {tc_files[:5]}"
    )
    env_names = sorted({
        _extract_env_from_filename(Path(f).name, env_prefix=env_prefix)
        for f in tc_files
        if _extract_env_from_filename(Path(f).name, env_prefix=env_prefix)
    })
    _diag_logger.info(
        f"collect_from_log_folder: env_names ({len(env_names)}) = {env_names[:10]}"
    )

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
        warnings.append(
            f"환경({env_prefix}_xx) 0건 — '{sub_tc}' 폴더 listing 검증 필요"
        )

    return session


# ---------------------------------------------------------------------------
# Jenkins cache (interface 정의만, 구현은 다음 라운드)
# ---------------------------------------------------------------------------

def collect_from_jenkins_cache(
    resolver: Any,
    project_id: str,
    cache_root: str,
    build_number: int | None = None,
    parse_warnings: list[str] | None = None,
    allowed_roots: list[str] | None = None,
    *,
    env_prefix: str = "SWTE",
) -> SwUTSession | None:
    """Jenkins build cache에서 SWTE 출력 수집 (T140 — 8차 라운드).

    ``backend/services/jenkins_adapter.scan_jenkins_build_root`` 로 build root를
    스캔하면 html_files list가 반환된다. 본 함수는 그 결과를 SWTE 환경
    (TestCaseData/ExecutionResult/AggregateCoverage 3 파일) 으로 그룹핑해
    ``log_folder`` 흐름과 동일한 변환 layer로 SwUTSession 을 구성한다.

    Args:
        resolver: file_resolver — 일반적으로 local (Jenkins cache는 local 디렉토리).
        project_id: 예) "HDPDM01".
        cache_root: Jenkins build cache root (예: ``.devops_pro_cache/jenkins``).
        build_number: Jenkins build 번호. None이면 ``latest`` 폴더 시도.
        parse_warnings: 호출자 전달 — 빈 환경 / scan 실패 사유 누적.
        allowed_roots: path traversal 방어 (endpoint 노출 시 의무).

    Returns:
        ``SwUTSession`` (환경 정상 수집) 또는 ``None`` (cache root 미발견 등).
    """
    import os
    import re
    from pathlib import Path as _P

    warnings = parse_warnings if parse_warnings is not None else []

    # T140 path traversal 방어
    if allowed_roots is not None:
        abs_cache = str(_P(cache_root).resolve()).replace("\\", "/").lower()
        ok = False
        for root in allowed_roots:
            abs_root = str(_P(root).resolve()).replace("\\", "/").lower()
            if abs_cache.startswith(abs_root.rstrip("/") + "/") or abs_cache == abs_root:
                ok = True
                break
        if not ok:
            raise ValueError(
                f"cache_root '{cache_root}' is not within allowed_roots {allowed_roots}"
            )

    if not os.path.isdir(cache_root):
        warnings.append(f"Jenkins cache_root 미발견: {cache_root}")
        return None

    # build_root 결정 — <cache_root>/<project_id>/<build_number>
    project_dir = os.path.join(cache_root, project_id)
    if not os.path.isdir(project_dir):
        warnings.append(f"Jenkins project_dir 미발견: {project_dir}")
        return None

    if build_number is not None:
        build_root = os.path.join(project_dir, str(build_number))
    else:
        # latest: 숫자 폴더 중 가장 큰 번호
        candidates = [
            d for d in os.listdir(project_dir)
            if d.isdigit() and os.path.isdir(os.path.join(project_dir, d))
        ]
        if not candidates:
            warnings.append(f"Jenkins build 폴더 0개 in {project_dir}")
            return None
        build_root = os.path.join(project_dir, max(candidates, key=int))

    if not os.path.isdir(build_root):
        warnings.append(f"Jenkins build_root 미발견: {build_root}")
        return None

    # jenkins_adapter.scan_jenkins_build_root — html 파일 enumerate
    try:
        from backend.services.jenkins_adapter import scan_jenkins_build_root
        scan = scan_jenkins_build_root(_P(build_root))
    except Exception as e:
        warnings.append(f"scan_jenkins_build_root 실패: {type(e).__name__}: {e}")
        return None

    html_files = scan.get("html_files") or []
    # 36-fix: env_prefix kwarg 동적 — SwUT="SWTE", SwIT="SwITC"
    env_re = re.compile(rf"{re.escape(env_prefix)}_\d+")
    env_groups: dict[str, dict[str, str]] = {}
    for f in html_files:
        name = _P(f).name
        m = env_re.match(name)
        if not m:
            continue
        env = m.group(0)
        if "test_case_data" in name:
            kind = "tc"
        elif "execution_results" in name:
            kind = "exec"
        elif "aggregate_coverage" in name:
            kind = "cov"
        else:
            continue
        env_groups.setdefault(env, {})[kind] = f

    if not env_groups:
        warnings.append(
            f"Jenkins build_root에서 {env_prefix}_xx html 파일 0건: {build_root}"
        )
        return None

    session = SwUTSession(
        project_id=project_id,
        version=f"jenkins-build-{build_number}" if build_number else "jenkins-latest",
        source_kind="jenkins_cache",
        source_path=build_root,
        parse_warnings=warnings,
    )

    # 각 환경마다 3 파일 변환 — log_folder 흐름과 동일 layer 사용
    for env_name, kinds in sorted(env_groups.items()):
        env_data = EnvironmentData(env_name=env_name)

        # TestCaseData
        tc_path = kinds.get("tc")
        if tc_path:
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
        exec_path = kinds.get("exec")
        if exec_path:
            try:
                with open(exec_path, "rb") as fh:
                    env_data.test_results = extract_execution_results(fh.read())
            except Exception as e:
                env_data.parse_errors.append(f"ExecutionResult: {type(e).__name__}: {e}")

        # AggregateCoverage
        cov_path = kinds.get("cov")
        if cov_path:
            try:
                with open(cov_path, "rb") as fh:
                    funcs, total = extract_aggregate_coverage(fh.read())
                env_data.function_coverage = funcs
                env_data.grand_total = total
            except Exception as e:
                env_data.parse_errors.append(f"AggregateCoverage: {type(e).__name__}: {e}")

        session.environments.append(env_data)

    return session


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_swut_session(
    resolver: Any,
    project_id: str,
    *,
    jenkins_build_number: int | None = None,
    cache_root: str = "",
    log_folder: str | None = None,
    allowed_roots: list[str] | None = None,
    env_prefix: str = "SWTE",
) -> SwUTSession:
    """Jenkins 캐시 우선, 없으면 log_folder fallback.

    Args:
        resolver: file_resolver.
        project_id: 예) "HDPDM01".
        jenkins_build_number: Jenkins build 번호. None이면 latest.
        log_folder: fallback path (`U:\\...\\01.Log\\v<VER>_<DATE>`).
        env_prefix: 환경 명명 prefix — SwUT="SWTE" (default), SwIT="SwITC" (36-fix).
            html 파일명 `<env_prefix>_NN_*.html` 매칭에 사용. SwIT는
            `swit_input_adapter.collect_swit_session`에서 "SwITC" 전달.

    Returns:
        SwUTSession — environments 채워짐. session.parse_warnings 확인 의무.

    Raises:
        ValueError: 두 입력 모두 미제공 또는 Jenkins/log 둘 다 실패 시.
    """
    warnings: list[str] = []

    # 1) Jenkins 시도 (cache_root 제공 시)
    if jenkins_build_number is not None and cache_root:
        session = collect_from_jenkins_cache(
            resolver, project_id, cache_root,
            build_number=jenkins_build_number,
            parse_warnings=warnings, allowed_roots=allowed_roots,
            env_prefix=env_prefix,
        )
        if session is not None and session.environments:
            session.parse_warnings = warnings
            return session
        warnings.append("Jenkins cache 실패 — log_folder fallback 시도")

    # 2) log_folder fallback
    if log_folder:
        return collect_from_log_folder(
            resolver, log_folder, project_id=project_id,
            parse_warnings=warnings, allowed_roots=allowed_roots,
            env_prefix=env_prefix,
        )

    raise ValueError(
        "jenkins_build_number 또는 log_folder 둘 중 하나는 반드시 지정해야 합니다"
    )
