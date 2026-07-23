# workflow/delta_update.py
"""Delta Update - identify changed functions and regenerate only affected UDS sections.

Uses git/svn diff to find changed files, then cross-references with the call graph
to determine the full impact set of functions that need UDS regeneration.
"""

from __future__ import annotations

import subprocess
import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# 반환타입 인식: 닫힌 allowlist가 아니라 "제어키워드가 아닌 식별자"로 구조 인식한다.
# ⚠ under-report fix: 과거엔 반환타입이 `void|int|U\d+|uint\d+_t|...` 닫힌 목록이라 프로젝트 고유
#   반환타입(byte·word·UINT8(bare)·l_u8·Std_ReturnType·Dem_ReturnType·typedef ScanState_t 등)의
#   함수가 func_decl_names에 안 잡혀 SIGNATURE/NEW/DELETE가 전부 BODY로 오분류됐다 → (a) 시그니처
#   변경인데 SDS 자동 FLAG 누락, (b) 삭제 함수가 by_name 부재 + DELETE 미탐으로 impact 집합에서
#   통째 유실. 실 kjpds02 소스 함수정의의 ~9.5%가 미인식 반환타입이었다(deep-review CONFIRMED).
# 안전성: `<type> <name>(` 2-토큰 구조라 함수 호출(1-토큰)·대입(`x = f(`)·캐스트는 자연 배제되고,
#   `<kw> <name>(` 형태로 오탐 가능한 제어키워드(return/else/do/case ...)만 negative lookahead로
#   차단한다. 오인식이 남더라도 방향은 과대보고(SIGNATURE/NEW/DELETE 과다 = 검토 확대 = 안전측).
_RET_TYPE = r"(?!(?:if|for|while|switch|return|sizeof|do|else|case|goto)\b)[A-Za-z_]\w*"
_FUNC_DECL_LINE = re.compile(
    r"^[+-]\s*(?:(?:static|extern|inline|const|volatile)\s+)*"
    + _RET_TYPE +
    r"[\w\s\*]*\s+(\w+)\s*\(",
    re.MULTILINE,
)
_FUNC_PROTO_LINE = re.compile(
    r"^[+-]\s*(?:(?:extern|static|inline|volatile|const)\s+)*"
    + _RET_TYPE +
    r"[\w\s\*\(\),]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;",
    re.MULTILINE,
)
# 접두(+/-) 없는 순수 텍스트(OLD/NEW 투영본)용 함수 선언 매처 — _scan_decls에서 사용.
# _FUNC_DECL_LINE과 동형이나 `^[+-]` 앵커 대신 라인 시작(선행 공백 허용)에 매칭한다.
_FUNC_DECL_LINE_PLAIN = re.compile(
    r"^\s*(?:(?:static|extern|inline|const|volatile)\s+)*"
    + _RET_TYPE +
    r"[\w\s\*]*\s+(\w+)\s*\(",
)
_HUNK_FUNC = re.compile(r"^@@.*@@\s*(?:.*?\s)?(\w+)\s*\(", re.MULTILINE)
# 모듈 레벨(컬럼0) 변수 선언만 매치 — `^[+-]` 직후 들여쓰기 없이 한정자/타입이 와야 한다.
# 과거 `^[+-]\s*`는 들여쓴 **지역변수**(함수 본문 내 `+    S32 s32t_NextIdx;`)까지 잡아,
# 시그니처가 hunk context(무변경)인 함수를 BODY 아닌 VARIABLE로 오분류→"글로벌 변수 변경" 오안내
# 했다(deep-review 지적). C 전역/정적은 컬럼0, 지역은 들여쓰기라 이 경계로 구분한다. VARIABLE·BODY는
# 둘 다 sds FLAG를 걸지 않아(ACTION_MATRIX) 안전 판정 불변 — 가이드 정확도 개선. 들여쓴 전역(#if
# 블록 등, 드묾)은 narrowable=False 안전망으로 파일단위 보수 유지되므로 under-report 아님.
_VAR_DECL_LINE = re.compile(
    r"^[+-](?:static\s+)?(?:const\s+|volatile\s+|unsigned\s+|signed\s+)*"
    r"(?:void|char|bool|float|double|int|long|short|u?int\d+(?:_t)?|U\d+|S\d+|[A-Za-z_]\w*_t)\b"
    r"(?!.*\()"
    r".*?\b([sg]_[A-Za-z0-9_]+|[A-Za-z0-9_]+)\b\s*(?:\[.*\])?\s*(?:=|;|,)",
    re.MULTILINE,
)

# --- 함수단위 narrowing 안전성(allowlist) 판정 신호 --------------------------------
# 정책: "위험 패턴 열거(blocklist)"가 아니라 "안전이 증명될 때만 narrow(allowlist)". 미인식
# top-level 구성(배열·값테이블·typedef·enum·struct·전역var·포인터·조건부컴파일·bare hunk)은
# 아래 셋 중 하나에 걸려 자동으로 narrowable=False(파일단위 보수 유지, 안전측 — under-report 방지).
_HUNK_ANY = re.compile(r"^@@ ", re.MULTILINE)  # 모든 hunk 마커(귀속 커버리지 분모)
# 전처리 지시자 변경 전부(#define/#undef/#if/#ifdef/#ifndef/#include/#pragma/#error 등) — 라인변경
# 없는 함수의 컴파일 여부/경로/매크로 전개를 바꿔 전역 영향.
_PREPROC_CHANGE = re.compile(r"^[+-]\s*#", re.MULTILINE)
# 컬럼0(함수 밖) 변경 라인 — +/- 직후 공백 없이 식별자/중괄호가 오는 라인. 전역var·배열·typedef·
# enum·struct·함수 시그니처·닫는 브레이스 등 top-level 편집을 포괄 차단한다(함수 '본문'은 들여쓰기라
# +/- 뒤 공백 → 미매치). 함수 시그니처(컬럼0)도 걸려 그 파일은 fatten 유지되나, 해당 함수는 kind
# 승격(SIGNATURE)은 그대로 받는다(안전측 — set은 보수, kind는 정확).
_TOPLEVEL_CHANGE = re.compile(r"^[+-][A-Za-z_{}]", re.MULTILINE)
# 초기화자 컨텍스트 — `@@ ... @@ static const T g = MK_CFG(1,` 처럼 값-전용 편집의 hunk 컨텍스트가
# 함수가 아니라 파일스코프 데이터 초기화(= ... word()인 경우. `_HUNK_FUNC`가 이를 함수로 오귀속해
# narrowable을 부여하면(값 변경의 데이터 리더 함수 누락) under-report가 되므로 별도 차단한다(안전측).
# (함수 시그니처엔 '='가 없어 무영향. 이 코드베이스엔 `= MACRO(` 파일스코프 초기화자 0건이나 방어적.)
_HUNK_INIT_CTX = re.compile(r"^@@.*@@.*=.*\b\w+\s*\(", re.MULTILINE)

# --- hunk 함수귀속 오탐 차단 --------------------------------------------------------
# `_HUNK_FUNC`는 "'(' 바로 앞 식별자"를 잡으므로 함수가 아닌 컨텍스트도 매치한다:
#   `@@ .. @@ u8 (*pf)(void)`  → 'u8'   (함수포인터/캐스트 — 타입명)
#   `@@ .. @@ if (cond)`       → 'if'   (제어문 — svn -p가 함수 못 찾을 때)
# 이 가비지가 흘러가면 (a) function_diffs에 존재하지 않는 함수 키가 생겨 증거가 오염되고,
# (b) narrowable 판정의 귀속 커버리지(ctx_hunks)가 과대계상돼 "모든 hunk가 함수에 귀속됨"이
# 거짓 성립 → 라인변경 없는 함수 제거(narrow)가 부당하게 허용된다(under-report 위험).
# 안전성: 거부하면 ctx_hunks < total_hunks → narrowable=False → 파일단위 fatten 유지(보수측).
# 즉 과잉 거부는 정밀도만 떨어뜨리고 절대 under-report를 만들지 않는다(자기일관적).
_NON_FUNC_TOKENS = frozenset({
    "if", "else", "for", "while", "switch", "case", "do", "return", "sizeof", "goto",
    "typedef", "struct", "union", "enum", "static", "extern", "inline", "const", "volatile",
    "register", "auto", "signed", "unsigned", "void", "char", "short", "int", "long",
    "float", "double", "bool", "defined",
})
# 정수 타입 별칭(u8/U16/s32/uint8_t/size_t 등) — 캐스트·함수포인터 컨텍스트의 오귀속 토큰.
_TYPE_ALIAS = re.compile(r"^(?:[usiUSI]\d{1,2}|u?int\d{1,2}(?:_t)?|[A-Za-z_]\w*_t)$")


def _hunk_func_name(line: str) -> Optional[str]:
    """hunk 헤더(`@@ .. @@ <ctx>`)에서 함수명 추출. 타입/키워드 오귀속이면 None(안전측 거부)."""
    m = _HUNK_FUNC.match(line)
    if not m:
        return None
    name = m.group(1)
    if name in _NON_FUNC_TOKENS or _TYPE_ALIAS.match(name):
        return None
    return name


def _hunk_func_names(diff_text: str) -> List[str]:
    """diff 전체에서 유효 함수귀속 이름 목록(오탐 제외). ctx_hunks 분자와 동일 기준."""
    out: List[str] = []
    for ln in (diff_text or "").splitlines():
        if not ln.startswith("@@"):
            continue
        nm = _hunk_func_name(ln)
        if nm:
            out.append(nm)
    return out


def _run_unified_diff(
    project_root: str,
    *,
    base_ref: str,
    scm_type: str,
    file_path: Optional[str] = None,
) -> str:
    root = Path(project_root)

    if scm_type == "svn":
        # -x -p (show-c-function): @@ hunk 헤더에 함수 컨텍스트를 붙여 extract_function_diffs가
        # 함수 귀속 가능하게 한다(svn_diff_unified와 동형). 과거 `--diff-cmd diff -x -U3`은 컨텍스트가
        # 없어(-p 누락) 로컬 diff 경로에서 function_diffs가 빈 채로 남아 "원문 절단"을 유발했다.
        # svn 내부 diff는 외부 diff 바이너리 의존도 없앤다. extract_signature_changes(+/- 선언)는 무해.
        cmd = ["svn", "diff"]
        if str(base_ref or "").strip():
            cmd.extend(["-r", base_ref])
        cmd.extend(["-x", "-p"])
        if file_path:
            cmd.append(file_path)
    else:
        cmd = ["git", "diff", base_ref]
        if file_path:
            cmd.extend(["--", file_path])

    result = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="ignore",
        timeout=30,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout

    if scm_type == "svn":
        fallback_cmd = ["svn", "diff", "-x", "-p"]
        if file_path:
            fallback_cmd.append(file_path)
        fallback = subprocess.run(
            fallback_cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=30,
        )
        if fallback.returncode == 0:
            return fallback.stdout
    return ""


def get_changed_files(
    project_root: str,
    *,
    base_ref: str = "HEAD~1",
    scm_type: str = "git",
) -> List[str]:
    """Get list of changed .c/.h files since base_ref."""
    root = Path(project_root)
    changed: List[str] = []

    try:
        if scm_type == "git":
            result = subprocess.run(
                ["git", "diff", "--name-only", base_ref, "--", "*.c", "*.h"],
                cwd=str(root), capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                changed = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        elif scm_type == "svn":
            if str(base_ref or "").strip():
                cmd = ["svn", "diff", "--summarize", "-r", base_ref]
            else:
                cmd = ["svn", "status"]
            result = subprocess.run(
                cmd,
                cwd=str(root), capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if not parts:
                        continue
                    fpath = parts[-1].strip()
                    if fpath.endswith((".c", ".h")):
                        changed.append(fpath)
    except Exception as e:
        logger.warning("Failed to get changed files via %s: %s", scm_type, e)

    return changed


def get_changed_functions(
    project_root: str,
    changed_files: List[str],
    *,
    base_ref: str = "HEAD~1",
    scm_type: str = "git",
) -> Set[str]:
    """Extract function names that were modified in the diff."""
    changed_funcs: Set[str] = set()

    for fpath in changed_files:
        try:
            diff_text = _run_unified_diff(
                project_root,
                base_ref=base_ref,
                scm_type=scm_type,
                file_path=fpath,
            )
            for m in _FUNC_DECL_LINE.finditer(diff_text):
                changed_funcs.add(m.group(1))
            for _nm in _hunk_func_names(diff_text):  # 타입/키워드 오귀속 제외
                changed_funcs.add(_nm)
        except Exception as e:
            logger.warning("Failed to parse diff for %s: %s", fpath, e)

    return changed_funcs


def _classify_from_edit_types(
    changed_files: List[str], edit_types: Dict[str, str]
) -> Dict[str, str]:
    """Jenkins changeSet editType(파일경로→add/edit/delete) 기반 파일 단위 분류.

    cloudium/원격에서 로컬 working-copy diff가 불가할 때 사용. diff(subprocess) 없이
    add→NEW / delete→DELETE / edit·미상→.h:HEADER·.c:BODY로 분류한다. SIGNATURE는 diff
    없이 구분 불가하므로 BODY로 보수 처리(영향 과대평가=안전측). 키는 파일 stem(소문자)로,
    _resolve_changed_types_to_functions가 by_name을 통해 실제 함수에 재매핑한다.
    """
    norm = {
        str(k).replace("\\", "/").strip().lower(): str(v or "").strip().lower()
        for k, v in (edit_types or {}).items()
    }
    out: Dict[str, str] = {}
    for fpath in changed_files:
        raw = str(fpath or "").strip()
        if not raw:
            continue
        stem = Path(raw).stem.lower()
        if not stem:
            continue
        et = norm.get(raw.replace("\\", "/").lower(), "edit")
        if et == "add":
            kind = "NEW"
        elif et == "delete":
            kind = "DELETE"
        else:  # edit/modify/기타
            kind = "HEADER" if raw.lower().endswith(".h") else "BODY"
        # 동일 stem 다중 파일: 구조적 변경(NEW/DELETE)은 단순 edit이 덮어쓰지 않게 보존.
        if out.get(stem) in {"NEW", "DELETE"}:
            continue
        out[stem] = kind
    return out


def _reconstruct_diff_decls(diff_text: str):
    """unified diff의 함수 선언 라인을 (부호, 함수명, 선언원문)으로 순회 — **멀티라인 선언 복원**.

    멀티라인 선언(파라미터가 여러 줄)은 첫 줄이 `(`만 열고 닫히지 않아, 종전엔
    `_classify_one_file_diff`(verdict 'unknown'→보수적 SIGNATURE)와 `extract_signature_changes`
    (빈 before/after→UI '원문 미확보')가 **둘 다 통째 스킵**했다. 그 결과 선언이 -/+ 양쪽에
    '동일'하게 나타나는 리포맷/재정렬 churn에서 **멀티라인 함수만 false SIGNATURE로 갇혔다**
    (kjpds02 s_sha256_expand_word·s_sha256_round_step·s_SysEepromCtrl_CopyTunningTables — 단일라인
    형제 함수는 same→BODY로 정상 강등되는데 멀티라인만 비교 불가라 침묵 오분류). 여는 괄호가
    균형을 이룰 때까지 **같은 부호(+/-)의 연속 라인**을 이어 붙여 온전한 선언을 복원하고, 본문
    `{`·프로토 `;` 이후를 제거한 뒤 연속 공백을 1칸으로 정규화(정렬 패딩 차이 흡수)해 비교 가능케 한다.

    - 부호는 '+' 또는 '-'. 선언원문은 정규화된 단일 문자열.
    - 복원해도 괄호가 안 맞으면(훅 경계로 절단된 멀티라인 등) 호출측이 불균형을 보고 '미확보'로
      보수 처리한다(과거와 동일 — under-report 방지). 단일라인 선언은 continuation 미소비 → 무변경.
    """
    lines = diff_text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if len(line) < 2 or line[0] not in "+-" or line[:3] in ("+++", "---"):
            i += 1
            continue
        m = _FUNC_DECL_LINE.match(line) or _FUNC_PROTO_LINE.match(line)
        if not m:
            i += 1
            continue
        polarity = line[0]
        content0 = line[1:]
        parts = [content0]
        depth = content0.count("(") - content0.count(")")
        j = i + 1
        # 여는 괄호가 남아 있으면(멀티라인) 같은 부호의 다음 라인을 이어 붙인다(상한 16줄 — 폭주 방지).
        while depth > 0 and j < n and (j - i) < 16:
            nxt = lines[j]
            if not nxt or nxt[0] != polarity or nxt[:3] in ("+++", "---"):
                break
            content = nxt[1:]
            parts.append(content)
            depth += content.count("(") - content.count(")")
            j += 1
        decl = " ".join(parts)
        _brace = decl.find("{")           # 본문 여는 중괄호 이후는 선언부 아님 → 절단
        if _brace >= 0:
            decl = decl[:_brace]
        decl = re.sub(r"\s+", " ", decl).strip().rstrip(";").strip()
        yield polarity, m.group(1), decl
        i = j if j > i + 1 else i + 1


def _scan_decls(text: str) -> Dict[str, str]:
    """접두(+/-) 없는 coherent C 텍스트(OLD/NEW 투영본)에서 함수 선언/정의 헤더를
    {funcname: 정규화 선언원문}으로 추출. 멀티라인 파라미터를 괄호 균형까지 이어붙이고 본문 `{`·
    프로토 `;` 이전만 취한다. **균형 복원된 선언만 기록**(절단 시 미기록 — 한쪽만 잘려 false diff
    나는 것 방지). 함수당 첫 매치(대개 1개). _sig_changes_from_projections 전용 헬퍼."""
    out: Dict[str, str] = {}
    lines = text.split("\n")
    n = len(lines)
    i = 0
    while i < n:
        m = _FUNC_DECL_LINE_PLAIN.match(lines[i])
        if not m:
            i += 1
            continue
        parts = [lines[i]]
        depth = lines[i].count("(") - lines[i].count(")")
        j = i + 1
        while depth > 0 and j < n and (j - i) < 16:
            parts.append(lines[j])
            depth += lines[j].count("(") - lines[j].count(")")
            j += 1
        decl = " ".join(parts)
        _brace = decl.find("{")
        if _brace >= 0:
            decl = decl[:_brace]
        decl = re.sub(r"\s+", " ", decl).strip().rstrip(";").strip()
        if depth <= 0 and m.group(1) not in out:  # 균형 복원된 선언만(절단 제외 — false diff 방지)
            out[m.group(1)] = decl
        i = j if j > i + 1 else i + 1
    return out


def _sig_changes_from_projections(diff_text: str) -> Dict[str, Dict[str, str]]:
    """각 hunk를 OLD 투영(context+'-')·NEW 투영(context+'+')으로 재구성해, 양쪽에서 복원한 함수
    선언이 실제로 다른 함수만 {func:{before,after}}로 반환한다(연속행 시그니처 변경 탐지).

    멀티라인 함수의 첫 줄(함수명+'(')이 context(무변경)이고 뒤 파라미터 연속행만 -/+로 바뀌면,
    변경 라인에 `funcname(` 토큰이 없어 `_reconstruct_diff_decls`(+/- 앵커)와 func_decl_names가
    못 잡아 SIGNATURE→VARIABLE/BODY로 under-report됐다(deep-review 발견1 — SDS 자동 FLAG 누락,
    ISO 26262 영향증거 최악 방향). 투영 재구성은 첫 줄이 context든 +/-든 무관하게 완전 선언을
    복원하므로 old!=new면 시그니처 변경으로 정확히 잡는다.

    - before==after(리포맷 churn·무변화)·NEW/DELETE(한쪽만)는 방출 안 함 — 순수 '변경' 신호만.
      → 안전측: old==new면 침묵(over-report 없음), churn false SIGNATURE를 되살리지 않음.
    - 한계: hunk가 함수명 줄보다 뒤에서 시작하면(긴 파라미터 목록의 깊은 변경) 함수명 줄이 hunk
      context 밖이라 미탐(드묾). 현 상태(전 연속행 변경 미탐)보다 열화가 아니라 개선이다.
    """
    out: Dict[str, Dict[str, str]] = {}
    old_lines: List[str] = []
    new_lines: List[str] = []

    def _flush() -> None:
        if not old_lines and not new_lines:
            return
        _before = _scan_decls("\n".join(old_lines))
        _after = _scan_decls("\n".join(new_lines))
        for _fn in set(_before) & set(_after):  # 양쪽 존재(=시그니처 변경). NEW/DELETE는 한쪽만이라 제외
            if _before[_fn] != _after[_fn]:
                out.setdefault(_fn, {"before": _before[_fn], "after": _after[_fn]})

    for ln in diff_text.splitlines():
        if ln.startswith("@@"):
            _flush()  # hunk 경계에서 마감 — 서로 다른 hunk의 선언이 잘못 이어붙지 않게
            old_lines.clear()
            new_lines.clear()
            continue
        if not ln or ln[:3] in ("+++", "---") or ln.startswith("Index:") or ln.startswith("==="):
            continue
        c = ln[0]
        if c == "+":
            new_lines.append(ln[1:])
        elif c == "-":
            old_lines.append(ln[1:])
        else:  # context(공백 접두) 또는 접두 없는 라인 → 양 투영 공통
            old_lines.append(ln[1:] if c == " " else ln)
            new_lines.append(ln[1:] if c == " " else ln)
    _flush()
    return out


def _classify_one_file_diff(
    diff_text: str, is_header: bool, known_funcs: Optional[Set[str]] = None
) -> Tuple[Dict[str, str], bool]:
    """단일 파일의 unified diff → ({func: kind}, narrowable).

    함수단위 kind는 기존 로직과 동일(NEW/DELETE/SIGNATURE/BODY/VARIABLE/HEADER). 두 번째 반환값
    narrowable=True 는 이 파일을 함수단위로 좁혀도(=라인변경 없는 함수 제거) **안전이 증명된** 경우만.
    allowlist: .c 이고, 변경 hunk가 하나 이상이며, 모든 @@ hunk가 함수 컨텍스트로 귀속되고
    (bare hunk 0), 전처리 지시자 변경이 없고, 컬럼0(함수 밖) 변경이 없을 때만 True. 미인식 top-level
    구성(배열·값테이블·typedef·enum·전역var·조건부컴파일 등)은 위 조건에서 걸려 False → fatten 유지.
    """
    hunk_funcs = set(_hunk_func_names(diff_text))  # 타입/키워드 오귀속 제외
    # 제어 키워드(if/for/while...)는 '(' 앞에 와도 함수 선언이 아님 — 오탐 제외.
    _CTRL_KW = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case"}
    added_decl = {m.group(1) for m in re.finditer(r"^\+\s*.*?\b(\w+)\s*\(", diff_text, re.MULTILINE) if m.group(1) not in _CTRL_KW}
    removed_decl = {m.group(1) for m in re.finditer(r"^-\s*.*?\b(\w+)\s*\(", diff_text, re.MULTILINE) if m.group(1) not in _CTRL_KW}
    func_decl_names = {m.group(1) for m in _FUNC_DECL_LINE.finditer(diff_text)}
    func_proto_names = {m.group(1) for m in _FUNC_PROTO_LINE.finditer(diff_text)}
    var_changed = bool(_VAR_DECL_LINE.search(diff_text))
    # 연속행(context-anchored) 시그니처 변경 — OLD/NEW 투영에서 복원한 선언이 실제로 다른 함수.
    # 첫 줄이 context(무변경)라 아래 +/- 앵커 기반 분류가 놓치는 case(deep-review 발견1)를 승격용으로
    # 미리 계산한다(before==after·churn은 방출 안 해 무영향 — 안전측).
    _ctx_sig_changes = _sig_changes_from_projections(diff_text)

    # 동일 선언이 -/+ 양쪽(프로토타입 재정렬·이동, 신규 함수 삽입으로 선언 블록 밀림 등)에 나타나면
    # 함수명은 added_decl·removed_decl에 다 잡히지만 실제 시그니처 변화는 없다. 선언 원문을 비교해
    # '진짜 다를 때'만 SIGNATURE로 판정한다(같으면 본문 변경).
    # C1 fix: 함수별로 '모든' -선언/+선언 원문을 집합으로 모은다. extract_signature_changes는 함수당
    #   '첫 매치'만 담아, 같은 파일에 forward-decl(재정렬·무변화)과 definition(실변경)이 공존하면
    #   먼저 나온 forward-decl로 고정돼 진짜 시그니처 변경을 은폐한다(under-report). 전체 집합이
    #   완전히 같을 때만 'same'(순수 재정렬)으로 본다 — 하나라도 다르면 changed(SIGNATURE 유지).
    # 멀티라인 fix: _reconstruct_diff_decls가 파라미터 줄바꿈 선언을 온전히 복원하므로, 과거처럼
    #   멀티라인을 통째 스킵해 verdict='unknown'(보수적 SIGNATURE)에 갇히지 않는다 — -/+ 복원 선언이
    #   동일하면 same(BODY), 다르면 changed(SIGNATURE)로 정확 판정(false SIGNATURE '원문 미확보' 차단).
    _removed_decls: Dict[str, set] = {}
    _added_decls: Dict[str, set] = {}
    for _pol, _fn, _decl in _reconstruct_diff_decls(diff_text):
        # 복원 후에도 괄호 불균형(훅 경계로 절단된 멀티라인 등)이면 미확보 → 스킵(보수적 SIGNATURE).
        if not _decl or _decl.count("(") > _decl.count(")"):
            continue
        (_added_decls if _pol == "+" else _removed_decls).setdefault(_fn, set()).add(_decl)

    def _sig_verdict(fn: str) -> str:
        """선언 원문 비교: 'changed'(다름)/'same'(동일)/'unknown'(원문 미확보).

        함수의 -선언 집합과 +선언 집합을 비교 — 완전히 같으면 same(순수 재정렬), 하나라도 다르면
        changed(진짜 변경 은폐 방지). 한쪽이라도 비면 unknown(복원 실패·훅 절단 등 → 보수적
        SIGNATURE 유지). 멀티라인 선언은 _reconstruct_diff_decls가 복원하므로 unknown 대상이 아니다.
        """
        _b = _removed_decls.get(fn) or set()
        _a = _added_decls.get(fn) or set()
        if not _b or not _a:
            return "unknown"
        return "same" if _a == _b else "changed"

    result: Dict[str, str] = {}
    candidates = hunk_funcs | func_decl_names | (func_proto_names if is_header else set())
    for func in sorted(candidates):
        if is_header:
            new_kind = "HEADER"
        elif func in added_decl and func in removed_decl and func in func_decl_names:
            # 선언이 -/+ 양쪽에 존재 — 원문이 '동일(same)'이면 재정렬/이동(시그니처 변화 없음)이므로
            # 본문 변경으로 본다. '다름(changed)' 또는 '미확보(unknown, 멀티라인 등)'는 보수적으로
            # SIGNATURE 유지 — 원문을 못 뽑았을 때 실제 시그니처 변경을 놓치지 않도록(under-report 방지).
            # W1 fix: same은 무조건 BODY로 강등 — var_changed(파일 전체 플래그)로 VARIABLE 오분류 금지.
            new_kind = "BODY" if _sig_verdict(func) == "same" else "SIGNATURE"
        elif func in added_decl and func in func_decl_names:
            new_kind = "NEW"
        elif func in removed_decl and func in func_decl_names:
            new_kind = "DELETE"
        elif var_changed:
            new_kind = "VARIABLE"
        else:
            new_kind = "BODY"
        result[func] = new_kind

    # allowlist — 모든 hunk가 함수로 귀속(bare 0) AND 전처리 변경 없음 AND 컬럼0 변경 없음.
    # ctx_hunks는 **유효** 함수귀속만 센다(_hunk_func_names): 타입/키워드 오귀속(`u8 (*pf)(`,
    # `if (`)을 귀속으로 인정하면 "모든 hunk가 함수에 귀속됨"이 거짓 성립해 narrow가 부당 허용됨.
    _ctx_names = _hunk_func_names(diff_text)
    total_hunks = len(_HUNK_ANY.findall(diff_text))
    ctx_hunks = len(_ctx_names)
    # known_funcs(소스 인덱스)가 주어지면 귀속 이름이 **실제 함수**인지 검증한다. AUTOSAR 매크로
    # (`FUNC(void, CODE) Foo(void)` → 'FUNC', `P2FUNC(...)(...)` → 'P2FUNC')처럼 정규식이 매크로를
    # 함수로 오귀속하면, 그 파일이 narrowable로 판정돼 **실제 함수가 전부 제거**될 수 있다(under-report).
    # 미지의 이름이 하나라도 있으면 narrow 불가(파일단위 fatten 유지 — 안전측).
    _names_known = True
    if known_funcs is not None:
        _names_known = all(n.lower() in known_funcs for n in _ctx_names)
    narrowable = (
        (not is_header)
        and total_hunks > 0
        and ctx_hunks == total_hunks
        and _names_known
        and not _PREPROC_CHANGE.search(diff_text)
        and not _TOPLEVEL_CHANGE.search(diff_text)
        and not _HUNK_INIT_CTX.search(diff_text)
        and bool(result)
    )
    # @@ 헤더 과다귀속 정정: svn -x -p의 @@ 헤더는 hunk 시작의 '이전/바깥 함수'(주석 블록·프로토타입
    # 선언 블록·이웃 함수 경계)를 라벨할 수 있어, 본문이 실제로 안 바뀐 함수를 changed로 넣는다.
    # extract_function_diffs와 동일한 본문 +/- 재귀속 귀속(_attribute_hunk_changes)으로 '실제 +/-
    # 변경이 있는 함수'만 남겨 허위 evidence='line'(원문 절단)을 제거한다. fatten 파일에선 orchestrator가
    # file_fatten(파일영향)으로 강등(impact 유지, 안전).
    # ⚠ narrowable(순수 함수-본문 편집) 파일엔 적용하지 않는다(deep-review S3): 함수 본문에 들여쓴
    #   선언성 라인(nested extern/forward-decl)이 있으면 _attribute_hunk_changes가 그 선언으로 재귀속해
    #   감싸는 실함수를 컨텍스트-only로 만들어 오제거 → orchestrator가 line-classified 파일에선 완전
    #   제거(under-report). 과다귀속은 전부 fatten(실함수 정의=컬럼0 → _TOPLEVEL_CHANGE) 파일에서만
    #   발생하므로 narrowable엔 이득도 없다(orchestrator가 line-evidence로 이미 정밀 narrow).
    # ⚠ 소문자 정규화 필수(result 키=원형, _evidenced 키=소문자). is_header proto(함수포인터-반환
    #   `void (*Get(id))(void);`)는 _FUNC_DECL_LINE 미매치라 func_proto_names(+/- 리터럴=실변경)로 보강.
    if not narrowable:
        _ev, _ = _attribute_hunk_changes(diff_text)
        _evidenced = set(_ev)
        if is_header:
            _evidenced |= {_p.lower() for _p in func_proto_names}
        result = {_f: _k for _f, _k in result.items() if _f.lower() in _evidenced}
    # 연속행 시그니처 변경 승격 (deep-review 발견1) — **필터 후** 적용해 누락 방지. 멀티라인 선언의
    # 첫 줄이 context(무변경)이고 파라미터 연속행만 -/+로 바뀌면 위 분기가 func_decl_names 공백으로
    # VARIABLE/BODY로 under-report(SDS FLAG 누락)한다. OLD/NEW 투영 복원 선언이 실제로 다르면
    # SIGNATURE로 승격(안전측 upgrade — NEW/DELETE/HEADER는 보존, 미탐 함수면 추가). before/after는
    # extract_signature_changes가 동일 투영으로 채운다. _ctx_sig_changes는 old!=new만 담아 churn 무영향.
    for _cfn in _ctx_sig_changes:
        if result.get(_cfn) in (None, "BODY", "VARIABLE"):
            result[_cfn] = "SIGNATURE"
    return result, narrowable


def classify_changed_functions(
    project_root: str,
    changed_files: List[str],
    *,
    scm_type: str = "git",
    base_ref: str = "HEAD~1",
    edit_types: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Classify changed functions conservatively from unified diff text.

    edit_types(Jenkins changeSet의 파일별 add/edit/delete)가 주어지면 git/svn diff를
    생략하고 editType 기반 파일 단위 분류로 직행한다(원격/cloudium에서 로컬 working-copy
    부재 대응). 상세는 _classify_from_edit_types 참조.
    """
    if edit_types:
        return _classify_from_edit_types(changed_files, edit_types)

    classifications: Dict[str, str] = {}
    for fpath in changed_files:
        try:
            diff_text = _run_unified_diff(
                project_root,
                base_ref=base_ref,
                scm_type=scm_type,
                file_path=fpath,
            )
            if not diff_text:
                continue
            per_file, _narrowable = _classify_one_file_diff(diff_text, fpath.endswith(".h"))
            for func, new_kind in per_file.items():
                # 같은 함수가 여러 파일 diff에 나오면 강한 kind(NEW/DELETE/SIGNATURE/HEADER) 보존.
                if classifications.get(func) in {"NEW", "DELETE", "SIGNATURE", "HEADER"}:
                    continue
                classifications[func] = new_kind
        except Exception as e:
            logger.warning("Failed to classify diff for %s: %s", fpath, e)

    return classifications


def _split_svn_diff_by_file(combined_diff: str) -> List[Tuple[str, str]]:
    """svn diff 통합 출력을 'Index: <path>' 기준으로 [(path, block), ...]로 분할한다."""
    out: List[Tuple[str, str]] = []
    cur_path = ""
    cur_lines: List[str] = []
    for line in (combined_diff or "").splitlines(keepends=True):
        m = re.match(r"^Index:\s+(.+?)\s*$", line)
        if m:
            if cur_path:
                out.append((cur_path, "".join(cur_lines)))
            cur_path = m.group(1).strip()
            cur_lines = [line]
        else:
            cur_lines.append(line)
    if cur_path:
        out.append((cur_path, "".join(cur_lines)))
    return out


def _attribute_hunk_changes(block: str) -> Tuple[Dict[str, List[str]], int]:
    """단일 파일 diff 블록 → ({함수(소문자): [실변경 세그먼트, ...]}, 선언-재귀속 수).

    귀속 두 경로(= 분류기 candidates와 동일): ① hunk 헤더 컨텍스트 `@@ ... @@ <func>`
    (`_hunk_func_name`), ② hunk 본문의 `+/-` 함수 정의 라인(`_FUNC_DECL_LINE`)으로 재귀속.
    실변경(+/-, `+++`/`---` 제외) 라인이 하나라도 있는 세그먼트만 방출한다(컨텍스트-only 조각 제외
    = 미혼입). **`extract_function_diffs`(원문 텍스트)와 `_classify_one_file_diff`(실제 변경 함수
    판정)의 단일 귀속 소스** — 두 파서가 정의상 정합(원문 절단·@@ 헤더 과다귀속 동시 해소). 반환
    키는 소문자. 캡(절단) 이전이라 소비자가 필요 시 캡을 얹는다.
    """
    per: Dict[str, List[str]] = {}
    reattr = 0
    cur_func: Optional[str] = None
    seg: List[str] = []

    def _emit(func: Optional[str], s: List[str]) -> None:
        # 실변경(+/-) 라인이 하나라도 있어야 방출 — 컨텍스트/빈 조각이 이전 cur_func로 새는 것을 차단.
        # ⚠ `x[:1] in "+-"`는 x=""일 때 ""가 "+-"의 부분문자열이라 True 오판정 → startswith 튜플.
        if func and any(x.startswith(("+", "-")) and x[:3] not in ("+++", "---") for x in s):
            per.setdefault(func.lower(), []).append("\n".join(s))

    for ln in block.splitlines():
        if ln.startswith("@@ "):
            _emit(cur_func, seg)
            cur_func = _hunk_func_name(ln)  # 헤더 시드(타입/키워드 오귀속은 None)
            seg = [ln]
            continue
        # 본문 +/- 함수 정의 라인 → 재귀속(분류기 func_decl_names 미러). 컨텍스트 라인은 ^[+-] 앵커로
        # 미매치, 함수 호출(1-토큰)·대입은 `<type> <name>(` 2-토큰 구조로 자연 배제.
        _m = _FUNC_DECL_LINE.match(ln)
        _newfn = _m.group(1) if _m else None
        if (
            _newfn
            and _newfn not in _NON_FUNC_TOKENS
            and not _TYPE_ALIAS.match(_newfn)
            and _newfn.lower() != (cur_func or "").lower()
        ):
            _emit(cur_func, seg)  # 이전 함수 세그먼트 마감(실변경 있으면)
            cur_func = _newfn
            seg = [ln]
            reattr += 1
        else:
            seg.append(ln)
    _emit(cur_func, seg)  # 블록 끝 — 마지막 세그먼트 flush
    return per, reattr


def extract_function_diffs(
    combined_diff: str,
    *,
    max_lines_per_func: int = 60,
    max_total_chars: int = 400_000,
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """svn diff에서 함수별 본문 변경 hunk를 추출한다 — AI 설명용 원문 제공(BODY 함수도 실제 코드 근거).

    귀속은 **분류기 `_classify_one_file_diff`와 동일한 두 경로**를 쓴다(정렬 — "원문 절단" 근본 해소):
      ① hunk 헤더 컨텍스트 `@@ ... @@ <func>`(`_hunk_func_name`). near-top 변경 시 svn -p가 이전
         함수를 라벨하거나 bare hunk면 여기서 못 잡는다.
      ② hunk 본문의 `+/-` 함수 정의 라인(`_FUNC_DECL_LINE`, 분류기 `func_decl_names`와 동일 규칙)으로
         **재귀속**. NEW/DELETE(추가/삭제 선언)와 이동·재포맷된 시그니처(BODY로 강등)를 회복한다.
    과거엔 ①만 써서, 분류기가 ②로 잡아 evidence='line'을 부여한 함수가 원문 없이 "원문 절단"으로
    표시됐다(라이브 kjpds02_pv: line 261 vs 원문 117). 컨텍스트(공백 접두) 라인은 `_FUNC_DECL_LINE`의
    `^[+-]` 앵커로 자연 제외돼 오귀속이 없다. 세그먼트는 실변경(+/-, `+++`/`---` 제외) 라인이 하나라도
    있을 때만 방출한다(컨텍스트-only 조각이 이전 함수로 새는 것 방지 — 미혼입). 한 함수의 여러 hunk는
    이어붙이고, 함수당 max_lines_per_func 줄로 절단(AI 프롬프트 크기 관리), 전체 max_total_chars를
    넘으면 이후 함수는 저장하지 않는다(응답 폭주 방지). 반환 키는 소문자(change_details·프론트 조인 규약).
    """
    # 파일 블록별로 공유 헬퍼(_attribute_hunk_changes)로 실변경 세그먼트를 귀속·병합한다.
    # (분류기 _classify_one_file_diff와 동일 귀속 소스 → 정합 보장.)
    per_func: Dict[str, List[str]] = {}
    _decl_reattr = 0  # 본문 선언 라인 재귀속 수(관찰성 — @@ 헤더만으론 못 잡던 회복분)
    for _path, block in _split_svn_diff_by_file(combined_diff):
        _block_per, _block_reattr = _attribute_hunk_changes(block)
        for _fn, _segs in _block_per.items():
            per_func.setdefault(_fn, []).extend(_segs)
        _decl_reattr += _block_reattr

    out: Dict[str, str] = {}
    total = 0
    omitted = 0
    for func, hunks in per_func.items():
        text = "\n".join(hunks)
        lines = text.splitlines()
        if len(lines) > max_lines_per_func:
            text = "\n".join(lines[:max_lines_per_func]) + f"\n… (+{len(lines) - max_lines_per_func}줄 생략)"
        if total + len(text) > max_total_chars:
            # 전체 상한 초과 — 이후 함수는 저장하지 않는다. 과거엔 break로 **조용히** 잘려서
            # 프론트가 "본문 diff 없음 = 직접 변경 증거 없음(파일영향)"으로 오판해 실제 변경 함수가
            # 기본 집계에서 숨겨질 수 있었다. 누락 개수를 집계해 호출측이 표면화하게 한다.
            omitted += 1
            continue
        out[func] = text
        total += len(text)
    if stats is not None:
        stats["truncated"] = omitted > 0
        stats["omitted"] = omitted
        stats["total_chars"] = total
        stats["attributed_via_decl"] = _decl_reattr
    return out


def is_noop_function_diff(diff_text: str) -> bool:
    """함수 본문 diff가 코드 이동/공백/포맷만(의미·로직 변경 없음)인지 판정.

    `-`/`+` 본문 라인을 **순서 보존 + trim 정규화**로 비교해 완전히 같으면 True(블록 이동·재들여쓰기).
    프론트 `extractDiffElements.noSemanticChange`와 동형. **⚠ 순서 비교(멀티셋 아님)** 라 문장 재정렬
    (`a=1;b=a;`→`b=a;a=1;`)은 순서가 달라 False(실변경 유지) = 오탐 방지. truncated diff(`… (+N줄
    생략)`)는 안 보이는 부분에 실변경 가능 → 판정 보류(False, 보수적). +/- 라인이 없으면 False.
    """
    minus: List[str] = []
    plus: List[str] = []
    for raw in str(diff_text).split("\n"):
        if not raw or raw.startswith("@@ ") or raw.startswith("+++") or raw.startswith("---"):
            continue
        if "줄 생략)" in raw:
            return False
        c = raw[0]
        if c == "+":
            plus.append(raw[1:].strip())
        elif c == "-":
            minus.append(raw[1:].strip())
    return bool(minus) and minus == plus


def extract_file_diffs(
    combined_diff: str,
    *,
    max_lines_per_file: int = 150,
    max_total_chars: int = 200_000,
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """svn/로컬 diff를 파일별 블록으로 쪼개 캡한 맵을 반환한다 — 함수 자체 diff가 없는 함수
    (파일영향/원문 절단)의 모달 '파일 전체 변경 보기' 폴백용. 키는 **정규화 상대경로**(소문자·슬래시,
    파이프라인 표준 `_in_line_classified`/`_split` 규약과 동일)라 프론트가 절대경로를 경계 suffix
    매칭한다. 파일당 max_lines_per_file 줄로 절단(`… (+N줄 생략)` 마커, 프론트 파서 호환), 전체
    max_total_chars 초과 시 이후 파일 생략(응답 폭주 방지). `Index:` 헤더 없는 diff는 빈 맵.
    **순수 표시용** — 변경 분류/evidence/impact 집합과 무관.
    """
    out: Dict[str, str] = {}
    total = 0
    omitted = 0
    for _path, block in _split_svn_diff_by_file(combined_diff):
        key = _path.replace("\\", "/").lower()
        if not key or key in out:
            continue
        lines = block.splitlines()
        if len(lines) > max_lines_per_file:
            block = "\n".join(lines[:max_lines_per_file]) + f"\n… (+{len(lines) - max_lines_per_file}줄 생략)"
        if total + len(block) > max_total_chars:
            omitted += 1
            continue
        out[key] = block
        total += len(block)
    if stats is not None:
        stats["omitted"] = omitted
        stats["total_chars"] = total
    return out


def classify_changed_functions_from_diff_text(
    combined_diff: str,
    known_funcs: Optional[Set[str]] = None,
) -> Tuple[Dict[str, str], Set[str]]:
    """`svn diff -r A:B`(-x -p) 통합 diff blob → (정밀 changed_types, line_classified_files).

    통합 blob을 'Index: <path>' 기준으로 파일 분할해 각 파일을 _classify_one_file_diff로 분류.
    - changed_types: 함수단위 정밀 kind(NEW/DELETE/SIGNATURE/BODY/VARIABLE/HEADER).
    - line_classified_files: is_header=False AND file_scope_change=False AND 함수 1개+ 귀속된 .c
      경로 집합(정규화·소문자). 오케스트레이터는 이 집합의 파일만 함수단위 narrowing하고, 그 외
      (헤더/매크로·인클루드·모듈스코프 변경 .c)는 파일단위 보수 분류를 유지한다(안전측 — 라인변경
      없는 함수도 데이터/매크로 결합으로 영향받을 수 있으므로 과대추정을 남긴다).

    ⚠ svn 기본 diff는 `@@` 헤더에 함수 컨텍스트가 없어 BODY-only 함수 귀속이 불가하다. 반드시
    `-x -p`(show-c-function)로 받은 blob이어야 한다. 컨텍스트가 전무하면(구버전 svn이 -p 무시)
    호출측이 positive-context 가드로 이 함수를 우회해야 한다.
    """
    changed_types: Dict[str, str] = {}
    line_classified_files: Set[str] = set()
    for path, block in _split_svn_diff_by_file(combined_diff):
        is_header = path.lower().endswith((".h", ".hpp"))
        per_file, narrowable = _classify_one_file_diff(block, is_header, known_funcs)
        for func, new_kind in per_file.items():
            if changed_types.get(func) in {"NEW", "DELETE", "SIGNATURE", "HEADER"}:
                continue
            changed_types[func] = new_kind
        if narrowable:  # allowlist: 안전이 증명된 순수 본문편집 .c만
            line_classified_files.add(path.replace("\\", "/").lower())
    return changed_types, line_classified_files


def diff_has_function_context(diff_text: str) -> bool:
    """svn diff에 `@@ ... @@ func(` 함수 컨텍스트가 실제로 붙었는지 판정(positive-context 가드).

    svn 기본 diff는 컨텍스트가 없고 `-x -p`(show-c-function)로만 붙는다. 구버전 svn이 `-p`를
    조용히 무시하면 rc==0인데도 bare `@@`만 나오므로 rc로는 감지 불가 — 이 함수로 검증한다.
    """
    return bool(_HUNK_FUNC.search(diff_text or ""))


def _signature_change_rank(rec: Dict[str, str]) -> int:
    """시그니처 변경 표시 rec의 강도(병합 우선순위): 실제 변경(before!=after)=2 > 한쪽만
    (NEW/DELETE)=1 > 무변화(before==after)=0. 동명 함수가 여러 파일/블록에 있을 때 '실제 변경된
    파일'을 무변화 파일에 가려지지 않게 병합하는 데 쓴다(extract_signature_changes 내부 + 로컬 diff
    경로 orchestrator._collect_signature_changes 양쪽 단일 출처)."""
    _bf, _af = rec.get("before"), rec.get("after")
    if _bf and _af:
        return 2 if _bf != _af else 0
    return 1


def extract_signature_changes(diff_text: str) -> Dict[str, Dict[str, str]]:
    """unified diff에서 함수별 이전(-)/이후(+) 선언 라인 원문을 추출한다.

    반환: {func_name: {"before": "<선언 원문>", "after": "<선언 원문>"}} — 존재하는 쪽만 채움.
      - SIGNATURE 변경: before/after 둘 다(매개변수/리턴타입 이전→이후).
      - NEW: after만 / DELETE: before만.
      - BODY(선언 라인 미변경): 결과에 없음(원문 표시 불필요).
    **멀티라인 선언(파라미터 줄바꿈)도 _reconstruct_diff_decls로 복원**해 before/after를 채운다 —
    종전엔 여는 괄호까지만 잡혀('void Foo(') 미확보로 스킵됐고, 그 결과 리포맷 churn의 멀티라인
    함수가 UI '원문 미확보'로 표시됐다(s_sha256_expand_word 등). 복원 후 before==after면 호출측
    (impact_orchestrator)이 change_details에 넣지 않아 '변화 없는 시그니처'를 렌더하지 않는다.

    ⚠ cross-file 마스킹 fix: **파일 블록 단위**(Index: 분할, 분류기 _classify_one_file_diff와 동일
    스코프)로 -선언/+선언을 집합으로 모아 집합 차로 (before,after) 쌍을 만들고, 병합 시 '실제 변경된
    쌍(before!=after)'을 무변화 쌍(before==after)·한쪽만 있는 쌍보다 우선한다. 동명 static 함수가
    여러 파일에 있고 한 파일은 무변화면, 과거 whole-blob setdefault(첫 매치)는 무변화 파일이 먼저 올
    때 그 동일쌍을 집어 실제 변경 before/after를 가렸다(분류는 SIGNATURE인데 UI '원문 미확보' — 멀티라인
    fix와 별개의 두 번째 미확보 경로). whole-blob 집합 차도 '진짜 before'가 다른 파일의 무변화 선언과
    겹쳐 상쇄돼 before를 잃으므로, 파일 스코프 쌍 형성이 정확하다. UI '변경 상세' 원문 표시용이며,
    변경유형 분류(classify_changed_functions)와 독립적인 best-effort 보강 데이터다(표시가 실제 변경을
    못 잡아도 분류는 파일 스코프로 정확 — under-report 0).
    """
    out: Dict[str, Dict[str, str]] = {}
    # Index: 헤더가 없으면(로컬 per-file diff 단일 blob) 전체를 한 블록으로 처리.
    blocks = _split_svn_diff_by_file(diff_text) or [("", diff_text)]
    for _path, block in blocks:
        before_set: Dict[str, Set[str]] = {}
        after_set: Dict[str, Set[str]] = {}
        for polarity, func, decl in _reconstruct_diff_decls(block):
            # 복원해도 괄호 불균형(훅 절단 등)이면 온전한 선언이 아님 → 미표시(정직).
            if not decl or decl.count("(") > decl.count(")"):
                continue
            (after_set if polarity == "+" else before_set).setdefault(func, set()).add(decl)
        for func in set(before_set) | set(after_set):
            _b = before_set.get(func) or set()
            _a = after_set.get(func) or set()
            _removed_only = _b - _a  # 이 파일에서 실제로 제거된 고유 선언(양쪽 공통=무변화는 상쇄)
            _added_only = _a - _b    # 이 파일에서 실제로 추가된 고유 선언
            rec: Dict[str, str] = {}
            if _removed_only or _added_only:
                # 진짜 변경(제거/추가된 고유 선언)만. NEW=added_only만, DELETE=removed_only만,
                # SIGNATURE=양쪽. 다수면 결정적(sorted 첫 원소).
                if _removed_only:
                    rec["before"] = sorted(_removed_only)[0]
                if _added_only:
                    rec["after"] = sorted(_added_only)[0]
            elif _b and _a:
                # 차집합이 빔(순수 재정렬·동일 선언) → 동일 쌍 유지(orchestrator가 before==after로 스킵).
                _common = sorted(_b)[0]
                rec["before"] = _common
                rec["after"] = _common
            if not rec:
                continue
            # 병합: '실제 변경(rank 2)'을 무변화/부분보다 우선 — 동명 함수의 변경 파일이 무변화 파일에
            # 가려지지 않게 한다. 동순위는 먼저 온 파일 유지(결정적).
            _prev = out.get(func)
            if _prev is None or _signature_change_rank(rec) > _signature_change_rank(_prev):
                out[func] = rec
        # 연속행(context-anchored) 변경 병합 (발견1) — 선언 첫 줄이 context(무변경)이고 파라미터
        # 연속행만 -/+로 바뀌면 위 +/- 앵커 집합-차가 못 잡는다. OLD/NEW 투영에서 복원한 실변경
        # (before!=after, rank 2)을 채워 '원문 미확보'를 없애고 분류 승격(SIGNATURE)과 정합시킨다.
        for _pf, _pr in _sig_changes_from_projections(block).items():
            _pprev = out.get(_pf)
            if _pprev is None or _signature_change_rank(_pr) > _signature_change_rank(_pprev):
                out[_pf] = _pr
    return out


def compute_impact_set(
    changed_functions: Set[str],
    call_map: Dict[str, List[str]],
    *,
    max_depth: int = 3,
) -> Set[str]:
    """Given changed functions and a call graph, compute the full impact set.

    Traverses callers (reverse call graph) up to max_depth levels to find all
    functions that may be affected by the changes.
    """
    reverse_map: Dict[str, Set[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            reverse_map.setdefault(callee, set()).add(caller)

    impact: Set[str] = set(changed_functions)
    frontier = set(changed_functions)

    for _ in range(max_depth):
        next_frontier: Set[str] = set()
        for func in frontier:
            callers = reverse_map.get(func, set())
            for caller in callers:
                if caller not in impact:
                    impact.add(caller)
                    next_frontier.add(caller)
            callees = call_map.get(func, [])
            for callee in callees:
                if callee not in impact:
                    impact.add(callee)
                    next_frontier.add(callee)
        if not next_frontier:
            break
        frontier = next_frontier

    return impact


def filter_function_details(
    function_details: Dict[str, Dict[str, Any]],
    impact_set: Set[str],
) -> Dict[str, Dict[str, Any]]:
    """Filter function_details to only include functions in the impact set."""
    filtered = {}
    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        name = info.get("name", "")
        if name in impact_set or name.lower() in {f.lower() for f in impact_set}:
            filtered[fid] = info
    return filtered


def compute_delta_summary(
    project_root: str,
    function_details: Dict[str, Dict[str, Any]],
    call_map: Dict[str, List[str]],
    *,
    base_ref: str = "HEAD~1",
    scm_type: str = "git",
) -> Dict[str, Any]:
    """Full delta analysis: changed files -> changed functions -> impact set -> filtered details."""
    changed_files = get_changed_files(project_root, base_ref=base_ref, scm_type=scm_type)
    if not changed_files:
        return {
            "changed_files": [],
            "changed_functions": [],
            "impact_set": [],
            "filtered_count": 0,
            "total_count": len(function_details),
            "skip_ratio": 1.0,
        }

    changed_types = classify_changed_functions(
        project_root,
        changed_files,
        base_ref=base_ref,
        scm_type=scm_type,
    )
    changed_funcs = set(changed_types)
    impact = compute_impact_set(changed_funcs, call_map)
    filtered = filter_function_details(function_details, impact)

    total = len(function_details)
    skip_ratio = 1.0 - (len(filtered) / total) if total > 0 else 0.0

    logger.info(
        "Delta update: %d changed files, %d changed functions, "
        "%d impact set, %d/%d functions to regenerate (skip %.0f%%)",
        len(changed_files), len(changed_funcs), len(impact),
        len(filtered), total, skip_ratio * 100,
    )

    return {
        "changed_files": changed_files,
        "changed_functions": sorted(changed_funcs),
        "changed_function_types": dict(sorted(changed_types.items())),
        "impact_set": sorted(impact),
        "filtered_count": len(filtered),
        "total_count": total,
        "skip_ratio": skip_ratio,
        "filtered_details": filtered,
    }
