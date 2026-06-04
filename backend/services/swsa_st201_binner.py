"""SwSA ST201 (Code Metric) 빈너 — QAC HMR(HIS Metrics) → 메트릭 밴드 집계.

ST201 시트의 코드 메트릭(복잡도) 결과는 QAC HMR(HIS Metrics Report)의 함수별
메트릭을 회사 양식 밴드로 재집계해 산출한다. 기존 ``qac_parser.QACDataManager``
(PRQA/Helix QAC HMR 파서)를 그대로 재사용한다.

회사 양식 ST201 밴드 (템플릿 2.ST201 rows 31~39 실측)::

    ST201 Cyclomatic Complexity      (STCYC=V_G)    1~10 P / 11~20 C / 21~30 C / >30 F
    ST202 Maximum Nesting Level      (STMIF=LEVEL)  1~5  P / 6~10  C / >10 F
    ST203 Max Function Calling No.   (STM29=CALLING)0~5  P / 6~10  C / >=11 F
    ST204 Max Function Called No.    (STCALL=CALLS) 0~7  P / 8~12  C / >=13 F

ST205 Recursion(STNRA) / ST206 Duplicated 는 HMR 에 없어 본 모듈 비대상
(ST205 = 별도 도구/수동, ST206 = PMD → swsa_pmd_parser).

verdict: Fail = Fail 밴드 함수 1개 이상. Conditional 은 '수정불가 사유 명시'가
필요한 수동 판정이라 자동은 Pass 로 두되 conditional_count 를 노출해 aggregator
가 노란 표시하도록 한다.

ISO 26262: HIS 메트릭은 ASIL 무관 권장. evidence 'auto-generated draft'.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from backend.services.qac_parser import MatrixItem, QACDataManager

__all__ = [
    "MetricBand",
    "MetricResult",
    "St201Result",
    "ST201_METRICS",
    "bin_metric_functions",
    "parse_st201_from_hmr",
]

# st_id -> (metric_code, MatrixItem, 표시명, [(upper_inclusive|None, label, verdict), ...])
ST201_METRICS: Dict[str, Tuple[str, MatrixItem, str, List[Tuple[Optional[int], str, str]]]] = {
    "ST201": ("STCYC", MatrixItem.V_G, "Cyclomatic Complexity",
              [(10, "1 ~ 10", "Pass"), (20, "11 ~ 20", "Conditional"),
               (30, "21 ~ 30", "Conditional"), (None, "> 30", "Fail")]),
    "ST202": ("STMIF", MatrixItem.LEVEL, "Maximum Nesting Level",
              [(5, "1 ~ 5", "Pass"), (10, "6 ~ 10", "Conditional"), (None, "> 10", "Fail")]),
    "ST203": ("STM29", MatrixItem.CALLING, "Maximum Function Calling Number",
              [(5, "0 ~ 5", "Pass"), (10, "6 ~ 10", "Conditional"), (None, ">= 11", "Fail")]),
    "ST204": ("STCALL", MatrixItem.CALLS, "Maximum Function Called Number",
              [(7, "0 ~ 7", "Pass"), (12, "8 ~ 12", "Conditional"), (None, ">= 13", "Fail")]),
}


@dataclass
class MetricBand:
    label: str          # '1 ~ 10'
    verdict: str        # 'Pass' / 'Conditional' / 'Fail'
    count: int = 0      # 해당 밴드 함수 수


@dataclass
class MetricResult:
    st_id: str
    metric_code: str
    name: str
    bands: List[MetricBand]
    total_functions: int = 0
    max_value: int = 0
    fail_count: int = 0
    conditional_count: int = 0
    worst_functions: List[Tuple[str, int]] = field(default_factory=list)

    @property
    def result(self) -> str:
        """Fail 밴드 함수가 1개 이상이면 Fail, 아니면 Pass."""
        return "Fail" if self.fail_count > 0 else "Pass"


@dataclass
class St201Result:
    total_functions: int = 0
    helix_version: str = ""
    old_version: bool = False
    metrics: Dict[str, MetricResult] = field(default_factory=dict)
    parse_warnings: List[str] = field(default_factory=list)

    def metric(self, st_id: str) -> Optional[MetricResult]:
        return self.metrics.get(st_id)


def bin_metric_functions(functions: list) -> Dict[str, MetricResult]:
    """함수 메트릭 리스트 → ST201~ST204 밴드 집계.

    Args:
        functions: ``get_matrix_value(MatrixItem)`` / ``file_name`` /
            ``function_name`` 를 노출하는 객체 리스트 (qac_parser.HISItem).

    Returns:
        st_id → MetricResult.
    """
    out: Dict[str, MetricResult] = {}
    total = len(functions)
    for st_id, (code, mi, name, band_defs) in ST201_METRICS.items():
        bands = [MetricBand(label=lbl, verdict=v) for (_u, lbl, v) in band_defs]
        mr = MetricResult(st_id=st_id, metric_code=code, name=name, bands=bands,
                          total_functions=total)
        offenders: List[Tuple[str, int]] = []
        for it in functions:
            raw = it.get_matrix_value(mi)
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue
            mr.max_value = max(mr.max_value, val)
            # 밴드 배정 (upper inclusive, 마지막 None = 무한대)
            for bi, (upper, _lbl, verdict) in enumerate(band_defs):
                if upper is None or val <= upper:
                    bands[bi].count += 1
                    if verdict == "Fail":
                        mr.fail_count += 1
                        label = f"{it.file_name}::{it.function_name}".strip(":")
                        offenders.append((label, val))
                    elif verdict == "Conditional":
                        mr.conditional_count += 1
                    break
        offenders.sort(key=lambda t: -t[1])
        mr.worst_functions = offenders[:10]
        out[st_id] = mr
    return out


def _sniff_old_version(html_head: str) -> bool:
    """HMR HTML 앞부분으로 PRQA(구) vs Helix QAC(신) 판별."""
    low = html_head.lower()
    if "helix qac" in low:
        return False
    if "prqa" in low:
        return True
    return False  # 기본: 신 버전


def _resolve_path(source: Union[str, bytes, Path]) -> Tuple[Path, Optional[tempfile._TemporaryFileWrapper]]:
    """bytes 면 NamedTemporaryFile 로 dump (qac_parser 가 Path 만 받음)."""
    if isinstance(source, (bytes, bytearray)):
        tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        tmp.write(bytes(source))
        tmp.flush()
        tmp.close()
        return Path(tmp.name), tmp
    return Path(source), None


def parse_st201_from_hmr(
    source: Union[str, bytes, Path],
    *,
    old_version: Optional[bool] = None,
) -> St201Result:
    """QAC HMR → ST201Result (ST201~ST204 밴드 집계).

    Args:
        source: HMR HTML 경로/bytes.
        old_version: None 이면 내용으로 자동 판별 (PRQA vs Helix QAC).

    Returns:
        St201Result. 파싱 실패 시 parse_warnings 누적.
    """
    path, tmp = _resolve_path(source)
    result = St201Result()
    try:
        if not path.exists():
            result.parse_warnings.append(f"HMR 파일 없음: {path}")
            return result

        if old_version is None:
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:6000]
            except OSError:
                head = ""
            old_version = _sniff_old_version(head)
        result.old_version = old_version

        mgr = QACDataManager()
        ok = mgr.read_file(old_version, path)
        if not ok or not mgr.list_result:
            # 신/구 교차 재시도 (자동판별 오인 대비)
            mgr = QACDataManager()
            ok = mgr.read_file(not old_version, path)
            if ok and mgr.list_result:
                result.old_version = not old_version
            else:
                result.parse_warnings.append(
                    f"HMR 파싱 실패 (old_version={old_version}) — "
                    f"err={mgr.parse_error!r}. 구 PRQA 포맷은 미지원일 수 있음."
                )
                return result

        result.total_functions = len(mgr.list_result)
        result.metrics = bin_metric_functions(mgr.list_result)
        return result
    finally:
        if tmp is not None:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass
