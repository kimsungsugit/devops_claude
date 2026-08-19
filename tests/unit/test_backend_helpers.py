"""Unit tests for backend/helpers/common.py pure utility functions."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.helpers.common import (
    _build_excel_artifact_summary,
    _compact_symbol_simple,
    _extract_param_name_simple,
    _has_meaningful_value,
    _has_trace_token,
    _infer_related_id_simple,
    _is_allowed_req_doc,
    _is_relative_to,
    _json_safe,
    _normalize_asil_simple,
    _normalize_field_source,
    _normalize_symbol_simple,
    _parse_path_list,
    _parse_signature_outputs_simple,
    _parse_signature_params_simple,
    _read_json,
    _safe_extract_zip,
    _safe_int,
    _split_csv,
    _split_signature_params,
    _write_json,
)


class TestSplitSignatureParams:
    def test_simple_params(self):
        assert _split_signature_params("int a, float b") == ["int a", "float b"]

    def test_nested_parens(self):
        result = _split_signature_params("void (*cb)(int), int x")
        assert len(result) == 2
        assert "(*cb)(int)" in result[0]

    def test_empty(self):
        assert _split_signature_params("") == []
        assert _split_signature_params(None) == []

    def test_single_param(self):
        assert _split_signature_params("int x") == ["int x"]


class TestExtractParamName:
    def test_simple(self):
        assert _extract_param_name_simple("int count") == "count"

    def test_pointer(self):
        assert _extract_param_name_simple("int *ptr") == "ptr"

    def test_function_pointer(self):
        assert _extract_param_name_simple("void (*callback)(int)") == "callback"

    def test_array(self):
        assert _extract_param_name_simple("int buf[10]") == "buf"

    def test_empty(self):
        assert _extract_param_name_simple("") == ""
        assert _extract_param_name_simple(None) == ""


class TestHasMeaningfulValue:
    def test_empty_string(self):
        assert _has_meaningful_value("") is False

    def test_na_values(self):
        assert _has_meaningful_value("N/A") is False
        assert _has_meaningful_value("TBD") is False
        assert _has_meaningful_value("-") is False

    def test_valid_string(self):
        assert _has_meaningful_value("some description") is True

    def test_list_with_items(self):
        assert _has_meaningful_value(["a", "b"]) is True

    def test_empty_list(self):
        assert _has_meaningful_value([]) is False

    def test_list_with_blanks(self):
        assert _has_meaningful_value(["", "  "]) is False


class TestNormalizeAsilSimple:
    def test_valid_levels(self):
        assert _normalize_asil_simple("ASIL-D") == "D"
        assert _normalize_asil_simple("A") == "A"
        assert _normalize_asil_simple("QM") == "QM"

    def test_invalid(self):
        assert _normalize_asil_simple("N/A") == ""
        assert _normalize_asil_simple("") == ""
        assert _normalize_asil_simple("X") == ""


class TestNormalizeFieldSource:
    def test_known(self):
        assert _normalize_field_source("comment") == "comment"
        assert _normalize_field_source("sds") == "sds"
        assert _normalize_field_source("rule") == "rule"

    def test_unknown(self):
        assert _normalize_field_source("unknown") == "inference"
        assert _normalize_field_source("") == "inference"


class TestHasTraceToken:
    def test_with_token(self):
        assert _has_trace_token("SwCom_001") is True
        assert _has_trace_token("related to SwFn_42") is True

    def test_without_token(self):
        assert _has_trace_token("no trace here") is False
        assert _has_trace_token("") is False


class TestNormalizeSymbol:
    def test_basic(self):
        assert _normalize_symbol_simple("Foo_Bar") == "foo_bar"

    def test_compact(self):
        assert _compact_symbol_simple("Foo_Bar") == "foobar"


class TestParsePathList:
    def test_json_array(self):
        assert _parse_path_list('["a.c", "b.c"]') == ["a.c", "b.c"]

    def test_csv(self):
        assert _parse_path_list("a.c, b.c") == ["a.c", "b.c"]

    def test_empty(self):
        assert _parse_path_list("") == []

    def test_semicolon(self):
        assert _parse_path_list("a.c;b.c") == ["a.c", "b.c"]


class TestParseSignatureParams:
    def test_void_params(self):
        result = _parse_signature_params_simple("void foo(void)")
        assert result == ["[IN] (none)"]

    def test_with_params(self):
        result = _parse_signature_params_simple("int add(int a, int b)")
        assert len(result) == 2
        assert all(r.startswith("[IN]") for r in result)

    def test_no_parens(self):
        assert _parse_signature_params_simple("int x") == []


class TestParseSignatureOutputs:
    def test_return_type(self):
        result = _parse_signature_outputs_simple("int foo(void)")
        assert any("[OUT] return int" in r for r in result)

    def test_void_return(self):
        result = _parse_signature_outputs_simple("void foo(int *buf)")
        assert any("buf" in r for r in result)

    def test_no_output(self):
        result = _parse_signature_outputs_simple("void foo(const int *buf)")
        # const pointer -> not output; void return -> "[OUT] (none)"
        assert result == ["[OUT] (none)"]


class TestJsonSafe:
    def test_path(self):
        assert isinstance(_json_safe(Path("/tmp")), str)

    def test_set(self):
        result = _json_safe({1, 2})
        assert isinstance(result, list)

    def test_nested_dict(self):
        result = _json_safe({"a": Path("/x")})
        assert result == {"a": "/x"} or result == {"a": "\\x"}


class TestSafeInt:
    def test_valid(self):
        assert _safe_int("5", 0) == 5

    def test_default(self):
        assert _safe_int(None, 10) == 10
        assert _safe_int("abc", 10) == 10

    def test_clamp(self):
        assert _safe_int("1", 5, low=3) == 3
        assert _safe_int("100", 5, high=50) == 50


class TestSplitCsv:
    def test_string(self):
        assert _split_csv("a, b, c") == ["a", "b", "c"]

    def test_list_passthrough(self):
        assert _split_csv(["x"]) == ["x"]

    def test_none(self):
        assert _split_csv(None) == []


class TestIsRelativeTo:
    def test_true(self):
        assert _is_relative_to(Path("/a/b/c"), Path("/a/b")) is True

    def test_false(self):
        assert _is_relative_to(Path("/x/y"), Path("/a/b")) is False


class TestReadWriteJson:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "test.json"
        _write_json(p, {"key": "value"})
        assert _read_json(p, {}) == {"key": "value"}

    def test_read_missing(self, tmp_path):
        assert _read_json(tmp_path / "nope.json", {"default": True}) == {"default": True}


class TestIsAllowedReqDoc:
    def test_allowed(self):
        assert _is_allowed_req_doc(Path("spec.txt")) is True
        assert _is_allowed_req_doc(Path("doc.pdf")) is True

    def test_disallowed(self):
        assert _is_allowed_req_doc(Path("image.png")) is False


class TestInferRelatedIdSimple:
    def test_with_swcom(self):
        assert _infer_related_id_simple({"related": "SwCom_123"}) == "SwCom_123"

    def test_swufn_is_not_renamed_into_a_requirement_id(self):
        """⚠ 2026-08-03 로 **단언이 뒤집혔다**.

        예전엔 `SwUFn_42` → `SwFn_42` 개명을 기대했다. 그 개명이 곧 지어내기였다:
        `SwUFn_NN` 은 이 함수 **자신의** 단위설계 ID 이고 `SwFn_NN` 은 SwDS 의
        **설계요소** ID 다. 번호가 같다는 근거는 어디에도 없는데, 실재하는
        네임스페이스 안에 그럴듯한 ID 를 만들어 넣어 리뷰어가 문서 유래와
        구분할 수 없게 만들었다.

        실측(payload 86개): 빈 `related` **5,780건 전부**가 이 경로로 값을 받았고
        전부 함수 자신의 `id` 에서 왔다. 상세는
        `tests/unit/test_related_id_no_fabrication.py`.
        """
        assert _infer_related_id_simple({"related": "SwUFn_42"}) == ""

    def test_empty(self):
        assert _infer_related_id_simple({}) == ""
        assert _infer_related_id_simple({"related": "N/A"}) == ""


class TestBuildExcelArtifactSummary:
    def test_sts_type(self):
        result = _build_excel_artifact_summary("sts", {"test_case_count": 10})
        assert result["artifact_type"] == "sts"
        assert len(result["primary"]) > 0

    def test_suts_type(self):
        result = _build_excel_artifact_summary("suts", {"test_case_count": 5})
        assert result["artifact_type"] == "suts"

    def test_unknown_type(self):
        result = _build_excel_artifact_summary("unknown", {})
        assert result["primary"] == []

    @staticmethod
    def _covered_reqs(summary):
        return next(x["value"] for x in summary["secondary"] if x["key"] == "covered_reqs")

    def test_sits_covered_reqs_ignores_synthetic_related_count(self):
        """'Covered Reqs'가 합성 SwCom 보유 수를 폴백으로 쓰면 항상 만점처럼 보인다.

        회귀 대상: with_related_count(=Related ID 필드 보유 TC 수) 폴백. SITS는 모든 flow에
        순번 기반 SwCom_XX를 삽입하므로 그 값은 사실상 TC 총수와 같다.
        """
        summary = _build_excel_artifact_summary("sits", {
            "test_case_count": 10,
            "quality_report": {
                "with_related_count": 10,            # 합성 포함 — 신뢰 불가
                "with_requirement_trace_count": 3,   # 실제 요구 ID 기준
            },
        })
        assert self._covered_reqs(summary) == 3

    def test_sits_covered_reqs_prefers_trace_coverage(self):
        summary = _build_excel_artifact_summary("sits", {
            "test_case_count": 10,
            "trace_coverage": {"covered_reqs": 7},
            "quality_report": {"with_related_count": 10, "with_requirement_trace_count": 3},
        })
        assert self._covered_reqs(summary) == 7

    def test_sits_covered_reqs_zero_when_unmeasured(self):
        """구 산출물(새 키 없음)은 0 — 미측정을 만점으로 보이게 하지 않는다."""
        summary = _build_excel_artifact_summary("sits", {
            "test_case_count": 10,
            "quality_report": {"with_related_count": 10},
        })
        assert self._covered_reqs(summary) == 0


class TestSafeExtractZip:
    def test_extract(self, tmp_path):
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.txt", "hello")
            zf.writestr("sub/b.txt", "world")
        dest = tmp_path / "out"
        dest.mkdir()
        count = _safe_extract_zip(zip_path, dest)
        assert count == 2
        assert (dest / "a.txt").read_text() == "hello"
