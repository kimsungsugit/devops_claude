from __future__ import annotations

import json
import re
import concurrent.futures
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workflow.ai import agent_call, load_oai_config, load_oai_configs
import config
from utils.log import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    p = _PROMPTS_DIR / f"{name}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return f"You are a {name}. Return JSON only."


def _trim_text(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    head = max_chars - 200
    return text[:head] + "\n...[truncated]...\n" + text[-180:]


def _extract_style_excerpt(text: str, max_chars: int = 12000) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    picked: List[str] = []

    # 1) Title/Revision/Front matter (first non-empty 120 lines)
    front = []
    for ln in lines:
        if ln.strip() or front:
            front.append(ln)
        if len(front) >= 120:
            break
    picked.extend(front)

    # 2) Contents section
    try:
        idx = next(i for i, ln in enumerate(lines) if "Contents" in ln)
        picked.append("")
        picked.append("[Contents]")
        picked.extend(lines[idx : idx + 220])
    except StopIteration:
        pass

    # 3) Sample SwCom / function detail blocks
    fn_count = 0
    for i, ln in enumerate(lines):
        if "SwCom_" in ln or "Software Unit Design" in ln:
            picked.append("")
            picked.append("[Sample]")
            picked.extend(lines[i : i + 120])
            if len(picked) > 800:
                break
    for i, ln in enumerate(lines):
        if re.search(r"^Function\s+Name|^함수\s*명", ln.strip()):
            fn_count += 1
            if fn_count <= 2:
                picked.append("")
                picked.append("[FunctionDetail]")
                picked.extend(lines[i : i + 60])
            if fn_count >= 2:
                break

    # 4) Diagram-related hints
    for i, ln in enumerate(lines):
        if "Diagram" in ln or "Flow chart" in ln or "Logic" in ln:
            picked.append("")
            picked.append("[Diagram]")
            picked.extend(lines[i : i + 80])
            if len(picked) > 1000:
                break

    return _trim_text("\n".join(picked).strip(), max_chars=max_chars)


def _normalize_evidence_item(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, dict):
        source_type = str(item.get("source_type") or item.get("tag") or item.get("source") or "").strip()
        source_file = str(item.get("source_file") or "").strip()
        excerpt = str(item.get("excerpt") or item.get("content") or item.get("text") or "").strip()
        score = item.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        if not source_type and not source_file and not excerpt:
            return None
        return {
            "source_type": source_type or "unknown",
            "source_file": source_file,
            "excerpt": excerpt,
            "score": score,
        }
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {"source_type": "note", "source_file": "", "excerpt": text, "score": None}
    return None


def _normalize_evidence_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        norm = _normalize_evidence_item(item)
        if norm:
            out.append(norm)
    return out


def _normalize_section(section: Any) -> Dict[str, Any]:
    if isinstance(section, dict):
        normalized = dict(section)
        normalized["text"] = str(normalized.get("text") or "").strip()
        evidence = _normalize_evidence_list(normalized.get("evidence"))
        if normalized["text"] and normalized["text"].upper() != "N/A" and not evidence:
            # Keep explicit source tagging even when model omitted evidence.
            evidence = [{"source_type": "inference", "source_file": "", "excerpt": "", "score": None}]
        normalized["evidence"] = evidence
        return normalized
    if isinstance(section, str):
        text = str(section or "").strip()
        ev = []
        if text and text.upper() != "N/A":
            ev = [{"source_type": "inference", "source_file": "", "excerpt": "", "score": None}]
        return {"text": text, "evidence": ev}
    return {"text": "", "evidence": []}


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    raw = text.strip()

    def _try_parse(s: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None

    result = _try_parse(raw)
    if result:
        return result

    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
    if cleaned != raw:
        result = _try_parse(cleaned)
        if result:
            return result

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidate = cleaned[start : end + 1]
        result = _try_parse(candidate)
        if result:
            return result

        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        result = _try_parse(fixed)
        if result:
            return result

        fixed2 = re.sub(r'(?<=\w)"(?=\w)', r'\\"', fixed)
        result = _try_parse(fixed2)
        if result:
            return result

    if start != -1 and end <= start:
        partial = cleaned[start:]
        open_b = partial.count("{") - partial.count("}")
        partial += "}" * max(open_b, 0)
        open_sq = partial.count("[") - partial.count("]")
        partial += "]" * max(open_sq, 0)
        fixed = re.sub(r",\s*([}\]])", r"\1", partial)
        result = _try_parse(fixed)
        if result:
            return result

    if start != -1:
        truncated = cleaned[start:]
        last_good_end = -1
        for m in re.finditer(r'"(?:overview|requirements|interfaces|uds_frames|notes)"\s*:', truncated):
            last_good_end = m.start()
        if last_good_end > 0:
            chunk = truncated[:last_good_end].rstrip().rstrip(",")
            open_b = chunk.count("{") - chunk.count("}")
            chunk += "}" * max(open_b, 0)
            open_sq = chunk.count("[") - chunk.count("]")
            chunk += "]" * max(open_sq, 0)
            result = _try_parse(chunk)
            if result:
                return result

    kv_pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', raw)
    if kv_pairs:
        return {k: v for k, v in kv_pairs}

    return None


def _now_ts() -> str:
    try:
        from datetime import datetime

        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    except (OSError, ValueError):
        return "unknown"


def _write_diag(payload: Dict[str, Any]) -> None:
    try:
        repo_root = Path(__file__).resolve().parents[1]
        out_dir = repo_root / "backend" / "reports" / "uds_ai_diagnostics"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = payload.get("timestamp") or "unknown"
        name = f"uds_ai_diag_{ts}.json"
        (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, TypeError) as exc:
        logger.debug("_write_diag failed: %s", exc)

def _validate_sections(payload: Dict[str, Any], detailed: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        logger.warning("validate_sections: payload is not dict")
        return None
    if not payload:
        logger.warning("validate_sections: payload is empty")
        return None
    keys = ["overview", "requirements", "interfaces", "uds_frames", "notes"]
    missing = [k for k in keys if k not in payload]
    present_count = len(keys) - len(missing)
    if missing:
        logger.warning("validate_sections: missing keys: %s (present: %s)", missing, list(payload.keys())[:10])
        if present_count >= 2:
            for mk in missing:
                payload[mk] = {"text": "N/A", "evidence": []}
            logger.info("validate_sections: auto-filled %d missing keys: %s", len(missing), missing)
        else:
            return None
    logic = payload.get("logic_diagrams")
    if logic is not None and not isinstance(logic, list):
        payload["logic_diagrams"] = []
    for key in keys:
        val = payload.get(key)
        if isinstance(val, str):
            payload[key] = {"text": val, "evidence": []}
        elif isinstance(val, dict):
            evidence = val.get("evidence")
            if evidence is not None and not isinstance(evidence, list):
                val["evidence"] = []
    if isinstance(logic, list):
        cleaned_logic = []
        for item in logic:
            if not isinstance(item, dict):
                continue
            if "title" not in item and "description" not in item:
                continue
            if "title" not in item:
                item["title"] = ""
            if "description" not in item:
                item["description"] = ""
            evidence = item.get("evidence")
            if evidence is not None and not isinstance(evidence, list):
                item["evidence"] = []
            cleaned_logic.append(item)
        payload["logic_diagrams"] = cleaned_logic
    if detailed and "document" not in payload:
        payload["document"] = ""
        logger.info("validate_sections: auto-filled missing 'document' key")
    return payload


def _parse_decision(text: Optional[str]) -> Tuple[str, str]:
    if not text:
        return "retry", "empty"
    raw = text.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            decision = str(data.get("decision") or "").strip().lower()
            reason = str(data.get("reason") or "").strip()
            if decision in ("accept", "retry", "reject"):
                return decision, reason or decision
    except (json.JSONDecodeError, ValueError):
        pass
    lowered = raw.lower()
    for key in ("accept", "retry", "reject"):
        if key in lowered:
            return key, raw[:200]
    return "retry", raw[:200]


def _call_role(
    cfg: Dict[str, Any],
    *,
    role: str,
    stage: str,
    messages: List[Dict[str, str]],
    validator: Optional[Any] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    return agent_call(
        cfg,
        messages,
        log_dir=None,
        role=role,
        stage=stage,
        settings={"temperature": temperature},
        validator=validator,
    )


def _quality_warnings(sections: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    for key in ["overview", "requirements", "interfaces", "uds_frames", "notes"]:
        val = sections.get(key)
        if not isinstance(val, dict):
            continue
        text = str(val.get("text") or "").strip()
        evidence = val.get("evidence") or []
        if text and text.upper() != "N/A" and not evidence:
            warnings.append(f"{key}: evidence_missing")
    logic_items = sections.get("logic_diagrams") if isinstance(sections.get("logic_diagrams"), list) else []
    for item in logic_items or []:
        if not isinstance(item, dict):
            continue
        if item.get("description") and not item.get("evidence"):
            title = str(item.get("title") or "logic")
            warnings.append(f"logic_diagrams:{title}: evidence_missing")
    return warnings


def _build_section_prompt(section_key: str, *, repair: bool = False) -> str:
    repair_header = (
        "IMPORTANT: This is a REPAIR attempt. "
        "The previous LLM response truncated and produced N/A for this section. "
        "You MUST generate substantive content using the provided source data. "
        "Writing N/A is only acceptable if the source data contains absolutely "
        "zero relevant information for this section.\n"
    ) if repair else ""
    return (
        f"{repair_header}"
        f"You are a UDS Writer for section: {section_key}.\n"
        "Return JSON only: {\"text\":\"...\",\"evidence\":[{source_type, source_file, excerpt, score}]}.\n"
        "Safety: Do NOT invent facts. If insufficient data, write \"N/A\" and evidence can be empty.\n"
        "ASIL Assignment Rules:\n"
        "- Use ASIL from SRS/SDS documents first (source_type: srs/sds).\n"
        "- Use Doxygen @asil/@safety tags if present (source_type: comment).\n"
        "- Infer ASIL from calling/called functions' ASIL levels (highest inherits).\n"
        "- Functions accessing safety-critical shared data inherit the data's ASIL.\n"
        "- Default to QM only when no evidence exists.\n"
        "Related ID Rules:\n"
        "- Map functions to SwTR/SwTSR/SwFn IDs from requirements documents.\n"
        "- Use @requirement/@req tags from Doxygen comments.\n"
        "- Trace through call graphs to find indirect requirement links."
    )


def _repair_missing_sections(
    raw: Dict[str, Any],
    *,
    cfg: Dict[str, Any],
    user_payload: Dict[str, Any],
    analysis_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Regenerate sections that were auto-filled with N/A by _validate_sections."""
    REQUIRED = ["overview", "requirements", "interfaces", "uds_frames", "notes"]
    missing = [
        k for k in REQUIRED
        if not raw.get(k) or str(raw[k].get("text", "")).strip().upper() == "N/A"
    ]
    if not missing:
        return raw

    logger.info("_repair_missing_sections: regenerating %d sections: %s", len(missing), missing)

    already_generated = {
        k: raw[k] for k in REQUIRED if k not in missing and raw.get(k)
    }

    def _run_repair(key: str) -> Tuple[str, Dict[str, Any]]:
        messages = [
            {"role": "system", "content": _build_section_prompt(key, repair=True)},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        **user_payload,
                        "analysis_context": analysis_payload,
                        "target_section": key,
                        "already_generated": already_generated,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]
        res = _call_role(cfg, role="writer", stage=f"uds_repair_{key}", messages=messages, temperature=0.2)
        reply = res.get("output") if isinstance(res, dict) else None
        payload = _extract_json_payload(reply or "") or {}
        return key, _normalize_section(payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_run_repair, key) for key in missing]
        for future in concurrent.futures.as_completed(futures):
            key, section = future.result()
            if section and str(section.get("text", "")).strip().upper() != "N/A":
                raw[key] = section
                logger.info("_repair_missing_sections: repaired section '%s'", key)
            else:
                logger.warning("_repair_missing_sections: repair failed for '%s', keeping N/A", key)

    return raw


def _parallel_sections(
    cfg: Dict[str, Any],
    user_payload: Dict[str, Any],
    analysis_payload: Dict[str, Any],
) -> Dict[str, Any]:
    keys = ["overview", "requirements", "interfaces", "uds_frames", "notes"]
    out: Dict[str, Any] = {}

    def _run_section(key: str) -> Tuple[str, Dict[str, Any]]:
        messages = [
            {"role": "system", "content": _build_section_prompt(key)},
            {
                "role": "user",
                "content": json.dumps(
                    {**user_payload, "analysis_context": analysis_payload, "target_section": key},
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]
        res = _call_role(cfg, role="writer", stage=f"uds_{key}", messages=messages, temperature=0.2)
        reply = res.get("output") if isinstance(res, dict) else None
        payload = _extract_json_payload(reply or "") or {}
        return key, _normalize_section(payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_run_section, key) for key in keys]
        for future in concurrent.futures.as_completed(futures):
            key, section = future.result()
            out[key] = section
    return out


def generate_uds_ai_sections(
    *,
    requirements_text: str,
    source_sections: Dict[str, str],
    notes_text: str,
    logic_items: List[Dict[str, Any]],
    example_text: str = "",
    detailed: bool = True,
    rag_snippets: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    cfg = load_oai_config(None)
    if not cfg:
        return None

    logic_titles = [str(x.get("title") or "") for x in logic_items if isinstance(x, dict)]
    norm_rag_snippets: List[Dict[str, Any]] = []
    for item in rag_snippets or []:
        if isinstance(item, dict):
            norm_rag_snippets.append(
                {
                    "source_type": "rag",
                    "source_file": str(item.get("source_file") or ""),
                    "excerpt": str(item.get("excerpt") or item.get("content") or item.get("text") or ""),
                    "score": item.get("score"),
                }
            )
    user_payload = {
        "requirements": _trim_text(requirements_text, 24000),
        "source_overview": _trim_text(source_sections.get("overview", ""), 8000),
        "source_requirements": _trim_text(source_sections.get("requirements", ""), 12000),
        "source_interfaces": _trim_text(source_sections.get("interfaces", ""), 8000),
        "source_uds_frames": _trim_text(source_sections.get("uds_frames", ""), 8000),
        "notes": _trim_text(notes_text, 6000),
        "logic_diagrams": logic_titles,
        "example_output": _extract_style_excerpt(example_text, max_chars=12000),
        "rag_snippets": norm_rag_snippets,
    }

    analysis_prompt = (
        "Analyze the inputs for completeness and conflicts.\n"
        "Return JSON only: {\"refined_requirements\":\"...\",\"gaps\":[],\"notes\":\"...\"}.\n"
        "Do not invent facts."
    )
    analysis_messages = [
        {"role": "system", "content": analysis_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]
    analysis_res = _call_role(cfg, role="analysis", stage="uds_analysis", messages=analysis_messages)
    analysis_reply = analysis_res.get("output") if isinstance(analysis_res, dict) else None
    analysis_payload = _extract_json_payload(analysis_reply or "") or {}

    if bool(getattr(config, "UDS_PARALLEL_SECTIONS", False)):
        sections = _parallel_sections(cfg, user_payload, analysis_payload)
        sections = _repair_missing_sections(
            sections,
            cfg=cfg,
            user_payload=user_payload,
            analysis_payload=analysis_payload,
        )
        logic_payload = {"logic_diagrams": []}
        if logic_titles:
            logic_prompt = (
                "Create concise descriptions for logic diagrams. "
                "Return JSON only: {\"logic_diagrams\":[{\"title\":\"...\",\"description\":\"...\",\"evidence\":[{source_type, source_file, excerpt, score}]}]}."
            )
            logic_messages = [
                {"role": "system", "content": logic_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ]
            logic_res = _call_role(cfg, role="writer", stage="uds_logic", messages=logic_messages, temperature=0.2)
            logic_reply = logic_res.get("output") if isinstance(logic_res, dict) else None
            logic_payload = _extract_json_payload(logic_reply or "") or {}
        logic_raw = logic_payload.get("logic_diagrams") or []
        normalized_logic: List[Dict[str, Any]] = []
        if isinstance(logic_raw, list):
            for item in logic_raw:
                if not isinstance(item, dict):
                    continue
                normalized_logic.append(
                    {
                        "title": str(item.get("title") or ""),
                        "description": str(item.get("description") or ""),
                        "evidence": (
                            _normalize_evidence_list(item.get("evidence"))
                            or (
                                [{"source_type": "inference", "source_file": "", "excerpt": "", "score": None}]
                                if str(item.get("description") or "").strip()
                                and str(item.get("description") or "").strip().upper() != "N/A"
                                else []
                            )
                        ),
                    }
                )
        sections["logic_diagrams"] = normalized_logic
        if detailed:
            doc_lines = [
                "1. Overview",
                sections.get("overview", {}).get("text", ""),
                "2. Requirements",
                sections.get("requirements", {}).get("text", ""),
                "3. Interfaces",
                sections.get("interfaces", {}).get("text", ""),
                "4. UDS Frames",
                sections.get("uds_frames", {}).get("text", ""),
                "5. Notes",
                sections.get("notes", {}).get("text", ""),
            ]
            sections["document"] = "\n".join([ln for ln in doc_lines if ln is not None]).strip()
        sections["quality_warnings"] = _quality_warnings(sections)
        return sections

    system_prompt = (
        "You are a UDS Writer. Build UDS section text from given inputs.\n"
        "Safety:\n"
        "- Do NOT invent facts. If insufficient data, write \"N/A\".\n"
        "- Include evidence list per section with schema: {source_type, source_file, excerpt, score}.\n"
        "- If rag_snippets are provided, use source_type 'rag' and include source_file.\n"
        "- Each non-N/A section should be at least 2 sentences.\n"
        "- When detailed is true, produce a long, structured document with many subsections and numbering.\n"
        "- Target length should be comparable to example_output when available.\n"
        "ASIL Assignment:\n"
        "- Prefer ASIL from SRS/SDS documents (source: srs/sds).\n"
        "- Use Doxygen @asil/@safety tags (source: comment).\n"
        "- Infer from calling/called functions' ASIL (highest inherits). Default to QM.\n"
        "- Always record the source of ASIL assignment.\n"
        "Related ID Mapping:\n"
        "- Map to SwTR/SwTSR/SwFn IDs from SRS. Use @requirement tags from code.\n"
        "- Trace call graphs for indirect requirement links.\n"
        "Output MUST be a single JSON object with keys:\n"
        "overview, requirements, interfaces, uds_frames, notes, logic_diagrams, document.\n"
        "Each section value must be an object with fields: text, evidence.\n"
        "logic_diagrams is a list of objects: title, description, evidence.\n"
        "document is a full detailed UDS document in plain text, structured with numbering\n"
        "and headings similar to the example_output. Keep it consistent with given data.\n"
        "Use the example_output for style if provided, but do not copy content."
    )

    writer_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {**user_payload, "analysis_context": analysis_payload},
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]

    def _validator(reply: str) -> Any:
        data = _extract_json_payload(reply)
        return _validate_sections(data, detailed=detailed) if data is not None else None

    result = _call_role(
        cfg,
        role="writer",
        stage="uds_sections",
        messages=writer_messages,
        validator=_validator,
    )
    reply = result.get("output") if isinstance(result, dict) else None
    if not reply:
        attempts = result.get("attempts") or [] if isinstance(result, dict) else []
        for att in reversed(attempts):
            att_output = att.get("output") if isinstance(att, dict) else None
            if att_output:
                fallback = _extract_json_payload(str(att_output))
                if fallback:
                    validated = _validate_sections(fallback, detailed=detailed)
                    if validated:
                        logger.info("AI sections recovered from attempt fallback")
                        reply = att_output
                        break
        if not reply:
            _write_diag(
                {
                    "timestamp": _now_ts(),
                    "ok": False,
                    "reason": result.get("reason") if isinstance(result, dict) else "no_result",
                    "attempts": attempts,
                }
            )
            return None
    raw = _extract_json_payload(reply)
    if raw is None:
        _write_diag(
            {
                "timestamp": _now_ts(),
                "ok": False,
                "reason": "json_parse_failed",
                "attempts": result.get("attempts") if isinstance(result, dict) else [],
            }
        )
        return None

    raw = _repair_missing_sections(
        raw,
        cfg=cfg,
        user_payload=user_payload,
        analysis_payload=analysis_payload,
    )

    review_prompt = _load_prompt("uds_reviewer")
    review_messages = [
        {"role": "system", "content": review_prompt},
        {"role": "user", "content": json.dumps(raw, ensure_ascii=False, indent=2)},
    ]
    review_res = _call_role(cfg, role="reviewer", stage="uds_review", messages=review_messages, temperature=0.1)
    review_reply = review_res.get("output") if isinstance(review_res, dict) else None
    decision, reason = _parse_decision(review_reply)
    if decision == "accept":
        auditor_prompt = _load_prompt("uds_auditor")
        audit_messages = [
            {"role": "system", "content": auditor_prompt},
            {"role": "user", "content": json.dumps(raw, ensure_ascii=False, indent=2)},
        ]
        audit_res = _call_role(cfg, role="auditor", stage="uds_audit", messages=audit_messages, temperature=0.1)
        audit_reply = audit_res.get("output") if isinstance(audit_res, dict) else None
        decision, reason = _parse_decision(audit_reply)

    max_retries = 2
    retry_count = 0
    best_raw = raw
    while decision in ("retry", "reject") and retry_count < max_retries:
        retry_count += 1
        writer_messages.append(
            {
                "role": "user",
                "content": f"Reviewer/Auditor feedback (attempt {retry_count}): {reason}. Fix the output to comply.",
            }
        )
        result = _call_role(
            cfg,
            role="writer",
            stage=f"uds_sections_retry_{retry_count}",
            messages=writer_messages,
            validator=_validator,
        )
        reply = result.get("output") if isinstance(result, dict) else None
        retry_raw = _extract_json_payload(reply or "") if reply else None
        if retry_raw is None:
            break
        raw = retry_raw
        best_raw = raw
        review_messages_r = [
            {"role": "system", "content": review_prompt},
            {"role": "user", "content": json.dumps(raw, ensure_ascii=False, indent=2)},
        ]
        review_res_r = _call_role(cfg, role="reviewer", stage=f"uds_review_retry_{retry_count}", messages=review_messages_r, temperature=0.1)
        decision, reason = _parse_decision(review_res_r.get("output") if isinstance(review_res_r, dict) else None)
    if best_raw is None:
        return None
    raw = best_raw

    sections: Dict[str, Any] = {}
    for key in ["overview", "requirements", "interfaces", "uds_frames", "notes"]:
        sections[key] = _normalize_section(raw.get(key))
    logic_raw = raw.get("logic_diagrams") or []
    if isinstance(logic_raw, list):
        normalized_logic: List[Dict[str, Any]] = []
        for item in logic_raw:
            if not isinstance(item, dict):
                continue
            normalized_logic.append(
                {
                    "title": str(item.get("title") or ""),
                    "description": str(item.get("description") or ""),
                    "evidence": (
                        _normalize_evidence_list(item.get("evidence"))
                        or (
                            [{"source_type": "inference", "source_file": "", "excerpt": "", "score": None}]
                            if str(item.get("description") or "").strip()
                            and str(item.get("description") or "").strip().upper() != "N/A"
                            else []
                        )
                    ),
                }
            )
        sections["logic_diagrams"] = normalized_logic
    else:
        sections["logic_diagrams"] = []
    if detailed:
        sections["document"] = str(raw.get("document") or "").strip()
    sections["quality_warnings"] = _quality_warnings(sections)
    return sections


# ---------------------------------------------------------------------------
# Per-function AI description generation
# ---------------------------------------------------------------------------

_FUNC_DESC_BATCH_SIZE = 5
_FUNC_DESC_MAX_BATCHES = 120
_FUNC_DESC_BATCH_DELAY = 3.0
_FUNC_DESC_BACKOFF_BASE = 4.0
_FUNC_DESC_BACKOFF_MAX = 120.0


def _build_func_desc_prompt(batch: List[Dict[str, Any]], *, pass_num: int = 1) -> str:
    if pass_num == 2:
        lines = [
            "You are an automotive software documentation expert.",
            "Refine each function's Korean description using the additional context (body snippet, prior description).",
            "Keep descriptions concise (1-3 sentences). Improve accuracy based on the code body.",
            "Return ONLY a JSON object mapping function name to refined description string.",
            "",
            "Functions:",
        ]
    else:
        lines = [
            "You are an automotive software documentation expert.",
            "For each function below, write a concise Korean description (1-2 sentences) explaining its purpose.",
            "Base your description ONLY on the provided information (name, prototype, module, called functions, globals).",
            "Do NOT invent functionality. If insufficient data, describe based on the function name.",
            "Return ONLY a JSON object mapping function name to description string.",
            'Example: {"func_a": "시스템 초기화 후 ADC 변환을 시작한다.", "func_b": "수신된 LIN 프레임의 CRC를 검증한다."}',
            "",
            "Functions:",
        ]
    for item in batch:
        name = item.get("name", "")
        proto = item.get("prototype", "")
        module = item.get("module", "")
        called = item.get("called", "")
        globals_g = item.get("globals_summary", "")
        lines.append(f"- name: {name}")
        if proto:
            lines.append(f"  prototype: {proto}")
        if module:
            lines.append(f"  module: {module}")
        if called:
            lines.append(f"  calls: {called}")
        if globals_g:
            lines.append(f"  globals: {globals_g}")
        if pass_num == 2:
            prior = item.get("prior_desc", "")
            body = item.get("body_snippet", "")
            if prior:
                lines.append(f"  prior_description: {prior}")
            if body:
                lines.append(f"  body_snippet: {body}")
        lines.append("")
    return "\n".join(lines)


def generate_ai_function_descriptions(
    function_details: Dict[str, Dict[str, Any]],
    module_map: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Generate AI descriptions for functions that currently have inference-only descriptions.

    Returns a dict mapping fid to AI-generated description.
    Also includes name-based keys for backward compatibility.
    """
    configs = load_oai_configs(None)
    cfg = None
    for c in (configs or []):
        m = str(c.get("model") or "").lower()
        if "flash" in m:
            cfg = c
            logger.info("Using flash model for func desc: %s", c.get("model"))
            break
    if not cfg:
        cfg = load_oai_config(None)
    if not cfg:
        logger.warning("AI config not available for function descriptions")
        return {}

    if not module_map:
        module_map = {}

    candidates: List[Dict[str, Any]] = []
    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        src = str(info.get("description_source") or "").strip().lower()
        if src in {"comment", "sds", "reference", "ai"}:
            continue
        name = str(info.get("name") or "").strip()
        if not name:
            continue
        called_list = []
        called_raw = info.get("called") or ""
        if isinstance(called_raw, str):
            called_list = [c.strip() for c in called_raw.split("\n") if c.strip() and c.strip().upper() not in {"N/A", "-"}]
        elif isinstance(called_raw, list):
            called_list = [str(c).strip() for c in called_raw if str(c).strip()]

        gg = info.get("globals_global") or []
        gs = info.get("globals_static") or []
        globals_names = []
        for g in (gg[:3] + gs[:2]):
            raw = str(g or "").strip()
            m = re.match(r"^\[(?:IN|OUT|INOUT)\]\s+(.+)", raw)
            if m:
                globals_names.append(m.group(1).split("|")[0].strip()[:30])
            elif raw and raw.upper() not in {"N/A", "-"}:
                globals_names.append(raw[:30])

        candidates.append({
            "fid": fid,
            "name": name,
            "prototype": str(info.get("prototype") or "")[:120],
            "module": module_map.get(name.lower(), ""),
            "called": ", ".join(called_list[:5]),
            "globals_summary": ", ".join(globals_names[:4]),
        })

    if not candidates:
        logger.info("No candidates for AI function description generation")
        return {}

    logger.info("AI function description: %d candidates in %d batches",
                len(candidates), min(len(candidates) // _FUNC_DESC_BATCH_SIZE + 1, _FUNC_DESC_MAX_BATCHES))

    results: Dict[str, str] = {}
    batches = [candidates[i:i + _FUNC_DESC_BATCH_SIZE]
               for i in range(0, len(candidates), _FUNC_DESC_BATCH_SIZE)]
    batches = batches[:_FUNC_DESC_MAX_BATCHES]

    import threading as _threading
    _results_lock = _threading.Lock()

    def _process_batch(batch_idx: int, batch: list, *, pass_num: int = 1) -> int:
        """Process a single batch. Returns number of errors (0 or 1)."""
        import time as _time
        prompt = _build_func_desc_prompt(batch, pass_num=pass_num)
        messages = [
            {"role": "system", "content": "Return ONLY valid JSON. No markdown fences, no extra text."},
            {"role": "user", "content": prompt},
        ]
        max_retries = 6
        stage = f"func_desc_batch_{batch_idx}" if pass_num == 1 else f"func_desc_p2_batch_{batch_idx}"
        temp = 0.2 if pass_num == 1 else 0.3
        logger.info("[AI] Pass%d batch %d/%d (%d funcs)...", pass_num, batch_idx + 1, len(batches), len(batch))
        for attempt in range(max_retries):
            try:
                res = _call_role(cfg, role="writer", stage=stage, messages=messages, temperature=temp)
                reply = res.get("output") if isinstance(res, dict) else None
                if not reply:
                    logger.warning("[AI] batch %d: empty reply", batch_idx + 1)
                    return 0
                parsed = _extract_json_payload(reply)
                if not isinstance(parsed, dict):
                    logger.warning("[AI] batch %d: invalid JSON", batch_idx + 1)
                    return 0
                batch_ok = 0
                with _results_lock:
                    for item in batch:
                        name = item["name"]
                        fid = item.get("fid", "")
                        desc = parsed.get(name) or parsed.get(name.lower()) or ""
                        desc = str(desc).strip()
                        min_len = 5 if pass_num == 1 else 10
                        if desc and len(desc) > min_len:
                            results[name.lower()] = desc
                            if fid:
                                results[f"__fid__{fid}"] = desc
                            batch_ok += 1
                fid_count = sum(1 for k in results if k.startswith("__fid__"))
                logger.info("[AI] batch %d: OK (%d/%d), unique_names=%d, fid_mapped=%d",
                            batch_idx + 1, batch_ok, len(batch), len(results) - fid_count, fid_count)
                return 0
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "rate" in err_str or "quota" in err_str or "resource_exhausted" in err_str
                if is_rate_limit and attempt < max_retries - 1:
                    backoff = min(_FUNC_DESC_BACKOFF_BASE * (2 ** attempt), _FUNC_DESC_BACKOFF_MAX)
                    logger.warning("[AI] batch %d: rate limited, wait %.0fs (attempt %d/%d)",
                                   batch_idx + 1, backoff, attempt + 1, max_retries)
                    _time.sleep(backoff)
                    continue
                logger.error("[AI] batch %d: FAILED - %s", batch_idx + 1, e)
                return 1
        return 0

    _AI_PARALLEL_WORKERS = int(os.environ.get("AI_PARALLEL_WORKERS", "2"))

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=_AI_PARALLEL_WORKERS) as pool:
        futures = {}
        for batch_idx, batch in enumerate(batches):
            futures[pool.submit(_process_batch, batch_idx, batch)] = batch_idx
        consecutive_errors = 0
        for fut in as_completed(futures):
            errs = fut.result()
            consecutive_errors += errs
            if consecutive_errors >= 10:
                logger.error("AI func desc: %d consecutive errors, aborting", consecutive_errors)
                break

    fid_count = sum(1 for k in results if k.startswith("__fid__"))
    logger.info("AI function description pass 1: %d unique names, %d fid-mapped / %d candidates",
                len(results) - fid_count, fid_count, len(candidates))

    # Pass 2: refine with body snippets for functions that got pass-1 results
    pass2_candidates = []
    for item in candidates:
        name = item["name"]
        if name.lower() not in results:
            continue
        fid = item.get("fid", "")
        finfo = function_details.get(fid, {})
        body = str(finfo.get("body_text") or "")[:400]
        if not body or len(body) < 20:
            continue
        pass2_candidates.append({
            **item,
            "prior_desc": results[name.lower()],
            "body_snippet": body,
        })

    if pass2_candidates:
        pass2_batches = [pass2_candidates[i:i + _FUNC_DESC_BATCH_SIZE]
                         for i in range(0, len(pass2_candidates), _FUNC_DESC_BATCH_SIZE)]
        pass2_batches = pass2_batches[:_FUNC_DESC_MAX_BATCHES // 2]
        logger.info("AI function description pass 2: %d candidates in %d batches",
                     len(pass2_candidates), len(pass2_batches))
        with ThreadPoolExecutor(max_workers=_AI_PARALLEL_WORKERS) as pool:
            p2_futures = {}
            for batch_idx, batch in enumerate(pass2_batches):
                p2_futures[pool.submit(_process_batch, batch_idx, batch, pass_num=2)] = batch_idx
            for fut in as_completed(p2_futures):
                try:
                    fut.result()
                except Exception as e:
                    logger.warning("AI func desc pass 2 batch failed: %s", e)
        fid_count_p2 = sum(1 for k in results if k.startswith("__fid__"))
        logger.info("AI function description pass 2 complete: %d unique names, %d fid-mapped", len(results) - fid_count_p2, fid_count_p2)

    return results
