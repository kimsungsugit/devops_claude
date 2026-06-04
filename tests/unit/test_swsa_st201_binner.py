"""SwSA ST201 binner 단위테스트 — 밴드 경계 + 실 HMR 회귀."""
from __future__ import annotations

import os

import pytest

from backend.services.qac_parser import MatrixItem
from backend.services.swsa_st201_binner import (
    ST201_METRICS,
    bin_metric_functions,
    bin_values_into_bands,
    metric_item_for_name,
    parse_band_predicate,
    parse_st201_from_hmr,
)


class TestBandPredicate:
    def test_range(self):
        p = parse_band_predicate("1 ~ 10")
        assert p(1) and p(10) and not p(0) and not p(11)

    def test_gte(self):
        p = parse_band_predicate(">=31")
        assert p(31) and p(100) and not p(30)

    def test_gt(self):
        p = parse_band_predicate("> 10")
        assert p(11) and not p(10)

    def test_single(self):
        p = parse_band_predicate("0")
        assert p(0) and not p(1)

    def test_invalid(self):
        assert parse_band_predicate("측정치") is None
        assert parse_band_predicate("") is None


class TestBinIntoBands:
    def test_first_match_wins(self):
        # 겹치는 밴드(>10, >=11)에서 11은 먼저 매칭한 '>10'에 계수
        labels = ["1 ~ 10", "> 10", ">=11"]
        counts = bin_values_into_bands([5, 11, 12], labels)
        assert counts == [1, 2, 0]

    def test_out_of_band_dropped(self):
        # 0은 '1~10' 밴드 밖 → 어디에도 안 들어감
        counts = bin_values_into_bands([0, 5, 5], ["1 ~ 10", "> 10"])
        assert counts == [2, 0]  # 0은 제외


class TestMetricItemForName:
    def test_mapping(self):
        assert metric_item_for_name("Cyclomatic\nComplexity") == MatrixItem.V_G
        assert metric_item_for_name("Maximum Nesting Level") == MatrixItem.LEVEL
        assert metric_item_for_name("Maximum Function CallingNumber") == MatrixItem.CALLING
        assert metric_item_for_name("Maximum Function CalledNumber") == MatrixItem.CALLS
        assert metric_item_for_name("Number of Function Parameters") == MatrixItem.PARAM

    def test_no_match(self):
        assert metric_item_for_name("Recursion Function Number") is None
        assert metric_item_for_name("Component Stress Complexity") is None


class _FakeFn:
    """qac_parser.HISItem 인터페이스 stub (get_matrix_value / file_name / function_name)."""

    def __init__(self, v_g=0, level=0, calling=0, calls=0, file="a.c", func="f"):
        self._v = {
            MatrixItem.V_G: str(v_g),
            MatrixItem.LEVEL: str(level),
            MatrixItem.CALLING: str(calling),
            MatrixItem.CALLS: str(calls),
        }
        self.file_name = file
        self.function_name = func

    def get_matrix_value(self, mi):
        return self._v.get(mi, "")


class TestBandAssignment:
    def test_all_pass_band(self):
        fns = [_FakeFn(v_g=5, level=2, calling=3, calls=4) for _ in range(10)]
        res = bin_metric_functions(fns)
        for st in ST201_METRICS:
            m = res[st]
            assert m.result == "Pass"
            assert m.fail_count == 0
            assert m.bands[0].count == 10  # 전부 첫(Pass) 밴드

    def test_cyclomatic_boundaries(self):
        # V_G: 10→Pass, 11→Conditional(11~20), 30→Conditional(21~30), 31→Fail(>30)
        fns = [_FakeFn(v_g=10), _FakeFn(v_g=11), _FakeFn(v_g=30), _FakeFn(v_g=31)]
        m = bin_metric_functions(fns)["ST201"]
        assert m.bands[0].count == 1   # 1~10
        assert m.bands[1].count == 1   # 11~20
        assert m.bands[2].count == 1   # 21~30
        assert m.bands[3].count == 1   # >30
        assert m.fail_count == 1
        assert m.conditional_count == 2
        assert m.result == "Fail"
        assert m.max_value == 31

    def test_nesting_boundaries(self):
        # STMIF: 5→Pass, 6→Cond, 11→Fail
        fns = [_FakeFn(level=5), _FakeFn(level=6), _FakeFn(level=11)]
        m = bin_metric_functions(fns)["ST202"]
        assert [b.count for b in m.bands] == [1, 1, 1]
        assert m.fail_count == 1 and m.result == "Fail"

    def test_called_boundaries(self):
        # STCALL: 7→Pass(0~7), 8→Cond(8~12), 13→Fail(>=13)
        fns = [_FakeFn(calls=7), _FakeFn(calls=8), _FakeFn(calls=13)]
        m = bin_metric_functions(fns)["ST204"]
        assert [b.count for b in m.bands] == [1, 1, 1]
        assert m.fail_count == 1

    def test_worst_functions_sorted(self):
        fns = [_FakeFn(v_g=40, func="big"), _FakeFn(v_g=35, func="mid"), _FakeFn(v_g=5, func="ok")]
        m = bin_metric_functions(fns)["ST201"]
        assert m.worst_functions[0] == ("a.c::big", 40)
        assert m.worst_functions[1] == ("a.c::mid", 35)

    def test_non_numeric_skipped(self):
        fns = [_FakeFn(v_g=5), _FakeFn()]
        fns[1]._v[MatrixItem.V_G] = "N/A"  # 비숫자 → skip
        m = bin_metric_functions(fns)["ST201"]
        assert m.bands[0].count == 1  # v_g=5 만 계수, 'N/A' 는 skip

    def test_unbinned_tracked(self):
        # C3: 결측 metric 함수가 unbinned 로 집계되어 silent Pass 오기재 방지
        fns = [_FakeFn(v_g=5), _FakeFn()]
        fns[1]._v[MatrixItem.V_G] = ""  # 결측
        m = bin_metric_functions(fns)["ST201"]
        assert m.unbinned_count == 1
        assert m.binned_count == 1
        assert m.total_functions == 2

    def test_negative_value_unbinned(self):
        # I3: 음수 HIS metric 은 비정상 → Pass 밴드에 들어가지 않고 unbinned
        fns = [_FakeFn(v_g=-3)]
        m = bin_metric_functions(fns)["ST201"]
        assert m.bands[0].count == 0
        assert m.unbinned_count == 1


class TestParse:
    def test_missing_file(self):
        r = parse_st201_from_hmr("nonexistent_hmr.html")
        assert any("HMR 파일 없음" in w for w in r.parse_warnings)
        assert r.total_functions == 0


_REAL = os.path.join(
    os.path.dirname(__file__), "..", "..", ".codex_tmp", "swsa_samples",
    "LOG_QAC_NE1aW_01_HMR_27052026_183745.html",
)


@pytest.mark.skipif(not os.path.exists(_REAL), reason="실 HMR 샘플 없음")
class TestRealHmr:
    def test_app_metrics(self):
        r = parse_st201_from_hmr(_REAL)
        assert r.total_functions == 878
        assert r.old_version is False
        assert r.parse_warnings == []
        # 모든 메트릭 Pass (이 빌드는 복잡도 낮음)
        for st in ("ST201", "ST202", "ST203", "ST204"):
            assert r.metric(st).result == "Pass"
            assert r.metric(st).total_functions == 878
