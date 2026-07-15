"""Phase 3 — v3.02 SwUDS 세로 key-value 표 ASIL 추출기 검증.

실 KJPDS02 SwUDS v3.02는 함수마다 '[ Function Information ]' 세로 표를 두고 행 라벨(col0)
'Name'/'ASIL'에 C 함수명·등급을 담는다(ASIL이 컬럼 헤더가 아니라 행 라벨 → 기존 파서 0건).
extract_function_asil_from_kv_tables는 lxml로 이를 추출한다. fail-closed(둘 다 있고 C 식별자·
유효등급일 때만)·max-merge(안전측)·python-docx 미사용을 검증한다.
"""
from __future__ import annotations

import io

from backend.services.iso26262_doc_asil_extractor import extract_function_asil_from_kv_tables


def _make_uds_docx(func_tables: list[dict[str, str]]) -> bytes:
    """func_tables: 함수별 {행라벨: 값} — 각각 세로 2열 표 하나로 stamp(실 v3.02 레이아웃 모사)."""
    from docx import Document  # backend/.venv에 존재(extractor도 사용)

    doc = Document()
    for ft in func_tables:
        t = doc.add_table(rows=0, cols=2)
        for label, value in ft.items():
            cells = t.add_row().cells
            cells[0].text = label
            cells[1].text = value
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_kv_extract_basic():
    """Name/ASIL 행 라벨 세로 표 → {함수명(소문자): 등급}. 사용자 예시 g_drvin_drv8706sq_init 포함."""
    data = _make_uds_docx([
        {"ID": "SwUFn_0101", "Name": "g_drvin_drv8706sq_init", "Prototype": "void x(void)", "ASIL": "A"},
        {"ID": "SwUFn_0102", "Name": "main", "ASIL": "QM"},
    ])
    m = extract_function_asil_from_kv_tables(data)
    assert m == {"g_drvin_drv8706sq_init": "A", "main": "QM"}


def test_kv_extract_normalizes_asil_prefix():
    """값 셀이 'ASIL C'처럼 접두사 포함이어도 정규 등급 'C'로 정규화."""
    data = _make_uds_docx([{"Name": "s_foo", "ASIL": "ASIL C"}])
    assert extract_function_asil_from_kv_tables(data) == {"s_foo": "C"}


def test_kv_extract_requires_both_name_and_asil():
    """ASIL 행 없는 표 → 미추출(fail-closed — 프로즈 표/입력파라미터 표 오귀속 방지)."""
    data = _make_uds_docx([{"ID": "SwUFn_1", "Name": "s_foo", "Prototype": "void s_foo(void)"}])
    assert extract_function_asil_from_kv_tables(data) == {}


def test_kv_extract_rejects_prose_name():
    """Name이 다단어 프로즈면 C 식별자 아님 → 거부(오귀속·오등급 차단)."""
    data = _make_uds_docx([{"Name": "power operation disable", "ASIL": "B"}])
    assert extract_function_asil_from_kv_tables(data) == {}


def test_kv_extract_rejects_invalid_grade():
    """오타/범위밖 등급('B(잠정)')은 무효 → 거부(under-report 위험 차단, _norm_asil_grade)."""
    data = _make_uds_docx([{"Name": "s_foo", "ASIL": "B(잠정)"}])
    assert extract_function_asil_from_kv_tables(data) == {}


def test_kv_extract_max_merge_on_duplicate():
    """같은 함수명이 여러 표에 나오면 max 등급(안전측 — 낮은 등급 채택은 under-report)."""
    data = _make_uds_docx([
        {"Name": "s_dup", "ASIL": "A"},
        {"Name": "s_dup", "ASIL": "C"},
    ])
    assert extract_function_asil_from_kv_tables(data) == {"s_dup": "C"}


def test_kv_extract_fail_safe_on_bad_bytes():
    """빈/비-zip 바이트는 예외 없이 빈 맵(impact 본류 비차단)."""
    assert extract_function_asil_from_kv_tables(b"") == {}
    assert extract_function_asil_from_kv_tables(b"not a zip at all") == {}


def test_kv_extract_rejects_oversize_input():
    """96MB(DOCX_MAX_BYTES) 초과 입력은 파싱 없이 빈 맵 — OOM/과대작업 가드(reviewer W1)."""
    from backend.services.iso26262_doc_asil_extractor import DOCX_MAX_BYTES

    assert extract_function_asil_from_kv_tables(b"x" * (DOCX_MAX_BYTES + 1)) == {}


def test_kv_extract_rejects_non_ascii_name():
    """비-ASCII 이름(g_foo한)은 순수 C 식별자 아님 → 거부(reviewer I2, _C_IDENT_FULL_RE re.ASCII)."""
    data = _make_uds_docx([{"Name": "g_foo한", "ASIL": "B"}])
    assert extract_function_asil_from_kv_tables(data) == {}
