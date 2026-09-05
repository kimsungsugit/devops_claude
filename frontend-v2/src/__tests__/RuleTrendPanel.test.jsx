/**
 * RuleTrendPanel — 분류 배지·null 분절 스파크·insufficient_data·fix 예시 흐름·correlation_note.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockTrend;
let mockFix;
let mockWindow;

vi.mock('../api.js', () => ({
  post: vi.fn((url) => {
    const u = String(url);
    if (u.includes('prqa-rule-trend')) return Promise.resolve(mockTrend);
    if (u.includes('rule-window-changes')) return Promise.resolve(mockWindow);
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
    expect(screen.getByText(/규칙 미적용 구간은 선이 끊겨/)).toBeInTheDocument();
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

  it('미해소 규칙(persistent)은 files_latest+observed_range로 증거 확장을 연다', async () => {
    mockTrend = {
      ...TREND,
      observed_range: { from_build: 122, to_build: 125 },
      rules: [
        { rule: 'Rule-9.9', counts: [4, null, 4], latest: 4, first: 4, net: 0, classification: 'persistent',
          files_latest: [{ path: 'APP/bar.c', count: 4 }], decreased_files: [] },
      ],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-9.9');
    await userEvent.click(screen.getByText('▸ 증거'));
    expect(screen.getByText(/미해소 위반 파일/)).toBeInTheDocument();
    expect(screen.getByText(/구간 증거 보기/)).toBeInTheDocument();
  });

  it('미해소여도 observed_range 없으면(단일 관측) 확장 버튼 없음', async () => {
    mockTrend = {
      ...TREND,
      observed_range: { from_build: 125, to_build: 125 },
      rules: [
        { rule: 'Rule-9.9', counts: [4], latest: 4, first: 4, net: 0, classification: 'persistent',
          files_latest: [{ path: 'APP/bar.c', count: 4 }], decreased_files: [] },
      ],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-9.9');
    expect(screen.queryByText(/▸ (예시|증거)/)).toBeNull();  // from==to — 구간 증거 성립 불가
  });

  it('감소 근거는 실제 감소 구간(decrease_window)을 표기하고 분류와 무관하게 열린다', async () => {
    // 총량이 늘어난(increasing) 규칙 안에도 줄어든 파일이 있으면 예시 근거가 된다.
    mockTrend = {
      ...TREND,
      rules: [{
        rule: 'Rule-2.2', counts: [35, null, 38], latest: 38, first: 35, net: 3,
        classification: 'increasing', files_latest: [], increased_files: [],
        decrease_window: { from_build: 122, to_build: 123, delta: -1, file_delta: -2 },
        decreased_files: [{ path: 'APP/foo.c', from_build: 122, to_build: 123, delta: -2, count_from: 14, count_to: 12 }],
      }],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-2.2');
    await userEvent.click(screen.getByText('▸ 예시'));
    // 규칙 총계(-1)가 아니라 아래 목록의 합(-2) — 표시와 목록이 어긋나지 않아야 한다.
    expect(screen.getByText(/감소 구간 #122→#123 \(파일 합 -2건\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('작성 예시 생성'));
    // 관측 구간(#122→#125)이 아니라 감소가 실제 일어난 구간으로 요청해야 diff가 잡힌다.
    expect(post).toHaveBeenCalledWith('/api/summary/rule-fix-example', expect.objectContaining({
      rule: 'Rule-2.2', file: 'APP/foo.c', from_build: 122, to_build: 123,
    }));
  });

  it('신규 발생 규칙은 발생 구간(increase_window) 증거를 연다', async () => {
    mockTrend = {
      ...TREND,
      observed_range: { from_build: 122, to_build: 125 },
      rules: [{
        rule: 'C-INT-003', counts: [null, null, 2], latest: 2, first: 0, net: 2,
        classification: 'new_recent', files_latest: [{ path: 'APP/bar.c', count: 2 }],
        decreased_files: [],
        increase_window: { from_build: 124, to_build: 125, delta: 2, file_delta: 2 },
        increased_files: [{ path: 'APP/bar.c', from_build: 124, to_build: 125, delta: 2, count_from: 0, count_to: 2 }],
      }],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('C-INT-003');
    await userEvent.click(screen.getByText('▸ 발생'));
    expect(screen.getByText(/발생 구간 #124→#125 \(파일 합 \+2건\)/)).toBeInTheDocument();
    expect(screen.getByText(/구간 증거 보기 \(#124→#125\)/)).toBeInTheDocument();
  });

  it('cross_module(RCMA) 엔트리는 배지 + 사유만 — 예시 생성 버튼 없음(LLM 호출 0)', async () => {
    mockTrend = {
      ...TREND,
      cross_module_keys: ['RCMA'],
      rules: [{
        rule: 'Rule-8.6', counts: [105, null, 99], latest: 99, first: 105, net: -6,
        classification: 'decreasing', files_latest: [{ path: 'RCMA', count: 99, scope: 'cross_module' }],
        decrease_window: { from_build: 122, to_build: 123, delta: -5 },
        decreased_files: [{ path: 'RCMA', from_build: 122, to_build: 123, delta: -5, scope: 'cross_module' }],
      }],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-8.6');
    await userEvent.click(screen.getByText('▸ 예시'));
    expect(screen.getAllByText('모듈 간 분석').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/특정 파일에 귀속되지 않아/).length).toBeGreaterThan(0);
    expect(screen.queryByText('작성 예시 생성')).toBeNull();  // 파일 실체 없음 — 호출 자체 차단
  });

  it('cross_module이어도 구간 변경 파일은 볼 수 있다(파일이 없는 것 ≠ 볼 게 없는 것)', async () => {
    mockTrend = {
      ...TREND,
      rules: [{
        rule: 'Rule-8.6', counts: [105, null, 99], latest: 99, first: 105, net: -6,
        classification: 'decreasing', files_latest: [{ path: 'RCMA', count: 99, scope: 'cross_module' }],
        decrease_window: { from_build: 122, to_build: 123, delta: -5, file_delta: -5 },
        decreased_files: [{ path: 'RCMA', from_build: 122, to_build: 123, delta: -5, scope: 'cross_module' }],
      }],
    };
    mockWindow = {
      ok: true, available: true, attribution: 'observational',
      note: '모듈 간 분석(RCMA) 위반은 특정 파일에 귀속되지 않습니다. 아래는 같은 빌드 구간에서 변경된 파일이며, 위반 증감의 원인이라는 판정이 아닙니다(관측 ≠ 인과).',
      totals: { changed: 26, headers: 10, decl_touched_files: 9, typedef_touched_files: 3 },
      omitted: 0,
      changed_files: [
        { path: 'APP/Ap_MotorCtrl_it_PDS.h', change_kind: 'modified', lines_added: 17, lines_removed: 70, decl_touched: 29, typedef_touched: 4, is_header: true },
        { path: 'APP/Ap_MotorCtrl_PDS.c', change_kind: 'modified', lines_added: 236, lines_removed: 1879, decl_touched: 25, typedef_touched: 2, is_header: false },
      ],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-8.6');
    await userEvent.click(screen.getByText('▸ 예시'));
    await userEvent.click(screen.getByText(/이 구간 변경 파일 보기 \(#122→#123\)/));
    expect(await screen.findByText('APP/Ap_MotorCtrl_it_PDS.h')).toBeInTheDocument();
    expect(screen.getByText(/변경 26개 · 헤더 10 · 선언 변경 9/)).toBeInTheDocument();
    // 인과로 격상하지 않는다는 고지가 항상 붙어야 한다.
    expect(screen.getByText(/관측 ≠ 인과/)).toBeInTheDocument();
  });

  it('규칙셋 도중 확장은 "#N부터 규칙 적용" + 각주로 구분(신규 발생 오독 방지)', async () => {
    mockTrend = {
      ...TREND,
      ruleset_sizes: [104, null, 242],
      rules: [{
        ...TREND.rules[0], rule: 'C-POS-012', applied_from_build: 125, scope_narrowed: true,
      }],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('C-POS-012');
    expect(screen.getByText('#125부터 규칙 적용')).toBeInTheDocument();
    expect(screen.getByText(/규칙셋이 104→242개로 변동/)).toBeInTheDocument();
  });

  it('규칙 설명(RCFInfo)이 있으면 규칙 아래 한 줄로 렌더, 없으면 생략', async () => {
    mockTrend = {
      ...TREND,
      rules: [
        { ...TREND.rules[0], description: { title: 'A project shall not contain unreachable code', enabled: true, group: 'M3CM' } },
        TREND.rules[1], // description 없음 — 설명 줄 자체가 생략(빈 값 위장 금지)
      ],
    };
    render(<RuleTrendPanel {...PROPS} />);
    await screen.findByText('Rule-1.1');
    expect(screen.getByText('A project shall not contain unreachable code')).toBeInTheDocument();
    // 설명 없는 규칙의 셀에는 규칙 ID만 존재(설명 줄 미렌더)
    expect(screen.getByText('Rule-2.2').textContent).toBe('Rule-2.2');
  });
});
