from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(r"D:/Project/devops/260105")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import report_generator as rg


def main() -> None:
    source_root = Path(r"D:/Project/Ados/PDS_64_RD")
    sections = rg.generate_uds_source_sections(str(source_root))
    names = [
        "main",
        "s_sysmain_init",
        "s_systemoperation",
        "s_systemdiagnosis",
        "s_systemmanagement",
    ]
    by_name = sections.get("function_details_by_name", {}) or {}
    fn_out = {}
    for name in names:
        info = by_name.get(name, {}) or {}
        fn_out[name] = {
            "exists": name in by_name,
            "description": str(info.get("description") or "")[:140],
            "related": str(info.get("related") or ""),
            "called": str(info.get("called") or "")[:240],
        }
    globals_detailed = sections.get("globals_detailed", []) or []
    function_names = {
        str(x.get("name") or "").strip()
        for x in (sections.get("functions", []) or [])
        if isinstance(x, dict)
    }
    overlaps = [
        x.get("name")
        for x in globals_detailed
        if isinstance(x, dict) and str(x.get("name") or "").strip() in function_names
    ]
    output = {
        "source_root_exists": source_root.exists(),
        "function_checks": fn_out,
        "globals_detailed_count": len(globals_detailed),
        "globals_function_name_overlap_top20": overlaps[:20],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
