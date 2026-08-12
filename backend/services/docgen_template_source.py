"""생성 산출물의 **템플릿을 무엇으로 삼을지** 정하는 단일 규칙.

## 왜 정본을 템플릿으로 쓰나 (사용자 결정, 2026-08-12)

생성기는 템플릿에서 표지·이력·Introduction·Test Environment 시트를 가져오고,
명세 시트(`2.SW Unit Test Spec` 등)만 지우고 새로 쓴다. 그래서 템플릿을 무엇으로
잡느냐가 **문서의 나머지 전부**를 정한다.

실측(2026-08-11):

| | 회사 표준 템플릿 v0.10 | 납품 정본 v1.02 |
|---|---|---|
| SwUTS 시트 | Cover · History · 1.Test Environment · 2.SW Unit Test Spec | + **Introduction** |
| Introduction | **없음** | 1.5 Test Method / 1.6 TC Generation Method **표기 규약** |
| 폭 | 28열(Param 10 고정) | 189열 |

검증기가 매 생성마다 `Optional sheet missing: 1.Introduction` 으로 FAIL 을 내던 것이
이 때문이다. 그리고 문서 안에 표기 규약(REQ/FI, AOR/AEC …)이 없으면 읽는 사람이
`Safety Related` 나 `Test Method` 칸을 대조할 표가 없다.

→ **정본이 있으면 정본을, 없으면 표준 템플릿을** 쓴다.

## 무엇을 선택했는지 반드시 말한다

어느 쪽을 썼는지는 산출물의 성격을 바꾸므로 침묵하면 안 된다. 이 함수는 경로와
함께 **사람이 읽는 사유**를 돌려주고, 호출부는 그것을 로그·응답에 싣는다.

⚠ 정본을 템플릿으로 쓰면 **정본의 History 시트가 그대로 딸려온다**(과거 개정 이력).
   그건 연속성 측면에선 맞고 "새 문서" 관점에선 낡은 값이다 — 어느 쪽이 맞는지는
   프로젝트 규약이라 여기서 정하지 않고 사유 문자열로 드러낸다.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

_logger = logging.getLogger("devops_api.docgen_template_source")

# 문서 종류 → (정본이 등록된 linked_docs 키, 표준 템플릿 키)
_DOC_KEYS: Dict[str, Tuple[str, str]] = {
    "uds": ("uds", "uds_template"),
    "sts": ("sts", "sts_template"),
    "suts": ("suts", "suts_template"),
    "sits": ("sits", "sits_template"),
}


def choose_template_source(
    doc_type: str,
    *,
    registered_template: str = "",
    reference_doc: str = "",
    prefer_reference: bool = True,
) -> Tuple[str, str]:
    """`(고를 경로, 사유)` — 아직 **해석(materialize)은 하지 않는다**.

    Args:
        registered_template: 레지스트리/설정의 `*_template`(회사 표준 템플릿).
        reference_doc: 같은 종류의 **납품 정본**(`linked_docs[doc_type]`).
        prefer_reference: 정본 우선 여부. 끄면 종전 동작(표준 템플릿 우선).

    빈 문자열을 돌려주면 템플릿 없이 생성한다(생성기가 워크북을 새로 만든다).
    """
    ref = str(reference_doc or "").strip()
    tpl = str(registered_template or "").strip()
    kind = str(doc_type or "").strip().lower()

    if prefer_reference and ref:
        return ref, (
            f"{kind.upper()} 정본을 템플릿으로 사용합니다 — 표지·이력·Introduction"
            f"(표기 규약 표)이 납품본과 같아집니다. 명세 시트는 새로 씁니다."
        )
    if tpl:
        why = f"{kind.upper()} 표준 템플릿을 사용합니다."
        if prefer_reference and not ref:
            why += " (정본이 등록돼 있지 않아 폴백했습니다 — Introduction 시트가 없을 수 있습니다.)"
        return tpl, why
    if ref:
        return ref, f"{kind.upper()} 정본을 템플릿으로 사용합니다 (표준 템플릿 미등록)."
    return "", f"{kind.upper()} 템플릿이 없어 서식 없이 생성합니다."


def resolve_template_for(
    doc_type: str,
    *,
    registered_template: str = "",
    reference_doc: str = "",
    prefer_reference: bool = True,
    resolver: Optional[Any] = None,
) -> Tuple[Optional[str], str]:
    """고른 템플릿을 **로컬 경로로 해석**해서 돌려준다.

    cloudium(`U:`) 경로는 worker 경유로 로컬화해야 openpyxl/python-docx 가 열 수 있다.
    해석에 실패하면 표준 템플릿으로 한 번 더 시도한다 — 정본이 stale 이라 못 읽는
    경우까지 생성 자체가 막히면 안 되기 때문이다. **폴백했다는 사실은 사유에 남긴다.**
    """
    from backend.services.resolver_helpers import resolve_builder_input

    _resolve = resolver or resolve_builder_input
    chosen, why = choose_template_source(
        doc_type,
        registered_template=registered_template,
        reference_doc=reference_doc,
        prefer_reference=prefer_reference,
    )
    if not chosen:
        return None, why

    local = _resolve(chosen, label=f"{doc_type} 템플릿")
    if local:
        _logger.info("docgen template[%s]: %s (%s)", doc_type, chosen, why)
        return local, why

    # 고른 쪽을 못 읽었다 — 다른 쪽이 있으면 시도하고 그 사실을 말한다.
    other = str(registered_template or "").strip() if chosen == str(reference_doc or "").strip() \
        else str(reference_doc or "").strip()
    if other:
        local2 = _resolve(other, label=f"{doc_type} 템플릿(폴백)")
        if local2:
            why2 = (
                f"{why} ⚠ 고른 파일을 읽지 못해 다른 템플릿으로 폴백했습니다 — "
                f"등록 경로가 낡았는지 확인하세요: {chosen}"
            )
            _logger.warning("docgen template[%s] fallback: %s → %s", doc_type, chosen, other)
            return local2, why2

    why3 = f"{why} ⚠ 템플릿을 읽지 못해 서식 없이 생성합니다: {chosen}"
    _logger.warning("docgen template[%s] unreadable: %s", doc_type, chosen)
    return None, why3


def linked_doc_keys(doc_type: str) -> Tuple[str, str]:
    """`(정본 키, 표준 템플릿 키)`. 호출부가 레지스트리에서 꺼낼 때 쓴다."""
    return _DOC_KEYS.get(str(doc_type or "").strip().lower(), ("", ""))
