# /app/workflow/runner.py
# -*- coding: utf-8 -*-
"""Background runner for UI async pipeline execution."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_status_path: Optional[Path] = None
_log_path: Optional[Path] = None


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _append_log(log_path: Path, msg: str) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _on_signal(signum: int, _frame: Any) -> None:
    sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    if _log_path:
        _append_log(_log_path, f"[runner] Received {sig_name}, shutting down...")
    if _status_path:
        _write_json(
            _status_path,
            {
                "state": "interrupted",
                "signal": sig_name,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "pid": os.getpid(),
            },
        )
    sys.exit(130 if signum == signal.SIGINT else 143)


def main() -> int:
    global _status_path, _log_path

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Async pipeline runner")
    parser.add_argument("--config", required=True, help="Path to run config JSON")
    parser.add_argument("--status", required=True, help="Path to status JSON")
    parser.add_argument("--log", required=True, help="Path to log file")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    _status_path = Path(args.status)
    _log_path = Path(args.log)
    status_path = _status_path
    log_path = _log_path

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        _append_log(log_path, f"[runner] Failed to read config: {e}\n{traceback.format_exc()}")
        _write_json(status_path, {"state": "error", "error": "config_read_failed"})
        return 2

    try:
        from workflow import gui_utils  # type: ignore
    except Exception as e:
        _append_log(log_path, f"[runner] Failed to import gui_utils: {e}\n{traceback.format_exc()}")
        _write_json(status_path, {"state": "error", "error": "import_failed"})
        return 2

    _write_json(
        status_path,
        {"state": "running", "started_at": datetime.now().isoformat(timespec="seconds"), "pid": os.getpid()},
    )

    def _log_cb(msg: str) -> None:
        _append_log(log_path, msg)

    exit_code = 1
    try:
        exit_code = int(gui_utils.run_pipeline(cfg, status_box=None, progress_bar=None, log_callback=_log_cb))
    except Exception as e:
        _append_log(log_path, f"[runner] Pipeline crashed: {e}\n{traceback.format_exc()}")
        exit_code = 2

    _write_json(
        status_path,
        {
            "state": "completed",
            "exit_code": exit_code,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(),
        },
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
