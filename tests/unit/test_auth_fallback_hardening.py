"""인증 폴백 하드닝 — `X-User` 헤더가 신원이 되던 표면.

## 실측한 것 (2026-08-04)

`DEV_MODE_X_USER_FALLBACK=1`(당시 `.env:65`) 상태에서 **헤더 한 줄**로:

    GET /api/quality/runs   (헤더 없음)          -> 401 AUTH_REQUIRED
    GET /api/quality/runs   X-User: nobody       -> 403 ADMIN_REQUIRED
    GET /api/quality/runs   X-User: <admin 이름>  -> **200**   ← 인증 우회
    GET /api/auth/me        X-User: <admin 이름>  -> 200 is_admin=True  ← 계정명 oracle

열리는 admin 라우트는 27개이고 그중에 `/api/swut/sutr/build`·`/api/swit/sitr/build`·
`/api/swreport/summary/build` 같은 **ISO 26262 evidence 생성기**가 있다.
`backend/dependencies/admin.py:6` 이 스스로 *"admin만 evidence 생성 가능"* 이라 적어둔
불변식이 헤더 하나로 무너진다. 게다가 X-User 경로는 `token_version` 검사를 구조적으로
안 타므로 **누가 만든 evidence 인지 사후 판별이 안 되고 취소도 안 된다**.

## 조치 (사용자 결정: 끈다)

1. `.env` 의 값을 0 으로 — untracked 라 커밋되지 않으므로 여기서 검증할 수 없다.
   대신 **켜졌을 때 조용하지 않도록** 기동 경고를 넣고, 그 경고의 존재를 여기서 잠근다.
2. `.env.example` 을 주석이 아니라 **명시적 `=0`** 으로.
3. best-effort 경로(`/api/auth/me`)의 **비대칭 제거** — 깨진 Bearer + `X-User: <admin>` 이
   엄격 경로에선 401 인데 여기선 200 이었다.
4. `allowed_users.json` 파싱 실패를 **경고 없이 제한 해제**로 접던 것 정정(값은 유지, 로그 추가).

⚠ 폴백 자체를 코드에서 지우지는 않았다 — 개발 편의(토큰 없이 curl)가 실재하고,
   사용자 결정은 "끈다" 였지 "제거한다" 가 아니다. 되켜지는 것을 **침묵시키지 않는** 쪽으로 막는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit._source_probe import source_of

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestBestEffortPathIsNotMoreLenientThanStrict:
    """같은 입력에 두 판정이 갈리면 관대한 쪽이 곧 우회로다."""

    def test_broken_bearer_does_not_fall_back_to_x_user(self):
        import backend.user_context as uc

        source = source_of(uc.UserContextMiddleware.dispatch)
        assert "if user is None and err is None and is_dev_mode_x_user_fallback_enabled():" in source, (
            "best-effort 경로가 JWT 오류(`err`)를 무시하고 X-User 로 내려간다 — "
            "엄격 경로가 401 로 막는 조합(깨진 Bearer + X-User: <admin>)이 여기서 통과한다"
        )

    def test_strict_path_still_rejects_broken_bearer(self):
        """대조군 — 엄격 경로의 기존 동작이 그대로인지."""
        import backend.user_context as uc

        source = source_of(uc.UserContextMiddleware.dispatch)
        assert "TOKEN_INVALID" in source or "jwt_error" in source


class TestFallbackIsNeverSilent:
    """플래그는 untracked `.env` 한 줄이라 조용히 되살아난다."""

    def test_startup_warns_when_fallback_is_enabled(self):
        """⚠ **문자열 존재만 보면 안 된다.** 처음엔 `"is_dev_mode_..." in main_py` 로
        확인했는데, 조건을 `if False:` 로 바꾸는 뮤테이션이 **살아남았다** — import 줄에
        같은 문자열이 남아 있기 때문이다. 조건문의 **test 표현식**에서 실제로 호출되는지
        AST 로 본다.
        """
        import ast

        main_py = (REPO_ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(main_py)
        guarded = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and any(
                isinstance(c, ast.Call)
                and getattr(c.func, "id", getattr(c.func, "attr", ""))
                == "is_dev_mode_x_user_fallback_enabled"
                for c in ast.walk(node.test)
            )
        ]
        assert guarded, (
            "기동 시 폴백 상태를 **조건으로** 확인하지 않는다 — 켜진 채로 운영돼도 아무도 모른다"
        )
        assert "DEV_MODE_X_USER_FALLBACK 이 켜져 있다" in main_py

    def test_warning_names_the_actual_consequence(self):
        """'개발용입니다' 로는 부족하다 — 무엇이 뚫리는지 말해야 한다."""
        main_py = (REPO_ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        idx = main_py.find("DEV_MODE_X_USER_FALLBACK 이 켜져 있다")
        window = main_py[idx : idx + 400]
        assert "admin" in window and "게이트" in window


class TestExampleDeclaresTheValue:
    def test_env_example_sets_it_explicitly_to_zero(self):
        """주석이면 파일만 봐서는 무엇이 적용 중인지 알 수 없다."""
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()]
        assert "DEV_MODE_X_USER_FALLBACK=0" in lines, (
            ".env.example 이 값을 명시하지 않는다 — 실제로 이 저장소 .env 에 =1 이 "
            "덧붙어 오래 남아 있었다"
        )
        assert "# DEV_MODE_X_USER_FALLBACK=1" not in lines


class TestAllowedUsersFailOpenIsReported:
    """빈 목록=제한없음은 의도지만, **파싱 실패까지** 같은 값으로 접으면 안 된다."""

    def _load(self, monkeypatch, tmp_path, payload: str):
        import backend.user_context as uc

        p = tmp_path / "allowed_users.json"
        p.write_text(payload, encoding="utf-8")
        monkeypatch.setattr(uc, "_ALLOWED_USERS_PATH", p)
        return uc._load_allowed_users()

    def test_valid_list_restricts(self, monkeypatch, tmp_path):
        assert self._load(monkeypatch, tmp_path, json.dumps(["a", "b"])) == {"a", "b"}

    def test_empty_list_is_no_restriction(self, monkeypatch, tmp_path):
        assert self._load(monkeypatch, tmp_path, "[]") is None

    def test_corrupt_file_is_no_restriction_but_warns(self, monkeypatch, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            result = self._load(monkeypatch, tmp_path, "{ not json")
        assert result is None, "동작은 그대로 — 되돌리면 운영이 잠긴다"
        assert any("제한이 **해제된 상태**" in r.getMessage() for r in caplog.records), (
            "손상된 파일이 경고 없이 제한을 해제한다 — 이 저장소의 fail-open 패턴"
        )

    def test_wrong_type_is_no_restriction_but_warns(self, monkeypatch, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            result = self._load(monkeypatch, tmp_path, json.dumps({"users": ["a"]}))
        assert result is None
        assert any("list 가 아니다" in r.getMessage() for r in caplog.records)


class TestFallbackOffActuallyCloses:
    """폴백이 꺼지면 세 표면이 전부 401 인지 — **실제 요청**으로."""

    @pytest.fixture
    def client(self, monkeypatch):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        # ⚠ conftest autouse 가 이 값을 "1" 로 세팅한다(그래서 스위트 전체가 X-User 로 돈다).
        #    이 클래스만 **끈 상태**를 재현한다.
        monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", "0")
        from backend.main import app

        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("get", "/api/quality/runs", None),
            ("post", "/api/local/editor/read", {"project_root": ".", "rel_path": ".env"}),
            ("post", "/api/scm/register", {"id": "x", "scm_type": "svn",
                                           "scm_url": "svn://x", "source_root": "C:/tmp"}),
        ],
    )
    def test_x_user_alone_is_rejected(self, client, method, path, body):
        """admin 이름을 알아도 401 — 토큰이 신원의 유일한 근거가 된다."""
        for name in ("nobody", "hbrnd2", "admin"):
            # `TestClient.get` 은 `json=` 을 안 받는다 — 메서드별로 인자를 가른다.
            kwargs = {"headers": {"X-User": name}}
            if body is not None:
                kwargs["json"] = body
            res = getattr(client, method)(path, **kwargs)
            assert res.status_code == 401, (
                f"{method.upper()} {path} 가 `X-User: {name}` 로 {res.status_code} 를 냈다 — "
                "폴백이 꺼졌는데 헤더가 여전히 신원으로 통한다"
            )

    def test_auth_me_no_longer_leaks_the_admin_name(self, client):
        res = client.get("/api/auth/me", headers={"X-User": "hbrnd2"})
        assert res.status_code == 200, "/api/auth/me 는 best-effort 라 401 이 아니다"
        body = res.json()
        assert body.get("is_admin") is False, "admin 계정명 oracle 이 살아 있다"
        assert body.get("authenticated") is False
        assert not body.get("username")
