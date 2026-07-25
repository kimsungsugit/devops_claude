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
# v3: module_graph(디렉터리 프록시 롤업)·cycles(반복 Tarjan SCC — 파일/모듈)·mutual_file_pairs·
#     refactor_candidates·asil_functions.by_function 추가 (K1 — 다이어그램/테스트 어드바이저 재료).
ARCH_METRICS_VERSION = 3
EXCERPT_MAX_LINES = 80

# 모듈 프록시 = 파일 상대경로의 앞 2세그먼트(예: "Sources/IF") — 최상위 1세그먼트는 실측상
# 거의 전부 "Sources"로 뭉쳐 무의미하고, 전체 dirname은 노드가 과다해진다. 루트 파일은 "(root)".
_MODULE_DEPTH = 2


def _invert_calls(call_map: Dict[str, List[str]], known: set) -> Dict[str, List[str]]:
    inv: Dict[str, List[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            if callee in known:
                inv.setdefault(callee, []).append(caller)
    return inv


def _module_of(rel_file: str) -> str:
    parts = [p for p in str(rel_file or "").replace("\\", "/").split("/") if p]
    if len(parts) <= 1:
        return "(root)"
    return "/".join(parts[:-1][:_MODULE_DEPTH])


def _tarjan_scc(adj: Dict[str, List[str]]) -> List[List[str]]:
    """반복(iterative) Tarjan SCC — 재귀한도 회피. size>=2 컴포넌트만(자기호출 제외).

    입력 adj의 키 집합이 노드 전체이며, adj 값의 미지 노드는 무시한다. 출력은 결정론
    (컴포넌트 내부 정렬 + 크기 내림차순)이라 캐시/테스트가 안정적이다.
    """
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: set = set()
    stack: List[str] = []
    sccs: List[List[str]] = []
    counter = 0
    for root in sorted(adj):
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work: List[tuple] = [(root, iter(sorted(adj.get(root) or ())))]
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in adj:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(adj.get(nxt) or ()))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp: List[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) >= 2:
                    sccs.append(sorted(comp))
    sccs.sort(key=lambda c: (-len(c), c[0]))
    return sccs


def _mutual_file_pairs(pair_counts: Dict[tuple, int]) -> List[Dict[str, Any]]:
    """양방향 호출이 관측된 파일 쌍 — 상호 의존(2-사이클)의 결정론 목록."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for (a, b) in pair_counts:
        if (a, b) in seen or (b, a) not in pair_counts:
            continue
        seen.add((a, b))
        seen.add((b, a))
        first, second = sorted((a, b))
        out.append({
            "a": first, "b": second,
            "a_to_b": pair_counts.get((first, second), 0),
            "b_to_a": pair_counts.get((second, first), 0),
        })
    out.sort(key=lambda p: (-(p["a_to_b"] + p["b_to_a"]), p["a"]))
    return out


def _build_module_graph(
    call_map: Dict[str, List[str]], file_of: Dict[str, str],
    *, max_nodes: int = 40, max_edges: int = 200,
) -> Dict[str, Any]:
    """모듈(디렉터리 프록시) 롤업 그래프 — 다이어그램 렌더 재료. 캡 절단은 truncated로 정직 표기."""
    node_files: Dict[str, set] = {}
    node_functions: Dict[str, int] = {}
    for fn, rel in file_of.items():
        m = _module_of(rel)
        node_files.setdefault(m, set())
        if rel:
            node_files[m].add(rel)
        node_functions[m] = node_functions.get(m, 0) + 1
    edge_counts: Dict[tuple, int] = {}
    for caller, callees in call_map.items():
        cm = _module_of(file_of.get(caller, ""))
        for callee in callees:
            tm = _module_of(file_of.get(callee, ""))
            if cm != tm:
                edge_counts[(cm, tm)] = edge_counts.get((cm, tm), 0) + 1
    all_modules = sorted(node_files, key=lambda m: (-node_functions.get(m, 0), m))
    kept = set(all_modules[:max_nodes])
    edges_sorted = sorted(edge_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kept_edges = [(pair, c) for pair, c in edges_sorted if pair[0] in kept and pair[1] in kept]
    truncated = len(all_modules) > max_nodes or len(kept_edges) > max_edges
    kept_edges = kept_edges[:max_edges]
    return {
        "nodes": [
            {"module": m, "files": len(node_files[m]), "functions": node_functions.get(m, 0)}
            for m in all_modules[:max_nodes]
        ],
        "edges": [{"from": a, "to": b, "calls": c} for (a, b), c in kept_edges],
        "truncated": truncated,
    }


def _refactor_candidates(
    file_of: Dict[str, str], body_lines: Dict[str, int],
    pair_counts: Dict[tuple, int], mutual_pairs: List[Dict[str, Any]], *, top_n: int = 8,
) -> List[Dict[str, Any]]:
    """결정론 개선 후보 — god_file(함수/본문 집중 + 다파일 유입·유출)·mutual_dependency.

    임계 미달이면 빈 목록(모든 파일을 후보로 라벨링하지 않는다 — 허위 신호 방지).
    basis는 항상 실측 수치 문자열.
    """
    per_file_fn: Dict[str, int] = {}
    per_file_lines: Dict[str, int] = {}
    for fn, rel in file_of.items():
        if not rel:
            continue
        per_file_fn[rel] = per_file_fn.get(rel, 0) + 1
        per_file_lines[rel] = per_file_lines.get(rel, 0) + body_lines.get(fn, 0)
    in_files: Dict[str, set] = {}
    out_files: Dict[str, set] = {}
    for (a, b) in pair_counts:
        out_files.setdefault(a, set()).add(b)
        in_files.setdefault(b, set()).add(a)
    out: List[Dict[str, Any]] = []
    god_rank = sorted(
        per_file_fn,
        key=lambda f: (-(per_file_fn[f] * 2 + per_file_lines.get(f, 0) // 100
                         + len(in_files.get(f) or ()) + len(out_files.get(f) or ())), f),
    )
    for f in god_rank:
        fn_cnt = per_file_fn[f]
        lines = per_file_lines.get(f, 0)
        n_in = len(in_files.get(f) or ())
        n_out = len(out_files.get(f) or ())
        # 임계: 함수 15+ 또는 본문 800줄+ 이면서 3개 파일 이상과 결합 — 집중+결합 동시 관측만.
        if (fn_cnt >= 15 or lines >= 800) and (n_in + n_out) >= 3:
            out.append({
                "kind": "god_file", "file": f,
                "functions": fn_cnt, "lines": lines, "in_files": n_in, "out_files": n_out,
                "basis": f"함수 {fn_cnt}개 · 본문 {lines:,}줄 · 유입 {n_in}파일 · 유출 {n_out}파일",
            })
        if len(out) >= top_n:
            break
    for p in mutual_pairs[: max(0, top_n - len(out))]:
        out.append({
            "kind": "mutual_dependency", "files": [p["a"], p["b"]],
            "basis": f"{p['a']}→{p['b']} {p['a_to_b']}회 · {p['b']}→{p['a']} {p['b_to_a']}회 상호 호출",
        })
    return out[:top_n]


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
    asil_by_function: Dict[str, str] = {}
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
        asil = str(f.get("comment_asil") or "").strip()
        if asil:
            # 소집합(주석 보유 함수만) — L2 테스트 어드바이저가 함수→ASIL 조인에 재사용.
            asil_by_function[name] = asil.upper()
    inv = _invert_calls(call_map, known)

    ccn_map = {str(k): v for k, v in (ccn_by_function or {}).items()}

    def _complexity(name: str) -> Dict[str, Any]:
        if name in ccn_map:
            try:
                return {"complexity": int(ccn_map[name]), "complexity_source": "vcast_ccn"}
            except (TypeError, ValueError):
                pass
        return {"complexity": body_lines.get(name, 0), "complexity_source": "loc_proxy"}

    def _score_complexity(comp: Dict[str, Any]) -> int:
        # 점수 입력은 척도를 맞춘다 — vcast_ccn(≈1~30)과 loc_proxy(본문 줄수, 수백)를 그대로
        # 곱하면 미측정 함수가 순위를 독식한다(실측 HDPDM01: ccn 조인 78%인데 top10 전원
        # loc_proxy). 표시 complexity는 원값+출처 라벨 그대로, 점수만 줄수//10 근사(v3).
        if comp["complexity_source"] == "vcast_ccn":
            return max(int(comp["complexity"]), 1)
        return max(int(comp["complexity"]) // 10, 1)

    fan_rows = [
        {"function": n, "file": file_of.get(n, ""), "fan_in": len(inv.get(n) or ()), "fan_out": len(call_map.get(n) or ())}
        for n in known
    ]
    fan_rows.sort(key=lambda r: (-(r["fan_in"] + r["fan_out"]), r["function"]))

    hotspots = []
    for n in known:
        fan_in = len(inv.get(n) or ())
        comp = _complexity(n)
        score = fan_in * _score_complexity(comp)
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

    # ── v3: 파일/모듈 그래프·SCC 사이클·상호 의존·개선 후보 (호출 관계 기반 — include 미분석) ──
    file_adj: Dict[str, List[str]] = {f: [] for f in {v for v in file_of.values() if v}}
    mod_adj: Dict[str, List[str]] = {_module_of(f): [] for f in file_adj}
    for (a, b) in pair_counts:
        file_adj.setdefault(a, []).append(b)
        ma, mb = _module_of(a), _module_of(b)
        mod_adj.setdefault(ma, [])
        mod_adj.setdefault(mb, [])
        if ma != mb:
            mod_adj[ma].append(mb)
    file_sccs = _tarjan_scc(file_adj)
    module_sccs = _tarjan_scc(mod_adj)
    mutual_pairs = _mutual_file_pairs(pair_counts)
    module_graph = _build_module_graph(call_map, file_of)
    refactor_candidates = _refactor_candidates(file_of, body_lines, pair_counts, mutual_pairs)

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
        "asil_functions": {"count": len(asil_by_function), "by_function": asil_by_function},
        "excerpts": excerpts,
        "module_graph": module_graph,
        "cycles": {
            # 0건이면 빈 배열(키 자체는 항상 존재 — 프론트가 '관측 없음'을 명시 렌더).
            "file_sccs": [{"files": c, "size": len(c)} for c in file_sccs[:10]],
            "module_sccs": [{"modules": c, "size": len(c)} for c in module_sccs[:10]],
            "mutual_file_pairs": mutual_pairs[:10],
        },
        "refactor_candidates": refactor_candidates,
    }
