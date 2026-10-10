"""raw string 안의 이중 백슬래시 정규식 — **조용히 죽는** 결함의 클래스 가드.

## 왜 클래스로 막는가

`re.compile(r"...\\\\d...")` 에서 raw string 의 `\\\\` 는 **리터럴 백슬래시**다. 즉
정규식은 "역슬래시 다음에 d" 를 요구하고, 대상 텍스트(C 소스·문서 제목)에 그런 문자열은
없으므로 **한 번도 매치되지 않는다**. 예외도 경고도 없이 `None` / `[]` 만 돌아온다.

이 저장소는 같은 모양을 **다섯 번** 겪었다:

| 위치 | 증상 |
|---|---|
| `report_gen/utils.py` `_infer_type_from_decl`(2건, 기존 주석에 기록) | 폴백이 항상 `""` |
| `workflow/code_parser/c_parser.py` 전역 범위 | `range_source="decl"` 영구 미발화 |
| `report_gen/docx_builder.py` `swufn_table_spec` 빌드·조회(2건) | dict 항상 비어 도달 불가 |

`\\d` 를 한 번 더 이스케이프해도 **문법은 유효**하고 테스트도 통과한다(매치가 0이 되는
게 정상 결과와 구분되지 않으므로). 그래서 개별 가드가 아니라 소스 스캔으로 막는다.

⚠ **docstring 은 제외한다** — 산문에서 UNC 경로 `\\\\server\\share` 를 설명하는 raw
docstring 이 실재한다(`backend/services/file_resolver.py`). 정규식이 아니므로 결함이 아니다.
정말로 리터럴 백슬래시를 찾아야 하는 **정규식**이면 같은 줄에 `# raw-backslash-ok` 를 단다.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 우리 코드만 — 서드파티 venv 는 이 계약의 대상이 아니다
SCAN_DIRS = ("backend", "workflow", "report_gen", "generators", "scripts", "prompts", "tools")
SKIP_PARTS = {".venv", "venv", "node_modules", "_archive", ".git", ".codex_tmp", "site-packages"}

# 소스 텍스트 기준: 백슬래시 2개 + 정규식 클래스 문자
_BAD = re.compile(r"\\\\[dDsSwWbBAZ]")
_ALLOW = "raw-backslash-ok"
_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@lru_cache(maxsize=8)
def _candidate_files(root: Path):
    """`root` 아래의 우리 `.py` 목록.

    ⚠ 제외 판정은 **root 기준 상대 경로**로 한다. 절대 경로 전체를 보면 저장소가
    `…/venv/` 같은 이름의 폴더 안에 있을 때 후보가 통째로 0이 되어 **ratchet 이
    조용히 초록**이 된다(이 시험을 쓰다 실제로 걸렸다 — conftest 가 `tmp_path` 를
    `.codex_tmp/` 아래로 돌리자 탐지기가 아무것도 못 봤다).
    """
    seen = set()
    for name in SCAN_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.relative_to(root).parts):
                continue
            seen.add(path)
    seen.update(root.glob("*.py"))
    return sorted(seen)


def _docstring_lines(text: str) -> set[int]:
    """docstring 리터럴이 시작하는 줄 번호 — 산문은 이 계약의 대상이 아니다."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    rows = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                rows.add(first.value.lineno)
    return rows


def _offenders(root: Path = REPO_ROOT):
    hits = []
    for path in _candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not _BAD.search(text):  # 빠른 선별 — 대부분의 파일은 여기서 끝난다
            continue
        lines = text.splitlines()
        doc_rows = _docstring_lines(text)
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
        for tok in tokens:
            if tok.type != tokenize.STRING:
                continue
            literal = tok.string
            prefix = literal[: len(literal) - len(literal.lstrip("rRbBuUfF"))].lower()
            if "r" not in prefix or not _BAD.search(literal):
                continue
            row = tok.start[0]
            if row in doc_rows:
                continue
            line = lines[row - 1] if 0 < row <= len(lines) else ""
            if _ALLOW in line:
                continue
            hits.append(f"{path.relative_to(root).as_posix()}:{row}  {literal[:80]}")
    return hits


def _fake_repo(tmp_path: Path, body: str, name: str = "bad.py") -> Path:
    pkg = tmp_path / "workflow"
    pkg.mkdir(exist_ok=True)
    (pkg / name).write_text(body, encoding="utf-8")
    return tmp_path


class TestNoDeadRawStringRegex:
    def test_repository_source_has_no_double_escaped_class_shorthand(self):
        found = _offenders()
        assert not found, (
            "raw string 안의 `\\\\d` 류는 정규식에서 리터럴 백슬래시라 영구 미매치다.\n"
            "한 겹으로 고치거나, 정말 백슬래시를 찾는 것이면 같은 줄에 "
            f"`# {_ALLOW}` 를 달 것:\n  " + "\n  ".join(found)
        )

    def test_the_detector_actually_fires(self, tmp_path):
        """⚠ 음성 대조군 — 탐지기가 아무것도 못 잡으면 위 시험은 항상 초록이다."""
        root = _fake_repo(tmp_path, 'import re\nP = re.compile(r"(0x\\\\d+)")\n')
        assert any("workflow/bad.py" in f for f in _offenders(root))

    def test_the_allow_comment_suppresses_it(self, tmp_path):
        root = _fake_repo(
            tmp_path, f'import re\nP = re.compile(r"(0x\\\\d+)")  # {_ALLOW}\n'
        )
        assert _offenders(root) == []

    def test_a_normal_regex_is_not_flagged(self, tmp_path):
        """⚠ 음성 대조군 — 정상 `\\d` 를 잡으면 저장소 전체가 빨개진다."""
        root = _fake_repo(tmp_path, 'import re\nP = re.compile(r"(0x\\d+)")\n')
        assert _offenders(root) == []

    def test_non_raw_strings_are_not_flagged(self, tmp_path):
        """일반 문자열의 `"\\\\d"` 는 정규식에 `\\d` 로 도착한다 — 정상이다."""
        root = _fake_repo(tmp_path, 'import re\nP = re.compile("(0x\\\\d+)")\n')
        assert _offenders(root) == []

    def test_a_raw_docstring_about_unc_paths_is_not_flagged(self, tmp_path):
        """실재 사례 — `\\\\server\\share` 를 설명하는 raw docstring 은 정규식이 아니다."""
        root = _fake_repo(
            tmp_path,
            'def f():\n    r"""UNC `\\\\\\\\server\\\\share` 보정."""\n    return 1\n',
        )
        assert _offenders(root) == []

    def test_a_bad_regex_below_a_docstring_is_still_caught(self, tmp_path):
        """⚠ docstring 면제가 파일 전체를 면제하면 안 된다."""
        root = _fake_repo(
            tmp_path,
            'r"""UNC `\\\\\\\\server\\\\share`."""\nimport re\nP = re.compile(r"(0x\\\\d+)")\n',
        )
        assert any("workflow/bad.py" in f for f in _offenders(root))


class TestDeadDuplicateStaysRemoved:
    """`swufn_table_spec` 은 살아 있는 전방탐색과 **같은 답**을 내던 도달 불가 중복이었다.

    실측(tokenized 템플릿·정본 SUDS, gate 통과 heading 429개): 두 경로의
    (rows, cols, style) 이 **429/429 동일**. 되살리면 한 번도 돈 적 없는 코드를 켜는 것이고
    얻는 게 없다. ⚠ 구조 검사임을 밝혀 둔다 — 관측량 가드는 위 ratchet 이다.
    """

    def test_docx_builder_does_not_reintroduce_it(self):
        src = (REPO_ROOT / "report_gen" / "docx_builder.py").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in src.splitlines() if not line.lstrip().startswith("#")
        )
        assert "swufn_table_spec" not in code


class TestScannerReachesRealSource:
    """⚠ 후보가 0이면 위 저장소 스캔은 **아무것도 안 보고도 통과**한다.

    이 저장소를 `…/venv/` 같은 이름의 폴더에 두면 실제로 그렇게 됐다.
    """

    def test_the_repository_scan_actually_sees_files(self):
        files = _candidate_files(REPO_ROOT)
        assert len(files) > 100, f"스캔 후보가 {len(files)}개뿐이다 — 필터가 트리를 삼켰다"
        names = {p.relative_to(REPO_ROOT).as_posix() for p in files}
        assert "workflow/code_parser/c_parser.py" in names
        assert "report_gen/docx_builder.py" in names

    def test_third_party_trees_are_still_excluded(self):
        offenders = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in _candidate_files(REPO_ROOT)
            if any(part in SKIP_PARTS for part in p.relative_to(REPO_ROOT).parts)
        }
        assert offenders == set()
