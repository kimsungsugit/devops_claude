from __future__ import annotations

from pathlib import Path
from typing import List

from docx import Document  # type: ignore
from docx.oxml.text.paragraph import CT_P  # type: ignore
from docx.oxml.table import CT_Tbl  # type: ignore
from docx.table import Table  # type: ignore
from docx.text.paragraph import Paragraph  # type: ignore


def _iter_blocks(doc: Document):
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("tbl", Table(child, doc))


def _dump_table(table: Table, max_rows: int = 6) -> List[str]:
    lines: List[str] = []
    rows = table.rows[:max_rows]
    for r_idx, row in enumerate(rows):
        cells = [c.text.strip() for c in row.cells]
        lines.append(f"row{r_idx}: {cells}")
    return lines


def main() -> None:
    path = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")
    doc = Document(str(path))
    found = False
    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            if text == "Interface Functions":
                found = True
                continue
        if found and kind == "tbl":
            lines = _dump_table(node)
            out = Path(r"D:\Project\devops\260105\backend\reports\uds_local\interface_table_template.txt")
            out.write_text("\n".join(lines), encoding="utf-8")
            return


if __name__ == "__main__":
    main()
