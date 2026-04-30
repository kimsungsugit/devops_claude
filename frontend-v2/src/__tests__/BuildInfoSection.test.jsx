import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => '.devops_cache'),
  buildTone: vi.fn((result) => {
    if (result === 'SUCCESS') return 'success';
    if (result === 'FAILURE') return 'danger';
    return 'neutral';
  }),
}));

// Mock App.jsx contexts
vi.mock('../App.jsx', () => ({
  useJenkinsCfg: vi.fn(() => ({
    cfg: {
      username: 'admin',
      token: 'token123',
      cacheRoot: '.devops_pro_cache',
      buildSelector: 'lastSuccessfulBuild',
      verifyTls: true,
    },
  })),
  useToast: vi.fn(() => vi.fn()),
}));

// Mock StatusBadge
vi.mock('../components/StatusBadge.jsx', () => ({
  default: ({ children, tone }) => (
    <span data-testid="status-badge" data-tone={tone}>{children}</span>
  ),
}));

const { default: BuildInfoSection } = await import('../components/sections/BuildInfoSection.jsx');

describe('BuildInfoSection', () => {
  const mockJob = { url: 'http://jenkins.example.com/job/test-job/' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // STS-BUILDINFO-001: analysisResult 없는 빈 상태 렌더링
  it('빈 상태: analysisResult가 없으면 안내 메시지가 표시된다', () => {
    // Arrange & Act
    render(<BuildInfoSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/대시보드에서 분석을 먼저 실행하세요/)).toBeInTheDocument();
  });

  // STS-BUILDINFO-002: 빌드 정보 패널 렌더링
  it('렌더링: 빌드 정보 패널 타이틀이 표시된다', () => {
    // Arrange & Act
    render(<BuildInfoSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/빌드 정보/)).toBeInTheDocument();
  });

  // STS-BUILDINFO-003: analysisResult가 있을 때 빌드 번호 표시
  it('렌더링: analysisResult가 있으면 빌드 번호가 표시된다', () => {
    // Arrange
    const analysisResult = {
      reportData: {
        build_number: 42,
        result: 'SUCCESS',
        branch: 'main',
        timestamp: 1700000000000,
        duration: 120000,
      },
    };

    // Act
    render(<BuildInfoSection job={mockJob} analysisResult={analysisResult} />);

    // Assert
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  // STS-BUILDINFO-004: 빌드 이력 섹션 렌더링
  it('렌더링: 빌드 이력 패널이 표시된다', () => {
    // Arrange & Act
    render(<BuildInfoSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/빌드 이력/)).toBeInTheDocument();
  });

  // STS-BUILDINFO-005: 빌드 이력 빈 상태
  it('빈 상태: 빌드 이력이 없을 때 안내 메시지가 표시된다', () => {
    // Arrange & Act
    render(<BuildInfoSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/불러오기 버튼을 클릭하세요/)).toBeInTheDocument();
  });

  // STS-BUILDINFO-006: 빌드 로그 섹션 렌더링
  it('렌더링: 빌드 로그 패널이 표시된다', () => {
    // Arrange & Act
    render(<BuildInfoSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/빌드 로그/)).toBeInTheDocument();
  });

  // STS-BUILDINFO-007: 불러오기 버튼 클릭 시 API 호출
  it('인터랙션: 불러오기 버튼 클릭 시 builds API를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post: mockPost } = await import('../api.js');
    mockPost.mockResolvedValue({ builds: [] });

    render(<BuildInfoSection job={mockJob} analysisResult={null} />);

    // 자동 로딩이 완료될 때까지 대기 (마운트 시 자동 loadBuilds 호출)
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalled();
    });
    mockPost.mockClear();

    // Act: 로딩 완료 후 버튼을 클릭
    const loadBtn = await screen.findByText('불러오기');
    await user.click(loadBtn);

    // Assert
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/api/jenkins/builds', expect.objectContaining({
        job_url: mockJob.url,
      }));
    });
  });

  // STS-BUILDINFO-008: 빌드 단계 표시 (steps 있을 때)
  it('렌더링: analysisResult에 steps가 있으면 빌드 단계 패널이 표시된다', () => {
    // Arrange
    const analysisResult = {
      reportData: {
        build_number: 10,
        result: 'SUCCESS',
        kpis: {
          build: {
            steps: [
              { name: 'Checkout', status: 'SUCCESS' },
              { name: 'Build', status: 'SUCCESS' },
            ],
          },
        },
      },
    };

    // Act
    render(<BuildInfoSection job={mockJob} analysisResult={analysisResult} />);

    // Assert
    expect(screen.getByText(/빌드 단계/)).toBeInTheDocument();
    expect(screen.getByText('Checkout')).toBeInTheDocument();
  });
});
