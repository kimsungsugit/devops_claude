"""소스 스냅샷을 **빌드 시점 revision**으로 고정.

근본 결함(실측 KJPDS02_PV): `ensure_source_checkout`은 registry override 경로에서 revision을
비워 HEAD를 체크아웃했다. 그래서 4개월치 33개 빌드를 하루에 백필하면 전부 그날의 트리를 받아
26개 빌드가 베이스라인과 바이트 동일해졌다 — 빌드별 변경 영향이 0으로 보이고 ASIL 함수 변경이
통째로 침묵했다. 아래는 고정 경로·재수집 판정·실패 정직 보고 검증(subprocess 미접촉).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _write_sentinel(source_dir: Path, text: str) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / ".source_complete").write_text(text, encoding="utf-8")


# ── source_snapshot_is_pinned ────────────────────────────────────────────


def test_pinned_requires_both_revision_and_source(tmp_path):
    from backend.services.jenkins_service import source_snapshot_is_pinned

    src = tmp_path / "source"
    assert source_snapshot_is_pinned(src) is False           # 센티널 자체가 없음

    # 구 센티널(revision_source 키 없음) — 보수적으로 '고정 안 됨'
    _write_sentinel(src, "scm=svn\nrevision=\nbranch=master\n")
    assert source_snapshot_is_pinned(src) is False

    # revision은 있으나 출처 미상 → 여전히 고정 아님(HEAD였을 수 있다)
    _write_sentinel(src, "scm=svn\nrevision=1042\nbranch=master\n")
    assert source_snapshot_is_pinned(src) is False

    _write_sentinel(src, "scm=svn\nrevision=1042\nbranch=master\nrevision_source=head\n")
    assert source_snapshot_is_pinned(src) is False

    _write_sentinel(src, "scm=svn\nrevision=1042\nbranch=master\nrevision_source=svn_date\n")
    assert source_snapshot_is_pinned(src) is True


def test_real_world_unpinned_sentinel_shape(tmp_path):
    """실측 KJPDS02_PV 센티널(revision 빈 값)이 정확히 '고정 안 됨'으로 판정된다."""
    from backend.services.jenkins_service import read_source_sentinel, source_snapshot_is_pinned

    src = tmp_path / "source"
    _write_sentinel(src, "scm=svn\nrevision=\nbranch=refs/remotes/origin/master\n")
    assert read_source_sentinel(src)["scm"] == "svn"
    assert source_snapshot_is_pinned(src) is False


# ── resolve_build_svn_revision ───────────────────────────────────────────


def test_resolve_revision_from_build_timestamp(monkeypatch):
    from backend.services import jenkins_service as js

    seen = {}

    def fake_at_date(**kw):
        seen.update(kw)
        return {"rc": 0, "revision": "1053", "repo_root": "svn://x/ADOS"}

    monkeypatch.setattr(js, "svn_revision_at_date", fake_at_date)
    r = js.resolve_build_svn_revision(
        repo_url="svn://x/ADOS/PDS", build_timestamp_ms=_ms("2026-06-25T04:00:15.971Z"))
    assert r == {"revision": "1053", "error": ""}
    # 밀리초까지 유지 — map_builds_to_svn_revisions와 같은 정밀도라야 콤보박스 revision과 일치
    assert seen["when_iso"] == "2026-06-25T04:00:15.971Z"


def test_resolve_revision_missing_timestamp_is_honest_error(monkeypatch):
    from backend.services import jenkins_service as js

    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: (_ for _ in ()).throw(AssertionError("svn을 부르면 안 된다")))
    assert js.resolve_build_svn_revision(repo_url="svn://x", build_timestamp_ms=None)["revision"] == ""
    assert js.resolve_build_svn_revision(repo_url="", build_timestamp_ms=123)["revision"] == ""


def test_resolve_revision_svn_failure_is_reported_not_swallowed(monkeypatch):
    from backend.services import jenkins_service as js

    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: {"rc": 1, "revision": "", "output": "svn: E170013 unable to connect"})
    r = js.resolve_build_svn_revision(repo_url="svn://x", build_timestamp_ms=_ms("2026-06-25T04:00:15Z"))
    assert r["revision"] == "" and "E170013" in r["error"]

    def boom(**k):
        raise OSError("svn binary missing")

    monkeypatch.setattr(js, "svn_revision_at_date", boom)
    r2 = js.resolve_build_svn_revision(repo_url="svn://x", build_timestamp_ms=_ms("2026-06-25T04:00:15Z"))
    assert r2["revision"] == "" and "OSError" in r2["error"]


# ── 체크아웃 경로 ────────────────────────────────────────────────────────


class _Client:
    """registry override를 유발하는 실제 형태 — Jenkins는 git URL, registry는 svn URL."""

    def get_scm_meta(self, build_selector="lastSuccessfulBuild"):
        return {"repo_urls": ["http://git/mirror.git"], "scm": "git",
                "git_branch": "master", "git_commit": "deadbeef"}


class _Entry:
    id = "ados"
    scm_url = "svn://x/ADOS/PDS"
    scm_type = "svn"
    branch = ""


def _patch_common(monkeypatch, js, svn_calls):
    monkeypatch.setattr("backend.services.scm_registry.resolve_scm_credentials",
                        lambda **k: ("u", "p", _Entry()))

    def fake_run_svn(**kw):
        svn_calls.append(kw)
        Path(kw["project_root"], kw["workdir_rel"]).mkdir(parents=True, exist_ok=True)
        return {"rc": 0, "output": "Checked out revision 1053."}

    monkeypatch.setattr(js, "run_svn", fake_run_svn)


def test_pin_checks_out_build_revision_and_records_source(tmp_path, monkeypatch):
    """pin_revision=True면 svn checkout이 -r <빌드시점 rev>로 나가고 센티널에 출처가 남는다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date", lambda **k: {"rc": 0, "revision": "1053"})

    res = js.ensure_source_checkout(
        build_root=tmp_path / "build_113", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["ok"] is True
    assert res["revision"] == "1053" and res["revision_source"] == "svn_date"
    assert svn_calls[0]["revision"] == "1053"     # HEAD가 아니라 그 빌드의 revision
    sentinel = (tmp_path / "build_113" / "source" / ".source_complete").read_text(encoding="utf-8")
    assert "revision=1053" in sentinel and "revision_source=svn_date" in sentinel
    assert js.source_snapshot_is_pinned(tmp_path / "build_113" / "source") is True


def test_without_pin_flag_behaviour_is_unchanged(tmp_path, monkeypatch):
    """기본값(pin_revision=False)은 종전대로 HEAD — 기존 호출자 회귀 없음."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: (_ for _ in ()).throw(AssertionError("고정 요청이 없으면 svn info 금지")))

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"),
    )
    assert svn_calls[0]["revision"] == ""          # HEAD
    assert res["revision_source"] == "head"


def test_pin_failure_falls_back_to_head_and_reports(tmp_path, monkeypatch):
    """revision 해석 실패는 체크아웃을 죽이지 않되 head + pin_error로 정직 보고."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: {"rc": 1, "revision": "", "output": "svn: E170013 no connect"})

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["ok"] is True and svn_calls[0]["revision"] == ""
    assert res["revision_source"] == "head" and "E170013" in res["pin_error"]
    assert js.source_snapshot_is_pinned(tmp_path / "b" / "source") is False


def test_unpinned_cached_snapshot_is_rechecked_out_when_pinning(tmp_path, monkeypatch):
    """이미 캐시됐어도 HEAD 트리면 재수집한다 — 이 판정이 없으면 고정 토글이 무력화된다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date", lambda **k: {"rc": 0, "revision": "1053"})

    src = tmp_path / "b" / "source"
    _write_sentinel(src, "scm=svn\nrevision=\nbranch=master\n")     # 구 HEAD 스냅샷
    (src / "stale.c").write_text("old", encoding="utf-8")

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["scm"] == "svn" and res["revision"] == "1053"        # 'cached' 반환이 아님
    assert len(svn_calls) == 1
    assert res["repin"] == {"applied": True, "previous_kept": False}
    assert res["path"] == str(src)                                  # 스테이징이 아니라 최종 경로
    assert not (src / "stale.c").exists()                           # 이전 트리는 교체됨
    assert js.source_snapshot_is_pinned(src) is True
    # 스테이징·백업 잔여물이 남으면 다음 sync의 rglob·지문 계산을 오염시킨다
    assert not (tmp_path / "b" / js.STAGING_DIR_NAME).exists()
    assert not (tmp_path / "b" / js.BACKUP_DIR_NAME).exists()


def test_repin_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    """⚠ 재수집 체크아웃이 실패해도 기존 스냅샷은 살아 있어야 한다.

    선삭제하면 그 빌드는 소스를 통째로 잃어 `has_source=False`가 되고 매트릭스에서 **행이
    사라진다** — 틀린 트리보다 나쁜 상태다(재수집 30건 중 1건만 실패해도 발생).
    """
    from backend.services import jenkins_service as js

    monkeypatch.setattr("backend.services.scm_registry.resolve_scm_credentials",
                        lambda **k: ("u", "p", _Entry()))
    monkeypatch.setattr(js, "svn_revision_at_date", lambda **k: {"rc": 0, "revision": "1053"})
    monkeypatch.setattr(js, "run_svn",
                        lambda **kw: {"rc": 1, "output": "svn: E170013 unable to connect"})

    src = tmp_path / "b" / "source"
    _write_sentinel(src, "scm=svn\nrevision=\nbranch=master\n")
    (src / "keep.c").write_text("original", encoding="utf-8")

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["ok"] is False                                   # 실패는 정직하게 보고
    assert res["repin"] == {"applied": False, "previous_kept": True,
                            "reason": "checkout_failed"}
    # 핵심 단언 — 기존 트리와 센티널이 그대로다
    assert (src / "keep.c").read_text(encoding="utf-8") == "original"
    assert js._source_is_complete(src) is True
    assert not (tmp_path / "b" / js.STAGING_DIR_NAME).exists()


def test_repin_staging_does_not_pollute_source_dir(tmp_path, monkeypatch):
    """스테이징 체크아웃은 source/ 가 아니라 형제 디렉터리로 나가야 한다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date", lambda **k: {"rc": 0, "revision": "1053"})
    _write_sentinel(tmp_path / "b" / "source", "scm=svn\nrevision=\nbranch=master\n")

    js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    # workdir_rel이 "source"로 하드코딩돼 있으면 스테이징이 실제 트리를 덮어쓴다
    assert svn_calls[0]["workdir_rel"] == js.STAGING_DIR_NAME


def test_force_still_deletes_first(tmp_path, monkeypatch):
    """force(사용자 명시 재수집)는 종전대로 선삭제 — 비파괴 경로는 repin 전용이다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    src = tmp_path / "b" / "source"
    _write_sentinel(src, "scm=svn\nrevision=1053\nbranch=master\nrevision_source=console\n")
    (src / "gone.c").write_text("x", encoding="utf-8")

    js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113", force=True,
    )
    assert svn_calls[0]["workdir_rel"] == "source"
    assert not (src / "gone.c").exists()


# ── 콘솔 로그 우선 ───────────────────────────────────────────────────────


def test_console_revision_wins_over_svn_date(tmp_path, monkeypatch):
    """콘솔 로그가 있으면 그 값을 쓴다 — 사실이고, 네트워크가 필요 없다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: (_ for _ in ()).throw(AssertionError("콘솔이 있으면 svn info 금지")))
    build_root = tmp_path / "build_113"
    build_root.mkdir(parents=True, exist_ok=True)
    (build_root / "jenkins_console.log").write_text(
        f"Updating {_Entry.scm_url} at revision '2026-05-27T13:00:09.163 +0900'\n"
        "At revision 1042\n", encoding="utf-8")

    res = js.ensure_source_checkout(
        build_root=build_root, client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["revision"] == "1042" and res["revision_source"] == "console"
    assert svn_calls[0]["revision"] == "1042"


def test_falls_back_to_svn_date_when_console_truncated(tmp_path, monkeypatch):
    """로그가 상한에 걸려 SCM 구간이 잘린 빌드(실측 #105·#107)는 날짜-revision으로."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date", lambda **k: {"rc": 0, "revision": "1036"})
    build_root = tmp_path / "build_107"
    build_root.mkdir(parents=True, exist_ok=True)
    (build_root / "jenkins_console.log").write_text("[Pipeline] End\nFinished: SUCCESS\n",
                                                    encoding="utf-8")

    res = js.ensure_source_checkout(
        build_root=build_root, client=_Client(), build_selector="107",
        build_timestamp_ms=_ms("2026-05-15T05:21:44Z"), pin_revision=True,
    )
    assert res["revision"] == "1036" and res["revision_source"] == "svn_date"


def test_both_sources_failing_reports_both_reasons(tmp_path, monkeypatch):
    """둘 다 실패하면 두 사유를 합쳐 보고한다 — 어느 쪽이 왜 안 됐는지 알 수 있어야 한다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: {"rc": 1, "revision": "", "output": "E170013 no connect"})

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["revision_source"] == "head"
    assert "console_log_missing" in res["pin_error"] and "E170013" in res["pin_error"]


def test_already_pinned_snapshot_is_reused(tmp_path, monkeypatch):
    """고정된 스냅샷은 재체크아웃하지 않는다 — 재수집이 무한 반복되면 안 된다."""
    from backend.services import jenkins_service as js

    svn_calls = []
    _patch_common(monkeypatch, js, svn_calls)

    src = tmp_path / "b" / "source"
    _write_sentinel(src, "scm=svn\nrevision=1053\nbranch=master\nrevision_source=svn_date\n")

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["scm"] == "cached" and svn_calls == []
    assert res["pinned"] is True and res["revision"] == "1053"


def test_git_scm_is_not_pinned_by_svn_date(tmp_path, monkeypatch):
    """svn 전용 경로 — git 잡에서 svn info를 부르면 안 된다."""
    from backend.services import jenkins_service as js

    calls = []
    monkeypatch.setattr("backend.services.scm_registry.resolve_scm_credentials",
                        lambda **k: ("u", "p", None))
    monkeypatch.setattr(js, "run_git", lambda **kw: (calls.append(kw), {"rc": 0, "output": ""})[1])
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: (_ for _ in ()).throw(AssertionError("git 잡에 svn info 금지")))

    res = js.ensure_source_checkout(
        build_root=tmp_path / "b", client=_Client(), build_selector="113",
        build_timestamp_ms=_ms("2026-05-27T04:00:09Z"), pin_revision=True,
    )
    assert res["ok"] is True and calls and res["revision_source"] == "jenkins"


# ── 인벤토리 표면화 ──────────────────────────────────────────────────────


def test_inventory_exposes_source_pinned(tmp_path, monkeypatch):
    from backend.services import build_inventory as bi

    build_root = tmp_path / "build_113"
    reports = build_root / "report"
    reports.mkdir(parents=True, exist_ok=True)
    _write_sentinel(build_root / "source", "scm=svn\nrevision=\nbranch=master\n")
    monkeypatch.setattr(bi, "list_cached_builds", lambda **k: [
        {"build_number": 113, "build_root": str(build_root), "reports_dir": str(reports)},
    ])
    monkeypatch.setattr(bi, "find_latest_rcr_html", lambda *a, **k: None)

    row = bi.list_cached_builds_meta(job_url="http://j/job/X", cache_root=tmp_path)[0]
    assert row["has_source"] is True          # 스냅샷은 있다
    assert row["source_pinned"] is False      # 다만 그 빌드 시점 트리가 아니다
    assert row["source_revision_source"] is None

    _write_sentinel(build_root / "source",
                    "scm=svn\nrevision=1053\nbranch=master\nrevision_source=svn_date\n")
    row2 = bi.list_cached_builds_meta(job_url="http://j/job/X", cache_root=tmp_path)[0]
    assert row2["source_pinned"] is True and row2["source_revision_source"] == "svn_date"
    assert row2["revision"] == "1053"
