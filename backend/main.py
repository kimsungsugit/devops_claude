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
import sys
import logging
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
        from backend.services.users import (
            bootstrap_admin_user_from_env as _bootstrap_user,
            warmup_dummy_hash as _warmup_dummy_hash,
        )
        from backend.services.admin_users import mask_user as _mask
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
            from backend.services.cloudium_extra_prefixes import load_extra_prefixes
            from backend.routers.health import _apply_extra_prefixes_to_resolver
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    from fastapi.staticfiles import StaticFiles  # noqa: E402
    from fastapi.responses import FileResponse  # noqa: E402

    import mimetypes
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
