"""54차 — SwIT v2.02 / SwUT v3.01 양식 layout inspect 모듈.

회사 양식 (HDPDM01 NE_GN7) Coverage Report / SUTR / SITR 등 xlsx/xlsm template을
openpyxl로 inspect하여 label↔cell 매핑 + 신규 row(B17 TC stats, B22 Requirements,
Test Log AL marker) 위치를 자동 추출. v2.02 양식 빈 cell 누락 fix (54차 사용자 보고).

## 매칭 전략

각 정보 항목은 v2.02 후보 label을 우선 매칭 → 못 찾으면 v3.01 후보 label 매칭 →
모두 실패면 warnings 누적 + fallback_to_v301=True.

| 정보 | v2.02 후보 | v3.01 후보 |
|------|------------|------------|
| release_sw_version | "SW Version", "SW 버전" | "Release Name(SW)" |
| hw_version | "HW Version", "HW 버전" | "Test Target Version(HW)" |
| project_full_name | "Project Name", "Project" | 동일 |
| test_date | "Test Date", "테스트 일자" | 동일 |
| test_engineer | "Test Engineer", "테스트 엔지니어" | 동일 |
| final_test_result | "Final Test Result", "최종 결과" | 동일 |
| tc_stats_row (v2.02) | "Total TC", "Test Case Count", "TC Count" | (없음) |
| requirements_row (v2.02) | "Requirements/Design Coverage", "Requirements Coverage" | (없음) |
| test_log_extra_marker_col | header row "Marker" / "Pass/Fail Marker" | (없음) |

## 캐싱

sha256 keying + maxsize=4 LRU. 회사 양식 4개 (SwUT Cov / SUTR / SwIT Cov / SITR)
범위 내. 동일 template 반복 빌드 시 openpyxl load_workbook 1회만.

## ISO 26262 audit 영향

본 모듈은 audit 산출물 정확도 향상 (v2.02 빈 cell fill) — evidence_class 변경 없음.
manual review 의무 동일.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Literal, Optional

try:
    import openpyxl  # type: ignore
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]


@dataclass(frozen=True)
class CellRef:
    """label 셀의 (row, col) — 1-based. value cell은 머지 보정 후 col+1."""
    row: int
    col: int


@dataclass
class SwitLayout:
    """v2.02/v3.01 template inspect 결과.

    Attributes:
        detected_version: 매칭된 라벨 비율에 따른 추정 ("v2.02" / "v3.01" / "unknown").
        fallback_to_v301: True면 v2.02 후보 다수 실패 → v3.01 hardcode fallback 사용 권장.
        cover_labels: {"project_full_name": "Project", "asil_level": "ASIL Level", ...}.
            값은 template에서 실제 매칭된 label text — writer 함수가 이 라벨로 find_kv_row.
        test_summary_labels: 동일 패턴. v2.02면 "SW Version", v3.01이면 "Release Name(SW)".
        tc_stats_row: v2.02 양식의 TC 통계 row index (1-based). None이면 v3.01 (해당 row 없음).
        tc_stats_col_start: TC stats row의 첫 값 셀 col. None이면 자동 (label_col + 1) 사용.
        requirements_row: v2.02의 Requirements/Design Coverage row index. None이면 v3.01.
        deviation_header_cell: SITR Deviation 시트 헤더 위치 (참고용, 현재 미사용).
        test_log_header_cell: SITR Test Log 시트 헤더 위치 (참고용).
        test_log_extra_marker_col: v2.02의 추가 marker col (예: AL col). None이면 미적용.
        warnings: inspect 중 누락 라벨 / 시트 미발견 등 메시지.
    """
    detected_version: Literal["v2.02", "v3.01", "unknown"] = "unknown"
    fallback_to_v301: bool = False
    cover_labels: dict[str, str] = field(default_factory=dict)
    test_summary_labels: dict[str, str] = field(default_factory=dict)
    tc_stats_row: Optional[int] = None
    tc_stats_col_start: Optional[int] = None
    requirements_row: Optional[int] = None
    deviation_header_cell: Optional[CellRef] = None
    test_log_header_cell: Optional[CellRef] = None
    test_log_extra_marker_col: Optional[int] = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Candidate label 후보 (v2.02 → v3.01 fallback)
# ---------------------------------------------------------------------------

_COVER_CANDIDATES: dict[str, tuple[str, ...]] = {
    # field_name → (v2.02 후보, ..., v3.01 후보)
    "project_full_name": ("Project", "프로젝트"),
    "asil_level": ("ASIL Level", "ASIL"),
    "status": ("Status", "상태"),
    "validation_date": ("Validation Date", "검증 일자", "검증일"),
    "author": ("Author", "작성자"),
    "reviewer": ("Reviewer", "검토자"),
    "approver": ("Approver", "승인자"),
    "doc_id": ("Doc. ID", "Doc ID", "문서 번호"),
    "version": ("Version", "버전"),
    "build_timestamp": ("Build Timestamp", "빌드 시간"),
}

_TEST_SUMMARY_CANDIDATES: dict[str, tuple[str, ...]] = {
    "project_full_name": ("Project Name", "Project", "프로젝트명"),
    # v2.02 "SW Version" 우선, v3.01 "Release Name(SW)" fallback
    "release_sw_version": ("SW Version", "SW 버전", "Release Name(SW)"),
    "hw_version": ("HW Version", "HW 버전", "Test Target Version(HW)"),
    "test_date": ("Test Date", "테스트 일자", "시험 일자"),
    "test_engineer": ("Test Engineer", "테스트 엔지니어", "시험 담당"),
    "final_test_result": ("Final Test Result", "최종 결과", "최종 시험 결과"),
    # SUTR/SITR 전용
    "target_coverage": ("Target Coverage", "목표 커버리지"),
    "actual_coverage": ("Actual Coverage", "실측 커버리지"),
    "target_pass_ratio": ("Target Pass ratio", "Target Pass Ratio", "목표 Pass 비율"),
    "actual_pass_ratio": ("Actual Pass ratio", "Actual Pass Ratio", "실측 Pass 비율"),
}

# v2.02 양식 신규 row label 후보
_TC_STATS_LABELS: tuple[str, ...] = (
    "Total TC", "Test Case Count", "TC Count", "전체 TC", "TC 수",
)
_REQUIREMENTS_LABELS: tuple[str, ...] = (
    "Requirements/Design Coverage",
    "Requirements Coverage",
    "Design Coverage",
    "요구사항/설계 커버리지",
)
_TEST_LOG_MARKER_LABELS: tuple[str, ...] = (
    "Marker", "Pass/Fail Marker", "검수 표시", "통과 표시",
)


# ---------------------------------------------------------------------------
# Inspect helpers
# ---------------------------------------------------------------------------

def _find_sheet(wb, name_predicate) -> object | None:
    """workbook에서 predicate(name) True인 첫 시트 반환."""
    for n in wb.sheetnames:
        if name_predicate(n):
            return wb[n]
    return None


def _scan_label_cell(
    ws, candidates: tuple[str, ...], *, max_row: int = 60,
) -> tuple[Optional[CellRef], Optional[str]]:
    """시트의 첫 N행에서 candidates 중 하나 매칭되는 cell + 매칭 label 반환.

    매칭은 cell.value.strip() == candidate 정확 비교 (대소문자 구분).
    """
    if ws is None:
        return (None, None)
    for row in ws.iter_rows(min_row=1, max_row=max_row, values_only=False):
        for cell in row:
            v = cell.value
            if not isinstance(v, str):
                continue
            s = v.strip()
            if not s:
                continue
            for cand in candidates:
                if s == cand:
                    return (CellRef(row=cell.row, col=cell.column), cand)
    return (None, None)


def _scan_labels_in_sheet(
    ws, candidates_map: dict[str, tuple[str, ...]], *, max_row: int = 60,
) -> tuple[dict[str, str], dict[str, CellRef]]:
    """시트에서 여러 field_name별 candidate matching.

    Returns:
        (labels_found, cells_found):
            labels_found: {field_name: matched_label_text}
            cells_found: {field_name: CellRef(row, col)} (label cell — value는 col+1)
    """
    labels: dict[str, str] = {}
    cells: dict[str, CellRef] = {}
    for field_name, cands in candidates_map.items():
        cell_ref, matched = _scan_label_cell(ws, cands, max_row=max_row)
        if cell_ref and matched:
            labels[field_name] = matched
            cells[field_name] = cell_ref
    return labels, cells


def _detect_version_from_labels(
    test_summary_labels: dict[str, str],
) -> Literal["v2.02", "v3.01", "unknown"]:
    """Test Summary 라벨로 양식 버전 추정.

    "SW Version" / "HW Version" 매칭 → v2.02. "Release Name(SW)" / "Test Target
    Version(HW)" 매칭 → v3.01.
    """
    release_label = test_summary_labels.get("release_sw_version", "")
    hw_label = test_summary_labels.get("hw_version", "")
    v202_signals = sum(
        1 for lbl in (release_label, hw_label)
        if lbl in ("SW Version", "SW 버전", "HW Version", "HW 버전")
    )
    v301_signals = sum(
        1 for lbl in (release_label, hw_label)
        if lbl in ("Release Name(SW)", "Test Target Version(HW)")
    )
    if v202_signals > v301_signals:
        return "v2.02"
    if v301_signals > v202_signals:
        return "v3.01"
    return "unknown"


def _scan_tc_stats_row(ws) -> tuple[Optional[int], Optional[int]]:
    """Test Summary 시트에서 TC stats row 위치 탐색.

    candidate label 매칭 후 row 반환. col_start는 label_col + 1 (자동 보정).

    Returns:
        (tc_stats_row, tc_stats_col_start) — 둘 다 None이면 v3.01 (없음).
    """
    cell_ref, _ = _scan_label_cell(ws, _TC_STATS_LABELS, max_row=60)
    if cell_ref is None:
        return (None, None)
    return (cell_ref.row, cell_ref.col + 1)


def _scan_requirements_row(ws) -> Optional[int]:
    """Test Summary 시트에서 Requirements/Design Coverage row 탐색."""
    cell_ref, _ = _scan_label_cell(ws, _REQUIREMENTS_LABELS, max_row=60)
    return cell_ref.row if cell_ref else None


def _scan_test_log_marker_col(ws) -> Optional[int]:
    """Test Log 시트의 header row에서 marker column 탐색.

    회사 v2.02 양식이 AL column에 별도 marker label을 둔다고 보고됨 (53차 사용자).
    candidates에 정확 매칭되는 cell의 column 반환.
    """
    cell_ref, _ = _scan_label_cell(ws, _TEST_LOG_MARKER_LABELS, max_row=10)
    return cell_ref.col if cell_ref else None


# ---------------------------------------------------------------------------
# Internal inspect (캐시 entry)
# ---------------------------------------------------------------------------

def _inspect_internal(
    template_bytes: bytes, kind: Literal["coverage", "sitr"],
) -> SwitLayout:
    """openpyxl load_workbook → 시트별 inspect → SwitLayout 반환.

    openpyxl 미설치 또는 load 실패 시 fallback_to_v301=True + warnings 누적하여 반환.
    """
    if openpyxl is None:
        return SwitLayout(
            detected_version="unknown",
            fallback_to_v301=True,
            warnings=["openpyxl 미설치 — layout inspect 불가, v3.01 fallback"],
        )
    try:
        # SITR도 xlsm이라 keep_vba=True (data_only=False 기본).
        wb = openpyxl.load_workbook(
            io.BytesIO(template_bytes),
            keep_vba=(kind == "sitr"),
            data_only=False,
        )
    except Exception as e:
        return SwitLayout(
            detected_version="unknown",
            fallback_to_v301=True,
            warnings=[f"template load 실패 ({type(e).__name__}: {e!s:.80}) — v3.01 fallback"],
        )

    warnings: list[str] = []
    try:
        # Cover 시트
        cover_ws = _find_sheet(wb, lambda n: n.lower() == "cover")
        cover_labels: dict[str, str] = {}
        if cover_ws is not None:
            cover_labels, _ = _scan_labels_in_sheet(cover_ws, _COVER_CANDIDATES)
        else:
            warnings.append("Cover 시트 미발견 — cover_labels 비어 있음")

        # Test Summary 시트 — 53차 fix substring 매칭과 일치 (v2.02 "1.Test Summary")
        ts_ws = _find_sheet(wb, lambda n: "test summary" in n.lower())
        test_summary_labels: dict[str, str] = {}
        tc_stats_row: Optional[int] = None
        tc_stats_col_start: Optional[int] = None
        requirements_row: Optional[int] = None
        if ts_ws is not None:
            test_summary_labels, _ = _scan_labels_in_sheet(
                ts_ws, _TEST_SUMMARY_CANDIDATES,
            )
            # v2.02 신규 row 탐색
            tc_stats_row, tc_stats_col_start = _scan_tc_stats_row(ts_ws)
            requirements_row = _scan_requirements_row(ts_ws)
        else:
            warnings.append("Test Summary 시트 미발견 — test_summary_labels 비어 있음")

        # Test Log 시트 (SITR only)
        test_log_extra_marker_col: Optional[int] = None
        test_log_header_cell: Optional[CellRef] = None
        deviation_header_cell: Optional[CellRef] = None
        if kind == "sitr":
            log_ws = _find_sheet(wb, lambda n: "test log" in n.lower())
            if log_ws is not None:
                test_log_extra_marker_col = _scan_test_log_marker_col(log_ws)
                # header cell 위치 참고 (writer가 직접 find_kv_row 사용하지만 inspect 결과 참고용)
                tc_header, _ = _scan_label_cell(
                    log_ws, ("Test Case ID", "TC ID", "TC name"), max_row=10,
                )
                test_log_header_cell = tc_header
            dev_ws = _find_sheet(wb, lambda n: "deviation" in n.lower())
            if dev_ws is not None:
                dev_header, _ = _scan_label_cell(
                    dev_ws, ("Test Case ID", "TC ID"), max_row=10,
                )
                deviation_header_cell = dev_header

        # 양식 버전 추정
        detected_version = _detect_version_from_labels(test_summary_labels)

        # fallback 판정: v2.02 신규 row가 모두 없고 v3.01 라벨 매칭이 다수면 v3.01
        # → fallback_to_v301 False (정상 v3.01 양식). v2.02 라벨 매칭 0이면 fallback.
        v202_label_count = sum(
            1 for v in test_summary_labels.values()
            if v in ("SW Version", "SW 버전", "HW Version", "HW 버전")
        )
        fallback_to_v301 = detected_version == "v3.01" or (
            detected_version == "unknown" and v202_label_count == 0
        )

        if detected_version == "v2.02" and tc_stats_row is None:
            warnings.append(
                "v2.02 양식 추정되나 TC stats row label 미발견 — "
                f"후보 {_TC_STATS_LABELS}"
            )
        if detected_version == "v2.02" and requirements_row is None:
            warnings.append(
                "v2.02 양식 추정되나 Requirements/Design Coverage row label 미발견 — "
                f"후보 {_REQUIREMENTS_LABELS}"
            )

        return SwitLayout(
            detected_version=detected_version,
            fallback_to_v301=fallback_to_v301,
            cover_labels=cover_labels,
            test_summary_labels=test_summary_labels,
            tc_stats_row=tc_stats_row,
            tc_stats_col_start=tc_stats_col_start,
            requirements_row=requirements_row,
            deviation_header_cell=deviation_header_cell,
            test_log_header_cell=test_log_header_cell,
            test_log_extra_marker_col=test_log_extra_marker_col,
            warnings=warnings,
        )
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Public API + LRU cache
# ---------------------------------------------------------------------------

_LAYOUT_CACHE: dict[tuple[str, str], SwitLayout] = {}
_MAX_CACHE_SIZE = 4  # 회사 양식 4개 (SwUT Cov/SUTR + SwIT Cov/SITR) 범위


def inspect_swit_layout(
    template_bytes: bytes,
    kind: Literal["coverage", "sitr"],
) -> SwitLayout:
    """v2.02 또는 v3.01 양식 template을 inspect하여 SwitLayout 추출.

    sha256(template_bytes) + kind 키로 LRU 캐시. 동일 template 반복 빌드 시
    openpyxl load_workbook 1회만 호출.

    Args:
        template_bytes: 회사 양식 xlsx (coverage) 또는 xlsm (sitr) bytes.
        kind: "coverage" 또는 "sitr".

    Returns:
        SwitLayout — detected_version + 라벨 매핑 + 신규 row 위치 + warnings.
        openpyxl 미설치 또는 load 실패 시 fallback_to_v301=True + warnings 누적.
    """
    sha = hashlib.sha256(template_bytes).hexdigest()
    key = (sha, kind)
    cached = _LAYOUT_CACHE.get(key)
    if cached is not None:
        return cached
    layout = _inspect_internal(template_bytes, kind)
    # LRU evict (insertion order)
    if len(_LAYOUT_CACHE) >= _MAX_CACHE_SIZE:
        # 가장 오래된 entry 제거 (dict의 insertion order 활용 — Python 3.7+)
        oldest = next(iter(_LAYOUT_CACHE))
        del _LAYOUT_CACHE[oldest]
    _LAYOUT_CACHE[key] = layout
    return layout


def clear_layout_cache() -> None:
    """테스트/관리 용 — 캐시 초기화."""
    _LAYOUT_CACHE.clear()


def cache_size() -> int:
    """테스트 용 — 현재 캐시 entry 수."""
    return len(_LAYOUT_CACHE)


__all__ = [
    "CellRef",
    "SwitLayout",
    "inspect_swit_layout",
    "clear_layout_cache",
    "cache_size",
]
