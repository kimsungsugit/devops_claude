from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from tree_sitter import Language, Parser  # type: ignore
    from tree_sitter_c import language as c_language  # type: ignore
except Exception:  # pragma: no cover
    Language = None  # type: ignore
    Parser = None  # type: ignore
    c_language = None  # type: ignore


def blank_c_comments(text: str) -> str:
    """주석을 **길이·줄 수를 유지한 채** 공백으로 지운다.

    ## 왜 지우기(strip)가 아니라 공백 채우기(blank)인가

    통째로 제거하면 바이트 오프셋이 밀린다. `_extract_leading_comment(text_bytes,
    start_byte)` 처럼 **오프셋으로 원문을 되짚는** 소비자가 엉뚱한 자리를 읽는다.
    길이를 유지하면 원문과 1:1 이라 정규식 매칭만 주석을 피하고 서술 추출은 원문에서
    그대로 한다.

    ## 왜 필요한가 (실측 2026-08-12)

    Processor Expert 가 만든 `Generated_Code/*.c` 는 매크로로 구현된 접근자의
    프로토타입을 **주석 안에** 남긴다:

        /*
        bool PS3_MOTOR_NSCS_GetVal(void)

        **  This method is implemented as a macro. See PS3_MOTOR_NSCS.h file.  **
        */

    tree-sitter 는 이 파일을 "함수 0개" 로 **정확히** 읽는다. 그런데 호출부의
    `if not funcs:` 가 그걸 "파싱 실패" 로 보고 정규식 폴백을 돌렸고, 그 정규식이
    주석을 훑어 **없는 함수를 만들어냈다**. 정본 SUTS 엔 이 접근자들이 하나도
    없다 — 존재하지 않는 함수의 시험 케이스를 생성하고 있었다는 뜻이다.

    ⚠ 문자열 리터럴 안의 `/*` 는 구분하지 않는다(기존 `_strip_c_comments` 와 동일한
      한계). C 소스에서 드물고, 잘못 가려도 함수를 **덜** 찾을 뿐 지어내지는 않는다.
    """
    if not text:
        return ""

    def _blank(m) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)
    text = re.sub(r"//[^\n]*", _blank, text)
    return text


# C 식별자. **앞의 `\b` 가 이 정규식의 본체다.**
#
# `[A-Za-z_]\w*` 만 쓰면 정수 리터럴의 접미사가 식별자로 잡힌다:
#   re.findall(r"[A-Za-z_]\w*", "123U")  ->  ['U']      ← `123U` 안의 `U`
#   re.findall(r"[A-Za-z_]\w*", "0x1FUL") ->  ['x1FUL']  ← 통째로
# `\b` 는 앞 글자가 `\w` 면 경계가 아니므로 둘 다 **아무것도** 내놓지 않는다(정답).
#
# ## 실측 피해 (2026-08-12, KJPDS02)
#
# 이 저장소엔 `U` 라는 전역이 하나 등록돼 있었다(`@0x00FF9DF0U` 오파싱 — 아래
# `source_parser._parse_c_declaration_statement` 주석 참조). 그래서 두 결함이
# 맞물렸다: `#define VectorNumber_VReserved123 123U` 의 확장형에서 `U` 가 나오고,
# 그게 등록된 전역 이름과 일치해 매크로를 쓰는 **모든** 함수에 전역 `U` 가 붙었다.
# 결과는 **324개 함수** — 이 프로젝트에서 가장 많이 붙은 "전역" 1위였다.
# 그 함수들은 `U`(1글자)가 이름 필터에서 탈락하면서 입력 열이 통째로 비었다.
#
# 파라미터 이름 추출(`parse_param_name`)에서는 더 직접적이다:
#   `U8 buf[10U]` -> ids[-1] 이 `buf` 가 아니라 **`U`** 였다.
_C_IDENT_RE = re.compile(r"\b[A-Za-z_]\w*")


def c_identifiers(text: str) -> List[str]:
    """C 코드 조각에서 식별자 토큰만 뽑는다(정수 리터럴 접미사 제외)."""
    return _C_IDENT_RE.findall(str(text or ""))


@dataclass
class CFunction:
    name: str
    signature: str
    is_static: bool
    file: str
    calls: List[str]
    used_globals: List[str]
    comment_desc: str
    comment_asil: str
    comment_related: str
    comment_precondition: str
    body_text: str
    comment_params: Optional[List[Dict[str, str]]] = None  # [{"name": "x", "desc": "..."}]
    comment_return: str = ""
    func_refs: Optional[List[str]] = None      # &foo/pfn=foo/f(foo) — 함수포인터 참조(엣지 승격 후보)
    pointer_calls: Optional[List[str]] = None  # (*p)()/obj->h()/pfn() — 간접 호출 사이트(배지)


def _run_preprocessor(
    path: Path,
    *,
    cpp_path: str = "gcc",
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
) -> Optional[bytes]:
    include_dirs = include_dirs or []
    defines = defines or []

    def _uniq(seq: List[str]) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        for x in seq:
            k = str(x or "").strip()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    candidates = _uniq([cpp_path, "gcc", "clang", "cl.exe"])
    for tool in candidates:
        t = tool.lower()
        if t.endswith("cl.exe") or t == "cl":
            args = [tool, "/nologo", "/EP", str(path)]
            for inc in include_dirs:
                args.append(f"/I{inc}")
            for d in defines:
                args.append(f"/D{d}")
        else:
            args = [tool, "-E", str(path)]
            for inc in include_dirs:
                args.extend(["-I", inc])
            for d in defines:
                args.extend(["-D", d])
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        except Exception:
            continue
    return None


def _run_preprocessor_fallback(
    path: Path,
    *,
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
    cpp_path: str = "gcc",
) -> Tuple[Optional[bytes], str]:
    include_dirs = include_dirs or []
    defines = defines or []
    tried: List[str] = []
    for cand in [cpp_path, "clang"]:
        tool = str(cand or "").strip()
        if not tool or tool in tried:
            continue
        tried.append(tool)
        data = _run_preprocessor(
            path,
            cpp_path=tool,
            include_dirs=include_dirs,
            defines=defines,
        )
        if data is not None:
            return data, tool
    return None, "no-preprocess"


def _node_text(src: bytes, node) -> str:
    try:
        return src[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _find_ident(node) -> Optional[str]:
    if node.type == "identifier":
        return node.text.decode("utf-8", errors="ignore")
    for child in node.children:
        name = _find_ident(child)
        if name:
            return name
    return None


def _walk(node):
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        if cur.children:
            stack.extend(reversed(cur.children))


_CALLBACK_REGISTER_PATTERNS = re.compile(
    r"\b(?:register|set|install|add|attach|bind)_?\w*(?:callback|handler|hook|listener|func)\b",
    re.I,
)

# 함수포인터/콜백 관례 이름 — identifier 호출이 이 패턴이면 간접호출 후보로 본다(대상은 known
# 필터로 최종 판정). 구조적 간접호출((*p)()/obj->h()/tbl[i]())은 이름과 무관하게 잡는다.
# 'fp'(부동소수/프레임포인터 관례)는 실측상 참양성 0·타 프로젝트 거짓양성 위험만 있어 제외.
_PTR_CALL_NAME = re.compile(r"(^|_)(pfn|pfunc|cb|callback|handler|hook)\d*(_|$)", re.I)

_STD_LIB_FUNCS = frozenset({
    "printf", "sprintf", "snprintf", "fprintf", "scanf", "sscanf",
    "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "memmove", "memcmp",
    "strlen", "strcpy", "strncpy", "strcmp", "strncmp", "strcat", "strncat",
    "strstr", "strchr", "strrchr", "strtol", "strtoul", "atoi", "atol",
    "abs", "labs", "fabs", "sqrt", "pow", "log", "exp",
    "assert", "exit", "abort",
})

# 문/제어 키워드 — function_definition으로 오파싱되는 아티팩트(예: 매크로가 만든 `if(...)`) 방어.
_C_STMT_KEYWORDS = frozenset({"if", "for", "while", "switch", "return", "sizeof", "do", "else"})

# tree-sitter는 전처리기를 평가하지 않아 #if 0(죽은 코드)·#if 1 분기 본문을 그대로 파싱한다.
# preprocess=False 경로에서 죽은 코드의 함수 정의가 들어오면 동명 함수가 ASIL resolver/call-tree의
# last-wins로 활성 정의를 덮어 안전분류(ASIL D→B)·엣지를 왜곡한다 → 비활성 분기 함수를 제외한다.
_FALSY_COND = frozenset({"0", "0u", "0U", "0ul", "0UL", "(0)", "false", "FALSE"})
_TRUTHY_COND = frozenset({"1", "1u", "1U", "(1)", "true", "TRUE"})


def _dead_function_nodes(root, src: bytes) -> Set[int]:
    """비활성 전처리 분기의 function_definition 노드 id 집합.

    - `#if 0 … [#else …] #endif` → then-분기(else/elif 이전) 함수는 죽음.
    - `#if 1 … #else … #endif`   → else/elif(alternative) 분기 함수는 죽음(중첩 서브트리 포함).
    보수성 원칙: literal 0/1만 판정하고 `#elif` 조건은 평가하지 않는다. 그 결과 `#if 0 / #elif 1 / #else`의
    도달불가 `#else`, `#if 0 / #elif 0`의 죽은 `#elif`는 **살아남을 수 있다(과대포함)**. 이는 의도된 tradeoff —
    영향/추적 도구에서 과대포함(죽은 함수 몇 개 더 노출)은 안전 방향이며, 실함수를 숨기거나 지우거나 ASIL을
    강등하지 않는다(적대 검증 확인). 정밀 pruning이 필요하면 전처리(preprocess=True) 또는 elif 체인 평가를 추가하라.
    """
    dead: Set[int] = set()
    for node in _walk(root):
        if node.type != "preproc_if":
            continue
        cond = node.child_by_field_name("condition")
        cond_txt = _node_text(src, cond).strip() if cond is not None else ""
        alt = node.child_by_field_name("alternative")
        if cond_txt in _FALSY_COND:
            for ch in node.children:
                if ch is alt or ch.type in ("preproc_else", "preproc_elif"):
                    continue  # else/elif(활성 후보)는 살림
                for d in _walk(ch):
                    if d.type == "function_definition":
                        dead.add(d.id)
        elif cond_txt in _TRUTHY_COND and alt is not None:
            for d in _walk(alt):
                if d.type == "function_definition":
                    dead.add(d.id)
    return dead

_REGEX_DEF_PAT = re.compile(
    r"^[\t ]*((?:static\s+)?[A-Za-z_][\w\s\*\(\),]*?)\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*\{",
    flags=re.M,
)


def _extract_calls(func_node, src: bytes) -> List[str]:
    calls: Set[str] = set()
    body = func_node.child_by_field_name("body")
    if not body:
        return []
    for node in _walk(body):
        if node.type == "call_expression":
            target = node.child_by_field_name("function")
            if target is None and node.children:
                target = node.children[0]
            if target is None:
                continue
            if target.type == "parenthesized_expression":
                inner = _find_ident(target)
                if inner:
                    calls.add(inner)
                continue
            name = _find_ident(target)
            if name:
                calls.add(name)
                if _CALLBACK_REGISTER_PATTERNS.match(name):
                    args = node.child_by_field_name("arguments")
                    if args:
                        for arg_node in args.children:
                            if arg_node.type == "identifier":
                                cb_name = arg_node.text.decode("utf-8", errors="ignore")
                                if cb_name and not cb_name.isupper():
                                    calls.add(cb_name)
        elif node.type == "assignment_expression":
            right = node.child_by_field_name("right")
            if right and right.type == "identifier":
                rname = right.text.decode("utf-8", errors="ignore")
                left = node.child_by_field_name("left")
                if left:
                    lt = _node_text(src, left)
                    if "handler" in lt.lower() or "callback" in lt.lower() or "func" in lt.lower():
                        if rname and not rname.isupper():
                            calls.add(rname)
    return sorted(calls - _STD_LIB_FUNCS)


def _extract_func_refs(func_node, src: bytes) -> List[str]:
    """직접 호출은 아니나 함수를 '참조'하는 지점 — &foo 주소취득 / pfn = foo 대입 /
    f(..., foo, ...) 인자 전달. call_tree가 known 함수와의 교집합만 엣지로 승격해
    함수포인터 등록으로 인한 도달성(거짓 루트)을 복원한다. 변수 참조는 known 필터로 탈락."""
    out: Set[str] = set()
    body = func_node.child_by_field_name("body")
    if not body:
        return []
    for node in _walk(body):
        t = node.type
        if t == "pointer_expression":
            # &foo(주소취득)만 — *p(역참조)는 제외. 연산자는 첫 자식.
            if _node_text(src, node).lstrip().startswith("&"):
                arg = node.child_by_field_name("argument")
                if arg is not None and arg.type == "identifier":
                    out.add(arg.text.decode("utf-8", errors="ignore"))
        elif t == "assignment_expression":
            right = node.child_by_field_name("right")
            if right is not None and right.type == "identifier":
                out.add(right.text.decode("utf-8", errors="ignore"))
        elif t == "call_expression":
            args = node.child_by_field_name("arguments")
            if args is not None:
                for a in args.children:
                    if a.type == "identifier":
                        out.add(a.text.decode("utf-8", errors="ignore"))
    return sorted(out)


def _extract_pointer_calls(func_node, src: bytes) -> List[str]:
    """함수포인터/콜백을 통한 간접 호출 사이트(대상 미해결) — 정적 콜트리가 대상을 못 잇는 지점.
    (*p)() 역참조 · obj->h()/obj.h() 멤버 · tbl[i]() 첨자, 그리고 pfn/cb/handler 관례 이름
    identifier 호출을 수집한다. call_tree가 known으로 해결되는 항목은 제외하고 미해결분만 배지로 노출."""
    out: Set[str] = set()
    body = func_node.child_by_field_name("body")
    if not body:
        return []
    for node in _walk(body):
        if node.type != "call_expression":
            continue
        target = node.child_by_field_name("function")
        if target is None:
            continue
        tt = target.type
        if tt in ("field_expression", "subscript_expression"):
            out.add(_node_text(src, target).strip())
        elif tt == "pointer_expression":
            ident = _find_ident(target)
            if ident:
                out.add(ident)
        elif tt == "parenthesized_expression":
            # (*pfn)() 역참조만 — (type)(x)/(expr)(x) 캐스트·괄호식은 제외(오탐 방지).
            inner = next((ch for ch in target.children if ch.type == "pointer_expression"), None)
            if inner is not None:
                ident = _find_ident(inner)
                if ident:
                    out.add(ident)
        elif tt == "identifier":
            nm = target.text.decode("utf-8", errors="ignore")
            # not isupper(): 전대문자는 함수형 매크로(CALLBACK_HANDLER 등) 관례 → 간접호출 아님.
            # _extract_calls의 콜백 인자/대입 가드(isupper 제외)와 동일 정책으로 거짓 ⚡배지 방지.
            if _PTR_CALL_NAME.search(nm) and not nm.isupper():
                out.add(nm)
    return sorted(out)


def _extract_calls_from_body_text(body_text: str) -> List[str]:
    calls: Set[str] = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", str(body_text or "")):
        name = str(m.group(1) or "").strip()
        if not name or name.lower() in {"if", "for", "while", "switch", "return", "sizeof"}:
            continue
        if name in _STD_LIB_FUNCS:
            continue
        calls.add(name)
    return sorted(calls)


def _extract_leading_comment(src: bytes, start_byte: int) -> str:
    try:
        text = src[:start_byte].decode("utf-8", errors="ignore")
    except Exception:
        return ""
    if not text.strip():
        return ""
    # Block comment
    end_idx = text.rfind("*/")
    if end_idx != -1:
        start_idx = text.rfind("/*", 0, end_idx)
        if start_idx != -1:
            tail = text[end_idx + 2 :].strip()
            if not tail:
                return text[start_idx + 2 : end_idx].strip()
    # Line comments
    lines = text.splitlines()
    collected: List[str] = []
    for ln in reversed(lines):
        stripped = ln.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith("//"):
            collected.append(stripped[2:].strip())
        else:
            break
    return "\n".join(reversed(collected)).strip()


# _parse_comment_fields의 인라인 regex를 모듈 레벨로 승격 — 함수 주석 라인마다 호출돼
# Python re 캐시(512)를 넘겨 재컴파일 폭주하던 병목(프로파일 실측 ~53s) 제거.
_RE_NOISE_SEP = re.compile(r"[-=*#_/\\.\s]{4,}")
_RE_BIT_REGISTERS = re.compile(r"\b\d+\s*-\s*BIT\s+REGISTERS\b", re.I)
_RE_REGISTERS = re.compile(r"\bREGISTERS?\b", re.I)
_RE_SEP3 = re.compile(r"[*=-]{3,}")
_RE_C_BRIEF = re.compile(r"@brief\s+(.*)", re.I)
_RE_C_DETAILS = re.compile(r"@details?\s+(.*)", re.I)
_RE_C_ASIL = re.compile(r"\bASIL\b[:\s-]+([A-Za-z0-9-]+)", re.I)
_RE_C_RELATED = re.compile(r"\bRelated ID\b[:\s]+(.+)", re.I)
_RE_C_PRECOND = re.compile(r"(?:@pre|Pre-?condition|Precondition|Require(?:ment)?)\b[:\s]+(.+)", re.I)
_RE_C_PRECOND_KO = re.compile(r"선행조건[:\s]+(.+)")
_RE_C_RANGE = re.compile(r"\bRange\b[:\s]+(.+)", re.I)
_RE_C_VALUE_RANGE = re.compile(r"\bValue Range\b[:\s]+(.+)", re.I)
_RE_C_DESC = re.compile(r"\bDescription\b[:\s]+(.+)", re.I)
_RE_C_PARAM = re.compile(r"@param\s+(?:\[(?:in|out|in,\s*out)\]\s*)?(\w+)\s*(.*)", re.I)
_RE_C_RETURN = re.compile(r"@(?:return|retval)\s+(.*)", re.I)
_RE_C_TAG_SKIP = re.compile(r"@(?:note|see|warning|file|author|date|version|since|deprecated|todo|bug|throws|exception)\b", re.I)


def _parse_comment_fields(comment: str) -> Tuple[str, str, str, str, str, List[Dict[str, str]], str]:
    """Returns (desc, asil, related, precondition, range_text, params, return_desc)."""
    if not comment:
        return "", "", "", "", "", [], ""
    asil = ""
    related = ""
    precondition = ""
    range_text = ""
    desc = ""
    params: List[Dict[str, str]] = []
    return_desc = ""
    def _is_noise_desc(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return True
        if _RE_NOISE_SEP.fullmatch(t):
            return True
        if _RE_BIT_REGISTERS.search(t):
            return True
        if _RE_REGISTERS.search(t) and _RE_SEP3.search(t):
            return True
        return False
    brief_lines: List[str] = []
    details_lines: List[str] = []
    in_details = False
    for raw in comment.splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line:
            continue
        m_brief = _RE_C_BRIEF.match(line)
        if m_brief:
            brief_lines.append(m_brief.group(1).strip())
            in_details = False
            continue
        m_details = _RE_C_DETAILS.match(line)
        if m_details:
            details_lines.append(m_details.group(1).strip())
            in_details = True
            continue
        if in_details and not line.startswith("@"):
            details_lines.append(line)
            continue
        if line.startswith("@"):
            in_details = False
        if not asil:
            m = _RE_C_ASIL.search(line)
            if m:
                asil = m.group(1).strip()
                continue
        if not related:
            m = _RE_C_RELATED.search(line)
            if m:
                related = m.group(1).strip()
                continue
        if not precondition:
            m = _RE_C_PRECOND.search(line)
            if m:
                precondition = m.group(1).strip()
                continue
            m = _RE_C_PRECOND_KO.search(line)
            if m:
                precondition = m.group(1).strip()
                continue
        if not range_text:
            m = _RE_C_RANGE.search(line)
            if m:
                range_text = m.group(1).strip()
                continue
            m = _RE_C_VALUE_RANGE.search(line)
            if m:
                range_text = m.group(1).strip()
                continue
        if not desc:
            m = _RE_C_DESC.search(line)
            if m:
                cand = m.group(1).strip()
                if not _is_noise_desc(cand):
                    desc = cand
                continue
        m_param = _RE_C_PARAM.match(line)
        if m_param:
            params.append({"name": m_param.group(1).strip(), "desc": m_param.group(2).strip()})
            in_details = False
            continue
        m_ret = _RE_C_RETURN.match(line)
        if m_ret:
            return_desc = m_ret.group(1).strip()
            in_details = False
            continue
        if not desc:
            if _is_noise_desc(line):
                continue
            if _RE_C_TAG_SKIP.match(line):
                continue
            desc = line
    if not desc and brief_lines:
        desc = " ".join(brief_lines).strip()
    if details_lines:
        details_text = " ".join(details_lines).strip()
        if desc:
            desc = f"{desc} {details_text}".strip()
        else:
            desc = details_text
    if params and desc:
        param_names = ", ".join(p["name"] for p in params)
        if return_desc:
            desc = f"{desc} (params: {param_names}; returns: {return_desc})"
        else:
            desc = f"{desc} (params: {param_names})"
    elif not desc and params:
        param_names = ", ".join(p["name"] for p in params)
        desc = f"Parameters: {param_names}"
        if return_desc:
            desc += f"; Returns: {return_desc}"
    elif not desc and return_desc:
        desc = f"Returns: {return_desc}"
    return desc, asil, related, precondition, range_text, params, return_desc


def _extract_function_defs(
    root, src: bytes, file_path: str, globals_set: Set[str]
) -> List[CFunction]:
    functions: List[CFunction] = []
    # root.children(직계)만 보면 #if/#ifdef(preproc_if) 안에 감싼 함수 정의를 통째로 놓쳐(이 코드베이스의
    # 안전 관련 파일 다수) tree-sitter가 0개→전 파일 regex 폴백되던 결함. 전체 트리를 순회해 어느 깊이의
    # function_definition도 잡는다(C는 함수 중첩 불가 → 중복 처리 없음).
    # 단 #if 0(죽은 코드) 분기 함수는 제외 — 동명 활성 함수의 ASIL/엣지를 last-wins로 덮는 안전결함 방지.
    dead = _dead_function_nodes(root, src)
    for node in _walk(root):
        if node.type != "function_definition" or node.id in dead:
            continue
        decl = node.child_by_field_name("declarator")
        decl_text = _node_text(src, decl) if decl else ""
        name = _find_ident(decl) if decl else None
        if not name or name in _C_STMT_KEYWORDS:
            # 매크로/K&R 등으로 `if(...)`가 function_definition으로 오파싱되는 아티팩트 방어(regex 폴백과 동일 정책).
            continue
        prefix = _node_text(src, node.child_by_field_name("type")) or ""
        is_static = "static" in prefix
        signature = (prefix + " " + decl_text).strip()
        calls = _extract_calls(node, src)
        func_refs = _extract_func_refs(node, src)
        pointer_calls = _extract_pointer_calls(node, src)
        used_globals: Set[str] = set()
        body = node.child_by_field_name("body")
        body_text = _node_text(src, body) if body else ""
        if body:
            for n in _walk(body):
                if n.type == "identifier":
                    ident = n.text.decode("utf-8", errors="ignore")
                    parent = getattr(n, "parent", None)
                    if parent is not None and parent.type == "call_expression":
                        continue
                    if ident in globals_set and ident != name:
                        used_globals.add(ident)
        comment = _extract_leading_comment(src, node.start_byte)
        desc, asil, related, precondition, _, c_params, c_return = _parse_comment_fields(comment)
        functions.append(
            CFunction(
                name=name,
                signature=signature,
                is_static=is_static,
                file=file_path,
                calls=calls,
                used_globals=sorted(used_globals),
                comment_desc=desc,
                comment_asil=asil,
                comment_related=related,
                comment_precondition=precondition,
                body_text=body_text,
                comment_params=c_params or None,
                comment_return=c_return,
                func_refs=func_refs,
                pointer_calls=pointer_calls,
            )
        )
    return functions


def _extract_function_defs_regex_fallback(
    text: str,
    file_path: str,
    globals_set: Set[str],
) -> List[CFunction]:
    if not text:
        return []
    functions: List[CFunction] = []
    keywords = {"if", "for", "while", "switch", "return", "sizeof"}
    text_bytes = text.encode("utf-8", errors="ignore")
    # ⚠ **주석 안에서 함수를 찾지 않는다.** Processor Expert 가 만든 `Generated_Code/*.c`
    #   는 매크로로 구현된 접근자의 프로토타입을 주석에 남긴다:
    #       /*
    #       bool PS3_MOTOR_NSCS_GetVal(void)
    #       **  This method is implemented as a macro. See ....h file.  **
    #       */
    #   tree-sitter 는 이 파일을 "함수 0개" 로 **정확히** 읽는데, 그러면 호출부의
    #   `if not funcs:` 가 이 폴백을 돌려 정규식이 주석을 훑고 **없는 함수를 만들어냈다**.
    #   파라미터 `[^;]*?` 가 주석 경계를 넘어 다음 함수의 `{` 까지 먹어 시그니처가 통째로
    #   오염되기까지 했다. 정본 SUTS 엔 이 접근자들이 하나도 없다 — 존재하지 않는 함수의
    #   시험 케이스를 만들고 있었다는 뜻이다.
    #   ⚠ 매칭용 텍스트만 가린다. 본문·주석 추출은 원문(`text`/`text_bytes`)에서 하며,
    #     `_blank_c_comments` 가 **길이를 유지**하므로 오프셋이 어긋나지 않는다.
    scan_text = blank_c_comments(text)
    for match in _REGEX_DEF_PAT.finditer(scan_text):
        prefix = str(match.group(1) or "").strip()
        name = str(match.group(2) or "").strip()
        params = " ".join(str(match.group(3) or "").replace("\n", " ").split())
        if not name or name in keywords:
            continue
        brace_start = match.end() - 1
        depth = 0
        brace_end = brace_start
        for idx in range(brace_start, len(text)):
            ch = text[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    brace_end = idx
                    break
        body_text = text[brace_start + 1 : brace_end].strip() if brace_end > brace_start else ""
        used_globals: Set[str] = set()
        for ident in re.findall(r"\b([A-Za-z_]\w*)\b", body_text):
            if ident in globals_set and ident != name:
                used_globals.add(ident)
        try:
            start_byte = len(text[: match.start()].encode("utf-8", errors="ignore"))
        except Exception:
            start_byte = 0
        comment = _extract_leading_comment(text_bytes, start_byte)
        desc, asil, related, precondition, _, c_params, c_return = _parse_comment_fields(comment)
        functions.append(
            CFunction(
                name=name,
                signature=f"{prefix} {name}({params})".strip(),
                is_static="static" in prefix.lower().split(),
                file=file_path,
                calls=_extract_calls_from_body_text(body_text),
                used_globals=sorted(used_globals),
                comment_desc=desc,
                comment_asil=asil,
                comment_related=related,
                comment_precondition=precondition,
                body_text=body_text,
                comment_params=c_params or None,
                comment_return=c_return,
            )
        )
    return functions


def _extract_globals(root, src: bytes) -> List[str]:
    globals_list: List[str] = []
    for node in root.children:
        if node.type != "declaration":
            continue
        decl_text = _node_text(src, node)
        # Skip function prototypes/declarations at global scope.
        if "(" in decl_text and ")" in decl_text:
            continue
        name = _find_ident(node) or ""
        if name and name not in globals_list:
            globals_list.append(name)
    return globals_list


def _extract_global_decls(root, src: bytes) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for node in root.children:
        if node.type != "declaration":
            continue
        type_node = node.child_by_field_name("type")
        type_text = _node_text(src, type_node).strip() if type_node else ""
        decl_text = _node_text(src, node)
        # Skip function declarations/prototypes and function pointer typedef-like declarations.
        if "(" in decl_text and ")" in decl_text:
            continue
        range_text = ""
        range_source = ""
        if decl_text:
            m = re.search(r"(0x[0-9A-Fa-f]+|\\d+)\\s*~\\s*(0x[0-9A-Fa-f]+|\\d+)", decl_text)
            if m:
                range_text = f"{m.group(1)} ~ {m.group(2)}"
                range_source = "decl"
        comment = _extract_leading_comment(src, node.start_byte)
        desc_text = ""
        if comment:
            dtext, _, _, _, rtext, _, _ = _parse_comment_fields(comment)
            desc_text = dtext or ""
            if rtext:
                range_text = rtext
                range_source = "comment"
        is_static = "static" in decl_text
        handled = False
        for child in node.children:
            if child.type != "init_declarator":
                continue
            handled = True
            decl_node = child.child_by_field_name("declarator") or child
            name = _find_ident(decl_node) or ""
            init_node = child.child_by_field_name("value")
            init_text = _node_text(src, init_node).strip() if init_node else ""
            if not name:
                continue
            results.append(
                {
                    "name": name,
                    "type": type_text,
                    "init": init_text,
                    "range": range_text,
                    "decl": decl_text,
                    "range_source": range_source,
                    "is_static": "true" if is_static else "false",
                    "desc": desc_text,
                }
            )
        if not handled:
            name = _find_ident(node) or ""
            if name:
                results.append(
                    {
                        "name": name,
                        "type": type_text,
                        "init": "",
                        "range": range_text,
                        "decl": decl_text,
                        "range_source": range_source,
                        "is_static": "true" if is_static else "false",
                        "desc": desc_text,
                    }
                )
    return results


def _make_parser():
    """tree_sitter 버전차/capsule 1회성 소비 함정을 흡수하는 견고한 파서 생성.

    구버전 API `Parser.set_language`는 최신 tree_sitter에서 제거됐는데, 실패한 set_language 호출이
    c_language() capsule을 소비해 이후 `Language(capsule)`이 '빈 문법'이 되는 함정이 있다 — 파싱은
    되나 function_definition 0개가 되어 전 파일이 조용히 regex 폴백되고, 엔진은 import 유무만 보고
    'tree-sitter'로 오표기됐다(정밀 엔진이 실제로는 regex였음). 시도마다 capsule을 새로 얻고, 실제
    C 스니펫에서 function_definition이 나오는지 검증한 뒤 반환한다. 모두 실패하면 None(→regex 폴백)."""
    if Parser is None or c_language is None:
        return None

    def _valid(p) -> bool:
        try:
            t = p.parse(b"int _ts_probe(void){return 0;}")
            return any(n.type == "function_definition" for n in _walk(t.root_node))
        except Exception:
            return False

    if Language is not None:
        # 1) 최신 권장: Parser(Language(capsule))
        try:
            p = Parser(Language(c_language()))
            if _valid(p):
                return p
        except Exception:
            pass
        # 2) .language 속성 대입(중간 버전)
        try:
            p = Parser()
            p.language = Language(c_language())
            if _valid(p):
                return p
        except Exception:
            pass
    # 3) 구버전: set_language(capsule)
    try:
        p = Parser()
        p.set_language(c_language())
        if _valid(p):
            return p
    except Exception:
        pass
    return None


def parse_c_project(
    source_root: str,
    *,
    max_files: int = 300,
    preprocess: bool = False,
    include_dirs: Optional[List[str]] = None,
    defines: Optional[List[str]] = None,
    cpp_path: str = "gcc",
) -> Dict[str, object]:
    root = Path(source_root).resolve()
    if not root.exists():
        return {"functions": [], "globals": [], "scanned": []}
    allowed = {".c", ".h", ".cpp", ".hpp"}
    functions: List[Dict[str, object]] = []
    globals_list: Set[str] = set()
    globals_detailed: List[Dict[str, str]] = []
    scanned: List[str] = []
    preprocess_stats: Dict[str, int] = {"gcc": 0, "clang": 0, "no-preprocess": 0}
    parser = _make_parser()
    count = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() not in allowed:
                continue
            path = Path(dirpath) / name
            count += 1
            if count > max_files:
                break
            scanned.append(str(path))
            try:
                preprocessor_used = "no-preprocess"
                if preprocess:
                    data, preprocessor_used = _run_preprocessor_fallback(
                        path,
                        include_dirs=include_dirs,
                        defines=defines,
                        cpp_path=cpp_path,
                    )
                else:
                    data = None
                if data is None:
                    preprocessor_used = "no-preprocess"
                    data = path.read_bytes()
                preprocess_stats[preprocessor_used] = preprocess_stats.get(preprocessor_used, 0) + 1
            except Exception:
                continue
            raw_text = ""
            try:
                raw_text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                raw_text = ""
            file_globals: Set[str] = set()
            funcs: List[CFunction] = []
            root_node = None
            if parser is not None:
                tree = parser.parse(data)
                root_node = tree.root_node
                file_globals = set(_extract_globals(root_node, data))
                funcs = _extract_function_defs(root_node, data, str(path), file_globals)
            if not funcs:
                funcs = _extract_function_defs_regex_fallback(raw_text, str(path), file_globals)
            for f in funcs:
                functions.append(
                    {
                        "name": f.name,
                        "signature": f.signature,
                        "is_static": f.is_static,
                        "file": f.file,
                        "calls": f.calls,
                        "used_globals": f.used_globals,
                        "comment_desc": f.comment_desc,
                        "comment_asil": f.comment_asil,
                        "comment_related": f.comment_related,
                        "comment_precondition": f.comment_precondition,
                        "body": f.body_text,
                        "func_refs": f.func_refs or [],
                        "pointer_calls": f.pointer_calls or [],
                    }
                )
            if root_node is not None:
                # 776에서 이미 파싱한 root_node 재사용(재파싱 제거). file_globals도 778 결과 재사용.
                for g in file_globals:
                    if not g:
                        continue
                    globals_list.add(g)
                    globals_detailed.append({"name": g, "file": str(path)})
                for g in _extract_global_decls(root_node, data):
                    if not isinstance(g, dict):
                        continue
                    name = g.get("name") or ""
                    if not name:
                        continue
                    globals_list.add(name)
                    g["file"] = str(path)
                    globals_detailed.append(g)
        if count > max_files:
            break
    return {
        "functions": functions,
        "globals": sorted(globals_list),
        "globals_detailed": globals_detailed,
        "scanned": scanned,
        "preprocess_stats": preprocess_stats,
        # 실제 파서 성공 여부를 정직하게 노출 — import 유무가 아니라 검증된 tree-sitter 파서인지.
        "parser_engine": "tree-sitter" if parser is not None else "regex-fallback",
    }
