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

import json
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
        """구판 리포트에 없는 필드는 None(미측정) — 0 으로 접으면 '누락 없음' 이 된다.

        ⚠ 이 테스트는 **음성 대조군일 뿐**이다. 손으로 쓴 구판 .md 를 먹이므로,
          리더가 라벨을 통째로 잘못 알고 있어도 통과한다 — 실제로 2026-09-01 까지
          세 필드가 **한 번도** 채워진 적이 없었는데 이 테스트는 내내 초록이었다.
          양성(진짜 라이터가 쓴 파일에서 수치가 복원되는가)은
          `tests/unit/test_validation_report_roundtrip.py` 가 잰다. 둘은 세트다.
        """
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
        for key in ("gate_report", "confidence", "docx_validate", "reference"):
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


# ═══════════════════════════════════════════════════════════════════════════
# (R47 N22) 같은 `.validation.md` 를 두 계열이 쓴다 — 첫 줄로 형식을 가른다
# ═══════════════════════════════════════════════════════════════════════════

_STS_XLSM_MD = """# STS 생성 문서 자동 검증 리포트

**파일**: `sts_x.xlsm`  
**검증 시각**: 2026-09-09 20:00:41  
**결과**: PASS

---

## 1. 구조 검증

| 항목 | 값 |
|------|-----|
| 시트 수 | 6 |
| TC 수 | 270 |

## 3. Quality Gate (5/5)

| 항목 | 결과 |
|------|------|
| TC 존재 | PASS |
| 빈 제목 < 30% | PASS |
| 스텝 존재 > 50% | PASS |
| 기대값 존재 > 50% | PASS |
| 요구사항 연결 존재 | PASS |

## 5. Warnings

- Optional sheet missing: 1.Introduction
"""

# 라이브 실물(2026-09-09 SUTS): 게이트 5/5 인데 `issues` 때문에 FAIL — 판정과 표는 독립이다.
_SUTS_XLSM_MD = """# SUTS 생성 문서 자동 검증 리포트

**파일**: `suts_x.xlsm`  
**검증 시각**: 2026-09-09 20:07:47  
**결과**: FAIL

---

## 1. 구조 검증

| 항목 | 값 |
|------|-----|
| TC 수 | 1025 |

## 3. Quality Gate (4/5)

| 항목 | 결과 |
|------|------|
| TC 존재 | PASS |
| 시퀀스 존재 | PASS |
| I/O 없는 TC < 50% | FAIL |
| TC당 평균 시퀀스 >= 2 | PASS |
| 함수 커버리지 측정됨 | N/A (TC 없음) |

## 4. Issues

- Optional sheet missing: 1.Introduction

## 5. Warnings

- ⚠ 145/1025 TCs lack I/O variables
"""

# SITS 라이터는 Quality Gate 절이 없고 이슈 절 제목이 한국어다.
_SITS_XLSM_MD = """# SITS 생성 문서 자동 검증 리포트

**파일**: `sits_x.xlsm`  
**검증 시각**: 2026-09-09 20:08:28  
**결과**: PASS

---

## 1. 구조 검증

| 항목 | 값 |
|------|-----|
| TC 수 (SwITC_*) | 120 |

## 3. 이슈

- 이슈 없음

## 4. 경고

- ⚠ 합성 ID 3건
"""


def _write_validation(tmp_path, stem: str, suffix: str, text: str):
    out = tmp_path / f"{stem}{suffix}"
    out.write_bytes(b"x")
    out.with_suffix(".validation.md").write_text(text, encoding="utf-8")
    return out


class TestXlsmValidationFormat:
    """리더가 UDS 라벨로만 읽어 `present:True, ok:None` + null 14개를 내던 것(2026-09-09 실측)."""

    def test_sts_pass_is_read_as_xlsm_with_gate_table(self, tmp_path):
        from report_gen.evidence import read_docx_validation
        out = _write_validation(tmp_path, "sts_x", ".xlsm", _STS_XLSM_MD)
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["present"] is True
        assert got["format"] == "xlsm"
        assert got["doc_kind"] == "STS"
        assert got["ok"] is True
        assert (got["gates_passed"], got["gates_total"]) == (5, 5)
        assert [g["name"] for g in got["gate_items"]][:2] == ["TC 존재", "빈 제목 < 30%"]
        assert got["failed_gates"] == []
        assert got["issues"] == []
        assert got["warnings"] == ["Optional sheet missing: 1.Introduction"]
        assert got["structure"]["TC 수"] == "270"
        assert got["checked_at"] == "2026-09-09 20:00:41"
        # UDS 전용 필드를 null 더미로 싣지 않는다 — 그게 화면이 '판정 불가' 를 그리던 원인이다.
        assert "swufn_headings" not in got and "missing_from_docx" not in got

    def test_suts_fail_is_fail_not_undecidable(self, tmp_path):
        """실패가 '판정 불가' 로 접히던 그 문서 — ok=False 가 그대로 나와야 한다."""
        from report_gen.evidence import read_docx_validation
        out = _write_validation(tmp_path, "suts_x", ".xlsm", _SUTS_XLSM_MD)
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["ok"] is False
        assert (got["gates_passed"], got["gates_total"]) == (4, 5)
        assert got["failed_gates"] == ["I/O 없는 TC < 50%"]
        assert [g["result"] for g in got["gate_items"]] == ["PASS", "PASS", "FAIL", "PASS", "N/A"]
        assert got["issues"] == ["Optional sheet missing: 1.Introduction"]
        assert got["warnings"] == ["145/1025 TCs lack I/O variables"]   # ⚠ 표식 제거

    def test_sits_without_gate_section_keeps_gates_none_not_zero(self, tmp_path):
        from report_gen.evidence import read_docx_validation
        out = _write_validation(tmp_path, "sits_x", ".xlsm", _SITS_XLSM_MD)
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["doc_kind"] == "SITS"
        assert got["ok"] is True
        assert got["gates_passed"] is None and got["gates_total"] is None
        assert got["gate_items"] == []
        assert got["issues"] == []                       # `- 이슈 없음` 은 항목이 아니다
        assert got["warnings"] == ["합성 ID 3건"]

    def test_xlsm_without_warnings_section_means_zero_not_unknown(self, tmp_path):
        """(리뷰 I3) 라이터 셋은 경고가 없으면 절을 생략한다 — 절 부재는 0건이지 미상(None)이 아니다."""
        from report_gen.evidence import read_docx_validation
        text = _SITS_XLSM_MD.split("## 4. 경고")[0]
        out = _write_validation(tmp_path, "sits_nowarn", ".xlsm", text)
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["warnings"] == []

    def test_result_line_missing_is_none_not_pass(self, tmp_path):
        from report_gen.evidence import read_docx_validation
        text = _STS_XLSM_MD.replace("**결과**: PASS\n", "")
        out = _write_validation(tmp_path, "sts_y", ".xlsm", text)
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["format"] == "xlsm" and got["ok"] is None

    def test_uds_docx_format_is_tagged_and_unchanged(self, sidecars):
        from report_gen.evidence import read_docx_validation
        got = read_docx_validation(pathlib.Path(str(sidecars)).with_suffix(".validation.md"))
        assert got["format"] == "docx"
        assert got["ok"] is False and "gate_items" not in got

    def test_unknown_format_is_undecidable_with_reason(self, tmp_path):
        from report_gen.evidence import read_docx_validation
        out = _write_validation(tmp_path, "z", ".xlsm", "# Something else\n\nResult: PASS\n")
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["present"] is True and got["format"] == "unknown"
        assert got["ok"] is None                          # `PASS` 단어가 있어도 통과로 읽지 않는다
        assert "Something else" in got["reason"]

    def test_titleless_kv_text_still_reads_as_docx(self, tmp_path):
        """제목 없는 구판/최소 산출물 — `- 라벨: \\`값\\`` 줄이 있으면 UDS 계열이다."""
        from report_gen.evidence import read_docx_validation
        out = _write_validation(tmp_path, "legacy", ".docx", "# R\n- OK: `False`\n")
        got = read_docx_validation(out.with_suffix(".validation.md"))
        assert got["format"] == "docx" and got["ok"] is False

    def test_dispatch_is_by_content_not_by_extension(self, tmp_path):
        """DB 의 doc_type/확장자가 틀려도 파일 첫 줄이 진실이다."""
        from report_gen.evidence import read_docx_validation
        out = _write_validation(tmp_path, "mislabeled", ".docx", _SUTS_XLSM_MD)
        assert read_docx_validation(out.with_suffix(".validation.md"))["format"] == "xlsm"


class TestExpectedSidecarsPerSection:
    """`sidecars_expected`(UDS 여부 하나)로 접으면 STS 에 "사이드카를 만들지 않는다" 고 적게 된다."""

    def test_sts_expects_validation_but_not_gate_or_confidence(self, api, tmp_path):
        client, make_run = api
        out = _write_validation(tmp_path, "sts_live", ".xlsm", _SUTS_XLSM_MD.replace("SUTS", "STS"))
        rid = make_run("sts", output_path=out)
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["expected_sidecars"] == {"gate_report": False, "confidence": False, "docx_validate": True,
                                             "reference": False}
        assert body["sidecars_expected"] is False            # 구 소비처 호환
        assert body["docx_validate"]["format"] == "xlsm"
        assert body["docx_validate"]["ok"] is False
        assert body["gate_report"]["present"] is False

    def test_uds_expects_all_three(self, api, sidecars):
        client, make_run = api
        rid = make_run("uds", output_path=sidecars)
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["expected_sidecars"] == {"gate_report": True, "confidence": True, "docx_validate": True,
                                             "reference": True}

    @pytest.mark.parametrize("doc_type", ["sts", "suts", "sits"])
    def test_every_xlsm_writer_expects_a_validation_sidecar(self, api, doc_type):
        """(리뷰 W4) 손으로 든 목록 — 항목 하나를 빼면 화면이 "이 문서 종류는 만들지 않는다" 는 거짓을 적는다."""
        client, make_run = api
        rid = make_run(doc_type)
        assert client.get(f"/api/quality/runs/{rid}/evidence").json()["expected_sidecars"]["docx_validate"] is True

    def test_writers_list_matches_the_generators_that_actually_write_the_sidecar(self):
        """목록의 근거는 라이터다 — `generators/*.py` 에서 `.validation.md` 를 쓰는 모듈 + UDS."""
        import re

        from report_gen.evidence import VALIDATION_SIDECAR_WRITERS

        root = pathlib.Path(__file__).resolve().parents[2]
        writers = {p.stem for p in (root / "generators").glob("*.py")
                   if re.search(r'with_suffix\(["\']\.validation\.md["\']\)', p.read_text(encoding="utf-8", errors="replace"))}
        assert writers, "generators 에서 라이터를 하나도 못 찾았다 — 정규식이 죽었다"
        assert set(VALIDATION_SIDECAR_WRITERS) == writers | {"uds"}

    @pytest.mark.parametrize("doc_type", ["swreport", "swut", "swit"])
    def test_builders_without_sidecars_expect_none(self, api, doc_type):
        client, make_run = api
        rid = make_run(doc_type)
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["expected_sidecars"] == {"gate_report": False, "confidence": False, "docx_validate": False,
                                             "reference": False}

# ==============================================================
# 6. 참조 SwUDS 보강 근거 (R47 N26)
# ==============================================================
# run 2058(2026-09-09) 의 gen_stats 엔 `same_project:false · safety_fields_blocked:305` 가 처음부터 적혀
# 있었지만 읽는 화면이 없어 "게이트 23.8%" 의 원인이 두 라운드 동안 보이지 않았다. 이 섹션이 그 기록을
# 근거 엔드포인트 → 보드까지 나른다.

_REF_STATS_2064 = {   # 2026-09-10 run 2064 실측 형태(+ N26 이 추가한 configured/document)
    "mode": "template",
    "reference_suds": {
        "identity": {"same_project": True, "reason": "token_match", "ref_tokens": ["KJPDS02"],
                     "payload_tokens": ["KJPDS02", "NE1AW"], "shared_tokens": ["KJPDS02"]},
        "configured": True,
        "document": "(KJPDS02_SwUDS) Software Unit Design Specification_v3.03_260902.docx",
        "safety_fields_applied": 710, "safety_fields_blocked": 0,
        "descriptive_fields_applied": 877, "invalid_asil_rejected": 0,
        "structural_fields_applied": {"inputs": 412, "outputs": 427, "globals_static": 14,
                                      "globals_global": 306, "called": 375, "calling": 64},
        "structural_fields_blocked": {"inputs": 0, "outputs": 0, "globals_static": 0,
                                      "globals_global": 0, "called": 0, "calling": 0},
    },
}
_REF_STATS_2058 = {   # 2026-09-09 run 2058 실측 형태 — 구판 빌더(configured/document 없음), 참조가 남의 문서
    "mode": "template",
    "reference_suds": {
        "identity": {"same_project": False, "reason": "token_mismatch", "ref_tokens": ["HDPDM01"],
                     "payload_tokens": ["KJPDS02"], "shared_tokens": []},
        "safety_fields_applied": 0, "safety_fields_blocked": 305,
        "descriptive_fields_applied": 385, "invalid_asil_rejected": 1,
        "structural_fields_applied": {"inputs": 0, "outputs": 0, "globals_static": 0,
                                      "globals_global": 0, "called": 0, "calling": 0},
        "structural_fields_blocked": {"inputs": 200, "outputs": 200, "globals_static": 8,
                                      "globals_global": 150, "called": 150, "calling": 50},
    },
}
_PAYLOAD_ENRICHED = {"docx_path": "x", "summary": {}, "function_details": {},
                     "enrichment": {"applied": True, "functions": 1157, "unknown_keys": 0}}


def _ref_sidecars(tmp_path, stats=_REF_STATS_2064, payload=_PAYLOAD_ENRICHED, *, stem="spec", raw_stats=None):
    """`<stem>.docx` + `<stem>.docx.gen_stats.json` + `<stem>.payload.json` — None 이면 그 파일을 만들지 않는다."""
    docx = tmp_path / f"{stem}.docx"
    docx.write_bytes(b"PK\x03\x04dummy")
    if raw_stats is not None:
        (tmp_path / f"{stem}.docx.gen_stats.json").write_text(raw_stats, encoding="utf-8")
    elif stats is not None:
        (tmp_path / f"{stem}.docx.gen_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    if payload is not None:
        (tmp_path / f"{stem}.payload.json").write_text(json.dumps(payload), encoding="utf-8")
    return docx


class TestReferenceEnrichmentSection:

    def test_live_shape_of_run_2064_is_read_whole(self, tmp_path):
        from report_gen.evidence import read_evidence

        ref = read_evidence(str(_ref_sidecars(tmp_path)))["reference"]
        assert ref["present"] is True
        assert ref["document"].endswith("_v3.03_260902.docx") and ref["configured"] is True
        assert ref["same_project"] is True and ref["identity_reason"] == "token_match"
        assert ref["shared_tokens"] == ["KJPDS02"]
        assert (ref["safety_fields_applied"], ref["safety_fields_blocked"]) == (710, 0)
        # (R50 N38) 구판 gen_stats(키 없음)는 미기록 — 0 으로 접지 않는다
        assert ref["safety_fields_overridden"] is None and ref["safety_fields_agreed"] is None
        assert ref["descriptive_fields_applied"] == 877 and ref["invalid_asil_rejected"] == 0
        assert (ref["structural_fields_applied"], ref["structural_fields_blocked"]) == (1598, 0)
        assert ref["enrichment"] == {"present": True, "applied": True, "functions": 1157, "unknown_keys": 0, "reason": None,
                                     "record_source": "payload"}

    @pytest.mark.parametrize("overridden,expected", [
        ({}, 0),                                   # 기록됐고 덮은 게 없다 — 미기록(None)과 다르다
        ({"sds": 3, "module_inherit": 2}, 5),      # 이전 출처별 합
        ({"sds": "?"}, None),                      # 정수가 아닌 축이 있으면 미측정
    ])
    def test_overridden_sum_distinguishes_zero_from_unrecorded(self, tmp_path, overridden, expected):
        """(R50 N38) 뮤테이션 M15: 빈 dict 를 `_int_sum` 에 그대로 넣으면 "덮은 것 없음" 이 "미기록" 으로 접힌다."""
        import copy

        from report_gen.evidence import read_evidence

        stats = copy.deepcopy(_REF_STATS_2064)
        stats["reference_suds"]["safety_fields_overridden"] = overridden
        stats["reference_suds"]["safety_fields_agreed"] = 7
        ref = read_evidence(str(_ref_sidecars(tmp_path, stats=stats)))["reference"]
        assert ref["safety_fields_overridden"] == expected
        assert ref["safety_fields_agreed"] == 7

    def test_foreign_reference_of_run_2058_is_visible_not_silent(self, tmp_path):
        """게이트 23.8% 의 원인 그 자체 — 다른 프로젝트 문서라 305건 차단. 병합 이전 라이터라 enrichment 도 없다."""
        from report_gen.evidence import read_evidence

        payload_legacy = {"docx_path": "x", "summary": {}, "function_details": {}}
        ref = read_evidence(str(_ref_sidecars(tmp_path, _REF_STATS_2058, payload_legacy)))["reference"]
        assert ref["present"] is True
        assert ref["same_project"] is False and ref["identity_reason"] == "token_mismatch"
        assert ref["safety_fields_blocked"] == 305 and ref["safety_fields_applied"] == 0
        assert ref["invalid_asil_rejected"] == 1
        assert ref["structural_fields_blocked"] == 758
        # 구판 통계엔 없는 키 — "모름" 이지 "미지정" 이 아니다.
        assert ref["document"] is None and ref["configured"] is None
        assert ref["enrichment"]["present"] is False and ref["enrichment"]["applied"] is None
        assert "병합하지 않는 라이터" in ref["enrichment"]["reason"]

    def test_undelivered_reference_is_false_not_none(self, tmp_path):
        stats = json.loads(json.dumps(_REF_STATS_2064))
        stats["reference_suds"].update({"configured": False, "document": None})
        stats["reference_suds"]["identity"] = {"same_project": None, "reason": "ref_no_token",
                                               "ref_tokens": [], "payload_tokens": ["KJPDS02"]}
        from report_gen.evidence import read_evidence

        ref = read_evidence(str(_ref_sidecars(tmp_path, stats)))["reference"]
        assert ref["configured"] is False and ref["document"] is None
        assert ref["same_project"] is None and ref["identity_reason"] == "ref_no_token"
        assert ref["shared_tokens"] == []

    def test_enrichment_not_applied_carries_the_builders_reason(self, tmp_path):
        from report_gen.evidence import read_evidence

        payload = {"docx_path": "x", "summary": {}, "function_details": {},
                   "enrichment": {"applied": False, "reason": "빌더가 보강본을 남기지 않음 (spec.docx.function_details.json)"}}
        enr = read_evidence(str(_ref_sidecars(tmp_path, payload=payload)))["reference"]["enrichment"]
        assert enr["present"] is True and enr["applied"] is False and enr["functions"] is None
        assert "남기지 않음" in enr["reason"]

    def test_payload_absent_is_reported_inside_the_section(self, tmp_path):
        from report_gen.evidence import read_evidence

        ref = read_evidence(str(_ref_sidecars(tmp_path, payload=None)))["reference"]
        assert ref["present"] is True                      # 통계는 있으니 섹션은 산다
        assert ref["enrichment"]["present"] is False
        assert "payload 사이드카 없음" in ref["enrichment"]["reason"]

    def test_stats_absent_unreadable_or_without_reference_are_three_different_reasons(self, tmp_path):
        from report_gen.evidence import read_evidence

        for sub in ("a", "b", "c", "d"):
            (tmp_path / sub).mkdir()
        absent = read_evidence(str(_ref_sidecars(tmp_path / "a", stats=None)))["reference"]
        assert absent["present"] is False and "생성 통계 사이드카 없음" in absent["reason"]
        broken = read_evidence(str(_ref_sidecars(tmp_path / "b", raw_stats="{ not json")))["reference"]
        assert broken["present"] is False and "읽기 실패" in broken["reason"]
        old = read_evidence(str(_ref_sidecars(tmp_path / "c", stats={"mode": "template"})))["reference"]
        assert old["present"] is False and "reference_suds 기록 없음" in old["reason"]
        lst = read_evidence(str(_ref_sidecars(tmp_path / "d", raw_stats="[1, 2]")))["reference"]
        assert lst["present"] is False and "dict 가 아님" in lst["reason"]

    def test_all_zero_merge_with_unknown_keys_is_a_failure_not_a_success_of_zero(self, tmp_path):
        """(리뷰 W3) 라이터가 '병합 0건 · 미지 키 n' 을 남기면 되쓰기 실패다 — applied:true 로 내면 화면이 거짓을 그린다."""
        from report_gen.evidence import read_evidence

        payload = {"docx_path": "x", "summary": {}, "function_details": {},
                   "enrichment": {"applied": True, "functions": 0, "unknown_keys": 1157}}
        enr = read_evidence(str(_ref_sidecars(tmp_path, payload=payload)))["reference"]["enrichment"]
        assert enr["applied"] is False and enr["functions"] == 0 and enr["unknown_keys"] == 1157
        assert "하나도 맞지 않아" in enr["reason"]
        # 대조군 — 함수가 0개인 payload 에서 0/0 은 실패가 아니다(미지 키 0).
        payload["enrichment"] = {"applied": True, "functions": 0, "unknown_keys": 0}
        (tmp_path / "spec.payload.json").write_text(json.dumps(payload), encoding="utf-8")
        assert read_evidence(str(tmp_path / "spec.docx"))["reference"]["enrichment"]["applied"] is True

    def test_structural_sum_is_unmeasured_when_any_axis_is_not_an_int(self, tmp_path):
        """(리뷰 W5) `{"inputs": "?", "outputs": 3}` 은 3 이 아니라 미측정이고, 빈 dict 는 0(차단 없음)이 아니다."""
        from report_gen.evidence import _int_sum, read_evidence

        assert _int_sum({}) is None and _int_sum({"a": "x"}) is None and _int_sum({"a": "?", "b": 3}) is None
        assert _int_sum({"a": True, "b": 1}) is None and _int_sum("7") is None
        assert _int_sum({"a": 2, "b": 3}) == 5
        stats = json.loads(json.dumps(_REF_STATS_2064))
        stats["reference_suds"]["structural_fields_blocked"] = {}
        stats["reference_suds"]["structural_fields_applied"]["inputs"] = None
        ref = read_evidence(str(_ref_sidecars(tmp_path, stats)))["reference"]
        assert ref["structural_fields_blocked"] is None and ref["structural_fields_applied"] is None

    def test_suffix_rules_match_the_writers(self):
        """리더의 접미사 두 개는 라이터 규칙의 사본이다 — 갈리면 섹션이 영원히 '없음' 이 된다.

        (리뷰 I4) payload 라이터는 셋(비동기 helpers · jenkins · local) — 셋 다 대조한다. docx 부재 환경은 skip 이 아니라
        경로 규칙 문자열 자체를 소스에서 확인한다.
        """
        from report_gen.evidence import GEN_STATS_SUFFIX, PAYLOAD_SUFFIX

        out = "X:/o/spec.docx"
        try:
            from report_gen.docx_builder import gen_stats_path
        except ImportError:                       # pragma: no cover - docx 없는 환경
            src = (pathlib.Path(__file__).resolve().parents[2] / "report_gen/docx_builder.py").read_text(encoding="utf-8")
            assert f'return Path(str(output_path) + "{GEN_STATS_SUFFIX}")' in src
        else:
            assert pathlib.Path(out + GEN_STATS_SUFFIX) == gen_stats_path(out)
        pytest.importorskip("fastapi")
        from backend.helpers import uds as U
        from backend.routers import jenkins, local
        from tests.unit._source_probe import source_of
        for fn in (jenkins._write_uds_payload_sidecar, local._write_uds_payload_sidecar, U._uds_generate_from_paths):
            assert f'with_suffix("{PAYLOAD_SUFFIX}")' in source_of(fn), fn.__qualname__

    def test_endpoint_exposes_reference_and_expects_it_only_for_uds(self, api, tmp_path):
        client, make_run = api
        rid = make_run("uds", output_path=_ref_sidecars(tmp_path))
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["reference"]["present"] is True and body["reference"]["safety_fields_applied"] == 710
        assert body["expected_sidecars"]["reference"] is True
        rid2 = make_run("sts")
        body2 = client.get(f"/api/quality/runs/{rid2}/evidence").json()
        assert body2["reference"]["present"] is False and body2["reference"]["reason"]
        assert body2["expected_sidecars"]["reference"] is False

    def test_origin_is_carried_when_recorded_and_null_otherwise(self, tmp_path):
        """(R47-d 리뷰 I3) "form" / "registry:<id>" 를 그대로, 기록 없음·비문자열은 None(지어내지 않는다)."""
        import copy

        from report_gen.evidence import read_evidence

        assert read_evidence(str(_ref_sidecars(tmp_path, stem="a")))["reference"]["origin"] is None
        stats = copy.deepcopy(_REF_STATS_2064)
        stats["reference_suds"]["origin"] = "registry:kjpds02_pv"
        assert read_evidence(str(_ref_sidecars(tmp_path, stats, stem="b")))["reference"]["origin"] == "registry:kjpds02_pv"
        stats["reference_suds"]["origin"] = "form"
        assert read_evidence(str(_ref_sidecars(tmp_path, stats, stem="c")))["reference"]["origin"] == "form"
        stats["reference_suds"]["origin"] = 7
        assert read_evidence(str(_ref_sidecars(tmp_path, stats, stem="d")))["reference"]["origin"] is None

    def test_registry_mismatch_is_carried_when_well_formed_and_null_otherwise(self, tmp_path):
        """(R47-e N30) `{"scm_id","form","registry"}` 만 그대로 — 부재·비dict·이름 빈 값은 None(불일치 없음/미기록)."""
        import copy

        from report_gen.evidence import read_evidence

        assert read_evidence(str(_ref_sidecars(tmp_path, stem="a")))["reference"]["registry_mismatch"] is None
        stats = copy.deepcopy(_REF_STATS_2064)
        mm = {"scm_id": "kjpds02_pv", "form": "(OTHER_SwUDS) y.docx", "registry": "(KJPDS02_SwUDS) v3.03.docx"}
        stats["reference_suds"]["registry_mismatch"] = mm
        assert read_evidence(str(_ref_sidecars(tmp_path, stats, stem="b")))["reference"]["registry_mismatch"] == mm
        stats["reference_suds"]["registry_mismatch"] = {"form": "", "registry": "x"}
        assert read_evidence(str(_ref_sidecars(tmp_path, stats, stem="c")))["reference"]["registry_mismatch"] is None
        stats["reference_suds"]["registry_mismatch"] = "yes"
        assert read_evidence(str(_ref_sidecars(tmp_path, stats, stem="d")))["reference"]["registry_mismatch"] is None
        # (리뷰 W2) 대조 상태는 문자열 그대로 — 없으면 None.
        assert read_evidence(str(_ref_sidecars(tmp_path, stem="e")))["reference"]["registry_compare"] is None
        stats["reference_suds"]["registry_compare"] = "unavailable:레지스트리 조회 실패(RuntimeError)"
        got = read_evidence(str(_ref_sidecars(tmp_path, stats, stem="f")))["reference"]["registry_compare"]
        assert got == "unavailable:레지스트리 조회 실패(RuntimeError)"

    def test_every_key_the_board_reads_from_ref_is_produced_by_the_reader(self, tmp_path):
        """보드가 `ref.<키>` / `ref.enrichment.<키>` 로 읽는 이름이 리더 출력에 있어야 한다(형제 가드: `val.`)."""
        import re

        from report_gen.evidence import read_evidence

        board = pathlib.Path(__file__).resolve().parents[2] / "frontend-v2/src/components/sections/DocGenStatusBoard.jsx"
        if not board.exists():                        # pragma: no cover - 경로 이동 대비
            pytest.skip(f"보드 파일 없음: {board}")
        text = board.read_text(encoding="utf-8")
        used = set(re.findall(r"\bref\??\.([a-z_]+)", text))
        used_enr = set(re.findall(r"\bref\.enrichment\??\.([a-z_]+)", text))
        assert "safety_fields_applied" in used and "applied" in used_enr, "가드가 보드의 ref 줄을 못 찾았다"
        ref = read_evidence(str(_ref_sidecars(tmp_path)))["reference"]
        produced = set(ref) | {"reason"}
        assert not sorted(used - produced), f"보드가 읽는데 리더가 안 내는 키: {sorted(used - produced)}"
        assert not sorted(used_enr - set(ref["enrichment"])), sorted(used_enr - set(ref["enrichment"]))


# ==============================================================
# 8. (R47-f N28) 섹션 선택 — attribution 은 payload 를 열지 않는다
# ==============================================================

class TestSectionSelection:
    """근거 1회 열람 = evidence + attribution 두 요청. attribution 이 `confidence` 만 쓰면서 전량을
    부르는 바람에 2.7MB payload 가 요청마다 두 번 파싱됐다(리뷰 W7). 고른 섹션만 읽고, 모르는
    이름은 조용히 빠지지 않는다."""

    def test_default_reads_every_section(self, sidecars):
        from report_gen.evidence import EVIDENCE_SECTIONS, read_evidence

        got = read_evidence(str(sidecars))
        assert set(got) == {"output_path_present", *EVIDENCE_SECTIONS}

    def test_subset_carries_only_the_requested_keys(self, sidecars):
        from report_gen.evidence import read_evidence

        got = read_evidence(str(sidecars), sections=("confidence",))
        assert set(got) == {"output_path_present", "confidence"}
        assert got["confidence"]["present"] is True
        assert got["confidence"]["total_functions"] == 169

    def test_subset_does_not_open_the_reference_sidecars(self, sidecars, monkeypatch):
        """관측량: 참조 리더가 **호출되지 않는다**. 대조군: 전량 호출은 같은 조건에서 터진다."""
        import report_gen.evidence as ev

        def _boom(*_a, **_k):
            raise AssertionError("reference 섹션을 읽었다 — payload 가 파싱됐다")

        monkeypatch.setattr(ev, "read_reference_enrichment", _boom)
        got = ev.read_evidence(str(sidecars), sections=("confidence", "gate_report"))
        assert set(got) == {"output_path_present", "confidence", "gate_report"}
        with pytest.raises(AssertionError, match="payload"):
            ev.read_evidence(str(sidecars))

    def test_unknown_section_is_an_error_not_a_silent_omission(self, sidecars):
        from report_gen.evidence import read_evidence

        with pytest.raises(ValueError, match="confidnce"):
            read_evidence(str(sidecars), sections=("confidnce",))

    def test_empty_selection_is_an_error_not_a_silent_nothing(self, sidecars):
        """(리뷰 W1) `sections=()` 가 통과하면 소비자의 `or {}` 가 "요청 안 함" 을 "사이드카 없음" 으로 번역한다."""
        from report_gen.evidence import read_evidence

        with pytest.raises(ValueError, match="비었다"):
            read_evidence(str(sidecars), sections=())
        with pytest.raises(ValueError, match="비었다"):
            read_evidence("", sections=[])

    def test_section_order_is_this_literal(self, sidecars):
        """(리뷰 뮤턴트 2) 상수 자신과 비교하면 동어반복 — 응답 키 순서를 리터럴로 고정한다."""
        from report_gen.evidence import EVIDENCE_SECTIONS, read_evidence

        assert EVIDENCE_SECTIONS == ("gate_report", "confidence", "docx_validate", "reference")
        assert list(read_evidence(str(sidecars))) == ["output_path_present", *EVIDENCE_SECTIONS]

    def test_every_sidecar_suffix_is_a_readable_section(self):
        """(리뷰 W3) 이름 출처가 둘 — 접미사 표에만 적힌 사이드카는 영구 미판독이 된다. evidence endpoint 의
        `expected_sidecars` 4키도 같은 집합이어야 한다."""
        import re

        from report_gen.evidence import EVIDENCE_SECTIONS, SIDECAR_SUFFIXES

        assert set(SIDECAR_SUFFIXES) <= set(EVIDENCE_SECTIONS)
        src = (pathlib.Path(__file__).resolve().parents[2] / "backend/routers/quality.py").read_text(encoding="utf-8")
        m = re.search(r'payload\["expected_sidecars"\] = \{(.*?)\n    \}', src, re.S)
        assert m, "expected_sidecars 리터럴을 찾지 못했다"
        assert set(re.findall(r'"([a-z_]+)":', m.group(1))) == set(EVIDENCE_SECTIONS)

    def test_missing_output_path_still_shapes_only_the_requested_keys(self):
        from report_gen.evidence import read_evidence

        got = read_evidence("", sections=("reference",))
        assert set(got) == {"output_path_present", "reference"}
        assert got["output_path_present"] is False
        assert got["reference"]["present"] is False
        # (리뷰 W2) 경로 없는 분기도 상수 순 — 호출자 순이 아니다.
        assert list(read_evidence("", sections=("reference", "gate_report"))) == [
            "output_path_present", "gate_report", "reference"]

    def test_order_follows_the_contract_not_the_caller(self, sidecars):
        from report_gen.evidence import EVIDENCE_SECTIONS, read_evidence

        got = read_evidence(str(sidecars), sections=("reference", "gate_report"))
        assert [k for k in got if k != "output_path_present"] == [
            s for s in EVIDENCE_SECTIONS if s in ("reference", "gate_report")]


@pytest.fixture
def attribution_api(tmp_path, monkeypatch, sidecars):
    """`POST /api/docgen/attribution` 용 TestClient + 사이드카를 가리키는 UDS run 하나(임시 quality DB)."""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.routers import docgen_preflight
    from workflow.quality import db as qdb
    from workflow.quality.recorder import record_run

    db_file = tmp_path / "q.db"
    monkeypatch.setattr(qdb, "_default_db_path", lambda: db_file)
    run_id = record_run("uds", {"quick_gate": {"counts": {"total_functions": 169}}},
                        output_path=str(sidecars), db_path=db_file)
    app = FastAPI()
    app.include_router(docgen_preflight.router)
    yield TestClient(app), run_id
    # (리뷰 I4) 형제 `api` fixture 와 같은 관습 — 엔진을 놓아야 tmp 트리 정리가 된다(R44 N19 의 갈래).
    qdb.reset_engine()


class TestAttributionReadsOnlyConfidence:
    """`POST /api/docgen/attribution` 이 근거를 **신뢰도 섹션만** 읽는다 — 행동 + 소스 두 층."""

    def test_endpoint_answers_without_touching_the_payload(self, attribution_api, monkeypatch):
        import report_gen.evidence as ev

        def _boom(*_a, **_k):
            raise AssertionError("attribution 이 reference 섹션(payload)을 읽었다")

        monkeypatch.setattr(ev, "read_reference_enrichment", _boom)
        client, run_id = attribution_api
        res = client.post("/api/docgen/attribution", json={"run_id": run_id})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["available"] is True
        assert body["total_functions"] == 169
        assert {f["field"] for f in body["fields"]} == {"asil", "related", "description"}

    def test_router_source_narrows_the_sections(self):
        src = (pathlib.Path(__file__).resolve().parents[2] / "backend/routers/docgen_preflight.py").read_text(encoding="utf-8")
        assert 'read_evidence(output_path or "", sections=("confidence",))' in src,             "attribution 이 섹션을 좁히지 않거나 호출 포맷이 바뀌었다(재포맷이면 이 리터럴을 갱신)"
        assert 'read_evidence(output_path or "")' not in src
        # (리뷰 W1) 고른 섹션을 `or {}` 로 받으면 "요청 안 함" 이 "사이드카 없음" 으로 번역된다.
        assert 'conf = ev["confidence"]' in src


class TestAttributionChecksWhatTheChainReads:
    """(R47-i N32) 귀속의 "지금 상태" 는 **사슬이 읽는 입력만** 확인하고, 문서 경로가 아닌 3축은 preflight 와 같은 함수로 채운다.

    두 결함이 한 자리에 있었다: ① 해석된 입력 7키 전부를 워커로 찔러 봤는데 `attribute_field` 는 그중 4키만 읽는다
    (`stp`·`template` 은 응답에 없는 IPC). ② preflight 가 채우는 `ai`·`call_graph`·`source_comment` 를 귀속은 안 채워
    같은 run 이 준비 게이트에선 ✓ 인데 귀속 화면은 "현재 상태 확인 안 함" 이었다(R47-f 리뷰 I2).
    """

    class _SpyResolver:
        mode = "local"

        def __init__(self, present):
            self.present = set(present)
            self.asked = []

        def exists(self, p):
            self.asked.append(p)
            return p in self.present

        def is_dir(self, p):
            self.asked.append(p)
            return False

        def list_dir(self, *_a, **_k):
            return []

    _LINKED = {"srs": "U:/reg/srs.docx", "sds": "U:/reg/sds.docx", "uds": "U:/reg/uds.docx",
               "hsis": "U:/reg/hsis.docx", "stp": "U:/reg/stp.docx", "uds_template": "U:/reg/tpl.docx"}

    @staticmethod
    def _entry(linked, source_root):
        import types
        return types.SimpleNamespace(
            source_root=source_root, builder_project_id="",
            linked_docs=types.SimpleNamespace(model_dump=lambda mode="json": dict(linked)))

    @pytest.fixture
    def surfaces(self, attribution_api, monkeypatch, tmp_path):
        """가짜 레지스트리(6키, hsis 만 부재) + 스파이 리졸버 + AI 설정 있음 — 귀속과 preflight 를 같은 요청으로 부른다."""
        import workflow.ai as wai
        from backend.routers import docgen_preflight as dp
        from backend.services import file_resolver as fr
        from backend.services import scm_registry as reg

        spy = self._SpyResolver(present={v for k, v in self._LINKED.items() if k != "hsis"})
        entry = self._entry(self._LINKED, str(tmp_path))
        monkeypatch.setattr(reg, "get_registry_entry", lambda sid: entry if sid == "spy" else None)
        monkeypatch.setattr(fr, "get_resolver", lambda: spy)
        monkeypatch.setattr(wai, "load_oai_config", lambda _p: {"api_key": "k"})
        monkeypatch.setattr(dp, "_read_doc_material",
                            lambda _p: {"ok": False, "reason": "skip", "chars": 0, "items": None})
        dp._cov.clear_cache()
        client, run_id = attribution_api
        return client, run_id, spy, dp

    @staticmethod
    def _rows(body):
        return {r["source"]: r for f in body["fields"] for r in f["rows"]}

    def _attr(self, client, run_id):
        res = client.post("/api/docgen/attribution", json={"run_id": run_id, "scm_id": "spy"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["available"] is True
        return self._rows(body)

    def test_probes_only_inputs_the_chain_reads(self, surfaces):
        client, run_id, spy, _dp = surfaces
        rows = self._attr(client, run_id)
        # 리졸버에 물어본 경로 = 사슬이 읽는 4키뿐 — `stp`·`template` 은 한 번도 안 찌른다(절대 집합).
        assert set(spy.asked) == {"U:/reg/srs.docx", "U:/reg/sds.docx", "U:/reg/uds.docx", "U:/reg/hsis.docx"}, spy.asked
        assert {s: rows[s]["have_now"] for s in ("srs", "sds", "uds", "hsis")} == \
            {"srs": True, "sds": True, "uds": True, "hsis": False}

    def test_derived_axes_are_filled_like_preflight(self, surfaces):
        client, run_id, spy, dp = surfaces
        rows = self._attr(client, run_id)
        # 절대값: 소스 루트(tmp_path)가 있으니 콜그래프 True · AI 설정 있음 True · 주석은 캐시가 없어 모름 ·
        # kb/reference 는 두 표면 다 확인 경로가 없다(모름이 정직).
        expect = {"call_graph": True, "ai": True, "comment": None, "rag": None, "reference": None}
        assert {s: rows[s]["have_now"] for s in expect} == expect
        # 같은 요청의 preflight 사슬과 갈리지 않는다 — 패리티는 위 절대값에 **더하는** 단언이다(한 함수로 합친 뒤엔
        # 패리티만으로는 규칙이 통째로 틀려도 통과한다: R47-h 뮤테이션 M3 의 교훈).
        spy.asked.clear()
        pf = dp._compute_preflight(dp.PreflightRequest(doc_type="uds", scm_id="spy"))
        have = {r["source"]: r["have"] for s in pf["steps"] if s["id"].startswith("chain_") for r in s["chain"]}
        for src in ("call_graph", "ai", "comment", "sds", "srs", "uds", "hsis", "reference", "rag"):
            assert have[src] is rows[src]["have_now"], (src, have[src], rows[src]["have_now"])

    @pytest.mark.parametrize("cov, expect", [
        ({"functions": 4, "description": {"filled": 3, "substantive": 3}}, True),     # 실질 설명 있음
        ({"functions": 4, "description": {"filled": 3, "substantive": 0}}, False),    # 쟀는데 실질 0
        ({"functions": 0, "description": {"filled": 0, "substantive": 0},
          "reason": "소스 루트를 찾을 수 없습니다"}, None),                              # 못 잼 — 없음이 아니다
    ])
    def test_comment_axis_follows_the_cached_measurement(self, surfaces, monkeypatch, cov, expect):
        client, run_id, _spy, dp = surfaces
        monkeypatch.setattr(dp._cov, "cached", lambda *_a, **_k: dict(cov))
        assert self._attr(client, run_id)["comment"]["have_now"] is expect

    @pytest.mark.parametrize("cfg, expect", [
        (lambda _p: {"api_key": "k"}, True),     # 설정 있음 — 그 경로가 열려 있다
        (lambda _p: None, False),                # 설정 파일은 읽었는데 항목 없음 — 확인했고 없음
        (lambda _p: (_ for _ in ()).throw(OSError("unreadable")), None),  # 못 읽음 — 모름(없는 결핍을 만들지 않는다)
    ])
    def test_ai_axis_is_a_setting_not_a_document(self, surfaces, monkeypatch, cfg, expect):
        client, run_id, _spy, _dp = surfaces
        import workflow.ai as wai
        monkeypatch.setattr(wai, "load_oai_config", cfg)
        assert self._attr(client, run_id)["ai"]["have_now"] is expect

    def test_no_source_root_means_no_call_graph(self, surfaces, monkeypatch):
        """소스 루트가 없으면 콜그래프는 '모름' 이 아니라 **없음** — 파싱 산출이라 소스 없이 생길 수 없다(preflight 와 같은 규칙)."""
        client, run_id, _spy, _dp = surfaces
        from backend.services import scm_registry as reg
        entry = self._entry(self._LINKED, "")
        monkeypatch.setattr(reg, "get_registry_entry", lambda sid: entry)
        rows = self._attr(client, run_id)
        assert rows["call_graph"]["have_now"] is False
        assert rows["comment"]["have_now"] is None


class TestEnrichmentFromGenStats:
    """(R47-g N28-b) `reference.enrichment` 는 통계 사이드카의 병기값을 먼저 쓰고, 그때 2.7MB payload 는 열지 않는다.

    run 2070 in-process: `reference` 섹션 74ms·13.7MB 중 거의 전부가 payload 파싱이었다 — 네 값 때문에.
    """

    _GS_WITH = dict(_REF_STATS_2064, enrichment={"applied": True, "functions": 1157, "unknown_keys": 0,
                                                  "source": "spec.docx.function_details.json"})

    def test_gen_stats_copy_is_used_and_payload_is_not_opened(self, tmp_path):
        from report_gen import evidence as ev

        docx = _ref_sidecars(tmp_path, stats=self._GS_WITH, payload=None)   # payload 자체가 없다
        ref = ev.read_evidence(str(docx), sections=("reference",))["reference"]
        assert ref["enrichment"] == {"present": True, "applied": True, "functions": 1157, "unknown_keys": 0, "reason": None,
                                     "record_source": "gen_stats"}
        # 열지 않았다는 직접 증거 — payload 를 "{ not json" 으로 두어도 결과가 같다(열었다면 '읽기 실패' 사유).
        (tmp_path / "spec.payload.json").write_text("{ not json", encoding="utf-8")
        again = ev.read_evidence(str(docx), sections=("reference",))["reference"]["enrichment"]
        assert again["present"] is True and again["applied"] is True and again["functions"] == 1157

    def test_gen_stats_wins_over_payload_when_both_exist(self, tmp_path):
        from report_gen.evidence import read_evidence

        other = {"docx_path": "x", "summary": {}, "function_details": {},
                 "enrichment": {"applied": False, "reason": "payload 쪽 기록"}}
        enr = read_evidence(str(_ref_sidecars(tmp_path, stats=self._GS_WITH, payload=other)))["reference"]["enrichment"]
        assert enr["applied"] is True and enr["functions"] == 1157 and enr["record_source"] == "gen_stats"

    def test_legacy_stats_without_the_key_still_fall_back_to_payload(self, tmp_path):
        """구 run(병기 이전 라이터) — 값은 같고 느릴 뿐이다. 병기가 없는데 payload 도 안 열면 화면이 '기록 없음' 으로 접힌다."""
        from report_gen.evidence import read_evidence

        enr = read_evidence(str(_ref_sidecars(tmp_path)))["reference"]["enrichment"]     # _REF_STATS_2064 엔 enrichment 없음
        assert enr == {"present": True, "applied": True, "functions": 1157, "unknown_keys": 0, "reason": None,
                       "record_source": "payload"}

    def test_non_dict_copy_in_stats_falls_back_to_payload(self, tmp_path):
        from report_gen.evidence import read_evidence

        stats = dict(_REF_STATS_2064, enrichment="applied")
        enr = read_evidence(str(_ref_sidecars(tmp_path, stats=stats)))["reference"]["enrichment"]
        assert enr["applied"] is True and enr["functions"] == 1157 and enr["record_source"] == "payload"

    def test_zero_merge_rule_applies_to_the_stats_copy_too(self, tmp_path):
        """(리뷰 W3 의 규칙은 출처를 가리지 않는다) 통계 쪽 '0건 병합·미지 키 1157' 도 되쓰기 실패다."""
        from report_gen.evidence import read_evidence

        stats = dict(_REF_STATS_2064, enrichment={"applied": True, "functions": 0, "unknown_keys": 1157})
        enr = read_evidence(str(_ref_sidecars(tmp_path, stats=stats, payload=None)))["reference"]["enrichment"]
        assert enr["applied"] is False and enr["functions"] == 0 and enr["unknown_keys"] == 1157
        assert "하나도 맞지 않아" in enr["reason"]
        stats["enrichment"] = {"applied": False, "reason": "빌더가 보강본을 남기지 않음 (spec.docx.function_details.json)"}
        enr = read_evidence(str(_ref_sidecars(tmp_path, stats=stats, payload=None)))["reference"]["enrichment"]
        assert enr["applied"] is False and enr["functions"] is None and "남기지 않음" in enr["reason"]

    def test_record_source_is_none_when_there_is_no_record_at_all(self, tmp_path):
        """(리뷰 W1) 출처 키는 기록이 있을 때만 파일을 가리킨다 — 부재 두 갈래는 None 이지 'payload' 가 아니다."""
        from report_gen.evidence import read_evidence

        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        gone = read_evidence(str(_ref_sidecars(tmp_path / "a", payload=None)))["reference"]["enrichment"]
        assert gone["present"] is False and gone["record_source"] is None
        no_key = read_evidence(str(_ref_sidecars(tmp_path / "b", payload={"docx_path": "x", "summary": {}, "function_details": {}})))["reference"]["enrichment"]
        assert no_key["present"] is False and no_key["record_source"] is None

    def test_both_sources_produce_the_same_shape_for_the_same_record(self, tmp_path):
        """같은 라이터 기록이면 어느 사이드카에서 읽어도 판정이 같다 — 다른 건 `record_source` 뿐이어야 한다."""
        from report_gen.evidence import read_evidence

        for i, rec in enumerate(({"applied": True, "functions": 3, "unknown_keys": 2},
                                 {"applied": True, "functions": 0, "unknown_keys": 5},
                                 {"applied": False, "reason": "보강본 형식이 dict 가 아님"},
                                 {"applied": True, "functions": "?", "unknown_keys": None})):
            a = tmp_path / f"a{i}"
            b = tmp_path / f"b{i}"
            a.mkdir()
            b.mkdir()
            via_stats = read_evidence(str(_ref_sidecars(a, stats=dict(_REF_STATS_2064, enrichment=rec), payload=None)))
            via_payload = read_evidence(str(_ref_sidecars(b, payload={"docx_path": "x", "summary": {}, "function_details": {}, "enrichment": rec})))
            s_enr = dict(via_stats["reference"]["enrichment"])
            p_enr = dict(via_payload["reference"]["enrichment"])
            assert (s_enr.pop("record_source"), p_enr.pop("record_source")) == ("gen_stats", "payload"), rec
            assert s_enr == p_enr, rec


class TestReferenceMatchingSummary:
    """(R51 N40) `reference_suds.matching` → 정수 축만. 구판(키 없음)은 None — "ID 충돌 0" 으로 읽히면 안 된다."""

    def test_legacy_stats_without_matching_are_unrecorded(self, tmp_path):
        from report_gen.evidence import read_evidence

        assert read_evidence(str(_ref_sidecars(tmp_path)))["reference"]["matching"] is None

    def test_matching_ints_pass_through_and_non_ints_are_none(self, tmp_path):
        import copy

        from report_gen.evidence import read_evidence

        stats = copy.deepcopy(_REF_STATS_2064)
        stats["reference_suds"]["matching"] = {"by_name": 896, "by_name_and_id": 46, "id_collision_blocks": 773,
                                               "unmatched_blocks": 37, "unnamed_blocks": 0, "blocked_axes": {"related": 6, "inputs": 2},
                                               "ambiguous_names": "9", "ambiguous_sample": [{"name": "main"}]}
        m = read_evidence(str(_ref_sidecars(tmp_path, stats=stats)))["reference"]["matching"]
        assert m == {"by_name": 896, "by_name_and_id": 46, "id_collision_blocks": 773, "unmatched_blocks": 37,
                     "unnamed_blocks": 0, "blocked_axes": 8, "ambiguous_names": None}

    @pytest.mark.parametrize("blocked,expected", [({}, 0), ({"asil": 1}, 1), (None, None), ({"asil": "x"}, None)])
    def test_blocked_axes_sum_distinguishes_zero_from_unrecorded(self, tmp_path, blocked, expected):
        import copy

        from report_gen.evidence import read_evidence

        stats = copy.deepcopy(_REF_STATS_2064)
        stats["reference_suds"]["matching"] = {"by_name": 1, "blocked_axes": blocked}
        m = read_evidence(str(_ref_sidecars(tmp_path, stats=stats)))["reference"]["matching"]
        assert m["blocked_axes"] == expected and m["by_name"] == 1
