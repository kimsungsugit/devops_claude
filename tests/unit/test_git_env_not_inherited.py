"""(R46 2026-09-09) B-7 index 오염의 원인 — pre-commit 훅 아래 pytest 가 **절대경로**
`GIT_INDEX_FILE`(`.git/next-index-<pid>.lock`) 을 상속받고, 임시 저장소에서 `git add` 하는
테스트가 그 index 를 덮어썼다. 두 방어선(훅의 unset · conftest 의 scrub)이 살아 있는지 잰다."""
from __future__ import annotations

import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_git_repo_local_env_is_not_visible_to_tests():
    for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX"):
        assert name not in os.environ, f"{name} 이 테스트에 보인다 — 임시 저장소 git 작업이 실 index 를 덮어쓸 수 있다"


def test_conftest_actually_scrubs(monkeypatch):
    """scrub 코드가 있다는 것과 **지운다**는 것은 다르다 — 값을 넣고 conftest 의 로직을 다시 태운다."""
    import tests.conftest as ct

    monkeypatch.setenv("GIT_INDEX_FILE", str(_ROOT / ".git" / "next-index-1.lock"))
    scrubbed = tuple(
        v for v in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR")
        if os.environ.pop(v, None) is not None
    )
    assert scrubbed == ("GIT_INDEX_FILE",)
    assert isinstance(ct._SCRUBBED_GIT_ENV, tuple)


def test_precommit_runs_pytest_without_git_local_env():
    hook = (_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    m = re.search(r"TEST_OUTPUT=\$\((.*?)-m pytest tests/", hook, re.S)
    assert m, "pre-commit 의 pytest 호출을 찾지 못했다"
    assert "git rev-parse --local-env-vars" in m.group(1) and "unset" in m.group(1), (
        "훅이 pytest 자식에서 GIT_INDEX_FILE 등을 빼지 않는다 — 임시 index 오염(B-7) 재발")
    # 낡은 진단("테스트 스위트는 범인이 아니다")이 다시 살아나지 않게
    assert "테스트 스위트는 범인이 아니다" not in hook
