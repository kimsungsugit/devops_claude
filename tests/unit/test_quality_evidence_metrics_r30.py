"""R30 — generation evidence reaches the quality gate board and the review issue list (never the verdict).

2026-09-27 the user asked whether the work shows "in web document generation and the gates". It showed on the web
status board (generation disclosures) only: no gate read any of it. Now the evaluator records the evidence as
**non-gated** metrics — they are rows of the quality gate's run-detail table, labelled (trends carry only score and
verdict, and advice skips metrics without a threshold); pass/fail and the score are untouched (the module's policy for
new axes) — and warning-tone disclosures become review issues.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from workflow.quality.advisor import advice_for
from workflow.quality.evaluator import compute_gate_verdict, evaluate_sits, evaluate_sts, evaluate_suts

REPO = Path(__file__).resolve().parents[2]

STS_RB = {"tcs": 41, "facts": 146, "facts_used": 56, "steps": 168, "traced:tcs": 59,
          "system_documents": [{"doc": "SyRS", "file": "a.docx", "blocks": 115},
                               {"doc": "SyDS", "file": "b.docx", "error": "PackageNotFoundError: x"}],
          "system_input_skips": ["SyDS: 파일 없음"]}
SUTS_EVIDENCE = {"expected_evidence_summary": {"total": 200, "derived": 50, "unknown": 150},
                 "mcdc_design_summary": {"decisions": 40, "designed": 30, "invalidated_pairs": 2},
                 "source_findings": {"findings": 16, "functions": 9}}
SITS_EVIDENCE = {"integration_oracle": {"status": "evaluated", "cells": 400, "derived": 100},
                 "interface_contract": {"distinct_cross_module_calls": 12}}


def _sts(**gs):
    return {"total_test_cases": 10, "completeness_pct": 100.0, "requirement_coverage": {"covered_pct": 90.0, "total_reqs": 5},
            "generation_stats": gs}


def _by(metrics):
    return {m["metric_name"]: m for m in metrics}


def test_sts_evidence_metrics_are_recorded_and_never_gated():
    m = _by(evaluate_sts(_sts(requirement_boundary=STS_RB)))
    assert m["requirement_boundary_tcs"]["value"] == 41 and m["requirement_boundary_failed"]["value"] == 0
    assert m["requirement_boundary_fact_use_pct"]["value"] == round(56 / 146 * 100, 2)
    assert m["traced_system_documents_read"]["value"] == 1 and m["traced_system_documents_unread"]["value"] == 2
    assert m["traced_system_boundary_tcs"]["value"] == 59
    new = [k for k in m if k.startswith(("requirement_boundary", "traced_system"))]
    assert new and all(m[k]["threshold"] is None and m[k]["gate_pass"] is None for k in new)


_EVIDENCE_RUNS = {
    "sts": (lambda: evaluate_sts(_sts()), lambda: evaluate_sts(_sts(requirement_boundary=STS_RB))),
    "suts": (lambda: evaluate_suts({"total_test_cases": 5, "function_coverage_pct": 90.0, "io_coverage_pct": 80.0}),
             lambda: evaluate_suts({"total_test_cases": 5, "function_coverage_pct": 90.0, "io_coverage_pct": 80.0,
                                    **SUTS_EVIDENCE})),
    "sits": (lambda: evaluate_sits({"total_test_cases": 4, "requirement_traceability_pct": 80.0, "io_coverage_pct": 70.0}),
             lambda: evaluate_sits({"total_test_cases": 4, "requirement_traceability_pct": 80.0, "io_coverage_pct": 70.0,
                                    **SITS_EVIDENCE})),
}


@pytest.mark.parametrize("doc_type", sorted(_EVIDENCE_RUNS))
def test_no_evidence_metric_is_gated_and_verdict_and_score_do_not_move(doc_type):
    # (review W5) a gated evidence metric would flip existing projects — for all three documents
    from workflow.quality.evaluator import compute_overall_score
    plain, with_ev = (f() for f in _EVIDENCE_RUNS[doc_type])
    new = [m for m in with_ev if m["metric_name"] not in {x["metric_name"] for x in plain}]
    assert new and all(m["threshold"] is None and m["gate_pass"] is None for m in new)
    assert compute_gate_verdict(plain) == compute_gate_verdict(with_ev)
    assert compute_overall_score(plain) == compute_overall_score(with_ev)


def test_the_fallback_score_of_a_run_with_no_gated_metric_ignores_the_evidence():
    # (review r2 I-2) with no thresholded metric the score averages every `_pct` — an evidence ratio moved it 0 → 5
    from workflow.quality.evaluator import compute_overall_score
    plain = evaluate_suts({"total_test_cases": 0})
    with_ev = evaluate_suts({"total_test_cases": 0, "mcdc_design_summary": {"decisions": 10, "designed": 2},
                             "expected_evidence_summary": {"total": 10, "derived": 10}})
    assert compute_gate_verdict(plain)["gated_count"] == compute_gate_verdict(with_ev)["gated_count"] == 0
    assert compute_overall_score(plain) == compute_overall_score(with_ev)


def test_the_verdict_is_the_same_with_and_without_the_evidence():
    base = compute_gate_verdict(evaluate_sts(_sts()))
    with_ev = compute_gate_verdict(evaluate_sts(_sts(requirement_boundary={"error": "RuntimeError: x"})))
    assert base == with_ev
    base = compute_gate_verdict(evaluate_suts({"total_test_cases": 5, "function_coverage_pct": 90.0, "io_coverage_pct": 80.0}))
    with_ev = compute_gate_verdict(evaluate_suts({"total_test_cases": 5, "function_coverage_pct": 90.0,
                                                  "io_coverage_pct": 80.0, **SUTS_EVIDENCE}))
    assert base == with_ev


def test_the_overall_score_is_the_same_with_and_without_the_evidence():
    # the score averages thresholded metrics only — the evidence carries no threshold
    from workflow.quality.evaluator import compute_overall_score
    assert compute_overall_score(evaluate_sts(_sts())) == \
        compute_overall_score(evaluate_sts(_sts(requirement_boundary=STS_RB)))
    plain = {"total_test_cases": 5, "function_coverage_pct": 90.0, "io_coverage_pct": 80.0}
    assert compute_overall_score(evaluate_suts(plain)) == compute_overall_score(evaluate_suts({**plain, **SUTS_EVIDENCE}))


def test_an_artifact_without_the_blocks_gets_no_evidence_metrics_and_a_failure_is_one_row():
    names = set(_by(evaluate_sts(_sts())))
    assert not any(k.startswith(("requirement_boundary", "traced_system")) for k in names)
    m = _by(evaluate_sts(_sts(requirement_boundary={"error": "RuntimeError: x"})))
    assert m["requirement_boundary_failed"]["value"] == 1 and "requirement_boundary_tcs" not in m
    # before R29 there is no system_documents list: nothing about the trace is claimed; no document given = 0 read
    m = _by(evaluate_sts(_sts(requirement_boundary={"tcs": 1, "facts": 0})))
    assert "traced_system_documents_read" not in m and "requirement_boundary_fact_use_pct" not in m
    m = _by(evaluate_sts(_sts(requirement_boundary={"tcs": 1, "system_documents": []})))
    assert m["traced_system_documents_read"]["value"] == 0 and "traced_system_boundary_tcs" not in m
    # (review Info 1) a document read with no system table could not be used: it counts as unread
    m = _by(evaluate_sts(_sts(requirement_boundary={"tcs": 1, "system_documents": [{"doc": "SyRS", "blocks": 0}]})))
    assert (m["traced_system_documents_read"]["value"], m["traced_system_documents_unread"]["value"]) == (0, 1)


def test_suts_evidence_metrics():
    m = _by(evaluate_suts({"total_test_cases": 5, **SUTS_EVIDENCE}))
    assert (m["expected_derived_pct"]["value"], m["expected_derived_cells"]["value"],
            m["expected_unknown_cells"]["value"]) == (25.0, 50, 150)
    assert (m["mcdc_designed_pct"]["value"], m["mcdc_invalidated_pairs"]["value"]) == (75.0, 2)
    assert m["source_findings"]["value"] == 16
    empty = _by(evaluate_suts({"total_test_cases": 5, "expected_evidence_summary": {"total": 0},
                               "mcdc_design_summary": {"decisions": 0}}))
    assert "expected_derived_pct" not in empty and "mcdc_designed_pct" not in empty   # no denominator: no 0 %
    assert empty["mcdc_invalidated_pairs"]["value"] == 0


def test_sits_evidence_metrics():
    m = _by(evaluate_sits({"total_test_cases": 4, **SITS_EVIDENCE}))
    assert (m["integration_expected_derived_pct"]["value"], m["integration_expected_derived_cells"]["value"]) == (25.0, 100)
    assert m["integration_oracle_evaluated"]["value"] == 1 and m["interface_contract_failed"]["value"] == 0
    m = _by(evaluate_sits({"total_test_cases": 4, "integration_oracle": {"status": "error:ValueError", "cells": 9},
                           "interface_contract": {"error": "x"}}))
    assert m["integration_oracle_evaluated"]["value"] == 0 and "integration_expected_derived_pct" not in m
    assert m["interface_contract_failed"]["value"] == 1


@pytest.mark.parametrize("status", ["no_project_context", "project_context_schema_mismatch:v3", "tree_sitter_unavailable"])
def test_an_oracle_that_never_ran_is_not_recorded_as_success(status):
    # (review W1) the producer's not-run statuses: "failed 0" read as success — record "evaluated 0"
    m = _by(evaluate_sits({"total_test_cases": 4, "integration_oracle": {"status": status}}))
    assert m["integration_oracle_evaluated"]["value"] == 0 and "integration_expected_derived_pct" not in m
    assert "integration_oracle_failed" not in m


@pytest.mark.parametrize("doc_type, metrics", [
    ("sts", lambda: evaluate_sts(_sts(requirement_boundary=STS_RB))),
    ("suts", lambda: evaluate_suts({"total_test_cases": 5, **SUTS_EVIDENCE})),
    ("sits", lambda: evaluate_sits({"total_test_cases": 4, **SITS_EVIDENCE})),
])
def test_every_new_metric_has_a_label_in_the_advisor_and_on_the_board(doc_type, metrics):
    # set difference against what the evaluator emits — not a hand list (a hand list would be a copy to drift)
    rules, _axis = advice_for(doc_type)
    shared = (REPO / "frontend-v2/src/metricLabels.js").read_text(encoding="utf-8")
    labels = set(re.findall(r"\b([a-z_]+):\s*'", shared[shared.index("METRIC_LABELS"):shared.index("metricLabel =")]))
    new = {m["metric_name"] for m in metrics()} - {m["metric_name"] for m in {
        "sts": lambda: evaluate_sts(_sts()), "suts": lambda: evaluate_suts({"total_test_cases": 5}),
        "sits": lambda: evaluate_sits({"total_test_cases": 4})}[doc_type]()}
    assert new, "the evidence produced no metric"
    assert new <= set(rules), f"no advisor label: {sorted(new - set(rules))}"
    assert all(rules[k].get("threshold") is None for k in new)
    assert new <= labels, f"no board label: {sorted(new - labels)}"
    # (review W6) the gate run-detail table is where these rows are seen — it renders the shared labels
    gate = (REPO / "frontend-v2/src/components/sections/QualityGateSection.jsx").read_text(encoding="utf-8")
    assert "import { metricLabel } from '../../metricLabels.js';" in gate and "{metricLabel(s.metric_name)}" in gate


# ── review issue list ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def qdb(monkeypatch, tmp_path):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


def _issues_for(db, tmp_path, quality_report, artifact="sts"):
    import uuid

    from workflow.quality.db import get_session
    from workflow.quality.issues import collect_run_issues
    from workflow.quality.models import GenerationRun

    out = tmp_path / "doc.xlsm"
    out.write_bytes(b"PK\x03\x04x")
    (tmp_path / "doc.payload.json").write_text(json.dumps({"artifact_type": artifact, "quality_report": quality_report},
                                                          ensure_ascii=False), encoding="utf-8")
    with get_session(db) as s:
        run = GenerationRun(run_uuid=str(uuid.uuid4()), doc_type=artifact, scm_id="p", status="success",
                            output_path=str(out), output_sha256="a" * 64)
        s.add(run)
        s.flush()
        rid = run.id
    with get_session(db) as s:
        return collect_run_issues(s, rid)


def test_warning_disclosures_become_review_issues_and_info_ones_do_not(qdb, tmp_path):
    qr = _sts(requirement_boundary={"error": "RuntimeError: late failure"})
    qr["total_test_cases"] = 10
    out = _issues_for(qdb, tmp_path, qr)
    disc = [i for i in out["issues"] if i["source"] == "generation_disclosures"]
    assert [i["code"] for i in disc] == ["disclosure:sts_requirement_boundary"]
    assert disc[0]["severity"] == "warning" and disc[0]["kind"] == "potential"
    assert "late failure" in disc[0]["message"] and out["sources"]["generation_disclosures"] == 1
    # an all-info report: the source is present, no issue from it (0, not None)
    ok = _issues_for(qdb, tmp_path, _sts(requirement_boundary={"tcs": 1, "facts": 3, "facts_used": 1}))
    assert not [i for i in ok["issues"] if i["source"] == "generation_disclosures"]
    assert ok["sources"]["generation_disclosures"] == 0


def test_missing_disclosures_are_no_evidence_for_sts_and_not_applicable_elsewhere(qdb, tmp_path):
    # (review W2) an STS whose disclosures cannot be read is "evidence missing" (False) — the list says so; a document
    #   type that writes no disclosures is "not applicable" (None)
    out = _issues_for(qdb, tmp_path, {})           # empty quality_report — generation did not finish
    assert out["sources"]["generation_disclosures"] is False
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = _issues_for(qdb, other_dir, {}, artifact="swsa")
    assert other["sources"]["generation_disclosures"] is None


def test_the_disclosing_doc_types_come_from_the_disclosure_module(qdb, tmp_path, monkeypatch):
    # (review r2 W7) a new document type that starts writing disclosures is "evidence missing" at once — no hand list
    import report_gen.generation_disclosures as gdm
    monkeypatch.setattr(gdm, "DISCLOSURE_DOC_TYPES", frozenset(gdm.DISCLOSURE_DOC_TYPES | {"swsa"}))
    out = _issues_for(qdb, tmp_path, {}, artifact="swsa")
    assert out["sources"]["generation_disclosures"] is False


def test_a_long_warning_keeps_its_reason_and_says_it_was_cut(qdb, tmp_path):
    # (review W3) the note ends with the reason; a head-only cut lost it
    rb = {"tcs": 1, "facts": 2, "facts_used": 1, "traced:tcs": 3,
          "traced_facts_by_block": {f"SySM_{i:02d}": 30 - i for i in range(10)}, "traced_blocks_used": 10,
          "system_documents": [{"doc": "SyRS", "file": "a" * 60 + ".docx", "blocks": 115},
                               {"doc": "SyDS", "file": "b.docx", "error": "PackageNotFoundError: gone"}]}
    out = _issues_for(qdb, tmp_path, _sts(requirement_boundary=rb))
    (it,) = [i for i in out["issues"] if i["code"] == "disclosure:sts_traced_system_boundary"]
    assert len(it["message"]) <= 400 and "PackageNotFoundError: gone" in it["message"]
    assert it["message"].endswith("(전문: 생성 공시)") and "**" not in it["message"]


@pytest.mark.parametrize("text, expected", [
    (r"FileNotFoundError: [Errno 2] No such file: 'D:\Project\Ados\secret\SyRS_v3.docx'",
     "FileNotFoundError: [Errno 2] No such file: 'SyRS_v3.docx'"),
    (r"PermissionError: C:\Users\someone\app.c denied", "PermissionError: app.c denied"),
    (r"unc \\server\share\dir\x.docx end", "unc x.docx end"),
    ("posix /home/user/data/f.xlsm tail", "posix f.xlsm tail"),
    ("quoted 'U:/연구소/1000 프로젝트/SyRS.docx' ok", "quoted 'SyRS.docx' ok"),
    # not paths: units, a slash between two values, a drive letter alone
    ("speed 1.3m/s and 4.85V 미만/5.15V 초과 U: 없음", "speed 1.3m/s and 4.85V 미만/5.15V 초과 U: 없음"),
])
def test_paths_in_disclosure_text_are_reduced_to_file_names(text, expected):
    # (review r2 W8) disclosure notes carry exception text — the review list and the LLM prompt get file names only
    from workflow.quality.issues import _basename_paths
    assert _basename_paths(text) == expected


def test_a_warning_issue_never_carries_an_absolute_path(qdb, tmp_path):
    qr = _sts(requirement_boundary={"error": r"FileNotFoundError: 'D:\Project\Ados\PDS64_RD\secret\SyRS_v3.docx'"})
    out = _issues_for(qdb, tmp_path, qr)
    (it,) = [i for i in out["issues"] if i["code"] == "disclosure:sts_requirement_boundary"]
    assert "SyRS_v3.docx" in it["message"] and "PDS64_RD" not in it["message"] and ":\\" not in it["message"]


def test_disclosure_issues_come_after_the_gate_failures(qdb, tmp_path):
    # (review Info 4) the explainer prompt caps its items — a gate failure must not be pushed out by disclosures
    import uuid

    from workflow.quality.db import get_session
    from workflow.quality.issues import collect_run_issues
    from workflow.quality.models import GenerationRun, QualityScore

    out_file = tmp_path / "doc.xlsm"
    out_file.write_bytes(b"PK")
    (tmp_path / "doc.payload.json").write_text(json.dumps({"artifact_type": "sts", "quality_report": _sts(
        requirement_boundary={"error": "RuntimeError: x"})}), encoding="utf-8")
    with get_session(qdb) as s:
        run = GenerationRun(run_uuid=str(uuid.uuid4()), doc_type="sts", scm_id="p", status="success",
                            output_path=str(out_file), output_sha256="a" * 64)
        s.add(run)
        s.flush()
        s.add(QualityScore(run_id=run.id, metric_name="completeness_pct", value=50.0, threshold=80.0, gate_pass=False))
        rid = run.id
    with get_session(qdb) as s:
        codes = [i["code"] for i in collect_run_issues(s, rid)["issues"]]
    assert codes.index("score_below_threshold:completeness_pct") < codes.index("disclosure:sts_requirement_boundary")


def test_the_explainer_has_a_rule_action_for_disclosure_issues():
    from backend.services.issue_explainer import _DEFAULT_ACTION, rule_action
    assert rule_action("disclosure:sts_traced_system_boundary") != _DEFAULT_ACTION
    # (review W4) a source finding is a defect candidate, not a missing input — regenerating does not change it
    assert rule_action("disclosure:suts_source_findings") != rule_action("disclosure:sts_traced_system_boundary")
    assert "재생성으로 사라지지 않는다" in rule_action("disclosure:suts_source_findings")
    src = (REPO / "frontend-v2/src/components/IssueList.jsx").read_text(encoding="utf-8")
    assert "generation_disclosures: '생성 공시'" in src
