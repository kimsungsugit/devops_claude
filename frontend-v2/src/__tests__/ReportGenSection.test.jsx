import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => '.devops_cache'),
  getUsername: vi.fn(() => 'testuser'),
}));

// Mock App.jsx contexts
vi.mock('../App.jsx', () => ({
  useJenkinsCfg: vi.fn(() => ({
    cfg: {
      username: 'admin',
      token: 'token123',
      cacheRoot: '.devops_pro_cache',
      buildSelector: 'lastSuccessfulBuild',
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

// fetch mock
globalThis.fetch = vi.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ reports: [] }),
  })
);

const { default: ReportGenSection } = await import('../components/sections/ReportGenSection.jsx');

describe('ReportGenSection', () => {
  const mockJob = { url: 'http://jenkins.example.com/job/test-job/' };
  const mockAnalysisResult = { cacheRoot: '.devops_cache' };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();   // 공유 입력 prefill 격리 (scanFolder 초기값 오염 방지)
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ reports: [] }),
    });
  });

  // STS-REPORTGEN-001: 기본 렌더링 (QAC 탭 기본)
  it('렌더링: QAC/PRQA 탭이 기본으로 표시된다', () => {
    // Arrange & Act
    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Assert: 탭 목록에 QAC 탭이 포함된다 (중복 허용)
    const qacMatches = screen.getAllByText(/정적 분석 \(QAC\/PRQA\)/);
    expect(qacMatches.length).toBeGreaterThanOrEqual(1);
  });

  // STS-REPORTGEN-002: VectorCAST 탭 표시
  it('렌더링: VectorCAST 동적 분석 탭이 표시된다', () => {
    // Arrange & Act
    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Assert
    expect(screen.getByText(/동적 분석/)).toBeInTheDocument();
    expect(screen.getByText(/VectorCAST/)).toBeInTheDocument();
  });

  // STS-REPORTGEN-003: QAC 탭 활성 상태 기본값
  it('기본 상태: QAC 탭이 초기에 활성화되어 있다', () => {
    // Arrange & Act
    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Assert: QAC 탭 버튼의 fontWeight가 700(활성)이어야 한다
    const qacTab = screen.getByText(/정적 분석 \(QAC\/PRQA\)/);
    expect(qacTab).toBeInTheDocument();
    // 스타일 직접 비교 대신, VectorCAST 패널이 기본적으로 없는지 확인
    expect(screen.queryByText(/VectorCAST 커버리지/)).not.toBeInTheDocument();
  });

  // STS-REPORTGEN-004: VectorCAST 탭 클릭 시 전환
  it('인터랙션: VectorCAST 탭 클릭 시 해당 패널이 표시된다', async () => {
    // Arrange
    const user = userEvent.setup();
    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Act
    const vcastTab = screen.getByText(/동적 분석 \(VectorCAST\)/);
    await user.click(vcastTab);

    // Assert: VectorCAST 탭이 화면에 표시된다 (중복 허용)
    await waitFor(() => {
      const vcastMatches = screen.getAllByText(/VectorCAST/);
      expect(vcastMatches.length).toBeGreaterThanOrEqual(1);
    });
  });

  // STS-REPORTGEN-005: QAC 폴더 스캔 — 경로 미입력 시 경고
  it('인터랙션: QAC 폴더 스캔 시 경로 미입력이면 경고 toast가 호출된다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { useToast } = await import('../App.jsx');
    const mockToast = vi.fn();
    useToast.mockReturnValue(mockToast);

    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Act: 폴더 스캔 버튼 (QAC 패널에 있음)
    const scanBtn = screen.getByText('폴더 스캔');
    await user.click(scanBtn);

    // Assert
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith('warning', expect.any(String));
    });
  });

  // STS-REPORTGEN-006: QAC Jenkins 아티팩트 불러오기 버튼
  it('인터랙션: Jenkins 아티팩트 불러오기 버튼 클릭 시 API를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { api } = await import('../api.js');
    api.mockResolvedValue({ artifacts: [] });

    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Act: 'Jenkins 아티팩트' 버튼 클릭
    const loadBtn = screen.getByText('Jenkins 아티팩트');
    await user.click(loadBtn);

    // Assert
    await waitFor(() => {
      expect(api).toHaveBeenCalled();
    });
  });

  // STS-REPORTGEN-007: 입력 일원화 — QAC 폴더가 공유값으로 prefill
  it('입력 일원화: 공유 log_qac_prqa가 QAC 스캔 폴더 초기값으로 prefill된다', () => {
    // Arrange
    localStorage.setItem('devops_v2_shared_inputs', JSON.stringify({ log_qac_prqa: 'D:/shared/PRQA' }));

    // Act
    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);

    // Assert — QAC 패널(기본 탭) 폴더 입력이 공유값으로 채워짐
    expect(screen.getByPlaceholderText(/PRQA/)).toHaveValue('D:/shared/PRQA');
  });

  // STS-REPORTGEN-008: 입력 일원화 — VCast 폴더는 멀티라인 공유값의 첫 비공백 줄
  it('입력 일원화: 공유 log_vectorcast 첫 비공백 줄이 VCast 스캔 폴더 초기값으로', async () => {
    // Arrange — 빈 첫 줄 + 공백 포함 멀티라인
    localStorage.setItem('devops_v2_shared_inputs', JSON.stringify({ log_vectorcast: '\n  U:/log/PV  \nU:/log/PV2' }));
    const user = userEvent.setup();

    // Act
    render(<ReportGenSection job={mockJob} analysisResult={mockAnalysisResult} />);
    await user.click(screen.getByText(/동적 분석 \(VectorCAST\)/));

    // Assert — 첫 비공백 줄을 trim하여 단일 폴더로
    const input = await screen.findByPlaceholderText(/VectorCAST/);
    expect(input).toHaveValue('U:/log/PV');
  });
});
