/**
 * BuildDeltaDrilldown — 빌드간 PRQA 위반 delta 드릴다운 패널.
 * available:false reason 한국어 매핑 / in_changed_set 배지 / signals 문장 / 정직성(±0, 부재 미위장).
 */
import { render, screen, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockDelta;

vi.mock('../api.js', () => ({
  post: vi.fn((url) => {
    if (String(url).includes('prqa-delta')) {
      return mockDelta instanceof Error ? Promise.reject(mockDelta) : Promise.resolve(mockDelta);
    }
    return Promise.resolve({});
  }),
}));

const { default: BuildDeltaDrilldown } = await import('../components/sections/BuildDeltaDrilldown.jsx');
const { post } = await import('../api.js');

const OK_DELTA = {
  ok: true, available: true, reason: null,
  build_number: 125, baseline_build_number: 124, baseline_auto: true,
  basis: 'worstrules_matrix',
  totals: { cur: 562, base: 552, delta: 10 },
  rules: {
    new: [{ rule: 'Rule-9.9', count: 4 }],
    resolved: [{ rule: 'Rule-2.2', count_was: 3 }],
    increased: [{ rule: 'Rule-8.6', base: 10, cur: 14, delta: 4 }],
    decreased: [{ rule: 'Rule-12.1', base: 9, cur: 6, delta: -3 }],
    residual_delta: 2,
  },
  files: [
    { file: 'foo.c', path: 'APP/src/foo.c', base: 12, cur: 17, delta: 5, rules: [{ rule: 'Rule-8.6', base: 2, cur: 5, delta: 3 }], in_changed_set: true },
    { file: 'bar.c', path: 'APP/src/bar.c', base: 5, cur: 4, delta: -1, rules: [], in_changed_set: false },
  ],
  files_omitted: 0,
  changed_files: { available: true, source: 'change_log', count: 2 },
  signals: [{ type: 'changed_file_violation_increase', file: 'APP/src/foo.c', delta: 5, rules: ['Rule-8.6'] }],
  truncation: { cur_files_truncated_to: null, base_files_truncated_to: null },
  cache: { cur_hit: true, base_hit: true },
};

const PROPS = { jobUrl: 'http://jenkins/job/KJ/', cacheRoot: '.devops_pro_cache', scmId: 'kj', buildNumber: 125 };

describe('BuildDeltaDrilldown', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDelta = OK_DELTA;
  });

  it('규칙 delta(신규/해소/증감)와 총계, 비교 쌍을 렌더한다', async () => {
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText('Rule-9.9 +4')).toBeInTheDocument();
    expect(screen.getByText('Rule-2.2 −3')).toBeInTheDocument();
    expect(screen.getByText(/Rule-8\.6: 10→14/)).toBeInTheDocument();
    expect(screen.getByText(/#124\(직전\) → #125/)).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith('/api/jenkins/prqa-delta', {
      job_url: PROPS.jobUrl, cache_root: PROPS.cacheRoot, build_number: 125, scm_id: 'kj',
    });
  });

  it('변경 파일 신호 문장 + in_changed_set 배지를 표시한다', async () => {
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText(/변경한 파일 1개의 위반이 늘었습니다/)).toBeInTheDocument();
    const fooRow = screen.getByTitle('APP/src/foo.c').closest('tr');
    expect(within(fooRow).getByText('변경파일')).toBeInTheDocument();
    const barRow = screen.getByTitle('APP/src/bar.c').closest('tr');
    expect(within(barRow).queryByText('변경파일')).toBeNull();
  });

  it('residual delta 각주(규칙 미귀속 몫)를 표시한다', async () => {
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText(/규칙 미귀속\(기타 비상위\) 위반 변화/)).toBeInTheDocument();
  });

  it('change-log 부재(in_changed_set 필드 없음)면 변경 컬럼 자체를 만들지 않는다(false 위장 금지)', async () => {
    mockDelta = {
      ...OK_DELTA,
      changed_files: { available: false, reason: 'scm_id_not_provided' },
      signals: [],
      files: OK_DELTA.files.map(({ in_changed_set: _drop, ...f }) => f),
    };
    render(<BuildDeltaDrilldown {...PROPS} />);
    await screen.findByText('Rule-9.9 +4');
    expect(screen.queryByText('변경')).toBeNull();       // 헤더 없음
    expect(screen.queryByText('변경파일')).toBeNull();   // 배지 없음
  });

  it('W-B: 규칙 미귀속(residual) 몫은 파일 행에 "기타 ±N"으로 명시(under-report 방지)', async () => {
    mockDelta = {
      ...OK_DELTA,
      signals: [],
      files: [
        // 총계 +5인데 규칙 delta 합은 +3 → 잔차 +2를 '기타'로 표기해야 한다.
        { file: 'foo.c', path: 'APP/src/foo.c', base: 12, cur: 17, delta: 5, rules: [{ rule: 'Rule-8.6', base: 2, cur: 5, delta: 3 }], in_changed_set: false },
        // 규칙 목록이 비었는데 delta ≠ 0 (residual-only 파일).
        { file: 'res.c', path: 'APP/src/res.c', base: 3, cur: 7, delta: 4, rules: [], in_changed_set: false },
      ],
    };
    render(<BuildDeltaDrilldown {...PROPS} />);
    const fooRow = (await screen.findByTitle('APP/src/foo.c')).closest('tr');
    expect(within(fooRow).getByText(/Rule-8\.6 \+3, 기타 \+2/)).toBeInTheDocument();
    const resRow = screen.getByTitle('APP/src/res.c').closest('tr');
    expect(within(resRow).getByText('기타 +4')).toBeInTheDocument();
  });

  it('W1: 변경 규칙 4개+ 파일도 표시(top3)+기타 == Δ — 4위 규칙 침묵 소멸 금지', async () => {
    mockDelta = {
      ...OK_DELTA,
      signals: [],
      files: [
        // Δ=10 = A+4, B+3, C+2, D+1 — top3 표시 후 D(+1)는 '기타 +1'로 흡수돼야 한다.
        {
          file: 'many.c', path: 'APP/src/many.c', base: 0, cur: 10, delta: 10,
          rules: [
            { rule: 'Rule-A', base: 0, cur: 4, delta: 4 },
            { rule: 'Rule-B', base: 0, cur: 3, delta: 3 },
            { rule: 'Rule-C', base: 0, cur: 2, delta: 2 },
            { rule: 'Rule-D', base: 0, cur: 1, delta: 1 },
          ],
          in_changed_set: false,
        },
      ],
    };
    render(<BuildDeltaDrilldown {...PROPS} />);
    const row = (await screen.findByTitle('APP/src/many.c')).closest('tr');
    expect(within(row).getByText(/Rule-A \+4, Rule-B \+3, Rule-C \+2, 기타 \+1/)).toBeInTheDocument();
  });

  it('available:false reason을 한국어로 매핑해 표시한다', async () => {
    mockDelta = { ok: true, available: false, reason: 'no_rcr_baseline', build_number: 125, baseline_build_number: 124 };
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText(/기준 빌드에 PRQA\(RCR\) 리포트가 없어/)).toBeInTheDocument();
  });

  it('미지의 reason도 침묵하지 않고 원문 노출', async () => {
    mockDelta = { ok: true, available: false, reason: 'weird_new_reason' };
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText(/위반 delta를 계산할 수 없습니다 \(weird_new_reason\)/)).toBeInTheDocument();
  });

  it('조회 실패는 오류로 표시(silent 금지)', async () => {
    mockDelta = new Error('HTTP 500');
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText(/위반 delta 조회 오류: .*HTTP 500/)).toBeInTheDocument();
  });

  it('절단 경고(truncation)를 표시한다', async () => {
    mockDelta = { ...OK_DELTA, truncation: { cur_files_truncated_to: 60, base_files_truncated_to: null } };
    render(<BuildDeltaDrilldown {...PROPS} />);
    expect(await screen.findByText(/delta가 불완전할 수 있습니다/)).toBeInTheDocument();
  });
});
