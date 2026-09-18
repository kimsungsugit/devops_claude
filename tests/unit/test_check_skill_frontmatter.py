"""scripts/check_skill_frontmatter.py — 스킬 트리거가 조용히 사라지는 걸 막는 게이트.

배경 — 이 검사가 왜 있나:
2026-07-17에 스킬 **16개 전부**(프로젝트 14 + 플러그인 2) 트리거 문구가 모델에
노출되지 않고 있었다. 두 경로:
  1. 9개는 `trigger:` 라는 **비공식 필드**를 썼다 → 경고 없이 무시
  2. 7개는 `when_to_use` 자체가 없었다 → 트리거 0
둘 다 하네스가 아무 말도 안 하므로 **눈으로는 구분이 불가능**하다. 기계 검사가
유일한 방어이고, 그래서 이 테스트의 절반은 "검사기가 실제로 실패하는가"를 본다 —
통과만 하는 검사기는 게이트가 아니라 fake-green 이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_skill_frontmatter as csf  # noqa: E402

_GOOD = """\
---
name: demo
description: 데모 스킬이다.
when_to_use: 데모, 예시 요청 시
---

# 본문
"""


def _write(tmp_path: Path, body: str, *, skill: str = "demo") -> Path:
    d = tmp_path / ".claude" / "skills" / skill
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_good_file_has_no_issues(tmp_path: Path) -> None:
    assert csf.check_file(_write(tmp_path, _GOOD)) == []


# --- 각 결함이 실제로 잡히는가 (mutation) --------------------------------


def test_trigger_field_is_flagged_as_unknown(tmp_path: Path) -> None:
    """`trigger:` — 실제로 9개 스킬을 무력화했던 그 필드."""
    body = _GOOD.replace("when_to_use: 데모, 예시 요청 시", "trigger: 데모, 예시 요청 시")
    issues = csf.check_file(_write(tmp_path, body))
    # 두 가지가 동시에 잡혀야 한다: 미지 필드 + when_to_use 부재
    assert any("trigger" in i for i in issues), issues
    assert any("when_to_use" in i for i in issues), issues


def test_most_silent_defect_is_reported_first(tmp_path: Path) -> None:
    """순서 = 심각도. 호출부가 상위 3건만 보여주고 나머지를 접는다.

    `trigger:`(미지 필드)가 뒤로 밀리면 "(+N more)"에 삼켜져 **가장 중요한
    결함이 안 보인다** — 침묵 절단이 "다 봤다"로 읽히는 그 패턴이다.
    """
    body = "---\nname: wrong\ntrigger: 무시됨\n---\n\n# 본문\n"
    issues = csf.check_file(_write(tmp_path, body))
    assert len(issues) >= 4, issues
    assert "미지 필드" in issues[0], f"미지 필드가 1순위가 아니다: {issues}"
    assert "when_to_use" in issues[1], f"트리거 0 이 2순위가 아니다: {issues}"


def test_missing_when_to_use_is_flagged(tmp_path: Path) -> None:
    body = "---\nname: demo\ndescription: 설명.\n---\n"
    issues = csf.check_file(_write(tmp_path, body))
    assert any("when_to_use" in i and "트리거" in i for i in issues), issues


def test_name_mismatch_with_directory_is_flagged(tmp_path: Path) -> None:
    """`name` 은 표시 라벨이고 실제 커맨드는 디렉터리명 — 어긋나면 혼란이다."""
    body = _GOOD.replace("name: demo", "name: not-the-dir")
    issues = csf.check_file(_write(tmp_path, body))
    assert any("not-the-dir" in i and "/demo" in i for i in issues), issues


def _write_at(tmp_path: Path, rel: str, body: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# --- 위치 분류 (skill_location) — "스킬이 뭐냐"의 단일 정의 -----------------


@pytest.mark.parametrize(
    "rel, kind, command",
    [
        (".claude/skills/demo/SKILL.md", "project", "/demo"),
        (".claude/plugins/my-plugin/skills/doc-gen/SKILL.md", "plugin", "/my-plugin:doc-gen"),
        (".claude/plugins/my-plugin/SKILL.md", "plugin_root", "/my-plugin:"),
        (".claude/skills/group/nested/SKILL.md", "nested", ""),
        (".claude/plugins/my-plugin/skills/a/b/SKILL.md", "nested", ""),
        ("vendor/site-packages/fastapi/SKILL.md", "unknown", ""),
    ],
)
def test_skill_location_classifies(tmp_path: Path, rel: str, kind: str, command: str) -> None:
    p = _write_at(tmp_path, rel, _GOOD)
    assert csf.skill_location(p) == (kind, command)


def test_nested_skill_is_flagged_not_stamped_clean(tmp_path: Path) -> None:
    """**오음성 방지** — 중첩 스킬은 discovery 가 영구 불가인데 clean 을 찍고 있었다.

    CLAUDE.md: "스킬 discovery는 `.claude/skills/<name>/` 한 단계만". 이 저장소는
    실제로 이중중첩 9개를 flatten 해야 했다. 호출 불가능한 스킬에 '이상 없음'
    도장을 찍는 건 침묵보다 나쁘다 — 오탐이 아니라 **오음성**이다.
    """
    p = _write_at(tmp_path, ".claude/skills/group/nested/SKILL.md", _GOOD)
    issues = csf.check_file(p)
    assert issues, "중첩 스킬에 clean 도장을 찍었다"
    assert "discovery" in issues[0], f"위치 결함이 1순위가 아니다: {issues}"


def test_plugin_root_name_is_not_flagged(tmp_path: Path) -> None:
    """플러그인 루트는 `name` 이 **커맨드 이름을 정하는** 유일한 자리.

    공식 문서: "The plugin-root case is the one place where `name` does set the
    command name". 여기서 불일치를 신고하면 **정답을 오답이라 모는** 오탐이다.
    """
    p = _write_at(
        tmp_path,
        ".claude/plugins/my-plugin/SKILL.md",
        "---\nname: review\ndescription: 설명.\nwhen_to_use: 예시 시\n---\n",
    )
    assert csf.check_file(p) == []


def test_plugin_skill_accepts_namespaced_name(tmp_path: Path) -> None:
    """플러그인 스킬 호출명은 **네임스페이스로 감싸진다**(`/<plugin>:<name>`).

    CLAUDE.md 가 `/devops-release:doc-gen` 이라 광고하므로 그 표기를 라벨로 써도
    정답이다. 이걸 신고하면 정답을 오답이라 모는 것.
    """
    p = _write_at(
        tmp_path,
        ".claude/plugins/my-plugin/skills/doc-gen/SKILL.md",
        "---\nname: my-plugin:doc-gen\ndescription: 설명.\nwhen_to_use: 예시 시\n---\n",
    )
    assert csf.check_file(p) == []


def test_plugin_skill_wrong_name_points_at_namespaced_command(tmp_path: Path) -> None:
    """틀렸을 땐 **네임스페이스 포함** 실제 호출명을 알려줘야 한다."""
    p = _write_at(
        tmp_path,
        ".claude/plugins/my-plugin/skills/doc-gen/SKILL.md",
        "---\nname: wrong\ndescription: 설명.\nwhen_to_use: 예시 시\n---\n",
    )
    issues = csf.check_file(p)
    assert any("/my-plugin:doc-gen" in i for i in issues), issues


def test_absent_name_is_not_an_issue(tmp_path: Path) -> None:
    """공식 스펙: `name` 은 선택이고 **디렉터리명이 기본값**이다.

    이걸 '필수 누락'으로 잡으면 정상 스킬에 오탐을 낸다.
    """
    body = "---\ndescription: 설명.\nwhen_to_use: 예시 시\n---\n"
    assert csf.check_file(_write(tmp_path, body)) == []


def test_over_char_limit_is_flagged(tmp_path: Path) -> None:
    body = _GOOD.replace("데모 스킬이다.", "가" * (csf.CHAR_LIMIT + 1))
    issues = csf.check_file(_write(tmp_path, body))
    assert any(str(csf.CHAR_LIMIT) in i and "잘린다" in i for i in issues), issues


def test_exactly_at_limit_is_allowed(tmp_path: Path) -> None:
    """경계값 — 상한 '초과'만 문제다. off-by-one 로 정상 스킬을 막지 않는다."""
    wtu = "예시 요청 시"
    desc = "가" * (csf.CHAR_LIMIT - len(wtu))
    body = f"---\nname: demo\ndescription: {desc}\nwhen_to_use: {wtu}\n---\n"
    assert csf.check_file(_write(tmp_path, body)) == []


def test_missing_description_is_flagged(tmp_path: Path) -> None:
    """스펙상 선택이지만(첫 문단 폴백) 그 폴백으론 자동 호출 매칭이 안 된다."""
    body = "---\nname: demo\nwhen_to_use: 예시 시\n---\n\n# 본문 첫 문단\n"
    issues = csf.check_file(_write(tmp_path, body))
    assert any("description" in i for i in issues), issues


@pytest.mark.parametrize(
    "field",
    ["argument-hint", "arguments", "disable-model-invocation", "user-invocable",
     "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent",
     "hooks", "paths", "shell"],
)
def test_official_optional_fields_are_not_flagged(tmp_path: Path, field: str) -> None:
    """공식 16개 필드는 오탐 없이 통과해야 한다.

    allowlist 가 실제보다 좁으면 **정상 필드를 결함으로 신고**한다 — 검사기가
    신뢰를 잃는 가장 빠른 길이다. 공식 문서(skills.md "Frontmatter reference")의
    선택 필드를 전부 넣어 잠근다.
    """
    body = _GOOD.replace("---\n\n# 본문", f"{field}: some-value\n---\n\n# 본문")
    assert csf.check_file(_write(tmp_path, body)) == [], f"{field} 오탐"


def test_no_frontmatter_is_flagged(tmp_path: Path) -> None:
    issues = csf.check_file(_write(tmp_path, "# 그냥 마크다운\n"))
    assert any("frontmatter" in i for i in issues), issues


def test_unterminated_frontmatter_is_flagged(tmp_path: Path) -> None:
    issues = csf.check_file(_write(tmp_path, "---\nname: demo\ndescription: x\n"))
    assert any("닫히지" in i for i in issues), issues


def test_malformed_yaml_is_flagged(tmp_path: Path) -> None:
    issues = csf.check_file(_write(tmp_path, "---\nname: [unclosed\n---\n"))
    assert any("YAML" in i for i in issues), issues


def test_frontmatter_not_a_mapping_is_flagged(tmp_path: Path) -> None:
    issues = csf.check_file(_write(tmp_path, "---\n- just\n- a list\n---\n"))
    assert any("mapping" in i for i in issues), issues


def test_non_string_yaml_key_does_not_crash(tmp_path: Path) -> None:
    """YAML 은 `on:`→bool, `2026:`→int 키를 만든다. 섞이면 sorted() 가 TypeError.

    검사기가 임의 입력에 **자기가 죽으면** 그게 곧 fake-green(결과 없음).
    """
    body = "---\nname: demo\ndescription: d\nwhen_to_use: w\non: x\ncustom: z\n2026: y\n---\n"
    issues = csf.check_file(_write(tmp_path, body))  # 예외 안 나야 함
    # bool True 는 str() 하면 "True" — 미지 필드로 잡히되 크래시는 없다
    assert any("미지 필드" in i for i in issues), issues


def test_bom_prefixed_file_is_not_falsely_rejected(tmp_path: Path) -> None:
    """BOM(win32/PowerShell 저장 산물)이 붙어도 정상 파일은 통과해야 한다.

    utf-8 로 읽으면 BOM 때문에 "frontmatter 없음"이라 **거짓말**한다 — 열어보면
    1행이 `---` 다. 검사기가 거짓말하는 순간이 신뢰를 잃는 순간.
    """
    p = _write(tmp_path, _GOOD)
    p.write_bytes(b"\xef\xbb\xbf" + _GOOD.encode("utf-8"))
    assert csf.check_file(p) == []


def test_yaml_coerced_when_to_use_is_flagged(tmp_path: Path) -> None:
    """`when_to_use: yes` → YAML bool True. 비어있진 않지만 트리거로 못 쓴다."""
    body = "---\nname: demo\ndescription: d\nwhen_to_use: yes\n---\n"
    issues = csf.check_file(_write(tmp_path, body))
    assert any("when_to_use" in i and "문자열이 아님" in i for i in issues), issues


def test_unreadable_file_reports_instead_of_passing(tmp_path: Path) -> None:
    """읽기 실패를 빈 리스트로 삼키면 '이상 없음'으로 위장된다."""
    issues = csf.check_file(tmp_path / "does-not-exist" / "SKILL.md")
    assert issues and "읽기 실패" in issues[0], issues


def test_missing_pyyaml_is_disabled_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """PyYAML 부재는 **검사 불가**(DISABLED)지 통과가 아니다.

    이 저장소가 훅에서 온종일 싸운 패턴 — 도구가 없어 아무것도 못 봤는데
    빈 결과가 'clean' 으로 읽히는 것 — 을 여기서 되풀이하지 않는다.
    """
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *a, **kw):
        if name == "yaml":
            raise ImportError("No module named yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", fake_import)
    fm, err = csf.parse_frontmatter(_GOOD)
    assert fm is None
    assert err.startswith("DISABLED"), err
    assert "통과 아님" in err


# --- 실제 스킬 트리 잠금 (회귀) -------------------------------------------


def _real_skills() -> list[Path]:
    # CLI 와 **같은 열거 함수**를 쓴다 — 테스트가 따로 rglob 하면 스코프가 갈라진다.
    return csf.iter_skills(_ROOT)


def test_repo_has_skills() -> None:
    """스킬을 0개로 읽으면 아래 검사가 전부 공허하게 통과한다."""
    assert len(_real_skills()) >= 10


def test_scan_covers_plugin_skills() -> None:
    """CLI 스캔 범위 == 훅 검사 범위. 어긋나면 CLI 가 'clean' 이라 해도 훅이 문다."""
    found = {p.parent.name for p in _real_skills()}
    assert {"doc-gen", "review"} <= found, f"플러그인 스킬 누락: {sorted(found)}"


@pytest.mark.parametrize("path", _real_skills(), ids=lambda p: p.parent.name)
def test_every_real_skill_is_clean(path: Path) -> None:
    assert csf.check_file(path) == []


def test_main_returns_zero_on_clean_tree(capsys: pytest.CaptureFixture) -> None:
    assert csf.main([]) == 0
    assert "이상 없음" in capsys.readouterr().out


def test_main_returns_one_when_a_skill_is_broken(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """exit code 계약 — 0 이 아니어야 CI/훅이 실패를 본다."""
    bad = _write(tmp_path, _GOOD.replace("when_to_use: 데모, 예시 요청 시", "trigger: 데모"))
    assert csf.main([str(bad)]) == 1
    assert "trigger" in capsys.readouterr().out


# --- PostToolUse 훅 배선 (markdown_lint_hook) -----------------------------
#
# 이 훅은 **모든 .md 편집**마다 돈다. SKILL.md 분기를 여기에 실었으므로
# (a) 결함이 실제로 표면화되는지 (b) 다른 .md 를 오염시키지 않는지 둘 다 잠근다.


import markdown_lint_hook as mlh  # noqa: E402


def _run_hook(path: Path, capsys: pytest.CaptureFixture) -> str:
    mlh.main({"tool_input": {"file_path": str(path)}})
    return capsys.readouterr().out


def test_hook_surfaces_frontmatter_defect(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    bad = _write(tmp_path, "---\nname: demo\ntrigger: 무시됨\n---\n\n# 본문\n")
    out = _run_hook(bad, capsys)
    assert "frontmatter" in out and "trigger" in out, out


def test_hook_is_clean_on_valid_skill(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out = _run_hook(_write(tmp_path, _GOOD), capsys)
    assert "clean" in out, out


def test_hook_emits_readable_korean(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """ensure_ascii=False — \\uXXXX 로 깨지면 사람이 못 읽는다."""
    bad = _write(tmp_path, "---\nname: demo\ntrigger: 무시됨\n---\n\n# 본문\n")
    out = _run_hook(bad, capsys)
    assert "미지 필드" in out, out
    assert "\\u" not in out, f"한글이 이스케이프됨: {out}"


def test_hook_skips_frontmatter_check_for_ordinary_md(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """일반 .md 는 frontmatter 검사 대상이 아니다 — 오탐 방지 회귀."""
    p = tmp_path / "README.md"
    p.write_text("# 제목\n\n본문\n", encoding="utf-8")
    out = _run_hook(p, capsys)
    assert "frontmatter" not in out, out


def test_hook_reports_when_checker_is_unimportable(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검사기를 못 부르면 **침묵하지 않고** 보고한다.

    조용히 넘어가면 '검사했고 깨끗함'과 구분이 안 된다 — 이 저장소의 fake-green.
    """
    monkeypatch.setitem(sys.modules, "check_skill_frontmatter", None)
    out = _run_hook(_write(tmp_path, _GOOD), capsys)
    assert "검사 불가" in out and "통과 아님" in out, out
