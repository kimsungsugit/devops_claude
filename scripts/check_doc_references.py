"""하네스 문서 본문의 **코드 참조가 실재하는지** 검사한다 (변경 라인 ratchet).

## 왜 생겼나

`check_skill_frontmatter.py` 는 frontmatter **구조**만 본다. 그래서 본문이 하는 주장은
아무도 안 본다 — 2026-08-03 감사에서 나온 것들이 전부 이 사각지대에 있었다:

    .claude/agents/documenter/documenter.md   `build_docx(...)` 사용법을 적어 뒀는데
                                              **그런 함수가 저장소에 없다**(`def build_docx` 0건).
                                              `templates/uds_template.docx` 도 없다.
    플러그인 db-manager.md                    Alembic·`backend/models.py`·`data/devops.db`
                                              전부 부재 — 파일 전체가 허구였다.
    .claude/skills/impact-analysis/SKILL.md   강등 로직을 `impact_orchestrator.py:1659-1660`
                                              이라 적었는데 그 줄은 무관(실제 `:2487`).
    .claude/skills/ci-validate/SKILL.md       이미 제거된 `--ignore` 를 아직 있다고 기술.

전부 **조용하다.** 문서를 믿고 실행하면 ImportError 가 나거나, 없는 도구로 명령을
시도하거나, 애먼 줄을 들여다보게 된다.

## 무엇을 잡고 무엇을 못 잡나

    DOC001  백틱 안 경로가 저장소에 없다
    DOC002  `path:NNN` 의 줄 번호가 파일 길이를 넘는다
    DOC003  `path::symbol` 의 symbol 이 그 파일에 없다 (`def`/`class` 기준)

**못 잡는 것**: 줄 번호가 파일 안이지만 **내용이 이동한** 경우(위 `:1659-1660` 이 그렇다 —
파일이 2,700줄이라 DOC002 를 통과한다). 줄 번호 인용 자체가 드리프트에 약하다는 뜻이고,
그래서 이 저장소는 `path::symbol` 형태를 권한다 — 그건 DOC003 이 잡는다.

## ratchet

`_ratchet_core` 를 그대로 쓴다(판정 로직 단일 출처). 변경 라인에 새로 **추가된** 참조만
막는다 — 기존 문서의 낡은 참조를 한 번에 다 고칠 수는 없기 때문이다.
rc 규약도 공유: 0=신규 없음 / 1=신규 있음 / 2=DISABLED(판정 불가, 통과 아님).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet_core as core  # noqa: E402

ROOT = core.ROOT
TOOL = "doc-refs"

#: 기본 검사 범위. 하네스 문서만 — `docs/` 는 backlog 가 커서 별건.
DEFAULT_GLOBS = (".claude/**/*.md", "CLAUDE.md")

#: 백틱 안에서 "저장소 경로" 로 볼 모양. 와일드카드(`*`)·플레이스홀더(`<`)·드라이브
#: 문자(`D:`)·URL(`://`)은 문자 집합에서 자연히 배제된다 — 그것들은 참조가 아니라 패턴이다.
_REF_RE = re.compile(
    r"`([\w./\-]+\.(?:py|jsx?|md|json|ya?ml|sh|bat|txt|css|ini|toml|cfg|sqlite))"
    r"(?:::([\w.]+))?"      # ::symbol  (선택)
    r"(?::(\d+))?"          # :line     (선택)
    r"(?:-\d+)?`"           # -line     (끝 범위는 검사 안 함)
)

#: 코드 펜스 안은 건너뛴다 — 예시 코드의 경로는 실재를 주장하지 않는다.
_FENCE_RE = re.compile(r"^\s*```")

#: 억제 마커. **"이건 없다" 를 서술하는 문단** 때문에 필요하다 — 이 저장소의 문서는
#: "X 를 전제했는데 X 가 없다" 를 자주 적고, 그건 드리프트가 아니라 정정 기록이다.
#: (실측: 첫 실행 23건 중 4건이 이 부류였다.)
#:
#: ⚠ **문단 단위**로 적용된다(빈 줄로 구분되는 연속 블록 전체). 줄 단위로 만들었더니
#: 여러 줄짜리 인용문의 첫 줄에 있는 참조를 못 덮어 바로 오탐이 났다 — 마커를 그 줄마다
#: 반복해 붙이게 되면 문서가 마커로 뒤덮인다.
_SUPPRESS = "doc-refs-ok"


def _suppressed_lines(lines: list[str]) -> set[int]:
    """마커가 든 문단(빈 줄로 구분되는 블록)의 모든 줄 번호(1-based)."""
    out: set[int] = set()
    block: list[int] = []
    has_marker = False
    for i, raw in enumerate(lines, 1):
        if raw.strip():
            block.append(i)
            has_marker = has_marker or (_SUPPRESS in raw)
        else:
            if has_marker:
                out.update(block)
            block, has_marker = [], False
    if has_marker:
        out.update(block)
    return out


def _git(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _tracked_index() -> tuple[set[str], dict[str, list[str]]]:
    """`git ls-files` 로 (경로 집합, 파일명→경로들) 인덱스.

    저장소 밖(`outputs/` 등 untracked 대용량)을 훑지 않으려고 git 을 쓴다.
    실패하면 Disabled — 인덱스 없이 검사하면 전부 '없음' 으로 오판한다.
    """
    cp = _git(["git", "-c", "core.quotepath=false", "ls-files"])
    if cp.returncode != 0:
        raise core.Disabled(
            f"{TOOL}: git ls-files 실패(rc={cp.returncode}) — 저장소 목록을 못 얻어 판정 보류"
        )
    paths = {p.strip().strip('"') for p in cp.stdout.splitlines() if p.strip()}
    by_name: dict[str, list[str]] = {}
    for p in paths:
        by_name.setdefault(p.rsplit("/", 1)[-1], []).append(p)
    return paths, by_name


def _resolve(ref: str, paths: set[str], by_name: dict[str, list[str]]) -> str | None:
    """참조 문자열 → repo-상대 경로. 해석 불가면 None, 판정 보류면 `""`.

    ⚠ tracked 목록만 보면 **gitignore 된 실재 파일이 전부 '없음' 으로 오판**된다
    (실측: 첫 실행 23건 중 6건이 `reports/*.sqlite` · `settings.local.json` ·
    `config/file_mode.json` · `.codex_tmp/*` 였다). 그래서 파일시스템 존재도 함께 본다.
    git 인덱스는 **동명이인 해석용**으로만 쓴다(`outputs/` 대용량을 안 훑기 위해).
    """
    if ref in paths or (ROOT / ref).exists():
        return ref
    if "/" not in ref:
        # 디렉터리 없는 bare 이름은 참조가 아니라 **산출물 파일명 예시**인 경우가 많다
        # (`analysis_summary.md`, `YYYY-MM-DD-제목.md`, 이미 지워진 `stop_check.py` 언급).
        # 유일하게 해석되면 줄번호·심볼 검사에는 쓰되, 부재를 **위반으로 올리지는 않는다**.
        cands = by_name.get(ref) or []
        return cands[0] if len(cands) == 1 else ""
    return None


def _symbol_defined(rel_path: str, symbol: str) -> bool:
    """`def symbol` / `class symbol` 이 파일에 있는가. 마지막 마디만 본다."""
    leaf = symbol.rsplit(".", 1)[-1]
    try:
        text = (ROOT / rel_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True   # 못 읽으면 판정하지 않는다(다른 검사가 잡는다)
    return re.search(rf"^\s*(?:async\s+def|def|class)\s+{re.escape(leaf)}\b", text, re.M) is not None


def scan(md_files: list[str], paths: set[str], by_name: dict[str, list[str]]) -> list[core.Hit]:
    hits: list[core.Hit] = []
    for rel_md in md_files:
        try:
            lines = (ROOT / rel_md).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        suppressed = _suppressed_lines(lines)
        in_fence = False
        for lineno, raw in enumerate(lines, 1):
            if _FENCE_RE.match(raw):
                in_fence = not in_fence
                continue
            if in_fence or lineno in suppressed:
                continue
            for m in _REF_RE.finditer(raw):
                ref, symbol, line_s = m.group(1), m.group(2), m.group(3)
                resolved = _resolve(ref, paths, by_name)
                if resolved is None:
                    hits.append((rel_md, lineno, "DOC001", f"경로 없음: {ref}"))
                    continue
                if resolved == "":
                    continue  # 동명이인 — 판정 보류
                if line_s:
                    try:
                        n = sum(1 for _ in (ROOT / resolved).open(encoding="utf-8", errors="ignore"))
                    except OSError:
                        n = None
                    if n is not None and int(line_s) > n:
                        hits.append((rel_md, lineno, "DOC002",
                                     f"{resolved}:{line_s} — 파일은 {n}줄뿐"))
                if symbol and resolved.endswith(".py") and not _symbol_defined(resolved, symbol):
                    hits.append((rel_md, lineno, "DOC003",
                                 f"{resolved} 에 `{symbol}` 정의 없음(def/class 기준)"))
    return hits


def _default_targets() -> list[str]:
    out: list[str] = []
    for pat in DEFAULT_GLOBS:
        out += [p.relative_to(ROOT).as_posix() for p in ROOT.glob(pat) if p.is_file()]
    return sorted(set(out))


def _main() -> int:
    diff_spec, files = core.parse_cli(sys.argv[1:])
    md_files = [f.replace("\\", "/") for f in files if f.endswith(".md")] or _default_targets()
    if not md_files:
        return 0

    paths, by_name = _tracked_index()
    violations = scan(md_files, paths, by_name)

    added = core.added_lines(
        _git(core.git_diff_cmd(diff_spec)),
        _git(core.git_untracked_cmd(md_files)),
    )
    new_hits, legacy = core.split_new_vs_legacy(violations, added)
    return core.emit(TOOL, new_hits, legacy, added)


if __name__ == "__main__":
    sys.exit(core.run_guarded(_main))
