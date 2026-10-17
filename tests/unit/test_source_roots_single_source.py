"""소스 루트 분해는 `report_gen.source_roots` 한 곳에서만 한다 (R47 N24, 2026-09-10).

## 왜 생겼나

`source_root` 는 "복수 경로를 한 문자열" 로 온다(레지스트리 실측 3항목 전부 콤마 결합).
그 문자열을 조각내는 코드가 **30곳**, 규약이 **두 갈래**였다 — 생성기·시그니처·SVN 조회는
콤마·세미콜론 둘 다 갈랐고, 라우터의 `_first_root` 17곳·주석 커버리지 3곳·레지스트리 조회 1곳은
콤마만 갈랐다. 세미콜론으로 이은 프로젝트는 생성기에선 두 루트, 라우터 존재 검사에선
`"D:/a;D:/b"` 통짜(없는 경로)가 된다. R46 리뷰 W6 이월.

## 이 파일이 고정하는 것

1. 분해 계약(구분자 2종·공백·빈 조각·중복·순서).
2. **저장소 전수 스윕** — `source_root` 류 변수를 `.split(",")`/`replace(";", ",")` 로 직접 자르는
   줄이 단일 출처 밖에 다시 생기지 않는다(손으로 든 목록이 아니라 트리를 훑는다).
3. 관측량 — 세미콜론 결합 레지스트리의 둘째 루트로 `resolve_scm_id` 가 프로젝트를 찾는다
   (콤마만 가르던 옛 코드에선 None 이었다).

뮤테이션(2026-09-10): `SEPARATORS` 에서 `;` 를 빼면 1·3 이 죽고, 라우터 한 곳을 옛 형태로
되돌리면 2 가 죽는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from report_gen.source_roots import (
    SEPARATORS,
    first_source_root,
    join_source_roots,
    split_source_roots,
)

_REPO = Path(__file__).resolve().parents[2]


class TestContract:

    def test_comma_and_semicolon_both_split(self):
        assert split_source_roots("D:/a,D:/b") == ["D:/a", "D:/b"]
        assert split_source_roots("D:/a;D:/b") == ["D:/a", "D:/b"]
        assert split_source_roots("D:/a; D:/b ,D:/c") == ["D:/a", "D:/b", "D:/c"]

    def test_blank_pieces_are_dropped_and_order_kept(self):
        assert split_source_roots(" ,D:/b,, ;D:/a ") == ["D:/b", "D:/a"]
        assert split_source_roots("") == []
        assert split_source_roots(None) == []

    def test_exact_duplicates_collapse_but_normalisation_is_not_done_here(self):
        assert split_source_roots("D:/a,D:/a") == ["D:/a"]
        # 대소문자·슬래시 차이는 여기서 접지 않는다 — 경로 동일성은 소비처(`_normalize_path_key`) 몫.
        assert split_source_roots("D:/a,d:\\a") == ["D:/a", "d:\\a"]

    def test_first_root_skips_leading_blank_piece(self):
        """옛 `split(",")[0].strip()` 은 `" ,D:/b"` 에서 빈 문자열을 냈다."""
        assert first_source_root(" ,D:/b") == "D:/b"
        assert first_source_root("D:/a;D:/b") == "D:/a"
        assert first_source_root("") == ""
        assert first_source_root(None) == ""

    def test_join_is_the_comma_form_the_generators_take(self):
        assert join_source_roots(["D:/a", " D:/b ", ""]) == "D:/a,D:/b"
        assert split_source_roots(join_source_roots(["D:/a", "D:/b"])) == ["D:/a", "D:/b"]

    def test_separator_set_is_exactly_the_two_the_repo_used(self):
        assert set(SEPARATORS) == {",", ";"}


# 분해 대상으로 쓰이는 변수 이름 — 이 토큰이 있는 줄에서만 직접 분해를 금지한다.
_ROOT_TOKEN = re.compile(r"\b(source_root|src_root|raw_src|_src_roots_str|source_roots)\b")
_SPLIT = re.compile(r"""\.split\(\s*["'][,;]["']\s*\)|replace\(\s*["'];["']\s*,\s*["'],["']\s*\)""")
# (리뷰 C2) 준비 게이트는 변수명이 `path` 라 위 토큰에 안 걸렸다 — "첫 조각 뽑기" 형태는 변수명이 뭐든 잡는다.
_FIRST_PICK = re.compile(r"""\.split\(\s*["'][,;]["']\s*\)\[0\]""")
_FIRST_PICK_TOKEN = re.compile(r"\b(path|root|roots|src)\w*\b")
_SCAN_DIRS = ("backend", "generators", "report_gen", "scripts", "workflow")
_SKIP_PARTS = {"venv", ".venv", "node_modules", "site-packages", "__pycache__"}
_SINGLE_SOURCE = _REPO / "report_gen" / "source_roots.py"


def _offenders() -> list[str]:
    hits: list[str] = []
    for d in _SCAN_DIRS:
        for py in (_REPO / d).rglob("*.py"):
            if _SKIP_PARTS & set(py.parts) or py == _SINGLE_SOURCE:
                continue
            try:
                lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for no, line in enumerate(lines, 1):
                code = line.split("#", 1)[0]
                if (_ROOT_TOKEN.search(code) and _SPLIT.search(code)) or (
                        _FIRST_PICK.search(code) and _FIRST_PICK_TOKEN.search(code)):
                    hits.append(f"{py.relative_to(_REPO)}:{no}: {code.strip()[:100]}")
    return hits


class TestRepositorySweep:

    def test_no_direct_split_of_source_root_outside_the_single_source(self):
        found = _offenders()
        assert not found, "source_root 를 직접 자르는 줄 — split_source_roots()/first_source_root() 로:\n" + "\n".join(found)

    def test_the_sweep_actually_matches_the_old_shapes(self, tmp_path):
        """가드가 옛 형태 세 가지를 잡는지 — 못 잡으면 위 테스트의 초록은 정보 0 이다."""
        for shape in (
            '_first_root = source_root.split(",")[0].strip() if source_root else ""',
            'roots = [p.strip() for p in str(source_root or "").replace(";", ",").split(",") if p.strip()]',
            'cands = [Path(p.strip()).resolve() for p in raw_src.replace(";", ",").split(",") if p.strip()]',
        ):
            assert _ROOT_TOKEN.search(shape) and _SPLIT.search(shape), shape
        # (리뷰 C2) 변수명이 `path` 인 준비 게이트 형태도 잡는다.
        pre = 'first = path.split(",")[0].strip()'
        assert _FIRST_PICK.search(pre) and _FIRST_PICK_TOKEN.search(pre)
        # 무관한 분해(함수 ID 목록·C 선언 텍스트)는 잡지 않는다 — 거짓양성이 곧 가드 무력화다.
        for benign in (
            'return [t for t in (s.strip() for s in str(raw or "").replace(";", ",").split(",")) if t]',
            'return text.split(",")[0].strip().rstrip("}").strip()',
            'v_stripped = var.split(",")[0].strip().split(":")[0].strip()',
        ):
            assert not (_ROOT_TOKEN.search(benign) and _SPLIT.search(benign)), benign
            assert not (_FIRST_PICK.search(benign) and _FIRST_PICK_TOKEN.search(benign)), benign

    def test_consumers_import_the_single_source(self):
        """치환한 모듈이 실제로 단일 출처를 import 한다 — 이름만 같은 지역 함수가 아니다.

        `scm_registry` 는 함수 안에서 든다(리뷰 W5: 단발 스크립트가 `report_gen` 패키지 init 1.1초를 물지 않게) —
        그쪽은 소스로 확인한다.
        """
        from backend.helpers import uds
        from backend.routers import docgen_preflight, jenkins, local
        from backend.services import docgen_comment_coverage, scm_registry
        from generators import sits
        from report_gen import project_setup, uds_generator
        from tests.unit._source_probe import source_of
        for mod in (uds, jenkins, local, docgen_preflight, docgen_comment_coverage, sits, project_setup, uds_generator):
            fn = getattr(mod, "split_source_roots", None) or getattr(mod, "first_source_root", None)
            assert fn is not None, mod.__name__
            assert fn.__module__ == "report_gen.source_roots", (mod.__name__, fn.__module__)
        assert "from report_gen.source_roots import split_source_roots" in source_of(scm_registry.resolve_scm_entry)


class TestObservable:

    def test_semicolon_joined_registry_root_resolves_by_its_second_root(self, tmp_path, monkeypatch):
        """콤마만 가르던 `resolve_scm_id` 는 `"D:/src;D:/fbl"` 을 한 키로 만들어 둘째 루트를 못 찾았다."""
        pytest.importorskip("pydantic")
        from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
        from backend.services import scm_registry

        monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
        scm_registry.register_entry(ScmRegisterRequest(
            id="p1", name="P1", scm_type="git", scm_url="https://example/p1.git",
            source_root="D:/src;D:/fbl", linked_docs=ScmLinkedDocs(),
        ))
        assert scm_registry.resolve_scm_id("D:/fbl") == "p1"
        assert scm_registry.resolve_scm_id("D:/src") == "p1"
        assert scm_registry.resolve_scm_id("D:/elsewhere") is None
        # (리뷰 C1) 기록기는 등록 문자열 **그대로** 를 넘긴다(`recorder.py`) — 전체문자열 조회도 찾아야 한다.
        #   등록값만 세미콜론을 가르고 조회값은 콤마만 갈랐던 첫 판은 여기서 None 이었다(리뷰어 프로브 실측).
        assert scm_registry.resolve_scm_id("D:/src;D:/fbl") == "p1"
        assert scm_registry.resolve_scm_id("D:/fbl, D:/src") == "p1"
        assert scm_registry.resolve_scm_id("D:/src,D:/src") == "p1"    # 중복 조각(게이트 실측 — 접으면 1조각)
