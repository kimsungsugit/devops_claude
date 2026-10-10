"""빌드가 **실제로 체크아웃한** SVN revision을 Jenkins 콘솔 로그에서 직독한다.

왜 콘솔 로그인가 — 실측 KJPDS02_PV build_125 (`jenkins_console.log`):

    Updating svn://192.168.110.33/ADOS/NE1AW_PORTING at revision '2026-07-24T13:00:11.266 +0900'
    At revision 1082

이 값은 **추정이 아니라 사실**이다. 대안인 `svn info -r {빌드시각}`(date-revolution)은
빌드 *시작* 시각으로 되짚는 근사라, 시작과 SCM 스텝 사이에 커밋이 들어오면 한 칸 어긋난다.
게다가 콘솔 로그는 이미 빌드 캐시에 내려받혀 있어 **네트워크가 전혀 필요 없고**, Jenkins가
꺼져 있어도, SVN에 못 붙어도 동작한다.

정직성 규약:
- 로그에 없거나(잘림 등) URL이 안 맞으면 빈 revision + 사유 — 아무 숫자나 고르지 않는다.
- 같은 URL에 서로 다른 revision이 여러 개면 **모호로 판정하고 포기**한다(하나를 찍으면
  틀린 트리를 '고정됨'으로 위장하게 된다).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONSOLE_LOG_NAME = "jenkins_console.log"

# `Updating <url> at revision '...'` / `Checking out <url> at revision ...`
# git 쪽 `Checking out Revision <sha1> (refs/...)`와 헷갈리면 안 되므로 **URL 형태**를 요구한다.
_SVN_TARGET_RE = re.compile(
    r"^\s*(?:Updating|Checking out|Exporting)\s+(?P<url>(?:svn|svn\+ssh|https?|file)://\S+)",
    re.IGNORECASE,
)
# `At revision 1082` / `Checked out revision 1082.` / `Updated to revision 1082.`
# ⚠ `Checking out Revision <sha1>`(git)은 숫자가 아니라 매치되지 않는다.
_SVN_REV_RE = re.compile(
    r"^\s*(?:At|Checked out|Updated to|Exported)\s+revision\s+(?P<rev>\d+)\s*\.?\s*$",
    re.IGNORECASE,
)


def _norm_url(url: str) -> str:
    """비교용 정규화 — 후행 슬래시·대소문자(스킴/호스트)만 흡수. 경로 대소문자는 보존."""
    u = str(url or "").strip().rstrip("/")
    if "://" not in u:
        return u.lower()
    scheme, _, rest = u.partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower()}{slash}{path}"


def _urls_match(logged: str, wanted: str) -> bool:
    """로그의 체크아웃 URL이 우리가 비교하려는 저장소인지.

    잡이 하위 경로를 체크아웃할 수 있으므로 접두 일치도 허용하되, 경로 경계에서만
    끊는다(`/ADOS/NE1`이 `/ADOS/NE1AW_PORTING`을 삼키지 않게).
    """
    a, b = _norm_url(logged), _norm_url(wanted)
    if not a or not b:
        return False
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer.startswith(shorter + "/")


def parse_console_revisions(text: str) -> List[Tuple[str, int]]:
    """콘솔 로그 → [(체크아웃 URL, revision), ...]. 대상 라인 뒤 첫 revision 라인만 짝짓는다."""
    out: List[Tuple[str, int]] = []
    pending: Optional[str] = None
    for line in text.splitlines():
        m = _SVN_TARGET_RE.match(line)
        if m:
            pending = m.group("url")
            continue
        r = _SVN_REV_RE.match(line)
        if r and pending:
            out.append((pending, int(r.group("rev"))))
            pending = None
    return out


def revision_from_console_text(text: str, *, repo_url: str) -> Dict[str, str]:
    """로그 본문에서 `repo_url`에 해당하는 revision. 실패는 사유와 함께 빈 값."""
    pairs = parse_console_revisions(text or "")
    if not pairs:
        return {"revision": "", "reason": "console_no_svn_revision"}
    matched = {rev for url, rev in pairs if _urls_match(url, repo_url)}
    if not matched:
        return {"revision": "", "reason": "console_url_mismatch"}
    if len(matched) > 1:
        # 같은 저장소에 서로 다른 revision이 찍혔다 — 어느 트리가 그 빌드인지 단정 불가.
        return {"revision": "", "reason": f"console_ambiguous:{','.join(str(r) for r in sorted(matched))}"}
    return {"revision": str(next(iter(matched))), "reason": ""}


# SCM 스텝은 파이프라인 맨 앞이라 revision 라인은 로그 선두에 있다(실측 build_125: 56번째 줄).
# 로그가 상한(JENKINS_CONSOLE_LOG_MAX_BYTES)에 걸려 잘리면 **선두가 잘려나가** 어차피 못 찾는다
# (실측 build_105/107 = 정확히 2,000,000 bytes, svn 언급 0건). 그래서 앞부분만 읽어도 손실이 없고,
# 33빌드를 훑는 호출에서 66MB를 읽지 않아도 된다.
CONSOLE_HEAD_BYTES = 512_000


def revision_from_console_log(
    build_root: Path, *, repo_url: str, head_bytes: int = CONSOLE_HEAD_BYTES,
) -> Dict[str, str]:
    """빌드 캐시의 `jenkins_console.log`에서 revision 직독(네트워크 0)."""
    path = Path(build_root) / CONSOLE_LOG_NAME
    try:
        with path.open("rb") as fh:
            raw = fh.read(head_bytes) if head_bytes and head_bytes > 0 else fh.read()
    except OSError:
        return {"revision": "", "reason": "console_log_missing"}
    return revision_from_console_text(raw.decode("utf-8", errors="ignore"), repo_url=repo_url)
