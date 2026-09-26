"""미추적 leaf 함수가 **호출자의 요구를 승계하지 않는다**(R11 종결 가드).

백로그 "SRS 미추적 Phase 3 — 콜그래프 roll-up"(leaf 를 지배 조상의 요구로 승계)이 세 번
올라왔다. 2026-08-19 에 실측으로 종결했고, 이 파일이 그 결정을 되돌림으로부터 지킨다.

## 왜 안 하는가 (실측)

KJPDS02_PV 콜그래프(함수 1157 · 엣지 1476) leaf 514건의 도달 루트 분포

    297(57.8%) 호출자 없음 · **163(31.7%) 단일 지배 조상** · 36 2~3 · 18 4+

구조적 전제(단일 조상)는 3분의 1쯤 성립한다. 막히는 건 그 다음이다:

    추적된 조상이 **정확히 1개**인 미추적 함수 4건 → **4건 전부 조상이 다중 요구**
    추적 함수 349개의 요구 수 분포: 단일 요구 33개 · 나머지 2~17개

조상이 하나여도 그 조상이 요구를 2~17개 달고 있어, 승계하면 leaf 하나가 요구 여러 개에
붙는다. 커밋 `52e4b08`(SDS 컴포넌트 24배 과대표기 정화)이 정확히 막은 fan-out 의 **반대
방향**이다 — 그때는 부모 related 를 인터페이스 함수에 상속시켜 16 SwCom 이 382 로 부풀었다.

그리고 고칠 대상이 없다: 실측(build_125) `unmapped_app_design_gap` **0** · `covered`
**68/68**. 바뀌는 건 화면의 미추적 숫자(627→~3)뿐이고 대가는 감사 문서의 근거 없는 링크다.

⚠ `unmapped_uds_linked` 의 'roll-up' 은 **설계 문서 계층**(leaf 가 부모 SwUFn 아래
  설계됨) 이야기다. 근거는 `in_uds`(UDS 등재)이지 호출 관계가 아니다 — 둘을 같은 말로
  읽으면 이 백로그가 네 번째로 올라온다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from report_gen.requirements import generate_uds_traceability_matrix

#: 부모 `Ap_Door_Run` 은 SDS 함수명 브리지로 SwTR_001 에 추적되고 UDS 에도 등재된다.
#: leaf `s_Door_ClampLimit` 은 **자기 링크도 UDS 등재도 없다** — 승계가 없으면 미추적·미설계다.
_PARENT = "Ap_Door_Run"
_LEAF = "s_Door_ClampLimit"


def _matrix() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = [{"id": "SwTR_001"}, {"id": "SwTR_002"}]
    sds_pairs = [{"requirement_id": "SwTR_001", "component_ids": [_PARENT]}]
    # ⚠ `source == "VectorCAST"` 가 없으면 행이 vcast 입력으로 세어지지도 않는다
    #   (`requirements.py` 의 진입 조건). 픽스처가 조용히 공허 통과하던 자리다.
    vcast = [
        {"source": "VectorCAST", "subprogram": _PARENT, "testcase": "TC_01", "result": "pass"},
        {"source": "VectorCAST", "subprogram": _LEAF, "testcase": "TC_02", "result": "pass"},
    ]
    return generate_uds_traceability_matrix(
        items, [], vcast, sds_pairs=sds_pairs, uds_function_ids=[_PARENT])


class TestUntracedLeafIsNotAbsorbedByItsCaller:
    """추적된 부모가 있어도 미추적 leaf 는 미추적으로 남는다.

    ⚠ 이 테스트는 **구현되면 실패한다** — 그게 목적이다. 승계를 넣으면
      `leaf_helper` 가 부모의 요구로 흡수돼 아래 단언이 깨진다.
    """

    def test_fixture_actually_produces_an_unmapped_leaf(self):
        """⚠ 먼저 픽스처가 살아 있는지 본다 — 비면 아래 단언이 전부 공허 통과다."""
        m = _matrix()
        um = m.get("unmapped_vcast") or []
        assert len(um) == 1, f"미추적 행이 1건이어야 한다(현재 {len(um)}) — 픽스처가 죽었다"
        assert um[0].get("in_uds") is False, um[0]

    def test_leaf_stays_unmapped(self):
        m = _matrix()
        unmapped = {str(u.get("subprogram") or "") for u in (m.get("unmapped_vcast") or [])}
        assert _LEAF in unmapped, (
            "미추적 leaf 가 사라졌다 — 호출자의 요구를 승계했는가? "
            "그렇다면 이 모듈 docstring 의 실측을 먼저 읽을 것")

    def test_traced_parent_does_not_gain_the_leaf(self):
        """반대 방향도 본다 — 부모의 source_ids 에 leaf 가 끼어들지 않는다."""
        m = _matrix()
        row = next(r for r in m["rows"] if r["requirement_id"] == "SwTR_001")
        srcs = {str(s).strip().lower() for s in (row.get("source_ids") or [])}
        assert _PARENT.lower() in srcs, f"부모가 추적되지 않았다 — 픽스처 확인: {srcs}"
        assert _LEAF.lower() not in srcs, (
            f"leaf 가 부모 요구의 설계 근거로 승격됐다(fan-out) — 52e4b08 이 막은 형태: {srcs}")

    def test_leaf_counts_as_a_real_design_gap_not_a_granularity_diff(self):
        """UDS 에도 없는 leaf 는 '입도차'가 아니라 진짜 갭으로 세어야 한다."""
        s = _matrix()["summary"]
        assert s["unmapped_design_gap"] == 1, s
        assert s["unmapped_uds_linked"] == 0, s
        assert s["unmapped_app_design_gap"] == 1, s


class TestTheGeneratorTakesNoCallGraph:
    """생성기는 콜그래프를 **받지 않는다** — 승계를 하려면 여기부터 바뀐다.

    ⚠ 이건 동작 단언이 아니라 **결정 트립와이어**다. 시그니처에 콜그래프가 들어오는
      순간 이 테스트가 깨지고, 그때 위 실측을 다시 읽게 된다. 값이 없다고 지우지 말 것 —
      지우면 백로그가 조용히 네 번째로 올라온다.
    """

    def test_signature_has_no_call_graph_parameter(self):
        import inspect

        params = set(inspect.signature(generate_uds_traceability_matrix).parameters)
        forbidden = {p for p in params
                     if any(t in p.lower() for t in ("call_graph", "callers", "call_tree", "callgraph"))}
        assert not forbidden, (
            f"콜그래프 인자가 생겼다: {sorted(forbidden)} — 모듈 docstring 의 실측(조상 4건 "
            "전부 다중 요구 · 추적함수 349 중 단일요구 33)을 먼저 확인할 것")

    def test_module_does_not_import_call_tree(self):
        import pathlib

        src = pathlib.Path("report_gen/requirements.py").read_text(encoding="utf-8")
        for token in ("build_call_tree_precise", "from backend.services.call_tree"):
            assert token not in src, f"콜그래프 구현이 들어왔다: {token!r}"


class TestTheHonestCountsStillHold:
    """분류의 근거가 `in_uds` 라는 것(호출 관계가 아님)을 고정한다."""

    def test_design_gap_is_the_complement_of_in_uds(self):
        m = _matrix()
        s = m.get("summary") or {}
        um = m.get("unmapped_vcast") or []
        linked = sum(1 for u in um if u.get("in_uds"))
        gap = sum(1 for u in um if not u.get("in_uds"))
        assert s.get("unmapped_uds_linked", linked) == linked
        assert s.get("unmapped_design_gap", gap) == gap
        # 두 축의 합이 전체다 — 제3의 축(콜그래프)이 끼면 이 항등식이 깨진다.
        assert linked + gap == len(um), (linked, gap, len(um))
