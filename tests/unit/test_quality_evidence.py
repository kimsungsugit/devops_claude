"""품질 **근거**(사이드카) 읽기와 `/runs/{id}/evidence` 계약.

## 왜 이 테스트가 있나

게이트가 내는 건 점수와 PASS/FAIL 뿐이고, **그렇게 된 이유**는 DOCX 옆 Markdown
사이드카 세 개에만 있었다 — writer 4곳 / reader 0곳. 화면이 "왜" 를 말할 수 없었다.

읽기를 붙이면서 가장 위험한 건 **부재를 양호로 접는 것**이다. 사이드카가 없는데
`{}` 나 `0` 을 돌려주면 화면은 "근거상 문제 없음" 으로 그린다. 그래서 모든 섹션이
`present` 를 들고, `False` 면 `reason` 이 붙는다 — 아래 테스트 절반이 그 음성
대조군이다.

두 번째 위험은 **문자열 truthy** 다. `.validation.md` 의 `OK: False` 줄을 그대로
JS 로 흘리면 문자열 `'False'` 는 truthy 라 실패가 성공으로 그려진다(이 저장소가
`gate_report.py` 에서 이미 겪었다). 파서가 bool 로 좁히고, 해석 불가면 None 이다.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

_GATE_MD = """# UDS Field Quality Gate Report

- Target DOCX: `X:/out/spec.docx`
- Total functions: `169`
- Gate pass: `False`
- Gates: `3` / `13` passed

## Metrics
- Description fill: `120` / `169` (71.0%)
- Called fill (supported): `160` / `169` (94.7%)
- ASIL non-TBD: `140` / `169` (82.8%)
- Traceability (Related + Supported Call): `52` / `169` (30.8%)

## TBD Residual
- ASIL TBD: `29` / `169`
- Related TBD: `12` / `169`

## Description Quality Grade
- High (comment/SDS/reference): `120` (71.0%)
- Medium (keyword inference): `40` (23.7%)
- Low (generic template): `9` (5.3%)

## Thresholds
- description_fill_rate: `70.0%`

## Failed Gates
- **traceability_rate**: 30.8% < 20.0%
  - 개선 가이드: Related ID 를 SRS 요구와 연결하세요.
- **input_fill_rate**: 10.0% < 20.0%
"""

_CONF_MD = """# ASIL/Related ID Confidence Report

- Total functions: `169`
- Overall confidence score: `0.712` (grade: `B`)
- Low confidence threshold: `< 0.80`

## Description Source
- comment: `120`
- inference: `40`

## ASIL Source
- none

## Related ID Source
- srs: `52`
"""

_VALID_MD = """# UDS Validation Report

- Docx: `X:/out/spec.docx`
- OK: `False`
- Tables: `340`
- Images: `12`
- SwUFn headings: `169`
- FunctionInfo tables: `169`
- Logic rows: `900`

## Issues
- heading 3개가 빈 명세로 출력됨
"""


@pytest.fixture
def sidecars():
    """`spec.docx` 와 형제 사이드카 3종을 만든 임시 디렉터리."""
    d = pathlib.Path(tempfile.mkdtemp())
    docx = d / "spec.docx"
    docx.write_bytes(b"PK\x03\x04dummy")
    (d / "spec.quality_gate.md").write_text(_GATE_MD, encoding="utf-8")
    (d / "spec.field_confidence.md").write_text(_CONF_MD, encoding="utf-8")
    (d / "spec.validation.md").write_text(_VALID_MD, encoding="utf-8")
    return docx


@pytest.fixture
def bare_docx():
    """산출물만 있고 사이드카가 하나도 없는 경우."""
    d = pathlib.Path(tempfile.mkdtemp())
    docx = d / "spec.docx"
    docx.write_bytes(b"PK\x03\x04dummy")
    return docx


# ==============================================================
# 1. 파서 — 있는 것을 정확히 판다
# ==============================================================

class TestGateReportParsing:

    def test_reads_verdict_and_gate_counts(self, sidecars):
        from report_gen.evidence import read_gate_report

        got = read_gate_report(sidecars.with_suffix(".quality_gate.md"))
        assert got["present"] is True
        assert got["gate_pass"] is False
        assert got["gate_pass_status"] == "ok"
        assert got["total_functions"] == 169
        assert (got["gates_passed"], got["gates_total"]) == (3, 13)

    def test_reads_tbd_residual(self, sidecars):
        """TBD 잔여는 `N / M` 에 **괄호가 없어** Metrics 정규식이 못 잡는다."""
        from report_gen.evidence import read_gate_report

        tbd = read_gate_report(sidecars.with_suffix(".quality_gate.md"))["tbd_residual"]
        assert tbd["asil_tbd"] == {"count": 29, "total": 169}
        assert tbd["related_tbd"] == {"count": 12, "total": 169}

    def test_reads_description_quality_grades(self, sidecars):
        from report_gen.evidence import read_gate_report

        dq = read_gate_report(sidecars.with_suffix(".quality_gate.md"))["description_quality"]
        assert dq["high"]["count"] == 120
        assert dq["low"] == {"count": 9, "pct": 5.3}

    def test_failed_gates_carry_their_guide(self, sidecars):
        """개선 가이드가 게이트에 **붙어** 나와야 조치로 이어진다."""
        from report_gen.evidence import read_gate_report

        failed = read_gate_report(sidecars.with_suffix(".quality_gate.md"))["failed_gates"]
        by_name = {f["gate"]: f for f in failed}
        assert "traceability_rate" in by_name
        assert by_name["traceability_rate"]["detail"] == "30.8% < 20.0%"
        assert "Related ID" in by_name["traceability_rate"]["guide"]
        # 가이드가 없는 게이트는 빈 문자열 — 앞 게이트의 가이드가 새면 안 된다
        assert by_name["input_fill_rate"]["guide"] == ""

    def test_metrics_come_from_the_shared_parser(self, sidecars):
        from report_gen.evidence import read_gate_report

        m = read_gate_report(sidecars.with_suffix(".quality_gate.md"))["metrics"]
        assert m["description_fill"]["percent"] == 71.0
        # `Called fill (supported)` 는 라벨이 정규화되어 들어온다
        assert m["called_fill_supported"]["numerator"] == 160

    def test_ambiguous_verdict_is_not_a_pass(self):
        """`Gate pass:` 가 2회면 판정 불가 — 어느 쪽도 고르지 않는다."""
        from report_gen.evidence import read_gate_report

        d = pathlib.Path(tempfile.mkdtemp())
        p = d / "x.quality_gate.md"
        p.write_text(
            "# R\n- Gate pass: `False`\n\n검토 의견: 이전엔 Gate pass: `True` 였다.\n",
            encoding="utf-8",
        )
        got = read_gate_report(p)
        assert got["gate_pass"] is None
        assert got["gate_pass_status"] == "ambiguous"


class TestConfidenceParsing:

    def test_reads_score_and_grade(self, sidecars):
        from report_gen.evidence import read_confidence_report

        got = read_confidence_report(sidecars.with_suffix(".field_confidence.md"))
        assert got["present"] is True
        assert got["overall_score"] == 0.712
        assert got["grade"] == "B"
        assert got["total_functions"] == 169

    def test_none_source_list_is_empty_not_literal(self, sidecars):
        """생산자의 `- none` 은 목록 없음이지 'none' 이라는 출처가 아니다."""
        from report_gen.evidence import read_confidence_report

        got = read_confidence_report(sidecars.with_suffix(".field_confidence.md"))
        assert got["asil_sources"] == []
        assert got["description_sources"] == ["comment: `120`", "inference: `40`"]


class TestDocxValidationParsing:

    def test_ok_false_is_boolean_false(self, sidecars):
        """문자열 `'False'` 를 그대로 흘리면 JS 에서 truthy 라 FAIL 이 PASS 가 된다."""
        from report_gen.evidence import read_docx_validation

        got = read_docx_validation(sidecars.with_suffix(".validation.md"))
        assert got["ok"] is False
        assert got["tables"] == 340
        assert got["issues"] == ["heading 3개가 빈 명세로 출력됨"]

    def test_unparseable_ok_is_none_not_false(self):
        """해석 불가는 '실패' 가 아니라 '판정 불가' 다."""
        from report_gen.evidence import read_docx_validation

        d = pathlib.Path(tempfile.mkdtemp())
        p = d / "x.validation.md"
        p.write_text("# R\n- OK: `maybe`\n", encoding="utf-8")
        assert read_docx_validation(p)["ok"] is None

    def test_fields_absent_in_old_reports_are_none_not_zero(self, sidecars):
        """신판에만 있는 필드는 None(미측정) — 0 으로 접으면 '누락 없음' 이 된다."""
        from report_gen.evidence import read_docx_validation

        got = read_docx_validation(sidecars.with_suffix(".validation.md"))
        assert got["expected_functions"] is None
        assert got["matched_functions"] is None
        assert got["missing_from_docx"] is None


# ==============================================================
# 2. 부재 — 절대 양호로 접지 않는다 (음성 대조군)
# ==============================================================

class TestAbsenceIsExplicit:

    def test_missing_sidecar_is_present_false_with_reason(self, bare_docx):
        from report_gen.evidence import read_evidence

        got = read_evidence(str(bare_docx))
        assert got["output_path_present"] is True  # docx 는 있다
        for key in ("gate_report", "confidence", "docx_validate"):
            assert got[key]["present"] is False, key
            assert got[key].get("reason"), f"{key}: 부재 사유가 비었다"

    def test_absent_section_is_not_an_empty_dict(self, bare_docx):
        """`{}` 를 돌려주면 소비처의 `if (!x)` 가 '문제 없음' 으로 읽는다."""
        from report_gen.evidence import read_evidence

        got = read_evidence(str(bare_docx))
        assert got["gate_report"] != {}
        assert "gate_pass" not in got["gate_report"]  # 값을 지어내지 않는다

    def test_no_output_path_is_reported_not_crashed(self):
        from report_gen.evidence import read_evidence

        got = read_evidence("")
        assert got["output_path_present"] is False
        assert got["gate_report"]["present"] is False
        assert "경로" in got["gate_report"]["reason"]

    def test_deleted_docx_still_reads_surviving_sidecars(self, sidecars):
        """산출물이 지워져도 사이드카가 남아 있으면 근거는 살아 있다."""
        from report_gen.evidence import read_evidence

        sidecars.unlink()
        got = read_evidence(str(sidecars))
        assert got["output_path_present"] is False
        assert got["gate_report"]["present"] is True


# ==============================================================
# 3. endpoint 계약
# ==============================================================

@pytest.fixture
def api(monkeypatch, tmp_path):
    """quality 라우터 + 격리된 DB. (run 을 만들어 주는 헬퍼를 함께 반환)"""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.dependencies.auth import require_user
    from backend.routers import quality
    from workflow.quality import db as qdb

    db_file = tmp_path / "q.db"
    monkeypatch.setattr(qdb, "_default_db_path", lambda: db_file)

    app = FastAPI()
    app.include_router(quality.router)
    app.dependency_overrides[require_user] = lambda: "tester"
    client = TestClient(app)

    _payloads = {
        "sits": {"requirement_traceability_pct": 80.0, "io_coverage_pct": 90.0,
                 "total_test_cases": 5},
        "uds": {"quick_gate": {"counts": {"total_functions": 169},
                               "rates": {"called_fill": 95.0}}},
    }

    def make_run(doc_type="uds", output_path=None, scm_id=None):
        from workflow.quality.recorder import record_run
        return record_run(
            doc_type,
            _payloads.get(doc_type, {"x": 1}),
            output_path=str(output_path) if output_path else None,
            scm_id=scm_id,
            db_path=db_file,
        )

    return client, make_run


class TestEvidenceEndpoint:

    def test_missing_run_is_404(self, api):
        client, _ = api
        assert client.get("/api/quality/runs/999999/evidence").status_code == 404

    def test_run_without_output_path_is_200_not_404(self, api):
        """run 은 실재한다 — 산출물 경로가 없는 것뿐이다."""
        client, make_run = api
        rid = make_run("uds")
        res = client.get(f"/api/quality/runs/{rid}/evidence")
        assert res.status_code == 200
        body = res.json()
        assert body["output_path_present"] is False
        assert body["gate_report"]["present"] is False
        assert body["gate_report"]["reason"]

    def test_sidecars_are_parsed(self, api, sidecars):
        client, make_run = api
        rid = make_run("uds", output_path=sidecars)
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["run_id"] == rid
        assert body["gate_report"]["gate_pass"] is False
        assert body["gate_report"]["tbd_residual"]["asil_tbd"]["count"] == 29
        assert body["confidence"]["grade"] == "B"
        assert body["docx_validate"]["ok"] is False

    def test_non_uds_marks_sidecars_as_not_expected(self, api):
        """UDS 아닌 doc_type 의 `present:false` 는 결함이 아니라 정상이다."""
        client, make_run = api
        rid = make_run("sits")
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["sidecars_expected"] is False

    def test_uds_marks_sidecars_as_expected(self, api, sidecars):
        client, make_run = api
        rid = make_run("uds", output_path=sidecars)
        assert client.get(f"/api/quality/runs/{rid}/evidence").json()["sidecars_expected"] is True

    def test_client_cannot_choose_the_path(self, api, sidecars):
        """경로는 서버가 DB 에서 꺼낸다 — 쿼리로 바꿔치기할 입구가 없다."""
        client, make_run = api
        rid = make_run("uds")  # output_path 없음
        body = client.get(
            f"/api/quality/runs/{rid}/evidence",
            params={"output_path": str(sidecars), "path": str(sidecars)},
        ).json()
        # 쿼리를 줘도 사이드카를 읽지 않는다
        assert body["gate_report"]["present"] is False


class TestRouterGuardsItself:
    """라우터 **자체**가 로그인을 요구한다 (미들웨어와 별개의 2중 방어).

    ⚠ 이 클래스가 왜 따로 필요한가 — 뮤테이션으로 드러난 사각이다.
    `test_admin_gate.py` 는 `backend.main.app` 을 쓰는데, 거기선
    `UserContextMiddleware` 가 신원 없는 요청을 **라우터보다 먼저** 401 로 끊는다.
    그래서 라우터의 `dependencies=[Depends(require_user)]` 를 통째로 지워도
    그쪽 테스트는 전부 통과했다(실측: M1 생존). 미들웨어 예외 목록에
    `/api/quality` 가 들어가거나 라우터를 다른 앱에 붙이는 순간 무방비가 된다.

    여기서는 **미들웨어 없는 앱**에 라우터만 붙여 라우터 게이트를 직접 겨눈다.
    """

    def _bare_app_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.routers import quality

        app = FastAPI()
        app.include_router(quality.router)  # dependency override 없음
        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize("path", [
        "/api/quality/runs",
        "/api/quality/policy",
        "/api/quality/trend",
        "/api/quality/runs/1/evidence",
    ])
    def test_unauthenticated_is_401_without_middleware(self, path):
        pytest.importorskip("fastapi")
        res = self._bare_app_client().get(path)
        assert res.status_code == 401, (
            f"미들웨어 없이 {path} 가 {res.status_code} — 라우터의 인증 dependency 가 "
            f"빠졌다. 미들웨어는 유일한 방어선이 아니어야 한다: {res.text[:200]}"
        )


class TestListExposesNewFields:

    def test_scm_id_and_gate_reason_are_exposed(self, api):
        """목록이 새 필드를 실제로 담는다 — 화면이 프로젝트와 사유를 볼 수 있어야 한다."""
        client, make_run = api
        # 알 수 없는 doc_type → 검사 0건 → verdict.reason='no_gated_metric' 이 남는다
        make_run("bogus_type", scm_id="hdpdm01")
        runs = client.get("/api/quality/runs", params={"limit": 5}).json()["runs"]
        assert runs, "방금 기록한 run 이 목록에 없다"
        target = runs[0]
        assert target["scm_id"] == "hdpdm01"
        assert target["gate_reason"] == "no_gated_metric"
        assert "meta" in target

    def test_normal_run_reports_no_gate_reason(self, api):
        """음성 대조군 — 사유가 없으면 None 이지 빈 문자열이 아니다."""
        client, make_run = api
        make_run("sits")
        runs = client.get("/api/quality/runs", params={"limit": 1}).json()["runs"]
        assert runs[0]["gate_reason"] is None

    def test_scm_id_filter_narrows(self, api):
        client, make_run = api
        make_run("sits")
        res = client.get("/api/quality/runs", params={"scm_id": "nonexistent_project"})
        assert res.status_code == 200
        assert res.json()["runs"] == []
