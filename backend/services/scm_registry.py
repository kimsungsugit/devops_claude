from __future__ import annotations

import json
import os
from datetime import datetime
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
import threading as _threading  # noqa: E402

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
        # `.gitattributes` 는 `*.json text eol=lf` 다. `newline` 을 안 주면 Windows 에서
        # `\n` -> `\r\n` 으로 바뀌어, 설정을 한 번 저장하는 것만으로 파일 전체 줄끝이
        # 뒤집힌다. 같은 실수가 훅 스크립트에서 나면 bash 가 실행을 거부한다.
        newline="\n",
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


def _save_store_unlocked(store: ScmRegistryStore) -> Path:
    """락 없이 저장 — 이미 _REGISTRY_LOCK을 보유한 read-modify-write 안에서만 호출할 것.
    (threading.Lock 폴백은 re-entrant가 아니라 save_registry_store를 중첩 호출하면 데드락)"""
    _save_json(REGISTRY_PATH, store.model_dump(mode="json"))
    return REGISTRY_PATH


def save_registry_store(store: ScmRegistryStore) -> Path:
    with _REGISTRY_LOCK:
        return _save_store_unlocked(store)


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
    # ⚠ read-modify-write 전체를 락으로 감싼다. 과거엔 load가 락 밖이라 동시 실행 시 lost-update가
    #   났다(스토어 전체를 통째로 덮어쓰므로 다른 항목의 갱신이 조용히 되돌아감).
    with _REGISTRY_LOCK:
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
        _save_store_unlocked(store)
        return entry


def update_entry(entry_id: str, req: ScmUpdateRequest) -> ScmRegistryEntry:
    # ⚠ read-modify-write를 락 안에서 원자적으로. impact 실행 락이 scm별로 바뀌면서 서로 다른
    #   프로젝트가 동시에 _update_linked_doc(run당 최대 3회)을 호출할 수 있고, load가 락 밖이면
    #   한쪽이 stale 스토어로 전체를 덮어써 **방금 생성한 문서 경로가 조용히 되돌아간다**
    #   (그 다음 실행의 before/after diff까지 오염).
    with _REGISTRY_LOCK:
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
            _save_store_unlocked(store)
            return updated
    raise KeyError(entry_id)


def delete_entry(entry_id: str) -> bool:
    with _REGISTRY_LOCK:  # read-modify-write 원자성(lost-update 방지)
        store = load_registry_store()
        remaining = [entry for entry in store.registries if entry.id != entry_id]
        if len(remaining) == len(store.registries):
            return False
        store.registries = remaining
        _save_store_unlocked(store)
        return True


def replace_linked_docs(entry_id: str, linked_docs: ScmLinkedDocs) -> ScmRegistryEntry:
    return update_entry(entry_id, ScmUpdateRequest(linked_docs=linked_docs))


def patch_linked_doc_field(entry_id: str, field: str, path_text: str) -> ScmRegistryEntry | None:
    """linked_docs의 **단일 필드**만 원자적으로 갱신(read-modify-write를 락 안에서).

    ⚠ 과거 impact 오케스트레이터의 `_update_linked_doc`은 락 **밖에서** entry를 읽어 linked_docs
    전체 블롭을 만든 뒤 update_entry로 통째 덮어썼다 — 그 사이 다른 스레드/admin이 같은 entry의
    **다른 필드**(예: uds)를 바꾸면, stale 블롭이 그 변경을 조용히 되돌렸다. 여기서는 락을 잡은 채
    현재 값을 읽어 지정 필드만 바꾸므로 다른 필드의 동시 변경이 보존된다.
    """
    with _REGISTRY_LOCK:
        store = load_registry_store()
        for idx, entry in enumerate(store.registries):
            if entry.id != entry_id:
                continue
            merged = entry.linked_docs.model_dump(mode="json")
            merged[str(field)] = path_text
            payload = entry.model_dump(mode="json")
            payload["linked_docs"] = ScmLinkedDocs.model_validate(merged).model_dump(mode="json")
            payload["updated_at"] = _now_iso()
            updated = ScmRegistryEntry.model_validate(payload)
            store.registries[idx] = updated
            _save_store_unlocked(store)
            return updated
    return None


DEFAULT_SCM_PASSWORD_ENV = "DEVOPS_SCM_PASSWORD"

# Environment variable name validation:
#   - Must look like a shell env identifier ([A-Z_][A-Z0-9_]*).
#   - Reject well-known system variables whose values must not be interpreted
#     as passwords (a common footgun when copy-pasting configs).
import re as _re_env  # noqa: E402

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


def _normalize_path_key(text: str) -> str:
    """경로 비교용 정규화 — 대소문자·구분자·후행 슬래시 차이를 흡수."""
    s = str(text or "").strip().strip('"').strip("'")
    if not s:
        return ""
    try:
        return os.path.normcase(os.path.normpath(s))
    except (TypeError, ValueError):
        # normpath 는 embedded null 같은 병적 입력에만 던진다. 값을 버리지 않고
        # 손수 정규화한 결과를 돌려주므로 판정이 사라지지 않는다(침묵 아님).
        return s.replace("\\", "/").rstrip("/").lower()


def resolve_scm_id(value: str) -> str | None:
    """`project_id` 나 `source_root` 를 SCM registry entry id 로 정규화한다.

    품질 이력(`GenerationRun.scm_id`)의 프로젝트 축을 채우는 **단일 판정**이다.
    런타임 기록(`record_*`)과 과거 행 백필(`scripts/backfill_quality_scm_id.py`)이
    **둘 다 이 함수를 쓴다** — 판정을 복제하면 한쪽만 고쳐져 같은 입력이 두 값으로
    갈린다(이 저장소가 `_is_hsis_data_row`·`_ratchet_core`·`_artifact_check` 에서
    이미 네 번 겪은 실패다).

    매칭 규칙 — **정확일치만**:
      1. entry.id 와 대소문자 무시 일치      ("HDPDM01" → "hdpdm01")
      2. entry.source_root 와 경로 정규화 일치 ("D:/Project/Ados/PDS64_RD" → …)
      3. 콤마 복수 경로는 조각별로 1·2 를 시도하고, **후보가 정확히 하나일 때만** 채택

    ⚠ 부분일치·최장접두·"후보가 하나뿐이니 그거겠지" 폴백을 **하지 않는다**.
    `docGenHelpers.js::useScmFallback` 이 `items[0]` 을 무근거로 집어 다중 등록
    환경에서 오귀속을 만드는 그 패턴이고, 품질 이력에서 같은 짓을 하면 A 프로젝트의
    FAIL 이 B 프로젝트 화면에 뜬다. 근거가 없으면 **None**(=미상)이 정답이다.

    Returns:
        entry id, 또는 판정 불가 시 None.
    """
    raw = str(value or "").strip()
    if not raw:
        return None

    entries = list_registry_entries()
    if not entries:
        return None

    by_id = {str(e.id or "").strip().lower(): str(e.id) for e in entries if e.id}
    by_root: Dict[str, str] = {}
    for e in entries:
        # ⚠ registry 쪽 `source_root` **도** 콤마 복수다(실측 2026-08-07: 3항목 전부
        #   "D:/…/PDS64_RD,D:\…\PDS64_FBL" 꼴). 조회값만 조각내고 등록값을 통짜로
        #   두면 단일 경로 조회가 영원히 안 맞는다 — 정규화는 **양쪽 대칭**이어야 한다.
        #   (이 저장소가 추적성 정규화에서 한쪽만 strip 해 겪은 것과 같은 결함이다.)
        for piece in str(getattr(e, "source_root", "") or "").split(","):
            key = _normalize_path_key(piece)
            if not key:
                continue
            # 서로 **다른** entry 가 같은 경로를 쓰면 그 경로로는 프로젝트를 특정할 수
            # 없다 — 임의로 하나를 고르는 대신 키를 무효화한다(미상 처리).
            # 같은 entry 안의 중복 조각은 무효화 대상이 아니다.
            if key in by_root and by_root[key] != str(e.id):
                by_root[key] = ""
            elif key not in by_root:
                by_root[key] = str(e.id)

    def _one(token: str) -> str | None:
        t = token.strip()
        if not t:
            return None
        hit = by_id.get(t.lower())
        if hit:
            return hit
        return by_root.get(_normalize_path_key(t)) or None

    direct = _one(raw)
    if direct:
        return direct

    if "," in raw:
        found = {r for r in (_one(part) for part in raw.split(",")) if r}
        if len(found) == 1:
            return found.pop()

    return None


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
