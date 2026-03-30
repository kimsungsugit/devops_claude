from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import re

from backend.services.local_service import list_directory, read_file_text, search_in_files


class CodeSearchMCPServer:
    def _query_tokens(self, query: str) -> List[str]:
        parts = [p.strip() for p in re.split(r"[\s,./:_()\\-]+", str(query or "")) if p.strip()]
        return [p for p in parts if len(p) >= 2]

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "search_code", "type": "read"},
            {"name": "read_file", "type": "read"},
            {"name": "read_file_range", "type": "read"},
            {"name": "list_directory", "type": "read"},
        ]

    def list_resources(self) -> List[str]:
        return [
            "code://search",
            "code://file/{path}",
            "code://directory/{path}",
        ]

    def list_prompts(self) -> List[str]:
        return [
            "explain_code_region",
            "trace_failure_to_source",
        ]

    def call_tool(
        self,
        tool_name: str,
        *,
        project_root: str,
        rel_path: str = ".",
        query: str = "",
        max_results: int = 50,
        start_line: int = 1,
        end_line: int = 120,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> Dict[str, Any]:
        root = str(Path(project_root or ".").resolve())
        if tool_name == "search_code":
            query_text = str(query or "")
            out = search_in_files(root, rel_path, query_text, max_results=max_results)
            if (not out.get("ok")) or (((out.get("results") or []))):
                pass
            else:
                aggregate: List[Dict[str, Any]] = []
                for token in self._query_tokens(query_text):
                    token_out = search_in_files(root, rel_path, token, max_results=max_results)
                    if token_out.get("ok"):
                        aggregate.extend(list((token_out.get("results") or [])))
                    if len(aggregate) >= max_results:
                        break
                dedup: List[Dict[str, Any]] = []
                seen = set()
                for item in aggregate:
                    key = (str(item.get("path") or ""), int(item.get("line") or 0))
                    if key in seen:
                        continue
                    seen.add(key)
                    dedup.append(item)
                    if len(dedup) >= max_results:
                        break
                out = {"ok": True, "results": dedup}
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": bool(out.get("ok")),
                "output": out,
                "error_code": "" if out.get("ok") else str(out.get("error") or "search_failed"),
                "error_message": "" if out.get("ok") else str(out.get("error") or "search_failed"),
                "resource_uri": "code://search",
            }
        if tool_name == "read_file":
            out = read_file_text(root, rel_path, max_bytes=max_bytes)
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": bool(out.get("ok")),
                "output": out,
                "error_code": "" if out.get("ok") else str(out.get("error") or "read_failed"),
                "error_message": "" if out.get("ok") else str(out.get("error") or "read_failed"),
                "resource_uri": f"code://file/{rel_path}",
            }
        if tool_name == "read_file_range":
            out = read_file_text(root, rel_path, max_bytes=max_bytes)
            if not out.get("ok"):
                return {
                    "tool_name": tool_name,
                    "tool_type": "read",
                    "ok": False,
                    "output": out,
                    "error_code": str(out.get("error") or "read_failed"),
                    "error_message": str(out.get("error") or "read_failed"),
                    "resource_uri": f"code://file/{rel_path}",
                }
            text = str(out.get("text") or "")
            lines = text.splitlines()
            start = max(1, int(start_line or 1))
            end = max(start, int(end_line or start))
            excerpt = "\n".join(lines[start - 1 : end])
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {
                    "path": rel_path,
                    "start_line": start,
                    "end_line": end,
                    "text": excerpt,
                },
                "error_code": "",
                "error_message": "",
                "resource_uri": f"code://file/{rel_path}",
            }
        if tool_name == "list_directory":
            out = list_directory(root, rel_path)
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": bool(out.get("ok")),
                "output": out,
                "error_code": "" if out.get("ok") else str(out.get("error") or "list_failed"),
                "error_message": "" if out.get("ok") else str(out.get("error") or "list_failed"),
                "resource_uri": f"code://directory/{rel_path}",
            }
        return {
            "tool_name": tool_name,
            "tool_type": "read",
            "ok": False,
            "output": {},
            "error_code": "unknown_tool",
            "error_message": f"Unknown code search MCP tool: {tool_name}",
            "resource_uri": "",
        }

    def read_resource(self, uri: str, *, project_root: str) -> Dict[str, Any]:
        if uri.startswith("code://file/"):
            rel_path = uri.split("code://file/", 1)[1]
            return self.call_tool("read_file", project_root=project_root, rel_path=rel_path)
        if uri.startswith("code://directory/"):
            rel_path = uri.split("code://directory/", 1)[1]
            return self.call_tool("list_directory", project_root=project_root, rel_path=rel_path)
        if uri == "code://search":
            return {
                "ok": False,
                "error_code": "query_required",
                "error_message": "search resource requires a query",
            }
        return {
            "ok": False,
            "error_code": "unknown_resource",
            "error_message": f"Unknown code search MCP resource: {uri}",
        }

    def get_prompt(self, prompt_name: str) -> str:
        prompts = {
            "explain_code_region": "Explain the relevant code region, identify the important functions, and summarize what it does.",
            "trace_failure_to_source": "Use code search results and file excerpts to trace the likely source location for the reported failure.",
        }
        return prompts.get(prompt_name, "")


_CODE_SEARCH_MCP_SERVER = CodeSearchMCPServer()


def get_code_search_mcp_server() -> CodeSearchMCPServer:
    return _CODE_SEARCH_MCP_SERVER
