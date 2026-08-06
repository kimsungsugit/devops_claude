"""Resolver 공유 헬퍼 — endpoint들이 import하여 cloudium 게이트 백업 검증.

CloudiumGateMiddleware가 PATH_KEYS 매칭 키를 자동 검사하지만, endpoint-local
방어 심층화 layer로 본 모듈을 import해 명시적으로 호출한다. health.py와
jenkins.py 등이 동일 헬퍼를 공유해 비대칭 방어 결손을 방지한다 (deep-reviewer C3).
"""
from __future__ import annotations

import atexit
import hashlib
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

# cloudium 문서를 로컬로 떨구는 프로세스 수명 temp 루트. 첫 사용 시 만들고 종료 시 지운다.
_MATERIALIZE_ROOT: Path | None = None


def _materialize_root() -> Path:
    global _MATERIALIZE_ROOT
    if _MATERIALIZE_ROOT is None or not _MATERIALIZE_ROOT.exists():
        _MATERIALIZE_ROOT = Path(tempfile.mkdtemp(prefix="devops_reqdoc_"))
        atexit.register(shutil.rmtree, _MATERIALIZE_ROOT, True)
    return _MATERIALIZE_ROOT


def materialize_via_resolver(
    path_str: str, *, allow: Callable[[Path], bool] | None = None,
) -> tuple[Path | None, str]:
    """cloudium 문서를 resolver(worker IPC)로 읽어 **로컬 파일로 떨구고** 그 경로를 준다.

    반환: ``(로컬 경로 | None, 사유)``. 성공하면 사유는 ``""``.

    ## 왜 '읽기만 resolver 로' 로는 부족한가

    호출부들은 본문만 쓰는 게 아니라 **경로를 하류로 넘긴다**(``req_doc_paths``).
    그 하류가 전부 ``Path`` 직독이다 — ``_build_req_map_from_doc_paths``(ASIL/Related),
    ``_extract_sds_partition_map``, ``_build_uds_asil_map``. 읽기만 resolver 로 바꾸면
    U: 경로가 그대로 하류로 흘러 거기서 다시 막히고, 이번엔 **조용히 스킵**된다
    (오늘은 최소한 사유와 함께 실패한다). 반쪽 수정이 지금보다 나쁜 경우다.

    ``_build_uds_asil_map`` 의 docstring 이 이미 정답을 적어 뒀다 —
    *"호출부가 cloudium U: 경로를 로컬 tmp로 변환해 넘긴 뒤에만 유효"*.

    ## ⚠ 파일명을 유지한다

    ``tmpXXXX.docx`` 로 바꾸면 안 된다. 호출부가 ``p.name`` 으로
    ``is_srs_filename``/``is_sds_filename`` 을 판정하므로 문서 종류가 통째로 오분류된다
    (그 판정의 함정은 별도로 기록돼 있다 — "swds"에는 "sds"가 없다 류).
    그래서 경로 해시로 만든 하위 디렉터리 안에 **원본 파일명 그대로** 쓴다
    (다른 폴더의 동명 파일이 서로 덮어쓰지 않게).
    """
    raw = (path_str or "").strip()
    if not raw:
        return None, ""
    name = Path(raw).name or raw

    # ⚠ 게이트는 전부 **바이트를 받기 전에** — 안 쓸 문서를 IPC 로 끌어오지 않는다.
    #   ① 파서가 아예 못 읽는 형식(단일 출처: chunker.SUPPORTED_TEXT_EXTS)
    #   ② 호출자의 추가 제약(allow) — ①보다 넓힐 수는 없고 좁히기만 한다
    if (why := parser_unreadable_reason(raw)):
        return None, why
    if allow is not None and not allow(Path(raw)):
        return None, f"{name}: 허용된 요구사항 문서 형식이 아님"

    try:
        enforce_resolver_access(raw)
    except HTTPException as exc:
        return None, f"{name}: 접근 거부 — {str(exc.detail)[:160]}"
    except Exception as exc:  # noqa: BLE001 — resolver 계열 예외가 광범위. 사유는 보존한다
        return None, f"{name}: 접근 검사 실패 ({type(exc).__name__}: {str(exc)[:120]})"

    from backend.services.file_resolver import get_resolver
    resolver = get_resolver()
    try:
        if not resolver.exists(raw):
            return None, f"{name}: 파일 없음 — 경로가 바뀌었거나 문서가 이동/개정됐을 수 있다"
    except Exception as exc:  # noqa: BLE001
        return None, f"{name}: 존재 확인 실패 ({type(exc).__name__}: {str(exc)[:120]})"

    try:
        data = resolver.read_bytes(raw)
    except Exception as exc:  # noqa: BLE001
        return None, f"{name}: 읽기 실패 ({type(exc).__name__}: {str(exc)[:120]})"
    if not data:
        return None, f"{name}: 0바이트 — worker read 가 비었거나 파일이 비어 있음"

    key = hashlib.sha1(raw.replace("\\", "/").lower().encode("utf-8")).hexdigest()[:12]
    try:
        out_dir = _materialize_root() / key
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / name
        out.write_bytes(data)
    except OSError as exc:
        return None, f"{name}: 로컬 임시 파일 생성 실패 ({type(exc).__name__}: {str(exc)[:100]})"
    return out, ""


def parser_unreadable_reason(path_str: str) -> str:
    """파서가 **아예 못 읽는** 확장자면 사유를, 읽을 수 있으면 ``""`` 를 준다.

    판정 기준은 ``chunker.SUPPORTED_TEXT_EXTS`` **단일 출처**다 — 목록을 여기 복제하면
    파서에 형식이 추가돼도 게이트가 모르고 계속 거부한다(이 저장소 단골 드리프트).

    ## 왜 '읽기 전에' 판정하나

    cloudium 에서는 본문 추출 전에 worker IPC 로 바이트를 **통째로** 끌어온다. 못 읽을
    형식을 안 거르면 수십 MB 를 받아 놓고 파서가 ``""`` 를 돌려주고, 사용자는
    **"본문 0자 — 양식/권한 확인 필요"** 라는 원인과 무관한 사유를 본다.
    (요구문서 읽기가 실체화로 바뀌면서 이 비용이 실제로 생겼다 — 그 전에는 Path 직독이
     실패해 애초에 바이트를 안 받았다.)
    """
    from workflow.rag.chunker import SUPPORTED_TEXT_EXTS

    p = Path((path_str or "").strip())
    ext = p.suffix.lower()
    if ext in SUPPORTED_TEXT_EXTS:
        return ""
    shown = ext or "(확장자 없음)"
    return (f"{p.name or path_str}: 본문 추출기가 읽을 수 없는 형식 {shown} — "
            f"지원: {', '.join(sorted(SUPPORTED_TEXT_EXTS))}")


def _needs_resolver_read() -> bool:
    """cloudium 모드면 True — local 모드에서는 직독이 정답이라 아무것도 바꾸지 않는다."""
    try:
        from backend.services.file_resolver import CloudiumFileResolver, get_resolver
        return isinstance(get_resolver(), CloudiumFileResolver)
    except Exception:  # noqa: BLE001 — silent-ok: resolver 조회 실패는 '직독 유지'가 안전측
        return False


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

    ## 2026-08-06 — 사유 보고에서 **실제 읽기**로 (인계 P3)

    예전엔 여기서 "그 자리를 고치지 않는다(정본 해법은 별건)"고 적어 두고 사유만
    돌려줬다. 이제 cloudium 모드에서는 :func:`materialize_via_resolver` 로 worker IPC
    read 후 **로컬 파일로 떨궈** 그 경로를 돌려준다. 반환 shape 이 그대로라 호출부
    7곳은 한 줄도 안 바뀐다.

    로컬 파일로 떨구는 이유는 편의가 아니다 — 호출부가 이 경로를 ``req_doc_paths`` 로
    **하류에 넘기고**, 그 하류(``_build_req_map_from_doc_paths``·
    ``_extract_sds_partition_map``·``_build_uds_asil_map``)가 전부 ``Path`` 직독이다.
    본문만 resolver 로 읽어 오면 U: 경로가 하류로 흘러 거기서 **조용히** 스킵된다.

    ⚠ **local 모드 동작은 그대로다.** 직독을 먼저 시도하고, 그게 안 될 때만
    (그리고 resolver 가 cloudium 일 때만) 실체화로 내려간다.

    ``allow`` 는 **본문을 읽기 전에** 평가되는 범위 게이트다(호출자의
    ``_is_allowed_req_doc``). 읽고 나서 검사하면 허용 밖 파일을 먼저 열게 되므로
    순서를 바꾸지 않는다.
    """
    from workflow.rag.chunker import _read_text_from_file

    raw = (path_str or "").strip()
    if not raw:
        return None, "", ""

    def _via_resolver() -> tuple[Path | None, str, str]:
        """cloudium 실체화 경로 — 실패하면 사유를 그대로 올린다."""
        local, why = materialize_via_resolver(raw, allow=allow)
        if why or local is None:
            return None, "", why
        try:
            t = _read_text_from_file(local)
        except Exception as exc:  # noqa: BLE001 — 파서 계열 예외가 광범위. 사유는 보존한다
            return local, "", f"{local.name}: 본문 추출 실패 ({type(exc).__name__}: {str(exc)[:100]})"
        if not t or not t.strip():
            return local, "", f"{local.name}: 본문 0자 — 양식/권한 확인 필요"
        return local, t.strip(), ""

    try:
        p = Path(raw).expanduser().resolve()
    except (OSError, ValueError) as exc:
        if _needs_resolver_read():
            return _via_resolver()
        return None, "", f"{raw}: 경로 해석 실패 ({type(exc).__name__})"

    # cloudium 이면 직독이 애초에 안 되는 경로다(PermissionError 든 '파일 없음'이든).
    # 실체화로 내려간다 — local 모드에서는 이 분기가 절대 안 탄다.
    try:
        if not p.exists():
            if _needs_resolver_read():
                return _via_resolver()
            return p, "", f"{p.name}: 파일 없음"
        if not p.is_file():
            return p, "", f"{p.name}: 파일이 아님(디렉터리)"
    except PermissionError:
        if _needs_resolver_read():
            return _via_resolver()
        return p, "", (
            f"{p.name}: 접근 권한 없음 — 백엔드 프로세스가 이 경로를 직접 열 수 없다. "
            "로컬로 복사한 경로를 지정하거나 cloudium 모드로 실행할 것"
        )
    except OSError as exc:
        if _needs_resolver_read():
            return _via_resolver()
        return p, "", f"{p.name}: {type(exc).__name__} — {str(exc)[:120]}"

    # ⚠ 파서 게이트는 **존재/디렉터리 판정 뒤**에 온다. 앞에 두면 디렉터리(확장자 없음)가
    #   "읽을 수 없는 형식"으로 뭉개져 '파일이 아님'이라는 갈래가 사라진다(실제로 그렇게
    #   짰다가 기존 테스트에 잡혔다 — 갈래를 가르려다 갈래를 없앤 꼴).
    #   cloudium 은 어차피 위 exists/PermissionError 에서 _via_resolver 로 빠지고,
    #   거기(materialize)에 같은 게이트가 있어 IPC 절약은 그대로다.
    if (why := parser_unreadable_reason(raw)):
        return p, "", why

    if allow is not None and not allow(p):
        return p, "", f"{p.name}: 허용된 요구사항 문서 위치가 아님"

    try:
        text = _read_text_from_file(p)
    except Exception as exc:  # noqa: BLE001 — 파서 계열 예외가 광범위. 사유는 보존한다
        return p, "", f"{p.name}: 본문 추출 실패 ({type(exc).__name__}: {str(exc)[:100]})"

    if not text or not text.strip():
        # 직독은 됐는데 본문이 0자 — cloudium 이면 '열리긴 하나 내용이 안 읽히는' 상태일 수
        # 있어(실측: _read_text_from_file 이 빈 문자열) worker 경유로 한 번 더 본다.
        if _needs_resolver_read():
            lp, lt, lw = _via_resolver()
            if lt:
                return lp, lt, ""
        return p, "", f"{p.name}: 본문 0자 — 양식/권한 확인 필요"
    return p, text.strip(), ""


def read_uploaded_requirement_doc(filename: str, data: bytes) -> tuple[str, str]:
    """업로드된 요구문서 바이트를 파싱하고 **사유를 돌려준다**. 반환 ``(본문, 사유)``.

    임시 파일 write → 파서 → **unlink** 까지 한 덩어리로 묶는다. 호출부(async 핸들러)는
    이걸 워커 스레드로 보내므로 docx 파싱이 이벤트 루프를 잡지 않는다.

    ⚠ 예전 인라인 판은 두 가지가 틀려 있었다: 파싱 실패를 ``text = ""`` 로 삼켜
    "요구 0건"으로만 보였고, ``delete=False`` 로 만든 임시 파일을 **지우지 않아**
    업로드마다 temp 가 쌓였다.
    """
    import tempfile

    from workflow.rag.chunker import _read_text_from_file

    name = Path(filename or "").name or "업로드 파일"
    suffix = Path(name).suffix.lower() or ".txt"
    tmp_p: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_p = Path(tmp.name)
        text = _read_text_from_file(tmp_p)
    except Exception as exc:  # noqa: BLE001 — 파서 계열이 광범위. 사유는 보존한다
        return "", f"{name}: 본문 추출 실패 ({type(exc).__name__}: {str(exc)[:100]})"
    finally:
        if tmp_p is not None:
            try:
                tmp_p.unlink()
            except OSError:
                pass

    if not text or not text.strip():
        return "", f"{name}: 본문 0자 — 양식/권한 확인 필요"
    return text.strip(), ""


def read_requirement_doc_via_resolver(
    path_str: str, *, allow: Callable[[Path], bool] | None = None,
) -> tuple[str, str]:
    """resolver(cloudium 이면 **worker IPC**) 경유로 요구문서 1건을 읽고 사유를 돌려준다.

    반환: ``(본문, 사유)``. 성공하면 사유는 ``""``.

    ## 위 :func:`read_requirement_doc` 과 무엇이 다른가

    이제 **읽기 능력은 같다**(2026-08-06 P3 이관 — 저쪽도 cloudium 이면 실체화한다).
    차이는 반환뿐이다: 저쪽은 ``(경로, 본문, 사유)`` 로 **경로까지** 주고, 이쪽은
    ``(본문, 사유)`` 만 준다. 하류로 경로를 넘겨야 하면 저쪽, 본문만 쓰면 이쪽이다.
    ⚠ 실제 read 는 :func:`materialize_via_resolver` **한 곳**을 공유한다 — 예전엔 여기에
    사본이 있었고, 그런 사본이 이 저장소에서 늘 "한쪽만 수정"으로 갈라졌다.

    ## 왜 신설했나

    ``/api/jenkins/uds/requirements-preview`` 의 읽기 루프가 다섯 갈래 실패를 전부
    ``text = ""`` 로 삼키고 있었다 — ①접근 거부 ②파일 없음 ③형식 불허 ④read 실패
    ⑤본문 추출 실패. 응답은 언제나 ``ok: True`` 라 호출자는 구분할 수 없고, 프론트는
    끝에서 **"SRS 경로를 확인하세요"** 라는 한 문장으로 뭉갠다. 사용자에겐
    *"문서는 있는데 없다고 나온다"* 로 보인다(실제 보고).

    바로 아래 두 블록(``compare``/``function_mapping``)은 같은 결함을 이미 고쳐
    ``errors`` 에 사유를 싣는데(그 주석이 "네 상태가 전부 같은 null 이 돼 4개월간
    묻혔다"고 적고 있다), **정작 그 위 루프는 안 고쳐졌다** — 늘 나오는 한쪽만 고침.
    """
    from workflow.rag.chunker import _read_text_from_file

    raw = (path_str or "").strip()
    if not raw:
        return "", ""
    name = Path(raw).name or raw

    local, why = materialize_via_resolver(raw, allow=allow)
    if why or local is None:
        return "", why

    try:
        text = _read_text_from_file(local)
    except Exception as exc:  # noqa: BLE001 — 파서 계열 예외가 광범위
        return "", f"{name}: 본문 추출 실패 ({type(exc).__name__}: {str(exc)[:100]})"

    if not text or not text.strip():
        return "", f"{name}: 본문 0자 — 양식/권한 확인 필요"
    return text.strip(), ""


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
