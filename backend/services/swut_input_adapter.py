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
    """단위 함수(SwUFn_xxxx)별 커버리지 — Coverage Report 3.Coverage 시트의 한 행.

    59차 F4-C 신규: ``function_calls_coverage`` — KJPDS02 v1.01 양식의 row 6
    'Function Calls' 별도 metric. v1.01 양식은 Functions / Function Calls 2개
    coverage를 분리해 표시 (row 5 Functions Total/Fail/Exception/Coverage +
    row 6 Function Calls 동일 4 metric). v2.02/v3.01 양식은 단일 Coverage라
    빈 CoverageStats default → backward-compat.
    """
    unit_id: str = ""  # 예: SwUFn_0101
    name: str = ""      # 예: main
    statement: CoverageStats = field(default_factory=CoverageStats)
    branch: CoverageStats = field(default_factory=CoverageStats)
    mcdc: CoverageStats = field(default_factory=CoverageStats)
    complexity: int = 0
    # 59차 F4-C 신규 — KJPDS02 v1.01 양식 row 6 'Function Calls' coverage.
    # v2.02/v3.01 양식에서는 빈 CoverageStats (default) — writer가 skip.
    function_calls_coverage: CoverageStats = field(default_factory=CoverageStats)
    # 라운드 76 T1103 신규 — c_parser file basename (예: "bats.c").
    # vcast 추출은 component 단위 (component_name만)이라 file 정보 없음. c_parser
    # merge dedup key `(name, file)` 정확성 향상용. enhance_function_coverage_with_file
    # helper가 c_function_map 매칭으로 주입. 빈 string이면 dedup file=""로 fallback.
    file: str = ""
    # 라운드 77 T1201 신규 — vcast 함수의 소속 component name 추적.
    # 라운드 76 fix #4 후 extract_aggregate_coverage가 current_component 추적하나
    # FunctionCoverage에 저장 안 함 → 4.Coverage C3 'Component' stamp 부정확
    # (R10 C3='g_SysOs_WdiCtrl' anomaly). vcast row: HTML table의 component name
    # (예: 'SysOs_Main'). sub_functions: parent module name. c_parser only: 빈 string
    # (fc.file basename로 대체). backward-compat default `""`.
    component_name: str = ""


@dataclass
class ExecutionRow:
    """TC별 실행 결과 — SUTR Test Log 시트의 행.

    이름이 ``TestExecution`` 이었으나 pytest의 ``Test`` prefix와 충돌해
    collection warning이 매 라운드 누적되어 ``ExecutionRow`` 로 rename
    (deep-reviewer X5).

    58차 F1: `actual_result` 신규 필드 — VectorCAST ExecutionResult.html에서
    BeautifulSoup으로 직접 추출한 variable → (actual, expected) Dict. SUTR Test
    Log Z~AI 컬럼 stamp source. `vcast_parser.parse_execution_result` 자체 결함
    (line 451-454 nested loop self-marker) 우회.
    """
    tc_name: str = ""             # 예: SwUFn_0101.001
    component: str = ""           # 예: SysOs_Main
    subprogram: str = ""          # 예: main
    passed: bool = False
    events: list[str] = field(default_factory=list)
    # 58차 F1 신규 — VectorCAST 실측 actual + expected pairs.
    # key=variable name, value=(actual_value, expected_value).
    actual_result: dict[str, tuple[str, str]] = field(default_factory=dict)
    # 59차 F4-B 신규 — step별 actual/expected dict list. 회사 v1.01 KJPDS02 양식
    # 호환 인프라. VectorCAST HTML이 ``Iteration N`` 라벨로 step 분리하면 채움.
    # HDPDM01 fixture에는 미존재 → empty (TC suffix .001/.002/...로 step 효과).
    actual_result_steps: list[dict[str, tuple[str, str]]] = field(default_factory=list)


@dataclass
class EnvironmentData:
    """1개 SWTE 환경의 모든 데이터."""
    env_name: str = ""            # 예: SWTE_01
    component_name: str = ""      # 예: SysOs_Main
    environment_name: str = ""    # VectorCAST internal env name
    test_cases: dict[str, Any] = field(default_factory=dict)  # tc_name -> TestCaseItem (TCBank.test_cases)
    test_results: dict[str, ExecutionRow] = field(default_factory=dict)
    # 57차 T321 — vcast_parser TCBank.test_results carry forward (actual_result 포함).
    # SUTR Test Log Z~AI 컬럼 Actual stamp용 — extract_execution_results는 pass/fail만
    # 추출하므로 별도 source 필요.
    tc_result_items: dict[str, list] = field(default_factory=dict)  # tc_name -> List[TestResultItem]
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
    # 라운드 73 T812/T814 — C source parse 결과 (옵션). router/poc가 parse_c_project
    # 결과를 unit_id → dict 형태로 채워 넣음. _write_consistency_sheet가 signature /
    # comment_desc / file 등 stamp용으로 활용.
    # value dict 필드: name, signature, file, comment_desc, comment_asil, comment_params,
    #                   comment_return, calls (list), used_globals (list)
    c_function_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 라운드 73 T815 — SwUDS docx parse 결과 (옵션). function_id → dict 형태.
    # value dict 필드: heading_text, description, asil
    swuds_function_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 라운드 80 T1406 — ISO 26262 추적성 체인 (SRS/SDS/SUDS) ASIL 매핑 (옵션).
    # iso26262_doc_asil_extractor로 채워짐. _write_test_log fallback chain에서 사용.
    function_asil_from_suds: dict[str, str] = field(default_factory=dict)   # 'SwUFn_0101' → 'A'
    component_asil_from_sds: dict[str, str] = field(default_factory=dict)   # 'SwCom_01' / 'System OS' → 'A'
    function_asil_from_srs: dict[str, str] = field(default_factory=dict)    # 'g_DoorState' → 'A' (보조)
    # 라운드 85 T1902 — SUDS docx 함수명↔SwUFn reverse map (fc.unit_id 함수명 ↔
    # SUDS SwUFn ASIL chain 완성용). 라이브 v1.07 진단 unique 440건.
    function_name_to_swufn_from_suds: dict[str, str] = field(default_factory=dict)  # 'main' → 'SwUFn_0101'


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

    F6 자체평가 Round 1 W2 주의 (caller 계약):
        반환 dict의 `function_rows` list는 **session.environments[*].function_coverage
        의 reference** (extend로 평탄화만, copy 안 함). caller가 fc 객체를 mutate
        하면 (예: F6-C `fc.function_calls_coverage = ...`) **session 객체 본체에
        반영**. 매 build마다 fresh session을 만들면 영향 없음 (현재 router 패턴).
        향후 session caching/재사용 도입 시 silent regression 위험 — caller에서
        `dataclasses.replace(fc, ...)` + 새 list 구성 패턴 필요.

    F6 자체평가 Round 2 W8 주의 (nested mutation):
        `dataclasses.replace(fc, ...)`로 새 FunctionCoverage를 만들어도, nested
        CoverageStats (`statement`/`branch`/`mcdc`/`function_calls_coverage`)는
        명시적으로 교체된 필드 외에는 **동일 reference 복사**. 따라서 downstream
        writer가 nested CoverageStats 객체를 mutate하면 session으로 leak.
        현재 모든 writer는 read-only (cell에 값 stamp만) — 안전. 향후 변경 시
        반드시 nested 객체도 `dataclasses.replace` 적용 의무.
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
        # 라운드 80 T1408 — ISO 26262 추적성 체인 ASIL maps (Coverage 시트 fallback용).
        "function_asil_from_suds": dict(getattr(session, "function_asil_from_suds", {}) or {}),
        "component_asil_from_sds": dict(getattr(session, "component_asil_from_sds", {}) or {}),
        "function_asil_from_srs": dict(getattr(session, "function_asil_from_srs", {}) or {}),
        # 라운드 85 T1902 — SUDS reverse map (함수명→SwUFn).
        "function_name_to_swufn_from_suds": dict(getattr(session, "function_name_to_swufn_from_suds", {}) or {}),
        "deviated": 0,
    }


def enhance_function_coverage_with_file(
    function_rows: list[FunctionCoverage],
    c_function_map: dict[str, dict[str, Any]] | None,
) -> int:
    """라운드 76 T1103: vcast FunctionCoverage에 c_parser file 정보 주입.

    vcast `function_rows`는 `file` 정보가 빈 string (vcast HTML이 component 단위
    추출이라 component_name만 보유). `merge_function_rows_with_c_parser`의 dedup
    key `(name, file)` 2-tuple이 vcast 측에서 file=""라 모든 c_parser 함수가
    c_parser-only로 추가되는 결함 (라운드 74 롤백 사유). 본 helper로 vcast
    function의 name이 c_function_map에 매칭되면 c_entry.file을 fc.file에 주입 →
    dedup 정확 매칭.

    Args:
        function_rows: vcast FunctionCoverage list (mutate).
        c_function_map: c_parser 결과 dict (name → CFunction dict).

    Returns:
        file 주입된 row 수.

    backward-compat:
        c_function_map None/empty → 변경 0 (vcast 그대로).
    """
    if not c_function_map:
        return 0
    enhanced = 0
    for fc in function_rows:
        if fc.file:
            continue  # 이미 file 정보 있음
        c_entry = c_function_map.get(fc.name) or c_function_map.get(fc.unit_id)
        if c_entry and c_entry.get("file"):
            fc.file = c_entry["file"]
            enhanced += 1
    return enhanced


def merge_function_rows_with_c_parser(
    agg: dict[str, Any],
    c_function_map: dict[str, dict[str, Any]] | None,
    *,
    out_warnings: list[str] | None = None,
) -> list[FunctionCoverage]:
    """라운드 74 T905 — c_parser primary 함수 분해.

    vcast function_rows (HDPDM01 ~60 함수)와 c_parser CFunction map (~317 함수)을
    union dedup. dedup key는 ``(name, file)`` 2-tuple — 동명 함수가 다른 file에 있으면
    별도 entry. vcast에 없는 c_parser only 함수는 빈 CoverageStats + 표시 flag로
    추가.

    Args:
        agg: aggregate_session 결과 dict.
        c_function_map: session.c_function_map (None이면 vcast row 그대로 반환).
        out_warnings: 매칭 충돌 / merge 통계 누적.

    Returns:
        merged list[FunctionCoverage] — vcast rows 먼저, c_parser only 뒤. 추가된
        c_parser only row는 `unit_id`에 ``SwUFn_C_<index>`` 자동 생성 prefix (vcast
        unit_id와 명시적 구분 — audit reviewer 식별 가능).

    audit policy:
        - vcast row는 그대로 (실측 coverage 100% 유지).
        - c_parser only row는 statement/branch CoverageStats(0, 0, 0.0) 빈 셀 +
          comment_asil 우선 매핑 (function_asil_map에 자동 등록).

    backward-compat:
        c_function_map None / empty → 빈 list union 결과로 vcast rows 그대로 반환.
    """
    existing_rows: list[FunctionCoverage] = list(agg.get("function_rows") or [])
    if not c_function_map:
        return existing_rows

    # vcast rows의 (name, file) set 구축 — file은 c_parser에만 있어 vcast는 'unknown'
    existing_keys: set[tuple[str, str]] = set()
    for fc in existing_rows:
        # vcast unit_id가 SwUFn_NNNN 또는 component_name 형식. name으로만 매칭 시도.
        existing_keys.add((fc.name or fc.unit_id, ""))
        existing_keys.add((fc.name or fc.unit_id, fc.name or ""))  # fallback

    merged = list(existing_rows)
    c_parser_only_count = 0
    next_idx = 9000  # vcast SwUFn_0101 등과 명시적 구분 (9000번대)
    for c_name, c_fn in c_function_map.items():
        c_file = c_fn.get("file") or ""
        key_a = (c_name, c_file)
        key_b = (c_name, "")
        if key_a in existing_keys or key_b in existing_keys:
            continue
        # c_parser only — 빈 CoverageStats + SwUFn_C_<index> unit_id 자동 생성
        # 라운드 76 자체평가 fix — file 정보 주입 (audit reviewer 시인성).
        # 라운드 77 T1203 — component_name = file basename(.c 제외) — vcast component
        # 와 동일 의미 매칭. 'Cpu.c' → 'Cpu'.
        from pathlib import Path as _PathHere
        c_comp = _PathHere(c_file).stem if c_file else ""
        fc = FunctionCoverage(
            unit_id=f"SwUFn_C_{next_idx}",
            name=c_name,
            file=c_file,
            component_name=c_comp,
            statement=CoverageStats(0, 0, 0.0),
            branch=CoverageStats(0, 0, 0.0),
            mcdc=CoverageStats(0, 0, 0.0),
            complexity=0,
        )
        merged.append(fc)
        existing_keys.add(key_a)
        next_idx += 1
        c_parser_only_count += 1

        # R1 mitigation — c_parser comment_asil를 function_asil_map에 자동 등록.
        c_asil = (c_fn.get("comment_asil") or "").strip().upper()
        if c_asil in {"A", "B", "C", "D", "QM"}:
            agg.setdefault("function_asil_map", {})[fc.unit_id] = c_asil

    if out_warnings is not None and c_parser_only_count > 0:
        out_warnings.append(
            f"[merge] c_parser only 함수 {c_parser_only_count}개 추가 stamp "
            f"(SwUFn_C_9000~ unit_id). coverage 미실측 — audit reviewer 수동 확인 의무."
        )

    return merged


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

    # 라운드 76 자체평가 fix #4 — vcast HTML table 구조:
    #   R0: header (Unit/Subprogram/Complexity/Statements/Branches)
    #   R1: 'SysEepromCtrl_PDS' / 'g_SysEepromCtrl_Main' / '9' / '29/29 (100%)' / '11/11 (100%)'
    #   R2: ''                  / 'g_SysEepromCtrl_Diag' / '6' / '20/20 (100%)' / '8/8 (100%)'
    #   ... (R2~Rn: 첫 cell 빈 — 같은 component 안 다른 함수)
    # 이전 코드는 `if not first: continue`로 빈 first cell row 모두 skip → 30 함수 중 1개만 추출.
    # fix: 빈 first cell이면 이전 component_name 유지 + second cell (Subprogram)이 함수명.
    rows = table.find_all("tr")
    current_component = ""
    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 4:
            continue
        first = cells[0].get_text(strip=True)
        second = cells[1].get_text(strip=True) if len(cells) > 1 else ""

        # 헤더 row skip (회사 vcast 양식 column 라벨)
        if first in ("Unit", "Subprogram", "Complexity"):
            continue

        # vcast HTML: 새 component 시작이면 first에 component name, 같은 component 내
        # 다른 함수면 first 빈 + second(Subprogram)에 함수명.
        if first:
            # 새 component 그룹 시작 또는 GRAND TOTALS
            if "TOTAL" in first.upper():
                # GRAND TOTALS / TOTALS row — current_component 갱신 안 함
                function_name = first
                component_name = current_component or first
            else:
                current_component = first
                function_name = second or first  # second 없으면 first가 함수
                component_name = first
        else:
            # 같은 component 안 다른 함수
            function_name = second
            component_name = current_component

        if not function_name:
            continue

        metric_cells = [c.get_text(" ", strip=True) for c in cells]
        metrics = [_parse_metric_cell(t) for t in metric_cells if _RE_PCT.search(t)]

        # 라운드 77 T1202 — component_name 명시 주입 (R10 C3 anomaly fix).
        fc = FunctionCoverage(
            unit_id=function_name,
            name=function_name,
            component_name=component_name,
        )
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

        if "GRAND TOTAL" in function_name.upper() or "TOTAL" in function_name.upper():
            grand_total = fc
        else:
            functions.append(fc)

    return (functions, grand_total)


def _parse_aggregate_coverage_via_temp(
    resolver: Any, html_path: str,
) -> Any:
    """라운드 75 T1001 helper: vcast_parser.parse_aggregate_coverage 호출 wrapper.

    parser가 Path 인자만 받으므로 worker bytes를 임시 파일로 dump → parse → unlink.
    `MetricsBank.sub_functions` 네스트 구조 반환 — `flatten_sub_functions`에 전달.
    """
    from backend.services.vcast_parser import (
        ReportType, VCASTVersion, parse_vcast_report,
    )
    data = _read_via_resolver(resolver, html_path)
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
        tf.write(data)
        tmp = Path(tf.name)
    try:
        return parse_vcast_report(tmp, ReportType.AggregateCoverage, VCASTVersion.Ver2025)
    finally:
        tmp.unlink(missing_ok=True)


def flatten_sub_functions(
    metrics_bank: Any,
    *,
    component_name: str = "",
    out_warnings: list[str] | None = None,
) -> list[FunctionCoverage]:
    """라운드 75 T1001: vcast_parser MetricsBank.sub_functions → FunctionCoverage list.

    회사 KJPDS02 v1.01 SwUTCV 4.Coverage 570 함수 row 패턴 대비 우리 HDPDM01
    NE_GN7 추출이 환경당 2 함수 (60/30 env) 한계. `extract_aggregate_coverage`가
    HTML `<table>` 요약(unique 함수명)만 파싱하나 vcast_parser는 같은 HTML의
    `<pre class="aggregate-coverage">` marker에서 module_order/suborder/name 3-필드
    추출 → 네스트 `sub_functions` 보유 (~5~10 sub-fn ÷ 환경). 본 helper로 평탄화.

    Args:
        metrics_bank: vcast_parser.parse_aggregate_coverage 결과 (`MetricsBank` 객체).
            `sub_functions: Dict[module_name, List[SubFunctionExecution(order, name, executed)]]`.
        component_name: 환경의 component name (audit 추적성). unit_id 생성 시 prefix.
        out_warnings: dedup 충돌 / 빈 결과 / 예외 누적.

    Returns:
        FunctionCoverage list — vcast HTML sub-function 단위. unit_id:
        ``SwUFn_<component>_<module_order>_<suborder>`` (audit 추적성).
        executed=False 함수도 포함 (CoverageStats(0,1,0.0)). executed=True는
        CoverageStats(1,1,1.0).

    Empty/invalid 시 빈 list 반환 (backward-compat fallback).
    """
    if metrics_bank is None:
        return []
    sub_funcs = getattr(metrics_bank, "sub_functions", None) or {}
    if not sub_funcs:
        return []

    safe_comp = (component_name or "X").replace(" ", "_").replace(".", "_")[:20]
    seen_names: set[str] = set()
    out: list[FunctionCoverage] = []
    conflict_count = 0
    for mod_idx, (module_name, sub_list) in enumerate(sorted(sub_funcs.items()), start=1):
        if not sub_list:
            continue
        for sub_exec in sub_list:
            name = (getattr(sub_exec, "name", "") or "").strip()
            order = getattr(sub_exec, "order", "")
            executed = bool(getattr(sub_exec, "executed", False))
            if not name:
                continue
            if name in seen_names:
                conflict_count += 1
                continue
            seen_names.add(name)
            unit_id = f"SwUFn_{safe_comp}_{mod_idx}_{order}"
            stats = CoverageStats(
                covered=1 if executed else 0,
                total=1,
                coverage_pct=1.0 if executed else 0.0,
            )
            out.append(FunctionCoverage(
                unit_id=unit_id,
                name=name,
                statement=stats,
                branch=CoverageStats(0, 0, 0.0),
                mcdc=CoverageStats(0, 0, 0.0),
                complexity=0,
                # 라운드 77 T1203 — sub_function의 parent module = component_name
                component_name=module_name,
            ))
    if conflict_count > 0 and out_warnings is not None:
        out_warnings.append(
            f"[sub_functions] dedup 충돌 {conflict_count}건 (동일 name 첫 entry 보존)"
        )
    return out


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


def extract_execution_results_with_actual(html_bytes: bytes) -> dict[str, ExecutionRow]:
    """58차 F1 — SWTE ExecutionResult HTML → pass/fail + actual_result Dict.

    `extract_execution_results` 확장 (기존 h3 순회 + 다음 h4 찾기 패턴 차용).
    VectorCAST 2025 ExecutionResult.html에서 variable + (actual, expected) 추출.

    VectorCAST report format 변형 (관측):
        (변형 A) <h3>...PASS...</h3> 직후 <h4>Start of SwUFn_...</h4>
        (변형 B) <h4>Start of SwUFn_...</h4> 직후 <h3>...PASS...</h3>
    본 함수는 두 변형 모두 지원하기 위해 기존 `extract_execution_results`와 동일한
    h3 순회 + find_all_next h4 매칭 패턴 사용. actual_result는 td 'EXPECTED:'/
    'ACTUAL:' label 추출 (가능한 만큼만 — graceful 0건도 정상).

    Returns:
        dict[tc_name, ExecutionRow]: actual_result는 variable → (actual, expected).
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for SWTE extractors")
    soup = BeautifulSoup(html_bytes, "html.parser")
    results: dict[str, ExecutionRow] = {}

    # 통합 패턴 — h4 'Start of <tc_name>' 순회 (모든 변형 통일):
    #   각 TC 섹션은 h4 Start of <tc> 부터 다음 h4 Start of (또는 문서 끝) 까지.
    #   passed 판별은 가장 가까운 h3 'Execution Results (PASS|FAIL)' (h4 이전 또는 이후 무관).
    #   actual_result는 그 섹션 안의 tr.success/danger variable rows에서 추출.
    all_h4_starts: list = []
    for h4 in soup.find_all("h4"):
        h4_text = h4.get_text(strip=True)
        m = re.match(r"Start of\s+(\S+)", h4_text)
        if m:
            all_h4_starts.append((m.group(1), h4))

    for idx, (tc_name, h4) in enumerate(all_h4_starts):
        if tc_name in results:
            continue
        # 다음 h4 Start of marker — 섹션 종료점
        next_h4 = all_h4_starts[idx + 1][1] if idx + 1 < len(all_h4_starts) else None
        # passed 판별 — 가장 가까운 h3 'Execution Results' (이전 또는 이후)
        passed = False
        h3_prev = h4.find_previous("h3", title=re.compile("Execution Results", re.I))
        h3_next = h4.find_next("h3", title=re.compile("Execution Results", re.I))
        # next_h4 이전인 h3만 검토
        for h3 in (h3_prev, h3_next):
            if h3 is None:
                continue
            h3_line = getattr(h3, "sourceline", 0) or 0
            h4_line = getattr(h4, "sourceline", 0) or 0
            next_h4_line = getattr(next_h4, "sourceline", 10**9) if next_h4 else 10**9
            # 이전 h3은 직전 TC 종료점 이후 (즉 h4 직전), 다음 h3은 next_h4 이전이어야 매칭
            if (h3 is h3_prev and h3_line >= h4_line - 20) or (
                h3 is h3_next and h3_line < (next_h4_line or 10**9)
            ):
                txt = h3.get_text(" ", strip=True)
                passed = "(PASS)" in txt or ("PASS" in txt and "FAIL" not in txt)
                break
        actual_result = _extract_var_rows_between(h4, next_h4)
        results[tc_name] = ExecutionRow(
            tc_name=tc_name, passed=passed, actual_result=actual_result,
        )

    return results


def extract_step_iterations(
    html_bytes: bytes,
) -> dict[str, list[dict[str, str]]]:
    """59차 F4-B — VectorCAST HTML에서 TC당 step별 input dict 추출.

    회사 v1.01 (KJPDS02) 양식은 1 TC = 6 row step (step 1~6의 다른 input 변수 값
    조합). VectorCAST HTML이 step 분리 anchor (``Iteration N`` / ``Test Step N`` /
    ``Step N``) 를 가지면 그 anchor 사이 INPUT VALUE 라벨을 추출하여 step별 dict
    list로 반환.

    HDPDM01 NE_GN7 v2.02 양식 fixture (29 TC 라이브 검증, 2026-05-27) 에서는
    ``Iteration`` / ``Test Step`` 라벨 0건 — 모든 TC empty list (step 분리는 TC
    suffix ``.001/.002/...`` 로 처리됨). 본 함수는 미래 KJPDS02 환경 또는
    VectorCAST 다른 버전 호환을 위한 인프라.

    Args:
        html_bytes: VectorCAST ExecutionResult.html bytes (또는 TestCaseDataReport).

    Returns:
        ``{tc_name: [step1_input_dict, step2_input_dict, ...]}`` — step 분리 라벨이
        없는 TC는 empty list. caller (``_write_test_log``) 가 본 list가 비어 있으면
        기존 fallback (TC suffix 다중화) 동작.
    """
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for step iteration extractor")
    soup = BeautifulSoup(html_bytes, "html.parser")
    results: dict[str, list[dict[str, str]]] = {}

    # step anchor regex — h3/h4/h5 텍스트 매칭.
    step_anchor_re = re.compile(
        r"^\s*(Iteration|Test Step|Step|Sequence Step)\s+(\d+)\s*$",
        re.IGNORECASE,
    )

    # TC 섹션 anchor 모음 (extract_execution_results_with_actual와 동일 패턴).
    all_h4_starts: list = []
    for h4 in soup.find_all("h4"):
        h4_text = h4.get_text(strip=True)
        m = re.match(r"Start of\s+(\S+)", h4_text)
        if m:
            all_h4_starts.append((m.group(1), h4))

    for idx, (tc_name, h4) in enumerate(all_h4_starts):
        if tc_name in results:
            continue
        next_h4 = all_h4_starts[idx + 1][1] if idx + 1 < len(all_h4_starts) else None
        next_line = (
            getattr(next_h4, "sourceline", 10**9) if next_h4 is not None else 10**9
        )

        # 본 TC 섹션 안의 step anchor 찾기 (h3/h4/h5 모두 후보)
        step_anchors: list = []
        for tag_name in ("h3", "h4", "h5"):
            for el in h4.find_all_next(tag_name, limit=200):
                el_line = getattr(el, "sourceline", 10**9) or 10**9
                if el_line >= next_line:
                    break
                if el is h4:
                    continue
                txt = el.get_text(strip=True)
                if step_anchor_re.match(txt):
                    step_anchors.append(el)
        # sourceline 순 정렬 (h3/h4/h5 섞일 수 있음)
        step_anchors.sort(key=lambda x: getattr(x, "sourceline", 0) or 0)

        if not step_anchors:
            results[tc_name] = []
            continue

        steps: list[dict[str, str]] = []
        for s_idx, anchor in enumerate(step_anchors):
            end_anchor = (
                step_anchors[s_idx + 1] if s_idx + 1 < len(step_anchors) else next_h4
            )
            end_line = (
                getattr(end_anchor, "sourceline", 10**9) if end_anchor else 10**9
            )

            # anchor ~ end_anchor 사이의 INPUT VALUE 라벨 추출.
            # VectorCAST HTML 패턴: <td>INPUT VALUE</td> <td>var_name</td> <td>value</td>
            #   또는 'INPUT VALUE = var = value' 인라인 텍스트.
            step_dict: dict[str, str] = {}
            for tr in anchor.find_all_next("tr", limit=500):
                tr_line = getattr(tr, "sourceline", 10**9) or 10**9
                if tr_line >= end_line:
                    break
                tds = tr.find_all("td")
                # 'INPUT VALUE' label 찾기 (정확 매칭 또는 startswith)
                if len(tds) >= 3:
                    label = tds[0].get_text(strip=True).upper()
                    if "INPUT" in label and "VALUE" in label:
                        var_name = tds[1].get_text(strip=True)
                        var_value = tds[2].get_text(strip=True)
                        if var_name:
                            step_dict[var_name] = var_value
                # 인라인 'INPUT VALUE = var = value' 패턴
                txt = tr.get_text(" ", strip=True)
                inline_m = re.search(
                    r"INPUT\s+VALUE\s*=\s*(\S+)\s*=\s*(\S+)", txt, re.IGNORECASE,
                )
                if inline_m and inline_m.group(1) not in step_dict:
                    step_dict[inline_m.group(1)] = inline_m.group(2)
            steps.append(step_dict)
        results[tc_name] = steps

    return results


def _extract_var_rows_between(anchor, end_anchor) -> dict[str, tuple[str, str]]:
    """58차 F1 (수정) — anchor와 end_anchor 사이의 tr.success/danger variable row 추출.

    variable row 식별: 첫 td의 class가 'i1', 'i2', 'i3', ... 패턴. tr.success는 match,
    tr.danger는 fail (actual vs expected 차이).
    """
    actual_result: dict[str, tuple[str, str]] = {}
    if anchor is None:
        return actual_result
    name_by_level: dict[int, str] = {}
    end_line = getattr(end_anchor, "sourceline", None) if end_anchor else None
    for tr in anchor.find_all_next("tr", limit=2000):
        tr_line = getattr(tr, "sourceline", None)
        if end_line is not None and tr_line is not None and tr_line >= end_line:
            break
        tds = tr.find_all("td", recursive=False)
        if not tds:
            tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        first_td = tds[0]
        td_classes = first_td.get("class") or []
        level_match = next(
            (
                re.match(r"^i(\d+)$", c)
                for c in td_classes
                if isinstance(c, str) and re.match(r"^i\d+$", c)
            ),
            None,
        )
        if not level_match:
            continue
        classlevel = int(level_match.group(1))
        # 'i0' (UNIT label) / 'i1' (Globals label) 등은 variable row 아님 — 값이 변수명만
        # 보유. 실제 variable row는 td 3+ 보유 + 값/match 컬럼 있음.
        raw_name = first_td.get_text(strip=True)
        if not raw_name:
            continue
        # 'UNIT:' / 'Globals:' / 'Locals:' 등 label row skip
        if any(raw_name.startswith(prefix) for prefix in (
            "UNIT:", "Globals:", "Locals:", "Parameters:", "Return Value:",
        )):
            if classlevel <= 1:
                name_by_level.clear()
            continue
        name_by_level[classlevel] = raw_name
        for stale_level in [level for level in name_by_level if level > classlevel]:
            name_by_level.pop(stale_level, None)
        var_name = ""
        for level in sorted(name_by_level):
            part = name_by_level[level]
            if not var_name:
                var_name = part
            elif part.startswith("["):
                var_name += part
            else:
                var_name += f".{part}"
        if not var_name or var_name in actual_result:
            continue
        # 마지막 td class가 success-marker → actual == expected (match)
        last_td_classes = tds[-1].get("class") or []
        is_match = any(
            isinstance(c, str) and "success-marker" in c for c in last_td_classes
        )
        is_fail = any(
            isinstance(c, str) and ("fail-marker" in c or "danger" in c)
            for c in last_td_classes
        )
        actual_val = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        if is_match:
            expected_val = actual_val
        elif is_fail and len(tds) > 3:
            expected_val = tds[3].get_text(strip=True)
        else:
            expected_val = tds[3].get_text(strip=True) if len(tds) > 3 else actual_val
        if not actual_val and not expected_val and not (is_match or is_fail):
            continue
        actual_result[var_name] = (actual_val, expected_val)
    return actual_result


def _extract_actual_from_node(anchor) -> dict[str, tuple[str, str]]:
    """58차 F1 — anchor element 이후 다음 TC 섹션 도달 전까지 variable row 추출.

    VectorCAST 2025 실 HTML 구조 (관측):
        <tr class="success">           <!-- pass 변수 row -->
          <td class='i2'>variable_name</td>
          <td>type</td>
          <td>value</td>                <!-- actual == expected (success match) -->
          <td class='success-marker'>&lt;match&gt;</td>
        </tr>
        <tr class="danger">            <!-- fail 변수 row -->
          <td class='i2'>variable_name</td>
          <td>type</td>
          <td>actual_value</td>
          <td>expected_value</td>      <!-- or class='fail-marker' -->
        </tr>

    variable row 식별: 첫 td의 class가 'i1', 'i2', 'i3', ... pattern. 다음 anchor
    (h3/h4 Start of 또는 Execution Results) 도달 전까지 수집.

    Args:
        anchor: BeautifulSoup element — h3 또는 h4 시작점.

    Returns:
        dict[var_name, (actual, expected)]: 빈 dict면 graceful (stamp skip).
    """
    actual_result: dict[str, tuple[str, str]] = {}
    if anchor is None:
        return actual_result

    # 다음 TC 섹션 marker (h3 Execution Results 또는 h4 Start of) sourceline
    next_anchor_line = None
    for cand in anchor.find_all_next(["h3", "h4"]):
        cand_text = cand.get_text(strip=True)
        is_marker = False
        if cand.name == "h3" and re.search(
            r"Execution Results", cand_text, re.I,
        ):
            is_marker = True
        elif cand.name == "h4" and re.match(r"Start of\s+\S+", cand_text):
            is_marker = True
        if is_marker:
            next_anchor_line = getattr(cand, "sourceline", None)
            break

    # tr 순회 — variable row만 추출
    for tr in anchor.find_all_next("tr", limit=500):
        tr_line = getattr(tr, "sourceline", None)
        # 다음 anchor 도달했으면 stop
        if (next_anchor_line is not None and tr_line is not None
                and tr_line >= next_anchor_line):
            break
        tds = tr.find_all("td", recursive=False)
        if not tds:
            tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        first_td = tds[0]
        td_classes = first_td.get("class") or []
        # variable row 식별 — 첫 td class가 i1, i2, i3, ...
        if not any(isinstance(c, str) and re.match(r"^i\d+$", c) for c in td_classes):
            continue
        var_name = first_td.get_text(strip=True)
        if not var_name or var_name in actual_result:
            continue

        # success-marker → actual == expected (둘 다 tds[2])
        # fail/danger → actual=tds[2], expected=tds[3]
        last_td_classes = tds[-1].get("class") or []
        is_match = any(
            isinstance(c, str) and "success-marker" in c for c in last_td_classes
        )
        actual_val = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        if is_match:
            expected_val = actual_val
        else:
            expected_val = tds[3].get_text(strip=True) if len(tds) > 3 else ""
        actual_result[var_name] = (actual_val, expected_val)
    return actual_result


def _is_before(elem_a, elem_b) -> bool:
    """BeautifulSoup element a가 b보다 문서 상 앞에 있는지 (sourceline 비교 + 안전 fallback)."""
    la = getattr(elem_a, "sourceline", None)
    lb = getattr(elem_b, "sourceline", None)
    if la is None or lb is None:
        return True  # 알 수 없으면 conservative True (포함)
    return la < lb


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


def _parse_execution_result_via_temp(resolver: Any, html_path: str) -> Any:
    """57차 T321 — vcast_parser.parse_execution_result 호출 (actual_result 포함).

    extract_execution_results는 pass/fail만 추출하지만 vcast_parser는
    TestResultItem.actual_result (Dict[str, Tuple[str, str]] — (actual, expected))
    까지 추출. SUTR Test Log Z~AI 컬럼 Actual stamp용 source.
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
        return parse_vcast_report(tmp, ReportType.ExecutionResult, VCASTVersion.Ver2025)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 라운드 89 — VectorCAST 출력 폴더 레이아웃 변종 (HDPDM01 SWTE vs KJPDS02 VC2025)
# ---------------------------------------------------------------------------
#
# 같은 VectorCAST HTML 계열이지만 출력 폴더명/파일명 명명이 프로젝트마다 다르다.
#
#   SWTE 변종 (HDPDM01 NE_GN7):
#     01.TestCaseDataReport/<env>_test_case_data_report.html      env=SWTE_NN
#     02.ExecutionResultReport/<env>_execution_results_report.html
#     03.AggregateCoverageReport/<env>_aggregate_coverage_report.html
#     04.MetricsReport/<env>_metrics_report.html
#
#   VC2025 표준 (KJPDS02 / VectorCAST 2025 기본 리포트 폴더):
#     TestCaseData/<env>_TestCaseDataReport.html                  env=SwUT_NN_<name>
#     ExecutionResult/<env>_ExecutionResultReport.html
#     Aggregate/<env>_AggregateCoverageReport.html
#     Metrics/<env>_MetricsReport.html
#
# env 추출은 tc 파일명에서 tc_suffix를 strip하는 방식이 두 변종 모두에 정확하나,
# SWTE는 기존 prefix 정규식(`_extract_env_from_filename`)을 유지해 300+ 회귀에
# byte-identical 동작 보장 (env_mode="prefix"). VC2025만 suffix-strip 사용.


@dataclass(frozen=True)
class LogLayout:
    """VectorCAST 출력 폴더 레이아웃 변종 기술자."""
    name: str
    tc_dir: str
    exec_dir: str
    cov_dir: str
    metrics_dir: str
    tc_suffix: str
    exec_suffix: str
    cov_suffix: str
    metrics_suffix: str
    env_mode: str  # "prefix" (SWTE 정규식) | "suffix" (suffix-strip)
    # B1 — 실행결과 폴더명 대체 후보 (KJPDS02 PV 실측: "ExecutionResult" 대신
    # "Execution"). exec_dir 미존재 시 순서대로 시도해 첫 존재 폴더로 대체.
    # default 빈 튜플 — SWTE 등 기존 레이아웃 동작 영향 0.
    exec_dir_alts: tuple[str, ...] = ()

    def extract_env(self, filename: str, env_prefix: str) -> str:
        """tc 리포트 파일명 → env 이름. 매칭 실패 시 빈 문자열."""
        if self.env_mode == "suffix":
            if filename.endswith(self.tc_suffix):
                return filename[: -len(self.tc_suffix)]
            return ""
        # prefix 모드 — 기존 동작 (backward compat, SWTE/SwIT)
        return _extract_env_from_filename(filename, env_prefix=env_prefix)


SWTE_LAYOUT = LogLayout(
    name="swte",
    tc_dir="01.TestCaseDataReport",
    exec_dir="02.ExecutionResultReport",
    cov_dir="03.AggregateCoverageReport",
    metrics_dir="04.MetricsReport",
    tc_suffix="_test_case_data_report.html",
    exec_suffix="_execution_results_report.html",
    cov_suffix="_aggregate_coverage_report.html",
    metrics_suffix="_metrics_report.html",
    env_mode="prefix",
)

VC2025_LAYOUT = LogLayout(
    name="vc2025",
    tc_dir="TestCaseData",
    # exec_dir="ExecutionResult" 유지 — 기존 HDPDM01 환경 backward compat.
    # KJPDS02 PV 실측(260604)은 폴더명이 "Execution" — exec_dir_alts로 대체 지원.
    exec_dir="ExecutionResult",
    cov_dir="Aggregate",
    metrics_dir="Metrics",
    tc_suffix="_TestCaseDataReport.html",
    exec_suffix="_ExecutionResultReport.html",
    cov_suffix="_AggregateCoverageReport.html",
    metrics_suffix="_MetricsReport.html",
    env_mode="suffix",
    exec_dir_alts=("Execution",),
)

# 탐지 순서 — SWTE 우선 (기존 동작 보존), 미발견 시 VC2025.
_LOG_LAYOUTS = (SWTE_LAYOUT, VC2025_LAYOUT)


def _exists_quiet(resolver: Any, path: str) -> bool:
    """resolver.exists 예외를 False로 흡수 — 대체 후보 탐색 전용.

    primary 경로 존재 검사(기존 흐름)는 예외를 그대로 전파해 backward compat
    유지. 본 헬퍼는 B1 exec_dir_alts probing처럼 "없으면 다음 후보" 분기에만 사용.
    """
    try:
        return bool(resolver.exists(path))
    except Exception:  # noqa: BLE001 — exists 실패는 미존재로 간주 (후보 탐색)
        return False


def _detect_log_layout(
    resolver: Any, log_folder: str, out_warnings: list[str] | None = None
) -> LogLayout:
    """log_folder 내 tc 폴더 존재 여부로 레이아웃 변종 자동 감지.

    SWTE → VC2025 순으로 검사. 둘 다 미발견 시 SWTE_LAYOUT 반환 (기존
    "하위 폴더 미발견" warning 흐름에 위임 — backward compat).
    """
    for layout in _LOG_LAYOUTS:
        try:
            if resolver.exists(os.path.join(log_folder, layout.tc_dir)):
                if layout is not SWTE_LAYOUT and out_warnings is not None:
                    out_warnings.append(
                        f"로그 레이아웃 '{layout.name}' 자동 감지 "
                        f"(폴더 {layout.tc_dir}/ 기준)"
                    )
                return layout
        except Exception:  # noqa: BLE001 — exists 실패는 다음 layout 시도
            continue
    return SWTE_LAYOUT


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
    # Case A 빠른 경로: tc sub-folder 이미 존재 → 그대로 사용.
    # 라운드 89 — SWTE("01.TestCaseDataReport") / VC2025("TestCaseData") 둘 다 인정.
    # exists 예외는 W2 계약대로 warning 누적 후 원본 반환 (silent 금지).
    try:
        for _layout in _LOG_LAYOUTS:
            if resolver.exists(os.path.join(log_folder, _layout.tc_dir)):
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


def _norm_env_stem(stem: str) -> str:
    """env stem 정규화 — 폴더 간 명명 불일치 흡수용 (라운드 89).

    실 데이터(KJPDS02)에서 TestCaseData는 `..._SafeWriteQueue_PDS`, 형제 폴더는
    `..._SafeWriteQueue` 로 trailing `_PDS` 토큰이 불일치하는 사례 발견. 매칭 키를
    소문자 + trailing `_pds` 제거로 정규화해 같은 유닛을 연결한다.
    """
    s = stem.strip().lower()
    while s.endswith("_pds"):
        s = s[:-4]
    return s


def _resolve_report_path(
    resolver: Any,
    folder: str,
    env: str,
    suffix: str,
    *,
    alt_suffixes: tuple[str, ...] = (),
    idx_cache: dict[str, dict[str, str]],
    out_warnings: list[str] | None,
) -> str:
    """`{env}{suffix}` exact 우선, 없으면 정규화 stem 매칭 fallback.

    exact 파일이 존재하면 그대로 반환(happy path — SWTE/대부분 KJPDS02 env에
    동작 byte-identical). 미존재 시에만 폴더를 1회 인덱싱하여 trailing `_PDS`
    차이를 흡수한 후보를 찾고, 매칭되면 warning을 남기고 그 경로를 반환한다.
    후보 0건이면 exact 경로를 그대로 반환(이후 read에서 FileNotFoundError →
    parse_errors 기록, silent skip 차단 정책 유지).
    """
    suffixes = (suffix, *alt_suffixes)
    exact = os.path.join(folder, f"{env}{suffix}")
    for candidate_suffix in suffixes:
        candidate = os.path.join(folder, f"{env}{candidate_suffix}")
        try:
            if resolver.exists(candidate):
                return candidate
        except Exception:  # noqa: BLE001 — exists 실패는 fuzzy로 위임
            pass

    idx = idx_cache.get(folder)
    if idx is None:
        idx = {}
        try:
            for f in _list_dir_via_resolver(resolver, folder, pattern="*.html"):
                nm = Path(f).name
                for candidate_suffix in suffixes:
                    if nm.endswith(candidate_suffix):
                        idx.setdefault(_norm_env_stem(nm[: -len(candidate_suffix)]), f)
                        break
        except Exception:  # noqa: BLE001
            idx = {}
        idx_cache[folder] = idx

    cand = idx.get(_norm_env_stem(env))
    if cand and cand != exact:
        if out_warnings is not None:
            out_warnings.append(
                f"파일명 불일치 fallback: env '{env}' → '{Path(cand).name}' "
                f"({Path(folder).name}/ 폴더, trailing _PDS 정규화 매칭)"
            )
        return cand
    return exact


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

    # 라운드 89 — 레이아웃 변종 자동 감지 (SWTE / VC2025). 폴더명 + 파일 suffix +
    # env 추출 방식이 변종마다 다르다.
    layout = _detect_log_layout(resolver, log_folder, warnings)
    _diag_logger.info(f"collect_from_log_folder: layout={layout.name!r}")

    # 1) 3 sub-folder 존재 확인
    sub_tc = os.path.join(log_folder, layout.tc_dir)
    sub_exec = os.path.join(log_folder, layout.exec_dir)
    exec_dir_label = layout.exec_dir
    # B1 — 실행결과 폴더명 대체 후보 (KJPDS02 PV 실측 260604: "ExecutionResult"
    # 대신 "Execution"). 기본 exec_dir 미존재 시 exec_dir_alts를 순서대로 시도,
    # 첫 존재 폴더로 대체 + warning 기록. alts 빈 레이아웃(SWTE)은 단락 평가로
    # 추가 resolver.exists 호출 0 — 기존 동작 byte-identical.
    if layout.exec_dir_alts and not _exists_quiet(resolver, sub_exec):
        for _alt_dir in layout.exec_dir_alts:
            _alt_path = os.path.join(log_folder, _alt_dir)
            if _exists_quiet(resolver, _alt_path):
                warnings.append(
                    f"실행결과 폴더 대체 감지: {layout.exec_dir} 미존재 → "
                    f"{_alt_dir} 사용"
                )
                _diag_logger.info(
                    f"collect_from_log_folder: exec_dir 대체 "
                    f"{layout.exec_dir!r} → {_alt_dir!r}"
                )
                sub_exec = _alt_path
                exec_dir_label = _alt_dir
                break
    sub_cov = os.path.join(log_folder, layout.cov_dir)
    # 라운드 74 T909/T910 — Metrics 폴더 (옵션) 동적 탐지. 존재 시 함수별 추가 metric.
    sub_metrics = os.path.join(log_folder, layout.metrics_dir)
    has_metrics_folder = resolver.exists(sub_metrics)
    if has_metrics_folder:
        _diag_logger.info(f"collect_from_log_folder: 하위 폴더 존재 {sub_metrics!r}")

    # B1 — sub_exec/label은 위에서 대체됐을 수 있음 (exec_dir_alts) → 일관 반영.
    for sub_path, label in [
        (sub_tc, layout.tc_dir),
        (sub_exec, exec_dir_label),
        (sub_cov, layout.cov_dir),
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
        layout.extract_env(Path(f).name, env_prefix)
        for f in tc_files
        if layout.extract_env(Path(f).name, env_prefix)
    })
    _diag_logger.info(
        f"collect_from_log_folder: env_names ({len(env_names)}) = {env_names[:10]}"
    )

    # 3) 각 env마다 3 파일 추출
    # 라운드 89 — 폴더별 정규화 stem 인덱스 캐시 (파일명 불일치 fallback용, exact
    # 매칭 실패 시에만 1회 채워짐).
    _folder_idx_cache: dict[str, dict[str, str]] = {}
    for env in env_names:
        env_data = EnvironmentData(env_name=env)

        # TestCaseData
        tc_path = os.path.join(sub_tc, f"{env}{layout.tc_suffix}")
        try:
            tcbank = _parse_testcase_data_via_temp(resolver, tc_path)
            env_data.component_name = getattr(tcbank, "component_name", "")
            env_data.environment_name = getattr(tcbank, "environment", "")
            env_data.test_cases = dict(getattr(tcbank, "test_cases", {}) or {})
            # 57차 T321 — TCBank.test_results carry forward (actual_result 포함)
            env_data.tc_result_items = dict(getattr(tcbank, "test_results", {}) or {})
            parse_err = getattr(tcbank, "parse_error", None)
            if parse_err:
                env_data.parse_errors.append(f"TestCaseData: {parse_err}")
        except Exception as e:
            env_data.parse_errors.append(f"TestCaseData: {type(e).__name__}: {e}")

        # ExecutionResult
        exec_path = _resolve_report_path(
            resolver, sub_exec, env, layout.exec_suffix,
            idx_cache=_folder_idx_cache, out_warnings=warnings,
        )
        try:
            data = _read_via_resolver(resolver, exec_path)
            # 58차 F1 — actual_result Dict까지 추출 (extract_execution_results_with_actual)
            env_data.test_results = extract_execution_results_with_actual(data)
            # 57차 T321 — vcast_parser ExecutionResult parsing 추가 (actual_result 포함).
            # extract_execution_results는 pass/fail만 추출 → 별도 source 필요.
            try:
                tcbank_exec = _parse_execution_result_via_temp(resolver, exec_path)
                exec_test_results = getattr(tcbank_exec, "test_results", {}) or {}
                if exec_test_results:
                    # tc_result_items merge — TestCaseData parse 결과와 union.
                    # 동일 tc_name에 양쪽 다 있으면 ExecutionResult 우선 (actual_result 보유).
                    for tc_name, items in exec_test_results.items():
                        env_data.tc_result_items[tc_name] = items
            except Exception as e_inner:
                env_data.parse_errors.append(
                    f"ExecutionResult vcast parse: {type(e_inner).__name__}: {e_inner}"
                )
        except Exception as e:
            env_data.parse_errors.append(f"ExecutionResult: {type(e).__name__}: {e}")

        # AggregateCoverage
        cov_alt_suffixes = (
            ("_AggregateReport.html",)
            if layout.name == "vc2025" and layout.cov_suffix != "_AggregateReport.html"
            else ()
        )
        cov_path = _resolve_report_path(
            resolver, sub_cov, env, layout.cov_suffix,
            alt_suffixes=cov_alt_suffixes,
            idx_cache=_folder_idx_cache, out_warnings=warnings,
        )
        try:
            data = _read_via_resolver(resolver, cov_path)
            funcs, total = extract_aggregate_coverage(data)
            env_data.function_coverage = funcs
            env_data.grand_total = total
        except Exception as e:
            env_data.parse_errors.append(f"AggregateCoverage: {type(e).__name__}: {e}")

        # 라운드 75 T1002~T1004 — vcast_parser sub_functions 평탄화 통합.
        # extract_aggregate_coverage가 HTML `<table>` 요약(unique 함수명만)만 추출
        # 하나, 같은 HTML의 `<pre class="aggregate-coverage">` marker는 module/sub-fn
        # 3-필드(module_order/suborder/name) 보유 → vcast_parser가 이미 추출 + 네스트
        # 구조 (MetricsBank.sub_functions) 보유. 본 통합으로 환경당 함수 수 2 → 5~10
        # 추정 (~120~210 total stamp 가능).
        try:
            mb = _parse_aggregate_coverage_via_temp(resolver, cov_path)
            extra_fns = flatten_sub_functions(
                mb,
                component_name=env_data.component_name,
                out_warnings=env_data.parse_errors,
            )
            if extra_fns:
                existing_names = {fc.name for fc in env_data.function_coverage}
                # 라운드 73 c_function_map ASIL 매핑 자동 등록 (T1003)
                c_fn_map_local = getattr(session, "c_function_map", None) or {}
                added = 0
                asil_mapped = 0
                for new_fc in extra_fns:
                    if new_fc.name in existing_names:
                        continue
                    env_data.function_coverage.append(new_fc)
                    existing_names.add(new_fc.name)
                    added += 1
                    # ASIL 매핑 — c_function_map에 매칭되면 env.function_asil_map 등록
                    c_entry = c_fn_map_local.get(new_fc.name)
                    if c_entry:
                        asil = (c_entry.get("comment_asil") or "").strip().upper()
                        if asil in {"A", "B", "C", "D", "QM"}:
                            env_data.function_asil_map[new_fc.unit_id] = asil
                            asil_mapped += 1
                if added > 0:
                    _diag_logger.info(
                        f"collect_from_log_folder: {env} sub_functions 평탄화 → "
                        f"{added} 함수 추가 ({asil_mapped} ASIL 매핑)"
                    )
        except Exception as e:
            # T1004 backward-compat — vcast_parser 실패 시 silent fallback (기존 60 row 유지)
            env_data.parse_errors.append(
                f"[sub_functions] vcast_parser 실패 (skip): {type(e).__name__}: {str(e)[:80]}"
            )

        # 라운드 74 T910 — 04.MetricsReport HTML (옵션). 존재 시 vcast_hmr_parser
        # 재활용 → 환경별 함수별 metric 추출 후 function_coverage에 union (dedup by name).
        # HDPDM01 NE_GN7은 미존재 — silent skip (backward-compat). KJPDS02 같은 다른
        # 양식에 04.MetricsReport이 있으면 자동 활용.
        if has_metrics_folder:
            metrics_path = _resolve_report_path(
                resolver, sub_metrics, env, layout.metrics_suffix,
                idx_cache=_folder_idx_cache, out_warnings=warnings,
            )
            try:
                if resolver.exists(metrics_path):
                    metrics_data = _read_via_resolver(resolver, metrics_path)
                    from backend.services.vcast_hmr_parser import parse_hmr_html
                    _w: list[str] = []
                    hmr = parse_hmr_html(metrics_data, parse_warnings=_w)
                    if hmr.ok and hmr.metrics:
                        existing_names = {fc.name for fc in env_data.function_coverage}
                        added = 0
                        # 라운드 89: hmr.metrics는 dict[str, FunctionCallsMetric] —
                        # .values() 순회 (이전: 키(str) 순회로 AttributeError, HDPDM01엔
                        # Metrics 폴더 부재로 미노출되다 KJPDS02 VC2025에서 처음 발현).
                        for m in hmr.metrics.values():
                            if m.function_name in existing_names:
                                continue
                            new_fc = FunctionCoverage(
                                unit_id=m.function_name,
                                name=m.function_name,
                                statement=CoverageStats(0, 0, 0.0),
                                branch=CoverageStats(0, 0, 0.0),
                                function_calls_coverage=CoverageStats(
                                    covered=m.covered_calls,
                                    total=m.total_calls,
                                    coverage_pct=(m.coverage_pct or 0) / 100.0,
                                ),
                                complexity=m.complexity or 0,
                            )
                            env_data.function_coverage.append(new_fc)
                            existing_names.add(m.function_name)
                            added += 1
                        if added > 0:
                            _diag_logger.info(
                                f"collect_from_log_folder: {env} 04.MetricsReport "
                                f"merge — {added} function metric 추가"
                            )
            except Exception as e:
                env_data.parse_errors.append(f"MetricsReport: {type(e).__name__}: {e}")

        session.environments.append(env_data)

    if not session.environments:
        warnings.append(
            f"환경({env_prefix}_xx) 0건 — '{sub_tc}' 폴더 listing 검증 필요"
        )

    # 59차 F5 W4 — 추출 누락 summary parse_warnings emit (silent skip 차단).
    # audit reviewer가 산출물에 어떤 데이터가 누락됐는지 즉시 인지 가능.
    # ISO 26262 평가: 추출 실패가 silent skip되면 evidence_class 무관 거짓 PASS 위험.
    _summary_input_empty = 0
    _summary_expected_empty = 0
    _summary_actual_value_empty = 0
    _summary_actual_execution_missing = 0
    _input_empty_by_env: dict[str, int] = {}
    _expected_empty_by_env: dict[str, int] = {}
    _actual_value_empty_by_env: dict[str, int] = {}
    _actual_execution_missing_by_env: dict[str, int] = {}
    _total_tcs = 0

    for env_data in session.environments:
        for tc_name, tc_items in env_data.test_cases.items():
            _total_tcs += 1
            items = tc_items if isinstance(tc_items, list) else [tc_items]
            first = items[0] if items else None
            if first is not None:
                if not (getattr(first, "input_data", None) or {}):
                    _summary_input_empty += 1
                    _input_empty_by_env[env_data.env_name] = (
                        _input_empty_by_env.get(env_data.env_name, 0) + 1
                    )
                if not (getattr(first, "expected_result", None) or {}):
                    _summary_expected_empty += 1
                    _expected_empty_by_env[env_data.env_name] = (
                        _expected_empty_by_env.get(env_data.env_name, 0) + 1
                    )
            # actual_result 확인 — ExecutionRow 또는 TestResultItem
            exec_r = env_data.test_results.get(tc_name)
            actual_via_exec = bool(getattr(exec_r, "actual_result", None) or {}) if exec_r else False
            tr_items_for_tc = env_data.tc_result_items.get(tc_name, [])
            tr_first = tr_items_for_tc[0] if tr_items_for_tc else None
            actual_via_tr = bool(getattr(tr_first, "actual_result", None) or {}) if tr_first else False
            if not (actual_via_exec or actual_via_tr):
                if exec_r is None and tr_first is None:
                    _summary_actual_execution_missing += 1
                    _actual_execution_missing_by_env[env_data.env_name] = (
                        _actual_execution_missing_by_env.get(env_data.env_name, 0) + 1
                    )
                else:
                    _summary_actual_value_empty += 1
                    _actual_value_empty_by_env[env_data.env_name] = (
                        _actual_value_empty_by_env.get(env_data.env_name, 0) + 1
                    )

    if _total_tcs > 0 and (
        _summary_input_empty
        or _summary_expected_empty
        or _summary_actual_value_empty
        or _summary_actual_execution_missing
    ):
        warnings.append(
            f"[extraction] value-row summary: total={_total_tcs}, "
            f"input_empty={_summary_input_empty}"
            f"({100*_summary_input_empty/_total_tcs:.1f}%), "
            f"expected_empty={_summary_expected_empty}"
            f"({100*_summary_expected_empty/_total_tcs:.1f}%), "
            f"actual_value_empty={_summary_actual_value_empty}"
            f"({100*_summary_actual_value_empty/_total_tcs:.1f}%), "
            f"actual_execution_missing={_summary_actual_execution_missing}"
            f"({100*_summary_actual_execution_missing/_total_tcs:.1f}%). "
            "Empty value rows can be valid when the VectorCAST TC has no data rows; "
            "execution_missing requires audit review."
        )
        for label, dist in [
            ("input_empty", _input_empty_by_env),
            ("expected_empty", _expected_empty_by_env),
            ("actual_value_empty", _actual_value_empty_by_env),
            ("actual_execution_missing", _actual_execution_missing_by_env),
        ]:
            if dist:
                top = sorted(dist.items(), key=lambda x: -x[1])[:5]
                warnings.append(
                    f"[extraction] env top5 {label}: "
                    + ", ".join(f"{env}={cnt}" for env, cnt in top)
                )

    _summary_missing_input = 0
    _summary_missing_expected = 0
    _summary_missing_actual = 0
    _missing_input_by_env: dict[str, int] = {}
    _missing_expected_by_env: dict[str, int] = {}
    _missing_actual_by_env: dict[str, int] = {}

    if _total_tcs > 0 and (
        _summary_missing_input or _summary_missing_expected or _summary_missing_actual
    ):
        warnings.append(
            f"[추출 누락 summary] 총 {_total_tcs} TC 중 input 누락 "
            f"{_summary_missing_input}건 ({100*_summary_missing_input/_total_tcs:.1f}%), "
            f"expected 누락 {_summary_missing_expected}건 "
            f"({100*_summary_missing_expected/_total_tcs:.1f}%), actual 누락 "
            f"{_summary_missing_actual}건 ({100*_summary_missing_actual/_total_tcs:.1f}%) "
            "— audit evidence 진단 필요 (silent skip 차단 W4)"
        )
        # env별 분포는 top 5건만 — warnings 너무 많아지지 않게.
        for label, dist in [
            ("input", _missing_input_by_env),
            ("expected", _missing_expected_by_env),
            ("actual", _missing_actual_by_env),
        ]:
            if dist:
                top = sorted(dist.items(), key=lambda x: -x[1])[:5]
                warnings.append(
                    f"[추출 누락 env top5 {label}] "
                    + ", ".join(f"{env}={cnt}" for env, cnt in top)
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
                # 57차 T321 — TCBank.test_results carry forward
                env_data.tc_result_items = dict(getattr(tcbank, "test_results", {}) or {})
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
                    # 58차 F1 — actual_result Dict까지 추출
                    env_data.test_results = extract_execution_results_with_actual(fh.read())
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

def _collect_from_log_folders_merged(
    resolver: Any,
    log_folders: list[str],
    project_id: str = "",
    parse_warnings: list[str] | None = None,
    allowed_roots: list[str] | None = None,
    *,
    env_prefix: str = "SWTE",
) -> SwUTSession:
    """B2 — 다중 log_folder collect + 세션 병합 (예: APP 43 + BOOT 10 = 53유닛 통합).

    병합 정책 (이중 집계 방지 — docstring 계약):
        - environments: 폴더 순서대로 합산. env_name 중복 시 **첫 폴더 우선 +
          뒤 항목 skip + parse_warnings에 중복 경고**. 동일 env가 두 번 집계되면
          total/passed 수치가 부풀어 evidence 신뢰성이 훼손되므로 first-wins.
        - parse_warnings: 폴더 식별 prefix(`[#i <폴더명>]`) 부여 후 합산.
        - source_path: 폴더별 (release 자동 선택 후) source_path를 ";"로 join.
        - version: 첫 폴더 기준.

    Raises:
        ValueError: allowed_roots 위반 폴더 발견 시 즉시 전파 (보안 검사 —
            부분 성공 세션을 만들지 않는다).
    """
    merged_warnings = parse_warnings if parse_warnings is not None else []
    merged = SwUTSession(
        project_id=project_id,
        source_kind="log_folder",
        parse_warnings=merged_warnings,
    )
    seen_envs: set[str] = set()
    source_paths: list[str] = []
    for idx, folder in enumerate(log_folders, start=1):
        folder_name = Path(folder.rstrip("/\\")).name or folder
        tag = f"[#{idx} {folder_name}]"
        sub_warnings: list[str] = []
        sub = collect_from_log_folder(
            resolver, folder, project_id=project_id,
            parse_warnings=sub_warnings, allowed_roots=allowed_roots,
            env_prefix=env_prefix,
        )
        if not merged.version:
            merged.version = sub.version
        source_paths.append(sub.source_path or folder)
        merged_warnings.extend(f"{tag} {w}" for w in sub_warnings)
        for env in sub.environments:
            if env.env_name in seen_envs:
                merged_warnings.append(
                    f"{tag} env_name 중복 — 첫 폴더 우선, 본 항목 skip "
                    f"(이중 집계 방지): {env.env_name}"
                )
                continue
            seen_envs.add(env.env_name)
            merged.environments.append(env)
        # 부가 dict 필드 first-wins 병합 — collect 시점엔 대부분 빈 dict이나
        # (router가 사후 주입) 향후 collect 단계 채움에 대비한 방어적 병합.
        for _attr in (
            "c_function_map", "swuds_function_map", "function_asil_from_suds",
            "component_asil_from_sds", "function_asil_from_srs",
            "function_name_to_swufn_from_suds",
        ):
            _dst = getattr(merged, _attr)
            for _k, _v in (getattr(sub, _attr, {}) or {}).items():
                _dst.setdefault(_k, _v)
    merged.source_path = ";".join(source_paths)
    return merged


def collect_swut_session(
    resolver: Any,
    project_id: str,
    *,
    jenkins_build_number: int | None = None,
    cache_root: str = "",
    log_folder: str | None = None,
    log_folders: list[str] | None = None,
    allowed_roots: list[str] | None = None,
    env_prefix: str = "SWTE",
) -> SwUTSession:
    """Jenkins 캐시 우선, 없으면 log_folder fallback.

    Args:
        resolver: file_resolver.
        project_id: 예) "HDPDM01".
        jenkins_build_number: Jenkins build 번호. None이면 latest.
        log_folder: fallback path (`U:\\...\\01.Log\\v<VER>_<DATE>`).
        log_folders: B2 — 다중 log_folder (예: KJPDS02 APP+BOOT 분리 폴더 통합
            빌드). **비어있지 않으면 log_folder(단일)보다 우선.** 2개 이상이면
            폴더별 collect 후 세션 병합 — env_name 중복 시 첫 폴더 우선 + 뒤
            항목 skip + 중복 경고 (이중 집계 방지). 상세 정책은
            `_collect_from_log_folders_merged` docstring.
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

    # 2) log_folder(s) fallback — B2: log_folders(비어있지 않으면) > log_folder 단일.
    effective_folders = [f for f in (log_folders or []) if f]
    if not effective_folders and log_folder:
        effective_folders = [log_folder]

    if len(effective_folders) == 1:
        # 단일 폴더 — 기존 경로 그대로 (병합/prefix 미적용, backward compat).
        return collect_from_log_folder(
            resolver, effective_folders[0], project_id=project_id,
            parse_warnings=warnings, allowed_roots=allowed_roots,
            env_prefix=env_prefix,
        )
    if effective_folders:
        return _collect_from_log_folders_merged(
            resolver, effective_folders, project_id=project_id,
            parse_warnings=warnings, allowed_roots=allowed_roots,
            env_prefix=env_prefix,
        )

    raise ValueError(
        "jenkins_build_number 또는 log_folder 둘 중 하나는 반드시 지정해야 합니다"
    )
