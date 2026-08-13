"""report_gen.function_analyzer - Auto-split from report_generator.py"""
# Re-import common dependencies
import re
import os
import json
import csv
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from report_gen.provenance import is_weak_source
from workflow.code_parser.c_parser import blank_c_comments, c_identifiers
from report_gen.utils import (
    _normalize_related_ids,
    _normalize_swufn_id,
    _extract_call_names,
    _normalize_call_field,
    _dedupe_multiline_text,
    _normalize_asil_value,
)

_logger = logging.getLogger("report_generator")

def _split_signature_param_chunks(param_text: str) -> List[str]:
    chunks: List[str] = []
    cur: List[str] = []
    paren_depth = 0
    bracket_depth = 0
    angle_depth = 0
    for ch in str(param_text or ""):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "<":
            angle_depth += 1
        elif ch == ">":
            angle_depth = max(0, angle_depth - 1)
        if ch == "," and paren_depth == 0 and bracket_depth == 0 and angle_depth == 0:
            token = "".join(cur).strip()
            if token:
                chunks.append(token)
            cur = []
            continue
        cur.append(ch)
    token = "".join(cur).strip()
    if token:
        chunks.append(token)
    return chunks


def _extract_param_symbol(param_text: str) -> str:
    raw = str(param_text or "").strip()
    if not raw:
        return ""
    m_func_ptr = re.search(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)", raw)
    if m_func_ptr:
        return str(m_func_ptr.group(1) or "").strip()
    m_array = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])\s*$", raw)
    if m_array:
        return str(m_array.group(1) or "").strip()
    m_name = re.search(r"([A-Za-z_]\w*)\s*$", raw)
    if not m_name:
        return ""
    name = str(m_name.group(1) or "").strip()
    if name.lower() in {"const", "volatile", "restrict", "struct", "union", "enum"}:
        return ""
    return name


def _parse_signature_params(signature: str, tag_direction: bool = False) -> List[str]:
    # ⚠ **주석부터 지운다.** LIN 스택처럼 파라미터마다 앞에 설명 주석을 다는 코드가 있다:
    #       void lin_lld_sci_rx_response(
    #           /* [IN] Length of response data expect to wait */
    #           l_u8 msg_length )
    #   주석을 남기면 세 곳이 동시에 망가진다(실측 2026-08-12, KJPDS02 23개 unit):
    #     1. 주석이 `_split_param` 의 **타입 문자열**로 들어가 파라미터 엔트리가
    #        `/* [IN] Length … */ l_u8 msg_length` 가 된다 → 소비처(`generators/suts.py`)
    #        가 "선언이 아님" 으로 통째로 버려 **입력 열이 빈다**
    #     2. `pointer_range = "*" in ptype` 이 주석의 `/*` 를 포인터로 읽어 포인터가
    #        아닌 `l_u8` 에 `(range: 0x0 ~ 0xFFFFFFFF)` 를 붙인다 — **없는 근거**다
    #     3. 주석 안의 콤마에서 `_split_signature_param_chunks` 가 쪼개
    #        파라미터 하나가 **둘로 찢어진다**(`lin_tl_make_slaveres_pdu` 실측)
    #   길이 보존 blank 라 아래 공백 정규화가 그대로 흡수한다.
    signature = blank_c_comments(signature)
    if not signature or "(" not in signature or ")" not in signature:
        return []
    params = signature.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not params or params.lower() == "void":
        return []
    chunks = _split_signature_param_chunks(params)
    items: List[str] = []
    for idx, raw in enumerate(chunks, start=1):
        part = " ".join(raw.replace("\n", " ").split()).strip()
        part = re.sub(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)", r"* \1", part)
        part = re.sub(r"\(\s*\*\s*\)\s*\(", "(*fn)(", part)
        part = re.sub(r"\s*\[\s*([^\]]*)\s*\]\s*$", r"[\1]", part)
        if part and re.match(r"^(const|volatile)\s+[A-Za-z_]\w*$", part):
            part = f"{part} param"
        if part and not _extract_param_symbol(part):
            part = f"{part} __arg{idx}"
        if part and tag_direction:
            is_const = bool(re.search(r"\bconst\b", part))
            is_ptr = "*" in part or "[" in part
            if is_const:
                part = f"[IN] {part}"
            elif is_ptr:
                part = f"[INOUT] {part}"
            else:
                part = f"[IN] {part}"
        if part:
            items.append(part)
    return items


def _strip_comments_and_strings(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    text = re.sub(r"\"(\\\\.|[^\"])*\"", "\"\"", text)
    text = re.sub(r"'(\\\\.|[^'])+'", "''", text)
    return text


# 이 프로젝트(MISRA-C)는 상수를 **캐스트 + 정수 접미사**로 감싼다:
#   #define u8s_FIT_MAX_BUFFER  ( ( U8 )( 9U ) )      #define TEMP_LUT_SIZE (5U)
#   #define SHA256_DIGEST_SIZE  ( U8 )32U             #define PWM_CHANNEL_COUNT 2U
# 아래 화이트리스트는 `U`·`L` 을 불허하므로 이런 값은 통째로 안 접히고 **배열 크기가
# 조용히 사라진다**. 실측(KJPDS02): 배열 차원에 쓰인 매크로 13종이 **전부** 이 형태다.
_INT_SUFFIX_RE = re.compile(r"\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]+\b")
# ⚠ 캐스트는 **뒤에 피연산자가 붙을 때만** 캐스트다. `(UNKNOWN) + 3` 의 괄호까지 지우면
#   남은 `+ 3` 이 3 으로 평가돼 **모르는 값을 3 이라고 지어낸다**. 그래서 lookahead 로
#   `(` 나 숫자가 바로 뒤따를 때만 벗긴다.
_C_CAST_RE = re.compile(
    r"\(\s*(?:const|volatile|signed|unsigned)?\s*[A-Za-z_]\w*\s*\**\s*\)\s*(?=[(\d])"
)


def _strip_c_literal_noise(expr: str) -> str:
    """`( ( U8 )( 9U ) )` → `(  ( 9 ) )`. 캐스트는 중첩될 수 있어 반복한다(상한 4)."""
    out = _INT_SUFFIX_RE.sub(r"\1", str(expr or ""))
    for _ in range(4):
        nxt = _C_CAST_RE.sub(" ", out)
        if nxt == out:
            break
        out = nxt
    return out


def _safe_eval_int(expr: str) -> Optional[int]:
    if not expr:
        return None
    try:
        expr = _strip_c_literal_noise(expr.strip())
        if not re.match(r"^[0-9xXa-fA-F\+\-\*/\(\)\s]+$", expr):
            return None
        return int(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return None


def _subst_macros(raw: str, macro_map: Dict[str, str], depth: int = 4) -> str:
    """식에 **실제로 나타난** 식별자만 치환하고, 값이 또 매크로면 반복한다.

    ⚠ 예전엔 매크로 맵 **전체**를 돌며 매번 `re.sub` 했다(KJPDS02 는 5,622개) —
      느린 데다 **한 번만** 돌아서 `#define A (B + 10u)` 처럼 값 안에 또 매크로가
      든 경우를 못 접었다.
    """
    for _ in range(depth):
        # ⚠ `set` 순회 순서는 실행마다 달라진다. 어떤 매크로 값이 같은 라운드의 다른
        #   매크로 이름을 품고 있으면 치환 순서가 결과를 바꿔 **산출물이 실행마다
        #   달라진다**(캐시 시그니처가 무의미해진다). 정렬해 고정한다.
        hits = sorted(n for n in set(re.findall(r"\b[A-Za-z_]\w*\b", raw))
                      if macro_map.get(n))
        if not hits:
            break
        for n in hits:
            raw = re.sub(rf"\b{re.escape(n)}\b", str(macro_map[n]), raw)
    return raw


def _normalize_bracket_expr(expr: str, macro_map: Dict[str, str]) -> Tuple[str, Optional[int]]:
    raw = (expr or "").strip()
    if not raw:
        return "", None
    raw = _subst_macros(raw, macro_map)
    val = _safe_eval_int(raw)
    if val is not None:
        return str(val), val
    return raw, None


# 선언 첨자는 여러 개일 수 있다(`[5][7][7]`). 통짜로 접으면 `[3][4]` 가 `3][4` 가 돼
# `_safe_eval_int` 도 실패하고 `isdigit()` 도 거짓이라 **조용히 크기가 사라진다**.
_DIM_RE = re.compile(r"\[([^\]]*)\]")


def _normalize_dims(dims: str, macro_map: Dict[str, str]) -> List[str]:
    """`[A][B]` → `['9', '8']`. 각 차원을 **따로** 접는다. 브래킷이 없으면 통째로 한 차원."""
    raw = str(dims or "").strip()
    if not raw:
        return []
    found = _DIM_RE.findall(raw) or [raw]
    return [_normalize_bracket_expr(d, macro_map)[0] for d in found]


def _split_param(param: str) -> Tuple[str, str, str]:
    text = " ".join(param.replace("\n", " ").split()).strip()
    if not text:
        return "", "", ""
    array_part = ""
    # ⚠ 첨자는 **여러 개**(`[3][4]`)일 수도, **비어 있을**(`U8 data[]`) 수도 있다.
    #   하나·비지 않음으로 가정하면 남은 텍스트가 `]` 로 끝나 아래 이름 정규식이
    #   실패하고 **이름이 통째로 타입 쪽으로 넘어간다**(`S16 t[3][4]` → 이름 ''·
    #   타입 'S16 t[3]' → 표기 `S16 t[3] [4]`). 이름이 없으면 소비처가 그 변수를
    #   식별할 수 없다.
    m = re.search(r"((?:\[[^\]]*\])+)\s*$", text)
    if m:
        array_part = m.group(1)
        text = text[: m.start()].strip()
    name_match = re.search(r"([A-Za-z_]\w*)$", text)
    if not name_match:
        return text, "", array_part
    name = name_match.group(1)
    type_text = text[: name_match.start()].strip()
    type_text = type_text.replace("  ", " ").strip()
    return type_text, name, array_part


# 변수 이름 **뒤에** 올 수 있는 접근자 꼬리(`.f` · `->f` · `[i]`, 섞여서 반복).
# ⚠ **첨자를 반드시 포함해야 한다.** 없으면 `arr[i] = f(i);` 가 대입으로 안 잡히고
#   맨 아래 "이름이 보이면 읽기" 분기로 떨어져 **쓰기 전용 배열이 시험 입력이 된다**.
#   실측(2026-08-12, KJPDS02): EEPROM read 계열
#   `u8g_SysEepromCtrl_ProdDateInfo[u8t_Idx] = u8g_…_ReadProdDate((U16)u8t_Idx);` 4건이
#   정본엔 입력 0개인데 우리는 입력으로 냈다.
_ACCESS_TAIL = r"(?:\s*(?:->|\.)\s*\w+|\s*\[[^\]]*\])*"


def _new_usage_slot() -> Dict[str, Any]:
    return {
        "lhs": False,
        "rhs": False,
        "inout": False,
        "lhs_idx": None,
        "rhs_idx": None,
        "members": set(),
        "indexes": set(),
        "divisor": False,
    }


def _scan_name_usage(lines: List[str], name: str, u: Dict[str, Any]) -> None:
    """한 이름의 읽기/쓰기 방향을 라인 스캔으로 채운다.

    ⚠ 전역 이름과 **매크로 이름**이 반드시 같은 판정을 쓰도록 단일 출처로 뺐다.
      예전엔 매크로 경로가 판정을 복제하지 않고 `rhs = True` 를 **무조건** 세웠다.
      그래서 `PTAD_PTADL4 = big_RESET;` 처럼 **쓰기만 하는 레지스터**가 읽기로
      기록되고, 이어서 `_written` 이 `inout` 까지 세워 시험 **입력**으로 올라갔다.
      실측(2026-08-12, KJPDS02): 읽기 캡을 풀어 매크로가 3.2배로 늘자 이 결함이
      그대로 확대돼 "정본은 입력 0개인데 우리는 값을 낸" unit 이 34 → 44 로 늘었다.
    """
    for idx, line in enumerate(lines):
        if not line.strip() or name not in line:
            continue
        for m in re.finditer(rf"\b{re.escape(name)}\b\s*(->|\.)\s*([A-Za-z_]\w*)", line):
            u["members"].add(f"{name}{m.group(1)}{m.group(2)}")
        for m in re.finditer(rf"\b{re.escape(name)}\b\s*\[\s*([^\]]+)\s*\]", line):
            u["indexes"].add(m.group(1).strip())
        if re.search(rf"/\s*\(?\s*\b{re.escape(name)}\b", line):
            u["divisor"] = True
        if re.search(
            rf"(\+\+|--)\s*\b{re.escape(name)}\b"
            rf"|\b{re.escape(name)}\b{_ACCESS_TAIL}\s*(\+\+|--)",
            line,
        ):
            u["lhs"] = True
            u["rhs"] = True
            u["inout"] = True
            continue
        if re.search(
            rf"\b{re.escape(name)}\b{_ACCESS_TAIL}\s*(\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=)",
            line,
        ):
            u["lhs"] = True
            u["rhs"] = True
            u["inout"] = True
            continue
        m_assign = re.search(rf"\b{re.escape(name)}\b{_ACCESS_TAIL}\s*=(?!=)", line)
        if m_assign:
            u["lhs"] = True
            if u["lhs_idx"] is None:
                u["lhs_idx"] = idx
            rhs = line[m_assign.end():]
            if re.search(rf"\b{re.escape(name)}\b", rhs):
                u["rhs"] = True
                u["inout"] = True
            continue
        if re.search(rf"\b{re.escape(name)}\b", line):
            u["rhs"] = True
            if u["rhs_idx"] is None:
                u["rhs_idx"] = idx


def _collect_var_usage(
    body_text: str,
    var_names: List[str],
    macro_globals: Dict[str, List[str]] | None = None,
    macro_expansions: Dict[str, str] | None = None,
) -> Dict[str, Dict[str, Any]]:
    usage: Dict[str, Dict[str, Any]] = {n: _new_usage_slot() for n in var_names}
    if not body_text or not var_names:
        return usage
    text = _strip_comments_and_strings(body_text)
    lines = text.splitlines()
    if macro_globals:
        _expansions = macro_expansions or {}
        # 본문을 **한 번만** 토큰화한다. 매크로 이름은 항상 식별자라 `\bNAME\b` 검색과
        # 토큰 멤버십이 동치인데, 비용은 O(매크로) 정규식 vs O(1) 조회로 갈린다.
        # ⚠ 이게 없으면 읽기 캡 해제가 그대로 폭탄이 된다 — 매크로 맵이 3.2배로 늘고
        #   이 루프는 **함수마다** 도므로 1,157함수 × 10,000매크로 = 1,160만 회
        #   재컴파일이다(re 캐시 512개라 전부 미스). 실측 파싱이 4.5분에서 수십 분이 된다.
        _body_toks = set(c_identifiers(text))
        for m_name, globals_list in macro_globals.items():
            if not m_name or not globals_list:
                continue
            if m_name not in _body_toks:
                continue
            # 본문엔 매크로 이름만 있으므로 아래 전역 라인 스캔은 이 사용을 **절대**
            # 못 본다(`PTT_PTT3 = big_RESET;`). 매크로 이름으로 같은 스캔을 돌려
            # 방향을 구한 뒤, 그 방향을 전역에 합류시킨다.
            mu = _new_usage_slot()
            _scan_name_usage(lines, m_name, mu)
            for g in globals_list:
                if g not in usage:
                    continue
                u = usage[g]
                # ⚠ **방향 축만** 합류시킨다. members/indexes 는 매크로 이름 기준이라
                #   (`RXBUF0.foo`) 전역 경로로 쓸 수 없다 — 전역 쪽 이름은 아래 확장형이 준다.
                for k in ("lhs", "rhs", "inout"):
                    u[k] = bool(u[k]) or bool(mu[k])
                for k in ("lhs_idx", "rhs_idx"):
                    if u[k] is None and mu[k] is not None:
                        u[k] = mu[k]
                # 매크로 확장형을 멤버 경로로 등록한다. 이게 없으면 이름이 base 로만 남아
                # `_PTT` 가 되는데, 정본은 비트 필드까지 적는다(`_PTT.Bits.PTT3`).
                exp = str(_expansions.get(m_name) or "").strip()
                if exp and exp != g and re.match(rf"^{re.escape(g)}\s*(?:\.|->|\[)", exp):
                    u["members"].add(re.sub(r"\s+", "", exp))
    for name in var_names:
        _scan_name_usage(lines, name, usage[name])
    for u in usage.values():
        if u["inout"]:
            continue
        if u["lhs"] and u["rhs"]:
            u["inout"] = True
            continue
        if u["lhs_idx"] is not None and u["rhs_idx"] is not None:
            u["inout"] = True
    return usage


def _extract_primary_condition(body_text: str) -> str:
    def _normalize_condition(cond: str) -> str:
        cond = " ".join(str(cond or "").replace("\n", " ").split())
        if not cond:
            return ""
        cond = re.sub(r"\b([A-Za-z_]\w*)\s*!=\s*0\b", r"\1", cond)
        cond = re.sub(r"\b([A-Za-z_]\w*)\s*==\s*0\b", r"!\1", cond)
        cond = cond.replace("&&", " AND ").replace("||", " OR ")
        cond = re.sub(r"\s+", " ", cond).strip()
        if len(cond) > 42:
            cond = cond[:39].rstrip() + "..."
        return cond

    def _extract_paren_expr(text: str, start: int) -> str:
        depth = 0
        i = start
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i]
            i += 1
        return text[start + 1:min(start + 80, len(text))]

    text = _strip_comments_and_strings(body_text or "")
    if not text:
        return ""
    m_sw = re.search(r"\bswitch\s*\(", text, flags=re.S)
    if m_sw:
        expr = _extract_paren_expr(text, m_sw.end() - 1)
        cases = re.findall(r"\bcase\s+([^:]+):", text)
        if cases:
            case_labels = [c.strip() for c in cases[:4]]
            return _normalize_condition(f"switch({expr.strip()}): {', '.join(case_labels)}")
        return _normalize_condition(f"switch({expr.strip()})")

    conditions: list = []
    for m in re.finditer(r"\b(?:else\s+)?if\s*\(", text, flags=re.S):
        expr = _extract_paren_expr(text, m.end() - 1)
        if expr:
            conditions.append(expr.strip())
        if len(conditions) >= 3:
            break

    if conditions:
        if len(conditions) == 1:
            return _normalize_condition(conditions[0])
        return _normalize_condition(" / ".join(conditions[:3]))

    m_while = re.search(r"\bwhile\s*\(", text, flags=re.S)
    if m_while:
        expr = _extract_paren_expr(text, m_while.end() - 1)
        if expr:
            return _normalize_condition(expr.strip())

    m_for = re.search(r"\bfor\s*\(([^;]*);([^;]*);", text, flags=re.S)
    if m_for:
        cond = " ".join(str(m_for.group(2) or "").split())
        if cond:
            return _normalize_condition(cond)

    return ""


def _extract_condition_branch_calls(body_text: str) -> Tuple[List[str], List[str]]:
    text = _strip_comments_and_strings(body_text or "")
    if not text:
        return [], []
    m_sw = re.search(r"\bswitch\s*\(([^)]+)\)\s*\{(?P<body>.*?)\}", text, flags=re.S)
    if m_sw:
        body = str(m_sw.group("body") or "")
        case_blocks = re.findall(r"\bcase\b[^:]*:(?P<c>.*?)(?=\bcase\b|\bdefault\b|})", body, flags=re.S)
        m_default = re.search(r"\bdefault\s*:(?P<d>.*?)(?=\bcase\b|})", body, flags=re.S)
        default_block = str(m_default.group("d") or "") if m_default else ""
        all_case_calls: list = []
        for cb in case_blocks:
            block = cb if isinstance(cb, str) else cb[0] if cb else ""
            for c in _extract_call_names(block):
                if c not in all_case_calls:
                    all_case_calls.append(c)
        false_calls = list(dict.fromkeys(_extract_call_names(default_block)))
        return all_case_calls, false_calls
    m = re.search(
        r"\bif\s*\([^)]*\)\s*\{(?P<t>.*?)\}(?:\s*else\s*(?:if\s*\([^)]*\)\s*)?(?:\{(?P<f>.*?)\}))?",
        text,
        flags=re.S,
    )
    if not m:
        return [], []
    true_block = str(m.group("t") or "")
    false_block = str(m.group("f") or "")
    true_calls = list(dict.fromkeys(_extract_call_names(true_block)))
    false_calls = list(dict.fromkeys(_extract_call_names(false_block)))
    return true_calls, false_calls


def _extract_logic_terminal_paths(body_text: str) -> Tuple[str, str]:
    text = _strip_comments_and_strings(body_text or "")
    if not text:
        return "", ""
    has_return = bool(re.search(r"\breturn\b", text))
    has_error = bool(re.search(r"\b(error|fail|fault|exception|timeout|invalid)\b", text, flags=re.I))
    return ("Return" if has_return else "", "Error End" if has_error else "")


def _extract_logic_flow(body_text: str, all_calls: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Extract a structured control-flow representation from C function body.

    Returns a list of flow nodes, each being one of:
      {"type": "call", "name": "func_name"}
      {"type": "if", "condition": "expr",
       "true_body": [nodes], "false_body": [nodes]}
      {"type": "switch", "expr": "var",
       "cases": [{"label": "CASE_X", "calls": [names]}],
       "default_calls": [names]}
      {"type": "loop", "kind": "for"|"while"|"do", "condition": "expr",
       "body": [nodes]}
      {"type": "return", "value": "expr"}
      {"type": "assign", "text": "short description"}
    """
    raw = _strip_comments_and_strings(body_text or "")
    if not raw:
        return []

    # Strip outer function-body braces
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        raw = stripped[1:-1]

    known_calls = set(str(c).strip() for c in (all_calls or []) if str(c).strip())

    def _paren_expr(text: str, start: int) -> Tuple[str, int]:
        depth, i = 0, start
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i].strip(), i + 1
            i += 1
        return text[start + 1:min(start + 80, len(text))].strip(), len(text)

    def _brace_block(text: str, start: int) -> Tuple[str, int]:
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i], i + 1
            i += 1
        return text[start + 1:], len(text)

    def _norm_cond(c: str) -> str:
        c = " ".join(c.replace("\n", " ").split()).strip()
        c = re.sub(r"\b([A-Za-z_]\w*)\s*!=\s*0\b", r"\1", c)
        c = re.sub(r"\b([A-Za-z_]\w*)\s*==\s*0\b", r"!\1", c)
        c = c.replace("&&", " AND ").replace("||", " OR ")
        c = re.sub(r"\s+", " ", c).strip()
        if len(c) > 60:
            c = c[:57].rstrip() + "..."
        return c

    def _calls_in(block: str) -> List[str]:
        found: List[str] = []
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", block):
            nm = m.group(1)
            if nm in known_calls and nm not in found:
                found.append(nm)
        return found

    def _parse_block(text: str, depth: int = 0) -> List[Dict[str, Any]]:
        if depth > 4 or not text or not text.strip():
            return []
        nodes: List[Dict[str, Any]] = []
        pos = 0
        text_len = len(text)
        pending_calls: List[str] = []

        def _flush_pending():
            nonlocal pending_calls
            for c in pending_calls:
                nodes.append({"type": "call", "name": c})
            pending_calls = []

        while pos < text_len:
            # Skip whitespace
            ws = re.match(r"\s+", text[pos:])
            if ws:
                pos += ws.end()
                if pos >= text_len:
                    break

            # --- switch ---
            m_sw = re.match(r"\bswitch\s*\(", text[pos:])
            if m_sw:
                _flush_pending()
                expr, after_paren = _paren_expr(text, pos + m_sw.end() - 1)
                ws2 = re.match(r"\s*", text[after_paren:])
                brace_start = after_paren + (ws2.end() if ws2 else 0)
                if brace_start < text_len and text[brace_start] == "{":
                    body, after_brace = _brace_block(text, brace_start)
                    cases: List[Dict[str, Any]] = []
                    case_blocks = re.split(r"\bcase\b", body)
                    default_calls: List[str] = []
                    for cb in case_blocks[1:]:
                        lbl_m = re.match(r"\s*([^:]+):", cb)
                        label = lbl_m.group(1).strip() if lbl_m else "?"
                        block_text = cb[lbl_m.end():] if lbl_m else cb
                        dm = re.search(r"\bdefault\s*:", block_text)
                        if dm:
                            default_calls = _calls_in(block_text[dm.end():])
                            block_text = block_text[:dm.start()]
                        calls = _calls_in(block_text)
                        if calls:
                            cases.append({"label": label, "calls": calls})
                    if not default_calls:
                        dm_top = re.search(r"\bdefault\s*:(.+?)(?=\bcase\b|})", body, flags=re.S)
                        if dm_top:
                            default_calls = _calls_in(dm_top.group(1))
                    nodes.append({
                        "type": "switch", "expr": _norm_cond(expr),
                        "cases": cases[:8], "default_calls": default_calls[:4],
                    })
                    pos = after_brace
                    continue

            # --- if / else if / else ---
            m_if = re.match(r"\bif\s*\(", text[pos:])
            if m_if:
                _flush_pending()
                cond, after_paren = _paren_expr(text, pos + m_if.end() - 1)
                ws2 = re.match(r"\s*", text[after_paren:])
                brace_start = after_paren + (ws2.end() if ws2 else 0)
                true_body_text = ""
                false_body_text = ""
                if brace_start < text_len and text[brace_start] == "{":
                    true_body_text, after_true = _brace_block(text, brace_start)
                else:
                    stmt_end = text.find(";", after_paren)
                    if stmt_end >= 0:
                        true_body_text = text[after_paren:stmt_end + 1]
                        after_true = stmt_end + 1
                    else:
                        after_true = after_paren

                # Check for else
                ws3 = re.match(r"\s*", text[after_true:])
                else_start = after_true + (ws3.end() if ws3 else 0)
                m_else = re.match(r"\belse\b\s*", text[else_start:])
                if m_else:
                    after_else_kw = else_start + m_else.end()
                    m_elif = re.match(r"\bif\s*\(", text[after_else_kw:])
                    if m_elif:
                        false_body_text = ""
                        after_false = else_start
                        # Parse else-if as a nested if in false_body
                        sub = _parse_block(text[after_else_kw:], depth + 1)
                        if sub:
                            node = {
                                "type": "if", "condition": _norm_cond(cond),
                                "true_body": _parse_block(true_body_text, depth + 1),
                                "false_body": sub,
                            }
                            nodes.append(node)
                            # Advance past the else-if chain heuristically
                            remaining = text[after_else_kw:]
                            if remaining.strip().startswith("if"):
                                m_skip = re.match(r"\bif\s*\(", remaining)
                                if m_skip:
                                    _, ap = _paren_expr(remaining, m_skip.end() - 1)
                                    ws_b = re.match(r"\s*", remaining[ap:])
                                    bs = ap + (ws_b.end() if ws_b else 0)
                                    if bs < len(remaining) and remaining[bs] == "{":
                                        _, af = _brace_block(remaining, bs)
                                        pos = after_else_kw + af
                                    else:
                                        se = remaining.find(";", ap)
                                        pos = after_else_kw + (se + 1 if se >= 0 else ap)
                                else:
                                    pos = after_else_kw
                            else:
                                pos = after_else_kw
                            continue
                    elif after_else_kw < text_len and text[after_else_kw:].lstrip().startswith("{"):
                        ws4 = re.match(r"\s*", text[after_else_kw:])
                        fb_start = after_else_kw + (ws4.end() if ws4 else 0)
                        false_body_text, after_false = _brace_block(text, fb_start)
                    else:
                        stmt_end = text.find(";", after_else_kw)
                        if stmt_end >= 0:
                            false_body_text = text[after_else_kw:stmt_end + 1]
                            after_false = stmt_end + 1
                        else:
                            after_false = after_else_kw
                else:
                    after_false = after_true

                node = {
                    "type": "if", "condition": _norm_cond(cond),
                    "true_body": _parse_block(true_body_text, depth + 1),
                    "false_body": _parse_block(false_body_text, depth + 1),
                }
                nodes.append(node)
                pos = after_false
                continue

            # --- for / while / do-while loops ---
            m_for = re.match(r"\bfor\s*\(", text[pos:])
            m_while = re.match(r"\bwhile\s*\(", text[pos:])
            m_do = re.match(r"\bdo\b\s*\{?", text[pos:])
            if m_for or m_while:
                _flush_pending()
                m_loop = m_for or m_while
                kind = "for" if m_for else "while"
                cond, after_paren = _paren_expr(text, pos + m_loop.end() - 1)
                ws2 = re.match(r"\s*", text[after_paren:])
                bs = after_paren + (ws2.end() if ws2 else 0)
                if bs < text_len and text[bs] == "{":
                    loop_body, after_body = _brace_block(text, bs)
                    loop_cond = cond
                    if kind == "for":
                        parts = cond.split(";")
                        loop_cond = parts[1].strip() if len(parts) > 1 else cond
                    nodes.append({
                        "type": "loop", "kind": kind,
                        "condition": _norm_cond(loop_cond),
                        "body": _parse_block(loop_body, depth + 1),
                    })
                    pos = after_body
                    continue
            if m_do:
                _flush_pending()
                ws2 = re.match(r"\s*\{?", text[pos + m_do.end():])
                bs = pos + m_do.end()
                while bs < text_len and text[bs] != "{":
                    bs += 1
                if bs < text_len:
                    loop_body, after_body = _brace_block(text, bs)
                    m_wcond = re.match(r"\s*while\s*\(", text[after_body:])
                    if m_wcond:
                        cond, _ = _paren_expr(text, after_body + m_wcond.end() - 1)
                    else:
                        cond = ""
                    nodes.append({
                        "type": "loop", "kind": "do",
                        "condition": _norm_cond(cond),
                        "body": _parse_block(loop_body, depth + 1),
                    })
                    pos = after_body
                    semi = text.find(";", pos)
                    pos = semi + 1 if semi >= 0 else pos
                    continue

            # --- return ---
            m_ret = re.match(r"\breturn\b\s*([^;]*);?", text[pos:])
            if m_ret:
                _flush_pending()
                val = m_ret.group(1).strip()
                nodes.append({"type": "return", "value": val[:50] if val else ""})
                pos += m_ret.end()
                continue

            # --- function call or assignment ---
            m_call = re.match(r"([A-Za-z_]\w*)\s*\(", text[pos:])
            if m_call:
                nm = m_call.group(1)
                if nm in known_calls:
                    pending_calls.append(nm)
                _, after_call = _paren_expr(text, pos + m_call.end() - 1)
                semi = text.find(";", after_call)
                pos = semi + 1 if semi >= 0 else after_call
                continue

            # --- skip to next statement ---
            semi = text.find(";", pos)
            if semi >= 0:
                stmt = text[pos:semi].strip()
                if stmt and re.search(r"\b([A-Za-z_]\w*)\s*\(", stmt):
                    for cm in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", stmt):
                        cname = cm.group(1)
                        if cname in known_calls and cname not in pending_calls:
                            pending_calls.append(cname)
                pos = semi + 1
            else:
                break

        _flush_pending()
        return nodes

    result = _parse_block(raw)

    # Compact: remove empty if-bodies and trivial nodes
    def _compact(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for n in nodes:
            if n["type"] == "if":
                tb = _compact(n.get("true_body") or [])
                fb = _compact(n.get("false_body") or [])
                if tb or fb:
                    out.append({"type": "if", "condition": n["condition"],
                                "true_body": tb, "false_body": fb})
            elif n["type"] == "switch":
                cases = [c for c in n.get("cases", []) if c.get("calls")]
                dc = n.get("default_calls", [])
                if cases or dc:
                    out.append({"type": "switch", "expr": n["expr"],
                                "cases": cases, "default_calls": dc})
            elif n["type"] == "loop":
                body = _compact(n.get("body") or [])
                if body:
                    out.append({"type": "loop", "kind": n.get("kind", "while"),
                                "condition": n["condition"], "body": body})
            else:
                out.append(n)
        return out

    return _compact(result)


def _format_param_entry(
    name: str,
    type_text: str,
    array_part: str,
    index_values: List[str],
    macro_map: Dict[str, str],
    pointer_range: bool,
    divisor: bool = False,
    *,
    size_hint: str = "",
) -> str:
    """엔트리 표시 문자열. 꼬리는 **이름 뒤에만** 붙는다.

    `size_hint` 는 **전역**의 선언 배열 차원(`[60]`)이다. 파라미터는 `array_part` 로
    이미 `buf[10]` 을 만들지만 전역엔 그 자리가 없어, 정본이 원소 단위로 펼쳐 적는
    배열(입력 엔트리의 50.3%)의 크기를 소비처(`generators/suts.py`)가 알 방법이
    없었다. `(size: N)` 꼬리로 실어 보낸다 — 꼬리 목록은 `_PARAM_ANNOT_KEYS` 단일 출처.
    """
    display = name
    if array_part:
        dims = _normalize_dims(array_part, macro_map)
        if dims and all(dims):
            display = display + "".join(f"[{d}]" for d in dims)
    if size_hint:
        dims = _normalize_dims(size_hint, macro_map)
        # 숫자로 접힌 것만 싣는다. `[MAX_LEN]` 처럼 못 접은 값을 실으면 소비처가
        # 원소 개수를 알 수 없어 **확장을 조용히 건너뛴다** — 그건 크기가 없는 것과 같다.
        # 다차원은 `9x8` 로 싣는다(차원을 곱해 버리면 소비처가 `[i][j]` 를 못 만든다).
        if dims and all(d.isdigit() for d in dims):
            display = f"{display} (size: {'x'.join(dims)})"
    if index_values:
        display = f"{display} (idx: {', '.join(index_values)})"
    if pointer_range:
        display = f"{display} (range: 0x00000000 ~ 0xFFFFFFFF)"
    if divisor:
        display = f"{display} (divisor: no 0)"
    if type_text:
        return f"{type_text} {display}".strip()
    return display


def _extract_return_type(signature: str, func_name: str) -> str:
    if not signature:
        return ""
    head = signature.split(func_name, 1)[0] if func_name and func_name in signature else signature
    head = re.sub(r"\b(static|extern|inline)\b", "", head).strip()
    head = " ".join(head.split())
    return head


def _classify_param_direction(param: str) -> str:
    param_norm = " ".join(param.split())
    if "*" in param_norm:
        if re.search(r"\bconst\b", param_norm):
            return "[IN]"
        return "[INOUT]"
    if "[" in param_norm and "]" in param_norm:
        return "[INOUT]"
    if re.search(r"\b(struct|union)\b", param_norm, re.I):
        return "[INOUT]"
    return "[IN]"


def _parse_signature_outputs(signature: str, func_name: str) -> List[str]:
    outputs: List[str] = []
    if signature:
        head = signature.split(func_name, 1)[0] if func_name and func_name in signature else signature
        head = re.sub(r"\b(static|extern|inline)\b", "", head).strip()
        head = " ".join(head.split())
        if head and "void" not in head:
            outputs.append(f"[OUT] return {head}")
    for param in _parse_signature_params(signature):
        param_norm = " ".join(param.split())
        p_lower = param_norm.lower()
        if ("*" in param_norm or "[" in param_norm and "]" in param_norm) and "const" not in p_lower:
            outputs.append(f"{_classify_param_direction(param_norm)} {param_norm}")
            continue
        if re.search(r"\b(struct|union)\b", param_norm, re.I):
            outputs.append(f"{_classify_param_direction(param_norm)} {param_norm}")
            continue
        # Function pointer arguments may carry callbacks used for output/state changes.
        if "(*" in param_norm and "const" not in p_lower:
            outputs.append(f"{_classify_param_direction(param_norm)} {param_norm}")
    return outputs


def _fallback_function_description(
    func_name: str,
    called: Any = None,
) -> str:
    name = str(func_name or "").strip() or "해당 소프트웨어 유닛"
    called_list: List[str] = []
    if isinstance(called, list):
        called_list = [str(x).strip() for x in called if str(x).strip()]
    elif isinstance(called, str):
        for token in re.split(r"[,\n]+", called):
            t = token.strip()
            if t:
                called_list.append(t)
    lname = name.lower()
    _ACTION_MAP = [
        (["init", "startup", "boot", "setup"], "초기화 절차를 수행하고 기본 파라미터를 설정한다"),
        (["diag", "check", "monitor", "detect", "verify"], "상태를 점검하고 진단 결과를 갱신한다"),
        (["update", "refresh", "calc", "conv", "compute", "process"], "입력 데이터를 처리하여 연산 결과를 갱신한다"),
        (["ctrl", "control", "manage", "regulate"], "제어 조건을 평가하고 출력 상태를 결정한다"),
        (["error", "fault", "protect", "safe"], "오류 조건을 감시하고 안전 보호 동작을 실행한다"),
        (["read", "get", "load", "fetch"], "요청된 데이터를 읽어 반환한다"),
        (["write", "set", "store", "save"], "지정된 값을 대상 레지스터 또는 메모리에 기록한다"),
        (["send", "transmit", "tx"], "통신 프로토콜에 따라 데이터를 송신한다"),
        (["recv", "receive", "rx"], "통신 채널로부터 데이터를 수신하여 버퍼에 저장한다"),
        (["isr", "interrupt", "handler"], "인터럽트 발생 시 해당 이벤트를 처리한다"),
        (["timer", "schedule", "period", "cyclic"], "주기적 타이머 이벤트를 처리한다"),
        (["enable", "activate", "start", "on"], "대상 모듈 또는 출력을 활성화한다"),
        (["disable", "deactivate", "stop", "off", "shutdown"], "대상 모듈 또는 출력을 비활성화한다"),
        (["reset", "clear", "clr"], "내부 상태 및 플래그를 초기 상태로 리셋한다"),
        (["limit", "clamp", "saturate", "bound"], "입력값을 허용 범위 내로 제한한다"),
        (["filter", "smooth", "average", "lpf"], "입력 신호에 필터링을 적용하여 노이즈를 제거한다"),
        (["convert", "map", "scale", "transform"], "입력값을 목적 단위 또는 형식으로 변환한다"),
        (["sort", "search", "find", "lookup"], "데이터 검색 또는 정렬을 수행한다"),
        (["log", "record", "trace"], "동작 이력을 기록한다"),
        (["test", "validate", "assert"], "지정된 조건을 검증하고 결과를 판정한다"),
    ]
    action = "소프트웨어 유닛의 지정된 동작을 수행한다"
    for keywords, desc in _ACTION_MAP:
        if any(k in lname for k in keywords):
            action = desc
            break
    parts = re.split(r"(?=[A-Z])|_", name)
    parts = [p for p in parts if p and p.lower() not in {"s", "g", "fn", "func"}]
    context = " ".join(parts[:3]) if parts else ""
    if called_list:
        chain = ", ".join(called_list[:5])
        return f"{name}: {context} 모듈에서 {action}. 주요 호출 대상: {chain}."
    return f"{name}: {context} 모듈에서 {action}."


# LLM 이 **작업을 거절한 문장**. 설명이 아니라 거절이므로 어떤 출처 등급으로도
# 산출물에 실리면 안 된다.
#
# ⚠ `_GENERIC_DESC_PATTERNS`(아래)와 **다른 축**이다. 그쪽은 "내용이 없는 상투구" 라
#   더 나은 문구로 **보강**하면 되지만, 거절문은 보강 대상이 아니라 **거부** 대상이다.
#   실제로 `_is_generic_description("I'm sorry, I cannot generate a description…")`
#   은 `False` 를 돌려준다 — 상투구 목록으로는 안 잡힌다(실측).
#
# 출처: 삭제한 `workflow/ai_validator.py::validate_llm_response` 의 `banned_patterns`.
# 그 모듈은 프로덕션 호출자가 0이라 **한 번도 발화한 적이 없었고**(§6 후보 10), 6개
# 공개 API 중 4개는 live 구현과 중복이었다. 중복이 아닌 유일한 검사가 이것이라
# 여기로 옮기고 나머지는 지웠다. ⚠ 같이 있던 `min_length=20` 은 **가져오지 않았다** —
# 실사용 채택 기준이 `len > 5`(1패스)/`len > 10`(2패스)라, 20자로 올리면 6~20자
# 정상 한국어 설명이 새로 거절된다.
_LLM_REFUSAL_PATTERNS = (
    "as an ai",
    "i'm sorry",
    "i am sorry",
    "i cannot",
    "i can't",
    "죄송합니다",
    "제공할 수 없습니다",
    "생성할 수 없습니다",
    "답변할 수 없습니다",
)


def is_llm_refusal(text: Any) -> bool:
    """LLM 이 거절한 문장인가 — **판정 단일 출처**.

    소비처 둘이 리터럴로 각자 적으면 이 저장소가 네 번 겪은 "복제 → 한쪽만 고쳐짐" 이
    된다:
      - `workflow/uds_ai.py::_process_batch`  AI 설명 **채택 관문**
      - `report_gen/function_analyzer.py::_finalize_function_fields`
        `trusted_desc` 화이트리스트가 `"ai"` 를 내용검사에서 면제하던 자리
    """
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(p in lowered for p in _LLM_REFUSAL_PATTERNS)


_GENERIC_DESC_PATTERNS = [
    "auto-generated from",
    "함수의 동작을 수행한다",
    "요구된 기능을 수행한다",
    "tbd",
    "입력/상태 데이터를 처리하고 후속 제어 흐름을 진행한다",
    "핵심 동작을 수행한다",
    "기능을 수행한다.",
    "해당 소프트웨어 유닛",
    "지정된 동작을 수행한다",
]

_DESC_TERM_MAP = {
    "POR": "Power On Reset",
    "WDI": "Watchdog Interface",
    "Diag": "Diagnosis",
    "Ctrl": "Control",
    "Init": "Initialization",
    "ISR": "Interrupt Service Routine",
    "Tmout": "Timeout",
    "Eeprom": "EEPROM",
    "Rpm": "Revolutions per minute",
}


def _is_exact_generic(desc: str) -> bool:
    s = str(desc or "").strip().lower()
    return s in {"function", "func", "n/a", "tbd", "-", "none", ""}


def _is_generic_description(desc: str) -> bool:
    s = " ".join(str(desc or "").split()).strip().lower()
    if not s:
        return True
    if _is_exact_generic(s):
        return True
    return any(p in s for p in _GENERIC_DESC_PATTERNS)


def _classify_description_quality(
    desc: str, source: str = ""
) -> str:
    s = str(desc or "").strip()
    src = str(source or "").strip().lower()
    if not s:
        return "low"
    trusted = src in {"comment", "sds", "reference", "srs", "ai"}
    if trusted:
        if _is_generic_description(s):
            return "medium"
        return "high"
    if _is_generic_description(s):
        return "low"
    if is_weak_source(src):
        if len(s) > 30:
            return "medium"
        return "low"
    return "medium"


def _split_func_name_words(name: str) -> List[str]:
    """Split function name (camelCase/snake_case/prefix) into readable words."""
    s = str(name or "").strip()
    s = re.sub(r"^[sgu]\d*[sg]?_", "", s, count=1)
    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", s).split("_")
    words = [w.strip() for w in parts if w.strip() and w.strip().lower() not in {"s", "g", "u8", "u16", "u32", "s16", "fn"}]
    return words


def _enhance_function_description(func_name: str, called: Any = None, module_hint: str = "") -> str:
    name = str(func_name or "").strip()
    if name.lower() in {"function", "func", "unknown"}:
        name = "UnnamedUnit"
    lname = name.lower()
    called_list: List[str] = []
    if isinstance(called, list):
        called_list = [str(x).strip() for x in called if str(x).strip()]
    elif isinstance(called, str):
        called_list = [str(x).strip() for x in re.split(r"[,\n]+", called) if str(x).strip()]
    module_text = str(module_hint or "").strip()

    if lname == "main":
        if called_list:
            init_call = called_list[0]
            remain = called_list[1:6]
            if remain:
                return (
                    f"POR(Power On Reset) 시 {init_call}를 호출하여 시스템을 초기화하고, "
                    f"이후 {', '.join(remain)}를 순차적으로 수행한다."
                )
            return f"POR(Power On Reset) 시 {init_call}를 호출하여 시스템을 초기화한다."
        return "시스템의 메인 제어 루프를 수행한다."

    if lname.startswith(("s_init_", "g_init_")):
        return f"{name} 함수는 시스템 초기 설정 및 상태 변수를 초기화한다."
    if lname.startswith(("s_system", "g_system", "s_sys", "g_sys")):
        if called_list:
            return f"{name} 함수는 시스템 상태를 점검하고 {', '.join(called_list[:4])}를 호출하여 제어를 수행한다."
        return f"{name} 함수는 시스템 상태를 점검하고 제어한다."
    if lname.startswith(("u8s_", "u16s_", "s16s_", "u32s_")) and "conv" in lname:
        return f"{name} 함수는 입력 신호를 변환/스케일링하여 내부 제어 값으로 갱신한다."

    name_words = _split_func_name_words(name)
    readable = " ".join(name_words).strip() if name_words else name

    if called_list:
        prefix = f"{module_text} 모듈의 " if module_text else ""
        return f"{prefix}{name}은(는) {', '.join(called_list[:5])}를 호출하며 {readable} 로직을 실행한다."
    return f"{name}은(는) {readable} 관련 연산을 수행하고 결과를 반영한다."


def _enhance_description_text(func_name: str, desc: str, called: Any = None) -> str:
    name = str(func_name or "").strip() or "UnnamedUnit"
    if name.lower() in {"function", "func", "unknown"}:
        name = "UnnamedUnit"
    text = " ".join(str(desc or "").split()).strip()
    called_list: List[str] = []
    if isinstance(called, list):
        called_list = [str(x).strip() for x in called if str(x).strip()]
    elif isinstance(called, str):
        called_list = [str(x).strip() for x in re.split(r"[,\n]+", called) if str(x).strip()]
    lname = name.lower()
    if (not text) or text.startswith("Auto-generated from"):
        name_words = _split_func_name_words(name)
        readable = " ".join(name_words).strip() if name_words else name
        action = f"{readable} 관련 연산을 수행하고 결과를 반영한다"
        if any(k in lname for k in ["init", "startup", "boot", "setup"]):
            action = "시스템 초기화를 수행한다"
        elif any(k in lname for k in ["reset", "clear", "cleanup"]):
            action = "상태를 초기값으로 재설정한다"
        elif any(k in lname for k in ["diag", "check", "monitor", "detect", "verify"]):
            action = "상태를 점검하고 진단 결과를 갱신한다"
        elif any(k in lname for k in ["update", "refresh", "measure", "calc", "compute"]):
            action = "입력 데이터를 처리하여 상태 값을 갱신한다"
        elif any(k in lname for k in ["ctrl", "control", "manage", "regulate"]):
            action = "제어 로직을 수행하고 상태 전이를 관리한다"
        elif any(k in lname for k in ["send", "transmit", "tx", "write"]):
            action = "데이터를 전송한다"
        elif any(k in lname for k in ["recv", "receive", "rx", "read"]):
            action = "데이터를 수신하고 파싱한다"
        elif any(k in lname for k in ["parse", "decode", "extract"]):
            action = "수신 데이터를 해석하여 내부 구조체에 저장한다"
        elif any(k in lname for k in ["encode", "compose", "build", "pack"]):
            action = "내부 데이터를 프로토콜 형식으로 구성한다"
        elif any(k in lname for k in ["handle", "process", "run", "execute"]):
            action = "수신된 요청이나 이벤트를 처리한다"
        elif any(k in lname for k in ["get", "fetch", "query", "lookup"]):
            action = "요청된 데이터를 조회하여 반환한다"
        elif any(k in lname for k in ["set", "configure", "assign"]):
            action = "지정된 값으로 설정을 변경한다"
        elif any(k in lname for k in ["crc", "checksum", "hash"]):
            action = "데이터 무결성 검증을 위한 체크섬을 계산한다"
        elif any(k in lname for k in ["schedule", "timer", "periodic"]):
            action = "주기적 스케줄링 동작을 수행한다"
        elif "sleep" in lname:
            action = "절전 진입/복귀 제어를 수행한다"
        elif any(k in lname for k in ["callback", "handler", "isr", "interrupt"]):
            action = "이벤트 또는 인터럽트 발생 시 콜백 처리를 수행한다"
        elif any(k in lname for k in ["state", "status", "flag"]):
            action = f"{readable} 상태를 확인하고 전이 조건을 평가한다"
        elif any(k in lname for k in ["conv", "convert", "transform", "scale"]):
            action = "입력 값을 변환/스케일링하여 출력한다"
        elif any(k in lname for k in ["error", "fault", "fail"]):
            action = "오류 상태를 감지하고 안전 동작을 수행한다"
        elif any(k in lname for k in ["adc", "pwm", "gpio", "spi", "i2c", "uart", "can", "lin"]):
            action = f"{readable} 하드웨어 인터페이스를 제어한다"
        elif any(k in lname for k in ["buzzer", "led", "lamp", "display", "sound"]):
            action = f"{readable} 출력 장치를 제어한다"
        elif any(k in lname for k in ["task", "job", "worker"]):
            action = f"{readable} 태스크를 실행하고 완료 상태를 갱신한다"
        elif any(k in lname for k in ["protect", "safe", "guard", "lock"]):
            action = f"{readable} 보호 로직을 수행한다"
        elif any(k in lname for k in ["limit", "clamp", "bound", "range"]):
            action = "입력 값을 허용 범위 내로 제한한다"
        text = f"{name}은(는) {action}."
        if called_list:
            text += f" 주요 호출: {', '.join(called_list[:5])}."
    if _is_generic_description(text):
        text = _enhance_function_description(name, called_list)
    for src, dst in _DESC_TERM_MAP.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and not text.endswith("."):
        text += "."
    return text


def _normalize_symbol_name(raw: str) -> str:
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return ""
    # Split duplicated wrapped fragments from merged DOCX cells.
    first = re.split(r"[\r\n|,;]+", text)[0].strip()
    if not first:
        return ""
    m = re.search(r"[A-Za-z_]\w*", first)
    return (m.group(0) if m else first).strip()


def _finalize_function_fields(info: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(info or {})
    name_text = str(out.get("name") or "").strip()
    desc_raw = str(out.get("description") or "").strip()
    desc_source = str(out.get("description_source") or "").strip().lower()
    # ⚠ **거절문은 설명이 아니다** — 값이 없는 것과 같이 취급한다(§6 후보 10).
    #    신뢰 출처(`ai`/`comment`/`sds`/`reference`)는 아래에서 내용검사를 **면제**받아
    #    원문 그대로 통과하므로, 여기서 비우지 않으면 "I'm sorry, I cannot generate…"
    #    같은 문장이 납품 UDS 의 설명 칸에 그대로 실린다.
    #    ⚠ `trusted_desc = … and not is_llm_refusal(…)` 만으로는 **부족했다**: else 분기의
    #      `_enhance_description_text` 는 상투구가 아닌 텍스트를 그대로 돌려주고
    #      `_is_generic_description(거절문)` 은 False 라, 거절문이 살아남는다(실측).
    #      값을 비워 폴백 생성으로 보내야 한다.
    if desc_raw and is_llm_refusal(desc_raw):
        _logger.warning(
            "함수 %s 의 설명이 모델 거절문이라 채택하지 않는다(출처=%s): %.60s",
            name_text or "?", desc_source or "-", desc_raw,
        )
        desc_raw = ""
        desc_source = ""
        out["description"] = ""
        out["description_source"] = ""
    trusted_desc = desc_source in {"ai", "comment", "sds", "reference"}
    if not desc_raw:
        desc_raw = _fallback_function_description(
            name_text,
            out.get("called") or out.get("calls_list") or [],
        )
        out["description_source"] = out.get("description_source") or "inference"
    if trusted_desc and desc_raw:
        out["description"] = desc_raw
    else:
        desc_enhanced = _enhance_description_text(
            name_text,
            str(desc_raw or ""),
            out.get("called") or out.get("calls_list") or [],
        )
        if _is_generic_description(desc_enhanced):
            desc_enhanced = _enhance_function_description(
                name_text,
                out.get("called") or out.get("calls_list") or [],
                str(out.get("module_name") or ""),
            )
            out["description_source"] = out.get("description_source") or "inference"
        out["description"] = desc_enhanced
    # ⚠ 예전엔 `if not asil: asil="QM"; asil_source="default"` 였다. 지웠다 —
    #   근거의 부재를 등급 주장으로 바꾸지 않는다(`docx_builder._inherit_module_asil` 참조).
    # ⚠ 정규화 결과를 **무조건 대입**하던 것도 고쳤다. `_normalize_asil_value` 는
    #   `"TBD"`/`"N/A"`/`"-"` 를 빈 문자열로 접는다(계약: `tests/unit/test_report_gen.py:79`).
    #   순위 비교(`requirements.py:2237`)에선 그게 맞지만, 값 칸에 그대로 대입하면
    #   **"미정"(TBD)과 "아예 없음"(빈칸)이 같은 것이 된다.** 정규화는 값을 다듬는
    #   것이지 지우는 게 아니므로, 등급을 못 뽑으면 원래 표기를 보존한다.
    _asil_norm = _normalize_asil_value(str(out.get("asil") or ""))
    out["asil"] = _asil_norm if _asil_norm else str(out.get("asil") or "").strip()
    if not str(out.get("related") or "").strip():
        out["related"] = "TBD"
        out["related_source"] = out.get("related_source") or "inference"
    out["related"] = _normalize_related_ids(str(out.get("related") or ""))
    if not str(out.get("precondition") or "").strip():
        out["precondition"] = "N/A"
    out["precondition"] = _dedupe_multiline_text(str(out.get("precondition") or ""), na_to_empty=True) or "N/A"
    if name_text.lower() == "main":
        out["related"] = "SwST_01, SwCom_01, SwSTR_01, SwSTR_02, SwSTR_04, SwSTR_06, SwSTR_09"
        out["related_source"] = out.get("related_source") or "rule"
    for key in ("inputs", "outputs", "globals_global", "globals_static"):
        val = out.get(key)
        if not isinstance(val, list):
            out[key] = []
            continue
        norm_vals: List[str] = []
        for item in val:
            s = str(item or "").strip()
            if not s or s.lower() in {"none", "n/a", "na", "-"}:
                continue
            norm_vals.append(s)
        out[key] = norm_vals
    out["called"] = _normalize_call_field(str(out.get("called") or ""))
    out["calling"] = _normalize_call_field(str(out.get("calling") or ""))
    return out


def _is_static_var(name: str, static_name_map: Dict[str, bool]) -> bool:
    if not name:
        return False
    mapped = static_name_map.get(name)
    if mapped is not None:
        return mapped
    from config import STATIC_VAR_PREFIXES
    return any(name.startswith(p) for p in STATIC_VAR_PREFIXES)


_PRECOND_PATTERNS: List[re.Pattern] = [
    re.compile(r"if\s*\(\s*!?\s*\w*(?:Init|initialized|ready|enabled|done)\w*\s*\)", re.I),
    re.compile(r"assert\s*\(\s*(.{5,60}?)\s*\)"),
    re.compile(r"if\s*\(\s*\w+\s*==\s*NULL\s*\)", re.I),
    re.compile(r"if\s*\(\s*NULL\s*==\s*\w+\s*\)", re.I),
    re.compile(r"if\s*\(\s*\w+\s*[!=]=\s*(?:TRUE|FALSE|0[xX][0-9a-fA-F]+|0)\s*\)"),
]


def _infer_precondition_from_body(body: str, func_name: str = "") -> str:
    if not body:
        return ""
    first_lines = body[:600]
    conditions: List[str] = []
    for pat in _PRECOND_PATTERNS:
        m = pat.search(first_lines)
        if m:
            conditions.append(m.group(0).strip())
    if conditions:
        return "; ".join(conditions[:3])
    if re.search(r"(?:_Init|Init|Initialize|Setup)\b", func_name, re.I):
        return "N/A (initialization function)"
    return ""


def _build_function_info_rows(info: Dict[str, Any], cols: int) -> List[List[str]]:
    info = _finalize_function_fields(info)
    name_text = str(info.get("name") or "").strip()
    name_norm = re.sub(r"[^a-z0-9_]", "", name_text.lower())
    proto_text = str(info.get("prototype") or "").strip()
    if not proto_text and name_norm == "main":
        info["prototype"] = "void main( void )"
    if name_norm == "main":
        info["related"] = "SwST_01, SwCom_01, SwSTR_01, SwSTR_02, SwSTR_04, SwSTR_06, SwSTR_09"
    if not str(info.get("description") or "").strip():
        info["description"] = _fallback_function_description(
            str(info.get("name") or ""),
            info.get("called") or info.get("calls_list") or [],
        )
    pairs: List[Tuple[str, str]] = []
    pairs.append(("ID", _normalize_swufn_id(str(info.get("id") or ""))))
    pairs.append(("Name", str(info.get("name") or "")))
    pairs.append(("Prototype", str(info.get("prototype") or "")))
    pairs.append(("Description", str(info.get("description") or "")))
    pairs.append(("ASIL", str(info.get("asil") or "")))
    pairs.append(("Related ID", str(info.get("related") or "")))
    if info.get("show_mapping_evidence"):
        pairs.append(("ASIL Source", str(info.get("asil_source") or "N/A")))
        evidence_parts: List[str] = []
        if str(info.get("sds_match_key") or "").strip():
            evidence_parts.append(f"key={info.get('sds_match_key')}")
        if str(info.get("sds_match_mode") or "").strip():
            evidence_parts.append(f"mode={info.get('sds_match_mode')}")
        if str(info.get("sds_match_scope") or "").strip():
            evidence_parts.append(f"scope={info.get('sds_match_scope')}")
        if info.get("mapping_confidence") not in (None, ""):
            evidence_parts.append(f"confidence={info.get('mapping_confidence')}")
        if str(info.get("related_source") or "").strip():
            evidence_parts.append(f"related_source={info.get('related_source')}")
        pairs.append(("Mapping Evidence", ", ".join(evidence_parts) if evidence_parts else "N/A"))
    inputs = info.get("inputs") or []
    outputs = info.get("outputs") or []
    formatted_inputs = []
    for param in inputs:
        p = str(param).strip()
        if not p:
            continue
        if p.startswith("[IN") or p.startswith("("):
            formatted_inputs.append(p)
        else:
            formatted_inputs.append(f"{_classify_param_direction(p)} {p}")
    pairs.append(("Input Parameters", "\n".join(formatted_inputs) if formatted_inputs else "N/A"))
    pairs.append(("Output Parameters", "\n".join([str(x) for x in outputs if x]) if outputs else "N/A"))
    pairs.append(("Precondition", str(info.get("precondition") or "") or "N/A"))
    globals_global = info.get("globals_global") or []
    globals_static = info.get("globals_static") or []
    pairs.append(
        (
            "Used Globals (Global)",
            "\n".join([str(x) for x in globals_global if x]) if globals_global else "N/A",
        )
    )
    pairs.append(
        (
            "Used Globals (Static)",
            "\n".join([str(x) for x in globals_static if x]) if globals_static else "N/A",
        )
    )
    pairs.append(("Called Function", _normalize_call_field(str(info.get("called") or "")) or "N/A"))
    pairs.append(("Calling Function", _normalize_call_field(str(info.get("calling") or "")) or "N/A"))
    pairs.append(("Logic Diagram", str(info.get("logic") or "")))

    rows: List[List[str]] = []
    if cols >= 6:
        for k, v in pairs:
            row = [k, k, v, v, v, v]
            rows.append(row[:cols])
        return rows
    cells_per_row = max(2, cols // 2 * 2)
    pairs_per_row = max(1, cells_per_row // 2)
    row: List[str] = []
    for idx, (k, v) in enumerate(pairs):
        row.extend([k, v])
        if (idx + 1) % pairs_per_row == 0:
            rows.append(row[:cells_per_row])
            row = []
    if row:
        while len(row) < cells_per_row:
            row.append("")
        rows.append(row[:cells_per_row])
    return rows

