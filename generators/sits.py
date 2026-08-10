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

from generators._artifact_check import apply_write_back_check
from report_gen.doc_kind import is_sds_filename

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

# Row 6 상세 헤더(열 번호 → 라벨). `generate_sits_xlsm`이 시트에 쓰는 값이자, 영향도 탭의
# 문서 초안이 Excel 붙여넣기 TSV 열 순서를 얻는 **단일 출처**다(복제 금지 — suts와 동일 원칙).
_DETAIL_HEADERS = {
    _TCID_COL: "TC ID",
    _DESC_COL: "Description",
    _CHAIN_COL: "Call Chain",
    _GEN_COL: "Test Case Generation Method",
    _PRECOND_COL: "Precondition",
    _RELATED_COL: "SwDS",
}
# (`_MAX_SUBCASES = 16` 은 어디서도 참조되지 않는 죽은 상수였다 — 옆의 14 와 값이 달라
#  "상한 16 이 걸린다" 는 오해를 부른다. 실제 상한은 아래 _DEFAULT_SUBCASES 뿐이다.)
_DEFAULT_SUBCASES = 14  # 7 BV + 4 COND_COMB + 2 ERR_PROP + 2 GLOBAL

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
    "bool":   [-1,    0,     0,     0,    1,     1,     2],
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
        # `*SDS*` 글롭은 `SwDS` 표기를 놓친다("swds" 에 "sds" 없음) — 전량 글롭 후 단일 출처로 거른다.
        sds_files = sorted(p for p in docs_dir.glob("*.docx") if is_sds_filename(p.name))
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

# 통합 흐름 상한. 폭주 방지용 안전밸브이지 "이만큼만 시험하면 된다"는 뜻이 아니다.
# 실측(KJPDS02 계열 900함수)에서는 흐름 145개 중 25개가 이 값에 걸린다 — 걸리면
# 경고 + 품질 리포트(`integration_flow_coverage`)에 남으므로 값 조정은 보고 나서 판단할 것.
_DEFAULT_MAX_FLOWS = 120

_ASIL_RANK: Dict[str, int] = {"D": 0, "C": 1, "B": 2, "A": 3, "QM": 4}


def _asil_rank(asil: Any) -> int:
    """ASIL 선별 우선순위 — 값이 작을수록 먼저 남긴다. 미상 등급은 QM 뒤로 보낸다."""
    return _ASIL_RANK.get(str(asil or "").strip().upper(), len(_ASIL_RANK))


def _select_flows_within_cap(
    candidates: List[Dict[str, Any]],
    max_flows: Optional[int],
    stats_out: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """`max_flows` 캡을 적용하되 **무엇이 잘렸는지 남기고**, 안전등급 높은 쪽을 살린다.

    예전엔 수집 루프가 캡에 닿으면 그냥 `break` 했다. 정렬 키가 함수명 알파벳순이라
    어느 흐름이 살아남는지가 **안전등급과 무관**하게 정해졌고, 잘렸다는 사실 자체가
    어디에도 안 남았다(로그·품질 리포트 모두). 실측(KJPDS02 계열 900함수):
    통합 흐름 145개 중 25개가 조용히 사라졌고 그 중 7개가 ASIL A 였다 —
    같은 모듈(Sys_UDS_LinComp)이 알파벳 경계에서 두 동강 났다.

    출력 순서는 알파벳 그대로 둔다(선별만 안전우선). 문서 행 순서를 흔들지 않기 위해서다.
    """
    total = len(candidates)
    kept = candidates
    dropped: List[Dict[str, Any]] = []

    if max_flows is not None and 0 <= max_flows < total:
        indexed = list(enumerate(candidates))
        # (등급, 알파벳 순번) — 같은 등급 안에서는 기존 순서를 그대로 지킨다(결정성 유지).
        ranked = sorted(indexed, key=lambda t: (_asil_rank(t[1].get("asil")), t[0]))
        keep_idx = {i for i, _ in ranked[:max_flows]}
        kept = [c for i, c in indexed if i in keep_idx]
        dropped = [c for i, c in indexed if i not in keep_idx]

    dist: Dict[str, int] = {}
    for c in dropped:
        key = str(c.get("asil") or "QM")
        dist[key] = dist.get(key, 0) + 1
    safety_dropped = sum(
        n for a, n in dist.items() if a.strip().upper() in ("A", "B", "C", "D")
    )

    if stats_out is not None:
        stats_out.update({
            "total_flows_found": total,
            "max_flows": max_flows,
            "flows_emitted": len(kept),
            "flows_dropped": len(dropped),
            "flow_emit_pct": round(len(kept) / max(total, 1) * 100, 1),
            "dropped_entry_fns": [str(c.get("fn_name") or "") for c in dropped],
            "dropped_asil_distribution": dist,
            "dropped_safety_related_count": safety_dropped,
        })

    if dropped:
        _logger.warning(
            "SITS: 통합 흐름 %d개 중 %d개만 생성한다 — max_flows=%s 캡으로 %d개 제외"
            "(안전관련 ASIL A~D %d개 포함). 제외된 흐름은 시험 규격에 **존재하지 않는다**. "
            "예: %s",
            total, len(kept), max_flows, len(dropped), safety_dropped,
            ", ".join(str(c.get("fn_name") or "") for c in dropped[:5]),
        )

    return kept


def collect_integration_flows(
    function_details: Dict[str, Dict[str, Any]],
    # ⚠ `None` = 캡 없음. `_select_flows_within_cap` 은 처음부터 `Optional[int]` 를
    #   받았는데 여기만 `int` 로 좁아, 캡 **전** 총량을 재려는 호출자가 타입상 막혔다.
    #   (총량은 캡 전에만 보인다 — 결과 길이로 되짚으면 절단을 못 본다.)
    max_flows: Optional[int] = _DEFAULT_MAX_FLOWS,
    stats_out: Optional[Dict[str, Any]] = None,
    sds_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Identify cross-module integration flows from function call graph.

    An integration flow is a function that calls functions from a different
    module (file).  Flows are grouped by the calling function (entry point).

    Returns list of flow dicts:
      { flow_id, entry_fn, call_chain, functions, module_name, swcom_id,
        input_vars, expected_vars, asil, related_ids }

    Args:
        sds_map: Related ID 보강용 SDS 파티션 맵. None 이면 저장소 `docs/` 글롭
            (`_load_default_sds_map`)으로 폴백하는데 이는 **프로젝트 무관**이다
            — `sts.py`/`suts.py` 는 이미 같은 파라미터를 갖고 있었고 여기만 없어서
            **호출자가 대상 프로젝트의 SDS 를 줄 방법 자체가 없었다.**

    `stats_out` 를 주면 캡 절단 내역(총 후보 수·제외 수·제외분 ASIL 분포)과
    **SDS 보강 실적**(`sds_*` 키)을 채운다. 소비처에서 결과 길이로 되짚으면 절단을 못
    본다 — 캡 **전** 총량이 여기서만 보인다.
    """
    # ── SDS 보강 계측 ──────────────────────────────────────────────────────
    # ⚠ 실측(2026-07-31): 이 보강은 **한 건도 산출한 적이 없다.**
    #   `_load_default_sds_map()` 이 주는 맵의 값 스키마는
    #   `{kind, description, related, asil, component_description, canonical}` 인데
    #   여기서는 `entry.get("swcom") or entry.get("component")` 를 읽었다 — **없는
    #   필드**라 항상 None 이고, 그 사실이 `except Exception: pass` 에 묻혀 있었다.
    #   (같은 맵을 쓰는 `sts.py::_lookup_sds_related_ids` 는 실재 필드 `related` 를 읽는다.)
    #   대체 필드를 **추측하지 않는다** — 틀린 SwCom 을 추적성 열에 넣는 건 0 건보다 나쁘다.
    #   대신 0 을 **보이게** 만든다: 아래 카운터가 `stats_out` 으로 나간다.
    _sds_lookups = 0        # 조회 시도한 함수 수
    _sds_key_hits = 0       # 맵에서 키가 잡힌 수
    _sds_swcom_hits = 0     # 실제로 SwCom 을 얻은 수
    _sds_source = "argument" if sds_map is not None else "repo_docs_glob"
    if sds_map is None:
        sds_map = _load_default_sds_map()
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

    # ── Pass 1: 자격 판정만 (싸다) — 후보를 **전부** 모은다 ──────────────────
    # 예전엔 이 루프가 `len(flows) >= max_flows` 에서 break 했다. 그러면 캡 이후의
    # 후보는 세어지지도 않아 "몇 개가 잘렸는지" 를 아무도 알 수 없다. 자격 판정
    # (calls_list 유무 + cross-module callee 유무)은 dict 조회뿐이라 전량 수행해도 싸고,
    # 비싼 변수/기대값 구성은 Pass 2 에서 선별된 것에만 한다 = 기존 비용과 동일.
    candidates: List[Dict[str, Any]] = []
    for fid, info in sorted_items:
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

        _cand_asil = str(info.get("asil") or "QM")
        if _cand_asil in ("TBD", ""):
            _cand_asil = "QM"

        # ⚠ SwCom 은 **후보 전체**(알파벳순)에 대해 여기서 부여한다. 예전엔 캡 안쪽
        # 루프에서 부여돼 **ID 가 캡 값에 의존**했다 — 캡을 바꾸면 같은 모듈이 다른
        # SwCom 을 받는다. 후보 전체 기준이면 캡·선별 정책이 바뀌어도 ID 가 고정된다.
        # (실측: 이 프로젝트는 캡 120/무제한 어느 쪽도 모듈 29개·ID 변동 0건 = 무해한 변경)
        candidates.append({
            "fid": fid,
            "info": info,
            "fn_name": fn_name,
            "my_module": my_module,
            "cross_calls": cross_calls,
            "asil": _cand_asil,
            "swcom_id": _infer_swcom_id(my_module, swcom_counter),
        })

    # ── 캡 적용: 안전등급 높은 쪽을 남기고, 잘린 내역을 stats_out 에 남긴다 ────
    selected = _select_flows_within_cap(candidates, max_flows, stats_out)

    # ── Pass 2: 선별된 후보만 비싼 구성 ──────────────────────────────────────
    for _cand in selected:
        fid = _cand["fid"]
        info = _cand["info"]
        fn_name = _cand["fn_name"]
        my_module = _cand["my_module"]
        cross_calls = _cand["cross_calls"]

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

        # ASIL — Pass 1 에서 정규화한 값을 그대로 쓴다. 여기서 다시 계산하면
        # 선별 기준(등급)과 방출 값이 갈라질 수 있다.
        asil = _cand["asil"]

        # Related IDs
        related_parts: List[str] = []
        # from srs_req_ids field
        for field in ("srs_req_ids", "related", "related_id"):
            val = info.get(field) or ""
            ids = _parse_req_ids(str(val))
            related_parts.extend(ids)
        # from SDS map — 결과가 0 이어도 **왜 0 인지** 셀 수 있어야 한다(위 주석 참조).
        _sds_lookups += 1
        try:
            for cand in [fn_name, fn_name.lower()]:
                entry = sds_map.get(cand)
                if entry:
                    _sds_key_hits += 1
                    swcom_cand = entry.get("swcom") or entry.get("component")
                    if swcom_cand:
                        related_parts.append(swcom_cand)
                        _sds_swcom_hits += 1
                    break
        except Exception as e:  # noqa: BLE001 - 조회 실패는 보고하고 계속한다
            _logger.warning("SITS: SDS Related 보강 조회 실패(%s) — 이 함수는 건너뛴다: %s",
                            type(e).__name__, fn_name)
        # Assign SwCom.
        # ⚠ _infer_swcom_id는 **모듈 등장 순번**으로 만든 합성 ID다(실제 SDS component ID가
        # 아니다). 모든 flow에 무조건 들어가므로 related_ids는 절대 비지 않는다 — 이 값을
        # 요구 추적성 분자로 세면 항상 100%가 된다. 어느 ID가 합성인지 **삽입 지점에서**
        # 기록해 두어 품질 지표가 추측 없이 걸러낼 수 있게 한다.
        # (위 SDS map이 같은 ID를 이미 넣었다면 그건 문서 유래이므로 합성으로 치지 않는다.)
        swcom_id = _cand["swcom_id"]   # Pass 1 에서 후보 전체 기준으로 부여됨
        synthetic_related: List[str] = []
        if swcom_id not in related_parts:
            related_parts.insert(0, swcom_id)
            synthetic_related.append(swcom_id)

        # Deduplicate while preserving order
        seen_rel: set = set()
        deduped_related: List[str] = []
        for r in related_parts:
            if r and r not in seen_rel:
                seen_rel.add(r)
                deduped_related.append(r)

        # Collect indirect (global) vars for GLOBAL strategy
        indirect_vars_list: List[str] = []
        for g in globals_g + globals_s:
            tag = str(g).upper()
            gn = _clean_var_name(g)
            if gn and "[INDIRECT]" in tag and gn not in {p[0] for p in input_pairs}:
                if gn not in indirect_vars_list and len(indirect_vars_list) < 5:
                    indirect_vars_list.append(gn)
        # Also collect from callees
        for callee in cross_calls[:4]:
            callee_info = name_to_info.get(callee)
            if callee_info:
                for g in (callee_info.get("globals_global") or [])[:5]:
                    tag = str(g).upper()
                    gn = _clean_var_name(g)
                    if gn and "[INDIRECT]" in tag and gn not in indirect_vars_list:
                        if len(indirect_vars_list) < 5:
                            indirect_vars_list.append(gn)

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
            "indirect_vars": indirect_vars_list,
            "asil": asil,
            "related_ids": deduped_related,
            # related_ids 중 순번 기반 합성분(요구 추적성 분자에서 제외 — 위 삽입부 주석)
            "synthetic_related_ids": synthetic_related,
            "logic_flow": info.get("logic_flow") or [],
        })

    # SDS 보강 실적을 **반드시** 내보낸다. 0 을 침묵시키면 "보강이 동작한다" 로 읽힌다.
    if stats_out is not None:
        stats_out.update({
            "sds_source": _sds_source,
            "sds_map_entries": len(sds_map or {}),
            "sds_lookups": _sds_lookups,
            "sds_key_hits": _sds_key_hits,
            "sds_swcom_hits": _sds_swcom_hits,
        })
    if _sds_lookups and not _sds_swcom_hits:
        _logger.warning(
            "SITS: SDS 기반 Related 보강이 %d회 조회에서 **0건** 산출했다 "
            "(키 매칭 %d건, 맵 %d항목, 출처=%s). 맵 스키마에 swcom/component 필드가 "
            "없거나 다른 프로젝트의 SDS 다 — Related ID 의 SwCom 축은 비어 있다.",
            _sds_lookups, _sds_key_hits, len(sds_map or {}), _sds_source,
        )
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

    # ── Additional strategies for branch coverage ──
    next_num = len(sub_cases) + 1

    # GAP A: Condition combination — toggle each input while others at mid
    if len(input_vars) >= 2 and len(sub_cases) < max_cases:
        for toggle_idx in range(min(4, len(input_vars))):
            if len(sub_cases) >= max_cases:
                break
            comb_inputs: Dict[str, Any] = {}
            for vi, vname in enumerate(input_vars):
                bv = bv_sets[vi] if vi < len(bv_sets) else _infer_boundary_values(vname)
                if vi == toggle_idx:
                    comb_inputs[vname] = bv[1] if toggle_idx % 2 == 0 else bv[5]  # min or max
                else:
                    comb_inputs[vname] = bv[3]  # mid
            comb_expected: Dict[str, Any] = {}
            for ev_idx, ev in enumerate(expected_vars):
                ev_raw = expected_raws[ev_idx] if ev_idx < len(expected_raws) else ev
                bv_exp = _infer_boundary_values(ev_raw)
                comb_expected[ev] = bv_exp[3]  # mid expected
            toggle_var = input_vars[toggle_idx] if toggle_idx < len(input_vars) else f"var{toggle_idx}"
            direction = "최솟값" if toggle_idx % 2 == 0 else "최댓값"
            sub_cases.append({
                "case_num": next_num,
                "case_label": f"COND_{toggle_idx+1} [{toggle_var}={direction}]",
                "call_chain": "",
                "precondition": f"조건 조합: {toggle_var}={direction}, 나머지=중간값",
                "inputs": comb_inputs,
                "expected": comb_expected,
            })
            next_num += 1

    # GAP C: Error propagation — inject boundary errors and check chain behavior
    if input_vars and len(sub_cases) < max_cases:
        for err_idx, err_key in enumerate(["min_inv", "max_inv"]):
            if len(sub_cases) >= max_cases:
                break
            err_inputs: Dict[str, Any] = {}
            for vi, vname in enumerate(input_vars):
                bv = bv_sets[vi]
                err_inputs[vname] = bv[0] if err_key == "min_inv" else bv[-1]
            err_expected: Dict[str, Any] = {}
            for ev_idx, ev in enumerate(expected_vars):
                ev_raw = expected_raws[ev_idx] if ev_idx < len(expected_raws) else ev
                bv_exp = _infer_boundary_values(ev_raw)
                err_expected[ev] = bv_exp[1] if err_key == "min_inv" else bv_exp[5]
            direction = "하한 초과" if err_key == "min_inv" else "상한 초과"
            sub_cases.append({
                "case_num": next_num,
                "case_label": f"ERR_PROP_{err_idx+1} [{direction}]",
                "call_chain": "",
                "precondition": f"에러 전파: 입력 {direction} → 콜체인 방어 처리 확인",
                "inputs": err_inputs,
                "expected": err_expected,
            })
            next_num += 1

    # GAP D: Global state combination — toggle indirect (global) vars
    indirect_vars = flow.get("indirect_vars") or []
    if indirect_vars and input_vars and len(sub_cases) < max_cases:
        for gv_idx, gv in enumerate(indirect_vars[:2]):
            if len(sub_cases) >= max_cases:
                break
            gstate_inputs: Dict[str, Any] = {}
            for vi, vname in enumerate(input_vars):
                bv = bv_sets[vi]
                gstate_inputs[vname] = bv[3]  # mid
            gv_bv = _infer_boundary_values(gv)
            gstate_inputs[gv] = gv_bv[1]  # global at min
            gstate_expected: Dict[str, Any] = {}
            for ev_idx, ev in enumerate(expected_vars):
                ev_raw = expected_raws[ev_idx] if ev_idx < len(expected_raws) else ev
                bv_exp = _infer_boundary_values(ev_raw)
                gstate_expected[ev] = bv_exp[3]
            gstate_expected[gv] = gv_bv[1]  # expect global stays at min (no change by function)
            sub_cases.append({
                "case_num": next_num,
                "case_label": f"GLOBAL_{gv_idx+1} [{gv}=min]",
                "call_chain": "",
                "precondition": f"글로벌 상태: {gv}=최솟값, 입력=중간값 → 상태 의존 분기 커버",
                "inputs": gstate_inputs,
                "expected": gstate_expected,
            })
            next_num += 1

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
            "synthetic_related_ids": flow.get("synthetic_related_ids") or [],
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
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
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
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
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
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
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
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
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

    # ── Row 6: detail headers ── 정의는 모듈 상수 `_DETAIL_HEADERS`(단일 출처) ──
    # 별칭이 아니라 사본 — 이후 누가 여기서 헤더를 덧쓰더라도 모듈 상수가 오염되지 않게.
    detail_headers: Dict[int, str] = dict(_DETAIL_HEADERS)
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
    flow_stats: Optional[Dict[str, Any]] = None,
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

    # ── 요구 추적성은 Related ID 보유율과 다른 축이다 ──
    # collect_integration_flows가 모든 flow에 순번 기반 합성 SwCom_XX를 삽입하므로
    # related_ids는 절대 비지 않는다 → related_pct는 사실상 항상 100%다. 그 값을 요구
    # 추적성으로 쓰면 요구 링크가 하나도 없어도 게이트를 통과한다. 여기서는 **삽입 지점이
    # 기록한 synthetic_related_ids를 뺀 실제 ID**로만 분자를 센다(문자열 prefix 추측 아님 —
    # SDS 문서에서 온 진짜 SwCom ID는 합성으로 분류되지 않는다).
    def _real_related(t: Dict[str, Any]) -> List[str]:
        synth = set(t.get("synthetic_related_ids") or [])
        return [r for r in (t.get("related_ids") or []) if r not in synth]

    with_req_trace = sum(1 for t in itcs if _real_related(t))
    req_trace_pct = round(with_req_trace / max(total_tc, 1) * 100, 1)
    # related_ids는 있으나 전부 합성인 TC — "링크 있음"으로 보이지만 추적 근거는 0이다.
    synthetic_only_count = sum(
        1 for t in itcs if (t.get("related_ids") and not _real_related(t))
    )

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

    # ── 통합 흐름 캡 절단 (있으면) ──────────────────────────────────────────
    # TC 수(total_test_cases)만 보면 "흐름 120개 전부 시험함" 으로 읽힌다. 분모는
    # 생성된 흐름 수가 아니라 **소스에서 찾은 흐름 수**다 — 캡에 잘린 만큼 규격에
    # 아예 없는 흐름이 생기므로 그 사실을 리포트에 남긴다.
    fs = flow_stats or {}
    flow_cov: Dict[str, Any] = {}
    if fs.get("total_flows_found") is not None:
        _found = int(fs.get("total_flows_found") or 0)
        flow_cov = {
            "total_flows_found": _found,
            "flows_emitted": int(fs.get("flows_emitted") or 0),
            "flows_dropped": int(fs.get("flows_dropped") or 0),
            "flow_emit_pct": fs.get("flow_emit_pct"),
            "max_flows": fs.get("max_flows"),
            "dropped_safety_related_count": int(fs.get("dropped_safety_related_count") or 0),
            "dropped_asil_distribution": fs.get("dropped_asil_distribution") or {},
            "dropped_entry_fns": list(fs.get("dropped_entry_fns") or []),
        }

    # SDS 기반 Related 보강 실적. **조건 없이** 싣는다 — 0 건이야말로 실어야 하는 값이다.
    # ⚠ 이걸 빠뜨렸다가 자체 감사에서 잡혔다: `collect_integration_flows` 가 `stats_out`
    #   으로 `sds_*` 를 내보내도 여기서 **이름 지정한 8개 키만** 골라 담아 전부 버려졌고,
    #   그래서 보강 실적은 로그에만 남았다(품질 리포트는 API 로 나가지만 로그는 안 나간다).
    #   "보고를 추가했다" 와 "보고가 도달한다" 는 다른 문제다.
    sds_enrich: Dict[str, Any] = {}
    if fs.get("sds_lookups") is not None:
        _lk = int(fs.get("sds_lookups") or 0)
        _hit = int(fs.get("sds_swcom_hits") or 0)
        sds_enrich = {
            "source": fs.get("sds_source"),            # argument | repo_docs_glob
            "map_entries": int(fs.get("sds_map_entries") or 0),
            "lookups": _lk,
            "key_hits": int(fs.get("sds_key_hits") or 0),
            "swcom_hits": _hit,
            # 분모 0 = 미측정(0% 아님) — 이 저장소 규약
            "yield_pct": round(100.0 * _hit / _lk, 2) if _lk else None,
        }

    return {
        "total_test_cases": total_tc,
        "total_sub_cases": total_sub,
        "avg_sub_cases_per_tc": avg_sub,
        # 캡에 잘린 흐름이 있으면 비지 않는다(없으면 {} — 소비처는 .get 으로 읽는다).
        "integration_flow_coverage": flow_cov,
        # SDS 보강이 **어느 문서로 몇 건** 산출했는지. 저장소 폴백(프로젝트 무관)이면
        # source 로 드러난다.
        "sds_related_enrichment": sds_enrich,
        # Related ID **필드 보유율**(합성 포함) — 서식 채움 지표이지 추적성이 아니다.
        "with_related_count": with_related,
        "related_coverage_pct": related_pct,
        # 실제 요구/설계 ID 기준 추적성(합성 SwCom 제외) — 품질 게이트가 쓰는 값.
        "with_requirement_trace_count": with_req_trace,
        "requirement_traceability_pct": req_trace_pct,
        "synthetic_only_related_count": synthetic_only_count,
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
            elif desc_val is not None and str(desc_val).strip():
                # ⚠ 예전엔 `re.match(r"^\d", desc)` 였다 — desc 가 숫자로 시작할 때만
                # sub-case 로 셌다. 그런데 라이터는 `case_label or case_num` 을 쓰고
                # case_label 은 `COND_1 [...]`·`ERR_PROP_1 [...]`·`GLOBAL_*` 처럼 문자로
                # 시작한다. 라이터 포맷이 바뀌었는데 리더 휴리스틱이 안 따라간 것이다.
                # 실측(실 프로젝트 120 TC): 파일에 1288행이 있는데 840 만 세어 34.8% 과소,
                # avg_sub_per_tc 도 7.0(실제 10.7)이었다. 그런데 valid 는 True 였다.
                # 판정을 프리픽스 추측이 아니라 **구조**로 바꾼다: 라이터는 sub-case 행에
                # TC ID 를 절대 안 쓰고 _DESC_COL 은 항상 채운다(위 writer 참조).
                # 이 시트는 template 이 있어도 통째로 지우고 다시 만들므로 잔여행이 없다.
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
            f"| Related ID 커버리지 (합성 포함) | {qr.get('related_coverage_pct', 0)}% |",
            f"| 요구 추적성 (합성 SwCom 제외) | {qr.get('requirement_traceability_pct', 0)}% |",
            f"| 합성 ID만 있는 TC | {qr.get('synthetic_only_related_count', 0)} |",
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
    # ⚠ 신규 인자는 **맨 끝**에 붙인다. 중간에 끼우면 위치 인자로 부르는 호출부가
    #    조용히 다른 값에 바인딩된다(현재 호출부 4곳은 전부 키워드지만 계약은 지킨다).
    max_flows: int = _DEFAULT_MAX_FLOWS,
) -> Dict[str, Any]:
    """Top-level SITS generation pipeline.

    Args:
        source_root: Root directory of C source code
        output_path: Path for output XLSM file
        template_path: Optional SITS template XLSM
        project_config: Optional config dict (project_id, version, asil_level, doc_id)
        ai_config: Optional AI config dict (reserved, not used yet)
        max_subcases: Maximum sub-cases per TC (default _DEFAULT_SUBCASES = 14)
            — 중복 기재돼 있었고 "default 5"·"default 7" 둘 다 실제 값과 달랐다.
        on_progress: Optional callback(pct: int, message: str)
        srs_docx_path: Optional SRS DOCX for requirement ID enrichment
        sds_docx_path: Optional SDS DOCX for component context
        uds_path: Optional UDS DOCX/XLSM for function descriptions
        hsis_path: Optional HSIS XLSX for hardware signal context
        max_flows: 통합 흐름 상한(default _DEFAULT_MAX_FLOWS = 120). 걸리면 안전등급
            높은 흐름부터 남기고, 잘린 내역이 로그 + quality_report
            ["integration_flow_coverage"] 에 남는다. 실측 프로젝트에서 145개 중
            25개가 이 값에 걸린다 — 규격에 없는 흐름이 그만큼 생긴다는 뜻이다.
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
    # ⚠ SITS 는 `sds_docx_path` 를 받고도 **Related ID 보강에는 쓰지 않았다** — 흐름
    #   수집이 저장소 `docs/` 글롭(프로젝트 무관, 현재 HDPDM01)만 봤다. SUTS 가 정확히
    #   같은 결함을 이미 고쳐 뒀고(`suts._resolve_sds_map` docstring 참조) 그 헬퍼를
    #   **재사용**한다 — 복제하면 한쪽만 고쳐지는 이 저장소의 반복 실패 모드가 된다.
    _project_sds_map: Optional[Dict[str, Dict[str, str]]] = None
    if sds_docx_path:
        _progress(7, "SDS 설계 컨텍스트 로드 중")
        try:
            from generators.suts import _resolve_sds_map
            _project_sds_map = _resolve_sds_map(sds_docx_path)
        except Exception as e:  # noqa: BLE001 - 확보 실패는 폴백 사유로 보고만 한다
            _logger.warning("SITS: 프로젝트 SDS 맵 확보 실패(%s) — 저장소 docs/ 폴백으로 "
                            "넘어간다(프로젝트 무관): %s", type(e).__name__, e)
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
    # 콤마 구분 복수 경로 지원: 첫 번째 경로로 검증
    _first_root = source_root.split(",")[0].strip() if source_root else ""
    source_root_path = Path(_first_root).resolve() if _first_root else None
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
            report_data = _get_source_sections_cached(source_root)  # 콤마 구분 그대로 전달
        except Exception:
            from report_generator import generate_uds_source_sections
            report_data = generate_uds_source_sections(source_root)  # 콤마 구분 그대로 전달
        function_details = report_data.get("function_details", {})
        total_source_functions = len(function_details)
        if not function_details:
            raise ValueError("No function_details in source parse result")
    except Exception as e:
        _logger.warning("SITS: full source parse failed, trying lightweight: %s", e)
        try:
            from generators.suts import _lightweight_parse
            function_details = _lightweight_parse(_first_root)
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
    flow_stats: Dict[str, Any] = {}
    flows = collect_integration_flows(
        function_details, max_flows=max_flows, stats_out=flow_stats,
        sds_map=_project_sds_map)

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

    # ⚠ "수집 완료" 는 캡에 잘렸을 때 완결을 주장하는 거짓말이 된다. 잘렸으면 그렇게 쓴다.
    _dropped_flows = int(flow_stats.get("flows_dropped") or 0)
    if _dropped_flows:
        _progress(
            50,
            f"{len(flows)}개 통합 흐름 수집 — 전체 {flow_stats.get('total_flows_found')}개 중 "
            f"{_dropped_flows}개는 max_flows 캡으로 제외(규격에 미포함)",
        )
    else:
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
    quality_report = generate_sits_quality_report(
        itcs, total_source_functions, flow_stats=flow_stats)

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
    # 파일에서 되읽은 수가 실제로 만든 수와 같은지 대조한다. 이게 없으면 라이터가
    # 흘려도 `valid: True` 가 나오고, 호출자에게 가는 test_case_count 는 파일이 아니라
    # 생성기가 세어준 값이라 아무도 눈치채지 못한다.
    validation = apply_write_back_check(validation, {
        "tc_count": len(itcs),
        "sub_case_count": sum(len(t.get("sub_cases") or []) for t in itcs),
    })
    if not validation.get("valid"):
        _logger.warning("SITS validation issues: %s", validation.get("issues"))

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

    # Quality DB recording (non-fatal)
    try:
        from workflow.quality.recorder import record_run
        record_run(
            "sits", quality_report,
            project_root=str(source_root or ""),
            elapsed_sec=elapsed,
            output_path=actual_output,
            ai_model=str((ai_config or {}).get("model", "")),
        )
    except Exception:
        # non-fatal 은 유지하되 침묵은 금지 (sts.py 의 동일 블록이 NameError 를
        # 몇 년간 삼켜 품질 기록이 통째로 유실된 전례).
        _logger.exception("SITS quality record skipped (non-fatal)")

    return {
        "output_path": actual_output,
        "quality_report": quality_report,
        "test_case_count": len(itcs),
        "total_sub_cases": sum(len(t["sub_cases"]) for t in itcs),
        "elapsed_seconds": elapsed,
        "validation": validation,
        "validation_report_path": validation_report_path,
    }
