"""계정·역할 변경 감사 기록 — append-only JSONL (R48-a 리뷰 W4).

4-eyes 의 증거는 "누가 승인했나" 로 끝나지 않는다 — **누가 그 사람에게 승인 권한을 줬나** 까지다. `review_audit` 는 검토
행위만 남기고, 계정 생성/역할 변경은 마스킹된 로그 한 줄뿐이었다. admin 이 승인자 계정을 만들어 스스로 로그인하는 우회는
막을 수 없지만(정책), **영속 흔적**은 남겨야 한다.

- 위치: `config.DEFAULT_REPORT_DIR/account_audit.jsonl`(= `reports/`, git 밖). 한 줄 = 한 사건. 지우거나 고치지 않는다.
- 이름은 **원문**이다(감사 기록이 마스킹돼 있으면 되짚을 수 없다). 파일은 서버 로컬이고 HTTP 로 노출하지 않는다.
- 쓰기 실패는 사건을 막지 않되 WARNING 으로 남긴다 — 감사 기록이 없는 채 조용히 진행되면 그것이 가장 나쁜 상태다.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger("devops_api.account_audit")
_LOCK = threading.Lock()


def audit_path() -> Path:
    try:
        import config
        base = Path(str(getattr(config, "DEFAULT_REPORT_DIR", "reports") or "reports"))
    except Exception as exc:  # noqa: BLE001 — config 부재(독립 스크립트)면 저장소 기본 위치
        _logger.debug("config 없이 기본 reports/ 사용(%s)", type(exc).__name__)
        base = Path("reports")
    return base / "account_audit.jsonl"


def record_account_event(action: str, *, actor: str, subject: str, detail: Optional[Dict[str, Any]] = None) -> bool:
    """한 줄 추가. 반환 False = 기록 실패(사건 자체는 진행됐다 — 호출자가 응답에 `audit_recorded` 로 공시)."""
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": str(action), "actor": str(actor), "subject": str(subject),
        "detail": dict(detail or {}),
    }
    path = audit_path()
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        _logger.warning("계정 감사 기록 실패(%s) — %s %s→%s 는 진행됐다", exc, action, actor, subject)
        return False


__all__ = ["audit_path", "record_account_event"]
