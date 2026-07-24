"""소스 아키텍처 결정론 메트릭 — fan-in/out·핫스팟·파일 결합도·사이즈 아웃라이어.

요약탭 "아키텍처 인사이트"의 근거 데이터(LLM 0회). parse_c_project(tree-sitter,
preprocess=False — 70파일 <1s)의 함수별 calls를 반전해 fan-in을 만든다
(backend/services/call_tree._invert_call_map과 동일 의미 — workflow→backend 역방향
import 금지 계층 규약이라 로컬 구현).

정직성 규약:
- 복잡도는 VectorCAST ccn 조인(ccn_by_function)이 1순위, 미매칭은 본문 라인수 프록시 —
  complexity_source("vcast_ccn"|"loc_proxy")로 출처를 항상 라벨링한다(측정과 추정 혼동 금지).
- fan 계산은 프로젝트 내 정의 함수 간 호출만(외부/라이브러리 호출은 결합도에 불포함).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# v2: file 경로를 source 기준 상대로(절대경로 비대 — 표기/LLM/필터 어휘 경량화).
ARCH_METRICS_VERSION = 2
EXCERPT_MAX_LINES = 80


def _invert_calls(call_map: Dict[str, List[str]], known: set) -> Dict[str, List[str]]:
    inv: Dict[str, List[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            if callee in known:
                inv.setdefault(callee, []).append(caller)
    return inv


def compute_architecture_metrics(
    source_dir: Path,
    *,
    ccn_by_function: Optional[Dict[str, int]] = None,
    top_n: int = 10,
    excerpt_top: int = 2,
    excerpt_max_lines: int = EXCERPT_MAX_LINES,
    max_files: int = 1200,
) -> Dict[str, Any]:
    """스냅샷 소스 → 아키텍처 메트릭. 파싱 실패는 {"available": False, "reason": …}."""
    from workflow.code_parser.c_parser import parse_c_project

    t0 = time.time()
    try:
        parsed = parse_c_project(str(source_dir), max_files=max_files, preprocess=False)
    except Exception as exc:
        logger.warning("arch metrics parse failed (%s): %s", source_dir, exc)
        return {"available": False, "reason": f"parse_failed: {type(exc).__name__}"}
    functions = parsed.get("functions") or []
    if not functions:
        return {"available": False, "reason": "no_functions_parsed"}

    known = {str(f.get("name") or "") for f in functions if f.get("name")}
    call_map: Dict[str, List[str]] = {}
    file_of: Dict[str, str] = {}
    body_lines: Dict[str, int] = {}
    asil_count = 0
    src_prefix = str(Path(source_dir).resolve()).replace("\\", "/").rstrip("/") + "/"

    def _rel_file(raw: str) -> str:
        # 절대경로를 source 기준 상대로 — 표기/LLM 페이로드/환각 필터 어휘 경량화.
        s = str(raw or "").replace("\\", "/")
        return s[len(src_prefix):] if s.lower().startswith(src_prefix.lower()) else s

    for f in functions:
        name = str(f.get("name") or "")
        if not name:
            continue
        # 프로젝트 내 정의 함수 호출만(중복 제거) — 외부 호출은 결합 지표에서 제외.
        callees = sorted({c for c in (f.get("calls") or []) if c in known and c != name})
        call_map[name] = callees
        file_of[name] = _rel_file(f.get("file"))
        body_lines[name] = len(str(f.get("body") or "").splitlines())
        if str(f.get("comment_asil") or "").strip():
            asil_count += 1
    inv = _invert_calls(call_map, known)

    ccn_map = {str(k): v for k, v in (ccn_by_function or {}).items()}

    def _complexity(name: str) -> Dict[str, Any]:
        if name in ccn_map:
            try:
                return {"complexity": int(ccn_map[name]), "complexity_source": "vcast_ccn"}
            except (TypeError, ValueError):
                pass
        return {"complexity": body_lines.get(name, 0), "complexity_source": "loc_proxy"}

    fan_rows = [
        {"function": n, "file": file_of.get(n, ""), "fan_in": len(inv.get(n) or ()), "fan_out": len(call_map.get(n) or ())}
        for n in known
    ]
    fan_rows.sort(key=lambda r: (-(r["fan_in"] + r["fan_out"]), r["function"]))

    hotspots = []
    for n in known:
        fan_in = len(inv.get(n) or ())
        comp = _complexity(n)
        score = fan_in * max(comp["complexity"], 1)
        if fan_in > 0:
            hotspots.append({"function": n, "file": file_of.get(n, ""), "fan_in": fan_in, **comp, "score": score})
    hotspots.sort(key=lambda r: (-r["score"], r["function"]))
    hotspots = hotspots[:top_n]

    edges = sum(len(v) for v in call_map.values())
    cross_edges = 0
    pair_counts: Dict[tuple, int] = {}
    for caller, callees in call_map.items():
        cf = file_of.get(caller, "")
        for callee in callees:
            tf = file_of.get(callee, "")
            if cf and tf and cf != tf:
                cross_edges += 1
                pair_counts[(cf, tf)] = pair_counts.get((cf, tf), 0) + 1
    top_pairs = [
        {"from_file": a, "to_file": b, "calls": c}
        for (a, b), c in sorted(pair_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    ]

    size_rows = [
        {"function": n, "file": file_of.get(n, ""), "lines": body_lines.get(n, 0)} for n in known
    ]
    size_rows.sort(key=lambda r: (-r["lines"], r["function"]))

    excerpts: List[Dict[str, Any]] = []
    by_name = {str(f.get("name") or ""): f for f in functions}
    for h in hotspots[:excerpt_top]:
        f = by_name.get(h["function"])
        if not f:
            continue
        lines = str(f.get("body") or "").splitlines()
        truncated = len(lines) > excerpt_max_lines
        excerpts.append({
            "function": h["function"], "file": h["file"],
            "text": "\n".join(lines[:excerpt_max_lines]),
            "truncated": truncated,
        })

    return {
        "available": True,
        "version": ARCH_METRICS_VERSION,
        "snapshot": {
            "files": len({v for v in file_of.values() if v}),
            "functions": len(known),
            "parse_ms": int((time.time() - t0) * 1000),
            "parser_engine": parsed.get("parser_engine"),
        },
        "fan": fan_rows[:top_n],
        "hotspots": hotspots,
        "coupling": {
            "edges": edges,
            "cross_edges": cross_edges,
            "cross_file_call_ratio": round(cross_edges / edges, 3) if edges else None,
            "top_pairs": top_pairs,
        },
        "size_outliers": size_rows[:top_n],
        "asil_functions": {"count": asil_count},
        "excerpts": excerpts,
    }
