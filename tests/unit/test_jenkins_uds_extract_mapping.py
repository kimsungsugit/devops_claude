"""Regression: /api/jenkins/uds/extract-mapping 의 Related ID 설계-ID 추출.

UDS Function Information 표의 "Related ID" 행에서 설계 요구 ID(SwFn/SwSTR/SwST/SwTK)를
뽑아 mapping_pairs 로 낸다. 과거 정규식 `Sw[A-Z]{2,}_\\d+`(대문자 전용)은 소문자 섞인
SwFn 을 통째로 놓쳤고, 전체 셀 스캔이라 "Called Function" 행의 SwUFn 함수 ID까지
요구참조로 오수집했다. 이를 [A-Za-z] + "Related ID" 행 한정으로 고친 것의 회귀 가드.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pytest

from backend.routers import jenkins
from backend.routers.jenkins import jenkins_uds_extract_mapping


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch):
    """resolver를 local로 고정 + UDS 매핑 캐시 클리어(테스트 간 격리)."""
    from backend.services import file_resolver as fr
    monkeypatch.setattr(fr, "_resolver", fr.LocalFileResolver())
    jenkins._UDS_MAPPING_CACHE.clear()
    yield
    jenkins._UDS_MAPPING_CACHE.clear()


def _make_uds_docx(tmp_path: Path, tables: List[List[Tuple[str, str]]]) -> str:
    """Function Information 표들을 담은 합성 docx. 각 표 = [(label, value), ...].

    파서 규약: 첫 행 first cell 에 "Function Information", label=cells[0]/value=cells[2],
    표당 ≥4행. 3열 표로 만들어 value 를 cells[2]에 둔다(병합셀 grid 확장과 동일).
    """
    docx = pytest.importorskip("docx")
    d = docx.Document()
    for rows in tables:
        tb = d.add_table(rows=len(rows), cols=3)
        for i, (label, value) in enumerate(rows):
            tb.rows[i].cells[0].text = label
            tb.rows[i].cells[2].text = value
    fp = tmp_path / "uds.docx"
    d.save(str(fp))
    return str(fp)


def _fi(related: str, name: str = "foo_func", fid: str = "SwUFn_0101",
        extra: List[Tuple[str, str]] | None = None) -> List[Tuple[str, str]]:
    rows = [
        ("[ Function Information ]", ""),
        ("ID", fid),
        ("Name", name),
        ("Related ID", related),
    ]
    if extra:
        rows.extend(extra)
    return rows


def _req_ids(res: dict) -> set:
    return {p["requirement_id"] for p in res.get("mapping_pairs", [])}


def test_swfn_captured_from_related_id(tmp_path: Path) -> None:
    """SwFn(소문자 n 섞인 CamelCase)이 Related ID에서 포착된다.

    mutation: 정규식을 [A-Z]{2,}로 되돌리면 SwFn 미포착 → 이 테스트 실패.
    """
    path = _make_uds_docx(tmp_path, [_fi("SwFn_05")])
    res = jenkins_uds_extract_mapping({"uds_path": path})
    assert res["ok"] is True
    ids = _req_ids(res)
    assert "SwFn_05" in ids
    # source_ids 에 함수명이 실려야
    pair = next(p for p in res["mapping_pairs"] if p["requirement_id"] == "SwFn_05")
    assert "foo_func" in pair["source_ids"]


def test_swufn_from_called_function_not_harvested(tmp_path: Path) -> None:
    """"Called Function" 행의 다른 함수 SwUFn ID는 요구참조로 수집되지 않는다.

    mutation: 전체 셀 스캔으로 되돌리면 SwUFn_0999 누출 → 이 테스트 실패.
    """
    path = _make_uds_docx(tmp_path, [
        _fi("SwSTR_02", extra=[("Called Function", "SwUFn_0999")]),
    ])
    res = jenkins_uds_extract_mapping({"uds_path": path})
    ids = _req_ids(res)
    assert "SwSTR_02" in ids            # Related ID 행은 읽힘
    assert "SwUFn_0999" not in ids      # Called Function 행은 스캔 밖


def test_uppercase_design_ids_still_captured(tmp_path: Path) -> None:
    """구 [A-Z]가 잡던 SwSTR/SwST/SwTK도 [A-Za-z]에서 회귀 없이 포착(경계 확인)."""
    path = _make_uds_docx(tmp_path, [_fi("SwSTR_02, SwST_03, SwTK_04")])
    res = jenkins_uds_extract_mapping({"uds_path": path})
    ids = _req_ids(res)
    assert {"SwSTR_02", "SwST_03", "SwTK_04"} <= ids


def test_echo_table_junk_not_harvested(tmp_path: Path) -> None:
    """값 셀이 라벨을 echo하는 junk 표에서 'ID'/'Name'이 harvest되지 않는다 (deep-review C1).

    HDPDM01의 165개 표가 cells=['Name','Name',…] 형태라 func_name='Name'/func_id='ID'가
    설계-ID bridge로 요구 추적성에 유입됐다. echo 가드가 이를 차단하는지 고정.
    """
    tables = [
        _fi("SwFn_05", name="real_func", fid="SwUFn_0101"),          # 정상 표
        [("[ Function Information ]", ""), ("ID", "ID"),             # junk: 값=라벨 echo
         ("Name", "Name"), ("Related ID", "SwFn_09")],
    ]
    res = jenkins_uds_extract_mapping({"uds_path": _make_uds_docx(tmp_path, tables)})
    afi = res["all_function_ids"]
    assert "ID" not in afi and "Name" not in afi        # junk 미유입
    assert "real_func" in afi                            # 정상 표는 정상 harvest
    src = {s for m in res["mapping_pairs"] for s in m["source_ids"]}
    assert "ID" not in src and "Name" not in src
    assert "real_func" in src                            # 정상 함수는 유지


def test_related_id_label_variant_captured(tmp_path: Path) -> None:
    """라벨 변형 'Related ID(s)'도 스캔한다 (W2 강건화)."""
    tables = [[("[ Function Information ]", ""), ("ID", "SwUFn_0101"),
               ("Name", "foo_func"), ("Related ID(s)", "SwFn_05")]]
    res = jenkins_uds_extract_mapping({"uds_path": _make_uds_docx(tmp_path, tables)})
    assert "SwFn_05" in _req_ids(res)


def test_own_swufn_id_not_self_referenced(tmp_path: Path) -> None:
    """함수 자기 SwUFn ID(cells 'ID' 행)는 Related ID에 안 나오면 요구참조가 아니다."""
    path = _make_uds_docx(tmp_path, [_fi("SwFn_05", fid="SwUFn_0101")])
    ids = _req_ids(res := jenkins_uds_extract_mapping({"uds_path": path}))
    assert "SwUFn_0101" not in ids
    # 인벤토리(all_function_ids)에는 이름·자기ID가 남는다
    assert "SwUFn_0101" in res["all_function_ids"]
    assert "foo_func" in res["all_function_ids"]
