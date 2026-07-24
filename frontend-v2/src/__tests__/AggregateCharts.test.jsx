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

  it('구문 커버리지(UT 기준) 제목 + UT 기준 SCM 프로젝트는 기준-상이 각주 없이 UT/IT 각주만', () => {
    render(<AggregateCharts projects={[
      P({ name: 'KJPDS02_PV', line_rate: 0.995, coverage_source: 'scm_vcast', coverage_basis: 'ut_statement', tests_source: 'scm_vcast', ut_total: 120, it_total: 45 }),
      P({ name: 'HDPDM01', line_rate: 0.92, coverage_source: 'build', coverage_basis: 'ut_statement', tests_source: 'build' }),
    ]} buildStats={{ total: 2 }} />);
    expect(screen.getByText('구문 커버리지 (UT 기준, %)')).toBeInTheDocument();
    // 둘 다 UT 구문 기준 → 기준-상이 각주 없음.
    expect(screen.queryByText(/UT 구문 커버리지 미산출/)).toBeNull();
    // TC 개수 각주(tests_source)는 변경 없음 — 그대로 표시.
    expect(screen.getByText('VectorCAST UT/IT 개수')).toBeInTheDocument();
  });

  it('UT 구문을 못 뽑은 프로젝트(비-ut_statement)만 기준-상이 각주로 폭로한다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'UT_OK', line_rate: 0.99, coverage_source: 'scm_vcast', coverage_basis: 'ut_statement' }),
      P({ name: 'IT_ONLY', line_rate: 0.4, coverage_source: 'scm_vcast', coverage_basis: 'it_statement' }),
      P({ name: 'BUILD_LINE', line_rate: 0.8, coverage_source: 'build', coverage_basis: 'build_line' }),
    ]} buildStats={{ total: 3 }} />);
    const note = screen.getByText(/UT 구문 커버리지 미산출/);
    expect(note).toBeInTheDocument();
    // 비-UT 프로젝트만 이름+기준 라벨로 나열, UT_OK는 제외.
    expect(note.textContent).toMatch(/IT_ONLY\(IT 구문\)/);
    expect(note.textContent).toMatch(/BUILD_LINE\(빌드 라인커버\)/);
    expect(note.textContent).not.toMatch(/UT_OK/);
  });

  it('빌드 0.0 플레이스홀더+SCM 무이력 프로젝트는 미집계 각주로 구분한다', () => {
    // 실측 KJPDS02_PV(무이력): 빌드 line_rate=0.0이라 null 조건으론 안 걸림 → coverage_source==null로 판정.
    render(<AggregateCharts projects={[
      P({ name: 'NODATA', line_rate: 0, coverage_source: null, tests_source: null, ut_total: 0, it_total: 0 }),
    ]} buildStats={{ total: 1 }} />);
    expect(screen.getByText(/커버리지 미집계/)).toBeInTheDocument();
    expect(screen.getByText('0 표시')).toBeInTheDocument();  // <b> 조각, 코드규모 '0(미집계)'와 구분
  });

  it('모든 프로젝트가 UT 구문 기준이면 기준-상이/미집계 커버리지 각주를 표시하지 않는다', () => {
    render(<AggregateCharts projects={[
      P({ name: 'HDPDM01', line_rate: 0.92, coverage_source: 'build', coverage_basis: 'ut_statement', tests_source: 'build' }),
    ]} buildStats={{ total: 1 }} />);
    expect(screen.queryByText(/UT 구문 커버리지 미산출/)).toBeNull();
    expect(screen.queryByText('VectorCAST UT/IT 개수')).toBeNull();
    expect(screen.queryByText('0 표시')).toBeNull();
  });
});
