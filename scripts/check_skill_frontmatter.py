"""SKILL.md frontmatter 검증 — **조용히 실패하는** 결함들을 잡는다.

스킬이 자동 호출되려면 (1) 올바른 위치에 있고 (2) frontmatter 의
`description` + `when_to_use` 가 모델에 노출되어야 한다. 그런데 이게 안 되는
경로가 여럿이고 **전부 아무 경고도 없다** — 눈으로는 구분이 안 된다:

1. **잘못된 필드명** — `trigger:` 같은 미지 필드는 경고 없이 무시된다. 2026-07-17
   이전 9개 스킬이 `trigger:` 를 써서 트리거 문구가 전부 무효였다
   (`/start-work` 의 "다 고쳐/이어서/1번부터" 포함)
2. **필드 부재** — `when_to_use` 가 없으면 트리거 문구가 0이다. `/hotfix`·
   `/doc-pipeline` 은 CLAUDE.md 가 "자동 연결"이라 부르면서 실제론 여기 있었다
3. **잘못된 위치** — `.claude/skills/<name>/` 한 단계만 discovery 된다. 중첩되면
   스킬로 **인식조차 안 되는데** 파일은 멀쩡해 보인다(이 저장소가 flatten 으로 당함)
4. **YAML 강제 변환** — `when_to_use: yes` 는 bool True 로 읽혀 트리거가 "True" 가 된다

검사기가 임의 입력에 스스로 죽어도(TypeError/BOM 오탐) 그게 곧 fake-green 이므로
그런 방어도 여기 포함한다. 기계 검사가 이 침묵을 깨는 유일한 방어다.

사용:
    .venv/Scripts/python.exe scripts/check_skill_frontmatter.py           # 전체 스캔
    .venv/Scripts/python.exe scripts/check_skill_frontmatter.py <path>    # 단일 파일

exit 0 = 문제 없음 / 1 = 문제 있음 / 2 = **검사 불가**(DISABLED — 통과 아님)
"""
from __future__ import annotations

import sys
from pathlib import Path

# description + when_to_use 합산 상한. 초과분은 잘려서 — 역시 조용히 — 사라진다.
# 공식 문서 원문: "the combined `description` and `when_to_use` text is truncated
# at 1,536 characters in the skill listing to reduce context usage."
CHAR_LIMIT = 1536

# 공식 frontmatter 필드 **전 16개** (https://code.claude.com/docs/en/skills.md
# "Frontmatter reference", 2026-07-17 원문 대조). 여기 없는 필드는 조용히 무시된다.
#
# ⚠ 이 집합이 실제보다 좁으면 **정상 필드에 오탐**을 낸다. 하네스에 새 필드가
#    생기면 위 문서를 다시 보고 여기에 추가할 것. 오탐이 나면 그건 이 집합의
#    문제이지 스킬의 문제가 아니다.
KNOWN_FIELDS = {
    "name",                      # 목록에 뜨는 **표시 라벨**. 기본값 = 디렉터리명
    "description",               # 자동 호출 판정의 주 근거 (권장)
    "when_to_use",               # 트리거 문구 — description 뒤에 이어붙어 노출된다
    "argument-hint",             # 자동완성 힌트
    "arguments",                 # $name 치환용 위치 인수
    "disable-model-invocation",  # true = Claude 자동 호출 차단 (수동 전용)
    "user-invocable",            # false = / 메뉴에서 숨김
    "allowed-tools",             # 이 턴에 사전 승인할 도구
    "disallowed-tools",          # 이 스킬 활성 중 차단할 도구
    "model",                     # 모델 오버라이드
    "effort",                    # 노력 수준 오버라이드
    "context",                   # fork = 별도 subagent 컨텍스트
    "agent",                     # context: fork 일 때 subagent 타입
    "hooks",                     # 이 스킬 라이프사이클 훅
    "paths",                     # glob — 매칭 파일 작업 시에만 자동 로드
    "shell",                     # bash | powershell
}

# ⚠ 공식 스펙상 **필수 필드는 없다.** `name` 은 디렉터리명으로, `description` 은
#    본문 첫 문단으로 폴백한다. 다만 첫 문단 폴백은 자동 호출 매칭에 거의 쓸모가
#    없으므로(본문은 절차 설명이지 "언제 쓰나"가 아니다) 이 저장소는 description 을
#    요구한다 — 스펙 위반이 아니라 **프로젝트 정책**이다.
RECOMMENDED_FIELDS = ("description",)


def parse_frontmatter(raw: str) -> tuple[dict | None, str]:
    """YAML frontmatter 를 파싱한다. 반환: (mapping, error_message)."""
    try:
        import yaml
    except ImportError:
        return None, "DISABLED: PyYAML 미설치 — 검사 불가(통과 아님). venv 확인"

    if not raw.startswith("---"):
        return None, "frontmatter 없음 (파일이 '---' 로 시작해야 한다)"
    end = raw.find("\n---", 3)
    if end == -1:
        return None, "frontmatter 가 닫히지 않음 (종료 '---' 없음)"
    try:
        fm = yaml.safe_load(raw[3:end])
    except Exception as e:  # yaml.YAMLError 외 스캐너 예외도 있어 광범위하게 잡는다
        return None, f"YAML 파싱 실패: {e}"
    if fm is None:
        return None, "frontmatter 가 비어 있음"
    if not isinstance(fm, dict):
        return None, f"frontmatter 가 mapping 이 아님 ({type(fm).__name__})"
    return fm, ""


def skill_location(path: Path) -> tuple[str, str]:
    """SKILL.md 를 **하네스 관점**에서 분류한다. 반환: (kind, 실제 호출명).

    이게 "스킬이 뭐냐"의 **단일 정의**다. CLI 스캔·훅·테스트가 전부 이걸 쓴다 —
    셋이 각자 판정하면 갈라진다(실제로 CLI 가 `.claude/skills/*` 만 봐서 플러그인
    스킬 2개를 놓친 적이 있다).

    kind:
      `project`     `.claude/skills/<name>/SKILL.md`              → `/<name>`
      `plugin`      `.claude/plugins/<p>/skills/<name>/SKILL.md`  → `/<p>:<name>`
      `plugin_root` `.claude/plugins/<p>/SKILL.md`                → `/<p>:<frontmatter name>`
                    (**유일하게 `name` 이 호출명을 정하는 자리** — 스킬 디렉터리가 없어서)
      `nested`      `.claude/skills/` 아래 **2단 이상**           → **discovery 안 됨**
      `unknown`     스킬 위치가 아님(서드파티 패키지 등)          → 판정 보류
    """
    try:
        parts = path.resolve().parts
    except OSError:  # 경로가 깨졌어도 판정 자체는 계속한다
        parts = path.parts

    # 가장 안쪽 `.claude` 기준 — 중첩 저장소(`apps/web/.claude/`)도 각자 유효하다
    idx = max((i for i, seg in enumerate(parts) if seg == ".claude"), default=-1)
    if idx < 0:
        return "unknown", ""
    rest = parts[idx + 1:]

    if rest[:1] == ("skills",):
        # ("skills", <name>, "SKILL.md") 만 유효 — 그 이상 깊으면 스캔 안 된다
        if len(rest) == 3:
            return "project", f"/{rest[1]}"
        return "nested", ""

    if rest[:1] == ("plugins",) and len(rest) >= 3:
        plugin = rest[1]
        if len(rest) == 3:  # <plugin>/SKILL.md
            return "plugin_root", f"/{plugin}:"
        if rest[2] == "skills":
            if len(rest) == 5:  # <plugin>/skills/<name>/SKILL.md
                return "plugin", f"/{plugin}:{rest[3]}"
            return "nested", ""

    return "unknown", ""


def inspect_file(path: Path) -> tuple[list[str], dict | None]:
    """SKILL.md 하나를 검사한다. 반환: (문제 목록, frontmatter).

    frontmatter 는 통계 출력용이며 파싱 실패 시 None. 한 번만 읽고 파싱한다.
    """
    # utf-8-sig — BOM 이 있으면 벗기고 없으면 utf-8 과 동일(엄격히 우월).
    # BOM 을 안 벗기면 정상 파일에 "frontmatter 없음(파일이 '---' 로 시작해야
    # 한다)"고 **거짓말**한다 — 열어보면 1행이 `---` 다. 검사기가 거짓말하는
    # 순간이 늑대소년이 되는 순간이고, 여긴 win32/PowerShell 저장소라 BOM 이 붙는다.
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception as e:
        return [f"읽기 실패: {type(e).__name__}: {e}"], None

    fm, err = parse_frontmatter(raw)
    if fm is None:
        return [err], None

    # ⚠ 순서 = 심각도. 호출부(markdown_lint_hook)가 **상위 3건만** 보여주고
    #    나머지를 "(+N more)"로 접으므로, 뒤로 밀린 항목은 사실상 안 보인다.
    #    가장 조용히 죽는 것(위치 자체가 잘못 → 아예 로드 안 됨)을 맨 앞에 둔다.
    issues: list[str] = []
    kind, command = skill_location(path)
    desc = str(fm.get("description") or "").strip()
    wtu = str(fm.get("when_to_use") or "").strip()

    # 0) 위치 — 여기가 틀리면 아래 검사는 전부 무의미하다. 스킬이 **로드조차 안 된다.**
    #    이 저장소가 실제로 당한 결함(이중중첩 9개를 flatten 해야 했다)이고,
    #    CLAUDE.md 가 "discovery 는 `.claude/skills/<name>/` 한 단계만"이라 못박고 있다.
    #    여기서 침묵하면 **호출 불가능한 스킬에 clean 도장**을 찍는 셈 — 오탐보다 나쁘다.
    if kind == "nested":
        issues.append(
            "discovery 안 됨 — `.claude/skills/<name>/SKILL.md` 한 단계만 스캔된다"
            " (중첩 디렉터리는 스킬로 인식되지 않는다). 평탄화할 것"
        )

    # 1) 미지 필드 — `trigger:` 가 여기 걸린다. 하네스는 아무 말도 안 한다.
    #    map(str, ...) — YAML 은 bool/int 키를 만든다(`on:` → True, `2026:` → int).
    #    섞인 타입을 그냥 sorted() 하면 TypeError 로 검사기 자신이 죽는다.
    unknown = sorted(map(str, set(fm) - KNOWN_FIELDS))
    if unknown:
        issues.append(f"미지 필드 {unknown} — 경고 없이 무시된다 (공식 16개 아님)")

    # 2) 트리거 문구 0
    if not wtu:
        issues.append("`when_to_use` 없음 — 트리거 문구 0 (직접 타이핑해야만 걸림)")

    # 3) 매칭 근거 없음
    for field in RECOMMENDED_FIELDS:
        if not str(fm.get(field) or "").strip():
            issues.append(f"`{field}` 없음 — 본문 첫 문단 폴백으론 자동 호출 매칭이 안 된다")

    # 4) 값이 문자열이 아님 — `when_to_use: yes` 는 YAML 이 bool True 로 읽어
    #    트리거가 문자 그대로 "True" 가 된다. 비어있진 않아서 3)을 통과한다.
    for field in ("description", "when_to_use"):
        val = fm.get(field)
        if val is not None and not isinstance(val, str):
            issues.append(
                f"`{field}` 가 문자열이 아님 ({type(val).__name__}) — "
                f"YAML 이 값을 변환했다. 따옴표로 감쌀 것"
            )

    # 5) 초과분 절단
    total = len(desc) + len(wtu)
    if total > CHAR_LIMIT:
        issues.append(f"description+when_to_use {total}자 > {CHAR_LIMIT}자 — 초과분이 조용히 잘린다")

    # 6) 표시 라벨 혼란 — `name` 은 표시용일 뿐이고 호출명은 **위치**에서 온다.
    #    동작 불능은 아니라 마지막.
    #    ⚠ `plugin_root` 는 검사하지 않는다 — 공식 문서: "The plugin-root case is
    #    the one place where `name` does set the command name, because there is no
    #    skill directory to take it from." 거기서 신고하면 **정답을 오답이라 모는** 오탐이다.
    #    ⚠ `plugin` 은 호출명이 **네임스페이스로 감싸진다**(`/<plugin>:<name>`).
    #    라벨로는 디렉터리명과 네임스페이스 전체명 둘 다 말이 되므로 둘 다 허용한다.
    name = str(fm.get("name") or "").strip()
    if name and kind in ("project", "plugin", "nested"):
        acceptable = {path.parent.name}
        if command:
            acceptable.add(command.lstrip("/"))
        if name not in acceptable:
            hint = f" — 실제 호출은 `{command}`" if command else ""
            issues.append(f"`name: {name}` 이 위치와 불일치{hint}")

    return issues, fm


def check_file(path: Path) -> list[str]:
    """문제 목록만 필요한 호출자용 얇은 래퍼 (markdown_lint_hook 이 쓴다)."""
    return inspect_file(path)[0]


def iter_skills(root: Path) -> list[Path]:
    """검사 대상 SKILL.md 를 열거한다 — **CLI·테스트 공용 단일 소스**.

    `.claude/` 전체를 rglob 하되 `skill_location` 이 `unknown` 으로 본 것(서드파티
    패키지가 vendored 한 SKILL.md 등)은 뺀다. `nested` 는 **남긴다** — 그건 우리
    스킬인데 잘못 놓인 것이라 검사기가 "discovery 안 됨"으로 신고해야 한다.

    ⚠ CLI 와 테스트가 각자 열거하면 갈라진다(실제로 CLI 가 `.claude/skills/*` 만
       봐서 플러그인 2개를 놓쳤다). "스킬이 뭐냐"는 여기 한 곳에서만 정한다.
    """
    out = []
    for p in sorted((root / ".claude").rglob("SKILL.md")):
        if skill_location(p)[0] != "unknown":
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]

    targets = [Path(a) for a in argv] if argv else iter_skills(root)

    if not targets:
        print("검사 대상 SKILL.md 가 없다 — 경로 확인", file=sys.stderr)
        return 2

    # PyYAML 부재는 전 파일에 동일하게 걸리므로 한 번만 판정하고 즉시 빠진다.
    # (여기서 0 을 내면 "검사 안 함"이 "통과"로 읽힌다 — 이 저장소의 fake-green)
    probe, err = parse_frontmatter("---\nname: probe\n---\n")
    if probe is None and err.startswith("DISABLED"):
        print(err, file=sys.stderr)
        return 2

    rows: list[tuple[str, int, int, int]] = []
    problems: list[tuple[Path, list[str]]] = []
    for p in targets:
        found, fm = inspect_file(p)
        if found:
            problems.append((p, found))
        if fm:
            d = len(str(fm.get("description") or "").strip())
            w = len(str(fm.get("when_to_use") or "").strip())
            rows.append((str(fm.get("name") or p.parent.name), d, w, d + w))

    if rows:
        print(f"{'skill':<20}{'desc':>6}{'wtu':>6}{'total':>7}  limit={CHAR_LIMIT}")
        print("-" * 46)
        for n, d, w, t in rows:
            flag = "" if t <= CHAR_LIMIT else "  <-- OVER"
            print(f"{n:<20}{d:>6}{w:>6}{t:>7}{flag}")
        print("-" * 46)

    if problems:
        print(f"\n문제 {sum(len(v) for _, v in problems)}건 / 파일 {len(problems)}개:")
        for p, found in problems:
            rel = p.relative_to(root) if p.is_absolute() and root in p.parents else p
            for msg in found:
                print(f"  {rel}: {msg}")
        return 1

    print(f"\n스킬 {len(rows)}개 — 이상 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
