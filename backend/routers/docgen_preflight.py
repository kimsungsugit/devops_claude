"""문서 생성 **사전 판정**(preflight) — 만들기 전에 무엇이 부족한지 말한다.

## 무엇을 푸는가

`DocGenSection.generateDoc` 은 생성 전 검증이 없다. 필수 입력이 없으면 백엔드 400 으로
죽고, **선택 입력이 없으면 조용히 그것 없이 만든다**(`_resolve_opt_j`·`_res_async_sits`).
그래서 근거가 빠진 ISO 26262 산출물에 "생성 완료" 토스트가 뜬다. 이 엔드포인트는
**생성을 실행하지 않고** 그 상태를 먼저 보고한다.

## 설계 규약 (전부 실측에서 나왔다)

1. **`state` 7값을 서로 접지 않는다.** 특히 `unknown`(확인 못 함)을 `missing`(확인했고
   없음)으로 접으면 IPC 한 번 실패에 멀쩡한 문서가 '없음' 이 된다. 반대로 `unknown` 으로
   생성을 막지도 않는다 — worker 가 잠깐 흔들릴 때 생성이 통째로 불가가 된다.
2. **`degraded`(있지만 부족)는 차단하지 않는다.** 실측상 주석·타입 근거가 100% 인
   프로젝트가 없다. 막으면 아무도 문서를 못 만든다.
3. **재지 못한 값을 `0` 으로 그리지 않는다.** 소스 파싱은 실측 41~368초라 요청 안에서
   돌릴 수 없다 — 캐시가 없으면 `unmeasured` 로 두고 측정 액션을 제안한다.
4. **칸 수를 예고하지 않는다.** 출처는 "후보 집합 + 강도 우선 덮어쓰기" 구조이고
   `module_inherit` 이 모듈 전체로 번지므로 입력 유무만으로 계산할 수 없다
   (`docgen_field_sources` 모듈 docstring 참조). 사슬의 **단계별 가용성만** 낸다.

## 입력 표면

경로는 레지스트리(`scm_id`)에서 오고, `doc_paths` 는 **생성 핸들러가 이미 받는 것과
같은 표면**이다(새로 열지 않는다). 모든 파일 접근은 **resolver(cloudium 이면 worker
IPC) 경유**다 — 이 저장소의 하드 제약이다.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.dependencies.admin import require_admin
from backend.services import docgen_comment_coverage as _cov
from backend.services import docgen_field_sources as _chain
from backend.services import docgen_output as _out
from backend.services import docgen_requirements as _req
from backend.services import docgen_test_materials as _tm
from backend.services.swut_meta_resolver import (
    folder_contents_hint as _resolver_folder_contents_hint,
)

router = APIRouter()
_logger = logging.getLogger("devops_api.docgen_preflight")

# ── state 어휘 (계획서 §5) ──────────────────────────────────────────────────
S_OK = "ok"                    # 확인됨
S_MISSING = "missing"          # 확인했고 없다
S_STALE = "stale_path"         # 경로가 낡음(같은 폴더에 개정본 후보)
S_ERROR = "error"              # worker 미기동 등 인프라
S_DEGRADED = "degraded"        # 있지만 부족 — 차단하지 않는다
S_UNMEASURED = "unmeasured"    # 재지 못했다 — 0 이 아니다
S_NEEDED = "needed"            # 사용자 결정 대기

# verdict 는 오독 위험이 큰 순서로 도출한다.
V_BLOCKED = "blocked"
V_NEEDS_DECISION = "needs_decision"
V_UNKNOWN = "unknown"
V_DEGRADED = "degraded"
V_READY = "ready"

# ── phase 어휘 — **화면과 lockstep** ────────────────────────────────────────
#
# 패널은 `PHASE_ORDER` 를 돌며 `steps.filter(s => s.phase === p)` 로 그린다. 그래서
# 여기에만 있고 화면에 없는 phase 는 **에러도 경고도 없이 통째로 사라진다** — 서버는
# 행을 냈고 사용자는 못 본다. 이 저장소가 반복해 겪은 침묵 그대로다.
# 드리프트는 `tests/unit/test_docgen_preflight_phases.py` 가 양쪽에서 실측해 막는다.
PH_ACCESS = "access"
PH_INPUT = "input"
PH_MATERIAL = "material"
PH_CHAIN = "chain"
PH_DECISION = "decision"
PH_HISTORY = "history"      # 직전 생성의 결말 — 지금의 입력이 아니라 **기록**이다
PHASES = (PH_ACCESS, PH_INPUT, PH_MATERIAL, PH_CHAIN, PH_DECISION, PH_HISTORY)

# 레지스트리 `linked_docs` 키 → 이 모듈의 입력 키.
_DOC_KEY_TO_INPUT = {
    "srs": _req.IN_SWRS,
    "sds": _req.IN_SWDS,
    "uds": _req.IN_UDS_DOC,
    "hsis": _req.IN_HSIS,
    "stp": _req.IN_STP,
    "template": _req.IN_TEMPLATE,
}
_INPUT_TO_DOC_KEY = {v: k for k, v in _DOC_KEY_TO_INPUT.items()}

# 템플릿은 **문서마다 형식이 다르다**(UDS .docx / 시험 규격서 .xlsm). 그래서 레지스트리
# 키도 문서별로 나뉜다. 없으면 공용 `template` 로 폴백한다(구 설정 호환).
_TEMPLATE_KEY_BY_DOC = {
    "uds": "uds_template",
    "sts": "sts_template",
    "suts": "suts_template",
    "sits": "sits_template",
}

# `adopt-doc-path` 가 교체할 수 있는 **레지스트리 키**. 공용 `template` 은 뺀다 —
# `ScmLinkedDocs` 에 그 필드가 없어(`uds_template` 등만 있다) 화이트리스트를 통과해도
# "기존 등록 경로가 없습니다" 400 으로 끝난다. 설정(doc_paths)의 공용 `template` 은
# 여전히 입력으로 읽지만, 레지스트리 교체 대상은 아니다(2026-09-03 감사 P-1).
_ADOPTABLE_DOC_KEYS = frozenset(
    k for k in _DOC_KEY_TO_INPUT if k != "template"
) | frozenset(_TEMPLATE_KEY_BY_DOC.values())

# `_resolve_inputs_with_origin` 이 origins 에 남기는 **마커** — 양식 설정 파일이 있는데
# 읽지 못했다. 입력 키가 아니라서 `inputs` 에는 절대 들어가지 않는다.
_CONFIG_UNREADABLE = "__meta_config_unreadable__"

# 시험 **결과** 문서의 양식은 SCM 레지스트리가 아니라 `config/swut_meta.json` 의
# `template_paths` 가 프로젝트별로 관리한다(정본을 옮기면 갈라진다). 여기 있는 것은
# **어느 키를 봐야 하는가** 뿐이다.
# 생성기가 **실제로 여는 형식**. UDS 는 python-docx, 시험 규격서는 openpyxl 이다.
#
# ⚠ 회사 표준 폴더에는 같은 이름의 `.xlsm` 과 `.docx` 가 **둘 다** 있다(실측). 그래서
#   `.docx` 를 고르기 쉬운데, 시험 규격서 생성기는 그걸 열다가
#   `InvalidFileException: openpyxl does not support .docx` 로 죽는다 — 실제로 그렇게
#   실패했다. 게이트가 **생성 전에** 잡아야 하는 종류의 결함이다.
_TEMPLATE_EXPECTED_EXT = {
    "uds": (".docx",),
    "sts": (".xlsm", ".xlsx"),
    "suts": (".xlsm", ".xlsx"),
    "sits": (".xlsm", ".xlsx"),
}

# doc_type → `config/swut_meta.json` `template_paths` 의 양식 키.
# 정본은 라우터의 `_read_template_bytes` 다(`swut.py:241` · `swit.py:235`) — 거기서 config
# fallback 키를 고르므로, 여기가 갈라지면 게이트는 "양식 있음" 이라 하고 빌드는 400 을 낸다.
_TEST_REPORT_TEMPLATE_KEY = {
    "swut": "coverage_report_template",
    "sutr": "sutr_template",
    "swutcr": "swutcr_template",
    "swit": "swit_coverage_template",
    "sitr": "swit_sitr_template",
    "switcr": "switcr_template",
    "swreport": "es95411_template",
}


# 시험 결과 6종 → VectorCAST 로그의 **시리즈**. 통합 Summary(`swreport`)는 로그가 아니라
# 레벨별 산출물을 읽으므로 여기 없다.
_TEST_REPORT_LOG_SERIES = {
    "swut": "swut", "sutr": "swut", "swutcr": "swut",
    "swit": "swit", "sitr": "swit", "switcr": "swit",
}

# 대응 시험 규격서가 **필수가 될 수 있는** 문서 — spec-based 빌드 경로를 가진 둘뿐이다.
# (커버리지·종합결과는 같은 규격서를 읽지만 없어도 빌드가 죽지 않는다.)
_SPEC_REQUIRED_SERIES = {"sutr": "swut", "sitr": "swit"}


class PreflightRequest(BaseModel):
    doc_type: str = Field(
        ...,
        description=(
            "uds/sts/suts/sits · swut/sutr/swutcr · swit/sitr/switcr · swreport "
            "(swut/swit 은 커버리지 리포트 — Quality DB doc_type 과 같은 어휘를 쓴다)"
        ),
    )
    scm_id: str = Field("", description="SCM 레지스트리 id — 경로의 기본 출처")
    # 설정 > SCM 우선순위는 프론트 정책(`sharedInputs.js`)이며 여기서 뒤집지 않는다.
    # 생성 핸들러가 이미 받는 것과 같은 표면이라 새 입력 표면이 아니다.
    doc_paths: Dict[str, str] = Field(default_factory=dict)
    source_root: str = Field("", description="비우면 레지스트리 값을 쓴다")
    # 시험 결과 3종(SUTR/SITR/통합)의 빌더 폼. 프론트 `missingRequiredFields` 판정을
    # 여기로 흡수해 **판정이 두 벌이 되지 않게** 한다(이 저장소의 반복 결함).
    form: Dict[str, Any] = Field(default_factory=dict)
    # UDS 는 Jenkins **빌드 캐시**가 있어야 시작한다(`helpers/uds.py:1504`).
    job_url: str = ""
    cache_root: str = ""
    build_selector: str = "lastSuccessfulBuild"
    # 사용자가 화면에서 정한 생성 상한(localStorage `devops_v2_docgen_caps`).
    #
    # ⚠ `Dict[str, Any]` 인 것은 의도다 — 같은 스토어에 `suts_scope` 같은 **문자열**
    #   선택지가 섞여 있어(`sharedInputs.js:64` `saveDocGenChoice`) `Dict[str, int]`
    #   로 받으면 그 키 하나 때문에 요청 전체가 422 로 죽는다.
    # ⚠ 이 값은 **판정에만** 쓴다(정했는가 / 안 정했는가). 생성 파라미터는 생성
    #   요청이 따로 싣는다 — 여기로 문서를 만들지 않는다.
    caps: Dict[str, Any] = Field(default_factory=dict)
    # 프로젝트 ASIL 등급(설정 > 공통 메타). 상한과 달리 **문서 내용을 바꾼다** —
    # `generators/sts.py:1719` 가 이 값으로 요구별 ASIL 이 빈 칸을 역채움하고,
    # `is_safety_asil` 판정이 시험 생성 갈래를 가른다. 표지의 "ASIL Level" 칸도 이것이다.
    # ⚠ 빈 값을 `QM` 으로 접지 않는다 — 근거 부재를 "안전 요구 없음" 으로 바꾸면
    #   under-classification 이다(저장소 규약: 지어내지 않는다).
    asil_level: str = ""


def _step(step_id: str, phase: str, state: str, label: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": step_id, "phase": phase, "state": state, "label": label}
    out.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return out


def _cap_user_value(caps: Dict[str, Any], name: str) -> Optional[int]:
    """사용자가 화면에서 정한 상한. **안 정한 것과 0 을 구분한다.**

    프론트 규약(`sharedInputs.js:50-57`)은 빈 값·0·음수면 **키를 지운다** = 생성기
    기본값을 쓴다는 뜻이다. 그 규약을 여기서 되풀이하지 않고 그대로 존중한다 — 0 이
    실려 오면 사용자가 고른 값이 아니라 스토어가 깨진 것이므로 '안 정함' 으로 본다.
    같은 스토어에 문자열 선택지(`suts_scope`)가 섞여 있어 형 변환 실패도 '안 정함' 이다.
    """
    raw = caps.get(name)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


# 이 축은 절단량을 **잴 방법이 아예 없다**. `unmeasured` 로 두면 verdict 가 영구
# 고착되므로(원래 고치려던 결함) `ok` 로 두되 측정하지 않는다는 사실을 말한다.
_NO_MEASURE = object()

# cap 이름 → 소스 파싱 캐시에서 그 절단을 담는 키.
_CAP_TRUNCATION_KEY = {
    "max_items_per_category": "uds_category_caps",
    "max_source_files": "uds_file_scan",
}


def _cap_truncation(cap_name: str, tm: Dict[str, Any]) -> Any:
    """이 상한이 **지금 자르고 있는가**.

    Returns:
        ``_NO_MEASURE`` 측정 경로가 없는 축 · ``None`` 잴 수 있는데 아직 안 쟀다 ·
        ``{}`` 쟀고 안 자른다 · ``{"measured": …, "reason": …}`` 쟀고 자른다.

    ⚠ 넷을 서로 접지 않는다. 특히 "안 쟀다" 를 "안 자른다" 로 접으면 이 모듈 docstring
    §3("재지 못한 값을 `0` 으로 그리지 않는다")을 스스로 어긴다.
    """
    key = _CAP_TRUNCATION_KEY.get(cap_name)
    if not key:
        return _NO_MEASURE
    box = tm.get(key) or {}
    if not box.get("measured"):
        return None
    if key == "uds_category_caps":
        tr = box.get("truncated") or {}
        if not tr:
            return {}
        dropped = sum(int(v.get("dropped") or 0) for v in tr.values())
        worst_k, worst_v = max(tr.items(), key=lambda kv: int(kv[1].get("dropped") or 0))
        return {
            "measured": {"truncated": tr, "dropped_total": dropped},
            "reason": (f"지금 {dropped}개 항목이 상한에 걸려 규격에서 빠집니다 "
                       f"(가장 큰 축 `{worst_k}` {worst_v.get('total')}→{worst_v.get('cap')})"),
        }
    if not box.get("truncated"):
        return {}
    return {
        "measured": {"scanned": box.get("scanned"), "truncated": True},
        "reason": (f"소스 파일 상한({box.get('cap')})에 닿았습니다 — 그 뒤 파일의 함수는 "
                   "문서에 아예 없습니다"),
    }


# "전량" 의 **출처**. 둘은 서로 다른 강도의 주장이라 같은 문장을 쓰면 안 된다.
#   measured — 이 소스를 실제로 세어 나온 수. `전량 145 중 95개가 빠진다` 가 참이다.
#   catalog  — 생성기 전략 후보의 **이론적 최대**. 함수마다 후보 수가 달라 그만큼
#              나오는 함수는 거의 없다. 이걸 measured 처럼 단언하면 손실을 부풀린다.
_SUG_MEASURED = "measured"
_SUG_CATALOG = "catalog"


def _cap_full_total(cap_name: str, cap: Dict[str, Any],
                    tm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """"전부 담으려면 얼마" 와 **그 수를 어디서 얻었는가**.

    Returns:
        ``_NO_MEASURE`` 이 상한엔 '전량' 을 잴 축이 아예 없다 · ``None`` 잴 수 있는데
        아직 안 쟀다 · ``{"value", "basis"}`` 쟀다.

    ⚠ 앞의 둘을 접으면 안 된다. `_NO_MEASURE` 를 `None` 으로 접으면 영영 안 나올 답을
      기다리며 verdict 가 `unknown` 에 고착되고, 반대로 접으면 곧 나올 답을 "측정하지
      않습니다" 로 덮어 **실제 손실이 화면에서 사라진다**(둘 다 실측으로 겪었다).

    ⚠ 판정(전량 대비 얼마가 빠지는가)은 여기 값 하나로만 한다. 예전엔 `generator`
    기본값으로 세는 경로가 섞여 있어, 흐름이 145 인데 120 기준으로 세는 바람에
    50 으로 낮춘 손실을 95 가 아니라 70 으로 보고했다.
    """
    if cap_name == "max_tc_per_req":
        raw, basis = (tm.get("sts_mapping") or {}).get("max_functions_per_req"), _SUG_MEASURED
    elif cap_name == "max_flows":
        raw, basis = (tm.get("sits") or {}).get("flows_total"), _SUG_MEASURED
    elif cap_name in ("max_subcases", "max_sequences"):
        # 생성기가 만들 수 있는 후보 전량. API 기본이 그보다 작으면 그 차이가 손실 **상한**이다.
        # ⚠ SUTS 는 `generator`(24)가 **캡**이라 그걸로 재면 `n <= api` 가 되어 조치
        #   제안이 영영 안 뜬다 — 전략 카탈로그 최대(30)를 써야 한다.
        raw, basis = (cap.get("catalog_max") or cap.get("generator")), _SUG_CATALOG
    else:
        return _NO_MEASURE
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return {"value": n, "basis": basis} if n > 0 else None


def _cap_measured_at(cap_name: str, tm: Dict[str, Any]) -> Optional[int]:
    """그 절단 통계를 **어느 상한으로** 쟀는가. 모르면 `None`."""
    box = tm.get(_CAP_TRUNCATION_KEY.get(cap_name) or "") or {}
    try:
        return int(box.get("cap"))
    except (TypeError, ValueError):
        return None


def _cap_suggested_from_truncation(cap_name: str, tm: Dict[str, Any]) -> Optional[int]:
    """"전부 담으려면 얼마" — **측정에서 확실히 알 수 있을 때만**.

    ⚠ `max_source_files` 는 여기 없다. 스캔이 상한에 닿는 즉시 멈춰서 전체 파일 수를
      모르기 때문이다(`uds_generator.py` 의 `file_scan` 주석). 모르는 수를 제안으로
      내면 사용자는 그 값을 넣고 "이제 전부 담긴다" 고 믿는다 — 이 모듈이 금지하는
      바로 그 형태다.
    """
    if cap_name != "max_items_per_category":
        return None
    tr = (tm.get("uds_category_caps") or {}).get("truncated") or {}
    totals = []
    for v in tr.values():
        try:
            totals.append(int(v.get("total")))
        except (TypeError, ValueError):
            continue
    # 상한은 **분류마다** 걸리므로, 하나도 안 빠지려면 가장 큰 분류를 담아야 한다.
    return max(totals) if totals else None


def _linked_docs(req: "PreflightRequest") -> Dict[str, Any]:
    """레지스트리의 `linked_docs`. 없으면 빈 dict — 조회 실패를 "없음" 과 섞지 않는다."""
    if not req.scm_id:
        return {}
    try:
        from backend.services.scm_registry import get_registry_entry
        entry = get_registry_entry(req.scm_id)
        return entry.linked_docs.model_dump(mode="json") if entry is not None else {}
    except Exception:  # silent-ok: 공시는 실패해도 화면이 떠야 한다
        logging.getLogger("devops_api").debug("linked_docs 조회 실패", exc_info=True)
        return {}


def _reference_doc_for(req: "PreflightRequest", *, linked: Dict[str, Any]) -> str:
    """같은 종류의 **납품 정본** 경로.

    ⚠ 우선순위는 프론트 생성 요청(`DocGenSection.jsx`: `docPaths[docType] ||
      linkedDocs[docType]`)과 **같아야** 한다. 갈리면 게이트가 이번 생성에 쓰이지 않을
      파일을 "실제로 쓸 템플릿" 이라고 이름 댄다.

    ⚠ `_resolve_inputs` 로는 못 얻는다 — 거기 `_DOC_KEY_TO_INPUT` 은 `srs`/`sds`/`uds`
      같은 **근거 문서** 키만 담고, 정본 키(`sts`/`suts`/`sits`)는 없다.
    """
    key = str(req.doc_type or "").strip().lower()
    v = str(req.doc_paths.get(key) or "").strip()
    if v:
        return v
    raw = linked.get(key)
    return str((raw[0] if isinstance(raw, list) and raw else raw) or "").strip()


def _tm_lookup_paths(inputs: Dict[str, str]) -> Dict[str, str]:
    """측정 캐시를 찾을(그리고 채울) 문서 경로 — **`_resolve_inputs` 결과에서만** 만든다.

    측정과 조회가 각자 경로를 구하면 문자열이 조금만 달라도 캐시가 영영 안 맞아
    게이트가 계속 `unmeasured` 로 남는다. 그래서 두 경로 모두 이 함수를 통한다.
    """
    return {
        "sds_path": str(inputs.get(_req.IN_SWDS) or ""),
        "srs_path": str(inputs.get(_req.IN_SWRS) or ""),
        "uds_path": str(inputs.get(_req.IN_UDS_DOC) or ""),
    }


def _suts_normalize_scope(scope: Any) -> "tuple[str, str]":
    """시험 범위 정규화 — **정의는 생성기가 갖는다**(`generators.suts.normalize_scope`).

    화면이 규칙을 복제하면 여집합을 보게 되고, 그때 같은 값에 두 화면이 반대말을 한다
    (실측: `sud` → 게이트 "정본 기준" / 생성기 "소스 전체").

    ⚠ import 실패 시에도 화면은 떠야 하므로 폴백을 두되, **폴백도 같은 방향**(모르는
      값은 좁은 쪽)이어야 한다. 넓은 쪽으로 떨어지면 폴백이 원래 결함을 되살린다.
    """
    try:
        from generators.suts import normalize_scope
        return normalize_scope(scope)
    except Exception:  # silent-ok: 공시는 실패해도 화면이 떠야 한다
        logging.getLogger("devops_api").debug(
            "SUTS scope 정규화를 생성기에서 못 읽었다 — 폴백", exc_info=True)
        raw = str(scope or "").strip()
        low = raw.lower()
        if not low or low == "suds":
            return "suds", ""
        return ("source", "") if low == "source" else ("suds", raw)


def _mcdc_risk(tm: Dict[str, Any], eff: Optional[int],
               full: Optional[int]) -> Optional[Dict[str, Any]]:
    """SUTS 시퀀스 상한이 **이 소스에서** MC/DC 를 자르는가.

    `generators/suts` 는 MC/DC 전략을 목록 **맨 끝**에 붙이고 `strategies[:max_seq]` 로
    앞에서 자른다. 그래서 상한이 후보 최대보다 작으면 MC/DC 가 가장 먼저 사라진다 —
    ASIL D 는 MC/DC 가 필수(ISO 26262-6)라 그 프로젝트에선 규격 미달로 직결된다.

    지금까지 게이트는 이 사실을 **일반론**으로만 적었다: QM 전용 프로젝트에는 읽을
    이유 없는 소음이고, 정작 ASIL D 프로젝트에서는 몇 개가 걸리는지 말하지 못했다.
    등급 분포는 이미 재고 있으므로(`suts_asil.by_grade`) 새로 재지 않는다.

    ⚠ 안 쟀으면 ``None`` — 등급을 모른다는 사실을 "ASIL D 없음" 으로 접지 않는다.
    """
    a = tm.get("suts_asil") or {}
    if not a.get("measured"):
        return None
    by_grade = a.get("by_grade")
    if not isinstance(by_grade, dict):
        return None
    d = int(by_grade.get("D") or 0)
    c = int(by_grade.get("C") or 0)
    cut = isinstance(eff, int) and isinstance(full, int) and eff < full
    return {"asil_d": d, "asil_c": c, "mcdc_at_risk": bool(cut and d)}


def _permission_error_kind(message: str) -> str:
    """`PermissionError` 가 실어 온 **사실**을 가른다 — `worker` / `prefix` / `other`.

    `file_resolver.CloudiumFileResolver` 는 서로 다른 세 사실에 같은 예외형을 쓴다:
    worker 연결 실패·미응답(`_ipc_call`/`_ensure_gate`, "Cloudium worker …"),
    허용 prefix 밖 경로 차단(`_check_allowed`, "allowed_prefixes"/"차단"),
    그리고 worker 가 되돌려 준 OS 권한 오류. 화면의 조치는 셋이 다르다 — 첫째는 워커
    실행, 둘째는 SCM/파일 모드에서 prefix 등록, 셋째는 권한. 문장으로만 가를 수 있다
    (예외형이 하나라서) — 그래서 표지 어구만 본다.
    """
    text = str(message or "")
    # worker 문장을 먼저 본다 — read-only 차단 문구("write_text 차단.")에도 "차단" 이 있어
    # 순서를 바꾸면 그쪽이 prefix 로 오분류된다(현재 `exists` 경로에선 도달 불가지만 헬퍼는 범용).
    if "cloudium worker" in text.lower():
        return "worker"
    # `_check_allowed` 의 두 문장: 허용목록 **미설정**("allowed_prefixes 미설정 … 외부 경로
    # 차단됨") 과 허용목록 밖("허용되지 않은 경로 접근 차단됨") — 실무의 거의 전부는 후자다.
    if any(tok in text for tok in ("allowed_prefixes", "외부 경로 차단", "허용되지 않은 경로")):
        return "prefix"
    return "other"


def _probe_path(resolver: Any, path: str) -> Dict[str, Any]:
    """존재 3상태. ⚠ 확인 실패를 `missing` 으로 접지 않는다(`scm.py:294` 와 같은 규약).

    `kind` 는 `S_ERROR` 일 때만 뜻이 있다(`_permission_error_kind`). 예전엔 prefix 밖
    경로도 worker 연결 실패와 같은 `S_ERROR` 하나라, 화면이 이미 돌고 있는 워커를
    "실행하세요" 라고 안내했다(2026-09-03 감사 P-3③).
    """
    try:
        return {"state": S_OK if resolver.exists(path) else S_MISSING, "reason": "", "kind": ""}
    except PermissionError as exc:
        kind = _permission_error_kind(str(exc))
        if kind == "prefix":
            return {"state": S_ERROR, "kind": kind,
                    "reason": f"허용 경로(allowed_prefixes) 밖 — {str(exc)[:160]}"}
        return {"state": S_ERROR, "kind": kind, "reason": f"접근 거부 — {str(exc)[:160]}"}
    except Exception as exc:  # noqa: BLE001 — resolver/IPC 계열이 광범위하다
        return {"state": S_UNMEASURED, "kind": "",
                "reason": f"확인 실패 ({type(exc).__name__}: {str(exc)[:120]})"}


def _mark_available(available: Dict[str, bool], key: str, state: str) -> None:
    """입력 가용성 — **3상태**로 적는다.

    `S_OK` → True, 확인했고 없음(`missing`/`stale`) → False, 그리고 **확인하지 못한 것**
    (`unmeasured`/`error`)은 **키를 만들지 않는다**. `docgen_field_sources.chain_state` 는
    키가 없으면 "모름"(`have=None`) 으로 그린다 — 예전의 `(state == S_OK)` 는 확인 실패를
    "확인했고 없음"(✗) 으로 접었고, 같은 파일이 주석 커버리지에서 정확히 그것을 금지해
    두고도 입력 행에서는 어기고 있었다(2026-09-03 감사 P-3②).
    """
    if state == S_OK:
        available[key] = True
    elif state in (S_MISSING, S_STALE):
        available[key] = False


def _revision_actions(
    key: str, origin: Optional[Dict[str, str]], suggestion: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """개정본 채택 액션 — **어느 레지스트리 키를 바꿀지**(`target`)를 함께 싣는다.

    화면은 `step.id`(입력 키 `swrs`/`swds`/`uds_doc`)만 알고 `adopt-doc-path` 는
    레지스트리 키(`srs`/`sds`/`uds`)만 받는다. `target` 이 없던 동안 보드가 `step.id` 를
    그대로 보내 대표 조치 버튼이 `400 알 수 없는 문서 키: swrs` 였다 — `hsis`/`stp` 만
    두 키가 같아 우연히 동작했다(2026-09-03 감사 P-1).

    설정(doc_paths)에서 온 경로는 레지스트리 교체 대상이 **아니다** — 교체해도 설정이 계속
    레지스트리를 가려 화면은 그대로다. 그때는 어디서 바꿔야 하는지를 사유로 말한다.
    """
    src = (origin or {}).get("from", "")
    reg_key = str((origin or {}).get("key") or _INPUT_TO_DOC_KEY.get(key, key))
    if src == "registry" and reg_key in _ADOPTABLE_DOC_KEYS:
        return ([{"kind": "adopt_suggestion", "value": suggestion, "target": reg_key}], "")
    # ⚠ 채택할 수 없는 출처는 **어디서 바꾸는지**를 반드시 말한다. 기본값을 침묵으로 두면
    #   새 출처가 생길 때마다 "안내 없는 pick_path" 가 조용히 늘어난다(R26 리뷰 W2/X5).
    note = _ORIGIN_GUIDANCE.get(src) or _ORIGIN_GUIDANCE["__unknown__"]
    return ([{"kind": "pick_path", "target": reg_key}], note)


# 출처 → 개정본을 채택할 수 없을 때 사용자가 고칠 자리. 미등록 출처는 `__unknown__` 으로
# 떨어지되 **문장은 있다**(어디서든 침묵하지 않는다).
# ⚠ `form`(레벨별 산출물)·`request`(source_root) 는 지금 stale 분기에 **도달하지 않는다** —
#   둘 다 개정본 제안을 하지 않는 자기 분기를 탄다. 죽은 코드가 아니라 "출처가 생기면 문장도
#   있어야 한다" 는 표의 완결성이다(R26 리뷰 FI1).
_ORIGIN_GUIDANCE = {
    "doc_paths": "설정(입력 자료)에 지정된 경로라 레지스트리 교체 대상이 아닙니다 — 설정에서 바꾸세요",
    "config": "양식 설정(config/swut_meta.json)에 등록된 경로입니다 — 그 파일에서 바꾸세요",
    "form": "빌더 탭의 입력 폼에서 온 경로입니다 — 폼에서 바꾸세요",
    "request": "이 요청이 직접 지정한 경로입니다 — 요청 값을 바꾸세요",
    "__unknown__": "이 경로의 출처를 특정하지 못해 자동 채택하지 않습니다 — 등록한 곳에서 바꾸세요",
}

# 레벨별 산출물(통합 Summary `source_paths`)의 결합 구분자. 콤마는 경로에 쓰일 수 있어
# (`…\Report,APP\x.xlsm` 실측) 오분할된다 — 개행은 경로에 못 들어간다(R26 리뷰 W1).
_MULTI_SEP_LEVEL = "\n"


def _split_multi(key: str, path: str) -> List[str]:
    """다중 경로 입력을 조각으로. VectorCAST 는 콤마(config 규약), 산출물은 개행."""
    if key == _req.IN_LEVEL_ARTIFACTS:
        sep = _MULTI_SEP_LEVEL
    elif key == _req.IN_VCAST:
        sep = ","
    else:
        # 일반 문서 경로는 자르지 않는다 — `…\Report,APP\SwRS.docx` 를 콤마로 자르면 W1 과
        # 같은 오분할이 접근 probe 에 남는다(리뷰 NI1).
        return [str(path or "").strip()] if str(path or "").strip() else []
    return [x.strip() for x in str(path or "").split(sep) if x.strip()]


# 2026-08-26 — 본체를 `swut_meta_resolver.folder_contents_hint` 로 올렸다.
# 빌드 경로(라우터 3종)가 같은 문장을 써야 같은 부재에 화면이 두 말을 하지 않는다.
_folder_contents_hint = _resolver_folder_contents_hint


def _suggest_revision(resolver: Any, path: str) -> str:
    """등록 경로가 낡았을 때 **같은 폴더의 개정본 후보**를 찾는다.

    실측(인계 문서): `kjpds02` 는 SRS 를 `_v2.03_….docx` 로 등록했는데 폴더엔
    `_v3.01_…_R.docx` 하나뿐이었다. 막는 대신 고치게 유도하는 것이 이 함수의 목적이다.
    후보가 여럿이면 **고르지 않는다** — 임의 선택은 다른 프로젝트 문서를 끌어올 수 있다.
    """
    try:
        p = Path(path)
        parent, suffix = str(p.parent), p.suffix.lower()
        if not parent or not suffix:
            return ""
        names = resolver.list_dir(parent, pattern=f"*{suffix}") or []
    except Exception:  # noqa: BLE001  # silent-ok
        # 폴더를 못 훑는 것은 제안이 없다는 뜻일 뿐, 판정(파일 없음)은 이미 났다.
        return ""

    from report_gen.doc_kind import is_sds_filename, is_srs_filename
    kind = None
    if is_srs_filename(p.name):
        kind = is_srs_filename
    elif is_sds_filename(p.name):
        kind = is_sds_filename
    cands: List[str] = []
    for n in names:
        # ⚠ **파일명만** 낸다. resolver 의 `list_dir` 은 전체 경로를 돌려주는데(로컬·worker
        #   둘 다), 그걸 그대로 `suggestion` 에 실으면 보드가 `adopt-doc-path` 에 전체
        #   경로를 보내고 그 엔드포인트는 "파일명만 지정할 수 있습니다" 로 400 을 낸다 —
        #   같은 버튼의 두 번째 400 이었다(2026-09-03 감사 P-1, 가드 실행에서 드러남).
        name = Path(str(n.get("name") if isinstance(n, dict) else n)).name
        if not name or name == p.name:
            continue
        if kind is None or kind(name):
            cands.append(name)
    return cands[0] if len(cands) == 1 else ""


def _builder_project_id(req: PreflightRequest) -> str:
    """빌더 `project_id`(예: "KJPDS02") — 폼 값이 우선, 없으면 SCM 이 선언한 값.

    ⚠ SCM id 와 다른 어휘다(`kjpds02_pv` ↔ `KJPDS02`). 레지스트리가 그 매핑을 갖는다.
    """
    pid = str(req.form.get("project_id") or "").strip()
    if pid or not req.scm_id:
        return pid
    try:
        from backend.services.scm_registry import get_registry_entry
        entry = get_registry_entry(req.scm_id)
        return str(getattr(entry, "builder_project_id", "") or "").strip()
    except Exception:  # noqa: BLE001 — 레지스트리 로딩 계열이 광범위
        # 못 읽으면 '미지정' 으로 두고 소비처가 사유를 낸다(지어내지 않는다).
        return ""


def _resolve_inputs(req: PreflightRequest) -> Dict[str, str]:
    """입력 키 → 경로 (출처 없이). 계약 유지용 어댑터 — 순회는 `_resolve_inputs_with_origin` 한 곳뿐."""
    return _resolve_inputs_with_origin(req)[0]


def _resolve_inputs_with_origin(
    req: PreflightRequest,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """입력 키 → 경로, 그리고 **그 경로가 어디서 왔는지**.

    우선순위는 **설정(doc_paths) > SCM 레지스트리**(기존 정책). 출처는
    `{"from": "doc_paths"|"registry"|"config"|"form"|"request", "key": <그쪽 키>}` 다.
    조치 액션이 출처를 알아야 한다 — 레지스트리에서 온 낡은 경로는 `adopt-doc-path` 로
    교체할 수 있지만, 설정에서 온 경로는 교체해도 설정이 계속 가린다(P-1).
    """
    from backend.services.scm_registry import get_registry_entry

    linked: Dict[str, Any] = {}
    source_root = req.source_root
    source_root_from = "request" if source_root else ""
    if req.scm_id:
        entry = get_registry_entry(req.scm_id)
        if entry is not None:
            linked = entry.linked_docs.model_dump(mode="json")
            if not source_root and entry.source_root:
                source_root, source_root_from = entry.source_root, "registry"

    def _pick(*keys: str) -> Tuple[str, Dict[str, str]]:
        """설정(doc_paths) > 레지스트리 순, 그리고 **앞선 키가 이긴다**."""
        for key in keys:
            v = str(req.doc_paths.get(key) or "").strip()
            if v:
                return v, {"from": "doc_paths", "key": key}
        for key in keys:
            raw = linked.get(key)
            v = str((raw[0] if isinstance(raw, list) and raw else raw) or "").strip()
            if v:
                return v, {"from": "registry", "key": key}
        return "", {}

    out: Dict[str, str] = {}
    origins: Dict[str, Dict[str, str]] = {}
    if source_root:
        out[_req.IN_SOURCE_ROOT] = source_root
        origins[_req.IN_SOURCE_ROOT] = {"from": source_root_from, "key": "source_root"}

    # 통합 Summary 의 레벨별 산출물은 레지스트리·config 어디에도 등록되지 않는다 —
    # 라우터(`swreport.py::_resolve_source_workbooks`)가 요청의 `source_paths` 를 읽고,
    # 비면 양식 자체를 source 로 쓴다(template-self). 게이트도 **같은 자리(폼)** 를 본다.
    # ⚠ 예전엔 이 키가 `required` 인데 채우는 곳이 없어 통합 Summary 준비 점검이
    #   **영구 `진행 불가`** 였다(2026-09-03 감사 P-2). 리스트는 콤마로 이어 아래 probe 가
    #   조각별로 본다(VectorCAST 복수 폴더와 같은 규약).
    raw_paths = req.form.get("source_paths") if isinstance(req.form, dict) else None
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]           # 문자열 하나를 조용히 버리지 않는다
    if isinstance(raw_paths, list):
        # 목록은 **라우터와 같은 함수**로 만든다 — 라우터는 이 목록을 전부 읽으므로 하나라도
        # 없으면 빌드가 죽는다(부분 결손 아님). 게이트가 자기 규칙으로 목록을 만들면
        # "진행해도 된다" 고 한 조건에서 생성이 500 을 낸다(R26 리뷰 C1).
        from backend.routers.swreport import planned_source_paths
        parts = planned_source_paths(raw_paths)
        if parts:
            out[_req.IN_LEVEL_ARTIFACTS] = _MULTI_SEP_LEVEL.join(parts)
            origins[_req.IN_LEVEL_ARTIFACTS] = {"from": "form", "key": "source_paths"}

    # 시험 결과 6종의 VectorCAST 자료는 **라우터와 같은 출처**에서 온다.
    #
    # ⚠ `linked_docs.vectorcast` 를 쓰면 안 된다 — 그건 RAG(json) 경로이고 Sw* 빌더가
    #   여는 것은 VectorCAST **로그 폴더**다. 다른 자료를 확인하고 "있다/없다" 를 말하면
    #   게이트가 조용히 딴소리를 한다.
    # ⚠ 이 폴백을 안 보면 게이트가 **거짓 차단**을 낸다(2026-08-24 실측): 보드에서
    #   SwUTCR 이 정상 생성되는데 준비 점검은 "경로 미지정 → 진행 불가" 였다.
    series = _TEST_REPORT_LOG_SERIES.get(str(req.doc_type or "").strip().lower())
    if series:
        pid = _builder_project_id(req)
        if pid:
            from backend.services.swut_meta_resolver import (
                MetaConfigUnreadable,
                config_log_folders_for,
                config_spec_path_for,
                load_meta_from_config_strict,
            )
            # ⚠ **읽을 수 있는가**를 먼저 확인한다(strict 로더). 값은 아래 `*_for` 함수가
            #   같은 캐시로 읽는다 — 그 둘이 라우터 회귀의 seam 이라 여기서 값까지 직접
            #   읽으면 seam 을 우회한다. 못 읽었으면 아래 두 키가 "경로가 지정되지 않았습니다"
            #   (missing) 로 그려져 required 입력이 **진행 불가**가 된다 → 마커를 남기고
            #   입력 루프가 `unmeasured` 로 낸다(P-3①).
            try:
                load_meta_from_config_strict(pid)
            except MetaConfigUnreadable as exc:
                # `key` 는 "그쪽 키" 계약을 지킨다 — 예외 문장은 `error` 에 따로 둔다.
                origins[_CONFIG_UNREADABLE] = {"from": "config", "key": "swut_meta.json",
                                               "error": str(exc)[:200]}
            folders = config_log_folders_for(pid, series)
            if folders:
                # 복수 폴더(APP+BOOT)는 콤마로 잇는다 — 아래 probe 가 조각별로 본다.
                out[_req.IN_VCAST] = ",".join(folders)
                origins[_req.IN_VCAST] = {"from": "config", "key": f"{series}_log_folders"}
            # 대응 시험 규격서(SwUTS/SwITS)도 같은 이유로 config 를 본다. 이것도
            # `linked_docs` 엔 없고 `swut_meta.json` 에만 등록돼 있어, 안 보면
            # **등록돼 있는데도** "경로가 지정되지 않았습니다" 가 뜬다.
            if _req.IN_SPEC_DOC not in out:
                spec_path = config_spec_path_for(pid, series)
                if spec_path:
                    out[_req.IN_SPEC_DOC] = spec_path
                    origins[_req.IN_SPEC_DOC] = {"from": "config", "key": f"{series}s_docx_path"}
    for doc_key, input_key in _DOC_KEY_TO_INPUT.items():
        if doc_key == "template":
            # 문서별 템플릿을 먼저 보고, 없으면 공용 `template`(구 설정) 로 폴백한다.
            # 형식이 다른 자리에 같은 경로를 넣던 것이 원래 결함이므로 전용 키가 우선이다.
            # ⚠ 레지스트리엔 공용 `template` 필드가 없다(`ScmLinkedDocs`) — 그 폴백은
            #   설정(doc_paths) 쪽에서만 실제로 값이 나온다.
            specific = _TEMPLATE_KEY_BY_DOC.get(str(req.doc_type or "").strip().lower())
            v, origin = _pick(specific, "template") if specific else _pick("template")
        else:
            v, origin = _pick(doc_key)
        if v:
            out[input_key] = v
            origins[input_key] = origin
    return out, origins


def _read_doc_material(path: str) -> Dict[str, Any]:
    """요구문서를 **worker 경유로** 읽고 요구 인식 건수를 센다."""
    from backend.helpers.common import _is_allowed_req_doc
    from backend.services.resolver_helpers import read_requirement_doc_via_resolver

    text, reason = read_requirement_doc_via_resolver(path, allow=_is_allowed_req_doc)
    if reason:
        return {"ok": False, "reason": reason, "chars": 0, "items": None}
    items = None
    try:
        from report_gen.requirements import generate_uds_requirements_preview
        items = len((generate_uds_requirements_preview([text]) or {}).get("items") or [])
    except Exception as exc:  # noqa: BLE001 — 파서 계열 예외가 광범위
        _logger.warning("preflight: 요구 인식 실패 — %s", exc, exc_info=True)
        return {"ok": True, "reason": "", "chars": len(text), "items": None,
                "items_reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return {"ok": True, "reason": "", "chars": len(text), "items": items}


def _uds_normalize_unmatched(value: Any) -> "tuple[str, str]":
    """남의 함수 절 처리 정규화 — **정의는 생성기가 갖는다**
    (`report_gen.docx_builder.normalize_unmatched_headings`).

    ⚠ 폴백도 **같은 방향**(모르는 값은 안 지우는 쪽)이어야 한다. 반대로 떨어지면
      폴백이 문서를 조용히 얇게 만든다 — `_suts_normalize_scope` 와 같은 규약이다.
    """
    try:
        from report_gen.docx_builder import normalize_unmatched_headings
        return normalize_unmatched_headings(value)
    except Exception:  # silent-ok: 공시는 실패해도 화면이 떠야 한다
        logging.getLogger("devops_api").debug(
            "unmatched_headings 정규화를 생성기에서 못 읽었다 — 폴백", exc_info=True)
        raw = str(value or "").strip()
        return ("drop" if raw.lower() == "drop" else "keep",
                "" if raw.lower() in ("", "keep", "drop") else raw)


# 직전 소요가 그 단계 예산의 이 비율 이상이면 경고로 올린다. **측정된 값끼리의 비**이지
# 다음 실행에 대한 추정이 아니다 — 소스 파일 수로 다음 소요를 곱해 예측하지 않는다
# (이 저장소의 `unmeasured` 규약: 모르는 것은 모른다고 적는다).
_TIGHT_BUDGET_RATIO = 0.8


def _last_run_step(req: PreflightRequest) -> Optional[Dict[str, Any]]:
    """직전 생성이 **어떻게 끝났는지** 한 행으로. 기록이 없으면 `None`.

    ## 왜 게이트에 이 축이 필요한가 (실측 근거는 `docgen_last_run` 모듈 docstring)

    게이트의 나머지 행은 전부 *지금의 입력*을 잰다. 그래서 직전 시도가 통째로 실패했어도
    (실측: 2026-08-10·08-11 재시도 사다리 끝까지 실패, 산출물 없음) 다음에 게이트를 열면
    "준비 완료" 였다. 무엇이 준비됐는지는 맞지만 **무슨 일이 있었는지**는 어디에도 없었다.

    ## 상태를 고른 이유

    - 실패·타임아웃·예외 → `degraded`(**차단 아님**). 원인이 사라졌는지 게이트는 알 수
      없으니 막지 않는다. 대신 "눌러도 되지만 같은 실패를 볼 수 있다" 를 말한다. 성공한
      생성이 한 번 나오면 이 행은 스스로 ✓ 로 돌아온다 — 원인이 사라졌음을 증명하는
      유일한 사건이 그것이라서, **자기 해소되는** 판정이다.
    - 성공했지만 **한 개도 안 실림** → `degraded`. 반영률이 낮은 것은 템플릿이 의도된
      부분집합일 수 있어 뒤집지 않는다는 것이 기존 결정이다(`_run_docx_in_subprocess`).
      다만 0 은 부분집합이 아니라 전무다.
    - `started` → `unmeasured`. 진행 중이거나 프로세스가 중단된 것이라 **결말을 모른다**.
    - 기록 없음 → **행을 내지 않는다**(모듈 docstring의 고착 사유).

    ⚠ UDS 전용이다. 체크포인트를 쓰는 것은 `_generate_docx_with_retry` 뿐이므로
      (실측: 저장소에 `stage.json` 쓰기 지점 1곳) 다른 문서 종류에 이 행을 내면
      "기록이 없다"가 곧 "생성한 적 없다"로 오독된다.
    """
    if str(req.doc_type or "").strip().lower() != "uds":
        return None
    from backend.services.docgen_last_run import (
        STATUS_EXCEPTION,
        STATUS_FAILED,
        STATUS_STARTED,
        STATUS_SUCCESS,
        STATUS_TIMEOUT,
        last_retry_stage,
        last_uds_run,
    )

    run = last_uds_run(req.cache_root, req.job_url)
    if not run:
        return None

    when = f"({run['when']}) " if run["when"] else ""
    stage = f"`{run['stage']}` 단계" if run["stage"] else "생성"
    status = run["status"]
    measured: Dict[str, Any] = {
        "status": status or None, "stage": run["stage"] or None,
        "artifact": run["artifact"], "artifact_exists": run["artifact_exists"],
        "empty_headings": run["empty_heading_count"],
        "dropped_headings": run["dropped_heading_count"],
        # ⚠ `Measured` 가 그리는 키로 낸다 — 화면이 안 읽는 키에 실으면 기록만 남고
        #   아무도 못 보는 쓰기 전용 관측량이 된다(이 저장소가 반복해 고친 형태다).
        "elapsed_seconds": run["elapsed_seconds"],
        "budget_seconds": run["budget_seconds"],
    }

    def _duration_note() -> Tuple[str, bool]:
        """`(소요 문장, 예산에 근접한가)`.

        ⚠ 못 잰 것은 **말하지 않는다**. 라운드 12 이전 기록엔 `elapsed_seconds` 가 아예
          없어서(체크포인트가 단계마다 덮어써지며 시작 시각이 지워졌다) `None` 이다 —
          0초로 접으면 "즉시 끝났다" 는 거짓이 된다.
        """
        el, bud = run["elapsed_seconds"], run["budget_seconds"]
        if not isinstance(el, (int, float)):
            return "", False
        if not isinstance(bud, int) or bud <= 0:
            return f" 이 단계 소요 {el:.0f}초.", False
        ratio = el / bud
        return (f" 이 단계 소요 **{el:.0f}초**(예산 {bud}초의 {ratio * 100:.0f}%).",
                ratio >= _TIGHT_BUDGET_RATIO)

    _dur, _tight = _duration_note()
    # 반영률은 `Measured` 가 이미 아는 두 키로 낸다 — 화면이 새 키를 배우지 않아도 보인다.
    if run["measurable"]:
        measured["value"] = run["matched_functions"]
        measured["of"] = run["payload_functions"]

    if status == STATUS_SUCCESS:
        tail = (f" 내용 없이 남은 heading {run['empty_heading_count']}개."
                if isinstance(run["empty_heading_count"], int)
                and run["empty_heading_count"] > 0 else "")
        tail += _dur
        if not run["measurable"]:
            # ⚠ "잴 수 없다" 에는 **두 가지**가 있고 뜻이 정반대다.
            #   ① payload 가 0 이라고 **기록됐다** → 실을 것이 없었다는 사실(결함).
            #   ② 수치 자체가 기록에 없다 → 아무것도 모른다(미측정).
            #   둘을 한 문장으로 합치면 ②에 대고 "실을 함수가 0개" 라는 거짓을 말한다.
            if run["payload_functions"] == 0:
                return _step(
                    "last_run", PH_HISTORY, S_DEGRADED, "직전 생성", measured=measured,
                    reason=(f"{when}{stage}까지 가서 파일은 만들어졌지만 **문서에 실을 함수가 "
                            f"0개**였습니다 — 만들어진 것은 템플릿 서식뿐입니다."
                            f"{tail} 분석이 함수를 하나도 내지 못한 것이므로 소스 경로와 "
                            f"빌드 캐시를 먼저 확인하세요."),
                )
            return _step(
                "last_run", PH_HISTORY, S_UNMEASURED, "직전 생성", measured=measured,
                reason=(f"{when}성공했지만 **반영률이 기록되지 않았습니다** — 재지 못한 "
                        f"것이지 0% 가 아닙니다.{tail} 다음 생성부터는 기록됩니다."),
            )
        if run["matched_functions"] == 0:
            return _step(
                "last_run", PH_HISTORY, S_DEGRADED, "직전 생성", measured=measured,
                reason=(f"{when}성공했지만 **분석 함수 {run['payload_functions']}개가 문서에 "
                        f"하나도 실리지 않았습니다**.{tail} 템플릿의 heading 집합이 이 "
                        f"프로젝트 함수와 맞는지 확인하세요 — 위 '템플릿 출처' 행이 "
                        f"이번에 쓸 파일을 이름 댑니다."),
            )
        # 성공했지만 **예산에 닿아 있었다** — 다음 생성이 조금만 커지면 이 단계는
        # 시간 초과로 끊기고 payload 를 줄인 다음 단계(예산은 더 짧다)로 내려간다.
        # 그건 산출물이 조용히 얇아진다는 뜻이라, 성공이어도 미리 말한다.
        _budget_warn = (" ⚠ 예산의 대부분을 썼습니다 — 소스가 늘거나 템플릿이 커지면 "
                        "다음 생성은 이 단계에서 끊기고, **payload 를 줄인 다음 단계**"
                        "(예산은 더 짧습니다)로 내려갑니다." if _tight else "")
        return _step(
            "last_run", PH_HISTORY, S_DEGRADED if _tight else S_OK, "직전 생성",
            measured=measured,
            reason=(f"{when}성공 — 분석 함수 {run['payload_functions']}개 중 "
                    f"**{run['matched_functions']}개**가 문서에 실렸습니다.{tail}"
                    f"{_budget_warn}"),
        )

    if status in (STATUS_FAILED, STATUS_TIMEOUT, STATUS_EXCEPTION):
        if status == STATUS_TIMEOUT:
            # 상한은 `_dur` 이 "예산 N초" 로 이미 말한다 — 둘 다 쓰면 같은 수를 두 번
            # 적는다. 소요를 못 잰 옛 기록에서만 여기서 상한을 든다.
            limit = run["timeout_seconds"]
            head = (f"{when}**시간이 초과**돼 끝났습니다 — {stage}"
                    f"{f', 상한 {limit}초' if limit and not _dur else ''}.")
        else:
            head = f"{when}{stage}에서 **실패**했습니다."
        cause = f" 원인: `{run['cause']}`" if run["cause"] else ""
        # 산출물 부재는 결말을 뒷받침하는 독립 증거다 — 있으면 그것도 말한다(부분 산출).
        artifact = ("" if run["artifact_exists"]
                    else " 산출물 파일도 남지 않았습니다.")
        # 체크포인트는 단계마다 **덮어쓰인다** — 남아 있는 것이 마지막으로 시도한 단계다.
        # 그게 사다리의 끝이면 재시도가 하나도 살리지 못했다는 뜻이라, 같은 '실패' 라도
        # 무게가 다르다. 사다리 정의는 생성기와 **같은 출처**를 읽는다(복제 아님).
        exhausted = ""
        if run["stage"] and run["stage"] == last_retry_stage():
            exhausted = " 재시도 사다리의 **마지막 단계**까지 전부 실패했습니다."
        return _step(
            "last_run", PH_HISTORY, S_DEGRADED, "직전 생성", measured=measured,
            reason=(f"{head}{cause}{artifact}{exhausted}{_dur} 원인이 그대로면 이번에도 "
                    f"같은 곳에서 멈춥니다 — 생성 자체는 막지 않습니다."),
        )

    if status == STATUS_STARTED:
        return _step(
            "last_run", PH_HISTORY, S_UNMEASURED, "직전 생성", measured=measured,
            reason=(f"{when}{stage}가 시작된 기록만 있고 **끝이 기록되지 않았습니다** — "
                    f"지금 진행 중이거나 프로세스가 중단된 것입니다. 성공으로 읽지 "
                    f"않습니다."),
        )

    # 모르는 결말 — 코드를 그대로 보인다(지어내지 않는다).
    return _step(
        "last_run", PH_HISTORY, S_UNMEASURED, "직전 생성", measured=measured,
        reason=(f"{when}기록의 결말이 `{status or '없음'}` 이라 해석하지 못했습니다 — "
                f"기록 파일: {run['artifact']}.stage.json"),
    )


@router.post("/api/docgen/preflight")
def docgen_preflight(req: PreflightRequest) -> Dict[str, Any]:
    """생성 전 준비 상태를 판정한다. **생성하지 않는다.**"""
    return _compute_preflight(req)


def _compute_preflight(req: PreflightRequest) -> Dict[str, Any]:
    """preflight 판정 본체.

    엔드포인트에서 분리한 이유는 **질문 생성기가 같은 판정을 써야** 하기 때문이다.
    프론트가 계산된 `steps` 를 되보내는 방식은 임의 데이터를 판정 입력으로 삼는 셈이라
    쓰지 않는다 — 서버가 같은 함수로 다시 계산한다.
    """
    from backend.services.file_resolver import get_resolver

    spec = _req.requirements_for(req.doc_type)
    resolver = get_resolver()
    inputs, origins = _resolve_inputs_with_origin(req)
    steps: List[Dict[str, Any]] = []
    available: Dict[str, bool] = {}

    # ── 0. 접근 — cloudium 이면 worker 가 살아 있어야 한다 ────────────────────
    mode = getattr(resolver, "mode", "local")
    if mode != "local":
        # 다중값 키(콤마/개행 결합)는 **첫 조각**으로 잰다 — 결합 문자열 자체는 존재하지
        # 않는 합성 경로다(리뷰 I1).
        probe_target = next(
            ((_split_multi(k, p) or [""])[0] for k, p in inputs.items()
             if k != _req.IN_SOURCE_ROOT), "",
        )
        if probe_target:
            res = _probe_path(resolver, probe_target)
            # ⚠ worker 연결 실패일 때만 "워커를 실행하세요" 다. 허용 prefix 밖 경로도
            #   같은 `S_ERROR` 로 오는데, 그건 워커가 아니라 등록의 문제라 아래 입력 행이
            #   `open_scm` 으로 안내한다(P-3③).
            if res["state"] == S_ERROR and res.get("kind") == "worker":
                steps.append(_step(
                    "worker", "access", S_ERROR, "Cloudium worker",
                    reason=res["reason"],
                    actions=[{"kind": "run_worker"}],
                ))

    # ── 1. 입력 ──────────────────────────────────────────────────────────────
    required = list(spec.get("required") or [])
    optional: Dict[str, str] = dict(spec.get("optional") or {})

    # 대응 시험 규격서는 **프로젝트마다 필수 여부가 다르다.**
    #
    # `sutr_spec_based`/`sitr_spec_based` 가 켜진 프로젝트에서는 결과 문서의
    # `3.Test Log` 시트를 규격서 시트 **통째 복사**로 만든다. 그래서 규격서가 없으면
    # 선택 입력이 빠지는 게 아니라 라우터가 **HTTP 400** 을 낸다 — 표에 `optional` 로
    # 박아 두면 게이트가 "없어도 됩니다" 라고 **거짓말**을 하게 된다(2026-08-24 실측).
    # HDPDM01 처럼 꺼진 프로젝트에서는 그대로 선택 입력이다 — 그래서 config 를 읽는다.
    #
    # ⚠ 승격 대상은 **SUTR/SITR 뿐**이다. 커버리지·종합결과는 같은 규격서를 쓰지만
    #   없어도 빌드가 성공한다(TC 대조가 빠지고 FI 칸이 노란 강조로 남을 뿐) — 실측으로
    #   `resolve_swuts_test_specs` 가 `None` 을 돌려주고 그대로 진행한다. 넷까지 required
    #   로 올리면 이번엔 게이트가 **반대 방향으로** 거짓말한다(막을 이유가 없는데 막음).
    _spec_series = _SPEC_REQUIRED_SERIES.get(str(req.doc_type or "").strip().lower())
    if _spec_series and _req.IN_SPEC_DOC in optional:
        _pid = _builder_project_id(req)
        if _pid:
            from backend.services.swut_meta_resolver import config_spec_is_required_for
            if config_spec_is_required_for(_pid, _spec_series):
                required.append(_req.IN_SPEC_DOC)
                optional.pop(_req.IN_SPEC_DOC, None)
    config_unreadable = origins.get(_CONFIG_UNREADABLE)
    if config_unreadable:
        # 양식 설정 파일이 있는데 못 읽었다 — 아래 config 유래 입력들이 "미지정" 으로
        # 보이는 이유가 이것이다. 한 번만, 판정 없이(`unmeasured`) 말한다.
        steps.append(_step(
            "meta_config", "access", S_UNMEASURED, "양식 설정(swut_meta.json)",
            reason=f"읽지 못했습니다 — {config_unreadable.get('error', '')}",
        ))
    for key in required + [k for k in optional if k not in required]:
        label = _req.INPUT_LABELS.get(key, key)
        is_required = key in required
        path = inputs.get(key, "")
        if not path:
            if config_unreadable and key in (_req.IN_VCAST, _req.IN_SPEC_DOC):
                # config 에서 왔을 키가 비어 있는데 그 config 를 못 읽었다 — "미지정"
                # 이 아니라 **모름**이다. missing 으로 접으면 required 가 곧 진행 불가다.
                steps.append(_step(
                    key, "input", S_UNMEASURED, label, required=is_required,
                    reason="양식 설정을 읽지 못해 확인할 수 없습니다",
                    effect=optional.get(key, ""),
                ))
                continue
            state = S_MISSING if is_required else S_NEEDED
            steps.append(_step(
                key, "input", state, label,
                required=is_required,
                reason="경로가 지정되지 않았습니다",
                effect=optional.get(key, ""),
                actions=[{"kind": "pick_path", "target": _INPUT_TO_DOC_KEY.get(key, key)}],
            ))
            available[key] = False
            continue

        # ⚠ 레벨별 산출물은 **항목 수와 무관하게** 이 분기다 — 1개짜리 목록을 단일 경로 분기로
        #   보내면 `required` 승격이 빠져 "준비 완료" 인데 생성은 500 이다(리뷰 확인 패스 C1).
        if key == _req.IN_LEVEL_ARTIFACTS or (
            key == _req.IN_VCAST and len(_split_multi(key, path)) > 1
        ):
            # APP+BOOT 처럼 폴더가 여럿이면 **전부** 확인한다. 첫 개만 보면 두 번째가
            # 사라져도 "확인됨" 이 되고, 산출물은 절반만 담긴 채로 나간다.
            # 통합 Summary 의 레벨별 산출물(`source_paths`)도 같은 규약이다.
            is_level = key == _req.IN_LEVEL_ARTIFACTS
            noun = "산출물" if is_level else "로그 폴더"
            parts = _split_multi(key, path)
            probes = [(x, _probe_path(resolver, x)) for x in parts]
            bad = [(x, r) for x, r in probes if r["state"] != S_OK]
            unknown = [(x, r) for x, r in probes if r["state"] in (S_UNMEASURED, S_ERROR)]
            if unknown:
                # ⚠ 조각 하나라도 **확인 못 했으면** 전체가 모름이다. `bad` 로 접으면
                #   "하나도 찾지 못했습니다"(없음) 가 되어 required 가 곧 진행 불가 —
                #   이 라운드가 단일 경로에서 없앤 접기가 옆 분기에 남아 있었다(리뷰 C2).
                st = S_ERROR if any(r["state"] == S_ERROR for _, r in unknown) else S_UNMEASURED
                why = (f"{len(parts)}개 중 {len(unknown)}개를 확인하지 못했습니다: "
                       + "; ".join(f"{Path(x).name} ({r['reason']})" for x, r in unknown))
            elif not bad:
                st, why = S_OK, ""
            elif len(bad) == len(probes):
                st, why = S_MISSING, f"등록된 {noun} 중 하나도 찾지 못했습니다"
            elif is_level:
                # 통합 Summary 는 목록을 **전부** 읽는다(`swreport.planned_source_paths`) —
                # 하나만 없어도 빌드가 500 이다. 부분 결손이 아니라 차단이다(리뷰 C1).
                st = S_MISSING
                why = (f"{len(parts)}개 중 {len(bad)}개를 찾지 못했습니다 — 하나라도 없으면 "
                       "생성이 실패합니다: " + "; ".join(Path(x).name for x, _ in bad))
            else:
                # VectorCAST 로그 폴더는 일부만 없어도 빌드가 되고 산출물만 줄어든다 —
                # **부분 결손**이다. 그 사실을 말하고 막지는 않는다.
                st = S_DEGRADED
                why = (f"{len(parts)}개 중 {len(bad)}개를 찾지 못했습니다: "
                       + "; ".join(Path(x).name for x, _ in bad))
            steps.append(_step(
                key, "input", st, label,
                # 목록을 **지정했으면** 그 전부가 있어야 한다 — 선택 입력이라도 빈 목록과
                # "지정했는데 깨진 목록" 은 다르다.
                required=is_required or (is_level and st in (S_MISSING, S_ERROR)),
                value=path, reason=why, effect=optional.get(key, ""),
                measured={"folders": len(parts), "missing": len(bad), "unknown": len(unknown)},
            ))
            _mark_available(available, key, st)
            continue

        if key == _req.IN_SOURCE_ROOT:
            # 소스 루트는 디렉터리이고 로컬이다(레지스트리 실측: 전부 C:/D:).
            first = path.split(",")[0].strip()
            ok = bool(first) and Path(first).expanduser().is_dir()
            steps.append(_step(
                key, "input", S_OK if ok else S_MISSING, label,
                required=True, value=path,
                reason="" if ok else "디렉터리를 찾을 수 없습니다",
            ))
            available[key] = ok
            continue

        res = _probe_path(resolver, path)
        state = res["state"]
        extra: Dict[str, Any] = {"value": path, "reason": res["reason"]}
        if state == S_ERROR and res.get("kind") == "prefix":
            # 워커는 살아 있는데 이 경로가 허용 prefix 밖이다 — 조치는 워커 실행이 아니라
            # SCM/파일 모드에 prefix 를 등록하는 것이다.
            extra["actions"] = [{"kind": "open_scm"}]
        if state == S_MISSING:
            suggestion = _suggest_revision(resolver, path)
            if suggestion:
                state = S_STALE
                extra["suggestion"] = suggestion
                extra["reason"] = "등록 경로에 파일이 없습니다. 같은 폴더의 개정본으로 보입니다"
                acts, note = _revision_actions(key, origins.get(key), suggestion)
                extra["actions"] = acts
                if note:
                    extra["reason"] += " — " + note
            else:
                extra["reason"] = "파일이 없습니다 — 경로가 바뀌었을 수 있습니다"
                extra["actions"] = [{"kind": "pick_path",
                                     "target": _INPUT_TO_DOC_KEY.get(key, key)}]
        # 템플릿은 **형식까지** 맞아야 한다 — 존재만으로는 부족하다.
        if key == _req.IN_TEMPLATE and state == S_OK:
            want = _TEMPLATE_EXPECTED_EXT.get(str(req.doc_type or "").lower(), ())
            ext = Path(path).suffix.lower()
            if want and ext not in want:
                state = S_MISSING
                extra["reason"] = (
                    f"생성기가 {'/'.join(want)} 를 여는데 {ext} 가 등록됐습니다 — "
                    "같은 이름의 다른 형식 파일을 확인하세요"
                )
                # 같은 이름의 올바른 확장자 파일이 **실재할 때만** 제안한다.
                for cand_ext in want:
                    cand = Path(path).with_suffix(cand_ext)
                    if _probe_path(resolver, str(cand))["state"] == S_OK:
                        state = S_STALE
                        extra["suggestion"] = cand.name
                        acts, note = _revision_actions(key, origins.get(key), cand.name)
                        extra["actions"] = acts
                        if note:
                            extra["reason"] += " — " + note
                        break

        steps.append(_step(key, "input", state, label, required=is_required,
                           effect=optional.get(key, ""), **extra))
        _mark_available(available, key, state)

    # ── 1-b. **실제로 쓸 템플릿** — 위 `template` 행이 그것이 아닐 수 있다 ────
    #
    # 생성은 `docgen_template_source.choose_template_source` 로 정하고, 그 규칙은
    # **정본(납품본)이 있으면 정본을 쓴다**(`prefer_reference=True`, 호출부 5곳 전부
    # 기본값). 그런데 게이트는 오래 설정한 표준 템플릿 경로만 보여 줬다. 그래서:
    #
    #   - 정본이 등록돼 있으면 화면이 **쓰이지도 않을 파일**에 ✓ 를 줬다.
    #   - 그 표준 템플릿이 접근 불가면 `error` 로 그려 **막힌 것처럼** 보였는데,
    #     실제 생성은 정본으로 멀쩡히 돌았다(반대 방향 거짓말).
    #
    # 템플릿이 무엇이냐는 사소하지 않다 — 표지·이력·Introduction(표기 규약 표)이 전부
    # 거기서 온다(`docgen_template_source` 모듈 docstring).
    #
    # ⚠ 규칙을 여기 복제하지 않는다. 같은 함수를 부른다(순수 경로 선택이라 IO 없음).
    if req.doc_type in ("uds", "sts", "suts", "sits"):
        _ref = _reference_doc_for(req, linked=_linked_docs(req))
        _tpl = inputs.get(_req.IN_TEMPLATE, "")
        try:
            from backend.services.docgen_template_source import (
                choose_template_source,
                prefer_reference_from,
            )
            # ⚠ 사용자가 고른 값을 **반영해서** 공시한다. 기본값을 하드코딩하면 사용자가
            #   "표준 템플릿 우선" 을 골라도 이 행은 계속 정본을 이름 댄다 —
            #   `suts_scope` 가 같은 이유로 `req.caps` 를 읽는다(같은 파일 5-b).
            _chosen, _why = choose_template_source(
                req.doc_type, registered_template=_tpl, reference_doc=_ref,
                prefer_reference=prefer_reference_from(
                    req.caps.get("template_source")),
            )
        except Exception:  # silent-ok: 공시는 실패해도 화면이 떠야 한다
            logging.getLogger("devops_api").debug("템플릿 선택 공시 실패", exc_info=True)
            _chosen, _why = "", ""
        if _why:
            _shadowed = bool(_tpl and _chosen and _chosen != _tpl)
            _tail = ""
            if _shadowed:
                _tail += (f" ⚠ 설정한 표준 템플릿(`{Path(_tpl).name}`)은 이번 생성에 "
                          f"**쓰이지 않습니다**.")
                # 폴백은 **정본을 골랐을 때만** 뜻이 있다. 표준 템플릿을 고른 상태에서
                # "실패하면 표준 템플릿으로" 라고 쓰면 자기 자신을 가리키는 헛말이다.
                _tail += " 정본을 못 읽으면 표준 템플릿으로 한 번 더 시도합니다."
            # 고른 파일이 **열리는지**까지 본다. 선택만 공시하고 접근을 안 보면,
            # 못 여는 파일을 "이걸로 만듭니다" 라고 이름 대는 셈이다.
            _tpl_state = S_OK if _chosen else S_DEGRADED
            if _chosen:
                _probe = (_probe_path(resolver, _chosen) if _chosen != _tpl
                          else {"state": S_OK if available.get(_req.IN_TEMPLATE) else S_MISSING,
                                "reason": ""})
                if _probe["state"] != S_OK:
                    _tpl_state = S_DEGRADED
                    _tail += (f" ⚠ 그런데 이 파일을 열지 못합니다"
                              f"{(' — ' + _probe['reason']) if _probe['reason'] else ''}"
                              f" — {'표준 템플릿으로 폴백합니다' if _shadowed else '서식 없이 생성됩니다'}.")
            # phase 는 **`decision`** 이다 — 이제 이 행에 선택지가 붙는다. 자료가
            # 부족해서가 아니라 사람이 정하는 축이므로 캡·범위와 같은 자리에 온다.
            _tpl_choice = (spec.get("choices") or {}).get("template_source") or {}
            steps.append(_step(
                "template_source", "decision", _tpl_state, "템플릿 출처",
                value=_chosen or "",
                measured={"registered": _tpl or None, "reference": _ref or None,
                          "shadowed": _shadowed or None,
                          # 화면이 옵션 목록을 복제하지 않도록 **서버가 내려준다**.
                          # `choice` 가 있으면 패널이 그 자리에 `<select>` 를 그린다.
                          "choice": "template_source" if _tpl_choice else None,
                          "options": _tpl_choice.get("options") or None,
                          "picked": str(req.caps.get("template_source") or "")},
                reason=_why + _tail,
            ))

    # ── 1-a. UDS 는 Jenkins **빌드 캐시**가 있어야 시작한다 ───────────────────
    #
    # `_uds_generate_from_paths`(`backend/helpers/uds.py:1504`)가 **맨 첫 줄에서**
    # `_resolve_cached_build_root` 를 부르고 없으면 `404: cached build not found` 로
    # 즉시 죽는다 — `source_only=True` 여도 마찬가지다. 실측: 소스·요구문서·템플릿이
    # 다 갖춰져 있어도 **0.0초 만에** 실패했다. 게이트가 이 전제를 몰라 "준비 완료" 로
    # 그릴 수 있었다.
    # ⚠ STS/SUTS/SITS 는 이 전제가 없다(같은 세션에서 캐시 없이 생성 성공).
    if req.doc_type == "uds":
        if not req.job_url:
            steps.append(_step(
                "build_cache", "input", S_NEEDED, "Jenkins 빌드 캐시", required=True,
                reason="프로젝트(빌드)를 먼저 선택해야 합니다",
            ))
        else:
            try:
                from backend.helpers.jenkins import _resolve_cached_build_root
                build_root = _resolve_cached_build_root(
                    req.job_url, req.cache_root, req.build_selector)
            except Exception as exc:  # noqa: BLE001 — 캐시 해석 계열이 광범위
                build_root = None
                _logger.warning("preflight: 빌드 캐시 확인 실패 — %s", exc)
            steps.append(_step(
                "build_cache", "input", S_OK if build_root else S_MISSING,
                "Jenkins 빌드 캐시", required=True, value=str(build_root or ""),
                reason="" if build_root else (
                    "내려받은 빌드 산출물이 없습니다 — 빌드를 선택해 동기화한 뒤 다시 시도하세요"),
            ))

    # ── 1-b. 사슬이 참조하는 나머지 입력도 **확인은 한다** ────────────────────
    #
    # 요구 표(`required`+`optional`)는 "이 문서를 만들려면 무엇이 필요한가" 이고, 사슬은
    # "어느 출처가 필드를 채울 수 있는가" 라 **후자가 더 넓다**. 예: UDS 의 요구 표에는
    # HSIS·UDS문서가 없지만 사슬에는 있다(각각 `local.py:603` HSIS 승격,
    # `requirements.py:1660` UDS 직독).
    #
    # 스텝을 만들지 않으면 `available` 에 키가 없어 사슬이 전부 `?`(모름)로 그려진다 —
    # 실제로는 레지스트리에 등록돼 있는데도. 화면이 '모름' 투성이가 되면 쓸모가 없다.
    # 그래서 **스텝은 요구 표대로 두되 가용성은 넓게 확인한다.**
    for key, path in inputs.items():
        if key in available or key in (_req.IN_SOURCE_ROOT, _req.IN_VCAST, _req.IN_LEVEL_ARTIFACTS):
            # 다중 경로 키는 위에서 조각별로 이미 판정했다 — 결합 문자열을 통째로 다시 probe 하면
            # 로컬 리졸버가 False 를 내 "확인했고 없음" 으로 뒤집는다(리뷰 NW2).
            continue
        # ⚠ 3상태다 — `== S_OK` 로 접으면 확인 실패가 "확인했고 없음"(✗) 이 된다(P-3②).
        _mark_available(available, key, _probe_path(resolver, path)["state"])

    # AI 출처는 문서가 아니라 **설정**이다 — 키가 있으면 그 경로가 열려 있다.
    try:
        from workflow.ai import load_oai_config
        available[_chain.INPUT_AI] = bool(load_oai_config(None))
    except Exception:  # noqa: BLE001  # silent-ok
        # 설정을 못 읽으면 '모름' 이 정답이다. `False`(없음)로 접으면 없는 결핍을 만든다.
        pass

    # ── 2. 재료 — 요구 인식 ──────────────────────────────────────────────────
    swrs_path = inputs.get(_req.IN_SWRS, "")
    if swrs_path and available.get(_req.IN_SWRS):
        mat = _read_doc_material(swrs_path)
        if not mat["ok"]:
            steps.append(_step("req_items", "material", S_UNMEASURED, "요구 인식",
                               reason=mat["reason"]))
        elif mat["items"] is None:
            steps.append(_step("req_items", "material", S_UNMEASURED, "요구 인식",
                               reason=mat.get("items_reason", "인식기를 돌리지 못했습니다"),
                               measured={"chars": mat["chars"]}))
        else:
            steps.append(_step(
                "req_items", "material",
                S_OK if mat["items"] else S_DEGRADED, "요구 인식",
                measured={"value": mat["items"], "chars": mat["chars"]},
                reason="" if mat["items"] else "문서는 읽혔는데 요구 0건 — 경로가 아니라 양식 문제입니다",
            ))

    # ── 3. 재료 — 소스 주석 (캐시가 있을 때만) ───────────────────────────────
    src = inputs.get(_req.IN_SOURCE_ROOT, "")
    if src and available.get(_req.IN_SOURCE_ROOT):
        cov = _cov.measure(src) if _cov.has_cached(src) else None
        if cov is not None and cov.get("reason"):
            # 측정을 시도했지만 못 쟀다 — `0` 으로 그리면 "주석이 하나도 없다" 가 된다.
            # ⚠ `available[comment]` 를 **설정하지 않는다**. 설정하면 사슬이 그 출처를
            #   "확인했고 없음"(X)으로 그리는데 실제로는 모르는 상태다.
            steps.append(_step(
                "comment_coverage", "material", S_UNMEASURED, "소스 주석",
                reason=str(cov["reason"]),
                actions=[{"kind": "measure_source"}],
            ))
        elif cov is not None:
            fn = cov["functions"]
            filled = cov["description"]["filled"]
            subst = cov["description"]["substantive"]
            steps.append(_step(
                "comment_coverage", "material",
                S_OK if subst and fn and subst >= fn * 0.5 else S_DEGRADED,
                "소스 주석",
                measured={"functions": fn, "filled": filled, "substantive": subst,
                          "scanned_files": cov["scanned_files"], "partial": cov["partial"]},
                reason=(f"설명 {filled}개 중 실질 내용은 {subst}개 — 나머지는 양식 라벨만 있습니다"
                        if cov["substantive_gap"] else ""),
                samples=cov["samples"],
                # 건수만으로는 못 고친다 — 파일·함수명 목록을 내보낼 수 있게 한다.
                actions=([{"kind": "export_comment_targets"}]
                         if (cov["substantive_gap"] or filled < fn) else []),
            ))
            available[_chain.INPUT_SOURCE_COMMENT] = bool(subst)
            steps.append(_step(
                "asil_tags", "material",
                S_OK if cov["asil"]["filled"] else S_DEGRADED, "소스 @asil 태그",
                measured={"value": cov["asil"]["filled"], "of": fn},
            ))
        else:
            steps.append(_step(
                "comment_coverage", "material", S_UNMEASURED, "소스 주석",
                reason="아직 측정하지 않았습니다 — 소스 파싱은 수십 초 이상 걸립니다",
                actions=[{"kind": "measure_source"}],
            ))

    # ── 3-b. 재료 — 시험 문서 전용 (STS 요구매핑 / SITS 흐름 / SUTS 타입) ─────
    #
    # UDS 는 필드를 채우지만 시험 문서는 **시험 케이스를 합성한다**. 재료가 없으면
    # 문서가 안 만들어지는 게 아니라 **틀린 시험값이 만들어진다**.
    #
    # ⚠ STS 는 오래 이 게이트 밖에 있었다. 그런데 STS 야말로 재료가 없어도 TC 가
    #   나온다 — 매핑이 빈 요구는 `_generate_review_steps` 로 **소스 근거 0** 인
    #   리뷰 절차가 채워지고, 요구 커버리지는 100% 로 보인다.
    _MATERIAL_DOCS = ("sts", "sits", "suts")
    _MATERIAL_LABEL = "요구 매핑 / 통합 흐름 / 변수 타입"
    # ⚠ 캐시 조회에 **측정 때와 같은 문서 경로**를 넘긴다. 예전엔 키가 `source_root`
    #   하나라, 설정에서 SwDS 를 바꿔도 캐시가 그대로 맞아 이미 교체된 문서로 잰 수치를
    #   최대 15분 동안 "지금 값" 으로 보고했다. 양쪽이 같은 `_resolve_inputs` 를 쓴다.
    _tm_paths = _tm_lookup_paths(inputs)
    if req.doc_type in _MATERIAL_DOCS and src and available.get(_req.IN_SOURCE_ROOT):
        # ⚠ `has_cached()` 로 먼저 묻지 않는다 — 둘 다 내용 서명을 계산하느라 소스
        #   트리를 os.walk 한다(실측 99파일 33ms). `cached()` 는 없으면 `None` 이라
        #   물음 하나로 충분하다.
        tm = _tm.cached(src, **_tm_paths)
        if tm is None:
            steps.append(_step(
                "test_materials", "material", S_UNMEASURED, _MATERIAL_LABEL,
                reason="아직 측정하지 않았습니다 — 소스 파싱은 수십 초 이상 걸립니다",
                actions=[{"kind": "measure_source"}],
            ))
        elif not tm.get("ok"):
            steps.append(_step("test_materials", "material", S_UNMEASURED,
                               _MATERIAL_LABEL, reason=str(tm.get("reason") or "")))
        else:
            # ── 이 수치가 **언제** 잰 것인가 ──────────────────────────────────
            #
            # 아래 행들은 전부 캐시된 측정에서 나온다(파싱이 수십 초라 요청 안에서 다시
            # 재지 않는다). 그런데 화면은 그 사실을 말하지 않아 15분 전 수치가 방금 잰
            # 것처럼 보였다. 게다가 캐시 키는 **경로만** 담아서, 같은 경로의 SwDS 를
            # 열어 고쳐도 키가 같아 옛 수치가 그대로 유효로 남았다.
            #
            # 이제 로컬 경로면 `(mtime,size)` 서명으로 내용 변경까지 잡는다. cloudium
            # (`U:`)은 worker IPC 에 `stat` op 이 없어 잡을 수 없다 — 그 사실을 숨기지
            # 않고 `ttl_only` 로 표시한다. 모르는 것을 최신이라고 말하지 않는다.
            _meas_at = tm.get("measured_at")
            _fresh_kind = str(tm.get("freshness") or "")
            if _meas_at:
                _age_min = max(0, int((time.time() - float(_meas_at)) // 60))
                _verified = _fresh_kind == "verified"
                steps.append(_step(
                    "materials_freshness", "material",
                    S_OK if _verified else S_DEGRADED, "측정 시점",
                    measured={"age_minutes": _age_min, "freshness": _fresh_kind or None},
                    reason=(
                        f"{_age_min}분 전에 잰 값입니다 — 소스·문서가 바뀌면 자동으로 "
                        f"다시 잽니다(내용 서명 대조)."
                        if _verified else
                        f"{_age_min}분 전에 잰 값입니다. ⚠ 원격 경로라 **파일이 바뀌어도 "
                        f"감지하지 못합니다** — 최대 15분 동안 옛 수치가 그대로 보입니다. "
                        f"문서를 고쳤다면 [소스 측정]으로 다시 재세요."
                    ),
                    actions=[{"kind": "measure_source"}],
                ))
            if req.doc_type == "sits":
                s = tm["sits"]
                # ⚠ "절단 0" 이 아니라 **여유**를 본다. 실측: KJPDS02 는 후보 120 /
                #   캡 120 으로 여유가 0 이라, 함수가 하나만 늘어도 조용히 잘린다.
                # ⚠ 측정은 **생성기 기본 캡**(120)으로 잰 것이다. 사용자가 상한을
                #   정했으면 그 값으로 다시 재야 한다 — 안 그러면 같은 패널의 두 행이
                #   서로 다른 캡을 말한다. 실측: 50 으로 낮췄는데 이 행은 계속
                #   "25개가 빠집니다"(실제 95) = **70건 과소보고**, 200 으로 올려도
                #   "빠집니다" 라고 했다. `flows_total` 은 캡 없이 잰 후보 총량이라
                #   재측정 없이 계산된다(`docgen_test_materials._measure_sits`).
                _eff_flows = _cap_user_value(req.caps, "max_flows") or int(s["cap"] or 0)
                _flow_head = _eff_flows - int(s["flows_total"] or 0)
                steps.append(_step(
                    "sits_flows", "material",
                    S_DEGRADED if _flow_head <= 0 else S_OK, "통합 흐름",
                    measured={"value": s["flows_total"], "of": _eff_flows,
                              "headroom": _flow_head},
                    # ⚠ 이미 잘리는 것과 곧 잘릴 것은 다른 말이다. 라이브에서 여유가
                    #   **-25**(즉 25개가 이미 빠지는 중)인데 "함수가 늘면 잘리기
                    #   시작한다" 는 미래형 문구가 나왔다 — 현재 손실을 예고로 읽게 한다.
                    reason=(
                        f"흐름 {abs(_flow_head)}개가 상한({_eff_flows})을 넘어 시험 규격에서 "
                        "빠집니다 — 안전등급이 높은 쪽부터 남지만, 빠진 흐름은 문서에 "
                        "존재하지 않습니다"
                        if _flow_head < 0
                        else ("여유가 없습니다 — 함수가 늘면 그 순간부터 흐름이 잘립니다"
                              if _flow_head == 0 else "")
                    ),
                    sample=s.get("sample_flow"),
                ))
                # ⚠ Related 칸을 실제로 채우는 건 SwDS 가 아니라 **SwUDS** 다. SDS 파티션
                #   맵에는 SwCom 축이 아예 없어 `sds_swcom_hits` 는 **구조적으로 0** 이고
                #   (`_measure_sits` docstring), 그걸 판정에 쓰면 이 스텝은 **영구 빨간불**
                #   이면서 문구는 "추적성 열이 합성 ID 만 남습니다" 라 산출물과 정반대를
                #   말한다 — 라이브 실측으로 같은 프로젝트에서 SwCom **699 토큰**이 실린다.
                #   판정은 SwUDS 축으로 옮기고, SwDS 0 은 참고값으로 계속 노출한다
                #   (0 을 숨기는 것과 0 으로 판정하는 것은 다른 문제다).
                uds_hits = s.get("uds_hits")
                uds_info = s.get("uds") or {}
                steps.append(_step(
                    "sits_related_source", "material",
                    S_OK if uds_hits else S_DEGRADED, "Related ID 보강 (SwUDS)",
                    measured={"value": uds_hits, "lookups": s.get("uds_lookups"),
                              "related_ids": s.get("uds_related_ids"),
                              # 진입 함수 자신 vs 호출 트리 아래 — 근거의 거리가 다르다
                              "chain_flows": s.get("related_chain_flows"),
                              "chain_ids": s.get("related_chain_ids"),
                              # SwDS 축은 구조적으로 0 — 숨기지 않되 판정엔 안 쓴다
                              "sds_swcom_hits": s.get("sds_swcom_hits"),
                              "sds_map_entries": s.get("sds_map_entries")},
                    reason=("" if uds_hits else
                            (str(uds_info.get("reason") or "")
                             or "SwUDS 를 읽었지만 Related ID 를 하나도 얻지 못했습니다 — "
                                "추적성 열이 합성 ID 만 남습니다")),
                ))
            if req.doc_type in ("suts", "sits"):
                t = tm["suts"]
                total = t["variables"]
                steps.append(_step(
                    "suts_types", "material",
                    S_OK if total and t["fallback"] == 0 else S_DEGRADED,
                    "입출력 변수 타입 근거",
                    measured={"value": t["grounded"], "of": total,
                              "fallback": t["fallback"]},
                    reason=(f"{t['fallback']}개가 근거 없이 uint8_t(0~255)로 채워집니다 — "
                            "실제 폭이 다르면 경계값 시험이 틀립니다"
                            if t["fallback"] else ""),
                    samples=t.get("fallback_samples"),
                ))
            if req.doc_type == "suts":
                # 입력 변수가 하나도 없는 unit — 그 시퀀스는 **넣을 값이 없어** 시험이
                # 성립하지 않는다. ⚠ 0 이 전부 결함은 아니다(정본 1,005 중 172 건이 0).
                # 그래서 건수만이 아니라 **사유별**로 낸다 — 안 나누면 "정상 0" 과
                # "잃어버린 0" 이 한 숫자에 섞여 판단할 수가 없다.
                z = tm.get("suts_inputs") or {}
                if z.get("measured"):
                    _n, _units = z["units_without_input"], max(z["units"], 1)
                    _ref = z["reference_without_input"] * 100.0 / max(z["reference_units"], 1)
                    _pct = _n * 100.0 / _units
                    steps.append(_step(
                        "suts_inputs", "material",
                        S_OK if _pct <= _ref else S_DEGRADED,
                        "입력 변수가 없는 unit",
                        measured={"value": _n, "of": z["units"],
                                  "causes": z.get("causes") or {},
                                  "reference_pct": round(_ref, 1)},
                        reason=(
                            f"{_n}개({_pct:.1f}%) — 정본은 {_ref:.1f}% 입니다. "
                            "사유가 `no_params_no_globals` 면 정상이고, 그 외는 재료를 놓친 것입니다"
                            if _pct > _ref else ""
                        ),
                        samples=[
                            f"{c}: {', '.join(v[:4])}"
                            for c, v in (z.get("cause_samples") or {}).items()
                        ],
                    ))
                # 안전 판정의 **근거**. 값을 바꾸자는 게 아니라(대안 6개가 다 더 나빴다 —
                # `suts._resolve_unit_asil`), 그 등급이 파티션 이름의 부분문자열 첫
                # 일치로 정해졌다는 사실을 ISO 26262 문서 앞에서 숨기지 않는다.
                a = tm.get("suts_asil") or {}
                if a.get("measured"):
                    _fz, _cf = a.get("fuzzy", 0), a.get("fuzzy_conflict", 0)
                    steps.append(_step(
                        "suts_asil_evidence", "material",
                        S_OK if not (_fz or _cf) else S_DEGRADED,
                        "안전 등급의 근거",
                        measured={"value": _fz + _cf, "of": a.get("graded", 0),
                                  "units": a.get("units", 0), "conflict": _cf},
                        reason=(
                            f"{_fz + _cf}개 unit 의 안전 등급이 SwDS 파티션 이름의 "
                            f"**부분문자열 첫 일치**로 정해졌습니다"
                            + (f" (그중 {_cf}개는 후보 등급까지 갈립니다 = 사전 순서가 "
                               "등급을 정했습니다)" if _cf else "")
                            + " — SwUDS 를 주면 그 표가 먼저 결정합니다"
                            if (_fz or _cf) else ""
                        ),
                        samples=list(a.get("samples") or []),
                    ))
            if req.doc_type == "sts":
                # 요구가 **함수 근거를 갖고** 시험되는가. 매핑이 빈 요구도 TC 는 나오므로
                # (`_generate_review_steps`) 이 축이 없으면 근거 0 인 TC 가 커버리지
                # 100% 뒤에 숨는다.
                m = tm.get("sts_mapping") or {}
                if not m.get("measured"):
                    steps.append(_step(
                        "sts_req_mapping", "material", S_UNMEASURED,
                        "요구-함수 매핑", reason=str(m.get("reason") or ""),
                    ))
                else:
                    _tot = max(int(m.get("requirements") or 0), 1)
                    _mapped = int(m.get("mapped") or 0)
                    _unmapped = _tot - _mapped
                    # 설계-ID 브리지가 꺼져 있으면 **그것부터** 말한다. 안 그러면
                    # "SwDS 엔 있는데 못 닿음" 이 코드 결함처럼 읽히는데, 실제로는
                    # SwUDS 를 안 줘서 브리지가 안 돈 것일 수 있다(실측 16 요구 차이).
                    _br = m.get("bridge") or {}
                    _br_off = "" if _br.get("on") else (
                        f" · 설계-ID 브리지 꺼짐({_br.get('reason') or '사유 미상'}) — "
                        "SwUDS 를 주면 설계 파티션에만 걸린 요구까지 닿습니다"
                    )
                    steps.append(_step(
                        "sts_req_mapping", "material",
                        S_OK if not _unmapped else S_DEGRADED, "요구-함수 매핑",
                        measured={"value": _mapped, "of": m.get("requirements"),
                                  "causes": m.get("causes") or {},
                                  "bridge": _br},
                        reason=(
                            f"{_unmapped}개 요구가 함수에 안 붙었습니다 — 그 요구의 TC 는 "
                            "소스 근거 없이 리뷰 절차로만 만들어집니다"
                            + (f" ({m['sds_reason']})" if m.get("sds_reason") else "")
                            + _br_off
                            if _unmapped else ""
                        ),
                        samples=[
                            f"{c}: {', '.join(v[:4])}"
                            for c, v in (m.get("cause_samples") or {}).items()
                        ],
                    ))
                    # ⚠ 상한이 버리는 함수는 **하한**이다. 한 함수가 여러 TC 를 내면
                    #   상한이 더 일찍 차므로 실제로는 더 빠진다(실측 715 vs 887).
                    # 사용자가 상한을 정했으면 그 값으로 다시 센다(SITS 와 같은 이유).
                    # 재계산은 원래와 **같은 방식**이어야 한다 — 요구별 목록에서 앞
                    # `cap` 개만 남기고 **고유 함수 집합의 차**를 센다. 분포 합으로
                    # 세면 여러 요구에 걸친 함수를 중복 계상해 과대보고가 된다.
                    _eff_tc = (_cap_user_value(req.caps, "max_tc_per_req")
                               or int(m.get("cap") or 0))
                    _lists = m.get("req_fid_lists") or []
                    if _lists and _eff_tc > 0:
                        _all = {f for row in _lists for f in row}
                        _kept = {f for row in _lists for f in row[:_eff_tc]}
                        _beyond = len(_all - _kept)
                        _over = sum(1 for row in _lists if len(row) > _eff_tc)
                    else:
                        _beyond = int(m.get("functions_beyond_cap") or 0)
                        _over = m.get("requirements_over_cap")
                    steps.append(_step(
                        "sts_tc_cap", "material",
                        S_OK if not _beyond else S_DEGRADED, "요구당 TC 상한",
                        measured={"value": m.get("mapped_functions"), "cap": _eff_tc,
                                  "beyond_cap": _beyond,
                                  "requirements_over_cap": _over},
                        reason=(
                            f"매핑된 함수 {m.get('mapped_functions')}개 중 **최소** "
                            f"{_beyond}개가 요구당 상한({_eff_tc})에 걸려 시험되지 "
                            f"않습니다. 남는 {_eff_tc}개가 무엇인지는 관련성이 아니라 "
                            "**함수 순서**가 정합니다"
                            if _beyond else ""
                        ),
                    ))

    # ── 4. 사슬 — 각 필드를 채울 경로의 단계별 가용성 ─────────────────────────
    available[_chain.INPUT_CALL_GRAPH] = bool(available.get(_req.IN_SOURCE_ROOT))
    for field in (spec.get("fields") or []):
        rows = _chain.chain_state(field, available)
        grounded = [r for r in rows if r["grounded"]]
        have_any = any(r["have"] is True for r in grounded)
        # ⚠ 전부 `None`(확인 못 함)이면 "확보되지 않았다" 가 아니라 **모른다**다(리뷰 W5).
        all_unknown = bool(grounded) and all(r["have"] is None for r in grounded)
        steps.append(_step(
            f"chain_{field}", "chain",
            S_OK if have_any else (S_UNMEASURED if all_unknown else S_DEGRADED),
            f"{_chain.FIELD_LABELS.get(field, field)} 출처",
            chain=grounded,
            # ⚠ 칸 수를 예고하지 않는다(모듈 docstring 규약).
            reason=("" if have_any else
                    "출처를 하나도 확인하지 못했습니다" if all_unknown else
                    "근거 있는 출처가 하나도 확보되지 않았습니다"),
        ))

    # ── 4-a. 시험 결과 3종 — **양식 템플릿** ─────────────────────────────────
    #
    # 이 셋의 템플릿은 SCM 레지스트리가 아니라 `config/swut_meta.json` 의
    # `template_paths` 가 **프로젝트별로** 관리한다(정본을 옮기면 갈라진다). 문제는
    # 게이트가 그 존재를 확인한 적이 없다는 것이다 — 실측 비대칭:
    #   HDPDM01 6키(통합 Summary용 `es95411_template` **없음**) / KJPDS02 9키
    #   그리고 `swut_meta` 에 등록된 프로젝트는 둘뿐인데 SCM 은 셋이다.
    # 없으면 [생성]을 눌러야 알 수 있었다.
    if req.doc_type in _req.TEST_REPORT_DOC_TYPES:
        tpl_key = _TEST_REPORT_TEMPLATE_KEY.get(req.doc_type, "")
        # 폼에 명시된 값이 우선, 없으면 **SCM 이 지정한 양식 키**를 쓴다.
        # SCM id 와 양식 project_id 는 다른 어휘라(예: `kjpds02_pv` ↔ `KJPDS02`)
        # 레지스트리가 그 매핑을 갖는다.
        project_id = str(req.form.get("project_id") or "").strip()
        if not project_id and req.scm_id:
            try:
                from backend.services.scm_registry import get_registry_entry
                entry = get_registry_entry(req.scm_id)
                project_id = str(getattr(entry, "builder_project_id", "") or "").strip()
            except Exception:  # noqa: BLE001  # silent-ok
                # 레지스트리를 못 읽으면 '미지정' 으로 두고 아래에서 사유를 낸다.
                project_id = ""
        state, reason, value = S_UNMEASURED, "", ""
        if not project_id:
            state, reason = S_NEEDED, "대상 project_id 를 먼저 정해야 템플릿을 찾을 수 있습니다"
        else:
            meta: Optional[Dict[str, Any]]
            try:
                # ⚠ strict 변형이다 — 빌드용 `load_meta_from_config` 는 읽기 실패를 `{}` 로
                #   삼켜 "프로젝트 미등록" 과 구별이 안 된다. 게이트가 그 `{}` 를 받으면
                #   "설정에 없다"(missing) → required → **진행 불가**로 굳는다 — config 를
                #   못 읽은 순간 시험 결과 6종 전부가 차단됐다(2026-09-03 감사 P-3①).
                from backend.services.swut_meta_resolver import load_meta_from_config_strict
                meta = load_meta_from_config_strict(project_id) or {}
            except Exception as exc:  # noqa: BLE001 — config 로딩 계열이 광범위
                # 읽기 실패는 `None`(모름)이다 — `{}`(없음)과 접지 않는다.
                meta = None
                reason = f"양식 설정을 읽지 못했습니다 ({type(exc).__name__}: {str(exc)[:100]})"
            paths = (meta or {}).get("template_paths") or {}
            if meta is None:
                state = S_UNMEASURED
            elif not meta:
                state = S_MISSING
                reason = reason or (f"`{project_id}` 가 양식 설정(swut_meta)에 없습니다 — "
                                    "회사 표준 양식을 찾을 수 없습니다")
            elif not paths.get(tpl_key):
                state = S_MISSING
                reason = f"`{project_id}` 에 `{tpl_key}` 양식이 등록돼 있지 않습니다"
            else:
                value = str(paths[tpl_key])
                probe = _probe_path(resolver, value)
                state = probe["state"]
                reason = probe["reason"] or ("" if state == S_OK else "양식 파일을 찾지 못했습니다")
                if state == S_MISSING:
                    # 등록 경로만 보여 주면 "왜 없는지" 를 사람이 U: 드라이브를 열어
                    # 확인해야 한다. 그 폴더의 실제 파일을 함께 낸다(증거이지 판정 아님).
                    reason += _folder_contents_hint(resolver, value)
        steps.append(_step(
            "report_template", "input", state, "결과 양식(템플릿)",
            required=True, value=value, reason=reason,
            actions=[{"kind": "open_scm"}] if state != S_OK else [],
        ))

    # ── 4-b. 시험 결과 3종 — 빌더 폼 필수값 ──────────────────────────────────
    #
    # ⚠ `release_sw_version` 만은 **기본값을 만들지 않는다.** 임의 버전을 찍으면
    #   ISO 26262 납품 문서 표지에 틀린 릴리스가 박힌다 — 화면이 조용히 만든 거짓 증거다.
    if req.doc_type in _req.TEST_REPORT_DOC_TYPES:
        for field in _req.TEST_REPORT_FORM_FIELDS:
            filled = str(req.form.get(field) or "").strip()
            steps.append(_step(
                f"form_{field}", "decision",
                S_OK if filled else S_NEEDED, field,
                value=filled,
                reason="" if filled else "값이 필요합니다 — 임의 값으로 채우지 않습니다",
                actions=[] if filled else [{"kind": "input_value", "target": field}],
            ))

    # ── 5. 캡 — 자료 부족이 아니라 사용자 결정 ───────────────────────────────
    #
    # ⚠ 예전엔 **모든** 캡을 무조건 `S_NEEDED` 로 냈다. 그래서 UDS/STS/SUTS/SITS 는
    #   입력을 아무리 완비해도 verdict 가 영원히 `needs_decision` 이라 "준비 완료" 가
    #   한 번도 뜨지 않았다 — 게이트의 최상위 신호가 죽어 있었다. 게다가 조정할 수
    #   **없는** 캡까지 "결정 필요" 라 해서, 사용자가 할 수 없는 일을 조치 목록에 남겼다.
    #   이제 셋을 가른다: 조정 불가(공시) / 사용자가 정함 / 아직 안 정함.
    # 조정 불가 상한이라도 **실제로 자르고 있는지**는 말해야 한다. `ok` 로만 두면
    # "안 잘린다" 로 읽혀, 상한을 공시하는 이유 자체가 사라진다.
    #
    # 소스 파싱 캐시(`docgen_test_materials`)에 절단 통계가 있으면 그것으로 판정하고,
    # 없으면 재지 않는다(측정은 실측 41~368초). 캐시 키는 소스 루트 + **그때 쓴 문서
    # 경로**라, 같은 자료로 잰 다른 문서 게이트의 측정은 여기서도 그대로 쓰인다.
    _tm_cached: Dict[str, Any] = {}
    if src and available.get(_req.IN_SOURCE_ROOT):
        _tm_cached = _tm.cached(src, **_tm_paths) or {}

    for cap_name, cap in (spec.get("caps") or {}).items():
        adjustable = bool(cap.get("adjustable"))
        measured: Dict[str, Any] = {
            "api_default": cap.get("api"),
            "generator_default": cap.get("generator"),
            "adjustable": adjustable,
        }
        reason = str(cap.get("effect") or "")
        if not adjustable:
            # 왜 못 바꾸는지를 반드시 말한다. **env 와 코드 상수는 다른 말이다** —
            # 뭉뚱그리면 있지도 않은 환경변수를 찾아 헤매게 된다.
            env = str(cap.get("env") or "")
            via = (f"환경변수 `{env}` 로만 조정할 수 있습니다" if env
                   else "코드 상수로 고정돼 있어 화면에서 바꿀 수단이 없습니다")
            measured["adjust_via"] = via
            reason = f"{reason} — {via}" if reason else via
            # 3단 사다리 — 안 재봤음 / 재봤고 자름 / 재봤고 안 자름.
            # ⚠ 예전엔 셋을 전부 `ok` 로 접었다. 조정 못 하는 상한이라도 **지금 자르고
            #   있으면** 그 사실이 상태에 나와야 한다. `degraded` 는 차단이 아니다(§2).
            _obs = _cap_truncation(cap_name, _tm_cached)
            if _obs is _NO_MEASURE:
                state = S_OK
                reason = f"{reason} (이 상한의 절단량은 측정하지 않습니다)"
            elif _obs is None:
                state = S_UNMEASURED
                reason = f"{reason} (절단 여부는 아직 재지 않았습니다)"
            elif _obs:
                state = S_DEGRADED
                measured.update(_obs["measured"])
                reason = f"{_obs['reason']} — {via}"
            else:
                state = S_OK
        else:
            # ⚠ 판정은 **실효값**으로 한다 — 사용자가 정했으면 그 값, 아니면 API 기본값.
            #   예전엔 `picked` 로만 재서 같은 산출에 두 판정이 나왔다: SUTS 를 안 건드리면
            #   `needed`(손실 언급 없음), 기본값과 **똑같은 24** 를 직접 넣으면 `degraded`
            #   "6개가 빠집니다". 만들어지는 문서는 완전히 같은데 게이트가 문서가 아니라
            #   **사용자의 타이핑**을 재고 있었다. 그 반대편 결함이 더 크다 — STS 는 기본
            #   5 로 두면 매핑 함수 1,028개 중 상당수가 무시험인데, 아무 숫자도 안 넣은
            #   기본 상태에서는 게이트가 그 손실을 한 번도 말하지 않았다.
            picked = _cap_user_value(req.caps, cap_name)
            if picked is not None:
                measured["user_value"] = picked
            # ⚠ 조정 가능해졌다고 `env` 를 지우지 않는다. 요청에 값을 안 실으면 그
            #   환경변수가 **서버 기본값을 정한다** — 화면이 그걸 안 말하면 "기본 1200"
            #   이 어디서 온 수인지 알 방법이 없다(예전엔 "이것으로만 조정 가능" 이라는
            #   더 강한 말로 실려 있었고, 그 문장만 지우면 정보까지 함께 사라졌다).
            _env = str(cap.get("env") or "")
            if _env:
                measured["default_from_env"] = _env
                reason = f"{reason} (서버 기본값은 환경변수 `{_env}` 가 정합니다)"
            _api = cap.get("api")
            eff = picked if picked is not None else (_api if isinstance(_api, int) else None)
            _tot = _cap_full_total(cap_name, cap, _tm_cached)
            if _tot is None:
                # 잴 수 있는 축인데 아직 안 쟀다 → `ok` 도 `needed` 도 아니다. 여기서
                # `needed` 를 내면 "결정하라" 면서 결정에 필요한 수를 못 주는 꼴이 된다.
                state = S_UNMEASURED
                reason = f"{reason} (전량을 아직 재지 않아 이 상한이 자르는지 알 수 없습니다)"
            elif _tot is _NO_MEASURE:
                # ── 전량은 못 재도 **지금 자르는가**는 잴 수 있는 축이 있다 ────────
                #
                # UDS 두 상한이 그렇다. `uds_file_scan` 은 상한에 닿는 즉시 break 하므로
                # 전체 파일 수를 **모른다**(`uds_generator.py` 주석). 그래서 "전부 담으려면
                # 얼마" 는 못 말하지만 "지금 잘리고 있다" 는 정확히 말할 수 있다.
                #
                # ⚠ 이 사다리는 원래 **조정 불가** 가지에만 있었다. 두 상한을 조정
                #   가능으로 바꾸면서 그대로 두었더니, 실제로 잘리고 있는데도 행이
                #   `unmeasured` 로 바뀌어 **측정된 손실이 화면에서 사라졌다**(기존
                #   가드 5건이 잡았다). 조정 가능 여부는 손실 보고와 직교한다.
                _obs = _cap_truncation(cap_name, _tm_cached)
                if _obs is _NO_MEASURE:
                    # 전량도 절단량도 잴 축이 없다(STS `max_steps_per_tc`). `unmeasured`
                    # 로 두면 verdict 가 영구 고착된다 — `ok` 로 두되 안 잰다고 말한다.
                    state = S_OK
                    reason = f"{reason} (이 상한의 절단량은 측정하지 않습니다)"
                elif _obs is None:
                    # 이 가지는 '전량' 이 아니라 **절단 여부**를 재는 축이다. 위쪽
                    # 문구를 그대로 쓰면 재고 있는 대상이 뭔지 어긋난다.
                    state = S_UNMEASURED
                    reason = f"{reason} (절단 여부는 아직 재지 않았습니다)"
                elif _obs:
                    state = S_DEGRADED
                    measured.update(_obs["measured"])
                    _sug = _cap_suggested_from_truncation(cap_name, _tm_cached)
                    if _sug is not None:
                        measured["suggested"] = _sug
                        measured["suggested_basis"] = _SUG_MEASURED
                    reason = f"{reason} — {_obs['reason']}"
                    if picked is not None and picked != _cap_measured_at(cap_name, _tm_cached):
                        # 측정은 **그때 쓰던 상한**으로 잰 것이다. 사용자가 값을 바꿨는데
                        # 그 사실을 안 밝히면 지금 고른 값으로 잰 수치처럼 읽힌다.
                        reason += (f" (이 수치는 상한 "
                                   f"{_cap_measured_at(cap_name, _tm_cached)} 으로 잰 것입니다 "
                                   f"— {picked} 로 다시 만들면 달라집니다)")
                else:
                    state = S_OK
                    reason = f"{reason} — 측정 기준 이 상한에 걸려 빠지는 항목은 없습니다"
            elif eff is None:
                state = S_NEEDED   # adjustable 인데 api 기본이 없다 = 계약 불일치(가드가 잡는다)
            else:
                _full, _basis = int(_tot["value"]), _tot["basis"]
                _short = _full - eff
                if _short > 0:
                    measured["suggested"] = _full
                    measured["suggested_basis"] = _basis
                    measured["below_full"] = _short
                    # ⚠ 두 축의 주장 강도가 다르다. 실측 축은 "빠진다", 카탈로그 축은
                    #   "최대 …까지 빠질 수 있다" — 후자를 단언으로 쓰면 손실을 부풀린다.
                    _loss = (f"전량 {_full} 중 {_short}개가 빠집니다"
                             if _basis == _SUG_MEASURED else
                             f"후보 최대 {_full}종 중 **최대 {_short}종**까지 빠질 수 있습니다"
                             f"(함수마다 후보 수가 달라 실제 손실은 더 적을 수 있습니다)")
                    # 아직 안 정했으면 **결정 대기**, 정했으면 받아들인 degrade 다.
                    # 둘 다 손실은 같은 문장으로 말한다.
                    if picked is None:
                        state = S_NEEDED
                        reason = f"{reason} — 아직 정하지 않아 기본값 {eff} 로 만듭니다. {_loss}"
                    else:
                        # `ok` 로 두면 "정했다" 가 "충분하다" 로 읽힌다
                        # (degraded 는 차단이 아니다 — 모듈 규약 §2).
                        state = S_DEGRADED
                        reason = f"{reason} — {eff} 로 정했습니다. {_loss}"
                else:
                    # 전량을 담는다 → 결정할 것이 없다. 예전엔 이 경우에도 `needed` 라
                    # 4개 문서가 `준비 완료` 에 닿을 수 없었다(고치려던 결함 그 자체).
                    state = S_OK
                    if picked is not None and eff > _full:
                        # 상한의 상한 — 이 이상 올려도 담을 것이 없다. 막지는 않는다.
                        measured["over_suggested"] = True
                        reason = (f"{reason} — {eff} 로 정했지만 {_full} 이상은 "
                                  f"더 담을 것이 없습니다")
                # ASIL 축은 이 상한에서만 실질이 있다 — MC/DC 가 맨 끝이라 먼저 잘린다.
                # 일반론("ASIL D 는 MC/DC 필수")을 **이 소스의 수**로 바꾼다.
                if cap_name == "max_sequences":
                    _risk = _mcdc_risk(_tm_cached, eff, _full)
                    if _risk is not None:
                        measured.update(_risk)
                        if _risk["mcdc_at_risk"]:
                            reason += (f" ⚠ 이 소스에 **ASIL D 함수가 {_risk['asil_d']}개** "
                                       f"있습니다 — MC/DC 는 전략 목록 맨 끝이라 이 상한에 "
                                       f"가장 먼저 잘립니다(ISO 26262-6: ASIL D 는 MC/DC 필수)")
                        elif not _risk["asil_d"]:
                            # 없는 위험을 경고로 남겨 두면 진짜 경고가 묻힌다.
                            reason += " (측정 기준 이 소스에 ASIL D 함수는 없습니다)"
                        else:
                            # ASIL D 는 있는데 상한이 후보 전량을 담는 경우. 앞의 정적
                            # 문구("MC/DC 가 맨 끝이라 잘립니다")가 그대로 남으면 `ok`
                            # 행에 살아 있는 경고가 붙어 **자기모순**이 된다 —
                            # 그 문장은 기본값을 말한 것이지 지금 고른 값이 아니다.
                            reason += (f" (상한이 후보 전량이라 ASIL D 함수 "
                                       f"{_risk['asil_d']}개의 MC/DC 도 잘리지 않습니다)")
        # ⚠ `input_value` 액션을 붙이지 않는다. 조정 가능하면 입력칸이 그 행에 있고,
        #   조정 불가면 누를 이유가 없다. 예전엔 무조건 붙어서, 누르면 보드가
        #   "해당 빌더 탭에서 조정합니다"(`DocGenStatusBoard.jsx:668`)라며 **그런 탭이
        #   없는 곳**으로 사용자를 보냈다.
        #
        # 대신 **못 잰 행에는 재는 수단**을 준다. 이걸 빼면 "아직 재지 않았습니다" 가
        # 막다른 길이 된다 — UDS 는 재는 버튼이 어디에도 없어(`measure_source` 는
        # sts/sits/suts 행에만 붙었다) 두 상한이 영영 `unmeasured` 로 남고 verdict 가
        # `unknown` 에 고착됐다. 상태만 정직해지고 사용자는 아무것도 할 수 없던 셈이다.
        _cap_actions = ([{"kind": "measure_source"}]
                        if state == S_UNMEASURED and src and available.get(_req.IN_SOURCE_ROOT)
                        else [])
        steps.append(_step(f"cap_{cap_name}", "decision", state, cap_name,
                           measured=measured, reason=reason, actions=_cap_actions))

    # ── 5-a. ASIL 등급 — 상한과 달리 **문서 내용을 바꾼다** ──────────────────
    #
    # `generators/sts.py:1719` 는 이 값으로 요구별 ASIL 빈 칸을 역채움하고,
    # `is_safety_asil` 판정이 시험 생성 갈래를 가른다. 표지의 "ASIL Level" 칸도 이것이다.
    # 그런데 화면은 오래 이 값을 **보내지 않았다** — 백엔드는 `Form("")` 로 받고 있었고
    # Sw* 빌더 폼엔 입력칸이 있는데, 문서 4종만 배선이 빠져 항상 빈 값으로 생성됐다.
    #
    # ⚠ 빈 값을 `QM` 으로 채우지 않는다. 근거 없는 등급을 지어내면 하류가 그걸 사실로
    #   쓴다(저장소 규약 `[[project_asil_no_fabrication]]`). 대신 **무엇이 달라지는지**를
    #   말하고 사람이 정하게 둔다.
    # ⚠ **UDS 는 제외한다.** 핸들러(`/api/jenkins/uds/generate-async`)가 `asil_level` 을
    #   선언하지 않아 보내도 FastAPI 가 조용히 버린다 — 행을 내면 사용자는 골랐다고 믿는데
    #   문서는 그대로인 **거짓 통제**가 된다(2026-08-31 에 실제로 그렇게 만들었다).
    #   받게 고치는 것도 답이 아니다: UDS 의 ASIL 은 함수별 증거에서 온다
    #   (`uds_generator:1408` — Doxygen `@asil` → SwDS 맵 → 없으면 `TBD`, 출처는
    #   `asil_source` 에 남는다). 프로젝트 기본값을 주입하면 정직한 `TBD` 전체를 지어낸
    #   등급으로 덮는다(`[[project_asil_no_fabrication]]`). UDS 의 ASIL 표면은 이미
    #   `chain_asil` 행이 맡고 있으므로 여기 또 내면 두 목소리가 된다.
    if req.doc_type in ("sts", "suts", "sits"):
        _asil = str(req.asil_level or "").strip().upper()
        steps.append(_step(
            "asil_level", "decision", S_OK if _asil else S_NEEDED, "프로젝트 ASIL 등급",
            measured={"value": _asil or None},
            reason=(
                f"**{_asil}** 로 만듭니다 — 요구별 ASIL 이 빈 칸은 이 값으로 채워지고, "
                f"안전 관련 판정이 그에 따라 갈립니다."
                if _asil else
                "설정되지 않았습니다 — 표지의 ASIL 칸이 비고, 요구별 ASIL 이 빈 항목은 "
                "**빈 채로 남습니다**(안전 관련 시험 갈래가 켜지지 않습니다). "
                "빈 값을 QM 으로 채우지는 않습니다 — 근거 없는 등급은 지어내지 않습니다. "
                "옆에서 바로 고르세요(설정 > 공통 메타 > ASIL 레벨과 같은 값입니다)."
            ),
        ))

    # ── 5-b. 시험 범위 — 캡과 같은 성격의 **사용자 결정** ────────────────────
    # SUTS 는 SwUDS(단위 설계서) 기반 문서다. 납품 정본도 그 범위이므로 기본은
    # `suds`(설계 ID 가 있는 함수만)다. 소스에는 그보다 많은 함수가 있어(실측 1,160 vs
    # 정본 1,005) 전부 시험하면 정본에 없는 항목이 섞인다 — 어느 쪽을 원하는지는
    # 사람이 정한다. 기본값은 **생성기가 갖고 화면은 복제하지 않는다**.
    if req.doc_type == "suts":
        # ⚠ 사용자가 고른 값을 읽어야 한다. 안 읽으면 화면의 `<select>` 는 "소스 전체" 를
        #   보이는데 바로 옆 문구는 "기본은 정본 기준입니다" 라 **자기모순**이 된다.
        # ⚠ 판정 규칙을 여기에 **복제하지 않는다**. 예전엔 게이트가 `== "source"`, 생성기가
        #   `== "suds" else 전체` 라 서로 여집합을 봤다 — `sud` 같은 값 하나에 게이트는
        #   "정본 기준", 생성기는 "소스 전체" 로 **반대말**을 했다(그쪽이 위험한 방향).
        _scope, _scope_bad = _suts_normalize_scope(req.caps.get("suts_scope"))
        _scope_reason = (
            "현재 **소스 전체**입니다 — SwUDS 와 대조하지 않으므로 정본에 없는 함수가 "
            "규격서에 들어갑니다(실측 소스 1,160 vs 정본 1,005)."
            if _scope == "source" else
            "기본은 정본 기준입니다 — SwUDS 설계 ID 가 있는 함수만 시험합니다. "
            "소스 전체를 시험하려면 바꾸세요(정본에 없는 함수가 포함됩니다)."
        )
        _scope_choice = (spec.get("choices") or {}).get("suts_scope") or {}
        steps.append(_step(
            "scope", "decision", S_OK if not _scope_bad else S_DEGRADED, "시험 범위",
            measured={"value": _scope, "stored": _scope_bad or None,
                      # 옵션의 단일 출처는 `docgen_requirements` 의 `choices` 표다.
                      # 오래 화면·라우터·가드가 각자 목록을 손으로 들고 있었다.
                      "choice": "suts_scope" if _scope_choice else None,
                      "options": _scope_choice.get("options") or None,
                      "picked": str(req.caps.get("suts_scope") or "")},
            reason=(f"저장된 값 `{_scope_bad}` 을 알 수 없어 기본값으로 되돌렸습니다 — "
                    f"{_scope_reason}" if _scope_bad else _scope_reason),
        ))

    # ── 5-c. 직전 생성의 결말 — 지금의 입력이 아니라 **기록**이다 ─────────────
    # 판정을 여기 인라인하지 않는다. 인라인이면 가드가 "행이 있는가" 같은 모양밖에 못
    # 보고, 실제 결말별 판정은 전체 생성 없이는 검증할 수 없다(라운드 4가 `apply_scope`
    # 를 추출한 것과 같은 사유).
    _last = _last_run_step(req)

    # ── 5-d. 정본에만 있는 남의 함수 절 — 남길 것인가 ────────────────────────
    # 판단 축이라 **고르게 한다**. 다만 근거 없이 물으면 사용자는 답할 수 없으므로,
    # 직전 생성이 실제로 몇 개를 빈 서식으로 남겼는지를 같은 행에서 말한다
    # (그 수는 이미 읽어 온 기록에 있다 — 다시 조회하지 않는다).
    if req.doc_type == "uds":
        _um, _um_bad = _uds_normalize_unmatched(req.caps.get("unmatched_headings"))
        _um_choice = (spec.get("choices") or {}).get("unmatched_headings") or {}
        _um_measured = (_last or {}).get("measured") or {}
        _um_last = _um_measured.get("empty_headings")
        _um_dropped = _um_measured.get("dropped_headings")
        # 소요와 이 선택은 **같은 원인**을 공유한다 — 빈 서식을 만드는 일이 생성 시간의
        # 대부분이다(실측 HDPDM01 정본: 빈 heading 402개에서 278초, 지우면 39초).
        # 직전이 오래 걸렸다면 여기가 지렛대라는 사실을 그 자리에서 말한다.
        _um_elapsed = _um_measured.get("elapsed_seconds")
        _um_time = (" 직전 생성 소요의 대부분이 그 서식을 만드는 데 쓰입니다."
                    if isinstance(_um_elapsed, (int, float))
                    and isinstance(_um_last, int) and _um_last > 0 else "")
        if isinstance(_um_dropped, int) and _um_dropped > 0:
            # ⚠ 직전 실행이 이미 `drop` 이었으면 그 수는 `empty` 가 아니라 여기 있다.
            #   `empty` 만 보면 "직전엔 0개가 남았다" = "지울 이유가 없다" 로 읽혀,
            #   방금 지운 사실이 다음 판단에서 사라진다.
            _um_evidence = f" 직전 생성에서는 **{_um_dropped}개**를 지웠습니다."
        elif isinstance(_um_last, int):
            # 0 도 근거다 — "이 템플릿에서는 남는 게 없었다" 는 고를 이유가 없다는 뜻이다.
            _um_evidence = f" 직전 생성에서는 **{_um_last}개**가 그렇게 남았습니다."
        else:
            # 기록이 없으면 수를 지어내지 않는다 — 재고 나서 고르라고 말한다.
            _um_evidence = " 직전 생성 기록이 없어 몇 개인지는 **아직 재지 못했습니다**."
        _um_reason = (
            "이번 분석에 없는 함수 절을 **지웁니다** — 분석한 함수만 담긴 문서가 됩니다. "
            "정본을 부분집합으로 쓰는 경우가 아니라면 되돌리세요."
            if _um == "drop" else
            "정본 템플릿에 있고 이번 분석에 없는 함수 절은 **빈 서식으로 남습니다** — "
            "무엇이 분석되지 않았는지 문서에 드러납니다(기본)."
        ) + _um_evidence + _um_time
        steps.append(_step(
            "unmatched_headings", "decision", S_OK if not _um_bad else S_DEGRADED,
            "남의 함수 절", measured={
                # ⚠ `of` 를 쓰지 않는다 — `Measured` 가 `value / of` 로 그리므로
                #   "keep / 978" 이라는 뜻 없는 분수가 된다. 수는 사유 문장에 있다.
                "value": _um, "stored": _um_bad or None,
                "choice": "unmatched_headings" if _um_choice else None,
                "options": _um_choice.get("options") or None,
                "picked": str(req.caps.get("unmatched_headings") or "")},
            reason=(f"저장된 값 `{_um_bad}` 을 알 수 없어 기본값으로 되돌렸습니다 — "
                    f"{_um_reason}" if _um_bad else _um_reason),
        ))

    if _last:
        steps.append(_last)

    # ── verdict — 오독 위험이 큰 순서로 ──────────────────────────────────────
    states = {s["state"] for s in steps}
    blocked = any(
        s["state"] in (S_MISSING, S_STALE, S_ERROR) and s.get("required")
        for s in steps
    ) or S_ERROR in states
    if blocked:
        verdict = V_BLOCKED
    elif S_NEEDED in states:
        verdict = V_NEEDS_DECISION
    elif S_UNMEASURED in states:
        verdict = V_UNKNOWN
    elif S_DEGRADED in states:
        verdict = V_DEGRADED
    else:
        verdict = V_READY

    return {
        "ok": True,
        "doc_type": req.doc_type,
        "label": spec.get("label", req.doc_type),
        "unknown_doc_type": bool(spec.get("unknown_doc_type")),
        "verdict": verdict,
        "file_mode": mode,
        "steps": steps,
    }


@router.post("/api/docgen/questions")
def docgen_questions(req: PreflightRequest) -> Dict[str, Any]:
    """결정 항목을 **자연어 질문**으로 낸다.

    ## 왜 preflight 와 분리했나

    preflight 는 행을 펼칠 때마다 도는 동기 API 이고 LLM 은 수 초다. 한 응답에 묶으면
    준비 상태 표시 전체가 LLM 을 기다린다. preflight 가 먼저 오고 질문이 뒤따른다.

    ## 판정을 다시 계산한다

    프론트가 계산된 `steps` 를 되보내지 않는다 — 임의 데이터를 판정 입력으로 삼는 셈이다.
    서버가 `_compute_preflight` 로 같은 판정을 다시 만든다.
    """
    from backend.services import docgen_questions as _q

    pf = _compute_preflight(req)
    built = _q.build_questions(req.doc_type, pf.get("steps") or [])
    return {
        "ok": True,
        "doc_type": req.doc_type,
        "verdict": pf.get("verdict"),
        **built,
    }


class AttributionRequest(BaseModel):
    run_id: int
    scm_id: str = ""
    doc_paths: Dict[str, str] = Field(default_factory=dict)
    source_root: str = ""


@router.post("/api/docgen/attribution")
def docgen_attribution(req: AttributionRequest) -> Dict[str, Any]:
    """생성된 문서에서 **"이 칸이 왜 비었나"** 를 사슬로 거슬러 올라간다.

    ## 무엇이 없었나

    필드별 채움률·TBD 잔여·출처 분포는 **이미 산출된다**(품질 지표 + 신뢰도 사이드카).
    없던 것은 그 분포를 **입력 축으로 환산**하는 일이다 — `asil_source` 가 `default`
    435건이라는 사실만으로는 무엇을 해야 할지 알 수 없고, "1순위 소스 `@asil` 0건 ·
    2순위 SwDS 미연결" 로 바꿔야 조치가 보인다.

    ## ⚠ 두 시점을 섞지 않는다

    출처 분포는 **생성 당시** 산출이고 입력 가용성은 **지금** 이다. 지금 SwDS 를
    연결했다고 과거 산출물이 달라지지 않으므로, 응답은 두 값을 나란히 두고 시점이
    다르다는 사실(`timing_note`)을 함께 낸다. 한쪽으로 합치면 "이미 고쳤는데 왜 아직
    비어 있나" 라는 오독이 생긴다.

    ## 경로 입력 표면

    사이드카 경로는 **클라이언트가 보내지 않는다** — DB 의 `output_path` 에서 온다
    (`quality.get_run_evidence` 와 같은 규약).
    """
    try:
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun
    except ImportError:
        raise HTTPException(status_code=503, detail="quality module not available") from None

    init_db()
    with get_session() as session:
        run = session.query(GenerationRun).filter_by(id=req.run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail=f"run_id {req.run_id} not found")
        output_path = run.output_path
        doc_type = str(run.doc_type or "")

    try:
        from report_gen.evidence import read_evidence
    except ImportError:
        raise HTTPException(status_code=503, detail="evidence module not available") from None

    ev = read_evidence(output_path or "")
    conf = ev.get("confidence") or {}
    if not conf.get("present"):
        # 부재를 빈 결과로 접지 않는다 — 사유 없이 `[]` 를 주면 "원인이 없다" 로 읽힌다.
        return {
            "ok": True, "run_id": req.run_id, "doc_type": doc_type,
            "output_path": output_path,
            "available": False,
            "reason": conf.get("reason") or "신뢰도 사이드카가 없습니다",
            "fields": [],
        }

    # 현재 입력 가용성 — preflight 와 **같은 해석**을 쓴다(두 화면이 갈리지 않게).
    from backend.services.file_resolver import get_resolver
    resolver = get_resolver()
    inputs = _resolve_inputs(PreflightRequest(
        doc_type=doc_type or "uds", scm_id=req.scm_id,
        doc_paths=req.doc_paths, source_root=req.source_root,
    ))
    available: Dict[str, bool] = {}
    for key, path in inputs.items():
        if key == _req.IN_SOURCE_ROOT:
            first = path.split(",")[0].strip()
            available[key] = bool(first) and Path(first).expanduser().is_dir()
        else:
            # preflight 와 같은 3상태(`_mark_available`) — 확인 실패는 키를 만들지 않는다.
            _mark_available(available, key, _probe_path(resolver, path)["state"])

    dist_by_field = {
        "asil": _chain.parse_source_distribution(conf.get("asil_sources")),
        "related": _chain.parse_source_distribution(conf.get("related_sources")),
        "description": _chain.parse_source_distribution(conf.get("description_sources")),
    }
    fields = [_chain.attribute_field(f, d, available) for f, d in dist_by_field.items()]

    return {
        "ok": True,
        "run_id": req.run_id,
        "doc_type": doc_type,
        "output_path": output_path,
        "available": True,
        "total_functions": conf.get("total_functions"),
        "overall_score": conf.get("overall_score"),
        "grade": conf.get("grade"),
        "fields": fields,
        "timing_note": ("출처 분포는 **생성 당시** 값이고 입력 가용성은 **지금** 입니다 — "
                        "지금 자료를 채워도 이미 만들어진 문서는 달라지지 않습니다."),
    }


class AdoptDocPathRequest(BaseModel):
    scm_id: str
    doc_key: str = Field(..., description="srs/sds/uds/hsis/stp/template")
    # ⚠ **파일명만** 받는다. 전체 경로를 받으면 임의 경로를 레지스트리에 심을 수 있다.
    #   부모 디렉터리는 기존 등록 경로에서 가져오므로 폴더를 벗어날 수 없다.
    filename: str


@router.post("/api/docgen/adopt-doc-path", dependencies=[Depends(require_admin)])
def docgen_adopt_doc_path(req: AdoptDocPathRequest) -> Dict[str, Any]:
    """낡은 등록 경로를 **같은 폴더의 개정본**으로 교체한다.

    실측(인계 문서): `kjpds02` 는 SRS 를 `_v2.03_….docx` 로 등록했는데 폴더엔
    `_v3.01_…_R.docx` 하나뿐이었다. 문서가 개정되며 파일명이 바뀌면 등록이 조용히 낡고,
    화면은 "문서가 있는데 없다고 나온다" 가 된다.

    ## 왜 설정 복사가 아니라 레지스트리 갱신인가

    설정(`doc_paths`)에 복사하면 **그 순간 또 굳는다** — 다음 개정 때 같은 문제가 나고,
    이번엔 설정이 SCM 을 가려서 더 안 보인다. 진실원은 레지스트리다.

    ## 입력 표면

    `filename` 만 받고 부모 디렉터리는 **기존 등록 경로**에서 온다. 경로 구분자가 섞인
    이름은 거부한다 — 그래야 등록된 폴더 밖을 가리킬 수 없다.
    """
    from backend.schemas import ScmLinkedDocs, ScmUpdateRequest
    from backend.services.file_resolver import get_resolver
    from backend.services.scm_registry import get_registry_entry, update_entry

    doc_key = str(req.doc_key or "").strip().lower()
    # 문서별 템플릿 키(`uds_template` 등)도 교체 대상이다 — 템플릿도 개정되며 파일명이 바뀐다.
    # ⚠ 화이트리스트와 **스키마 필드**를 둘 다 본다 — 목록에 있어도 `ScmLinkedDocs` 에
    #   없는 키(예전의 공용 `template`)는 아래 `linked.get` 이 늘 None 이라 "기존 등록
    #   경로가 없습니다" 로만 끝났다. 어느 쪽이 갈려도 여기서 400 으로 드러난다.
    if doc_key not in _ADOPTABLE_DOC_KEYS or doc_key not in ScmLinkedDocs.model_fields:
        raise HTTPException(status_code=400, detail=f"알 수 없는 문서 키: {req.doc_key}")

    name = str(req.filename or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="파일명만 지정할 수 있습니다")

    entry = get_registry_entry(req.scm_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")

    linked = entry.linked_docs.model_dump(mode="json")
    current = linked.get(doc_key)
    current_path = str((current[0] if isinstance(current, list) and current else current) or "")
    if not current_path:
        raise HTTPException(status_code=400, detail=f"{doc_key} 에 기존 등록 경로가 없습니다")

    parent = str(Path(current_path).parent)
    new_path = str(Path(parent) / name)

    # 교체 전에 **실물을 확인**한다. 없는 파일로 바꾸면 문제를 옮기기만 한다.
    resolver = get_resolver()
    probe = _probe_path(resolver, new_path)
    if probe["state"] != S_OK:
        raise HTTPException(
            status_code=400,
            detail=f"교체 대상을 확인하지 못했습니다: {probe['reason'] or '파일 없음'}",
        )

    # 리스트형 키(복수 등록)는 첫 항목만 바꾸고 나머지는 보존한다.
    if isinstance(current, list):
        linked[doc_key] = [new_path, *current[1:]]
    else:
        linked[doc_key] = new_path

    updated = update_entry(
        req.scm_id, ScmUpdateRequest(linked_docs=ScmLinkedDocs.model_validate(linked)),
    )
    return {"ok": True, "doc_key": doc_key, "old": current_path, "new": new_path,
            "item": updated.model_dump(mode="json")}


class CommentTargetsRequest(BaseModel):
    source_root: str
    max_files: int = 300


@router.post("/api/docgen/comment-targets")
def docgen_comment_targets(req: CommentTargetsRequest) -> Dict[str, Any]:
    """주석이 없거나 **내용이 비어 있는** 함수 목록.

    건수만으로는 아무도 못 고친다 — 파일·함수명이 있어야 개발자가 실제로 주석을 단다.
    실측(HDPDM01): `comment_desc` 380개 중 **277개가 `'Function  |'`**(양식 라벨만)이라
    "주석 없음"(55개)보다 "내용 없음"이 훨씬 많다. 두 갈래를 **구분해서** 낸다.

    ⚠ 캐시가 없으면 재지 않는다(무겁다). 먼저 `measure-source` 를 부를 것.
    """
    if not _cov.has_cached(req.source_root, max_files=req.max_files):
        return {"ok": False, "reason": "아직 측정하지 않았습니다 — 먼저 소스를 측정하세요",
                "targets": []}
    return {"ok": True, **_cov.list_comment_targets(req.source_root, max_files=req.max_files)}


class MeasureSourceRequest(BaseModel):
    source_root: str
    max_files: int = 300
    # 시험 문서(STS/SITS/SUTS)면 통합 흐름·변수 타입·요구 매핑까지, UDS 면 분류별·
    # 파일 스캔 상한의 **실제 절단량**까지 잰다. 파서가 달라 비용이 별개다.
    doc_type: str = ""
    # ⚠ 아래 세 경로는 **직접 지정 시에만** 쓴다. 기본은 `scm_id`+`doc_paths` 로
    #   서버가 `_resolve_inputs` 를 돌려 정한다 — 프론트가 제 나름의 우선순위로
    #   경로를 고르면 **판정이 두 벌**이 되고, 그 결과 preflight 의 캐시 조회 키와
    #   어긋나 측정을 해도 게이트가 계속 `unmeasured` 로 남는다.
    scm_id: str = ""
    doc_paths: Dict[str, str] = Field(default_factory=dict)
    sds_path: str = ""
    # STS 축(요구-함수 매핑)에만 쓴다. 없으면 그 축은 **미측정**으로 남는다 —
    # 요구 목록이 없으면 "몇 개가 근거 없이 시험되는가" 를 셀 수가 없다.
    srs_path: str = ""
    # 설계-ID 브리지(SwUDS Related ID → 설계 ID → SwDS → 요구)의 좌측 끝.
    # 없으면 브리지가 **꺼진 채로** 재고, 그 사실을 `sts_mapping.bridge` 로 낸다.
    uds_path: str = ""


@router.post("/api/docgen/measure-source")
def docgen_measure_source(req: MeasureSourceRequest) -> Dict[str, Any]:
    """소스 재료를 **실제로 측정**한다(느리다 — 실측 41~368초).

    preflight 와 분리한 이유는 `docgen_comment_coverage.has_cached` docstring 참조.
    결과는 캐시되어 이후 preflight 가 즉시 싣는다.

    ⚠ 두 측정은 **다른 파서**를 쓴다(`parse_c_project` vs `generate_uds_source_sections`).
    한쪽 캐시가 있다고 다른 쪽이 있는 게 아니므로 각각 판정한다.
    """
    out: Dict[str, Any] = {
        "ok": True,
        "comment_coverage": _cov.measure(req.source_root, max_files=req.max_files),
    }
    # ⚠ `uds` 가 여기 들어 있어야 한다. UDS 게이트의 두 상한(`max_source_files`·
    #   `max_items_per_category`)이 **실제로 자르고 있는가** 는 `_tm.measure` 가 내는
    #   `uds_category_caps`/`uds_file_scan` 에서만 나온다. 오래 시험 문서 3종만 재서,
    #   UDS 행에 `소스 측정` 버튼을 붙여도 눌러 봐야 그 통계가 안 채워졌다 —
    #   200 과 토스트만 돌아오고 화면은 그대로인 **거짓 통제**가 된다.
    if str(req.doc_type or "").strip().lower() in ("sts", "sits", "suts", "uds"):
        # 경로 해석은 **게이트와 같은 함수**로 한다. 그래야 캐시 키가 맞고, 어느 문서를
        # 근거로 쟀는지에 대해 두 화면이 같은 말을 한다. 명시 인자는 덮어쓰기로만 둔다.
        _resolved = _tm_lookup_paths(_resolve_inputs(PreflightRequest(
            doc_type=req.doc_type or "uds", scm_id=req.scm_id,
            doc_paths=req.doc_paths, source_root=req.source_root,
        )))
        paths = {
            "sds_path": req.sds_path or _resolved["sds_path"],
            "srs_path": req.srs_path or _resolved["srs_path"],
            "uds_path": req.uds_path or _resolved["uds_path"],
        }
        out["test_materials"] = _tm.measure(req.source_root, **paths)
        # 어느 문서로 쟀는지를 응답에 남긴다 — 캐시가 안 맞을 때 되짚을 유일한 단서다.
        out["measured_with"] = paths
    return out


class SaveAsRequest(BaseModel):
    """생성된 산출물을 사용자가 고른 폴더로 내보낸다.

    생성 위치 자체는 신뢰 루트 하위로 confine 돼 있어 바꿀 수 없다(경계). 그래서
    "경로 선택" 은 **완료된 파일의 내보내기**로 푼다 — 근거는 `docgen_output` docstring.
    """

    src_path: str = Field(..., description="생성 응답의 output_path")
    dest_dir: str = Field(..., description="사용자가 고른 폴더 (이미 존재해야 함)")
    overwrite: bool = False


# 파일시스템에 쓰는 동작이라 `adopt-doc-path` 와 같은 등급으로 막는다. 폴더 선택
# (`/api/file-mode/browse-file`)이 이미 admin 전용이므로 여기만 열어 두면 비대칭이다.
@router.post("/api/docgen/save-as", dependencies=[Depends(require_admin)])
def docgen_save_as(req: SaveAsRequest) -> Dict[str, Any]:
    """산출물을 지정 폴더로 복사한다. 거절 사유는 `code` 로 구분 가능하게 돌려준다."""
    import shutil

    # `local._allowed_request_roots()` 와 **같은 목록**이어야 한다("폴더는 열리는데
    # 저장은 거절" 같은 모순 방지). 라우터끼리 얽지 않는 대신 드리프트 가드로 묶는다
    # (`test_docgen_output.py::test_src_roots_match_local_router`).
    _repo_root = Path(__file__).resolve().parents[2]

    try:
        src, dest = _out.resolve_save_target(
            req.src_path,
            req.dest_dir,
            allowed_src_roots=_out.default_src_roots(_repo_root),
            overwrite=bool(req.overwrite),
        )
    except _out.SaveTargetError as exc:
        # 400 으로 내되 `code` 를 실어 화면이 "덮어쓸까요?" 같은 후속을 물을 수 있게 한다.
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc

    try:
        shutil.copy2(str(src), str(dest))
    except Exception as exc:
        _logger.warning("docgen save-as copy failed: %s -> %s: %s", src, dest, exc)
        raise HTTPException(
            status_code=500,
            detail={"code": "copy_failed", "message": f"복사 실패: {exc}"},
        ) from exc
    return {"ok": True, "path": str(dest), "folder": str(dest.parent)}
