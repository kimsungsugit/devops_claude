from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from workflow.function_module_map import build_function_module_index


REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGE_DIR = REPO_ROOT / "reports" / "impact_changes"

UDS_COMPARE_FIELDS = [
    "description",
    "inputs",
    "outputs",
    "calls_list",
    "globals_global",
    "globals_static",
    "related",
    "asil",
]


def ensure_change_dir() -> Path:
    CHANGE_DIR.mkdir(parents=True, exist_ok=True)
    return CHANGE_DIR


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _artifact_payload_path(path_text: str) -> Path | None:
    raw = str(path_text or "").strip()
    if not raw:
        return None
    path = Path(raw)
    payload_path = path.with_suffix(".payload.json")
    return payload_path if payload_path.exists() else None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if value is None:
        return ""
    return value


def _build_uds_name_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = payload.get("function_details") if isinstance(payload.get("function_details"), dict) else {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for info in rows.values():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip().lower()
        if not name:
            continue
        by_name[name] = info
    return by_name


def _summarize_uds_entry(info: Dict[str, Any]) -> Dict[str, Any]:
    calls = info.get("calls_list") if isinstance(info.get("calls_list"), list) else []
    globals_global = info.get("globals_global") if isinstance(info.get("globals_global"), list) else []
    globals_static = info.get("globals_static") if isinstance(info.get("globals_static"), list) else []
    outputs = info.get("outputs") if isinstance(info.get("outputs"), list) else []
    return {
        "calls_count": len(calls),
        "globals_count": len(globals_global) + len(globals_static),
        "output_count": len(outputs),
        "related": str(info.get("related") or "").strip(),
        "asil": str(info.get("asil") or "").strip(),
    }


def diff_uds_payload(before_payload: Dict[str, Any], after_payload: Dict[str, Any], function_names: Iterable[str]) -> Dict[str, Any]:
    before_map = _build_uds_name_map(before_payload)
    after_map = _build_uds_name_map(after_payload)
    changed_functions: List[Dict[str, Any]] = []
    for func_name in sorted({str(name or "").strip().lower() for name in function_names if str(name or "").strip()}):
        before_info = before_map.get(func_name)
        after_info = after_map.get(func_name)
        if not before_info and not after_info:
            continue
        if not before_info and after_info:
            changed_functions.append(
                {
                    "name": str(after_info.get("name") or func_name),
                    "fields_changed": ["created"],
                    "before": {},
                    "after": _summarize_uds_entry(after_info),
                }
            )
            continue
        if before_info and not after_info:
            changed_functions.append(
                {
                    "name": str(before_info.get("name") or func_name),
                    "fields_changed": ["removed"],
                    "before": _summarize_uds_entry(before_info),
                    "after": {},
                }
            )
            continue
        fields_changed = [
            field
            for field in UDS_COMPARE_FIELDS
            if _normalize_value(before_info.get(field)) != _normalize_value(after_info.get(field))
        ]
        if not fields_changed:
            continue
        changed_functions.append(
            {
                "name": str(after_info.get("name") or before_info.get("name") or func_name),
                "fields_changed": fields_changed,
                "before": _summarize_uds_entry(before_info),
                "after": _summarize_uds_entry(after_info),
            }
        )
    return {
        "status": "completed" if changed_functions else "unchanged",
        "summary": {"changed_functions": len(changed_functions)},
        "changed_functions": changed_functions,
    }


def _payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_result = payload.get("raw_result") if isinstance(payload.get("raw_result"), dict) else {}
    return {
        "test_case_count": payload.get("test_case_count")
        or raw_result.get("test_case_count")
        or payload.get("summary", {}).get("primary", [{}])[0].get("value", 0),
        "total_sequences": payload.get("total_sequences") or raw_result.get("total_sequences") or 0,
    }


def build_change_log(
    *,
    run_id: str,
    trigger: Dict[str, Any],
    result: Dict[str, Any],
    previous_linked_docs: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    previous_linked_docs = previous_linked_docs or {}
    actions = result.get("actions") if isinstance(result.get("actions"), dict) else {}
    changed_types = result.get("changed_function_types") if isinstance(result.get("changed_function_types"), dict) else {}
    impact = result.get("impact") if isinstance(result.get("impact"), dict) else {}
    docs: Dict[str, Any] = {}

    uds_info = actions.get("uds") if isinstance(actions.get("uds"), dict) else {}
    if uds_info:
        after_payload = _load_json(_artifact_payload_path(uds_info.get("output_path") or "") or Path("_missing_"))
        before_payload = _load_json(_artifact_payload_path(previous_linked_docs.get("uds") or "") or Path("_missing_"))
        if uds_info.get("status") == "completed" and after_payload:
            docs["uds"] = diff_uds_payload(before_payload, after_payload, uds_info.get("functions") or changed_types.keys())
            docs["uds"]["artifact_path"] = str(uds_info.get("output_path") or "")
        else:
            flagged_count = int(uds_info.get("function_count") or 0)
            docs["uds"] = {
                "status": str(uds_info.get("status") or "skipped"),
                "summary": {"changed_functions": flagged_count, "flagged_functions": flagged_count},
                "changed_functions": [{"name": fn, "fields_changed": ["flagged"]} for fn in (uds_info.get("functions") or [])],
                "artifact_path": str(uds_info.get("artifact_path") or uds_info.get("output_path") or ""),
            }

    suts_info = actions.get("suts") if isinstance(actions.get("suts"), dict) else {}
    if suts_info:
        after_payload = _load_json(_artifact_payload_path(suts_info.get("output_path") or "") or Path("_missing_"))
        before_payload = _load_json(_artifact_payload_path(previous_linked_docs.get("suts") or "") or Path("_missing_"))
        after_summary = _payload_summary(after_payload)
        before_summary = _payload_summary(before_payload)
        changed_functions = [
            {"function": name, "change_type": "regenerated"}
            for name in (suts_info.get("functions") or [])
        ]
        docs["suts"] = {
            "status": str(suts_info.get("status") or "skipped"),
            "summary": {
                "changed_functions": len(changed_functions),
                "changed_cases": int(after_summary.get("test_case_count") or 0),
                "changed_sequences": int(after_summary.get("total_sequences") or 0),
                "before_cases": int(before_summary.get("test_case_count") or 0),
                "before_sequences": int(before_summary.get("total_sequences") or 0),
            },
            "changed_cases": changed_functions,
            "artifact_path": str(suts_info.get("output_path") or ""),
            "validation_report_path": str((suts_info.get("result") or {}).get("validation_report_path") or ""),
        }

    sits_info = actions.get("sits") if isinstance(actions.get("sits"), dict) else {}
    if sits_info:
        exec_result = sits_info.get("result") or {}
        after_tc = int(exec_result.get("test_case_count") or sits_info.get("test_case_count") or 0)
        after_sub = int(exec_result.get("total_sub_cases") or sits_info.get("total_sub_cases") or 0)
        before_payload = _load_json(_artifact_payload_path(previous_linked_docs.get("sits") or "") or Path("_missing_"))
        before_tc = int(before_payload.get("test_case_count") or 0)
        before_sub = int(before_payload.get("total_sub_cases") or 0)
        flagged_fn_count = int(sits_info.get("function_count") or 0)
        docs["sits"] = {
            "status": str(sits_info.get("status") or "skipped"),
            "summary": {
                "test_case_count": after_tc,
                "total_sub_cases": after_sub,
                "before_test_case_count": before_tc,
                "before_total_sub_cases": before_sub,
                "delta_cases": after_tc - before_tc,
                "delta_sub_cases": after_sub - before_sub,
                "flagged_functions": flagged_fn_count,
            },
            "flagged_functions": list(sits_info.get("functions") or []),
            "artifact_path": str(sits_info.get("artifact_path") or sits_info.get("output_path") or ""),
            "validation_report_path": str(exec_result.get("validation_report_path") or ""),
        }

    for target in ("sts", "sds"):
        info = actions.get(target) if isinstance(actions.get(target), dict) else {}
        if not info:
            continue
        docs[target] = {
            "status": str(info.get("status") or "skipped"),
            "summary": {"flagged_functions": int(info.get("function_count") or 0)},
            "flagged_functions": list(info.get("functions") or []),
            "artifact_path": str(info.get("artifact_path") or ""),
        }

    summary = {
        "uds_changed_functions": int(docs.get("uds", {}).get("summary", {}).get("changed_functions", 0)),
        "suts_changed_functions": int(docs.get("suts", {}).get("summary", {}).get("changed_functions", 0)),
        "suts_changed_cases": int(docs.get("suts", {}).get("summary", {}).get("changed_cases", 0)),
        "suts_changed_sequences": int(docs.get("suts", {}).get("summary", {}).get("changed_sequences", 0)),
        "sits_test_cases": int(docs.get("sits", {}).get("summary", {}).get("test_case_count", 0)),
        "sits_sub_cases": int(docs.get("sits", {}).get("summary", {}).get("total_sub_cases", 0)),
        "sits_delta_cases": int(docs.get("sits", {}).get("summary", {}).get("delta_cases", 0)),
        "sits_flagged": int(docs.get("sits", {}).get("summary", {}).get("flagged_functions", 0)),
        "sts_flagged": int(docs.get("sts", {}).get("summary", {}).get("flagged_functions", 0)),
        "sds_flagged": int(docs.get("sds", {}).get("summary", {}).get("flagged_functions", 0)),
    }

    return {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "trigger": str(trigger.get("trigger_type") or trigger.get("trigger") or ""),
        "dry_run": bool(result.get("dry_run")),
        "scm_id": str(trigger.get("scm_id") or ""),
        "base_ref": str(trigger.get("base_ref") or ""),
        "changed_files": list(trigger.get("changed_files") or []),
        "changed_functions": dict(sorted(changed_types.items())),
        "impact_counts": {
            "direct": len(impact.get("direct") or []),
            "indirect_1hop": len(impact.get("indirect_1hop") or []),
            "indirect_2hop": len(impact.get("indirect_2hop") or []),
        },
        "summary": summary,
        "documents": docs,
        "artifacts": {
            "uds": str((docs.get("uds") or {}).get("artifact_path") or ""),
            "suts": str((docs.get("suts") or {}).get("artifact_path") or ""),
            "sits": str((docs.get("sits") or {}).get("artifact_path") or ""),
            "sts_review": str((docs.get("sts") or {}).get("artifact_path") or ""),
            "sds_review": str((docs.get("sds") or {}).get("artifact_path") or ""),
        },
    }


def write_change_log(change_log: Dict[str, Any]) -> Path:
    ensure_change_dir()
    run_id = str(change_log.get("run_id") or "").strip() or datetime.now().strftime("impact_%Y%m%d_%H%M%S")
    ts = run_id.replace("impact_", "", 1)
    out = CHANGE_DIR / f"change_{ts}.json"
    _save_json(out, change_log)
    return out


def list_change_logs(scm_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    ensure_change_dir()
    target_scm = str(scm_id or "").strip()
    items: List[Dict[str, Any]] = []
    for path in sorted(CHANGE_DIR.glob("change_*.json"), reverse=True):
        raw = _load_json(path)
        if not raw:
            continue
        if target_scm and str(raw.get("scm_id") or "").strip() != target_scm:
            continue
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        items.append(
            {
                "path": str(path),
                "filename": path.name,
                "run_id": str(raw.get("run_id") or path.stem.replace("change_", "impact_")),
                "timestamp": raw.get("timestamp") or path.stem.replace("change_", ""),
                "trigger": raw.get("trigger") or "",
                "dry_run": bool(raw.get("dry_run")),
                "changed_files": raw.get("changed_files") or [],
                "summary": summary,
            }
        )
        if len(items) >= max(1, int(limit or 20)):
            break
    return items


def load_change_log(run_id: str) -> Dict[str, Any]:
    ensure_change_dir()
    raw_id = str(run_id or "").strip()
    if not raw_id:
        raise KeyError("run_id required")
    candidates = [
        CHANGE_DIR / raw_id,
        CHANGE_DIR / f"{raw_id}.json",
        CHANGE_DIR / f"change_{raw_id}.json",
        CHANGE_DIR / f"change_{raw_id.replace('impact_', '', 1)}.json",
    ]
    for path in candidates:
        if path.exists():
            payload = _load_json(path)
            if payload:
                return payload
    raise KeyError(raw_id)


def list_function_history(scm_id: str, function_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    target = str(function_name or "").strip().lower()
    if not target:
        return []
    items: List[Dict[str, Any]] = []
    for item in list_change_logs(scm_id=scm_id, limit=max(1, int(limit or 20)) * 5):
        try:
            detail = load_change_log(item["run_id"])
        except KeyError:
            continue
        changed = detail.get("changed_functions") if isinstance(detail.get("changed_functions"), dict) else {}
        if target not in {str(name).strip().lower() for name in changed.keys()}:
            continue
        docs = detail.get("documents") if isinstance(detail.get("documents"), dict) else {}
        uds_doc = docs.get("uds") if isinstance(docs.get("uds"), dict) else {}
        suts_doc = docs.get("suts") if isinstance(docs.get("suts"), dict) else {}
        uds_entry = next(
            (row for row in (uds_doc.get("changed_functions") or []) if str(row.get("name") or "").strip().lower() == target),
            None,
        )
        items.append(
            {
                "run_id": detail.get("run_id") or item["run_id"],
                "timestamp": detail.get("timestamp") or item["timestamp"],
                "change_type": changed.get(target, ""),
                "uds_fields_changed": list((uds_entry or {}).get("fields_changed") or []),
                "suts_changed_cases": int(suts_doc.get("summary", {}).get("changed_cases", 0)) if isinstance(suts_doc.get("summary"), dict) else 0,
            }
        )
        if len(items) >= max(1, int(limit or 20)):
            break
    return items


def list_module_history(scm_id: str, module_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    target = str(module_name or "").strip().lower()
    if not target:
        return []
    items: List[Dict[str, Any]] = []
    for item in list_change_logs(scm_id=scm_id, limit=max(1, int(limit or 20)) * 5):
        try:
            detail = load_change_log(item["run_id"])
        except KeyError:
            continue
        changed = detail.get("changed_functions") if isinstance(detail.get("changed_functions"), dict) else {}
        changed_files = detail.get("changed_files") if isinstance(detail.get("changed_files"), list) else []
        module_index = build_function_module_index(changed, changed_files=changed_files)
        matched_functions = [
            name
            for name, info in module_index.items()
            if str(info.get("best_module") or "").strip().lower() == target
        ]
        if not matched_functions:
            continue
        items.append(
            {
                "run_id": detail.get("run_id") or item["run_id"],
                "timestamp": detail.get("timestamp") or item["timestamp"],
                "module_name": module_name,
                "matched_functions": matched_functions,
                "matched_count": len(matched_functions),
                "changed_files": changed_files,
            }
        )
        if len(items) >= max(1, int(limit or 20)):
            break
    return items
