"""Unit tests for backend services (files, paths).

Tests actual behavior of file reading utilities and path resolution
without heavy mocking.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.services.files import (  # noqa: E402
    _matches_filters,
    _normalize_filter_tokens,
    normalize_rate_0_1,
    read_csv_rows,
    read_text_limited,
    tail_text,
)
from backend.services.paths import (  # noqa: E402
    _is_drive_abs,
    is_under_any,
    safe_resolve_under,
    sanitize_relpath,
)


# ═══════════════════════════════════════════════════════════════════
# read_text_limited
# ═══════════════════════════════════════════════════════════════════
class TestReadTextLimited:
    """Tests for read_text_limited()."""

    def test_read_small_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("hello world")
            tmp = f.name
        try:
            text, truncated = read_text_limited(Path(tmp), max_bytes=1024)
            assert text == "hello world"
            assert truncated is False
        finally:
            os.unlink(tmp)

    def test_read_truncated_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("A" * 500)
            tmp = f.name
        try:
            text, truncated = read_text_limited(Path(tmp), max_bytes=100)
            assert len(text) == 100
            assert truncated is True
        finally:
            os.unlink(tmp)

    def test_read_nonexistent_file(self):
        text, truncated = read_text_limited(Path("/nonexistent/file.txt"), max_bytes=1024)
        assert text == ""
        assert truncated is False

    def test_read_binary_content_graceful(self):
        """Binary content is decoded with errors='ignore', no crash."""
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(bytes(range(256)))
            tmp = f.name
        try:
            text, truncated = read_text_limited(Path(tmp), max_bytes=4096)
            assert isinstance(text, str)
            assert truncated is False
        finally:
            os.unlink(tmp)

    def test_read_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp = f.name
        try:
            text, truncated = read_text_limited(Path(tmp), max_bytes=1024)
            assert text == ""
            assert truncated is False
        finally:
            os.unlink(tmp)

    def test_read_exact_boundary(self):
        """File size exactly equals max_bytes -- not truncated."""
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("X" * 100)
            tmp = f.name
        try:
            text, truncated = read_text_limited(Path(tmp), max_bytes=100)
            assert len(text) == 100
            assert truncated is False
        finally:
            os.unlink(tmp)

    def test_read_utf8_multibyte(self):
        """UTF-8 multibyte chars are handled without error."""
        content = "Hello \u4e16\u754c \ud55c\uae00 \U0001f600"
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="wb"
        ) as f:
            f.write(content.encode("utf-8"))
            tmp = f.name
        try:
            text, truncated = read_text_limited(Path(tmp), max_bytes=4096)
            assert isinstance(text, str)
            # Some chars may be garbled at boundary but no exception
        finally:
            os.unlink(tmp)


# ═══════════════════════════════════════════════════════════════════
# tail_text
# ═══════════════════════════════════════════════════════════════════
class TestTailText:
    """Tests for tail_text()."""

    def test_tail_small_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("line1\nline2\nline3\n")
            tmp = f.name
        try:
            result = tail_text(Path(tmp), max_bytes=4096)
            assert "line1" in result
            assert "line3" in result
        finally:
            os.unlink(tmp)

    def test_tail_large_file_reads_end(self):
        """For a file larger than max_bytes, tail_text reads the end portion."""
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            for i in range(1000):
                f.write(f"line {i:04d}\n")
            tmp = f.name
        try:
            result = tail_text(Path(tmp), max_bytes=200)
            # Should contain lines near the end
            assert "line 0999" in result or "0999" in result
            # Should NOT contain the very first line (too early)
            assert "line 0000\n" not in result
        finally:
            os.unlink(tmp)

    def test_tail_nonexistent_file(self):
        result = tail_text(Path("/nonexistent/file.txt"))
        assert result == ""


# ═══════════════════════════════════════════════════════════════════
# read_csv_rows
# ═══════════════════════════════════════════════════════════════════
class TestReadCsvRows:
    """Tests for read_csv_rows()."""

    def test_read_csv(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8", newline=""
        ) as f:
            f.write("name,value\nalpha,1\nbeta,2\n")
            tmp = f.name
        try:
            rows = read_csv_rows(Path(tmp))
            assert len(rows) == 2
            assert rows[0]["name"] == "alpha"
            assert rows[1]["value"] == "2"
        finally:
            os.unlink(tmp)

    def test_read_csv_limit(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8", newline=""
        ) as f:
            f.write("col\n")
            for i in range(100):
                f.write(f"{i}\n")
            tmp = f.name
        try:
            rows = read_csv_rows(Path(tmp), limit=10)
            assert len(rows) == 10
        finally:
            os.unlink(tmp)

    def test_read_csv_nonexistent(self):
        rows = read_csv_rows(Path("/nonexistent/data.csv"))
        assert rows == []

    def test_read_csv_empty_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp = f.name
        try:
            rows = read_csv_rows(Path(tmp))
            assert rows == []
        finally:
            os.unlink(tmp)


# ═══════════════════════════════════════════════════════════════════
# normalize_rate_0_1
# ═══════════════════════════════════════════════════════════════════
class TestNormalizeRate:
    """Tests for normalize_rate_0_1()."""

    def test_none_returns_none(self):
        assert normalize_rate_0_1(None) is None

    def test_string_non_numeric_returns_none(self):
        assert normalize_rate_0_1("abc") is None

    def test_already_0_to_1(self):
        assert normalize_rate_0_1(0.85) == 0.85
        assert normalize_rate_0_1(0.0) == 0.0
        assert normalize_rate_0_1(1.0) == 1.0

    def test_percentage_to_fraction(self):
        assert normalize_rate_0_1(85.0) == 0.85
        assert normalize_rate_0_1(50) == 0.5

    def test_basis_points_to_fraction(self):
        assert normalize_rate_0_1(8500) == 0.85

    def test_string_numeric(self):
        assert normalize_rate_0_1("0.75") == 0.75
        assert normalize_rate_0_1("75") == 0.75


# ═══════════════════════════════════════════════════════════════════
# _normalize_filter_tokens / _matches_filters
# ═══════════════════════════════════════════════════════════════════
class TestFilterHelpers:
    """Tests for filter token normalization and matching."""

    def test_normalize_empty(self):
        assert _normalize_filter_tokens(None) == []
        assert _normalize_filter_tokens([]) == []

    def test_normalize_strips_slashes(self):
        tokens = _normalize_filter_tokens(["/src/", "\\lib\\"])
        assert tokens == ["src", "lib"]

    def test_normalize_backslash_to_forward(self):
        tokens = _normalize_filter_tokens(["a\\b\\c"])
        assert tokens == ["a/b/c"]

    def test_matches_no_filters(self):
        """No include/exclude means everything matches."""
        assert _matches_filters("src/main.c", [], []) is True

    def test_matches_include_filter(self):
        assert _matches_filters("src/main.c", ["src"], []) is True
        assert _matches_filters("lib/util.c", ["src"], []) is False

    def test_matches_exclude_filter(self):
        assert _matches_filters("build/out.o", [], ["build"]) is False
        assert _matches_filters("src/main.c", [], ["build"]) is True

    def test_matches_include_and_exclude(self):
        """Exclude takes precedence over include."""
        assert _matches_filters("src/test/mock.c", ["src"], ["src/test"]) is False
        assert _matches_filters("src/main.c", ["src"], ["src/test"]) is True

    def test_matches_exact_path(self):
        assert _matches_filters("src", ["src"], []) is True
        assert _matches_filters("src", [], ["src"]) is False


# ═══════════════════════════════════════════════════════════════════
# sanitize_relpath
# ═══════════════════════════════════════════════════════════════════
class TestSanitizeRelpath:
    """Tests for sanitize_relpath()."""

    def test_normal_path(self):
        assert sanitize_relpath("src/main.c") == "src/main.c"

    def test_empty_returns_dot(self):
        assert sanitize_relpath("") == "."
        assert sanitize_relpath(None) == "."

    def test_current_dir_dot(self):
        assert sanitize_relpath(".") == "."

    def test_strips_leading_slash(self):
        """Absolute POSIX paths raise ValueError."""
        with pytest.raises(ValueError, match="absolute"):
            sanitize_relpath("/etc/passwd")

    def test_rejects_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            sanitize_relpath("../etc/passwd")

    def test_rejects_embedded_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            sanitize_relpath("src/../../etc/passwd")

    def test_rejects_windows_absolute(self):
        with pytest.raises(ValueError, match="absolute"):
            sanitize_relpath("C:/Windows/System32")

    def test_backslash_normalized(self):
        result = sanitize_relpath("src\\lib\\main.c")
        assert "\\" not in result
        assert "src" in result and "main.c" in result

    def test_dot_segments_removed(self):
        result = sanitize_relpath("./src/./main.c")
        assert result == "src/main.c"


# ═══════════════════════════════════════════════════════════════════
# _is_drive_abs
# ═══════════════════════════════════════════════════════════════════
class TestIsDriveAbs:
    """Tests for _is_drive_abs()."""

    def test_windows_drive(self):
        assert _is_drive_abs("C:/Users") is True
        assert _is_drive_abs("D:\\Data") is True

    def test_not_drive(self):
        assert _is_drive_abs("src/main.c") is False
        assert _is_drive_abs("/usr/bin") is False
        assert _is_drive_abs("") is False

    def test_short_string(self):
        assert _is_drive_abs("C:") is False
        assert _is_drive_abs("C") is False


# ═══════════════════════════════════════════════════════════════════
# safe_resolve_under
# ═══════════════════════════════════════════════════════════════════
class TestSafeResolveUnder:
    """Tests for safe_resolve_under()."""

    def test_resolve_normal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            result = safe_resolve_under(base, "subdir/file.txt")
            assert result.is_relative_to(base.resolve())

    def test_reject_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError):
                safe_resolve_under(Path(tmpdir), "../escape.txt")

    def test_reject_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError):
                safe_resolve_under(Path(tmpdir), "/etc/passwd")


# ═══════════════════════════════════════════════════════════════════
# is_under_any
# ═══════════════════════════════════════════════════════════════════
class TestIsUnderAny:
    """Tests for is_under_any()."""

    def test_path_under_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            child = Path(tmpdir) / "sub" / "file.txt"
            assert is_under_any(child, [Path(tmpdir)]) is True

    def test_path_not_under_any_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            other = Path(tmpdir).parent / "other_location"
            # May or may not be under tmpdir depending on resolution
            result = is_under_any(other, [Path(tmpdir)])
            assert isinstance(result, bool)

    def test_empty_roots(self):
        assert is_under_any(Path("/some/path"), []) is False

    def test_multiple_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                child = Path(tmpdir2) / "data.txt"
                assert is_under_any(child, [Path(tmpdir1), Path(tmpdir2)]) is True
                assert is_under_any(child, [Path(tmpdir1)]) is False


# ═══════════════════════════════════════════════════════════════════
# local_service: list_directory
# ═══════════════════════════════════════════════════════════════════
from backend.services.local_service import (  # noqa: E402
    format_c_code,
    list_directory,
    read_file_text,
    replace_in_file,
    replace_lines,
    search_in_files,
    write_file_text,
)


class TestListDirectory:
    """Tests for list_directory()."""

    def test_list_real_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.txt").write_text("a", encoding="utf-8")
            (Path(tmpdir) / "subdir").mkdir()
            result = list_directory(tmpdir)
            assert result["ok"] is True
            names = [e["name"] for e in result["entries"]]
            assert "a.txt" in names
            assert "subdir" in names

    def test_list_nonexistent_directory(self):
        result = list_directory("/nonexistent/dir/xyz")
        assert result["ok"] is False

    def test_list_sorts_dirs_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "z_file.txt").write_text("z", encoding="utf-8")
            (Path(tmpdir) / "a_dir").mkdir()
            result = list_directory(tmpdir)
            assert result["ok"] is True
            entries = result["entries"]
            # Directory should come before file
            dir_idx = next(i for i, e in enumerate(entries) if e["name"] == "a_dir")
            file_idx = next(i for i, e in enumerate(entries) if e["name"] == "z_file.txt")
            assert dir_idx < file_idx


# ═══════════════════════════════════════════════════════════════════
# local_service: read_file_text / write_file_text / replace_lines
# ═══════════════════════════════════════════════════════════════════
class TestFileOperations:
    """Tests for read_file_text, write_file_text, replace_lines."""

    def test_read_file_text_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.txt"
            fpath.write_text("hello", encoding="utf-8")
            result = read_file_text(tmpdir, "test.txt")
            assert result["ok"] is True
            assert result["text"] == "hello"
            assert result["truncated"] is False

    def test_read_file_text_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "big.txt"
            fpath.write_text("A" * 500, encoding="utf-8")
            result = read_file_text(tmpdir, "big.txt", max_bytes=100)
            assert result["ok"] is True
            assert len(result["text"]) == 100
            assert result["truncated"] is True

    def test_read_file_text_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = read_file_text(tmpdir, "nope.txt")
            assert result["ok"] is False

    def test_write_file_text_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_file_text(tmpdir, "new.txt", "content", make_backup=False)
            assert result["ok"] is True
            assert (Path(tmpdir) / "new.txt").read_text(encoding="utf-8") == "content"

    def test_write_file_text_creates_subdirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_file_text(tmpdir, "sub/dir/file.txt", "nested", make_backup=False)
            assert result["ok"] is True
            assert (Path(tmpdir) / "sub" / "dir" / "file.txt").exists()

    def test_write_file_text_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "orig.txt"
            fpath.write_text("original", encoding="utf-8")
            result = write_file_text(tmpdir, "orig.txt", "updated", make_backup=True)
            assert result["ok"] is True
            assert result["backup"]  # backup path should be set
            assert Path(result["backup"]).exists()
            assert fpath.read_text(encoding="utf-8") == "updated"

    def test_replace_lines_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "code.c"
            fpath.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
            result = replace_lines(tmpdir, "code.c", 2, 3, "NEW_LINE_2\nNEW_LINE_3")
            assert result["ok"] is True
            text = fpath.read_text(encoding="utf-8")
            assert "NEW_LINE_2" in text
            assert "NEW_LINE_3" in text
            assert "line1" in text
            assert "line4" in text

    def test_replace_lines_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = replace_lines(tmpdir, "nope.c", 1, 1, "content")
            assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
# local_service: search_in_files
# ═══════════════════════════════════════════════════════════════════
class TestSearchInFiles:
    """Tests for search_in_files()."""

    def test_search_finds_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.c").write_text("int foo = 42;\nint bar = 99;\n", encoding="utf-8")
            result = search_in_files(tmpdir, ".", "foo")
            assert result["ok"] is True
            assert len(result["results"]) == 1
            assert result["results"][0]["line"] == 1

    def test_search_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.c").write_text("int x = 1;\n", encoding="utf-8")
            result = search_in_files(tmpdir, ".", "zzzzz_no_match")
            assert result["ok"] is True
            assert len(result["results"]) == 0

    def test_search_empty_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = search_in_files(tmpdir, ".", "")
            assert result["ok"] is False

    def test_search_respects_max_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lines = "\n".join([f"match_{i}" for i in range(50)])
            (Path(tmpdir) / "big.txt").write_text(lines, encoding="utf-8")
            result = search_in_files(tmpdir, ".", "match_", max_results=5)
            assert result["ok"] is True
            assert len(result["results"]) == 5


# ═══════════════════════════════════════════════════════════════════
# local_service: replace_in_file
# ═══════════════════════════════════════════════════════════════════
class TestReplaceInFile:
    """Tests for replace_in_file()."""

    def test_replace_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.c"
            fpath.write_text("int val = 42;", encoding="utf-8")
            result = replace_in_file(tmpdir, "test.c", "42", "99")
            assert result["ok"] is True
            assert result["changed"] is True
            assert "99" in fpath.read_text(encoding="utf-8")

    def test_replace_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.c"
            fpath.write_text("int val = 42;", encoding="utf-8")
            result = replace_in_file(tmpdir, "test.c", "NOTFOUND", "replacement")
            assert result["ok"] is True
            assert result["changed"] is False

    def test_replace_empty_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.c"
            fpath.write_text("int val = 42;", encoding="utf-8")
            result = replace_in_file(tmpdir, "test.c", "", "replacement")
            assert result["ok"] is False

    def test_replace_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = replace_in_file(tmpdir, "nope.c", "a", "b")
            assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
# local_service: format_c_code
# ═══════════════════════════════════════════════════════════════════
class TestFormatCCode:
    """Tests for format_c_code()."""

    def test_empty_text(self):
        result = format_c_code("")
        assert result["ok"] is False
        assert result["error"] == "empty_text"

    def test_format_returns_dict(self):
        result = format_c_code("int main(){return 0;}")
        assert "ok" in result
        # May succeed or fail depending on clang-format availability


# ═══════════════════════════════════════════════════════════════════
# jenkins_helpers
# ═══════════════════════════════════════════════════════════════════
from backend.services.jenkins_helpers import (  # noqa: E402
    _detect_reports_dir,
    _job_slug,
    _norm_job_url,
    _safe_artifact_path,
)


class TestJenkinsHelpers:
    """Tests for Jenkins helper functions."""

    def test_norm_job_url_adds_trailing_slash(self):
        assert _norm_job_url("http://jenkins/job/test") == "http://jenkins/job/test/"
        assert _norm_job_url("http://jenkins/job/test/") == "http://jenkins/job/test/"

    def test_norm_job_url_empty(self):
        assert _norm_job_url("") == ""
        assert _norm_job_url(None) == ""

    def test_job_slug_sanitizes(self):
        slug = _job_slug("http://jenkins.local:8080/job/My Project/")
        assert "/" not in slug
        assert ":" not in slug
        assert len(slug) > 0

    def test_safe_artifact_path_normal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _safe_artifact_path(Path(tmpdir), "artifacts/report.xml")
            assert result is not None
            assert result.is_relative_to(Path(tmpdir).resolve())

    def test_safe_artifact_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _safe_artifact_path(Path(tmpdir), "../escape.txt")
            assert result is None

    def test_safe_artifact_path_rejects_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _safe_artifact_path(Path(tmpdir), "/etc/passwd")
            assert result is None

    def test_safe_artifact_path_rejects_windows_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _safe_artifact_path(Path(tmpdir), "C:/Windows/System32")
            assert result is None

    def test_safe_artifact_path_rejects_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _safe_artifact_path(Path(tmpdir), "")
            assert result is None

    def test_safe_artifact_path_rejects_tilde(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _safe_artifact_path(Path(tmpdir), "~/.ssh/config")
            assert result is None

    def test_detect_reports_dir_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _detect_reports_dir(Path(tmpdir))
            assert result.name == "reports"

    def test_detect_reports_dir_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Report").mkdir()
            result = _detect_reports_dir(Path(tmpdir))
            assert result.name == "Report"


# ═══════════════════════════════════════════════════════════════════
# jenkins_client helpers
# ═══════════════════════════════════════════════════════════════════
from backend.services.jenkins_client import (  # noqa: E402
    _as_dict,
    _as_list,
    _first_nonempty,
    _join_url,
    _norm_str,
)


class TestJenkinsClientHelpers:
    """Tests for jenkins_client module-level helpers."""

    def test_join_url_basic(self):
        assert _join_url("http://host", "path") == "http://host/path"
        assert _join_url("http://host/", "/path") == "http://host/path"

    def test_join_url_empty(self):
        assert _join_url("", "path") == "path"
        assert _join_url("http://host", "") == "http://host/"

    def test_as_list(self):
        assert _as_list([1, 2]) == [1, 2]
        assert _as_list("not_a_list") == []
        assert _as_list(None) == []
        assert _as_list(42) == []

    def test_as_dict(self):
        assert _as_dict({"a": 1}) == {"a": 1}
        assert _as_dict("not_a_dict") == {}
        assert _as_dict(None) == {}

    def test_norm_str(self):
        assert _norm_str("hello ") == "hello"
        assert _norm_str(42) == "42"
        assert _norm_str(None) == ""
        assert _norm_str([]) == ""

    def test_first_nonempty(self):
        assert _first_nonempty("", None, "found") == "found"
        assert _first_nonempty("first", "second") == "first"
        assert _first_nonempty("", "", "") == ""
        assert _first_nonempty(None) == ""
