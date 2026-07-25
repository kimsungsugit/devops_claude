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
    metrics_present: { functions: true, function_calls: true, statements: false, branches: false },
    totals: {
      entries: 1638,
      functions: { covered: 504, total: 1638, rate: 30.8 },
      function_calls: { covered: 855, total: 2989, rate: 28.6 },
      statements: null, branches: null,
    },
    worst: [
      { unit: 'b.c', subprogram: 'g_it', ccn: 1,
        functions: { covered: 0, total: 1, rate: 0.0 }, function_calls: { covered: 0, total: 3, rate: 0.0 } },
    ],
  },
  failed_testcases: { available: true, count: 0, items: [], source: 'build_artifact', source_path: 'D:\\x\\report\\vectorcast_rag\\vectorcast_rag.json' },
  coverage_source: 'vectorcast_metrics',
  coverage_source_detail: null,
};

// N1: 빌드 산출물에 함수 커버리지가 없어 SCM 입력 문서로 폴백한 응답(실측 KJPDS02_PV 형태).
const SCM_RESP = {
  ok: true, available: true, build_number: 125,
  coverage_source: 'scm_vcast_job',
  coverage_source_detail: { job_file: 'job_impact_20260725_113538_x.json', generated_at: '2026-07-25T11:39:22+09:00', complexity_rows: 1008 },
  function_coverage: {
    available: true, source: 'scm_vcast_job',
    totals: {
      functions: 1014, fully_covered: 991, uncovered: 0,
      statements: { covered: 10078, total: 10134, rate: 99.4 },
      branches: { covered: 4866, total: 4933, rate: 98.6 },
    },
    worst: [
      { unit: 'ADC_MONITOR', subprogram: 'ADC_MONITOR_HWEnDi', ccn: 7,
        statements: { covered: 7, total: 17, rate: 0.4118 }, branches: { covered: 2, total: 8, rate: 0.25 } },
    ],
    uncovered: [],
  },
  it_coverage: {
    available: true, source: 'scm_vcast_job',
    // SCM IT엔 진입(functions) 축이 없다 — 컬럼이 동적으로 구성돼야 한다.
    metrics_present: { functions: false, function_calls: true, statements: true, branches: true },
    totals: {
      entries: 712, functions: null,
      function_calls: { covered: 1256, total: 1258, rate: 99.8 },
      statements: { covered: 2350, total: 7438, rate: 31.6 },
      branches: { covered: 976, total: 3677, rate: 26.5 },
    },
    worst: [
      { unit: 'Ap_b', subprogram: 'g_scm_it', ccn: 1,
        statements: { covered: 1, total: 3, rate: 0.333 }, branches: { covered: 1, total: 1, rate: 1.0 },
        function_calls: { covered: 2, total: 3, rate: 0.667 } },
    ],
  },
  failed_testcases: {
    available: true, count: 0, items: [], source: 'scm_vcast_job', source_path: null,
    generated_at: '2026-07-25T11:39:22+09:00',
    test_summary: { total: 7502, passed: 7502, failed: 0, pass_rate: 1.0, ut_rows: 6844, it_rows: 658 },
  },
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
    expect(screen.getByText(/출처 빌드 산출물\(UT\/IT metrics\)/)).toBeInTheDocument(); // 소스 폴백 표기
    expect(screen.getByText('50%', { exact: false })).toBeInTheDocument(); // rate 0.5(0~1)→50%
  });

  it('IT 블록 — 보유 축(진입/호출)만 렌더 + env 접미사 정규화된 유닛', async () => {
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/진입 30\.8%/)).toBeInTheDocument();
    expect(screen.getByText(/구문·분기와 비교 불가/)).toBeInTheDocument();
    expect(screen.getByText('g_it')).toBeInTheDocument();
    // 빌드 IT엔 구문 축이 없다 — '구문' 헤더는 UT 표 하나뿐이어야 한다(0%로 위장 금지).
    expect(screen.getAllByRole('columnheader', { name: '구문' })).toHaveLength(1);
    expect(screen.getAllByRole('columnheader', { name: '진입' })).toHaveLength(1);
  });

  // ── N1: SCM 입력 문서 폴백 ──
  it('SCM 폴백 — 출처 배지(로드 시각)와 SCM 전용 IT 축(구문/분기/호출)', async () => {
    mockResp = SCM_RESP;
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    // 배지는 조상 패널과 텍스트가 겹치므로 접근 라벨로 정확히 지목한다
    expect(await screen.findByLabelText('커버리지 출처')).toHaveTextContent('SCM 입력 문서 · 2026-07-25 11:39 로드');
    expect(screen.getByText(/출처 SCM 입력 문서/)).toBeInTheDocument();
    // 진입 축이 없으므로 '비교 불가'가 아니라 'UT와 합산 금지' 문구
    expect(screen.getByText(/UT와 합산 금지/)).toBeInTheDocument();
    expect(screen.getByText(/구문 31\.6%/)).toBeInTheDocument();
    expect(screen.getByText('g_scm_it')).toBeInTheDocument();
    // SCM IT는 구문/분기/호출 3축 — UT 표까지 합쳐 '구문' 헤더는 2개, '진입'은 0개
    expect(screen.getAllByRole('columnheader', { name: '구문' })).toHaveLength(2);
    expect(screen.queryByRole('columnheader', { name: '진입' })).toBeNull();
  });

  it('SCM 폴백 — 실패 TC 집계와 출처를 SCM으로 표기', async () => {
    mockResp = SCM_RESP;
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/전체 7502/)).toBeInTheDocument();
    expect(screen.getByText(/출처: SCM 입력 문서/)).toBeInTheDocument();
  });

  it('커버리지 소스 전무 — 빌드·SCM 양쪽 부재를 명시', async () => {
    mockResp = { ...RESP, coverage_source: null, coverage_source_detail: null,
      function_coverage: { available: false, reason: 'no_function_coverage_source' } };
    render(<FunctionCoveragePanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/SCM 입력 문서 로드 이력에도 없습니다/)).toBeInTheDocument();
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
