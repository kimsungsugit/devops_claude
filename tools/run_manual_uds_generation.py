from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

repo_root = Path(r"D:\Project\devops\260105")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import report_generator as rg
from workflow import rag as ragmod


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
            rows.append(str(payload))
    return "\n".join(rows)


def main() -> None:
    docs_dir = repo_root / "docs"
    sr_candidates = [
        p for p in docs_dir.iterdir() if "HDPDM01_SR" in p.name and p.suffix.lower() == ".xlsx"
    ]
    docs = []
    if sr_candidates:
        docs.append(sr_candidates[0])
    docs.extend(
        [
            docs_dir / "(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx",
            docs_dir / "(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx",
            docs_dir / "PDSM_Funtional_Specification_1.42_TC_220421_2.xlsx",
        ]
    )

    req_texts = []
    notes = []
    ref_files = []
    for p in docs:
        if not p.exists():
            continue
        if p.suffix.lower() == ".xlsx":
            text = _read_xlsx_rows(p)
        else:
            text = ragmod._read_text_from_file(p)
        if text:
            req_texts.append(text)
            notes.append(f"doc:{p.name}")
            ref_files.append(p.name)

    source_root = Path(r"D:\Project\Ados\PDS_64_RD")
    source_sections = (
        rg.generate_uds_source_sections(str(source_root)) if source_root.exists() else {}
    )
    req_from_docs = rg.generate_uds_requirements_from_docs(req_texts) if req_texts else ""
    req_map = rg._build_req_map_from_texts(req_texts) if req_texts else {}
    sds_map = {}
    for p in docs:
        if "SDS" in p.name and p.suffix.lower() == ".docx":
            sds_map = rg._extract_sds_partition_map(str(p))
            break
    req_source = source_sections.get("requirements", "")
    req_combined = "\n".join(
        [t for t in [req_from_docs.strip(), req_source.strip()] if t]
    ).strip()

    tpl = docs_dir / "(HDPDM01_SUDS)_template_clean.docx"
    payload = {
        "job_url": "local",
        "build_number": "",
        "project_name": source_root.name if source_root.exists() else "PDS_64_RD",
        "summary": {},
        "overview": source_sections.get("overview", ""),
        "requirements": req_combined,
        "interfaces": source_sections.get("interfaces", ""),
        "uds_frames": source_sections.get("uds_frames", ""),
        "notes": "\n".join(notes),
        "reference_files": ref_files,
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
        "logic_max_children": 3,
        "logic_max_grandchildren": 2,
        "logic_max_depth": 3,
    }

    out_dir = repo_root / "backend" / "reports" / "uds_local"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_doc = out_dir / f"uds_spec_generated_expanded_manual_{ts}.docx"
    rg.generate_uds_docx(str(tpl) if tpl.exists() else None, payload, str(out_doc))
    html = rg.generate_uds_preview_html(payload)
    out_doc.with_suffix(".html").write_text(html, encoding="utf-8")
    print(out_doc)


if __name__ == "__main__":
    main()
