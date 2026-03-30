# /app/utils/text.py
"""Text processing helpers used across the project."""

from __future__ import annotations

import re
from typing import List


def trim_text(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars*, keeping head + tail with a marker."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    head = max_chars - 200
    return text[:head] + "\n...[truncated]...\n" + text[-180:]


def strip_c_comments(text: str) -> str:
    """Remove C-style block and line comments from *text*."""
    if not text:
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse consecutive whitespace into single spaces and strip."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences on period/newline boundaries."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def trim_sentence_words(sentence: str, max_words: int) -> str:
    """Trim a sentence to at most *max_words* words."""
    if max_words <= 0:
        return sentence
    words = sentence.split()
    if len(words) <= max_words:
        return sentence
    return " ".join(words[:max_words]).rstrip() + "..."


def title_case_first(text: str) -> str:
    """Upper-case the first character of *text*."""
    if not text:
        return ""
    return text[:1].upper() + text[1:]
