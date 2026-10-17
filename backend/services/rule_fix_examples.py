"""룰 fix 예시의 증거 수집 — 두 빌드 소스 스냅샷에서 같은 파일의 실제 변경 diff 발췌.

"위반이 줄어든 규칙 × 줄어든 파일"에 대해, 그 구간(from_build→to_build)의 실제 코드
변경을 difflib unified diff로 발췌해 LLM(workflow/rule_fix_example.py)의 유일한 근거로
제공한다. 캐시 빌드의 source/ 스냅샷만 사용 — Jenkins/SVN 불필요.

정직성 규약:
- RCR 파일 경로(툴 기준 상대)와 스냅샷 상대경로는 루트가 달라 완전 일치가 불가 —
  suffix 조인 후 실패 시 basename 검색, **다중 매치는 ambiguous로 정직 실패**(오귀속 금지).
- 두 스냅샷에서 파일 내용이 동일하면 `file_unchanged_between_builds` — 위반 감소가
  이 파일 수정 때문이 아닐 수 있다는 사실을 숨기지 않는다.
- diff는 캡(헝크/문자) — 절단 시 truncated 표기.
"""
from __future__ import annotations

import difflib
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# J2 상향(4/6000→8/16000): 실측 KJPDS02_PV Rule 구간 diff가 18헝크인데 4로 절단돼 증거의
# 대부분이 잘렸다. on-demand(버튼) 전용이라 상향의 자동 비용은 0, LLM 입력 상한 내.
DIFF_MAX_HUNKS = 8
DIFF_MAX_CHARS = 16000
_SOURCE_EXCLUDE_DIRS = {".svn", ".git"}


def _norm_rel(p: str) -> str:
    s = str(p or "").replace("\\", "/").strip().lower()
    while s.startswith("./") or s.startswith("../"):
        s = s[2:] if s.startswith("./") else s[3:]
    return s.strip("/")


def snapshot_dir(build_root: Optional[Path]) -> Optional[Path]:
    """이 빌드의 소스 스냅샷 디렉토리 — 없으면 None.

    스냅샷 유무는 **여러 축의 결과를 동시에 결정한다**: 코드 발췌(LLM 지침), 자동 생성
    마커 확인, 구간 diff. 그 판정을 각자 하면 한쪽만 고쳐진다(이 저장소가 ruff/eslint
    ratchet 에서 이미 겪은 패턴) — 여기 한 곳에서만 본다.
    """
    if build_root is None:
        return None
    source = Path(build_root) / "source"
    return source if source.is_dir() else None


def build_snapshot_index(build_root: Path) -> Optional[Dict[str, List[Path]]]:
    """source/ 를 **한 번만** 걸어 ``{basename(소문자): [경로]}`` 인덱스를 만든다.

    같은 스냅샷에서 여러 파일을 해석할 때 `resolve_snapshot_file` 이 파일마다 `rglob` 을
    돌면 트리를 그만큼 다시 걷는다 — 실측 프로파일에서 마커 확인 8건이 전체 시간의 58%를
    먹었다. 인덱스를 넘기면 워크는 1회다. 스냅샷이 없으면 None(호출측이 rglob 폴백).
    """
    source = snapshot_dir(build_root)
    if source is None:
        return None
    index: Dict[str, List[Path]] = {}
    try:
        for cand in source.rglob("*"):
            if not cand.is_file():
                continue
            if any(seg in _SOURCE_EXCLUDE_DIRS for seg in cand.parts):
                continue
            index.setdefault(cand.name.lower(), []).append(cand)
    except OSError:
        return None
    return index


def resolve_snapshot_file(
    build_root: Path, rcr_path: str, *, index: Optional[Dict[str, List[Path]]] = None,
) -> Optional[Path]:
    """RCR의 파일 경로를 빌드 source/ 스냅샷의 실제 파일로 해석.

    ① 정규화 suffix 조인(세그먼트 경계) ② basename 검색. 다중 매치 → None(ambiguous).
    `index`(=`build_snapshot_index` 산출)를 주면 트리 워크 없이 후보를 뽑는다 — **판정
    로직은 그대로**라 인덱스 유무로 결과가 갈리지 않는다(복제하면 한쪽만 고쳐진다).
    """
    source = Path(build_root) / "source"
    if not source.is_dir():
        return None
    target = _norm_rel(rcr_path)
    if not target:
        return None
    basename = target.rsplit("/", 1)[-1]
    # 디렉토리 정보("APP/config.c")가 있을 때만 suffix 확정을 허용한다 — basename 단독
    # 질의("config.c")는 "/config.c" suffix가 모든 동명 파일에 걸려 첫 후보를 오확정한다
    # (APP vs BOOT 동명 파일 오귀속). basename 질의는 전체 스캔 후 유일할 때만 채택.
    has_dir = "/" in target
    matches: List[Path] = []
    suffix_matches: List[Path] = []
    # 인덱스는 이미 파일·제외디렉토리 필터를 거쳤지만, 아래 루프의 가드를 그대로 통과시켜
    # 두 경로가 같은 판정을 받게 한다(폴백 rglob 과 결과가 갈리면 안 된다).
    candidates = source.rglob(basename) if index is None else index.get(basename.lower(), [])
    try:
        for cand in candidates:
            if not cand.is_file():
                continue
            if any(seg in _SOURCE_EXCLUDE_DIRS for seg in cand.parts):
                continue
            rel = _norm_rel(str(cand.relative_to(source)))
            if rel == target:
                return cand  # 완전 일치 — 유일 확정
            if has_dir and rel.endswith("/" + target):
                # 통합 deep-review W2: 첫 suffix 매치 즉시 확정은 동일 'dir/파일' suffix가
                # 여러 루트(moduleA/APP/util.c vs moduleB/APP/util.c)에 있을 때 오귀속 —
                # 수집 후 유일할 때만 채택(모듈의 ambiguity 정직 계약과 일관).
                suffix_matches.append(cand)
                continue
            matches.append(cand)
    except OSError:
        return None
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    if suffix_matches:
        return None  # suffix 2개+ — ambiguous 정직 실패
    if len(matches) == 1:
        return matches[0]
    return None  # 0개(부재) 또는 2개+(ambiguous) — 오귀속보다 정직 실패


def capped_unified_diff(a_text: str, b_text: str, rel_path: str,
                        *, max_hunks: int = DIFF_MAX_HUNKS, max_chars: int = DIFF_MAX_CHARS) -> Dict[str, Any]:
    """unified diff를 헝크/문자 캡으로 발췌 — LLM 입력 상한(비용·환각 통제)."""
    lines = list(difflib.unified_diff(
        a_text.splitlines(), b_text.splitlines(),
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}", lineterm="",
    ))
    hunks_total = sum(1 for line in lines if line.startswith("@@"))
    out: List[str] = []
    hunks_used = 0
    size = 0
    truncated = False
    for line in lines:
        if line.startswith("@@"):
            if hunks_used >= max_hunks:
                truncated = True
                break
            hunks_used += 1
        size += len(line) + 1
        if size > max_chars:
            truncated = True
            break
        out.append(line)
    return {
        "text": "\n".join(out),
        "truncated": truncated or hunks_total > hunks_used,
        "hunks_used": hunks_used,
        "hunks_total": hunks_total,
    }


def collect_fix_evidence(
    *, from_build_root: Path, to_build_root: Path, file: str,
) -> Dict[str, Any]:
    """두 스냅샷에서 파일을 해석해 diff 증거를 만든다. 실패는 reason으로 정직 반환."""
    from_path = resolve_snapshot_file(from_build_root, file)
    to_path = resolve_snapshot_file(to_build_root, file)
    if from_path is None or to_path is None:
        source_missing = not (Path(from_build_root) / "source").is_dir() or not (Path(to_build_root) / "source").is_dir()
        if source_missing:
            return {"ok": False, "reason": "snapshot_missing"}
        # 부재/다중매치 구분: basename 검색이 2개+였는지는 resolve가 함구하므로 재검.
        basename = _norm_rel(file).rsplit("/", 1)[-1]

        def _count(root: Path) -> int:
            try:
                return sum(
                    1 for c in (Path(root) / "source").rglob(basename)
                    if c.is_file() and not any(seg in _SOURCE_EXCLUDE_DIRS for seg in c.parts)
                )
            except OSError:
                return 0

        if _count(from_build_root) > 1 or _count(to_build_root) > 1:
            return {"ok": False, "reason": "file_ambiguous_in_snapshot"}
        return {"ok": False, "reason": "file_not_in_snapshot"}
    try:
        a_text = from_path.read_text(encoding="utf-8", errors="ignore")
        b_text = to_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"ok": False, "reason": "snapshot_read_failed"}
    if a_text == b_text:
        # 위반 감소가 이 파일 수정 때문이 아닐 수 있음(빌드/설정/타 파일 영향) — 정직 실패.
        return {"ok": False, "reason": "file_unchanged_between_builds"}
    rel = _norm_rel(file)
    diff = capped_unified_diff(a_text, b_text, rel)
    diff_sha = hashlib.sha1(diff["text"].encode("utf-8")).hexdigest()
    return {"ok": True, "diff": diff, "diff_sha": diff_sha,
            "from_path": str(from_path), "to_path": str(to_path)}
