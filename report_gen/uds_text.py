"""report_gen.uds_text - Auto-split from report_generator.py"""
# Re-import common dependencies
import re
import os
import json
import csv
import logging
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from report.constants import UDS_RULES

_logger = logging.getLogger("report_generator")

def _title_case_line(text: str) -> str:
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def _trim_sentence_words(sentence: str, max_words: int) -> str:
    if max_words <= 0:
        return sentence
    words = sentence.split()
    if len(words) <= max_words:
        return sentence
    return " ".join(words[:max_words]).rstrip() + "..."


def _apply_sentence_rules(
    text: str,
    max_sentences: int,
    max_words: int,
    max_chars: int,
    ensure_period: bool,
) -> str:
    base = (text or "").strip()
    if not base:
        return ""
    sentences = _split_sentences(base) if max_sentences else [base]
    if max_sentences:
        sentences = sentences[: max(1, max_sentences)]
    if max_words:
        sentences = [_trim_sentence_words(s, max_words) for s in sentences]
    merged = " ".join(s for s in sentences if s).strip()
    if max_chars and len(merged) > max_chars:
        merged = merged[:max_chars].rstrip()
        if not merged.endswith(("...", ".", "!", "?")):
            merged = merged.rstrip(".,!?") + "..."
    if ensure_period and merged and not merged.endswith((".", "!", "?")):
        merged += "."
    return merged


def _apply_uds_rules(text: str, section_key: str = "") -> str:
    text = (text or "").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    fmt = UDS_RULES.get("formatting", {})
    section = UDS_RULES.get("sections", {}).get(section_key or "", {})
    max_bullets = int(section.get("max_bullets", fmt.get("max_bullets_default", 8)))
    max_sentences = int(section.get("max_sentences", fmt.get("max_sentences", 2)))
    max_words = int(section.get("max_words_per_sentence", fmt.get("max_words_per_sentence", 24)))
    max_chars = int(section.get("max_chars", fmt.get("max_chars", 180)))
    max_line_chars = int(section.get("max_line_chars", fmt.get("max_line_chars", 240)))
    ensure_period = bool(section.get("ensure_period", fmt.get("ensure_period", True)))
    title_case = bool(section.get("title_case", fmt.get("title_case", True)))
    bullet = str(fmt.get("bullet_prefix", "- "))

    cleaned: List[str] = []
    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        had_bullet = raw.startswith(("-", "*"))
        if had_bullet:
            raw = raw[1:].lstrip()
        raw = _apply_sentence_rules(raw, max_sentences, max_words, max_chars, ensure_period)
        if title_case:
            raw = _title_case_line(raw)
        if max_line_chars and len(raw) > max_line_chars:
            raw = raw[: max(1, max_line_chars - 3)].rstrip() + "..."
        if had_bullet:
            cleaned.append(f"{bullet}{raw}")
        else:
            cleaned.append(raw)

    cleaned = cleaned[: max(1, max_bullets)]
    cleaned = [ln if ln.startswith(("-", "*")) else f"{bullet}{ln}" for ln in cleaned]
    return "\n".join(cleaned)


def _ai_section_text(ai_sections: Any, key: str) -> str:
    if not isinstance(ai_sections, dict):
        return ""
    val = ai_sections.get(key)
    if isinstance(val, dict):
        return str(val.get("text") or "").strip()
    if isinstance(val, str):
        return val.strip()
    return ""


def _ai_evidence_lines(ai_sections: Any) -> List[str]:
    if not isinstance(ai_sections, dict):
        return []
    lines: List[str] = []

    def _summarize(text: str, limit: int = 120) -> str:
        if not text:
            return ""
        cleaned = " ".join(str(text).split())
        return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "..."

    def _format_item(item: Any) -> str:
        if isinstance(item, dict):
            source_type = str(item.get("source_type") or item.get("tag") or item.get("source") or "").strip().lower()
            source_file = str(item.get("source_file") or "").strip()
            source = str(item.get("source") or "").strip()
            content = str(item.get("excerpt") or item.get("content") or item.get("text") or "").strip()
            base = os.path.basename(source_file) if source_file else ""
            if source_type == "rag" or (source_file and "rag" in source_type):
                label = base or source_file or "rag"
                summary = _summarize(content)
                return f"rag: {label}{' - ' + summary if summary else ''}"
            if source:
                summary = _summarize(content)
                return f"{source}: {summary}" if summary else source
            if source_type:
                summary = _summarize(content)
                label = source_type
                if base:
                    label = f"{source_type}:{base}"
                return f"{label}{' - ' + summary if summary else ''}"
        return str(item).strip()

    for key in ["overview", "requirements", "interfaces", "uds_frames", "notes"]:
        val = ai_sections.get(key)
        if not isinstance(val, dict):
            continue
        evidence = val.get("evidence") or []
        if isinstance(evidence, list) and evidence:
            items = [_format_item(x) for x in evidence]
            items = [x for x in items if x]
            if items:
                lines.append(f"{key}: " + ", ".join(items))
    return lines


def _ai_quality_warnings(ai_sections: Any) -> List[str]:
    if not isinstance(ai_sections, dict):
        return []
    warnings = ai_sections.get("quality_warnings")
    if isinstance(warnings, list):
        return [str(w).strip() for w in warnings if str(w).strip()]
    return []


def _merge_section_text(base: str, ai_sections: Any, key: str, *, append_base: bool = False) -> str:
    ai_text = _ai_section_text(ai_sections, key)
    if ai_text:
        if append_base and base:
            return "\n".join([ai_text, base]).strip()
        return ai_text
    return base


def _merge_logic_ai_items(logic_items: List[Dict[str, Any]], ai_sections: Any) -> List[Dict[str, Any]]:
    if not isinstance(logic_items, list) or not logic_items:
        return logic_items
    ai_logic = None
    if isinstance(ai_sections, dict):
        ai_logic = ai_sections.get("logic_diagrams")
    if not isinstance(ai_logic, list) or not ai_logic:
        return logic_items
    lookup = {}
    for item in ai_logic:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title:
            lookup[title] = item
    merged: List[Dict[str, Any]] = []
    for item in logic_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        ai_item = lookup.get(title) if title else None
        if isinstance(ai_item, dict) and ai_item.get("description"):
            merged.append({**item, "description": ai_item.get("description")})
        else:
            merged.append(item)
    return merged


def _ai_document_text(ai_sections: Any) -> str:
    if not isinstance(ai_sections, dict):
        return ""
    return str(ai_sections.get("document") or "").strip()


def _uds_lines_to_html(lines: str) -> str:
    safe = escape(lines or "")
    parts = [ln.strip() for ln in safe.splitlines() if ln.strip()]
    items = []
    for ln in parts:
        item = ln.lstrip("-* ").strip()
        items.append(f"<li>{item}</li>")
    if not items:
        return "<p>N/A</p>"
    return "<ul>" + "".join(items) + "</ul>"


def _uds_logic_html(logic_items: List[Dict[str, Any]]) -> str:
    if not logic_items:
        return "<p>N/A</p>"
    parts = []
    for item in logic_items:
        title = escape(str(item.get("title") or "Logic Diagram"))
        src = escape(str(item.get("url") or ""))
        desc = escape(str(item.get("description") or ""))
        if src:
            block = (
                f"<div class=\"logic-item\">"
                f"<div class=\"logic-title\">{title}</div>"
                f"<img src=\"{src}\" alt=\"{title}\" style=\"max-width:100%;height:auto;\" />"
            )
            if desc:
                block += f"<div class=\"logic-desc\">{desc}</div>"
            block += "</div>"
            parts.append(block)
        else:
            detail = desc or "N/A"
            block = (
                f"<div class=\"logic-item\">"
                f"<div class=\"logic-title\">{title}</div>"
                f"<div class=\"logic-desc\">{detail}</div>"
                f"</div>"
            )
            parts.append(block)
    return "".join(parts) if parts else "<p>N/A</p>"


