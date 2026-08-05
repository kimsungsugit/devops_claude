"""``async def`` 라우터 핸들러가 이벤트 루프를 막지 않는다 (2026-08-05).

## 왜 생겼나

정적분석 ``ASYNC240`` 50건이 **전부 ``backend/routers/`` 의 ``async def`` 핸들러
안**이었다. FastAPI 는 ``async def`` 핸들러를 이벤트 루프에서 직접 돌리므로,
그 안의 블로킹 IO 는 **그 요청 하나가 아니라 백엔드 전체**를 멈춘다.

실측한 구조:

- ``local_uds_generate`` 는 Gemini 호출(``generate_uds_ai_sections``)·C 소스 파싱·
  리포트 생성기 8종을 **전부 루프 위에서** 돌린다. 생성 1건이 수 분이므로 그동안
  ``/api/health`` 도, 프론트가 **5초마다** 부르는 cloudium 접근 확인도 전부 대기한다.
  → 사용자에게는 "백엔드 먹통" 과 구분되지 않는다.
- ``local_suts_generate`` / ``local_sits_generate`` 는 ``await`` 가 **하나도 없는**
  ``async def`` 였다. 즉 이벤트 루프를 점유할 이유가 전혀 없는데 점유하고 있었다.

## 이게 왜 "판정 복제" 인가

저장소는 이미 답을 알고 있었다:

- ``local.py:243`` 의 ``_run_blocking`` docstring 이 문자 그대로
  *"async 엔드포인트의 이벤트 루프 hang 방지"* 다. 그런데 **딱 1곳**(docx 생성)에서만 쓰인다.
- ``swut.py`` / ``swit.py`` / ``swsa.py`` / ``swreport.py`` 는 ``Semaphore`` +
  ``asyncio.to_thread(run_build_safely)`` 를 **11곳에 체계적으로** 적용했다
  (``swut.py:19`` 에 "W5: asyncio.to_thread 마이그레이션" 이라고 적혀 있다).
- 반면 ``local.py`` / ``jenkins.py`` 에는 ``Semaphore`` 가 **0개**다.

같은 결함을 한쪽 계열에만 고친 것 — 이 저장소의 1순위 재발 패턴이다.
그래서 이 파일은 **구조 불변식**을 못 박아 다음 핸들러가 같은 모양으로 추가되는 것을 막는다.

## 이 파일이 주장하지 않는 것

"블로킹이 몇 ms 였다" 같은 **타이밍**은 단언하지 않는다. 시간 기반 단언은 CI 부하에서
흔들려 곧 무시되는 테스트가 된다. 여기서 보는 것은 AST 구조뿐이다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# 이벤트 루프에서 절대 돌면 안 되는 무거운 동기 함수 — 각각 수 초~수 분.
# (AI 호출 / 전체 소스트리 파싱 / docx·xlsx 빌드)
HEAVY_CALLS = frozenset({
    "generate_uds_ai_sections",
    "generate_uds_source_sections",
    "generate_suts",
    "generate_sits",
    "generate_sts",
    "_generate_docx_with_retry",
    "generate_uds_validation_report",
    "generate_called_calling_accuracy_report",
    "generate_asil_related_confidence_report",
    "generate_uds_constraints_report",
    "generate_uds_field_quality_gate_report",
    "generate_swcom_context_report",
    "generate_uds_preview_html",
    # ⚠ 이건 이름만 보면 오프로딩 같지만 **아니다**. 내부에서 ThreadPoolExecutor 에
    #   submit 한 뒤 `future.result(timeout=...)` 로 **호출자를 동기 대기**시킨다
    #   (backend/helpers/common.py:401). 즉 워커 스레드에서 돌아도 이벤트 루프는
    #   timeout_seconds 만큼 그대로 막힌다. "스레드에서 돈다 ≠ 호출자가 안 막힌다".
    "_run_report_with_timeout",
})

# 블로킹을 스레드로 넘기는 정당한 수단. 이 안에 들어 있으면 통과다.
OFFLOADERS = frozenset({"_run_blocking", "to_thread", "run_in_threadpool", "run_in_executor"})

ROUTER_FILES = (
    "backend/routers/local.py",
    "backend/routers/jenkins.py",
    "backend/routers/health.py",
    "backend/routers/excel.py",
    "backend/routers/qac.py",
    "backend/routers/vcast.py",
)


def _is_route(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """``@router.get/post/...`` 데코레이터가 붙었는가."""
    for d in fn.decorator_list:
        src = ast.unparse(d)
        if src.startswith(("router.", "app.")) or ".router." in src:
            return True
    return False


def _load(rel: str) -> ast.Module:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _async_routes(rel: str) -> list[ast.AsyncFunctionDef]:
    return [n for n in ast.walk(_load(rel))
            if isinstance(n, ast.AsyncFunctionDef) and _is_route(n)]


_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(fn: ast.AST):
    """**이 함수 자신의 본문**만 순회한다 — 중첩 def/async def/lambda 안으로는 안 들어간다.

    ⚠ 이 구분이 없으면 거짓 양성이 대량 발생한다(실측). ``local_suts_generate_async``
      는 ``generate_suts`` 를 중첩 ``_worker`` 안에서 부르고 그 ``_worker`` 를
      ``threading.Thread`` 로 띄운다 — **이미 스레드로 넘어간 것**이라 결함이 아니다.
      순진한 ``ast.walk`` 는 이걸 "루프에서 돈다" 고 잘못 보고한다.
    """
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NESTED):
            continue  # 중첩 함수 본문은 여기서 안 돈다 (호출 시점이 다르다)
        stack.extend(ast.iter_child_nodes(node))


def _own_awaits(fn: ast.AsyncFunctionDef) -> list[ast.Await]:
    """중첩 함수 안의 await 은 제외한 — **이 함수 자신의** await."""
    return [c for c in _own_nodes(fn) if isinstance(c, ast.Await)]


# 이벤트 루프에서 돌면 안 되는 블로킹 IO 의 흔적. U: 는 네트워크 드라이브라
# `exists()` 한 번이 수 초 걸릴 수 있고, cloudium 모드에서는 worker TCP IPC 로 나간다.
BLOCKING_IO_METHODS = frozenset({
    "exists", "is_dir", "is_file", "stat", "iterdir", "glob", "rglob",
    "read_text", "read_bytes", "write_text", "write_bytes", "mkdir", "unlink",
    "list_dir", "check_access",
})


def _own_blocking_io(fn: ast.AsyncFunctionDef) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKING_IO_METHODS:
            hits.append((node.lineno, ast.unparse(node)[:70]))
        elif isinstance(node.func, ast.Name) and node.func.id == "open":
            hits.append((node.lineno, ast.unparse(node)[:70]))
    return hits


# ---------------------------------------------------------------------------
# 불변식 1 — await 이 없으면 async 일 이유가 없다
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel", ROUTER_FILES)
def test_async_route_handlers_actually_await_something(rel: str) -> None:
    """``await`` 가 하나도 없는 ``async def`` 핸들러는 순수 블로킹이다.

    FastAPI 는 ``def`` 핸들러를 **스레드풀**로 돌리므로, ``async`` 를 떼는 것만으로
    이벤트 루프가 자유로워진다. 반대로 ``async`` 를 붙여 두면 이득은 0이고 손해만 있다.

    실측(수정 전): ``local_suts_generate`` 등 8개가 여기 걸렸고, 그중
    ``local_suts_generate`` / ``local_sits_generate`` 는 본문에서
    ``generate_suts`` / ``generate_sits`` 를 직접 호출해 **생성 전 구간**을 루프에서 돌렸다.

    ⚠ 단서: ``await`` 이 없어도 **블로킹 IO 도 없으면** 결함이 아니다(상수 dict 를
      돌려주는 핸들러는 흔하고 무해하다). 그래서 "await 0 **그리고** 블로킹 IO 있음"
      두 조건이 함께 성립할 때만 잡는다 — 안 그러면 무해한 핸들러까지 잡는 소음이 된다.
    """
    offenders = []
    for fn in _async_routes(rel):
        if _own_awaits(fn):
            continue
        io = _own_blocking_io(fn)
        if io:
            where = ", ".join(f"{ln}:{s}" for ln, s in io[:3])
            offenders.append(f"{rel}:{fn.lineno} {fn.name}  [{where}]")
    assert not offenders, (
        "await 이 없는데 블로킹 IO 를 하는 async 라우터 핸들러 — `async` 를 떼면 "
        "FastAPI 가 스레드풀로 돌려 이벤트 루프가 풀린다:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 불변식 2 — 무거운 동기 호출은 반드시 스레드로 넘어간다
# ---------------------------------------------------------------------------
def _offloaded_call_lines(fn: ast.AsyncFunctionDef) -> set[int]:
    """``await _run_blocking(f, ...)`` / ``await asyncio.to_thread(f, ...)`` 안에서
    **인자로 넘어간** 함수 이름의 위치를 모은다 — 이건 이미 스레드로 간 것이다."""
    safe: set[int] = set()
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if fname not in OFFLOADERS:
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name):
                    safe.add(sub.lineno)
                elif isinstance(sub, ast.Call):
                    safe.add(sub.lineno)
    return safe


@pytest.mark.parametrize("rel", ROUTER_FILES)
def test_heavy_generation_is_not_called_on_the_event_loop(rel: str) -> None:
    """무거운 생성 함수가 ``async def`` 핸들러에서 **직접** 호출되면 안 된다.

    허용되는 형태는 둘뿐이다:
      1. ``await _run_blocking(generate_x, ...)`` / ``await asyncio.to_thread(...)``
      2. 핸들러 자체가 ``def`` (FastAPI 가 스레드풀로 돌림)
    """
    bad: list[str] = []
    for fn in _async_routes(rel):
        safe_lines = _offloaded_call_lines(fn)
        for node in _own_nodes(fn):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in HEAVY_CALLS and node.lineno not in safe_lines:
                bad.append(f"{rel}:{node.lineno} {fn.name}() -> {name}()")
    assert not bad, (
        "이벤트 루프에서 직접 호출되는 무거운 생성 함수 — 그동안 백엔드 전체가 멈춘다. "
        "`await _run_blocking(...)` 또는 핸들러를 `def` 로:\n  " + "\n  ".join(bad)
    )


# ---------------------------------------------------------------------------
# 불변식 3 — 이미 고쳐진 계열이 되돌아가지 않는다 (판정 복제 방지)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel", ("backend/routers/swut.py", "backend/routers/swit.py",
                                 "backend/routers/swreport.py"))
def test_swut_family_keeps_the_offload_pattern(rel: str) -> None:
    """SwUT/SwIT/SwReport 계열은 ``to_thread`` 패턴이 **정답**으로 이미 적용돼 있다.

    이 단언이 깨지면 정답 쪽이 퇴화한 것이다 — local/jenkins 를 고칠 때 참조하는
    기준이 사라지므로 함께 지킨다.
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    assert "asyncio.to_thread" in src, f"{rel}: to_thread 오프로딩이 사라졌다"
    assert "Semaphore" in src, f"{rel}: 동시 실행 제한(Semaphore)이 사라졌다"


def test_threadpool_paths_preserve_user_context() -> None:
    """``async def`` → ``def`` 전환과 ``to_thread`` 오프로딩의 **전제**를 못 박는다.

    이 저장소는 사용자 신원을 ``backend.user_context.current_user`` **ContextVar**
    로 들고 다니고, ``_progress_key`` 같은 곳이 그걸 읽어 사용자별 캐시 키를 만든다.
    전환 후 워커 스레드에서 컨텍스트가 날아가면 모든 진행률이 ``default`` 사용자
    아래로 섞인다 — 조용히 틀리는 종류의 회귀다.

    실측으로 두 경로 모두 보존됨을 확인했고, 여기서 고정해 **의존성 업그레이드가
    이 성질을 깨면 즉시 드러나게** 한다.
    """
    import asyncio

    from starlette.concurrency import run_in_threadpool

    from backend.user_context import current_user, get_current_user

    async def _probe() -> tuple[str, str]:
        token = current_user.set("ctxprobe")
        try:
            return (await run_in_threadpool(get_current_user),
                    await asyncio.to_thread(get_current_user))
        finally:
            current_user.reset(token)

    via_fastapi, via_to_thread = asyncio.run(_probe())
    assert via_fastapi == "ctxprobe", (
        "run_in_threadpool 이 ContextVar 를 잃는다 — `def` 핸들러 전환이 사용자 신원을 "
        "날린다는 뜻이므로 전환 방식을 재검토해야 한다"
    )
    assert via_to_thread == "ctxprobe", (
        "asyncio.to_thread 가 ContextVar 를 잃는다 — `_run_blocking` 오프로딩이 "
        "사용자 신원을 날린다"
    )


def test_offload_helper_has_exactly_one_definition() -> None:
    """오프로딩 헬퍼의 정의는 ``_safety.py`` **한 곳뿐**이어야 한다.

    처음엔 ``local.py`` 안에만 있었고 ``jenkins.py`` 에는 없어서, jenkins 쪽 UDS
    생성이 소스 파싱·docx 빌드·리포트 6종을 전부 이벤트 루프에서 돌렸다.
    사본을 만들어 해결하면 이 저장소가 반복해 겪은 "판정 복제 → 한쪽만 고쳐짐"
    이 되므로(``_ratchet_core.py`` 가 같은 이유로 생겼다) 정의 수를 직접 센다.
    """
    defs: list[str] = []
    for path in sorted((REPO / "backend/routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in ("run_blocking", "_run_blocking"):
                defs.append(f"{path.name}:{node.lineno}")
    assert len(defs) == 1, f"오프로딩 헬퍼 정의가 {len(defs)}개다 — 단일 출처여야 한다: {defs}"
    assert defs[0].startswith("_safety.py:"), f"정의 위치가 공용 모듈이 아니다: {defs[0]}"


@pytest.mark.parametrize("rel", ("backend/routers/local.py", "backend/routers/jenkins.py"))
def test_both_uds_routers_use_the_shared_offloader(rel: str) -> None:
    """local 과 jenkins **둘 다** 공용 헬퍼를 쓴다.

    한쪽만 배선하면 나머지 한쪽이 조용히 옛 동작으로 남는다 — 이 결함이 애초에
    그렇게 4개월을 버텼다.
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    assert "from backend.routers._safety import run_blocking" in src, (
        f"{rel}: 공용 오프로딩 헬퍼를 import 하지 않는다"
    )
    assert "_run_blocking(" in src, f"{rel}: 오프로딩을 실제로 쓰지 않는다"
