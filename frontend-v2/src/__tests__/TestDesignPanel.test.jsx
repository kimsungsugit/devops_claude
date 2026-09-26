/** TestDesignPanel — MC/DC 배너·기법 테이블(iso_ref title)·band_missing 억제 문구·카탈로그. */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import TestDesignPanel from '../components/sections/TestDesignPanel.jsx';

const RESP = {
  ok: true, available: true, build_number: 26,
  mcdc_note: 'MC/DC는 현 빌드 산출물에 미측정 — 미측정≠미달.',
  catalog: {
    boundary_values: { label: '경계값 분석', iso_ref: 'ISO 26262-6 Table 8 1c', when: '분기 경계' },
    robustness: { label: '강건성(비정상 입력) 시험', iso_ref: 'ISO 26262-6 §9.4.2 연계', when: 'ASIL B+' },
  },
  technique_recommendations: {
    available: true, source_coverage: 'vectorcast_metrics', asil_source: 'comment_asil',
    coverage_join: { entries: 349, with_asil: 12, asil_unknown: 337 },
    items: [
      { function: 'Safe_Fn', unit: 'a.c', asil: 'C', ccn: 22, gap_kind: 'below_target',
        techniques: ['boundary_values', 'robustness'], basis: 'ASIL C · 구문 90% · 분기 50% · MC/DC 미측정 · ccn 22' },
    ],
    items_omitted: 0,
    summary: { below_target: 1, unmeasured_metric: 0, uncovered: 0, asil_unknown_with_gap: 0, mcdc_unmeasured_safety: 0 },
  },
  design_test_gap: {
    available: true,
    totals: { targets_with_uds: 626, uds_functions_distinct: 800, suts_tests_distinct: 3243, vcast_functions_distinct: 900 },
    band_missing: { suts: false, vcast: false },
    targets_with_uds_no_suts: [{ target_id: 'REQ-9', uds_count: 2 }],
    no_suts_omitted: 0,
    targets_with_uds_no_any_test: [],
    note: '갭은 요구ID 단위 링크 관측 기준',
  },
};

const PROPS = { jobUrl: 'http://j/', cacheRoot: '' };

describe('TestDesignPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockResp = RESP;
  });

  it('MC/DC 배너·기법 권고 테이블·coverage_join 캡션·갭 목록 렌더', async () => {
    render(<TestDesignPanel {...PROPS} />);
    expect(await screen.findByText(/미측정≠미달/)).toBeInTheDocument();
    expect(screen.getByText('Safe_Fn')).toBeInTheDocument();
    expect(screen.getByText('목표 미달')).toBeInTheDocument();
    // 기법 배지 title = iso_ref + when
    expect(screen.getByText('경계값 분석')).toHaveAttribute('title', expect.stringContaining('ISO 26262-6 Table 8 1c'));
    expect(screen.getByText(/ASIL 조인 12건/)).toBeInTheDocument();     // SwUFn 조인 함정 표면화
    expect(screen.getByText(/미상은 QM 단정 안 함/)).toBeInTheDocument();
    expect(screen.getByText('REQ-9')).toBeInTheDocument();
    expect(screen.getByText(/심사 판정 아님/)).toBeInTheDocument();
  });

  it('band_missing.suts — 요구별 열거 대신 증거 부재 문구', async () => {
    mockResp = {
      ...RESP,
      design_test_gap: {
        ...RESP.design_test_gap,
        band_missing: { suts: true, vcast: false },
        targets_with_uds_no_suts: [], no_suts_suppressed: true,
        targets_with_uds_no_any_test: [{ target_id: 'REQ-3', uds_count: 1 }],
      },
    };
    render(<TestDesignPanel {...PROPS} />);
    expect(await screen.findByText(/갭이 아니라 증거 부재/)).toBeInTheDocument();
    expect(screen.getByText(/어떤 시험 링크도 없음/)).toBeInTheDocument();
  });

  it('섹션별 정직 부재 — 커버리지 없음/링크 테이블 없음', async () => {
    mockResp = {
      ...RESP,
      technique_recommendations: { available: false, reason: 'no_coverage_entries' },
      design_test_gap: { available: false, reason: 'no_trace_link_table' },
    };
    render(<TestDesignPanel {...PROPS} />);
    expect(await screen.findByText(/기법 권고를 만들 수 없습니다/)).toBeInTheDocument();
    expect(screen.getByText(/설계-시험 갭을 판정하지 않습니다/)).toBeInTheDocument();
  });

  it('기법 카탈로그 토글', async () => {
    render(<TestDesignPanel {...PROPS} />);
    await screen.findByText(/미측정≠미달/);
    await userEvent.click(screen.getByText(/기법 카탈로그/));
    // 라벨은 기법 칩에도 존재 — 카탈로그 개행 후 2개 이상, iso_ref 셀 텍스트는 카탈로그 고유
    expect(screen.getAllByText('강건성(비정상 입력) 시험').length).toBeGreaterThan(1);
    expect(screen.getByText('ISO 26262-6 §9.4.2 연계')).toBeInTheDocument();
  });
});

// ── N4: 변경 축 · IT 별도 라벨 · 필터 · 케이스 초안 ──
describe('TestDesignPanel — N4', () => {
  const N4 = {
    ...RESP,
    technique_recommendations: {
      available: true, source_coverage: 'scm_vcast_job', asil_source: 'uds_link',
      coverage_join: { entries: 1267, ut_rows: 1008, it_rows: 259, with_asil: 508, asil_unknown: 759 },
      changed_axis: { available: true, baseline_build: 122, target_build: 125, count: 116 },
      asil_counts: { comment_asil: 0, uds_link: 385, both: 0, conflict: 0, total: 385 },
      items: [
        { function: 's_CPUInstructionTest', unit: 'SysDiagCtrl_PDS', asil: 'A', ccn: 3,
          metric_set: 'ut', changed: true, gap_kind: 'changed_below_target',
          techniques: ['boundary_values'], suggested_min_cases: 3, suggested_min_cases_estimate: true,
          basis: '변경됨 · ASIL A · 구문 80% · 분기 60% · ccn 3 · 분기 커버 최소 TC 추정 3' },
        { function: 'g_it_only', unit: 'Ap_Main', asil: null, ccn: 1,
          metric_set: 'it', changed: false, gap_kind: 'it_not_exercised',
          techniques: ['boundary_values'], basis: '통합(IT) 측정 · 구문 0%' },
      ],
      items_omitted: 222,
      summary: { below_target: 1, unmeasured_metric: 0, uncovered: 0, asil_unknown_with_gap: 137,
                 mcdc_unmeasured_safety: 0, changed_with_gap: 11, it_gap: 222 },
    },
  };

  beforeEach(() => { vi.clearAllMocks(); mockResp = N4; });

  it('UT 갭과 IT 축을 분리 표기 + 변경 축 구간 표시', async () => {
    render(<TestDesignPanel {...PROPS} />);
    expect(await screen.findByText(/단위\(UT\) 갭 1건 관측/)).toBeInTheDocument();
    expect(screen.getByText(/통합\(IT\) 축 222건/)).toBeInTheDocument();
    expect(screen.getByText(/변경 함수 갭 11건/)).toBeInTheDocument();
    expect(screen.getByText(/변경 축: #122→#125 \(116함수\)/)).toBeInTheDocument();
    expect(screen.getByText(/ASIL 출처 요구 역전파/)).toBeInTheDocument();
  });

  it('IT 행은 별도 갭 라벨(단위 미커버와 구분)', async () => {
    render(<TestDesignPanel {...PROPS} />);
    expect(await screen.findByText('IT 미실행')).toBeInTheDocument();
    expect(screen.getByText('변경·미달')).toBeInTheDocument();
  });

  it('필터 — 변경분만 고르면 IT 행이 빠진다', async () => {
    const user = userEvent.setup();
    render(<TestDesignPanel {...PROPS} />);
    await screen.findByText('s_CPUInstructionTest');
    expect(screen.getByText('g_it_only')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '변경분만' }));
    expect(screen.getByText('s_CPUInstructionTest')).toBeInTheDocument();
    expect(screen.queryByText('g_it_only')).toBeNull();
  });

  it('케이스 초안 — 버튼 클릭 시 on-demand 요청 후 표 렌더', async () => {
    const user = userEvent.setup();
    const { post } = await import('../api.js');
    render(<TestDesignPanel {...PROPS} />);
    await screen.findByText('s_CPUInstructionTest');
    post.mockImplementation((url) => {
      if (String(url).includes('test-case-draft')) {
        return Promise.resolve({
          ok: true, available: true, function: 's_CPUInstructionTest',
          file: 'Sources/SYSTEM/SysDiagCtrl_PDS.c',
          deterministic: {
            techniques: [{ id: 'boundary_values', label: '경계값 분석', iso_ref: 'ISO 26262-6 Table 8 1c' }],
            suggested_min_cases: 3, suggested_min_cases_estimate: true,
            boundary_candidates: [], coverage: { mcdc_state: 'unmeasured' },
          },
          cases: [{ id: 'TC1', purpose: '정상 경로', technique: 'equivalence_partitioning',
                    preconditions: '', inputs: '파라미터 없음', expected: 'flag == OFF',
                    covers: 'if (val != 0xAAAA5555U)' }],
          notes: ['외부 전역 초기화 필요'], dropped_cases: 0, ai_enriched: true,
          model: 'gemini-3.5-flash-lite', note: '초안이며 심사 판정이 아닙니다.',
        });
      }
      return Promise.resolve(N4);
    });
    await user.click(screen.getByRole('button', { name: /s_CPUInstructionTest 케이스 초안 생성/ }));
    expect(await screen.findByText('TC1')).toBeInTheDocument();
    expect(screen.getByText('if (val != 0xAAAA5555U)')).toBeInTheDocument();
    expect(screen.getByText(/최소 TC 추정 3\(McCabe 근사, 측정값 아님\)/)).toBeInTheDocument();
    expect(screen.getByText(/초안이며 심사 판정이 아닙니다/)).toBeInTheDocument();
  });

  it('초안 실패는 정직하게 사유 표기', async () => {
    const user = userEvent.setup();
    const { post } = await import('../api.js');
    render(<TestDesignPanel {...PROPS} />);
    await screen.findByText('s_CPUInstructionTest');
    post.mockImplementation((url) => (String(url).includes('test-case-draft')
      ? Promise.resolve({ ok: true, available: false, reason: 'function_not_found_in_snapshot' })
      : Promise.resolve(N4)));
    await user.click(screen.getByRole('button', { name: /s_CPUInstructionTest 케이스 초안 생성/ }));
    expect(await screen.findByText(/function_not_found_in_snapshot/)).toBeInTheDocument();
  });
});
