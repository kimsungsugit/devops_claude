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

## ⚠ UDS(docx)는 위 표와 **다른 경로**다 (실측 2026-08-31)

위 실측은 SwUTS(**xlsm**)다. 시트 기반 빌더는 시트를 통째로 복사하므로 표지·이력이
정말 따라온다. UDS 는 docx 이고 `docx_builder` 가 본문을 **재작성**한다
(`_extract_template_blocks` → `_clear_docx_body` → 블록 재구성).

KJPDS02_PV 정본(53MB) vs 표준 템플릿 v0.10, 소스 25파일/57함수로 실제 생성해 비교:

| | 표준 템플릿 | 정본 |
|---|---|---|
| 소요 / 산출물 | 17초 / 375KB | **1,116.5초** / 64.4MB |
| payload 함수 반영 | **0/57 (0.0%)** | **57/57 (100.0%)** |
| SwUFn heading | 8개(자리표시자) | 1,035개(실제 함수명) |
| 텍스트박스(표지) | 32 → **0** | 20 → **0** |
| 콘텐츠 컨트롤 | 13 → **0** | 9 → **0** |
| 표 데이터 행 | 헤더만, 나머지 **빈칸** | 〃 |

즉 docx 에서 정본이 주는 것은 표지가 아니라 **함수 heading 집합**이고(그래서 반영률이
0% → 100% 로 갈린다), 표지·이력 데이터·콘텐츠 컨트롤 값은 **어느 템플릿이든 유실된다**
(`p.text` 가 `w:sdt`·`wps:txbx` 안의 런을 못 읽고, 표는 `(행수,열수,style,헤더)` 로만
담기기 때문). 사유 문구를 문서 종류별로 가르는 이유가 이것이다 — 한 문장으로 뭉치면
둘 중 한쪽에는 반드시 거짓이 된다.
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


# 템플릿 출처 선택지 — **철자의 단일 출처**.
#
# 이 토큰은 프론트(`<select value>`) · 라우터(`Form`) · 게이트(공시) 세 곳을 지난다.
# 한 곳만 철자가 어긋나면 조용히 기본값으로 떨어지고, 그 결과는 "고른 적 없음" 과
# 화면상 구분되지 않는다 — 사용자는 골랐다고 믿는데 문서는 그대로다.
TEMPLATE_SOURCE_REFERENCE = "reference"
TEMPLATE_SOURCE_STANDARD = "standard"
# 빈 문자열 = 미설정 = 서버 기본. 저장소가 빈 값에서 키를 지우는 규약과 짝이다
# (`sharedInputs.js::saveDocGenChoice`) — 여기서 기본값을 복제하지 않기 위함이다.
TEMPLATE_SOURCE_CHOICES: Tuple[str, ...] = (
    "", TEMPLATE_SOURCE_REFERENCE, TEMPLATE_SOURCE_STANDARD,
)


def prefer_reference_from(choice: str) -> bool:
    """선택 토큰 → `prefer_reference`.

    `standard` **만** 정본 우선을 끈다. 미설정·미지값은 서버 기본(정본 우선)이다 —
    모르는 값에서 동작이 갈리면 같은 저장값에 게이트와 생성기가 반대말을 한다
    (`_suts_normalize_scope` 가 같은 이유로 생성기 정의를 되쓴다).
    """
    return str(choice or "").strip().lower() != TEMPLATE_SOURCE_STANDARD


# 시트 기반 빌더(xlsm)는 템플릿 **시트를 통째로** 복사하므로 표지·이력이 실제로
# 따라온다. docx(UDS)는 본문을 **재작성**하므로 그렇지 않다 — 아래 두 함수가 그 차이를
# 문장으로 만든다. 한 문장으로 뭉치면 둘 중 하나에는 반드시 거짓이 된다.
_SHEET_BASED = ("sts", "suts", "sits")


def _reference_gain(kind: str) -> str:
    """정본을 템플릿으로 삼아 **실제로 얻는 것**."""
    if kind in _SHEET_BASED:
        return ("표지·이력·Introduction(표기 규약 표)이 납품본과 같아집니다. "
                "명세 시트는 새로 씁니다.")
    # UDS(docx) — 얻는 것은 표지가 아니라 **함수 heading 집합**이다. 이 라이터는
    # 템플릿의 heading 을 순회하며 payload 함수를 찾으므로, 템플릿에 없는 함수는
    # 문서에 안 들어간다. 실측: 자리표시자 템플릿 0/57 → 정본 57/57.
    return ("정본의 함수 heading 집합을 그대로 써서 **이 프로젝트 함수가 문서에 실립니다** "
            "— 실측으로 표준 템플릿은 57개 중 0개, 정본은 57개 전부였습니다. "
            "명세 본문은 새로 씁니다.")


def _reference_caveat(kind: str) -> str:
    """정본을 템플릿으로 삼을 때 **따라오지 않는 것**(침묵하면 거짓 공시가 된다)."""
    if kind in _SHEET_BASED:
        return (" ⚠ 정본의 History 시트가 과거 개정 이력째로 딸려옵니다 — "
                "새 문서로 낼 때는 그 시트를 확인하세요.")
    return (" ⚠ docx 는 본문 **구조만** 복제합니다: 표지(텍스트박스)·표의 데이터 행·"
            "콘텐츠 컨트롤 값은 따라오지 않습니다(실측 텍스트박스 32→0, 이력 표는 "
            "헤더만 남음). 정본이 크면 오래 걸립니다 — 53MB 정본으로 18분 37초, "
            "표준 템플릿은 17초였습니다.")


def _standard_caveat(kind: str) -> str:
    """표준 템플릿을 고른 쪽의 대가. UDS 는 이게 **문서를 통째로 비운다**."""
    if kind in _SHEET_BASED:
        return ""
    return (" ⚠ UDS 는 템플릿의 heading 집합이 곧 문서의 함수 목록이라, 자리표시자만 있는 "
            "표준 템플릿이면 분석한 함수가 **하나도 실리지 않습니다**(실측 0/57).")


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
            f"{kind.upper()} 정본을 템플릿으로 사용합니다 — {_reference_gain(kind)}"
            f"{_reference_caveat(kind)}"
        )
    if tpl:
        why = f"{kind.upper()} 표준 템플릿을 사용합니다.{_standard_caveat(kind)}"
        if prefer_reference and not ref:
            why += " (정본이 등록돼 있지 않아 폴백했습니다 — Introduction 시트가 없을 수 있습니다.)"
        return tpl, why
    if ref:
        return ref, (f"{kind.upper()} 정본을 템플릿으로 사용합니다 (표준 템플릿 미등록) — "
                     f"{_reference_gain(kind)}{_reference_caveat(kind)}")
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
