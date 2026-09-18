"""경로 봉인 — 클라이언트가 준 경로가 신뢰 루트 밖을 가리키지 못하게.

## 왜 여기로 올렸나

같은 판정이 **세 벌**로 흩어져 있었고 허용 집합이 서로 달랐다:

    local.py `_allowed_request_roots()`      [repo, 캐시]                  ← /api/local/* 20곳
    assistant_service `_trusted_base_roots()` [repo, project_root, report_dir, jenkins]
    jenkins.py                                자체 목록

그 사이로 **봉인이 아예 없는 엔드포인트**가 남아 있었다(2026-08-19 실측 6곳: 임의
`.xlsx/.docx` 읽기 3곳, 임의 경로 쓰기 3곳). 이 저장소의 1순위 재발 패턴이 "판정 복제 →
한쪽만 고쳐짐"이라, 라우터가 공통으로 쓸 봉인을 여기 단일 출처로 둔다.

⚠ **허용 집합을 넓히는 방향으로 통합하지 않았다.** 가장 좁은 것(`[repo, 캐시]`)이 기준이고,
  더 필요한 자리는 호출부에서 `extra_roots` 로 명시한다 — 자세한 이유는
  :func:`trusted_roots` 참조.
"""
from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional

_logger = logging.getLogger("devops_api")


def sanitize_relpath(p: str) -> str:
    s = (p or "").strip().replace("\\", "/")
    if not s:
        return "."
    if s.startswith("/") or _is_drive_abs(s):
        raise ValueError("absolute path not allowed")
    s = s.lstrip("/")
    parts = []
    for part in PurePosixPath(s).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal not allowed")
        parts.append(part)
    return "/".join(parts) if parts else "."


def _is_drive_abs(s: str) -> bool:
    return bool(len(s) >= 3 and s[1] == ":" and (s[2] == "/" or s[2] == "\\"))


def safe_resolve_under(base: Path, rel: str) -> Path:
    base_r = base.resolve()
    rel_s = sanitize_relpath(rel)
    out = (base_r / rel_s).resolve()
    if not out.is_relative_to(base_r):
        raise ValueError("resolved path escapes base directory")
    return out


def is_under_any(path: Path, roots: Iterable[Path]) -> bool:
    try:
        p = path.resolve()
    except Exception:
        p = Path(str(path))
    for r in roots:
        try:
            rr = Path(str(r)).resolve()
            if p.is_relative_to(rr):
                return True
        except Exception:
            continue
    return False


# ── 신뢰 루트 ────────────────────────────────────────────────────────


def _repo_root() -> Path:
    """저장소 루트 — **이 파일의 위치**에서 유도한다(`backend/services/paths.py`).

    ⚠ 예전엔 `import config` 후 `config.__file__` 의 부모를 썼다. **틀렸다.**
      `config` 는 모듈 참조라 언제든 갈아끼울 수 있고, 이 저장소의 테스트 3개가 실제로
      `sys.modules["config"] = <stub>` 을 한다(`tests/unit/test_workflow_ai.py:98` 등).
      그러면 신뢰 루트가 통째로 **stub 의 경로**로 바뀐다 — 실측:

          정상    -> D:/Project/devops/Release_claude
          stub 후 -> C:/somewhere/else

      결과는 `-n auto` 에서 같은 워커에 그 테스트가 먼저 걸린 경우 `/api/local/*` 가
      403 이 되는 **비결정 실패**였고(2026-08-21 pre-commit 이 잡았다), 더 나쁜 건
      **보안 경계가 가변 모듈 상태에 의존**한다는 점이다.

      `__file__` 은 갈아끼울 수 없고 import 도 필요 없다. `parents[2]` =
      `paths.py` -> `services` -> `backend` -> **저장소 루트**.
    """
    return Path(__file__).resolve().parents[2]


def trusted_roots() -> List[Path]:
    """요청자가 최상위로 지정할 수 있는 경로 — 저장소와 앱 캐시, 둘뿐이다.

    ⚠ **설정값으로 넓히지 않는다.** `DEFAULT_REPORT_DIR`·`DEFAULT_PROJECT_ROOT` 를 여기
      더하면, 그 설정을 바꾸는 것만으로 `/api/local/*` 20곳의 허용 범위가 조용히 넓어진다
      (`confine_request_root` 가 이 목록을 쓴다). 실측(2026-08-19)으로도 이 배포에서는
      둘 다 이미 저장소 밑이라 더할 이유가 없다.

      특정 엔드포인트가 저장소 밖(예: `JENKINS_SERVER_ROOTS`)을 정당하게 읽어야 하면
      **그 자리에서** `extra_roots` 로 명시한다 — 넓힌 사실이 호출부에 남는다.
    """
    return [_repo_root(), (Path.home() / ".devops_pro_cache").resolve()]


def confine(raw: object, *, extra_roots: Optional[Iterable[Path]] = None,
            what: str = "path") -> Path:
    """클라이언트가 준 경로를 신뢰 루트 하위로 확정한다. 벗어나면 **403**.

    ⚠ `Path(base) / raw` 는 봉인이 아니다 — `..` 도 통과하고 **절대경로는 base 를 통째로
      대체한다**. 그래서 join 이 아니라 "resolve 한 뒤 루트 안인지"로 판정한다.

    ⚠ 사유에 **경로를 되비추지 않는다**. 403 본문이 서버 내부 경로의 존재 여부를 알려
      주는 정찰 도구가 되면 안 된다(`test_local_request_root_confinement` 가 고정한 규약).
    """
    from fastapi import HTTPException

    s = str(raw or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail=f"{what} required")
    try:
        p = Path(s).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid {what}") from exc
    roots = list(trusted_roots())
    if extra_roots:
        roots += [Path(str(r)).expanduser().resolve() for r in extra_roots]
    if not is_under_any(p, roots):
        _logger.warning("경로 봉인 거부(%s): %s", what, p)
        raise HTTPException(status_code=403, detail=f"{what} not allowed")
    return p
