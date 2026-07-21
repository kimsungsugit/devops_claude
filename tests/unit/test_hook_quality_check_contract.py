"""scripts/quality_check.py `--json` 계약 — Stop 훅 ↔ /start-work 링크.

핵심 계약:
  1. `--json` 은 **top-level** 에 `counts.critical` 을 낸다.
     소비자(`.claude/skills/start-work/SKILL.md`)가 `result["counts"]["critical"]`
     로 읽어 Gate 5 루프의 진행/정체를 판정한다.
  2. `verified` / `not_run` 을 **항상** 낸다(조기종료 경로 포함).
     `critical == 0` 은 "검증했고 깨끗함"이 아니라 "Critical 로 분류된 게 없음"일
     뿐이다 — 도구 부재·타임아웃·대응 테스트 없음은 Critical 이 아니어서
     **아무것도 안 돌렸는데 critical==0** 이 나온다. 소비자는
     `.get("verified", True)` 로 읽으므로 이 키가 **빠지면 fail-open**(= 아무것도
     안 돌렸는데 "검증됨"으로 통과)이 된다.
  3. `not_run` 의 값은 `_NOT_RUN_STATES` 에 속한 상태만 담고, RAN 상태
     (`clean` / `PASS …` / `FAIL` / `N issues`)는 절대 담지 않는다.

왜 subprocess 인가:
`quality_check.py` 는 `__main__` 가드 없이 top-level 에서 게이트를 돌리고
`sys.exit()` 를 부른다 → **import 하면 그 자리에서 전체 배터리가 돌고 프로세스가
죽는다**. 그래서 이 파일만 실제 프로세스로 띄운다(나머지 훅은 in-process).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "quality_check.py"
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _hook_env  # noqa: E402

# 소비자가 읽는 키 (start-work SKILL.md Gate 5)
_CONSUMER_KEYS = ("counts", "verified", "not_run")


def _run_json(*args: str, timeout: int = 300) -> dict:
    # QUALITY_CHECK_BUDGET 로 예산을 좁힌다 — 이 헬퍼는 **실 작업 트리**에 대고
    # quality_check.py 를 띄우는데, 트리에 이 파일(느린 tests/unit conftest 를
    # import 하는 테스트)의 미커밋 변경이 있으면 quality_check 가 그 스위트를 중첩
    # 실행해 한 번에 ~250s+ 를 먹는다 — 스테이징 시점이 정확히 그 상태라 300s
    # outer timeout 에 flaky 였다(deep-review I6). 계약 테스트는 JSON **shape** 만
    # 검사하고(도구가 budget_exceeded=NOT_RUN 로 빠져도 counts/verified/not_run
    # 형태·상호정합은 동일), round 파싱은 예산과 무관하므로 검증력은 그대로다.
    env = {**os.environ, "QUALITY_CHECK_BUDGET": "20"}
    r = subprocess.run(
        [_hook_env.project_py(), str(_SCRIPT), "--json", *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(_ROOT), env=env,
    )
    assert r.stdout.strip(), f"--json 인데 stdout 이 비었다 (rc={r.returncode}): {r.stderr[-200:]}"
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def payload() -> dict:
    """실제 트리 상태 그대로 1회 실행 — 조기종료/주경로 어느 쪽이든 계약은 같아야 한다."""
    return _run_json()


class TestConsumerContract:
    """계약 1·2 — start-work 가 읽는 키가 항상 있다."""

    def test_consumer_keys_present(self, payload):
        missing = [k for k in _CONSUMER_KEYS if k not in payload]
        assert not missing, f"소비자가 읽는 키 누락: {missing}"

    def test_counts_critical_is_int(self, payload):
        assert isinstance(payload["counts"]["critical"], int)

    def test_verified_is_bool(self, payload):
        assert isinstance(payload["verified"], bool)

    def test_not_run_is_mapping(self, payload):
        assert isinstance(payload["not_run"], dict)

    def test_verified_matches_not_run(self, payload):
        """verified 는 not_run 이 빈 경우에만 True — 두 필드가 서로 모순되면 안 된다."""
        assert payload["verified"] is (not payload["not_run"])

    def test_next_action_consistent_with_critical(self, payload):
        expected = "proceed" if payload["counts"]["critical"] == 0 else "fix_required"
        assert payload["next_action"] == expected


class TestNotRunStates:
    """계약 3 — not_run 에 RAN 상태가 섞이지 않는다."""

    def test_values_are_not_run_states(self, payload):
        import re
        src = _SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"_NOT_RUN_STATES = \{([^}]+)\}", src)
        assert m, "_NOT_RUN_STATES 를 못 찾음"
        states = set(re.findall(r'"([^"]+)"', m.group(1)))
        # 조기종료 경로는 {"all": "no_changes"} 를 쓴다 — 그것도 '안 돌림' 이다
        allowed = states | {"no_changes"}
        for k, v in payload["not_run"].items():
            assert v in allowed, f"not_run[{k}]={v!r} 이 NOT_RUN 상태가 아님"

    def test_ran_states_never_in_not_run(self, payload):
        """`clean`/`PASS …` 같은 RAN 상태가 not_run 에 들어가면 안 된다."""
        for k, v in payload["not_run"].items():
            assert not str(v).startswith("PASS"), f"not_run[{k}]={v!r} 은 RAN 상태"
            assert v != "clean", f"not_run[{k}]={v!r} 은 RAN 상태"


class TestRunnerDecodeSafety:
    """`_run` 은 서브프로세스 출력을 **utf-8 + errors=replace** 로 디코드해야 한다.

    한글 Windows 에서 npm/vitest 등이 cp949 바이트(예: 0xbe)를 뱉으면, strict
    디코드는 subprocess 의 reader thread 를 죽여 그 스트림을 **조용히 None/""** 로
    만든다(실측: 그 예외는 main 으로 전파 안 되고 buffer 만 빈다). verdict 가 빈
    stdout 을 읽으면 fail-green 이고, 실패 브랜치의 `r.stdout.strip()` 은 None 에
    AttributeError 로 게이트를 통째로 죽인다.

    encoding 을 안 박으면 text=True 는 locale.getpreferredencoding() 에 의존해,
    cp949 로케일 머신에선 git·ruff 의 UTF-8 JSON 까지 오독한다 → utf-8 **고정**이
    정본이다. 이 계약은 소스에서 직접 잠근다(되돌리면 이 테스트가 실패).
    """

    def _run_body(self) -> str:
        import re
        src = _SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"\ndef _run\(.*?(?=\ndef )", src, re.S)
        assert m, "_run 함수를 못 찾음"
        return m.group(0)

    def test_run_pins_utf8_and_replace(self):
        body = self._run_body()
        # 유일한 subprocess.run 호출(나머지는 _run 경유)에 두 인자가 다 있어야 한다.
        assert 'encoding="utf-8"' in body, "_run 이 encoding 을 utf-8 로 고정하지 않음 (로케일 의존 = cp949 오독)"
        assert 'errors="replace"' in body, "_run 이 errors=replace 를 안 씀 (cp949 바이트에 reader thread 사망 → 빈 스트림)"

    def test_replace_preserves_ascii_markers(self):
        """행동 확인 — replace 는 비-utf8 바이트가 섞여도 ASCII verdict 마커를 보존한다."""
        import subprocess as sp
        emit = [sys.executable, "-c",
                r'import sys; sys.stdout.buffer.write(b"PASS\xbe done\n")']
        r = sp.run(emit, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=30)
        assert r.stdout is not None and "PASS" in r.stdout, \
            f"replace 로도 마커가 소실됨: {r.stdout!r}"


class TestCleanTreeIsNotVerified:
    """조기종료(무변경) 경로도 계약을 지킨다 — fail-open 방지.

    `verified` 를 안 내면 소비자의 `.get("verified", True)` 가 기본값 True 로
    떨어져 **아무것도 안 돌렸는데 "검증됨"** 이 된다.
    """

    def test_no_changes_reports_unverified(self, tmp_path, monkeypatch):
        import subprocess as sp
        # 깨끗한 git 트리를 만들어 조기종료 경로를 강제
        sp.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "scripts").mkdir()
        for f in ("quality_check.py", "_hook_env.py"):
            (tmp_path / "scripts" / f).write_bytes((_ROOT / "scripts" / f).read_bytes())
        sp.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                "commit", "-qm", "init"], cwd=tmp_path, check=True)

        r = sp.run(
            [_hook_env.project_py(), "scripts/quality_check.py", "--json"],
            capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
        )
        d = json.loads(r.stdout)
        assert d.get("skipped") == "no_changes", f"조기종료 경로가 아님: {d}"
        assert d["verified"] is False, "무변경인데 verified=True → fail-open"
        assert d["not_run"], "무변경인데 not_run 이 비었다"
        assert "counts" in d, "조기종료 shape 에 counts 누락 → 소비자 파싱 실패"


class TestUntrackedFilesAreExamined:
    """untracked(아직 `git add` 안 한) 신규 파일도 검사 대상이다 — fake-green 방지.

    tracked diff 만 보던 시절엔 새로 만든 파일이 이 스크립트의 **모든 검사에서 통째로
    빠졌다**. 트리에 그 파일밖에 없으면 `changed_raw` 가 비어 조기종료(no_changes)로
    빠지고, 검사한 적 없는 채 `verified` 로 통과했다. 이 스크립트가 없애려는
    fake-green 그 자체다.

    이 테스트는 fix(untracked → ls-files 로 changed 에 편입)를 되돌리면 실패한다:
    되돌리면 untracked 뿐인 트리가 no_changes 로 조기종료해 침묵-except 가 안 잡힌다.
    """

    def _init_repo(self, root, sp):
        sp.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "scripts").mkdir()
        # §7d 침묵 검사는 _silence_check 를 import 한다 — 없으면 DISABLED 로 빠져
        # 이 테스트가 무의미해진다. 세 파일 모두 복사.
        for f in ("quality_check.py", "_hook_env.py", "_silence_check.py"):
            (root / "scripts" / f).write_bytes((_ROOT / "scripts" / f).read_bytes())
        sp.run(["git", "add", "-A"], cwd=root, check=True)
        sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                "commit", "-qm", "init"], cwd=root, check=True)

    def test_untracked_silent_except_is_caught(self, tmp_path):
        import subprocess as sp
        self._init_repo(tmp_path, sp)
        # 커밋 뒤에 놓는 untracked 신규 파일 — broad-silent except 포함.
        (tmp_path / "newmod.py").write_text(
            "def risky():\n"
            "    try:\n"
            "        do_it()\n"
            "    except Exception:\n"
            "        pass\n",
            encoding="utf-8",
        )
        r = sp.run(
            [_hook_env.project_py(), "scripts/quality_check.py", "--json"],
            capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
        )
        d = json.loads(r.stdout)
        # 1) 조기종료로 새지 않았다 — untracked 가 '변경'으로 잡혀 검사가 돌았다.
        assert d.get("skipped") != "no_changes", \
            f"untracked 뿐인 트리가 no_changes 로 조기종료 → 검사 누락: {d}"
        # 2) 그 파일의 신규 침묵-except 가 warning 으로 표면화됐다.
        sil = [i for i in d.get("issues", [])
               if "newmod.py" in str(i.get("file", "")) and "침묵" in str(i.get("message", ""))]
        assert sil, f"untracked 파일의 침묵-except 미검출 (issues={d.get('issues')})"

    def test_untracked_only_tree_is_not_verified_silently(self, tmp_path):
        """untracked 파일이 clean 이어도, '검사했다'는 사실 자체가 기록돼야 한다.

        조기종료가 아니라 실제 검사 경로를 탔음을 changed_files 카운트로 확인한다.
        """
        import subprocess as sp
        self._init_repo(tmp_path, sp)
        (tmp_path / "clean_new.py").write_text("X = 1\n", encoding="utf-8")
        r = sp.run(
            [_hook_env.project_py(), "scripts/quality_check.py", "--json"],
            capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
        )
        d = json.loads(r.stdout)
        assert d.get("skipped") != "no_changes", \
            f"untracked clean 파일도 조기종료로 새면 안 된다: {d}"


class TestRoundArg:
    """`--round` 는 start-work 루프가 1..5 로 부른다 (MAX_ROUNDS=5)."""

    @pytest.mark.parametrize("rnd", ["1", "2", "4", "5"])
    def test_rounds_parse(self, rnd):
        """round 4/5 는 예전에 argparse error → exit 2 + 빈 stdout 이라 소비자가 깨졌다.

        (round 3 은 전체 스위트를 돌려 느리므로 여기선 제외 — 별도 검증됨)
        """
        d = _run_json("--round", rnd)
        assert d["round"] == int(rnd)
        assert "critical" in d["counts"]
