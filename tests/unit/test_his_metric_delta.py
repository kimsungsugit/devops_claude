"""HIS 메트릭(HMR) 함수 단위 delta — 밴드 판정 · 쌍 비교 · 캐시 · 정직성.

핵심 계약(회귀 시 사용자가 잘못된 원인을 지목하게 되는 것들):
- 값 변화와 **밴드 교차**는 다른 사건이다. 9→10은 값만, 10→11은 Pass→Conditional.
- 밴드가 정의되지 않은 메트릭(PATH·STMT 등)은 verdict None — Pass로 접으면 '기준 없음'이
  '통과'로 위장된다.
- HMR 부재는 '변화 없음'이 아니라 available:false — 빈 목록으로 위장 금지.
- 동일 basename이 여러 경로에 있으면 찍지 않고 ambiguous.
"""
from __future__ import annotations

import json

import pytest

from backend.services.his_metric_delta import (
    HIS_METRICS_CACHE_NAME,
    band_verdict,
    compute_function_metric_delta,
    find_latest_hmr_html,
    load_his_metrics_cached,
    load_pair_function_delta,
)

_HDR = "CALLS (STCAL)|RETURN (STM19)|v(G) (STCYC)|PATH (STPTH)|LEVEL (STMIF)|STMT (STST3)|PARAM (STPAR)|GOTO (STGTO)|CALLING (STM29)"


def _hmr_html(files: dict) -> str:
    """{파일경로: {함수명: [CALLS, RETURN, V_G, PATH, LEVEL, STMT, PARAM, GOTO, CALLING]}} → HMR HTML."""
    parts = ["<html><head><title>Helix QAC HIS Metrics Report</title></head><body>"]
    for path, fns in files.items():
        parts.append(f"<h3>File: {path}</h3>")
        for fn, vals in fns.items():
            head = "".join(f'<td align="right">{h}</td>' for h in _HDR.split("|"))
            body = "".join(f'<td align="right">{v}</td>' for v in vals)
            parts.append(
                f"<h4>Function: {fn}</h4><table>"
                f'<tr><td align="left">Metric</td>{head}</tr>'
                f'<tr><td align="left">Values</td>{body}</tr></table>'
            )
    parts.append("</body></html>")
    return "".join(parts)


def _write_build(tmp_path, name: str, files: dict):
    """빌드 루트 + report/ 구성. HMR은 빌드 루트 직하(KJPDS02_* 실제 배치)."""
    root = tmp_path / name
    reports = root / "report"
    reports.mkdir(parents=True)
    (root / f"{name}_HMR_01012026_120000.html").write_text(_hmr_html(files), encoding="utf-8")
    return root, reports


# ── 밴드 판정 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [("1", "Pass"), ("10", "Pass"), ("11", "Conditional"), ("30", "Conditional"), ("31", "Fail")],
)
def test_band_verdict_v_g_boundaries(value, expected):
    """회사 ST201 밴드 경계 — 10/11 과 30/31 이 등급 경계다."""
    assert band_verdict("V_G", value)["verdict"] == expected


def test_band_verdict_undefined_metric_is_none_not_pass():
    """PATH·STMT 는 회사 양식에 밴드가 없다 — None(기준 없음)이지 Pass가 아니다."""
    assert band_verdict("PATH", "999") is None
    assert band_verdict("STMT", "999") is None


def test_band_verdict_non_numeric_is_none():
    assert band_verdict("V_G", "n/a") is None
    assert band_verdict("V_G", None) is None


# ── 쌍 비교 ───────────────────────────────────────────────────────────────────

def test_added_removed_modified_classification():
    base = {"/w/a.c\x1fkeep()": {"V_G": "2"}, "/w/a.c\x1fgone()": {"V_G": "1"}}
    cur = {"/w/a.c\x1fkeep()": {"V_G": "5"}, "/w/a.c\x1fbrand_new()": {"V_G": "3"}}
    out = compute_function_metric_delta(cur, base)
    assert out["available"] is True
    assert out["totals"] == {"added": 1, "removed": 1, "modified": 1}
    kinds = {f["function"]: f["change"] for f in out["functions"]}
    assert kinds == {"brand_new()": "added", "keep()": "modified", "gone()": "removed"}


def test_unchanged_function_is_omitted():
    same = {"/w/a.c\x1fq()": {"V_G": "2", "STMT": "9"}}
    out = compute_function_metric_delta(dict(same), dict(same))
    assert out["functions"] == []
    assert out["totals"] == {"added": 0, "removed": 0, "modified": 0}


def test_band_crossing_reported_only_when_verdict_changes():
    """9→10 은 값만 변함(둘 다 Pass), 10→11 은 Pass→Conditional 교차."""
    within = compute_function_metric_delta(
        {"/w/a.c\x1ff()": {"V_G": "10"}}, {"/w/a.c\x1ff()": {"V_G": "9"}}
    )
    assert within["functions"][0]["metrics"][0]["base"] == "9"
    assert within["functions"][0]["band_crossings"] == []

    across = compute_function_metric_delta(
        {"/w/a.c\x1ff()": {"V_G": "11"}}, {"/w/a.c\x1ff()": {"V_G": "10"}}
    )
    cross = across["functions"][0]["band_crossings"]
    assert len(cross) == 1
    assert (cross[0]["from_verdict"], cross[0]["to_verdict"]) == ("Pass", "Conditional")
    assert cross[0]["st_id"] == "ST201"


def test_unbanded_metric_change_never_produces_crossing():
    """PATH 2→180 은 큰 변화지만 회사 밴드가 없어 등급 교차로 보고하면 안 된다."""
    out = compute_function_metric_delta(
        {"/w/a.c\x1ff()": {"PATH": "180"}}, {"/w/a.c\x1ff()": {"PATH": "2"}}
    )
    fn = out["functions"][0]
    assert fn["metrics"][0]["label"] == "PATH"
    assert fn["metrics"][0]["verdict"] is None
    assert fn["band_crossings"] == []


def test_worsened_functions_sort_before_value_only_changes():
    """등급이 나빠진 함수가 먼저 — 값만 흔들린 함수보다 판단 가치가 높다."""
    base = {"/w/a.c\x1fnoisy()": {"STMT": "3"}, "/w/a.c\x1fworse()": {"V_G": "10"}}
    cur = {"/w/a.c\x1fnoisy()": {"STMT": "40"}, "/w/a.c\x1fworse()": {"V_G": "31"}}
    out = compute_function_metric_delta(cur, base)
    assert out["functions"][0]["function"] == "worse()"


def test_added_function_metrics_have_no_base():
    """신규 함수는 base가 없다 — 0으로 채우면 '0에서 늘었다'는 허위 변화가 된다."""
    out = compute_function_metric_delta({"/w/a.c\x1fnew()": {"V_G": "4"}}, {})
    assert out["functions"][0]["metrics"][0]["base"] is None
    assert out["functions"][0]["metrics"][0]["cur"] == "4"


def test_max_functions_truncation_reports_omitted():
    cur = {f"/w/a.c\x1ff{i}()": {"V_G": "1"} for i in range(10)}
    out = compute_function_metric_delta(cur, {}, max_functions=3)
    assert len(out["functions"]) == 3
    assert out["omitted"] == 7
    assert out["totals"]["added"] == 10  # 총계는 절단과 무관


# ── 파일 필터 ─────────────────────────────────────────────────────────────────

def test_file_filter_matches_by_path_suffix():
    """RCR 상대경로(../../workspace/…)와 HMR 절대경로는 루트가 달라 suffix 매칭이 유일 경로."""
    cur = {
        "C:/j/workspace/P/source/Sources/SYS/uds.c\x1ff()": {"V_G": "5"},
        "C:/j/workspace/P/source/Sources/IF/other.c\x1fg()": {"V_G": "9"},
    }
    base = {
        "C:/j/workspace/P/source/Sources/SYS/uds.c\x1ff()": {"V_G": "2"},
        "C:/j/workspace/P/source/Sources/IF/other.c\x1fg()": {"V_G": "9"},
    }
    out = compute_function_metric_delta(
        cur, base, file="../../../../workspace/P/source/Sources/SYS/uds.c"
    )
    assert [f["function"] for f in out["functions"]] == ["f()"]


def test_file_filter_rejects_basename_only_collision():
    """x_uds.c 가 uds.c 로 잘못 매칭되면 남의 함수를 원인으로 지목하게 된다."""
    fns = {"C:/j/w/src/x_uds.c\x1fbad()": {"V_G": "5"}}
    out = compute_function_metric_delta(fns, fns, file="uds.c")
    assert out["available"] is False
    assert out["reason"] == "file_not_in_hmr"


def test_file_filter_ambiguous_refuses_to_guess():
    """APP/config.c 와 BOOT/config.c — 찍으면 틀린 함수를 원인으로 제시한다."""
    fns = {
        "C:/j/w/APP/config.c\x1fa()": {"V_G": "1"},
        "C:/j/w/BOOT/config.c\x1fb()": {"V_G": "1"},
    }
    out = compute_function_metric_delta(fns, fns, file="config.c")
    assert out["available"] is False
    assert out["reason"] == "file_ambiguous_in_hmr"


def test_file_new_in_current_build_still_resolves_but_flags_partial():
    """대상 빌드에만 있는 파일은 진행하되, '전부 신규'가 사실로 읽히면 안 된다.

    파일이 실제로 신설된 경우와 이전 빌드 분석 대상에서 빠진 경우를 HMR만으로는 구분할 수
    없다 — partial 플래그로 그 불확실성을 고지한다.
    """
    cur = {"C:/j/w/src/new.c\x1ff()": {"V_G": "3"}}
    out = compute_function_metric_delta(cur, {}, file="src/new.c")
    assert out["available"] is True
    assert out["totals"]["added"] == 1
    assert out["partial"] == "base_missing"


def test_file_gone_from_current_build_flags_partial():
    base = {"C:/j/w/src/old.c\x1ff()": {"V_G": "3"}}
    out = compute_function_metric_delta({}, base, file="src/old.c")
    assert out["partial"] == "cur_missing"
    assert out["totals"]["removed"] == 1


def test_both_sides_present_has_no_partial_flag():
    """양쪽 다 있으면 partial 키 자체가 없어야 한다 — 상시 경고는 경고를 무의미하게 만든다."""
    fns = {"C:/j/w/src/a.c\x1ff()": {"V_G": "3"}}
    out = compute_function_metric_delta({"C:/j/w/src/a.c\x1ff()": {"V_G": "4"}}, fns, file="src/a.c")
    assert "partial" not in out


# ── 로드 · 캐시 ───────────────────────────────────────────────────────────────

def test_find_latest_hmr_prefers_build_root_and_mtime(tmp_path):
    root, reports = _write_build(tmp_path, "b1", {"C:/w/a.c": {"f()": [1, 1, 2, 2, 1, 5, 0, 0, 1]}})
    assert find_latest_hmr_html(root, reports).name.endswith(".html")


def test_load_writes_and_reuses_cache(tmp_path):
    root, reports = _write_build(tmp_path, "b1", {"C:/w/a.c": {"f()": [1, 1, 2, 2, 1, 5, 0, 0, 1]}})
    first = load_his_metrics_cached(root, reports)
    assert first is not None and first["cache_hit"] is False
    assert (reports / HIS_METRICS_CACHE_NAME).exists()
    second = load_his_metrics_cached(root, reports)
    assert second["cache_hit"] is True
    assert second["functions"] == first["functions"]


def test_cache_invalidated_when_source_changes(tmp_path):
    """캐시 키는 결과 해시가 아니라 원본 시그니처 — 원본이 바뀌면 재파싱되어야 한다."""
    root, reports = _write_build(tmp_path, "b1", {"C:/w/a.c": {"f()": [1, 1, 2, 2, 1, 5, 0, 0, 1]}})
    load_his_metrics_cached(root, reports)
    hmr = find_latest_hmr_html(root, reports)
    hmr.write_text(_hmr_html({"C:/w/a.c": {"f()": [1, 1, 9, 2, 1, 5, 0, 0, 1]}}), encoding="utf-8")
    again = load_his_metrics_cached(root, reports)
    assert again["cache_hit"] is False
    assert list(again["functions"].values())[0]["V_G"] == "9"


def test_corrupt_cache_falls_back_to_reparse(tmp_path):
    root, reports = _write_build(tmp_path, "b1", {"C:/w/a.c": {"f()": [1, 1, 2, 2, 1, 5, 0, 0, 1]}})
    (reports / HIS_METRICS_CACHE_NAME).write_text("{not json", encoding="utf-8")
    out = load_his_metrics_cached(root, reports)
    assert out is not None and out["functions"]


def test_missing_hmr_returns_none_not_empty(tmp_path):
    """HMR 부재를 빈 dict로 위장하면 '메트릭 변화 0'이라는 허위 사실이 된다."""
    root = tmp_path / "empty"
    (root / "report").mkdir(parents=True)
    assert load_his_metrics_cached(root, root / "report") is None


def test_pair_delta_without_hmr_is_unavailable(tmp_path):
    root_a, rep_a = _write_build(tmp_path, "a", {"C:/w/a.c": {"f()": [1, 1, 2, 2, 1, 5, 0, 0, 1]}})
    root_b = tmp_path / "b"
    (root_b / "report").mkdir(parents=True)
    out = load_pair_function_delta(
        from_build_root=root_b, from_reports_dir=root_b / "report",
        to_build_root=root_a, to_reports_dir=rep_a,
    )
    assert out == {"available": False, "reason": "no_hmr"}


def test_pair_delta_end_to_end(tmp_path):
    """실제 사례 형태 — 신규 함수 1 + 복잡도가 밴드를 넘은 함수 1."""
    common = "C:/j/workspace/P/source/Sources/SYS/uds.c"
    root_b, rep_b = _write_build(tmp_path, "b123", {common: {"grow()": [3, 1, 10, 3, 3, 18, 0, 0, 0]}})
    root_a, rep_a = _write_build(tmp_path, "b124", {
        common: {"grow()": [4, 1, 11, 11, 4, 26, 0, 0, 0], "fresh()": [0, 1, 2, 2, 1, 12, 3, 0, 1]},
    })
    out = load_pair_function_delta(
        from_build_root=root_b, from_reports_dir=rep_b,
        to_build_root=root_a, to_reports_dir=rep_a,
        file="../../../workspace/P/source/Sources/SYS/uds.c",
    )
    assert out["available"] is True
    assert out["totals"] == {"added": 1, "removed": 0, "modified": 1}
    grow = next(f for f in out["functions"] if f["function"] == "grow()")
    assert grow["band_crossings"][0]["to_verdict"] == "Conditional"
    assert out["note"]


def test_cache_payload_is_json_roundtrippable(tmp_path):
    """캐시는 JSON — 키에 쓰는 US 구분자가 직렬화를 깨지 않아야 한다."""
    root, reports = _write_build(tmp_path, "b1", {"C:/w/a.c": {"f()": [1, 1, 2, 2, 1, 5, 0, 0, 1]}})
    load_his_metrics_cached(root, reports)
    payload = json.loads((reports / HIS_METRICS_CACHE_NAME).read_text(encoding="utf-8"))
    assert payload["src"]["parser_version"] >= 1
    assert any("\x1f" in k for k in payload["functions"])
