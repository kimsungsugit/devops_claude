"""R32 — 평가기 None 접기(Q-9) · 어휘/임계/캐시 잔여(Q-10) · 분모 0 규약(B-9) + R31 리뷰 편입(W2·I12).

계획서 `docs/plans/PLAN_2026-09-03_게이트_결함_잔여_검토기록.md` §2.2 Q-9/Q-10 · §3 B-9, R32 절.

착수 실측(2026-09-04, `reports/quality.sqlite` 2,016 run · payload 126개 · 신뢰도 사이드카 56개):
- `accuracy_*` 행 **0건**(전 doc_type) — 생산자 키 `called_exact_match` ↔ 평가기 키 `called_pct` 불일치.
  축이 처음부터 죽어 있었다(`> 0` 필터가 그 0 을 버려 "정확도 0%" 거짓 대신 침묵이 됐다).
- `suts.io_coverage_pct` 12 run 전부 TC>0 · `sits` TC 0 run 0건 · `swsa` run 0건 · 신뢰도 `Total functions: 0` **2건**.
- payload 출처 어휘: 강한 출처+빈 값 **0건**, `inference`+빈 ASIL 52건, `hsis` 0건.
즉 이 라운드에서 라이브로 발화하는 결함은 신뢰도 등급 `D` 2건과 accuracy 축 부재뿐이고, 나머지는 합성 입력으로 잰다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest

import backend.helpers.common as _common_mod  # noqa: F401
import backend.helpers.uds as _uds_mod  # noqa: F401
import backend.routers.jenkins as _jenkins_mod  # noqa: F401
import backend.routers.local as _local_mod  # noqa: F401
import backend.routers.quality as _quality_mod  # noqa: F401

# ⚠ 모듈 수준 import 는 의도다. `tools/generate_uds_local.py` 를 먼저 import 한 테스트가 있으면 `sys.path[0]` 에
#   260105 트리가 꽂혀, 함수 안의 `from generators.sts import …` 가 **그 트리의 같은 이름 파일**로 해석된다
#   (실측: `test_generate_uds_local.py` 뒤에 돌리면 SUTS/STS 검증 md 테스트 3건이 옛 항목명으로 실패).
#   수집 시점에 이 저장소 모듈을 캐시에 올려 두면 순서와 무관하다 — 근본(도구의 sys.path 변형)은 R33 후보.
import generators.sts as _sts_mod  # noqa: F401
import generators.suts as _suts_mod  # noqa: F401
import report_gen.evidence as _evidence_mod  # noqa: F401
import report_gen.validation as _validation_mod  # noqa: F401
import workflow.quality.advisor as _advisor_mod  # noqa: F401
import workflow.quality.evaluator as _evaluator_mod  # noqa: F401
import workflow.quality.recorder as _recorder_mod  # noqa: F401
from tests.unit._source_probe import source_of

# ==============================================================
# B-9 — 분모 0 → threshold None (해당 없음 ≠ 미측정 ≠ 0%)
# ==============================================================


def _by_name(metrics):
    return {m["metric_name"]: m for m in metrics}


class TestDenominatorZeroIsNotAFailure:
    def test_helper_contract(self):
        from workflow.quality.evaluator import _gate_if_applicable
        assert _gate_if_applicable(70.0, 0) is None
        assert _gate_if_applicable(70.0, 0.0) is None
        assert _gate_if_applicable(70.0, 1) == 70.0

    def test_suts_io_coverage_is_ungated_when_there_are_no_tcs(self):
        from workflow.quality.evaluator import evaluate_suts
        m = _by_name(evaluate_suts({"total_test_cases": 0, "io_coverage_pct": 0.0}))
        assert m["io_coverage_pct"]["threshold"] is None
        assert m["io_coverage_pct"]["gate_pass"] is None
        assert m["total_test_cases"]["value"] == 0.0

    def test_suts_io_coverage_stays_gated_with_tcs(self):
        """라이브 12 run 의 형태 — TC 253 의 실측 0% 는 **진짜 FAIL** 이다(1157·1158)."""
        from workflow.quality.evaluator import evaluate_suts
        m = _by_name(evaluate_suts({"total_test_cases": 253, "io_coverage_pct": 0.0}))
        assert m["io_coverage_pct"]["threshold"] == 70.0
        assert m["io_coverage_pct"]["gate_pass"] is False

    def test_sits_zero_tcs_yields_no_gated_metric_not_zero_percent_fail(self):
        from workflow.quality.evaluator import compute_gate_verdict, evaluate_sits
        metrics = evaluate_sits({"total_test_cases": 0, "requirement_traceability_pct": 0.0, "io_coverage_pct": 0.0})
        m = _by_name(metrics)
        assert m["requirement_traceability_pct"]["threshold"] is None
        assert m["io_coverage_pct"]["threshold"] is None
        verdict = compute_gate_verdict(metrics)
        assert verdict["gate_pass"] is False
        assert verdict["reason"] == "no_gated_metric"

    def test_sits_missing_key_with_tcs_is_still_fail_closed(self):
        """키 부재(구판)는 B-9 대상이 아니다 — 기존 fail-closed 그대로(`evaluate_sits` 주석의 규약)."""
        from workflow.quality.evaluator import evaluate_sits
        m = _by_name(evaluate_sits({"total_test_cases": 10, "io_coverage_pct": 80.0}))
        assert m["requirement_traceability_pct"]["gate_pass"] is False

    def test_sts_zero_requirements_is_fail_closed_not_not_applicable(self):
        """(리뷰 W1) STS 는 요구 기반 문서라 "요구 0개" 는 해당 없음이 아니라 **요구 문서를 못 읽은 것**이다.
        비게이트로 빼면 `completeness_pct` 하나만 남아 `gate_pass=True·100.0` 이 됐다(리뷰어 실측)."""
        from workflow.quality.evaluator import compute_gate_verdict, evaluate_sts
        metrics = evaluate_sts({"total_test_cases": 10, "completeness_pct": 100.0,
                                "requirement_coverage": {"total_reqs": 0, "covered_reqs": 0, "pct": 0.0}})
        m = _by_name(metrics)
        assert m["requirement_coverage_pct"]["threshold"] == 70.0
        assert m["requirement_coverage_pct"]["gate_pass"] is False
        assert m["requirement_coverage_unmeasured"]["value"] == 1.0
        assert m["total_requirements"]["value"] == 0.0
        assert compute_gate_verdict(metrics)["gate_pass"] is False

    def test_sts_absent_coverage_is_fail_closed_and_says_so(self):
        from workflow.quality.evaluator import evaluate_sts
        m = _by_name(evaluate_sts({"total_test_cases": 5}))
        assert m["requirement_coverage_pct"]["gate_pass"] is False
        assert m["requirement_coverage_unmeasured"]["value"] == 1.0

    def test_sts_coverage_without_total_key_is_marked_unmeasured(self):
        """(리뷰 I1) dict 는 있는데 `total_reqs` 만 없는 구판 — 지표가 "측정됨(0.0)" 으로 뒤집히면 안 된다."""
        from workflow.quality.evaluator import evaluate_sts
        m = _by_name(evaluate_sts({"total_test_cases": 5, "requirement_coverage": {"covered_pct": 50.0}}))
        assert m["requirement_coverage_unmeasured"]["value"] == 1.0

    def test_sts_live_shape_is_unchanged(self):
        from workflow.quality.evaluator import evaluate_sts
        m = _by_name(evaluate_sts({"total_test_cases": 215, "requirement_coverage": {"total_reqs": 68, "covered_reqs": 68, "pct": 100.0}}))
        assert m["requirement_coverage_pct"]["gate_pass"] is True
        assert m["requirement_coverage_pct"]["threshold"] == 70.0
        assert m["requirement_coverage_unmeasured"]["value"] == 0.0
        assert m["total_requirements"]["value"] == 68.0

    def test_swsa_with_nothing_measured_is_ungated(self):
        from workflow.quality.evaluator import evaluate_swsa
        m = _by_name(evaluate_swsa({"his_metrics": [{"total": 0, "fail": 0, "unbinned": 0}]}))
        assert m["his_pass_pct"]["threshold"] is None
        assert m["his_metrics_measured"]["value"] == 0.0

    def test_swsa_with_measurements_is_gated(self):
        from workflow.quality.evaluator import evaluate_swsa
        m = _by_name(evaluate_swsa({"his_metrics": [{"total": 10, "fail": 1, "unbinned": 1}]}))
        assert m["his_pass_pct"]["threshold"] == 80.0
        assert m["his_pass_pct"]["value"] == 80.0
        assert m["his_metrics_measured"]["value"] == 1.0


class TestAccuracyAxisIsAlive:
    """생산자 키(`*_exact_match`)를 읽고, 값이 있으면 **0.0 도** 기록한다."""

    def _eval(self, accuracy: Dict[str, Any]):
        from workflow.quality.evaluator import evaluate_uds
        return _by_name(evaluate_uds({"quick_gate": {"rates": {}, "gate_pass": False}, "accuracy": accuracy}))

    def test_producer_keys_are_read(self):
        m = self._eval({"called_exact_match": 97.5, "calling_exact_match": 97.2})
        assert m["accuracy_called_pct"]["value"] == 97.5
        assert m["accuracy_calling_pct"]["value"] == 97.2

    def test_zero_measurement_is_recorded_not_dropped(self):
        m = self._eval({"called_exact_match": 0.0, "calling_exact_match": 0.0})
        assert m["accuracy_called_pct"]["value"] == 0.0
        assert m["accuracy_calling_pct"]["value"] == 0.0

    def test_absent_measurement_is_omitted_not_zero(self):
        m = self._eval({"called_exact_match": None, "calling_exact_match": None})
        assert "accuracy_called_pct" not in m
        assert "accuracy_calling_pct" not in m
        assert "accuracy_called_pct" not in self._eval({})

    def test_legacy_pct_keys_still_work(self):
        m = self._eval({"called_pct": 12.5})
        assert m["accuracy_called_pct"]["value"] == 12.5

    def test_the_real_producer_and_evaluator_agree_by_construction(self, tmp_path):
        from backend.helpers.uds import _parse_accuracy_report
        from workflow.quality.evaluator import evaluate_uds
        p = tmp_path / "x.accuracy.md"
        p.write_text("# Called/Calling Accuracy Report\n- Called exact match: `0` / `282` (0.0%)\n"
                     "- Calling exact match: `274` / `282` (97.2%)\n", encoding="utf-8")
        acc = _parse_accuracy_report(p)
        m = _by_name(evaluate_uds({"quick_gate": {"rates": {}}, "accuracy": acc}))
        assert m["accuracy_called_pct"]["value"] == 0.0
        assert m["accuracy_calling_pct"]["value"] == 97.2


# ==============================================================
# Q-9 — 신뢰도 리포트: 값 없는 강한 출처 · 함수 0개 등급
# ==============================================================


class _FakeDoc:
    pass


def _confidence(tmp_path, payload, name="c"):
    from report_gen.validation import generate_asil_related_confidence_report
    out = tmp_path / f"{name}.md"
    generate_asil_related_confidence_report(payload, str(out))
    return out.read_text(encoding="utf-8")


def _score_of(text: str) -> float:
    m = re.search(r"Overall confidence score: `([\d.]+)`", text)
    assert m, text[:400]
    return float(m.group(1))


class TestConfidenceScoreLooksAtTheValue:
    def test_strong_source_with_empty_value_does_not_score_as_strong(self, tmp_path):
        full = {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f",
            "description": "Reads sensor", "description_source": "sds",
            "asil": "B", "asil_source": "sds",
            "related": "SwFn_01", "related_source": "sds",
        }}}
        empty_asil = json.loads(json.dumps(full))
        empty_asil["function_details_by_name"]["f"]["asil"] = ""
        assert _score_of(_confidence(tmp_path, full, "full")) == pytest.approx(0.95, abs=1e-3)
        # (0.95 + 0.30 + 0.95) / 3 — 빈 값은 출처 라벨과 무관하게 `default`(0.30) 다.
        assert _score_of(_confidence(tmp_path, empty_asil, "empty")) == pytest.approx(0.733, abs=1e-3)

    def test_table_and_distribution_show_the_effective_source(self, tmp_path):
        """(리뷰 W7) 점수만 0.30 으로 재고 표엔 `추론` 을 찍으면 리포트가 자기 평균을 재현하지 못한다."""
        text = _confidence(tmp_path, {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f",
            "description": "Reads sensor", "description_source": "sds",
            "asil": "", "asil_source": "inference",
            "related": "SwFn_01", "related_source": "sds",
        }}})
        asil_section = text.split("## ASIL Source")[1].split("## ")[0]
        assert "기본값(근거 없음)" in asil_section
        assert "추론" not in asil_section
        assert "값 없음(빈칸/TBD) — 근거 미기록" in text

    def test_unknown_labels_are_counted_once(self, tmp_path):
        """(리뷰 I5) 미지 라벨이 표와 점수에서 두 번 세어져 정확히 2배로 적혔다."""
        text = _confidence(tmp_path, {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f",
            "description": "Reads sensor", "description_source": "weirdlabel",
            "asil": "B", "asil_source": "sds",
            "related": "SwFn_01", "related_source": "sds",
        }}})
        assert "`weirdlabel`×1" in text, text[-600:]

    def test_placeholder_values_count_as_empty(self, tmp_path):
        base = {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f",
            "description": "Reads sensor", "description_source": "sds",
            "asil": "TBD", "asil_source": "srs",
            "related": "N/A", "related_source": "srs",
        }}}
        assert _score_of(_confidence(tmp_path, base)) == pytest.approx((0.95 + 0.30 + 0.30) / 3, abs=1e-3)

    def test_zero_functions_is_not_grade_d(self, tmp_path):
        from report_gen.evidence import read_confidence_report
        out = tmp_path / "z.md"
        from report_gen.validation import generate_asil_related_confidence_report
        generate_asil_related_confidence_report({"function_details_by_name": {}}, str(out))
        text = out.read_text(encoding="utf-8")
        assert "grade: `D`" not in text
        assert "grade: `n/a`" in text
        assert "미측정" in text
        parsed = read_confidence_report(out)
        assert parsed["total_functions"] == 0
        assert parsed["overall_score"] is None
        assert parsed["grade"] == "n/a"


class TestAsilMergeRespectsStrongSources:
    """DOCX 회수 병합 — 세 필드가 같은 예외 판정(`provenance.is_weak_source`)을 쓴다."""

    def _run(self, tmp_path, monkeypatch, asil_source: str):
        from report_gen.validation import generate_asil_related_confidence_report
        payload = {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f",
            "description": "Reads sensor", "description_source": "sds",
            "asil": "TBD", "asil_source": asil_source,
            "related": "SwFn_01", "related_source": "sds",
        }}}
        fake_docx = tmp_path / f"{asil_source}.docx"
        fake_docx.write_bytes(b"stub")
        monkeypatch.setattr("docx.Document", lambda *_a, **_k: _FakeDoc())
        monkeypatch.setattr(
            "report_gen.validation._extract_function_info_from_docx",
            lambda _doc: {"f": {"id": "SwUFn_01", "name": "f", "description": "Reads sensor",
                                "asil": "B", "related": "SwFn_01"}},
        )
        out = tmp_path / f"{asil_source}.md"
        generate_asil_related_confidence_report(payload, str(out), str(fake_docx))
        return out.read_text(encoding="utf-8")

    def test_weak_source_is_overwritten_from_the_document(self, tmp_path, monkeypatch):
        text = self._run(tmp_path, monkeypatch, "inference")
        assert "generated_doc" in text or "생성 UDS DOCX" in text

    def test_strong_source_tbd_is_kept(self, tmp_path, monkeypatch):
        """SRS 가 명시한 TBD 는 문서에서 회수한 `B` 로 덮이지 않는다("tbd 면 tbd")."""
        text = self._run(tmp_path, monkeypatch, "srs")
        assert "생성 UDS DOCX 에서 회수" not in text
        # ASIL 열이 여전히 TBD 로 남는다(값 자체를 지어내지 않는다).
        assert re.search(r"\|\s*f\s*\|.*\bTBD\b", text) or "TBD" in text

    def test_the_three_guards_use_provenance_not_literals(self):
        from report_gen import validation as v
        src = source_of(v.generate_asil_related_confidence_report)
        assert "weak_asil_src = is_weak_source(" in src
        assert "weak_desc_src = is_weak_source(" in src
        assert "weak_rel_src = is_weak_source(" in src
        assert 'in {"", "inference", "rule"}' not in src


# ==============================================================
# Q-10 — 출처 어휘 · 임계 부재 · 사이드카 생성 실패 · 조언 임계 · SUTS 게이트 표
# ==============================================================


class TestFieldSourceVocabularyIsShared:
    def test_hsis_alias_is_trusted_like_the_confidence_report(self):
        from backend.helpers.common import _is_trusted_source_for_field, _normalize_field_source
        assert _normalize_field_source("hsis") == "sds"
        assert _is_trusted_source_for_field({"description_source": "hsis"}, "description") is True

    @pytest.mark.parametrize("src", ["sds_match", "srs_default_qm", "generated_doc", "default", "unknown", ""])
    def test_live_weak_vocabulary_stays_untrusted(self, src):
        from backend.helpers.common import _is_trusted_source_for_field, _normalize_field_source
        assert _normalize_field_source(src) == "inference"
        assert _is_trusted_source_for_field({"description_source": src}, "description") is False

    def test_alias_table_is_provenance_not_a_literal(self):
        from backend.helpers import common
        src = source_of(common._normalize_field_source)
        assert "canonical_source(" in src


class TestMissingThresholdIsFailClosedNotACrash:
    @pytest.fixture
    def payload(self):
        return {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f", "called": ["g"], "calling": ["h"],
            "inputs": ["[IN] x"], "outputs": ["[OUT] y"], "description": "Reads sensor",
            "description_source": "sds", "asil": "B", "asil_source": "sds",
            "related": "SwFn_01", "related_source": "sds",
        }}}

    def test_full_table_passes_and_reports_nothing_missing(self, payload):
        from backend.helpers.uds import _compute_quick_quality_gate
        out = _compute_quick_quality_gate(payload)
        assert out["thresholds_missing"] == []
        assert out["gate_pass"] is True

    def test_missing_key_does_not_raise_and_fails_that_gate(self, payload, monkeypatch):
        import config
        from backend.helpers.uds import _compute_quick_quality_gate
        table = dict(config.UDS_QUALITY_GATE_THRESHOLDS)
        table.pop("called_min")
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", table)
        out = _compute_quick_quality_gate(payload)
        assert out["thresholds_missing"] == ["called_min"]
        assert out["gate_pass"] is False
        # 신뢰도 축은 온전하므로 그쪽 판정은 그대로다.
        assert out["confidence_gate_pass"] is True


class TestSidecarGenerationFailureIsNotAbsence:
    @staticmethod
    def _quick():
        return {"gate_pass": True, "confidence_gate_pass": True, "rates": {}, "counts": {"total_functions": 1}, "thresholds": {}}

    def test_failed_generation_is_fail_closed(self):
        from backend.helpers.uds import _build_quality_evaluation
        out = _build_quality_evaluation(self._quick(), None, None, quality_gate_error="field quality gate report timeout (300s)")
        assert out["gate_pass"] is False
        assert out["gate_source"] == "report_generation_failed"
        assert out["report_gate"]["gate_pass_status"] == "generation_failed"
        assert "timeout" in out["report_gate"]["error"]

    def test_doc_only_still_ignores_the_report_axis(self):
        from backend.helpers.uds import _build_quality_evaluation
        out = _build_quality_evaluation(self._quick(), None, None, doc_only_mode=True, quality_gate_error="x")
        assert out["gate_pass"] is True
        assert out["gate_source"] == "quick_only"

    def test_no_error_keeps_the_old_absent_semantics(self):
        from backend.helpers.uds import _build_quality_evaluation
        out = _build_quality_evaluation(self._quick(), None, None)
        assert out["gate_source"] == "quick_only"

    def test_the_sync_generate_route_passes_the_error_through(self):
        from backend.routers import local
        src = Path(local.__file__).read_text(encoding="utf-8")
        i = src.index('report_name="field quality gate report"')
        window = src[i: i + 1500]
        assert "quality_gate_error=" in window, "local generate 가 사이드카 실패 사유를 병합 판정에 넘기지 않는다"


class TestAdvisorThresholdsComeFromConfig:
    def test_rule_thresholds_equal_config(self):
        import config
        from workflow.quality.advisor import _UDS_ADVICE
        t = config.UDS_QUALITY_GATE_THRESHOLDS
        assert _UDS_ADVICE["called_pct"]["threshold"] == t["called_min"]
        assert _UDS_ADVICE["description_pct"]["threshold"] == t["description_min"]
        assert _UDS_ADVICE["asil_pct"]["threshold"] == t["asil_min"]

    def test_helper_reads_config_and_falls_back(self, monkeypatch):
        import config
        from workflow.quality.advisor import _uds_gate_threshold
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {"called_min": 12.5})
        assert _uds_gate_threshold("called_min", 95.0) == 12.5
        assert _uds_gate_threshold("nope_min", 33.0) == 33.0


class TestAdvisorDoesNotContradictAnIndeterminateVerdict:
    """(리뷰 W2) 게이트 항목 0개(판정 불가) run 에 rule 폴백 임계로 "긴급 미달" 을 붙이지 않는다."""

    @pytest.fixture
    def qdb(self, tmp_path, monkeypatch):
        from workflow.quality import db as qdb_mod
        db_file = tmp_path / "q.sqlite"
        monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
        qdb_mod.reset_engine()
        qdb_mod.init_db(db_file)
        yield db_file
        qdb_mod.reset_engine()

    def test_swsa_with_nothing_measured_gets_no_suggestions(self, qdb):
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.recorder import record_run
        rid = record_run("swsa", {"his_metrics": [{"total": 0, "fail": 0, "unbinned": 0}]},
                         project_root=str(qdb.parent), db_path=qdb)
        assert rid > 0
        res = suggest_improvements(rid, db_path=qdb)
        assert res["suggestions"] == []
        assert "판정이 성립하지" in res["summary"]

    def test_measured_swsa_still_gets_suggestions(self, qdb):
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.recorder import record_run
        rid = record_run("swsa", {"his_metrics": [{"total": 10, "fail": 8, "unbinned": 0}]},
                         project_root=str(qdb.parent), db_path=qdb)
        res = suggest_improvements(rid, db_path=qdb)
        assert [s["metric"] for s in res["suggestions"]] == ["his_pass_pct"]


class TestAdvisorThresholdsAreResolvedAtCallTime:
    """(리뷰 W5) import 시점 스냅샷이면 `reexec_config`/env 변경 뒤 게이트와 제안이 다른 숫자가 된다."""

    def test_rule_threshold_follows_config_now(self, monkeypatch):
        import config
        from workflow.quality.advisor import _UDS_ADVICE, _rule_threshold
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {**config.UDS_QUALITY_GATE_THRESHOLDS, "called_min": 12.5})
        assert _rule_threshold(_UDS_ADVICE["called_pct"]) == 12.5
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {**config.UDS_QUALITY_GATE_THRESHOLDS, "called_min": 33.0})
        assert _rule_threshold(_UDS_ADVICE["called_pct"]) == 33.0

    def test_rules_without_a_key_keep_their_literal(self):
        from workflow.quality.advisor import _rule_threshold
        assert _rule_threshold({"threshold": 80.0}) == 80.0
        assert _rule_threshold({"threshold": None}) is None

    def test_uds_rules_all_carry_a_config_key(self):
        import config
        from workflow.quality.advisor import _UDS_ADVICE
        for name, rule in _UDS_ADVICE.items():
            if rule.get("threshold") is None:
                continue
            assert rule.get("threshold_key") in config.UDS_QUALITY_GATE_THRESHOLDS, name


class TestGateDefinitionReachesTheSurfaces:
    """(리뷰 W3) 병합 판정의 사이드카 실패는 `gate_definition:` 마커에만 남는다 — 목록·추세가 그걸 실어야 화면이 그린다."""

    class _S:
        def __init__(self, name, value=1.0):
            self.metric_name, self.value = name, value

    def test_helper_reads_the_marker(self):
        from backend.routers.quality import _gate_definition
        assert _gate_definition([self._S("gate_definition:report_generation_failed")]) == "report_generation_failed"
        assert _gate_definition([self._S("gated_metric_count", 7.0)]) is None
        assert _gate_definition([self._S("gate_definition:")]) is None
        assert _gate_definition(None) is None

    def test_run_dict_and_trend_carry_it(self):
        from backend.routers import quality
        src = Path(quality.__file__).read_text(encoding="utf-8")
        assert src.count('"gate_definition": _gate_definition(') == 2, "목록(_run_to_dict)과 /trend 둘 다 실어야 세 표면이 같다"


class TestStsGateTableDoesNotPassVacuously:
    """(리뷰 W4) SUTS 만 고치고 형제 STS 를 두면 같은 빈 문서를 한쪽은 4/5 통과, 한쪽은 0/3 으로 적는다."""

    def _report(self, tmp_path, tc_count: int):
        from generators.sts import generate_sts_validation_report
        x = tmp_path / "s.xlsm"
        x.write_bytes(b"stub")
        validation = {"valid": tc_count > 0, "issues": [], "warnings": [],
                      "stats": {"tc_count": tc_count, "empty_title_tcs": 0, "no_step_tcs": 0, "no_expected_tcs": 0,
                                "reqs_linked": 0, "sheet_count": 1, "sheets": ["TC"]}}
        out = generate_sts_validation_report(str(x), quality_report={}, validation=validation)
        return Path(out).read_text(encoding="utf-8")

    def test_zero_tcs_marks_ratio_items_not_applicable(self, tmp_path):
        text = self._report(tmp_path, 0)
        assert "## 3. Quality Gate (0/1)" in text
        assert text.count("N/A (TC 없음)") == 4

    def test_with_tcs_all_items_are_judged(self, tmp_path):
        text = self._report(tmp_path, 3)
        gate = text.split("## 3. Quality Gate")[1].split("## ")[0]
        assert "N/A" not in gate
        assert "| 요구사항 연결 존재 | FAIL |" in gate


class TestSutsGateTableDoesNotPassVacuously:
    def _report(self, tmp_path, tc_count: int, seq_count: int):
        from generators.suts import generate_suts_validation_report
        x = tmp_path / "s.xlsm"
        x.write_bytes(b"stub")
        validation = {"valid": tc_count > 0, "issues": [], "warnings": [],
                      "stats": {"tc_count": tc_count, "seq_count": seq_count, "empty_io_tc_count": 0,
                                "avg_seq_per_tc": 0, "sheet_count": 1, "sheets": ["TC"]}}
        out = generate_suts_validation_report(str(x), quality_report={"function_coverage_pct": 50.0}, validation=validation)
        return Path(out).read_text(encoding="utf-8")

    def test_zero_tcs_marks_ratio_items_not_applicable(self, tmp_path):
        text = self._report(tmp_path, 0, 0)
        assert "## 3. Quality Gate (1/3)" in text
        assert text.count("N/A (TC 없음)") == 2
        assert "| I/O 없는 TC < 50% | PASS |" not in text

    def test_with_tcs_all_items_are_judged(self, tmp_path):
        text = self._report(tmp_path, 4, 8)
        assert "N/A" not in text.split("## 3. Quality Gate")[1].split("##")[0]
        assert "## 3. Quality Gate (" in text


# ==============================================================
# W2 — payload 라이터 5곳 원자화 (report_gen/atomic_io.py 단일 출처)
# ==============================================================


class TestPayloadSidecarsAreWrittenAtomically:
    def test_atomic_io_leaves_no_tmp_and_keeps_old_on_failure(self, tmp_path, monkeypatch):
        import os

        from report_gen.atomic_io import atomic_write_text
        out = tmp_path / "p.payload.json"
        atomic_write_text(out, "OLD")
        assert out.read_text(encoding="utf-8") == "OLD"
        assert [p.name for p in tmp_path.iterdir()] == ["p.payload.json"]

        def _boom(*_a, **_k):
            raise OSError("replace failed")
        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(OSError):
            atomic_write_text(out, "NEW")
        assert out.read_text(encoding="utf-8") == "OLD"
        assert [p.name for p in tmp_path.iterdir()] == ["p.payload.json"]

    def test_validation_alias_is_the_same_function(self):
        from report_gen import validation
        from report_gen.atomic_io import atomic_write_text
        assert validation._atomic_write_text is atomic_write_text

    @pytest.mark.parametrize("modname,fn", [
        ("backend.routers.local", "_write_uds_payload_sidecar"),
        ("backend.routers.jenkins", "_write_uds_payload_sidecar"),
        ("backend.helpers.common", "_write_excel_artifact_sidecar"),
    ])
    def test_writer_functions_go_through_atomic_io(self, modname, fn):
        import importlib
        mod = importlib.import_module(modname)
        src = source_of(getattr(mod, fn))
        assert "atomic_write_text(" in src, f"{modname}.{fn}"
        assert ".write_text(" not in src, f"{modname}.{fn} 이 아직 write_text 를 쓴다"

    def test_uds_helper_and_tool_writer_go_through_atomic_io(self):
        root = Path(__file__).resolve().parents[2]
        uds_src = (root / "backend" / "helpers" / "uds.py").read_text(encoding="utf-8")
        assert "sidecar_path.write_text(" not in uds_src
        assert re.search(r"atomic_write_text\(\s*sidecar_path,", uds_src), "uds.py payload 라이터가 atomic_write_text 를 안 쓴다"
        tool_src = (root / "tools" / "generate_uds_local.py").read_text(encoding="utf-8")
        assert "sidecar.write_text(" not in tool_src
        assert "atomic_write_text(sidecar," in tool_src

    def test_local_writer_produces_a_readable_payload(self, tmp_path):
        from backend.routers.local import _write_uds_payload_sidecar
        out = tmp_path / "u.docx"
        p = _write_uds_payload_sidecar(out, {"function_details": {"f": {"name": "f"}}, "summary": {}})
        assert p == tmp_path / "u.payload.json"
        assert json.loads(p.read_text(encoding="utf-8"))["function_details"]["f"]["name"] == "f"
        assert [x.name for x in tmp_path.iterdir()] == ["u.payload.json"]
