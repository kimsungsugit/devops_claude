"""함수 단위 시험 케이스 초안 생성(N4) — 결정론 코어 + Gemini enrichment.

계층 규약(rule_fix_example과 동일): 소스 읽기·캐시 같은 IO는 라우터가 하고, 이 모듈은
주어진 함수 컨텍스트(시그니처·파라미터·전역·호출·커버리지·ASIL·ccn) + 본문 발췌 →
케이스 표 계산만 한다.

ISO 정직성:
- **결정론 코어가 항상 산출된다**: 권고 기법, 분기 커버 최소 TC 추정(McCabe), 파라미터에서
  유도한 경계값 후보. LLM이 없거나 실패해도 이 골격은 남는다.
- note는 서버 고정 주입 — "초안이며 심사 판정이 아니고, 요구 기반 시험을 대체하지 않는다".
- 환각 사후 필터: 케이스에 등장한 식별자가 본문·파라미터·전역·호출 함수 집합 밖이면 그
  **케이스만** 폐기한다(전체 폐기는 과하고, 통과분은 유효하다).
- MC/DC는 현 데이터 미측정 — 프롬프트가 '미달' 표현을 금지하고 코어도 그렇게 표기한다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from workflow.summary_ai_insight import _extract_json_payload, resolve_effective_model

logger = logging.getLogger(__name__)

TEST_CASE_DRAFT_PROMPT_VERSION = 1

TEST_CASE_DRAFT_NOTE = (
    "이 표는 커버리지 갭과 소스 본문을 근거로 만든 **시험 케이스 초안**이며 심사 판정이 아닙니다. "
    "요구사항 기반 시험(ISO 26262-6 Table 8 1a)을 대체하지 않으며, 실제 채택 전 요구 추적성과 "
    "기대 결과를 설계자가 확정해야 합니다."
)

# 환각 필터 허용 어휘(rule_fix_example과 동일 계열 + 시험 표현에 흔한 토큰).
_C_COMMON = {
    "if", "else", "for", "while", "do", "switch", "case", "default", "break", "continue",
    "return", "goto", "sizeof", "typedef", "struct", "union", "enum", "static", "const",
    "volatile", "extern", "void", "char", "short", "int", "long", "float", "double",
    "signed", "unsigned", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t",
    "int16_t", "int32_t", "int64_t", "boolean", "bool", "true", "false", "null",
    "u8", "u16", "u32", "s8", "s16", "s32", "define", "include", "pragma", "inline",
    "min", "max", "and", "not", "the", "for", "value", "values", "input", "inputs",
    "expected", "result", "state", "range", "boundary", "normal", "error", "test",
}
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _identifiers(text: str) -> set:
    return {m.group(0).lower() for m in _IDENT_RE.finditer(text or "")}


def _param_boundaries(params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """파라미터 타입에서 경계값 후보를 유도(결정론) — 타입 미상은 후보를 만들지 않는다."""
    out: List[Dict[str, Any]] = []
    for p in params or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        t = str(p.get("type") or p.get("desc") or "").lower()
        cands: List[str] = []
        m = re.search(r"(u?int(8|16|32|64)_t|u(8|16|32)|s(8|16|32))", t)
        if m:
            token = m.group(0)
            bits = int(re.search(r"(8|16|32|64)", token).group(0))  # type: ignore[union-attr]
            if token.startswith(("u", "uint")):
                cands = ["0", "1", str((1 << bits) - 2), str((1 << bits) - 1)]
            else:
                half = 1 << (bits - 1)
                cands = [str(-half), "-1", "0", "1", str(half - 1)]
        elif "bool" in t or "boolean" in t:
            cands = ["FALSE", "TRUE"]
        elif "*" in t or "ptr" in t or "pointer" in t:
            cands = ["NULL", "유효 포인터"]
        if cands:
            out.append({"param": name, "type": p.get("type") or None, "candidates": cands})
    return out


def build_deterministic_draft(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 없이 항상 나오는 골격 — 권고 기법·최소 TC 추정·경계값 후보·측정 상태."""
    from workflow.test_design_advisor import TECHNIQUE_CATALOG, suggested_min_cases

    ccn = ctx.get("ccn")
    gap_kind = str(ctx.get("gap_kind") or "") or None
    techniques = [t for t in (ctx.get("techniques") or []) if t in TECHNIQUE_CATALOG]
    min_cases = suggested_min_cases(ccn, (gap_kind or "").replace("changed_", "") or None)
    return {
        "techniques": [
            {"id": t, "label": TECHNIQUE_CATALOG[t]["label"], "iso_ref": TECHNIQUE_CATALOG[t]["iso_ref"]}
            for t in techniques
        ],
        "suggested_min_cases": min_cases,
        "suggested_min_cases_estimate": True,   # McCabe 근사 — 측정값 아님
        "boundary_candidates": _param_boundaries(ctx.get("params") or []),
        "coverage": {"statement": ctx.get("statement"), "branch": ctx.get("branch"),
                     "mcdc": None, "mcdc_state": "unmeasured"},
        "asil": ctx.get("asil"), "asil_source": ctx.get("asil_source"),
        "globals_used": list(ctx.get("globals") or [])[:20],
        "calls": list(ctx.get("calls") or [])[:20],
    }


def filter_cases(cases: List[Any], allowed: set) -> Dict[str, Any]:
    """케이스별 환각 필터 — 미지 식별자가 과반이면 그 케이스만 폐기."""
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for c in cases:
        if not isinstance(c, dict):
            dropped += 1
            continue
        text = " ".join(str(c.get(k) or "") for k in ("preconditions", "inputs", "expected", "covers"))
        idents = _identifiers(text)
        unknown = {i for i in idents if i not in allowed}
        if idents and len(unknown) > max(2, len(idents) // 2):
            dropped += 1
            continue
        if not str(c.get("expected") or "").strip():
            dropped += 1  # 기대 결과 없는 케이스는 시험이 아니다
            continue
        kept.append({
            "id": str(c.get("id") or f"TC{len(kept) + 1}"),
            "purpose": str(c.get("purpose") or ""),
            "technique": str(c.get("technique") or ""),
            "preconditions": str(c.get("preconditions") or ""),
            "inputs": str(c.get("inputs") or ""),
            "expected": str(c.get("expected") or ""),
            "covers": str(c.get("covers") or ""),
        })
    return {"cases": kept[:8], "dropped": dropped}


def generate_test_case_draft(
    *,
    context: Dict[str, Any],
    source_excerpt: str,
    cfg: Optional[Dict[str, Any]] = None,
    agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """케이스 초안 생성. 반환 {deterministic, cases, notes, ai_enriched, enrich_reason, model}.

    LLM 미설정/실패/전량 폐기여도 deterministic 골격은 항상 반환한다(결정론 코어 규약).
    """
    deterministic = build_deterministic_draft(context)
    if cfg is None:
        try:
            from workflow.impact_ai_guide import _load_impact_oai_config
            cfg = _load_impact_oai_config()
        except Exception:
            logger.warning("test-case-draft LLM config 해석 실패 — 결정론 폴백", exc_info=True)
            cfg = None
    model = resolve_effective_model(cfg)
    base = {"deterministic": deterministic, "cases": [], "notes": [], "dropped_cases": 0,
            "ai_enriched": False, "model": model}
    if not cfg:
        return {**base, "enrich_reason": "llm_unavailable"}
    if not str(source_excerpt or "").strip():
        # 본문이 없으면 인용 검증이 불가능해 어떤 케이스도 신뢰할 수 없다 — 호출 자체를 생략.
        return {**base, "enrich_reason": "no_source_excerpt"}

    try:
        if agent_call is None:
            from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415
        from prompts import load_prompt

        system = load_prompt("summary_test_case_draft")
        payload = json.dumps({
            "function": context.get("function"), "unit": context.get("unit"),
            "signature": context.get("signature"),
            "params": context.get("params"), "globals": context.get("globals"),
            "calls": context.get("calls"),
            "coverage": deterministic["coverage"], "ccn": context.get("ccn"),
            "asil": context.get("asil"), "asil_source": context.get("asil_source"),
            "gap_kind": context.get("gap_kind"),
            "recommended_techniques": deterministic["techniques"],
            "suggested_min_cases": deterministic["suggested_min_cases"],
            "boundary_candidates": deterministic["boundary_candidates"],
        }, ensure_ascii=False) + "\n\n[함수 소스 본문]\n" + str(source_excerpt)
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="summary_test_case_draft")
        parsed = _extract_json_payload(output or "")
        cases = parsed.get("cases") if isinstance(parsed, dict) else parsed
        if not isinstance(cases, list) or not cases:
            return {**base, "enrich_reason": "llm_empty_or_invalid"}
        allowed = (
            _identifiers(source_excerpt)
            | _identifiers(str(context.get("signature") or ""))
            | {str(p.get("name") or "").lower() for p in (context.get("params") or []) if isinstance(p, dict)}
            | {str(g).lower() for g in (context.get("globals") or [])}
            | {str(c).lower() for c in (context.get("calls") or [])}
            | {str(context.get("function") or "").lower()}
            | _C_COMMON
        )
        allowed.discard("")
        filtered = filter_cases(cases, allowed)
        if not filtered["cases"]:
            return {**base, "dropped_cases": filtered["dropped"], "enrich_reason": "all_cases_filtered"}
        notes = [str(n) for n in (parsed.get("notes") or [])[:5]] if isinstance(parsed, dict) else []
        return {
            **base,
            "cases": filtered["cases"], "notes": notes, "dropped_cases": filtered["dropped"],
            "ai_enriched": True, "enrich_reason": None,
        }
    except Exception:
        logger.warning("test-case-draft enrichment 실패 — 결정론 폴백", exc_info=True)
        return {**base, "enrich_reason": "llm_error"}
