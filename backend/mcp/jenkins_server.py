from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.mcp.report_server import get_report_mcp_server
from backend.services.files import tail_text
from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug


def _resolve_cached_build_root(job_url: str, cache_root: str, build_selector: str) -> Optional[Path]:
    base = Path(cache_root).expanduser().resolve()
    job_slug = _job_slug(job_url)
    job_root = (base / "jenkins" / job_slug).resolve()
    if not job_root.exists():
        return None
    selector = str(build_selector or "").strip()
    if selector.isdigit():
        cand = (job_root / f"build_{int(selector)}").resolve()
        return cand if cand.exists() else None
    builds = sorted(job_root.glob("build_*"), reverse=True)
    return builds[0].resolve() if builds else None


class JenkinsMCPServer:
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "get_cached_build_root", "type": "read"},
            {"name": "get_build_report_summary", "type": "read"},
            {"name": "get_build_report_status", "type": "read"},
            {"name": "get_build_report_findings", "type": "read"},
            {"name": "get_console_excerpt", "type": "read"},
            {"name": "list_cached_artifacts", "type": "read"},
        ]

    def list_resources(self) -> List[str]:
        return [
            "jenkins://job/{job_slug}/build/{build_id}/status",
            "jenkins://job/{job_slug}/build/{build_id}/summary",
            "jenkins://job/{job_slug}/build/{build_id}/findings",
            "jenkins://job/{job_slug}/build/{build_id}/console",
            "jenkins://job/{job_slug}/build/{build_id}/artifacts",
        ]

    def list_prompts(self) -> List[str]:
        return [
            "analyze_pipeline_failure",
            "summarize_build_health",
        ]

    def call_tool(
        self,
        tool_name: str,
        *,
        job_url: str,
        cache_root: str,
        build_selector: str = "lastSuccessfulBuild",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        build_root = _resolve_cached_build_root(job_url, cache_root, build_selector)
        if tool_name == "get_cached_build_root":
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": bool(build_root),
                "output": {"build_root": str(build_root) if build_root else ""},
            }
        if not build_root:
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": False,
                "error_code": "missing_cached_build",
                "error_message": "Cached Jenkins build not found",
                "output": {},
            }

        report_dir = _detect_reports_dir(build_root)
        report_mcp = get_report_mcp_server()

        if tool_name == "get_build_report_summary":
            out = report_mcp.call_tool("get_report_summary", report_dir=report_dir)
            out["resource_uri"] = f"jenkins://job/{_job_slug(job_url)}/build/{build_root.name}/summary"
            return out
        if tool_name == "get_build_report_status":
            out = report_mcp.call_tool("get_run_status", report_dir=report_dir)
            out["resource_uri"] = f"jenkins://job/{_job_slug(job_url)}/build/{build_root.name}/status"
            return out
        if tool_name == "get_build_report_findings":
            out = report_mcp.call_tool("get_findings", report_dir=report_dir)
            out["resource_uri"] = f"jenkins://job/{_job_slug(job_url)}/build/{build_root.name}/findings"
            return out
        if tool_name == "get_console_excerpt":
            console_path = build_root / "jenkins_console.log"
            max_bytes = int(kwargs.get("max_bytes") or 240 * 1024)
            text = tail_text(console_path, max_bytes=max_bytes) if console_path.exists() else ""
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {
                    "path": str(console_path) if console_path.exists() else "",
                    "text": text,
                },
                "resource_uri": f"jenkins://job/{_job_slug(job_url)}/build/{build_root.name}/console",
            }
        if tool_name == "list_cached_artifacts":
            files: List[str] = []
            try:
                for path in build_root.rglob("*"):
                    if path.is_file():
                        files.append(str(path.resolve().relative_to(build_root.resolve())).replace("\\", "/"))
                    if len(files) >= int(kwargs.get("limit") or 300):
                        break
            except Exception:
                files = []
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {"files": files},
                "resource_uri": f"jenkins://job/{_job_slug(job_url)}/build/{build_root.name}/artifacts",
            }
        return {
            "tool_name": tool_name,
            "tool_type": "read",
            "ok": False,
            "error_code": "unknown_tool",
            "error_message": f"Unknown Jenkins MCP tool: {tool_name}",
            "output": {},
        }

    def read_resource(
        self,
        uri: str,
        *,
        job_url: str,
        cache_root: str,
        build_selector: str = "lastSuccessfulBuild",
    ) -> Dict[str, Any]:
        if uri.endswith("/summary"):
            return self.call_tool("get_build_report_summary", job_url=job_url, cache_root=cache_root, build_selector=build_selector)
        if uri.endswith("/status"):
            return self.call_tool("get_build_report_status", job_url=job_url, cache_root=cache_root, build_selector=build_selector)
        if uri.endswith("/findings"):
            return self.call_tool("get_build_report_findings", job_url=job_url, cache_root=cache_root, build_selector=build_selector)
        if uri.endswith("/console"):
            return self.call_tool("get_console_excerpt", job_url=job_url, cache_root=cache_root, build_selector=build_selector)
        if uri.endswith("/artifacts"):
            return self.call_tool("list_cached_artifacts", job_url=job_url, cache_root=cache_root, build_selector=build_selector)
        return {
            "ok": False,
            "error_code": "unknown_resource",
            "error_message": f"Unknown Jenkins MCP resource: {uri}",
        }

    def get_prompt(self, prompt_name: str) -> str:
        prompts = {
            "analyze_pipeline_failure": "Summarize the current Jenkins pipeline failure, identify the likely cause, and suggest the next recovery step.",
            "summarize_build_health": "Summarize the build health using cached reports, status, and console context.",
        }
        return prompts.get(prompt_name, "")


_JENKINS_MCP_SERVER = JenkinsMCPServer()


def get_jenkins_mcp_server() -> JenkinsMCPServer:
    return _JENKINS_MCP_SERVER
