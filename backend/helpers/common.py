"""Common utility functions for the helpers package."""
import re
import os
import sys
import csv
import json
import time
import shutil
import hashlib
import logging
import tempfile
import zipfile
import traceback
import subprocess
import threading
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set
from functools import lru_cache
from time import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

try:
    from fastapi import HTTPException, UploadFile
except ImportError:
    HTTPException = Exception
    UploadFile = None  # type: ignore[assignment,misc]

try:
    from backend.schemas import JenkinsPublishRequest
except ImportError:
    JenkinsPublishRequest = None  # type: ignore[assignment,misc]

import config
from backend.state import (
    jenkins_progress_lock as _jenkins_progress_lock,
    jenkins_progress as _jenkins_progress,
    jenkins_progress_latest as _jenkins_progress_latest,
)

_logger = logging.getLogger("devops_api")
_api_logger = _logger

repo_root = Path(__file__).resolve().parents[2]

SETTINGS_FILE = Path.home() / ".devops_gui_profiles.json"



def _split_signature_params(inner: str) -> List[str]:
    """Split a C function parameter list into individual parameter tokens,
    respecting nested parentheses and brackets."""
    buf: List[str] = []
    cur: List[str] = []
    paren = 0
    bracket = 0
    for ch in str(inner or ""):
        if ch == "," and paren == 0 and bracket == 0:
            token = "".join(cur).strip()
            if token:
                buf.append(token)
            cur = []
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket = max(0, bracket - 1)
        cur.append(ch)
    token = "".join(cur).strip()
    if token:
        buf.append(token)
    return buf


def _extract_param_name_simple(token: str) -> str:
    """Extract parameter name from a C parameter declaration token."""
    t = str(token or "").strip()
    if not t:
        return ""
    m_fp = re.search(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)", t)
    if m_fp:
        return m_fp.group(1)
    m_arr = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])\s*$", t)
    if m_arr:
        return m_arr.group(1)
    m = re.search(r"([A-Za-z_]\w*)\s*$", t)
    return m.group(1) if m else ""


def _mtime_or_zero(path: Optional[Path]) -> float:
    try:
        if path and path.exists():
            return float(path.stat().st_mtime)
    except Exception:
        pass
    return 0.0


def _has_meaningful_value(value: Any) -> bool:
    if isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
        return len(items) > 0
    text = str(value or "").strip()
    if not text:
        return False
    return text.upper() not in {"N/A", "TBD", "-"}


def _normalize_field_source(value: Any) -> str:
    src = str(value or "").strip().lower()
    if src in {"comment", "sds", "srs", "reference", "rule", "inference"}:
        return src
    return "inference"


def _has_trace_token(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(re.search(r"\b(SwCom_\d+|SwFn_\d+|SwSTR_\d+|SwST_\d+)\b", text, flags=re.I))


def _is_trusted_source_for_field(info: Dict[str, Any], field_name: str) -> bool:
    src = _normalize_field_source((info or {}).get(f"{field_name}_source"))
    if src in {"comment", "sds", "srs", "reference"}:
        return True
    if src != "rule":
        return False
    # Deterministic rule-based mapping is accepted as trusted for traceability fields.
    if field_name == "related":
        return _has_trace_token((info or {}).get("related") or (info or {}).get("related_id") or (info or {}).get("related_ids"))
    if field_name == "asil":
        asil = _normalize_asil_simple((info or {}).get("asil"))
        fn_id = str((info or {}).get("id") or "").strip()
        return bool(asil) and bool(re.search(r"\bSwUFn_\d+\b", fn_id, flags=re.I))
    return False


def _normalize_symbol_simple(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(name or "").strip().lower())


def _compact_symbol_simple(name: str) -> str:
    return _normalize_symbol_simple(name).replace("_", "")


def _normalize_asil_simple(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"N/A", "TBD", "-"}:
        return ""
    raw = raw.replace("ASIL-", "").replace("ASIL", "").strip()
    if raw in {"A", "B", "C", "D", "QM"}:
        return raw
    return ""


def _build_excel_artifact_summary(artifact_type: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    kind = str(artifact_type or "").strip().lower()
    quality = payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {}
    trace = payload.get("trace_coverage") if isinstance(payload.get("trace_coverage"), dict) else {}
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    warnings = validation.get("warnings") if isinstance(validation.get("warnings"), list) else []
    primary: List[Dict[str, Any]] = []
    secondary: List[Dict[str, Any]] = []

    if kind == "sts":
        primary = [
            {"key": "test_case_count", "label": "Test Cases", "value": int(payload.get("test_case_count") or 0)},
            {"key": "covered_reqs", "label": "Covered Reqs", "value": int(trace.get("covered_reqs") or 0)},
            {"key": "coverage_pct", "label": "Coverage", "value": float(trace.get("pct") or 0), "unit": "%"},
        ]
        secondary = [
            {"key": "complete_test_cases", "label": "Complete TCs", "value": int(quality.get("complete_test_cases") or 0)},
            {"key": "safety_test_cases", "label": "Safety TCs", "value": int(quality.get("safety_test_cases") or 0)},
            {"key": "elapsed_seconds", "label": "Elapsed", "value": float(payload.get("elapsed_seconds") or 0), "unit": "s"},
        ]
    elif kind == "suts":
        primary = [
            {"key": "test_case_count", "label": "Test Cases", "value": int(payload.get("test_case_count") or 0)},
            {"key": "total_sequences", "label": "Sequences", "value": int(payload.get("total_sequences") or 0)},
            {"key": "avg_sequences_per_tc", "label": "Avg Seq/TC", "value": float(quality.get("avg_sequences_per_tc") or 0)},
        ]
        secondary = [
            {"key": "total_input_vars", "label": "Input Vars", "value": int(quality.get("total_input_vars") or 0)},
            {"key": "total_output_vars", "label": "Output Vars", "value": int(quality.get("total_output_vars") or 0)},
            {"key": "elapsed_seconds", "label": "Elapsed", "value": float(payload.get("elapsed_seconds") or 0), "unit": "s"},
        ]
    elif kind == "sits":
        tc_count = int(payload.get("test_case_count") or 0)
        sub_count = int(payload.get("total_sub_cases") or 0)
        avg_sub = round(sub_count / tc_count, 1) if tc_count else 0.0
        # flow_count: from validation stats or direct field
        flow_count = int(
            payload.get("flow_count")
            or (payload.get("validation") or {}).get("stats", {}).get("flow_count")
            or tc_count  # fallback: 1 flow per ITC
        )
        # covered_reqs: from trace_coverage, or quality_report.with_related_count
        covered_reqs = int(
            trace.get("covered_reqs")
            or quality.get("with_related_count")
            or 0
        )
        primary = [
            {"key": "test_case_count", "label": "Test Cases", "value": tc_count},
            {"key": "total_sub_cases", "label": "Sub-cases", "value": sub_count},
            {"key": "avg_sub_per_tc", "label": "Avg Sub/TC", "value": avg_sub},
        ]
        secondary = [
            {"key": "flow_count", "label": "Flows", "value": flow_count},
            {"key": "covered_reqs", "label": "Covered Reqs", "value": covered_reqs},
            {"key": "elapsed_seconds", "label": "Elapsed", "value": float(payload.get("elapsed_seconds") or 0), "unit": "s"},
        ]
    return {
        "artifact_type": kind,
        "ok": bool(payload.get("ok", True)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "primary": primary,
        "secondary": secondary,
        "validation": {
            "valid": bool(validation.get("valid", False)) if validation else False,
            "issue_count": len(issues),
            "warning_count": len(warnings),
        },
    }


def _build_excel_artifact_payload(
    artifact_type: str,
    result: Optional[Dict[str, Any]] = None,
    *,
    output_path: str = "",
    filename: str = "",
    download_url: str = "",
    preview_url: str = "",
) -> Dict[str, Any]:
    payload = dict(result or {})
    summary = _build_excel_artifact_summary(artifact_type, payload)
    return {
        "artifact_type": str(artifact_type or "").strip().lower(),
        "filename": str(filename or payload.get("filename") or "").strip(),
        "output_path": str(output_path or payload.get("output_path") or "").strip(),
        "download_url": str(download_url or payload.get("download_url") or "").strip(),
        "preview_url": str(preview_url or payload.get("preview_url") or "").strip(),
        "validation_report_path": str(payload.get("validation_report_path") or "").strip(),
        "residual_report_path": str(payload.get("residual_report_path") or "").strip(),
        "summary": summary,
        "quality_report": payload.get("quality_report", {}),
        "trace_coverage": payload.get("trace_coverage", {}),
        "validation": payload.get("validation", {}),
        "raw_result": payload,
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _write_excel_artifact_sidecar(out_path: Path, artifact_type: str, payload: Dict[str, Any]) -> Optional[Path]:
    try:
        sidecar = out_path.with_suffix(".payload.json")
        data = _json_safe(payload if isinstance(payload, dict) else {})
        if not isinstance(data.get("summary"), dict):
            data["summary"] = _build_excel_artifact_summary(artifact_type, data.get("raw_result") or data)
        sidecar.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return sidecar
    except Exception as exc:
        _logger.warning("excel payload sidecar write skipped: %s", exc)
        return None


def _read_excel_artifact_sidecar(file_path: Path) -> Dict[str, Any]:
    sidecar = file_path.with_suffix(".payload.json")
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _infer_related_id_simple(info: Dict[str, Any]) -> str:
    if not isinstance(info, dict):
        return ""
    candidates = [
        info.get("related"),
        info.get("related_id"),
        info.get("related_ids"),
        info.get("swcom"),
        info.get("id"),
        info.get("partition"),
    ]
    for cand in candidates:
        text = str(cand or "").strip()
        if not text or text.upper() in {"N/A", "TBD", "-"}:
            continue
        m = re.search(r"\b(SwCom_\d+|SwFn_\d+|SwUFn_\d+|SwSTR_\d+|SwST_\d+)\b", text, flags=re.I)
        if m:
            token = str(m.group(1) or "").strip()
            if token.lower().startswith("swufn_"):
                token = "SwFn_" + token.split("_", 1)[-1]
            token = token.replace("swcom", "SwCom")
            token = token.replace("swfn", "SwFn")
            token = token.replace("swstr", "SwSTR")
            token = token.replace("swst", "SwST")
            return token
        return text
    return ""


def _parse_signature_params_simple(signature: str) -> List[str]:
    sig = str(signature or "").strip()
    m = re.search(r"\((.*)\)", sig)
    if not m:
        return []
    inner = str(m.group(1) or "").strip()
    if not inner or inner.lower() == "void":
        # Explicitly mark no-input signatures as documented.
        return ["[IN] (none)"]
    parts = _split_signature_params(inner)
    out: List[str] = []
    for p in parts:
        token = re.sub(r"\s+", " ", p).strip()
        token = re.sub(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)", r"* \1", token)
        token = re.sub(r"\s*\[\s*([^\]]*)\s*\]\s*$", r"[\1]", token)
        if token:
            out.append(f"[IN] {token}")
    return out


def _parse_signature_outputs_simple(signature: str) -> List[str]:
    sig = str(signature or "").strip()
    if not sig:
        return []
    head = sig.split("(", 1)[0].strip()
    if not head:
        return []
    pieces = [x for x in re.split(r"\s+", head) if x]
    if not pieces:
        return []
    ret = " ".join(pieces[:-1]) if len(pieces) >= 2 else pieces[0]
    ret = ret.strip()
    outputs: List[str] = []
    if ret and ret.lower() != "void":
        outputs.append(f"[OUT] return {ret}")
    m = re.search(r"\((.*)\)", sig)
    inner = str(m.group(1) if m else "").strip()
    if inner and inner.lower() != "void":
        for raw_param in _split_signature_params(inner):
            p = re.sub(r"\s+", " ", str(raw_param or "").strip())
            pname = _extract_param_name_simple(p)
            pl = p.lower()
            # Non-const pointer/array parameters are treated as potential outputs.
            if ("*" in p or "[" in p) and ("const " not in pl) and pname:
                outputs.append(f"[OUT] {pname}")
    deduped = list(dict.fromkeys(outputs))
    if not deduped:
        # Explicitly mark no-output signatures as documented.
        deduped = ["[OUT] (none)"]
    return deduped


def _run_report_with_timeout(
    fn,
    *,
    timeout_seconds: int,
    report_name: str,
) -> Tuple[bool, str]:
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(fn)
        future.result(timeout=timeout_seconds)
        ex.shutdown(wait=True, cancel_futures=False)
        return True, ""
    except FuturesTimeoutError:
        ex.shutdown(wait=False, cancel_futures=True)
        msg = f"{report_name} timeout ({timeout_seconds}s)"
        _api_logger.info("[UDS_REPORT] %s", msg)
        return False, msg
    except Exception as exc:
        ex.shutdown(wait=False, cancel_futures=True)
        tb = traceback.format_exc()
        msg = f"{report_name} error: {exc}"
        _api_logger.error("[UDS_REPORT] %s\n%s", msg, tb)
        return False, msg


def _progress_key(action: str, job_url: str, build_selector: str, job_id: str = "") -> str:
    return f"{action}::{(job_url or '').strip()}::{(build_selector or '').strip()}::{job_id or ''}"


def _set_progress(
    action: str,
    job_url: str,
    build_selector: str,
    payload: Dict[str, Any],
    job_id: str = "",
) -> None:
    key = _progress_key(action, job_url, build_selector, job_id)
    with _jenkins_progress_lock:
        now = datetime.now().isoformat(timespec="seconds")
        prev = _jenkins_progress.get(key) or {}
        merged = {**prev, **payload, "updated_at": now}
        if "started_at" not in merged:
            merged["started_at"] = now
        if job_id:
            merged["job_id"] = job_id
            latest_key = _progress_key(action, job_url, build_selector)
            _jenkins_progress_latest[latest_key] = job_id
        _jenkins_progress[key] = merged


def _get_progress(action: str, job_url: str, build_selector: str, job_id: str = "") -> Dict[str, Any]:
    key = _progress_key(action, job_url, build_selector, job_id)
    with _jenkins_progress_lock:
        data = _jenkins_progress.get(key)
        if data:
            return dict(data)
        if not job_id:
            latest_key = _progress_key(action, job_url, build_selector)
            latest_id = _jenkins_progress_latest.get(latest_key, "")
            if latest_id:
                fallback_key = _progress_key(action, job_url, build_selector, latest_id)
                return dict(_jenkins_progress.get(fallback_key) or {})
        return {}


def _parse_path_list(raw: str) -> List[str]:
    raw = str(raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
    parts = [x.strip() for x in re.split(r"[\n,;]+", raw) if x.strip()]
    return parts


def _is_allowed_req_doc(path: Path) -> bool:
    return path.suffix.lower() in {".txt", ".md", ".pdf", ".docx"}


def _write_upload_to_temp(f: UploadFile, default_suffix: str) -> Optional[Path]:
    if not f or not f.filename:
        return None
    suffix = Path(f.filename).suffix.lower() or default_suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(f.file.read())
        return Path(tmp.name)


def _parse_component_map_file(path: Path) -> Dict[str, Dict[str, str]]:
    if not path or not path.exists():
        return {}
    suffix = path.suffix.lower()
    rows: List[Dict[str, Any]] = []
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                rows = [r for r in data if isinstance(r, dict)]
        except Exception:
            rows = []
    elif suffix in {".csv", ".tsv", ".txt"}:
        try:
            delimiter = "\t" if suffix == ".tsv" else ","
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                for row in reader:
                    if row:
                        rows.append(row)
        except Exception:
            rows = []
    elif suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd  # type: ignore
        except Exception:
            rows = []
        else:
            try:
                sheets = pd.read_excel(str(path), sheet_name=None)
                for _, df in sheets.items():
                    if df is None:
                        continue
                    for record in df.fillna("").to_dict(orient="records"):
                        rows.append(record)
            except Exception:
                rows = []
    if not rows:
        return {}
    mapping: Dict[str, Dict[str, str]] = {}
    file_keys = {"file", "파일", "파일이름", "file name"}
    comp_keys = {"component", "컴포넌트", "컴포넌트 이름", "component name", "name"}
    struct_keys = {"structure", "구조", "폴더"}
    verify_keys = {"verify", "검증", "검증 대상"}
    for row in rows:
        if not isinstance(row, dict):
            continue
        file_val = ""
        comp_val = ""
        struct_val = ""
        verify_val = ""
        for k, v in row.items():
            key = str(k or "").strip().lower()
            if key in file_keys:
                file_val = str(v or "").strip()
            elif key in comp_keys:
                comp_val = str(v or "").strip()
            elif key in struct_keys:
                struct_val = str(v or "").strip()
            elif key in verify_keys:
                verify_val = str(v or "").strip()
        if not file_val or not comp_val:
            continue
        mapping[file_val] = {
            "component": comp_val,
            "verify": verify_val,
            "structure": struct_val,
        }
        mapping[Path(file_val).stem] = {
            "component": comp_val,
            "verify": verify_val,
            "structure": struct_val,
        }
    return mapping


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _split_csv(val: Any) -> List[str]:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [s.strip() for s in val.split(",") if s.strip()]
    return []


def _safe_int(value: Any, default: int, low: Optional[int] = None, high: Optional[int] = None) -> int:
    try:
        if value is None or value == "":
            n = default
        else:
            n = int(value)
    except (TypeError, ValueError):
        n = default
    if low is not None and n < low:
        n = low
    if high is not None and n > high:
        n = high
    return n


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> int:
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = (dest_dir / info.filename).resolve()
            if not _is_relative_to(target, dest_dir):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count
