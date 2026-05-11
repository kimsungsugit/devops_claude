"""Excel xlsx/xlsm 템플릿 빌더 공통 helper.

회사 표준 SwUT 빌더 (Coverage / SUTR) 가 공통으로 사용하는:
- 머지셀 anchor 보정 (회사 xlsx는 거의 모든 셀이 머지)
- label-value KV 쓰기
- 짧은 날짜 변환
- **xlsx/xlsm bytes 입력 검증** (ZIP bomb / 헤더 위조 방어)

검증 helper는 reviewer 권고에 따라 빌더 진입점에서 호출 의무.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any

# ZIP bomb 한계 — 압축 해제 후 100MB 초과 시 거부. 일반 xlsx/xlsm은 수 MB.
_MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024
# 단일 파일이 의심스러울 정도로 큰 경우 — 보통 sharedStrings.xml도 수 MB 이내
_MAX_SINGLE_FILE_SIZE = 50 * 1024 * 1024
# 압축비 상한 (decompressed / compressed). ZIP bomb은 보통 1000+.
_MAX_COMPRESSION_RATIO = 200

# Office Open XML (xlsx/xlsm/docx) 매직 바이트 — ZIP 헤더와 동일.
_XLSX_MAGIC = b"PK\x03\x04"


class TemplateValidationError(ValueError):
    """xlsx/xlsm bytes 입력이 유효하지 않을 때 — ZIP bomb 방어용."""


def validate_xlsx_template_bytes(data: bytes, *, label: str = "template") -> None:
    """xlsx/xlsm template bytes 검증 (Critical S — ZIP bomb / 헤더 위조 방어).

    Raises:
        TemplateValidationError: bytes가 유효한 xlsx/xlsm 아니거나 ZIP bomb 의심.
    """
    if not data:
        raise TemplateValidationError(f"{label} bytes empty")
    if data[:4] != _XLSX_MAGIC:
        raise TemplateValidationError(
            f"{label} magic bytes mismatch — 'PK\\x03\\x04' 헤더 부재"
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise TemplateValidationError(f"{label} not a valid ZIP: {e}")

    # xlsx/xlsm 필수 마커 (Open Office XML 구조) 확인
    namelist = zf.namelist()
    if not any(n.startswith("xl/") or n == "[Content_Types].xml" for n in namelist):
        raise TemplateValidationError(
            f"{label} Open Office XML 구조 미발견 — xl/ 또는 [Content_Types].xml 없음"
        )

    # ZIP bomb 검증: 압축비 + 총 크기 + 단일 파일 크기
    total_decompressed = 0
    for info in zf.infolist():
        if info.file_size > _MAX_SINGLE_FILE_SIZE:
            raise TemplateValidationError(
                f"{label} 단일 entry 크기 초과: {info.filename} = "
                f"{info.file_size:,} bytes (한도 {_MAX_SINGLE_FILE_SIZE:,})"
            )
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > _MAX_COMPRESSION_RATIO:
                raise TemplateValidationError(
                    f"{label} 압축비 ZIP bomb 의심: {info.filename} ratio={ratio:.0f}"
                )
        total_decompressed += info.file_size
        if total_decompressed > _MAX_DECOMPRESSED_SIZE:
            raise TemplateValidationError(
                f"{label} 총 압축 해제 크기 초과: {total_decompressed:,} bytes"
            )


# ---------------------------------------------------------------------------
# Sheet helpers (머지셀 보정)
# ---------------------------------------------------------------------------

def find_kv_row(ws: Any, label: str, max_row: int = 50) -> tuple[int, int] | None:
    """시트의 첫 N행에서 label 셀 위치(row,col) 찾기."""
    for row in ws.iter_rows(min_row=1, max_row=max_row, values_only=False):
        for cell in row:
            if cell.value and isinstance(cell.value, str) and cell.value.strip() == label:
                return (cell.row, cell.column)
    return None


def resolve_merge_anchor(ws: Any, row: int, col: int) -> tuple[int, int]:
    """좌표가 머지 영역 안이면 top-left anchor 좌표로 보정."""
    for mr in ws.merged_cells.ranges:
        if mr.min_row <= row <= mr.max_row and mr.min_col <= col <= mr.max_col:
            return (mr.min_row, mr.min_col)
    return (row, col)


def safe_write(ws: Any, row: int, col: int, value: Any) -> bool:
    """머지 영역 anchor 보정 후 쓰기. 머지된 비-anchor 셀이면 silent skip + False."""
    anchor_row, anchor_col = resolve_merge_anchor(ws, row, col)
    try:
        ws.cell(row=anchor_row, column=anchor_col).value = value
        return True
    except AttributeError:
        return False


def write_value_after_label(ws: Any, label: str, value: Any, max_row: int = 50) -> bool:
    """`label` 셀 옆 컬럼에 value 쓰기 (머지 영역 보정)."""
    pos = find_kv_row(ws, label, max_row)
    if not pos:
        return False
    row, col = pos
    target_col = col + 1
    for mr in ws.merged_cells.ranges:
        if mr.min_row <= row <= mr.max_row and mr.min_col <= col <= mr.max_col:
            target_col = mr.max_col + 1
            break
    return safe_write(ws, row, target_col, value)


def short_date(s: str) -> str:
    """`2024-02-19` → `240219` (회사 표준 파일명용)."""
    if not s:
        return ""
    m = re.match(r"(\d{2,4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if not m:
        return s.replace("-", "").replace("/", "")[:6]
    yy = m.group(1)[-2:]
    return f"{yy}{int(m.group(2)):02d}{int(m.group(3)):02d}"
