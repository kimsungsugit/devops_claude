"""SPA 진입 문서(index.html)는 캐시하지 않는다 (2026-08-05).

## 왜

vite 빌드는 번들 파일명에 해시를 넣고 **옛 파일을 지운다**. 그래서 새 배포 후
브라우저가 옛 `index.html` 을 캐시로 재사용하면, 거기 적힌 옛 번들은 이미 없어서
404 이거나(빈 화면) 이미 로드된 옛 JS 가 그대로 돈다 — 사용자에게는 **"고쳤다는데
안 바뀐다"** 로 보이고, 하드 새로고침을 알아야만 벗어난다.

실제로 이 세션에서 문서 경로 라이브 반영을 고치고 빌드까지 했는데도 사용자 화면이
그대로였던 것이 이 부류다(그때는 열려 있던 탭이 옛 JS 를 메모리에서 계속 돌렸다).

⚠ "Cache-Control 을 안 보내면 캐시가 안 된다" 는 **틀렸다.** 헤더가 없으면 브라우저는
`Last-Modified` 기반 **휴리스틱 캐싱**을 적용한다(RFC 9111 §4.2.2). 그래서 명시가 필요하다.

## 무엇을 지키나

- `index.html`(및 SPA 폴백 경로) → `no-cache`
- 해시가 붙은 `assets/*` → **캐시 금지를 강요하지 않는다**. 파일명이 곧 버전이라
  오래 캐시되는 편이 맞고, 여기까지 no-cache 를 걸면 매 로드가 재다운로드가 된다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_DIST = REPO / "frontend-v2" / "dist"

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (_DIST / "index.html").exists(),
    reason="frontend-v2/dist 미빌드 — SPA 라우트가 등록되지 않는다",
)


@pytest.fixture(scope="module")
def client():
    from backend.main import app
    return TestClient(app)


def test_spa_entry_is_not_cached(client):
    res = client.get("/")
    assert res.status_code == 200
    cc = res.headers.get("cache-control", "")
    assert "no-cache" in cc.lower(), (
        f"index.html 에 no-cache 가 없다(cache-control={cc!r}) — 브라우저가 휴리스틱 "
        "캐싱으로 옛 진입 문서를 재사용하면 배포가 사용자에게 안 보인다"
    )


def test_spa_fallback_route_is_not_cached(client):
    """딥링크(예: /detail/...)도 같은 index.html 을 준다 — 거기도 no-cache 여야 한다."""
    res = client.get("/some/deep/link")
    assert res.status_code == 200
    assert "no-cache" in res.headers.get("cache-control", "").lower()


def test_api_path_is_not_swallowed_into_index_html(client):
    """API 경로는 SPA 폴백으로 삼켜지지 않는다(기존 계약 — 함께 고정).

    ⚠ 상태코드를 404 로 못 박지 않는다 — 인증 미들웨어가 라우팅보다 먼저 401 을 낼 수
      있다(실측). 여기서 지키는 성질은 "**HTML 이 아니다**" 이지 특정 코드가 아니다.
    """
    res = client.get("/api/definitely-not-a-route")
    assert 400 <= res.status_code < 500, f"예상 밖 상태코드: {res.status_code}"
    assert "text/html" not in res.headers.get("content-type", ""), (
        "API 경로에 index.html 이 반환됐다 — 클라이언트가 JSON 을 기대하는 자리에서 "
        "HTML 을 받아 파싱 실패로 나타난다"
    )


def test_hashed_assets_are_not_forced_no_cache(client):
    """해시 asset 까지 no-cache 를 걸면 매 로드가 재다운로드다 — 그건 다른 결함이다."""
    assets = sorted((_DIST / "assets").glob("*.js")) if (_DIST / "assets").is_dir() else []
    if not assets:
        pytest.skip("dist/assets 에 번들이 없다")
    res = client.get(f"/assets/{assets[0].name}")
    assert res.status_code == 200
    assert "no-cache" not in res.headers.get("cache-control", "").lower(), (
        "해시 asset 에까지 no-cache 가 걸렸다 — 파일명이 곧 버전이므로 캐시되어야 한다"
    )
