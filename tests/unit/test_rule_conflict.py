"""rule_conflict — 룰 상충 후보 판정과 애매한 지점.

핵심 계약(회귀 시 조용히 거짓말이 되는 것들):
- **상대 규칙이 규칙셋에 없으면 후보에서 빠진다**(음성 대조군). 안 빠지면 걸릴 수 없는
  규칙을 경고하는 헛경보가 된다.
- RCFInfo 부재는 '위험 없음'이 아니라 `ruleset_unknown` — 증거 부재를 통과로 접지 않는다.
- 규칙셋 변동 감지는 **관측(non-None)끼리** 이어야 한다 — 사이에 낀 미분석 빌드가
  변화를 삼키면 규칙셋 확장이 코드 악화로 보고된다(실측 KJPDS02_PV #116→#117→#120).
- 위반이 1건이라도 있으면 그 규칙은 적용된 것(위반이 곧 검사의 증거).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.rule_conflict import (
    _headroom_evidence,
    _measurement_ambiguities,
    _window_evidence,
    clear_conflict_table_cache,
    compute_rule_conflicts,
    is_generated_path,
    load_conflict_table,
    normalize_rule_id,
)


@pytest.fixture(autouse=True)
def _clear_table_cache():
    """테이블은 프로세스 캐시를 쓴다 — 테스트마다 임시 파일이 달라지므로 매번 비운다."""
    clear_conflict_table_cache()
    yield
    clear_conflict_table_cache()


# ── 규칙 ID 정규화 ──────────────────────────────────────────────────────────

def test_normalize_rule_id_absorbs_notation_variants():
    for raw in ("Rule-10.4", "Rule 10.4", "MISRA 10.4", "M3CM Rule-10.4", "10.4", "rule_10.4"):
        assert normalize_rule_id(raw) == "Rule-10.4", raw


def test_normalize_rule_id_keeps_non_numeric_schemes():
    # Secure C 등 다른 규칙 체계를 Rule-* 로 접으면 서로 다른 규칙이 같은 키로 뭉개진다.
    assert normalize_rule_id("C-INT-002") == "C-INT-002"
    assert normalize_rule_id("") == ""
    assert normalize_rule_id(None) == ""


# ── 지식 테이블 로딩 ────────────────────────────────────────────────────────

def _write_table(path: Path, conflicts: list, categories: dict | None = None) -> Path:
    path.write_text(json.dumps({
        "version": 1,
        "source_note": "테스트용 큐레이션",
        "rule_categories": categories or {},
        "conflicts": conflicts,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_conflict_table_missing_is_reported_not_silent(tmp_path):
    out = load_conflict_table(tmp_path / "nope.json")
    assert out["available"] is False and out["reason"] == "table_missing"
    assert out["conflicts"] == []  # 빈 목록을 '상충 없음'으로 위장하지 않는다(available로 구분)


def test_load_conflict_table_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_conflict_table(p)["reason"] == "table_unreadable"


def test_load_conflict_table_normalizes_and_drops_entries_without_fixing(tmp_path):
    p = _write_table(tmp_path / "t.json", [
        {"id": "ok", "when_fixing": ["Rule 10.4"], "may_violate": ["MISRA 10.8"]},
        {"id": "no-fixing", "when_fixing": [], "may_violate": ["Rule-2.2"]},
        {"when_fixing": ["Rule-1.1"]},  # id 없음 — 후보 식별 불가
    ], categories={"Rule 10.4": "required"})
    out = load_conflict_table(p)
    assert [c["id"] for c in out["conflicts"]] == ["ok"]
    assert out["conflicts"][0]["when_fixing"] == ["Rule-10.4"]
    assert out["conflicts"][0]["may_violate"] == ["Rule-10.8"]
    assert out["rule_categories"] == {"Rule-10.4": "required"}


def test_shipped_table_is_valid_and_categories_cover_referenced_rules():
    """저장소에 담긴 실제 테이블 — 참조 규칙이 전부 등급표에 있어야 예외 판단이 가능하다."""
    out = load_conflict_table()
    assert out["available"] is True and out["conflicts"], "실 테이블이 로드되지 않았다"
    cats = out["rule_categories"]
    referenced = set()
    for c in out["conflicts"]:
        referenced |= set(c["when_fixing"]) | set(c["may_violate"])
    assert not (referenced - set(cats)), f"등급 미기재 규칙: {sorted(referenced - set(cats))}"
    assert len({c["id"] for c in out["conflicts"]}) == len(out["conflicts"]), "id 중복"


# ── 자동 생성 판별 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,expected", [
    ("../src/Generated_Code/PP1_BUZZER_PWM.c", True),
    ("src\\generated\\a.c", True),
    ("src/LIN/lin_cfg.h", True),          # 파일명 규칙(_cfg)
    ("src/APP/Ap_MotorCtrl_PDS.c", False),
    ("src/config/main.c", False),          # 'config' 는 생성 디렉토리가 아니다
    ("", False),
])
def test_is_generated_path(path, expected):
    assert is_generated_path(path) is expected


# ── 증거 산출 (순수 함수) ───────────────────────────────────────────────────

def test_window_evidence_requires_same_file_and_same_window():
    trend_rules = {
        "Rule-10.4": {"decreased_files": [
            {"path": "src/a.c", "from_build": 10, "to_build": 11, "delta": -3},
            {"path": "src/b.c", "from_build": 10, "to_build": 11, "delta": -1},
        ]},
        "Rule-10.8": {"increased_files": [
            {"path": "src/a.c", "from_build": 10, "to_build": 11, "delta": 2},   # 같은 파일·구간 → 채택
            {"path": "src/b.c", "from_build": 11, "to_build": 12, "delta": 5},   # 구간 불일치 → 제외
            {"path": "src/z.c", "from_build": 10, "to_build": 11, "delta": 9},   # 파일 불일치 → 제외
        ]},
    }
    out = _window_evidence(trend_rules, ["Rule-10.4"], ["Rule-10.8"])
    assert [(e["file"], e["rule_up"]) for e in out] == [("src/a.c", "Rule-10.8")]
    assert out[0]["delta_down"] == -3 and out[0]["delta_up"] == 2


def test_headroom_evidence_uses_distance_not_exact_boundary():
    """⚠ 여유를 '+1이면 밴드가 바뀌나'로만 보면 실측에서 아무것도 안 걸린다.

    실제 준수 리팩터링은 복잡도를 1단이 아니라 2~5단 올린다. 임계 이하 거리를 재야
    v(G)=9 같은 함수(HDPDM01 s_LinTx_DTC 실사례)가 잡힌다.
    """
    # LEVEL 밴드는 1~5 Pass 라 여유가 금방 좁아진다 — V_G 축 확인이 LEVEL 에 오염되지
    # 않도록 V_G 대상 함수들의 LEVEL 은 넉넉히(1 → 여유 5, 임계 밖) 둔다.
    functions = {
        "c:/w/src/a.c\x1ftight()": {"V_G": "10", "LEVEL": "1"},    # V_G 여유 1
        "c:/w/src/a.c\x1fnear()": {"V_G": "9", "LEVEL": "1"},      # V_G 여유 2 — 구 구현은 놓쳤다
        "c:/w/src/a.c\x1froomy()": {"V_G": "4", "LEVEL": "1"},     # V_G 여유 7 → 임계 밖
        "c:/w/src/a.c\x1fnesting()": {"V_G": "2", "LEVEL": "5"},   # LEVEL 여유 1
    }
    out = _headroom_evidence(functions, ["src/a.c"], ["V_G"])
    # 여유가 작은 것부터 — 상한에 잘려도 가장 위험한 함수가 남는다.
    assert [(e["function"], e["headroom"]) for e in out] == [("tight()", 1), ("near()", 2)]
    assert out[0]["verdict"] == "Pass" and out[0]["next_verdict"] == "Conditional"
    # metric_risk 가 LEVEL 이면 중첩 경계 함수가 잡힌다 — 어떤 메트릭을 미는 수정인지가 기준.
    assert [e["function"] for e in _headroom_evidence(functions, ["src/a.c"], ["LEVEL"])] == ["nesting()"]
    # 밴드가 정의되지 않은 메트릭은 판정하지 않는다(임계값을 지어내면 없던 위반이 생긴다).
    assert _headroom_evidence(functions, ["src/a.c"], ["STMT"]) == []
    # 임계를 좁히면 경계에 정확히 붙은 것만 남는다(호출측이 정한다).
    assert [e["function"] for e in _headroom_evidence(functions, ["src/a.c"], ["V_G"], threshold=1)] \
        == ["tight()"]


def test_band_headroom_skips_same_verdict_bands():
    """V_G 11~20 과 21~30 은 **둘 다 Conditional** — 20→21 을 '나빠짐'으로 세면 안 된다."""
    from backend.services.his_metric_delta import band_headroom

    assert band_headroom("V_G", 10)["headroom"] == 1      # Pass 상한 → 11에서 Conditional
    assert band_headroom("V_G", 20)["headroom"] == 11     # 21은 여전히 Conditional, Fail은 31
    assert band_headroom("V_G", 20)["next_verdict"] == "Fail"
    assert band_headroom("V_G", 31) is None               # 이미 최악 밴드 — 여유 0이 아니라 개념 부재
    assert band_headroom("STMT", 100) is None             # 밴드 미정의
    assert band_headroom("V_G", "nan") is None


def test_measurement_ambiguity_ruleset_change_spans_unanalyzed_build():
    """미분석 빌드(None)를 사이에 두고도 규칙셋 변동을 잡아야 한다 — 실측 회귀 지점."""
    trend = {
        "builds": [{"build_number": 116}, {"build_number": 117}, {"build_number": 120}],
        "ruleset_sizes": [104, None, 242],
        "rules": [{"rule": "C-POS-012", "counts": [None, None, 92]}],
        "residual": {"counts": [0, None, 0]},
    }
    out = _measurement_ambiguities(trend, {}, {}, set(), {"Rule-1.1"})
    change = [m for m in out if m["kind"] == "ruleset_change"]
    assert len(change) == 1
    assert change[0]["from_build"] == 116 and change[0]["to_build"] == 120
    assert change[0]["from_size"] == 104 and change[0]["to_size"] == 242
    assert "C-POS-012" in change[0]["affected_rules"]


def test_measurement_ambiguity_reports_unattributed_and_missing_ruleset():
    trend = {"builds": [{"build_number": 5}], "ruleset_sizes": [None], "rules": [
        {"rule": "Rule-8.6", "classification_reason": "insufficient_observations"},
    ], "residual": {"counts": [11]}}
    per_file = {"RCMA": {"Rule-8.6": 99}, "src/a.c": {"Rule-8.6": 6}}
    details = {"filestatus_total_vc": 577, "violations_attributed_total": 491}
    out = _measurement_ambiguities(trend, details, per_file, {"RCMA"}, None)
    kinds = {m["kind"] for m in out}
    assert {"unattributed", "ruleset_unknown", "single_observation", "residual", "file_unattributed"} <= kinds
    un = next(m for m in out if m["kind"] == "unattributed")
    assert un["rules"][0] == {"rule": "Rule-8.6", "unattributed": 99, "total": 105}
    gap = next(m for m in out if m["kind"] == "file_unattributed")
    assert gap["gap"] == 86


# ── compute_rule_conflicts (캐시 빌드 픽스처) ───────────────────────────────

_RCF_HEAD = """
 <div class="sec"><h3><a name="RCFInfo">Rule Configuration Status</a></h3></div>
 <div class="subsec"><h5>M3CM</h5></div>
 <table border="0">"""
_RCF_TAIL = """
 </table>"""


def _rcf(rules: dict) -> str:
    """RCFInfo 블록 — {규칙: enabled bool}. 빈 dict 면 블록 자체를 만들지 않는다."""
    if not rules:
        return ""
    rows = "".join(
        f'\n  <tr><td></td><td title="{r} desc">{r}</td>'
        f'<td>{"enabled" if on else "disabled"}</td></tr>'
        for r, on in rules.items()
    )
    return _RCF_HEAD + rows + _RCF_TAIL


def _rcr(counts: dict, rcf_rules: dict | None = None, *, path: str = "src/a.c") -> str:
    """WorstRules + FileStatus 최소 RCR. counts = {규칙: 건수}."""
    rules = list(counts)
    header = "".join(f"<th>{r}</th>" for r in rules)
    cells = "".join(f"<td>{counts[r]}</td>" for r in rules)
    vc = sum(counts.values())
    href = path.replace("/", "\\")
    return f"""<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
 <table border="1">
  <tr><th>Files</th>{header}</tr>
  <tr><td align="left"><a href="..\\{href}" title="..\\{href}">{path.rsplit('/', 1)[-1]}</a></td>{cells}</tr>
 </table>
 <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Active Diagnostics</th><th>Violated Rules</th><th>Violation Count</th><th>Compliance Index</th></tr>
  <tr><td align="left"><a href="..\\{href}" title="..\\{href}">{path.rsplit('/', 1)[-1]}</a></td><td>1</td><td>{len(rules)}</td><td>{vc}</td><td>90.00%</td></tr>
 </table>{_rcf(rcf_rules or {})}
</body></html>"""


def _mk_build(root: Path, n: int, rcr_html: str) -> None:
    b = root / "jenkins" / "http_j_job_X" / f"build_{n}"
    (b / "report").mkdir(parents=True)
    (b / f"X_RCR_010120{n:02d}.html").write_text(rcr_html, encoding="utf-8")


_JOB = "http://j/job/X"


def _table(tmp_path: Path) -> Path:
    return _write_table(tmp_path / "conflicts.json", [
        {
            "id": "cast-cascade", "when_fixing": ["Rule-10.4"], "may_violate": ["Rule-10.8"],
            "kind": "fix_induces", "mechanism": "캐스팅이 복합식에 걸린다",
            "resolutions": ["단항 피연산자에 캐스팅"], "confidence": "high",
        },
        {
            "id": "needs-disabled-rule", "when_fixing": ["Rule-10.4"], "may_violate": ["Rule-99.9"],
            "kind": "fix_induces", "mechanism": "규칙셋에 없는 상대", "confidence": "low",
        },
    ], categories={"Rule-10.4": "required", "Rule-10.8": "required", "Rule-99.9": "advisory"})


def test_conflict_detected_as_cooccurrence_when_both_rules_hit_same_file(tmp_path):
    cache = tmp_path / "cache"
    rcf = {"Rule-10.4": True, "Rule-10.8": True}
    _mk_build(cache, 10, _rcr({"Rule-10.4": 4, "Rule-10.8": 2}, rcf))
    _mk_build(cache, 11, _rcr({"Rule-10.4": 4, "Rule-10.8": 2}, rcf))

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    assert out["available"] is True
    ids = [c["id"] for c in out["conflicts"]]
    assert ids == ["cast-cascade"], "규칙셋에 없는 상대(Rule-99.9)를 참조하는 항목은 빠져야 한다"
    c = out["conflicts"][0]
    assert c["tier"] == "cooccurrence"
    assert c["ruleset_unknown"] is False
    assert [m["rule"] for m in c["fixing"]] == ["Rule-10.4"]
    assert c["fixing"][0]["category"] == "required"
    assert c["evidence"]["cooccurrence"][0]["fixing_counts"] == {"Rule-10.4": 4}
    assert out["by_rule"]["Rule-10.4"] == ["cast-cascade"]
    assert out["ambiguities"]["conflict"][0]["id"] == "cast-cascade"
    # 정상 측정이면 null — 값이 있으면 '상충 없음'이 아니라 위반 표를 못 읽은 것이다.
    assert out["latest_rcr_reason"] is None
    # 동시 위반 증거가 있으면 지침 생성 가능 — 프론트가 버튼을 내기 전에 아는 근거.
    assert c["advice"] == {"available": True, "reason": None}
    # 이 상충은 metric_risk 가 없다 → 메트릭 축은 '해당 없음'(못 봄이 아니다).
    assert c["metric_axis"]["applicable"] is False


def test_metric_axis_distinguishes_not_applicable_from_unmeasured(tmp_path):
    """metric_headroom 이 비었을 때 '여유 있음'과 '못 봄'이 구분돼야 한다.

    RCR 축엔 latest_rcr_reason 을 달아 놓고 메트릭 축을 빼놓은 게 직전 라운드의 비대칭이었다.
    이 픽스처엔 HMR 이 없으므로 metric_risk 를 가진 상충은 checked=False 여야 한다.
    """
    cache = tmp_path / "cache"
    rcf = {"Rule-15.5": True, "Rule-15.4": True}
    _mk_build(cache, 10, _rcr({"Rule-15.5": 3}, rcf))
    _mk_build(cache, 11, _rcr({"Rule-15.5": 3}, rcf))
    table = _write_table(tmp_path / "t2.json", [{
        "id": "single-exit", "when_fixing": ["Rule-15.5"], "may_violate": ["Rule-15.4"],
        "kind": "fix_induces", "metric_risk": ["LEVEL", "V_G"], "confidence": "high",
    }], categories={"Rule-15.5": "advisory", "Rule-15.4": "advisory"})

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=table)
    assert out["metrics"]["available"] is False and out["metrics"]["reason"] == "no_hmr"
    axis = out["conflicts"][0]["metric_axis"]
    assert axis["applicable"] is True and axis["checked"] is False and axis["reason"] == "no_hmr"
    # 증거 부재를 '여유 있음'으로 접지 않았다 — headroom 은 비어 있지만 사유가 함께 있다.
    assert out["conflicts"][0]["evidence"]["metric_headroom"] == []


def test_advice_reports_cross_module_only_when_all_violations_unattributed(tmp_path):
    """Rule-8.6 99/99 처럼 위반이 전부 RCMA 면 파일 증거는 **원리적으로** 없다.

    '못 찾음'(no_code_evidence)으로 보고하면 사용자는 스냅샷 재수집을 시도한다 —
    실제로는 도구 한계라 아무리 재수집해도 안 나온다.
    """
    cache = tmp_path / "cache"
    rcf = {"Rule-10.4": True, "Rule-10.8": True}
    # RCMA(파일 귀속 없음)에만 위반이 있는 RCR — path 없는 pseudo 행.
    html = _rcr({"Rule-10.4": 9}, rcf, path="RCMA")
    _mk_build(cache, 10, html)
    _mk_build(cache, 11, html)

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    c = next(c for c in out["conflicts"] if c["id"] == "cast-cascade")
    assert c["advice"]["reason"] == "cross_module_only"
    assert c["advice"]["unattributed"] == 9 and c["advice"]["total"] == 9
    # 파일 귀속이 없으니 메트릭 축도 함수를 특정할 수 없다(HMR 유무와 별개 사유).
    assert c["evidence"]["cooccurrence"] == []


def test_advice_unavailable_when_all_evidence_is_cross_module(tmp_path):
    """증거가 **있어도** 전부 모듈 간 집계면 스냅샷 발췌는 못 만든다.

    이걸 available:True 로 두면 버튼을 눌러야만 실패를 알고, 그때 나오는 사유도 틀린다
    (증거 수집기가 pseudo 항목을 걸러내므로 'no_code_evidence' 로 떨어진다).
    """
    cache = tmp_path / "cache"
    rcf = {"Rule-10.4": True, "Rule-10.8": True}
    # 두 규칙이 **RCMA 안에서** 함께 위반 → cooccurrence 는 잡히지만 scope=cross_module.
    html = _rcr({"Rule-10.4": 9, "Rule-10.8": 4}, rcf, path="RCMA")
    _mk_build(cache, 10, html)
    _mk_build(cache, 11, html)

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    c = next(c for c in out["conflicts"] if c["id"] == "cast-cascade")
    assert c["evidence"]["cooccurrence"], "동시 위반 관측 자체는 있어야 한다(버리지 않는다)"
    assert all(e.get("scope") == "cross_module" for e in c["evidence"]["cooccurrence"])
    assert c["advice"]["available"] is False and c["advice"]["reason"] == "cross_module_only"


def test_absent_counterpart_rule_is_filtered_with_reason(tmp_path):
    """음성 대조군 — 상대 규칙이 규칙셋에 있지만 위반이 없어도 후보는 남고,
    아예 없으면(=검사 안 함) 빠진다. 빠진 사유는 남는다."""
    cache = tmp_path / "cache"
    # Rule-10.8 은 규칙셋에 존재(위반 0), Rule-99.9 는 아예 없음.
    rcf = {"Rule-10.4": True, "Rule-10.8": True}
    _mk_build(cache, 10, _rcr({"Rule-10.4": 4}, rcf))
    _mk_build(cache, 11, _rcr({"Rule-10.4": 4}, rcf))

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    ids = [c["id"] for c in out["conflicts"]]
    assert ids == ["cast-cascade"]
    c = out["conflicts"][0]
    assert c["tier"] == "ruleset_active", "위반 0 + 규칙 활성 = 예고 등급"
    assert c["risk_filtered"] == []


def test_disabled_counterpart_rule_removes_candidate(tmp_path):
    cache = tmp_path / "cache"
    rcf = {"Rule-10.4": True, "Rule-10.8": False}  # 상대가 비활성 → 그 규칙으론 안 걸린다
    _mk_build(cache, 10, _rcr({"Rule-10.4": 4}, rcf))
    _mk_build(cache, 11, _rcr({"Rule-10.4": 4}, rcf))

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    assert out["conflicts"] == []
    assert out["ruleset"]["available"] is True
    # 제외는 침묵하지 않는다 — "왜 이 상충이 안 보이나"에 답할 근거를 남긴다.
    excluded = {e["id"]: e for e in out["table"]["excluded"]}
    assert set(excluded) == {"cast-cascade", "needs-disabled-rule"}
    assert excluded["cast-cascade"]["inactive"] == ["Rule-10.8"]
    assert excluded["cast-cascade"]["reason"] == "counterpart_inactive"
    # 대조 결과가 자립한다: 표시 + 위반없음 + 성립불가 = 테이블 전체
    assert len(out["conflicts"]) + out["table"]["skipped_no_violation"] + len(out["table"]["excluded"]) \
        == out["table"]["total"]


def test_missing_rcfinfo_degrades_to_ruleset_unknown(tmp_path):
    """RCFInfo가 없으면 '위험 없음'이 아니라 '확인 못 함'이다."""
    cache = tmp_path / "cache"
    _mk_build(cache, 10, _rcr({"Rule-10.4": 4}, {}))
    _mk_build(cache, 11, _rcr({"Rule-10.4": 4}, {}))

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    assert out["ruleset"] == {
        "available": False, "enabled_count": None, "source_build": None, "reason": "no_rcfinfo",
    }
    assert {c["tier"] for c in out["conflicts"]} == {"ruleset_unknown"}
    assert all(c["ruleset_unknown"] for c in out["conflicts"])
    assert any(m["kind"] == "ruleset_unknown" for m in out["ambiguities"]["measurement"])
    # 상대 규칙 활성 여부를 모르므로 걸러내지 않는다 — 둘 다 후보로 남긴다.
    assert {c["id"] for c in out["conflicts"]} == {"cast-cascade", "needs-disabled-rule"}


def test_violation_counts_as_applied_even_without_rcfinfo_entry(tmp_path):
    """위반이 있으면 그 규칙은 적용된 것 — RCFInfo에 없다고 후보를 접지 않는다."""
    cache = tmp_path / "cache"
    # RCFInfo에는 Rule-10.4만 기재되고 Rule-10.8은 빠져 있으나, 위반은 둘 다 있다.
    rcf = {"Rule-10.4": True}
    _mk_build(cache, 10, _rcr({"Rule-10.4": 4, "Rule-10.8": 3}, rcf))
    _mk_build(cache, 11, _rcr({"Rule-10.4": 4, "Rule-10.8": 3}, rcf))

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    assert [c["id"] for c in out["conflicts"]] == ["cast-cascade"]
    assert out["conflicts"][0]["tier"] == "cooccurrence"


def test_generated_code_violations_are_separated(tmp_path):
    cache = tmp_path / "cache"
    rcf = {"Rule-10.4": True, "Rule-10.8": True}
    html = _rcr({"Rule-10.4": 4}, rcf, path="src/Generated_Code/gen.c")
    _mk_build(cache, 10, html)
    _mk_build(cache, 11, html)

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=_table(tmp_path))
    gen = out["ambiguities"]["generated"]
    assert len(gen) == 1 and gen[0]["basis"] == "path" and gen[0]["violations"] == 4
    assert out["ambiguities"]["generated_unprobed"] == 0


def test_generated_marker_probe_limit_is_reported_not_silent(monkeypatch, tmp_path):
    """마커 검사 상한을 넘기면 '자동 생성 없음'이 아니라 '확인 못 함'으로 고지한다."""
    import backend.services.rule_conflict as rc

    monkeypatch.setattr(rc, "MAX_MARKER_PROBES", 1)
    per_file = {f"src/m{i}.c": {"Rule-10.4": 1} for i in range(4)}
    items, unprobed = rc._generated_ambiguities(per_file, set(), None)
    assert items == []            # 경로 규칙에도 안 걸리고 스냅샷도 없다
    assert unprobed == 3          # 1건만 검사하고 나머지는 미확인 — 침묵하지 않는다


def test_missing_table_reports_unavailable_not_empty(tmp_path):
    cache = tmp_path / "cache"
    _mk_build(cache, 10, _rcr({"Rule-10.4": 4}, {"Rule-10.4": True}))
    _mk_build(cache, 11, _rcr({"Rule-10.4": 4}, {"Rule-10.4": True}))

    out = compute_rule_conflicts(job_url=_JOB, cache_root=cache, table_path=tmp_path / "absent.json")
    assert out["available"] is False and out["reason"] == "table_missing"


def test_no_cached_build_is_reported(tmp_path):
    out = compute_rule_conflicts(
        job_url=_JOB, cache_root=tmp_path / "empty", table_path=_table(tmp_path),
    )
    assert out["available"] is False and out["reason"] == "no_cached_build"
