"""코드·테스트가 인용하는 `test_*.py::Name` 은 **실재해야** 한다.

(2026-09-04 R28 P-5④) 죽은 인용 3건이 같은 계열이었다: `docgen_last_run.py` 와
`test_docgen_last_run.py` 가 `test_report_reachability.py` 의 `TestCheckpointIsWriteOnly` 를
"그 사실이 기록돼 있다" 는 근거로 들었는데 그 클래스는 R11 에 `TestCheckpointIsRead` 로
뒤집혀 **존재하지 않았다**. `docgen_requirements.py` 는 존재한 적 없는
`test_docgen_requirements.py` 를 대조 근거로 적어 뒀다(2026-08-21 실측).

⚠ 이 docstring 은 옛 이름을 `file::Name` 형태로 적지 않는다 — 이 파일도 스캔 대상이라
그렇게 적으면 **가드가 자기를 위반한다**(R28 리뷰 C3: untracked 상태의 369 passed 가 `git add`
하는 순간 붉어질 뻔했다. 게이트는 실제로 돌린 범위만 잰다).

인용은 "여기 가드가 있다" 는 주장이다. 대상이 없으면 그 주장은 거짓이고, 읽는 사람은
가드가 있다고 믿고 넘어간다. 그래서 인용된 파일과 이름의 실존을 전수로 잰다.

스코프는 **코드와 테스트**(`.py`/`.js`/`.jsx`)다. `docs/` 계획서·라운드 노트는 역사 기록이라
당시 이름을 그대로 두는 것이 맞다. `backend/venv`(점 없음, git 미추적 site-packages)는
`.gitignore` 로 걸러진다 — 이 저장소가 한 번 그 폴더를 세어 수치를 통째로 틀린 적이 있다.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_CITE = re.compile(r"(?<!\w)(test_\w+\.py)::(\w+)")
_SCAN_SUFFIXES = {".py", ".js", ".jsx"}
_SCAN_ROOTS = ("backend", "report_gen", "workflow", "generators", "tools", "scripts",
               "tests", "frontend-v2/src")


def _tracked_files() -> list[Path]:
    """git 이 추적하는 파일만 — venv·node_modules·산출물은 여기서 자연히 빠진다."""
    out = subprocess.run(["git", "ls-files", "--", *_SCAN_ROOTS], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines()
            if line and Path(line).suffix in _SCAN_SUFFIXES]


def _defined_names(test_file: Path) -> set[str]:
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}


def _citations() -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = {}
    for f in _tracked_files():
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in _CITE.finditer(text):
            found.setdefault((m.group(1), m.group(2)), set()).add(
                str(f.relative_to(ROOT)).replace("\\", "/"))
    return found


def _test_files_by_name() -> dict[str, list[Path]]:
    """같은 basename 이 다른 디렉터리에 있을 수 있다(실측 2건: `test_report_gen.py`,
    `test_scm_router.py`) — last-wins dict 면 한쪽만 검사돼 오탐/미탐이 갈린다(리뷰 W8)."""
    out: dict[str, list[Path]] = {}
    for p in (ROOT / "tests").rglob("test_*.py"):
        out.setdefault(p.name, []).append(p)
    return out


def _name_defined_in_any(name: str, targets: list[Path]) -> bool:
    """같은 basename 후보 **어느 하나**에라도 정의돼 있으면 실존이다."""
    return any(name in _defined_names(t) for t in targets)


def test_every_cited_test_file_and_name_exists() -> None:
    cites = _citations()
    assert cites, "인용을 하나도 못 찾았다 — 정규식이나 스코프가 깨졌다(공허 통과 금지)"
    test_files = _test_files_by_name()
    dead: list[str] = []
    for (fname, name), srcs in sorted(cites.items()):
        targets = test_files.get(fname) or []
        if not targets:
            dead.append(f"{fname}::{name} — 파일 없음 (인용: {', '.join(sorted(srcs))})")
            continue
        if not _name_defined_in_any(name, targets):
            dead.append(f"{fname}::{name} — 이름 없음 (인용: {', '.join(sorted(srcs))})")
    assert not dead, "존재하지 않는 테스트를 근거로 인용한다:\n" + "\n".join(dead)


def test_duplicate_basenames_are_all_consulted(tmp_path: Path) -> None:
    """실 저장소에 같은 basename 이 2건 있다 — 마지막 것만 보면 앞의 정의가 '없음' 이 된다.

    (지금 그 두 파일을 가리키는 인용이 없어 실파일로는 차이가 안 난다 — 합성으로 잰다.)
    """
    a = tmp_path / "unit" / "test_dup.py"
    b = tmp_path / "integration" / "test_dup.py"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_text("class OnlyInA:\n    pass\n", encoding="utf-8")
    b.write_text("def only_in_b():\n    pass\n", encoding="utf-8")
    assert _name_defined_in_any("OnlyInA", [a, b])
    assert _name_defined_in_any("only_in_b", [a, b])
    assert not _name_defined_in_any("nowhere", [a, b])


def test_the_guard_scans_itself_once_tracked() -> None:
    """이 파일이 git 에 올라간 뒤엔 자기 자신도 스캔 대상이어야 한다 — 아니면 자기 위반을 못 본다."""
    me = Path(__file__).resolve()
    tracked = {p.resolve() for p in _tracked_files()}
    if me not in tracked:
        import pytest
        pytest.skip("아직 untracked — `git add` 뒤에 자기 스캔이 켜진다(리뷰 C3 의 사각)")
    assert me in tracked


def test_the_guard_sees_its_own_citation_style() -> None:
    """정규식이 이 저장소의 실제 인용 형태를 잡는지 — 못 잡으면 위 테스트는 빈 집합 통과.

    ⚠ 예시는 **런타임에 조립**한다 — 리터럴로 적으면 이 파일의 인용이 되어 실존 검사를 받는다.
    """
    sep = ":" * 2
    assert _CITE.search(f"`tests/unit/test_report_reachability.py{sep}TestCheckpointIsRead` 가")
    assert _CITE.search(f"(`test_docgen_last_run.py{sep}TestCheckpointWritesOnce`)")
    # 경로 조각이 아닌 곳은 잡지 않는다.
    assert _CITE.search("test_x.py: 설명") is None
    assert _CITE.search(f"my_test_x.py{sep}Name") is None
