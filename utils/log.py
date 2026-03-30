# /app/utils/log.py
"""Centralized logging configuration for the DevOps toolkit."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_CONFIGURED = False

_DEFAULT_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
    fmt: str = _DEFAULT_FMT,
    date_fmt: str = _DEFAULT_DATE_FMT,
) -> None:
    """Configure root logger with console (and optional file) handler.

    Safe to call multiple times; only the first call takes effect.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger. Calls ``setup_logging`` on first use."""
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
