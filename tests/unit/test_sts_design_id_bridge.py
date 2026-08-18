# tests/unit/test_sts_design_id_bridge.py
r"""STS 요구-함수 매핑의 **설계-ID 브리지** 회귀.

## 무엇을 못 하고 있었나 (실측 2026-08-18, KJPDS02_PV · 정본 SwRS/SwDS v3.01)

68 요구 중 20 이 함수에 안 붙었다. 그 20 중 16 은 SwDS 의 `related` **에는 있었다**.
그 16 이 걸린 파티션의 kind 를 세어 보니::

    design_id 19 · table_row 12 · design_element 4   ← `function` 0

즉 키가 `swfn_35`(설계 ID) 이거나 `차속에 따른 도어 open 방지`(한글 기능명)다. 후보가
함수 이름·모듈 이름뿐인 기존 사슬로는 **구조적으로** 못 닿는다 — 이름을 더 세게 비벼도
안 되고, 비비면 유령 매칭만 는다.

SwUDS 는 함수마다 `Related ID` 로 "이 함수가 구현하는 설계 요소"를 적어 둔다. 그 설계
ID 로 SwDS 설계 파티션을 찾으면 요구에 닿는다. 오프라인 시뮬 결과::

    base                    요구 48/68 · 링크 8,397 · 16건  1/16
    +브리지(SwCom 제외)        요구 64/68 · 링크 8,667 · 16건 16/16
    +브리지(SwCom 포함)        요구 64/68 · 링크 9,358          ← 새 요구 0, fan-out 만 증가

붙은 함수 이름이 요구 내용과 맞는지도 봤다(수치만으로는 over-trace 를 못 본다):
`SwEI_01`(battery power value 이상감지) → `u16s_BatteryLow_Check`/`u16s_BatteryHigh_Check`,
`SwTR_0606`(차속에 따른 도어 open 방지) → `u8s_VehicleSpeedCheck`.

## ⚠ 이름으로만 잇는다

SwUDS 의 `SwUFn` 번호와 소스 파서의 `SwUFn` 번호는 **다른 체계**다(43쌍 중 35쌍 불일치,
ID 조인만이 만든 링크 276건). 번호로 조인하면 조용한 오귀속이다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from generators.sts import load_uds_design_ids, map_requirements_to_functions


def _reqs(*ids: str) -> List[Dict[str, Any]]:
    return [{"id": i} for i in ids]


def _fd(**kw: str) -> Dict[str, Dict[str, Any]]:
    """fid → {name}. fid 는 일부러 SwUDS 와 **다른 번호**를 쓴다(실제 상황 재현)."""
    return {fid: {"name": name, "related": "", "module_name": ""} for fid, name in kw.items()}


class TestDesignPartitionsAreOutOfReachByName:
    """설계 파티션은 이름으로 못 닿는다 — 브리지가 없으면 0."""

    SDS = {
        # 설계 ID 키 — 함수 이름과 닮은 구석이 없다
        "swfn_30": {"kind": "design_id", "related": "SwTR_0606"},
        # 한글 기능명 키 — 정규화해도 함수 이름이 될 수 없다
        "차속에 따른 도어 open 방지": {"kind": "table_row", "related": "SwTR_0606"},
    }

    def test_without_bridge_the_requirement_stays_unmapped(self):
        out = map_requirements_to_functions(
            _reqs("SwTR_0606"), _fd(SwUFn_9001="u8s_VehicleSpeedCheck"), sds_map=self.SDS)
        assert out["SwTR_0606"] == [], "이름 사슬이 설계 파티션에 닿으면 안 된다(유령 매칭)"

    def test_with_bridge_it_maps(self):
        out = map_requirements_to_functions(
            _reqs("SwTR_0606"), _fd(SwUFn_9001="u8s_VehicleSpeedCheck"), sds_map=self.SDS,
            uds_design_ids={"u8s_vehiclespeedcheck": ["SwFn_30"]})
        assert out["SwTR_0606"] == ["SwUFn_9001"]

    def test_bridge_is_off_when_not_given(self):
        """None 이면 **꺼진다** — 없는 근거를 만들어내지 않는다."""
        for arg in (None, {}):
            out = map_requirements_to_functions(
                _reqs("SwTR_0606"), _fd(SwUFn_9001="u8s_VehicleSpeedCheck"),
                sds_map=self.SDS, uds_design_ids=arg)
            assert out["SwTR_0606"] == []


class TestJoinIsByNameNotByNumber:
    """⚠ 이 클래스가 이 파일의 핵심이다 — 번호 조인은 오귀속이다."""

    SDS = {"swfn_30": {"kind": "design_id", "related": "SwTR_0606"}}

    def test_matching_swufn_number_does_not_link(self):
        """SwUDS 의 `SwUFn_1416` 과 소스의 `SwUFn_1416` 은 **다른 함수**다.

        mutation: 조인을 `fid` 로 바꾸면 이 테스트가 실패한다.
        """
        out = map_requirements_to_functions(
            _reqs("SwTR_0606"),
            _fd(SwUFn_1416="s_ProcessLatchStates"),   # 소스에서의 1416
            sds_map=self.SDS,
            # SwUDS 문서에서 1416 은 다른 함수였다 → 이름이 안 맞으므로 링크 없음
            uds_design_ids={"s_doorstate_autoclose": ["SwFn_30"], "swufn_1416": ["SwFn_30"]})
        assert out["SwTR_0606"] == [], "SwUFn 번호로 이으면 남의 함수를 요구에 붙인다"

    def test_the_right_function_still_links_by_name(self):
        """대조군 — 같은 시나리오에서 **이름이 맞는** 함수는 붙는다."""
        out = map_requirements_to_functions(
            _reqs("SwTR_0606"),
            _fd(SwUFn_1416="s_ProcessLatchStates", SwUFn_2701="s_DoorState_AutoClose"),
            sds_map=self.SDS,
            uds_design_ids={"s_doorstate_autoclose": ["SwFn_30"]})
        assert out["SwTR_0606"] == ["SwUFn_2701"]


class TestExistingTiersAreUntouched:
    """브리지는 **더하기만** 한다 — 기존 두 티어의 결과를 바꾸지 않는다."""

    def test_comment_tier_still_short_circuits(self):
        """주석에 요구 ID 가 있으면 그대로 붙는다(브리지 유무와 무관)."""
        fd = {"f1": {"name": "foo", "related": "SwTR_0101", "module_name": ""}}
        sds = {"foo": {"kind": "function", "related": "SwTR_0202"}}
        without = map_requirements_to_functions(_reqs("SwTR_0101", "SwTR_0202"), fd, sds_map=sds)
        with_br = map_requirements_to_functions(
            _reqs("SwTR_0101", "SwTR_0202"), fd, sds_map=sds, uds_design_ids={"bar": ["SwFn_01"]})
        assert without == with_br == {"SwTR_0101": ["f1"], "SwTR_0202": []}

    def test_bridge_adds_on_top_of_the_comment_tier(self):
        """주석으로 이미 붙은 함수도 브리지가 **추가** 요구를 준다.

        1티어는 `continue` 로 SDS 티어를 건너뛰므로, 브리지를 그 루프 안에 넣었다면
        이 링크가 생기지 않는다 — 별도 패스로 도는 이유의 회귀 가드.
        """
        fd = {"f1": {"name": "foo", "related": "SwTR_0101", "module_name": ""}}
        sds = {"swfn_07": {"kind": "design_id", "related": "SwTR_0909"}}
        out = map_requirements_to_functions(
            _reqs("SwTR_0101", "SwTR_0909"), fd, sds_map=sds,
            uds_design_ids={"foo": ["SwFn_07"]})
        assert out == {"SwTR_0101": ["f1"], "SwTR_0909": ["f1"]}

    def test_no_duplicate_fid_when_both_tiers_hit(self):
        fd = {"f1": {"name": "foo", "related": "SwTR_0101", "module_name": ""}}
        sds = {"swfn_07": {"kind": "design_id", "related": "SwTR_0101"}}
        out = map_requirements_to_functions(
            _reqs("SwTR_0101"), fd, sds_map=sds, uds_design_ids={"foo": ["SwFn_07"]})
        assert out["SwTR_0101"] == ["f1"]




# ── load_uds_design_ids — SwUDS 문서 → 함수 이름 → 설계 ID ───────────────────

def _uds_docx(tmp_path: Path, tables: List[List[Tuple[str, str]]], name: str = "uds.docx") -> str:
    """`Function Information` 표를 담은 합성 docx (파서 규약: 값이 cells[2])."""
    docx = pytest.importorskip("docx")
    d = docx.Document()
    for rows in tables:
        tb = d.add_table(rows=len(rows), cols=3)
        for i, (label, value) in enumerate(rows):
            tb.rows[i].cells[0].text = label
            tb.rows[i].cells[2].text = value
    fp = tmp_path / name
    d.save(str(fp))
    return str(fp)


def _fi(related: str, fname: str = "foo_func", fid: str = "SwUFn_0101") -> List[Tuple[str, str]]:
    return [("[ Function Information ]", ""), ("ID", fid), ("Name", fname),
            ("Related ID", related)]


class TestLoadUdsDesignIds:
    def test_keyed_by_lowercased_function_name(self, tmp_path: Path):
        p = _uds_docx(tmp_path, [_fi("SwFn_30, SwSTR_01", fname="s_DoorState_AutoClose")])
        assert load_uds_design_ids(p) == {"s_doorstate_autoclose": ["SwFn_30", "SwSTR_01"]}

    def test_swcom_is_dropped_at_load_time(self, tmp_path: Path):
        p = _uds_docx(tmp_path, [_fi("SwCom_14, SwFn_30")])
        assert load_uds_design_ids(p) == {"foo_func": ["SwFn_30"]}

    def test_function_with_only_swcom_is_absent(self, tmp_path: Path):
        """빈 리스트를 남기지 않는다 — 소비처가 truthy 검사를 하기 때문."""
        p = _uds_docx(tmp_path, [_fi("SwCom_14")])
        assert load_uds_design_ids(p) == {}

    def test_missing_path_is_off_not_crash(self, tmp_path: Path):
        assert load_uds_design_ids("") == {}
        assert load_uds_design_ids(str(tmp_path / "없는파일.docx")) == {}

    def test_unreadable_document_reports_and_disables(self, tmp_path: Path, caplog):
        """⚠ 못 읽은 것을 "설계 ID 가 없다" 로 접지 않는다 — 경고를 남긴다."""
        bad = tmp_path / "broken.docx"
        bad.write_bytes(b"not a docx at all")
        with caplog.at_level("WARNING"):
            assert load_uds_design_ids(str(bad)) == {}
        assert any("브리지" in r.getMessage() for r in caplog.records),             "파싱 실패가 조용히 지나갔다"

    def test_same_name_twice_does_not_duplicate_ids(self, tmp_path: Path):
        p = _uds_docx(tmp_path, [_fi("SwFn_30"), _fi("SwFn_30, SwFn_31")])
        assert load_uds_design_ids(p) == {"foo_func": ["SwFn_30", "SwFn_31"]}


class TestSwComExclusionEndToEnd:
    """SwCom 제외는 **로더 한 곳**에만 있다 — 문서부터 매핑까지 통으로 확인한다.

    가드를 매핑 쪽에도 흩뿌리면 어느 한쪽을 지워도 테스트가 살아남는다(뮤테이션 생존).
    그래서 여기서는 로더를 실제로 태워서 판정한다.

    실측 근거: SwCom 을 넣으면 요구는 **0개** 늘고 요구당 링크 중앙이 4 → 138,
    최대 110 → 1,068 로 뛴다.
    """

    def test_swcom_only_function_never_reaches_the_requirement(self, tmp_path: Path):
        p = _uds_docx(tmp_path, [_fi("SwCom_14", fname="foo")])
        sds = {"swcom_14": {"kind": "component", "related": "SwTR_0606"}}
        out = map_requirements_to_functions(
            _reqs("SwTR_0606"), _fd(f1="foo"), sds_map=sds,
            uds_design_ids=load_uds_design_ids(p) or None)
        assert out["SwTR_0606"] == []

    @pytest.mark.parametrize("did", ["SwFn_30", "SwSTR_01", "SwST_06", "SwTK_04"])
    def test_the_four_tight_namespaces_do_bridge(self, tmp_path: Path, did: str):
        p = _uds_docx(tmp_path, [_fi(did, fname="foo")])
        sds = {did.lower(): {"kind": "design_id", "related": "SwTR_0606"}}
        out = map_requirements_to_functions(
            _reqs("SwTR_0606"), _fd(f1="foo"), sds_map=sds,
            uds_design_ids=load_uds_design_ids(p) or None)
        assert out["SwTR_0606"] == ["f1"], f"{did} 가 브리지를 못 탔다"


class TestParserIsASingleSource:
    """표 순회 규약이 라우터와 STS 양쪽에 복제되면 한쪽만 고쳐진다."""

    def test_jenkins_delegates_to_the_shared_extractor(self):
        from backend.routers import jenkins
        from report_gen import uds_related
        assert jenkins._docx_tables_text is uds_related.docx_tables_text

    def test_no_second_function_information_walk(self):
        """`Function Information` 판정이 **코드로는** 라우터에 없어야 한다.

        ⚠ 주석은 제외한다 — 왜 여기 없는지를 설명하는 주석까지 걸리면 이 가드는
          자기 설명을 금지하는 셈이 된다.
        """
        import inspect

        from backend.routers import jenkins
        code = [ln for ln in inspect.getsource(jenkins).splitlines()
                if not ln.lstrip().startswith("#")]
        assert not [ln for ln in code if "Function Information" in ln], (
            "라우터가 표 순회를 다시 구현했다 — report_gen/uds_related.py 를 쓸 것")


class TestGenerateStsActuallyWiresTheBridge:
    """⚠ 헬퍼 단독 테스트는 **호출부가 값을 버리는 것**을 못 본다.

    실제로 못 봤다 — 뮤테이션 M10(`generate_sts` 가 `uds_design_ids=None` 을 넘김)이
    위 21건을 전부 통과했다. 배선은 배선 층에서 확인한다.
    """

    class _Sentinel(RuntimeError):
        def __init__(self, kwargs):
            super().__init__("stop")
            self.kwargs = kwargs

    def _run(self, tmp_path: Path, monkeypatch, uds: str | None) -> dict:
        import generators.sts as gsts

        def _spy(reqs, fd, **kw):
            raise self._Sentinel(kw)

        monkeypatch.setattr(gsts, "map_requirements_to_functions", _spy)
        with pytest.raises(self._Sentinel) as exc:
            gsts.generate_sts(
                requirements_text=["SwTR_0606: 차속에 따른 도어 open 방지"],
                function_details={"f1": {"id": "f1", "name": "foo", "module_name": ""}},
                output_path=str(tmp_path / "out.xlsm"),
                uds_path=uds,
            )
        return exc.value.kwargs

    def test_design_ids_reach_the_mapper(self, tmp_path: Path, monkeypatch):
        uds = _uds_docx(tmp_path, [_fi("SwFn_30", fname="foo")])
        kw = self._run(tmp_path, monkeypatch, uds)
        assert kw["uds_design_ids"] == {"foo": ["SwFn_30"]}

    def test_without_uds_the_mapper_is_told_the_bridge_is_off(self, tmp_path: Path, monkeypatch):
        """대조군 — 빈 dict 를 넘긴다(거짓 데이터를 만들지 않는다)."""
        kw = self._run(tmp_path, monkeypatch, None)
        assert kw["uds_design_ids"] == {}
