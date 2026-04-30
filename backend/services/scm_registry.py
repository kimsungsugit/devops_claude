from __future__ import annotations

import os
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from filelock import FileLock
except ImportError:
    FileLock = None
from pydantic import ValidationError

from backend.schemas import (
    ScmLinkedDocs,
    ScmRegisterRequest,
    ScmRegistryEntry,
    ScmRegistryStore,
    ScmUpdateRequest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "scm_registry.json"
import threading as _threading
_REGISTRY_LOCK = FileLock(str(REGISTRY_PATH) + ".lock", timeout=10) if FileLock else _threading.Lock()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_store() -> Dict[str, Any]:
    return {"registries": []}


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_registry_file() -> Path:
    if not REGISTRY_PATH.exists():
        _save_json(REGISTRY_PATH, _empty_store())
    return REGISTRY_PATH


def load_registry_store() -> ScmRegistryStore:
    ensure_registry_file()
    try:
        raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        backup = REGISTRY_PATH.with_suffix(".invalid.json")
        try:
            backup.write_text(REGISTRY_PATH.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        except Exception:
            pass
        _save_json(REGISTRY_PATH, _empty_store())
        return ScmRegistryStore()
    if not isinstance(raw, dict):
        raw = _empty_store()
    try:
        return ScmRegistryStore.model_validate(raw)
    except ValidationError:
        backup = REGISTRY_PATH.with_suffix(".invalid.json")
        try:
            backup.write_text(REGISTRY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
        _save_json(REGISTRY_PATH, _empty_store())
        return ScmRegistryStore()


def save_registry_store(store: ScmRegistryStore) -> Path:
    with _REGISTRY_LOCK:
        _save_json(REGISTRY_PATH, store.model_dump(mode="json"))
    return REGISTRY_PATH


def list_registry_entries() -> List[ScmRegistryEntry]:
    with _REGISTRY_LOCK:
        return load_registry_store().registries


def get_registry_entry(entry_id: str) -> ScmRegistryEntry | None:
    entry_id = str(entry_id or "").strip()
    if not entry_id:
        return None
    for entry in list_registry_entries():
        if entry.id == entry_id:
            return entry
    return None


def register_entry(req: ScmRegisterRequest) -> ScmRegistryEntry:
    store = load_registry_store()
    if any(entry.id == req.id for entry in store.registries):
        raise ValueError(f"registry id already exists: {req.id}")
    # Validate/normalize the env var name before persisting. Raising here is
    # preferable to silently resolving to `PATH` at checkout time.
    payload = req.model_dump()
    payload["scm_password_env"] = validate_scm_password_env(payload.get("scm_password_env", ""))
    now = _now_iso()
    entry = ScmRegistryEntry(
        **payload,
        created_at=now,
        updated_at=now,
    )
    store.registries.append(entry)
    save_registry_store(store)
    return entry


def update_entry(entry_id: str, req: ScmUpdateRequest) -> ScmRegistryEntry:
    store = load_registry_store()
    for idx, entry in enumerate(store.registries):
        if entry.id != entry_id:
            continue
        merged = entry.model_dump(mode="json")
        patch = req.model_dump(exclude_none=True, mode="json")
        if "scm_password_env" in patch:
            patch["scm_password_env"] = validate_scm_password_env(patch["scm_password_env"])
        if "linked_docs" in patch and isinstance(patch["linked_docs"], dict):
            linked = ScmLinkedDocs.model_validate(
                {
                    **entry.linked_docs.model_dump(mode="json"),
                    **patch["linked_docs"],
                }
            )
            patch["linked_docs"] = linked.model_dump(mode="json")
        merged.update(patch)
        merged["updated_at"] = _now_iso()
        updated = ScmRegistryEntry.model_validate(merged)
        store.registries[idx] = updated
        save_registry_store(store)
        return updated
    raise KeyError(entry_id)


def delete_entry(entry_id: str) -> bool:
    store = load_registry_store()
    remaining = [entry for entry in store.registries if entry.id != entry_id]
    if len(remaining) == len(store.registries):
        return False
    store.registries = remaining
    save_registry_store(store)
    return True


def replace_linked_docs(entry_id: str, linked_docs: ScmLinkedDocs) -> ScmRegistryEntry:
    return update_entry(entry_id, ScmUpdateRequest(linked_docs=linked_docs))


DEFAULT_SCM_PASSWORD_ENV = "DEVOPS_SCM_PASSWORD"

# Environment variable name validation:
#   - Must look like a shell env identifier ([A-Z_][A-Z0-9_]*).
#   - Reject well-known system variables whose values must not be interpreted
#     as passwords (a common footgun when copy-pasting configs).
import re as _re_env

_ENV_NAME_PATTERN = _re_env.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_ENV_NAME_BLACKLIST = frozenset(
    {
        "PATH", "HOME", "USER", "USERNAME", "LOGNAME",
        "PWD", "SHELL", "LANG", "LC_ALL", "TERM",
        "TMP", "TEMP", "TMPDIR", "APPDATA", "LOCALAPPDATA",
        "SYSTEMROOT", "WINDIR", "PROGRAMFILES", "PROGRAMDATA",
        "PYTHONPATH", "LD_LIBRARY_PATH",
    }
)


class ScmValidationError(ValueError):
    """Raised when registry data fails validation (distinct from conflict)."""


def validate_scm_password_env(name: str) -> str:
    """Return a cleaned env-var name if it is safe to use, or "" if it is not.

    This is deliberately permissive for legitimate names and strict about
    the system variables that are most likely to be chosen by accident.
    """
    clean = str(name or "").strip()
    if not clean:
        return ""
    up = clean.upper()
    if up in _ENV_NAME_BLACKLIST:
        raise ScmValidationError(
            f"scm_password_env={clean!r} is a reserved system variable; pick a project-specific name"
        )
    if not _ENV_NAME_PATTERN.match(clean):
        raise ScmValidationError(
            f"scm_password_env={clean!r} is not a valid shell identifier "
            "(expected [A-Z_][A-Z0-9_]{0,63})"
        )
    return clean


def _normalize_repo_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def find_registry_by_url(repo_url: str) -> ScmRegistryEntry | None:
    """Find a registered entry whose scm_url matches (or is a parent of) repo_url.

    Only the "registry is parent, request is child" direction is allowed. The
    reverse (registry is a deeper sub-path than the request) is rejected to
    avoid cross-matching unrelated sibling projects that happen to share the
    same SVN host.
    """
    target = _normalize_repo_url(repo_url)
    if not target:
        return None
    best: ScmRegistryEntry | None = None
    best_len = -1
    for entry in list_registry_entries():
        candidate = _normalize_repo_url(entry.scm_url)
        if not candidate:
            continue
        if candidate == target or target.startswith(candidate + "/"):
            # Prefer the longest (most specific) matching candidate so that
            # "svn://host/proj/trunk" beats "svn://host/proj" when both are
            # registered.
            if len(candidate) > best_len:
                best = entry
                best_len = len(candidate)
    return best


def resolve_scm_credentials(
    *,
    repo_url: str = "",
    scm_id: str = "",
    override_username: str = "",
) -> Tuple[str, str, ScmRegistryEntry | None]:
    """Resolve SVN/Git credentials from registry + env, without accepting plaintext over HTTP.

    Lookup order:
      1. scm_id (explicit) → registry entry.
      2. repo_url → registry entry with matching scm_url.
    Username: override_username > entry.scm_username.
    Password: env[entry.scm_password_env] > env[DEVOPS_SCM_PASSWORD].
    """
    entry: ScmRegistryEntry | None = None
    if scm_id:
        entry = get_registry_entry(scm_id)
    if entry is None and repo_url:
        entry = find_registry_by_url(repo_url)

    username = (override_username or "").strip()
    if not username and entry is not None:
        username = (entry.scm_username or "").strip()

    password = ""
    if entry is not None and entry.scm_password_env:
        password = os.environ.get(entry.scm_password_env, "") or ""
    if not password:
        password = os.environ.get(DEFAULT_SCM_PASSWORD_ENV, "") or ""

    return username, password, entry
