"""R31 — 표면 정합: 판정 불가(Q-6) · 통과 판정에 붙는 사유(Q-7) · 라이터↔리더 누수(Q-8) + R30 편입 2건.

계획서 `docs/plans/PLAN_2026-09-03_게이트_결함_잔여_검토기록.md` §2.2 Q-6/Q-7/Q-8, R31 절.

착수 실측(2026-09-04, `reports/quality.sqlite` 2,016 run): `gated_metric_count == 0` 인 run **0건**,
`gate_reason:` 행 **0건**, summary 없는 run **0건**. 즉 Q-6 의 세 표면 불일치는 코드에 실재하지만 실 데이터에선
아직 발화한 적이 없다 — 그래서 여기 가드는 전부 **합성 run** 으로 잰다.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ==============================================================
# 공통 픽스처 — 합성 quality DB
# ==============================================================


@pytest.fixture
def qdb(tmp_path, monkeypatch):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


def _make_run(db, doc_type: str, scores: List[tuple], *, overall=50.0, gate=False, with_summary=True) -> int:
    from workflow.quality.db import get_session
    from workflow.quality.models import GenerationRun, QualityScore, QualitySummary

    with get_session(db) as s:
        run = GenerationRun(run_uuid=str(uuid.uuid4()), doc_type=doc_type, status="success")
        s.add(run)
        s.flush()
        for name, val, gp, th in scores:
            s.add(QualityScore(run_id=run.id, metric_name=name, value=val, gate_pass=gp, threshold=th))
        if with_summary:
            s.add(QualitySummary(run_id=run.id, overall_score=overall, gate_pass=gate))
        rid = run.id
    return rid


@pytest.fixture
def client(qdb):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.dependencies.auth import require_user
    from backend.routers import quality

    app = FastAPI()
    app.include_router(quality.router)
    app.dependency_overrides[require_user] = lambda: "tester"
    return TestClient(app)


# ==============================================================
# Q-6 — 판정 불가를 세 표면이 같은 근거로 그린다
# ==============================================================


class TestTrendCarriesTheVerdictBasis:

    def test_trend_item_has_reason_and_gated_count(self, client, qdb):
        """추세 막대가 `gate_pass` 만 보면 검사 0건이 빨간 막대가 된다 — 사유·규모가 응답에 있어야 한다."""
        _make_run(qdb, "uds", [
            ("gated_metric_count", 0.0, None, None),
            ("gate_reason:no_gated_metric", 1.0, None, None),
        ], gate=False)
        items = client.get("/api/quality/trend").json()["trend"]
        assert len(items) == 1
        assert items[0]["gate_reason"] == "no_gated_metric"
        assert items[0]["gated_metric_count"] == 0
        assert items[0]["gate_pass"] is False, "서버 판정은 그대로 — 프론트가 사유로 '판정 불가' 를 고른다"

    def test_trend_item_without_markers_is_none_not_zero(self, client, qdb):
        """구 run(지표 없음)은 미기록(None)이다 — 0 으로 접으면 전부 '판정 불가' 가 된다."""
        _make_run(qdb, "uds", [("called_pct", 90.0, True, 80.0)], gate=True)
        items = client.get("/api/quality/trend").json()["trend"]
        assert items[0]["gate_reason"] is None
        assert items[0]["gated_metric_count"] is None

    def test_run_list_has_top_level_gated_count_without_scores(self, client, qdb):
        """목록은 `include_scores=false` 가 기본이라 예전엔 검사 규모를 알 길이 없었다(게이트 화면 목록이 FAIL 로 그림)."""
        _make_run(qdb, "uds", [("gated_metric_count", 0.0, None, None)], gate=False)
        _make_run(qdb, "sts", [], gate=True)
        runs = client.get("/api/quality/runs").json()["runs"]
        by_type = {r["doc_type"]: r for r in runs}
        assert "scores" not in by_type["uds"], "기본 목록은 scores 를 싣지 않는다(계약 불변)"
        assert by_type["uds"]["gated_metric_count"] == 0
        assert by_type["sts"]["gated_metric_count"] is None

    def test_gated_count_helper_rejects_garbage(self):
        from backend.routers.quality import _gated_metric_count

        class _S:
            def __init__(self, name, value):
                self.metric_name, self.value = name, value

        assert _gated_metric_count([_S("gated_metric_count", 7.0)]) == 7
        assert _gated_metric_count([_S("gated_metric_count", None)]) is None
        assert _gated_metric_count([_S("gated_metric_count", "x")]) is None
        assert _gated_metric_count([_S("other", 0.0)]) is None
        assert _gated_metric_count(None) is None


class TestAdvisorDoesNotInventAVerdict:

    def test_missing_summary_is_no_verdict_not_fail(self, qdb):
        """요약 행이 없으면 판정 없음이다 — 예전엔 0.0/False 로 접어 '게이트 미통과' 문장을 지어냈다."""
        from workflow.quality.advisor import suggest_improvements

        rid = _make_run(qdb, "uds", [("called_pct", 50.0, False, 80.0)], with_summary=False)
        res = suggest_improvements(rid, db_path=qdb)
        assert res["gate_pass"] is None
        assert res["overall_score"] is None
        assert "판정 없음" in res["summary"]
        assert "미통과" not in res["summary"]
        assert "0.0" not in res["summary"], "없는 점수를 0.0 으로 말하면 안 된다"

    def test_summary_gate_pass_cannot_be_null_so_no_third_state(self, qdb):
        """착수 실측이 뒤집은 전제: `quality_summaries.gate_pass` 는 **NOT NULL** 이다.

        "요약은 있는데 판정 None" 이라는 세 번째 상태는 DB 가 거부한다 — 그래서 advisor 의 판정 없음은
        요약 행 부재 하나뿐이고, 그 분기를 더 만들면 도달 불가 코드다. 이 사실을 여기 잠근다.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from workflow.quality.db import get_session

        rid = _make_run(qdb, "uds", [], overall=42.0, gate=False)
        with pytest.raises(IntegrityError):
            with get_session(qdb) as s:
                s.execute(text("UPDATE quality_summaries SET gate_pass = NULL WHERE run_id = :rid"), {"rid": rid})

    def test_gated_zero_still_wins_over_everything(self, qdb):
        """검사 0건은 요약이 있어도 '판정 불가' 다(기존 계약 유지)."""
        from workflow.quality.advisor import suggest_improvements

        rid = _make_run(qdb, "uds", [("gated_metric_count", 0.0, None, None)], overall=100.0, gate=True)
        res = suggest_improvements(rid, db_path=qdb)
        assert res["gated_metric_count"] == 0
        assert "0개" in res["summary"] and "통과 아님" in res["summary"]


# ==============================================================
# Q-7 — 사유는 판정 축에서만 파생된다
# ==============================================================

_RATE_KEYS = (
    "called_fill", "calling_fill", "input_fill", "output_fill", "global_fill", "static_fill",
    "description_fill", "asil_fill", "related_fill",
    "description_trusted_fill", "asil_trusted_fill", "related_trusted_fill",
)
_THR_KEYS = (
    "called_min", "calling_min", "input_min", "output_min", "global_min", "static_min",
    "description_min", "asil_min", "related_min",
    "description_trusted_min", "asil_trusted_min", "related_trusted_min",
)
_THRESHOLD_CODES = {
    "CALLED_LOW", "CALLING_LOW", "CALLING_ZERO", "INPUT_PARSE_LOW", "OUTPUT_PARSE_LOW",
    "DESCRIPTION_LOW", "ASIL_LOW", "RELATED_ID_LOW",
    "DESCRIPTION_TRUST_LOW", "ASIL_TRUST_LOW", "RELATED_ID_TRUST_LOW",
    "GLOBAL_PARSE_LOW", "STATIC_PARSE_LOW",
}


def _qg(rates: Dict[str, float], thr: Dict[str, float], total: int = 10) -> Dict[str, Any]:
    return {"rates": rates, "thresholds": thr, "counts": {"total_functions": total}}


def _codes(qg, template_warning=""):
    from backend.helpers.uds import _derive_quality_reason_codes
    return _derive_quality_reason_codes(qg, template_warning=template_warning)


def _info(qg):
    from backend.helpers.uds import _derive_quality_info_codes
    return _derive_quality_info_codes(qg)


class TestReasonsComeOnlyFromGateAxes:

    def test_no_functions_returns_early_without_low_codes(self):
        """함수 0개의 미달률은 측정이 아니다 — 예전엔 12개 `*_LOW` 가 전부 붙었다."""
        got = _codes(_qg({k: 0.0 for k in _RATE_KEYS}, {k: 50.0 for k in _THR_KEYS}, total=0))
        assert got == ["NO_FUNCTIONS"], got

    def test_no_functions_keeps_template_invalid(self):
        """템플릿 결함은 함수 수와 무관한 별도 축이라 조기 반환에도 살아남는다."""
        got = _codes(_qg({}, {}, total=0), template_warning="bad")
        assert got == ["NO_FUNCTIONS", "TEMPLATE_INVALID"]

    def test_global_static_are_not_reasons_but_info(self):
        """`global_min`/`static_min` 은 판정 축이 아니다 — 통과 판정에 미달 사유가 붙던 자리."""
        rates = {k: 100.0 for k in _RATE_KEYS}
        rates["global_fill"] = 0.0
        rates["static_fill"] = 0.0
        thr = {k: 50.0 for k in _THR_KEYS}
        assert _codes(_qg(rates, thr)) == []
        assert _info(_qg(rates, thr)) == ["GLOBAL_PARSE_LOW", "STATIC_PARSE_LOW"]

    def test_calling_zero_is_a_reason_only_while_the_axis_is_on(self):
        rates = {k: 100.0 for k in _RATE_KEYS}
        rates["calling_fill"] = 0.0
        on = {k: 50.0 for k in _THR_KEYS}
        assert _codes(_qg(rates, on)) == ["CALLING_ZERO"]
        assert "CALLING_ZERO" not in _info(_qg(rates, on)), "한 코드가 두 목록에 동시에 있으면 안 된다"
        off = dict(on, calling_min=0.0)
        assert _codes(_qg(rates, off)) == [], "축을 껐으면 판정은 통과 — 사유가 남으면 모순"
        assert _info(_qg(rates, off)) == ["CALLING_ZERO"], "파서가 안 돈 사실은 정보로 남는다"

    def test_calling_zero_is_not_duplicated_with_calling_low(self):
        rates = {k: 100.0 for k in _RATE_KEYS}
        rates["calling_fill"] = 0.0
        got = _codes(_qg(rates, {k: 50.0 for k in _THR_KEYS}))
        assert got.count("CALLING_ZERO") == 1 and "CALLING_LOW" not in got

    def test_info_is_empty_when_there_are_no_functions(self):
        assert _info(_qg({k: 0.0 for k in _RATE_KEYS}, {k: 50.0 for k in _THR_KEYS}, total=0)) == []

    @pytest.mark.parametrize("seed", range(40))
    def test_pass_verdict_never_carries_a_threshold_reason(self, seed):
        """불변식: quick+confidence 판정이 True 면 임계 사유는 0개. 판정식과 같은 튜플에서 사유를 뽑기 때문."""
        import random

        from backend.helpers.uds import CONFIDENCE_GATE_AXES, QUICK_GATE_AXES

        rng = random.Random(seed)
        rates = {k: rng.choice([0.0, 10.0, 50.0, 90.0, 100.0]) for k in _RATE_KEYS}
        thr = {k: rng.choice([0.0, 50.0, 95.0]) for k in _THR_KEYS}
        verdict = all(rates[r] >= thr[t] for r, t in (*QUICK_GATE_AXES, *CONFIDENCE_GATE_AXES))
        reasons = set(_codes(_qg(rates, thr))) & _THRESHOLD_CODES
        if verdict:
            assert not reasons, f"통과인데 사유 {reasons} (rates={rates}, thr={thr})"
        else:
            assert reasons, f"미통과인데 사유 0개 (rates={rates}, thr={thr})"

    def test_evaluation_dict_separates_info_from_reason(self, tmp_path):
        from backend.helpers.uds import _build_quality_evaluation

        rates = {k: 100.0 for k in _RATE_KEYS}
        rates["global_fill"] = 0.0
        qg = _qg(rates, {k: 50.0 for k in _THR_KEYS})
        qg["gate_pass"] = True
        qg["confidence_gate_pass"] = True
        ev = _build_quality_evaluation(qg, None, None, doc_only_mode=True)
        assert ev["gate_pass"] is True
        assert ev["reason_codes"] == [] and ev["action_hints"] == []
        assert ev["info_codes"] == ["GLOBAL_PARSE_LOW"]
        assert ev["info_hints"] and "globals_global" in ev["info_hints"][0], "문구는 그대로 — 등급만 내려간다"

    def test_reason_code_table_covers_exactly_the_gate_axes(self):
        """사유 표의 키 = 판정 축의 임계 키. 축이 추가되면 여기서 걸린다."""
        from backend.helpers.uds import (
            _INFO_CODE_BY_THRESHOLD_KEY,
            _REASON_CODE_BY_THRESHOLD_KEY,
            CONFIDENCE_GATE_AXES,
            QUICK_GATE_AXES,
        )

        assert set(_REASON_CODE_BY_THRESHOLD_KEY) == {t for _, t in (*QUICK_GATE_AXES, *CONFIDENCE_GATE_AXES)}
        assert not (set(_REASON_CODE_BY_THRESHOLD_KEY) & set(_INFO_CODE_BY_THRESHOLD_KEY))


# ==============================================================
# Q-8 — `.validation.md` 라이터↔리더
# ==============================================================


def _write_validation(tmp_path, fake: Dict[str, Any]) -> Path:
    import report_gen.validation as V

    out = tmp_path / "r.validation.md"
    orig = V.validate_uds_docx_structure
    V.validate_uds_docx_structure = lambda _p: fake  # noqa: ARG005
    try:
        V.generate_uds_validation_report("x.docx", str(out))
    finally:
        V.validate_uds_docx_structure = orig
    return out


_BASE = {"docx_path": "x.docx", "ok": True, "table_count": 1, "image_count": 0,
         "swufn_heading_count": 3, "function_info_table_count": 3, "logic_row_count": 0,
         "logic_with_image_count": 0}


class TestZeroIsWrittenWhenCompared:

    def test_zero_missing_survives_the_round_trip(self, tmp_path):
        """대조했고 누락 0 이면 리더는 0 을 받는다 — 예전엔 줄이 없어 None(미측정)이었다."""
        from report_gen.evidence import read_docx_validation

        out = _write_validation(tmp_path, dict(_BASE, expected_functions=3, matched_functions=3,
                                               missing_from_docx_count=0, headings_without_payload_count=0,
                                               payload_functions_missing_from_docx=[],
                                               docx_headings_without_payload=[]))
        got = read_docx_validation(out)
        assert got["missing_from_docx"] == 0
        assert got["headings_without_payload"] == 0
        assert got["uncomparable"] is False

    def test_zero_line_has_no_warning_marker_and_no_example(self, tmp_path):
        import report_gen.validation_labels as VL

        out = _write_validation(tmp_path, dict(_BASE, expected_functions=3, matched_functions=3,
                                               missing_from_docx_count=0, headings_without_payload_count=0))
        text = out.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if VL.LABEL_MISSING_FROM_DOCX in ln)
        assert not line.startswith("- ⚠"), line
        assert "(예:" not in line

    def test_nonzero_keeps_marker_and_examples(self, tmp_path):
        from report_gen.evidence import read_docx_validation

        out = _write_validation(tmp_path, dict(_BASE, expected_functions=5, matched_functions=2,
                                               missing_from_docx_count=3, headings_without_payload_count=0,
                                               payload_functions_missing_from_docx=["a", "b", "c"]))
        text = out.read_text(encoding="utf-8")
        assert "- ⚠" in text and "(예: a, b, c)" in text
        assert read_docx_validation(out)["missing_from_docx"] == 3

    def test_uncompared_writes_no_count_line_at_all(self, tmp_path):
        """대조 못 했으면 0 을 쓰지 않는다 — 0 은 '누락 없음' 이라는 단언이다."""
        import report_gen.validation_labels as VL
        from report_gen.evidence import read_docx_validation

        out = _write_validation(tmp_path, dict(_BASE, expected_functions=None,
                                               warnings=["payload 사이드카 없음(x.payload.json) — 입력 대비 대조 불가(미검증)"]))
        text = out.read_text(encoding="utf-8")
        assert VL.LABEL_MISSING_FROM_DOCX not in text
        got = read_docx_validation(out)
        assert got["missing_from_docx"] is None
        assert got["uncomparable"] is True


class TestWarningsReachTheReader:

    def test_warnings_survive_the_round_trip(self, tmp_path):
        from report_gen.evidence import read_docx_validation

        w = ["소스 함수 629개가 문서에 없다 — 템플릿에 대응 SwUFn heading 이 없어 조용히 빠졌다(예: a, b)",
             "템플릿 heading 150개에 대응 소스 함수가 없다 — **빈 함수 명세**로 출력된다(예: c)"]
        out = _write_validation(tmp_path, dict(_BASE, expected_functions=900, matched_functions=271,
                                               missing_from_docx_count=629, headings_without_payload_count=150,
                                               warnings=w))
        assert read_docx_validation(out)["warnings"] == w

    def test_no_warnings_is_an_empty_list_not_none(self, tmp_path):
        from report_gen.evidence import read_docx_validation

        out = _write_validation(tmp_path, dict(_BASE, expected_functions=3, matched_functions=3,
                                               missing_from_docx_count=0, headings_without_payload_count=0))
        assert read_docx_validation(out)["warnings"] == []

    def test_old_artifact_without_the_section_is_empty_list(self, tmp_path):
        from report_gen.evidence import read_docx_validation

        p = tmp_path / "old.validation.md"
        p.write_text("# UDS Validation Report\n\n- OK: `True`\n\n## Issues\n- none\n", encoding="utf-8")
        got = read_docx_validation(p)
        assert got["warnings"] == []
        assert got["uncomparable"] is None, "줄 자체가 없는 구판은 None(미상) — True/False 어느 쪽도 아니다"

    def test_section_title_is_the_shared_constant_on_both_sides(self):
        """제목 문자열이 한쪽에 리터럴로 남으면 라벨 결함이 재발한다 — 소스로 확인."""
        import report_gen.validation_labels as VL
        from report_gen.evidence import read_docx_validation
        from report_gen.validation import generate_uds_validation_report
        from tests.unit._source_probe import source_of

        for fn in (generate_uds_validation_report, read_docx_validation):
            src = source_of(fn)
            assert VL.SECTION_WARNINGS not in src, f"{fn.__name__} 가 절 제목을 리터럴로 들고 있다"
            assert "SECTION_WARNINGS" in src


# ==============================================================
# R30 편입 ① — 사이드카 원자 기록
# ==============================================================


class TestSidecarsAreWrittenAtomically:

    def test_normal_write_leaves_no_tmp(self, tmp_path):
        from report_gen.validation import _atomic_write_text

        out = tmp_path / "a" / "x.quality_gate.md"
        _atomic_write_text(out, "hello")
        assert out.read_text(encoding="utf-8") == "hello"
        assert not (tmp_path / "a" / "x.quality_gate.md.tmp").exists()

    def test_failed_replace_keeps_the_old_file_and_raises(self, tmp_path, monkeypatch):
        """반쯤 쓰인 파일이 그 이름을 갖는 일이 없다 — 옛 내용이 남고 예외는 올라온다."""
        from report_gen.validation import _atomic_write_text

        out = tmp_path / "x.quality_gate.md"
        out.write_text("OLD", encoding="utf-8")

        def _boom(_src, _dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(OSError):
            _atomic_write_text(out, "NEW")
        assert out.read_text(encoding="utf-8") == "OLD"
        assert not out.with_name(out.name + ".tmp").exists(), "임시 파일이 남으면 다음 읽기가 그걸 집는다"

    def test_the_three_evidence_sidecars_use_it(self):
        """증거 3종(`SIDECAR_SUFFIXES`)의 라이터가 전부 원자 기록을 탄다 — 하나라도 `write_text` 로 돌아가면 걸린다."""
        from report_gen.validation import (
            generate_asil_related_confidence_report,
            generate_uds_field_quality_gate_report,
            generate_uds_validation_report,
        )
        from tests.unit._source_probe import source_of

        for fn in (generate_uds_validation_report, generate_uds_field_quality_gate_report,
                   generate_asil_related_confidence_report):
            src = source_of(fn)
            assert "_atomic_write_text(" in src, fn.__name__
            body_after_try = src.split("lines: List[str] = []", 1)[-1]
            assert 'out.write_text("\\n".join(lines)' not in body_after_try, (
                f"{fn.__name__} 의 성공 경로가 비원자 write_text 로 돌아갔다")


# ==============================================================
# R30 편입 ② — `report_gate` 에 채점 집합 수
# ==============================================================

_GATE_MD = """# UDS Field Quality Gate Report

- Docx: `x.docx`
- Payload: `x.payload.json` · functions 18
- Total functions: `18`
- Document entries: `426` · scored (document ∩ payload): `18`
- Scored entries: `18` / `426` — 문서 커버리지 4.2%, 판정 밖
- Distinct scored functions: `17`
- Gates: `9` / `10` passed
- Gate pass: `True`

## Metrics
- Description fill: `18` / `18` (100.0%)
"""


class TestReportGateCarriesTheScoringScope:

    def test_parse_scoring_scope_reads_the_three_head_lines(self):
        from report_gen.gate_report import parse_scoring_scope

        got = parse_scoring_scope(_GATE_MD)
        assert got == {"scored_entries": {"count": 18, "total": 426},
                       "document_entries": 426, "distinct_scored_functions": 17}

    def test_old_sidecar_is_none_not_zero(self):
        from report_gen.gate_report import parse_scoring_scope

        got = parse_scoring_scope("# UDS Field Quality Gate Report\n\n- Gate pass: `True`\n")
        assert got == {"scored_entries": None, "document_entries": None, "distinct_scored_functions": None}

    def test_head_lines_stop_at_the_first_section(self):
        """본문 절 안의 같은 라벨은 head 가 아니다 — 절 안 문장이 채점 범위를 조종하면 안 된다."""
        from report_gen.gate_report import parse_scoring_scope

        text = "# R\n\n- Gate pass: `True`\n\n## Notes\n- Document entries: `999`\n"
        assert parse_scoring_scope(text)["document_entries"] is None

    def test_scope_lines_are_not_mistaken_for_metrics(self):
        """R30 리뷰 W2 — 채점 범위 줄이 `(…)` 를 달면 지표 파서가 지표로 집는다. 지금 형식은 안 집힌다."""
        from report_gen.gate_report import parse_gate_report

        keys = set(parse_gate_report(_GATE_MD)["metrics"])
        assert "scored_entries" not in keys and "document_entries" not in keys
        assert "description_fill" in keys

    def test_uds_helper_report_gate_exposes_them(self, tmp_path):
        from backend.helpers.uds import _parse_quality_gate_report

        p = tmp_path / "x.quality_gate.md"
        p.write_text(_GATE_MD, encoding="utf-8")
        got = _parse_quality_gate_report(p)
        assert got["gate_pass"] is True
        assert got["scored_entries"] == {"count": 18, "total": 426}
        assert got["document_entries"] == 426
        assert got["distinct_scored_functions"] == 17
        absent = _parse_quality_gate_report(tmp_path / "nope.md")
        assert absent["scored_entries"] is None and absent["document_entries"] is None

    def test_evidence_reader_and_helper_agree_by_construction(self, tmp_path):
        """두 소비처가 **같은 함수**를 부른다 — 값이 같은 게 아니라 출처가 같아야 한다."""
        from backend.helpers.uds import _parse_quality_gate_report
        from report_gen.evidence import read_gate_report
        from tests.unit._source_probe import source_of

        assert "parse_scoring_scope(" in source_of(read_gate_report)
        assert "parse_scoring_scope(" in source_of(_parse_quality_gate_report)
        p = tmp_path / "x.quality_gate.md"
        p.write_text(_GATE_MD, encoding="utf-8")
        ev, hp = read_gate_report(p), _parse_quality_gate_report(p)
        for k in ("scored_entries", "document_entries", "distinct_scored_functions"):
            assert ev[k] == hp[k], k
