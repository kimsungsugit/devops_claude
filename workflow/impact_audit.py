from __future__ import annotations

import json
import os
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
LOCK_PATH = AUDIT_DIR / ".run_lock"  # legacy(하위호환 참조용) — 실제 락은 아래 scm별 경로
# 다중 uvicorn 워커 배포: 실행 수명 동안 FileLock을 '보유'해 진짜 cross-process 뮤텍스로 쓴다
# (holder crash 시 OS가 fd를 닫으며 자동 해제 → 좀비 락 없음). intra 락은 같은 프로세스 내 다중
# daemon 잡을 직렬화(filelock은 같은 인스턴스에 re-entrant라 자체로 intra 배제 불가).
# ⚠ 두 락 모두 **scm_id별**로 지연 생성한다(_get_locks) — 전역 단일 락은 프로젝트 간 차단 +
# 테스트 격리 불가(import 시점 경로 바인딩) 문제를 일으켰다.
_RUN_FILE_LOCKS: Dict[str, Any] = {}
_RUN_INTRA_LOCKS: Dict[str, threading.Lock] = {}
_RUN_LOCKS_GUARD = threading.Lock()
# 키(scm)별 소유 스레드 — 실패한 acquire/타 스레드가 남의 락을 풀지 못하게 한다(threading.Lock은
# owner 개념이 없어 명시 추적 필요). scm별로 두므로 서로 다른 프로젝트가 같은 프로세스에서 동시에
# 실행돼도 소유자가 덮이지 않는다.
_RUN_LOCK_OWNERS: Dict[str, int] = {}


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


def _lock_key(scm_id: str) -> str:
    s = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(scm_id or "").strip())
    return s.strip("_").lower() or "default"


def _get_locks(scm_id: str):
    """(key, json_path, intra_lock, file_lock) — **scm_id별** 락을 지연 생성한다.

    과거엔 모듈 import 시점에 고정 경로로 만든 **전역 단일** FileLock이었다:
      (1) 프로젝트 A 분석이 프로젝트 B를 최대 1시간(문서 자동생성 timeout) 동안 차단하고,
      (2) 테스트가 AUDIT_DIR/LOCK_PATH를 monkeypatch해도 FileLock 경로는 import 시점 repo 경로에
          바인딩돼 그대로여서, **동시 실행 pytest들이 서로의 락에 걸려 'active_lock' 유령 실패**를
          냈다(원인 파악이 매우 어려움 — 코드 결함처럼 보임).
    → 호출 시점의 AUDIT_DIR로 scm별 경로를 만들고, 경로가 바뀌면 락 객체를 재생성한다.
    """
    key = _lock_key(scm_id)
    json_path = AUDIT_DIR / f".run_lock_{key}.json"
    flock_path = str(AUDIT_DIR / f".run_lock_{key}.flock")
    with _RUN_LOCKS_GUARD:
        intra = _RUN_INTRA_LOCKS.setdefault(key, threading.Lock())
        fl = _RUN_FILE_LOCKS.get(key)
        if fl is None or (FileLock and getattr(fl, "lock_file", None) != flock_path):
            fl = FileLock(flock_path, timeout=5) if FileLock else threading.Lock()
            _RUN_FILE_LOCKS[key] = fl
    return key, json_path, intra, fl


def _active_lock_result(json_path: Path) -> Dict[str, Any]:
    existing = _load_json(json_path, default={}) or {}
    return {"ok": False, "reason": "active_lock", "lock_path": str(json_path), "lock": existing}


def acquire_run_lock(scm_id: str) -> Dict[str, Any]:
    """Impact 실행 중복을 차단하는 뮤텍스 획득(intra-process + cross-process).

    성공 시 두 락을 '실행 수명 동안' 보유하고 release_run_lock()에서 해제한다(과거처럼 즉시
    해제 후 .run_lock 내용검사에 의존하지 않는다 — 그 방식은 cross-process에서 살아있는 타
    프로세스 락을 오회수했다). .run_lock 파일은 이제 진단용 메타데이터일 뿐 뮤텍스가 아니다.
    """
    ensure_audit_dir()
    key, json_path, intra, fl = _get_locks(scm_id)
    # 1) intra-process 직렬화 — 같은 프로세스의 다른 daemon 잡 스레드가 이미 실행 중이면 차단.
    #    (filelock은 동일 인스턴스에 re-entrant라 cross-process만으로는 이걸 못 막는다.)
    if not intra.acquire(blocking=False):
        return _active_lock_result(json_path)
    # 2) cross-process 뮤텍스 — 다른 uvicorn 워커가 보유 중이면 즉시(timeout 0) 실패.
    try:
        if FileLock:
            fl.acquire(timeout=0)
        elif not fl.acquire(blocking=False):
            raise TimeoutError("lock held")
    except Exception:
        try:
            intra.release()
        except RuntimeError:
            pass
        return _active_lock_result(json_path)

    # 두 락 보유 — 키별 소유 스레드 기록 후 진단 메타데이터 기록(뮤텍스 아님).
    with _RUN_LOCKS_GUARD:
        _RUN_LOCK_OWNERS[key] = threading.get_ident()
    payload = {
        "scm_id": str(scm_id or "").strip(),
        "started_at": _now_iso(),
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
    }
    try:
        # ⚠ 진단 메타 기록 실패가 **락 영구 누수**가 되면 안 된다(과거엔 try 없이 호출돼, 디스크
        #   오류·권한 문제로 예외가 나면 두 락을 쥔 채 예외가 전파돼 프로세스 수명 내내 impact
        #   분석 전체가 'active_lock'으로 막혔다). 진단은 best-effort.
        _save_json(json_path, payload)
    except Exception:
        pass
    return {"ok": True, "lock_path": str(json_path), "lock": payload}


def release_run_lock(scm_id: str = "") -> bool:
    """이 스레드가 소유한 락만 해제. scm_id를 주면 그 키만(권장 — 명시적).

    ⚠ scm_id 없이 tid만으로 키를 찾으면(과거 방식) 스레드 ident 재사용 시 **남의 락을 해제**하고
    진짜 소유 락은 프로세스 수명 내내 누수될 수 있다(파이썬은 ident 재사용을 허용). 소유자 검증은
    유지하되 키는 호출측이 명시하는 것이 안전하다. 인자 없는 호출은 하위호환(폴백 스캔).
    """
    tid = threading.get_ident()
    with _RUN_LOCKS_GUARD:
        if scm_id:
            key = _lock_key(scm_id)
            if _RUN_LOCK_OWNERS.get(key) != tid:
                return False  # 비소유자 → no-op(남의 락 보호)
        else:
            key = next((k for k, v in list(_RUN_LOCK_OWNERS.items()) if v == tid), None)
            if key is None:
                return False
        _RUN_LOCK_OWNERS.pop(key, None)
        fl = _RUN_FILE_LOCKS.get(key)
        intra = _RUN_INTRA_LOCKS.get(key)
    json_path = AUDIT_DIR / f".run_lock_{key}.json"
    removed = False
    try:
        if json_path.exists():
            json_path.unlink()
            removed = True
    except OSError:
        pass
    try:
        if fl is not None:
            if FileLock:
                if getattr(fl, "is_locked", False):
                    fl.release()
            elif fl.locked():
                fl.release()
    except Exception:
        pass
    try:
        if intra is not None and intra.locked():
            intra.release()
    except RuntimeError:
        pass
    return removed


def write_impact_audit(payload: Dict[str, Any]) -> Path:
    """ISO 26262 감사 레코드 기록. 파일명에 **scm_id**를 포함하고 충돌 시 유니크화한다.

    ⚠ 실행 락이 scm별로 바뀌면서 서로 다른 프로젝트가 **동시에** 끝날 수 있는데, 파일명이 초 단위
    타임스탬프뿐이면 한쪽의 감사 기록이 조용히 덮어써진다(추적성 손실 — 안전 엔지니어가 "무엇을 왜
    분석/제외했는지"를 검증할 유일한 durable 레코드다). scm_id + 중복 시 접미사로 손실을 막는다.
    (읽기: list_impact_audits는 impact_*.json glob, change_log는 run_id=stem에서 파생 → 호환)
    """
    ensure_audit_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    scm = _lock_key(str(payload.get("scm_id") or ""))  # alnum/_/- 로 안전화
    base = f"impact_{ts}" if scm == "default" else f"impact_{ts}_{scm}"
    out = AUDIT_DIR / f"{base}.json"
    _n = 1
    while out.exists():  # 같은 초·같은 scm 재실행에서도 덮어쓰지 않는다
        out = AUDIT_DIR / f"{base}_{_n}.json"
        _n += 1
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
