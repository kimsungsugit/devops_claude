from __future__ import annotations

import gc
import logging
import os
import pathlib
import shutil
import stat
import sys
import threading
import uuid
from pathlib import Path

import pytest

_TMP_ROOT = Path(__file__).resolve().parents[1] / ".codex_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)

# (R46 2026-09-09) pre-commit 훅 아래에서 pytest 가 돌면 `GIT_INDEX_FILE` 이 **절대경로**
# (`.git/next-index-<pid>.lock` — pathspec 커밋의 임시 index)로 상속된다. 임시 저장소에서
# `git add` 를 하는 테스트가 그 값을 그대로 쓰면 **커밋 중인 실 index 를 덮어쓴다**
# (B-7: 2026-08-25 1,212→3 트리 · 2026-09-09 `unable to read` 두 번). git 이 "다른 저장소로
# 갈 때 지우라" 고 지정한 변수들을 세션 시작에 지운다. 훅도 같은 변수를 빼고 띄우지만
# (`.githooks/pre-commit`), 훅 없이 `GIT_INDEX_FILE` 을 둔 셸에서 돌려도 안전해야 한다.
#: 지운 변수 이름 — 테스트가 "실제로 지웠는가" 를 단언하는 데 쓴다.
_SCRUBBED_GIT_ENV: tuple[str, ...] = tuple(
    v for v in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR")
    if os.environ.pop(v, None) is not None
)

# (R47 N21 2026-09-10) 테스트는 **사용자의 `logs/backend.log` 에 쓰지 않는다.**
# `backend.main` 은 import 시점에 `_attach_file_log()` 로 `RotatingFileHandler` 를 붙이는데,
# 그 경로가 `DEVOPS_LOG_DIR` 미설정이면 저장소 `logs/` 다. 테스트 모듈 수십 개가 모듈 상단에서
# `backend.main` 을 import 하므로 `-n auto` 워커 18개가 **전부 실 로그 파일을 연 채** 돌았다.
# 실측(2026-09-10): `logs/backend.log` 116,400줄 중 pytest 임시경로가 찍힌 줄만 2,838줄이고,
# 회전 파일이 `.1`·`.5` 만 남고 `.2~.4` 가 없다(여러 프로세스가 같은 파일을 동시에 회전한 흔적).
# 사후 진단용 로그가 테스트 소음과 섞이면 "그 시각에 무슨 일이 있었나" 를 읽을 수 없다.
#
# ⚠ 왜 fixture 가 아니라 **import 시점**인가 — 핸들러는 collection 중 모듈 import 에서 붙는다.
#   세션 fixture 는 그보다 늦다. `.env` 는 `override=False` 로 읽히므로 여기서 넣은 값이 이긴다.
#   pid 별 디렉터리라 xdist 워커끼리도 파일을 공유하지 않는다. 정리는 `pytest_unconfigure`.
_ISOLATED_LOG_DIR = Path(__file__).resolve().parents[1] / ".codex_tmp" / f"logs-test-{os.getpid()}"
os.environ["DEVOPS_LOG_DIR"] = str(_ISOLATED_LOG_DIR)

#: pytest 를 띄운 cwd. 정리가 cwd 를 트리 밖으로 옮겨야 할 때 **여기로** 돌아온다 —
#: 레포 루트는 "복원값" 이 아니라 지어낸 값이다(R45 리뷰 I-1: 다른 cwd 에서 띄운 사용자에게
#: 조용한 축 변경이고, teardown 중 살아 있는 daemon 스레드 12곳이 그 cwd 를 목격한다).
_INITIAL_CWD = os.getcwd()

#: 정리에 실패한 경로 — 프로세스 안에서만 쓰는 사본(테스트가 단언에 쓴다).
_CLEANUP_FAILURES: list[str] = []

#: **파일**로도 남긴다. 이유는 `pytest_unconfigure` 참조 — 리스트만으로는 아무에게도 안 닿는다.
_CLEANUP_FAILURE_LOG = _TMP_ROOT / "_cleanup_failures.txt"


def _record_cleanup_failure(line: str) -> None:
    """실패 한 줄을 프로세스 사본과 **파일**에 함께 남긴다.

    ⚠ (R43 리뷰 C2) 첫 판은 모듈 전역 리스트에만 쌓고 세션 fixture 가 `print` 했다.
    그런데 이 저장소의 게이트 4곳은 전부 `-n auto` 이고 `-s` 가 없다:
      · `-s` 없는 직렬 실행에서는 세션 fixture teardown 의 stdout 이 **캡처돼 사라진다**.
      · xdist 에서는 워커가 **별도 프로세스**라 리스트가 N조각으로 갈리고 컨트롤러에
        전달되지 않는다.
    즉 "조용히 쌓이는 것을 막는 유일한 신호" 라고 적어 둔 그 신호가 **실사용 조건에서
    0% 도달**이었다. `ignore_errors=True` 를 걷어낸 자리에 같은 모양의 fake-green 을
    다시 넣은 셈이다. 파일이면 프로세스 경계를 넘고 캡처와도 무관하다.
    """
    _CLEANUP_FAILURES.append(line)
    try:
        with open(_CLEANUP_FAILURE_LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass          # 기록조차 못 하는 상황이라도 리스트 사본은 남는다


def pytest_configure(config):
    """세션 시작 시 실패 로그를 비운다 — 지난 실행의 잔재를 이번 것으로 읽지 않는다."""
    if hasattr(config, "workerinput"):
        return        # xdist 워커는 지우지 않는다(컨트롤러가 이미 비웠다)
    try:
        _CLEANUP_FAILURE_LOG.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def pytest_unconfigure(config):
    """정리 실패를 **컨트롤러에서** 보고한다 — 워커 stdout 은 여기까지 오지 않는다."""
    # (R47 N21) 이 프로세스의 격리 로그 디렉터리를 지운다 — 워커·컨트롤러 각자 자기 pid 것만.
    # 핸들러가 파일을 쥐고 있으므로(R44 실측 WinError 32) 먼저 놓고 지운다. `backend.main` 을
    # import 한 적 없는 프로세스(컨트롤러)는 디렉터리 자체가 없다.
    if _ISOLATED_LOG_DIR.exists():
        _release_handles_under(_ISOLATED_LOG_DIR)
        _cleanup_tree(_ISOLATED_LOG_DIR)
    if hasattr(config, "workerinput"):
        return
    try:
        lines = [ln for ln in _CLEANUP_FAILURE_LOG.read_text(encoding="utf-8").splitlines() if ln]
    except OSError:
        return
    if not lines:
        return
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    say = reporter.write_line if reporter is not None else print
    say(f"[임시 트리 정리] 실패 {len(lines)}건 — `.codex_tmp` 에 남았습니다:")
    for line in lines[:5]:
        say(f"  {line}")
    if len(lines) > 5:
        say(f"  … 외 {len(lines) - 5}건 (전체: {_CLEANUP_FAILURE_LOG})")


def _force_rmtree(path: Path, *, record: bool = True) -> bool:
    """임시 트리(또는 파일)를 **정말로** 지운다. 실패는 침묵하지 않는다.

    `record=False` 면 실패를 기록하지 않는다 — "1차는 조용히, 실패하면 GC 후 2차만 기록"
    하는 `_cleanup_tree` 용이다(같은 실패를 두 번 적지 않는다).

    ⚠ (R45 리뷰 W-2) **파일** 경로도 받는다. 예전엔 디렉터리 전용이라 파일을 주면
    `shutil.rmtree` 가 `os.scandir` 에서 `NotADirectoryError` 를 내고, `lexists` 가 True 라
    **핸들 유무와 무관하게 항상 False** 였다. 가드 테스트가 그 False 를 "핸들이 열려 있다"
    로 읽어 한 라운드를 "미규명" 으로 보냈다 — 실패 줄에 이미 `NotADirectoryError` 라고
    적혀 있었는데 `WinError 32` 로 읽은 것이다.

    ⚠ (R43 N16) 예전엔 세 곳 모두 `shutil.rmtree(..., ignore_errors=True)` 였고,
    그래서 `.codex_tmp` 에 `pytest-*` 디렉터리가 **13,723개**(가장 오래된 것 2026-03-13,
    6개월치)나 쌓여 있었다. `ls .codex_tmp` 한 번이 120초를 넘겼다.

    원인은 디스크가 아니라 **Windows + git** 이다: 테스트가 임시 저장소를 만들면
    `.git/objects/**` 가 **읽기 전용(0444)** 으로 생성되고, Windows 의 `unlink` 는 그
    파일을 지우지 못해 `PermissionError [WinError 5]` 를 낸다. `ignore_errors=True` 가
    그 예외를 통째로 삼켰으므로, 정리는 **한 번도 성공한 적이 없는데** 스위트는 조용했다
    (실측: 잔존물 3개를 손으로 지워 보니 1개는 성공, git 이 든 2개는 전부 WinError 5).

    이 저장소가 반복해 고친 fake-green 이 **정리 경로**에 남아 있던 자리다 — 빈 출력을
    성공으로 읽는 것과 같다. 이제 쓰기 비트를 세우고 재시도하며, 그래도 안 되면 사실을
    모아 세션 끝에 보고한다(테스트를 실패시키지는 않는다 — 정리는 판정이 아니다).

    ⚠ **테스트가 패치한 전역을 밟지 않는다.** 첫 판은 `if not path.exists()` 로 시작했는데,
    `Path.exists` 를 monkeypatch 로 PermissionError 를 던지게 만드는 테스트가 있어
    (`test_impact_changes.py:159` — cloudium SMB 권한거부 재현) **teardown 이 그 패치를 밟고
    죽었다**. 정리는 teardown 에서 도는 코드라, 그 시점에 무엇이 패치돼 있는지 알 수 없다 —
    그래서 판정도 `Path` 가 아니라 `os.path.lexists` 로 한다(끊어진 심링크도 '남았다').

    ⚠ **콜백은 예외를 위로 던지지 않는다**(리뷰 W1). 던지면 `shutil.rmtree` 가 그 자리에서
    언와인드해 **나머지 형제 항목을 아예 못 지운다** — 실패 케이스에서 옛 `ignore_errors`
    보다도 적게 지우게 된다. 모아 두고 계속 진행한 뒤, 끝에서 실제로 남았는지로 판정한다.
    """
    failures: list[str] = []

    def _on_exc(func, target, exc):
        # 읽기 전용이면 쓰기 비트를 세우고 한 번 더.
        try:
            if os.path.islink(target):
                # 심링크에 chmod 하면 **타깃**의 권한이 바뀐다 — 트리 밖 파일을 건드릴 수
                # 있으므로 손대지 않는다(리뷰 W3). rmtree 는 링크를 따라 들어가지 않는다.
                failures.append(f"{target}: symlink — {type(exc).__name__}")
                return
            mode = os.stat(target, follow_symlinks=False).st_mode
            # ⚠ `S_IWRITE`(=0o200)를 **대입**하면 r/x 가 사라진다(리뷰 W2). 디렉터리는 x 를
            #   잃는 순간 하위 순회가 불가능해지고, 남는 파일은 열어 볼 수도 없게 된다.
            os.chmod(target, mode | stat.S_IWUSR | (stat.S_IXUSR if os.path.isdir(target) else 0))
            func(target)
        except OSError as retry_exc:
            failures.append(f"{target}: {type(retry_exc).__name__}: {retry_exc}")

    try:
        if os.path.islink(path) or not os.path.isdir(path):
            # 파일(또는 링크)은 rmtree 대상이 아니다 — 같은 콜백으로 한 번 시도한다.
            try:
                os.unlink(path)
            except FileNotFoundError:
                return True
            except OSError as exc:
                _on_exc(os.unlink, path, exc)
        elif sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_on_exc)
        else:
            # 3.11 이하에는 `onexc` 가 없다 — 없는 인자를 주면 TypeError 가 나고 그것은
            # `except OSError` 에 안 잡혀 teardown 전체가 죽는다(리뷰 W5).
            shutil.rmtree(path, onerror=lambda f, t, ei: _on_exc(f, t, ei[1]))
    except FileNotFoundError:
        return True          # 이미 없다 = 정리 완료(실패가 아니다)
    except OSError as exc:
        failures.append(f"{path}: {type(exc).__name__}: {exc}")

    if not os.path.lexists(path):
        return True          # 도중에 무엇이 실패했든 **결과적으로 지워졌다**
    if not record:
        return False
    detail = failures[0] if failures else "원인 미상"
    if len(failures) > 1:
        detail += f" (외 {len(failures) - 1}건)"
    # ⚠ 메시지를 짧게 자르지 않는다 — Windows 는 **파일명이 문장 끝**에 붙어서, 120자 캡이
    #   유일한 진단 정보를 통째로 버렸다(리뷰 W4).
    # 실패 상세가 이미 루트 경로로 시작하면 앞에 또 붙이지 않는다(같은 경로 두 번).
    line = detail if detail.startswith(str(path)) else f"{path}: {detail}"
    _record_cleanup_failure(line[:600])
    return False


def _cleanup_tree(path: Path) -> bool:
    """정리의 정본 순서: 핸들을 놓고 → 지우고 → **실패했을 때만** GC 후 한 번 더.

    ⚠ (R45 리뷰 W-1) 처음엔 `_release_handles_under` 가 매번 `gc.collect()` 를 불렀다.
    full collection 은 부하 인터프리터에서 중앙값 **198 ms** 이고 `tmp_path` 테스트가
    **1,447개**라 전량 1회에 **+290~480 s CPU** — 모듈 하나(84건)의 A/B 실측 +22~33 s.
    CI(2~4코어 `loadfile`)는 벽시계 +75~240 s, pre-commit 의 xdist 미설치 직렬 폴백은
    1800 s 예산(여유 ≈530 s)을 넘길 수 있었다. 99.8% 는 GC 없이 지워지므로, GC 는 1차
    삭제가 실패한 **0.2%** 에만 쓴다. 효과는 같다(실측: 실패 → collect → 삭제 성공).
    """
    _release_handles_under(path)
    if _force_rmtree(path, record=False):
        return True
    # 참조 끊긴 파일 객체(예: `load_workbook(read_only=True)` 를 변수에서 버린 것)는
    # GC 시점에 닫힌다. 그 시점이 정리보다 늦으면 실패, 빠르면 성공 — "정리 실패 0" 이
    # 재실행에서 8 로 돌아온 이유가 이것이었다(R44). 우연을 순서로 바꾼다.
    gc.collect()
    return _force_rmtree(path)


# ⚠ (R43 리뷰 C1) 보고를 세션 fixture 로 두면 **정작 가장 큰 두 트리의 실패를 못 본다**.
# fixture teardown 은 setup 역순이고 setup 은 이름 알파벳 순이라, `_report_cleanup_failures`
# 는 `_isolate_config_files`·`_isolate_report_dirs` 보다 **먼저** 끝났다 — 그 둘이 teardown 에서
# 하는 정리의 실패는 이미 보고가 끝난 뒤에 기록됐다. 게다가 그 순서는 설계가 아니라 **이름
# 철자에 딸린 우연**이었다. 그래서 보고는 모든 finalizer 뒤에 도는 `pytest_unconfigure` 로
# 옮겼다(위). 여기에 fixture 를 다시 두지 말 것.


def _release_handles_under(path: Path) -> None:
    """`path` 하위를 잡고 있는 **우리 프로세스의** 핸들을 놓는다 — 파일 핸들뿐 아니라
    **프로세스 cwd 도 옮긴다**(전역 부작용, 갈래 ④). 진단 목적으로 부르지 말 것. (R44 N19)

    R43 이 정리 실패 보고를 살리자 두 번째 원인이 드러났다 — 실행당 23건이 전부
    `WinError 32`(사용 중)이고, 읽기 전용과 무관했다. 실측으로 두 갈래였다:

    · **로그 핸들러 10건** — `backend.main._attach_file_log()` 가 `RotatingFileHandler` 를
      열어 로거에 붙이고 **닫지 않는다**(프로덕션에선 프로세스 수명과 같으니 정상).
      `test_backend_file_logging.py` 가 `DEVOPS_LOG_DIR` 를 tmp 로 잡고 그 함수를 부르면,
      핸들러가 tmp 파일을 쥔 채 남아 teardown 이 지우지 못한다(6 passed · 정리 실패 5건).
    · **DB 엔진 18건** — `q.db` 를 `db_path=` 로 만든 sqlalchemy 엔진이 경로별 캐시
      (`_engines`)에 살아 있어 sqlite 연결이 열린 채다. `reset_engine()` 뒤에는 지워진다.

    로깅 갈래는 **전수 순회**다(등록된 모든 로거를 훑는다) — 새 테스트가 어디서 핸들러를
    열든 걸린다. 반면 락·엔진 갈래는 **모듈 이름을 적은 목록**이다(아래 튜플). 지금 저장소에
    경로별 엔진 캐시는 그 둘뿐이지만, 세 번째가 생기면 조용히 빠진다 — 이 저장소가
    `_REPORT_DIR_TARGETS` 에서 이미 겪은 형태다(`impact_jobs` 누락 → AST 전수 가드).
    `test_temp_tree_cleanup.py` 의 가드가 "저장소의 `_engines` 정의 == 이 목록" 을 강제한다.
    """
    try:
        # ⚠ (R44 리뷰 W4) 구분자를 붙이지 않으면 `…/inside` 가 `…/inside_extra` 를 접두사로
        #   먹는다(실증: 형제 디렉터리의 핸들러까지 닫혔다). pid 접두사도 같다(123 ⊂ 1234).
        root = os.path.join(os.path.normcase(os.path.abspath(path)), "")
    except (OSError, ValueError):
        return

    # ① 로깅 파일 핸들러 — 루트 로거 + 등록된 모든 로거.
    loggers = [logging.getLogger()]
    loggers += [logging.getLogger(name) for name in list(logging.root.manager.loggerDict)]
    for logger in loggers:
        for handler in list(getattr(logger, "handlers", []) or []):
            fname = getattr(handler, "baseFilename", None)
            if not fname:
                continue
            try:
                if os.path.normcase(os.path.abspath(fname)).startswith(root):
                    handler.close()
                    logger.removeHandler(handler)
            except (OSError, ValueError):
                continue

    # ② 실행 락(FileLock) — `impact_audit` 은 실행 수명 동안 락을 **보유**하는 설계라
    #    (holder crash 시 OS 가 fd 를 닫아 좁비 락이 안 남는다) 테스트가 `release_run_lock`
    #    을 안 부르면 `.flock` 이 열린 채 남는다. 그 경로가 이 트리 안이면 놓아 준다.
    audit_mod = sys.modules.get("workflow.impact_audit")
    locks = getattr(audit_mod, "_RUN_FILE_LOCKS", None) if audit_mod is not None else None
    if isinstance(locks, dict):
        for key, lock in list(locks.items()):
            lock_file = getattr(lock, "lock_file", None)
            if not lock_file:
                continue
            try:
                if not os.path.normcase(os.path.abspath(lock_file)).startswith(root):
                    continue
                if getattr(lock, "is_locked", False):
                    lock.release(force=True)
            except (OSError, ValueError, AttributeError, TypeError):
                continue
            locks.pop(key, None)
            # ⚠ (R44 리뷰 W5) **짝을 함께 놓는다.** cross-process 락만 풀고 intra 락과
            #   소유자 기록을 남기면 같은 키의 다음 acquire 가 `intra.acquire(blocking=False)`
            #   에서 실패해 **영구 `active_lock`** 이 된다(리뷰어 실증). `impact_audit` 자신의
            #   docstring 이 "원인 파악이 매우 어려움" 이라 적어 둔 그 상태다.
            intra_locks = getattr(audit_mod, "_RUN_INTRA_LOCKS", None)
            if isinstance(intra_locks, dict):
                intra = intra_locks.get(key)
                try:
                    if intra is not None and intra.locked():
                        intra.release()      # threading.Lock 은 타 스레드 해제를 허용한다
                except (RuntimeError, AttributeError):
                    pass
                intra_locks.pop(key, None)
            owners = getattr(audit_mod, "_RUN_LOCK_OWNERS", None)
            if isinstance(owners, dict):
                owners.pop(key, None)

    # ③ 경로별 엔진 캐시(quality·chat) — 이 경로의 DB 를 쓴 테스트가 있으면 dispose.
    for mod_name in ("workflow.quality.db", "backend.services.chat_history_db"):
        mod = sys.modules.get(mod_name)
        engines = getattr(mod, "_engines", None) if mod is not None else None
        if not isinstance(engines, dict):
            continue
        if any(os.path.normcase(os.path.abspath(str(k))).startswith(root) for k in engines):
            reset = getattr(mod, "reset_engine", None)
            if callable(reset):
                try:
                    reset()
                except Exception as exc:  # noqa: BLE001 — 정리 실패가 teardown 을 막지 않는다
                    # 침묵하지 않는다 — 못 놓은 핸들은 곧 잔존물이 되고, 그 사유가 유일한 단서다.
                    _record_cleanup_failure(f"{path}: {mod_name}.reset_engine() 실패 — "
                                            f"{type(exc).__name__}: {exc}")

    # ④ 프로세스 cwd — Windows 는 **현재 디렉터리를 지우지 못한다**("사용 중").
    #    `monkeypatch.chdir(tmp_path / …)` 를 쓴 테스트는 teardown 이 인자 역순이라
    #    `tmp_path` 정리가 chdir 복원보다 **먼저** 돈다(R45 실측: `fake_workspace` 잔존).
    #    R43 C3 와 같은 순서 함정 — 정리 전에 트리 밖으로 나간다(복원은 monkeypatch 몫이며
    #    `MonkeyPatch.undo` 는 저장해 둔 절대경로로 무조건 chdir 하므로 최종값은 같다).
    try:
        if os.path.join(os.path.normcase(os.getcwd()), "").startswith(root):
            os.chdir(_INITIAL_CWD)
    except OSError as exc:
        # 사유를 남긴다 — 결과는 어차피 `WinError 32` 로 보고되지만 원인(cwd)이 사라진다.
        _record_cleanup_failure(f"{path}: cwd 이탈 실패 — {type(exc).__name__}: {exc}")

    # ⚠ GC 는 여기서 하지 않는다 — `_cleanup_tree` 가 **1차 삭제 실패 시에만** 부른다
    #   (무조건 collect 는 전량 +290~480 s CPU, 리뷰 W-1).


@pytest.fixture()
def tmp_path() -> Path:
    path = _TMP_ROOT / f"pytest-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        _cleanup_tree(path)


@pytest.fixture(scope="session", autouse=True)
def _isolate_quality_db():
    """테스트는 **사용자의 Quality DB**(`reports/quality.sqlite`)에 쓰지 않는다.

    실측(2026-09-07): 라이브 2,058행 중 swut 1,338행의 **1,327행**이 `project_root='HDPDM01'` ·
    `statement_coverage_pct=0.0` 인 픽스처 서명이었고, 2.5초 간격으로 두 건씩(= 스위트 한 번) 쌓여 있었다.
    라우터 테스트가 `/api/swreport/summary/build` 같은 **실 경로**를 태우는데 `record_run` 이
    `db_path` 없이 기본 경로(`config.DEFAULT_REPORT_DIR/quality.sqlite`)로 떨어지기 때문이다.

    그 행들은 조회 화면의 추세·KPI 에 섞이고, R34 의 `superseded_by`("같은 scm·문서의 더 새로운 성공 run")
    자리를 테스트 행이 차지하며, R36 이후로는 **해시까지 붙어 검토 대상**이 된다. 게이트가 사용자 데이터를
    바꾸면 그 데이터로 잰 값은 더 이상 사실이 아니다 — 그래서 스위트 전체를 프로세스별 임시 DB 로 돌린다.

    ⚠ 개별 테스트의 `monkeypatch.setattr(qdb, "_default_db_path", ...)`(21파일)은 그대로 동작한다 —
      함수 스코프 monkeypatch 가 이 세션 값을 저장했다가 되돌린다. `db_path=` 명시 호출도 무관하다.
    """
    try:
        from workflow.quality import db as _qdb
    except ImportError:      # sqlalchemy 부재 환경 — 기록 경로 자체가 없으니 오염 위험도 없다
        yield
        return
    db_file = _TMP_ROOT / f"quality-test-{os.getpid()}.sqlite"
    mp = pytest.MonkeyPatch()
    mp.setattr(_qdb, "_default_db_path", lambda: db_file)
    _qdb.reset_engine()
    try:
        yield db_file
    finally:
        mp.undo()
        _qdb.reset_engine()
        for suffix in ("", "-wal", "-shm"):
            pathlib.Path(str(db_file) + suffix).unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def _isolate_tempfile_dir():
    """테스트는 **사용자의 %TEMP%** 를 건드리지 않는다 — `tempfile` 의 기본 디렉터리를 세션별 폴더로. (R51 N42)

    실측(2026-09-15): 요구 문서 실체화 루트(`%TEMP%/devops_reqdoc_*`)에 "주인 프로세스가 죽은 루트 청소" 를 넣자,
    `materialize_via_resolver` 를 태우는 테스트가 **실제 %TEMP%** 에서 청소를 돌렸다. 정상 코드는 죽은 루트만 지웠지만
    뮤테이션 한 판(나이 조건 제거)이 **살아 있는 백엔드의 루트까지 28개 전부** 지웠다 — 테스트가 기계 상태를 바꾸면
    그 뒤의 모든 측정이 오염된다(Quality DB·채팅 DB 격리와 같은 축). `_materialize_root()` 는 `tempfile.mkdtemp` /
    `tempfile.gettempdir()` 만 보므로 여기 한 곳이면 실체화·청소가 전부 세션 폴더 안에서 논다.

    ⚠ 함수 스코프 `monkeypatch.setattr(tempfile, "tempdir", …)` 은 그대로 동작한다(세션 값을 저장했다 되돌린다).
    ⚠ 위치는 **저장소 밖**(시스템 temp 아래 세션 폴더)이어야 한다 — `.codex_tmp` 아래 두면 "저장소 밖 경로는 403" 을
      재는 쓰기 봉인 테스트(`test_router_status_and_write_confinement`)의 탐침이 신뢰 루트 안이 돼 4건이 setup ERROR 다
      (2026-09-16 게이트 실측). 청소는 이 폴더 안의 `devops_reqdoc_*` 만 보므로 실제 %TEMP% 의 루트는 건드리지 않는다.
    """
    import shutil
    import tempfile

    prev = tempfile.tempdir
    root = Path(tempfile.gettempdir()) / f"devops-tests-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(root)
    try:
        yield root
    finally:
        tempfile.tempdir = prev
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _isolate_chat_history_db():
    """테스트는 **사용자의 채팅 이력 DB**(`reports/chat_history.sqlite`)에 쓰지 않는다. (R41 N11)

    ⚠ 앞판의 격리는 **전역 싱글톤 고정**에 기대고 있었다: 각 테스트가 `reset_engine()` 후
      `init_db(tmp)` 를 불러 모듈 전역 `_engine` 을 임시 경로로 박아 두면, 그 뒤 `db_path` 를
      **안 주는** 호출(`get_session()` 등)도 따라왔다. 그건 "첫 호출이 tmp 였다" 에 의존하는
      **순서 취약** 방어다 — 다른 테스트가 먼저 라이브 경로로 열면 그때부터 전부 라이브로 간다.
      게다가 경로별 캐시가 없어 회복 지점도 없었다.

    R41 이 `chat_history_db` 를 `workflow/quality/db.py` 와 같은 **경로별 캐시**로 바꾸면서
    그 우연한 방어가 사라졌으므로(= `db_path` 없는 호출은 기본 경로로 간다), 격리를
    `_default_db_path` 를 갈아끼우는 **명시적인 방식**으로 옮긴다 — `_isolate_quality_db` 와 같은 형태.
    """
    try:
        from backend.services import chat_history_db as _chat
    except ImportError:      # sqlalchemy 부재 환경 — 쓰기 경로 자체가 없다
        yield
        return
    db_file = _TMP_ROOT / f"chat-history-test-{os.getpid()}.sqlite"
    mp = pytest.MonkeyPatch()
    # ⚠ **원본을 여기서 보존한다.** 함수 스코프 fixture 들도 같은 이름을 갈아끼우는데, 그들이
    #   보존하면 이미 격리된 값을 "원본" 으로 잡는다 — 기본 경로 계약을 재는 테스트가
    #   자기 격리를 검사하게 된다(실측으로 그렇게 실패했다). 세션이 가장 먼저이므로 여기가 맞다.
    mp.setattr(_chat, "_default_db_path_original", _chat._default_db_path, raising=False)
    mp.setattr(_chat, "_default_db_path", lambda: db_file)
    _chat.reset_engine()
    try:
        yield db_file
    finally:
        mp.undo()
        _chat.reset_engine()
        for suffix in ("", "-wal", "-shm"):
            pathlib.Path(str(db_file) + suffix).unlink(missing_ok=True)


#: 사용자 **설정 파일** 세션 격리 — `(모듈 경로, 상수 이름, 임시 파일명)`.
#: 위 `_REPORT_DIR_TARGETS`(디렉터리)와 달리 파일 하나씩이라 표를 따로 둔다.
_CONFIG_FILE_TARGETS = (
    ("backend.services.file_mode_store", "MODE_PATH", "file_mode.json"),
    ("backend.services.cloudium_extra_prefixes", "PREFIXES_PATH", "cloudium_extra_prefixes.json"),
)


@pytest.fixture(scope="session", autouse=True)
def _isolate_config_files():
    """테스트는 **사용자의 `config/` 설정 파일**을 고쳐 쓰지 않는다. (R41 N12)

    ⚠ R38 감사가 짚은 자리다: `test_admin_gate.py` 가 admin 자격으로
      `POST /api/file-mode/add-allowed-prefix {"prefix":"U:/test"}` 를 **실제로 호출**한다.
      지금 안전한 이유는 경로 격리가 아니라 **resolver 가 local 로 고정돼 핸들러가 400 에서
      반환**하기 때문이다 — 누가 그 테스트에 cloudium resolver fixture 를 붙이는 순간
      사용자 `config/cloudium_extra_prefixes.json`(3,677B)에 쓴다.
      "지금 안 터진다" 가 격리가 아니다.

    `file_mode.json` 도 같은 축이다 — 파일 모드는 **영속**이라(`영속 > env > local`)
    테스트가 한 번 바꾸면 다음 기동까지 남는다.
    """
    root = _TMP_ROOT / f"config-test-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    mp = pytest.MonkeyPatch()
    skipped: list[str] = []
    for mod_path, attr, fname in _CONFIG_FILE_TARGETS:
        try:
            mod = __import__(mod_path, fromlist=["_"])
        except ImportError as exc:
            skipped.append(f"{mod_path}.{attr}({type(exc).__name__})")
            continue
        mp.setattr(mod, attr, root / fname, raising=True)
    if skipped:
        print(f"\n[config 격리] DISABLED {len(skipped)}건 — {', '.join(skipped)}")
    try:
        yield root
    finally:
        mp.undo()
        # (R44 리뷰 W6) 세션 루트도 같은 해제를 거친다 — `.run_lock_*.flock` 이 실제로
        # 만들어지는 자리가 여기다(`reports-test-<pid>/impact_audit`). 배선이 `tmp_path` 에만
        # 있으면 락 갈래가 정작 락이 사는 트리에서 발화하지 않는다.
        _cleanup_tree(root)


#: 세션 격리 대상 — `(모듈 경로, 상수 이름, 하위 디렉터리 이름)`. **여기 없는 경로는 격리되지 않는다.**
#: 새 산출 디렉터리를 만들면 이 표에 한 줄을 더하고, 아래 `test_report_dirs_are_isolated.py` 의
#: 전수 가드가 "코드가 쓰는 `reports/` 하위 == 이 표" 를 강제한다(손으로 든 목록은 반드시 빠진다).
_REPORT_DIR_TARGETS = (
    ("workflow.impact_changes", "CHANGE_DIR", "impact_changes"),
    ("workflow.impact_audit", "AUDIT_DIR", "impact_audit"),
    ("backend.routers.qac", "QAC_IMPACT_DIR", "qac_impact"),
    ("backend.routers.impact", "UDS_REPORT_DIR", "uds"),
    # ⚠ 이 줄은 **가드가 찾아냈다**. 감사가 짚은 4개만 넣고 끝냈다가, 전수 스캔에서
    #   `impact_jobs`(249개 누적)가 빠져 있는 걸 발견했다 — 손으로 든 목록은 빠진다는 것을
    #   같은 라운드 안에서 그대로 재현한 셈이다. 그래서 `test_report_dirs_are_isolated.py` 가
    #   "`reports/` 하위를 가리키는 모듈 상수 전수 == 이 표" 를 강제한다.
    ("workflow.impact_jobs", "JOB_DIR", "impact_jobs"),
    # (R38 리뷰 W-1) 재생성 산출 2곳 — 부르는 테스트가 아직 없어 유출은 0이었지만, 인라인
    # 리터럴이라 **부르는 순간** 사용자 트리에 쓴다. 가드가 못 보던 자리라 리뷰가 짚었다.
    ("workflow.impact_orchestrator", "SUTS_REPORT_DIR", "suts"),
    ("workflow.impact_orchestrator", "SITS_REPORT_DIR", "sits"),
    # (R39) **두 번째 산출 트리** `backend/reports/` — R38 리뷰 I-5 가 짚은 자리다.
    # D-1 의 "전량 1회당 24개" 는 top-level `reports/` 만 잰 값이라 이쪽 유출은 세지도 않았다.
    ("workflow.impact_orchestrator", "UDS_LOCAL_REPORT_DIR", "uds_local"),
    ("workflow.uds_ai", "UDS_AI_DIAG_DIR", "uds_ai_diagnostics"),
)


@pytest.fixture(scope="session", autouse=True)
def _isolate_report_dirs():
    """테스트는 **사용자의 `reports/` 트리**에 쓰지 않는다.

    R36 이 `reports/quality.sqlite` 한 곳에 격리를 넣었는데, 같은 결함이 `reports/` 하위 4개
    디렉터리에 그대로 남아 있었다 — 그리고 **분모가 8배 크고 사용자 화면에 직결**된다.
    실측(2026-09-08, R38 D-1): 전량 실행 1회당 24개 파일이 새로 생기고, 누적은
    `impact_changes` 11,128 · `impact_audit` 4,906 · `uds` 3,638 · `qac_impact` 1,586 이며
    그중 `qac_impact` 는 **1,586개 중 1,585개**가 테스트 산물(실물 1건)이었다.

    왜 화면이 틀어지나: `build_timeline(scm_id, limit=200)` 이 이 파일들을 시각 역순으로 읽는다.
    픽스처가 매 실행마다 새 타임스탬프로 쌓이므로 **최신 200건을 100% 점유**했고, HDPDM01 의
    실제 영향분석 이력 735건은 화면에서 완전히 사라졌다(`distinct_changed_functions` 9 vs 대조군
    kjpds02_pv 821). 그 값은 `ProjectSummarySection.jsx` 가 *"배너의 유일한 출처"* 라고 적은
    경로이고 `summary_insight.py` 가 **AI 인사이트 입력**으로도 읽는다.

    ⚠ 왜 세션 autouse 인가 — 개별 `monkeypatch.setattr(…CHANGE_DIR…)` 이 이미 **47곳**에 있었는데
      **3파일이 빠져서** 유출이 계속됐다. 파일 목록을 손으로 드는 격리는 반드시 빠진다.
      함수 스코프 monkeypatch 는 이 세션 값을 저장했다 되돌리므로 기존 47곳은 그대로 동작한다.
    """
    root = _TMP_ROOT / f"reports-test-{os.getpid()}"
    mp = pytest.MonkeyPatch()
    patched: list[str] = []
    skipped: list[str] = []
    for mod_path, attr, sub in _REPORT_DIR_TARGETS:
        try:
            mod = __import__(mod_path, fromlist=["_"])
        except ImportError as exc:
            # 의존성 부재 환경(sqlalchemy·fastapi 등) — 그 모듈의 쓰기 경로 자체가 없으니 위험도 없다.
            # ⚠ 그래도 **침묵하지 않는다**(R38 리뷰 I-1). 빈 출력을 "격리됨" 으로 읽는 것이
            #   이 저장소가 반복해 고친 fake-green 패턴이다.
            skipped.append(f"{mod_path}.{attr}({type(exc).__name__})")
            continue
        target = root / sub
        target.mkdir(parents=True, exist_ok=True)
        mp.setattr(mod, attr, target, raising=True)
        patched.append(f"{mod_path}.{attr}")
    if skipped:
        print(f"\n[reports 격리] DISABLED {len(skipped)}건 — {', '.join(skipped)} "
              f"(적용 {len(patched)}건)")
    try:
        yield root
    finally:
        mp.undo()
        # (R44 리뷰 W6) 세션 루트도 같은 해제를 거친다 — `.run_lock_*.flock` 이 실제로
        # 만들어지는 자리가 여기다(`reports-test-<pid>/impact_audit`). 배선이 `tmp_path` 에만
        # 있으면 락 갈래가 정작 락이 사는 트리에서 발화하지 않는다.
        _cleanup_tree(root)


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


@pytest.fixture(autouse=True)
def _isolate_account_audit(tmp_path_factory, monkeypatch):
    """(R48-a) 계정 감사 로그(`reports/account_audit.jsonl`)를 프로덕션 밖으로 — 테스트가 실 감사 기록에 159행을 썼다(실측).

    `_isolate_report_dirs` 표는 서비스가 **모듈 로드 시점**에 굳힌 경로만 다루고, 이 모듈은 호출 시점에 `config` 를 읽으므로
    함수 자체를 tmp 경로로 덮는다(N14 계열 — 프로덕션 데이터 디렉터리에 테스트가 쓰지 않는다).
    """
    try:
        from backend.services import account_audit as aa
    except ImportError:
        return
    p = tmp_path_factory.mktemp("account_audit") / "account_audit.jsonl"
    monkeypatch.setattr(aa, "audit_path", lambda: p)


@pytest.fixture(autouse=True)
def _default_approvers(tmp_path_factory, monkeypatch):
    """(R48-a) 승인자 목록도 머신 상태(`config/approvers.json`)에서 격리한다 — 기본은 **빈 목록**.

    `_default_admin_users` 와 같은 규약: 파일별 fixture 가 `APPROVERS_PATH` 를 다시 덮으면 그쪽이 이긴다.
    빈 목록이 기본인 이유: 검토 쓰기 권한이 "admin 또는 승인자" 로 넓어졌으므로, 실 머신에 등록된 승인자가
    테스트의 403 기대를 조용히 200 으로 바꿀 수 있다.
    """
    tmp = tmp_path_factory.mktemp("approvers_default")
    p = tmp / "approvers.json"
    p.write_text('{"approvers": [], "schema_version": 1}', encoding="utf-8")
    try:
        from backend.services import approvers as ap
    except ImportError:
        return
    monkeypatch.setattr(ap, "APPROVERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(ap, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(ap, "_LOCK", threading.Lock())
    ap._cache["mtime"] = 0.0
    ap._cache["approvers"] = set()


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
