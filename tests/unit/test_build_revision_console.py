"""Jenkins 콘솔 로그에서 빌드가 **실제로 체크아웃한** SVN revision 직독.

실측 KJPDS02_PV `jenkins_console.log`(build_125):

    Checking out Revision e98d2722... (refs/remotes/origin/master)   ← git 미러(무관)
    Updating svn://192.168.110.33/ADOS/NE1AW_PORTING at revision '2026-07-24T13:00:11.266 +0900'
    At revision 1082                                                  ← 이것이 사실

33빌드 실측: 31건 해석(고유 revision 21개), 2건은 로그가 상한(2,000,000 bytes)에 걸려
선두가 잘린 케이스 → 정직하게 빈 값 + 사유(폴백이 svn 날짜-revision으로 처리).
"""
from __future__ import annotations

URL = "svn://192.168.110.33/ADOS/NE1AW_PORTING"

REAL_LOG = """\
Started by timer
[Pipeline] node
Running on agent in C:/jenkins/workspace/KJPDS02_PV
Checking out Revision e98d2722878331316fc44be04139ee280692c7c0 (refs/remotes/origin/master)
 > git config core.sparsecheckout
[Pipeline] bat
Updating svn://192.168.110.33/ADOS/NE1AW_PORTING at revision '2026-07-24T13:00:11.266 +0900' --quiet

At revision 1082

[Pipeline] End of Pipeline
Finished: SUCCESS
"""


def test_parses_real_console_shape():
    from backend.services.build_revision import revision_from_console_text

    assert revision_from_console_text(REAL_LOG, repo_url=URL) == {"revision": "1082", "reason": ""}


def test_git_sha_line_is_not_mistaken_for_revision():
    """`Checking out Revision <sha1>`(git)을 SVN revision으로 오인하면 안 된다."""
    from backend.services.build_revision import parse_console_revisions

    pairs = parse_console_revisions(REAL_LOG)
    assert pairs == [(URL, 1082)]          # git 라인은 URL 형태가 아니라 짝을 이루지 않는다


def test_checked_out_and_updated_to_variants():
    from backend.services.build_revision import revision_from_console_text

    for line in ("Checked out revision 1053.", "Updated to revision 1053.", "At revision 1053"):
        text = f"Updating {URL} at revision 'x'\n{line}\n"
        assert revision_from_console_text(text, repo_url=URL)["revision"] == "1053", line


def test_url_mismatch_is_honest_not_guessed():
    """다른 저장소의 revision을 주워오면 안 된다 — 틀린 트리를 '고정됨'으로 위장하게 된다."""
    from backend.services.build_revision import revision_from_console_text

    text = "Updating svn://other/REPO at revision 'x'\nAt revision 999\n"
    r = revision_from_console_text(text, repo_url=URL)
    assert r["revision"] == "" and r["reason"] == "console_url_mismatch"


def test_subpath_checkout_matches_on_path_boundary():
    from backend.services.build_revision import revision_from_console_text

    sub = f"{URL}/APP"
    assert revision_from_console_text(
        f"Updating {sub} at revision 'x'\nAt revision 1060\n", repo_url=URL)["revision"] == "1060"
    # 경계 없는 접두는 매치 금지(`/ADOS/NE1`이 `/ADOS/NE1AW_PORTING`을 삼키면 안 됨)
    near = "svn://192.168.110.33/ADOS/NE1"
    assert revision_from_console_text(
        f"Updating {URL} at revision 'x'\nAt revision 1060\n", repo_url=near)["revision"] == ""


def test_ambiguous_multiple_revisions_refuses_to_pick():
    """같은 URL에 서로 다른 revision이 찍히면 포기한다(하나를 찍으면 틀린 트리를 고정 위장)."""
    from backend.services.build_revision import revision_from_console_text

    text = (f"Updating {URL} at revision 'a'\nAt revision 1040\n"
            f"Updating {URL} at revision 'b'\nAt revision 1055\n")
    r = revision_from_console_text(text, repo_url=URL)
    assert r["revision"] == "" and r["reason"].startswith("console_ambiguous:")
    assert "1040" in r["reason"] and "1055" in r["reason"]


def test_same_revision_twice_is_not_ambiguous():
    from backend.services.build_revision import revision_from_console_text

    text = (f"Updating {URL} at revision 'a'\nAt revision 1040\n"
            f"Updating {URL} at revision 'b'\nAt revision 1040\n")
    assert revision_from_console_text(text, repo_url=URL)["revision"] == "1040"


def test_truncated_log_without_scm_section_is_honest():
    """로그가 상한에 걸려 선두가 잘리면(실측 build_105/107) 빈 값 + 사유."""
    from backend.services.build_revision import revision_from_console_text

    r = revision_from_console_text("[Pipeline] // node\nFinished: SUCCESS\n", repo_url=URL)
    assert r["revision"] == "" and r["reason"] == "console_no_svn_revision"


def test_missing_log_file(tmp_path):
    from backend.services.build_revision import revision_from_console_log

    r = revision_from_console_log(tmp_path, repo_url=URL)
    assert r["revision"] == "" and r["reason"] == "console_log_missing"


def test_head_only_read_finds_leading_scm_section(tmp_path):
    """SCM 스텝은 로그 선두라 앞부분만 읽어도 손실이 없다(33빌드 66MB 회피)."""
    from backend.services.build_revision import revision_from_console_log

    (tmp_path / "jenkins_console.log").write_text(
        REAL_LOG + ("x" * 3_000_000), encoding="utf-8")
    assert revision_from_console_log(tmp_path, repo_url=URL, head_bytes=8192)["revision"] == "1082"


def test_revision_after_unrelated_target_is_not_stolen():
    """대상 라인 뒤 **첫** revision만 짝짓는다 — 뒤따르는 무관한 숫자를 끌어오지 않는다."""
    from backend.services.build_revision import parse_console_revisions

    text = (f"Updating {URL} at revision 'a'\nAt revision 1040\n"
            "At revision 9999\n")   # 짝 없는 고아 — 무시돼야 한다
    assert parse_console_revisions(text) == [(URL, 1040)]
