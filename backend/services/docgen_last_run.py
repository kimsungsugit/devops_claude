"""**직전 생성이 어떻게 끝났는지**를 준비 게이트가 읽을 수 있게 하는 단일 출처.

## 왜 이 모듈이 생겼나 (2026-09-01 실측)

UDS 생성은 매번 `<out>.docx.stage.json` 체크포인트를 남긴다
(`backend/helpers/uds.py::_generate_docx_with_retry`). 거기엔 어느 단계에서 어떻게
끝났는지, 성공했다면 payload 함수가 몇 개나 문서에 들어갔는지가 전부 적혀 있다.

그런데 **그 파일을 읽는 코드가 저장소 전체에 없었다.** 그 사실 자체가
`tests/unit/test_report_reachability.py::TestCheckpointIsWriteOnly` 에 기록돼 있었고,
"나중에 reader 가 생기면 여기서 실패하므로 그때 기록을 갱신하면 된다" 고 적혀 있다.

사용자 캐시(`hbrnd2/exports`)의 실제 기록 3건 — 게이트는 셋 다 몰랐다:

| 시각 | 단계 | 결말 | 실제로 무슨 일이 있었나 |
|---|---|---|---|
| 2026-08-07 15:46 | `full` | success | payload 함수 **0개**, 내용 없이 남은 heading **419개** — 문서는 템플릿 서식뿐 |
| 2026-08-10 17:01 | `degraded_light` | failed | 재시도 사다리 **끝까지 전부 실패**(`PackageNotFoundError`), 산출물 없음 |
| 2026-08-11 09:35 | `degraded_light` | failed | 〃 |

즉 **두 번은 아무것도 못 만들었고 한 번은 빈 서식을 만들었는데**, 그 다음에 게이트를
열어도 "준비 완료" 였다. 게이트의 다른 행은 전부 *지금의 입력*을 재는데, 직전 시도가
어떻게 끝났는지는 어디에도 없었다.

## 판정 규약

- **기록이 없으면 행을 내지 않는다.** `unmeasured` 로 내면 한 번도 생성한 적 없는
  프로젝트가 영구히 `unknown` 판정에 고착된다 — 재는 수단이 "생성해 보는 것" 뿐이라
  게이트가 스스로 풀 수 없는 매듭이 된다(같은 함정을 라운드 3에서 이미 밟았다).
- **성공/실패 판정을 여기서 뒤집지 않는다.** 반영률이 낮다고 실패로 부르지 않는다 —
  템플릿이 의도된 부분집합일 수 있다(`_run_docx_in_subprocess` 주석이 든 사유).
  다만 **한 개도 안 실린 것**은 부분집합이 아니라 전무이므로 `degraded` 로 말한다.
- **분모 0 은 0% 가 아니다.** `payload_functions == 0` 이면 반영률을 재지 않는다
  (`_uds_artifact_fidelity` 와 같은 규약 — 규칙을 복제하지 않고 같은 경계를 쓴다).
  대신 잴 수 있는 축(빈 heading 수)은 그대로 말한다.
- **`started` 는 성공이 아니다.** 체크포인트는 각 단계 **시작 시**에도 쓰인다. 프로세스가
  중단되면 그 상태로 남으므로 "결말이 기록되지 않았다" 로 낸다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger("devops_api.docgen_last_run")

# 체크포인트가 실을 수 있는 결말. `_run_docx_in_subprocess` 의 네 갈래와 lockstep이다.
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_EXCEPTION = "exception"
STATUS_STARTED = "started"

# ── 이름 규칙 — 쓰는 쪽과 읽는 쪽의 **단일 출처** ──────────────────────────
#
# 체크포인트 접미사는 `_run_docx_in_subprocess` 가 **여기서 import 해서** 쓴다. 리터럴을
# 양쪽에 두면 한쪽만 바뀌었을 때 글로브가 아무것도 못 찾고, 그 결과는 "생성한 적 없음"
# 과 화면상 구분되지 않는다 — 행이 조용히 사라지는 것이다.
CHECKPOINT_SUFFIX = ".docx.stage.json"
# 산출물 접두사는 두 쌍둥이 라이터(`backend/helpers/uds.py` · `backend/routers/jenkins.py`)
# 가 f-string 안에서 쓰므로 상수를 넘길 수 없다. 대신 드리프트를 가드가 실측한다
# (`tests/unit/test_docgen_last_run.py::TestNamingIsBoundToTheWriters`).
ARTIFACT_PREFIX = "uds_spec_"
_CHECKPOINT_GLOB = ARTIFACT_PREFIX + "{slug}_*" + CHECKPOINT_SUFFIX


def last_retry_stage() -> str:
    """재시도 사다리의 **마지막 단계 이름**. 모르면 빈 문자열.

    체크포인트는 단계마다 덮어쓰이므로 남아 있는 것이 *마지막으로 시도한* 단계다.
    그게 사다리의 끝이면 재시도가 하나도 살리지 못했다는 뜻이라 같은 '실패' 라도
    무게가 다르다.

    ⚠ 단계 목록을 여기에 복제하지 않는다 — `_generate_docx_with_retry` 가 읽는
      `config.UDS_DOCX_RETRY_STAGES` 를 그대로 읽는다. 복제하면 사다리를 바꿀 때
      한쪽만 고쳐지고, 그러면 이 문장이 조용히 틀린 말이 된다.
    """
    try:
        import config
        stages = getattr(config, "UDS_DOCX_RETRY_STAGES", None) or []
        return str(stages[-1][0]) if stages else ""
    except Exception:  # silent-ok — 사다리를 못 읽으면 이 한 문장만 빠진다(판정 불변)
        return ""


def find_last_run_checkpoint(cache_root: str, job_url: str) -> Optional[Path]:
    """이 프로젝트의 **가장 최근** UDS 생성 체크포인트.

    ⚠ `create=False` 다. 읽기 조회가 디렉터리를 만들면 없는 캐시가 조회만으로 생겨난다
      (`_normalize_jenkins_cache_root` 의 인자 설명이 그 사유를 든다).

    ⚠ 정렬은 **mtime** 이다. 파일명의 `_{ts}` 는 생성을 *시작한* 시각이고, 체크포인트는
      단계가 끝날 때마다 다시 쓰이므로 mtime 이 곧 "가장 최근에 기록된 결말" 이다.
    """
    slug = str(job_url or "").strip()
    if not slug:
        # 슬러그가 없으면 남의 프로젝트 기록을 집게 된다 — 조회 자체를 하지 않는다.
        return None
    try:
        from backend.helpers.jenkins import _jenkins_exports_dir
        from backend.services.jenkins_helpers import _job_slug

        out_dir = _jenkins_exports_dir(cache_root, create=False)
        if not out_dir.is_dir():
            return None
        hits = list(out_dir.glob(_CHECKPOINT_GLOB.format(slug=_job_slug(job_url))))
    except Exception as exc:  # noqa: BLE001 — 캐시 경로 해석 계열이 광범위
        _logger.warning("직전 생성 기록 조회 실패(%s: %s)", type(exc).__name__, exc)
        return None
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)


def _artifact_of(checkpoint: Path) -> Path:
    """`….docx.stage.json` → `….docx`. 접미사만 걷는다(이름 규칙 복제 아님)."""
    name = checkpoint.name
    if not name.endswith(CHECKPOINT_SUFFIX):
        return checkpoint
    return checkpoint.with_name(name[: -len(CHECKPOINT_SUFFIX)] + ".docx")


def _cause_line(record: Dict[str, Any]) -> str:
    """실패 사유 한 줄 — traceback 의 **마지막 줄**이 예외 그 자체다.

    `error_tail` 은 `(stderr + stdout)[-2000:]` 이라 앞이 잘려 있을 수 있지만 끝은
    온전하다. 실측에서 이 한 줄이 정확히 원인을 짚었다:
    `docx.opc.exceptions.PackageNotFoundError: Package not found at 'U:/…'`
    """
    raw = str(record.get("error_tail") or record.get("error") or "").strip()
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def _when(record: Dict[str, Any]) -> str:
    """사람이 읽는 시각. 기록에 없는 값을 지어내지 않는다(없으면 빈 문자열)."""
    raw = str(record.get("ended_at") or record.get("started_at") or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%m/%d %H:%M")
    except ValueError:
        return raw[:16]


def summarize_last_run(checkpoint: Path) -> Optional[Dict[str, Any]]:
    """체크포인트 한 건 → 게이트가 그대로 쓸 수 있는 사실 묶음.

    Returns:
        `None` 은 **읽지 못했다**는 뜻이다(부재/깨짐). 없는 결말을 "성공" 으로 접지 않는다.
    """
    try:
        record = json.loads(checkpoint.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 깨진 기록은 결말이 아니다
        _logger.warning("직전 생성 기록을 읽지 못했다(%s: %s): %s",
                        type(exc).__name__, exc, checkpoint.name)
        return None
    if not isinstance(record, dict):
        return None

    artifact = _artifact_of(checkpoint)
    stats = record.get("gen_stats")
    stats = stats if isinstance(stats, dict) else {}
    payload = stats.get("payload_functions")
    matched = stats.get("matched_functions")
    measurable = isinstance(payload, int) and payload > 0 and isinstance(matched, int)

    return {
        "status": str(record.get("status") or "").strip(),
        "stage": str(record.get("stage") or "").strip(),
        "when": _when(record),
        "artifact": artifact.name,
        # 실패한 생성은 파일을 남기지 않는다 — 그 사실이 결말을 뒷받침한다.
        "artifact_exists": artifact.exists(),
        "timeout_seconds": record.get("timeout_seconds"),
        "cause": _cause_line(record),
        # ⚠ `measurable=False` 는 반영률 0% 가 **아니다**. 분모가 없어 재지 못한 것이다.
        "measurable": measurable,
        "payload_functions": payload if isinstance(payload, int) else None,
        "matched_functions": matched if isinstance(matched, int) else None,
        "empty_heading_count": stats.get("empty_heading_count"),
        "unmatched_payload_count": stats.get("unmatched_payload_count"),
        # 라운드 9·10 이 심은 관측량 — 있으면 싣고 없으면 없는 대로 둔다(옛 기록엔 없다).
        "restored_template_blocks": stats.get("restored_template_blocks"),
        "preserved_template_tables": stats.get("preserved_template_tables"),
        "table_rows_recovered": stats.get("table_rows_recovered"),
        "table_rows_blank_trimmed": stats.get("table_rows_blank_trimmed"),
        "swcom_globals_unattributed": stats.get("swcom_globals_unattributed"),
        "checkpoint": str(checkpoint),
    }


def last_uds_run(cache_root: str, job_url: str) -> Optional[Dict[str, Any]]:
    """이 프로젝트의 직전 UDS 생성 결말. 기록이 없으면 `None`."""
    checkpoint = find_last_run_checkpoint(cache_root, job_url)
    return summarize_last_run(checkpoint) if checkpoint else None
