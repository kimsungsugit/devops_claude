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
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional

try:
    import openpyxl  # type: ignore
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

# 54-fix C2: ZIP bomb 방어 backstop — caller에 의존하지 않고 본 모듈에서도 검증.
from backend.services.excel_template_utils import (
    TemplateValidationError,
    validate_xlsx_template_bytes,
)


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
        tc_stats_row: **55-fix 이후 의미 = data row** (label_row + 1). 회사 v2.02 SITR
            양식은 라벨이 row 17 가로 배치 (B17~F17), 데이터는 row 18에 위치. writer가
            본 row에 직접 fill. None이면 v3.01 (해당 row 없음). 이전 (55-fix 이전)
            의미는 "label row"였음 — semantic breaking change. 55-fix-2 W1 docstring 갱신.
        tc_stats_col_start: TC stats row의 첫 데이터 셀 col. **55-fix 이후 = label_col**
            (가로 배치라 라벨 col부터 데이터 시작). 이전 = label_col + 1.
        requirements_row: v2.02의 Requirements/Design Coverage row index. None이면 v3.01.
            **주의**: 회사 v2.02 SITR 양식은 row 22에 default 'SwITS' 채워져 있어
            우리 코드가 추가 fill 필요 없음. `'■  Requirements/Design Coverage'` 후보
            추가 시 row 20 (헤더) 매칭되어 덮어쓰기 위험 — 추가 금지 (W5).
        deviation_header_cell: SITR Deviation 시트 헤더 위치 (참고용, 현재 미사용).
        test_log_header_cell: SITR Test Log 시트 헤더 위치 (참고용).
        test_log_extra_marker_col: v2.02의 추가 marker col (예: AL col). None이면 미적용.
        tc_stats_label_missing: **56차 신규** — v2.02 Coverage 양식 fallback 감지. 회사
            Coverage Report v2.02 양식은 row 17이 빈 row (사용자 수동 입력 영역)라
            label 매칭 실패. 본 flag True면 writer가 라벨도 함께 stamp. SITR은 label
            존재 → 항상 False (기존 path 유지).
        requirements_label_missing: 동일 패턴. v2.02 Coverage가 B20에 헤더 부재 시 True.
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
    tc_stats_label_missing: bool = False
    requirements_label_missing: bool = False
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

# v2.02 양식 신규 row label 후보 — 55-fix: 사용자 실 산출물 보고로 'Total Number of TCs'
# 추가. 회사 v2.02 SITR 양식의 실 라벨이 candidate-tuple에 없어 row 검출 실패했음.
_TC_STATS_LABELS: tuple[str, ...] = (
    "Total Number of TCs",  # v2.02 SITR 실 양식 (55-fix 사용자 보고)
    "Total TC", "Test Case Count", "TC Count",
    "전체 TC", "TC 수",
)
_REQUIREMENTS_LABELS: tuple[str, ...] = (
    "Requirements/Design Coverage",
    "Requirements Coverage",
    "Design Coverage",
    "요구사항/설계 커버리지",
)
# 55-fix 주의: 회사 v2.02 SITR 양식은 row 20에 '■  Requirements/Design Coverage'
# 헤더 + row 22에 이미 'SwITS' default 채워져 있음. ■ prefix 후보를 추가하면
# requirements_row=20이 검출되어 우리 writer가 라벨 row를 덮어씀. 따라서 추가 금지.
# 만약 향후 회사 양식이 SwITS default 안 갖는 양식 도입 시 별도 검토.
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
    """Test Summary 시트에서 TC stats data row 위치 탐색.

    55-fix: 회사 v2.02 SITR 양식은 라벨 row가 헤더 (B17~F17 가로 배치)이고
    data는 label_row + 1 (B18~F18)에 위치. label_row를 그대로 반환하면 writer가
    label을 덮어씀. 본 함수는 **data row** 반환.

    또한 col_start = label_col (라벨이 가로 배치라 첫 라벨 col부터 데이터 시작).

    Returns:
        (tc_stats_data_row, tc_stats_col_start) — 둘 다 None이면 v3.01 (없음).
    """
    cell_ref, _ = _scan_label_cell(ws, _TC_STATS_LABELS, max_row=60)
    if cell_ref is None:
        return (None, None)
    # data row = 라벨 row + 1, 데이터 시작 col = 라벨 col (가로 배치)
    return (cell_ref.row + 1, cell_ref.col)


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

    54-fix C2: ZIP bomb 방어 — 외부에서 validate_xlsx_template_bytes 호출하지 않고
    바로 inspect 호출 시도 거부. 압축비 / 단일 파일 크기 / 총 크기 한도는
    excel_template_utils 정책 동일.

    openpyxl 미설치 또는 load 실패 시 fallback_to_v301=True + warnings 누적하여 반환.
    """
    if openpyxl is None:
        return SwitLayout(
            detected_version="unknown",
            fallback_to_v301=True,
            warnings=["openpyxl 미설치 — layout inspect 불가, v3.01 fallback"],
        )
    # 54-fix C2: ZIP bomb / magic byte 사전 검증.
    try:
        validate_xlsx_template_bytes(template_bytes, label=f"layout inspect ({kind})")
    except TemplateValidationError as e:
        return SwitLayout(
            detected_version="unknown",
            fallback_to_v301=True,
            warnings=[f"template 입력 검증 실패 — {e!s:.150}"],
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

        # 56차 T306 — v2.02 Coverage 양식 label-missing fallback.
        # 회사 Coverage Report v2.02는 row 17 (TC stats) + row 20 (Requirements)을
        # 사용자 수동 입력 영역으로 두어 template에 라벨 부재 → label 매칭 실패 →
        # 기존엔 silent skip. fallback path: B17/B20 cell이 None이면 default position
        # 사용 + label_missing=True 표시 → writer가 라벨도 함께 stamp.
        tc_stats_label_missing = False
        requirements_label_missing = False
        if detected_version == "v2.02" and ts_ws is not None:
            if tc_stats_row is None:
                # row 17 B열이 빈 cell이면 fallback 활성
                try:
                    b17 = ts_ws.cell(17, 2).value  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover — openpyxl edge case
                    b17 = "_"
                if b17 is None or (isinstance(b17, str) and b17.strip() == ""):
                    tc_stats_row = 18  # data row = label row + 1
                    tc_stats_col_start = 2  # B 열
                    tc_stats_label_missing = True
                    warnings.append(
                        "v2.02 양식 Coverage: TC stats row label 미발견 → "
                        "default position (row=17 label / row=18 data, col=B) fallback. "
                        "writer가 라벨도 stamp (56차 T306)."
                    )
                else:
                    warnings.append(
                        "v2.02 양식 추정되나 TC stats row label 미발견 + B17 비어있지 않음 — "
                        f"fallback 미적용. 후보 {_TC_STATS_LABELS}"
                    )
            if requirements_row is None:
                try:
                    b20 = ts_ws.cell(20, 2).value  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    b20 = "_"
                if b20 is None or (isinstance(b20, str) and b20.strip() == ""):
                    requirements_row = 20
                    requirements_label_missing = True
                    warnings.append(
                        "v2.02 양식 Coverage: Requirements row label 미발견 → "
                        "default position (row=20, col=B) fallback. writer가 헤더+"
                        "라벨도 stamp (56차 T306)."
                    )
                else:
                    warnings.append(
                        "v2.02 양식 추정되나 Requirements row label 미발견 + B20 비어있지 않음 — "
                        f"fallback 미적용. 후보 {_REQUIREMENTS_LABELS}"
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
            tc_stats_label_missing=tc_stats_label_missing,
            requirements_label_missing=requirements_label_missing,
            warnings=warnings,
        )
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Public API + LRU cache
# ---------------------------------------------------------------------------

# 54-fix W1/W3: cache stampede + StopIteration 방어 + maxsize 4→8 (thrashing 여유).
# 자체 LRU dict → threading.Lock 보호. Semaphore(3) SwUT + Semaphore(2) SwIT 동시
# 빌드 + 향후 C1 fix로 SwUT도 layout 호출 시 5건 동시 thread 가능.
_LAYOUT_CACHE: dict[tuple[str, str], SwitLayout] = {}
_MAX_CACHE_SIZE = 8  # W3 — 회사 양식 4개 + 시험용/향후 추가 여유
_CACHE_LOCK = threading.Lock()


def inspect_swit_layout(
    template_bytes: bytes,
    kind: Literal["coverage", "sitr"],
) -> SwitLayout:
    """v2.02 또는 v3.01 양식 template을 inspect하여 SwitLayout 추출.

    sha256(template_bytes) + kind 키로 LRU 캐시. 동일 template 반복 빌드 시
    openpyxl load_workbook 1회만 호출.

    54-fix W1: cache stampede 방어 — _CACHE_LOCK으로 hit/miss + insertion 직렬화.
    동일 key 동시 miss 시 두 번째 thread는 첫 번째의 결과를 cache hit으로 받음.

    Args:
        template_bytes: 회사 양식 xlsx (coverage) 또는 xlsm (sitr) bytes.
        kind: "coverage" 또는 "sitr".

    Returns:
        SwitLayout — detected_version + 라벨 매핑 + 신규 row 위치 + warnings.
        openpyxl 미설치 또는 load 실패 시 fallback_to_v301=True + warnings 누적.
    """
    sha = hashlib.sha256(template_bytes).hexdigest()
    key = (sha, kind)
    # Fast path — lock 밖 확인
    with _CACHE_LOCK:
        cached = _LAYOUT_CACHE.get(key)
        if cached is not None:
            return cached
    # Miss path — inspect (load_workbook 비용 ~수십 ms, lock 밖)
    layout = _inspect_internal(template_bytes, kind)
    # Insertion + LRU evict — lock 안 (stampede 시 dup work 가능하나 결과 동일)
    with _CACHE_LOCK:
        # Stampede 검사 — 다른 thread가 먼저 set 했으면 그 값을 반환 (메모리 일관성)
        existing = _LAYOUT_CACHE.get(key)
        if existing is not None:
            return existing
        if len(_LAYOUT_CACHE) >= _MAX_CACHE_SIZE:
            # 가장 오래된 entry 제거 (dict insertion order, Python 3.7+).
            # 빈 dict 진입 방어 (W1 StopIteration) — len check가 보장
            try:
                oldest = next(iter(_LAYOUT_CACHE))
                del _LAYOUT_CACHE[oldest]
            except (StopIteration, KeyError):  # pragma: no cover — race-safe guard
                pass
        _LAYOUT_CACHE[key] = layout
        return layout


def clear_layout_cache() -> None:
    """테스트/관리 용 — 캐시 초기화."""
    with _CACHE_LOCK:
        _LAYOUT_CACHE.clear()


def cache_size() -> int:
    """테스트 용 — 현재 캐시 entry 수."""
    with _CACHE_LOCK:
        return len(_LAYOUT_CACHE)


__all__ = [
    "CellRef",
    "SwitLayout",
    "inspect_swit_layout",
    "clear_layout_cache",
    "cache_size",
]
