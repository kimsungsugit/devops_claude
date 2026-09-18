# tests/unit/test_resolver_isolation_scope.py
r"""resolver 격리는 **module 스코프 fixture 에도** 걸려야 한다.

## 실측 (2026-08-14)

`conftest._default_local_resolver` 는 함수 스코프인데, pytest 는 **높은 스코프 fixture 를
먼저** 세운다. 그래서 module 스코프 fixture 안에서 본 `file_resolver._resolver` 는
**`None`** 이었다 — 격리가 한 번도 안 걸린 것이다. 거기서 처음 파일을 만지면
`get_resolver()` 가 `config/file_mode.json`(영속)을 읽어 **머신 상태 그대로** lazy-init
된다.

이 머신은 `mode=cloudium` 이라, 그런 fixture 가 부르는 `generate_uds_source_sections`
의 경로 판정이 Cloudium worker(127.0.0.1:8765)로 나간다. 워커는 단일 프로세스라
`-n auto`(18 워커) 고부하에서 일부 probe 가 timeout 되고 fixture 가
`PermissionError: Cloudium worker 미응답` 으로 터진다 → 그 클래스 전체 ERROR.

    전량 -n auto  332s → 6,502 passed
    전량 -n auto  386s → 6,502 passed
    pre-commit    171s → test_phantom_inputs::TestPhantomGlobalU **ERROR 1** (-x 로 커밋 차단)
    전량 -n auto  741s → test_macro_register_direction::TestRegistersPastTheOldCap **ERROR 4**
    전량 -n auto  753s → 6,502 passed

같은 트리가 어떤 때는 통과하고 어떤 때는 막힌다 = **게이트가 비결정적**이었다.
워커가 아예 없는 머신에서는 100% 실패한다 — `_default_local_resolver` 의 docstring 이
막겠다고 적어 둔 바로 그 증상이다.
"""
from __future__ import annotations

import pytest

_SEEN: dict = {}


@pytest.fixture(scope="module")
def _resolver_at_module_scope():
    """⚠ 일부러 **module 스코프**다 — 함수 스코프면 이 회귀를 재현하지 못한다."""
    from backend.services import file_resolver as fr
    _SEEN["module"] = type(fr._resolver).__name__
    return _SEEN["module"]


def test_module_scoped_fixture_sees_the_local_resolver(_resolver_at_module_scope):
    """`None`(미격리) 도 cloudium 도 아니어야 한다.

    `None` 이면 첫 파일 접근에서 머신 설정으로 lazy-init 된다 — 그게 원래 결함이다.
    """
    assert _resolver_at_module_scope == "LocalFileResolver", (
        f"module 스코프에서 격리가 안 걸렸다 → {_resolver_at_module_scope} "
        "(None 이면 머신의 file_mode.json 으로 lazy-init 된다)")


def test_function_scope_is_still_isolated():
    """대조군 — 기존 함수 스코프 격리를 세션 fixture 가 덮어쓰지 않았는지."""
    from backend.services import file_resolver as fr
    assert type(fr._resolver).__name__ == "LocalFileResolver"


def test_a_module_scoped_parse_does_not_need_the_worker(tmp_path):
    """행동 검사 — 로컬 tmp 경로를 파싱하는 데 워커가 끼면 안 된다.

    ⚠ 이 저장소의 하드 제약은 "cloudium 파일은 워커를 통해서" 이지, "모든 경로가
      워커를 통해서" 가 아니다. 로컬 tmp 를 워커에 물으면 워커가 죽거나 붐빌 때
      **소스 파싱 자체가 실패**한다.
    """
    from backend.services import file_resolver as fr
    (tmp_path / "m.c").write_text("void f(void){}\n", encoding="utf-8")
    assert fr.get_resolver().is_dir(str(tmp_path)) is True
