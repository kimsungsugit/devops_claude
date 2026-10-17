"""subprocess 를 만지는 두 입력 표면의 보안 계약 (2026-08-05).

정적분석 ``S603``/``S607`` 153건을 실제 소스로 훑다가 나온 **진짜** 2건이다
(나머지 151건은 상수 인자거나 shell=False 라 무해했다).

## 1. PowerShell 다이얼로그 제목 — 임의 명령 실행

``/api/file-mode/browse-file`` body 의 ``title`` 이 검증 없이
``backend/services/local_service.py`` 의 PowerShell 스크립트 **문자열 안**으로
f-string 보간됐다:

    f"$dlg.Description='{title or '폴더 선택'}';"

``powershell -Command`` 는 받은 문자열을 **파싱**하므로 ``shell=False`` 는 방어가
아니다. title 에 작은따옴표 하나면 인용이 닫히고 뒤가 명령이 된다. 게다가 같은
결함이 ``pick_directory`` / ``pick_file`` **두 벌로 복제**돼 있었다(이 저장소의
1순위 재발 패턴). 그래서 아래 테스트는 두 곳을 **함께** 고정한다.

## 2. ``/api/run/stop`` — 임의 프로세스 종료 + 임의 경로 쓰기

``stop_run`` 이 body 의 pid 를 그대로 ``taskkill /T /F`` 로 넘겼다. 이 라우터는
``router = APIRouter()`` 라 ``require_admin`` 이 없어 인증된 일반 사용자 누구나
호출한다. 소유권 대조용 레지스트리 ``running_processes`` 가 있고 ``_track_process``
가 기록까지 하는데 **읽는 프로덕션 코드가 0곳**이었다 — 만들어 두고 안 쓴 것이다.
덤으로 ``req.status_path`` 를 ``safe_resolve_under`` 없이 resolve 해서 임의 경로에
JSON 을 썼다(같은 파일 270·294·316·368행은 전부 confine 한다).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytest.importorskip("backend.services.local_service")

from backend.routers import sessions as sessions_router  # noqa: E402
from backend.schemas import StopRequest  # noqa: E402
from backend.services import local_service  # noqa: E402

# 인용 탈출을 노리는 페이로드. 옛 판이라면 `'` 가 Description 인용을 닫고
# 세미콜론 뒤가 명령으로 실행된다.
EVIL_TITLE = "x';Start-Process calc;'"


# ===========================================================================
# 1. PowerShell 제목 주입
# ===========================================================================
@pytest.fixture
def no_tkinter(monkeypatch):
    """tkinter 를 못 쓰게 만들어 **PowerShell 폴백 경로**를 타게 한다.

    (sys.modules 에 None 을 넣으면 `import tkinter` 가 ImportError 를 낸다.)
    """
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", None)


@pytest.fixture
def captured_ps(monkeypatch):
    """_pick_via_powershell 호출을 가로채 (script, title) 을 기록."""
    calls: list[tuple[str, str]] = []

    def _fake(script: str, title: str = "") -> tuple[str, str]:
        calls.append((script, title))
        return "C:/chosen", ""

    monkeypatch.setattr(local_service, "_pick_via_powershell", _fake)
    return calls


@pytest.mark.parametrize("fn_name", ["pick_directory", "pick_file"])
def test_title_is_never_interpolated_into_the_script(fn_name, no_tkinter, captured_ps):
    """제목이 스크립트 **텍스트**에 들어가면 안 된다 — 두 함수 모두.

    ``parametrize`` 로 둘을 함께 도는 게 핵심이다. 한쪽만 고정하면 다른 쪽에
    보간이 되살아나도 초록이다(이 결함이 애초에 두 벌로 복제돼 있었다).
    """
    getattr(local_service, fn_name)(EVIL_TITLE)
    assert captured_ps, f"{fn_name}: PowerShell 폴백을 안 탔다 — 테스트 전제가 깨졌다"
    script, title = captured_ps[0]
    assert EVIL_TITLE not in script, (
        f"{fn_name}: 제목이 스크립트 문자열에 보간됐다 — 임의 명령 실행 경로다:\n{script}"
    )
    assert "Start-Process" not in script
    assert "$env:" in script, f"{fn_name}: 제목을 환경변수로 받지 않는다"
    assert title == EVIL_TITLE, f"{fn_name}: 제목이 env 인자로 전달되지 않았다"


def test_powershell_runner_puts_title_in_env_not_argv(monkeypatch):
    """argv 에는 제목이 없고 env 에만 있어야 한다."""
    seen_cmd: list[str] = []
    seen_env: dict[str, str] = {}

    class _Res:
        returncode = 0
        stdout = "C:/picked"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen_cmd.extend(cmd)
        seen_env.update(kwargs.get("env") or {})
        return _Res()

    monkeypatch.setattr(local_service.subprocess, "run", _fake_run)
    local_service._pick_via_powershell("$x=$env:ARIA_DIALOG_TITLE;", EVIL_TITLE)

    argv = " ".join(seen_cmd)
    assert EVIL_TITLE not in argv, f"제목이 argv 로 샜다: {argv}"
    assert seen_env.get(local_service._DLG_TITLE_ENV) == EVIL_TITLE, (
        "제목이 환경변수로 전달되지 않았다 — 그러면 다이얼로그 제목이 빈 채로 뜬다"
    )


def test_title_length_is_capped(monkeypatch):
    """길이 상한 — 환경 블록을 임의 크기로 부풀리지 못하게."""
    seen_env: dict[str, str] = {}

    class _Res:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen_env.update(kwargs.get("env") or {})
        return _Res()

    monkeypatch.setattr(local_service.subprocess, "run", _fake_run)
    local_service._pick_via_powershell("x", "A" * 5000)
    assert len(seen_env[local_service._DLG_TITLE_ENV]) == local_service._DLG_TITLE_MAX


def test_no_fstring_interpolation_of_title_remains_in_source():
    """소스 수준 가드 — 런타임 테스트를 우회하는 신규 보간을 막는다.

    ⚠ 위 동작 테스트는 ``_pick_via_powershell`` 을 monkeypatch 하므로, 누군가
      **세 번째** 다이얼로그 함수를 추가하면서 다시 보간하면 잡지 못한다.
      그래서 소스에 남은 f-string 안에 ``title`` 이 들어가는지 AST 로 직접 본다.
    """
    tree = ast.parse((REPO / "backend/services/local_service.py").read_text(encoding="utf-8"))
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for part in node.values:
            if not isinstance(part, ast.FormattedValue):
                continue
            names = {n.id for n in ast.walk(part.value) if isinstance(n, ast.Name)}
            if "title" in names:
                bad.append(f"line {node.lineno}: {ast.unparse(node)[:80]}")
    assert not bad, (
        "title 을 f-string 으로 보간하는 자리가 남아 있다 — PowerShell 로 넘어가면 "
        "임의 명령 실행이다:\n  " + "\n  ".join(bad)
    )


# ===========================================================================
# 2. /api/run/stop 소유권 + 경로 confine
# ===========================================================================
@pytest.fixture
def clean_registry(monkeypatch):
    """``running_processes`` 전역을 스냅샷 후 **원래 값으로 복원**한다.

    ⚠ 특정 값으로 고정하지 않는다 — 전역 싱글톤을 teardown 에서 고정했다가
      단독 실행 16건이 깨진 전례가 있다(CLAUDE.md 격리 규약).
    """
    reg = sessions_router.running_processes
    snapshot = dict(reg)
    reg.clear()
    yield reg
    reg.clear()
    reg.update(snapshot)


@pytest.fixture
def no_kill(monkeypatch):
    """실제로 프로세스를 죽이지 않는다 — 죽이면 테스트 러너가 위험하다."""
    killed: list[object] = []

    class _Res:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(sessions_router.subprocess, "run",
                        lambda cmd, **kw: (killed.append(cmd), _Res())[1])
    monkeypatch.setattr(sessions_router.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    return killed


def test_untracked_pid_is_rejected(clean_registry, no_kill):
    """추적되지 않은 PID 는 403 이고 **종료 시도조차 하지 않는다**.

    옛 판은 백엔드 자신의 PID 를 주면 ``/T``(자식 트리) ``/F``(강제)로
    uvicorn 을 통째로 내릴 수 있었다.
    """
    with pytest.raises(Exception) as exc:
        sessions_router.stop_run(StopRequest(pid=999999))
    assert getattr(exc.value, "status_code", None) == 403
    assert not no_kill, "거부했는데도 종료를 시도했다 — 검사가 kill 뒤에 있다"


def test_tracked_pid_is_killed_and_registry_entry_removed(clean_registry, no_kill, tmp_path):
    status = tmp_path / "run_status.json"
    status.write_text('{"state": "running"}', encoding="utf-8")
    clean_registry["sess_a"] = {"pid": 4321, "status_path": str(status)}

    out = sessions_router.stop_run(StopRequest(pid=4321))

    assert out["ok"] is True
    assert out["session_id"] == "sess_a"
    assert out["status_written"] is True
    assert no_kill, "추적된 PID 인데 종료를 시도하지 않았다"
    assert "sess_a" not in clean_registry, "종료 후 레지스트리에서 제거되지 않았다"
    assert "stopped" in status.read_text(encoding="utf-8")


def test_request_status_path_cannot_redirect_the_write(clean_registry, no_kill, tmp_path):
    """요청이 준 경로가 아니라 **추적 기록의 경로**에만 쓴다.

    옛 판은 ``Path(req.status_path).resolve()`` 라 임의 경로에 JSON 을 썼다.
    """
    tracked = tmp_path / "sess" / "run_status.json"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("{}", encoding="utf-8")
    attacker = tmp_path / "elsewhere" / "pwned.json"
    clean_registry["sess_b"] = {"pid": 777, "status_path": str(tracked)}

    sessions_router.stop_run(StopRequest(pid=777, status_path=str(attacker)))

    assert not attacker.exists(), (
        f"요청이 지정한 경로에 파일이 생겼다 — 임의 파일 쓰기가 남아 있다: {attacker}"
    )
    assert "stopped" in tracked.read_text(encoding="utf-8")


def test_status_write_failure_is_reported_not_silenced(clean_registry, no_kill, tmp_path, monkeypatch):
    """상태 파일 기록 실패를 삼키지 않는다.

    옛 판은 ``except Exception: pass`` + 고정 ``{"ok": True}`` 라, 상태가 안
    써져도 호출자는 정상 종료로 읽었다.
    """
    status = tmp_path / "run_status.json"
    status.write_text("{}", encoding="utf-8")
    clean_registry["sess_c"] = {"pid": 555, "status_path": str(status)}

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(sessions_router, "_write_json", _boom)
    out = sessions_router.stop_run(StopRequest(pid=555))

    assert out["status_written"] is False
    assert "status_error" in out and "disk full" in out["status_error"]


def test_failed_kill_is_reported_as_not_ok(clean_registry, tmp_path, monkeypatch):
    """종료가 **실패**하면 ``ok: False`` 여야 한다.

    옛 판은 ``check=False`` + 고정 ``{"ok": True}`` 라 실패와 성공이 구분되지
    않았다 — 호출자는 멈추지 않은 작업을 멈춘 것으로 읽고, 공격자에게는 PID
    존재 여부를 떠보는 oracle 이 된다.

    플랫폼 분기를 그대로 탄다(nt=taskkill rc, posix=os.kill 예외).
    """
    status = tmp_path / "run_status.json"
    status.write_text("{}", encoding="utf-8")
    clean_registry["sess_d"] = {"pid": 4242, "status_path": str(status)}

    class _Fail:
        returncode = 1
        stdout = b""
        stderr = b"not found"

    if sessions_router.os.name == "nt":
        monkeypatch.setattr(sessions_router.subprocess, "run", lambda cmd, **kw: _Fail())
    else:
        def _boom(_pid, _sig):
            raise OSError("no such process")
        monkeypatch.setattr(sessions_router.os, "kill", _boom)

    out = sessions_router.stop_run(StopRequest(pid=4242))
    assert out["ok"] is False, "종료가 실패했는데 ok:True 로 보고했다"


def test_registry_is_actually_read_by_production_code():
    """``running_processes`` 를 **프로덕션에서 읽는다**는 사실 자체를 고정한다.

    이 결함의 본질은 "레지스트리가 없다" 가 아니라 **"있는데 아무도 안 읽는다"**
    였다. 소유권 검사를 지우면 이 단언이 먼저 깨져야 한다.
    """
    src = (REPO / "backend/routers/sessions.py").read_text(encoding="utf-8")
    assert "running_processes" in src, "소유권 대조가 사라졌다"
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "stop_run"), None)
    assert fn is not None, "stop_run 이 사라졌다"
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "running_processes" in names or "_find_tracked_run" in called, (
        "stop_run 이 더 이상 소유권 레지스트리를 참조하지 않는다"
    )
