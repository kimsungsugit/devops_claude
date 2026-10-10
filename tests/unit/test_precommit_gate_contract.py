# tests/unit/test_precommit_gate_contract.py
"""`.githooks/pre-commit` 3단계 게이트의 **fail-closed 계약**.

## 왜 이 테스트가 있나

pytest 단계는 `timeout 900` 으로 도는데, 예전엔 타임아웃(exit 124)을 받으면
`"Skipping — commit allowed"` 를 찍고 **커밋을 통과시켰다**. 즉 회귀를 한 줄도
안 돌린 상태가 "게이트를 지났다"로 기록된다.

이건 가상의 위험이 아니라 이미 두 번 현실이 됐다:

1. 예전 주석의 "full 회귀 ~70s" 드리프트 때문에 180s cap 이 **매번** 124 로 빠져
   게이트가 사실상 없던 시기가 있었다.
2. 스위트가 3,486개/281초(2026-07-17) → 4,638개/590초(2026-07-29)로 자라
   900s 예산까지 여유가 **310초**뿐이 됐다. 그대로 뒀으면 같은 일이 반복된다.

훅은 bash 라 in-process 로 못 부른다. 대신 **소스에서 계약을 읽어** 검사한다 —
"타임아웃 분기가 exit 1 로 끝나는가"는 텍스트로 확인 가능한 성질이다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / ".githooks" / "pre-commit"


@pytest.fixture(scope="module")
def hook_src() -> str:
    if not _HOOK.is_file():
        pytest.skip(f"pre-commit 훅이 없다: {_HOOK}")
    return _HOOK.read_text(encoding="utf-8", errors="replace")


class TestTimeoutIsFailClosed:
    def test_timeout_branch_exists(self, hook_src):
        """타임아웃(124)을 아예 안 다루면 그것도 통과다 — 분기 자체가 있어야 한다."""
        assert "-eq 124" in hook_src, "타임아웃 분기가 사라졌다"

    def test_timeout_branch_aborts(self, hook_src):
        """124 분기 안에 `exit 1` 이 있어야 한다.

        분기 본문만 잘라서 본다 — 파일 어딘가에 exit 1 이 있다는 것만으로는
        '이 분기가' 중단한다는 근거가 안 된다.
        """
        m = re.search(r"-eq 124\s*\];?\s*then(.*?)(?:^\s*elif |^\s*else\b)",
                      hook_src, re.S | re.M)
        assert m, "124 분기 본문을 못 찾았다 — 구조가 바뀌었으면 이 테스트도 갱신할 것"
        body = m.group(1)
        assert "exit 1" in body, (
            "타임아웃인데 커밋을 통과시킨다 — 회귀를 한 줄도 안 돌린 상태가 "
            f"'게이트 통과'로 기록된다. 분기 본문:\n{body}")

    def test_no_commit_allowed_wording_on_timeout(self, hook_src):
        """`commit allowed` 문구가 타임아웃 경로에 남아 있으면 회귀다."""
        m = re.search(r"-eq 124\s*\];?\s*then(.*?)(?:^\s*elif |^\s*else\b)",
                      hook_src, re.S | re.M)
        assert m
        assert "commit allowed" not in m.group(1).lower()

    def test_test_failure_still_aborts(self, hook_src):
        """대조군: 원래 있던 '테스트 실패 → 중단'이 살아 있어야 한다.

        ⚠ 예전엔 `"Unit tests failed"` 라는 **문구**를 앵커로 삼았다. 2026-08-21 에
          게이트 범위가 `tests/unit/` → `tests/unit/ tests/integration/ tests/e2e/` 로
          넓어지며 그 문구가 부정확해져 `"Tests failed"` 로 바뀌었고, **동작은 그대로인데
          이 테스트만 깨졌다.** 문구는 계약이 아니다 — 계약은 "pytest 종료코드가 0이 아니면
          커밋을 중단한다" 는 **제어 흐름**이다. 그래서 위 `test_timeout_branch_aborts` 와
          같은 방식(분기 본문을 잘라서 검사)으로 바꿨다. 느슨해진 게 아니라, 이제 문구를
          바꿔도 안 깨지고 **분기를 지우면 깨진다**.
        """
        m = re.search(r"TEST_EXIT -ne 0\s*\];?\s*then(.*?)(?:^\s*elif |^\s*else\b)",
                      hook_src, re.S | re.M)
        assert m, (
            "테스트 실패 분기(`$TEST_EXIT -ne 0`)를 못 찾았다 — 구조가 바뀌었으면 "
            "이 테스트도 갱신할 것. 분기가 사라졌다면 그게 회귀다."
        )
        body = m.group(1)
        assert "exit 1" in body, (
            "테스트가 실패했는데 커밋을 통과시킨다 — 실패한 회귀가 '게이트 통과'로 "
            f"기록된다. 분기 본문:\n{body}")


class TestParallelIsOptionalButExplicit:
    """xdist 부재를 조용히 직렬로 흡수하면 안 된다(anti-fake-green 계약)."""

    def test_xdist_presence_is_probed_not_assumed(self, hook_src):
        assert "import xdist" in hook_src, (
            "xdist 유무를 실제 import 로 확인해야 한다 — 있다고 가정하면 "
            "미설치 환경에서 `-n auto` 가 pytest 인자 오류로 죽는다")

    def test_serial_fallback_is_announced(self, hook_src):
        """직렬로 떨어졌으면 그렇다고 말해야 한다 — 예산 여유가 다르기 때문."""
        assert "직렬" in hook_src, "직렬 폴백을 사용자에게 알리지 않는다"


class TestGateStagesArePresent:
    """3단계가 통째로 사라지는 회귀를 막는다."""

    @pytest.mark.parametrize("marker", ["py_compile", "ruff_ratchet.py",
                                        "eslint_ratchet.py",
                                        "check_skill_frontmatter.py",
                                        "-m pytest"])
    def test_stage_marker_present(self, hook_src, marker):
        assert marker in hook_src, f"게이트 단계가 사라졌다: {marker}"

    def test_uses_project_venv_not_bare_python(self, hook_src):
        """맨 `python` 은 mingw 로 잡혀 ruff/bcrypt 가 없다 — 저장소가 3번 고친 함정."""
        assert "PROJECT_PY" in hook_src
        assert re.search(r'\$\{?PROJECT_PY\}?" *-m pytest|\$PROJECT_PY" -m pytest',
                         hook_src) or '"$PROJECT_PY" -m pytest' in hook_src, \
            "pytest 를 프로젝트 venv 로 안 돌린다"


# ── [4/4] index 무결성 ────────────────────────────────────────────────────────
#
# 2026-08-25 실사고: 이 훅이 **통과시킨** 커밋 2건(`04cf6a9`·`c19290a`)의 트리가 3파일뿐
# 이었고 나머지 1,208개가 삭제로 기록됐다. 워킹트리는 멀쩡했고 `--no-verify` 로는 같은
# 명령이 정상 커밋됐다 — 훅이 도는 동안 무언가가 index 를 덮어썼다는 뜻이다.
# 원인은 아직 특정 못 했다(저장소를 복제해 동일 환경에서 `pytest tests/` 7,309건을 돌렸을 때
# index 는 한 번도 안 변했다 — 테스트 스위트는 범인이 아니다). 원인을 모르는 채로도 결과는
# 막는다: 시작/종료 스테이징이 다르면 중단.
#
# ⚠ 이 클래스는 **소스 문자열이 아니라 동작**을 시험한다. 훅에서 가드 두 조각을 그대로
#   떼어내 임시 저장소의 진짜 pre-commit 으로 돌린다 — 문구만 남고 로직이 죽는 경우
#   (뮤테이션 생존)를 막기 위해서다.
_GUARD_BEFORE_RE = re.compile(r"^# 0b\..*?^STAGED_STATUS_BEFORE=.*?$", re.S | re.M)
_GUARD_AFTER_RE = re.compile(r"^# 4\. index 무결성.*?^set -e$", re.S | re.M)


def _git_env() -> dict:
    """git 이 '다른 저장소로 갈 때 지우라'고 지정한 변수를 제거한 환경.

    pre-commit 훅 아래에서 pytest 가 돌면 `GIT_INDEX_FILE` 등이 상속된다. 상대경로면
    무해했지만(실측), 절대경로가 섞이는 순간 임시 저장소에 건 `git add` 가 **실 저장소
    index 를 덮어쓴다**(1,212→3 실증). 진단 도구가 진단 대상을 망가뜨리지 않게 잘라낸다.
    """
    import os
    import subprocess as sp

    env = dict(os.environ)
    names = sp.run(["git", "rev-parse", "--local-env-vars"],
                   capture_output=True, text=True).stdout.split()
    for n in names or ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX"):
        env.pop(n, None)
    return env


class TestIndexIntegrityGateIsFailClosed:
    def test_guard_fragments_exist(self, hook_src):
        """가드가 통째로 사라지면 아래 동작 시험이 조용히 skip 되므로 먼저 존재를 고정한다."""
        assert _GUARD_BEFORE_RE.search(hook_src), "시작 시점 스테이징 기록(# 0b)이 없다"
        assert _GUARD_AFTER_RE.search(hook_src), "종료 시점 대조(# 4)가 없다"

    @pytest.mark.parametrize(
        ("label", "middle", "expect_rc"),
        [
            ("대조군 — 게이트가 index 를 안 건드림", "", 0),
            ("뮤테이션 — 게이트 도중 index 가 비워짐", "git read-tree --empty\n", 1),
        ],
    )
    def test_guard_blocks_only_when_index_changes(
        self, hook_src, tmp_path, label, middle, expect_rc
    ):
        import shutil
        import subprocess as sp

        if not shutil.which("bash") or not shutil.which("git"):
            pytest.skip("bash/git 없음")

        before = _GUARD_BEFORE_RE.search(hook_src).group(0)
        after = _GUARD_AFTER_RE.search(hook_src).group(0)
        env = _git_env()

        def g(*args):
            return sp.run(["git", *args], cwd=tmp_path, capture_output=True,
                          text=True, env=env, timeout=120)

        (tmp_path / "scripts").mkdir()
        for i in range(5):
            (tmp_path / f"f{i}.txt").write_text(f"v{i}\n", encoding="utf-8")
        (tmp_path / "scripts" / "a.py").write_text("x = 1\n", encoding="utf-8")
        g("init", "-q", ".")
        g("add", "-A")
        g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

        (tmp_path / "f0.txt").write_text("changed\n", encoding="utf-8")
        g("add", "f0.txt")

        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            "#!/bin/bash\nset -e\n" + before + "\n\n" + middle + "\n" + after + "\n",
            encoding="utf-8", newline="\n",
        )
        hook.chmod(0o755)

        r = g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "probe")
        assert r.returncode == expect_rc, (
            f"{label}: rc={r.returncode} (기대 {expect_rc})\n{r.stdout}\n{r.stderr}"
        )
        if expect_rc:
            # 막았다는 사실만이 아니라 **왜** 막았는지도 말해야 사람이 복구할 수 있다.
            assert "스테이징 내용이 바뀌었다" in (r.stdout + r.stderr)
            assert "git reset --mixed" in (r.stdout + r.stderr)


# ── 훅 파일의 줄끝 ────────────────────────────────────────────────────────────
#
# `.gitattributes` 가 이미 못박아 뒀다: `.githooks/* text eol=lf`
#   "Shell scripts and git hooks must keep LF on all platforms — bash on Windows
#    (msys2 / git-bash) refuses to execute scripts with CRLF line endings."
#
# 그런데 **아무도 검사하지 않았다.** `.gitattributes` 는 커밋 시 정규화를 지시할 뿐,
# 워킹트리 파일이 CRLF 로 바뀌는 것은 못 막는다. 그리고 git 이 실행하는 것은
# 워킹트리 파일이다.
#
# 2026-08-25 실사고: Python 의 `Path.write_text()` 로 훅을 저장했더니 Windows 기본
# 개행 변환이 걸려 파일 전체가 CRLF(276줄)가 됐다. `bash -n` 은 통과하고 커밋 diff 도
# 정상으로 보인다(git 이 읽을 때 정규화하므로) — **게이트가 죽어도 화면상 증거가 없다.**
# 이 저장소가 가장 싫어하는 형태의 실패다.
class TestHookFilesKeepLf:
    def test_githooks_are_lf_in_working_tree(self):
        import subprocess as sp

        hooks_dir = _ROOT / ".githooks"
        if not hooks_dir.is_dir():
            pytest.skip(".githooks 없음")

        offenders = []
        checked = 0
        for p in sorted(hooks_dir.iterdir()):
            if not p.is_file():
                continue
            rel = p.relative_to(_ROOT).as_posix()
            # 판정은 확장자 추측이 아니라 **git 에게 묻는다** — `*.ps1 text eol=crlf` 처럼
            # CRLF 가 정답인 파일을 위반으로 오판하지 않기 위해.
            r = sp.run(["git", "-C", str(_ROOT), "check-attr", "eol", "--", rel],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
            want = r.stdout.rsplit(":", 1)[-1].strip() if r.stdout else "unspecified"
            if want != "lf":
                continue
            checked += 1
            crlf = p.read_bytes().count(b"\r\n")
            if crlf:
                offenders.append(f"{rel}: CRLF {crlf}줄")

        # 하나도 안 셌으면 이 테스트는 공허하게 통과한다 — 그것도 실패로 본다.
        assert checked > 0, ".gitattributes 가 .githooks/* 에 eol=lf 를 안 걸고 있다"
        assert not offenders, (
            "훅이 CRLF 다 — Windows bash 가 실행을 거부해 게이트가 통째로 죽는다:\n  "
            + "\n  ".join(offenders)
        )
