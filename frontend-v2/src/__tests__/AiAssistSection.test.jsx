import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  postSse: vi.fn(),
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

  // STS-AIASSIST-006: AI 추론 모드(기본) — 전송 시 /api/chat/stream(SSE) 호출
  it('인터랙션: 기본 AI 추론 모드에서 전송 시 /api/chat/stream(SSE)을 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post, postSse } = await import('../api.js');
    post.mockResolvedValue(null);
    postSse.mockResolvedValue(undefined);

    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    const textarea = screen.getByPlaceholderText(/질문을 입력하세요/);
    const sendBtn = screen.getByText('전송');

    // Act
    await user.type(textarea, '빌드 결과를 알려주세요');
    expect(sendBtn).not.toBeDisabled();

    await user.click(sendBtn);

    // Assert
    await waitFor(() => {
      expect(postSse).toHaveBeenCalledWith(
        '/api/chat/stream',
        expect.objectContaining({ question: '빌드 결과를 알려주세요' }),
        expect.anything(),
      );
    });
  });

  // STS-AIASSIST-006b: 빠른 검색 모드 전환 — /api/jenkins/rag/query 호출 (폴백 유지)
  it('인터랙션: 빠른 검색 모드로 전환 후 전송 시 /api/jenkins/rag/query를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post } = await import('../api.js');
    post.mockResolvedValue({ answer: '검색 결과' });

    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Act
    await user.click(screen.getByText('빠른 검색'));
    const textarea = screen.getByPlaceholderText(/질문을 입력하세요/);
    await user.type(textarea, '실패 테스트');
    await user.click(screen.getByText('전송'));

    // Assert
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/api/jenkins/rag/query', expect.objectContaining({
        query: '실패 테스트',
      }));
    });
  });

  // STS-AIASSIST-007: 새 대화 버튼
  it('인터랙션: 메시지 전송 후 새 대화 버튼이 나타난다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post, postSse } = await import('../api.js');
    post.mockResolvedValue(null);
    postSse.mockResolvedValue(undefined);

    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    const textarea = screen.getByPlaceholderText(/질문을 입력하세요/);
    await user.type(textarea, '질문');
    await user.click(screen.getByText('전송'));

    // Assert
    await waitFor(() => {
      expect(screen.getByText('새 대화')).toBeInTheDocument();
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

  // STS-AIASSIST-009: 이력 버튼 클릭 시 서버 대화 목록을 불러온다
  it('인터랙션: 이력 버튼 클릭 시 대화 목록 API를 호출하고 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post, api } = await import('../api.js');
    post.mockResolvedValue(null);
    api.mockResolvedValue({ conversations: [{ thread_id: 't1', title: '이전 대화', message_count: 4 }] });

    render(<AiAssistSection job={mockJob} analysisResult={null} />);

    // Act
    await user.click(screen.getByText('이력'));

    // Assert
    await waitFor(() => {
      expect(api).toHaveBeenCalledWith('/api/chat/history?limit=30');
    });
    expect(await screen.findByText('이전 대화')).toBeInTheDocument();
  });

  // STS-AIASSIST-010: graph_node 이벤트 → 진행 stepper 단계/경과시간 렌더
  it('인터랙션: graph_node_started/finished 이벤트로 진행 stepper가 단계와 경과시간을 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post, postSse } = await import('../api.js');
    post.mockResolvedValue(null);
    // onEvent 를 동기 발사하고, finally 가 stepStatus 를 비우지 않도록 pending 유지
    postSse.mockImplementation((_path, _body, opts) => {
      opts.onEvent('message', { type: 'started' });
      opts.onEvent('message', { type: 'graph_node_started', payload: { node: 'classify_intent' } });
      opts.onEvent('message', { type: 'graph_node_finished', payload: { node: 'classify_intent', elapsed_ms: 123 } });
      opts.onEvent('message', { type: 'graph_node_started', payload: { node: 'build_context' } });
      return new Promise(() => {}); // 스트리밍 유지
    });

    render(<AiAssistSection job={mockJob} analysisResult={null} />);
    const textarea = screen.getByPlaceholderText(/질문을 입력하세요/);
    await user.type(textarea, '진행 표시 확인');

    // Act
    await user.click(screen.getByText('전송'));

    // Assert: 5단계 라벨 + 완료 단계 경과시간 + 진행 상태 role
    await waitFor(() => {
      expect(screen.getByText('질문 분석')).toBeInTheDocument();
    });
    expect(screen.getByText('컨텍스트')).toBeInTheDocument();
    expect(screen.getByText('모델')).toBeInTheDocument();
    expect(screen.getByText('답변')).toBeInTheDocument();
    expect(screen.getByText('123ms')).toBeInTheDocument(); // classify_intent 완료 경과
  });
});
