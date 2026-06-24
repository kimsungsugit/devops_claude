"""SCM(cloudium) IT 함수콜 보강 — _aggregate_it_function_calls 단위 테스트 (2026-06-24).

AggregateCoverage(구문/분기/MC-DC) 리포트에 없는 함수콜(Function Called) 커버리지를 VectorCAST
Metric report HTML에서 추출해 it_metrics.grand_totals를 채우는 로직 검증. 그동안 함수콜은 Jenkins
빌드 산출물에서만 나왔으나 SwITCV 빌더가 쓰는 parse_hmr_html을 재사용해 SCM 경로에서도 제공한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.routers.jenkins import _aggregate_it_function_calls  # noqa: E402


def _hmr(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """합성 VectorCAST Metric report HTML — (unit, fn, complexity, functions_metric, calls_metric)."""
    body = "\n".join(
        f"<tr><td class='col_unit'>{u}</td><td class='col_subprogram'>{fn}</td>"
        f"<td class='col_complexity'>{c}</td><td class='col_metric'>{f}</td>"
        f"<td class='col_metric'>{cl}</td></tr>"
        for u, fn, c, f, cl in rows
    )
    return (
        "<html><body><table><thead><tr>"
        "<th class='col_unit'>Unit</th><th class='col_subprogram'>Subprogram</th>"
        "<th class='col_complexity'>Complexity</th><th class='col_metric'>Functions</th>"
        "<th class='col_metric'>Function Calls</th></tr></thead>"
        f"<tbody>{body}</tbody></table></body></html>"
    ).encode("utf-8")


def test_grand_totals_function_calls_and_functions():
    """함수콜·함수 진입 둘 다 전 함수 합산되어 grand_totals를 만든다."""
    html = _hmr([
        ("bats.c", "BATS_Init", "1", "1 / 1 (100%)", "5 / 10 (50%)"),
        ("bats.c", "BATS_Update", "2", "1 / 1 (100%)", "8 / 8 (100%)"),
        ("vehicle.c", "g_Check", "3", "0 / 1 (0%)", "3 / 7 (42%)"),
    ])
    grand, by_name = _aggregate_it_function_calls([html])
    # 함수콜: (5+8+3)/(10+8+7) = 16/25
    assert grand["function_calls"] == {"covered": 16, "total": 25, "rate": round(16 / 25, 4)}
    # 함수 진입: (1+1+0)/(1+1+1) = 2/3
    assert grand["functions"]["covered"] == 2
    assert grand["functions"]["total"] == 3
    # entries 병합용 함수명 map
    assert by_name["BATS_Init"] == {"covered": 5, "total": 10}
    assert by_name["BATS_Update"] == {"covered": 8, "total": 8}


def test_multiple_reports_merge():
    """여러 Metric report(APP+BOOT 등) HTML을 합산한다."""
    a = _hmr([("a.c", "fa", "1", "1 / 1 (100%)", "2 / 4 (50%)")])
    b = _hmr([("b.c", "fb", "1", "1 / 1 (100%)", "3 / 3 (100%)")])
    grand, by_name = _aggregate_it_function_calls([a, b])
    assert grand["function_calls"] == {"covered": 5, "total": 7, "rate": round(5 / 7, 4)}
    assert set(by_name) == {"fa", "fb"}


def test_leaf_no_calls_omits_function_calls_key():
    """call 없는 leaf(빈 cell, total_calls=0)만 있으면 function_calls 키 생략(0% 위장 금지)."""
    html = _hmr([("a.c", "leaf", "1", "1 / 1 (100%)", "")])
    grand, _by = _aggregate_it_function_calls([html])
    assert "function_calls" not in grand   # fc_tot=0
    assert grand["functions"]["total"] == 1  # functions는 채워짐


def test_empty_and_non_metric_html_graceful():
    """빈 리스트/비-metric HTML은 빈 dict (graceful)."""
    grand, by_name = _aggregate_it_function_calls([])
    assert grand == {} and by_name == {}
    grand2, _ = _aggregate_it_function_calls([b"<html>not a metric report</html>"])
    assert grand2 == {}
