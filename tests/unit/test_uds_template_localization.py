# tests/unit/test_uds_template_localization.py
"""UDS 템플릿이 **생성기가 열 수 있는 경로**로 넘어가는가.

## 왜 이 파일이 생겼나 (2026-09-01 실측)

UDS 생성은 서브프로세스에서 `docx.Document(path)` 로 템플릿을 **직접** 연다. 그래서
cloudium worker 가 닿지 않고, `U:` 경로를 그대로 넘기면 재시도 3단계가 전부
`PackageNotFoundError` 로 죽는다. 가정이 아니라 남아 있는 기록의 마지막 줄이다:

    docx.opc.exceptions.PackageNotFoundError: Package not found at
    'U:/연구소/…/04.SW 단위 설계/01.SwUDS/(XXXX_SwUDS) Software Unit Design…docx'

라운드 7이 jenkins 쪽 UDS 2곳을 `resolve_template_for`(= worker 경유 로컬 tmp)로
배선했는데 `/api/local/uds/generate` **한 곳만** 원 경로를 그대로 넘기고 있었다.
등록본이 로컬 `D:` 이고 프론트 호출처가 0곳이라 잠복해 있었을 뿐이다.

## 규약

- 해석 실패는 `None`(= 템플릿 없이 생성)이다. **원 경로를 흘려보내지 않는다** —
  그러면 같은 실패가 하류에서 나고 사유만 사라진다.
- 라우터는 로컬화하지 않는 형제(`resolve_registered_uds_template`)를 **부르지 않는다**.
  그 함수는 `helpers` 안에서만 쓰인다.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any, List

import pytest

from backend.helpers import uds as uds_helpers

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ROUTERS = _REPO / "backend" / "routers"

RAW = "resolve_registered_uds_template"
LOCALIZED = "resolve_registered_uds_template_local"
CLOUD_TPL = "U:/연구소/2200 개발 사양/01.SwUDS/(XXXX_SwUDS) Software Unit Design.docx"


class TestTheHelperLocalizes:
    def test_cloudium_path_is_handed_to_the_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: List[Any] = []

        def fake_resolve(path_str: str, **kw: Any) -> str:
            seen.append(path_str)
            return r"C:\tmp\localized\tpl.docx"

        monkeypatch.setattr(uds_helpers, RAW, lambda: CLOUD_TPL)
        monkeypatch.setattr("backend.services.resolver_helpers.resolve_builder_input",
                            fake_resolve)
        got = uds_helpers.resolve_registered_uds_template_local()
        assert seen == [CLOUD_TPL], "resolver 를 거치지 않았다"
        assert got == r"C:\tmp\localized\tpl.docx"

    def test_unresolvable_is_none_not_the_raw_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """이 한 줄이 이 파일의 핵심이다 — 원 경로가 새어 나가면 08-10·08-11 재현이다."""
        monkeypatch.setattr(uds_helpers, RAW, lambda: CLOUD_TPL)
        monkeypatch.setattr("backend.services.resolver_helpers.resolve_builder_input",
                            lambda *a, **k: None)
        assert uds_helpers.resolve_registered_uds_template_local() is None

    def test_no_registration_does_not_call_the_resolver(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """등록이 없는 것은 실패가 아니다 — 조회 자체를 하지 않는다."""
        calls: List[Any] = []
        monkeypatch.setattr(uds_helpers, RAW, lambda: "")
        monkeypatch.setattr("backend.services.resolver_helpers.resolve_builder_input",
                            lambda *a, **k: calls.append(a) or "nope")
        assert uds_helpers.resolve_registered_uds_template_local() is None
        assert calls == []

    def test_local_path_survives_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """local 모드에서는 직독이 정답이다 — 사본을 만들지 않는다(resolver 계약)."""
        local = str(_REPO / "docs")
        monkeypatch.setattr(uds_helpers, RAW, lambda: local)
        monkeypatch.setattr("backend.services.resolver_helpers.resolve_builder_input",
                            lambda p, **k: p)
        assert uds_helpers.resolve_registered_uds_template_local() == local


def _called_names(path: pathlib.Path) -> set[str]:
    """그 모듈이 **실제로 부르는** 이름들(AST). 주석·문자열은 세지 않는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


class TestNoRouterUsesTheUnlocalizedSibling:
    def test_routers_never_call_the_raw_resolver(self) -> None:
        """라우터가 부르면 그 경로는 cloudium 에서 죽는다 — 배선이 아니라 **금지**다."""
        offenders = [p.name for p in sorted(_ROUTERS.glob("*.py"))
                     if RAW in _called_names(p)]
        assert offenders == [], (
            f"{offenders} 가 로컬화하지 않는 템플릿 해석을 부른다 — "
            f"`{LOCALIZED}` 또는 `resolve_template_for` 를 쓸 것"
        )

    def test_the_local_uds_endpoint_actually_localizes(self) -> None:
        """금지만으로는 부족하다 — 그 자리에 **대체가 들어갔는지**도 본다."""
        assert LOCALIZED in _called_names(_ROUTERS / "local.py")

    @pytest.mark.parametrize("router", ["jenkins.py", "local.py"])
    def test_every_uds_generation_router_has_a_localizing_call(self, router: str) -> None:
        """UDS 를 만드는 라우터는 셋 중 하나로 템플릿을 해석해야 한다."""
        names = _called_names(_ROUTERS / router)
        assert names & {LOCALIZED, "resolve_template_for", "resolve_builder_input"}, (
            f"{router}: 템플릿을 로컬화하는 호출이 하나도 없다"
        )
