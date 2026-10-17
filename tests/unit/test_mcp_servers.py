"""Unit tests for backend/mcp/ server classes (mock-based)."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

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

    def test_ripgrep_error_returns_none_not_empty(self, tmp_path, monkeypatch):
        """ripgrep 오류(exit 2)를 '매치 없음'(results:[])으로 위장하지 않고 None(에러)로 (B3).

        rg exit 2(잘못된 정규식·IO 오류)의 빈 stdout 은 exit 1(매치 없음)과 동일하다.
        returncode 를 안 보면 안전패턴 검색이 "부재"로 오독된다. 뮤테이션: rc 검사를
        제거하면 {"ok":True,"results":[]} 가 반환돼 실패한다.
        """
        import subprocess as sp

        from backend.mcp import code_search_server
        srv = self._make()
        monkeypatch.setattr(code_search_server.shutil, "which", lambda _n: "rg")
        monkeypatch.setattr(
            code_search_server.subprocess, "run",
            lambda *a, **k: sp.CompletedProcess(a[0] if a else [], 2, "", "regex parse error"),
        )
        out = srv._search_with_ripgrep(
            root=str(tmp_path), rel_path=".", query="[unbalanced", max_results=10, is_regex=True,
        )
        assert out is None, f"ripgrep 오류가 '매치 없음'으로 위장됐다: {out}"

    def test_ripgrep_no_match_returns_ok_empty(self, tmp_path, monkeypatch):
        """대조: exit 1(매치 없음)은 정상 결과(ok:True, results:[]) — 오류와 구분됨."""
        import subprocess as sp

        from backend.mcp import code_search_server
        srv = self._make()
        monkeypatch.setattr(code_search_server.shutil, "which", lambda _n: "rg")
        monkeypatch.setattr(
            code_search_server.subprocess, "run",
            lambda *a, **k: sp.CompletedProcess(a[0] if a else [], 1, "", ""),
        )
        out = srv._search_with_ripgrep(
            root=str(tmp_path), rel_path=".", query="zzz", max_results=10, is_regex=False,
        )
        assert out == {"ok": True, "results": []}


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

    def test_read_bundle_invalidates_on_findings_change(self, tmp_path):
        """캐시 시그니처가 findings_flat.json 변경을 감지해야 한다 (deep-review C1).

        예전엔 시그니처가 analysis_summary/run_status 2개만 봐, findings_flat 이 갱신돼도
        stale hit → reviewer/tester 가 사라진 안전 finding 을 못 봤다. 뮤테이션: 시그니처를
        2개 파일로 되돌리면 [B] 갱신을 놓쳐 실패한다.
        """
        import os
        srv = self._make()
        f = tmp_path / "findings_flat.json"
        f.write_text(json.dumps([{"id": "A"}]), encoding="utf-8")
        b1 = srv.read_bundle(tmp_path)
        assert [x["id"] for x in b1["findings"]] == ["A"]
        # findings 만 갱신(analysis_summary/run_status 는 그대로) + mtime 명시적 전진
        f.write_text(json.dumps([{"id": "B"}]), encoding="utf-8")
        st = f.stat()
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
        b2 = srv.read_bundle(tmp_path)
        assert [x["id"] for x in b2["findings"]] == ["B"], "stale findings 캐시가 갱신을 놓쳤다"

    def test_read_json_corrupt_is_surfaced_not_silent(self, tmp_path, caplog):
        """corrupt JSON 을 '없음'과 동일 취급(silent [])하지 않고 표면화한다 (deep-review B2)."""
        import logging

        from backend.mcp.report_server import _read_json
        f = tmp_path / "findings_flat.json"
        f.write_text("{ this is not valid json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            result = _read_json(f, default=[])
        assert result == []  # 반환 계약은 유지(호출자 안 깨짐)
        assert any("파싱 실패" in r.message for r in caplog.records), \
            "corrupt JSON 이 조용히 삼켜졌다(missing 과 구분 안 됨)"

    def test_get_findings_corrupt_is_not_clean(self, tmp_path):
        """corrupt findings_flat.json 은 agent 에 ok:False/degraded 로 도달해야 한다 (W2).

        로그만으론 부족 — get_findings 가 ok:True,[] 로 내면 reviewer/tester 는 "clean build"
        로 읽는다. 뮤테이션: get_findings 의 `ok: not _corrupt` 를 `ok: True` 로 되돌리면 실패.
        """
        srv = self._make()
        (tmp_path / "findings_flat.json").write_text("{ broken json", encoding="utf-8")
        out = srv.call_tool("get_findings", report_dir=tmp_path)
        assert out["ok"] is False, "corrupt findings 가 clean(ok:True)로 위장됐다"
        assert out.get("degraded") is True
        assert "findings_flat.json" in (out.get("parse_errors") or [])

    def test_get_findings_clean_is_ok_true(self, tmp_path):
        """대조: 정상 findings 는 ok:True, degraded:False — corrupt 와 구분됨."""
        srv = self._make()
        (tmp_path / "findings_flat.json").write_text(json.dumps([{"id": "X"}]), encoding="utf-8")
        out = srv.call_tool("get_findings", report_dir=tmp_path)
        assert out["ok"] is True and out.get("degraded") is False
        assert [f["id"] for f in out["output"]] == ["X"]
