"""VectorCAST aggregate metrics report (HMR) parser 단위 테스트 (60차 F6-C).

합성 HTML로 양식 시뮬레이션 + parse_hmr_html 검증. 라이브 검증은
``.codex_tmp/round_60_local_build/inspect_hmr_format.py``에서 별도 수행
(Jenkins_PDSM_UT/IT_metrics_report.html 실제 파일).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.vcast_hmr_parser import (  # noqa: E402
    HTML_MAX_BYTES,
    parse_hmr_html,
)


def _build_hmr_html(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """합성 HMR HTML — VectorCAST aggregate metrics report 양식 시뮬레이션.

    Args:
        rows: (unit_file, function_name, complexity, functions_metric, calls_metric) 튜플 list.
            metric format: 'X / Y (Z%)' 또는 '' (빈 cell = leaf function).
    """
    body_rows = []
    for unit, fn, complexity, fns, calls in rows:
        body_rows.append(
            f"<tr>"
            f"<td class='col_unit'>{unit}</td>"
            f"<td class='col_subprogram'>{fn}</td>"
            f"<td class='col_complexity'>{complexity}</td>"
            f"<td class='col_metric'>{fns}</td>"
            f"<td class='col_metric'>{calls}</td>"
            f"</tr>"
        )
    body = "\n".join(body_rows)
    html = (
        "<html><body><table>"
        "<thead><tr>"
        "<th class='col_unit'>Unit</th>"
        "<th class='col_subprogram'>Subprogram</th>"
        "<th class='col_complexity'>Complexity</th>"
        "<th class='col_metric'>Functions</th>"
        "<th class='col_metric'>Function Calls</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table></body></html>"
    )
    return html.encode("utf-8")


class TestVcastHmrParser:
    def test_empty_bytes_returns_ok_false(self):
        """T424-1: 빈 bytes는 ok=False + warning emit."""
        result = parse_hmr_html(b"")
        assert result.ok is False
        assert any("비어있음" in w for w in result.parse_warnings)
        assert result.metrics == {}

    def test_oversize_rejected(self):
        """T424-2: HTML_MAX_BYTES 초과 시 DoS 방지 — ok=False."""
        big = b"<html>" + (b"x" * (HTML_MAX_BYTES + 1)) + b"</html>"
        result = parse_hmr_html(big)
        assert result.ok is False
        assert any("DoS 방지" in w for w in result.parse_warnings)

    def test_basic_function_calls_extraction(self):
        """T424-3: 정상 양식 — Function Calls metric 정확 추출."""
        html_bytes = _build_hmr_html([
            ("bats.c", "BATS_Init", "1", "1 / 1 (100%)", "5 / 10 (50%)"),
            ("bats.c", "BATS_Update", "2", "1 / 1 (100%)", "8 / 8 (100%)"),
            ("vehicle.c", "g_SystemStatusCheck", "3", "1 / 1 (100%)", "3 / 7 (42%)"),
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        assert len(result.metrics) == 3
        # BATS_Init
        m = result.metrics["BATS_Init"]
        assert m.covered_calls == 5
        assert m.total_calls == 10
        assert m.coverage_pct == 50.0
        assert m.unit_file == "bats.c"
        # g_SystemStatusCheck
        m2 = result.metrics["g_SystemStatusCheck"]
        assert m2.covered_calls == 3
        assert m2.total_calls == 7
        assert m2.unit_file == "vehicle.c"

    def test_leaf_function_empty_calls_cell_skipped(self):
        """T424-4: 빈 Function Calls cell (leaf) + 빈 Functions cell 동시 → row skip."""
        html_bytes = _build_hmr_html([
            ("util.c", "util_helper", "1", "", ""),  # 둘 다 비어있음 → skip
            ("util.c", "util_main", "2", "1 / 1 (100%)", "3 / 3 (100%)"),
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        # leaf row는 skip — util_main만 추출
        assert "util_helper" not in result.metrics
        assert "util_main" in result.metrics

    def test_unit_file_inheritance(self):
        """T424-5: 같은 파일 내 row의 unit_file이 비어있으면 직전 row 값 상속."""
        html_bytes = _build_hmr_html([
            ("main.c", "main", "5", "1 / 1 (100%)", "10 / 10 (100%)"),
            ("", "main_helper", "2", "1 / 1 (100%)", "4 / 4 (100%)"),  # unit 빈 → main.c 상속
            ("", "main_init", "1", "1 / 1 (100%)", "2 / 2 (100%)"),
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        assert result.metrics["main_helper"].unit_file == "main.c"
        assert result.metrics["main_init"].unit_file == "main.c"

    def test_no_metric_table_returns_ok_false(self):
        """T424-6: col_metric 없는 HTML → metric 0건 + ok=False."""
        html_bytes = b"<html><body><p>No table here</p></body></html>"
        result = parse_hmr_html(html_bytes)
        assert result.ok is False
        assert any("metric 0건" in w for w in result.parse_warnings)


class TestVcastHmrParserAmbiguous:
    """F6 자체평가 Round 1 C2: 함수명 중복 silent wrong-pick 차단."""

    def test_duplicate_function_name_collected_in_by_name(self):
        """C2-1: 같은 함수명 다른 unit_file 2건 — metrics_by_name에 2 entry 보존."""
        html_bytes = _build_hmr_html([
            ("bats.c", "Init", "1", "1 / 1 (100%)", "10 / 10 (100%)"),
            ("vehicle.c", "Init", "1", "1 / 1 (100%)", "2 / 8 (25%)"),
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        # metrics는 backward-compat (첫 매칭만)
        assert "Init" in result.metrics
        assert result.metrics["Init"].unit_file == "bats.c"
        # metrics_by_name은 caller 권장 API — 모든 매칭 보존
        candidates = result.metrics_by_name["Init"]
        assert len(candidates) == 2
        unit_files = {c.unit_file for c in candidates}
        assert unit_files == {"bats.c", "vehicle.c"}

    def test_unique_function_name_single_entry_in_by_name(self):
        """C2-2: 함수명 unique 시 metrics_by_name list 길이 1."""
        html_bytes = _build_hmr_html([
            ("util.c", "util_func", "2", "1 / 1 (100%)", "5 / 5 (100%)"),
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        assert len(result.metrics_by_name["util_func"]) == 1

    def test_to_dict_reports_ambiguous_count(self):
        """C2-3: to_dict() 응답에 ambiguous_count 포함."""
        html_bytes = _build_hmr_html([
            ("a.c", "Init", "1", "1/1 (100%)", "1/1 (100%)"),
            ("b.c", "Init", "1", "1/1 (100%)", "1/1 (100%)"),
            ("c.c", "Update", "1", "1/1 (100%)", "1/1 (100%)"),
        ])
        result = parse_hmr_html(html_bytes)
        d = result.to_dict()
        assert d["ambiguous_count"] == 1  # Init만 중복

    def test_same_unit_file_same_function_dedup_round2_w6(self):
        """Round 2 W6 fix: 같은 (unit_file, function_name) 중복 row dedup.

        VectorCAST aggregate metrics report가 같은 함수를 2번 reporting하는
        quirk가 있을 때 false ambiguous → false negative stamp skip 방지.
        같은 unit_file의 동일 함수명 row 2개는 1건만 보존.
        """
        html_bytes = _build_hmr_html([
            ("bats.c", "Init", "1", "1/1 (100%)", "5/5 (100%)"),
            ("bats.c", "Init", "1", "1/1 (100%)", "5/5 (100%)"),  # 같은 unit_file 중복
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        # metrics_by_name['Init'] 길이는 1 (dedup) — ambiguous 아님
        candidates = result.metrics_by_name["Init"]
        assert len(candidates) == 1, (
            f"같은 unit_file 중복 row가 dedup 안 됨: {[(c.unit_file, c.function_name) for c in candidates]}"
        )
        # ambiguous_count도 0
        assert result.to_dict()["ambiguous_count"] == 0

    def test_dedup_metric_mismatch_emits_warning_round4_nw5(self):
        """Round 4 NW5 fix: 같은 (unit_file, function_name) 중복 row의 metric
        값 불일치 시 parse_warnings emit (silent drop 차단).

        vcast가 부분 실행 + 최종 실행 결과 양쪽 보고 quirk 시 첫 row만 보존되어
        audit reviewer가 어떤 값이 산출물에 stamp되었는지 알 수 없는 silent
        wrong-pick 방지.
        """
        html_bytes = _build_hmr_html([
            ("bats.c", "Init", "1", "1/1 (100%)", "5/10 (50%)"),
            ("bats.c", "Init", "1", "1/1 (100%)", "8/10 (80%)"),  # 같은 file 다른 metric
        ])
        result = parse_hmr_html(html_bytes)
        assert result.ok is True
        # dedup으로 길이 1 유지 + 첫 row 보존
        assert len(result.metrics_by_name["Init"]) == 1
        assert result.metrics_by_name["Init"][0].covered_calls == 5
        # NW5: parse_warnings에 metric 불일치 사유 누적
        mismatch_warnings = [
            w for w in result.parse_warnings
            if "HMR dedup" in w and "값 불일치" in w
        ]
        assert len(mismatch_warnings) == 1, (
            f"NW5 회귀: metric 불일치 warning 누락. parse_warnings: {result.parse_warnings}"
        )
        assert "Init" in mismatch_warnings[0]
        assert "bats.c" in mismatch_warnings[0]
