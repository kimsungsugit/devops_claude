"""UDS (Unit Design Specification) domain helpers."""
import re
import os
import sys
import json
import time
import logging
import tempfile
import zipfile
import traceback
import subprocess
import threading
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Set
from time import time

try:
    from fastapi import HTTPException, UploadFile
except ImportError:
    HTTPException = Exception
    UploadFile = None  # type: ignore[assignment,misc]

from backend.state import (
    uds_view_cache_lock as _uds_view_cache_lock,
    uds_view_cache as _uds_view_cache,
    source_sections_cache_lock as _source_sections_cache_lock,
    source_sections_cache as _source_sections_cache,
)
from backend.services.paths import is_under_any
from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug
from backend.services.report_parsers import build_report_summary

import config
from report_generator import (
    _build_req_map_from_doc_paths,
    build_uds_view_payload,
    generate_uds_source_sections,
    generate_uds_requirements_from_docs,
    generate_uds_validation_report,
    generate_uds_field_quality_gate_report,
    generate_uds_constraints_report,
    generate_uds_preview_html,
    generate_uds_logic_items,
    generate_called_calling_accuracy_report,
    generate_swcom_context_report,
    generate_swcom_context_diff_report,
    generate_asil_related_confidence_report,
)
try:
    from workflow.uds_ai import generate_uds_ai_sections
except ImportError:
    generate_uds_ai_sections = None
try:
    from workflow.rag import _read_text_from_file, get_kb
except ImportError:
    _read_text_from_file = None
    get_kb = None

from backend.helpers.common import (
    _split_signature_params,
    _extract_param_name_simple,
    _mtime_or_zero,
    _has_meaningful_value,
    _normalize_field_source,
    _has_trace_token,
    _is_trusted_source_for_field,
    _normalize_symbol_simple,
    _compact_symbol_simple,
    _normalize_asil_simple,
    _infer_related_id_simple,
    _parse_signature_params_simple,
    _parse_signature_outputs_simple,
    _is_allowed_req_doc,
    _write_upload_to_temp,
    _parse_component_map_file,
    _read_json,
    _write_json,
    _run_report_with_timeout,
    _progress_key,
    _set_progress,
    _get_progress,
    _parse_path_list,
    _safe_extract_zip,
    SETTINGS_FILE,
    _api_logger,
)

_logger = logging.getLogger("devops_api")

repo_root = Path(__file__).resolve().parents[2]



def _compute_quick_quality_gate(uds_payload: Dict[str, Any]) -> Dict[str, Any]:
    by_name = uds_payload.get("function_details_by_name")
    rows: List[Dict[str, Any]] = []
    if isinstance(by_name, dict):
        for _, info in by_name.items():
            if isinstance(info, dict):
                rows.append(info)
    if not rows:
        detail_map = uds_payload.get("function_details")
        if isinstance(detail_map, dict):
            for _, info in detail_map.items():
                if isinstance(info, dict):
                    rows.append(info)
    _thresholds = getattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {})
    total = len(rows)
    if total <= 0:
        return {
            "gate_pass": False,
            "reason": "no functions",
            "thresholds": dict(_thresholds),
            "rates": {
                "called_fill": 0.0,
                "calling_fill": 0.0,
                "input_fill": 0.0,
                "output_fill": 0.0,
                "global_fill": 0.0,
                "static_fill": 0.0,
                "description_fill": 0.0,
                "asil_fill": 0.0,
                "related_fill": 0.0,
                "description_trusted_fill": 0.0,
                "asil_trusted_fill": 0.0,
                "related_trusted_fill": 0.0,
            },
            "counts": {
                "total_functions": 0,
                "with_called": 0,
                "with_calling": 0,
                "with_input": 0,
                "with_output": 0,
                "with_global": 0,
                "with_static": 0,
                "with_description": 0,
                "with_asil": 0,
                "with_related": 0,
                "with_description_trusted": 0,
                "with_asil_trusted": 0,
                "with_related_trusted": 0,
            },
            "confidence_gate_pass": False,
        }
    with_input = sum(1 for r in rows if _has_meaningful_value(r.get("inputs")))
    with_output = sum(1 for r in rows if _has_meaningful_value(r.get("outputs")))
    with_called = sum(1 for r in rows if _has_meaningful_value(r.get("called") or r.get("calls_list")))
    with_calling = sum(1 for r in rows if _has_meaningful_value(r.get("calling")))
    with_global = sum(1 for r in rows if _has_meaningful_value(r.get("globals_global")))
    with_static = sum(1 for r in rows if _has_meaningful_value(r.get("globals_static")))
    with_description = sum(1 for r in rows if _has_meaningful_value(r.get("description")))
    with_asil = sum(1 for r in rows if _has_meaningful_value(r.get("asil")))
    with_related = sum(
        1
        for r in rows
        if _has_meaningful_value(r.get("related") or r.get("related_id") or r.get("related_ids"))
    )
    with_description_trusted = sum(
        1 for r in rows if _has_meaningful_value(r.get("description")) and _is_trusted_source_for_field(r, "description")
    )
    with_asil_trusted = sum(
        1 for r in rows if _has_meaningful_value(r.get("asil")) and _is_trusted_source_for_field(r, "asil")
    )
    with_related_trusted = sum(
        1
        for r in rows
        if _has_meaningful_value(r.get("related") or r.get("related_id") or r.get("related_ids"))
        and _is_trusted_source_for_field(r, "related")
    )
    called_rate = round((with_called / total) * 100.0, 1)
    calling_rate = round((with_calling / total) * 100.0, 1)
    input_rate = round((with_input / total) * 100.0, 1)
    output_rate = round((with_output / total) * 100.0, 1)
    global_rate = round((with_global / total) * 100.0, 1)
    static_rate = round((with_static / total) * 100.0, 1)
    description_rate = round((with_description / total) * 100.0, 1)
    asil_rate = round((with_asil / total) * 100.0, 1)
    related_rate = round((with_related / total) * 100.0, 1)
    description_trusted_rate = round((with_description_trusted / total) * 100.0, 1)
    asil_trusted_rate = round((with_asil_trusted / total) * 100.0, 1)
    related_trusted_rate = round((with_related_trusted / total) * 100.0, 1)
    thresholds = dict(_thresholds)
    gate_pass = (
        called_rate >= thresholds["called_min"]
        and calling_rate >= thresholds["calling_min"]
        and input_rate >= thresholds["input_min"]
        and output_rate >= thresholds["output_min"]
        and description_rate >= thresholds["description_min"]
        and asil_rate >= thresholds["asil_min"]
        and related_rate >= thresholds["related_min"]
    )
    confidence_gate_pass = (
        description_trusted_rate >= thresholds["description_trusted_min"]
        and asil_trusted_rate >= thresholds["asil_trusted_min"]
        and related_trusted_rate >= thresholds["related_trusted_min"]
    )
    return {
        "gate_pass": bool(gate_pass),
        "thresholds": thresholds,
        "rates": {
            "called_fill": called_rate,
            "calling_fill": calling_rate,
            "input_fill": input_rate,
            "output_fill": output_rate,
            "global_fill": global_rate,
            "static_fill": static_rate,
            "description_fill": description_rate,
            "asil_fill": asil_rate,
            "related_fill": related_rate,
            "description_trusted_fill": description_trusted_rate,
            "asil_trusted_fill": asil_trusted_rate,
            "related_trusted_fill": related_trusted_rate,
        },
        "counts": {
            "total_functions": total,
            "with_called": with_called,
            "with_calling": with_calling,
            "with_input": with_input,
            "with_output": with_output,
            "with_global": with_global,
            "with_static": with_static,
            "with_description": with_description,
            "with_asil": with_asil,
            "with_related": with_related,
            "with_description_trusted": with_description_trusted,
            "with_asil_trusted": with_asil_trusted,
            "with_related_trusted": with_related_trusted,
        },
        "confidence_gate_pass": bool(confidence_gate_pass),
    }


def _enrich_function_quality_fields(uds_payload: Dict[str, Any]) -> None:
    if not isinstance(uds_payload, dict):
        return
    details = uds_payload.get("function_details")
    by_name = uds_payload.get("function_details_by_name")
    call_map = uds_payload.get("call_map")
    if not isinstance(call_map, dict):
        call_map = {}
    reverse: Dict[str, List[str]] = {}
    normalized_call_map: Dict[str, List[str]] = {}
    compact_call_map: Dict[str, List[str]] = {}
    alias_name: Dict[str, str] = {}

    def _register_alias(raw_name: str, preferred: str) -> None:
        n = _normalize_symbol_simple(raw_name)
        c = _compact_symbol_simple(raw_name)
        if n and n not in alias_name:
            alias_name[n] = preferred
        if c and c not in alias_name:
            alias_name[c] = preferred

    if isinstance(details, dict):
        for _, info in details.items():
            if not isinstance(info, dict):
                continue
            nm = str(info.get("name") or "").strip()
            if nm:
                _register_alias(nm, nm)
    if isinstance(by_name, dict):
        for k, info in by_name.items():
            nm = str((info or {}).get("name") or "").strip() if isinstance(info, dict) else ""
            preferred = nm or str(k or "").strip()
            _register_alias(str(k or ""), preferred)
            if nm:
                _register_alias(nm, preferred)
    for caller, callees in call_map.items():
        caller_name = str(caller or "").strip()
        c_norm = _normalize_symbol_simple(caller_name)
        if not c_norm or not isinstance(callees, list):
            continue
        c_comp = _compact_symbol_simple(caller_name)
        normalized_call_map.setdefault(c_norm, [])
        compact_call_map.setdefault(c_comp, [])
        for callee in callees:
            callee_name = str(callee or "").strip()
            n = _normalize_symbol_simple(callee_name)
            c = _compact_symbol_simple(callee_name)
            if not n:
                continue
            if callee_name and callee_name not in normalized_call_map[c_norm]:
                normalized_call_map[c_norm].append(callee_name)
            if callee_name and callee_name not in compact_call_map[c_comp]:
                compact_call_map[c_comp].append(callee_name)
            reverse.setdefault(n, [])
            if caller_name and caller_name not in reverse[n]:
                reverse[n].append(caller_name)
            reverse.setdefault(c, [])
            if caller_name and caller_name not in reverse[c]:
                reverse[c].append(caller_name)

    def _is_blank_value(value: Any) -> bool:
        text = str(value or "").strip()
        return (not text) or text.upper() in {"N/A", "TBD", "-"}

    def _is_blank_list(value: Any) -> bool:
        if not isinstance(value, list):
            return True
        rows = [str(x).strip() for x in value if str(x).strip()]
        return len(rows) == 0

    def _patch_info(info: Dict[str, Any]) -> None:
        if not isinstance(info, dict):
            return
        sig = str(info.get("signature") or info.get("prototype") or "").strip()
        if _is_blank_list(info.get("inputs")) and sig:
            info["inputs"] = _parse_signature_params_simple(sig)
        if _is_blank_list(info.get("outputs")) and sig:
            info["outputs"] = _parse_signature_outputs_simple(sig)
        if _is_blank_value(info.get("called")):
            fn_name = str(info.get("name") or "").strip()
            fn_norm = _normalize_symbol_simple(fn_name)
            fn_comp = _compact_symbol_simple(fn_name)
            callees = list(normalized_call_map.get(fn_norm, [])) + list(compact_call_map.get(fn_comp, []))
            dedup_raw = list(dict.fromkeys([str(v).strip() for v in callees if str(v).strip()]))
            dedup: List[str] = []
            for item in dedup_raw:
                if not item or item == fn_name:
                    continue
                canon = alias_name.get(_normalize_symbol_simple(item)) or alias_name.get(_compact_symbol_simple(item)) or item
                if canon == fn_name:
                    continue
                if canon not in dedup:
                    dedup.append(canon)
            info["called"] = "\n".join(dedup) if dedup else "No callee (leaf function)"
        if _is_blank_value(info.get("calling")):
            fn_name = str(info.get("name") or "").strip()
            fn_norm = _normalize_symbol_simple(fn_name)
            fn_comp = _compact_symbol_simple(fn_name)
            callers = list(reverse.get(fn_norm, [])) + list(reverse.get(fn_comp, []))
            dedup_callers: List[str] = []
            for item in callers:
                s = str(item or "").strip()
                if not s or s == fn_name:
                    continue
                canon = alias_name.get(_normalize_symbol_simple(s)) or alias_name.get(_compact_symbol_simple(s)) or s
                if canon == fn_name:
                    continue
                if canon not in dedup_callers:
                    dedup_callers.append(canon)
            info["calling"] = "\n".join(dedup_callers) if dedup_callers else "No caller (entry/root function)"
        asil_norm = _normalize_asil_simple(info.get("asil"))
        if asil_norm:
            info["asil"] = asil_norm
            if _normalize_field_source(info.get("asil_source")) == "inference":
                info["asil_source"] = "rule"
        else:
            # Use QM as conservative default when no explicit ASIL mapping exists.
            info["asil"] = "QM"
            info["asil_source"] = "rule"
        if _is_blank_value(info.get("related") or info.get("related_id") or info.get("related_ids")):
            inferred_related = _infer_related_id_simple(info)
            if inferred_related:
                info["related"] = inferred_related
                info["related_source"] = "rule"
        else:
            if _normalize_field_source(info.get("related_source")) == "inference" and _has_trace_token(info.get("related")):
                info["related_source"] = "rule"

    if isinstance(details, dict):
        for _, info in details.items():
            _patch_info(info)
    if isinstance(by_name, dict):
        for _, info in by_name.items():
            _patch_info(info)


def _validate_docx_template_bytes(raw: Optional[bytes]) -> Tuple[bool, str]:
    if not raw:
        return False, "template bytes empty"
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                return False, "word/document.xml missing"
    except Exception as exc:
        return False, f"invalid docx zip: {exc}"
    return True, ""


def _parse_quality_gate_report(path: Optional[Path]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"gate_pass": None, "rates": {}}
    if not path or not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    m_gate = re.search(r"- Gate pass:\s*`?(True|False)`?", text, flags=re.I)
    if m_gate:
        out["gate_pass"] = str(m_gate.group(1)).strip().lower() == "true"
    for key in ["Description", "Input", "Output", "Globals\\(Global\\)", "Globals\\(Static\\)", "Called", "Calling"]:
        m = re.search(rf"- {key} fill:\s*`\d+`\s*/\s*`\d+`\s*\(([\d.]+)%\)", text, flags=re.I)
        if not m:
            continue
        norm = key.lower().replace("\\", "").replace("(", "_").replace(")", "").replace(" ", "_")
        out["rates"][f"{norm}_fill"] = float(m.group(1))
    return out


def _parse_accuracy_report(path: Optional[Path]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"called_exact_match": None, "calling_exact_match": None}
    if not path or not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    m_called = re.search(r"Called exact match:.*\(([\d.]+)%\)", text, flags=re.I)
    m_calling = re.search(r"Calling exact match:.*\(([\d.]+)%\)", text, flags=re.I)
    if m_called:
        out["called_exact_match"] = float(m_called.group(1))
    if m_calling:
        out["calling_exact_match"] = float(m_calling.group(1))
    return out


def _derive_quality_reason_codes(quick_gate: Dict[str, Any], template_warning: str = "") -> List[str]:
    codes: List[str] = []
    rates = quick_gate.get("rates") if isinstance(quick_gate, dict) else {}
    thresholds = quick_gate.get("thresholds") if isinstance(quick_gate, dict) else {}
    total = int((quick_gate.get("counts") or {}).get("total_functions") or 0) if isinstance(quick_gate, dict) else 0
    if total <= 0:
        codes.append("NO_FUNCTIONS")
    called = float((rates or {}).get("called_fill") or 0.0)
    calling = float((rates or {}).get("calling_fill") or 0.0)
    inp = float((rates or {}).get("input_fill") or 0.0)
    outp = float((rates or {}).get("output_fill") or 0.0)
    gbl = float((rates or {}).get("global_fill") or 0.0)
    stc = float((rates or {}).get("static_fill") or 0.0)
    desc = float((rates or {}).get("description_fill") or 0.0)
    asil = float((rates or {}).get("asil_fill") or 0.0)
    rel = float((rates or {}).get("related_fill") or 0.0)
    desc_trust = float((rates or {}).get("description_trusted_fill") or 0.0)
    asil_trust = float((rates or {}).get("asil_trusted_fill") or 0.0)
    rel_trust = float((rates or {}).get("related_trusted_fill") or 0.0)
    if called < float((thresholds or {}).get("called_min") or 95.0):
        codes.append("CALLED_LOW")
    if calling <= 0.0:
        codes.append("CALLING_ZERO")
    elif calling < float((thresholds or {}).get("calling_min") or 95.0):
        codes.append("CALLING_LOW")
    if inp < float((thresholds or {}).get("input_min") or 90.0):
        codes.append("INPUT_PARSE_LOW")
    if outp < float((thresholds or {}).get("output_min") or 90.0):
        codes.append("OUTPUT_PARSE_LOW")
    if gbl < float((thresholds or {}).get("global_min") or 40.0):
        codes.append("GLOBAL_PARSE_LOW")
    if stc < float((thresholds or {}).get("static_min") or 20.0):
        codes.append("STATIC_PARSE_LOW")
    if desc < float((thresholds or {}).get("description_min") or 90.0):
        codes.append("DESCRIPTION_LOW")
    if asil < float((thresholds or {}).get("asil_min") or 50.0):
        codes.append("ASIL_LOW")
    if rel < float((thresholds or {}).get("related_min") or 70.0):
        codes.append("RELATED_ID_LOW")
    if desc_trust < float((thresholds or {}).get("description_trusted_min") or 60.0):
        codes.append("DESCRIPTION_TRUST_LOW")
    if asil_trust < float((thresholds or {}).get("asil_trusted_min") or 40.0):
        codes.append("ASIL_TRUST_LOW")
    if rel_trust < float((thresholds or {}).get("related_trusted_min") or 50.0):
        codes.append("RELATED_ID_TRUST_LOW")
    if template_warning:
        codes.append("TEMPLATE_INVALID")
    return list(dict.fromkeys(codes))


def _build_quality_action_hints(reason_codes: List[str]) -> List[str]:
    hints: List[str] = []
    rc = set([str(x or "").strip() for x in (reason_codes or []) if str(x or "").strip()])
    if "CALLED_LOW" in rc:
        hints.append("called 복원 규칙을 강화하세요(call_map 정규화/alias 매칭).")
    if "CALLING_ZERO" in rc or "CALLING_LOW" in rc:
        hints.append("calling 역방향 매핑과 함수명 정규화 규칙을 점검하세요.")
    if "INPUT_PARSE_LOW" in rc:
        hints.append("시그니처 파서를 확장하세요(포인터/배열/함수포인터/typedef).")
    if "OUTPUT_PARSE_LOW" in rc:
        hints.append("출력 판정 규칙(return + non-const pointer/array)을 보강하세요.")
    if "GLOBAL_PARSE_LOW" in rc:
        hints.append("globals_global 추출 규칙과 전역변수 사용 탐지를 보강하세요.")
    if "STATIC_PARSE_LOW" in rc:
        hints.append("globals_static 추출 규칙(정적 변수 매핑)을 점검하세요.")
    if "DESCRIPTION_LOW" in rc:
        hints.append("description 추론/참조 병합 규칙을 점검하세요.")
    if "ASIL_LOW" in rc:
        hints.append("ASIL 매핑(SDS/SRS/주석) 규칙을 강화하세요.")
    if "RELATED_ID_LOW" in rc:
        hints.append("Related ID(SwCom/SwFn) 추적성 링크 규칙을 보강하세요.")
    if "DESCRIPTION_TRUST_LOW" in rc:
        hints.append("description_source의 inference/rule 비중을 줄이고 SDS/SRS/reference 매핑을 늘리세요.")
    if "ASIL_TRUST_LOW" in rc:
        hints.append("ASIL을 기본 QM 추론 대신 SDS/SRS/주석 근거로 매핑하도록 보강하세요.")
    if "RELATED_ID_TRUST_LOW" in rc:
        hints.append("related_source를 inference/rule에서 SRS/SDS/reference로 승격시키는 규칙을 추가하세요.")
    if "TEMPLATE_INVALID" in rc:
        hints.append("DOCX 템플릿 유효성(word/document.xml)을 확인하거나 fallback 사용하세요.")
    if "NO_FUNCTIONS" in rc:
        hints.append("source_root/파서 결과를 확인하고 함수 추출이 되는지 점검하세요.")
    return hints


def _build_quality_evaluation(
    quick_gate: Dict[str, Any],
    quality_gate_path: Optional[Path],
    accuracy_path: Optional[Path],
    *,
    template_warning: str = "",
    doc_only_mode: bool = False,
) -> Dict[str, Any]:
    report_gate = _parse_quality_gate_report(quality_gate_path)
    report_acc = _parse_accuracy_report(accuracy_path)
    reason_codes = _derive_quality_reason_codes(quick_gate, template_warning=template_warning)
    action_hints = _build_quality_action_hints(reason_codes)
    quick_pass = bool((quick_gate or {}).get("gate_pass"))
    confidence_pass = bool((quick_gate or {}).get("confidence_gate_pass"))
    report_pass = report_gate.get("gate_pass")
    if doc_only_mode:
        # In doc-only mode, additional reports are intentionally skipped.
        merged_pass = bool(quick_pass and confidence_pass)
        gate_source = "quick_only"
    elif report_pass is None:
        merged_pass = bool(quick_pass and confidence_pass)
        gate_source = "quick_only"
    else:
        merged_pass = bool(quick_pass and confidence_pass and bool(report_pass))
        gate_source = "quick_confidence_and_report"
    policy = {
        "mode": "doc_only" if doc_only_mode else "full",
        "hard_thresholds": quick_gate.get("thresholds") if isinstance(quick_gate, dict) else {},
        "warning_thresholds": getattr(config, "UDS_QUALITY_WARNING_THRESHOLDS", {}),
    }
    return {
        "gate_pass": merged_pass,
        "gate_source": gate_source,
        "quick_gate": quick_gate,
        "confidence_gate_pass": confidence_pass,
        "report_gate": report_gate,
        "accuracy": report_acc,
        "reason_codes": reason_codes,
        "action_hints": action_hints,
        "template_warning": template_warning,
        "policy": policy,
    }


def _to_swcom_from_fn(info: Dict[str, Any]) -> str:
    fn_id = str(info.get("id") or "").strip()
    sw = str(info.get("swcom") or "").strip()
    if sw:
        return sw
    m = re.search(r"SwUFn_(\d{2})", fn_id, flags=re.I)
    return f"SwCom_{m.group(1)}" if m else "UNMAPPED"


def _get_source_sections_cached(source_root: str, max_files: int = 1200) -> Dict[str, Any]:
    root = Path(str(source_root or "")).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail="source_root not found or not directory")
    key = str(root)
    now = time()
    with _source_sections_cache_lock:
        item = _source_sections_cache.get(key)
        # Lightweight TTL cache to avoid repeated heavy parsing.
        _cache_ttl = getattr(config, "UDS_SOURCE_SECTIONS_CACHE_TTL", 1800)
        if item and (now - float(item.get("cached_at") or 0.0) <= _cache_ttl):
            payload = item.get("payload")
            if isinstance(payload, dict):
                return deepcopy(payload)
    import logging as _logging
    _log = _logging.getLogger("uvicorn.error")
    _log.info("[source_sections] Parsing started for %s", key)
    t0 = time()
    sections = generate_uds_source_sections(str(root))
    elapsed = time() - t0
    _log.info("[source_sections] Parsing finished in %.1fs for %s", elapsed, key)
    with _source_sections_cache_lock:
        _source_sections_cache[key] = {"payload": sections, "cached_at": now}
    return deepcopy(sections)


def _extract_call_graph_payload(
    sections: Dict[str, Any],
    focus_function: str,
    depth: int,
    include_external: bool = False,
) -> Dict[str, Any]:
    call_map = sections.get("call_map") if isinstance(sections.get("call_map"), dict) else {}
    details_by_name = (
        sections.get("function_details_by_name")
        if isinstance(sections.get("function_details_by_name"), dict)
        else {}
    )
    normalized: Dict[str, List[str]] = {}
    reverse: Dict[str, List[str]] = {}
    for caller, vals in call_map.items():
        c = str(caller or "").strip()
        if not c:
            continue
        out_vals: List[str] = []
        if isinstance(vals, list):
            for v in vals:
                name = str(v or "").strip()
                if name:
                    out_vals.append(name)
                    reverse.setdefault(name, []).append(c)
        normalized[c] = out_vals
    focus = str(focus_function or "").strip()
    nodes_set: set[str] = set()
    edges_set: set[Tuple[str, str]] = set()
    if focus and focus in normalized:
        frontier = {focus}
        nodes_set.add(focus)
        for _ in range(max(1, depth)):
            nxt: set[str] = set()
            for cur in frontier:
                for callee in normalized.get(cur, []):
                    nodes_set.add(callee)
                    edges_set.add((cur, callee))
                    nxt.add(callee)
                for caller in reverse.get(cur, []):
                    nodes_set.add(caller)
                    edges_set.add((caller, cur))
                    nxt.add(caller)
            frontier = nxt
            if not frontier:
                break
    else:
        for caller, vals in normalized.items():
            nodes_set.add(caller)
            for callee in vals:
                nodes_set.add(callee)
                edges_set.add((caller, callee))
    nodes = []
    for name in sorted(nodes_set):
        info = details_by_name.get(str(name).lower()) if isinstance(details_by_name, dict) else None
        if not isinstance(info, dict):
            info = {}
        nodes.append(
            {
                "id": name,
                "label": name,
                "swcom": _to_swcom_from_fn(info),
                "id_ref": str(info.get("id") or ""),
            }
        )
    edges = [{"source": s, "target": t} for s, t in sorted(edges_set)]
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "focus": focus,
            "depth": depth,
            "include_external": bool(include_external),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }


def _extract_dependency_map_payload(
    sections: Dict[str, Any],
    level: str = "module",
) -> Dict[str, Any]:
    call_map = sections.get("call_map") if isinstance(sections.get("call_map"), dict) else {}
    details_by_name = (
        sections.get("function_details_by_name")
        if isinstance(sections.get("function_details_by_name"), dict)
        else {}
    )
    level_norm = str(level or "module").strip().lower()
    if level_norm not in {"module", "function"}:
        level_norm = "module"

    def fn_bucket(name: str) -> str:
        info = details_by_name.get(str(name).lower()) if isinstance(details_by_name, dict) else None
        if not isinstance(info, dict):
            return "UNMAPPED"
        return _to_swcom_from_fn(info)

    nodes_set: set[str] = set()
    edges_set: set[Tuple[str, str]] = set()
    for caller, vals in call_map.items():
        c = str(caller or "").strip()
        if not c:
            continue
        c_key = c if level_norm == "function" else fn_bucket(c)
        nodes_set.add(c_key)
        if not isinstance(vals, list):
            continue
        for v in vals:
            callee = str(v or "").strip()
            if not callee:
                continue
            t_key = callee if level_norm == "function" else fn_bucket(callee)
            nodes_set.add(t_key)
            if c_key != t_key:
                edges_set.add((c_key, t_key))
    nodes = [{"id": n, "label": n} for n in sorted(nodes_set)]
    edges = [{"source": s, "target": t} for s, t in sorted(edges_set)]
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {"level": level_norm, "node_count": len(nodes), "edge_count": len(edges)},
    }


def _parse_signature_params(signature: str) -> List[Dict[str, str]]:
    sig = str(signature or "").strip()
    m = re.search(r"\((.*)\)", sig)
    if not m:
        return []
    inner = str(m.group(1) or "").strip()
    if not inner or inner.lower() == "void":
        return []
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    out: List[Dict[str, str]] = []
    for p in parts:
        token = re.sub(r"\s+", " ", p).strip()
        pm = re.match(r"(.+?)\s+([A-Za-z_]\w*(?:\s*\[[^\]]*\])?)$", token)
        if pm:
            out.append({"type": pm.group(1).strip(), "name": pm.group(2).strip()})
        else:
            out.append({"type": token, "name": ""})
    return out


def _build_test_cases_for_signature(function_name: str, signature: str, strategy: str, max_cases: int) -> List[Dict[str, Any]]:
    params = _parse_signature_params(signature)
    if not params:
        return [
            {
                "name": "basic_no_param",
                "inputs": {},
                "expected": "returns without crash",
                "rationale": "No parameter function baseline",
            }
        ]
    strategy_norm = str(strategy or "boundary").strip().lower()
    cases: List[Dict[str, Any]] = []
    for idx, p in enumerate(params, start=1):
        ptype = str(p.get("type") or "").lower()
        pname = str(p.get("name") or f"arg{idx}").strip() or f"arg{idx}"
        if strategy_norm in {"boundary", "stub"}:
            if "*" in ptype:
                seeds = ["NULL", "VALID_PTR"]
            elif "bool" in ptype:
                seeds = [0, 1]
            elif any(t in ptype for t in ["uint", "int", "short", "long", "size_t"]):
                seeds = [0, 1, -1, 2147483647]
            else:
                seeds = [0, 1]
        else:
            seeds = [0, 1]
        for s in seeds:
            cases.append(
                {
                    "name": f"{pname}_case_{len(cases) + 1}",
                    "inputs": {pname: s},
                    "expected": "check return value / output state",
                    "rationale": f"{strategy_norm} input for {pname}",
                }
            )
            if len(cases) >= max_cases:
                break
        if len(cases) >= max_cases:
            break
    if not cases:
        cases.append(
            {
                "name": "basic_case",
                "inputs": {},
                "expected": "check return value",
                "rationale": "fallback",
            }
        )
    return cases[:max_cases]


def _get_uds_view_payload_cached(
    docx_path: Path,
    accuracy_path: Optional[Path] = None,
    quality_gate_path: Optional[Path] = None,
) -> Dict[str, Any]:
    sidecar_path = docx_path.with_suffix(".payload.json")
    key = str(docx_path.resolve())
    stamp = (
        _mtime_or_zero(docx_path),
        _mtime_or_zero(accuracy_path),
        _mtime_or_zero(quality_gate_path),
        _mtime_or_zero(sidecar_path),
    )
    with _uds_view_cache_lock:
        item = _uds_view_cache.get(key)
        if item and item.get("stamp") == stamp and isinstance(item.get("payload"), dict):
            return deepcopy(item["payload"])
    payload = build_uds_view_payload(
        str(docx_path),
        str(accuracy_path) if accuracy_path and accuracy_path.exists() else "",
        str(quality_gate_path) if quality_gate_path and quality_gate_path.exists() else "",
    )
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception:
            sidecar = {}
        sidecar_summary = sidecar.get("summary")
        if isinstance(sidecar_summary, dict):
            payload_summary = payload.get("summary")
            if not isinstance(payload_summary, dict):
                payload_summary = {}
            payload_summary.update(sidecar_summary)
            payload["summary"] = payload_summary
        details = sidecar.get("function_details")
        if isinstance(details, dict):
            by_id: Dict[str, Dict[str, Any]] = {}
            by_name: Dict[str, Dict[str, Any]] = {}
            for _, info in details.items():
                if not isinstance(info, dict):
                    continue
                fid = str(info.get("id") or "").strip()
                name = str(info.get("name") or "").strip().lower()
                if fid:
                    by_id[fid] = info
                if name:
                    by_name[name] = info
            for fn in payload.get("functions", []) or []:
                if not isinstance(fn, dict):
                    continue
                fid = str(fn.get("id") or "").strip()
                name = str(fn.get("name") or "").strip().lower()
                src = by_id.get(fid) or by_name.get(name)
                if not isinstance(src, dict):
                    continue
                for field in (
                    "sds_match_key",
                    "sds_match_mode",
                    "sds_match_scope",
                    "mapping_confidence",
                    "asil_source",
                    "related_source",
                    "description_source",
                ):
                    value = src.get(field)
                    if value not in (None, ""):
                        fn[field] = value
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        payload["summary"] = summary
    if not isinstance(summary.get("mapping"), dict):
        summary["mapping"] = _compute_uds_mapping_summary(payload.get("functions") or [])
    with _uds_view_cache_lock:
        _uds_view_cache[key] = {
            "stamp": stamp,
            "payload": payload,
            "cached_at": time(),
        }
    return deepcopy(payload)


def _slice_page(rows: List[Dict[str, Any]], page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    p = max(1, int(page or 1))
    size = max(1, min(500, int(page_size or 50)))
    total = len(rows)
    start = (p - 1) * size
    end = start + size
    return rows[start:end], total


def _compute_uds_mapping_summary(rows: Any) -> Dict[str, Any]:
    items = []
    if isinstance(rows, dict):
        items = [v for v in rows.values() if isinstance(v, dict)]
    elif isinstance(rows, list):
        items = [v for v in rows if isinstance(v, dict)]
    total = len(items)
    direct = fallback = other = unmapped = 0
    residual_tbd = []
    for info in items:
        scope = str(info.get("sds_match_scope") or "").strip().lower()
        if scope == "function":
            direct += 1
        elif scope == "swcom":
            fallback += 1
        elif scope:
            other += 1
        else:
            unmapped += 1
        asil = str(info.get("asil") or "").strip().upper()
        if asil == "TBD":
            related = str(info.get("related") or "").strip().upper()
            has_related = bool(related and related not in {"TBD", "N/A", "-"})
            match_key = str(info.get("sds_match_key") or "").strip()
            if not match_key and not has_related:
                reason = "No SDS match and no related requirement"
            elif not match_key:
                reason = "No SDS match"
            elif not has_related:
                reason = "No related requirement"
            else:
                reason = "Mapping pending"
            residual_tbd.append(
                {
                    "id": str(info.get("id") or "").strip(),
                    "name": str(info.get("name") or "").strip(),
                    "sds_match_key": match_key,
                    "sds_match_mode": str(info.get("sds_match_mode") or "").strip(),
                    "sds_match_scope": str(info.get("sds_match_scope") or "").strip(),
                    "reason": reason,
                }
            )
    return {
        "total": total,
        "direct": direct,
        "fallback": fallback,
        "other": other,
        "unmapped": unmapped,
        "residual_tbd_count": len(residual_tbd),
        "residual_tbd_rows": residual_tbd[:20],
    }


def _write_residual_tbd_report(out_path: Path, summary_mapping: Dict[str, Any]) -> Optional[Path]:
    try:
        if not isinstance(summary_mapping, dict):
            return None
        rows = summary_mapping.get("residual_tbd_rows") or []
        if not rows:
            return None
        report_path = out_path.with_suffix(".residual_tbd.md")
        lines = [
            "# Residual TBD Trace Report",
            "",
            f"- Docx: `{out_path}`",
            f"- Residual TBD Count: `{summary_mapping.get('residual_tbd_count', 0)}`",
            "",
            "## Rows",
            "",
        ]
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append(f"- `{row.get('id') or '-'}` {row.get('name') or '-'}")
            lines.append(f"  - reason: `{row.get('reason') or '-'}`")
            lines.append(f"  - sds_match_key: `{row.get('sds_match_key') or '-'}`")
            lines.append(f"  - sds_match_mode: `{row.get('sds_match_mode') or '-'}`")
            lines.append(f"  - sds_match_scope: `{row.get('sds_match_scope') or '-'}`")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path
    except Exception:
        return None


def _apply_uds_view_filters(
    payload: Dict[str, Any],
    *,
    q: str = "",
    swcom: str = "all",
    asil: str = "all",
    trace_q: str = "",
    page: int = 1,
    page_size: int = 50,
    trace_page: int = 1,
    trace_page_size: int = 100,
) -> Dict[str, Any]:
    functions = payload.get("functions") if isinstance(payload.get("functions"), list) else []
    traceability = payload.get("traceability") if isinstance(payload.get("traceability"), list) else []
    q_l = str(q or "").strip().lower()
    swcom_l = str(swcom or "all").strip().lower()
    asil_l = str(asil or "all").strip().lower()
    trace_q_l = str(trace_q or "").strip().lower()

    filtered_functions: List[Dict[str, Any]] = []
    for fn in functions:
        if not isinstance(fn, dict):
            continue
        fn_swcom = str(fn.get("swcom") or "").strip().lower()
        fn_asil = str(fn.get("asil") or "").strip().lower()
        if swcom_l != "all" and fn_swcom != swcom_l:
            continue
        if asil_l != "all" and fn_asil != asil_l:
            continue
        if q_l:
            blob = " ".join(
                [
                    str(fn.get("id") or ""),
                    str(fn.get("name") or ""),
                    str(fn.get("prototype") or ""),
                    str(fn.get("description") or ""),
                ]
            ).lower()
            if q_l not in blob:
                continue
        filtered_functions.append(fn)
    paged_functions, fn_total = _slice_page(filtered_functions, page, page_size)

    filtered_trace: List[Dict[str, Any]] = []
    for row in traceability:
        if not isinstance(row, dict):
            continue
        row_swcom = str(row.get("swcom") or "").strip().lower()
        if swcom_l != "all" and row_swcom != swcom_l:
            continue
        if trace_q_l:
            blob = " ".join(
                [
                    str(row.get("requirement_id") or ""),
                    str(row.get("function_id") or ""),
                    str(row.get("function_name") or ""),
                    str(row.get("swcom") or ""),
                ]
            ).lower()
            if trace_q_l not in blob:
                continue
        filtered_trace.append(row)
    paged_trace, trace_total = _slice_page(filtered_trace, trace_page, trace_page_size)

    out = dict(payload)
    out["functions"] = paged_functions
    out["traceability"] = paged_trace
    out["meta"] = {
        "functions_total": fn_total,
        "traceability_total": trace_total,
        "page": max(1, int(page or 1)),
        "page_size": max(1, min(500, int(page_size or 50))),
        "trace_page": max(1, int(trace_page or 1)),
        "trace_page_size": max(1, min(500, int(trace_page_size or 100))),
        "server_filtered": True,
    }
    return out


def _generate_docx_with_retry(
    tpl: Optional[str],
    uds_payload: Dict[str, Any],
    out_path: Path,
    retries: int = 3,
) -> None:
    def _build_docx_retry_payload(base_payload: Dict[str, Any], level: int) -> Dict[str, Any]:
        payload = deepcopy(base_payload or {})
        if level >= 1:
            payload.pop("ai_sections", None)
            payload["logic_max_children"] = min(int(payload.get("logic_max_children") or 3), 2)
            payload["logic_max_grandchildren"] = min(int(payload.get("logic_max_grandchildren") or 2), 1)
            payload["logic_max_depth"] = min(int(payload.get("logic_max_depth") or 3), 2)
        if level >= 2:
            payload["logic_diagrams"] = []
            payload["software_unit_design"] = str(payload.get("software_unit_design") or "")[:60000]
            payload["requirements"] = str(payload.get("requirements") or "")[:80000]
        return payload

    def _run_docx_in_subprocess(
        stage_payload: Dict[str, Any],
        *,
        stage: str,
        timeout_seconds: int,
    ) -> Tuple[bool, str]:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="uds_payload_", suffix=".json", dir=str(out_path.parent))
        payload_file = Path(temp_path)
        try:
            os.close(fd)
        except Exception:
            pass
        checkpoint = out_path.with_suffix(".docx.stage.json")
        try:
            payload_file.write_text(json.dumps(stage_payload, ensure_ascii=False), encoding="utf-8")
            checkpoint.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "started",
                        "timeout_seconds": timeout_seconds,
                        "started_at": datetime.now().isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            inline = (
                "import json,sys,report_generator as rg;"
                "tpl=sys.argv[1] or None; p=sys.argv[2]; out=sys.argv[3];"
                "payload=json.loads(open(p,'r',encoding='utf-8').read());"
                "ai_cfg=payload.pop('_gen_ai_config',None);"
                "rg.generate_uds_docx(tpl,payload,out,ai_cfg);"
                "print('OK')"
            )
            run = subprocess.run(
                [sys.executable, "-c", inline, str(tpl or ""), str(payload_file), str(out_path)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            if run.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                checkpoint.write_text(
                    json.dumps(
                        {
                            "stage": stage,
                            "status": "success",
                            "ended_at": datetime.now().isoformat(timespec="seconds"),
                            "stdout_tail": (run.stdout or "")[-1000:],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return True, ""
            err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-2000:]
            checkpoint.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "failed",
                        "returncode": run.returncode,
                        "ended_at": datetime.now().isoformat(timespec="seconds"),
                        "error_tail": err,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return False, err or f"returncode={run.returncode}"
        except subprocess.TimeoutExpired:
            checkpoint.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "timeout",
                        "ended_at": datetime.now().isoformat(timespec="seconds"),
                        "timeout_seconds": timeout_seconds,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return False, f"timeout({timeout_seconds}s)"
        except Exception as exc:
            checkpoint.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "exception",
                        "ended_at": datetime.now().isoformat(timespec="seconds"),
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return False, str(exc)
        finally:
            try:
                payload_file.unlink(missing_ok=True)
            except Exception:
                pass

    stages = getattr(config, "UDS_DOCX_RETRY_STAGES", [("full", 0, 2400), ("degraded_ai_off", 1, 1800), ("degraded_light", 2, 900)])
    max_retries = max(1, int(retries))
    selected = stages[:max_retries] if max_retries <= len(stages) else stages
    last_error = ""
    errors_log: List[str] = []
    for stage, level, timeout_sec in selected:
        _api_logger.info("[UDS_DOCX] stage=%s level=%s timeout=%ds start", stage, level, timeout_sec)
        ok, err = _run_docx_in_subprocess(
            _build_docx_retry_payload(uds_payload, level),
            stage=stage,
            timeout_seconds=timeout_sec,
        )
        if ok:
            _api_logger.info("[UDS_DOCX] stage=%s SUCCESS", stage)
            return
        last_error = err
        errors_log.append(f"[stage={stage}] {err[:500]}")
        _api_logger.error("[UDS_DOCX] stage=%s FAILED: %s", stage, err[:300])
    full_log = "\n".join(errors_log)
    raise RuntimeError(f"DOCX generation failed after {len(selected)} retries:\n{full_log}")


def _run_impact_analysis_for_uds(source_root_path: Optional[Path], changed_files_raw: str) -> Optional[Path]:
    changed_files = str(changed_files_raw or "").strip()
    if not source_root_path or not source_root_path.exists() or not changed_files:
        return None
    out_dir = repo_root / "reports" / "uds"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "impact_analysis.md"
    cmd = [
        sys.executable,
        str(repo_root / "tools" / "impact_analysis.py"),
        "--source-root",
        str(source_root_path),
        "--changed",
        changed_files,
        "--out",
        str(out_path),
    ]
    try:
        run = subprocess.run(
            cmd,
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if run.returncode == 0 and out_path.exists():
            return out_path
        err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-4000:]
    except Exception as exc:
        err = str(exc)
    # Always emit a report file for changed-unit runs so downstream steps
    # can rely on a stable artifact path.
    lines = [
        "# Impact Analysis Report",
        "",
        f"- Source root: `{source_root_path}`",
        f"- Changed files: `{changed_files}`",
        "- Status: `failed`",
        "",
        "## Error",
        f"- {err or 'unknown error'}",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _uds_generate_from_paths(
    *,
    job_url: str,
    cache_root: str,
    build_selector: str,
    template_path: str,
    source_root: str,
    source_only: bool,
    req_file_paths: List[Path],
    note_file_paths: List[Path],
    logic_file_paths: List[Path],
    req_paths: List[str],
    logic_source: str = "",
    logic_max_children: Optional[int] = None,
    logic_max_grandchildren: Optional[int] = None,
    logic_max_depth: Optional[int] = None,
    globals_format_order: str = "",
    globals_format_sep: str = "",
    globals_format_with_labels: bool = True,
    ai_enable: bool = False,
    ai_example_text: str = "",
    ai_detailed: bool = True,
    rag_top_k: Optional[int] = None,
    rag_categories: Optional[List[str]] = None,
    progress_cb: Optional[Any] = None,
    component_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    def _progress(stage: str, percent: int, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if not progress_cb:
            return
        payload = {"stage": stage, "percent": percent, "message": message}
        if extra:
            payload.update(extra)
        progress_cb(stage, payload)

    build_root = _resolve_cached_build_root(job_url, cache_root, build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    summary = build_report_summary(report_dir, project_root=repo_root)

    _progress("notes", 10, "추가 문서 파싱")
    notes: List[str] = []
    for p in note_file_paths:
        try:
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if text:
            notes.append(text.strip())

    _progress("requirements", 25, "요구사항 문서 파싱")
    req_texts: List[str] = []
    req_map: Dict[str, Any] = {}
    req_doc_paths: List[str] = []
    for p in req_file_paths:
        try:
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if p.suffix.lower() == ".docx":
            req_doc_paths.append(str(p))
        if text:
            req_texts.append(text.strip())
    for path_str in req_paths:
        try:
            p = Path(path_str).expanduser().resolve()
            if not p.exists() or not p.is_file():
                continue
            if not _is_allowed_req_doc(p):
                continue
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if text:
            req_texts.append(text.strip())
            if p.suffix.lower() == ".docx":
                req_doc_paths.append(str(p))

    _progress("source", 45, "소스/섹션 분석")
    jenkins_meta = summary.get("jenkins") if isinstance(summary, dict) else {}
    if not isinstance(jenkins_meta, dict):
        jenkins_meta = {}
    summary_text = summary.get("summary_text", "") if isinstance(summary, dict) else ""
    source_sections: Dict[str, str] = {}
    source_root_path = Path(source_root).resolve() if source_root else None
    if source_root_path and source_root_path.exists():
        source_sections = generate_uds_source_sections(
            str(source_root_path),
            component_map=component_map if component_map else None,
        )

    _progress("requirements_build", 60, "요구사항 정리")
    req_from_docs = generate_uds_requirements_from_docs(req_texts) if req_texts else ""
    req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}

    _progress("logic", 70, "Logic Diagram 첨부")
    logic_items: List[Dict[str, Any]] = []
    if logic_file_paths:
        logic_dir = _jenkins_logic_dir(cache_root)
        logic_dir.mkdir(parents=True, exist_ok=True)
        ts_logic = datetime.now().strftime("%Y%m%d_%H%M%S")
        for p in logic_file_paths:
            if not p or not p.exists():
                continue
            suffix = p.suffix.lower() or ".png"
            safe_name = "".join(c for c in p.stem if c.isalnum() or c in ("-", "_"))
            out_name = f"logic_{safe_name}_{ts_logic}{suffix}"
            out_path = logic_dir / out_name
            try:
                out_path.write_bytes(p.read_bytes())
            except Exception:
                continue
            logic_items.append(
                {
                    "title": p.name,
                    "path": str(out_path),
                    "url": f"/api/jenkins/uds/logic?job_url={job_url}&cache_root={cache_root}&filename={out_name}",
                }
            )
    if not logic_items and logic_source:
        try:
            logic_items = generate_uds_logic_items(
                req_texts,
                logic_source,
                source_root=str(source_root_path) if source_root_path else "",
            )
        except Exception:
            logic_items = []

    ai_sections = None
    if ai_enable:
        _progress("ai", 80, "AI 섹션 생성")
        try:
            rag_snippets: List[Dict[str, Any]] = []
            try:
                report_dir = _detect_reports_dir(build_root)
                kb = get_kb(report_dir)
                rag_query = " ".join(req_texts).strip()[:2000]
                if not rag_query:
                    rag_query = (source_sections.get("overview", "") or "").strip()[:2000]
                if rag_query:
                    use_top_k = rag_top_k if rag_top_k and rag_top_k > 0 else int(
                        getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)
                    )
                    use_categories = [str(c).strip() for c in (rag_categories or []) if str(c).strip()]
                    if not use_categories:
                        use_categories = ["uds", "requirements", "code", "vectorcast"]
                    rag_rows = kb.search(
                        rag_query,
                        top_k=use_top_k,
                        categories=use_categories,
                    )
                    for row in rag_rows:
                        rag_snippets.append(
                            {
                                "title": row.get("error_raw") or "",
                                "category": row.get("category") or "",
                                "source_type": "rag",
                                "source_file": row.get("source_file") or "",
                                "excerpt": str(row.get("context") or row.get("fix") or "")[:1200],
                                "score": row.get("score"),
                            }
                        )
            except Exception:
                rag_snippets = []
            ai_sections = generate_uds_ai_sections(
                requirements_text="\n".join(req_texts),
                source_sections=source_sections,
                notes_text="\n".join(notes),
                logic_items=logic_items,
                example_text=ai_example_text,
                detailed=bool(ai_detailed),
                rag_snippets=rag_snippets,
            )
        except Exception:
            ai_sections = None

    _progress("payload", 82, "UDS 페이로드 생성")
    req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}
    req_source = source_sections.get("requirements", "")
    if source_only:
        req_combined = req_source
    elif req_from_docs and req_source:
        req_combined = "\n".join([req_from_docs.strip(), req_source.strip()]).strip()
    else:
        req_combined = req_from_docs or req_source
    globals_order_list = [
        x.strip()
        for x in re.split(r"[,\|;]+", globals_format_order or "")
        if x.strip()
    ]
    uds_payload = {
        "job_url": job_url,
        "build_number": jenkins_meta.get("build_number"),
        "project_name": summary.get("project") if isinstance(summary, dict) else "",
        "summary": summary,
        "overview": summary_text or source_sections.get("overview", ""),
        "requirements": req_combined,
        "interfaces": source_sections.get("interfaces", ""),
        "uds_frames": source_sections.get("uds_frames", ""),
        "notes": "\n".join(notes),
        "logic_diagrams": logic_items,
        "software_unit_design": source_sections.get("software_unit_design", ""),
        "unit_structure": source_sections.get("unit_structure", ""),
        "global_data": source_sections.get("global_data", ""),
        "interface_functions": source_sections.get("interface_functions", ""),
        "internal_functions": source_sections.get("internal_functions", ""),
        "function_table_rows": source_sections.get("function_table_rows", []),
        "global_vars": source_sections.get("global_vars", []),
        "static_vars": source_sections.get("static_vars", []),
        "macro_defs": source_sections.get("macro_defs", []),
        "calibration_params": source_sections.get("calibration_params", []),
        "function_details": source_sections.get("function_details", {}),
        "function_details_by_name": source_sections.get("function_details_by_name", {}),
        "call_map": source_sections.get("call_map", {}),
        "module_map": source_sections.get("module_map", {}),
        "req_map": req_map,
        "globals_info_map": source_sections.get("globals_info_map", {}),
        "common_macros": source_sections.get("common_macros", []),
        "type_defs": source_sections.get("type_defs", []),
        "param_defs": source_sections.get("param_defs", []),
        "version_defs": source_sections.get("version_defs", []),
        "globals_format_order": globals_order_list,
        "globals_format_sep": globals_format_sep,
        "globals_format_with_labels": globals_format_with_labels,
        "call_relation_mode": "code",
        "logic_max_children": logic_max_children,
        "logic_max_grandchildren": logic_max_grandchildren,
        "logic_max_depth": logic_max_depth,
    }
    impact_path = _run_impact_analysis_for_uds(
        source_root_path,
        os.getenv("UDS_CHANGED_FILES", ""),
    )
    if impact_path:
        notes_text = str(uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join([x for x in [notes_text, f"impact:{impact_path.name}"] if x])
    if ai_sections:
        uds_payload["ai_sections"] = ai_sections
    if source_only and source_sections.get("notes"):
        uds_payload["notes"] = (uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join(
            [x for x in [uds_payload["notes"], source_sections.get("notes")] if x]
        )

    _progress("docx", 85, "DOCX 생성")
    job_slug = _job_slug(job_url)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _jenkins_exports_dir(cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"uds_spec_{job_slug}_{ts}.docx"
    tpl = str(template_path).strip() or None
    _generate_docx_with_retry(tpl, uds_payload, out_path)
    summary = uds_payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        uds_payload["summary"] = summary
    summary["mapping"] = _compute_uds_mapping_summary(uds_payload.get("function_details") or {})
    sidecar_path = out_path.with_suffix(".payload.json")
    try:
        sidecar_path.write_text(
            json.dumps(
                {
                    "docx_path": str(out_path),
                    "summary": summary,
                    "function_details": uds_payload.get("function_details") or {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    residual_tbd_path = _write_residual_tbd_report(out_path, summary.get("mapping") or {})
    validation_path = out_path.with_suffix(".validation.md")
    ok_validation, _ = _run_report_with_timeout(
        lambda: generate_uds_validation_report(str(out_path), str(validation_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="validation report",
    )
    if not ok_validation:
        validation_path = None
    accuracy_path = out_path.with_suffix(".accuracy.md")
    src_root = str(source_root_path) if source_root_path else ""
    ok_accuracy, _ = _run_report_with_timeout(
        lambda: generate_called_calling_accuracy_report(
            str(out_path),
            src_root,
            str(accuracy_path),
            relation_mode="code",
        ),
        timeout_seconds=getattr(config, "UDS_ACCURACY_REPORT_TIMEOUT", 300),
        report_name="accuracy report",
    )
    if not ok_accuracy:
        accuracy_path = None
    swcom_context_path = out_path.with_suffix(".swcom_context.md")
    ok_swcom, _ = _run_report_with_timeout(
        lambda: generate_swcom_context_report(str(out_path), str(swcom_context_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="swcom context report",
    )
    if not ok_swcom:
        swcom_context_path = None
    swcom_diff_path = out_path.with_suffix(".swcom_diff.md")
    ref_docx = Path(getattr(config, "UDS_REF_SUDS_PATH", ""))
    if not ref_docx.exists():
        ref_docx = repo_root / "docs" / "(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"
    if ref_docx.exists():
        ok_swcom_diff, _ = _run_report_with_timeout(
            lambda: generate_swcom_context_diff_report(str(ref_docx), str(out_path), str(swcom_diff_path)),
            timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
            report_name="swcom context diff report",
        )
        if not ok_swcom_diff:
            swcom_diff_path = None
    else:
        swcom_diff_path = None
    confidence_path = out_path.with_suffix(".field_confidence.md")
    ok_confidence, _ = _run_report_with_timeout(
        lambda: generate_asil_related_confidence_report(
            uds_payload,
            str(confidence_path),
            str(out_path),
        ),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="ASIL/Related confidence report",
    )
    if not ok_confidence:
        confidence_path = None
    constraints_path = out_path.with_suffix(".constraints.md")
    ok_constraints, _ = _run_report_with_timeout(
        lambda: generate_uds_constraints_report(uds_payload, str(constraints_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="constraints report",
    )
    if not ok_constraints:
        constraints_path = None
    quality_gate_path = out_path.with_suffix(".quality_gate.md")
    ok_quality_gate, _ = _run_report_with_timeout(
        lambda: generate_uds_field_quality_gate_report(str(out_path), str(quality_gate_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="field quality gate report",
    )
    if not ok_quality_gate:
        quality_gate_path = None

    _progress("preview", 92, "미리보기 생성")
    preview_html = generate_uds_preview_html(uds_payload)
    preview_path = out_path.with_suffix(".html")
    preview_path.write_text(preview_html, encoding="utf-8")

    return {
        "ok": True,
        "filename": out_path.name,
        "download_url": f"/api/jenkins/uds/download?job_url={job_url}&cache_root={cache_root}&filename={out_path.name}",
        "preview_url": f"/api/jenkins/uds/preview?job_url={job_url}&cache_root={cache_root}&filename={preview_path.name}",
        "validation_path": str(validation_path) if validation_path else "",
        "accuracy_path": str(accuracy_path) if accuracy_path else "",
        "swcom_context_path": str(swcom_context_path) if swcom_context_path else "",
        "swcom_diff_path": str(swcom_diff_path) if swcom_diff_path else "",
        "confidence_path": str(confidence_path) if confidence_path else "",
        "constraints_path": str(constraints_path) if constraints_path else "",
        "quality_gate_path": str(quality_gate_path) if quality_gate_path else "",
        "impact_path": str(impact_path) if impact_path else "",
        "residual_tbd_report_path": str(residual_tbd_path) if residual_tbd_path else "",
    }
