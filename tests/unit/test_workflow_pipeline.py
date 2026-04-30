# tests/unit/test_workflow_pipeline.py
# -*- coding: utf-8 -*-
"""
workflow/pipeline.py 단위 테스트
- 순수 유틸 함수 (_cmake_quote, _normalize_define, _normalize_include_dir,
  _is_simple_signature, _csv_list, _pick_best_rag_solution)
- 파일 I/O 헬퍼 (_write_text, _write_json, _has_test_main_file)
- _extract_stub_functions 기본 동작

ISO 26262 / ASIL 고려사항:
- _is_simple_signature 는 ASIL 함수 타입 검증에 사용될 수 있으므로
  BVA(경계값 분석)와 EP(동치 분할)를 적용한다.

요구사항 추적: SRS-PIPE-001 (파이프라인 유틸 안정성)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import types  # noqa: E402

import pytest

# ---------------------------------------------------------------------------
# 무거운 외부 의존성 stub 처리
# ---------------------------------------------------------------------------


def _ensure_stubs() -> None:
    """workflow.__init__ 실행을 방지하고 외부 의존성을 stub 처리한다."""
    sys.modules.setdefault("analysis_tools", MagicMock())
    sys.modules.setdefault("utils", MagicMock())
    sys.modules.setdefault(
        "utils.log",
        MagicMock(get_logger=MagicMock(return_value=MagicMock())),
    )

    _config = sys.modules.get("config") or MagicMock()
    _config.DEFAULT_OAI_CONFIG_PATH = None  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_MODEL = "gpt-4.1-mini"  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_NUM_PREDICT = 8192  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_TEMPERATURE = 0.3  # type: ignore[attr-defined]
    sys.modules["config"] = _config

    # workflow 패키지: 빈 ModuleType으로 등록하여 __init__ 실행 방지
    if not isinstance(sys.modules.get("workflow"), types.ModuleType) or \
            getattr(sys.modules.get("workflow"), "__path__", None) is None:
        _wf = types.ModuleType("workflow")
        _wf.__path__ = [str(Path(__file__).resolve().parents[2] / "workflow")]  # type: ignore[assignment]
        _wf.__package__ = "workflow"
        sys.modules["workflow"] = _wf

    # workflow 하위 모듈 stub
    _th = MagicMock()
    _th.strip_c_comments = MagicMock(side_effect=lambda t: t)
    _th.param_placeholder = MagicMock(return_value=(None, None))
    _th.parse_param_name = MagicMock(return_value="")
    _th.alt_buffer = MagicMock(return_value="")
    _th.build_call_variants = MagicMock(return_value=[])
    _th.is_simple_signature = MagicMock(return_value=False)
    sys.modules["workflow.test_helpers"] = _th  # type: ignore[assignment]


_ensure_stubs()

import workflow.pipeline as pipeline_mod  # noqa: E402


# ---------------------------------------------------------------------------
# _cmake_quote
# ---------------------------------------------------------------------------

class TestCmakeQuote:
    """SRS-PIPE-010: CMake 경로 인용 처리."""

    def test_백슬래시가_포워드슬래시로_변환된다(self):
        # Arrange & Act
        result = pipeline_mod._cmake_quote("D:\\Project\\src")

        # Assert
        assert "D/Project/src" in result or "D:/Project/src" in result

    def test_결과에_쌍따옴표가_포함된다(self):
        # Arrange & Act
        result = pipeline_mod._cmake_quote("path/to/file")

        # Assert
        assert result.startswith('"') and result.endswith('"')

    def test_빈_문자열_입력시_빈_따옴표를_반환한다(self):
        """경계값: 빈 문자열"""
        # Arrange & Act
        result = pipeline_mod._cmake_quote("")

        # Assert
        assert result == '""'

    def test_None_입력시_빈_따옴표를_반환한다(self):
        """경계값: None 입력"""
        # Arrange & Act
        result = pipeline_mod._cmake_quote(None)

        # Assert
        assert result == '""'


# ---------------------------------------------------------------------------
# _normalize_define
# ---------------------------------------------------------------------------

class TestNormalizeDefine:
    """SRS-PIPE-011: CMake define 정규화 — BVA/EP."""

    def test_일반_define_이름이_그대로_반환된다(self):
        # Arrange & Act
        result = pipeline_mod._normalize_define("MY_DEFINE")

        # Assert
        assert result == "MY_DEFINE"

    def test_마이너스D_접두사가_제거된다(self):
        # Arrange & Act
        result = pipeline_mod._normalize_define("-DMY_DEFINE")

        # Assert
        assert result == "MY_DEFINE"

    def test_공백이_있는_define은_None을_반환한다(self):
        """무효 입력: 공백 포함"""
        # Arrange & Act
        result = pipeline_mod._normalize_define("MY DEFINE")

        # Assert
        assert result is None

    def test_큰따옴표가_있는_define은_None을_반환한다(self):
        """무효 입력: 따옴표 포함"""
        # Arrange & Act
        result = pipeline_mod._normalize_define('MY_DEF="value"')

        # Assert
        assert result is None

    def test_빈_문자열은_None을_반환한다(self):
        """경계값: 빈 입력"""
        # Arrange & Act
        result = pipeline_mod._normalize_define("")

        # Assert
        assert result is None

    def test_None_입력은_None을_반환한다(self):
        """경계값: None 입력"""
        # Arrange & Act
        result = pipeline_mod._normalize_define(None)

        # Assert
        assert result is None


# ---------------------------------------------------------------------------
# _is_simple_signature (ASIL 관련 함수 타입 검증)
# ---------------------------------------------------------------------------

class TestIsSimpleSignature:
    """SRS-PIPE-012: C 함수 시그니처 단순성 판별 — ASIL BVA.

    MC/DC 조건 조합:
    | ret 비어있음 | typedef/struct/enum 포함 | 허용 토큰만 포함 | 결과 |
    |------------|-------------------------|-----------------|------|
    | True        | -                       | -               | False|
    | False       | True                    | -               | False|
    | False       | False                   | True            | True |
    | False       | False                   | False           | False|
    """

    def test_빈_반환타입은_False를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("", "void", header_found=False)

        # Assert
        assert result is False

    def test_typedef_포함_반환타입은_False를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("typedef void", "void", header_found=False)

        # Assert
        assert result is False

    def test_struct_포함_반환타입은_False를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("struct MyType", "void", header_found=False)

        # Assert
        assert result is False

    def test_uint8_t_반환타입은_True를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("uint8_t", "void", header_found=False)

        # Assert
        assert result is True

    def test_void_반환에_int_파라미터는_True를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("void", "int count", header_found=False)

        # Assert
        assert result is True

    def test_커스텀_타입_파라미터는_header_found_없으면_False를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("void", "MyCustomType x", header_found=False)

        # Assert
        assert result is False

    def test_커스텀_t_타입은_header_found_True면_허용된다(self):
        """_t 접미사 타입은 header_found=True 시 허용."""
        # Arrange & Act
        result = pipeline_mod._is_simple_signature("void", "custom_result_t x", header_found=True)

        # Assert
        assert result is True


# ---------------------------------------------------------------------------
# _csv_list
# ---------------------------------------------------------------------------

class TestCsvList:
    """SRS-PIPE-013: CSV/줄바꿈 구분 리스트 파싱 — BVA."""

    def test_None_입력은_빈_리스트를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._csv_list(None)

        # Assert
        assert result == []

    def test_빈_문자열은_빈_리스트를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._csv_list("")

        # Assert
        assert result == []

    def test_콤마_구분_문자열이_파싱된다(self):
        # Arrange & Act
        result = pipeline_mod._csv_list("a, b, c")

        # Assert
        assert result == ["a", "b", "c"]

    def test_줄바꿈_구분_문자열이_파싱된다(self):
        # Arrange & Act
        result = pipeline_mod._csv_list("alpha\nbeta\ngamma")

        # Assert
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result

    def test_리스트_입력은_그대로_반환된다(self):
        # Arrange & Act
        result = pipeline_mod._csv_list(["x", "y", "z"])

        # Assert
        assert result == ["x", "y", "z"]

    def test_공백_항목은_제거된다(self):
        # Arrange & Act
        result = pipeline_mod._csv_list("a,,b, ,c")

        # Assert
        assert "" not in result
        assert " " not in result
        assert "a" in result and "b" in result and "c" in result

    def test_단일_항목_문자열은_원소_1개_리스트를_반환한다(self):
        """경계값: 원소 1개"""
        # Arrange & Act
        result = pipeline_mod._csv_list("only_one")

        # Assert
        assert result == ["only_one"]


# ---------------------------------------------------------------------------
# _pick_best_rag_solution
# ---------------------------------------------------------------------------

class TestPickBestRagSolution:
    """SRS-PIPE-014: RAG 솔루션 선택 — score 기반."""

    def test_빈_리스트는_None을_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._pick_best_rag_solution([])

        # Assert
        assert result is None

    def test_단일_항목은_그대로_반환된다(self):
        # Arrange
        solutions = [{"score": 0.9, "text": "solution A"}]

        # Act
        result = pipeline_mod._pick_best_rag_solution(solutions)

        # Assert
        assert result == solutions[0]

    def test_가장_높은_score_항목이_반환된다(self):
        # Arrange
        solutions = [
            {"score": 0.5, "text": "C"},
            {"score": 0.9, "text": "A"},
            {"score": 0.7, "text": "B"},
        ]

        # Act
        result = pipeline_mod._pick_best_rag_solution(solutions)

        # Assert
        assert result["text"] == "A"
        assert result["score"] == 0.9

    def test_score_없는_항목은_0점으로_처리된다(self):
        # Arrange
        solutions = [
            {"text": "no score"},
            {"score": 0.3, "text": "has score"},
        ]

        # Act
        result = pipeline_mod._pick_best_rag_solution(solutions)

        # Assert
        assert result["text"] == "has score"


# ---------------------------------------------------------------------------
# _write_text / _write_json (파일 I/O 헬퍼)
# ---------------------------------------------------------------------------

class TestWriteHelpers:
    """SRS-PIPE-015: 파일 쓰기 헬퍼 — 디렉토리 자동 생성."""

    def test_write_text가_파일을_생성한다(self, tmp_path: Path):
        # Arrange
        target = tmp_path / "sub" / "test.txt"

        # Act
        pipeline_mod._write_text(target, "hello pipeline")

        # Assert
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "hello pipeline"

    def test_write_text_None_내용은_빈_파일을_생성한다(self, tmp_path: Path):
        """경계값: None 내용"""
        # Arrange
        target = tmp_path / "empty.txt"

        # Act
        pipeline_mod._write_text(target, None)

        # Assert
        assert target.exists()
        assert target.read_text(encoding="utf-8") == ""

    def test_write_json이_JSON_파일을_생성한다(self, tmp_path: Path):
        # Arrange
        target = tmp_path / "result.json"
        data = {"ok": True, "count": 42}

        # Act
        pipeline_mod._write_json(target, data)

        # Assert
        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["ok"] is True
        assert loaded["count"] == 42

    def test_write_json_중첩_디렉토리를_자동_생성한다(self, tmp_path: Path):
        # Arrange
        target = tmp_path / "a" / "b" / "c" / "data.json"

        # Act
        pipeline_mod._write_json(target, {"key": "value"})

        # Assert
        assert target.exists()


# ---------------------------------------------------------------------------
# _has_test_main_file
# ---------------------------------------------------------------------------

class TestHasTestMainFile:
    """SRS-PIPE-016: 테스트 main 함수 유무 감지."""

    def test_main_함수가_있는_파일은_True를_반환한다(self, tmp_path: Path):
        # Arrange
        f = tmp_path / "test_foo.c"
        f.write_text("int main(void) { return 0; }", encoding="utf-8")

        # Act
        result = pipeline_mod._has_test_main_file(f)

        # Assert
        assert result is True

    def test_main_함수가_없는_파일은_False를_반환한다(self, tmp_path: Path):
        # Arrange
        f = tmp_path / "foo.c"
        f.write_text("void foo(void) { return; }", encoding="utf-8")

        # Act
        result = pipeline_mod._has_test_main_file(f)

        # Assert
        assert result is False

    def test_존재하지_않는_파일은_False를_반환한다(self, tmp_path: Path):
        """경계값: 존재하지 않는 파일"""
        # Arrange
        f = tmp_path / "nonexistent.c"

        # Act
        result = pipeline_mod._has_test_main_file(f)

        # Assert
        assert result is False


# ---------------------------------------------------------------------------
# _extract_stub_functions (통합 수준 단위 테스트)
# ---------------------------------------------------------------------------

class TestExtractStubFunctions:
    """SRS-PIPE-017: C 스텁 함수 추출 기본 동작."""

    def test_빈_소스는_빈_리스트를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._extract_stub_functions("")

        # Assert
        assert result == []

    def test_None_소스는_빈_리스트를_반환한다(self):
        # Arrange & Act
        result = pipeline_mod._extract_stub_functions(None)

        # Assert
        assert result == []

    def test_단순_함수_시그니처를_추출한다(self):
        """기본 void 함수 추출."""
        # Arrange
        src = "void my_func(uint8_t val) { return; }\n"

        # Act
        result = pipeline_mod._extract_stub_functions(src)

        # Assert
        names = [f.get("name") for f in result]
        assert "my_func" in names
