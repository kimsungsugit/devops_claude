"""DevOps Pro API -- FastAPI application entry point.

All endpoint logic lives in backend/routers/.
Shared helper functions live in backend/helpers/ package.

Deployment notes:
  Development : uvicorn backend.main:app --host 127.0.0.1 --port 9000 --reload
  Production  : uvicorn backend.main:app --host 0.0.0.0 --port 9000 --workers 1

  IMPORTANT: --workers MUST be 1.
  In-memory state (backend/state.py, file_resolver _resolver / _gate_cache,
  rate limiter _rate_store) is NOT shared across worker processes. Cloudium
  모드에서는 worker A=cloudium / worker B=local 같은 split-brain이 발생해
  read-only 보장이 깨진다. Long-running jobs도 generate-async + progress
  polling이 daemon thread로 처리되므로 단일 worker로 충분.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import os

# 49차 — .env 자동 로드 (JWT_SECRET / BOOTSTRAP_ADMIN_USER 등). uvicorn은 .env 자동 로드
# 안 함 — 사용자가 매번 env 수동 설정하지 않도록 backend startup 시 1회 로드.
try:
    from dotenv import load_dotenv as _load_dotenv  # type: ignore
    _load_dotenv(repo_root / ".env", override=False)  # 기존 환경 변수 우선
except ImportError:
    pass  # python-dotenv 미설치 시 graceful


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter — activate via LOG_FORMAT=json env var."""

    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


_api_logger = logging.getLogger("devops_api")
if not _api_logger.handlers:
    _h = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        _h.setFormatter(JSONFormatter())
    else:
        _h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    _api_logger.addHandler(_h)
    _api_logger.setLevel(logging.INFO)


def _attach_file_log() -> str:
    """콘솔 외에 **회전 파일 로그**를 붙인다. 성공하면 파일 경로, 실패하면 "".

    ## 왜 필요한가

    ``scripts/start.bat:37`` 은 uvicorn 을 리다이렉션 없이 띄운다. 그래서 로그가
    콘솔 창에만 남고, 창이 닫히거나 프로세스가 죽으면 **증거가 0** 이다.
    실제로 2026-08-04 "클라우디움 먹통" 을 진단할 때 원인(백엔드 미기동)을
    특정하는 데 네 번의 조사가 필요했던 이유가 이것이다 — 죽은 뒤에 볼 게 없었다.

    ## 계약

    - ``uvicorn.error`` 에도 붙인다. 기동 실패·미포착 예외 traceback 이 그쪽으로
      가기 때문이다(``devops_api`` 만 붙이면 정작 크래시가 파일에 안 남는다).
      ``uvicorn.access`` 는 **일부러 제외** — 요청마다 한 줄이라 회전이 너무 빨라
      정작 크래시 직전 구간이 밀려난다.
    - 콘솔 포맷과 달리 **날짜를 포함**한다. 사후 분석에서 시:분:초만으로는
      어느 날 일인지 알 수 없다.
    - 파일을 못 열면 **조용히 넘어가지 않고 사유를 보고**한다. 빈 로그를
      "문제 없음" 으로 읽는 것이 이 저장소가 반복해 겪은 fake-green 이다.
    """
    from logging.handlers import RotatingFileHandler

    log_dir = Path(os.environ.get("DEVOPS_LOG_DIR") or (repo_root / "logs"))
    try:
        max_mb = max(1, int(os.environ.get("DEVOPS_LOG_MAX_MB") or 20))
        backups = max(1, int(os.environ.get("DEVOPS_LOG_BACKUPS") or 5))
    except ValueError:
        max_mb, backups = 20, 5
        _api_logger.warning("DEVOPS_LOG_MAX_MB/BACKUPS 가 정수가 아니다 — 기본값(20MB×5) 사용")

    target = log_dir / "backend.log"
    # uvicorn --reload 는 모듈을 다시 import 한다 — 같은 파일에 핸들러가 겹치지 않게.
    for existing in list(_api_logger.handlers):
        if getattr(existing, "baseFilename", None) == str(target.resolve()):
            return str(target)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            target, maxBytes=max_mb * 1024 * 1024, backupCount=backups, encoding="utf-8",
        )
    except OSError as exc:
        # stderr 로도 낸다 — 이 시점엔 파일 로그가 없으므로 콘솔이 유일한 통로다.
        msg = (f"파일 로그를 열지 못했다({type(exc).__name__}: {exc}) — 콘솔 로그만 남는다. "
               f"경로: {target}. DEVOPS_LOG_DIR 로 다른 위치를 지정할 수 있다.")
        _api_logger.warning(msg)
        print(f"[devops_api] {msg}", file=sys.stderr)
        return ""

    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        fh.setFormatter(JSONFormatter())
    else:
        fh.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
        ))
    _api_logger.addHandler(fh)
    logging.getLogger("uvicorn.error").addHandler(fh)
    return str(target)


_LOG_FILE_PATH = _attach_file_log()

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app_instance):
    """서버 시작/종료 이벤트 (FastAPI lifespan 패턴)."""
    import socket
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except Exception:
        ip = "127.0.0.1"
    # ⚠ **인증 폴백이 켜져 있으면 기동 때마다 크게 알린다.**
    #   `DEV_MODE_X_USER_FALLBACK=1` 이면 JWT 없이 `X-User` 헤더 한 줄이 신원이 되고,
    #   그 이름이 `admin_users.json` 에 있으면 **admin 게이트 27개가 전부 통과**된다
    #   (실측 2026-08-04: `X-User: <admin>` 으로 `/api/swut/sutr/build` 등 ISO 26262
    #   evidence 생성기 게이트 통과). 이 플래그는 untracked `.env` 한 줄이라 조용히
    #   되살아날 수 있으므로, 켜진 상태를 **침묵시키지 않는다**.
    try:
        from backend.services.auth_service import is_dev_mode_x_user_fallback_enabled
        if is_dev_mode_x_user_fallback_enabled():
            _api_logger.warning(
                "⚠ DEV_MODE_X_USER_FALLBACK 이 켜져 있다 — JWT 없이 X-User 헤더만으로 "
                "신원이 결정되고, 그 이름이 admin 이면 모든 admin 게이트가 통과된다. "
                "개발 전용 플래그이므로 운영에서는 .env 에서 0 으로 둘 것."
            )
    except Exception as _fe:   # noqa: BLE001 - 경고 실패가 기동을 막지 않는다
        _api_logger.warning("인증 폴백 상태를 확인하지 못했다: %s", _fe)

    # Initialize Quality DB
    try:
        from workflow.quality.db import init_db as _init_quality_db
        _init_quality_db()
    except Exception as _qe:
        _api_logger.warning("Quality DB init skipped: %s", _qe)

    # Initialize Chat History DB
    try:
        from backend.services.chat_history_db import init_db as _init_chat_history_db
        _init_chat_history_db()
    except Exception as _che:
        _api_logger.warning("Chat History DB init skipped: %s", _che)

    # 41차 W2: 빈 admin_users.json + BOOTSTRAP_ADMIN_USERS env면 자동 등록 (lockout 회복).
    # 42차 W7: admin user 이름은 로그에 마스킹 표시 (added_masked) — 평문 누출 차단.
    try:
        from backend.services.admin_users import bootstrap_from_env
        _bootstrap_result = bootstrap_from_env()
        _safe_log = {
            "action": _bootstrap_result.get("action"),
            "added_count": _bootstrap_result.get("added_count", 0),
            "added_masked": _bootstrap_result.get("added_masked", []),
        }
        _api_logger.info("Admin bootstrap: %s", _safe_log)
    except Exception as _be:
        _api_logger.warning("Admin bootstrap 실패: %s", _be)

    # 45차 C1: 빈 users.json + BOOTSTRAP_ADMIN_USER/PASSWORD env면 첫 사용자 자동 등록.
    # 첫 로그인 시 must_change_password=True로 PW 변경 강제.
    try:
        from backend.services.admin_users import mask_user as _mask
        from backend.services.users import (
            bootstrap_admin_user_from_env as _bootstrap_user,
        )
        from backend.services.users import (
            warmup_dummy_hash as _warmup_dummy_hash,
        )
        _user_result = _bootstrap_user()
        _safe_user_log = {
            "action": _user_result.get("action"),
            "username": _mask(_user_result["username"]) if _user_result.get("username") else None,
        }
        _api_logger.info("User bootstrap: %s", _safe_user_log)
        # 46차 W32: dummy hash 미리 계산 — 첫 unknown user 로그인 latency 회피.
        _warmup_dummy_hash()
        _api_logger.info("Timing-safe dummy hash warmed up (46차 W32).")
    except Exception as _ue:
        _api_logger.warning("User bootstrap 실패: %s", _ue)

    _api_logger.info("=" * 50)
    _api_logger.info("DevOps Release Server started")
    _api_logger.info("  Local:   http://127.0.0.1:9000")
    _api_logger.info("  Network: http://%s:9000", ip)
    _api_logger.info("=" * 50)

    from backend.services.file_resolver import get_resolver
    resolver = get_resolver()
    _api_logger.info("  File mode: %s", resolver.mode)
    if resolver.mode == "cloudium":
        cfg = resolver.get_config()
        _api_logger.info("  Allowed paths: %s", cfg.get("allowed_prefixes", []))
        # D2: multi-worker 사용 시 _resolver/_gate_cache 모듈 글로벌 비공유로
        # split-brain 발생 가능 — 시작 시 명시 경고.
        try:
            workers_env = int(os.environ.get("WEB_CONCURRENCY", "1"))
        except ValueError:
            workers_env = 1
        if workers_env > 1:
            _api_logger.error(
                "  ⚠️  Cloudium 모드 + WEB_CONCURRENCY=%d (>1) 감지: "
                "worker 간 _resolver/_gate_cache 비공유로 read-only 보장이 "
                "깨질 수 있음. --workers 1 사용을 강력 권장.", workers_env,
            )

        # cloudium worker 자동 시작 (헬퍼 위임)
        from backend.services.cloudium_worker_launcher import ensure_cloudium_worker_running
        _api_logger.info("  Cloudium worker auto-start: %s", ensure_cloudium_worker_running())

        # N18: 등록된 모든 SCM의 source_root/linked_docs를 allowed_prefixes에 자동 merge
        try:
            from backend.routers.scm import merge_all_scm_paths_to_cloudium
            _api_logger.info("  SCM allowed_prefixes auto-merge: %s", merge_all_scm_paths_to_cloudium())
        except Exception as _me:
            _api_logger.warning("  SCM allowed_prefixes auto-merge 실패: %s", _me)

        # 39차: 사용자 추가 cloudium prefixes (config/cloudium_extra_prefixes.json) 자동 merge
        try:
            from backend.routers.health import _apply_extra_prefixes_to_resolver
            from backend.services.cloudium_extra_prefixes import load_extra_prefixes
            _extra = load_extra_prefixes()
            if _extra:
                _apply_extra_prefixes_to_resolver(_extra)
                _api_logger.info(
                    "  Cloudium extra prefixes auto-merge: %d entries", len(_extra),
                )
        except Exception as _xe:
            _api_logger.warning("  Cloudium extra prefixes auto-merge 실패: %s", _xe)

    yield  # 서버 실행 중
    _api_logger.info("DevOps Release Server shutting down")


app = FastAPI(title="ARIA API", version="1.0", lifespan=_lifespan)

# ── CORS (2026-08-04 좁힘, 보안 표면 감사) ───────────────────────────────────
#
# 예전엔 `allow_origins=["*"]` 였다. 그러면 **사용자가 아무 웹페이지만 방문해도** 그
# 페이지의 스크립트가 `http://localhost:9000` 으로 요청을 보내고 **응답을 읽을 수 있다**
# (drive-by). 실측 당시 `/api/local/editor/read` 로 `.env`(JWT_SECRET·
# BOOTSTRAP_ADMIN_PASSWORD 포함)가 그 경로로 나갔다. 그 endpoint 는 이번 라운드에
# 잠갔지만, `*` 자체가 심층방어를 통째로 없애므로 함께 정리한다.
#
# ⚠ **LAN 의 다른 PC 접속은 안 깨진다**(사용자 확인 사항). 프로덕션은 백엔드가
#    `frontend-v2/dist` 를 **같은 오리진에서 서빙**하므로(`:316-345`), `http://<LAN-IP>:9000`
#    으로 여는 프론트의 API 호출은 same-origin 이고 CORS 검사를 아예 타지 않는다.
#    bind 는 0.0.0.0 유지 — 이 목록은 브라우저 cross-origin 판독만 제한한다.
#
# ⚠ cross-origin 이 실제로 필요한 경우는 **vite dev 서버(5174)가 원격 백엔드를 볼 때**뿐이다.
#    그런 조합을 쓰면 `DEVOPS_CORS_EXTRA_ORIGINS` 에 콤마로 origin 을 넣는다.
#    (값을 코드에 하드코딩하지 않는 이유: 이 저장소는 배포 host 를 모른다 — 지어내지 않는다.)
_CORS_DEFAULT_ORIGINS = [
    "http://localhost:5174", "http://127.0.0.1:5174",   # vite dev
    "http://localhost:9000", "http://127.0.0.1:9000",   # 백엔드가 서빙하는 프론트
]
_CORS_EXTRA = [
    o.strip() for o in os.environ.get("DEVOPS_CORS_EXTRA_ORIGINS", "").split(",") if o.strip()
]
_CORS_ORIGINS = _CORS_DEFAULT_ORIGINS + _CORS_EXTRA
if _CORS_EXTRA:
    _api_logger.info("CORS 추가 origin: %s", _CORS_EXTRA)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # 다운로드 파일명 + 커스텀 상태 헤더를 cross-origin(dev 5174)에서도 프론트가 읽게 노출.
    expose_headers=["Content-Disposition", "X-Swit-Matched", "X-Swit-Missing", "X-SwUT-Summary"],
)

from backend.middleware import (  # noqa: E402
    CloudiumGateMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
# CloudiumGateMiddleware는 라우터 진입 직전에 path 검사 — UserContext보다 안쪽
# (즉, add 순서상 마지막에 추가하면 dispatch 가장 바깥으로 옴; 본 미들웨어는
# 사용자 식별 후 path 검사하므로 UserContext와 함께 inner layer 배치).
app.add_middleware(CloudiumGateMiddleware)

from backend.user_context import UserContextMiddleware  # noqa: E402

app.add_middleware(UserContextMiddleware)


# 표준 에러 핸들러 (error_handler.py에서 단일 관리)
from backend.error_handler import global_exception_handler, http_exception_handler  # noqa: E402

app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

# **W-N1 fix**: cloudium 정책 위반 응답을 미들웨어와 동일 shape로 통일
from backend.middleware import CloudiumBlockedException, _cloudium_blocked_response  # noqa: E402


async def _cloudium_blocked_exception_handler(request, exc: CloudiumBlockedException):
    return _cloudium_blocked_response(exc.detail)

app.add_exception_handler(CloudiumBlockedException, _cloudium_blocked_exception_handler)


# ---------------------------------------------------------------------------
# Register modular routers
# ---------------------------------------------------------------------------
from backend.routers.health import router as _health_router  # noqa: E402

app.include_router(_health_router)

# 42차 W2: health의 admin only sub-router (file-mode add/remove/list/browse-file).
from backend.routers.health import admin_router as _health_admin_router  # noqa: E402

app.include_router(_health_admin_router)

# 40차: 인증/권한 endpoint (GET /api/auth/me + /api/auth/admins)
from backend.routers.auth import router as _auth_router  # noqa: E402

app.include_router(_auth_router)

from backend.routers.chat import router as _chat_router  # noqa: E402

app.include_router(_chat_router)
from backend.routers.code import router as _code_router  # noqa: E402

app.include_router(_code_router)
from backend.routers.config import router as _config_router  # noqa: E402

app.include_router(_config_router)
from backend.routers.excel import router as _excel_router  # noqa: E402

app.include_router(_excel_router)
from backend.routers.exports import router as _exports_router  # noqa: E402

app.include_router(_exports_router)
from backend.routers.impact import router as _impact_router  # noqa: E402

app.include_router(_impact_router)
from backend.routers.profiles import router as _profiles_router  # noqa: E402

app.include_router(_profiles_router)
from backend.routers.qac import router as _qac_router  # noqa: E402

app.include_router(_qac_router)
from backend.routers.test_gen import router as _test_gen_router  # noqa: E402

app.include_router(_test_gen_router)
from backend.routers.vcast import router as _vcast_router  # noqa: E402

app.include_router(_vcast_router)
from backend.routers.jenkins import router as _jenkins_router  # noqa: E402

app.include_router(_jenkins_router)
from backend.routers.local import router as _local_router  # noqa: E402

app.include_router(_local_router)
from backend.routers.sessions import router as _sessions_router  # noqa: E402

app.include_router(_sessions_router)
from backend.routers.scm import router as _scm_router  # noqa: E402

app.include_router(_scm_router)
from backend.routers.summary_insight import router as _summary_insight_router  # noqa: E402

app.include_router(_summary_insight_router)
from backend.routers.quality import router as _quality_router  # noqa: E402

app.include_router(_quality_router)
from backend.routers.swut import router as _swut_router  # noqa: E402

app.include_router(_swut_router)
# 33차 라운드 — SwIT (Software Integration Test) Coverage Report v2.02
from backend.routers.swit import router as _swit_router  # noqa: E402

app.include_router(_swit_router)
# SwSA (Software Static Analysis Report) — QAC/PMD 로그 자동 빌드
from backend.routers.swsa import router as _swsa_router  # noqa: E402

app.include_router(_swsa_router)

# SwReport (SW Test Result Report) — 레벨별 산출물 → ES95411 통합 Summary
from backend.routers.swreport import router as _swreport_router  # noqa: E402

app.include_router(_swreport_router)

# ---------------------------------------------------------------------------
# Serve frontend-v2 production build (static files + SPA fallback)
# ---------------------------------------------------------------------------
_frontend_dist = repo_root / "frontend-v2" / "dist"
if (_frontend_dist / "index.html").exists():
    import mimetypes

    from fastapi.responses import FileResponse  # noqa: E402
    from fastapi.staticfiles import StaticFiles  # noqa: E402
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")

    # Serve entire dist as static files (proper MIME types)
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend_assets")

    # Serve favicon and other root-level static files
    @app.get("/favicon.svg")
    async def _favicon_svg():
        p = _frontend_dist / "favicon.svg"
        if p.exists():
            return FileResponse(str(p), media_type="image/svg+xml")
        raise HTTPException(status_code=404)

    # SPA catch-all: return index.html for any non-API unmatched route
    # API paths that don't match a router endpoint get a proper 404 instead of index.html
    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"API endpoint not found: /{full_path}")
        return FileResponse(str(_frontend_dist / "index.html"))

    _api_logger.info("Frontend-v2 production build served from %s", _frontend_dist)
else:
    _api_logger.warning("No frontend-v2 dist/ found at %s — run 'cd frontend-v2 && npm run build'", _frontend_dist)
