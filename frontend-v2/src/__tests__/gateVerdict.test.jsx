/**
 * gateVerdict — 판정 **단일 출처** 계약(R31 Q-6).
 *
 * A. 행동: 검사 규모 0 은 `gate_pass` 가 무엇이든 "판정 불가", null 은 통과가 아니다.
 * B. 구조: 컴포넌트가 로컬 `verdictOf`/`gateLabel` 을 다시 정의하지 않는다 — 판정을 두 곳에
 *    두면 보드는 "판정 불가", 목록은 "FAIL", 추세는 빨간 막대로 갈린다(실제로 그랬다).
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';
import {
  verdictOf, trendVerdictOf, metricVerdictOf, gatedCountOf, gateDefinitionOf, reasonTextOf,
  REASON_TEXT, TONE_COLOR, VERDICT_CODES,
  reviewVerdictOf, reviewErrorText, reviewFreshnessOf, latestReviewOf, hashReasonText, basisReasonText, HASH_REASON_TEXT,
  REVIEW_DECISIONS, REVIEW_DECISION_LABEL, REVIEW_ERROR_TEXT, REVIEW_VERDICT_CODES,
} from '../gateVerdict.js';

describe('verdictOf — 서버 판정 그대로, 검사 0건이 먼저', () => {
  it('run 이 없으면 미생성', () => {
    expect(verdictOf(null)).toEqual({ code: 'ABSENT', tone: 'neutral', label: '미생성' });
  });

  it('gate_pass true/false/null', () => {
    expect(verdictOf({ summary: { gate_pass: true } }).label).toBe('PASS');
    expect(verdictOf({ summary: { gate_pass: false } }).label).toBe('FAIL');
    expect(verdictOf({ summary: { gate_pass: null } }).label).toBe('판정 없음');
    expect(verdictOf({ summary: null }).label).toBe('판정 없음');
  });

  it('gate_reason=no_gated_metric 이면 gate_pass=true 여도 판정 불가', () => {
    const v = verdictOf({ summary: { gate_pass: true }, gate_reason: 'no_gated_metric' });
    expect(v).toEqual({ code: 'INDETERMINATE', tone: 'warning', label: '판정 불가' });
  });

  it('top-level gated_metric_count=0 이면 사유가 없어도 판정 불가 (목록/추세 형태)', () => {
    expect(verdictOf({ summary: { gate_pass: false }, gated_metric_count: 0 }).label).toBe('판정 불가');
  });

  it('scores 행의 gated_metric_count=0 도 잡는다 (상세 형태)', () => {
    const run = { summary: { gate_pass: false }, scores: [{ metric_name: 'gated_metric_count', value: 0 }] };
    expect(verdictOf(run).label).toBe('판정 불가');
  });

  // (R32 W3) 병합 판정의 사이드카 축이 실패하면 요약 gate_pass 는 7축 True 인데 병합은 False 다 — PASS 로 그리지 않는다.
  it('gate_definition=report_generation_failed 이면 gate_pass=true 여도 판정 불가', () => {
    const v = verdictOf({ summary: { gate_pass: true }, gate_definition: 'report_generation_failed', gated_metric_count: 7 });
    expect(v.code).toBe('INDETERMINATE');
    expect(reasonTextOf({ gate_definition: 'report_generation_failed' })).toMatch(/생성 실패/);
    expect(verdictOf({ summary: { gate_pass: true }, gate_definition: 'report_unreadable' }).code).toBe('INDETERMINATE');
  });

  it('scores 행의 gate_definition 마커도 잡고, 정상 정의는 판정을 바꾸지 않는다', () => {
    const run = { summary: { gate_pass: true }, scores: [{ metric_name: 'gate_definition:report_generation_failed', value: 1 }] };
    expect(verdictOf(run).code).toBe('INDETERMINATE');
    expect(gateDefinitionOf(run)).toBe('report_generation_failed');
    expect(verdictOf({ summary: { gate_pass: true }, gate_definition: 'quick_confidence_and_report' }).code).toBe('PASS');
    expect(gateDefinitionOf({})).toBeNull();
  });

  it('추세 항목의 gate_definition 도 같은 판정기로 간다', () => {
    expect(trendVerdictOf({ gate_pass: true, gate_definition: 'report_generation_failed' }).code).toBe('INDETERMINATE');
  });

  it('gated_metric_count 미기록(null)은 0 이 아니다 — 판정은 gate_pass 를 따른다', () => {
    expect(verdictOf({ summary: { gate_pass: true }, gated_metric_count: null }).label).toBe('PASS');
    expect(gatedCountOf({ gated_metric_count: null, scores: [] })).toBeNull();
    expect(gatedCountOf({ gated_metric_count: 'x' })).toBeNull();
    expect(gatedCountOf({ scores: [{ metric_name: 'gated_metric_count', value: 7 }] })).toBe(7);
  });

  it('점수로 통과를 지어내지 않는다', () => {
    expect(verdictOf({ summary: { overall_score: 99, gate_pass: null } }).label).toBe('판정 없음');
  });

  it('모든 판정에 code 가 있고 code 집합은 고정이다 (소비처는 code 로 분기)', () => {
    const cases = [null, { summary: { gate_pass: true } }, { summary: { gate_pass: false } },
      { summary: null }, { gate_reason: 'no_gated_metric' }];
    const codes = cases.map((c) => verdictOf(c).code);
    expect(codes).toEqual(['ABSENT', 'PASS', 'FAIL', 'NONE', 'INDETERMINATE']);
    for (const c of codes) expect(VERDICT_CODES).toContain(c);
    expect(metricVerdictOf(null).code).toBe('NONE');
  });
});

describe('trendVerdictOf / metricVerdictOf', () => {
  it('추세 항목(top-level gate_pass)을 같은 판정기로 보낸다', () => {
    expect(trendVerdictOf({ gate_pass: false, gate_reason: 'no_gated_metric', gated_metric_count: 0 }).label)
      .toBe('판정 불가');
    expect(trendVerdictOf({ gate_pass: false }).label).toBe('FAIL');
    expect(trendVerdictOf({ gate_pass: null }).label).toBe('판정 없음');
    expect(trendVerdictOf(null).label).toBe('미생성');
  });

  it('지표 행 판정 — null 은 판정 없음', () => {
    expect(metricVerdictOf(true).label).toBe('PASS');
    expect(metricVerdictOf(false).label).toBe('FAIL');
    expect(metricVerdictOf(null).label).toBe('판정 없음');
  });

  it('모든 톤에 색이 있다', () => {
    for (const t of ['success', 'danger', 'warning', 'neutral']) expect(TONE_COLOR[t]).toBeTruthy();
    expect(REASON_TEXT.no_gated_metric).toMatch(/0개/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// B. 구조 — 판정 복제 금지
// ─────────────────────────────────────────────────────────────────────────────

const SRC = path.resolve(process.cwd(), 'src');
const COMPONENTS = [
  'components/sections/DocGenStatusBoard.jsx',
  'components/sections/QualityGateSection.jsx',
];

/** 주석은 옛 결함을 **설명**하느라 판정식을 인용한다 — 코드만 잰다. */
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

describe('판정 로직은 gateVerdict.js 한 곳에만 있다', () => {
  for (const rel of COMPONENTS) {
    it(`${rel} 는 로컬 판정 함수를 정의하지 않고 gateVerdict 를 import 한다`, () => {
      const file = path.join(SRC, rel);
      expect(fs.existsSync(file)).toBe(true);
      const src = stripComments(fs.readFileSync(file, 'utf-8'));
      expect(src).toMatch(/from\s+'\.\.\/\.\.\/gateVerdict\.js'/);
      // 로컬 정의(함수 선언·화살표 대입) 어느 형태도 안 된다.
      expect(src).not.toMatch(/function\s+(verdictOf|gateLabel|metricVerdictOf|trendVerdictOf|reviewVerdictOf|reviewErrorText|reviewFreshnessOf|reviewDecisionTone)\s*\(/);
      expect(src).not.toMatch(/(const|let|var)\s+(verdictOf|gateLabel|metricVerdictOf|trendVerdictOf|reviewVerdictOf|reviewErrorText|reviewFreshnessOf)\s*=/);
      // (R35) 검토 라벨·어휘도 복제 금지 — 컴포넌트에 '승인됨' 리터럴 매핑이나 decision 문자열 비교가 생기면 걸린다.
      expect(src).not.toMatch(/approved\s*:\s*['"]승인됨/);
      expect(src).not.toMatch(/decision\s*===\s*['"]approved['"]\s*\?/);
      expect(src).not.toMatch(/stale\s*\?\s*['"]/);
      // 소비처는 `code` 로 분기한다 — 라벨 문자열 비교가 남으면 라벨을 고칠 때 KPI 분모가 조용히 바뀐다(리뷰 W1).
      expect(src).not.toMatch(/\.label\s*===\s*['"](PASS|FAIL|판정 불가|판정 없음|미생성)['"]/);
      // 판정식 자체의 복제 — `gate_pass === true ? 'PASS'` 류가 컴포넌트에 다시 생기면 걸린다.
      expect(src).not.toMatch(/gate_pass\s*===\s*true\s*\?\s*['"]PASS/);
      expect(src).not.toMatch(/\?\?\s*\(\s*score\s*>=\s*70\s*\)/);
    });
  }

  it('gateVerdict.js 밖의 src 에 verdictOf 정의가 없다', () => {
    const offenders = [];
    const walk = (dir) => {
      for (const name of fs.readdirSync(dir)) {
        const full = path.join(dir, name);
        if (fs.statSync(full).isDirectory()) {
          if (name === '__tests__' || name === 'node_modules') continue;
          walk(full);
        } else if (/\.(js|jsx)$/.test(name) && !full.endsWith('gateVerdict.js')) {
          const s = stripComments(fs.readFileSync(full, 'utf-8'));
          if (/function\s+verdictOf\s*\(|(const|let|var)\s+verdictOf\s*=/.test(s)) offenders.push(path.relative(SRC, full));
        }
      }
    };
    walk(SRC);
    expect(offenders).toEqual([]);
  });
});


// ─────────────────────────────────────────────────────────────────────────────
// C. (R35) 검토 기록 — 게이트와 다른 축, 같은 규약(서버 값 그대로 · null 은 통과/최신이 아니다)
// ─────────────────────────────────────────────────────────────────────────────

const SHA = 'b'.repeat(64);
const rec = (over = {}) => ({ id: 1, reviewer: 'r1', decision: 'approved', stale: false, version: 1, updated_at: '2026-09-07T01:00:00+00:00', ...over });

describe('reviewVerdictOf — 검토 열 판정', () => {
  it('해시 없는 run 은 상태와 무관하게 검토 잠금이고 사유를 title 에 싣는다', () => {
    expect(reviewVerdictOf({ output_sha256: null }, null).code).toBe('LOCKED');
    expect(reviewVerdictOf({ output_sha256: null }, { reviews: [rec()] }).label).toBe('검토 잠금(해시 없음)');
    expect(reviewVerdictOf({ output_sha256: null, meta: { output_sha256_reason: 'file_missing' } }, null).title).toMatch(/file_missing/);
    expect(reviewVerdictOf({ output_sha256: null }, null).title).toMatch(/구 run/);
    expect(reviewVerdictOf({ output_sha256: SHA }, { hash_unavailable: true, hash_reason: 'no_path' }).title).toMatch(/no_path/);
  });

  it('상태 미조회는 조회 중, 조회 실패는 실패 — 둘 다 미검토가 아니다', () => {
    expect(reviewVerdictOf({ output_sha256: SHA }, undefined).code).toBe('UNKNOWN');
    expect(reviewVerdictOf({ output_sha256: SHA }, undefined, { error: 'down' })).toMatchObject({ code: 'ERROR', tone: 'danger' });
  });

  it('기록 없음은 미검토, 기록은 판정 라벨 + stale 3상태', () => {
    expect(reviewVerdictOf({ output_sha256: SHA }, { reviews: [] })).toMatchObject({ code: 'NONE', label: '미검토' });
    expect(reviewVerdictOf({ output_sha256: SHA }, { reviews: [rec()] })).toMatchObject({ code: 'REVIEWED', tone: 'success', label: '승인됨' });
    expect(reviewVerdictOf({ output_sha256: SHA }, { reviews: [rec({ decision: 'rejected' })] })).toMatchObject({ tone: 'danger', label: '반려' });
    expect(reviewVerdictOf({ output_sha256: SHA }, { reviews: [rec({ decision: 'needs_work' })] })).toMatchObject({ tone: 'warning', label: '보완 필요' });
    expect(reviewVerdictOf({ output_sha256: SHA }, { reviews: [rec({ stale: true })] })).toMatchObject({ code: 'STALE', tone: 'warning', label: '승인됨 · stale' });
    expect(reviewVerdictOf({ output_sha256: SHA }, { reviews: [rec({ stale: null })], current_basis_reason: 'file_missing' }))
      .toMatchObject({ code: 'UNVERIFIED', label: '승인됨 · 최신성 판단 불가' });
  });

  it('판정이 갈리면 대표 1건으로 접지 않고 "판정 갈림" 이며, title 에 검토자 실명은 없다 (리뷰 W2/W7)', () => {
    const st = { reviews: [rec({ id: 1, reviewer: 'old', decision: 'rejected', updated_at: '2026-09-01T00:00:00+00:00' }), rec({ id: 2, reviewer: 'new', updated_at: '2026-09-07T00:00:00+00:00' })] };
    expect(latestReviewOf(st).reviewer).toBe('new');
    const v = reviewVerdictOf({ output_sha256: SHA }, st);
    expect(v).toMatchObject({ code: 'MIXED', tone: 'warning', label: '판정 갈림 2종' });
    expect(v.title).toMatch(/반려 \/ 승인됨|승인됨 \/ 반려/);
    expect(v.title).not.toMatch(/new|old/);
    // 같은 판정 둘이면 갈림이 아니다 — 인원만 title 에.
    const same = { reviews: [rec({ id: 1, reviewer: 'a' }), rec({ id: 2, reviewer: 'b', updated_at: '2026-09-08T00:00:00+00:00' })] };
    const v2 = reviewVerdictOf({ output_sha256: SHA }, same);
    expect(v2.label).toBe('승인됨');
    expect(v2.title).toMatch(/검토 2명/);
    expect(v2.title).not.toMatch(/\ba\b|\bb\b/);
  });

  it('대표 선택은 시각 파싱 기준이다 — 표기가 달라도 뒤집히지 않는다 (리뷰 I1)', () => {
    const st = { reviews: [
      rec({ id: 1, reviewer: 'x', updated_at: '2026-09-07T01:00:00.500000+00:00' }),
      rec({ id: 2, reviewer: 'y', updated_at: '2026-09-07T10:00:00+09:00' }),   // = 01:00:00Z, 더 이르다
    ] };
    expect(latestReviewOf(st).reviewer).toBe('x');
    expect(latestReviewOf({ reviews: [rec({ id: 1, updated_at: null }), rec({ id: 2, updated_at: null })] }).id).toBe(2);
  });

  it('서버 missing 은 별도 코드이고 batch_budget 사유는 다시 재는 길을 말한다 (리뷰 W1/C2)', () => {
    expect(reviewVerdictOf({ output_sha256: SHA }, undefined, { missing: true })).toMatchObject({ code: 'MISSING', tone: 'danger' });
    const v = reviewVerdictOf({ output_sha256: SHA }, { reviews: [rec({ stale: null })], current_basis_reason: 'batch_budget' });
    expect(v.code).toBe('UNVERIFIED');
    expect(v.title).toMatch(/근거 보기/);
  });

  it('코드 집합이 고정돼 있다', () => {
    expect(REVIEW_VERDICT_CODES).toEqual(['LOCKED', 'ERROR', 'MISSING', 'UNKNOWN', 'NONE', 'MIXED', 'STALE', 'UNVERIFIED', 'REVIEWED']);
    expect(REVIEW_DECISIONS).toEqual(['approved', 'rejected', 'needs_work']);
    for (const d of REVIEW_DECISIONS) expect(REVIEW_DECISION_LABEL[d]).toBeTruthy();
  });
});

describe('reviewFreshnessOf / reviewErrorText', () => {
  it('stale 3상태를 접지 않는다', () => {
    expect(reviewFreshnessOf({ stale: true }).code).toBe('STALE');
    expect(reviewFreshnessOf({ stale: false }).code).toBe('FRESH');
    expect(reviewFreshnessOf({ stale: null }).code).toBe('UNVERIFIED');
    expect(reviewFreshnessOf({}).code).toBe('UNVERIFIED');
  });

  it('코드가 있으면 그 문장, 403/401 은 코드 없이도 권한/로그인 문장, 나머지는 서버 message', () => {
    for (const [code, text] of Object.entries(REVIEW_ERROR_TEXT)) {
      expect(reviewErrorText({ code, status: 409 })).toBe(text);
    }
    expect(reviewErrorText({ status: 403, code: 'HTTP_403' })).toBe(REVIEW_ERROR_TEXT.ADMIN_REQUIRED);
    expect(reviewErrorText({ status: 401, code: 'HTTP_401' })).toBe(REVIEW_ERROR_TEXT.AUTH_REQUIRED);
    expect(reviewErrorText({ status: 500, code: 'INTERNAL_ERROR', message: 'kaboom' })).toMatch(/kaboom/);
  });

  it('검토 어휘는 서버 DECISIONS 와 lockstep 이다 (workflow/quality/review.py)', () => {
    const py = fs.readFileSync(path.resolve(process.cwd(), '..', 'workflow', 'quality', 'review.py'), 'utf-8');
    const m = py.match(/^DECISIONS\s*=\s*\(([^)]*)\)/m);
    expect(m).not.toBeNull();
    const server = [...m[1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1]);
    expect([...REVIEW_DECISIONS]).toEqual(server);
  });
});


describe('hashReasonText / basisReasonText — 사유를 문장으로, 경로 계열과 배선 실패를 구별해서 (R36 리뷰 W2)', () => {
  it('배선 실패 4종은 경고 표시가 붙고 경로 계열 5종은 안 붙는다', () => {
    for (const t of ['no_bytes', 'bytes_unreadable', 'bytes_not_bytes', 'empty_bytes']) {
      expect(hashReasonText(t)).toMatch(/⚠/);
    }
    for (const t of ['no_path', 'file_missing', 'not_a_file', 'unreadable', 'invalid_arg']) {
      expect(hashReasonText(t)).not.toMatch(/⚠/);
      expect(hashReasonText(t)).toBeTruthy();
    }
  });

  it('모르는 토큰은 지어내지 않고 그대로, null 은 null', () => {
    expect(hashReasonText('quantum_flux')).toBe('quantum_flux');
    expect(hashReasonText(null)).toBeNull();
    expect(hashReasonText(undefined)).toBeNull();
  });

  it('basisReasonText 는 no_path 를 고장이 아니라 구조로 설명하고 대조 방법을 남긴다', () => {
    expect(basisReasonText('no_path')).toMatch(/사본을 갖고 있지 않아/);
    expect(basisReasonText('no_path')).toMatch(/해시로 직접 대조/);
    expect(basisReasonText('batch_budget')).toMatch(/예산/);
    expect(basisReasonText(null)).toBeNull();
  });

  it('사유 어휘는 서버 recorder 의 토큰을 모두 덮는다 (lockstep)', () => {
    const py = fs.readFileSync(path.resolve(process.cwd(), '..', 'workflow', 'quality', 'recorder.py'), 'utf-8');
    const tokens = new Set();
    for (const m of py.matchAll(/return \{"output_hash_reason": "([a-z_]+)"\}/g)) tokens.add(m[1]);
    for (const m of py.matchAll(/return None, None, "([a-z_]+)"/g)) tokens.add(m[1]);
    expect(tokens.size).toBeGreaterThanOrEqual(7);
    for (const t of tokens) expect(HASH_REASON_TEXT[t], `사유 ${t} 에 문장이 없다`).toBeTruthy();
  });
});
