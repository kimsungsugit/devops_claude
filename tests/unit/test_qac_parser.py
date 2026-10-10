"""QAC Parser 단위 테스트"""
from pathlib import Path

import pytest

from backend.services.qac_parser import (
    HISItem,
    MatrixItem,
    QACDataManager,
    parse_qac_report,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestHISItem:
    def test_split_string(self):
        result = HISItem.split_string("a,b,c", [","])
        assert result == ["a", "b", "c"]

    def test_split_string_empty(self):
        assert HISItem.split_string("", [","]) == []
        assert HISItem.split_string(None, [","]) == []

    def test_get_title_name(self):
        assert HISItem.get_title(MatrixItem.V_G, True) == "v(G)"
        assert HISItem.get_title(MatrixItem.CALLS, False) == "STCAL"

    def test_update_from_bs4(self):
        item = HISItem()
        # _convert_matrix_item matches by display name (CALLS, v(G)), not code (STCAL, STCYC)
        headers = ["Metric", "CALLS", "RETURN", "v(G)"]
        values = ["Values", "3", "1", "5"]
        assert item.update_from_bs4("TestFunc", headers, values)
        assert item.function_name == "TestFunc"
        assert item.get_matrix_value(MatrixItem.CALLS) == "3"
        assert item.get_matrix_value(MatrixItem.V_G) == "5"

    def test_update_from_bs4_mismatched_lengths(self):
        item = HISItem()
        assert not item.update_from_bs4("Func", ["a", "b"], ["x"])

    def test_update_from_bs4_empty_name(self):
        item = HISItem()
        assert not item.update_from_bs4("", ["a"], ["x"])


class TestQACDataManager:
    def test_init_builds_spec(self):
        mgr = QACDataManager()
        assert MatrixItem.V_G in mgr.dic_spec
        assert mgr.dic_spec[MatrixItem.V_G].list_spec == [11, 21, 31]

    def test_clear(self):
        mgr = QACDataManager()
        mgr.list_result.append(HISItem(function_name="dummy"))
        mgr.clear()
        assert len(mgr.list_result) == 0

    def test_check_warning_level(self):
        mgr = QACDataManager()
        # v(G) thresholds: [11, 21, 31]
        assert mgr.check_warning_level(MatrixItem.V_G, "5") == 0
        assert mgr.check_warning_level(MatrixItem.V_G, "15") == 1
        assert mgr.check_warning_level(MatrixItem.V_G, "25") == 2
        assert mgr.check_warning_level(MatrixItem.V_G, "35") == 3

    def test_check_warning_level_invalid(self):
        mgr = QACDataManager()
        assert mgr.check_warning_level(MatrixItem.V_G, "") == 0
        assert mgr.check_warning_level(MatrixItem.V_G, "abc") == 0

    def test_get_matrix_list(self):
        items = QACDataManager.get_matrix_list()
        assert MatrixItem.V_G in items
        assert MatrixItem.CALLS in items


class TestParseQACReport:
    def test_parse_new_version(self):
        path = FIXTURES / "qac_his_new.html"
        if not path.exists():
            pytest.skip("fixture missing")
        mgr = parse_qac_report(path, old_version=False)
        assert len(mgr.list_result) == 3
        names = [r.function_name for r in mgr.list_result]
        assert "Ap_BuzzerCtrl_Init" in " ".join(names)
        assert "Ap_BuzzerCtrl_Process" in " ".join(names)

    def test_parse_old_version(self):
        path = FIXTURES / "qac_his_old.html"
        if not path.exists():
            pytest.skip("fixture missing")
        mgr = parse_qac_report(path, old_version=True)
        assert len(mgr.list_result) >= 1

    def test_parse_auto_detect(self):
        path = FIXTURES / "qac_his_new.html"
        if not path.exists():
            pytest.skip("fixture missing")
        mgr = parse_qac_report(path)  # old_version=None → auto-detect
        assert len(mgr.list_result) == 3

    def test_parse_nonexistent_file(self):
        mgr = parse_qac_report(Path("/nonexistent/file.html"))
        assert hasattr(mgr, "parse_error") and mgr.parse_error

    def test_warning_levels_updated(self):
        path = FIXTURES / "qac_his_new.html"
        if not path.exists():
            pytest.skip("fixture missing")
        mgr = parse_qac_report(path, old_version=False)
        # Ap_BuzzerCtrl_Process has v(G)=15 which exceeds threshold 11
        vg_over = mgr.dic_spec_over_count.get(MatrixItem.V_G)
        assert vg_over is not None
        assert sum(vg_over.list_spec) > 0
