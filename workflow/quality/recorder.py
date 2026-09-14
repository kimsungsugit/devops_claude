"""Record generation runs and quality scores to the Quality DB."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from workflow.quality.evaluator import (
    compute_gate_verdict,
    compute_overall_score,
    evaluate_comprehensive_result,
    evaluate_coverage,
    evaluate_sits,
    evaluate_sts,
    evaluate_suts,
    evaluate_swit_coverage,
    evaluate_swreport,
    evaluate_swsa,
    evaluate_test_result,
    evaluate_uds,
)
from workflow.quality.models import GenerationRun, QualityScore, QualitySummary

_logger = logging.getLogger("workflow.quality.recorder")


# (R37 D-3) 빈 산출물 run 의 `status`. `success` 와 갈라 두면 KPI·추세·delta 가 자동으로 비켜간다.
EMPTY_OUTPUT_STATUS = "empty_output"

#: (R39 N1) 빌드 응답이 "이 파일이 어느 run 인가" 를 말하는 헤더. 값은 run id 또는 `unrecorded`.
QUALITY_RUN_HEADER = "X-Quality-Run-Id"
#: 기록이 안 됐을 때의 값 — 빈 헤더나 헤더 부재로 두면 "옛 서버" 와 구별되지 않는다.
QUALITY_RUN_UNRECORDED = "unrecorded"


def quality_run_headers(run_id: Any) -> Dict[str, str]:
    """기록 결과 → 응답 헤더 한 줄. **실패도 말한다.**

    빌더 6곳은 `record_run(...)` 을 `try/except` 로 감싸 non-fatal 로 두는데(기록이 깨져도 산출물은
    줘야 한다), 그 반환값을 **아무도 안 봤다**. 그래서 사용자는 파일을 받고도
    ① 이게 어느 run 인지 · ② 애초에 기록이 됐는지를 알 방법이 없었다 — 검토 기록(R34~)이
    run 단위인데 방금 받은 파일과 그 run 을 **잇는 수단이 없다**는 뜻이다.

    ⚠ 헤더를 **빼지 않는다**. 부재는 "옛 서버" 와 구별되지 않아 화면이 두 상태를 한 칸에 그린다 —
      기록 실패는 `unrecorded` 로 **명시**한다(이 저장소의 anti-fake-green 계약).
    ⚠ 이 헤더는 `backend/main.py::EXPOSED_RESPONSE_HEADERS` 에 **반드시** 들어가야 한다.
      cross-origin 구성(`config.js` 의 `__ARIA_API_BASE__`)에서는 노출 목록에 없는 헤더가
      브라우저에서 조용히 `null` 이 된다 — `tests/unit/test_response_headers_exposed.py` 가 강제한다.
    """
    try:
        n = int(run_id)
    except (TypeError, ValueError):
        return {QUALITY_RUN_HEADER: QUALITY_RUN_UNRECORDED}
    return {QUALITY_RUN_HEADER: str(n)} if n > 0 else {QUALITY_RUN_HEADER: QUALITY_RUN_UNRECORDED}

# doc_type → summary 에서 "내용물 개수" 를 담는 키. 어휘가 문서마다 다르다(같은 뜻인데 이름이 셋).
_EMPTY_KEYS = {
    "sts": "total_test_cases", "suts": "total_test_cases", "sits": "total_test_cases",
    "swreport": "performed_count",
    # 종합결과서(swutcr/switcr)도 커버리지와 **같은 `total_tcs` 키**를 쓴다
    # (`swut_comprehensive_aggregator.py:1078`). 바로 아래 SUTR/SITR 과 헷갈리지 말 것.
    "swut": "total_tcs", "swit": "total_tcs", "swutcr": "total_tcs", "switcr": "total_tcs",
    # 시험 결과 보고서 summary 는 `total_tcs` 가 아니라 `total` 이다 — 커버리지 키를 그대로 쓰면
    # **모든 SUTR/SITR 이 빈 산출물로** 판정된다.
    "sutr": "total", "sitr": "total",
    "swsa": "his_metrics",
    # UDS 는 summary 가 아니라 `quick_gate.counts.total_functions` 에 규모가 있다 — 아래 특수 분기.
    "uds": "total_functions",
}


def empty_output_reason(doc_type: Any, quality_data: Any) -> Optional[str]:
    """내용이 빈 산출물인가 — 그렇다면 **어느 축이 0이었는지**. 아니면 None.

    판정을 여기 하나만 둔다: 기록기와 화면 문구가 각자 세면 "왜 점수가 없는지" 가 갈린다.
    반환값은 사유 토큰(`empty:<키>`)이고 그대로 `meta.empty_output_reason` 에 남는다.
    """
    dt = str(doc_type or "").lower().strip()
    key = _EMPTY_KEYS.get(dt)
    if not key:
        return None
    data = quality_data or {}
    if dt == "uds":
        # 규모가 중첩(`quick_gate.counts.total_functions`)이고 bare quick_gate 형태도 온다.
        qg = data.get("quick_gate") if isinstance(data.get("quick_gate"), dict) else data
        counts = qg.get("counts") if isinstance(qg.get("counts"), dict) else {}
        try:
            n = int(counts.get("total_functions") or qg.get("total_functions") or 0)
        except (TypeError, ValueError):
            n = 0
        return f"empty:{key}" if n <= 0 else None
    if dt in ("swut", "swit"):
        # ⚠ (R38 D-5 ③) 커버리지 문서의 내용물은 **TC 수가 아니라 함수 행**이다.
        #   `total_tcs` 하나로 판정하면, 로그 폴더가 비었거나 **헤더 탐지가 실패했을 때**
        #   (`swut_consistency_checker.py` 가 "헤더 탐지 실패로 total_tcs=0" 이라 적어 둔 바로 그
        #   상황) 구문·분기·MC/DC 지표가 **통째로 기록되지 않는다** — ISO 26262 커버리지 증거가
        #   무경고로 사라진다. 게다가 `evaluator.evaluate_coverage` 는 같은 `total_tcs` 를
        #   "분모로 쓰면 완전실행 스위트를 오탐 FAIL 시킨다" 며 **비게이트 참고지표**로만 쓴다 —
        #   판정에 못 쓰는 값을 기록 여부 판정에 쓰고 있었던 셈이다.
        #   분모 축은 `_record_run_impl` 의 `fn_count`(swut/swit)와 **같은 키**를 본다.
        n = 0
        for k in ("total_tcs", "functions_with_coverage", "function_rows"):
            try:
                n = max(n, int(data.get(k) or 0))
            except (TypeError, ValueError):
                continue
        return "empty:coverage_rows" if n <= 0 else None
    if key == "his_metrics":
        return None if data.get(key) else f"empty:{key}"
    try:
        n = int(data.get(key) or 0)
    except (TypeError, ValueError):
        n = 0
    return f"empty:{key}" if n <= 0 else None


def current_identity() -> Optional[str]:
    """(R48-a) 지금 요청의 사용자 이름 — 없으면 None.

    `backend.user_context` 는 지연 import(계층: workflow → backend 는 이 모듈의 scm_registry 선례와 같다).
    `default` 는 미들웨어의 "신원 없음" 토큰이라 이름이 아니다 — NULL 로 둔다. 백엔드 없이 도는 스크립트
    (`generate_uds_local.py` 등)는 import 자체가 실패할 수 있고, 그때도 None 이다(기록을 버리지 않는다).
    """
    try:
        from backend.user_context import get_current_user
        user = str(get_current_user() or "").strip()
    except Exception as exc:  # noqa: BLE001 — 백엔드 컨텍스트 밖(독립 스크립트)에서는 신원이 없는 것이 정상
        _logger.debug("created_by 미기록 — 요청 컨텍스트 없음(%s)", type(exc).__name__)
        return None
    return user if user and user != "default" else None


def _record_empty_output_run(doc_type: str, *, reason: str, status: Any = None, **kwargs: Any) -> int:
    """생성은 됐고 내용이 비었다 — **run 행만** 남긴다(점수·요약 없음).

    ⚠ 예전엔 이 경우를 통째로 skip 했다. 그러면 사용자는 문서를 내려받았는데 생성 현황은
      계속 "미생성" 이라, 같은 빈 문서를 다시 만든다. 0점 FAIL 로 기록하는 것도 답이 아니다
      (재지도 않은 축을 미달로 세어 KPI 를 오염시킨다 — skip 이 원래 막으려던 것).
      그래서 **사실만** 남긴다: 언제·무엇을·어느 바이트로 만들었는지, 그리고 왜 점수가 없는지.
    ⚠ 요약(`QualitySummary`)을 만들지 않는 것이 곧 판정 제외다 — `/api/quality/trend` 는
      `join(QualitySummary)` 라 이 run 을 보지 않고, 점수 집계도 마찬가지다.
    """
    from workflow.quality.db import get_session, init_db

    db_path = kwargs.get("db_path")
    init_db(db_path)
    with get_session(db_path) as session:
        output_size, output_sha, sha_reason = _measure_output(
            kwargs.get("output_path"), kwargs.get("output_sha256"), kwargs.get("output_size_bytes"),
            kwargs.get("output_hash_reason"),
        )
        run_meta: Dict[str, Any] = dict(kwargs.get("meta") or {})
        run_meta["empty_output_reason"] = reason
        if sha_reason:
            run_meta["output_sha256_reason"] = sha_reason
        # ⚠ 호출부가 준 status 를 **덮지 않는다**(R37 리뷰 W4). `record_run(status="failed", …)` 에
        #   빈 데이터가 실리면 "실패했다" 는 사실이 "내용이 비었다" 로 갈아끼워진다 — 둘 다 참일 때
        #   더 중요한 쪽은 실패다. 사유는 어느 쪽이든 meta 에 남는다.
        given = str(kwargs.get("status") or status or "success").strip() or "success"
        run = GenerationRun(
            run_uuid=str(uuid.uuid4()),
            doc_type=doc_type,
            project_root=kwargs.get("project_root"),
            scm_id=kwargs.get("scm_id"),
            target_function=kwargs.get("target_function"),
            status=EMPTY_OUTPUT_STATUS if given == "success" else given,
            elapsed_sec=kwargs.get("elapsed_sec"),
            output_path=kwargs.get("output_path"),
            output_size_bytes=output_size,
            output_sha256=output_sha,
            created_by=kwargs.get("created_by"),
            ai_model=kwargs.get("ai_model"),
            error_msg=kwargs.get("error_msg"),
            meta_json=json.dumps(run_meta, ensure_ascii=False),
        )
        session.add(run)
        session.flush()
        return int(run.id)


def record_run(
    doc_type: str,
    quality_data: Dict[str, Any],
    *,
    project_root: Optional[str] = None,
    scm_id: Optional[str] = None,
    target_function: Optional[str] = None,
    status: str = "success",
    elapsed_sec: Optional[float] = None,
    output_path: Optional[str] = None,
    output_sha256: Optional[str] = None,
    output_size_bytes: Optional[int] = None,
    output_hash_reason: Optional[str] = None,
    ai_model: Optional[str] = None,
    error_msg: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None,
    created_by: Optional[str] = None,
) -> int:
    """생성 실행 1회를 Quality DB에 기록.

    ``created_by`` (R48-a): 이 run 을 만든 사람. 명시하지 않으면 **요청 contextvar**(`get_current_user`)에서
    읽는다 — 호출부 11곳을 건드리지 않고도 채워지도록 판정을 여기 한 곳에 둔다(`scm_id` 자동 해결과 같은
    자리). 백그라운드 스레드는 `wrap_with_user` 로 신원을 상속하므로 async 생성도 채워진다. 신원이 없으면
    (`default`·스크립트) NULL — 검토 기록의 자기 승인 판정은 NULL 을 "판단 불가" 로 공시한다.

    ``output_sha256`` (R33 C-1): 산출물 바이트의 SHA-256 hex. 명시하면 그 값을 쓰고, 없으면
    ``output_path`` 파일을 읽어 계산한다. 둘 다 없으면 NULL(미기록). 이 값이 검토 기록(R34~)의 대상
    고정에 쓰인다. **BytesIO 응답 빌더는 `output_hash_kwargs(buf)` 를 `**` 로 펼쳐 넘긴다**(R36 C-4) —
    호출부마다 `sha256_hex(buf.getvalue())` 를 복제하면 한 곳이 빠진다.
    ``output_size_bytes``: 명시 해시와 **같은 바이트**의 길이. 명시 해시가 있으면 크기는 파일에서 재지
    않는다 — 한 행의 크기와 해시가 다른 바이트를 가리키면 안 된다(R33 리뷰 W2).
    ``output_hash_reason`` (R36 리뷰 W2): 바이트를 못 얻은 **호출부 쪽 사유**. 경로도 해시도 없을 때
    `no_path` 대신 이 값을 남긴다 — 안 그러면 "경로가 없는 문서다"(정상)와 "버퍼 배선이 깨졌다"(버그)가
    한 토큰이 되어, R36 자신의 실패가 화면에서 정상으로 읽힌다.
    해시를 못 기록한 사유는 `meta.output_sha256_reason` 에 남는다(`no_path`·`file_missing`·`not_a_file`·
    `unreadable`·`invalid_arg` + 호출부 사유 `no_bytes`·`bytes_unreadable`·`bytes_not_bytes`·`empty_bytes`)
    — NULL 갈래를 한 값으로 접지 않는다(R33 W5 · R36 리뷰 W2).

    Returns:
        run_id (성공 시), -1 (실패 시 -- 예외 전파하지 않음)
    """
    try:
        # scm_id 를 명시로 받지 못했으면 `project_root` 에서 해결한다.
        # 호출부 7곳(swut/swit/swreport/swsa/sts/suts/sits)은 이미 프로젝트를 아는
        # 값을 project_root 로 넘기고 있으므로, 판정을 **여기 한 곳**에 두면 그
        # 7곳을 건드리지 않고도 축이 채워지고 앞으로 늘 호출도 자동으로 덮인다.
        # (UDS 5곳은 project_root 자체가 없어 명시 전달이 필요하다 — 라우터 참조.)
        # ⚠ 이 해결은 빈 산출물 판정 **앞**에 있어야 한다(R37 D-3). 뒤에 두면 빈 run 만
        #   `scm_id` 가 NULL 이 되고, 화면은 프로젝트 축으로 조회하므로 그 run 을 못 찾아
        #   **여전히 "미생성"** 이다 — 기록을 남기는 의미가 절반 사라진다.
        if not scm_id and project_root:
            try:
                from backend.services.scm_registry import resolve_scm_id
                scm_id = resolve_scm_id(project_root)
            except Exception:
                # registry 를 못 읽는 건 품질 기록을 버릴 이유가 아니다. 축만 미상으로
                # 두고 기록은 계속한다 — 다만 침묵은 금지(사후에 왜 NULL 인지 알아야 한다).
                _logger.exception("scm_id 자동 해결 실패 — 미상(NULL)으로 기록한다")
                scm_id = None
        # (R48-a) 생성자 — 명시 인자 > 요청 contextvar. 빈 산출물 분기 **앞**에서 해결한다(scm_id 와 같은 이유).
        created_by = current_identity() if created_by is None else (str(created_by).strip() or None)
        if created_by is None:
            # (리뷰 W4) NULL 은 곧 4-eyes 판정 불가(면제)다 — 조용히 남기지 않는다. 사유를 meta 에 적고 WARNING 으로.
            meta = dict(meta or {})
            meta.setdefault("created_by_reason", "no_identity")
            _logger.warning("%s run 을 생성자 미상(created_by NULL)으로 기록한다 — 요청 컨텍스트 밖(스크립트/GUI)이거나 "
                            "신원 없는 요청. 이 run 은 자기 승인 차단 대상에서 벗어난다", (doc_type or "").lower())

        # 내용이 빈 산출물: **점수는 남기지 않고 생성 사실만** 남긴다 (R37 D-3).
        # 예전엔 통째로 skip 했는데, 그러면 사용자는 파일을 받았는데 화면은 "미생성" 이라
        # 같은 빈 문서를 다시 만든다. 판정 축은 여전히 비켜간다(요약을 안 만든다).
        # doc_type 11종 전부 같은 규약이다 — UDS(중첩 키)도 `empty_output_reason` 이 판정한다.
        _dt = (doc_type or "").lower().strip()
        _empty_reason = empty_output_reason(_dt, quality_data)
        if _empty_reason:
            _logger.info("%s quality run recorded without scores (%s)", _dt, _empty_reason)
            return _record_empty_output_run(
                _dt, reason=_empty_reason, status=status,
                project_root=project_root, scm_id=scm_id, target_function=target_function,
                elapsed_sec=elapsed_sec, output_path=output_path, output_sha256=output_sha256,
                output_size_bytes=output_size_bytes, output_hash_reason=output_hash_reason,
                ai_model=ai_model, error_msg=error_msg, meta=meta, db_path=db_path,
                created_by=created_by,
            )

        return _record_run_impl(
            doc_type, quality_data,
            project_root=project_root, scm_id=scm_id,
            target_function=target_function,
            status=status, elapsed_sec=elapsed_sec,
            output_path=output_path, output_sha256=output_sha256,
            output_size_bytes=output_size_bytes, output_hash_reason=output_hash_reason,
            ai_model=ai_model,
            error_msg=error_msg, meta=meta, db_path=db_path,
            created_by=created_by,
        )
    except Exception:
        _logger.exception("Failed to record quality run (non-fatal)")
        return -1


def record_uds_run(quality_eval: Dict[str, Any], **kwargs: Any) -> int:
    """UDS 생성 품질을 Quality DB에 기록 (non-fatal).

    Args:
        quality_eval: backend._build_quality_evaluation() 반환 dict(quick_gate 포함)
            또는 _compute_quick_quality_gate() 반환 dict(bare quick_gate: rates/counts 보유).
        **kwargs: record_run 으로 전달 (project_root/output_path/elapsed_sec/ai_model 등).

    ⚠ (R40 N10) **함수가 0개여도 기록한다.** 예전 이 자리엔 빈 생성이면 건너뛴다는 문장이
    있었는데, R37 이 그 선차단을 없앤 뒤로 **사실이 아니었다** — UDS 만 옛 동작으로 남으면
    생성은 됐는데 이력이 없어 보드가 영영 "미생성" 이고, 사용자는 같은 빈 문서를 다시 만든다.
    빈 산출물 판정은 `record_run` 의 `empty_output_reason` **한 곳**이 하고, 그 run 은
    `status='empty_output'` 으로 남아 점수만 없다(= 판정 제외).

    Returns:
        run_id (성공 시), -1 (**실패 시** -- 예외 전파하지 않음). skip 은 더 이상 없다.
    """
    try:
        data = dict(quality_eval or {})
        # bare quick_gate(rates/counts 보유)면 quick_gate 로 감싼다.
        if "quick_gate" not in data and ("rates" in data or "counts" in data):
            data = {
                "quick_gate": data,
                "gate_pass": data.get("gate_pass"),
                "confidence_gate_pass": data.get("confidence_gate_pass"),
            }
        # (R37 리뷰 W1) 여기서 함수 수를 보고 선차단하지 않는다 — 그러면 **UDS 만** 옛 동작으로
        # 남아, 생성은 됐는데 이력이 없어 보드가 영영 "미생성" 이다. 판정은 `record_run` 의
        # `empty_output_reason` 하나로 통일한다.
        # ⚠ (R40 N10) 그때 남겨 둔 `total_fn = int(...)` + `del total_fn` 을 **지웠다.**
        #   아무도 안 쓰는 값인데 `int()` 가 던지면(예: `total_functions="N/A"`) 아래
        #   `except Exception` 이 `return -1`(기록 통째 유실)로 접는다 — 정작 살아 있는 판정기는
        #   같은 입력을 `(TypeError, ValueError)` 로 받아 0 으로 정상 처리한다.
        #   **죽은 계산이 산 경로를 죽이는** 형태라, 계산 자체를 없애는 것이 옳다.
        return record_run("uds", data, **kwargs)
    except Exception:
        _logger.exception("Failed to record UDS quality run (non-fatal)")
        return -1


def record_test_result_run(
    doc_type: str,
    summary: Dict[str, Any],
    *,
    project_id: str = "",
    asil_level: str = "",
    release_sw_version: str = "",
    **kwargs: Any,
) -> int:
    """SUTR/SITR(시험 결과 보고서) 1회 기록 — SwUT/SwIT 라우터 **공용 단일 출처**.

    라우터별로 복제하면 한쪽만 고쳐진다. 실제로 커버리지 기록 블록이 이미 swut/swit 에
    두 벌 복제돼 있고, 이 저장소는 같은 패턴으로 여러 번 당했다(판정 복제 → 한쪽만 수정).
    doc_type 외에는 전부 같으므로 인자만 다르게 받아 여기 한 곳에서 만든다.

    ``project_id`` 를 ``project_root`` 로 넘기는 건 오타가 아니다 — Sw* 계열은 예전부터
    ``project_root`` 자리에 project_id("HDPDM01")를 실어 왔고, ``record_run`` 의 scm_id
    자동 해결이 그 어휘를 그대로 받는다(models.py 의 project_root 주석 참조).
    """
    return record_run(
        doc_type, summary,
        project_root=str(project_id or ""),
        meta={
            "asil_level": str(asil_level or ""),
            "kind": doc_type,
            "release_sw_version": str(release_sw_version or ""),
        },
        **kwargs,
    )


_SHA256_HEX_LEN = 64


def sha256_hex(data: bytes) -> str:
    """바이트열의 SHA-256 hex(64자) — BytesIO 응답 빌더가 `record_run(output_sha256=)` 에 넘길 값."""
    return hashlib.sha256(data).hexdigest()


def _digest_kwargs(view: Any) -> Dict[str, Any]:
    """바이트를 담은 무엇이든 → `{output_sha256, output_size_bytes}`. **복사하지 않는다.**

    `hashlib` 은 buffer protocol 을 그대로 받으므로 `bytes()` 로 감쌀 이유가 없다. 크기는
    `nbytes`(memoryview 는 `len()` 이 **항목 수**라 itemsize 가 1 이 아니면 바이트 수와 다르다).
    """
    n = getattr(view, "nbytes", None)
    if n is None:
        n = len(view)
    if not n:
        _logger.warning("산출물 바이트가 0개다 — 해시 미기록(빈 입력의 해시를 산출물 해시로 남기지 않는다)")
        return {"output_hash_reason": "empty_bytes"}
    return {"output_sha256": hashlib.sha256(view).hexdigest(), "output_size_bytes": int(n)}


def output_hash_kwargs(buf: Any) -> Dict[str, Any]:
    """(R36 C-4) BytesIO 응답 빌더의 산출물 → `record_run(**kwargs)` 인자.

    성공: `{output_sha256, output_size_bytes}` · 실패: `{output_hash_reason: …}`(기록은 남기고 해시만 없음).
    라우터 4곳 + 시험결과 헬퍼 2곳이 각자 `sha256_hex(buf.getvalue())` 를 복제하면 한 곳이 빠진다(이 저장소의
    반복 결함). 받는 것: `io.BytesIO` · `bytes`/`bytearray`/`memoryview`.

    (R37 D-2) **`getbuffer()` 로 무복사 해시**한다. 실측(write 로 채운 11MB BytesIO, 5회 중앙값):
    `getvalue()` 는 추가 peak **11.00 MB**, `getbuffer()` 는 **0.00 MB**(시간은 6.0ms vs 5.9ms 로 동등).
    앞판은 `getvalue()` 로 한 벌, `bytes(data)` 로 또 한 벌을 떠서 응답 조립의 `read()` 까지 **세 벌**이었다.
    ⚠ export 를 안 풀면 그 BytesIO 는 `write`/`truncate`/`close` 가 전부 `BufferError` 다(실측) — 그래서
      반드시 `with` 로 감싼다. `seek`/`read` 는 export 중에도 되므로 응답 조립은 영향을 받지 않는다.
    ⚠ 하네스 주의: `io.BytesIO(초기값)` 은 그 값을 **공유**해 `getvalue()` 가 복사를 안 한다 — 그 형태로 재면
      두 방식의 우열이 반대로 나온다(실제 빌더는 `wb.save(buf)` 즉 write 로 채운다).

    ⚠ **실패를 `no_path` 로 접지 않는다**(R36 리뷰 W2). 경로 없는 문서는 정상이고 버퍼를 못 받은 것은 버그인데,
      한 토큰이면 화면에서 구별되지 않아 **배선이 끊긴 사실이 영영 리포트되지 않는다**.
    ⚠ **0바이트는 해시하지 않는다**(리뷰 W3). `e3b0c442…`(빈 입력의 sha256)는 유효한 해시처럼 보여서
      빈 산출물이 검토 승인까지 받을 수 있다 — 무엇의 해시인가를 답할 수 없으면 기록하지 않는다.
    ⚠ 같은 입력을 다시 빌드해도 해시는 대개 다르다 — openpyxl 이 `docProps/core.xml` 에 **초 단위** 저장 시각을
      쓴다(2026-09-07 실측: 같은 초 안 6회는 동일, 1.1초 넘기면 그 파트만 다름). 검토는 run 의 바이트에 붙는다.
    """
    if isinstance(buf, (bytes, bytearray, memoryview)):
        try:
            return _digest_kwargs(buf)
        except (BufferError, TypeError, ValueError) as exc:
            # 비연속 memoryview 등 — hashlib 이 거부한다. 침묵하지 않고 사유를 남긴다.
            _logger.warning("산출물 바이트를 해시하지 못했다 — 해시 미기록: %s", exc)
            return {"output_hash_reason": "bytes_unreadable"}
    if hasattr(buf, "getbuffer"):
        try:
            with buf.getbuffer() as view:      # ← 무복사. with 를 벗어나며 export 해제(BufferError 방지)
                return _digest_kwargs(view)
        except Exception as exc:  # noqa: BLE001 — 어떤 실패도 기록을 버릴 이유가 아니다
            _logger.warning("산출물 버퍼를 읽지 못했다 — 해시 미기록: %s", exc)
            return {"output_hash_reason": "bytes_unreadable"}
    if hasattr(buf, "getvalue"):
        # `getbuffer` 가 없는 파일류(구현체·스텁) 폴백 — 여기서만 복사가 생긴다.
        try:
            data = buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("산출물 버퍼를 읽지 못했다 — 해시 미기록: %s", exc)
            return {"output_hash_reason": "bytes_unreadable"}
        if not isinstance(data, (bytes, bytearray, memoryview)):
            _logger.warning("산출물 버퍼가 바이트가 아니다(%s) — 해시 미기록", type(data).__name__)
            return {"output_hash_reason": "bytes_not_bytes"}
        return _digest_kwargs(data)
    _logger.warning("산출물 버퍼 없음(%s) — 해시 미기록", type(buf).__name__)
    return {"output_hash_reason": "no_bytes"}


def _hash_and_size_of_file(path: "str | Path") -> "tuple[str, int]":
    """파일 바이트의 (SHA-256 hex, 길이) — **한 번 읽으며** 둘 다 잰다. 1MiB 청크(UDS docx 46MB).

    크기를 `stat` 으로 따로 재면 그 사이 파일이 갈릴 때 한 행의 크기와 해시가 다른 세대를 가리킨다
    (R33 리뷰 X1-B TOCTOU). 파일이 없거나 못 읽으면 예외를 **그대로** 올린다 — 호출부가 사유를 정한다.
    """
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def sha256_of_file(path: "str | Path") -> str:
    """파일 바이트의 SHA-256 hex(검토 기록의 stale 재검증이 쓸 공개 함수)."""
    return _hash_and_size_of_file(path)[0]


def resolve_output_path(output_path: Any) -> Path:
    """`output_path` 를 **저장소 루트 기준**으로 앵커링한다(상대 경로 → 절대).

    라이브 DB 실측(2026-09-07): 상대 경로 행이 실재한다(`reports\\_gen_check\\SUTS_check.xlsm` 등). 앵커 없이
    `Path(p)` 를 열면 백엔드 기동(CWD)과 스크립트 실행이 **다른 파일**을 해시한다 — `db._default_db_path`
    가 같은 함정으로 read/write DB 가 갈렸던 자리다. 기록·재검증(R34)이 이 한 함수를 같이 쓴다.
    저장되는 `output_path` 문자열은 손대지 않는다(원본 증거).
    """
    p = Path(str(output_path))
    if p.is_absolute():
        return p
    try:
        import config
        root = Path(config.__file__).resolve().parent
    except Exception:  # config 를 못 찾는 실행(도구 단독) — CWD 폴백을 **명시**
        _logger.warning("저장소 루트를 못 찾아 상대 output_path 를 CWD 기준으로 앵커링한다: %s", p)
        root = Path.cwd()
    return root / p


def _normalize_sha256(value: Any) -> Optional[str]:
    """명시 해시 인자 검증: 64자 hex 만 받고 나머지는 None(+경고).

    잘못된 값을 그대로 저장하면 검토 기록의 `expected_sha256` 비교가 영원히 STALE 이 된다.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if len(s) == _SHA256_HEX_LEN and all(c in "0123456789abcdef" for c in s):
        return s
    _logger.warning("output_sha256 인자가 SHA-256 hex 가 아니다 — 미기록(NULL)으로 둔다: %r", value)
    return None


def _measure_output(
    output_path: Any, output_sha256: Any, output_size_bytes: Any = None,
    output_hash_reason: Any = None,
) -> "tuple[Optional[int], Optional[str], Optional[str]]":
    """(크기, 해시, 해시 없음 사유). 실패는 NULL + 사유 + 경고 — 어떤 예외도 기록을 버리게 하지 않는다.

    - 명시 해시가 있으면 크기도 **명시 값**(같은 바이트)만 쓴다. 파일은 열지 않는다(W2).
    - 명시 해시가 없으면 경로 파일을 한 번 읽어 크기·해시를 같이 잰다.
    - NULL 은 "해시 없음" 이지 "빈 산출물" 이 아니다. 사유 어휘: `no_path`(경로도 바이트도 안 넘어옴 — C-4 뒤엔
      라우터가 버퍼를 못 넘긴 것) · `file_missing` · `not_a_file`(디렉터리 등) · `unreadable`(권한·인코딩·NUL 경로 등 그 외 전부)
      · `invalid_arg`(명시 해시가 hex 아님). 리더(R34)는 사유와 무관하게 NULL 을 `hash_unavailable` 로
      잠그되 화면엔 사유를 그대로 낸다.

    ⚠ (R33 리뷰 C1) 좁힌 `except OSError` 는 NUL 바이트 경로의 `ValueError` 를 밖으로 흘려 `record_run` 의
    `return -1`(기록 통째 유실)로 갔다. 여기서는 **어떤 예외든** 사유로 접는다 — 이 함수의 실패는 품질
    기록을 버릴 이유가 아니다.
    """
    explicit = _normalize_sha256(output_sha256)
    if output_sha256 is not None and explicit is None:
        return None, None, "invalid_arg"
    if explicit is not None:
        size = int(output_size_bytes) if isinstance(output_size_bytes, int) and output_size_bytes >= 0 else None
        return size, explicit, None
    if not output_path:
        # 호출부가 사유를 줬으면 그것이 더 정확하다 — `no_path`(경로 없는 문서 = 정상)와
        # `no_bytes`/`bytes_unreadable`(버퍼 배선 실패 = 버그)를 한 토큰으로 접지 않는다(R36 리뷰 W2).
        reason = str(output_hash_reason) if output_hash_reason else "no_path"
        return None, None, reason
    try:
        p = resolve_output_path(output_path)
        if not p.exists():
            _logger.warning("output_path 가 없다(%s) — 해시 미기록(NULL)", p)
            return None, None, "file_missing"
        if not p.is_file():
            _logger.warning("output_path 가 파일이 아니다(%s) — 크기·해시 미기록(NULL)", p)
            return None, None, "not_a_file"
        sha, size = _hash_and_size_of_file(p)
        return size, sha, None
    except Exception as exc:
        _logger.warning("output_path 를 못 읽었다(%r) — 해시 미기록(NULL): %s", output_path, exc)
        return None, None, "unreadable"


def _record_run_impl(
    doc_type: str,
    quality_data: Dict[str, Any],
    **kwargs: Any,
) -> int:
    from workflow.quality.db import get_session, init_db

    db_path = kwargs.get("db_path")
    init_db(db_path)

    # 1. 평가
    doc_type = doc_type.lower().strip()
    if doc_type == "uds":
        metrics = evaluate_uds(quality_data)
    elif doc_type == "sts":
        metrics = evaluate_sts(quality_data)
    elif doc_type == "suts":
        metrics = evaluate_suts(quality_data)
    elif doc_type == "sits":
        metrics = evaluate_sits(quality_data)
    elif doc_type == "swreport":
        metrics = evaluate_swreport(quality_data)
    elif doc_type == "swut":
        _meta = kwargs.get("meta") or {}
        metrics = evaluate_coverage(quality_data, asil=_meta.get("asil_level"))
    elif doc_type == "swit":
        # SwUT 와 **다른 평가기** — SwITCV 는 구문/분기를 O/X 표식으로 덮어쓰므로
        # evaluate_coverage 에 넣으면 재지도 않은 축이 0% 영구 FAIL 이 되고, 정작
        # 정본이 지목하는 미달(Functions/Function Calls)은 어느 지표에도 안 뜬다.
        # evaluate_swit_coverage docstring 참조. SwUTCV 는 실측 구문 커버리지를
        # 내므로(실측 99.45%/1014함수) 위 분기 그대로 둔다.
        _meta = kwargs.get("meta") or {}
        metrics = evaluate_swit_coverage(quality_data, asil=_meta.get("asil_level"))
    elif doc_type in ("sutr", "sitr"):
        # 커버리지 문서(swut/swit)와 **다른 평가기** — 시험 결과 보고서는 커버리지 축을
        # 내지 않으므로 evaluate_coverage 에 넣으면 미측정 축이 0% FAIL 로 둔갑한다.
        metrics = evaluate_test_result(quality_data)
    elif doc_type in ("swutcr", "switcr"):
        # 종합결과서는 **또 다른 평가기**다 — 총 TC 키가 `total` 이 아니라 `total_tcs` 라,
        # 바로 위 evaluate_test_result 에 넣으면 분모가 0 으로 접혀 실행률이 폭주한다
        # (tested 200건 → 20000%). evaluate_comprehensive_result docstring 참조.
        metrics = evaluate_comprehensive_result(quality_data)
    elif doc_type == "swsa":
        metrics = evaluate_swsa(quality_data)
    else:
        _logger.warning("Unknown doc_type: %s, skipping evaluation", doc_type)
        metrics = []

    overall = compute_overall_score(metrics)
    # 판정은 evaluator 단일 출처. 예전엔 여기 인라인 `all(... if gate_pass is not None)` 였고,
    # 필터가 비면 `all([])`=True 라 **검사 0건이 통과로 기록**됐다(위 unknown doc_type 분기가
    # 바로 그 경로 — metrics=[] → gate=True, score=0.0).
    verdict = compute_gate_verdict(metrics)
    gate_pass = verdict["gate_pass"]
    if verdict["reason"] == "no_gated_metric":
        _logger.warning(
            "품질 게이트 항목이 0개다 (doc_type=%s, 지표 %d개) — 판정이 성립하지 않으므로 "
            "통과로 기록하지 않는다(fail-closed). threshold 설정 또는 doc_type 을 확인할 것.",
            doc_type, len(metrics),
        )
    # 게이트 대상 수를 지표로 남긴다 — DB 만 보고도 "0개였다"를 알 수 있어야 한다.
    # threshold=None(비게이트)이라 판정에는 영향이 없다.
    metrics = list(metrics) + [{
        "metric_name": "gated_metric_count",
        "value": float(verdict["gated_count"]),
        "gate_pass": None,
        "threshold": None,
    }]

    # ⚠ **같은 doc_type 인데 호출 경로마다 gate_pass 의 정의가 다르다.**
    # UDS 실측(2026-08-03): `/api/local/uds/generate`(동기)만 `_build_quality_evaluation`
    # 을 통해 quick AND confidence AND report 3중 판정을 기록하고,
    # `local generate-async` · `jenkins generate` · `jenkins generate-async` 세 경로는
    # **bare quick_gate** 를 기록한다. 즉 `quality_summaries.gate_pass` 한 컬럼에 두
    # 정의가 섞여 있는데 그걸 구분할 근거가 DB 어디에도 없었다.
    #
    # 정의를 통일하면 **기록되는 값 자체가 바뀌므로**(과거 run 과 비교 불가) 그건 정책
    # 결정으로 남기고, 여기서는 "이 행이 어느 정의로 나왔는지" 만 additive 로 남긴다.
    # 스키마 변경 없음 — `gated_metric_count` 와 같은 비게이트 지표 행이다.
    # 이름에 정의를 넣어 SQL 한 줄로 분포가 나온다:
    #   select metric_name, count(*) from quality_scores
    #    where metric_name like 'gate_definition:%' group by 1
    _src = str((quality_data or {}).get("gate_source") or "").strip() or "quick_gate_only"
    metrics = list(metrics) + [{
        "metric_name": f"gate_definition:{_src}",
        "value": 1.0,
        "gate_pass": None,
        "threshold": None,
    }]

    # 판정 **사유**도 같은 방식으로 남긴다. 예전엔 `compute_gate_verdict` 가 낸
    # `reason` 을 위 로그 한 줄에 쓰고 버렸다 — 그래서 화면은 "FAIL" 만 알고
    # "왜" 를 알 방법이 DB 어디에도 없었다(`gated_metric_count` 값 0 이 유일한 흔적).
    # 사유가 없을 때(정상 판정)는 행을 만들지 않는다 — 빈 사유를 남기면 소비처가
    # "사유 있음/없음" 을 구분하지 못한다.
    _reason = str(verdict.get("reason") or "").strip()
    if _reason:
        metrics = list(metrics) + [{
            "metric_name": f"gate_reason:{_reason}"[:50],  # 컬럼이 String(50)
            "value": 1.0,
            "gate_pass": None,
            "threshold": None,
        }]

    # 2. DB 기록
    with get_session(db_path) as session:
        # output_size · output_sha256 계산 (R33 C-1: 해시는 명시 인자 우선, 사유는 meta 로)
        output_size, output_sha, sha_reason = _measure_output(
            kwargs.get("output_path"), kwargs.get("output_sha256"), kwargs.get("output_size_bytes"),
            kwargs.get("output_hash_reason"),
        )
        run_meta: Dict[str, Any] = dict(kwargs.get("meta") or {})
        if sha_reason:
            run_meta["output_sha256_reason"] = sha_reason

        run = GenerationRun(
            run_uuid=str(uuid.uuid4()),
            doc_type=doc_type,
            project_root=kwargs.get("project_root"),
            scm_id=kwargs.get("scm_id"),
            target_function=kwargs.get("target_function"),
            status=kwargs.get("status", "success"),
            elapsed_sec=kwargs.get("elapsed_sec"),
            output_path=kwargs.get("output_path"),
            output_size_bytes=output_size,
            output_sha256=output_sha,
            created_by=kwargs.get("created_by"),
            ai_model=kwargs.get("ai_model"),
            error_msg=kwargs.get("error_msg"),
            meta_json=(json.dumps(run_meta, ensure_ascii=False) if run_meta else None),
        )
        session.add(run)
        session.flush()  # run.id 확보

        # QualityScore
        for m in metrics:
            score = QualityScore(
                run_id=run.id,
                metric_name=m["metric_name"],
                value=m["value"],
                gate_pass=m.get("gate_pass"),
                threshold=m.get("threshold"),
            )
            session.add(score)

        # 직전 동일 doc_type run 조회 (delta 계산).
        # id < run.id (삽입 순서 엄밀히 이전) + (created_at, id) 결정적 정렬 →
        # 동시 기록 시 더 새 run 을 prev 로 잘못 고르는 RMW 레이스 차단.
        #
        # ⚠ **프로젝트도 같아야 한다.** 예전엔 doc_type 만 봐서 HDPDM01 swut 의
        # delta 가 바로 앞에 기록된 KJPDS02 swut 대비로 계산됐다 — 화면의 `↑ +12.4`
        # 가 다른 프로젝트와의 차이였다는 뜻이다. scm_id 를 아는 run 끼리만 비교한다.
        # scm_id 가 없는(백필 미상·구 경로) run 은 현행대로 doc_type 만 본다 —
        # 과거 행과의 연속성을 끊지 않기 위함이고, 이 경우 delta 는 여전히 프로젝트를
        # 넘나들 수 있다(그 한계는 scm_id 가 채워지는 만큼 자연히 사라진다).
        # ⚠ **성공 run 만** 비교 대상이다(R37 D-3). 빈 산출물 run 은 요약이 없어서 `prev_run.summary`
        #   가 None 이 되고, 그러면 delta 가 조용히 사라진다 — 점수는 그대로인데 화면의 `↑ +x.x` 만
        #   없어져 "비교할 게 없다" 로 읽힌다. 판정에 못 드는 run 은 비교 기준도 아니다.
        _scm = kwargs.get("scm_id")
        _prev_q = session.query(GenerationRun).filter(
            GenerationRun.doc_type == doc_type,
            GenerationRun.status == "success",
            GenerationRun.id < run.id,
        )
        if _scm:
            _prev_q = _prev_q.filter(GenerationRun.scm_id == _scm)
        prev_run = (
            _prev_q
            .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .first()
        )

        score_delta = None
        prev_run_id = None
        if prev_run and prev_run.summary:
            prev_run_id = prev_run.id
            score_delta = round(overall - prev_run.summary.overall_score, 2)

        # fn_count 추출 (doc_type별 분모)
        fn_count = None
        if doc_type == "uds":
            qg = quality_data.get("quick_gate") or {}
            counts = qg.get("counts") or {}
            fn_count = int(
                counts.get("total_functions")
                or qg.get("total_functions")
                or qg.get("fn_count")
                or 0
            )
        elif doc_type == "swreport":
            fn_count = int(quality_data.get("performed_count") or 0)
        elif doc_type in ("swut", "swit"):
            fn_count = int(
                quality_data.get("functions_with_coverage")
                or quality_data.get("function_rows")
                or 0
            )
        elif doc_type in ("sutr", "sitr"):
            # 시험 결과 보고서의 분모는 함수가 아니라 **TC 수**다. 아래 else 로 흘리면
            # `total_test_cases`(다른 문서군의 키)를 찾다 못 찾고 0 이 되어, 규모가
            # 0 인 실행처럼 보인다.
            fn_count = int(quality_data.get("total") or 0)
        elif doc_type in ("swutcr", "switcr"):
            # 종합결과서도 분모는 TC 수다(위 SUTR/SITR 과 같은 축). 다만 키가 `total` 이
            # 아니라 `total_tcs` 라 위 분기에 합칠 수 없다 — 합치면 0 이 되어 규모가
            # 0 인 실행처럼 보인다.
            fn_count = int(quality_data.get("total_tcs") or 0)
        elif doc_type == "swsa":
            fn_count = int(quality_data.get("his_metric_count") or 0)
        else:
            fn_count = int(quality_data.get("total_test_cases") or 0)

        summary = QualitySummary(
            run_id=run.id,
            overall_score=overall,
            gate_pass=gate_pass,
            score_delta=score_delta,
            prev_run_id=prev_run_id,
            fn_count=fn_count,
        )
        session.add(summary)

        _logger.info(
            "Quality recorded: doc_type=%s run_id=%d score=%.1f gate=%s delta=%s",
            doc_type, run.id, overall, gate_pass, score_delta,
        )
        return run.id
