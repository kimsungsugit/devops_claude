"""scripts/_hook_env.py — 훅 인터프리터 해석 + 도구 부재 탐지.

핵심 계약:
  1. `module_missing()` 은 **그 도구 자체가 없어서** 실패한 경우에만 True 다.
     사용자 코드의 import 실패(`ModuleNotFoundError: No module named 'x'`)는
     False — 그걸 True 로 읽으면 "pytest 미설치" 같은 **오진**을 내서 개발자를
     애먼 venv 디버깅으로 보낸다.
  2. `project_py()` 는 도구가 갖춰진 venv 를 우선 해석하고, 못 찾으면
     현재 인터프리터로 폴백한다(폴백해도 1번이 DISABLED 로 표면화하므로
     침묵 green 은 없다).
  3. `DEVOPS_HOOK_PY` env 가 실재 파일을 가리키면 그것이 최우선이다.

배경 — 이 계약이 왜 있나:
훅은 정리된 PATH 에서 떠서 맨 `python` 이 mingw 로 잡히는데 거기엔 ruff/bcrypt 가
없다. 그때 `python -m ruff` 는 **stdout 이 비고**, 호출부가 그걸 `(stdout or "clean")`
으로 읽어 **게이트가 죽은 채 "clean" 을 보고**했다(fake-green). `module_missing()`
이 그 침묵을 DISABLED 로 바꾸는 유일한 지점이라 여기가 무너지면 게이트 전체가 무너진다.

⚠ 규칙이 **3벌**로 복제돼 있다 — `_hook_env`(정본) / `quality_check.py` 폴백 /
`posttool_dispatch.py` 폴백. 실제로 한 번 갈라졌던 이력이 있어(정본만 allowlist 로
고치고 폴백 하나를 빠뜨림) 아래 test_all_three_implementations_agree 가 셋을 묶어둔다.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _hook_env  # noqa: E402


def _cp(returncode: int, stderr: str = "", stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# runpy 가 `python -m <없는모듈>` 에 내는 실제 형식 (Windows/POSIX 공통)
_RUNPY_RUFF = "C:/msys64/mingw64/bin/python.exe: No module named ruff"
_RUNPY_POSIX = "/usr/bin/python3: No module named pytest"
# 사용자 코드가 내는 형식 — 도구는 멀쩡하고 **테스트 대상 코드**가 깨진 것
_USER_MNFE = "E   ModuleNotFoundError: No module named 'bcrypt'"
_USER_IMPORTERROR = 'ImportError("No module named legacy_thing")'


class TestModuleMissing:
    """계약 1 — 도구 부재만 True."""

    def test_runpy_missing_tool_is_true(self):
        assert _hook_env.module_missing(_cp(1, _RUNPY_RUFF)) is True

    def test_runpy_posix_form_is_true(self):
        assert _hook_env.module_missing(_cp(1, _RUNPY_POSIX)) is True

    def test_user_code_module_not_found_is_false(self):
        """실사례: mingw pytest 가 bcrypt 수집 에러로 죽었을 때.

        pytest 는 **설치돼 있다**. 이걸 True 로 읽으면 "pytest 미설치" 라고
        오진해 개발자를 venv 디버깅으로 보낸다.
        """
        assert _hook_env.module_missing(_cp(4, _USER_MNFE)) is False

    def test_user_import_error_is_false(self):
        """구 blocklist 구현(`"ModuleNotFoundError" not in ...`)이 놓치던 케이스."""
        assert _hook_env.module_missing(_cp(4, _USER_IMPORTERROR)) is False

    def test_success_is_never_missing(self):
        """rc==0 이면 stderr 내용과 무관하게 False."""
        assert _hook_env.module_missing(_cp(0, _RUNPY_RUFF)) is False

    def test_empty_stderr_is_false(self):
        assert _hook_env.module_missing(_cp(1, "")) is False

    def test_none_stderr_does_not_raise(self):
        """capture_output 없이 만든 CompletedProcess 는 stderr=None 이다."""
        assert _hook_env.module_missing(_cp(1, None)) is False  # type: ignore[arg-type]

    def test_anchored_to_last_line(self):
        """멀티라인 stderr 는 **마지막 줄** 기준.

        앞줄에 무슨 말이 있든 마지막 줄이 runpy 시그니처면 도구 부재다.
        """
        multi = "Traceback (most recent call last):\n  ...\n" + _RUNPY_RUFF
        assert _hook_env.module_missing(_cp(1, multi)) is True

    def test_user_error_on_last_line_is_false(self):
        multi = "collecting ...\nE   ImportError\n" + _USER_MNFE
        assert _hook_env.module_missing(_cp(4, multi)) is False


class TestProjectPy:
    """계약 2·3 — venv 해석과 env override."""

    def test_returns_existing_file(self):
        p = _hook_env.project_py()
        assert Path(p).is_file(), f"해석된 인터프리터가 실재하지 않음: {p}"

    def test_resolved_interpreter_has_tools(self):
        """해석된 인터프리터엔 실제로 ruff 가 있어야 한다.

        이게 깨지면 게이트가 다시 DISABLED 로 떨어진다(= 오늘 고친 그 상태).
        """
        r = subprocess.run(
            [_hook_env.project_py(), "-m", "ruff", "--version"],
            capture_output=True, text=True, timeout=60,
        )
        assert not _hook_env.module_missing(r), f"ruff 없음: {r.stderr[:120]}"

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("DEVOPS_HOOK_PY", sys.executable)
        assert _hook_env.project_py() == sys.executable

    def test_env_override_ignored_when_path_missing(self, monkeypatch, tmp_path):
        """실재하지 않는 경로면 무시하고 정상 해석으로 폴백."""
        monkeypatch.setenv("DEVOPS_HOOK_PY", str(tmp_path / "nope.exe"))
        assert Path(_hook_env.project_py()).is_file()


class TestImplementationsAgree:
    """3벌로 복제된 규칙이 갈라지지 않게 묶는다.

    `_hook_env`(정본) / `quality_check.py` 폴백 / `posttool_dispatch.py` 폴백.
    폴백은 `import _hook_env` 가 실패했을 때만 쓰이므로 정상 경로 테스트로는
    안 잡힌다 → 소스에서 정규식을 뽑아 직접 대조한다.
    """

    _CASES = [
        (_cp(1, _RUNPY_RUFF), True),
        (_cp(1, _RUNPY_POSIX), True),
        (_cp(4, _USER_MNFE), False),
        (_cp(4, _USER_IMPORTERROR), False),
        (_cp(0, _RUNPY_RUFF), False),
        (_cp(1, ""), False),
    ]

    @staticmethod
    def _fallback_pattern(filename: str) -> str:
        src = (_SCRIPTS / filename).read_text(encoding="utf-8")
        m = re.search(r're\.match\(r"(\^\\S\+[^"]+)"', src)
        assert m, f"{filename} 폴백에서 module_missing 정규식을 못 찾음"
        return m.group(1)

    @pytest.mark.parametrize("filename", ["quality_check.py", "posttool_dispatch.py"])
    def test_fallback_matches_canonical(self, filename):
        pat = re.compile(self._fallback_pattern(filename))

        def fallback(r):
            tail = (r.stderr or "").strip().splitlines()
            return bool(r.returncode != 0 and tail and pat.match(tail[-1].strip()))

        for r, expected in self._CASES:
            assert _hook_env.module_missing(r) is expected, f"정본 불일치: {r.stderr!r}"
            assert fallback(r) is expected, f"{filename} 폴백 불일치: {r.stderr!r}"
