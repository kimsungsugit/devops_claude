/**
 * SummaryAiInsightPanel — AI 인사이트 패널(probe 자동표시/생성/중단/재생성/폴백 배지).
 * X9: post(probe — signal 불요) + api(생성 — AbortSignal) 헬퍼만 사용.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockProbe;       // post('/api/summary/ai-insight', {probe:true}) 응답
let mockGenerate;    // api() 생성 응답(함수면 (url, opts) 호출)

vi.mock('../api.js', () => ({
  post: vi.fn(() => Promise.resolve(mockProbe)),
  api: vi.fn((url, opts) => (typeof mockGenerate === 'function' ? mockGenerate(url, opts) : Promise.resolve(mockGenerate))),
}));

const { default: SummaryAiInsightPanel } = await import('../components/sections/SummaryAiInsightPanel.jsx');
const { api, post } = await import('../api.js');

const DONE = {
  ok: true, available: true, cached: false, prompt_version: 1, model: 'gemini-2.5-flash',
  ai_enriched: true, generated_at: '2026-07-24T23:00:00', rcr_available: true, delta_available: true,
  input: { latest_build: 125, baseline_build: 124, excerpt_files: ['APP/src/foo.c'] },
  deterministic: { headline: { violations: 562 }, top_rules: [{ rule: 'Rule-8.6', count: 120 }], delta_summary: {}, complexity_offenders: [], gaps: [] },
  sections: {
    rules: { ai_enriched: true, reason: null, items: [{ rule: 'Rule-8.6', title: '경계 검사', why_risky: '오버플로', typical_cause: '캐스팅 남용', fix_guide: '명시 검사' }] },
    mistakes: { ai_enriched: true, reason: null, items: [{ pattern: '매직 넘버', rules: ['Rule-8.6'], files: ['APP/src/foo.c'], diagnosis: '진단', improvement: '개선', evidence_quote: 'int x = 42;', confidence: 'medium' }] },
    roles: { ai_enriched: true, reason: null, developer: [{ priority: 1, action: '규칙 정리', basis: '위반 120건' }], tester: [{ priority: 1, action: 'TC 보강', basis: '미달 2건' }] },
  },
};

const PROPS = { jobUrl: 'http://jenkins/job/KJ/', cacheRoot: '.devops_pro_cache', scmId: 'kj', trace: { has_data: true, uncovered: 8 } };

describe('SummaryAiInsightPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockProbe = { ok: true, available: true, cached: false };
    mockGenerate = DONE;
  });

  it('probe 캐시 히트 → 생성 버튼 없이 자동 표시(LLM 0회) + 캐시 푸터', async () => {
    mockProbe = { ...DONE, cached: true };
    render(<SummaryAiInsightPanel {...PROPS} />);
    expect((await screen.findAllByText(/Rule-8\.6/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/캐시됨/)).toBeInTheDocument();
    expect(screen.queryByText('AI 인사이트 생성')).toBeNull();
    expect(api).not.toHaveBeenCalled(); // 생성 호출 없음
    expect(post).toHaveBeenCalledWith('/api/summary/ai-insight', expect.objectContaining({ probe: true }));
  });

  it('probe 미스 → 버튼만; 클릭 시 생성(force 없음) 후 섹션 렌더', async () => {
    const user = userEvent.setup();
    render(<SummaryAiInsightPanel {...PROPS} />);
    const btn = await screen.findByText('AI 인사이트 생성');
    await user.click(btn);
    expect(await screen.findByText('매직 넘버')).toBeInTheDocument();
    expect(screen.getByText('int x = 42;')).toBeInTheDocument();       // evidence 코드 인용
    expect(screen.getByText(/모델 gemini-2\.5-flash/)).toBeInTheDocument();
    const [, opts] = api.mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.force).toBeUndefined();
    expect(body.trace_summary).toEqual(PROPS.trace);                    // 추적성 스냅샷 동반
    expect(opts.signal).toBeInstanceOf(AbortSignal);                    // 중단 지원
  });

  it('재생성 버튼 → force:true로 재호출', async () => {
    const user = userEvent.setup();
    mockProbe = { ...DONE, cached: true };
    render(<SummaryAiInsightPanel {...PROPS} />);
    await screen.findAllByText(/Rule-8\.6/);
    await user.click(screen.getByText('재생성'));
    await screen.findByText(/새로 생성/);
    const [, opts] = api.mock.calls[0];
    expect(JSON.parse(opts.body).force).toBe(true);
  });

  it('ai_enriched:false 섹션은 "결정론 분석(AI 미사용)" 배지 + 사유 표기', async () => {
    mockGenerate = {
      ...DONE, ai_enriched: false, model: null,
      sections: {
        rules: { ai_enriched: false, reason: 'llm_unavailable', items: [] },
        mistakes: { ai_enriched: false, reason: 'llm_error', items: [] },
        roles: { ai_enriched: false, reason: 'llm_unavailable', developer: [{ priority: 1, action: '결정론 권고', basis: '위반 562' }], tester: [{ priority: 1, action: 'TC', basis: '갭 2' }] },
      },
    };
    const user = userEvent.setup();
    render(<SummaryAiInsightPanel {...PROPS} />);
    await user.click(await screen.findByText('AI 인사이트 생성'));
    const badges = await screen.findAllByText('결정론 분석(AI 미사용)');
    expect(badges).toHaveLength(3);
    expect(screen.getByText(/AI 호출 실패/)).toBeInTheDocument();       // llm_error 매핑
    expect(screen.getByText(/결정론 권고/)).toBeInTheDocument();        // roles 폴백 표시("1. …")
    expect(screen.getByText(/AI 미사용\(결정론\)/)).toBeInTheDocument(); // 푸터 정직
  });

  it('생성 중 중단 → 요청 abort + 버튼 복원(에러 미표시)', async () => {
    const user = userEvent.setup();
    mockGenerate = (url, opts) => new Promise((resolve, reject) => {
      opts.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    });
    render(<SummaryAiInsightPanel {...PROPS} />);
    await user.click(await screen.findByText('AI 인사이트 생성'));
    expect(screen.getByText(/생성 중/)).toBeInTheDocument();
    await user.click(screen.getByText('중단'));
    expect(await screen.findByText('AI 인사이트 생성')).toBeInTheDocument(); // idle 복원
    expect(screen.queryByText(/AI 인사이트 오류/)).toBeNull();
  });

  it('생성 실패(비-abort)는 오류 표면화', async () => {
    const user = userEvent.setup();
    mockGenerate = () => Promise.reject(new Error('HTTP 500'));
    render(<SummaryAiInsightPanel {...PROPS} />);
    await user.click(await screen.findByText('AI 인사이트 생성'));
    expect(await screen.findByText(/AI 인사이트 오류: .*HTTP 500/)).toBeInTheDocument();
  });

  it('rcr_available:false 경고 노출(위반 기반 인사이트 제한 정직 고지)', async () => {
    const user = userEvent.setup();
    mockGenerate = { ...DONE, rcr_available: false };
    render(<SummaryAiInsightPanel {...PROPS} />);
    await user.click(await screen.findByText('AI 인사이트 생성'));
    expect(await screen.findByText(/RCR\) 리포트가 없어 위반 기반 인사이트가 제한/)).toBeInTheDocument();
  });

  it('testing 섹션(v4) — topic 배지·심볼·근거 렌더 + 아키 cycle 배지 맵', async () => {
    const user = userEvent.setup();
    mockGenerate = {
      ...DONE,
      sections: {
        ...DONE.sections,
        architecture: {
          ai_enriched: true, reason: null,
          items: [{ topic: 'cycle', finding: '파일 순환 관측', suggestion: '인터페이스 분리 검토', functions: [], files: ['APP/a.c'], basis: 'size 2', confidence: 'medium' }],
        },
        testing: {
          ai_enriched: true, reason: null,
          items: [{ topic: 'design_gap', finding: '시험 링크 없음', suggestion: 'SUTS 케이스 설계', symbols: ['REQ-9'], basis: 'UDS 1건', confidence: 'medium' }],
        },
      },
    };
    render(<SummaryAiInsightPanel {...PROPS} />);
    await user.click(await screen.findByText('AI 인사이트 생성'));
    expect(await screen.findByText('설계-시험 갭')).toBeInTheDocument();     // testing topic 배지
    expect(screen.getByText(/대상: REQ-9/)).toBeInTheDocument();
    expect(screen.getByText('순환 의존')).toBeInTheDocument();               // arch cycle 배지 한국어 맵
  });
});
