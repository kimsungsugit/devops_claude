/**
 * derivePipelineNodes — 파이프라인 헬스 노드 상태 도출(순수 함수).
 * ISO 정직성: 증거부재 = 'muted(미확인)' (ok/danger 위장 금지).
 */
import { describe, it, expect } from 'vitest';
import { derivePipelineNodes } from '../pipelineHealth.js';

const TRACE = {
  has_data: true,
  band_counts: { SDS: 43, UDS: 64, STS: 60, SUTS: 58, SITS: 20 },
  asil_gap_count: 0,
};
const PRQA = { project_compliance_index: 91 };
const VCAST = { ut_passed: 100, ut_total: 100, it_passed: 50, it_total: 50 };

function byId(nodes) {
  return Object.fromEntries(nodes.map((n) => [n.id, n]));
}

describe('derivePipelineNodes', () => {
  it('정상 데이터 — 6개 노드 전부 ok', () => {
    const n = byId(derivePipelineNodes({
      trace: TRACE, prqa: PRQA, scmVcast: VCAST, rollup: { cumulative_flag_docs: 0 }, latestViolationsDelta: -3,
    }));
    expect(Object.keys(n)).toHaveLength(6);
    for (const id of ['sds', 'uds', 'static', 'suts', 'sits', 'sts']) expect(n[id].state).toBe('ok');
    expect(n.static.detail).toContain('준수율 91%');
    expect(n.static.detail).toContain('Δ위반 -3');
  });

  it('증거부재는 전부 muted(미확인) — ok/danger 위장 금지', () => {
    const n = byId(derivePipelineNodes({ trace: null, prqa: {}, scmVcast: null, rollup: {}, latestViolationsDelta: null }));
    for (const id of ['sds', 'uds', 'static', 'suts', 'sits', 'sts']) expect(n[id].state).toBe('muted');
    expect(n.sds.detail).toBe('추적성 없음');
    expect(n.suts.detail).toBe('결과 없음');
    expect(n.static.detail).toBe('준수율 미산출');
  });

  it('trace has_data:false는 null과 동일 취급', () => {
    const n = byId(derivePipelineNodes({ trace: { has_data: false }, prqa: {}, scmVcast: null, rollup: {}, latestViolationsDelta: null }));
    expect(n.sds.state).toBe('muted');
    expect(n.sts.state).toBe('muted');
  });

  it('테스트 실패는 danger + 실패 수 표기', () => {
    const n = byId(derivePipelineNodes({
      trace: TRACE, prqa: PRQA, scmVcast: { ut_passed: 95, ut_total: 100, it_passed: 50, it_total: 50 },
      rollup: {}, latestViolationsDelta: null,
    }));
    expect(n.suts.state).toBe('danger');
    expect(n.suts.detail).toBe('실패 5/100');
    expect(n.sits.state).toBe('ok');
  });

  it('ASIL 시험 미달은 STS danger', () => {
    const n = byId(derivePipelineNodes({
      trace: { ...TRACE, asil_gap_count: 2 }, prqa: PRQA, scmVcast: VCAST, rollup: {}, latestViolationsDelta: null,
    }));
    expect(n.sts.state).toBe('danger');
    expect(n.sts.detail).toBe('ASIL 시험 미달 2');
  });

  it('검토 대기(FLAG) 문서는 UDS warn', () => {
    const n = byId(derivePipelineNodes({
      trace: TRACE, prqa: PRQA, scmVcast: VCAST, rollup: { cumulative_flag_docs: 3 }, latestViolationsDelta: null,
    }));
    expect(n.uds.state).toBe('warn');
    expect(n.uds.detail).toBe('검토 대기 3');
  });

  it('준수율 낮음/위반 증가 — danger(<70) 및 warn(delta>0)', () => {
    const low = byId(derivePipelineNodes({ trace: TRACE, prqa: { project_compliance_index: 65 }, scmVcast: VCAST, rollup: {}, latestViolationsDelta: null }));
    expect(low.static.state).toBe('danger');
    const up = byId(derivePipelineNodes({ trace: TRACE, prqa: { project_compliance_index: 95 }, scmVcast: VCAST, rollup: {}, latestViolationsDelta: 10 }));
    expect(up.static.state).toBe('warn');
    expect(up.static.detail).toContain('Δ위반 +10');
  });

  it('I1: 0/0 테스트는 muted + "결과 없음"(통과 0/0 fake-ok 문구 금지)', () => {
    const n = byId(derivePipelineNodes({
      trace: TRACE, prqa: PRQA, scmVcast: { ut_passed: 0, ut_total: 0, it_passed: 50, it_total: 50 },
      rollup: {}, latestViolationsDelta: null,
    }));
    expect(n.suts.state).toBe('muted');
    expect(n.suts.detail).toBe('결과 없음');
  });

  it('I2: 준수율 결측이어도 Δ위반은 노출(위반 급증 침묵 금지)', () => {
    const n = byId(derivePipelineNodes({
      trace: TRACE, prqa: {}, scmVcast: VCAST, rollup: {}, latestViolationsDelta: 50,
    }));
    expect(n.static.state).toBe('muted');
    expect(n.static.detail).toBe('준수율 미산출 · Δ위반 +50');
  });

  it('추적성은 있는데 밴드 0이면 warn(문서 연결 의심 — 미확인과 구분)', () => {
    const n = byId(derivePipelineNodes({
      trace: { has_data: true, band_counts: {}, asil_gap_count: 0 }, prqa: PRQA, scmVcast: VCAST, rollup: {}, latestViolationsDelta: null,
    }));
    expect(n.sds.state).toBe('warn');
    expect(n.sts.state).toBe('warn');
  });
});
