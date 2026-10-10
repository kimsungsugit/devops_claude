"""ID 정합성 감사 (hiMA WrongRelatedID / WrongName 차별점 대응).

hiMA(외부 C# 추적성 도구)는 RelatedID를 **정확(exact) 멤버십**으로 매칭한다. 따라서
대상 문서에 없는 ID를 참조하거나(WrongRelatedID), 철자/공백/대소문자만 다른 ID는
**silent하게 잘못 연결되거나 누락**된다. 우리 매트릭스 빌더(`generate_uds_traceability_matrix`)도
요구사항 ID를 `_normalize_req_id`(모든 공백 제거 + 대문자화)로 정규화하므로, 서로 다른 raw
철자가 같은 canonical로 붕괴하면 **첫 항목만 표시되고 나머지는 log로만 흘려 삼켜진다**.

이 모듈은 그 *삼켜지던* 정합성 해저드를 **명시적·결정적 감사 finding**으로 표면화한다:

1. **정규화 충돌(id_collisions)**: raw 철자 N개(≥2)가 같은 canonical로 붕괴 → 추적이
   silent하게 병합/분리. hiMA exact-match가 오인하는 바로 그 클래스.
2. **상향 dangling 참조(dangling_refs)**: 설계(SDS)/단위설계(UDS)가 *SRS 부분집합에 없는*
   요구사항 ID를 참조 → '존재하지 않는 대상 인용'(WrongRelatedID). 단, 다른 ID namespace
   (SwFn/SwST 등)는 정당한 범위 차이일 수 있으므로 **prefix별로 묶어 정직하게** 보고한다.
3. **placeholder 참조 ID(placeholder_ids)**: `SwCom_XX`/`TBD`/`??` 등 미완성 템플릿 토큰.

설계 원칙(trace_link_table.py와 동일):
- **순수 함수**: 입력을 변형하지 않는다. 부작용/시각(datetime) 없음.
- **결정적**: 모든 목록을 canonical 기준으로 정렬 — 같은 입력 → 동일 출력.
- **false-positive 보수**: 충돌/dangling은 사실(fact)이며, 정당할 수 있는 dangling은
  namespace 그룹으로 분류해 '결함 단정'을 피한다(과장 금지).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

# dangling/충돌이 정당할 수 있는 ID '계열' — 선행 알파벳 run을 namespace prefix로 본다.
_PREFIX_RE = re.compile(r"^[A-Za-z]+")

# placeholder/미완성 토큰: SwCom_XX, FOO_NN, ??, <id>, TBD/TODO/FIXME 등.
# 보수적으로 — 2글자+ X/N run(경계), 2개+ '?', 또는 명시 토큰만. 단일 X(MAX 등) 미매칭.
# X/N run은 *대문자 한정*: placeholder 관례(SwCom_XX)는 대문자이고, 실제 C 식별자의
# 소문자 토큰(eeprom_xx_write, g_nnn_idx)을 오탐하지 않도록 함. 키워드만 대소문자 무관.
_PLACEHOLDER_RE = re.compile(
    r"(?:\b|_)(?:X{2,}|N{2,}|\?{2,})(?:\b|_|$)|<[^>]*>|\b(?i:TBD|TODO|FIXME)\b",
)

# DoS / 출력 비대 방지 캡 — counts(stats)는 전수, list만 절단.
_MAX_GROUP_LIST = 5000      # 충돌/dangling 목록 최대 항목
_MAX_VARIANTS = 50          # 한 충돌 그룹의 raw 변형 표시 상한
_MAX_PLACEHOLDER = 2000

# namespace prefix(대문자) → V-model 계층 라벨. hiMA IDRules + 실문서 정의/참조 분포로 도출.
# foreign dangling이 "오류"가 아니라 "어느 계층의 ID인가"를 명시해 V-model 구조차를 가독화.
# (예: SwSTR/SwST/SwTK는 SDS가 정의하는 설계 ID → SRS 요구사항이 아닌 게 정상.)
_VMODEL_LAYER = {
    # 요구사항(SwRS): SRS universe가 정의하는 계열
    "SWTR": "SwRS(요구사항)", "SWTSR": "SwRS(요구사항)", "SWNTR": "SwRS(요구사항)",
    "SWNTSR": "SwRS(요구사항)", "SWCNF": "SwRS(요구사항)", "SWEI": "SwRS(요구사항)",
    "SWEIF": "SwRS(요구사항)",
    # 설계(SwDS): 아키텍처 설계서가 정의하는 ID — UDS가 참조하나 SRS엔 없음
    "SWSTR": "SwDS(설계)", "SWST": "SwDS(설계)", "SWTK": "SwDS(설계)",
    "SWCOM": "SwDS(설계)", "SWFN": "SwDS(설계)", "SWCON": "SwDS(설계)",
    "SWPT": "SwDS(설계)",
    # 단위설계(SwUDS)
    "SWUFN": "SwUDS(단위설계)",
    # 시스템 계층
    "SYRS": "Sy(시스템)", "SYDS": "Sy(시스템)",
}


def _layer_of(namespace: str) -> str:
    """namespace prefix → V-model 계층 라벨('기타'=미분류). 'SWSTR'→'SwDS(설계)'."""
    return _VMODEL_LAYER.get(str(namespace or "").upper(), "기타")


def _namespace(raw: str) -> str:
    """ID의 namespace prefix(선행 알파벳 run, 대문자) — dangling 정직 그룹핑용.

    'SwRS_001'→'SWRS', 'g_drvin_x'→'G', 숫자/기호 시작이면 '#'.
    """
    m = _PREFIX_RE.match(str(raw or "").strip())
    return m.group(0).upper() if m else "#"


def _is_placeholder(raw: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(str(raw or "")))


def build_integrity_audit(
    req_ids: Iterable[str],
    norm_to_raws: Mapping[str, Sequence[str]],
    referenced: Mapping[str, Mapping[str, str]],
    related_ids: Mapping[str, Iterable[str]],
) -> Dict[str, Any]:
    """ID 정합성 감사 결과(순수·결정적) 생성.

    Args:
        req_ids: 매트릭스 대상(SRS) 요구사항 정규화 ID 목록 — dangling 판정 universe.
        norm_to_raws: {canonical → [raw 철자, ...]} 전체. 한 canonical에 raw가 2개+면 충돌.
        referenced: {band → {정규화_rid → raw_rid}} 설계/단위설계가 참조한 요구사항.
            band 예: 'SDS'(설계 component_id가 인용한 req), 'UDS'(mapping_pairs의 req).
            정규화_rid가 req_ids universe에 없으면 상향 dangling(존재하지 않는 대상 참조).
        related_ids: {band → [관련 산출물 id, ...]} placeholder 스캔 대상
            (SDS 컴포넌트명·UDS 함수명 등 raw).

    Returns:
        dict: id_collisions / dangling_refs / dangling_by_namespace /
              placeholder_ids / stats. 모든 목록 canonical 정렬.
    """
    req_set = {str(r or "").strip() for r in (req_ids or []) if str(r or "").strip()}
    # SRS universe에 실제 등장하는 namespace 집합 — dangling 심각도 분류용.
    # 어떤 ID가 'SRS에 쓰이는 namespace인데 이 ID만 부재'면 오타/오참조 의심(suspect,
    # hiMA WrongRelatedID 본류). 'SRS에 아예 없는 namespace'면 다른 요구사항 계층(foreign,
    # 구조적 — V-model 계층차로 정상일 수 있음). 이 구분이 거짓경보(노이즈)를 막는다.
    srs_namespaces = {_namespace(r) for r in req_set}

    # ── 1. 정규화 충돌: 한 canonical에 distinct raw 철자가 2개+ ──
    collisions: List[Dict[str, Any]] = []
    for canon in sorted(norm_to_raws or {}):
        raws = norm_to_raws[canon] or []
        # distinct·정렬 — 순서 무관 결정성. (raw가 정확히 같으면 충돌 아님)
        distinct = sorted({str(r) for r in raws if str(r or "").strip()})
        if len(distinct) < 2:
            continue
        collisions.append(
            {
                "canonical": canon,
                "variants": distinct[:_MAX_VARIANTS],
                "variant_count": len(distinct),
                # 빌더 first-wins 규칙상 표시에 살아남는 철자(목록의 첫 raw가 아니라
                # 정렬상 첫 항목은 단정 불가 → 'kept'는 변형 중 사전순 첫으로 둔다.
                # 감사 목적상 'N개가 1개로 병합됨'이 핵심 신호이며 어느 게 살았는지는 부차).
                "kept": distinct[0],
            }
        )
    # 충돌 많은 순(변형 수 ↓), 동률은 canonical 사전순 — 결정적.
    collisions.sort(key=lambda c: (-c["variant_count"], c["canonical"]))
    collision_affected_raw = sum(c["variant_count"] for c in collisions)

    # ── 2. 상향 dangling: 참조 req가 SRS universe에 없음 (namespace별 + 심각도 분류) ──
    # severity: 'suspect' = SRS에 쓰이는 namespace인데 이 ID만 부재(오타/오참조 의심,
    #   hiMA WrongRelatedID 본류) / 'foreign' = SRS에 없는 namespace(다른 요구사항 계층,
    #   구조적일 수 있음 — 거짓경보 방지). dangling_suspect_count가 진짜 검토 우선순위.
    dangling_refs: Dict[str, List[Dict[str, str]]] = {}
    dangling_by_namespace: Dict[str, Dict[str, int]] = {}
    # foreign(계층참조)을 V-model 계층별로 집계 — "어느 계층의 ID인가" 가독화(추가형).
    dangling_layer_summary: Dict[str, int] = {}
    dangling_total = 0
    suspect_total = 0
    for band in sorted(referenced or {}):
        mapping = referenced.get(band) or {}
        band_list: List[Dict[str, str]] = []
        ns_counts: Dict[str, int] = {}
        for norm in sorted(mapping):
            n = str(norm or "").strip()
            if not n or n in req_set:
                continue
            raw = str(mapping.get(norm) or norm)
            ns = _namespace(raw)
            severity = "suspect" if ns in srs_namespaces else "foreign"
            layer = _layer_of(ns)
            if severity == "suspect":
                suspect_total += 1
            else:
                # foreign만 계층 집계(suspect는 SRS 내 오타라 계층차 아님).
                dangling_layer_summary[layer] = dangling_layer_summary.get(layer, 0) + 1
            band_list.append(
                {"ref_id": raw, "normalized": n, "namespace": ns,
                 "severity": severity, "layer": layer}
            )
            ns_counts[ns] = ns_counts.get(ns, 0) + 1
        if band_list:
            dangling_total += len(band_list)
            # suspect(오타 의심) 우선 표시 — 같은 severity 내 정규화 ID 사전순(결정적).
            band_list.sort(key=lambda d: (0 if d["severity"] == "suspect" else 1, d["normalized"]))
            dangling_refs[band] = band_list[:_MAX_GROUP_LIST]
            dangling_by_namespace[band] = dict(sorted(ns_counts.items()))

    # ── 3. placeholder 참조 ID ──
    placeholder_ids: Dict[str, List[str]] = {}
    placeholder_total = 0
    for band in sorted(related_ids or {}):
        found = sorted(
            {str(r).strip() for r in (related_ids.get(band) or []) if _is_placeholder(r)}
        )
        if found:
            placeholder_total += len(found)
            placeholder_ids[band] = found[:_MAX_PLACEHOLDER]

    clean = not collisions and dangling_total == 0 and placeholder_total == 0

    return {
        "id_collisions": collisions[:_MAX_GROUP_LIST],
        "dangling_refs": dangling_refs,
        "dangling_by_namespace": dangling_by_namespace,
        # foreign dangling의 V-model 계층 분포(예: {'SwDS(설계)': 34}) — 추가형.
        "dangling_layer_summary": dict(sorted(dangling_layer_summary.items())),
        "placeholder_ids": placeholder_ids,
        "stats": {
            "collision_count": len(collisions),
            "collision_affected_raw": collision_affected_raw,
            "dangling_count": dangling_total,
            # suspect = SRS namespace 내 부재(오타/오참조 의심, 검토 우선) / foreign = 다른 계층.
            "dangling_suspect_count": suspect_total,
            "dangling_foreign_count": dangling_total - suspect_total,
            "placeholder_count": placeholder_total,
            # 감사 합격(finding 0) — '깨끗함'을 명시적으로 신호(silent 0과 구분).
            "clean": clean,
        },
    }
