"""생성 중 문제 수집기 — "무엇이 문제였고(actual), 무엇이 문제가 될 수 있는가(potential)" 를 **생성이 도는 동안** 모은다 (R48-b).

## 왜

문서 생성 파이프라인은 경고를 `_logger.warning` 으로만 남겼다 — 참조 SwUDS 가 다른 파일이다, 소스 루트 하나를 못 찾았다,
템플릿에 없는 함수 214개가 문서에서 빠졌다, accuracy 리포트가 300초 타임아웃으로 죽었다. 전부 백엔드 로그에만 있고 화면은
진행바와 마지막 메시지뿐이었다. 사용자는 "success" 60MB 문서를 받고 나서야 셀을 열어 보고 알았다.

이 모듈은 그 경고들을 **구조화된 항목**으로 모아 진행 폴링(`issues`)·완료 결과·품질 run 의 `meta_json` 에 싣는다. 판정을 바꾸지
않는다(게이트는 그대로) — 보이게만 한다.

## 어휘

- `severity`: `error`(생성 결과가 틀렸거나 빠졌다) · `warning`(결과는 나왔지만 신뢰가 깎인다) · `risk`(지금은 문제가 아니지만 검토자가 알아야 한다)
- `kind`: `actual`(이미 문제가 된 것) · `potential`(문제가 될 수 있는 것)
- `code`: 기계용 식별자(`reference_identity_blocked`, `report_timeout:accuracy` …). 설명기(`issue_explainer`)의 룰 문장이 이 코드로 붙는다.

## 전달 방식

파라미터를 열 겹 뚫지 않는다 — `contextvars` 로 **현재 수집기**를 둔다. 파이프라인 진입부가 `use_collector()` 로 열고, 깊은
헬퍼는 `note_issue()` 만 부른다. 수집기가 없으면(단위 테스트·다른 경로) 조용히 아무것도 안 한다 — 이 모듈은 관측이지 판정이
아니라 부재가 결과를 바꾸면 안 된다. 스레드는 `wrap_with_user` 처럼 호출자가 컨텍스트 안에서 파이프라인을 **직접** 부르므로
같은 스레드 안에서 값이 보인다(백그라운드 워커가 파이프라인 함수 안에서 `use_collector` 를 연다).
"""
from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

SEVERITIES = ("error", "warning", "risk")
KINDS = ("actual", "potential")

# 한 run 에 남길 상한 — 함수 1,157개짜리 문서에서 함수마다 항목을 만들면 진행 폴링 응답이 MB 급이 된다.
# 넘치면 마지막에 `issues_truncated` 한 건으로 **넘쳤다는 사실**을 남긴다(조용히 자르지 않는다).
MAX_ISSUES = 200
MESSAGE_MAX = 400


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    kind: str
    message: str
    stage: str = ""
    facts: Dict[str, Any] = field(default_factory=dict)
    at: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IssueCollector:
    """스레드 안전한 누적 목록. 같은 `(code, message)` 는 한 번만(재시도 루프가 같은 경고를 반복 찍는 것을 막는다)."""

    def __init__(self) -> None:
        self._items: List[Issue] = []
        self._seen: set = set()
        self._lock = threading.Lock()
        self._overflow = 0

    def add(self, code: str, severity: str, kind: str, message: str, *,
            stage: str = "", facts: Optional[Dict[str, Any]] = None) -> Optional[Issue]:
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}: {severity!r}")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}: {kind!r}")
        code = str(code or "").strip()
        if not code:
            raise ValueError("code 가 비었다")
        msg = " ".join(str(message or "").split())[:MESSAGE_MAX]
        key = (code, msg)
        with self._lock:
            if key in self._seen:
                return None
            if len(self._items) >= MAX_ISSUES:
                self._overflow += 1
                return None
            self._seen.add(key)
            item = Issue(
                code=code, severity=severity, kind=kind, message=msg, stage=str(stage or ""),
                facts=dict(facts or {}), at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._items.append(item)
            return item

    def as_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            out = [i.as_dict() for i in self._items]
            if self._overflow:
                out.append(Issue(
                    code="issues_truncated", severity="warning", kind="actual",
                    message=f"문제 항목이 상한 {MAX_ISSUES}건을 넘어 {self._overflow}건을 싣지 못했다 — 백엔드 로그를 볼 것",
                    facts={"dropped": self._overflow, "max": MAX_ISSUES},
                    at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ).as_dict())
            return out

    def counts(self) -> Dict[str, Any]:
        with self._lock:
            items = list(self._items)
        by_sev = {s: 0 for s in SEVERITIES}
        by_kind = {k: 0 for k in KINDS}
        for i in items:
            by_sev[i.severity] += 1
            by_kind[i.kind] += 1
        return {"total": len(items) + (1 if self._overflow else 0), **by_kind, "by_severity": by_sev}

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


_CURRENT: contextvars.ContextVar[Optional[IssueCollector]] = contextvars.ContextVar("gen_issues_collector", default=None)


def current_collector() -> Optional[IssueCollector]:
    return _CURRENT.get()


@contextmanager
def use_collector(collector: Optional[IssueCollector] = None) -> Iterator[IssueCollector]:
    """이 블록 안에서 `note_issue()` 가 `collector` 에 쌓인다. 빠져나가면 이전 값으로 복원(중첩 안전)."""
    c = collector if collector is not None else IssueCollector()
    token = _CURRENT.set(c)
    try:
        yield c
    finally:
        _CURRENT.reset(token)


def note_issue(code: str, severity: str, kind: str, message: str, *,
               stage: str = "", facts: Optional[Dict[str, Any]] = None) -> Optional[Issue]:
    """현재 수집기에 한 건 더한다. 수집기가 없으면 None(아무 일도 없다 — 관측의 부재가 판정을 바꾸지 않는다)."""
    c = _CURRENT.get()
    if c is None:
        return None
    return c.add(code, severity, kind, message, stage=stage, facts=facts)


def issue_payload(collector: Optional[IssueCollector]) -> Dict[str, Any]:
    """진행 폴링·완료 결과·meta 에 싣는 형태 — 수집기가 없으면 빈 목록이 아니라 **`issues_recorded: False`** 다."""
    if collector is None:
        return {"issues": [], "issue_counts": None, "issues_recorded": False}
    return {"issues": collector.as_list(), "issue_counts": collector.counts(), "issues_recorded": True}


__all__ = [
    "KINDS",
    "MAX_ISSUES",
    "SEVERITIES",
    "Issue",
    "IssueCollector",
    "current_collector",
    "issue_payload",
    "note_issue",
    "use_collector",
]
