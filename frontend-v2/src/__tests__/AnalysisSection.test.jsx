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
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
});
