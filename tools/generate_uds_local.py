from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
import sys
import time
import logging
import tempfile
import subprocess
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

repo_root = Path(r"D:\Project\devops\260105")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from workflow import rag as ragmod
from workflow.ai import load_oai_config
from workflow.rag import get_kb
import report_generator as rg


def _iter_udf_identifiers(info: dict) -> set[str]:
    used_vars: set[str] = set()
    for field in ("globals_global", "globals_static", "inputs", "outputs"):
        for item in info.get(field) or []:
            text = str(item or "").strip()
            if not text:
                continue
            token = text
            if text.startswith("["):
                parts = text.split()
                token = parts[-1] if parts else text
            token = token.split(".", 1)[0].split("->", 1)[0]
            token = re.sub(r"\s*[:(].*$", "", token).strip(" ,;")
            if token and re.match(r"^[A-Za-z_]\w+$", token):
                used_vars.add(token)
    return used_vars


def _append_evidence(info: dict, field: str, value: str) -> None:
    values = [str(v).strip() for v in (info.get(field) or []) if str(v).strip()]
    if value not in values:
        values.append(value)
    info[field] = values


def _normalize_field_entry(entry: str) -> str:
    text = str(entry or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\[INDIRECT2\]\s+", "[INDIRECT-2HOP] ", text, flags=re.I)
    text = re.sub(r"^\[INDIRECT\]\s+", "[INDIRECT-1HOP] ", text, flags=re.I)
    text = re.sub(r"^\[INOUT\]\s+", "[IN/OUT] ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_field_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = _normalize_field_entry(str(raw or ""))
        if not text:
            continue
        key = re.sub(r"^\[[^\]]+\]\s*", "", text).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _parse_signature_params_simple(signature: str) -> list[str]:
    sig = str(signature or "").strip()
    if not sig or "(" not in sig or ")" not in sig:
        return []
    inner = sig.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not inner or inner.lower() == "void":
        return []
    result: list[str] = []
    for raw in inner.split(","):
        token = str(raw or "").strip()
        if token:
            result.append(f"[IN] {token}")
    return result


def _parse_signature_outputs_simple(signature: str, function_name: str) -> list[str]:
    sig = str(signature or "").strip()
    fn_name = str(function_name or "").strip()
    if not sig:
        return []
    head = sig.split(fn_name, 1)[0].strip() if fn_name and fn_name in sig else sig
    head = re.sub(r"\b(?:static|inline|extern|const|volatile)\b", "", head, flags=re.I)
    ret = re.sub(r"\s+", " ", head).strip(" *")
    if not ret or ret.lower() == "void":
        return []
    return [f"[OUT] return {ret}"]


def _read_xlsx_rows(path: Path) -> str:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return ""
    try:
        sheets = pd.read_excel(str(path), sheet_name=None)
    except Exception:
        return ""
    rows = []
    for sheet_name, df in sheets.items():
        if df is None:
            continue
        try:
            records = df.fillna("").to_dict(orient="records")
        except Exception:
            continue
        for idx, row in enumerate(records):
            payload = {"sheet": sheet_name, "row_index": idx + 1, "data": row}
            rows.append(json.dumps(payload, ensure_ascii=False, default=str))
    return "\n".join(rows)


def _discover_hsis_path(repo_root: Path) -> str:
    docs_dir = repo_root / "docs"
    if not docs_dir.exists():
        return ""
    for p in docs_dir.iterdir():
        if p.is_file() and p.suffix.lower() in {".xlsx", ".xlsm"} and "hsis" in p.name.lower():
            return str(p)
    return ""


def _enrich_source_sections_with_docs(
    repo_root: Path,
    source_sections: dict,
    *,
    req_doc_paths: list[str],
    sds_doc_paths: list[str],
) -> dict:
    sections = source_sections if isinstance(source_sections, dict) else {}
    details = sections.get("function_details", {})
    table_rows = sections.get("function_table_rows", [])
    if not isinstance(details, dict) or not details:
        return sections

    rg.enrich_function_details_with_docs(
        details,
        table_rows if isinstance(table_rows, list) else None,
        req_doc_paths=req_doc_paths,
        sds_doc_paths=sds_doc_paths,
    )

    hsis_path = _discover_hsis_path(repo_root)
    if hsis_path:
        try:
            from generators.sts import _load_hsis_signals

            hsis_data = _load_hsis_signals(hsis_path)
            hsis_signals = hsis_data.get("signals", [])
            if hsis_signals:
                hsis_by_var: dict[str, dict] = {}
                for signal in hsis_signals:
                    raw_names = str(signal.get("sw_var_name") or "")
                    for token in re.split(r"[\n,\s]+", raw_names):
                        token = token.strip()
                        if token and re.match(r"^[A-Za-z_]\w+$", token):
                            hsis_by_var[token] = signal
                for info in details.values():
                    if not isinstance(info, dict):
                        continue
                    used_vars = _iter_udf_identifiers(info)
                    has_code_evidence = bool(
                        (info.get("calls_list") or [])
                        or (info.get("globals_global") or [])
                        or (info.get("globals_static") or [])
                        or (info.get("inputs") or [])
                        or (info.get("outputs") or [])
                        or str(info.get("logic_flow") or "").strip()
                    )
                    if has_code_evidence:
                        _append_evidence(info, "description_evidence_sources", "code")
                        _append_evidence(info, "related_evidence_sources", "code")
                    matched = [hsis_by_var[v] for v in used_vars if v in hsis_by_var]
                    if has_code_evidence and str(info.get("description_source") or "").strip() in {"sds", "sds_match"}:
                        info["description_source_detail"] = "code+sds_match"
                    if not matched:
                        continue
                    hsis_signal_names = list(
                        dict.fromkeys(str(sig.get("signal_name") or "").strip() for sig in matched if str(sig.get("signal_name") or "").strip())
                    )
                    hsis_related_ids = list(
                        dict.fromkeys(str(sig.get("related_id") or "").strip() for sig in matched if str(sig.get("related_id") or "").strip())
                    )
                    info["hsis_match_count"] = len(matched)
                    if hsis_signal_names:
                        info["hsis_signal_names"] = hsis_signal_names
                    if hsis_related_ids:
                        info["hsis_related_ids"] = hsis_related_ids
                    _append_evidence(info, "description_evidence_sources", "hsis")
                    _append_evidence(info, "related_evidence_sources", "hsis")
                    if str(info.get("description_source") or "").strip() in {"", "inference"}:
                        info["description_source"] = "hsis"
                    elif str(info.get("description_source") or "").strip() in {"sds", "sds_match"}:
                        info["description_source_detail"] = "hsis+sds_match"
                    current_related = str(info.get("related") or "").strip()
                    if not current_related or current_related.upper() in {"TBD", "N/A", "-"}:
                        if hsis_related_ids:
                            info["related"] = hsis_related_ids[0]
                            info["related_source"] = "hsis"
                    elif str(info.get("related_source") or "").strip() == "sds":
                        info["related_source_detail"] = "hsis+sds"
        except Exception:
            pass

    for info in details.values():
        if not isinstance(info, dict):
            continue
        prototype = str(info.get("prototype") or "").strip()
        if prototype and not str(info.get("signature") or "").strip():
            info["signature"] = prototype
        signature = str(info.get("signature") or info.get("prototype") or "").strip()
        if signature and not (info.get("inputs") or []):
            info["inputs"] = _parse_signature_params_simple(signature)
        if signature and not (info.get("outputs") or []):
            info["outputs"] = _parse_signature_outputs_simple(signature, str(info.get("name") or ""))
        for field_name in ("inputs", "outputs", "globals_global", "globals_static"):
            info[field_name] = _normalize_field_list(info.get(field_name) or [])
        if str(info.get("description_source") or "").strip() in {"sds", "sds_match"}:
            _append_evidence(info, "description_evidence_sources", "sds")
        if str(info.get("related_source") or "").strip() in {"sds", "hsis", "srs"}:
            _append_evidence(info, "related_evidence_sources", str(info.get("related_source") or "").strip())

    rebuilt_by_name: dict[str, dict] = {}
    for info in details.values():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip()
        if name:
            rebuilt_by_name[name] = info
    sections["function_details"] = details
    sections["function_details_by_name"] = rebuilt_by_name
    return sections


def _run_report_with_timeout(
    fn,
    *,
    timeout_seconds: int,
    logger: logging.Logger,
    name: str,
) -> bool:
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(fn)
        future.result(timeout=timeout_seconds)
        ex.shutdown(wait=True, cancel_futures=False)
        return True
    except FuturesTimeoutError:
        ex.shutdown(wait=False, cancel_futures=True)
        logger.warning("%s skipped by timeout (%ss)", name, timeout_seconds)
    except Exception as exc:
        ex.shutdown(wait=False, cancel_futures=True)
        logger.warning("%s failed: %s", name, exc)
    return False


def _build_docx_retry_payload(base_payload: dict, level: int) -> dict:
    payload = deepcopy(base_payload or {})
    if level <= 0:
        return payload
    # 1st degrade: remove optional AI expansion noise.
    if level >= 1:
        payload.pop("ai_sections", None)
        payload["logic_max_children"] = min(int(payload.get("logic_max_children") or 3), 2)
        payload["logic_max_grandchildren"] = min(int(payload.get("logic_max_grandchildren") or 2), 1)
        payload["logic_max_depth"] = min(int(payload.get("logic_max_depth") or 3), 2)
    # 2nd degrade: keep structure but remove heavy logic rendering inputs.
    if level >= 2:
        payload["logic_diagrams"] = []
        payload["software_unit_design"] = str(payload.get("software_unit_design") or "")[:60000]
        payload["requirements"] = str(payload.get("requirements") or "")[:80000]
    return payload


def _generate_docx_with_subprocess(
    *,
    tpl: str,
    payload: dict,
    output_path: Path,
    timeout_seconds: int,
    logger: logging.Logger,
    stage: str,
) -> tuple[bool, str]:
    work_dir = output_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    payload_file = Path(tempfile.mkstemp(prefix="uds_payload_", suffix=".json", dir=str(work_dir))[1])
    checkpoint = output_path.with_suffix(".docx.stage.json")
    stage_payload_file = output_path.with_suffix(f".docx.payload.{stage}.json")
    try:
        payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        stage_payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        checkpoint.write_text(
            json.dumps(
                {
                    "stage": stage,
                    "status": "started",
                    "timeout_seconds": timeout_seconds,
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                    "output_path": str(output_path),
                    "stage_payload_path": str(stage_payload_file),
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
            "rg.generate_uds_docx(tpl,payload,out);"
            "print('OK')"
        )
        run = subprocess.run(
            [sys.executable, "-c", inline, tpl or "", str(payload_file), str(output_path)],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if run.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            checkpoint.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "success",
                        "ended_at": datetime.now().isoformat(timespec="seconds"),
                        "output_path": str(output_path),
                        "stage_payload_path": str(stage_payload_file),
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
                    "output_path": str(output_path),
                    "stage_payload_path": str(stage_payload_file),
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
                    "output_path": str(output_path),
                    "stage_payload_path": str(stage_payload_file),
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
                    "output_path": str(output_path),
                    "stage_payload_path": str(stage_payload_file),
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


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _find_resume_candidate(out_dir: Path, retry_stages: list[tuple[str, int, int]]) -> tuple[Path, int] | None:
    stage_files = sorted(out_dir.glob("*.docx.stage.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    stage_order = [name for name, _, _ in retry_stages]
    for stage_file in stage_files:
        info = _load_json(stage_file)
        status = str(info.get("status") or "").strip().lower()
        stage_name = str(info.get("stage") or "").strip()
        if status not in {"started", "failed", "timeout", "exception"}:
            continue
        if stage_name not in stage_order:
            continue
        out_path_text = str(info.get("output_path") or "").strip()
        if out_path_text:
            out_path = Path(out_path_text)
        else:
            raw = str(stage_file)
            out_path = Path(raw[:-11] if raw.endswith(".stage.json") else raw.replace(".stage.json", ""))
        payload_path_text = str(info.get("stage_payload_path") or "").strip()
        if payload_path_text:
            payload_path = Path(payload_path_text)
        else:
            payload_path = out_path.with_suffix(f".docx.payload.{stage_name}.json")
        if not payload_path.exists():
            continue
        start_idx = stage_order.index(stage_name)
        return out_path, start_idx
    return None


def _resolve_source_root(repo_root: Path) -> Path:
    override = os.getenv("UDS_SOURCE_ROOT", "").strip()
    candidates = [
        Path(override) if override else None,
        Path(r"D:\Project\Ados\PDS64_RD"),
        Path(r"D:\Project\Ados\PDS_64_RD"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists() and candidate.is_dir():
            return candidate
    return Path(override) if override else Path(r"D:\Project\Ados\PDS64_RD")


def _write_uds_payload_sidecar(output_path: Path, uds_payload: dict) -> Path | None:
    try:
        details = uds_payload.get("function_details")
        if not isinstance(details, dict) or not details:
            return None
        summary = uds_payload.get("summary")
        if not isinstance(summary, dict):
            summary = {}
        sidecar = output_path.with_suffix(".payload.json")
        payload = {
            "docx_path": str(output_path),
            "summary": summary,
            "function_details": details,
        }
        sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return sidecar
    except Exception:
        return None


def main() -> None:
    repo_root = Path(r"D:\Project\devops\260105")
    use_ai = os.getenv("UDS_USE_AI", "1").strip() not in {"0", "false", "False"}
    impact_mode = os.getenv("UDS_IMPACT_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
    expand = True
    template_path = Path(
        r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"
    )
    if not template_path.exists():
        template_path = Path(
            r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx"
        )
    log_path = repo_root / "reports" / "uds" / "uds_generation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(str(log_path), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("uds_local")
    docs_dir = repo_root / "docs"
    sr_candidates = [p for p in docs_dir.iterdir() if "HDPDM01_SR" in p.name and p.suffix.lower() == ".xlsx"]
    sr_doc = sr_candidates[0] if sr_candidates else Path(r"D:\Project\devops\260105\docs\★ (HDPDM01_SR) Stakeholder Requirements_v_2025.xlsx")
    docs = [
        sr_doc,
        Path(r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx"),
        Path(r"D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"),
        Path(r"D:\Project\devops\260105\docs\PDSM_Funtional_Specification_1.42_TC_220421_2.xlsx"),
    ]
    source_root = _resolve_source_root(repo_root)
    skip_source = os.getenv("UDS_SKIP_SOURCE", "0").strip() in {"1", "true", "True"}

    req_texts = []
    notes = []
    reference_files = []
    skip_docs = os.getenv("UDS_SKIP_DOCS", "0").strip() in {"1", "true", "True"}

    if not skip_docs:
        logger.info("docs parsing started")
        for p in docs:
            if not p.exists():
                print(f"MISSING: {p}")
                continue
            suffix = p.suffix.lower()
            if suffix == ".xlsx":
                text = _read_xlsx_rows(p)
            else:
                text = ragmod._read_text_from_file(p)
            if text:
                req_texts.append(text)
                notes.append(f"doc:{p.name}")
                reference_files.append(p.name)
        logger.info("docs parsing completed: %s files", len(reference_files))

    if skip_source:
        source_sections = {}
    else:
        logger.info("source parsing started: %s", source_root)
        source_sections = rg.generate_uds_source_sections(str(source_root)) if source_root.exists() else {}
        req_doc_paths = [
            str(p) for p in docs
            if p.exists() and p.suffix.lower() == ".docx" and "SRS" in p.name.upper()
        ]
        sds_doc_paths = [
            str(p) for p in docs
            if p.exists() and p.suffix.lower() == ".docx" and "SDS" in p.name.upper()
        ]
        source_sections = _enrich_source_sections_with_docs(
            repo_root,
            source_sections,
            req_doc_paths=req_doc_paths,
            sds_doc_paths=sds_doc_paths,
        )
        logger.info("source parsing completed")
    req_from_docs = rg.generate_uds_requirements_from_docs(req_texts) if req_texts else ""
    req_map = rg._build_req_map_from_texts(req_texts) if req_texts else {}
    sds_map = {}
    for p in docs:
        if "SDS" in p.name and p.suffix.lower() == ".docx":
            sds_map = rg._extract_sds_partition_map(str(p))
            break
    req_source = source_sections.get("requirements", "")
    if req_from_docs and req_source:
        req_combined = "\n".join([req_from_docs.strip(), req_source.strip()]).strip()
    else:
        req_combined = req_from_docs or req_source

    if template_path.exists():
        reference_files.append(template_path.name)

    uds_payload = {
        "job_url": "local",
        "build_number": "",
        "project_name": source_root.name if source_root.exists() else "PDS_64_RD",
        "summary": {},
        "overview": source_sections.get("overview", ""),
        "requirements": req_combined,
        "interfaces": source_sections.get("interfaces", ""),
        "uds_frames": source_sections.get("uds_frames", ""),
        "notes": "\n".join(notes),
        "reference_files": reference_files,
        "logic_diagrams": [],
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
        "sds_partition_map": sds_map,
        "globals_info_map": source_sections.get("globals_info_map", {}),
        "common_macros": source_sections.get("common_macros", []),
        "type_defs": source_sections.get("type_defs", []),
        "param_defs": source_sections.get("param_defs", []),
        "version_defs": source_sections.get("version_defs", []),
        "globals_format_order": ["Name", "Type", "File", "Range"],
        "globals_format_sep": " | ",
        "globals_format_with_labels": True,
        "call_relation_mode": "code",
        "logic_max_children": 3,
        "logic_max_grandchildren": 2,
        "logic_max_depth": 3,
    }

    example_text = ""
    for p in docs:
        if p.suffix.lower() == ".docx" and "SUDS" in p.name:
            try:
                example_text = ragmod._read_text_from_file(p)
            except Exception:
                example_text = ""
            break

    if use_ai:
        try:
            from workflow.uds_ai import generate_uds_ai_sections
            cfg = load_oai_config(None)
            if cfg:
                rag_snippets = []
                try:
                    kb = get_kb(repo_root / "reports")
                    rag_query = (req_combined.strip() or source_sections.get("overview", ""))[:2000]
                    if rag_query:
                        rag_rows = kb.search(
                            rag_query,
                            top_k=8 if expand else 3,
                            categories=["requirements", "uds", "code"],
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
                notes_text = ""
                if expand:
                    doc_block = "\n\n".join(req_texts)[:40000]
                    src_block = "\n\n".join(
                        [
                            source_sections.get("overview", ""),
                            source_sections.get("interfaces", ""),
                            source_sections.get("uds_frames", ""),
                        ]
                    )
                    notes_text = "\n\n".join([doc_block, src_block]).strip()
                ai_sections = generate_uds_ai_sections(
                    requirements_text=req_combined,
                    source_sections=source_sections,
                    notes_text=notes_text,
                    logic_items=[],
                    example_text=example_text,
                    detailed=True,
                    rag_snippets=rag_snippets,
                )
                if ai_sections:
                    uds_payload["ai_sections"] = ai_sections
        except Exception:
            pass

    out_dir = repo_root / "backend" / "reports" / "uds_local"
    out_dir.mkdir(parents=True, exist_ok=True)
    changed_files = os.getenv("UDS_CHANGED_FILES", "").strip()
    impact_path = None
    if changed_files and source_root.exists():
        impact_path = repo_root / "reports" / "uds" / "impact_analysis.md"
        impact_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cmd = [
                sys.executable,
                str(repo_root / "tools" / "impact_analysis.py"),
                "--source-root",
                str(source_root),
                "--changed",
                changed_files,
                "--out",
                str(impact_path),
            ]
            run = subprocess.run(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
            )
            if run.returncode == 0 and impact_path.exists():
                notes.append(f"impact:{impact_path.name}")
                uds_payload["notes"] = "\n".join(notes)
                logger.info("impact analysis created: %s", impact_path)
            else:
                err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-4000:]
                logger.warning("impact analysis failed: %s", err[-400:])
                impact_path.write_text(
                    "\n".join(
                        [
                            "# Impact Analysis Report",
                            "",
                            f"- Source root: `{source_root}`",
                            f"- Changed files: `{changed_files}`",
                            "- Status: `failed`",
                            "",
                            "## Error",
                            f"- {err or 'unknown error'}",
                        ]
                    ),
                    encoding="utf-8",
                )
        except Exception as exc:
            logger.warning("impact analysis error: %s", exc)
            impact_path.write_text(
                "\n".join(
                    [
                        "# Impact Analysis Report",
                        "",
                        f"- Source root: `{source_root}`",
                        f"- Changed files: `{changed_files}`",
                        "- Status: `failed`",
                        "",
                        "## Error",
                        f"- {exc}",
                    ]
                ),
                encoding="utf-8",
            )
    tpl = str(template_path) if template_path.exists() else None
    last_err = ""
    retry_stages = [
        ("full", 0, 1200),
        ("degraded_ai_off", 1, 900),
        ("degraded_light", 2, 600),
    ]
    resume_enabled = os.getenv("UDS_RESUME_LAST", "1").strip().lower() in {"1", "true", "yes", "on"}
    resume = _find_resume_candidate(out_dir, retry_stages) if resume_enabled else None
    start_index = 0
    if resume:
        output_path, start_index = resume
        logger.info("docx resume detected: %s (start stage index=%s)", output_path, start_index)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = out_dir / f"uds_spec_generated_expanded_{ts}.docx"
    logger.info("docx generation started: %s", output_path)
    for idx, (stage, level, timeout_sec) in enumerate(retry_stages[start_index:], start=start_index + 1):
        t0 = time.time()
        stage_payload_path = output_path.with_suffix(f".docx.payload.{stage}.json")
        if resume and stage_payload_path.exists():
            staged_payload = _load_json(stage_payload_path)
            if not staged_payload:
                staged_payload = _build_docx_retry_payload(uds_payload, level)
        else:
            staged_payload = _build_docx_retry_payload(uds_payload, level)
        ok_docx, err = _generate_docx_with_subprocess(
            tpl=tpl or "",
            payload=staged_payload,
            output_path=output_path,
            timeout_seconds=timeout_sec,
            logger=logger,
            stage=stage,
        )
        if ok_docx:
            logger.info(
                "docx generation success (attempt=%s stage=%s elapsed=%.1fs)",
                idx,
                stage,
                time.time() - t0,
            )
            last_err = ""
            break
        last_err = err
        logger.warning(
            "docx generation failed (attempt=%s stage=%s elapsed=%.1fs): %s",
            idx,
            stage,
            time.time() - t0,
            err,
        )
        time.sleep(1.0)
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"DOCX generation failed after retries: {last_err}")
    sidecar_path = _write_uds_payload_sidecar(output_path, uds_payload)
    validation_path = output_path.with_suffix(".validation.md")
    ok_validation = _run_report_with_timeout(
        lambda: rg.generate_uds_validation_report(str(output_path), str(validation_path)),
        timeout_seconds=120,
        logger=logger,
        name="validation report",
    )
    if ok_validation:
        logger.info("validation report created: %s", validation_path)
    else:
        validation_path = None
    accuracy_path = None
    swcom_context_path = None
    if not impact_mode:
        accuracy_path = output_path.with_suffix(".accuracy.md")
        ok_accuracy = _run_report_with_timeout(
            lambda: rg.generate_called_calling_accuracy_report(
                str(output_path),
                str(source_root) if source_root.exists() else "",
                str(accuracy_path),
                relation_mode=str(uds_payload.get("call_relation_mode") or "code"),
            ),
            timeout_seconds=300,
            logger=logger,
            name="accuracy report",
        )
        if ok_accuracy:
            logger.info("accuracy report created: %s", accuracy_path)
        else:
            accuracy_path = None
        swcom_context_path = output_path.with_suffix(".swcom_context.md")
        ok_swcom = _run_report_with_timeout(
            lambda: rg.generate_swcom_context_report(str(output_path), str(swcom_context_path)),
            timeout_seconds=120,
            logger=logger,
            name="swcom context report",
        )
        if ok_swcom:
            logger.info("swcom context report created: %s", swcom_context_path)
        else:
            swcom_context_path = None
    confidence_path = output_path.with_suffix(".field_confidence.md")
    ok_confidence = _run_report_with_timeout(
        lambda: rg.generate_asil_related_confidence_report(
            uds_payload,
            str(confidence_path),
            str(output_path),
        ),
        timeout_seconds=120,
        logger=logger,
        name="ASIL/Related confidence report",
    )
    if ok_confidence:
        logger.info("ASIL/Related confidence report created: %s", confidence_path)
    else:
        confidence_path = None
    constraints_path = output_path.with_suffix(".constraints.md")
    ok_constraints = _run_report_with_timeout(
        lambda: rg.generate_uds_constraints_report(uds_payload, str(constraints_path)),
        timeout_seconds=120,
        logger=logger,
        name="constraints report",
    )
    if ok_constraints:
        logger.info("constraints report created: %s", constraints_path)
    else:
        constraints_path = None
    quality_gate_path = output_path.with_suffix(".quality_gate.md")
    ok_quality_gate = _run_report_with_timeout(
        lambda: rg.generate_uds_field_quality_gate_report(str(output_path), str(quality_gate_path)),
        timeout_seconds=120,
        logger=logger,
        name="field quality gate report",
    )
    if ok_quality_gate:
        logger.info("field quality gate report created: %s", quality_gate_path)
    else:
        quality_gate_path = None
    swcom_diff_path = None
    if not impact_mode:
        swcom_diff_path = output_path.with_suffix(".swcom_diff.md")
        ref_docx = repo_root / "docs" / "(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"
        if ref_docx.exists():
            ok_swcom_diff = _run_report_with_timeout(
                lambda: rg.generate_swcom_context_diff_report(str(ref_docx), str(output_path), str(swcom_diff_path)),
                timeout_seconds=120,
                logger=logger,
                name="swcom context diff report",
            )
            if ok_swcom_diff:
                logger.info("swcom context diff report created: %s", swcom_diff_path)
            else:
                swcom_diff_path = None
        else:
            swcom_diff_path = None
        try:
            html = rg.generate_uds_preview_html(uds_payload)
            output_path.with_suffix(".html").write_text(html, encoding="utf-8")
        except Exception:
            pass

    print(f"UDS_DOCX={output_path}")
    if sidecar_path:
        print(f"UDS_PAYLOAD={sidecar_path}")
    if validation_path:
        print(f"UDS_VALIDATION={validation_path}")
    if accuracy_path:
        print(f"UDS_ACCURACY={accuracy_path}")
    if swcom_context_path:
        print(f"UDS_SWCOM_CONTEXT={swcom_context_path}")
    if confidence_path:
        print(f"UDS_CONFIDENCE={confidence_path}")
    if constraints_path:
        print(f"UDS_CONSTRAINTS={constraints_path}")
    if quality_gate_path:
        print(f"UDS_QUALITY_GATE={quality_gate_path}")
    if impact_path:
        print(f"UDS_IMPACT={impact_path}")
    if swcom_diff_path:
        print(f"UDS_SWCOM_DIFF={swcom_diff_path}")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"OK: {output_path}\n", encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            repo_root = Path(r"D:\Project\devops\260105")
            log_path = repo_root / "reports" / "uds" / "uds_generation.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(f"ERROR: {exc}\n", encoding="utf-8")
        except Exception:
            pass
        raise
