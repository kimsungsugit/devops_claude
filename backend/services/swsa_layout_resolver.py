"""SwSA 시트 레이아웃 해석 — 라벨 앵커 기반 (버전/컬럼 shift 흡수).

회사 SwSA 양식은 버전·시트마다 좌표가 다르다 (실측):
  - ST101~ST1001(LAYOUT-A): Test-Info 라벨 col B, 데이터 col C.
  - ST1101(LAYOUT-B): 라벨 col C, 데이터 col D (+1 shift).
  - v0.10 템플릿 vs v0.11 레퍼런스: ST101 Test Summary 표 컬럼이 +2 shift,
    행 수도 단일행 vs Mandatory/Required/Total 3행으로 상이.

하드코딩 좌표는 silent 오기재를 유발하므로, **라벨을 찾아 그 옆/아래 셀에 쓰는**
방식으로 모든 버전을 흡수한다. ``excel_template_utils.find_kv_row`` +
``resolve_merge_anchor`` 재사용.

ISO 26262: 좌표 오인은 audit evidence 위치 오류 → 라벨 미발견 시 명시적 신호
(silent skip 차단).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.services.excel_template_utils import find_kv_row, resolve_merge_anchor

__all__ = [
    "StSheetLayout",
    "find_value_target",
    "find_label_row",
    "detect_st_layout",
    "TEST_INFO_LABELS",
]

# Test-Information 블록 라벨 (모든 ST 시트 공통). 값은 라벨 바로 오른쪽 셀.
TEST_INFO_LABELS: Dict[str, str] = {
    "analysis_round": "분석차수",
    "sw_version": "SW Ver.",
    "tester": "Tester",
    "debugger": "Debugger",
}


@dataclass
class StSheetLayout:
    """ST 시트 한 장의 라벨 앵커 해석 결과."""

    sheet_name: str
    # field_key -> (write_row, write_col)  값을 쓸 셀 (anchor 보정 완료)
    test_info: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    data_col_offset: Optional[int] = None  # 데이터 컬럼 - 라벨 컬럼 (보통 1)
    round_label_col: Optional[int] = None  # '분석차수' 라벨 컬럼 (layout 판정용)
    missing: List[str] = field(default_factory=list)

    @property
    def layout(self) -> str:
        """라벨 컬럼으로 LAYOUT-A(라벨 col B) vs LAYOUT-B(라벨 col C, ST1101) 추정.

        값 컬럼이 아니라 라벨 컬럼 기준 — 병합 라벨(B4:C4)이 값을 D로 밀어도 정확.
        """
        if self.round_label_col is None:
            return "?"
        return "A" if self.round_label_col <= 2 else "B"

    @property
    def ok(self) -> bool:
        return not self.missing


def find_label_row(
    ws: Any, label: str, max_row: int = 120, *,
    label_col: Optional[int] = None, min_row: int = 1,
) -> Optional[Tuple[int, int]]:
    """라벨 셀 (row, col) 탐색. 없으면 None.

    Args:
        label_col: 지정 시 해당 컬럼의 라벨만 매칭 (동명 라벨 충돌 방지 —
            예: Cover 'Author' 가 사인오프 헤더 I2 와 doc-block C30 양쪽 존재).
        min_row: 탐색 시작 행.
    """
    if label_col is None and min_row == 1:
        return find_kv_row(ws, label, max_row=max_row)
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, values_only=False):
        for cell in row:
            if label_col is not None and cell.column != label_col:
                continue
            if cell.value and isinstance(cell.value, str) and cell.value.strip() == label:
                return (cell.row, cell.column)
    return None


def _label_end_col(ws: Any, r: int, c: int) -> int:
    """(r,c) 라벨이 병합돼 있으면 병합 max_col, 아니면 c.

    회사 양식은 시트마다 라벨을 단일 셀(B4) 또는 병합(B4:C4)로 둔다. 병합 라벨에
    단순 c+1 을 쓰면 값 셀이 라벨 병합 안으로 들어가 anchor 로 되돌아가 **라벨을
    덮어쓰는** 버그가 난다 (v0.10 ST201 실측). 병합 끝 다음 칸을 값 셀로 쓴다.
    """
    for mr in ws.merged_cells.ranges:
        if mr.min_row <= r <= mr.max_row and mr.min_col <= c <= mr.max_col:
            return mr.max_col
    return c


def find_value_target(
    ws: Any, label: str, *, col_delta: int = 1, row_delta: int = 0, max_row: int = 120,
    label_col: Optional[int] = None, min_row: int = 1,
) -> Optional[Tuple[int, int]]:
    """라벨을 찾아 값을 쓸 셀 좌표(merge anchor 보정) 반환.

    Args:
        col_delta: 라벨 기준 값 셀의 컬럼 오프셋 (기본 +1 = 오른쪽).
        row_delta: 행 오프셋 (기본 0 = 같은 행). 표 헤더 아래 데이터는 +1.
        label_col / min_row: 동명 라벨 충돌 방지용 제약 (find_label_row 참조).

    Returns:
        (row, col) 또는 라벨 미발견 시 None.
    """
    pos = find_label_row(ws, label, max_row=max_row, label_col=label_col, min_row=min_row)
    if pos is None:
        return None
    r, c = pos
    # 병합 라벨이면 병합 끝 기준으로 오프셋 (col_delta=1 이 라벨 안으로 안 들어가게)
    base_col = _label_end_col(ws, r, c) if col_delta > 0 else c
    return resolve_merge_anchor(ws, r + row_delta, base_col + col_delta)


def detect_st_layout(ws: Any, *, max_row: int = 120) -> StSheetLayout:
    """ST 시트의 Test-Information 블록 라벨 앵커 해석.

    분석차수/SW Ver./Tester/Debugger 라벨을 찾아 각 값 셀 좌표를 계산한다.
    라벨 미발견은 ``missing`` 에 누적 (silent skip 차단).
    """
    layout = StSheetLayout(sheet_name=getattr(ws, "title", ""))
    for key, label in TEST_INFO_LABELS.items():
        pos = find_label_row(ws, label, max_row=max_row)
        if pos is None:
            layout.missing.append(label)
            continue
        r, c = pos
        base_col = _label_end_col(ws, r, c)   # 병합 라벨 끝 기준
        target = resolve_merge_anchor(ws, r, base_col + 1)
        layout.test_info[key] = target
        if key == "analysis_round":
            layout.round_label_col = c
        if layout.data_col_offset is None:
            layout.data_col_offset = target[1] - c
    return layout
