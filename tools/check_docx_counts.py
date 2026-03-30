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
    doc = Document(str(path))
    hits = []
    paras = [(p.text or "").strip() for p in doc.paragraphs]
    for idx, text in enumerate(paras):
        if re.search(r"^(Interfaces:|Internals:|Global data:)", text):
            hits.append((idx, text))
    print(len(hits))
    for idx, text in hits[:5]:
        start = max(0, idx - 2)
        end = min(len(paras), idx + 3)
        print("---")
        for j in range(start, end):
            print(paras[j])


if __name__ == "__main__":
    main()
