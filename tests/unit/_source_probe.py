"""구조 가드가 보는 소스를 **지금 파일에서 이름으로** 꺼낸다.

## `inspect.getsource` 를 왜 안 쓰나

`inspect.getsource(fn)` 은 **import 당시** 코드 객체의 `co_firstlineno` 를 **지금 디스크에
있는 파일**에 적용한다. 두 시점이 어긋나면 — 게이트가 도는 6분 동안 다른 세션이 그 `.py`
를 저장하면 — 시작 줄이 밀려 **바로 앞 함수의 소스가 조용히** 돌아온다.

2026-08-25 실측: 커밋 게이트 중 `backend/routers/local.py` 가 저장돼
`test_sds_and_uds_reads_are_not_confined` 가 "쓰기 봉인이 사라졌다"로 실패했다. 봉인은
멀쩡했고 가드가 **다른 함수**를 보고 있었다. 거짓 실패는 거짓 통과의 쌍둥이다 — 사람이
게이트를 믿지 않게 만들고 `--no-verify` 로 가는 길을 낸다.

`linecache` 경로도 완전하진 않다: `checkcache` 는 (mtime, size) 로만 판단하므로 **같은
크기로 같은 초에 다시 쓰인** 파일은 stale 캐시가 그대로 나온다. 모듈 단위 조회도 이
창에서는 낡은 내용을 낼 수 있다.

## 이 모듈이 내는 답

**"지금 파일에 있는, 그 이름의 정의"**. 줄 번호를 안 쓰므로 밀림에 면역이고, 파일을 직접
읽으므로 stale 캐시도 안 탄다. 성질이 다르다는 걸 알고 쓸 것:

  - `inspect.getsource` = "**import 된** 그 코드" (어긋날 수 있는 방식으로)
  - `source_of`         = "**지금 파일에 있는** 그 이름의 정의"

구조 가드는 후자가 맞다 — 검사 대상이 *커밋될 파일의 현재 내용* 이기 때문이다. 반대로
"런타임에 실제로 로드된 코드" 를 봐야 하는 검사에는 쓰면 안 된다(그런 검사는
`inspect.getsource` 를 쓰고 `# getsource-ok: <사유>` 를 달 것).

⚠ 조용한 폴백은 두지 않는다. 이름을 못 찾거나 같은 자리에 동명이인이 있으면 **명시적으로
   실패**한다 — 폴백은 "검사한 줄 알았는데 안 한" 상태를 만든다.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Iterator

__all__ = ["SourceProbeError", "source_of"]

# 새 스코프를 만들지 **않는** 컨테이너. 조건부 정의(`if TYPE_CHECKING:`,
# `try: ... except ImportError:`)가 흔해서 한 겹 안까지 본다.
_TRANSPARENT = (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class SourceProbeError(RuntimeError):
    """소스를 **단정할 수 없을 때** 낸다. 조용히 다른 답을 내지 않기 위한 것."""


def _scope_defs(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """이 스코프에 속한 정의를 낸다. 중첩 클래스/함수 **안으로는 안 들어간다**."""
    for node in body:
        if isinstance(node, _DEFS):
            yield node
        elif isinstance(node, _TRANSPARENT):
            yield from _scope_defs(node.body)
            yield from _scope_defs(getattr(node, "orelse", []))
            for handler in getattr(node, "handlers", []):
                yield from _scope_defs(handler.body)
            yield from _scope_defs(getattr(node, "finalbody", []))


def _resolve(body: list[ast.stmt], name: str, path: str, qualname: str) -> ast.stmt:
    hits = [n for n in _scope_defs(body) if n.name == name]  # type: ignore[attr-defined]
    if not hits:
        raise SourceProbeError(
            f"{qualname}: {path} 안에 `{name}` 정의가 없다 — 이름이 바뀌었거나 다른 "
            "파일로 옮겨졌다. 가드가 무엇을 보는지 다시 잡을 것")
    if len(hits) > 1:
        raise SourceProbeError(
            f"{qualname}: {path} 의 같은 자리에 `{name}` 정의가 {len(hits)}개다 — 어느 "
            "쪽인지 단정하지 않는다")
    return hits[0]


def source_of(obj: Any) -> str:
    """`obj`(모듈/함수/메서드/클래스)의 소스를 **현재 파일 기준**으로 돌려준다.

    데코레이터가 있으면 `inspect.getsource` 와 같이 `@` 줄부터 포함한다. 들여쓰기는
    원문 그대로 둔다(호출부가 `inspect.cleandoc`/`ast.parse` 를 직접 하는 곳이 있다).
    """
    target = inspect.unwrap(obj)          # functools.wraps 데코레이터를 따라간다
    path = inspect.getsourcefile(target)
    if not path:
        raise SourceProbeError(f"{obj!r}: 소스 파일을 못 찾았다 (C 확장/빌트인?)")
    src = Path(path).read_text(encoding="utf-8")
    if inspect.ismodule(target):
        return src

    qualname = getattr(target, "__qualname__", "") or getattr(target, "__name__", "")
    if not qualname:
        raise SourceProbeError(f"{obj!r}: 이름이 없다 — 이름으로는 못 찾는다")
    if "<locals>" in qualname:
        raise SourceProbeError(
            f"{qualname}: 함수 안에 중첩된 정의는 이름으로 못 찾는다 — 바깥 함수를 볼 것")

    try:
        tree: Any = ast.parse(src)
    except SyntaxError as exc:
        raise SourceProbeError(
            f"{path}: 지금 파싱이 안 된다 (line {exc.lineno}). 다른 세션이 저장하는 중이면 "
            "일시적이다 — 코드 결함으로 단정하기 전에 파일 상태부터 볼 것") from exc

    node: Any = tree
    for part in qualname.split("."):
        node = _resolve(node.body, part, path, qualname)

    lines = src.splitlines(keepends=True)
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))]) - 1
    return "".join(lines[start:node.end_lineno])
