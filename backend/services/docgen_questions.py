"""결정 항목을 **사람이 읽고 답할 수 있는 질문**으로 바꾼다.

## 왜 LLM 을 쓰나

게이트가 내는 것은 `proceed_without_swds: needed` 같은 코드다. 사용자가 그걸 보고
무엇을 결정해야 하는지 알려면 맥락이 필요하다 — "SwDS 가 없으면 ASIL 을 채울 다른
경로가 이 프로젝트엔 없다" 같은 문장. 그 문장화를 LLM 이 한다.

## ⚠ 역할을 가른다 (타협 없음)

| | 담당 | 이유 |
|---|---|---|
| 측정·판정·수치 | **코드**(결정론) | ISO 26262 증거다. LLM 이 만들면 그 자체가 거짓 증거 |
| 문장화·질문 | LLM | 읽고 결정할 수 있는 형태로 |

**LLM 은 숫자를 만들지 않는다.** 프롬프트에 넣은 측정값만 쓸 수 있고, 응답에 그 밖의
숫자가 있으면 **그 응답을 버리고 룰 문장으로 폴백**한다(`_invented_numbers`). 검증
가능한 규칙이라 뮤테이션으로 고정할 수 있다.

**폴백은 선택이 아니라 필수다.** LLM 비활성·키 없음·타임아웃·거절 어느 쪽이든 룰
문장(측정값을 그대로 서술)으로 내려간다. 화면이 LLM 에 의존해 죽으면 안 된다.

응답에는 `generated_by: "llm" | "rule"` 이 실린다 — **문장의 출처를 숨기지 않는다**
(이 저장소의 provenance 규약과 같은 취지).

## ⚠ ASIL 기본값에 QM 을 넣지 않는다

근거 부재를 `QM`(안전 관련 아님)으로 바꾸면 under-classification 이다. 선택지는
`TBD 로 둔다` / `값을 직접 지정` 뿐이다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("devops_api.docgen_questions")

# 질문 캐시 — 같은 측정값이면 같은 문장이다. LLM 을 행 펼침마다 부르지 않는다.
_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.RLock()
_CACHE_TTL_S = 1800.0

# 숫자 토큰. 천단위 콤마·소수점을 한 덩어리로 잡는다.
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers_in(text: Any) -> List[str]:
    return [str(m).replace(",", "") for m in _NUM.findall(str(text or ""))]


def _allowed_numbers(facts: Dict[str, Any]) -> set[str]:
    """프롬프트에 실린 모든 숫자 — LLM 이 쓸 수 있는 유일한 수치 집합."""
    allowed: set[str] = set()
    for tok in _numbers_in(json.dumps(facts, ensure_ascii=False)):
        allowed.add(tok)
        # `2.80` ↔ `2.8` 처럼 표기만 다른 경우를 같은 값으로 본다.
        if "." in tok:
            allowed.add(tok.rstrip("0").rstrip("."))
    return allowed


def invented_numbers(text: str, facts: Dict[str, Any]) -> List[str]:
    """응답에서 **프롬프트에 없던 숫자**를 찾는다. 하나라도 있으면 그 응답은 버린다.

    ⚠ 이 검사가 이 모듈의 안전장치 전부다. LLM 이 "435개 중 82개" 같은 그럴듯한 수치를
    지어내면 사용자는 그걸 측정값으로 읽는다.
    """
    allowed = _allowed_numbers(facts)
    out: List[str] = []
    for tok in _numbers_in(text):
        if tok in allowed:
            continue
        if "." in tok and tok.rstrip("0").rstrip(".") in allowed:
            continue
        out.append(tok)
    return out


# ── 질문 뼈대: facts 는 **코드가** 채운다 ──────────────────────────────────
#
# 각 항목의 `rule_body` 는 LLM 없이도 쓸 수 있는 문장이다. 측정값을 그대로 서술하며
# 지어내지 않는다.

def _q(qid: str, kind: str, severity: str, facts: Dict[str, Any],
       title: str, rule_body: str, options: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    return {
        "id": qid, "kind": kind, "severity": severity, "facts": facts,
        "title": title, "body": rule_body, "options": options or [],
        "generated_by": "rule",
    }


def _questions_from_steps(doc_type: str, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """preflight 스텝 → 결정 질문(문장은 아직 룰 판)."""
    out: List[Dict[str, Any]] = []
    by_id = {str(s.get("id")): s for s in steps}

    for s in steps:
        sid = str(s.get("id") or "")
        state = str(s.get("state") or "")
        label = str(s.get("label") or sid)

        # 1) 선택 입력이 없다 — 없이 진행할지 결정해야 한다.
        if state == "needed" and s.get("phase") == "input":
            effect = str(s.get("effect") or "")
            out.append(_q(
                f"proceed_without_{sid}", "confirm", "high",
                {"input": sid, "label": label, "effect": effect},
                f"{label} 없이 만들까요?",
                (f"{label} 가 연결되지 않았습니다. 없이 진행하면 {effect}."
                 if effect else f"{label} 가 연결되지 않았습니다."),
                [{"value": "proceed", "label": "이대로 진행"},
                 {"value": "cancel", "label": "먼저 연결하겠습니다"}],
            ))

        # 2) 캡 — 자료 부족이 아니라 상한 설정이다.
        elif sid.startswith("cap_"):
            m = s.get("measured") or {}
            out.append(_q(
                sid, "value", "medium",
                {"cap": sid[4:], "api_default": m.get("api_default"),
                 "generator_default": m.get("generator_default"),
                 "effect": str(s.get("reason") or "")},
                f"{sid[4:]} 상한을 조정할까요?",
                (f"현재 {m.get('api_default')} 이고 생성기 기본값은 "
                 f"{m.get('generator_default')} 입니다. {s.get('reason') or ''}"),
            ))

        # 3) 빌더 폼 필수값 — 특히 릴리스 버전은 **지어내면 안 된다**.
        elif sid.startswith("form_") and state == "needed":
            field = sid[5:]
            out.append(_q(
                sid, "value", "high", {"field": field},
                f"{field} 값을 입력해 주세요",
                ("임의 값으로 채우지 않습니다 — 틀린 값이 납품 문서 표지에 박힙니다."
                 if field == "release_sw_version" else "생성에 필요한 값입니다."),
            ))

    # 4) 사슬이 통째로 빈 필드 — 그 필드는 TBD 로 남는다.
    for s in steps:
        sid = str(s.get("id") or "")
        if not sid.startswith("chain_") or s.get("state") != "degraded":
            continue
        field = sid[6:]
        chain = [r for r in (s.get("chain") or []) if r.get("grounded")]
        empty = [str(r.get("input_label") or r.get("input")) for r in chain if r.get("have") is False]
        out.append(_q(
            f"accept_tbd_{field}", "choice", "high",
            {"field": field, "empty_inputs": empty,
             "chain_len": len(chain)},
            f"{s.get('label') or field} 를 어떻게 할까요?",
            ("근거 있는 출처가 하나도 확보되지 않았습니다"
             + (f" (비어 있는 입력: {', '.join(empty)})" if empty else "")
             + ". 이대로 만들면 그 칸은 TBD 로 남습니다."),
            # ⚠ QM 을 선택지에 넣지 않는다 — 근거 부재를 '안전 관련 아님' 으로
            #   바꾸면 under-classification 이다.
            [{"value": "tbd", "label": "TBD 로 두고 진행"},
             {"value": "specify", "label": "값을 직접 지정"},
             {"value": "cancel", "label": "자료를 먼저 채우겠습니다"}],
        ))

    # worker 미기동은 결정이 아니라 조치다 — 질문으로 만들지 않는다.
    if by_id.get("worker", {}).get("state") == "error":
        out = [q for q in out if q["severity"] == "high"]
    return out


# ── LLM 문장화 ──────────────────────────────────────────────────────────────

_SYSTEM = (
    "너는 ISO 26262 문서 생성 도구의 안내 문구를 쓴다. "
    "**주어진 사실(facts)에 없는 수치를 절대 쓰지 마라.** "
    "숫자를 새로 만들거나 추정하지 마라. 한국어로, 2~3문장으로, "
    "사용자가 무엇을 결정해야 하는지 분명히 써라."
)


def _llm_body(cfg: Dict[str, Any], question: Dict[str, Any]) -> Optional[str]:
    """LLM 으로 본문 한 단락을 만든다. 실패하거나 숫자를 지어내면 ``None``."""
    facts = question.get("facts") or {}
    prompt = (
        f"질문 제목: {question.get('title')}\n"
        f"사실(JSON): {json.dumps(facts, ensure_ascii=False)}\n"
        f"기본 안내문: {question.get('body')}\n\n"
        "위 사실만 사용해 안내문을 다듬어라."
    )
    try:
        from workflow.ai import agent_call_text
        text = agent_call_text(cfg, [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ], role="assistant")
    except Exception as exc:  # noqa: BLE001 — LLM 계열 예외가 광범위. 폴백이 정답이다
        _logger.info("질문 문장화 실패(룰 폴백) — %s: %s", type(exc).__name__, str(exc)[:120])
        return None

    body = str(text or "").strip()
    if not body:
        return None
    bad = invented_numbers(body, facts)
    if bad:
        # ⚠ 지어낸 수치가 하나라도 있으면 통째로 버린다. 일부만 지우면 문맥이 깨진 채
        #   남고, 그게 더 읽기 어렵다.
        _logger.warning("질문 문장에 프롬프트 밖 숫자 %s — 룰 폴백", bad[:5])
        return None
    return body


def build_questions(doc_type: str, steps: List[Dict[str, Any]], *,
                    use_llm: bool = True) -> Dict[str, Any]:
    """결정 질문 목록. 문장은 LLM, 실패하면 룰.

    Returns:
        ``{"questions": [...], "llm_used": bool, "llm_reason": str}``
    """
    questions = _questions_from_steps(doc_type, steps)
    if not questions:
        return {"questions": [], "llm_used": False, "llm_reason": "결정할 항목이 없습니다"}

    key = hashlib.sha1(
        json.dumps([doc_type, [q["facts"] for q in questions]],
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and (time.time() - hit[0]) < _CACHE_TTL_S:
            return hit[1]

    llm_used = False
    llm_reason = ""
    if use_llm:
        cfg = None
        try:
            from workflow.ai import load_oai_config
            cfg = load_oai_config(None)
        except Exception as exc:  # noqa: BLE001
            llm_reason = f"LLM 설정을 읽지 못했습니다 ({type(exc).__name__})"
        if not cfg:
            llm_reason = llm_reason or "LLM 이 설정되지 않았습니다"
        else:
            for q in questions:
                body = _llm_body(cfg, q)
                if body:
                    q["body"] = body
                    q["generated_by"] = "llm"
                    llm_used = True
            if not llm_used:
                llm_reason = llm_reason or "LLM 문장을 쓰지 못해 기본 안내문을 씁니다"
    else:
        llm_reason = "LLM 사용 안 함"

    out = {"questions": questions, "llm_used": llm_used, "llm_reason": llm_reason}
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), out)
    return out


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
