"""Patch UDS template: insert substitution tokens into 1.1~1.4 and strip dev memo.

Target: docs/(HDPDM01_SUDS)_template_clean.docx
  - p.199 Purpose body:  HDPDM01 프로젝트        → {{PROJECT_NAME}} 프로젝트
  - p.202 Scope body:    BSD 소프트웨어          → {{MODULE_NAME}} 소프트웨어
  - p.205, p.206 (Scope list): "* 펌웨어 별 수정 색" / "A.10.51 ..." → 삭제
  - p.209 Terms body:    HDPDM01 Glossary        → {{PROJECT_NAME}} Glossary
  - p.211 Reference body: empty → {{REFERENCE_TABLE}}

Preserves original runs/formatting by editing paragraph text in-place.
A copy is written to docs/(HDPDM01_SUDS)_template_tokenized.docx so the
original template_clean.docx is untouched; switch config pointer once verified.
"""
from __future__ import annotations

from pathlib import Path

import docx

SRC = Path(r"D:\Project\devops\Release_claude\docs\(HDPDM01_SUDS)_template_clean.docx")
DST = Path(r"D:\Project\devops\Release_claude\docs\(HDPDM01_SUDS)_template_tokenized.docx")


def _set_paragraph_text(para, new_text: str) -> None:
    """Replace paragraph text preserving first run's formatting."""
    runs = para.runs
    if not runs:
        para.text = new_text
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""


def main() -> None:
    doc = docx.Document(str(SRC))
    paras = list(doc.paragraphs)

    targets = {
        199: lambda p: _set_paragraph_text(
            p,
            p.text.replace("HDPDM01 프로젝트", "{{PROJECT_NAME}} 프로젝트"),
        ),
        202: lambda p: _set_paragraph_text(
            p,
            p.text.replace("BSD 소프트웨어", "{{MODULE_NAME}} 소프트웨어"),
        ),
        209: lambda p: _set_paragraph_text(
            p,
            p.text.replace("HDPDM01 Glossary", "{{PROJECT_NAME}} Glossary"),
        ),
        # p.211 is the "Reference" Heading — leave it alone.
        # p.212 is the empty body paragraph that follows the Reference heading.
        212: lambda p: _set_paragraph_text(p, "{{REFERENCE_TABLE}}"),
    }
    removals = {205, 206}

    print(f"Loaded {len(paras)} paragraphs from {SRC.name}")

    for idx, fn in targets.items():
        if idx >= len(paras):
            print(f"  ! skip idx={idx} (out of range)")
            continue
        before = paras[idx].text[:80]
        fn(paras[idx])
        after = paras[idx].text[:80]
        print(f"  [{idx}] {before!r} → {after!r}")

    for idx in sorted(removals, reverse=True):
        if idx >= len(paras):
            continue
        p = paras[idx]
        print(f"  [{idx}] REMOVE {p.text[:80]!r}")
        p._element.getparent().remove(p._element)

    doc.save(str(DST))
    print(f"Saved → {DST}")


if __name__ == "__main__":
    main()
