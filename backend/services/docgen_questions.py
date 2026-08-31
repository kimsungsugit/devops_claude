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
from collections import OrderedDict
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("devops_api.docgen_questions")

# 질문 캐시 — 같은 측정값이면 같은 문장이다. LLM 을 행 펼침마다 부르지 않는다.
#
# ⚠ **상한이 있어야 한다.** 키는 측정값 전체의 해시라 상한을 하나 바꿀 때마다 새 키가
#   생긴다(캡 입력칸은 blur 마다 재조회한다). TTL 만 두면 만료된 항목도 **다시 조회될 때만**
#   버려지므로, 한 번 쓰고 안 돌아오는 키가 프로세스 수명 내내 남는다. 이 서버는
#   `--reload` 없이 며칠씩 떠 있다.
_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_TTL_S = 1800.0
# 화면 하나가 문서 11종 × 결정 몇 개를 오가는 정도는 넉넉히 담고, 그 위로는 오래된 것부터
# 버린다(LRU). 캐시가 비어도 결과는 같다 — 느려질 뿐이라 안전하게 버릴 수 있다.
_CACHE_MAX = 256

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
            cap_name = sid[4:]
            api_default = m.get("api_default")
            # 흐름 캡은 **지금 실제로 잘리고 있는지**가 심각도를 가른다. 여유가 0 이하면
            # 안전등급 높은 흐름까지 규격에서 사라질 수 있다(실측 kjpds02_pv: 여유 -25).
            flow = (by_id.get("sits_flows") or {}).get("measured") or {}
            headroom = flow.get("headroom")
            at_boundary = isinstance(headroom, int) and headroom <= 0
            # `adjustable` 이 정본이다. 다만 그 키가 없던 옛 payload 도 받아야 하므로
            # **같은 사실의 다른 표현**인 `api_default is not None` 을 폴백으로 쓴다.
            adjustable = bool(m.get("adjustable", api_default is not None))
            user_value = m.get("user_value")
            # 스텝이 `ok` 면 **결정할 것이 없다** — 전량을 담고 있다는 뜻이다.
            # 예전엔 캡이 늘 `needed` 라 이 분기가 사실상 항상 참이었는데, 이제 상한이
            # 전량을 담으면 `ok` 가 나온다. 그때도 "조정할까요?" 를 물으면 스텝은 ✓ 인데
            # 질문은 결정을 요구하는 **두 목소리**가 된다. 조정 못 하는 상한은 결정이
            # 아니라 공시라 남긴다(그게 그 행의 존재 이유다).
            if state == "ok" and adjustable:
                continue
            # 조정할 수 없는 상한은 **결정이 아니라 공시**다 — 사용자가 할 수 없는 일을
            # 결정 목록 상단에 올리면 진짜 결정이 묻힌다.
            severity = ("high" if (cap_name == "max_flows" and at_boundary)
                        else "medium" if adjustable else "low")
            facts = {"cap": cap_name, "api_default": api_default,
                     "generator_default": m.get("generator_default"),
                     "effect": str(s.get("reason") or "")}
            if cap_name == "max_flows" and headroom is not None:
                facts["headroom"] = headroom
                facts["flows_total"] = flow.get("value")
            if not adjustable and m.get("adjust_via"):
                facts["adjust_via"] = str(m["adjust_via"])
            if user_value is not None:
                facts["user_value"] = user_value
            # ⚠ `api_default is None` 은 **API 가 이 값을 받지 않는다**는 뜻이다.
            #   "현재 None" 으로 흘리면 사용자는 값이 비었다고 읽는다.
            if not adjustable:
                current = "이 상한은 화면에서 조정할 수 없습니다"
                if m.get("adjust_via"):
                    current += f" — {m['adjust_via']}"
            elif user_value is not None:
                # 정한 값을 되읽어 보인다. 이게 없으면 사용자가 200 을 넣어도 화면은
                # 계속 기본값을 "현재" 라고 불러 자기 선택이 반영됐는지 알 수 없다.
                current = f"현재 {user_value}(직접 지정)"
            else:
                current = f"현재 {api_default}"
            # ⚠ 못 잰 상한에 "조정할까요?" 를 물으면, 조정에 필요한 수를 못 주면서
            #   결정을 요구하는 꼴이다. 먼저 할 일은 재는 것이다.
            head = (f"{cap_name} 상한 — 지금 잘리고 있습니다"
                    if at_boundary and cap_name == "max_flows"
                    else f"{cap_name} 상한 — 자르는지 아직 재지 않았습니다"
                    if state == "unmeasured"
                    else f"{cap_name} 상한 — 무엇이 빠지는지 알아두세요" if not adjustable
                    else f"{cap_name} 상한을 조정할까요?")
            body = f"{current}, 생성기 기본값은 {m.get('generator_default')} 입니다. {s.get('reason') or ''}"
            if at_boundary and cap_name == "max_flows":
                body = (f"통합 흐름이 상한을 넘어 일부가 시험 규격에서 빠집니다. {body}")
            out.append(_q(sid, "value", severity, facts, head, body))

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
            _CACHE.move_to_end(key)          # LRU — 방금 쓴 것을 뒤로
            return hit[1]
        # ⚠ 여기서 만료분을 지우지 않는다 — **아래 쓰기 경로가 이미 전량을 청소**하고
        #   같은 키를 다시 넣는다. 여기 `del` 을 두면 하는 일이 없으면서 뭔가 하는 것처럼
        #   보이는 줄이 된다(뮤테이션으로 확인: 지워도 관측 가능한 차이가 없었다).

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
        _CACHE.move_to_end(key)
        # ⚠ 만료 청소만으로는 부족하다 — 만료 전에 상한을 넘길 수 있고(캡을 여러 번
        #   바꾸면 30분 안에 수백 키가 난다), 그때 오래된 것부터 버려야 한다.
        now = time.time()
        for _k in [k for k, v in _CACHE.items() if (now - v[0]) >= _CACHE_TTL_S]:
            del _CACHE[_k]
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
