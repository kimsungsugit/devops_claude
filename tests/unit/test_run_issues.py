"""(R48-b) run 문제 목록 `workflow/quality/issues.py` + `GET /api/review/runs/{id}/issues`.

세 출처(생성 시 meta · 사이드카 근거 · DB 점수)를 한 어휘로 모으고 `source` 를 항목마다 적는다. 부재는 항목으로 남긴다
(사이드카 없음 = "근거 없음" 이지 "문제 없음" 이 아니다).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import pytest

pytest.importorskip("fastapi")

from tests.unit.test_quality_evidence import _CONF_MD, _GATE_MD, _VALID_MD  # noqa: E402


@pytest.fixture
def qdb(monkeypatch, tmp_path):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


def _run(db, *, doc_type="uds", output_path: Optional[str] = None, meta: Optional[dict] = None,
         scores: Optional[list] = None) -> int:
    from workflow.quality.db import get_session
    from workflow.quality.models import GenerationRun, QualityScore

    with get_session(db) as s:
        run = GenerationRun(run_uuid=str(uuid.uuid4()), doc_type=doc_type, scm_id="p", status="success",
                            output_path=output_path, output_sha256="a" * 64,
                            meta_json=json.dumps(meta, ensure_ascii=False) if meta is not None else None)
        s.add(run)
        s.flush()
        for name, value, thr, ok in (scores or []):
            s.add(QualityScore(run_id=run.id, metric_name=name, value=value, threshold=thr, gate_pass=ok))
        return run.id


def _collect(db, rid):
    from workflow.quality.db import get_session
    from workflow.quality.issues import collect_run_issues

    with get_session(db) as s:
        return collect_run_issues(s, rid)


def _sidecars(tmp_path, *, gate=_GATE_MD, conf=_CONF_MD, valid=_VALID_MD):
    docx = tmp_path / "spec.docx"
    docx.write_bytes(b"PK\x03\x04dummy")
    if gate is not None:
        (tmp_path / "spec.quality_gate.md").write_text(gate, encoding="utf-8")
    if conf is not None:
        (tmp_path / "spec.field_confidence.md").write_text(conf, encoding="utf-8")
    if valid is not None:
        (tmp_path / "spec.validation.md").write_text(valid, encoding="utf-8")
    return docx


class TestSources:
    def test_generation_issues_from_meta_with_source_tag(self, qdb):
        rid = _run(qdb, meta={"issues": [
            {"code": "report_timeout:accuracy", "severity": "warning", "kind": "actual", "message": "accuracy 300s", "stage": "reports", "facts": {"seconds": 300}},
            {"code": "", "message": "코드 없는 항목은 버린다"},
        ]})
        out = _collect(qdb, rid)
        gen = [i for i in out["issues"] if i["source"] == "generation"]
        assert [(i["code"], i["stage"], i["facts"]) for i in gen] == [("report_timeout:accuracy", "reports", {"seconds": 300})]
        assert out["sources"]["generation"] is True

    def test_missing_meta_key_is_not_recorded(self, qdb):
        rid = _run(qdb, meta={"entry": "x"})
        assert _collect(qdb, rid)["sources"]["generation"] is False
        rid2 = _run(qdb, meta={"issues": []})
        assert _collect(qdb, rid2)["sources"]["generation"] is True   # 빈 목록도 '기록됨'

    def test_sidecar_axes_for_uds(self, qdb, tmp_path):
        docx = _sidecars(tmp_path)
        rid = _run(qdb, output_path=str(docx))
        out = _collect(qdb, rid)
        codes = {i["code"]: i for i in out["issues"]}
        # gate_report: 실패 게이트 2 · TBD 2 · (payload 줄 없음)
        assert codes["gate_fail:traceability_rate"]["severity"] == "error" and codes["gate_fail:traceability_rate"]["kind"] == "actual"
        assert codes["gate_fail:input_fill_rate"]["source"] == "gate_report"
        # 리더가 라벨을 `asil_tbd` 로 정규화한다(`evidence.read_gate_report`) — 코드도 그 키를 쓴다.
        assert codes["tbd_residual:asil_tbd"]["facts"] == {"label": "asil_tbd", "count": 29, "total": 169}
        assert codes["tbd_residual:asil_tbd"]["kind"] == "potential"
        assert codes["tbd_residual:related_tbd"]["facts"]["count"] == 12
        # validation: OK False + issues 1
        assert codes["validation_fail"]["severity"] == "error"
        assert codes["validation_issue"]["message"] == "heading 3개가 빈 명세로 출력됨"
        # confidence B 는 항목 없음
        assert not [c for c in codes if c.startswith("confidence")]
        assert out["sources"] == {"generation": False, "gate_report": True, "docx_validate": True,
                                  "confidence": True, "reference": False, "scores": 0}
        assert out["counts"]["total"] == len(out["issues"])
        assert out["counts"]["actual"] + out["counts"]["potential"] == out["counts"]["total"]

    def test_absent_sidecars_become_items_not_silence(self, qdb, tmp_path):
        docx = _sidecars(tmp_path, gate=None, conf=None, valid=None)
        rid = _run(qdb, output_path=str(docx))
        out = _collect(qdb, rid)
        codes = {i["code"] for i in out["issues"]}
        assert {"evidence_missing:gate_report", "evidence_missing:docx_validate"} <= codes
        assert out["sources"]["gate_report"] is False and out["sources"]["docx_validate"] is False
        for i in out["issues"]:
            assert i["kind"] == "potential" and i["severity"] == "risk"

    def test_non_uds_reads_only_validation(self, qdb, tmp_path):
        docx = _sidecars(tmp_path)
        rid = _run(qdb, doc_type="sts", output_path=str(docx))
        out = _collect(qdb, rid)
        assert out["sources"]["gate_report"] is None and out["sources"]["confidence"] is None
        assert not [i for i in out["issues"] if i["source"] in ("gate_report", "confidence", "reference")]
        assert any(i["code"] == "validation_fail" for i in out["issues"])

    def test_scores_below_threshold(self, qdb):
        rid = _run(qdb, scores=[("description_pct", 60.0, 90.0, False), ("asil_pct", 95.0, 90.0, True),
                                ("gate_reason:no_gated_metric", 1.0, None, False)])
        out = _collect(qdb, rid)
        sc = [i for i in out["issues"] if i["source"] == "scores"]
        assert [(i["code"], i["facts"]) for i in sc] == [("score_below_threshold:description_pct", {"metric": "description_pct", "value": 60.0, "threshold": 90.0})]
        assert out["sources"]["scores"] == 1

    def test_no_output_path_is_disclosed(self, qdb):
        rid = _run(qdb)
        out = _collect(qdb, rid)
        assert out["output_path_present"] is False
        assert any(i["code"] == "output_path_unrecorded" for i in out["issues"])

    def test_missing_file_is_disclosed(self, qdb, tmp_path):
        rid = _run(qdb, output_path=str(tmp_path / "gone.docx"))
        out = _collect(qdb, rid)
        assert any(i["code"] == "output_file_missing" for i in out["issues"])

    def test_validation_issue_overflow_is_capped_and_counted(self, qdb, tmp_path):
        from workflow.quality.issues import LIST_CAP

        many = _VALID_MD.replace("- heading 3개가 빈 명세로 출력됨", "\n".join(f"- issue {i}" for i in range(LIST_CAP + 5)))
        docx = _sidecars(tmp_path, valid=many)
        rid = _run(qdb, output_path=str(docx))
        out = _collect(qdb, rid)
        shown = [i for i in out["issues"] if i["code"] == "validation_issue"]
        over = [i for i in out["issues"] if i["code"] == "validation_issue_overflow"]
        assert len(shown) == LIST_CAP and over and over[0]["facts"] == {"total": LIST_CAP + 5, "shown": LIST_CAP}

    def test_run_not_found(self, qdb):
        from workflow.quality.issues import RunNotFound

        with pytest.raises(RunNotFound):
            _collect(qdb, 999)


class TestRouter:
    def _app(self, user="reader"):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from backend.dependencies.auth import require_jwt_user, require_user
        from backend.error_handler import http_exception_handler
        from backend.routers import review

        app = FastAPI()
        app.add_exception_handler(HTTPException, http_exception_handler)
        app.include_router(review.router)
        app.dependency_overrides[require_user] = lambda: user
        app.dependency_overrides[require_jwt_user] = lambda: user
        return TestClient(app)

    def test_get_issues_is_login_only_and_404_for_missing(self, qdb, tmp_path):
        docx = _sidecars(tmp_path)
        rid = _run(qdb, output_path=str(docx))
        c = self._app()
        r = c.get(f"/api/review/runs/{rid}/issues")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] == rid and body["counts"]["total"] > 0
        assert "output_path" not in body   # 서버 절대경로는 싣지 않는다
        assert c.get("/api/review/runs/999999/issues").status_code == 404

    def test_explain_defaults_to_rule_when_llm_off(self, qdb, tmp_path):
        docx = _sidecars(tmp_path)
        rid = _run(qdb, output_path=str(docx))
        c = self._app()
        r = c.post(f"/api/review/runs/{rid}/issues/explain", json={"use_llm": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["generated_by"] == "rule" and body["llm_reason"] == "LLM 사용 안 함"
        assert len(body["items"]) == body["items_total"]
        assert all(i["action"] for i in body["items"])
        assert c.post(f"/api/review/runs/{rid}/issues/explain", json={"use_llm": False, "extra": 1}).status_code == 422
        assert c.post("/api/review/runs/999999/issues/explain", json={}).status_code == 404
