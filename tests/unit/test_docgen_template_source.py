"""템플릿을 무엇으로 삼는지 — **정본 우선**(사용자 결정, 2026-08-12).

생성기는 템플릿에서 표지·이력·Introduction·Test Environment 를 가져오고 명세 시트만
새로 쓴다. 그래서 템플릿 선택이 **문서의 나머지 전부**를 정한다.

실측(2026-08-11): 회사 표준 템플릿 v0.10 에는 `Introduction` 시트가 **없어서**
검증기가 매 생성마다 `Optional sheet missing: 1.Introduction` 으로 FAIL 을 냈다.
그리고 그 시트에 `Test Method`(REQ/FI)·`TC Generation Method`(AOR/AEC) 표기 규약 표가
있어, 없으면 읽는 사람이 칸 값을 대조할 근거가 없다.
"""
from __future__ import annotations

from backend.services.docgen_template_source import (
    choose_template_source,
    linked_doc_keys,
    resolve_template_for,
)


def test_reference_document_wins_over_standard_template():
    got, why = choose_template_source(
        "suts", registered_template="U:/tpl/(XXXX_SwUTS)_v0.10.xlsm",
        reference_doc="U:/proj/(KJPDS02_SwUTS)_v1.02.xlsm",
    )
    assert got.endswith("v1.02.xlsm")
    assert "정본" in why


def test_falls_back_to_standard_template_and_says_so():
    """정본이 없으면 표준 템플릿을 쓰되 **Introduction 이 없을 수 있다**고 말한다."""
    got, why = choose_template_source(
        "sts", registered_template="U:/tpl/std.xlsm", reference_doc="",
    )
    assert got == "U:/tpl/std.xlsm"
    assert "폴백" in why and "Introduction" in why


def test_no_template_is_reported_not_silently_ignored():
    got, why = choose_template_source("sits", registered_template="", reference_doc="")
    assert got == ""
    assert "서식 없이" in why


def test_prefer_reference_can_be_turned_off():
    """종전 동작(표준 템플릿 우선)으로 되돌릴 수 있어야 한다 — 되돌림 경로가 없으면 실험도 못 한다."""
    got, _ = choose_template_source(
        "uds", registered_template="std.docx", reference_doc="ref.docx",
        prefer_reference=False,
    )
    assert got == "std.docx"


def test_unreadable_choice_falls_back_and_warns():
    """정본이 stale 이라 못 읽으면 표준 템플릿으로 넘어가되 **그 사실을 남긴다**.

    ⚠ 조용히 폴백하면 "정본으로 만들었다" 고 오해한 채 다른 서식의 문서가 나간다.
    """
    calls: list[str] = []

    def _fake(path: str, *, label: str = "", reasons=None):
        calls.append(path)
        return None if path == "ref.xlsm" else "C:/local/std.xlsm"

    got, why = resolve_template_for(
        "suts", registered_template="std.xlsm", reference_doc="ref.xlsm", resolver=_fake,
    )
    assert got == "C:/local/std.xlsm"
    assert "폴백" in why and "ref.xlsm" in why
    assert calls == ["ref.xlsm", "std.xlsm"]


def test_both_unreadable_yields_none_with_reason():
    got, why = resolve_template_for(
        "sits", registered_template="a.xlsm", reference_doc="b.xlsm",
        resolver=lambda p, *, label="", reasons=None: None,
    )
    assert got is None
    assert "읽지 못해" in why


def test_doc_keys_cover_the_four_generated_specs():
    for doc, (ref_key, tpl_key) in (
        ("uds", ("uds", "uds_template")),
        ("sts", ("sts", "sts_template")),
        ("suts", ("suts", "suts_template")),
        ("sits", ("sits", "sits_template")),
    ):
        assert linked_doc_keys(doc) == (ref_key, tpl_key)
    assert linked_doc_keys("없는문서") == ("", "")


def test_routers_pass_reference_doc_to_the_single_rule():
    """세 문서의 **모든** 엔드포인트가 같은 규칙을 타는지.

    ⚠ SITS 는 엔드포인트가 3개다(sync·stream·async). 작성 중 실제로 하나를 빠뜨려
      `reference_doc_path` 가 정의되지 않은 채 참조되는 상태가 됐다 — Form 선언과
      사용처를 함수 단위로 짝지어 본다.
    """
    import re
    from pathlib import Path as _P

    repo = _P(__file__).resolve().parents[2]
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        src = (repo / rel).read_text(encoding="utf-8", errors="ignore")
        cur, declared, used = None, set(), set()
        for line in src.splitlines():
            m = re.match(r"(?:async )?def (\w+)\(", line)
            if m:
                cur = m.group(1)
            if "reference_doc_path: str = Form" in line:
                declared.add(cur)
            if "reference_doc=reference_doc_path" in line:
                used.add(cur)
        assert used <= declared, (
            f"{rel}: {sorted(used - declared)} 가 reference_doc_path 를 선언 없이 쓴다 (NameError)"
        )
        assert used == declared, f"{rel}: 선언만 하고 안 쓰는 곳 {sorted(declared - used)}"
