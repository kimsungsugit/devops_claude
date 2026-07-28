/**
 * ArchitectureImprovementPanel — 결정론 후보 표시 · 필터 · As-Is/To-Be 병렬 · 정직 폴백(Q3).
 * 핵심: AI 없이도 후보는 보여야 하고, 목표 구조 미생성 사유를 삼키지 않아야 한다.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import ArchitectureImprovementPanel from '../components/sections/ArchitectureImprovementPanel.jsx';

const PROPS = { jobUrl: 'http://j/', cacheRoot: '' };

const BASE = {
  ok: true, available: true, build_number: 125,
  candidates: [
    { kind: 'break_cycle', target: 'APP/b.c → APP/a.c', files: ['APP/a.c', 'APP/b.c'],
      action: '이 호출을 인터페이스로 뒤집어 순환을 끊는다',
      basis: '순환 2파일 중 최소 비용 간선 — 호출 2회', effort: 'low' },
    { kind: 'inject_global', target: 'g_shared', globals: ['g_shared'], functions: ['hi_fn'],
      action: '전역 직접 참조 대신 파라미터로 주입한다',
      basis: '2개 모듈 · 39개 함수가 참조(읽기/쓰기 미구분)', effort: 'high' },
  ],
  summary: { total: 2, by_kind: { break_cycle: 1, inject_global: 1 }, structural: 1, testability: 1 },
  as_is: { nodes: [{ module: 'APP', files: 2, functions: 6 }], edges: [{ from: 'APP', to: 'LIB', calls: 4 }] },
  note: '아래 후보와 목표 구조는 측정치에서 도출한 제안이며 검증된 설계가 아닙니다.',
  target_design: null, ai_enriched: false, enrich_reason: 'not_generated',
};

describe('ArchitectureImprovementPanel', () => {
  beforeEach(() => { vi.clearAllMocks(); mockResp = BASE; });

  it('AI 없이도 결정론 후보를 근거 수치와 함께 표시한다', async () => {
    render(<ArchitectureImprovementPanel {...PROPS} />);
    expect(await screen.findByText('순환 끊기')).toBeInTheDocument();
    expect(screen.getByText('APP/b.c → APP/a.c')).toBeInTheDocument();
    expect(screen.getByText(/최소 비용 간선 — 호출 2회/)).toBeInTheDocument();
    expect(screen.getByText(/후보 2건/)).toBeInTheDocument();
    expect(screen.getByText(/구조 1 · 테스트 용이성 1/)).toBeInTheDocument();
  });

  it('필터 — 테스트 용이성만 고르면 구조 후보가 빠진다', async () => {
    const user = userEvent.setup();
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    await user.click(screen.getByRole('button', { name: '테스트 용이성' }));
    expect(screen.getByText('전역 주입화')).toBeInTheDocument();
    expect(screen.queryByText('순환 끊기')).toBeNull();
  });

  it('목표 구조 미생성 — 사유를 삼키지 않는다', async () => {
    render(<ArchitectureImprovementPanel {...PROPS} />);
    expect(await screen.findByText(/아직 생성하지 않았습니다/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /목표 구조 생성/ })).toBeInTheDocument();
  });

  it('생성 후 As-Is와 To-Be를 나란히 + 폐기 노드 수 표기', async () => {
    const user = userEvent.setup();
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    mockResp = {
      ...BASE, ai_enriched: true, enrich_reason: null, model: 'gemini-3.5-flash-lite',
      target_design: {
        nodes: [
          { module: 'APP', members: ['APP/a.c'], role: '응용 로직', is_new: false },
          { module: 'Diag_New', members: ['ADC_HWEnDi'], role: '진단 분리', is_new: true },
        ],
        edges: [{ from: 'APP', to: 'Diag_New', why: '진단 호출' }],
        rationale: ['순환 2파일 · 최소 비용 간선 2회'],
        dropped_nodes: 1,
      },
    };
    await user.click(screen.getByRole('button', { name: /목표 구조 생성/ }));
    expect(await screen.findByText('현재 (As-Is)')).toBeInTheDocument();
    expect(screen.getByText('제안 (To-Be)')).toBeInTheDocument();
    expect(screen.getByText('Diag_New')).toBeInTheDocument();
    expect(screen.getByText(/신설/)).toBeInTheDocument();
    expect(screen.getByText(/폐기한 제안 모듈 1개/)).toBeInTheDocument();
    expect(screen.getByText(/순환 2파일 · 최소 비용 간선 2회/)).toBeInTheDocument();
  });

  it('To-Be가 As-Is와 1:1로 같으면 "구조 변경 아님"을 먼저 알린다', async () => {
    // ⚠ 실측(KJPDS02_PV): AI가 현재 모듈 8개를 그대로 되풀이하고 역할 설명만 붙였다.
    //   표만 나란히 두면 사용자가 그걸 알아채려고 8행을 눈으로 대조해야 한다.
    const user = userEvent.setup();
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    mockResp = {
      ...BASE, ai_enriched: true, enrich_reason: null, model: 'gemini-3.5-flash-lite',
      target_design: {
        nodes: [{ module: 'APP', members: ['APP'], role: '응용 로직 계층', is_new: false }],
        edges: [{ from: 'APP', to: 'LIB', why: '기존 호출' }],
        rationale: [], dropped_nodes: 0,
      },
    };
    await user.click(screen.getByRole('button', { name: /목표 구조 생성/ }));
    expect(await screen.findByText(/1:1로 동일/)).toBeInTheDocument();
    expect(screen.getByText(/역할 설명/)).toBeInTheDocument();
    // '구성: 자기 자신'은 정보가 0이라 '동일'로 접는다
    expect(screen.getByText('동일')).toBeInTheDocument();
  });

  it('후보 0건 — 생성 버튼 없이 "임계 초과 없음"만 알린다', async () => {
    mockResp = { ...BASE, candidates: [], summary: { total: 0, by_kind: {}, structural: 0, testability: 0 } };
    render(<ArchitectureImprovementPanel {...PROPS} />);
    expect(await screen.findByText(/임계를 넘는 개선 후보가 없습니다/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /목표 구조 생성/ })).toBeNull();
  });

  it('제안≠검증된 설계 고지를 상시 노출', async () => {
    render(<ArchitectureImprovementPanel {...PROPS} />);
    expect(await screen.findByText(/검증된 설계가 아닙니다/)).toBeInTheDocument();
  });

  it('available:false reason 렌더', async () => {
    mockResp = { ok: true, available: false, reason: 'no_source_snapshot' };
    render(<ArchitectureImprovementPanel {...PROPS} />);
    expect(await screen.findByText(/소스 스냅샷이 없어 제안을 만들 수 없습니다/)).toBeInTheDocument();
  });
});

// ── 상세 플레이북 — "뭘 개선하라는 건지 모르겠다"를 없애는 층 ────────────────────
describe('ArchitectureImprovementPanel — 상세 개선안', () => {
  const withDetail = (detail, extra = {}) => ({
    ...BASE,
    candidates: [{ ...BASE.candidates[0], detail, ...extra }, BASE.candidates[1]],
  });

  beforeEach(() => { vi.clearAllMocks(); });

  it('▸ 를 눌러야 상세가 나온다 — 단계·스텁 계획·코드 스케치', async () => {
    const user = userEvent.setup();
    mockResp = withDetail({
      version: 1,
      summary: 'a.c가 b.c의 B_Notify()를 직접 부르는 바람에 순환이 생긴다.',
      steps: ['A_Cb.h에 콜백 타입을 선언한다.', 'A_Tick() 안의 직접 호출을 슬롯 호출로 바꾼다.'],
      sketch: { lang: 'c', before: 'B_Notify();', after: 'if (s_cb != NULL) { s_cb(); }',
        note: '타입·인자는 파서가 주지 않아 주석으로 비워 둔 스케치다 — 그대로 컴파일되지 않는다.' },
      stub_plan: { what: ['테스트가 s_cb 에 자기 스텁을 등록한다'], gain: 'b.c 링크가 불필요해진다.' },
      impact: { files_in_cycle: 2, edge_call_sites: 1 },
      caveats: [],
    });
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    // 접힌 상태에서는 상세가 DOM 에 없다(스캔 소음 방지)
    expect(screen.queryByText(/A_Cb.h에 콜백 타입/)).toBeNull();

    await user.click(screen.getByRole('button', { name: /상세 개선안 펼치기/ }));
    expect(screen.getByText(/A_Cb.h에 콜백 타입/)).toBeInTheDocument();
    expect(screen.getByText('시험 스텁 계획')).toBeInTheDocument();
    expect(screen.getByText(/s_cb 에 자기 스텁을 등록한다/)).toBeInTheDocument();
    expect(screen.getByText('if (s_cb != NULL) { s_cb(); }')).toBeInTheDocument();
  });

  it('코드는 스케치라고 항상 말한다 — 그대로 복사하면 컴파일이 안 되기 때문', async () => {
    const user = userEvent.setup();
    mockResp = withDetail({
      version: 1, summary: 's', steps: [],
      sketch: { lang: 'c', before: 'x', after: 'y', note: '그대로 컴파일되지 않는다.' },
      caveats: [],
    });
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    await user.click(screen.getByRole('button', { name: /상세 개선안 펼치기/ }));
    expect(screen.getByText(/그대로 컴파일되지 않는다/)).toBeInTheDocument();
  });

  it('분할 제안 — 어느 함수가 어느 파일로 가는지 보여준다', async () => {
    const user = userEvent.setup();
    mockResp = withDetail({
      version: 1, summary: '파일 내부 호출 덩어리 기준으로 2덩어리로 갈린다.',
      steps: ['x_Env.c — 함수 7개'],
      split_proposal: [
        { file: 'x_Env.c', size: 7, label: 's_Env', functions: ['s_Env_Calc', 's_Env_Read'] },
        { file: 'x_Perf.c', size: 5, label: 's_Perf', functions: ['s_Perf_Track'] },
      ],
      sketch: null, stub_plan: null, impact: { cut_calls: 0 }, caveats: [],
    });
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    await user.click(screen.getByRole('button', { name: /상세 개선안 펼치기/ }));
    expect(screen.getByText('x_Env.c')).toBeInTheDocument();
    expect(screen.getByText(/s_Env_Calc, s_Env_Read/)).toBeInTheDocument();
  });

  it('분할 축이 없으면 군집을 지어내지 않고 그 사실을 말한다', async () => {
    const user = userEvent.setup();
    mockResp = withDetail({
      version: 1,
      summary: '이 파일은 **기계적 분할선이 없다** — 함수 95%가 서로 호출로 한 덩어리다.',
      steps: ['기능(도메인) 단위로 먼저 나눈다.'],
      sketch: null, stub_plan: null,
      impact: { largest_component_share: 0.953 },
      caveats: ['연결성분·이름 접두사 두 축 모두 임계 미달이라 자동 군집을 제시하지 않는다.'],
    });
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    await user.click(screen.getByRole('button', { name: /상세 개선안 펼치기/ }));
    expect(screen.getByText(/기계적 분할선이 없다/)).toBeInTheDocument();
    expect(screen.getByText(/자동 군집을 제시하지 않는다/)).toBeInTheDocument();
    expect(screen.queryByText(/분할 제안/)).toBeNull();
  });

  it('상세가 없는 후보는 토글이 없다 — 빈 상세를 만들지 않는다', async () => {
    mockResp = { ...BASE, playbook: { total: 2, with_detail: 0, without_detail: 2 } };
    render(<ArchitectureImprovementPanel {...PROPS} />);
    await screen.findByText('순환 끊기');
    expect(screen.queryByRole('button', { name: /상세 개선안 펼치기/ })).toBeNull();
    expect(screen.getByText(/2건은 상세 재료 없음/)).toBeInTheDocument();
  });

  it('detail 없는 구 응답에서도 표는 그대로 뜬다(하위호환)', async () => {
    mockResp = BASE;   // playbook 키 자체가 없음
    render(<ArchitectureImprovementPanel {...PROPS} />);
    expect(await screen.findByText('순환 끊기')).toBeInTheDocument();
    expect(screen.getByText('APP/b.c → APP/a.c')).toBeInTheDocument();
  });
});
