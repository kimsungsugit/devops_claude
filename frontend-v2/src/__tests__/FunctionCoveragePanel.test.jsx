/** FunctionCoveragePanel — UT 구문/분기 totals·source 캡션·IT 분리 블록·실패 TC 출처(L1). */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import FunctionCoveragePanel from '../components/sections/FunctionCoveragePanel.jsx';

const RESP = {
  ok: true, available: true, build_number: 26,
  function_coverage: {
    available: true, source: 'vectorcast_metrics',
    totals: {
      functions: 349, fully_covered: 340, uncovered: 2,
      statements: { covered: 4396, total: 4429, rate: 99.3 },
      branches: { covered: 1868, total: 1893, rate: 98.7 },
    },
    worst: [
      { unit: 'a.c', subprogram: 'f_half', ccn: 5,
        statements: { covered: 5, total: 10, rate: 0.5 }, branches: { covered: 1, total: 4, rate: 0.25 } },
    ],
    uncovered: [],
  },
  it_coverage: {
    available: true, source: 'vectorcast_metrics',
    totals: {
      entries: 1638,
      functions: { covered: 504, total: 1638, rate: 30.8 },
      function_calls: { covered: 855, total: 2989, rate: 28.6 },
    },
    worst: [
      { unit: 'b.c', subprogram: 'g_it', ccn: 1,
        functions: { covered: 0, total: 1, rate: 0.0 }, function_calls: { covered: 0, total: 3, rate: 0.0 } },
    ],
  },
  failed_testcases: { available: true, count: 0, items: [], source_path: 'D:\\x\\report\\vectorcast_rag\\vectorcast_rag.json' },
};

describe('FunctionCoveragePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockResp = RESP;
  });

  it('UT totals(구문+분기)·source 캡션·0~1 스케일 rate 방어 렌더', async () => {
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/구문 99\.3%/)).toBeInTheDocument();
    expect(screen.getByText(/분기 98\.7%/)).toBeInTheDocument();        // L1: 분기 totals 신설
    expect(screen.getByText(/출처 UT metrics/)).toBeInTheDocument();    // 소스 폴백 표기
    expect(screen.getByText('50%', { exact: false })).toBeInTheDocument(); // rate 0.5(0~1)→50%
  });

  it('IT 블록 — 별개 메트릭 라벨 + env 접미사 정규화된 유닛', async () => {
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/함수 진입 30\.8%/)).toBeInTheDocument();
    expect(screen.getByText(/구문·분기와 비교 불가/)).toBeInTheDocument();
    expect(screen.getByText('g_it')).toBeInTheDocument();
  });

  it('실패 TC 출처 경로 캡션(source_path)', async () => {
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/출처: …vectorcast_rag\/vectorcast_rag\.json/)).toBeInTheDocument();
  });

  it('IT 부재 — 정직 안내(available:false 분리)', async () => {
    mockResp = { ...RESP, it_coverage: { available: false, reason: 'no_it_metrics' } };
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/통합\(IT\) 메트릭이 없습니다/)).toBeInTheDocument();
  });
});
