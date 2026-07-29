"""broad-silent except 탐지 (AST) — ruff 사각지대 보강.

`ruff`/E722 는 bare `except:` 만 본다. `except Exception: pass` 는 **구조적
사각지대**다(프로젝트 침묵 except 1294개의 대부분이 여기 산다). 이 모듈은
'실패를 조용히 삼키는 except' 라는 **코드 형태**를 찾는다.

⚠ 이건 '나쁜 코드' 탐지가 아니라 '형태' 탐지다. 구현 중 실측한 결과, 위험한
침묵(`jenkins_adapter.py:1716` write_complexity_csv 실패 삼킴 → 안전지표 영값)과
정당한 침묵(`jenkins_adapter.py:381` progress_cb telemetry / `jenkins.py:2329`
tmp.unlink cleanup)이 **구조적으로 완전히 동일**하다 — 둘 다
`try: <호출> except Exception: pass`. 따라서 분류기는 둘을 구분할 수 없고,
구분하려 들지도 않는다. **판단은 사람이 한다.**

이 사각지대를 실용적으로 좁히는 3가지 **비의미적** 면제:

  1. **좁은 예외** — Exception/BaseException/bare 가 아니면(`except KeyError:` 등)
     의도가 이미 명시된 것이라 flag 안 함.
  2. **body 에 raise 또는 로깅 호출** — 삼키지 않으므로 flag 안 함.
  3. **`# silent-ok` 마커** — 저자가 "이 침묵은 검토했고 괜찮다"를 **명시 선언**.
     except/pass 줄 어디든 이 문자열이 있으면 면제한다. greppable audit trail =
     fake-green 의 정반대(침묵을 숨기는 게 아니라 **드러내놓고** 승인). 정당한
     침묵(cleanup·telemetry)의 정당 해소책이다.

소비 지점 (분류기는 **단일 소스** — module_missing 3벌 파리티 교훈):
  - `posttool_dispatch.py` (PostToolUse, per-file): 편집 파일의 침묵 목록을
    advisory context 로 보고(비차단·정보성).
  - `quality_check.py §7d` (Stop, changed-files **ratchet**): git diff 추가 라인에
    속한 **net-new 침묵만** Warning. 레거시 1294개는 건드리는 파일이어도 침묵.

CLI (검증/수동용): `.venv/Scripts/python.exe scripts/_silence_check.py <file.py> ...`
  exit 0 = 침묵 없음 / 1 = 침묵 있음.
"""
from __future__ import annotations

import ast

#: 광의 예외 이름. 이걸(또는 bare) 잡아야 '침묵 후보'다.
_BROAD_NAMES = {"Exception", "BaseException"}

#: body 안에 이 이름의 호출이 있으면 "삼키지 않음"으로 보고 면제한다.
#: 과탐(정당한 침묵 놓침)보다 **under-report**(가짜 Warning 억제) 쪽으로 기운다 —
#: nudge 게이트라 조용한 편이 낫다. 부분 문자열 매칭이라 관대하다.
#: ⚠ `_call_name`은 **속성명만** 돌려준다(`_logger.exception` → `"exception"`). 그래서
#:   객체명에 'log'가 들어가도 소용이 없고, 메서드명 자체가 힌트에 있어야 한다. 이 때문에
#:   `logger.exception(...)`(로그+삼킴의 정석 관용구)이 통째로 오탐이었다 — routers/impact.py
#:   한 파일에서만 4건. "exception"을 추가해 그 계열을 면제한다.
_LOG_HINTS = (
    "log", "warn", "error", "critical", "print", "report",
    "trace", "debug", "notify", "alert", "emit", "capture", "raise", "exception",
)

#: body/except 줄에 이 문자열이 있으면 저자가 침묵을 명시 승인한 것.
SUPPRESS_MARKER = "silent-ok"


def _handler_names(handler: ast.ExceptHandler) -> list[str]:
    t = handler.type
    if t is None:
        return []  # bare except:
    elts = t.elts if isinstance(t, ast.Tuple) else [t]
    names: list[str] = []
    for e in elts:
        if isinstance(e, ast.Name):
            names.append(e.id)
        elif isinstance(e, ast.Attribute):
            names.append(e.attr)  # e.g. builtins.Exception
    return names


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """bare except: 또는 (Exception|BaseException) 를 잡으면 광의."""
    names = _handler_names(handler)
    if not names and handler.type is None:
        return True  # bare
    return any(n in _BROAD_NAMES for n in names)


def _call_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _is_pass_only(handler: ast.ExceptHandler) -> bool:
    def _trivial(stmt: ast.stmt) -> bool:
        if isinstance(stmt, ast.Pass):
            return True
        # `...` (Ellipsis) 및 bare 문자열 docstring 도 no-op.
        return (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
        )
    return all(_trivial(s) for s in handler.body)


def _body_is_silent(handler: ast.ExceptHandler) -> bool:
    """body 가 실패를 삼키는가 — raise/로깅/예외변수-참조 중 하나라도 있으면 아님.

    예외를 바인딩(`except X as e`)하고 body 에서 `e` 를 참조하면 **다루는 중**이다
    (`results.append(f"{type(e).__name__}")` 처럼 표면화·포맷·기록). 이건 로깅
    함수명 화이트리스트로는 못 잡는 표면화라 별도 판별한다 — hook 파일의
    report-and-continue 관용구 오탐을 막는다.
    """
    if handler.name:
        for stmt in handler.body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and node.id == handler.name:
                    return False
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return False
            if isinstance(node, ast.Call):
                name = _call_name(node).lower()
                if name and any(h in name for h in _LOG_HINTS):
                    return False
    return True


def _suppressed(handler: ast.ExceptHandler, src_lines: list[str]) -> bool:
    last = handler.lineno
    for stmt in handler.body:
        last = max(last, getattr(stmt, "end_lineno", None) or stmt.lineno)
    # handler.lineno(1-based) .. last(1-based) 를 0-based 로 순회.
    for i in range(handler.lineno - 1, last):
        if 0 <= i < len(src_lines) and SUPPRESS_MARKER in src_lines[i]:
            return True
    return False


def silent_excepts(source: str) -> list[tuple[int, str]]:
    """소스에서 broad-silent except 를 찾는다.

    반환: `(lineno, reason)` 리스트. reason ∈ {"pass-only", "no-raise/no-log"}.
    파싱 불가(SyntaxError)면 빈 목록 — 판정 보류(호출부가 syntax 오류를 따로 본다).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    src_lines = source.splitlines()
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_broad(node):
            continue
        if not _body_is_silent(node):
            continue
        if _suppressed(node, src_lines):
            continue
        reason = "pass-only" if _is_pass_only(node) else "no-raise/no-log"
        out.append((node.lineno, reason))
    out.sort()
    return out


def _unquote_diff_path(path: str) -> str:
    """git 이 따옴표로 감싼 diff 경로를 원래 경로로 되돌린다.

    git 은 비ASCII·공백·특수문자가 든 경로를 `"b/src/\\355\\225\\234\\352\\270\\200.jsx"`
    처럼 **따옴표 + 8진 이스케이프**로 낸다(`core.quotepath` 기본값 true).
    이걸 그대로 두면 `startswith("b/")` 가 False 라 `b/` 접두사가 안 떨어지고 키가
    어긋난다 → ratchet 소비자가 **모든 위반을 '레거시'로 오분류해 조용히 통과**시킨다
    (한글 파일명 하나로 게이트가 통째로 무력화된다).

    호출측이 `-c core.quotepath=false` 를 주면 8진 이스케이프는 사라지지만 공백·따옴표가
    든 경로는 여전히 따옴표로 감싸이므로, 두 경우를 모두 여기서 처리한다.
    """
    if not (path.startswith('"') and path.endswith('"') and len(path) >= 2):
        return path
    body = path[1:-1]
    # C 스타일 이스케이프 해제: \nnn(8진) → 바이트, \" \\ \t \n 등 → 리터럴.
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.extend(ch.encode("utf-8"))
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if nxt and nxt in "01234567" and len(body) >= i + 4:
            try:
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            except ValueError:
                pass
        out.extend({"n": b"\n", "t": b"\t", "r": b"\r"}.get(nxt, nxt.encode("utf-8")))
        i += 2
    return out.decode("utf-8", errors="replace")


def _iter_added_lines(diff: str) -> dict[str, set[int]]:
    """`git diff -U0` 출력을 파싱해 파일별 **추가된 라인 번호**(신 파일 기준) 집합.

    ratchet 용 — net-new 침묵만 걸러내려 소비자(quality_check)가 쓴다. 여기 둬서
    hunk 파싱을 한 곳에서만 유지한다.
    """
    added: dict[str, set[int]] = {}
    cur: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = _unquote_diff_path(line[4:].strip())
            if path.startswith("b/"):
                path = path[2:]
            cur = None if path == "/dev/null" else path
            added.setdefault(cur, set()) if cur else None
        elif line.startswith("@@") and cur is not None:
            # 형식: @@ -a,b +c,d @@  (,d 생략 시 1)
            try:
                plus = line.split("+", 1)[1].split(" ", 1)[0]
                start_s, _, count_s = plus.partition(",")
                start = int(start_s)
                count = int(count_s) if count_s else 1
            except (ValueError, IndexError):
                continue
            for ln in range(start, start + count):
                added[cur].add(ln)
    return added


def main(argv: list[str] | None = None) -> int:
    import sys
    from pathlib import Path

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: _silence_check.py <file.py> [...]", file=sys.stderr)
        return 2
    found = 0
    for a in args:
        p = Path(a)
        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            print(f"{a}: read error ({type(e).__name__})", file=sys.stderr)
            continue
        for lineno, reason in silent_excepts(source):
            found += 1
            print(f"{a}:{lineno}: broad-silent except ({reason})")
    if not found:
        print("침묵 except 없음 (또는 전부 면제됨)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
