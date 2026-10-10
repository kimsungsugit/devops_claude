"""`sds_functions` 에서 설계 요소 분리 — "컴포넌트 아닌 것 = 함수" 가정 제거.

라운드114 밴드 정화(kind 화이트리스트)로 강등된 것들(설계ID `SwFn_`/`SwST_`, 상태명
`standby`, 미확인 표행, heading 잔재)이 전부 차집합을 타고 `sds_functions` 로 흘렀다.
프론트 패널이 그 목록을 "설계 컴포넌트의 **멤버 함수**"라 라벨하므로 목차 줄
(`"33\tswcom_35: bootloader\t110"`)까지 함수로 표시됐다.

저장소 동봉 HDPDM01 실측(정화 후):
    sds_functions 634건 중 135건(21.3%)이 비-함수
    63행 중 52행이 오염, SWNTR_0408 은 10/10 전부 비-함수
    정화 전에는 499건 100% function 이었다 — 즉 라운드114 가 만든 회귀다

⚠ 함수만 남기고 끝내면 **14행이 uncovered 로 회귀**한다(설계 근거가 설계요소뿐인 요구).
그래서 `has_design` 3-site 가 `sds_design_elements` 를 함께 봐야 한다.
"""
from __future__ import annotations

import pytest

from report_gen.requirements import (
    build_sds_component_maps,
    generate_uds_traceability_matrix,
)


def _pm(**entries):
    """{키: (kind, related)} → 파티션 맵."""
    return {k: {"kind": v[0], "related": v[1]} for k, v in entries.items()}


PM = _pm(
    swcom_01=("component", "SwTR_01"),
    swst_01=("design_id", "SwTR_01"),          # 설계ID — 함수 아님
    standby=("design_element", "SwTR_01"),     # 상태명 — 함수 아님
    g_do_work=("function", "SwTR_01"),         # 진짜 인터페이스 함수
    junk_row=("table_row", "SwTR_02"),         # 미확인 표행 — 함수 아님
    toc_line=("heading", "SwTR_02"),           # 목차/heading 잔재 — 함수 아님
)


def _matrix(pairs, req_ids=("SwTR_01", "SwTR_02")):
    return generate_uds_traceability_matrix(
        [{"id": r, "name": r} for r in req_ids],
        mapping_pairs=[], vcast_rows=[], sds_pairs=pairs,
        sits_rows=[], uds_function_ids=[], component_asil={},
    )


def _pairs_from(pm):
    m = build_sds_component_maps(pm)
    return [{"requirement_id": rid,
             "component_ids": comps,
             "design_component_ids": m["req_to_design_comps"].get(rid, []),
             "folded_component_ids": m["req_to_folded_comps"].get(rid, []),
             "design_element_ids": m["req_to_element_comps"].get(rid, [])}
            for rid, comps in sorted(m["req_to_comps"].items())], m


def test_element_bucket_excludes_components_and_functions():
    """설계 요소 버킷 = 밴드도 함수도 아닌 것만."""
    m = build_sds_component_maps(PM)
    assert set(m["req_to_element_comps"]["SWTR_01"]) == {"swst_01", "standby"}
    assert set(m["req_to_element_comps"]["SWTR_02"]) == {"junk_row", "toc_line"}
    # 컴포넌트·함수는 절대 들어오지 않는다
    for bucket in m["req_to_element_comps"].values():
        assert "swcom_01" not in bucket
        assert "g_do_work" not in bucket


def test_sds_functions_contains_only_functions():
    """핵심 — 상태명·설계ID·목차줄이 '함수'로 나오지 않는다."""
    pairs, _ = _pairs_from(PM)
    rows = {r["requirement_id"]: r for r in _matrix(pairs)["rows"]}
    assert rows["SwTR_01"]["sds_functions"] == ["g_do_work"]
    assert set(rows["SwTR_01"]["sds_design_elements"]) == {"swst_01", "standby"}
    # 함수가 하나도 없는 요구는 함수 목록이 비어야 한다(예전엔 표행·heading 이 들어찼다)
    assert rows["SwTR_02"]["sds_functions"] == []
    assert set(rows["SwTR_02"]["sds_design_elements"]) == {"junk_row", "toc_line"}


def test_no_entry_is_lost_or_double_counted():
    """I2 — components ∪ functions ∪ elements ∪ folded ⊇ component_ids, 그리고 교집합 없음."""
    pairs, m = _pairs_from(PM)
    rows = {r["requirement_id"]: r for r in _matrix(pairs)["rows"]}
    for rid_raw, rid in (("SwTR_01", "SWTR_01"), ("SwTR_02", "SWTR_02")):
        r = rows[rid_raw]
        comps = {c.lower() for c in r["sds_components"]}
        fns = {c.lower() for c in r["sds_functions"]}
        els = {c.lower() for c in r["sds_design_elements"]}
        folded = {c.lower() for c in m["req_to_folded_comps"].get(rid, [])}
        need = {c.lower() for c in m["req_to_comps"][rid]}
        assert need <= (comps | fns | els | folded), f"{rid} 누락"
        assert not (fns & els), f"{rid} 함수/설계요소 이중 계상"


def test_coverage_unchanged_by_the_split():
    """분리 전/후 설계 보유 판정이 완전히 같아야 한다 — 커버리지 회귀 0."""
    pairs, _ = _pairs_from(PM)
    after = {r["requirement_id"]: r for r in _matrix(pairs)["rows"]}
    # 분리 이전 = design_element_ids 를 안 넘긴 상태(구 캐시와 동일)
    before_pairs = [{k: v for k, v in p.items() if k != "design_element_ids"} for p in pairs]
    before = {r["requirement_id"]: r for r in _matrix(before_pairs)["rows"]}
    for rid in after:
        _has_a = bool(after[rid]["sds_components"] or after[rid]["sds_functions"]
                      or after[rid]["sds_design_elements"])
        _has_b = bool(before[rid]["sds_components"] or before[rid]["sds_functions"])
        assert _has_a is _has_b, rid


def test_stale_cache_degrades_to_pre_split_behavior():
    """구 캐시엔 design_element_ids 가 없다 → 전부 sds_functions(분리 이전 동작), 손실 0."""
    pairs, _ = _pairs_from(PM)
    stale = [{k: v for k, v in p.items() if k != "design_element_ids"} for p in pairs]
    rows = {r["requirement_id"]: r for r in _matrix(stale)["rows"]}
    assert set(rows["SwTR_01"]["sds_functions"]) == {"g_do_work", "swst_01", "standby"}
    assert rows["SwTR_01"]["sds_design_elements"] == []


def test_design_only_requirement_stays_covered():
    """설계 근거가 설계요소뿐인 요구 — 함수만 정화하면 uncovered 로 회귀하는 케이스.

    HDPDM01 실측 14행이 여기 해당한다(SWNTR_0408 등). has_design 3-site 가
    sds_design_elements 를 봐야만 covered 가 유지된다.
    """
    pm = _pm(swst_09=("design_id", "SwTR_03"))
    pairs, _ = _pairs_from(pm)
    rows = {r["requirement_id"]: r for r in _matrix(pairs, req_ids=("SwTR_03",))["rows"]}
    r = rows["SwTR_03"]
    assert r["sds_components"] == [] and r["sds_functions"] == []
    assert r["sds_design_elements"] == ["swst_09"]     # ← 유일한 설계 근거


@pytest.mark.parametrize("path,token", [
    ("backend/routers/jenkins.py", 'row.get("sds_design_elements")'),
    # `backend/routers/local.py` 의 `/api/local/traceability` 는 2026-09-03(R27 B-2) 제거 —
    # 호출자 0인 죽은 사본이었다. 살아 있는 site 는 jenkins + 프론트 둘이다.
    ("frontend-v2/src/components/sections/SrsSdsSection.jsx", "'sds_design_elements'"),
])
def test_has_design_live_site_lockstep(path, token):
    """살아 있는 site(jenkins·프론트) 중 한 곳만 빠지면 그 표면에서만 커버리지가 조용히 떨어진다."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8", errors="ignore")
    assert token in text, f"{path} 가 sds_design_elements 를 has_design 에 안 넣었다"


def test_both_backend_modes_emit_the_field():
    """생산자(`report_gen/requirements.py`)와 jenkins 경로가 같은 키를 내야 프론트가 갈리지 않는다.

    (local 모드 추적성 엔드포인트는 2026-09-03 R27 B-2 에서 제거 — 추적성 화면은 파일 모드와
    무관하게 `/api/jenkins/uds/*` 를 쓴다.)
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for path in ("report_gen/requirements.py",):
        text = (root / path).read_text(encoding="utf-8", errors="ignore")
        assert '"sds_design_elements"' in text, path
    jenkins = (root / "backend" / "routers" / "jenkins.py").read_text(encoding="utf-8", errors="ignore")
    assert '"design_element_ids"' in jenkins, "jenkins sds_pairs 가 설계요소를 안 싣는다"
