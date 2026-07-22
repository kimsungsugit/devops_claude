/**
 * AggregateCharts — 대시보드 집계 차트.
 * 핵심 검증: 코드규모 LOC 카드가 lizard/QAC 혼재 시 정직 각주를 표시(silent 혼재 방지),
 * 그리고 backend가 채운 loc/diagnostics가 렌더되는지(상세탭 연계 sanity).
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import AggregateCharts from '../components/AggregateCharts.jsx';

const P = (over = {}) => ({
  job_url: `http://jk/job/${over.name || 'X'}/`, name: 'X', result: 'SUCCESS',
  line_rate: 0.9, ut_total: 10, it_total: 5, diagnostics: 0, loc: 0,
  functions: 0, code_metrics_source: 'lizard', rcr_compliance_index: 90, ...over,
});

describe('AggregateCharts', () => {
  it('QAC 폴백 프로젝트가 있으면 코드규모 카드에 QAC LOC 각주를 표시한다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'KJPDS02_PV', loc: 67464, functions: 881, diagnostics: 496, code_metrics_source: 'qac' }),
      P({ name: 'HDPDM01', loc: 4429, functions: 349, diagnostics: 577, code_metrics_source: 'lizard' }),
    ]} buildStats={{ total: 2 }} />);
    expect(screen.getByText(/QAC LOC\(헤더 포함\)/)).toBeInTheDocument();
    // 연계된 값이 실제로 렌더되는지(이전엔 0)
    expect(screen.getByText('67,464')).toBeInTheDocument();
    expect(screen.getByText('496')).toBeInTheDocument();
  });

  it('모든 프로젝트가 lizard면 QAC 각주를 표시하지 않는다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'HDPDM01', loc: 4429, functions: 349, diagnostics: 577, code_metrics_source: 'lizard' }),
    ]} buildStats={{ total: 1 }} />);
    expect(screen.queryByText(/QAC LOC\(헤더 포함\)/)).toBeNull();
  });

  it('완전 부재(code_metrics_reason) 프로젝트는 0으로 뜨되 미집계 각주로 구분한다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'NODATA', loc: 0, functions: 0, diagnostics: 0, code_metrics_source: null, code_metrics_reason: 'no_complexity_csv_and_no_qac' }),
    ]} buildStats={{ total: 1 }} />);
    // 문구가 <b>로 쪼개져 단일 노드 조각으로 검증.
    expect(screen.getByText('0(미집계)')).toBeInTheDocument();
    expect(screen.getByText(/실제 0 아님/)).toBeInTheDocument();
  });
});
