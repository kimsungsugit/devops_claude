"""게이트가 **모든 테스트 디렉터리**에 닿는지 고정한다.

## 왜 이게 필요한가 (2026-08-21 실사고)

`tests/integration/` 56건이 **17일 동안 전부 401 로 죽어 있었는데 아무도 몰랐다.**
게이트 4곳(pre-commit · Stop 훅 · GitHub Actions · GitLab CI)이 전부 `tests/unit/` 만
돌았기 때문이다. 스위트는 초록이었고, 그 디렉터리에는 `STS-EXPORTS-001` 같은
ISO 26262 추적성 ID 가 달려 "시험이 있다"는 문서 근거로 쓰이고 있었다.

죽은 스위트의 피해는 "회귀를 못 잡는다" 로 끝나지 않는다 — **낡은 계약을 보존한다.**
`test_api_endpoints.py` 는 `/api/run/stop` 이 임의 PID 에 200 을 주던(=백엔드를 통째로
죽일 수 있던) 시절의 기대를 그대로 갖고 있었다. 되살리며 "실패하니까" 그쪽으로
맞췄다면 취약점이 돌아왔다.

## 이 테스트가 막는 것

새 테스트 디렉터리를 만들고 게이트에 배선하지 않으면 **여기서 실패한다.**
"내가 다 찾았나?" 를 사람 기억이 아니라 유지되는 불변식으로 바꾼다
(`test_output_path_collision_sweep.py` 와 같은 패턴).

⚠ 면제하려면 아래 `_EXEMPT` 에 **사유와 함께** 적을 것. 조용히 빠지는 길은 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TESTS = _REPO / "tests"

# 게이트 파일 — 하나라도 그 디렉터리를 돌리면 '도달' 로 본다.
_GATES = {
    "pre-commit": _REPO / ".githooks" / "pre-commit",
    "GitHub Actions": _REPO / ".github" / "workflows" / "ci.yml",
    "GitLab CI": _REPO / ".gitlab-ci.yml",
}

# 면제 — **사유 필수**. 비워 두는 게 정상이다.
#
# ⚠ 면제는 "괜찮다" 가 아니라 **기록된 부채**다. 지우려면 사유가 해소돼야 한다.
_EXEMPT: dict[str, str] = {
    "test_coverage_boost.py": (
        "2026-08-21 실측: 87 passed + **20 errors / 303초**. errors 는 전부 "
        "`mock_uds_payload`·`mock_function_details` fixture 부재(저장소 어디에도 정의가 "
        "없다 — 파일 헤더 `# /app/tests/...` 가 말해주듯 옛 Docker 구성 잔재)다. "
        "fixture 를 **지어내면** 잘못된 입력으로 통과하는 테스트가 되므로 손대지 않았다. "
        "303초도 pre-commit 예산(900초, 현 사용 372초)에 넣기엔 부담이라 함께 보류한다. "
        "⚠ 해소 순서: 먼저 두 fixture 의 **정본 shape 를 찾거나 결정**하고, 그 다음 시간."
    ),
}
# ⚠ 처음엔 여기에 세 파일이 다 있었다. "루트 3파일 합계 196건 / 1 failed / 20 errors /
#   561초" 를 **한 묶음**으로 보고 같은 사유를 붙였기 때문이다. 파일별로 다시 재니
#   전혀 달랐다 — `test_quality_improvements.py` 는 25초에 전부 통과(게이트 편입),
#   `test_json_parsing.py` 는 애초에 **테스트가 0개**였다(스크립트형 fake-green — 진짜
#   테스트 7개로 승격). **합계를 인용하기 전에 분해할 것.**


def _test_dirs() -> list[str]:
    """`tests/` 바로 아래에서 `test_*.py` 를 실제로 가진 디렉터리."""
    out = []
    for d in sorted(p for p in _TESTS.iterdir() if p.is_dir()):
        if d.name.startswith((".", "__")):
            continue
        if any(d.rglob("test_*.py")):
            out.append(d.name)
    return out


def _root_test_files() -> list[str]:
    """`tests/` **바로 아래**에 놓인 test 파일.

    ⚠ 디렉터리만 세면 이걸 통째로 놓친다 — 실제로 놓쳤다. 처음 판은 `tests/*/` 만 봤고,
      `tests/` 루트의 3개 파일 **196건**이 검사 밖이었다(디렉터리 사각지대를 고치면서
      파일 사각지대를 새로 만든 셈이다).
    """
    return sorted(p.name for p in _TESTS.glob("test_*.py"))


def _gate_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _is_ignored(text: str, name: str) -> bool:
    """게이트가 `--ignore=tests/<name>` 으로 **명시 제외**하는가.

    ⚠ 이게 없으면 `pytest tests/ --ignore=tests/X` 를 보고 X 를 '도달'로 오판한다.
      게이트를 `tests/` 통째로 바꾸는 순간 모든 면제가 조용히 무효가 되는 구멍이다.
    """
    return bool(re.search(rf"--ignore=tests/{re.escape(name)}\b", text))


def _covers(text: str, name: str) -> bool:
    """pytest 호출이 이 디렉터리/파일을 실제로 돌리는가.

    `tests/<name>` 을 직접 적었거나 `tests/` 통째로 돌리면 도달 — 단
    `--ignore` 로 빠졌으면 도달이 아니다.
    """
    if _is_ignored(text, name):
        return False
    if re.search(rf"pytest[^\n]*\btests/{re.escape(name)}\b", text):
        return True
    # `pytest tests/ ...` — 하위 전부
    return bool(re.search(r"pytest[^\n]*\btests/(?![\w.-])", text))


def test_every_test_directory_is_reachable_by_some_gate():
    dirs = _test_dirs()
    roots = _root_test_files()
    assert dirs, "tests/ 밑에서 테스트 디렉터리를 하나도 못 찾았다 — 이 가드가 무력하다"

    gate_texts = {name: _gate_text(p) for name, p in _GATES.items()}
    present = [n for n, t in gate_texts.items() if t]
    assert present, f"게이트 파일을 하나도 못 읽었다: {list(_GATES)}"

    unreached = {}
    for d in dirs:
        if d in _EXEMPT:
            continue
        hit = [n for n, t in gate_texts.items() if _covers(t, d)]
        if not hit:
            unreached[d] = sorted(present)
    # 루트 직속 파일도 같은 기준으로 — 디렉터리만 세면 196건이 통째로 샌다.
    for f in roots:
        if f in _EXEMPT:
            continue
        hit = [n for n, t in gate_texts.items() if _covers(t, f)]
        if not hit:
            unreached[f] = sorted(present)

    assert not unreached, (
        "게이트가 닿지 않는 테스트 디렉터리가 있다 — 여기 있는 회귀는 "
        "**깨져도 아무도 모른다**(2026-08-21: integration 56건이 17일간 그랬다).\n"
        + "\n".join(f"  tests/{d}/  — 확인한 게이트: {', '.join(g)}" for d, g in unreached.items())
        + "\n배선할 곳: .githooks/pre-commit · .github/workflows/ci.yml · .gitlab-ci.yml\n"
        + "정말 돌리면 안 되는 디렉터리라면 이 파일의 `_EXEMPT` 에 **사유와 함께** 적을 것."
    )


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_gate_file_exists(gate_name):
    """게이트 파일이 사라지면 위 검사가 조용히 느슨해진다 — 그걸 막는다."""
    path = _GATES[gate_name]
    assert path.exists(), f"게이트 파일이 없다: {path.relative_to(_REPO)}"


def test_exemptions_carry_a_reason():
    """면제는 있어도 되지만 **이유 없이는 안 된다.**"""
    blank = [d for d, why in _EXEMPT.items() if not (why or "").strip()]
    assert not blank, f"사유 없는 면제: {blank}"


def test_exemptions_are_not_stale():
    """사라진 대상을 계속 면제하고 있으면 알려준다.

    ⚠ 면제 목록이 낡으면 "면제가 걸려 있다" 는 사실만 남고 그게 무엇을 덮고 있는지가
      흐려진다. 대상이 없어졌으면 항목도 지워야 한다.
    """
    known = set(_test_dirs()) | set(_root_test_files())
    stale = sorted(set(_EXEMPT) - known)
    assert not stale, (
        f"면제 대상이 더 이상 존재하지 않는다 — `_EXEMPT` 에서 지울 것: {stale}"
    )


def test_unit_directory_itself_is_covered():
    """자기 진단 — `tests/unit/` 조차 안 잡히면 `_covers` 정규식이 고장난 것이다.

    ⚠ 이 단언이 없으면 정규식이 **항상 False** 를 내도 위 테스트가 통과해 버린다
      (모든 디렉터리가 unreached 로 잡혀 실패할 것 같지만, `_test_dirs()` 가 빈
       목록이면 그것도 조용히 통과한다). 양성 대조군이다.
    """
    hits = [n for n, p in _GATES.items() if _covers(_gate_text(p), "unit")]
    assert hits, "`tests/unit/` 을 도는 게이트를 하나도 못 찾았다 — _covers 정규식 점검 필요"
