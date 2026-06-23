"""명시 RelatedID 링크 테이블 파생 (hiMA식 추적성 매트릭스 지원).

`generate_uds_traceability_matrix()`의 결과(rows/summary)로부터 평면(flat)
**(target_id, related_id, related_type, source, confidence)** 링크 테이블을
파생한다. hiMA(외부 C# 추적성 도구)의 `SpecItem.RelatedID`처럼, 런타임 휴리스틱
bridge가 빌드마다 재계산하는 것과 달리 **명시적이고 결정적인(같은 입력 → 동일 출력)
감사 가능 baseline**을 제공한다.

설계 원칙:
- **순수 함수**: 입력 matrix dict를 변형하지 않는다(additive). 부작용/시각(datetime) 없음.
- **결정적(P2)**: 모든 링크를 전 필드 기준 정렬해 같은 입력이면 byte-identical 출력.
  (상류 SwCom_XX 번호의 위치기반 fragility는 sits.py 영역이며 여기서 canonical
   정렬로 baseline 안정성만 보장 — 심층 content-addressing은 후속 과제.)
- **커버리지 %는 부동소수 나눗셈**: hiMA가 정수나눗셈으로 66.0%를 절삭하던 버그를
  되풀이하지 않는다.

이 모듈은 기존 매트릭스 빌더/생성기를 한 줄도 수정하지 않고 그 출력만 소비한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# 추적 체인 밴드 순서 (V-model: 설계 → 단위 → 시험 레벨)
BANDS: Tuple[str, ...] = ("SDS", "UDS", "STS", "SUTS", "SITS", "VectorCAST")

# related_type 라벨 — 밴드별 관계 종류 (hiMA DocumentType 대응)
_RELATED_TYPE = {
    "SDS": "SDS_COMPONENT",
    "UDS": "UDS_FUNCTION",
    "STS": "STS_TEST",
    "SUTS": "SUTS_TEST",
    "SITS": "SITS_TEST",
    "VectorCAST": "VCAST_FUNCTION",
}

# ASIL 결합(P5) — hiMA가 셀에 비노출하는 ASIL을 추적성 갭과 결합한다(차별점).
# 등급 순위(ISO 26262: QM<A<B<C<D)와 등급별 '기대 시험 밴드'(추적성 관점, 간소화):
#   D/C(고안전): 단위(SUTS)+통합(SITS) 시험 추적 기대.
#   A/B: 최소 1개 시험(STS/SUTS/SITS/VectorCAST) 추적 기대.
#   QM/미상: 기대 없음(안전 무관).
_ASIL_RANK = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}
_TEST_BANDS = ("STS", "SUTS", "SITS", "VectorCAST")


def _asil_missing_bands(asil: str, band_counts: Dict[str, int]) -> List[str]:
    """ASIL 등급과 target의 밴드별 링크 수로 '부족한 기대 시험 밴드'를 반환.

    QM/미상(rank<1)은 기대 없음 → []. C/D는 SUTS·SITS 둘 다 필요(없으면 각각 표기).
    A/B는 시험 밴드 중 하나라도 있으면 충족, 전무면 ['ANY_TEST'].
    """
    rank = _ASIL_RANK.get(asil, -1)
    if rank < 1:
        return []
    missing: List[str] = []
    if rank >= 3:  # ASIL C/D
        if band_counts.get("SUTS", 0) == 0:
            missing.append("SUTS")
        if band_counts.get("SITS", 0) == 0:
            missing.append("SITS")
    else:  # ASIL A/B
        if not any(band_counts.get(b, 0) > 0 for b in _TEST_BANDS):
            missing.append("ANY_TEST")
    return missing


def _unwrap(matrix: Any) -> Dict[str, Any]:
    """`{"matrix": {...}}` 래핑과 top-level 형태를 모두 받아 inner dict 반환."""
    if isinstance(matrix, dict):
        if "rows" in matrix:
            return matrix
        inner = matrix.get("matrix")
        if isinstance(inner, dict):
            return inner
    return matrix if isinstance(matrix, dict) else {}


def _test_related_id(t: Dict[str, Any]) -> str:
    """시험 행(test dict)에서 related_id로 쓸 식별자를 안정적으로 추출.

    우선순위: testcase → subprogram → unit → id. 모두 비면 빈 문자열(스킵).
    """
    for k in ("testcase", "subprogram", "unit", "id"):
        v = str(t.get(k) or "").strip()
        if v:
            return v
    return ""


def _test_confidence(t: Dict[str, Any]) -> str:
    """시험 행의 confidence 도출 — indirect 추적은 indirect, 아니면 원 confidence."""
    if t.get("trace_type") == "indirect":
        return "indirect"
    conf = str(t.get("confidence") or "").strip()
    return conf or "direct"


def build_link_table(matrix: Any) -> Dict[str, Any]:
    """UDS 추적성 매트릭스 → 명시 링크 테이블 + 교차표/커버리지 파생(순수·결정적).

    Args:
        matrix: `generate_uds_traceability_matrix()` 결과(top-level 또는
            `{"matrix": {...}}` 래핑). rows 각 항목은 requirement_id,
            sds_components, source_ids, sts_tests/suts_tests/sits_tests, tests 보유.

    Returns:
        dict:
          - links: 정렬된 [{target_id, related_id, related_type, source, confidence}]
          - bands: 밴드 순서 목록
          - columns: {band: [정렬된 distinct related_id]} — 교차표 열 헤더
          - targets: [정렬된 distinct target_id] — 교차표 행
          - coverage: {by_target, by_band, uncovered_targets}
          - asil_coverage: {by_target(=target→ASIL), by_level, gaps, has_asil} (P5)
          - stats: {target_count, link_count, by_band_link_count, asil_gap_count}
    """
    inner = _unwrap(matrix)
    rows = inner.get("rows") if isinstance(inner, dict) else None
    rows = rows if isinstance(rows, list) else []

    links: List[Dict[str, str]] = []
    seen: set = set()

    def add(target: str, related: Any, band: str, confidence: str) -> None:
        related_s = str(related or "").strip()
        if not target or not related_s:
            return
        rtype = _RELATED_TYPE[band]
        key = (target, related_s, rtype, band)
        if key in seen:
            return
        seen.add(key)
        links.append(
            {
                "target_id": target,
                "related_id": related_s,
                "related_type": rtype,
                "source": band,
                "confidence": confidence or "",
            }
        )

    targets_set: set = set()
    columns: Dict[str, set] = {b: set() for b in BANDS}
    target_asil: Dict[str, str] = {}  # ASIL 결합(P5) — target_id → ASIL(canonical)

    for row in rows:
        if not isinstance(row, dict):
            continue
        target = str(row.get("requirement_id") or "").strip()
        if not target:
            continue
        targets_set.add(target)
        # 요구사항 ASIL(매트릭스가 연결 설계요소 최고로 도출) — 갭 판정/표면화용.
        _ra = str(row.get("asil") or "").strip().upper()
        if _ra:
            target_asil[target] = _ra

        # T1: SRS → SDS (설계 컴포넌트)
        for comp in row.get("sds_components") or []:
            add(target, comp, "SDS", "direct")
            c = str(comp or "").strip()
            if c:
                columns["SDS"].add(c)
        # T2: SDS → UDS (단위 함수)
        for src in row.get("source_ids") or []:
            add(target, src, "UDS", "direct")
            s = str(src or "").strip()
            if s:
                columns["UDS"].add(s)
        # T3~T5: 시험 레벨 (STS/SUTS/SITS)
        for band in ("STS", "SUTS", "SITS"):
            for t in row.get(f"{band.lower()}_tests") or []:
                if not isinstance(t, dict):
                    continue
                rid = _test_related_id(t)
                if not rid:
                    continue
                add(target, rid, band, _test_confidence(t))
                columns[band].add(rid)
        # VectorCAST 실행추적 — 통합 tests 목록에서 source로 식별
        for t in row.get("tests") or []:
            if isinstance(t, dict) and t.get("source") == "VectorCAST":
                rid = _test_related_id(t)
                if not rid:
                    continue
                add(target, rid, "VectorCAST", _test_confidence(t) or "fuzzy")
                columns["VectorCAST"].add(rid)

    # ── 결정적 정렬(P2): 전 필드 기준 — 같은 입력 → 동일 순서 ──
    links.sort(
        key=lambda lk: (
            lk["target_id"],
            lk["source"],
            lk["related_type"],
            lk["related_id"],
            lk["confidence"],
        )
    )

    targets = sorted(targets_set)

    # ── 커버리지 집계 (부동소수 % — hiMA 정수나눗셈 절삭 버그 회피) ──
    by_target: Dict[str, Dict[str, int]] = {}
    for tgt in targets:
        by_target[tgt] = {b: 0 for b in BANDS}
        by_target[tgt]["total"] = 0
    band_link_count: Dict[str, int] = {b: 0 for b in BANDS}
    for lk in links:
        tgt = lk["target_id"]
        band = lk["source"]
        if tgt in by_target:
            by_target[tgt][band] += 1
            by_target[tgt]["total"] += 1
        band_link_count[band] += 1

    total_targets = len(targets)
    by_band: Dict[str, Dict[str, Any]] = {}
    for b in BANDS:
        linked = sum(1 for tgt in targets if by_target[tgt][b] > 0)
        by_band[b] = {
            "linked_targets": linked,
            "total_targets": total_targets,
            # 부동소수 — 절삭 없이 정확한 비율(소수 1자리 반올림)
            "pct": round(linked * 100.0 / total_targets, 1) if total_targets else 0.0,
        }

    # 추적 0건 target(hiMA 0카운트 핑크밴드 대응) — 정방향 추적성 공백.
    uncovered_targets = [tgt for tgt in targets if by_target[tgt]["total"] == 0]

    # ── ASIL 결합(P5) — 등급별 추적성 충족/갭 (hiMA 비노출 차별점) ──
    # 안전등급(A+) 요구사항이 등급에 걸맞은 시험 추적을 갖췄는지 판정.
    asil_by_level: Dict[str, Dict[str, int]] = {}
    asil_gaps: List[Dict[str, Any]] = []
    for tgt in targets:
        a = target_asil.get(tgt, "")
        key = a if a in _ASIL_RANK else "UNKNOWN"
        lvl = asil_by_level.setdefault(key, {"targets": 0, "test_covered": 0, "gap": 0})
        lvl["targets"] += 1
        bt = by_target[tgt]
        if any(bt.get(b, 0) > 0 for b in _TEST_BANDS):
            lvl["test_covered"] += 1
        missing = _asil_missing_bands(a, bt)
        if missing:
            lvl["gap"] += 1
            asil_gaps.append({"target_id": tgt, "asil": a, "missing": missing})
    # 결정적 정렬 — ASIL 높은 순, 동률은 target_id 사전순.
    asil_gaps.sort(key=lambda g: (-_ASIL_RANK.get(g["asil"], -1), g["target_id"]))

    return {
        "links": links,
        "bands": list(BANDS),
        "columns": {b: sorted(columns[b]) for b in BANDS},
        "targets": targets,
        "coverage": {
            "by_target": by_target,
            "by_band": by_band,
            "uncovered_targets": uncovered_targets,
        },
        # ASIL 결합(P5) — 요구사항별 ASIL + 등급별 충족/갭. 데이터 없으면 has_asil=False.
        # unknown_count: ASIL 미부여(연결 설계요소에 등급 없음) 요구사항 — 갭과 별개로
        #   표면화(reviewer WARN-B: 안전등급 미할당 자체가 감사 finding이라 silent 금지).
        "asil_coverage": {
            "by_target": target_asil,
            "by_level": asil_by_level,
            "gaps": asil_gaps,
            "has_asil": bool(target_asil),
            # 미상은 'ASIL 데이터가 있는데 일부 요구사항만 등급 없음'일 때만 유의미.
            # ASIL 데이터 자체가 전무하면(has_asil False) 0 — '미할당'으로 오인 방지.
            "unknown_count": (
                asil_by_level.get("UNKNOWN", {}).get("targets", 0) if target_asil else 0
            ),
        },
        "stats": {
            "target_count": total_targets,
            "link_count": len(links),
            "by_band_link_count": band_link_count,
            "asil_gap_count": len(asil_gaps),
        },
    }
