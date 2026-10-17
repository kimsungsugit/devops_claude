"""코딩 룰북 조립(Q4) — 규칙별 초안을 카테고리로 묶어 팀 문서 한 벌로 만든다.

지금까지 `rule_definition`은 **규칙 1개씩** on-demand 카드로만 나왔다. 사용자 요구는
"정적분석에 나온 룰 위반에 대해 코드룰을 제안해서 정리"이므로, 여러 규칙을 한 번에 처리해
카테고리별로 묶고 Markdown으로 내보낼 수 있는 **룰북**을 만든다.

계층 규약: 증거 수집(RCR 파싱·스냅샷 diff)은 라우터가 하고, 이 모듈은 규칙별 증거가 담긴
입력을 받아 ①분류 ②규칙별 초안 생성 위임 ③Markdown 조립만 한다.

정직성:
- **증거 0건 규칙은 룰북에 넣지 않는다**(no_code_evidence) — 일반론 룰이 섞이면 문서 전체의
  신뢰가 무너진다. 대신 제외 목록과 사유를 함께 반환해 '왜 빠졌는지'를 남긴다.
- Markdown은 **서버가 조립**한다(클라이언트 문자열 조립 금지 — 표기 규약이 두 곳으로 갈라진다).
- note는 서버 고정 — 초안이지 승인된 사내 표준이 아니다.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

CODING_RULEBOOK_VERSION = 1

CODING_RULEBOOK_NOTE = (
    "이 룰북은 이 프로젝트의 정적분석 위반 관측과 실제 코드 증거로부터 만든 **초안**입니다. "
    "팀 검토·승인 전에는 사내 코딩 표준이 아니며, 규칙 원문(MISRA/QAC)의 정의를 대체하지 않습니다."
)

# 카테고리 분류 — RCFInfo 설명 텍스트와 규칙 번호에서 유추한다. 판정 근거를 category_basis로 남긴다.
_CATEGORY_RULES: List[tuple] = [
    ("mandatory", "필수(Mandatory)", re.compile(r"\bmandatory\b", re.I)),
    ("required", "요구(Required)", re.compile(r"\brequired\b", re.I)),
    ("advisory", "권고(Advisory)", re.compile(r"\badvisory\b", re.I)),
]
CATEGORY_LABEL = {
    "mandatory": "필수(Mandatory)", "required": "요구(Required)",
    "advisory": "권고(Advisory)", "project": "프로젝트 관례",
}
# 표시 순서 — 강제력이 높은 것부터.
CATEGORY_ORDER = ["mandatory", "required", "advisory", "project"]


def classify_rule(rule: str, description: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """규칙 → 카테고리. 근거(어디서 판정했는지)를 함께 돌려준다(추정을 사실로 위장하지 않기)."""
    title = str((description or {}).get("title") or "")
    for key, _label, pat in _CATEGORY_RULES:
        if pat.search(title):
            return {"category": key, "category_basis": f"규칙 설명에 '{pat.pattern}' 표기"}
    if re.match(r"^(MISRA|M)\s*[-_]?\d", str(rule or ""), re.I):
        return {"category": "required", "category_basis": "MISRA 규칙 번호 형식(강제력 미상 — 요구로 가정)"}
    return {"category": "project", "category_basis": "공식 분류 표기 없음 — 프로젝트 관례로 분류"}


def build_rulebook(
    rule_inputs: List[Dict[str, Any]],
    *,
    generate: Optional[Callable[..., Dict[str, Any]]] = None,
    max_rules: int = 15,
) -> Dict[str, Any]:
    """규칙 입력 목록 → 카테고리별 룰북.

    rule_inputs 각 항목: {rule, description, trend_row, evidence_diffs, unresolved_excerpts,
    counts}. 증거(diff·발췌)가 하나도 없으면 생성하지 않고 excluded에 사유와 함께 남긴다.
    generate는 주입 가능(테스트/비용 통제) — 기본은 workflow.rule_definition.
    """
    if generate is None:
        from workflow.rule_definition import generate_rule_definition as generate

    sections: Dict[str, List[Dict[str, Any]]] = {}
    excluded: List[Dict[str, Any]] = []
    ai_used = 0
    for item in (rule_inputs or [])[:max_rules]:
        rule = str(item.get("rule") or "").strip()
        if not rule:
            continue
        diffs = item.get("evidence_diffs") or []
        excerpts = item.get("unresolved_excerpts") or []
        if not diffs and not excerpts:
            # 증거 없는 규칙은 일반론 초안이 된다 — 문서에 넣지 않고 이유를 남긴다.
            excluded.append({"rule": rule, "reason": "no_code_evidence"})
            continue
        try:
            gen = generate(
                rule=rule, description=item.get("description"),
                trend_row=item.get("trend_row") or {},
                evidence_diffs=diffs, unresolved_excerpts=excerpts,
            )
        except Exception:  # noqa: BLE001 — 한 규칙 실패가 룰북 전체를 죽이지 않는다
            logger.warning("rulebook: 규칙 %s 초안 생성 실패", rule, exc_info=True)
            excluded.append({"rule": rule, "reason": "generation_error"})
            continue
        if not gen.get("definition"):
            excluded.append({"rule": rule, "reason": gen.get("enrich_reason") or "no_definition"})
            continue
        if gen.get("ai_enriched"):
            ai_used += 1
        cls = classify_rule(rule, item.get("description"))
        sections.setdefault(cls["category"], []).append({
            "rule": rule,
            "title": (item.get("description") or {}).get("title"),
            "violations": (item.get("counts") or {}).get("latest"),
            "trend": (item.get("trend_row") or {}).get("classification"),
            "evidence_used": {"fix_diffs": len(diffs), "unresolved_excerpts": len(excerpts)},
            **cls,
            **gen["definition"],
        })
    ordered = [
        {"category": c, "label": CATEGORY_LABEL[c], "rules": sections[c]}
        for c in CATEGORY_ORDER if sections.get(c)
    ]
    return {
        "version": CODING_RULEBOOK_VERSION,
        "sections": ordered,
        "excluded": excluded,
        "totals": {
            "requested": len(rule_inputs or []),
            "included": sum(len(s["rules"]) for s in ordered),
            "excluded": len(excluded),
            "ai_enriched": ai_used,
        },
        "note": CODING_RULEBOOK_NOTE,
    }


def _fence(code: str) -> str:
    text = str(code or "").strip()
    return f"```c\n{text}\n```\n" if text else ""


def _cell(value: Any) -> str:
    """Markdown 표 셀 이스케이프 — 규칙명·사유에 `|`가 섞이면 표가 통째로 깨진다."""
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(rulebook: Dict[str, Any], *, project: str = "") -> str:
    """룰북 → Markdown. **서버에서 조립**해 화면과 파일의 표기가 갈라지지 않게 한다."""
    lines: List[str] = [f"# 코딩 룰북 초안{f' — {project}' if project else ''}", ""]
    t = rulebook.get("totals") or {}
    lines += [
        f"> {rulebook.get('note', '')}",
        "",
        f"- 수록 규칙: **{t.get('included', 0)}**건 (요청 {t.get('requested', 0)} · 제외 {t.get('excluded', 0)})",
        f"- AI 초안: {t.get('ai_enriched', 0)}건 · 나머지는 증거만 수록",
        "",
    ]
    for sec in rulebook.get("sections") or []:
        lines += [f"## {sec['label']}", ""]
        for r in sec["rules"]:
            head = f"### {r['rule']}"
            if r.get("title"):
                head += f" — {r['title']}"
            lines += [head, ""]
            if r.get("intent"):
                lines += [f"**의도**: {r['intent']}", ""]
            if r.get("rationale"):
                lines += [f"**근거**: {r['rationale']}", ""]
            if r.get("avoid_pattern"):
                lines += ["**피할 패턴**", "", _fence(r["avoid_pattern"])]
            if r.get("comply_pattern"):
                lines += ["**준수 패턴**", "", _fence(r["comply_pattern"])]
            if r.get("exceptions"):
                lines += ["**예외**", ""] + [f"- {x}" for x in r["exceptions"]] + [""]
            meta = [f"분류 근거: {r.get('category_basis', '—')}"]
            if r.get("violations") is not None:
                meta.append(f"최근 위반 {r['violations']}건")
            if r.get("trend"):
                meta.append(f"트렌드 {r['trend']}")
            ev = r.get("evidence_used") or {}
            meta.append(f"증거 diff {ev.get('fix_diffs', 0)}·발췌 {ev.get('unresolved_excerpts', 0)}")
            meta.append(f"확신도 {r.get('confidence', 'low')}")
            lines += [f"<sub>{' · '.join(meta)}</sub>", ""]
    if rulebook.get("excluded"):
        # 왜 빠졌는지를 문서에 남긴다 — 빠진 규칙이 '문제 없음'으로 읽히면 안 된다.
        lines += ["## 제외된 규칙", "",
                  "| 규칙 | 사유 |", "| --- | --- |"]
        lines += [f"| {_cell(e['rule'])} | {_cell(e['reason'])} |" for e in rulebook["excluded"]]
        lines += [""]
    return "\n".join(lines)
