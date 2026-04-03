"""Unit tests for backend/mcp/ server classes (mock-based)."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Stub heavy optional deps before importing MCP servers
for _mod in [
    "langchain_core", "langchain_core.tools",
    "langchain_mcp_adapters", "langchain_mcp_adapters.tools",
    "mcp", "mcp.client", "mcp.client.stdio", "mcp.server", "mcp.server.fastmcp",
]:
    if _mod not in sys.modules:
        _s = types.ModuleType(_mod)
        _s.BaseTool = MagicMock
        _s.StructuredTool = MagicMock
        _s.FastMCP = MagicMock
        sys.modules[_mod] = _s


class TestGitMCPServer:
    def _make(self):
        from backend.mcp.git_server import GitMCPServer
        return GitMCPServer()

    def test_list_tools(self):
        srv = self._make()
        tools = srv.list_tools()
        names = [t["name"] for t in tools]
        assert "git_status" in names
        assert "git_diff" in names

    def test_list_resources(self):
        srv = self._make()
        resources = srv.list_resources()
        assert any("status" in r for r in resources)

    def test_list_prompts(self):
        srv = self._make()
        prompts = srv.list_prompts()
        assert len(prompts) >= 1

    def test_normalize_result_ok(self):
        srv = self._make()
        result = srv._normalize_result("git_status", "read", {"rc": 0, "output": "on branch main"}, "git://repo/status")
        assert result["ok"] is True
        assert result["error_code"] == ""

    def test_normalize_result_not_git(self):
        srv = self._make()
        result = srv._normalize_result("git_status", "read", {"rc": 128, "output": "fatal: not a git repository"}, "git://repo/status")
        assert result["ok"] is False
        assert result["error_code"] == "not_git_repo"

    def test_normalize_result_generic_error(self):
        srv = self._make()
        result = srv._normalize_result("git_diff", "read", {"rc": 1, "output": "some error"}, "git://repo/diff")
        assert result["ok"] is False
        assert result["error_code"] == "git_command_failed"

    def test_call_tool_unknown(self):
        srv = self._make()
        result = srv.call_tool("nonexistent_tool", project_root=".")
        assert result["ok"] is False


class TestDocsMCPServer:
    def _make(self):
        from backend.mcp.docs_server import DocsMCPServer
        return DocsMCPServer()

    def test_list_tools(self):
        srv = self._make()
        tools = srv.list_tools()
        names = [t["name"] for t in tools]
        assert "list_docs" in names
        assert "read_doc" in names

    def test_list_resources(self):
        srv = self._make()
        assert len(srv.list_resources()) >= 1

    def test_query_tokens(self):
        srv = self._make()
        tokens = srv._query_tokens("hello_world-test/path")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens
        assert "path" in tokens

    def test_query_tokens_short_filtered(self):
        srv = self._make()
        tokens = srv._query_tokens("a b cd")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens


class TestCodeSearchMCPServer:
    def _make(self):
        from backend.mcp.code_search_server import CodeSearchMCPServer
        return CodeSearchMCPServer()

    def test_list_tools(self):
        srv = self._make()
        tools = srv.list_tools()
        names = [t["name"] for t in tools]
        assert "search_code" in names
        assert "read_file" in names

    def test_query_tokens(self):
        srv = self._make()
        tokens = srv._query_tokens("main_loop/function")
        assert "main" in tokens
        assert "loop" in tokens
        assert "function" in tokens


class TestReportMCPServer:
    def _make(self):
        from backend.mcp.report_server import ReportMCPServer
        return ReportMCPServer()

    def test_list_tools(self):
        srv = self._make()
        tools = srv.list_tools()
        names = [t["name"] for t in tools]
        assert "get_report_summary" in names
        assert "get_coverage" in names

    def test_list_resources(self):
        srv = self._make()
        resources = srv.list_resources()
        assert len(resources) >= 3

    def test_list_prompts(self):
        srv = self._make()
        prompts = srv.list_prompts()
        assert "triage_build_failure" in prompts

    def test_read_bundle_empty_dir(self, tmp_path):
        srv = self._make()
        bundle = srv.read_bundle(tmp_path)
        assert isinstance(bundle, dict)
        assert "summary" in bundle
