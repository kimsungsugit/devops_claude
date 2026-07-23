"""Regression tests for VectorCAST 복수 경로 cloudium fallback 병합.

부트로더/FBL/APP 등 테스트 결과가 Jenkins와 별도 vectorcast_rag.json으로 나올 수
있어, 사용자가 설정의 SCM '연결 문서 경로'(linked_docs.vectorcast)에 복수 경로를
등록한다. 본 테스트는 다음 순수 함수의 계약을 고정한다:

- _collect_vcast_paths: vcast_log_paths(복수) + vcast_log_path(legacy 단일) 합치고
  슬래시/대소문자 무시 dedup, 순서 보존.
- _merge_vectorcast_payloads: test_rows 합치고 동일 row dedup, summary/failures 재계산.
- _load_vectorcast_rag_from_cloudium_multi: 단일은 원본 보존, 복수는 병합.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.routers.jenkins as J
from backend.schemas import JenkinsReportRequest, ScmLinkedDocs


# ── _collect_vcast_paths ──────────────────────────────────────────────
def test_collect_paths_combines_list_and_legacy() -> None:
    req = JenkinsReportRequest(
        job_url="http://j/job/x",
        cache_root=".cache",
        vcast_log_paths=["U:/a/vectorcast_rag.json", "U:/b"],
        vcast_log_path="U:/c",
    )
    assert J._collect_vcast_paths(req) == [
        "U:/a/vectorcast_rag.json",
        "U:/b",
        "U:/c",
    ]


def test_collect_paths_dedup_slash_and_case() -> None:
    req = JenkinsReportRequest(
        job_url="j",
        cache_root=".c",
        vcast_log_paths=["U:\\Boot\\", "u:/boot", "U:/App"],
        vcast_log_path="U:/APP/",
    )
    # 'U:\\Boot\\' 와 'u:/boot' 는 동일 → 첫 항목만, 'U:/App' 와 'U:/APP/' 동일.
    assert J._collect_vcast_paths(req) == ["U:\\Boot\\", "U:/App"]


def test_collect_paths_empty_and_blank() -> None:
    req = JenkinsReportRequest(
        job_url="j", cache_root=".c",
        vcast_log_paths=["", "   ", "U:/x"], vcast_log_path="",
    )
    assert J._collect_vcast_paths(req) == ["U:/x"]


def test_collect_paths_none_inputs() -> None:
    req = JenkinsReportRequest(job_url="j", cache_root=".c")
    assert J._collect_vcast_paths(req) == []


# ── _merge_vectorcast_payloads ────────────────────────────────────────
def test_merge_concatenates_and_recomputes_summary() -> None:
    boot = {
        "test_rows": [
            {"subprogram": "fbl_init", "testcase": "tc1", "unit": "u1", "result": "PASS", "report": "r1"},
            {"subprogram": "fbl_crc", "testcase": "tc2", "unit": "u1", "result": "FAIL", "report": "r1"},
        ],
        "ut_reports": ["boot/ut.html"],
    }
    app = {
        "test_rows": [
            {"subprogram": "app_main", "testcase": "tc3", "unit": "u2", "result": "PASS", "report": "r2"},
        ],
        "ut_reports": ["app/ut.html"],
    }
    merged = J._merge_vectorcast_payloads([boot, app])
    assert merged["test_rows_count"] == 3
    assert merged["summary"]["total"] == 3
    assert merged["summary"]["passed"] == 2
    assert merged["summary"]["failed"] == 1
    # failures 재계산 — FAIL row 1건만.
    assert len(merged["failures"]) == 1
    assert merged["failures"][0]["subprogram"] == "fbl_crc"
    # ut_reports 합쳐짐.
    assert merged["ut_reports"] == ["boot/ut.html", "app/ut.html"]
    assert merged["merged_sources"] == 2


def test_merge_splits_summary_by_source() -> None:
    """merge가 결합 summary와 별개로 source(UT/IT)별 summary/카운트를 분리 산출한다.

    UT 패널은 summary_ut, IT 패널은 summary_it을 써서 합부가 섞이지 않게 한다.
    """
    ut = {"test_rows": [
        {"subprogram": "u1", "testcase": "t1", "unit": "u", "result": "PASS", "report": "r", "source": "UT"},
        {"subprogram": "u2", "testcase": "t2", "unit": "u", "result": "FAIL", "report": "r", "source": "UT"},
    ]}
    it = {"test_rows": [
        {"subprogram": "i1", "testcase": "t3", "unit": "u", "result": "PASS", "report": "r", "source": "IT"},
    ]}
    merged = J._merge_vectorcast_payloads([ut, it])
    # 결합은 그대로 3건.
    assert merged["summary"]["total"] == 3
    # 분리 카운트/합부.
    assert merged["test_rows_count_ut"] == 2
    assert merged["test_rows_count_it"] == 1
    assert merged["summary_ut"]["passed"] == 1 and merged["summary_ut"]["failed"] == 1
    assert merged["summary_it"]["passed"] == 1 and merged["summary_it"]["failed"] == 0
    # ut + it == 전체 (누락/이중 없음)
    assert merged["test_rows_count_ut"] + merged["test_rows_count_it"] == merged["test_rows_count"]


def test_split_helper_unknown_source_counts_as_ut() -> None:
    """_split_vcast_summary_by_source: source 미상 row는 UT로 귀속(ut+it=전체 보존)."""
    rows = [
        {"result": "PASS"},                    # source 없음 → UT
        {"result": "PASS", "source": "it"},    # 소문자도 IT로 인식
        {"result": "FAIL", "source": "UT"},
    ]
    split = J._split_vcast_summary_by_source(rows)
    assert split["test_rows_count_ut"] == 2 and split["test_rows_count_it"] == 1
    assert split["summary_ut"]["passed"] == 1 and split["summary_ut"]["failed"] == 1
    assert split["summary_it"]["passed"] == 1


def test_split_helper_single_kind_nulls_other() -> None:
    """전부 UT면 summary_it=None, 전부 IT면 summary_ut=None(빈 카드 방지)."""
    ut_only = J._split_vcast_summary_by_source([{"result": "PASS", "source": "UT"}])
    assert ut_only["summary_it"] is None and ut_only["summary_ut"]["total"] == 1
    it_only = J._split_vcast_summary_by_source([{"result": "PASS", "source": "IT"}])
    assert it_only["summary_ut"] is None and it_only["summary_it"]["total"] == 1


def test_merge_dedups_identical_rows() -> None:
    """같은 경로 두 번 등록(또는 부모/자식 경로) → 동일 row 이중 집계 방지."""
    same_row = {"subprogram": "f", "testcase": "tc", "unit": "u", "result": "PASS", "report": "r"}
    p1 = {"test_rows": [dict(same_row)]}
    p2 = {"test_rows": [dict(same_row)]}
    merged = J._merge_vectorcast_payloads([p1, p2])
    assert merged["test_rows_count"] == 1
    assert merged["summary"]["total"] == 1


def test_merge_tolerates_non_dict_and_missing_rows() -> None:
    payloads = [None, {}, {"test_rows": [{"subprogram": "x", "result": "PASS"}]}]
    merged = J._merge_vectorcast_payloads(payloads)  # type: ignore[arg-type]
    assert merged["test_rows_count"] == 1
    # None/{} 는 merged_sources 에서 빈 dict 제외 ({}는 falsy).
    assert merged["merged_sources"] == 1


# ── _load_vectorcast_rag_from_cloudium_multi ──────────────────────────
def test_multi_single_path_returns_raw(monkeypatch) -> None:
    """단일 경로면 원본 payload 필드 보존(병합 미적용) + UT/IT 분리 필드만 추가."""
    raw = {"test_rows": [{"subprogram": "f"}], "build_root": "U:/x", "scanned_at": "t"}
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium", lambda _p: dict(raw))
    out = J._load_vectorcast_rag_from_cloudium_multi(["U:/x"])
    # 원본 필드 보존
    assert out["build_root"] == "U:/x" and out["scanned_at"] == "t"
    assert out["test_rows"] == raw["test_rows"]
    # UT/IT 분리 필드 추가(source 없는 row → UT 귀속).
    assert out["test_rows_count_ut"] == 1 and out["test_rows_count_it"] == 0
    assert out["summary_it"] is None and out["summary_ut"]["total"] == 1


def test_multi_merges_when_two_paths(monkeypatch) -> None:
    table = {
        "U:/boot": {"test_rows": [{"subprogram": "b", "result": "PASS"}]},
        "U:/app": {"test_rows": [{"subprogram": "a", "result": "FAIL"}]},
    }
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium", lambda p: dict(table.get(p, {})))
    out = J._load_vectorcast_rag_from_cloudium_multi(["U:/boot", "U:/app"])
    assert out["test_rows_count"] == 2
    assert out["summary"]["passed"] == 1
    assert out["summary"]["failed"] == 1


def test_multi_skips_empty_payloads(monkeypatch) -> None:
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium", lambda p: {} if p == "U:/empty" else {"test_rows": [{"subprogram": "f", "result": "PASS"}]})
    # empty 하나 + 실데이터 하나 → 실데이터만 → 단일 취급 (원본 보존).
    out = J._load_vectorcast_rag_from_cloudium_multi(["U:/empty", "U:/real"])
    assert out["test_rows"] == [{"subprogram": "f", "result": "PASS"}]


def test_multi_all_empty_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium", lambda _p: {})
    assert J._load_vectorcast_rag_from_cloudium_multi(["U:/a", "U:/b"]) == {}


# ── _parse_vcast_logs_from_cloudium_folder (원본 리포트 직접 파싱) ──────
class _FakeRow:
    """swut_input_adapter.ExecutionRow stub — passed/subprogram/component만 사용."""
    def __init__(self, passed: bool, subprogram: str = "", component: str = "") -> None:
        self.passed = passed
        self.subprogram = subprogram
        self.component = component


class _FakeResolver:
    mode = "cloudium"
    def exists(self, _p):  # tc 폴더 존재 검사용
        return True


def _patch_folder_parse(monkeypatch, *, exec_results, tc_files=None):
    """_parse_vcast_logs_from_cloudium_folder가 호출하는 SA 헬퍼/resolver를 모킹.

    실제 VC2025_LAYOUT을 재사용해 extract_env(suffix-strip) 동작까지 검증한다.
    """
    import backend.services.swut_input_adapter as SA
    import backend.services.file_resolver as FR

    if tc_files is None:
        tc_files = ["SwUT_01_Lib_sha256_TestCaseDataReport.html"]
    monkeypatch.setattr(FR, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(SA, "_resolve_latest_release_folder",
                        lambda r, p, out_warnings=None: p)
    monkeypatch.setattr(SA, "_detect_log_layout",
                        lambda r, folder, w=None: SA.VC2025_LAYOUT)
    monkeypatch.setattr(SA, "_exists_quiet", lambda r, p: True)
    monkeypatch.setattr(SA, "_list_dir_via_resolver",
                        lambda r, path, pattern="*": list(tc_files))
    monkeypatch.setattr(SA, "_resolve_report_path",
                        lambda r, folder, env, suffix, **kw: f"{folder}/{env}{suffix}")
    monkeypatch.setattr(SA, "_read_via_resolver", lambda r, path: b"<html></html>")
    monkeypatch.setattr(SA, "extract_execution_results_with_actual",
                        lambda data: dict(exec_results))
    # 모듈 캐시 비움 — 테스트 간 격리.
    J._VCAST_CLOUDIUM_PARSE_CACHE.clear()


def test_folder_parse_builds_rows_and_summary(monkeypatch) -> None:
    _patch_folder_parse(monkeypatch, exec_results={
        "SwUFn_0133.001": _FakeRow(True),
        "SwUFn_0133.002": _FakeRow(False),
    })
    out = J._parse_vcast_logs_from_cloudium_folder(
        "U:/x/09.SW 단위 테스트/.../1.APP_UT_report_260604")
    assert out["parsed_from"] == "cloudium_raw_reports"
    assert out["vcast_kind"] == "UT"
    assert out["test_rows_count"] == 2
    assert out["summary"]["passed"] == 1
    assert out["summary"]["failed"] == 1
    # subprogram은 tc_name(SwUFn_0133.001)에서 함수 id(SwUFn_0133) 도출.
    subs = {r["subprogram"] for r in out["test_rows"]}
    assert subs == {"SwUFn_0133"}
    # unit은 env 이름(suffix-strip).
    assert all(r["unit"] == "SwUT_01_Lib_sha256" for r in out["test_rows"])
    # failures 재계산 — FAIL 1건.
    assert len(out["failures"]) == 1
    assert out["failures"][0]["testcase"] == "SwUFn_0133.002"


def test_folder_parse_normalizes_swufn_and_skips_pseudo(monkeypatch) -> None:
    """rank1/3: testcase명에서 SwUFn ID를 정규 추출(UDS func_id와 join), <<...>> 의사
    엔트리는 제외해 summary 과계상 방지."""
    _patch_folder_parse(monkeypatch, exec_results={
        "CTC_SwUFn_0431.001": _FakeRow(True),     # → SwUFn_0431
        "SwIT_SwUFn_0101_01": _FakeRow(True),      # → SwUFn_0101
        "Check_MainApp_Jump.001": _FakeRow(True),  # SwUFn 없음 → 함수명 base 유지
        "<<COMPOUND>>": _FakeRow(False),           # 의사 엔트리 → 제외
    })
    out = J._parse_vcast_logs_from_cloudium_folder("U:/x/단위 테스트/norm_UT")
    subs = {r["subprogram"] for r in out["test_rows"]}
    assert "SwUFn_0431" in subs
    assert "SwUFn_0101" in subs
    assert "Check_MainApp_Jump" in subs
    # <<COMPOUND>>는 제외되어 3건만.
    assert out["test_rows_count"] == 3
    assert all(not r["testcase"].startswith("<<") for r in out["test_rows"])


def test_folder_parse_it_classification(monkeypatch) -> None:
    _patch_folder_parse(monkeypatch, exec_results={"SwIFn_0201.001": _FakeRow(True)})
    out = J._parse_vcast_logs_from_cloudium_folder(
        "U:/x/10.SW 통합 테스트/.../1.APP_IT_Report_260604")
    assert out["vcast_kind"] == "IT"
    assert out["it_reports"] and not out["ut_reports"]
    assert out["test_rows"][0]["source"] == "IT"


class _CS:
    """CoverageStats stub — covered/total만 사용."""
    def __init__(self, covered: int, total: int) -> None:
        self.covered = covered
        self.total = total


class _FC:
    """FunctionCoverage stub — statement/branch/mcdc."""
    def __init__(self, s, b, m) -> None:
        self.statement = _CS(*s)
        self.branch = _CS(*b)
        self.mcdc = _CS(*m)


def test_folder_parse_extracts_coverage(monkeypatch) -> None:
    """env별 AggregateCoverage 리포트에서 구문/분기/MC-DC 커버리지를 추출해 payload.coverage에 담는다."""
    import backend.services.swut_input_adapter as SA
    _patch_folder_parse(monkeypatch, exec_results={"SwUFn_0133.001": _FakeRow(True)})
    # grand_total이 90/100(구문)·40/50(분기)·8/10(MC-DC) 반환하도록 추출기 모킹.
    monkeypatch.setattr(SA, "extract_aggregate_coverage",
                        lambda data, **_kw: ([], _FC((90, 100), (40, 50), (8, 10))))
    out = J._parse_vcast_logs_from_cloudium_folder("U:/x/09.SW 단위 테스트/cov_UT")
    cov = out["coverage"]
    assert cov["statement"] == {"covered": 90, "total": 100, "rate": 0.9}
    assert cov["branch"] == {"covered": 40, "total": 50, "rate": 0.8}
    assert cov["mcdc"] == {"covered": 8, "total": 10, "rate": 0.8}


def test_merge_combines_coverage_overall_and_ut_it() -> None:
    """병합이 전체 coverage + UT/IT 분리 합산을 산출한다."""
    ut = {
        "test_rows": [{"subprogram": "f", "result": "PASS"}], "vcast_kind": "UT",
        "coverage": {"statement": {"covered": 90, "total": 100, "rate": 0.9},
                     "branch": {"covered": 0, "total": 0, "rate": None},
                     "mcdc": {"covered": 0, "total": 0, "rate": None}},
    }
    it = {
        "test_rows": [{"subprogram": "g", "result": "PASS"}], "vcast_kind": "IT",
        "coverage": {"statement": {"covered": 40, "total": 50, "rate": 0.8},
                     "branch": {"covered": 0, "total": 0, "rate": None},
                     "mcdc": {"covered": 0, "total": 0, "rate": None}},
    }
    merged = J._merge_vectorcast_payloads([ut, it])
    assert merged["coverage"]["statement"] == {"covered": 130, "total": 150, "rate": round(130 / 150, 4)}
    assert merged["coverage_ut"]["statement"]["covered"] == 90
    assert merged["coverage_it"]["statement"]["covered"] == 40
    # 데이터 전무한 메트릭은 None rate.
    assert merged["coverage"]["mcdc"]["rate"] is None


def test_merge_no_coverage_yields_none() -> None:
    """coverage 없는 payload만 병합하면 coverage 키가 None(빈 표시 회피)."""
    merged = J._merge_vectorcast_payloads([
        {"test_rows": [{"subprogram": "f", "result": "PASS"}]},
        {"test_rows": [{"subprogram": "g", "result": "FAIL"}]},
    ])
    assert merged["coverage"] is None
    assert merged["coverage_ut"] is None


def test_folder_parse_empty_results_returns_diagnostic(monkeypatch) -> None:
    """결과 0건: silent-drop 방지(P1)로 빈 dict가 아니라 진단 dict를 반환한다
    (test_rows=[], vcast_kind, parse_warnings에 '결과 0건' 경고 표면화)."""
    _patch_folder_parse(monkeypatch, exec_results={})
    out = J._parse_vcast_logs_from_cloudium_folder("U:/x/단위 테스트/empty_UT")
    assert out["test_rows"] == []
    assert out["vcast_kind"] == "UT"
    assert out.get("parse_warnings")  # 0건 경고 누적


def test_folder_parse_uses_cache(monkeypatch) -> None:
    calls = {"n": 0}
    base = dict(exec_results_ref={"SwUFn_0101.001": _FakeRow(True)})

    import backend.services.swut_input_adapter as SA
    _patch_folder_parse(monkeypatch, exec_results=base["exec_results_ref"])

    orig = SA.extract_execution_results_with_actual
    def _counting(data):
        calls["n"] += 1
        return orig(data)
    monkeypatch.setattr(SA, "extract_execution_results_with_actual", _counting)

    path = "U:/x/단위 테스트/cache_UT"
    out1 = J._parse_vcast_logs_from_cloudium_folder(path)
    out2 = J._parse_vcast_logs_from_cloudium_folder(path)
    assert out1["test_rows_count"] == 1 and out2["test_rows_count"] == 1
    # 2차는 캐시 hit — 파서 재호출 없음.
    assert calls["n"] == 1


# ── _docx_tables_text — 손상 docx fallback (document.xml 직접 파싱) ─────
def _docxml_only_zip(doc_xml: str) -> bytes:
    """word/document.xml만 담은 zip — python-docx는 못 열어 fallback 경로를 강제."""
    import io as _io
    import zipfile as _zip
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_FI_DOC_XML = (
    '<?xml version="1.0"?>'
    f'<w:document xmlns:w="{_W}"><w:body>'
    '<w:tbl>'
    '<w:tr><w:tc><w:p><w:r><w:t>[ Function Information ]</w:t></w:r></w:p></w:tc></w:tr>'
    '<w:tr><w:tc><w:p><w:r><w:t>ID</w:t></w:r></w:p></w:tc>'
    '<w:tc><w:p><w:r><w:t>SwUFn_0101</w:t></w:r></w:p></w:tc></w:tr>'
    '<w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>'
    '<w:tc><w:p><w:r><w:t>main</w:t></w:r></w:p></w:tc></w:tr>'
    '<w:tr><w:tc><w:p><w:r><w:t>Req</w:t></w:r></w:p></w:tc>'
    '<w:tc><w:p><w:r><w:t>SwSTR_01</w:t></w:r></w:p></w:tc></w:tr>'
    '</w:tbl></w:body></w:document>'
)


def test_docx_tables_text_fallback_parses_document_xml() -> None:
    """python-docx가 못 여는 손상/불완전 docx도 document.xml 표를 복구한다.

    손상 UDS docx(이미지 CRC 오류)에서 매핑 0건이던 회귀를 가드 — 2-cell 행 구조로
    파싱되는지 + Function Information 표가 인식되는지 확인.
    """
    tables = J._docx_tables_text(_docxml_only_zip(_FI_DOC_XML))
    assert tables is not None and len(tables) == 1
    rows = tables[0]
    assert "Function Information" in rows[0][0]
    # 실제 w:tc만 추출 → 값은 cells[1] (2-cell 행).
    assert ["ID", "SwUFn_0101"] in rows
    assert ["Name", "main"] in rows


def test_docx_tables_text_returns_none_on_garbage() -> None:
    assert J._docx_tables_text(b"this is not a zip / docx at all") is None


# ── 동기/비동기 vectorcast-rag (리팩터 + 잡 전환) ─────────────────────
def test_compute_vectorcast_rag_missing_when_nothing_found(monkeypatch) -> None:
    """빌드 캐시 없음 + 등록 경로 없음 → {ok:false, error:missing, parse_warnings:[]}
    (P1: silent-drop 방지 계약 — 등록 경로가 없으니 사유도 빈 리스트)."""
    monkeypatch.setattr(J, "_resolve_cached_build_root", lambda *a, **k: None)
    req = JenkinsReportRequest(job_url="http://j/job/x", cache_root=".c")
    out = J._compute_vectorcast_rag(req)
    assert out == {"ok": False, "error": "missing", "parse_warnings": []}


def test_compute_vectorcast_rag_surfaces_cloudium_parse_warnings(monkeypatch) -> None:
    """P1: cloudium 폴백이 test_rows를 못 얻어도 실패 사유(parse_warnings)를 missing 응답에
    실어 표면화한다 — 과거엔 bare {ok:False,error:missing}로 사용자에게 사유 없이 열이 비었다.
    worker timeout(PermissionError)/폴더 부재가 가장 흔한 KJPDS02 PV 통증."""
    monkeypatch.setattr(J, "_resolve_cached_build_root", lambda *a, **k: None)
    monkeypatch.setattr(
        J, "_load_vectorcast_rag_from_cloudium_multi",
        lambda paths: {"test_rows": [],
                       "parse_warnings": ["IT: cloudium 접근 실패 PermissionError (worker 미응답/timeout 가능)"]},
    )
    req = JenkinsReportRequest(job_url="http://j/job/x", cache_root=".c", vcast_log_paths=["U:/vc"])
    out = J._compute_vectorcast_rag(req)
    assert out["ok"] is False and out["error"] == "missing"
    assert any("PermissionError" in w for w in out.get("parse_warnings", []))


def test_vectorcast_rag_async_dispatches_job(monkeypatch) -> None:
    """async 엔드포인트는 무거운 파싱을 start_job(trigger_type='vectorcast')으로 던지고 job_id 반환."""
    import workflow.impact_jobs as IJ

    captured = {}

    def _fake_start_job(*, scm_id, trigger_type, runner, metadata=None):
        captured["scm_id"] = scm_id
        captured["trigger_type"] = trigger_type
        captured["runner"] = runner
        captured["metadata"] = metadata
        return {"ok": True, "job_id": "job_test", "status": "queued"}

    monkeypatch.setattr(IJ, "start_job", _fake_start_job)
    # runner가 호출되면 동기 계산을 수행하는지 확인용으로 _compute도 모킹.
    monkeypatch.setattr(J, "_compute_vectorcast_rag", lambda req: {"ok": True, "data": {"test_rows": [1]}})

    req = JenkinsReportRequest(job_url="http://j/job/x", cache_root=".c", vcast_log_paths=["U:/vc"])
    out = J.jenkins_vectorcast_rag_async(req)
    assert out["ok"] is True and out["job_id"] == "job_test"
    assert captured["trigger_type"] == "vectorcast"
    # 내부 경로는 메타에 싣지 않고 개수만(W3).
    assert captured["metadata"]["vcast_path_count"] == 1
    assert "vcast_paths" not in captured["metadata"]
    # runner는 _compute_vectorcast_rag를 호출(잡 스레드에서 실행될 본체).
    assert captured["runner"]("job_test")["ok"] is True


# ── ScmLinkedDocs.vectorcast schema ───────────────────────────────────
def test_linked_docs_vectorcast_defaults_empty_list() -> None:
    ld = ScmLinkedDocs()
    assert ld.vectorcast == []


def test_linked_docs_vectorcast_accepts_list() -> None:
    ld = ScmLinkedDocs(vectorcast=["U:/a", "U:/b"])
    assert ld.vectorcast == ["U:/a", "U:/b"]
    # round-trip through model_dump (registry 저장 경로).
    assert ld.model_dump()["vectorcast"] == ["U:/a", "U:/b"]


# ── per-function vcast_summary + complexity_rows (audit D2/D3 fix) ─────
class _FCFull:
    """FunctionCoverage stub — per-function entries/complexity 검증용 (name/unit_id/component_name/complexity 포함)."""
    def __init__(self, name, s, b, m, complexity=0, component="") -> None:
        self.name = name
        self.unit_id = name
        self.component_name = component
        self.statement = _CS(*s)
        self.branch = _CS(*b)
        self.mcdc = _CS(*m)
        self.complexity = complexity


def test_folder_parse_emits_vcast_summary_and_complexity(monkeypatch) -> None:
    """폴더 파서가 함수별 vcast_summary.{ut}_metrics.entries + complexity_rows를 산출(집계 폐기 방지).
    MC/DC total=0이면 pairs.rate=None(0% 위장 금지)."""
    import backend.services.swut_input_adapter as SA
    _patch_folder_parse(monkeypatch, exec_results={"SwUFn_0133.001": _FakeRow(True)})
    funcs = [
        _FCFull("Ap_Door_Run", (10, 10), (8, 10), (17, 20), complexity=9, component="DoorU"),
        _FCFull("Ap_NoMcdc", (5, 5), (0, 0), (0, 0), complexity=3, component="DoorU"),
    ]
    # grand 존재(집계는 grand 사용)해도 per-function은 항상 funcs에서 모음을 검증.
    monkeypatch.setattr(SA, "extract_aggregate_coverage",
                        lambda data, **_kw: (funcs, _FC((15, 15), (8, 10), (17, 20))))
    out = J._parse_vcast_logs_from_cloudium_folder("U:/x/09.SW 단위 테스트/vs_UT")
    entries = out["vcast_summary"]["ut_metrics"]["entries"]
    by = {e["subprogram"]: e for e in entries}
    assert by["Ap_Door_Run"]["pairs"] == {"covered": 17, "total": 20, "rate": 0.85}
    assert by["Ap_Door_Run"]["statements"] == {"covered": 10, "total": 10, "rate": 1.0}
    assert by["Ap_Door_Run"]["ccn"] == 9
    # MC/DC total=0 → rate None (증거 부재 ≠ 0% 미커버)
    assert by["Ap_NoMcdc"]["pairs"]["rate"] is None
    assert by["Ap_NoMcdc"]["pairs"]["total"] == 0
    # complexity_rows — complexity>0 함수만, file/unit=component.
    comp = {c["function"]: c for c in out["complexity_rows"]}
    assert comp["Ap_Door_Run"]["complexity"] == 9
    assert comp["Ap_Door_Run"]["file"] == "DoorU"
    assert comp["Ap_NoMcdc"]["complexity"] == 3


def test_folder_parse_neutralizes_degenerate_mcdc(monkeypatch) -> None:
    """deep-review C1 — mcdc(pairs) 컬럼이 함수-진입 위장(전 함수 pairs.total=1·분기 변동)이면
    coverage.mcdc·entries[].pairs 를 중화(라벨 무관 데이터 가드). 헤더가 'MC/DC'여도 거짓 지표 차단."""
    import backend.services.swut_input_adapter as SA
    _patch_folder_parse(monkeypatch, exec_results={"SwIFn_0201.001": _FakeRow(True)})
    # 12함수 전부 mcdc.total=1(covered 1/0), 분기 total 변동(3·9, max>2) = 퇴화 지문
    funcs = [
        _FCFull(f"fn{i}", (5, 5), (1, 9 if i % 2 else 3), (1 if i < 6 else 0, 1),
                complexity=2, component="C")
        for i in range(12)
    ]
    monkeypatch.setattr(SA, "extract_aggregate_coverage",
                        lambda data, **_kw: (funcs, _FC((60, 60), (30, 40), (6, 12))))
    out = J._parse_vcast_logs_from_cloudium_folder("U:/x/10.SW 통합 테스트/vs_IT")
    # 퇴화 → coverage.mcdc 중화(grand 6/12 아님)
    assert out["coverage"]["mcdc"] == {"covered": 0, "total": 0, "rate": None}
    # entries pairs 도 전부 중화
    vs = out["vcast_summary"]
    entries = (vs.get("it_metrics") or vs.get("ut_metrics") or {}).get("entries", [])
    assert entries and all((e.get("pairs") or {}).get("total") == 0 for e in entries)
    # statement/branch 는 무영향(중화 대상 아님)
    assert out["coverage"]["statement"]["total"] > 0
    assert out["coverage"]["branch"]["total"] > 0
    assert any("mcdc-guard" in w for w in out.get("parse_warnings", []))


def test_folder_payload_feeds_coverage_gap(monkeypatch, tmp_path) -> None:
    """P0 end-to-end: 폴더 파서 payload가 coverage_gap을 먹여 ASIL 차등 MC/DC 평가가 동작(available=True)."""
    import backend.services.swut_input_adapter as SA
    from workflow import coverage_gap
    _patch_folder_parse(monkeypatch, exec_results={"SwUFn_0133.001": _FakeRow(True)})
    funcs = [
        _FCFull("Ap_Door_Run", (10, 10), (8, 10), (17, 20), complexity=9),  # MC/DC 0.85
        _FCFull("Ap_Helper", (5, 5), (5, 5), (5, 5), complexity=2),         # 전부 100%
    ]
    monkeypatch.setattr(SA, "extract_aggregate_coverage",
                        lambda data, **_kw: (funcs, _FC((0, 0), (0, 0), (0, 0))))
    payload = J._parse_vcast_logs_from_cloudium_folder("U:/x/09.SW 단위 테스트/e2e_UT")
    # coverage_gap이 폴더 payload를 그대로 읽도록(로더 모킹).
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium", lambda p: payload)
    res = coverage_gap.compute_coverage_gap(
        ["Ap_Door_Run", "Ap_Helper"],
        {"Ap_Door_Run": "D", "Ap_Helper": "QM"},
        ["U:/x/09.SW 단위 테스트/e2e_UT"],
        cache_root=str(tmp_path), scm_id="e2e", update_baseline=False,
    )
    assert res["available"] is True   # 회귀 핵심: 폴더 경로로 더 이상 available=False 아님
    byfn = {r["function"]: r for r in res["functions"]}
    assert byfn["Ap_Door_Run"]["target_metric"] == "mcdc"
    assert byfn["Ap_Door_Run"]["meets_target"] is False    # 0.85 < 1.0
    assert byfn["Ap_Helper"]["target_metric"] == "statement"
    assert byfn["Ap_Helper"]["meets_target"] is True
    assert res["summary"]["below_target"] == 1


def test_merge_combines_vcast_summary_and_complexity() -> None:
    """병합이 ut/it metrics entries와 complexity_rows를 보존·결합한다."""
    ut = {
        "test_rows": [{"subprogram": "f", "result": "PASS"}], "vcast_kind": "UT",
        "vcast_summary": {"ut_metrics": {"entries": [
            {"subprogram": "f", "ccn": 5,
             "statements": {"covered": 10, "total": 10, "rate": 1.0},
             "branches": {"covered": 0, "total": 0, "rate": None},
             "pairs": {"covered": 0, "total": 0, "rate": None}},
        ]}},
        "complexity_rows": [{"function": "f", "file": "U1", "unit": "U1", "complexity": 5}],
    }
    it = {
        "test_rows": [{"subprogram": "g", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {"entries": [
            {"subprogram": "g", "ccn": 3,
             "statements": {"covered": 0, "total": 0, "rate": None},
             "branches": {"covered": 0, "total": 0, "rate": None},
             "pairs": {"covered": 4, "total": 4, "rate": 1.0}},
        ]}},
        "complexity_rows": [{"function": "g", "file": "U2", "unit": "U2", "complexity": 3}],
    }
    merged = J._merge_vectorcast_payloads([ut, it])
    assert merged["vcast_summary"]["ut_metrics"]["entries"][0]["subprogram"] == "f"
    assert merged["vcast_summary"]["it_metrics"]["entries"][0]["subprogram"] == "g"
    assert len(merged["complexity_rows"]) == 2


def test_merge_preserves_and_sums_grand_totals() -> None:
    """버그2 회귀: 다중 IT 폴더(APP+BOOT) 병합 시 it_metrics.grand_totals(함수콜/함수진입)를
    드롭하지 않고 covered/total 합산·rate 재계산해 보존한다. 드롭하면 2폴더+ 로드 시 카드가
    조용히 사라졌다."""
    app = {
        "test_rows": [{"subprogram": "a", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {
            "entries": [{"subprogram": "a"}],
            "grand_totals": {
                "function_calls": {"covered": 855, "total": 2989, "rate": round(855 / 2989, 4)},
                "functions": {"covered": 504, "total": 1638, "rate": round(504 / 1638, 4)},
            },
        }},
    }
    boot = {
        "test_rows": [{"subprogram": "b", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {
            "entries": [{"subprogram": "b"}],
            "grand_totals": {
                "function_calls": {"covered": 45, "total": 111, "rate": round(45 / 111, 4)},
                "functions": {"covered": 20, "total": 62, "rate": round(20 / 62, 4)},
            },
        }},
    }
    merged = J._merge_vectorcast_payloads([app, boot])
    gt = merged["vcast_summary"]["it_metrics"]["grand_totals"]
    # 함수콜: (855+45)/(2989+111) = 900/3100
    assert gt["function_calls"] == {"covered": 900, "total": 3100, "rate": round(900 / 3100, 4)}
    # 함수 진입: (504+20)/(1638+62) = 524/1700
    assert gt["functions"] == {"covered": 524, "total": 1700, "rate": round(524 / 1700, 4)}
    # entries도 보존.
    assert len(merged["vcast_summary"]["it_metrics"]["entries"]) == 2


def test_merge_grand_totals_partial_and_zero_omitted() -> None:
    """한 폴더에만 grand_totals가 있거나 total=0이면: 있는 것만 합산, total=0 메트릭은 키 생략."""
    with_gt = {
        "test_rows": [{"subprogram": "a", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {"grand_totals": {
            "function_calls": {"covered": 10, "total": 20, "rate": 0.5},
            "functions": {"covered": 0, "total": 0, "rate": None},  # total=0 → 생략
        }}},
    }
    no_gt = {
        "test_rows": [{"subprogram": "b", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {"entries": [{"subprogram": "b"}]}},
    }
    merged = J._merge_vectorcast_payloads([with_gt, no_gt])
    gt = merged["vcast_summary"]["it_metrics"]["grand_totals"]
    assert gt["function_calls"] == {"covered": 10, "total": 20, "rate": 0.5}
    assert "functions" not in gt  # total=0이라 위장 카드 방지


def test_merge_grand_totals_overlap_double_counts_documented() -> None:
    """W1 동작 문서화: merge 레벨에는 cross-folder 함수 dedup이 없어, 공유 함수가 두 폴더
    grand_totals에 모두 있으면 covered/total이 이중 계상된다. 이는 기존 coverage(구문/분기/
    MCDC) 병합과 동일 정책이며, UI 주석 + _collect_vcast_paths 경로 dedup으로 완화한다.
    정책을 나중에 함수별 dedup으로 바꾸면 이 테스트가 먼저 깨져 의도 변경을 드러낸다."""
    shared = {
        "test_rows": [{"subprogram": "sha_init", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {"grand_totals": {
            "function_calls": {"covered": 3, "total": 5, "rate": 0.6},
        }}},
    }
    merged = J._merge_vectorcast_payloads([dict(shared), dict(shared)])
    gt = merged["vcast_summary"]["it_metrics"]["grand_totals"]
    # 동일 payload 2개 → 합산이 2배(6/10) — 현 정책상 예상 동작(과대 계상 가능성 명시).
    assert gt["function_calls"] == {"covered": 6, "total": 10, "rate": 0.6}


def test_merge_grand_totals_only_no_entries() -> None:
    """엣지: grand_totals만 있고 entries 없는 payload → 출력 blk에 grand_totals만(entries 키 없음)."""
    only_gt = {
        "test_rows": [{"subprogram": "a", "result": "PASS"}], "vcast_kind": "IT",
        "vcast_summary": {"it_metrics": {"grand_totals": {
            "function_calls": {"covered": 7, "total": 14, "rate": 0.5},
        }}},
    }
    merged = J._merge_vectorcast_payloads([only_gt, only_gt])
    blk = merged["vcast_summary"]["it_metrics"]
    assert blk["grand_totals"]["function_calls"] == {"covered": 14, "total": 28, "rate": 0.5}
    assert "entries" not in blk  # entries 없는 입력은 entries 키를 만들지 않음


def test_merge_dedups_complexity_rows() -> None:
    """같은 (function,unit) complexity는 중복 등록돼도 1건."""
    p1 = {"test_rows": [{"subprogram": "f", "result": "PASS"}],
          "complexity_rows": [{"function": "f", "unit": "U", "complexity": 5}]}
    p2 = {"test_rows": [{"subprogram": "f", "result": "PASS"}],
          "complexity_rows": [{"function": "f", "unit": "U", "complexity": 5}]}
    merged = J._merge_vectorcast_payloads([p1, p2])
    assert len(merged["complexity_rows"]) == 1


def test_complexity_endpoint_cloudium_fallback(monkeypatch) -> None:
    """빌드 complexity.csv 없으면 SCM cloudium 폴더의 함수별 복잡도로 폴백(source=cloudium)."""
    monkeypatch.setattr(J, "_resolve_cached_build_root", lambda *a, **k: None)
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium_multi",
                        lambda paths: {"complexity_rows": [{"function": "f", "file": "U", "complexity": 12}]})
    req = JenkinsReportRequest(job_url="http://j/job/x", cache_root=".c", vcast_log_paths=["U:/vc"])
    out = J.jenkins_complexity(req)
    assert out["source"] == "cloudium"
    assert out["rows"][0]["complexity"] == 12


def test_complexity_endpoint_404_when_no_build_no_scm(monkeypatch) -> None:
    """빌드 없음 + SCM 경로 없음 → 기존처럼 404."""
    monkeypatch.setattr(J, "_resolve_cached_build_root", lambda *a, **k: None)
    req = JenkinsReportRequest(job_url="http://j/job/x", cache_root=".c")
    with pytest.raises(HTTPException) as ei:
        J.jenkins_complexity(req)
    assert ei.value.status_code == 404
