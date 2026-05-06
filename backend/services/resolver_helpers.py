"""Resolver 공유 헬퍼 — endpoint들이 import하여 cloudium 게이트 백업 검증.

CloudiumGateMiddleware가 PATH_KEYS 매칭 키를 자동 검사하지만, endpoint-local
방어 심층화 layer로 본 모듈을 import해 명시적으로 호출한다. health.py와
jenkins.py 등이 동일 헬퍼를 공유해 비대칭 방어 결손을 방지한다 (deep-reviewer C3).
"""
from __future__ import annotations

from fastapi import HTTPException


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
