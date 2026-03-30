from __future__ import annotations

from pathlib import Path

from docx import Document  # type: ignore


def main() -> None:
    path = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")
    doc = Document(str(path))
    for table in doc.tables:
        if not table.rows:
            continue
        header = [c.text.strip() for c in table.rows[0].cells]
        if not header or "[ Function Information ]" not in header[0]:
            continue
        cols = len(table.columns)
        for r_idx, row in enumerate(table.rows):
            cells = row.cells
            col_count = len(cells)
            if r_idx == 0:
                for c_idx in range(1, col_count):
                    cells[c_idx].text = ""
                continue
            if col_count >= 2:
                cells[1].text = ""
            if col_count >= 4:
                for c_idx in range(3, col_count):
                    cells[c_idx].text = ""
    doc.save(str(path))


if __name__ == "__main__":
    main()
