"""report_gen.source_parser - Auto-split from report_generator.py"""
# Re-import common dependencies
import re
import os
import json
import csv
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Set

_logger = logging.getLogger("report_generator")

_CALL_SKIP_WORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "case",
    "else",
}
_STATIC_STORAGE_WORDS = (
    "static",
    "STATIC",
    "FAST_STATIC",
    "NEAR_STATIC",
    "STATIC_VAR",
    "STATIC_DATA",
    "FAR_STATIC",
    "SECTION_STATIC",
)
_DECL_QUALIFIER_WORDS = {
    "const",
    "volatile",
    "register",
    "signed",
    "unsigned",
    "short",
    "long",
    "auto",
}


def _iter_c_statements(text: str, top_level_only: bool = False) -> List[str]:
    if not text:
        return []
    clean = _strip_c_comments(text)
    statements: List[str] = []
    cur: List[str] = []
    brace_depth = 0
    paren_depth = 0
    bracket_depth = 0
    in_preprocessor = False
    at_line_start = True
    prev = ""
    for ch in clean:
        if at_line_start:
            if ch in " \t":
                pass
            elif ch == "#":
                in_preprocessor = True
            at_line_start = False
        if ch == "\n":
            if in_preprocessor and prev != "\\":
                in_preprocessor = False
            at_line_start = True
            if not top_level_only or brace_depth == 0:
                cur.append(ch)
            prev = ch
            continue
        if in_preprocessor:
            prev = ch
            continue
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        if not top_level_only or brace_depth == 0:
            cur.append(ch)
        if ch == ";" and paren_depth == 0 and bracket_depth == 0 and (not top_level_only or brace_depth == 0):
            stmt = "".join(cur).strip()
            if stmt:
                statements.append(stmt)
            cur = []
        prev = ch
    tail = "".join(cur).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_decl_items(text: str) -> List[str]:
    items: List[str] = []
    cur: List[str] = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for ch in str(text or ""):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
        if ch == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            token = "".join(cur).strip()
            if token:
                items.append(token)
            cur = []
            continue
        cur.append(ch)
    token = "".join(cur).strip()
    if token:
        items.append(token)
    return items


# `const` 판정 **단일 출처**. 소비처가 셋이다(uds_generator 의 타입 병합 · generators/suts
# 의 전역 억제 · 테스트). 이 저장소는 판정을 복제했다가 한쪽만 고쳐진 전례가 여러 번이다.
# ⚠ 단어 경계 필수 — `constant_t` 같은 타입 이름이 걸리면 멀쩡한 전역을 지운다.
_CONST_TYPE_RE = re.compile(r"\bconst\b", re.I)


def is_const_type(type_text: Any) -> bool:
    """선언 타입이 `const` 한정자를 갖는가. `None`·빈 값은 판정 불가 → False."""
    return bool(_CONST_TYPE_RE.search(str(type_text or "")))


# 선언자 **끝**의 배열 차원(`[60]` · `[MAX][2]` · 크기 미지정 `[]`).
_DECL_ARRAY_DIM_RE = re.compile(r"((?:\s*\[[^\]]*\])+)\s*$")


def _decl_array_dim(decl: str) -> str:
    """선언자에서 배열 차원만 뽑는다. 배열이 아니면 빈 문자열.

    ⚠ `_extract_decl_name_and_type` 은 이 부분을 **버린다** — 정규식이
      `(?:\\[[^\\]]*\\])?` 로 매치만 하고 캡처하지 않는다. 그래서
      `static U8 u8s_DataBuffer[60];` 이 `{'name': …, 'type': 'U8'}` 로만 남고
      크기 60 은 산출물 어디에도 없다(디스크 캐시 `static_vars` 로 확인).

      정본 SUTS 는 배열을 **원소 단위로 펼쳐** 적는다 — 실측(KJPDS02_PV): 입력 엔트리
      6,014 중 **3,023(50.3%)** 이 `name[N]` 형태이고, 134개 base 중 **120개가 모든
      unit 에서 같은 개수**로 나온다(= 관찰된 접근 첨자가 아니라 선언 크기). 크기가
      없으면 그 절반을 재현할 근거 자체가 없다.

    ⚠ **`_extract_decl_name_and_type` 의 튜플 폭을 넓히지 않는다.** 테스트 4곳이
      2-튜플로 언팩하고 있고, 이 저장소는 추출기 튜플이 3→4 로 넓어졌을 때 소비처
      한 곳이 남아 `ValueError` 로 4개월간 조용히 깨진 전례가 있다
      (`_scan_source_function_names` 주석 참조). 그래서 별도 함수로 뽑는다.
    """
    text = str(decl or "").strip().rstrip(";").split("=", 1)[0].strip()
    if not text or "(" in text:  # 함수 포인터 선언자는 대상이 아니다
        return ""
    m = _DECL_ARRAY_DIM_RE.search(text)
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(1))


def _extract_decl_name_and_type(decl: str, base_type: str) -> Tuple[str, str]:
    text = str(decl or "").strip().rstrip(";")
    text = text.split("=", 1)[0].strip()
    if not text:
        return "", ""
    m_func_ptr = re.search(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)", text)
    if m_func_ptr:
        name = str(m_func_ptr.group(1) or "").strip()
        return name, f"{base_type} *".strip()
    # ⚠ 첨자는 **여러 개**일 수 있다(`[5][7][7]`). 하나만 허용하면 다차원 선언에서
    #   정규식이 통째로 실패하고 `_parse_c_declaration_statement` 가 **빈 리스트**를
    #   낸다 — 크기가 없는 게 아니라 **변수 자체가 사라진다**. 실측(KJPDS02):
    #   `static U16 u16s_MovgAvgFltBuff[u8s_FIT_MAX_BUFFER][u8g_LIB_FLT_MAX_CNT];`
    #   가 파서 산출 900함수 어디에도 없었다(정본은 72원소로 펼쳐 적는다).
    m_name = re.search(r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])*\s*$", text)
    if not m_name:
        return "", ""
    name = str(m_name.group(1) or "").strip()
    prefix = text[: m_name.start()].strip()
    pointer_suffix = " *" if "*" in prefix else ""
    return name, f"{base_type}{pointer_suffix}".strip()


def _parse_c_declaration_statement(stmt: str) -> List[Dict[str, str]]:
    compact = " ".join(str(stmt or "").replace("\n", " ").split()).strip().rstrip(";")
    if not compact:
        return []
    if compact.startswith("#"):
        return []
    if re.match(r"^\s*typedef\b", compact):
        return []
    if re.search(r"\b(?:if|for|while|switch)\b", compact):
        return []
    # Strip __attribute__((...)) annotations before parsing
    compact = re.sub(r"__attribute__\s*\(\(.*?\)\)", "", compact).strip()
    # 절대주소 배치 접미사 `@0x000002C0` 제거 (Renesas/CodeWarrior 계열 SFR 선언).
    # ⚠ 안 지우면 **주소 리터럴이 변수명이 된다** — `extern volatile PTTSTR _PTT @0x000002C0;`
    #   이 `_PTT` 가 아니라 `x000002C0` 으로 등록됐다(선언자 마지막 토큰을 이름으로 잡기
    #   때문). 이 프로젝트 `Generated_Code/IO_Map.h` 한 파일에만 372건이라, 레지스터 전체가
    #   쓰레기 이름으로 들어가고 진짜 이름은 어디에도 없었다. `@` 는 C 토큰이 아니므로
    #   선언문에 나오면 배치 지정자로 봐도 안전하다.
    # ⚠ **정수 접미사(`[uUlL]`)까지 먹어야 한다.** `@0x00FF9DF0U` 에서 `0[xX][0-9A-Fa-f]+`
    #   는 `U` 앞에서 멈추므로(=16진수가 아님) `U` 한 글자가 선언문에 남고, 그게 마지막
    #   토큰이라 **변수명이 `U` 가 된다**. 실측(SysOs_Main.c `g_FirmwareVersionInfo`):
    #   그렇게 등록된 `U` 가 매크로 토큰화 결함(`123U`→`U`)과 맞물려 **324개 함수**에
    #   전역으로 붙었다 — 이 프로젝트 전역 부착 1위가 존재하지 않는 변수였다.
    compact = re.sub(
        r"@\s*(?:0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*)", " ", compact
    ).strip()

    storage_words: List[str] = []
    qualifiers: List[str] = []
    type_tokens: List[str] = []
    tokens = compact.split()
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        upper_tok = tok.upper()
        lower_tok = tok.lower()
        if tok in _STATIC_STORAGE_WORDS:
            storage_words.append(tok)
            idx += 1
            continue
        if lower_tok == "extern":
            storage_words.append(tok)
            idx += 1
            continue
        if lower_tok in _DECL_QUALIFIER_WORDS:
            qualifiers.append(tok)
            idx += 1
            continue
        if lower_tok in {"struct", "enum", "union"} and idx + 1 < len(tokens):
            type_tokens.extend([tok, tokens[idx + 1]])
            idx += 2
            continue
        type_tokens.append(tok)
        idx += 1
        break
    remainder = " ".join(tokens[idx:]).strip()
    if not remainder and type_tokens:
        remainder = type_tokens.pop()
    if not type_tokens:
        return []
    # Only reject function declarations; allow () in initializer (e.g. static int x = fn())
    name_part = remainder.split("=", 1)[0] if "=" in remainder else remainder
    if "(" in name_part and "(*" not in name_part:
        return []

    base_type = " ".join(qualifiers + type_tokens).strip()
    results: List[Dict[str, str]] = []
    for item in _split_decl_items(remainder):
        name, dtype = _extract_decl_name_and_type(item, base_type)
        if not name or not dtype:
            continue
        results.append(
            {
                "name": name,
                "type": dtype,
                # 배열 차원(`[60]`). 정본이 원소 단위로 펼쳐 적는 근거다 — `_decl_array_dim` 주석 참조.
                "array": _decl_array_dim(item),
                "init": item.split("=", 1)[1].strip() if "=" in item else "",
                "static": "true" if any(tok in _STATIC_STORAGE_WORDS for tok in storage_words) else "false",
                "extern": "true" if any(tok.lower() == "extern" for tok in storage_words) else "false",
            }
        )
    return results

def _read_bytes_resolver_aware(path: Path) -> bytes:
    """cloudium 모드면 worker IPC resolver로 read, 그 외(local/standalone)는 직접 read.
    backend 미가용(standalone report_gen)이면 조용히 로컬 경로로 폴백 → 회귀 0."""
    try:
        from backend.services.file_resolver import get_resolver
        r = get_resolver()
        if getattr(r, "mode", "local") != "local":
            return r.read_bytes(str(path))
    except Exception:
        pass
    return Path(path).read_bytes()


# C 원문 읽기 상한.
#
# ⚠ **옛 기본값 200,000 은 조용히 자르는 캡이었고, 이 프로젝트에서 실제로 잘랐다.**
#   실측(KJPDS02_PV, 2026-08-12):
#     Generated_Code/IO_Map.h        680,639 B → 29.4% 만 읽음
#       · 매크로 정의 5,622 중 **3,881 소실**
#       · extern 전역 후보 363 중 **251 소실**
#   레지스터 정의는 파일 뒤쪽에 몰려 있어 앞쪽 `_PTT`·`_FCLKDIV` 는 살아남고
#   뒤쪽 `_ADC0CTL`·`_SCI0CR2`·`_CPMUINT`·`_ECCIE`·`_LP0IF` 는 통째로 사라진다.
#   그래서 SFR 이 "부분적으로만" 인식되는 것처럼 보였다(파서 결함이 아니라 캡).
#
# ⚠ 이 캡은 **안전장치도 아니었다** — `_read_bytes_resolver_aware` 가 파일 전체를
#   이미 메모리로 읽은 **뒤** 잘라내므로 I/O·피크메모리를 아끼지 못한다. 게다가
#   tree-sitter 경로(`c_parser.parse_c_project`)는 같은 파일을 캡 없이 `read_bytes()`
#   로 읽는다 — 즉 두 경로의 **비대칭**이라, 전역 선언은 잡히는데 그 전역을 가리키는
#   매크로만 사라져 매크로 접기(`macro_globals_map`)가 조용히 죽었다.
#
# 상한 자체는 남긴다(병적으로 큰 생성 파일 방어). 대신 **닿으면 보고**한다 —
# `_read_source_text` 가 절단 여부를 돌려주고 호출자가 WARNING 으로 올린다.
_SRC_READ_MAX_BYTES = 2_000_000


def _read_source_text(
    path: Path, max_bytes: int = _SRC_READ_MAX_BYTES
) -> Tuple[str, int, bool]:
    """원문 텍스트와 함께 **원본 바이트 수 · 절단 여부**를 돌려준다.

    `_read_text_limited` 는 절단을 조용히 한다. 호출자가 "잘렸다" 를 셀 수 있어야
    "이 프로젝트엔 그 매크로가 원래 없다" 와 구분된다.
    """
    try:
        data = _read_bytes_resolver_aware(path)
    except Exception:
        return "", 0, False
    raw_len = len(data)
    truncated = bool(max_bytes) and raw_len > max_bytes
    if truncated:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8", errors="ignore"), raw_len, truncated
    except Exception:
        return "", raw_len, truncated


def _read_text_limited(path: Path, max_bytes: int = _SRC_READ_MAX_BYTES) -> str:
    return _read_source_text(path, max_bytes)[0]


def _strip_c_comments(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


# 주석 가리기는 **단일 출처**다 — 이 저장소가 반복해서 겪은 실패가 "판정 복제 후
# 한쪽만 고침" 이라, 두 파서(c_parser 정규식 폴백 · 여기)가 같은 함수를 쓴다.
# tree_sitter 유무와 무관하게 import 된다(c_parser 의 tree_sitter import 는 guarded).
from workflow.code_parser.c_parser import blank_c_comments as _blank_c_comments  # noqa: E402


def _extract_c_prototypes(text: str) -> List[Tuple[str, str, str, bool]]:
    """헤더에서 함수 프로토타입 추출. Returns [(name, params, return_type, is_extern)]."""
    if not text:
        return []
    results: List[Tuple[str, str, str, bool]] = []
    for match in re.finditer(
        r"^[\t ]*(extern\s+)?(__interrupt\s+)?([A-Za-z_][\w\s\*]*?)\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*;",
        text,
        flags=re.M,
    ):
        is_extern = bool(match.group(1))
        interrupt_prefix = (match.group(2) or "").strip()
        ret_type = " ".join((match.group(3) or "").split()).strip()
        name = match.group(4)
        params = " ".join(match.group(5).replace("\n", " ").split())
        if interrupt_prefix:
            ret_type = f"{interrupt_prefix}{ret_type}"
        results.append((name, params, ret_type, is_extern))
    return results


def _preprocess_isr_macros(text: str) -> str:
    """ISR(name) 매크로를 void name(void) 형태로 변환."""
    return re.sub(
        r'\bISR\s*\(\s*([A-Za-z_]\w*)\s*\)',
        r'void \1(void)',
        text,
    )


def _extract_c_definitions(text: str) -> List[Tuple[str, str, str, bool]]:
    """소스에서 함수 정의 추출. Returns [(name, params, return_type, is_static)]."""
    if not text:
        return []
    # ISR() 매크로 프리프로세싱
    text = _preprocess_isr_macros(text)
    # ⚠ 주석 안의 프로토타입을 함수로 만들지 않는다(`_blank_c_comments` 참조).
    #   길이를 유지하므로 아래 offset 기반 처리와 어긋나지 않는다.
    text = _blank_c_comments(text)
    keywords = {"if", "for", "while", "switch", "return", "sizeof"}
    results: List[Tuple[str, str, str, bool]] = []
    for match in re.finditer(
        r"^[\t ]*((?:static|__interrupt)\s+)?([A-Za-z_][\w\s\*]*?)\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*\{",
        text,
        flags=re.M,
    ):
        qualifier = (match.group(1) or "").strip()
        is_static = "static" in qualifier
        ret_type = " ".join((match.group(2) or "").split()).strip()
        name = match.group(3)
        if name in keywords:
            continue
        params = " ".join(match.group(4).replace("\n", " ").split())
        results.append((name, params, ret_type, is_static))
    return results


def _extract_c_function_bodies(text: str) -> Dict[str, str]:
    if not text:
        return {}
    out: Dict[str, str] = {}
    pat = re.compile(
        r"^[\t ]*(?:static\s+)?[A-Za-z_][\w\s\*\(\),]*?\s+([A-Za-z_]\w*)\s*\([^;]*?\)\s*\{",
        flags=re.M,
    )
    for m in pat.finditer(text):
        name = str(m.group(1) or "").strip()
        if not name:
            continue
        start = m.end() - 1  # points to "{"
        depth = 0
        end = start
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = text[start + 1 : end].strip() if end > start else ""
        if body:
            out[name] = body
    return out


def _extract_c_macros(text: str) -> List[str]:
    if not text:
        return []
    results: List[str] = []
    for match in re.finditer(r"^[\t ]*#\s*define\s+([A-Za-z_]\w+)", text, flags=re.M):
        results.append(match.group(1))
    return results


def _extract_c_macro_defs(text: str) -> List[Tuple[str, str]]:
    if not text:
        return []
    results: List[Tuple[str, str]] = []
    for match in re.finditer(
        r"^[\t ]*#\s*define[ \t]+([A-Za-z_]\w+)[ \t]+([^\r\n]+)",
        text,
        flags=re.M,
    ):
        name = match.group(1).strip()
        val = match.group(2).strip()
        if name:
            results.append((name, val))
    return results


# 구조체/공용체 멤버의 **배열 차원**. 정본 SUTS 는 `DiagData.CloseFailure[0..2]` 처럼
# 멤버 배열도 원소 단위로 적는데, 이 저장소는 struct 본문을 **한 번도 읽지 않았다**
# (`type_defs` 는 주석 표 섹션이라 멤버 차원이 없다). 실측 KJPDS02_PV: 정본 미달
# 1,511칸 중 112칸이 이 축 하나다.
#
# ⚠ 본문은 **중괄호 균형**으로 자른다. 정규식 `\{(.*?)\}` 는 중첩 union 에서 안쪽
#   `}` 에 멈춰 `ProgramStruct`(안에 `union {…} Add;`)의 멤버를 통째로 놓친다.
_STRUCT_HEAD_RE = re.compile(r"typedef\s+(?:struct|union)\b[^{;]*\{")
_STRUCT_TAIL_RE = re.compile(r"\s*(\w+)\s*;")
_INNER_HEAD_RE = re.compile(r"(?:struct|union)\s*\{")
# 멤버 선언: `UINT8 LIN_data[LIN_MAX_DATA_BYTES];` · `S16 t[3][4];`
# ⚠ **줄 시작에 기대지 않는다** — `typedef struct { int a[2]; int b[3]; } T;` 처럼
#   한 줄에 여러 멤버가 오면 `^...$` 를 `re.M` 으로 걸어도 첫 개만 잡고 나머지를
#   조용히 버린다. 멤버 구분자는 줄바꿈이 아니라 `;` 다.
# ⚠ 포인터 멤버(`UINT8 *p[4]`)는 제외한다 — 원소 수가 아니라 포인터 개수라
#   시험 변수로 펼치면 없는 대상을 적게 된다.
_STRUCT_MEMBER_RE = re.compile(
    r"^\s*(?:(?:const|volatile|static)\s+)*[A-Za-z_]\w*\s+"
    r"(\w+)\s*((?:\[[^\]]*\])+)\s*$"
)


def _iter_struct_members(body: str) -> Iterator[Tuple[str, str]]:
    """`;` 로 끊어 멤버 선언을 훑는다(줄바꿈 위치와 무관)."""
    for seg in str(body or "").split(";"):
        m = _STRUCT_MEMBER_RE.match(seg)
        if m:
            yield m.group(1), m.group(2)


def _balanced_block(text: str, open_at: int) -> int:
    """`text[open_at] == '{'` 에서 짝이 맞는 `}` 위치. 못 찾으면 -1."""
    depth = 0
    for j in range(open_at, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def extract_struct_member_arrays(text: str) -> Dict[str, Dict[str, str]]:
    """`타입명 → {멤버경로: 차원문자열}`. 차원은 **접기 전 원문**(`[LIN_MAX_DATA_BYTES]`).

    매크로 접기는 파일 전체를 다 읽은 뒤에야 가능하므로(값이 다른 헤더에 있다)
    여기서는 원문만 모으고, 접기는 호출부(`uds_generator`)가 `_normalize_dims` 로 한다.

    이름 붙은 중첩 블록은 `Add.ByteArray` 처럼 **경로**로 편다.

    ⚠ 주석은 **여기서** 지운다 — 호출부가 지웠겠거니 하면 안 된다. 멤버를 `;` 로
      끊는데 `UINT8 dataIndex;  /* … */\\n UINT8 dataBuffer[8];` 에서는 조각이
      `/* … */ UINT8 dataBuffer[8]` 로 시작해 앵커에 걸리지 않는다. 실측:
      `LIN_INT_CTRL` 이 통째로 빠졌는데 `LIN_FRAME` 은 **멤버에 주석이 없어서**
      우연히 통과해, 라이브에서만 8칸이 조용히 사라졌다.
    """
    out: Dict[str, Dict[str, str]] = {}
    if not text:
        return out
    text = _strip_c_comments(text)
    for head in _STRUCT_HEAD_RE.finditer(text):
        i = text.index("{", head.start())
        j = _balanced_block(text, i)
        if j < 0:
            continue
        tail = _STRUCT_TAIL_RE.match(text, j + 1)
        if not tail:
            continue
        body = text[i + 1:j]
        members = out.setdefault(tail.group(1), {})
        # ① 최상위 멤버 — 중첩 블록을 지운 뒤 훑는다(안쪽 멤버가 밖으로 새지 않게).
        flat = body
        for _ in range(6):
            nxt = re.sub(r"\{[^{}]*\}", " ", flat)
            if nxt == flat:
                break
            flat = nxt
        for mname, dims in _iter_struct_members(flat):
            members.setdefault(mname, dims)
        # ② 이름 붙은 중첩 블록 → `외부.내부`
        for inner in _INNER_HEAD_RE.finditer(body):
            ii = body.index("{", inner.start())
            jj = _balanced_block(body, ii)
            if jj < 0:
                continue
            iname = _STRUCT_TAIL_RE.match(body, jj + 1)
            if not iname:
                continue
            for mname, dims in _iter_struct_members(body[ii + 1:jj]):
                members.setdefault(f"{iname.group(1)}.{mname}", dims)
    return out


def _extract_c_global_candidates(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for stmt in _iter_c_statements(text, top_level_only=True):
        for item in _parse_c_declaration_statement(stmt):
            gname = str(item.get("name") or "").strip()
            gtype = str(item.get("type") or "").strip()
            if not gname or not gtype:
                continue
            if gname in seen:
                continue
            seen.add(gname)
            out.append(
                {
                    "name": gname,
                    "type": gtype,
                    "array": str(item.get("array") or "").strip(),
                    "init": str(item.get("init") or "").strip(),
                    "static": str(item.get("static") or "false").strip().lower(),
                    "extern": str(item.get("extern") or "false").strip().lower(),
                }
            )
    return out


def _extract_local_static_candidates(body_text: str) -> List[str]:
    """Return names of local static variables declared inside a function body.

    Strategy: combine AST-based detection (tree-sitter) with regex-based
    scanning.  AST handles standard ``static`` and custom macro storage words
    accurately; regex supplements with function-pointer declarators
    (``(*pfCb)``) that tree-sitter cannot parse cleanly.
    """
    if not body_text:
        return []
    regex_names = _extract_local_static_candidates_regex(body_text)
    ast_names = _extract_local_static_candidates_ast(body_text)
    if ast_names is None:
        return regex_names
    # Merge: AST results first, then any regex-only names appended
    seen: Set[str] = set(ast_names)
    merged = list(ast_names)
    for name in regex_names:
        if name not in seen:
            seen.add(name)
            merged.append(name)
    return merged


def _extract_local_static_candidates_regex(body_text: str) -> List[str]:
    """Regex-based local static variable detection (fallback)."""
    _static_kw_pat = re.compile(
        r"\b(?:" + "|".join(re.escape(w) for w in _STATIC_STORAGE_WORDS) + r")\b"
    )
    names: List[str] = []
    seen: Set[str] = set()
    for stmt in _iter_c_statements(body_text, top_level_only=False):
        if not _static_kw_pat.search(stmt):
            continue
        for item in _parse_c_declaration_statement(stmt):
            if str(item.get("static") or "").lower() != "true":
                continue
            name = str(item.get("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _extract_local_static_candidates_ast(body_text: str) -> Optional[List[str]]:
    """AST-based local static variable detection using tree-sitter.

    Returns a list of variable names on success, or None if tree-sitter is
    unavailable or parsing fails (caller falls back to regex).
    """
    try:
        from tree_sitter import Language, Parser  # type: ignore
        import tree_sitter_c as tsc  # type: ignore
    except ImportError:
        return None

    # Wrap the function body in a dummy function so the parser sees valid C
    wrapped = b"void __dummy__(void) {\n" + body_text.encode("utf-8", errors="replace") + b"\n}\n"
    try:
        lang = Language(tsc.language())
        parser = Parser(lang)
        tree = parser.parse(wrapped)
    except Exception:
        return None

    names: List[str] = []
    seen: Set[str] = set()
    _ast_collect_static_decls(tree.root_node, wrapped, names, seen)
    return names


_STATIC_STORAGE_BYTES = {w.encode() for w in _STATIC_STORAGE_WORDS}


def _ast_collect_static_decls(
    node: Any, source: bytes, names: List[str], seen: Set[str]
) -> None:
    """Recursively walk an AST node and collect names of static variable declarations.

    Handles both the standard C ``static`` keyword (parsed as
    ``storage_class_specifier``) and project-specific macro aliases such as
    ``FAST_STATIC`` or ``STATIC`` (parsed as type identifiers by tree-sitter).
    """
    if node.type == "declaration":
        is_static = any(
            (
                child.type == "storage_class_specifier"
                and source[child.start_byte : child.end_byte] == b"static"
            )
            or source[child.start_byte : child.end_byte] in _STATIC_STORAGE_BYTES
            for child in node.children
        )
        if is_static:
            for child in node.children:
                _ast_collect_declarator_names(child, source, names, seen)
    for child in node.children:
        _ast_collect_static_decls(child, source, names, seen)


def _ast_collect_declarator_names(
    node: Any, source: bytes, names: List[str], seen: Set[str]
) -> None:
    """Extract declared variable names from an AST declarator node."""
    if node.type in ("identifier",):
        name = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    elif node.type in (
        "init_declarator",
        "pointer_declarator",
        "array_declarator",
        "parenthesized_declarator",
    ):
        for child in node.children:
            _ast_collect_declarator_names(child, source, names, seen)
    elif node.type == "declaration":
        # Nested (e.g. for-loop init)
        for child in node.children:
            _ast_collect_declarator_names(child, source, names, seen)


def _extract_fallback_call_names(
    source_text: str,
    func_name: str,
    function_name_set: Set[str],
    body_text: str = "",
    max_candidates: int = 50,
) -> List[str]:
    if not source_text or not func_name or not function_name_set:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep

    search_text = str(body_text or "")
    if not search_text:
        pat = re.compile(rf"\b{re.escape(func_name)}\s*\([^;]*?\)\s*\{{", flags=re.M)
        m = pat.search(source_text)
        if m:
            start = m.end() - 1
            depth = 0
            end = start
            for idx in range(start, len(source_text)):
                ch = source_text[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx
                        break
            if end > start:
                search_text = source_text[start + 1 : end]
        if not search_text:
            m = re.search(rf"\b{re.escape(func_name)}\b", source_text)
            if m:
                left = max(0, m.start() - 2500)
                right = min(len(source_text), m.end() + 2500)
                search_text = source_text[left:right]
    clean = _strip_comments_and_strings(search_text)
    if not clean:
        return []
    lines = [ln for ln in clean.splitlines() if not ln.lstrip().startswith("#")]
    clean = "\n".join(lines)
    candidates: List[str] = []
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", clean):
        name = str(m.group(1) or "").strip()
        if (
            not name
            or name == func_name
            or name.lower() in _CALL_SKIP_WORDS
            or name not in function_name_set
        ):
            continue
        if name not in candidates:
            candidates.append(name)
        if len(candidates) >= max_candidates:
            break
    for m in re.finditer(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\(", clean):
        name = str(m.group(1) or "").strip()
        if (
            not name
            or name == func_name
            or name.lower() in _CALL_SKIP_WORDS
            or name not in function_name_set
        ):
            continue
        if name not in candidates:
            candidates.append(name)
        if len(candidates) >= max_candidates:
            break
    return candidates[:max_candidates]


def _extract_macro_call_names(
    body_text: str,
    macro_call_map: Dict[str, List[str]],
    max_candidates: int = 50,
) -> List[str]:
    if not body_text or not macro_call_map:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep

    clean = _strip_comments_and_strings(body_text)
    if not clean:
        return []
    candidates: List[str] = []
    for macro_name, target_names in macro_call_map.items():
        if not macro_name or not target_names:
            continue
        if not re.search(rf"\b{re.escape(macro_name)}\b\s*(?:\(|$)", clean, flags=re.M):
            continue
        for name in target_names:
            if not name or name in candidates:
                continue
            candidates.append(name)
            if len(candidates) >= max_candidates:
                return candidates[:max_candidates]
    return candidates[:max_candidates]


def _extract_function_pointer_call_targets(
    body_text: str,
    function_name_set: Set[str],
    max_candidates: int = 20,
) -> List[str]:
    if not body_text or not function_name_set:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep

    clean = _strip_comments_and_strings(body_text)
    if not clean:
        return []
    alias_to_target: Dict[str, str] = {}
    assign_patterns = [
        re.compile(r"\b([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)\s*;"),
        re.compile(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\([^;]*?\)\s*=\s*&?\s*([A-Za-z_]\w*)\s*;"),
    ]
    for pat in assign_patterns:
        for m in pat.finditer(clean):
            alias = str(m.group(1) or "").strip()
            target = str(m.group(2) or "").strip()
            if not alias or not target or target not in function_name_set or alias in function_name_set:
                continue
            alias_to_target[alias] = target

    candidates: List[str] = []
    for alias, target in alias_to_target.items():
        if re.search(rf"\b{re.escape(alias)}\s*\(", clean) or re.search(
            rf"\(\s*\*\s*{re.escape(alias)}\s*\)\s*\(",
            clean,
        ):
            if target not in candidates:
                candidates.append(target)
            if len(candidates) >= max_candidates:
                break
    return candidates[:max_candidates]


def _extract_comment_lines(text: str) -> List[str]:
    if not text:
        return []
    lines: List[str] = []
    for ln in text.splitlines():
        if "//" in ln:
            lines.append(ln.split("//", 1)[1].strip())
    for match in re.finditer(r"/\*([\s\S]*?)\*/", text):
        block = match.group(1)
        for ln in block.splitlines():
            cleaned = ln.strip().lstrip("*").strip()
            if cleaned:
                lines.append(cleaned)
    return lines


def _scan_source_comment_patterns(source_root: str, max_files: int = 300) -> List[Dict[str, Any]]:
    root = Path(source_root).resolve()
    if not root.exists():
        return []
    allowed = {".c", ".h", ".cpp", ".hpp"}
    pattern = re.compile(r"\b(logic|flow|state|diagram)\b", flags=re.I)
    items: List[Dict[str, Any]] = []
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            raw = _read_text_limited(p)
            if not raw:
                continue
            comments = _extract_comment_lines(raw)
            for ln in comments:
                if pattern.search(ln):
                    items.append(
                        {
                            "title": f"{p.name} (comment)",
                            "description": ln.strip()[:240],
                        }
                    )
                if len(items) >= 80:
                    break
            if len(items) >= 80:
                break
        if scanned > max_files or len(items) >= 80:
            break
    return items


def _scan_source_requirement_ids(source_root: str, max_files: int = 800) -> List[str]:
    root = Path(source_root).resolve()
    if not root.exists():
        return []
    allowed = {".c", ".h", ".cpp", ".hpp"}
    ids: set[str] = set()
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            text = _read_text_limited(p)
            if not text:
                continue
            for rid in re.findall(r"\bSw(?:TR|TSR|Com|Fn)_\d+\b", text):
                ids.add(rid)
        if scanned > max_files:
            break
    return sorted(ids)


def _scan_source_function_names(source_root: str, max_files: int = 800) -> Dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.exists():
        return {"names": [], "scanned": 0}
    allowed = {".c", ".h", ".cpp", ".hpp"}
    names: set[str] = set()
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            raw = _read_text_limited(p)
            if not raw:
                continue
            text = _strip_c_comments(raw)
            # ⚠ `fn, *_` 로 받는다 — 두 추출기의 튜플 폭이 3 → 4 로 넓어졌을 때
            #   (43a2f99, 2026-04-08) 같은 커밋이 uds_generator.py 소비처는 고쳤는데
            #   여기만 3-tuple 로 남아 **C 파일이 하나라도 있으면 ValueError** 였다.
            #   호출자(jenkins requirements-preview)가 그 예외를 무로그로 삼켜
            #   `function_mapping: null` 로 응답했기 때문에 약 4개월간 드러나지 않았다.
            #   여기서 필요한 건 이름뿐이므로 폭 변화에 영향받지 않게 둔다.
            for fn, *_rest in _extract_c_prototypes(text):
                names.add(fn)
            for fn, *_rest in _extract_c_definitions(text):
                names.add(fn)
        if scanned > max_files:
            break
    return {"names": sorted(names), "scanned": scanned}


def _extract_doxygen_asil_tags(text: str) -> Dict[str, Dict[str, str]]:
    """Extract ASIL/safety/requirement tags from Doxygen comments preceding functions."""
    if not text:
        return {}
    result: Dict[str, Dict[str, str]] = {}
    comment_pat = re.compile(
        r"/\*\*(.*?)\*/\s*"
        r"(?:static\s+)?[A-Za-z_][\w\s\*]*?\s+([A-Za-z_]\w*)\s*\(",
        flags=re.S,
    )
    for m in comment_pat.finditer(text):
        body = m.group(1)
        func_name = m.group(2).strip()
        if not func_name:
            continue
        info: Dict[str, str] = {}
        asil_m = re.search(r"@(?:asil|ASIL)\s+([A-D]|QM)\b", body, re.I)
        if asil_m:
            info["asil"] = asil_m.group(1).upper()
        safety_m = re.search(r"@(?:safety|SAFETY)\s+(.+?)(?:\n|$)", body)
        if safety_m:
            info["safety"] = safety_m.group(1).strip()
            if not info.get("asil"):
                asil_in_safety = re.search(r"\b(ASIL[\s\-_]*[A-D]|QM)\b", info["safety"], re.I)
                if asil_in_safety:
                    raw = asil_in_safety.group(1).upper().replace(" ", "").replace("-", "").replace("_", "")
                    info["asil"] = raw.replace("ASIL", "") if raw.startswith("ASIL") else raw
        req_ids: List[str] = []
        for req_m in re.finditer(
            r"@(?:requirement|req|related)\s+(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK)_\d+)",
            body,
            re.I,
        ):
            req_ids.append(req_m.group(1))
        if req_ids:
            info["requirement"] = ", ".join(req_ids)
        brief_m = re.search(r"@brief\s+(.+?)(?:\n|$)", body)
        if brief_m:
            info["brief"] = brief_m.group(1).strip()
        if info:
            result[func_name] = info
    return result


def _extract_file_header_asil(text: str) -> str:
    """Extract module-level ASIL from file header comment block."""
    if not text:
        return ""
    header_m = re.match(r"\s*/\*\*(.*?)\*/", text, flags=re.S)
    if not header_m:
        header_m = re.match(r"\s*/\*(.*?)\*/", text, flags=re.S)
    if not header_m:
        return ""
    header = header_m.group(1)
    asil_m = re.search(
        r"\b(?:ASIL[\s\-_:]*([A-D](?:\s*\([A-D]\))?)|QM)\b",
        header,
        re.I,
    )
    if asil_m:
        if asil_m.group(0).strip().upper().startswith("QM"):
            return "QM"
        return asil_m.group(1)[0].upper() if asil_m.group(1) else ""
    return ""
