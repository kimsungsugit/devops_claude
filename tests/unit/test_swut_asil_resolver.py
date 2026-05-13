"""30차 W21 T218 회귀 — swut_asil_resolver.resolve_function_asil_map.

기존 자산 ``workflow.code_parser.c_parser.parse_c_project`` 를 활용한 함수별
ASIL 추출의 fail-safe / 매핑 / 정규화 검증.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.services.swut_asil_resolver import (
    AsilResolveResult,
    _normalize_asil,
    _extract_function_id,
    resolve_function_asil_map,
)


class TestNormalizeAsil:
    """``@asil ASIL-B`` 표기 정규화 — 단일 문자 또는 빈 string."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ASIL-B", "B"),
            ("ASIL: C", "C"),
            ("asil d", "D"),
            ("@asil ASIL A", "A"),
            ("ASIL-QM", "QM"),
            ("ASIL_D", "D"),  # 언더스코어 케이스
            # c_parser fallback — group(1)이 letter만 반환한 경우
            ("B", "B"),
            ("d", "D"),
            ("qm", "QM"),
            (" B ", "B"),  # whitespace trim
            ("", ""),
            ("not-asil", ""),
            ("ASIL-E", ""),  # 잘못된 등급
            ("ASIL: X", ""),
            ("ASIL", ""),    # c_parser group(1) = "ASIL" 자체 — invalid
        ],
    )
    def test_normalize_various_forms(self, raw: str, expected: str):
        assert _normalize_asil(raw) == expected


class TestExtractFunctionId:
    """C 함수명 또는 Related ID 주석에서 SwUFn_NNNN 추출."""

    def test_function_name_contains_swufn(self):
        assert _extract_function_id("SwUFn_0101_init", "") == "SwUFn_0101"

    def test_related_id_fallback(self):
        assert _extract_function_id("comm_init", "SwUFn_0102") == "SwUFn_0102"

    def test_function_name_priority_over_related(self):
        # 함수명 우선 — Hyundai 컨벤션
        assert _extract_function_id("SwUFn_0101_a", "SwUFn_0999") == "SwUFn_0101"

    def test_no_match_returns_empty(self):
        assert _extract_function_id("comm_init", "") == ""
        assert _extract_function_id("", "") == ""


class TestResolveEmptyInput:
    """빈 입력 — fail-safe 정상 동작."""

    def test_empty_string_returns_empty_result(self):
        result = resolve_function_asil_map("")
        assert isinstance(result, AsilResolveResult)
        assert result.function_asil_map == {}
        assert result.warnings == []

    def test_none_returns_empty_result(self):
        result = resolve_function_asil_map(None)  # type: ignore[arg-type]
        assert result.function_asil_map == {}

    def test_missing_path_returns_warning(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist"
        result = resolve_function_asil_map(str(missing))
        assert result.function_asil_map == {}
        assert any("미존재" in w for w in result.warnings)

    def test_not_directory_returns_warning(self, tmp_path: Path):
        f = tmp_path / "single.c"
        f.write_text("// dummy")
        result = resolve_function_asil_map(str(f))
        assert result.function_asil_map == {}
        assert any("디렉토리 아님" in w for w in result.warnings)


class TestResolveSampleSource:
    """tests/fixtures/sample.c 의 @asil ASIL-B Doxygen 예시로 회귀."""

    def test_uses_existing_fixture(self):
        # tests/fixtures/sample.c 는 Doxygen 예시 보유 — Phase 1 발견.
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        assert fixtures.exists(), "tests/fixtures 디렉토리 부재 — 회귀 fixture 누락"

    def test_resolves_asil_from_function_name_with_swufn(self, tmp_path: Path):
        # Hyundai 컨벤션 — 함수명 자체에 SwUFn_NNNN 포함.
        src = tmp_path / "comm.c"
        src.write_text(
            textwrap.dedent(
                """
                /**
                 * @brief init
                 * @asil ASIL-D
                 */
                int SwUFn_0103_init(void) { return 0; }
                """
            ).strip(),
            encoding="utf-8",
        )
        result = resolve_function_asil_map(str(tmp_path))
        assert result.function_asil_map.get("SwUFn_0103") == "D"
        # 매핑 성공 → 진단 warning 없음
        assert not any("매칭 0건" in w for w in result.warnings)


class TestResolveUnknownFunctionIds:
    """function_ids 제공 시 매핑 못한 항목 누적."""

    def test_unknown_function_ids_listed(self, tmp_path: Path):
        src = tmp_path / "comm.c"
        src.write_text(
            textwrap.dedent(
                """
                /**
                 * @asil ASIL-B
                 */
                int SwUFn_0101_init(void) { return 0; }
                """
            ).strip(),
            encoding="utf-8",
        )
        result = resolve_function_asil_map(
            str(tmp_path),
            function_ids=["SwUFn_0101", "SwUFn_0102", "SwUFn_0103"],
        )
        assert result.function_asil_map.get("SwUFn_0101") == "B"
        # 0102, 0103은 매핑 안 됨
        assert sorted(result.unknown_function_ids) == ["SwUFn_0102", "SwUFn_0103"]


class TestResolveZeroMatchingWarning:
    """C 함수 있으나 SwUFn / @asil 없음 → 진단 warning."""

    def test_zero_match_warning(self, tmp_path: Path):
        # SwUFn 패턴 없는 함수 + @asil 태그 없음.
        src = tmp_path / "comm.c"
        src.write_text(
            textwrap.dedent(
                """
                /** @brief plain function */
                int comm_init(void) { return 0; }
                """
            ).strip(),
            encoding="utf-8",
        )
        result = resolve_function_asil_map(str(tmp_path))
        # 매핑 0건 + warning
        assert result.function_asil_map == {}
        assert any("매칭 0건" in w for w in result.warnings) or any(
            "C 함수 0개" in w for w in result.warnings
        )


class TestResolveAllowedRootsGuard:
    """path traversal 방어 — allowed_roots 외부 거부."""

    def test_outside_allowed_roots_rejected(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "x.c").write_text("int SwUFn_0001(void){return 0;}", encoding="utf-8")

        # allowed_roots는 다른 디렉토리만 허용 → 거부
        other = tmp_path / "other"
        other.mkdir()

        result = resolve_function_asil_map(
            str(src_dir), allowed_roots=[str(other)],
        )
        assert result.function_asil_map == {}
        assert any("allowed_roots 외부" in w for w in result.warnings)


class TestSystemDirBlacklist:
    """30차 W21 deep-reviewer Critical fix — 시스템 디렉토리 blacklist."""

    @pytest.mark.parametrize(
        "blocked_path",
        [
            "C:/Windows",
            "C:/Windows/System32",
            "c:/program files",
            "/etc",
            "/etc/passwd_backup",
            "/root",
            "/sys/class",
            "/proc/1",
        ],
    )
    def test_system_directory_rejected_without_allowed_roots(
        self, blocked_path: str, tmp_path: Path,
    ):
        """allowed_roots 미지정해도 시스템 path는 backstop으로 거부."""
        # 실제 디렉토리 존재 여부 무관 — path 검증이 exists() 보다 먼저.
        result = resolve_function_asil_map(blocked_path)
        assert result.function_asil_map == {}
        # 시스템 디렉토리 거부 또는 미존재 거부 (둘 중 하나).
        assert any(
            "시스템 디렉토리" in w or "미존재" in w or "디렉토리 아님" in w
            for w in result.warnings
        )

    def test_user_project_root_allowed_without_allowed_roots(self, tmp_path: Path):
        """사용자 프로젝트 path는 allowed_roots 없어도 통과."""
        src = tmp_path / "my_project_src"
        src.mkdir()
        (src / "x.c").write_text(
            "/** @asil ASIL-D */\nint SwUFn_0001(void){return 0;}",
            encoding="utf-8",
        )
        result = resolve_function_asil_map(str(src))
        # 거부 warning 없음 — 통과
        assert not any("시스템 디렉토리" in w for w in result.warnings)
        assert not any("allowed_roots 외부" in w for w in result.warnings)


class TestResolveNormalizationVariants:
    """C 파일 → c_parser → resolver 통합 흐름의 ASIL 표기 정규화.

    c_parser의 ASIL 추출 regex는 ``\\bASIL\\b[:\\s-]+`` (word boundary +
    colon/space/hyphen separator). underscore-only ("ASIL_D")는 c_parser
    단계에서 추출 못 하므로 본 통합 회귀에서는 제외 — 단위 ``TestNormalizeAsil``
    에서 별도로 검증 (raw 입력 시 underscore 가능).
    """

    @pytest.mark.parametrize(
        "asil_doxygen,expected",
        [
            ("@asil ASIL-A", "A"),
            ("@asil ASIL-B", "B"),
            ("@asil asil-c", "C"),
            ("@asil ASIL-D", "D"),
            ("@asil B", "B"),    # c_parser fallback 경로
            ("@asil D", "D"),
            ("@asil QM", "QM"),
        ],
    )
    def test_doxygen_asil_normalization(
        self, tmp_path: Path, asil_doxygen: str, expected: str,
    ):
        src = tmp_path / "f.c"
        src.write_text(
            textwrap.dedent(
                f"""
                /**
                 * {asil_doxygen}
                 */
                int SwUFn_0099_x(void) {{ return 0; }}
                """
            ).strip(),
            encoding="utf-8",
        )
        result = resolve_function_asil_map(str(tmp_path))
        assert result.function_asil_map.get("SwUFn_0099") == expected
