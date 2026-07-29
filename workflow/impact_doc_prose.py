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
#   ⚠ 반대 방향 함정도 있다: 어휘를 경계값 테이블(`C_TYPE_ALIAS`)로만 좁히면 **U64/S64가
#   빠진다**(경계값 정의가 없어 테이블에 없을 뿐, `generators/sits.py`가 타입으로 인정하는
#   토큰이다) → "U64 폭" 같은 정상 문장이 `unknown_number: 64`로 폐기된다. 그래서 어휘 출처는
#   `KNOWN_TYPE_TOKENS`(경계값 유무와 무관한 타입 어휘)다.
def _build_type_token_re() -> "re.Pattern[str]":
    from workflow.c_type_bounds import KNOWN_TYPE_TOKENS

    words = {w for w in KNOWN_TYPE_TOKENS if w}
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


_PROMPT_PAYLOAD_BUDGET = 12000

# 프롬프트 예산 배정 순서. `PROSE_FIELDS` 각 필드가 근거로 삼는 문서 노드를 앞에 둔다 —
# 예산이 모자랄 때 밀려나야 하는 건 표 렌더용 부수 노드(columns 등)이지 문서 노드가 아니다.
_NODE_PRIORITY = ("uds", "sds", "sts", "sits", "suts", "suts_meta", "columns")


def _shrink_node(node: Any, budget: int) -> Any:
    """노드 하나를 예산 안으로 줄인다. **유효한 JSON 구조를 유지**한다(문자열 자르기 아님)."""
    def size(v: Any) -> int:
        try:
            return len(json.dumps(v, ensure_ascii=False))
        except (TypeError, ValueError):
            return len(str(v))

    if size(node) <= budget:
        return node
    if isinstance(node, list):
        # 반씩 줄이면 예산의 절반도 못 쓰고 끝난다(근거가 그만큼 덜 간다) → 비례 추정 후 미세 조정.
        keep = list(node)
        est = max(1, len(keep) * budget // max(1, size(keep)))
        keep = keep[:est]
        while len(keep) > 1 and size(keep) > budget:
            keep = keep[: len(keep) - max(1, len(keep) // 8)]
        # 미세 증가는 **횟수를 묶는다** — 한 걸음마다 접두 전체를 재직렬화하므로 무제한이면
        # 원소가 많은 리스트에서 O(n²)가 된다(요청 경로에서 CPU를 먹는다). 추정치가 이미
        # 가깝기 때문에 몇 걸음이면 충분하고, 못 채운 예산은 정확도가 아니라 여유일 뿐이다.
        for _ in range(8):
            if len(keep) >= len(node) or size(node[: len(keep) + 1]) > budget:
                break
            keep = node[: len(keep) + 1]
        if len(keep) == 1 and size(keep) > budget:
            return [_shrink_node(keep[0], budget)]
        return keep
    if isinstance(node, dict):
        out = dict(node)
        # 큰 값부터 줄인다 — 작은 메타(component/asil)를 먼저 버리면 서술 근거가 통째로 사라진다.
        # ⚠ 몫에 하한(예전 200)을 두면 **작은 예산을 지킬 수 없다**: 키가 많을 때 하한×키수가
        #   예산을 넘어, 호출부가 아무리 조여도 결과가 줄지 않는다(실측 13,490 > 12,000).
        for k in sorted(out, key=lambda k: size(out[k]), reverse=True):
            if size(out) <= budget:
                break
            out[k] = _shrink_node(out[k], max(1, budget // max(1, len(out))))
        return out
    # 스칼라는 문자열로 잘라 싣는다. ⚠ 직렬화하면 따옴표 2자가 더 붙으므로 그만큼 덜 자르면
    # 결과가 예산을 1회 초과하고, 호출부 회계가 그 노드를 **통째로 버린다**(근거 0).
    text = str(node)
    return text[: max(0, budget - 2)]


def trim_for_prompt(deterministic: Dict[str, Any], budget: int = _PROMPT_PAYLOAD_BUDGET) -> Dict[str, Any]:
    """프롬프트에 실을 결정론 페이로드를 **문서 노드마다 몫을 주어** 줄인다.

    ⚠ 예전엔 통짜 JSON을 `[:12000]`으로 잘랐다. SUTS 표만 21KB라 뒤에 오는 uds/sds/sts/sits가
    **전부 잘려나갔고**(실측), 그 상태로 `sts_purpose`·`sits_description`을 요구하니 근거 없는
    산문이 나왔다. 게다가 허용 집합은 잘리기 **전** 전체에서 만들어져, 모델이 본 적도 없는
    값까지 통과시키는 **더 느슨한** 게이트가 됐다(그래서 이 함수의 결과가 허용 집합의 출처다).

    문자열 절단이 아니라 구조 축소라, 모델에 가는 JSON은 항상 파싱 가능하다.
    """
    det = deterministic if isinstance(deterministic, dict) else {}
    present = [k for k in det if det.get(k) not in (None, "", [], {})]
    if not present:
        return {}
    # 우선순위 = 서술 필드가 실제로 근거로 삼는 문서 노드 먼저. 나머지(클라이언트가 임의로
    # 얹은 키)는 뒤로 — 예산이 모자랄 때 **문서 노드가 밀려나면 안 된다**.
    order = {n: i for i, n in enumerate(_NODE_PRIORITY)}
    keys = sorted(present, key=lambda k: (order.get(k, len(order)), present.index(k)))

    # 남은 예산을 남은 노드 수로 나눠 순서대로 배정하고 **실제 사용량만 차감**한다.
    # 몫에 하한을 두는 방식(구현 1안)은 하한×노드수가 예산을 넘어 총량 보장이 깨졌다.
    # ⚠ 노드 본문만 세면 **dict 래퍼가 빠진다** — `"key":` 와 쉼표가 키마다 붙어, 60키면
    #   660자가 예산 밖으로 샌다(실측 12,611 > 12,000). 키 비용까지 차감한다.
    # 구분자는 `json.dumps` 기본값이 `": "` 와 `", "` 로 **각 2자**다(합 4). 2자로만 세면 노드마다
    # 2자씩 새서, 마지막 노드가 정확히 몫을 채운 경우 최종 보증 루프가 그 노드를 통째로 뺀다.
    def _cost(key: str, node: Any) -> int:
        return len(json.dumps(node, ensure_ascii=False)) + len(json.dumps(key, ensure_ascii=False)) + 4

    out: Dict[str, Any] = {}
    remaining = budget - 2   # 바깥 `{}`
    for i, k in enumerate(keys):
        left = len(keys) - i
        # 몫에서 **키 비용을 먼저 뺀다**. 안 빼면 `_shrink_node`가 몫을 정확히 채우는 경우
        # (문자열 노드는 항상 `[:budget]`으로 딱 맞춘다) 키 때문에 1회 초과해 **노드가 통째로
        # 탈락**한다 — 잘라서 일부라도 싣는 것이 목적인데 근거가 0이 된다(실측).
        overhead = len(json.dumps(k, ensure_ascii=False)) + 4
        share = max(1, remaining // left - overhead)
        node = _shrink_node(det[k], share)
        cost = _cost(k, node)
        if cost > remaining:
            continue   # 이 노드는 통째로 못 싣는다 — 호출부가 trimmed_nodes 로 밝힌다
        out[k] = node
        remaining -= cost
    # 남은 예산은 앞 순위 노드부터 되돌려 준다(균등 배정에서 남은 여유 회수).
    for k in keys:
        if remaining <= 0 or k not in out:
            continue
        cur = len(json.dumps(out[k], ensure_ascii=False))
        if cur >= len(json.dumps(det[k], ensure_ascii=False)):
            continue
        grown = _shrink_node(det[k], cur + remaining)
        gained = len(json.dumps(grown, ensure_ascii=False)) - cur
        if gained <= 0 or gained > remaining:
            continue
        out[k] = grown
        remaining -= gained
    # 최종 보증 — 위 배정은 `_shrink_node`가 "최선 노력"(dict 키 자체가 차지하는 바이트는 못 줄임)
    # 이라 근사치다. 여기서 실제 직렬화 길이로 재고, 넘치면 **우선순위 낮은 노드부터** 뺀다.
    # 노드 수가 유한하므로 반드시 끝나고, 결과 길이는 예산 이하가 보장된다.
    while out and len(json.dumps(out, ensure_ascii=False)) > budget:
        out.pop(keys[max(i for i, k in enumerate(keys) if k in out)])
    return out


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
        # 프롬프트 예산으로 근거가 줄어든 문서 노드 — 화면이 "일부 근거만 사용"을 말할 수 있게.
        "trimmed_nodes": [],
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
        # 프롬프트에 실제로 실리는 것 = 이 `sent`. 아래 허용 집합도 **이것**에서 만든다.
        sent = trim_for_prompt(deterministic)
        if not sent:
            # 노드가 전부 비었으면 허용 집합도 비어 어떤 문장도 통과 못 한다 — 호출 자체를 생략.
            return {**base, "reason": "no_deterministic_payload"}
        # 절단을 침묵시키지 않는다 — 근거의 일부만 보고 쓴 산문임을 호출부가 말할 수 있게.
        # ⚠ `sent` 만 훑으면 **통째로 빠진 노드가 빠진다** — 축소보다 큰 손실인데 오히려 침묵한다.
        # 빈 노드(`{}`/`[]`)는 애초에 실을 게 없어 제외한다 — 프론트가 없는 문서에도 자리를
        # 채워 보내므로(`docProposalFor(fn,'sits') || {}`), 안 빼면 매번 "일부만 사용"이 뜬다.
        trimmed = sorted(
            k for k, v in deterministic.items()
            if v not in (None, "", [], {})
            and json.dumps(sent.get(k), ensure_ascii=False) != json.dumps(v, ensure_ascii=False)
        )
        payload = json.dumps(
            {"function": function, "signature": signature, "deterministic": sent},
            ensure_ascii=False,
        )
        if function_diff:
            payload += "\n\n[변경 diff]\n" + str(function_diff)[:4000]
        output = agent_call(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ], role="analysis", stage="impact_doc_prose")
        parsed = _extract_json_payload(output or "")
        if not isinstance(parsed, dict) or not any(parsed.get(f) for f in PROSE_FIELDS):
            return {**base, "reason": "llm_empty_or_invalid"}

        # ⚠ 허용 집합의 출처는 **모델이 실제로 본 것**(`sent`)이어야 한다. 원본
        #   `deterministic`(상한 256KB)에서 만들면, 프롬프트에서 잘려나가 모델이 본 적 없는
        #   값까지 "결정론에 있는 값"으로 통과시킨다 = 게이트가 스스로 느슨해진다.
        nums: set = set()
        idents: set = set()
        _collect_known(sent, nums, idents)
        idents |= _identifiers(signature) | _identifiers(function)
        idents.discard("")
        res = filter_prose(parsed, nums, idents)
        if not res["fields"]:
            return {**base, "dropped_fields": res["dropped_fields"],
                    "trimmed_nodes": trimmed, "reason": "all_fields_filtered"}
        return {**base, "ok": True, "fields": res["fields"],
                "dropped_fields": res["dropped_fields"], "trimmed_nodes": trimmed}
    except Exception:
        logger.warning("doc-prose 생성 실패", exc_info=True)
        return {**base, "reason": "llm_error"}
