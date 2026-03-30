from __future__ import annotations

import json
import time
from pathlib import Path
import sys

repo_root = Path(r"d:\Project\devops\260105")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import report_generator as rg


def main() -> None:
    root = Path(r"d:\Project\devops\260105\backend\reports\uds_local")
    payloads = sorted(root.glob("uds_payload_*.json"), key=lambda p: p.stat().st_size)
    if not payloads:
        raise RuntimeError("payload not found")
    payload_file = payloads[0]
    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    out = root / f"uds_regen_dedupe_{time.strftime('%Y%m%d_%H%M%S')}.docx"
    tpl = Path(
        r"d:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"
    )
    rg.generate_uds_docx(str(tpl) if tpl.exists() else None, payload, str(out))
    print(f"payload={payload_file.name}")
    print(str(out))


if __name__ == "__main__":
    main()
