from __future__ import annotations

from pathlib import Path

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


def main() -> None:
    path = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx")
    doc = Document(str(path))
    expect = False
    last_heading = ""
    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            if text.startswith("SwUFn_"):
                last_heading = text
                expect = True
                continue
        if expect and kind == "tbl":
            print(f"HEADING={last_heading}")
            rows = node.rows[:6]
            for i, r in enumerate(rows):
                print(i, [c.text.strip() for c in r.cells])
            break


if __name__ == "__main__":
    main()
