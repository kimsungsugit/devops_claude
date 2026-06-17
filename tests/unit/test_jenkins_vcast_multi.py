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
    """단일 경로면 원본 payload 그대로 (모든 필드 보존, 병합 미적용)."""
    raw = {"test_rows": [{"subprogram": "f"}], "build_root": "U:/x", "scanned_at": "t"}
    monkeypatch.setattr(J, "_load_vectorcast_rag_from_cloudium", lambda _p: dict(raw))
    out = J._load_vectorcast_rag_from_cloudium_multi(["U:/x"])
    assert out == raw  # build_root/scanned_at 보존


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


def test_folder_parse_empty_results_returns_empty(monkeypatch) -> None:
    _patch_folder_parse(monkeypatch, exec_results={})
    out = J._parse_vcast_logs_from_cloudium_folder("U:/x/단위 테스트/empty_UT")
    assert out == {}


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


# ── ScmLinkedDocs.vectorcast schema ───────────────────────────────────
def test_linked_docs_vectorcast_defaults_empty_list() -> None:
    ld = ScmLinkedDocs()
    assert ld.vectorcast == []


def test_linked_docs_vectorcast_accepts_list() -> None:
    ld = ScmLinkedDocs(vectorcast=["U:/a", "U:/b"])
    assert ld.vectorcast == ["U:/a", "U:/b"]
    # round-trip through model_dump (registry 저장 경로).
    assert ld.model_dump()["vectorcast"] == ["U:/a", "U:/b"]
