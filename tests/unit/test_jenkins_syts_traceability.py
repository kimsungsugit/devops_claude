"""Regression: /api/jenkins/syts/extract-traceability 전용 파서.

SyTS 레이아웃은 SITS와 달라(TC ID=col B 'Test Case ID', Related ID=상단 병합 그룹헤더
아래 열) 과거 SITS 파서 위임이 Title(col C)을 testcase로, Test Environment(SyTE)를
requirement로 오독해 밴드의 92.9%가 허위 추적이었다. 전용 파서로 교체한 것의 회귀 가드.
TC ID는 SyTC_ 형태, 요구 ID는 col의 Related ID(SyEIF→SwEI 평탄화).
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from backend.routers.jenkins import jenkins_syts_extract_traceability


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch):
    """resolver를 local로 고정 — tmp 파일 직접 read(cloudium IPC 회피)."""
    from backend.services import file_resolver as fr
    monkeypatch.setattr(fr, "_resolver", fr.LocalFileResolver())


def _save(wb: openpyxl.Workbook, tmp_path: Path, name: str) -> str:
    fp = tmp_path / name
    wb.save(str(fp))
    return str(fp)


def test_syts_tc_id_and_related_id_columns(tmp_path: Path) -> None:
    """TC ID(col B) + Related ID(row3 병합헤더, col T) 정확 추출, Title은 미유입.

    mutation: TC 열을 col C(Title)로 읽으면 testcase='SBCM LIN Signal' → TC 형태 아님 → 스킵.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "2.System Test Spec"
    ws.cell(3, 20, "Related ID")          # 병합 그룹헤더 — TC 헤더(row4)보다 위
    ws.cell(4, 2, "Test Case ID")
    ws.cell(4, 3, "Title")
    ws.cell(5, 2, "SyTC_SyEIF_01_01")
    ws.cell(5, 3, "SBCM LIN Signal")      # Title — testcase/requirement로 유입되면 안 됨
    ws.cell(5, 20, "SyEIF_01")
    res = jenkins_syts_extract_traceability({"path": _save(wb, tmp_path, "syts.xlsx")})
    assert res["ok"] is True
    pairs = {(r["requirement_id"], r["testcase"]) for r in res["vcast_rows"]}
    assert ("SWEI_01", "SyTC_SyEIF_01_01") in pairs     # SyEIF→SwEI 평탄화
    # Title 문자열은 어느 필드에도 유입되지 않는다
    assert all("SBCM" not in str(v) for r in res["vcast_rows"] for v in r.values())
    assert {r["source"] for r in res["vcast_rows"]} == {"SyTS"}


def test_syts_related_id_same_row_as_tc_header(tmp_path: Path) -> None:
    """Related ID가 TC 헤더와 같은 행에 있어도 추출(레이아웃 변형)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "System Test Specification"
    ws.cell(4, 2, "Test Case ID")
    ws.cell(4, 20, "Related ID")
    ws.cell(5, 2, "SyTC_SyTR_0101_01")
    ws.cell(5, 20, "SyTR_0101")
    res = jenkins_syts_extract_traceability({"path": _save(wb, tmp_path, "s.xlsx")})
    pairs = {(r["requirement_id"], r["testcase"]) for r in res["vcast_rows"]}
    assert ("SWTR_0101", "SyTC_SyTR_0101_01") in pairs


def test_syts_multi_value_related_id(tmp_path: Path) -> None:
    """한 Related ID 셀의 콤마구분 다중 요구를 모두 추출."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2.System Test Spec"
    ws.cell(4, 2, "Test Case ID")
    ws.cell(4, 20, "Related ID")
    ws.cell(5, 2, "SyTC_SyEIF_01_01")
    ws.cell(5, 20, "SyEIF_01, SyTR_0102")
    res = jenkins_syts_extract_traceability({"path": _save(wb, tmp_path, "s.xlsx")})
    reqs = {r["requirement_id"] for r in res["vcast_rows"]}
    assert {"SWEI_01", "SWTR_0102"} <= reqs


def test_syts_no_related_col_warns(tmp_path: Path) -> None:
    """Related ID 열 미탐지 시 warning + 빈 결과(침묵 오파싱 방지)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "System Test Spec"
    ws.cell(4, 2, "Test Case ID")
    ws.cell(4, 3, "Title")               # Related ID 열 없음
    ws.cell(5, 2, "SyTC_SyEIF_01_01")
    ws.cell(5, 3, "SBCM LIN Signal")
    res = jenkins_syts_extract_traceability({"path": _save(wb, tmp_path, "s.xlsx")})
    assert res["vcast_rows"] == []
    assert res.get("warning") and "Related ID" in res["warning"]


def test_syts_non_tc_id_row_skipped(tmp_path: Path) -> None:
    """TC 열 값이 TC ID 형태(SyTC_)가 아니면 스킵 — Title/설명 유입 2차 방어."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2.System Test Spec"
    ws.cell(4, 2, "Test Case ID")
    ws.cell(4, 20, "Related ID")
    ws.cell(5, 2, "Not A Test Case")     # TC ID 형태 아님
    ws.cell(5, 20, "SyEIF_01")
    res = jenkins_syts_extract_traceability({"path": _save(wb, tmp_path, "s.xlsx")})
    assert res["vcast_rows"] == []
