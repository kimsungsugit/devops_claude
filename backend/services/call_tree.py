from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_CODE_EXTS = {".c", ".h", ".cpp", ".hpp"}
_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "catch",
    "case",
    "do",
    "else",
}

_EXTERNAL_HEADER_MAP = {
    "stdio.h": {
        "printf",
        "sprintf",
        "snprintf",
        "scanf",
        "puts",
        "putchar",
        "getchar",
        "fopen",
        "fclose",
        "fread",
        "fwrite",
        "fprintf",
        "fscanf",
    },
    "string.h": {
        "memcpy",
        "memset",
        "memcmp",
        "strlen",
        "strcpy",
        "strncpy",
        "strcat",
        "strncat",
        "strcmp",
        "strncmp",
        "strchr",
        "strrchr",
        "strstr",
    },
    "stdlib.h": {
        "malloc",
        "free",
        "calloc",
        "realloc",
        "atoi",
        "atof",
        "strtol",
        "strtoul",
        "exit",
        "abs",
        "rand",
        "srand",
    },
    "math.h": {"sin", "cos", "tan", "sqrt", "pow", "fabs", "floor", "ceil"},
}


def _classify_external(name: str) -> Dict[str, str]:
    for header, funcs in _EXTERNAL_HEADER_MAP.items():
        if name in funcs:
            return {"header": header, "library": header.replace(".h", "")}
    return {"header": "unknown", "library": "unknown"}


def _build_external_lookup(custom_map: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, str]]:
    lookup: Dict[str, Dict[str, str]] = {}
    for header, funcs in _EXTERNAL_HEADER_MAP.items():
        for name in funcs:
            lookup[name] = {"header": header, "library": header.replace(".h", "")}
    for item in custom_map or []:
        if not isinstance(item, dict):
            continue
        header = str(item.get("header") or "unknown")
        library = str(item.get("library") or header.replace(".h", ""))
        names = item.get("names") or item.get("name")
        if isinstance(names, str):
            names = [n.strip() for n in names.replace("\n", ",").split(",") if n.strip()]
        if not isinstance(names, list):
            continue
        for name in names:
            if not name:
                continue
            lookup[str(name)] = {"header": header, "library": library}
    return lookup


def _normalize_tokens(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for item in values:
        raw = str(item).replace("\\", "/").strip().strip("/")
        if raw:
            out.append(raw)
    return out


def _matches_filters(rel_path: str, include: List[str], exclude: List[str]) -> bool:
    rel_norm = rel_path.replace("\\", "/").strip("/")
    if exclude:
        for token in exclude:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return False
    if include:
        for token in include:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return True
        return False
    return True


def _strip_comments_and_strings(text: str) -> str:
    out = []
    i = 0
    length = len(text)
    in_block = False
    in_line = False
    in_str = False
    in_chr = False
    while i < length:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < length else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
            i += 1
            continue
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == "\"":
                in_str = False
            i += 1
            continue
        if in_chr:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_chr = False
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if ch == "\"":
            in_str = True
            i += 1
            continue
        if ch == "'":
            in_chr = True
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _iter_source_files(
    root_dir: Path,
    include_paths: List[str],
    exclude_paths: List[str],
    max_files: int,
) -> List[Path]:
    out: List[Path] = []
    for path in root_dir.rglob("*"):
        if len(out) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in _CODE_EXTS:
            continue
        rel = path.relative_to(root_dir).as_posix()
        if not _matches_filters(rel, include_paths, exclude_paths):
            continue
        out.append(path)
    return out


def _load_compile_commands(path: Path, source_root: Path) -> List[Path]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    files: List[Path] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        file_value = item.get("file")
        if not file_value:
            continue
        file_path = Path(str(file_value))
        if not file_path.is_absolute():
            directory = Path(str(item.get("directory") or "")).resolve()
            if directory:
                file_path = (directory / file_path).resolve()
        if file_path.suffix.lower() not in _CODE_EXTS:
            continue
        try:
            if file_path.exists() and file_path.is_file() and file_path.resolve().is_relative_to(source_root):
                files.append(file_path.resolve())
        except Exception:
            continue
    uniq = sorted({p for p in files})
    return uniq


def _scan_functions(source_files: List[Path]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    func_defs: Dict[str, Dict[str, Any]] = {}
    duplicates: List[Dict[str, Any]] = []
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", re.MULTILINE)
    for path in source_files:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        cleaned = _strip_comments_and_strings(raw)
        for match in pattern.finditer(cleaned):
            name = match.group(1)
            if name in _KEYWORDS:
                continue
            start = match.end() - 1
            depth = 0
            end = None
            for idx in range(start, len(cleaned)):
                if cleaned[idx] == "{":
                    depth += 1
                elif cleaned[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx
                        break
            if end is None:
                continue
            body = cleaned[start + 1 : end]
            if name in func_defs:
                duplicates.append({"name": name, "path": str(path)})
                continue
            func_defs[name] = {"name": name, "path": str(path), "body": body}
    return func_defs, duplicates


def _extract_calls(
    body: str,
    known_funcs: Set[str],
    external_lookup: Dict[str, Dict[str, str]],
) -> Tuple[List[str], List[Dict[str, str]]]:
    calls: Set[str] = set()
    externals: Dict[str, Dict[str, str]] = {}
    if not body:
        return [], []
    call_pat = re.compile(r"\b([A-Za-z_]\w*)\s*\(", re.MULTILINE)
    for match in call_pat.finditer(body):
        callee = match.group(1)
        if callee in _KEYWORDS:
            continue
        if callee in known_funcs:
            calls.add(callee)
        else:
            if callee not in externals:
                externals[callee] = {"name": callee, **external_lookup.get(callee, _classify_external(callee))}
    return sorted(calls), [externals[k] for k in sorted(externals.keys())]


def _build_tree(
    name: str,
    call_map: Dict[str, List[str]],
    external_map: Dict[str, List[Dict[str, str]]],
    max_depth: int,
    depth: int,
    visited: Set[str],
    include_external: bool,
    budget: Optional[List[int]] = None,
    ref_map: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, Any]:
    # budget = [남은_노드_예산, 절단_플래그] (auto_roots 전체 포레스트에서만 전달). _build_tree는
    # 자식마다 visited를 복사해 경로를 열거(그래프 아님)하므로 노드가 branching^depth로 팽창할 수
    # 있다 → 전역 예산으로 상한(수동 entry 경로는 budget=None으로 무변경).
    if budget is not None and budget[0] <= 0:
        budget[1] = 1
        return {"name": name, "calls": [], "budget_exceeded": True}
    node: Dict[str, Any] = {"name": name, "calls": []}
    if budget is not None:
        budget[0] -= 1
    if depth >= max_depth:
        node["truncated"] = True
        return node
    if name in visited:
        node["cycle"] = True
        return node
    visited.add(name)
    ref_children = ref_map.get(name, ()) if ref_map else ()
    for callee in call_map.get(name, []):
        child = _build_tree(callee, call_map, external_map, max_depth, depth + 1, set(visited), include_external, budget, ref_map)
        if callee in ref_children:
            # feature 2: 직접호출이 아니라 함수포인터 참조(&/대입/인자 전달)로 추론된 엣지 — 신뢰도 구분.
            child["via_ref"] = True
        node["calls"].append(child)
    if include_external:
        node["externals"] = external_map.get(name, [])
    return node


# auto_roots(전체 콜트리) 자원 상한 — 수동 entry [:200] 캡과 parity + 포레스트 전역 노드 예산.
# 대형 프로젝트에서 루트 수(=in-degree 0 함수)나 경로 열거 팽창이 payload/CPU/프론트 프리즈를
# 유발하지 않도록 방어. 절단 발생은 stats(roots_truncated/nodes_truncated)로 정직하게 노출.
_MAX_AUTO_ROOTS = 200
_MAX_FOREST_NODES = 60000

# boot/진입점 루트를 truncation([:_MAX_AUTO_ROOTS])에서 우선 보존하기 위한 이름 기반 우선순위.
# 백엔드는 시그니처가 없어 이름만으로 판별(0=boot, 1=ISR/인터럽트, 2=일반) — 프론트는 노드
# signature('ISR (...)')까지 활용해 Cpu_* 등을 더 정밀히 재정렬한다(표시 전용). 여기서 boot를
# 앞세우는 목적은, 대형 프로젝트에서 main·_Startup이 알파벳 절단에 밀려 누락되지 않게 하는 것.
_BOOT_ROOT_NAMES = frozenset({"main", "_start", "__start", "_startup", "_entrypoint", "reset_handler", "startup"})


def _invert_call_map(call_map: Dict[str, List[str]], known: Set[str]) -> Dict[str, List[str]]:
    """호출 그래프 반전(feature 1 역방향). inv[callee] = [callee를 호출하는 caller들].
    known 전체를 키로 초기화(고아 leaf도 루트 산출에 참여). 방향만 뒤집으므로 엣지 수는 동일."""
    inv: Dict[str, Set[str]] = {k: set() for k in known}
    for caller, callees in call_map.items():
        for c in callees:
            if c in known:
                inv.setdefault(c, set()).add(caller)
    return {k: sorted(v) for k, v in inv.items()}


def _root_priority(name: str) -> int:
    n = str(name or "").lower()
    if n in _BOOT_ROOT_NAMES:
        return 0
    if n.endswith(("_interrupt", "_isr", "_irqhandler", "_irq")) or n.startswith("isr_"):
        return 1
    return 2


def _auto_root_entries(call_map: Dict[str, List[str]], known: Set[str]) -> List[str]:
    """전체 콜트리용 루트 집합 산출.

    루트 = in-degree 0 함수(아무도 호출하지 않는 진입점 — main·ISR·콜백·미사용 등).
    이 루트들의 forest가 known 전체를 도달하도록, 순환만으로 묶여(mutual recursion) 루트에서
    도달 불가한 컴포넌트는 결정적 순서로 대표 1개씩 추가 루트로 흡수한다 → 100% 커버 보장.
    반환 순서는 결정적: (진입점 우선순위, 이름)로 정렬 — boot(main·_Startup) → ISR → 일반 순.
    이 순서가 [:_MAX_AUTO_ROOTS] 절단 선택 순서이기도 하므로 boot 루트가 먼저 보존된다.
    """
    called: Set[str] = set()
    for callees in call_map.values():
        for c in callees:
            if c in known:
                called.add(c)
    roots: List[str] = sorted(known - called, key=lambda n: (_root_priority(n), n))
    reached: Set[str] = set()
    stack: List[str] = list(roots)
    while stack:
        n = stack.pop()
        if n in reached:
            continue
        reached.add(n)
        for c in call_map.get(n, []):
            if c in known and c not in reached:
                stack.append(c)
    # 순환 전용(미도달) 컴포넌트: 결정적 순서로 대표를 추가 루트화하며 그 컴포넌트 흡수
    for n in sorted(known - reached):
        if n in reached:
            continue
        roots.append(n)
        stack = [n]
        while stack:
            m = stack.pop()
            if m in reached:
                continue
            reached.add(m)
            for c in call_map.get(m, []):
                if c in known and c not in reached:
                    stack.append(c)
    return roots


def build_call_tree(
    source_root: Path,
    entries: List[str],
    include_paths: Optional[List[str]] = None,
    exclude_paths: Optional[List[str]] = None,
    max_depth: int = 5,
    max_files: int = 2000,
    include_external: bool = False,
    compile_commands_path: Optional[Path] = None,
    external_map: Optional[List[Dict[str, Any]]] = None,
    auto_roots: bool = False,
    reverse: bool = False,
) -> Dict[str, Any]:
    root_dir = Path(source_root).resolve()
    include_tokens = _normalize_tokens(include_paths)
    exclude_tokens = _normalize_tokens(exclude_paths)
    compile_db = compile_commands_path or (root_dir / "compile_commands.json")
    if compile_db.exists():
        src_files = _load_compile_commands(compile_db, root_dir)
        src_files = [
            p for p in src_files
            if _matches_filters(p.relative_to(root_dir).as_posix(), include_tokens, exclude_tokens)
        ]
        src_files = src_files[:max_files]
    else:
        src_files = _iter_source_files(root_dir, include_tokens, exclude_tokens, max_files)
    func_defs, duplicates = _scan_functions(src_files)
    known = set(func_defs.keys())
    call_map: Dict[str, List[str]] = {}
    # C2 fix: 과거 지역변수 `external_map`(Dict)이 파라미터 `external_map`(List, 사용자 custom
    # 분류)을 동명으로 shadow해 349행 _build_external_lookup이 빈 dict를 받아 custom external_map이
    # 무력화되던 결함. 함수별 external 결과는 별도 변수 `external_calls`로 분리한다.
    external_calls: Dict[str, List[Dict[str, str]]] = {}
    external_lookup = _build_external_lookup(external_map)
    for name, info in func_defs.items():
        calls, externals = _extract_calls(info.get("body", ""), known, external_lookup)
        call_map[name] = calls
        external_calls[name] = externals
    # feature 1: 역방향(called-by) — regex 엔진도 반전 parity. external은 방향상 무의미 → 비움.
    if reverse:
        call_map = _invert_call_map(call_map, known)
        external_calls = {k: [] for k in external_calls}
    roots_total = 0
    budget: Optional[List[int]] = None
    if auto_roots:
        all_roots = _auto_root_entries(call_map, known)
        roots_total = len(all_roots)
        entries = all_roots[:_MAX_AUTO_ROOTS]
        budget = [_MAX_FOREST_NODES, 0]
    trees = []
    missing = []
    for entry in entries:
        if entry not in known:
            missing.append(entry)
            continue
        trees.append(_build_tree(entry, call_map, external_calls, max_depth, 0, set(), include_external, budget))
    edges = sum(len(v) for v in call_map.values())
    return {
        "source_root": str(root_dir),
        "entries": entries,
        "trees": trees,
        "missing": missing,
        "stats": {
            "files_scanned": len(src_files),
            "functions": len(known),
            "edges": edges,
            "duplicates": len(duplicates),
            "roots": len(entries) if auto_roots else 0,
            "roots_total": roots_total,
            "roots_truncated": bool(auto_roots and roots_total > len(entries)),
            "nodes_truncated": bool(budget is not None and budget[1]),
            "compile_commands": str(compile_db) if compile_db.exists() else "",
            "reverse": bool(reverse),
        },
    }


def _enrich_nodes(node: Dict[str, Any], func_meta: Dict[str, Dict[str, Any]]) -> None:
    """트리 노드에 함수 메타(file/signature/asil)를 주입 — 정밀 엔진 전용.

    parse_c_project가 제공하는 Doxygen ASIL/시그니처/파일을 노드에 실어 프론트가 ASIL 배지·
    소스 점프를 렌더할 수 있게 한다. cycle/truncated 노드도 name 기준으로 메타를 채운다.
    """
    meta = func_meta.get(node.get("name") or "")
    if meta:
        if meta.get("asil"):
            node["asil"] = meta["asil"]
        if meta.get("file"):
            node["file"] = meta["file"]
        if meta.get("signature"):
            node["signature"] = meta["signature"]
        if meta.get("indirect"):
            # feature 3: 이 함수 본문의 미해결 간접호출(함수포인터/디스패치) — 프론트가 ⚡ 배지로 노출.
            node["indirect"] = meta["indirect"]
    for child in node.get("calls") or []:
        _enrich_nodes(child, func_meta)


def build_call_tree_precise(
    source_root: Path,
    entries: List[str],
    include_paths: Optional[List[str]] = None,
    exclude_paths: Optional[List[str]] = None,
    max_depth: int = 5,
    max_files: int = 2000,
    include_external: bool = False,
    external_map: Optional[List[Dict[str, Any]]] = None,
    auto_roots: bool = False,
    reverse: bool = False,
) -> Dict[str, Any]:
    """tree-sitter(parse_c_project) 기반 정밀 콜트리.

    reverse=True면 호출 그래프를 반전해 '누가 이 함수를 호출하나(called-by)' 트리를 낸다(영향분석용).
    func_refs(&foo/pfn=foo/f(foo))는 known 함수만 엣지로 승격해 함수포인터 등록의 도달성을 복원하고
    (via_ref 태그), pointer_calls(미해결 간접호출)는 node.indirect로 실어 프론트가 배지로 노출한다.

    regex 엔진(build_call_tree)과 동일한 출력 shape를 내되, 호출엣지를 tree-sitter로 추출해
    함수포인터/콜백 등록(handler·callback 대입)까지 잡는다. parse_c_project의 calls는
    표준 라이브러리만 제거한 모든 호출이므로, known(프로젝트 정의 함수)에 없는 호출을 external로
    분리해 _build_external_lookup으로 분류한다. 노드에는 ASIL/파일/시그니처 메타를 보강한다.

    tree-sitter 미가용 시 parse_c_project가 functions=[]를 반환 → known 빈 → 모든 entry가
    missing으로 떨어지고 stats.engine='unavailable'로 표기한다. 호출자(엔드포인트)는 이 신호로
    regex 엔진 폴백을 결정할 수 있다(R1 완화).
    """
    root_dir = Path(source_root).resolve()
    include_tokens = _normalize_tokens(include_paths)
    exclude_tokens = _normalize_tokens(exclude_paths)
    try:
        from workflow.code_parser import c_parser as _cp
    except Exception:
        return {
            "source_root": str(root_dir),
            "entries": entries,
            "trees": [],
            "missing": list(entries),
            "stats": {
                "files_scanned": 0,
                "functions": 0,
                "edges": 0,
                "duplicates": 0,
                "compile_commands": "",
                "engine": "unavailable",
            },
        }
    parsed = _cp.parse_c_project(str(root_dir), max_files=max(1, int(max_files)))
    funcs = parsed.get("functions", []) or []
    raw_calls: Dict[str, List[str]] = {}
    raw_refs: Dict[str, List[str]] = {}      # feature 2: 함수 참조(&foo/pfn=foo/f(foo))
    raw_pcalls: Dict[str, List[str]] = {}    # feature 3: 간접 호출 사이트((*p)()/obj->h()/pfn())
    func_meta: Dict[str, Dict[str, Any]] = {}
    for f in funcs:
        nm = f.get("name")
        if not nm:
            continue
        # include/exclude를 함수의 소스 파일 경로 기준으로 적용(regex 엔진과 동일 의미)
        if include_tokens or exclude_tokens:
            rel = f.get("file") or ""
            try:
                rel_norm = Path(rel).resolve().relative_to(root_dir).as_posix()
            except Exception:
                rel_norm = str(rel).replace("\\", "/")
            if not _matches_filters(rel_norm, include_tokens, exclude_tokens):
                continue
        raw_calls[nm] = list(f.get("calls", []) or [])
        raw_refs[nm] = list(f.get("func_refs", []) or [])
        raw_pcalls[nm] = list(f.get("pointer_calls", []) or [])
        func_meta[nm] = {
            "file": f.get("file"),
            "signature": f.get("signature"),
            "asil": f.get("comment_asil") or f.get("asil"),
        }
    known = set(raw_calls.keys())
    # include/exclude로 스코프 밖이지만 프로젝트 정의 함수(필터 전 전체) — external(unknown 라이브러리)로
    # 오분류하지 않기 위해 별도 집합 유지(리뷰 finding [1]).
    all_project_funcs = {f.get("name") for f in funcs if f.get("name")}
    external_lookup = _build_external_lookup(external_map)
    call_map: Dict[str, List[str]] = {}
    external_calls: Dict[str, List[Dict[str, str]]] = {}
    ref_map: Dict[str, Set[str]] = {}   # feature 2: ref로만 생긴 엣지(via_ref 표시용 — 직접호출 제외)
    for nm, calls in raw_calls.items():
        internal: Set[str] = set()
        externals: Dict[str, Dict[str, str]] = {}
        for callee in calls:
            if callee in known:
                internal.add(callee)
            elif callee in all_project_funcs:
                # 스코프 밖(필터 제외) 프로젝트 함수 — external 오분류 대신 internal leaf로(자식 없음).
                internal.add(callee)
            elif callee not in externals:
                externals[callee] = {"name": callee, **external_lookup.get(callee, _classify_external(callee))}
        # feature 2: &foo/pfn=foo/f(foo)로 참조된 known 함수를 엣지로 승격(함수포인터 등록 도달성 복원).
        # 직접호출에 이미 있던 것은 제외 → ref로만 생긴 엣지만 via_ref로 표시(직접≠추론 구분).
        promoted = {r for r in raw_refs.get(nm, []) if r in known and r != nm}
        ref_map[nm] = promoted - internal
        internal |= promoted
        # feature 3: 미해결 간접호출만 남김 — known으로 풀리는 pfn명(실제 해결됨)은 제외, 구조적(->/[]/*)은 유지.
        indirect = [p for p in raw_pcalls.get(nm, [])
                    if not (re.fullmatch(r"[A-Za-z_]\w*", p) and p in known)]
        if indirect:
            func_meta.setdefault(nm, {})["indirect"] = indirect
        call_map[nm] = sorted(internal)
        external_calls[nm] = [externals[k] for k in sorted(externals.keys())]
    # feature 1: 역방향(called-by) — 호출 그래프를 반전. external은 방향상 무의미 → 비움.
    # via_ref(추론 엣지)는 방향도 함께 반전해 유지 — reverse에서 X의 자식(caller) C가 참조엣지였으면
    # C를 via_ref로 표시(추론 엣지가 영향분석에서 실엣지처럼 위장하지 않게, 리뷰 W1).
    if reverse:
        call_map = _invert_call_map(call_map, known)
        external_calls = {k: [] for k in external_calls}
        inv_ref: Dict[str, Set[str]] = {}
        for caller, callees in ref_map.items():
            for c in callees:
                inv_ref.setdefault(c, set()).add(caller)
        ref_map = inv_ref
    roots_total = 0
    budget: Optional[List[int]] = None
    if auto_roots:
        all_roots = _auto_root_entries(call_map, known)
        roots_total = len(all_roots)
        entries = all_roots[:_MAX_AUTO_ROOTS]
        budget = [_MAX_FOREST_NODES, 0]
    trees = []
    missing = []
    for entry in entries:
        if entry not in known:
            missing.append(entry)
            continue
        tree = _build_tree(entry, call_map, external_calls, max_depth, 0, set(), include_external, budget, ref_map)
        _enrich_nodes(tree, func_meta)
        trees.append(tree)
    edges = sum(len(v) for v in call_map.values())
    return {
        "source_root": str(root_dir),
        "entries": entries,
        "trees": trees,
        "missing": missing,
        "stats": {
            "files_scanned": len(parsed.get("scanned", []) or []),
            "functions": len(known),
            "edges": edges,
            "duplicates": 0,
            "roots": len(entries) if auto_roots else 0,
            "roots_total": roots_total,
            "roots_truncated": bool(auto_roots and roots_total > len(entries)),
            "nodes_truncated": bool(budget is not None and budget[1]),
            "compile_commands": "",
            "reverse": bool(reverse),
            # parse_c_project가 검증된 tree-sitter 파서 성공 여부를 parser_engine으로 정직 노출
            # (import 유무가 아니라 실제 파싱 성공 — #if 중첩/capsule 소비로 regex 폴백되면 그대로 표기).
            "engine": parsed.get("parser_engine")
            or ("tree-sitter" if (getattr(_cp, "Parser", None) is not None and getattr(_cp, "c_language", None) is not None) else "regex-fallback"),
        },
    }


def call_tree_to_csv(payload: Dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    job_url = (meta or {}).get("job_url", "")
    build_selector = (meta or {}).get("build_selector", "")
    build_root = (meta or {}).get("build_root", "")
    writer.writerow(["entry_root", "parent", "callee", "type", "header", "library", "depth", "path", "job_url", "build_selector", "build_root"])

    def _walk(node: Dict[str, Any], depth: int, path: str, entry_root: str) -> None:
        parent = node.get("name")
        for child in node.get("calls") or []:
            child_name = child.get("name")
            child_path = f"{path} > {child_name}" if path else str(child_name)
            writer.writerow([
                entry_root,
                parent,
                child_name,
                "internal",
                "",
                "",
                depth + 1,
                child_path,
                job_url,
                build_selector,
                build_root,
            ])
            _walk(child, depth + 1, child_path, entry_root)
        for ext in node.get("externals") or []:
            ext_name = ext.get("name")
            ext_path = f"{path} > {ext_name}" if path else str(ext_name)
            writer.writerow([
                entry_root,
                parent,
                ext_name,
                "external",
                ext.get("header"),
                ext.get("library"),
                depth + 1,
                ext_path,
                job_url,
                build_selector,
                build_root,
            ])

    for root in payload.get("trees") or []:
        root_name = root.get("name")
        _walk(root, 0, str(root_name), str(root_name))
    return buf.getvalue()


def call_tree_to_html(payload: Dict[str, Any], template: Optional[str] = None) -> str:
    def _render_node(node: Dict[str, Any]) -> str:
        name = node.get("name", "")
        flags = []
        if node.get("cycle"):
            flags.append("cycle")
        if node.get("truncated"):
            flags.append("truncated")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        html = [f"<li><strong>{name}</strong>{flag_text}"]
        externals = node.get("externals") or []
        if externals:
            html.append("<ul>")
            for ext in externals:
                html.append(
                    f"<li>{ext.get('name')} <em>[{ext.get('header')} | {ext.get('library')}]</em></li>"
                )
            html.append("</ul>")
        children = node.get("calls") or []
        if children:
            html.append("<ul>")
            for child in children:
                html.append(_render_node(child))
            html.append("</ul>")
        html.append("</li>")
        return "".join(html)

    tree_parts = ["<ul>"]
    for root in payload.get("trees") or []:
        tree_parts.append(_render_node(root))
    tree_parts.append("</ul>")
    tree_html = "".join(tree_parts)

    raw_template = (template or "").strip()
    if raw_template:
        if "{{tree}}" in raw_template or "{{content}}" in raw_template:
            return raw_template.replace("{{tree}}", tree_html).replace("{{content}}", tree_html)
        return raw_template + tree_html

    parts = [
        "<html><head><meta charset='utf-8'/>",
        "<style>body{font-family:Arial,sans-serif;font-size:13px} ul{list-style:disc;margin-left:16px}</style>",
        "</head><body>",
        "<h3>Function Call Tree</h3>",
        tree_html,
        "</body></html>",
    ]
    return "".join(parts)
