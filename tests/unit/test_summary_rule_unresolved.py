"""rule-unresolved-evidence — 미해소 규칙×파일 구간 증거(변경/무변경/정직 reason/counts 독립)."""
from __future__ import annotations

from pathlib import Path


def _rcr(foo_r1: int) -> str:
    """WorstRules(Rule-1.1) + FileStatus 최소 RCR — 파일 경로는 APP\\foo.c(정규화 후 APP/foo.c)."""
    return f"""<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Rule-1.1</th></tr>
  <tr><td align="left"><a href="APP\\foo.c" title="APP\\foo.c">foo.c</a></td><td>{foo_r1}</td></tr>
 </table>
 <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Violated Rules</th><th>Violation Count</th></tr>
  <tr><td align="left"><a href="APP\\foo.c" title="APP\\foo.c">foo.c</a></td><td>1</td><td>{foo_r1}</td></tr>
 </table>
</body></html>"""


_HMR_COLS = "CALLS (STCAL)|v(G) (STCYC)|LEVEL (STMIF)|CALLING (STM29)|STMT (STST3)"


def _hmr(fns: dict) -> str:
    """{함수명: [CALLS, V_G, LEVEL, CALLING, STMT]} → APP/foo.c 소속 최소 HMR."""
    head = "".join(f"<td>{h}</td>" for h in _HMR_COLS.split("|"))
    body = "<h3>File: C:/jenkins/workspace/P/APP/foo.c</h3>"
    for fn, vals in fns.items():
        cells = "".join(f"<td>{v}</td>" for v in vals)
        body += (
            f"<h4>Function: {fn}</h4><table>"
            f"<tr><td>Metric</td>{head}</tr><tr><td>Values</td>{cells}</tr></table>"
        )
    return f"<html><head><title>Helix QAC HIS Metrics Report</title></head><body>{body}</body></html>"


def _snap(
    tmp_path: Path, n: int, files: dict, *, rcr_r1: int | None = None, hmr: dict | None = None
) -> Path:
    root = tmp_path / f"build_{n}"
    (root / "report").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = root / "source" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    if rcr_r1 is not None:
        (root / f"X_RCR_0101202{n % 10}.html").write_text(_rcr(rcr_r1), encoding="utf-8")
    if hmr is not None:
        (root / f"X_HMR_0101202{n % 10}.html").write_text(_hmr(hmr), encoding="utf-8")
    return root


def _wire(monkeypatch, a_root: Path, b_root: Path):
    from backend.routers import summary_insight as si

    metas = [
        {"build_number": 125, "build_root": str(b_root), "reports_dir": str(b_root / "report")},
        {"build_number": 122, "build_root": str(a_root), "reports_dir": str(a_root / "report")},
    ]
    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta", lambda **k: metas)
    return si


_BODY = {"job_url": "http://j/", "rule": "Rule-1.1", "file": "APP/foo.c",
         "from_build": 122, "to_build": 125}


def test_changed_file_evidence_with_counts(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "int x = 42;\n"}, rcr_r1=6)
    b = _snap(tmp_path, 125, {"APP/foo.c": "int x = X_INIT;\n"}, rcr_r1=6)
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["file_changed"] is True
    assert "-int x = 42;" in r["diff"]["text"]
    assert r["counts"] == {"from": 6, "to": 6}          # RCR 카운트 조인(파일 경로 키 일치)
    assert "인과" in r["note"]                            # 서버 고정 note 상시


def test_unchanged_file_is_valid_evidence_not_failure(tmp_path, monkeypatch):
    # 무변경은 실패가 아니라 유효 증거 — '위반 잔존 + 구간 내 파일 미수정' 관측.
    a = _snap(tmp_path, 122, {"APP/foo.c": "same\n"}, rcr_r1=6)
    b = _snap(tmp_path, 125, {"APP/foo.c": "same\n"}, rcr_r1=6)
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["file_changed"] is False and r["diff"] is None
    assert r["counts"] == {"from": 6, "to": 6}


def test_counts_independent_of_missing_rcr(tmp_path, monkeypatch):
    # RCR 없음 → counts는 None(0 위장 금지) + counts_reason, diff 증거는 독립 반환.
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["file_changed"] is True
    assert r["counts"] == {"from": None, "to": None} and r["counts_reason"] == "no_rcr"


def test_honest_failure_reasons(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    # 스냅샷에 없는 파일
    r = si.summary_rule_unresolved_evidence({**_BODY, "file": "ghost.c"})
    assert r["available"] is False and r["reason"] == "file_not_in_snapshot"
    assert r["file_changed"] is None and r["diff"] is None
    # 캐시에 없는 빌드 / 파라미터 누락
    r2 = si.summary_rule_unresolved_evidence({**_BODY, "to_build": 999})
    assert r2["available"] is False and r2["reason"] == "build_not_cached"
    r3 = si.summary_rule_unresolved_evidence({"job_url": "http://j/"})
    assert r3["available"] is False and r3["reason"] == "params_required"


def test_ambiguous_basename_honest(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/config.c": "a\n", "BOOT/config.c": "b\n"})
    b = _snap(tmp_path, 125, {"APP/config.c": "a2\n", "BOOT/config.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence({**_BODY, "file": "config.c"})
    assert r["available"] is False and r["reason"] == "file_ambiguous_in_snapshot"


# ── 함수 단위 귀속(HMR) ────────────────────────────────────────────────────────
# RCR은 파일×규칙이 최상세라 규칙의 '줄'을 못 준다. 같은 빌드의 HMR은 함수 단위라
# '어느 함수가 새로 생겼고 무엇이 복잡해졌는가'까지는 실측으로 좁힐 수 있다.

def test_attribution_lists_changed_functions(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"}, rcr_r1=0,
              hmr={"keep()": [3, 3, 3, 0, 18]})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"}, rcr_r1=4,
              hmr={"keep()": [4, 7, 4, 0, 26], "fresh()": [0, 2, 1, 1, 12]})
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    attr = r["attribution"]
    assert attr["available"] is True
    assert attr["totals"] == {"added": 1, "removed": 0, "modified": 1}
    by_name = {f["function"]: f for f in attr["functions"]}
    assert by_name["fresh()"]["change"] == "added"
    # 신규 함수의 base는 None — 0으로 채우면 '0에서 늘었다'는 허위 변화가 된다.
    assert all(m["base"] is None for m in by_name["fresh()"]["metrics"])
    assert {m["metric"]: (m["base"], m["cur"]) for m in by_name["keep()"]["metrics"]}["V_G"] == ("3", "7")
    # 관측≠규칙 귀속 경계를 note로 상시 노출.
    assert "판정이 아닙니다" in attr["note"]


def test_attribution_band_crossing_surfaced(tmp_path, monkeypatch):
    """v(G) 10→11 은 회사 ST201 밴드에서 Pass→Conditional — 값 변화와 구분해 보고한다."""
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"}, hmr={"grow()": [1, 10, 1, 0, 5]})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"}, hmr={"grow()": [1, 11, 1, 0, 5]})
    si = _wire(monkeypatch, a, b)
    cross = si.summary_rule_unresolved_evidence(dict(_BODY))["attribution"]["functions"][0]["band_crossings"]
    assert len(cross) == 1
    assert (cross[0]["from_verdict"], cross[0]["to_verdict"]) == ("Pass", "Conditional")


def test_attribution_absent_hmr_is_honest_and_does_not_break_evidence(tmp_path, monkeypatch):
    """HMR이 없어도 diff·counts 본 응답은 그대로 — 부가 정보 실패가 카드를 죽이면 안 된다."""
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"}, rcr_r1=6)
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"}, rcr_r1=6)
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["diff"]["text"]
    assert r["attribution"] == {"available": False, "reason": "no_hmr"}


def test_file_rule_deltas_shows_all_changed_rules_for_the_file(tmp_path, monkeypatch):
    """카드는 규칙 하나를 보지만, 같은 파일에서 함께 변한 규칙을 알아야 원인을 좁힌다."""
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"}, rcr_r1=0)
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"}, rcr_r1=4)
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["file_rule_deltas"] == [{"rule": "Rule-1.1", "base": 0, "cur": 4, "delta": 4}]


def test_file_rule_deltas_empty_when_rcr_missing(tmp_path, monkeypatch):
    """RCR 결측은 counts_reason으로 이미 고지된다 — 여기서 0 delta를 지어내지 않는다."""
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    assert si.summary_rule_unresolved_evidence(dict(_BODY))["file_rule_deltas"] == []
