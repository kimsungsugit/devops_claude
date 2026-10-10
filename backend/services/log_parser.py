"""Structured log file parser.

Parses Jenkins console logs and VectorCAST command logs into structured data:
- Pipeline stages with duration and status
- Error/warning extraction
- Summary statistics

Supports:
- Jenkins Pipeline console log (jenkins_console.log)
- VectorCAST command log (command.log, remotelaunch.log)
- Generic text logs (*.log, *.txt)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("devops_api.log_parser")


@dataclass
class LogEntry:
    """Single parsed log entry."""
    line_no: int = 0
    timestamp: Optional[str] = None
    level: str = "INFO"  # ERROR, WARNING, INFO, DEBUG
    message: str = ""
    stage: Optional[str] = None
    source: Optional[str] = None


@dataclass
class PipelineStage:
    """Jenkins pipeline stage."""
    name: str = ""
    status: str = "unknown"  # success, failure, skipped
    start_line: int = 0
    end_line: int = 0
    line_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class LogSummary:
    """Parsed log summary."""
    total_lines: int = 0
    error_count: int = 0
    warning_count: int = 0
    stages: List[PipelineStage] = field(default_factory=list)
    errors: List[LogEntry] = field(default_factory=list)
    warnings: List[LogEntry] = field(default_factory=list)
    key_events: List[LogEntry] = field(default_factory=list)


# ── Patterns ──
_JENKINS_STAGE_START = re.compile(r"\[Pipeline\] \{ \((.+?)\)")
_JENKINS_STAGE_END = re.compile(r"\[Pipeline\] // stage")
_TIMESTAMP_PATTERNS = [
    re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d+)\s+(.*)"),           # HH:MM:SS.microseconds
    re.compile(r"^\[(\d{4}-\d{2}-\d{2}T[\d:]+)\]\s+(.*)"),      # [ISO timestamp]
    re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*)"),  # YYYY-MM-DD HH:MM:SS
]
_ERROR_PATTERNS = re.compile(
    r"(?i)\b(error|fatal|exception|fail(?:ed|ure)?|unable|cannot|crash|abort|denied|rejected)\b"
)
_WARNING_PATTERNS = re.compile(
    r"(?i)\b(warn(?:ing)?|caution|deprecated|timeout|retry|skip(?:ped)?)\b"
)
_KEY_EVENT_PATTERNS = re.compile(
    r"(?i)((?:build|test|compile|link|deploy|checkout|svn|git|coverage|pass|result|complete|finish|start|begin)\b)"
)


def parse_jenkins_console_log(filepath: Path) -> LogSummary:
    """Parse Jenkins Pipeline console log into structured data."""
    if not filepath.exists():
        return LogSummary()

    lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = LogSummary(total_lines=len(lines))

    current_stage: Optional[PipelineStage] = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Stage detection
        stage_start = _JENKINS_STAGE_START.search(stripped)
        if stage_start:
            current_stage = PipelineStage(
                name=stage_start.group(1),
                start_line=i + 1,
                status="running",
            )
            summary.stages.append(current_stage)
            continue

        if _JENKINS_STAGE_END.search(stripped):
            if current_stage:
                current_stage.end_line = i + 1
                current_stage.line_count = current_stage.end_line - current_stage.start_line
                if current_stage.errors:
                    current_stage.status = "failure"
                else:
                    current_stage.status = "success"
            current_stage = None
            continue

        # Error detection
        if _ERROR_PATTERNS.search(stripped):
            entry = LogEntry(line_no=i + 1, level="ERROR", message=stripped[:200],
                             stage=current_stage.name if current_stage else None)
            summary.errors.append(entry)
            summary.error_count += 1
            if current_stage:
                current_stage.errors.append(stripped[:200])

        # Warning detection
        elif _WARNING_PATTERNS.search(stripped):
            entry = LogEntry(line_no=i + 1, level="WARNING", message=stripped[:200],
                             stage=current_stage.name if current_stage else None)
            summary.warnings.append(entry)
            summary.warning_count += 1
            if current_stage:
                current_stage.warnings.append(stripped[:200])

        # Key events
        elif _KEY_EVENT_PATTERNS.search(stripped):
            entry = LogEntry(line_no=i + 1, level="INFO", message=stripped[:200],
                             stage=current_stage.name if current_stage else None)
            summary.key_events.append(entry)

    return summary


def parse_vcast_command_log(filepath: Path) -> LogSummary:
    """Parse VectorCAST command/remote launch log."""
    if not filepath.exists():
        return LogSummary()

    lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = LogSummary(total_lines=len(lines))

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Extract timestamp
        timestamp = None
        message = stripped
        for pat in _TIMESTAMP_PATTERNS:
            m = pat.match(stripped)
            if m:
                timestamp = m.group(1)
                message = m.group(2)
                break

        # Classify
        if _ERROR_PATTERNS.search(message):
            entry = LogEntry(line_no=i + 1, timestamp=timestamp, level="ERROR", message=message[:200])
            summary.errors.append(entry)
            summary.error_count += 1
        elif _WARNING_PATTERNS.search(message):
            entry = LogEntry(line_no=i + 1, timestamp=timestamp, level="WARNING", message=message[:200])
            summary.warnings.append(entry)
            summary.warning_count += 1
        elif _KEY_EVENT_PATTERNS.search(message):
            entry = LogEntry(line_no=i + 1, timestamp=timestamp, level="INFO", message=message[:200])
            summary.key_events.append(entry)

    return summary


def parse_log_file(filepath: Path) -> Dict[str, Any]:
    """Auto-detect log type and parse.

    Returns structured summary dict suitable for API response.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return {"ok": False, "error": f"File not found: {filepath}"}

    name = filepath.name.lower()

    if "jenkins_console" in name:
        summary = parse_jenkins_console_log(filepath)
    elif "command" in name or "remotelaunch" in name or "vcast" in name:
        summary = parse_vcast_command_log(filepath)
    else:
        # Generic log
        summary = parse_vcast_command_log(filepath)  # Same parser works for generic

    return {
        "ok": True,
        "filename": filepath.name,
        "total_lines": summary.total_lines,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "stages": [
            {
                "name": s.name,
                "status": s.status,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "line_count": s.line_count,
                "error_count": len(s.errors),
                "warning_count": len(s.warnings),
            }
            for s in summary.stages
        ],
        "errors": [
            {"line": e.line_no, "message": e.message, "stage": e.stage}
            for e in summary.errors[:50]
        ],
        "warnings": [
            {"line": w.line_no, "message": w.message, "stage": w.stage}
            for w in summary.warnings[:30]
        ],
        "key_events": [
            {"line": e.line_no, "message": e.message, "stage": e.stage}
            for e in summary.key_events[:30]
        ],
    }
