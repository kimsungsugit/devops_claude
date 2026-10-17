# tests/unit/test_uds_registered_template.py
"""서버에 **등록된** UDS 템플릿이 실제로 쓰이는지 — 세 생성 경로 공통 계약.

## 왜 이 테스트가 있나

관리자 API(`POST /api/config/uds-template`)가 저장한 템플릿은
`config/uds_template_server_config.json` 에 들어가고 `config.resolve_uds_template_path()`
가 그것을 해석한다. 그런데 `/api/local/uds/generate` 는 템플릿 업로드가 없으면
**그 해석을 건너뛰고 곧장 `UDS_REF_SUDS_PATH`(원본 정본 SUDS)로 폴백**했다.
즉 이 경로에서는 **등록이 아무 효과가 없었다** — 관리자가 무엇을 지정하든 매번
정본 SUDS 가 템플릿으로 쓰였다.

jenkins 동기(`jenkins.py`)·비동기(`helpers/uds.py`)는 빈 문자열을 `... or None` 로
넘겨 `generate_uds_docx` 안에서 `resolve_uds_template_path()` 를 타므로 정상이었다.
**local 경로만 어긋나 있었다** — 같은 판정이 세 곳에 흩어져 한 곳만 틀어진, 이
저장소가 반복해 겪은 형태다.

`config.py` 의 `UDS_TEMPLATE_PATH` 주석도 tokenized 판을 "서버 기본 템플릿" 이라고
말하는데 local 경로가 그 의도를 우회하고 있었다.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


class TestResolutionOrder:
    """`resolve_uds_template_path()` 자체의 우선순위: 등록본 → env → 빈 문자열."""

    def _cfg(self, monkeypatch, tmp_path, payload, *, env_path=""):
        import config

        f = tmp_path / "uds_template_server_config.json"
        if payload is not None:
            f.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(config, "UDS_TEMPLATE_SERVER_CONFIG_PATH", f, raising=False)
        monkeypatch.setattr(config, "UDS_TEMPLATE_PATH", env_path, raising=False)
        return config

    def test_registered_wins(self, monkeypatch, tmp_path):
        tpl = tmp_path / "registered.docx"
        tpl.write_bytes(b"x")
        env = tmp_path / "env.docx"
        env.write_bytes(b"x")
        cfg = self._cfg(monkeypatch, tmp_path, {"template_path": str(tpl)}, env_path=str(env))
        assert cfg.resolve_uds_template_path() == str(tpl)

    def test_env_is_used_when_nothing_registered(self, monkeypatch, tmp_path):
        env = tmp_path / "env.docx"
        env.write_bytes(b"x")
        cfg = self._cfg(monkeypatch, tmp_path, {"template_path": ""}, env_path=str(env))
        assert cfg.resolve_uds_template_path() == str(env)

    def test_registered_path_that_does_not_exist_is_ignored(self, monkeypatch, tmp_path):
        """⚠ 없는 경로를 돌려주면 소비처가 그걸 템플릿으로 열려다 죽는다."""
        env = tmp_path / "env.docx"
        env.write_bytes(b"x")
        cfg = self._cfg(monkeypatch, tmp_path, {"template_path": str(tmp_path / "gone.docx")},
                        env_path=str(env))
        assert cfg.resolve_uds_template_path() == str(env)

    def test_nothing_available_returns_empty(self, monkeypatch, tmp_path):
        """음성 대조군 — 아무것도 없으면 빈 문자열이어야 한다(소비처가 '템플릿 없음'
        으로 읽는다). 여기서 아무 경로나 지어내면 엉뚱한 문서가 나온다."""
        cfg = self._cfg(monkeypatch, tmp_path, None, env_path=str(tmp_path / "absent.docx"))
        assert cfg.resolve_uds_template_path() == ""

    def test_unreadable_config_falls_back_quietly(self, monkeypatch, tmp_path):
        env = tmp_path / "env.docx"
        env.write_bytes(b"x")
        f = tmp_path / "uds_template_server_config.json"
        f.write_text("{ not json", encoding="utf-8")
        import config
        monkeypatch.setattr(config, "UDS_TEMPLATE_SERVER_CONFIG_PATH", f, raising=False)
        monkeypatch.setattr(config, "UDS_TEMPLATE_PATH", str(env), raising=False)
        assert config.resolve_uds_template_path() == str(env)


def _fn_node(rel: str, name: str):
    src = (_ROOT / rel).read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n, src
    raise AssertionError(f"{rel}: {name} 를 못 찾았다")


def _assignments_to(rel: str, name: str, target: str):
    """`target` 에 대입하는 문들을 `(줄번호, 우변 소스)` 로.

    ⚠ 함수 본문을 substring 으로 보면 안 된다 — `UDS_REF_SUDS_PATH` 는 같은 함수 안에서
    **SwCom diff 참조 문서**로도 쓰인다(템플릿과 무관). 처음 이 테스트를 문자열 검색으로
    썼다가 그 등장에 속아 실패했다. 대입문만 본다.
    """
    node, src = _fn_node(rel, name)
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            if target in {t.id for t in n.targets if isinstance(t, ast.Name)}:
                out.append((n.lineno, ast.get_source_segment(src, n.value) or ""))
    return sorted(out)


class TestEveryPathConsultsTheRegistration:
    """세 생성 경로가 **전부** 등록본을 본다. 한 곳만 고치면 그 경로만 어긋난다."""

    def test_local_uses_the_shared_resolver(self):
        """local 핸들러는 판정을 인라인으로 다시 쓰지 말고 헬퍼를 부른다.

        ⚠ 인라인일 때는 가드가 "대입문이 있는가" 같은 **모양**밖에 못 봤고, 분기를
        `if False:` 로 죽이는 뮤테이션 2건이 통째로 살아남았다. 헬퍼로 빼서 아래
        `TestResolverBehaviour` 가 **결과**를 단언한다.

        ⚠ 2026-09-01(라운드 12): 요구 대상이 **로컬화하는 형제**로 바뀌었다. 등록본을
        찾는 것만으로는 부족하다 — 그 경로가 `U:` 면 생성 서브프로세스가 열지 못해
        재시도 3단계가 전부 `PackageNotFoundError` 로 죽는다(실측 08-10·08-11).
        raw 형제를 라우터가 부르는 것 자체는
        `test_uds_template_localization.py::test_routers_never_call_the_raw_resolver`
        가 금지한다 — 여기서는 **대체가 실제로 들어갔는지**를 본다.
        """
        assigns = _assignments_to("backend/routers/local.py", "local_uds_generate", "tpl_path")
        assert any("resolve_registered_uds_template_local()" in rhs for _, rhs in assigns), (
            "local 경로가 공용 해석기를 안 쓴다 — 등록본이 무시되거나, 쓰더라도 "
            "cloudium 경로를 로컬화하지 않아 생성이 죽는다"
        )
        assert not any("UDS_REF_SUDS_PATH" in rhs for _, rhs in assigns), (
            "정본을 tpl_path 에 직접 채우고 있다 — 등록본보다 앞설 위험"
        )

    @pytest.mark.parametrize(
        "rel,name",
        [("backend/routers/jenkins.py", "jenkins_uds_generate"),
         ("backend/helpers/uds.py", "_uds_generate_from_paths")],
    )
    def test_jenkins_paths_pass_empty_through(self, rel, name):
        """jenkins 계열은 빈 값을 `None` 으로 넘겨 `generate_uds_docx` 안에서 해석하게
        한다. 여기서 정본 경로를 직접 채우기 시작하면 local 과 같은 결함이 생긴다."""
        assigns = _assignments_to(rel, name, "tpl")
        assert assigns, f"{name}: 템플릿을 담는 `tpl` 대입이 없다"
        assert any("or None" in rhs for _, rhs in assigns), (
            f"{name}: 빈 템플릿을 None 으로 넘기는 관용구가 사라졌다 — 그러면 "
            "generate_uds_docx 가 등록본을 해석할 기회를 잃는다"
        )
        assert not any("UDS_REF_SUDS_PATH" in rhs for _, rhs in assigns), (
            f"{name}: 정본을 템플릿으로 직접 채우고 있다 — 등록본이 무시된다"
        )

    def test_builder_is_the_single_resolution_point(self):
        """`generate_uds_docx` 가 해석 단일 지점이다 — 여기가 빠지면 전 경로가 죽는다."""
        src = (_ROOT / "report_gen" / "docx_builder.py").read_text(encoding="utf-8")
        assert "resolve_uds_template_path" in src


class TestResolverBehaviour:
    """`resolve_registered_uds_template()` 의 **결과**를 단언한다.

    구조 검사(대입문이 있는가)로는 부족하다 — 분기를 `if False:` 로 죽여도 통과했다.
    """

    def _setup(self, monkeypatch, tmp_path, *, registered="", ref=""):
        import config
        from backend.helpers import uds as uds_mod

        monkeypatch.setattr(config, "resolve_uds_template_path", lambda: registered, raising=False)
        monkeypatch.setattr(config, "UDS_REF_SUDS_PATH", ref, raising=False)
        return uds_mod.resolve_registered_uds_template

    def test_registered_template_is_returned(self, monkeypatch, tmp_path):
        """⚠ 핵심 — 등록본이 있으면 그게 나와야 한다. 이게 안 되면 관리자 지정이 무효다."""
        reg = tmp_path / "registered.docx"
        reg.write_bytes(b"x")
        ref = tmp_path / "reference.docx"
        ref.write_bytes(b"x")
        f = self._setup(monkeypatch, tmp_path, registered=str(reg), ref=str(ref))
        assert f() == str(reg)

    def test_reference_is_used_when_nothing_registered(self, monkeypatch, tmp_path):
        """음성 대조군 — 등록본이 없으면 정본으로 내려가야 한다(템플릿이 통째로
        빠지면 4단계 SUDS 구조가 사라진다)."""
        ref = tmp_path / "reference.docx"
        ref.write_bytes(b"x")
        f = self._setup(monkeypatch, tmp_path, registered="", ref=str(ref))
        assert f() == str(ref)

    def test_nothing_available_returns_empty_not_a_guess(self, monkeypatch, tmp_path):
        f = self._setup(monkeypatch, tmp_path, registered="", ref=str(tmp_path / "gone.docx"))
        assert f() == ""

    def test_resolver_failure_falls_back_and_logs(self, monkeypatch, tmp_path, caplog):
        """등록본 해석이 터져도 생성은 계속돼야 한다 — 단, 조용히는 안 된다."""
        import config

        def _boom():
            raise RuntimeError("boom")

        ref = tmp_path / "reference.docx"
        ref.write_bytes(b"x")
        monkeypatch.setattr(config, "resolve_uds_template_path", _boom, raising=False)
        monkeypatch.setattr(config, "UDS_REF_SUDS_PATH", str(ref), raising=False)
        from backend.helpers import uds as uds_mod

        with caplog.at_level("WARNING", logger="devops_api"):
            assert uds_mod.resolve_registered_uds_template() == str(ref)
        assert "등록 템플릿 해석 실패" in caplog.text

    def test_whitespace_only_registration_is_not_a_path(self, monkeypatch, tmp_path):
        ref = tmp_path / "reference.docx"
        ref.write_bytes(b"x")
        f = self._setup(monkeypatch, tmp_path, registered="   ", ref=str(ref))
        assert f() == str(ref)
