"""추적성 enrich의 SwUDS 문서 직독 ASIL 상향 검증(under-report 해소).

enrich_function_details_with_docs에 uds_doc_paths를 주면 함수 ASIL을 SwUDS v3.02 세로
key-value 표(Name/ASIL 행 라벨)에서 직독해 반영한다(SDS 이름 휴리스틱 매칭보다 정확).
안전 불변(등급 낮추기 절대 없음, 상향만):
  · 문서 유래(asil_source=sds/srs/inference/blank)가 UDS보다 낮으면 → UDS로 상향(SDS 오매칭·
    SRS 미스보다 UDS 문서 직독이 권위). blank·TBD·N/A도 채움.
  · 소스 코드 @asil(asil_source="comment", c_source 권위)이 UDS보다 낮으면 → 등급 유지 +
    asil_doc_conflict 표면화(자동 상향 안 함 — impact _enrich_asil_from_uds와 lockstep,
    backend/services/CLAUDE.md "c_source > swuds"). 문서>코드 불일치는 수동 검토 신호.
  · 현재값이 UDS보다 높거나 같으면 → 유지(max, 하향 없음).
"""
from __future__ import annotations

import io
import os
import tempfile

from report_gen.requirements import enrich_function_details_with_docs


def _uds_docx(rows: list[dict[str, str]]) -> str:
    """rows: 함수별 {행라벨: 값} — 각각 세로 2열 표(실 v3.02 레이아웃 모사) → tmp docx 경로."""
    from docx import Document  # backend/.venv에 존재

    doc = Document()
    for ft in rows:
        t = doc.add_table(rows=0, cols=2)
        for label, value in ft.items():
            c = t.add_row().cells
            c[0].text, c[1].text = label, value
    buf = io.BytesIO()
    doc.save(buf)
    f = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    f.write(buf.getvalue())
    f.close()
    return f.name


def _enrich(details: dict, uds_rows: list[dict[str, str]]) -> dict:
    p = _uds_docx(uds_rows)
    try:
        enrich_function_details_with_docs(details, [], uds_doc_paths=[p])
    finally:
        os.unlink(p)
    return details


def test_uds_fills_blank_asil():
    """소스 blank + UDS 문서=A → A 채움, asil_source=uds([A] 38건 under-report 해소 경로)."""
    d = {"f1": {"name": "s_foo", "asil": ""}}
    _enrich(d, [{"Name": "s_foo", "ASIL": "A"}])
    assert d["f1"]["asil"] == "A"
    assert d["f1"]["asil_source"] == "uds"


def test_uds_fills_tbd_asil():
    """소스 TBD + UDS=C → C 채움(TBD/N/A/-도 blank로 취급)."""
    d = {"f1": {"name": "s_bar", "asil": "TBD"}}
    _enrich(d, [{"Name": "s_bar", "ASIL": "C"}])
    assert d["f1"]["asil"] == "C"
    assert d["f1"]["asil_source"] == "uds"


def test_uds_does_not_lower_higher_source_grade():
    """소스 C > UDS A → C 유지(등급 낮추기 절대 없음), 불일치 플래그도 없음(C>A는 정상)."""
    d = {"f1": {"name": "s_hi", "asil": "C"}}
    _enrich(d, [{"Name": "s_hi", "ASIL": "A"}])
    assert d["f1"]["asil"] == "C"
    assert d["f1"].get("asil_source") != "uds"
    assert "asil_doc_conflict" not in d["f1"]


def test_uds_raises_doc_derived_grade_when_lower():
    """문서 유래 등급(비-comment, 예 SDS/SRS/inference)이 UDS보다 낮으면 → UDS로 상향(under-report 해소).

    asil_source가 comment(소스 코드 @asil)가 아니면 UDS 문서 직독이 권위 — SDS 이름 휴리스틱
    오매칭/SRS 미스가 남긴 낮은 등급을 UDS가 이긴다([A] 38건 회복 경로).
    """
    d = {"f1": {"name": "s_lo", "asil": "QM", "asil_source": "srs"}}
    _enrich(d, [{"Name": "s_lo", "ASIL": "A"}])
    assert d["f1"]["asil"] == "A"
    assert d["f1"]["asil_source"] == "uds"


def test_uds_preserves_source_comment_asil_and_flags_conflict():
    """소스 코드 @asil(asil_source="comment")=QM < UDS A → QM 유지 + asil_doc_conflict(deep-review W1 회귀).

    c_source > swuds 정책(backend/services/CLAUDE.md): 소스 코드 @asil이 실 구현 권위. UDS 문서가
    더 높아도 자동 상향하지 않고 불일치만 표면화(수동 검토 신호) — impact _enrich_asil_from_uds와
    lockstep. 같은 함수가 impact 탭=QM / 추적성 탭=A로 모순 표시되던 것 폐색.
    """
    d = {"f1": {"name": "s_sa", "asil": "QM", "asil_source": "comment"}}
    _enrich(d, [{"Name": "s_sa", "ASIL": "A"}])
    assert d["f1"]["asil"] == "QM"                          # 소스 등급 유지(상향 안 함)
    assert d["f1"]["asil_source"] == "comment"              # 소스 권위 보존
    assert d["f1"].get("asil_doc_conflict") == "source=QM<uds=A"  # 불일치 표면화


def test_uds_lower_grade_does_not_override_existing_higher():
    """현재값 A(SDS direct/exact 이름매칭 등) > UDS QM → A 유지(하향 방지 — 라이브 101건 회귀 고정).

    first-wins(UDS 우선 blank-fill)면 UDS QM이 정당한 SDS A(sf_* secure flash 등)를 덮어
    under-report를 유발했다. max-merge(상향 전용)로 폐색: UDS는 현재값보다 높을 때만 이긴다.
    """
    d = {"f1": {"name": "s_hi", "asil": "A"}}
    _enrich(d, [{"Name": "s_hi", "ASIL": "QM"}])
    assert d["f1"]["asil"] == "A"
    assert d["f1"].get("asil_source") != "uds"


def test_uds_unknown_function_untouched():
    """UDS에 없는 함수는 UDS가 안 건드림(blank 유지 — SDS/SRS 폴백 몫)."""
    d = {"f1": {"name": "s_notinuds", "asil": ""}}
    _enrich(d, [{"Name": "s_other", "ASIL": "A"}])
    assert d["f1"]["asil"] == ""
    assert d["f1"].get("asil_source") != "uds"


def test_no_uds_paths_is_backward_compatible():
    """uds_doc_paths 미제공 → UDS 개입 없음(기존 호출부 동작 불변, 하위호환)."""
    d = {"f1": {"name": "s_foo", "asil": ""}}
    enrich_function_details_with_docs(d, [])
    assert d["f1"]["asil"] == ""
    assert d["f1"].get("asil_source") != "uds"
