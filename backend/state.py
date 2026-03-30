# /app/backend/state.py
"""Shared in-memory state for the backend (caches, locks, progress)."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Tuple

# Jenkins progress tracking (in-memory)
jenkins_progress_lock = threading.Lock()
jenkins_progress: Dict[str, Dict[str, Any]] = {}
jenkins_progress_latest: Dict[str, str] = {}

# UDS view cache
uds_view_cache_lock = threading.Lock()
uds_view_cache: Dict[str, Dict[str, Any]] = {}

# Source sections cache
source_sections_cache_lock = threading.Lock()
source_sections_cache: Dict[str, Dict[str, Any]] = {}

# Session list cache
session_list_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
SESSION_CACHE_TTL: float = 5.0

# Running processes tracking
running_processes: Dict[str, Dict[str, Any]] = {}
