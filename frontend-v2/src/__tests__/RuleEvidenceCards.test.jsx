/** UnresolvedEvidenceCard — 구간 증거 3상태(변경/무변경/실패 reason) + note 상시. */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;      // rule-unresolved-evidence 응답
let mockDefResp;   // rule-definition 응답 (함수면 body 기반 분기 — probe/생성 구분)

vi.mock('../api.js', () => ({
  post: vi.fn((url, body) => {
    const u = String(url);
    if (u.includes('rule-definition')) {
      const r = typeof mockDefResp === 'function' ? mockDefResp(body) : mockDefResp;
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(r);
    }
    return mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp);
  }),
}));

import { RuleDefinitionCard, UnresolvedEvidenceCard } from '../components/sections/RuleEvidenceCards.jsx';

const PROPS = {
  jobUrl: 'http://j/', cacheRoot: '', rule: 'Rule-1.1',
  file: { path: 'APP/foo.c', count: 6 }, fromBuild: 122, toBuild: 125,
};

const NOTE = '파일 변경/무변경과 위반 잔존은 같은 빌드 구간의 관측이며 인과 판정이 아닙니다.';

describe('UnresolvedEvidenceCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('파일 변경 증거 — 배지 + counts + diff + note', async () => {
    mockResp = {
      ok: true, available: true, file_changed: true,
      counts: { from: 6, to: 6 }, diff: { text: '-int x = 42;\n+int x = X_INIT;', truncated: false },
      note: NOTE,
    };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText('파일 변경됨 — 위반 유지')).toBeInTheDocument();
    expect(screen.getByText(/위반 6 → 6건/)).toBeInTheDocument();
    expect(screen.getByText(/구간 변경 diff/)).toBeInTheDocument();
    expect(screen.getByText(`⚖ ${NOTE}`)).toBeInTheDocument();
  });

  it('파일 무변경 — 유효 증거 배지(실패 아님), diff 없음, counts 결측은 —', async () => {
    mockResp = {
      ok: true, available: true, file_changed: false,
      counts: { from: null, to: 6 }, counts_reason: 'no_rcr', diff: null, note: NOTE,
    };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText('파일 무변경 — 위반 잔존')).toBeInTheDocument();
    expect(screen.getByText(/위반 — → 6건/)).toBeInTheDocument();   // null은 '—'(0 위장 금지)
    expect(screen.getByText(/일부 빌드 RCR 없음/)).toBeInTheDocument();
    expect(screen.queryByText(/구간 변경 diff/)).toBeNull();
  });

  it('available:false reason 한글 매핑', async () => {
    mockResp = { ok: true, available: false, reason: 'file_ambiguous_in_snapshot' };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/동일 이름 파일이 여러 개/)).toBeInTheDocument();
  });

  it('요청 실패 — 오류 노출(침묵 금지)', async () => {
    mockResp = new Error('500');
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/구간 증거 조회 오류/)).toBeInTheDocument();
  });
});

const ATTR_NOTE = '함수 목록은 이 구간에 실제로 바뀐 함수이며, 규칙 위반이 그 함수에서 났다는 판정이 아닙니다.';

describe('FunctionAttribution (구간 증거 카드 안 함수 단위 귀속)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const withAttr = (attribution, file_rule_deltas = []) => ({
    ok: true, available: true, file_changed: true,
    counts: { from: 0, to: 4 }, diff: { text: '+void f(void) {}', truncated: false },
    note: NOTE, attribution, file_rule_deltas,
  });

  it('신규/변경 함수와 메트릭 변화를 표시하고, 파일의 규칙 delta를 함께 보여준다', async () => {
    mockResp = withAttr(
      {
        available: true,
        totals: { added: 1, modified: 1, removed: 0 },
        omitted: 0,
        note: ATTR_NOTE,
        functions: [
          { function: 's_Build()', change: 'added',
            metrics: [{ metric: 'V_G', label: 'v(G)', base: null, cur: '2', verdict: 'Pass' }],
            band_crossings: [] },
          { function: 's_Process()', change: 'modified',
            metrics: [{ metric: 'PATH', label: 'PATH', base: '3', cur: '11', verdict: null }],
            band_crossings: [] },
        ],
      },
      [{ rule: 'Rule-2.2', base: 0, cur: 4, delta: 4 }],
    );
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/s_Build\(\)/)).toBeInTheDocument();
    expect(screen.getByText(/s_Process\(\)/)).toBeInTheDocument();
    // 신규 함수는 base가 없으므로 값만 — '0→2'로 쓰면 허위 변화가 된다.
    expect(screen.getByText('v(G) 2')).toBeInTheDocument();
    expect(screen.getByText('PATH 3→11')).toBeInTheDocument();
    expect(screen.getByText(/신규 1 · 변경 1 · 삭제 0/)).toBeInTheDocument();
    expect(screen.getByText('Rule-2.2')).toBeInTheDocument();
    expect(screen.getByText('+4')).toBeInTheDocument();
    expect(screen.getByText(`⚖ ${ATTR_NOTE}`)).toBeInTheDocument();
  });

  it('밴드 교차는 등급 변화로 별도 표기(값 변화와 구분)', async () => {
    mockResp = withAttr({
      available: true, totals: { added: 0, modified: 1, removed: 0 }, omitted: 0, note: ATTR_NOTE,
      functions: [{
        function: 's_RearSet()', change: 'modified',
        metrics: [{ metric: 'V_G', label: 'v(G)', base: '9', cur: '11', verdict: 'Conditional' }],
        band_crossings: [{
          metric: 'V_G', label: 'v(G)', name: 'Cyclomatic Complexity', st_id: 'ST201',
          base: '9', cur: '11', from_verdict: 'Pass', to_verdict: 'Conditional',
          from_band: '1 ~ 10', to_band: '11 ~ 20',
        }],
      }],
    });
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/Cyclomatic Complexity 9→11/)).toBeInTheDocument();
    expect(screen.getByText(/판정 Pass\(1 ~ 10\)/)).toBeInTheDocument();
    expect(screen.getByText(/Conditional\(11 ~ 20\)/)).toBeInTheDocument();
  });

  it('HMR 부재는 사유를 한글로 알린다 — 빈 목록을 변화 없음으로 위장하지 않는다', async () => {
    mockResp = withAttr({ available: false, reason: 'no_hmr' });
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/HIS 메트릭 리포트\(HMR\)가 없는 빌드/)).toBeInTheDocument();
  });

  it('함수 변화 0건은 그 사실을 명시(빈 화면 금지)', async () => {
    mockResp = withAttr({
      available: true, totals: { added: 0, modified: 0, removed: 0 },
      omitted: 0, functions: [], note: ATTR_NOTE,
    });
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/함수 메트릭에는 변화가 없습니다/)).toBeInTheDocument();
  });

  it('한쪽 빌드에만 파일이 있으면 "전부 신규"를 사실로 읽지 않도록 경고', async () => {
    mockResp = withAttr({
      available: true, totals: { added: 3, modified: 0, removed: 0 }, omitted: 0,
      partial: 'base_missing', note: ATTR_NOTE,
      functions: [{ function: 'f1()', change: 'added', metrics: [], band_crossings: [] }],
    });
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/모든 함수가 신규로/)).toBeInTheDocument();
    expect(screen.getByText(/분석 대상에서 빠진 것인지는 구분되지 않습니다/)).toBeInTheDocument();
  });

  it('양쪽 다 있으면 partial 경고를 띄우지 않는다', async () => {
    mockResp = withAttr({
      available: true, totals: { added: 0, modified: 1, removed: 0 }, omitted: 0, note: ATTR_NOTE,
      functions: [{ function: 'f()', change: 'modified',
        metrics: [{ metric: 'V_G', label: 'v(G)', base: '2', cur: '3', verdict: 'Pass' }],
        band_crossings: [] }],
    });
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText('v(G) 2→3')).toBeInTheDocument();
    expect(screen.queryByText(/모든 함수가 신규로/)).toBeNull();
  });

  it('attribution 부재(구 응답)여도 카드는 그대로 동작한다', async () => {
    mockResp = {
      ok: true, available: true, file_changed: true, counts: { from: 6, to: 6 },
      diff: { text: '-a\n+b', truncated: false }, note: NOTE,
    };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText('파일 변경됨 — 위반 유지')).toBeInTheDocument();
    expect(screen.queryByText(/이 구간에 바뀐 함수/)).toBeNull();
  });
});

const DEF_PROPS = { jobUrl: 'http://j/', cacheRoot: '', rule: 'Rule-1.1' };
const DEF_OK = {
  ok: true, available: true, rule: 'Rule-1.1',
  description: { title: 'official desc' },
  note: '이 초안은 팀 검토·승인 전에는 코딩 룰이 아닙니다.',
  definition: {
    intent: '규칙 의도 요약', rationale: '근거', avoid_pattern: 'int x = 42;',
    comply_pattern: 'int x = X_INIT;', exceptions: ['부트 코드 검토 필요'],
    evidence_basis: '위반 6건', confidence: 'medium',
  },
  ai_enriched: true, model: 'gemini-3.5-flash-lite',
};

describe('RuleDefinitionCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDefResp = null;
  });

  it('probe 미스 → 증거 요약 + 생성 버튼, 클릭 → 초안 렌더(LLM은 클릭 시에만)', async () => {
    mockDefResp = (body) => (body?.probe
      ? { ok: true, available: true, cached: false, evidence_used: { fix_diffs: 1, unresolved_excerpts: 2 } }
      : DEF_OK);
    render(<RuleDefinitionCard {...DEF_PROPS} />);
    expect(await screen.findByText(/해소 diff 1건 · 미해소 발췌 2건/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('팀 룰 초안 생성'));
    expect(await screen.findByText(/규칙 의도 요약/)).toBeInTheDocument();
    expect(screen.getByText('int x = X_INIT;')).toBeInTheDocument();
    expect(screen.getByText(/코딩 룰이 아닙니다/)).toBeInTheDocument();  // note 상시
  });

  it('probe 캐시 히트 → 클릭 없이 자동 표시 + Markdown 복사', async () => {
    mockDefResp = { ...DEF_OK, cached: true };
    const writeText = vi.fn().mockResolvedValue();
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<RuleDefinitionCard {...DEF_PROPS} />);
    expect(await screen.findByText(/규칙 의도 요약/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Markdown 복사'));
    expect(writeText).toHaveBeenCalledTimes(1);
    const md = writeText.mock.calls[0][0];
    expect(md).toContain('## Rule-1.1 — 팀 코딩 룰 초안');
    expect(md).toContain('official desc');
    expect(md).toContain('int x = X_INIT;');
  });

  it('no_code_evidence → 일반론 방지 안내(생성 버튼 없음)', async () => {
    mockDefResp = { ok: true, available: false, reason: 'no_code_evidence' };
    render(<RuleDefinitionCard {...DEF_PROPS} />);
    expect(await screen.findByText(/일반론 방지/)).toBeInTheDocument();
    expect(screen.queryByText('팀 룰 초안 생성')).toBeNull();
  });

  it('AI 미생성(enrich_reason) — 결정론 폴백 안내', async () => {
    mockDefResp = (body) => (body?.probe
      ? { ok: true, available: true, cached: false, evidence_used: { fix_diffs: 1, unresolved_excerpts: 0 } }
      : { ...DEF_OK, definition: null, ai_enriched: false, enrich_reason: 'llm_unavailable' });
    render(<RuleDefinitionCard {...DEF_PROPS} />);
    await userEvent.click(await screen.findByText('팀 룰 초안 생성'));
    expect(await screen.findByText(/AI 초안 미생성\(llm_unavailable\)/)).toBeInTheDocument();
  });
});
