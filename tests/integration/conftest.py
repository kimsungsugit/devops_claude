"""integration 회귀 공용 fixture.

머신 상태 격리(admin 등록 · resolver local 고정 · JWT 폴백 · KB 캐시)는 여기 없다 —
`tests/conftest.py` 단일 출처에서 상속한다. **여기에 다시 쓰지 말 것.**
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    """인증 헤더가 붙은 TestClient.

    ⚠ **헤더가 없으면 전부 401 이다.** 커밋 `1b6bb99`(2026-08-04)가 `X-User` 단독 신원을
      막고 `Authorization: Bearer` 를 요구하게 됐고, 회귀 호환은 `DEV_MODE_X_USER_FALLBACK=1`
      + **`X-User` 헤더**가 둘 다 있어야 성립한다(폴백만으론 안 된다 — 실측). 이 스위트는
      6개 파일이 각자 `TestClient(app)` 를 헤더 없이 만들고 있었고, 그래서 56건이
      17일 동안 401 로 죽어 있었다.

    ⚠ 여기 하나로 모은 이유: 같은 fixture 가 6벌이면 한쪽만 고쳐진다. 새 파일은 이
      fixture 를 **그냥 인자로 받으면 된다** — 자기 `client` 를 정의하면 이걸 가린다.
    """
    from backend.main import app

    return TestClient(app, headers={"X-User": "tester"})
