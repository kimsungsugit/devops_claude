/**
 * ArchitectureMetricsPanel — v4(N5) 블록: ASIL 간섭 후보·전역 결합·커버리지×복잡도·
 * 간접 호출/캡슐화. 각 블록은 부재 시 정직 안내로 폴백해야 하고(증거부재≠0),
 * 파서 한계(static 과소 탐지)는 비율 대신 note로 고지된다.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import ArchitectureMetricsPanel from '../components/sections/ArchitectureMetricsPanel.jsx';

const RESP = {
  ok: true, available: true, version: 4, build_number: 125,
  snapshot: { files: 62, functions: 917, parse_ms: 1506, parser_engine: 'tree-sitter' },
  hotspots: [{ function: 'hub', file: 'a.c', fan_in: 9, complexity: 12, complexity_source: 'vcast_ccn', score: 108 }],
  coupling: { edges: 100, cross_edges: 27, cross_file_call_ratio: 0.27, top_pairs: [{ from_file: 'APP/a.c', to_file: 'BSW/b.c', calls: 5 }] },
  size_outliers: [{ function: 'big', file: 'a.c', lines: 400 }],
  asil_interference: {
    available: true, graded_functions: 385, edges_total: 419, mixed_modules: 0,
    edges: [{ caller: 'ADC_MONITOR_Disable', callee: 'ADC_MONITOR_HWEnDi', caller_asil: 'A',
              callee_asil: null, higher: 'ADC_MONITOR_Disable', lower: 'ADC_MONITOR_HWEnDi',
              caller_file: 'APP/adc.c', callee_file: 'APP/adc.c', cross_module: false }],
    note: '등급이 다른 함수 간 호출은 검토 후보이며 위반 판정이 아니다.',
  },
  global_coupling: {
    available: true, distinct_globals: 586, cross_module_globals: 0, functions_using_globals: 413,
    top: [{ global: 'u8s_DidLsb', functions: 39, modules: 1, files: 3, module_names: ['Sources/SYSTEM'] }],
    note: '파서는 읽기/쓰기를 구분하지 않는다 — 사용(참조) 기준이다.',
  },
  coverage_complexity: {
    available: true, joined: 761, unjoined: 156, complexity_basis: 'vcast_ccn',
    complexity_threshold: 4, coverage_threshold: 0.8,
    counts: { high_complex_low_cov: 3, high_complex_high_cov: 231, low_complex_low_cov: 0, low_complex_high_cov: 527 },
    priority: [{ function: 'ADC_MONITOR_HWEnDi', file: 'APP/adc.c', statement: 0.4118, complexity: 7, complexity_source: 'vcast_ccn' }],
    note: '사분면 임계는 측정 복잡도 상위 25%와 구문 80% 기준이다.',
  },
  indirect_calls: {
    functions_with_indirect: 694, reference_edges: 2714, func_ref_functions: 690, pointer_call_functions: 6,
    top: [{ function: 'ptr_user', func_refs: 3, pointer_calls: 1, file: 'BSW/b.c' }],
    note: '함수포인터 참조·간접 호출 사이트는 호출 그래프 엣지에 포함되지 않는다.',
  },
  encapsulation: {
    functions: 917, static_functions_detected: 2, static_detection_reliable: false,
    header_defined_functions: 6, header_defined_top: [], documented_functions: 685, documented_ratio: 0.747,
    note: 'static 판정은 파서 한계로 과소 탐지된다 — 비율 해석 금지.',
  },
};

describe('ArchitectureMetricsPanel v4', () => {
  beforeEach(() => { vi.clearAllMocks(); mockResp = RESP; });

  it('ASIL 간섭 후보 — 등급 상이 호출과 판정 아님 고지', async () => {
    render(<ArchitectureMetricsPanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/등급 보유 함수 385/)).toBeInTheDocument();
    expect(screen.getByText('419')).toBeInTheDocument();
    // callee명은 사분면 표에도 나오므로 간섭 행 안에서 확인한다
    const edgeRow = screen.getByText(/ADC_MONITOR_Disable/).closest('tr');
    expect(edgeRow).toHaveTextContent('ADC_MONITOR_HWEnDi');
    expect(edgeRow).toHaveTextContent('미상');       // 하위 등급 미상 표기
    expect(screen.getByText(/위반 판정이 아니/)).toBeInTheDocument();
  });

  it('전역 결합 — 다중 모듈 참조 수와 read/write 미구분 고지', async () => {
    render(<ArchitectureMetricsPanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/전역 586개 중/)).toBeInTheDocument();
    expect(screen.getByText(/읽기\/쓰기를 구분하지 않는다/)).toBeInTheDocument();
  });

  it('커버리지×복잡도 — 미조인 수를 침묵하지 않는다', async () => {
    render(<ArchitectureMetricsPanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/조인 761함수\(미조인 156\)/)).toBeInTheDocument();
    expect(screen.getByText('41%')).toBeInTheDocument();     // 0.4118 → 41%
  });

  it('간접 호출 — 콜그래프 미반영 규모를 표면화', async () => {
    render(<ArchitectureMetricsPanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/참조 엣지 2714건/)).toBeInTheDocument();
    expect(screen.getByText(/위 fan-in\/사이클에 미반영/)).toBeInTheDocument();
    expect(screen.getByText(/문서화 75%/)).toBeInTheDocument();
    expect(screen.getByText(/비율 해석 금지/)).toBeInTheDocument();
  });

  it('v4 블록 부재(구 캐시 v3 응답) — 정직 안내로 폴백', async () => {
    mockResp = { ...RESP, version: 3, asil_interference: undefined, global_coupling: undefined,
      coverage_complexity: undefined, indirect_calls: undefined, encapsulation: undefined };
    render(<ArchitectureMetricsPanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/함수 ASIL 등급 정보가 없어/)).toBeInTheDocument();
    expect(screen.getByText(/전역 참조가 관측되지 않았습니다/)).toBeInTheDocument();
    expect(screen.getByText(/함수 커버리지 인덱스가 없어/)).toBeInTheDocument();
  });

  it('간섭·사분면 available:false — 사유를 삼키지 않는다', async () => {
    mockResp = {
      ...RESP,
      asil_interference: { available: false, reason: 'no_asil_index', edges: [], modules: [] },
      coverage_complexity: { available: false, reason: 'no_coverage_index' },
    };
    render(<ArchitectureMetricsPanel jobUrl="http://j/" cacheRoot="" />);
    expect(await screen.findByText(/주석·요구 역전파 모두 부재/)).toBeInTheDocument();
    expect(screen.getByText(/사분면을 낼 수 없습니다/)).toBeInTheDocument();
  });
});
