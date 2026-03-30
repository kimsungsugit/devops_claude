"""SUTS (Software Unit Test Specification) auto-generation engine.

Generates XLSM output from UDS function details and source code analysis.
Each unit function gets a dedicated TC with input/output variable columns
and multiple test sequences (boundary values, error conditions, etc.).
"""
from __future__ import annotations

import logging
import re
import time
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from report_gen.requirements import _extract_sds_partition_map

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INPUT_COL_START = 14      # C14
_INPUT_COL_END = 62        # C62  (max 49 input vars)
_OUTPUT_COL_START = 63     # C63
_OUTPUT_COL_END = 148      # C148 (max 86 output vars)
_RELATED_COL = 149         # C149
_SEQ_COL = 13              # C13

_MAX_SEQUENCES = 10
_DEFAULT_SEQ_COUNT = 6

_GEN_METHODS = {"AEC, ABV", "ABV, AOR", "AOR", "ABV"}
_DEFAULT_GEN_METHOD = "AEC, ABV"
_DEFAULT_TEST_ENV = "SwTE_01"

_SDS_MAP_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def _load_default_sds_map() -> Dict[str, Dict[str, str]]:
    global _SDS_MAP_CACHE
    if _SDS_MAP_CACHE is not None:
        return _SDS_MAP_CACHE
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    merged: Dict[str, Dict[str, str]] = {}
    if docs_dir.exists():
        for path in docs_dir.glob("*.docx"):
            if "sds" not in path.name.lower():
                continue
            data = _extract_sds_partition_map(str(path))
            for key, value in data.items():
                if key not in merged:
                    merged[key] = dict(value)
                    continue
                for field in ("asil", "related", "description"):
                    if value.get(field) and not merged[key].get(field):
                        merged[key][field] = value[field]
    _SDS_MAP_CACHE = merged
    return merged


def _resolve_unit_asil(info: Dict[str, Any], sds_map: Dict[str, Dict[str, str]]) -> str:
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

    module_name = str(info.get("module_name") or "").strip()
    candidates: List[str] = []
    if module_name:
        candidates.append(module_name)
        base = re.sub(r"_pds$", "", module_name, flags=re.I)
        candidates.append(base)
        tokenized = re.sub(r"([a-z])([A-Z])", r"\1 \2", base.replace("_", " "))
        tokenized = re.sub(r"\bctrl\b", "control", tokenized, flags=re.I)
        tokenized = re.sub(r"\bdiag\b", "diagnostic", tokenized, flags=re.I)
        words = [w for w in tokenized.split() if w.lower() not in {"ap", "drv", "sys", "pds", "main", "func"}]
        if words:
            candidates.append(" ".join(words))
    for candidate in candidates:
        direct = sds_map.get(candidate.lower())
        if direct and direct.get("asil"):
            return str(direct["asil"]).strip()
    for candidate in candidates:
        nc = _norm(candidate)
        if not nc:
            continue
        for key, value in sds_map.items():
            nk = _norm(key)
            if not nk:
                continue
            if nc == nk or nc in nk or nk in nc:
                return str(value.get("asil") or "").strip()
    return ""

_SRS_REQ_ID_PAT = re.compile(
    r"\b(?:SW[_R]?|SRS|Sw|HDPDM\d*|SWR|SWS|SYSRS)[_-]?\d[\w_-]*",
    re.I,
)


def _resolve_srs_req_ids_for_function(
    func_name: str,
    sds_map: Dict[str, Dict[str, str]],
) -> str:
    """Resolve SRS requirement IDs for a function via SDS partition map `related` field."""
    if not sds_map or not func_name:
        return ""
    candidates = [func_name.lower(), func_name.lower().replace("_", " ")]
    for candidate in candidates:
        entry = sds_map.get(candidate)
        if entry:
            related = str(entry.get("related", "") or "")
            ids = _SRS_REQ_ID_PAT.findall(related)
            if ids:
                return ", ".join(ids[:4])
    # Fuzzy: partial name match
    fn_lower = func_name.lower()
    for key, entry in sds_map.items():
        if fn_lower in key or key in fn_lower:
            related = str(entry.get("related", "") or "")
            ids = _SRS_REQ_ID_PAT.findall(related)
            if ids:
                return ", ".join(ids[:4])
    return ""


# C type boundary values (min_invalid, min_valid, zero, mid, max_valid, max_invalid)
_TYPE_BOUNDARIES: Dict[str, Dict[str, Any]] = {
    "uint8_t":  {"min_inv": -1,     "min": 0,      "mid": 127,   "max": 255,     "max_inv": 256},
    "uint8":    {"min_inv": -1,     "min": 0,      "mid": 127,   "max": 255,     "max_inv": 256},
    "uint16_t": {"min_inv": -1,     "min": 0,      "mid": 32767, "max": 65535,   "max_inv": 65536},
    "uint16":   {"min_inv": -1,     "min": 0,      "mid": 32767, "max": 65535,   "max_inv": 65536},
    "uint32_t": {"min_inv": -1,     "min": 0,      "mid": 2**15, "max": 2**32-1, "max_inv": 2**32},
    "int8_t":   {"min_inv": -129,   "min": -128,   "mid": 0,     "max": 127,     "max_inv": 128},
    "int16_t":  {"min_inv": -32769, "min": -32768, "mid": 0,     "max": 32767,   "max_inv": 32768},
    "int16":    {"min_inv": -32769, "min": -32768, "mid": 0,     "max": 32767,   "max_inv": 32768},
    "int32_t":  {"min_inv": -(2**31)-1, "min": -(2**31), "mid": 0, "max": 2**31-1, "max_inv": 2**31},
    "float":    {"min_inv": -1001.0, "min": -1000.0, "mid": 0.0,  "max": 1000.0,  "max_inv": 1001.0},
    "bool":     {"min_inv": -1,     "min": 0,       "mid": 0,    "max": 1,       "max_inv": 2},
    "bit":      {"min_inv": -1,     "min": 0,       "mid": 0,    "max": 1,       "max_inv": 2},
}
_DEFAULT_BOUNDARY = {"min_inv": -1, "min": 0, "mid": 127, "max": 255, "max_inv": 256}

# Domain-keyword based float boundaries for physical/engineering signals
_FLOAT_DOMAIN_BOUNDS: List[Tuple[List[str], Dict[str, Any]]] = [
    (["voltage", "volt", "_v_", "_vbat", "_vcc"],
     {"min_inv": -1.0, "min": 0.0, "mid": 12.0, "max": 60.0, "max_inv": 61.0}),
    (["temperature", "temp", "_temp", "_t_"],
     {"min_inv": -41.0, "min": -40.0, "mid": 25.0, "max": 150.0, "max_inv": 151.0}),
    (["speed", "_spd", "velocity", "_vel"],
     {"min_inv": -1.0, "min": 0.0, "mid": 60.0, "max": 300.0, "max_inv": 301.0}),
    (["pressure", "_pres", "_press"],
     {"min_inv": -0.1, "min": 0.0, "mid": 2.5, "max": 10.0, "max_inv": 10.1}),
    (["current", "_cur", "_amp"],
     {"min_inv": -0.1, "min": 0.0, "mid": 5.0, "max": 50.0, "max_inv": 51.0}),
    (["angle", "_ang", "degree", "_deg"],
     {"min_inv": -1.0, "min": 0.0, "mid": 90.0, "max": 360.0, "max_inv": 361.0}),
    (["percent", "_pct", "ratio", "_ratio"],
     {"min_inv": -1.0, "min": 0.0, "mid": 50.0, "max": 100.0, "max_inv": 101.0}),
]


def _get_float_bounds_for_var(var_name: str) -> Dict[str, Any]:
    """Return domain-specific float boundaries based on variable name keywords."""
    name_lower = var_name.lower()
    for keywords, bounds in _FLOAT_DOMAIN_BOUNDS:
        if any(kw in name_lower for kw in keywords):
            return bounds
    return _TYPE_BOUNDARIES["float"]


# Patterns for inferring types from variable names
_TYPE_NAME_PATTERNS = [
    (re.compile(r"\bu8[gs]?_|uint8|U8|BYTE", re.I), "uint8_t"),
    (re.compile(r"\bu16[gs]?_|uint16|U16|WORD", re.I), "uint16_t"),
    (re.compile(r"\bu32[gs]?_|uint32|U32|DWORD", re.I), "uint32_t"),
    (re.compile(r"\bs8[gs]?_|int8[^_]|S8", re.I), "int8_t"),
    (re.compile(r"\bs16[gs]?_|int16|S16", re.I), "int16_t"),
    (re.compile(r"\bs32[gs]?_|int32|S32", re.I), "int32_t"),
    (re.compile(r"\bBits\.|_F\b|_Flag|_Sta\b|_Enable|_Disable", re.I), "bit"),
    (re.compile(r"\bf32|float|FLOAT", re.I), "float"),
    (re.compile(r"\bbool\b|BOOL|boolean", re.I), "bool"),
]


# ---------------------------------------------------------------------------
# Phase 1: Data extraction
# ---------------------------------------------------------------------------

_TYPE_NAMES = {
    "U8", "U16", "U32", "S8", "S16", "S32",
    "uint8_t", "uint16_t", "uint32_t", "int8_t", "int16_t", "int32_t",
    "BOOL", "void", "char", "int", "float", "double", "long",
    "unsigned", "signed", "short", "const", "volatile", "static",
}

# Local temp variable prefixes — these live on stack, not meaningful for unit test I/O
_LOCAL_TEMP_PATS = re.compile(
    r"^(u8t_|u16t_|u32t_|s8t_|s16t_|s32t_|sf_t|tmpVal|temp_|tmp_|loop_|idx_|cnt_|i$|j$|k$|n$)",
    re.I,
)

# Prefixes that are clearly global reads (function inputs)
_INPUT_PREFIXES = ("u8g_", "u16g_", "u32g_", "s16g_", "s8g_", "s32g_")
# Prefixes that are clearly module-static writes (function outputs)
_OUTPUT_PREFIXES = ("u8s_", "u16s_", "u32s_", "s16s_", "s32s_")
# Hardware registers — typically both read and written
_REG_PAT = re.compile(r"^REG_|^lin_|^PS\.|^DiagData\.")


def collect_unit_functions(
    function_details: Dict[str, Dict[str, Any]],
    globals_info_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Collect and structure unit functions from report_generator output.

    Matching reference SUTS patterns: variables can appear as BOTH input and
    output (read-modify-write). Local temps are excluded. REG_ and state
    vars are placed in output. Caps at reasonable counts per function.
    """
    gim = globals_info_map or {}
    sds_map = _load_default_sds_map()
    units: List[Dict[str, Any]] = []

    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        name = info.get("name", "")
        if not name:
            continue

        prototype = info.get("prototype") or f"void {name}(void)"
        inputs_raw = info.get("inputs") or []
        outputs_raw = info.get("outputs") or []
        globals_g = info.get("globals_global") or []
        globals_s = info.get("globals_static") or []

        input_vars: List[str] = _extract_var_names(inputs_raw)
        output_vars: List[str] = _extract_var_names(outputs_raw)

        inp_set = set(input_vars)
        out_set = set(output_vars)

        globals_g_set = set(globals_g)

        for g in globals_g + globals_s:
            gn = _clean_global_name(g)
            if not gn or gn in _TYPE_NAMES:
                continue
            if len(gn) <= 2 or not re.match(r"[A-Za-z_]", gn):
                continue
            if _LOCAL_TEMP_PATS.match(gn):
                continue

            tag = str(g).upper()
            is_indirect = "[INDIRECT]" in tag
            is_in_global = g in globals_g_set

            role_in = False
            role_out = False

            if any(k in tag for k in ["[IN]", "READ", "RHS"]):
                role_in = True
            if any(k in tag for k in ["[OUT]", "WRITE", "LHS"]):
                role_out = True

            if not role_in and not role_out:
                if gn.startswith(_OUTPUT_PREFIXES):
                    role_out = True
                elif gn.startswith(_INPUT_PREFIXES):
                    if not is_indirect:
                        role_in = True
                elif _REG_PAT.match(gn):
                    if not is_indirect:
                        role_in = True
                    role_out = True
                elif gn.startswith(("g_", "r_")):
                    if not is_indirect:
                        role_in = True
                    role_out = True
                elif not is_in_global:
                    role_out = True
                elif not is_indirect:
                    role_in = True

            if role_in and gn not in inp_set:
                input_vars.append(gn)
                inp_set.add(gn)
            if role_out and gn not in out_set:
                output_vars.append(gn)
                out_set.add(gn)

        component = ""
        module = info.get("module_name", "")
        if fid and re.match(r"SwUFn_\d+", fid):
            comp_num = fid.replace("SwUFn_", "")[:2]
            component = f"SwCom_{comp_num}"
            if module:
                component = f"{component}\n({module})"

        # Attempt to resolve SRS requirement IDs via SDS partition map
        srs_req_ids = _resolve_srs_req_ids_for_function(name, sds_map)

        if not output_vars:
            ret_type = _infer_return_type(prototype)
            if ret_type and ret_type.lower() != "void":
                ret_var = f"return_{name}"
                output_vars.append(ret_var)
                out_set.add(ret_var)

        max_inp = _INPUT_COL_END - _INPUT_COL_START + 1
        max_out = _OUTPUT_COL_END - _OUTPUT_COL_START + 1

        asil = str(info.get("asil") or "TBD").strip()
        if not asil or asil.upper() == "TBD":
            asil = _resolve_unit_asil(info, sds_map) or asil

        units.append({
            "fid": fid,
            "name": name,
            "prototype": prototype,
            "component": component,
            "input_vars": input_vars[:max_inp],
            "output_vars": output_vars[:max_out],
            "logic_flow": info.get("logic_flow") or [],
            "calls_list": info.get("calls_list") or [],
            "description": info.get("description", ""),
            "asil": asil,
            "srs_req_ids": srs_req_ids,
            "precondition": info.get("precondition", ""),
        })

    units.sort(key=lambda u: u["fid"])
    _logger.info("Collected %d unit functions", len(units))
    return units


def _infer_return_type(prototype: str) -> str:
    """Extract the return type from a C function prototype string."""
    proto = prototype.strip()
    m = re.match(r"^([\w\s\*]+?)\s+\w+\s*\(", proto)
    if not m:
        return "void"
    ret = m.group(1).strip()
    ret = re.sub(r"\b(static|inline|extern|const|volatile)\b", "", ret).strip()
    return ret if ret else "void"


def _extract_var_names(raw_list: List[str]) -> List[str]:
    """Extract clean variable names from [IN]/[OUT] tagged param strings."""
    names: List[str] = []
    for raw in raw_list:
        s = str(raw).strip()
        s = re.sub(r"^\[(?:IN|OUT|INOUT)\]\s*", "", s)
        s = re.sub(r"^return\s+", "", s, flags=re.I)
        # Remove type qualifiers, keep only the symbol name
        parts = s.split()
        if not parts:
            continue
        candidate = parts[-1].strip("*&;,")
        candidate = re.sub(r"\[.*?\]$", "", candidate)
        if candidate and re.match(r"[A-Za-z_]", candidate):
            if candidate not in names:
                names.append(candidate)
    return names


def _clean_global_name(g: str) -> str:
    s = str(g).strip()
    s = re.sub(r"^\[INDIRECT\]\s*", "", s)
    s = re.sub(r"^\[(?:IN|OUT|INOUT)\]\s*", "", s)
    parts = s.split()
    return parts[-1].strip("*&;,") if parts else ""


# ---------------------------------------------------------------------------
# Phase 2: Variable type analysis
# ---------------------------------------------------------------------------

_globals_type_cache: Dict[str, str] = {}


def set_globals_type_cache(gim: Dict[str, Dict[str, str]]) -> None:
    """Populate type cache from globals_info_map for precise type resolution."""
    _globals_type_cache.clear()
    for var_name, info in gim.items():
        vtype = (info.get("type") or "").strip()
        if vtype:
            _globals_type_cache[var_name] = vtype


def infer_variable_type(var_name: str) -> str:
    """Infer C type from variable naming convention or globals_info_map."""
    if var_name in _globals_type_cache:
        raw = _globals_type_cache[var_name]
        mapped = _normalize_type(raw)
        if mapped:
            return mapped
    for pat, typename in _TYPE_NAME_PATTERNS:
        if pat.search(var_name):
            return typename
    return "uint8_t"


def _normalize_type(raw: str) -> str:
    """Map raw C type string to a known boundary type."""
    r = raw.strip().lower()
    for key in _TYPE_BOUNDARIES:
        if key in r:
            return key
    alias = {"u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t",
             "s8": "int8_t", "s16": "int16_t", "s32": "int32_t"}
    for k, v in alias.items():
        if r == k:
            return v
    return ""


def get_boundary_values(typename: str) -> Dict[str, Any]:
    normalized = typename.lower().replace(" ", "").replace("_t", "_t")
    return _TYPE_BOUNDARIES.get(normalized, _DEFAULT_BOUNDARY)


# ---------------------------------------------------------------------------
# Phase 3: Test sequence generation
# ---------------------------------------------------------------------------

def determine_gen_method(unit: Dict[str, Any]) -> str:
    """Determine TC generation method based on function characteristics."""
    logic = unit.get("logic_flow") or []
    has_conditions = any(n.get("type") in ("if", "switch") for n in logic if isinstance(n, dict))
    has_loops = any(n.get("type") == "loop" for n in logic if isinstance(n, dict))
    n_inputs = len(unit.get("input_vars", []))

    if has_conditions and n_inputs > 0:
        return "AEC, ABV"
    if n_inputs > 2:
        return "ABV, AOR"
    if n_inputs > 0:
        return "ABV"
    return "AOR"


def determine_test_method(unit: Dict[str, Any]) -> str:
    """Infer a unit-test method label for the fixed SUTS columns."""
    logic = unit.get("logic_flow") or []
    has_conditions = any(n.get("type") in ("if", "switch") for n in logic if isinstance(n, dict))
    has_loops = any(n.get("type") == "loop" for n in logic if isinstance(n, dict))
    n_inputs = len(unit.get("input_vars", []))

    if has_conditions or has_loops:
        return "FNCT"
    if n_inputs > 0:
        return "FIT"
    return "RVW"


def generate_sequences(
    unit: Dict[str, Any],
    max_seq: int = _DEFAULT_SEQ_COUNT,
) -> List[Dict[str, Any]]:
    """Generate test sequences for a unit function.

    Produces boundary-value and error-condition test sequences matching
    the reference SUTS patterns:
      Seq 1: all inputs at error-low boundary (min_inv)
      Seq 2: all inputs at minimum valid (0 for unsigned)
      Seq 3: normal mid-range values
      Seq 4: all inputs at maximum valid
      Seq 5: all inputs at error-high boundary (max_inv)
      Seq 6: mixed combination (alternating valid/boundary)
    """
    input_vars = unit.get("input_vars") or []
    output_vars = unit.get("output_vars") or []

    if not input_vars and not output_vars:
        fn_name = unit.get("name", "function")
        prototype = unit.get("prototype", "")
        is_void_return = "void" in prototype.split("(")[0].lower() if "(" in prototype else True
        calls_list = unit.get("calls_list") or []
        logic_flow = unit.get("logic_flow") or []

        # Build calls summary for description
        if calls_list:
            calls_short = calls_list[:5]
            calls_str = ", ".join(f"{c}()" for c in calls_short)
            if len(calls_list) > 5:
                calls_str += f" 외 {len(calls_list) - 5}개"
            calls_note = f" 하위 함수 [{calls_str}] 순차 호출 확인"
        else:
            calls_note = " 예외 없이 완료되며 호출 후 상태 이상 없음"

        # Extract guard condition from logic_flow for ERROR_PATH description
        guard_cond = ""
        for node in logic_flow:
            cond = str(node.get("condition", "") or node.get("text", "")).strip()
            if cond and any(op in cond for op in ("<", ">", "==", "!=", "NULL", "null")):
                guard_cond = cond[:80]
                break
        if guard_cond:
            error_desc = (
                f"{fn_name}() 에러 경로: 조건 [{guard_cond}] 위반 상태에서 호출, "
                f"에러 처리 루틴 진입 또는 안전 상태 유지 확인"
            )
        else:
            error_desc = (
                f"{fn_name}() 에러 경로: 의존 모듈/전역 변수 비정상 상태에서 호출, "
                f"에러 처리 루틴 진입 또는 안전 상태 유지 확인"
            )

        # Build inputs/expected from indirect_vars (callee global vars) if available
        indirect_vars: List[str] = unit.get("indirect_vars") or []
        normal_inputs: Dict[str, Any] = {}
        error_inputs: Dict[str, Any] = {}
        normal_expected: Dict[str, Any] = {}
        error_expected: Dict[str, Any] = {}
        if indirect_vars:
            for _iv in indirect_vars[:4]:
                _vtype = infer_variable_type(_iv)
                _bounds = (
                    _get_float_bounds_for_var(_iv) if _vtype == "float"
                    else get_boundary_values(_vtype)
                )
                normal_inputs[_iv] = _bounds.get("mid", 0)
                normal_expected[_iv] = _bounds.get("mid", 0)
                error_inputs[_iv] = _bounds.get("max_inv", _bounds.get("max", 255) + 1)
                error_expected[_iv] = _bounds.get("max", 255)  # clamped/saturated

        seqs = [
            {"seq_num": 1, "inputs": normal_inputs, "expected": normal_expected,
             "strategy": "NORMAL_CALL",
             "description": f"{fn_name}() 정상 호출:{calls_note}"},
            {"seq_num": 2, "inputs": error_inputs, "expected": error_expected,
             "strategy": "ERROR_PATH",
             "description": error_desc},
            {"seq_num": 3, "inputs": {}, "expected": {},
             "strategy": "REPEAT_CALL",
             "description": (
                 f"{fn_name}() 반복 호출 안정성: 100회 연속 호출 후 메모리 누수 없음, "
                 f"시스템 상태 일관성 유지"
             )},
        ]
        if not is_void_return:
            seqs.append({"seq_num": 4, "inputs": {}, "expected": {},
                         "strategy": "RETURN_CHECK",
                         "description": f"{fn_name}() 반환값 검증: 반환값이 정의된 범위 내 유효한 값임을 확인"})
        return seqs[:max_seq]

    var_types = {v: infer_variable_type(v) for v in input_vars}
    var_bounds = {
        v: (_get_float_bounds_for_var(v) if t == "float" else get_boundary_values(t))
        for v, t in var_types.items()
    }

    out_types = {v: infer_variable_type(v) for v in output_vars}
    out_bounds = {
        v: (_get_float_bounds_for_var(v) if t == "float" else get_boundary_values(t))
        for v, t in out_types.items()
    }

    logic_flow = unit.get("logic_flow") or []

    strategies = [
        ("BV_MIN_INV", "min_inv"),
        ("BV_MIN",     "min"),
        ("BV_MID",     "mid"),
        ("BV_MAX",     "max"),
        ("BV_MAX_INV", "max_inv"),
        ("MIXED",      None),
    ]

    _STRAT_LABEL: Dict[str, str] = {
        "BV_MIN_INV": "유효 하한 초과 (경계-1): 에러/포화 처리 확인",
        "BV_MIN":     "최솟값 경계 입력: 최솟값에서 정상 처리 확인",
        "BV_MID":     "정상 중간값 입력: 정상 동작 범위 확인",
        "BV_MAX":     "최댓값 경계 입력: 최댓값에서 정상 처리 확인",
        "BV_MAX_INV": "유효 상한 초과 (경계+1): 에러/포화 처리 확인",
        "MIXED":      "혼합 경계값: 짝수 인수=최솟값, 홀수 인수=최댓값 조합",
    }

    sequences: List[Dict[str, Any]] = []
    for idx, (strat_name, bound_key) in enumerate(strategies[:max_seq]):
        seq_num = idx + 1
        inp_vals: Dict[str, Any] = {}
        exp_vals: Dict[str, Any] = {}

        if bound_key:
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = bnd.get(bound_key, 0)
                inp_vals[v] = _format_test_value(raw, var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = _infer_expected_for_strategy(
                    bnd, bound_key, out_types.get(v, "uint8_t"), logic_flow, v
                )
                exp_vals[v] = _format_test_value(raw, out_types.get(v, "uint8_t"))
        else:
            for i, v in enumerate(input_vars):
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                key = "min" if i % 2 == 0 else "max"
                raw = bnd.get(key, 0)
                inp_vals[v] = _format_test_value(raw, var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = bnd.get("mid", 0)
                exp_vals[v] = _format_test_value(raw, out_types.get(v, "uint8_t"))

        # Build human-readable description showing actual variable names and values
        label = _STRAT_LABEL.get(strat_name, strat_name)
        inp_parts = [f"{v}={inp_vals[v]}" for v in input_vars if v in inp_vals]
        exp_parts = [f"{v}={exp_vals[v]}" for v in output_vars if v in exp_vals]
        desc_lines = [label]
        if inp_parts:
            desc_lines.append("Input: " + ", ".join(inp_parts))
        if exp_parts:
            desc_lines.append("Expected: " + ", ".join(exp_parts))
        description = "\n".join(desc_lines)

        sequences.append({
            "seq_num": seq_num,
            "inputs": inp_vals,
            "expected": exp_vals,
            "strategy": strat_name,
            "description": description,
        })

    return sequences


def _format_test_value(value: Any, typename: str) -> Any:
    """Format test values to match reference document patterns.

    - bit/bool: use hex (0x0, 0x1)
    - REG/hardware: use hex for small ints
    - others: plain integer
    """
    if value is None:
        return 0
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if typename in ("bit", "bool"):
        if isinstance(value, (int, float)):
            iv = int(value)
            if 0 <= iv <= 0xFF:
                return f"0x{iv:X}"
    return value


def _infer_expected_for_strategy(
    bounds: Dict[str, Any],
    strategy_key: str,
    typename: str,
    logic_flow: List[Dict[str, Any]],
    var_name: str,
) -> Any:
    """Infer expected output value based on input strategy and logic analysis.

    Uses logic_flow branch analysis to determine more accurate expected outputs:
    - Error-boundary inputs (min_inv/max_inv): saturation, clamping, or error flag
    - Valid boundary inputs (min/max): the boundary value itself (pass-through or capped)
    - Mid-range inputs: normal processing result
    """
    is_bit = typename in ("bit", "bool")
    has_guard = _flow_has_guard_clause(logic_flow, var_name)
    has_clamp = _flow_has_clamp_pattern(logic_flow, var_name)
    is_enable_flag = _is_enable_disable_var(var_name)
    is_counter = _is_counter_accumulator_var(var_name)
    is_state_var = _is_state_machine_var(var_name)
    bmin = bounds.get("min", 0)
    bmax = bounds.get("max", 0)
    bmid = bounds.get("mid", 0)

    # Enable/disable flag: output toggles between 0/1 on valid input
    if is_enable_flag and strategy_key in ("min", "BV_MIN"):
        return 0
    if is_enable_flag and strategy_key in ("max", "BV_MAX"):
        return 1

    # Counter/accumulator: mid-range or clamp at max on overflow
    if is_counter:
        if strategy_key == "max_inv":
            return bmax  # saturates/wraps at max
        if strategy_key == "min_inv":
            return bmin  # saturates at min

    # State machine variable: invalid input → stays in safe/init state
    if is_state_var and strategy_key in ("min_inv", "max_inv"):
        return bmin  # remain in initial/safe state on invalid transition

    if strategy_key == "min_inv":
        if is_bit:
            return bmax
        if has_clamp:
            return bmin   # clamped to lower bound
        if has_guard:
            return bmin   # guarded: stays at safe min value
        # No pattern detected: mark as needs verification
        raw = bounds.get("min_inv", bmin)
        return f"[검증 필요] {raw}"

    if strategy_key == "max_inv":
        if is_bit:
            return bmax
        if has_clamp:
            return bmax   # clamped to upper bound
        if has_guard:
            return bmax   # guarded: stays at safe max value
        # No pattern detected: mark as needs verification
        raw = bounds.get("max_inv", bmax)
        return f"[검증 필요] {raw}"

    if strategy_key == "min":
        if is_bit:
            return 0
        return bmin

    if strategy_key == "max":
        return bmax

    return bmid


def _is_enable_disable_var(var_name: str) -> bool:
    """Check if variable name indicates an enable/disable flag or activation signal."""
    name = var_name.lower()
    keywords = ("enable", "disable", "active", "flag", "en_", "_en", "on_", "_on",
                 "inhibit", "valid", "allowed", "permit")
    return any(kw in name for kw in keywords)


def _is_counter_accumulator_var(var_name: str) -> bool:
    """Check if variable name indicates a counter or accumulator."""
    name = var_name.lower()
    keywords = ("count", "cnt", "accum", "sum", "total", "index", "idx",
                 "tick", "timer", "elapsed", "delta")
    return any(kw in name for kw in keywords)


def _is_state_machine_var(var_name: str) -> bool:
    """Check if variable name indicates a state machine variable."""
    name = var_name.lower()
    keywords = ("state", "_st_", "_sts", "status", "mode", "phase", "stage",
                 "step", "fsm", "_sm_")
    return any(kw in name for kw in keywords)


def _flow_has_guard_clause(logic_flow: List[Dict[str, Any]], var_name: str) -> bool:
    """Check if logic_flow contains an if-guard referencing var_name (range check)."""
    clean = var_name.lower().strip()
    for node in logic_flow:
        cond = str(node.get("condition", "") or node.get("text", "")).lower()
        if clean in cond:
            for kw in ("<", ">", "<=", ">=", "==", "!=", "min", "max", "limit"):
                if kw in cond:
                    return True
        for child in node.get("children", []):
            if _flow_has_guard_clause([child], var_name):
                return True
    return False


def _flow_has_clamp_pattern(logic_flow: List[Dict[str, Any]], var_name: str) -> bool:
    """Check if logic_flow contains a clamp/saturation pattern for var_name."""
    clean = var_name.lower().strip()
    for node in logic_flow:
        text = str(node.get("text", "") or node.get("condition", "")).lower()
        if clean in text:
            for kw in ("clamp", "saturate", "limit", "cap", "bound", "clip"):
                if kw in text:
                    return True
            if ("=" in text) and any(w in text for w in ("max", "min", "0xff", "0xffff")):
                return True
        for child in node.get("children", []):
            if _flow_has_clamp_pattern([child], var_name):
                return True
    return False


# ---------------------------------------------------------------------------
# Phase 4: AI Enhancement (optional)
# ---------------------------------------------------------------------------

_SUTS_AI_SYSTEM_PROMPT = (
    "You are a software unit test engineer writing SUTS for automotive ECU software (ISO 26262).\n"
    "Given a C function context and test sequences, provide accurate expected output values.\n"
    "Rules:\n"
    "- Analyze the function name, description, calls, and logic conditions to infer behavior.\n"
    "- For void/no-param functions: use 'Indirect variables' as testable state variables.\n"
    "  NORMAL_CALL: expected = typical post-call values (e.g., initialized/reset state).\n"
    "  ERROR_PATH: expected = safe/default state after error (0 or initial value).\n"
    "  REPEAT_CALL: expected = same stable state (idempotent).\n"
    "- For functions with inputs: boundary-exceeding inputs → clamped/saturated expected output.\n"
    "- Return ONLY a JSON array: [{\"seq_num\":1, \"expected\":{\"var\":value,...}}, ...]\n"
    "- Only set expected values for variables that appear in 'Indirect variables' or 'Output variables'.\n"
    "- Values must be numeric (int or float). Use 0 for unknown/safe defaults."
)


_AI_TIMEOUT_SEC = 30
_AI_MAX_RETRIES = 2


def _ai_call_with_retry(agent_call_fn, ai_config, messages, *,
                         stage: str, max_retries: int = _AI_MAX_RETRIES,
                         timeout: int = _AI_TIMEOUT_SEC,
                         temperature: float = 0.2) -> str:
    """Wrapper around agent_call with timeout and retry logic."""
    import json as _json
    import threading

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        result_holder: Dict[str, Any] = {}
        exc_holder: List[Exception] = []

        def _invoke():
            try:
                r = agent_call_fn(
                    ai_config, messages,
                    role="writer", stage=stage,
                    settings={"temperature": temperature},
                )
                result_holder["val"] = r
            except Exception as ex:
                exc_holder.append(ex)

        t = threading.Thread(target=_invoke, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            _logger.warning("AI call timed out (attempt %d/%d, %ds)", attempt, max_retries, timeout)
            last_err = TimeoutError(f"AI call timed out after {timeout}s")
            continue

        if exc_holder:
            last_err = exc_holder[0]
            _logger.warning("AI call error (attempt %d/%d): %s", attempt, max_retries, last_err)
            continue

        raw = result_holder.get("val")
        reply = raw.get("output", "") if isinstance(raw, dict) else ""
        if reply:
            return reply
        _logger.warning("AI returned empty response (attempt %d/%d)", attempt, max_retries)
        last_err = ValueError("Empty AI response")

    if last_err:
        _logger.warning("AI call exhausted retries: %s", last_err)
    return ""


def _parse_ai_json(reply: str, expect_list: bool = True) -> Any:
    """Parse AI response as JSON with fallback regex extraction."""
    import json as _json
    if not reply:
        return None
    try:
        payload = _json.loads(reply) if isinstance(reply, str) else reply
        if expect_list and isinstance(payload, list):
            return payload
        if not expect_list and isinstance(payload, dict):
            return payload
        return payload
    except Exception:
        pattern = r"\[[\s\S]*\]" if expect_list else r"\{[\s\S]*\}"
        m = re.search(pattern, reply)
        if m:
            try:
                return _json.loads(m.group())
            except Exception:
                pass
    return None


def _validate_ai_sequence_item(item: Any, valid_seq_nums: set) -> bool:
    """Validate a single AI-enhanced sequence item."""
    if not isinstance(item, dict):
        return False
    if "seq_num" not in item or "expected" not in item:
        return False
    if item["seq_num"] not in valid_seq_nums:
        return False
    if not isinstance(item["expected"], dict):
        return False
    return True


def enhance_sequences_with_ai(
    unit: Dict[str, Any],
    sequences: List[Dict[str, Any]],
    ai_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Enhance expected output values using AI with timeout and retry."""
    if not ai_config:
        return sequences

    try:
        from workflow.ai import agent_call
    except ImportError:
        _logger.warning("workflow.ai not available; skipping AI enhancement")
        return sequences

    _inp_vars = unit.get("input_vars") or []
    _out_vars = unit.get("output_vars") or []
    _indirect = unit.get("indirect_vars") or []
    _calls = unit.get("calls_list") or []
    _lf = unit.get("logic_flow") or []

    # Summarise logic_flow conditions for AI context
    _cond_lines: List[str] = []
    def _collect_conds(nodes: List[Any], depth: int = 0) -> None:
        for _n in nodes:
            if not isinstance(_n, dict):
                continue
            _c = str(_n.get("condition") or _n.get("text") or "").strip()
            if _c and depth < 3:
                _cond_lines.append(_c[:100])
            for _key in ("true_body", "false_body", "body"):
                _sub = _n.get(_key)
                if isinstance(_sub, list):
                    _collect_conds(_sub, depth + 1)
    _collect_conds(_lf)

    func_ctx = (
        f"Function: {unit.get('prototype', '')}\n"
        f"Description: {unit.get('description', '')}\n"
        f"Input variables: {_inp_vars}\n"
        f"Output variables: {_out_vars}\n"
        f"Calls: {_calls[:8]}\n"
    )
    if _indirect:
        func_ctx += f"Indirect variables (from callees): {_indirect}\n"
    if _cond_lines:
        func_ctx += f"Logic conditions: {_cond_lines[:6]}\n"

    seq_info = "Current sequences:\n"
    for s in sequences:
        seq_info += f"  Seq {s['seq_num']} ({s['strategy']}): inputs={s['inputs']}, expected={s['expected']}\n"

    reply = _ai_call_with_retry(
        agent_call, ai_config,
        [
            {"role": "system", "content": _SUTS_AI_SYSTEM_PROMPT},
            {"role": "user", "content": func_ctx + "\n" + seq_info},
        ],
        stage="suts_enhance",
        temperature=0.2,
    )

    payload = _parse_ai_json(reply, expect_list=True)
    if isinstance(payload, list):
        valid_nums = {s["seq_num"] for s in sequences}
        seq_map = {s["seq_num"]: s for s in sequences}
        applied = 0
        for item in payload:
            if _validate_ai_sequence_item(item, valid_nums):
                seq_map[item["seq_num"]]["expected"].update(item["expected"])
                applied += 1
        if applied:
            _logger.info("AI enhanced %d/%d sequences for %s", applied, len(payload), unit.get("name"))

    return sequences


# ---------------------------------------------------------------------------
# Phase 5: XLSM output
# ---------------------------------------------------------------------------

def generate_suts_xlsm(
    template_path: Optional[str],
    units: List[Dict[str, Any]],
    all_sequences: Dict[str, List[Dict[str, Any]]],
    output_path: str,
    project_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate SUTS XLSM file."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        _logger.error("openpyxl not installed")
        raise

    cfg = project_config or {}
    project_id = cfg.get("project_id", "PROJECT")
    doc_id = cfg.get("doc_id", f"{project_id}-SUTS")
    version = cfg.get("version", "v1.00")
    asil_level = cfg.get("asil_level", "")

    if template_path and Path(template_path).is_file():
        wb = openpyxl.load_workbook(template_path, keep_vba=True)
        _logger.info("Loaded SUTS template: %s", template_path)
    else:
        wb = openpyxl.Workbook()
        _create_suts_cover(wb, project_id, doc_id, version, asil_level)
        _create_suts_history(wb, version)
        _create_suts_intro(wb)
        _create_suts_test_env(wb)
        _logger.info("Created new SUTS workbook (no template)")

    thin = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    hdr_font = Font(name="맑은 고딕", size=9, bold=True)
    data_font = Font(name="맑은 고딕", size=8)
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sheet_name = "2.SW Unit Test Spec"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)

    # --- Title row (row 1, merged A1 to last column — matches reference A1:EG1) ---
    title_font = Font(name="맑은 고딕", size=13, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=_RELATED_COL)
    ws.cell(row=1, column=1, value="Software Unit Test Specification").font = title_font
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    # --- Header rows (5-6) ---
    # Row 5: group headers — merged spans
    def _fill_and_merge(row, c_start, c_end, label):
        for c in range(c_start, c_end + 1):
            ws.cell(row=row, column=c).fill = hdr_fill
            ws.cell(row=row, column=c).border = thin
            ws.cell(row=row, column=c).alignment = center
        ws.cell(row=row, column=c_start, value=label).font = hdr_font
        if c_end > c_start:
            try:
                ws.merge_cells(
                    start_row=row, start_column=c_start,
                    end_row=row, end_column=c_end,
                )
            except Exception:
                pass

    _fill_and_merge(5, 2, 2, "Component/Unit")
    _fill_and_merge(5, 3, _SEQ_COL, "Test Case")       # cols 3–13
    _fill_and_merge(5, _INPUT_COL_START, _INPUT_COL_END, "Input")
    _fill_and_merge(5, _OUTPUT_COL_START, _OUTPUT_COL_END, "Expected Result")
    _fill_and_merge(5, _RELATED_COL, _RELATED_COL, "Related ID")
    ws.row_dimensions[5].height = 18

    # Row 6: sub-headers (fixed columns)
    # Cols 11 (K)=Sequence(action text), 12 (L)=Test Case Gen.Method(per-seq), 13 (M)=Seq No.
    fixed_headers = {
        2: "Component", 3: "TC ID", 4: "Name", 5: "Description",
        6: "Safety\nRelated", 7: "Test\nEnvironment", 8: "Test\nMethod",
        9: "Gen.\nMethod", 10: "Precondition",
        11: "Sequence", 12: "Test Case\nGen.Method", _SEQ_COL: "Seq.\nNo.",
    }
    for c, h in fixed_headers.items():
        cell = ws.cell(row=6, column=c, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.border = thin
        cell.alignment = center

    ws.cell(row=6, column=_RELATED_COL, value="SUDS").font = hdr_font
    ws.cell(row=6, column=_RELATED_COL).fill = hdr_fill
    ws.cell(row=6, column=_RELATED_COL).border = thin
    ws.cell(row=6, column=_RELATED_COL).alignment = center
    ws.row_dimensions[6].height = 34.5  # matches reference row 6 height

    # Column widths
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 32
    ws.column_dimensions["E"].width = 60.0  # Description (function prototype — matches reference)
    ws.column_dimensions["F"].width = 9
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 10
    ws.column_dimensions["I"].width = 12
    ws.column_dimensions["J"].width = 26.75
    ws.column_dimensions["K"].width = 52.75  # Sequence action text — matches reference
    ws.column_dimensions["L"].width = 13.0   # Test Case Gen.Method per-seq — matches reference
    ws.column_dimensions["M"].width = 7      # Seq. No.

    # --- Data rows ---
    row_num = 7
    tc_count = 0
    total_seq = 0

    for unit in units:
        fid = unit["fid"]
        seqs = all_sequences.get(fid, [])
        if not seqs:
            seqs = [{"seq_num": 1, "inputs": {}, "expected": {}, "strategy": "N/A"}]

        tc_id = f"SwUTC_{fid}"
        gen_method = determine_gen_method(unit)
        test_method = determine_test_method(unit)
        description_parts = []
        if unit.get("description"):
            description_parts.append(str(unit["description"]).strip())
        prototype = str(unit.get("prototype") or "").strip()
        if prototype:
            description_parts.append(prototype)
        tc_description = "\n".join(part for part in description_parts if part)[:500]
        is_safety = str(unit.get("asil") or "").strip().upper() not in ("", "QM", "TBD")
        # SRS req IDs: append to description so they're visible in the TC row
        srs_ids = str(unit.get("srs_req_ids") or "").strip()
        if srs_ids:
            tc_description = (tc_description + f"\n[SRS: {srs_ids}]").strip()
        n_seq = len(seqs)
        start_row = row_num

        # TC definition row — fixed meta columns (cols 11-13 are per-seq, left empty here)
        _CENTER_TC = {6, 7, 8, 9}  # short single-value columns → center align
        ws.cell(row=row_num, column=2, value=unit["component"]).font = data_font
        ws.cell(row=row_num, column=3, value=tc_id).font = data_font
        ws.cell(row=row_num, column=4, value=unit["name"]).font = data_font
        ws.cell(row=row_num, column=5, value=tc_description).font = data_font
        ws.cell(row=row_num, column=6, value="X" if is_safety else "").font = data_font
        ws.cell(row=row_num, column=6).alignment = center
        ws.cell(row=row_num, column=7, value=_DEFAULT_TEST_ENV).font = data_font
        ws.cell(row=row_num, column=7).alignment = center
        ws.cell(row=row_num, column=8, value=test_method).font = data_font
        ws.cell(row=row_num, column=8).alignment = center
        ws.cell(row=row_num, column=9, value=gen_method).font = data_font
        ws.cell(row=row_num, column=9).alignment = center
        # Precondition: include SRS req IDs so they're visible in TC row
        precond_base = str(unit.get("precondition") or "").strip()
        if srs_ids and srs_ids not in precond_base:
            precondition_val = f"SRS: {srs_ids}\n{precond_base}".strip()
        else:
            precondition_val = precond_base
        ws.cell(row=row_num, column=10, value=precondition_val).font = data_font
        # Col L (12): TC-level gen_method — merged across all TC rows (matches reference)
        ws.cell(row=row_num, column=12, value=gen_method).font = data_font
        ws.cell(row=row_num, column=12).alignment = center
        ws.cell(row=row_num, column=_RELATED_COL, value=fid).font = data_font
        ws.cell(row=row_num, column=_RELATED_COL).alignment = center

        # Input variable names in TC row
        input_vars = unit.get("input_vars", [])
        for vi, vname in enumerate(input_vars):
            col = _INPUT_COL_START + vi
            if col > _INPUT_COL_END:
                break
            cell = ws.cell(row=row_num, column=col, value=vname)
            cell.font = hdr_font
            cell.alignment = center
            ws.column_dimensions[get_column_letter(col)].width = max(
                12, min(len(vname) + 2, 24)
            )

        # Output variable names in TC row
        output_vars = unit.get("output_vars", [])
        for vi, vname in enumerate(output_vars):
            col = _OUTPUT_COL_START + vi
            if col > _OUTPUT_COL_END:
                break
            cell = ws.cell(row=row_num, column=col, value=vname)
            cell.font = hdr_font
            cell.alignment = center
            ws.column_dimensions[get_column_letter(col)].width = max(
                12, min(len(vname) + 2, 24)
            )

        # Apply borders to TC row
        max_data_col = max(
            12,
            _INPUT_COL_START + len(input_vars) - 1,
            _OUTPUT_COL_START + len(output_vars) - 1,
            _RELATED_COL,
        )
        for c in range(2, max_data_col + 1):
            ws.cell(row=row_num, column=c).border = thin
            ws.cell(row=row_num, column=c).alignment = wrap

        row_num += 1

        # Sequence rows
        for seq in seqs:
            ws.cell(row=row_num, column=_SEQ_COL, value=seq["seq_num"]).font = data_font
            ws.cell(row=row_num, column=_SEQ_COL).alignment = center
            ws.cell(row=row_num, column=_SEQ_COL).border = thin

            # Col K (11): Sequence — full action description text (matches reference "Sequence" col)
            # Combine strategy tag + description into a readable action text
            strategy_val = str(seq.get("strategy", "") or "")
            seq_desc = str(seq.get("description", "") or "")
            if strategy_val and seq_desc:
                sequence_text = f"[{strategy_val}] {seq_desc}"
            elif seq_desc:
                sequence_text = seq_desc
            else:
                sequence_text = strategy_val
            ws.cell(row=row_num, column=11, value=sequence_text).font = data_font
            ws.cell(row=row_num, column=11).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(row=row_num, column=11).border = thin

            # Col 12 (L) is TC-level gen_method, written only in tc_def_row and merged.
            # No per-seq data written to col 12.

            # Input values
            for vi, vname in enumerate(input_vars):
                col = _INPUT_COL_START + vi
                if col > _INPUT_COL_END:
                    break
                val = seq.get("inputs", {}).get(vname)
                if val is not None:
                    cell = ws.cell(row=row_num, column=col, value=val)
                    cell.font = data_font
                    cell.alignment = center
                    cell.border = thin

            # Expected output values
            for vi, vname in enumerate(output_vars):
                col = _OUTPUT_COL_START + vi
                if col > _OUTPUT_COL_END:
                    break
                val = seq.get("expected", {}).get(vname)
                if val is not None:
                    cell = ws.cell(row=row_num, column=col, value=val)
                    cell.font = data_font
                    cell.alignment = center
                    cell.border = thin

            row_num += 1
            total_seq += 1

        # Merge fixed TC-metadata columns across TC def row + all sequence rows
        # Cols 11 (strategy), 12 (description), 13 (seq_no) are per-sequence — NOT merged
        end_row = row_num - 1
        tc_def_row = start_row
        merge_cols = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, _RELATED_COL]  # 12=col L (TC gen method)
        if end_row > tc_def_row:
            for mc in merge_cols:
                try:
                    ws.merge_cells(
                        start_row=tc_def_row, start_column=mc,
                        end_row=end_row, end_column=mc,
                    )
                except Exception:
                    pass

        tc_count += 1

    _logger.info("Wrote %d TCs, %d sequences to sheet", tc_count, total_seq)

    # --- Traceability sheet: Component → Function → TC ---
    _write_suts_traceability_sheet(wb, units, thin, hdr_fill, hdr_font, data_font)

    # --- Remove default sheet if we created new workbook ---
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        del wb["Sheet"]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    _logger.info("SUTS saved: %s", out)
    return str(out)


def _write_suts_traceability_sheet(wb, units, border, hdr_fill, hdr_font, data_font):
    """Write traceability sheet mapping Components → Functions → SUTS TCs."""
    from openpyxl.styles import Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    sheet_name = "3.Traceability"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    covered_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

    ws.cell(row=1, column=1, value="Traceability Between [SUDS] and [SUTS]").font = hdr_font

    headers = ["#", "Component", "Function ID", "Function Name", "TC ID",
               "SRS Req ID", "Input Vars", "Output Vars", "Sequences", "Gen Method", "Status"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=ci, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = border
        c.alignment = center

    widths = [5, 16, 16, 32, 22, 28, 10, 10, 10, 14, 10]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    row = 4
    for idx, u in enumerate(units, 1):
        tc_id = f"SwUTC_{u['fid']}"
        n_inp = len(u.get("input_vars", []))
        n_out = len(u.get("output_vars", []))
        has_io = n_inp > 0 or n_out > 0
        has_req = bool(u.get("srs_req_ids", ""))
        status = "Covered" if has_io else "No I/O"

        ws.cell(row=row, column=1, value=idx).font = data_font
        ws.cell(row=row, column=2, value=(u.get("component") or "").split("\n")[0]).font = data_font
        ws.cell(row=row, column=3, value=u["fid"]).font = data_font
        ws.cell(row=row, column=4, value=u["name"]).font = data_font
        ws.cell(row=row, column=5, value=tc_id).font = data_font
        ws.cell(row=row, column=6, value=u.get("srs_req_ids", "")).font = data_font
        ws.cell(row=row, column=7, value=n_inp).font = data_font
        ws.cell(row=row, column=8, value=n_out).font = data_font
        ws.cell(row=row, column=9, value=len(u.get("logic_flow", []))).font = data_font
        ws.cell(row=row, column=10, value=determine_gen_method(u)).font = data_font
        ws.cell(row=row, column=11, value=status).font = data_font

        for ci in range(1, 12):
            ws.cell(row=row, column=ci).border = border
            ws.cell(row=row, column=ci).alignment = wrap
            if has_io:
                ws.cell(row=row, column=ci).fill = covered_fill

        row += 1

    # Summary at bottom
    row += 1
    total = len(units)
    with_io = sum(1 for u in units if u.get("input_vars") or u.get("output_vars") or u.get("indirect_vars"))
    with_req = sum(1 for u in units if u.get("srs_req_ids"))
    ws.cell(row=row, column=1, value="Summary").font = hdr_font
    row += 1
    ws.cell(row=row, column=1, value="Total Functions").font = data_font
    ws.cell(row=row, column=2, value=total).font = data_font
    row += 1
    ws.cell(row=row, column=1, value="With I/O (Covered)").font = data_font
    ws.cell(row=row, column=2, value=with_io).font = data_font
    row += 1
    ws.cell(row=row, column=1, value="Coverage %").font = data_font
    ws.cell(row=row, column=2, value=f"{round(with_io / max(total, 1) * 100, 1)}%").font = data_font
    row += 1
    ws.cell(row=row, column=1, value="With SRS Req ID").font = data_font
    ws.cell(row=row, column=2, value=with_req).font = data_font
    row += 1
    ws.cell(row=row, column=1, value="SRS Traceability %").font = data_font
    ws.cell(row=row, column=2, value=f"{round(with_req / max(total, 1) * 100, 1)}%").font = data_font


def _create_suts_cover(wb, project_id, doc_id, version, asil_level):
    ws = wb.active
    ws.title = "Cover"
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    title_font = Font(name="맑은 고딕", size=24, bold=True)
    label_font = Font(name="맑은 고딕", size=9, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Column widths matching reference
    col_widths = {"A": 2.875, "B": 6.875, "C": 13.0, "D": 13.0, "E": 13.0,
                  "F": 13.0, "G": 13.0, "H": 4.625, "I": 6.875, "J": 13.0, "K": 10.625}
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    # B5:K5 merged — main title block (height=123 matching reference)
    ws.merge_cells("B5:K5")
    ws["B5"] = "Software Unit Test Specification\n(소프트웨어 단위테스트 명세서)"
    ws["B5"].font = title_font
    ws["B5"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[5].height = 123.0

    # I2 = "Doc. ID" label, J2:K2 merged = value
    ws["I2"] = "Doc. ID"
    ws["I2"].font = label_font
    ws["I2"].alignment = center
    ws.merge_cells("J2:K2")
    ws["J2"] = doc_id
    ws["J2"].font = data_font
    ws["J2"].alignment = center

    # I3 = "Version" label, J3:K3 merged = value
    ws["I3"] = "Version"
    ws["I3"].font = label_font
    ws["I3"].alignment = center
    ws.merge_cells("J3:K3")
    ws["J3"] = version
    ws["J3"].font = data_font
    ws["J3"].alignment = center

    info_rows = [
        ("Project", project_id),
        ("ASIL Level", asil_level),
        ("Status", "Draft"),
        ("Date", datetime.now().strftime("%Y-%m-%d")),
    ]
    for i, (label, value) in enumerate(info_rows):
        r = 21 + i
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=11)
        ws.cell(row=r, column=2, value=label).font = label_font
        ws.cell(row=r, column=2).fill = hdr_fill
        ws.cell(row=r, column=2).border = thin
        ws.cell(row=r, column=2).alignment = center
        ws.cell(row=r, column=6, value=value).font = data_font
        ws.cell(row=r, column=6).border = thin
        ws.cell(row=r, column=6).alignment = left


def _create_suts_history(wb, version):
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    ws = wb.create_sheet("History")
    hdr_font = Font(name="맑은 고딕", size=10, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    # Column widths matching reference: A:1.25, B:8.375, C:9.125, D:35.5, E:8.625, F:13.0, G:13.0, H:1.25
    ws.column_dimensions["A"].width = 1.25
    ws.column_dimensions["B"].width = 8.375
    ws.column_dimensions["C"].width = 9.125
    ws.column_dimensions["D"].width = 35.5
    ws.column_dimensions["E"].width = 8.625
    ws.column_dimensions["F"].width = 13.0
    ws.column_dimensions["G"].width = 13.0
    ws.column_dimensions["H"].width = 1.25
    ws.row_dimensions[2].height = 18.0
    ws.row_dimensions[3].height = 14.25

    ws.merge_cells("B2:G2")
    ws["B2"] = "▶ Revision History"
    ws["B2"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B2"].alignment = Alignment(horizontal="left", vertical="center")

    headers = ["Version", "Date", "Description", "Author", "Reviewer", "Approver"]
    for i, h in enumerate(headers):
        c = ws.cell(row=4, column=2 + i, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = thin
        c.alignment = center

    row_data = [
        (version, datetime.now().strftime("%Y.%m.%d"), "- Auto-generated", "Auto", "-", "-"),
    ]
    for ri, (ver, date, desc, author, reviewer, approver) in enumerate(row_data):
        r = 5 + ri
        for ci, val in enumerate([ver, date, desc, author, reviewer, approver]):
            cell = ws.cell(row=r, column=2 + ci, value=val)
            cell.font = data_font
            cell.border = thin


def _create_suts_intro(wb):
    ws = wb.create_sheet("1.Introduction")
    from openpyxl.styles import Font
    ws["A1"] = "Introduction"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B3"] = "1.1 Purpose"
    ws["B3"].font = Font(name="맑은 고딕", size=10, bold=True)
    ws["B4"] = (
        "본 문서는 소프트웨어 유닛테스트 명세를 기술하는 문서이며, "
        "소프트웨어 유닛테스트 수행자에 의해서 작성된다."
    )
    ws["B6"] = (
        "유닛 소프트웨어 테스트의 근거가 되는 문서로서 정의며 "
        "유닛 소프트웨어 테스트 수행자에게 제공된다."
    )
    ws["B8"] = "1.2 Scope"
    ws["B8"].font = Font(name="맑은 고딕", size=10, bold=True)
    ws["B9"] = "본 문서는 유닛테스트 테스트 대상의 정의를 포함하며, 소프트웨어 단위 테스트의 사양을 정의하고 있다."


def _create_suts_test_env(wb):
    ws = wb.create_sheet("1.Test Environment")
    from openpyxl.styles import Font
    ws["A1"] = "Test Environments"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B3"] = "STP의 SwUTE_01 과 테스트 환경으로 동일하다."
    ws["B6"] = "< End of Document >"


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def generate_suts_quality_report(
    units: List[Dict[str, Any]],
    all_sequences: Dict[str, List[Dict[str, Any]]],
    total_source_functions: int = 0,
) -> Dict[str, Any]:
    total_tc = len(units)
    total_seq = sum(len(s) for s in all_sequences.values())
    total_inp = sum(len(u.get("input_vars", [])) for u in units)
    total_out = sum(len(u.get("output_vars", [])) for u in units)
    avg_seq = round(total_seq / max(total_tc, 1), 1)
    with_io = sum(
        1 for u in units
        if u.get("input_vars") or u.get("output_vars") or u.get("indirect_vars")
        or any(
            bool(s.get("inputs")) or bool(s.get("expected"))
            for s in all_sequences.get(u["fid"], [])
        )
    )
    with_logic = sum(1 for u in units if u.get("logic_flow"))

    gen_methods: Dict[str, int] = {}
    for u in units:
        gm = determine_gen_method(u)
        gen_methods[gm] = gen_methods.get(gm, 0) + 1

    components: Dict[str, int] = {}
    for u in units:
        comp = (u.get("component") or "Unknown").split("\n")[0]
        components[comp] = components.get(comp, 0) + 1

    src_total = total_source_functions or total_tc
    func_coverage_pct = round(total_tc / max(src_total, 1) * 100, 1)
    io_coverage_pct = round(with_io / max(total_tc, 1) * 100, 1)

    return {
        "total_test_cases": total_tc,
        "total_sequences": total_seq,
        "avg_sequences_per_tc": avg_seq,
        "total_input_vars": total_inp,
        "total_output_vars": total_out,
        "with_io_count": with_io,
        "with_logic_count": with_logic,
        "function_coverage_pct": func_coverage_pct,
        "io_coverage_pct": io_coverage_pct,
        "total_source_functions": src_total,
        "gen_method_distribution": gen_methods,
        "component_distribution": components,
    }


# ---------------------------------------------------------------------------
# Document validation
# ---------------------------------------------------------------------------

def validate_suts_xlsm(
    xlsm_path: str,
    expected_tc_range: Optional[tuple] = None,
    expected_seq_range: Optional[tuple] = None,
) -> Dict[str, Any]:
    """Validate generated SUTS XLSM for structural and data quality.

    Returns dict with 'valid' bool, 'issues' list, 'warnings' list, and 'stats' dict.
    """
    issues: List[str] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {}

    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"valid": False, "issues": ["openpyxl not installed"], "warnings": [], "stats": {}}

    p = Path(xlsm_path)
    if not p.exists():
        return {"valid": False, "issues": [f"File not found: {xlsm_path}"], "warnings": [], "stats": {}}

    try:
        wb = load_workbook(str(p), read_only=True, data_only=True)
    except Exception as e:
        return {"valid": False, "issues": [f"Cannot open: {e}"], "stats": {}}

    required_sheets = ["2.SW Unit Test Spec"]
    for s in required_sheets:
        if s not in wb.sheetnames:
            issues.append(f"Missing required sheet: {s}")

    expected_sheets = ["Cover", "History", "1.Introduction", "1.Test Environment",
                       "2.SW Unit Test Spec", "3.Traceability"]
    stats["sheets"] = wb.sheetnames
    stats["sheet_count"] = len(wb.sheetnames)
    for s in expected_sheets:
        if s not in wb.sheetnames:
            issues.append(f"Optional sheet missing: {s}")

    if "2.SW Unit Test Spec" in wb.sheetnames:
        ws = wb["2.SW Unit Test Spec"]
        max_col = min(int(ws.max_column or 149), 149)
        stats["max_col"] = max_col

        tc_count = 0
        seq_count = 0
        empty_io_tcs = 0
        last_row = 6
        for row_idx, row in enumerate(
            ws.iter_rows(min_row=7, max_col=max_col, values_only=True),
            start=7,
        ):
            last_row = row_idx
            tc_id = row[2] if len(row) > 2 else None
            if tc_id and str(tc_id).startswith("SwUTC"):
                tc_count += 1
                has_input = any(v not in (None, "") for v in row[13:min(62, len(row))])
                has_output = any(v not in (None, "") for v in row[62:min(149, len(row))])
                if not has_input and not has_output:
                    empty_io_tcs += 1
            seq_val = row[12] if len(row) > 12 else None
            if seq_val is not None and str(seq_val).strip():
                seq_count += 1

        stats["max_row"] = last_row

        stats["tc_count"] = tc_count
        stats["seq_count"] = seq_count
        stats["empty_io_tc_count"] = empty_io_tcs
        stats["avg_seq_per_tc"] = round(seq_count / max(tc_count, 1), 1)

        if tc_count == 0:
            issues.append("No test cases (SwUTC_*) found")
        if seq_count == 0:
            issues.append("No test sequences found")
        if empty_io_tcs > tc_count * 0.5:
            issues.append(f"Over 50% TCs lack I/O variables ({empty_io_tcs}/{tc_count})")

        if expected_tc_range:
            lo, hi = expected_tc_range
            if tc_count < lo or tc_count > hi:
                issues.append(f"TC count {tc_count} outside expected range [{lo}, {hi}]")

        if expected_seq_range:
            lo, hi = expected_seq_range
            if seq_count < lo or seq_count > hi:
                issues.append(f"Sequence count {seq_count} outside expected range [{lo}, {hi}]")

    wb.close()
    return {"valid": len(issues) == 0, "issues": issues, "stats": stats}


def validate_sts_xlsm(xlsm_path: str) -> Dict[str, Any]:
    """Validate generated STS XLSM for structural and data quality."""
    issues: List[str] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {}

    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"valid": False, "issues": ["openpyxl not installed"], "warnings": [], "stats": {}}

    p = Path(xlsm_path)
    if not p.exists():
        return {"valid": False, "issues": [f"File not found: {xlsm_path}"], "warnings": [], "stats": {}}

    try:
        wb = load_workbook(str(p), read_only=True, data_only=True)
    except Exception as e:
        return {"valid": False, "issues": [f"Cannot open: {e}"], "warnings": [], "stats": {}}

    stats["sheets"] = wb.sheetnames
    stats["sheet_count"] = len(wb.sheetnames)

    expected_sheets = ["Cover", "History", "1.Introduction"]
    for s in expected_sheets:
        if s not in wb.sheetnames:
            warnings.append(f"Optional sheet missing: {s}")

    sts_sheet = None
    for candidate in ["3.SW Integration Test Spec", "2.SW Test Spec"]:
        if candidate in wb.sheetnames:
            sts_sheet = candidate
            break

    if not sts_sheet:
        issues.append("No STS main sheet found")
        wb.close()
        return {"valid": False, "issues": issues, "warnings": warnings, "stats": stats}

    ws = wb[sts_sheet]
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    stats["max_row"] = max_row
    stats["max_col"] = max_col

    tc_count = 0
    empty_title_tcs = 0
    no_step_tcs = 0
    no_expected_tcs = 0
    reqs_linked = 0
    for r in range(7, max_row + 1):
        tc_id = ws.cell(row=r, column=2).value
        if tc_id and str(tc_id).strip():
            tc_count += 1
            title = ws.cell(row=r, column=3).value
            if not title or not str(title).strip():
                empty_title_tcs += 1
            step_action = ws.cell(row=r, column=5).value
            if not step_action or not str(step_action).strip():
                no_step_tcs += 1
            expected_val = ws.cell(row=r, column=6).value
            if not expected_val or not str(expected_val).strip():
                no_expected_tcs += 1
            req_ref = ws.cell(row=r, column=4).value
            if req_ref and str(req_ref).strip():
                reqs_linked += 1

    stats["tc_count"] = tc_count
    stats["empty_title_tcs"] = empty_title_tcs
    stats["no_step_tcs"] = no_step_tcs
    stats["no_expected_tcs"] = no_expected_tcs
    stats["reqs_linked"] = reqs_linked
    stats["req_linkage_pct"] = round(reqs_linked / tc_count * 100, 1) if tc_count else 0

    if tc_count == 0:
        issues.append("No test cases found")
    if empty_title_tcs > tc_count * 0.3:
        issues.append(f"Over 30% TCs lack titles ({empty_title_tcs}/{tc_count})")
    if no_step_tcs > tc_count * 0.5:
        warnings.append(f"Over 50% TCs lack action steps ({no_step_tcs}/{tc_count})")
    if no_expected_tcs > tc_count * 0.5:
        warnings.append(f"Over 50% TCs lack expected results ({no_expected_tcs}/{tc_count})")
    if tc_count > 0 and reqs_linked == 0:
        warnings.append("No TCs linked to requirements")

    wb.close()
    return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings, "stats": stats}


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------

def generate_suts(
    source_root: str,
    output_path: str,
    template_path: Optional[str] = None,
    project_config: Optional[Dict[str, Any]] = None,
    ai_config: Optional[Dict[str, Any]] = None,
    max_sequences: int = _DEFAULT_SEQ_COUNT,
    on_progress: Optional[Any] = None,
    srs_docx_path: Optional[str] = None,
    sds_docx_path: Optional[str] = None,
    uds_path: Optional[str] = None,
    hsis_path: Optional[str] = None,
    target_function_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Top-level SUTS generation pipeline.

    Args:
        source_root: Root directory of C source code
        output_path: Path for output XLSM file
        template_path: Optional SUTS template XLSM
        project_config: Optional config dict
        ai_config: Optional AI config dict for Gemini enhancement
        max_sequences: Maximum sequences per TC
        on_progress: Optional callback(pct: int, message: str) for progress updates
        srs_docx_path: Optional path to SRS DOCX for requirement ID enrichment
        sds_docx_path: Optional path to SDS DOCX for ASIL/design context
        uds_path: Optional path to UDS DOCX/XLSM for function descriptions

    Returns:
        Dict with keys: output_path, quality_report, test_case_count, etc.
    """
    def _progress(pct: int, msg: str):
        _logger.info("[%d%%] %s", pct, msg)
        if on_progress:
            try:
                on_progress(pct, msg)
            except Exception:
                pass

    _logger.info("=== SUTS Generation Start ===")
    t0 = time.time()
    target_name_set = {
        str(name or "").strip().lower()
        for name in (target_function_names or [])
        if str(name or "").strip()
    }

    _progress(5, "소스 코드 파싱 시작")
    globals_info_map: Dict[str, Dict[str, str]] = {}
    try:
        try:
            from backend.helpers import _get_source_sections_cached

            report_data = _get_source_sections_cached(source_root)
        except Exception:
            from report_generator import generate_uds_source_sections

            report_data = generate_uds_source_sections(source_root)
        function_details = report_data.get("function_details", {})
        globals_info_map = report_data.get("globals_info_map", {}) or {}
        if not function_details:
            raise ValueError("generate_uds_source_sections returned no function_details")
    except Exception as e:
        _logger.warning("Full UDS source parse failed, trying lightweight: %s", e)
        function_details = _lightweight_parse(source_root)

    if target_name_set:
        function_details = {
            fid: info
            for fid, info in function_details.items()
            if isinstance(info, dict) and str(info.get("name") or "").strip().lower() in target_name_set
        }

    _progress(25, f"소스 파싱 완료 - {len(function_details)}개 함수 발견")

    _progress(30, "유닛 함수 수집 중")
    units = collect_unit_functions(function_details, globals_info_map)

    if not units:
        _logger.warning("No unit functions found!")
        return {
            "output_path": "",
            "quality_report": {},
            "test_case_count": 0,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": "No functions found in source code",
        }

    _progress(35, f"{len(units)}개 유닛 함수 수집 완료")

    # ── SRS requirement ID enrichment ────────────────────────────────────
    if srs_docx_path and Path(srs_docx_path).is_file():
        _progress(36, "SRS 요구사항 ID 보강 중")
        try:
            from generators.sts import parse_srs_docx_tables
            srs_reqs = parse_srs_docx_tables(srs_docx_path)
            if srs_reqs:
                # Build function_name → req_ids map from SRS data
                fn_to_reqs: Dict[str, List[str]] = {}
                for req in srs_reqs:
                    req_id = req.get("id", "")
                    if not req_id:
                        continue
                    related = str(req.get("related_id") or req.get("verification") or "")
                    desc = str(req.get("description") or req.get("name") or "")
                    # Find function name references in requirement text
                    for m in re.finditer(r"\b([A-Za-z_]\w*(?:_pds|_init|_main|_run|_update|_check|_calc|_set|_get|_proc))\b", related + " " + desc):
                        fn_key = m.group(1).lower()
                        if fn_key not in fn_to_reqs:
                            fn_to_reqs[fn_key] = []
                        if req_id not in fn_to_reqs[fn_key]:
                            fn_to_reqs[fn_key].append(req_id)
                # Enrich units that have no srs_req_ids yet
                for unit in units:
                    if unit.get("srs_req_ids"):
                        continue
                    fn_lower = unit["name"].lower()
                    direct = fn_to_reqs.get(fn_lower)
                    if direct:
                        unit["srs_req_ids"] = ", ".join(direct[:4])
                _logger.info("SRS enrichment: %d reqs parsed, %d units have req IDs now",
                             len(srs_reqs),
                             sum(1 for u in units if u.get("srs_req_ids")))
        except Exception as _e:
            _logger.debug("SRS enrichment skipped: %s", _e)

    # ── UDS function description enrichment ──────────────────────────────
    if uds_path and Path(uds_path).is_file():
        _progress(37, "UDS 함수 설명 보강 중")
        try:
            from generators.sts import _load_uds_descriptions
            uds_descs = _load_uds_descriptions(uds_path)
            if uds_descs:
                enriched_count = 0
                for unit in units:
                    fn_lower = unit["name"].lower()
                    uds_desc = uds_descs.get(fn_lower)
                    if uds_desc and len(uds_desc) > len(unit.get("description") or ""):
                        unit["description"] = uds_desc
                        enriched_count += 1
                _logger.info("UDS descriptions enriched for %d units", enriched_count)
        except Exception as _e:
            _logger.debug("UDS description enrichment skipped: %s", _e)

    # ── HSIS signal enrichment ────────────────────────────────────────────
    # Uses HSIS xlsx to enrich: srs_req_ids (from related_id), variable
    # boundary hints from characteristics (e.g. "0...255"), and srs_req_ids
    # for units that read/write HSIS signal SW variables.
    if hsis_path and Path(hsis_path).is_file():
        _progress(38, "HSIS 신호 보강 중")
        try:
            from generators.sts import _load_hsis_signals
            _hsis_data = _load_hsis_signals(hsis_path)
            _hsis_signals = _hsis_data.get("signals", [])
            if _hsis_signals:
                # Build sw_var_name → signal dict (one var can split by \n/,)
                _hsis_var_map: Dict[str, Dict[str, Any]] = {}
                for _sig in _hsis_signals:
                    _sw_raw = str(_sig.get("sw_var_name") or "")
                    for _tok in re.split(r"[\n,\s]+", _sw_raw):
                        _tok = _tok.strip()
                        if _tok and re.match(r"^[A-Za-z_]\w+$", _tok):
                            _hsis_var_map[_tok] = _sig

                # Parse "min...max" or "min - max" from characteristics
                def _parse_hsis_range(chars: str):
                    if not chars:
                        return None, None
                    m = re.search(r"([-\d.]+)\s*\.{2,3}\s*([-\d.]+)", chars)
                    if not m:
                        m = re.search(r"([-\d.]+)\s*[-~]\s*([-\d.]+)", chars)
                    if m:
                        try:
                            return float(m.group(1)), float(m.group(2))
                        except ValueError:
                            pass
                    return None, None

                enriched_hsis = 0
                for unit in units:
                    # Collect all variable names used by this unit
                    # unit dict uses "input_vars"/"output_vars" (string lists),
                    # not "inputs"/"outputs" (dicts).
                    _unit_vars: List[str] = list(unit.get("input_vars") or [])
                    _unit_vars += list(unit.get("output_vars") or [])

                    _matched: List[Dict[str, Any]] = [
                        _hsis_var_map[v] for v in _unit_vars if v in _hsis_var_map
                    ]
                    if not _matched:
                        continue

                    # 1) enrich srs_req_ids from HSIS related_id
                    if not unit.get("srs_req_ids"):
                        _hsis_req_ids = [
                            s["related_id"] for s in _matched
                            if s.get("related_id") and str(s["related_id"]).strip()
                        ]
                        if _hsis_req_ids:
                            unit["srs_req_ids"] = ", ".join(
                                list(dict.fromkeys(_hsis_req_ids))[:4]
                            )

                    # 2) store HSIS boundary hints on the unit for sequence generation
                    _hsis_bounds: Dict[str, tuple] = {}
                    for _vname in _unit_vars:
                        if _vname in _hsis_var_map:
                            _chars = _hsis_var_map[_vname].get("characteristics", "")
                            _lo, _hi = _parse_hsis_range(_chars)
                            if _lo is not None and _hi is not None:
                                _hsis_bounds[_vname] = (_lo, _hi)
                    if _hsis_bounds:
                        unit.setdefault("hsis_bounds", {}).update(_hsis_bounds)

                    enriched_hsis += 1

                _logger.info("HSIS enrichment: %d units enriched from %d signals",
                             enriched_hsis, len(_hsis_signals))
        except Exception as _hsis_exc:
            _logger.warning("HSIS enrichment skipped: %s", _hsis_exc)

    if globals_info_map:
        set_globals_type_cache(globals_info_map)

    # ── Indirect variable enrichment for void/no-param functions ─────────────
    # For units with no input/output vars, derive testable variables from
    # the global variables of their callee functions (indirect side effects).
    _fn_name_to_info: Dict[str, Dict[str, Any]] = {
        info.get("name", ""): info
        for info in function_details.values()
        if isinstance(info, dict) and info.get("name")
    }
    for _void_unit in units:
        if _void_unit.get("input_vars") or _void_unit.get("output_vars"):
            continue
        _indirect: List[str] = []
        for _callee_name in (_void_unit.get("calls_list") or [])[:8]:
            _callee_info = _fn_name_to_info.get(_callee_name)
            if not _callee_info:
                continue
            # Prefer callee outputs (side effects), then inputs
            _callee_outs = _extract_var_names(_callee_info.get("outputs") or [])
            _callee_ins = _extract_var_names(_callee_info.get("inputs") or [])
            for _v in _callee_outs + _callee_ins:
                if _v not in _indirect:
                    _indirect.append(_v)
            if len(_indirect) >= 6:
                break
        if _indirect:
            _void_unit["indirect_vars"] = _indirect[:6]
            _logger.debug("void unit %s: indirect_vars=%s", _void_unit["name"], _indirect[:6])

    # ── logic_flow variable extraction for remaining void functions ──────────
    # For units still without any testable variable (calls_list was also empty),
    # extract C identifier names from logic_flow condition/text strings.
    # Filters out: C keywords, all-caps macro names, single-letter tokens.
    _C_KEYWORDS = frozenset({
        "if", "else", "while", "for", "return", "switch", "case", "break",
        "continue", "do", "null", "true", "false", "void", "int", "char",
        "uint", "uint8", "uint16", "uint32", "int8", "int16", "int32",
    })
    for _void_unit in units:
        if (_void_unit.get("input_vars") or _void_unit.get("output_vars")
                or _void_unit.get("indirect_vars")):
            continue
        _lf_vars: List[str] = []

        def _walk_flow_nodes(nodes: List[Any]) -> None:
            for _n in nodes:
                if not isinstance(_n, dict):
                    continue
                _text = str(_n.get("condition") or _n.get("text") or "")
                # Extract C identifiers from condition/text
                for _tok in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", _text):
                    if (_tok.lower() not in _C_KEYWORDS
                            and not _tok.isupper()  # skip ALL_CAPS macros
                            and _tok not in _lf_vars
                            and len(_lf_vars) < 6):
                        _lf_vars.append(_tok)
                # Recurse into sub-bodies
                for _key in ("true_body", "false_body", "body"):
                    _sub = _n.get(_key)
                    if isinstance(_sub, list):
                        _walk_flow_nodes(_sub)

        _walk_flow_nodes(_void_unit.get("logic_flow") or [])
        if _lf_vars:
            _void_unit["indirect_vars"] = _lf_vars
            _logger.debug("void unit %s: logic_flow vars=%s", _void_unit["name"], _lf_vars)

    # Identify void functions that still lack all variable info — these are
    # the only ones that need AI enhancement (limits API calls to ~12 units).
    _void_no_vars = {
        u["fid"] for u in units
        if not u.get("input_vars") and not u.get("output_vars")
        and not u.get("indirect_vars")
    }
    _logger.info("Units needing AI enhancement: %d", len(_void_no_vars))

    _progress(40, "테스트 시퀀스 생성 시작")
    all_sequences: Dict[str, List[Dict[str, Any]]] = {}
    ai_enhanced = 0
    for i, unit in enumerate(units):
        seqs = generate_sequences(unit, max_sequences)
        if ai_config and unit["fid"] in _void_no_vars:
            seqs = enhance_sequences_with_ai(unit, seqs, ai_config)
            ai_enhanced += 1
        all_sequences[unit["fid"]] = seqs
        if (i + 1) % 50 == 0 or i == len(units) - 1:
            pct = 40 + int(35 * (i + 1) / len(units))
            _progress(pct, f"시퀀스 생성 {i+1}/{len(units)}")
    if ai_enhanced:
        _logger.info("AI enhanced %d void-function units", ai_enhanced)

    total_seq = sum(len(s) for s in all_sequences.values())
    _progress(80, f"시퀀스 생성 완료 - {total_seq}개")

    quality = generate_suts_quality_report(units, all_sequences, len(function_details))

    _progress(85, "XLSM 파일 생성 중")
    out = generate_suts_xlsm(template_path, units, all_sequences, output_path, project_config)

    _progress(90, "생성 문서 자동 검증 중")
    validation = validate_suts_xlsm(out)
    if validation.get("issues"):
        _logger.warning("SUTS validation issues: %s", validation["issues"])

    validation_report_path = ""
    try:
        validation_report_path = generate_suts_validation_report(out, quality, validation=validation)
        _logger.info("SUTS validation report: %s", validation_report_path)
    except Exception as _vr:
        _logger.warning("SUTS validation report generation skipped: %s", _vr)

    elapsed = time.time() - t0
    _progress(100, f"SUTS 생성 완료 ({elapsed:.1f}초)")

    return {
        "output_path": out,
        "quality_report": quality,
        "test_case_count": len(units),
        "total_sequences": total_seq,
        "elapsed_seconds": round(elapsed, 1),
        "validation": validation,
        "validation_report_path": validation_report_path,
    }


def _lightweight_parse(source_root: str) -> Dict[str, Dict[str, Any]]:
    """Lightweight C source parsing when full report_generator is unavailable."""
    from report.c_parsing import (
        _strip_c_comments,
        _extract_c_definitions,
        _extract_c_function_bodies,
        _extract_simple_call_names,
    )

    root = Path(source_root)
    c_files = list(root.rglob("*.c"))
    function_details: Dict[str, Dict[str, Any]] = {}
    fn_counter = 0

    for cf in c_files:
        try:
            raw = cf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        stripped = _strip_c_comments(raw)
        defs = _extract_c_definitions(stripped)
        bodies = _extract_c_function_bodies(stripped)

        for d in defs:
            # _extract_c_definitions returns Tuple[name, params, is_static]
            if isinstance(d, tuple):
                name = d[0] if len(d) > 0 else ""
                params = d[1] if len(d) > 1 else ""
            elif isinstance(d, dict):
                name = d.get("name", "")
                params = d.get("params", "")
            else:
                continue
            if not name:
                continue
            fn_counter += 1
            fid = f"SwUFn_{fn_counter:04d}"
            sig = f"void {name}({params})" if params else f"void {name}(void)"
            body = bodies.get(name, "")
            calls = _extract_simple_call_names(body) if body else []

            function_details[fid] = {
                "id": fid,
                "name": name,
                "prototype": sig,
                "inputs": [f"[IN] {p}" for p in _lw_parse_params(sig)],
                "outputs": _lw_parse_outputs(sig, name),
                "calls_list": calls,
                "logic_flow": _lw_extract_logic_flow(body),
                "globals_global": [],
                "globals_static": [],
                "module_name": cf.stem,
                "file": str(cf),
                "description": "",
                "asil": "TBD",
                "precondition": "",
            }

    return function_details


def _lw_parse_params(sig: str) -> List[str]:
    if "(" not in sig:
        return []
    params = sig.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not params or params.lower() == "void":
        return []
    result = []
    for p in params.split(","):
        p = p.strip()
        parts = p.split()
        if parts:
            result.append(parts[-1].strip("*&"))
    return result


def _lw_parse_outputs(sig: str, name: str) -> List[str]:
    if not sig:
        return []
    head = sig.split(name, 1)[0] if name in sig else sig
    head = re.sub(r"\b(static|extern|inline)\b", "", head).strip()
    if head and "void" not in head.lower():
        return [f"[OUT] return {head.strip()}"]
    return []


_LW_BRANCH_RE = re.compile(
    r'\b(if|else\s+if|else|switch|case|for|while)\b\s*(\([^)]*\))?',
    re.IGNORECASE,
)


def _lw_extract_logic_flow(body: str) -> List[Dict[str, Any]]:
    """Extract simplified logic flow nodes from a C function body."""
    if not body:
        return []
    nodes: List[Dict[str, Any]] = []
    for m in _LW_BRANCH_RE.finditer(body):
        keyword = m.group(1).strip().lower()
        cond = (m.group(2) or "").strip("() \t")
        node: Dict[str, Any] = {"type": keyword, "text": m.group(0).strip()}
        if cond:
            node["condition"] = cond
        nodes.append(node)
        if len(nodes) >= 40:
            break
    return nodes


# ---------------------------------------------------------------------------
# Document validation
# ---------------------------------------------------------------------------

def generate_suts_validation_report(
    xlsm_path: str,
    quality_report: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a validation report markdown for SUTS XLSM.

    Writes a .validation.md file next to the XLSM and returns its path.
    """
    validation_data = validation if isinstance(validation, dict) else validate_suts_xlsm(xlsm_path)
    stats = validation_data.get("stats", {})
    issues = validation_data.get("issues", [])
    qr = quality_report or {}

    tc_count = stats.get("tc_count", 0)
    seq_count = stats.get("seq_count", 0)
    empty_io = stats.get("empty_io_tc_count", 0)

    lines = [
        "# SUTS 생성 문서 자동 검증 리포트",
        "",
        f"**파일**: `{Path(xlsm_path).name}`  ",
        f"**검증 시각**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**결과**: {'PASS' if validation_data.get('valid') else 'FAIL'}",
        "",
        "---",
        "",
        "## 1. 구조 검증",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 시트 수 | {stats.get('sheet_count', 0)} |",
        f"| 시트 목록 | {', '.join(stats.get('sheets', []))} |",
        f"| TC 수 | {tc_count} |",
        f"| 시퀀스 수 | {seq_count} |",
        f"| TC당 평균 시퀀스 | {stats.get('avg_seq_per_tc', 0)} |",
        f"| I/O 없는 TC 수 | {empty_io} |",
        "",
    ]

    if qr:
        lines.extend([
            "## 2. 품질 지표",
            "",
            "| 항목 | 값 |",
            "|------|-----|",
            f"| 총 TC 수 | {qr.get('total_test_cases', 0)} |",
            f"| 총 시퀀스 수 | {qr.get('total_sequences', 0)} |",
            f"| TC당 평균 시퀀스 | {qr.get('avg_sequences_per_tc', 0)} |",
            f"| 총 입력 변수 | {qr.get('total_input_vars', 0)} |",
            f"| 총 출력 변수 | {qr.get('total_output_vars', 0)} |",
            f"| I/O 보유 TC | {qr.get('with_io_count', 0)} ({qr.get('io_coverage_pct', 0)}%) |",
            f"| 로직 보유 TC | {qr.get('with_logic_count', 0)} |",
            f"| 함수 커버리지 | {qr.get('function_coverage_pct', 0)}% |",
            "",
        ])
        if qr.get("gen_method_distribution"):
            lines.extend([
                "### 생성 방법 분포",
                "",
                "| 방법 | 수 |",
                "|------|-----|",
            ])
            for k, v in qr["gen_method_distribution"].items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

    gate_items = [
        ("TC 존재", tc_count > 0),
        ("시퀀스 존재", seq_count > 0),
        ("I/O 없는 TC < 50%", empty_io <= tc_count * 0.5 if tc_count else True),
        ("TC당 평균 시퀀스 >= 2", stats.get("avg_seq_per_tc", 0) >= 2 if tc_count else True),
        ("함수 커버리지 > 0", qr.get("function_coverage_pct", 0) > 0 if qr else tc_count > 0),
    ]
    passed = sum(1 for _, ok in gate_items if ok)

    lines.extend([
        f"## 3. Quality Gate ({passed}/{len(gate_items)})",
        "",
        "| 항목 | 결과 |",
        "|------|------|",
    ])
    for name, ok in gate_items:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} |")
    lines.append("")

    if issues:
        lines.extend(["## 4. Issues", ""])
        for i in issues:
            lines.append(f"- {i}")
        lines.append("")

    out_path = Path(xlsm_path).with_suffix(".validation.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return str(out_path)


def validate_suts_output(xlsm_path: str) -> Dict[str, Any]:
    """Validate a generated SUTS XLSM for structural completeness."""
    from openpyxl import load_workbook
    wb = load_workbook(xlsm_path, read_only=True, data_only=True)
    issues: List[str] = []
    stats: Dict[str, Any] = {"sheets": wb.sheetnames, "sheet_count": len(wb.sheetnames)}

    expected_sheets = ["Cover", "History", "1.Introduction", "1.Test Environment", "2.SW Unit Test Spec"]
    for s in expected_sheets:
        if s not in wb.sheetnames:
            issues.append(f"Missing sheet: {s}")

    if "2.SW Unit Test Spec" in wb.sheetnames:
        ws = wb["2.SW Unit Test Spec"]
        tc_count = 0
        seq_count = 0
        total_inp = 0
        total_out = 0
        for r in range(7, (ws.max_row or 7) + 1):
            tc_id = ws.cell(row=r, column=3).value
            if tc_id and str(tc_id).startswith("SwUTC"):
                tc_count += 1
                total_inp += sum(1 for c in range(14, 63) if ws.cell(row=r, column=c).value)
                total_out += sum(1 for c in range(63, 149) if ws.cell(row=r, column=c).value)
            elif ws.cell(row=r, column=11).value:
                seq_count += 1

        stats["tc_count"] = tc_count
        stats["seq_count"] = seq_count
        stats["avg_inp"] = round(total_inp / max(tc_count, 1), 1)
        stats["avg_out"] = round(total_out / max(tc_count, 1), 1)
        stats["avg_seq"] = round(seq_count / max(tc_count, 1), 1)

        if tc_count == 0:
            issues.append("No test cases found")
        if seq_count == 0:
            issues.append("No sequences found")
        if stats["avg_inp"] < 1:
            issues.append(f"Low avg input vars: {stats['avg_inp']}")
        if stats["avg_out"] < 1:
            issues.append(f"Low avg output vars: {stats['avg_out']}")

    wb.close()
    stats["issues"] = issues
    stats["valid"] = len(issues) == 0
    return stats
