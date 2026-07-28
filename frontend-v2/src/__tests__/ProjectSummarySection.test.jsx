/**
 * ProjectSummarySection — 서브탭 셸 단위 테스트.
 * - 서브탭 밖(항상 표시): 헤더 + 문제점 배너 — 어느 탭에 있든 "지금 괜찮은가"가 보여야 한다
 * - 서브탭 4개: 개요 / 아키텍처 / 소스코드 / 빌드 변경 (안 연 탭은 마운트 안 함)
 * - 조회·상태는 전부 부모 소유 — 서브탭으로 내리면 그 탭을 안 연 사용자에게 배너가 조용히 빈다
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
let mockSrcBuilds;
let mockSrcBuildsFail;   // 설정하면 cached-builds-meta 가 거부한다
let mockCellGate;        // 설정하면 change-matrix/cell 이 이 promise 뒤에 해소된다(진행 표시 관찰용)
let mockMatrix;
let mockBackfill;

vi.mock('../api.js', () => ({
  api: vi.fn((url) => (String(url).includes('build-timeline') ? Promise.resolve(mockTimeline) : Promise.resolve({}))),
  post: vi.fn((url) => {
    const u = String(url);
    if (u.includes('scm-vcast-summary')) return Promise.resolve(mockScmVcast);
    if (u.includes('trace-summary')) return Promise.resolve(mockTrace);
    if (u.includes('prqa-trend')) return Promise.resolve(mockPrqaTrend);
    if (u.includes('prqa-delta')) return Promise.resolve(mockPrqaDelta);
    if (u.includes('/api/jenkins/builds')) return Promise.resolve(mockAllBuilds);
    if (u.includes('cached-builds-meta')) {
      return mockSrcBuildsFail ? Promise.reject(new Error(mockSrcBuildsFail)) : Promise.resolve(mockSrcBuilds);
    }
    if (u.includes('change-matrix/cell')) {
      const done = { ok: true, target: { build_number: 125 }, shared_with_builds: [125] };
      return mockCellGate ? mockCellGate.then(() => done) : Promise.resolve(done);
    }
    if (u.includes('change-matrix')) return Promise.resolve(mockMatrix);
    if (u.includes('sync-backfill')) return Promise.resolve(mockBackfill);
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
// ⚠ archMetricsCache 는 모듈 레벨 싱글톤이라 파일 안 테스트끼리 오염된다 —
//   아키텍처 서브탭을 여는 테스트의 응답이 뒤 테스트로 샌다.
const { clearArchMetricsCache } = await import('../archMetricsCache.js');

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

/**
 * 서브탭 이동 헬퍼 — 예전엔 그룹 헤딩(`role="heading"`)이 렌더 동기화 지점이었지만,
 * 이제 그 자리가 탭 버튼이라 **탭을 열어야 그 안의 패널이 마운트된다**(lazy).
 */
async function gotoSub(user, label) {
  await user.click(screen.getByRole('tab', { name: label }));
}

describe('ProjectSummarySection (서브탭 재구성)', () => {
  beforeEach(() => {
    clearArchMetricsCache();
    vi.clearAllMocks();
    mockTimeline = TIMELINE;
    mockScmVcast = SCMVCAST;
    mockTrace = TRACE;
    mockPrqaTrend = PRQATREND;
    mockPrqaDelta = { ok: true, available: false, reason: 'no_baseline_build' };
    mockTraceGenSuccess = false;
    mockCfg = {};
    mockAllBuilds = [];
    mockSrcBuildsFail = '';
    mockCellGate = null;
    mockSrcBuilds = { ok: true, available: true, builds: [
      { build_number: 125, has_source: true, source_pinned: true, timestamp_iso: '2026-07-24T13:00:11', revision: '1075' },
      { build_number: 122, has_source: true, source_pinned: true, timestamp_iso: '2026-06-25T13:00:00', revision: '1053' },
    ] };
    mockBackfill = { ok: true, available: true, job_id: 'jid', total: 10 };
    mockMatrix = {
      ok: true, available: true, level: 'files',
      baseline: { build_number: 122, timestamp_iso: '2026-06-25T13:00:00', revision: '1053' },
      rows: [
        { row_key: 'b125', build_number: 125, build_result: 'SUCCESS', timestamp_iso: '2026-07-24T13:00:11',
          revision: '1075', snapshot_group: { count: 1, members: [125] }, is_baseline: false,
          identical_to_baseline: false, files: { added: 0, deleted: 0, modified: 1, changed: 1, unchanged: 146 },
          functions: null, asil: null, function_state: { state: 'not_computed', reason: 'level_files' }, cell_id: 'a__b' },
        { row_key: 'b122', build_number: 122, is_baseline: true, snapshot_group: { count: 1, members: [122] },
          files: null, functions: null, asil: null, function_state: { state: 'baseline' } },
      ],
      pending_cells: [{ cell_id: 'a__b', target_build: 125 }],
      snapshot_groups: [], stats: { rows: 2 },
    };
    localStorage.clear();
  });

  // ── 서브탭 구조 ──

  it('숨김(사용자 결정): 파이프라인 헬스·정적동적 현황·추적성 현황·테스트 설계는 렌더하지 않는다', async () => {
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);   // 렌더 완료 대기(배너는 유지되는 축)
    // 개요 탭(기본): 정적동적·추적성 현황 패널은 SHOW 플래그로 숨김
    expect(screen.queryByText('정적·동적 분석 현황')).toBeNull();
    expect(screen.queryByText('추적성 현황 (SW)')).toBeNull();
    expect(screen.queryByText('6,886/6,886')).toBeNull();       // 정적동적 현황의 UT KPI
    // 소스코드 탭: 테스트 설계 어드바이저는 SHOW.testDesign=false
    await gotoSub(user, '소스코드');
    expect(screen.queryByText(/테스트 설계 어드바이저/)).toBeNull();
  });

  it('서브탭 4개를 tablist로 제공하고 기본은 개요다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    expect(screen.getByRole('tablist', { name: '프로젝트 분석 영역' })).toBeInTheDocument();
    for (const label of ['개요', '아키텍처', '소스코드', '빌드 변경']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: '개요' })).toHaveAttribute('aria-selected', 'true');
  });

  it('키보드는 **수동 활성화** — 화살표는 포커스만 옮기고 탭을 마운트하지 않는다', async () => {
    // ⚠ 자동 활성화면 →→→ 로 지나가는 것만으로 아키텍처·소스코드가 마운트되어
    //   lazy 로 16→6 으로 줄인 요청이 키보드 사용자에겐 통째로 복구된다.
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    const overview = screen.getByRole('tab', { name: '개요' });
    expect(overview).toHaveAttribute('tabindex', '0');

    overview.focus();
    await user.keyboard('{ArrowRight}');
    // 포커스와 roving tabIndex 는 옮겨가되, 선택은 그대로 개요다
    expect(screen.getByRole('tab', { name: '아키텍처' })).toHaveFocus();
    expect(screen.getByRole('tab', { name: '아키텍처' })).toHaveAttribute('tabindex', '0');
    expect(overview).toHaveAttribute('aria-selected', 'true');
    expect(mockPost.mock.calls.some(([u]) => String(u).includes('architecture-metrics'))).toBe(false);

    // Enter 로 비로소 활성화
    await user.keyboard('{Enter}');
    expect(screen.getByRole('tab', { name: '아키텍처' })).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: '빌드 변경' })).toHaveFocus();
    await user.keyboard(' ');
    expect(screen.getByRole('tab', { name: '빌드 변경' })).toHaveAttribute('aria-selected', 'true');
  });

  it('안 연 서브탭은 마운트하지 않는다(첫 진입 요청 폭주 차단)', async () => {
    // ⚠ 이 단언이 재구성의 목적을 고정한다 — 예전엔 진입 즉시 11개 패널이 전부 조회했다.
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    const called = (frag) => mockPost.mock.calls.some(([u]) => String(u).includes(frag));
    expect(called('architecture-metrics')).toBe(false);
    expect(called('change-matrix')).toBe(false);
    expect(called('prqa-rule-trend')).toBe(false);
    expect(called('quality-detail')).toBe(false);

    await gotoSub(user, '빌드 변경');
    await vi.waitFor(() => { expect(called('change-matrix')).toBe(true); });
    // 다른 탭 것은 여전히 안 나간다
    expect(called('architecture-metrics')).toBe(false);
  });

  it('keep-alive: 탭을 되돌아와도 재조회하지 않는다', async () => {
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    await vi.waitFor(() => {
      expect(mockPost.mock.calls.some(([u]) => String(u).includes('change-matrix'))).toBe(true);
    });
    const before = mockPost.mock.calls.filter(([u]) => String(u).includes('change-matrix')).length;
    await gotoSub(user, '개요');
    await gotoSub(user, '빌드 변경');
    expect(mockPost.mock.calls.filter(([u]) => String(u).includes('change-matrix')).length).toBe(before);
  });

  it('진행 중 작업은 서브탭 위에 뜨고, 그 탭으로 가는 버튼이 붙는다', async () => {
    // ⚠ 진행 표시가 서브탭 안에만 있으면 탭을 옮기는 순간 표시도 중지 버튼도 사라진다
    //   — 작업은 계속 서버를 때리는데 화면은 "아무 일도 안 일어나는 중"이 된다.
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    await screen.findByRole('heading', { name: '빌드별 변경 영향' });
    // 셀 계산이 끝나기 전 상태를 관찰해야 하므로 응답을 게이트로 잡아 둔다
    let release;
    mockCellGate = new Promise((r) => { release = r; });
    await user.click(await screen.findByText(/함수 축 계산 \(1건\)/));

    // 개요로 옮겨도 진행 표시가 남는다.
    // ⚠ 패널 자체 표시(display:none 이지만 DOM 에는 있다)와 상단 스트립 둘 다 잡히므로,
    //   스트립에만 있는 '이동' 버튼으로 식별한다.
    await gotoSub(user, '개요');
    const goBtn = await screen.findByRole('button', { name: /빌드 변경\(으\)로/ });
    expect(goBtn).toBeInTheDocument();
    expect(within(goBtn.parentElement).getByText(/함수 축 계산 중/)).toBeInTheDocument();

    // 끝나면 스트립이 사라진다(영구 잔존 금지)
    release();
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: /빌드 변경\(으\)로/ })).toBeNull());
  });

  it('문제점 칩은 근거 화면으로 이동한다(죽은 라벨 금지)', async () => {
    // "ASIL 시험 미달 2"를 읽고도 어디를 봐야 하는지 화면이 말하지 않으면 사용자가 탭을 뒤진다.
    const user = userEvent.setup();
    window.__detailSection = vi.fn();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await user.click(await screen.findByRole('button', { name: /미추적 요구 8 — 요구사항 커버리지/ }));
    expect(window.__detailSection).toHaveBeenCalledWith('srssds', undefined);
    delete window.__detailSection;
  });

  it('같은 섹션이 근거면 딥링크 대신 서브탭만 바꾼다', async () => {
    const user = userEvent.setup();
    window.__detailSection = vi.fn();
    mockSrcBuilds = { ok: true, available: true, builds: [
      { build_number: 125, has_source: true, source_pinned: true },
      { build_number: 122, has_source: true, source_pinned: false },
    ] };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await user.click(await screen.findByRole('button', { name: /스냅샷 미고정 빌드 1 — 빌드 변경 탭/ }));
    expect(window.__detailSection).not.toHaveBeenCalled();
    expect(screen.getByRole('tab', { name: '빌드 변경' })).toHaveAttribute('aria-selected', 'true');
    delete window.__detailSection;
  });

  it('활성 서브탭을 부모에 알린다(breadcrumb 동기화)', async () => {
    const user = userEvent.setup();
    const onSubChange = vi.fn();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} onSubChange={onSubChange} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    expect(onSubChange).toHaveBeenCalledWith('overview', '개요');
    await gotoSub(user, '소스코드');
    expect(onSubChange).toHaveBeenCalledWith('source', '소스코드');
  });

  it('initialSub로 들어오면 그 서브탭에 착지한다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} initialSub="arch" />);
    await screen.findByText(/⚠ 문제 \d+건/);
    expect(screen.getByRole('tab', { name: '아키텍처' })).toHaveAttribute('aria-selected', 'true');
  });

  it('캐시 빌드 목록 조회 실패를 로딩/0으로 위장하지 않는다', async () => {
    // ⚠ 실패하면 아래 두 패널이 통째로 비는데, 사유가 없으면 "빌드가 없는 것"으로 읽힌다.
    const user = userEvent.setup();
    mockSrcBuildsFail = 'boom';
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('조회 실패')).toBeInTheDocument();   // 개요 KPI sub
    await gotoSub(user, '빌드 변경');
    expect(await screen.findByText(/캐시 빌드 목록 조회 실패 — boom/)).toBeInTheDocument();
  });

  it('캐시 빌드 조회 실패를 배너가 고지한다 — "이상 없음" 초록 위장 금지', async () => {
    // ⚠ 이 실패는 `스냅샷 미고정 빌드` 칩의 데이터 출처를 죽인다 → unpinnedCount 가 0으로
    //   붕괴해 문제 0건이 되고, 헤더 pill 이 초록 "이상 없음"을 낸다(증거부재 ≠ 정상).
    mockSrcBuildsFail = 'boom';
    mockTrace = { ...TRACE, uncovered: 0, asil_gap_count: 0, asil_unknown_count: 0,
      integrity_collision_count: 0, integrity_dangling_count: 0, coverage_pct: 95, summary_raw: {} };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText(/캐시 빌드 목록 조회 실패 — 스냅샷 미고정 여부를 판정할 수 없습니다/)).toBeInTheDocument();
  });

  it('PRQA 트렌드 실패가 개요 델타·매트릭스 Δ열에도 사유로 전달된다', async () => {
    // 부모만 알고 자식에 안 넘기면 "변화 없음"과 "못 읽음"이 구분 불가가 된다.
    const user = userEvent.setup();
    const { post } = await import('../api.js');
    const orig = post.getMockImplementation();
    post.mockImplementation((url, body) => (String(url).includes('prqa-trend')
      ? Promise.reject(new Error('trend down')) : orig(url, body)));
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('직전 빌드 대비 — 트렌드 조회 실패')).toBeInTheDocument();
    await gotoSub(user, '빌드 변경');
    expect(await screen.findByText(/Δ위반 ⚠미조회/)).toBeInTheDocument();
    post.mockImplementation(orig);
  });

  it('미고정 스냅샷은 탭을 안 열어도 문제점 배너에 뜬다', async () => {
    // 경고가 '빌드 변경' 탭 안에만 있으면 lazy 라 열기 전엔 안 보인다 —
    // '변화 0'을 코드 미변경으로 오독하게 만드는 축이라 배너로 올린다.
    mockSrcBuilds = { ok: true, available: true, builds: [
      { build_number: 125, has_source: true, source_pinned: true },
      { build_number: 122, has_source: true, source_pinned: false },
    ] };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('스냅샷 미고정 빌드 1')).toBeInTheDocument();
  });

  it('개요는 새 조회 없이 이미 받은 값으로 KPI를 만든다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    expect(screen.getByText('추적 커버리지')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();          // trace.coverage_pct
    expect(screen.getByText('562')).toBeInTheDocument();          // prqa.rule_violation_count
    expect(screen.getByText('823')).toBeInTheDocument();          // code_metrics.functions
    // 개요 전용 엔드포인트는 없다 — 부모 5개 + AI probe 뿐
    const urls = mockPost.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes('/api/summary/') && !u.includes('ai-insight'))).toBe(false);
  });

  it('패널 제목은 role="heading"으로 잡힌다(스크린리더 점프 복원)', async () => {
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    expect(await screen.findByRole('heading', { name: '빌드별 변경 영향' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '베이스라인 → 최신 변화' })).toBeInTheDocument();
  });

  it('패널은 헤더만 남기고 접을 수 있다(aria-expanded 반전)', async () => {
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    const btn = await screen.findByRole('button', { name: '빌드별 변경 영향 접기' });
    expect(btn).toHaveAttribute('aria-expanded', 'true');
    await user.click(btn);
    expect(screen.getByRole('button', { name: '빌드별 변경 영향 펼치기' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('추적성 패널을 숨겨도 trace는 계속 조회한다(문제점 배너·AI 인사이트 근거)', async () => {
    // ⚠ 회귀 방지 핵심: 패널만 숨기고 fetch까지 지우면 배너가 조용히 비어 '이상 없음'으로 위장된다.
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('미추적 요구 8')).toBeInTheDocument();
    expect(screen.getByText('ASIL 미상 12')).toBeInTheDocument();
    expect(screen.getByText(/⚠ 문제 \d+건/)).toBeInTheDocument();
    expect(mockPost.mock.calls.some(([u]) => String(u).includes('uds/trace-summary'))).toBe(true);
  });

  it('구 3그룹은 서브탭이 됐다 — 헤딩이 아니라 탭으로 이동한다', async () => {
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '아키텍처');
    expect(screen.getByRole('tab', { name: '아키텍처' })).toHaveAttribute('aria-selected', 'true');
    await gotoSub(user, '소스코드');
    expect(await screen.findByRole('heading', { name: 'PRQA 정적분석 빌드별 트렌드' })).toBeInTheDocument();
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


  it('W1: analysisResult가 다른 Job의 것이면 추적성 자동생성을 보류한다(오귀속 차단)', async () => {
    mockTrace = { has_data: false };
    mockTraceGenSuccess = true; // 생성이 허용됐다면 성공했을 상황
    const staleResult = { ...RESULT, jobUrl: 'http://jenkins/job/OTHER_JOB/' };
    render(<ProjectSummarySection job={JOB} analysisResult={staleResult} />);
    expect(await screen.findByText(/자동 생성 보류/)).toBeInTheDocument();
    expect(buildTraceMatrix).not.toHaveBeenCalled();
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
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={result} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '소스코드');
    expect(await screen.findByRole('heading', { name: '정적분석 위반 상세 (PRQA/MISRA)' })).toBeInTheDocument();
    expect(screen.getByText('Rule-8.6')).toBeInTheDocument();
    expect(screen.getByText('foo.c')).toBeInTheDocument();
    expect(screen.getByText(/550건만 파일에 귀속/)).toBeInTheDocument();
  });




  it('표는 change-log를 안 써도 rollup 배너는 그대로 발화한다(침묵 회귀 고정)', async () => {
    // ⚠ 이 테스트가 계획의 최대 위험을 막는다: "표가 timeline을 안 쓰니 fetch도 지우자"는
    //   다음 사람의 합리적 판단이 문제점 배너를 조용히 비운다.
    mockTimeline = {
      ...TIMELINE,
      rollup: { ...TIMELINE.rollup, cumulative_flag_docs: 4, cumulative_coverage_regressed: 2 },
    };
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('MC/DC 회귀 2')).toBeInTheDocument();
    expect(screen.getByText('검토 대기 문서 4')).toBeInTheDocument();
    // build-timeline 조회 자체가 살아 있어야 한다(rollup의 유일한 출처).
    const { api } = await import('../api.js');
    expect(api.mock.calls.some(([u]) => String(u).includes('build-timeline'))).toBe(true);
    // 헤더 리비전 범위도 rollup 소비처다.
    expect(screen.getByText(/r1018 → r1053/)).toBeInTheDocument();
    // 구 표의 잡 결과 축은 사라졌다.
    expect(screen.queryByText('누적 변경 함수')).toBeNull();
    expect(screen.queryByRole('columnheader', { name: '재생성/검토' })).toBeNull();
  });

  it('빌드별 변경 영향은 소스 스냅샷 비교로 그린다 — change-log 행은 표에 없다', async () => {
    // 구 표는 build_number 없는 change-log 레코드가 "#—" 행으로 쌓였다(실측 89행 중 88행).
    mockTimeline = {
      ...TIMELINE,
      rows: [
        { run_id: 'old1', timestamp: '2026-05-01T00:00:00', changed_files_count: 27, changed_functions_count: 640 },
        ...TIMELINE.rows,
      ],
    };
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    await screen.findByRole('heading', { name: '빌드별 변경 영향' });
    expect(screen.queryByText('#—')).toBeNull();
    // 매트릭스는 change-matrix를 조회한다(build-timeline이 아니라).
    await vi.waitFor(() => {
      expect(mockPost.mock.calls.some(([u]) => String(u).includes('change-matrix'))).toBe(true);
    });
  });

  it('베이스라인은 두 패널이 공유한다 — cached-builds-meta는 부모가 1회만 조회', async () => {
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    await screen.findByRole('heading', { name: '빌드별 변경 영향' });
    await vi.waitFor(() => {
      expect(mockPost.mock.calls.filter(([u]) => String(u).includes('cached-builds-meta')).length).toBe(1);
    });
    // 매트릭스 요청의 baseline_build가 목록의 최고령(#122)과 일치한다.
    await vi.waitFor(() => {
      const call = mockPost.mock.calls.find(([u]) => String(u).endsWith('/api/summary/change-matrix'));
      expect(call?.[1]).toMatchObject({ baseline_build: 122 });
    });
  });

  it('행 클릭이 변경 영향 평가 탭으로 이동하지 않는다(핸드오프 제거)', async () => {
    window.__detailSection = vi.fn();
    const user = userEvent.setup();
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await screen.findByText(/⚠ 문제 \d+건/);
    await gotoSub(user, '빌드 변경');
    await screen.findByRole('heading', { name: '빌드별 변경 영향' });
    expect(window.__detailSection).not.toHaveBeenCalled();
    expect(localStorage.getItem('devops_v2_impact_focus_build')).toBeNull();
    delete window.__detailSection;
  });

  // ── 과거 빌드 가져오기 옵션 (스냅샷 고정 · 비교 캐시 자동 생성) ───────────
  // 근본 결함: 고정이 없으면 과거 빌드가 전부 '받아온 날의 HEAD 트리'라 비교가 무의미해진다
  // (실측 33빌드 중 26개 동일 트리 → 변화 0 + ASIL 함수 변경 침묵).

  describe('과거 빌드 가져오기 옵션', () => {
    const startBackfill = async (user) => {
      await user.click(screen.getByRole('button', { name: '과거 빌드 가져오기' }));
      return vi.waitFor(() => {
        const call = mockPost.mock.calls.find(([u]) => String(u).includes('sync-backfill'));
        expect(call).toBeTruthy();
        return call[1];
      });
    };

    it('두 토글이 기본 ON이고 그대로 요청에 실린다', async () => {
      const user = userEvent.setup();
      render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
      await screen.findByText(/⚠ 문제 \d+건/);
      await gotoSub(user, '빌드 변경');
      await screen.findByRole('heading', { name: '빌드별 변경 영향' });
      const pin = screen.getByLabelText(/스냅샷을 빌드 시점 revision으로 고정/);
      const warm = screen.getByLabelText(/비교 캐시\(함수 축\) 자동 생성/);
      expect(pin).toBeChecked();
      expect(warm).toBeChecked();

      const body = await startBackfill(user);
      expect(body).toMatchObject({ pin_source: true, warm_matrix: true });
    });

    it('비교 캐시는 화면에서 고른 베이스라인으로 만든다(기준 불일치 = 캐시 전량 미스)', async () => {
      const user = userEvent.setup();
      render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
      await screen.findByText(/⚠ 문제 \d+건/);
      await gotoSub(user, '빌드 변경');
      await screen.findByRole('heading', { name: '빌드별 변경 영향' });
      await vi.waitFor(() => {
        expect(mockPost.mock.calls.some(([u]) => String(u).endsWith('/api/summary/change-matrix'))).toBe(true);
      });
      const body = await startBackfill(user);
      // 매트릭스가 쓰는 기준과 동일해야 한다(목록 최고령 #122)
      expect(body.baseline_build).toBe(122);
    });

    it('토글을 끄면 꺼진 채로 전달된다', async () => {
      const user = userEvent.setup();
      render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
      await screen.findByText(/⚠ 문제 \d+건/);
      await gotoSub(user, '빌드 변경');
      await screen.findByRole('heading', { name: '빌드별 변경 영향' });
      await user.click(screen.getByLabelText(/스냅샷을 빌드 시점 revision으로 고정/));
      await user.click(screen.getByLabelText(/비교 캐시\(함수 축\) 자동 생성/));
      const body = await startBackfill(user);
      expect(body).toMatchObject({ pin_source: false, warm_matrix: false });
    });

    it('가져올 빌드 개수를 선택하면 count로 전달된다', async () => {
      const user = userEvent.setup();
      render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
      await screen.findByText(/⚠ 문제 \d+건/);
      await gotoSub(user, '빌드 변경');
      await screen.findByRole('heading', { name: '빌드별 변경 영향' });
      await user.selectOptions(screen.getByLabelText(/가져올 빌드/), '30');
      const body = await startBackfill(user);
      expect(body.count).toBe(30);
    });

    it('고정 안 된 캐시 빌드가 있으면 재수집을 안내한다', async () => {
      mockSrcBuilds = { ok: true, available: true, builds: [
        { build_number: 125, has_source: true, source_pinned: true },
        { build_number: 122, has_source: true, source_pinned: false },
        { build_number: 111, has_source: true, source_pinned: false },
      ] };
      const user = userEvent.setup();
      render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
      await screen.findByText(/⚠ 문제 \d+건/);
      await gotoSub(user, '빌드 변경');
      await screen.findByRole('heading', { name: '빌드별 변경 영향' });
      expect(await screen.findByText(/캐시 빌드 2개는 소스가/)).toBeInTheDocument();
    });

    it('전부 고정됐으면 재수집 안내를 내지 않는다', async () => {
      const user = userEvent.setup();
      render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
      await screen.findByText(/⚠ 문제 \d+건/);
      await gotoSub(user, '빌드 변경');
      await screen.findByRole('heading', { name: '빌드별 변경 영향' });
      expect(screen.queryByText(/개는 소스가/)).toBeNull();
    });
  });
});
