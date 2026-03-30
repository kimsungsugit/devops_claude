from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from backend.services.files import list_log_candidates, parse_coverage_xml, tail_text


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


class ReportMCPServer:
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "get_report_summary", "type": "read"},
            {"name": "get_run_status", "type": "read"},
            {"name": "get_findings", "type": "read"},
            {"name": "get_coverage", "type": "read"},
            {"name": "get_log_excerpt", "type": "read"},
            {"name": "list_report_files", "type": "read"},
        ]

    def list_resources(self) -> List[str]:
        return [
            "report://session/{session_id}/summary",
            "report://session/{session_id}/status",
            "report://session/{session_id}/findings",
            "report://session/{session_id}/coverage",
            "report://session/{session_id}/log/{name}",
        ]

    def list_prompts(self) -> List[str]:
        return [
            "triage_build_failure",
            "summarize_findings",
            "review_coverage_gap",
        ]

    def read_bundle(self, report_dir: Path) -> Dict[str, Any]:
        report_dir = Path(report_dir).resolve()
        summary = _read_json(report_dir / "analysis_summary.json", default={})
        findings = _read_json(report_dir / "findings_flat.json", default=[])
        history = _read_json(report_dir / "history.json", default=[])
        status = _read_json(report_dir / "run_status.json", default={})
        jenkins_scan = _read_json(report_dir / "jenkins_scan.json", default={})

        coverage = summary.get("coverage") if isinstance(summary, dict) else None
        if not isinstance(coverage, dict):
            coverage = {}
        if coverage.get("line_rate") is None:
            parsed = parse_coverage_xml([report_dir])
            if parsed:
                coverage["line_rate"] = parsed.get("line_rate")
                coverage["branch_rate"] = parsed.get("branch_rate")
                coverage["enabled"] = True
                if coverage.get("threshold") is None:
                    coverage["threshold"] = getattr(config, "DEFAULT_COVERAGE_THRESHOLD", 0.8)
                if coverage.get("line_rate") is not None and coverage.get("threshold") is not None:
                    coverage["ok"] = float(coverage["line_rate"]) >= float(coverage["threshold"])
                coverage["source"] = parsed.get("path")
                summary["coverage"] = coverage

        return {
            "report_dir": str(report_dir),
            "summary": summary,
            "findings": findings,
            "history": history,
            "status": status,
            "jenkins_scan": jenkins_scan,
        }

    def call_tool(self, tool_name: str, *, report_dir: Path, **kwargs: Any) -> Dict[str, Any]:
        report_dir = Path(report_dir).resolve()
        bundle = self.read_bundle(report_dir)

        if tool_name == "get_report_summary":
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": bundle.get("summary") or {},
                "resource_uri": "report://session/local/summary",
            }
        if tool_name == "get_run_status":
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": bundle.get("status") or {},
                "resource_uri": "report://session/local/status",
            }
        if tool_name == "get_findings":
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": bundle.get("findings") or [],
                "resource_uri": "report://session/local/findings",
            }
        if tool_name == "get_coverage":
            summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
            coverage = summary.get("coverage") if isinstance(summary, dict) else {}
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": coverage or {},
                "resource_uri": "report://session/local/coverage",
            }
        if tool_name == "get_log_excerpt":
            log_name = str(kwargs.get("log_name") or "system").strip().lower()
            max_bytes = int(kwargs.get("max_bytes") or 96 * 1024)
            logs = list_log_candidates(report_dir)
            paths = logs.get(log_name) or []
            text = tail_text(paths[0], max_bytes=max_bytes) if paths else ""
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {
                    "log_name": log_name,
                    "text": text,
                    "path": str(paths[0]) if paths else "",
                },
                "resource_uri": f"report://session/local/log/{log_name}",
            }
        if tool_name == "list_report_files":
            files = []
            try:
                for path in report_dir.rglob("*"):
                    if path.is_file():
                        files.append(str(path))
                    if len(files) >= int(kwargs.get("limit") or 200):
                        break
            except Exception:
                files = []
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": True,
                "output": {"files": files},
                "resource_uri": "report://session/local/files",
            }
        return {
            "tool_name": tool_name,
            "tool_type": "read",
            "ok": False,
            "error_code": "unknown_tool",
            "error_message": f"Unknown report MCP tool: {tool_name}",
            "output": {},
        }

    def read_resource(self, uri: str, *, report_dir: Path) -> Dict[str, Any]:
        if uri.endswith("/summary"):
            return self.call_tool("get_report_summary", report_dir=report_dir)
        if uri.endswith("/status"):
            return self.call_tool("get_run_status", report_dir=report_dir)
        if uri.endswith("/findings"):
            return self.call_tool("get_findings", report_dir=report_dir)
        if uri.endswith("/coverage"):
            return self.call_tool("get_coverage", report_dir=report_dir)
        if "/log/" in uri:
            log_name = uri.rsplit("/log/", 1)[-1]
            return self.call_tool("get_log_excerpt", report_dir=report_dir, log_name=log_name)
        return {
            "ok": False,
            "error_code": "unknown_resource",
            "error_message": f"Unknown report MCP resource: {uri}",
        }

    def get_prompt(self, prompt_name: str) -> str:
        prompts = {
            "triage_build_failure": "Summarize the current build failure, identify the most likely cause, and suggest the next remediation step.",
            "summarize_findings": "Summarize the key findings by severity and explain which ones should be handled first.",
            "review_coverage_gap": "Review current coverage metrics, compare them to the threshold, and explain the most useful next step.",
        }
        return prompts.get(prompt_name, "")


_REPORT_MCP_SERVER = ReportMCPServer()


def get_report_mcp_server() -> ReportMCPServer:
    return _REPORT_MCP_SERVER
