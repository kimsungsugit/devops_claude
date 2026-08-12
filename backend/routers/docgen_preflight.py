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
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.dependencies.admin import require_admin
from backend.services import docgen_comment_coverage as _cov
from backend.services import docgen_field_sources as _chain
from backend.services import docgen_output as _out
from backend.services import docgen_requirements as _req
from backend.services import docgen_test_materials as _tm

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

_TEST_REPORT_TEMPLATE_KEY = {
    "sutr": "sutr_template",
    "sitr": "swit_sitr_template",
    "swreport": "es95411_template",
}


class PreflightRequest(BaseModel):
    doc_type: str = Field(..., description="uds/sts/suts/sits/sutr/sitr/swreport")
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


def _step(step_id: str, phase: str, state: str, label: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": step_id, "phase": phase, "state": state, "label": label}
    out.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return out


def _probe_path(resolver: Any, path: str) -> Dict[str, Any]:
    """존재 3상태. ⚠ 확인 실패를 `missing` 으로 접지 않는다(`scm.py:294` 와 같은 규약)."""
    try:
        return {"state": S_OK if resolver.exists(path) else S_MISSING, "reason": ""}
    except PermissionError as exc:
        return {"state": S_ERROR, "reason": f"접근 거부 — {str(exc)[:160]}"}
    except Exception as exc:  # noqa: BLE001 — resolver/IPC 계열이 광범위하다
        return {"state": S_UNMEASURED, "reason": f"확인 실패 ({type(exc).__name__}: {str(exc)[:120]})"}


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
        name = str(n.get("name") if isinstance(n, dict) else n)
        if not name or name == p.name:
            continue
        if kind is None or kind(Path(name).name):
            cands.append(name)
    return cands[0] if len(cands) == 1 else ""


def _resolve_inputs(req: PreflightRequest) -> Dict[str, str]:
    """입력 키 → 경로. 우선순위는 **설정(doc_paths) > SCM 레지스트리**(기존 정책)."""
    from backend.services.scm_registry import get_registry_entry

    linked: Dict[str, Any] = {}
    source_root = req.source_root
    if req.scm_id:
        entry = get_registry_entry(req.scm_id)
        if entry is not None:
            linked = entry.linked_docs.model_dump(mode="json")
            source_root = source_root or (entry.source_root or "")

    def _pick(*keys: str) -> str:
        """설정(doc_paths) > 레지스트리 순, 그리고 **앞선 키가 이긴다**."""
        for key in keys:
            v = str(req.doc_paths.get(key) or "").strip()
            if v:
                return v
        for key in keys:
            raw = linked.get(key)
            v = str((raw[0] if isinstance(raw, list) and raw else raw) or "").strip()
            if v:
                return v
        return ""

    out: Dict[str, str] = {}
    if source_root:
        out[_req.IN_SOURCE_ROOT] = source_root
    for doc_key, input_key in _DOC_KEY_TO_INPUT.items():
        if doc_key == "template":
            # 문서별 템플릿을 먼저 보고, 없으면 공용 `template`(구 설정) 로 폴백한다.
            # 형식이 다른 자리에 같은 경로를 넣던 것이 원래 결함이므로 전용 키가 우선이다.
            specific = _TEMPLATE_KEY_BY_DOC.get(str(req.doc_type or "").strip().lower())
            v = _pick(specific, "template") if specific else _pick("template")
        else:
            v = _pick(doc_key)
        if v:
            out[input_key] = v
    return out


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
    inputs = _resolve_inputs(req)
    steps: List[Dict[str, Any]] = []
    available: Dict[str, bool] = {}

    # ── 0. 접근 — cloudium 이면 worker 가 살아 있어야 한다 ────────────────────
    mode = getattr(resolver, "mode", "local")
    if mode != "local":
        probe_target = next(
            (p for k, p in inputs.items() if k != _req.IN_SOURCE_ROOT), ""
        )
        if probe_target:
            res = _probe_path(resolver, probe_target)
            if res["state"] == S_ERROR:
                steps.append(_step(
                    "worker", "access", S_ERROR, "Cloudium worker",
                    reason=res["reason"],
                    actions=[{"kind": "run_worker"}],
                ))

    # ── 1. 입력 ──────────────────────────────────────────────────────────────
    required = list(spec.get("required") or [])
    optional: Dict[str, str] = dict(spec.get("optional") or {})
    for key in required + [k for k in optional if k not in required]:
        label = _req.INPUT_LABELS.get(key, key)
        is_required = key in required
        path = inputs.get(key, "")
        if not path:
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
        if state == S_MISSING:
            suggestion = _suggest_revision(resolver, path)
            if suggestion:
                state = S_STALE
                extra["suggestion"] = suggestion
                extra["reason"] = "등록 경로에 파일이 없습니다. 같은 폴더의 개정본으로 보입니다"
                extra["actions"] = [{"kind": "adopt_suggestion", "value": suggestion}]
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
                        extra["actions"] = [{"kind": "adopt_suggestion", "value": cand.name}]
                        break

        steps.append(_step(key, "input", state, label, required=is_required,
                           effect=optional.get(key, ""), **extra))
        available[key] = (state == S_OK)

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
        if key in available or key == _req.IN_SOURCE_ROOT:
            continue
        available[key] = _probe_path(resolver, path)["state"] == S_OK

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

    # ── 3-b. 재료 — 시험 문서 전용 (SITS 흐름 / SUTS 타입) ───────────────────
    #
    # UDS 는 필드를 채우지만 시험 문서는 **시험 케이스를 합성한다**. 재료가 없으면
    # 문서가 안 만들어지는 게 아니라 **틀린 시험값이 만들어진다**.
    if req.doc_type in ("sits", "suts") and src and available.get(_req.IN_SOURCE_ROOT):
        tm = _tm.cached(src) if _tm.has_cached(src) else None
        if tm is None:
            steps.append(_step(
                "test_materials", "material", S_UNMEASURED,
                "통합 흐름 / 변수 타입",
                reason="아직 측정하지 않았습니다 — 소스 파싱은 수십 초 이상 걸립니다",
                actions=[{"kind": "measure_source"}],
            ))
        elif not tm.get("ok"):
            steps.append(_step("test_materials", "material", S_UNMEASURED,
                               "통합 흐름 / 변수 타입", reason=str(tm.get("reason") or "")))
        else:
            if req.doc_type == "sits":
                s = tm["sits"]
                # ⚠ "절단 0" 이 아니라 **여유**를 본다. 실측: KJPDS02 는 후보 120 /
                #   캡 120 으로 여유가 0 이라, 함수가 하나만 늘어도 조용히 잘린다.
                steps.append(_step(
                    "sits_flows", "material",
                    S_DEGRADED if s["at_cap_boundary"] else S_OK, "통합 흐름",
                    measured={"value": s["flows_total"], "of": s["cap"],
                              "headroom": s["headroom"]},
                    # ⚠ 이미 잘리는 것과 곧 잘릴 것은 다른 말이다. 라이브에서 여유가
                    #   **-25**(즉 25개가 이미 빠지는 중)인데 "함수가 늘면 잘리기
                    #   시작한다" 는 미래형 문구가 나왔다 — 현재 손실을 예고로 읽게 한다.
                    reason=(
                        f"흐름 {abs(s['headroom'])}개가 상한을 넘어 시험 규격에서 빠집니다 "
                        "— 안전등급이 높은 쪽부터 남지만, 빠진 흐름은 문서에 존재하지 않습니다"
                        if isinstance(s["headroom"], int) and s["headroom"] < 0
                        else ("여유가 없습니다 — 함수가 늘면 그 순간부터 흐름이 잘립니다"
                              if s["at_cap_boundary"] else "")
                    ),
                    sample=s.get("sample_flow"),
                ))
                # SwCom 보강 0 건은 **숨기지 않는다** — 실측상 실 SwDS 를 줘도 0 이다.
                swcom_hits = s.get("sds_swcom_hits")
                steps.append(_step(
                    "sits_sds_related", "material",
                    S_OK if swcom_hits else S_DEGRADED, "SwDS 기반 Related 보강",
                    measured={"value": swcom_hits, "lookups": s.get("sds_lookups"),
                              "key_hits": s.get("sds_key_hits"),
                              "map_entries": s.get("sds_map_entries")},
                    reason=(s.get("sds_reason") or
                            ("SwDS 를 읽었지만 SwCom 을 하나도 얻지 못했습니다 — "
                             "추적성 열이 합성 ID 만 남습니다" if not swcom_hits else "")),
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

    # ── 4. 사슬 — 각 필드를 채울 경로의 단계별 가용성 ─────────────────────────
    available[_chain.INPUT_CALL_GRAPH] = bool(available.get(_req.IN_SOURCE_ROOT))
    for field in (spec.get("fields") or []):
        rows = _chain.chain_state(field, available)
        grounded = [r for r in rows if r["grounded"]]
        have_any = any(r["have"] is True for r in grounded)
        steps.append(_step(
            f"chain_{field}", "chain",
            S_OK if have_any else S_DEGRADED,
            f"{_chain.FIELD_LABELS.get(field, field)} 출처",
            chain=grounded,
            # ⚠ 칸 수를 예고하지 않는다(모듈 docstring 규약).
            reason="" if have_any else "근거 있는 출처가 하나도 확보되지 않았습니다",
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
            try:
                from backend.services.swut_meta_resolver import load_meta_from_config
                meta = load_meta_from_config(project_id) or {}
            except Exception as exc:  # noqa: BLE001 — config 로딩 계열이 광범위
                meta = {}
                reason = f"양식 설정을 읽지 못했습니다 ({type(exc).__name__}: {str(exc)[:100]})"
            paths = (meta or {}).get("template_paths") or {}
            if not meta:
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
    for cap_name, cap in (spec.get("caps") or {}).items():
        steps.append(_step(
            f"cap_{cap_name}", "decision", S_NEEDED, cap_name,
            measured={"api_default": cap.get("api"), "generator_default": cap.get("generator")},
            reason=cap.get("effect", ""),
            actions=[{"kind": "input_value", "target": cap_name}],
        ))

    # ── 5-b. 시험 범위 — 캡과 같은 성격의 **사용자 결정** ────────────────────
    # SUTS 는 SwUDS(단위 설계서) 기반 문서다. 납품 정본도 그 범위이므로 기본은
    # `suds`(설계 ID 가 있는 함수만)다. 소스에는 그보다 많은 함수가 있어(실측 1,160 vs
    # 정본 1,005) 전부 시험하면 정본에 없는 항목이 섞인다 — 어느 쪽을 원하는지는
    # 사람이 정한다. 기본값은 **생성기가 갖고 화면은 복제하지 않는다**.
    if req.doc_type == "suts":
        steps.append(_step(
            "scope", "decision", S_OK, "시험 범위",
            reason=(
                "기본은 정본 기준입니다 — SwUDS 설계 ID 가 있는 함수만 시험합니다. "
                "소스 전체를 시험하려면 바꾸세요(정본에 없는 함수가 포함됩니다)."
            ),
        ))

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
            available[key] = _probe_path(resolver, path)["state"] == S_OK

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
    if doc_key not in _DOC_KEY_TO_INPUT and doc_key not in set(_TEMPLATE_KEY_BY_DOC.values()):
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
    # 시험 문서(SITS/SUTS)면 통합 흐름·변수 타입까지 잰다. 파서가 달라 비용이 별개다.
    doc_type: str = ""
    sds_path: str = ""


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
    if str(req.doc_type or "").strip().lower() in ("sits", "suts"):
        out["test_materials"] = _tm.measure(req.source_root, sds_path=req.sds_path)
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
