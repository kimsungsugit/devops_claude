# /app/workflow/runner.py
# -*- coding: utf-8 -*-
"""Background runner for GUI async pipeline execution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Async pipeline runner")
    parser.add_argument("--config", required=True, help="Path to run config JSON")
    parser.add_argument("--status", required=True, help="Path to status JSON")
    parser.add_argument("--log", required=True, help="Path to log file")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    status_path = Path(args.status)
    log_path = Path(args.log)

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        _append_log(log_path, f"[runner] Failed to read config: {e}")
        _write_json(status_path, {"state": "error", "error": "config_read_failed"})
        return 2

    # allow importing gui_utils (non-package) from repo root
    repo_root = Path(__file__).resolve().parents[1]
    gui_dir = repo_root / "gui"
    if str(gui_dir) not in sys.path:
        sys.path.insert(0, str(gui_dir))

    try:
        import gui_utils  # type: ignore
    except Exception as e:
        _append_log(log_path, f"[runner] Failed to import gui_utils: {e}")
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
        _append_log(log_path, f"[runner] Pipeline crashed: {e}")
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
