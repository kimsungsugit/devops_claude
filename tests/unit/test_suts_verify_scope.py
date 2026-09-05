"""시험 범위(component_map `verify`) 판정과 SUTS 보고.

## 왜 (KJPDS02_PV 실측, 2026-08-18)

`uds_generator` 의 파일 수집은 `verify=X`(시험 면제) 파일을 건너뛴다. 그런데 함수는
**AST 파서(`parse_c_project`)** 도 만들고, 그쪽은 루트를 **따로 훑어** 그 필터를 안 탄다.
결과: 면제 파일의 함수가 SUTS 에 시험 항목으로 실리는데 **아무 데도 안 남는다**.

    정본이 시험하는 1,005 unit 의 verify 분포   O 908 · 매핑없음 47 · ? 26 · X 24
    우리만 내는 152 unit 의 분포                 X 45 · ? 44 · O 43 · 매핑없음 20
                                                 ↑ 정본 2.4% 대 우리 29.6% (12배)

X 를 무조건 빼면 안 된다 — 정본도 24개를 담는다. 그래서 **거르지 않고 센다**.
시험을 뺄지는 사람이 정할 일이고, 조용하면 그 결정 기회 자체가 사라진다.

## ⚠ 판정은 단일 출처

경로 키 우선 · 파일명 폴백. 순서가 뒤바뀌면 같은 파일명이 여러 트리에 있을 때 엉뚱한
컴포넌트로 붙는다(맵이 그 충돌을 풀려고 경로 키를 둔다). 예전엔 이 판정이
`uds_generator` 안에 인라인으로만 있어 복제 위험이 컸다.
"""
from __future__ import annotations

import logging

import pytest

from generators.suts import collect_unit_functions
from report_gen.requirements import component_verify_of, resolve_component_entry

_MAP = {
    "lin.c": {"component": "LIN Stack(SwCom_20)", "verify": "X"},
    "lin": {"component": "LIN Stack(SwCom_20)", "verify": "X"},
    "FBL/Sources/LIN/lin.c": {"component": "Bootloader(SwCom_35)", "verify": "O"},
    "Door_PDS.c": {"component": "Door(SwCom_01)", "verify": "O"},
}


class TestVerifyResolution:
    def test_path_key_wins_over_filename(self):
        """경로 키가 이겨야 한다 — 같은 `lin.c` 가 두 트리에 있고 판정이 반대다."""
        assert component_verify_of("D:/x/FBL/Sources/LIN/lin.c", _MAP) == "O"
        assert component_verify_of("D:/y/Other/lin.c", _MAP) == "X"

    def test_backslash_path_is_normalized(self):
        assert component_verify_of(r"D:\x\FBL\Sources\LIN\lin.c", _MAP) == "O"

    def test_stem_fallback(self):
        assert component_verify_of("D:/z/lin", _MAP) == "X"

    def test_unknown_is_empty_not_o(self):
        """⚠ 모르는 것과 '면제 아님'을 섞지 않는다."""
        assert component_verify_of("D:/z/nosuch.c", _MAP) == ""
        assert component_verify_of("", _MAP) == ""
        assert component_verify_of("D:/z/lin.c", None) == ""
        assert resolve_component_entry("D:/z/nosuch.c", _MAP) == {}

    def test_entry_carries_component(self):
        assert resolve_component_entry("D:/y/Other/lin.c", _MAP)["component"].startswith("LIN")


def _fd(name, file):
    return {"a": {"id": "SwUFn_0101", "name": name, "prototype": f"void {name}(void)",
                  "file": file, "inputs": [], "outputs": [],
                  "globals_global": [], "globals_static": [], "logic_flow": []}}


class TestSutsScopeReport:
    def test_unit_carries_verify_scope(self, monkeypatch):
        monkeypatch.setattr("generators.suts._load_component_map", lambda: _MAP)
        u = collect_unit_functions(_fd("lin_lld_get_state", "D:/y/Other/lin.c"), sds_map={})[0]
        assert u["verify_scope"] == "X"

    def test_in_scope_unit_is_not_flagged(self, monkeypatch):
        """음성 대조군 — 시험 대상 파일이 X 로 찍히면 경고가 늑대를 부른다."""
        monkeypatch.setattr("generators.suts._load_component_map", lambda: _MAP)
        u = collect_unit_functions(_fd("g_Door_Init", "D:/y/Door_PDS.c"), sds_map={})[0]
        assert u["verify_scope"] == "O"

    def test_exempt_unit_is_reported_not_dropped(self, monkeypatch, caplog):
        """⚠ **거르지 않는다.** 정본도 X unit 24개를 담는다 — 빼는 건 사람 결정이다."""
        monkeypatch.setattr("generators.suts._load_component_map", lambda: _MAP)
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            units = collect_unit_functions(_fd("lin_lld_get_state", "D:/y/Other/lin.c"), sds_map={})
        assert len(units) == 1, "면제 unit 을 조용히 지웠다"
        # ⚠ `record.message` 는 지연 포매팅이라 `%` 인자가 아직 안 박혀 있다.
        #   `getMessage()` 로 완성된 문자열을 봐야 한다.
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "verify=X" in msgs, f"보고가 없다: {msgs}"
        assert "lin_lld_get_state" in msgs, f"어느 unit 인지 안 밝힌다: {msgs}"

    def test_no_map_says_so_instead_of_claiming_clean(self, monkeypatch, caplog):
        """⚠ 맵이 없으면 '면제 0건'이 아니라 **판정 안 함**이라고 말해야 한다."""
        monkeypatch.setattr("generators.suts._load_component_map", lambda: {})
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(_fd("whatever", "D:/y/Other/lin.c"), sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "component_map 없음" in msgs, msgs

    def test_map_load_failure_does_not_break_generation(self, monkeypatch):
        """맵 로드가 깨져도 산출물은 나가야 한다 — 보고는 부가 정보다."""
        def _boom():
            raise RuntimeError("boom")
        monkeypatch.setattr("generators.suts._load_component_map", _boom)
        units = collect_unit_functions(_fd("g_Door_Init", "D:/y/Door_PDS.c"), sds_map={})
        assert len(units) == 1 and units[0]["verify_scope"] == ""


@pytest.mark.parametrize("verify,expected", [("X", "X"), ("x", "X"), (" O ", "O"), ("", "")])
def test_verify_is_normalized(verify, expected):
    assert component_verify_of("D:/a/f.c", {"f.c": {"verify": verify}}) == expected
