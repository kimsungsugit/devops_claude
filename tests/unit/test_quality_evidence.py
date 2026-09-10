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
        assert body["expected_sidecars"] == {"gate_report": False, "confidence": False, "docx_validate": True}
        assert body["sidecars_expected"] is False            # 구 소비처 호환
        assert body["docx_validate"]["format"] == "xlsm"
        assert body["docx_validate"]["ok"] is False
        assert body["gate_report"]["present"] is False

    def test_uds_expects_all_three(self, api, sidecars):
        client, make_run = api
        rid = make_run("uds", output_path=sidecars)
        body = client.get(f"/api/quality/runs/{rid}/evidence").json()
        assert body["expected_sidecars"] == {"gate_report": True, "confidence": True, "docx_validate": True}

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
        assert body["expected_sidecars"] == {"gate_report": False, "confidence": False, "docx_validate": False}
