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
  functions: 0, code_metrics_source: 'lizard', coverage_source: 'build',
  tests_source: 'build', rcr_compliance_index: 90, ...over,
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

  it('SCM 이력 커버리지 프로젝트가 있으면 VectorCAST 구문/UT·IT 각주를 표시한다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'KJPDS02_PV', line_rate: 0.995, coverage_source: 'scm_vcast', tests_source: 'scm_vcast', ut_total: 120, it_total: 45 }),
      P({ name: 'HDPDM01', line_rate: 0.92, coverage_source: 'build', tests_source: 'build' }),
    ]} buildStats={{ total: 2 }} />);
    // <b> 조각으로 커버리지·테스트 각주를 각각 검증(둘 다 'SCM 로드 이력의'라 bold로 구분).
    expect(screen.getByText('VectorCAST 구문 커버리지')).toBeInTheDocument();
    expect(screen.getByText('VectorCAST UT/IT 개수')).toBeInTheDocument();
  });

  it('빌드 0.0 플레이스홀더+SCM 무이력 프로젝트는 미집계 각주로 구분한다', () => {
    // 실측 KJPDS02_PV(무이력): 빌드 line_rate=0.0이라 null 조건으론 안 걸림 → coverage_source==null로 판정.
    render(<AggregateCharts projects={[
      P({ name: 'NODATA', line_rate: 0, coverage_source: null, tests_source: null, ut_total: 0, it_total: 0 }),
    ]} buildStats={{ total: 1 }} />);
    expect(screen.getByText(/커버리지 미집계/)).toBeInTheDocument();
    expect(screen.getByText('0 표시')).toBeInTheDocument();  // <b> 조각, 코드규모 '0(미집계)'와 구분
  });

  it('모든 프로젝트가 빌드 소스면 SCM/미집계 커버리지 각주를 표시하지 않는다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'HDPDM01', line_rate: 0.92, coverage_source: 'build', tests_source: 'build' }),
    ]} buildStats={{ total: 1 }} />);
    expect(screen.queryByText('VectorCAST 구문 커버리지')).toBeNull();
    expect(screen.queryByText('VectorCAST UT/IT 개수')).toBeNull();
    expect(screen.queryByText('0 표시')).toBeNull();
  });
});
