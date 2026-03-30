from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any

from docx import Document  # type: ignore
from docx.oxml.text.paragraph import CT_P  # type: ignore
from docx.oxml.table import CT_Tbl  # type: ignore
from docx.table import Table  # type: ignore
from docx.text.paragraph import Paragraph  # type: ignore


def _heading_level(style_name: str) -> int:
    if not style_name or not style_name.startswith("Heading"):
        return 0
    for token in style_name.split():
        if token.isdigit():
            return int(token)
    for ch in style_name:
        if ch.isdigit():
            return int(ch)
    return 1


def _iter_blocks(doc: Document):
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("tbl", Table(child, doc))


def _cell_merge_info(cell) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    tc_pr = cell._tc.tcPr
    if tc_pr is None:
        return info
    grid_span = tc_pr.gridSpan
    if grid_span is not None and grid_span.val:
        info["gridSpan"] = int(grid_span.val)
    vmerge = tc_pr.vMerge
    if vmerge is not None:
        info["vMerge"] = vmerge.val or "continue"
    return info


def main() -> None:
    tpl = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")
    out = Path(r"D:\Project\devops\260105\backend\reports\uds_local\template_schema.json")
    doc = Document(str(tpl))
    heading_stack: List[str] = []
    items: List[Dict[str, Any]] = []
    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            if not text:
                continue
            level = _heading_level(str(getattr(node.style, "name", "") or ""))
            if level > 0:
                while len(heading_stack) >= level:
                    heading_stack.pop()
                heading_stack.append(text)
        else:
            table = node
            rows = len(table.rows)
            cols = len(table.columns)
            header_rows: List[List[str]] = []
            merge_map: List[List[Dict[str, Any]]] = []
            for r_idx, row in enumerate(table.rows[:2]):
                header_rows.append([c.text.strip() for c in row.cells])
                merge_map.append([_cell_merge_info(c) for c in row.cells])
            items.append(
                {
                    "ctx": " > ".join(heading_stack),
                    "rows": rows,
                    "cols": cols,
                    "header_rows": header_rows,
                    "header_merges": merge_map,
                }
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
