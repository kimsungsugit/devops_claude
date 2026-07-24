/**
 * RuleTrendPanel — 분류 배지·null 분절 스파크·insufficient_data·fix 예시 흐름·correlation_note.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockTrend;
let mockFix;

vi.mock('../api.js', () => ({
  post: vi.fn((url) => {
    const u = String(url);
    if (u.includes('prqa-rule-trend')) return Promise.resolve(mockTrend);
    if (u.includes('rule-fix-example')) {
      return mockFix instanceof Error ? Promise.reject(mockFix) : Promise.resolve(mockFix);
    }
    return Promise.resolve({});
  }),
}));

const { default: RuleTrendPanel } = await import('../components/sections/RuleTrendPanel.jsx');
const { post } = await import('../api.js');

const TREND = {
  ok: true, available: true, reason: null,
  builds: [
    { build_number: 122, analyzed: true }, { build_number: 124, analyzed: false }, { build_number: 125, analyzed: true },
  ],
  builds_skipped: [{ build_number: 124, reason: 'no_rcr' }],
  insufficient_data: false,
  rules: [
    { rule: 'Rule-1.1', counts: [6, null, 2], latest: 2, first: 6, net: -4, classification: 'decreasing',
      files_latest: [{ path: 'APP/foo.c', count: 2 }],
      decreased_files: [{ path: 'APP/foo.c', from_build: 122, to_build: 125, delta: -4 }] },
    { rule: 'Rule-2.2', counts: [4, null, 4], latest: 4, first: 4, net: 0, classification: 'persistent', files_latest: [], decreased_files: [] },
  ],
  rules_omitted: 0,
  residual: { counts: [5, null, 9], note: '' },
  summary: { resolved: 0, decreasing: 1, persistent: 1, increasing: 0, new_recent: 0 },
  cache: { rcr_hits: 2, rcr_misses: 0 },
  scope_note: '분류는 캐시된 빌드 구간 한정 관측',
};

const FIX_OK = {
  ok: true, available: true, reason: null,
  rule: 'Rule-1.1', file: 'APP/foo.c', from_build: 122, to_build: 125,
  evidence: { text: '-int x = 42;\n+int x = X_INIT;', truncated: false, hunks_used: 1, hunks_total: 1 },
  correlation_note: '이 파일의 위반 감소와 아래 변경은 같은 빌드 구간에서 관측된 상관이며, 인과가 검증된 것은 아닙니다.',
  example: { explanation: '매직 넘버를 매크로로', avoid_pattern: 'int x = 42;', compliant_pattern: 'int x = X_INIT;', confidence: 'medium' },
  ai_enriched: true, enrich_reason: null, model: 'gemini-3.5-flash-lite', cached: false,
};

const PROPS = { jobUrl: 'http://jenkins/job/KJ/', cacheRoot: '.devops_pro_cache' };

describe('RuleTrendPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTrend = TREND;
    mockFix = FIX_OK;
  });

  it('분류 배지와 순변화, 관측 요약을 렌더한다', async () => {
    render(<RuleTrendPanel {...PROPS} />);
    expect(await screen.findByText('Rule-1.1')).toBeInTheDocument();
    expect(screen.getAllByText('감소').length).toBeGreaterThan(0);
    expect(screen.getAllByText('지속 발생').length).toBeGreaterThan(0);
    expect(screen.getByText('-4')).toBeInTheDocument();
    expect(screen.getByText(/2개 빌드 관측/)).toBeInTheDocument();
    expect(screen.getByText(/미분석 빌드 자리는 선이 끊겨/)).toBeInTheDocument();
  });

  it('null 자리는 스파크라인이 분절된다(0으로 잇지 않음 — polyline 2세그먼트 아님, 점 2개)', async () => {
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-1.1');
    const svg = screen.getByRole('img', { name: 'Rule-1.1 빌드별 위반 추이' });
    // counts [6, null, 2] → 관측 1개짜리 세그먼트 2개 → polyline 없음, circle 2개.
    expect(svg.querySelectorAll('polyline').length).toBe(0);
    expect(svg.querySelectorAll('circle').length).toBe(2);
  });

  it('insufficient_data면 분류 배지 대신 — 표시', async () => {
    mockTrend = {
      ...TREND, insufficient_data: true,
      rules: [{ rule: 'Rule-1.1', counts: [2], latest: 2, first: 2, net: 0, classification: null, files_latest: [], decreased_files: [] }],
      builds: [{ build_number: 125, analyzed: true }],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-1.1');
    expect(screen.getByText(/관측 부족\(분류 없음\)/)).toBeInTheDocument();
    expect(screen.queryByText('감소')).toBeNull();
  });

  it('감소 규칙 확장 → 예시 생성 → correlation_note 상시 + before/after 코드', async () => {
    const user = userEvent.setup();
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-1.1');
    await user.click(screen.getByText('▸ 예시'));
    expect(screen.getByText(/위반이 줄어든 파일/)).toBeInTheDocument();
    await user.click(screen.getByText('작성 예시 생성'));
    expect(await screen.findByText(/인과가 검증된 것은 아닙니다/)).toBeInTheDocument(); // 상관≠인과 상시
    expect(screen.getByText('위반하지 않는 작성')).toBeInTheDocument();
    expect(screen.getByText('int x = X_INIT;')).toBeInTheDocument();
    expect(screen.getByText(/확신도 medium/)).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith('/api/summary/rule-fix-example', expect.objectContaining({
      rule: 'Rule-1.1', file: 'APP/foo.c', from_build: 122, to_build: 125,
    }));
  });

  it('예시 불가 사유(파일 무변경)를 한국어로 정직 표기', async () => {
    mockFix = { ok: true, available: false, reason: 'file_unchanged_between_builds' };
    const user = userEvent.setup();
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-1.1');
    await user.click(screen.getByText('▸ 예시'));
    await user.click(screen.getByText('작성 예시 생성'));
    expect(await screen.findByText(/파일 내용이 변하지 않았습니다/)).toBeInTheDocument();
  });

  it('AI 미생성이어도 diff 증거는 표시(결정론 폴백)', async () => {
    mockFix = { ...FIX_OK, example: null, ai_enriched: false, enrich_reason: 'llm_unavailable', model: null };
    const user = userEvent.setup();
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-1.1');
    await user.click(screen.getByText('▸ 예시'));
    await user.click(screen.getByText('작성 예시 생성'));
    expect(await screen.findByText(/AI 예시 미생성/)).toBeInTheDocument();
    expect(screen.getByText(/실제 변경 diff 증거/)).toBeInTheDocument();
  });

  it('available:false reason 매핑(RCR 없음)', async () => {
    mockTrend = { ok: true, available: false, reason: 'no_rcr_in_cached_builds' };
    render(<RuleTrendPanel {...PROPS} />);
    expect(await screen.findByText(/PRQA\(RCR\) 리포트가 없습니다/)).toBeInTheDocument();
  });
});
