# /app/backend/routers/health.py
"""Health-check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

import config

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "engine": getattr(config, "ENGINE_NAME", "DevOps Analyzer"),
        "version": getattr(config, "ENGINE_VERSION", "unknown"),
    }
