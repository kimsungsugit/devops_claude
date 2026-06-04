"""SwSA QAC results_data.xml 파서 단위테스트.

합성 fixture로 핵심 불변식 검증 (CI 결정성):
  - dataroot[type='per-file'] 중복이 2× 집계로 새지 않음
  - 카테고리(Mandatory/Required) active/total 분리
  - leaf 룰(Message 보유) distinct 개수 / by_prefix
실데이터(.codex_tmp/swsa_samples/XML_*.xml)가 있으면 추가 검증 (없으면 skip).
"""
from __future__ import annotations

import os

import pytest

from backend.services.swsa_qac_xml_parser import (
    MISRA_MANDATORY,
    MISRA_REQUIRED,
    parse_qac_results_xml,
)

# 합성 fixture: project rollup + per-file 중복(동일 데이터) 포함.
# M3CM: Mandatory(Rule-8.6 active=10/total=20, Rule-2.2 active=5/total=5),
#       Required(Rule-21.1 active=3/total=3), Common(active=1).
# HKCCM: High(C-INT-001 active=8), Low(C-DCI-003 active=0/total=40).
_SYNTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<AnalysisData helix_qac_version="Helix QAC 2025.1" projectpath="C:/ws/PROJ"
              projectconfig="Initial" timestamp="20260527T182049">
  <dataroot type="project">
    <tree type="files">
      <Folder basename="Source Files" total="100" active="40"/>
      <RuleGroup name="M3CM" total="28" active="19">
        <Rule id="CMN-0" text="Common" total="1" active="1"/>
        <Rule id="M3CM-1" text="MISRA Mandatory" total="25" active="15"/>
        <Rule id="M3CM-2" text="MISRA Required" total="3" active="3"/>
      </RuleGroup>
    </tree>
    <tree type="rules">
      <RuleGroup name="M3CM" total="28" active="19">
        <Rule id="CMN-0" text="Common" total="1" active="1">
          <Rule id="CMN-0.4" text="Dataflow" total="1" active="1">
            <Message guid="x-1" total="1" active="1" severity="7" text="msg"/>
          </Rule>
        </Rule>
        <Rule id="M3CM-1" text="MISRA Mandatory" total="25" active="15">
          <Rule id="Rule-8.6" text="external linkage" total="20" active="10">
            <Message guid="q-8200" total="20" active="10" severity="1" text="8.6"/>
          </Rule>
          <Rule id="Rule-2.2" text="dead code" total="5" active="5">
            <Message guid="q-3000" total="5" active="5" severity="2" text="2.2"/>
          </Rule>
        </Rule>
        <Rule id="M3CM-2" text="MISRA Required" total="3" active="3">
          <Rule id="Rule-21.1" text="reserved" total="3" active="3">
            <Message guid="q-9000" total="3" active="3" severity="1" text="21.1"/>
          </Rule>
        </Rule>
      </RuleGroup>
      <RuleGroup name="HKCCM" total="50" active="8">
        <Rule id="HKC-1" text="High" total="10" active="8">
          <Rule id="HKC-1_1" text="Code Error" total="10" active="8">
            <Rule id="C-INT-001" text="integer conv" total="10" active="8">
              <Message guid="q-1861" total="10" active="8" severity="4" text="1861"/>
            </Rule>
          </Rule>
        </Rule>
        <Rule id="HKC-3" text="Low" total="40" active="0">
          <Rule id="C-DCI-003" text="reserved identifier" total="40" active="0">
            <Message guid="q-0602" total="40" active="0" severity="7" text="0602"/>
          </Rule>
        </Rule>
      </RuleGroup>
    </tree>
  </dataroot>
  <dataroot type="per-file">
    <File path="a.c"><RuleGroup name="M3CM" total="28" active="19">
      <Rule id="M3CM-1" text="MISRA Mandatory" total="25" active="15"/>
    </RuleGroup></File>
  </dataroot>
</AnalysisData>
"""


class TestSynthetic:
    def setup_method(self):
        self.r = parse_qac_results_xml(_SYNTH_XML)

    def test_meta_and_files(self):
        assert self.r.helix_qac_version == "Helix QAC 2025.1"
        assert self.r.project_config == "Initial"
        assert self.r.source_files_total == 100
        assert self.r.source_files_active == 40

    def test_no_perfile_double_count(self):
        # per-file dataroot 의 동일 데이터가 합산되면 active 가 2× 가 됨
        m = self.r.misra
        assert m is not None
        assert m.active == 19
        assert m.total == 28
        assert self.r.parse_warnings == []

    def test_misra_categories(self):
        m = self.r.misra
        man, req = m.category(MISRA_MANDATORY), m.category(MISRA_REQUIRED)
        assert (man.active, man.total) == (15, 25)
        assert (req.active, req.total) == (3, 3)
        # Mandatory + Required + Common(1) == group active
        assert man.active + req.active + m.category("Common").active == m.active

    def test_misra_leaf_rules(self):
        m = self.r.misra
        # active>0 leaf: Rule-8.6, Rule-2.2, Rule-21.1, CMN-0.4 → 4
        assert m.distinct_rules(use_active=True) == 4
        ids = {r.rule_id for r in m.leaf_rules}
        assert "Rule-8.6" in ids and "Rule-21.1" in ids
        top = m.rules_sorted()[0]
        assert top.rule_id == "Rule-8.6" and top.active == 10

    def test_secure_group(self):
        s = self.r.secure
        assert s is not None
        assert (s.active, s.total) == (8, 50)
        assert s.category("High").active == 8
        assert s.category("Low").total == 40
        # by_prefix: C-INT-001 active=8 → INT; C-DCI-003 active=0 → 제외
        bp = s.by_prefix(use_active=True)
        assert bp.get("INT") == 8
        assert "DCI" not in bp  # active=0 이라 제외

    def test_distinct_rules_active_vs_total(self):
        s = self.r.secure
        # active 기준 distinct=1 (INT만), total 기준 distinct=2 (INT+DCI)
        assert s.distinct_rules(use_active=True) == 1
        assert s.distinct_rules(use_active=False) == 2


class TestErrorHandling:
    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_qac_results_xml("nonexistent_results_data.xml")

    def test_empty_groups_warning(self):
        r = parse_qac_results_xml(
            '<AnalysisData><dataroot type="project"><tree type="rules"/></dataroot></AnalysisData>'
        )
        assert r.groups == {}
        assert any("RuleGroup 미발견" in w for w in r.parse_warnings)


_REAL = os.path.join(
    os.path.dirname(__file__), "..", "..", ".codex_tmp", "swsa_samples", "XML_APP_NE1aW.xml"
)


@pytest.mark.skipif(not os.path.exists(_REAL), reason="실데이터 샘플 없음 (.codex_tmp)")
class TestRealSampleAPP:
    """실 KJPDS02 NE1aW 샘플 — 회귀 고정값 (포맷 검증)."""

    def setup_method(self):
        self.r = parse_qac_results_xml(_REAL)

    def test_misra_rollup(self):
        m = self.r.misra
        assert m.active == 286 and m.total == 1283
        assert m.category(MISRA_MANDATORY).active == 233
        assert m.category(MISRA_REQUIRED).active == 52
        assert self.r.parse_warnings == []

    def test_secure_rollup(self):
        s = self.r.secure
        assert s.active == 210 and s.total == 1077
        # severity 카테고리
        assert {"High", "Middle", "Low"} <= set(s.categories)
