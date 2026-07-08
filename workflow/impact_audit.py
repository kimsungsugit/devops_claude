from __future__ import annotations

import os
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    from filelock import FileLock
except ImportError:
    FileLock = None


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO_ROOT / "reports" / "impact_audit"
LOCK_PATH = AUDIT_DIR / ".run_lock"
_RUN_FILE_LOCK = FileLock(str(LOCK_PATH) + ".flock", timeout=5) if FileLock else threading.Lock()
# 다중 uvicorn 워커 배포: 실행 수명 동안 _RUN_FILE_LOCK을 '보유'해 진짜 cross-process 뮤텍스로
# 쓴다(holder crash 시 OS가 fd를 닫으며 자동 해제 → 좀비 락 없음). _RUN_INTRA_LOCK은 같은
# 프로세스 내 다중 daemon 잡을 직렬화(filelock은 같은 인스턴스에 re-entrant라 자체로 intra 배제
# 불가). _RUN_LOCK_OWNER는 소유 스레드를 기록해 실패한 acquire/타 스레드가 남의 락을 풀지
# 못하게 한다(threading.Lock은 owner 개념이 없어 명시 추적 필요).
_RUN_INTRA_LOCK = threading.Lock()
_RUN_LOCK_OWNER: Dict[str, Any] = {"tid": None}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return raw if isinstance(raw, dict) else default


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_audit_dir() -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIT_DIR


def _active_lock_result() -> Dict[str, Any]:
    existing = _load_json(LOCK_PATH, default={}) or {}
    return {"ok": False, "reason": "active_lock", "lock_path": str(LOCK_PATH), "lock": existing}


def acquire_run_lock(scm_id: str) -> Dict[str, Any]:
    """Impact 실행 중복을 차단하는 뮤텍스 획득(intra-process + cross-process).

    성공 시 두 락을 '실행 수명 동안' 보유하고 release_run_lock()에서 해제한다(과거처럼 즉시
    해제 후 .run_lock 내용검사에 의존하지 않는다 — 그 방식은 cross-process에서 살아있는 타
    프로세스 락을 오회수했다). .run_lock 파일은 이제 진단용 메타데이터일 뿐 뮤텍스가 아니다.
    """
    ensure_audit_dir()
    # 1) intra-process 직렬화 — 같은 프로세스의 다른 daemon 잡 스레드가 이미 실행 중이면 차단.
    #    (filelock은 동일 인스턴스에 re-entrant라 cross-process만으로는 이걸 못 막는다.)
    if not _RUN_INTRA_LOCK.acquire(blocking=False):
        return _active_lock_result()
    # 2) cross-process 뮤텍스 — 다른 uvicorn 워커가 보유 중이면 즉시(timeout 0) 실패.
    try:
        if FileLock:
            _RUN_FILE_LOCK.acquire(timeout=0)
        elif not _RUN_FILE_LOCK.acquire(blocking=False):
            raise TimeoutError("lock held")
    except Exception:
        try:
            _RUN_INTRA_LOCK.release()
        except RuntimeError:
            pass
        return _active_lock_result()

    # 두 락 보유 — 소유 스레드 기록 후 진단 메타데이터 기록(뮤텍스 아님).
    _RUN_LOCK_OWNER["tid"] = threading.get_ident()
    payload = {
        "scm_id": str(scm_id or "").strip(),
        "started_at": _now_iso(),
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
    }
    _save_json(LOCK_PATH, payload)
    return {"ok": True, "lock_path": str(LOCK_PATH), "lock": payload}


def release_run_lock() -> bool:
    # 소유 스레드만 해제 — 실패한 acquire나 다른 스레드가 남의 락을 풀지 못하게(threading.Lock은
    # owner 검증이 없어 명시 확인 필요). finally에서 무조건 호출돼도 비소유자는 no-op.
    if _RUN_LOCK_OWNER.get("tid") != threading.get_ident():
        return False
    _RUN_LOCK_OWNER["tid"] = None
    removed = False
    if LOCK_PATH.exists():
        try:
            LOCK_PATH.unlink()
            removed = True
        except OSError:
            pass
    try:
        if FileLock:
            if getattr(_RUN_FILE_LOCK, "is_locked", False):
                _RUN_FILE_LOCK.release()
        elif _RUN_FILE_LOCK.locked():
            _RUN_FILE_LOCK.release()
    except Exception:
        pass
    try:
        if _RUN_INTRA_LOCK.locked():
            _RUN_INTRA_LOCK.release()
    except RuntimeError:
        pass
    return removed


def write_impact_audit(payload: Dict[str, Any]) -> Path:
    ensure_audit_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = AUDIT_DIR / f"impact_{ts}.json"
    _save_json(out, payload)
    return out


def list_impact_audits(scm_id: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    ensure_audit_dir()
    target_scm = str(scm_id or "").strip()
    items: List[Dict[str, Any]] = []
    for path in sorted(AUDIT_DIR.glob("impact_*.json"), reverse=True):
        raw = _load_json(path, default={})
        if not raw:
            continue
        if target_scm and str(raw.get("scm_id") or "").strip() != target_scm:
            continue
        actions = raw.get("actions") if isinstance(raw.get("actions"), dict) else {}
        auto_count = 0
        flag_count = 0
        failed_count = 0
        for info in actions.values():
            if not isinstance(info, dict):
                continue
            mode = str(info.get("mode") or "").upper()
            status = str(info.get("status") or "").lower()
            if mode == "AUTO":
                auto_count += 1
            elif mode == "FLAG":
                flag_count += 1
            if status == "failed":
                failed_count += 1
        items.append(
            {
                "path": str(path),
                "filename": path.name,
                "timestamp": raw.get("timestamp") or raw.get("started_at") or path.stem.replace("impact_", ""),
                "scm_id": raw.get("scm_id", ""),
                "trigger": raw.get("trigger", ""),
                "dry_run": bool(raw.get("dry_run")),
                "changed_files": raw.get("changed_files") or [],
                "changed_functions": raw.get("changed_functions") or {},
                "warnings": raw.get("warnings") or [],
                "auto_count": auto_count,
                "flag_count": flag_count,
                "failed_count": failed_count,
                "actions": actions,
            }
        )
        if len(items) >= max(1, int(limit or 10)):
            break
    return items
