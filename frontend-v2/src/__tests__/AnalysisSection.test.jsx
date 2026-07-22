/**
 * AnalysisSection 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-SECTION-ANALYSIS
 * - 커버리지를 유닛테스트(UT)/통합테스트(IT) 패널로 분리(UT+IT 합산 '커버리지 상세'·빌드 Line/Branch 카드 제거)
 * - 유닛/통합테스트 그룹의 SwUTCV/SwITCV 정합성 검증(Coverage ↔ SUTR/SITR)
 * - "VectorCAST 테스트" 패널 렌더링
 * - 정적분석 "코드 규모 (lizard)" 지표 렌더링 (구 '코드 메트릭' 패널 이동)
 * - analysisResult에 coverage 데이터가 있을 때 퍼센트 표시
 * - analysisResult가 없을 때(빈 데이터) 안전하게 렌더링
 * - "함수 복잡도 상세" 불러오기 버튼 존재 확인
 *
 * 외부 의존성:
 * - useJenkinsCfg, useToast: App.jsx mock
 * - api.js (post, defaultCacheRoot): mock
 * - StatusBadge: 실제 컴포넌트 사용 (단순 UI)
 */
import { StrictMode } from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Context mock ──────────────────────────────────────────────────────
const mockToast = vi.fn();

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: {
      baseUrl: 'http://jenkins',
      username: 'user',
      token: 'token',
      cacheRoot: '.cache',
      buildSelector: 'lastSuccessfulBuild',
    },
    update: vi.fn(),
  }),
  useToast: () => mockToast,
}));

// ── api.js mock ───────────────────────────────────────────────────────
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => ''),
}));

const { default: AnalysisSection, saModules } = await import('../components/sections/AnalysisSection.jsx');

/* ── 픽스처 ── */
const makeJob = () => ({
  name: 'test-job',
  url: 'http://jenkins/job/test-job/',
});

const makeAnalysisResult = (overrides = {}) => ({
  cacheRoot: '.cache',
  reportData: {
    coverage: 85,
    kpis: {
      coverage: { line_rate: 0.85, branch_rate: 0.72, ok: true },
      prqa: {},
      code_metrics: {},
      vectorcast: {},
      tests: {},
      scan: {},
      files: {},
      build: {},
    },
    tester: {},
  },
  ...overrides,
});

describe('AnalysisSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  // ── 패널 렌더링 ───────────────────────────────────────────────────

  it('구 ‘코드 커버리지’ 패널과 UT+IT 합산 ‘커버리지 상세’를 제거하고 UT/IT 패널로 분리한다', () => {
    // Arrange & Act — 별도 '코드 커버리지' 패널·유닛테스트 안에 섞이던 'UT+IT 합산 커버리지 상세'를 모두 제거.
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert: 합산 서브섹션 제거 → 커버리지는 유닛/통합테스트 패널로 각각 분리(패널 자체는 항상 존재).
    expect(screen.queryByText('코드 커버리지')).toBeNull();
    expect(screen.queryByText(/커버리지 상세/)).toBeNull();
    expect(screen.getByText('유닛테스트 (Unit Test · VectorCAST UT)')).toBeInTheDocument();
    expect(screen.getByText('통합테스트 (Integration Test · VectorCAST IT)')).toBeInTheDocument();
  });

  it('유닛테스트·통합테스트 패널 제목을 렌더링한다(VectorCAST 분리)', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert: VectorCAST 단일 패널 → UT/IT 2개 섹션으로 분리
    expect(screen.getByText('유닛테스트 (Unit Test · VectorCAST UT)')).toBeInTheDocument();
    expect(screen.getByText('통합테스트 (Integration Test · VectorCAST IT)')).toBeInTheDocument();
  });

  it('정적분석(Helix QAC) 패널 제목을 렌더링한다', () => {
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);
    expect(screen.getByText('정적분석 (Helix QAC · MISRA-C)')).toBeInTheDocument();
  });

  it('code_metrics가 있으면 정적분석에 "코드 규모 (lizard)" 지표를 표시한다', () => {
    // Arrange — 구 '코드 메트릭' 패널은 제거되고 고유 지표가 정적분석으로 이동됨
    const result = makeAnalysisResult();
    result.reportData.kpis.code_metrics = { code_files: 128, functions: 512, nloc: 24300 };

    // Act
    render(<AnalysisSection job={makeJob()} analysisResult={result} />);

    // Assert — lizard 코드 규모 카드가 정적분석 섹션에 표시(소스파일/함수수/NLOC)
    expect(screen.getByText(/코드 규모 \(lizard\)/)).toBeInTheDocument();
    expect(screen.getByText('소스 파일')).toBeInTheDocument();
    expect(screen.getByText('함수 수 (lizard 정적계수)')).toBeInTheDocument();
    expect(screen.getByText('NLOC')).toBeInTheDocument();
    expect(screen.getByText('24,300')).toBeInTheDocument();  // nloc toLocaleString
  });

  it('"함수 복잡도 상세" 패널 제목을 렌더링한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('함수 복잡도 상세')).toBeInTheDocument();
  });

  // ── 커버리지 데이터 표시 ──────────────────────────────────────────

  it('빌드 전체 Line Coverage 카드는 테스트 결과 탭에서 제거됐다(개요 탭과 중복)', () => {
    // Arrange & Act — 빌드 전체 Line/Branch Coverage는 개요(ResultPanel)에만 두고, 여기선 UT/IT 커버리지로 분리.
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert: 빌드 Line Coverage 카드 없음(개요 탭으로 이동).
    expect(screen.queryByText('Line Coverage')).toBeNull();
  });

  it('빌드 전체 Branch Coverage 카드도 테스트 결과 탭에서 표시하지 않는다(개요 탭으로 이동)', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.queryByText('Branch Coverage')).toBeNull();
  });

  // ── 빈 데이터 처리 ────────────────────────────────────────────────

  it('analysisResult가 null이면 오류 없이 렌더링한다', () => {
    // Arrange & Act & Assert — 오류 없이 렌더링되어야 함
    expect(() => {
      render(<AnalysisSection job={makeJob()} analysisResult={null} />);
    }).not.toThrow();
  });

  it('analysisResult가 null이어도 유닛테스트 패널을 표시한다(커버리지 데이터 없으면 상세 생략)', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={null} />);

    // Assert: 커버리지가 유닛테스트 그룹으로 통합됐으므로 패널 자체는 항상 존재(데이터 없으면 상세만 생략).
    expect(screen.getByText('유닛테스트 (Unit Test · VectorCAST UT)')).toBeInTheDocument();
    expect(screen.queryByText('코드 커버리지')).toBeNull();
  });

  it('kpis.coverage가 없으면 Line Coverage 카드를 표시하지 않는다', () => {
    // Arrange
    const result = makeAnalysisResult({
      reportData: {
        coverage: null,
        kpis: { coverage: {}, prqa: {}, code_metrics: {}, vectorcast: {}, tests: {}, scan: {}, files: {}, build: {} },
        tester: {},
      },
    });

    // Act
    render(<AnalysisSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.queryByText('Line Coverage')).toBeNull();
  });

  // ── 복잡도 불러오기 버튼 ─────────────────────────────────────────

  it('"불러오기" 버튼이 존재한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('불러오기')).toBeInTheDocument();
  });

  // ── VectorCAST SCM 경로 폴백(이슈①) ──────────────────────────────
  it('빌드에 VectorCAST가 없고 SCM에 경로가 등록돼 있으면 "SCM 경로에서 불러오기" 버튼을 표시한다', () => {
    // Arrange: tester.vectorcast 비어 있음 + matchedScm.linked_docs.vectorcast 등록
    const result = makeAnalysisResult({
      matchedScm: { id: 'kjpds02', name: 'KJPDS02', linked_docs: { vectorcast: ['U:/PROJ/vcast'] } },
    });

    // Act
    render(<AnalysisSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText('SCM 경로에서 불러오기')).toBeInTheDocument();
  });

  it('빌드에 VectorCAST가 없고 SCM 경로도 없으면 설정 등록 안내를 표시한다', () => {
    // Arrange: vectorcast 비어 있음 + matchedScm 없음
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert: 버튼 대신 설정 안내
    expect(screen.queryByText('SCM 경로에서 불러오기')).toBeNull();
    expect(screen.getByText(/SCM 연결 문서 경로에 VectorCAST 로그 폴더를 등록/)).toBeInTheDocument();
  });

  it('"SCM 경로에서 불러오기" 클릭 시 비동기 잡으로 던지고 폴링한다(블로킹 회피)', async () => {
    // Arrange: 동기 4.5분 블로킹 대신 async 잡 + /api/scm/impact-job 폴링
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'job_x', status: 'queued' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: { test_rows_count: 42, ut_reports: [], it_reports: [] } } },
      });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      // Act
      fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
      await vi.advanceTimersByTimeAsync(3500);   // 폴링 1회(3s) 경과

      // Assert: async 엔드포인트 + 폴링 호출
      expect(post).toHaveBeenCalledWith(
        '/api/jenkins/report/vectorcast-rag-async',
        expect.objectContaining({ vcast_log_paths: ['U:/vc'] }),
      );
      expect(api).toHaveBeenCalledWith('/api/scm/impact-job/job_x');
    } finally {
      vi.useRealTimers();
    }
  });

  it('SCM 커버리지(단일 UT 폴더)가 로드되면 유닛테스트 패널에 UT 구문/분기/MC-DC %를 표시한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jcov' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
          test_rows_count: 42, vcast_kind: 'UT', ut_reports: ['r1'], it_reports: [],
          coverage: {
            statement: { covered: 90, total: 100, rate: 0.9 },
            branch: { covered: 40, total: 50, rate: 0.8 },
            mcdc: { covered: 8, total: 10, rate: 0.8 },
          },
        } } },
      });
      // 빌드 커버리지는 없음(coverage:null) → 로드 전 빈 상태, 로드 후 SCM 커버리지 표시.
      const result = makeAnalysisResult({
        reportData: { coverage: null, kpis: { coverage: {}, prqa: {}, code_metrics: {}, vectorcast: {}, tests: {}, scan: {}, files: {}, build: {} }, tester: {} },
        matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } },
      });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);   // 폴링 1회(3s) → 완료 → setScmVcast 플러시
      });

      // 단일 UT 폴더(vcast_kind='UT') → 유닛테스트 패널에 UT 커버리지 카드(구문/분기/MC-DC)
      expect(screen.getByText('UT 구문(Statement)')).toBeInTheDocument();
      expect(screen.getByText('90%')).toBeInTheDocument();
      expect(screen.getAllByText('UT MC/DC').length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('SCM summary_ut/summary_it가 있으면 UT/IT 통과·실패를 각 패널에 분리 표시한다(effVcast forward 회귀 가드)', async () => {
    // effVcast 리터럴이 summary_ut/summary_it/test_rows_count_it를 다시 빠뜨리면 IT pass/fail 블록이
    // 조용히 재소실되고 UT가 'UT+IT' 결합 라벨로 회귀 → 이 테스트가 그 침묵 회귀를 차단한다.
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jsplit' });
      api.mockResolvedValue({ ok: true, job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
        test_rows_count: 20, test_rows_count_ut: 12, test_rows_count_it: 8,
        ut_reports: ['u'], it_reports: ['i'],
        summary: { total: 20, passed: 18, failed: 2, skipped: 0, unknown: 0, pass_rate: 0.9 },
        summary_ut: { total: 12, passed: 11, failed: 1, skipped: 0, unknown: 0, pass_rate: 0.9167 },
        summary_it: { total: 8, passed: 7, failed: 1, skipped: 0, unknown: 0, pass_rate: 0.875 },
      } } } });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);
      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });
      // UT 패널: UT 전용 통과 라벨(결합 'UT+IT' 아님) / IT 패널: IT 전용 통과·테스트케이스 블록 부활
      expect(screen.getByText('통과 (UT)')).toBeInTheDocument();
      expect(screen.getByText('통과 (IT)')).toBeInTheDocument();
      expect(screen.getByText('테스트 케이스 (IT)')).toBeInTheDocument();
      expect(screen.queryByText('통과 (UT+IT)')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('다중 폴더 병합 coverage_ut/coverage_it를 UT/IT 패널에 분리 표시하고 합산은 표시하지 않는다', async () => {
    // vcast_kind 없는 병합 payload(coverage_ut/coverage_it 분리 + coverage 합산 동봉) 라우팅 가드.
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jmerge' });
      api.mockResolvedValue({ ok: true, job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
        test_rows_count: 30, ut_reports: ['u1', 'u2'], it_reports: ['i1'],
        coverage: { statement: { covered: 100, total: 122, rate: 0.82 } },      // 합산 — 표시 안 함
        coverage_ut: { statement: { covered: 60, total: 70, rate: 0.86 } },
        coverage_it: { statement: { covered: 40, total: 52, rate: 0.77 } },
      } } } });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/a', 'U:/b'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);
      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });
      // UT/IT 각 패널에 분리 커버리지 카드
      expect(screen.getByText('UT 구문(Statement)')).toBeInTheDocument();
      expect(screen.getByText('86%')).toBeInTheDocument();
      expect(screen.getByText('IT 구문(Statement)')).toBeInTheDocument();
      expect(screen.getByText('77%')).toBeInTheDocument();
      // 합산(UT+IT) 카드는 표시 안 함 — 접두 없는 '구문(Statement)'·합산값(82%) 부재
      expect(screen.queryByText('구문(Statement)')).toBeNull();
      expect(screen.queryByText('82%')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── SwUTCV/SwITCV 정합성 검증 (Coverage Report ↔ SUTR/SITR) ──

  it('SwUTCV 정합성 검증: 경로 입력 후 실행하면 /api/swut/consistency/check 호출 + PASS·커버리지 요약 표시', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({
      ok: true, issues: [], parse_warnings: [],
      coverage_summary: { total_tcs: 240, total_functions: 30, uncovered_functions: [], exception_statement: 3, exception_branch: 2, final_result: 'PASS' },
      sutr_summary: { total_tcs: 240, passed: 240, failed: 0, not_executed: 0 },
    });
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    fireEvent.change(screen.getByPlaceholderText('…/SwUTCV_Coverage_*.xlsx'), { target: { value: 'U:/cov.xlsx' } });
    fireEvent.change(screen.getByPlaceholderText('…/SUTR_*.xlsm'), { target: { value: 'U:/sutr.xlsm' } });
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: /정합성 비교/ })[0]);
    });

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/swut/consistency/check', { coverage_path: 'U:/cov.xlsx', sutr_path: 'U:/sutr.xlsm' },
    ));
    // ✅ PASS는 summary 접미사 + 상태줄 양쪽에 나옴(의도된 UX) → getAllByText
    expect(screen.getAllByText(/✅ PASS/).length).toBeGreaterThan(0);
    // 커버리지 결과 요약 카드(빌더 Coverage Report에서 파싱) + SUTR 합부
    expect(screen.getByText('Traceability TC')).toBeInTheDocument();
    expect(screen.getByText('미커버 함수')).toBeInTheDocument();
  });

  it('SwUTCV 정합성: issue가 있으면 FAIL + severity 배지로 표시한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({
      ok: false, parse_warnings: [],
      issues: [{ severity: 'warning', category: 'uncovered_mismatch', message: '미커버 함수 불일치 발견' }],
      coverage_summary: {}, sutr_summary: {},
    });
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    fireEvent.change(screen.getByPlaceholderText('…/SwUTCV_Coverage_*.xlsx'), { target: { value: 'U:/c.xlsx' } });
    fireEvent.change(screen.getByPlaceholderText('…/SUTR_*.xlsm'), { target: { value: 'U:/s.xlsm' } });
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: /정합성 비교/ })[0]);
    });

    await waitFor(() => expect(screen.getAllByText(/⚠️ FAIL/).length).toBeGreaterThan(0));
    expect(screen.getByText('[uncovered_mismatch]')).toBeInTheDocument();
    expect(screen.getByText('미커버 함수 불일치 발견')).toBeInTheDocument();
  });

  it('SwITCV 정합성 검증: SITR 경로로 /api/swit/consistency/check 호출', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: true, issues: [], parse_warnings: [], coverage_summary: {}, sutr_summary: {} });
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    fireEvent.change(screen.getByPlaceholderText('…/SwITCV_Coverage_*.xlsx'), { target: { value: 'U:/itcov.xlsx' } });
    fireEvent.change(screen.getByPlaceholderText('…/SITR_*.xlsm'), { target: { value: 'U:/sitr.xlsm' } });
    await act(async () => {
      // [0]=UT 실행 버튼, [1]=IT 실행 버튼 (DOM 순서)
      fireEvent.click(screen.getAllByRole('button', { name: /정합성 비교/ })[1]);
    });

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/swit/consistency/check', { coverage_path: 'U:/itcov.xlsx', sitr_path: 'U:/sitr.xlsm' },
    ));
  });

  // ── 단일 산출물 직접 파싱 (정합성 비교 없이 문서 1개만) ──

  it('SwUTCV 단일 파싱: Coverage 경로로 /api/swut/doc/summary 호출 + verdict 없이 커버리지 카드만', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({
      coverage_summary: { total_tcs: 100, total_functions: 12, uncovered_functions: ['SwUFn_3'], exception_statement: 1, exception_branch: 0, final_result: 'PASS' },
      parse_warnings: [],
    });
    const { container } = render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    fireEvent.change(screen.getByPlaceholderText('…/SwUTCV_Coverage_*.xlsx'), { target: { value: 'U:/cov.xlsx' } });
    await act(async () => {
      // [0]=UT Coverage 파싱 버튼 (IT에도 동명 버튼 존재 → DOM 순서 UT 먼저)
      fireEvent.click(screen.getAllByRole('button', { name: /이 문서 파싱 \(Coverage\)/ })[0]);
    });

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/swut/doc/summary', { path: 'U:/cov.xlsx', kind: 'coverage' },
    ));
    expect(screen.getByText('Traceability TC')).toBeInTheDocument();
    expect(screen.getByText('미커버 함수')).toBeInTheDocument();
    // hideVerdict — 정합성 비교가 아니므로 PASS/FAIL verdict 상태줄 없음
    expect(container.querySelector('.swut-consistency-status')).toBeNull();
  });

  it('SwITCV 단일 파싱: SITR 경로로 /api/swit/doc/summary {kind:report} 호출 + SITR 합부 카드', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({
      sutr_summary: { total_tcs: 30, passed: 28, failed: 2, not_executed: 0, deviated: 0, final_result: 'NG' },
      parse_warnings: [],
    });
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    fireEvent.change(screen.getByPlaceholderText('…/SITR_*.xlsm'), { target: { value: 'U:/sitr.xlsm' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /이 문서 파싱 \(SITR\)/ }));
    });

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/swit/doc/summary', { path: 'U:/sitr.xlsm', kind: 'report' },
    ));
    expect(screen.getByText('SITR TC')).toBeInTheDocument();
    expect(screen.getByText('통과')).toBeInTheDocument();
    expect(screen.getByText('실패')).toBeInTheDocument();
  });

  it('단일 파싱 결과가 비면 "추출된 결과가 없습니다" 안내를 표시한다 (hideVerdict 빈 분기)', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ coverage_summary: {}, parse_warnings: [] });
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    fireEvent.change(screen.getByPlaceholderText('…/SwUTCV_Coverage_*.xlsx'), { target: { value: 'U:/empty.xlsx' } });
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: /이 문서 파싱 \(Coverage\)/ })[0]);
    });

    await waitFor(() => expect(screen.getByText(/추출된 결과가 없습니다/)).toBeInTheDocument());
  });

  it('파싱 후 경로를 바꾸면 stale 결과 카드가 사라진다 (FE-2 _path 가드)', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({
      coverage_summary: { total_tcs: 100, uncovered_functions: [] },
      parse_warnings: [],
    });
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    const input = screen.getByPlaceholderText('…/SwUTCV_Coverage_*.xlsx');
    fireEvent.change(input, { target: { value: 'U:/cov.xlsx' } });
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: /이 문서 파싱 \(Coverage\)/ })[0]);
    });
    await waitFor(() => expect(screen.getByText('Traceability TC')).toBeInTheDocument());

    // 경로 변경 → 직전 결과의 _path와 불일치 → stale 카드 자동 숨김
    fireEvent.change(input, { target: { value: 'U:/other.xlsx' } });
    await waitFor(() => expect(screen.queryByText('Traceability TC')).toBeNull());
  });

  // ── 재진입 자동복구(스피너 고착/데이터 유실 방지) ──────────────────
  it('보존된 완료 잡이 있으면 재진입 시 클릭 없이 결과를 자동 복구한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      const job = makeJob();
      // 이전 로드에서 보존된 진행 중 job_id (새로고침/remount로 폴링 루프가 끊긴 상황 재현)
      localStorage.setItem('devops_v2_vcast_jobs', JSON.stringify({ [job.url]: { jobId: 'job_resume', startedAt: 0 } }));
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: { test_rows_count: 7502, ut_reports: [], it_reports: [] } } },
      });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });

      // Act: 클릭 없이 렌더(mount)만으로 보존 잡 폴링 → poll-first로 즉시 완료 적재
      await act(async () => {
        render(<AnalysisSection job={job} analysisResult={result} />);
        await vi.advanceTimersByTimeAsync(100);
      });

      // Assert: 보존된 잡으로 폴링했고, 새 잡(post)은 생성하지 않았으며, 결과가 적재되고, 보존 잡은 정리됨
      expect(api).toHaveBeenCalledWith('/api/scm/impact-job/job_resume');
      expect(post).not.toHaveBeenCalled();
      expect(screen.getByText('7,502')).toBeInTheDocument();
      expect(JSON.parse(localStorage.getItem('devops_v2_vcast_jobs') || '{}')).toEqual({});
    } finally {
      vi.useRealTimers();
    }
  });

  it('보존된 잡이 404(유실)면 자동복구를 조용히 중단하고 보존 항목을 제거한다', async () => {
    vi.useFakeTimers();
    try {
      const { api } = await import('../api.js');
      const job = makeJob();
      localStorage.setItem('devops_v2_vcast_jobs', JSON.stringify({ [job.url]: { jobId: 'job_gone', startedAt: 0 } }));
      api.mockRejectedValue(new Error('impact job not found'));
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });

      await act(async () => {
        render(<AnalysisSection job={job} analysisResult={result} />);
        await vi.advanceTimersByTimeAsync(100);
      });

      // 404는 error 토스트 없이 조용히 종료 + 보존 항목 제거 → 무한 재폴링 방지
      expect(mockToast).not.toHaveBeenCalledWith('error', expect.stringContaining('상태 조회 실패'));
      expect(JSON.parse(localStorage.getItem('devops_v2_vcast_jobs') || '{}')).toEqual({});
    } finally {
      vi.useRealTimers();
    }
  });

  // ── StrictMode 회귀(mountedRef cleanup race) ──────────────────────
  // 회귀 가드: StrictMode는 effect를 setup→cleanup→setup으로 이중 호출한다. mountedRef를 setup에서
  // true로 복원하지 않으면 cleanup이 false로 고정 → 폴링 while(mountedRef.current)가 안 돌아
  // impact-job 요청이 0이고 스피너가 고착된다(dev 5174에서 실제 발생한 버그).
  it('StrictMode에서도 클릭 시 impact-job 폴링이 동작하고 결과가 적재된다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'job_strict', status: 'queued' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: { test_rows_count: 99, ut_reports: [], it_reports: [] } } },
      });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(
        <StrictMode>
          <AnalysisSection job={makeJob()} analysisResult={result} />
        </StrictMode>,
      );

      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });

      // mountedRef가 cleanup으로 false 고정되면 while 루프가 안 돌아 이 호출이 발생하지 않음
      expect(api).toHaveBeenCalledWith('/api/scm/impact-job/job_strict');
      expect(screen.getByText('99')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── 빌드 Line 0% 카드 숨김(VectorCAST 커버리지와 혼동 방지) ─────────
  it('VectorCAST UT 커버리지가 있으면 표시하고 빌드 전체 Line Coverage 카드는 항상 제거한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jhide' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
          test_rows_count: 10, vcast_kind: 'UT', ut_reports: ['r1'], it_reports: [],
          coverage: { statement: { covered: 70, total: 100, rate: 0.7 }, branch: { covered: 60, total: 100, rate: 0.6 }, mcdc: { covered: 0, total: 0, rate: null } },
        } } },
      });
      // 빌드 라인커버리지 0 (rd.coverage=0) + SCM VectorCAST 경로 등록
      const result = makeAnalysisResult({
        reportData: { coverage: 0, kpis: { coverage: { line_rate: 0 }, prqa: {}, code_metrics: {}, vectorcast: {}, tests: {}, scan: {}, files: {}, build: {} }, tester: {} },
        matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } },
      });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });

      // UT 커버리지(구문 70%)는 표시되고, 빌드 전체 'Line Coverage' 카드는 제거(개요 탭과 중복)
      expect(screen.getByText('UT 구문(Statement)')).toBeInTheDocument();
      expect(screen.getByText('70%')).toBeInTheDocument();
      expect(screen.queryByText('Line Coverage')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── 복잡도 분포 막대↔산포도 토글 + 위험 사분면 ─────────────────────
  const makeVcastWithComplexity = () => ({
    test_rows_count: 5, ut_reports: [], it_reports: [],
    complexity_rows: [
      { function: 'risky_fn', file: 'mod_a', unit: 'mod_a', complexity: 40 },   // 高복잡(40>15)
      { function: 'safe_fn', file: 'mod_b', unit: 'mod_b', complexity: 3 },
    ],
    vcast_summary: {
      ut_metrics: { entries: [
        // risky: 구문 10%(低) → 高복잡+低커버 = danger
        { unit: 'mod_a', subprogram: 'risky_fn', ccn: 40,
          statements: { covered: 10, total: 100, rate: 0.1 }, branches: { covered: 1, total: 10, rate: 0.1 }, pairs: { covered: 0, total: 4, rate: 0 } },
        // safe: 구문 95%(高) → 低복잡+高커버 = success
        { unit: 'mod_b', subprogram: 'safe_fn', ccn: 3,
          statements: { covered: 95, total: 100, rate: 0.95 }, branches: { covered: 9, total: 10, rate: 0.9 }, pairs: { covered: 4, total: 4, rate: 1 } },
      ] },
    },
  });

  it('커버리지가 join되면 막대와 산포도를 한 화면에 나란히 표시하고 위험/양호를 분류한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jscat' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: makeVcastWithComplexity() } },
      });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });

      // 막대(임계 초과 요약)와 산포도(축 설명/범례)가 토글 없이 동시에 표시
      expect(screen.getByText('구간별 함수 수 (막대)')).toBeInTheDocument();
      expect(screen.getByText('복잡도 × 커버리지 (산포도)')).toBeInTheDocument();
      expect(screen.getByText(/임계\(>15\) 초과/)).toBeInTheDocument();
      expect(screen.getByText(/X=커버리지\(구문%\)/)).toBeInTheDocument();
      expect(screen.getByText(/위험 1/)).toBeInTheDocument();
      expect(screen.getByText(/양호 1/)).toBeInTheDocument();
      // 토글 버튼은 더 이상 존재하지 않음
      expect(screen.queryByRole('button', { name: '산포도' })).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('산포도 포인트에 마우스를 올리면 함수명 툴팁이 뜨고 벗어나면 사라진다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jtip' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: makeVcastWithComplexity() } },
      });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });

      // hover 전엔 툴팁 없음 → 첫 포인트(=risky_fn) hover 시 함수명 툴팁 → leave 시 제거
      expect(screen.queryByTestId('scatter-tooltip')).toBeNull();
      const circles = document.querySelectorAll('svg circle');
      expect(circles.length).toBeGreaterThan(0);
      fireEvent.mouseEnter(circles[0]);
      expect(screen.getByTestId('scatter-tooltip')).toHaveTextContent('risky_fn');
      fireEvent.mouseLeave(circles[0]);
      expect(screen.queryByTestId('scatter-tooltip')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('커버리지(vcast_summary)가 없으면 산포도 대신 안내를 띄우고 막대 분포만 표시한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jnocov' });
      // complexity_rows는 있으나 vcast_summary 없음 → join 0건 → 산포 미가용
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
          test_rows_count: 1, ut_reports: [], it_reports: [],
          complexity_rows: [{ function: 'f1', file: 'u', unit: 'u', complexity: 22 }],
        } } },
      });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });

      // 막대 분포(임계 초과 요약)는 보이고, 산포도는 미표시 + 안내 문구 표시
      expect(screen.getByText('구간별 함수 수 (막대)')).toBeInTheDocument();
      expect(screen.getByText(/임계\(>15\) 초과/)).toBeInTheDocument();
      expect(screen.queryByText(/X=커버리지\(구문%\)/)).toBeNull();
      expect(screen.getByText(/커버리지가 로드되면 표시됩니다/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── Jenkins 출처 함수레벨: 함수콜 커버리지 + 모듈→함수 드릴다운 ──
  const makeRichVcast = () => ({
    test_rows_count: 100, ut_reports: ['r1'], it_reports: ['r2'],
    coverage: { statement: { covered: 90, total: 100, rate: 0.9 }, branch: { covered: 40, total: 50, rate: 0.8 }, mcdc: { covered: 8, total: 10, rate: 0.8 } },
    vcast_summary: {
      ut_metrics: { entries: [
        { unit: 'mod_a.c', subprogram: 'fn_a', ccn: 5, statements: { covered: 8, total: 10, rate: 0.8 }, branches: { covered: 2, total: 4, rate: 0.5 } },
      ], grand_totals: {} },
      it_metrics: { entries: [
        { unit: 'mod_b.c', subprogram: 'fn_b', ccn: 3, functions: { covered: 1, total: 1, rate: 1 }, function_calls: { covered: 5, total: 10, rate: 0.5 } },
      ], grand_totals: { function_calls: { covered: 855, total: 2989, rate: 0.28 }, functions: { covered: 504, total: 1638, rate: 0.3 } } },
    },
  });

  it('빌드 vcast 있는 프로젝트는 함수레벨 로드 시 IT 함수콜 커버리지 + 모듈→함수 드릴다운을 표시한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jrich' });
      api.mockResolvedValue({ ok: true, job: { status: 'completed', result: { ok: true, source: 'jenkins', data: makeRichVcast() } } });
      // 빌드 산출물에 vcast 있음(tester.vectorcast reports) → SCM 경로 없이 '함수레벨 상세 불러오기' 노출
      const result = makeAnalysisResult({
        reportData: {
          coverage: 99,
          kpis: { coverage: { line_rate: 0.99 }, prqa: {}, code_metrics: { functions: 349 }, vectorcast: { ut: { modules: [{ name: 'mod_a.c', line_rate: 80, branch_rate: 50 }] } }, tests: {}, scan: {}, files: {}, build: {} },
          tester: { vectorcast: { ut_reports: ['r1'], it_reports: ['r2'], test_rows_count: 100 }, vectorcast_ut_line_rate: 99, vectorcast_it_line_rate: 50 },
        },
        matchedScm: { id: 's', name: 'S', linked_docs: {} },
      });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);

      // 빌드 vcast 있으면 SCM 경로 없이도 '함수레벨 상세 불러오기' 버튼
      const btn = screen.getByRole('button', { name: '함수레벨 상세 불러오기' });
      await act(async () => { fireEvent.click(btn); await vi.advanceTimersByTimeAsync(3500); });

      // IT 함수콜 커버리지(28%) + 함수 진입(30%) — 통합테스트 패널에 표시(코드메트릭 중복 카드는 제거됨)
      expect(screen.getAllByText('함수콜 커버리지').length).toBeGreaterThan(0);
      expect(screen.getAllByText('28%').length).toBeGreaterThan(0);
      // 출처 배지(Jenkins)
      expect(screen.getAllByText(/Jenkins 빌드/).length).toBeGreaterThan(0);
      // 모듈→함수 드릴다운: mod_a.c 행 클릭 → 함수 fn_a 펼침
      expect(screen.queryByText('fn_a')).toBeNull();
      fireEvent.click(screen.getByText('mod_a.c'));
      expect(screen.getByText('fn_a')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('시험 결과가 전부 미분류(unknown)면 통과/실패 0 대신 미분류 안내를 표시한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'junk' });
      // 빌드 산출물 VectorCAST가 커버리지 기준 → result=None → summary 전부 unknown
      api.mockResolvedValue({ ok: true, job: { status: 'completed', result: { ok: true, source: 'jenkins', data: {
        test_rows_count: 10, ut_reports: ['r'], it_reports: ['r'],
        summary: { total: 10, passed: 0, failed: 0, skipped: 0, unknown: 10, pass_rate: 0 },
      } } } });
      const result = makeAnalysisResult({ matchedScm: { id: 's', name: 'S', linked_docs: { vectorcast: ['U:/vc'] } } });
      render(<AnalysisSection job={makeJob()} analysisResult={result} />);
      await act(async () => {
        fireEvent.click(screen.getByText('SCM 경로에서 불러오기'));
        await vi.advanceTimersByTimeAsync(3500);
      });
      // 오해 소지의 '통과 0/실패 0/통과율 0%' 카드 대신 미분류 안내
      expect(screen.queryByText('통과 (UT+IT)')).toBeNull();
      expect(screen.getByText(/결과 미분류이며/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

// ── saModules: SCM 정적분석 응답 정규화(다중모듈 + 하위호환) ──────────────
describe('saModules', () => {
  it('modules 배열이 있으면 그대로 반환한다', () => {
    const tool = { ok: true, modules: [{ label: 'APP' }, { label: 'BOOT' }] };
    expect(saModules(tool).map((m) => m.label)).toEqual(['APP', 'BOOT']);
  });

  it('구 응답(modules 없음, ok)이면 단일 객체를 1-모듈로 감싼다', () => {
    const legacy = { ok: true, summary: { active_warnings: 3 } };
    const out = saModules(legacy);
    expect(out).toHaveLength(1);
    expect(out[0]).toBe(legacy);
  });

  it('ok=false 이거나 null/undefined면 빈 배열', () => {
    expect(saModules({ ok: false })).toEqual([]);
    expect(saModules(null)).toEqual([]);
    expect(saModules(undefined)).toEqual([]);
  });

  it('빈 modules 배열은 그대로 빈 배열(ok여도 감싸지 않음)', () => {
    expect(saModules({ ok: true, modules: [] })).toEqual([]);
  });
});
