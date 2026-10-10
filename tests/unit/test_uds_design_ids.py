"""SwUDS 설계 ID 파서 — **틀린 ID 를 채우지 않는지**가 본체다.

생성기는 그동안 `SwUFn_{소스파싱순번:04d}` 를 SUDS 칸과 TC_ID 에 넣었다. 모양은
설계 ID 와 같지만 **다른 설계 요소를 가리킨다**(정본과 교집합 251개 중 178개).
그래서 이 파서의 계약은 "많이 채운다" 가 아니라 **"채운 것은 맞다"** 이다.

라이브 실측(KJPDS02 SwUDS v3.02 ↔ SwUTS 정본 v1.02, 2026-08-11):
  일치 992 (97.8%) · 빈칸 22 · **틀린 ID 0**
"""
from __future__ import annotations

from pathlib import Path

import pytest

from generators.uds_design_ids import load_uds_design_ids, resolve_design_id


def _make_uds(tmp_path: Path, lines: list[str], name: str = "uds.docx") -> str:
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    for line in lines:
        doc.add_paragraph(line)
    out = tmp_path / name
    doc.save(str(out))
    return str(out)


def test_reads_design_ids_from_paragraphs(tmp_path):
    """SwUDS 본문의 `SwUFn_0101: main` 문단이 근거다(실측 1,035개)."""
    p = _make_uds(tmp_path, [
        "SwUFn_0101: main",
        "본문 설명 줄 — 무시된다",
        "SwUFn_0122: s_sha256_transform",
        "SwUFn_0123: s_sha256_init",
    ])
    got = load_uds_design_ids(p)
    assert got["by_name"] == {
        "main": "SwUFn_0101",
        "s_sha256_transform": "SwUFn_0122",
        "s_sha256_init": "SwUFn_0123",
    }
    assert got["total"] == 3
    assert resolve_design_id(got, "s_sha256_init") == "SwUFn_0123"


def test_duplicate_names_are_dropped_not_guessed(tmp_path):
    """동명이인은 **빈칸**이다.

    실측 9건(`SCI0_Init` 이 SwUFn_2901 과 SwUFn_3515 양쪽). 임의로 하나를 고르면
    0.9% 를 채우는 대신 그 0.9% 가 조용히 틀린다.
    """
    p = _make_uds(tmp_path, [
        "SwUFn_2901: SCI0_Init",
        "SwUFn_3515: SCI0_Init",
        "SwUFn_0101: main",
    ])
    got = load_uds_design_ids(p)
    assert got["ambiguous"] == ["SCI0_Init"]
    assert "SCI0_Init" not in got["by_name"]
    assert resolve_design_id(got, "SCI0_Init") == ""      # 추측하지 않는다
    assert resolve_design_id(got, "main") == "SwUFn_0101"  # 유일한 것은 채운다


def test_same_id_repeated_is_not_ambiguous(tmp_path):
    """같은 ID 가 여러 번 나오는 것은 충돌이 아니다(문서가 함수를 두 번 언급)."""
    p = _make_uds(tmp_path, ["SwUFn_0101: main", "SwUFn_0101: main"])
    got = load_uds_design_ids(p)
    assert got["ambiguous"] == []
    assert resolve_design_id(got, "main") == "SwUFn_0101"


def test_unknown_name_returns_blank_never_a_sequence_number(tmp_path):
    """못 찾으면 빈 문자열 — **순번으로 대체하면 안 된다**(그게 원래 결함이다)."""
    p = _make_uds(tmp_path, ["SwUFn_0101: main"])
    got = load_uds_design_ids(p)
    assert resolve_design_id(got, "s_없는함수") == ""
    assert resolve_design_id(got, "") == ""
    assert resolve_design_id(None, "main") == ""
    assert resolve_design_id({}, "main") == ""


def test_missing_or_unreadable_doc_yields_empty_map(tmp_path):
    """파싱 실패는 빈 맵이다. 호출부는 그 경우 ID 칸을 비워야 한다."""
    assert load_uds_design_ids("")["by_name"] == {}
    assert load_uds_design_ids(str(tmp_path / "없는파일.docx"))["by_name"] == {}
    bad = tmp_path / "not_a_docx.docx"
    bad.write_bytes(b"not a zip")
    assert load_uds_design_ids(str(bad))["by_name"] == {}
    # .docx 가 아닌 확장자는 열지 않는다(잘못된 파서에 넘기면 예외만 시끄럽다).
    other = tmp_path / "uds.xlsm"
    other.write_bytes(b"x")
    assert load_uds_design_ids(str(other))["by_name"] == {}


def test_cache_is_invalidated_when_file_changes(tmp_path):
    """(mtime, size) 시그니처가 바뀌면 다시 읽는다 — stale 맵은 틀린 ID 를 만든다."""
    p = _make_uds(tmp_path, ["SwUFn_0101: main"])
    assert resolve_design_id(load_uds_design_ids(p), "main") == "SwUFn_0101"
    _make_uds(tmp_path, ["SwUFn_0999: main"], name="uds.docx")
    assert resolve_design_id(load_uds_design_ids(p), "main") == "SwUFn_0999"


def test_suts_tc_id_follows_design_id_when_available(tmp_path):
    """정본은 `TC_ID = "SwUTC_" + SUDS` 다(실측 1,013/1,014).

    설계 ID 를 못 찾은 단위는 TC_ID 를 비울 수 없으므로(시트의 키다) 내부 fid 로
    만들되, **SUDS 칸은 비운다**.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from generators.suts import _COL_TC_ID, _DATA_START_ROW, _RELATED_COL, generate_suts_xlsm

    units = [
        {"fid": "SwUFn_0007", "name": "s_known", "component": "SwCom_01",
         "input_vars": ["a"], "output_vars": [], "asil": "A", "suds_id": "SwUFn_0122"},
        {"fid": "SwUFn_0008", "name": "s_unknown", "component": "SwCom_01",
         "input_vars": ["b"], "output_vars": [], "asil": "A"},
    ]
    seqs = {u["fid"]: [{"seq_num": 1, "strategy": "BV_MID",
                        "inputs": {}, "expected": {}}] for u in units}
    out = tmp_path / "suts.xlsx"
    generate_suts_xlsm(None, units, seqs, str(out), {"project_id": "T"})

    ws = openpyxl.load_workbook(str(out), read_only=True, data_only=True)["2.SW Unit Test Spec"]
    r1, r2 = _DATA_START_ROW, _DATA_START_ROW + 2   # TC 행 + 시퀀스 1행씩
    assert ws.cell(row=r1, column=_COL_TC_ID).value == "SwUTC_SwUFn_0122"
    assert ws.cell(row=r1, column=_RELATED_COL).value == "SwUFn_0122"
    # 설계 ID 없음 → TC_ID 는 내부 fid, SUDS 칸은 빈칸
    assert ws.cell(row=r2, column=_COL_TC_ID).value == "SwUTC_SwUFn_0008"
    assert ws.cell(row=r2, column=_RELATED_COL).value is None
