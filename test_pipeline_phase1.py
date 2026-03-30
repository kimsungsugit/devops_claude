"""Phase 1: Source analysis + AI section generation + save intermediate JSON."""
import sys, os, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

from report_generator import (
    generate_uds_source_sections,
    _extract_sds_partition_map,
)
from workflow.rag import _read_text_from_file

SOURCE_ROOT = r"D:\Project\devops\260105\my_lin_gateway_251118_bakup"
SRS_PATH = r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx"
SDS_PATH = r"D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
CACHE_DIR = Path(r"D:\Project\devops\260105\reports\uds_local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("=" * 70)
    print("[Phase 1] Source analysis + AI generation")
    print("=" * 70)

    print("\n[1/4] Source analysis")
    source_sections = generate_uds_source_sections(SOURCE_ROOT)
    fd = source_sections.get("function_details", {})
    print(f"  Functions: {len(fd)}")

    print("\n[2/4] SRS/SDS document parsing")
    req_texts, srs_texts, sds_texts, sds_doc_paths = [], [], [], []
    for doc_path in [SRS_PATH, SDS_PATH]:
        p = Path(doc_path)
        if not p.exists():
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

    print("\n[3/4] SDS DOCX table parsing")
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
            print(f"  Error: {e}")
    print(f"  SDS entries: {len(sds_partition_map)}")

    print("\n[4/4] AI section generation")
    ai_sections = None
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
            print(f"  AI sections: {list(ai_sections.keys())}")
        else:
            print("  AI returned None")
    except Exception as e:
        print(f"  AI error: {e}")
        import traceback; traceback.print_exc()

    cache_path = CACHE_DIR / "phase1_cache.json"
    def _make_serializable(obj):
        if isinstance(obj, dict):
            return {k: _make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [_make_serializable(v) for v in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            return str(obj)

    cache = {
        "source_sections": _make_serializable(source_sections),
        "srs_texts": srs_texts,
        "sds_texts": sds_texts,
        "sds_doc_paths": sds_doc_paths,
        "sds_partition_map": _make_serializable(sds_partition_map),
        "ai_sections": _make_serializable(ai_sections) if ai_sections else None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Cache saved: {cache_path} ({cache_path.stat().st_size // 1024} KB)")
    print("Phase 1 DONE")


if __name__ == "__main__":
    main()
