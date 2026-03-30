# /build_rule_catalog.py
# -*- coding: utf-8 -*-
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_rcf_file(file_path: Path) -> dict[str, str]:
    """Parses a .rcf file and extracts rule IDs and descriptions."""
    catalog = {}
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        # Find all <rule> elements with an 'id' attribute starting with 'Rule-'
        for rule_element in root.findall(".//rule[@id]"):
            rule_id_attr = rule_element.get("id", "")
            if rule_id_attr.startswith("Rule-"):
                text_element = rule_element.find("text")
                if text_element is not None and text_element.text:
                    # Key format "Rule X-Y"
                    rule_key = rule_id_attr.replace("-", " ", 1)
                    description = text_element.text.strip()
                    catalog[rule_key] = description
    except ET.ParseError as e:
        print(f"Error parsing {file_path}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred with {file_path}: {e}")
    return catalog


def main():
    """
    Parses all .rcf files in the 'rules' directory and generates a combined
    rule_catalog.json file.
    """
    rules_dir = Path("rules")
    if not rules_dir.is_dir():
        print(f"Error: Directory '{rules_dir}' not found.")
        return

    master_catalog = {}
    rcf_files = list(rules_dir.glob("*.rcf"))

    if not rcf_files:
        print("No .rcf files found in the 'rules' directory.")
        return

    print(f"Found {len(rcf_files)} RCF files to parse.")

    for rcf_file in rcf_files:
        print(f"Parsing {rcf_file.name}...")
        catalog = parse_rcf_file(rcf_file)
        master_catalog.update(catalog)
        print(f"-> Found {len(catalog)} rules.")

    output_path = rules_dir / "rule_catalog.json"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(master_catalog, f, ensure_ascii=False, indent=2)
        print(f"\nSuccessfully generated {output_path} with {len(master_catalog)} total rules.")
    except Exception as e:
        print(f"\nError writing to {output_path}: {e}")


if __name__ == "__main__":
    main()
