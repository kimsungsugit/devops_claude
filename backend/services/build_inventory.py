"""캐시된 빌드의 오프라인 메타 인벤토리 — Jenkins 연결 없이 빌드 목록을 완성한다.

`list_cached_builds`(jenkins_service.py)는 {build_root, build_number, reports_dir, mtime}만
반환한다(result/timestamp/revision 없음). 요약탭이 "캐시에 있는 모든 빌드"를 Jenkins
불가 상황에서도 표면화하려면 빌드 디렉토리의 로컬 산출물을 직독해야 한다:
- report/status.json  → result / timestamp(ISO 문자열 — KJPDS02_PV 실측) / build_url
- source/.source_complete 센티널 → scm / revision / branch (jenkins_service가 기록)
- 존재 플래그(has_source/has_rcr/has_analysis_summary) → 상위 기능(rule-trend·baseline-diff)의
  가용성 판단.

정직성 규약: 산출물 부재/손상은 null(0·빈문자 위장 금지) — 프론트가 '—'로 렌더한다.
jenkins_service.py는 동시세션 편집이 잦아 이 모듈은 별도 파일로 분리(무접촉).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.jenkins_service import list_cached_builds
from backend.services.prqa_delta import find_latest_rcr_html

logger = logging.getLogger(__name__)

SENTINEL_NAME = ".source_complete"


def _parse_sentinel(source_dir: Path) -> Dict[str, str]:
    """`.source_complete` 텍스트(`scm=…\nrevision=…\nbranch=…`) 파싱 — 부재/손상은 {}."""
    path = source_dir / SENTINEL_NAME
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    out: Dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key in ("scm", "revision", "branch", "revision_source") and value:
            out[key] = value
    return out


def _is_pinned(sentinel: Dict[str, str]) -> bool:
    """스냅샷이 **그 빌드의 revision**으로 고정됐는지 — HEAD 체크아웃은 False.

    고정되지 않은 스냅샷은 '받아온 날의 트리'라, 과거 빌드를 한꺼번에 백필하면 전부 같은
    트리가 된다(실측: 4개월 33빌드 중 26빌드 동일). 그러면 베이스라인 대비 변화가 0으로
    보이고 ASIL 함수 변경이 통째로 사라지므로, 이 플래그를 UI까지 올려 재수집을 유도한다.
    `revision_source` 키가 없는 구 센티널도 고정 안 됨으로 본다(보수적).
    """
    if not sentinel.get("revision"):
        return False
    return sentinel.get("revision_source", "") not in ("", "head")


def _read_status_json(reports_dir: Path) -> Dict[str, Any]:
    try:
        data = json.loads((reports_dir / "status.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def list_cached_builds_meta(*, job_url: str, cache_root: Path) -> List[Dict[str, Any]]:
    """캐시 빌드 목록 + 오프라인 메타(최신순). Jenkins 연결 불필요."""
    rows: List[Dict[str, Any]] = []
    for base in list_cached_builds(job_url=job_url, cache_root=cache_root):
        build_root = Path(str(base.get("build_root") or ""))
        reports_dir = Path(str(base.get("reports_dir") or ""))
        status = _read_status_json(reports_dir)
        source_dir = build_root / "source"
        sentinel = _parse_sentinel(source_dir)
        ts = status.get("timestamp")
        rows.append(
            {
                **base,
                "result": status.get("result") or None,
                # status.json timestamp는 ISO 문자열(실측) — 형식 그대로 전달(변환 왜곡 금지).
                "timestamp_iso": str(ts) if ts else None,
                "build_url": status.get("build_url") or None,
                "revision": sentinel.get("revision") or None,
                "branch": sentinel.get("branch") or None,
                "scm": sentinel.get("scm") or None,
                # 스냅샷 신뢰도 — False면 '변화 0'이 코드 미변경이 아니라 HEAD 체크아웃 결과다.
                "source_pinned": _is_pinned(sentinel),
                "source_revision_source": sentinel.get("revision_source") or None,
                "has_source": (source_dir / SENTINEL_NAME).exists(),
                "has_rcr": find_latest_rcr_html(build_root, reports_dir) is not None,
                "has_analysis_summary": (reports_dir / "analysis_summary.json").exists(),
            }
        )
    return rows


def find_build_meta(rows: List[Dict[str, Any]], build_number: Optional[int]) -> Optional[Dict[str, Any]]:
    if build_number is None:
        return None
    for r in rows:
        try:
            if int(r.get("build_number")) == int(build_number):
                return r
        except (TypeError, ValueError):
            continue
    return None
