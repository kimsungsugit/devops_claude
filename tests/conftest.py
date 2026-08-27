from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

import pytest

_TMP_ROOT = Path(__file__).resolve().parents[1] / ".codex_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def tmp_path() -> Path:
    path = _TMP_ROOT / f"pytest-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def sample_report_dir(tmp_path: Path) -> Path:
    """Create a sample report directory with minimal JSON files for MCP tests."""
    import json as _json

    report_dir = tmp_path / "reports"
    report_dir.mkdir()

    (report_dir / "analysis_summary.json").write_text(
        _json.dumps({
            "project": "test_project",
            "coverage": {"line_rate": 0.85, "branch_rate": 0.72, "threshold": 0.8, "ok": True},
        }),
        encoding="utf-8",
    )
    (report_dir / "findings_flat.json").write_text(
        _json.dumps([
            {"severity": "warning", "rule": "W001", "message": "unused variable", "file": "main.c", "line": 10},
        ]),
        encoding="utf-8",
    )
    (report_dir / "run_status.json").write_text(
        _json.dumps({"ok": True, "total": 50, "passed": 48, "failed": 2}),
        encoding="utf-8",
    )
    (report_dir / "history.json").write_text(_json.dumps([]), encoding="utf-8")
    (report_dir / "jenkins_scan.json").write_text(_json.dumps({}), encoding="utf-8")
    return report_dir


@pytest.fixture()
def mock_llm_response(monkeypatch):
    """Mock workflow.ai LLM calls to return a canned response without hitting real APIs."""

    def _mock_call(*args, **kwargs):
        return {"text": "Mocked LLM response", "usage": {"input_tokens": 10, "output_tokens": 20}}

    try:
        import workflow.ai as _ai_mod
        monkeypatch.setattr(_ai_mod, "call_llm", _mock_call, raising=False)
        monkeypatch.setattr(_ai_mod, "call_gemini", _mock_call, raising=False)
    except (ImportError, AttributeError):
        pass
    return _mock_call


@pytest.fixture()
def mock_api_client():
    """Provide a mock httpx-style async client for API integration tests."""
    from unittest.mock import AsyncMock, MagicMock

    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}))
    client.post = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}))
    client.delete = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}))
    return client


# ── 머신 상태 격리 (2026-08-21: tests/unit/ 에서 여기로 **이동**) ─────────────
#
# ⚠ 이 fixture 들은 **단위 전용이 아니다.** backend 를 만지는 모든 회귀가 필요로 하는
#   "머신 상태로부터의 격리"다. 예전엔 `tests/unit/conftest.py` 에만 있어서
#   `tests/integration/` 은 격리가 **0** 이었고, 그래서 56건이 401 로 죽어 있었다
#   (2026-08-04 커밋 1b6bb99 이후 17일간 아무도 몰랐다 — 게이트가 tests/unit/ 만 돈다).
#
# ⚠ **복제하지 말 것.** 새 테스트 디렉터리를 만들면 여기서 자동으로 상속된다.
#   디렉터리별 conftest 에 같은 내용을 다시 쓰면 한쪽만 고쳐지는 결함이 재발한다.


@pytest.fixture()
def no_reference_suds(monkeypatch, tmp_path):
    """생성기가 **저장소 고정 입력**을 읽는 것을 막는다 — 느리고, 값이 섞인다.

    막는 것 둘:

      · `config.UDS_REF_SUDS_PATH` — 기본값이 저장소 `docs/` 의 HDPDM01 SUDS(**40.7MB**).
        읽으면 **다른 프로젝트 문서의 값**이 섞여 계측 단정이 흔들린다.
      · `config.resolve_uds_template_path()` — `template_path=None` 은 "템플릿 없음" 이
        아니라 저장소 기본 템플릿(**430 heading**)을 끌어온다.

    ⚠ 실측(2026-08-21, `tests/test_coverage_boost.py`): 이 둘을 안 막으면
      `generate_uds_docx(None, {}, out)` 가 **429초**다(빈 payload인데도). 프로파일상
      `_build_function_info_table` 429회 → `_merge_function_info_table` 858회 →
      python-docx `table.cell()` 81,510회 → `get_child_element` **4,390만 회**.
      `table.cell()` 이 접근마다 셀 목록을 재구성해 O(n^2) 가 되는 축이다.

    ⚠ **autouse 가 아니다.** 폴백 경로 자체를 검증하는 테스트는 이걸 쓰면 안 된다.
      모듈 전체에 걸려면 `pytestmark = pytest.mark.usefixtures("no_reference_suds")`.

    ⚠ 이 저장소에 같은 내용이 이미 3벌 있다(`tests/unit/test_uds_docx_gen_stats.py` 의
      autouse `_no_reference_suds`, `test_asil_no_fabrication.py`, `test_provenance_
      vocabulary.py`). 새 사용처는 **여기를 쓸 것** — 복제를 늘리지 않는다.
    """
    import config

    monkeypatch.setattr(config, "UDS_REF_SUDS_PATH",
                        str(tmp_path / "no_such_reference.docx"), raising=False)
    monkeypatch.setattr(config, "resolve_uds_template_path", lambda: "", raising=False)


@pytest.fixture()
def fixtures_dir() -> Path:
    """`tests/fixtures/` — sample.c 등 정적 입력.

    ⚠ 이 fixture 는 **어디에도 없었다.** `tests/integration/test_report_gen.py` 가
      요구하는데 정의가 없어 7건이 `fixture 'fixtures_dir' not found` 로 ERROR 였다
      (파일 헤더의 `# /app/tests/...` 가 말해주듯 옛 Docker 구성에서 온 테스트다).
    """
    return Path(__file__).resolve().parent / "fixtures"


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
