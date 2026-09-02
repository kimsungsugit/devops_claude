/**
 * 안전 요구(ASIL A~D) 커버리지 — **판정 단일 출처**.
 *
 * 이 값이 위험한 이유는 두 가지다.
 *
 * 1. **분모 0 을 0% 로 쓰면 안 된다.** ASIL 등급이 붙은 요구가 하나도 없는 프로젝트에서
 *    `covered / max(total, 1)` 은 `0.0%` 를 낸다 — "안전 요구 커버리지 0%" 는 심각한
 *    경보인데 사실은 **잴 대상이 없다**는 뜻이다. 미측정은 `null` 로 내고 화면은 `—` 로
 *    그린다(저장소 규약: 미측정 ≠ 0 ≠ 통과).
 *
 * 2. **미상(UNKNOWN)을 분모에서 뺀 사실을 숨기면 안 된다.** 등급이 없는 요구는 QM 이
 *    아니라 **판단 불가**다(근거 부재를 QM 으로 바꾸면 under-classification). 그래서
 *    분모에서 빼되 `unknown` 으로 함께 돌려준다 — 실측 KJPDS02_PV 는 A 62/62 = 100%
 *    인데 미상이 4건이라, 그 4건을 안 보이면 "안전 요구는 전부 검증됨" 으로 오독된다.
 *
 * ⚠ 두 화면이 각자 세면 같은 문서가 표면에 따라 다른 값을 낸다(저장소가 반복해 겪은 형태).
 *   대시보드 카드(`ResultPanel`, 캐시 읽기전용)와 상세탭(`SrsSdsSection` extraSummary,
 *   라이브)이 **이 함수 하나만** 쓴다. 백엔드 `jenkins.py::_cache_trace_summary` 의
 *   `safety_*` 도 같은 규칙이며, 그쪽이 없는 옛 캐시에서도 화면이 나오도록 여기서
 *   `asil_distribution` 으로부터 직접 파생한다.
 */

/** 안전 관련 등급 — QM(비안전)과 미상(판단 불가)은 제외. */
export const SAFETY_GRADES = ['D', 'C', 'B', 'A'];

/** 미상 버킷의 키 — 백엔드는 'UNKNOWN', 상세탭 파생은 '미상' 을 쓴다. */
export const UNKNOWN_GRADE_KEYS = ['UNKNOWN', '미상'];

const _cell = (v) => ({
  total: Number(v?.total) || 0,
  covered: Number(v?.covered) || 0,
});

/**
 * 등급 분포로부터 안전 요구 커버리지를 파생한다.
 *
 * @param {Object|Array|null} dist  `{grade: {total, covered}}` 또는
 *   `[{grade, total, covered}]` (상세탭 `asilRows` 형태). 둘 다 받는다.
 * @returns {{total:number, covered:number, pct:(number|null), unknown:number, hasData:boolean}}
 *   `pct` 는 분모가 0 이면 **`null`**(미측정) — 절대 0 이 아니다.
 */
export function deriveSafetyCoverage(dist) {
  const map = {};
  if (Array.isArray(dist)) {
    for (const row of dist) {
      if (row && row.grade != null) map[String(row.grade)] = _cell(row);
    }
  } else if (dist && typeof dist === 'object') {
    for (const [k, v] of Object.entries(dist)) map[String(k)] = _cell(v);
  }

  let total = 0;
  let covered = 0;
  for (const g of SAFETY_GRADES) {
    const c = map[g];
    if (!c) continue;
    total += c.total;
    covered += c.covered;
  }
  let unknown = 0;
  for (const k of UNKNOWN_GRADE_KEYS) unknown += map[k]?.total || 0;

  return {
    total,
    covered,
    // 분모 0 = 잴 대상이 없다. 0% 로 접으면 "안전 커버리지 0%" 라는 없는 경보를 만든다.
    pct: total > 0 ? Math.round((covered / total) * 1000) / 10 : null,
    unknown,
    hasData: Object.keys(map).length > 0,
  };
}

/**
 * 화면에 그대로 쓸 수 있는 문구 3종.
 *
 * 라벨/값/주석을 한곳에서 만들어 두 표면이 **같은 말**을 하게 한다.
 * (예전엔 한쪽만 미상 건수를 적어 같은 데이터가 다르게 읽혔다.)
 */
export function safetyCoverageText(sc) {
  if (!sc || !sc.hasData) return null;
  if (sc.pct == null) {
    return {
      value: '—',
      detail: 'ASIL A~D 요구 0건 — 잴 대상이 없다(0% 아님)',
      note: sc.unknown > 0 ? `등급 미상 ${sc.unknown}건` : '',
      unmeasured: true,
    };
  }
  return {
    value: `${sc.pct}%`,
    detail: `안전 요구 ${sc.total}건 중 ${sc.covered}건 추적 확보`,
    // 미상을 분모에서 뺀 사실을 항상 함께 적는다 — 없으면 100% 가 "전부 검증됨" 으로 읽힌다.
    note: sc.unknown > 0 ? `등급 미상 ${sc.unknown}건은 분모 밖(안전 여부 판단 불가)` : '',
    unmeasured: false,
  };
}
