# tests/unit/test_qac_jenkins_impact.py
"""QAC jenkins-impact 게이트가 데이터 부재를 '영향 없음'으로 위장하지 않는지 (A B4).

STS/SUTS QAC 캐시 excel 이 하나도 없을 때(cache_root 오설정·미생성) 예전엔 match_count=0
→ has_any_impact:false 로 흘러, 안전관련 변경이 재검증을 조용히 우회했다. 이제 데이터
부재는 has_any_impact:None + status:insufficient_data 로 표면화한다.
"""
from __future__ import annotations

import openpyxl

from backend.helpers.jenkins import _jenkins_sts_dir
from backend.routers.qac import qac_jenkins_impact


def test_no_cache_is_insufficient_data_not_no_impact(tmp_path):
    """캐시 디렉토리가 비면 has_any_impact=None + insufficient_data (false 아님).

    뮤테이션: has_any_impact 를 `bool(...)`(무조건 계산)로 되돌리면 None 이 False 가 돼 실패.
    """
    payload = qac_jenkins_impact(
        job_url="http://j/x", cache_root=str(tmp_path),
        build_selector="lastSuccessfulBuild", function_name="EEPROM_Write",
    )
    s = payload["summary"]
    assert s["has_any_impact"] is None, "데이터 부재인데 영향 없음(false/true)로 확정됐다"
    assert s["data_available"] is False
    assert s["status"] == "insufficient_data"
    assert s["sts_files_scanned"] == 0 and s["suts_files_scanned"] == 0


def test_cache_present_gives_concrete_verdict(tmp_path):
    """대조: STS 캐시가 있으면 has_any_impact 가 bool 로 확정된다(데이터 있음)."""
    sts_dir = _jenkins_sts_dir(str(tmp_path))
    sts_dir.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TC"
    ws.cell(1, 1).value = "EEPROM_Write called here"   # 함수명 매칭
    wb.save(sts_dir / "sts_build1.xlsx")

    payload = qac_jenkins_impact(
        job_url="http://j/x", cache_root=str(tmp_path),
        build_selector="lastSuccessfulBuild", function_name="EEPROM_Write",
    )
    s = payload["summary"]
    assert s["data_available"] is True
    assert s["status"] != "insufficient_data" if "status" in s else True
    assert isinstance(s["has_any_impact"], bool)   # None 아님 — 확정 판정
    assert s["sts_files_scanned"] >= 1
