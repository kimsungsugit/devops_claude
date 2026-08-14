"""SITS (Software Integration Test Specification) auto-generation engine.

Generates XLSM output matching the reference SITS structure:
  - TC 행(SwITC_xx) + 서브케이스 행
  - Columns: TC ID | Description | Call chain | Safety | Test Method | Gen Method |
             Input Param 1-82 | Expected Param 1-113 | Related ID
  - Sheets: Cover, History, 1.Introduction, 2.Test Environment,
            3-1.SW Integration Strategy, `_SPEC_SHEET_NAME`

⚠ 시트 이름은 **상수 `_SPEC_SHEET_NAME` 하나**가 출처다. 라이터와 검증기가 각자
문자열을 들고 있으면 한쪽만 고쳐진다 — 실제로 그랬다(라이터는 `3.…` 로 옮겼는데
`validate_sits_xlsm` 은 `4.…` 를 계속 찾아 **자기 산출물을 한 번도 못 읽었다**:
TC 0 · sub-case 0 으로 보고하면서 "미검증" 처리, 2026-08-14 게이트 실측).
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
# ⚠ **납품 정본**(KJPDS02_PV_SwITS v1.02, 205열) 기준이다. 표준 템플릿 v0.10 이
#   아니다 — 템플릿은 Param 10개 고정이라 실제 파라미터(입력 82 / 기대 113)를 못 담는다.
#
# 정본 실측(2026-08-11):
#   시트    : `3.SW Integration Test Spec`  (예전엔 시트 `4.…` 를 따로 만들어 붙였다)
#   r3 밴드 : B3:G3 'Test Case' · I3:CL3 'Input' · CM3:GU3 'Expected Result' · GV3 'Related ID'
#   r4 헤더 : B TC ID · C4:D4 'Description' · E Safety Related · F Test Method
#             · G Test Case Generation Method · H (서브케이스 번호) · I~ Param n · GV 'SwDS'
#   r5~     : TC 행(변수명) 1개 + 서브케이스 행 N개. B/E/F/G/GV 는 **블록 전체 병합**
#             (SUTS 와 다르다 — SUTS 는 Method 가 시퀀스 그룹 단위다)
_BAND_ROW = 3
_HEADER_ROW = 4
_DATA_START_ROW = 5

# 시험 규격 시트 이름 — 라이터·검증기의 **단일 출처**(위 모듈 docstring 참조).
_SPEC_SHEET_NAME = "3.SW Integration Test Spec"

_TCID_COL = 2          # B  — TC ID (SwITC_xx)
_DESC_COL = 3          # C  — 서브케이스 번호
_CHAIN_COL = 4         # D  — call chain (정본도 여기에 'Interface : main -> …' 를 쓴다)
_SAFETY_COL = 5        # E  — Safety Related (O/X)
_METHOD_COL = 6        # F  — Test Method
_GEN_COL = 7           # G  — Test Case Generation Method
_SEQ_COL = 8           # H  — 서브케이스 번호(반복)
_INPUT_COL_START = 9   # I  — Input Param 1
_INPUT_COL_END = 90    # CL — Input Param 82
_EXP_COL_START = 91    # CM — Expected Param 1
_EXP_COL_END = 203     # GU — Expected Param 113
_RELATED_COL = 204     # GV — Related ID (SwDS)

# ── 값 어휘 — SwITS 정본 실측 ────────────────────────────────────────────────
# ⚠ 결합자가 SwUTS 와 다르다. SwUTS 는 슬래시(`AOR/ABV`), SwITS 는 쉼표(`AOR, AEC`).
#   실측: Method `REQ, IFT` 49 · `FI` 5 / Gen `AOR, AEC` 49 · `AOR/ABV` 5.
_SITS_METHOD_DEFAULT = "REQ, IFT"   # 통합시험 기본 — 요구 기반 + 인터페이스 시험
_SITS_METHOD_FAULT = "FI"           # 고장 주입
_SITS_GEN_DEFAULT = "AOR, AEC"
_SITS_GEN_BOUNDARY = "AOR/ABV"


def _safety_mark(asil: Any) -> str:
    """`Safety Related` 칸 — `O`(안전 관련) / `X`(비안전) / 빈칸(근거 없음).

    ⚠ 근거 부재를 `X` 로 단정하지 않는다(under-classification). SUTS·STS 와 같은 규약.
    """
    val = str(asil or "").strip().upper()
    if val in ("A", "B", "C", "D") or val.startswith("ASIL"):
        return "O"
    if val == "QM":
        return "X"
    return ""


def _sits_test_method(itc: Dict[str, Any]) -> str:
    """통합 TC 의 Test Method. 오류 전파 서브케이스를 가지면 고장 주입으로 본다."""
    for sc in itc.get("sub_cases") or []:
        if "ERR" in str(sc.get("strategy") or sc.get("case_label") or "").upper():
            return _SITS_METHOD_FAULT
    return _SITS_METHOD_DEFAULT


def _sits_gen_method(gen: Any) -> str:
    """생성기 라벨 → 정본 어휘. 경계값 계열이면 `AOR/ABV`, 그 외 `AOR, AEC`."""
    g = str(gen or "").strip().upper()
    return _SITS_GEN_BOUNDARY if ("ABV" in g or "BV" in g) else _SITS_GEN_DEFAULT

_MAX_INPUT_PARAMS = _INPUT_COL_END - _INPUT_COL_START + 1   # 67
_MAX_EXP_PARAMS = _EXP_COL_END - _EXP_COL_START + 1        # 70

# Row 6 상세 헤더(열 번호 → 라벨). `generate_sits_xlsm`이 시트에 쓰는 값이자, 영향도 탭의
# 문서 초안이 Excel 붙여넣기 TSV 열 순서를 얻는 **단일 출처**다(복제 금지 — suts와 동일 원칙).
_DETAIL_HEADERS = {
    _TCID_COL: "TC ID",
    _DESC_COL: "Description",
    _CHAIN_COL: "Call Chain",
    _SAFETY_COL: "Safety Related",
    _METHOD_COL: "Test Method",
    _GEN_COL: "Test Case Generation Method",
    _RELATED_COL: "SwDS",
}
# ⚠ `Precondition` 열은 정본에 **없다**(그건 SwTS 정본의 열이다). 예전 판은 F열에
#   Precondition 을 써서 정본의 `Test Method` 자리를 차지하고 있었다.
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

# SwUDS 함수→SwCom 맵 캐시. (경로, mtime_ns, size) → 맵. 53MB docx 를 매번 훑을 수 없다.
_UDS_SWCOM_CACHE: Dict[str, Tuple[Tuple[int, int], Dict[str, List[str]]]] = {}


def load_uds_swcom_map(uds_path: Optional[str]) -> Dict[str, List[str]]:
    """SwUDS 가 함수마다 적어 둔 `Related ID` 에서 `{함수명(소문자): [SwCom_NN]}`.

    ## 왜 이게 Related 칸의 소스인가

    정본 실측(KJPDS02_PV_SwITS v1.02) — Related 칸의 어휘는 **설계/시험 요소 ID** 다:
    `SwCom` 170회(33종) · `SwFn` 69 · `SwSTR` 62 · `SwST` 38 · `SwTK` 8.
    요구 ID(`SwTR_`/`SwTSR_`/`SwNTR_`/`SwEI_`)는 **0 건**이다.

    그리고 이 로더가 SwUDS 에서 뽑은 SwCom 33종은 **정본의 33종과 완전히 같다**
    (교집합 33 · 차집합 양쪽 0 · 함수 매핑 1,025건, 2026-08-14 실측). 즉 정본은
    바로 이 표를 근거로 Related 칸을 채운다.

    ⚠ 대비 — SDS 파티션 맵은 이 칸의 소스가 **아니다**. 값 스키마 실측은
    `{asil, canonical, component_description, description, kind, related}` 이고
    함수 항목(588개)의 `related` 에 든 것은 전부 요구 ID다(설계 ID 토큰 0건).

    실패는 빈 맵이다 — 그 경우 호출부는 합성 ID 로 내려가되 **합성임을 표시**해야 한다.
    """
    raw = str(uds_path or "").strip()
    if not raw:
        return {}
    p = Path(raw)
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError as exc:
        _logger.warning("SITS: SwUDS 접근 실패 — SwCom 보강 생략: %s (%s)", raw, exc)
        return {}
    key = str(p.resolve()).lower()
    cached = _UDS_SWCOM_CACHE.get(key)
    if cached and cached[0] == sig:
        return cached[1]
    try:
        from backend.services.iso26262_doc_asil_extractor import (
            extract_function_swcom_from_kv_tables,
        )
        m = extract_function_swcom_from_kv_tables(p.read_bytes()) or {}
    except Exception as exc:  # noqa: BLE001 - 보강 실패는 보고하고 빈 맵으로 계속한다
        _logger.warning("SITS: SwUDS SwCom 추출 실패(%s) — 합성 ID 로 내려간다: %s",
                        type(exc).__name__, exc)
        return {}
    _UDS_SWCOM_CACHE[key] = (sig, m)
    _logger.info("SITS: SwUDS 함수→SwCom 매핑 %d건 로드 (%s)", len(m), p.name)
    return m


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
    """`[IN] u8g_Speed` → `u8g_Speed`. 정본 표기 규칙은 SUTS 와 **같은 출처**를 쓴다.

    ## 예전 판은 두 줄로 정반대 일을 했다

        s = re.sub(r"\\[.*?\\]", "", raw)   # `[IN]` 태그와 함께 **배열 첨자까지** 지웠다
        s = re.sub(r"\\s+", "_", s)         # 타입을 버리는 대신 **이름에 이어붙였다**

    그래서 `const UINT8 * data` 가 `const_UINT8_*_data` 로, `return U8` 이
    `return_UINT8` 로, `p->m` 이 `p->m` 그대로 산출물에 실렸다. 정본(VectorCAST)은
    각각 `data` · `return` · `p[0].m` 이라고 적는다.

    실측(2026-08-14, KJPDS02_PV): 정본 기대 656칸 중 **일치 0** · 입력 496 중 26(5.2%).
    미달의 최대 축이 배열이나 수집 범위가 아니라 **이름 표기 자체**였다.

    ## 복제하지 않는다

    SUTS 가 다섯 라운드에 걸쳐 정본과 맞춰 놓은 규칙(`return` 슬롯 · 포인터 `[0].` ·
    타입 한정자 제거 · 주석 제거)을 그대로 **호출**한다. 여기에 같은 로직을 다시 쓰면
    한쪽만 고쳐지는 이 저장소의 반복 실패 모드가 된다(`_resolve_sds_map` 을 같은 이유로
    이미 재사용하고 있다).

    ⚠ 이름을 뽑지 못하면 **빈 문자열**이다(예전엔 `raw[:40]` 으로 원문 조각을 흘렸다).
       호출부는 빈 값을 걸러야 한다.
    """
    from generators.suts import _extract_var_names
    names = _extract_var_names([str(raw or "")])
    return names[0] if names else ""


def _clean_global_var_name(raw: str) -> str:
    """전역 엔트리용 — `[INDIRECT] u8s_Flag` → `u8s_Flag`.

    ⚠ 파라미터용(`_clean_var_name`)과 **다른 함수**여야 한다. 전역의 방향 태그는
    `[IN]`/`[OUT]`/`[INOUT]` 말고도 `[INDIRECT]`·`[INDIRECT2]` 로 온다. 파라미터
    정제기는 그 세 개만 벗기므로 `[INDIRECT] …` 는 남은 대괄호 때문에 형태 검사에서
    **통째로 버려진다**.

    실측(2026-08-14): 두 경로를 한 함수로 합쳤더니 정본과 맞던 입력 **9칸이 사라졌다**
    — `u8s_E2EInitFlag_SBCM0`·`u8s_PrevCounter_SBCM0`·`g_DoorState`·
    `u32s_SecuritySeed` 처럼 전부 전역이었다. SUTS 도 같은 이유로 두 함수를 나눠 두고
    있고(`_clean_global_name` 은 태그 목록을 `_DIR_TAG_PAT` 단일 출처로 본다),
    그 주석은 태그 하나를 빼먹어 같은 실패를 두 번 겪었다고 적어 두었다.
    """
    from generators.suts import _clean_global_name, _vc_pointer_notation
    return _vc_pointer_notation(_clean_global_name(str(raw or "")))


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


def _reach_cross_module(
    entry: str,
    calls_map: Dict[str, List[str]],
    module_of: Dict[str, str],
    max_hop: int,
) -> List[str]:
    """`entry` 에서 `max_hop` 홉 이내에 닿는 **다른 모듈** 함수들(폭 우선 방문 순).

    통합 시험의 대상은 "모듈 경계를 넘는 실행 경로"다. 그런데 계층 진입점
    (`main` · `*_Main` · ISR · 프로토콜 파서)은 대개 **같은 모듈의 내부 함수만 직접
    호출**하고, 실제 경계 횡단은 두세 홉 아래에서 일어난다. 직접 callee 만 보면 이런
    진입점이 통째로 탈락한다.

    실측(2026-08-14, KJPDS02_PV): 정본이 시험하는 통합지점 15개가 전부 이 경로로
    빠져 있었다 — `main`(직접 호출 2개가 둘 다 같은 모듈) · `s_SysMain_Init` ·
    `s_System_MainLoop` · `g_DrvIn_Main` · `g_DrvOut_Main` · `g_UDS_RDBI_Paser` ·
    `g_UDS_WDBI_Paser` · `g_UDS_SessionCtrl` · `SCI0_ISR` · `LinRawToTp` 등.
    """
    my = (module_of.get(entry) or "").lower()
    if not my:
        return []
    found: List[str] = []
    seen = {entry}
    frontier = [entry]
    for _ in range(max(1, max_hop)):
        nxt: List[str] = []
        for fn in frontier:
            for callee in calls_map.get(fn, []):
                if callee in seen:
                    continue
                seen.add(callee)
                if (module_of.get(callee) or "").lower() != my:
                    found.append(callee)
                else:
                    # 같은 모듈이면 더 내려가 본다 — 경계는 그 아래에 있다.
                    nxt.append(callee)
        frontier = nxt
        if not frontier:
            break
    return found


def _build_call_chain_nodes(
    entry: str,
    calls_map: Dict[str, List[str]],
    max_nodes: int,
) -> Tuple[List[str], int]:
    """호출 트리를 깊이 우선으로 편 방문 순서와, **상한에 막혀 못 넣은 함수 수**.

    정본 실측(KJPDS02_PV_SwITS v1.02): 체인은
    `Interface : main -> s_System_InitSequence -> s_SysMain_Init -> …` 처럼 **경로
    전체**이고 길이 분포는 1~5홉 22 · 6~20홉 12 · 21~50홉 8 · 50홉 초과 5 (최대 92),
    같은 함수가 두 번 나오는 TC 는 **0/54** 다(= visited 기반 전개).
    우리는 `entry + 직접 cross callee 4개` = 최대 5홉만 적고 있었다.

    ⚠ 상한을 넘으면 **자르되 몇 개를 못 실었는지 돌려준다**. 조용히 자르면 읽는 쪽이
    "이 경로가 전부" 로 읽는다(이 저장소가 반복해서 물린 절단-침묵 패턴).
    """
    seen = {entry}
    order = [entry]
    dropped: set = set()
    stack: List[Any] = [iter(calls_map.get(entry, []))]
    while stack:
        try:
            callee = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if callee in seen:
            continue
        if len(order) >= max_nodes:
            # 상한 초과분은 **고유 함수 단위**로 센다(같은 함수를 여러 번 만나도 1).
            dropped.add(callee)
            continue
        seen.add(callee)
        order.append(callee)
        stack.append(iter(calls_map.get(callee, [])))
    return order, len(dropped)


# ---------------------------------------------------------------------------
# Core: integration flow collection
# ---------------------------------------------------------------------------

# 통합 흐름 상한. 폭주 방지용 안전밸브이지 "이만큼만 시험하면 된다"는 뜻이 아니다.
#
# ⚠ 이 값은 전이 판정(`_reach_cross_module`) 이전에 정해졌다. 실측(2026-08-14,
#   KJPDS02_PV 1,157함수): 후보가 239 → **367** 로 늘었고 그중 **306개가 SwUDS 등재**다.
#   즉 기본값 120 이면 설계가 인정한 통합 지점의 절반 이상이 규격에서 빠진다.
#   값을 여기서 올리지 않는 이유는 프로젝트마다 규모가 다르기 때문이다 — 대신 잘린
#   내역을 **보이게** 만들어 두었다: 경고 2줄(총량 / 그중 등재분) + 품질 리포트
#   `integration_flow_coverage.dropped_in_design_doc_count`. 그 수치가 0 이 아니면
#   호출자가 `max_flows` 를 올릴 근거가 된다.
_DEFAULT_MAX_FLOWS = 120

# 직접 callee 가 전부 같은 모듈일 때 **몇 홉까지 내려가** 경계를 찾을지.
# (`_reach_cross_module` — 계층 진입점은 자기 모듈 안쪽만 직접 호출한다)
_CROSS_REACH_HOPS = 3
# 호출 체인 한 줄에 담을 함수 수 상한. 정본 실측 최대는 92 홉이다.
_MAX_CHAIN_NODES = 100

# `collect_integration_flows` 가 `stats_out` 에 싣는 **흐름 축** 키.
# ⚠ 생산자와 품질 리포트가 이 목록 **하나**를 본다. 예전엔 리포트가 자기 화이트리스트를
#   따로 들고 있어 생산자에 키를 추가해도 조용히 버려졌다 — 같은 결함을 두 번 겪었다.
#   여기에 없는 흐름 키는 리포트에 도달하지 않으므로, 키를 늘리면 **여기부터** 고칠 것.
#   (가드: `test_generators_sits.py::TestFlowStatsReachTheReport`)
_FLOW_COV_KEYS: Tuple[str, ...] = (
    "total_flows_found", "flows_emitted", "flows_dropped", "flow_emit_pct", "max_flows",
    "dropped_safety_related_count", "dropped_asil_distribution", "dropped_entry_fns",
    "dropped_in_design_doc_count",
    "transitive_entries", "transitive_entries_emitted", "cross_reach_hops",
    "chain_truncated_flows", "chain_max_nodes",
)

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
        # (등급, **설계 문서 등재 여부**, 알파벳 순번).
        #
        # ⚠ 가운데 항이 없으면 이 프로젝트에서는 사실상 **알파벳순 = 임의**다(후보가
        #   거의 전부 QM 이다). 실측(2026-08-14, KJPDS02_PV): 후보 367 · 캡 200 에서
        #   정본이 시험하는 통합지점 34개 중 **30개만** 살아남았고, 밀려난 것 중에는
        #   직전 라운드까지 잘 나오던 `s_Ap_ExecuteControlFunctions`·
        #   `s_SystemHashCalculate` 가 있었다 — 후보가 늘면 캡이 **기존 정답을 밀어낸다**.
        #
        #   SwUDS 등재 여부를 키에 넣으면 같은 캡에서 **34/34** 가 생존한다. 근거:
        #   정본 통합지점은 34개 전부가 SwUDS 에 등재돼 있고(100%), 후보 전체로는
        #   83.4%(306/367)라 미등재 61개가 먼저 밀린다. 필터로 쓰면 약하지만
        #   **정렬 키로는 정확**하다. (호출 트리 크기·이름 패턴은 정본 보존율이
        #   각각 35%·56% 로 오히려 나빠 기각했다.)
        ranked = sorted(indexed, key=lambda t: (
            _asil_rank(t[1].get("asil")),
            0 if t[1].get("in_design_doc") else 1,
            t[0],
        ))
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
            # 잘린 것 중 **설계 문서에 등재된** 함수 수. 0 이 아니면 캡이 설계가
            # 인정한 단위를 먹고 있다는 뜻이므로 캡 값을 다시 볼 신호다.
            "dropped_in_design_doc_count": sum(1 for c in dropped if c.get("in_design_doc")),
        })

    if dropped:
        _logger.warning(
            "SITS: 통합 흐름 %d개 중 %d개만 생성한다 — max_flows=%s 캡으로 %d개 제외"
            "(안전관련 ASIL A~D %d개 포함). 제외된 흐름은 시험 규격에 **존재하지 않는다**. "
            "예: %s",
            total, len(kept), max_flows, len(dropped), safety_dropped,
            ", ".join(str(c.get("fn_name") or "") for c in dropped[:5]),
        )
    _doc_dropped = [c for c in dropped if c.get("in_design_doc")]
    if _doc_dropped:
        # 등재분까지 먹었다는 건 캡이 **설계가 인정한 단위**를 자르고 있다는 뜻이다.
        # 실측(2026-08-14, KJPDS02_PV): 후보 367 중 등재 306, 캡 200 → 등재분 106개가
        # 잘렸고 그 안에 정본 통합지점 3개(`s_System_MainLoop`·`s_SystemHashCalculate`·
        # `s_SysEepromCtrl_WriteData_Direct`)가 있었다. 캡 값을 다시 볼 신호다.
        _logger.warning(
            "SITS: 그중 %d개는 **SwUDS 에 등재된** 통합 지점이다 — 캡(%s)이 설계가 인정한 "
            "단위를 자르고 있다. 예: %s",
            len(_doc_dropped), max_flows,
            ", ".join(str(c.get("fn_name") or "") for c in _doc_dropped[:5]),
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
    uds_swcom_map: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Identify cross-module integration flows from function call graph.

    통합 흐름 = **모듈 경계를 넘는 실행 경로의 진입점**이다. 경계를 직접 넘든
    (`cross_via="direct"`), 같은 모듈 안쪽을 몇 홉 지나 넘든(`"transitive"`) 자격은
    같다 — 계층 진입점(`main`·`*_Main`·ISR·프로토콜 파서)은 후자의 모양이고, 직접
    callee 만 보던 판정에서 **정본 통합지점 15개가 통째로 빠졌다**(`_reach_cross_module`).

    Returns list of flow dicts:
      { flow_id, entry_fn, call_chain, cross_via, cross_calls, chain_dropped,
        functions, module_name, swcom_id, input_vars, expected_vars, asil,
        related_ids, synthetic_related_ids }

    `call_chain` 은 정본과 같이 **경로 전체**다(`_build_call_chain_nodes`).
    `chain_dropped` 가 0 이 아니면 그 경로는 상한에 걸려 잘린 것이다.

    Args:
        sds_map: Related ID 보강용 SDS 파티션 맵. None 이면 저장소 `docs/` 글롭
            (`_load_default_sds_map`)으로 폴백하는데 이는 **프로젝트 무관**이다
            — `sts.py`/`suts.py` 는 이미 같은 파라미터를 갖고 있었고 여기만 없어서
            **호출자가 대상 프로젝트의 SDS 를 줄 방법 자체가 없었다.**
        uds_swcom_map: `{함수명(소문자): [SwCom_NN]}` — Related 칸 SwCom 의 **유일한
            문서 근거**(`load_uds_swcom_map`). 주지 않으면 순번 합성 ID 로 내려간다.

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
    _sds_swcom_hits = 0     # 실제로 SwCom 을 얻은 수 — 이 맵으로는 **구조적으로 0**(위 참조)
    # ── SwUDS 축 — Related 칸의 실제 소스(`load_uds_swcom_map` docstring 참조) ──
    _uds_swcom_lookups = 0  # 조회 시도한 함수 수
    _uds_swcom_hits = 0     # SwUDS 에서 SwCom 을 실제로 얻은 함수 수
    _uds_swcom_ids = 0      # 그렇게 얻은 SwCom ID 총 개수(함수당 다중 가능)
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

    # 전이 판정·체인 전개용 호출 그래프. **프로젝트 함수끼리의 호출만** 남긴다
    # (memset/printf 같은 외부 심볼은 파싱 그래프에 없고 통합 경로도 아니다).
    _module_of: Dict[str, str] = {n: _get_module_name(i) for n, i in name_to_info.items() if n}
    _calls_map: Dict[str, List[str]] = {
        n: [c for c in (i.get("calls_list") or []) if c in name_to_info]
        for n, i in name_to_info.items() if n
    }
    _transitive_entries = 0       # 직접 경계 없이 전이로만 자격을 얻은 진입점 수
    _chain_truncated_total = 0    # 체인이 상한에 걸려 잘린 흐름 수(침묵 금지)

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

        # 직접 callee 가 전부 같은 모듈이어도, **몇 홉 아래에서** 경계를 넘으면 그건
        # 통합 지점이다 — 계층 진입점(`main`·`*_Main`·ISR·파서)의 전형적인 모양이다.
        # 이 폴백이 없을 때 정본 통합지점 15개가 통째로 빠졌다(`_reach_cross_module`).
        _cross_via = "direct"
        if not cross_calls:
            cross_calls = _reach_cross_module(
                fn_name, _calls_map, _module_of, _CROSS_REACH_HOPS)
            if not cross_calls:
                continue
            _cross_via = "transitive"
            _transitive_entries += 1

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
            # 경계를 **직접** 넘는지, 몇 홉 아래에서 넘는지. 같은 `cross_calls` 라도
            # 근거가 다르므로 산출물·리포트가 구별할 수 있어야 한다.
            "cross_via": _cross_via,
            # 설계 문서(SwUDS)에 등재된 함수인가 — 캡 선별 키
            # (`_select_flows_within_cap` 주석의 실측 근거 참조).
            "in_design_doc": fn_name.lower() in (uds_swcom_map or {}),
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

        # ── Call chain — 정본은 **경로 전체**를 적는다 ────────────────────────
        # 정본 실측(KJPDS02_PV_SwITS v1.02): `Interface : main -> s_System_InitSequence
        # -> …` 로 최대 92 홉, 같은 함수 재등장 0/54(= visited 전개). 우리는
        # `entry + 직접 cross callee 4개` = 최대 5 홉만 적어, 통합 경로가 아니라
        # **첫 갈림길 몇 개**만 보여 주고 있었다.
        _chain_nodes, _chain_dropped = _build_call_chain_nodes(
            fn_name, _calls_map, _MAX_CHAIN_NODES)
        call_chain = " -> ".join(_chain_nodes)
        if _chain_dropped:
            _chain_truncated_total += 1

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
            # ⚠ 빈 이름 가드. 예전 `_clean_var_name` 은 무엇을 받든 문자열을 냈기에
            #   (`raw[:40]` 폴백) 이 검사가 필요 없었다 — 이제는 못 뽑으면 빈 값이다.
            if vn and vn.lower() not in _fn_name_set and vn not in {p[0] for p in input_pairs}:
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
            gn = _clean_global_var_name(g)
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
        # ⚠ 정본은 이 칸에 **변수 이름만** 적는다 — `함수명() 변수` 같은 접두를 쓰지
        #   않는다(정본 기대 1,172칸 중 괄호 접두 0건). 접두를 붙이면 같은 변수가 부르는
        #   함수마다 다른 이름이 되어, 정본과 대조할 때 **한 칸도 맞지 않는다**.
        #   어느 함수가 그 전역을 건드리는지는 Interface 체인이 이미 말해 준다.
        for callee in cross_calls[:5]:
            callee_info = name_to_info.get(callee)
            if callee_info:
                for v in (callee_info.get("outputs") or [])[:5]:
                    vn = _clean_var_name(v)
                    if vn and vn.lower() not in _fn_name_set and vn not in {p[0] for p in exp_pairs}:
                        exp_pairs.append((vn, v))
                # Callee globals as observable side-effect outputs
                for g in ((callee_info.get("globals_global") or []) + (callee_info.get("globals_static") or []))[:4]:
                    gn = _clean_global_var_name(g)
                    if gn and gn.lower() not in _fn_name_set and gn not in {p[0] for p in exp_pairs}:
                        exp_pairs.append((gn, g))

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
                        # 위와 같은 이유로 `함수명()` 접두를 붙이지 않는다(정본은 0건).
                        if gname not in {p[0] for p in exp_pairs}:
                            exp_pairs.append((gname, gname))
                if len(exp_pairs) >= _MAX_EXP_PARAMS:
                    break

        expected_vars: List[str] = [p[0] for p in exp_pairs[:_MAX_EXP_PARAMS]]
        expected_raws: List[str] = [p[1] for p in exp_pairs[:_MAX_EXP_PARAMS]]

        # ASIL — Pass 1 에서 정규화한 값을 그대로 쓴다. 여기서 다시 계산하면
        # 선별 기준(등급)과 방출 값이 갈라질 수 있다.
        asil = _cand["asil"]

        # ── Related IDs ──────────────────────────────────────────────────────
        # 정본 실측: 이 칸의 어휘는 SwCom 170 · SwFn 69 · SwSTR 62 · SwST 38 · SwTK 8 —
        # **설계/시험 요소 ID** 다. 요구 ID(SwTR_ 계열)는 0 건이다.
        related_parts: List[str] = []
        # ① SwUDS 가 함수마다 적어 둔 SwCom — 정본이 쓰는 바로 그 표다
        #   (실측: 이 맵의 SwCom 33종 ↔ 정본 33종, 차집합 양쪽 0).
        _uds_swcom_lookups += 1
        _uds_hit = list((uds_swcom_map or {}).get(fn_name.lower()) or [])
        if _uds_hit:
            _uds_swcom_hits += 1
            _uds_swcom_ids += len(_uds_hit)
            related_parts.extend(_uds_hit)
        # ② 소스 주석/파서가 실어 준 ID
        for field in ("srs_req_ids", "related", "related_id"):
            val = info.get(field) or ""
            ids = _parse_req_ids(str(val))
            related_parts.extend(ids)
        # ③ from SDS map — 결과가 0 이어도 **왜 0 인지** 셀 수 있어야 한다(위 주석 참조).
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
        # ⚠ SwUDS 에서 **진짜** SwCom 을 얻었으면 합성값을 덧붙이지 않는다. 덧붙이면 한
        #   칸에 문서 유래 SwCom 과 다른 컴포넌트를 가리키는 순번 합성값이 나란히 실리고,
        #   셀만 보는 쪽은 둘을 구별할 방법이 없다(합성 표시는 `synthetic_related_ids`
        #   에만 있고 산출물 셀에는 없다). 그 상태로 정본과 대조하면 모양이 같아 '일치'
        #   로도 잡힌다 — 가장 나쁜 종류의 거짓 추적성이다.
        swcom_id = _cand["swcom_id"]   # Pass 1 에서 후보 전체 기준으로 부여됨
        synthetic_related: List[str] = []
        if not _uds_hit and swcom_id not in related_parts:
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
            gn = _clean_global_var_name(g)
            if gn and "[INDIRECT]" in tag and gn not in {p[0] for p in input_pairs}:
                if gn not in indirect_vars_list and len(indirect_vars_list) < 5:
                    indirect_vars_list.append(gn)
        # Also collect from callees
        for callee in cross_calls[:4]:
            callee_info = name_to_info.get(callee)
            if callee_info:
                for g in (callee_info.get("globals_global") or [])[:5]:
                    tag = str(g).upper()
                    gn = _clean_global_var_name(g)
                    if gn and "[INDIRECT]" in tag and gn not in indirect_vars_list:
                        if len(indirect_vars_list) < 5:
                            indirect_vars_list.append(gn)

        flows.append({
            "flow_id": fid,
            "entry_fn": fn_name,
            "call_chain": call_chain,
            # 경계를 직접 넘는지(`direct`) 몇 홉 아래에서 넘는지(`transitive`).
            "cross_via": _cand.get("cross_via", "direct"),
            "cross_calls": cross_calls,
            # 체인이 상한에 걸려 못 실은 함수 수. 0 이 아니면 이 경로는 **전부가 아니다**.
            "chain_dropped": _chain_dropped,
            "functions": _chain_nodes,
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

    # 보강 실적을 **반드시** 내보낸다. 0 을 침묵시키면 "보강이 동작한다" 로 읽힌다.
    if stats_out is not None:
        stats_out.update({
            "sds_source": _sds_source,
            "sds_map_entries": len(sds_map or {}),
            "sds_lookups": _sds_lookups,
            "sds_key_hits": _sds_key_hits,
            "sds_swcom_hits": _sds_swcom_hits,
            # SwUDS 축 — Related 칸의 실제 소스
            "uds_swcom_map_entries": len(uds_swcom_map or {}),
            "uds_swcom_lookups": _uds_swcom_lookups,
            "uds_swcom_hits": _uds_swcom_hits,
            "uds_swcom_ids": _uds_swcom_ids,
            # 경계 판정 축 — 직접 vs 전이. 전이분이 0 이면 계층 진입점이 다시 빠지고
            # 있다는 뜻이므로 이 값이 회귀 신호가 된다.
            "transitive_entries": _transitive_entries,
            "cross_reach_hops": _CROSS_REACH_HOPS,
            # 체인 절단 — 0 이 아니면 그 흐름의 경로는 **전부가 아니다**.
            "chain_truncated_flows": _chain_truncated_total,
            "chain_max_nodes": _MAX_CHAIN_NODES,
        })
    if _sds_lookups and not _sds_swcom_hits:
        # ⚠ 이 맵으로는 **구조적으로 0** 이다(값 스키마에 swcom/component 필드가 없고
        #   함수 항목의 `related` 는 요구 ID 뿐 — 실측). 그래서 문장을 "설정이 잘못됐다"
        #   가 아니라 사실대로 적고, SwUDS 축이 채웠는지를 같이 말한다.
        _logger.info(
            "SITS: SDS 맵에는 SwCom 축이 없다(조회 %d · 키매칭 %d · 맵 %d항목 · 출처=%s) "
            "— Related 의 SwCom 은 SwUDS 축에서 온다: %d/%d 함수 · ID %d개.",
            _sds_lookups, _sds_key_hits, len(sds_map or {}), _sds_source,
            _uds_swcom_hits, _uds_swcom_lookups, _uds_swcom_ids,
        )
    # ⚠ `None`(맵을 **주지 않은** 호출)과 `{}`(주려다 **비어서 온** 호출)는 다르다.
    #   전자는 SwCom 보강을 의도하지 않은 경로(영향도 dry-run 등)라 경고하면 노이즈가
    #   되고, 후자는 SwUDS 를 읽으려다 실패한 것이라 반드시 보여야 한다.
    #   `generate_sits` 는 실패해도 `{}` 를 넘기므로 진짜 실패는 항상 잡힌다.
    if uds_swcom_map is not None and _uds_swcom_lookups and not _uds_swcom_hits:
        _logger.warning(
            "SITS: SwUDS 기반 SwCom 보강이 %d회 조회에서 **0건** 산출했다(맵 %d항목). "
            "Related ID 는 순번 합성 SwCom 만 남는다 — 추적성 지표를 그대로 믿지 말 것.",
            _uds_swcom_lookups, len(uds_swcom_map),
        )
    if _chain_truncated_total:
        _logger.warning(
            "SITS: 호출 체인이 상한(%d)에 걸려 흐름 %d개에서 잘렸다 — 그 TC 의 "
            "Interface 칸은 **경로 전부가 아니다**.",
            _MAX_CHAIN_NODES, _chain_truncated_total,
        )
    # ⚠ `_transitive_entries` 는 **후보** 기준(Pass 1)이고 `flows` 는 캡 적용 후다.
    #   방출된 쪽을 따로 세지 않으면 캡에 잘린 전이 후보가 직접분으로 둔갑한다.
    _emitted_transitive = sum(1 for f in flows if f.get("cross_via") == "transitive")
    _logger.info(
        "SITS: collected %d integration flows (직접 경계 %d · 전이 경계 %d · %d홉까지 탐색"
        " · 후보 단계 전이 %d)",
        len(flows), len(flows) - _emitted_transitive, _emitted_transitive,
        _CROSS_REACH_HOPS, _transitive_entries,
    )
    if stats_out is not None:
        stats_out["transitive_entries_emitted"] = _emitted_transitive
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

    # ⚠ 경계 근거(직접/전이)를 함께 낸다 — 같은 "Cross-Module Calls" 라도 진입점이
    #   직접 넘은 것과 몇 홉 아래에서 넘은 것은 읽는 사람에게 다른 사실이다.
    for ci, h in enumerate(["SwCom ID", "Module", "Entry Function",
                            "경계", "Cross-Module Calls"], start=1):
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
        via = "직접" if f.get("cross_via", "direct") == "direct" else "전이"
        for ci, val in enumerate([f["swcom_id"], f["module_name"],
                                   f["entry_fn"], via, calls_str], start=1):
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

    # ⚠ 정본의 시트는 `3.SW Integration Test Spec` 이다. 예전엔 템플릿의 3번 시트를
    #   놔둔 채 `4.…` 를 **따로 붙여** 한 파일에 빈 정본 시트와 채워진 사본이 공존했다.
    sheet_name = _SPEC_SHEET_NAME
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
    _fill_and_merge(_BAND_ROW, _TCID_COL, _GEN_COL, "Test Case")
    _fill_and_merge(_BAND_ROW, _INPUT_COL_START, _INPUT_COL_END, "Input")
    _fill_and_merge(_BAND_ROW, _EXP_COL_START, _EXP_COL_END, "Expected Result")
    _fill_and_merge(_BAND_ROW, _RELATED_COL, _RELATED_COL, "Related ID")
    ws.row_dimensions[_BAND_ROW].height = 18

    # ── Row 6: detail headers ── 정의는 모듈 상수 `_DETAIL_HEADERS`(단일 출처) ──
    # 별칭이 아니라 사본 — 이후 누가 여기서 헤더를 덧쓰더라도 모듈 상수가 오염되지 않게.
    detail_headers: Dict[int, str] = dict(_DETAIL_HEADERS)
    for col_i in range(1, _RELATED_COL + 1):
        cell = ws.cell(row=_HEADER_ROW, column=col_i)
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
    ws.row_dimensions[_HEADER_ROW].height = 30

    # ── Column widths ────────────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 1.0
    ws.column_dimensions[get_column_letter(_TCID_COL)].width = 14
    ws.column_dimensions[get_column_letter(_DESC_COL)].width = 10
    ws.column_dimensions[get_column_letter(_CHAIN_COL)].width = 40
    ws.column_dimensions[get_column_letter(_SAFETY_COL)].width = 9
    ws.column_dimensions[get_column_letter(_METHOD_COL)].width = 12
    ws.column_dimensions[get_column_letter(_GEN_COL)].width = 14
    ws.column_dimensions[get_column_letter(_SEQ_COL)].width = 5
    for ci in range(_INPUT_COL_START, _INPUT_COL_END + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 9
    for ci in range(_EXP_COL_START, _EXP_COL_END + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 9
    ws.column_dimensions[get_column_letter(_RELATED_COL)].width = 35

    # ── Data rows ────────────────────────────────────────────────────────────
    current_row = _DATA_START_ROW
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
        # Safety Related / Test Method — 정본은 TC 행에 쓰고 블록 전체로 병합한다
        # (SUTS 와 다르다: SUTS 는 Method 가 시퀀스 그룹 단위다).
        ws.cell(row=current_row, column=_SAFETY_COL,
                value=_safety_mark(itc.get("asil"))).font = data_font
        ws.cell(row=current_row, column=_SAFETY_COL).alignment = center
        ws.cell(row=current_row, column=_SAFETY_COL).border = thin
        ws.cell(row=current_row, column=_METHOD_COL,
                value=_sits_test_method(itc)).font = data_font
        ws.cell(row=current_row, column=_METHOD_COL).alignment = center
        ws.cell(row=current_row, column=_METHOD_COL).border = thin
        ws.cell(row=current_row, column=_GEN_COL,
                value=_sits_gen_method(gen_method)).font = data_font
        ws.cell(row=current_row, column=_GEN_COL).alignment = center
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
        _tc_row = current_row
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

            # 서브케이스 번호는 정본에서 C(Description 앞칸)와 H 두 곳에 온다.
            ws.cell(row=current_row, column=_SEQ_COL, value=sc["case_num"]).font = data_font
            ws.cell(row=current_row, column=_SEQ_COL).alignment = center
            ws.cell(row=current_row, column=_SEQ_COL).border = thin

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

        # TC 메타 열은 블록 전체 병합 — 정본이 그렇다(B5:B40 · E5:E40 · F5:F40 · G5:G40 · GV5:GV40).
        _block_end = current_row - 1
        if _block_end > _tc_row:
            for mc in (_TCID_COL, _SAFETY_COL, _METHOD_COL, _GEN_COL, _RELATED_COL):
                try:
                    ws.merge_cells(start_row=_tc_row, start_column=mc,
                                   end_row=_block_end, end_column=mc)
                except Exception as exc:  # noqa: BLE001
                    _logger.debug("SITS TC merge skipped (col %d, %d:%d): %s",
                                  mc, _tc_row, _block_end, exc)

    # Freeze panes — 헤더 아래 첫 데이터 행에서 고정
    ws.freeze_panes = f"C{_DATA_START_ROW}"

    # Save
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    _logger.info("SITS XLSM saved: %s (rows=%d)", out_path.name, current_row - _DATA_START_ROW)
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
        # ⚠ 키 목록은 `_FLOW_COV_KEYS` **하나**가 출처다. 예전엔 여기에 이름을 손으로
        #   나열했는데, 생산자에 키를 추가해도 이 목록에 없으면 **조용히 버려졌다**.
        #   같은 결함을 두 번 겪었다(2026-07-31 `sds_*`, 2026-08-14 전이/체인 축) —
        #   두 번째에는 "전이 판정이 동작했는가" 를 리포트에서 확인할 수 없어,
        #   캡에 잘린 정본 지점 3개의 원인 규명이 한 라운드 늦어졌다.
        flow_cov = {k: fs[k] for k in _FLOW_COV_KEYS if k in fs}

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

    # SwUDS 축 — Related 칸의 **실제** SwCom 소스. 위 sds_enrich 가 0 인 것은 결함이
    # 아니라 그 맵의 성질이고(스키마에 SwCom 이 없다), 실적은 여기서 봐야 한다.
    uds_swcom_enrich: Dict[str, Any] = {}
    if fs.get("uds_swcom_lookups") is not None:
        _ulk = int(fs.get("uds_swcom_lookups") or 0)
        _uhit = int(fs.get("uds_swcom_hits") or 0)
        uds_swcom_enrich = {
            "map_entries": int(fs.get("uds_swcom_map_entries") or 0),
            "lookups": _ulk,
            "hits": _uhit,
            "ids": int(fs.get("uds_swcom_ids") or 0),
            "yield_pct": round(100.0 * _uhit / _ulk, 2) if _ulk else None,
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
        # SwUDS 축 — Related 칸의 SwCom 은 여기서 온다(정본과 같은 표).
        "uds_swcom_enrichment": uds_swcom_enrich,
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

    # ⚠ 시트 이름·데이터 시작행은 **라이터와 같은 상수**를 쓴다. 문자열/숫자를 여기에
    #   복제하면 라이터가 옮겨갈 때 리더만 뒤에 남는다 — 실제로 시트는 `4.…`(라이터는
    #   `3.…` 로 이동), 시작행은 7(라이터는 5)로 굳어 있었고, 그래서 이 검증기는
    #   **자기 산출물을 한 줄도 못 읽으면서** TC 0 · sub-case 0 을 보고했다.
    required_sheets = [_SPEC_SHEET_NAME]
    for s in required_sheets:
        if s not in wb.sheetnames:
            issues.append(f"Missing required sheet: {s}")

    tc_count = 0
    sub_count = 0

    if _SPEC_SHEET_NAME in wb.sheetnames:
        ws = wb[_SPEC_SHEET_NAME]
        for row in ws.iter_rows(min_row=_DATA_START_ROW, values_only=True):
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
    # Related ID 의 SwCom 축은 **SwUDS** 에서 온다(`load_uds_swcom_map` docstring — 정본과
    # 같은 표다). 못 얻으면 순번 합성 ID 로 내려가되 합성임이 산출물에 표시된다.
    _uds_swcom_map = load_uds_swcom_map(uds_path)
    flow_stats: Dict[str, Any] = {}
    flows = collect_integration_flows(
        function_details, max_flows=max_flows, stats_out=flow_stats,
        sds_map=_project_sds_map, uds_swcom_map=_uds_swcom_map)

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
