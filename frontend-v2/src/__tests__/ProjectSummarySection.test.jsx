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
let mockPrqaDelta;
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
    if (u.includes('prqa-delta')) return Promise.resolve(mockPrqaDelta);
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
const { buildTraceMatrix } = await import('../traceMatrix.js');
const { post: mockPost } = await import('../api.js');

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
    { build_number: 122, violations: 558, diagnostics: 496, compliance: 92, violations_delta: null, diagnostics_delta: null },
    { build_number: 124, violations: 552, diagnostics: 492, compliance: 91, violations_delta: -6, diagnostics_delta: -4 },
    { build_number: 125, violations: 562, diagnostics: 502, compliance: 91, violations_delta: 10, diagnostics_delta: 10 },
  ],
};

describe('ProjectSummarySection (재설계)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTimeline = TIMELINE;
    mockScmVcast = SCMVCAST;
    mockTrace = TRACE;
    mockPrqaTrend = PRQATREND;
    mockPrqaDelta = { ok: true, available: false, reason: 'no_baseline_build' };
    mockTraceGenSuccess = false;
    mockCfg = {};
    mockAllBuilds = [];
    localStorage.clear();
  });

  // ── Phase O: 패널 숨김 + 3그룹 재배치 ──

  it('숨김(사용자 결정): 파이프라인 헬스·정적동적 현황·추적성 현황·테스트 설계는 렌더하지 않는다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);   // 렌더 완료 대기(배너는 유지되는 축)
    expect(screen.queryByText('정적·동적 분석 현황')).toBeNull();
    expect(screen.queryByText('추적성 현황 (SW)')).toBeNull();
    expect(screen.queryByText('6,886/6,886')).toBeNull();       // 정적동적 현황의 UT KPI
    expect(screen.queryByText(/테스트 설계 어드바이저/)).toBeNull();
    expect(screen.queryByTestId('pipeline-health')).toBeNull();
  });

  it('추적성 패널을 숨겨도 trace는 계속 조회한다(문제점 배너·AI 인사이트 근거)', async () => {
    // ⚠ 회귀 방지 핵심: 패널만 숨기고 fetch까지 지우면 배너가 조용히 비어 '이상 없음'으로 위장된다.
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('미추적 요구 8')).toBeInTheDocument();
    expect(screen.getByText('ASIL 미상 12')).toBeInTheDocument();
    expect(screen.getByText(/⚠ 문제 \d+건/)).toBeInTheDocument();
    expect(mockPost.mock.calls.some(([u]) => String(u).includes('uds/trace-summary'))).toBe(true);
  });

  it('3그룹 헤딩(SW 아키텍처 / 소스코드 / 빌드별 변경 영향)을 표시한다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByRole('heading', { name: /SW 아키텍처/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /소스코드/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /빌드별 변경 영향/ })).toBeInTheDocument();
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

  it('추적성 캐시 없으면 자동생성 → 성공 시 캐시 재조회로 반영(영속)', async () => {
    mockTrace = { has_data: false };
    mockTraceGenSuccess = true;  // buildTraceMatrix ok:true → 재조회에서 has_data:true
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    // 추적성 패널은 숨김이므로 관측 지점은 배너 — 재조회 성공 시 갭 칩이 뜨고 '미생성' 경고는 사라진다.
    expect(await screen.findByText('미추적 요구 8')).toBeInTheDocument();
    expect(screen.queryByText(/추적성 미생성/)).toBeNull();
  });

  it('커버리지 게이트: 미달(fail)이면 문제점 배너에 danger 칩(소문자 계약 회귀 방지)', async () => {
    mockTrace = { ...TRACE, coverage_pct: 45 };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('커버리지 미달 45%')).toBeInTheDocument();
  });

  it('커버리지 게이트: 주의(warn) 구간 칩', async () => {
    mockTrace = { ...TRACE, coverage_pct: 65 };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('커버리지 주의 65%')).toBeInTheDocument();
  });

  it('커버리지 게이트: null이면 칩 없음(증거부재≠미달 — 허위 0% 경보 금지)', async () => {
    mockTrace = { ...TRACE, coverage_pct: null };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('미추적 요구 8')).toBeInTheDocument(); // 배너 자체는 정상
    expect(screen.queryByText(/커버리지 미달/)).toBeNull();
    expect(screen.queryByText(/커버리지 주의/)).toBeNull();
  });

  it('W2: 동일 빌드 재분석 시 최신 분석 행을 채택한다(구 분석이 최신을 가리지 않음)', async () => {
    const mk = (runId, ts, fns) => ({
      run_id: runId, timestamp: ts, build_number: 125, build_revision: '1053',
      base_ref: '1018', changed_files_count: 1, changed_functions_count: fns,
      impact_counts: { direct: 1, indirect_1hop: 0, indirect_2hop: 0 },
      max_asil: 'QM', max_asil_bucket: 'unknown', mcdc_required: false,
      auto_docs: 1, flag_docs: 0, coverage_regressed: 0, coverage_unmeasured_safety: 0,
      coverage_measured: true, partial_failure: false, before_payload_unavailable: false,
    });
    // rows는 최신순 — 재분석(신, 함수 9)과 원분석(구, 함수 5)이 같은 #125.
    mockTimeline = {
      ok: true, entry_id: 'kj',
      rows: [mk('r-new', '2026-03-24T13:00:00', 9), mk('r-old', '2026-03-24T12:00:00', 5)],
      rollup: { analyzed_build_count: 2, distinct_changed_functions: 9, asil_distribution: {}, revision_range: {} },
    };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const cells = await screen.findAllByText('#125');
    expect(cells).toHaveLength(1); // 중복 행 없음
    const row = cells[0].closest('tr');
    expect(within(row).getByText('9')).toBeInTheDocument(); // 최신 분석 값
  });

  it('W1: analysisResult가 다른 Job의 것이면 추적성 자동생성을 보류한다(오귀속 차단)', async () => {
    mockTrace = { has_data: false };
    mockTraceGenSuccess = true; // 생성이 허용됐다면 성공했을 상황
    const staleResult = { ...RESULT, jobUrl: 'http://jenkins/job/OTHER_JOB/' };
    render(<ProjectSummarySection job={JOB} analysisResult={staleResult} />);
    expect(await screen.findByText(/자동 생성 보류/)).toBeInTheDocument();
    expect(buildTraceMatrix).not.toHaveBeenCalled();
  });

  it('타임라인 Δ위반 컬럼: 트렌드 delta를 빌드별로 조인해 +N 표기, 결측은 —', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const row = (await screen.findByText('#125')).closest('tr');
    expect(within(row).getByText('+10')).toBeInTheDocument();
  });

  // 파이프라인 헬스 스트립은 Phase O에서 숨김(SHOW.pipelineHealth=false) — 컴포넌트 자체의
  // 노드/딥링크 동작은 PipelineHealthStrip 전용 테스트가 계속 검증한다.
  it('파이프라인 헬스 스트립은 숨김 상태다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    expect(screen.queryByText(/파이프라인 헬스/)).toBeNull();
    expect(screen.queryByText('SDS 설계')).toBeNull();
  });

  it('정적분석 위반 상세: kpis.prqa top_rules/top_files를 추가 fetch 없이 렌더 + 미귀속 각주', async () => {
    const result = {
      ...RESULT,
      reportData: {
        kpis: {
          ...RESULT.reportData.kpis,
          prqa: {
            ...RESULT.reportData.kpis.prqa,
            top_rules: [{ rule: 'Rule-8.6', count: 120 }, { rule: 'Rule-2.1', count: 44 }],
            top_files: [{ file: 'foo.c', path: 'APP/src/foo.c', count: 31 }],
            violations_attributed_total: 550,  // 562 중 550만 귀속 → 각주
          },
        },
      },
    };
    render(<ProjectSummarySection job={JOB} analysisResult={result} />);
    expect(await screen.findByText('정적분석 위반 상세 (PRQA/MISRA)')).toBeInTheDocument();
    expect(screen.getByText('Rule-8.6')).toBeInTheDocument();
    expect(screen.getByText('foo.c')).toBeInTheDocument();
    expect(screen.getByText(/550건만 파일에 귀속/)).toBeInTheDocument();
  });

  it('드릴다운 chevron: 클릭 시 prqa-delta 조회 + impact 핸드오프는 발생하지 않음(stopPropagation)', async () => {
    const user = userEvent.setup();
    window.__detailSection = vi.fn();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const row = (await screen.findByText('#125')).closest('tr');
    await user.click(within(row).getByRole('button', { name: /펼치기/ }));
    // 확장 패널이 available:false reason을 한국어로 노출
    expect(await screen.findByText(/비교할 이전 캐시 빌드가 없습니다/)).toBeInTheDocument();
    const { post } = await import('../api.js');
    expect(post).toHaveBeenCalledWith('/api/jenkins/prqa-delta', expect.objectContaining({ build_number: 125, scm_id: 'kj' }));
    expect(window.__detailSection).not.toHaveBeenCalled(); // 행 클릭 핸드오프 미발화
    expect(localStorage.getItem('devops_v2_impact_focus_build')).toBeNull();
    delete window.__detailSection;
  });

  it('Phase E: 서버 캐시 병합 행(analyzed:false, cached:true)은 "캐시 · 미분석" 배지 + 요청에 cache_root 동반', async () => {
    mockTimeline = {
      ...TIMELINE,
      cache_merge: { attempted: true, merged: 1, added: 1 },
      rows: [
        {
          run_id: '__cached_126', analyzed: false, cached: true, build_number: 126,
          build_revision: '1075', build_result: 'SUCCESS', timestamp: '2026-07-24T13:00:11',
          impact_counts: {}, max_asil_bucket: 'unknown', coverage_measured: false,
        },
        ...TIMELINE.rows,
      ],
    };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const row = (await screen.findByText('#126')).closest('tr');
    expect(within(row).getByText('캐시 · 미분석')).toBeInTheDocument();
    const { api } = await import('../api.js');
    const timelineCall = api.mock.calls.find(([u]) => String(u).includes('build-timeline'));
    expect(String(timelineCall[0])).toContain('cache_root=');
  });

  it('Phase E: Jenkins 병합이 캐시 행을 analyzed로 승격하지 않는다', async () => {
    mockCfg = { username: 'u', token: 't', verifyTls: true };
    mockTimeline = {
      ...TIMELINE,
      rows: [{
        run_id: '__cached_126', analyzed: false, cached: true, build_number: 126,
        build_revision: '1075', build_result: null, timestamp: '',
        impact_counts: {}, max_asil_bucket: 'unknown', coverage_measured: false,
      }],
    };
    mockAllBuilds = [{ number: 126, result: 'SUCCESS', timestamp: 1700000000000, revision: '1075' }];
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    const row = (await screen.findByText('#126')).closest('tr');
    // Jenkins 목록에 있어도 분석된 것이 아니다 — 캐시·미분석 유지 + 결과는 보강됨.
    expect(within(row).getByText('캐시 · 미분석')).toBeInTheDocument();
    expect(within(row).getByText('SUCCESS')).toBeInTheDocument();
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
