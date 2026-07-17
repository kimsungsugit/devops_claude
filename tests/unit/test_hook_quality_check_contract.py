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
    r = subprocess.run(
        [_hook_env.project_py(), str(_SCRIPT), "--json", *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(_ROOT),
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
