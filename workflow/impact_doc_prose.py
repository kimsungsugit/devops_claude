"""영향도 문서 초안의 **서술문만** LLM으로 보강(선택 기능).

역할 분담이 이 모듈의 전부다:
  - **값**(경계값·Input/Expected·TC ID·행 번호·판정)은 100% 결정론이 소유한다
    (`workflow/impact_orchestrator._build_doc_proposal` + 프론트 `impactDocDraft.js`).
  - **산문**(UDS Description / SDS Behavior / 시험 목적)만 여기서 만든다. 결정론 근거가
    없어 `_build_doc_proposal`이 `*_source: "ai_required"`로 비워둔 자리다.

왜 기존 `explain-change`를 확장하지 않았나: 그쪽 반환은 마크다운 blob 하나라 셀 단위로
삽입할 수 없고, 프롬프트 스키마에 회귀 테스트가 물려 있어 바꾸면 기존 카드가 깨진다.

## 값 환각 게이트 (정직성의 실행 장치)

프롬프트로 "값을 쓰지 마라"라고 지시하는 것만으로는 부족하다. 응답을 받은 뒤:
  1. 산문에 등장한 **숫자 리터럴**이 결정론 페이로드에 없는 값이면 → 그 필드만 폐기
  2. 식별자가 허용 집합(함수/전역/호출/시그니처) 밖이면 → 그 필드만 폐기
필드 단위 폐기인 이유: 한 필드가 틀렸다고 나머지 멀쩡한 서술문까지 버릴 이유가 없다
(`test_case_draft.filter_cases`와 같은 계열). 폐기 사유는 `dropped_fields`로 돌려준다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from workflow.summary_ai_insight import _extract_json_payload, resolve_effective_model

logger = logging.getLogger(__name__)

# v2: 문서별 노드(uds/sds/sts/suts/sits)를 모두 싣고 "자기 노드 근거로만" 규칙을 명시.
# v1은 SUTS 노드만 보내면서 5개 필드를 요구해 sts_purpose·sits_description이 근거 없이 작성됐다.
IMPACT_DOC_PROSE_PROMPT_VERSION = 2

PROSE_FIELDS = (
    "uds_description", "sds_behavior", "suts_description", "sts_purpose", "sits_description",
)

IMPACT_DOC_PROSE_NOTE = (
    "AI가 작성한 **서술문 초안**입니다. 표의 값(경계값·Input/Expected·판정)은 결정론 산출이며 "
    "AI가 바꾸지 않습니다. 문서에 반영하기 전 설계자 검토가 필요합니다."
)

# 숫자 리터럴 — hex/2진/10진(부호·접미사 포함). 산문에 나오면 결정론 페이로드와 대조한다.
_NUM_RE = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|\d+(?:\.\d+)?)")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# C 타입 토큰 안의 숫자는 **값이 아니라 비트폭**이다(U16의 16, int32_t의 32, float64의 64).
# 값 대조에서 빼지 않으면 "U16 폭 입력의 경계를 확인한다" 같은 **정상 문장이 폐기**된다
# (실측: 결정론 페이로드에 U16 문자열이 없는 조합 — 타입 미상 케이스에서 흔하다).
#
# ⚠ 폭을 `\d{1,2}` 로 열어두면 **없는 타입이 면제된다**: `U48`·`S99`·`u7`·`uint99` 가 숫자
#   검사(비트폭이라며 제거)와 식별자 검사(타입 어휘라며 면제)를 **둘 다** 통과해, 안전 문서
#   초안에 "U48 폭 입력" 같은 환각 타입이 그대로 실렸다(실측). 면제 대상은 이 프로젝트가
#   실제로 아는 타입뿐이어야 하므로 어휘를 `c_type_bounds` 단일 출처에서 만든다 —
#   타입이 늘면 거기만 고치면 되고, 여기서 다시 폭을 넓히는 일이 없다.
def _build_type_token_re() -> "re.Pattern[str]":
    from workflow.c_type_bounds import C_TYPE_ALIAS, FLOAT_TYPES

    words = {w for w in (*C_TYPE_ALIAS, *FLOAT_TYPES) if w}
    # 다어절('unsigned char')은 공백 유연 매칭, 긴 것부터 — 'unsigned'가 'unsigned char'를 선점하지 않게.
    alts = [re.escape(w).replace(r"\ ", r"\s+") for w in sorted(words, key=len, reverse=True)]
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b", re.I)


_TYPE_TOKEN_RE = _build_type_token_re()

# 서술문에 흔히 등장하는 일반 어휘 — 식별자 검사에서 면제(한국어 문장 속 영문 토큰).
_PROSE_COMMON = {
    "asil", "uds", "sds", "sts", "suts", "sits", "iso", "vectorcast", "mcdc",
    "input", "inputs", "output", "outputs", "expected", "precondition", "boundary",
    "min", "mid", "max", "null", "true", "false", "void", "return", "static", "const",
    "u8", "u16", "u32", "s8", "s16", "s32", "bool", "boolean", "int", "char", "float",
}
# 서수·연도처럼 문장에 자연스러운 작은 수 — 값 대조에서 면제(1개, 2가지 …).
_NUM_ALLOW = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "26262"}


def _numbers(text: str, *, strip_type_tokens: bool = False) -> set:
    """텍스트의 숫자 리터럴 집합.

    `strip_type_tokens`: 산문 검사용. C 타입 토큰(U16/int32_t/float64)의 비트폭을 값으로
    오인하지 않도록 먼저 제거한다. 결정론 페이로드 수집(허용 집합 구축) 쪽은 **끄고** 쓴다 —
    거기선 'U16'이 실려 있으면 16을 허용해 주는 편이 관대해서 안전하다.
    """
    src = _TYPE_TOKEN_RE.sub(" ", text or "") if strip_type_tokens else (text or "")
    return {m.group(0).lstrip("+") for m in _NUM_RE.finditer(src)}


def _identifiers(text: str) -> set:
    return {m.group(0).lower() for m in _IDENT_RE.finditer(text or "")}


def _collect_known(payload: Any, nums: set, idents: set) -> None:
    """결정론 페이로드를 재귀 순회해 등장한 숫자·식별자를 모은다(허용 집합의 근거)."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            idents.update(_identifiers(str(k)))
            _collect_known(v, nums, idents)
    elif isinstance(payload, (list, tuple)):
        for v in payload:
            _collect_known(v, nums, idents)
    elif payload is not None and not isinstance(payload, bool):
        s = str(payload)
        nums.update(_numbers(s))
        idents.update(_identifiers(s))


def _normalize_num(tok: str) -> Optional[int]:
    """'0xFF' / '255' → 255. 진법이 달라도 같은 값이면 같게 본다(비교 실패는 None)."""
    s = str(tok or "").strip().lstrip("+")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    try:
        if s.lower().startswith("0x"):
            n = int(s[2:], 16)
        elif s.lower().startswith("0b"):
            n = int(s[2:], 2)
        elif s.isdigit():
            n = int(s)
        else:
            return None
    except ValueError:
        return None
    return -n if neg else n


def filter_prose(
    fields: Dict[str, Any],
    known_numbers: set,
    allowed_identifiers: set,
) -> Dict[str, Any]:
    """필드별 환각 검사 → `{fields, dropped_fields:[{field, reason, token}]}`.

    필드 단위로만 폐기한다 — 한 문장이 틀렸다고 나머지 멀쩡한 서술문까지 버리지 않는다.
    """
    known = {n for n in (_normalize_num(x) for x in known_numbers) if n is not None}
    kept: Dict[str, str] = {}
    dropped: List[Dict[str, str]] = []
    for name in PROSE_FIELDS:
        text = str(fields.get(name) or "").strip()
        if not text:
            continue
        bad_num = next(
            (t for t in _numbers(text, strip_type_tokens=True)
             if t not in _NUM_ALLOW
             and (_normalize_num(t) is None or _normalize_num(t) not in known)),
            None,
        )
        if bad_num:
            dropped.append({"field": name, "reason": "unknown_number", "token": bad_num})
            continue
        bad_id = next(
            (t for t in _identifiers(text)
             if t not in allowed_identifiers and t not in _PROSE_COMMON
             # C 타입 토큰(int32_t/float64/U16…)은 환각 대상이 아니다 — 프로젝트 어휘다.
             # 숫자 검사와 같은 규칙을 쓴다(둘 중 하나만 면제하면 다른 쪽에서 걸린다).
             and not _TYPE_TOKEN_RE.fullmatch(t)),
            None,
        )
        if bad_id:
            dropped.append({"field": name, "reason": "unknown_identifier", "token": bad_id})
            continue
        kept[name] = text[:400]
    return {"fields": kept, "dropped_fields": dropped}


def generate_doc_prose(
    *,
    function: str,
    deterministic: Dict[str, Any],
    signature: str = "",
    function_diff: str = "",
    cfg: Optional[Dict[str, Any]] = None,
    agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """결정론 초안에 붙일 서술문을 만든다.

    반환 `{ok, fields, dropped_fields, note, model, reason}`.
    LLM 미설정/실패/전량 폐기여도 예외를 던지지 않는다 — 호출부는 표를 그대로 유지한다.
    """
    base: Dict[str, Any] = {
        "ok": False, "fields": {}, "dropped_fields": [],
        "note": IMPACT_DOC_PROSE_NOTE, "model": "", "reason": "",
    }
    if cfg is None:
        try:
            from workflow.impact_ai_guide import _load_impact_oai_config
            cfg = _load_impact_oai_config()
        except Exception:
            logger.warning("doc-prose LLM config 해석 실패", exc_info=True)
            cfg = None
    base["model"] = resolve_effective_model(cfg)
    if not cfg:
        return {**base, "reason": "llm_unavailable"}
    if not isinstance(deterministic, dict) or not deterministic:
        # 결정론 근거가 없으면 서술문이 붙을 자리도 없다 — 호출 자체를 생략(환각 유인 제거).
        return {**base, "reason": "no_deterministic_payload"}

    try:
        if agent_call is None:
            from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415
        from prompts import load_prompt

        system = load_prompt("impact_doc_prose")
        payload = json.dumps(
            {"function": function, "signature": signature, "deterministic": deterministic},
            ensure_ascii=False,
        )[:12000]
        if function_diff:
            payload += "\n\n[변경 diff]\n" + str(function_diff)[:4000]
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="impact_doc_prose")
        parsed = _extract_json_payload(output or "")
        if not isinstance(parsed, dict) or not any(parsed.get(f) for f in PROSE_FIELDS):
            return {**base, "reason": "llm_empty_or_invalid"}

        nums: set = set()
        idents: set = set()
        _collect_known(deterministic, nums, idents)
        idents |= _identifiers(signature) | _identifiers(function)
        idents.discard("")
        res = filter_prose(parsed, nums, idents)
        if not res["fields"]:
            return {**base, "dropped_fields": res["dropped_fields"], "reason": "all_fields_filtered"}
        return {**base, "ok": True, "fields": res["fields"], "dropped_fields": res["dropped_fields"]}
    except Exception:
        logger.warning("doc-prose 생성 실패", exc_info=True)
        return {**base, "reason": "llm_error"}
