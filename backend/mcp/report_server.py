from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from backend.services.files import list_log_candidates, parse_coverage_xml, tail_text

_logger = logging.getLogger(__name__)

# read_bundle 캐시 무효화 시그니처가 커버해야 하는 입력 파일 전부. 예전엔
# analysis_summary/run_status 2개만 봐, findings_flat/history/jenkins_scan/coverage 가
# 갱신돼도 stale hit 였다(예: Jenkins 재스캔이 jenkins_scan.json 만 갱신 → 시그니처
# 불변 → 옛 findings 반환 → reviewer/tester 가 사라진 안전 finding 을 못 봄).
_BUNDLE_SIG_FILES = (
    "analysis_summary.json", "findings_flat.json", "history.json",
    "run_status.json", "jenkins_scan.json",
    # parse_coverage_xml 이 우선순위대로 보는 두 위치(top-level·서브디렉토리). rglob-중첩
    # 임의 위치는 TTL 이 backstop — 완전 열거는 매 호출 rglob 이라 비용이 커 TTL 로 수용.
    "coverage.xml", "coverage/coverage.xml",
)


def _read_json(path: Path, default: Any, *, errors: Optional[List[str]] = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        # corrupt/절단 파일을 '없음'(default)과 동일 취급하면 findings_flat.json 손상이
        # ok:true + [] "clean build" 로 위장된다(B2). 로그 + errors 목록으로 표면화해
        # read_bundle→get_findings 가 agent(reviewer/tester)에 degraded 를 전한다.
        _logger.warning("리포트 JSON 파싱 실패 %s: %s", getattr(path, "name", path), e)
        if errors is not None:
            errors.append(getattr(path, "name", str(path)))
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None




class ReportMCPServer:
    # 프로세스 싱글톤이 모든 요청 스레드에서 공유 → lock 으로 보호 + LRU 상한(무한 증가 방지).
    # (시그니처 튜플, 삽입 monotonic 시각, 번들) — 시그니처=번들 입력 파일들의 mtime_ns.
    _bundle_cache: "OrderedDict[str, tuple[tuple[int, ...], float, Dict[str, Any]]]" = OrderedDict()
    _cache_lock = threading.Lock()
    _CACHE_TTL = 60  # seconds
    _CACHE_MAX = 64  # LRU 상한(report_dir cardinality 폭증 시 메모리 누수 차단)

    def clear_cache(self, report_dir: str | None = None) -> None:
        with self._cache_lock:
            if report_dir:
                self._bundle_cache.pop(str(Path(report_dir).resolve()), None)
            else:
                self._bundle_cache.clear()

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
        cache_key = str(report_dir)
        try:
            sig = tuple(
                (report_dir / f).stat().st_mtime_ns if (report_dir / f).exists() else 0
                for f in _BUNDLE_SIG_FILES
            ) if report_dir.exists() else ()
        except OSError:
            sig = ()
        # hit 판정: **모든 번들 입력**의 mtime_ns 시그니처 일치 + TTL 상한(비-파일 입력
        # 대비 안전망). 예전엔 2개 파일 mtime 만 봐 findings/jenkins_scan 갱신을 놓쳤고
        # _CACHE_TTL 은 참조조차 안 됐다(dead). mtime_ns 로 같은-초 write 충돌도 회피.
        with self._cache_lock:
            cached = self._bundle_cache.get(cache_key)
            if cached and cached[0] == sig and (time.monotonic() - cached[1]) < self._CACHE_TTL:
                self._bundle_cache.move_to_end(cache_key)
                return dict(cached[2])  # 최상위 얕은복사로 by-reference 캐시 오염 방지
        parse_errors: List[str] = []
        summary = _read_json(report_dir / "analysis_summary.json", default={}, errors=parse_errors)
        findings = _read_json(report_dir / "findings_flat.json", default=[], errors=parse_errors)
        history = _read_json(report_dir / "history.json", default=[], errors=parse_errors)
        status = _read_json(report_dir / "run_status.json", default={}, errors=parse_errors)
        jenkins_scan = _read_json(report_dir / "jenkins_scan.json", default={}, errors=parse_errors)

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

        bundle = {
            "report_dir": str(report_dir),
            "summary": summary,
            "findings": findings,
            "history": history,
            "status": status,
            "jenkins_scan": jenkins_scan,
            # corrupt 로 default 로 떨어진 입력 파일명들 — 소비 tool 이 ok:False/degraded 로 표면화.
            "parse_errors": parse_errors,
        }
        with self._cache_lock:
            self._bundle_cache[cache_key] = (sig, time.monotonic(), bundle)
            self._bundle_cache.move_to_end(cache_key)
            while len(self._bundle_cache) > self._CACHE_MAX:
                self._bundle_cache.popitem(last=False)
        return dict(bundle)

    def call_tool(self, tool_name: str, *, report_dir: str | Path, **kwargs: Any) -> Dict[str, Any]:
        report_dir = Path(report_dir).resolve()
        bundle = self.read_bundle(report_dir)

        if tool_name == "get_report_summary":
            _errs = bundle.get("parse_errors") or []
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                "ok": "analysis_summary.json" not in _errs,
                "output": bundle.get("summary") or {},
                "parse_errors": _errs,
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
            _errs = bundle.get("parse_errors") or []
            _corrupt = "findings_flat.json" in _errs
            return {
                "tool_name": tool_name,
                "tool_type": "read",
                # corrupt findings 를 ok:True 로 내면 "clean build" 위장이다(B2 핵심) —
                # degraded 로 표면화해 reviewer/tester 가 '검사 안 됨'을 알게 한다.
                "ok": not _corrupt,
                "output": bundle.get("findings") or [],
                "degraded": _corrupt,
                "parse_errors": _errs,
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
