import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from workflow.uds_ai import _extract_json_payload

tests = [
    ('{"a":1}', True),
    ('```json\n{"a":1}\n```', True),
    ('{"a":1,}', True),
    ('{"a":"hello"', True),
    ('Sure! Here is JSON:\n{"a":1}', True),
    ('', False),
    ('not json', False),
]
ok = 0
for t, expect in tests:
    result = _extract_json_payload(t)
    got = result is not None
    status = "PASS" if got == expect else "FAIL"
    if status == "PASS":
        ok += 1
    print(f"{status}: input={t[:40]!r} expected={expect} got={got}")
print(f"\nTotal: {ok}/{len(tests)}")
