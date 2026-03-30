"""UDS AI-enabled full pipeline test."""
import sys, os, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

from report_generator import (
    generate_uds_source_sections,
    generate_uds_docx,
    generate_uds_field_quality_gate_report,
    generate_called_calling_accuracy_report,
    generate_asil_related_confidence_report,
    _extract_requirements_from_doc,
    _extract_sds_partition_map,
)
from workflow.rag import _read_text_from_file

SOURCE_ROOT = r"D:\Project\devops\260105\my_lin_gateway_251118_bakup"
SRS_PATH = r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx"
SDS_PATH = r"D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
OUT_DIR = Path(r"D:\Project\devops\260105\reports\uds_local")
AI_ENABLE = True

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_docx = OUT_DIR / f"uds_ai_{ts}.docx"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print("=" * 70)
    print(f"[1/7] Source analysis: {SOURCE_ROOT}")
    source_sections = generate_uds_source_sections(SOURCE_ROOT)
    fd = source_sections.get("function_details", {})
    fd_name = source_sections.get("function_details_by_name", {})
    print(f"  Functions: {len(fd)}, by_name: {len(fd_name)}")

    print(f"\n[2/7] SRS/SDS document parsing")
    req_texts, srs_texts, sds_texts = [], [], []
    sds_doc_paths = []
    for doc_path in [SRS_PATH, SDS_PATH]:
        p = Path(doc_path)
        if not p.exists():
            print(f"  SKIP (not found): {p.name}")
            continue
        text = _read_text_from_file(p)
        if text:
            req_texts.append(text.strip())
            if "srs" in p.name.lower():
                srs_texts.append(text.strip())
                print(f"  SRS: {p.name} ({len(text)} chars)")
            elif "sds" in p.name.lower():
                sds_texts.append(text.strip())
                sds_doc_paths.append(str(p))
                print(f"  SDS: {p.name} ({len(text)} chars)")

    print(f"\n[3/7] SDS DOCX table parsing")
    sds_partition_map = {}
    for sds_path in sds_doc_paths:
        try:
            docx_map = _extract_sds_partition_map(sds_path)
            if docx_map:
                for k, v in docx_map.items():
                    if k not in sds_partition_map:
                        sds_partition_map[k] = v
                    else:
                        for field in ("asil", "related", "description"):
                            if v.get(field) and not sds_partition_map[k].get(field):
                                sds_partition_map[k][field] = v[field]
        except Exception as e:
            print(f"  SDS parsing error: {e}")
    print(f"  SDS partition entries: {len(sds_partition_map)}")

    ai_sections = None
    if AI_ENABLE:
        print(f"\n[4/7] AI section generation")
        try:
            from workflow.uds_ai import generate_uds_ai_sections
            logic_items = source_sections.get("logic_diagrams", [])
            if not isinstance(logic_items, list):
                logic_items = []
            ai_sections = generate_uds_ai_sections(
                requirements_text="\n".join(req_texts),
                source_sections=source_sections,
                notes_text="",
                logic_items=logic_items,
                example_text="",
                detailed=True,
                rag_snippets=[],
            )
            if ai_sections:
                print(f"  AI sections generated: {list(ai_sections.keys())}")
            else:
                print("  AI returned None (config or API issue)")
        except Exception as e:
            print(f"  AI generation failed: {e}")
            import traceback; traceback.print_exc()
            ai_sections = None
    else:
        print(f"\n[4/7] AI section generation: DISABLED")

    print(f"\n[5/7] Building UDS payload")
    uds_payload = {
        "project_name": "LIN Gateway",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": SOURCE_ROOT,
        **source_sections,
        "srs_texts": srs_texts,
        "sds_texts": sds_texts,
        "sds_doc_paths": sds_doc_paths,
        "sds_partition_map": sds_partition_map,
        "req_map": {},
        "logic_max_children": 3,
        "logic_max_grandchildren": 2,
        "logic_max_depth": 3,
        "ai_func_desc_enable": AI_ENABLE,
    }
    if ai_sections:
        uds_payload["ai_sections"] = ai_sections
    print(f"  Payload keys: {len(uds_payload)}")

    print(f"\n[6/7] Generating DOCX: {out_docx.name}")
    result = generate_uds_docx(None, uds_payload, str(out_docx))
    print(f"  Output: {result}")
    docx_size = out_docx.stat().st_size / 1024
    print(f"  Size: {docx_size:.0f} KB")

    print(f"\n[7/7] Quality reports")
    qg_path = str(out_docx).replace(".docx", ".quality_gate.md")
    conf_path = str(out_docx).replace(".docx", ".confidence.md")
    acc_path = str(out_docx).replace(".docx", ".accuracy.md")
    generate_uds_field_quality_gate_report(str(out_docx), qg_path)
    print(f"  Quality gate: {Path(qg_path).name}")
    generate_asil_related_confidence_report(uds_payload, conf_path)
    print(f"  Confidence: {Path(conf_path).name}")
    generate_called_calling_accuracy_report(str(out_docx), SOURCE_ROOT, acc_path)
    print(f"  Accuracy: {Path(acc_path).name}")

    print("\n" + "=" * 70)
    print("QUALITY GATE SUMMARY:")
    print("=" * 70)
    qg_text = Path(qg_path).read_text(encoding="utf-8", errors="ignore")
    for line in qg_text.splitlines():
        if any(k in line.lower() for k in ["pass", "fail", "total", "rate", "fill", "result", "gate"]):
            print(f"  {line.strip()}")

    print("\nCONFIDENCE REPORT SUMMARY:")
    print("-" * 50)
    try:
        conf_text = Path(conf_path).read_text(encoding="utf-8", errors="ignore")
        for line in conf_text.splitlines():
            if any(k in line.lower() for k in ["confidence", "score", "grade", "source", "description", "inference", "comment", "sds", "ai"]):
                print(f"  {line.strip()}")
    except Exception:
        print("  (not generated)")

    print("=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
