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
