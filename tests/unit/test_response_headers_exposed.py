"""라우터가 보내는 커스텀 헤더는 브라우저가 **읽을 수 있어야** 한다. (R39 N2)

## 왜 이 가드가 있나

CORS 에서 `expose_headers` 에 없는 응답 헤더는 `res.headers.get(...)` 이 **조용히 `null`** 이 된다 —
서버는 정상으로 보내고, 네트워크 탭에도 보이고, 오직 스크립트만 못 읽는다. 실패가 아니라 부재라서
화면은 "빌드가 요약을 안 줬다" 로 읽고, 로그에는 아무것도 안 남는다.

실측(2026-09-08): 라우터가 발행하는 X- 헤더 **13종**인데 노출 목록엔 **4개**뿐이었고, 겹치는 건
`X-SwUT-Summary` **하나**였다. 즉 SwIT·SwReport·SwSA 의 요약·경고와 SwUT 의 경고·미완성 시트가
**통째로 사라지는** 구성이 있었다. 그런데 `main.py` 주석은 "커스텀 상태 헤더를 프론트가 읽게 노출"
이라고 적혀 **사실 행세**를 하고 있었다.

지금 개발 구성에서 안 보이는 이유는 vite proxy(`/api` → 9000) 덕에 **same-origin** 이기 때문이다.
`frontend-v2/public/config.js` 는 **재빌드 없이** `window.__ARIA_API_BASE__` 를 바꾸도록 설계된
파일이고 주석이 split deployment 예시까지 준다 — 그 한 줄이면 발화한다.

## 무엇을 재나

"라우터가 실제로 발행하는 헤더" 를 **AST 로 전수** 걷어 목록과 대조한다. 손으로 든 목록은 빠진다는
것을 이 저장소가 R38 에서 다시 확인했으므로(격리 표에서 `impact_jobs` 누락), 목록을 사람이 세지 않는다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ROUTERS = _REPO / "backend" / "routers"

#: 노출하지 않아도 되는 헤더 — **사유가 있어야 한다**(`test_skip_list_has_reasons`).
_NOT_EXPOSED_OK = {
    # 표준 헤더는 CORS 가 기본 노출한다(safelisted response header).
    "Content-Length": "CORS safelist — 명시 노출 불필요",
}


def _headers_emitted_by_routers() -> dict[str, set[str]]:
    """라우터가 응답에 싣는 `X-*` 헤더 전수 → `{헤더: {파일}}`.

    두 형태를 모두 본다 — dict 리터럴(`{"X-Foo": v}`)과 첨자 대입(`headers["X-Foo"] = v`).
    앞판 조사가 정규식으로 dict 형태만 봐서 `jenkins.py` 의 `X-Swit-*` 를 놓쳤다.
    문자열 리터럴이 아니라 **키로 쓰인 자리**만 세므로 주석·docstring 언급은 걸리지 않는다.
    """
    found: dict[str, set[str]] = {}
    for path in _ROUTERS.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                            and key.value.startswith("X-")):
                        found.setdefault(key.value, set()).add(path.name)
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                v = node.slice.value
                if isinstance(v, str) and v.startswith("X-"):
                    found.setdefault(v, set()).add(path.name)
    # ⚠ **헬퍼가 만드는 헤더는 라우터 AST 에 이름이 없다.** `quality_run_headers()` 는 dict 를
    #   통째로 돌려주므로 위 스캔이 못 본다 — 그대로 두면 "아무도 안 보낸다"(dead) 로 오판한다.
    #   실제로 이 가드를 처음 돌렸을 때 그렇게 실패했다. 호출하는 파일을 발행처로 센다.
    from workflow.quality.recorder import QUALITY_RUN_HEADER
    for path in _ROUTERS.glob("*.py"):
        if "quality_run_headers(" in path.read_text(encoding="utf-8", errors="replace"):
            found.setdefault(QUALITY_RUN_HEADER, set()).add(path.name)
    return found


def _exposed() -> list[str]:
    from backend.main import EXPOSED_RESPONSE_HEADERS
    return list(EXPOSED_RESPONSE_HEADERS)


class TestEveryEmittedHeaderIsReadable:
    def test_scan_is_not_vacuous(self):
        """스캔이 비면 아래 대조가 전부 통과한다 — 그건 가드가 아니다."""
        emitted = _headers_emitted_by_routers()
        assert len(emitted) >= 10, f"라우터 X- 헤더를 {len(emitted)}종밖에 못 찾았다 — 스캔이 깨졌다"

    def test_no_emitted_header_is_invisible_to_the_browser(self):
        """발행하는데 노출 안 된 헤더 = **cross-origin 에서 조용히 사라지는 값**."""
        emitted = _headers_emitted_by_routers()
        exposed = {h.lower() for h in _exposed()}
        missing = {
            h: sorted(files) for h, files in emitted.items()
            if h.lower() not in exposed and h not in _NOT_EXPOSED_OK
        }
        assert not missing, (
            "라우터가 보내는데 `expose_headers` 에 없다 — cross-origin 구성에서 프론트가 못 읽는다:\n  "
            + "\n  ".join(f"{h} ({', '.join(f)})" for h, f in sorted(missing.items()))
            + "\n→ backend/main.py 의 `EXPOSED_RESPONSE_HEADERS` 에 추가할 것"
        )

    def test_no_dead_entry_in_the_exposed_list(self):
        """아무도 안 보내는 헤더가 목록에 남아 있으면, 그 줄은 **없는 계약**을 설명한다."""
        emitted_lower = {h.lower() for h in _headers_emitted_by_routers()}
        dead = [
            h for h in _exposed()
            if h.startswith("X-") and h.lower() not in emitted_lower
        ]
        assert not dead, (
            f"`expose_headers` 에 있는데 어느 라우터도 안 보낸다: {dead}\n"
            "→ 발행이 사라졌으면 목록에서도 지울 것(낡은 줄은 있는 것처럼 읽힌다)"
        )

    def test_skip_list_has_reasons(self):
        """예외에는 **사유**가 있어야 한다 — 사유 없는 예외는 곧 잊히고, 잊힌 예외는 가드를 지운다."""
        for name, why in _NOT_EXPOSED_OK.items():
            assert why and len(why) > 5, f"{name}: 예외 사유가 비어 있다"


class TestTheQualityRunHeaderIsWired:
    """(R39 N1) 빌드 응답이 "이 파일이 어느 run 인가" 를 말한다 — 검토 기록과 잇는 유일한 단서."""

    def test_header_name_is_single_sourced(self):
        """이름을 두 곳에 적으면 한쪽만 바뀐다 — 노출 목록은 recorder 의 상수를 따른다."""
        from workflow.quality.recorder import QUALITY_RUN_HEADER
        assert QUALITY_RUN_HEADER in _exposed(), (
            f"{QUALITY_RUN_HEADER} 가 노출 목록에 없다 — cross-origin 에서 run id 를 못 읽는다"
        )

    @pytest.mark.parametrize(("value", "expect"), [
        (7, "7"),
        (1234, "1234"),
        (None, "unrecorded"),       # 기록 실패(non-fatal except)
        (-1, "unrecorded"),         # 옛 skip 관용
        (0, "unrecorded"),
        ("x", "unrecorded"),        # 예상 못 한 타입도 침묵하지 않는다
    ])
    def test_failure_is_named_not_omitted(self, value, expect):
        """헤더를 **빼지 않는다** — 부재는 '옛 서버' 와 구별되지 않아 화면이 두 상태를 한 칸에 그린다."""
        from workflow.quality.recorder import QUALITY_RUN_HEADER, quality_run_headers
        out = quality_run_headers(value)
        assert out[QUALITY_RUN_HEADER] == expect

    def test_every_build_router_sends_it(self):
        """빌드 응답을 만드는 라우터 4곳이 **전부** 이 헤더를 싣는다(한 곳이 빠지면 그 문서만 못 잇는다)."""
        emitted = _headers_emitted_by_routers()
        # 헬퍼(`headers.update(quality_run_headers(...))`)를 쓰므로 AST 키 스캔에는 안 잡힌다 —
        # 호출 자체를 센다.
        callers = set()
        for path in _ROUTERS.glob("*.py"):
            src = path.read_text(encoding="utf-8", errors="replace")
            if "quality_run_headers(" in src:
                callers.add(path.name)
        assert callers >= {"swut.py", "swit.py", "swreport.py", "swsa.py"}, (
            f"이 헤더를 싣지 않는 빌드 라우터가 있다: 실제 {sorted(callers)}"
        )
        assert emitted, "스캔 자체가 비었다"
