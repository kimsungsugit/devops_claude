from __future__ import annotations

import re
from pathlib import Path

from docx import Document  # type: ignore


def main() -> None:
    report_dir = Path(r"D:\Project\devops\260105\backend\reports\uds_local")
    candidates = sorted(
        report_dir.glob("uds_spec_generated_expanded_*.docx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No generated docx in {report_dir}")
    path = candidates[0]
    print(f"FILE={path}")
    doc = Document(str(path))
    pattern = re.compile(r"^(Interfaces:|Internals:|Global data:|N/A)$", re.I)
    hits = 0
    for t_idx, table in enumerate(doc.tables):
        for r_idx, row in enumerate(table.rows):
            row_texts = [cell.text.strip() for cell in row.cells]
            if any(pattern.search(txt) for txt in row_texts):
                hits += 1
                print(f"table={t_idx} row={r_idx} cells={row_texts}")
                if hits >= 5:
                    return
    if hits == 0:
        print("No matches in tables.")


if __name__ == "__main__":
    main()
