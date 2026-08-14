"""40차 — pytest conftest: 회귀 fixture 공통.

40차 admin role 가드 도입 — 기존 100+ 회귀가 X-User='tester'를 admin으로 암묵 가정.
본 autouse fixture가 admin_users 모듈을 monkeypatch해서 ['tester', 'hbrnd2']를 기본
admin으로 등록 → 기존 회귀 깨지지 않음.

회귀 파일별 격리 fixture(`_isolated_admins`, `_isolated_storage` 등)가 있으면
그들이 우선 (override). 본 fixture는 default fallback.
"""
from __future__ import annotations

import threading

import pytest


@pytest.fixture(autouse=True)
def _default_admin_users(tmp_path_factory, monkeypatch, request):
    """기존 회귀 (X-User='tester')를 admin으로 자동 등록.

    파일별 회귀가 본인의 admin_users fixture(`_isolated_admins`)를 정의했으면
    monkeypatch 우선순위로 그 fixture가 본 default를 덮어쓴다.
    """
    # 임시 admin_users.json — 회귀 batch 종료 후 자동 cleanup
    tmp = tmp_path_factory.mktemp("admin_users_default")
    p = tmp / "admin_users.json"
    p.write_text(
        '{"admins": ["tester", "hbrnd2"], "schema_version": 1}',
        encoding="utf-8",
    )
    try:
        from backend.services import admin_users as au
    except ImportError:
        # backend 모듈 import 실패 (예: backend 외 회귀)
        return
    monkeypatch.setattr(au, "ADMIN_USERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(au, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(au, "_LOCK", threading.Lock())
    # cache invalidate — 다음 load_admins에서 disk read
    au._cache["mtime"] = 0.0
    au._cache["admins"] = set()


@pytest.fixture(scope="session", autouse=True)
def _session_local_resolver():
    """⚠ 함수 스코프 격리는 **module/session 스코프 fixture 를 못 덮는다.**

    pytest 는 높은 스코프 fixture 를 먼저 세운다. 그래서 아래 `_default_local_resolver`
    (함수 스코프)가 돌기 **전에** module 스코프 fixture 가 실행되고, 거기서 처음
    파일을 만지면 `get_resolver()` 가 `config/file_mode.json`(영속)을 읽어
    **머신 상태 그대로** lazy-init 된다. 실측(2026-08-14): module 스코프 fixture 가 본
    `file_resolver._resolver` 는 `None` — 즉 격리가 한 번도 안 걸려 있었다.

    이 머신은 `mode=cloudium` 이라, 그 fixture 들이 부르는
    `generate_uds_source_sections` 의 경로 판정이 **Cloudium worker(127.0.0.1:8765)로**
    나간다. 워커는 단일 프로세스라 `-n auto`(18 워커) 고부하에서 일부 probe 가 timeout
    되고, `PermissionError: Cloudium worker 미응답` 이 fixture 에서 터진다 → 그 클래스
    전체가 ERROR. 같은 트리가 **어떤 때는 통과하고 어떤 때는 막히는** 이유였다
    (`test_phantom_inputs` 1건 / `test_macro_register_direction` 4건, pre-commit 은
    `-x` 라 그대로 커밋 차단). 워커가 아예 없는 머신에서는 100% 실패한다.

    ⚠ **원래 값을 복원한다.** 전역 싱글톤을 teardown 에서 특정 값으로 고정하면 그게
      다음 누설이 된다(커밋 584833e 의 전례 — 그 반대 방향으로 16건이 깨졌다).
    """
    try:
        from backend.services import file_resolver as fr
    except ImportError:
        yield
        return
    original = fr._resolver
    fr._resolver = fr.LocalFileResolver()
    try:
        yield
    finally:
        fr._resolver = original


@pytest.fixture(autouse=True)
def _default_local_resolver(monkeypatch):
    """파일 resolver 를 local 로 고정 — 유닛 회귀가 **머신 설정에 의존하지 않도록**.

    `config/file_mode.json` 은 영속이라 dev 머신에 `mode=cloudium` 이 남아 있으면
    `get_resolver()` 가 cloudium 으로 lazy-init 되고, Cloudium worker(127.0.0.1:8765)가
    없는 환경에서는 파일을 만지는 모든 라우터가 **403 cloudium-blocked** 로,
    경로 판정 헬퍼는 `absent` 대신 `unreadable` 로 떨어진다. 즉 **같은 코드가 머신에
    따라 통과/실패**한다.

    예전엔 `test_file_resolver_cloudium.py` 가 teardown 에서 전역 resolver 를 Local 로
    바꿔놓고 가는 **누설** 덕분에 전체 실행에서만 우연히 통과했고, 개별 파일을
    단독 실행하면 깨졌다(test_routers 14건 / test_swsa_router 1건 / impact_changes 1건).
    그 누설을 없앤 대신 여기서 **기본값으로 명시 고정**한다.

    cloudium 자체를 검증하는 회귀(test_file_resolver_cloudium / test_cloudium_*)는
    본인 fixture 에서 resolver 를 직접 세팅하므로 fixture 우선순위상 본 default 를
    덮어쓴다 (`_default_admin_users` 와 동일한 override 규약).
    """
    try:
        from backend.services import file_resolver as fr
    except ImportError:
        return  # backend 외 회귀
    monkeypatch.setattr(fr, "_resolver", fr.LocalFileResolver())


@pytest.fixture(autouse=True)
def _reset_kb_cache():
    """get_kb 프로세스 캐시(D8)가 테스트 간 인스턴스를 누수시키지 않도록 격리.

    전역 _KB_CACHE 가 살아있으면, 같은 base_dir 을 쓰는 다른 테스트가 stale
    인스턴스를 보거나 디스크 fixture 변경을 캐시 hit 으로 건너뛴다.
    """
    try:
        from workflow.rag import _clear_kb_cache
        _clear_kb_cache()
    except Exception:
        pass
    yield
    try:
        from workflow.rag import _clear_kb_cache
        _clear_kb_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _default_jwt_env(monkeypatch):
    """45차 C1 — 기존 X-User 신뢰 회귀 호환.

    DEV_MODE_X_USER_FALLBACK=1로 backward-compat 모드 활성. 단, JWT 전용 회귀
    (test_auth_login_router.py, test_auth_service.py)는 본인 fixture에서 명시적으로
    `monkeypatch.delenv("DEV_MODE_X_USER_FALLBACK", raising=False)` 호출하여 비활성.

    JWT secret도 기본 secret 설정 — 100+ 회귀가 JWT decoder import만 해도 동작.
    """
    monkeypatch.setenv("DEV_MODE_X_USER_FALLBACK", "1")
    if not (monkeypatch.delenv("JWT_SECRET", raising=False) or False):
        monkeypatch.setenv(
            "JWT_SECRET",
            "default_test_secret_minimum_32bytes_xxxxxxxxxxxxxxxx",
        )
