"""Resolver 공유 헬퍼 — endpoint들이 import하여 cloudium 게이트 백업 검증.

CloudiumGateMiddleware가 PATH_KEYS 매칭 키를 자동 검사하지만, endpoint-local
방어 심층화 layer로 본 모듈을 import해 명시적으로 호출한다. health.py와
jenkins.py 등이 동일 헬퍼를 공유해 비대칭 방어 결손을 방지한다 (deep-reviewer C3).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException


def read_requirement_doc(
    path_str: str, *, allow: Callable[[Path], bool] | None = None,
) -> tuple[Path | None, str, str]:
    """요구사항 문서 1건을 읽고 **실패 사유를 돌려준다**.

    반환: ``(해석된 경로 | None, 본문, 사유)``. 성공하면 사유는 ``""``.

    ## 왜 이게 필요한가

    UDS/STS 생성 핸들러 세 곳이 전부 이렇게 쓰고 있었다::

        try:
            p = Path(path_str).expanduser().resolve()
            if not p.exists() or not p.is_file():
                continue
            text = _read_text_from_file(p)
            ...
        except Exception:
            continue

    이러면 ①경로 오타 ②파일 없음 ③**권한 없음** ④본문 추출 0자 가 전부 같은
    "그냥 건너뜀" 이 된다. 실측(2026-08-05)으로 확인한 결과, cloudium 모드에서
    registry 의 ``U:/…`` 문서는 **백엔드 프로세스 권한으로 열리지 않는다**:

        Path("U:/…/SRS.docx").exists()   → PermissionError (0.1ms)
        _read_text_from_file(같은 경로)   → "" (빈 문자열)

    그래서 등록된 SRS/SDS 를 그대로 넘겨도 전부 조용히 탈락하고, 핸들러는 끝에서
    "SRS document is required" 라는 **원인과 무관한** 400 을 낸다. 사용자는 준
    문서를 안 줬다는 말을 듣는다.

    이 함수는 그 자리를 고치지 않는다(정본 해법은 worker IPC 경유 read 로의
    이관이고 별건이다). 대신 **무엇이 왜 탈락했는지**를 호출자가 사용자에게
    전달할 수 있게 만든다 — 이 저장소의 '미계산을 0/없음 으로 위장하지 않는다' 규약.

    ``allow`` 는 **본문을 읽기 전에** 평가되는 범위 게이트다(호출자의
    ``_is_allowed_req_doc``). 읽고 나서 검사하면 허용 밖 파일을 먼저 열게 되므로
    순서를 바꾸지 않는다.
    """
    from workflow.rag.chunker import _read_text_from_file

    raw = (path_str or "").strip()
    if not raw:
        return None, "", ""

    try:
        p = Path(raw).expanduser().resolve()
    except (OSError, ValueError) as exc:
        return None, "", f"{raw}: 경로 해석 실패 ({type(exc).__name__})"

    try:
        if not p.exists():
            return p, "", f"{p.name}: 파일 없음"
        if not p.is_file():
            return p, "", f"{p.name}: 파일이 아님(디렉터리)"
    except PermissionError:
        return p, "", (
            f"{p.name}: 접근 권한 없음 — cloudium 모드에서는 백엔드 프로세스가 "
            "U: 경로를 직접 열 수 없다(worker 경유 read 미지원 경로). "
            "로컬로 복사한 경로를 지정하거나 업로드 가능한 모드에서 실행할 것"
        )
    except OSError as exc:
        return p, "", f"{p.name}: {type(exc).__name__} — {str(exc)[:120]}"

    if allow is not None and not allow(p):
        return p, "", f"{p.name}: 허용된 요구사항 문서 위치가 아님"

    try:
        text = _read_text_from_file(p)
    except Exception as exc:  # noqa: BLE001 — 파서 계열 예외가 광범위. 사유는 보존한다
        return p, "", f"{p.name}: 본문 추출 실패 ({type(exc).__name__}: {str(exc)[:100]})"

    if not text or not text.strip():
        return p, "", f"{p.name}: 본문 0자 — 양식/권한 확인 필요"
    return p, text.strip(), ""


def enforce_resolver_access(path: str) -> None:
    """Cloudium 모드에서 게이트 + 화이트리스트 검사 — 실패 시 403.

    Layer 정책:
      1차 — CloudiumGateMiddleware가 PATH_KEYS 자동 검사 (request entry)
      2차 — 본 함수가 endpoint 진입 시 명시 검사 (방어 심층)
      3차 — resolver.read_bytes 등 read 메서드도 _gate_then_allow 호출
             (단 ContextVar로 미들웨어 통과 시 skip — W1 최적화)

    Local 모드면 no-op (cloudium 외 환경에서는 사용자 권한이 곧 OS 권한).
    """
    from backend.services.file_resolver import CloudiumFileResolver, get_resolver
    resolver = get_resolver()
    if isinstance(resolver, CloudiumFileResolver):
        try:
            resolver.check_access(path)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))


def reject_upload_in_cloudium(*files) -> None:
    """**D3 fix**: Cloudium 모드에서 사용자 파일 업로드 거부.

    Cloudium의 핵심 사용 사례는 "클라우디움 서버 경로를 직접 지정해 worker IPC로 read"이며,
    파일 업로드 경로는 backend python.exe가 자체 임시 디스크에 write하는 행위로 cloudium의
    read-only 정책 선언과 모순된다. 사용자에게 Settings에서 직접 경로 선택하도록 안내.

    LOCAL 모드면 no-op. 빈 UploadFile (filename 없음)도 통과.

    **W-N1 fix**: HTTPException 대신 `CloudiumBlockedException`을 raise해
    fastapi exception handler가 미들웨어와 동일한 응답 shape
    (`{ok, code: "CLOUDIUM_BLOCKED", detail}`)로 변환. frontend가 단일
    분기 로직으로 cloudium 정책 위반 식별 가능.
    """
    from backend.services.file_resolver import CloudiumFileResolver, get_resolver
    from backend.middleware import CloudiumBlockedException
    if not isinstance(get_resolver(), CloudiumFileResolver):
        return
    for f in files:
        if f is not None and getattr(f, "filename", None):
            raise CloudiumBlockedException(
                detail=(
                    "Cloudium 모드에서는 파일 업로드 불가. Settings에서 클라우디움 "
                    "서버 경로를 직접 선택하세요."
                )
            )
