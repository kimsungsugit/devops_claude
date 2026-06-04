"""SwSA ST201 binner 단위테스트 — 밴드 경계 + 실 HMR 회귀."""
from __future__ import annotations

import os

import pytest

from backend.services.qac_parser import MatrixItem
from backend.services.swsa_st201_binner import (
    ST201_METRICS,
    bin_metric_functions,
    parse_st201_from_hmr,
)


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
