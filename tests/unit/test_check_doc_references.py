"""`scripts/check_doc_references.py` — 하네스 문서 본문의 코드 참조 검사기.

이 검사기가 생긴 이유는 `check_skill_frontmatter.py` 가 frontmatter **구조**만 보기
때문이다. 2026-08-03 감사에서 나온 드리프트가 전부 그 사각지대에 있었다:
없는 함수 사용법(`build_docx`), 없는 파일(`templates/uds_template.docx`),
무관한 줄번호(`impact_orchestrator.py:1659-1660`), 통째로 허구인 에이전트 문서.

여기 테스트는 **오탐 억제 장치들이 진짜 탐지까지 같이 죽이지 않는지**를 주로 본다 —
검사기를 조용하게 만드는 건 쉽고, 그러면 게이트가 없는 것보다 나쁘다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_repo_root / "scripts"))

import check_doc_references as cdr  # noqa: E402


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """검사기가 tmp_path 를 저장소 루트로 보게 한다."""
    monkeypatch.setattr(cdr, "ROOT", tmp_path)
    return tmp_path


def _scan(root: Path, md_rel: str, body: str, tracked: set[str] | None = None):
    (root / md_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / md_rel).write_text(body, encoding="utf-8")
    paths = set(tracked or set())
    by_name: dict[str, list[str]] = {}
    for p in paths:
        by_name.setdefault(p.rsplit("/", 1)[-1], []).append(p)
    return cdr.scan([md_rel], paths, by_name)


class TestDetection:
    def test_doc001_missing_path(self, fake_root):
        hits = _scan(fake_root, "doc.md", "설명은 `report_gen/nope.py` 참조.\n")
        assert [h[2] for h in hits] == ["DOC001"]

    def test_doc002_line_beyond_eof(self, fake_root):
        (fake_root / "mod.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
        hits = _scan(fake_root, "doc.md", "위치는 `mod.py:99` 다.\n", tracked={"mod.py"})
        assert [h[2] for h in hits] == ["DOC002"]

    def test_doc003_symbol_not_defined(self, fake_root):
        (fake_root / "mod.py").write_text("def real_one():\n    pass\n", encoding="utf-8")
        hits = _scan(fake_root, "doc.md", "`mod.py::build_docx` 를 쓴다.\n", tracked={"mod.py"})
        assert [h[2] for h in hits] == ["DOC003"]
        assert "build_docx" in hits[0][3]

    def test_existing_symbol_is_clean(self, fake_root):
        (fake_root / "mod.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
        assert _scan(fake_root, "doc.md", "`mod.py::Thing` 참조.\n", tracked={"mod.py"}) == []


class TestFalsePositiveSuppressors:
    """오탐 억제 4종. 첫 실행 23건 중 이들이 14건을 만들었다."""

    def test_gitignored_but_existing_file_is_not_a_violation(self, fake_root):
        """tracked 목록에만 의존하면 gitignore 된 실재 파일이 전부 '없음' 이 된다.

        실측: `reports/*.sqlite`·`settings.local.json`·`config/file_mode.json` 6건.
        """
        (fake_root / "reports").mkdir()
        (fake_root / "reports/quality.sqlite").write_bytes(b"x")
        assert _scan(fake_root, "doc.md", "DB 는 `reports/quality.sqlite` 다.\n", tracked=set()) == []

    def test_bare_filename_absence_is_not_reported(self, fake_root):
        """디렉터리 없는 이름은 산출물 파일명 예시인 경우가 많다(`analysis_summary.md` 등)."""
        assert _scan(fake_root, "doc.md", "결과는 `analysis_summary.md` 로 남는다.\n") == []

    def test_code_fence_is_skipped(self, fake_root):
        body = "```bash\ncat `report_gen/nope.py`\n```\n"
        assert _scan(fake_root, "doc.md", body) == []

    def test_suppress_marker_covers_whole_paragraph(self, fake_root):
        """마커는 **문단 단위**다 — 줄 단위면 여러 줄 인용문의 첫 줄을 못 덮는다.

        실제로 그 오탐이 났다: 마커를 문단 끝 줄에 달았더니 앞 두 줄의 참조가 남았다.
        """
        body = (
            "> 이 파일은 원래 `backend/models.py` 를\n"
            "> 전제했는데 `backend/models.py` 가 없다. <!-- doc-refs-ok -->\n"
            "\n"
            "다른 문단의 `backend/models.py` 는 여전히 잡힌다.\n"
        )
        hits = _scan(fake_root, "doc.md", body)
        assert [h[1] for h in hits] == [4], f"문단 밖까지 억제됐다: {hits}"


class TestSuppressorsDoNotKillDetection:
    """억제 장치가 진짜 탐지까지 죽이면 게이트가 없는 것보다 나쁘다."""

    def test_existing_dir_path_still_checked_for_line_number(self, fake_root):
        """파일이 실재해도 줄 번호는 계속 검사한다(존재 확인이 검사를 끝내면 안 된다)."""
        (fake_root / "pkg").mkdir()
        (fake_root / "pkg/mod.py").write_text("x = 1\n", encoding="utf-8")
        hits = _scan(fake_root, "doc.md", "`pkg/mod.py:50` 참조.\n")
        assert [h[2] for h in hits] == ["DOC002"]

    def test_bare_filename_still_checked_for_symbol(self, fake_root):
        """부재는 안 잡아도, 유일하게 해석되면 심볼은 검사한다."""
        (fake_root / "mod.py").write_text("def other():\n    pass\n", encoding="utf-8")
        hits = _scan(fake_root, "doc.md", "`mod.py::missing_fn` 참조.\n", tracked={"mod.py"})
        assert [h[2] for h in hits] == ["DOC003"]


class TestRepoIsClean:
    def test_current_harness_docs_have_no_dangling_references(self):
        """저장소 실제 상태 — backlog 0 을 유지한다(신규 드리프트 조기 검출)."""
        paths, by_name = cdr._tracked_index()
        hits = cdr.scan(cdr._default_targets(), paths, by_name)
        assert hits == [], "하네스 문서에 죽은 참조가 생겼다:\n" + "\n".join(
            f"  {h[0]}:{h[1]} {h[2]} {h[3]}" for h in sorted(hits)
        )
