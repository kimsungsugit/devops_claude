"""Auto-generated router: profiles"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
from pathlib import Path
from datetime import datetime

from backend.schemas import (
    SessionNamePayload,
)
from backend.helpers import _load_raw_profiles, _normalize_profile, _save_raw_profiles


router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.get("/api/profiles")
def list_profiles() -> Dict[str, Any]:
    raw = _load_raw_profiles()
    profiles = raw.get("profiles", {}) or {}
    names = sorted(list(profiles.keys()))
    return {"names": names, "last_profile": raw.get("last_profile")}


@router.get("/api/profiles/{name}")
def get_profile(name: str) -> Dict[str, Any]:
    raw = _load_raw_profiles()
    profiles = raw.get("profiles", {}) or {}
    prof = profiles.get(name)
    if not isinstance(prof, dict):
        raise HTTPException(status_code=404, detail="profile not found")
    return prof


@router.post("/api/profiles/{name}")
def save_profile(name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw = _load_raw_profiles()
    profiles = raw.get("profiles", {}) or {}
    profiles[name] = _normalize_profile(cfg)
    raw["profiles"] = profiles
    raw["last_profile"] = name
    raw["updated_at"] = datetime.now().isoformat()
    _save_raw_profiles(raw)
    return {"ok": True, "name": name}


@router.post("/api/profiles/last")
def set_last_profile(payload: SessionNamePayload) -> Dict[str, Any]:
    raw = _load_raw_profiles()
    raw["last_profile"] = payload.name
    raw["updated_at"] = datetime.now().isoformat()
    _save_raw_profiles(raw)
    return {"ok": True, "name": payload.name}


@router.delete("/api/profiles/{name}")
def delete_profile(name: str) -> Dict[str, Any]:
    raw = _load_raw_profiles()
    profiles = raw.get("profiles", {}) or {}
    if name not in profiles:
        raise HTTPException(status_code=404, detail="profile not found")
    profiles.pop(name, None)
    raw["profiles"] = profiles
    if raw.get("last_profile") == name:
        raw["last_profile"] = None
    raw["updated_at"] = datetime.now().isoformat()
    _save_raw_profiles(raw)
    return {"ok": True, "name": name}


