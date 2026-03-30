import sys, io, docx
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'D:\Project\devops\260105')
from report_generator import _extract_function_info_from_docx
doc = docx.Document(r'D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx')
fn_map = _extract_function_info_from_docx(doc)
na_count = 0
empty_count = 0
filled_count = 0
na_values = {}
empty_ids = []
for fid, info in fn_map.items():
    c = str(info.get("calling") or "").strip()
    if not c:
        empty_count += 1
        empty_ids.append(fid)
    elif c.upper() in ("N/A", "TBD", "-", "NONE"):
        na_count += 1
        na_values.setdefault(c, []).append(fid)
    else:
        filled_count += 1

print(f"Total: {len(fn_map)}")
print(f"Filled (non-empty, non-N/A): {filled_count}")
print(f"N/A-like values: {na_count}")
for val, ids in na_values.items():
    print(f"  '{val}': {len(ids)} functions")
print(f"Empty (no calling key or empty string): {empty_count}")
print()
print(f"--- _filled() would count as filled: {filled_count}/{len(fn_map)} = {filled_count/len(fn_map)*100:.1f}%")
print(f"--- If N/A counted as filled: {filled_count + na_count}/{len(fn_map)} = {(filled_count + na_count)/len(fn_map)*100:.1f}%")
print()

if empty_ids:
    print(f"--- First 10 empty calling IDs: {empty_ids[:10]}")

has_calling_key = sum(1 for fid, info in fn_map.items() if "calling" in info)
no_calling_key = sum(1 for fid, info in fn_map.items() if "calling" not in info)
print(f"\n--- Has 'calling' key in dict: {has_calling_key}")
print(f"--- Missing 'calling' key entirely: {no_calling_key}")

if no_calling_key > 0:
    missing_ids = [fid for fid, info in fn_map.items() if "calling" not in info]
    print(f"--- First 10 missing 'calling' key IDs: {missing_ids[:10]}")
