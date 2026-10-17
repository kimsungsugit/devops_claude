"""integration 회귀 공용 fixture.

머신 상태 격리(admin 등록 · resolver local 고정 · JWT 폴백 · KB 캐시)는 여기 없다 —
`tests/conftest.py` 단일 출처에서 상속한다. **여기에 다시 쓰지 말 것.**
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_scm_registry(tmp_path_factory, monkeypatch):
    """운영 `config/scm_registry.json` 을 **쓰지 못하게** 임시본으로 갈아 끼운다.

    ⚠ 왜 필요한가 (2026-08-25 실측). `test_scm_router.py` 의 중복등록 회귀는
    `POST /api/scm/register` → 재등록 → `DELETE` 를 **운영 레지스트리에 직접** 한다.
    두 가지가 동시에 나쁘다:

    1. **사용자 운영 설정을 건드린다.** delete 로 되돌려도 파일 바이트는 달라진다
       (updated_at·직렬화 차이). 회귀가 사용자 데이터를 만지면 안 된다.
    2. **`-n auto` 에서 다른 워커의 가드를 터뜨린다.**
       `tests/unit/test_scm_write_requires_admin.py` 가 그 파일의 before/after 바이트를
       비교하는데, 이 스위트가 병렬로 쓰면 **자기가 안 한 변경**을 보고 실패한다.
       2026-08-21 게이트 범위가 `tests/integration/` 까지 넓어지며 드러났고, 인터리빙에
       따라 나타나는 **flaky** 라 지금까지 초록일 때가 있었다.

    실행 순서상 registry 를 만지는 fixture 보다 먼저 걸려야 하므로 autouse 다.
    """
    from backend.services import scm_registry as reg

    tmp = tmp_path_factory.mktemp("scm_registry_iso") / "scm_registry.json"
    live = reg.REGISTRY_PATH
    if live.exists():
        # 기존 항목이 있어야 list/status 회귀가 실제와 같은 모양을 본다.
        tmp.write_bytes(live.read_bytes())
    monkeypatch.setattr(reg, "REGISTRY_PATH", tmp)
    try:
        from filelock import FileLock
        monkeypatch.setattr(reg, "_REGISTRY_LOCK", FileLock(str(tmp) + ".lock", timeout=10))
    except ImportError:
        import threading
        monkeypatch.setattr(reg, "_REGISTRY_LOCK", threading.Lock())


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
