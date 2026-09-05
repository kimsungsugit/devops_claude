"""파일 모드(local/cloudium) 영속 저장소 — 재시작 간 사용자 선택 유지.

`/api/file-mode` POST로 전환한 모드는 in-memory resolver 싱글톤(`_resolver`)에만
반영돼 backend 재시작 시 `DEVOPS_FILE_MODE` env 기본값(local)으로 되돌아갔다.
본 저장소가 선택을 `config/file_mode.json`에 영속하고, `get_resolver()`가 startup
시 이를 env보다 우선 적용해 마지막 선택을 복원한다.

저장 위치: `config/file_mode.json`
스키마:
    {"mode": "local"|"cloudium",
     "allowed_prefixes": "<csv>",
     "gate_process": "<exe>",
     "schema_version": 1}

cloudium_extra_prefixes.py 패턴 차용 — FileLock + atomic write (.tmp → os.replace).
allowed_prefixes/gate_process는 cloudium 모드에서 `switch_mode`가 소비하는 kwargs와
동일. 동적으로 추가된 prefix는 cloudium_extra_prefixes.json + SCM merge가 별도로
복원하므로 여기서는 UI 전환 당시의 base 값만 보관한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    FileLock = None  # type: ignore[assignment]
import threading

REPO_ROOT = Path(__file__).resolve().parents[2]
MODE_PATH = REPO_ROOT / "config" / "file_mode.json"
_LOCK = (
    FileLock(str(MODE_PATH) + ".lock", timeout=10)
    if FileLock
    else threading.Lock()
)

_VALID_MODES = ("local", "cloudium")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """atomic write — tmp 파일 작성 후 os.replace로 원자적 교체."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        # `.gitattributes` 는 `*.json text eol=lf` 다. `newline` 을 안 주면 Windows 에서
        # `\n` -> `\r\n` 으로 바뀌어, 설정을 한 번 저장하는 것만으로 파일 전체 줄끝이
        # 뒤집힌다. 같은 실수가 훅 스크립트에서 나면 bash 가 실행을 거부한다.
        newline="\n",
    )
    os.replace(str(tmp), str(path))


def load_file_mode() -> Optional[dict[str, Any]]:
    """영속된 파일 모드 설정 반환.

    Returns:
        {"mode", "allowed_prefixes", "gate_process"} dict,
        또는 None — 파일 없음 / 손상 / mode 무효 시 (graceful, env fallback 유도).
    """
    if not MODE_PATH.exists():
        return None
    try:
        raw = json.loads(MODE_PATH.read_text(encoding="utf-8"))
    except Exception:
        # 손상 파일 graceful — .invalid.json으로 backup 후 None (env 기본값 fallback).
        # rename 실패 시에도 원본을 제거해 매 startup마다 같은 손상 파일을 다시
        # 읽는 무한 손상 루프를 막는다.
        import logging
        try:
            MODE_PATH.rename(MODE_PATH.with_suffix(".invalid.json"))
        except Exception:  # pragma: no cover
            try:
                MODE_PATH.unlink(missing_ok=True)
            except Exception:
                pass
        logging.getLogger("devops_api").warning(
            "file_mode.json 손상 — 무시하고 env/기본 모드로 fallback")
        return None
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode", "")).strip().lower()
    if mode not in _VALID_MODES:
        return None
    return {
        "mode": mode,
        "allowed_prefixes": str(raw.get("allowed_prefixes") or ""),
        "gate_process": str(raw.get("gate_process") or ""),
    }


def save_file_mode(
    mode: str,
    allowed_prefixes: str = "",
    gate_process: str = "",
) -> None:
    """파일 모드 선택을 영속 저장. mode가 유효하지 않으면 저장 skip (no-op)."""
    m = (mode or "").strip().lower()
    if m not in _VALID_MODES:
        return
    payload = {
        "mode": m,
        "allowed_prefixes": allowed_prefixes or "",
        "gate_process": gate_process or "",
        "schema_version": 1,
    }
    with _LOCK:
        _atomic_write(MODE_PATH, payload)


def clear_file_mode() -> None:
    """영속 모드 제거 — 이후 env(DEVOPS_FILE_MODE)/기본값(local)으로 복귀."""
    with _LOCK:
        try:
            MODE_PATH.unlink()
        except FileNotFoundError:
            pass


__all__ = ["MODE_PATH", "load_file_mode", "save_file_mode", "clear_file_mode"]
