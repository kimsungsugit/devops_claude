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

import re
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
    "bin_values_into_bands",
    "metric_item_for_name",
    "parse_band_predicate",
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
    unbinned_count: int = 0   # metric 값 결측/비숫자로 밴드 미배정된 함수 수 (C3)
    worst_functions: List[Tuple[str, int]] = field(default_factory=list)

    @property
    def binned_count(self) -> int:
        return self.total_functions - self.unbinned_count

    @property
    def result(self) -> str:
        """Fail 밴드 함수 1개 이상이면 Fail, 아니면 Pass.

        주의: unbinned_count>0(metric 결측)이면 '미평가'를 Pass 로 오기재할 위험 →
        호출자는 ``unbinned_count`` 를 확인해 노란 표시할 것 (St201Result.parse_warnings).
        """
        return "Fail" if self.fail_count > 0 else "Pass"


@dataclass
class St201Result:
    total_functions: int = 0
    helix_version: str = ""
    old_version: bool = False
    module: str = ""        # 로그 폴더 모듈명 (APP_… / BOOT_…) — 컬럼 split 용
    metrics: Dict[str, MetricResult] = field(default_factory=dict)
    # 메트릭별 함수값 raw (템플릿 주도 재binning 용). key=MatrixItem.name (예: 'V_G').
    function_values: Dict[str, List[int]] = field(default_factory=dict)
    parse_warnings: List[str] = field(default_factory=list)

    def metric(self, st_id: str) -> Optional[MetricResult]:
        return self.metrics.get(st_id)

    def values_for(self, item: "MatrixItem") -> List[int]:
        return self.function_values.get(item.name, [])


# 템플릿 메트릭명(D열) → MatrixItem (substring, 소문자). Recursion/Duplicated/Stress 는
# HMR 부재 → None (Recursion=별도, Duplicated=PMD).
_NAME_TO_ITEM: List[Tuple[str, "MatrixItem"]] = [
    ("cyclomatic", MatrixItem.V_G),
    ("nesting", MatrixItem.LEVEL),
    ("calling", MatrixItem.CALLING),
    ("called", MatrixItem.CALLS),
    ("parameter", MatrixItem.PARAM),
    ("instruction", MatrixItem.STMT),
    ("path", MatrixItem.PATH),
    ("return", MatrixItem.RETURN),
    ("goto", MatrixItem.GOTO),
]

# parse 시 수집할 MatrixItem (function_values)
_VALUE_ITEMS: List["MatrixItem"] = [
    MatrixItem.V_G, MatrixItem.LEVEL, MatrixItem.CALLING, MatrixItem.CALLS,
    MatrixItem.PARAM, MatrixItem.STMT, MatrixItem.PATH, MatrixItem.RETURN, MatrixItem.GOTO,
]


def metric_item_for_name(name: str) -> Optional["MatrixItem"]:
    """템플릿 메트릭명 → MatrixItem. 매칭 없으면 None (수동/타 소스)."""
    low = (name or "").lower()
    for kw, item in _NAME_TO_ITEM:
        if kw in low:
            return item
    return None


def parse_band_predicate(label: str):
    """밴드 라벨('1 ~ 10','> 10','>=11','0','>0') → 술어 함수. 불가 시 None."""
    s = (label or "").replace(" ", "")
    if not s:
        return None
    m = re.match(r"^(\d+)~(\d+)$", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return lambda v: a <= v <= b
    m = re.match(r"^>=(\d+)$", s)
    if m:
        n = int(m.group(1))
        return lambda v: v >= n
    m = re.match(r"^>(\d+)$", s)
    if m:
        n = int(m.group(1))
        return lambda v: v > n
    m = re.match(r"^<=(\d+)$", s)
    if m:
        n = int(m.group(1))
        return lambda v: v <= n
    m = re.match(r"^<(\d+)$", s)
    if m:
        n = int(m.group(1))
        return lambda v: v < n
    m = re.match(r"^(\d+)$", s)
    if m:
        n = int(m.group(1))
        return lambda v: v == n
    return None


def _band_upper(label: str) -> Optional[int]:
    """밴드 라벨의 상한값. 'a ~ b'→b, '<= n'→n, '< n'→n-1, 단일 'n'→n. 상한 없으면 None."""
    s = (label or "").replace(" ", "")
    m = re.match(r"^(\d+)~(\d+)$", s)
    if m:
        return int(m.group(2))
    m = re.match(r"^<=(\d+)$", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^<(\d+)$", s)
    if m:
        return int(m.group(1)) - 1
    m = re.match(r"^(\d+)$", s)
    if m:
        return int(m.group(1))
    return None


def bin_values_into_bands(values: List[int], band_labels: List[str]) -> List[int]:
    """함수값들을 템플릿 밴드 라벨 순서대로 카운트. 밴드 겹치면 먼저 매칭한 밴드.

    rank1 audit fix: 첫(Pass) 밴드는 **하한 개방**(`v <= 상한`)으로 처리한다. 회사
    양식은 nesting/param 등 첫 밴드를 '1 ~ N' 으로 쓰지만 HIS metric 은 0 값을 가질
    수 있고(예: nesting=0 함수), 레퍼런스가 첫 밴드에 전체 함수수(859)를 기재하는
    것으로 보아 0 도 Pass 밴드에 포함하는 것이 정답. '1 ~ N' 의 0 누락을 방지.
    """
    preds = [parse_band_predicate(lbl) for lbl in band_labels]
    if band_labels:
        upper0 = _band_upper(band_labels[0])
        if upper0 is not None:
            preds[0] = lambda v, u=upper0: v <= u  # 첫 밴드 하한 개방
    counts = [0] * len(band_labels)
    for v in values:
        for i, p in enumerate(preds):
            if p is not None and p(v):
                counts[i] += 1
                break
    return counts


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
        binned = 0
        for it in functions:
            raw = it.get_matrix_value(mi)
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue  # 결측/비숫자 → 아래 unbinned 로 집계
            if val < 0:
                continue  # I3: HIS metric 음수는 비정상 → 미평가(unbinned), silent Pass 차단
            binned += 1
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
        mr.unbinned_count = total - binned
        # I1: 동점 tie-break를 라벨 2차 키로 재현성 확보
        offenders.sort(key=lambda t: (-t[1], t[0]))
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
        # 템플릿 주도 재binning 용 raw 함수값 수집 (모든 지원 MatrixItem)
        for it in mgr.list_result:
            for mi in _VALUE_ITEMS:
                try:
                    val = int(it.get_matrix_value(mi))
                except (TypeError, ValueError):
                    continue
                result.function_values.setdefault(mi.name, []).append(val)
        # C3: metric 결측 함수가 있으면 '미평가'를 Pass 로 오기재하지 않도록 경고
        for st_id, mr in result.metrics.items():
            if mr.unbinned_count > 0:
                result.parse_warnings.append(
                    f"{st_id}: {mr.unbinned_count}/{mr.total_functions} 함수 "
                    f"{mr.metric_code} 결측 — 미평가(Pass 아님, 검토 필요)"
                )
        return result
    finally:
        if tmp is not None:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass
