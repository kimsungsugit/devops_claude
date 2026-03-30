from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Set

import networkx as nx  # type: ignore

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import report_generator as rg


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def _split_changed(raw: str) -> List[str]:
    out: List[str] = []
    for token in (raw or "").replace(";", ",").split(","):
        t = str(token).strip()
        if t:
            out.append(t)
    return out


def analyze(source_root: str, changed: List[str]) -> Dict[str, object]:
    sections = rg.generate_uds_source_sections(source_root)
    call_map = sections.get("call_map", {}) or {}
    by_name = sections.get("function_details_by_name", {}) or {}
    table_rows = sections.get("function_table_rows", []) or []

    g = nx.DiGraph()
    for caller, callees in call_map.items():
        c = _norm(caller)
        if not c:
            continue
        g.add_node(c)
        if isinstance(callees, list):
            for callee in callees:
                k = _norm(str(callee))
                if k:
                    g.add_edge(c, k)

    file_to_funcs: Dict[str, Set[str]] = {}
    func_to_file: Dict[str, str] = {}
    for name, info in by_name.items():
        if not isinstance(info, dict):
            continue
        fn = _norm(name)
        f = str(info.get("file") or "").strip()
        if not fn or not f:
            continue
        func_to_file[fn] = f
        file_to_funcs.setdefault(f.lower(), set()).add(fn)
        file_to_funcs.setdefault(Path(f).name.lower(), set()).add(fn)

    seed_funcs: Set[str] = set()
    for ch in changed:
        key = str(ch).strip().lower()
        if not key:
            continue
        seed_funcs.update(file_to_funcs.get(key, set()))
        seed_funcs.update(file_to_funcs.get(Path(key).name.lower(), set()))
        for fn, fp in func_to_file.items():
            if key in fp.lower():
                seed_funcs.add(fn)

    impacted_funcs: Set[str] = set(seed_funcs)
    for s in list(seed_funcs):
        if s in g:
            impacted_funcs.update(nx.descendants(g, s))
            impacted_funcs.update(nx.ancestors(g, s))

    fn_to_swcom: Dict[str, str] = {}
    for row in table_rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        sw = str(row[0] or "").strip()
        fn = _norm(str(row[3] or ""))
        if sw and fn:
            fn_to_swcom[fn] = sw
    impacted_swcom = sorted({fn_to_swcom.get(f, "SwCom_Unknown") for f in impacted_funcs})

    return {
        "changed_files": changed,
        "seed_function_count": len(seed_funcs),
        "impacted_function_count": len(impacted_funcs),
        "impacted_functions": sorted(impacted_funcs),
        "impacted_swcom": impacted_swcom,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="UDS impact analysis from changed files")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--changed", default="")
    ap.add_argument("--out", default=str(ROOT / "reports" / "uds" / "impact_analysis.md"))
    args = ap.parse_args()

    changed = _split_changed(args.changed)
    result = analyze(args.source_root, changed)

    out_md = Path(args.out)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# UDS Impact Analysis Report")
    lines.append("")
    lines.append(f"- Source root: `{args.source_root}`")
    lines.append(f"- Changed files: `{len(changed)}`")
    lines.append(f"- Seed functions: `{result['seed_function_count']}`")
    lines.append(f"- Impacted functions: `{result['impacted_function_count']}`")
    lines.append("")
    lines.append("## Impacted SwCom")
    sw_list = result.get("impacted_swcom", []) or []
    lines.extend([f"- {x}" for x in sw_list] if sw_list else ["- none"])
    lines.append("")
    lines.append("## Impacted Functions (Top 200)")
    fn_list = result.get("impacted_functions", []) or []
    lines.extend([f"- `{x}`" for x in fn_list[:200]] if fn_list else ["- none"])
    lines.append("")
    lines.append(f"- JSON: `{out_json}`")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"IMPACT_MD={out_md}")
    print(f"IMPACT_JSON={out_json}")


if __name__ == "__main__":
    main()
