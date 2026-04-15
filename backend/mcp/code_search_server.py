from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

from backend.services.local_service import list_directory, read_file_text, search_in_files


class CodeSearchMCPServer:
    def _query_tokens(self, query: str) -> List[str]:
        parts = [p.strip() for p in re.split(r"[\s,./:_()\\-]+", str(query or "")) if p.strip()]
        return [p for p in parts if len(p) >= 2]

    def _search_with_ripgrep(
        self,
        root: str,
        rel_path: str,
        query: str,
        max_results: int,
        is_regex: bool,
        file_glob: str = "",
        exclude_glob: str = "",
    ) -> Optional[Dict[str, Any]]:
        """ripgrep(rg)으로 코드 검색을 수행한다.

        Args:
            root: 프로젝트 루트 절대 경로.
            rel_path: 검색 대상 상대 경로.
            query: 검색 문자열 또는 정규표현식 패턴.
            max_results: 반환할 최대 결과 수.
            is_regex: True이면 query를 정규표현식으로 처리한다.

        Returns:
            ``{"ok": True, "results": [...]}`` 형식의 딕셔너리.
            ripgrep 실행 실패 시 None을 반환하여 fallback을 유도한다.
        """
        rg_bin = shutil.which("rg")
        if rg_bin is None:
            return None

        search_root = Path(root)
        if rel_path and rel_path != ".":
            search_root = search_root / rel_path

        cmd: List[str] = [
            rg_bin,
            "--json",
            f"--max-count={max_results}",
            "--max-filesize=1M",
        ]
        if not is_regex:
            cmd.append("--fixed-strings")
        if file_glob:
            cmd += ["--glob", file_glob]
        if exclude_glob:
            cmd += ["--glob", f"!{exclude_glob}"]
        cmd += [query, str(search_root)]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

        root_path = Path(root)
        results: List[Dict[str, Any]] = []

        for raw_line in proc.stdout.splitlines():
            if len(results) >= max_results:
                break
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "match":
                continue

            data = obj.get("data", {})
            file_path_str: str = data.get("path", {}).get("text", "")
            line_number: int = data.get("line_number", 0)
            lines_text: str = data.get("lines", {}).get("text", "").rstrip("\n")

            if not file_path_str:
                continue

            try:
                rel = str(Path(file_path_str).relative_to(root_path))
            except ValueError:
                rel = file_path_str

            results.append({"path": rel, "line": line_number, "text": lines_text.strip()})

        return {"ok": True, "results": results}

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
        is_regex: bool = False,
        file_glob: str = "",
        exclude_glob: str = "",
        start_line: int = 1,
        end_line: int = 120,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> Dict[str, Any]:
        root = str(Path(project_root or ".").resolve())
        if tool_name == "search_code":
            query_text = str(query or "")

            # ripgrep 우선 시도; 설치되지 않은 환경에서는 None 반환
            rg_out = self._search_with_ripgrep(root, rel_path, query_text, max_results, is_regex, file_glob, exclude_glob)
            if rg_out is not None:
                # ripgrep 성공: 결과가 없어도 정상 응답으로 간주
                out: Dict[str, Any] = rg_out
            else:
                # fallback: 기존 순차 파일 스캔 (is_regex 미지원)
                out = search_in_files(root, rel_path, query_text, max_results=max_results)
                if (not out.get("ok")) or (out.get("results") or []):
                    pass
                else:
                    aggregate: List[Dict[str, Any]] = []
                    for token in self._query_tokens(query_text):
                        token_out = search_in_files(root, rel_path, token, max_results=max_results)
                        if token_out.get("ok"):
                            aggregate.extend(list(token_out.get("results") or []))
                        if len(aggregate) >= max_results:
                            break
                    dedup: List[Dict[str, Any]] = []
                    seen: set = set()
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
