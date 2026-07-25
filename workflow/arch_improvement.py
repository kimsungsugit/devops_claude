"""아키텍처 개선(To-Be) 제안 — 결정론 후보 + Gemini 목표 구조(Q3).

지금까지 아키텍처 축은 **진단만** 했다("결합 26.9% · 순환 4건"). 여기서 한 걸음 더 나가
*어떻게 바꿀지*를 낸다. 두 층으로 나눈다:

1. **결정론 후보**(LLM 무관, 항상 산출) — 측정치에서 규칙으로 도출한다. 각 후보는 `basis`에
   실측 수치를 인용하고, 임계 미달이면 아예 만들지 않는다(모든 파일을 후보로 라벨링 금지).
   - 구조: `break_cycle`(SCC 안에서 **끊는 비용이 가장 싼 간선**) · `split_god_file` ·
     `layer_violation`(하위→상위 호출을 콜백/이벤트로 뒤집기)
   - **테스트 용이성**(사용자 요구): `inject_global`(전역 참조 다수 → 파라미터 주입) ·
     `seam_for_pointer`(함수포인터 → 스텁 시임) · `extract_pure`(고복잡×저커버 → 순수 함수 추출)
2. **AI 목표 구조** — 위 후보와 실제 심볼만 근거로 모듈 노드/엣지를 제안한다. 후보가 0이면
   **LLM을 호출하지 않는다**(근거 없는 그림은 그럴듯한 허구일 뿐).

정직성: note는 서버 고정(제안≠검증된 설계), 환각 필터는 입력 심볼(모듈·파일·함수) 밖이면 폐기,
계층 후보는 상위 계층 축(휴리스틱)의 한계를 문구로 승계한다.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from workflow.summary_ai_insight import _extract_json_payload, resolve_effective_model

logger = logging.getLogger(__name__)

ARCH_IMPROVEMENT_PROMPT_VERSION = 1

ARCH_IMPROVEMENT_NOTE = (
    "아래 후보와 목표 구조는 **측정치에서 도출한 제안**이며 검증된 설계가 아닙니다. "
    "채택 전 설계자가 요구사항·안전 목표·기존 인터페이스 계약을 검토해야 하며, "
    "계층 관련 항목은 함수명 휴리스틱에 기반해 오탐을 포함할 수 있습니다."
)

# 후보 종류별 표시 순서(위험/실행 용이성 절충). 값이 작을수록 먼저 보여준다.
_KIND_RANK = {
    "break_cycle": 0, "layer_violation": 1, "split_god_file": 2,
    "extract_pure": 3, "inject_global": 4, "seam_for_pointer": 5,
}
KIND_LABEL = {
    "break_cycle": "순환 끊기",
    "layer_violation": "계층 역방향 정리",
    "split_god_file": "집중 파일 분할",
    "extract_pure": "순수 함수 추출(테스트 용이성)",
    "inject_global": "전역 → 파라미터 주입(테스트 격리)",
    "seam_for_pointer": "함수포인터 시임 명시(스텁 지점)",
}
TESTABILITY_KINDS = {"extract_pure", "inject_global", "seam_for_pointer"}


def _cheapest_edge(files: List[str], edges: Dict[tuple, int]) -> Optional[Dict[str, Any]]:
    """SCC 안에서 호출 수가 가장 적은 간선 — 끊는 비용이 가장 싼 지점."""
    inside = set(files)
    cands = [
        {"from": a, "to": b, "calls": c}
        for (a, b), c in edges.items()
        if a in inside and b in inside and a != b
    ]
    if not cands:
        return None
    cands.sort(key=lambda e: (e["calls"], e["from"], e["to"]))
    return cands[0]


# 종류별 상한(아래 각 블록의 슬라이스와 일치). 전체 상한을 이 합보다 작게 잡으면 **정렬 순서상
# 뒤에 오는 테스트 용이성 후보가 통째로 잘려나간다** — 실측에서 testability가 0이 되던 결함이라
# 전체 상한은 종류별 상한의 합으로 둔다(절단은 반드시 omitted로 표기).
PER_KIND_CAP = {"break_cycle": 4, "layer_violation": 4, "split_god_file": 4,
                "extract_pure": 3, "inject_global": 3, "seam_for_pointer": 2}
DEFAULT_TOP_N = sum(PER_KIND_CAP.values())


def build_candidates(arch: Dict[str, Any], *, top_n: int = DEFAULT_TOP_N) -> List[Dict[str, Any]]:
    """아키텍처 메트릭 → 개선 후보(결정론). 근거 없는 항목은 만들지 않는다."""
    out: List[Dict[str, Any]] = []
    edges = {
        (e.get("from"), e.get("to")): int(e.get("calls") or 0)
        for e in ((arch.get("file_graph") or {}).get("edges") or [])
        if e.get("from") and e.get("to")
    }

    # ① 순환 끊기 — SCC별로 가장 싼 간선 1개.
    for scc in ((arch.get("cycles") or {}).get("file_sccs") or [])[:4]:
        files = [str(f) for f in (scc.get("files") or [])]
        cheap = _cheapest_edge(files, edges)
        if not cheap:
            continue
        out.append({
            "kind": "break_cycle", "files": files,
            "target": f"{cheap['from']} → {cheap['to']}",
            "action": "이 호출을 인터페이스(콜백/이벤트)로 뒤집어 순환을 끊는다",
            "basis": f"순환 {len(files)}파일 중 최소 비용 간선 — 호출 {cheap['calls']}회",
            "effort": "low" if cheap["calls"] <= 3 else "medium",
        })

    # ② 계층 역방향 — 하위가 상위를 직접 부르는 지점.
    lay = arch.get("layer_graph") or {}
    if lay.get("available"):
        for p in (lay.get("reverse_pairs") or [])[:4]:
            out.append({
                "kind": "layer_violation",
                "functions": [p.get("caller"), p.get("callee")],
                "files": [f for f in (p.get("caller_file"), p.get("callee_file")) if f],
                "target": f"{p.get('caller')} → {p.get('callee')}",
                "action": "하위 계층이 상위를 직접 부르지 않도록 콜백 등록/이벤트로 역전한다",
                "basis": f"{p.get('caller_layer')} → {p.get('callee_layer')} 역방향 호출"
                         f"(전체 {lay.get('reverse_total')}건) · 계층은 함수명 추정값",
                "effort": "medium",
            })

    # ③ 집중 파일 분할 — 기존 결정론 후보 승계.
    for c in (arch.get("refactor_candidates") or []):
        if c.get("kind") != "god_file":
            continue
        out.append({
            "kind": "split_god_file", "files": [c.get("file")], "target": c.get("file"),
            "action": "호출 이웃이 몰린 축을 기준으로 파일을 분할해 유입/유출 면을 줄인다",
            "basis": c.get("basis"), "effort": "high",
        })

    # ④ 순수 함수 추출 — 고복잡×저커버(테스트 투자 우선순위 1순위와 동일 축).
    cc = arch.get("coverage_complexity") or {}
    if cc.get("available"):
        for p in (cc.get("priority") or [])[:3]:
            out.append({
                "kind": "extract_pure", "functions": [p.get("function")],
                "files": [p.get("file")] if p.get("file") else [],
                "target": p.get("function"),
                "action": "분기 로직을 부수효과 없는 순수 함수로 떼어내 단위 시험 케이스를 붙인다",
                "basis": f"구문 {round(float(p.get('statement') or 0) * 100)}% · "
                         f"복잡도 {p.get('complexity')}"
                         f"{'' if p.get('complexity_source') == 'vcast_ccn' else '(추정)'}",
                "effort": "medium",
            })

    # ⑤ 전역 → 주입 — 모듈 경계를 넘는 공유 전역이 테스트 격리를 막는다.
    gc = arch.get("global_coupling") or {}
    if gc.get("available"):
        for g in (gc.get("top") or [])[:3]:
            if (g.get("modules") or 0) < 2:
                continue  # 한 모듈 안의 전역은 격리 부담이 작다 — 후보로 만들지 않는다
            out.append({
                "kind": "inject_global", "globals": [g.get("global")],
                "functions": list(g.get("functions_sample") or [])[:5],
                "target": g.get("global"),
                "action": "전역 직접 참조 대신 파라미터/컨텍스트로 주입해 테스트에서 상태를 고정한다",
                "basis": f"{g.get('modules')}개 모듈 · {g.get('functions')}개 함수가 참조"
                         f"(읽기/쓰기 미구분)",
                "effort": "high",
            })

    # ⑥ 함수포인터 시임 — 콜그래프에 안 잡히는 간접 호출은 스텁 지점이기도 하다.
    ind = arch.get("indirect_calls") or {}
    for t in (ind.get("top") or [])[:2]:
        out.append({
            "kind": "seam_for_pointer", "functions": [t.get("function")],
            "files": [t.get("file")] if t.get("file") else [],
            "target": t.get("function"),
            "action": "간접 호출 지점을 명시적 시임(등록 API)으로 노출해 테스트에서 스텁을 끼운다",
            "basis": f"함수포인터 참조 {t.get('func_refs')} · 간접 호출 {t.get('pointer_calls')}"
                     f" — 콜그래프 엣지 미반영",
            "effort": "medium",
        })

    out.sort(key=lambda c: (_KIND_RANK.get(c["kind"], 9), str(c.get("target") or "")))
    if len(out) > top_n:
        # 단순 절단은 정렬 뒤쪽(테스트 용이성)을 통째로 날린다 — 종류별로 최소 1건은 남긴다.
        kept: List[Dict[str, Any]] = []
        seen_kinds: set = set()
        for c in out:
            if c["kind"] not in seen_kinds:
                kept.append(c)
                seen_kinds.add(c["kind"])
        for c in out:
            if len(kept) >= top_n:
                break
            if c not in kept:
                kept.append(c)
        kept.sort(key=lambda c: (_KIND_RANK.get(c["kind"], 9), str(c.get("target") or "")))
        return kept[:top_n]
    return out


def summarize(candidates: List[Dict[str, Any]], *, omitted: int = 0) -> Dict[str, Any]:
    """후보 집계 — 구조/테스트 용이성 축 분리(둘은 목적이 다르다)."""
    by_kind: Dict[str, int] = {}
    for c in candidates:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    testability = sum(v for k, v in by_kind.items() if k in TESTABILITY_KINDS)
    return {
        "total": len(candidates),
        "by_kind": by_kind,
        "structural": len(candidates) - testability,
        "testability": testability,
        "omitted": omitted,   # 표시 상한으로 잘린 수 — 0이 아니면 프론트가 명시한다(침묵 절단 금지)
    }


def _known_symbols(arch: Dict[str, Any], candidates: List[Dict[str, Any]]) -> set:
    """환각 필터 어휘 — 메트릭·후보에 실제로 등장한 모듈/파일/함수/전역만."""
    out: set = set()
    for n in ((arch.get("module_graph") or {}).get("nodes") or []):
        out.add(str(n.get("module") or ""))
    for n in ((arch.get("file_graph") or {}).get("nodes") or []):
        out.add(str(n.get("file") or ""))
        out.add(str(n.get("module") or ""))
    for c in candidates:
        for key in ("files", "functions", "globals"):
            out.update(str(v) for v in (c.get(key) or []))
        if c.get("target"):
            out.add(str(c["target"]))
    out.discard("")
    return out


def generate_target_design(
    *,
    arch: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]] = None,
    agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """AI 목표 구조(To-Be). 후보가 없으면 호출하지 않는다(근거 없는 그림 금지)."""
    model = resolve_effective_model(cfg) if cfg is not None else None
    base = {"target_design": None, "ai_enriched": False, "model": model}
    if not candidates:
        return {**base, "enrich_reason": "no_candidates"}
    if cfg is None:
        try:
            from workflow.impact_ai_guide import _load_impact_oai_config
            cfg = _load_impact_oai_config()
        except Exception:
            logger.warning("arch-improvement LLM config 해석 실패 — 결정론 폴백", exc_info=True)
            cfg = None
        model = resolve_effective_model(cfg)
        base["model"] = model
    if not cfg:
        return {**base, "enrich_reason": "llm_unavailable"}

    try:
        if agent_call is None:
            from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415
        from prompts import load_prompt

        system = load_prompt("summary_arch_improvement")
        payload = json.dumps({
            "current_modules": (arch.get("module_graph") or {}).get("nodes"),
            "current_edges": ((arch.get("module_graph") or {}).get("edges") or [])[:20],
            "cycles": (arch.get("cycles") or {}).get("file_sccs"),
            "layer": {k: (arch.get("layer_graph") or {}).get(k)
                      for k in ("nodes", "edges", "reverse_total")},
            "coupling": {k: (arch.get("coupling") or {}).get(k) for k in ("cross_file_call_ratio", "top_pairs")},
            "candidates": candidates,
        }, ensure_ascii=False)
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="summary_arch_improvement")
        parsed = _extract_json_payload(output or "")
        if not isinstance(parsed, dict):
            return {**base, "enrich_reason": "llm_empty_or_invalid"}
        known = _known_symbols(arch, candidates)
        nodes, dropped = [], 0
        for n in (parsed.get("nodes") or []):
            if not isinstance(n, dict) or not n.get("module"):
                dropped += 1
                continue
            members = [m for m in (n.get("members") or []) if str(m) in known]
            if (n.get("members") or []) and not members:
                dropped += 1      # 구성원이 전부 미지 심볼 — 지어낸 모듈
                continue
            nodes.append({
                "module": str(n["module"]), "members": members[:8],
                "role": str(n.get("role") or ""), "is_new": bool(n.get("is_new")),
            })
        names = {n["module"] for n in nodes}
        edges = [
            {"from": str(e.get("from")), "to": str(e.get("to")), "why": str(e.get("why") or "")}
            for e in (parsed.get("edges") or [])
            if isinstance(e, dict) and str(e.get("from")) in names and str(e.get("to")) in names
        ]
        if not nodes:
            return {**base, "enrich_reason": "all_nodes_filtered", "dropped_nodes": dropped}
        return {
            **base,
            "target_design": {
                "nodes": nodes, "edges": edges,
                "rationale": [str(r) for r in (parsed.get("rationale") or [])[:5]],
                "dropped_nodes": dropped,
            },
            "ai_enriched": True, "enrich_reason": None,
        }
    except Exception:
        logger.warning("arch-improvement enrichment 실패 — 결정론 폴백", exc_info=True)
        return {**base, "enrich_reason": "llm_error"}
