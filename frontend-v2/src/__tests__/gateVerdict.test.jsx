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
  verdictOf, trendVerdictOf, metricVerdictOf, gatedCountOf, REASON_TEXT, TONE_COLOR, VERDICT_CODES,
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
      expect(src).not.toMatch(/function\s+(verdictOf|gateLabel|metricVerdictOf|trendVerdictOf)\s*\(/);
      expect(src).not.toMatch(/(const|let|var)\s+(verdictOf|gateLabel|metricVerdictOf|trendVerdictOf)\s*=/);
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
