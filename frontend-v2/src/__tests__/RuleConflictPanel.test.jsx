/**
 * RuleConflictPanel — 증거 등급 배지·활성 미확인 경고·대조 결과 자립 각주·지침 생성 흐름.
 *
 * 이 패널이 조용히 거짓말할 수 있는 지점만 고정한다:
 * - 접으면 조회 실패가 화면에서 사라지는 것(problem 슬롯)
 * - 34쌍 중 3건만 보이는 이유를 안 알려줘 "상충이 거의 없다"로 읽히는 것
 * - 규칙 설정을 못 읽었는데 후보를 확정처럼 보여주는 것
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockAdvice;

vi.mock('../api.js', () => ({
  post: vi.fn((url) => {
    if (String(url).includes('rule-conflict-advice')) {
      return mockAdvice instanceof Error ? Promise.reject(mockAdvice) : Promise.resolve(mockAdvice);
    }
    return Promise.resolve({});
  }),
}));

const { default: RuleConflictPanel } = await import('../components/sections/RuleConflictPanel.jsx');
const { post } = await import('../api.js');

const DATA = {
  ok: true, available: true, reason: null, build_number: 125,
  note: '상충 후보는 큐레이션된 규칙 지식과 관측을 결합한 가능성이며, 인과 판정이 아닙니다.',
  table: {
    available: true, reason: null, version: 1, total: 34,
    source_note: 'MISRA-C:2012 기반 큐레이션',
    category_note: 'mandatory=예외 불가',
    skipped_no_violation: 29,
    excluded: [{ id: 'tu-local-static', reason: 'counterpart_inactive', fixing: ['Rule-8.6'], inactive: ['Rule-8.7'] }],
  },
  ruleset: { available: true, enabled_count: 242, source_build: 125, reason: null },
  metrics: { available: true, reason: null, function_count: 822, headroom_threshold: 3 },
  latest_rcr_reason: null,
  conflicts: [
    {
      id: 'cast-cascade', kind: 'fix_induces', tier: 'cooccurrence',
      tier_note: '두 규칙이 같은 파일에서 함께 위반 중입니다',
      ruleset_unknown: false,
      fixing: [{ rule: 'Rule-10.4', title: 'same essential type', count: 26, category: 'required' }],
      risk: [{ rule: 'Rule-10.8', title: 'composite cast', count: 5, category: 'required' }],
      risk_filtered: [],
      evidence: {
        windows: [],
        cooccurrence: [{ file: 'src/IF/ApiIn_LinRxComp_PDS.c', fixing_counts: { 'Rule-10.4': 26 }, risk_counts: { 'Rule-10.8': 5 }, total: 31 }],
        metric_headroom: [],
      },
      metric_axis: { applicable: false, checked: false, reason: null },
      advice: { available: true, reason: null },
      mechanism: '캐스팅이 복합식에 걸린다',
      resolutions: ['단항 피연산자 각각에 캐스팅'],
      deviation_hint: '10.x는 전부 required',
      metric_risk: [], confidence: 'high', refs: ['MISRA-C:2012 Rule 10.x'],
      fixing_violations: 26,
    },
    {
      id: 'single-exit-nesting', kind: 'fix_induces', tier: 'metric_headroom',
      tier_note: '밴드 경계에 붙은 함수가 있습니다', ruleset_unknown: false,
      fixing: [{ rule: 'Rule-15.5', title: 'single exit', count: 3, category: 'advisory' }],
      risk: [{ rule: 'Rule-17.4', title: 'all paths return', count: 0, category: 'mandatory' }],
      risk_filtered: [{ rule: 'Rule-99.9', reason: 'not_in_ruleset' }],
      evidence: {
        windows: [], cooccurrence: [],
        metric_headroom: [{ file: 'src/a.c', function: 'tight()', metric: 'V_G', label: 'v(G)', value: 9, headroom: 2, st_id: 'ST201', band: '1 ~ 10', verdict: 'Pass', next_band: '11 ~ 20', next_verdict: 'Conditional' }],
      },
      metric_axis: { applicable: true, checked: true, reason: null, files_checked: 1, threshold: 3 },
      advice: { available: true, reason: null },
      mechanism: '중첩이 깊어진다', resolutions: [], deviation_hint: '',
      metric_risk: ['LEVEL', 'V_G'], confidence: 'high', refs: [],
      fixing_violations: 3,
    },
  ],
  conflicts_omitted: 0,
  by_rule: { 'Rule-10.4': ['cast-cascade'], 'Rule-15.5': ['single-exit-nesting'] },
  co_resolution: [
    {
      rules: ['C-POS-012', 'Rule-2.2'],
      titles: ['Remove Dead Code', 'A project shall not contain dead code'],
      groups: ['HKCCM', 'M3CM'], cross_ruleset: true,
      files: 4, identical_files: 3, strength: 'mostly_identical',
      overlap_upper_bound: 38, totals: { 'C-POS-012': 44, 'Rule-2.2': 38 },
      sample_files: [{ file: 'src/a.c', 'C-POS-012': 12, 'Rule-2.2': 12 }],
    },
  ],
  co_resolution_note: '파일별 위반 수가 일치한다는 관측이며 같은 코드 줄이라는 증명이 아닙니다.',
  ambiguities: {
    conflict: [{ id: 'cast-cascade', tier: 'cooccurrence', fixing: ['Rule-10.4'], risk: ['Rule-10.8'], categories: ['required'], kind: 'fix_induces', confidence: 'high' }],
    measurement: [
      { kind: 'ruleset_change', from_build: 116, to_build: 120, from_size: 104, to_size: 242, affected_rules: ['C-POS-012'], affected_total: 7, detail: '규칙셋이 바뀐 구간입니다' },
      { kind: 'unattributed', rules: [{ rule: 'Rule-8.6', unattributed: 99, total: 105 }], detail: '파일에 귀속되지 않습니다' },
    ],
    generated: [{ file: 'src/Generated_Code/PP1.c', basis: 'path', violations: 2, rules: ['C-INT-002'] }],
  },
};

const props = { jobUrl: 'http://j/job/X', cacheRoot: '/c' };

beforeEach(() => {
  vi.clearAllMocks();
  mockAdvice = { ok: true, available: true, cached: false, conflict_id: 'cast-cascade', evidence_used: { cooccurrence_excerpts: 2, window_diffs: 0 } };
});

describe('RuleConflictPanel', () => {
  it('상충 표에 증거 등급 배지와 규칙·등급을 보여준다', async () => {
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    expect(screen.getByText('동시 위반')).toBeTruthy();
    expect(screen.getByText('메트릭 여유 없음')).toBeTruthy();
    expect(screen.getByText('Rule-10.4')).toBeTruthy();
    expect(screen.getByText('Rule-10.8')).toBeTruthy();
    // mandatory 는 예외 신청 자체가 불가 — 별표로 구분한다.
    expect(screen.getByTitle('예외(deviation) 신청 불가')).toBeTruthy();
  });

  it('대조 결과가 자립한다 — 표시 건수만 보여주면 "상충이 거의 없다"로 읽힌다', () => {
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    const note = screen.getByText(/지식 테이블 34쌍 대조/);
    expect(note.textContent).toContain('표시 2건');
    expect(note.textContent).toContain('위반이 없어 제외 29건');
    expect(note.textContent).toContain('Rule-8.6→Rule-8.7');
  });

  it('행을 펼치면 메커니즘·실측 증거·해소 방향이 나온다', async () => {
    const user = userEvent.setup();
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    await user.click(screen.getAllByRole('button', { name: /보기/ })[0]);
    expect(screen.getByText(/캐스팅이 복합식에 걸린다/)).toBeTruthy();
    expect(screen.getByText(/ApiIn_LinRxComp_PDS.c/)).toBeTruthy();
    expect(screen.getByText(/단항 피연산자 각각에 캐스팅/)).toBeTruthy();
  });

  it('메트릭 여유 경고에 남은 거리와 밴드 교차를 명시한다', async () => {
    const user = userEvent.setup();
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    await user.click(screen.getAllByRole('button', { name: /보기/ })[1]);
    // '경계에 정확히 붙음'이 아니라 **남은 거리**를 보여준다 — 실제 수정은 1단이 아니다.
    expect(screen.getByText(/tight\(\).*v\(G\) 9/)).toBeTruthy();
    expect(screen.getByText(/여유 2단/)).toBeTruthy();
    expect(screen.getByText(/Conditional/)).toBeTruthy();
    // 규칙셋에 없어 걸러진 상대는 감추지 않는다.
    expect(screen.getByText(/규칙셋에 없어 제외: Rule-99.9/)).toBeTruthy();
  });

  it('메트릭 축을 못 봤으면 "여유 있음"이 아니라 사유를 낸다', async () => {
    const user = userEvent.setup();
    const noHmr = {
      ...DATA,
      metrics: { available: false, reason: 'no_hmr', function_count: null, headroom_threshold: 3 },
      conflicts: [{
        ...DATA.conflicts[1],
        evidence: { windows: [], cooccurrence: [], metric_headroom: [] },
        metric_axis: { applicable: true, checked: false, reason: 'no_hmr' },
      }],
    };
    render(<RuleConflictPanel {...props} data={noHmr} defaultOpen />);
    // 패널 상단 배너 — 모든 행을 펼쳐야만 알 수 있으면 안 된다.
    expect(screen.getByText(/HIS 메트릭\(HMR\)을 읽지 못했습니다/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /보기/ }));
    expect(screen.getByText(/확인하지 못했습니다.*HIS 메트릭 리포트\(HMR\)가 없습니다/)).toBeTruthy();
  });

  it('메트릭 축을 봤고 여유가 있으면 그렇게 말한다(빈 화면 금지)', async () => {
    const user = userEvent.setup();
    const roomy = {
      ...DATA,
      conflicts: [{
        ...DATA.conflicts[1],
        evidence: { windows: [], cooccurrence: [], metric_headroom: [] },
        metric_axis: { applicable: true, checked: true, reason: null, files_checked: 4, threshold: 3 },
      }],
    };
    render(<RuleConflictPanel {...props} data={roomy} defaultOpen />);
    await user.click(screen.getByRole('button', { name: /보기/ }));
    expect(screen.getByText(/4개 파일을 확인했고.*여유가 3단 이하인 함수는 없습니다/)).toBeTruthy();
  });

  it('위반이 전부 미귀속이면 버튼을 내기 전에 원리적 불가를 알린다', async () => {
    const user = userEvent.setup();
    const crossOnly = {
      ...DATA,
      conflicts: [{
        ...DATA.conflicts[0],
        evidence: { windows: [], cooccurrence: [], metric_headroom: [] },
        advice: { available: false, reason: 'cross_module_only', unattributed: 99, total: 99 },
      }],
    };
    render(<RuleConflictPanel {...props} data={crossOnly} defaultOpen />);
    await user.click(screen.getByRole('button', { name: /보기/ }));
    expect(screen.getByText(/원리적으로 불가능합니다\(스냅샷 누락이 아닙니다\)/)).toBeTruthy();
    expect(screen.getByText(/위반 99\/99건이 미귀속/)).toBeTruthy();
    // 누를 수 없는 버튼을 내지 않고, 확인 요청도 보내지 않는다.
    expect(screen.queryByRole('button', { name: '지침 생성' })).toBeNull();
    expect(post).not.toHaveBeenCalledWith('/api/summary/rule-conflict-advice', expect.anything());
  });

  it('조회 실패는 접혀 있어도 헤더에 남는다(problem 슬롯)', () => {
    render(<RuleConflictPanel {...props} data={null} error="500 boom" />);
    expect(screen.getByText(/조회 실패 — 500 boom/)).toBeTruthy();
    // 문제가 있는 패널은 접기 버튼 자체가 없다(사유가 본문에만 있으면 접힘=정상과 구분 불가).
    expect(screen.queryByRole('button', { name: /펼치기|접기/ })).toBeNull();
  });

  it('규칙 설정을 못 읽은 빌드는 확정처럼 보여주지 않는다', () => {
    const unknown = {
      ...DATA,
      ruleset: { available: false, enabled_count: null, source_build: null, reason: 'no_rcfinfo' },
    };
    render(<RuleConflictPanel {...props} data={unknown} defaultOpen />);
    expect(screen.getByText(/규칙 활성 미확인/)).toBeTruthy();
    expect(screen.getByText(/상대 규칙이 실제로 검사되는지 확인하지 못했습니다/)).toBeTruthy();
  });

  it('상충 0건이면 테이블 대조 사실과 함께 알린다', () => {
    render(<RuleConflictPanel {...props} data={{ ...DATA, conflicts: [], by_rule: {} }} defaultOpen />);
    expect(screen.getByText(/지식 테이블에 등재된 상충 관계에 해당하는 것이 없습니다/)).toBeTruthy();
  });

  it('함께 해소될 수 있는 규칙을 겹침 상한·근거와 함께 보여준다', () => {
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    expect(screen.getByText(/함께 해소될 수 있는 규칙/)).toBeTruthy();
    expect(screen.getByText(/규칙셋 교차 HKCCM \/ M3CM/)).toBeTruthy();
    expect(screen.getByText(/공존 4파일 중/)).toBeTruthy();
    // 겹침은 '상한'이지 확정 중복분이 아님을 note 로 상시 고지한다.
    expect(screen.getByText(/같은 코드 줄이라는 증명이 아닙니다/)).toBeTruthy();
  });

  it('예방적 지침(상대 규칙 미발생)임을 근거 성격으로 밝힌다', async () => {
    const user = userEvent.setup();
    const preventive = {
      ...DATA,
      conflicts: [{
        ...DATA.conflicts[0],
        evidence: { windows: [], cooccurrence: [], metric_headroom: [] },
        advice: { available: true, reason: null, basis: 'fixing_only' },
        risk: [{ rule: 'Rule-10.8', title: 'composite cast', count: 0, category: 'required' }],
        fixing_files: [{ file: 'src/a.c', count: 7 }],
      }],
    };
    render(<RuleConflictPanel {...props} data={preventive} defaultOpen />);
    await user.click(screen.getByRole('button', { name: /보기/ }));
    expect(screen.getByText(/예방적 — 상대 규칙 아직 미발생/)).toBeTruthy();
    // 막지 않는다 — 고칠 코드가 실재하므로 지침을 만들 수 있다.
    await waitFor(() => expect(screen.getByRole('button', { name: '지침 생성' })).toBeTruthy());
  });

  it('애매한 지점 3종을 각 섹션으로 보여준다', () => {
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    expect(screen.getByText(/#116→#120에서 규칙 104→242개/)).toBeTruthy();
    expect(screen.getByText(/Rule-8.6 99\/105건/)).toBeTruthy();
    expect(screen.getByText('PP1.c')).toBeTruthy();
    expect(screen.getByText('경로 규칙')).toBeTruthy();
  });

  it('지침은 mount 시 probe만 하고(LLM 0회) 생성 버튼을 낸다', async () => {
    const user = userEvent.setup();
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    await user.click(screen.getAllByRole('button', { name: /보기/ })[0]);
    await waitFor(() => expect(screen.getByRole('button', { name: '지침 생성' })).toBeTruthy());
    expect(post).toHaveBeenCalledWith('/api/summary/rule-conflict-advice',
      expect.objectContaining({ conflict_id: 'cast-cascade', probe: true }));

    mockAdvice = {
      ok: true, available: true, cached: false, conflict_id: 'cast-cascade',
      note: '이 지침은 제안이며 인과 판정이 아닙니다.',
      advice: {
        tradeoff: 'u16s_LIN_FAIL_TM 캐스팅이 10.8에 걸린다',
        both_satisfying_pattern: '#define X ((U16)1U)',
        recommended_order: '피연산자별 캐스팅 먼저',
        deviation_candidate: '', residual_risk: '가독성 저하', confidence: 'high',
      },
      ai_enriched: true, enrich_reason: null, model: 'gemini-3.5-flash-lite',
      evidence_used: { cooccurrence_excerpts: 2, window_diffs: 0 }, evidence_files: ['src/IF/ApiIn_LinRxComp_PDS.c'],
    };
    await user.click(screen.getByRole('button', { name: '지침 생성' }));
    await waitFor(() => expect(screen.getByText(/u16s_LIN_FAIL_TM 캐스팅이 10.8에 걸린다/)).toBeTruthy());
    expect(screen.getByText('#define X ((U16)1U)')).toBeTruthy();
    expect(screen.getByText(/남는 위험 — 가독성 저하/)).toBeTruthy();
  });

  it('증거가 없으면 일반론 지침을 만들지 않고 사유를 밝힌다', async () => {
    const user = userEvent.setup();
    mockAdvice = { ok: true, available: false, reason: 'no_code_evidence', conflict_id: 'cast-cascade', evidence_tier: 'ruleset_active' };
    render(<RuleConflictPanel {...props} data={DATA} defaultOpen />);
    await user.click(screen.getAllByRole('button', { name: /보기/ })[0]);
    await waitFor(() => expect(screen.getByText(/코드 증거.*찾지 못해 지침을 만들지 않았습니다/)).toBeTruthy());
    expect(screen.queryByRole('button', { name: '지침 생성' })).toBeNull();
  });
});
