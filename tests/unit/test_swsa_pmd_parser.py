"""SwSA PMD/CPD 중복코드 파서 단위테스트."""
from __future__ import annotations

import os

import pytest

from backend.services.swsa_pmd_parser import parse_pmd_cpd

_SYNTH = r"""Found a 176 line (562 tokens) duplication in the following files:
Starting at line 263 of C:\ws\PROJ\Sources\lin_cfg.c
Starting at line 481 of C:\ws\PROJ\Sources\lin_cfg.c
  ,0x00 /* dup body */
Found a 30 line (90 tokens) duplication in the following files:
Starting at line 10 of C:\ws\PROJ\a.c
Starting at line 99 of C:\ws\PROJ\b.c
Found a 5 line (12 tokens) duplication in the following files:
Starting at line 1 of C:\ws\PROJ/c.c
Starting at line 2 of C:\ws\PROJ/c.c
"""


class TestSynthetic:
    def setup_method(self):
        self.r = parse_pmd_cpd(_SYNTH)

    def test_block_count(self):
        assert self.r.total_blocks == 3
        assert self.r.parse_warnings == []

    def test_totals(self):
        assert self.r.total_duplicated_lines == 176 + 30 + 5
        assert self.r.max_lines == 176

    def test_band_distribution(self):
        # 176→High(>=50), 30→Moderate(10~49), 5→Low(0~9)
        assert self.r.band_counts == {"0 ~ 9": 1, "10 ~ 49": 1, ">= 50": 1}
        assert self.r.fail_count == 1
        assert self.r.conditional_count == 1
        assert self.r.result == "Fail"

    def test_basenames_and_files(self):
        top = self.r.blocks_sorted()[0]
        assert top.lines == 176
        assert top.basenames == ["lin_cfg.c", "lin_cfg.c"]
        assert top.start_lines == [263, 481]

    def test_mixed_path_separators(self):
        # 마지막 블록은 backslash + forward slash 혼합 경로
        last = self.r.blocks_sorted()[-1]
        assert last.basenames == ["c.c", "c.c"]


class TestEdge:
    def test_no_duplication(self):
        r = parse_pmd_cpd("No duplications found.\nDone.")
        assert r.total_blocks == 0
        assert r.result == "Pass"
        assert any("미발견" in w for w in r.parse_warnings)

    def test_all_low_band_pass(self):
        txt = "Found a 3 line (8 tokens) duplication in the following files:\nStarting at line 1 of a.c\n"
        r = parse_pmd_cpd(txt)
        assert r.result == "Pass"
        assert r.fail_count == 0


_REAL = os.path.join(
    os.path.dirname(__file__), "..", "..", ".codex_tmp", "swsa_samples",
    "LOG_NE1AW_PORTING_2631_PMD_Report_20260323.txt",
)


@pytest.mark.skipif(not os.path.exists(_REAL), reason="실 PMD 샘플 없음")
class TestRealPmd:
    def test_kjpds02_app_dups(self):
        r = parse_pmd_cpd(_REAL)
        assert r.total_blocks == 21
        assert r.total_duplicated_lines == 812
        assert r.max_lines == 176
        assert r.band_counts == {"0 ~ 9": 0, "10 ~ 49": 18, ">= 50": 3}
        assert r.result == "Fail"
