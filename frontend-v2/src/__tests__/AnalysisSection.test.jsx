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
import { render, screen, waitFor } from '@testing-library/react';
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
});
