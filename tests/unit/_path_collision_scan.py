# -*- coding: utf-8 -*-
"""ts 기반 산출물 경로 중 **선점되지 않은 것**을 AST 로 찾는다.

## 왜 문자열 grep 이 아니라 AST 인가

이 저장소의 경로 조립 관용구는 `<디렉터리> / f"...{ts}..."` 다. 문자열 검색으로 찾으면
①결함을 설명한 **주석**에 걸리고(실제로 걸렸다) ②`f"Run {run_id} | …"` 같은 **메시지**를
경로로 오인한다. AST 로 `BinOp(/)` 의 오른쪽이 ts 유래 f-string 인 경우만 본다.

## ⚠ 오염 전파를 좁게 잡는 이유

처음엔 "ts 를 참조하는 모든 대입"을 모듈 전역에서 전파시켰다. 그랬더니 `total`·`filename`
같은 흔한 이름이 다른 함수에서 오염돼 **55건이 잡혔고 대부분 나눗셈이었다**(`covered / total`).
지금은 ①**함수 스코프별**로 재고 ②**f-string 을 거친 대입만** 전파한다 — 경로 이름 조립이
실제로 그 형태이기 때문이다.

## 면제 표기

의도적으로 선점하지 않는 자리는 같은 줄 또는 바로 윗줄에 `# path-collision-ok: <사유>`
를 단다(이 저장소의 `# silent-ok` 와 같은 관용구). 사유 없는 면제는 인정하지 않는다.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Set, Tuple

#: 서버가 쓰는 산출물만 본다. `tools/` 는 수동 실행 스크립트라 제외.
ROOTS = ("backend", "workflow", "report_gen", "generators")
_SKIP_PARTS = {".venv", "node_modules", "__pycache__", "site-packages", "tests"}
_TS_FMT = "%Y%m%d_%H%M%S"
_RESERVERS = {"reserve_unique_path", "reserve_unique_dir"}
_EXEMPT = "# path-collision-ok:"
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)


def _is_ts_call(node: ast.AST) -> bool:
    """`datetime.now().strftime("%Y%m%d_%H%M%S")` 인가 (뒤에 `+ …` 가 붙어도 인정)."""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "strftime" and sub.args
                and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == _TS_FMT):
            return True
    return False


def _names_in(node: ast.AST) -> Set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _own_body(scope: ast.AST) -> Iterator[ast.AST]:
    """중첩 함수 **안으로 내려가지 않는** 순회 — 바깥 이름을 섞지 않는다.

    ⚠ `ast.walk` 로 돌면서 중첩 스코프 노드만 `continue` 하면 **소용없다** — walk 는 이미
      그 자식들을 큐에 넣은 뒤다. 실제로 그렇게 짰다가 모듈 스코프가 전 함수의 지역명을
      보게 돼, 요청 파라미터 `filename` 이 오염된 것으로 잡혔다(오탐 5건).
    """
    stack: List[ast.AST] = [scope]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                continue
            stack.append(child)


def _scopes(tree: ast.AST) -> Iterator[ast.AST]:
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _tainted_in_scope(scope: ast.AST, body: List[ast.AST]) -> Set[str]:
    """`ts` → `base = f"…{ts}"` → `name = f"{base}.docx"` 만 따라간다.

    ⚠ 전이 폐포를 4번 도는데, 매 라운드 `ast.walk` 로 대입식을 다시 훑으면 큰 파일에서
      **저장소 전체 스캔이 57초**가 된다(실측). 대입별 특징을 **한 번만** 뽑아 두고
      폐포는 그 위에서 돈다.
    """
    # (대상 이름, ts 직접 여부, f-string 안에서 참조하는 이름들)
    facts: List[Tuple[str, bool, Set[str]]] = []
    for node in body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        v = node.value
        fstring_names: Set[str] = set()
        for s in ast.walk(v):
            if isinstance(s, ast.JoinedStr):
                fstring_names |= _names_in(s)
        facts.append((tgt.id, _is_ts_call(v), fstring_names))
    if not any(direct for _, direct, _ in facts):
        return set()

    tainted: Set[str] = set()
    for _ in range(4):  # 전이 폐포. 4겹이면 이 저장소엔 충분하다
        grew = False
        for name, direct, fstring_names in facts:
            if name in tainted:
                continue
            # ⚠ f-string 을 거친 것만 전파 — 나눗셈·집계로 번지지 않게.
            if direct or (fstring_names & tainted):
                tainted.add(name)
                grew = True
        if not grew:
            break
    return tainted


def _assign_target(scope: ast.AST, binop: ast.AST) -> str:
    """`x = <이 BinOp>` 라면 `x`, 아니면 빈 문자열."""
    for node in _own_body(scope):
        if (isinstance(node, ast.Assign) and node.value is binop
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            return node.targets[0].id
    return ""


def _exempt(lines: List[str], lineno: int) -> bool:
    """같은 줄, 또는 **바로 위에 붙은 주석 블록** 안에 마커가 있으면 면제.

    ⚠ 한 줄만 거슬러 보면 사유가 두 줄 이상인 마커를 못 읽는다(실제로 3건 놓쳤다).
      사유를 짧게 쓰라고 강요하는 건 방향이 반대다 — 블록 전체를 본다.
    """
    i = lineno - 1
    if 0 <= i < len(lines) and _EXEMPT in lines[i]:
        return True
    i -= 1
    while 0 <= i < len(lines) and lines[i].lstrip().startswith("#"):
        if _EXEMPT in lines[i]:
            return True
        i -= 1
    return False


def _reserved_lines(tree: ast.AST) -> Set[int]:
    """`reserve_unique_*(...)` 호출이 덮는 줄 범위."""
    out: Set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _RESERVERS):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            out.update(range(node.lineno, end + 1))
    return out


def _reserved_names(tree: ast.AST) -> Set[str]:
    """`reserve_unique_*(want)` 처럼 **나중에** 선점에 넘겨지는 이름.

    `want = out_dir / f"…"` 로 조립해 두고 두 줄 뒤에 선점하는 형태가 있다 — 줄 범위만
    보면 조립 줄이 미선점으로 잡힌다.
    """
    out: Set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _RESERVERS):
            for arg in node.args:
                out |= _names_in(arg)
    return out


def _iter_files() -> Iterator[Path]:
    for root in ROOTS:
        for f in Path(root).rglob("*.py"):
            if _SKIP_PARTS & set(f.parts):
                continue
            yield f


def scan_text(src: str, label: str = "<memory>") -> List[Tuple[str, int, str]]:
    """소스 문자열 하나를 검사한다 — 합성 코드로 스캐너 자체를 검증하려고 분리해 뒀다.

    ⚠ 파일만 훑는 스캐너는 **자기가 아무것도 못 찾는 상태**로 조용히 통과할 수 있다
      (경로 오타·루트 변경). 심어 둔 결함을 잡는지 함께 단언한다.
    """
    # ⚠ 가장 큰 절약 — ts 포맷이 아예 없는 파일은 파싱조차 하지 않는다.
    if _TS_FMT not in src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    reserved = _reserved_lines(tree)
    reserved_names = _reserved_names(tree)
    hits: Set[int] = set()
    for scope in _scopes(tree):
        body = list(_own_body(scope))
        tainted = _tainted_in_scope(scope, body)
        if not tainted:
            continue
        for node in body:
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
                continue
            if not (_names_in(node.right) & tainted):
                continue
            if node.lineno in reserved or _exempt(lines, node.lineno):
                continue
            if _assign_target(scope, node) in reserved_names:
                continue
            hits.add(node.lineno)
    return sorted((label, ln, lines[ln - 1].strip()[:120]) for ln in hits)


def scan_unreserved() -> List[Tuple[str, int, str]]:
    """(파일, 줄, 식) — ts 유래 f-string 으로 경로를 만드는데 선점도 면제도 없는 자리."""
    found: List[Tuple[str, int, str]] = []
    for f in _iter_files():
        try:
            src = f.read_text(encoding="utf-8")
        except OSError:
            continue
        found.extend(scan_text(src, str(f).replace("\\", "/")))
    return sorted(found)
