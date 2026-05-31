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

from .design_tokens import (
    ASIL_A_FILL_RGB as _ASIL_A_FILL_RGB,
    ASIL_B_FILL_RGB as _ASIL_B_FILL_RGB,
    ASIL_C_FILL_RGB as _ASIL_C_FILL_RGB,
    ASIL_D_FILL_RGB as _ASIL_D_FILL_RGB,
    ASIL_QM_FILL_RGB as _ASIL_QM_FILL_RGB,
    FAIL_FILL_RGB as _FAIL_FILL_RGB,
    USER_INPUT_FILL_RGB as _USER_INPUT_FILL_RGB,
    USER_INPUT_PLACEHOLDER,
)

try:
    import openpyxl  # type: ignore
    from openpyxl.styles import PatternFill  # type: ignore
    _HAS_PATTERN_FILL = True
except ImportError:  # pragma: no cover - openpyxl 미설치 fail-safe
    openpyxl = None  # type: ignore[assignment]
    PatternFill = None  # type: ignore[assignment]
    _HAS_PATTERN_FILL = False

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


class BuildMetaValidationError(ValueError):
    """빌더 입력 메타가 유효하지 않을 때 — endpoint 노출 전 입력 신뢰 경계 (deep-reviewer X3)."""


# Hyundai/Mobis 표준 release 버전 형식. 미충족 시 파일명 깨짐(`_v__240219_R.xlsx`).
_RELEASE_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
# yyyy-mm-dd 또는 yyyy/mm/dd 또는 yy-mm-dd
_TEST_DATE_RE = re.compile(r"^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}")


_MAX_NAME_LEN = 100   # 사람 이름 / Test Engineer / Author 등 최대 길이
_MAX_ISSUE_TEXT_LEN = 2000  # deviation issue_text 셀 한도 (xlsx 32767 한도보다 훨씬 작게)
_DOC_ID_SEQ_RE = re.compile(r"^\d+$")


def _safe_repr(v: str, limit: int = 40) -> str:
    """reviewer X8: 에러 메시지에 사용자 입력 그대로 노출 안 되도록 truncate + repr."""
    return repr(v)[:limit]


def validate_name_field(value: str, field_name: str, *, allow_empty: bool = True) -> None:
    """test_engineer/author/approver/reviewer 등 사람 이름 필드 검증 (H1 Critical).

    - 길이 100자 이내
    - 줄바꿈(`\\n`/`\\r`) 금지 — xlsx 셀 깨짐 방지

    Raises:
        BuildMetaValidationError
    """
    if not value:
        if allow_empty:
            return
        raise BuildMetaValidationError(f"{field_name} is empty")
    if len(value) > _MAX_NAME_LEN:
        raise BuildMetaValidationError(
            f"{field_name} 길이 {len(value)} > {_MAX_NAME_LEN} 한도"
        )
    if "\n" in value or "\r" in value:
        raise BuildMetaValidationError(
            f"{field_name}에 줄바꿈 문자 포함 — 단일 라인 필요 (값={_safe_repr(value)})"
        )


def validate_build_meta(
    release_sw_version: str,
    test_date: str,
    *,
    doc_id_sequence: str = "",
    test_engineer: str = "",
    author: str = "",
    approver: str = "",
    reviewer: str = "",
) -> None:
    """빌더 진입에서 필수 입력 검증 (deep-reviewer X3 + 5차 H1/H2).

    Raises:
        BuildMetaValidationError: 빈 string / 형식 미충족 시.
    """
    if not release_sw_version or not release_sw_version.strip():
        raise BuildMetaValidationError(
            "release_sw_version is empty — 빈 string은 파일명 `_v__...` 깨짐"
        )
    if not _RELEASE_VERSION_RE.match(release_sw_version.strip()):
        raise BuildMetaValidationError(
            f"release_sw_version {_safe_repr(release_sw_version)} 형식 미충족 — "
            "'\\d+.\\d+(.\\d+)?' 필요"
        )
    if not test_date or not test_date.strip():
        raise BuildMetaValidationError("test_date is empty")
    if not _TEST_DATE_RE.match(test_date.strip()):
        raise BuildMetaValidationError(
            f"test_date {_safe_repr(test_date)} 형식 미충족 — yyyy-mm-dd / yyyy/mm/dd 필요"
        )
    # H2: doc_id_sequence는 digit만 허용 (빈 string OK)
    if doc_id_sequence and not _DOC_ID_SEQ_RE.match(doc_id_sequence):
        raise BuildMetaValidationError(
            f"doc_id_sequence {_safe_repr(doc_id_sequence)} 비-digit — Doc ID 체계 위반"
        )
    # H1: 사람 이름 필드 4개 검증
    validate_name_field(test_engineer, "test_engineer")
    validate_name_field(author, "author")
    validate_name_field(approver, "approver")
    validate_name_field(reviewer, "reviewer")


def truncate_cell_text(value: Any, max_len: int = _MAX_ISSUE_TEXT_LEN) -> tuple[str, bool]:
    """xlsx 셀 한도(32,767자) 훨씬 이내로 truncate (H3 — uncaught IllegalCharacterError 방어).

    Returns:
        (truncated_value, was_truncated)
    """
    s = str(value) if value is not None else ""
    if len(s) <= max_len:
        return (s, False)
    return (s[:max_len] + " …(truncated)", True)


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

    try:
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
    finally:
        # I3 (deep-reviewer): infolist 한도 초과로 raise 시에도 zf 명시적 close.
        zf.close()


# 빌더가 placeholder 시트 (예: 1.Traceability TC×Function 매트릭스 미구현) 셀에 부착하는
# 명시적 마커. consistency_checker / audit 도구가 같은 string으로 감지해서 evidence로
# 잘못 분류하지 않도록 한다 (시나리오 A self-validation false positive 방어).
BLANK_MARKUP = (
    "BLANK — auto-generated placeholder (TC×Function matrix pending). "
    "ISO 26262 evidence 사용 전 수동 작성 필수."
)


def sheet_is_blank_placeholder(ws: Any) -> bool:
    """시트 anchor 영역(A1~A3, B1~B3)에 BLANK_MARKUP이 있는지 확인.

    Returns:
        True면 빌더가 작성한 placeholder 시트 — consistency_checker는 해당 시트의
        데이터 추출을 skip하고 parse_warnings에 등록해야 함.
    """
    if ws is None:
        return False
    for r in range(1, 4):
        for c in range(1, 4):
            try:
                v = ws.cell(row=r, column=c).value
            except (AttributeError, IndexError):
                continue
            if v and isinstance(v, str) and v.startswith("BLANK"):
                return True
    return False


def has_vba_macros(data: bytes) -> bool:
    """xlsx/xlsm 안에 ``xl/vbaProject.bin`` entry 존재 여부.

    ``True``면 SUTR 빌더 출력 시 매크로가 ZIP entry로 보존됨. 단, **매크로 실행 가능성을
    보장하지는 않음** — VBA 코드가 시트 ref / Defined Name을 가리키는 경우 빌더의 셀
    변경으로 stale ref 깨질 위험 (deep-reviewer W2).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "xl/vbaProject.bin" in zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


_VBA_REF_PATTERNS = (
    re.compile(rb"Cells\s*\(", re.IGNORECASE),
    re.compile(rb"Sheets\s*\(", re.IGNORECASE),
    re.compile(rb"Names\s*\(", re.IGNORECASE),
    re.compile(rb"Range\s*\(", re.IGNORECASE),
)


def build_release_history_row(
    meta: Any, *, doc_kind: str = "",
    out_warnings: list[str] | None = None,
) -> list[dict[str, str]]:
    """55-fix — 산출물별 release entry single row (사용자 결정 B).

    이전: `collect_git_history`로 git log 10건 채워서 audit reviewer 혼동
        (commit hash + 자동 commit + 매일 snapshot이 산출물 history로 보임).
    현재: 산출물의 release_sw_version + test_date + author 1 row만.
        reviewer/approver는 audit 입력으로 빈칸 둠.

    55-fix-2 W6: release_sw_version 또는 test_date 빈 시 warning 누적 +
        빈 cell silent fill 방지. router는 Pydantic으로 검증되지만 내부 호출
        (회귀, PoC, dataclass default)에서 빈 값 위험 — audit 추적성 보호.

    Args:
        meta: BuildMetaBase 또는 sub class (release_sw_version, test_date, author 속성).
        doc_kind: 옵션 — "SwUT Coverage Report" / "SwUT SUTR" / "SwIT Coverage Report"
            / "SwIT SITR" — description 식별 (W2 표준화).
        out_warnings: 옵션 — warning 누적 list. 빈 입력 사유 추가 (W6).

    Returns:
        list[1 row dict]. _write_history_sheet에 전달.
    """
    release = (getattr(meta, "release_sw_version", "") or "").strip()
    test_date = (getattr(meta, "test_date", "") or "").strip()
    author = getattr(meta, "author", "") or ""

    # 55-fix-2 W6 + 55-fix-3 W9: 빈 입력 audit 추적성 — silent fill 차단.
    # ISO 26262 audit 책임자 식별 필수 — author 누락도 검증.
    if out_warnings is not None:
        ctx = f" [{doc_kind}]" if doc_kind else ""  # I6: doc_kind context 부착
        if not release:
            out_warnings.append(
                f"History row release_sw_version 빈 string — meta.release_sw_version 누락 "
                f"(audit reviewer가 산출물에서 빈 version cell을 데이터 누락으로 오해 가능){ctx}"
            )
        if not test_date:
            out_warnings.append(
                f"History row test_date 빈 string — meta.test_date 누락{ctx}"
            )
        # 55-fix-3 W9: author 누락 — ISO 26262 audit 책임자 식별 필수
        if not author:
            out_warnings.append(
                f"History row author 빈 string — meta.author 누락 "
                f"(audit reviewer 책임자 식별 불가){ctx}"
            )

    # date format: yyyy-mm-dd → yy.mm.dd (collect_git_history와 동일)
    date_short = ""
    if len(test_date) >= 10:
        # "2026-05-14" → "26.05.14"
        try:
            normalized = test_date.replace("/", "-")
            parts = normalized.split("-")
            if len(parts) >= 3:
                yy = parts[0][-2:]
                mm = f"{int(parts[1]):02d}"
                dd = f"{int(parts[2][:2]):02d}"
                date_short = f"{yy}.{mm}.{dd}"
        except (ValueError, IndexError):
            date_short = test_date[:8]

    description = f"Initial release v{release}" if release else "Initial release"
    if doc_kind:
        description = f"{description} ({doc_kind})"

    return [{
        "version": f"v{release}" if release else "",
        "date": date_short,
        "description": description,
        "author": str(author)[:50],
        "reviewer": "",
        "approver": "",
    }]


def collect_git_history(
    repo_root: str | None = None,
    *,
    limit: int = 10,
) -> list[dict[str, str]]:
    """git log → History 시트 자동 채움용 row list (T134).

    55-fix 이후 SwUT/SwIT 빌더는 `build_release_history_row` 사용. git log 전체 표기는
    audit reviewer가 산출물 history로 혼동했음 (commit hash + 자동 commit + snapshot).
    본 함수는 유지 (backward compat) — 별도 호출처 또는 테스트 회귀에서 사용.

    Returns:
        list[{version, date, description, author, reviewer, approver}].
        git 명령 실패 시 빈 list.
    """
    import os
    import subprocess
    cwd = repo_root or os.getcwd()
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}",
             "--pretty=format:%h\x1f%ai\x1f%an\x1f%s"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []

    out: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 4:
            continue
        sha, iso_date, author, subject = parts[0], parts[1], parts[2], parts[3]
        # iso_date "2024-02-19 10:44:13 +0900" → "24.02.19"
        date_short = ""
        if len(iso_date) >= 10:
            yy = iso_date[2:4]
            mm = iso_date[5:7]
            dd = iso_date[8:10]
            date_short = f"{yy}.{mm}.{dd}"
        out.append({
            "version": f"v{sha[:7]}",
            "date": date_short,
            "description": subject[:200],
            "author": author[:50],
            "reviewer": "",
            "approver": "",
        })
    return out


def inspect_vba_refs(data: bytes) -> list[str]:
    """VBA 매크로의 stale ref 위험 패턴 감지 (5차 reviewer I1).

    ``vbaProject.bin`` 안 raw bytes에서 ``Cells(`` / ``Sheets(`` / ``Names(`` / ``Range(``
    같은 cell/sheet 참조 호출을 grep. 발견되면 빌더의 셀 변경으로 stale ref가 될 수 있어
    warning 권장.

    Returns:
        발견된 패턴 이름 list (예: ``["Cells(", "Sheets("]``). 빈 list면 의심 패턴 없음.
        VBA entry 없거나 읽기 실패 시도 빈 list.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "xl/vbaProject.bin" not in zf.namelist():
                return []
            vba_bytes = zf.read("xl/vbaProject.bin")
    except (zipfile.BadZipFile, OSError, KeyError):
        return []

    found: list[str] = []
    for pat in _VBA_REF_PATTERNS:
        if pat.search(vba_bytes):
            # 패턴 source에서 시각화용 이름만 추출 (예: ``rb"Cells\s*\("`` → ``"Cells("``).
            label = (
                pat.pattern.decode("ascii", errors="replace")
                .replace("\\s*", "")
                .replace("\\(", "(")
            )
            found.append(label)
    return found


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


def clear_data_range(
    ws: Any,
    *,
    start_row: int,
    end_row: int,
    start_col: int,
    end_col: int,
    preserve_formula: bool = True,
    preserve_merged_anchor: bool = True,
    sentinel_patterns: list[str] | None = None,
) -> int:
    """라운드 D T601: 시트의 data row 영역 clear (template-copy partial overwrite 결함 fix).

    SwUT/SwIT builder가 template-copy 전략 사용 시 양식의 default 데이터
    (예: 이전 release의 419 함수, 4 deviation 등)를 clear하지 않고 신규 데이터를
    일부만 덮어쓰기 → audit 신뢰성 무너짐. 본 helper로 builder가 stamp 전에
    data row 영역을 명시 clear.

    Args:
        ws: openpyxl Worksheet.
        start_row / end_row: clear 대상 row range (inclusive, 1-based).
        start_col / end_col: clear 대상 col range (inclusive, 1-based).
        preserve_formula: True면 `=` 시작 cell (수식) 보존 — Test Summary 같은
            cross-sheet reference 수식 보호.
        preserve_merged_anchor: True면 머지 영역의 비-anchor cell은 건드리지 않음
            (anchor만 clear) — 머지 깨짐 방지.
        sentinel_patterns: 이 substring 중 하나를 포함한 cell 발견 시 그 row
            직전까지만 clear. 예: ['End of Document', '< End', '■ Appendix']
            — 양식의 끝 마커/Appendix 보호 (F7 자체평가 Round 1 C1/C3 fix).

    Returns:
        cleared cell count.
    """
    if start_row > end_row or start_col > end_col:
        return 0
    # F7 자체평가 R1 C1/C3 + R2 N2: sentinel 사전 탐지 — end_row 조기 종료.
    # N2 fix: substring 매칭 (`pat in v`)이 false positive — 함수명 'AppendixHelper'
    # 등이 'Appendix' substring 매칭하여 잘못 clear 무력화. strict 매칭으로 변경:
    # - 양식 끝 마커는 '<', '■', '※' prefix (예: '< End of Document >', '■ Appendix')
    # - 또는 strip 후 pat과 exact / startswith 매칭
    # - 'TOTALS' / 'GRAND TOTALS' 단독 cell만 매칭 (포함 부분 매칭 X)
    if sentinel_patterns:
        actual_end = end_row
        for r in range(start_row, end_row + 1):
            for c in range(start_col, end_col + 1):
                try:
                    v = ws.cell(row=r, column=c).value
                except (AttributeError, IndexError):
                    continue
                if not isinstance(v, str):
                    continue
                v_stripped = v.strip()
                for pat in sentinel_patterns:
                    # 양식 마커는 보통 cell 단독으로 존재 (다른 텍스트 미혼합)
                    # strict 매칭 3가지: exact / startswith '<'/'■'/'※' + pat / pat이 단독 단어
                    if v_stripped == pat:
                        actual_end = r - 1
                        break
                    if v_stripped.startswith(("<", "■", "※")) and pat in v_stripped:
                        actual_end = r - 1
                        break
                if actual_end != end_row:
                    break
            if actual_end != end_row:
                break
        end_row = actual_end
        if start_row > end_row:
            return 0
    cleared = 0
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            try:
                cell = ws.cell(row=r, column=c)
            except (AttributeError, IndexError):
                continue
            if cell.value is None:
                continue
            # 수식 보존
            if preserve_formula and isinstance(cell.value, str) and cell.value.startswith("="):
                continue
            # 머지 영역 비-anchor 보존
            if preserve_merged_anchor:
                anchor_r, anchor_c = resolve_merge_anchor(ws, r, c)
                if (anchor_r, anchor_c) != (r, c):
                    continue
            try:
                cell.value = None
                cleared += 1
            except AttributeError:
                continue
    return cleared


def auto_expand_row_block(
    ws: Any,
    *,
    insert_at_row: int,
    amount: int,
    template_row_idx: int,
    copy_style: bool = True,
    copy_merge: bool = True,
    copy_dimension: bool = True,
    max_col_scan: int | None = None,
) -> int:
    """라운드 73 T801: row 자동 확장 — template row의 style/merge/dimension 복제.

    회사 v3.01/v2.02 양식은 고정 sample slot (Coverage 5~15 row, Consistency 30 row 등).
    실데이터(1941 TC × 60 fn / 5000+ TC 미래)가 slot 초과 시 stamp 잘림 → 본 helper로
    insert_rows + template 단일 row의 style/merge/dimension 복제하여 양식 일관성 유지.

    Args:
        ws: openpyxl Worksheet.
        insert_at_row: 신규 row가 들어갈 위치 (1-based). 기존 이 row는 amount만큼 downshift.
        amount: 삽입할 row 수.
        template_row_idx: style/merge/dimension 복제할 template row (1-based).
            ⚠️ template_row_idx >= insert_at_row면 insert 후 template_row_idx += amount.
            본 함수는 insert 전에 style을 capture하므로 호출자가 인지 필요.
        copy_style: cell._style (font/fill/border/number_format/alignment 등) 복제.
        copy_merge: template row의 single-row merge range를 신규 row마다 동일 col span으로 추가.
            multi-row merge는 skip (복잡도 차단).
        copy_dimension: row_dimensions.height 복제.
        max_col_scan: style 복제 시 최대 col (None이면 ws.max_column).

    Returns:
        실제 삽입된 row 수 (실패 시 0).

    Side effects:
        - ws.merged_cells.ranges가 openpyxl 내부에서 자동 offset 보정 (insert_rows 표준 동작).
        - End-of-Document sentinel ('< End of Document >')는 insert_at_row 이상이면 자동 downshift.

    Raises:
        없음. 실패 시 silent 0 반환 + 호출자가 warning 누적.

    Performance:
        single-row insert가 N회 호출되면 O(N²) cost (openpyxl insert_rows는 매번
        전체 cell shift). 대량 row 필요 시 amount를 N으로 묶어 1회 호출 권장
        (raw insert_rows 1회 + 그 후 style replication N회 = O(N) cost).
    """
    if openpyxl is None or amount <= 0 or insert_at_row < 1 or template_row_idx < 1:
        return 0

    # 1) Capture template state BEFORE insert (template_row_idx 위치가 shift되기 전)
    template_merges: list[tuple[int, int]] = []  # single-row (row, col_min, col_max)
    template_multi_row_merges: list[tuple[int, int, int, int]] = []  # (row_offset, height, col_min, col_max)
    if copy_merge:
        # template_row_idx가 multi-row merge의 첫 row 또는 안쪽일 때 그 블록 전체 capture.
        # 회사 v3.01 SUTR Test Result는 1 TC당 6-row 단위 block merge (B17:B22 등).
        # auto_expand이 6-row block 단위로 호출되면 block 전체 multi-row merge 복제.
        for mr in list(ws.merged_cells.ranges):
            if mr.min_row == template_row_idx and mr.max_row == template_row_idx:
                template_merges.append((mr.min_col, mr.max_col))
            elif mr.min_row == template_row_idx and mr.max_row > template_row_idx:
                # multi-row merge — template_row를 첫 row로 한 block.
                height = mr.max_row - mr.min_row + 1
                template_multi_row_merges.append((0, height, mr.min_col, mr.max_col))

    template_height: float | None = None
    if copy_dimension:
        rd = ws.row_dimensions.get(template_row_idx)
        if rd is not None:
            template_height = getattr(rd, "height", None)

    max_c = max_col_scan or ws.max_column
    template_styles: list[tuple[int, Any]] = []
    if copy_style:
        import copy as _copy
        for c in range(1, max_c + 1):
            try:
                src_cell = ws.cell(row=template_row_idx, column=c)
                if getattr(src_cell, "has_style", False):
                    template_styles.append((c, _copy.copy(src_cell._style)))
            except (AttributeError, IndexError):
                continue

    # 2) Insert rows — openpyxl 내장 merged_cells offset 보정 적용
    try:
        ws.insert_rows(insert_at_row, amount=amount)
    except (AttributeError, ValueError, TypeError):
        return 0

    # 3) Apply captured style/merge/dimension to each new row
    import copy as _copy
    try:
        from openpyxl.utils import get_column_letter  # type: ignore
    except ImportError:
        get_column_letter = None  # type: ignore[assignment]

    for offset in range(amount):
        new_row = insert_at_row + offset

        if copy_style:
            for col_idx, style in template_styles:
                try:
                    ws.cell(row=new_row, column=col_idx)._style = _copy.copy(style)
                except (AttributeError, IndexError):
                    continue

        if copy_dimension and template_height is not None:
            try:
                ws.row_dimensions[new_row].height = template_height
            except (AttributeError, KeyError):
                pass

        if copy_merge and get_column_letter is not None:
            for min_col, max_col in template_merges:
                try:
                    start_ref = f"{get_column_letter(min_col)}{new_row}"
                    end_ref = f"{get_column_letter(max_col)}{new_row}"
                    ws.merge_cells(f"{start_ref}:{end_ref}")
                except (AttributeError, ValueError):
                    continue

    # multi-row merge 복제 (block 단위) — caller가 block size N의 정확한 배수로 amount 지정 시.
    # 회사 v3.01 SUTR Test Result는 6-row block (B17:B22 → B23:B28 → ...). amount % height == 0 시
    # 신규 row 전체에 동일 col span으로 multi-row merge 적용.
    if copy_merge and get_column_letter is not None and template_multi_row_merges:
        for _row_off, height, min_col, max_col in template_multi_row_merges:
            if height <= 1 or amount % height != 0:
                continue
            blocks = amount // height
            for b in range(blocks):
                block_start = insert_at_row + b * height
                block_end = block_start + height - 1
                try:
                    start_ref = f"{get_column_letter(min_col)}{block_start}"
                    end_ref = f"{get_column_letter(max_col)}{block_end}"
                    ws.merge_cells(f"{start_ref}:{end_ref}")
                except (AttributeError, ValueError):
                    continue

    return amount


def push_sentinel_to_last_row(
    ws: Any,
    *,
    sentinel_text: str = "< End of Document >",
    search_max_row: int | None = None,
) -> int | None:
    """라운드 73 T804 helper: '< End of Document >' sentinel이 데이터 row 중간에 있으면
    실제 마지막 데이터 row 뒤로 이동.

    insert_rows 사용 시 sentinel이 row 중간에 박힐 수 있어 audit 시각 깨짐 — 본 helper로
    sentinel을 ws.max_row 위치로 push.

    Args:
        ws: Worksheet.
        sentinel_text: 찾을 sentinel text (exact match, strip 후).
        search_max_row: scan 한계 (None이면 ws.max_row).

    Returns:
        sentinel이 이동된 새 row 번호 (None이면 sentinel 미발견).
    """
    if openpyxl is None:
        return None

    scan_end = search_max_row or ws.max_row
    # 라운드 89 perf — ws.max_column을 루프 밖으로 1회 hoist. openpyxl의 max_column은
    # property로 매 호출마다 전체 셀을 순회(O(cells))하므로, for r 루프 안에서 호출하면
    # O(rows × cells) = O(n²)가 된다 (py-spy: _write_test_log 시간의 99.7%가 여기).
    # 본 함수는 읽기 후 sentinel 값만 이동 — 컬럼 수 불변이라 hoist는 동작 동일.
    max_col = ws.max_column
    found_row: int | None = None
    found_col: int | None = None
    for r in range(1, scan_end + 1):
        for c in range(1, max_col + 1):
            try:
                v = ws.cell(row=r, column=c).value
            except (AttributeError, IndexError):
                continue
            if isinstance(v, str) and v.strip() == sentinel_text:
                found_row, found_col = r, c
                break
        if found_row is not None:
            break

    if found_row is None:
        return None

    # 실제 데이터 last row 찾기 (sentinel 위치 제외, 그 위에서 마지막 non-empty)
    last_data_row = found_row
    for r in range(found_row + 1, scan_end + 1):
        for c in range(1, max_col + 1):
            try:
                v = ws.cell(row=r, column=c).value
            except (AttributeError, IndexError):
                continue
            if v is not None and (not isinstance(v, str) or v.strip()):
                last_data_row = r
                break

    if last_data_row == found_row:
        return found_row  # 이미 마지막

    # sentinel을 last_data_row + 1로 이동
    try:
        ws.cell(row=found_row, column=found_col).value = None
        ws.cell(row=last_data_row + 1, column=found_col).value = sentinel_text
        return last_data_row + 1
    except (AttributeError, IndexError):
        return found_row


def update_cross_refs_after_row_expansion(
    ws: Any,
    *,
    old_totals_row: int,
    new_totals_row: int,
    scan_max_row: int = 30,
    scan_max_col: int = 30,
) -> int:
    """라운드 76 T1101: 양식 cross-ref formula의 hardcoded row reference 동적 갱신.

    회사 ★개발템플릿 V3 SwUTCV 4.Coverage R5 `=E25` / R6 `=L25` 같은 hardcoded row
    reference가 양식 default 가정 TOTALS row (예: 25 — 15 함수 slot용). c_parser
    primary merge 활성 시 row 폭증 (60→377) 후 R25는 c_parser 함수 row가 되어
    cross-ref formula 의미 깨짐. 본 helper로 `=E25` → `=E{new_totals_row}` 자동 갱신.

    Args:
        ws: openpyxl Worksheet.
        old_totals_row: 양식 default TOTALS row (보통 25).
        new_totals_row: row 폭증 후 실제 TOTALS row 위치.
        scan_max_row: cross-ref formula 탐색 row 한계 (보통 양식 헤더 30 row 안).
        scan_max_col: cross-ref formula 탐색 col 한계.

    Returns:
        갱신된 cell 수.

    Policy:
        - regex `=([A-Z]+){old_totals_row}\\b` (단어 경계) 매칭 — `=E25` ✓, `=E250` ✗
        - cross-sheet ref (`'2.Traceability'!H9` 등 `!` 포함)는 변경 안 함
        - calculated formula (`=(E5-F5)/E5` 같은 R{old}가 아닌 R5/R6) 영향 없음
        - merge anchor 보정 후 safe_write
        - idempotent: 이미 new_totals_row 참조하는 cell은 변경 안 함 (regex 매칭 0)

    backward-compat:
        old_totals_row == new_totals_row 시 변경 0 (auto_expand 미가동 케이스).
    """
    if openpyxl is None or old_totals_row == new_totals_row:
        return 0
    pattern = re.compile(rf"=([A-Z]+){old_totals_row}\b")
    updated = 0
    max_r = min(ws.max_row, scan_max_row)
    max_c = min(ws.max_column, scan_max_col)
    for r in range(1, max_r + 1):
        for c in range(1, max_c + 1):
            try:
                v = ws.cell(row=r, column=c).value
            except (AttributeError, IndexError):
                continue
            if not isinstance(v, str) or not v.startswith("="):
                continue
            # cross-sheet ref skip — `'시트명'!cell` 또는 `시트명!cell` 모두
            if "!" in v:
                continue
            # `\g<1>` 명시 — Python re가 `\1396`을 group 139로 잘못 해석하는 것 방지.
            new_v = pattern.sub(rf"=\g<1>{new_totals_row}", v)
            if new_v == v:
                continue
            if safe_write(ws, r, c, new_v):
                updated += 1
    return updated


# 23차 T192 / 29차 W17: 시각 강조 RGB + placeholder 텍스트는
# ``design_tokens`` 단일 출처에서 import (위 import 블록 참조).


def _apply_fill(ws: Any, row: int, col: int, rgb: str) -> bool:
    """openpyxl PatternFill 적용 — openpyxl 미설치 / 머지셀 비-anchor면 silent False."""
    if not _HAS_PATTERN_FILL:
        return False
    anchor_row, anchor_col = resolve_merge_anchor(ws, row, col)
    try:
        ws.cell(row=anchor_row, column=anchor_col).fill = PatternFill(  # type: ignore[misc]
            start_color=rgb, end_color=rgb, fill_type="solid",
        )
        return True
    except AttributeError:
        return False


def mark_user_input_required(
    ws: Any, row: int, col: int, hint: str = "",
) -> bool:
    """23차 T192: 사용자 입력 필요 셀에 노란 배경 + placeholder 텍스트.

    Args:
        hint: 텍스트 뒤에 추가할 안내 (예: "Approver 이름").

    Returns:
        쓰기 + 색칠 모두 성공 시 True.
    """
    label = USER_INPUT_PLACEHOLDER + (f" — {hint}" if hint else "")
    wrote = safe_write(ws, row, col, label)
    filled = _apply_fill(ws, row, col, _USER_INPUT_FILL_RGB)
    return wrote and filled


def write_value_or_mark(
    ws: Any, row: int, col: int, value: Any, hint: str = "",
) -> bool:
    """23차 T192: value 있으면 그대로 쓰고, 빈 string/None이면 사용자 입력 표시.

    Returns:
        True if value written; False if marked as user-input-required.
    """
    if value:
        return safe_write(ws, row, col, value)
    mark_user_input_required(ws, row, col, hint=hint)
    return False


def mark_fail_cell(ws: Any, row: int, col: int) -> bool:
    """23차 T192: 2.Consistency FAIL row 등 강조용 빨간 배경."""
    return _apply_fill(ws, row, col, _FAIL_FILL_RGB)


def mark_asil_d_function(ws: Any, row: int, col: int) -> bool:
    """30차 W21: 3.Coverage 시트의 ASIL D 함수 row 강조용 빨간 배경.

    색상 RGB는 ``mark_fail_cell`` 과 동일하나 호출 의미를 분리.
    - ``mark_fail_cell``: TC 실행 결과 FAIL 표시
    - ``mark_asil_d_function``: audit 검토 우선순위 (MC/DC 커버리지 필수) 표시

    동일 셀에 두 의미가 겹치면 호출 순서 보장으로 마지막 호출이 우선.
    빌더는 ASIL 강조를 FAIL 강조보다 나중에 호출 권장.
    """
    return _apply_fill(ws, row, col, _ASIL_D_FILL_RGB)


def mark_asil_b_function(ws: Any, row: int, col: int) -> bool:
    """31차 W29: 3.Coverage 시트의 ASIL B 함수 row 강조 — 연한 파랑.

    audit 검토 우선순위: 분기 커버리지 필수. ASIL D (빨간)보다 낮은 시인성
    으로 단계 구분.
    """
    return _apply_fill(ws, row, col, _ASIL_B_FILL_RGB)


def mark_asil_c_function(ws: Any, row: int, col: int) -> bool:
    """31차 W29: 3.Coverage 시트의 ASIL C 함수 row 강조 — 연한 주황.

    audit 검토 우선순위: MC/DC 커버리지 권장. ASIL D (빨간)과 ASIL B (파랑)
    사이 단계 — 색상으로 시각적 등급 차이 명시.
    """
    return _apply_fill(ws, row, col, _ASIL_C_FILL_RGB)


def mark_asil_a_function(ws: Any, row: int, col: int) -> bool:
    """라운드 81 T1502: 3.Coverage / SUTR Test Log ASIL A 함수 row 강조 — 연한 녹색.

    audit 검토 우선순위: 구문 커버리지로 충분 (가장 약한 안전 등급).
    HDPDM01 NE_GN7 환경처럼 A/QM 함수가 압도적인 경우에도 audit reviewer가
    분포를 한눈에 인지 가능. ASIL B (파랑)보다 낮은 시인성으로 단계 구분.
    """
    return _apply_fill(ws, row, col, _ASIL_A_FILL_RGB)


def mark_asil_qm_function(ws: Any, row: int, col: int) -> bool:
    """라운드 81 T1502: 3.Coverage / SUTR Test Log QM 함수 row 강조 — 연한 회색.

    Quality Management — 비안전, 정보성. 함수가 ISO 26262 안전 요구사항 외부
    (애플리케이션 로직 등)에 있음을 audit reviewer에게 명시. ASIL A 이상
    (녹색/파랑/주황/빨강)과 색조 자체 분리 (회색) — 안전 vs 비안전 한눈 구분.
    """
    return _apply_fill(ws, row, col, _ASIL_QM_FILL_RGB)


def write_label_or_mark(
    ws: Any,
    label: str,
    value: Any,
    hint: str = "",
    optional_labels: set[str] | None = None,
    out_warnings: list[str] | None = None,
    max_row: int = 50,
) -> bool:
    """23차 T192/W12: 라벨 옆 셀에 value 쓰기 — value 빈 경우 노란 placeholder.

    Coverage / SUTR builder 양쪽에서 공유 (이전 ``_write_label_or_mark`` 중복 제거).

    동작:
      1. ``find_kv_row``로 라벨 위치 찾기
      2. 머지 영역 보정 후 target_col 결정
      3. value 있으면 ``safe_write``, 없으면 ``mark_user_input_required`` (노란 강조)

    Args:
        optional_labels: 라벨 미발견 시 warnings 누적 skip 대상 (예: {"Reviewer"}).
        out_warnings: 미발견 라벨 사유 누적용.

    Returns:
        value가 실제로 쓰였으면 True (mark는 False).
    """
    pos = find_kv_row(ws, label, max_row)
    if not pos:
        if (optional_labels is None or label not in optional_labels) and out_warnings is not None:
            out_warnings.append(f"라벨 '{label}' 미발견 — 셀 쓰기 skip")
        return False
    row, col = pos
    target_col = col + 1
    for mr in ws.merged_cells.ranges:
        if mr.min_row <= row <= mr.max_row and mr.min_col <= col <= mr.max_col:
            target_col = mr.max_col + 1
            break
    return write_value_or_mark(ws, row, target_col, value, hint=hint)


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
