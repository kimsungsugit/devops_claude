from __future__ import annotations

from pathlib import Path

from docx import Document  # type: ignore


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
    last_heading = ""
    hits = 0
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        style = str(getattr(p.style, "name", "") or "")
        if _heading_level(style) > 0:
            last_heading = text
            continue
        if text == "N/A":
            print(f"heading={last_heading} text={text}")
            hits += 1
            if hits >= 10:
                break
    if hits == 0:
        print("No N/A paragraphs found.")


if __name__ == "__main__":
    main()
