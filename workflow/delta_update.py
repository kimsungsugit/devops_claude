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


_FUNC_DECL_LINE = re.compile(
    r"^[+-]\s*(?:static\s+)?"
    r"(?:void|int|uint\d+_t|int\d+_t|U\d+|S\d+|bool|float|double|char|unsigned|signed|CONSTP2VAR|P2FUNC)"
    r"[\w\s\*]*\s+(\w+)\s*\(",
    re.MULTILINE,
)
_FUNC_PROTO_LINE = re.compile(
    r"^[+-]\s*(?:(?:extern|static|inline|volatile|const)\s+)*"
    r"(?:void|int|uint\d+_t|int\d+_t|U\d+|S\d+|bool|float|double|char|unsigned|signed|CONSTP2VAR|P2FUNC|FUNC)"
    r"[\w\s\*\(\),]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;",
    re.MULTILINE,
)
_HUNK_FUNC = re.compile(r"^@@.*@@\s*(?:.*?\s)?(\w+)\s*\(", re.MULTILINE)
_VAR_DECL_LINE = re.compile(
    r"^[+-]\s*(?:static\s+)?(?:const\s+|volatile\s+|unsigned\s+|signed\s+)*"
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


def _run_unified_diff(
    project_root: str,
    *,
    base_ref: str,
    scm_type: str,
    file_path: Optional[str] = None,
) -> str:
    root = Path(project_root)

    if scm_type == "svn":
        cmd = ["svn", "diff"]
        if str(base_ref or "").strip():
            cmd.extend(["-r", base_ref])
        cmd.extend(["--diff-cmd", "diff", "-x", "-U3"])
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
        fallback_cmd = ["svn", "diff"]
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
            for m in _HUNK_FUNC.finditer(diff_text):
                changed_funcs.add(m.group(1))
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


def _classify_one_file_diff(diff_text: str, is_header: bool) -> Tuple[Dict[str, str], bool]:
    """단일 파일의 unified diff → ({func: kind}, narrowable).

    함수단위 kind는 기존 로직과 동일(NEW/DELETE/SIGNATURE/BODY/VARIABLE/HEADER). 두 번째 반환값
    narrowable=True 는 이 파일을 함수단위로 좁혀도(=라인변경 없는 함수 제거) **안전이 증명된** 경우만.
    allowlist: .c 이고, 변경 hunk가 하나 이상이며, 모든 @@ hunk가 함수 컨텍스트로 귀속되고
    (bare hunk 0), 전처리 지시자 변경이 없고, 컬럼0(함수 밖) 변경이 없을 때만 True. 미인식 top-level
    구성(배열·값테이블·typedef·enum·전역var·조건부컴파일 등)은 위 조건에서 걸려 False → fatten 유지.
    """
    hunk_funcs = {m.group(1) for m in _HUNK_FUNC.finditer(diff_text)}
    # 제어 키워드(if/for/while...)는 '(' 앞에 와도 함수 선언이 아님 — 오탐 제외.
    _CTRL_KW = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case"}
    added_decl = {m.group(1) for m in re.finditer(r"^\+\s*.*?\b(\w+)\s*\(", diff_text, re.MULTILINE) if m.group(1) not in _CTRL_KW}
    removed_decl = {m.group(1) for m in re.finditer(r"^-\s*.*?\b(\w+)\s*\(", diff_text, re.MULTILINE) if m.group(1) not in _CTRL_KW}
    func_decl_names = {m.group(1) for m in _FUNC_DECL_LINE.finditer(diff_text)}
    func_proto_names = {m.group(1) for m in _FUNC_PROTO_LINE.finditer(diff_text)}
    var_changed = bool(_VAR_DECL_LINE.search(diff_text))

    result: Dict[str, str] = {}
    candidates = hunk_funcs | func_decl_names | (func_proto_names if is_header else set())
    for func in sorted(candidates):
        if is_header:
            new_kind = "HEADER"
        elif func in added_decl and func in removed_decl and func in func_decl_names:
            new_kind = "SIGNATURE"
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
    total_hunks = len(_HUNK_ANY.findall(diff_text))
    ctx_hunks = len(_HUNK_FUNC.findall(diff_text))
    narrowable = (
        (not is_header)
        and total_hunks > 0
        and ctx_hunks == total_hunks
        and not _PREPROC_CHANGE.search(diff_text)
        and not _TOPLEVEL_CHANGE.search(diff_text)
        and not _HUNK_INIT_CTX.search(diff_text)
        and bool(result)
    )
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


def classify_changed_functions_from_diff_text(
    combined_diff: str,
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
        per_file, narrowable = _classify_one_file_diff(block, is_header)
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


def extract_signature_changes(diff_text: str) -> Dict[str, Dict[str, str]]:
    """unified diff에서 함수별 이전(-)/이후(+) 선언 라인 원문을 추출한다.

    반환: {func_name: {"before": "<선언 원문>", "after": "<선언 원문>"}} — 존재하는 쪽만 채움.
      - SIGNATURE 변경: before/after 둘 다(매개변수/리턴타입 이전→이후).
      - NEW: after만 / DELETE: before만.
      - BODY(선언 라인 미변경): 결과에 없음(원문 표시 불필요).
    한 함수에 여러 선언 라인이 잡히면 첫 라인을 유지한다(대개 1개). 여러 줄에 걸친 선언은
    미지원(단일 라인 선언 가정 — C 코드 통상 단일 라인). UI '변경 상세' 원문 표시용이며,
    변경유형 분류(classify_changed_functions)와 독립적인 best-effort 보강 데이터다.
    """
    out: Dict[str, Dict[str, str]] = {}
    for line in diff_text.splitlines():
        if len(line) < 2 or line[0] not in "+-":
            continue
        if line[:3] in ("+++", "---"):  # diff 파일 헤더(+++ / ---) 제외
            continue
        m = _FUNC_DECL_LINE.match(line) or _FUNC_PROTO_LINE.match(line)
        if not m:
            continue
        func = m.group(1)
        decl = line[1:].strip()
        if decl.endswith("{"):  # 본문 여는 중괄호 제거 → 순수 선언부만
            decl = decl[:-1].strip()
        # 멀티라인 선언(파라미터 줄바꿈)은 여는 괄호까지만 잡혀 'void Foo('로 잘린다 →
        # before==after 은폐를 막기 위해 괄호 불균형(닫힘 부족)이면 미확보로 처리(스킵).
        if decl.count("(") > decl.count(")"):
            continue
        rec = out.setdefault(func, {})
        key = "after" if line[0] == "+" else "before"
        rec.setdefault(key, decl)
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
