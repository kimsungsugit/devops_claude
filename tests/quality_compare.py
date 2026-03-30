"""
Before/After Quality Comparison Script.
Runs the same measurements and compares with baseline_before.json.
"""

import json
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.quality_baseline import (
    _measure_srs_parsing,
    _measure_sds_parsing,
    _measure_reference_suds_extraction,
    _measure_code_analysis,
    _measure_json_parsing,
)


def main():
    before_path = Path(__file__).parent / "baseline_before.json"
    if not before_path.exists():
        print("ERROR: baseline_before.json not found")
        return

    before = json.loads(before_path.read_text(encoding="utf-8"))

    print("=" * 70)
    print("UDS Quality Before/After Comparison Report")
    print("=" * 70)

    after = {}
    after["srs_parsing"] = _measure_srs_parsing()
    after["sds_parsing"] = _measure_sds_parsing()
    after["reference_suds"] = _measure_reference_suds_extraction()
    after["code_analysis"] = _measure_code_analysis()
    after["json_parsing"] = _measure_json_parsing()

    after_path = Path(__file__).parent / "baseline_after.json"
    after_path.write_text(json.dumps(after, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n--- Reference SUDS Field Fill Rates ---")
    print(f"{'Field':<20} {'Before':>10} {'After':>10} {'Change':>10}")
    print("-" * 52)
    ref_fields = ["description", "inputs", "outputs", "globals_static",
                  "globals_global", "called", "calling", "asil", "related"]
    for field in ref_fields:
        b_rate = before.get("reference_suds", {}).get(f"{field}_rate", "N/A")
        a_rate = after.get("reference_suds", {}).get(f"{field}_rate", "N/A")
        if isinstance(b_rate, (int, float)) and isinstance(a_rate, (int, float)):
            change = a_rate - b_rate
            symbol = "+" if change > 0 else ""
            print(f"{field:<20} {b_rate:>9.1%} {a_rate:>9.1%} {symbol}{change:>8.1%}")
        else:
            print(f"{field:<20} {str(b_rate):>10} {str(a_rate):>10} {'N/A':>10}")

    print("\n--- JSON Parsing ---")
    b_success = before.get("json_parsing", {}).get("success", 0)
    b_total = before.get("json_parsing", {}).get("total_samples", 0)
    a_success = after.get("json_parsing", {}).get("success", 0)
    a_total = after.get("json_parsing", {}).get("total_samples", 0)
    print(f"  Before: {b_success}/{b_total}")
    print(f"  After:  {a_success}/{a_total}")

    print("\n--- SRS Parsing ---")
    b_count = before.get("srs_parsing", {}).get("txt_primary_count", 0)
    a_count = after.get("srs_parsing", {}).get("txt_primary_count", 0)
    print(f"  Requirements extracted: {b_count} -> {a_count}")

    print("\n--- Quality Gate Summary ---")
    thresholds = {
        "description": 0.9,
        "inputs": 0.5,
        "outputs": 0.7,
        "globals_static": 0.05,
        "called": 0.9,
        "calling": 0.5,
        "asil": 0.5,
    }
    b_pass = 0
    a_pass = 0
    for field, threshold in thresholds.items():
        b_rate = before.get("reference_suds", {}).get(f"{field}_rate", 0) or 0
        a_rate = after.get("reference_suds", {}).get(f"{field}_rate", 0) or 0
        b_ok = b_rate >= threshold
        a_ok = a_rate >= threshold
        if b_ok:
            b_pass += 1
        if a_ok:
            a_pass += 1
        status = "PASS" if a_ok else "FAIL"
        print(f"  {field:<20} threshold={threshold:.0%}  before={'PASS' if b_ok else 'FAIL'}  after={status}")

    print(f"\n  Quality Gate: {b_pass}/{len(thresholds)} -> {a_pass}/{len(thresholds)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
