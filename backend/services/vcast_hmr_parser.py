"""VectorCAST aggregate metrics report parser (60차 F6-C 라운드).

회사 Jenkins 빌드 산출물 ``Jenkins_PDSM_UT_metrics_report.html`` /
``Jenkins_PDSM_IT_metrics_report.html`` 양식의 ``col_metric`` table을 parse
하여 함수별 **Function Calls coverage** metric을 추출. KJPDS02 v1.01 Coverage
Report 양식의 row 6 (Function Calls) stamp source로 사용.

양식 구조 (T421 라이브 분석):
    <table>
      <thead>
        <th class="col_unit">Unit</th>            <-- 파일명 (예: bats.c)
        <th class="col_subprogram">Subprogram</th> <-- 함수명 (예: BATS_Init)
        <th class="col_complexity">Complexity</th>
        <th class="col_metric">Functions</th>     <-- Function coverage 'X / Y (Z%)'
        <th class="col_metric">Function Calls</th> <-- 본 parser target
      </thead>
      <tbody>
        <tr>
          <td class="col_unit">bats.c</td>
          <td class="col_subprogram">BATS_Init</td>
          <td class="col_complexity">1</td>
          <td class="success col_metric">1 / 1 (100%)</td>
          <td class="col_metric"> </td>          <-- 빈 cell = leaf function
        </tr>
        ...
        <tr>
          <th class="col_unit">TOTALS</th>       <-- TOTALS row skip
          ...
        </tr>
      </tbody>
    </table>

ISO 26262 Tool Qualification:
    - evidence_class: "auto-generated draft"
    - ASIL A: reviewer 검토 후 evidence 사용 가능

Fail-safe:
    - HTML_MAX_BYTES=8MB DoS 방지
    - BeautifulSoup ImportError → ok=False
    - parse 실패 시 빈 dict + parse_warnings 누적
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    from bs4 import BeautifulSoup  # type: ignore
    _HAS_BS4 = True
except ImportError:  # pragma: no cover - hook fail-safe
    BeautifulSoup = None  # type: ignore[assignment]
    _HAS_BS4 = False


HTML_MAX_BYTES = 8 * 1024 * 1024  # 8MB — HMR 보통 600KB 이하
_METRIC_RE = re.compile(
    r"(\d+)\s*/\s*(\d+)\s*\((\d+(?:\.\d+)?)\s*%\)"
)


@dataclass
class FunctionCallsMetric:
    """함수별 Function Calls coverage."""
    function_name: str       # 'BATS_Init' / 'g_SystemStatusCheck'
    unit_file: str = ""      # 'bats.c' (같은 파일 내 row가 &nbsp;면 직전 값 상속)
    covered_calls: int = 0
    total_calls: int = 0
    coverage_pct: float = 0.0
    complexity: int = 0
    # Function coverage (covered/total) — 옵션 보조 metric (audit 참고용).
    functions_covered: int = 0
    functions_total: int = 0


@dataclass
class HmrParseResult:
    """HMR HTML 파싱 결과.

    F6 자체평가 Round 1 C2: `metrics_by_name`은 함수명 → 모든 매칭 list. 같은
    함수명이 다른 unit_file에 존재 (예: bats.c::Init + vehicle.c::Init) 시
    caller가 ambiguous 판단 + silent wrong-pick 차단. `metrics`는 backward-compat
    하지만 첫 매칭만 보존 (audit 신뢰성 위해 caller는 `metrics_by_name` 사용 권장).
    """
    ok: bool
    metrics: dict[str, FunctionCallsMetric] = field(default_factory=dict)
    metrics_by_name: dict[str, list[FunctionCallsMetric]] = field(default_factory=dict)
    parse_warnings: list[str] = field(default_factory=list)
    total_rows_scanned: int = 0

    def to_dict(self) -> dict[str, Any]:
        ambiguous = sum(1 for ms in self.metrics_by_name.values() if len(ms) > 1)
        return {
            "ok": self.ok,
            "metric_count": len(self.metrics),
            "ambiguous_count": ambiguous,
            "rows_scanned": self.total_rows_scanned,
            "sample": [
                {
                    "function_name": m.function_name,
                    "unit_file": m.unit_file,
                    "covered_calls": m.covered_calls,
                    "total_calls": m.total_calls,
                    "coverage_pct": m.coverage_pct,
                }
                for m in list(self.metrics.values())[:20]
            ],
            "parse_warnings": self.parse_warnings,
            "tool_qualification": {
                "evidence_class": "auto-generated draft",
                "asil_a_usage": "reviewer 검토 후 evidence 사용 가능",
                "format_assumption": (
                    "VectorCAST aggregate metrics report "
                    "(Jenkins_PDSM_UT/IT_metrics_report.html, col_metric class)"
                ),
            },
        }


def _parse_metric_cell(text: str) -> tuple[int, int, float] | None:
    """'X / Y (Z%)' → (X, Y, Z). 빈 cell → None."""
    if not text:
        return None
    s = text.strip().replace("\xa0", " ").replace("&nbsp;", " ").strip()
    if not s:
        return None
    m = _METRIC_RE.search(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), float(m.group(3))


def _safe_int(text: str, default: int = 0) -> int:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return default


def parse_hmr_html(
    html_bytes: bytes,
    *,
    parse_warnings: list[str] | None = None,
) -> HmrParseResult:
    """HMR HTML bytes → HmrParseResult.

    Fail-safe:
        - bs4 미설치 → ok=False
        - HTML_MAX_BYTES 초과 → ok=False
        - 함수 metric 0건 → ok=False
        - 개별 row parse 실패는 skip + parse_warnings 누적

    Returns:
        HmrParseResult. metrics: {function_name: FunctionCallsMetric}
    """
    warnings = parse_warnings if parse_warnings is not None else []

    if not _HAS_BS4:
        return HmrParseResult(
            ok=False,
            parse_warnings=warnings + ["BeautifulSoup 미설치 — HMR 파싱 불가"],
        )
    if not html_bytes:
        return HmrParseResult(
            ok=False,
            parse_warnings=warnings + ["HMR HTML bytes 비어있음"],
        )
    if len(html_bytes) > HTML_MAX_BYTES:
        return HmrParseResult(
            ok=False,
            parse_warnings=warnings + [
                f"HMR 크기 {len(html_bytes):,} > 한도 {HTML_MAX_BYTES:,} — DoS 방지",
            ],
        )

    try:
        soup = BeautifulSoup(html_bytes, "html.parser")  # type: ignore[misc]
    except Exception as e:
        return HmrParseResult(
            ok=False,
            parse_warnings=warnings + [
                f"BeautifulSoup parse 실패 — {type(e).__name__}: {e}",
            ],
        )

    metrics: dict[str, FunctionCallsMetric] = {}
    metrics_by_name: dict[str, list[FunctionCallsMetric]] = {}
    rows_scanned = 0
    last_unit_file = ""

    # col_metric class 가진 td를 가진 tr만 추출 (TOTALS row는 th라 skip)
    for tr in soup.find_all("tr"):
        # data row만 — td (th가 아닌)
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 4:
            continue
        rows_scanned += 1

        # col_unit / col_subprogram / col_complexity / col_metric x2
        try:
            unit_cell = tds[0].get_text(strip=True)
            subprogram_cell = tds[1].get_text(strip=True)
            complexity_cell = tds[2].get_text(strip=True)
            functions_cell = tds[3].get_text(strip=True) if len(tds) > 3 else ""
            calls_cell = tds[4].get_text(strip=True) if len(tds) > 4 else ""
        except Exception as e:
            warnings.append(f"HMR row {rows_scanned} parse 실패: {type(e).__name__}")
            continue

        # unit_file 상속 — &nbsp; 또는 빈 cell이면 직전 row 값 사용
        unit_clean = unit_cell.replace("\xa0", "").strip()
        if unit_clean:
            last_unit_file = unit_clean
        unit_file = last_unit_file

        # function_name 비면 skip
        function_name = subprogram_cell.strip()
        if not function_name:
            continue

        # Function Calls metric parse (빈 cell = leaf function, covered_calls/total_calls=0)
        calls_parsed = _parse_metric_cell(calls_cell)
        functions_parsed = _parse_metric_cell(functions_cell)

        if calls_parsed is None and functions_parsed is None:
            # 둘 다 metric 없으면 이 row 무의미 → skip
            continue

        covered_calls, total_calls, coverage_pct = (
            calls_parsed if calls_parsed else (0, 0, 0.0)
        )
        functions_covered, functions_total = (
            (functions_parsed[0], functions_parsed[1]) if functions_parsed else (0, 0)
        )

        metric_obj = FunctionCallsMetric(
            function_name=function_name,
            unit_file=unit_file,
            covered_calls=covered_calls,
            total_calls=total_calls,
            coverage_pct=coverage_pct,
            complexity=_safe_int(complexity_cell),
            functions_covered=functions_covered,
            functions_total=functions_total,
        )
        # F6 자체평가 Round 1 C2: 함수명별 모든 매칭 누적 (audit silent wrong-pick 차단).
        # metrics는 backward-compat (첫 매칭). metrics_by_name이 caller 권장 API.
        # Round 2 W6 fix: 같은 (unit_file, function_name) 중복 row (vcast quirk) 시
        # dedup — false ambiguous → false negative stamp skip 방지.
        bucket = metrics_by_name.setdefault(function_name, [])
        if not any(m.unit_file == unit_file for m in bucket):
            bucket.append(metric_obj)
        if function_name not in metrics:
            metrics[function_name] = metric_obj

    if not metrics:
        return HmrParseResult(
            ok=False,
            parse_warnings=warnings + [
                "HMR metric 0건 추출 — 양식 불일치 추정 "
                "(col_metric class table 없음 또는 row 구조 변경)"
            ],
            total_rows_scanned=rows_scanned,
        )

    return HmrParseResult(
        ok=True,
        metrics=metrics,
        metrics_by_name=metrics_by_name,
        parse_warnings=warnings,
        total_rows_scanned=rows_scanned,
    )


__all__ = [
    "FunctionCallsMetric",
    "HmrParseResult",
    "parse_hmr_html",
    "HTML_MAX_BYTES",
]
