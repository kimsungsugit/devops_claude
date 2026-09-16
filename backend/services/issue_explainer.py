"""문제 목록을 **사람이 읽는 문장**으로 — Gemini 로 풀어 설명하되, 숫자는 절대 만들지 않는다 (R48-b).

`docgen_questions.py` 와 같은 역할 분리를 그대로 따른다:

| | 담당 | 이유 |
|---|---|---|
| 무엇이 문제인가(코드·수치·출처) | **코드**(`workflow/quality/issues.py`) | ISO 26262 증거. LLM 이 만들면 그 자체가 거짓 증거 |
| 왜 문제이고 무엇을 하면 되는가 | LLM(Gemini) | 검토자가 읽고 판단할 수 있는 형태 |

## 안전장치(전부 검증 가능 → 뮤테이션으로 고정)
1. **프롬프트 밖 숫자**가 응답에 하나라도 있으면 응답을 통째로 버린다(`docgen_questions.invented_numbers` 재사용 — 한 곳).
2. 응답의 항목 `code` 는 입력 목록의 코드 **부분집합**이어야 한다 — 없는 문제를 지어내지 못한다.
3. LLM 비활성·키 없음·타임아웃·형식 위반 어느 쪽이든 **룰 문장**으로 내려간다. 화면이 LLM 에 의존해 죽지 않는다.
4. 응답에 `generated_by: "llm" | "rule"` 와 `model` 을 싣는다 — 문장의 출처를 숨기지 않는다.
5. 호출은 **버튼**으로만(라우터 계약) — 페이지를 열 때마다 LLM 을 부르지 않는다. 같은 사실이면 캐시(TTL·LRU).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from backend.services.docgen_questions import invented_numbers

_logger = logging.getLogger("devops_api.issue_explainer")

_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_TTL_S = 1800.0
_CACHE_MAX = 128

# 프롬프트에 싣는 항목 상한 — 검증 이슈 200건을 다 넣으면 토큰만 태운다. 넘치는 만큼은 사실로 적어 넘긴다.
PROMPT_ITEMS_MAX = 40

_SYSTEM = (
    "너는 ISO 26262 문서 자동 생성 도구의 검토 보조다. 입력은 문서 생성 run 에서 관측된 문제 목록(JSON)이다. "
    "**입력에 없는 숫자를 절대 쓰지 마라. 숫자를 새로 만들거나 추정하지 마라.** 입력에 없는 문제를 만들지 마라. "
    "한국어로, 검토자가 승인/반려를 판단할 수 있게 써라. 반드시 아래 JSON 만 출력하라(코드 펜스 없이):\n"
    '{"summary": "<전체 요약 2~4문장 — 실제 문제와 잠재 문제를 갈라 말할 것>", '
    '"items": [{"i": <입력 항목의 i 그대로>, "code": "<입력의 code 그대로>", "explanation": "<왜 문제인가 1~2문장>", "action": "<무엇을 하면 되는가 1문장>"}]}'
)

# 코드 접두 → 룰 조치문. LLM 이 없을 때의 문장이고, LLM 응답이 있어도 code 마다 여기 문장이 기본값이다.
_RULE_ACTION: Dict[str, str] = {
    "gate_fail": "해당 축의 근거 입력(참조 SwUDS·SwRS/SwDS·소스 주석)을 채우거나 상한을 늘려 다시 생성한다.",
    "gate_unmeasured": "잴 대상이 0건인 축이다 — 대상이 있어야 하는 문서라면 입력 범위(소스 루트·상한)를 확인한다.",
    "gate_no_threshold": "설정에서 그 축의 임계를 정하거나 판정 밖으로 뺄지 정책을 정한다.",
    "tbd_residual": "TBD 로 남은 값을 검토자가 채우거나, 참조 SwUDS 를 지정해 자동 보강되게 한다.",
    "prototype_unreadable": "Prototype 을 못 읽은 함수의 선언 형태(매크로·전처리)를 확인한다 — 입출력 수치는 그 함수를 뺀 값이다.",
    "entries_not_in_payload": "문서 템플릿(정본)에만 있는 절이다 — 정본의 부분집합 의도가 맞는지 확인한다.",
    "payload_not_in_document": "템플릿에 대응 heading 이 없어 빠진 함수다 — 템플릿을 갱신하거나 unmatched_headings 정책을 확인한다.",
    "payload_missing": "payload 사이드카 기록 실패다 — 디스크·권한을 확인하고 다시 생성한다.",
    "validation_fail": "검증 이슈 항목을 하나씩 닫은 뒤 다시 생성한다 — 이 상태로 승인하면 구조 결함이 산출물에 남는다.",
    "validation_issue": "해당 이슈를 문서에서 확인하고 입력(요구·설계 문서·소스)을 고친다.",
    "validation_warning": "판정을 바꾸지 않는 공시다 — 검토자가 알고 승인해야 한다.",
    "validation_gate_fail": "검증 게이트 미달 축의 입력을 채운다.",
    "functions_missing_from_docx": "소스 함수가 문서에 빠졌다 — 템플릿 heading 또는 함수 매칭 규칙을 확인한다.",
    "headings_without_payload": "내용 없는 절이 남았다 — 정본 절 제거(drop) 정책을 검토하거나 소스 범위를 넓힌다.",
    "dropped_headings": "정본에서 뺀 절 수다 — 뺀 것이 의도된 부분집합인지 확인한다.",
    "confidence_low": "ASIL·Related 출처가 약하다 — 참조 SwUDS 를 지정하거나 소스 주석에 @asil 을 단다.",
    "reference_suds_unconfigured": "레지스트리에 이 프로젝트의 SwUDS 정본을 등록하거나 폼에서 지정한다.",
    "reference_identity_blocked": "지정한 참조 SwUDS 가 다른 프로젝트 문서다 — 올바른 정본으로 바꾼다(차단은 안전 장치다).",
    "reference_registry_mismatch": "폼 지정 경로와 레지스트리 정본이 다르다 — 어느 쪽이 맞는지 정하고 레지스트리를 갱신한다.",
    "score_below_threshold": "기록 시점 임계 미달 축이다 — 게이트 축 조치와 같다.",
    "evidence_missing": "근거 사이드카가 없다 — 재생성하면 생긴다. 이 run 은 근거 없이 승인하는 셈이다.",
    "evidence_read_failed": "근거 파일을 읽지 못했다 — 파일 손상/권한을 확인한다.",
    "output_file_missing": "기록된 경로에 파일이 없다 — 옮겼거나 지웠다. 검토는 기록 해시에만 붙는다.",
    "output_path_unrecorded": "경로 미기록 run(구판) — 재생성해야 근거를 댈 수 있다.",
    "source_root_missing": "레지스트리의 소스 루트 하나가 없다 — 경로를 고치거나 목록에서 뺀다.",
    "source_root_none": "소스 루트를 하나도 못 찾았다 — 함수 0개 문서다. 소스 루트 설정을 고친다.",
    "source_cap_reached": "파일/항목 상한에 닿아 나머지는 인식되지 않았다 — 준비 게이트의 상한(cap_*)을 늘린다.",
    "source_read_truncated": "파일 내부 읽기 상한에 닿았다 — 큰 헤더(매크로)가 잘렸다. 상한 정책을 확인한다.",
    "requirements_missing": "요구사항 문서를 읽지 못했다 — SwRS/SwDS 경로·형식을 확인한다.",
    "requirement_doc_skipped": "그 문서만 읽지 못했다 — 경로·권한(cloudium 워커)·양식을 확인한다. 나머지 문서로만 만든 문서다.",
    "ai_disabled": "AI 설명이 꺼져 있다 — description 은 소스 주석/참조에서만 온다. 필요하면 AI 를 켜고 재생성한다.",
    "ai_failed": "AI 섹션 생성이 실패했다 — API 키·모델·네트워크를 확인한다.",
    "docx_unmatched_functions": "템플릿 heading 이 없어 문서에 못 실은 함수다 — 정본 템플릿 갱신 또는 매칭 규칙 확인.",
    "text_section_unplaced": "본문 절이 정본 레이아웃에 자리가 없어 빠졌다 — 정본에 그 절을 두거나, 그 입력을 이 문서에 안 쓰는 것으로 정한다.",
    "reference_overrode_doc_asil": "정본 SwUDS 와 설계 문서(SwDS)의 ASIL·Related 가 어긋난 함수다 — 정본을 썼다. 두 문서 중 낡은 쪽을 갱신한다.",
    "reference_ambiguous_function_name": "정본 SwUDS 가 같은 함수를 두 절에 다른 ASIL·Related 로 실었다 — 어느 쪽도 적용하지 않았다. 정본에서 사본 절을 지우거나 값을 맞춘다.",
    "reference_id_numbering_differs": "정본 SwUDS 의 함수 ID 와 생성본 ID 가 다른 함수를 가리킨다 — 매칭은 이름으로 했으니 결과는 맞다. 정본 ID 로 함수를 찾지 말 것.",
    "sds_partition_map_failed": "SwDS 에서 파티션 맵을 못 뽑았다 — 문서 양식(표 구조)을 확인한다. 정본·소스만으로 채운 문서다.",
    "sds_partition_map_empty": "요구 문서는 있는데 SwDS 파티션이 0건이다 — 파일명에 SwDS 가 있는지, 표 구조가 맞는지 확인한다.",
    "payload_sidecar_failed": "payload 기록 실패 — 채점기가 자기 대조로 강등됐다. 디스크를 확인하고 재생성한다.",
    "report_timeout": "후처리 리포트가 시간 안에 끝나지 못했다 — 그 리포트 없이 산출물이 나갔다. 예산(UDS_REPORT_TIMEOUT)이나 리포트 성능을 본다.",
    "report_failed": "후처리 리포트 실패 — 로그의 사유를 본다.",
    "quick_gate_fail": "빠른 게이트 FAIL — 미달 축의 조치를 따른다.",
    "threshold_missing": "임계가 없는 축이 있어 fail-closed 됐다 — 설정을 채운다.",
    "issues_truncated": "항목 상한을 넘었다 — 백엔드 로그에서 나머지를 본다.",
}
_DEFAULT_ACTION = "관측된 사실을 확인하고, 입력을 고친 뒤 다시 생성한다."


def rule_action(code: str) -> str:
    c = str(code or "")
    return _RULE_ACTION.get(c) or _RULE_ACTION.get(c.split(":", 1)[0]) or _DEFAULT_ACTION


def _facts_of(payload: Dict[str, Any]) -> Dict[str, Any]:
    """프롬프트에 싣는 사실 — 목록(상한)·건수. 숫자 검증의 허용 집합이 곧 이 dict 다."""
    items = list(payload.get("issues") or [])
    shown = items[:PROMPT_ITEMS_MAX]
    return {
        "run_id": payload.get("run_id"),
        "doc_type": payload.get("doc_type"),
        "counts": payload.get("counts") or {},
        "items_shown": len(shown),
        "items_total": len(items),
        # `i` = 목록 안 순번. 같은 code 가 여러 건(`requirement_doc_skipped` 는 문서마다 한 건)이라 code 만으로는
        # 설명을 항목에 되붙일 수 없다 — LLM 이 `i` 를 그대로 돌려주고, 병합·화면은 `i` 우선, code 는 폴백(리뷰 I6).
        "issues": [
            {"i": idx, "code": it.get("code"), "severity": it.get("severity"), "kind": it.get("kind"),
             "source": it.get("source"), "message": str(it.get("message") or "")[:200], "facts": it.get("facts") or {}}
            for idx, it in enumerate(shown)
        ],
    }


def rule_explanation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 없이 내는 문장 — 수치는 입력 그대로, 조치는 코드별 표."""
    counts = payload.get("counts") or {}
    items = list(payload.get("issues") or [])
    sev = counts.get("by_severity") or {}
    if not items:
        summary = "관측된 문제가 없다 — 단, 근거 출처가 없는 축(sources)이 있으면 '문제 없음' 이 아니라 '잰 것이 없음' 이다."
    else:
        summary = (
            f"문제 {counts.get('total', len(items))}건 — 이미 문제가 된 것(actual) {counts.get('actual', 0)}건, "
            f"문제가 될 수 있는 것(potential) {counts.get('potential', 0)}건. "
            f"심각도: error {sev.get('error', 0)} · warning {sev.get('warning', 0)} · risk {sev.get('risk', 0)}. "
            "error 가 하나라도 있으면 그 축은 산출물이 틀렸거나 빠진 상태라 승인 전에 닫아야 한다."
        )
    return {
        "summary": summary,
        "items": [
            {"i": idx, "code": it.get("code"), "explanation": str(it.get("message") or ""), "action": rule_action(str(it.get("code") or ""))}
            for idx, it in enumerate(items)
        ],
    }


def _strip_fence(text: str) -> str:
    t = str(text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1).strip() if m else t


def _parse_llm(text: str, facts: Dict[str, Any]) -> "tuple[Optional[Dict[str, Any]], str]":
    """응답 검증. `(parsed, reason)` — parsed 가 None 이면 reason 이 폐기 사유."""
    raw = _strip_fence(text)
    if not raw:
        return None, "빈 응답"
    try:
        data = json.loads(raw)
    except ValueError:
        # 앞뒤에 문장이 붙었을 수 있다 — 첫 `{` 부터 마지막 `}` 까지 한 번 더.
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e <= s:
            return None, "JSON 이 아니다"
        try:
            data = json.loads(raw[s:e + 1])
        except ValueError:
            return None, "JSON 이 아니다"
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not isinstance(data.get("items"), list):
        return None, "형식 위반(summary/items)"
    shown = list(facts.get("issues") or [])
    allowed_codes = {str(i.get("code")) for i in shown}
    items: List[Dict[str, Any]] = []
    for it in data["items"]:
        if not isinstance(it, dict):
            return None, "형식 위반(item)"
        code = str(it.get("code") or "")
        if code not in allowed_codes:
            return None, f"입력에 없는 문제 코드 {code[:40]!r}"
        # `i` 는 입력 순번과 code 가 **둘 다** 맞을 때만 믿는다 — 틀리면 버리고 code 폴백(없는 항목을 만들지 않는다).
        idx = it.get("i")
        if not (isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(shown)
                and str(shown[idx].get("code")) == code):
            idx = None
        items.append({"i": idx, "code": code, "explanation": str(it.get("explanation") or "").strip(),
                      "action": str(it.get("action") or "").strip() or rule_action(code)})
    text_all = data["summary"] + " " + " ".join(i["explanation"] + " " + i["action"] for i in items)
    bad = invented_numbers(text_all, facts)
    if bad:
        return None, f"프롬프트 밖 숫자 {bad[:5]}"
    return {"summary": data["summary"].strip(), "items": items}, ""


def _model_name(cfg: Dict[str, Any]) -> str:
    return str(os.environ.get("LLM_MODEL_OVERRIDE") or cfg.get("model_override") or cfg.get("model") or "").strip()


def explain_issues(payload: Dict[str, Any], *, use_llm: bool = True,
                   llm_call_fn=None) -> Dict[str, Any]:
    """`POST /api/review/runs/{id}/issues/explain` 본문.

    Returns: `{generated_by, model, summary, items, llm_reason, facts_sha1, items_shown, items_total}`.
    `llm_call_fn(cfg, messages) -> str` 는 테스트 seam — 기본은 `workflow.ai.agent_call_text`.
    """
    facts = _facts_of(payload)
    key = hashlib.sha1(json.dumps([facts, bool(use_llm)], ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and (time.time() - hit[0]) < _CACHE_TTL_S:
            _CACHE.move_to_end(key)
            return dict(hit[1], cached=True)

    out: Dict[str, Any] = {"generated_by": "rule", "model": None, "llm_reason": "", "facts_sha1": key,
                           "items_shown": facts["items_shown"], "items_total": facts["items_total"]}
    llm_out: Optional[Dict[str, Any]] = None
    if not use_llm:
        out["llm_reason"] = "LLM 사용 안 함"
    elif not payload.get("issues"):
        out["llm_reason"] = "설명할 문제가 없다"
    else:
        cfg = None
        try:
            from workflow.ai import load_oai_config
            cfg = load_oai_config(None)
        except Exception as exc:  # noqa: BLE001 — 설정 실패는 룰 폴백 사유로만 남긴다
            out["llm_reason"] = f"LLM 설정을 읽지 못했다({type(exc).__name__})"
        if cfg:
            out["model"] = _model_name(cfg) or None
            prompt = (
                "문제 목록(JSON):\n" + json.dumps(facts, ensure_ascii=False) +
                "\n\n위 목록만 근거로 summary 와 items 를 채워라. items 의 code 는 입력의 code 를 그대로 써라."
            )
            messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
            try:
                if llm_call_fn is not None:
                    text = llm_call_fn(cfg, messages)
                else:
                    from workflow.ai import agent_call_text
                    text = agent_call_text(cfg, messages, role="assistant")
            except Exception as exc:  # noqa: BLE001 — LLM 계열 예외가 광범위. 폴백이 정답이다
                text = None
                out["llm_reason"] = f"LLM 호출 실패({type(exc).__name__}: {str(exc)[:80]})"
            if text:
                llm_out, why = _parse_llm(str(text), facts)
                if llm_out is None:
                    _logger.warning("issue explain: LLM 응답 폐기 — %s", why)
                    out["llm_reason"] = f"LLM 응답 폐기 — {why}"
            elif not out["llm_reason"]:
                out["llm_reason"] = "LLM 이 빈 응답을 냈다"
        elif not out["llm_reason"]:
            out["llm_reason"] = "LLM 이 설정되지 않았다"

    rule = rule_explanation(payload)
    if llm_out is not None:
        # LLM 이 설명하지 않은 코드는 룰 문장으로 채운다 — 목록이 줄어들면 안 된다(빠진 항목 = 없는 문제로 읽힌다).
        # 순번(`i`)이 맞는 설명을 먼저, 없으면 같은 code 의 설명(옛 응답 형식 호환), 그것도 없으면 룰 문장.
        by_i = {i["i"]: i for i in llm_out["items"] if i.get("i") is not None}
        by_code = {i["code"]: i for i in llm_out["items"]}
        merged = [dict(by_i.get(r["i"]) or by_code.get(str(r["code"])) or r, code=r["code"], i=r["i"]) for r in rule["items"]]
        out.update(generated_by="llm", summary=llm_out["summary"], items=merged)
    else:
        out.update(summary=rule["summary"], items=rule["items"])

    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), dict(out))
        _CACHE.move_to_end(key)
        now = time.time()
        for k in [k for k, v in _CACHE.items() if (now - v[0]) >= _CACHE_TTL_S]:
            del _CACHE[k]
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["PROMPT_ITEMS_MAX", "clear_cache", "explain_issues", "rule_action", "rule_explanation"]
