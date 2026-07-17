"""훅 스크립트 공용 환경 해석 — 인터프리터 선택과 침묵 degrade 탐지.

훅은 정리된 PATH를 가진 셸에서 뜨기 때문에 맨 `python`이 mingw python으로
해석된다. 그 인터프리터에는 ruff / bcrypt가 없어서 두 가지 fake-green이 났다:
(1) `python -m ruff` 가 **빈 stdout**을 남기고 실패 → 호출부가 "clean"으로 읽음,
(2) pytest는 설치돼 있으나 bcrypt 수집 에러로 3.5초 만에 rc=1 + "1 error" →
호출부가 마지막 줄에서 "failed"를 못 찾아 **"PASS"**로 읽음.
`.githooks/pre-commit`이 같은 함정을 bash 쪽에서 우회하고 있고, 이 모듈은
그 규칙의 Python 판이다 — 다만 **후보 목록이 완전히 같지는 않다**:
pre-commit은 `.venv` 두 곳 다음에 PATH `python`으로 떨어지고, 여기서는
`backend/.venv`를 거친 뒤 `sys.executable`로 떨어진다. 한쪽을 고치면
다른 쪽도 같이 볼 것.

`python scripts/<hook>.py`로 실행되므로 sys.path[0] == scripts/ 이고,
따라서 `import _hook_env`는 별도 경로 설정 없이 동작한다.
`DEVOPS_HOOK_PY` 로 인터프리터를 강제 지정할 수 있다(진단·CI용).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: 도구(ruff)·의존성(bcrypt)이 모두 갖춰진 순서대로 후보를 나열한다.
_CANDIDATES = (
    _ROOT / ".venv" / "Scripts" / "python.exe",
    _ROOT / ".venv" / "bin" / "python",
    _ROOT / "backend" / ".venv" / "Scripts" / "python.exe",
    _ROOT / "backend" / ".venv" / "bin" / "python",
)


def project_py() -> str:
    """프로젝트 venv 인터프리터 경로. 못 찾으면 현재 인터프리터로 폴백.

    폴백해도 `module_missing()`이 DISABLED로 표면화하므로 침묵 green은 없다.
    `DEVOPS_HOOK_PY`가 실재 파일을 가리키면 그것을 최우선으로 쓴다
    (`QUALITY_CHECK_BUDGET`/`QUALITY_CHECK_FORCE`와 같은 env override 관례).
    """
    override = os.environ.get("DEVOPS_HOOK_PY")
    if override and Path(override).is_file():
        return override
    for cand in _CANDIDATES:
        if cand.is_file():
            return str(cand)
    return sys.executable


def module_missing(r: subprocess.CompletedProcess) -> bool:
    """`python -m <mod>` 에서 **그 도구 자체가** 없어서 실패했는지 — 침묵 degrade 방지용.

    stderr에 "No module named"가 있는지만 보면 **사용자 코드의**
    ModuleNotFoundError까지 삼킨다. 예: conftest.py가 없는 패키지를 import하면
    pytest는 rc=4 + stderr에 `ModuleNotFoundError: No module named 'x'` 를 내는데,
    그걸 "pytest 미설치"로 보고하면 개발자를 venv 디버깅으로 오도한다.
    runpy가 도구 부재에 내는 시그니처는 stderr **마지막 줄**의
    `No module named <mod>` (따옴표 없음)이므로 거기에 앵커한다.
    """
    if r.returncode == 0:
        return False
    tail = (r.stderr or "").strip().splitlines()
    if not tail:
        return False
    # runpy: "C:/...python.exe: No module named ruff"
    # 사용자 코드: "ModuleNotFoundError: No module named 'bcrypt'"  ← 따옴표 있음
    last = tail[-1]
    return "No module named" in last and "ModuleNotFoundError" not in last
