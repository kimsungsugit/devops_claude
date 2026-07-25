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
