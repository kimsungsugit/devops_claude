"""prqa_rule_trend — 규칙×빌드 분류 5종·미분석 null·insufficient_data·residual 제외.

추가 계약(2026-07-27): 규칙 미적용 빌드 null(규칙셋 확장을 '신규 발생'으로 오분류 금지) ·
변화 구간(decrease/increase window) 기반 파일 증거 · RCMA류 pseudo 엔트리 cross_module scope.
"""
from __future__ import annotations

from pathlib import Path

from backend.services.prqa_rule_trend import (
    _classify,
    compute_rule_trend,
    cross_module_keys,
    is_cross_module_key,
    rules_applied_in_build,
)


# ── 분류 순수 함수 ──────────────────────────────────────────────────────────

def test_classify_five_kinds_and_priority():
    assert _classify([5, 3, 0]) == "resolved"          # 최신 0 + 과거 >0
    assert _classify([0, 2, 4]) == "new_recent"        # 최초 0 → 등장
    assert _classify([3, 5, 7]) == "increasing"
    assert _classify([7, 5, 3]) == "decreasing"
    assert _classify([4, 4, 4]) == "persistent"
    assert _classify([0, 5, 0]) == "resolved"          # resolved가 new_recent보다 우선
    assert _classify([0, 0, 0]) is None                # 전 구간 0 — 노이즈
    assert _classify([5]) is None                      # 관측 1개 — 분류 불가
    assert _classify([None, 5, None, 3]) == "decreasing"  # null(미분석) 자리는 건너뜀


# ── compute_rule_trend (캐시 빌드 픽스처) ───────────────────────────────────

def _mk_build(tmp_path: Path, n: int, *, rcr_html: str | None) -> None:
    root = tmp_path / "jenkins" / "http_j_job_X" / f"build_{n}"
    (root / "report").mkdir(parents=True)
    if rcr_html is not None:
        (root / f"X_RCR_0101202{n % 10}.html").write_text(rcr_html, encoding="utf-8")


# J1: RCFInfo(규칙 설명) 블록 — 실물 구조(빈 <td> 들여쓰기 + <td title>규칙ID + enabled).
_RCF_BLOCK = """
 <div class="sec"><h3><a name="RCFInfo">Rule Configuration Status</a></h3></div>
 <div class="subsec"><h5>M3CM</h5></div>
 <table border="0">
  <tr><td></td><td></td><td></td><td title="one one desc">Rule-1.1</td><td>enabled</td></tr>
 </table>"""


def _rcr(foo_r1: int, foo_r2: int, residual_vc: int = 0, rcf: str = "") -> str:
    """WorstRules(Rule-1.1/Rule-2.2) + FileStatus(잔차 유발용 vc 가산) 최소 RCR."""
    vc = foo_r1 + foo_r2 + residual_vc
    return f"""<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Rule-1.1</th><th>Rule-2.2</th></tr>
  <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>{foo_r1}</td><td>{foo_r2}</td></tr>
 </table>
 <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Active Diagnostics</th><th>Violated Rules</th><th>Violation Count</th><th>Compliance Index</th></tr>
  <tr><td align="left"><a href="..\\src\\foo.c" title="..\\src\\foo.c">foo.c</a></td><td>1</td><td>2</td><td>{vc}</td><td>90.00%</td></tr>
 </table>{rcf}
</body></html>"""


def test_rule_trend_series_classification_and_files(tmp_path):
    # 122: R1=6/R2=0, 124: RCR 없음(미분석), 125: R1=2/R2=4
    _mk_build(tmp_path, 122, rcr_html=_rcr(6, 0))
    _mk_build(tmp_path, 124, rcr_html=None)
    _mk_build(tmp_path, 125, rcr_html=_rcr(2, 4))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out["available"] is True and out["insufficient_data"] is False
    assert [b["build_number"] for b in out["builds"]] == [122, 124, 125]  # 오름차순
    assert out["builds"][1]["analyzed"] is False
    assert out["builds_skipped"] == [{"build_number": 124, "reason": "no_rcr"}]
    by = {r["rule"]: r for r in out["rules"]}
    # 미분석 빌드 자리는 null(0 위장 금지)
    assert by["Rule-1.1"]["counts"] == [6, None, 2]
    assert by["Rule-1.1"]["classification"] == "decreasing"
    assert by["Rule-1.1"]["net"] == -4
    assert by["Rule-2.2"]["counts"] == [0, None, 4]
    assert by["Rule-2.2"]["classification"] == "new_recent"
    # 감소 규칙의 파일 귀속(from→to 감소)
    dec = by["Rule-1.1"]["decreased_files"]
    assert dec and dec[0]["from_build"] == 122 and dec[0]["to_build"] == 125 and dec[0]["delta"] == -4
    assert by["Rule-2.2"]["files_latest"][0]["count"] == 4
    assert out["summary"]["decreasing"] == 1 and out["summary"]["new_recent"] == 1
    # 2회차 — 전부 디스크 캐시 히트
    out2 = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out2["cache"]["rcr_misses"] == 0 and out2["cache"]["rcr_hits"] == 2


def test_rule_trend_insufficient_data_no_classification(tmp_path):
    _mk_build(tmp_path, 125, rcr_html=_rcr(3, 1))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out["available"] is True and out["insufficient_data"] is True
    assert all(r["classification"] is None for r in out["rules"])  # 단일 관측 — 추세 단정 금지


def test_rule_trend_residual_separated(tmp_path):
    """FileStatus 잔차(기타 비상위)는 규칙 시리즈가 아니라 residual.counts로만."""
    _mk_build(tmp_path, 122, rcr_html=_rcr(2, 0, residual_vc=5))
    _mk_build(tmp_path, 125, rcr_html=_rcr(2, 0, residual_vc=9))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    rule_names = {r["rule"] for r in out["rules"]}
    assert not any("기타" in n for n in rule_names)
    assert out["residual"]["counts"] == [5, 9]


def test_rule_trend_no_cache_and_no_rcr(tmp_path):
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out["available"] is False and out["reason"] == "no_cached_build"
    _mk_build(tmp_path, 1, rcr_html=None)
    out2 = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out2["available"] is False and out2["reason"] == "no_rcr_in_cached_builds"


# ── J1: 규칙 설명(RCFInfo) 병합 + observed_range ────────────────────────────

def test_rule_trend_descriptions_from_latest_analyzed_and_observed_range(tmp_path):
    # 122엔 RCFInfo 없음, 125엔 있음 → 설명은 "설명을 가진 최신 analyzed"(125) 기준 + 출처 명시.
    _mk_build(tmp_path, 122, rcr_html=_rcr(6, 0))
    _mk_build(tmp_path, 124, rcr_html=None)
    _mk_build(tmp_path, 125, rcr_html=_rcr(2, 4, rcf=_RCF_BLOCK))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out["descriptions_available"] is True
    assert out["descriptions_source_build"] == 125
    # 관측 구간 = 최초↔최신 analyzed(미분석 124는 경계가 아님) — J2 구간 증거의 from/to 쌍.
    assert out["observed_range"] == {"from_build": 122, "to_build": 125}
    by = {r["rule"]: r for r in out["rules"]}
    assert by["Rule-1.1"]["description"] == {"title": "one one desc", "enabled": True, "group": "M3CM"}
    assert by["Rule-2.2"]["description"] is None  # RCFInfo에 없는 규칙 — None(빈 문자열 위장 금지)


# ── 규칙셋 변동 · 변화 구간 · cross_module (2026-07-27) ─────────────────────

def _rcf(*rules: tuple) -> str:
    """RCFInfo 블록 — (rule_id, enabled) 목록. 규칙 '적용 여부'의 유일 판정 근거."""
    rows = "".join(
        f'<tr><td></td><td title="{r} desc">{r}</td><td>{"enabled" if en else "disabled"}</td></tr>'
        for r, en in rules
    )
    return f"""
 <div class="sec"><h3><a name="RCFInfo">Rule Configuration Status</a></h3></div>
 <div class="subsec"><h5>M3CM</h5></div>
 <table border="0">{rows}</table>"""


def _rcr_multi(files: dict, *, rcma: dict | None = None, rcf: str = "") -> str:
    """파일별 규칙 카운트 + (옵션) RCMA pseudo 행(FileStatus 부재 = 파일 귀속 없음) RCR."""
    rules = sorted({r for rc in files.values() for r in rc} | set(rcma or {}))
    th = "".join(f"<th>{r}</th>" for r in rules)
    wr = ""
    for path, rc in files.items():
        name = path.rsplit("/", 1)[-1]
        wr += (f'<tr><td align="left"><a href="{path}" title="{path}">{name}</a></td>'
               + "".join(f"<td>{rc.get(r, 0)}</td>" for r in rules) + "</tr>")
    if rcma:
        # anchor 없는 셀 → path_raw='' → 표시명이 키(실측 KJPDS02_PV RCMA 행과 동일 구조).
        wr += '<tr><td align="left">RCMA</td>' + "".join(f"<td>{rcma.get(r, 0)}</td>" for r in rules) + "</tr>"
    fs = ""
    for path, rc in files.items():
        name = path.rsplit("/", 1)[-1]
        fs += (f'<tr><td align="left"><a href="{path}" title="{path}">{name}</a></td>'
               f'<td>1</td><td>{len(rc)}</td><td>{sum(rc.values())}</td><td>90.00%</td></tr>')
    return f"""<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
 <table border="1"><tr><th>Files</th>{th}</tr>{wr}</table>
 <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Active Diagnostics</th><th>Violated Rules</th><th>Violation Count</th><th>Compliance Index</th></tr>
  {fs}
 </table>{rcf}
</body></html>"""


def test_ruleset_expansion_is_not_new_violation(tmp_path):
    """규칙셋 확장(#125에 규칙 추가)은 '신규 발생'이 아니다 — 미적용 구간은 null."""
    _mk_build(tmp_path, 122, rcr_html=_rcr_multi(
        {"src/foo.c": {"Rule-1.1": 6}}, rcf=_rcf(("Rule-1.1", True))))
    _mk_build(tmp_path, 125, rcr_html=_rcr_multi(
        {"src/foo.c": {"Rule-1.1": 6, "Rule-9.9": 4}},
        rcf=_rcf(("Rule-1.1", True), ("Rule-9.9", True))))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    by = {r["rule"]: r for r in out["rules"]}
    r99 = by["Rule-9.9"]
    assert r99["counts"] == [None, 4]          # #122엔 검사 자체가 없었다(0 위장 금지)
    assert r99["classification"] is None       # 관측 1개 — 추세 단정 금지
    assert r99["classification_reason"] == "insufficient_observations"
    assert r99["applied_from_build"] == 125 and r99["scope_narrowed"] is True
    assert out["summary"]["new_recent"] == 0   # 규칙 확장을 코드 악화로 보고하지 않는다
    assert out["ruleset_sizes"] == [1, 2]
    # 검사가 계속 적용된 규칙은 그대로 0/양수 유지.
    assert by["Rule-1.1"]["counts"] == [6, 6] and by["Rule-1.1"]["scope_narrowed"] is False


def test_disabled_rule_counts_as_not_measured(tmp_path):
    """비활성 규칙 구간도 null — 검사하지 않은 것을 '위반 0'으로 적지 않는다."""
    _mk_build(tmp_path, 122, rcr_html=_rcr_multi(
        {"src/foo.c": {"Rule-1.1": 6}}, rcf=_rcf(("Rule-1.1", True), ("Rule-9.9", False))))
    _mk_build(tmp_path, 125, rcr_html=_rcr_multi(
        {"src/foo.c": {"Rule-1.1": 6, "Rule-9.9": 4}},
        rcf=_rcf(("Rule-1.1", True), ("Rule-9.9", True))))
    by = {r["rule"]: r for r in compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)["rules"]}
    assert by["Rule-9.9"]["counts"] == [None, 4]


def test_decrease_window_finds_mid_range_fix(tmp_path):
    """구간 **중간**에서 해소된 규칙의 파일 증거 — 전 구간(first→last) 비교로는 놓친다."""
    rcf = _rcf(("Rule-1.1", True), ("Rule-9.9", True))
    _mk_build(tmp_path, 120, rcr_html=_rcr_multi({"src/foo.c": {"Rule-1.1": 5, "Rule-9.9": 0}}, rcf=rcf))
    _mk_build(tmp_path, 122, rcr_html=_rcr_multi({"src/foo.c": {"Rule-1.1": 5, "Rule-9.9": 3}}, rcf=rcf))
    _mk_build(tmp_path, 123, rcr_html=_rcr_multi({"src/foo.c": {"Rule-1.1": 5, "Rule-9.9": 0}}, rcf=rcf))
    by = {r["rule"]: r for r in compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)["rules"]}
    r99 = by["Rule-9.9"]
    assert r99["counts"] == [0, 3, 0] and r99["classification"] == "resolved"
    # 감소 구간은 #122→#123(전 구간 #120→#123은 0→0으로 후보가 비었다).
    assert r99["decrease_window"]["from_build"] == 122 and r99["decrease_window"]["to_build"] == 123
    assert [(f["path"], f["delta"]) for f in r99["decreased_files"]] == [("src/foo.c", -3)]
    assert r99["increase_window"]["from_build"] == 120  # 발생 구간도 함께 노출
    assert [(f["path"], f["delta"]) for f in r99["increased_files"]] == [("src/foo.c", 3)]


def test_decreased_files_reported_even_when_total_increases(tmp_path):
    """총량이 늘어난 규칙 안의 감소 파일도 증거로 낸다 — '잘 된 예시'의 유일한 근거."""
    rcf = _rcf(("Rule-1.1", True))
    _mk_build(tmp_path, 122, rcr_html=_rcr_multi(
        {"src/foo.c": {"Rule-1.1": 14}, "src/bar.c": {"Rule-1.1": 0}}, rcf=rcf))
    _mk_build(tmp_path, 125, rcr_html=_rcr_multi(
        {"src/foo.c": {"Rule-1.1": 12}, "src/bar.c": {"Rule-1.1": 5}}, rcf=rcf))
    row = next(r for r in compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)["rules"]
               if r["rule"] == "Rule-1.1")
    assert row["classification"] == "increasing"      # 총량 14 → 17
    assert [(f["path"], f["delta"]) for f in row["decreased_files"]] == [("src/foo.c", -2)]
    assert [(f["path"], f["delta"]) for f in row["increased_files"]] == [("src/bar.c", 5)]


def test_cross_module_pseudo_entry_marked_not_file(tmp_path):
    """RCMA류 pseudo 엔트리는 scope='cross_module' — 스냅샷 조회 대상이 아니다."""
    rcf = _rcf(("Rule-8.6", True))
    _mk_build(tmp_path, 122, rcr_html=_rcr_multi({"src/foo.c": {}}, rcma={"Rule-8.6": 105}, rcf=rcf))
    _mk_build(tmp_path, 125, rcr_html=_rcr_multi({"src/foo.c": {}}, rcma={"Rule-8.6": 99}, rcf=rcf))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out["cross_module_keys"] == ["RCMA"]
    row = next(r for r in out["rules"] if r["rule"] == "Rule-8.6")
    assert row["classification"] == "decreasing"
    assert row["files_latest"] == [{"path": "RCMA", "count": 99, "scope": "cross_module"}]
    assert [(f["path"], f.get("scope")) for f in row["decreased_files"]] == [("RCMA", "cross_module")]


def test_cross_module_key_and_applied_helpers():
    assert is_cross_module_key("RCMA") is True
    assert is_cross_module_key("APP/foo.c") is False
    assert is_cross_module_key("foo.h") is False
    assert is_cross_module_key("") is False          # 빈 키는 판정 대상 아님
    details = {"violations_by_file": [
        {"file": "RCMA", "path": "", "rules": []},
        {"file": "foo.c", "path": "", "rules": []},       # 경로 정규화 실패한 실제 파일 — 제외
        {"file": "bar.c", "path": "src/bar.c", "rules": []},
    ]}
    assert cross_module_keys(details) == {"RCMA"}
    # RCFInfo 부재 → None(판정 불가). 있으면 enabled만.
    assert rules_applied_in_build({}) is None
    assert rules_applied_in_build({"rule_descriptions": {
        "A": {"enabled": True}, "B": {"enabled": False}, "C": {},
    }}) == {"A", "C"}


def test_rule_trend_descriptions_absent(tmp_path):
    # 전 빌드 RCFInfo 부재 — available False + 전 규칙 description None(침묵 기본값 금지).
    _mk_build(tmp_path, 122, rcr_html=_rcr(6, 0))
    _mk_build(tmp_path, 125, rcr_html=_rcr(2, 4))
    out = compute_rule_trend(job_url="http://j/job/X/", cache_root=tmp_path)
    assert out["descriptions_available"] is False
    assert out["descriptions_source_build"] is None
    assert all(r["description"] is None for r in out["rules"])
