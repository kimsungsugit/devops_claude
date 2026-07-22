# tests/unit/test_qac_jenkins_impact.py
"""QAC jenkins-impact 게이트가 데이터 부재를 '영향 없음'으로 위장하지 않는지 (A B4).

STS/SUTS QAC 캐시 excel 이 하나도 없을 때(cache_root 오설정·미생성) 예전엔 match_count=0
→ has_any_impact:false 로 흘러, 안전관련 변경이 재검증을 조용히 우회했다. 이제 데이터
부재는 has_any_impact:None + status:insufficient_data 로 표면화한다.
"""
from __future__ import annotations

import openpyxl

from backend.helpers.jenkins import _jenkins_sts_dir, _jenkins_suts_dir
from backend.routers.qac import qac_jenkins_impact


def _write_excel(dir_path, name, cell_text):
    dir_path.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TC"
    ws.cell(1, 1).value = cell_text
    wb.save(dir_path / name)


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


def test_both_caches_present_no_match_is_concrete_false(tmp_path):
    """대조: 두 소스 캐시가 다 있고 매치 0 이면 has_any_impact=False (확정 무영향, None 아님)."""
    _write_excel(_jenkins_sts_dir(str(tmp_path)), "sts_b1.xlsx", "unrelated content")
    _write_excel(_jenkins_suts_dir(str(tmp_path)), "suts_b1.xlsx", "unrelated content")
    payload = qac_jenkins_impact(
        job_url="http://j/x", cache_root=str(tmp_path),
        build_selector="lastSuccessfulBuild", function_name="EEPROM_Write",
    )
    s = payload["summary"]
    assert s["data_available"] is True
    assert s["has_any_impact"] is False           # 두 소스 다 스캔·매치0 → 확정 무영향
    assert s["missing_sources"] == []
    assert "status" not in s                        # 부분/부재 아님
    assert s["sts_files_scanned"] >= 1 and s["suts_files_scanned"] >= 1


def test_partial_cache_one_source_missing_is_none_not_false(tmp_path):
    """W4 — STS만 있고(매치0) SUTS 캐시 부재면 has_any_impact=None + partial_data.

    예전 OR 로직은 STS만 있어도 data_available=True 라 SUTS 캐시 누락이 has_any=False 로
    묻혔다(안전변경이 SUTS 재검증 우회). 뮤테이션: OR/무조건 bool 로 되돌리면 None 이
    False 가 돼 실패.
    """
    _write_excel(_jenkins_sts_dir(str(tmp_path)), "sts_b1.xlsx", "unrelated content")  # STS만
    payload = qac_jenkins_impact(
        job_url="http://j/x", cache_root=str(tmp_path),
        build_selector="lastSuccessfulBuild", function_name="EEPROM_Write",
    )
    s = payload["summary"]
    assert s["has_any_impact"] is None, "SUTS 캐시 누락인데 STS만으로 무영향 단정됐다"
    assert s["missing_sources"] == ["SUTS"]
    assert s["status"] == "partial_data"
    assert s["sts_files_scanned"] >= 1 and s["suts_files_scanned"] == 0


def test_impacted_source_gives_true_even_if_other_missing(tmp_path):
    """어느 한 소스라도 영향 확인되면 나머지 캐시 부재여도 has_any_impact=True (확정 영향)."""
    _write_excel(_jenkins_sts_dir(str(tmp_path)), "sts_b1.xlsx", "EEPROM_Write")  # STS 매치
    payload = qac_jenkins_impact(
        job_url="http://j/x", cache_root=str(tmp_path),
        build_selector="lastSuccessfulBuild", function_name="EEPROM_Write",
    )
    s = payload["summary"]
    assert s["has_any_impact"] is True   # STS 영향 확인 → SUTS 미판정과 무관하게 True
