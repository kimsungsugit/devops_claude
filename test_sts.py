# -*- coding: utf-8 -*-
"""Quick integration test for sts_generator."""
import sys, os, json
os.chdir(r"D:\Project\devops\260105")
sys.path.insert(0, ".")

from sts_generator import (
    parse_requirements_structured,
    map_requirements_to_functions,
    generate_test_cases,
    generate_traceability_matrix,
    generate_quality_report,
    generate_sts_xlsm,
)

req_texts = [
    "SwEI_01 External Interface Check - LIN data transfer [ASIL:ASIL A]",
    "SwEI_02 CAN Interface - CAN bus normal operation",
    "SwTR_0101 Door Motor Speed - motor speed control [ASIL:ASIL B] [Related:SwCom_01]",
    "SwTR_0102 Anti-Pinch Protection - pinch protection [ASIL:ASIL B]",
    "SwTR_0201 Buzzer Control - buzzer warning control",
    "SwTSR_0101 Safety Shutdown - emergency stop [ASIL:ASIL B]",
    "SwNTR_0101 Watchdog Timer - watchdog refresh",
    "SwNTR_0201 Memory Check - memory integrity",
    "SwNTSR_0101 Boot Sequence Safety - boot safety [ASIL:ASIL A]",
]

function_details = {
    "SwUFn_0101": {
        "id": "SwUFn_0101", "name": "s_MotorSpdCtrl",
        "related": "SwTR_0101", "inputs": ["u8g_TargetSpeed: u8"],
        "calls_list": ["s_MotorSpdCtrl_OpenAstOffsetCalc", "s_MotorSpdCtrl_OpenAstVsupRatioCalc"],
        "logic_flow": [
            {"type": "call", "name": "s_MotorSpdCtrl_OpenAstOffsetCalc"},
            {"type": "if", "condition": "u8g_DoorPreCtrl_DecelDrMovSpd_F == VALID",
             "true_body": [{"type": "call", "name": "s_MotorSpdCtrl_OpenAstOffsetCalc"}],
             "false_body": [{"type": "call", "name": "s_MotorSpdCtrl_OpenAstVsupRatioCalc"}]},
            {"type": "return", "value": ""},
        ],
    },
    "SwUFn_0201": {
        "id": "SwUFn_0201", "name": "s_AntiPinchCheck",
        "related": "SwTR_0102", "inputs": ["u8g_Position: u16", "u8g_Force: u16"],
        "calls_list": ["s_AntiPinchCalc", "s_MotorStop"],
        "logic_flow": [
            {"type": "call", "name": "s_AntiPinchCalc"},
            {"type": "if", "condition": "u8g_Force > THRESHOLD",
             "true_body": [{"type": "call", "name": "s_MotorStop"}, {"type": "return", "value": "E_NOT_OK"}],
             "false_body": []},
            {"type": "return", "value": "E_OK"},
        ],
    },
    "SwUFn_0301": {
        "id": "SwUFn_0301", "name": "g_Ap_BuzzerCtrl_Func",
        "related": "SwTR_0201", "inputs": [],
        "calls_list": ["s_BuzzerStateCtrl", "s_BuzzerStateStop"],
        "logic_flow": [
            {"type": "switch", "expr": "u8g_BuzzerState",
             "cases": [
                 {"label": "STATE_ON", "calls": ["s_BuzzerStateCtrl"]},
                 {"label": "STATE_OFF", "calls": ["s_BuzzerStateStop"]},
             ],
             "default_calls": ["s_BuzzerStateStop"]},
        ],
    },
    "SwUFn_0401": {
        "id": "SwUFn_0401", "name": "s_WatchdogRefresh",
        "related": "SwNTR_0101", "inputs": [],
        "calls_list": [],
        "logic_flow": [],
    },
}

# 1. Parse requirements
reqs = parse_requirements_structured(req_texts)
print(f"Parsed {len(reqs)} requirements")
for r in reqs:
    print(f"  {r['id']} [{r['req_type']}] ASIL={r.get('asil','-')}")

# 2. Map
req_to_fids = map_requirements_to_functions(reqs, function_details)
print(f"\nMappings:")
for rid, fids in req_to_fids.items():
    print(f"  {rid} -> {fids}")

# 3. Generate TCs
tcs = generate_test_cases(reqs, function_details, req_to_fids)
print(f"\nGenerated {len(tcs)} test cases:")
for tc in tcs:
    print(f"  {tc['id']} | {tc['test_method']}/{tc['gen_method']} | safety={tc['safety_related']} | steps={len(tc['steps'])}")
    for i, st in enumerate(tc["steps"]):
        print(f"    [{i+1}] {st['action'][:60]} => {st['expected'][:60]}")

# 4. Traceability
trace = generate_traceability_matrix(tcs, reqs)
print(f"\nTraceability: {trace['coverage']}")

# 5. Quality
qr = generate_quality_report(tcs, trace)
print(f"\nQuality Report:")
for k, v in qr.items():
    print(f"  {k}: {v}")

# 6. Write XLSM
out = generate_sts_xlsm(None, tcs, trace, "test_sts_output.xlsx",
                         {"project_id": "HDPDM01", "doc_id": "HDPDM01-STS-0827", "version": "v1.00", "asil_level": "ASIL A"})
print(f"\nOutput: {out}")
print(f"File size: {os.path.getsize(out)/1024:.1f} KB")
print("\nALL TESTS PASSED")
