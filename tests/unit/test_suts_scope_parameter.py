"""SUTS 시험 범위(`scope=suds|source`)가 **어떤 함수를 규격서에 넣는가**.

## 왜 이 파일이 생겼나 (2026-08-31)

판정이 오래 이렇게 생겼었다::

    if _scope == "suds":  ... SwUDS 설계 ID 로 거른다
    else:                 ... 소스 전체 (SwUDS 미대조)

`suds` 가 **아닌 모든 값**이 `else` 로 떨어진다. 오타(`sud`)·옛 저장값·미래의 세 번째
범위가 전부 **가장 넓은 범위**가 되어, 정본에 없는 함수가 ISO 26262 산출물에 들어갔다.
게다가 준비 게이트는 반대로 `== "source"` 로 판정해서 같은 값에 **"정본 기준"** 이라고
안심시켰다 — 한 값에 두 화면이 반대말을 했고, 틀리는 쪽이 넓은 방향이었다.

## 왜 헬퍼로 뽑았나

이 판정은 `generate_suts` 본체에 인라인이라 **전체 생성 없이는 검증할 수 없었다**.
프로젝트에서 가장 무거운 판정 하나가 시험 사각에 있던 셈이다.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from generators.suts import SCOPE_REFERENCE, SCOPE_SOURCE, apply_scope, normalize_scope


def _units() -> List[Dict[str, Any]]:
    return [
        {"name": "SwUnit_has_id_1", "suds_id": "SwUnit_01"},
        {"name": "not_in_swuds", "suds_id": ""},
        {"name": "SwUnit_has_id_2", "suds_id": "SwUnit_02"},
        {"name": "also_not_in_swuds"},          # 키 자체가 없는 경우
    ]


@pytest.mark.parametrize("raw,expect", [
    (None, SCOPE_REFERENCE), ("", SCOPE_REFERENCE), ("   ", SCOPE_REFERENCE),
    ("suds", SCOPE_REFERENCE), ("SUDS", SCOPE_REFERENCE), (" suds ", SCOPE_REFERENCE),
    ("source", SCOPE_SOURCE), ("SOURCE", SCOPE_SOURCE), (" source ", SCOPE_SOURCE),
])
def test_known_scopes_normalize_without_complaint(raw, expect) -> None:
    assert normalize_scope(raw) == (expect, "")


@pytest.mark.parametrize("raw", ["sud", "all", "reference", "sudss", "정본", "0"])
def test_unknown_scope_falls_back_to_the_narrow_one(raw) -> None:
    """모르는 값은 **좁은 쪽**으로 떨어지고 원본을 함께 돌려준다.

    넓은 쪽(`source`)으로 떨어지면 정본에 없는 함수가 조용히 규격서에 들어간다 —
    되돌리기 어려운 방향이라 fail-open 을 허용하지 않는다.
    """
    assert normalize_scope(raw) == (SCOPE_REFERENCE, raw)


def test_unknown_scope_actually_filters_like_suds() -> None:
    """**관측량으로** 확인한다 — 정규화만 맞고 필터가 안 걸리면 의미가 없다."""
    kept, notes = apply_scope(_units(), "sud")
    assert [u["name"] for u in kept] == ["SwUnit_has_id_1", "SwUnit_has_id_2"]
    # 조용히 넘기지 않는다. 모르는 값을 받은 사실이 보고에 남아야 한다.
    assert any("알 수 없는 시험 범위" in n and "sud" in n for n in notes), notes


def test_source_scope_keeps_everything() -> None:
    """음성 대조군 — `source` 는 실제로 전부 남긴다(폴백이 과하게 먹지 않는가)."""
    kept, notes = apply_scope(_units(), "source")
    assert len(kept) == 4
    assert any("소스 전체" in n for n in notes), notes


def test_reference_scope_reports_what_it_dropped() -> None:
    """좁힌 사실은 **반드시 보고**한다 — 조용히 자르면 커버리지가 자기 자신을 분모로 삼는다."""
    kept, notes = apply_scope(_units(), SCOPE_REFERENCE)
    assert len(kept) == 2
    assert any("2개 제외" in n for n in notes), notes


def test_no_design_ids_does_not_empty_the_document() -> None:
    """설계 ID 를 하나도 못 얻으면 **거르지 않는다**.

    거르면 SwUDS 를 못 읽은 프로젝트에서 규격서가 통째로 비고, 커버리지는 0/0 = 100% 로
    보인다. 대신 그 사실을 보고한다.
    """
    units = [{"name": "a"}, {"name": "b", "suds_id": ""}]
    kept, notes = apply_scope(units, SCOPE_REFERENCE)
    assert len(kept) == 2
    assert any("하나도 확보하지 못해" in n for n in notes), notes


def test_scope_does_not_mutate_the_caller_list() -> None:
    """호출부의 목록을 제자리에서 줄이지 않는다 — 뒤 단계가 같은 리스트를 다시 본다."""
    original = _units()
    kept, _ = apply_scope(original, SCOPE_REFERENCE)
    assert len(original) == 4, "입력 리스트가 훼손됐다"
    assert kept is not original
