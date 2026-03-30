from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

repo_root = Path(r"D:\Project\devops\260105")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import report_generator as rg


def _extract_doc_fn_info(path: Path) -> Dict[str, Dict[str, str]]:
    data = rg._extract_function_info_from_docx(docx.Document(str(path)))
    out: Dict[str, Dict[str, str]] = {}
    for _fid, row in data.items():
        name = str(row.get("name") or "").strip().lower()
        if not name:
            continue
        out[name] = row
    return out


def _names_from_field(text: str) -> Set[str]:
    items: Set[str] = set()
    for line in str(text or "").splitlines():
        raw = line.strip().rstrip(";")
        if not raw:
            continue
        m = re.search(r"\b([A-Za-z_]\w*)\s*\(", raw)
        if m:
            items.add(m.group(1))
        else:
            if re.match(r"^[A-Za-z_]\w*$", raw):
                items.add(raw)
    return items


def _build_expected_maps(source_sections: Dict[str, object]) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, str]]:
    details_by_name = source_sections.get("function_details_by_name", {}) or {}
    module_map = source_sections.get("module_map", {}) or {}
    exp_called: Dict[str, Set[str]] = {}
    exp_calling: Dict[str, Set[str]] = {}
    fn_to_swcom: Dict[str, str] = {}
    # function -> swcom id from table rows
    for row in source_sections.get("function_table_rows", []) or []:
        if not isinstance(row, list) or len(row) < 4:
            continue
        swcom = str(row[0] or "").strip()
        name = str(row[3] or "").strip().lower()
        if swcom and name:
            fn_to_swcom[name] = swcom
    # called map
    for name, info in details_by_name.items():
        if not isinstance(info, dict):
            continue
        calls = [str(x).strip() for x in (info.get("calls_list") or []) if str(x).strip()]
        exp_called[str(name).lower()] = set(calls)
    # reverse
    for caller, callees in exp_called.items():
        for callee in callees:
            exp_calling.setdefault(callee.lower(), set()).add(caller)
    return exp_called, exp_calling, fn_to_swcom


def _ratio(a: int, b: int) -> str:
    if b <= 0:
        return "0.0%"
    return f"{(a / b) * 100:.1f}%"


def main() -> None:
    repo = repo_root
    report_dir = repo / "backend" / "reports" / "uds_local"
    docx_files = sorted(report_dir.glob("uds_spec_generated_expanded_*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docx_files:
        raise FileNotFoundError(f"No generated UDS docx found in {report_dir}")
    target_doc = docx_files[0]
    out = report_dir / "called_calling_accuracy_latest.md"
    report_path = rg.generate_called_calling_accuracy_report(
        str(target_doc),
        str(Path(r"D:\Project\Ados\PDS_64_RD")),
        str(out),
        relation_mode="code",
    )
    print(report_path)


if __name__ == "__main__":
    main()
