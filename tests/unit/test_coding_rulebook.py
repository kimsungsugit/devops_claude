"""코딩 룰북 조립(Q4) — 카테고리 분류·증거 없는 규칙 제외·Markdown 서버 조립.

핵심 계약: 증거 0건 규칙은 룰북에 넣지 않고 **제외 사유를 남긴다**(일반론 룰이 섞이면 문서
전체의 신뢰가 무너진다). Markdown은 서버가 조립해 화면과 파일 표기가 갈라지지 않게 한다.
"""
from __future__ import annotations

from workflow.coding_rulebook import (
    CODING_RULEBOOK_NOTE,
    build_rulebook,
    classify_rule,
    render_markdown,
)


def _definition(rule="M-1"):
    return {
        "definition": {
            "intent": "포인터 산술을 배열 인덱스로 대체한다",
            "rationale": "경계 검사 누락으로 오버런 위험",
            "avoid_pattern": "p++; *p = v;",
            "comply_pattern": "buf[i] = v;",
            "exceptions": ["DMA 디스크립터 순회"],
            "evidence_basis": "해소 diff 1건",
            "confidence": "medium",
        },
        "ai_enriched": True, "enrich_reason": None, "model": "gemini",
    }


def _item(rule, *, diffs=1, excerpts=0, title=None, latest=12):
    return {
        "rule": rule,
        "description": {"title": title} if title else None,
        "trend_row": {"classification": "persistent", "latest": latest},
        "evidence_diffs": [{"file": "a.c", "text": "diff"} for _ in range(diffs)],
        "unresolved_excerpts": [{"file": "b.c", "text": "code"} for _ in range(excerpts)],
        "counts": {"latest": latest},
    }


# ── 분류 ────────────────────────────────────────────────────────────────────

def test_classify_uses_official_description_first():
    c = classify_rule("M-3-1", {"title": "Required: pointer arithmetic"})
    assert c["category"] == "required" and "규칙 설명" in c["category_basis"]
    c2 = classify_rule("X-9", {"title": "Advisory rule about naming"})
    assert c2["category"] == "advisory"
    c3 = classify_rule("Y-1", {"title": "Mandatory check"})
    assert c3["category"] == "mandatory"


def test_classify_falls_back_to_rule_number_then_project():
    c = classify_rule("MISRA-14.2", None)
    assert c["category"] == "required" and "강제력 미상" in c["category_basis"]
    c2 = classify_rule("PRJ_CUSTOM", None)
    assert c2["category"] == "project" and "공식 분류 표기 없음" in c2["category_basis"]


# ── 조립 ────────────────────────────────────────────────────────────────────

def test_rules_without_evidence_are_excluded_with_reason():
    """증거 0건이면 일반론 초안이 된다 — 문서에 넣지 않고 이유를 남긴다."""
    book = build_rulebook(
        [_item("M-1"), _item("M-2", diffs=0, excerpts=0)],
        generate=lambda **k: _definition(),
    )
    assert book["totals"]["included"] == 1 and book["totals"]["excluded"] == 1
    assert book["excluded"] == [{"rule": "M-2", "reason": "no_code_evidence"}]


def test_generation_failure_is_excluded_not_silent():
    def _fail(**k):
        raise RuntimeError("llm down")

    book = build_rulebook([_item("M-1")], generate=_fail)
    assert book["totals"]["included"] == 0
    assert book["excluded"][0]["reason"] == "generation_error"


def test_definition_none_carries_llm_reason():
    book = build_rulebook(
        [_item("M-1")],
        generate=lambda **k: {"definition": None, "ai_enriched": False,
                              "enrich_reason": "hallucinated_identifiers", "model": "m"},
    )
    assert book["excluded"][0]["reason"] == "hallucinated_identifiers"


def test_sections_ordered_by_enforcement_strength():
    book = build_rulebook(
        [
            _item("A-1", title="Advisory naming"),
            _item("M-1", title="Mandatory bound check"),
            _item("R-1", title="Required init"),
            _item("P-1"),
        ],
        generate=lambda **k: _definition(),
    )
    assert [s["category"] for s in book["sections"]] == ["mandatory", "required", "advisory", "project"]
    assert book["totals"]["included"] == 4 and book["totals"]["ai_enriched"] == 4


def test_max_rules_cap_applied():
    items = [_item(f"R-{i}") for i in range(20)]
    book = build_rulebook(items, generate=lambda **k: _definition(), max_rules=5)
    assert book["totals"]["included"] == 5
    assert book["totals"]["requested"] == 20      # 요청 수는 그대로 — 절단을 숨기지 않는다


# ── Markdown ────────────────────────────────────────────────────────────────

def test_markdown_contains_sections_code_and_exclusions():
    book = build_rulebook(
        [_item("M-1", title="Mandatory bound check"), _item("M-2", diffs=0)],
        generate=lambda **k: _definition(),
    )
    md = render_markdown(book, project="KJPDS02_PV")
    assert md.startswith("# 코딩 룰북 초안 — KJPDS02_PV")
    assert "## 필수(Mandatory)" in md and "### M-1 — Mandatory bound check" in md
    assert "**의도**" in md and "```c" in md and "buf[i] = v;" in md
    assert "**예외**" in md and "DMA 디스크립터 순회" in md
    # 빠진 규칙이 '문제 없음'으로 읽히면 안 된다 — 제외 표를 문서에 남긴다
    assert "## 제외된 규칙" in md and "| M-2 | no_code_evidence |" in md
    assert CODING_RULEBOOK_NOTE.split(".")[0] in md


def test_markdown_shows_classification_basis_and_confidence():
    book = build_rulebook([_item("MISRA-14.2")], generate=lambda **k: _definition())
    md = render_markdown(book)
    assert "분류 근거:" in md and "강제력 미상" in md
    assert "확신도 medium" in md
    assert "증거 diff 1" in md


def test_empty_rulebook_renders_without_error():
    book = build_rulebook([], generate=lambda **k: _definition())
    md = render_markdown(book)
    assert book["sections"] == [] and book["totals"]["included"] == 0
    assert "수록 규칙: **0**건" in md


def test_note_is_server_fixed():
    assert "초안" in CODING_RULEBOOK_NOTE and "사내 코딩 표준이 아니며" in CODING_RULEBOOK_NOTE


def test_markdown_table_cells_escape_pipes():
    """규칙명·사유에 `|`가 섞이면 제외 표가 통째로 깨진다 — 셀 이스케이프."""
    book = build_rulebook([_item("A|B", diffs=0)], generate=lambda **k: _definition())
    md = render_markdown(book)
    assert r"| A\|B | no_code_evidence |" in md
    assert md.count("| --- | --- |") == 1        # 표 구조가 살아 있다
