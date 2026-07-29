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
        """대조군: 원래 있던 '테스트 실패 → 중단'이 살아 있어야 한다."""
        assert re.search(r"Unit tests failed.*?\n\s*exit 1", hook_src, re.S), \
            "테스트 실패 시 중단이 사라졌다"


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
