"""report_gen.source_parser - Auto-split from report_generator.py"""
# Re-import common dependencies
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

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
    return _cap_and_decode(data, max_bytes)


def _cap_and_decode(data: bytes, max_bytes: int = _SRC_READ_MAX_BYTES) -> Tuple[str, int, bool]:
    """읽은 바이트에 상한·디코딩을 적용 → `(원문, 원본 바이트 수, 절단 여부)`.

    `_read_source_text` 와, 읽기 **실패**를 구분해야 하는 호출자(`utils._infer_type_from_file` 의 실행 단위 캐시 —
    R52 리뷰 W1: 실패를 빈 원문으로 굳히면 그 파일의 나머지 전역이 전부 조용히 타입 없음이 된다)가 같은 규칙을 쓴다.
    """
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
from workflow.code_parser.c_parser import (  # noqa: E402
    _iter_regex_def_heads,
    _parse_comment_fields,
    blank_dead_code,
)
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
            # ⚠ 구분 공백 필수. 없으면 `__interruptvoid` 라는 존재하지 않는 타입이 되어
            #   정확일치 판정 사이트가 "반환값 있음" 으로 읽는다(실측: 산출물 34칸).
            #   판정은 `report_gen.c_return.returns_value` 단일 출처를 쓸 것.
            ret_type = f"{interrupt_prefix} {ret_type}"
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
    """`{함수 이름: 본문}` — 정의 머리 뒤 중괄호 균형으로 자른 본문(같은 이름은 뒤엣것이 남는다).

    ⚠ R61(N63): 머리는 `c_parser._iter_regex_def_heads`(R59 선형 스캐너)로 찾는다. 여기 있던 정규식은 R59 가
      `c_parser` 에서 걷어낸 것과 **같은 모양의 사본**이었다 — 접두 클래스에 괄호·쉼표가 들어 있어 세미콜론 없는
      초기화 표(`Vectors.c` 17.9KB)에서 줄마다 백트래킹, 그 한 파일에 1.6초 동안 GIL 을 쥐었다. 사본은 고친 쪽의
      가드에 걸리지 않는다: R59 는 `c_parser` 만 쟀고 이 함수는 호출 입력(주석 제거본)으로 재야만 드러났다.
    """
    if not text:
        return {}
    out: Dict[str, str] = {}
    for _head_start, _prefix, name, _params, head_end in _iter_regex_def_heads(text):
        if not name:
            continue
        start = head_end - 1  # points to "{"
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
#: ⚠ 1번 그룹은 `struct` / `union` 이다 — union 멤버는 **베이스 전체와 같은 저장소**라
#:   전폭 별칭(`REG_X.Byte`)에 레지스터 설명을 쓸 수 있는지 판단하는 근거가 된다.
#:   기존 소비자(`extract_struct_member_arrays`)는 `.start()` 만 쓰므로 영향 없다.
_STRUCT_HEAD_RE = re.compile(r"typedef\s+(struct|union)\b[^{;]*\{")
_STRUCT_TAIL_RE = re.compile(r"\s*(\w+)\s*;")
_INNER_HEAD_RE = re.compile(r"(struct|union)\s*\{")
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


# 구조체/공용체 멤버의 **타입 · 비트폭 · 자기 주석**.
#
# ⚠ 배열 차원만 담는 위 `extract_struct_member_arrays` 와 **키는 같고 값이 다르다**.
#   그 함수의 반환형(`{타입: {멤버: "[8]"}}`)은 SUTS/SITS 와 캐시 키
#   `struct_member_arrays` 가 이미 쓰고 있어 넓히면 소비처 계약이 깨진다 → 따로 낸다.
#
# 왜 필요한가 (실측 2026-08-26 · 산출물 46.8MB 직독): 멤버 경로 행 **335개**가
# Type/Range/Reset/Desc **네 칸 전부** 베이스 심볼의 값을 이고 있었다.
# `REG_ADC0STS.Bits.READY` 는 1비트 필드인데 Type 칸이 `ADC0STSSTR`(레지스터 전체
# 공용체)였다. 정본 대비 재현율이 멤버 행만 4개 열 전부 **0.0%**(n=273)이고 단일
# 심볼 행은 type **93.7%** 다 — 값 부재가 아니라 **다른 대상의 값**이었다.
_MEMBER_NEST_MAX = 6
# 멤버 선언: `U8 Byte` · `U8 READY :1` · `UINT8 buf[8]` · `lin_tl_pdu_data *tl_pdu`
# ⚠ 별표가 이름에 붙는 형태(`T   *p`)를 놓치면 그 타입의 멤버가 통째로 안 잡힌다
#   (실측: `lin_transport_layer_queue::tl_pdu` 12칸).
# (R65 N74) 두 단어 이상의 기본 타입(`unsigned long long bitcount` · `struct tag x`)도 한 멤버다 — 앞 판은 첫 단어를 타입,
#   둘째 단어를 이름으로 읽다가 셋째 단어에서 실패해 그 멤버를 통째로 버렸다(실측: KJPDS02 `SHA256_CTX.bitcount` 1개).
_MEMBER_DECL_RE = re.compile(
    r"^\s*((?:(?:const|volatile|static|unsigned|signed|short|long|struct|union|enum)\s+)*[A-Za-z_]\w*)"
    r"(?:\s*(\*+)\s*|\s+)(\w+)\s*(?:((?:\[[^\]]*\])+)|:\s*(\d+))?\s*$"
)


def _top_level_member_segments(masked: str):
    """깊이 0 의 `;` 로만 끊어 `(시작, 세미콜론 위치)` 를 낸다.

    ⚠ 위 `extract_struct_member_arrays` 는 중첩 블록을 **먼저 지우고** 훑는다. 그러면
      오프셋이 밀려 원문에서 꼬리 주석을 되짚을 수 없다. 깊이를 세면 위치가 보존된다.
    """
    depth = 0
    start = 0
    for i, ch in enumerate(masked):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ";" and depth == 0:
            yield start, i
            start = i + 1


def _member_trailing_comment(raw_body: str, semi_pos: int) -> str:
    """선언이 끝난 **같은 줄**의 주석. 없으면 빈 문자열.

    ⚠ `;` 로 끊은 조각의 **머리** 주석을 그대로 쓰면 앞 멤버의 설명이 다음 멤버로
      간다. 전역에서 같은 밀림이 809개 중 **411개**였다(Phase 3, `_is_trailing_comment`).
      설계서에 "이 필드는 X 다" 를 **틀리게** 적는 것이라 빈 칸보다 나쁘다.

    ⚠ 멤버 **위**에 따로 붙은 leading 주석은 쓰지 않는다 — MCU 헤더에선 그 자리가
      절 제목(`/*** PARTID0 - Part ID Register 0; 0x00000000 ***/`)이라 필드 설명이
      아니다. 못 가져오는 건 손실이지만 틀리게 가져오는 것보다 낫다.
    """
    line = str(raw_body)[semi_pos + 1:].split("\n", 1)[0]
    m = re.search(r"/\*(.*?)\*/", line)
    if m:
        return _clean_comment_text(m.group(1))
    m = re.search(r"//(.*)$", line)
    return _clean_comment_text(m.group(1)) if m else ""


def _clean_comment_text(text: str) -> str:
    """Doxygen 표식(`/**<` · `/*!` · `/***`)의 잔재를 걷어낸다.

    안 하면 `/**< PDU data */` 가 `*< PDU data` 로 문서에 나간다 — 내용은 맞지만
    설계서 칸에 파서 부스러기를 실어 보내는 셈이다.
    """
    return re.sub(r"[*\s]+$", "", re.sub(r"^[*<!\s]+", "", str(text or "")))


def _walk_member_types(raw: str, masked: str, kind: str = "struct",
                       depth: int = 0) -> Dict[str, Dict[str, str]]:
    """이름 붙은 중첩 블록을 **재귀로** 편다.

    실물에 3단이 있다 — `REG_PARTID.Overlap_STR.PARTID0STR.Bits.ID0`. 1단만 펴면
    그런 행이 통째로 안 풀린다(실측 55칸이 그 형태였다).
    """
    out: Dict[str, Dict[str, str]] = {}
    if depth > _MEMBER_NEST_MAX:
        return out
    for seg_start, semi in _top_level_member_segments(masked):
        m = _MEMBER_DECL_RE.match(masked[seg_start:semi])
        if not m:
            continue
        star = f" {m.group(2)}" if m.group(2) else ""
        out.setdefault(m.group(3), {
            "type": (m.group(1).strip() + star).strip(),
            "array": m.group(4) or "",
            "bits": m.group(5) or "",
            "desc": _member_trailing_comment(raw, semi),
            # union 멤버는 **베이스 전체와 같은 저장소**다. 그 사실이 없으면
            # `REG_X.Byte` 같은 전폭 별칭 행에서 레지스터 설명을 쓸 수 있는지
            # 판단할 수 없다 — 정본도 그 칸엔 레지스터 설명을 적는다
            # (`REG_ADC0STS.Byte` → `ADC0STS / ADC Status Register`).
            "parent": kind,
        })
    pos = 0
    while True:
        inner = _INNER_HEAD_RE.search(masked, pos)
        if not inner:
            break
        i = masked.index("{", inner.start())
        j = _balanced_block(masked, i)
        if j < 0:
            break
        pos = j + 1
        tail = _STRUCT_TAIL_RE.match(masked, j + 1)
        if not tail:
            continue
        for mname, rec in _walk_member_types(
                raw[i + 1:j], masked[i + 1:j],
                inner.group(1), depth + 1).items():
            out.setdefault(f"{tail.group(1)}.{mname}", rec)
    return out


def extract_struct_member_types(text: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    """`타입명 -> {멤버경로: {type, array, bits, desc}}`.

    주석은 **가린다(blank)** — 지우면 길이가 줄어 원문 오프셋으로 꼬리 주석을 되짚을
    수 없다(`blank_c_comments` 가 그러라고 있는 단일 출처다).
    """
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    if not text:
        return out
    masked = _blank_c_comments(text)
    for head in _STRUCT_HEAD_RE.finditer(masked):
        i = masked.index("{", head.start())
        j = _balanced_block(masked, i)
        if j < 0:
            continue
        tail = _STRUCT_TAIL_RE.match(masked, j + 1)
        if not tail:
            continue
        members = out.setdefault(tail.group(1), {})
        for mname, rec in _walk_member_types(
                text[i + 1:j], masked[i + 1:j], head.group(1)).items():
            members.setdefault(mname, rec)
    return out


def resolve_struct_member(member_types: Optional[Dict[str, Dict[str, Dict[str, str]]]],
                          base_type: str,
                          path: str) -> Optional[Dict[str, str]]:
    """`ADC0STSSTR` + `Bits.READY` -> 그 멤버의 레코드. 못 찾으면 `None`.

    ⚠ **못 찾았을 때 베이스의 레코드를 대신 주지 않는다.** 이름은 비트 하나를
      가리키는데 값이 레지스터 전체를 말하면, 빈 칸이면 하지 않았을 주장을
      **틀리게** 하는 것이다.

    경로는 한 마디씩 따라간다 — 중간 마디가 또 다른 typedef 라도 이어진다.
    """
    if not isinstance(member_types, dict):
        return None
    base = str(base_type or "").strip()
    trail = str(path or "").strip()
    if not base or not trail:
        return None
    cur, rest = base, trail
    for _ in range(_MEMBER_NEST_MAX + 1):
        table = member_types.get(cur) or {}
        # ① 남은 경로 **전체**를 먼저 본다. 익명 중첩 블록은 `Bits.READY` 처럼
        #    점 있는 한 개의 키로 들어 있어, 마디로 쪼개면 `Bits` 에서 끊긴다.
        whole = table.get(rest)
        if isinstance(whole, dict):
            return whole
        # ② 안 되면 한 마디만 소비하고 그 타입으로 내려간다(중간 마디가 typedef).
        seg, _dot, tail = rest.partition(".")
        seg = re.sub(r"\[.*$", "", seg).strip()
        hit = table.get(seg) if seg else None
        if not isinstance(hit, dict):
            return None
        if not tail:
            return hit
        words = re.sub(r"\s*\*+$", "", str(hit.get("type") or "")).split()
        cur, rest = (words[-1] if words else ""), tail
        if not cur:
            return None
    return None


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
        import tree_sitter_c as tsc  # type: ignore
        from tree_sitter import Language, Parser  # type: ignore
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
            text = _strip_c_comments(blank_dead_code(raw))   # (R63 N70) 죽은 `#if 0` 분기의 이름은 함수 집합이 아니다
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


#: 문서 주석 **뒤에 오는** 함수 머리. 옛 정규식의 뒷부분과 같은 모양이고, 접두(반환형) 길이에만
#: 상한을 뒀다 — 상한이 없으면 단어·공백이 길게 이어진 자리에서 lazy 확장이 제곱으로 돈다.
#: ⚠ 공백 런에도 같은 상한을 둔다(리뷰 I3) — 접두만 묶으면 `타입` 뒤 긴 공백에서 lazy 위치마다 `\s+` 가 런 전체를
#:   먹었다 되물린다(실측 1MB = 주석 200 × 공백 5,000 에 2.25초). 원문엔 없는 모양이지만 주석을 공백으로 바꾼
#:   텍스트가 들어오면 바로 현실이 된다. 이 함수는 **원문(raw)** 으로 부를 것 — 주석이 지워지면 읽을 태그도 없다.
#:   이름 **뒤** 공백엔 상한이 필요 없다 — 런마다 한 번만 되물리므로 합이 입력 길이를 넘지 않는다(뮤테이션으로 확인).
_DOX_HEAD_PREFIX_MAX = 256
_DOX_HEAD_PAT = re.compile(
    r"(?:static\s+)?[A-Za-z_][\w\s\*]{0,%(n)d}?\s{1,%(n)d}([A-Za-z_]\w*)\s*\(" % {"n": _DOX_HEAD_PREFIX_MAX}
)
_C_SPACE = " \t\r\n\f\v"


def _doxygen_tags_of(body: str) -> Dict[str, str]:
    """문서 주석 본문 하나의 태그 — `asil`·`safety`·`requirement`·`brief` 중 있는 것만."""
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
    return info


def _skip_space_and_non_owner_comments(text: str, pos: int) -> int:
    """공백과 **함수의 주인이 아닌** 주석을 건너뛴 위치.

    주인이 아닌 주석 = 일반 주석(`/* … */`·`// …`), 뒤따름 문서(`/**< …` — 앞 멤버의 것), **태그 없는** `/** … */`.
    - Freescale LIN 양식은 `/** … *//*END*-----*/` 뒤에 함수가 온다 — 문서 주석과 함수 사이에 일반 주석이 낀다.
    - 태그가 **있는** `/** … */` 에선 멈춘다: 그건 다음 함수의 자기 주석이고, 가까운 쪽이 이긴다.
    - 태그 없는 `/**` (구분선 `/*** sep ***/`·그룹 마커 `/**@{*/`)가 짝을 끊게 두면 `@asil` 이 **조용히 사라진다**
      (리뷰 W2). 끊는 쪽의 오류는 과소보고, 잇는 쪽의 오류는 과대보고라 잇는다.
    """
    n = len(text)
    while pos < n:
        if text[pos] in _C_SPACE:
            pos += 1
        elif text.startswith("//", pos):
            eol = text.find("\n", pos)
            pos = n if eol < 0 else eol + 1
        elif text.startswith("/*", pos):
            close = text.find("*/", pos + 2)
            if close < 0:
                return n
            if (
                text.startswith("/**", pos)
                and not text.startswith("/**<", pos)
                and _doxygen_tags_of(text[pos + 3 : close])      # `/**/` 면 빈 슬라이스 → 태그 없음
            ):
                break
            pos = close + 2
        else:
            break
    return pos


def _iter_doc_comment_heads(text: str) -> Iterator[Tuple[str, str]]:
    """`(함수 이름, 문서 주석 본문)` — 문서 주석 **하나**와 그 바로 뒤 함수 머리의 짝.

    ⚠ R61(N63): 옛 구현은 `<문서 주석 lazy 본문><공백><머리>` 한 덩어리를 `re.S` 로 걸었다. 주석이 함수 앞이 아니면
    `.*?` 가 **다음 주석들을 넘어** 머리가 나올 때까지 늘어난다. 결과가 둘이었다.
      1. 비용 — 함수가 없는 레지스터 헤더(670KB)에서 `/**` 마다 파일 끝까지 훑어 3.6초·2.6초.
         정규식은 GIL 을 놓지 않으므로 그 동안 백엔드 프로세스 전체가 멈췄다(라이브 4.2~4.5초 정지).
      2. 오귀속 — 파일 머리말의 `@brief`/`@asil` 이 **첫 함수의 것**이 됐다(실측 KJPDS02 17건은
         자기 주석이 있는데도 머리말 문장으로 덮였고, 14건은 남의 주석을 받았다).
    여기선 주석을 첫 `*/` 에서 닫고, 그 뒤 공백·주인 아닌 주석만 건너뛴 자리에서 머리를 **한 번** 맞춘다.
    ⚠ 전처리 줄(`#pragma`·`#if`)은 건너뛰지 않는다 — 재 보니 더해지는 7건 중 5건이 오귀속이었다.
    ⚠ 머리가 안 맞으면 **건너뛴 끝**에서 이어 간다. 건너뛴 주석들은 어차피 같은 자리에 닿아 같은 이유로 떨어지므로,
      하나씩 다시 시작하면 잇닿은 주석 N 개에서 N² 이 된다.
    """
    pos = 0
    while True:
        start = text.find("/**", pos)
        if start < 0:
            return
        # `/**/` 는 빈 주석이다 — 닫는 `*/` 가 여는 `/**` 와 겹친다.
        close = text.find("*/", start + 2)
        if close < 0:
            return
        if text.startswith("/**<", start):
            pos = close + 2          # 뒤따름 문서 — 앞 멤버의 것이지 다음 함수의 것이 아니다.
            continue
        gap_end = _skip_space_and_non_owner_comments(text, close + 2)
        head = _DOX_HEAD_PAT.match(text, gap_end)
        if head is None:
            pos = gap_end
            continue
        yield head.group(1), text[start + 3 : close]
        pos = head.end()


def _extract_doxygen_asil_tags(text: str) -> Dict[str, Dict[str, str]]:
    """Extract ASIL/safety/requirement tags from Doxygen comments preceding functions.

    ⚠ 소비처는 `uds_generator` 의 **정규식 폴백 분기**(tree-sitter 가 그 함수를 못 찾았을 때)뿐이다. tree-sitter 경로의
      주석은 `c_parser._extract_leading_comment` 가 읽고, 거기엔 "사이에 낀 일반 주석" 규칙이 아직 없다(N69).
    """
    if not text:
        return {}
    result: Dict[str, Dict[str, str]] = {}
    for func_name, body in _iter_doc_comment_heads(text):
        info = _doxygen_tags_of(body)
        if info:
            result[func_name] = info
    return result


# (R62 N69) 헤더 프로토타입의 문서 주석 — 정의 쪽에 주석이 없는 함수의 설명·ASIL·Related 원천.
#   벤더 드라이버(Freescale LIN 스택)는 문서를 **헤더에만** 적는다. 실측: 설명이 추론 문장으로 나간 함수 중
#   KJPDS02 71개 · PDS64 66개(추론 94개 중)가 헤더에 `@brief` 를 갖고 있었고, `.h` 의 문서 주석은 읽히기만 하고
#   한 번도 쓰인 적이 없었다(R61 리뷰 I2). 필드 해석은 정의 쪽과 **같은 파서**(`_parse_comment_fields`)로 한다 —
#   주석이 어느 파일에 적혔느냐로 설명의 모양이 달라지면 안 된다.
_ASIL_RANK = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}
_NOT_A_FUNCTION_NAME = frozenset(
    {"void", "char", "short", "int", "long", "float", "double", "signed", "unsigned", "struct", "union", "enum",
     "const", "volatile", "static", "extern", "typedef", "if", "for", "while", "switch", "return", "sizeof"}
)


def extract_header_function_docs(raw: str) -> Dict[str, Dict[str, str]]:
    """헤더 원문 → `{함수 이름: {"desc","asil","related","precondition"}}`. 필드가 하나도 없는 주석은 싣지 않는다."""
    out: Dict[str, Dict[str, str]] = {}
    if not raw:
        return out
    # 죽은 `#if 0` 분기의 프로토타입은 문서화 근거가 아니다(리뷰 I7 — 정의 쪽과 같은 규칙).
    for func_name, body in _iter_doc_comment_heads(blank_dead_code(raw)):
        if func_name in _NOT_A_FUNCTION_NAME:
            continue   # `typedef void (*Cb)(void);` 를 머리 패턴이 `void(` 로 읽는다(리뷰 I8)
        desc, asil, related, precondition, _rng, _params, _ret = _parse_comment_fields(body)
        if not (desc or asil or related):
            continue
        # first-wins — 같은 헤더에 같은 이름이 두 번(`#if`/`#else` 양쪽 프로토타입)이면 먼저 적힌 쪽.
        out.setdefault(
            func_name,
            {"desc": desc, "asil": asil, "related": related, "precondition": precondition},
        )
    return out


def _path_parts_norm(p: str) -> List[str]:
    """비교용 경로 조각 — 소문자 + `..`/`.`/중복 구분자 정리. (R65 리뷰 W1) cloudium 모드의 `_roots` 는 resolve 를 안 하고
    tree-sitter 경로(`parse_c_project`)는 항상 resolve 하므로, 루트 문자열에 `..` 가 섞이면 같은 파일이 다른 루트로 읽혀 헤더
    프로토타입·헤더 주석이 **전량** `other_root` 로 떨어진다. 파일 시스템은 건드리지 않는다(원격 경로 그대로)."""
    s = str(p or "")
    if not s:
        return []
    return [x.lower() for x in Path(os.path.normpath(s)).parts]


def _shared_path_parts(a: str, b: str) -> int:
    pa = _path_parts_norm(a)
    pb = _path_parts_norm(b)
    n = 0
    for x, y in zip(pa, pb, strict=False):
        if x != y:
            break
        n += 1
    return n


def _root_index_of(path: str, roots: List[str]) -> int:
    parts = _path_parts_norm(path)
    best, best_len = -1, -1
    for i, root in enumerate(roots):
        rp = _path_parts_norm(root)
        if rp and parts[: len(rp)] == rp and len(rp) > best_len:
            best, best_len = i, len(rp)
    return best


def _norm_def_axis(value: Any) -> str:
    """(R66 N76) 정의 충돌 비교용 정규화 — `const`/`volatile` 를 걷고 공백을 접고 `*` 앞뒤 공백을 없앤다.
    `U16` vs `word` 는 다르고, `const U8 *` vs `U8*` 는 같다(한정자는 tree-sitter 타입에 없어 비교 축이 아니다)."""
    s = re.sub(r"\b(?:const|volatile)\b", " ", str(value or ""))
    s = " ".join(s.split())
    return re.sub(r"\s*\*\s*", "*", s).strip()


def _short_def_path(path: str, roots: List[str]) -> str:
    """(R66 N76 리뷰 I1) 공시용 짧은 경로 `r0:Eeprom/EEPROM.c` — 루트 번호 + `상위폴더/파일`. 어느 루트에도 안 걸리면 `r-`."""
    idx = _root_index_of(path, roots)
    tail = "/".join(Path(str(path or "")).parts[-2:])
    return f"r{idx if idx >= 0 else '-'}:{tail}"


def _definition_order(path: str, roots: List[str]) -> Tuple[int, str]:
    """(R66 N76) 같은 이름의 정의가 여러 파일에 있을 때 **어느 것이 남는지**의 정렬 키 — (소스 루트 순서, 정규화 경로).
    첫 루트(주 트리)의 정의가 이기고, 같은 루트면 경로 문자열순. 어느 루트에도 안 걸리면 맨 뒤. 파일 열거 순서(모드 의존)를
    대신하는 규칙이라 두 모드가 같은 문서를 낸다."""
    idx = _root_index_of(path, roots)
    return (idx if idx >= 0 else len(roots), os.path.normcase(os.path.normpath(str(path or ""))))


def pick_header_doc(
    candidates: List[Dict[str, str]], file_path: str, roots: Optional[List[str]] = None
) -> Dict[str, str]:
    """같은 이름을 문서화한 헤더가 여럿일 때 하나를 고른다(APP/FBL 두 트리가 같은 이름의 헤더를 따로 갖는다).

    - `roots` 를 주면 **정의 파일과 같은 소스 루트의 헤더만** 후보다. 실측: 부트로더 트리의 `Comms.h` 가 선언한
      `LINPHY0_Init` 의 주석이 앱 트리의 `LINPHY0.c` 로 갔다 — 이름이 같아도 다른 바이너리의 함수다.
    - 정의 파일과 경로를 가장 길게 공유하는 헤더를 고른다.
    - 그래도 여럿이고 내용이 다르면 **설명·Related 는 고르지 않는다**(아무거나 고르면 남의 문장을 싣는다).
      ASIL 만은 그중 가장 높은 등급을 돌려준다 — 모르겠다고 비우면 하류가 SDS/TBD 로 내려가 과소분류가 된다.
    """
    if roots:
        own = _root_index_of(file_path, roots)
        candidates = [c for c in candidates if _root_index_of(str(c.get("file") or ""), roots) == own]
    if not candidates:
        return {}
    best = max(_shared_path_parts(str(c.get("file") or ""), file_path) for c in candidates)
    top = [c for c in candidates if _shared_path_parts(str(c.get("file") or ""), file_path) == best]
    first = top[0]
    _key = ("desc", "asil", "related", "precondition")
    same = all(tuple(c.get(k) or "" for k in _key) == tuple(first.get(k) or "" for k in _key) for c in top)
    if same:
        return first
    ranked = [c for c in top if str(c.get("asil") or "").strip().upper() in _ASIL_RANK]
    if not ranked:
        return {}
    highest = max(ranked, key=lambda c: _ASIL_RANK[str(c.get("asil") or "").strip().upper()])
    # `file` 을 비운다 — 취한 것은 등급뿐인데 그 헤더가 "이 함수를 문서화했다" 로 읽히면 안 된다(리뷰 W4).
    return {"file": "", "desc": "", "asil": str(highest.get("asil") or ""), "related": "", "precondition": ""}


def prototype_param_count(sig: str) -> int:
    """시그니처의 인자 수. `(void)`·빈 괄호는 0, 괄호를 못 찾으면 -1(모름). 함수 포인터 인자의 안쪽 쉼표는 세지 않는다."""
    s = str(sig or "").strip()
    if not s.endswith(")"):
        return -1
    depth = 0
    start = -1
    for i in range(len(s) - 1, -1, -1):
        ch = s[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                start = i
                break
    if start < 0:
        return -1
    inner = " ".join(s[start + 1:-1].split())
    if inner == "void":
        return 0
    if inner == "":
        # (리뷰 W5) `f()` 는 C 에서 "인자 미지정" 이지 0개가 아니다 — `(void)` 와 접으면 인자 있는 정의와 불일치로 읽혀 헤더를 잃는다.
        #   대상 코드베이스 4 트리엔 이 형태의 헤더 선언이 0건이라 실효는 없지만 값의 뜻은 맞게 둔다.
        return -1
    n, d = 1, 0
    for ch in inner:
        if ch in "([":
            d += 1
        elif ch in ")]":
            d -= 1
        elif ch == "," and d == 0:
            n += 1
    return n


def _ident_before_params(sig: str) -> str:
    """마지막 최상위 `(` 바로 앞의 식별자. `ISR (Cpu_Interrupt)` → `ISR`, `void f(U8 a)` → `f`. 없으면 빈 문자열."""
    s = str(sig or "").strip()
    if not s.endswith(")"):
        return ""
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                m = re.search(r"([A-Za-z_]\w*)\s*$", s[:i])
                return m.group(1) if m else ""
    return ""


def pick_header_prototype(
    candidates: List[Dict[str, str]],
    file_path: str,
    roots: Optional[List[str]],
    definition_sig: str,
    is_static: bool = False,
    name: str = "",
) -> Tuple[str, str]:
    """함수 하나의 Prototype 을 고른다 → `(signature, source)`.

    (R65 N74) 앞 판은 이름 → 헤더 프로토타입 **first-wins** 였다. 같은 이름의 함수가 APP/FBL 두 트리에 따로 있으면(실측 충돌 이름
    KJPDS02 14 · PDS64 11) 두 정의가 **먼저 읽힌 헤더 하나**의 프로토타입을 나눠 가졌고, 그 순서는 파일 열거 순서(local `os.walk` 와
    cloudium 워커 목록이 다르다)라 같은 소스가 모드에 따라 다른 문서를 냈다. 실측 결과 `lin_lld_sci.c:lin_lld_sci_init(l_ifc_handle)`
    이 부트로더 `Comms.h` 의 `(void)` 를 달고 있었다 — LIN 헤더는 verify=X 계층이라 텍스트 루프가 읽지도 않는다.

    규칙(`pick_header_doc` 와 같은 축):
    - static 함수는 정의 그대로 — 헤더가 선언하는 것은 외부 연결 함수이고 같은 이름의 파일 내부 함수는 남이다(R62 규칙).
    - `roots` 를 주면 **정의 파일과 같은 소스 루트의 헤더만** 후보다. 없으면 정의를 지킨다(`definition:other_root`).
    - 정의 파일과 경로를 가장 길게 공유하는 헤더. 동률은 경로 문자열 순으로 — 열거 순서에 기대지 않는다.
    - 인자 수가 정의와 다른 프로토타입은 남의 것이다(`definition:arity`). 남은 후보가 서로 다르면 고르지 않는다(`definition:conflict`).
    - 정의가 매크로형(`ISR (Cpu_Interrupt)` — 괄호 앞 식별자가 `name` 이 아니다)이면 인자 수를 모르는 것으로 두고 헤더를 받는다
      (`header:macro_def` — 인자 수 검사를 건너뛴 사실을 남긴다).
    `source` 는 `header*` 아니면 `definition:<이유>` — 호출자가 세어 `prototype_scan` 으로 공시한다.
    """
    if is_static:
        return definition_sig, "definition:static"
    cands = [c for c in (candidates or []) if str(c.get("sig") or "").strip()]
    if not cands:
        return definition_sig, "definition:no_header"
    if roots:
        own = _root_index_of(file_path, roots)
        # (리뷰 W2) 정의 파일이 어느 루트에도 안 걸리면(-1) 후보의 -1 과 "같은 루트" 가 되어 남의 시그니처를 싣는다 → 정의를 지킨다.
        cands = [c for c in cands if own >= 0 and _root_index_of(str(c.get("file") or ""), roots) == own]
        if not cands:
            return definition_sig, "definition:other_root"
    best = max(_shared_path_parts(str(c.get("file") or ""), file_path) for c in cands)
    top = sorted(
        (c for c in cands if _shared_path_parts(str(c.get("file") or ""), file_path) == best),
        key=lambda c: str(c.get("file") or "").lower(),
    )
    want = prototype_param_count(definition_sig)
    # ⚠ 정의가 매크로형(`ISR (Cpu_Interrupt)` — tree-sitter 가 `ISR` 을 선언자로 읽는다)이면 괄호 안은 인자가 아니라 이름이다.
    #   그대로 세면 헤더 `(void)` 와 "인자 수가 다르다" 가 되어 ISR 15/14개가 정의로 떨어졌다(첫 구현, 페이로드 대조로 발견).
    #   판별은 **함수 이름**으로(리뷰 W4 — 후보 하나의 모양에 기대지 않는다): 괄호 앞 식별자가 이름이 아니면 인자 수를 모르는 것.
    macro_def = bool(name) and _ident_before_params(definition_sig) != name
    if macro_def:
        want = -1
    fit = [c for c in top if want < 0 or prototype_param_count(str(c.get("sig") or "")) == want]
    if not fit:
        return definition_sig, "definition:arity"
    if len({" ".join(str(c.get("sig") or "").split()) for c in fit}) > 1:
        return definition_sig, "definition:conflict"
    return str(fit[0].get("sig") or ""), ("header:macro_def" if macro_def else "header")


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
