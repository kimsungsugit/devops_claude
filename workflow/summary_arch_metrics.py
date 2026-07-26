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
# v4(N5): asil_interference(간섭 자유 후보)·global_coupling(전역 공유)·coverage_complexity
#     (사분면)·indirect_calls/encapsulation(콜그래프 완전성·캡슐화).
# v5(O3): file_graph — 모듈 다이어그램의 파일 단위 드릴다운 재료. pair_counts를 top 10만 노출하고
#     버리던 것을 캡 안에서 전부 싣는다(실측 62파일·308엣지).
# v6(Q2): layer_graph(APP/BSW/LIB/BOOT + 역방향 검토후보) · file_graph.topo_order(DSM 정렬) ·
#     global_coupling.top[].functions_sample(전역↔함수 이분 그래프 재료).
ARCH_METRICS_VERSION = 6

# file_graph 캡 — 실측(62/308)은 무손실. 초과 시 truncated:true로 정직 표기(_build_module_graph 규약).
FILE_GRAPH_MAX_NODES = 400
FILE_GRAPH_MAX_EDGES = 800
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


def _build_file_graph(
    file_of: Dict[str, str], body_lines: Dict[str, int], pair_counts: Dict[tuple, int],
    *, max_nodes: int = FILE_GRAPH_MAX_NODES, max_edges: int = FILE_GRAPH_MAX_EDGES,
) -> Dict[str, Any]:
    """파일 단위 호출 그래프 — 모듈 노드를 클릭했을 때 그 안을 펼치기 위한 재료(v5).

    모듈 그래프는 디렉터리 앞 2세그먼트 프록시라 파일 수십 개가 한 덩어리로 접힌다. 여기서
    파일별 함수 수·본문 줄수와 파일 간 호출 엣지를 그대로 실어, 프론트가 모듈 → 파일로
    한 단계 더 내려갈 수 있게 한다. 캡을 넘으면 truncated:true(침묵 절단 금지).

    노드 선정은 **함수 수 내림차순**이고, 엣지는 **양 끝이 살아남은 노드일 때만** 싣는다 —
    잘려나간 노드를 가리키는 엣지를 남기면 프론트가 존재하지 않는 파일을 그린다.
    """
    per_file_fn: Dict[str, int] = {}
    per_file_lines: Dict[str, int] = {}
    for fn, rel in file_of.items():
        if not rel:
            continue
        per_file_fn[rel] = per_file_fn.get(rel, 0) + 1
        per_file_lines[rel] = per_file_lines.get(rel, 0) + body_lines.get(fn, 0)
    ranked = sorted(per_file_fn, key=lambda f: (-per_file_fn[f], f))
    kept = set(ranked[:max_nodes])
    edges_sorted = sorted(pair_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kept_edges = [(pair, c) for pair, c in edges_sorted if pair[0] in kept and pair[1] in kept]
    truncated = len(ranked) > max_nodes or len(kept_edges) > max_edges
    return {
        "nodes": [
            {"file": f, "module": _module_of(f), "functions": per_file_fn[f],
             "lines": per_file_lines.get(f, 0)}
            for f in ranked[:max_nodes]
        ],
        "edges": [{"from": a, "to": b, "calls": c} for (a, b), c in kept_edges[:max_edges]],
        "truncated": truncated,
        "total_files": len(ranked),
        "total_edges": len(pair_counts),
        # v6: DSM(의존 구조 매트릭스) 정렬 순서. 이 순서로 행·열을 놓으면 **상삼각에 남는 셀이
        # 곧 순환**이라 눈으로 사이클을 짚을 수 있다(히트맵을 함수 수 순으로 놓으면 안 보인다).
        "topo_order": _topo_order(list(kept), pair_counts),
    }


def _topo_order(files: List[str], pair_counts: Dict[tuple, int]) -> List[str]:
    """SCC 응축 후 위상정렬 — DSM 행/열 순서. 순환은 한 덩어리로 묶여 내부 순서만 임의가 된다.

    출력은 결정론(같은 입력 → 같은 순서)이라 캐시·테스트가 안정적이다. 그래프에 없는 파일도
    반드시 포함한다(고립 노드를 떨구면 DSM에서 파일이 사라진다).
    """
    node_set = set(files)
    adj: Dict[str, List[str]] = {f: [] for f in node_set}
    for (a, b) in pair_counts:
        if a in node_set and b in node_set and a != b:
            adj[a].append(b)
    # SCC를 하나의 super-node로 응축 — 순환이 있어도 위상정렬이 성립한다.
    comp_of: Dict[str, int] = {}
    for i, comp in enumerate(_tarjan_scc(adj)):
        for f in comp:
            comp_of[f] = i
    # SCC에 안 들어간 노드(자기 자신만인 컴포넌트)에 새 id를 이어 붙인다.
    next_id = (max(comp_of.values()) + 1) if comp_of else 0
    for f in sorted(node_set):
        if f not in comp_of:
            comp_of[f] = next_id
            next_id += 1
    members: Dict[int, List[str]] = {}
    for f, c in comp_of.items():
        members.setdefault(c, []).append(f)
    cadj: Dict[int, set] = {c: set() for c in members}
    indeg: Dict[int, int] = {c: 0 for c in members}
    for (a, b) in pair_counts:
        if a not in comp_of or b not in comp_of:
            continue
        ca, cb = comp_of[a], comp_of[b]
        if ca != cb and cb not in cadj[ca]:
            cadj[ca].add(cb)
            indeg[cb] += 1
    # Kahn — 같은 진입차수면 컴포넌트 대표 이름 순(결정론).
    ready = sorted((c for c, d in indeg.items() if d == 0), key=lambda c: sorted(members[c])[0])
    order: List[str] = []
    while ready:
        c = ready.pop(0)
        order.extend(sorted(members[c]))
        for nxt in sorted(cadj[c], key=lambda x: sorted(members[x])[0]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda x: sorted(members[x])[0])
    if len(order) < len(node_set):   # 방어: 응축이 완전하면 도달 불가(남으면 정직하게 뒤에 붙인다)
        order.extend(sorted(node_set - set(order)))
    return order


# 계층 서열 — 위(상위)에서 아래(하위)로 호출하는 것이 정방향. 값이 클수록 상위.
# TEST_ARTIFACT는 추적 대상 함수가 아니라 서열 밖(-1)이며 계층 그래프에서 제외한다.
LAYER_ORDER = {"APP_LEAF": 3, "BSW_DRIVER": 2, "LIB_UTIL": 1, "BOOT_REPROG": 0}
LAYER_LABEL = {
    "APP_LEAF": "APP (응용)", "BSW_DRIVER": "BSW (드라이버)",
    "LIB_UTIL": "LIB (유틸)", "BOOT_REPROG": "BOOT (부트/리프로그)",
}
LAYER_NOTE = (
    "계층은 **함수명 휴리스틱**으로 추정한 값이며 선언된 아키텍처가 아니다 — 역방향 호출은 "
    "'위반'이 아니라 계층화 검토 후보다. 각 항목의 함수 쌍을 열어 설계자가 직접 판정할 것."
)


def _build_layer_graph(
    call_map: Dict[str, List[str]], file_of: Dict[str, str], *, max_pairs: int = 30,
) -> Dict[str, Any]:
    """APP/BSW/LIB/BOOT 계층 그래프 + 하위→상위 역방향 호출(검토 후보).

    분류는 `report_gen.requirements._classify_unmapped_layer`(ISO 26262 SwDS 계층 규칙)를
    재사용한다 — 같은 규칙을 두 곳에 복제하면 한쪽만 고쳐지는 표류가 생긴다. workflow →
    report_gen 방향 import는 기존 선례가 있다(impact_orchestrator.py).
    """
    try:
        from report_gen.requirements import _classify_unmapped_layer
    except Exception as exc:  # 분류 규칙 미가용 — 계층 축만 비활성(다른 메트릭은 영향 없음)
        logger.debug("layer classifier unavailable: %s", exc)
        return {"available": False, "reason": "layer_classifier_unavailable"}

    layer_of: Dict[str, str] = {}
    unclassifiable = 0
    for name in call_map:
        try:
            layer_of[name] = _classify_unmapped_layer([name.lower()])
        except Exception:  # silent-ok: 개별 함수 분류 실패는 그 함수만 제외 — 아래 unclassifiable로 계수해 표면화
            unclassifiable += 1
    counts: Dict[str, int] = {}
    for lay in layer_of.values():
        counts[lay] = counts.get(lay, 0) + 1
    if not any(k in LAYER_ORDER for k in counts):
        return {"available": False, "reason": "no_layer_resolved"}

    edges: Dict[tuple, int] = {}
    reverse_pairs: List[Dict[str, Any]] = []
    for caller, callees in call_map.items():
        a = layer_of.get(caller)
        if a not in LAYER_ORDER:
            continue
        for callee in callees:
            b = layer_of.get(callee)
            if b not in LAYER_ORDER or a == b:
                continue
            edges[(a, b)] = edges.get((a, b), 0) + 1
            if LAYER_ORDER[a] < LAYER_ORDER[b]:
                # 하위가 상위를 호출 — 계층화 원칙상 검토 대상(콜백/이벤트로 뒤집을 후보).
                reverse_pairs.append({
                    "caller": caller, "caller_layer": a, "caller_file": file_of.get(caller, ""),
                    "callee": callee, "callee_layer": b, "callee_file": file_of.get(callee, ""),
                })
    reverse_pairs.sort(key=lambda r: (r["caller_layer"], r["caller"], r["callee"]))
    rev_by_edge: Dict[tuple, int] = {}
    for r in reverse_pairs:
        key = (r["caller_layer"], r["callee_layer"])
        rev_by_edge[key] = rev_by_edge.get(key, 0) + 1
    return {
        "available": True,
        "reason": None,
        "nodes": [
            {"layer": k, "label": LAYER_LABEL[k], "rank": LAYER_ORDER[k], "functions": counts.get(k, 0)}
            for k in sorted(LAYER_ORDER, key=lambda x: -LAYER_ORDER[x])
            if counts.get(k, 0) > 0
        ],
        "edges": [
            {"from": a, "to": b, "calls": c, "reverse": LAYER_ORDER[a] < LAYER_ORDER[b]}
            for (a, b), c in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "reverse_total": len(reverse_pairs),
        "reverse_pairs": reverse_pairs[:max_pairs],
        "reverse_pairs_omitted": max(0, len(reverse_pairs) - max_pairs),
        # 계층 그래프에서 빠진 함수를 침묵시키지 않는다: 시험 산출물로 분류된 수 + 분류 자체가
        # 실패한 수를 각각 표기(합계가 곧 '이 그림에 없는 함수').
        "excluded_test_artifact": counts.get("TEST_ARTIFACT", 0),
        "unclassifiable": unclassifiable,
        "note": LAYER_NOTE,
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


def _asil_interference(
    call_map: Dict[str, List[str]], file_of: Dict[str, str],
    asil_by_fn: Dict[str, Any], *, top_n: int = 20,
) -> Dict[str, Any]:
    """ASIL 함수 ↔ 저/무등급 함수 호출 엣지 + 모듈별 등급 혼재(N5).

    ISO 26262-6의 **freedom from interference 검토 후보**를 뽑는 장치이며 판정이 아니다:
    등급이 높은 함수가 낮은/미상 등급 함수를 호출하면(또는 그 반대) 간섭 분석 대상이 된다.
    등급 인덱스가 비면 available:false — 등급 부재를 'QM 전부'로 위장하지 않는다.
    """
    from workflow.asil_propagation import ASIL_RANK, normalize_asil
    from workflow.coverage_gap import _norm_fn

    idx: Dict[str, str] = {}
    for k, v in (asil_by_fn or {}).items():
        a = normalize_asil(v.get("asil") if isinstance(v, dict) else v)
        if a:
            idx[_norm_fn(k)] = a
    if not idx:
        return {"available": False, "reason": "no_asil_index", "edges": [], "modules": []}

    def _rank(name: str) -> int:
        return ASIL_RANK.get(idx.get(_norm_fn(name), ""), -1)

    edges: List[Dict[str, Any]] = []
    for caller, callees in call_map.items():
        cr = _rank(caller)
        for callee in callees:
            tr = _rank(callee)
            if cr < 0 and tr < 0:
                continue                      # 양쪽 미상 — 간섭 판단 근거 없음
            if cr == tr:
                continue
            higher, lower = (caller, callee) if cr > tr else (callee, caller)
            edges.append({
                "caller": caller, "callee": callee,
                "caller_asil": idx.get(_norm_fn(caller)), "callee_asil": idx.get(_norm_fn(callee)),
                "higher": higher, "lower": lower,
                "caller_file": file_of.get(caller, ""), "callee_file": file_of.get(callee, ""),
                "cross_module": _module_of(file_of.get(caller, "")) != _module_of(file_of.get(callee, "")),
            })
    edges.sort(key=lambda e: (-max(ASIL_RANK.get(e["caller_asil"] or "", -1),
                                   ASIL_RANK.get(e["callee_asil"] or "", -1)),
                              e["caller"], e["callee"]))

    mod_levels: Dict[str, Dict[str, int]] = {}
    for fn, rel in file_of.items():
        a = idx.get(_norm_fn(fn))
        m = _module_of(rel)
        bucket = mod_levels.setdefault(m, {})
        key = a or "unknown"
        bucket[key] = bucket.get(key, 0) + 1
    modules = []
    for m, dist in mod_levels.items():
        graded = {k: v for k, v in dist.items() if k != "unknown"}
        modules.append({
            "module": m, "distribution": dist,
            "levels": len(graded),
            "max_asil": max(graded, key=lambda k: ASIL_RANK.get(k, -1)) if graded else None,
            "mixed": len(graded) > 1,
        })
    modules.sort(key=lambda r: (-int(r["mixed"]), -ASIL_RANK.get(r["max_asil"] or "", -1), r["module"]))
    return {
        "available": True,
        "reason": None,
        "graded_functions": len(idx),
        "edges": edges[:top_n],
        "edges_total": len(edges),
        "modules": modules[:top_n],
        "mixed_modules": sum(1 for m in modules if m["mixed"]),
        "note": ("등급이 다른 함수 간 호출은 ISO 26262-6 freedom from interference 검토 "
                 "후보이며 위반 판정이 아니다. 등급은 요구 역전파/주석 관측치다."),
    }


def _global_coupling(
    used_globals: Dict[str, List[str]], file_of: Dict[str, str], *, top_n: int = 15,
) -> Dict[str, Any]:
    """전역 변수별 사용 함수/모듈 — 모듈 경계를 넘는 공유 데이터(N5).

    ⚠ 파서는 read/write를 구분하지 않는다 — "다중 writer"라 부르면 거짓이다. 여기서 세는 것은
    **사용(참조) 함수 수**와 **모듈 수**뿐이고, 경합/재진입은 이 지표로 단정할 수 없다.
    """
    by_global: Dict[str, Dict[str, set]] = {}
    for fn, globs in used_globals.items():
        for g in globs or []:
            name = str(g or "").strip()
            if not name:
                continue
            rec = by_global.setdefault(name, {"functions": set(), "modules": set(), "files": set()})
            rec["functions"].add(fn)
            rel = file_of.get(fn, "")
            rec["files"].add(rel)
            rec["modules"].add(_module_of(rel))
    rows = [
        {"global": g, "functions": len(r["functions"]), "modules": len(r["modules"]),
         "files": len(r["files"]), "module_names": sorted(r["modules"])[:6],
         # v6: 전역↔함수 이분 그래프 렌더 재료. 카운트만으론 그림을 못 그린다(캡 8 + 생략 수 표기).
         "functions_sample": sorted(r["functions"])[:8],
         "functions_omitted": max(0, len(r["functions"]) - 8)}
        for g, r in by_global.items()
    ]
    rows.sort(key=lambda r: (-r["modules"], -r["functions"], r["global"]))
    cross = [r for r in rows if r["modules"] > 1]
    return {
        "available": bool(rows),
        "reason": None if rows else "no_global_usage",
        "distinct_globals": len(rows),
        "functions_using_globals": sum(1 for v in used_globals.values() if v),
        "cross_module_globals": len(cross),
        "top": rows[:top_n],
        "note": ("파서는 읽기/쓰기를 구분하지 않는다 — 아래 수치는 '사용(참조)' 기준이며 "
                 "다중 writer·경합을 단정하지 않는다."),
    }


def _coverage_complexity(
    known: set, file_of: Dict[str, str], complexity_of,
    coverage_by_fn: Optional[Dict[str, Any]], *, top_n: int = 15,
) -> Dict[str, Any]:
    """커버리지 × 복잡도 사분면 — 테스트 투자 우선순위(N5). 미조인은 별도 카운트."""
    if not coverage_by_fn:
        return {"available": False, "reason": "no_coverage_index"}
    from workflow.coverage_gap import _norm_fn

    idx = {_norm_fn(k): v for k, v in coverage_by_fn.items()}
    joined: List[Dict[str, Any]] = []
    unjoined = 0
    for n in known:
        rec = idx.get(_norm_fn(n))
        st = (rec or {}).get("statement") if isinstance(rec, dict) else None
        if not isinstance(st, (int, float)):
            unjoined += 1
            continue
        comp = complexity_of(n)
        joined.append({
            "function": n, "file": file_of.get(n, ""),
            "statement": round(float(st), 4), "branch": (rec or {}).get("branch"),
            **comp,
        })
    if not joined:
        return {"available": False, "reason": "no_joined_functions", "unjoined": unjoined}
    # 복잡도 임계는 측정 ccn 기준(loc_proxy는 척도가 달라 사분면에서 제외 — 혼합 시 순위 오염).
    measured = [r for r in joined if r["complexity_source"] == "vcast_ccn"]
    pool = measured or joined
    comps = sorted(r["complexity"] for r in pool)
    hi_comp = comps[int(len(comps) * 0.75)] if comps else 0
    quadrants = {"high_complex_low_cov": [], "high_complex_high_cov": [],
                 "low_complex_low_cov": [], "low_complex_high_cov": 0}
    for r in pool:
        hi_c = r["complexity"] >= max(hi_comp, 1)
        lo_v = r["statement"] < 0.8
        if hi_c and lo_v:
            quadrants["high_complex_low_cov"].append(r)
        elif hi_c:
            quadrants["high_complex_high_cov"].append(r)
        elif lo_v:
            quadrants["low_complex_low_cov"].append(r)
        else:
            quadrants["low_complex_high_cov"] += 1
    for key in ("high_complex_low_cov", "high_complex_high_cov", "low_complex_low_cov"):
        quadrants[key].sort(key=lambda r: (r["statement"], -r["complexity"], r["function"]))
    return {
        "available": True,
        "reason": None,
        "joined": len(joined),
        "unjoined": unjoined,               # 조인 실패는 침묵 제외하지 않는다
        "complexity_basis": "vcast_ccn" if measured else "loc_proxy",
        "complexity_threshold": hi_comp,
        "coverage_threshold": 0.8,
        "counts": {k: (len(v) if isinstance(v, list) else v) for k, v in quadrants.items()},
        "priority": quadrants["high_complex_low_cov"][:top_n],
        "note": ("사분면 임계는 측정 복잡도 상위 25%와 구문 80% 기준이다. 커버리지 미조인 "
                 "함수는 제외했으며 그 수를 unjoined로 표기한다."),
    }


def compute_architecture_metrics(
    source_dir: Path,
    *,
    ccn_by_function: Optional[Dict[str, int]] = None,
    asil_by_function: Optional[Dict[str, Any]] = None,
    coverage_by_function: Optional[Dict[str, Any]] = None,
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
    comment_asil_map: Dict[str, str] = {}
    globals_of: Dict[str, List[str]] = {}
    func_refs_of: Dict[str, List[str]] = {}
    pointer_calls_of: Dict[str, List[str]] = {}
    static_fns: set = set()
    documented_fns: set = set()
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
            comment_asil_map[name] = asil.upper()
        # v4(N5): 전역 사용·간접 호출·캡슐화 재료 — 파서가 이미 주는데 버려지던 필드들.
        globals_of[name] = [str(g) for g in (f.get("used_globals") or [])]
        func_refs_of[name] = [str(r) for r in (f.get("func_refs") or [])]
        pointer_calls_of[name] = [str(p) for p in (f.get("pointer_calls") or [])]
        if f.get("is_static"):
            static_fns.add(name)
        if str(f.get("comment_desc") or "").strip():
            documented_fns.add(name)
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
    file_graph = _build_file_graph(file_of, body_lines, pair_counts)
    layer_graph = _build_layer_graph(call_map, file_of)
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

    # ── v4(N5): 간섭 자유 후보 · 전역 결합 · 커버리지×복잡도 · 간접 호출/캡슐화 ──
    # ASIL 인덱스는 주입(요구 역전파) 우선, 없으면 주석 맵 — 주석 0건 프로젝트에서도 축이 산다.
    asil_index: Dict[str, Any] = dict(asil_by_function or {}) or dict(comment_asil_map)
    interference = _asil_interference(call_map, file_of, asil_index)
    global_coupling = _global_coupling(globals_of, file_of)
    cov_complexity = _coverage_complexity(known, file_of, _complexity, coverage_by_function)
    indirect_fns = {n for n, v in func_refs_of.items() if v} | {n for n, v in pointer_calls_of.items() if v}
    indirect_edges = sum(len(v) for v in func_refs_of.values()) + sum(len(v) for v in pointer_calls_of.values())
    header_defined = sorted({n for n in known if str(file_of.get(n, "")).lower().endswith(".h")})

    return {
        "available": True,
        "version": ARCH_METRICS_VERSION,
        "asil_interference": interference,
        "global_coupling": global_coupling,
        "coverage_complexity": cov_complexity,
        "indirect_calls": {
            # 콜그래프(call_map)는 직접 호출만 담는다 — 함수포인터 참조/간접 호출 사이트는
            # 엣지에 반영되지 않으므로 그 규모를 정직하게 고지한다(실측 690함수).
            "functions_with_indirect": len(indirect_fns),
            "reference_edges": indirect_edges,
            "func_ref_functions": sum(1 for v in func_refs_of.values() if v),
            "pointer_call_functions": sum(1 for v in pointer_calls_of.values() if v),
            "top": [
                {"function": n, "func_refs": len(func_refs_of.get(n) or ()),
                 "pointer_calls": len(pointer_calls_of.get(n) or ()), "file": file_of.get(n, "")}
                for n in sorted(indirect_fns,
                                key=lambda x: (-(len(func_refs_of.get(x) or ()) + len(pointer_calls_of.get(x) or ())), x))[:10]
            ],
            "note": ("함수포인터 참조·간접 호출 사이트는 호출 그래프 엣지에 포함되지 않는다 — "
                     "fan-in/out·사이클은 직접 호출 기준 하한값으로 읽어야 한다."),
        },
        "encapsulation": {
            "functions": len(known),
            # ⚠ 파서의 static 판정은 신뢰도가 낮다(실측 914함수 중 2건 — 실제 C 코드와 불일치).
            # 비율로 제시하면 '캡슐화가 거의 없다'는 허위 결론을 부르므로 탐지 수만 싣고
            # 한계를 note로 명시한다(측정과 추정 혼동 금지 규약).
            "static_functions_detected": len(static_fns),
            "static_detection_reliable": False,
            "header_defined_functions": len(header_defined),
            "header_defined_top": header_defined[:10],
            "documented_functions": len(documented_fns),
            "documented_ratio": round(len(documented_fns) / len(known), 3) if known else None,
            "note": ("static 판정은 파서 한계로 과소 탐지된다 — 비율 해석 금지. 문서화 비율은 "
                     "함수 주석(설명문) 보유 기준이다."),
        },
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
        # by_function은 **소스 주석 기반**만 담는다(기존 계약 — 라우터가 이걸 역전파와 병합한다).
        "asil_functions": {"count": len(comment_asil_map), "by_function": comment_asil_map,
                           "index_used": len(asil_index)},
        "excerpts": excerpts,
        "module_graph": module_graph,
        # v5(O3): 모듈 노드 → 내부 파일 드릴다운 재료. 모듈 그래프와 같은 pair_counts에서 나온다.
        "file_graph": file_graph,
        # v6(Q2): ISO 26262-6 계층 관점 — APP/BSW/LIB/BOOT와 역방향 호출(검토 후보).
        "layer_graph": layer_graph,
        "cycles": {
            # 0건이면 빈 배열(키 자체는 항상 존재 — 프론트가 '관측 없음'을 명시 렌더).
            "file_sccs": [{"files": c, "size": len(c)} for c in file_sccs[:10]],
            "module_sccs": [{"modules": c, "size": len(c)} for c in module_sccs[:10]],
            "mutual_file_pairs": mutual_pairs[:10],
        },
        "refactor_candidates": refactor_candidates,
    }
