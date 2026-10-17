"""SDS 파티션 엔트리의 kind 판정 — 밴드 화이트리스트·단일 출처 가드.

`_extract_sds_partition_map` 이 만드는 엔트리에는 `kind` 가 붙고, 그 kind 로
"SDS 밴드에 셀 것"과 "안 셀 것"이 갈린다. 이 파일은 그 판정을 담당하는
`build_sds_component_maps` 를 직접 대상으로 삼는다(docx 불필요).

## 왜 이 파일이 필요한가

`_add_entry` 의 `kind` **기본값이 `"component"`** 라, 11개 호출지점 중 인터페이스 함수
행(1곳)만 명시하고 나머지 10곳이 전부 컴포넌트로 등록됐다. 그 결과 SDS 밴드에
상태명(`initial`/`standby`/`auto close`)과 설계ID(`SwFn_`/`SwSTR_`/`SwST_`)가 섞여
실 컴포넌트 33개가 201개로 부풀었다(저장소 동봉 HDPDM01 SDS 실측).

## 지배 불변식

- **I1** `req_to_comps`/`comp_set` 은 kind 와 무관하게 전수 — 브리지 3종
  (`sds_func_to_reqs`/`design_to_reqs`/`comp_to_reqs`)이 여기 의존한다. 줄면 회귀.
- **I2** 밴드에서 뺀 것은 `sds_functions` 로 흘러가야 한다(커버리지 보존).
  이쪽 검증은 `test_sds_trace_purification.py` 담당.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report_gen.requirements import (
    _SDS_BAND_KINDS,
    _SDS_KIND_RANK,
    _canonical_swcom_id,
    build_sds_component_maps,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pm(**entries):
    """{키: (kind, related)} → partition_map 형태."""
    return {
        key: ({"related": related} if kind is None else {"related": related, "kind": kind})
        for key, (kind, related) in entries.items()
    }


# ── I1: component_ids 는 kind 와 무관하게 전수 ──────────────────────────────


def test_component_ids_never_shrinks_by_kind():
    """A2 — `req_to_comps`/`comp_set` 은 kind 무관 전수.

    브리지 회귀의 정면 차단. 밴드 정화가 어떤 kind 를 추가·강등하든 이 집합은
    `related` 에서 요구ID를 실제로 낳은 엔트리 전부여야 한다.
    """
    pm = _pm(
        swcom_01=("component", "SwTR_01"),
        g_iface_fn=("function", "SwTR_01"),
        initial=("design_element", "SwTR_01"),
        swfn_03=("design_id", "SwTR_01"),
        boot=("table_row", "SwTR_01"),
        some_heading=("heading", "SwTR_01"),
        legacy_no_kind=(None, "SwTR_01"),
    )
    maps = build_sds_component_maps(pm)
    assert maps["comp_set"] == set(pm)
    # 요구ID 는 _normalize_req_id 로 대문자 정규화된다(SwTR_01 → SWTR_01).
    assert set(maps["req_to_comps"]["SWTR_01"]) == set(pm)


def test_entries_without_parseable_req_ids_are_dropped():
    """`related` 는 있으나 요구ID 토큰이 없으면 두 맵 모두에서 탈락(게이트 보존)."""
    maps = build_sds_component_maps(_pm(
        swcom_01=("component", "SwTR_01"),
        noise=("component", "see chapter 3"),
    ))
    assert maps["comp_set"] == {"swcom_01"}
    assert maps["design_comp_set"] == {"swcom_01"}


def test_entries_without_related_are_dropped_but_keep_asil():
    """`related` 없는 엔트리는 맵에서 빠지되 `component_asil` 에는 남는다.

    요구의 component_id 가 related 없는 SwCom 정의 행을 가리킬 수 있어, ASIL 결합만
    게이트 밖에서 전 엔트리를 순회한다.
    """
    maps = build_sds_component_maps({
        "swcom_01": {"related": "SwTR_01", "kind": "component", "asil": "B"},
        "swcom_09": {"related": "", "kind": "component", "asil": "D"},
    })
    assert maps["comp_set"] == {"swcom_01"}
    assert maps["component_asil"] == {"swcom_01": "B", "swcom_09": "D"}


def test_related_id_with_internal_whitespace_is_normalized():
    """`SwRS_ 001` 처럼 내부 공백이 있어도 같은 요구로 정규화된다."""
    maps = build_sds_component_maps(_pm(swcom_01=("component", "SwTR_ 01, SwTR_02")))
    assert sorted(maps["req_to_comps"]) == ["SWTR_01", "SWTR_02"]


def test_malformed_partition_map_entries_are_skipped():
    """dict 아닌 값·빈 맵에도 죽지 않는다(파서 산출물이 늘 정상은 아니다)."""
    assert build_sds_component_maps({})["comp_set"] == set()
    assert build_sds_component_maps(None)["comp_set"] == set()
    maps = build_sds_component_maps({"bad": "not-a-dict", "swcom_01": {"related": "SwTR_01"}})
    assert maps["comp_set"] == {"swcom_01"}


# ── 밴드 화이트리스트 ───────────────────────────────────────────────────────


def test_band_whitelist_admits_only_component_kind():
    """A1 — 6종 kind 가 전부 요구를 물고 있어도 밴드에 드는 건 'component' 뿐."""
    maps = build_sds_component_maps(_pm(
        swcom_01=("component", "SwTR_01"),
        g_iface_fn=("function", "SwTR_01"),
        initial=("design_element", "SwTR_01"),
        swfn_03=("design_id", "SwTR_01"),
        boot=("table_row", "SwTR_01"),
        some_heading=("heading", "SwTR_01"),
    ))
    assert maps["design_comp_set"] == {"swcom_01"}
    assert maps["req_to_design_comps"]["SWTR_01"] == ["swcom_01"]


def test_missing_kind_defaults_to_component():
    """A3 — kind 없는 레거시 엔트리는 **밴드에 포함**(분류 이전 동작 보존).

    구 캐시·외부 주입 partition_map 이 새 분류로 조용히 밴드에서 빠지면 SDS 커버리지가
    이유 없이 떨어진다. 폴백은 `_SDS_DEFAULT_KIND` 하나뿐이므로 여기서 고정한다.
    """
    maps = build_sds_component_maps(_pm(legacy=(None, "SwTR_01")))
    assert maps["design_comp_set"] == {"legacy"}


def test_unknown_kind_falls_back_to_component():
    """등록 안 된 kind 문자열은 KeyError 가 아니라 기본값으로 흡수된다(fail-safe)."""
    maps = build_sds_component_maps(_pm(weird=("no_such_kind", "SwTR_01")))
    assert maps["design_comp_set"] == {"weird"}


def test_band_kinds_is_a_positive_whitelist():
    """A6 대응 — 화이트리스트는 긍정형이어야 한다.

    부정형(`kind != 'function'`)이면 새 kind 를 아무리 붙여도 전부 밴드를 통과해
    이 라운드의 분류가 통째로 무효가 된다. 상수 형태로 그 계약을 고정한다.
    """
    assert _SDS_BAND_KINDS == frozenset({"component"})
    assert set(_SDS_KIND_RANK) >= {"component", "function", "design_element",
                                   "design_id", "table_row", "heading"}
    # component 가 최상위 랭크 — 같은 키가 컴포넌트로도 등록되면 컴포넌트가 이긴다.
    assert _SDS_KIND_RANK["component"] == max(_SDS_KIND_RANK.values())
    # function 은 약한 kind 를 이겨야 한다(예전엔 약한 kind 가 먼저 걸리면 승격이 막혔다).
    assert _SDS_KIND_RANK["function"] > _SDS_KIND_RANK["table_row"]


# ── canonical 접기 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("SwCom_14", "SwCom_14"),
    ("SwCom_7", "SwCom_07"),      # A7 제로패딩
    ("Sw Com 7", "SwCom_07"),
    ("SwCom-7", "SwCom_07"),
    ("Door Control(SwCom_14)", "SwCom_14"),
    ("door control", ""),         # ID 없음 → 빈 문자열(원 키 유지)
    ("", ""),
    (None, ""),
])
def test_canonical_swcom_id(raw, expected):
    assert _canonical_swcom_id(raw) == expected


def test_canonical_folds_id_and_name_into_one_component():
    """A4 — `swcom_14` 와 `door control` 은 같은 표의 같은 행 → 밴드에서 1개로 접힌다.

    ⚠ 접힌 **원 키**는 `req_to_folded_comps` 에 반드시 남아야 한다. 소비처의 차집합이
    이걸 안 빼면 두 키가 모두 `sds_functions` 로 흘러 이중 계상된다.
    """
    pm = {
        "swcom_14": {"kind": "component", "related": "SwTR_01", "canonical": "SwCom_14"},
        "door control": {"kind": "component", "related": "SwTR_01", "canonical": "SwCom_14"},
        "g_iface": {"kind": "function", "related": "SwTR_01"},
    }
    maps = build_sds_component_maps(pm)
    assert maps["req_to_design_comps"]["SWTR_01"] == ["SwCom_14"]
    assert maps["design_comp_set"] == {"SwCom_14"}
    assert set(maps["req_to_folded_comps"]["SWTR_01"]) == {"swcom_14", "door control"}
    # I1: 조회 키는 셋 다 살아 있다 — 이름으로만 참조한 요구의 링크가 끊기면 안 된다.
    assert set(maps["req_to_comps"]["SWTR_01"]) == set(pm)


def test_entry_without_canonical_keeps_raw_key():
    """A5 — SwCom 표에 없는 고아 이름은 접지 않고 원 키를 그대로 표시한다(조용한 소실 방지)."""
    maps = build_sds_component_maps(_pm(orphan_module=("component", "SwTR_01")))
    assert maps["req_to_design_comps"]["SWTR_01"] == ["orphan_module"]
    assert maps["req_to_folded_comps"] == {}


def test_canonical_dedup_within_row():
    """같은 요구가 ID·이름 양쪽에서 걸려도 표시 라벨은 1개."""
    pm = {
        "swcom_14": {"kind": "component", "related": "SwTR_01, SwTR_02", "canonical": "SwCom_14"},
        "door control": {"kind": "component", "related": "SwTR_01", "canonical": "SwCom_14"},
    }
    maps = build_sds_component_maps(pm)
    assert maps["req_to_design_comps"]["SWTR_01"] == ["SwCom_14"]
    assert maps["req_to_design_comps"]["SWTR_02"] == ["SwCom_14"]


def test_folded_only_records_keys_that_actually_disappeared():
    """canonical 이 원 키와 같으면(대소문자까지) folded 에 넣지 않는다 — 무의미한 부풀림 방지."""
    pm = {"SwCom_14": {"kind": "component", "related": "SwTR_01", "canonical": "SwCom_14"}}
    maps = build_sds_component_maps(pm)
    assert maps["req_to_folded_comps"] == {}


def test_non_band_kinds_are_never_folded():
    """밴드 밖 kind 는 접기 대상이 아니다 — folded 가 부풀면 차집합이 함수를 잃는다."""
    pm = {"swfn_03": {"kind": "design_id", "related": "SwTR_01", "canonical": "SwCom_14"}}
    maps = build_sds_component_maps(pm)
    assert maps["req_to_design_comps"] == {}
    assert maps["req_to_folded_comps"] == {}
    assert maps["req_to_comps"]["SWTR_01"] == ["swfn_03"]


# ── 단일 출처 구조 가드 ─────────────────────────────────────────────────────


def test_routers_do_not_reimplement_sds_classification():
    """D12 — 두 라우터가 판정을 다시 구현하지 않는지.

    예전엔 `jenkins.py` 와 `local.py` 가 같은 kind 분기·같은 정규식을 **복제**하고 있어,
    한쪽만 고쳐지면 모드 간 SDS 컴포넌트 수가 갈렸다(`scripts/_ratchet_core.py` 가
    ruff/eslint ratchet 에서 겪은 것과 같은 실패). 판정은
    `build_sds_component_maps` 한 곳에만 있어야 한다.
    """
    # SDS 분류에 고유한 토큰만 금지한다. 요구ID 정규식 자체는 HSIS 매핑
    # (`jenkins.py` `_norm_hsis_req` 근처) 등 무관한 곳에서도 정당하게 쓰이므로 넣지 않는다.
    forbidden = (
        'kind") == "function"',
        "kind') == 'function'",
        "design_comp_set.add",
    )
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in src, (
                f"{rel} 가 SDS 분류를 재구현하고 있다: {token!r}. "
                f"판정은 report_gen.requirements.build_sds_component_maps 단일 출처."
            )
    # 단일 출처 사용 단언은 **살아 있는 소비자**(jenkins)에만. local 의 추적성 엔드포인트는
    # 2026-09-03(R27 B-2) 제거됐다 — 금지 토큰 검사(위)는 local 에도 계속 건다.
    jenkins_src = (REPO_ROOT / "backend/routers/jenkins.py").read_text(encoding="utf-8")
    assert "build_sds_component_maps" in jenkins_src, "jenkins 가 단일 출처를 쓰지 않는다"


# ── 실 문서 canary ──────────────────────────────────────────────────────────

_SDS_DOCS = sorted((REPO_ROOT / "docs").glob("*SDS*.docx"))


@pytest.mark.skipif(not _SDS_DOCS, reason="저장소 동봉 SDS docx 없음")
def test_real_sds_document_purification_numbers():
    """E13 — 실 문서 수치 봉인.

    저장소 동봉 HDPDM01 SDS 실측(라운드114 기준):
      정화 전  design 201  (SwCom 33 + 이름 33 + 설계ID 66 + 상태명 65 + 잔재 4)
      kind 분류 후      66  (SwCom ID 33 + 이름 33)
      canonical 접기 후 33  ← 이 프로젝트의 공식 SW 컴포넌트 수와 일치
      comp_set          700 (불변 — 브리지 3종이 여기 의존)

    수치가 바뀌면 파서나 분류가 움직였다는 뜻이다. 값을 갱신하기 전에 **왜** 바뀌었는지
    먼저 밝힐 것.
    """
    from report_gen.requirements import _extract_sds_partition_map

    maps = build_sds_component_maps(_extract_sds_partition_map(str(_SDS_DOCS[0])))
    assert len(maps["comp_set"]) == 700, "I1 위반 — 브리지 입력이 줄었다"
    assert len(maps["design_comp_set"]) == 33

    # 밴드 라벨은 전부 canonical SwCom ID — 상태명·설계ID·이름 키가 섞이면 실패한다.
    import re as _re
    assert all(_re.fullmatch(r"SwCom_\d{2}", c) for c in maps["design_comp_set"]), \
        sorted(c for c in maps["design_comp_set"] if not _re.fullmatch(r"SwCom_\d{2}", c))

    # I2: 어느 행에서도 (design ∪ folded ∪ 나머지) 가 component_ids 를 온전히 덮는다.
    for rid, comps in maps["req_to_comps"].items():
        dset = {c.lower() for c in maps["req_to_design_comps"].get(rid, [])}
        fset = {c.lower() for c in maps["req_to_folded_comps"].get(rid, [])}
        rest = {c.lower() for c in comps if c.lower() not in dset and c.lower() not in fset}
        assert (dset | fset | rest) >= {c.lower() for c in comps}, rid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
