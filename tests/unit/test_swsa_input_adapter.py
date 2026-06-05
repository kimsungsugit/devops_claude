"""SwSA input_adapter 단위테스트 — 발견 분류 + 다중 모듈 병합."""
from __future__ import annotations

from backend.services.swsa_input_adapter import (
    SwsaLogSet,
    collect_swsa_inputs,
    discover_swsa_logs,
    merge_pmd_results,
    merge_qac_results,
)
from backend.services.swsa_pmd_parser import parse_pmd_cpd
from backend.services.swsa_qac_xml_parser import parse_qac_results_xml

_XML_TPL = """<AnalysisData helix_qac_version="Helix QAC 2025.1"><dataroot type="project">
<tree type="files"><Folder basename="Source Files" total="{ft}" active="{fa}"/></tree>
<tree type="rules"><RuleGroup name="M3CM" total="{t}" active="{a}">
<Rule id="M3CM-1" text="MISRA Mandatory" total="{t}" active="{a}">
<Rule id="Rule-8.6" text="x" total="{t}" active="{a}"><Message guid="m" total="{t}" active="{a}"/></Rule>
</Rule></RuleGroup></tree></dataroot></AnalysisData>"""

_PMD = "Found a 60 line (200 tokens) duplication in the following files:\nStarting at line 1 of a.c\n"


class FakeResolver:
    """list_dir / read_bytes stub."""

    def __init__(self, files: dict):
        self._files = files  # path -> bytes

    def list_dir(self, path, pattern="*", recursive=False):
        return list(self._files.keys())

    def read_bytes(self, path):
        return self._files[path]


class TestDiscovery:
    def test_classify_by_basename(self):
        files = {
            "U:/PV/QAC/APP_x/results_data.xml": b"",
            "U:/PV/QAC/APP_x/QAC_APP_HMR_1.html": b"",
            "U:/PV/QAC/APP_x/QAC_APP_RCR_1.html": b"",  # RCR 무시
            "U:/PV/PMD/APP_x/APP_PMD_Report.txt": b"",
            "U:/PV/QAC/APP_x/note.png": b"",            # 무시
        }
        ls = discover_swsa_logs(FakeResolver(files), "U:/PV")
        assert ls.qac_xml == ["U:/PV/QAC/APP_x/results_data.xml"]
        assert len(ls.qac_hmr) == 1 and "HMR" in ls.qac_hmr[0]
        assert len(ls.pmd_txt) == 1
        assert ls.total == 3

    def test_empty_folder_warns(self):
        ls = discover_swsa_logs(FakeResolver({}), "U:/PV")
        assert ls.total == 0
        assert any("미발견" in w for w in ls.warnings)

    def test_list_dir_failure_graceful(self):
        class Boom:
            def list_dir(self, *a, **k):
                raise OSError("worker down")
        ls = discover_swsa_logs(Boom(), "U:/PV")
        assert ls.total == 0
        assert any("스캔 실패" in w for w in ls.warnings)


class TestMergeQac:
    def test_two_modules_sum(self):
        a = parse_qac_results_xml(_XML_TPL.format(ft=100, fa=40, t=20, a=10))
        b = parse_qac_results_xml(_XML_TPL.format(ft=50, fa=20, t=8, a=6))
        merged = merge_qac_results([a, b])
        assert merged.misra.active == 16        # 10 + 6
        assert merged.misra.total == 28         # 20 + 8
        assert merged.source_files_total == 150
        # 동일 rule_id(Rule-8.6) 합산 → 1 distinct, active=16
        assert merged.misra.distinct_rules() == 1
        leaf = merged.misra.leaf_rules[0]
        assert leaf.rule_id == "Rule-8.6" and leaf.active == 16

    def test_single_module_passthrough(self):
        a = parse_qac_results_xml(_XML_TPL.format(ft=100, fa=40, t=20, a=10))
        assert merge_qac_results([a]) is a

    def test_per_module_populated(self):
        # v0.11 detail(J=APP/K=BOOT) 용 per_module 기록
        a = parse_qac_results_xml(_XML_TPL.format(ft=100, fa=40, t=20, a=10))
        b = parse_qac_results_xml(_XML_TPL.format(ft=50, fa=20, t=8, a=6))
        merged = merge_qac_results([a, b], ["APP", "BOOT"])
        leaf = next(lr for lr in merged.misra.leaf_rules if lr.rule_id == "Rule-8.6")
        # Rule-8.6: APP active=10, BOOT active=6
        assert leaf.active_for("APP") == 10
        assert leaf.active_for("BOOT") == 6
        assert leaf.active == 16

    def test_extraction_failed_excluded(self):
        ok = parse_qac_results_xml(_XML_TPL.format(ft=100, fa=40, t=20, a=10))
        bad = parse_qac_results_xml("<AnalysisData><broken")
        merged = merge_qac_results([bad, ok])
        assert merged.misra.active == 10  # 손상 모듈 제외


class TestMergePmd:
    def test_dedup_blocks(self):
        r1 = parse_pmd_cpd(_PMD)
        r2 = parse_pmd_cpd(_PMD)  # 동일 블록
        merged = merge_pmd_results([r1, r2])
        assert merged.total_blocks == 1  # 중복 제거


class TestCollect:
    def test_end_to_end_with_fake_resolver(self):
        files = {
            "U:/PV/QAC/APP/results_data.xml": _XML_TPL.format(ft=100, fa=40, t=20, a=10).encode(),
            "U:/PV/QAC/BOOT/results_data.xml": _XML_TPL.format(ft=50, fa=20, t=8, a=6).encode(),
            "U:/PV/PMD/APP/x_PMD_Report.txt": _PMD.encode(),
        }
        data = collect_swsa_inputs(FakeResolver(files), "U:/PV")
        assert data.qac_xml.misra.active == 16
        assert data.pmd.total_blocks == 1
        assert sorted(data.modules) == ["APP", "BOOT"]


def test_logset_total_property():
    ls = SwsaLogSet(qac_xml=["a"], qac_hmr=["b", "c"], pmd_txt=["d"])
    assert ls.total == 4


class TestLatestPerModule:
    """날짜 중복 합산 차단 — 모듈별 최신 분석만 선택."""

    def test_collect_dedups_dates(self):
        # APP/BOOT 각 2개 날짜 → 최신만 (2088 더블카운팅 방지)
        files = {
            "U:/PV/QAC/APP_260326_v2631/results_data.xml": _XML_TPL.format(ft=100, fa=40, t=20, a=10).encode(),
            "U:/PV/QAC/APP_260527_v0.05/results_data.xml": _XML_TPL.format(ft=200, fa=80, t=40, a=30).encode(),
            "U:/PV/QAC/BOOT_260402_v1.13/results_data.xml": _XML_TPL.format(ft=50, fa=20, t=8, a=6).encode(),
            "U:/PV/QAC/BOOT_260527_v1.16/results_data.xml": _XML_TPL.format(ft=60, fa=25, t=10, a=7).encode(),
        }
        data = collect_swsa_inputs(FakeResolver(files), "U:/PV")
        # 최신: APP_260527(a=30) + BOOT_260527(a=7) = 37 (260326/260402 제외)
        assert data.qac_xml.misra.active == 37
        assert any("이전 분석 제외" in w for w in data.warnings)

    def test_single_date_no_drop(self):
        files = {
            "U:/PV/QAC/APP_260527/results_data.xml": _XML_TPL.format(ft=100, fa=40, t=20, a=10).encode(),
        }
        data = collect_swsa_inputs(FakeResolver(files), "U:/PV")
        assert data.qac_xml.misra.active == 10
        assert not any("제외" in w for w in data.warnings)
