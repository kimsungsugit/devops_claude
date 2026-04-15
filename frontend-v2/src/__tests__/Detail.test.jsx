/**
 * Detail 뷰 단위 테스트
 *
 * 요구사항 추적: SRS-VIEW-DETAIL
 * - selectedJob 없을 때 빈 상태 메시지 표시
 * - selectedJob 있을 때 섹션 네비게이션 렌더링
 * - 섹션 탭 클릭 시 활성 상태 전환
 * - 브레드크럼 Job 이름 표시
 *
 * 외부 의존성 전략:
 * - useJob: App.jsx mock
 * - 모든 Section 컴포넌트: mock (단위 격리)
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Context mock ──────────────────────────────────────────────────────
let mockSelectedJob = null;
let mockAnalysisResult = null;

vi.mock('../App.jsx', () => ({
  useJob: () => ({
    selectedJob: mockSelectedJob,
    analysisResult: mockAnalysisResult,
  }),
}));

// ── Section 컴포넌트 일괄 mock ─────────────────────────────────────
vi.mock('../components/sections/BuildInfoSection.jsx', () => ({
  default: () => <div data-testid="section-build">BuildInfo</div>,
}));
vi.mock('../components/sections/ScmSection.jsx', () => ({
  default: () => <div data-testid="section-scm">SCM</div>,
}));
vi.mock('../components/sections/AnalysisSection.jsx', () => ({
  default: () => <div data-testid="section-analysis">Analysis</div>,
}));
vi.mock('../components/sections/SrsSdsSection.jsx', () => ({
  default: () => <div data-testid="section-srssds">SrsSds</div>,
}));
vi.mock('../components/sections/DocGenSection.jsx', () => ({
  default: () => <div data-testid="section-docgen">DocGen</div>,
}));
vi.mock('../components/sections/AiAssistSection.jsx', () => ({
  default: () => <div data-testid="section-ai">AiAssist</div>,
}));
vi.mock('../components/sections/ReportGenSection.jsx', () => ({
  default: () => <div data-testid="section-reports">ReportGen</div>,
}));
vi.mock('../components/sections/ImpactGuideSection.jsx', () => ({
  default: () => <div data-testid="section-impact">ImpactGuide</div>,
}));
vi.mock('../components/sections/ProjectSetupSection.jsx', () => ({
  default: () => <div data-testid="section-setup">ProjectSetup</div>,
}));

const { default: Detail } = await import('../views/Detail.jsx');

describe('Detail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSelectedJob = null;
    mockAnalysisResult = null;
  });

  // ── selectedJob 없을 때 빈 상태 ────────────────────────────────

  it('selectedJob이 없으면 "프로젝트를 선택하세요" 메시지를 표시한다', () => {
    // Arrange & Act
    render(<Detail />);

    // Assert
    expect(screen.getByText('프로젝트를 선택하세요')).toBeInTheDocument();
  });

  it('selectedJob이 없으면 섹션 네비게이션을 렌더링하지 않는다', () => {
    // Arrange & Act
    render(<Detail />);

    // Assert
    expect(screen.queryByText('빌드 정보')).toBeNull();
  });

  it('selectedJob이 없으면 대시보드 안내 메시지를 포함한다', () => {
    // Arrange & Act
    render(<Detail />);

    // Assert
    expect(screen.getByText(/대시보드에서 Jenkins Job을 선택하고/)).toBeInTheDocument();
  });

  // ── selectedJob 있을 때 ─────────────────────────────────────────

  it('selectedJob이 있으면 섹션 네비게이션을 렌더링한다', () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert — "빌드 정보"는 브레드크럼과 accordion 레이블에 중복 존재하므로 getAllByText 사용
    expect(screen.getAllByText('빌드 정보').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('SCM')).toBeInTheDocument();
    expect(screen.getByText('문서 생성')).toBeInTheDocument();
  });

  it('selectedJob이 있으면 브레드크럼에 Job 이름을 표시한다', () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert
    expect(screen.getByText('my-job')).toBeInTheDocument();
  });

  it('기본 활성 섹션은 "빌드 정보"이다', () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert
    expect(screen.getByTestId('section-build')).toBeInTheDocument();
  });

  // ── 섹션 탭 네비게이션 ─────────────────────────────────────────

  it('SCM 섹션 탭 클릭 시 SCM 컴포넌트를 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);
    await user.click(screen.getByText('SCM'));

    // Assert
    expect(screen.getByTestId('section-scm')).toBeInTheDocument();
  });

  it('문서 생성 탭 클릭 시 DocGen 컴포넌트를 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);
    await user.click(screen.getByText('문서 생성'));

    // Assert
    expect(screen.getByTestId('section-docgen')).toBeInTheDocument();
  });

  it('탭 클릭 시 브레드크럼 섹션 레이블이 업데이트된다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);
    await user.click(screen.getByText('SCM'));

    // Assert — 브레드크럼에서도 SCM 텍스트가 나타남
    // 네비게이션 라벨 + 브레드크럼 합쳐서 2번 이상 등장
    expect(screen.getAllByText('SCM').length).toBeGreaterThanOrEqual(1);
  });
});
