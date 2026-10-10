"""빌드간 PRQA 위반 delta — prqa_delta 서비스 + POST /api/jenkins/prqa-delta.

정직성 규약 검증 중심: 계산 불가 → available:false+reason(침묵 0 금지),
residual은 규칙 delta에서 분리, path 조인(basename 오병합 방지), 캐시 무효화 키.
"""
from __future__ import annotations

import json
from pathlib import Path

# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────


def _details(files):
    """parse_prqa_rcr_details 출력 최소형 — violations_by_file만 delta에 필요.

    files: [(file, path, total, {rule: count}, residual_count)]
    """
    vbf = []
    attributed = 0
    for file, path, total, rules, residual in files:
        rule_list = [{"rule": r, "count": c} for r, c in rules.items()]
        if residual:
            rule_list.append({"rule": "기타 규칙 (비상위)", "count": residual, "residual": True})
        vbf.append({"file": file, "path": path, "total": total, "rules": rule_list})
        attributed += total
    return {"violations_by_file": vbf, "violations_attributed_total": attributed}


def _rcr_html(foo_r86=5, foo_r21=3, bar_r86=10):
    """WorstRules + FileStatus 최소 RCR — test_report_parsers._RCR_HTML 축약형."""
    foo_vc = foo_r86 + foo_r21
    return f"""<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Rule-2.1</th><th>Rule-8.6</th></tr>
  <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>{foo_r21}</td><td>{foo_r86}</td></tr>
  <tr><td align="left"><a href="..\\src\\bar.c" title="..\\src\\bar.c">bar.c</a></td><td>0</td><td>{bar_r86}</td></tr>
 </table>
 <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Active Diagnostics</th><th>Violated Rules</th><th>Violation Count</th><th>Compliance Index</th></tr>
  <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>1</td><td>2</td><td>{foo_vc}</td><td>98.00%</td></tr>
  <tr><td align="left"><a href="..\\src\\bar.c" title="..\\src\\bar.c">bar.c</a></td><td>1</td><td>1</td><td>{bar_r86}</td><td>95.00%</td></tr>
 </table>
</body></html>"""


# ── compute_prqa_pair_delta (순수 계산) ──────────────────────────────────────


def test_pair_delta_new_resolved_increased_decreased():
    from backend.services.prqa_delta import compute_prqa_pair_delta

    base = _details([("a.c", "src/a.c", 10, {"Rule-1.1": 4, "Rule-2.2": 3, "Rule-3.3": 3}, 0)])
    cur = _details([("a.c", "src/a.c", 12, {"Rule-1.1": 7, "Rule-3.3": 1, "Rule-9.9": 4}, 0)])
    d = compute_prqa_pair_delta(cur, base)
    assert d["rules"]["new"] == [{"rule": "Rule-9.9", "count": 4}]
    assert d["rules"]["resolved"] == [{"rule": "Rule-2.2", "count_was": 3}]
    assert d["rules"]["increased"] == [{"rule": "Rule-1.1", "base": 4, "cur": 7, "delta": 3}]
    assert d["rules"]["decreased"] == [{"rule": "Rule-3.3", "base": 3, "cur": 1, "delta": -2}]
    assert d["totals"] == {"cur": 12, "base": 10, "delta": 2}
    assert d["basis"] == "worstrules_matrix"


def test_pair_delta_residual_bucket_separated():
    """residual('기타 규칙')은 규칙 delta에 섞이지 않고 residual_delta로만 나온다."""
    from backend.services.prqa_delta import compute_prqa_pair_delta

    base = _details([("a.c", "src/a.c", 10, {"Rule-1.1": 4}, 6)])
    cur = _details([("a.c", "src/a.c", 13, {"Rule-1.1": 4}, 9)])
    d = compute_prqa_pair_delta(cur, base)
    assert d["rules"]["new"] == [] and d["rules"]["resolved"] == []
    assert d["rules"]["increased"] == [] and d["rules"]["decreased"] == []
    assert d["rules"]["residual_delta"] == 3
    # 파일 delta에는 총계 변화가 잡힌다(잔차 몫 포함).
    assert d["files"][0]["delta"] == 3


def test_pair_delta_file_join_by_path_not_basename():
    """APP/config.c vs BOOT/config.c — path 키 조인이라 동명 파일이 오병합되지 않는다."""
    from backend.services.prqa_delta import compute_prqa_pair_delta

    base = _details(
        [
            ("config.c", "APP/config.c", 5, {"Rule-1.1": 5}, 0),
            ("config.c", "BOOT/config.c", 2, {"Rule-2.2": 2}, 0),
        ]
    )
    cur = _details(
        [
            ("config.c", "APP/config.c", 8, {"Rule-1.1": 8}, 0),
            ("config.c", "BOOT/config.c", 2, {"Rule-2.2": 2}, 0),
        ]
    )
    d = compute_prqa_pair_delta(cur, base)
    assert len(d["files"]) == 1  # BOOT 쪽 무변화 → 제외
    assert d["files"][0]["path"] == "APP/config.c"
    assert d["files"][0]["delta"] == 3


def test_pair_delta_rule_swap_zero_net_still_reported():
    """총계는 그대로여도 규칙 구성이 바뀐 파일(+A/−B)은 delta 행으로 유지."""
    from backend.services.prqa_delta import compute_prqa_pair_delta

    base = _details([("a.c", "src/a.c", 6, {"Rule-1.1": 6}, 0)])
    cur = _details([("a.c", "src/a.c", 6, {"Rule-2.2": 6}, 0)])
    d = compute_prqa_pair_delta(cur, base)
    assert len(d["files"]) == 1
    assert d["files"][0]["delta"] == 0
    rules = {r["rule"]: r["delta"] for r in d["files"][0]["rules"]}
    assert rules == {"Rule-2.2": 6, "Rule-1.1": -6}


def test_pair_delta_max_files_cap_and_omitted_count():
    from backend.services.prqa_delta import compute_prqa_pair_delta

    base = _details([(f"f{i}.c", f"src/f{i}.c", 1, {"Rule-1.1": 1}, 0) for i in range(5)])
    cur = _details([(f"f{i}.c", f"src/f{i}.c", 1 + i + 1, {"Rule-1.1": 1 + i + 1}, 0) for i in range(5)])
    d = compute_prqa_pair_delta(cur, base, max_files=2)
    assert len(d["files"]) == 2
    assert d["files_omitted"] == 3
    # |delta| 내림차순 — 가장 큰 증가(f4: +5)가 먼저.
    assert d["files"][0]["file"] == "f4.c"


def test_changed_file_signals_intersection_and_normalization():
    """경로 구분자(\\)·대소문자 정규화 + 세그먼트 경계 suffix 매칭. 부분 파일명 오매칭 금지."""
    from backend.services.prqa_delta import apply_changed_file_signals

    files = [
        {"file": "foo.c", "path": "APP/src/Foo.c", "delta": 5, "rules": [{"rule": "Rule-8.6", "delta": 5}]},
        {"file": "x_foo.c", "path": "APP/src/x_foo.c", "delta": 2, "rules": []},
        {"file": "quiet.c", "path": "APP/src/quiet.c", "delta": -1, "rules": []},
    ]
    signals = apply_changed_file_signals(files, ["Sources\\APP\\src\\foo.c", "Sources/APP/src/quiet.c"])
    assert files[0]["in_changed_set"] is True
    assert files[1]["in_changed_set"] is False  # 'x_foo.c'는 'foo.c'와 경계 불일치
    assert files[2]["in_changed_set"] is True
    # 신호는 '변경 파일 ∧ 위반 증가'만 — quiet.c(-1)는 제외.
    assert len(signals) == 1
    assert signals[0]["file"] == "APP/src/Foo.c"
    assert signals[0]["rules"] == ["Rule-8.6"]


def test_rule_totals_skips_residual_and_counts_all_files():
    from backend.services.prqa_delta import rule_totals_from_details

    details = _details(
        [
            ("a.c", "src/a.c", 7, {"Rule-1.1": 4}, 3),
            ("b.c", "src/b.c", 2, {"Rule-1.1": 1, "Rule-2.2": 1}, 0),
        ]
    )
    totals, residual = rule_totals_from_details(details)
    assert totals == {"Rule-1.1": 5, "Rule-2.2": 1}
    assert residual == 3


# ── RCR 상세 디스크 캐시 ─────────────────────────────────────────────────────


def _write_rcr(build_root: Path, html: str, name="PROJ_RCR_01012026.html"):
    build_root.mkdir(parents=True, exist_ok=True)
    reports = build_root / "report"
    reports.mkdir(exist_ok=True)
    (build_root / name).write_text(html, encoding="utf-8")
    return reports


def test_rcr_details_cache_roundtrip(tmp_path, monkeypatch):
    """1회차 파싱 후 캐시 생성 → 2회차는 파서 미호출(cache_hit)."""
    from backend.services import prqa_delta

    reports = _write_rcr(tmp_path / "build_10", _rcr_html())
    calls = {"n": 0}
    real = prqa_delta.parse_prqa_rcr_details

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(prqa_delta, "parse_prqa_rcr_details", counting)
    r1 = prqa_delta.load_rcr_details_cached(tmp_path / "build_10", reports)
    assert r1 is not None and r1["cache_hit"] is False
    assert (reports / prqa_delta.RCR_DETAILS_CACHE_NAME).exists()
    r2 = prqa_delta.load_rcr_details_cached(tmp_path / "build_10", reports)
    assert r2 is not None and r2["cache_hit"] is True
    assert calls["n"] == 1
    assert r2["details"]["violations_by_file"] == r1["details"]["violations_by_file"]


def test_rcr_details_cache_invalidate_on_mtime_and_version(tmp_path, monkeypatch):
    from backend.services import prqa_delta

    build_root = tmp_path / "build_10"
    reports = _write_rcr(build_root, _rcr_html())
    r1 = prqa_delta.load_rcr_details_cached(build_root, reports)
    assert r1["cache_hit"] is False
    # RCR 원본 교체(mtime/size 변화) → 재파싱
    (build_root / "PROJ_RCR_01012026.html").write_text(_rcr_html(bar_r86=20), encoding="utf-8")
    r2 = prqa_delta.load_rcr_details_cached(build_root, reports)
    assert r2["cache_hit"] is False
    # 파서 버전 증가 → 캐시 무효화
    monkeypatch.setattr(prqa_delta, "PARSER_VERSION", prqa_delta.PARSER_VERSION + 1)
    r3 = prqa_delta.load_rcr_details_cached(build_root, reports)
    assert r3["cache_hit"] is False


def test_rcr_details_cache_write_failure_fail_soft(tmp_path, monkeypatch):
    """캐시 기록 실패(권한 등)여도 파싱 결과는 정상 반환."""
    from backend.services import prqa_delta

    build_root = tmp_path / "build_10"
    reports = _write_rcr(build_root, _rcr_html())

    def boom(self, *a, **k):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)
    r = prqa_delta.load_rcr_details_cached(build_root, reports)
    assert r is not None and r["cache_hit"] is False
    assert r["details"]["violations_by_file"]


def test_rcr_missing_returns_none(tmp_path):
    from backend.services.prqa_delta import load_rcr_details_cached

    build_root = tmp_path / "build_10"
    (build_root / "report").mkdir(parents=True)
    assert load_rcr_details_cached(build_root, build_root / "report") is None


# ── POST /api/jenkins/prqa-delta 엔드포인트 ─────────────────────────────────


def _builds_meta(tmp_path, numbers):
    out = []
    for n in numbers:
        br = tmp_path / f"build_{n}"
        out.append({"build_root": str(br), "build_number": n, "reports_dir": str(br / "report"), "mtime": 0})
    return sorted(out, key=lambda b: -b["build_number"])


def test_endpoint_pair_delta_with_auto_baseline(tmp_path, monkeypatch):
    from backend.routers import summary_insight

    _write_rcr(tmp_path / "build_124", _rcr_html(bar_r86=10))
    _write_rcr(tmp_path / "build_125", _rcr_html(bar_r86=14))
    monkeypatch.setattr(summary_insight, "list_cached_builds", lambda **k: _builds_meta(tmp_path, [125, 124]))
    resp = summary_insight.jenkins_prqa_delta({"job_url": "http://j/", "build_number": 125, "cache_root": str(tmp_path / "cr")})
    assert resp["available"] is True
    assert resp["baseline_build_number"] == 124 and resp["baseline_auto"] is True
    inc = {r["rule"]: r["delta"] for r in resp["rules"]["increased"]}
    assert inc == {"Rule-8.6": 4}
    assert resp["totals"]["delta"] == 4
    # 변경파일 미제공 → in_changed_set 필드 자체가 없다(false 위장 금지).
    assert resp["changed_files"]["available"] is False
    assert all("in_changed_set" not in f for f in resp["files"])
    assert "files" not in resp["changed_files"]  # 응답 경량화(목록은 signals/files로 충분)


def test_endpoint_no_rcr_available_false_with_reason(tmp_path, monkeypatch):
    """현재/기준 어느 한쪽 RCR 부재 → 부분 delta 금지, reason 명시."""
    from backend.routers import summary_insight

    _write_rcr(tmp_path / "build_125", _rcr_html())
    (tmp_path / "build_124" / "report").mkdir(parents=True)  # RCR 없음
    monkeypatch.setattr(summary_insight, "list_cached_builds", lambda **k: _builds_meta(tmp_path, [125, 124]))
    resp = summary_insight.jenkins_prqa_delta({"job_url": "http://j/", "build_number": 125})
    assert resp["available"] is False and resp["reason"] == "no_rcr_baseline"
    resp2 = summary_insight.jenkins_prqa_delta({"job_url": "http://j/", "build_number": 124})
    assert resp2["available"] is False and resp2["reason"] == "no_rcr_current"


def test_endpoint_single_build_no_baseline(tmp_path, monkeypatch):
    from backend.routers import summary_insight

    _write_rcr(tmp_path / "build_125", _rcr_html())
    monkeypatch.setattr(summary_insight, "list_cached_builds", lambda **k: _builds_meta(tmp_path, [125]))
    resp = summary_insight.jenkins_prqa_delta({"job_url": "http://j/", "build_number": 125})
    assert resp["available"] is False and resp["reason"] == "no_baseline_build"


def test_endpoint_build_not_cached_and_missing_params(tmp_path, monkeypatch):
    from backend.routers import summary_insight

    monkeypatch.setattr(summary_insight, "list_cached_builds", lambda **k: [])
    assert summary_insight.jenkins_prqa_delta({})["reason"] == "job_url_required"
    assert summary_insight.jenkins_prqa_delta({"job_url": "http://j/"})["reason"] == "build_number_required"
    resp = summary_insight.jenkins_prqa_delta({"job_url": "http://j/", "build_number": 9})
    assert resp["available"] is False and resp["reason"] == "build_not_cached"


def test_endpoint_explicit_baseline_and_changed_files_signals(tmp_path, monkeypatch):
    """명시 baseline + scm_id change-log 교차 — in_changed_set/signals 배선."""
    from backend.routers import summary_insight

    _write_rcr(tmp_path / "build_120", _rcr_html(foo_r86=5))
    _write_rcr(tmp_path / "build_125", _rcr_html(foo_r86=9))
    monkeypatch.setattr(summary_insight, "list_cached_builds", lambda **k: _builds_meta(tmp_path, [125, 124, 120]))
    monkeypatch.setattr(
        summary_insight,
        "_changed_files_for_build",
        lambda scm_id, n: {"available": True, "source": "change_log", "count": 1, "files": ["Sources/src/foo.c"]},
    )
    resp = summary_insight.jenkins_prqa_delta(
        {"job_url": "http://j/", "build_number": 125, "baseline_build_number": 120, "scm_id": "kj"}
    )
    assert resp["available"] is True
    assert resp["baseline_build_number"] == 120 and resp["baseline_auto"] is False
    foo = next(f for f in resp["files"] if f["file"] == "foo.c")
    assert foo["in_changed_set"] is True and foo["delta"] == 4
    assert resp["signals"] and resp["signals"][0]["type"] == "changed_file_violation_increase"


def test_endpoint_cache_hits_second_call(tmp_path, monkeypatch):
    from backend.routers import summary_insight

    _write_rcr(tmp_path / "build_124", _rcr_html())
    _write_rcr(tmp_path / "build_125", _rcr_html(bar_r86=11))
    monkeypatch.setattr(summary_insight, "list_cached_builds", lambda **k: _builds_meta(tmp_path, [125, 124]))
    body = {"job_url": "http://j/", "build_number": 125}
    r1 = summary_insight.jenkins_prqa_delta(body)
    assert r1["cache"] == {"cur_hit": False, "base_hit": False}
    r2 = summary_insight.jenkins_prqa_delta(body)
    assert r2["cache"] == {"cur_hit": True, "base_hit": True}
    assert r2["rules"] == r1["rules"]


def test_changed_files_lookup_no_log(monkeypatch, tmp_path):
    """change-log에 해당 빌드가 없으면 available:false(공집합 위장 금지)."""
    from backend.routers import summary_insight
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    out = summary_insight._changed_files_for_build("kj", 999)
    assert out["available"] is False and out["reason"] == "no_change_log_for_build"
    out2 = summary_insight._changed_files_for_build("", 1)
    assert out2["available"] is False and out2["reason"] == "scm_id_not_provided"


def test_cache_file_is_valid_json_with_src_signature(tmp_path):
    from backend.services import prqa_delta

    reports = _write_rcr(tmp_path / "build_10", _rcr_html())
    prqa_delta.load_rcr_details_cached(tmp_path / "build_10", reports)
    payload = json.loads((reports / prqa_delta.RCR_DETAILS_CACHE_NAME).read_text(encoding="utf-8"))
    assert payload["src"]["parser_version"] == prqa_delta.PARSER_VERSION
    assert payload["src"]["mtime_ns"] > 0 and payload["src"]["size"] > 0
    assert isinstance(payload["details"]["violations_by_file"], list)
