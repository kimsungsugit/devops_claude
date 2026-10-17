"""라이터의 `enrichment` 기록을 읽는 **판정 단일 출처**. (R47-h N33, 2026-09-11)

부모 라이터(`backend.helpers.uds.merge_enriched_function_details`)는 빌더 보강본을 payload 에 병합한 결과를
`{"applied": True, "functions": n, "unknown_keys": m, ...}` 또는 `{"applied": False, "reason": ...}` 로 남기고,
같은 요약을 `gen_stats.json` 에 병기한다(R47-g). 이 기록을 읽는 표면이 둘이다:

| 표면 | 모듈 | 읽는 파일 |
|---|---|---|
| 근거 API → 보드 "게이트 반영" | `report_gen.evidence.read_reference_enrichment` | gen_stats 우선, 구 run 은 payload |
| 게이트 md 머리글 "Scored fields source" | `report_gen.validation.generate_uds_field_quality_gate_report` | payload |

R47 리뷰 W3 의 규칙 — **`applied:true · functions:0 · unknown_keys:n>0` 은 되쓰기 실패다**(보강본 키가 payload
함수 키와 하나도 맞지 않았다) — 를 근거 리더만 알고 있었고, md 머리글은 `applied` 를 날것으로 읽어 같은 run 을
"빌더가 되쓴 값(보강 반영 0 함수) · 문서를 만든 값과 같다" 라 적었다. 보드는 ⚠, md 는 성공 — 한 기록에 두 판정.
판정을 여기 하나로 두고 두 표면이 같은 함수를 부른다.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def int_field(d: Dict[str, Any], key: str) -> Optional[int]:
    """정수 필드만 값으로 인정한다 — bool·문자열·부재는 미기록(None)이지 0 이 아니다."""
    v = d.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def normalize_enrichment(rec: Dict[str, Any], record_source: str) -> Dict[str, Any]:
    """라이터의 `enrichment` 기록 → 판정 계약 `{present, applied, functions, unknown_keys, reason, record_source}`.

    판정 규칙은 출처(통계·payload)와 무관하고, `record_source` 는 어느 파일에서 읽었는지만 말한다(R47-g 리뷰 W1 —
    없으면 병기 경로가 끊겨도 값은 같고 소요만 2.3배로 돌아가며 아무 신호가 없다). `rec` 는 호출자가 dict 를 보장한다
    (두 호출자 모두 `isinstance(..., dict)` 뒤에 부른다).
    """
    if rec.get("applied") is True:
        fn = int_field(rec, "functions")
        unknown = int_field(rec, "unknown_keys")
        if fn is None or unknown is None:
            # (R47-h 리뷰 W1) 두 수 중 하나라도 정수가 아니면 아래 규칙을 잴 수 없다 — 미기록을 0 으로 접어
            #   "되쓴 값 ? 함수 · 문서를 만든 값과 같다" 를 내던 것을 판정 불가(=성공 아님)로. 현행 라이터는 항상
            #   정수 둘을 쓰므로 손상·수기 편집·미래 라이터에서만 닿는 경계다.
            return {"present": True, "applied": False, "functions": fn, "unknown_keys": unknown,
                    "reason": "되쓴 함수 수·미지 키 수가 정수로 기록되지 않아 되쓰기 판정 불가",
                    "record_source": record_source}
        if fn == 0 and unknown > 0:
            # (R47 리뷰 W3) 라이터는 "병합 성공 0건 · 미지 키 n" 을 남긴다 — 되쓰기 **실패**다. applied:true 를
            #   그대로 내면 화면·md 가 "되쓴 값 0 함수 — 문서를 만든 값" 이라는 거짓을 그린다. 0/0 은 실패가 아니다
            #   (보강본이 비어 있었을 뿐 — 대조군 가드).
            return {"present": True, "applied": False, "functions": 0, "unknown_keys": unknown,
                    "reason": f"보강본 키 {unknown}건이 payload 함수 키와 하나도 맞지 않아 되쓴 값 없음",
                    "record_source": record_source}
        return {"present": True, "applied": True, "functions": fn, "unknown_keys": unknown, "reason": None,
                "record_source": record_source}
    return {"present": True, "applied": False, "functions": None, "unknown_keys": None,
            "reason": str(rec.get("reason") or "사유 미기록"), "record_source": record_source}
