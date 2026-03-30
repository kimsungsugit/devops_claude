"""
UDS Quality Baseline Measurement Script

Measures current quality metrics using actual input data:
- SRS/SDS DOCX parsing rates
- Reference SUDS DOCX extraction rates (inputs/outputs/globals_static)
- Code analysis coverage
- AI JSON parsing robustness
"""

import json
import sys
import os
import re
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SRS_DOCX = REPO_ROOT / "docs" / "(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx"
SDS_DOCX = REPO_ROOT / "docs" / "(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
REF_SUDS = REPO_ROOT / "docs" / "(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"
SRS_TXT = REPO_ROOT / "docs" / "HDPDM01_SRS.txt"
SDS_TXT = REPO_ROOT / "docs" / "HDPDM01_SDS.txt"
SOURCE_ROOT = Path(r"D:\Project\Ados\PDS_64_RD")

MALFORMED_JSON_SAMPLES = [
    '{"overview": {"text": "hello"}, "requirements": {"text": "world"}}',
    '```json\n{"overview": {"text": "hello"}}\n```',
    '{"overview": {"text": "hello",}, "requirements": {"text": "world"}}',
    '{"overview": {"text": "hello"',
    'Sure! Here is the JSON:\n{"overview": {"text": "test"}}',
    '',
    'not json at all',
]


def _measure_srs_parsing() -> Dict[str, Any]:
    """Measure SRS document parsing success rate."""
    from report_generator import (
        _extract_requirements_from_doc,
        _extract_requirements_fallback,
    )

    results = {"txt_available": SRS_TXT.exists(), "docx_available": SRS_DOCX.exists()}

    if SRS_TXT.exists():
        text = SRS_TXT.read_text(encoding="utf-8", errors="replace")
        primary = _extract_requirements_from_doc(text)
        fallback = _extract_requirements_fallback(text)
        results["txt_primary_count"] = len(primary)
        results["txt_fallback_count"] = len(fallback)
        results["txt_primary_success"] = len(primary) > 0

        blocks_with_asil = 0
        blocks_with_related = 0
        for line in primary:
            if re.search(r"ASIL[:\s]*[A-DQ]", line, re.I):
                blocks_with_asil += 1
            if re.search(r"\bSw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+\b", line):
                blocks_with_related += 1
        results["txt_blocks_with_asil"] = blocks_with_asil
        results["txt_blocks_with_related_id"] = blocks_with_related

    if SRS_DOCX.exists():
        try:
            from workflow.rag import _read_text_from_file
            docx_text = _read_text_from_file(SRS_DOCX)
            results["docx_text_length"] = len(docx_text)
            primary = _extract_requirements_from_doc(docx_text)
            fallback = _extract_requirements_fallback(docx_text)
            results["docx_primary_count"] = len(primary)
            results["docx_fallback_count"] = len(fallback)
            results["docx_primary_success"] = len(primary) > 0
        except Exception as e:
            results["docx_error"] = str(e)

    return results


def _measure_sds_parsing() -> Dict[str, Any]:
    """Measure SDS document parsing success rate."""
    results = {"txt_available": SDS_TXT.exists(), "docx_available": SDS_DOCX.exists()}

    if SDS_DOCX.exists():
        try:
            from report_generator import _extract_sds_partition_map
            partition_map = _extract_sds_partition_map(str(SDS_DOCX))
            results["partition_count"] = len(partition_map)
            with_asil = sum(1 for v in partition_map.values() if v.get("asil"))
            with_related = sum(1 for v in partition_map.values() if v.get("related"))
            results["partitions_with_asil"] = with_asil
            results["partitions_with_related"] = with_related
        except Exception as e:
            results["docx_error"] = str(e)

    if SDS_TXT.exists():
        text = SDS_TXT.read_text(encoding="utf-8", errors="replace")
        swcom_ids = set(re.findall(r"\bSwCom_\d+\b", text))
        results["txt_swcom_count"] = len(swcom_ids)

    return results


def _measure_reference_suds_extraction() -> Dict[str, Any]:
    """Measure reference SUDS DOCX field extraction rates."""
    results = {"available": REF_SUDS.exists()}
    if not REF_SUDS.exists():
        return results

    try:
        import docx as _docx
        from report_generator import _extract_function_info_from_docx

        doc = _docx.Document(str(REF_SUDS))
        fn_map = _extract_function_info_from_docx(doc)
        total = len(fn_map)
        results["total_functions"] = total

        if total == 0:
            return results

        def _filled(v: Any) -> bool:
            if isinstance(v, list):
                return len(v) > 0
            s = str(v or "").strip()
            return bool(s) and s.upper() not in {"N/A", "TBD", "-", "NONE", ""}

        def _present(v: Any) -> bool:
            """N/A is considered valid (field is present and explicitly set)."""
            if isinstance(v, list):
                return len(v) > 0
            s = str(v or "").strip()
            return bool(s)

        na_valid_fields = {"called", "calling", "precondition"}

        fields = ["name", "prototype", "description", "asil", "related",
                   "inputs", "outputs", "globals_global", "globals_static",
                   "called", "calling", "precondition"]
        for field in fields:
            checker = _present if field in na_valid_fields else _filled
            count = sum(1 for info in fn_map.values() if checker(info.get(field)))
            results[f"{field}_filled"] = count
            results[f"{field}_rate"] = round(count / total, 4)

        void_funcs = sum(
            1 for info in fn_map.values()
            if isinstance(info, dict) and "void" in str(info.get("prototype") or "").lower().split("(", 1)[-1]
        )
        non_void = total - void_funcs
        inputs_non_void = sum(
            1 for info in fn_map.values()
            if isinstance(info, dict)
            and "void" not in str(info.get("prototype") or "").lower().split("(", 1)[-1]
            and _filled(info.get("inputs"))
        )
        results["void_param_functions"] = void_funcs
        results["inputs_non_void_filled"] = inputs_non_void
        results["inputs_non_void_rate"] = round(inputs_non_void / non_void, 4) if non_void > 0 else 0.0

        try:
            from report_generator import _classify_description_quality
            desc_high = desc_med = desc_low = 0
            tbd_asil = tbd_related = 0
            for info in fn_map.values():
                if not isinstance(info, dict):
                    continue
                q = _classify_description_quality(
                    str(info.get("description") or ""),
                    str(info.get("description_source") or ""),
                )
                if q == "high":
                    desc_high += 1
                elif q == "medium":
                    desc_med += 1
                else:
                    desc_low += 1
                if str(info.get("asil") or "").strip().upper() == "TBD":
                    tbd_asil += 1
                if str(info.get("related") or "").strip().upper() == "TBD":
                    tbd_related += 1
            results["desc_quality_high"] = desc_high
            results["desc_quality_medium"] = desc_med
            results["desc_quality_low"] = desc_low
            results["tbd_asil_count"] = tbd_asil
            results["tbd_related_count"] = tbd_related
        except Exception:
            pass

    except Exception as e:
        results["error"] = str(e)

    return results


def _measure_code_analysis() -> Dict[str, Any]:
    """Measure code analysis coverage on PDS_64_RD."""
    results = {"source_root_exists": SOURCE_ROOT.exists()}
    if not SOURCE_ROOT.exists():
        return results

    c_files = list(SOURCE_ROOT.rglob("*.c"))
    h_files = list(SOURCE_ROOT.rglob("*.h"))
    results["c_files"] = len(c_files)
    results["h_files"] = len(h_files)
    results["total_files"] = len(c_files) + len(h_files)

    global_vars = []
    static_vars = []
    functions_g = []
    functions_s = []
    static_prefix_re = re.compile(r"\b[us]\d+s_\w+")
    global_prefix_re = re.compile(r"\b[us]\d+g_\w+")

    for f in c_files + h_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for m in global_prefix_re.finditer(text):
            global_vars.append(m.group())
        for m in static_prefix_re.finditer(text):
            static_vars.append(m.group())

        for m in re.finditer(r"\bvoid\s+(g_\w+)\s*\(", text):
            functions_g.append(m.group(1))
        for m in re.finditer(r"\bstatic\s+void\s+(s_\w+)\s*\(", text):
            functions_s.append(m.group(1))
        for m in re.finditer(r"\bvoid\s+(s_\w+)\s*\(", text):
            functions_s.append(m.group(1))

    results["global_var_names"] = len(set(global_vars))
    results["static_var_names"] = len(set(static_vars))
    results["interface_functions"] = len(set(functions_g))
    results["internal_functions"] = len(set(functions_s))
    results["naming_convention_detected"] = len(set(global_vars)) > 0 or len(set(static_vars)) > 0

    return results


def _measure_json_parsing() -> Dict[str, Any]:
    """Test JSON parsing robustness with various malformed inputs."""
    from workflow.uds_ai import _extract_json_payload

    results = {"total_samples": len(MALFORMED_JSON_SAMPLES), "success": 0, "failure": 0}
    details = []
    for i, sample in enumerate(MALFORMED_JSON_SAMPLES):
        parsed = _extract_json_payload(sample)
        ok = parsed is not None
        if ok:
            results["success"] += 1
        else:
            results["failure"] += 1
        details.append({"index": i, "length": len(sample), "parsed": ok})
    results["details"] = details
    results["success_rate"] = round(results["success"] / max(results["total_samples"], 1), 4)
    return results


def main():
    print("=" * 60)
    print("UDS Quality Baseline Measurement")
    print("=" * 60)

    baseline: Dict[str, Any] = {}

    print("\n[1/5] Measuring SRS parsing...")
    baseline["srs_parsing"] = _measure_srs_parsing()
    print(f"  TXT primary: {baseline['srs_parsing'].get('txt_primary_count', 'N/A')}")
    print(f"  DOCX primary: {baseline['srs_parsing'].get('docx_primary_count', 'N/A')}")

    print("\n[2/5] Measuring SDS parsing...")
    baseline["sds_parsing"] = _measure_sds_parsing()
    print(f"  Partition count: {baseline['sds_parsing'].get('partition_count', 'N/A')}")

    print("\n[3/5] Measuring reference SUDS extraction...")
    baseline["reference_suds"] = _measure_reference_suds_extraction()
    ref = baseline["reference_suds"]
    print(f"  Total functions: {ref.get('total_functions', 'N/A')}")
    for field in ["inputs", "outputs", "globals_static", "description", "called", "calling"]:
        rate = ref.get(f"{field}_rate", "N/A")
        filled = ref.get(f"{field}_filled", "N/A")
        print(f"  {field}: {filled} ({rate})")

    print("\n[4/5] Measuring code analysis coverage...")
    baseline["code_analysis"] = _measure_code_analysis()
    ca = baseline["code_analysis"]
    print(f"  Files: {ca.get('total_files', 'N/A')} (C: {ca.get('c_files', 'N/A')}, H: {ca.get('h_files', 'N/A')})")
    print(f"  Global vars: {ca.get('global_var_names', 'N/A')}, Static vars: {ca.get('static_var_names', 'N/A')}")
    print(f"  Interface funcs: {ca.get('interface_functions', 'N/A')}, Internal funcs: {ca.get('internal_functions', 'N/A')}")

    print("\n[5/5] Measuring JSON parsing robustness...")
    baseline["json_parsing"] = _measure_json_parsing()
    print(f"  Success: {baseline['json_parsing']['success']}/{baseline['json_parsing']['total_samples']}")

    out_path = Path(__file__).parent / "baseline_before.json"
    out_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nBaseline saved to: {out_path}")
    print("=" * 60)

    return baseline


if __name__ == "__main__":
    main()
