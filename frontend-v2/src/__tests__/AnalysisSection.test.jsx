/**
 * AnalysisSection 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-SECTION-ANALYSIS
 * - "코드 커버리지" 패널 렌더링
 * - "VectorCAST 테스트" 패널 렌더링
 * - "코드 메트릭" 패널 렌더링
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

const { default: AnalysisSection } = await import('../components/sections/AnalysisSection.jsx');

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

  it('"코드 커버리지" 패널 제목을 렌더링한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('코드 커버리지')).toBeInTheDocument();
  });

  it('"VectorCAST 테스트" 패널 제목을 렌더링한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('VectorCAST 테스트')).toBeInTheDocument();
  });

  it('"코드 메트릭" 패널 제목을 렌더링한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('코드 메트릭')).toBeInTheDocument();
  });

  it('"함수 복잡도 상세" 패널 제목을 렌더링한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('함수 복잡도 상세')).toBeInTheDocument();
  });

  // ── 커버리지 데이터 표시 ──────────────────────────────────────────

  it('line_rate가 있을 때 Line Coverage 카드를 표시한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('Line Coverage')).toBeInTheDocument();
    expect(screen.getByText('85%')).toBeInTheDocument();
  });

  it('branch_rate가 있을 때 Branch Coverage 카드를 표시한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('Branch Coverage')).toBeInTheDocument();
    expect(screen.getByText('72%')).toBeInTheDocument();
  });

  // ── 빈 데이터 처리 ────────────────────────────────────────────────

  it('analysisResult가 null이면 오류 없이 렌더링한다', () => {
    // Arrange & Act & Assert — 오류 없이 렌더링되어야 함
    expect(() => {
      render(<AnalysisSection job={makeJob()} analysisResult={null} />);
    }).not.toThrow();
  });

  it('analysisResult가 null이어도 "코드 커버리지" 패널을 표시한다', () => {
    // Arrange & Act
    render(<AnalysisSection job={makeJob()} analysisResult={null} />);

    // Assert
    expect(screen.getByText('코드 커버리지')).toBeInTheDocument();
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

  it('SCM 커버리지가 로드되면 코드 커버리지 패널에 구문/분기/MC-DC %를 표시한다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jcov' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
          test_rows_count: 42, ut_reports: [], it_reports: [],
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

      expect(screen.getByText('구문(Statement)')).toBeInTheDocument();
      expect(screen.getByText('90%')).toBeInTheDocument();
      expect(screen.getByText('MC/DC')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
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
  it('VectorCAST 커버리지가 있고 빌드 Line이 0%면 혼동되는 빌드 Line Coverage 카드를 숨긴다', async () => {
    vi.useFakeTimers();
    try {
      const { post, api } = await import('../api.js');
      post.mockResolvedValue({ ok: true, job_id: 'jhide' });
      api.mockResolvedValue({
        ok: true,
        job: { status: 'completed', result: { ok: true, source: 'cloudium', data: {
          test_rows_count: 10, ut_reports: [], it_reports: [],
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

      // VectorCAST 구문(Statement)은 표시되고, 오해 소지의 빌드 'Line Coverage' 0% 카드는 숨김
      expect(screen.getByText('구문(Statement)')).toBeInTheDocument();
      expect(screen.getByText('70%')).toBeInTheDocument();
      expect(screen.queryByText('Line Coverage')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
