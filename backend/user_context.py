"""Lightweight user identification for multi-user internal deployment."""
from __future__ import annotations

import json
import contextvars
from pathlib import Path
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

current_user: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user", default="default"
)

# Allowed users list (loaded once at import)
_ALLOWED_USERS_PATH = Path(__file__).resolve().parents[1] / "config" / "allowed_users.json"
_allowed_users: set[str] | None = None


def _load_allowed_users() -> set[str] | None:
    """Load allowed users from config. Returns None if no restriction (file missing)."""
    if not _ALLOWED_USERS_PATH.exists():
        return None
    try:
        data = json.loads(_ALLOWED_USERS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > 0:
            return set(data)
        # Empty list or wildcard ["*"] → unrestricted
        return None
    except Exception:
        return None


def get_allowed_users() -> set[str] | None:
    """Return the set of allowed users, or None if unrestricted."""
    global _allowed_users
    if _allowed_users is None:
        _allowed_users = _load_allowed_users()
    return _allowed_users


def reload_allowed_users():
    """Force reload of allowed users list."""
    global _allowed_users
    _allowed_users = _load_allowed_users()


class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip auth for:
        # 1. CORS preflight (OPTIONS) — must pass without X-User for split-PC deployment
        # 2. Health check / static files
        # 3. Non-API paths (SPA, assets)
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in ("/api/health", "/favicon.svg")
            or not path.startswith("/api/")
        ):
            return await call_next(request)

        user = (request.headers.get("X-User") or "").strip()
        if not user:
            return JSONResponse(status_code=401, content={"detail": "X-User header required"})

        allowed = get_allowed_users()
        if allowed is not None and user not in allowed:
            return JSONResponse(status_code=403, content={"detail": f"User '{user}' not authorized"})

        token = current_user.set(user)
        try:
            response = await call_next(request)
            return response
        finally:
            current_user.reset(token)


def get_current_user() -> str:
    """Return the current request's user identifier."""
    return current_user.get("default")


def wrap_with_user(fn):
    """Wrap a callable so it inherits the current user context.

    Use this when launching background threads from request handlers:
        t = threading.Thread(target=wrap_with_user(_run_sync), daemon=True)
    """
    user = get_current_user()

    def wrapper(*args, **kwargs):
        token = current_user.set(user)
        try:
            return fn(*args, **kwargs)
        finally:
            current_user.reset(token)

    return wrapper
