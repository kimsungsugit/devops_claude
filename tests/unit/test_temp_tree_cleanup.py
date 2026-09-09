"""임시 트리 정리가 **실제로** 지우고, 못 지우면 말한다 (R43 N16).

`.codex_tmp` 에 `pytest-*` 디렉터리가 **13,723개**(가장 오래된 것 2026-03-13, 6개월치,
전수 파일 43,836개 · 0.95 GB) 쌓여 있었다. `ls .codex_tmp` 한 번이 120초를 넘겼다.

원인은 디스크가 아니라 Windows + git 이다: 테스트가 임시 저장소를 만들면
`.git/objects/**` 가 **읽기 전용(0444)** 으로 생기고, Windows 의 `unlink` 는 그 파일을
지우지 못해 `PermissionError [WinError 5]` 를 낸다. 정리 코드가 세 곳 모두
`shutil.rmtree(..., ignore_errors=True)` 였으므로 그 실패는 **통째로 삼켜졌다** —
정리는 한 번도 성공한 적이 없는데 스위트는 조용했다.

빈 출력을 성공으로 읽는 fake-green 이 **정리 경로**에 남아 있던 자리다.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from tests.conftest import _CLEANUP_FAILURES, _force_rmtree


@pytest.fixture()
def failure_log(monkeypatch, tmp_path: Path) -> Path:
    """이 파일의 테스트는 **일부러** 정리 실패를 만든다.

    그 가짜가 세션 보고(`pytest_unconfigure`)에 섞이면 진짜 실패와 구별되지 않는다 —
    C3 가 지적한 것과 같은 형태다. 기록 대상 파일과 리스트를 이 테스트 동안만 갈아끼운다.
    """
    from tests import conftest as _cf

    log = tmp_path / "failures.txt"
    monkeypatch.setattr(_cf, "_CLEANUP_FAILURE_LOG", log)
    before = len(_CLEANUP_FAILURES)
    try:
        yield log
    finally:
        del _CLEANUP_FAILURES[before:]


def _readonly_tree(root: Path) -> Path:
    """git 이 만드는 것과 같은 **읽기 전용 파일**이 든 트리."""
    root.mkdir(parents=True, exist_ok=True)
    inner = root / "objects" / "ab"
    inner.mkdir(parents=True)
    f = inner / "deadbeef"
    f.write_bytes(b"x")
    os.chmod(f, stat.S_IREAD)      # 0444 — git object 와 같은 상태
    return f


def test_readonly_files_are_actually_removed(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    f = _readonly_tree(target)
    assert not (os.stat(f).st_mode & stat.S_IWRITE), "전제: 파일이 읽기 전용이어야 한다"

    assert _force_rmtree(target) is True
    assert not target.exists(), "읽기 전용 파일이 든 트리가 남았다"


def test_the_old_way_really_did_leave_it_behind(tmp_path: Path) -> None:
    """대조군 — 옛 방식(`ignore_errors=True`)은 **남긴다**.

    이 단언이 없으면 위 테스트가 "원래도 잘 지워졌다" 는 경우와 구별되지 않는다
    (차이를 못 만드는 가드는 정보가 0이다).
    """
    import shutil

    target = tmp_path / "repo_old"
    _readonly_tree(target)
    shutil.rmtree(target, ignore_errors=True)
    assert target.exists(), (
        "옛 방식이 지워 버렸다 — 이 플랫폼에선 읽기 전용이 삭제를 막지 않는다는 뜻이라 "
        "위 테스트의 의미가 달라진다(전제를 다시 확인할 것)")


def test_real_git_objects_are_readonly_here(tmp_path: Path) -> None:
    """실제 `git init` 산출물이 읽기 전용인지 — 원인 진단이 이 플랫폼에서 성립하는지 고정."""
    repo = tmp_path / "g"
    repo.mkdir()
    try:
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        (repo / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "x"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git 사용 불가: {exc}")

    objects = [f for f in (repo / ".git" / "objects").rglob("*") if f.is_file()]
    assert objects, "git object 가 하나도 없다 — 전제가 깨졌다"
    readonly = [f for f in objects if not (os.stat(f).st_mode & stat.S_IWRITE)]
    assert readonly, "git object 가 읽기 전용이 아니다 — 이 플랫폼에선 N16 의 원인이 다르다"

    # 그리고 그 트리도 정리된다.
    assert _force_rmtree(repo) is True
    assert not repo.exists()


def test_failures_are_recorded_not_swallowed(failure_log: Path, tmp_path: Path) -> None:
    """지우지 못하면 **사실을 남긴다** — 조용히 넘어가는 것이 이 결함의 본체였다.

    ⚠ (R43 리뷰 C3) 첫 판은 함수 스코프 `monkeypatch` 로 `shutil.rmtree` 를 망가뜨렸다.
    fixture teardown 은 인자 순서의 역순이라 **`tmp_path` 정리가 monkeypatch undo 보다
    먼저** 돈다 — 그 정리가 망가진 `rmtree` 를 밟아 ① `.codex_tmp` 에 잔존물을 매 실행
    하나씩 남기고(이 커밋이 없애려는 바로 그것을 새로 만들었다) ② 세션 보고에 늘 있는
    가짜 1건을 섞었다. `MonkeyPatch.context()` 로 **본문 안에서** 되돌린다.
    """
    import shutil as _shutil

    target = tmp_path / "stubborn"
    target.mkdir()
    (target / "f.txt").write_text("x", encoding="utf-8")

    def _always_fail(path, **_kw):
        raise PermissionError("simulated WinError 5")

    before = len(_CLEANUP_FAILURES)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_shutil, "rmtree", _always_fail)
        assert _force_rmtree(target) is False
    assert len(_CLEANUP_FAILURES) == before + 1
    assert "stubborn" in _CLEANUP_FAILURES[-1]
    # 패치가 풀린 뒤엔 정말로 지워진다 — 잔존물을 남기고 끝내지 않는다.
    assert _force_rmtree(target) is True


def test_cleanup_survives_patched_path_globals(monkeypatch, tmp_path: Path) -> None:
    """정리는 **teardown 에서 도는 코드**라, 그 시점에 무엇이 패치돼 있는지 알 수 없다.

    실측(R43): `test_impact_changes.py` 가 cloudium SMB 권한거부를 재현하려고
    `Path.exists` 를 monkeypatch 로 PermissionError 를 던지게 만든다. 정리 헬퍼가
    `path.exists()` 로 시작하자 **그 테스트의 teardown 이 통째로 ERROR** 가 됐다 —
    정리 코드가 테스트가 패치한 전역을 밟은 것이다.
    """
    target = tmp_path / "victim"
    target.mkdir()
    (target / "f.txt").write_text("x", encoding="utf-8")

    def _boom(self, *a, **k):
        raise PermissionError("[WinError 5]")

    monkeypatch.setattr(Path, "exists", _boom)
    monkeypatch.setattr(Path, "is_dir", _boom)

    assert _force_rmtree(target) is True
    monkeypatch.undo()
    assert not target.exists()


def test_absent_path_is_success_not_failure(tmp_path: Path) -> None:
    """이미 없는 경로는 **정리 완료**다 — 실패로 세면 보고가 잡음으로 가득 찬다."""
    before = len(_CLEANUP_FAILURES)
    assert _force_rmtree(tmp_path / "never-existed") is True
    assert len(_CLEANUP_FAILURES) == before


def test_one_stubborn_file_does_not_block_its_siblings(failure_log: Path, tmp_path: Path) -> None:
    """(리뷰 W1) 한 항목이 안 지워져도 **나머지는 지운다**.

    첫 판의 콜백은 재시도 실패 시 예외를 위로 던졌고, 그러면 `shutil.rmtree` 가 그 자리에서
    언와인드해 형제 항목을 아예 손대지 못했다 — 실패 케이스에서 옛 `ignore_errors=True`
    **보다도 적게** 지우는 상태였다(리뷰어 실측: `b/g` 가 남았다).
    """
    root = tmp_path / "tree"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    stuck = root / "a" / "locked.bin"
    stuck.write_bytes(b"x")
    sibling = root / "b" / "ok.txt"
    sibling.write_text("x", encoding="utf-8")

    handle = open(stuck, "rb")          # noqa: SIM115 — Windows 공유 위반을 만든다
    try:
        ok = _force_rmtree(root)
        if ok:
            import pytest as _pytest
            _pytest.skip("이 플랫폼은 열린 파일도 삭제한다 — 이 시나리오가 성립하지 않는다")
        assert not sibling.exists(), "형제 항목이 안 지워졌다 — 콜백이 삭제를 중단시켰다"
        assert stuck.exists(), "전제: 잠긴 파일은 남아야 한다"
    finally:
        handle.close()
        _force_rmtree(root)


def test_failures_reach_a_file_not_just_a_list(failure_log: Path, tmp_path: Path) -> None:
    """(리뷰 C2) 실패는 **파일**에 남는다 — 리스트만으로는 xdist 워커 밖으로 못 나간다.

    게이트 4곳은 전부 `-n auto` 이고 `-s` 가 없다. 그 조건에서 세션 fixture 의 `print` 는
    ① 캡처되거나 ② 워커 프로세스에 갇혀 **아무에게도 도달하지 않는다**.
    """
    import shutil as _shutil

    target = tmp_path / "unreachable"
    target.mkdir()

    def _always_fail(path, **_kw):
        raise PermissionError("simulated")

    before_lines = (failure_log.read_text(encoding="utf-8").splitlines()
                    if failure_log.exists() else [])
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(_shutil, "rmtree", _always_fail)
            assert _force_rmtree(target) is False
        after_lines = failure_log.read_text(encoding="utf-8").splitlines()
        assert len(after_lines) == len(before_lines) + 1
        assert "unreachable" in after_lines[-1]
    finally:
        _force_rmtree(target)


def test_failure_message_keeps_the_filename(failure_log: Path, tmp_path: Path) -> None:
    """(리뷰 W4) Windows 는 **파일명이 문장 끝**에 붙는다 — 짧게 자르면 진단이 통째로 사라진다."""
    import shutil as _shutil

    long_name = "a" * 80
    target = tmp_path / long_name
    target.mkdir()

    def _always_fail(path, **_kw):
        raise PermissionError(
            "[WinError 32] 다른 프로세스가 파일을 사용 중이기 때문에 프로세스가 액세스 할 수 "
            f"없습니다: '{target / 'deep' / 'inner' / 'victim.bin'}'")

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(_shutil, "rmtree", _always_fail)
            _force_rmtree(target)
        assert "victim.bin" in _CLEANUP_FAILURES[-1], _CLEANUP_FAILURES[-1]
    finally:
        _force_rmtree(target)


def test_symlink_target_permissions_are_not_touched(failure_log: Path, tmp_path: Path) -> None:
    """(리뷰 W3) 심링크에 `chmod` 하면 **타깃**의 권한이 바뀐다 — 트리 밖 파일을 건드릴 수 있다.

    정리 대상은 임시 트리인데, 그 안의 링크 하나 때문에 저장소 소스나 사용자 문서의 권한이
    바뀌면 정리가 아니라 사고다. `rmtree` 는 링크를 따라 들어가지 않으므로 삭제 자체는
    안전하지만, 재시도 콜백의 `chmod` 는 기본이 **follow** 다.
    """
    outsider_dir = tmp_path / "outside"
    outsider_dir.mkdir()
    outsider = outsider_dir / "precious.txt"
    outsider.write_text("x", encoding="utf-8")
    os.chmod(outsider, stat.S_IREAD)          # 읽기 전용 — 이 상태가 유지돼야 한다
    before_mode = stat.S_IMODE(os.stat(outsider).st_mode)

    tree = tmp_path / "tree"
    tree.mkdir()
    link = tree / "link.txt"
    try:
        os.symlink(outsider, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"이 환경에서 심링크를 만들 수 없다: {exc}")

    _force_rmtree(tree)

    assert outsider.exists(), "링크를 따라가 트리 밖 파일을 지웠다"
    assert stat.S_IMODE(os.stat(outsider).st_mode) == before_mode, (
        "링크 타깃의 권한이 바뀌었다 — chmod 가 링크를 따라갔다")
