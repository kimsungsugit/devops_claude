"""MCP stdio server — exposes project MCP tools to Claude Code.

Run: python -m backend.mcp.stdio_server
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Flush stderr immediately so error messages appear before process exit
import functools
print = functools.partial(print, flush=True)  # noqa: A001 — intentional shadow

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

from backend.mcp import (
    get_code_search_mcp_server,
    get_docs_mcp_server,
    get_git_mcp_server,
    get_jenkins_mcp_server,
    get_report_mcp_server,
)
from backend.services import local_service as _ls

mcp = FastMCP("devops-release")

# ── Report tools ──────────────────────────────────────────────────────
_report = get_report_mcp_server()


@mcp.tool()
def report_summary(report_dir: str) -> str:
    """Get build/test report summary from a report directory."""
    return json.dumps(_report.call_tool("get_report_summary", report_dir=report_dir), ensure_ascii=False, default=str)


@mcp.tool()
def report_findings(report_dir: str) -> str:
    """Get findings (warnings, errors) from a report directory."""
    return json.dumps(_report.call_tool("get_findings", report_dir=report_dir), ensure_ascii=False, default=str)


@mcp.tool()
def report_coverage(report_dir: str) -> str:
    """Get code coverage data from a report directory."""
    return json.dumps(_report.call_tool("get_coverage", report_dir=report_dir), ensure_ascii=False, default=str)


@mcp.tool()
def report_log(report_dir: str, log_name: str = "system", max_bytes: int = 98304) -> str:
    """Read log excerpt from a report directory."""
    return json.dumps(_report.call_tool("get_log_excerpt", report_dir=report_dir, log_name=log_name, max_bytes=max_bytes), ensure_ascii=False, default=str)


# ── Git tools ─────────────────────────────────────────────────────────
_git = get_git_mcp_server()


@mcp.tool()
def git_status(project_root: str) -> str:
    """Get git status of the project."""
    return json.dumps(_git.call_tool("git_status", project_root=project_root), ensure_ascii=False, default=str)


@mcp.tool()
def git_diff(project_root: str, path: str = "") -> str:
    """Get git diff of the project."""
    return json.dumps(_git.call_tool("git_diff", project_root=project_root, path=path), ensure_ascii=False, default=str)


@mcp.tool()
def git_log(project_root: str, max_count: int = 30) -> str:
    """Get recent git log entries."""
    return json.dumps(_git.call_tool("git_log", project_root=project_root, max_count=max_count), ensure_ascii=False, default=str)


@mcp.tool()
def git_changed_files(project_root: str) -> str:
    """List files changed in the working tree."""
    return json.dumps(_git.call_tool("list_changed_files", project_root=project_root), ensure_ascii=False, default=str)


# ── Code search tools ────────────────────────────────────────────────
_code = get_code_search_mcp_server()


@mcp.tool()
def search_code(query: str, project_root: str = "", max_results: int = 20, file_glob: str = "", exclude_glob: str = "") -> str:
    """Search for code patterns in the source tree. Use file_glob (e.g. '*.c') and exclude_glob (e.g. '*.test.*') to filter."""
    return json.dumps(_code.call_tool("search_code", project_root=project_root, query=query, max_results=max_results, file_glob=file_glob, exclude_glob=exclude_glob), ensure_ascii=False, default=str)


@mcp.tool()
def read_source_file(project_root: str, rel_path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Read a source file (optionally a specific line range)."""
    return json.dumps(_code.call_tool("read_file", project_root=project_root, rel_path=rel_path, start_line=start_line, end_line=end_line), ensure_ascii=False, default=str)


# ── Docs tools ────────────────────────────────────────────────────────
_docs = get_docs_mcp_server()


@mcp.tool()
def list_docs(query: str = "") -> str:
    """List available documentation files, optionally filtered by query."""
    return json.dumps(_docs.call_tool("list_docs", query=query), ensure_ascii=False, default=str)


@mcp.tool()
def search_docs(query: str) -> str:
    """Search documentation content."""
    return json.dumps(_docs.call_tool("search_docs", query=query), ensure_ascii=False, default=str)


@mcp.tool()
def read_doc(rel_path: str) -> str:
    """Read a documentation file."""
    return json.dumps(_docs.call_tool("read_doc", rel_path=rel_path), ensure_ascii=False, default=str)


# ── Jenkins tools ─────────────────────────────────────────────────────
_jenkins = get_jenkins_mcp_server()


@mcp.tool()
def jenkins_build_summary(job_url: str, cache_root: str = ".devops_pro_cache", build_selector: str = "lastSuccessfulBuild") -> str:
    """Get Jenkins build report summary."""
    return json.dumps(_jenkins.call_tool("get_build_report_summary", job_url=job_url, cache_root=cache_root, build_selector=build_selector), ensure_ascii=False, default=str)


@mcp.tool()
def jenkins_build_status(job_url: str, cache_root: str = ".devops_pro_cache", build_selector: str = "lastSuccessfulBuild") -> str:
    """Get Jenkins build status."""
    return json.dumps(_jenkins.call_tool("get_build_report_status", job_url=job_url, cache_root=cache_root, build_selector=build_selector), ensure_ascii=False, default=str)


# ── Write tools ───────────────────────────────────────────────────────

def _assert_under_root(project_root: str, rel_path: str) -> Path:
    """Resolve rel_path and verify it is strictly under project_root.

    Args:
        project_root: Absolute path to the project root directory.
        rel_path: Relative path to resolve.

    Returns:
        Resolved absolute Path.

    Raises:
        ValueError: If the resolved path escapes project_root or targets a
            forbidden file (e.g. .env).
    """
    root = Path(project_root).resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"Path escapes project root: {rel_path!r}")
    if target.name == ".env" or target.suffix == "" and target.stem == ".env":
        raise ValueError(".env files are forbidden for write operations")
    return target


@mcp.tool()
def git_stage_files(project_root: str, paths: str) -> str:
    """Stage one or more files with git add.

    Args:
        project_root: Absolute path to the git repository root.
        paths: Comma-separated relative file paths to stage.

    Returns:
        JSON object with keys ``rc`` (return code) and ``output`` (git output).
    """
    root = Path(project_root).resolve()
    path_list = [p.strip() for p in paths.split(",") if p.strip()]
    # Validate every path before touching git
    for p in path_list:
        _assert_under_root(project_root, p)
    result = _ls.git_stage(str(root), ".", path_list)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def write_file(project_root: str, rel_path: str, content: str) -> str:
    """Write (or overwrite) a text file inside the project.

    Args:
        project_root: Absolute path to the project root directory.
        rel_path: Relative path of the file to write.
        content: Full text content to write (UTF-8).

    Returns:
        JSON object with keys ``ok``, ``path``, and ``backup``.
    """
    _assert_under_root(project_root, rel_path)
    result = _ls.write_file_text(project_root, rel_path, content)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def replace_in_file(project_root: str, rel_path: str, old_text: str, new_text: str) -> str:
    """Replace the first occurrence of old_text with new_text in a file.

    Args:
        project_root: Absolute path to the project root directory.
        rel_path: Relative path of the file to edit.
        old_text: Exact text to search for.
        new_text: Replacement text.

    Returns:
        JSON object with keys ``ok`` and ``changed`` (bool).
    """
    _assert_under_root(project_root, rel_path)
    result = _ls.replace_in_file(project_root, rel_path, old_text, new_text)
    return json.dumps(result, ensure_ascii=False, default=str)


# ── Health check ─────────────────────────────────────────────────────
@mcp.tool()
def health_check() -> str:
    """Check MCP server health and list available tools."""
    status = {}
    for name, srv in [("report", _report), ("git", _git), ("code", _code), ("docs", _docs), ("jenkins", _jenkins)]:
        try:
            tools = srv.list_tools()
            status[name] = {"ok": True, "tools": len(tools)}
        except Exception as e:
            status[name] = {"ok": False, "error": str(e)}
    return json.dumps({"status": "healthy", "servers": status}, ensure_ascii=False, default=str)


# ── Cache management ──────────────────────────────────────────────────
@mcp.tool()
def clear_report_cache(report_dir: str = "") -> str:
    """Clear cached report data to force fresh reads."""
    _report.clear_cache(report_dir if report_dir else None)
    return json.dumps({"ok": True, "cleared": report_dir or "all"}, ensure_ascii=False)


# ── Git resources ─────────────────────────────────────────────────────
@mcp.resource("git://repo/status")
def res_git_status() -> str:
    """Current git working tree status."""
    return json.dumps(
        _git.read_resource("git://repo/status", project_root=str(_PROJECT_ROOT)),
        ensure_ascii=False,
        default=str,
    )


@mcp.resource("git://repo/diff")
def res_git_diff() -> str:
    """Current git diff of the working tree."""
    return json.dumps(
        _git.read_resource("git://repo/diff", project_root=str(_PROJECT_ROOT)),
        ensure_ascii=False,
        default=str,
    )


@mcp.resource("git://repo/log")
def res_git_log() -> str:
    """Recent git commit log."""
    return json.dumps(
        _git.read_resource("git://repo/log", project_root=str(_PROJECT_ROOT)),
        ensure_ascii=False,
        default=str,
    )


@mcp.resource("git://repo/changed-files")
def res_git_changed_files() -> str:
    """Files changed in the current working tree."""
    return json.dumps(
        _git.read_resource("git://repo/changed-files", project_root=str(_PROJECT_ROOT)),
        ensure_ascii=False,
        default=str,
    )


@mcp.resource("docs://index")
def res_docs_index() -> str:
    """Index of all available documentation files."""
    return json.dumps(
        _docs.read_resource("docs://index"),
        ensure_ascii=False,
        default=str,
    )


# ── Prompts ───────────────────────────────────────────────────────────
@mcp.prompt()
def triage_build_failure() -> str:
    """Triage a build failure and suggest the next remediation step."""
    return _report.get_prompt("triage_build_failure")


@mcp.prompt()
def summarize_change_risk() -> str:
    """Summarize repository change risk and identify areas to review."""
    return _git.get_prompt("summarize_change_risk")


@mcp.prompt()
def review_coverage_gap() -> str:
    """Review coverage metrics and explain the most useful next step."""
    return _report.get_prompt("review_coverage_gap")


if __name__ == "__main__":
    import os

    # Windows: switch stdin/stdout to binary mode to prevent CRLF translation
    # that would corrupt the JSON-RPC framing used by the MCP stdio transport.
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    try:
        mcp.run(transport="stdio")
    except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError):
        pass
    except Exception as exc:
        print(f"MCP server error: {exc}", file=sys.stderr)
        sys.exit(1)
