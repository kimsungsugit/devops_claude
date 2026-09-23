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
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402
from html import escape  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Set, Tuple  # noqa: E402

from report.constants import (  # noqa: E402
    DEFAULT_TYPE_RANGES,
)
from report_gen.c_reset import (  # noqa: E402 (import 블록 전체가 상수 뒤에 온다)
    collect_reset_assignments,
    placed_global_names,
    resolve_reset,
)
from report_gen.c_return import returns_value  # noqa: E402 (import 블록 전체가 상수 뒤에 온다)
from report_gen.function_analyzer import (  # noqa: E402
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
    _normalize_dims,
    _normalize_symbol_name,
    _observed_index_values,
    _parse_signature_outputs,
    _parse_signature_params,
    _split_param,
)
from report_gen.provenance import has_evidence_value, unrecorded_source  # noqa: E402
from report_gen.requirements import (  # noqa: E402
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
from report_gen.source_parser import (  # noqa: E402
    _SRC_READ_MAX_BYTES,
    _decl_array_dim,
    _definition_order,
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
    _norm_def_axis,
    _read_source_text,
    _read_text_limited,
    _scan_source_comment_patterns,
    _short_def_path,
    _strip_c_comments,
    extract_enum_domains,
    extract_header_function_docs,
    extract_struct_member_arrays,
    extract_struct_member_types,
    extract_typedef_aliases,
    is_const_type,
    pick_header_doc,
    pick_header_prototype,
)
from report_gen.source_roots import split_source_roots  # noqa: E402
from report_gen.uds_text import (  # noqa: E402
    _ai_document_text,
    _ai_evidence_lines,
    _apply_uds_rules,
    _merge_logic_ai_items,
    _merge_section_text,
    _uds_lines_to_html,
    _uds_logic_html,
)
from report_gen.utils import (  # noqa: E402
    _extract_simple_call_names,
    _infer_type_from_decl,
    _infer_type_from_file,
    _normalize_swcom_label,
    _safe_dict,
    function_name_key,
    normalize_prototype_text,
)
from report_gen.validation_labels import (  # noqa: E402
    CALL_ROW_LABEL_TO_KEY,
    LABEL_CALLED_FUNCTION,
    LABEL_CALLING_FUNCTION,
)
from workflow.code_parser.c_parser import (  # noqa: E402 (이 파일 import 블록 전체가 상수 뒤에 온다)
    blank_dead_code,
    c_identifiers,
)

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
                # 문서 라벨을 그대로 되비춘다("Called: …" = 정본 관례로 호출자). 라벨 리터럴은 `validation_labels` 단일 출처.
                called = _collect_section_lines(lines, LABEL_CALLED_FUNCTION)
                calling = _collect_section_lines(lines, LABEL_CALLING_FUNCTION)
                parts: List[str] = []
                if called:
                    parts.append("Called(호출자): " + ", ".join(called[:12]))     # (리뷰 I3) 방향을 한 단어로
                if calling:
                    parts.append("Calling(피호출자): " + ", ".join(calling[:12]))
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


# (R68 N72) 소스 단계의 ASIL·Related 출처 라벨. 값 사슬은 2026-04-09(`0b7e1979`) 이래 comment > override > SDS > TBD 인데
#   라벨은 comment > SDS > `inference` 만 알았다 — override 가 준 값(실측 KJPDS02 228건 · PDS64 255건)과 값이 없는 TBD
#   (KJPDS02 918건)가 전부 "추론" 으로 찍혔다. 라벨은 **값을 준 단계**가 단다. `override` 는 저장소의 정본 역추출 스냅샷
#   (`docs/uds_function_swcom_override.json`, 함수 이름 키 — 프로젝트 확인 없음)이라 약한 출처(0.60, `inference` 와 같은
#   점수)로 등록한다: 값과 덮어쓰기 규칙은 그대로고 라벨만 사실이 된다. 프로젝트 귀속은 P7 결정 축(계획서).
# (R70 N84) 두 루프(AST · 텍스트 폴백)가 **같은 사슬**을 쓴다. R68 까지 폴백 루프의 Related 사슬에만 override 가 없어
#   같은 함수가 어느 루프로 가느냐(tree-sitter 가 읽었는가)에 따라 Related 가 달라질 수 있었다 — 라이브 두 루트
#   (KJPDS02 229 · PDS64 256, override 이름 전부 AST 루프)에선 값 변화 0 이지만 규칙이 둘이면 한쪽만 고쳐진다.
_OVERRIDE_SOURCE = "override"


def _source_stage_provenance(
    *,
    comment_asil: Any,
    comment_related: Any,
    override: Any,
    sds_asil: Any,
    sds_related: Any,
) -> Tuple[str, str, str, str]:
    """(asil, asil_source, related, related_source) — 값을 준 단계가 라벨을 단다.

    사슬은 ASIL·Related 둘 다 comment > override > SDS > TBD 하나뿐이다(AST 루프와 텍스트 폴백 루프 공용).
    값이 없으면(`TBD`) 근거도 없다 — `unrecorded_source` 규약대로 `default`(0.30)이지 `inference` 가 아니다.
    """
    ovr = override if isinstance(override, dict) else {}

    def _pick(comment: Any, ovr_val: Any, sds_val: Any) -> Tuple[str, str]:
        # (R76 N86) 실값 판정은 `has_evidence_value` — 예전 truthiness 는 `N/A`·`-`·`none` 같은 **자리표시자 문자열**을
        #   실값으로 봐서, 앞 단계의 자리표시자가 뒤 단계의 실값(SwDS 의 `A`)을 가리고 라벨은 `comment`/`sds` 로 찍혔다.
        #   하류(`validation._score_for` 쪽 `has_evidence_value`)는 같은 값을 "값 없음" 으로 읽어 payload 라벨과 갈렸다.
        for val, src in ((comment, "comment"), (ovr_val, _OVERRIDE_SOURCE), (sds_val, "sds")):
            if has_evidence_value(val):
                return str(val), src
        return "TBD", unrecorded_source("TBD")

    asil, asil_src = _pick(comment_asil, ovr.get("asil"), sds_asil)
    related, related_src = _pick(comment_related, ovr.get("related"), sds_related)
    return asil, asil_src, related, related_src


_PARAM_TAG_RE = re.compile(r"^\s*\[(?:IN|OUT|INOUT)\]\s*", re.I)


def _annotate_typedef_bases(
    globals_info_map: Dict[str, Dict[str, Any]],
    function_details: Dict[str, Dict[str, Any]],
    aliases: Dict[str, str],
    enum_domains: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """(R73 N92) 별칭 타입을 원 선언으로 푼 값을 전역 레코드(`base_type`)와 함수 레코드(`param_base_types`)에 적고,
    enum 타입이면 그 **닫힌 값 집합**(`value_domain` · `param_value_domains`)도 적는다.

    풀린 것만 적는다 — 별칭이 아닌 선언엔 키를 만들지 않는다(없는 키 = 선언 그대로). 반환은 공시용 계수.
    """
    from report_gen.function_analyzer import split_param_annotations
    from report_gen.source_parser import _TYPE_NOISE_RE, apply_c_type_width, infer_c_type_widths
    from report_gen.source_parser import resolve_typedef as _resolve_alias

    widths = infer_c_type_widths(aliases)
    enums = enum_domains or {}
    stats: Dict[str, Any] = {"aliases": len(aliases or {}), "globals_resolved": 0, "params_resolved": 0,
                             "c_type_widths": dict(widths),
                             "enum_types": len({(tuple(v.get("values") or []), tuple(v.get("names") or [])) for v in enums.values()}),
                             "globals_with_enum_domain": 0, "params_with_enum_domain": 0}
    if not aliases and not enums:
        return stats

    def resolve_typedef(decl: str, _aliases: Dict[str, str]) -> str:
        # 별칭을 원 선언까지 푼 뒤, 그 원 선언이 기본 C 타입이면 프로젝트가 증언한 폭으로 읽는다
        # (`U16` 을 거치지 않고 `unsigned int x` 로 바로 적힌 선언도 같은 폭을 받는다).
        return apply_c_type_width(_resolve_alias(decl, _aliases), widths)

    def enum_domain_of(*decls: str) -> Optional[Dict[str, Any]]:
        # 선언 그대로(`enum en_g_DoorState`) · 별칭을 푼 선언 · 마지막 토큰(typedef 별칭 `e_ReProgSequence`) 순으로 찾는다.
        for d in decls:
            core = " ".join(_TYPE_NOISE_RE.sub(" ", str(d or "")).split())
            for key in (core, core.split()[-1] if core else ""):
                if key and key in enums:
                    # 레코드엔 값 집합만 싣는다 — 이름·최소·최대는 payload 루트 `enum_domains[type]` 에 있다(리뷰 W6).
                    return {"kind": "enum", "type": key, "values": list(enums[key]["values"])}
        return None

    for _rec in (globals_info_map or {}).values():
        if not isinstance(_rec, dict):
            continue
        raw = str(_rec.get("type") or "").strip()
        base = resolve_typedef(raw, aliases) if raw else ""
        if base and base != raw:
            _rec["base_type"] = base
            stats["globals_resolved"] += 1
        _dom = enum_domain_of(raw, _resolve_alias(raw, aliases)) if raw else None
        if _dom:
            _rec["value_domain"] = _dom
            stats["globals_with_enum_domain"] += 1
    for info in (function_details or {}).values():
        if not isinstance(info, dict):
            continue
        resolved: Dict[str, str] = {}
        domains: Dict[str, Dict[str, Any]] = {}
        for raw_entry in list(info.get("inputs") or []) + list(info.get("outputs") or []):
            s = split_param_annotations(_PARAM_TAG_RE.sub("", str(raw_entry or "").strip()))[0].strip()
            if not s or re.match(r"^return\b", s, re.I):
                continue
            parts = s.replace("*", " * ").split()
            if len(parts) < 2 or parts[-1] == "*":
                continue
            root = re.split(r"->|\.", parts[-1].strip("*&;,"), maxsplit=1)[0]
            root = re.sub(r"(?:\[[^\]]*\])+$", "", root)
            decl = " ".join(parts[:-1]).strip()
            base = resolve_typedef(decl, aliases)
            if root and base and base != decl and root not in resolved:
                resolved[root] = base
            _pdom = enum_domain_of(decl, _resolve_alias(decl, aliases)) if root else None
            if _pdom and root not in domains:
                domains[root] = _pdom
        if resolved:
            info["param_base_types"] = resolved
            stats["params_resolved"] += len(resolved)
        if domains:
            info["param_value_domains"] = domains
            stats["params_with_enum_domain"] += len(domains)
    return stats


def _header_origin_label(hdr_doc: Dict[str, str]) -> str:
    """`comment_origin` 값. 헤더 여럿이 다른 말을 해 등급만 취한 경우엔 특정 헤더를 지목하지 않는다(리뷰 W4)."""
    file_name = Path(str(hdr_doc.get("file") or "")).name
    return "header:" + file_name if file_name else "header:ambiguous"


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
    if prev is not None and prev is not detail:
        _pf = os.path.normcase(str(prev.get("file") or "").strip())
        _df = os.path.normcase(str(detail.get("file") or "").strip())
        if _pf and _df and _pf != _df:
            # (R57 N54) 교차 파일 쌍둥이 — 이름 하나에 정의 둘. 문서는 정의별로 고르므로(`_pick_function_candidate`)
            #   이 맵은 **첫 정의**를 유지한다(예전에 두 번째 정의를 버리던 때와 같은 기본값 — 영향분석 등 이름 하나만
            #   보는 소비자가 갑자기 다른 파일을 보지 않게).
            return
    by_name[key] = detail  # 동일성 보존(문서 생성의 in-place 갱신 경로 유지)


def _merge_call_map(call_map: Dict[str, List[str]], name: str, calls: Any) -> None:
    """`call_map[name]` 에 피호출자를 **합집합·순서 보존**으로 넣는다. (R57 N54)

    이름 키 하나에 정의가 둘(APP/FBL)일 수 있다 — 덮어쓰면 먼저 온 정의의 피호출자가 사라지고, 그 함수들의
    호출자 행(`callers_map`)에서 이 이름이 빠진다. 문서 표의 피호출자 칸은 정의별 `calls_list` 를 쓰므로 섞이지 않는다.
    """
    incoming = [str(c).strip() for c in (calls if isinstance(calls, list) else []) if str(c).strip()]
    prev = call_map.get(name)
    if not isinstance(prev, list) or not prev:
        call_map[name] = incoming
        return
    seen = set(prev)
    for c in incoming:
        if c not in seen:
            prev.append(c)
            seen.add(c)


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
    # (R56 N52) 행 라벨 ↔ 내부 키는 대응표대로(정본 관례: Called 행 = 호출자 = `calling`). 리더 `_extract_function_blocks` 와 왕복.
    for _label in (LABEL_CALLED_FUNCTION, LABEL_CALLING_FUNCTION):
        if block.get(CALL_ROW_LABEL_TO_KEY[_label]):
            lines.append(f"{_label}\t{block.get(CALL_ROW_LABEL_TO_KEY[_label])}")
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


_C_COMMENT_SPAN_PAT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_COMMENT_NAMES_A_DID_PAT = re.compile(r"\bDID\b", re.I)


def _did_pattern_hits(fn_body: str, patterns: List["re.Pattern[str]"]) -> Tuple[List[str], int]:
    """함수 본문의 DID 패턴 매치 `(값 목록, 버린 주석 매치 수)` — 코드 속 매치는 전부, **주석 속 매치는 그 주석이
    `DID` 라고 말할 때만**.

    (R60, 리뷰 W1) DID 패턴엔 `0x` + 16진 4자리가 있어 주석 속 아무 상수나 걸렸다. KJPDS02 실측 124건 중 13건이
    주석에만 있었고 그중 9건이 DID 가 아니었다(`/* TIM0TC3: BIT=0x0186 */` · `// 0x7FFF` · 주석 처리된 코드의 마스크
    `0xFF00` · 프레임 설명 속 `DID_H`). 그렇다고 주석을 통째로 지우면 **주석에만 적힌 진짜 DID 4건을 잃는다**
    (`{   /* DID: 0x1002 */` · `/* Build response header for unified DID 0xF2F0 */`) — 코드는 그 값을 매크로·바이트
    비교로만 쓴다. 전처리(`gcc -E`)가 주석을 지우던 시절엔 생성 코드의 오탐 2건이 우연히 가려져 있었다.
    ⚠ 코드 속 16진 4자리(마스크 등)의 오탐은 여기서 다루지 않는다(N66).
    """
    spans = [(m.start(), m.end()) for m in _C_COMMENT_SPAN_PAT.finditer(fn_body)]
    hits: List[Tuple[int, str]] = []
    dropped = 0
    for pat in patterns:
        for dm in pat.finditer(fn_body):
            val = dm.group(0).strip()
            if not val:
                continue
            pos = dm.start()
            span = next(((a, b) for a, b in spans if a <= pos < b), None)
            if span is not None and not _COMMENT_NAMES_A_DID_PAT.search(fn_body, span[0], span[1]):
                dropped += 1
                continue
            hits.append((pos, val))
    return [v for _, v in hits], dropped



def _build_project_context(source_text_cache: Dict[str, str], read_truncated: List[Tuple[str, int]],
                           roots=(), walk=None, read=None, max_files: int = 4000) -> Dict[str, Any]:
    """루트 아래 **모든** `.c`/`.h` 원문으로 프로젝트 C 문맥을 만든다(`generators.c_project_context`). 실패는 사유로 남긴다.

    ⚠ 문서 범위와 컴파일 문맥은 다르다: 소스 단계는 component_map `verify=X` 파일(LIN 드라이버·`Include_File_Management.h`)을
    문서 대상에서 빼는데, 그 목록으로 문맥을 만들었더니 모든 파일이 include 하는 헤더가 사라져 실 생성의 MC/DC 가 전부
    `identifier_undeclared` 가 됐다(R81 실측: 인벤토리 393 설계 vs 실 생성 0). 그래서 루트를 따로 훑는다. 이미 읽은 원문은
    재사용하고, 상한에 잘려 읽힌 파일은 전부 다시 읽는다(`read` 는 상한 없음).
    """
    truncated = {str(p) for p, _n in read_truncated}
    texts = {str(p): t for p, t in source_text_cache.items()
             if str(p).lower().endswith((".c", ".h")) and t and str(p) not in truncated}
    unread: List[str] = []
    at_cap = False
    if walk is not None and read is not None:
        seen = 0
        for root in roots or ():
            for path in walk(root):
                if path.suffix.lower() not in (".c", ".h"):
                    continue
                seen += 1
                if seen > max_files:
                    at_cap = True
                    break
                key = str(path)
                if key not in texts:
                    text = read(path)
                    if text:
                        texts[key] = text
                    else:
                        unread.append(key)
    try:
        from generators.c_project_context import build_project_context
        context = build_project_context(texts)
    except (ImportError, ValueError, RecursionError, AttributeError, TypeError) as exc:
        _logger.warning("프로젝트 C 문맥 생성 실패 — MC/DC 는 프로젝트 헤더를 해석하지 못한다: %s", exc)
        return {"status": f"build_failed:{type(exc).__name__}"}
    # 문맥에 못 넣은 파일 — 그 파일의 선언이 필요한 식별자는 값을 확정하지 않는다(엔진은 `partial_context` 로 표시).
    context["incomplete_files"] = sorted(unread + [p for p in truncated if p not in texts])
    context["file_cap_reached"] = at_cap
    return context


def generate_uds_source_sections(
    source_root: str,
    component_map: Optional[Dict[str, Dict[str, str]]] = None,
    sds_partition_map: Optional[Dict[str, Dict[str, str]]] = None,
    *,
    preprocess: bool = False,
    max_files: Optional[int] = None,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:   # 값은 str·list·dict 혼합(function_details 등) — 과거 Dict[str, str]는 오기
    """`max_files`/`max_items` 는 **호출자 상한**. `None` 이면 `config` 기본값을 쓴다.

    ⚠ `preprocess` 기본값은 **False** 다(R60 N64 — 2026-09-17 까지 True). "정밀" 이라던 전처리 경로는 실측하니
      함수의 6%(KJPDS02)·0%(PDS64)에만 닿았고 닿은 곳에선 소스 주석 설명 52건을 추론 문장으로 바꾸고 전역 718개를
      엉뚱한 파일에 귀속시켰다 — 입력·출력·호출 어느 칸에도 이득이 없었다(상세 `parse_c_project` docstring).
      이 기본값과 `backend.helpers.uds._get_source_sections_cached` 의 기본값은 같아야 한다(캐시 키에 들어간다) —
      `tests/unit/test_source_sections_preprocess_default_r60.py` 가 묶는다. `preprocess` 이후 인자는 **키워드 전용**
      이다(리뷰 I2) — 위치 인자로 True 가 들어오면 그 가드가 못 본다.
    ⚠ 이 전환으로 KJPDS02 의 전역 표 모수가 25,005 → 1,327 로 **19배 준다. 회귀가 아니다** — 같은 헤더의 extern 이
      그 헤더를 include 한 `.c` 마다 복제돼 있던 것이 사라진 것이다(리뷰 I5).

    ⚠ 숫자를 여기 복제하지 않는다 — 기본값의 단일 출처는 `config.UDS_MAX_SOURCE_FILES`/
      `UDS_MAX_FUNCTION_ITEMS`(환경변수로 덮임)이고, 준비 게이트의 공시도 거기서 읽는다
      (`docgen_requirements._uds_cap`). `generators/sts.py` 의 `max_tc_per_req` 와 같은 규약.
    """
    # 콤마/세미콜론 구분 복수 소스 루트 지원
    _raw_roots = split_source_roots(source_root)

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
    typedef_aliases: Dict[str, str] = {}
    enum_domains: Dict[str, Dict[str, Any]] = {}
    _typedef_conflicts: Set[str] = set()
    _enum_conflicts: Set[str] = set()
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
    # (R66 N76) 정의 충돌로 규칙이 고른 이름 — 뒤의 이름 키 폴백(행 → 맵 빈 칸 채우기)이 진 파일의 값을 다시 넣지 않게.
    _collision_names: Set[str] = set()
    source_text_cache: Dict[str, str] = {}
    # (R52 N41) 타입 폴백(`_infer_type_from_file`)의 실행 단위 원문 캐시 — 두 호출부가 **같은** 캐시를 넘긴다(한쪽만 넘기면
    #   그쪽은 옛 동작대로 전역마다 파일을 다시 읽는다). 이 함수가 끝나면 버려진다.
    #   ⚠ 위 `source_text_cache`(`_src_read` — 상한 없음, local 모드는 `errors="replace"`)와는 읽기 경로·상한·디코딩이 달라
    #   합치지 않았다(리뷰 I2). 세 번째 원문 캐시를 만들지 말 것 — 합치려면 상한 통일이 먼저다.
    _type_scan_cache: Dict[str, str] = {}
    # (R65 N74) name → 헤더 프로토타입 **후보 전부** [{file, sig}]. 고르는 것은 함수마다 `pick_header_prototype`(정의와 같은 트리 ·
    #   같은 인자 수). 앞 판의 `name → 첫 프로토타입` first-wins 는 APP/FBL 쌍둥이가 한 프로토타입을 나눠 갖게 했다.
    _header_proto_map: Dict[str, List[Dict[str, str]]] = {}
    _proto_scan: Dict[str, int] = {}          # source → 함수 수 (`header` / `definition:<이유>`)
    _proto_kept: Dict[str, List[Dict[str, str]]] = {}    # 정의를 지킨 이유 → [{name, file}](공시용, 이유당 50개)
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
        """typedef 정규화 적용. (R56 N52) 먼저 한 줄로 — 원문 줄바꿈·주석 제거(정본 Prototype 은 전부 한 줄, 실측 50건)."""
        sig = normalize_prototype_text(sig)
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
    # (R62 N69) 헤더 프로토타입의 문서 주석 — 이름 → 후보 목록(헤더가 APP/FBL 트리에 따로 있다).
    _header_docs: Dict[str, List[Dict[str, str]]] = {}
    _root_strs: List[str] = [str(_r) for _r in _roots]
    # 죽은 `#if 0` 분기라 모으지 않은 정의 — {파일: [이름]}. 텍스트 루프가 읽는 `.c` 기준(면제 계층 파일은 애초에 안 읽는다).
    _dead_code_excluded: Dict[str, List[str]] = {}
    # (R63 N70) 같은 이유로 모으지 않은 전역·매크로·프로토타입 — {종류: {파일: [이름]}}. 이름은 그 파일 기준(다른 파일에 산 정의가 있을 수 있다).
    _dead_decls_excluded: Dict[str, Dict[str, List[str]]] = {}
    # 원문 읽기 상한에 **닿은 파일**. 캡은 조용히 자르므로 닿았다는 사실을 남기지
    # 않으면 "이 프로젝트엔 그 선언이 원래 없다" 와 구분되지 않는다
    # (실측: 200KB 캡이 IO_Map.h 의 매크로 69% 를 지웠는데 로그가 한 줄도 없었다).
    _read_truncated: List[Tuple[str, int]] = []
    for p in files:
        raw, _raw_len, _cut = _read_source_text(p)
        if _cut:
            _read_truncated.append((str(p), _raw_len))
        # (R63 N70) 죽은 `#if 0` 분기는 **이 루프의 모든 수집기**에서 가린다 — R62 는 함수 정의만 가려, 죽은 구간에만 있는
        #   전역(KJPDS02 6개 · PDS64 4개 — `CRC32.c:crcTable` 등, 정본 UDS 엔 0개)이 전역 표에 실재 변수로 남아 있었다.
        #   `raw` 는 원문 그대로 둔다(`source_text_cache` — 본문 조회용). 판정은 `blank_dead_code` 한 구현.
        live_raw = blank_dead_code(raw)
        _has_dead = live_raw is not raw
        text = _strip_c_comments(live_raw)
        if _has_dead:
            # (리뷰 W3) 전역·매크로·프로토타입도 버린 것을 센다 — 함수만 공시하면 "전역 표 행이 왜 줄었나" 에 답할 수 없다.
            _dead_text = _strip_c_comments(raw)
            _dg = sorted({str(g.get("name") or "") for g in _extract_c_global_candidates(_dead_text)} - {str(g.get("name") or "") for g in _extract_c_global_candidates(text)})
            _dm = sorted({m[0] for m in _extract_c_macro_defs(_dead_text)} - {m[0] for m in _extract_c_macro_defs(text)})
            _dp = sorted({d[0] for d in _extract_c_prototypes(_dead_text)} - {d[0] for d in _extract_c_prototypes(text)})
            for _kind, _names in (("globals", _dg), ("macros", _dm), ("prototypes", _dp)):
                if _names:
                    _dead_decls_excluded.setdefault(_kind, {})[str(p)] = [n for n in _names if n]
        # ⚠ 주석이 지워진 `text` 로 본다 — 주석 안 선언을 세면 없는 레지스터가 생긴다.
        _placed_globals.update(placed_global_names(text))
        reqs.extend(_extract_requirements_from_comments(live_raw))
        dox_tags = _extract_doxygen_asil_tags(live_raw)
        if dox_tags:
            _doxygen_tags_by_file[str(p)] = dox_tags
        hdr_asil = _extract_file_header_asil(raw)   # 선두 고정 매치라 `#if 0` 이 앞서면 어차피 실패 — raw/live_raw 동치(리뷰 I3)
        if hdr_asil:
            _file_header_asil[str(p)] = hdr_asil
        for _sty, _smm in extract_struct_member_arrays(text).items():
            struct_member_arrays_raw.setdefault(_sty, {}).update(_smm)
        # ⚠ **주석이 남은 원문**(`live_raw`)을 넘긴다. `text` 는 주석이 지워진 판이라 멤버의 자기 주석이
        #    통째로 사라진다(그 함수가 내부에서 길이 보존 blank 를 다시 한다).
        # (R73 N92) 단순 typedef 별칭. 파일 열거 순서의 first-wins(같은 별칭이 다른 원형으로 또 나오면 첫 것).
        # 같은 이름이 **다른 내용**으로 또 나오면(`#ifdef` 갈래·이식 계층) 어느 쪽이 이 빌드의 것인지 모른다 — first-wins 로
        # 고르면 `infer_c_type_widths` 의 "상충 증언은 뺀다" 가 무력해진다(리뷰 W3). 충돌한 이름은 표에서 **뺀다**.
        for _ta, _tb in extract_typedef_aliases(live_raw).items():
            if typedef_aliases.setdefault(_ta, _tb) != _tb:
                _typedef_conflicts.add(_ta)
        for _en, _ed in extract_enum_domains(live_raw).items():
            if enum_domains.setdefault(_en, _ed)["values"] != _ed["values"]:
                _enum_conflicts.add(_en)
        for _sty, _smt in extract_struct_member_types(live_raw).items():
            _dst = struct_member_types.setdefault(_sty, {})
            for _mname, _mrec in _smt.items():
                # first-wins. dict 덮어쓰기로 행을 침묵 소실한 전례(SUTS R25 66행).
                _dst.setdefault(_mname, _mrec)
        for g in _extract_c_global_candidates(text):
            gname = str(g.get("name") or "").strip()
            if not gname:
                continue
            prev = manual_globals_info_map.get(gname, {})
            # (R66 N76 리뷰 C1) `.c` 안의 `extern` 은 선언이지 정의가 아니다 — 이미 있는 항목의 file·init·static 을 갈아 끼우지 않고
            #   (KJPDS02 `lin_lin21_proto.c:35 extern l_u8 etf_collision_flag;` 가 `lowlevel/lin.c` 의 정의 `= 0` 을 덮었다),
            #   처음 보는 이름이면 `extern` 표지를 달아 뒤에 오는 정의가 충돌 없이 이기게 한다.
            if str(g.get("extern") or "").strip().lower() == "true":
                if prev:
                    if not prev.get("type") and g.get("type"):
                        prev["type"] = str(g.get("type") or "").strip()
                    continue
                manual_globals_info_map[gname] = {
                    "type": str(g.get("type") or "").strip(), "array": str(g.get("array") or "").strip(), "file": str(p),
                    "range": "", "init": "", "range_source": "", "static": "false", "desc": "", "extern": "true",
                }
                continue
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
            for _hname, _hdoc in extract_header_function_docs(live_raw).items():
                _header_docs.setdefault(_hname, []).append({"file": str(p), **_hdoc})
            for name, params, ret_type, is_extern in _extract_c_prototypes(text):
                signature = f"{ret_type} {name}( {params} )" if ret_type else f"{name}({params})"
                # 후보로 쌓는다(first-wins 아님) — 어느 것을 쓸지는 정의 파일을 아는 자리에서 고른다.
                _header_proto_map.setdefault(name, []).append({"file": str(p), "sig": signature})
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
            # (R62 N69) 죽은 `#if 0` 분기의 정의는 모으지 않는다 — tree-sitter 가 일부러 뺀 함수를 아래 "AST 누락분 병합" 이
            #   이름으로 되살려 KJPDS02 24개 · PDS64 13개가 실재 함수처럼 올라 있었다. (R63) `text` 가 이미 가린 판이다.
            body_map = _extract_c_function_bodies(text)
            # 리셋/초기화 함수의 전역 대입을 모은다(같은 `body_map` 재사용 — 추가 파싱 0).
            # ⚠ 헤더(`.h`)는 여기 안 온다. 헤더에 `static` 초기화 함수가 있으면 못 본다.
            for _rvar, _rrows in collect_reset_assignments(body_map).items():
                _reset_assigns.setdefault(_rvar, []).extend(_rrows)
            if _has_dead:
                # 버린 것을 남긴다(R58 의 call_filter 와 같은 규약) — 안 남기면 "함수 수가 왜 줄었나" 에 답할 수 없다.
                _live_names = {d[0] for d in _extract_c_definitions(text)}
                _dead_here = sorted({d[0] for d in _extract_c_definitions(_dead_text)} - _live_names)
                if _dead_here:
                    _dead_code_excluded[str(p)] = _dead_here
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
                        # 함수 **자기** 주석의 등급만. `c_asil` 은 파일 머리말 ASIL 로 채워질 수 있고, 그걸 병합 분기가
                        # `asil_source: "comment"` 로 실으면 출처가 세탁된다(리뷰 W1 — AST 경로도 머리말 ASIL 은 안 쓴다).
                        "comment_asil_own": str(dox_info.get("asil", "") or ""),
                        "comment_related": c_related,
                        "comment_precondition": "",
                        "body": body_text,
                    }
                )
            source_text_cache[str(p)] = raw
            macros.extend(_extract_c_macros(text))
            for m_name, m_val in _extract_c_macro_defs(text):
                macro_defs.append([m_name, "", m_val, ""])

        lines = live_raw.splitlines()   # (R63) 주석 표도 죽은 분기는 읽지 않는다 — 위 요구 ID 추출과 한 규칙(리뷰 I4)
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
                        ast_result["decl_error_rejected"] = int(ast_result.get("decl_error_rejected") or 0) + int(
                            _partial.get("decl_error_rejected") or 0
                        )
                except Exception:
                    pass
            # (R58 N59, 리뷰 W1) 괄호 대상 `(Foo)(v)` 승격은 루트 단위 known 으로 먼저 됐다 — 루트를 합친 함수 집합으로
            # 다시 승격해야 교차 루트(APP↔FBL)의 진짜 호출이 남는다(멱등). 계수는 합친 기준으로 다시 센다.
            try:
                from workflow.code_parser.c_parser import promote_paren_call_targets as _promote_paren
                ast_result["call_filter"] = _promote_paren(ast_result["functions"])
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

        # (R57 N54) 같은 이름의 정의가 **다른 파일**에 있으면 둘 다 남긴다 — 예전엔 두 번째 정의를 파일째 버려
        #   (first-wins) 정본이 APP 절과 Bootloader 절에 따로 실은 9개 함수(main·WriteBlock·EEPROM_SetByte …)의
        #   Bootloader 표가 **APP 내용의 복사본**이었다(run 2088: 정본 main 표 둘은 피호출자가 다른데 생성본은 둘 다
        #   `s_System_InitSequence`). 같은 파일 안의 같은 이름(#ifdef 변형)은 종전대로 첫 정의에 ASIL 만 보수적 상향.
        #   교차 파일 충돌 기록(`function_collisions`)은 그대로 — 영향분석이 두 사본의 file/최대 ASIL 을 거기서 읽는다.
        _seen_ast_idx: Dict[Tuple[str, str], int] = {}
        _first_idx_by_name: Dict[str, int] = {}
        _deduped: List[Dict[str, Any]] = []

        def _note_collision(_a: Dict[str, Any], _b: Dict[str, Any], _fn_name: str) -> None:
            _ck = _fn_name.strip().lower()
            _ce = function_collisions.setdefault(_ck, {"files": [], "asil": ""})
            for _d in (_a, _b):
                _df = str(_d.get("file") or "").strip()
                if _df and _df not in _ce["files"]:
                    _ce["files"].append(_df)
                if _asil_rank_of(_d.get("comment_asil")) > _asil_rank_of(_ce.get("asil")):
                    _ce["asil"] = str(_d.get("comment_asil") or "")

        for _fn in (ast_result.get("functions") or []):
            _fn_name = str(_fn.get("name") or "").strip() if isinstance(_fn, dict) else ""
            if not _fn_name:
                continue
            _fkey = (_fn_name, os.path.normcase(str(_fn.get("file") or "").strip()))
            if _fkey not in _seen_ast_idx:
                # 교차 파일 쌍둥이(이름은 같고 파일이 다름)는 자기 정의로 남긴다 — 충돌 기록은 두 정의가 다 지나가는
                #   `_put_by_name` 이 한다(여기서도 적으면 같은 사실을 두 곳이 적는다).
                _seen_ast_idx[_fkey] = len(_deduped)
                _first_idx_by_name.setdefault(_fn_name, len(_deduped))
                _deduped.append(_fn)
            else:
                _prev = _deduped[_seen_ast_idx[_fkey]]
                if _asil_rank_of(_fn.get("comment_asil")) > _asil_rank_of(_prev.get("comment_asil")):
                    _prev["comment_asil"] = _fn.get("comment_asil")  # 하향 방지(보수적 상향)
                _note_collision(_prev, _fn, _fn_name)
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

        _global_def_collisions: Dict[str, Dict[str, Any]] = {}
        # (R66 N76) 이름 → {파일: 자기 정의(type·static·init·array)} — 충돌 후처리용.
        _own_defs: Dict[str, Dict[str, Dict[str, str]]] = {}
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
                # (리뷰 I2) `globals_info_map = dict(manual_globals_info_map)` 은 얕은 복사라 아래 `prev[...] = …` 제자리 수정이
                #   manual 맵의 항목 dict 에도 비친다 — L914 이후 manual 맵을 읽는 곳이 없어 무해. 다시 읽게 되면 여기가 결함이 된다.
                prev = globals_info_map.get(gname, {}) if isinstance(globals_info_map.get(gname), dict) else {}
                if gname and prev and str(g.get("is_extern") or "").strip().lower() == "true":
                    # (R64 N73) `extern` 은 선언이지 정의가 아니다 — 이미 있는 항목(텍스트 스캔의 정의·앞서 지나간 정의 행)의
                    #   file·init·desc·static 을 헤더 것으로 갈아 끼우지 않는다. include guard 안 헤더 extern 이 수집되면서
                    #   (KJPDS02 1,208행) 순회 순서에 따라 정의가 헤더에 귀속되던 경로. 비어 있는 칸(타입·설명)만 행이 가진
                    #   값으로 채운다. 아래 파일 스캔(`_infer_type_from_file`) 앞에서 끝내는 이유: 이름-only 행은 타입이 없어
                    #   665KB 레지스터 헤더를 이름마다 정규식으로 훑는데, 이미 아는 이름에 그 비용을 내지 않는다(A/B +7초).
                    incoming_desc = str(g.get("desc") or "").strip()
                    if not str(prev.get("type") or "").strip() and gtype:
                        prev["type"] = gtype
                    if not str(prev.get("desc") or "").strip() and incoming_desc:
                        # (리뷰 W3) 값은 정의 항목에 붙지만 출처는 헤더 선언의 주석이다 — 함수의 `comment_origin` 과 같은 규약으로 표기.
                        prev["desc"] = incoming_desc
                        prev["desc_source"] = "header_decl"
                    globals_info_map[gname] = prev
                    continue
                if not gtype and gfile:
                    gtype, init_from_file = _infer_type_from_file(gfile, gname, cache=_type_scan_cache)
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
                    incoming_desc = str(g.get("desc") or "").strip()
                    # ⚠ tree-sitter 산출 타입(`gtype`)엔 **`const` 한정자가 없다**.
                    #   텍스트 스캔(`prev`)은 갖고 있는데 여기서 통째로 덮여
                    #   `static const UDSFuncEntry_t s_UdsFuncTbl[…]` 가 그냥
                    #   `UDSFuncEntry_t` 로 남았다. const 는 "시험 입력으로 설정할 수
                    #   없다"는 판정의 유일한 근거라 **한정자만** 되살린다.
                    _gtype = gtype or str(prev.get("type") or "").strip()
                    if is_const_type(prev.get("type")) and not is_const_type(_gtype):
                        _gtype = f"const {_gtype}".strip()
                    # (R66 리뷰 W1) tree-sitter 행이 선언자별 `array` 를 실으면 그것이 자기 값이다(키가 있으면 빈 값도 사실).
                    #   없는 옛 행(이름-only)만 문장 꼬리(`_decl_array_dim`)로 폴백한다.
                    _own_array = str(g.get("array") or "").strip() if "array" in g else _decl_array_dim(gdecl)
                    _is_extern_row = str(g.get("is_extern") or "").strip().lower() == "true"
                    _incoming = {
                        "type": _gtype,
                        # ⚠ 텍스트 스캔이 이미 채워둔 값을 **먼저** 쓰고(const 처럼 그쪽만 아는 것이 있다), 없을 때만 자기 값.
                        "array": str(prev.get("array") or "").strip() or _own_array,
                        "file": gfile or str(prev.get("file") or "").strip(),
                        "range": grange or str(prev.get("range") or "").strip(),
                        "init": str(g.get("init") or "").strip() or str(prev.get("init") or "").strip(),
                        "range_source": str(g.get("range_source") or "").strip().lower(),
                        "static": "true" if is_static else "false",
                        "desc": incoming_desc or str(prev.get("desc") or "").strip(),
                    }
                    # (R66 N76) 같은 이름의 정의가 **다른 `.c`** 에도 있다 — 이 맵은 이름 키라 하나만 남는다. 옛 판은 뒤에 온 쪽이
                    #   이겼고(last-wins) 순서는 파일 열거(local `os.walk` vs cloudium `list_dir`)가 정했다. 실측(KJPDS02 10 · PDS64 9
                    #   이름): 정의 내용이 다른 것은 PDS64 `BackupArray`(APP `U16` vs FBL `word`) 1건이라 실효는 작지만 R65 와 같은
                    #   이유로 닫는다 — 누가 남는지는 규칙이 정한다: **소스 루트 순서**(첫 루트가 주 트리) → 경로 문자열. 진 쪽과
                    #   type·static·init·array 가 다르면 `differs` 에 적어 준비 게이트가 말한다. 두 정의를 표에 다 싣지는 않는다
                    #   (정본 표엔 파일 열이 없어 같은 이름 두 행은 구분이 안 된다 — 관찰로 남김).
                    #   이름-only 행(`decl` 없음)도 센다 — 그 행이 먼저 file 을 바꿔 두면 뒤따르는 상세 행에선 충돌이 안 보인다.
                    # 파일별 **자기** 정의(선언문이 있는 행만) — 아래 후처리가 충돌 이름의 `differs` 와 남은 정의의 칸을 여기서 읽는다.
                    #   `_incoming` 은 빈 칸을 prev(다른 파일의 텍스트 스캔·이름-only 행)로 메운 병합값이라 비교·복원에 못 쓴다.
                    #   충돌 판정 **앞**에서 적는다 — 진 쪽 행은 아래서 `continue` 한다.
                    #   (리뷰 C1) `extern` 행은 정의가 아니다 — 후보에도, 충돌에도 안 넣는다. prev 가 extern 표지뿐이면 그냥 덮는다.
                    if gdecl and gfile.lower().endswith((".c", ".cpp")) and not _is_extern_row:
                        _own_defs.setdefault(gname, {})[gfile] = {
                            "type": gtype, "static": "true" if is_static else "false",
                            "init": str(g.get("init") or "").strip(), "array": _own_array,
                        }
                    if _is_extern_row and not prev:
                        _incoming["extern"] = "true"
                    _pf = str(prev.get("file") or "").strip()
                    if (
                        _pf and gfile and os.path.normcase(_pf) != os.path.normcase(gfile)
                        and _pf.lower().endswith((".c", ".cpp")) and gfile.lower().endswith((".c", ".cpp"))
                        and not _is_extern_row and str(prev.get("extern") or "") != "true"
                    ):
                        _entry = _global_def_collisions.setdefault(gname, {"files": [_pf], "kept": _pf, "differs": []})
                        if gfile not in _entry["files"]:
                            _entry["files"].append(gfile)
                        if _definition_order(_pf, _root_strs) <= _definition_order(gfile, _root_strs):
                            continue   # 먼저 오는 루트/경로의 정의가 남는다 — 뒤에 온 쪽은 적기만
                        _entry["kept"] = gfile
                    static_name_map[gname] = is_static
                    globals_info_map[gname] = _incoming
            # (R66 N76) 충돌 이름 후처리 — ① `differs`: 파일별 자기 정의끼리 비교(한쪽이 비면 모름, 한정자·공백은 걷는다).
            #   ② 남은 정의(`kept`)의 array·init·static·type 을 그 파일의 자기 값으로 되돌린다 — 이름-only 행이 먼저 와서 다른
            #   파일의 배열 크기를 물려받는 경로(`u8s_Buf[4]` 가 `[8]` 로) 를 막는다. const 는 자기 타입에 없으므로 기존 칸이
            #   const 였고 기본형이 같으면 유지한다.
            for _cname, _centry in _global_def_collisions.items():
                _defs = _own_defs.get(_cname) or {}
                for _axis in ("type", "static", "init", "array"):
                    _vals = {_norm_def_axis(d.get(_axis)) for d in _defs.values()}
                    # 타입만 빈 값 = 모름(ERROR 선언). init·array·static 의 빈 값은 사실("초기값 없음")이라 차이다(리뷰 C2).
                    if _axis == "type":
                        _vals -= {""}
                    if len(_vals) > 1 and _axis not in _centry["differs"]:
                        _centry["differs"].append(_axis)
                # (리뷰 I4) 참가 파일 중 자기 정의 행이 없는 것(이름-only)이 있으면 비교가 불완전하다 — 모른다고 적는다.
                if len(_defs) < len(_centry["files"]) and "unknown" not in _centry["differs"]:
                    _centry["differs"].append("unknown")
                _kept_own = _defs.get(_centry["kept"])
                _cinfo = globals_info_map.get(_cname)
                if not _kept_own or not isinstance(_cinfo, dict):
                    continue
                # (리뷰 C2) "없음" 도 복원한다 — kept 에 초기값·배열이 없으면 진 파일의 `9U`·`[8]` 가 남아 있으면 안 된다.
                #   type·static 은 kept 파일의 상세 행이 자기 값으로 쓰므로(그 행은 `continue` 를 타지 않는다) 복원할 것이 없다 —
                #   뮤테이션이 등가로 확인해 뺐다. array·init 만 `prev 우선` 병합으로 오염된다.
                for _axis in ("array", "init"):
                    _cinfo[_axis] = _kept_own.get(_axis) or ""
            _collision_names.update(_global_def_collisions)
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
        if _dead_code_excluded or _dead_decls_excluded:
            _logger.info(
                "죽은 #if 0 구간 제외: 함수 %d · 전역 %d · 매크로 %d · 프로토타입 %d (파일 %d)",
                sum(len(v) for v in _dead_code_excluded.values()),
                sum(len(v) for v in _dead_decls_excluded.get("globals", {}).values()),
                sum(len(v) for v in _dead_decls_excluded.get("macros", {}).values()),
                sum(len(v) for v in _dead_decls_excluded.get("prototypes", {}).values()),
                len(set(_dead_code_excluded) | {f for d in _dead_decls_excluded.values() for f in d}),
            )
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
            # (R63 N70) 죽은 분기의 `static` 선언이 산 전역을 static 으로 만들지 않게 — 위 텍스트 루프와 같은 판정.
            for g in _extract_c_global_candidates(blank_dead_code(src_text)):
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
            for item in _extract_c_global_candidates(blank_dead_code(hdr_text)):
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
            # (R64 N73 리뷰 W1·W2) 조용히 지나가던 두 가지 — 이름이 ERROR 안에서만 나와 버린 선언 수(tree-sitter 오파싱),
            #   같은 이름의 정의가 여러 `.c` 에 있어 이름 키 맵이 한쪽만 남긴 이름(→ 후보 파일 목록).
            "decl_error_rejected": int(ast_result.get("decl_error_rejected") or 0),
            #   경로는 `상위폴더/파일` — APP·FBL 두 루트에 같은 이름의 파일이 있어 파일명만으론 같은 파일로 읽힌다(`EEPROM.c:BackupArray`).
            #   (R66 N76) `{files, kept, differs}` — 어느 정의가 남았고(`kept`), 진 쪽과 무엇이 달랐는지(`differs`: type/static/init/array).
            #   `differs` 가 비면 이름만 겹친 것이고, 차 있으면 표의 그 행이 한쪽 정의만 말하고 있다는 뜻이다(게이트 warning).
            #   (리뷰 I1) 앞에 소스 루트 번호 — APP/FBL 의 `Eeprom/EEPROM.c` 는 같은 문자열이라 번호 없이는 어느 트리가 남았는지 모른다.
            "definition_collisions": {
                k: {
                    "files": [_short_def_path(f, _root_strs) for f in v["files"]],
                    "kept": _short_def_path(v["kept"], _root_strs),
                    "differs": list(v["differs"]),
                }
                for k, v in sorted(_global_def_collisions.items())
            },
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
                # (R63 N70 리뷰 W2) 원문 캐시는 그대로 두고 **판정에 쓰는 소비자**만 가린다 — `#if 0` 안의 옛 구현(`main.c` 141~316행)이
                #   같은 이름의 첫 매치가 되어 죽은 본문의 호출이 산 함수의 Called 칸이 되던 경로.
                fb = _extract_fallback_call_names(
                    blank_dead_code(source_text_cache.get(file_path, "")),
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
            is_static = bool(fn.get("is_static"))
            file_path = str(fn.get("file") or "").strip()
            # 헤더 프로토타입 우선(파라미터명/타입이 더 정확) — 단 **이 정의의** 헤더만. (R65 N74) 규칙은 `pick_header_prototype` 한 곳.
            if name:
                signature, _proto_src = pick_header_prototype(
                    _header_proto_map.get(name) or [], file_path, _root_strs, signature, is_static=is_static, name=name
                )
                _proto_scan[_proto_src] = _proto_scan.get(_proto_src, 0) + 1
                # 정의를 지킨 이유별 목록 — 정상 상태(static·헤더 없음)는 빼고, 이름만으론 쌍둥이를 못 가르니 파일과 함께, 이유당 50개까지(리뷰 I1·I3).
                if _proto_src.startswith("definition:") and _proto_src not in ("definition:static", "definition:no_header"):
                    _kept = _proto_kept.setdefault(_proto_src, [])
                    if len(_kept) < 50:
                        _kept.append({"name": name, "file": "/".join(Path(file_path).parts[-2:]) if file_path else ""})
            # static 함수의 시그니처에 static 키워드 보존 (레퍼런스 UDS 형식)
            if is_static and not signature.lstrip().startswith("static "):
                signature = "static " + signature
            # typedef 정규화 (byte→U8, word→U16 등)
            signature = _normalize_prototype(signature)
            calls = fn.get("calls") or []
            used_globals = fn.get("used_globals") or []
            comment_desc = str(fn.get("comment_desc") or "").strip()
            comment_asil = str(fn.get("comment_asil") or "").strip()
            comment_related = str(fn.get("comment_related") or "").strip()
            comment_precond = str(fn.get("comment_precondition") or "").strip()
            if not name:
                continue
            # (R62 N69) 정의에 없는 필드만 헤더 프로토타입의 문서 주석에서 채운다 — 정의 쪽 주석이 항상 이긴다.
            #   static 은 제외: 헤더가 선언하는 것은 외부 연결 함수이고, 같은 이름의 파일 내부 함수는 남이다.
            comment_origin = ""
            if not is_static and not (comment_desc and comment_asil and comment_related):
                _hdr_doc = pick_header_doc(_header_docs.get(name) or [], file_path, _root_strs)
                if _hdr_doc:
                    _filled = False
                    if not comment_desc and _hdr_doc.get("desc"):
                        comment_desc, _filled = str(_hdr_doc["desc"]).strip(), True
                    if not comment_asil and _hdr_doc.get("asil"):
                        comment_asil, _filled = str(_hdr_doc["asil"]).strip(), True
                    if not comment_related and _hdr_doc.get("related"):
                        comment_related, _filled = str(_hdr_doc["related"]).strip(), True
                    if not comment_precond and _hdr_doc.get("precondition"):
                        comment_precond = str(_hdr_doc["precondition"]).strip()
                    if _filled:
                        comment_origin = _header_origin_label(_hdr_doc)
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
                _merge_call_map(call_map, name, calls)
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
            # (R57 리뷰 W4) 이름 키 — 같은 이름의 정의가 둘이면 첫 정의의 모듈을 유지한다(`_put_by_name` 과 같은 first-wins).
            module_map.setdefault(name, module_name)
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
                    # (R47-k N27-e) 첨자는 set 이라 순회 순서가 프로세스마다 다르다 — 정렬은 헬퍼가 한다.
                    index_vals = _observed_index_values(u.get("indexes"), macro_value_map)
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
                    index_vals = _observed_index_values(u.get("indexes"), macro_value_map)   # (R47-k) 위 파라미터 경로와 같은 헬퍼
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
            # (R56 N52) Called/Calling 칸은 **이름만** — 정본 951 함수 중 914 가 이름만이다. 프로토타입을 넣던 옛 방식은
            #   여러 줄 원문·주석까지 칸에 실었고(LIN 드라이버 50건) 되읽기 파서가 이름을 잃었다. 프로토타입은 Prototype 행에만.
            called_text = "\n".join(called_list)
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
            asil_v, asil_src, related_v, related_src = _source_stage_provenance(
                comment_asil=comment_asil, comment_related=comment_related,
                override=_func_override.get(name),
                sds_asil=_sds_map.get(name.lower(), {}).get("asil"),
                sds_related=_lookup_sds_related(name, module_name))
            detail = {
                "id": fn_id,
                "name": name,
                "prototype": signature,
                "description": desc_text,
                "asil": asil_v,
                "related": related_v,
                "description_source": "comment" if comment_desc else "inference",
                "asil_source": asil_src,
                "related_source": related_src,
                "inputs": inputs_list,
                "outputs": outputs_list,
                "precondition": inferred_precond,
                "file": str(file_path) if file_path else "",
                "source_unavailable_reason": "source_read_truncated" if any(p == file_path for p, _ in _read_truncated) else "",
                "source_text_complete": bool(source_text_cache.get(file_path)) and not any(p == file_path for p, _ in _read_truncated),
                "source_path": str(file_path) if file_path else "",
                "module_name": Path(file_path).stem if file_path else "",
                "comment_description": comment_desc,
                "comment_origin": comment_origin,   # "" = 정의 앞 주석(또는 주석 없음) · "header:<파일>" = 헤더 프로토타입의 문서 주석
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
                _merge_call_map(call_map, name, calls)
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
                module_map.setdefault(name, module_name)   # (R57 리뷰 W4) 위와 같은 규칙 — 두 곳이 같이 움직여야 한다
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
                # (R62 N69) 수집 단계(위 `fallback_functions.append`)가 읽어 둔 주석 필드를 여기서 버리고 있었다 —
                #   tree-sitter 가 놓친 함수는 `@asil` 이 있어도 SDS/TBD 로 내려갔다. AST 경로와 같은 우선순위로 쓴다.
                m_desc = str(fn.get("comment_desc") or "").strip()
                m_asil = str(fn.get("comment_asil_own") or "").strip()
                m_precond = str(fn.get("comment_precondition") or "").strip()
                m_related = str(fn.get("comment_related") or "").strip()
                m_origin = ""
                if not is_static and not (m_desc and m_asil and m_related):
                    _hdr_doc = pick_header_doc(_header_docs.get(name) or [], file_path, _root_strs)
                    if _hdr_doc:
                        _before = (m_desc, m_asil, m_related)
                        m_desc = m_desc or str(_hdr_doc.get("desc") or "").strip()
                        m_asil = m_asil or str(_hdr_doc.get("asil") or "").strip()
                        m_related = m_related or str(_hdr_doc.get("related") or "").strip()
                        m_precond = m_precond or str(_hdr_doc.get("precondition") or "").strip()
                        if (m_desc, m_asil, m_related) != _before:
                            m_origin = _header_origin_label(_hdr_doc)
                desc_text = _enhance_description_text(
                    name,
                    m_desc or _fallback_function_description(name, called_list),
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
                # (R65 리뷰 I2) 이 루프(텍스트 폴백 함수)는 헤더 프로토타입을 쓴 적이 없다 — 분모를 맞추기 위해 세기만 한다.
                _proto_scan["definition:fallback_loop"] = _proto_scan.get("definition:fallback_loop", 0) + 1
                # (R70 N84) AST 루프와 같은 사슬 — 예전엔 이 루프의 Related 만 override 를 건너뛰었다.
                asil_v, asil_src, related_v, related_src = _source_stage_provenance(
                    comment_asil=m_asil, comment_related=m_related,
                    override=_func_override.get(name),
                    sds_asil=_sds_map.get(name.lower(), {}).get("asil"),
                    sds_related=_lookup_sds_related(name, module_name))
                if related_src == _OVERRIDE_SOURCE:
                    # 이 루프에서 override 가 Related 를 준 건수 — 옛 사슬(SDS 우선)과 값이 갈릴 수 있던 자리다.
                    #   라이브 두 루트 0건(R70 실측). 다른 프로젝트에서 이 수가 서면 SwDS 값과 대조할 것(리뷰 I4).
                    _proto_scan["fallback_related_from_override"] = _proto_scan.get("fallback_related_from_override", 0) + 1
                detail = {
                    "id": fn_id,
                    "name": name,
                    "prototype": signature,
                    "description": desc_text,
                    "asil": asil_v,
                    "related": related_v,
                    "description_source": "comment" if m_desc else "inference",
                    "asil_source": asil_src,
                    "related_source": related_src,
                    "inputs": inputs_list,
                    "outputs": outputs_list,
                    "precondition": m_precond or "N/A",
                    "file": str(file_path) if file_path else "",
                    "source_unavailable_reason": "source_read_truncated" if any(p == file_path for p, _ in _read_truncated) else "",
                    "source_text_complete": bool(source_text_cache.get(file_path)) and not any(p == file_path for p, _ in _read_truncated),
                    "source_path": str(file_path) if file_path else "",
                    "module_name": Path(file_path).stem if file_path else "",
                    "comment_description": m_desc,
                    "comment_origin": m_origin,
                    "comment_asil": m_asil,
                    "comment_related": m_related,
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
            _listed_extern: Set[str] = set()
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
                if str(g.get("is_extern") or "").strip().lower() == "true":
                    # (R64 N73 리뷰 C1) 선언 행은 목록에 정의와 동급으로 서지 않는다 — include guard 안 헤더 extern(KJPDS02 1,208행)이
                    #   그대로 들어오면 `global_data` 총계가 1,014 → 1,915 로 부풀어 상한 240 안에서 진짜 전역(`_PIEL`·`_PIEP`)이
                    #   밀려나고, 같은 이름이 두 번 서고, 상한 손실 공시가 중복 선언을 "잘린 전역" 으로 센다. 항목의 집(`file`)이
                    #   이 파일이 아니면(정의가 다른 파일) 건너뛰고, 정의가 스캔 밖인 extern 은 한 번만 싣는다.
                    _home = str((globals_info_map.get(gname) or {}).get("file") or "").strip()
                    if (_home and os.path.normcase(_home) != os.path.normcase(gfile)) or gname in _listed_extern:
                        continue
                    _listed_extern.add(gname)
                if not gtype and gname in globals_info_map:
                    gtype = str(globals_info_map.get(gname, {}).get("type") or "").strip()
                if not gtype and gfile:
                    gtype2, init2 = _infer_type_from_file(gfile, gname, cache=_type_scan_cache)
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
            # (R66 N76 리뷰 C2) 행은 정의마다 하나라 충돌 이름엔 진 파일의 행도 있다 — 규칙이 비워 둔 init 을 그 행이 다시 채웠다(`9U`).
            if name in _collision_names:
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
    _did_comment_dropped = 0
    for fn in (ast_result.get("functions", []) if parse_c_project is not None else fallback_functions):
        fn_name = str(fn.get("name") or "").strip()
        fn_body = str(fn.get("body") or "").strip()
        if not fn_name or not fn_body:
            continue
        _did_vals, _did_dropped = _did_pattern_hits(fn_body, _did_pats)
        _did_comment_dropped += _did_dropped
        for did_val in _did_vals:
            if did_val not in did_entries:
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

    if _did_comment_dropped:
        _logger.info("DID scan: %d entries · 주석 속 매치 %d건 제외(그 주석이 DID 를 말하지 않음)",
                     len(did_entries), _did_comment_dropped)

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

    # (R73 N92) typedef 별칭을 원 선언으로 풀어 **payload 에 싣는다** — 전역엔 `base_type`, 함수엔 `param_base_types`
    #   (`{파라미터 root: 원 선언}`, 별칭이던 것만). 시험 생성기(SUTS·STS)가 경계값 타입을 풀 때 선언 옆에서 이걸 먼저 본다.
    #   전역 상태 없이 캐시 payload 와 `function_details` 로 흐르므로 STS(details 만 받음)에도 닿는다.
    for _cn in _typedef_conflicts:
        typedef_aliases.pop(_cn, None)
    for _cn in _enum_conflicts:
        enum_domains.pop(_cn, None)
    _td_stats = _annotate_typedef_bases(globals_info_map, function_details, typedef_aliases, enum_domains)
    _td_stats["alias_conflicts"] = sorted(_typedef_conflicts)
    _td_stats["enum_conflicts"] = sorted(_enum_conflicts)

    return {
        "typedef_aliases": typedef_aliases,
        "enum_domains": enum_domains,
        "typedef_scan": _td_stats,
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
        # (R80) 함수를 정의한 파일의 **완전한** 원문 — 파일당 한 번. 함수 레코드는 `source_path` 로 참조한다.
        #   함수마다 전문을 실었더니 캐시가 14배(2.4→34MB)가 되고 UDS 사이드카(`.payload.json`)에 소스 사본이 남았다.
        #   잘려 읽힌 파일은 넣지 않는다 — 소스 oracle 이 잘린 원문을 완전한 것으로 믿으면 안 된다.
        "source_files": {
            path: source_text_cache[path]
            for path in sorted({str(d.get("source_path") or "") for d in function_details.values()
                                if d.get("source_text_complete")})
            if path and source_text_cache.get(path)
        },
        # (R81) 프로젝트 C 문맥 — 대상 정수 폭(typedef 증언)·전처리 이벤트·매크로·열거자·전역·함수 쓰기 효과. MC/DC 설계가
        #   프로젝트 헤더(`U16`, `((U16)(5000U / u8g_T_MAIN))`, 헤더 전역)를 **선언에서** 해석하는 입력이다. 잘려 읽힌 파일은
        #   넣지 않는다(뒷부분의 `#undef`·재정의를 못 본 채 값을 확정하면 안 된다) — 빠진 파일은 `incomplete_files` 에 남긴다.
        "project_context": _build_project_context(source_text_cache, _read_truncated, _roots, _src_walk, _src_read),
        # {fid: body 앞 400자}. detail 밖에 두어 by_name 중복 직렬화를 피한다(위 선언부 주석).
        "function_body_snippets": function_body_snippets,
        # 동일 이름 다중정의(파일 간 충돌) — by_name은 last-wins이므로 이 맵이 없으면 영향분석이
        # 다른 사본의 파일 변경을 놓치고(under-report) 낮은 ASIL로 오판한다. {name: {files, asil}}.
        "function_collisions": function_collisions,
        # 전역 인식에서 **잃은 것**. 스캔 캡·미사용 판정·접두사 필터·타입없음 네 지점이
        # 전부 조용히 자르므로, 이 값이 없으면 "이 프로젝트엔 원래 전역이 없다" 로 오독한다.
        "globals_scan": _globals_loss,
        # (R65 N74) Prototype 의 출처 — 헤더를 쓴 함수 수와 **정의를 지킨 이유별 함수 이름**. 같은 이름의 헤더가 다른 트리에만
        #   있거나(other_root) 인자 수가 다르거나(arity) 같은 트리 후보끼리 다르면(conflict) 헤더를 고르지 않았다는 기록이다.
        "prototype_scan": {"counts": _proto_scan, "definition_kept": _proto_kept},
        # (R62) 죽은 `#if 0` 분기라 함수 목록에서 뺀 정의. tree-sitter 경로가 뺀 것은 여기 안 센다(그쪽은 애초에 목록에
        # 오른 적이 없다) — 이 값은 "정규식 경로가 예전엔 되살리던 것" 이다.
        "dead_code_excluded": {
            "files": len(_dead_code_excluded),
            "functions": sum(len(v) for v in _dead_code_excluded.values()),
            "by_file": _dead_code_excluded,
            # (R63 N70) 같은 구간에서 뺀 전역·매크로·프로토타입 — 종류별 개수(파일 기준 발생 수)와 {파일: [이름]}.
            "globals": sum(len(v) for v in _dead_decls_excluded.get("globals", {}).values()),
            "macros": sum(len(v) for v in _dead_decls_excluded.get("macros", {}).values()),
            "prototypes": sum(len(v) for v in _dead_decls_excluded.get("prototypes", {}).values()),
            "decls_by_file": _dead_decls_excluded,
        },
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
