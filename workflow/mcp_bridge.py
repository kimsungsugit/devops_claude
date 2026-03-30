from __future__ import annotations

import threading
from typing import Dict, List

from langchain_core.tools import BaseTool, StructuredTool

from backend.mcp import (
    get_code_search_mcp_server,
    get_docs_mcp_server,
    get_git_mcp_server,
    get_jenkins_mcp_server,
    get_report_mcp_server,
)

_TOOLS_LOCK = threading.Lock()
_TOOLS_CACHE: Dict[str, BaseTool] | None = None


def _build_tools() -> Dict[str, BaseTool]:
    report = get_report_mcp_server()
    jenkins = get_jenkins_mcp_server()
    git = get_git_mcp_server()
    code = get_code_search_mcp_server()
    docs = get_docs_mcp_server()

    def report_get_report_summary(report_dir: str) -> dict:
        return report.call_tool("get_report_summary", report_dir=report_dir)

    def report_get_run_status(report_dir: str) -> dict:
        return report.call_tool("get_run_status", report_dir=report_dir)

    def report_get_findings(report_dir: str) -> dict:
        return report.call_tool("get_findings", report_dir=report_dir)

    def report_get_log_excerpt(report_dir: str, log_name: str = "system", max_bytes: int = 98304) -> dict:
        return report.call_tool("get_log_excerpt", report_dir=report_dir, log_name=log_name, max_bytes=max_bytes)

    def jenkins_get_build_report_summary(job_url: str, cache_root: str, build_selector: str = "lastSuccessfulBuild") -> dict:
        return jenkins.call_tool("get_build_report_summary", job_url=job_url, cache_root=cache_root, build_selector=build_selector)

    def jenkins_get_build_report_status(job_url: str, cache_root: str, build_selector: str = "lastSuccessfulBuild") -> dict:
        return jenkins.call_tool("get_build_report_status", job_url=job_url, cache_root=cache_root, build_selector=build_selector)

    def jenkins_get_build_report_findings(job_url: str, cache_root: str, build_selector: str = "lastSuccessfulBuild") -> dict:
        return jenkins.call_tool("get_build_report_findings", job_url=job_url, cache_root=cache_root, build_selector=build_selector)

    def jenkins_get_console_excerpt(job_url: str, cache_root: str, build_selector: str = "lastSuccessfulBuild", max_bytes: int = 245760) -> dict:
        return jenkins.call_tool("get_console_excerpt", job_url=job_url, cache_root=cache_root, build_selector=build_selector, max_bytes=max_bytes)

    def git_status(project_root: str, workdir_rel: str = ".") -> dict:
        return git.call_tool("git_status", project_root=project_root, workdir_rel=workdir_rel)

    def git_diff(project_root: str, workdir_rel: str = ".", path: str = "") -> dict:
        return git.call_tool("git_diff", project_root=project_root, workdir_rel=workdir_rel, path=path)

    def git_log(project_root: str, workdir_rel: str = ".", max_count: int = 30) -> dict:
        return git.call_tool("git_log", project_root=project_root, workdir_rel=workdir_rel, max_count=max_count)

    def git_list_changed_files(project_root: str, workdir_rel: str = ".") -> dict:
        return git.call_tool("list_changed_files", project_root=project_root, workdir_rel=workdir_rel)

    def code_search_code(project_root: str, rel_path: str = ".", query: str = "", max_results: int = 50) -> dict:
        return code.call_tool("search_code", project_root=project_root, rel_path=rel_path, query=query, max_results=max_results)

    def code_read_file_range(project_root: str, rel_path: str, start_line: int = 1, end_line: int = 120) -> dict:
        return code.call_tool("read_file_range", project_root=project_root, rel_path=rel_path, start_line=start_line, end_line=end_line)

    def code_list_directory(project_root: str, rel_path: str = ".") -> dict:
        return code.call_tool("list_directory", project_root=project_root, rel_path=rel_path)

    def docs_list_docs() -> dict:
        return docs.call_tool("list_docs")

    def docs_search_docs(query: str, max_results: int = 20) -> dict:
        return docs.call_tool("search_docs", query=query, max_results=max_results)

    def docs_read_doc(rel_path: str, max_bytes: int = 65536) -> dict:
        return docs.call_tool("read_doc", rel_path=rel_path, max_bytes=max_bytes)

    tools = {
        "report_get_report_summary": StructuredTool.from_function(report_get_report_summary, name="report_get_report_summary", description="Read the local report summary via the internal report MCP server."),
        "report_get_run_status": StructuredTool.from_function(report_get_run_status, name="report_get_run_status", description="Read the local run status via the internal report MCP server."),
        "report_get_findings": StructuredTool.from_function(report_get_findings, name="report_get_findings", description="Read the local findings list via the internal report MCP server."),
        "report_get_log_excerpt": StructuredTool.from_function(report_get_log_excerpt, name="report_get_log_excerpt", description="Read a log excerpt via the internal report MCP server."),
        "jenkins_get_build_report_summary": StructuredTool.from_function(jenkins_get_build_report_summary, name="jenkins_get_build_report_summary", description="Read cached Jenkins build summary via the internal Jenkins MCP server."),
        "jenkins_get_build_report_status": StructuredTool.from_function(jenkins_get_build_report_status, name="jenkins_get_build_report_status", description="Read cached Jenkins build status via the internal Jenkins MCP server."),
        "jenkins_get_build_report_findings": StructuredTool.from_function(jenkins_get_build_report_findings, name="jenkins_get_build_report_findings", description="Read cached Jenkins findings via the internal Jenkins MCP server."),
        "jenkins_get_console_excerpt": StructuredTool.from_function(jenkins_get_console_excerpt, name="jenkins_get_console_excerpt", description="Read cached Jenkins console log excerpt via the internal Jenkins MCP server."),
        "git_status": StructuredTool.from_function(git_status, name="git_status", description="Read repository status via the internal Git MCP server."),
        "git_diff": StructuredTool.from_function(git_diff, name="git_diff", description="Read repository diff via the internal Git MCP server."),
        "git_log": StructuredTool.from_function(git_log, name="git_log", description="Read recent git history via the internal Git MCP server."),
        "git_list_changed_files": StructuredTool.from_function(git_list_changed_files, name="git_list_changed_files", description="List changed files via the internal Git MCP server."),
        "code_search_code": StructuredTool.from_function(code_search_code, name="code_search_code", description="Search code via the internal code search MCP server."),
        "code_read_file_range": StructuredTool.from_function(code_read_file_range, name="code_read_file_range", description="Read a file line range via the internal code search MCP server."),
        "code_list_directory": StructuredTool.from_function(code_list_directory, name="code_list_directory", description="List a directory via the internal code search MCP server."),
        "docs_list_docs": StructuredTool.from_function(docs_list_docs, name="docs_list_docs", description="List documentation files via the internal docs MCP server."),
        "docs_search_docs": StructuredTool.from_function(docs_search_docs, name="docs_search_docs", description="Search documentation via the internal docs MCP server."),
        "docs_read_doc": StructuredTool.from_function(docs_read_doc, name="docs_read_doc", description="Read a documentation file via the internal docs MCP server."),
    }
    return tools


def get_langchain_mcp_tool_map() -> Dict[str, BaseTool]:
    global _TOOLS_CACHE
    with _TOOLS_LOCK:
        if _TOOLS_CACHE is None:
            _TOOLS_CACHE = _build_tools()
        return dict(_TOOLS_CACHE)


def get_langchain_mcp_tools() -> List[BaseTool]:
    return list(get_langchain_mcp_tool_map().values())
