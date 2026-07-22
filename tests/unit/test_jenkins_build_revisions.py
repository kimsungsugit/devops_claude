"""빌드별 SVN revision 해석.

git 파이프라인 잡(예: KJPDS02_PV)은 Jenkins에 소스 SVN revision을 구조화로 노출하지 않고,
소스를 '빌드 시각 기준'으로 svn checkout 한다. 그래서 per-build revision은 빌드 timestamp를
SVN 날짜-revision으로 되찾아야 한다. 아래는 그 헬퍼·일괄 매핑·영향분석 date-resolution 검증
(subprocess/live svn 미접촉 — 전부 monkeypatch).
"""
from __future__ import annotations

import datetime as dt
import types


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


# ── local_service.svn_revision_at_date ───────────────────────────────────
def test_svn_revision_at_date_rejects_non_iso():
    from backend.services import local_service as ls
    r = ls.svn_revision_at_date(repo_url="svn://x/ADOS", when_iso="2026-06-25")  # T/Z 없음
    assert r["rc"] == 1 and r["revision"] == ""


def test_svn_revision_at_date_parses_revision_and_root(monkeypatch):
    from backend.services import local_service as ls
    out = ("Path: NE1AW_PORTING\nURL: svn://x/ADOS/NE1AW_PORTING\n"
           "Repository Root: svn://x/ADOS\nRevision: 1053\n")
    monkeypatch.setattr(ls, "_sanitize_password", lambda p: ("", None))
    monkeypatch.setattr(ls, "_run_cmd", lambda *a, **k: (0, out))
    r = ls.svn_revision_at_date(repo_url="svn://x/ADOS/NE1AW_PORTING", when_iso="2026-06-25T04:00:15Z")
    assert r["revision"] == "1053"
    assert r["repo_root"] == "svn://x/ADOS"


def test_svn_revision_at_date_non_numeric_is_blank(monkeypatch):
    from backend.services import local_service as ls
    monkeypatch.setattr(ls, "_sanitize_password", lambda p: ("", None))
    monkeypatch.setattr(ls, "_run_cmd", lambda *a, **k: (0, "Revision: HEAD\n"))
    r = ls.svn_revision_at_date(repo_url="svn://x/ADOS", when_iso="2026-06-25T04:00:15Z")
    assert r["revision"] == ""


# ── local_service.svn_date_revision_map ──────────────────────────────────
def test_svn_date_revision_map_parses_xml(monkeypatch):
    from backend.services import local_service as ls
    xml = (
        '<?xml version="1.0"?><log>'
        '<logentry revision="1052"><date>2026-06-24T04:00:00.000000Z</date></logentry>'
        '<logentry revision="1053"><date>2026-06-25T04:00:00.000000Z</date></logentry>'
        '</log>'
    )
    monkeypatch.setattr(ls, "_sanitize_password", lambda p: ("", None))
    monkeypatch.setattr(ls, "_run_cmd", lambda *a, **k: (0, xml))
    r = ls.svn_date_revision_map(
        repo_url="svn://x/ADOS", date_from_iso="2026-06-24T00:00:00Z", date_to_iso="2026-06-26T00:00:00Z")
    assert r["rc"] == 0
    assert r["entries"] == [
        ("2026-06-24T04:00:00.000000Z", 1052),
        ("2026-06-25T04:00:00.000000Z", 1053),
    ]


def test_svn_date_revision_map_rejects_non_iso():
    from backend.services import local_service as ls
    r = ls.svn_date_revision_map(repo_url="svn://x", date_from_iso="bad", date_to_iso="2026-06-26T00:00:00Z")
    assert r["rc"] == 1 and r["entries"] == []


# ── jenkins_service.map_builds_to_svn_revisions (bisect: youngest rev ≤ date) ──
def _patch_map(monkeypatch, floor_rev, entries, repo_root="svn://x/ADOS"):
    from backend.services import jenkins_service as js
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: {"rc": 0, "revision": str(floor_rev), "repo_root": repo_root})
    monkeypatch.setattr(js, "svn_date_revision_map", lambda **k: {"rc": 0, "entries": entries})
    return js


def test_map_builds_bisect_youngest_le_date(monkeypatch):
    entries = [
        ("2026-06-24T04:00:00Z", 1052),
        ("2026-06-25T04:00:00Z", 1053),
        ("2026-07-17T04:00:00Z", 1070),
    ]
    js = _patch_map(monkeypatch, 1048, entries)
    builds = [
        {"number": 117, "timestamp": _ms("2026-06-16T04:00:14Z")},  # 모든 엔트리보다 이전 → floor 1048
        {"number": 122, "timestamp": _ms("2026-06-25T04:00:15Z")},  # r1053 이후 → 1053
        {"number": 123, "timestamp": _ms("2026-07-17T04:00:12Z")},  # r1070 이후 → 1070
    ]
    res = js.map_builds_to_svn_revisions(repo_url="svn://x/ADOS/NE1AW_PORTING", builds=builds)
    assert res["ok"] is True and res["resolved"] == 3
    assert {b["number"]: b["revision"] for b in builds} == {117: "1048", 122: "1053", 123: "1070"}


def test_map_builds_logs_repo_root_not_project_path(monkeypatch):
    """다중 프로젝트 저장소 함정: 로그 대상은 프로젝트 경로가 아니라 anchor의 repo_root."""
    from backend.services import jenkins_service as js
    captured = {}
    monkeypatch.setattr(js, "svn_revision_at_date",
                        lambda **k: {"rc": 0, "revision": "1048", "repo_root": "svn://x/ADOS"})

    def _fake_map(**k):
        captured["repo_url"] = k.get("repo_url")
        return {"rc": 0, "entries": [("2026-06-25T04:00:00Z", 1053)]}

    monkeypatch.setattr(js, "svn_date_revision_map", _fake_map)
    builds = [{"number": 1, "timestamp": _ms("2026-06-16T04:00:00Z")},
              {"number": 2, "timestamp": _ms("2026-06-25T04:00:15Z")}]
    js.map_builds_to_svn_revisions(repo_url="svn://x/ADOS/NE1AW_PORTING", builds=builds)
    assert captured["repo_url"] == "svn://x/ADOS"  # 프로젝트 경로 아님


def test_map_builds_fail_soft_no_timestamps():
    from backend.services import jenkins_service as js
    res = js.map_builds_to_svn_revisions(repo_url="svn://x/ADOS", builds=[{"number": 1}])
    assert res["ok"] is False and res["resolved"] == 0


def test_map_builds_fail_soft_svn_down(monkeypatch):
    from backend.services import jenkins_service as js
    monkeypatch.setattr(js, "svn_revision_at_date", lambda **k: {"rc": 1, "revision": "", "repo_root": ""})
    monkeypatch.setattr(js, "svn_date_revision_map", lambda **k: {"rc": 1, "entries": []})
    builds = [{"number": 1, "timestamp": _ms("2026-06-25T04:00:15Z")}]
    res = js.map_builds_to_svn_revisions(repo_url="svn://x/ADOS", builds=builds)
    assert res["ok"] is False
    assert "revision" not in builds[0]  # 실패 시 미부착(목록은 그대로)


# ── jenkins._try_svn_revision_range: build_ts → date-revision (HEAD 폴백 라벨) ──
def _entry(**kw):
    d = {"scm_type": "svn", "scm_url": "svn://x/ADOS/NE1AW_PORTING",
         "source_root": "C:/export/NE1AW", "base_ref": "1018"}
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_try_svn_revision_range_resolves_by_timestamp(monkeypatch):
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest
    from backend.services import local_service as ls
    from backend.services import scm_registry
    monkeypatch.setattr(scm_registry, "get_registry_entry", lambda scm_id: _entry())
    monkeypatch.setattr(scm_registry, "resolve_scm_credentials", lambda **k: ("u", "p", None))
    monkeypatch.setattr(ls, "svn_revision_at_date",
                        lambda **k: {"rc": 0, "revision": "1053", "repo_root": "svn://x/ADOS"})
    monkeypatch.setattr(ls, "svn_diff_summarize",
                        lambda **k: {"rc": 0, "files": ["a.c"], "edit_types": {"a.c": "edit"}})
    req = JenkinsImpactTriggerRequest(scm_id="kjpds02_pv", build_number=122, job_url="http://j/job/X")
    out = jr._try_svn_revision_range(req, "deadbeefsha", build_ts=1782360015971)
    assert out is not None
    _files, _use_only, meta = out
    assert meta["build_revision"] == "1053"       # git SHA 아닌, 빌드 시각 기준 실제 revision
    assert meta["baseline_revision"] == "1018"
    assert meta["build_revision_is_head"] is False


def test_try_svn_revision_range_head_fallback_labeled(monkeypatch):
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest
    from backend.services import local_service as ls
    from backend.services import scm_registry
    monkeypatch.setattr(scm_registry, "get_registry_entry", lambda scm_id: _entry())
    monkeypatch.setattr(scm_registry, "resolve_scm_credentials", lambda **k: ("u", "p", None))
    # timestamp 없음 → date-resolution 불가 → svn HEAD 폴백 + 라벨.
    monkeypatch.setattr(ls, "svn_info_url",
                        lambda **k: {"rc": 0, "revision": "1077", "repo_root": "svn://x/ADOS"})
    monkeypatch.setattr(ls, "svn_diff_summarize", lambda **k: {"rc": 0, "files": [], "edit_types": {}})
    req = JenkinsImpactTriggerRequest(scm_id="kjpds02_pv", build_number=122, job_url="http://j/job/X")
    out = jr._try_svn_revision_range(req, "deadbeefsha", build_ts=None)
    assert out is not None
    _files, _use_only, meta = out
    assert meta["build_revision"] == "1077"
    assert meta["build_revision_is_head"] is True  # 침묵 아닌 명시 라벨
