"""UDS (Unit Design Specification) domain helpers."""
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from time import monotonic, time
from typing import Any, Dict, List, Optional, Tuple

try:
    from fastapi import HTTPException, UploadFile
except ImportError:
    HTTPException = Exception
    UploadFile = None  # type: ignore[assignment,misc]

import config
from backend.helpers.jenkins import _jenkins_exports_dir, _jenkins_logic_dir, _resolve_cached_build_root
from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug
from backend.services.report_parsers import build_report_summary
from backend.state import (
    source_sections_cache as _source_sections_cache,
)
from backend.state import (
    source_sections_cache_lock as _source_sections_cache_lock,
)
from backend.state import (
    uds_view_cache as _uds_view_cache,
)
from backend.state import (
    uds_view_cache_lock as _uds_view_cache_lock,
)
from report_gen.atomic_io import atomic_write_text
from report_gen.gate_report import (
    parse_gate_report,
    parse_scoring_scope,
    to_rate_map,
)
from report_generator import (
    _build_req_map_from_doc_paths,
    build_uds_view_payload,
    generate_asil_related_confidence_report,
    generate_called_calling_accuracy_report,
    generate_swcom_context_diff_report,
    generate_swcom_context_report,
    generate_uds_constraints_report,
    generate_uds_field_quality_gate_report,
    generate_uds_logic_items,
    generate_uds_preview_html,
    generate_uds_requirements_from_docs,
    generate_uds_source_sections,
    generate_uds_validation_report,
)

try:
    from workflow.uds_ai import generate_uds_ai_sections
except ImportError:
    generate_uds_ai_sections = None
try:
    from workflow.rag import _read_text_from_file, get_kb
except ImportError:
    _read_text_from_file = None
    get_kb = None

from backend.helpers.common import (
    _api_logger,
    _compact_symbol_simple,
    _has_meaningful_value,
    _has_real_interface_value,
    _infer_related_id_simple,
    _is_allowed_req_doc,
    _is_trusted_source_for_field,
    _mtime_or_zero,
    _normalize_asil_simple,
    _normalize_symbol_simple,
    _parse_signature_outputs_simple,
    _parse_signature_params_simple,
    _run_report_with_timeout,
)

_logger = logging.getLogger("devops_api")

repo_root = Path(__file__).resolve().parents[2]



def _read_gen_stats(out_path: Path) -> Dict[str, Any]:
    """DOCX 라이터가 남긴 생성 통계 sidecar 를 읽는다.

    ⚠ **왜 파일 경유인가**: 문서 생성은 `subprocess.run([python, "-c", inline, ...])` 로
    돌고 반환값을 버린다. 그래서 in-process 반환/`stats_out` 은 여기 닿지 않는다
    (`report_gen/docx_builder.py::gen_stats_path` 참조).

    부재/파싱 실패는 `{}` 로 낸다 — 호출자가 그걸 **미측정으로 명시**해야 하고
    "문제 없음" 으로 접어선 안 된다.
    """
    try:
        from report_gen.docx_builder import gen_stats_path
        p = gen_stats_path(str(out_path))
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:   # noqa: BLE001 - 통계 부재는 생성 실패가 아니다
        _logger.warning("생성 통계 sidecar 읽기 실패(%s) — 미측정으로 기록한다", e)
        return {}


def _gen_stats_result_fields(out_path: Path) -> Dict[str, Any]:
    """DOCX 생성 충실도를 **API 응답 표면**에 올릴 필드로 만든다.

    ⚠ 자체 감사(2026-07-31)에서 잡힌 격차: 이 수치는 sidecar 와
    `<out>.docx.stage.json` checkpoint 에 기록되는데, **checkpoint 를 읽는 코드가
    저장소 전체에 하나도 없다**(write-only). 로그 경고도 백엔드 로그에만 남는다.
    그래서 "침묵을 없앴다" 는 절반만 사실이었다 — 산출물을 검토하는 사람이 보는
    표면(다른 `*_path` 리포트들과 같은 자리)에는 없었다.

    **보고를 추가하는 것과 보고가 도달하는 것은 다른 문제다.**

    Returns:
        `gen_stats_path`(sidecar 경로) + `gen_stats_summary`(핵심 수치).
        sidecar 가 없으면 `gen_stats_summary=None` — **미측정을 "문제 없음" 과 구분**한다.
    """
    try:
        from report_gen.docx_builder import gen_stats_path
        p = gen_stats_path(str(out_path))
    except Exception as e:   # noqa: BLE001 - 경로 해석 실패는 생성 실패가 아니다
        _logger.warning("생성 통계 경로 해석 실패(%s) — 충실도를 미측정으로 보고한다: %s",
                        type(e).__name__, e)
        return {"gen_stats_path": "", "gen_stats_summary": None}
    stats = _read_gen_stats(out_path)
    if not stats:
        return {"gen_stats_path": "", "gen_stats_summary": None}
    return {
        "gen_stats_path": str(p) if p.exists() else "",
        "gen_stats_summary": {
            "mode": stats.get("mode"),
            "template_source": stats.get("template_source"),
            # ⚠ **명시 화이트리스트다.** 새 축을 `_stats` 에만 넣고 여기 안 더하면
            #    사이드카에는 있는데 API 응답에서 조용히 잘린다 — 이 docstring 이 말하는
            #    "보고를 추가하는 것과 보고가 도달하는 것은 다르다" 가 여기서 재발한다.
            #    (§6 후보 9 의 `template_identity` 가 정확히 그 자리였다.)
            "template_identity": stats.get("template_identity"),
            # 템플릿에서 그대로 가져온 것(표지 블록·이력/참조 표). 신원과 짝으로 읽는다 —
            # 남의 프로젝트 템플릿이면 이 수만큼 남의 내용이 산출물에 실린 것이다.
            "restored_template_blocks": stats.get("restored_template_blocks"),
            "preserved_template_tables": stats.get("preserved_template_tables"),
            "table_rows_recovered": stats.get("table_rows_recovered"),
            "table_rows_blank_trimmed": stats.get("table_rows_blank_trimmed"),
            "swcom_globals_unattributed": stats.get("swcom_globals_unattributed"),
            "payload_functions": stats.get("payload_functions"),
            "matched_functions": stats.get("matched_functions"),
            "match_pct": stats.get("match_pct"),      # 분모 0 이면 None(미측정)
            "unmatched_payload_count": stats.get("unmatched_payload_count"),
            "empty_heading_count": stats.get("empty_heading_count"),
            # **지운** heading — 비워 둔 것과 다른 사실이다. 둘을 같이 봐야
            # "왜 문서가 얇아졌나" 에 답할 수 있다(`keep` 이면 0).
            "dropped_heading_count": stats.get("dropped_heading_count"),
            "unmatched_headings_mode": stats.get("unmatched_headings_mode"),
            "deleted_heading_count": stats.get("deleted_heading_count"),
            "reference_suds": stats.get("reference_suds"),
        },
    }


def _resolve_uds_ai_model() -> str:
    """이 실행이 실제로 쓴 AI 모델명. 모르면 빈 문자열 — 지어내지 않는다.

    출처를 ``workflow.ai.load_oai_config`` 하나로 둔다. ``generate_uds_ai_sections``
    가 내부에서 부르는 바로 그 함수라(``workflow/uds_ai.py`` 의 ``load_oai_config(None)``),
    여기서 설정을 따로 읽으면 DB 에 남는 모델명과 실제로 문서를 만든 모델이 갈릴 수 있다.
    DB 가 답해야 하는 질문은 "무엇으로 설정돼 있었나" 가 아니라 **"무엇이 만들었나"** 다.
    """
    try:
        from workflow.ai import load_oai_config
        cfg = load_oai_config(None)
        if isinstance(cfg, dict):
            return str(cfg.get("model") or "").strip()
    except Exception:
        _logger.debug("UDS ai_model 해석 실패 — 기록은 계속한다", exc_info=True)
    return ""


def _uds_record_kwargs(
    *,
    source_root: Any,
    out_path: Any,
    t0: Optional[float] = None,
    ai_used: bool = False,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """``record_uds_run`` 에 실을 인자를 한 곳에서 만든다.

    UDS 는 생성 진입점이 4개(jenkins 동기/비동기 · local 동기/비동기)라 기록 호출부가
    다섯이다. 인자를 각자 채우면 경로마다 다른 열이 비어 "어느 경로로 만들었나" 가
    섞인다 — 실제로 그래서 ``elapsed_sec``·``ai_model``·``scm_id``·``meta_json`` 이
    **uds 행만 전부 NULL** 이었다(sts/suts/sits 는 셋 다 싣는다).

    ⚠ ``ai_used=False`` 면 ``ai_model`` 을 **싣지 않는다**. jenkins 동기 경로는 AI 섹션
    생성 단계 자체가 없어서, 설정 파일에 적힌 모델명을 기록하면 그 문서를 그 모델이
    만들었다는 거짓이 된다. 근거 없는 값을 채우지 않는 것이 이 저장소의 규약이다.
    """
    kwargs: Dict[str, Any] = {
        "project_root": str(source_root or ""),
        "output_path": str(out_path),
    }
    if t0 is not None:
        kwargs["elapsed_sec"] = max(0.0, time() - float(t0))
    meta: Dict[str, Any] = {"ai_used": bool(ai_used)}
    if ai_used:
        model = _resolve_uds_ai_model()
        if model:
            kwargs["ai_model"] = model
            meta["ai_model"] = model
    if extra_meta:
        meta.update({k: v for k, v in extra_meta.items() if v is not None})
    kwargs["meta"] = meta
    return kwargs


def resolve_registered_uds_template() -> str:
    """local UDS 생성이 쓸 템플릿 — **서버 등록본이 먼저**, 없으면 정본 SUDS.

    우선순위: `config.resolve_uds_template_path()`(admin `/api/config/uds-template`
    저장분 → `UDS_TEMPLATE_PATH` env) → `config.UDS_REF_SUDS_PATH` → 빈 문자열.

    ⚠ **왜 함수로 뺐나**: 예전엔 이 판정이 `local_uds_generate` 핸들러 안에 인라인이었고,
    등록본을 아예 조회하지 않고 곧장 `UDS_REF_SUDS_PATH` 로 폴백했다. 그래서 이 경로에서는
    **관리자가 무엇을 등록하든 매번 정본 SUDS 가 템플릿으로 쓰였다**. jenkins 동기/비동기는
    빈 값을 `None` 으로 넘겨 `generate_uds_docx` 안에서 해석하므로 정상이었다 —
    **local 경로만 어긋나 있었다.**

    인라인으로 두면 가드가 "대입문이 있는가" 같은 **모양**밖에 못 본다. 실제로 그렇게
    썼다가 `if False:` 로 분기를 죽이는 뮤테이션 2건이 통째로 살아남았다. 함수로 빼면
    호출 한 번으로 **결과**를 단언할 수 있다.

    Returns:
        존재가 확인된 경로, 또는 빈 문자열(= 템플릿 없음). 지어내지 않는다.
    """
    try:
        from config import resolve_uds_template_path
        registered = str(resolve_uds_template_path() or "").strip()
    except Exception as exc:   # noqa: BLE001 - 아래 정본 폴백으로 이어간다
        registered = ""
        _logger.warning("등록 템플릿 해석 실패(%s) — 정본 SUDS 로 폴백한다: %s",
                        type(exc).__name__, exc)
    if registered:
        return registered
    try:
        import config
        ref = Path(str(getattr(config, "UDS_REF_SUDS_PATH", "") or ""))
    except Exception:   # noqa: BLE001 - 정본 경로 해석 실패는 "템플릿 없음"
        return ""
    return str(ref) if str(ref) and ref.exists() else ""


def resolve_registered_uds_template_local() -> Optional[str]:
    """등록 템플릿을 **생성기가 직접 열 수 있는 경로**로. 없으면 `None`.

    ⚠ 형제 함수 `resolve_registered_uds_template()` 의 결과를 **그대로 쓰면 안 된다**.
      UDS 생성은 서브프로세스에서 `docx.Document(path)` 로 직접 여니 cloudium worker 가
      닿지 않는다 — `U:` 등록본이면 재시도 3단계가 전부 `PackageNotFoundError` 로 죽는다.
      가정이 아니라 실측이다: 캐시에 남은 2026-08-10·08-11 실패 기록의 마지막 줄이 정확히
      그 모양이고, 경로가 `U:/…/01.SwUDS/(XXXX_SwUDS)…docx` 다.

    ⚠ **왜 또 함수로 빼나**: 형제 함수의 docstring 이 이미 그 사유를 적어 뒀다 — 인라인이면
      가드가 "대입문이 있는가" 같은 모양밖에 못 보고, 실제로 그렇게 뒀다가 분기를 죽이는
      뮤테이션 2건이 통째로 살아남았다. 호출 한 번으로 **결과**를 단언할 수 있어야 한다.

    Returns:
        해석된 로컬 경로, 또는 `None`(등록 없음 / 해석 실패). **원 경로를 흘려보내지
        않는다** — 그러면 같은 실패가 하류에서 나고 사유만 사라진다. 사유는
        `resolve_builder_input` 이 로그에 남긴다.
    """
    registered = resolve_registered_uds_template()
    if not registered:
        return None
    from backend.services.resolver_helpers import resolve_builder_input

    return resolve_builder_input(registered, label="UDS 템플릿")


def _uds_artifact_fidelity(out_path: Any) -> Dict[str, Any]:
    """생성된 DOCX 에 payload 함수가 **실제로 몇 개 들어갔는지** 잰다.

    게이트(`_compute_quick_quality_gate`)는 **payload 만** 본다. 그래서 payload 가
    완벽하면 문서가 비어 있어도 만점이 나온다. 실측(2026-08-24, `reports/quality.sqlite`
    를 sidecar 와 조인):

        run 660·661 : payload 5개 중 문서 반영 **0개**, 빈 heading 419개 → gate PASS · 점수 **100.0**
        run 674     : payload 350개 중 252개(72.0%), 미반영 98개        → gate PASS · 점수 99.5

    ⚠ **생성 성공/실패 판정은 여기서 뒤집지 않는다.** `_run_docx_in_subprocess` 의
    주석이 사유를 대고 있다 — 템플릿이 의도된 부분집합일 수 있어 뒤집으면 대량 오탐이다.
    대신 수치를 게이트와 **같은 자리**(Quality DB)에 참고지표로 나란히 남겨, 만점 옆에
    반영률 0.0 이 보이게 한다. 판정 변경은 베이스라인을 쌓은 뒤 결정할 일이다.

    대조 문구와 "대조 불가" 판정은 `generators/_artifact_check.py` 를 그대로 쓴다 —
    STS/SUTS/SITS 가 쓰는 바로 그 함수다. 규칙을 복제하면 한쪽만 고쳐진다.

    Returns:
        `measured=False` 는 **미측정**이다(sidecar 부재/분모 0). 반영률 0% 와 다르며,
        미측정을 0.0 으로 기록하면 "문서가 비었다" 는 거짓이 DB 에 남는다.

    ⚠ 원시 건수를 `counts` 로 내보내지 않는 것은 의도다 — recorder 는 `counts` 에서
      `total_functions` 하나만 읽으므로 나머지는 **죽은 쓰기**가 된다(뮤테이션 M10 이
      생존해서 드러났다). 건수는 `meta_json` 으로 실제 저장되는 `meta` 에만 싣는다.
    """
    from generators._artifact_check import apply_write_back_check

    stats = _read_gen_stats(Path(str(out_path))) if out_path else {}
    payload_n = stats.get("payload_functions")
    matched_n = stats.get("matched_functions")
    if not isinstance(payload_n, int) or payload_n <= 0 or not isinstance(matched_n, int):
        reason = "sidecar 없음" if not stats else f"분모 없음(payload_functions={payload_n!r})"
        return {"measured": False, "rates": {},
                "meta": {"artifact_fidelity": {"measured": False, "reason": reason}}}

    # expected(생성했다고 주장한 수) ↔ written(파일에서 되읽은 수) 대조.
    validation = apply_write_back_check(
        {"valid": True, "issues": [], "stats": {"payload_functions": matched_n}},
        {"payload_functions": payload_n},
    )
    check = (validation.get("stats") or {}).get("write_back_check") or {}
    return {
        "measured": True,
        "rates": {"artifact_match_fill": round((matched_n / payload_n) * 100.0, 1)},
        "meta": {"artifact_fidelity": {
            "measured": True,
            "payload_functions": payload_n,
            "matched_functions": matched_n,
            "unmatched_payload_count": stats.get("unmatched_payload_count"),
            "empty_heading_count": stats.get("empty_heading_count"),
            # Quality DB 의 meta 로도 간다 — 문서가 얇아진 사유를 기록이 설명해야 한다.
            "dropped_heading_count": stats.get("dropped_heading_count"),
            "unmatched_headings_mode": stats.get("unmatched_headings_mode"),
            "deleted_heading_count": stats.get("deleted_heading_count"),
            "write_back_passed": bool(check.get("passed")),
            "mismatches": list(check.get("mismatches") or []),
        }},
    }


def _with_artifact_fidelity(
    quality_eval: Dict[str, Any], fidelity: Dict[str, Any],
) -> Dict[str, Any]:
    """충실도 rates/counts 를 quick_gate 에 얹은 **사본**을 낸다.

    ⚠ 원본을 제자리 수정하지 않는다 — 호출부(`local.py`)가 같은 dict 를 API 응답으로도
    돌려주므로, 여기서 건드리면 응답 모양이 조용히 바뀐다.

    ⚠ 미측정이면 아무것도 넣지 않는다. 0.0 을 넣으면 `evaluate_uds` 가 그걸 "반영률 0%"
    로 기록해, 재본 적 없는 것이 최악값으로 둔갑한다.
    """
    data = dict(quality_eval or {})
    if not fidelity.get("measured"):
        return data
    inner = data.get("quick_gate")
    if isinstance(inner, dict):
        qg = dict(inner)
        data["quick_gate"] = qg
    else:
        qg = data
    qg["rates"] = {**(qg.get("rates") or {}), **fidelity["rates"]}
    return data


def _record_uds_run(
    quality_eval: Dict[str, Any],
    *,
    source_root: Any,
    out_path: Any,
    t0: Optional[float] = None,
    ai_used: bool = False,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> int:
    """UDS 품질 기록의 **단일 관문** — 다섯 호출부가 전부 여기를 지난다.

    호출부가 `record_uds_run` 을 직접 부르면 산출물 충실도를 다섯 곳에 복제해야 하고,
    그러면 한쪽만 고쳐진다(이 저장소가 반복해 겪은 패턴). 인자 구성은
    `_uds_record_kwargs`, 충실도는 `_uds_artifact_fidelity` 가 맡고 여기서 합친다.
    """
    from workflow.quality.recorder import record_uds_run

    fidelity = _uds_artifact_fidelity(out_path)
    meta = dict(extra_meta or {})
    meta.update(fidelity["meta"])
    return record_uds_run(
        _with_artifact_fidelity(quality_eval, fidelity),
        **_uds_record_kwargs(
            source_root=source_root, out_path=out_path, t0=t0,
            ai_used=ai_used, extra_meta=meta,
        ),
    )


# quick gate 가 **실제로 판정에 쓰는** 축 — `(rates 키, config.UDS_QUALITY_GATE_THRESHOLDS 키)`.
# (R29) `/api/quality/policy` 는 12키 전부 "적용됨 — 판정에 쓰인다" 로 공시했는데 판정식은
#   7키(gate) + 3키(신뢰도) 였고 `global_min`/`static_min` 은 사유 코드에만 쓰였다
#   (`workflow/quality/evaluator.py` 가 의도적으로 제외 — 정상 모듈의 구조적 저평가).
#   판정식과 공시가 같은 튜플을 읽게 해 둘이 갈리지 않게 한다.
QUICK_GATE_AXES: Tuple[Tuple[str, str], ...] = (
    ("called_fill", "called_min"),
    ("calling_fill", "calling_min"),
    ("input_fill", "input_min"),
    ("output_fill", "output_min"),
    ("description_fill", "description_min"),
    ("asil_fill", "asil_min"),
    ("related_fill", "related_min"),
)
CONFIDENCE_GATE_AXES: Tuple[Tuple[str, str], ...] = (
    ("description_trusted_fill", "description_trusted_min"),
    ("asil_trusted_fill", "asil_trusted_min"),
    ("related_trusted_fill", "related_trusted_min"),
)


def _compute_quick_quality_gate(uds_payload: Dict[str, Any]) -> Dict[str, Any]:
    by_name = uds_payload.get("function_details_by_name")
    rows: List[Dict[str, Any]] = []
    if isinstance(by_name, dict):
        for _, info in by_name.items():
            if isinstance(info, dict):
                rows.append(info)
    if not rows:
        detail_map = uds_payload.get("function_details")
        if isinstance(detail_map, dict):
            for _, info in detail_map.items():
                if isinstance(info, dict):
                    rows.append(info)
    _thresholds = getattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {})
    total = len(rows)
    if total <= 0:
        return {
            "gate_pass": False,
            "reason": "no functions",
            "thresholds": dict(_thresholds),
            "rates": {
                "called_fill": 0.0,
                "calling_fill": 0.0,
                "input_fill": 0.0,
                "input_real_fill": 0.0,
                "output_fill": 0.0,
                "output_real_fill": 0.0,
                "global_fill": 0.0,
                "static_fill": 0.0,
                "description_fill": 0.0,
                "asil_fill": 0.0,
                "related_fill": 0.0,
                "description_trusted_fill": 0.0,
                "asil_trusted_fill": 0.0,
                "related_trusted_fill": 0.0,
            },
            "counts": {
                "total_functions": 0,
                "with_called": 0,
                "with_calling": 0,
                "with_input": 0,
                "with_input_real": 0,
                "with_output": 0,
                "with_output_real": 0,
                "with_global": 0,
                "with_static": 0,
                "with_description": 0,
                "with_asil": 0,
                "with_related": 0,
                "with_description_trusted": 0,
                "with_asil_trusted": 0,
                "with_related_trusted": 0,
            },
            "confidence_gate_pass": False,
        }
    # 실질 채움 — `[IN] (none)`(= 파라미터 없음)을 제외한 축. 게이트는 위 축이 그대로
    # 맡고 이건 **참고**다. 두 축을 나란히 둬야 `input_fill 98.3%` 가 "입력이 잘 채워졌다"
    # 로 오독되지 않는다(실측: 그 중 79.4%가 "없음" 표기였고, 전부 진짜 void 함수였다).
    with_input_real = sum(1 for r in rows if _has_real_interface_value(r.get("inputs")))
    with_output_real = sum(1 for r in rows if _has_real_interface_value(r.get("outputs")))
    with_input = sum(1 for r in rows if _has_meaningful_value(r.get("inputs")))
    with_output = sum(1 for r in rows if _has_meaningful_value(r.get("outputs")))
    with_called = sum(1 for r in rows if _has_meaningful_value(r.get("called") or r.get("calls_list")))
    with_calling = sum(1 for r in rows if _has_meaningful_value(r.get("calling")))
    with_global = sum(1 for r in rows if _has_meaningful_value(r.get("globals_global")))
    with_static = sum(1 for r in rows if _has_meaningful_value(r.get("globals_static")))
    with_description = sum(1 for r in rows if _has_meaningful_value(r.get("description")))
    with_asil = sum(1 for r in rows if _has_meaningful_value(r.get("asil")))
    with_related = sum(
        1
        for r in rows
        if _has_meaningful_value(r.get("related") or r.get("related_id") or r.get("related_ids"))
    )
    with_description_trusted = sum(
        1 for r in rows if _has_meaningful_value(r.get("description")) and _is_trusted_source_for_field(r, "description")
    )
    with_asil_trusted = sum(
        1 for r in rows if _has_meaningful_value(r.get("asil")) and _is_trusted_source_for_field(r, "asil")
    )
    with_related_trusted = sum(
        1
        for r in rows
        if _has_meaningful_value(r.get("related") or r.get("related_id") or r.get("related_ids"))
        and _is_trusted_source_for_field(r, "related")
    )
    called_rate = round((with_called / total) * 100.0, 1)
    calling_rate = round((with_calling / total) * 100.0, 1)
    input_real_rate = round((with_input_real / total) * 100.0, 1)
    output_real_rate = round((with_output_real / total) * 100.0, 1)
    input_rate = round((with_input / total) * 100.0, 1)
    output_rate = round((with_output / total) * 100.0, 1)
    global_rate = round((with_global / total) * 100.0, 1)
    static_rate = round((with_static / total) * 100.0, 1)
    description_rate = round((with_description / total) * 100.0, 1)
    asil_rate = round((with_asil / total) * 100.0, 1)
    related_rate = round((with_related / total) * 100.0, 1)
    description_trusted_rate = round((with_description_trusted / total) * 100.0, 1)
    asil_trusted_rate = round((with_asil_trusted / total) * 100.0, 1)
    related_trusted_rate = round((with_related_trusted / total) * 100.0, 1)
    thresholds = dict(_thresholds)
    _rates_by_key = {
        "called_fill": called_rate,
        "calling_fill": calling_rate,
        "input_fill": input_rate,
        "output_fill": output_rate,
        "description_fill": description_rate,
        "asil_fill": asil_rate,
        "related_fill": related_rate,
        "description_trusted_fill": description_trusted_rate,
        "asil_trusted_fill": asil_trusted_rate,
        "related_trusted_fill": related_trusted_rate,
    }
    # 축 목록은 `QUICK_GATE_AXES`/`CONFIDENCE_GATE_AXES` 단일 출처 — `/api/quality/policy` 가
    # 같은 튜플로 "이 키는 판정에 쓰인다" 를 공시한다(R29). `>=` 직접 비교라 임계 0 은 "축 끔".
    # (R32 Q-10) 예전엔 `thresholds[t]` 직접 첨자라 config 표에 키 하나가 없으면 KeyError → 호출부의
    #   non-fatal except 가 삼켜 **품질 기록이 통째로 유실**됐다(가장 조용한 실패). 없는 임계는 그 축을
    #   판정할 수 없다는 뜻이므로 통과로 접지 않고(`all([])` 함정) **fail-closed** 하며, 어느 키가 없었는지
    #   `thresholds_missing` 으로 남긴다. `_quality_threshold` 는 config 폴백까지 본 뒤에야 None 을 낸다.
    #   라이브 config 는 12키 전부 있어 발화 0 — 코드 결함만.
    thresholds_missing: List[str] = sorted(
        {t for _, t in (*QUICK_GATE_AXES, *CONFIDENCE_GATE_AXES) if _quality_threshold(thresholds, t) is None}
    )

    def _axis_pass(rate_key: str, thr_key: str) -> bool:
        thr = _quality_threshold(thresholds, thr_key)
        return thr is not None and _rates_by_key[rate_key] >= thr

    gate_pass = all(_axis_pass(r, t) for r, t in QUICK_GATE_AXES)
    confidence_gate_pass = all(_axis_pass(r, t) for r, t in CONFIDENCE_GATE_AXES)
    if thresholds_missing:
        _logger.warning("UDS quick gate: 임계 없는 축 %s — 해당 판정은 fail-closed", thresholds_missing)
    return {
        "gate_pass": bool(gate_pass),
        "thresholds": thresholds,
        "thresholds_missing": thresholds_missing,
        "rates": {
            "called_fill": called_rate,
            "calling_fill": calling_rate,
            "input_fill": input_rate,
            "input_real_fill": input_real_rate,
            "output_fill": output_rate,
            "output_real_fill": output_real_rate,
            "global_fill": global_rate,
            "static_fill": static_rate,
            "description_fill": description_rate,
            "asil_fill": asil_rate,
            "related_fill": related_rate,
            "description_trusted_fill": description_trusted_rate,
            "asil_trusted_fill": asil_trusted_rate,
            "related_trusted_fill": related_trusted_rate,
        },
        "counts": {
            "total_functions": total,
            "with_called": with_called,
            "with_calling": with_calling,
            "with_input": with_input,
            "with_input_real": with_input_real,
            "with_output": with_output,
            "with_output_real": with_output_real,
            "with_global": with_global,
            "with_static": with_static,
            "with_description": with_description,
            "with_asil": with_asil,
            "with_related": with_related,
            "with_description_trusted": with_description_trusted,
            "with_asil_trusted": with_asil_trusted,
            "with_related_trusted": with_related_trusted,
        },
        "confidence_gate_pass": bool(confidence_gate_pass),
    }


def _enrich_function_quality_fields(uds_payload: Dict[str, Any]) -> None:
    if not isinstance(uds_payload, dict):
        return
    details = uds_payload.get("function_details")
    by_name = uds_payload.get("function_details_by_name")
    call_map = uds_payload.get("call_map")
    if not isinstance(call_map, dict):
        call_map = {}
    reverse: Dict[str, List[str]] = {}
    normalized_call_map: Dict[str, List[str]] = {}
    compact_call_map: Dict[str, List[str]] = {}
    alias_name: Dict[str, str] = {}

    def _register_alias(raw_name: str, preferred: str) -> None:
        n = _normalize_symbol_simple(raw_name)
        c = _compact_symbol_simple(raw_name)
        if n and n not in alias_name:
            alias_name[n] = preferred
        if c and c not in alias_name:
            alias_name[c] = preferred

    if isinstance(details, dict):
        for _, info in details.items():
            if not isinstance(info, dict):
                continue
            nm = str(info.get("name") or "").strip()
            if nm:
                _register_alias(nm, nm)
    if isinstance(by_name, dict):
        for k, info in by_name.items():
            nm = str((info or {}).get("name") or "").strip() if isinstance(info, dict) else ""
            preferred = nm or str(k or "").strip()
            _register_alias(str(k or ""), preferred)
            if nm:
                _register_alias(nm, preferred)
    for caller, callees in call_map.items():
        caller_name = str(caller or "").strip()
        c_norm = _normalize_symbol_simple(caller_name)
        if not c_norm or not isinstance(callees, list):
            continue
        c_comp = _compact_symbol_simple(caller_name)
        normalized_call_map.setdefault(c_norm, [])
        compact_call_map.setdefault(c_comp, [])
        for callee in callees:
            callee_name = str(callee or "").strip()
            n = _normalize_symbol_simple(callee_name)
            c = _compact_symbol_simple(callee_name)
            if not n:
                continue
            if callee_name and callee_name not in normalized_call_map[c_norm]:
                normalized_call_map[c_norm].append(callee_name)
            if callee_name and callee_name not in compact_call_map[c_comp]:
                compact_call_map[c_comp].append(callee_name)
            reverse.setdefault(n, [])
            if caller_name and caller_name not in reverse[n]:
                reverse[n].append(caller_name)
            reverse.setdefault(c, [])
            if caller_name and caller_name not in reverse[c]:
                reverse[c].append(caller_name)

    def _is_blank_value(value: Any) -> bool:
        text = str(value or "").strip()
        return (not text) or text.upper() in {"N/A", "TBD", "-"}

    def _is_blank_list(value: Any) -> bool:
        if not isinstance(value, list):
            return True
        rows = [str(x).strip() for x in value if str(x).strip()]
        return len(rows) == 0

    def _patch_info(info: Dict[str, Any]) -> None:
        if not isinstance(info, dict):
            return
        sig = str(info.get("signature") or info.get("prototype") or "").strip()
        if _is_blank_list(info.get("inputs")) and sig:
            info["inputs"] = _parse_signature_params_simple(sig)
        if _is_blank_list(info.get("outputs")) and sig:
            info["outputs"] = _parse_signature_outputs_simple(sig)
        if _is_blank_value(info.get("called")):
            fn_name = str(info.get("name") or "").strip()
            fn_norm = _normalize_symbol_simple(fn_name)
            fn_comp = _compact_symbol_simple(fn_name)
            callees = list(normalized_call_map.get(fn_norm, [])) + list(compact_call_map.get(fn_comp, []))
            dedup_raw = list(dict.fromkeys([str(v).strip() for v in callees if str(v).strip()]))
            dedup: List[str] = []
            for item in dedup_raw:
                if not item or item == fn_name:
                    continue
                canon = alias_name.get(_normalize_symbol_simple(item)) or alias_name.get(_compact_symbol_simple(item)) or item
                if canon == fn_name:
                    continue
                if canon not in dedup:
                    dedup.append(canon)
            info["called"] = "\n".join(dedup) if dedup else "No callee (leaf function)"
        if _is_blank_value(info.get("calling")):
            fn_name = str(info.get("name") or "").strip()
            fn_norm = _normalize_symbol_simple(fn_name)
            fn_comp = _compact_symbol_simple(fn_name)
            callers = list(reverse.get(fn_norm, [])) + list(reverse.get(fn_comp, []))
            dedup_callers: List[str] = []
            for item in callers:
                s = str(item or "").strip()
                if not s or s == fn_name:
                    continue
                canon = alias_name.get(_normalize_symbol_simple(s)) or alias_name.get(_compact_symbol_simple(s)) or s
                if canon == fn_name:
                    continue
                if canon not in dedup_callers:
                    dedup_callers.append(canon)
            info["calling"] = "\n".join(dedup_callers) if dedup_callers else "No caller (entry/root function)"
        asil_norm = _normalize_asil_simple(info.get("asil"))
        if asil_norm:
            info["asil"] = asil_norm
            # ⚠ 예전엔 여기서 `asil_source` 를 inference → rule 로 **승격**했다.
            # 한 일은 `"asil d"` → `"D"` 정규화뿐인데 근거 등급이 0.60 → 0.75 로 올랐다.
            # **정규화는 새 근거가 아니다.** 출처는 원래 값을 그대로 둔다.
        # ⚠ 예전엔 `else: asil="QM"; asil_source="default"` 였다. 지웠다.
        #   주석은 이걸 "보수적 기본값" 이라 불렀지만 **방향이 거꾸로다** — ISO 26262 에서
        #   QM 은 **최저** 등급(안전 요구 면제)이라, 모르는 것을 QM 으로 적는 건 보수가
        #   아니라 under-classification 이다. 보수는 상향이지 하향이 아니다.
        #   `_normalize_asil_simple` 은 `TBD`/`N/A`/`-`/미인식 문자열을 전부 빈 값으로
        #   접으므로(실측), 여기서 **대입하지 않는 것**이 곧 "없으면 없는 대로, TBD 면
        #   TBD" 를 지키는 길이다. 원래 표기를 그대로 둔다.
        #   ⚠ 이 else 를 되살리면 `requirements.py`·`docx_builder.py`·`function_analyzer.py`
        #   에서 같은 이유로 지운 지어내기가 여기서 되살아난다 — 네 곳은 한 세트다.
        if _is_blank_value(info.get("related") or info.get("related_id") or info.get("related_ids")):
            inferred_related = _infer_related_id_simple(info)
            if inferred_related:
                info["related"] = inferred_related
                info["related_source"] = "rule"
        # ⚠ 예전엔 여기 else 분기가 있었다. 지웠다.
        #   `_normalize_field_source(related_source) == "inference" and _has_trace_token(related)`
        #   → `related_source = "rule"`. **값은 안 바꾸고 라벨만 바꾼다** — 즉 한 일이
        #   아무것도 없는데 근거 등급을 옮겼다.
        #   `_normalize_field_source` 화이트리스트가 6종뿐이라 **밖의 13종이 전부** 이
        #   조건에 걸렸다: `uds`·`swcom`·`sds_match`·`hsis`(0.95)·`rag`·`ai`(0.85)·
        #   `call_graph`(0.80) 은 **하향**, `default`·`unknown`·`generated_doc`(0.30)·
        #   `inference`(0.60)·`module_inherit`(0.70) 은 **근거 없는 상향**.
        #   판정 근거는 `related` 값이 `SwFn_\d+` **모양이라는 것뿐**이다.
        #   `report_gen/validation.py:1391-1393` 이 바로 이 패턴을 지우며
        #   *"ID 가 SwFn_07 모양이라는 건 SRS 를 참조했다는 증거가 아니라 그냥 문자열
        #   모양이다"* 라고 못박았다 — 계층이 다른 게 아니라 같은 규약을 어긴 것이다.
        #   실측: `related_trusted_fill` 0%→100%, 사유코드 `RELATED_ID_TRUST_LOW` 소거.
        #   local sync 경로는 enrich(`routers/local.py:1076`)가 신뢰도 리포트(`:1196`)보다
        #   **먼저** 돌아, 납품 사이드카 `.field_confidence.md` 의 저신뢰 공시가 지워졌다.

    if isinstance(details, dict):
        for _, info in details.items():
            _patch_info(info)
    if isinstance(by_name, dict):
        for _, info in by_name.items():
            _patch_info(info)


def _validate_docx_template_bytes(raw: Optional[bytes]) -> Tuple[bool, str]:
    if not raw:
        return False, "template bytes empty"
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                return False, "word/document.xml missing"
    except Exception as exc:
        return False, f"invalid docx zip: {exc}"
    return True, ""


def _parse_quality_gate_report(path: Optional[Path]) -> Dict[str, Any]:
    """`.quality_gate.md` 사이드카 → 게이트 판정 + 지표율.

    ⚠ 판정은 `report_gen.gate_report` **단일 출처**에 위임한다. 예전엔 이 함수가
    `re.search` 로 **첫 매치**를, `validation.py::_parse_quality_gate_summary` 가 줄 루프로
    **마지막 매치**를 취해 같은 파일에 정반대 값을 냈다(타입도 bool vs 문자열).
    상세와 재현 결과는 `report_gen/gate_report.py` 모듈 docstring 참조.

    `gate_pass=None` 은 **판정 불가**(파일 없음 / 읽기 실패 / `Gate pass:` 부재 또는 2회 이상)
    이지 통과가 아니다 — 아래 `_build_quality_evaluation` 이 그 구분을 유지한다.
    """
    out: Dict[str, Any] = {
        "gate_pass": None, "rates": {}, "gate_pass_status": "absent",
        # (R31, R30 리뷰 편입) 사이드카가 **무엇을** 채점했는지 — 한 실행에 함수 수가 셋(DB `fn_count` ·
        # 사이드카 채점 집합 · 문서 항목)인데 서로 참조가 없었다. 구판 사이드카는 None.
        "scored_entries": None, "document_entries": None, "distinct_scored_functions": None,
    }
    if not path or not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        # 파일은 있는데 못 읽었다 — "리포트가 없다" 와 구분해야 한다(아래 병합이 다르게 취급).
        out["gate_pass_status"] = "read_error"
        return out
    parsed = parse_gate_report(text)
    out["gate_pass"] = parsed.get("gate_pass")
    out["gate_pass_status"] = parsed.get("gate_pass_status")
    out["rates"] = to_rate_map(parsed)
    scope = parse_scoring_scope(text)
    out["scored_entries"] = scope.get("scored_entries")
    out["document_entries"] = scope.get("document_entries")
    out["distinct_scored_functions"] = scope.get("distinct_scored_functions")
    return out


def _parse_accuracy_report(path: Optional[Path]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"called_exact_match": None, "calling_exact_match": None}
    if not path or not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    m_called = re.search(r"Called exact match:.*\(([\d.]+)%\)", text, flags=re.I)
    m_calling = re.search(r"Calling exact match:.*\(([\d.]+)%\)", text, flags=re.I)
    if m_called:
        out["called_exact_match"] = float(m_called.group(1))
    if m_calling:
        out["calling_exact_match"] = float(m_calling.group(1))
    return out


def _quality_threshold(thresholds: Any, key: str) -> Optional[float]:
    """품질 임계값 — **0 은 유효한 값**이다("이 축은 보지 않는다").

    예전엔 호출부마다 `(thresholds or {}).get(key) or <리터럴>` 이었다. `0.0` 이 falsy 라
    운영자가 축을 끄려고 `UDS_CALLED_MIN=0` 을 넣으면 **가장 엄격한 기본값으로 뒤집혔다**.

    실측(2026-09-02): 12개 임계를 전부 0 으로 두면
      · `gate_pass` 는 `rate >= thresholds["called_min"]` 로 **직접 비교**하므로 True
      · 사유 코드는 12건 전부 `*_LOW`
    → **통과 판정인데 사유는 전부 미달**. 판정과 사유가 정면으로 모순됐다.

    기본값은 `config.UDS_QUALITY_GATE_THRESHOLDS` **단일 출처**에서 온다. 리터럴을
    호출부에 복제하면 config 가 바뀔 때 조용히 갈리고, 그 숫자가 사실 행세를 한다.

    Returns:
        `None` 이면 **어디에도 임계가 없다** = 그 축은 판정할 수 없다. 호출부는 사유를
        만들지 않는다 — 없는 임계를 지어내 미달이라고 말하지 않는다.
    """
    src = thresholds if isinstance(thresholds, dict) else {}
    if key in src:
        try:
            return float(src[key])
        except (TypeError, ValueError):
            _logger.warning("품질 임계 %s 가 숫자가 아니다(%r) — config 기본값으로", key, src[key])
    fallback = getattr(config, "UDS_QUALITY_GATE_THRESHOLDS", None) or {}
    try:
        return float(fallback[key])
    except (KeyError, TypeError, ValueError):
        return None


# 사유 코드 ↔ 판정 축. **판정식(`QUICK_GATE_AXES`+`CONFIDENCE_GATE_AXES`)과 같은 튜플에서만 사유를 만든다.**
# (R31 Q-7) 예전엔 `global_min`/`static_min` 도 사유로 나갔는데 그 두 축은 판정에 없다
#   (`workflow/quality/evaluator.py` 가 의도적으로 제외) → **통과 판정에 미달 사유**가 붙었다.
#   그 둘은 아래 `_derive_quality_info_codes` 의 정보 등급으로 내려간다(문구는 그대로).
_REASON_CODE_BY_THRESHOLD_KEY: Dict[str, str] = {
    "called_min": "CALLED_LOW",
    "calling_min": "CALLING_LOW",
    "input_min": "INPUT_PARSE_LOW",
    "output_min": "OUTPUT_PARSE_LOW",
    "description_min": "DESCRIPTION_LOW",
    "asil_min": "ASIL_LOW",
    "related_min": "RELATED_ID_LOW",
    "description_trusted_min": "DESCRIPTION_TRUST_LOW",
    "asil_trusted_min": "ASIL_TRUST_LOW",
    "related_trusted_min": "RELATED_ID_TRUST_LOW",
}
# 정보 등급 — 잰 값은 있지만 **판정에 쓰이지 않는** 축. 사유와 섞이면 "통과인데 미달" 이 된다.
_INFO_CODE_BY_THRESHOLD_KEY: Dict[str, str] = {
    "global_min": "GLOBAL_PARSE_LOW",
    "static_min": "STATIC_PARSE_LOW",
}


def _quality_rate(rates: Any, key: str) -> float:
    try:
        return float((rates or {}).get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _quality_total_functions(quick_gate: Any) -> int:
    if not isinstance(quick_gate, dict):
        return 0
    try:
        return int((quick_gate.get("counts") or {}).get("total_functions") or 0)
    except (TypeError, ValueError):
        return 0


def _derive_quality_reason_codes(quick_gate: Dict[str, Any], template_warning: str = "") -> List[str]:
    """`gate_pass`/`confidence_gate_pass` 가 **False 인 이유**만 낸다.

    계약(R31 Q-7): 사유는 판정 축(`QUICK_GATE_AXES` 7 + `CONFIDENCE_GATE_AXES` 3)에서만 파생한다.
    판정이 True 인데 사유가 붙는 조합은 만들지 않는다 —
      · `NO_FUNCTIONS` 면 **조기 반환**. 예전엔 계속 진행해 `or 0.0` 이 12개 `*_LOW` 를 전부 붙였다
        (함수 0개의 미달률은 측정이 아니다).
      · `CALLING_ZERO` 는 `calling` 축이 **켜져 있을 때만** 사유다(0 < 임계 = 진짜 미달의 특수형).
        축이 꺼져 있으면(임계 0/부재) 판정은 통과이므로 정보 코드로 내려간다.
      · `global`/`static` 은 판정 축이 아니다 → `_derive_quality_info_codes`.
    `TEMPLATE_INVALID` 는 함수 수와 무관한 별도 축이라 조기 반환에도 붙는다.
    """
    if not isinstance(quick_gate, dict):
        quick_gate = {}
    codes: List[str] = []
    if _quality_total_functions(quick_gate) <= 0:
        codes.append("NO_FUNCTIONS")
        if template_warning:
            codes.append("TEMPLATE_INVALID")
        return codes

    rates = quick_gate.get("rates")
    thresholds = quick_gate.get("thresholds")

    def _below(value: float, key: str) -> bool:
        """`gate_pass` 와 **같은 임계·같은 부등호**로 판단한다(`>=` 의 여집합).

        임계가 없으면 사유를 만들지 않는다 — `_quality_threshold` 계약 참조.
        """
        limit = _quality_threshold(thresholds, key)
        return limit is not None and value < limit

    for rate_key, thr_key in (*QUICK_GATE_AXES, *CONFIDENCE_GATE_AXES):
        value = _quality_rate(rates, rate_key)
        if not _below(value, thr_key):
            continue
        if thr_key == "calling_min" and value <= 0.0:
            codes.append("CALLING_ZERO")      # 미달의 특수형 — 파서가 안 돈 신호
        else:
            codes.append(_REASON_CODE_BY_THRESHOLD_KEY[thr_key])
    if template_warning:
        codes.append("TEMPLATE_INVALID")
    return list(dict.fromkeys(codes))


def _derive_quality_info_codes(quick_gate: Dict[str, Any]) -> List[str]:
    """판정에 쓰이지 않는 진단 — 사유가 아니다(통과 판정과 나란히 있어도 모순이 아니다).

    · `GLOBAL_PARSE_LOW`/`STATIC_PARSE_LOW`: config 에 임계는 있지만 판정 축이 아닌 두 축.
    · `CALLING_ZERO`: `calling` 축이 꺼져 있는데(임계 0/부재) 값이 0 — 파서가 안 돈 사실은 남긴다.
    함수 0개면 잰 값이 없으므로 빈 목록(`NO_FUNCTIONS` 가 사유 쪽에 있다).
    """
    if not isinstance(quick_gate, dict) or _quality_total_functions(quick_gate) <= 0:
        return []
    rates = quick_gate.get("rates")
    thresholds = quick_gate.get("thresholds")
    codes: List[str] = []
    calling_limit = _quality_threshold(thresholds, "calling_min")
    if _quality_rate(rates, "calling_fill") <= 0.0 and not (calling_limit is not None and calling_limit > 0):
        codes.append("CALLING_ZERO")
    for rate_key, thr_key in (("global_fill", "global_min"), ("static_fill", "static_min")):
        limit = _quality_threshold(thresholds, thr_key)
        if limit is not None and _quality_rate(rates, rate_key) < limit:
            codes.append(_INFO_CODE_BY_THRESHOLD_KEY[thr_key])
    return list(dict.fromkeys(codes))


def _build_quality_action_hints(reason_codes: List[str]) -> List[str]:
    hints: List[str] = []
    rc = set([str(x or "").strip() for x in (reason_codes or []) if str(x or "").strip()])
    if "CALLED_LOW" in rc:
        hints.append("called 복원 규칙을 강화하세요(call_map 정규화/alias 매칭).")
    if "CALLING_ZERO" in rc or "CALLING_LOW" in rc:
        hints.append("calling 역방향 매핑과 함수명 정규화 규칙을 점검하세요.")
    if "INPUT_PARSE_LOW" in rc:
        hints.append("시그니처 파서를 확장하세요(포인터/배열/함수포인터/typedef).")
    if "OUTPUT_PARSE_LOW" in rc:
        hints.append("출력 판정 규칙(return + non-const pointer/array)을 보강하세요.")
    if "GLOBAL_PARSE_LOW" in rc:
        hints.append("globals_global 추출 규칙과 전역변수 사용 탐지를 보강하세요.")
    if "STATIC_PARSE_LOW" in rc:
        hints.append("globals_static 추출 규칙(정적 변수 매핑)을 점검하세요.")
    if "DESCRIPTION_LOW" in rc:
        hints.append("description 추론/참조 병합 규칙을 점검하세요.")
    if "ASIL_LOW" in rc:
        hints.append("ASIL 매핑(SDS/SRS/주석) 규칙을 강화하세요.")
    if "RELATED_ID_LOW" in rc:
        hints.append("Related ID(SwCom/SwFn) 추적성 링크 규칙을 보강하세요.")
    if "DESCRIPTION_TRUST_LOW" in rc:
        hints.append("description_source의 inference/rule 비중을 줄이고 SDS/SRS/reference 매핑을 늘리세요.")
    if "ASIL_TRUST_LOW" in rc:
        hints.append("ASIL을 기본 QM 추론 대신 SDS/SRS/주석 근거로 매핑하도록 보강하세요.")
    if "RELATED_ID_TRUST_LOW" in rc:
        hints.append("related_source를 inference/rule에서 SRS/SDS/reference로 승격시키는 규칙을 추가하세요.")
    if "TEMPLATE_INVALID" in rc:
        hints.append("DOCX 템플릿 유효성(word/document.xml)을 확인하거나 fallback 사용하세요.")
    if "NO_FUNCTIONS" in rc:
        hints.append("source_root/파서 결과를 확인하고 함수 추출이 되는지 점검하세요.")
    return hints


def _build_quality_evaluation(
    quick_gate: Dict[str, Any],
    quality_gate_path: Optional[Path],
    accuracy_path: Optional[Path],
    *,
    template_warning: str = "",
    doc_only_mode: bool = False,
    quality_gate_error: str = "",
) -> Dict[str, Any]:
    """quick gate ∧ 신뢰도 ∧ 사이드카 리포트 병합 판정.

    `quality_gate_error` — (R32, R31 리뷰 I12) 사이드카 **생성이 실패**(타임아웃/예외)했을 때 호출부가 넘기는
    사유. 예전엔 실패하면 `quality_gate_path=None` 만 넘어와 아래 `absent`(리포트를 안 만든 doc_only 와
    같은 상태)로 접혀 **quick_only 로 강등된 채 PASS** 가 가능했다 — 생성 실패가 판정을 느슨하게 만드는
    fail-open. 사유가 있으면 `report_unreadable` 과 같은 급으로 fail-closed 한다.
    """
    report_gate = _parse_quality_gate_report(quality_gate_path)
    if quality_gate_error and not doc_only_mode and quality_gate_path is None:
        report_gate = dict(report_gate)
        report_gate["gate_pass_status"] = "generation_failed"
        report_gate["error"] = str(quality_gate_error)
    report_acc = _parse_accuracy_report(accuracy_path)
    reason_codes = _derive_quality_reason_codes(quick_gate, template_warning=template_warning)
    action_hints = _build_quality_action_hints(reason_codes)
    # (R31 Q-7) 판정 축 밖의 진단은 사유와 **다른 키**로 — 같은 목록에 섞이면 통과 판정에 미달 사유가 붙는다.
    info_codes = _derive_quality_info_codes(quick_gate)
    info_hints = _build_quality_action_hints(info_codes)
    quick_pass = bool((quick_gate or {}).get("gate_pass"))
    confidence_pass = bool((quick_gate or {}).get("confidence_gate_pass"))
    report_pass = report_gate.get("gate_pass")
    report_status = str(report_gate.get("gate_pass_status") or "absent")
    if doc_only_mode:
        # In doc-only mode, additional reports are intentionally skipped.
        merged_pass = bool(quick_pass and confidence_pass)
        gate_source = "quick_only"
    elif report_status in {"ambiguous", "not_found", "read_error", "generation_failed"}:
        # ⚠ "리포트가 없다" 와 "리포트가 있는데 못 읽었다" 는 다르다.
        #    아래 `absent` 는 리포트를 안 만든 경우라 병합에서 빼는 게 맞지만,
        #    파일이 있는데 판정을 못 뽑은 경우(모호/누락/읽기실패)를 같이 빼면
        #    **본문에 문장 한 줄 넣어 리포트 게이트를 무력화**할 수 있다
        #    (모호 → None → 병합 제외 → quick 만 통과하면 PASS). 옛 코드가 첫 매치를
        #    골라 False 를 내던 것보다 되레 느슨해지므로, 여기서는 fail-closed 한다.
        #    이 저장소 규약: 미측정을 통과로 바꾸지 않는다.
        merged_pass = False
        gate_source = "report_generation_failed" if report_status == "generation_failed" else "report_unreadable"
    elif report_pass is None:
        # status == "absent" — 리포트 자체가 생성되지 않았다(타임아웃·doc_only 등).
        merged_pass = bool(quick_pass and confidence_pass)
        gate_source = "quick_only"
    else:
        merged_pass = bool(quick_pass and confidence_pass and bool(report_pass))
        gate_source = "quick_confidence_and_report"
    policy = {
        "mode": "doc_only" if doc_only_mode else "full",
        "hard_thresholds": quick_gate.get("thresholds") if isinstance(quick_gate, dict) else {},
        "warning_thresholds": getattr(config, "UDS_QUALITY_WARNING_THRESHOLDS", {}),
    }
    return {
        "gate_pass": merged_pass,
        "gate_source": gate_source,
        "quick_gate": quick_gate,
        "confidence_gate_pass": confidence_pass,
        "report_gate": report_gate,
        "accuracy": report_acc,
        "reason_codes": reason_codes,
        "action_hints": action_hints,
        # 판정 밖 진단(global/static 채움률·꺼진 calling 축의 0) — 사유가 아니라 정보다.
        "info_codes": info_codes,
        "info_hints": info_hints,
        "template_warning": template_warning,
        "policy": policy,
    }


def _to_swcom_from_fn(info: Dict[str, Any]) -> str:
    fn_id = str(info.get("id") or "").strip()
    sw = str(info.get("swcom") or "").strip()
    if sw:
        return sw
    m = re.search(r"SwUFn_(\d{2})", fn_id, flags=re.I)
    return f"SwCom_{m.group(1)}" if m else "UNMAPPED"


def _source_sections_disk_cache_path(source_root: str, preprocess: bool = True,
                                     max_files: int = 0, max_items: int = 0) -> Path:
    """디스크 영속 캐시 파일 경로(정규화 source_root+preprocess+상한의 sha1). repo_root(모듈 전역, parents[2]).

    preprocess를 키에 포함 — impact(preprocess=False)와 문서생성(True)의 섹션은 내용이 달라
    같은 소스라도 별도 캐시 파일이어야 교차오염이 없다.

    ⚠ **상한도 키다.** 상한은 `generate_uds_source_sections` 의 산출을 실제로 자르므로
      (읽는 파일 수·분류별 항목 수), 키에서 빠지면 상한을 올려도 옛 상한으로 만든 payload
      가 돌아온다 — 사용자는 게이트에서 값을 올렸는데 문서는 그대로다.
    """
    import hashlib
    _key = (os.path.normcase(str(source_root or "").strip())
            + f"|pp={int(bool(preprocess))}|mf={int(max_files or 0)}|mi={int(max_items or 0)}")
    _h = hashlib.sha1(_key.encode("utf-8", "ignore")).hexdigest()[:16]
    return repo_root / ".devops_pro_cache" / "source_sections" / f"{_h}.json"


# 소스 인덱스(sections) 스키마/파서 버전. 파서가 산출물 구조·의미를 바꾸면 **반드시 올린다** —
# 디스크 캐시 시그니처에 포함되므로, 소스가 그대로여도 이전 캐시가 자동 무효화되고 재파싱된다.
# (v11: 멤버 접근 경로를 **잎까지** 잡는다. `_scan_name_usage` 가 링크를 **한 단계만**
#      물어 `_FSTAT.Bits.CCIF` 가 `_FSTAT.Bits` 로 남았다 — 존재하지 않는 잎이라 정본과
#      영영 안 맞고, 그 자리에 있어야 할 진짜 이름도 못 나온다. 구 캐시엔 잘린 이름이
#      실려 있으므로 무효화하지 않으면 소비처가 계속 그 이름을 본다.
#      (실측 KJPDS02 `.c` 직접 표기 2단 이상은 `PS.Add.DWord`·`t_Line.decel.*` 등 소수 —
#       이 프로젝트의 레지스터 경로는 매크로 확장으로 들어와 이미 잎까지 온다.)
#  v10: `globals_info_map.type` 에 **`const` 한정자가 되살아났다**. tree-sitter 산출 타입엔
#      const 가 없는데 그게 텍스트 스캔 값을 덮어써서 `static const UDSFuncEntry_t
#      s_UdsFuncTbl[…]` 이 그냥 `UDSFuncEntry_t` 로 남아 있었다. const 는 "시험 입력으로
#      설정할 수 없다"는 판정의 유일한 근거이고, 그 판정으로 SUTS 가 const 전역을 뺀다
#      (정본은 const 전역을 입력 0칸·기대 0칸으로 **한 번도 안 적는다**. 우리는 419칸).
#      구 캐시엔 const 가 안 실려 있어 무효화하지 않으면 억제가 조용히 안 걸린다.
#  v9: **다차원 배열이 산출물에서 통째로 빠져 있었다** — 크기가 없는 게 아니라 변수 자체가
#      없었다. `_extract_decl_name_and_type` 의 이름 정규식이 첨자를 `(?:\[[^\]]*\])?` 로
#      **하나만** 허용해, `static U16 u16s_MovgAvgFltBuff[R][C];` 에서 정규식이 통째로
#      실패하고 `_parse_c_declaration_statement` 가 빈 리스트를 냈다(파서 산출 1,157함수
#      어디에도 없음). 파라미터도 같은 결함이라 `S16 t[3][4]` · `U8 data[]` 의 이름이
#      타입 쪽으로 넘어가 식별 불가였다. 정본 실측: 입력 엔트리 첨자 깊이 {0:2748, 1:3138,
#      **2:128**} — 깊이 2 인 128칸(입력 71 · 기대 71 원소)이 여기서 사라졌다. 구 캐시엔
#      그 전역이 **없으므로** 무효화하지 않으면 fix 가 프로덕션에 도달하지 못한다.
#  v8: `globals_info_map` 에 **배열 차원**(`array`: `[60]`)이 붙었다. 정본 SUTS 입력
#      엔트리의 **50.3%(3,023/6,014)** 가 `name[N]` 원소 표기이고, 134개 base 중 120개가
#      모든 unit 에서 같은 개수 = 관찰 첨자가 아니라 **선언 크기**다. 그 크기를 파서가
#      통째로 버리고 있었다(`_extract_decl_name_and_type` 정규식이 `[...]` 를 매치만
#      하고 캡처하지 않음). 구 캐시엔 이 필드가 없으므로 무효화하지 않으면 원소 확장
#      소비처가 붙는 순간 **조용히 아무 일도 안 한다**.
#  v7: 원문 읽기 캡 200KB → 2MB. `Generated_Code/IO_Map.h`(665KB)를 **29.4% 만** 읽고 있어
#      매크로 정의 5,622 중 3,881 · extern 전역 363 중 251 이 사라졌다. 레지스터는 파일
#      뒤쪽에 몰려 있어 `_PTT`(앞)는 살고 `_ADC0CTL`·`_SCI0CR2`·`_CPMUINT`(뒤)는 통째로
#      없었다 — v5·v6 캐시엔 그 전역·매크로가 아예 없으므로 무효화하지 않으면 SFR 입력이
#      계속 0개다.
#  v6: **유령 두 종을 지웠다** — 이건 회수가 아니라 *제거*라 캐시가 안 죽으면 프로덕션엔
#      유령이 그대로 남는다. ①주석 안의 프로토타입을 함수로 만들던 정규식 폴백(Processor
#      Expert `*_GetVal` 3건 — 정본에 없는 함수의 시험 케이스였다) ②`@0x00FF9DF0U` 의 정수
#      접미사가 남아 변수명이 `U` 가 되고, 매크로 토큰화(`123U`→`U`)와 맞물려 **324개 함수**
#      에 전역으로 붙던 것. 추가로 파라미터 앞 설명 주석을 지워 `l_u8 msg_length` 류 23개
#      unit 의 입력이 살아난다.
#  v5: SFR 전역이 살아났다 — ①`extern volatile PTTSTR _PTT @0x000002C0;` 의 이름을 주소
#      리터럴(`x000002C0`)로 읽던 선언 파서 수정 ②매크로 확장형(`#define PTT_PTT3
#      _PTT.Bits.PTT3`)을 멤버 경로로 등록. v4 캐시엔 이 전역들이 없으므로 무효화하지 않으면
#      `g_SysOs_WdiCtrl` 입력이 계속 0개다(= fix 가 프로덕션에 도달 못 함).
#  v4: function_body_snippets 맵 — uds_ai의 AI 2차 description refinement가 읽는 body 앞 400자.
#      생산자가 없어 그 패스가 **한 번도 실행된 적 없는 dead path**였다(uds_ai는 function_details의
#      body_text를 읽는데 어느 detail 생성 지점도 그 키를 넣지 않는다). v3 캐시엔 이 맵이 없어
#      무효화하지 않으면 fix가 프로덕션에 도달하지 못한다.
#  v3: function_collisions 맵 — 동일 이름 다중정의의 **정의 파일 전체 + 최대 ASIL**. AST dedup이
#      두 번째 정의를 파일 경로째 버려서, 그 아래 레이어에서 충돌을 기록하려던 시도(v2)는 항상 빈
#      맵이었다 → dedup 지점에서 기록하도록 이동. v2 캐시는 collisions가 비어 있으므로 무효화 필요.
#  v2: function_details_by_name 다중정의 처리 시도(무효 — 위 참조).
#      버전이 없던 시절엔 소스가 안 바뀌면 구 캐시가 계속 히트해 **파서 fix가 프로덕션에서 무효**였다.)
#  v12: struct_member_arrays — 구조체 **멤버 배열**의 선언 차원(`{타입: {멤버: "[8]"}}`).
#      커밋 018019d 가 `uds_generator` 산출에 이 키를 새로 넣었는데 버전을 안 올려,
#      소스가 안 바뀐 프로젝트에서는 v11 캐시가 계속 히트해 **키가 없는 채로** 나갔다
#      (실측 kjpds02_pv: `struct_member_arrays` 0). SUTS·SITS 둘 다 이 키로 멤버 배열을
#      원소 단위로 펼치므로, 무효화 없이는 두 산출물 모두에서 fix 가 발화하지 않는다
#      — 위 v3/v4 주석이 경고한 것과 **같은 실패의 세 번째**다.
#  v13: `__interrupt void` 의 구분 공백 복원(`source_parser._extract_c_prototypes`).
#      v12 캐시에는 `__interruptvoid` 라는 존재하지 않는 타입이 그대로 박혀 있어
#      (실측: 캐시 6개 파일), 무효화하지 않으면 소스가 안 바뀐 프로젝트에서
#      **파서 fix 가 프로덕션에서 발화하지 않는다** — 위 v3/v4/v12 와 같은 실패.
#  v14: `struct_member_types` 신설 — 멤버 경로 행이 베이스 심볼의 레코드를 이지
#      않게 하는 유일한 출처. v13 캐시엔 이 키가 **아예 없어** 무효화하지 않으면
#      멤버 행이 전부 N/A 로 나간다(키 부재 → 해석 불가 → 빈 레코드). 키를 새로
#      넣고 버전을 안 올려 fix 가 프로덕션에서 죽었던 것이 바로 위 v12 다.
#  v15: `globals_info_map` 에 `reset`/`reset_source` 추가 — Reset Value 열이 이제
#      선언·리셋 함수 대입·정적 저장기간 중 어느 근거인지까지 싣는다. v14 캐시엔 그
#      키가 없어 `_param_reset_text` 가 옛 폴백(`init`)으로 떨어지므로, 무효화하지
#      않으면 소스가 안 바뀐 프로젝트에서 이 판정이 **한 번도 안 돈다**(v12 와 같은 실패).
_SOURCE_SECTIONS_SCHEMA_VERSION = "v15"


def _source_root_signature(source_root: str, max_files: int = 1200) -> Optional[str]:
    """로컬 소스 트리의 (스키마버전, 경로,mtime,size) 시그니처. 로컬 FS만(cloudium은 None → 디스크캐시 미사용).

    소스가 로컬에 있을 때만 유효 — 파일 하나라도 mtime/size가 바뀌면 시그니처가 달라져
    캐시가 무효화된다. cloudium/원격은 로컬 stat이 무의미하므로 None을 반환(디스크캐시 skip).
    파서 스키마 버전도 포함해, 소스 불변이어도 파서가 바뀌면 캐시를 무효화한다.
    """
    import hashlib
    roots = [p.strip() for p in str(source_root or "").replace(";", ",").split(",") if p.strip()]
    if not roots:
        return None
    h = hashlib.sha1()
    count = 0
    for root in roots:
        rp = Path(root).expanduser()
        try:
            if not rp.exists() or not rp.is_dir():
                return None  # 로컬에 없음 → 시그니처 불가(cloudium 등)
        except Exception:
            return None  # U:\ 등 접근 거부(PermissionError) → 로컬 아님 → 디스크캐시 skip
        for dp, _dns, fns in os.walk(rp):
            for fn in fns:
                if not fn.lower().endswith((".c", ".h")):
                    continue
                fpath = Path(dp) / fn
                try:
                    st = fpath.stat()
                except Exception:
                    return None
                h.update(str(fpath).encode("utf-8", "ignore"))
                h.update(str(int(st.st_mtime)).encode())
                h.update(str(st.st_size).encode())
                count += 1
                if count > max_files:
                    break
            if count > max_files:
                break
    return f"{_SOURCE_SECTIONS_SCHEMA_VERSION}:{count}:{h.hexdigest()}"


def _get_source_sections_cached(source_root: str, max_files: Optional[int] = None,
                                preprocess: bool = True,
                                max_items: Optional[int] = None) -> Dict[str, Any]:
    """소스 인덱스 — TTL + (경로,mtime,size) 시그니처 캐시.

    ⚠ `max_files` 는 오래 **시그니처 계산에만** 쓰였고 파싱에는 넘어가지 않았다. 즉
      `/api/code/*` 가 선언한 `max_files` 질의 파라미터는 받아만 두고 아무 일도 하지
      않는 **거짓 통제**였다. 이제 파싱까지 넘기고, 그래서 **캐시 키에도 들어가야** 한다.
    ⚠ 기본값을 숫자로 적지 않는다(예전엔 `1200`). `config` 가 환경변수로 덮이면
      `DEVOPS_UDS_MAX_FILES=77` 인데도 시그니처는 1200개로 계산되어 어긋났다.
    """
    try:
        import config as _cfg_caps
        _def_files = int(getattr(_cfg_caps, "UDS_MAX_SOURCE_FILES", 1200))
        _def_items = int(getattr(_cfg_caps, "UDS_MAX_FUNCTION_ITEMS", 120))
    except Exception:   # noqa: BLE001 - config 부재는 생성기와 같은 폴백으로
        _def_files, _def_items = 1200, 120
    max_files = int(max_files) if isinstance(max_files, int) and max_files > 0 else _def_files
    max_items = int(max_items) if isinstance(max_items, int) and max_items > 0 else _def_items
    # 콤마 구분 복수 경로 지원: 첫 번째 경로로 검증, 전체를 전달
    _first = (source_root or "").split(",")[0].strip()
    # cloudium 모드면 worker IPC resolver로 검증(원격 경로는 로컬 resolve/exists로 못 잡음).
    # local/standalone이면 기존 로컬 검증 그대로.
    try:
        from backend.services.file_resolver import get_resolver as _gr
        _res = _gr()
    except Exception:
        _res = None
    if _res is not None and getattr(_res, "mode", "local") != "local":
        try:
            _ok = bool(_first) and _res.is_dir(_first)
        except Exception:
            _ok = False   # worker 미기동/권한거부 등 → 접근불가로 처리(500 누출 방지 → 400)
    else:
        _root_chk = Path(_first).expanduser().resolve() if _first else Path(".")
        _ok = _root_chk.exists() and _root_chk.is_dir()
    if not _ok:
        raise HTTPException(status_code=400, detail="source_root not found or not directory")
    # 캐시 키: 전체 경로 + preprocess + **상한**(교차오염 방지). 상한이 빠지면
    # `/api/code/call-graph?max_files=200` 의 결과가 문서생성(1200)과 한 칸을 공유한다.
    key = f"{source_root}\x00pp={int(bool(preprocess))}\x00mf={max_files}\x00mi={max_items}"
    now = time()
    # 소스 시그니처(경로,mtime,size,스키마버전)를 먼저 계산 — 인메모리 TTL 캐시도 시그니처로 검증한다.
    # 과거엔 TTL 캐시가 mtime을 안 봐서, 소스를 편집하고 30분 내 재실행하면 **편집 전 함수 집합으로
    # 분석**했다(디스크 캐시는 mtime을 보는데 인메모리가 stale을 먼저 반환). cloudium은 _sig=None →
    # 시그니처 검증 skip(로컬 stat 무의미), 기존 TTL 동작 유지.
    _sig = _source_root_signature(source_root, max_files)
    with _source_sections_cache_lock:
        item = _source_sections_cache.get(key)
        # Lightweight TTL cache to avoid repeated heavy parsing.
        _cache_ttl = getattr(config, "UDS_SOURCE_SECTIONS_CACHE_TTL", 1800)
        _sig_ok = (not _sig) or (item or {}).get("signature") == _sig
        if item and _sig_ok and (now - float(item.get("cached_at") or 0.0) <= _cache_ttl):
            payload = item.get("payload")
            if isinstance(payload, dict):
                return deepcopy(payload)
    import logging as _logging
    _log = _logging.getLogger("uvicorn.error")
    # 디스크 영속 캐시(로컬 소스만): 재기동/크래시 후 첫 요청의 풀 재파싱(수십분)을 회피한다.
    # (경로,mtime,size) 시그니처가 일치하면 파싱 없이 로드. cloudium은 시그니처=None → skip.
    _disk_path = _source_sections_disk_cache_path(source_root, preprocess, max_files, max_items)
    if _sig:
        try:
            if _disk_path.exists():
                _cached = json.loads(_disk_path.read_text(encoding="utf-8"))
                if isinstance(_cached, dict) and _cached.get("signature") == _sig:
                    _payload = _cached.get("payload")
                    if isinstance(_payload, dict):
                        _log.info("[source_sections] Disk cache hit for %s", key)
                        with _source_sections_cache_lock:
                            _source_sections_cache[key] = {"payload": _payload, "cached_at": now, "signature": _sig}
                        return deepcopy(_payload)
        except Exception as _dc_exc:  # noqa: BLE001 — 디스크캐시 실패는 파싱으로 폴백
            _log.debug("source_sections disk cache read failed: %s", _dc_exc)
    _log.info("[source_sections] Parsing started for %s", key)
    t0 = time()
    sections = generate_uds_source_sections(  # 콤마 구분 그대로 전달
        source_root, preprocess=preprocess, max_files=max_files, max_items=max_items)
    elapsed = time() - t0
    _log.info("[source_sections] Parsing finished in %.1fs for %s", elapsed, key)
    with _source_sections_cache_lock:
        _source_sections_cache[key] = {"payload": sections, "cached_at": now, "signature": _sig}
    if _sig:
        try:
            _disk_path.parent.mkdir(parents=True, exist_ok=True)
            _tmp = _disk_path.with_suffix(f".{os.getpid()}.tmp")
            _tmp.write_text(json.dumps({"signature": _sig, "payload": sections}, ensure_ascii=False), encoding="utf-8")
            os.replace(_tmp, _disk_path)  # 원자적 교체
        except Exception as _dc_exc:  # noqa: BLE001 — 디스크캐시 쓰기 실패는 무시(다음에 재파싱)
            _log.debug("source_sections disk cache write failed: %s", _dc_exc)
    return deepcopy(sections)


def _extract_call_graph_payload(
    sections: Dict[str, Any],
    focus_function: str,
    depth: int,
    include_external: bool = False,
) -> Dict[str, Any]:
    call_map = sections.get("call_map") if isinstance(sections.get("call_map"), dict) else {}
    details_by_name = (
        sections.get("function_details_by_name")
        if isinstance(sections.get("function_details_by_name"), dict)
        else {}
    )
    normalized: Dict[str, List[str]] = {}
    reverse: Dict[str, List[str]] = {}
    for caller, vals in call_map.items():
        c = str(caller or "").strip()
        if not c:
            continue
        out_vals: List[str] = []
        if isinstance(vals, list):
            for v in vals:
                name = str(v or "").strip()
                if name:
                    out_vals.append(name)
                    reverse.setdefault(name, []).append(c)
        normalized[c] = out_vals
    focus = str(focus_function or "").strip()
    nodes_set: set[str] = set()
    edges_set: set[Tuple[str, str]] = set()
    if focus and focus in normalized:
        frontier = {focus}
        nodes_set.add(focus)
        for _ in range(max(1, depth)):
            nxt: set[str] = set()
            for cur in frontier:
                for callee in normalized.get(cur, []):
                    nodes_set.add(callee)
                    edges_set.add((cur, callee))
                    nxt.add(callee)
                for caller in reverse.get(cur, []):
                    nodes_set.add(caller)
                    edges_set.add((caller, cur))
                    nxt.add(caller)
            frontier = nxt
            if not frontier:
                break
    else:
        for caller, vals in normalized.items():
            nodes_set.add(caller)
            for callee in vals:
                nodes_set.add(callee)
                edges_set.add((caller, callee))
    nodes = []
    for name in sorted(nodes_set):
        info = details_by_name.get(str(name).lower()) if isinstance(details_by_name, dict) else None
        if not isinstance(info, dict):
            info = {}
        nodes.append(
            {
                "id": name,
                "label": name,
                "swcom": _to_swcom_from_fn(info),
                "id_ref": str(info.get("id") or ""),
            }
        )
    edges = [{"source": s, "target": t} for s, t in sorted(edges_set)]
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "focus": focus,
            "depth": depth,
            "include_external": bool(include_external),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }


def _extract_dependency_map_payload(
    sections: Dict[str, Any],
    level: str = "module",
) -> Dict[str, Any]:
    call_map = sections.get("call_map") if isinstance(sections.get("call_map"), dict) else {}
    details_by_name = (
        sections.get("function_details_by_name")
        if isinstance(sections.get("function_details_by_name"), dict)
        else {}
    )
    level_norm = str(level or "module").strip().lower()
    if level_norm not in {"module", "function"}:
        level_norm = "module"

    def fn_bucket(name: str) -> str:
        info = details_by_name.get(str(name).lower()) if isinstance(details_by_name, dict) else None
        if not isinstance(info, dict):
            return "UNMAPPED"
        return _to_swcom_from_fn(info)

    nodes_set: set[str] = set()
    edges_set: set[Tuple[str, str]] = set()
    for caller, vals in call_map.items():
        c = str(caller or "").strip()
        if not c:
            continue
        c_key = c if level_norm == "function" else fn_bucket(c)
        nodes_set.add(c_key)
        if not isinstance(vals, list):
            continue
        for v in vals:
            callee = str(v or "").strip()
            if not callee:
                continue
            t_key = callee if level_norm == "function" else fn_bucket(callee)
            nodes_set.add(t_key)
            if c_key != t_key:
                edges_set.add((c_key, t_key))
    nodes = [{"id": n, "label": n} for n in sorted(nodes_set)]
    edges = [{"source": s, "target": t} for s, t in sorted(edges_set)]
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {"level": level_norm, "node_count": len(nodes), "edge_count": len(edges)},
    }


def _parse_signature_params(signature: str) -> List[Dict[str, str]]:
    sig = str(signature or "").strip()
    m = re.search(r"\((.*)\)", sig)
    if not m:
        return []
    inner = str(m.group(1) or "").strip()
    if not inner or inner.lower() == "void":
        return []
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    out: List[Dict[str, str]] = []
    for p in parts:
        token = re.sub(r"\s+", " ", p).strip()
        pm = re.match(r"(.+?)\s+([A-Za-z_]\w*(?:\s*\[[^\]]*\])?)$", token)
        if pm:
            out.append({"type": pm.group(1).strip(), "name": pm.group(2).strip()})
        else:
            out.append({"type": token, "name": ""})
    return out


def _build_test_cases_for_signature(function_name: str, signature: str, strategy: str, max_cases: int) -> List[Dict[str, Any]]:
    params = _parse_signature_params(signature)
    if not params:
        return [
            {
                "name": "basic_no_param",
                "inputs": {},
                "expected": "returns without crash",
                "rationale": "No parameter function baseline",
            }
        ]
    strategy_norm = str(strategy or "boundary").strip().lower()
    cases: List[Dict[str, Any]] = []
    for idx, p in enumerate(params, start=1):
        ptype = str(p.get("type") or "").lower()
        pname = str(p.get("name") or f"arg{idx}").strip() or f"arg{idx}"
        if strategy_norm in {"boundary", "stub"}:
            if "*" in ptype:
                seeds = ["NULL", "VALID_PTR"]
            elif "bool" in ptype:
                seeds = [0, 1]
            elif any(t in ptype for t in ["uint", "int", "short", "long", "size_t"]):
                seeds = [0, 1, -1, 2147483647]
            else:
                seeds = [0, 1]
        else:
            seeds = [0, 1]
        for s in seeds:
            cases.append(
                {
                    "name": f"{pname}_case_{len(cases) + 1}",
                    "inputs": {pname: s},
                    "expected": "check return value / output state",
                    "rationale": f"{strategy_norm} input for {pname}",
                }
            )
            if len(cases) >= max_cases:
                break
        if len(cases) >= max_cases:
            break
    if not cases:
        cases.append(
            {
                "name": "basic_case",
                "inputs": {},
                "expected": "check return value",
                "rationale": "fallback",
            }
        )
    return cases[:max_cases]


def _get_uds_view_payload_cached(
    docx_path: Path,
    accuracy_path: Optional[Path] = None,
    quality_gate_path: Optional[Path] = None,
) -> Dict[str, Any]:
    sidecar_path = docx_path.with_suffix(".payload.json")
    key = str(docx_path.resolve())
    stamp = (
        _mtime_or_zero(docx_path),
        _mtime_or_zero(accuracy_path),
        _mtime_or_zero(quality_gate_path),
        _mtime_or_zero(sidecar_path),
    )
    with _uds_view_cache_lock:
        item = _uds_view_cache.get(key)
        if item and item.get("stamp") == stamp and isinstance(item.get("payload"), dict):
            return deepcopy(item["payload"])
    payload = build_uds_view_payload(
        str(docx_path),
        str(accuracy_path) if accuracy_path and accuracy_path.exists() else "",
        str(quality_gate_path) if quality_gate_path and quality_gate_path.exists() else "",
    )
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception:
            sidecar = {}
        sidecar_summary = sidecar.get("summary")
        if isinstance(sidecar_summary, dict):
            payload_summary = payload.get("summary")
            if not isinstance(payload_summary, dict):
                payload_summary = {}
            payload_summary.update(sidecar_summary)
            payload["summary"] = payload_summary
        details = sidecar.get("function_details")
        if isinstance(details, dict):
            by_id: Dict[str, Dict[str, Any]] = {}
            by_name: Dict[str, Dict[str, Any]] = {}
            for _, info in details.items():
                if not isinstance(info, dict):
                    continue
                fid = str(info.get("id") or "").strip()
                name = str(info.get("name") or "").strip().lower()
                if fid:
                    by_id[fid] = info
                if name:
                    by_name[name] = info
            for fn in payload.get("functions", []) or []:
                if not isinstance(fn, dict):
                    continue
                fid = str(fn.get("id") or "").strip()
                name = str(fn.get("name") or "").strip().lower()
                src = by_id.get(fid) or by_name.get(name)
                if not isinstance(src, dict):
                    continue
                for field in (
                    "sds_match_key",
                    "sds_match_mode",
                    "sds_match_scope",
                    "mapping_confidence",
                    "asil_source",
                    "related_source",
                    "description_source",
                ):
                    value = src.get(field)
                    if value not in (None, ""):
                        fn[field] = value
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        payload["summary"] = summary
    if not isinstance(summary.get("mapping"), dict):
        summary["mapping"] = _compute_uds_mapping_summary(payload.get("functions") or [])
    with _uds_view_cache_lock:
        _uds_view_cache[key] = {
            "stamp": stamp,
            "payload": payload,
            "cached_at": time(),
        }
    return deepcopy(payload)


def _slice_page(rows: List[Dict[str, Any]], page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    p = max(1, int(page or 1))
    size = max(1, min(500, int(page_size or 50)))
    total = len(rows)
    start = (p - 1) * size
    end = start + size
    return rows[start:end], total


def _compute_uds_mapping_summary(rows: Any) -> Dict[str, Any]:
    items = []
    if isinstance(rows, dict):
        items = [v for v in rows.values() if isinstance(v, dict)]
    elif isinstance(rows, list):
        items = [v for v in rows if isinstance(v, dict)]
    total = len(items)
    direct = fallback = other = unmapped = 0
    residual_tbd = []
    for info in items:
        scope = str(info.get("sds_match_scope") or "").strip().lower()
        if scope == "function":
            direct += 1
        elif scope == "swcom":
            fallback += 1
        elif scope:
            other += 1
        else:
            unmapped += 1
        asil = str(info.get("asil") or "").strip().upper()
        if asil == "TBD":
            related = str(info.get("related") or "").strip().upper()
            has_related = bool(related and related not in {"TBD", "N/A", "-"})
            match_key = str(info.get("sds_match_key") or "").strip()
            if not match_key and not has_related:
                reason = "No SDS match and no related requirement"
            elif not match_key:
                reason = "No SDS match"
            elif not has_related:
                reason = "No related requirement"
            else:
                reason = "Mapping pending"
            residual_tbd.append(
                {
                    "id": str(info.get("id") or "").strip(),
                    "name": str(info.get("name") or "").strip(),
                    "sds_match_key": match_key,
                    "sds_match_mode": str(info.get("sds_match_mode") or "").strip(),
                    "sds_match_scope": str(info.get("sds_match_scope") or "").strip(),
                    "reason": reason,
                }
            )
    return {
        "total": total,
        "direct": direct,
        "fallback": fallback,
        "other": other,
        "unmapped": unmapped,
        "residual_tbd_count": len(residual_tbd),
        "residual_tbd_rows": residual_tbd[:20],
    }


def _write_residual_tbd_report(out_path: Path, summary_mapping: Dict[str, Any]) -> Optional[Path]:
    try:
        if not isinstance(summary_mapping, dict):
            return None
        rows = summary_mapping.get("residual_tbd_rows") or []
        if not rows:
            return None
        report_path = out_path.with_suffix(".residual_tbd.md")
        lines = [
            "# Residual TBD Trace Report",
            "",
            f"- Docx: `{out_path}`",
            f"- Residual TBD Count: `{summary_mapping.get('residual_tbd_count', 0)}`",
            "",
            "## Rows",
            "",
        ]
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append(f"- `{row.get('id') or '-'}` {row.get('name') or '-'}")
            lines.append(f"  - reason: `{row.get('reason') or '-'}`")
            lines.append(f"  - sds_match_key: `{row.get('sds_match_key') or '-'}`")
            lines.append(f"  - sds_match_mode: `{row.get('sds_match_mode') or '-'}`")
            lines.append(f"  - sds_match_scope: `{row.get('sds_match_scope') or '-'}`")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path
    except Exception:
        return None


def _apply_uds_view_filters(
    payload: Dict[str, Any],
    *,
    q: str = "",
    swcom: str = "all",
    asil: str = "all",
    trace_q: str = "",
    page: int = 1,
    page_size: int = 50,
    trace_page: int = 1,
    trace_page_size: int = 100,
) -> Dict[str, Any]:
    functions = payload.get("functions") if isinstance(payload.get("functions"), list) else []
    traceability = payload.get("traceability") if isinstance(payload.get("traceability"), list) else []
    q_l = str(q or "").strip().lower()
    swcom_l = str(swcom or "all").strip().lower()
    asil_l = str(asil or "all").strip().lower()
    trace_q_l = str(trace_q or "").strip().lower()

    filtered_functions: List[Dict[str, Any]] = []
    for fn in functions:
        if not isinstance(fn, dict):
            continue
        fn_swcom = str(fn.get("swcom") or "").strip().lower()
        fn_asil = str(fn.get("asil") or "").strip().lower()
        if swcom_l != "all" and fn_swcom != swcom_l:
            continue
        if asil_l != "all" and fn_asil != asil_l:
            continue
        if q_l:
            blob = " ".join(
                [
                    str(fn.get("id") or ""),
                    str(fn.get("name") or ""),
                    str(fn.get("prototype") or ""),
                    str(fn.get("description") or ""),
                ]
            ).lower()
            if q_l not in blob:
                continue
        filtered_functions.append(fn)
    paged_functions, fn_total = _slice_page(filtered_functions, page, page_size)

    filtered_trace: List[Dict[str, Any]] = []
    for row in traceability:
        if not isinstance(row, dict):
            continue
        row_swcom = str(row.get("swcom") or "").strip().lower()
        if swcom_l != "all" and row_swcom != swcom_l:
            continue
        if trace_q_l:
            blob = " ".join(
                [
                    str(row.get("requirement_id") or ""),
                    str(row.get("function_id") or ""),
                    str(row.get("function_name") or ""),
                    str(row.get("swcom") or ""),
                ]
            ).lower()
            if trace_q_l not in blob:
                continue
        filtered_trace.append(row)
    paged_trace, trace_total = _slice_page(filtered_trace, trace_page, trace_page_size)

    out = dict(payload)
    out["functions"] = paged_functions
    out["traceability"] = paged_trace
    out["meta"] = {
        "functions_total": fn_total,
        "traceability_total": trace_total,
        "page": max(1, int(page or 1)),
        "page_size": max(1, min(500, int(page_size or 50))),
        "trace_page": max(1, int(trace_page or 1)),
        "trace_page_size": max(1, min(500, int(trace_page_size or 100))),
        "server_filtered": True,
    }
    return out


def _generate_docx_with_retry(
    tpl: Optional[str],
    uds_payload: Dict[str, Any],
    out_path: Path,
    retries: int = 3,
) -> None:
    def _build_docx_retry_payload(base_payload: Dict[str, Any], level: int) -> Dict[str, Any]:
        payload = deepcopy(base_payload or {})
        if level >= 1:
            payload.pop("ai_sections", None)
            payload["logic_max_children"] = min(int(payload.get("logic_max_children") or 3), 2)
            payload["logic_max_grandchildren"] = min(int(payload.get("logic_max_grandchildren") or 2), 1)
            payload["logic_max_depth"] = min(int(payload.get("logic_max_depth") or 3), 2)
        if level >= 2:
            payload["logic_diagrams"] = []
            payload["software_unit_design"] = str(payload.get("software_unit_design") or "")[:60000]
            payload["requirements"] = str(payload.get("requirements") or "")[:80000]
        return payload

    def _run_docx_in_subprocess(
        stage_payload: Dict[str, Any],
        *,
        stage: str,
        timeout_seconds: int,
    ) -> Tuple[bool, str]:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="uds_payload_", suffix=".json", dir=str(out_path.parent))
        payload_file = Path(temp_path)
        try:
            os.close(fd)
        except Exception:
            pass
        # ⚠ 접미사는 **읽는 쪽과 같은 상수**를 쓴다. 준비 게이트가 이 파일을 글로브로
        #   찾아 직전 생성의 결말을 공시하는데(`docgen_last_run`), 리터럴이 양쪽에 있으면
        #   한쪽만 바뀌었을 때 아무것도 못 찾고 그건 "생성한 적 없음" 과 구분되지 않는다.
        from backend.services.docgen_last_run import CHECKPOINT_SUFFIX
        checkpoint = out_path.with_suffix(CHECKPOINT_SUFFIX)
        # ⚠ 체크포인트는 단계마다 **덮어써진다**. 시작 시각을 `started` 레코드에만 두면
        #   종결 레코드가 그것을 지워, 이 생성이 **얼마나 걸렸는지** 를 되살릴 방법이
        #   없어진다(실측: 남아 있는 기록 3건 전부 `ended_at` 만 있다). 그래서 시작
        #   시각과 타이머를 여기서 한 번 잡고 네 갈래 종결이 **전부** 옮겨 싣는다.
        _started_at = datetime.now().isoformat(timespec="seconds")
        _t0 = monotonic()

        def _finish(record: Dict[str, Any]) -> Dict[str, Any]:
            """종결 레코드 공통 필드 — 시작·종료·소요·그 단계의 예산.

            ⚠ `elapsed_seconds` 는 **이 단계 하나**의 소요다. 앞 단계들의 소요는 덮어써져
              원래부터 남지 않으므로 사다리 전체의 합이 아니다(합으로 읽히면 거짓이다).
            """
            record["started_at"] = _started_at
            record["ended_at"] = datetime.now().isoformat(timespec="seconds")
            record["elapsed_seconds"] = round(monotonic() - _t0, 1)
            record["timeout_seconds"] = timeout_seconds
            return record

        try:
            payload_file.write_text(json.dumps(stage_payload, ensure_ascii=False), encoding="utf-8")
            checkpoint.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "started",
                        "timeout_seconds": timeout_seconds,
                        "started_at": _started_at,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            inline = (
                "import json,sys,report_generator as rg;"
                "tpl=sys.argv[1] or None; p=sys.argv[2]; out=sys.argv[3];"
                "payload=json.loads(open(p,'r',encoding='utf-8').read());"
                "ai_cfg=payload.pop('_gen_ai_config',None);"
                "rg.generate_uds_docx(tpl,payload,out,ai_cfg);"
                "print('OK')"
            )
            run = subprocess.run(
                [sys.executable, "-c", inline, str(tpl or ""), str(payload_file), str(out_path)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            if run.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                # ⚠ 위 판정은 "파일이 있고 0바이트가 아님" 뿐이다. 이 라이터는 **템플릿
                # 주도**라 payload 함수가 템플릿에 없으면 문서에 안 들어가는데, 그래도
                # returncode 0 + 파일 존재는 성립한다. 실측(HDPDM01): payload 432개 중
                # 95개(22.0%)가 미반영이고 빈 heading 74개인 문서가 "success" 였다.
                # 성공/실패 판정은 **바꾸지 않는다**(템플릿이 의도된 부분집합일 수 있어
                # 뒤집으면 대량 오탐) — 대신 수치를 checkpoint 에 실어 침묵을 없앤다.
                gen_stats = _read_gen_stats(out_path)
                record: Dict[str, Any] = _finish({
                    "stage": stage,
                    "status": "success",
                    "stdout_tail": (run.stdout or "")[-1000:],
                })
                if gen_stats:
                    record["gen_stats"] = gen_stats
                    unmatched = gen_stats.get("unmatched_payload_count")
                    empty = gen_stats.get("empty_heading_count")
                    if (isinstance(unmatched, int) and unmatched > 0) or (
                        isinstance(empty, int) and empty > 0
                    ):
                        total = gen_stats.get("payload_functions") or 0
                        record["warnings"] = [
                            f"payload 함수 {total}개 중 {gen_stats.get('matched_functions')}개 반영"
                            f"(반영률 {gen_stats.get('match_pct')}%). 템플릿에 대응 heading 이 없어"
                            f" 문서에 반영되지 않은 함수 {unmatched}개, 내용 없이 남은 heading"
                            f" {empty}개(삭제 표기 {gen_stats.get('deleted_heading_count')}개는 제외)."
                        ]
                        _logger.warning("UDS DOCX 생성 충실도: %s", record["warnings"][0])
                else:
                    # sidecar 부재 = 미측정. "문제 없음" 과 구분해 명시한다.
                    record["gen_stats_missing"] = True
                checkpoint.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
                )
                return True, ""
            err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-2000:]
            checkpoint.write_text(
                json.dumps(
                    _finish({
                        "stage": stage,
                        "status": "failed",
                        "returncode": run.returncode,
                        "error_tail": err,
                    }),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return False, err or f"returncode={run.returncode}"
        except subprocess.TimeoutExpired:
            checkpoint.write_text(
                json.dumps(
                    _finish({
                        "stage": stage,
                        "status": "timeout",
                    }),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return False, f"timeout({timeout_seconds}s)"
        except Exception as exc:
            checkpoint.write_text(
                json.dumps(
                    _finish({
                        "stage": stage,
                        "status": "exception",
                        "error": str(exc),
                    }),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return False, str(exc)
        finally:
            try:
                payload_file.unlink(missing_ok=True)
            except Exception:
                pass

    # ⚠ 단계 목록을 여기 복제하지 않는다. 예전엔 `getattr(config, …, [("full",0,2400),…])`
    #   로 리터럴 폴백을 달아 뒀는데, config 의 실제 예산은 **7200/3600/1800** 이라
    #   3배 차이였다. 죽은 폴백이 문서·기억에 옮겨 적히면서 "full 예산 2400초" 라는
    #   틀린 사실이 돌아다녔다(라운드 12 착수 실측에서 발견). 준비 게이트도 같은
    #   `config` 를 직독한다(`docgen_last_run.retry_stage_budget`).
    stages = list(getattr(config, "UDS_DOCX_RETRY_STAGES", None) or ())
    if not stages:
        raise RuntimeError(
            "config.UDS_DOCX_RETRY_STAGES 가 비어 있다 — 재시도 예산을 지어내지 않는다."
        )
    max_retries = max(1, int(retries))
    selected = stages[:max_retries] if max_retries <= len(stages) else stages
    last_error = ""
    errors_log: List[str] = []
    for stage, level, timeout_sec in selected:
        _api_logger.info("[UDS_DOCX] stage=%s level=%s timeout=%ds start", stage, level, timeout_sec)
        ok, err = _run_docx_in_subprocess(
            _build_docx_retry_payload(uds_payload, level),
            stage=stage,
            timeout_seconds=timeout_sec,
        )
        if ok:
            _api_logger.info("[UDS_DOCX] stage=%s SUCCESS", stage)
            return
        last_error = err
        errors_log.append(f"[stage={stage}] {err[:500]}")
        _api_logger.error("[UDS_DOCX] stage=%s FAILED: %s", stage, err[:300])
    full_log = "\n".join(errors_log)
    raise RuntimeError(f"DOCX generation failed after {len(selected)} retries:\n{full_log}")


def _run_impact_analysis_for_uds(source_root_path: Optional[Path], changed_files_raw: str) -> Optional[Path]:
    changed_files = str(changed_files_raw or "").strip()
    if not source_root_path or not source_root_path.exists() or not changed_files:
        return None
    out_dir = repo_root / "reports" / "uds"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "impact_analysis.md"
    cmd = [
        sys.executable,
        str(repo_root / "tools" / "impact_analysis.py"),
        "--source-root",
        str(source_root_path),
        "--changed",
        changed_files,
        "--out",
        str(out_path),
    ]
    try:
        run = subprocess.run(
            cmd,
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if run.returncode == 0 and out_path.exists():
            return out_path
        err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-4000:]
    except Exception as exc:
        err = str(exc)
    # Always emit a report file for changed-unit runs so downstream steps
    # can rely on a stable artifact path.
    lines = [
        "# Impact Analysis Report",
        "",
        f"- Source root: `{source_root_path}`",
        f"- Changed files: `{changed_files}`",
        "- Status: `failed`",
        "",
        "## Error",
        f"- {err or 'unknown error'}",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _uds_generate_from_paths(
    *,
    job_url: str,
    cache_root: str,
    build_selector: str,
    template_path: str,
    source_root: str,
    source_only: bool,
    req_file_paths: List[Path],
    note_file_paths: List[Path],
    logic_file_paths: List[Path],
    req_paths: List[str],
    logic_source: str = "",
    logic_max_children: Optional[int] = None,
    logic_max_grandchildren: Optional[int] = None,
    logic_max_depth: Optional[int] = None,
    globals_format_order: str = "",
    globals_format_sep: str = "",
    globals_format_with_labels: bool = True,
    ai_enable: bool = False,
    ai_example_text: str = "",
    ai_detailed: bool = True,
    rag_top_k: Optional[int] = None,
    rag_categories: Optional[List[str]] = None,
    progress_cb: Optional[Any] = None,
    component_map: Optional[Dict[str, Dict[str, str]]] = None,
    # 생성 상한 — 준비 게이트의 `cap_max_source_files`/`cap_max_items_per_category` 가
    # 이 두 값으로 내려온다. `None` 이면 `config` 기본값(환경변수로 덮임)이 쓰인다.
    max_source_files: Optional[int] = None,
    max_items_per_category: Optional[int] = None,
    # 정본에만 있는 남의 함수 절을 남길지 지울지 — 기본은 `""`(= keep, 종전 동작).
    # 정규화는 `docx_builder.normalize_unmatched_headings` 단일 출처가 한다.
    unmatched_headings: str = "",
) -> Dict[str, Any]:
    def _progress(stage: str, percent: int, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if not progress_cb:
            return
        payload = {"stage": stage, "percent": percent, "message": message}
        if extra:
            payload.update(extra)
        progress_cb(stage, payload)

    # 소요 시간은 **함수 진입부터** 잰다 — sts/suts/sits 와 같은 축이라야 비교가 된다.
    # ⚠ 이 모듈은 `from time import time` 이라 `time.time()` 이 아니라 `time()` 이다.
    _t0 = time()
    build_root = _resolve_cached_build_root(job_url, cache_root, build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    summary = build_report_summary(report_dir, project_root=repo_root)

    _progress("notes", 10, "추가 문서 파싱")
    notes: List[str] = []
    for p in note_file_paths:
        try:
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if text:
            notes.append(text.strip())

    _progress("requirements", 25, "요구사항 문서 파싱")
    req_texts: List[str] = []
    req_map: Dict[str, Any] = {}
    req_doc_paths: List[str] = []
    for p in req_file_paths:
        try:
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if p.suffix.lower() == ".docx":
            req_doc_paths.append(str(p))
        if text:
            req_texts.append(text.strip())
    for path_str in req_paths:
        try:
            p = Path(path_str).expanduser().resolve()
            if not p.exists() or not p.is_file():
                continue
            if not _is_allowed_req_doc(p):
                continue
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if text:
            req_texts.append(text.strip())
            if p.suffix.lower() == ".docx":
                req_doc_paths.append(str(p))

    _progress("source", 45, "소스/섹션 분석")
    jenkins_meta = summary.get("jenkins") if isinstance(summary, dict) else {}
    if not isinstance(jenkins_meta, dict):
        jenkins_meta = {}
    summary_text = summary.get("summary_text", "") if isinstance(summary, dict) else ""
    source_sections: Dict[str, str] = {}
    source_root_path = Path(source_root).resolve() if source_root else None
    if source_root_path and source_root_path.exists():
        source_sections = generate_uds_source_sections(
            str(source_root_path),
            component_map=component_map if component_map else None,
            max_files=max_source_files,
            max_items=max_items_per_category,
        )

    _progress("requirements_build", 60, "요구사항 정리")
    req_from_docs = generate_uds_requirements_from_docs(req_texts) if req_texts else ""
    req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}

    _progress("logic", 70, "Logic Diagram 첨부")
    logic_items: List[Dict[str, Any]] = []
    if logic_file_paths:
        logic_dir = _jenkins_logic_dir(cache_root)
        logic_dir.mkdir(parents=True, exist_ok=True)
        ts_logic = datetime.now().strftime("%Y%m%d_%H%M%S")
        for p in logic_file_paths:
            if not p or not p.exists():
                continue
            suffix = p.suffix.lower() or ".png"
            safe_name = "".join(c for c in p.stem if c.isalnum() or c in ("-", "_"))
            # ⚠ 라우터 쪽 쌍둥이(`backend/routers/jenkins.py` 의 logic 업로드)와 **같은
            #   이름 규칙**이다. 유일성이 업로드 파일명에만 걸려 있어 같은 초에 같은
            #   이름이면 덮어쓴다. `url` 은 **선점된 이름**으로 만든다.
            from backend.services.output_paths import reserve_unique_path
            out_path = reserve_unique_path(logic_dir / f"logic_{safe_name}_{ts_logic}{suffix}")
            out_name = out_path.name
            try:
                out_path.write_bytes(p.read_bytes())
            except Exception:
                continue
            logic_items.append(
                {
                    "title": p.name,
                    "path": str(out_path),
                    "url": f"/api/jenkins/uds/logic?job_url={job_url}&cache_root={cache_root}&filename={out_name}",
                }
            )
    if not logic_items and logic_source:
        try:
            logic_items = generate_uds_logic_items(
                req_texts,
                logic_source,
                source_root=str(source_root_path) if source_root_path else "",
            )
        except Exception:
            logic_items = []

    ai_sections = None
    if ai_enable:
        _progress("ai", 80, "AI 섹션 생성")
        try:
            rag_snippets: List[Dict[str, Any]] = []
            try:
                report_dir = _detect_reports_dir(build_root)
                kb = get_kb(report_dir)
                rag_query = " ".join(req_texts).strip()[:2000]
                if not rag_query:
                    rag_query = (source_sections.get("overview", "") or "").strip()[:2000]
                if rag_query:
                    # ⚠ 상한은 `workflow.ai.clamp_rag_top_k` 단일 출처(§6 후보 17).
                    #    사용자 Form 입력이 그대로 프롬프트 크기가 되는 유일한 축이다.
                    from workflow.ai import clamp_rag_top_k
                    use_top_k = clamp_rag_top_k(
                        rag_top_k if rag_top_k and rag_top_k > 0 else int(
                            getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)
                        ),
                        default=3,
                    )
                    use_categories = [str(c).strip() for c in (rag_categories or []) if str(c).strip()]
                    if not use_categories:
                        use_categories = ["uds", "requirements", "code", "vectorcast"]
                    rag_rows = kb.search(
                        rag_query,
                        top_k=use_top_k,
                        categories=use_categories,
                    )
                    for row in rag_rows:
                        rag_snippets.append(
                            {
                                "title": row.get("error_raw") or "",
                                "category": row.get("category") or "",
                                "source_type": "rag",
                                "source_file": row.get("source_file") or "",
                                "excerpt": str(row.get("context") or row.get("fix") or "")[:1200],
                                "score": row.get("score"),
                            }
                        )
            except Exception:
                rag_snippets = []
            ai_sections = generate_uds_ai_sections(
                requirements_text="\n".join(req_texts),
                source_sections=source_sections,
                notes_text="\n".join(notes),
                logic_items=logic_items,
                example_text=ai_example_text,
                detailed=bool(ai_detailed),
                rag_snippets=rag_snippets,
            )
        except Exception:
            ai_sections = None

    _progress("payload", 82, "UDS 페이로드 생성")
    req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}
    req_source = source_sections.get("requirements", "")
    if source_only:
        req_combined = req_source
    elif req_from_docs and req_source:
        req_combined = "\n".join([req_from_docs.strip(), req_source.strip()]).strip()
    else:
        req_combined = req_from_docs or req_source
    globals_order_list = [
        x.strip()
        for x in re.split(r"[,\|;]+", globals_format_order or "")
        if x.strip()
    ]
    # Gather source document paths for the Reference (1.4) section of the
    # generated UDS docx. Currently only SRS comes through req_file_paths /
    # req_paths; callers who also supply SDS/HSIS/STP should set
    # ``uds_payload["reference_docs"]`` explicitly (see _build_uds_reference_lines).
    _source_docs: List[str] = []
    for _p in (req_file_paths or []):
        try:
            s = str(_p).strip()
            if s and s not in _source_docs:
                _source_docs.append(s)
        except Exception:
            continue
    for _p in (req_paths or []):
        s = str(_p or "").strip()
        if s and s not in _source_docs:
            _source_docs.append(s)

    _project_name_val = summary.get("project") if isinstance(summary, dict) else ""
    # Heuristic for {{MODULE_NAME}} in the docx template:
    #   1) first path's leaf directory from `source_root` (comma-separated supported)
    #   2) project_name as fallback
    _module_name_val = ""
    try:
        _first_src = (source_root or "").split(",")[0].strip()
        if _first_src:
            _module_name_val = Path(_first_src).name
    except Exception:
        _module_name_val = ""
    if not _module_name_val:
        _module_name_val = str(_project_name_val or "")

    uds_payload = {
        "job_url": job_url,
        "build_number": jenkins_meta.get("build_number"),
        "project_name": _project_name_val,
        "module_name": _module_name_val,
        "source_docs": _source_docs,
        "summary": summary,
        "overview": summary_text or source_sections.get("overview", ""),
        "requirements": req_combined,
        "interfaces": source_sections.get("interfaces", ""),
        "uds_frames": source_sections.get("uds_frames", ""),
        "notes": "\n".join(notes),
        "logic_diagrams": logic_items,
        "software_unit_design": source_sections.get("software_unit_design", ""),
        "unit_structure": source_sections.get("unit_structure", ""),
        "global_data": source_sections.get("global_data", ""),
        "interface_functions": source_sections.get("interface_functions", ""),
        "internal_functions": source_sections.get("internal_functions", ""),
        "function_table_rows": source_sections.get("function_table_rows", []),
        "global_vars": source_sections.get("global_vars", []),
        "static_vars": source_sections.get("static_vars", []),
        "macro_defs": source_sections.get("macro_defs", []),
        "calibration_params": source_sections.get("calibration_params", []),
        "function_details": source_sections.get("function_details", {}),
        "function_details_by_name": source_sections.get("function_details_by_name", {}),
        "call_map": source_sections.get("call_map", {}),
        "module_map": source_sections.get("module_map", {}),
        "req_map": req_map,
        "globals_info_map": source_sections.get("globals_info_map", {}),
        "common_macros": source_sections.get("common_macros", []),
        "type_defs": source_sections.get("type_defs", []),
        "param_defs": source_sections.get("param_defs", []),
        "version_defs": source_sections.get("version_defs", []),
        "globals_format_order": globals_order_list,
        "globals_format_sep": globals_format_sep,
        "globals_format_with_labels": globals_format_with_labels,
        "call_relation_mode": "code",
        "logic_max_children": logic_max_children,
        "logic_max_grandchildren": logic_max_grandchildren,
        "logic_max_depth": logic_max_depth,
        "unmatched_headings": unmatched_headings,
    }
    impact_path = _run_impact_analysis_for_uds(
        source_root_path,
        os.getenv("UDS_CHANGED_FILES", ""),
    )
    if impact_path:
        notes_text = str(uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join([x for x in [notes_text, f"impact:{impact_path.name}"] if x])
    if ai_sections:
        uds_payload["ai_sections"] = ai_sections
    if source_only and source_sections.get("notes"):
        uds_payload["notes"] = (uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join(
            [x for x in [uds_payload["notes"], source_sections.get("notes")] if x]
        )

    _progress("docx", 85, "DOCX 생성")
    job_slug = _job_slug(job_url)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _jenkins_exports_dir(cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    # ⚠ `backend/routers/jenkins.py` 의 쌍둥이(`uds_spec_{job_slug}_{ts}.docx`)는 이미
    #   선점한다. 이름 규칙이 글자까지 같은데 여기만 맨 경로였다.
    from backend.services.output_paths import reserve_unique_path
    out_path = reserve_unique_path(out_dir / f"uds_spec_{job_slug}_{ts}.docx")
    tpl = str(template_path).strip() or None
    _generate_docx_with_retry(tpl, uds_payload, out_path)
    summary = uds_payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        uds_payload["summary"] = summary
    summary["mapping"] = _compute_uds_mapping_summary(uds_payload.get("function_details") or {})
    sidecar_path = out_path.with_suffix(".payload.json")
    try:
        # (R32 W2) 원자 기록 — 품질 게이트가 생성 직후 이 파일을 읽는다. `write_text` 는 truncate 창이
        # 있어 반쪽 JSON 을 읽은 채점기가 DOCX 자기 대조로 조용히 강등된다(`report_gen/atomic_io.py`).
        atomic_write_text(
            sidecar_path,
            json.dumps(
                {
                    "docx_path": str(out_path),
                    "summary": summary,
                    "function_details": uds_payload.get("function_details") or {},
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception:
        # payload 사이드카가 없으면 채점기는 문서 자기 대조로 떨어진다 — 그 사실은 로그에 남아야 한다.
        _logger.warning("UDS payload sidecar write skipped: %s", sidecar_path, exc_info=True)
    residual_tbd_path = _write_residual_tbd_report(out_path, summary.get("mapping") or {})
    validation_path = out_path.with_suffix(".validation.md")
    ok_validation, _ = _run_report_with_timeout(
        lambda: generate_uds_validation_report(str(out_path), str(validation_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="validation report",
    )
    if not ok_validation:
        validation_path = None
    accuracy_path = out_path.with_suffix(".accuracy.md")
    src_root = str(source_root_path) if source_root_path else ""
    ok_accuracy, _ = _run_report_with_timeout(
        lambda: generate_called_calling_accuracy_report(
            str(out_path),
            src_root,
            str(accuracy_path),
            relation_mode="code",
        ),
        timeout_seconds=getattr(config, "UDS_ACCURACY_REPORT_TIMEOUT", 300),
        report_name="accuracy report",
    )
    if not ok_accuracy:
        accuracy_path = None
    swcom_context_path = out_path.with_suffix(".swcom_context.md")
    ok_swcom, _ = _run_report_with_timeout(
        lambda: generate_swcom_context_report(str(out_path), str(swcom_context_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="swcom context report",
    )
    if not ok_swcom:
        swcom_context_path = None
    swcom_diff_path = out_path.with_suffix(".swcom_diff.md")
    # ⚠ 예전엔 지정 경로가 없으면 저장소 `docs/` 의 HDPDM01 SUDS 로 **조용히 대체**했다.
    #   운영자가 자기 프로젝트 문서를 지정했는데 경로가 틀리면, 아무 말 없이 **다른
    #   프로젝트와의 diff** 를 산출물로 내놓게 된다. 같은 패턴을 이 저장소가
    #   `backend/routers/local.py::_pick_doc_path` 에서 이미 고쳤다 — 지정이 실패하면
    #   대체하지 말고 건너뛴다.
    ref_docx = Path(str(getattr(config, "UDS_REF_SUDS_PATH", "") or ""))
    if not ref_docx.exists():
        _logger.warning(
            "참조 SUDS 를 찾지 못해 SwCom diff 리포트를 건너뛴다(%s) — 저장소 docs/ 의 "
            "다른 프로젝트 문서로 대체하지 않는다", ref_docx,
        )
    if ref_docx.exists():
        ok_swcom_diff, _ = _run_report_with_timeout(
            lambda: generate_swcom_context_diff_report(str(ref_docx), str(out_path), str(swcom_diff_path)),
            timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
            report_name="swcom context diff report",
        )
        if not ok_swcom_diff:
            swcom_diff_path = None
    else:
        swcom_diff_path = None
    confidence_path = out_path.with_suffix(".field_confidence.md")
    ok_confidence, _ = _run_report_with_timeout(
        lambda: generate_asil_related_confidence_report(
            uds_payload,
            str(confidence_path),
            str(out_path),
        ),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="ASIL/Related confidence report",
    )
    if not ok_confidence:
        confidence_path = None
    constraints_path = out_path.with_suffix(".constraints.md")
    ok_constraints, _ = _run_report_with_timeout(
        lambda: generate_uds_constraints_report(uds_payload, str(constraints_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="constraints report",
    )
    if not ok_constraints:
        constraints_path = None
    quality_gate_path = out_path.with_suffix(".quality_gate.md")
    ok_quality_gate, _ = _run_report_with_timeout(
        lambda: generate_uds_field_quality_gate_report(str(out_path), str(quality_gate_path)),
        timeout_seconds=getattr(config, "UDS_REPORT_TIMEOUT", 120),
        report_name="field quality gate report",
    )
    if not ok_quality_gate:
        quality_gate_path = None

    # Quality DB recording (non-fatal)
    try:
        # local 경로와 동일하게 enrich 후 quick_gate 계산 → 경로 간 점수 일관성.
        _enrich_function_quality_fields(uds_payload)
        # 기록은 `_record_uds_run` 단일 관문 — 다섯 호출부가 각자 인자를 채우면
        # 경로마다 다른 열이 비어 "어느 경로로 만들었나" 가 섞인다. 산출물 충실도도
        # 여기서만 붙는다(복제하면 한쪽만 고쳐진다).
        # scm_id 는 넘기지 않는다: 이 경로가 아는 건 job_url/cache_root 뿐이라
        # 여기서 지어내느니 recorder 가 project_root 로 해결하게 둔다.
        _record_uds_run(
            _compute_quick_quality_gate(uds_payload),
            source_root=source_root,
            out_path=out_path,
            t0=_t0,
            ai_used=bool(ai_enable and ai_sections),
            extra_meta={
                "entry": "jenkins_generate_async",
                "build_selector": str(build_selector or ""),
            },
        )
    except Exception:
        # non-fatal 은 유지하되 **침묵은 금지**. sts/suts/sits 의 동일한
        # `except: pass` 가 record_run 의 NameError 를 몇 년간 삼켜 품질 기록이
        # 통째로 유실된 전례가 있다(608f849). 여긴 enrich/quick_gate 까지 try 안에
        # 있어 셋 중 뭐가 터져도 조용히 사라진다.
        _logger.exception("UDS quality record skipped (non-fatal)")

    _progress("preview", 92, "미리보기 생성")
    preview_html = generate_uds_preview_html(uds_payload)
    preview_path = out_path.with_suffix(".html")
    preview_path.write_text(preview_html, encoding="utf-8")

    return {
        "ok": True,
        "filename": out_path.name,
        "download_url": f"/api/jenkins/uds/download?job_url={job_url}&cache_root={cache_root}&filename={out_path.name}",
        "preview_url": f"/api/jenkins/uds/preview?job_url={job_url}&cache_root={cache_root}&filename={preview_path.name}",
        "validation_path": str(validation_path) if validation_path else "",
        "accuracy_path": str(accuracy_path) if accuracy_path else "",
        "swcom_context_path": str(swcom_context_path) if swcom_context_path else "",
        "swcom_diff_path": str(swcom_diff_path) if swcom_diff_path else "",
        "confidence_path": str(confidence_path) if confidence_path else "",
        "constraints_path": str(constraints_path) if constraints_path else "",
        "quality_gate_path": str(quality_gate_path) if quality_gate_path else "",
        "impact_path": str(impact_path) if impact_path else "",
        "residual_tbd_report_path": str(residual_tbd_path) if residual_tbd_path else "",
        # DOCX 생성 충실도 — 다른 리포트들과 **같은 표면**에 올린다.
        # ⚠ 자체 감사에서 잡힌 것: 이 수치는 sidecar 와 `.docx.stage.json` checkpoint 에
        #   기록되는데, checkpoint 를 읽는 코드가 저장소 전체에 **하나도 없다**(write-only).
        #   그래서 "침묵을 없앴다" 고 적었지만 실제로는 로그와 파일에만 남았다.
        #   보고를 추가하는 것과 보고가 **도달하는** 것은 다른 문제다.
        **_gen_stats_result_fields(out_path),
    }
