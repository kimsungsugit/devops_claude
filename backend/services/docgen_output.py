"""생성 산출물의 **저장 위치** — 어디에 저장됐는지 알리고, 사용자가 고른 곳으로 옮긴다.

## 무엇을 푸는가

생성이 끝나면 파일은 캐시 루트(`~/.devops_pro_cache/...` 또는 `reports/`) 안에 떨어진다.
그 경로는 `_resolve_report_dir`(`backend/helpers/session.py:95`)가 신뢰 루트 **하위로
confine** 하므로 임의 위치로는 애초에 만들 수 없다 — 그건 결함이 아니라 경계다.

그래서 "경로를 고르고 싶다" 는 **생성 위치를 바꾸는 문제가 아니라 만들어진 파일을
원하는 곳으로 내보내는 문제**로 푼다. 생성 경계는 그대로 두고, 완료된 산출물만 복사한다.

## 왜 이 형태인가 (거절 규칙의 근거)

- **원본은 신뢰 루트 하위여야 한다.** 원본을 임의 경로로 열면 이 엔드포인트가 곧
  파일 읽기 프리미티브가 된다. 원본을 산출물로 묶어 두면 쓸 수 있는 **내용**이
  "이 앱이 방금 만든 문서" 로 제한된다.
- **목적지 폴더는 이미 있어야 한다**(`mkdir` 하지 않는다). 디렉터리 생성까지 허용하면
  임의 위치에 구조를 만들 수 있고, 오타 한 번이 엉뚱한 트리를 만든다.
- **덮어쓰기는 명시해야 한다.** 같은 이름이 있으면 기본은 거절이다. 조용한 덮어쓰기는
  되돌릴 수 없다.
- **파일명은 원본을 유지한다.** 이름까지 받으면 확장자를 바꿔 실행 파일을 떨굴 수 있다.
- **시스템 디렉터리는 거절한다.** 시작 프로그램·Windows·Program Files 는 사용자가
  문서를 저장하려는 곳이 아니고, 그리로 가는 요청은 의도가 다르다.
- **cloudium(U: 등)은 거절한다.** worker 는 **읽기 전용**이다(저장소 하드 제약).
  조용히 실패시키면 "저장됐다" 로 오독하므로 **사유를 명시**해 거절한다.

판정을 순수 함수로 떼어 둔 이유는 HTTP 없이 검사할 수 있어야 하기 때문이다 —
이 저장소의 반복 결함이 "판정 복제 후 한쪽만 수정" 이다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# 문서를 저장할 곳이 아닌 위치. 소문자 비교(Windows 경로는 대소문자 비구분).
_SYSTEM_DIR_PARTS = (
    "windows",
    "system32",
    "syswow64",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
)
# 시작 프로그램 — 여기에 파일을 떨구는 건 "저장" 이 아니다.
_STARTUP_MARKERS = ("startup", "시작프로그램")


class SaveTargetError(Exception):
    """저장 대상 거절. `code` 는 화면이 분기할 수 있는 안정 식별자다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_cloudium_path(path: str | Path) -> bool:
    """cloudium 경로인가 — worker 는 읽기 전용이라 저장 대상이 될 수 없다.

    UNC(`\\\\server\\share`)와 매핑 드라이브(`U:`)를 둘 다 본다. 드라이브 문자는
    사용자 환경마다 다를 수 있으므로 `DEVOPS_CLOUDIUM_DRIVES` 로 넓힐 수 있다.
    """
    raw = str(path or "").strip()
    if not raw:
        return False
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True
    drives = os.environ.get("DEVOPS_CLOUDIUM_DRIVES", "U")
    letters = {d.strip().rstrip(":").upper() for d in drives.split(",") if d.strip()}
    head = raw[:2]
    return len(head) == 2 and head[1] == ":" and head[0].upper() in letters


def _looks_system_dir(dest: Path) -> bool:
    parts = [p.lower() for p in dest.parts]
    if any(p in _SYSTEM_DIR_PARTS for p in parts):
        return True
    return any(m in p for p in parts for m in _STARTUP_MARKERS)


def resolve_save_target(
    src_path: str | Path,
    dest_dir: str | Path,
    *,
    allowed_src_roots: Iterable[Path],
    overwrite: bool = False,
) -> Tuple[Path, Path]:
    """`(원본, 목적지 파일)` 을 돌려주거나 `SaveTargetError` 를 던진다.

    복사는 하지 않는다 — 판정만 한다. 호출부가 복사한다.
    """
    raw_src = str(src_path or "").strip()
    raw_dest = str(dest_dir or "").strip()
    if not raw_src:
        raise SaveTargetError("src_required", "저장할 파일 경로가 없습니다.")
    if not raw_dest:
        raise SaveTargetError("dest_required", "저장할 폴더를 선택하세요.")

    try:
        src = Path(raw_src).expanduser().resolve()
    except Exception as exc:  # 경로 자체가 성립 안 하는 경우
        raise SaveTargetError("src_invalid", f"원본 경로를 해석할 수 없습니다: {exc}") from exc

    roots = [Path(str(r)).resolve() for r in allowed_src_roots]
    if not any(_under(src, r) for r in roots):
        # 원본을 산출물로 묶어 두는 것이 이 엔드포인트의 핵심 제약이다.
        raise SaveTargetError(
            "src_not_allowed",
            "이 앱이 생성한 산출물만 저장할 수 있습니다.",
        )
    if not src.exists() or not src.is_file():
        raise SaveTargetError("src_not_found", f"원본 파일이 없습니다: {src}")

    if is_cloudium_path(raw_dest):
        raise SaveTargetError(
            "dest_cloudium",
            "클라우디움(네트워크) 경로에는 저장할 수 없습니다 — 워커는 읽기 전용입니다. "
            "로컬 폴더에 저장한 뒤 옮기세요.",
        )

    try:
        dest = Path(raw_dest).expanduser().resolve()
    except Exception as exc:
        raise SaveTargetError("dest_invalid", f"저장 폴더 경로를 해석할 수 없습니다: {exc}") from exc

    if _looks_system_dir(dest):
        raise SaveTargetError("dest_system", f"시스템 폴더에는 저장할 수 없습니다: {dest}")
    if not dest.exists():
        # 만들어 주지 않는다 — 오타 한 번이 엉뚱한 트리를 만든다.
        raise SaveTargetError("dest_not_found", f"폴더가 없습니다: {dest}")
    if not dest.is_dir():
        raise SaveTargetError("dest_not_dir", f"폴더가 아닙니다: {dest}")

    out = dest / src.name  # 파일명은 원본 유지 — 확장자를 바꿔치기할 여지를 없앤다.
    if out.exists() and not overwrite:
        raise SaveTargetError("dest_exists", f"같은 이름의 파일이 이미 있습니다: {out.name}")
    if out.resolve() == src:
        raise SaveTargetError("dest_same", "원본과 같은 위치입니다.")
    return src, out


def _under(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except Exception:  # silent-ok: 비교 불가(드라이브 상이 등)는 "하위 아님" 이 맞는 답이다
        return False


def default_src_roots(repo_root: Optional[Path] = None) -> List[Path]:
    """산출물이 실제로 떨어지는 루트 — `api_open_folder` 의 허용 루트와 같은 집합.

    두 곳이 갈라지면 "폴더는 열리는데 저장은 거절" 같은 모순이 생긴다.
    """
    roots = [(Path.home() / ".devops_pro_cache")]
    if repo_root is not None:
        roots.append(Path(str(repo_root)))
    return [Path(str(r)).resolve() for r in roots]
