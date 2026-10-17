"""소스 루트 문자열 분해 — **단일 출처** (R47 N24, 2026-09-10).

## 왜 이 모듈이 생겼나

`source_root` 는 레지스트리·폼·환경변수에서 "복수 경로를 한 문자열" 로 온다
(실측 2026-08-07: 레지스트리 3항목 전부 `"D:/…/PDS64_RD,D:\\…\\PDS64_FBL"` 꼴).
그 문자열을 조각내는 코드가 저장소에 **30곳** 있었고 규약이 **두 갈래**였다:

- `replace(";", ",").split(",")` — 콤마·세미콜론 둘 다(생성기·시그니처·SVN 조회)
- `.split(",")` 만 — 콤마만(라우터 `_first_root` 17곳 · 주석 커버리지 3곳 · 레지스트리 조회 1곳)

같은 값이 입구마다 다르게 잘리면 세미콜론으로 이은 프로젝트는 생성기에선 두 루트가
보이는데 라우터 존재 검사에선 `"D:/a;D:/b"` 통짜가 되어 **없는 경로**가 된다 — R46 이
콤마 결합 문자열의 `exists()` 로 함수 0개 문서를 만든 것과 같은 결함 형태다.

## 계약

- 구분자는 콤마와 세미콜론, 앞뒤 공백 제거, 빈 조각 제거, **원문 순서 유지**.
- 같은 문자열이 반복되면 한 번만(정확 일치만 — 대소문자·슬래시 정규화는 하지 않는다.
  경로 동일성은 `scm_registry._normalize_path_key` 같은 소비처 몫이다).
- `first_source_root("")` 는 `""` — 존재 여부는 여기서 판정하지 않는다
  (`backend.helpers.uds._existing_source_roots` 가 그 층이다).

가드: `tests/unit/test_source_roots_single_source.py` 가 저장소를 훑어 이 모듈 밖의
분해 코드를 막는다.

## 경로 동일성 (R97)

`normalize_root_key` 는 `scm_registry._normalize_path_key` 가 쓰던 정규화(normcase+normpath)를 그대로 옮긴 것이다 —
레지스트리는 이제 이 함수에 위임한다. 프로젝트 맵(`report_gen.project_maps`)이 "이 생성 루트가 어느 프로젝트의 것인가"
를 레지스트리 조회와 **같은 정규화**로 판정해야 `D:/A` 와 `d:\\a\\` 가 한쪽에서만 같은 경로가 되는 일이 없다
(R47 이 분해 규약 두 갈래에서 겪은 결함과 같은 모양이다). 분해(`split_source_roots`)와 달리 이 함수는 조각 하나만 받는다.
"""
from __future__ import annotations

import os
from typing import Iterable, List

__all__ = ["split_source_roots", "first_source_root", "join_source_roots", "normalize_root_key", "SEPARATORS"]

#: 허용 구분자 — 새 구분자를 더할 일이 생기면 여기 한 곳이다.
SEPARATORS: tuple[str, ...] = (",", ";")


def split_source_roots(raw: object) -> List[str]:
    """`"D:/a, D:\\b;D:/a"` → `["D:/a", "D:\\b"]`."""
    text = str(raw or "")
    for sep in SEPARATORS[1:]:
        text = text.replace(sep, SEPARATORS[0])
    out: List[str] = []
    seen: set[str] = set()
    for piece in text.split(SEPARATORS[0]):
        p = piece.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def first_source_root(raw: object) -> str:
    """첫 루트(없으면 빈 문자열). 라우터의 존재 검사·모듈명 추정이 쓴다."""
    roots = split_source_roots(raw)
    return roots[0] if roots else ""


def join_source_roots(roots: Iterable[str]) -> str:
    """생성기에 넘길 표준 결합 — 콤마."""
    return SEPARATORS[0].join(r for r in (str(x).strip() for x in roots) if r)


def normalize_root_key(text: object) -> str:
    """경로 비교용 정규화 — 대소문자·구분자·후행 슬래시 차이를 흡수(`"D:/A"` 와 `"d:\\a\\"` 가 같은 키).

    `scm_registry._normalize_path_key` 의 본문을 바이트 단위로 옮겼다(그쪽은 이제 여기에 위임한다). 동작을 바꾸려면
    레지스트리 조회 · 프로젝트 맵 판정이 같이 바뀐다는 뜻이다.
    """
    s = str(text or "").strip().strip('"').strip("'")
    if not s:
        return ""
    try:
        return os.path.normcase(os.path.normpath(s))
    except (TypeError, ValueError):
        # normpath 는 embedded null 같은 병적 입력에만 던진다. 값을 버리지 않고
        # 손수 정규화한 결과를 돌려주므로 판정이 사라지지 않는다(침묵 아님).
        return s.replace("\\", "/").rstrip("/").lower()
