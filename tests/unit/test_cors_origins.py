"""CORS origin 화이트리스트 — drive-by 판독 차단 (2026-08-04 보안 표면 감사).

## 왜 좁혔나

`allow_origins=["*"]` 였다. 그러면 **사용자가 아무 웹페이지만 방문해도** 그 페이지의
스크립트가 `http://localhost:9000` 으로 요청을 보내고 **응답을 읽을 수 있다**(drive-by).
실측 당시 `/api/local/editor/read` 로 `.env`(JWT_SECRET·BOOTSTRAP_ADMIN_PASSWORD 포함)가
그 경로로 나갔다. 그 endpoint 는 이번 라운드에 잠갔지만 `*` 자체가 심층방어를 없앤다.

## LAN 접속은 안 깨진다

프로덕션은 백엔드가 `frontend-v2/dist` 를 **같은 오리진에서 서빙**한다
(`backend/main.py` 의 StaticFiles 마운트). 따라서 `http://<LAN-IP>:9000` 으로 여는
프론트의 API 호출은 **same-origin** 이고 브라우저가 CORS 검사를 아예 하지 않는다.
bind 는 0.0.0.0 유지 — 이 목록은 브라우저 cross-origin **판독**만 제한한다.

cross-origin 이 실제로 필요한 조합은 vite dev(5174)가 원격 백엔드를 볼 때뿐이고,
그건 `DEVOPS_CORS_EXTRA_ORIGINS` 로 넣는다. 배포 host 를 코드에 하드코딩하지 않는다 —
이 저장소는 그 값을 모르고, 모르는 값을 지어내지 않는다.
"""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("fastapi")


def _cors_options(app):
    """앱에 등록된 CORSMiddleware 의 kwargs 를 꺼낸다."""
    from starlette.middleware.cors import CORSMiddleware

    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw.kwargs
    raise AssertionError("CORSMiddleware 가 등록돼 있지 않다")


@pytest.fixture
def app():
    import backend.main as main

    return main.app


class TestWildcardIsGone:
    def test_origins_is_not_star(self, app):
        origins = _cors_options(app)["allow_origins"]
        assert origins != ["*"] and "*" not in origins, (
            "allow_origins 가 `*` 다 — 임의 웹페이지가 localhost:9000 응답을 읽을 수 있다"
        )

    def test_localhost_dev_and_backend_ports_are_allowed(self, app):
        origins = set(_cors_options(app)["allow_origins"])
        for expected in (
            "http://localhost:5174", "http://127.0.0.1:5174",
            "http://localhost:9000", "http://127.0.0.1:9000",
        ):
            assert expected in origins, f"{expected} 가 빠졌다 — 개발/로컬 사용이 깨진다"

    def test_credentials_stay_off(self, app):
        """`allow_credentials=True` + 넓은 origin 조합은 만들지 않는다."""
        assert _cors_options(app)["allow_credentials"] is False

    def test_expose_headers_preserved(self, app):
        """SwUT 요약 등 커스텀 헤더 노출 계약은 유지한다."""
        exposed = set(_cors_options(app)["expose_headers"])
        assert {"Content-Disposition", "X-SwUT-Summary"} <= exposed


class TestExtraOriginsComeFromEnv:
    def test_env_origins_are_appended(self, monkeypatch):
        """배포 host 를 코드에 박지 않고 env 로 받는다."""
        monkeypatch.setenv("DEVOPS_CORS_EXTRA_ORIGINS",
                           "http://192.168.0.10:5174, http://build-host:5174")
        import backend.main as main

        reloaded = importlib.reload(main)
        try:
            origins = set(_cors_options(reloaded.app)["allow_origins"])
            assert "http://192.168.0.10:5174" in origins
            assert "http://build-host:5174" in origins
        finally:
            monkeypatch.delenv("DEVOPS_CORS_EXTRA_ORIGINS", raising=False)
            importlib.reload(main)

    def test_blank_env_does_not_add_empty_origin(self, monkeypatch):
        """빈 문자열이 origin 목록에 들어가면 조용히 이상한 매칭이 생긴다."""
        monkeypatch.setenv("DEVOPS_CORS_EXTRA_ORIGINS", " , ,")
        import backend.main as main

        reloaded = importlib.reload(main)
        try:
            origins = _cors_options(reloaded.app)["allow_origins"]
            assert "" not in origins
            assert all(o.strip() for o in origins)
        finally:
            monkeypatch.delenv("DEVOPS_CORS_EXTRA_ORIGINS", raising=False)
            importlib.reload(main)


class TestSameOriginLanAccessIsUnaffected:
    """LAN 접속이 안 깨지는 **근거**를 값으로 고정한다.

    ⚠ 근거는 "origin 목록에 LAN IP 를 넣었다" 가 아니라 **프론트가 백엔드와 같은
      오리진에서 서빙된다** 는 사실이다. 그 서빙이 사라지면 LAN 사용자는 cross-origin 이
      되고 이 좁힘이 그들을 막는다 — 그때 이 테스트가 알려 준다.
    """

    def test_backend_serves_the_frontend_bundle(self):
        from pathlib import Path

        import backend.main as main

        source = Path(main.__file__).read_text(encoding="utf-8")
        assert 'StaticFiles(directory=str(_frontend_dist / "assets")' in source, (
            "백엔드가 프론트 번들을 서빙하지 않는다 — LAN 접속이 cross-origin 이 되므로 "
            "CORS 목록에 그 host 를 넣어야 한다(DEVOPS_CORS_EXTRA_ORIGINS)"
        )
        assert "_frontend_dist" in source
