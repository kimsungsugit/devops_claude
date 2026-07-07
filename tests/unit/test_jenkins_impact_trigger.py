from __future__ import annotations


def test_jenkins_impact_trigger_returns_registry_trigger(monkeypatch):
    from backend.routers.jenkins import jenkins_impact_trigger
    from backend.schemas import JenkinsImpactTriggerRequest

    class _FakeTrigger:
        def to_dict(self):
            return {
                "trigger_type": "jenkins",
                "scm_id": "hdpdm01",
                "changed_files": ["a.c"],
                "metadata": {"build_number": 42},
            }

    monkeypatch.setattr("backend.routers.jenkins.build_registry_trigger", lambda **_kwargs: _FakeTrigger())
    monkeypatch.setattr("backend.routers.jenkins.run_impact_update", lambda trigger: {"ok": True, "trigger": trigger.to_dict(), "actions": {"sts": {"mode": "FLAG"}}})

    result = jenkins_impact_trigger(
        JenkinsImpactTriggerRequest(
            scm_id="hdpdm01",
            build_number=42,
            job_url="http://jenkins/job/HDPDM01",
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert result["trigger"]["scm_id"] == "hdpdm01"
    assert result["actions"]["sts"]["mode"] == "FLAG"


def test_jenkins_impact_trigger_async_returns_job(monkeypatch):
    from backend.routers.jenkins import jenkins_impact_trigger_async
    from backend.schemas import JenkinsImpactTriggerRequest

    class _FakeTrigger:
        trigger_type = "jenkins"
        scm_id = "hdpdm01"
        dry_run = True
        targets = ["sts"]
        source_root = "D:/src"
        base_ref = ""

    monkeypatch.setattr("backend.routers.jenkins.build_registry_trigger", lambda **_kwargs: _FakeTrigger())
    monkeypatch.setattr(
        "backend.routers.jenkins.start_impact_job",
        lambda trigger: {"ok": True, "job_id": "impact_2", "status": "queued", "job": {"job_id": "impact_2"}},
    )

    result = jenkins_impact_trigger_async(
        JenkinsImpactTriggerRequest(
            scm_id="hdpdm01",
            build_number=42,
            job_url="http://jenkins/job/HDPDM01",
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert result["job_id"] == "impact_2"


def test_get_build_changed_files_parses_changeset(monkeypatch):
    from backend.services import jenkins_service

    fixture = {
        "changeSet": {"items": [
            {"affectedPaths": ["Sources/APP/Ap_Door.c", "docs/readme.md"], "commitId": "abc123"},
            {"paths": [{"file": "Sources/APP/Ap_Door.h"}], "commitId": "def456"},
        ]},
        "actions": [{"lastBuiltRevision": {"SHA1": "deadbeef"}}],
    }
    monkeypatch.setattr(jenkins_service.JenkinsClient, "_open_json", lambda self, url: fixture)

    out = jenkins_service.get_build_changed_files(
        job_url="http://jenkins/job/HDPDM01", build_number=42, username="u", api_token="t", verify_tls=True,
    )
    # .c/.h 만 (docs/readme.md 제외), 정렬
    assert out["files"] == ["Sources/APP/Ap_Door.c", "Sources/APP/Ap_Door.h"]
    assert out["revision"] == "deadbeef"   # lastBuiltRevision이 commitId보다 우선
    assert out["all_count"] == 3


def test_get_build_changed_files_extracts_edit_types(monkeypatch):
    """paths[].editType(add/edit/delete)를 .c/.h에 한해 edit_types로 수집한다."""
    from backend.services import jenkins_service

    fixture = {
        "changeSet": {"items": [
            {"paths": [
                {"file": "Sources/APP/Ap_New.c", "editType": "add"},
                {"file": "Sources/APP/Ap_Old.c", "editType": "delete"},
                {"file": "Sources/APP/Ap_Edit.c", "editType": "edit"},
                {"file": "docs/readme.md", "editType": "edit"},   # 비-소스 제외
            ], "commitId": "c1"},
        ]},
        "actions": [{"lastBuiltRevision": {"SHA1": "rev9"}}],
    }
    monkeypatch.setattr(jenkins_service.JenkinsClient, "_open_json", lambda self, url: fixture)

    out = jenkins_service.get_build_changed_files(
        job_url="http://jenkins/job/X", build_number=7, username="u", api_token="t", verify_tls=True,
    )
    assert out["edit_types"] == {
        "Sources/APP/Ap_New.c": "add",
        "Sources/APP/Ap_Old.c": "delete",
        "Sources/APP/Ap_Edit.c": "edit",
    }
    assert "docs/readme.md" not in out["edit_types"]
    assert out["files"] == ["Sources/APP/Ap_Edit.c", "Sources/APP/Ap_New.c", "Sources/APP/Ap_Old.c"]


def test_get_build_changed_files_edit_types_empty_when_only_affected_paths(monkeypatch):
    """affectedPaths만 있으면(editType 부재) edit_types는 비어 있고, 다운스트림이 확장자 기반 처리."""
    from backend.services import jenkins_service

    fixture = {"changeSet": {"items": [{"affectedPaths": ["Sources/APP/Ap_X.c"], "commitId": "c1"}]}}
    monkeypatch.setattr(jenkins_service.JenkinsClient, "_open_json", lambda self, url: fixture)
    out = jenkins_service.get_build_changed_files(
        job_url="http://jenkins/job/X", build_number=7, username="u", api_token="t",
    )
    assert out["edit_types"] == {}
    assert out["files"] == ["Sources/APP/Ap_X.c"]


def test_resolve_jenkins_changed_files_propagates_edit_types(monkeypatch):
    """get_build_changed_files의 edit_types가 trigger metadata로 전파된다(비어 있으면 생략)."""
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config",
                        lambda: {"username": "u", "token": "t", "baseUrl": "http://j", "verifyTls": True})
    monkeypatch.setattr(jsvc, "get_build_changed_files", lambda **k: {
        "files": ["a.c"], "revision": "r", "all_count": 1, "edit_types": {"a.c": "add"}})

    _f, _u, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"))
    assert meta["changed_file_edit_types"] == {"a.c": "add"}

    # 빈 edit_types → 키 생략
    monkeypatch.setattr(jsvc, "get_build_changed_files", lambda **k: {
        "files": ["a.c"], "revision": "r", "all_count": 1, "edit_types": {}})
    _f2, _u2, meta2 = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"))
    assert "changed_file_edit_types" not in meta2


def test_resolve_jenkins_changed_files_injects_build_changeset(monkeypatch):
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config", lambda: {"username": "u", "token": "t", "baseUrl": "http://j", "verifyTls": True})
    monkeypatch.setattr(jsvc, "get_build_changed_files", lambda **k: {"files": ["a.c", "b.h"], "revision": "rev1", "all_count": 2})

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X")
    )
    assert files == ["a.c", "b.h"]
    assert use_only is True
    assert meta["changed_files_source"] == "jenkins_changeset"
    assert meta["build_revision"] == "rev1"
    assert meta["jenkins_changed_file_count"] == 2


def test_resolve_jenkins_changed_files_fallback_without_credentials(monkeypatch):
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config", lambda: {"username": "", "token": "", "verifyTls": True})
    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X")
    )
    assert files is None
    assert use_only is False
    assert meta["changed_files_source"] == "local_diff_fallback"


def test_resolve_jenkins_changed_files_rejects_foreign_job_url(monkeypatch):
    """SSRF 방지: job_url이 설정된 baseUrl 하위가 아니면 서버 토큰을 안 보내고 fallback."""
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config",
                        lambda: {"username": "u", "token": "t", "baseUrl": "http://jenkins.local", "verifyTls": True})

    def _boom(**_k):
        raise AssertionError("get_build_changed_files must NOT be called for foreign job_url")

    monkeypatch.setattr(jsvc, "get_build_changed_files", _boom)

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://evil.example/job/X")
    )
    assert files is None
    assert use_only is False
    assert "baseUrl" in meta["linkage_reason"]


def test_resolve_jenkins_changed_files_fallback_without_build(monkeypatch):
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x")  # build_number=0, job_url=""
    )
    assert files is None
    assert use_only is False
    assert meta["changed_files_source"] == "local_diff_fallback"
    assert "no build_number/job_url" in meta["linkage_reason"]


# ── svn revision-range (현재 로컬 default 버전 A ↔ 새 빌드 버전 B) ─────────────

class _FakeSvnEntry:
    """resolve/entry용 최소 엔트리 — svn_revision_range 경로 테스트."""
    def __init__(self, *, scm_type="svn", scm_url="https://svn.example/repo/trunk",
                 source_root="D:/wc", entry_id="hdpdm01"):
        self.scm_type = scm_type
        self.scm_url = scm_url
        self.source_root = source_root
        self.id = entry_id


def _patch_svn_range(monkeypatch, *, entry, info_rev, repo_root="https://svn.example/repo",
                     diff=None, diff_boom=False):
    import backend.services.scm_registry as reg
    import backend.services.local_service as ls
    monkeypatch.setattr(reg, "get_registry_entry", lambda _sid: entry)
    monkeypatch.setattr(reg, "resolve_scm_credentials", lambda **_k: ("u", "p", None))
    monkeypatch.setattr(ls, "svn_info_url", lambda **_k: {
        "rc": 0 if info_rev else 1, "revision": info_rev,
        "url": (repo_root + "/trunk") if repo_root else "", "repo_root": repo_root})
    if diff_boom:
        def _boom(**_k):
            raise AssertionError("svn_diff_summarize must not be called")
        monkeypatch.setattr(ls, "svn_diff_summarize", _boom)
    elif diff is not None:
        monkeypatch.setattr(ls, "svn_diff_summarize", lambda **_k: diff)


def test_try_svn_revision_range_success(monkeypatch):
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(
        monkeypatch, entry=_FakeSvnEntry(), info_rev="100",
        diff={"rc": 0, "files": ["APP/a.c"], "edit_types": {"APP/a.c": "edit"}},
    )
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="hdpdm01", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is not None
    files, use_only, meta = out
    assert files == ["APP/a.c"]
    assert use_only is True
    assert meta["changed_files_source"] == "svn_revision_range"
    assert meta["baseline_revision"] == "100"
    assert meta["build_revision"] == "150"
    assert meta["changed_file_edit_types"] == {"APP/a.c": "edit"}
    assert "svn diff" in meta["linkage_reason"]


def test_try_svn_revision_range_no_change_when_equal(monkeypatch):
    """로컬 작업본 revision == 빌드 revision → 변경 0건(확인됨), diff 미호출."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(monkeypatch, entry=_FakeSvnEntry(), info_rev="150", diff_boom=True)
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="hdpdm01", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is not None
    files, use_only, meta = out
    assert files == []
    assert use_only is True
    assert meta["changed_files_source"] == "svn_revision_range"
    assert meta["baseline_revision"] == "150"
    assert "no changes" in meta["linkage_reason"]


def test_try_svn_revision_range_git_returns_none(monkeypatch):
    """git 엔트리는 revision-range 대상 아님 → None(changeSet 폴백)."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(monkeypatch, entry=_FakeSvnEntry(scm_type="git"), info_rev="100")
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is None


def test_try_svn_revision_range_svn_info_fail_returns_none(monkeypatch):
    """source_root가 작업본 아님/svn info 실패 → None(changeSet 폴백)."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(monkeypatch, entry=_FakeSvnEntry(), info_rev="")
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is None


def test_try_svn_revision_range_unknown_scm_returns_none():
    """registry에 없는 scm_id면 build_rev 형태와 무관하게 None(entry 없음 → svn 대상 아님)."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    req = JenkinsImpactTriggerRequest(scm_id="__nope__", build_number=5, job_url="http://j/job/X")
    assert jr._try_svn_revision_range(req, build_rev="deadbeef") is None
    assert jr._try_svn_revision_range(req, build_rev="") is None


def test_try_svn_revision_range_git_buildrev_uses_svn_head(monkeypatch):
    """Jenkins 빌드가 git으로 체크아웃해 build_rev이 git SHA(비정수)면 svn HEAD를 B로 쓴다.

    KJPDS02_PV 시나리오: 소스=svn, 빌드=git → build_revision이 git SHA40. base_ref=1018(A)와
    svn HEAD(B)로 diff.
    """
    from backend.routers import jenkins as jr
    import backend.services.scm_registry as reg
    import backend.services.local_service as ls
    from backend.schemas import JenkinsImpactTriggerRequest

    entry = _FakeSvnEntry(scm_url="svn://host/ADOS/NE1AW_PORTING",
                          source_root="C:/Project/Ados/NE1AW_PORTING")
    monkeypatch.setattr(reg, "get_registry_entry", lambda _sid: entry)
    monkeypatch.setattr(reg, "resolve_scm_credentials", lambda **_k: ("u", "p", None))
    # svn info(repo_url) → HEAD 1053 (build_rev이 비정수일 때 B로 대체)
    monkeypatch.setattr(ls, "svn_info_url", lambda **_k: {
        "rc": 0, "revision": "1053", "url": "svn://host/ADOS/NE1AW_PORTING", "repo_root": "svn://host/ADOS"})
    seen = {}

    def _fake_diff(*, repo_url, rev_a, rev_b, **_k):
        seen["a"], seen["b"] = rev_a, rev_b
        return {"rc": 0, "files": ["APP/a.c"], "edit_types": {"APP/a.c": "edit"}}

    monkeypatch.setattr(ls, "svn_diff_summarize", _fake_diff)
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="kjpds02_pv", build_number=76,
                                    job_url="http://j/job/X", base_ref="1018"),
        build_rev="667a3cf2d8370b88bdcf2a56330b59d6484ef1bd",  # git SHA40 (비정수)
    )
    assert out is not None
    _files, _use, meta = out
    assert meta["baseline_revision"] == "1018"    # base_ref (A)
    assert meta["build_revision"] == "1053"        # svn HEAD로 대체 (B, git SHA 아님)
    assert seen["a"] == "1018" and seen["b"] == "1053"


def test_try_svn_revision_range_uses_numeric_base_ref(monkeypatch):
    """source_root가 export(작업본 아님)여도 base_ref에 정수 revision이 있으면 그걸 A로 쓴다.

    KJPDS02_PV 시나리오: NE1AW_PORTING이 svn export라 svn info 불가 → base_ref=1018(커밋
    메시지 ver 0.05.17)을 baseline으로 명시.
    """
    from backend.routers import jenkins as jr
    import backend.services.scm_registry as reg
    import backend.services.local_service as ls
    from backend.schemas import JenkinsImpactTriggerRequest

    entry = _FakeSvnEntry(scm_url="svn://host/ADOS/NE1AW_PORTING",
                          source_root="C:/Project/Ados/NE1AW_PORTING")  # export
    monkeypatch.setattr(reg, "get_registry_entry", lambda _sid: entry)
    monkeypatch.setattr(reg, "resolve_scm_credentials", lambda **_k: ("u", "p", None))

    def _boom_info(**_k):
        raise AssertionError("svn_info_url must NOT be called when base_ref is numeric")

    monkeypatch.setattr(ls, "svn_info_url", _boom_info)
    seen = {}

    def _fake_diff(*, repo_url, rev_a, rev_b, **_k):
        seen["a"] = rev_a
        return {"rc": 0, "files": ["APP/a.c"], "edit_types": {"APP/a.c": "edit"}}

    monkeypatch.setattr(ls, "svn_diff_summarize", _fake_diff)
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="kjpds02_pv", build_number=5, job_url="http://j/job/X", base_ref="1018"),
        build_rev="1050",
    )
    assert out is not None
    _files, _use, meta = out
    assert meta["baseline_revision"] == "1018"   # base_ref 우선(작업본 svn info 안 탐)
    assert seen["a"] == "1018"


def test_try_svn_revision_range_multipath_picks_matching_wc(monkeypatch):
    """멀티패스 source_root(app,boot)에서 scm_url(app=NE1AW)과 같은 repo인 작업본 rev를 A로 쓴다."""
    from backend.routers import jenkins as jr
    import backend.services.scm_registry as reg
    import backend.services.local_service as ls
    from backend.schemas import JenkinsImpactTriggerRequest

    entry = _FakeSvnEntry(
        scm_url="svn://host/ADOS/NE1AW_PORTING",
        source_root="C:/Project/Ados/NE1AW_PORTING,C:/Project/Ados/PDS128_FBL",
    )
    monkeypatch.setattr(reg, "get_registry_entry", lambda _sid: entry)
    monkeypatch.setattr(reg, "resolve_scm_credentials", lambda **_k: ("u", "p", None))

    def _fake_info(*, repo_url, **_k):
        if "NE1AW" in repo_url:
            return {"rc": 0, "revision": "100", "url": "svn://host/ADOS/NE1AW_PORTING", "repo_root": "svn://host/ADOS"}
        if "PDS128" in repo_url:
            return {"rc": 0, "revision": "90", "url": "svn://host/ADOS/PDS128_FBL", "repo_root": "svn://host/ADOS"}
        return {"rc": 1, "revision": "", "url": "", "repo_root": ""}

    monkeypatch.setattr(ls, "svn_info_url", _fake_info)
    seen = {}

    def _fake_diff(*, repo_url, rev_a, rev_b, **_k):
        seen["a"] = rev_a
        seen["url"] = repo_url
        return {"rc": 0, "files": ["APP/a.c"], "edit_types": {"APP/a.c": "edit"}}

    monkeypatch.setattr(ls, "svn_diff_summarize", _fake_diff)
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="kjpds02_pv", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is not None
    _files, _use, meta = out
    assert meta["baseline_revision"] == "100"   # app(NE1AW) 작업본 rev (boot 90 아님)
    assert seen["a"] == "100"                     # diff가 A=100로 실행
    assert "NE1AW" in seen["url"]                 # scm_url(app)로 diff (boot 제외)
    assert _files == ["APP/a.c"]


def test_try_svn_revision_range_repo_mismatch_returns_none(monkeypatch):
    """작업본 repo-root가 scm_url과 다른 리포지토리면 A:B 비교 무의미 → None(silent-wrong 차단)."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(
        monkeypatch,
        entry=_FakeSvnEntry(scm_url="https://svn.example/repoB/trunk"),
        info_rev="100",
        repo_root="https://svn.example/repoA",   # 작업본은 repoA, diff 대상은 repoB
    )
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is None


def test_try_svn_revision_range_diff_failure_returns_none(monkeypatch):
    """svn diff rc!=0 → None(changeSet 폴백)."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(
        monkeypatch, entry=_FakeSvnEntry(), info_rev="100",
        diff={"rc": 1, "files": [], "edit_types": {}, "output": "svn: E170013"},
    )
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is None


def test_resolve_jenkins_changed_files_uses_svn_revision_range(monkeypatch):
    """전체 _resolve 경로: svn A:B 결과가 단일 빌드 changeSet을 대체한다."""
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config",
                        lambda: {"username": "u", "token": "t", "baseUrl": "http://j", "verifyTls": True})
    # 단일 빌드 changeSet은 'prev.c'만 보이지만(직전 빌드 대비), svn A:B가 전체 델타를 잡는다.
    monkeypatch.setattr(jsvc, "get_build_changed_files", lambda **_k: {
        "files": ["prev.c"], "revision": "150", "all_count": 1, "edit_types": {"prev.c": "edit"}})
    _patch_svn_range(
        monkeypatch, entry=_FakeSvnEntry(), info_rev="100",
        diff={"rc": 0, "files": ["APP/a.c", "APP/b.h"],
              "edit_types": {"APP/a.c": "edit", "APP/b.h": "add"}},
    )
    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="hdpdm01", build_number=5, job_url="http://j/job/X"))
    assert files == ["APP/a.c", "APP/b.h"]
    assert use_only is True
    assert meta["changed_files_source"] == "svn_revision_range"
    assert meta["baseline_revision"] == "100"
    assert meta["build_revision"] == "150"
    assert meta["changed_file_edit_types"] == {"APP/a.c": "edit", "APP/b.h": "add"}


def test_resolve_jenkins_svn_range_when_jenkins_down(monkeypatch):
    """Jenkins 조회가 실패(연결 끊김)해도 svn A:B(base_ref↔HEAD)는 독립적으로 성립한다.

    KJPDS02_PV 실장애 시나리오: Jenkins(.40) WinError 10060 → 그래도 svn(.33)로 분석.
    """
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    import backend.services.scm_registry as reg
    import backend.services.local_service as ls
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config",
                        lambda: {"username": "u", "token": "t", "baseUrl": "http://j", "verifyTls": True})

    def _boom(**_k):
        raise OSError("[WinError 10060] connection timed out")

    monkeypatch.setattr(jsvc, "get_build_changed_files", _boom)
    # svn 경로는 정상 (base_ref=1018, HEAD=1053)
    entry = _FakeSvnEntry(scm_url="svn://host/ADOS/NE1AW_PORTING", source_root="C:/wc")
    monkeypatch.setattr(reg, "get_registry_entry", lambda _sid: entry)
    monkeypatch.setattr(reg, "resolve_scm_credentials", lambda **_k: ("u", "p", None))
    monkeypatch.setattr(ls, "svn_info_url", lambda **_k: {
        "rc": 0, "revision": "1053", "url": "svn://host/ADOS/NE1AW_PORTING", "repo_root": "svn://host/ADOS"})
    monkeypatch.setattr(ls, "svn_diff_summarize", lambda **_k: {
        "rc": 0, "files": ["APP/a.c"], "edit_types": {"APP/a.c": "edit"}})

    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="kjpds02_pv", build_number=76,
                                    job_url="http://j/job/KJPDS02_PV/", base_ref="1018"))
    assert meta["changed_files_source"] == "svn_revision_range"   # Jenkins 죽어도 svn 성공
    assert meta["baseline_revision"] == "1018" and meta["build_revision"] == "1053"
    assert files == ["APP/a.c"] and use_only is True


def test_resolve_jenkins_changed_files_svn_range_falls_back_to_changeset(monkeypatch):
    """svn info 실패 시 단일 빌드 changeSet(build_revision 정수여도)로 graceful 폴백."""
    from backend.routers import jenkins as jr
    import backend.routers.config as cfgmod
    import backend.services.jenkins_service as jsvc
    from backend.schemas import JenkinsImpactTriggerRequest

    monkeypatch.setattr(cfgmod, "get_jenkins_config",
                        lambda: {"username": "u", "token": "t", "baseUrl": "http://j", "verifyTls": True})
    monkeypatch.setattr(jsvc, "get_build_changed_files", lambda **_k: {
        "files": ["a.c"], "revision": "150", "all_count": 1, "edit_types": {"a.c": "edit"}})
    # svn entry지만 source_root가 작업본 아님(svn info 실패) → changeSet 폴백
    _patch_svn_range(monkeypatch, entry=_FakeSvnEntry(), info_rev="")
    files, use_only, meta = jr._resolve_jenkins_changed_files(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"))
    assert files == ["a.c"]
    assert use_only is True
    assert meta["changed_files_source"] == "jenkins_changeset"
    assert meta["build_revision"] == "150"


def test_svn_diff_summarize_parses_status(monkeypatch):
    """svn diff --summarize 출력 파싱: M/A/D/R → edit/add/delete, .c/.h만, URL→상대경로."""
    from backend.services import local_service as ls

    base = "https://svn.example/repo/trunk"
    fake_out = "\n".join([
        f"M       {base}/APP/Ap_Door.c",
        f"A       {base}/APP/Ap_New.c",
        f"D       {base}/APP/Ap_Old.c",
        f"M       {base}/docs/readme.md",   # 비-소스 제외
        f"R       {base}/BSW/Bsw_X.h",       # 대체 → edit
    ])
    monkeypatch.setattr(ls, "_run_cmd", lambda *_a, **_k: (0, fake_out))
    out = ls.svn_diff_summarize(repo_url=base, rev_a="100", rev_b="150")
    assert out["rc"] == 0
    assert out["files"] == ["APP/Ap_Door.c", "APP/Ap_New.c", "APP/Ap_Old.c", "BSW/Bsw_X.h"]
    assert out["edit_types"] == {
        "APP/Ap_Door.c": "edit",
        "APP/Ap_New.c": "add",
        "APP/Ap_Old.c": "delete",
        "BSW/Bsw_X.h": "edit",
    }


def test_svn_diff_summarize_decodes_encoded_paths(monkeypatch):
    """비-ASCII 경로(%-인코딩, 한글 폴더)를 디코딩해 by_name 로컬 경로와 매칭되게 한다."""
    from backend.services import local_service as ls

    base = "https://svn.example/repo/trunk"
    fake_out = f"M       {base}/%ED%95%9C%EA%B8%80/App.c"  # '한글/App.c'
    monkeypatch.setattr(ls, "_run_cmd", lambda *_a, **_k: (0, fake_out))
    out = ls.svn_diff_summarize(repo_url=base, rev_a="100", rev_b="150")
    assert out["files"] == ["한글/App.c"]
    assert out["edit_types"] == {"한글/App.c": "edit"}


def test_svn_diff_summarize_rejects_nonnumeric_rev():
    """정수 아닌 revision(SHA1 등)은 거부 → 인자 주입 표면 차단."""
    from backend.services import local_service as ls

    out = ls.svn_diff_summarize(repo_url="https://x/r", rev_a="deadbeef", rev_b="150")
    assert out["rc"] == 1
    assert out["files"] == []
    assert out["edit_types"] == {}


# ── 변경 상세(시그니처 이전→이후) 추출 ──────────────────────────────────

def test_extract_signature_changes_captures_before_after():
    """unified diff에서 시그니처 이전(-)/이후(+) + 신규(after만)를 추출한다."""
    from workflow.delta_update import extract_signature_changes

    diff = "\n".join([
        "Index: APP/motor.c",
        "--- APP/motor.c\t(revision 100)",
        "+++ APP/motor.c\t(revision 150)",
        "@@ -10,7 +10,7 @@",
        "-int s_MotorCtrl(int a) {",
        "+int s_MotorCtrl(int a, bool b) {",
        "     return a;",
        " }",
        "+void g_NewDoor(U8 mode) {",
        "+    open(mode);",
        "+}",
    ])
    out = extract_signature_changes(diff)
    assert out["s_MotorCtrl"]["before"] == "int s_MotorCtrl(int a)"
    assert out["s_MotorCtrl"]["after"] == "int s_MotorCtrl(int a, bool b)"
    assert out["g_NewDoor"]["after"] == "void g_NewDoor(U8 mode)"
    assert "before" not in out["g_NewDoor"]


def test_extract_signature_changes_skips_unbalanced_decl():
    """멀티라인 선언의 여는 괄호 줄만(닫힘 없음)은 before==after 은폐 방지 위해 스킵."""
    from workflow.delta_update import extract_signature_changes

    diff = "-int Foo(\n+int Foo("  # 괄호 불균형(닫힘 부족) → 미확보 처리
    assert "Foo" not in extract_signature_changes(diff)


def test_try_svn_revision_range_reverse_direction_returns_none(monkeypatch):
    """A(로컬 작업본) > B(선택 빌드) 역방향이면 None(changeSet 폴백) — 삭제 가이드 오발동 방지."""
    from backend.routers import jenkins as jr
    from backend.schemas import JenkinsImpactTriggerRequest

    _patch_svn_range(monkeypatch, entry=_FakeSvnEntry(), info_rev="200", diff_boom=True)
    out = jr._try_svn_revision_range(
        JenkinsImpactTriggerRequest(scm_id="x", build_number=5, job_url="http://j/job/X"),
        build_rev="150",
    )
    assert out is None


def test_collect_signature_changes_reverse_returns_empty(monkeypatch):
    """A>B이면 svn_diff_unified를 호출하지 않고 빈 dict(역방향 원문 뒤집힘 방지)."""
    from workflow import impact_orchestrator as orch
    import backend.services.local_service as ls

    class _T:
        scm_id = "x"; scm_type = "svn"; base_ref = ""; changed_files = ["a.c"]; source_root = "D:/wc"

    class _E:
        scm_url = "https://svn.example/repo/trunk"; source_root = "D:/wc"

    def _boom(**_k):
        raise AssertionError("svn_diff_unified must not run for A>B")

    monkeypatch.setattr(ls, "svn_diff_unified", _boom)
    out = orch._collect_signature_changes(_T(), {"baseline_revision": "200", "build_revision": "150"}, _E())
    assert out == {}


def test_extract_signature_changes_ignores_body_only():
    """본문(로직)만 바뀌면 선언 라인이 없어 원문 결과가 비어야 한다."""
    from workflow.delta_update import extract_signature_changes

    diff = "\n".join([
        "@@ -5,3 +5,3 @@ int s_Foo(int a)",
        "-    x = 1;",
        "+    x = 2;",
    ])
    assert extract_signature_changes(diff) == {}


def test_svn_diff_unified_rejects_nonnumeric_rev():
    from backend.services import local_service as ls

    out = ls.svn_diff_unified(repo_url="https://x/r", rev_a="abc", rev_b="150")
    assert out["rc"] == 1


def test_svn_diff_unified_runs(monkeypatch):
    from backend.services import local_service as ls

    monkeypatch.setattr(ls, "_run_cmd", lambda *_a, **_k: (0, "Index: a.c\n-int f(void) {\n+int f(int a) {"))
    out = ls.svn_diff_unified(repo_url="https://x/repo/trunk", rev_a="100", rev_b="150")
    assert out["rc"] == 0
    assert "int f" in out["output"]


def test_collect_signature_changes_svn_range(monkeypatch):
    """svn A:B 경로: baseline/build revision이 있으면 전체 unified diff로 시그니처 추출."""
    from workflow import impact_orchestrator as orch
    import backend.services.local_service as ls
    import backend.services.scm_registry as reg

    class _T:
        scm_id = "x"; scm_type = "svn"; base_ref = ""; changed_files = ["a.c"]; source_root = "D:/wc"

    class _E:
        scm_url = "https://svn.example/repo/trunk"; source_root = "D:/wc"

    monkeypatch.setattr(reg, "resolve_scm_credentials", lambda **_k: ("u", "p", None))
    monkeypatch.setattr(ls, "svn_diff_unified", lambda **_k: {
        "rc": 0, "output": "-int f(void) {\n+int f(int a) {"})
    out = orch._collect_signature_changes(_T(), {"baseline_revision": "100", "build_revision": "150"}, _E())
    assert out["f"]["before"] == "int f(void)"
    assert out["f"]["after"] == "int f(int a)"
