"""prqa_rule_trend — 규칙×빌드 분류 5종·미분석 null·insufficient_data·residual 제외."""
from __future__ import annotations

from pathlib import Path

from backend.services.prqa_rule_trend import _classify, compute_rule_trend


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


def _rcr(foo_r1: int, foo_r2: int, residual_vc: int = 0) -> str:
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
 </table>
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
