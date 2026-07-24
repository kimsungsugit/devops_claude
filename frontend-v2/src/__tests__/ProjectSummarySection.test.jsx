/**
 * ProjectSummarySection — 재설계(세그먼트 현황/빌드별) 단위 테스트.
 * - 현황: 문제점 배너 + 정적·동적 차트 + 추적성
 * - 빌드별: 변경 영향 타임라인 + PRQA 트렌드
 * - ISO 정직성: 커버리지 미측정≠정상, VectorCAST SCM 스냅샷
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockTimeline;
let mockScmVcast;
let mockTrace;
let mockPrqaTrend;
let mockTraceGenSuccess;
let mockCfg;
let mockAllBuilds;

vi.mock('../api.js', () => ({
  api: vi.fn((url) => (String(url).includes('build-timeline') ? Promise.resolve(mockTimeline) : Promise.resolve({}))),
  post: vi.fn((url) => {
    const u = String(url);
    if (u.includes('scm-vcast-summary')) return Promise.resolve(mockScmVcast);
    if (u.includes('trace-summary')) return Promise.resolve(mockTrace);
    if (u.includes('prqa-trend')) return Promise.resolve(mockPrqaTrend);
    if (u.includes('/api/jenkins/builds')) return Promise.resolve(mockAllBuilds);
    return Promise.resolve({});
  }),
  defaultCacheRoot: () => '.devops_pro_cache',
}));
vi.mock('../App.jsx', () => ({ useToast: () => () => {}, useJenkinsCfg: () => ({ cfg: mockCfg }) }));
vi.mock('../projectLoader.js', () => ({ pickScmForJob: () => ({ id: 'kj' }) }));
vi.mock('../traceMatrix.js', () => ({
  buildTraceMatrix: vi.fn(async () => {
    if (mockTraceGenSuccess) {
      // 성공 시 캐시가 생긴 것처럼 다음 trace-summary가 has_data:true 반환하도록 세팅.
      mockTrace = { has_data: true, coverage_pct: 82, covered: 56, partial: 4, uncovered: 8, total_requirements: 68, asil_gap_count: 2, asil_unknown_count: 12, integrity_collision_count: 0, integrity_dangling_count: 0, band_counts: {}, asil_distribution: {}, summary_raw: {}, generated_at: '2026-03-24T13:00:00' };
      return { ok: true, warnings: [], dataSources: [] };
    }
    return { ok: false, reason: 'no_requirements', warnings: [] };
  }),
}));

const { default: ProjectSummarySection } = await import('../components/sections/ProjectSummarySection.jsx');

const JOB = { name: 'kjpds02_pv', url: 'http://jenkins/job/KJPDS02_PV/' };
const RESULT = {
  matchedScm: { id: 'kj' },
  reportData: {
    kpis: {
      code_metrics: { code_files: 126, functions: 823, nloc: 64805, source: 'qac' },
      prqa: { rule_violation_count: 562, diagnostic_count: 502, project_compliance_index: 91 },
    },
  },
};

const TIMELINE = {
  ok: true, entry_id: 'kj',
  rows: [{
    run_id: 'r1', timestamp: '2026-03-24T12:00:00', build_number: 125, build_revision: '1053',
    build_revision_is_head: false, base_ref: '1018', changed_files_count: 2, changed_functions_count: 5,
    impact_counts: { direct: 3, indirect_1hop: 2, indirect_2hop: 0 },
    max_asil: 'ASIL C', max_asil_bucket: 'C', mcdc_required: true,
    auto_docs: 3, flag_docs: 1, coverage_regressed: 0, coverage_unmeasured_safety: 0,
    coverage_measured: true, partial_failure: false, before_payload_unavailable: false,
  }],
  rollup: {
    analyzed_build_count: 1, distinct_changed_functions: 5, distinct_changed_files: 2,
    cumulative_auto_docs: 3, cumulative_flag_docs: 1, cumulative_coverage_regressed: 0,
    mcdc_required_any: true, asil_distribution: { D: 0, C: 1, B: 0, A: 0, QM: 0, unknown: 0 },
    revision_range: { base_ref: '1018', min_build_revision: 1053, max_build_revision: 1053 },
  },
  snapshot_note: '정적·동적 분석은 현재 SCM 스냅샷',
};
const SCMVCAST = { available: true, line_rate: 0.9945, branch_rate: 0.986, coverage_basis: 'ut_statement', ut_total: 6886, ut_passed: 6886, it_total: 616, it_passed: 616 };
const TRACE = {
  has_data: true, coverage_pct: 82, covered: 56, partial: 4, uncovered: 8, total_requirements: 68,
  asil_gap_count: 2, asil_unknown_count: 12, integrity_collision_count: 1, integrity_dangling_count: 0,
  band_counts: { UDS: 64, STS: 60, SUTS: 58, SITS: 20 }, asil_distribution: {},
  summary_raw: { unmapped_vcast_count: 5 }, generated_at: '2026-03-24T12:00:00',
};
const PRQATREND = {
  available: true, count: 3,
  builds: [
    { build_number: 122, violations: 558, diagnostics: 496, compliance: 92 },
    { build_number: 124, violations: 552, diagnostics: 492, compliance: 91 },
    { build_number: 125, violations: 562, diagnostics: 502, compliance: 91 },
  ],
};

describe('ProjectSummarySection (재설계)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTimeline = TIMELINE;
    mockScmVcast = SCMVCAST;
    mockTrace = TRACE;
    mockPrqaTrend = PRQATREND;
    mockTraceGenSuccess = false;
    mockCfg = {};
    mockAllBuilds = [];
    localStorage.clear();
  });

  it('현황: 정적(PRQA) 위반/진단을 표시한다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('562')).toBeInTheDocument(); // PRQA 위반
    expect(screen.getByText('502')).toBeInTheDocument();         // 진단
  });

  it('현황: 동적(VectorCAST) UT/IT 테스트 수를 표시한다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('6,886/6,886')).toBeInTheDocument(); // UT 통과/전체
    expect(screen.getByText('616/616')).toBeInTheDocument();            // IT
  });

  it('현황: 문제점 배너에 추적성 갭을 칩으로 노출한다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('미추적 요구 8')).toBeInTheDocument();
    expect(screen.getByText('ASIL 미상 12')).toBeInTheDocument();
    expect(screen.getByText(/⚠ 문제 \d+건/)).toBeInTheDocument();
  });

  it('현황: 추적성 현황(미추적/ASIL 미상 KPI)을 표시한다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    // 추적성 패널 로드(생성 시각으로 데이터 도착 확인) 후 KPI
    expect(await screen.findByText(/생성 시각/)).toBeInTheDocument();
    const kpi = screen.getByText('ASIL 시험 미달').closest('.panel');
    expect(within(kpi).getByText('2')).toBeInTheDocument();
  });

  it('단일 뷰: 빌드 타임라인 + PRQA 트렌드가 함께 표시된다(세그먼트 없음)', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('#125')).toBeInTheDocument();
    expect(screen.getByText(/PRQA 정적분석 빌드별 트렌드/)).toBeInTheDocument();
    expect(screen.getByText(/빌드별 변경 영향 \(전체 빌드\)/)).toBeInTheDocument();
  });

  it('빌드 행 클릭 시 localStorage focus + __detailSection("impact")', async () => {
    const user = userEvent.setup();
    window.__detailSection = vi.fn();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const row = (await screen.findByText('#125')).closest('tr');
    await user.click(row);
    expect(window.__detailSection).toHaveBeenCalledWith('impact');
    const stored = JSON.parse(localStorage.getItem('devops_v2_impact_focus_build'));
    expect(stored.build_number).toBe(125);
    delete window.__detailSection;
  });

  it('커버리지 미측정 빌드는 "커버리지 미측정"으로 표시(ISO 정직성)', async () => {
    mockTimeline = {
      ok: true, entry_id: 'kj',
      rows: [{
        run_id: 'r-um', timestamp: '2026-03-24T10:00:00', build_number: 200, build_revision: '1060',
        base_ref: '1018', changed_files_count: 1, changed_functions_count: 1,
        impact_counts: { direct: 1, indirect_1hop: 0, indirect_2hop: 0 },
        max_asil: 'QM', max_asil_bucket: 'unknown', mcdc_required: false,
        auto_docs: 1, flag_docs: 0, coverage_regressed: 0, coverage_unmeasured_safety: 0,
        coverage_measured: false, partial_failure: false, before_payload_unavailable: false,
      }],
      rollup: { analyzed_build_count: 1, distinct_changed_functions: 1, asil_distribution: {}, revision_range: {} },
    };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const row = (await screen.findByText('#200')).closest('tr');
    expect(within(row).getByText('커버리지 미측정')).toBeInTheDocument();
    expect(within(row).queryByText('정상')).toBeNull();
  });

  it('추적성 캐시 없으면 자동생성 시도 — 실패 시 사유 표시', async () => {
    mockTrace = { has_data: false };
    mockTraceGenSuccess = false;  // buildTraceMatrix ok:false (no_requirements)
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText(/SRS 요구사항을 추출하지 못함/)).toBeInTheDocument();
  });

  it('추적성 캐시 없으면 자동생성 → 성공 시 캐시 재조회로 표시(영속)', async () => {
    mockTrace = { has_data: false };
    mockTraceGenSuccess = true;  // buildTraceMatrix ok:true → 재조회에서 has_data:true
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    // 자동생성 후 재조회로 추적성 현황(생성 시각·미추적 KPI) 표시
    expect(await screen.findByText(/생성 시각/)).toBeInTheDocument();
    expect(screen.getByText('미추적 요구 8')).toBeInTheDocument();
  });

  it('전체 빌드 병합: Jenkins 목록의 미분석 빌드를 "미분석" 행으로 표시(비차단)', async () => {
    mockCfg = { username: 'u', token: 't', verifyTls: true };
    // timeline은 #125만 분석. Jenkins 목록엔 126(미분석)+125(분석).
    mockAllBuilds = [
      { number: 126, result: 'SUCCESS', timestamp: 1700000000000, revision: '1055' },
      { number: 125, result: 'SUCCESS', timestamp: 1699000000000, revision: '1053' },
    ];
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('#126')).toBeInTheDocument();  // 미분석 빌드 병합됨
    expect(screen.getByText('#125')).toBeInTheDocument();          // 분석 빌드 유지
    const row126 = screen.getByText('#126').closest('tr');
    expect(within(row126).getByText('미분석')).toBeInTheDocument();
  });
});
