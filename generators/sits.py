"""SITS (Software Integration Test Specification) auto-generation engine.

Generates XLSM output matching the reference SITS structure:
  - 77 TCs (SwITC_xx), 606 sub-cases
  - Columns: TC ID | Description | Call chain | Gen Method | Precondition |
             Input Param 1-67 | Expected Param 1-70 | Related ID
  - Sheets: Cover, History, 1.Introduction, 2.Test Environment,
            3-1.SW Integration Strategy, 4.SW Integration Test Spec
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column layout constants (1-based, matching reference SITS XLSM)
# ---------------------------------------------------------------------------
_TCID_COL = 2        # B  — TC ID (SwITC_xx) in header row
_DESC_COL = 3        # C  — sub-case number in data rows
_CHAIN_COL = 4       # D  — call chain in sub-case rows
_GEN_COL = 5         # E  — Test Case Generation Method
_PRECOND_COL = 6     # F  — Precondition value (sub-case rows)
_INPUT_COL_START = 8   # H  — Input Param 1 name/value
_INPUT_COL_END = 74    # BV — Input Param 67 (max)
_EXP_COL_START = 75    # BW — Expected Param 1 name/value
_EXP_COL_END = 144     # EQ — Expected Param 70 (max)
_RELATED_COL = 145     # ER — Related ID (SwCom_xx, SwSTR_xx …)

_MAX_INPUT_PARAMS = _INPUT_COL_END - _INPUT_COL_START + 1   # 67
_MAX_EXP_PARAMS = _EXP_COL_END - _EXP_COL_START + 1        # 70
_MAX_SUBCASES = 10
_DEFAULT_SUBCASES = 7

# Boundary value sets for common C types — 7 values per type:
#   min_inv | min_valid | low_mid | mid | high_mid | max_valid | max_inv
# This lets max_subcases=7 produce 7 distinct sub-cases per TC.
_BOUNDARY_SETS: Dict[str, List[Any]] = {
    "uint8":  [-1,    0,    63,    127,   191,   255,   256],
    "uint16": [-1,    0,   16383, 32767, 49151, 65535, 65536],
    "uint32": [-1,    0,   0x3FFFFFFF, 0x7FFFFFFF, 0xBFFFFFFF, 0xFFFFFFFF, 0x100000000],
    "int8":   [-129, -128,  -64,    0,    63,   127,   128],
    "int16":  [-32769, -32768, -16384, 0, 16383, 32767, 32768],
    "int32":  [-2147483649, -2147483648, -1073741824, 0, 1073741823, 2147483647, 2147483648],
    "float":  [-1.0,  0.0,   0.25,  0.5,  0.75,  1.0,   1.001],
    "bool":   [0,     0,     0,     0,    1,     1,     1],
    "default": [-1,   0,    63,    127,   191,   255,   256],
}

_SDS_MAP_CACHE: Optional[Dict[str, Dict[str, str]]] = None
_SDS_MAP_CACHE_MTIME: float = 0.0

# ---------------------------------------------------------------------------
# STP document parsing
# ---------------------------------------------------------------------------

def _parse_stp_document(stp_path: str) -> Dict[str, Any]:
    """Load and parse an STP file (.docx/.pdf/.txt) into a structured context dict.

    Returns:
        {
            "raw":                 str   — full extracted text,
            "doc_id":              str   — 문서번호 (e.g. "HDPDM01-STP-0825"),
            "version":             str   — 개정번호 (e.g. "v1.01"),
            "environments":        List[str] — test environment labels,
            "regression_strategy": str   — regression strategy excerpt,
        }
    """
    try:
        from generators.sts import _load_stp_context
        raw = _load_stp_context(stp_path)
    except Exception:
        raw = ""

    if not raw:
        return {}

    ctx: Dict[str, Any] = {
        "raw": raw,
        "doc_id": "",
        "version": "",
        "environments": [],
        "regression_strategy": "",
    }

    # 문서번호
    m = re.search(r"문서번호\s+([\w\-./]+)", raw)
    if m:
        ctx["doc_id"] = m.group(1).strip()

    # 개정번호 / 버전
    m = re.search(r"(?:개정번호|버전|Version|Rev\.?)\s+(v[\d.]+|\d+\.\d+)", raw, re.IGNORECASE)
    if m:
        ctx["version"] = m.group(1).strip()

    # 테스트 환경 — look for known environment keywords per line
    _ENV_PAT = re.compile(
        r"(HW.?in.?the.?loop|Hardware.?in.?the.?loop|HiL|"
        r"ECU\s*네트워크|ECU\s*network|"
        r"차량(?:\s*환경)?|Vehicle|MiL|SiL|TargetHW)",
        re.IGNORECASE,
    )
    seen_envs: set = set()
    for line in raw.splitlines():
        line = line.strip()
        m = _ENV_PAT.search(line)
        if m:
            # Use the matched token as the canonical environment label
            label = m.group(0).strip()
            if label.lower() not in seen_envs:
                seen_envs.add(label.lower())
                ctx["environments"].append(label)
        if len(ctx["environments"]) >= 6:
            break

    # 회귀 전략
    m = re.search(r"회귀\s*전략[^\n]*\n(.*?)(?=\n\n|\Z)", raw, re.DOTALL)
    if m:
        ctx["regression_strategy"] = m.group(0).strip()[:300]

    _logger.info(
        "SITS: STP parsed — doc_id=%s version=%s envs=%s",
        ctx["doc_id"], ctx["version"], ctx["environments"],
    )
    return ctx


# ---------------------------------------------------------------------------
# Shared helpers (re-used from sts / suts patterns)
# ---------------------------------------------------------------------------

def _load_default_sds_map() -> Dict[str, Dict[str, str]]:
    global _SDS_MAP_CACHE, _SDS_MAP_CACHE_MTIME
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    try:
        sds_files = sorted(docs_dir.glob("*SDS*.docx"))
        if sds_files:
            current_mtime = sds_files[0].stat().st_mtime
            # Return cached copy if file hasn't changed
            if _SDS_MAP_CACHE is not None and current_mtime == _SDS_MAP_CACHE_MTIME:
                return _SDS_MAP_CACHE
            from report_gen.requirements import _extract_sds_partition_map
            for f in sds_files:
                m = _extract_sds_partition_map(str(f))
                if m:
                    _SDS_MAP_CACHE = m
                    _SDS_MAP_CACHE_MTIME = f.stat().st_mtime
                    _logger.info("SITS: SDS map loaded from %s (%d entries)", f.name, len(m))
                    return _SDS_MAP_CACHE
    except Exception as e:
        _logger.debug("SITS: SDS map load failed: %s", e)
    # No SDS file or load failed — cache empty dict to avoid re-attempting every call
    if _SDS_MAP_CACHE is None:
        _SDS_MAP_CACHE = {}
    return _SDS_MAP_CACHE


def _infer_boundary_values(var_name: str) -> List[Any]:
    """Infer boundary values from annotated variable string or variable name.

    Supports two forms:
      - Annotated: '[IN] U8 u8t_Data' or '[OUT] return U16 (range: 0 ~ 65535)'
        → type is extracted from the explicit C type token (U8, S16, U32, …)
      - Plain name: 'u8Speed', 'u16Voltage'
        → type inferred from naming prefix (u8, u16, s32, …)
    """
    # ── 1. Explicit type token from annotated '[IN] TYPE varname' format ────
    type_match = re.search(
        r"\b(U8|U16|U32|U64|S8|S16|S32|S64|BOOL|BOOLEAN|FLOAT|FLOAT32|DOUBLE)\b",
        var_name,
        re.IGNORECASE,
    )
    if type_match:
        tok = type_match.group(1).upper()
        _type_map = {
            "U8": "uint8", "U16": "uint16", "U32": "uint32", "U64": "uint32",
            "S8": "int8",  "S16": "int16",  "S32": "int32",  "S64": "int32",
            "BOOL": "bool", "BOOLEAN": "bool",
            "FLOAT": "float", "FLOAT32": "float", "DOUBLE": "float",
        }
        return _BOUNDARY_SETS[_type_map[tok]]

    # ── 2. Naming-convention prefix / suffix (plain variable names) ─────────
    name = var_name.lower().lstrip("_")
    if re.search(r"\bu8|uint8|byte", name):
        return _BOUNDARY_SETS["uint8"]
    if re.search(r"\bu16|uint16|word", name):
        return _BOUNDARY_SETS["uint16"]
    if re.search(r"\bu32|uint32|dword", name):
        return _BOUNDARY_SETS["uint32"]
    if re.search(r"\bs8\b|int8", name):
        return _BOUNDARY_SETS["int8"]
    if re.search(r"\bs16\b|int16", name):
        return _BOUNDARY_SETS["int16"]
    if re.search(r"\bs32\b|int32", name):
        return _BOUNDARY_SETS["int32"]
    if re.search(r"float|flt|f32", name):
        return _BOUNDARY_SETS["float"]
    if re.search(r"flag|enable|active|bool|b_", name):
        return _BOUNDARY_SETS["bool"]
    return _BOUNDARY_SETS["default"]


def _clean_var_name(raw: str) -> str:
    """Extract clean variable name from annotated string like '[IN] u8g_Speed'."""
    s = re.sub(r"\[.*?\]", "", raw).strip()
    s = s.split("(")[0].strip()
    s = re.sub(r"\s+", "_", s)
    return s or raw[:40]


def _get_module_name(info: Dict[str, Any]) -> str:
    """Derive module/component name from function info."""
    file_path = info.get("file") or info.get("source_file") or ""
    if file_path:
        stem = Path(file_path).stem
        # Strip trailing _PDS, _Main suffixes to get component
        stem = re.sub(r"(_PDS|_Main|_main)$", "", stem, flags=re.IGNORECASE)
        return stem
    return info.get("module_name") or info.get("component") or "Unknown"


def _infer_swcom_id(module_name: str, swcom_counter: Dict[str, int]) -> str:
    """Map module name to SwCom_XX ID, assigning new IDs incrementally."""
    key = module_name.lower()
    if key not in swcom_counter:
        swcom_counter[key] = len(swcom_counter) + 1
    return f"SwCom_{swcom_counter[key]:02d}"


def _parse_req_ids(text: str) -> List[str]:
    """Extract SwXX_NN requirement IDs from text."""
    return re.findall(r"\bSw(?:TR|TSR|NTR|NTSR|ST|STR|Fn|Com)_\d+\b", text or "")


# ---------------------------------------------------------------------------
# Core: integration flow collection
# ---------------------------------------------------------------------------

def collect_integration_flows(
    function_details: Dict[str, Dict[str, Any]],
    max_flows: int = 120,
) -> List[Dict[str, Any]]:
    """Identify cross-module integration flows from function call graph.

    An integration flow is a function that calls functions from a different
    module (file).  Flows are grouped by the calling function (entry point).

    Returns list of flow dicts:
      { flow_id, entry_fn, call_chain, functions, module_name, swcom_id,
        input_vars, expected_vars, asil, related_ids }
    """
    # Build name → info lookup
    name_to_info: Dict[str, Dict[str, Any]] = {}
    for fid, info in function_details.items():
        if isinstance(info, dict):
            name_to_info[str(info.get("name") or "")] = info

    # Set of all project function names (lower-case) for ISR-artefact filtering
    _fn_name_set: set = {n.lower() for n in name_to_info if n}

    swcom_counter: Dict[str, int] = {}
    flows: List[Dict[str, Any]] = []
    seen_entries: set = set()

    # Sort by name for deterministic output
    sorted_items = sorted(
        [(fid, info) for fid, info in function_details.items() if isinstance(info, dict)],
        key=lambda x: str(x[1].get("name") or ""),
    )

    for fid, info in sorted_items:
        if len(flows) >= max_flows:
            break

        fn_name = str(info.get("name") or "")
        if not fn_name or fn_name in seen_entries:
            continue

        calls_list = list(info.get("calls_list") or [])
        if not calls_list:
            continue

        my_module = _get_module_name(info)

        # Find calls that cross module boundaries.
        # Only include callees that are known project functions (present in name_to_info).
        # External library / OS calls (memset, printf, …) are excluded because they are
        # not in the parsed function graph and do not represent software integration flows.
        cross_calls: List[str] = []
        for callee in calls_list:
            callee_info = name_to_info.get(callee)
            if callee_info:
                callee_module = _get_module_name(callee_info)
                if callee_module and callee_module.lower() != my_module.lower():
                    cross_calls.append(callee)

        if not cross_calls:
            continue

        seen_entries.add(fn_name)

        # Build call chain string
        chain_parts = [fn_name] + cross_calls[:4]
        call_chain = " -> ".join(chain_parts)

        # Collect variables
        # Each entry stored as (display_name, annotated_raw) so that
        # _infer_boundary_values can use the explicit C type token.
        inputs_raw = list(info.get("inputs") or [])
        outputs_raw = list(info.get("outputs") or [])
        globals_g = list(info.get("globals_global") or [])
        globals_s = list(info.get("globals_static") or [])

        # Build (var_name, annotated_raw) pairs — filter out entries whose
        # cleaned name matches a known function name (ISR stub artefact).
        input_pairs: List[Tuple[str, str]] = []
        # Pointer parameters of the entry function are observable I/O.
        # _lw_parse_params strips '*' from var names, so detect via prototype instead.
        ptr_out_pairs: List[Tuple[str, str]] = []
        _proto = str(info.get("prototype") or "")
        _ptr_params: set = set()
        if _proto and "(" in _proto:
            _param_str = _proto.split("(", 1)[1].rsplit(")", 1)[0]
            for _pp in _param_str.split(","):
                _pp = _pp.strip()
                if "*" in _pp and "const" not in _pp.lower():
                    # Extract variable name (last token, stripped of *)
                    _pparts = _pp.split()
                    if _pparts:
                        _pname = _pparts[-1].strip("*&;")
                        if _pname:
                            _ptr_params.add(_pname.lower())
        for raw in inputs_raw[:20]:
            vn = _clean_var_name(raw)
            if vn.lower() not in _fn_name_set and vn not in {p[0] for p in input_pairs}:
                input_pairs.append((vn, raw))
                # Pointer param (*) is also an out-parameter
                if vn.lower() in _ptr_params:
                    ptr_out_pairs.append((vn, raw))

        # If entry has no inputs, aggregate callee inputs as integration-level inputs
        if not input_pairs:
            for callee in cross_calls[:4]:
                callee_info = name_to_info.get(callee)
                if callee_info:
                    # Build pointer param set from callee prototype
                    _cproto = str(callee_info.get("prototype") or "")
                    _c_ptr_params: set = set()
                    if _cproto and "(" in _cproto:
                        _cps = _cproto.split("(", 1)[1].rsplit(")", 1)[0]
                        for _cpp in _cps.split(","):
                            _cpp = _cpp.strip()
                            if "*" in _cpp and "const" not in _cpp.lower():
                                _cpparts = _cpp.split()
                                if _cpparts:
                                    _cpname = _cpparts[-1].strip("*&;")
                                    if _cpname:
                                        _c_ptr_params.add(_cpname.lower())
                    for craw in (callee_info.get("inputs") or [])[:6]:
                        cvn = _clean_var_name(craw)
                        if cvn and cvn.lower() not in _fn_name_set and cvn not in {p[0] for p in input_pairs}:
                            input_pairs.append((cvn, craw))
                            if cvn.lower() in _c_ptr_params:
                                ptr_out_pairs.append((cvn, craw))
                if len(input_pairs) >= _MAX_INPUT_PARAMS:
                    break

        # Globals as additional observed inputs
        for g in (globals_g + globals_s)[:15]:
            gn = _clean_var_name(g)
            if gn and gn.lower() not in _fn_name_set and gn not in {p[0] for p in input_pairs}:
                input_pairs.append((gn, g))

        input_vars: List[str] = [p[0] for p in input_pairs[:_MAX_INPUT_PARAMS]]
        # Keep annotated raws for type inference
        input_raws: List[str] = [p[1] for p in input_pairs[:_MAX_INPUT_PARAMS]]

        # Expected: own outputs + pointer out-params + callee outputs + callee globals
        exp_pairs: List[Tuple[str, str]] = []
        for raw in outputs_raw[:10]:
            vn = _clean_var_name(raw)
            if vn and vn.lower() not in _fn_name_set:
                exp_pairs.append((vn, raw))
        # Pointer out-params of entry function are expected observables
        for vn, raw in ptr_out_pairs:
            if vn not in {p[0] for p in exp_pairs}:
                exp_pairs.append((vn, raw))
        for callee in cross_calls[:5]:
            callee_info = name_to_info.get(callee)
            if callee_info:
                for v in (callee_info.get("outputs") or [])[:5]:
                    vn = f"{callee}() {_clean_var_name(v)}"
                    if vn not in {p[0] for p in exp_pairs}:
                        exp_pairs.append((vn, v))
                # Callee globals as observable side-effect outputs
                for g in ((callee_info.get("globals_global") or []) + (callee_info.get("globals_static") or []))[:4]:
                    gn = _clean_var_name(g)
                    label = f"{callee}() {gn}"
                    if gn and gn.lower() not in _fn_name_set and label not in {p[0] for p in exp_pairs}:
                        exp_pairs.append((label, g))

        # If still no expected vars, mine global writes from logic_flow conditions
        if not exp_pairs:
            _GLOBAL_WRITE_RE = re.compile(
                r"\b(g_\w+|gs_\w+|g[A-Z]\w+)\s*(?:\[[\w\s+\-*]+\])?\s*=",
            )
            for src_fn in [fn_name] + list(cross_calls[:4]):
                src_info = name_to_info.get(src_fn) if src_fn != fn_name else info
                if not src_info:
                    continue
                for node in (src_info.get("logic_flow") or [])[:20]:
                    for m in _GLOBAL_WRITE_RE.finditer(str(node.get("text", "") + node.get("condition", ""))):
                        gname = m.group(1)
                        label = f"{src_fn}() {gname}"
                        if label not in {p[0] for p in exp_pairs}:
                            exp_pairs.append((label, gname))
                if len(exp_pairs) >= _MAX_EXP_PARAMS:
                    break

        expected_vars: List[str] = [p[0] for p in exp_pairs[:_MAX_EXP_PARAMS]]
        expected_raws: List[str] = [p[1] for p in exp_pairs[:_MAX_EXP_PARAMS]]

        # ASIL
        asil = str(info.get("asil") or "QM")
        if asil in ("TBD", ""):
            asil = "QM"

        # Related IDs
        related_parts: List[str] = []
        # from srs_req_ids field
        for field in ("srs_req_ids", "related", "related_id"):
            val = info.get(field) or ""
            ids = _parse_req_ids(str(val))
            related_parts.extend(ids)
        # from SDS map
        try:
            sds_map = _load_default_sds_map()
            for cand in [fn_name, fn_name.lower()]:
                entry = sds_map.get(cand)
                if entry:
                    swcom_cand = entry.get("swcom") or entry.get("component")
                    if swcom_cand:
                        related_parts.append(swcom_cand)
                    break
        except Exception:
            pass
        # Assign SwCom
        swcom_id = _infer_swcom_id(my_module, swcom_counter)
        if swcom_id not in related_parts:
            related_parts.insert(0, swcom_id)

        # Deduplicate while preserving order
        seen_rel: set = set()
        deduped_related: List[str] = []
        for r in related_parts:
            if r and r not in seen_rel:
                seen_rel.add(r)
                deduped_related.append(r)

        flows.append({
            "flow_id": fid,
            "entry_fn": fn_name,
            "call_chain": call_chain,
            "cross_calls": cross_calls,
            "functions": [fn_name] + cross_calls,
            "module_name": my_module,
            "swcom_id": swcom_id,
            "input_vars": input_vars,
            "input_raws": input_raws,   # annotated originals for type inference
            "expected_vars": expected_vars,
            "expected_raws": expected_raws,
            "asil": asil,
            "related_ids": deduped_related,
            "logic_flow": info.get("logic_flow") or [],
        })

    _logger.info("SITS: collected %d integration flows", len(flows))
    return flows


def _balance_related_ids(
    flows: List[Dict[str, Any]],
    max_freq_pct: float = 0.20,
) -> List[Dict[str, Any]]:
    """Redistribute over-concentrated Related IDs across flows.

    A req_id that appears in more than ``max_freq_pct`` of all flows is
    considered "over-used".  For flows that reference an over-used req_id
    *and* have at least one other (non-SwCom) req_id available, the
    over-used req_id is dropped so that SwCom IDs and less-frequent
    req_ids are surfaced instead.  SwCom_xx structural IDs are never
    removed.
    """
    total = len(flows)
    if total == 0:
        return flows

    max_count = max(1, int(total * max_freq_pct))

    # Count how many flows use each req_id
    usage: Dict[str, int] = {}
    for flow in flows:
        for rid in (flow.get("related_ids") or []):
            usage[rid] = usage.get(rid, 0) + 1

    over_used = {rid for rid, cnt in usage.items() if cnt > max_count and not rid.startswith("SwCom_")}
    if not over_used:
        return flows

    _logger.info(
        "_balance_related_ids: %d over-used IDs (threshold %d/%d): %s",
        len(over_used), max_count, total, sorted(over_used),
    )

    trimmed = 0
    for flow in flows:
        rids = flow.get("related_ids") or []
        non_swcom = [r for r in rids if not r.startswith("SwCom_")]
        # Only drop over-used IDs when there are other non-SwCom alternatives
        if len(non_swcom) > 1:
            filtered = [r for r in rids if r not in over_used or r.startswith("SwCom_")]
            if len(filtered) < len(rids):
                flow["related_ids"] = filtered
                trimmed += 1

    _logger.info("_balance_related_ids: trimmed %d flows", trimmed)
    return flows


# ---------------------------------------------------------------------------
# Core: ITC generation
# ---------------------------------------------------------------------------

def _determine_gen_method_for_flow(flow: Dict[str, Any]) -> str:
    """Select ABV / AEC / AOR based on flow characteristics."""
    logic = flow.get("logic_flow") or []
    has_cond = any(
        isinstance(n, dict) and n.get("type") in ("if", "switch")
        for n in logic
    )
    n_inputs = len(flow.get("input_vars", []))
    n_cross = len(flow.get("cross_calls", []))

    if n_cross >= 3:
        return "AOR, ABV"
    if has_cond and n_inputs > 0:
        return "ABV, AEC"
    if n_inputs > 2:
        return "ABV"
    return "ABV, AEC"


def _generate_sub_cases(
    flow: Dict[str, Any],
    max_cases: int = _DEFAULT_SUBCASES,
    stp_environments: Optional[List[str]] = None,
    gen_method: str = "ABV",
) -> List[Dict[str, Any]]:
    """Generate sub-cases (boundary value rows) for an integration flow.

    Each sub-case has:
      case_num, call_chain, precondition, inputs {var: value}, expected {var: value}

    If ``stp_environments`` is provided (parsed from STP document), each sub-case
    precondition cycles through the defined test environments (HW-in-the-loop, ECU
    network, etc.) instead of a plain numeric index.
    """
    input_vars = flow.get("input_vars") or []
    expected_vars = flow.get("expected_vars") or []
    # Annotated originals carry explicit C type tokens (e.g. '[IN] U16 u16Speed')
    input_raws = flow.get("input_raws") or input_vars
    expected_raws = flow.get("expected_raws") or expected_vars
    call_chain = flow.get("call_chain", "")

    use_aec = "AEC" in str(gen_method).upper()

    # AEC equivalence class labels aligned to the 7-value boundary set:
    #   [min_inv, min_valid, low_mid, mid, high_mid, max_valid, max_inv]
    _AEC_LABELS: List[str] = [
        "EC1:무효-하한",   # min_inv    — invalid below minimum
        "EC2:유효-하한",   # min_valid  — valid lower boundary
        "EC3:유효-정상-L", # low_mid    — valid nominal low
        "EC4:유효-중간",   # mid        — valid mid
        "EC5:유효-정상-H", # high_mid   — valid nominal high
        "EC6:유효-상한",   # max_valid  — valid upper boundary
        "EC7:무효-상한",   # max_inv    — invalid above maximum
    ]

    def _precondition(case_idx: int) -> str:
        if stp_environments:
            return stp_environments[case_idx % len(stp_environments)]
        return str(case_idx + 1)

    def _case_label(case_idx: int) -> str:
        """Case number with optional AEC equivalence class label."""
        num = case_idx + 1
        if use_aec and case_idx < len(_AEC_LABELS):
            return f"{num} [{_AEC_LABELS[case_idx]}]"
        return str(num)

    if not input_vars:
        # No explicit inputs: generate scenario-based sub-cases using environment cycling.
        # Even without I/O data, integration flows can be exercised in multiple test
        # environments / scenarios (normal, boundary, error) per ISTQB integration test.
        _SCENARIO_LABELS = [
            "Normal operation",
            "Boundary condition",
            "Error / fault injection",
            "Post-initialization state",
            "Concurrent invocation",
            "Recovery sequence",
            "Stress / extended run",
        ]
        n_no_io = min(max_cases, len(_SCENARIO_LABELS)) if max_cases > 1 else 1
        # If STP environments available, cap to realistic count
        if stp_environments:
            n_no_io = min(n_no_io, max(max_cases, len(stp_environments)))
        result_cases: List[Dict[str, Any]] = []
        for i in range(n_no_io):
            scenario = _SCENARIO_LABELS[i]
            label = _case_label(i)
            precond = _precondition(i)
            result_cases.append({
                "case_num": i + 1,
                "case_label": label,
                "call_chain": call_chain if i == 0 else "",
                "precondition": precond,
                "inputs": {"Scenario": scenario},
                "expected": {v: "N/A" for v in (expected_vars[:5] or ["Result"])},
            })
        return result_cases

    # Determine boundary value sets using annotated raws first (type-token priority),
    # then fall back to name-prefix heuristic for plain variable names.
    bv_sets = [_infer_boundary_values(r) for r in input_raws]
    n_cases = min(max_cases, len(bv_sets[0]))

    sub_cases: List[Dict[str, Any]] = []
    for case_idx in range(n_cases):
        inputs: Dict[str, Any] = {}
        for var_idx, var_name in enumerate(input_vars):
            bv = bv_sets[var_idx]
            inputs[var_name] = bv[case_idx] if case_idx < len(bv) else bv[-1]

        # Expected: boundary-aware values using annotated raws
        expected: Dict[str, Any] = {}
        is_boundary = (case_idx == 0 or case_idx == n_cases - 1)
        for ev_idx, ev in enumerate(expected_vars):
            ev_raw = expected_raws[ev_idx] if ev_idx < len(expected_raws) else ev
            bv_exp = _infer_boundary_values(ev_raw)
            if is_boundary:
                # Error boundary → clamp to nearest valid value
                expected[ev] = bv_exp[1] if case_idx == 0 else bv_exp[3]
            else:
                expected[ev] = bv_exp[case_idx] if case_idx < len(bv_exp) else bv_exp[-1]

        sub_cases.append({
            "case_num": case_idx + 1,
            "case_label": _case_label(case_idx),
            "call_chain": call_chain if case_idx == 0 else "",
            "precondition": _precondition(case_idx),
            "inputs": inputs,
            "expected": expected,
        })

    return sub_cases


def generate_itc_list(
    flows: List[Dict[str, Any]],
    max_subcases: int = _DEFAULT_SUBCASES,
    stp_environments: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Generate list of Integration Test Cases from flows.

    Each ITC has:
      tc_id, gen_method, input_vars, expected_vars, related_ids, sub_cases
    """
    itcs: List[Dict[str, Any]] = []
    for idx, flow in enumerate(flows, start=1):
        tc_id = f"SwITC_{idx:02d}"
        gen_method = _determine_gen_method_for_flow(flow)
        sub_cases = _generate_sub_cases(
            flow, max_cases=max_subcases,
            stp_environments=stp_environments,
            gen_method=gen_method,
        )
        # If scenario-based sub-cases were generated (no real IO), expose the "Scenario"
        # pseudo-input so the XLSM writer renders the column header + values.
        effective_input_vars = list(flow["input_vars"])
        effective_expected_vars = list(flow["expected_vars"])
        if not effective_input_vars and sub_cases and "Scenario" in (sub_cases[0].get("inputs") or {}):
            effective_input_vars = ["Scenario"]
        # If expected_vars is empty but sub-cases carry result, add "Result" header
        if not effective_expected_vars and sub_cases:
            first_exp = sub_cases[0].get("expected") or {}
            if first_exp:
                effective_expected_vars = list(first_exp.keys())[:_MAX_EXP_PARAMS]
        itcs.append({
            "tc_id": tc_id,
            "gen_method": gen_method,
            "entry_fn": flow["entry_fn"],
            "call_chain": flow["call_chain"],
            "module_name": flow["module_name"],
            "input_vars": effective_input_vars,
            "expected_vars": effective_expected_vars,
            "related_ids": flow["related_ids"],
            "sub_cases": sub_cases,
            "asil": flow["asil"],
        })
    _logger.info("SITS: generated %d ITCs, %d total sub-cases",
                 len(itcs), sum(len(t["sub_cases"]) for t in itcs))
    return itcs


# ---------------------------------------------------------------------------
# Excel generation
# ---------------------------------------------------------------------------

def _create_sits_cover(
    wb, project_id: str, doc_id: str, version: str, asil_level: str,
    stp_context: Optional[Dict[str, Any]] = None,
) -> None:
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    ws = wb.active
    ws.title = "Cover"

    title_font = Font(name="맑은 고딕", size=24, bold=True)
    label_font = Font(name="맑은 고딕", size=9, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    col_widths = {"A": 2.875, "B": 6.875, "C": 13.0, "D": 13.0, "E": 13.0,
                  "F": 13.0, "G": 13.0, "H": 4.625, "I": 6.875, "J": 13.0, "K": 10.625}
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    ws.merge_cells("B5:K5")
    ws["B5"] = "Software Integration Test Specification\n(소프트웨어 통합테스트 명세서)"
    ws["B5"].font = title_font
    ws["B5"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[5].height = 123.0

    ws["I2"] = "Doc. ID"
    ws["I2"].font = label_font
    ws["I2"].alignment = center
    ws.merge_cells("J2:K2")
    ws["J2"] = doc_id
    ws["J2"].font = data_font
    ws["J2"].alignment = center

    ws["I3"] = "Version"
    ws["I3"].font = label_font
    ws["I3"].alignment = center
    ws.merge_cells("J3:K3")
    ws["J3"] = version
    ws["J3"].font = data_font
    ws["J3"].alignment = center

    stp_doc_id = (stp_context or {}).get("doc_id", "")
    stp_ver = (stp_context or {}).get("version", "")
    stp_ref = stp_doc_id + (f" {stp_ver}" if stp_ver else "")
    info_rows = [
        ("Project", project_id),
        ("ASIL Level", asil_level),
        ("STP Ref.", stp_ref or "-"),
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


def _create_sits_history(wb, version: str) -> None:
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    ws = wb.create_sheet("History")
    hdr_font = Font(name="맑은 고딕", size=10, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")

    for col, w in {"A": 1.25, "B": 8.375, "C": 9.125, "D": 35.5,
                   "E": 8.625, "F": 13.0, "G": 13.0, "H": 1.25}.items():
        ws.column_dimensions[col].width = w

    ws.merge_cells("B2:G2")
    ws["B2"] = "▶ Revision History"
    ws["B2"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B2"].alignment = Alignment(horizontal="left", vertical="center")

    for i, h in enumerate(["Version", "Date", "Description", "Author", "Reviewer", "Approver"]):
        c = ws.cell(row=4, column=2 + i, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = thin
        c.alignment = center

    for ci, val in enumerate([version, datetime.now().strftime("%Y.%m.%d"),
                               "- Auto-generated", "Auto", "-", "-"]):
        cell = ws.cell(row=5, column=2 + ci, value=val)
        cell.font = data_font
        cell.border = thin


def _create_sits_intro(wb) -> None:
    from openpyxl.styles import Font
    ws = wb.create_sheet("1.Introduction")
    ws["A1"] = "Introduction"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B3"] = "1.1 Purpose"
    ws["B3"].font = Font(name="맑은 고딕", size=10, bold=True)
    ws["B4"] = (
        "본 문서는 소프트웨어 통합테스트 명세를 기술하는 문서이며, "
        "소프트웨어 통합테스트 수행자에 의해서 작성된다."
    )
    ws["B6"] = "1.2 Scope"
    ws["B6"].font = Font(name="맑은 고딕", size=10, bold=True)
    ws["B7"] = (
        "본 문서는 소프트웨어 컴포넌트 간 통합 인터페이스 및 "
        "통합 테스트 케이스를 정의한다."
    )


def _create_sits_test_env(wb, stp_context: Optional[Dict[str, Any]] = None) -> None:
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    ws = wb.create_sheet("2.Test Environment")
    ws["A1"] = "Test Environments"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)

    stp_doc_id = (stp_context or {}).get("doc_id", "")
    envs = (stp_context or {}).get("environments", [])

    if envs:
        stp_ref = f"STP 참조: {stp_doc_id}" if stp_doc_id else "STP 참조"
        ws["B3"] = f"통합 테스트는 {stp_ref}에서 정의된 환경을 기준으로 수행된다."
        ws["B3"].font = Font(name="맑은 고딕", size=9)

        thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                      top=Side(style="thin"), bottom=Side(style="thin"))
        hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
        hdr_font = Font(name="맑은 고딕", size=9, bold=True)
        data_font = Font(name="맑은 고딕", size=9)
        center = Alignment(horizontal="center", vertical="center")

        ws.cell(row=5, column=2, value="SwITE ID").font = hdr_font
        ws.cell(row=5, column=2).fill = hdr_fill
        ws.cell(row=5, column=2).border = thin
        ws.cell(row=5, column=2).alignment = center
        ws.cell(row=5, column=3, value="Test Environment").font = hdr_font
        ws.cell(row=5, column=3).fill = hdr_fill
        ws.cell(row=5, column=3).border = thin
        ws.cell(row=5, column=3).alignment = center

        for i, env in enumerate(envs, start=1):
            r = 5 + i
            ws.cell(row=r, column=2, value=f"SwITE_{i:02d}").font = data_font
            ws.cell(row=r, column=2).border = thin
            ws.cell(row=r, column=2).alignment = center
            ws.cell(row=r, column=3, value=env).font = data_font
            ws.cell(row=r, column=3).border = thin
    else:
        ws["B3"] = (
            "통합 테스트는 SwITE_01에서 정의된 환경을 기준으로 수행된다.\n"
            "- SwITE_01은 STP에서 정의되어 있다."
        )


def _create_sits_strategy(wb, flows: List[Dict[str, Any]]) -> None:
    """Create integration strategy sheet listing component call hierarchy."""
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    ws = wb.create_sheet("3-1.SW Integration Strategy")
    hdr_font = Font(name="맑은 고딕", size=10, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")

    ws["A1"] = "Software Integration Strategy"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["A3"] = "통합 순서 및 컴포넌트 경계 호출 목록:"
    ws["A3"].font = hdr_font

    for ci, h in enumerate(["SwCom ID", "Module", "Entry Function", "Cross-Module Calls"], start=1):
        c = ws.cell(row=5, column=ci, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = thin
        c.alignment = Alignment(horizontal="center", vertical="center")

    # Deduplicate by swcom_id + entry_fn
    seen: set = set()
    row = 6
    for f in flows:
        key = (f["swcom_id"], f["entry_fn"])
        if key in seen:
            continue
        seen.add(key)
        calls_str = ", ".join(f["cross_calls"][:8])
        for ci, val in enumerate([f["swcom_id"], f["module_name"],
                                   f["entry_fn"], calls_str], start=1):
            c = ws.cell(row=row, column=ci, value=val)
            c.font = data_font
            c.border = thin
        row += 1
        if row > 500:
            break


def generate_sits_xlsm(
    template_path: Optional[str],
    itcs: List[Dict[str, Any]],
    output_path: str,
    project_config: Optional[Dict[str, Any]] = None,
    flows: Optional[List[Dict[str, Any]]] = None,
    stp_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate SITS XLSM file matching the reference structure."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        _logger.error("openpyxl not installed")
        raise

    cfg = project_config or {}
    project_id = cfg.get("project_id", "PROJECT")
    doc_id = cfg.get("doc_id", f"{project_id}-SITS")
    version = cfg.get("version", "v1.00")
    asil_level = cfg.get("asil_level", "")

    if template_path and Path(template_path).is_file():
        wb = openpyxl.load_workbook(template_path, keep_vba=True)
        _logger.info("Loaded SITS template: %s", template_path)
    else:
        wb = openpyxl.Workbook()
        _create_sits_cover(wb, project_id, doc_id, version, asil_level, stp_context=stp_context)
        _create_sits_history(wb, version)
        _create_sits_intro(wb)
        _create_sits_test_env(wb, stp_context=stp_context)
        _create_sits_strategy(wb, flows or [])
        _logger.info("Created new SITS workbook (no template)")

    thin = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    hdr_font = Font(name="맑은 고딕", size=9, bold=True)
    data_font = Font(name="맑은 고딕", size=8)
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sheet_name = "4.SW Integration Test Spec"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)

    # ── Row 1: title ────────────────────────────────────────────────────────
    title_font = Font(name="맑은 고딕", size=13, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=_RELATED_COL)
    ws.cell(row=1, column=1, value="Software Integration Test Specification").font = title_font
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    # ── Helper: fill + merge ────────────────────────────────────────────────
    def _fill_and_merge(row: int, c_start: int, c_end: int, label: str) -> None:
        for c in range(c_start, c_end + 1):
            ws.cell(row=row, column=c).fill = hdr_fill
            ws.cell(row=row, column=c).border = thin
            ws.cell(row=row, column=c).alignment = center
        ws.cell(row=row, column=c_start, value=label).font = hdr_font
        if c_end > c_start:
            try:
                ws.merge_cells(start_row=row, start_column=c_start,
                                end_row=row, end_column=c_end)
            except Exception:
                pass

    # ── Row 5: group headers ────────────────────────────────────────────────
    _fill_and_merge(5, _TCID_COL, _GEN_COL + 1, "Test Case")
    _fill_and_merge(5, _INPUT_COL_START, _INPUT_COL_END, "Input")
    _fill_and_merge(5, _EXP_COL_START, _EXP_COL_END, "Expected Result")
    _fill_and_merge(5, _RELATED_COL, _RELATED_COL, "Related ID")
    ws.row_dimensions[5].height = 18

    # ── Row 6: detail headers ───────────────────────────────────────────────
    detail_headers: Dict[int, str] = {
        _TCID_COL: "TC ID",
        _DESC_COL: "Description",
        _CHAIN_COL: "Call Chain",
        _GEN_COL: "Test Case Generation Method",
        _PRECOND_COL: "Precondition",
        _RELATED_COL: "SwDS",
    }
    for col_i in range(1, _RELATED_COL + 1):
        cell = ws.cell(row=6, column=col_i)
        cell.fill = hdr_fill
        cell.border = thin
        cell.alignment = center
        cell.font = hdr_font
        if col_i in detail_headers:
            cell.value = detail_headers[col_i]
        elif _INPUT_COL_START <= col_i <= _INPUT_COL_END:
            cell.value = f"Param {col_i - _INPUT_COL_START + 1}"
        elif _EXP_COL_START <= col_i <= _EXP_COL_END:
            cell.value = f"Param {col_i - _EXP_COL_START + 1}"
    ws.row_dimensions[6].height = 30

    # ── Column widths ────────────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 1.0
    ws.column_dimensions[get_column_letter(_TCID_COL)].width = 14
    ws.column_dimensions[get_column_letter(_DESC_COL)].width = 10
    ws.column_dimensions[get_column_letter(_CHAIN_COL)].width = 40
    ws.column_dimensions[get_column_letter(_GEN_COL)].width = 14
    ws.column_dimensions[get_column_letter(_PRECOND_COL)].width = 10
    for ci in range(_INPUT_COL_START, _INPUT_COL_END + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 9
    for ci in range(_EXP_COL_START, _EXP_COL_END + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 9
    ws.column_dimensions[get_column_letter(_RELATED_COL)].width = 35

    # ── Data rows ────────────────────────────────────────────────────────────
    current_row = 7
    for itc in itcs:
        tc_id = itc["tc_id"]
        input_vars = itc.get("input_vars") or []
        expected_vars = itc.get("expected_vars") or []
        related_str = ", ".join(itc.get("related_ids") or [])
        gen_method = itc.get("gen_method", "ABV")

        # TC header row
        tc_desc = (
            f"Verify integration: {itc.get('entry_fn', '')} → "
            + " → ".join((itc.get("call_chain") or "").split(" -> ")[1:3])
        ).rstrip(" →")

        ws.cell(row=current_row, column=_TCID_COL, value=tc_id).font = Font(name="맑은 고딕", size=9, bold=True)
        ws.cell(row=current_row, column=_TCID_COL).border = thin
        ws.cell(row=current_row, column=_DESC_COL, value=tc_desc).font = data_font
        ws.cell(row=current_row, column=_DESC_COL).border = thin
        ws.cell(row=current_row, column=_DESC_COL).alignment = wrap
        ws.cell(row=current_row, column=_GEN_COL, value=gen_method).font = data_font
        ws.cell(row=current_row, column=_GEN_COL).border = thin
        ws.cell(row=current_row, column=_RELATED_COL, value=related_str).font = data_font
        ws.cell(row=current_row, column=_RELATED_COL).border = thin
        ws.cell(row=current_row, column=_RELATED_COL).alignment = wrap

        # Input param name headers in TC row
        for vi, var_name in enumerate(input_vars[:_MAX_INPUT_PARAMS]):
            col = _INPUT_COL_START + vi
            ws.cell(row=current_row, column=col, value=var_name).font = data_font
            ws.cell(row=current_row, column=col).border = thin

        # Expected param name headers in TC row
        for vi, var_name in enumerate(expected_vars[:_MAX_EXP_PARAMS]):
            col = _EXP_COL_START + vi
            ws.cell(row=current_row, column=col, value=var_name).font = data_font
            ws.cell(row=current_row, column=col).border = thin

        ws.row_dimensions[current_row].height = 18
        current_row += 1

        # Sub-case rows
        for sc in itc.get("sub_cases") or []:
            desc_val = sc.get("case_label") or sc["case_num"]
            ws.cell(row=current_row, column=_DESC_COL, value=desc_val).font = data_font
            ws.cell(row=current_row, column=_DESC_COL).border = thin
            ws.cell(row=current_row, column=_DESC_COL).alignment = wrap

            chain_val = sc.get("call_chain") or ""
            if chain_val:
                ws.cell(row=current_row, column=_CHAIN_COL, value=chain_val).font = data_font
                ws.cell(row=current_row, column=_CHAIN_COL).alignment = wrap
            ws.cell(row=current_row, column=_CHAIN_COL).border = thin

            ws.cell(row=current_row, column=_PRECOND_COL, value=sc.get("precondition", "")).font = data_font
            ws.cell(row=current_row, column=_PRECOND_COL).border = thin

            # Input values
            sc_inputs = sc.get("inputs") or {}
            for vi, var_name in enumerate(input_vars[:_MAX_INPUT_PARAMS]):
                col = _INPUT_COL_START + vi
                val = sc_inputs.get(var_name, "")
                ws.cell(row=current_row, column=col, value=val).font = data_font
                ws.cell(row=current_row, column=col).border = thin
                ws.cell(row=current_row, column=col).alignment = center

            # Expected values
            sc_expected = sc.get("expected") or {}
            for vi, var_name in enumerate(expected_vars[:_MAX_EXP_PARAMS]):
                col = _EXP_COL_START + vi
                val = sc_expected.get(var_name, "")
                ws.cell(row=current_row, column=col, value=val).font = data_font
                ws.cell(row=current_row, column=col).border = thin
                ws.cell(row=current_row, column=col).alignment = center

            ws.row_dimensions[current_row].height = 14
            current_row += 1

    # Freeze panes at row 7 col C
    ws.freeze_panes = "C7"

    # Save
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    _logger.info("SITS XLSM saved: %s (rows=%d)", out_path.name, current_row - 7)
    return str(out_path)


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def generate_sits_quality_report(
    itcs: List[Dict[str, Any]],
    total_source_functions: int = 0,
) -> Dict[str, Any]:
    total_tc = len(itcs)
    total_sub = sum(len(t.get("sub_cases") or []) for t in itcs)
    avg_sub = round(total_sub / max(total_tc, 1), 1)

    gen_dist: Dict[str, int] = {}
    for itc in itcs:
        for m in re.split(r"[,\s]+", itc.get("gen_method") or "ABV"):
            m = m.strip()
            if m:
                gen_dist[m] = gen_dist.get(m, 0) + 1

    with_related = sum(1 for t in itcs if t.get("related_ids"))
    related_pct = round(with_related / max(total_tc, 1) * 100, 1)

    swcom_dist: Dict[str, int] = {}
    for t in itcs:
        rids = t.get("related_ids") or []
        for r in rids:
            if r.startswith("SwCom_"):
                swcom_dist[r] = swcom_dist.get(r, 0) + 1

    with_io = sum(
        1 for t in itcs
        if t.get("input_vars") or t.get("expected_vars")
    )
    io_pct = round(with_io / max(total_tc, 1) * 100, 1)

    return {
        "total_test_cases": total_tc,
        "total_sub_cases": total_sub,
        "avg_sub_cases_per_tc": avg_sub,
        "with_related_count": with_related,
        "related_coverage_pct": related_pct,
        "with_io_count": with_io,
        "io_coverage_pct": io_pct,
        "gen_method_distribution": gen_dist,
        "swcom_distribution": swcom_dist,
        "total_source_functions": total_source_functions,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_sits_xlsm(xlsm_path: str) -> Dict[str, Any]:
    """Validate generated SITS XLSM for structural and data quality."""
    issues: List[str] = []
    stats: Dict[str, Any] = {}

    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"valid": False, "issues": ["openpyxl not installed"], "stats": {}}

    p = Path(xlsm_path)
    if not p.exists():
        return {"valid": False, "issues": [f"File not found: {xlsm_path}"], "stats": {}}

    try:
        wb = load_workbook(str(p), read_only=True, data_only=True)
    except Exception as e:
        return {"valid": False, "issues": [f"Cannot open: {e}"], "stats": {}}

    stats["sheets"] = wb.sheetnames
    stats["sheet_count"] = len(wb.sheetnames)

    required_sheets = ["4.SW Integration Test Spec"]
    for s in required_sheets:
        if s not in wb.sheetnames:
            issues.append(f"Missing required sheet: {s}")

    tc_count = 0
    sub_count = 0

    if "4.SW Integration Test Spec" in wb.sheetnames:
        ws = wb["4.SW Integration Test Spec"]
        for row in ws.iter_rows(min_row=7, values_only=True):
            if not row:
                continue
            tc_id_val = row[_TCID_COL - 1] if len(row) >= _TCID_COL else None
            desc_val = row[_DESC_COL - 1] if len(row) >= _DESC_COL else None
            if tc_id_val and str(tc_id_val).startswith("SwITC_"):
                tc_count += 1
            elif desc_val is not None and re.match(r"^\d", str(desc_val).strip()):
                sub_count += 1

        stats["tc_count"] = tc_count
        stats["flow_count"] = tc_count  # 1 flow per ITC in SITS
        stats["sub_case_count"] = sub_count
        stats["avg_sub_per_tc"] = round(sub_count / max(tc_count, 1), 1)

        if tc_count == 0:
            issues.append("No test cases (SwITC_*) found")
        if sub_count == 0:
            issues.append("No sub-cases found")

    wb.close()
    return {"valid": len(issues) == 0, "issues": issues, "stats": stats}


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

def generate_sits_validation_report(
    xlsm_path: str,
    quality_report: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> str:
    """Write .validation.md file next to XLSM and return its path."""
    validation_data = validation if isinstance(validation, dict) else validate_sits_xlsm(xlsm_path)
    stats = validation_data.get("stats", {})
    issues = validation_data.get("issues", [])
    qr = quality_report or {}

    lines = [
        "# SITS 생성 문서 자동 검증 리포트",
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
        f"| TC 수 (SwITC_*) | {stats.get('tc_count', 0)} |",
        f"| Sub-case 수 | {stats.get('sub_case_count', 0)} |",
        f"| TC당 평균 Sub-case | {stats.get('avg_sub_per_tc', 0)} |",
        "",
    ]

    if qr:
        lines += [
            "## 2. 품질 지표",
            "",
            "| 항목 | 값 |",
            "|------|-----|",
            f"| 총 TC 수 | {qr.get('total_test_cases', 0)} |",
            f"| 총 Sub-case 수 | {qr.get('total_sub_cases', 0)} |",
            f"| Related ID 보유 TC | {qr.get('with_related_count', 0)} |",
            f"| Related ID 커버리지 | {qr.get('related_coverage_pct', 0)}% |",
            f"| I/O 파라미터 보유 TC | {qr.get('with_io_count', 0)} |",
            f"| I/O 커버리지 | {qr.get('io_coverage_pct', 0)}% |",
            f"| 생성 방법 분포 | {qr.get('gen_method_distribution', {})} |",
            "",
        ]

    if issues:
        lines += ["## 3. 이슈", ""]
        for iss in issues:
            lines.append(f"- ❌ {iss}")
    else:
        lines += ["## 3. 이슈", "", "- 이슈 없음"]

    report_path = Path(xlsm_path).with_suffix(".validation.md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _logger.info("SITS validation report: %s", report_path.name)
    return str(report_path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_sits(
    source_root: str,
    output_path: str,
    template_path: Optional[str] = None,
    project_config: Optional[Dict[str, Any]] = None,
    ai_config: Optional[Dict[str, Any]] = None,
    max_subcases: int = _DEFAULT_SUBCASES,
    on_progress: Optional[Any] = None,
    srs_docx_path: Optional[str] = None,
    sds_docx_path: Optional[str] = None,
    uds_path: Optional[str] = None,
    hsis_path: Optional[str] = None,
    stp_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Top-level SITS generation pipeline.

    Args:
        source_root: Root directory of C source code
        output_path: Path for output XLSM file
        template_path: Optional SITS template XLSM
        project_config: Optional config dict (project_id, version, asil_level, doc_id)
        ai_config: Optional AI config dict (reserved, not used yet)
        max_subcases: Maximum sub-cases per TC (default 5)
        on_progress: Optional callback(pct: int, message: str)
        max_subcases: Maximum sub-cases per TC (default 7)
        srs_docx_path: Optional SRS DOCX for requirement ID enrichment
        sds_docx_path: Optional SDS DOCX for component context
        uds_path: Optional UDS DOCX/XLSM for function descriptions
        hsis_path: Optional HSIS XLSX for hardware signal context
        stp_path: Optional STP DOCX for test strategy context

    Returns:
        Dict with: output_path, quality_report, test_case_count, total_sub_cases,
                   elapsed_seconds, validation, validation_report_path
    """
    def _progress(pct: int, msg: str) -> None:
        _logger.info("[%d%%] %s", pct, msg)
        if on_progress:
            try:
                on_progress(pct, msg)
            except Exception:
                pass

    _logger.info("=== SITS Generation Start ===")
    t0 = time.time()

    _progress(5, "SITS 생성 시작")

    # ── Stage 1-4: document context loading ─────────────────────────────────
    if sds_docx_path:
        _progress(7, "SDS 설계 컨텍스트 로드 중")
        try:
            from generators.sts import _load_sds_summary
            sds_summary = _load_sds_summary(sds_docx_path)
            if sds_summary:
                _logger.info("SITS: SDS summary loaded (%d chars)", len(sds_summary))
        except Exception as e:
            _logger.debug("SITS: SDS load skipped: %s", e)

    if uds_path:
        _progress(8, "UDS 함수 설명 로드 중")
        try:
            from generators.sts import _load_uds_descriptions
            _uds_descs = _load_uds_descriptions(uds_path)
            if _uds_descs:
                _logger.info("SITS: UDS descriptions loaded (%d entries)", len(_uds_descs))
        except Exception as e:
            _logger.debug("SITS: UDS load skipped: %s", e)

    stp_context: Dict[str, Any] = {}
    if stp_path:
        _progress(9, "STP 시험 전략 로드 중")
        try:
            stp_context = _parse_stp_document(stp_path)
        except Exception as e:
            _logger.debug("SITS: STP load skipped: %s", e)

    if hsis_path:
        _progress(10, "HSIS 신호 로드 중")
        try:
            from generators.sts import _load_hsis_signals
            _hsis = _load_hsis_signals(hsis_path)
            if _hsis:
                _logger.info("SITS: HSIS signals loaded")
        except Exception as e:
            _logger.debug("SITS: HSIS load skipped: %s", e)

    # ── Stage 5: source parsing ──────────────────────────────────────────────
    _progress(15, "소스 코드 파싱 시작")
    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.is_dir():
        return {
            "output_path": "",
            "quality_report": {},
            "test_case_count": 0,
            "total_sub_cases": 0,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": "유효한 소스 코드 루트 경로가 없습니다.",
        }

    function_details: Dict[str, Dict[str, Any]] = {}
    total_source_functions = 0
    try:
        try:
            from backend.helpers import _get_source_sections_cached
            report_data = _get_source_sections_cached(str(source_root_path))
        except Exception:
            from report_generator import generate_uds_source_sections
            report_data = generate_uds_source_sections(str(source_root_path))
        function_details = report_data.get("function_details", {})
        total_source_functions = len(function_details)
        if not function_details:
            raise ValueError("No function_details in source parse result")
    except Exception as e:
        _logger.warning("SITS: full source parse failed, trying lightweight: %s", e)
        try:
            from generators.suts import _lightweight_parse
            function_details = _lightweight_parse(str(source_root_path))
            total_source_functions = len(function_details)
        except Exception as e2:
            _logger.error("SITS: lightweight parse also failed: %s", e2)
            return {
                "output_path": "",
                "quality_report": {},
                "test_case_count": 0,
                "total_sub_cases": 0,
                "elapsed_seconds": round(time.time() - t0, 1),
                "error": f"소스 파싱 실패: {e2}",
            }

    _progress(30, f"소스 파싱 완료 — {total_source_functions}개 함수 발견")

    # SRS requirement ID enrichment — per-function mapping
    if srs_docx_path:
        _progress(32, "SRS 요구사항 ID 매핑 중")
        try:
            from generators.sts import parse_srs_docx_tables
            reqs = parse_srs_docx_tables(srs_docx_path)
            if reqs:
                _logger.info("SITS: SRS reqs loaded (%d)", len(reqs))

                # Build a map: fn_name_lower → [req_ids] by scanning each requirement's
                # description for function names.  Only exact word-boundary matches count
                # to avoid "get" matching "get_speed", "get_torque", etc.
                _fn_names_lower = {
                    str(info.get("name") or "").lower(): fid
                    for fid, info in function_details.items()
                    if isinstance(info, dict) and len(str(info.get("name") or "")) >= 4
                }
                fn_to_req_ids: Dict[str, List[str]] = {}
                for req in reqs:
                    req_id = str(req.get("id") or "").strip()
                    if not req_id:
                        continue
                    req_desc = str(req.get("description") or "").lower()
                    for fn_lower in _fn_names_lower:
                        # Word-boundary match: function name must appear as whole word
                        if re.search(r"\b" + re.escape(fn_lower) + r"\b", req_desc):
                            fn_to_req_ids.setdefault(fn_lower, [])
                            if req_id not in fn_to_req_ids[fn_lower]:
                                fn_to_req_ids[fn_lower].append(req_id)

                # Annotate function_details
                matched = 0
                for fid, info in function_details.items():
                    if not isinstance(info, dict):
                        continue
                    fn_lower = str(info.get("name") or "").lower()
                    ids = fn_to_req_ids.get(fn_lower)
                    if ids:
                        info.setdefault("srs_req_ids", ", ".join(ids[:3]))
                        matched += 1
                _logger.info("SITS: SRS enrichment: %d functions matched", matched)
        except Exception as e:
            _logger.debug("SITS: SRS enrichment skipped: %s", e)

    # UDS description enrichment
    if uds_path:
        try:
            from generators.sts import _load_uds_descriptions, _merge_uds_into_function_details
            uds_descs = _load_uds_descriptions(uds_path)
            if uds_descs:
                _merge_uds_into_function_details(function_details, uds_descs)
        except Exception as e:
            _logger.debug("SITS: UDS enrichment skipped: %s", e)

    # ── Stage 6: collect integration flows ───────────────────────────────────
    _progress(40, "통합 흐름 수집 중")
    flows = collect_integration_flows(function_details)

    if not flows:
        _logger.warning("SITS: No integration flows found — check cross-module calls in source")
        return {
            "output_path": "",
            "quality_report": {},
            "test_case_count": 0,
            "total_sub_cases": 0,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": "통합 흐름을 찾을 수 없습니다. 소스 파싱 결과를 확인해주세요.",
        }

    _progress(50, f"{len(flows)}개 통합 흐름 수집 완료")

    # ── Stage 6b: balance over-concentrated Related IDs ──────────────────────
    flows = _balance_related_ids(flows)

    # ── Stage 7: generate ITCs ───────────────────────────────────────────────
    _progress(60, "통합 테스트 케이스 생성 중")
    stp_envs = stp_context.get("environments") or []
    itcs = generate_itc_list(flows, max_subcases=max_subcases, stp_environments=stp_envs or None)

    _progress(65, f"{len(itcs)}개 TC, {sum(len(t['sub_cases']) for t in itcs)}개 sub-case 생성 완료")

    # ── Stage 8: quality report ──────────────────────────────────────────────
    _progress(70, "품질 보고서 생성 중")
    quality_report = generate_sits_quality_report(itcs, total_source_functions)

    # ── Stage 9: XLSM generation ─────────────────────────────────────────────
    _progress(80, "XLSM 파일 생성 중")
    try:
        actual_output = generate_sits_xlsm(
            template_path=template_path,
            itcs=itcs,
            output_path=output_path,
            project_config=project_config,
            flows=flows,
            stp_context=stp_context,
        )
    except Exception as e:
        _logger.error("SITS: XLSM generation failed: %s", e)
        return {
            "output_path": "",
            "quality_report": quality_report,
            "test_case_count": len(itcs),
            "total_sub_cases": sum(len(t["sub_cases"]) for t in itcs),
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": f"XLSM 생성 실패: {e}",
        }

    # ── Stage 9.5: save intermediate JSON for VectorCAST export ─────────────
    try:
        _intermediate: Dict[str, Any] = {
            "schema_version": "1.0",
            "project_id": (project_config or {}).get("project_id", "PROJECT"),
            "source": {
                "source_root": source_root,
                "sits_path": actual_output,
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "integrations": [
                {
                    "tc_id": itc["tc_id"],
                    "entry_fn": itc["entry_fn"],
                    "call_chain": itc["call_chain"],
                    "module_name": itc["module_name"],
                    "gen_method": itc["gen_method"],
                    "asil": itc.get("asil", "QM"),
                    "metadata": {"related_ids": itc["related_ids"]},
                    "sub_cases": [
                        {
                            "case_num": sc.get("case_num", i + 1),
                            "case_label": sc.get("case_label", str(i + 1)),
                            "precondition": sc.get("precondition", ""),
                            "inputs": sc.get("inputs") or {},
                            "expected": sc.get("expected") or {},
                        }
                        for i, sc in enumerate(itc.get("sub_cases") or [])
                    ],
                }
                for itc in itcs
            ],
            "export_warnings": [],
        }
        _intermediate_path = Path(actual_output).with_name(
            Path(actual_output).stem + "_vectorcast.json"
        )
        _intermediate_path.write_text(
            json.dumps(_intermediate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _logger.info("SITS: intermediate JSON saved → %s", _intermediate_path)
    except Exception as _e:
        _logger.warning("SITS: intermediate JSON save failed: %s", _e)

    # ── Stage 10: validation ─────────────────────────────────────────────────
    _progress(90, "XLSM 검증 중")
    validation = validate_sits_xlsm(actual_output)

    # ── Stage 11: validation report ──────────────────────────────────────────
    _progress(95, "검증 보고서 생성 중")
    validation_report_path = ""
    try:
        validation_report_path = generate_sits_validation_report(
            actual_output, quality_report, validation
        )
    except Exception as e:
        _logger.warning("SITS: validation report generation failed: %s", e)

    elapsed = round(time.time() - t0, 1)
    _progress(100, f"SITS 생성 완료 ({elapsed}s)")
    _logger.info("=== SITS Generation Done: %d TCs, %d sub-cases, %.1fs ===",
                 len(itcs), sum(len(t["sub_cases"]) for t in itcs), elapsed)

    return {
        "output_path": actual_output,
        "quality_report": quality_report,
        "test_case_count": len(itcs),
        "total_sub_cases": sum(len(t["sub_cases"]) for t in itcs),
        "elapsed_seconds": elapsed,
        "validation": validation,
        "validation_report_path": validation_report_path,
    }
