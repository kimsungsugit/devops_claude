"""LLM semantic validator 단위 회귀 (라운드 C T510).

검증 항목:
- source_file 존재/부재
- function 매칭/누락 (c_parser function_set 활용)
- line range 유효/무효
- excerpt non-empty
- semantic_report.score 가중치 계산
- file_resolver / function_set None 시 graceful skip
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workflow.llm_semantic_validator import (  # noqa: E402
    SemanticFinding,
    SemanticReport,
    validate_evidence,
)


class _MemResolver:
    """in-memory file_resolver — 회귀 격리. files dict로 존재 + read_text 흉내."""
    def __init__(self, files: dict[str, str] | None = None):
        self._files = files or {}

    def exists(self, path: str) -> bool:
        return path in self._files

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


class TestValidateEvidence:
    def test_empty_list_returns_passed(self):
        report = validate_evidence([])
        assert report.passed is True
        assert report.score == 1.0
        assert report.checked_count == 0
        assert report.findings == []

    def test_source_file_exists_no_warning(self):
        evidence = [{
            "source_type": "code",
            "source_file": "src/main.c",
            "excerpt": "void main(void) { return; }",
            "score": 0.9,
        }]
        resolver = _MemResolver({"src/main.c": "void main(void) { return; }"})
        report = validate_evidence(evidence, file_resolver=resolver)
        # source_file 존재 + excerpt 있음 → no source_file warning
        sf_findings = [f for f in report.findings if f.category == "source_file"]
        assert len(sf_findings) == 0
        assert report.passed is True

    def test_source_file_missing_emits_warning(self):
        evidence = [{
            "source_type": "code",
            "source_file": "src/missing.c",
            "excerpt": "void foo(void);",
            "score": 0.5,
        }]
        resolver = _MemResolver({})  # 빈 — missing.c 부재
        report = validate_evidence(evidence, file_resolver=resolver)
        sf_findings = [f for f in report.findings if f.category == "source_file"]
        assert len(sf_findings) == 1
        assert sf_findings[0].severity == "warning"
        assert "미존재" in sf_findings[0].message
        assert report.passed is True  # warning만이라 passed
        # score < 1.0 (warning 1건)
        assert report.score < 1.0

    def test_function_unmatched_emits_warning(self):
        evidence = [{
            "source_type": "code",
            "source_file": "src/main.c",
            "excerpt": "s_Init() and g_Foo_Call(arg)",
            "score": 0.7,
        }]
        function_set = {"s_Init"}  # g_Foo_Call 누락
        resolver = _MemResolver({"src/main.c": "stub"})
        report = validate_evidence(
            evidence, function_set=function_set, file_resolver=resolver,
        )
        fn_findings = [f for f in report.findings if f.category == "function"]
        assert len(fn_findings) == 1
        assert "g_Foo_Call" in fn_findings[0].message

    def test_function_set_none_skips_match(self):
        """function_set None이면 함수명 매칭 skip (회귀 fixture 환경)."""
        evidence = [{
            "source_type": "code",
            "source_file": "src/main.c",
            "excerpt": "nonexistent_func()",
            "score": 0.5,
        }]
        resolver = _MemResolver({"src/main.c": "stub"})
        report = validate_evidence(
            evidence, function_set=None, file_resolver=resolver,
        )
        fn_findings = [f for f in report.findings if f.category == "function"]
        assert len(fn_findings) == 0

    def test_line_range_invalid_emits_warning(self):
        evidence = [{
            "source_type": "code",
            "source_file": "src/main.c",
            "excerpt": "see L500 for context",
            "score": 0.5,
        }]
        # 파일이 100 라인뿐 — L500 무효
        resolver = _MemResolver({"src/main.c": "\n".join(str(i) for i in range(100))})
        report = validate_evidence(evidence, file_resolver=resolver)
        lr_findings = [f for f in report.findings if f.category == "line_range"]
        assert len(lr_findings) == 1
        assert "무효" in lr_findings[0].message

    def test_excerpt_empty_emits_warning(self):
        evidence = [{
            "source_type": "code",
            "source_file": "src/main.c",
            "excerpt": "",
            "score": 0.3,
        }]
        report = validate_evidence(evidence)
        ex_findings = [f for f in report.findings if f.category == "excerpt"]
        assert len(ex_findings) == 1

    def test_score_calculation_weighted(self):
        """score = (valid + 0.5 * warning_only) / total."""
        evidence = [
            # 정상 1건 (no warning)
            {"source_type": "code", "source_file": "src/a.c",
             "excerpt": "s_Init()", "score": 0.9},
            # warning 1건 (source_file 미존재)
            {"source_type": "code", "source_file": "src/missing.c",
             "excerpt": "s_Foo()", "score": 0.5},
        ]
        resolver = _MemResolver({"src/a.c": "stub"})
        function_set = {"s_Init", "s_Foo"}
        report = validate_evidence(
            evidence, function_set=function_set, file_resolver=resolver,
        )
        # 1 valid + 1 warning_only → (1 + 0.5) / 2 = 0.75
        assert report.score == 0.75
        assert report.passed is True

    def test_summary_categorizes_findings(self):
        evidence = [
            {"source_type": "code", "source_file": "src/missing.c",
             "excerpt": "stub", "score": 0.5},
            {"source_type": "code", "source_file": "",
             "excerpt": "", "score": 0.3},
        ]
        resolver = _MemResolver({})
        report = validate_evidence(evidence, file_resolver=resolver)
        assert report.summary["source_file_missing"] == 1
        assert report.summary["excerpt_empty"] == 1

    def test_warning_messages_prefix_semantic(self):
        """warning_messages property는 [semantic] prefix — warning_categories 호환."""
        evidence = [{
            "source_type": "code",
            "source_file": "src/missing.c",
            "excerpt": "s_Foo()",
            "score": 0.5,
        }]
        resolver = _MemResolver({})
        report = validate_evidence(evidence, file_resolver=resolver)
        msgs = report.warning_messages
        assert len(msgs) >= 1
        assert all(m.startswith("[semantic]") for m in msgs)

    def test_dataclass_to_dict_shape(self):
        report = SemanticReport()
        d = report.to_dict()
        assert "passed" in d
        assert "score" in d
        assert "findings" in d
        assert "summary" in d
        assert "checked_count" in d

    def test_finding_to_dict_shape(self):
        f = SemanticFinding(
            index=0, severity="warning", category="source_file",
            message="test", source_file="x.c", excerpt_preview="abc",
        )
        d = f.to_dict()
        assert d["index"] == 0
        assert d["severity"] == "warning"
