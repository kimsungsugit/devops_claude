from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from backend.services.local_service import git_diff, git_log, git_status


class GitMCPServer:
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "git_status", "type": "read"},
            {"name": "git_diff", "type": "read"},
            {"name": "git_log", "type": "read"},
            {"name": "list_changed_files", "type": "read"},
        ]

    def list_resources(self) -> List[str]:
        return [
            "git://repo/status",
            "git://repo/diff",
            "git://repo/log",
            "git://repo/changed-files",
        ]

    def list_prompts(self) -> List[str]:
        return [
            "summarize_change_risk",
            "explain_diff",
        ]

    def _normalize_result(self, tool_name: str, tool_type: str, result: Dict[str, Any], resource_uri: str) -> Dict[str, Any]:
        rc = int(result.get("rc", 1))
        output = str(result.get("output") or "")
        ok = rc == 0
        error_code = ""
        error_message = ""
        if not ok:
            lower = output.lower()
            if "not a git repository" in lower:
                error_code = "not_git_repo"
            else:
                error_code = "git_command_failed"
            error_message = output[:500]
        return {
            "tool_name": tool_name,
            "tool_type": tool_type,
            "ok": ok,
            "output": {"text": output},
            "error_code": error_code,
            "error_message": error_message,
            "resource_uri": resource_uri,
        }

    def call_tool(self, tool_name: str, *, project_root: str, workdir_rel: str = ".", path: str = "", max_count: int = 30) -> Dict[str, Any]:
        root = str(Path(project_root or ".").resolve())
        if tool_name == "git_status":
            return self._normalize_result(tool_name, "read", git_status(root, workdir_rel), "git://repo/status")
        if tool_name == "git_diff":
            return self._normalize_result(tool_name, "read", git_diff(root, workdir_rel, False, path), "git://repo/diff")
        if tool_name == "git_log":
            return self._normalize_result(tool_name, "read", git_log(root, workdir_rel, max_count=max_count), "git://repo/log")
        if tool_name == "list_changed_files":
            status = git_status(root, workdir_rel)
            normalized = self._normalize_result(tool_name, "read", status, "git://repo/changed-files")
            if normalized.get("ok"):
                text = str(((normalized.get("output") or {}).get("text")) or "")
                files = []
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("##"):
                        continue
                    if len(line) > 3:
                        files.append(line[3:].strip())
                normalized["output"] = {"files": files, "text": text}
            return normalized
        return {
            "tool_name": tool_name,
            "tool_type": "read",
            "ok": False,
            "output": {},
            "error_code": "unknown_tool",
            "error_message": f"Unknown Git MCP tool: {tool_name}",
            "resource_uri": "",
        }

    def read_resource(self, uri: str, *, project_root: str, workdir_rel: str = ".") -> Dict[str, Any]:
        if uri.endswith("/status"):
            return self.call_tool("git_status", project_root=project_root, workdir_rel=workdir_rel)
        if uri.endswith("/diff"):
            return self.call_tool("git_diff", project_root=project_root, workdir_rel=workdir_rel)
        if uri.endswith("/log"):
            return self.call_tool("git_log", project_root=project_root, workdir_rel=workdir_rel)
        if uri.endswith("/changed-files"):
            return self.call_tool("list_changed_files", project_root=project_root, workdir_rel=workdir_rel)
        return {
            "ok": False,
            "error_code": "unknown_resource",
            "error_message": f"Unknown Git MCP resource: {uri}",
        }

    def get_prompt(self, prompt_name: str) -> str:
        prompts = {
            "summarize_change_risk": "Summarize the current repository changes, identify risk areas, and explain what should be reviewed first.",
            "explain_diff": "Explain the current diff in plain language and identify the likely impact.",
        }
        return prompts.get(prompt_name, "")


_GIT_MCP_SERVER = GitMCPServer()


def get_git_mcp_server() -> GitMCPServer:
    return _GIT_MCP_SERVER
