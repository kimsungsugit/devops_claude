from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set

from docx import Document  # type: ignore
from docx.oxml.table import CT_Tbl  # type: ignore
from docx.oxml.text.paragraph import CT_P  # type: ignore
from docx.table import Table  # type: ignore
from docx.text.paragraph import Paragraph  # type: ignore

repo_root = Path(r"D:\Project\devops\260105")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
import report_generator as rg


def _iter_blocks(doc: Document):
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("t", Table(child, doc))


def _extract_swcom_tables(doc_path: Path) -> Dict[str, Dict[str, List[str]]]:
    doc = Document(str(doc_path))
    cur_swcom = ""
    mode = ""
    out: Dict[str, Dict[str, List[str]]] = {}
    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            m = re.search(r"\b(SwCom_\d+)\b", text, flags=re.I)
            if m:
                cur_swcom = m.group(1).replace("swcom", "SwCom")
                out.setdefault(cur_swcom, {"global": [], "static": []})
            if "Global variables" in text:
                mode = "global"
            elif "Static Variables" in text:
                mode = "static"
            else:
                if re.search(r"\bSwUFn_\d+\b", text):
                    mode = ""
            continue
        if not cur_swcom or not mode:
            continue
        rows = node.rows[1:] if node.rows else []
        vals: List[str] = []
        for row in rows:
            cells = [(c.text or "").strip() for c in row.cells]
            if cells and cells[0]:
                vals.append(cells[0])
        out[cur_swcom][mode] = vals
        mode = ""
    return out


def main() -> None:
    report_dir = repo_root / "backend" / "reports" / "uds_local"
    docs = sorted(report_dir.glob("uds_spec_generated_expanded_*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docs:
        raise FileNotFoundError(f"No generated UDS docx in {report_dir}")
    target = docs[0]
    source = rg.generate_uds_source_sections(str(Path(r"D:\Project\Ados\PDS_64_RD")))
    fn_rows = source.get("function_table_rows", []) or []
    details = source.get("function_details_by_name", {}) or {}
    expected: Dict[str, Dict[str, Set[str]]] = {}
    for row in fn_rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        swcom = str(row[0] or "").strip()
        fn = str(row[3] or "").strip().lower()
        if not swcom or not fn:
            continue
        expected.setdefault(swcom, {"global": set(), "static": set()})
        info = details.get(fn)
        if not isinstance(info, dict):
            continue
        for g in info.get("globals_global") or []:
            name = re.split(r"(?:->|\.)", re.sub(r"^\[(?:IN|OUT|INOUT)\]\s+", "", str(g))).pop(0).strip()
            if name and not name.startswith("REG_"):
                expected[swcom]["global"].add(name)
        for g in info.get("globals_static") or []:
            name = re.split(r"(?:->|\.)", re.sub(r"^\[(?:IN|OUT|INOUT)\]\s+", "", str(g))).pop(0).strip()
            if name and not name.startswith("REG_"):
                expected[swcom]["static"].add(name)

    actual = _extract_swcom_tables(target)
    lines: List[str] = []
    lines.append("# SwCom Context Regression Report")
    lines.append(f"- Target DOCX: `{target}`")
    lines.append("")
    mismatches = 0
    for swcom in sorted(actual.keys()):
        a_g = set(actual.get(swcom, {}).get("global", []))
        a_s = set(actual.get(swcom, {}).get("static", []))
        e_g = expected.get(swcom, {}).get("global", set())
        e_s = expected.get(swcom, {}).get("static", set())
        miss_g = sorted(e_g - a_g)
        extra_g = sorted(a_g - e_g)
        miss_s = sorted(e_s - a_s)
        extra_s = sorted(a_s - e_s)
        if miss_g or extra_g or miss_s or extra_s:
            mismatches += 1
        lines.append(f"## {swcom}")
        lines.append(f"- global_missing: {len(miss_g)}, global_extra: {len(extra_g)}")
        lines.append(f"- static_missing: {len(miss_s)}, static_extra: {len(extra_s)}")
        if miss_g[:5]:
            lines.append(f"- sample_global_missing: {', '.join(miss_g[:5])}")
        if extra_g[:5]:
            lines.append(f"- sample_global_extra: {', '.join(extra_g[:5])}")
        if miss_s[:5]:
            lines.append(f"- sample_static_missing: {', '.join(miss_s[:5])}")
        if extra_s[:5]:
            lines.append(f"- sample_static_extra: {', '.join(extra_s[:5])}")
        lines.append("")
    lines.insert(2, f"- swcom_mismatch_count: `{mismatches}`")
    out = report_dir / "swcom_context_regression_latest.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
