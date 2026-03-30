"""Phase 2 without AI func desc - just DOCX generation + quality reports."""
import sys, os, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

from report_generator import (
    generate_uds_docx,
    generate_uds_field_quality_gate_report,
    generate_called_calling_accuracy_report,
    generate_asil_related_confidence_report,
)

SOURCE_ROOT = r"D:\Project\devops\260105\my_lin_gateway_251118_bakup"
CACHE_DIR = Path(r"D:\Project\devops\260105\reports\uds_local")
OUT_DIR = CACHE_DIR

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_docx = OUT_DIR / f"uds_v2_{ts}.docx"

def main():
    print("=" * 70)
    print("[Phase 2 - No AI func desc] DOCX + Quality reports")
    print("=" * 70)

    cache_path = CACHE_DIR / "phase1_cache.json"
    if not cache_path.exists():
        print(f"ERROR: Cache not found: {cache_path}")
        return
    print(f"\n[1/3] Loading cache ({cache_path.stat().st_size // 1024} KB)")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    source_sections = cache["source_sections"]
    srs_texts = cache.get("srs_texts", [])
    sds_texts = cache.get("sds_texts", [])
    sds_doc_paths = cache.get("sds_doc_paths", [])
    sds_partition_map = cache.get("sds_partition_map", {})
    ai_sections = cache.get("ai_sections")

    fd = source_sections.get("function_details", {})
    print(f"  Functions: {len(fd)}, AI sections: {bool(ai_sections)}")

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
        "ai_func_desc_enable": False,
    }
    if ai_sections:
        uds_payload["ai_sections"] = ai_sections

    print(f"\n[2/3] Generating DOCX: {out_docx.name}")
    result = generate_uds_docx(None, uds_payload, str(out_docx))
    print(f"  Output: {result}")
    if out_docx.exists():
        print(f"  Size: {out_docx.stat().st_size // 1024} KB")

    print(f"\n[3/3] Quality reports")
    qg_path = str(out_docx).replace(".docx", ".quality_gate.md")
    conf_path = str(out_docx).replace(".docx", ".confidence.md")
    acc_path = str(out_docx).replace(".docx", ".accuracy.md")
    generate_uds_field_quality_gate_report(str(out_docx), qg_path)
    generate_asil_related_confidence_report(uds_payload, conf_path)
    generate_called_calling_accuracy_report(str(out_docx), SOURCE_ROOT, acc_path)

    print("\n" + "=" * 70)
    print("QUALITY GATE SUMMARY:")
    print("=" * 70)
    qg_text = Path(qg_path).read_text(encoding="utf-8", errors="ignore")
    for line in qg_text.splitlines():
        if any(k in line.lower() for k in ["pass", "fail", "total", "rate", "fill", "result", "gate", "traceability"]):
            print(f"  {line.strip()}")
    print("=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
