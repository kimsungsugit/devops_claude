import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => '.devops_cache'),
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

const { default: AiAssistSection } = await import('../components/sections/AiAssistSection.jsx');

describe('AiAssistSection', () => {
  const mockJob = { url: 'http://jenkins.example.com/job/test-job/' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // STS-AIASSIST-001: 기본 렌더링
  it('렌더링: AI 어시스턴트 패널이 표시된다', async () => {
    // Arrange
    const { post } = await import('../api.js');
    post.mockResolvedValue({ stats: { total: 100 } });

    // Act
    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/AI 어시스턴트/)).toBeInTheDocument();
  });

  // STS-AIASSIST-002: 빈 메시지 상태의 안내 텍스트
  it('빈 상태: 메시지가 없을 때 안내 텍스트가 표시된다', async () => {
    // Arrange
    const { post } = await import('../api.js');
    post.mockResolvedValue(null);

    // Act
    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/무엇이든 물어보세요/)).toBeInTheDocument();
    });
  });

  // STS-AIASSIST-003: RAG 지식 베이스 상태 표시
  it('렌더링: RAG 지식 베이스 섹션이 표시된다', async () => {
    // Arrange
    const { post } = await import('../api.js');
    post.mockResolvedValue(null);

    // Act
    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/RAG 지식 베이스/)).toBeInTheDocument();
  });

  // STS-AIASSIST-004: 질문 입력 textarea 렌더링
  it('렌더링: 질문 입력 textarea가 표시된다', async () => {
    // Arrange
    const { post } = await import('../api.js');
    post.mockResolvedValue(null);

    // Act
    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByPlaceholderText(/질문을 입력하세요/)).toBeInTheDocument();
  });

  // STS-AIASSIST-005: 전송 버튼 비활성 상태 (입력 없음)
  it('빈 상태: 입력이 없으면 전송 버튼이 비활성화된다', async () => {
    // Arrange
    const { post } = await import('../api.js');
    post.mockResolvedValue(null);

    // Act
    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Assert
    const sendBtn = screen.getByText('전송');
    expect(sendBtn).toBeDisabled();
  });

  // STS-AIASSIST-006: 입력 후 전송 버튼 활성화 및 API 호출
  it('인터랙션: 질문 입력 후 전송 버튼이 활성화되고 API를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post } = await import('../api.js');
    post.mockResolvedValue({ answer: '테스트 답변입니다.' });

    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    const textarea = screen.getByPlaceholderText(/질문을 입력하세요/);
    const sendBtn = screen.getByText('전송');

    // Act
    await user.type(textarea, '빌드 결과를 알려주세요');
    expect(sendBtn).not.toBeDisabled();

    await user.click(sendBtn);

    // Assert
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/api/jenkins/rag/query', expect.objectContaining({
        query: '빌드 결과를 알려주세요',
      }));
    });
  });

  // STS-AIASSIST-007: 대화 초기화 버튼
  it('인터랙션: 메시지 전송 후 대화 초기화 버튼이 나타난다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post } = await import('../api.js');
    post.mockResolvedValue({ answer: '답변' });

    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    const textarea = screen.getByPlaceholderText(/질문을 입력하세요/);
    await user.type(textarea, '질문');
    await user.click(screen.getByText('전송'));

    // Assert
    await waitFor(() => {
      expect(screen.getByText('대화 초기화')).toBeInTheDocument();
    });
  });

  // STS-AIASSIST-008: RAG 상태 확인 API 자동 호출
  it('마운트: RAG 상태 확인 API가 자동으로 호출된다', async () => {
    // Arrange
    const { post } = await import('../api.js');
    post.mockResolvedValue({ stats: { total: 50 } });

    // Act
    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Assert
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/api/local/rag/status', {});
    });
  });
});
