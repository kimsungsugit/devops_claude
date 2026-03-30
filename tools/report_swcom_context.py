from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from docx import Document  # type: ignore
from docx.oxml.table import CT_Tbl  # type: ignore
from docx.oxml.text.paragraph import CT_P  # type: ignore
from docx.table import Table  # type: ignore
from docx.text.paragraph import Paragraph  # type: ignore


def _iter_blocks(doc: Document):
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("t", Table(child, doc))


def _parse_swcom_tables(doc_path: Path) -> Dict[str, Dict[str, List[List[str]]]]:
    doc = Document(str(doc_path))
    out: Dict[str, Dict[str, List[List[str]]]] = {}
    cur_swcom = ""
    pending = ""
    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            if not text:
                continue
            m_sw = re.search(r"\b(SwCom_\d+)\b", text, flags=re.I)
            if m_sw:
                cur_swcom = m_sw.group(1).replace("swcom", "SwCom")
                out.setdefault(cur_swcom, {"global_variables": [], "static_variables": []})
            if "Global variables" in text:
                pending = "global_variables"
            elif "Static Variables" in text:
                pending = "static_variables"
            continue
        if not cur_swcom or not pending:
            continue
        rows: List[List[str]] = []
        for row in node.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            if any(cells):
                rows.append(cells)
        out.setdefault(cur_swcom, {"global_variables": [], "static_variables": []})[pending] = rows
        pending = ""
    return out


def generate_swcom_context_report(docx_path: str, out_path: str) -> str:
    data = _parse_swcom_tables(Path(docx_path))
    lines: List[str] = []
    lines.append("# SwCom Context Report")
    lines.append("")
    lines.append(f"- Target DOCX: `{docx_path}`")
    lines.append("")
    lines.append("## Summary")
    sw_count = len(data)
    gv_total = sum(max(0, len(v.get("global_variables", [])) - 1) for v in data.values())
    sv_total = sum(max(0, len(v.get("static_variables", [])) - 1) for v in data.values())
    lines.append(f"- SwCom sections: `{sw_count}`")
    lines.append(f"- Global variable rows: `{gv_total}`")
    lines.append(f"- Static variable rows: `{sv_total}`")
    lines.append("")
    lines.append("## Suspicious Rows")
    suspicious: List[str] = []
    for swcom, tables in data.items():
        for sec_key in ("global_variables", "static_variables"):
            rows = tables.get(sec_key, [])
            for row in rows[1:]:
                name = str(row[0] if len(row) > 0 else "").strip()
                desc = str(row[4] if len(row) > 4 else "").strip()
                if name.startswith("REG_"):
                    suspicious.append(f"- {swcom} {sec_key}: REG alias `{name}`")
                if re.search(r"\.c$|\.h$", desc, flags=re.I):
                    suspicious.append(f"- {swcom} {sec_key}: description looks like file name `{desc}`")
    if suspicious:
        lines.extend(suspicious[:120])
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Per SwCom Counts")
    for swcom in sorted(data.keys()):
        gv = max(0, len(data[swcom].get("global_variables", [])) - 1)
        sv = max(0, len(data[swcom].get("static_variables", [])) - 1)
        lines.append(f"- {swcom}: global={gv}, static={sv}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    repo = Path(r"D:\Project\devops\260105")
    report_dir = repo / "backend" / "reports" / "uds_local"
    docs = sorted(report_dir.glob("uds_spec_generated_expanded_*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docs:
        raise FileNotFoundError(f"No UDS docx found in {report_dir}")
    target = docs[0]
    out = target.with_suffix(".swcom_context.md")
    print(generate_swcom_context_report(str(target), str(out)))
