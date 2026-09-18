"""run 하나의 **문제 목록** — 생성 시 기록 + 사이드카 근거 + DB 점수를 한 어휘로 모은다 (R48-b).

## 왜 세 출처인가

| 출처 | 무엇을 아나 | 없으면 |
|---|---|---|
| `meta_json.issues` | 생성 **도중** 수집기(`report_gen/gen_issues.py`)가 남긴 것 — 참조 불일치·소스 절단·리포트 타임아웃 | R48-b 이전 run·local 경로 run 은 없다(`sources.generation: False`) |
| 사이드카(`report_gen/evidence.py`) | 채점기가 문서를 **되읽어** 잰 것 — 실패 게이트·미측정·TBD 잔여·문서 누락 함수·검증 이슈 | 파일이 없으면 그 축은 `present:false` — 목록에 "근거 없음" 을 **항목으로** 남긴다 |
| `quality_scores` | 기록 시점 임계 미달 축(`gate_pass=False`) | 점수 없는 run(빈 산출물)은 0건 |

한 출처만 보면 갈린다: 사이드카가 없는 구 run 은 점수로만, 점수가 없는 빈 run 은 meta 로만 말할 수 있다. 세 출처를 합치되
`source` 를 항목마다 적어 **어디서 온 말인지** 숨기지 않는다.

## 어휘(수집기와 같다)
`severity` error|warning|risk · `kind` actual|potential. 판정을 만들지 않는다 — 게이트가 낸 값을 옮길 뿐이다.
숫자는 `facts` 에 그대로 싣는다(설명기의 "프롬프트 밖 숫자" 검사가 이 값을 허용 집합으로 쓴다).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from workflow.quality.models import GenerationRun, QualityScore

_logger = logging.getLogger("workflow.quality.issues")

# 목록 한 항목에서 펼치는 세부 상한 — validation issues 가 수백 줄이면 한 항목으로 접고 수를 적는다.
LIST_CAP = 20


class RunNotFound(LookupError):
    pass


def _issue(code: str, severity: str, kind: str, message: str, *, source: str,
           facts: Optional[Dict[str, Any]] = None, stage: str = "") -> Dict[str, Any]:
    return {
        "code": code, "severity": severity, "kind": kind, "message": " ".join(str(message).split())[:400],
        "source": source, "stage": stage, "facts": dict(facts or {}),
    }


def _meta_issues(raw: Optional[str]) -> "tuple[List[Dict[str, Any]], bool]":
    """생성 시 기록. `(items, recorded)` — 키가 없으면 recorded=False(구 run), 있으면 빈 목록도 True."""
    if not raw:
        return [], False
    try:
        meta = json.loads(raw)
    except (TypeError, ValueError):
        return [], False
    if not isinstance(meta, dict) or "issues" not in meta:
        return [], False
    out: List[Dict[str, Any]] = []
    for it in meta.get("issues") or []:
        if not isinstance(it, dict) or not it.get("code"):
            continue
        out.append(_issue(
            str(it.get("code")), str(it.get("severity") or "warning"), str(it.get("kind") or "actual"),
            str(it.get("message") or ""), source="generation", facts=it.get("facts") if isinstance(it.get("facts"), dict) else {},
            stage=str(it.get("stage") or ""),
        ))
    return out, True


def _from_gate_report(g: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not g or not g.get("present"):
        out.append(_issue("evidence_missing:gate_report", "risk", "potential",
                          f"품질 게이트 리포트가 없어 축별 판정을 근거로 댈 수 없다({(g or {}).get('reason') or '사유 미기록'})",
                          source="gate_report", facts={}))
        return out
    for f in g.get("failed_gates") or []:
        name = str((f or {}).get("gate") or "").strip() or "?"
        out.append(_issue(f"gate_fail:{name}", "error", "actual",
                          f"게이트 미달: {name}" + (f" — {f.get('detail')}" if (f or {}).get("detail") else ""),
                          source="gate_report", facts={"gate": name, "detail": (f or {}).get("detail")}))
    if g.get("gate_pass") is False and not (g.get("failed_gates") or []):
        out.append(_issue("gate_fail", "error", "actual", "게이트 판정 FAIL(미달 축이 개별 기록되지 않았다)",
                          source="gate_report", facts={"gates_passed": g.get("gates_passed"), "gates_total": g.get("gates_total")}))
    for name in g.get("unmeasured_gates") or []:
        out.append(_issue(f"gate_unmeasured:{name}", "risk", "potential",
                          f"측정 불가 축: {name} — 분모가 0 이라 채점에서 뺐다(0% 가 아니다)", source="gate_report", facts={"gate": name}))
    for name in g.get("ungated_gates") or []:
        out.append(_issue(f"gate_no_threshold:{name}", "warning", "actual",
                          f"임계 없는 축: {name} — 쟀지만 판정할 수 없어 Gate pass 가 False 다", source="gate_report", facts={"gate": name}))
    tbd = g.get("tbd_residual") or {}
    for label, v in tbd.items():
        if isinstance(v, dict) and (v.get("count") or 0) > 0:
            out.append(_issue(f"tbd_residual:{label}", "warning", "potential",
                              f"{label} 미확정(TBD) {v.get('count')} / {v.get('total')} — 검토자가 채우거나 근거를 지정해야 한다",
                              source="gate_report", facts={"label": label, "count": v.get("count"), "total": v.get("total")}))
    pu = g.get("prototype_unreadable") or {}
    if isinstance(pu, dict) and (pu.get("count") or 0) > 0:
        out.append(_issue("prototype_unreadable", "warning", "potential",
                          f"Prototype 을 읽지 못한 함수 {pu.get('count')} / {pu.get('total')} — 입력/출력 채움률은 나머지로만 잰 값",
                          source="gate_report", facts={"count": pu.get("count"), "total": pu.get("total")}))
    for key, msg in (("entries_not_in_payload", "문서에 있지만 payload 에 없는 항목"),
                     ("payload_not_in_document", "payload 에 있지만 문서에 없는 함수")):
        v = g.get(key) or {}
        if isinstance(v, dict) and (v.get("count") or 0) > 0:
            out.append(_issue(key, "warning", "actual", f"{msg} {v.get('count')} / {v.get('total')}",
                              source="gate_report", facts={"count": v.get("count"), "total": v.get("total")}))
    if g.get("payload_present") is False:
        out.append(_issue("payload_missing", "warning", "actual",
                          f"payload 사이드카 없음 — 채점기가 문서 자기 대조로 강등됐다({g.get('payload_read_error') or '사유 미기록'})",
                          source="gate_report", facts={}))
    return out


def _from_validation(v: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not v or not v.get("present"):
        out.append(_issue("evidence_missing:docx_validate", "risk", "potential",
                          f"구조 검증 리포트가 없다({(v or {}).get('reason') or '사유 미기록'})", source="docx_validate"))
        return out
    if v.get("ok") is False:
        out.append(_issue("validation_fail", "error", "actual",
                          f"산출물 구조 검증 FAIL({v.get('format') or '?'})", source="docx_validate",
                          facts={"gates_passed": v.get("gates_passed"), "gates_total": v.get("gates_total")}))
    elif v.get("ok") is None:
        out.append(_issue("validation_indeterminate", "risk", "potential",
                          f"구조 검증 판정 불가({v.get('reason') or '결과 줄 없음'})", source="docx_validate"))
    issues = [str(x) for x in (v.get("issues") or []) if str(x).strip()]
    for txt in issues[:LIST_CAP]:
        out.append(_issue("validation_issue", "error", "actual", txt, source="docx_validate"))
    if len(issues) > LIST_CAP:
        out.append(_issue("validation_issue_overflow", "error", "actual",
                          f"검증 이슈 {len(issues)}건 중 {LIST_CAP}건만 펼쳤다", source="docx_validate",
                          facts={"total": len(issues), "shown": LIST_CAP}))
    warns = v.get("warnings")
    if isinstance(warns, list):
        for txt in [str(x) for x in warns if str(x).strip()][:LIST_CAP]:
            out.append(_issue("validation_warning", "warning", "potential", txt, source="docx_validate"))
    for name in v.get("failed_gates") or []:
        out.append(_issue(f"validation_gate_fail:{name}", "error", "actual", f"검증 게이트 미달: {name}", source="docx_validate",
                          facts={"gate": name}))
    m = v.get("missing_from_docx")
    if isinstance(m, int) and m > 0:
        out.append(_issue("functions_missing_from_docx", "error", "actual",
                          f"소스 함수 {m}개가 문서에 없다(기대 {v.get('expected_functions')} · 반영 {v.get('matched_functions')})",
                          source="docx_validate", facts={"missing": m, "expected": v.get("expected_functions"), "matched": v.get("matched_functions")}))
    h = v.get("headings_without_payload")
    if isinstance(h, int) and h > 0:
        out.append(_issue("headings_without_payload", "warning", "potential",
                          f"내용 없이 남은 heading {h}개 — 문서가 껍데기 절을 담고 있다", source="docx_validate", facts={"count": h}))
    d = v.get("dropped_headings")
    if isinstance(d, int) and d > 0:
        out.append(_issue("dropped_headings", "warning", "potential",
                          f"정본에서 통째로 뺀 절 {d}개 — 남은 수치는 뺀 뒤의 값이다", source="docx_validate", facts={"count": d}))
    return out


def _from_confidence(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not c or not c.get("present"):
        return []   # UDS 전용 — 부재는 gate_report 축이 이미 말한다(중복 항목 금지)
    grade = str(c.get("grade") or "").strip().upper()
    if grade in ("D", "F"):
        return [_issue("confidence_low", "warning", "potential",
                       f"ASIL·Related 근거 신뢰도 등급 {grade}(점수 {c.get('overall_score')}) — 값이 있어도 출처가 약하다",
                       source="confidence", facts={"grade": grade, "overall_score": c.get("overall_score")})]
    return []


def _from_reference(r: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not r or not r.get("present"):
        return []   # 구판 빌더/비UDS — 통계 자체가 없다. gate 축과 달리 여기서 부재를 항목으로 만들지 않는다.
    out: List[Dict[str, Any]] = []
    if r.get("configured") is False:
        out.append(_issue("reference_suds_unconfigured", "warning", "potential",
                          "참조 SwUDS 없이 생성 — ASIL·Related 보강이 없어 그 칸은 소스 주석/추론에만 기댄다",
                          source="reference", facts={}))
    elif r.get("same_project") is False:
        out.append(_issue("reference_identity_blocked", "error", "actual",
                          f"참조 SwUDS({r.get('document')})가 다른 프로젝트로 판정돼 ASIL·Related 보강 {r.get('safety_fields_blocked')}건이 차단됐다",
                          source="reference", facts={"document": r.get("document"), "blocked": r.get("safety_fields_blocked"),
                                                     "applied": r.get("safety_fields_applied"), "reason": r.get("identity_reason")}))
    if r.get("registry_compare") == "differs":
        mm = r.get("registry_mismatch") or {}
        out.append(_issue("reference_registry_mismatch", "warning", "actual",
                          f"폼이 지정한 참조 SwUDS({mm.get('form')})가 레지스트리 {mm.get('scm_id')} 의 정본({mm.get('registry')})과 다르다 — 지정 경로를 썼다",
                          source="reference", facts=dict(mm)))
    return out


def _from_scores(scores: List[QualityScore]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in scores or []:
        name = str(getattr(s, "metric_name", "") or "")
        if getattr(s, "gate_pass", None) is False and name and not name.startswith(("gate_reason:", "gate_definition:")):
            out.append(_issue(f"score_below_threshold:{name}", "error", "actual",
                              f"기록 시점 임계 미달: {name} = {s.value} (임계 {s.threshold})",
                              source="scores", facts={"metric": name, "value": s.value, "threshold": s.threshold}))
    return out


def collect_run_issues(session: Session, run_id: int) -> Dict[str, Any]:
    """`GET /api/review/runs/{id}/issues` 본문. run 없음은 `RunNotFound`(라우터가 404)."""
    run = session.query(GenerationRun).filter_by(id=run_id).first()
    if not run:
        raise RunNotFound(f"run_id {run_id} not found")
    items: List[Dict[str, Any]] = []
    gen_items, recorded = _meta_issues(run.meta_json)
    items.extend(gen_items)

    sources: Dict[str, Any] = {"generation": recorded, "gate_report": None, "docx_validate": None,
                               "confidence": None, "reference": None, "scores": 0}
    dt = str(run.doc_type or "").strip().lower()
    if run.output_path:
        try:
            from report_gen.evidence import read_evidence
            ev = read_evidence(run.output_path)
        except Exception as exc:  # noqa: BLE001 — 근거 리더 실패는 항목으로 남긴다(목록 전체를 죽이지 않는다)
            _logger.warning("run %s 근거 읽기 실패(%s) — 사이드카 축 없이 목록을 낸다", run_id, type(exc).__name__)
            ev = {}
            items.append(_issue("evidence_read_failed", "risk", "potential",
                                f"근거 사이드카를 읽지 못했다({type(exc).__name__})", source="evidence"))
        g = ev.get("gate_report") or {}
        v = ev.get("docx_validate") or {}
        c = ev.get("confidence") or {}
        r = ev.get("reference") or {}
        if dt == "uds":
            items.extend(_from_gate_report(g))
            items.extend(_from_confidence(c))
            items.extend(_from_reference(r))
        items.extend(_from_validation(v))
        sources.update({"gate_report": bool(g.get("present")) if dt == "uds" else None,
                        "docx_validate": bool(v.get("present")),
                        "confidence": bool(c.get("present")) if dt == "uds" else None,
                        "reference": bool(r.get("present")) if dt == "uds" else None})
        if ev and ev.get("output_path_present") is False:
            items.append(_issue("output_file_missing", "warning", "actual",
                                "기록된 경로에 산출물 파일이 없다 — 검토는 기록 해시에만 붙는다", source="evidence"))
    else:
        items.append(_issue("output_path_unrecorded", "risk", "potential",
                            "산출물 경로가 기록되지 않은 run — 사이드카 근거를 찾을 수 없다", source="evidence"))

    sc = _from_scores(list(run.scores or []))
    items.extend(sc)
    sources["scores"] = len(sc)

    counts = {"actual": 0, "potential": 0, "by_severity": {"error": 0, "warning": 0, "risk": 0}}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
        counts["by_severity"][it["severity"]] = counts["by_severity"].get(it["severity"], 0) + 1
    counts["total"] = len(items)
    return {
        "run_id": run.id, "doc_type": run.doc_type, "scm_id": run.scm_id, "status": run.status,
        "output_path_present": bool(run.output_path),
        "issues": items, "counts": counts, "sources": sources,
    }


__all__ = ["LIST_CAP", "RunNotFound", "collect_run_issues"]
