from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List

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
    _save_json(REGISTRY_PATH, store.model_dump(mode="json"))
    return REGISTRY_PATH


def list_registry_entries() -> List[ScmRegistryEntry]:
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
    now = _now_iso()
    entry = ScmRegistryEntry(
        **req.model_dump(),
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
