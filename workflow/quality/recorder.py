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
    ai_model: Optional[str] = None,
    error_msg: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> int:
    """생성 실행 1회를 Quality DB에 기록.

    ``output_sha256`` (R33 C-1): 산출물 바이트의 SHA-256 hex. 명시하면 그 값을 쓰고(BytesIO 응답
    빌더는 경로가 없으니 `sha256_hex(buf.getvalue())` 로 넘긴다 — C-4), 없으면 ``output_path``
    파일을 읽어 계산한다. 둘 다 없으면 NULL(미기록). 이 값이 검토 기록(R34~)의 대상 고정에 쓰인다.
    ``output_size_bytes``: 명시 해시와 **같은 바이트**의 길이(`len(buf.getvalue())`). 명시 해시가 있으면
    크기는 파일에서 재지 않는다 — 한 행의 크기와 해시가 다른 바이트를 가리키면 안 된다(R33 리뷰 W2).
    해시를 못 기록한 사유는 `meta.output_sha256_reason` 에 남는다(`no_path`·`file_missing`·`not_a_file`·
    `unreadable`·`invalid_arg`) — NULL 네 갈래를 한 값으로 접지 않는다(W5).

    Returns:
        run_id (성공 시), -1 (실패 시 -- 예외 전파하지 않음)
    """
    try:
        # 빈 산출물 skip — 0점·FAIL 레코드가 KPI/trend 를 오염하지 않도록.
        # (UDS 0함수는 record_uds_run 에서 선 차단 → doc_type 간 정책 통일)
        _dt = (doc_type or "").lower().strip()
        _qd = quality_data or {}
        _empty = False
        if _dt in ("sts", "suts", "sits"):
            _empty = int(_qd.get("total_test_cases") or 0) <= 0
        elif _dt == "swreport":
            _empty = int(_qd.get("performed_count") or 0) <= 0
        elif _dt in ("swut", "swit", "swutcr", "switcr"):
            # 종합결과서(swutcr/switcr)도 커버리지와 **같은 `total_tcs` 키**를 쓴다
            # (`swut_comprehensive_aggregator.py:1078`). 바로 아래 SUTR/SITR 분기와
            # 헷갈리지 말 것 — 시험 결과 보고서만 `total` 이다.
            _empty = int(_qd.get("total_tcs") or 0) <= 0
        elif _dt in ("sutr", "sitr"):
            # 시험 결과 보고서 summary 는 `total_tcs` 가 아니라 `total` 이다 —
            # 커버리지 키를 그대로 쓰면 **모든 SUTR/SITR 이 빈 산출물로 skip** 된다
            # (기록이 없으니 화면은 "미생성" 을 계속 보여주고, 원인은 보이지 않는다).
            _empty = int(_qd.get("total") or 0) <= 0
        elif _dt == "swsa":
            _empty = not (_qd.get("his_metrics"))
        if _empty:
            _logger.info("%s quality run skipped (empty output)", _dt)
            return -1

        # scm_id 를 명시로 받지 못했으면 `project_root` 에서 해결한다.
        # 호출부 7곳(swut/swit/swreport/swsa/sts/suts/sits)은 이미 프로젝트를 아는
        # 값을 project_root 로 넘기고 있으므로, 판정을 **여기 한 곳**에 두면 그
        # 7곳을 건드리지 않고도 축이 채워지고 앞으로 늘 호출도 자동으로 덮인다.
        # (UDS 5곳은 project_root 자체가 없어 명시 전달이 필요하다 — 라우터 참조.)
        if not scm_id and project_root:
            try:
                from backend.services.scm_registry import resolve_scm_id
                scm_id = resolve_scm_id(project_root)
            except Exception:
                # registry 를 못 읽는 건 품질 기록을 버릴 이유가 아니다. 축만 미상으로
                # 두고 기록은 계속한다 — 다만 침묵은 금지(사후에 왜 NULL 인지 알아야 한다).
                _logger.exception("scm_id 자동 해결 실패 — 미상(NULL)으로 기록한다")
                scm_id = None

        return _record_run_impl(
            doc_type, quality_data,
            project_root=project_root, scm_id=scm_id,
            target_function=target_function,
            status=status, elapsed_sec=elapsed_sec,
            output_path=output_path, output_sha256=output_sha256,
            output_size_bytes=output_size_bytes,
            ai_model=ai_model,
            error_msg=error_msg, meta=meta, db_path=db_path,
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

    함수가 0개(빈 생성)면 기록하지 않는다 — 대시보드 0점 오염 방지.

    Returns:
        run_id (성공 시), -1 (skip/실패 시 -- 예외 전파하지 않음).
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
        qg = data.get("quick_gate") or {}
        total_fn = int(
            (qg.get("counts") or {}).get("total_functions")
            or qg.get("total_functions")
            or 0
        )
        if total_fn <= 0:
            _logger.info("UDS quality run skipped (0 functions)")
            return -1
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
) -> "tuple[Optional[int], Optional[str], Optional[str]]":
    """(크기, 해시, 해시 없음 사유). 실패는 NULL + 사유 + 경고 — 어떤 예외도 기록을 버리게 하지 않는다.

    - 명시 해시가 있으면 크기도 **명시 값**(같은 바이트)만 쓴다. 파일은 열지 않는다(W2).
    - 명시 해시가 없으면 경로 파일을 한 번 읽어 크기·해시를 같이 잰다.
    - NULL 은 "해시 없음" 이지 "빈 산출물" 이 아니다. 사유 어휘: `no_path`(경로 없음 — BytesIO 라우터,
      C-4 전) · `file_missing` · `not_a_file`(디렉터리 등) · `unreadable`(권한·인코딩·NUL 경로 등 그 외 전부)
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
        return None, None, "no_path"
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
        _scm = kwargs.get("scm_id")
        _prev_q = session.query(GenerationRun).filter(
            GenerationRun.doc_type == doc_type,
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
