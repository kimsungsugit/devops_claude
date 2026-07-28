from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

import config

from backend.services.jenkins_client import JenkinsClient, JenkinsServerClient
from backend.services.jenkins_adapter import ensure_frontend_summary
from backend.services.local_service import (
    run_git,
    run_svn,
    svn_date_revision_map,
    svn_revision_at_date,
)
from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug, _norm_job_url, _safe_artifact_path


_logger = logging.getLogger("devops_api.jenkins_service")


def list_jobs(
    *,
    base_url: str,
    username: str,
    api_token: str,
    recursive: bool = True,
    max_depth: int = 2,
    verify_tls: bool = True,
) -> List[Dict[str, Any]]:
    srv = JenkinsServerClient(
        base_url=base_url,
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    return [asdict(j) for j in srv.list_jobs(recursive=recursive, max_depth=max_depth)]


def list_builds(
    *,
    job_url: str,
    username: str,
    api_token: str,
    limit: int = 30,
    verify_tls: bool = True,
) -> List[Dict[str, Any]]:
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    api = f"{client.job_url}api/json?tree=builds[number,result,timestamp,url,building,duration]"
    data = client._open_json(api)  # type: ignore[attr-defined]
    builds: List[Dict[str, Any]] = []
    for b in data.get("builds", []) or []:
        if not isinstance(b, dict):
            continue
        builds.append(
            {
                "number": b.get("number"),
                "result": b.get("result"),
                "timestamp": b.get("timestamp"),
                "url": b.get("url"),
                "building": b.get("building"),
                "duration": b.get("duration"),
            }
        )
    return builds[: max(1, int(limit))]


def _dir_has_entries(path: Path) -> bool:
    try:
        return any(path.iterdir())
    except Exception:
        return False


# Sentinel file written after a successful checkout. Cached re-use is only
# allowed when this marker exists — presence of an arbitrary non-empty folder
# (e.g. a partial checkout left over from an interrupted sync) is not enough.
_SOURCE_SENTINEL_NAME = ".source_complete"


def _source_sentinel(source_dir: Path) -> Path:
    return source_dir / _SOURCE_SENTINEL_NAME


def _source_is_complete(source_dir: Path) -> bool:
    return source_dir.is_dir() and _source_sentinel(source_dir).exists()


def read_source_sentinel(source_dir: Path) -> Dict[str, str]:
    """`.source_complete` 파싱 — 부재/손상은 {}. (build_inventory와 같은 형식)"""
    out: Dict[str, str] = {}
    try:
        raw = _source_sentinel(Path(source_dir)).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip().lower()] = value.strip()
    return out


#: 고정된 것으로 인정하는 revision 출처. 값이 곧 신뢰 순위이기도 하다(console > svn_date).
PINNED_REVISION_SOURCES = ("console", "svn_date", "jenkins")


def source_snapshot_is_pinned(source_dir: Path) -> bool:
    """스냅샷이 **그 빌드의 revision**으로 고정됐는지.

    고정되지 않은 스냅샷(=HEAD 체크아웃)은 '체크아웃한 시각의 트리'라, 백필로 과거 빌드를
    한꺼번에 받아오면 전부 같은 트리가 된다 — 베이스라인 대비 변화가 0으로 보이고 ASIL 함수
    변경이 통째로 사라진다(실측: 4개월 33빌드 중 26빌드가 동일 트리). 그래서 revision이
    비어 있거나 출처가 head면 고정 안 됨으로 판정하고 재수집 대상이 된다.
    """
    meta = read_source_sentinel(source_dir)
    if not meta.get("revision"):
        return False
    return meta.get("revision_source", "") in PINNED_REVISION_SOURCES


def _ms_to_svn_iso(ms: int) -> str:
    """epoch ms → svn 날짜-revision용 UTC ISO(밀리초 유지 — map_builds_to_svn_revisions와 동일)."""
    d = _dt.datetime.fromtimestamp(int(ms) / 1000, _dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def resolve_build_svn_revision(
    *, repo_url: str, build_timestamp_ms: Optional[int], username: str = "", password: str = "",
) -> Dict[str, str]:
    """빌드 시각 → 그 시점 SVN revision(fail-soft).

    Jenkins가 소스 SVN revision을 구조화 데이터로 노출하지 않는 git 파이프라인 잡에서
    유일한 정확 경로다(`map_builds_to_svn_revisions`와 같은 근거 — 콘솔 로그 'At revision N'
    일치 검증됨). 실패는 빈 revision + 사유로 정직 보고하고 호출자가 HEAD로 진행한다.
    """
    if not str(repo_url or "").strip():
        return {"revision": "", "error": "no repo_url"}
    if not isinstance(build_timestamp_ms, (int, float)) or build_timestamp_ms <= 0:
        return {"revision": "", "error": "no build timestamp"}
    try:
        res = svn_revision_at_date(
            repo_url=str(repo_url).strip(), when_iso=_ms_to_svn_iso(int(build_timestamp_ms)),
            username=username, password=password,
        )
    except Exception as exc:  # noqa: BLE001 — svn 실행 실패는 HEAD 폴백으로 흡수(정직 기록)
        return {"revision": "", "error": f"{type(exc).__name__}: {exc}"}
    rev = str(res.get("revision") or "").strip()
    if not rev.isdigit():
        return {"revision": "", "error": str(res.get("output") or "svn info -r returned no revision")[:200]}
    return {"revision": rev, "error": ""}


def _robust_rmtree(path: Path) -> None:
    """Remove a directory tree, coping with read-only files that Subversion
    leaves behind on Windows (e.g. `.svn/pristine/**`). A plain `shutil.rmtree`
    there fails with PermissionError and leaves debris that confuses the next
    `svn checkout`."""
    import os
    import stat
    import shutil

    def _on_error(func, target, exc_info):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except Exception:
            pass

    if path.exists():
        shutil.rmtree(path, onerror=_on_error)


def _build_root_lock(build_root: Path):
    """Return a file-based lock scoped to the given build_root.

    When `filelock` is available we use a real file lock so multiple processes
    (e.g. forked workers) are serialised. Otherwise we fall back to a
    threading.Lock keyed by path — still protects against concurrent threads
    in the same process, which is the common case for sync-async.
    """
    try:
        from filelock import FileLock  # type: ignore
    except Exception:
        FileLock = None
    build_root = Path(build_root)
    build_root.mkdir(parents=True, exist_ok=True)
    lock_path = build_root / ".checkout.lock"
    if FileLock is not None:
        return FileLock(str(lock_path), timeout=1800)
    # Fallback: per-path threading lock (process-local only)
    import threading
    key = str(lock_path.resolve())
    cache = getattr(_build_root_lock, "_cache", None)
    if cache is None:
        cache = {}
        _build_root_lock._cache = cache  # type: ignore[attr-defined]
        _build_root_lock._guard = threading.Lock()  # type: ignore[attr-defined]
    with _build_root_lock._guard:  # type: ignore[attr-defined]
        lock = cache.get(key)
        if lock is None:
            lock = threading.Lock()
            cache[key] = lock
    return lock


def ensure_source_checkout(
    *,
    build_root: Path,
    client: JenkinsClient,
    build_selector: str,
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    scm_username: str = "",
    scm_id: str = "",
    force: bool = False,
    build_timestamp_ms: Optional[int] = None,
    pin_revision: bool = False,
) -> Dict[str, Any]:
    import shutil
    source_dir = Path(build_root) / "source"

    # Serialize concurrent checkouts against the same build_root. Two rapid
    # sync requests for the same build must not both enter the run_svn path
    # simultaneously — that causes .svn lock collisions and half-written dirs.
    with _build_root_lock(build_root):
        return _ensure_source_checkout_inner(
            build_root=build_root,
            source_dir=source_dir,
            client=client,
            build_selector=build_selector,
            progress_cb=progress_cb,
            scm_username=scm_username,
            scm_id=scm_id,
            force=force,
            shutil=shutil,
            build_timestamp_ms=build_timestamp_ms,
            pin_revision=pin_revision,
        )


STAGING_DIR_NAME = "source.repin"
BACKUP_DIR_NAME = "source.prev"


def _repin_via_staging(
    *, build_root: Path, source_dir: Path, client: JenkinsClient, build_selector: str,
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]], scm_username: str,
    scm_id: str, shutil, build_timestamp_ms: Optional[int],
) -> Dict[str, Any]:
    """비파괴 재수집 — 형제 디렉터리에 받아 성공했을 때만 교체한다.

    기존 트리를 먼저 지우고 받으면, 체크아웃이 실패한 빌드는 소스를 통째로 잃어
    `has_source=False`가 되고 매트릭스에서 **행 자체가 사라진다**. '틀린 트리'보다 나쁘다.
    교체는 rename 2회(빠름)로 하고 느린 rmtree는 임계 구간 밖에서 한다.
    """
    staging = Path(build_root) / STAGING_DIR_NAME
    backup = Path(build_root) / BACKUP_DIR_NAME
    _robust_rmtree(staging)
    result = _ensure_source_checkout_inner(
        build_root=build_root, source_dir=staging, client=client,
        build_selector=build_selector, progress_cb=progress_cb,
        scm_username=scm_username, scm_id=scm_id, force=False, shutil=shutil,
        build_timestamp_ms=build_timestamp_ms, pin_revision=True,
    )
    if not result.get("ok"):
        _robust_rmtree(staging)
        _logger.warning(
            "[repin] checkout 실패 — 기존 스냅샷을 보존한다 build_root=%s error=%s",
            build_root, result.get("error"),
        )
        result["repin"] = {"applied": False, "previous_kept": True,
                           "reason": str(result.get("error") or "checkout_failed")}
        return result
    try:
        _robust_rmtree(backup)
        if source_dir.exists():
            source_dir.rename(backup)
        try:
            staging.rename(source_dir)
        except OSError:
            # 교체 실패 → 원상 복구(둘 다 없는 상태로 두지 않는다)
            if backup.exists() and not source_dir.exists():
                backup.rename(source_dir)
            raise
    except OSError as exc:
        _robust_rmtree(staging)
        _logger.warning("[repin] swap 실패 — 기존 스냅샷 유지 build_root=%s: %s", build_root, exc)
        return {"ok": False, "error": "repin_swap_failed", "path": str(source_dir),
                "repin": {"applied": False, "previous_kept": True, "reason": str(exc)}}
    _robust_rmtree(backup)
    result["path"] = str(source_dir)
    result["repin"] = {"applied": True, "previous_kept": False}
    return result


def _ensure_source_checkout_inner(
    *,
    build_root: Path,
    source_dir: Path,
    client: JenkinsClient,
    build_selector: str,
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]],
    scm_username: str,
    scm_id: str,
    force: bool,
    shutil,
    build_timestamp_ms: Optional[int] = None,
    pin_revision: bool = False,
) -> Dict[str, Any]:
    # 고정 요청인데 기존 스냅샷이 HEAD 체크아웃이면 재수집한다. 이 재판정이 없으면 센티널만
    # 보고 '이미 캐시됨'으로 반환해, 고정 토글을 켜도 잘못된 트리가 영원히 남는다.
    repin = bool(pin_revision) and _source_is_complete(source_dir) and not source_snapshot_is_pinned(source_dir)
    if repin:
        # ⚠ 재수집은 **비파괴**다. 여기서 기존 트리를 먼저 지우면 새 체크아웃이 실패했을 때
        #   (네트워크 단절·revision에 경로 부재·인증) 그 빌드는 소스를 통째로 잃고 표에서
        #   사라진다 — 틀린 트리보다 나쁜 상태다. 그래서 스테이징 디렉터리에 받고 성공했을
        #   때만 교체한다. force(사용자 명시 재수집)는 종전대로 선삭제를 유지한다.
        if progress_cb:
            try:
                progress_cb("scm_reset", {"path": str(source_dir), "reason": "repin", "destructive": False})
            except Exception:  # silent-ok — 진행률 콜백 실패가 체크아웃을 막으면 안 된다
                pass
        return _repin_via_staging(
            build_root=build_root, source_dir=source_dir, client=client,
            build_selector=build_selector, progress_cb=progress_cb,
            scm_username=scm_username, scm_id=scm_id, shutil=shutil,
            build_timestamp_ms=build_timestamp_ms,
        )
    if force and source_dir.exists():
        # Caller requested a fresh checkout. Remove any previous artefacts so
        # the sentinel/cache logic below behaves as if this were a first sync.
        if progress_cb:
            try:
                progress_cb("scm_reset", {"path": str(source_dir), "reason": "force", "destructive": True})
            except Exception:
                pass
        _robust_rmtree(source_dir)
    if _source_is_complete(source_dir):
        cached_meta = read_source_sentinel(source_dir)
        if progress_cb:
            try:
                progress_cb("scm_done", {"path": str(source_dir), "skipped": True})
            except Exception:
                pass
        return {
            "ok": True, "path": str(source_dir), "scm": "cached",
            "revision": cached_meta.get("revision", ""),
            "revision_source": cached_meta.get("revision_source", "") or "head",
            "pinned": source_snapshot_is_pinned(source_dir),
        }
    try:
        meta = client.get_scm_meta(build_selector=build_selector or "lastSuccessfulBuild")
    except Exception:
        meta = {}
    meta = meta if isinstance(meta, dict) else {}
    meta_repo_urls = meta.get("repo_urls") or []
    jenkins_repo_url = str(meta_repo_urls[0]) if meta_repo_urls else ""
    jenkins_scm = str(meta.get("scm") or meta.get("scm_type") or "").lower()
    jenkins_branch = str(meta.get("git_branch") or meta.get("scm_branch") or "").strip()
    jenkins_revision = str(
        meta.get("scm_revision") or meta.get("git_commit") or meta.get("svn_revision") or ""
    ).strip()

    from backend.services.scm_registry import resolve_scm_credentials
    resolved_username, resolved_password, registry_entry = resolve_scm_credentials(
        repo_url=jenkins_repo_url,
        scm_id=scm_id,
        override_username=scm_username,
    )

    # Registry is source of truth when an explicit mapping exists: the user has
    # already told us which SVN/Git source this Jenkins job corresponds to.
    # Jenkins-reported repo_url can be a mirror URL (e.g. git mirror of an SVN
    # tree) or missing altogether when SCM plugin data is incomplete, so the
    # registry always wins when present.
    override_from_registry = False
    if registry_entry and (registry_entry.scm_url or "").strip():
        repo_url = registry_entry.scm_url.strip()
        scm = (registry_entry.scm_type or jenkins_scm or "svn").lower()
        branch = (registry_entry.branch or "").strip() or jenkins_branch
        # If Jenkins didn't report a repo_url (partial SCM metadata), we have
        # no way to confirm its revision applies to the registry URL we're
        # about to check out — treat that as an override so jenkins_revision
        # is discarded below and we fetch HEAD instead of a foreign revision.
        override_from_registry = (not jenkins_repo_url) or (jenkins_repo_url != repo_url)
        # Revision is only safe when (a) SCM types match AND (b) we are
        # actually checking out the URL Jenkins reported. If the registry
        # rerouted us to a different repo URL — even of the same type —
        # Jenkins' revision is an identifier from a foreign tree (e.g. the
        # mirror) and would either fail (svn: revision out of range) or
        # silently fetch the wrong commit. In that case do a HEAD checkout.
        if not jenkins_scm or jenkins_scm != scm or override_from_registry:
            revision = ""
        else:
            revision = jenkins_revision
    else:
        repo_url = jenkins_repo_url
        scm = jenkins_scm or "git"
        branch = jenkins_branch
        revision = jenkins_revision

    # ── 빌드 시점 revision 고정 ──────────────────────────────────────────────
    # 위 분기가 revision을 비우는 경로(registry override 등)는 **HEAD 체크아웃**이 된다.
    # 그러면 과거 빌드를 오늘 백필했을 때 4개월치 빌드가 전부 오늘의 트리를 받는다 —
    # 베이스라인 대비 변화 0, ASIL 함수 변경 침묵. Jenkins에 소스 SVN revision이 없으므로
    # 빌드 timestamp를 날짜-revision으로 되돌려 고정한다(실패는 HEAD 폴백 + 사유 기록).
    revision_source = "jenkins" if revision else "head"
    pin_error = ""
    if pin_revision and scm == "svn" and not revision:
        # ① 콘솔 로그 직독이 1순위 — 빌드가 **실제로** 체크아웃한 revision이고 네트워크가 없다.
        from backend.services.build_revision import revision_from_console_log

        from_console = revision_from_console_log(Path(build_root), repo_url=repo_url)
        if from_console.get("revision"):
            revision = from_console["revision"]
            revision_source = "console"
        else:
            # ② 폴백: 빌드 시각 → svn 날짜-revision. 로그가 상한에 걸려 선두가 잘린 빌드용.
            pinned = resolve_build_svn_revision(
                repo_url=repo_url, build_timestamp_ms=build_timestamp_ms,
                username=resolved_username, password=resolved_password or "",
            )
            if pinned.get("revision"):
                revision = pinned["revision"]
                revision_source = "svn_date"
            else:
                pin_error = f"{from_console.get('reason') or 'console_unavailable'} / {pinned.get('error') or ''}".strip(" /")
                _logger.warning(
                    "[ensure_source_checkout] pin_failed build_root=%s ts=%s error=%s (HEAD로 진행)",
                    build_root, build_timestamp_ms, pin_error,
                )

    if not repo_url:
        _logger.warning(
            "[ensure_source_checkout] repo_url_missing build_root=%s meta=%r scm_id=%s",
            build_root, meta, scm_id or "-",
        )
        if progress_cb:
            try:
                progress_cb("scm_failed", {"reason": "repo_url_missing"})
            except Exception:
                pass
        return {"ok": False, "error": "repo_url_missing", "meta": meta}

    if override_from_registry and registry_entry is not None:
        _logger.info(
            "[ensure_source_checkout] registry_override jenkins_url=%s → registry_url=%s registry=%s",
            jenkins_repo_url, repo_url, registry_entry.id,
        )
    _logger.info(
        "[ensure_source_checkout] repo_url=%s scm=%s rev=%s branch=%s user=%s registry=%s has_pw=%s",
        repo_url, scm, revision or "-", branch or "-",
        resolved_username or "-",
        (registry_entry.id if registry_entry else "-"),
        bool(resolved_password),
    )

    if progress_cb:
        try:
            progress_cb(
                "scm_clone",
                {
                    "repo_url": repo_url,
                    "branch": branch,
                    "scm": scm,
                    "user": resolved_username or "",
                    "registry_id": (registry_entry.id if registry_entry else ""),
                },
            )
        except Exception:
            pass
    if scm == "svn":
        result = run_svn(
            project_root=str(build_root),
            # 스테이징 재수집(_repin_via_staging)은 형제 디렉터리에 받으므로 고정 금지.
            workdir_rel=source_dir.name,
            action="checkout",
            repo_url=repo_url,
            revision=revision,
            username=resolved_username,
            password=resolved_password,
        )
    else:
        result = run_git(
            project_root=str(build_root),
            # 스테이징 재수집(_repin_via_staging)은 형제 디렉터리에 받으므로 고정 금지.
            workdir_rel=source_dir.name,
            action="clone",
            repo_url=repo_url,
            branch=branch,
            depth=0,
        )
    if result.get("rc") != 0:
        _logger.warning(
            "[ensure_source_checkout] checkout_failed scm=%s rc=%s repo_url=%s user=%s has_pw=%s output=%s",
            scm, result.get("rc"), repo_url, resolved_username or "-",
            bool(resolved_password),
            (result.get("output") or "")[:800],
        )
        if progress_cb:
            try:
                progress_cb(
                    "scm_failed",
                    {"reason": "checkout_failed", "output": result.get("output", "")},
                )
            except Exception:
                pass
        return {
            "ok": False,
            "error": "checkout_failed",
            "scm": scm,
            "repo_url": repo_url,
            "branch": branch,
            "revision": revision,
            "output": result.get("output", ""),
        }
    # Write the completion sentinel so subsequent sync calls can safely treat
    # this directory as cached. Best-effort — a failed write only means we'll
    # re-checkout on the next sync, which is still correct behaviour.
    try:
        source_dir.mkdir(parents=True, exist_ok=True)
        # revision_source는 신규 키 — 없는 구 센티널은 '고정 안 됨'으로 판정된다
        # (source_snapshot_is_pinned). 그래야 HEAD로 받아둔 기존 스냅샷이 재수집 대상이 된다.
        _source_sentinel(source_dir).write_text(
            f"scm={scm}\nrevision={revision}\nbranch={branch}\nrevision_source={revision_source}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    if progress_cb:
        try:
            progress_cb("scm_done", {"path": str(source_dir), "revision": revision,
                                     "revision_source": revision_source})
        except Exception:
            pass
    return {
        "ok": True,
        "path": str(source_dir),
        "scm": scm,
        "repo_url": repo_url,
        "branch": branch,
        "revision": revision,
        "revision_source": revision_source,
        "pin_error": pin_error,
    }


def get_build_info(
    *,
    job_url: str,
    username: str,
    api_token: str,
    build_selector: str,
    verify_tls: bool = True,
) -> Dict[str, Any]:
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    build, artifacts = client.list_artifacts(build_selector or "lastSuccessfulBuild")
    return {
        "build": asdict(build),
        "artifacts": [asdict(a) for a in artifacts],
    }


def get_build_changed_files(
    *,
    job_url: str,
    build_number: int,
    username: str,
    api_token: str,
    verify_tls: bool = True,
) -> Dict[str, Any]:
    """특정 Jenkins 빌드의 SCM changeSet(변경 파일 경로) + revision을 조회한다.

    영향도 분석을 '선택한 빌드의 실제 변경분'에 묶기 위한 헬퍼. git/svn 양쪽의
    changeSet 표현(affectedPaths / paths[].file)을 모두 수집하고, .c/.h 소스만
    반환한다(get_changed_files와 동일 범위). 자격증명/네트워크/파싱 오류는 호출자가
    local diff fallback으로 처리하도록 예외를 그대로 전파한다.

    Returns: {"files": [.c/.h 경로...], "revision": "<SHA1/rev>", "all_count": N}
    """
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    tree = (
        "timestamp,"
        "changeSet[items[affectedPaths,commitId,paths[file,editType]]],"
        "changeSets[items[affectedPaths,commitId,paths[file,editType]]],"
        "actions[lastBuiltRevision[SHA1,revision]]"
    )
    api = f"{client.job_url}{int(build_number)}/api/json?tree={tree}"
    data = client._open_json(api)  # type: ignore[attr-defined]

    csets: List[Dict[str, Any]] = []
    if isinstance(data.get("changeSet"), dict):
        csets.append(data["changeSet"])
    for cs in data.get("changeSets") or []:
        if isinstance(cs, dict):
            csets.append(cs)

    files: set[str] = set()
    # paths[].editType(add/edit/delete) — git/svn 모두 노출. cloudium/원격에서 로컬 diff가
    # 불가할 때 변경유형(NEW/DELETE) 분류의 유일한 출처. affectedPaths는 editType이 없으므로
    # paths[]가 있는 항목에서만 채워지며, 없으면 다운스트림이 확장자 기반(edit)으로 처리한다.
    edit_types: Dict[str, str] = {}
    revision = ""
    for cs in csets:
        for item in cs.get("items") or []:
            if not isinstance(item, dict):
                continue
            for p in item.get("affectedPaths") or []:
                if p:
                    files.add(str(p))
            for pth in item.get("paths") or []:
                if isinstance(pth, dict) and pth.get("file"):
                    f = str(pth["file"])
                    files.add(f)
                    et = str(pth.get("editType") or "").strip().lower()
                    if et and f.lower().endswith((".c", ".h")):
                        # 동일 파일이 여러 commit에 걸친 경우 DELETE/add를 단순 edit이 덮지 않게
                        # 보존(가장 구조적인 변경 유형 우선).
                        prev = edit_types.get(f)
                        if prev not in ("delete", "add"):
                            edit_types[f] = et
            if not revision and item.get("commitId"):
                revision = str(item["commitId"])

    for act in data.get("actions") or []:
        if isinstance(act, dict) and isinstance(act.get("lastBuiltRevision"), dict):
            lbr = act["lastBuiltRevision"]
            revision = str(lbr.get("SHA1") or lbr.get("revision") or revision)
            break

    src = sorted(f for f in files if str(f).lower().endswith((".c", ".h")))
    return {
        "files": src,
        "revision": revision,
        "all_count": len(files),
        "edit_types": edit_types,
        # 빌드 시각(epoch ms) — 소스가 '빌드 시각 기준'으로 svn checkout 되는 파이프라인
        # 잡에서 per-build SVN revision을 날짜-revision으로 되찾기 위한 키(svn_revision_at_date).
        "timestamp": data.get("timestamp"),
    }


def _iso_utc_to_ms(iso: str) -> Optional[int]:
    """svn <date>(UTC ISO, 예: '2026-06-25T04:00:15.971000Z') → epoch ms. 실패 시 None."""
    s = str(iso or "").strip()
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except (ValueError, TypeError):  # 파싱 불가 날짜 문자열 → 스킵(fail-soft)
        return None


def map_builds_to_svn_revisions(
    *,
    repo_url: str,
    builds: List[Dict[str, Any]],
    username: str = "",
    password: str = "",
    max_resolve: int = 100,
) -> Dict[str, Any]:
    """빌드 목록 각 항목에 per-build SVN revision을 in-place 부착한다(fail-soft).

    소스가 '빌드 시각 기준'으로 svn checkout 되는 git 파이프라인 잡(예: KJPDS02_PV)에서,
    빌드 timestamp(epoch ms)를 SVN 날짜-revision으로 매핑한다. Jenkins가 소스 SVN revision을
    구조화 데이터로 노출하지 않으므로(git SHA1만) 이 우회가 유일한 정확 경로다.

    빌드마다 svn info 하지 않고 총 svn 2회로 일괄한다: (1) 가장 오래된 빌드 시각의 floor
    revision(svn info) + (2) [min,max] 구간 svn log(1회)의 (date,rev) 엔트리. 각 빌드는
    'youngest rev ≤ 빌드시각'으로 계산(콘솔 로그의 'At revision N'과 일치 검증됨).

    revision을 못 구하면(svn 실패/미svn 프로젝트) 조용히 미부착 — 목록 자체는 그대로 둔다.
    max_resolve: 최신 N개만 해석(오래된 대량 빌드 과다 해석 방지).

    Returns: {"ok": bool, "resolved": int, "revision_source": str|None, "error": str}
    """
    url = str(repo_url or "").strip()
    if not url:
        return {"ok": False, "resolved": 0, "revision_source": None, "error": "no repo_url"}
    pairs: List[Tuple[int, Dict[str, Any]]] = []
    for b in builds:
        if isinstance(b, dict):
            ts = b.get("timestamp")
            if isinstance(ts, (int, float)):
                pairs.append((int(ts), b))
    if not pairs:
        return {"ok": False, "resolved": 0, "revision_source": None, "error": "no build timestamps"}
    pairs.sort(key=lambda p: p[0], reverse=True)
    target = pairs[: max(1, int(max_resolve))]
    ms_list = [ms for ms, _ in target]
    min_ms, max_ms = min(ms_list), max(ms_list)

    def _ms_to_iso(ms: int) -> str:
        # 밀리초까지 유지(초 절삭 금지) — 분석 경로(_try_svn_revision_range)도 full-ms를 쓰므로
        # 같은 정밀도라야 콤보박스 revision == 분석 revision 이 초 미만 경계에서도 일치한다(W2).
        d = _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc)
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"

    min_iso, max_iso = _ms_to_iso(min_ms), _ms_to_iso(max_ms)
    # (1) floor + repo_root: 가장 오래된 빌드 시각 기준 repo-wide youngest rev ≤ 그 시각.
    anchor = svn_revision_at_date(repo_url=url, when_iso=min_iso, username=username, password=password)
    _floor_str = str(anchor.get("revision") or "").strip()
    floor_rev = int(_floor_str) if _floor_str.isdigit() else None
    root = str(anchor.get("repo_root") or "").strip()
    # anchor(dated svn info) 실패 → 신뢰할 floor/repo_root 없음. 프로젝트 경로로 폴백하면 다중
    # 프로젝트 저장소에서 svn log가 부분집합이 돼 너무 낮은 revision을 조용히 붙인다(W4) →
    # 틀린 값 대신 미부착(fail-soft, 프론트가 '—'로 표시).
    if floor_rev is None or not root:
        return {"ok": False, "resolved": 0, "revision_source": None,
                "error": str(anchor.get("output") or "svn info -r failed (no floor/repo_root)")[:200]}
    # (2) [min,max] 구간 repo-wide 커밋 (ms, rev). svn checkout이 repo-wide revision(다른
    #     프로젝트 커밋 포함)을 잡으므로 로그 대상은 반드시 repo_root(프로젝트 경로=부분집합).
    entries: List[Tuple[int, int]] = []
    if max_ms > min_ms:
        rangemap = svn_date_revision_map(
            repo_url=root, date_from_iso=min_iso, date_to_iso=max_iso,
            username=username, password=password,
        )
        if int(rangemap.get("rc", 1)) != 0:
            # 구간 로그 실패(타임아웃 등) → oldest~newest 사이 커밋을 모른다. floor_rev를 전 빌드에
            # 붙이면 최신 빌드가 옛 revision으로 위장된다(W3, 과거 r1075 버그 형태) → 미부착.
            return {"ok": False, "resolved": 0, "revision_source": None,
                    "error": str(rangemap.get("output") or "svn log range failed")[:200]}
        for iso, rev in (rangemap.get("entries") or []):
            ems = _iso_utc_to_ms(iso)
            if ems is not None:
                entries.append((ems, int(rev)))
    # (3) 각 빌드: youngest rev ≤ 빌드시각(full-ms). floor_rev는 위 가드로 보장된 정수.
    resolved = 0
    for bms, b in target:
        rev = floor_rev
        for ems, erev in entries:
            if ems <= bms and erev > rev:
                rev = erev
        b["revision"] = str(rev)
        resolved += 1
    return {"ok": True, "resolved": resolved, "revision_source": "svn_date", "error": ""}


def sync_local_reports(
    *,
    job_url: str,
    local_reports_dir: Path,
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], Path, Path, List[str], List[Dict[str, Any]]]:
    reports_dir = Path(local_reports_dir).resolve()
    build_root = reports_dir.parent
    build_info: Dict[str, Any] = {
        "number": -1,
        "result": "LOCAL",
        "timestamp": None,
        "url": "",
        "job_url": job_url,
    }
    ensure_frontend_summary(
        reports_dir=reports_dir,
        build_root=build_root,
        build_info=build_info,
        progress_cb=progress_cb,
    )
    return build_info, build_root, reports_dir, [], []


def sync_jenkins_artifacts(
    *,
    job_url: str,
    username: str,
    api_token: str,
    cache_root: Path,
    verify_tls: bool,
    build_selector: str,
    patterns: List[str],
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    scan_mode: Optional[str] = None,
    scan_max_files: Optional[int] = None,
    scm_username: str = "",
    scm_id: str = "",
    force: bool = False,
    pin_source_revision: bool = False,
) -> Tuple[Dict[str, Any], Path, Path, List[str], List[Dict[str, Any]]]:
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )

    build, artifacts = client.list_artifacts(build_selector or "lastSuccessfulBuild")
    if progress_cb:
        try:
            progress_cb("list_artifacts", {"count": len(artifacts)})
        except Exception:
            pass
    if getattr(build, "number", -1) < 0:
        raise RuntimeError("빌드 정보 조회 실패")

    # Ensure the full cache directory tree exists — first-time sync for new projects
    Path(cache_root).mkdir(parents=True, exist_ok=True)
    (Path(cache_root) / "jenkins").mkdir(parents=True, exist_ok=True)

    job_slug = _job_slug(job_url)
    build_root = (Path(cache_root) / "jenkins" / job_slug / f"build_{build.number}").resolve()
    build_root.mkdir(parents=True, exist_ok=True)

    want = client.filter_artifacts(artifacts, patterns or [])
    if progress_cb:
        try:
            progress_cb("download_start", {"total": len(want)})
        except Exception:
            pass
    downloaded: List[str] = []

    total = max(1, len(want))
    for idx, a in enumerate(want):
        rel = getattr(a, "relativePath", "")
        if progress_cb:
            try:
                progress_cb(
                    "download",
                    {"current": idx + 1, "total": total, "file": str(rel)},
                )
            except Exception:
                pass
        dst = _safe_artifact_path(build_root, str(rel))
        if not dst:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        client.download_artifact(a, str(dst))
        try:
            downloaded.append(dst.resolve().relative_to(Path(build_root).resolve()).as_posix())
        except Exception:
            downloaded.append(str(rel).replace("\\", "/"))

    try:
        console_max = int(getattr(config, "JENKINS_CONSOLE_LOG_MAX_BYTES", 2_000_000))
    except Exception:
        console_max = 2_000_000
    try:
        console_path = build_root / "jenkins_console.log"
        if progress_cb:
            try:
                progress_cb("download_console", {"path": str(console_path.name)})
            except Exception:
                pass
        client.download_console_log(
            build_selector=build_selector or "lastSuccessfulBuild",
            dst_path=str(console_path),
            max_bytes=console_max,
        )
        try:
            downloaded.append(console_path.resolve().relative_to(Path(build_root).resolve()).as_posix())
        except Exception:
            downloaded.append(str(console_path.name))
    except Exception:
        pass

    checkout_result = ensure_source_checkout(
        build_root=build_root,
        client=client,
        build_selector=build_selector,
        progress_cb=progress_cb,
        scm_username=scm_username,
        scm_id=scm_id,
        force=force,
        # 빌드 시각(epoch ms)은 이미 list_artifacts로 받아둔 값 — 고정 시 svn 날짜-revision 키.
        build_timestamp_ms=getattr(build, "timestamp", None),
        pin_revision=pin_source_revision,
    )

    reports_dir = _detect_reports_dir(build_root)
    reports_dir.mkdir(parents=True, exist_ok=True)

    build_info: Dict[str, Any] = {
        "number": int(getattr(build, "number", -1)),
        "result": getattr(build, "result", None),
        "timestamp": getattr(build, "timestamp", None),
        "url": getattr(build, "url", None),
        "job_url": job_url,
        # Surface SCM checkout outcome so callers can detect a partial sync
        # (artifacts downloaded, but source_dir empty) without having to scan
        # the filesystem. Empty `error` = success.
        "checkout": {
            "ok": bool(checkout_result.get("ok")),
            "scm": checkout_result.get("scm", ""),
            "error": checkout_result.get("error", ""),
            "path": checkout_result.get("path", ""),
            "revision": checkout_result.get("revision", ""),
            "branch": checkout_result.get("branch", ""),
            # 스냅샷이 빌드 시점으로 고정됐는지 — 'head'면 체크아웃한 날의 트리다(비교 무의미).
            "revision_source": checkout_result.get("revision_source", ""),
            "pin_error": checkout_result.get("pin_error", ""),
        },
    }

    if progress_cb:
        try:
            progress_cb("scan_start", {})
        except Exception:
            pass
    ensure_frontend_summary(
        reports_dir=reports_dir,
        build_root=build_root,
        build_info=build_info,
        progress_cb=progress_cb,
        scan_mode=scan_mode,
        scan_max_files=scan_max_files,
    )
    if progress_cb:
        try:
            progress_cb("scan_done", {})
        except Exception:
            pass

    arts = [asdict(x) for x in artifacts]
    return build_info, build_root, reports_dir, downloaded, arts


def list_cached_builds(*, job_url: str, cache_root: Path) -> List[Dict[str, Any]]:
    job_slug = _job_slug(job_url)
    job_cache_dir = (Path(cache_root) / "jenkins" / job_slug).resolve()
    rows: List[Dict[str, Any]] = []
    if not job_cache_dir.exists():
        return rows
    for p in sorted(job_cache_dir.glob("build_*")):
        if not p.is_dir():
            continue
        num = -1
        try:
            num = int(p.name.replace("build_", ""))
        except Exception:
            pass
        reports_dir = _detect_reports_dir(p)
        rows.append(
            {
                "build_root": str(p),
                "build_number": num,
                "reports_dir": str(reports_dir),
                "mtime": p.stat().st_mtime,
            }
        )
    rows.sort(key=lambda x: x.get("build_number", -1), reverse=True)
    return rows
