from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import re

from backend.services.files import read_text_limited


class DocsMCPServer:
    def _query_tokens(self, query: str) -> List[str]:
        parts = [p.strip().lower() for p in re.split(r"[\s,./:_-]+", str(query or "")) if p.strip()]
        return [p for p in parts if len(p) >= 2]

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "list_docs", "type": "read"},
            {"name": "search_docs", "type": "read"},
            {"name": "read_doc", "type": "read"},
        ]

    def list_resources(self) -> List[str]:
        return [
            "docs://index",
            "docs://file/{path}",
        ]

    def list_prompts(self) -> List[str]:
        return [
            "summarize_spec_delta",
            "extract_requirements",
        ]

    def _docs_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "docs"

    def _iter_docs(self) -> List[Path]:
        root = self._docs_root()
        allowed = {".md", ".txt", ".json"}
        files: List[Path] = []
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in allowed:
                files.append(path)
        return sorted(files, key=lambda p: p.name.lower())

    def call_tool(
        self,
        tool_name: str,
        *,
        query: str = "",
        rel_path: str = "",
        max_results: int = 20,
        max_bytes: int = 64 * 1024,
    ) -> Dict[str, Any]:
        root = self._docs_root()
        if tool_name == "list_docs":
            files = [str(p.relative_to(root)).replace("\\", "/") for p in self._iter_docs()]
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {"files": files},
                "error_code": "",
                "error_message": "",
                "resource_uri": "docs://index",
            }
        if tool_name == "search_docs":
            if not str(query).strip():
                return {
                    "tool_name": tool_name,
                    "tool_type": "read",
                    "ok": False,
                    "output": {},
                    "error_code": "query_required",
                    "error_message": "query required",
                    "resource_uri": "docs://index",
                }
            hits: List[Dict[str, Any]] = []
            q = str(query)
            tokens = self._query_tokens(q)
            for path in self._iter_docs():
                text, _ = read_text_limited(path, max_bytes=max_bytes)
                if not text:
                    continue
                for idx, line in enumerate(text.splitlines(), start=1):
                    lower = line.lower()
                    matched = q.lower() in lower
                    if not matched and tokens:
                        matched = any(tok in lower for tok in tokens)
                    if matched:
                        hits.append(
                            {
                                "path": str(path.relative_to(root)).replace("\\", "/"),
                                "line": idx,
                                "text": line.strip(),
                            }
                        )
                        if len(hits) >= int(max_results):
                            break
                if len(hits) >= int(max_results):
                    break
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {"results": hits},
                "error_code": "",
                "error_message": "",
                "resource_uri": "docs://index",
            }
        if tool_name == "read_doc":
            target = (root / rel_path).resolve()
            if not target.exists() or target.parent != root:
                return {
                    "tool_name": tool_name,
                    "tool_type": "read",
                    "ok": False,
                    "output": {},
                    "error_code": "doc_not_found",
                    "error_message": "document not found",
                    "resource_uri": f"docs://file/{rel_path}",
                }
            text, truncated = read_text_limited(target, max_bytes=max_bytes)
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {
                    "path": str(target.relative_to(root)).replace("\\", "/"),
                    "text": text,
                    "truncated": truncated,
                },
                "error_code": "",
                "error_message": "",
                "resource_uri": f"docs://file/{str(target.relative_to(root)).replace('\\', '/')}",
            }
        return {
            "tool_name": tool_name,
            "tool_type": "read",
            "ok": False,
            "output": {},
            "error_code": "unknown_tool",
            "error_message": f"Unknown docs MCP tool: {tool_name}",
            "resource_uri": "",
        }

    def read_resource(self, uri: str) -> Dict[str, Any]:
        if uri == "docs://index":
            return self.call_tool("list_docs")
        if uri.startswith("docs://file/"):
            rel_path = uri.split("docs://file/", 1)[1]
            return self.call_tool("read_doc", rel_path=rel_path)
        return {
            "ok": False,
            "error_code": "unknown_resource",
            "error_message": f"Unknown docs MCP resource: {uri}",
        }

    def get_prompt(self, prompt_name: str) -> str:
        prompts = {
            "summarize_spec_delta": "Summarize the relevant specification or documentation delta and explain the practical impact.",
            "extract_requirements": "Extract the key requirements or constraints from the relevant documentation and summarize them clearly.",
        }
        return prompts.get(prompt_name, "")


_DOCS_MCP_SERVER = DocsMCPServer()


def get_docs_mcp_server() -> DocsMCPServer:
    return _DOCS_MCP_SERVER
