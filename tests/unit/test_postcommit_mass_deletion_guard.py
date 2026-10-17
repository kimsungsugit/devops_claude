# tests/unit/test_postcommit_mass_deletion_guard.py
"""`.githooks/post-commit` 의 **대량 삭제 조기 경보** 계약.

## 왜 이 테스트가 있나

2026-07-23~08-25 사이 이 저장소에서 **6회** 같은 사고가 났다: 커밋이 진행되는 동안
인덱스가 다른 내용으로 갈아끼워지면, git 은 그 순간의 인덱스를 **아무 경고 없이**
커밋한다. 결과는 "추적 파일 1,208개 삭제" 커밋인데 화면에는 오류가 한 줄도 안 나온다
(실측: `04cf6a9`·`c19290a`, 2026-08-25 — 트리에 3파일만 남았다).

⚠ **pre-commit 으로는 구조적으로 못 잡는다.** 훅이 끝난 *뒤* 인덱스가 바뀌어도
그대로 커밋되기 때문이다. 통제 실험으로 확인했다(git 2.52, 스크래치 저장소):

    A 정상 pathspec 커밋                      → 트리 9파일 ✅
    B 훅이 인덱스를 비운 뒤 pathspec 커밋      → 트리 0파일 · 9 deletions · 오류 0줄
    C 훅이 인덱스를 2파일로 갈아끼움 + pathspec → 트리 = 그 2파일
    D 같은 조건 + **pathspec 없음**            → 트리 = **똑같이 그 2파일**

D 가 핵심이다 — **pathspec 은 원인이 아니다.** 그래서 사후(post-commit) 검증만이
유일하게 믿을 수 있는 지점이고, 이 훅이 그것을 자동화한다.

⚠ 동등 뮤턴트 기록: 배너의 `>&2` 를 지워도 테스트가 안 깨진다. **테스트 공백이
아니다** — git 은 훅의 stdout 을 자기 stderr 로 넘긴다(실측: 훅에서 `echo` 한 문자열이
`git commit` 의 stdout 에는 0회·stderr 에는 1회). `>&2` 는 훅을 단독 실행할 때를 위한
명시이므로 남겨 둔다. 이 줄이 없으면 다음 사람이 같은 뮤턴트를 다시 쫓는다.

판정: 삭제 ≥ 50건 **AND** 트리가 직전의 1/4 미만으로 축소. 사고의 특징은 "많이
지워짐" 이 아니라 **"거의 아무것도 안 남음"** 이다(실측 1,211 → 3). 처음엔 "삭제가
남은 트리보다 많으면" 으로 뒀다가 **아래 음성 대조군이 오탐을 잡아냈다**(121개 중
55개 삭제 = 45% 에 경보). 규칙을 실제 신호에 맞춰 좁혔다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / ".githooks" / "post-commit"
_CHAIN_MARKER = "# AutoReport chained post-commit hook"


@pytest.fixture(scope="module")
def hook_src() -> str:
    if not _HOOK.is_file():
        pytest.skip(f"post-commit 훅이 없다: {_HOOK}")
    return _HOOK.read_text(encoding="utf-8", errors="replace")


class TestHookStructure:
    def test_chain_to_autoreport_is_preserved(self, hook_src):
        """가드를 얹으면서 AutoReport 체이닝을 끊으면 안 된다 — Jira 큐가 조용히 죽는다.

        ⚠ 부분문자열로만 보면 **주석 처리된 줄도 통과한다**(뮤테이션 M7 이 그걸로 살아
        남았다: `# exec "D:/..."` 에도 그 문자열이 그대로 들어 있다). 줄 단위로 본다.
        """
        assert _CHAIN_MARKER in hook_src
        live = [
            ln for ln in hook_src.splitlines()
            if ln.lstrip().startswith("exec ")
            and "AutoReport/.githooks/post-commit" in ln
        ]
        assert len(live) == 1, (
            "AutoReport 체이닝이 살아 있는 `exec` 줄로 정확히 한 번 있어야 한다 "
            f"(발견 {len(live)}개 — 주석 처리됐을 수 있다)"
        )

    def test_guard_runs_before_the_exec(self, hook_src):
        """`exec` 는 프로세스를 갈아끼운다 — 그 뒤에 두면 가드가 **영원히 안 돈다**."""
        assert hook_src.index("git show --name-status") < hook_src.index("exec ")

    def test_threshold_requires_both_conditions(self, hook_src):
        """절대수만 보면 정상 리팩터를, 비율만 보면 작은 저장소를 오탐한다."""
        assert "-ge 50" in hook_src, "절대수 하한이 없으면 작은 저장소가 오탐된다"
        assert "_guard_left * 4" in hook_src, "축소 비율 조건이 없으면 정상 리팩터가 오탐된다"


def _sh() -> str:
    for cand in ("sh", "bash"):
        p = shutil.which(cand)
        if p:
            return p
    pytest.skip("sh/bash 없음 — 행동 검증 생략")


def _guard_only(hook_src: str) -> str:
    """AutoReport 체이닝을 뺀 가드 부분만. 임시 저장소에서 외부 훅을 부르면 안 된다."""
    return hook_src.split(_CHAIN_MARKER)[0]


def _run(repo: Path, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, **kw)


@pytest.fixture
def repo(tmp_path: Path, hook_src: str) -> Path:
    sh = _sh()
    r = tmp_path / "r"
    r.mkdir()
    _run(r, "init", "-q", ".")
    _run(r, "config", "user.email", "t@t")
    _run(r, "config", "user.name", "t")
    _run(r, "config", "core.autocrlf", "false")
    for i in range(1, 121):
        (r / f"f{i}.txt").write_text("v1\n", encoding="utf-8")
    (r / "keep.txt").write_text("k\n", encoding="utf-8")
    _run(r, "add", "-A")
    _run(r, "commit", "-qm", "base")
    hooks = r / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "post-commit").write_text(
        "#!/bin/sh\n" + _guard_only(hook_src) + "\nexit 0\n", encoding="utf-8", newline="\n",
    )
    (hooks / "post-commit").chmod(0o755)
    r_sh = r  # noqa: F841 - sh 존재만 확인하면 된다
    assert sh
    return r


def _on_screen(res: subprocess.CompletedProcess) -> bool:
    """사람이 실제로 보는 채널. ⚠ 로그 파일과 **OR 로 묶지 말 것** — 묶었더니
    경보 문구를 지우는 뮤테이션(M5)이 살아남았다(로그만 남아도 통과했다)."""
    return "경고" in (res.stderr or "")


def _logged(repo: Path) -> bool:
    return (repo / ".git" / "mass-deletion-alarm.log").exists()


def _alarmed(res: subprocess.CompletedProcess, repo: Path) -> bool:
    """음성 대조군용 — 두 채널 중 **어느 하나라도** 뜨면 오탐이다."""
    return _on_screen(res) or _logged(repo)


class TestGuardBehaviour:
    def test_ordinary_commit_is_silent(self, repo):
        """음성 대조군 — 평범한 1파일 수정에 경보가 뜨면 아무도 안 읽게 된다."""
        (repo / "f1.txt").write_text("v2\n", encoding="utf-8")
        _run(repo, "add", "f1.txt")
        res = _run(repo, "commit", "-m", "ordinary")
        assert not _alarmed(res, repo), res.stderr

    def test_legit_refactor_deletion_is_silent(self, repo):
        """음성 대조군 — 121개 중 55개 삭제(45%)는 정상 리팩터다.
        이 대조군이 최초 임계("삭제 > 남은 트리")의 오탐을 실제로 잡아냈다."""
        _run(repo, "rm", "-q", *[f"f{i}.txt" for i in range(1, 56)])
        res = _run(repo, "commit", "-m", "refactor")
        assert not _alarmed(res, repo), res.stderr

    def test_index_swap_raises_the_alarm(self, repo):
        """양성 — 인덱스 교체 사고를 재현하면 반드시 경보가 떠야 한다."""
        pre = repo / ".git" / "hooks" / "pre-commit"
        pre.write_text(
            "#!/bin/sh\ngit read-tree --empty\ngit add keep.txt\nexit 0\n",
            encoding="utf-8", newline="\n",
        )
        pre.chmod(0o755)
        (repo / "f2.txt").write_text("v9\n", encoding="utf-8")
        _run(repo, "add", "f2.txt")
        res = _run(repo, "commit", "-m", "boom")
        left = _run(repo, "ls-tree", "-r", "HEAD", "--name-only").stdout.split()
        assert left == ["keep.txt"], f"사고 재현 실패 — 트리에 {len(left)}개 남음"
        assert _on_screen(res), (
            "화면에 경보가 안 뜬다 — 1,208개가 지워져도 조용하던 그 상태 그대로다"
        )
        assert _logged(repo), "로그에도 안 남으면 나중에 되짚을 근거가 없다"

    def test_alarm_records_the_numbers(self, repo):
        """경보가 '무언가 잘못됨'만 말하면 다음 사람이 다시 세야 한다 — 수치를 남긴다."""
        pre = repo / ".git" / "hooks" / "pre-commit"
        pre.write_text(
            "#!/bin/sh\ngit read-tree --empty\ngit add keep.txt\nexit 0\n",
            encoding="utf-8", newline="\n",
        )
        pre.chmod(0o755)
        _run(repo, "commit", "--allow-empty", "-m", "boom2")
        log = (repo / ".git" / "mass-deletion-alarm.log").read_text(encoding="utf-8")
        assert "deleted=120" in log and "left=1" in log, log
