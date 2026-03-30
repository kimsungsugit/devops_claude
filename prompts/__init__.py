# /app/prompts/__init__.py
"""Prompt loader for externalized LLM prompts."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_prompt(name: str, **kwargs: str) -> str:
    """Load a prompt template from the prompts/ directory.

    Supports ``{key}`` placeholder substitution via **kwargs.
    Falls back to an empty string on missing files.
    """
    path = _PROMPT_DIR / name
    if not path.suffix:
        path = path.with_suffix(".txt")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Prompt file not found: %s", path)
        return ""
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text.strip()
