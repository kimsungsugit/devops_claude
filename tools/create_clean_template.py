from __future__ import annotations

from pathlib import Path

from docx import Document  # type: ignore
from docx.oxml import OxmlElement  # type: ignore
from docx.oxml.ns import qn  # type: ignore
from docx.oxml.text.paragraph import CT_P  # type: ignore
from docx.oxml.table import CT_Tbl  # type: ignore
from docx.table import Table  # type: ignore
from docx.text.paragraph import Paragraph  # type: ignore


LABELS = [
    "[ Function Information ]",
    "ID",
    "Name",
    "Prototype",
    "Description",
    "ASIL",
    "Related ID",
    "Input Parameters",
    "Output Parameters",
    "Precondition",
    "Used Globals (Global)",
    "Used Globals (Static)",
    "Called Function",
    "Logic Diagram",
]


def _iter_blocks(doc: Document):
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("tbl", Table(child, doc))


def _set_cell_text(cell, text: str) -> None:
    tc = cell._tc
    for p in list(tc):
        tc.remove(p)
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    p.append(r)
    tc.append(p)


def _fix_function_table(table: Table) -> None:
    if not table.rows:
        return
    for r_idx, row in enumerate(table.rows):
        cells = row.cells
        if r_idx < len(LABELS):
            _set_cell_text(cells[0], LABELS[r_idx])
        else:
            _set_cell_text(cells[0], cells[0].text.strip())
        for c_idx in range(1, len(cells)):
            _set_cell_text(cells[c_idx], "")


def main() -> None:
    src = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")
    dst = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx")
    doc = Document(str(src))

    expect_table = False
    fixed = 0
    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            if text.startswith("SwUFn_"):
                expect_table = True
        elif kind == "tbl":
            if expect_table:
                _fix_function_table(node)
                fixed += 1
                expect_table = False
    doc.save(str(dst))
    Path(r"D:\Project\devops\260105\backend\reports\uds_local\clean_template_fix_count.txt").write_text(str(fixed), encoding="utf-8")


if __name__ == "__main__":
    main()
