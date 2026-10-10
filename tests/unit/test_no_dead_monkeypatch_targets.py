"""테스트가 **아무도 안 읽는 상수**를 monkeypatch 하고 있지 않은가 (R43 N15).

죽은 patch 는 실패하지 않는다 — 그래서 위험하다. 다음 사람은 그 줄을 보고 "이 경로는
격리돼 있다" 고 믿는다. 실제로 `workflow.impact_audit.LOCK_PATH` 가 그랬다:

- 상수는 `legacy(하위호환 참조용)` 로 남아 있었고 **프로덕션 소비처가 0** 이었다
  (실제 락 경로는 `_get_locks` 가 호출 시점의 `AUDIT_DIR` 로 scm 별로 만든다).
- 그런데 테스트 **17곳**이 그것을 tmp 로 patch 하고 있었다. 격리는 같은 파일의
  `AUDIT_DIR` patch 가 하고 있었고, `LOCK_PATH` 줄은 한 번도 아무것도 바꾸지 않았다.

즉 "격리했다" 는 신호만 17개 있었다. 이 가드는 그 형태가 돌아오는 것을 막는다.

⚠ 검사 대상은 **모듈 최상위 상수를 patch 하는 줄**뿐이다. 함수·메서드 patch 는 호출
그래프를 봐야 하므로 여기서 판정하지 않는다(못 하는 것을 아는 척하지 않는다).
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

#: 프로덕션 스캔에서 **빼는** 것만 적는다 — 넣을 것을 손으로 들면 반드시 빠진다.
#: ⚠ (리뷰 W8) 첫 판은 7개 디렉터리를 손으로 들었고 루트 `config.py`·`main.py` 등 7파일과
#:   `cloudium_worker/`·`utils/` 가 통째로 스캔 밖이었다. 하필 `config.py` 는 이 파일의
#:   docstring 이 예로 든 상수들의 **정의 모듈**이다. 저장소 교훈 그대로의 자리라 뒤집었다.
_SKIP_DIRS = {
    "venv", ".venv", "node_modules", "site-packages", "__pycache__", ".git",
    "tests", ".codex_tmp", "frontend-v2", ".claude", "docs", "reports", "outputs",
}

#: **테스트** 스캔에서 빼는 것. 위 목록과 **같지 않다** — 여기엔 `tests` 가 없다.
#: ⚠ 한때 `_SKIP_PARTS = _SKIP_DIRS` 로 재사용했다가 테스트 파일이 전부 스킵돼
#:   검사 대상이 **0건**이 됐다(= 가드가 통째로 vacuous). 통과하는 이유가 "볼 게 없어서"
#:   였고, 뮤테이션 3개가 나란히 생존해서야 드러났다. 아래 `test_the_guard_sees_something`
#:   이 그 상태를 직접 막는다.
_SKIP_PARTS = {"venv", ".venv", "node_modules", "site-packages", "__pycache__"}

#: 죽은 patch 가 **의도된** 자리(사유 필수). 비어 있는 것이 정상이다.
_EXEMPT: Dict[Tuple[str, str], str] = {}


def _prod_files() -> List[Path]:
    """저장소의 프로덕션 `.py` **전수** — 제외 목록만 적용하고 가지치기로 걷는다.

    `rglob` 은 `backend/venv`(git 미추적 site-packages 12,562파일)를 **다 걷고 나서**
    필터하므로 느리다. `os.walk` 에서 `dirnames` 를 잘라 아예 내려가지 않는다(리뷰 I2).
    """
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath) / fn)
    # `conftest.py` 는 테스트 트리에 있지만 **하네스의 프로덕션**이다 — 격리 상수를 정의하고
    # 스스로 읽는다. 읽기 쪽에서 빼면 그 상수를 patch 하는 fixture 가 죄다 죽은 patch 로 보인다
    # (실측: `_CLEANUP_FAILURE_LOG` 하나가 그렇게 걸렸다).
    out.extend(TESTS.rglob("conftest.py"))
    return out


#: 이름을 **문자열로 받아 읽는** 함수들. 이 호출의 인자로 등장한 리터럴만 읽기로 친다.
_NAME_TAKING_CALLS = {"getattr", "hasattr", "setattr", "delattr"}
#: `os.environ["X"]` / `.get("X")` 처럼 첨자·조회로 읽는 매핑.
_NAME_TAKING_METHODS = {"get", "getenv", "pop", "setdefault"}


def _names_read_as_string_literals(tree: ast.AST) -> Set[str]:
    """**읽기 위치**에 나타난 문자열 이름만 모은다.

    ⚠ (리뷰 W7) 첫 판은 "코드 안 문자열 리터럴이면 무조건 읽기" 였다. 그러면 프로덕션
    어딘가에 그 이름이 로그 문구·SQL 조각·프롬프트 텍스트로 **한 번만** 등장해도 가드가
    영구히 눈을 감는다 — 실측 **873개** 이름이 그렇게 마스킹되고 있었고, 뮤테이션으로
    실증됐다(`_MASK = "LOCK_PATH"` 한 줄을 넣자 가드가 통과).

    그래서 위치를 좁힌다: `getattr/hasattr/setattr/delattr` 의 인자, 매핑 조회
    (`.get("X")`·`os.environ["X"]`), `globals()["X"]`. 이러면 18건 거짓 양성(전부 이
    형태였다)은 그대로 해소되면서 마스킹 표면은 사라진다.
    """
    out: Set[str] = set()

    def _add(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isupper():
            out.add(node.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            mname = getattr(node.func, "attr", None)
            if fname in _NAME_TAKING_CALLS or mname in _NAME_TAKING_METHODS:
                for a in node.args:
                    _add(a)
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            _add(sl.value if isinstance(sl, ast.Index) else sl)  # type: ignore[attr-defined]
    return out


def _names_read_by_production() -> Set[str]:
    """프로덕션 코드가 **읽는** 대문자 이름 전부.

    읽기 형태: `X` · `mod.X` · `from m import X` · **읽기 위치의 문자열 리터럴**
    (`_names_read_as_string_literals` 참조).

    ⚠ 첫 판은 앞의 셋만 봤고 그래서 거짓 양성이 18건 났다: `getattr(config,
    "UDS_QUALITY_GATE_THRESHOLDS", None)` 처럼 **이름을 문자열로 넘겨 읽는** 자리를 못 본
    것이다. 그대로 믿었다면 멀쩡한 격리 17곳을 지울 뻔했다. 두 번째 판은 반대로 너무 넓어
    (모든 리터럴) 873개를 마스킹했다 — 지금은 **읽기 위치**로 좁혔다.

    어느 모듈의 이름인지까지는 따지지 않는다(별칭·재수출 때문에 거짓 양성이 난다).
    이 가드가 잡는 것은 **아무 데서도 읽히지 않는 이름** 하나뿐이다.
    동적 이름(`getattr(mod, name)` 에서 `name` 이 변수)은 원리상 잡을 수 없다.
    """
    read: Set[str] = set()
    for p in _prod_files():
        try:
            tree = ast.parse(p.read_text("utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id.isupper():
                read.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr.isupper():
                read.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name.isupper():
                        read.add(a.name)
        read |= _names_read_as_string_literals(tree)
    return read


def _patched_constants() -> Dict[Tuple[str, str], List[str]]:
    """테스트가 patch 하는 (대상표기, 상수) → 위치 목록. **AST 로** 본다.

    ⚠ (리뷰 W6) 첫 판은 한 줄 정규식이라 실측 3형태를 놓쳤다:
      · 여러 줄로 쪼개진 같은 호출 2건(`test_jenkins_sync_credentials.py`)
      · 문자열 타깃 `monkeypatch.setattr("backend.helpers.session.SETTINGS_FILE", …)` 3건
      · 대상이 변수인 `mp.setattr(mod, attr, …)` — `conftest` 의 격리 표 12건.
    마지막이 가장 아프다: 그 표는 스스로 *"여기 없는 경로는 격리되지 않는다"* 고 선언한
    격리의 단일 출처인데, 거기 죽은 상수가 들어오는 것이 정확히 이 가드가 막겠다는 시나리오다.

    변수 대상(`mp.setattr(mod, attr, …)`)은 이름을 정적으로 알 수 없으므로, 같은 파일의
    **모듈 상수 표에 든 문자열**을 후보로 본다(그 표가 곧 patch 목록이다).
    """
    out: Dict[Tuple[str, str], List[str]] = {}
    for p in TESTS.rglob("*.py"):
        if _SKIP_PARTS & set(p.parts):
            continue
        try:
            tree = ast.parse(p.read_text("utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = p.relative_to(ROOT)

        # ① `<x>.setattr(<target>, "CONST", …)` — 줄바꿈과 무관하게 잡힌다.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or getattr(node.func, "attr", None) != "setattr":
                continue
            args = node.args
            if len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
                target = getattr(args[0], "id", None) or getattr(args[0], "attr", None) or "?"
                name = args[1].value
                if name.isupper():
                    out.setdefault((target, name), []).append(f"{rel}:{node.lineno}")
            # ② 문자열 타깃 한 개짜리: `setattr("pkg.mod.CONST", value)`
            elif args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                dotted = args[0].value
                head, _, last = dotted.rpartition(".")
                if last.isupper():
                    out.setdefault((head or "?", last), []).append(f"{rel}:{node.lineno}")

        # ③ 표 기반 patch — 모듈 상수 튜플/리스트 안의 대문자 문자열.
        if any(isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "setattr"
               and len(n.args) >= 2 and isinstance(n.args[1], ast.Name)
               for n in ast.walk(tree)):
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not isinstance(node.value, (ast.Tuple, ast.List)):
                    continue
                table = getattr(node.targets[0], "id", "?")
                for row in node.value.elts:
                    if not isinstance(row, (ast.Tuple, ast.List)):
                        continue
                    for cell in row.elts:
                        if (isinstance(cell, ast.Constant) and isinstance(cell.value, str)
                                and cell.value.isupper()):
                            out.setdefault((table, cell.value), []).append(f"{rel}:{row.lineno}")
    return out


def test_no_test_patches_a_constant_production_never_reads() -> None:
    read = _names_read_by_production()
    dead = []
    for (mod_alias, const), where in sorted(_patched_constants().items()):
        if (mod_alias, const) in _EXEMPT:
            continue
        if const not in read:
            dead.append((mod_alias, const, where[:3], len(where)))
    assert dead == [], (
        "프로덕션이 읽지 않는 상수를 테스트가 patch 하고 있다 — 격리했다는 **신호만** 남는다. "
        f"상수를 지우거나 patch 를 지울 것: {dead}"
    )


def test_exemptions_carry_a_reason() -> None:
    """면제는 사유와 한 세트다 — 빈 사유는 면제가 아니라 잊힌 자리다."""
    for key, why in _EXEMPT.items():
        assert why.strip(), f"사유 없는 면제: {key}"


def test_the_guard_sees_something() -> None:
    """가드가 **볼 게 있어야** 판정이 뜻을 가진다 — 0건 통과는 통과가 아니다.

    실측(R43): 프로덕션 제외 목록을 테스트 스캔에 그대로 재사용했다가 `tests` 가 통째로
    걸러져 검사 대상이 **0건**이 됐다. 그 상태에서도 이 파일의 두 테스트는 초록이었고,
    뮤테이션 3개가 나란히 생존해서야 드러났다. 차이를 못 만드는 가드는 정보가 0이다.
    """
    patched = _patched_constants()
    assert len(patched) >= 50, f"검사 대상이 비정상적으로 적다({len(patched)}건) — 스캔이 죽었는지 볼 것"
    # 대표 형태 셋이 실제로 잡히는지(정규식 판이 놓쳤던 것들)
    tables = {t for t, _ in patched}
    assert any(t.endswith("_TARGETS") for t in tables), "표 기반 patch 를 못 본다"
    assert len(_names_read_by_production()) >= 500, "프로덕션 스캔이 죽었다"
