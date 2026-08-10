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

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services import docgen_comment_coverage as _cov
from backend.services import docgen_field_sources as _chain
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

    out: Dict[str, str] = {}
    if source_root:
        out[_req.IN_SOURCE_ROOT] = source_root
    for doc_key, input_key in _DOC_KEY_TO_INPUT.items():
        v = str(req.doc_paths.get(doc_key) or "").strip()
        if not v:
            raw = linked.get(doc_key)
            if isinstance(raw, list):
                v = str(raw[0]) if raw else ""
            else:
                v = str(raw or "")
        if v.strip():
            out[input_key] = v.strip()
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
        steps.append(_step(key, "input", state, label, required=is_required,
                           effect=optional.get(key, ""), **extra))
        available[key] = (state == S_OK)

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
        if _cov.has_cached(src):
            cov = _cov.measure(src)
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
                    reason=("캡에 닿아 있습니다 — 함수가 늘면 흐름이 잘리기 시작하고, "
                            "잘린 흐름은 시험 규격에 존재하지 않습니다"
                            if s["at_cap_boundary"] else ""),
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
