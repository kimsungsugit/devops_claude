"""산출물 저장 위치 판정 — 무엇을 거절하는지가 본체다.

이 모듈이 막는 것은 "잘못된 경로" 가 아니라 **조용한 사고**다: 말없이 덮어쓰기,
클라우디움에 저장한 줄 알기, 시스템 폴더에 문서 떨구기. 그래서 테스트도 전부
"거절했는가 + 사유를 구분 가능하게 냈는가" 를 본다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services import docgen_output as mod


def _mk(tmp_path: Path, name: str = "out.docx") -> Path:
    src_root = tmp_path / "cache"
    src_root.mkdir(parents=True, exist_ok=True)
    f = src_root / name
    f.write_text("x", encoding="utf-8")
    return f


def test_happy_path_returns_dest_under_chosen_folder(tmp_path: Path) -> None:
    src = _mk(tmp_path)
    dest_dir = tmp_path / "내문서"
    dest_dir.mkdir()
    got_src, got_dest = mod.resolve_save_target(
        src, dest_dir, allowed_src_roots=[tmp_path / "cache"]
    )
    assert got_src == src.resolve()
    # 파일명은 원본 유지 — 확장자 바꿔치기 여지를 없앤다.
    assert got_dest == (dest_dir / "out.docx").resolve()


def test_src_outside_allowed_roots_is_refused(tmp_path: Path) -> None:
    """원본을 임의 경로로 열면 이 엔드포인트가 곧 파일 읽기 프리미티브가 된다."""
    outside = tmp_path / "elsewhere" / "secret.docx"
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    dest = tmp_path / "d"
    dest.mkdir()
    with pytest.raises(mod.SaveTargetError) as ei:
        mod.resolve_save_target(outside, dest, allowed_src_roots=[tmp_path / "cache"])
    assert ei.value.code == "src_not_allowed"


def test_existing_file_refused_unless_overwrite(tmp_path: Path) -> None:
    src = _mk(tmp_path)
    dest_dir = tmp_path / "d"
    dest_dir.mkdir()
    (dest_dir / "out.docx").write_text("old", encoding="utf-8")
    with pytest.raises(mod.SaveTargetError) as ei:
        mod.resolve_save_target(src, dest_dir, allowed_src_roots=[tmp_path / "cache"])
    assert ei.value.code == "dest_exists"
    # 명시하면 통과한다 — 거절은 "묻지 않고 덮는 것" 을 막으려는 것이지 금지가 아니다.
    _, out = mod.resolve_save_target(
        src, dest_dir, allowed_src_roots=[tmp_path / "cache"], overwrite=True
    )
    assert out.name == "out.docx"


def test_missing_dest_is_not_created(tmp_path: Path) -> None:
    """`mkdir` 하지 않는다 — 오타 한 번이 엉뚱한 트리를 만든다."""
    src = _mk(tmp_path)
    ghost = tmp_path / "없는폴더"
    with pytest.raises(mod.SaveTargetError) as ei:
        mod.resolve_save_target(src, ghost, allowed_src_roots=[tmp_path / "cache"])
    assert ei.value.code == "dest_not_found"
    assert not ghost.exists()


@pytest.mark.parametrize("dest", [r"C:\Windows\System32", r"C:\Program Files\x"])
def test_system_dirs_refused(tmp_path: Path, dest: str) -> None:
    src = _mk(tmp_path)
    with pytest.raises(mod.SaveTargetError) as ei:
        mod.resolve_save_target(src, dest, allowed_src_roots=[tmp_path / "cache"])
    assert ei.value.code == "dest_system"


@pytest.mark.parametrize("dest", ["U:\\연구소\\문서", "\\\\server\\share\\docs", "//server/share"])
def test_cloudium_dest_refused_with_reason(tmp_path: Path, dest: str) -> None:
    """워커는 **읽기 전용**이다. 조용히 실패하면 '저장됐다' 로 오독한다."""
    src = _mk(tmp_path)
    with pytest.raises(mod.SaveTargetError) as ei:
        mod.resolve_save_target(src, dest, allowed_src_roots=[tmp_path / "cache"])
    assert ei.value.code == "dest_cloudium"
    assert "읽기 전용" in ei.value.message


def test_cloudium_drive_letters_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """드라이브 문자는 환경마다 다르다 — 하드코딩된 `U:` 만 보면 다른 PC 에서 샌다."""
    assert mod.is_cloudium_path("U:\\x") is True
    assert mod.is_cloudium_path("Z:\\x") is False
    monkeypatch.setenv("DEVOPS_CLOUDIUM_DRIVES", "U,Z")
    assert mod.is_cloudium_path("Z:\\x") is True
    assert mod.is_cloudium_path("D:\\x") is False


def test_blank_inputs_report_which_one(tmp_path: Path) -> None:
    with pytest.raises(mod.SaveTargetError) as e1:
        mod.resolve_save_target("", tmp_path, allowed_src_roots=[tmp_path])
    assert e1.value.code == "src_required"
    with pytest.raises(mod.SaveTargetError) as e2:
        mod.resolve_save_target(_mk(tmp_path), "", allowed_src_roots=[tmp_path / "cache"])
    assert e2.value.code == "dest_required"


def test_src_roots_match_local_router() -> None:
    """드리프트 가드 — `local._allowed_request_roots()` 와 **같은 목록**이어야 한다.

    갈라지면 "폴더 열기는 되는데 저장은 거절" 같은 모순이 난다. 라우터끼리 얽지
    않으려고 복제했으므로, 복제본이 벌어지는 것을 여기서 막는다.
    """
    from backend.routers import local as local_router

    repo_root = Path(local_router.__file__).resolve().parents[2]
    assert set(mod.default_src_roots(repo_root)) == set(local_router._allowed_request_roots())


def test_dest_same_as_source_refused(tmp_path: Path) -> None:
    src = _mk(tmp_path)
    with pytest.raises(mod.SaveTargetError) as ei:
        mod.resolve_save_target(
            src, src.parent, allowed_src_roots=[tmp_path / "cache"], overwrite=True
        )
    assert ei.value.code == "dest_same"


def test_open_folder_accepts_a_file_path() -> None:
    """생성 응답은 **파일** 경로를 준다 — 그걸 404 로 튕기면 '폴더 열기' 가 늘 실패한다.

    ⚠ 구조 검사다(호출하면 탐색기가 뜬다). 파일→상위폴더 승격 라인이 사라지면 깨진다.
    """
    src = Path(__file__).resolve().parents[2] / "backend" / "routers" / "local.py"
    body = src.read_text(encoding="utf-8", errors="ignore")
    idx = body.index("def api_open_folder")
    seg = body[idx: idx + 1400]
    assert "target.is_file()" in seg and "target = target.parent" in seg
