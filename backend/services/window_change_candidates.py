"""구간 변경 파일 후보 — 파일 귀속이 없는 규칙(RCMA류)의 유일한 코드 증거 경로.

Rule-8.6(one external definition)·Rule-5.6(typedef 유일성) 같은 **모듈 간 분석** 위반은
QAC가 특정 파일에 귀속시키지 않는다(RCR에 `path='' / file='RCMA'` pseudo 행 하나뿐). 그래서
`rule-fix-example`의 "이 파일의 diff"는 원리적으로 만들 수 없다.

그러나 위반이 실제로 줄어든 구간(실측 Rule-8.6 #122→#123: 104→99)에 **바뀐 소스 파일은
스냅샷에 실재한다**. 여기서는 그 구간의 변경 파일을 모아 "무엇이 바뀌었나"에 답한다 —
"무엇이 원인인가"에는 답하지 않는다(관측 ≠ 인과). 어느 변경이 위반 증감을 만들었는지는
QAC 데이터에 없고, 우리 파서로 재계산하려는 시도도 실패한다(실측: parse_c_project로 중복
외부정의 0건 — QAC는 104건).

성능: `baseline_diff`의 파일 열거/sha1만 재사용하고 **함수 파서는 부르지 않는다**
(실측 0.25초 vs 파서 포함 7초). on-demand 버튼 전용이라 임계경로에 없다.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.baseline_diff import _iter_src_files, _sha1

MAX_FILES = 30
ATTRIBUTION_NOTE = (
    "모듈 간 분석(RCMA) 위반은 특정 파일에 귀속되지 않습니다. 아래는 같은 빌드 구간에서 "
    "변경된 파일이며, 위반 증감의 원인이라는 판정이 아닙니다(관측 ≠ 인과). 선언·typedef "
    "변경 표시는 외부 링키지 규칙과의 관련 가능성을 나타내는 휴리스틱입니다."
)

_HEADER_EXTS = {".h", ".hpp", ".hh", ".inc"}
# 비-static 최상위 선언/정의 후보 — 외부 링키지 규칙(중복 정의·식별자 유일성)과 관련될 수
# 있는 라인. 함수 정의 라인도 포함한다(비-static 함수는 외부 링키지를 가지므로 Rule-8.6의
# 대상이다).
# ⚠ 들여쓰기 0만 최상위로 본다 — `^\s*`를 쓰면 함수 본문의 지역 변수(`    int x = 1;`)까지
#   전부 잡혀 값이 의미를 잃는다(실측에서 그 오검출을 확인하고 좁혔다). C 관례상 최상위
#   선언은 열 0에서 시작하지만 이것도 어디까지나 근사다.
# ⚠ 휴리스틱이다: 전처리·매크로·다중행 선언을 정확히 가르지 못한다. 그래서 이 값은
#   **정렬 키로만** 쓰고 후보 제외에는 절대 쓰지 않는다(0이어도 목록에 남는다).
_DECL_RE = re.compile(
    r"^(?!static\b)(?:extern\s+|const\s+|volatile\s+|unsigned\s+|signed\s+)*"
    r"[A-Za-z_][A-Za-z0-9_]*[\s*]+[A-Za-z_][A-Za-z0-9_]*\s*(?:\(|=|;|\[)"
)
_TYPEDEF_RE = re.compile(r"^typedef\b")


def _changed_lines(a_text: str, b_text: str) -> List[str]:
    """변경(±) 라인만 — 컨텍스트 0의 unified diff."""
    return [
        line[1:]
        for line in difflib.unified_diff(
            a_text.splitlines(), b_text.splitlines(), lineterm="", n=0
        )
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    ]


def collect_window_changes(
    *, from_build_root: Path, to_build_root: Path, max_files: int = MAX_FILES,
) -> Dict[str, Any]:
    """두 스냅샷 사이에 변경된 .c/.h 파일 목록(+선언 변경 휴리스틱). LLM 미사용."""
    from_src = Path(from_build_root) / "source"
    to_src = Path(to_build_root) / "source"
    if not from_src.is_dir() or not to_src.is_dir():
        return {"ok": True, "available": False, "reason": "snapshot_missing"}
    a_files = _iter_src_files(from_src)
    b_files = _iter_src_files(to_src)
    if not a_files or not b_files:
        return {"ok": True, "available": False, "reason": "snapshot_missing"}

    rows: List[Dict[str, Any]] = []
    for rel in sorted(set(a_files) | set(b_files)):
        a_path, b_path = a_files.get(rel), b_files.get(rel)
        if a_path is not None and b_path is not None and _sha1(a_path) == _sha1(b_path):
            continue
        kind = "added" if a_path is None else "deleted" if b_path is None else "modified"
        try:
            a_text = a_path.read_text(encoding="utf-8", errors="ignore") if a_path else ""
            b_text = b_path.read_text(encoding="utf-8", errors="ignore") if b_path else ""
        except OSError:
            continue
        changed = _changed_lines(a_text, b_text)
        rows.append({
            "path": rel,
            "change_kind": kind,
            "lines_added": sum(1 for line in difflib.unified_diff(
                a_text.splitlines(), b_text.splitlines(), lineterm="", n=0) if line.startswith("+") and not line.startswith("+++")),
            "lines_removed": sum(1 for line in difflib.unified_diff(
                a_text.splitlines(), b_text.splitlines(), lineterm="", n=0) if line.startswith("-") and not line.startswith("---")),
            "decl_touched": sum(1 for line in changed if _DECL_RE.match(line)),
            "typedef_touched": sum(1 for line in changed if _TYPEDEF_RE.match(line)),
            "is_header": Path(rel).suffix.lower() in _HEADER_EXTS,
        })

    if not rows:
        return {"ok": True, "available": False, "reason": "identical_snapshot"}
    # 외부 링키지 규칙과 관련 가능성이 높은 순 — 선언 변경 > 헤더 > 변경량. 어디까지나 표시
    # 순서이며 인과 판정이 아니다(위 ATTRIBUTION_NOTE).
    rows.sort(key=lambda r: (
        -r["decl_touched"], not r["is_header"],
        -((r["lines_added"] or 0) + (r["lines_removed"] or 0)), r["path"],
    ))
    totals = {
        "changed": len(rows),
        "headers": sum(1 for r in rows if r["is_header"]),
        "decl_touched_files": sum(1 for r in rows if r["decl_touched"] > 0),
        "typedef_touched_files": sum(1 for r in rows if r["typedef_touched"] > 0),
    }
    omitted = max(0, len(rows) - max_files)
    return {
        "ok": True, "available": True, "reason": None,
        "changed_files": rows[:max_files],
        "totals": totals,
        "omitted": omitted,
        "attribution": "observational",
        "note": ATTRIBUTION_NOTE,
    }


def resolve_window_metas(metas: List[Dict[str, Any]], from_build: Any, to_build: Any) -> Optional[tuple]:
    """(from_meta, to_meta) — 어느 쪽이든 캐시에 없으면 None."""
    from backend.services.build_inventory import find_build_meta

    a = find_build_meta(metas, from_build)
    b = find_build_meta(metas, to_build)
    return None if a is None or b is None else (a, b)
