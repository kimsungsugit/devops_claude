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
  // (R32 W3) 병합 판정의 사이드카 축이 실패한 경우 — 요약의 gate_pass 는 7축만 본 값이라 여기서 갈린다.
  report_generation_failed: '사이드카(.quality_gate.md) 생성 실패 — 병합 판정을 내릴 수 없다',
  report_unreadable: '사이드카(.quality_gate.md)를 읽을 수 없음 — 병합 판정을 내릴 수 없다',
};

/** 병합 판정이 성립하지 않는 게이트 정의 — 요약 `gate_pass` 가 True 여도 판정 불가로 그린다. */
export const INDETERMINATE_DEFINITIONS = Object.freeze(['report_generation_failed', 'report_unreadable']);

/** `gate_definition` — 목록/추세는 top-level 로, 상세는 `gate_definition:<src>` 지표 행으로 온다. 없으면 null. */
export function gateDefinitionOf(run) {
  if (!run) return null;
  if (typeof run.gate_definition === 'string' && run.gate_definition) return run.gate_definition;
  const row = Array.isArray(run.scores)
    ? run.scores.find((s) => String(s?.metric_name || '').startsWith('gate_definition:')) : null;
  if (!row) return null;
  const code = String(row.metric_name).slice('gate_definition:'.length);
  return code || null;
}

/** 판정 불가의 사유 텍스트 — `gate_reason` 이 없으면 게이트 정의에서, 그래도 없으면 검사 0건 문장. */
export function reasonTextOf(run) {
  if (!run) return REASON_TEXT.no_gated_metric;
  if (run.gate_reason && REASON_TEXT[run.gate_reason]) return REASON_TEXT[run.gate_reason];
  const def = gateDefinitionOf(run);
  if (def && INDETERMINATE_DEFINITIONS.includes(def)) return REASON_TEXT[def];
  return REASON_TEXT.no_gated_metric;
}

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
  // (R32 W3) 사이드카 축이 실패/판독 불가면 병합 판정은 False 인데 요약은 7축 True 다 — PASS 로 그리지 않는다.
  const def = gateDefinitionOf(run);
  if (def && INDETERMINATE_DEFINITIONS.includes(def)) {
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
    gate_definition: item.gate_definition ?? null,
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

// ─────────────────────────────────────────────────────────────────────────────
// (R35 C-3) 검토 기록 — 게이트 판정과 **다른 축**이다(검토는 게이트를 바꾸지 않는다, 계획 §4.1).
// 라벨·오류 문구는 여기 한 곳. 컴포넌트는 `code` 로 분기한다.
// ─────────────────────────────────────────────────────────────────────────────

/** 서버 `workflow/quality/review.py::DECISIONS` 의 복제 — `tests/unit/test_review_records.py` 가 lockstep 을 잰다. */
export const REVIEW_DECISIONS = Object.freeze(['approved', 'rejected', 'needs_work']);

export const REVIEW_DECISION_LABEL = Object.freeze({
  approved: '승인됨',
  rejected: '반려',
  needs_work: '보완 필요',
});

const REVIEW_DECISION_TONE = Object.freeze({
  approved: 'success',
  rejected: 'danger',
  needs_work: 'warning',
});

/** 판정 하나의 배지 톤 — 패널 기록 표처럼 톤만 필요한 곳은 판정기에 가짜 state 를 먹이지 말고 이걸 쓴다(리뷰 W6). */
export function reviewDecisionTone(decision) {
  return REVIEW_DECISION_TONE[decision] || 'neutral';
}

/** 검토 쓰기 오류 코드 → 사람이 읽는 문장. 없는 코드는 서버 message 그대로(호출부). */
export const REVIEW_ERROR_TEXT = Object.freeze({
  JWT_REQUIRED: '로그인 토큰이 필요합니다 — X-User 만으로는 검토를 저장할 수 없습니다.',
  AUTH_REQUIRED: '로그인이 필요합니다.',
  ADMIN_REQUIRED: '검토 권한이 없습니다(admin 만 기록할 수 있습니다 — 오류가 아니라 권한 상태입니다).',
  STALE: '산출물이 검토 시점과 다릅니다 — 새로고침 뒤 지금 산출물을 다시 검토하세요.',
  HASH_UNAVAILABLE: '이 run 은 산출물 해시가 없어 검토를 기록할 수 없습니다.',
  VERSION_CONFLICT: '다른 저장이 먼저 반영됐습니다 — 새로고침 뒤 다시 저장하세요.',
  DB_BUSY: '기록 DB 가 잠겨 있습니다 — 잠시 후 다시 시도하세요.',
});

/** 오류 객체(`api.js` 가 던진 `{status, code, message}`) → 문장. 403 은 코드가 없어도 권한 상태다. */
export function reviewErrorText(err) {
  const code = err?.code;
  if (code && REVIEW_ERROR_TEXT[code]) return REVIEW_ERROR_TEXT[code];
  if (err?.status === 403) return REVIEW_ERROR_TEXT.ADMIN_REQUIRED;
  if (err?.status === 401) return REVIEW_ERROR_TEXT.AUTH_REQUIRED;
  return `검토 저장 실패: ${err?.message || err}`;
}

/** 가장 최근 갱신된 기록 — 표시 대표. 없으면 null. 시각은 `Date.parse`(문자열 비교는 표기가 바뀌면 조용히 뒤집힌다 — 리뷰 I1), 같으면 id. */
export function latestReviewOf(state) {
  const list = Array.isArray(state?.reviews) ? state.reviews : [];
  if (!list.length) return null;
  const t = (r) => { const v = Date.parse(String(r?.updated_at || '')); return Number.isFinite(v) ? v : -Infinity; };
  return list.reduce((a, b) => (t(b) > t(a) || (t(b) === t(a) && Number(b?.id) > Number(a?.id)) ? b : a));
}

/** 서로 다른 판정이 섞였는가 — 반려 뒤 승인이 오면 대표 1건만 보여선 반려가 사라진다(리뷰 W2). */
export function reviewDecisionsOf(state) {
  const list = Array.isArray(state?.reviews) ? state.reviews : [];
  return [...new Set(list.map((r) => r?.decision).filter(Boolean))];
}

/**
 * run 하나의 검토 상태 라벨. **서버 값 그대로** — 프론트는 해시를 비교하지 않는다.
 *
 * 순서: 해시 없음(검토 잠금) → 조회 실패 → run 없음(서버 `missing`) → 상태 미조회 → 미검토 → 판정 갈림 → 최근 기록의 판정(+stale).
 * `opts.missing` 은 서버가 "그 run 없다" 고 답한 것 — '조회 중' 으로 남기면 끝난 조회를 안 끝난 것처럼 말한다(리뷰 W1).
 * title 에 검토자 실명을 싣지 않는다 — 목록은 스코프 없는 전체 표면이다(리뷰 W7). 이름은 패널에서.
 * `run.output_sha256` 만으로 잠금을 알 수 있어(목록 응답에 실려 온다) 상태 조회 없이도 첫 분기는 선다.
 * `stale === null` 은 "판단 불가" 이지 최신이 아니다 — false 로 접지 않는다(R34 C2 와 같은 규약).
 */
export function reviewVerdictOf(run, state, opts = {}) {
  const hashless = run ? run.output_sha256 == null : false;
  if (hashless || state?.hash_unavailable === true) {
    const reason = state?.hash_reason || run?.meta?.output_sha256_reason || null;
    return {
      code: 'LOCKED', tone: 'neutral', label: '검토 잠금(해시 없음)',
      title: reason ? `해시 미기록 사유: ${reason}` : '해시 미기록 — 구 run 은 사유가 기록되지 않았습니다',
    };
  }
  if (opts.error) return { code: 'ERROR', tone: 'danger', label: '검토 상태 조회 실패', title: String(opts.error) };
  if (opts.missing) return { code: 'MISSING', tone: 'danger', label: 'run 을 찾을 수 없음', title: '서버에 이 run 의 검토 상태가 없습니다(삭제됐거나 다른 DB)' };
  if (!state) return { code: 'UNKNOWN', tone: 'neutral', label: '조회 중…', title: '검토 상태를 아직 받지 못했습니다' };
  const rec = latestReviewOf(state);
  if (!rec) return { code: 'NONE', tone: 'neutral', label: '미검토', title: '검토 기록이 없습니다' };
  const n = state.reviews.length;
  const who = `검토 ${n}명`;
  const kinds = reviewDecisionsOf(state);
  if (kinds.length > 1) {
    return {
      code: 'MIXED', tone: 'warning', label: `판정 갈림 ${kinds.length}종`,
      title: `${who} — ${kinds.map((k) => REVIEW_DECISION_LABEL[k] || k).join(' / ')}. 근거 보기에서 각 기록을 확인하세요`,
    };
  }
  const decision = REVIEW_DECISION_LABEL[rec.decision] || rec.decision;
  if (rec.stale === true) {
    return {
      code: 'STALE', tone: 'warning', label: `${decision} · stale`,
      title: `${who} — 검토 시점 산출물과 지금 파일이 다릅니다`,
    };
  }
  if (rec.stale == null) {
    const why = state.current_basis_reason === 'batch_budget'
      ? '목록 배치 조회의 재해시 예산을 넘어 파일을 읽지 않았습니다 — 근거 보기를 열면 파일 기준으로 다시 잽니다'
      : (state.current_basis_reason || '파일 기준으로 다시 잴 수 없습니다');
    return {
      code: 'UNVERIFIED', tone: REVIEW_DECISION_TONE[rec.decision] || 'neutral', label: `${decision} · 최신성 판단 불가`,
      title: `${who} — ${why}`,
    };
  }
  return { code: 'REVIEWED', tone: REVIEW_DECISION_TONE[rec.decision] || 'neutral', label: decision, title: who };
}

export const REVIEW_VERDICT_CODES = Object.freeze(['LOCKED', 'ERROR', 'MISSING', 'UNKNOWN', 'NONE', 'MIXED', 'STALE', 'UNVERIFIED', 'REVIEWED']);

/** 기록 하나의 최신성 문장 — `stale` 3상태를 그대로. 컴포넌트가 `null` 을 '최신' 으로 접지 않게 한 곳에 둔다. */
export function reviewFreshnessOf(rec) {
  if (rec?.stale === true) return { code: 'STALE', tone: 'warning', label: 'stale — 지금 파일이 검토 시점과 다릅니다' };
  if (rec?.stale === false) return { code: 'FRESH', tone: 'success', label: '지금 파일과 일치' };
  return { code: 'UNVERIFIED', tone: 'neutral', label: '최신성 판단 불가(파일 기준 재해시 불가)' };
}

/**
 * 해시 미기록 사유(`hash_reason`) → 문장. **경로 계열과 버퍼 계열을 섞지 않는다**(R36 리뷰 W2):
 * 앞 다섯은 "이 문서엔 서버 사본이 없다/못 읽었다"(대개 정상), 뒤 넷은 **기록 배선이 끊긴 것**(버그)이다.
 * 없는 토큰은 그대로 보여 준다 — 모르는 사유를 아는 척하지 않는다.
 */
export const HASH_REASON_TEXT = Object.freeze({
  no_path: '산출물 경로가 기록되지 않은 run 입니다',
  file_missing: '기록된 경로에 파일이 없습니다',
  not_a_file: '기록된 경로가 파일이 아닙니다',
  unreadable: '기록된 경로를 읽지 못했습니다',
  invalid_arg: '전달된 해시 값이 올바르지 않았습니다',
  no_bytes: '⚠ 산출물 바이트가 기록기에 전달되지 않았습니다 — 기록 배선 문제입니다(정상 상태가 아닙니다)',
  bytes_unreadable: '⚠ 산출물 버퍼를 읽지 못했습니다 — 기록 배선 문제입니다',
  bytes_not_bytes: '⚠ 산출물 버퍼가 바이트가 아니었습니다 — 기록 배선 문제입니다',
  empty_bytes: '⚠ 산출물이 0바이트였습니다 — 빈 입력의 해시를 산출물 해시로 남기지 않습니다',
});

/** 사유 토큰 → 문장(모르는 토큰은 토큰 그대로). `null` 은 사유 자체가 미기록(구 run). */
export function hashReasonText(reason) {
  if (!reason) return null;
  return HASH_REASON_TEXT[reason] || String(reason);
}

/**
 * 지금 파일과 대조하지 못한 이유(`current_basis_reason`) → 문장 + **벗어나는 길**.
 * `no_path` 는 고장이 아니라 구조다 — 서버가 산출물 사본을 갖지 않는 문서(BytesIO 응답)라
 * 파일 대조가 성립하지 않는다. 그 사실과, 사용자가 손에 든 파일로 직접 대조하는 방법을 함께 낸다.
 */
export function basisReasonText(reason) {
  if (!reason) return null;
  if (reason === 'no_path') {
    return '서버가 이 산출물의 사본을 갖고 있지 않아 파일 대조가 성립하지 않습니다(내려받은 파일과 아래 해시로 직접 대조하세요)';
  }
  if (reason === 'batch_budget') {
    return '목록 배치 조회의 재해시 예산을 넘어 파일을 읽지 않았습니다 — 이 패널은 파일 기준으로 다시 잽니다';
  }
  return HASH_REASON_TEXT[reason] || String(reason);
}
