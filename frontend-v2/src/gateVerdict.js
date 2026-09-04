/**
 * 게이트 판정 — 화면 셋(생성 현황 보드 · 품질 게이트 목록/지표 · 점수 추세)의 **단일 출처**.
 *
 * (R31 Q-6) 같은 run 을 세 표면이 다르게 그렸다:
 *   - 보드는 `gate_reason === 'no_gated_metric'` → **판정 불가**(warning)
 *   - 게이트 화면 목록은 `summary.gate_pass` 만 봐서 **FAIL**
 *   - 추세는 `/trend` 에 사유가 없어 **빨간 막대**(캡션은 "회색=판정 없음" 을 약속)
 *   - advisor 는 요약 부재를 0점·False 로 접어 "게이트 미통과" 문장
 * 판정을 두 곳에 복제하면 이렇게 갈린다. 여기 하나만 두고 전부 import 한다 —
 * `__tests__/gateVerdict.test.jsx` 가 컴포넌트 안의 로컬 `verdictOf`/`gateLabel` 정의를 막는다.
 *
 * 규약: **서버 판정 그대로. null 을 통과로 접지 않는다.** 프론트는 `score >= 70` 같은
 * 재계산을 하지 않는다(옛 `QualityDashboard` 가 그렇게 통과를 지어냈다).
 */

/** 게이트 사유 코드 → 사람이 읽는 문장. 없는 코드는 코드 그대로. */
export const REASON_TEXT = {
  no_gated_metric: '검사 항목이 0개 — 판정이 성립하지 않는다',
};

/** `gated_metric_count` — 목록/추세는 top-level 로, 상세는 `scores` 행으로 온다. 둘 다 없으면 null(미기록). */
export function gatedCountOf(run) {
  if (!run) return null;
  if (run.gated_metric_count != null) {
    const n = Number(run.gated_metric_count);
    return Number.isFinite(n) ? n : null;
  }
  const row = Array.isArray(run.scores)
    ? run.scores.find((s) => s?.metric_name === 'gated_metric_count') : null;
  if (!row || row.value == null) return null;
  const n = Number(row.value);
  return Number.isFinite(n) ? n : null;
}

/**
 * run 하나의 판정.
 *
 * 순서가 곧 오독 방지 순서다: 검사 규모 0(판정 불가)이 `gate_pass` 보다 **먼저**다 —
 * 백엔드가 `all([])`=True 로 검사 0건을 PASS 로 기록하던 결함의 화면 쪽 방어.
 * `run` 이 `{ summary: { gate_pass }, gate_reason, gated_metric_count | scores }` 만 갖춰도 된다
 * (추세 항목은 `gate_pass` 가 top-level 이라 호출부가 감싼다).
 */
export function verdictOf(run) {
  if (!run) return { code: 'ABSENT', tone: 'neutral', label: '미생성' };
  const gated = gatedCountOf(run);
  if (run.gate_reason === 'no_gated_metric' || gated === 0) {
    return { code: 'INDETERMINATE', tone: 'warning', label: '판정 불가' };
  }
  const gp = run.summary?.gate_pass;
  if (gp === true) return { code: 'PASS', tone: 'success', label: 'PASS' };
  if (gp === false) return { code: 'FAIL', tone: 'danger', label: 'FAIL' };
  return { code: 'NONE', tone: 'neutral', label: '판정 없음' };
}

/** 소비처는 `label`(표시용 한국어)이 아니라 `code` 로 분기한다 — 라벨을 고치면 KPI 분모가 조용히 바뀐다(리뷰 W1). */
export const VERDICT_CODES = Object.freeze(['ABSENT', 'INDETERMINATE', 'PASS', 'FAIL', 'NONE']);

/** 추세 항목(`/api/quality/trend`)은 `gate_pass` 가 top-level 이다 — 같은 판정기로 보낸다. */
export function trendVerdictOf(item) {
  if (!item) return verdictOf(null);
  return verdictOf({
    summary: { gate_pass: item.gate_pass ?? null },
    gate_reason: item.gate_reason ?? null,
    gated_metric_count: item.gated_metric_count ?? null,
  });
}

/** 지표 한 행의 판정(run 판정과 다른 단위). `null` 은 비게이트/미기록 = 판정 없음. */
export function metricVerdictOf(gatePass) {
  if (gatePass === true) return { code: 'PASS', tone: 'success', label: 'PASS' };
  if (gatePass === false) return { code: 'FAIL', tone: 'danger', label: 'FAIL' };
  return { code: 'NONE', tone: 'neutral', label: '판정 없음' };
}

/** 판정 톤 → 막대/배지 색. 색을 세 화면이 각자 고르지 않게 한 곳에 둔다. */
export const TONE_COLOR = {
  success: 'var(--color-success)',
  danger: 'var(--color-danger)',
  warning: 'var(--color-warning)',
  neutral: 'var(--text-muted)',
  info: 'var(--color-info)',
};
