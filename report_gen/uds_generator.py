"""report_gen.uds_generator - Auto-split from report_generator.py"""
# Re-import common dependencies
import re

# ---------------------------------------------------------------------------
# Payload field name constants
# ---------------------------------------------------------------------------
# Two-level naming convention:
#
#   Function-level  (per-function dict, value = List[str] of variable names):
#     KEY_FN_GLOBALS  — global  variables *used* by this function
#     KEY_FN_STATICS  — static  variables *used* by this function
#
#   Module-level  (top-level payload, value = List[List[str]] 5-column table):
#     KEY_MOD_GLOBALS — global  variable *definitions* table for the whole module
#     KEY_MOD_STATICS — static  variable *definitions* table for the whole module
#
# Legacy alias: some older sidecar JSONs may still use the bare key "globals"
# which maps to KEY_FN_GLOBALS.  Readers must handle the fallback
# (see validation.py _extract_payload_function_details).
#
KEY_FN_GLOBALS = "globals_global"   # per-function: global var names list
KEY_FN_STATICS = "globals_static"   # per-function: static var names list
KEY_MOD_GLOBALS = "global_vars"     # module-level: global var definitions table
KEY_MOD_STATICS = "static_vars"     # module-level: static var definitions table
# Legacy key kept for backward compat when reading old sidecar JSON files
KEY_FN_GLOBALS_LEGACY = "globals"
# ---------------------------------------------------------------------------
import json
import logging
import os  # noqa: E402
from datetime import datetime
from html import escape
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Set, Tuple  # noqa: E402

from report.constants import (
    DEFAULT_TYPE_RANGES,
)
from report_gen.c_reset import (  # noqa: E402 (import 블록 전체가 상수 뒤에 온다)
    collect_reset_assignments,
    placed_global_names,
    resolve_reset,
)
from report_gen.c_return import returns_value  # noqa: E402 (import 블록 전체가 상수 뒤에 온다)
from report_gen.function_analyzer import (
    _collect_var_usage,
    _enhance_description_text,
    _enhance_function_description,
    _extract_condition_branch_calls,
    _extract_logic_flow,
    _extract_logic_terminal_paths,
    _extract_primary_condition,
    _extract_return_type,
    _fallback_function_description,
    _format_param_entry,
    _infer_precondition_from_body,
    _is_generic_description,
    _is_static_var,
    _normalize_bracket_expr,
    _normalize_dims,
    _normalize_symbol_name,
    _parse_signature_outputs,
    _parse_signature_params,
    _split_param,
)
from report_gen.requirements import (
    _collect_section_lines,
    _extract_function_blocks,
    _extract_requirements_from_comments,
    _extract_state_tokens,
    _extract_table_section,
    _load_component_map,
    _normalize_table_row,
    _split_doc_function_blocks,
    component_verify_of,
)
from report_gen.source_parser import (
    _SRC_READ_MAX_BYTES,
    _decl_array_dim,
    _extract_c_definitions,
    _extract_c_function_bodies,
    _extract_c_global_candidates,
    _extract_c_macro_defs,
    _extract_c_macros,
    _extract_c_prototypes,
    _extract_doxygen_asil_tags,
    _extract_fallback_call_names,
    _extract_file_header_asil,
    _extract_function_pointer_call_targets,
    _extract_local_static_candidates,
    _extract_macro_call_names,
    _read_source_text,
    _read_text_limited,
    _scan_source_comment_patterns,
    _strip_c_comments,
    extract_struct_member_arrays,
    extract_struct_member_types,
    is_const_type,
)
from report_gen.uds_text import (
    _ai_document_text,
    _ai_evidence_lines,
    _apply_uds_rules,
    _merge_logic_ai_items,
    _merge_section_text,
    _uds_lines_to_html,
    _uds_logic_html,
)
from report_gen.utils import (
    _extract_simple_call_names,
    _infer_type_from_decl,
    _infer_type_from_file,
    _normalize_swcom_label,
    _safe_dict,
    function_name_key,
)
from workflow.code_parser.c_parser import c_identifiers  # noqa: E402 (이 파일 import 블록 전체가 상수 뒤에 온다)

_logger = logging.getLogger("report_generator")

# function_body_snippets 항목 1건의 최대 길이. 소비자(workflow.uds_ai 2차 refinement)가
# 프롬프트에 400자만 싣는다 — 그보다 크게 저장하면 캐시만 커지고 쓰이지 않는다.
_BODY_SNIPPET_MAX = 400

# object-like 매크로가 **전역 변수의 멤버/원소를 가리키는** 경우만 매칭한다.
#   `#define PTT_PTT3  _PTT.Bits.PTT3`  ·  `#define RXBUF0  s_RxBuf[0]`
# 상수 매크로(`#define MAX 255`)나 식(`#define HALF (x/2)`)은 걸리지 않아야 한다 —
# 걸리면 전역이 아닌 이름이 globals_info_map 에 올라간다.
_MACRO_MEMBER_PATH_RE = re.compile(
    r"^([A-Za-z_]\w*)((?:\s*(?:\.|->)\s*[A-Za-z_]\w*|\s*\[[^\]]*\])+)$"
)


def generate_uds_logic_items(
    texts: List[str],
    mode: str,
    source_root: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    mode = str(mode or "").strip().lower()
    if mode not in {"call_tree", "state_table", "comment_pattern"}:
        return []
    if mode == "comment_pattern":
        return _scan_source_comment_patterns(source_root)
    items: List[Dict[str, Any]] = []
    for txt in texts:
        for block in _split_doc_function_blocks(txt):
            lines = block.get("lines") or []
            title = block.get("title") or block.get("id") or "Logic Diagram"
            desc = ""
            if mode == "call_tree":
                called = _collect_section_lines(lines, "Called Function")
                calling = _collect_section_lines(lines, "Calling Function")
                parts: List[str] = []
                if called:
                    parts.append("Called: " + ", ".join(called[:12]))
                if calling:
                    parts.append("Calling: " + ", ".join(calling[:12]))
                desc = " / ".join(parts) if parts else "N/A"
            elif mode == "state_table":
                states = _extract_state_tokens(lines)
                if states:
                    desc = "States: " + ", ".join(states[:20])
                else:
                    desc = "N/A"
            items.append({"title": title, "description": desc})
            if len(items) >= limit:
                return items
    return items


_BY_NAME_ASIL_RANK = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}


def _asil_rank(v: Any) -> int:
    a = re.sub(r"^ASIL[\s_-]*", "", str(v or "").strip().upper()).strip()
    return _BY_NAME_ASIL_RANK.get(a, -1)


def _put_by_name(
    by_name: Dict[str, Dict[str, Any]],
    name: str,
    detail: Dict[str, Any],
    collisions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """function_details_by_name 등록 + **동일 이름 다중 정의(파일 간 충돌) 기록**.

    C 프로젝트에는 같은 이름 함수가 여러 파일에 정의되는 경우가 있다(예: Generated_Code/EEPROM.c와
    Sources/Eeprom/EEPROM.c의 eeprom_setbyte, main 등). by_name은 last-wins라 한쪽 메타만 남아
      (a) `asil`이 더 낮은 사본으로 덮여 **안전 등급이 손실**되고(ISO 26262 — escalation·MC/DC 게이트),
      (b) `file`이 한쪽만 가리켜 영향분석의 파일 매칭이 다른 사본을 **누락**(under-report)했다.

    ⚠ 그렇다고 by_name에 **병합 사본(dict 복사)** 을 넣으면 안 된다 — by_name 값은 function_details의
    **동일 객체**여야 하고(docx_builder가 참조문서 값을 `target[key] = ...`로 in-place 병합하므로,
    복사본을 넣으면 그 갱신이 문서에 반영되지 않는다), 뒤이어 실행되는 콜그래프 보강 루프가
    `function_details_by_name[fn] = info`로 다시 덮어써 병합이 무효화되기도 한다.
    → by_name은 **동일성 유지(last-wins 그대로)**, 충돌 사실은 별도 맵(`collisions`)에 기록한다.
      소비자(영향분석)는 자신의 deepcopy에 이 정보를 얹어 쓴다.
    """
    key = function_name_key(name)
    if not key:
        return
    prev = by_name.get(key)
    if collisions is not None and prev is not None and prev is not detail:
        ent = collisions.setdefault(key, {"files": [], "asil": ""})
        for _d in (prev, detail):
            _f = str(_d.get("file") or "").strip()
            if _f and _f not in ent["files"]:
                ent["files"].append(_f)
            if _asil_rank(_d.get("asil")) > _asil_rank(ent.get("asil")):
                ent["asil"] = str(_d.get("asil") or "")
    by_name[key] = detail  # 동일성 보존(문서 생성의 in-place 갱신 경로 유지)


def _group_function_blocks_by_swcom(blocks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for block in blocks:
        swcom = str(block.get("swcom") or "").strip() or "SwCom_Unknown"
        groups.setdefault(swcom, []).append(block)
    return groups


def _format_function_block_lines(block: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    header = str(block.get("header") or "")
    if header:
        lines.append(header)
    if block.get("id"):
        lines.append(f"ID\t{block.get('id')}")
    if block.get("name"):
        lines.append(f"Name\t{block.get('name')}")
    if block.get("prototype"):
        lines.append(f"Prototype\t{block.get('prototype')}")
    if block.get("description"):
        lines.append(f"Description\t{block.get('description')}")
    if block.get("asil"):
        lines.append(f"ASIL\t{block.get('asil')}")
    if block.get("related"):
        lines.append(f"Related ID\t{block.get('related')}")
    if block.get("precondition"):
        lines.append(f"선행조건\t{block.get('precondition')}")
    if block.get("globals"):
        lines.append(f"사용 전역변수\t{block.get('globals')}")
    if block.get("called"):
        lines.append(f"Called Function\t{block.get('called')}")
    if block.get("calling"):
        lines.append(f"Calling Function\t{block.get('calling')}")
    inputs = block.get("inputs") or []
    if inputs:
        lines.append("[ Input Parameters ]")
        lines.extend(inputs)
    outputs = block.get("outputs") or []
    if outputs:
        lines.append("[ Output Parameters ]")
        lines.extend(outputs)
    if block.get("logic"):
        lines.append("[ Logic Diagram ]")
        lines.append("Logic Diagram: present")
    return lines


def parse_uds_preview_html(html: str) -> Dict[str, List[str]]:
    if not html:
        return {}
    sections = {"Overview": [], "Requirements": [], "Interfaces": [], "UDS Frames": [], "Notes": []}
    for name in sections.keys():
        m = re.search(rf"<h3>{re.escape(name)}</h3>(.*?)<h3>|<h3>{re.escape(name)}</h3>(.*)$", html, re.S)
        if not m:
            continue
        block = m.group(1) or m.group(2) or ""
        items = re.findall(r"<li>(.*?)</li>", block, flags=re.S)
        cleaned = [re.sub(r"<.*?>", "", i).strip() for i in items if i.strip()]
        sections[name] = cleaned
    return sections


def generate_uds_source_sections(
    source_root: str,
    component_map: Optional[Dict[str, Dict[str, str]]] = None,
    sds_partition_map: Optional[Dict[str, Dict[str, str]]] = None,
    preprocess: bool = True,
    max_files: Optional[int] = None,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:   # 값은 str·list·dict 혼합(function_details 등) — 과거 Dict[str, str]는 오기
    """`max_files`/`max_items` 는 **호출자 상한**. `None` 이면 `config` 기본값을 쓴다.

    ⚠ 숫자를 여기 복제하지 않는다 — 기본값의 단일 출처는 `config.UDS_MAX_SOURCE_FILES`/
      `UDS_MAX_FUNCTION_ITEMS`(환경변수로 덮임)이고, 준비 게이트의 공시도 거기서 읽는다
      (`docgen_requirements._uds_cap`). `generators/sts.py` 의 `max_tc_per_req` 와 같은 규약.
    """
    # 콤마/세미콜론 구분 복수 소스 루트 지원
    _raw_roots = [p.strip() for p in str(source_root).replace(";", ",").split(",") if p.strip()]

    # cloudium 모드면 worker IPC resolver로 소스 접근(read-only). local/standalone이면 None →
    # 기존 os.walk/Path 경로 그대로 사용(회귀 0). backend 미가용이면 조용히 None.
    _src_resolver = None
    try:
        from backend.services.file_resolver import get_resolver as _get_resolver
        _r0 = _get_resolver()
        if getattr(_r0, "mode", "local") != "local":
            _src_resolver = _r0
    except Exception:
        _src_resolver = None

    def _src_walk(walk_root):
        if _src_resolver is not None:
            for _sp in _src_resolver.list_dir(str(walk_root), pattern="*", recursive=True):
                yield Path(_sp)
        else:
            for _dp, _, _fns in os.walk(walk_root):
                for _n in _fns:
                    yield Path(_dp) / _n

    def _src_read(p) -> str:
        if _src_resolver is not None:
            try:
                return _src_resolver.read_bytes(str(p)).decode("utf-8", errors="ignore")
            except Exception:
                return ""
        try:
            return Path(p).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _src_relbase(p):
        # 모듈명 계산용. cloudium은 로컬 resolve 금지(원격경로 그대로), local은 기존 resolve.
        return Path(p) if _src_resolver is not None else Path(p).resolve()

    if _src_resolver is not None:
        _roots = [Path(p) for p in _raw_roots if _src_resolver.is_dir(p)]
    else:
        _roots = [Path(p).resolve() for p in _raw_roots if Path(p).resolve().exists()]
    if not _roots:
        return {}
    root = _roots[0]  # 기본 루트 (상대경로 계산 기준)
    allowed = {".c", ".h", ".cpp", ".hpp"}
    try:
        import config as _cfg
        _cfg_max_files = getattr(_cfg, "UDS_MAX_SOURCE_FILES", 1200)
        _cfg_max_items = getattr(_cfg, "UDS_MAX_FUNCTION_ITEMS", 120)
    except Exception:
        _cfg_max_files = 1200
        _cfg_max_items = 120
    # 호출자가 준 값이 있으면 그것, 없으면 config. `0`·음수는 "전부 자르라" 가 아니라
    # 미설정으로 본다 — 저장소가 이미 그 규약이고(`sharedInputs.js::saveDocGenCap`),
    # 여기서 다르게 읽으면 같은 값에 화면과 생성기가 반대말을 한다.
    max_files = int(max_files) if isinstance(max_files, int) and max_files > 0 else _cfg_max_files
    max_items = int(max_items) if isinstance(max_items, int) and max_items > 0 else _cfg_max_items
    files: List[Path] = []
    ext_counts: Dict[str, int] = {}
    top_dirs: Dict[str, int] = {}
    interfaces: List[str] = []
    internals: List[str] = []
    unknowns: List[str] = []
    macros: List[str] = []
    reqs: List[str] = []
    common_macros: List[str] = []
    type_defs: List[str] = []
    # 구조체/공용체 멤버의 배열 차원(접기 전 원문). 정본 SUTS 는 멤버 배열도
    # 원소 단위로 적는다 — `source_parser.extract_struct_member_arrays` 주석 참조.
    # 리셋/초기화 이름 함수 안의 전역 대입 — `Reset Value` 열의 유일한 소스 근거다.
    # ⚠ 실측: 이 대입을 안 보고 "정적 저장기간 → 0" 만 쓰면 정밀도가 96.5% → 93.7%
    #   로 내려가고, 실패가 하필 `u8g_ApiIn_LinRx_*` 외부 인터페이스 신호 34칸에 몰린다.
    _reset_assigns: Dict[str, List[Tuple[str, str]]] = {}
    # 배치 주소(`@0x…`)로 선언된 변수 — 리셋 값이 MCU 데이터시트에 있어 소스엔 없다.
    _placed_globals: Set[str] = set()
    struct_member_arrays_raw: Dict[str, Dict[str, str]] = {}
    # 타입 -> {멤버경로: {type, array, bits, desc}}. 배열 차원만 담는 위 맵과
    # **키는 같고 값이 다르다** — 소비처 계약(SUTS/SITS)이 달라 따로 낸다.
    struct_member_types: Dict[str, Dict[str, Dict[str, str]]] = {}
    # ⚠ 함수 스코프에 둔다 — 접기는 `if parse_c_project is not None:` 안에서만
    #   일어나는데 payload 는 밖에서 쓴다. 안에 선언하면 파서 부재 시 NameError.
    struct_member_arrays: Dict[str, Dict[str, str]] = {}
    param_defs: List[str] = []
    version_defs: List[str] = []
    global_data: List[str] = []
    global_vars: List[List[str]] = []
    static_vars: List[List[str]] = []
    macro_defs: List[List[str]] = []
    calibration_params: List[List[str]] = []
    function_table_rows: List[List[str]] = []
    # SwCom(mod_idx) 단위 함수 일련번호. `fn_id = SwUFn_{mod_idx}{counter}` 의 유일성을
    # 이 카운터가 책임진다 — 파일 stem 별로 세면 같은 SwCom 안에서 ID 가 충돌한다.
    _fn_counter_by_mod: Dict[int, int] = {}
    function_details: Dict[str, Dict[str, Any]] = {}
    function_details_by_name: Dict[str, Dict[str, Any]] = {}
    # {fid: body 앞부분}. AI 2차 description refinement(uds_ai)가 유일한 소비자다.
    # **detail dict 안이 아니라 별도 맵**인 이유: detail은 by_name(별칭 포함 1,160건)이 같은
    # 객체를 참조해 캐시 JSON에 두 번 직렬화되고, impact 문서초안 등 다른 소비자에게도 실려
    # 나간다. 여기 두면 fid 기준 1회(실측 900건 ≈ +360KB)로 끝나고 detail 계약도 안 바뀐다.
    function_body_snippets: Dict[str, str] = {}
    # 동일 이름 함수의 다중 정의(파일 간 충돌) 기록 — {name_lower: {files:[...], asil: max}}.
    # by_name은 last-wins(동일성 보존)이라 이 정보가 없으면 영향분석이 다른 사본을 누락한다.
    function_collisions: Dict[str, Dict[str, Any]] = {}
    call_map: Dict[str, List[str]] = {}
    fallback_functions: List[Dict[str, Any]] = []
    module_map: Dict[str, str] = {}
    globals_info_map: Dict[str, Dict[str, str]] = {}
    manual_globals_info_map: Dict[str, Dict[str, str]] = {}
    source_text_cache: Dict[str, str] = {}
    _header_proto_map: Dict[str, str] = {}  # name → header prototype (우선)
    if component_map is None:
        component_map = _load_component_map()
    _sds_map = sds_partition_map or {}

    # 함수 단위 SwCom/Related ID override (레퍼런스 UDS에서 역추출)
    _func_override: Dict[str, Dict[str, Any]] = {}
    for _override_path in [
        Path(__file__).resolve().parent / "docs" / "uds_function_swcom_override.json",
        Path(__file__).resolve().parent.parent / "docs" / "uds_function_swcom_override.json",
    ]:
        try:
            if _override_path.exists():
                _func_override = json.loads(_override_path.read_text(encoding="utf-8"))
                break
        except Exception:
            pass

    # typedef 정규화 맵 (임베디드 공통 타입)
    _typedef_map = {
        r"\bbyte\b": "U8", r"\bword\b": "U16", r"\bdword\b": "U32",
        r"\bBYTE\b": "U8", r"\bWORD\b": "U16", r"\bDWORD\b": "U32",
        r"\bEEPROM_TAddress_\b": "EEPROM_TAddress",
    }

    def _normalize_prototype(sig: str) -> str:
        """typedef 정규화 적용."""
        for pattern, replacement in _typedef_map.items():
            sig = re.sub(pattern, replacement, sig)
        return sig

    def _lookup_sds_related(func_name: str, module_name: str) -> str:
        """SDS 파티션 맵에서 함수명/모듈명으로 Related ID를 조회한다 (퍼지 매칭)."""
        if not _sds_map:
            return ""
        fn_lower = func_name.lower().strip()
        # 1. 함수명 정확 매칭
        info = _sds_map.get(fn_lower)
        if info and info.get("related"):
            return info["related"]
        # 2. 함수명 퍼지 매칭: g_DrvIn_Main → drvin, drvinmain 등
        fn_norm = re.sub(r"^[gs]_", "", fn_lower)  # g_, s_ 접두사 제거
        fn_tokens = re.sub(r"[^a-z0-9]", "", fn_norm)  # 특수문자 제거
        best_match = ""
        best_score = 0
        for k, v in _sds_map.items():
            if not v.get("related"):
                continue
            k_norm = re.sub(r"[^a-z0-9]", "", k)
            # 정확 포함 매칭 (함수명이 SDS 키에 포함되거나 반대)
            if fn_tokens and k_norm and (fn_tokens in k_norm or k_norm in fn_tokens):
                score = min(len(fn_tokens), len(k_norm)) / max(len(fn_tokens), len(k_norm), 1)
                if score > best_score:
                    best_score = score
                    best_match = v["related"]
        if best_score >= 0.5:
            return best_match
        # 3. 모듈명(SwCom 라벨) 매칭 — 최후 수단
        mod_key = re.sub(r"[^a-z0-9]+", "", module_name.lower())
        for k, v in _sds_map.items():
            if re.sub(r"[^a-z0-9]+", "", k) == mod_key and v.get("related"):
                return v["related"]
        return ""

    def _upsert_signature(items: List[str], signature: str, display: str) -> None:
        if not signature:
            return
        for idx, item in enumerate(items):
            if item.startswith(signature):
                items[idx] = display
                return
        items.append(display)

    truncated = False
    for _walk_root in _roots:
        for p in _src_walk(_walk_root):
            ext = p.suffix.lower()
            if ext not in allowed:
                continue
            if component_map:
                # 판정은 `requirements.component_verify_of` **단일 출처**다.
                # ⚠ 이 필터는 아래 `parse_c_project`(AST) 경로엔 안 걸린다 —
                #   그쪽은 루트를 따로 훑는다. 그래서 verify=X 파일의 함수가
                #   산출물에 남고, 그 사실은 `generators/suts` 가 보고한다.
                if component_verify_of(p, component_map) == "X":
                    continue
            files.append(p)
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            try:
                rel = p.relative_to(_walk_root)
            except ValueError:
                rel = p
            top = rel.parts[0] if rel.parts else "."
            top_dirs[top] = top_dirs.get(top, 0) + 1
            if len(files) >= max_files:
                truncated = True
                break
        if truncated:
            break

    doc_texts: List[str] = []
    _doxygen_tags_by_file: Dict[str, Dict[str, Dict[str, str]]] = {}
    _file_header_asil: Dict[str, str] = {}
    # 원문 읽기 상한에 **닿은 파일**. 캡은 조용히 자르므로 닿았다는 사실을 남기지
    # 않으면 "이 프로젝트엔 그 선언이 원래 없다" 와 구분되지 않는다
    # (실측: 200KB 캡이 IO_Map.h 의 매크로 69% 를 지웠는데 로그가 한 줄도 없었다).
    _read_truncated: List[Tuple[str, int]] = []
    for p in files:
        raw, _raw_len, _cut = _read_source_text(p)
        if _cut:
            _read_truncated.append((str(p), _raw_len))
        text = _strip_c_comments(raw)
        # ⚠ 주석이 지워진 `text` 로 본다 — 주석 안 선언을 세면 없는 레지스터가 생긴다.
        _placed_globals.update(placed_global_names(text))
        reqs.extend(_extract_requirements_from_comments(raw))
        dox_tags = _extract_doxygen_asil_tags(raw)
        if dox_tags:
            _doxygen_tags_by_file[str(p)] = dox_tags
        hdr_asil = _extract_file_header_asil(raw)
        if hdr_asil:
            _file_header_asil[str(p)] = hdr_asil
        for _sty, _smm in extract_struct_member_arrays(text).items():
            struct_member_arrays_raw.setdefault(_sty, {}).update(_smm)
        # ⚠ **`raw`** 를 넘긴다. `text` 는 주석이 지워진 판이라 멤버의 자기 주석이
        #    통째로 사라진다(그 함수가 내부에서 길이 보존 blank 를 다시 한다).
        for _sty, _smt in extract_struct_member_types(raw).items():
            _dst = struct_member_types.setdefault(_sty, {})
            for _mname, _mrec in _smt.items():
                # first-wins. dict 덮어쓰기로 행을 침묵 소실한 전례(SUTS R25 66행).
                _dst.setdefault(_mname, _mrec)
        for g in _extract_c_global_candidates(text):
            gname = str(g.get("name") or "").strip()
            if not gname:
                continue
            prev = manual_globals_info_map.get(gname, {})
            manual_globals_info_map[gname] = {
                "type": str(g.get("type") or prev.get("type") or "").strip(),
                # 배열 차원(`[60]`). 정본은 배열을 원소 단위로 펼쳐 적는다 —
                # `source_parser._decl_array_dim` 주석 참조.
                "array": str(g.get("array") or prev.get("array") or "").strip(),
                "file": str(p),
                "range": str(prev.get("range") or "").strip(),
                "init": str(g.get("init") or prev.get("init") or "").strip(),
                "range_source": str(prev.get("range_source") or "").strip(),
                "static": str(g.get("static") or prev.get("static") or "false").strip().lower(),
                "desc": str(prev.get("desc") or "").strip(),
            }
        if p.suffix.lower() in {".h", ".hpp"}:
            for name, params, ret_type, is_extern in _extract_c_prototypes(text):
                signature = f"{ret_type} {name}( {params} )" if ret_type else f"{name}({params})"
                # Header prototype을 맵에 저장 (source definition보다 우선)
                if name not in _header_proto_map:
                    _header_proto_map[name] = signature
                if name.startswith("g_"):
                    interfaces.append(signature)
                elif name.startswith("s_"):
                    internals.append(signature)
                elif is_extern:
                    interfaces.append(signature)
                else:
                    interfaces.append(signature)
            macros.extend(_extract_c_macros(text))
            for m_name, m_val in _extract_c_macro_defs(text):
                macro_defs.append([m_name, "", m_val, ""])
        else:
            body_map = _extract_c_function_bodies(text)
            # 리셋/초기화 함수의 전역 대입을 모은다(같은 `body_map` 재사용 — 추가 파싱 0).
            # ⚠ 헤더(`.h`)는 여기 안 온다. 헤더에 `static` 초기화 함수가 있으면 못 본다.
            for _rvar, _rrows in collect_reset_assignments(body_map).items():
                _reset_assigns.setdefault(_rvar, []).extend(_rrows)
            for name, params, ret_type, is_static in _extract_c_definitions(text):
                signature = f"{ret_type} {name}( {params} )" if ret_type else f"{name}({params})"
                if name.startswith("g_"):
                    interfaces.append(signature)
                elif name.startswith("s_"):
                    internals.append(signature)
                elif is_static:
                    internals.append(signature)
                else:
                    unknowns.append(signature)
                body_text = str(body_map.get(name) or "")
                calls_list = _extract_simple_call_names(body_text)
                dox_info = _doxygen_tags_by_file.get(str(p), {}).get(name, {})
                file_asil = _file_header_asil.get(str(p), "")
                c_asil = dox_info.get("asil", "") or file_asil
                c_related = dox_info.get("requirement", "")
                c_desc = dox_info.get("brief", "")
                fallback_functions.append(
                    {
                        "name": name,
                        "signature": signature,
                        "is_static": bool(is_static),
                        "file": str(p),
                        "calls": calls_list,
                        "used_globals": [],
                        "comment_desc": c_desc,
                        "comment_asil": c_asil,
                        "comment_related": c_related,
                        "comment_precondition": "",
                        "body": body_text,
                    }
                )
            source_text_cache[str(p)] = raw
            macros.extend(_extract_c_macros(text))
            for m_name, m_val in _extract_c_macro_defs(text):
                macro_defs.append([m_name, "", m_val, ""])

        lines = raw.splitlines()
        stop_headers = [
            "Type Definition",
            "Parameter Definition",
            "Version Information",
            "Software Unit Structure",
        ]
        cm = _extract_table_section(lines, "Common Macro Definition", stop_headers, 30)
        td = _extract_table_section(lines, "Type Definition", stop_headers, 30)
        pd = _extract_table_section(lines, "Parameter Definition", stop_headers, 30)
        vd = _extract_table_section(lines, "Version Information", stop_headers, 10)
        common_macros.extend(cm)
        type_defs.extend(td)
        param_defs.extend(pd)
        version_defs.extend(vd)

        if (
            len(interfaces) >= max_items
            and len(internals) >= max_items
            and len(macros) >= max_items
            and len(reqs) >= max_items
        ):
            break

    # additional documentation files (txt/md) for structured templates
    doc_files = 0
    for _walk_root2 in _roots:
        for p in _src_walk(_walk_root2):
            ext = p.suffix.lower()
            if ext not in {".txt", ".md"}:
                continue
            doc_texts.append(_read_text_limited(p))
            doc_files += 1
            if doc_files >= 20:
                break
        if doc_files >= 20:
            break

    function_blocks: List[Dict[str, Any]] = []
    for txt in doc_texts:
        function_blocks.extend(_extract_function_blocks(txt))
        cm = _extract_table_section(
            txt.splitlines(),
            "Common Macro Definition",
            ["Type Definition", "Parameter Definition", "Version Information", "Software Unit Structure"],
            30,
        )
        td = _extract_table_section(
            txt.splitlines(),
            "Type Definition",
            ["Parameter Definition", "Version Information", "Software Unit Structure"],
            30,
        )
        pd = _extract_table_section(
            txt.splitlines(),
            "Parameter Definition",
            ["Version Information", "Software Unit Structure"],
            30,
        )
        vd = _extract_table_section(
            txt.splitlines(),
            "Version Information",
            ["Software Unit Structure"],
            10,
        )
        common_macros.extend(cm)
        type_defs.extend(td)
        param_defs.extend(pd)
        version_defs.extend(vd)

    fallback_function_name_set: Set[str] = {
        str(fn.get("name") or "").strip()
        for fn in fallback_functions
        if str(fn.get("name") or "").strip()
    }

    # 전역 인식 손실 계수. **AST 경로 밖에서도 반드시 바인딩돼 있어야 한다** — 아래
    # 페이로드가 무조건 읽으므로, regex 폴백 경로에선 `NameError` 로 생성이 통째로 죽는다.
    # ⚠ 기본값을 0 으로 두면 안 된다. "손실 0" 과 "재지 못함" 은 다른 말이고, 0 으로 두면
    #   regex 폴백일 때 화면이 "전역을 하나도 안 잃었다" 고 말한다.
    _globals_loss: Dict[str, Any] = {"measured": False, "reason": "AST 파서 미가용(regex 폴백)"}

    # AST 기반 보강 (가능 시)
    try:
        from workflow.code_parser import parse_c_project  # type: ignore
    except Exception:
        parse_c_project = None  # type: ignore
    if parse_c_project is not None:
        try:
            # 복수 루트에서 AST 파싱 + 결과 병합
            ast_result = {"functions": [], "globals": [], "globals_detailed": []}
            for _parse_root in _roots:
                try:
                    _partial = parse_c_project(str(_parse_root), max_files=max_files, preprocess=preprocess)
                    if isinstance(_partial, dict):
                        ast_result["functions"].extend(_partial.get("functions") or [])
                        ast_result["globals"].extend(_partial.get("globals") or [])
                        ast_result["globals_detailed"].extend(_partial.get("globals_detailed") or [])
                except Exception:
                    pass
        except Exception:
            ast_result = {"functions": [], "globals": []}
        # AST 중복 함수 제거 (복수 루트에서 동일 함수명 중복 가능)
        # ⚠ 안전: first-wins로 detail은 유지하되 ASIL은 중복 변형 중 '최대'로 보수적 상향한다.
        # preprocess=False에선 #ifdef/#if MACRO로 가드된 동일 함수명 변형이 둘 다 파싱되는데,
        # 소스 우선(source-first) 변형이 비활성(낮은 ASIL)일 수 있어 first-wins가 ASIL을 하향할 위험
        # (ASIL D 변경을 A로 오판→에스컬레이션/MC-DC 게이트 미발동). ASIL만 max로 올려 하향을 차단.
        _ASIL_R = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}

        def _asil_rank_of(_v: Any) -> int:
            _s = re.sub(r"^ASIL[\s_-]*", "", str(_v or "").strip().upper()).strip()
            return _ASIL_R.get(_s, -1)

        _seen_ast_idx: Dict[str, int] = {}
        _deduped: List[Dict[str, Any]] = []
        for _fn in (ast_result.get("functions") or []):
            _fn_name = str(_fn.get("name") or "").strip() if isinstance(_fn, dict) else ""
            if not _fn_name:
                continue
            if _fn_name not in _seen_ast_idx:
                _seen_ast_idx[_fn_name] = len(_deduped)
                _deduped.append(_fn)
            else:
                _prev = _deduped[_seen_ast_idx[_fn_name]]
                if _asil_rank_of(_fn.get("comment_asil")) > _asil_rank_of(_prev.get("comment_asil")):
                    _prev["comment_asil"] = _fn.get("comment_asil")  # 하향 방지(보수적 상향)
                # ⚠ 여기서 두 번째 정의를 **파일 경로째 통째로 버린다**. 그래서 하위 레이어
                # (_put_by_name / function_details_by_name)는 충돌을 **볼 수조차 없다** — 충돌 정보를
                # 거기서 기록하려던 과거 시도들이 전부 죽은 코드였던 이유다.
                # 동일 이름이 여러 파일에 정의되면(예: Generated_Code/EEPROM.c와 Sources/Eeprom/EEPROM.c의
                # eeprom_setbyte, main 등) 영향분석은 남은 한 사본의 file만 보고 **다른 파일의 변경을
                # 통째로 놓친다**(ISO 26262 under-report — 실제로 ASIL D 구현이 누락될 수 있음).
                # → 정의 파일 전체와 최대 ASIL을 이 시점에 기록한다(소비자: impact_orchestrator).
                _ck = _fn_name.strip().lower()
                _ce = function_collisions.setdefault(_ck, {"files": [], "asil": ""})
                for _d in (_prev, _fn):
                    _df = str(_d.get("file") or "").strip()
                    if _df and _df not in _ce["files"]:
                        _ce["files"].append(_df)
                    if _asil_rank_of(_d.get("comment_asil")) > _asil_rank_of(_ce.get("asil")):
                        _ce["asil"] = str(_d.get("comment_asil") or "")
        ast_result["functions"] = _deduped
        module_ids: Dict[str, int] = {}
        module_order = [
            k for k, _ in sorted(top_dirs.items(), key=lambda x: (-x[1], x[0]))
        ]
        next_module_idx = 1
        for name in module_order:
            module_ids[name] = next_module_idx
            next_module_idx += 1
        globals_detailed = ast_result.get("globals_detailed", []) or []
        function_name_set: Set[str] = set()
        used_identifier_set: Set[str] = set()
        for ftmp in ast_result.get("functions", []) or []:
            if isinstance(ftmp, dict):
                n = str(ftmp.get("name") or "").strip()
                if n:
                    function_name_set.add(n)
                body_blob = str(ftmp.get("body_text") or ftmp.get("body") or "")
                if body_blob:
                    used_identifier_set.update(
                        re.findall(r"\b[A-Za-z_]\w*\b", _strip_c_comments(body_blob))
                    )
        function_name_set.update(fallback_function_name_set)
        globals_info_map = dict(manual_globals_info_map)
        static_name_map: Dict[str, bool] = {}
        for gk, gv in globals_info_map.items():
            try:
                static_name_map[gk] = str((gv or {}).get("static") or "").strip().lower() == "true"
            except Exception:
                static_name_map[gk] = False
        macro_name_set: Set[str] = set()
        for row in macro_defs:
            if row:
                macro_name_set.add(str(row[0]).strip())
        for row in common_macros:
            cols = _normalize_table_row(row)
            if cols:
                macro_name_set.add(str(cols[0]).strip())
        macro_value_map: Dict[str, str] = {}
        for row in macro_defs:
            if len(row) >= 3:
                macro_value_map[str(row[0]).strip()] = str(row[2]).strip()
        for row in common_macros:
            cols = _normalize_table_row(row)
            if len(cols) >= 3:
                macro_value_map[str(cols[0]).strip()] = str(cols[2]).strip()
        # 멤버 차원 접기는 **매크로 맵이 완성된 뒤**에 한다 — `[LIN_MAX_DATA_BYTES]`
        # 처럼 값이 다른 헤더에 있는 경우가 흔해서 파일 단위로는 못 접는다.
        # ⚠ 접히지 않은 차원은 **버린다**. `[SIGNATURE_SIZE]` 에서 숫자만 긁으면
        #   없는 크기를 지어내게 된다(`generators/suts._decl_dims_from_array_field`
        #   와 같은 이유).
        for _sty, _smm in struct_member_arrays_raw.items():
            for _mname, _mdims in _smm.items():
                _dims = _normalize_dims(_mdims, macro_value_map)
                if _dims and all(str(x).strip().isdigit() for x in _dims):
                    struct_member_arrays.setdefault(_sty, {})[_mname] = "".join(
                        f"[{int(x)}]" for x in _dims
                    )

        if globals_detailed:
            for g in globals_detailed:
                if not isinstance(g, dict):
                    continue
                gname = str(g.get("name") or "").strip()
                if gname in function_name_set:
                    continue
                if gname in macro_name_set:
                    continue
                gtype = str(g.get("type") or "").strip()
                gfile = str(g.get("file") or "").strip()
                grange = str(g.get("range") or "").strip()
                gdecl = str(g.get("decl") or "").strip()
                # Skip function prototypes accidentally surfaced as globals.
                if gdecl and "(" in gdecl and ")" in gdecl:
                    continue
                if not gtype and gdecl:
                    gtype = _infer_type_from_decl(gdecl, gname)
                if gtype.lower() == "void" and re.match(r"^[gs]_", gname):
                    continue
                if not gtype and gfile:
                    gtype, init_from_file = _infer_type_from_file(gfile, gname)
                    if not g.get("init") and init_from_file:
                        g = dict(g)
                        g["init"] = init_from_file
                if gtype.lower() == "void" and re.match(r"^[gs]_", gname):
                    continue
                is_static = str(g.get("is_static") or "").strip().lower() == "true"
                if not is_static and gname:
                    from config import STATIC_VAR_PREFIXES
                    if any(gname.startswith(p) for p in STATIC_VAR_PREFIXES):
                        is_static = True
                if gname:
                    prev = globals_info_map.get(gname, {}) if isinstance(globals_info_map.get(gname), dict) else {}
                    incoming_desc = str(g.get("desc") or "").strip()
                    static_name_map[gname] = is_static
                    # ⚠ tree-sitter 산출 타입(`gtype`)엔 **`const` 한정자가 없다**.
                    #   텍스트 스캔(`prev`)은 갖고 있는데 여기서 통째로 덮여
                    #   `static const UDSFuncEntry_t s_UdsFuncTbl[…]` 가 그냥
                    #   `UDSFuncEntry_t` 로 남았다. const 는 "시험 입력으로 설정할 수
                    #   없다"는 판정의 유일한 근거라 **한정자만** 되살린다.
                    _gtype = gtype or str(prev.get("type") or "").strip()
                    if is_const_type(prev.get("type")) and not is_const_type(_gtype):
                        _gtype = f"const {_gtype}".strip()
                    globals_info_map[gname] = {
                        "type": _gtype,
                        # ⚠ tree-sitter 쪽(`globals_detailed`)엔 배열 차원 필드가 없다.
                        #   텍스트 스캔이 이미 채워둔 값을 **먼저** 쓰고, 없을 때만
                        #   선언문에서 뽑는다(`decl` 은 문장 전체라 다중 선언자면
                        #   마지막 것이 나온다 — 그래서 텍스트 스캔이 우선이다).
                        "array": str(prev.get("array") or "").strip() or _decl_array_dim(gdecl),
                        "file": gfile or str(prev.get("file") or "").strip(),
                        "range": grange or str(prev.get("range") or "").strip(),
                        "init": str(g.get("init") or "").strip() or str(prev.get("init") or "").strip(),
                        "range_source": str(g.get("range_source") or "").strip().lower(),
                        "static": "true" if is_static else "false",
                        "desc": incoming_desc or str(prev.get("desc") or "").strip(),
                    }
        # ── Reset Value 판정 (판정은 `report_gen.c_reset` **단일 출처**) ──────────
        # 값과 **출처**를 함께 낸다. 정본은 같은 심볼에 두 값을 적는 곳이 16심볼·100칸
        # (4.6%) 인데, 그게 "C 정적 저장기간(0)" 과 "리셋 함수가 넣는 값" 이 섞인
        # 결과다. 표시 없이 값만 적으면 그 모호함을 그대로 물려받는다.
        _reset_stats: Dict[str, int] = {}
        for _gname, _ginfo in globals_info_map.items():
            _cell, _src = resolve_reset(
                _ginfo, _reset_assigns.get(_gname), macro_value_map,
                placed=_gname in _placed_globals)
            _ginfo["reset"] = _cell
            _ginfo["reset_source"] = _src
            _reset_stats[_src] = _reset_stats.get(_src, 0) + 1
        _logger.info(
            "reset 판정: %s",
            " · ".join(f"{k} {v}" for k, v in sorted(
                _reset_stats.items(), key=lambda kv: -kv[1])) or "(전역 없음)")

        # 스캔 캡에 실제로 닿는지 **센다**. 캡은 조용히 자르므로, 닿았는지를 기록하지 않으면
        # "이 프로젝트엔 전역이 원래 없다" 와 "캡에서 잘렸다" 를 구분할 수 없다.
        _c_files = [f for f in files if f.suffix.lower() == ".c"]
        _h_files = [f for f in files if f.suffix.lower() == ".h"]
        _scan_caps = {"c_total": len(_c_files), "c_cap": 200,
                      "h_total": len(_h_files), "h_cap": 300}
        for src_file in _c_files[:200]:
            try:
                src_text = _src_read(src_file)
                source_text_cache[str(src_file)] = src_text
            except Exception:
                continue
            for g in _extract_c_global_candidates(src_text):
                vname = str(g.get("name") or "").strip()
                if vname and str(g.get("static") or "").strip().lower() == "true":
                    static_name_map[vname] = True
        try:
            import config as _cfg
            _global_prefixes = tuple(getattr(_cfg, "GLOBAL_VAR_PREFIXES", ())) + tuple(
                getattr(_cfg, "STATIC_VAR_PREFIXES", ())
            )
        except Exception:
            _global_prefixes = ("g_", "s_", "u8g_", "u16g_", "u32g_", "u8s_", "u16s_", "u32s_")
        _extern_added = 0
        c_source_texts = [text for path, text in source_text_cache.items() if str(path).lower().endswith(".c")]
        # extern 사용여부 판정을 위해 전체 .c 원문의 식별자 토큰집합을 1회만 만든다.
        # (기존: extern마다 모든 .c에 re.search full-text 스캔 → O(헤더×extern×전체.c). 대형
        #  트리에서 파싱 지연의 주요인. 토큰집합 in 검사로 O(extern)로 단축.)
        # ⚠ 토큰화는 `c_identifiers`(= `\b` 앵커)여야 한다. `[A-Za-z_]\w*` 는 `2U` 의
        #   `U` 를 식별자로 내놔 **1글자 유령 전역**을 "소스에서 쓰임"으로 통과시킨다.
        _c_token_set: Set[str] = set()
        for _src_text in c_source_texts:
            _c_token_set.update(c_identifiers(_src_text))
        # ⚠ 매크로 뒤에 숨은 SFR(`#define PTT_PTT3 _PTT.Bits.PTT3`)을 살리려고 이 필터에
        #    "매크로 경유 사용" 예외를 넣었다가 **뺐다**. 실측(KJPDS02 Sources/SYSTEM +
        #    Generated_Code): 예외를 꺼도 `_PTT` 는 그대로 해결된다 — `globals_detailed`
        #    (tree-sitter 전 파일 스캔)가 이미 잡고 있고, 진짜 원인은 선언 이름을
        #    주소 리터럴로 읽던 `_parse_c_declaration_statement` 쪽이었다.
        #    근거가 확인되지 않는 완화는 넣지 않는다.
        # 이 필터들이 실제로 몇 건을 떨어뜨리는지 **센다**. 세지 않으면 "떨어뜨릴 게
        # 없었다" 와 "떨어뜨렸다" 가 똑같이 조용하다.
        #
        # ⚠ 실측(2026-08-12, KJPDS02·HDPDM01): 이 루프가 추가하는 건수는 **0** 이다.
        #   위 `globals_detailed`(tree-sitter 전 파일 스캔)가 헤더까지 이미 훑기 때문에
        #   `ename in globals_info_map` 에서 전부 걸러진다(include 가드를 씌워도 같다).
        #   즉 이 블록은 **tree-sitter 가 그 헤더를 파싱하지 못했을 때만** 동작하는
        #   폴백이다. 아래 카운터는 그 폴백이 언젠가 실제로 도는지 보기 위한 계측이며,
        #   지금은 도달하지 않으므로 테스트로 고정할 수 없다(가짜 테스트를 만들지 않는다).
        _extern_dropped = {"unused_in_source": 0, "prefix_mismatch": 0}
        for hdr_file in _h_files[:300]:
            try:
                hdr_text = _src_read(hdr_file)
                source_text_cache[str(hdr_file)] = hdr_text
            except Exception:
                continue
            for item in _extract_c_global_candidates(hdr_text):
                if str(item.get("extern") or "").strip().lower() != "true":
                    continue
                etype = str(item.get("type") or "").strip()
                ename = str(item.get("name") or "").strip()
                if not ename or ename in globals_info_map or ename in function_name_set or ename in macro_name_set:
                    continue
                if etype.lower() in {"void"}:
                    continue
                used_in_body = ename in used_identifier_set
                # 토큰집합 멤버십(O(1))으로 전체 .c full-text re.search를 대체.
                used_in_source = used_in_body or (ename in _c_token_set)
                if not used_in_source:
                    _extern_dropped["unused_in_source"] += 1
                    continue
                if (not any(ename.startswith(p) for p in _global_prefixes)) and not used_in_body:
                    _extern_dropped["prefix_mismatch"] += 1
                    continue
                globals_info_map[ename] = {
                    "type": etype,
                    "file": str(hdr_file),
                    "range": "",
                    "init": "",
                    "range_source": "extern_usage" if used_in_body else "extern_weak_usage",
                    "static": "false",
                    "desc": "",
                }
                _extern_added += 1
        if _extern_added > 0:
            _logger.info("extern variable scan: added %d variables from headers", _extern_added)
        _typeless_dropped = 0
        if globals_info_map:
            _before = len(globals_info_map)
            globals_info_map = {
                k: v for k, v in globals_info_map.items() if str(v.get("type") or "").strip()
            }
            _typeless_dropped = _before - len(globals_info_map)
        # 전역 인식에서 **잃은 것**을 한 줄로 낸다. 셋 다 조용히 자르는 지점이라, 기록이
        # 없으면 "이 프로젝트엔 원래 없다" 로 오독한다. 캡에 닿으면 WARNING 으로 올린다
        # (SITS `headroom` 과 같은 규약 — 절단 0 이 아니라 여유를 본다).
        _globals_loss = {
            "measured": True,
            **_scan_caps,
            "c_scanned": min(_scan_caps["c_total"], _scan_caps["c_cap"]),
            "h_scanned": min(_scan_caps["h_total"], _scan_caps["h_cap"]),
            "extern_added": _extern_added,
            "extern_dropped_unused": _extern_dropped["unused_in_source"],
            "extern_dropped_prefix": _extern_dropped["prefix_mismatch"],
            "typeless_dropped": _typeless_dropped,
            "globals_kept": len(globals_info_map),
            # 파일 **내부** 절단. 위 c_cap/h_cap 은 "파일 몇 개를 봤나" 이고 이건
            # "본 파일을 끝까지 읽었나" 다 — 둘은 다른 축이라 따로 센다.
            "read_truncated_files": len(_read_truncated),
            "read_truncated_detail": [
                {"file": f, "bytes": n, "cap": _SRC_READ_MAX_BYTES}
                for f, n in _read_truncated[:10]
            ],
        }
        _at_cap = (_scan_caps["c_total"] > _scan_caps["c_cap"]
                   or _scan_caps["h_total"] > _scan_caps["h_cap"])
        (_logger.warning if (_at_cap or _read_truncated) else _logger.info)(
            "globals scan: kept=%d | .c %d/%d · .h %d/%d%s | extern +%d "
            "(미사용 -%d · 접두사 -%d) | 타입없음 -%d | 파일내부절단 %d%s",
            _globals_loss["globals_kept"],
            _globals_loss["c_scanned"], _scan_caps["c_total"],
            _globals_loss["h_scanned"], _scan_caps["h_total"],
            "  ⚠캡 도달 — 나머지 파일의 전역은 인식되지 않는다" if _at_cap else "",
            _extern_added, _extern_dropped["unused_in_source"],
            _extern_dropped["prefix_mismatch"], _typeless_dropped,
            len(_read_truncated),
            ("  ⚠" + ", ".join(f"{Path(f).name}({n:,}B>{_SRC_READ_MAX_BYTES:,})"
                               for f, n in _read_truncated[:3])
             if _read_truncated else ""),
        )
        macro_globals_map: Dict[str, List[str]] = {}
        # 매크로 이름 -> 확장형. 확장형이 곧 **문서에 적힐 이름**이다(`_PTT.Bits.PTT3`).
        # 이게 없으면 base(`_PTT`)만 남아 정본과 다른 이름이 된다.
        # ⚠ 아래 `_MACRO_MEMBER_PATH_RE` 필터는 **정확성 가드가 아니라 맵 크기 제한**이다.
        #    실제로 "확장형이 이 전역의 멤버 경로인가" 판정은 `_collect_var_usage` 가 다시
        #    한다(`^{g}(\.|->|\[)`). 필터를 빼도 결과는 같고 맵만 커진다(이 프로젝트 7,337개).
        macro_expansion_map: Dict[str, str] = {}
        macro_call_map: Dict[str, List[str]] = {}
        if globals_info_map:
            for row in macro_defs:
                if len(row) >= 3:
                    m_name = str(row[0]).strip()
                    m_val = str(row[2]).strip()
                    if not m_name or not m_val:
                        continue
                    if _MACRO_MEMBER_PATH_RE.match(m_val):
                        macro_expansion_map[m_name] = re.sub(r"\s+", "", m_val)
                    # 전역명은 항상 식별자 토큰 → \bNAME\b ≡ 토큰 멤버십. m_val 1회 토큰화 후 O(1) in
                    # 검사로 per-global re.search(rf...) 재컴파일(대형 트리에서 파싱 지연 주요인) 제거.
                    #
                    # ⚠ **토큰 쪽을 순회한다**(전역 목록이 아니라). 전역은 1,500개인데
                    #   매크로 확장형의 토큰은 보통 1~3개다. 읽기 캡을 풀면서 매크로가
                    #   3.2배(≈2,800 → 9,000)로 늘었는데, 전역을 순회하면 1,350만 번
                    #   비교가 되고 토큰을 순회하면 2만 번이다. 결과 집합은 같다
                    #   (아래 소비처는 전역별 플래그를 독립적으로 세우므로 **순서 무관**).
                    #   순서는 캐시 산출물에 실리므로 `sorted` 로 고정한다.
                    hits = sorted(t for t in set(c_identifiers(m_val)) if t in globals_info_map)
                    if hits:
                        macro_globals_map[m_name] = hits
                    call_hits: List[str] = []
                    for call_name in _extract_simple_call_names(m_val):
                        if call_name in function_name_set and call_name not in call_hits:
                            call_hits.append(call_name)
                    if call_hits:
                        macro_call_map[m_name] = call_hits[:10]

        # 접근자 함수 패턴: get_*/set_* 함수가 전역변수를 반환/설정하는 패턴 감지
        _accessor_globals_map: Dict[str, List[str]] = {}
        if globals_info_map:
            for fn in ast_result.get("functions", []) or []:
                if not isinstance(fn, dict):
                    continue
                fname = str(fn.get("name") or "").strip()
                if not fname:
                    continue
                fname_lower = fname.lower()
                is_accessor = (
                    fname_lower.startswith("get_") or fname_lower.startswith("set_")
                    or fname_lower.startswith("get") or fname_lower.startswith("set")
                )
                if not is_accessor:
                    continue
                body = str(fn.get("body_text") or fn.get("body") or "").strip()
                used = fn.get("used_globals") or []
                if not isinstance(used, list):
                    used = []
                accessed_globals = [g for g in used if g in globals_info_map]
                if not accessed_globals and body:
                    # body 1회 토큰화 후 멤버십 — per-global re.search(rf...) 재컴파일 제거(위 macro 루프와 동일 관용구).
                    _body_toks = set(c_identifiers(body))
                    for gname in list(globals_info_map.keys())[:500]:
                        if gname in _body_toks:
                            accessed_globals.append(gname)
                if accessed_globals:
                    _accessor_globals_map[fname.lower()] = accessed_globals[:10]
            if _accessor_globals_map:
                _logger.info("Accessor function globals: %d accessor functions detected", len(_accessor_globals_map))

        callee_signature_map: Dict[str, str] = {}
        for f2 in ast_result.get("functions", []) or []:
            if not isinstance(f2, dict):
                continue
            n2 = str(f2.get("name") or "").strip()
            s2 = str(f2.get("signature") or "").strip()
            if n2 and s2 and n2 not in callee_signature_map:
                callee_signature_map[n2] = s2

        def _merge_call_candidates(
            fn_name: str,
            file_path: str,
            body_text: str,
            ast_calls: List[str],
        ) -> Tuple[List[str], str]:
            merged: List[str] = []
            source_parts: List[str] = []
            for name in ast_calls or []:
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if merged:
                source_parts.append("ast")
            for name in _extract_simple_call_names(body_text):
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if len(merged) > len(ast_calls or []):
                source_parts.append("body")
            macro_calls = _extract_macro_call_names(body_text, macro_call_map)
            for name in macro_calls:
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if macro_calls:
                source_parts.append("macro")
            fptr_calls = _extract_function_pointer_call_targets(body_text, function_name_set)
            for name in fptr_calls:
                if name and name != fn_name and name in function_name_set and name not in merged:
                    merged.append(name)
            if fptr_calls:
                source_parts.append("fptr")
            if not merged:
                fb = _extract_fallback_call_names(
                    source_text_cache.get(file_path, ""),
                    fn_name,
                    function_name_set,
                    body_text,
                )
                for name in fb:
                    if name and name != fn_name and name not in merged:
                        merged.append(name)
                if fb:
                    source_parts.append("fallback")
            return merged[:50], "+".join(source_parts) if source_parts else ""

        for fn in ast_result.get("functions", []) or []:
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name") or "").strip()
            signature = str(fn.get("signature") or name).strip()
            # Header prototype 우선 사용 (파라미터명/타입이 더 정확)
            if name in _header_proto_map:
                signature = _header_proto_map[name]
            is_static = bool(fn.get("is_static"))
            # static 함수의 시그니처에 static 키워드 보존 (레퍼런스 UDS 형식)
            if is_static and not signature.lstrip().startswith("static "):
                signature = "static " + signature
            # typedef 정규화 (byte→U8, word→U16 등)
            signature = _normalize_prototype(signature)
            file_path = str(fn.get("file") or "").strip()
            calls = fn.get("calls") or []
            used_globals = fn.get("used_globals") or []
            comment_desc = str(fn.get("comment_desc") or "").strip()
            comment_asil = str(fn.get("comment_asil") or "").strip()
            comment_related = str(fn.get("comment_related") or "").strip()
            comment_precond = str(fn.get("comment_precondition") or "").strip()
            if not name:
                continue
            if file_path and file_path not in source_text_cache:
                try:
                    source_text_cache[file_path] = _src_read(file_path)
                except Exception:
                    source_text_cache[file_path] = ""
            if not isinstance(calls, list):
                calls = []
            calls = [str(c).strip() for c in calls if str(c).strip()]
            body_text_full = str(fn.get("body_text") or fn.get("body") or "")
            calls, calls_source = _merge_call_candidates(name, file_path, body_text_full, calls)
            if calls_source:
                fn["calls_source"] = calls_source
            if isinstance(calls, list):
                call_map[name] = [str(c).strip() for c in calls if str(c).strip()]
            call_suffix = ""
            if isinstance(calls, list) and calls:
                call_suffix = f" calls: {', '.join([str(c) for c in calls[:6] if c])}"
            file_suffix = f" [{Path(file_path).name}]" if file_path else ""
            display = f"{signature}{file_suffix}{call_suffix}".strip()
            if is_static:
                _upsert_signature(internals, signature, display)
            else:
                _upsert_signature(interfaces, signature, display)
            module_name = "Module"
            if file_path:
                try:
                    fp_resolved = _src_relbase(file_path)
                    rel = None
                    for _r in _roots:
                        try:
                            rel = fp_resolved.relative_to(_r)
                            break
                        except ValueError:
                            continue
                    module_name = rel.parts[0] if rel and rel.parts else "Module"
                except Exception:
                    module_name = "Module"
            if component_map and file_path:
                # 경로 기반 매칭 우선 (동일 파일명 충돌 해결)
                mapped = None
                fp_norm = file_path.replace("\\", "/")
                for cm_key in component_map:
                    if "/" in cm_key and fp_norm.endswith(cm_key):
                        mapped = component_map[cm_key]
                        break
                if not mapped or not isinstance(mapped, dict):
                    key = Path(file_path).name
                    mapped = component_map.get(key) or component_map.get(Path(file_path).stem)
                if isinstance(mapped, dict) and mapped.get("component"):
                    module_name = str(mapped.get("component"))
                    module_name = _normalize_swcom_label(module_name)
            # 함수 단위 SwCom override 적용 (레퍼런스 역추출 맵)
            _ovr = _func_override.get(name)
            if _ovr and isinstance(_ovr, dict) and _ovr.get("swcom") is not None:
                mod_idx = int(_ovr["swcom"])
                module_name = f"SwCom_{mod_idx:02d}"
            else:
                # SwCom 번호를 module_name에서 직접 추출 (레퍼런스와 동일 체계)
                _swcom_m = re.search(r"SwCom[_\s-]*(\d+)", module_name, re.I)
                if _swcom_m:
                    mod_idx = int(_swcom_m.group(1))
                else:
                    if module_name not in module_ids:
                        module_ids[module_name] = next_module_idx
                        next_module_idx += 1
                    mod_idx = module_ids.get(module_name, 0)
            module_map[name] = module_name
            # ⚠ counter 는 `fn_id` 의 **유일성을 책임진다**. 예전엔 `module_name`(파일 stem)
            #   별로 셌는데 `fn_id` 는 `mod_idx`(SwCom 번호) + counter 로 만든다. 같은
            #   SwCom 에 속한 파일이 여럿이면 **서로 다른 함수가 같은 fn_id 를 받고**
            #   `function_details[fn_id] = detail` 이 조용히 덮어썼다.
            #   실측(PDS128_FBL, 2026-08-12): c_parser 186함수 → 165개만 남고 `main.c` 는
            #   24개 중 **5개만** 살아남았다(linuds 86 · lin 24 · main 5 가 전부
            #   `SwUFn_3501` 부터 시작). 정본 대비 251개 누락의 주 원인이다.
            #   SwCom 단위로 세는 것이 `SwUFn_{SwCom}{순번}` 체계의 원래 의도다.
            counter = _fn_counter_by_mod.get(mod_idx, 0) + 1
            _fn_counter_by_mod[mod_idx] = counter
            fn_id = f"SwUFn_{mod_idx:02d}{counter:02d}" if counter <= 99 else f"SwUFn_{mod_idx:02d}{counter:03d}"
            lname = name.lower()
            if lname.startswith("s_"):
                fn_type = "Internal"
            elif lname.startswith("g_"):
                fn_type = "I/F"
            else:
                fn_type = "Internal" if is_static else "I/F"
            function_table_rows.append(
                [
                    f"SwCom_{mod_idx:02d}",
                    module_name,
                    fn_id,
                    name,
                    fn_type,
                    "",
                ]
            )
            used_globals_list: List[str] = []
            inputs_list: List[str] = []
            outputs_list: List[str] = []
            globals_static: List[str] = []
            globals_global: List[str] = []
            body_text = str(fn.get("body") or "")
            if body_text:
                params = _parse_signature_params(signature)
                param_names: List[str] = []
                for p in params:
                    _, pname, _ = _split_param(p)
                    if pname:
                        param_names.append(pname)
                param_usage = _collect_var_usage(body_text, param_names)
                global_names = list(globals_info_map.keys())
                global_usage = _collect_var_usage(
                    body_text, global_names, macro_globals_map, macro_expansion_map
                )
                for p in params:
                    ptype, pname, array_part = _split_param(p)
                    if not pname:
                        continue
                    u = param_usage.get(pname, {})
                    direction = "IN"
                    if u.get("inout"):
                        direction = "INOUT"
                    elif u.get("lhs") and not u.get("rhs"):
                        direction = "OUT"
                    elif u.get("rhs"):
                        direction = "IN"
                    names = [pname]
                    for member_name in sorted(list(u.get("members") or [])):
                        if member_name not in names:
                            names.append(member_name)
                    index_vals: List[str] = []
                    for idx_expr in u.get("indexes") or []:
                        norm, _ = _normalize_bracket_expr(str(idx_expr), macro_value_map)
                        if norm:
                            index_vals.append(norm)
                    index_vals = list(dict.fromkeys(index_vals))
                    pointer_range = "*" in ptype or "*" in p
                    for disp_name in names:
                        display = _format_param_entry(
                            disp_name,
                            ptype,
                            array_part,
                            index_vals,
                            macro_value_map,
                            pointer_range,
                            bool(u.get("divisor")),
                        )
                        if direction in {"IN", "INOUT"}:
                            inputs_list.append(f"[{direction}] {display}")
                        if direction in {"OUT", "INOUT"}:
                            outputs_list.append(f"[{direction}] {display}")
                for gname, u in global_usage.items():
                    if not u.get("lhs") and not u.get("rhs") and not u.get("inout"):
                        continue
                    direction = "INOUT" if u.get("inout") or (u.get("lhs") and u.get("rhs")) else "OUT" if u.get("lhs") else "IN"
                    names = [gname]
                    for member_name in sorted(list(u.get("members") or [])):
                        if member_name not in names:
                            names.append(member_name)
                    index_vals: List[str] = []
                    for idx_expr in u.get("indexes") or []:
                        norm, _ = _normalize_bracket_expr(str(idx_expr), macro_value_map)
                        if norm:
                            index_vals.append(norm)
                    index_vals = list(dict.fromkeys(index_vals))
                    # 선언 배열 차원. 정본은 배열을 원소 단위로 펼쳐 적으므로
                    # (입력 엔트리의 50.3%) 소비처가 개수를 알아야 한다.
                    # ⚠ **base 이름에만** 붙인다 — 멤버 경로(`s.f`)나 확장형
                    #   (`_PTT.Bits.PTT3`)은 배열이 아니라 그 배열의 한 칸/필드다.
                    _g_array = str((globals_info_map.get(gname) or {}).get("array") or "").strip()
                    for disp_name in names:
                        display = _format_param_entry(
                            disp_name,
                            "",
                            "",
                            index_vals,
                            macro_value_map,
                            False,
                            bool(u.get("divisor")),
                            size_hint=_g_array if disp_name == gname else "",
                        )
                        entry = f"[{direction}] {display}"
                        if _is_static_var(gname, static_name_map):
                            globals_static.append(entry)
                        else:
                            globals_global.append(entry)
            else:
                if isinstance(used_globals, list):
                    call_set = set([str(c).strip() for c in calls] if isinstance(calls, list) else [])
                    for g in used_globals:
                        gname = str(g).strip()
                        if not gname or gname in call_set:
                            continue
                        used_globals_list.append(gname)
                globals_static = [g for g in used_globals_list if _is_static_var(g, static_name_map)]
                globals_global = [g for g in used_globals_list if not _is_static_var(g, static_name_map)]
                inputs_list = _parse_signature_params(signature, tag_direction=True)
                outputs_list = _parse_signature_outputs(signature, name)
            if body_text:
                local_static_set = set(g.strip() for g in globals_static)
                for ls_name in _extract_local_static_candidates(body_text):
                    if ls_name and ls_name not in local_static_set:
                        globals_static.append(ls_name)
                        local_static_set.add(ls_name)
            return_type = _extract_return_type(signature, name)
            if returns_value(return_type):
                m = re.search(r"\b(U8|U16|U32|S8|S16|S32)\b", return_type)
                base = m.group(1) if m else return_type.split()[-1]
                range_text = DEFAULT_TYPE_RANGES.get(base, "")
                return_entry = (
                    f"[OUT] return {return_type} (range: {range_text})"
                    if range_text
                    else f"[OUT] return {return_type}"
                )
                outputs_list = [return_entry] + outputs_list
            called_list = [str(c).strip() for c in calls if str(c).strip()] if isinstance(calls, list) else []
            called_sig_lines: List[str] = []
            for callee in called_list:
                sig = callee_signature_map.get(callee, "")
                if sig:
                    called_sig_lines.append(sig)
                else:
                    called_sig_lines.append(callee)
            called_text = "\n".join(called_sig_lines)
            desc_text = _enhance_description_text(
                name,
                comment_desc or _fallback_function_description(name, called_list),
                called_list,
            )
            if _is_generic_description(desc_text):
                module_hint = Path(file_path).stem if file_path else ""
                desc_text = _enhance_function_description(name, called_list, module_hint)
            true_calls, false_calls = _extract_condition_branch_calls(body_text)
            term_return, term_error = _extract_logic_terminal_paths(body_text)
            if name.lower() == "main" and called_list:
                init_first = called_list[0]
                follow_calls = ", ".join(called_list[1:6]) if len(called_list) > 1 else ""
                if follow_calls:
                    desc_text = (
                        f"Power-on 시 {init_first}를 호출해 시스템을 초기화하고, 이후 {follow_calls}를 순차 호출한다."
                    )
                else:
                    desc_text = f"Power-on 시 {init_first}를 호출해 시스템을 초기화한다."
            system_os_rules = {
                "s_sysmain_init": "시스템 초기 진입 시 주요 상태 변수/타이머를 초기화한다.",
                "s_systemoperation": "주기적으로 시스템 운전 상태를 갱신하고 동작 조건을 점검한다.",
                "s_systemdiagnosis": "진단 상태를 평가하고 오류 플래그를 갱신한다.",
                "s_systemmanagement": "시스템 상태 전이를 관리하고 운영 플래그를 유지한다.",
                "s_sysctrl_errorprotection": "오류 보호 로직을 수행하여 위험 상태를 차단한다.",
                "g_sysctrl_errorprotection": "오류 보호 로직을 수행하여 위험 상태를 차단한다.",
            }
            rkey = name.lower()
            if (not comment_desc) and rkey in system_os_rules:
                chain = ", ".join(called_list[:4]) if called_list else ""
                desc_text = system_os_rules[rkey]
                if chain:
                    desc_text = f"{desc_text} 호출 체인: {chain}."
            inferred_precond = comment_precond
            if not inferred_precond and body_text:
                inferred_precond = _infer_precondition_from_body(body_text, name)
            detail = {
                "id": fn_id,
                "name": name,
                "prototype": signature,
                "description": desc_text,
                "asil": comment_asil or (_func_override.get(name, {}).get("asil") if _func_override.get(name) else "") or _sds_map.get(name.lower(), {}).get("asil") or "TBD",
                "related": comment_related or (_func_override.get(name, {}).get("related") if _func_override.get(name) else "") or _lookup_sds_related(name, module_name) or "TBD",
                "description_source": "comment" if comment_desc else "inference",
                "asil_source": "comment" if comment_asil else ("sds" if _sds_map.get(name.lower(), {}).get("asil") else "inference"),
                "related_source": "comment" if comment_related else ("sds" if _lookup_sds_related(name, module_name) else "inference"),
                "inputs": inputs_list,
                "outputs": outputs_list,
                "precondition": inferred_precond,
                "file": str(file_path) if file_path else "",
                "module_name": Path(file_path).stem if file_path else "",
                "comment_description": comment_desc,
                "comment_asil": comment_asil,
                "comment_related": comment_related,
                "globals_global": globals_global,
                "globals_static": globals_static,
                "called": called_text,
                "calls_list": called_list,
                "logic_condition": _extract_primary_condition(body_text),
                "logic_true_calls": true_calls,
                "logic_false_calls": false_calls,
                "logic_return_path": term_return,
                "logic_error_path": term_error,
                "logic_flow": _extract_logic_flow(body_text, called_list),
                "logic": "Auto(call tree)" if called_list else "",
            }
            function_details[fn_id] = detail
            if body_text:
                function_body_snippets[fn_id] = body_text[:_BODY_SNIPPET_MAX]
            _put_by_name(function_details_by_name, name, detail, function_collisions)
        # Fallback: AST에서 누락된 함수도 병합 (regex 기반 수집분)
        _ast_names = {r[3] for r in function_table_rows if len(r) >= 4}
        if fallback_functions:
            for fn in fallback_functions:
                name = str(fn.get("name") or "").strip()
                if name in _ast_names:
                    continue  # AST에서 이미 수집한 함수는 건너뛰기
                signature = str(fn.get("signature") or name).strip()
                is_static = bool(fn.get("is_static"))
                if is_static and not signature.lstrip().startswith("static "):
                    signature = "static " + signature
                file_path = str(fn.get("file") or "").strip()
                calls = fn.get("calls") or []
                if not name:
                    continue
                if file_path and file_path not in source_text_cache:
                    try:
                        source_text_cache[file_path] = _src_read(file_path)
                    except Exception:
                        source_text_cache[file_path] = ""
                if not isinstance(calls, list):
                    calls = []
                calls = [str(c).strip() for c in calls if str(c).strip()]
                calls, calls_source = _merge_call_candidates(
                    name,
                    file_path,
                    str(fn.get("body") or ""),
                    calls,
                )
                if calls_source:
                    fn["calls_source"] = calls_source
                call_map[name] = [str(c).strip() for c in calls if str(c).strip()]
                module_name = "Module"
                if file_path:
                    try:
                        rel = _src_relbase(file_path).relative_to(root)
                        module_name = rel.parts[0] if rel.parts else "Module"
                    except Exception:
                        module_name = "Module"
                if component_map and file_path:
                    key = Path(file_path).name
                    mapped = component_map.get(key) or component_map.get(Path(file_path).stem)
                    if not mapped or not isinstance(mapped, dict) or not mapped.get("component"):
                        fp_norm = file_path.replace("\\", "/")
                        for cm_key in component_map:
                            if "/" in cm_key and fp_norm.endswith(cm_key):
                                mapped = component_map[cm_key]
                                break
                    if isinstance(mapped, dict) and mapped.get("component"):
                        module_name = str(mapped.get("component"))
                        module_name = _normalize_swcom_label(module_name)
                _ovr = _func_override.get(name)
                if _ovr and isinstance(_ovr, dict) and _ovr.get("swcom") is not None:
                    mod_idx = int(_ovr["swcom"])
                    module_name = f"SwCom_{mod_idx:02d}"
                else:
                    _swcom_m = re.search(r"SwCom[_\s-]*(\d+)", module_name, re.I)
                    if _swcom_m:
                        mod_idx = int(_swcom_m.group(1))
                    else:
                        if module_name not in module_ids:
                            module_ids[module_name] = next_module_idx
                            next_module_idx += 1
                        mod_idx = module_ids.get(module_name, 0)
                module_map[name] = module_name
                # 위와 같은 이유로 SwCom(mod_idx) 단위로 센다 — **두 곳이 같이 움직여야
                # 한다**(한쪽만 고치면 폴백 경로에서 같은 충돌이 그대로 남는다).
                counter = _fn_counter_by_mod.get(mod_idx, 0) + 1
                _fn_counter_by_mod[mod_idx] = counter
                fn_id = f"SwUFn_{mod_idx:02d}{counter:02d}" if counter <= 99 else f"SwUFn_{mod_idx:02d}{counter:03d}"
                fn_type = "Internal" if is_static else "I/F"
                if name.lower().startswith("s_"):
                    fn_type = "Internal"
                elif name.lower().startswith("g_"):
                    fn_type = "I/F"
                function_table_rows.append(
                    [
                        f"SwCom_{mod_idx:02d}",
                        module_name,
                        fn_id,
                        name,
                        fn_type,
                        "",
                    ]
                )
                called_list = [str(c).strip() for c in calls if str(c).strip()] if isinstance(calls, list) else []
                inputs_list = [f"[IN] {p}" for p in _parse_signature_params(signature)]
                outputs_list = _parse_signature_outputs(signature, name)
                desc_text = _enhance_description_text(
                    name,
                    _fallback_function_description(name, called_list),
                    called_list,
                )
                if _is_generic_description(desc_text):
                    module_hint = Path(file_path).stem if file_path else ""
                    desc_text = _enhance_function_description(name, called_list, module_hint)
                body_text = str(fn.get("body") or "")
                global_names = list(globals_info_map.keys())
                global_usage = _collect_var_usage(body_text, global_names) if body_text and global_names else {}
                globals_global: List[str] = []
                globals_static: List[str] = []
                _seen_globals: set = set()
                for gname, gusage in global_usage.items():
                    if not isinstance(gusage, dict):
                        continue
                    if not any(bool(gusage.get(k)) for k in ["lhs", "rhs", "inout", "members", "indexes", "divisor"]):
                        continue
                    is_static_g = bool(static_name_map.get(gname, False))
                    if is_static_g:
                        globals_static.append(gname)
                    else:
                        globals_global.append(gname)
                    _seen_globals.add(gname.lower())
                # 접근자 함수 호출을 통한 간접 globals
                if _accessor_globals_map and called_list:
                    for callee in called_list:
                        callee_lower = callee.strip().lower()
                        accessor_globals = _accessor_globals_map.get(callee_lower, [])
                        for ag in accessor_globals:
                            if ag.lower() not in _seen_globals:
                                is_static_g = bool(static_name_map.get(ag, False))
                                if is_static_g:
                                    globals_static.append(f"[INDIRECT] {ag}")
                                else:
                                    globals_global.append(f"[INDIRECT] {ag}")
                                _seen_globals.add(ag.lower())
                if body_text:
                    local_static_set = set(str(x).strip() for x in globals_static)
                    for ls_name in _extract_local_static_candidates(body_text):
                        if ls_name and ls_name not in local_static_set:
                            globals_static.append(ls_name)
                            local_static_set.add(ls_name)
                true_calls, false_calls = _extract_condition_branch_calls(body_text)
                term_return, term_error = _extract_logic_terminal_paths(body_text)
                detail = {
                    "id": fn_id,
                    "name": name,
                    "prototype": signature,
                    "description": desc_text,
                    "asil": (_func_override.get(name, {}).get("asil") if _func_override.get(name) else "") or _sds_map.get(name.lower(), {}).get("asil") or "TBD",
                    "related": _lookup_sds_related(name, module_name) or "TBD",
                    "description_source": "inference",
                    "asil_source": "sds" if _sds_map.get(name.lower(), {}).get("asil") else "inference",
                    "related_source": "sds" if _lookup_sds_related(name, module_name) else "inference",
                    "inputs": inputs_list,
                    "outputs": outputs_list,
                    "precondition": "N/A",
                    "file": str(file_path) if file_path else "",
                    "module_name": Path(file_path).stem if file_path else "",
                    "comment_description": "",
                    "comment_asil": "",
                    "comment_related": "",
                    "globals_global": globals_global,
                    "globals_static": globals_static,
                    "called": "\n".join(called_list),
                    "calls_list": called_list,
                    "logic_condition": _extract_primary_condition(body_text),
                    "logic_true_calls": true_calls,
                    "logic_false_calls": false_calls,
                    "logic_return_path": term_return,
                    "logic_error_path": term_error,
                    "logic_flow": _extract_logic_flow(body_text, called_list),
                    "logic": "Auto(call tree)" if called_list else "",
                }
                function_details[fn_id] = detail
                if body_text:
                    function_body_snippets[fn_id] = body_text[:_BODY_SNIPPET_MAX]
                _put_by_name(function_details_by_name, name, detail, function_collisions)
        if globals_detailed:
            for g in globals_detailed:
                if not isinstance(g, dict):
                    continue
                gname = str(g.get("name") or "").strip()
                if gname in macro_name_set:
                    continue
                gfile = str(g.get("file") or "").strip()
                gtype = str(g.get("type") or "").strip()
                ginit = str(g.get("init") or "").strip()
                is_static = str(g.get("is_static") or "").strip().lower() == "true"
                if not gname:
                    continue
                if not gtype and gname in globals_info_map:
                    gtype = str(globals_info_map.get(gname, {}).get("type") or "").strip()
                if not gtype and gfile:
                    gtype2, init2 = _infer_type_from_file(gfile, gname)
                    if gtype2:
                        gtype = gtype2
                    if init2 and not ginit:
                        ginit = init2
                if not gtype:
                    continue
                file_suffix = f" [{Path(gfile).name}]" if gfile else ""
                global_data.append(f"{gname}{file_suffix}".strip())
                row = [gname, gtype, "", ginit, ""]
                if is_static:
                    static_vars.append(row)
                else:
                    global_vars.append(row)
        else:
            if globals_info_map:
                for gname, info in globals_info_map.items():
                    gname = str(gname or "").strip()
                    if not gname or gname in macro_name_set:
                        continue
                    gtype = str((info or {}).get("type") or "").strip()
                    gfile = str((info or {}).get("file") or "").strip()
                    ginit = str((info or {}).get("init") or "").strip()
                    is_static = str((info or {}).get("static") or "").strip().lower() == "true"
                    if not gtype:
                        continue
                    file_suffix = f" [{Path(gfile).name}]" if gfile else ""
                    global_data.append(f"{gname}{file_suffix}".strip())
                    row = [gname, gtype, "", ginit, ""]
                    if is_static:
                        static_vars.append(row)
                    else:
                        global_vars.append(row)
            else:
                for g in ast_result.get("globals", []) or []:
                    if not isinstance(g, str):
                        continue
                    if g.strip():
                        if g.strip() in macro_name_set:
                            continue
                        global_data.append(g.strip())

    # 문서 기반 Function 블록 정보로 보강
    if function_blocks:
        for block in function_blocks:
            if not isinstance(block, dict):
                continue
            bid = str(block.get("id") or "").strip()
            bname = str(block.get("name") or "").strip()
            target = None
            if bid and bid in function_details:
                target = function_details.get(bid)
            if target is None and bname:
                target = function_details_by_name.get(bname.lower())
            if not isinstance(target, dict):
                continue
            for key in ["description", "asil", "related", "precondition", "logic"]:
                if not target.get(key) and block.get(key):
                    target[key] = block.get(key)
            if block.get("inputs") and not target.get("inputs"):
                target["inputs"] = block.get("inputs")
            if block.get("outputs") and not target.get("outputs"):
                target["outputs"] = block.get("outputs")
            if block.get("called") and not target.get("called"):
                target["called"] = block.get("called")

    def _unique(items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    # 카테고리 절단 — **무엇을 잘랐는지 남긴다.**
    #
    # ⚠ 아래 11개 축은 오래 조용히 잘렸다. 같은 함수의 전역 축(`_globals_loss`)은
    #   "기록이 없으면 '이 프로젝트엔 원래 없다' 로 오독한다" 는 이유로 손실을 남기는데
    #   카테고리 축만 빠져 있던 **비대칭**이다. 실측(KJPDS02_RD + FBL): 소스의
    #   `#define` 이 12,941개인데 분류 상한은 120 이다 — 준비 게이트가 이 상한을
    #   공시하면서도 "실제로 자르고 있는가" 는 말할 수 없었던 이유가 여기에 있었다.
    _cat_loss: Dict[str, Dict[str, int]] = {}

    def _cap_items(name: str, items: List[Any], cap: int, *, dedupe: bool = True) -> List[Any]:
        vals = _unique(items) if dedupe else list(items)
        total = len(vals)
        if total > cap:
            _cat_loss[name] = {"total": total, "cap": cap, "dropped": total - cap}
        return vals[:cap]

    interfaces = _cap_items("interfaces", interfaces, max_items)
    internals = _cap_items("internals", internals, max_items)
    unknowns = _cap_items("unknowns", unknowns, max_items)
    macros = _cap_items("macros", macros, max_items)
    reqs = _cap_items("reqs", reqs, max_items)
    common_macros = _cap_items("common_macros", common_macros, max_items)
    type_defs = _cap_items("type_defs", type_defs, max_items)
    param_defs = _cap_items("param_defs", param_defs, max_items)
    version_defs = _cap_items("version_defs", version_defs, max_items)
    global_data = _cap_items("global_data", global_data, max_items * 2)
    # ⚠ 원본이 여기만 `_unique` 를 거치지 않았다 — 동작을 바꾸지 않고 셈만 붙인다.
    macro_defs = _cap_items("macro_defs", macro_defs, max_items * 2, dedupe=False)
    if _cat_loss:
        # 전역 축과 같은 등급으로 올린다. 이게 없으면 규격서에서 빠진 항목이 어디에도
        # 안 남아 "원래 그만큼뿐" 으로 읽힌다.
        _logger.warning(
            "UDS 카테고리 상한(max_items=%d)에 걸려 %s",
            max_items,
            " · ".join(f"{k} {v['total']}→{v['cap']}(-{v['dropped']})"
                       for k, v in sorted(_cat_loss.items())),
        )
    if param_defs:
        for row in param_defs:
            cols = _normalize_table_row(row)
            if len(cols) >= 3:
                calibration_params.append([cols[0], cols[1], cols[2], cols[3] if len(cols) > 3 else ""])

    type_range_map: Dict[str, str] = {}
    for row in type_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            rng = str(cols[2]).strip()
            if not rng or rng.upper() in {"-", "N/A"}:
                continue
            type_range_map[cols[0]] = rng
            type_range_map[cols[1]] = rng
    default_type_ranges = {
        "U8": "0 ~ 255",
        "U16": "0 ~ 65535",
        "U32": "0 ~ 4294967295",
        "S8": "-128 ~ 127",
        "S16": "-32768 ~ 32767",
        "S32": "-2147483648 ~ 2147483647",
    }
    if not type_range_map:
        type_range_map = dict(default_type_ranges)
    param_range_map: Dict[str, str] = {}
    for row in param_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            param_range_map[cols[0]] = cols[2]
    macro_value_map: Dict[str, str] = {}
    for row in macro_defs:
        if len(row) >= 3:
            macro_value_map[str(row[0]).strip()] = str(row[2]).strip()
    for row in common_macros:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            macro_value_map[str(cols[0]).strip()] = str(cols[2]).strip()
    macro_range_map: Dict[str, str] = {}
    for m_name in macro_value_map.keys():
        m = re.match(r"(.+)_MIN$", m_name)
        if m:
            base = m.group(1)
            max_key = f"{base}_MAX"
            if max_key in macro_value_map:
                macro_range_map[base] = f"{macro_value_map[m_name]} ~ {macro_value_map[max_key]}"
    for gname, info in globals_info_map.items():
        source = str(info.get("range_source") or "").strip().lower()
        if source == "comment":
            continue
        current = str(info.get("range") or "").strip()
        init = str(info.get("init") or "").strip()
        resolved = ""
        if init and init in macro_value_map:
            base = init.replace("_MIN", "").replace("_MAX", "")
            if base in macro_range_map:
                resolved = macro_range_map[base]
            if not resolved and init in macro_value_map:
                resolved = macro_value_map.get(init, "")
        if not resolved and gname in param_range_map:
            resolved = param_range_map[gname]
        if not resolved:
            gtype = info.get("type") or ""
            if gtype in type_range_map:
                resolved = type_range_map[gtype]
            if not resolved and gtype in default_type_ranges:
                resolved = default_type_ranges[gtype]
        if not resolved and init:
            resolved = init
        if not resolved and current:
            resolved = current
        if resolved:
            info["range"] = resolved

    if globals_info_map:
        new_global_vars: List[List[str]] = []
        new_static_vars: List[List[str]] = []
        # fallback from global/static rows if info_map missing fields
        for row in global_vars + static_vars:
            if not row:
                continue
            name = str(row[0] or "").strip()
            if not name:
                continue
            info = globals_info_map.setdefault(name, {})
            if len(row) > 1 and not info.get("type"):
                info["type"] = str(row[1] or "").strip()
            if len(row) > 2 and not info.get("range"):
                info["range"] = str(row[2] or "").strip()
            if len(row) > 3 and not info.get("init"):
                info["init"] = str(row[3] or "").strip()
        for name, info in globals_info_map.items():
            if not str(info.get("type") or "").strip():
                continue
            row = [
                name,
                info.get("type") or "",
                info.get("range") or "",
                info.get("init") or "",
                "",
            ]
            if info.get("static") == "true":
                new_static_vars.append(row)
            else:
                new_global_vars.append(row)
        if new_global_vars:
            global_vars = new_global_vars
        if new_static_vars:
            static_vars = new_static_vars

    top_sorted = sorted(top_dirs.items(), key=lambda x: (-x[1], x[0]))
    top_list = ", ".join([k for k, _ in top_sorted[:5]]) if top_sorted else "N/A"
    file_count = len(files)

    ext_summary = ", ".join([f"{k}:{v}" for k, v in sorted(ext_counts.items())]) or "N/A"
    overview_lines = [
        f"Source root: {root}",
        f"Files scanned: {file_count} ({ext_summary})",
        f"Top modules: {top_list}",
        f"Public interfaces: {len(interfaces)}, Internal functions: {len(internals)}, Global data: {len(global_data)}",
    ]
    if truncated:
        # ⚠ 오래 `400` 이 하드코딩돼 있었다. 실제 상한은 `UDS_MAX_SOURCE_FILES`(기본
        #   1200, `DEVOPS_UDS_MAX_FILES` 로 덮임)라 어느 경우에도 맞지 않았고, 바로 위
        #   `Files scanned: {file_count}` 와 **인접한 두 줄이 다른 수**를 말했다.
        overview_lines.append(f"Scan truncated to first {max_files} files.")

    requirements_lines: List[str] = []
    for row in common_macros:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            requirements_lines.append(
                f"Common Macro: {cols[0]} ({cols[1]}={cols[2]})"
            )
    for row in type_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            requirements_lines.append(
                f"Type Definition: {cols[1]} = {cols[0]} ({cols[2]})"
            )
    for row in param_defs:
        cols = _normalize_table_row(row)
        if len(cols) >= 3:
            requirements_lines.append(
                f"Parameter: {cols[0]} ({cols[1]}={cols[2]})"
            )
    if version_defs:
        versions = []
        for row in version_defs:
            cols = _normalize_table_row(row)
            if len(cols) >= 2:
                versions.append(f"{cols[0]}={cols[1]}")
        if versions:
            requirements_lines.append(f"Version Information: {', '.join(versions)}")
    for req in reqs:
        requirements_lines.append(f"Requirement: {req}")
    if not requirements_lines:
        requirements_lines = [
            "Source-only draft. Verify against requirements and safety goals.",
            "Derive test cases from public interfaces and internal flows.",
            "Update with system-level requirements when available.",
        ]

    if function_blocks:
        for block in function_blocks[:max_items]:
            name = block.get("name") or block.get("id") or "UnknownFunction"
            desc = block.get("description") or "Description TBD"
            proto = block.get("prototype") or "Prototype TBD"
            asil = block.get("asil") or "TBD"
            line = f"Function Spec: {name} {proto} - {desc} (ASIL {asil})"
            requirements_lines.append(line)

    interfaces_lines = interfaces or ["N/A"]

    from report.constants import UDS_DID_PATTERNS, UDS_SERVICE_ID_PATTERNS, UDS_SERVICE_TABLE
    did_entries: List[str] = []
    service_entries: List[str] = []
    did_function_map: Dict[str, List[str]] = {}
    _did_pats = [re.compile(p, re.I) for p in UDS_DID_PATTERNS]
    _sid_pats = [re.compile(p, re.I) for p in UDS_SERVICE_ID_PATTERNS]
    for fn in (ast_result.get("functions", []) if parse_c_project is not None else fallback_functions):
        fn_name = str(fn.get("name") or "").strip()
        fn_body = str(fn.get("body") or "").strip()
        if not fn_name or not fn_body:
            continue
        for pat in _did_pats:
            for dm in pat.finditer(fn_body):
                did_val = dm.group(0).strip()
                if did_val and did_val not in did_entries:
                    did_entries.append(did_val)
                did_function_map.setdefault(did_val, [])
                if fn_name not in did_function_map[did_val]:
                    did_function_map[did_val].append(fn_name)
        for pat in _sid_pats:
            for sm in pat.finditer(fn_body):
                sid_raw = sm.group(0).strip()
                if sid_raw.startswith("0x") or sid_raw.startswith("0X"):
                    try:
                        sid_int = int(sid_raw, 16)
                        svc_name = UDS_SERVICE_TABLE.get(sid_int, "")
                        entry = f"0x{sid_int:02X} {svc_name} -> {fn_name}" if svc_name else f"{sid_raw} -> {fn_name}"
                    except ValueError:
                        entry = f"{sid_raw} -> {fn_name}"
                else:
                    entry = f"{sid_raw} -> {fn_name}"
                if entry not in service_entries:
                    service_entries.append(entry)

    frames_lines: List[str] = []
    if did_entries:
        frames_lines.append("=== DID Definitions ===")
        for d in did_entries[:40]:
            handlers = did_function_map.get(d, [])
            handler_str = f" (handlers: {', '.join(handlers[:5])})" if handlers else ""
            frames_lines.append(f"  {d}{handler_str}")
    if service_entries:
        frames_lines.append("=== UDS Service Mappings ===")
        frames_lines.extend(f"  {s}" for s in service_entries[:40])
    if not frames_lines:
        frames_lines = internals or ["N/A"]
    else:
        if internals:
            frames_lines.append("=== Internal Functions ===")
            frames_lines.extend(internals[:30])

    notes_lines = [
        "Generated from source-only scan.",
        "Function list is heuristic; review for accuracy.",
    ]
    if unknowns:
        notes_lines.append(f"Unclassified functions: {len(unknowns)}")
    if function_blocks:
        logic_count = sum(1 for b in function_blocks if b.get("logic") == "present")
        if logic_count:
            notes_lines.append(f"Logic diagram referenced: {logic_count} items")
    if not doc_texts:
        notes_lines.append("No artifact text docs found; fallback rules applied.")

    detail_lines: List[str] = []
    detail_lines.append("Software Unit Design")
    detail_lines.append("1. Common Macro Definition")
    detail_lines.extend(common_macros or ["N/A"])
    detail_lines.append("")
    detail_lines.append("2. Type Definition")
    detail_lines.extend(type_defs or ["N/A"])
    detail_lines.append("")
    detail_lines.append("3. Parameter Definition")
    detail_lines.extend(param_defs or ["N/A"])
    detail_lines.append("")
    detail_lines.append("4. Version Information")
    detail_lines.extend(version_defs or ["N/A"])
    detail_lines.append("")
    # 템플릿 기반 문서는 별도 섹션/표로 렌더링되므로 중복 나열을 피한다.
    max_blocks = 120
    if function_blocks:
        detail_lines.append("6. Function Information")
        grouped = _group_function_blocks_by_swcom(function_blocks)
        total_added = 0
        for swcom in sorted(grouped.keys()):
            detail_lines.append("")
            detail_lines.append(swcom)
            for block in grouped[swcom]:
                if total_added >= max_blocks:
                    detail_lines.append("[...truncated...]")
                    break
                detail_lines.extend(_format_function_block_lines(block))
                detail_lines.append("")
                total_added += 1
            if total_added >= max_blocks:
                break
    else:
        detail_lines.append("6. Function Information")
        detail_lines.append("N/A")

    # Backfill calling/input/output with normalized call graph and signature parsing.
    reverse_callers: Dict[str, List[str]] = {}
    reverse_callers_compact: Dict[str, List[str]] = {}
    compact_name_to_raw: Dict[str, str] = {}
    if isinstance(call_map, dict):
        for caller_name, callee_list in call_map.items():
            caller_norm = _normalize_symbol_name(str(caller_name or "")).lower()
            caller_comp = re.sub(r"[^a-z0-9]", "", caller_norm)
            if not caller_norm or not isinstance(callee_list, list):
                continue
            if caller_comp and caller_name:
                compact_name_to_raw.setdefault(caller_comp, str(caller_name).strip())
            for callee_name in callee_list:
                callee_norm = _normalize_symbol_name(str(callee_name or "")).lower()
                callee_comp = re.sub(r"[^a-z0-9]", "", callee_norm)
                if not callee_norm:
                    continue
                reverse_callers.setdefault(callee_norm, []).append(caller_norm)
                if callee_comp:
                    reverse_callers_compact.setdefault(callee_comp, []).append(caller_norm)
    for _, vals in list(reverse_callers.items()):
        seen_callers: List[str] = []
        for v in vals:
            if v and v not in seen_callers:
                seen_callers.append(v)
        vals[:] = seen_callers
    for _, vals in list(reverse_callers_compact.items()):
        seen_callers: List[str] = []
        for v in vals:
            if v and v not in seen_callers:
                seen_callers.append(v)
        vals[:] = seen_callers

    def _has_values(v: Any) -> bool:
        if isinstance(v, list):
            return any(str(x).strip() and str(x).strip().upper() not in {"N/A", "TBD", "-"} for x in v)
        text = str(v or "").strip()
        return bool(text) and text.upper() not in {"N/A", "TBD", "-"}

    calling_map: Dict[str, List[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            callee_lower = callee.lower() if callee else ""
            if callee_lower:
                calling_map.setdefault(callee_lower, [])
                if caller not in calling_map[callee_lower]:
                    calling_map[callee_lower].append(caller)

    def _call_edges(name: str) -> List[str]:
        if not name:
            return []
        vals = call_map.get(name)
        if vals is None:
            vals = call_map.get(name.lower(), [])
        return list(vals or [])

    def _get_2hop_calls(fn_name: str) -> List[str]:
        direct = _call_edges(fn_name)
        indirect: List[str] = []
        for d in direct:
            for hop2 in _call_edges(d):
                if hop2 not in direct and hop2 != fn_name and hop2 not in indirect:
                    indirect.append(hop2)
        return indirect

    def _get_2hop_callers(fn_name: str) -> List[str]:
        direct = calling_map.get(fn_name.lower(), [])
        indirect: List[str] = []
        for d in direct:
            for hop2 in calling_map.get(d.lower(), []):
                if hop2 not in direct and hop2 != fn_name and hop2 not in indirect:
                    indirect.append(hop2)
        return indirect

    def _entry_var_name(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        m = re.match(r"^\[(?:IN|OUT|INOUT|INDIRECT|INDIRECT2)\]\s+(.+)", text)
        if m:
            return m.group(1).split("|")[0].strip()
        return text.split("|")[0].strip()

    def _has_direct_globals(info: Dict[str, Any]) -> bool:
        for key in ("globals_global", "globals_static"):
            for item in info.get(key) or []:
                text = str(item or "").strip()
                if not text or text.upper() in {"N/A", "-"}:
                    continue
                if text.startswith("[INDIRECT"):
                    continue
                return True
        return False

    def _module_name_for(info: Dict[str, Any]) -> str:
        fname = str(info.get("name") or "").strip()
        return str(module_map.get(fname) or info.get("module_name") or "").strip()

    def _should_propagate_2hop(caller_info: Dict[str, Any], bridge_info: Dict[str, Any], leaf_info: Dict[str, Any]) -> bool:
        caller_module = _module_name_for(caller_info)
        bridge_module = _module_name_for(bridge_info)
        leaf_module = _module_name_for(leaf_info)
        if not caller_module or caller_module != bridge_module or caller_module != leaf_module:
            return False
        bridge_calls = bridge_info.get("calls_list") or []
        if len(bridge_calls) > 5:
            return False
        if not _has_direct_globals(leaf_info):
            return False
        return True

    for _, info in list(function_details.items()):
        if not isinstance(info, dict):
            continue
        fn_name = _normalize_symbol_name(str(info.get("name") or "")).lower()
        proto = str(info.get("prototype") or "").strip()
        if not _has_values(info.get("inputs")) and proto:
            info["inputs"] = _parse_signature_params(proto)
        if not _has_values(info.get("outputs")) and proto:
            info["outputs"] = _parse_signature_outputs(proto, str(info.get("name") or ""))
        if (not str(info.get("calling") or "").strip()) or str(info.get("calling") or "").strip().upper() in {"N/A", "TBD", "-"}:
            callers = list(reverse_callers.get(fn_name, []))
            fn_comp = re.sub(r"[^a-z0-9]", "", fn_name)
            callers += list(reverse_callers_compact.get(fn_comp, []))
            if callers:
                normalized_names: List[str] = []
                for c in callers:
                    ck = re.sub(r"[^a-z0-9]", "", str(c or "").lower())
                    normalized_names.append(compact_name_to_raw.get(ck, c))
                dedup = list(dict.fromkeys([str(x).strip() for x in normalized_names if str(x).strip()]))
                info["calling"] = "\n".join(dedup)
            else:
                info["calling"] = "N/A"
        hop2_called = _get_2hop_calls(fn_name) if fn_name else []
        hop2_callers = _get_2hop_callers(fn_name) if fn_name else []
        if hop2_called:
            info["called_indirect"] = hop2_called[:20]
        if hop2_callers:
            info["calling_indirect"] = hop2_callers[:20]
        if fn_name:
            # ⚠ 직접 대입하면 위에서 기록한 충돌 정보가 아니라 **등록 순서**만 바뀌지만,
            # 이 루프는 두 사본을 모두 순회하므로 충돌 기록을 계속 갱신해야 한다.
            _put_by_name(function_details_by_name, fn_name, info, function_collisions)

    # ── 간접 Globals 추적: same-module direct/2-hop globals를 제한적으로 caller에 전파 ──
    if call_map and function_details_by_name:
        _indirect_propagated = 0
        for caller_name, callee_list in call_map.items():
            caller_info = function_details_by_name.get(caller_name.lower())
            if not isinstance(caller_info, dict):
                continue
            caller_gg = caller_info.get("globals_global") or []
            caller_gs = caller_info.get("globals_static") or []
            if not isinstance(caller_gg, list):
                caller_gg = []
            if not isinstance(caller_gs, list):
                caller_gs = []
            existing_gg_names = set()
            for g in caller_gg:
                gs = str(g or "").strip()
                vname = _entry_var_name(gs)
                if vname:
                    existing_gg_names.add(vname.lower())
            existing_gs_names = set()
            for g in caller_gs:
                gs = str(g or "").strip()
                vname = _entry_var_name(gs)
                if vname:
                    existing_gs_names.add(vname.lower())
            added = False
            for callee_name in callee_list:
                callee_info = function_details_by_name.get(callee_name.lower())
                if not isinstance(callee_info, dict):
                    continue
                if _module_name_for(caller_info) and _module_name_for(caller_info) != _module_name_for(callee_info):
                    continue
                for g in (callee_info.get("globals_global") or []):
                    gs = str(g or "").strip()
                    if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                        continue
                    var_name = _entry_var_name(gs)
                    if var_name.lower() not in existing_gg_names:
                        caller_gg.append(f"[INDIRECT] {var_name}")
                        existing_gg_names.add(var_name.lower())
                        added = True
                for g in (callee_info.get("globals_static") or []):
                    gs = str(g or "").strip()
                    if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                        continue
                    var_name = _entry_var_name(gs)
                    if var_name.lower() not in existing_gs_names:
                        caller_gs.append(f"[INDIRECT] {var_name}")
                        existing_gs_names.add(var_name.lower())
                        added = True
                for leaf_name in _call_edges(callee_name):
                    leaf_info = function_details_by_name.get(str(leaf_name).lower())
                    if not isinstance(leaf_info, dict):
                        continue
                    if not _should_propagate_2hop(caller_info, callee_info, leaf_info):
                        continue
                    for g in (leaf_info.get("globals_global") or []):
                        gs = str(g or "").strip()
                        if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                            continue
                        var_name = _entry_var_name(gs)
                        if var_name.lower() not in existing_gg_names:
                            caller_gg.append(f"[INDIRECT2] {var_name}")
                            existing_gg_names.add(var_name.lower())
                            added = True
                    for g in (leaf_info.get("globals_static") or []):
                        gs = str(g or "").strip()
                        if not gs or gs.upper() in {"N/A", "-"} or gs.startswith("[INDIRECT"):
                            continue
                        var_name = _entry_var_name(gs)
                        if var_name.lower() not in existing_gs_names:
                            caller_gs.append(f"[INDIRECT2] {var_name}")
                            existing_gs_names.add(var_name.lower())
                            added = True
            if added:
                caller_info["globals_global"] = caller_gg
                caller_info["globals_static"] = caller_gs
                _indirect_propagated += 1
        if _indirect_propagated > 0:
            _logger.info("Indirect globals propagation: %d caller functions updated", _indirect_propagated)
            for fid, info in function_details.items():
                if not isinstance(info, dict):
                    continue
                fname = str(info.get("name") or "").strip().lower()
                src = function_details_by_name.get(fname)
                if isinstance(src, dict):
                    for gk in ("globals_global", "globals_static"):
                        sv = src.get(gk)
                        if isinstance(sv, list) and sv:
                            info[gk] = list(sv)

    return {
        "overview": "\n".join(overview_lines),
        "requirements": "\n".join(requirements_lines),
        "interfaces": "\n".join(interfaces_lines),
        "uds_frames": "\n".join(frames_lines),
        "notes": "\n".join(notes_lines),
        "unit_structure": "\n".join(
            [
                f"Interfaces: {len(interfaces)}",
                f"Internals: {len(internals)}",
                f"Global data: {len(global_data)}",
            ]
        ),
        "global_data": "\n".join(global_data),
        "interface_functions": "\n".join(interfaces),
        "internal_functions": "\n".join(internals),
        "global_vars": global_vars,
        "static_vars": static_vars,
        "macro_defs": macro_defs,
        "calibration_params": calibration_params,
        "function_table_rows": function_table_rows,
        "function_details": function_details,
        "function_details_by_name": function_details_by_name,
        # {fid: body 앞 400자}. detail 밖에 두어 by_name 중복 직렬화를 피한다(위 선언부 주석).
        "function_body_snippets": function_body_snippets,
        # 동일 이름 다중정의(파일 간 충돌) — by_name은 last-wins이므로 이 맵이 없으면 영향분석이
        # 다른 사본의 파일 변경을 놓치고(under-report) 낮은 ASIL로 오판한다. {name: {files, asil}}.
        "function_collisions": function_collisions,
        # 전역 인식에서 **잃은 것**. 스캔 캡·미사용 판정·접두사 필터·타입없음 네 지점이
        # 전부 조용히 자르므로, 이 값이 없으면 "이 프로젝트엔 원래 전역이 없다" 로 오독한다.
        "globals_scan": _globals_loss,
        # 카테고리 절단(인터페이스/내부/매크로/타입…). `globals_scan` 과 같은 규약 —
        # **잘린 것을 남긴다**. 준비 게이트의 `max_items_per_category` 공시가 실제로
        # 무엇을 잘랐는지 이 값으로만 알 수 있다.
        "category_caps": {
            "measured": True,
            "cap": max_items,
            "truncated": _cat_loss,
            "any_truncated": bool(_cat_loss),
        },
        # 파일 스캔 절단. ⚠ `truncated` 는 상한에 닿는 즉시 서고 곧바로 break 하므로
        # **전체 파일 수는 모른다** — 지어내지 않고 "닿았다" 는 사실만 낸다.
        "file_scan": {
            "measured": True,
            "cap": max_files,
            "scanned": len(files),
            "truncated": bool(truncated),
        },
        "call_map": call_map,
        "calling_map": calling_map,
        "module_map": module_map,
        "globals_info_map": globals_info_map,
        # 타입 → {멤버경로: "[8]"} — 접힌 선언 차원만 담는다.
        "struct_member_arrays": struct_member_arrays,
        # 타입 -> {멤버경로: {type, array, bits, desc}} — 멤버 행이 베이스의
        # 레코드를 이지 않게 하는 유일한 출처(`_member_grid_info`).
        "struct_member_types": struct_member_types,
        "common_macros": common_macros,
        "type_defs": type_defs,
        "param_defs": param_defs,
        "version_defs": version_defs,
        "software_unit_design": "\n".join(detail_lines).strip(),
        "did_function_map": did_function_map,
        "did_entries": did_entries,
        "service_entries": service_entries,
    }


def generate_uds_preview_markdown(uds_payload: Dict[str, Any]) -> str:
    payload = _safe_dict(uds_payload)
    summary = _safe_dict(payload.get("summary", {}))
    project = payload.get("project_name") or summary.get("project") or summary.get("project_name") or "UDS Spec"
    generated_at = payload.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    ai_sections = payload.get("ai_sections")
    overview = _apply_uds_rules(
        _merge_section_text(payload.get("overview", "") or "", ai_sections, "overview"),
        "overview",
    )
    requirements = _apply_uds_rules(
        _merge_section_text(payload.get("requirements", "") or "", ai_sections, "requirements"),
        "requirements",
    )
    interfaces = _apply_uds_rules(
        _merge_section_text(payload.get("interfaces", "") or "", ai_sections, "interfaces"),
        "interfaces",
    )
    uds_frames = _apply_uds_rules(
        _merge_section_text(payload.get("uds_frames", "") or "", ai_sections, "uds_frames"),
        "uds_frames",
    )
    notes_text = _merge_section_text(
        payload.get("notes", "") or "",
        ai_sections,
        "notes",
        append_base=True,
    )
    evidence_lines = _ai_evidence_lines(ai_sections)
    if evidence_lines:
        notes_text = "\n".join([notes_text, "Evidence:"] + evidence_lines).strip()
    notes = _apply_uds_rules(notes_text, "notes")
    software_unit_design = payload.get("software_unit_design", "") or ""

    detailed_doc = _ai_document_text(ai_sections)
    lines = [
        f"# {project}",
        "",
        f"- Job URL: {payload.get('job_url') or ''}",
        f"- Build: {payload.get('build_number') or ''}",
        f"- Generated at: {generated_at}",
        "",
        "## Overview",
        overview or "- N/A",
        "",
        "## Requirements",
        requirements or "- N/A",
        "",
        "## Interfaces",
        interfaces or "- N/A",
        "",
        "## UDS Frames",
        uds_frames or "- N/A",
        "",
        "## Notes",
        notes or "- N/A",
        "",
        "## Software Unit Design",
        software_unit_design or "- N/A",
        "",
    ]
    if detailed_doc:
        lines += ["## Detailed UDS", detailed_doc, ""]
    return "\n".join(lines).rstrip() + "\n"


def generate_uds_preview_html(uds_payload: Dict[str, Any]) -> str:
    payload = _safe_dict(uds_payload)
    summary = _safe_dict(payload.get("summary", {}))
    project = payload.get("project_name") or summary.get("project") or summary.get("project_name") or "UDS Spec"
    generated_at = payload.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    ai_sections = payload.get("ai_sections")
    overview = _apply_uds_rules(
        _merge_section_text(payload.get("overview", "") or "", ai_sections, "overview"),
        "overview",
    )
    requirements = _apply_uds_rules(
        _merge_section_text(payload.get("requirements", "") or "", ai_sections, "requirements"),
        "requirements",
    )
    interfaces = _apply_uds_rules(
        _merge_section_text(payload.get("interfaces", "") or "", ai_sections, "interfaces"),
        "interfaces",
    )
    uds_frames = _apply_uds_rules(
        _merge_section_text(payload.get("uds_frames", "") or "", ai_sections, "uds_frames"),
        "uds_frames",
    )
    notes_text = _merge_section_text(
        payload.get("notes", "") or "",
        ai_sections,
        "notes",
        append_base=True,
    )
    evidence_lines = _ai_evidence_lines(ai_sections)
    if evidence_lines:
        notes_text = "\n".join([notes_text, "Evidence:"] + evidence_lines).strip()
    notes = _apply_uds_rules(notes_text, "notes")
    detailed_doc = _ai_document_text(ai_sections)
    software_unit_design = payload.get("software_unit_design", "") or ""

    project_html = escape(str(project))
    job_url_html = escape(str(payload.get("job_url") or ""))
    build_html = escape(str(payload.get("build_number") or ""))
    generated_html = escape(str(generated_at))

    logic_items = payload.get("logic_diagrams")
    logic_items = _merge_logic_ai_items(logic_items, ai_sections)
    logic_html = (
        _uds_logic_html(logic_items) if isinstance(logic_items, list) else "<p>N/A</p>"
    )

    return "\n".join(
        [
            "<div class=\"uds-doc\">",
            f"<h2>{project_html}</h2>",
            "<ul>",
            f"<li><strong>Job URL:</strong> {job_url_html}</li>",
            f"<li><strong>Build:</strong> {build_html}</li>",
            f"<li><strong>Generated at:</strong> {generated_html}</li>",
            "</ul>",
            "<h3>Overview</h3>",
            _uds_lines_to_html(overview),
            "<h3>Requirements</h3>",
            _uds_lines_to_html(requirements),
            "<h3>Interfaces</h3>",
            _uds_lines_to_html(interfaces),
            "<h3>UDS Frames</h3>",
            _uds_lines_to_html(uds_frames),
            "<h3>Notes</h3>",
            _uds_lines_to_html(notes),
            "<h3>Detailed UDS</h3>",
            f"<pre>{escape(detailed_doc) if detailed_doc else 'N/A'}</pre>",
            "<h3>Logic Diagrams</h3>",
            logic_html,
            "<h3>Software Unit Design</h3>",
            "<pre>" + escape(software_unit_design or "N/A") + "</pre>",
            "</div>",
        ]
    )
